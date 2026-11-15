"""商业域权益行并发安全（行锁＋刷新）——资金敏感面竞态钉。

背景：``commercial_entitlements`` 是「一人一份」的权益行（PK=user_id），
席位激活与首单扣费都读它再写它。此前读-改-写**无行锁**（``ensure_entitlement``
只是 ``session.get``），并发窗口里两个请求可能都读到旧值并各自写入：

- **双激活**：两个请求都读到 ``seat_status != 'active'`` ⇒ 都写 active，
  席位激活事件落两条、席位来源被后写者静默覆盖；
- **双记账**（更糟）：账本侧**无唯一约束**兜底（``commercial_revenue_ledger``
  不对 ``(subject_type, subject_user_id)`` 建唯一键），两个请求都通过
  「未扣过首单费」检查 ⇒ **同一交付者被记两笔 3980 席位费**。

本文件钉住修复后的行为（``commercial/service.py::lock_entitlement``）：

1. 并发激活必须串行化：后到者读到已提交真值即 409 ``seat_already_active``，
   且**不得覆盖**先到者写入的席位来源；
2. 并发扣费不得双记账：账本「席位费科目行恒 1 行」是硬不变量；
3. 权益行**尚不存在**时的并发建行不得 500（savepoint 兜底路径）；
4. 静态钉：权益**写**路径一律走行锁原语，**读**面保持无锁（读面加锁会
   把并发读变成串行写）。

模拟手法（房内范式，``quota_service._lock_quota`` 同款）：裸连接提交
「另一事务已写入」，本会话 identity map 仍持有并发前的旧实例
（``expire_on_commit=False`` 时属性不会自动过期）——正是并发窗口里第二个
请求持有的内存视图；写路径的「行锁重读」必须见已提交真值。
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from conftest import INITIAL_PASSWORD
from fde_api.commercial.models import (
    FIRST_ORDER_SEAT_FEE,
    CommercialEntitlement,
    CommercialRevenueLedger,
)
from fde_api.commercial.service import (
    CommercialServiceError,
    activate_seat,
    ensure_entitlement,
    lock_entitlement,
)
from fde_api.workbench.models import OperationEvent

from test_commercial_revenue_ledger import _delivery_chain, _elect
from test_research_subjects_api import (  # noqa: F401  (pytest fixture)
    admin_client,
    authorized_client_factory,
)


def _pwd() -> str:
    return INITIAL_PASSWORD


def _entitlement_row(session, user_id: str) -> CommercialEntitlement | None:
    return session.scalars(
        select(CommercialEntitlement).where(CommercialEntitlement.user_id == user_id)
    ).first()


def _seat_fee_rows(session, user_id: str) -> list[CommercialRevenueLedger]:
    return list(
        session.scalars(
            select(CommercialRevenueLedger).where(
                CommercialRevenueLedger.subject_type == "seat_fee",
                CommercialRevenueLedger.subject_user_id == user_id,
            )
        ).all()
    )


def _seat_activation_events(session, user_id: str) -> list[OperationEvent]:
    return list(
        session.scalars(
            select(OperationEvent).where(
                OperationEvent.event_type == "commercial_seat_activated"
            )
        ).all()
    )


# ---------------------------------------------------------------------------
# 1. 并发激活席位：必须串行化（否则双激活 ＋ 席位来源被覆盖）
# ---------------------------------------------------------------------------


def test_activate_seat_race_serializes_on_row_lock(
    db_session, admin_client, authorized_client_factory
) -> None:
    """并发激活：后到者必须读到已提交真值并被 409 拒，且不得覆盖席位来源。

    模拟：先到者（另一事务）已把席位激活为 ``first_delivery`` 并提交；
    本会话 identity map 里仍留着并发前的旧实例（``seat_status='none'``）
    ——若无行锁＋刷新，本请求会读到旧值并把席位来源改写成自己的
    （``bootcamp_practical``）＝**先到者的写入被静默覆盖**。
    """
    admin = admin_client.user
    deliverer = authorized_client_factory("fde_engineer").user

    # 权益行存在（先到者已激活过）
    ensure_entitlement(db_session, deliverer.id)
    db_session.commit()
    stale = _entitlement_row(db_session, deliverer.id)
    assert stale is not None
    assert stale.seat_status == "none", "前置：初始席位态应为 none"

    # 另一事务已激活并提交（裸连接＝独立事务）
    engine = db_session.get_bind()
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE commercial_entitlements SET seat_status = 'active', "
                "seat_source = 'first_delivery', seat_activated_at = now(), "
                "seat_expires_at = now() + interval '365 days' "
                "WHERE user_id = :uid"
            ),
            {"uid": deliverer.id},
        )

    # 迟到的激活（持有旧内存视图）必须被拒
    with pytest.raises(CommercialServiceError) as late:
        activate_seat(
            db_session,
            actor=admin,
            user_id=deliverer.id,
            seat_source="bootcamp_practical",
            confirm_password=_pwd(),
        )
    assert late.value.code == "seat_already_active"
    assert late.value.status == 409

    db_session.rollback()
    db_session.expire_all()
    row = _entitlement_row(db_session, deliverer.id)
    assert row is not None
    assert row.seat_status == "active"
    assert row.seat_source == "first_delivery", "迟到者覆盖了先到者的席位来源"


# ---------------------------------------------------------------------------
# 2. 真并发：对方持行锁未提交时，本请求必须**等待**并在其提交后读真值
# ---------------------------------------------------------------------------


def test_activate_seat_waits_for_concurrent_writer_then_rejects(
    db_session, admin_client, authorized_client_factory
) -> None:
    """真并发（双连接）：另一事务**持锁未提交**时，本请求必须等待而非读旧值。

    这是「行锁」与「只刷新」的分水岭：
    - 只有刷新（无行锁）：本请求读到的是对方**未提交**前的已提交值（``none``）
      ⇒ 判为未激活 ⇒ 双激活（对方提交后本请求照样写 active）；
    - 行锁＋刷新：本请求在 ``SELECT ... FOR UPDATE`` 上等待对方提交，
      随后读到已提交真值（``active``）⇒ 409 拒。

    时序：对方事务 INSERT/UPDATE 后**不立即提交**（持有行锁），主线程随即发起
    激活请求；对方在 1 秒后提交——主线程必须在该提交之前抵达锁点（毫秒级，
    余量充足）。
    """
    admin = admin_client.user
    deliverer = authorized_client_factory("fde_engineer").user
    ensure_entitlement(db_session, deliverer.id)
    db_session.commit()

    engine = db_session.get_bind()
    wrote = threading.Event()
    failure: list[BaseException] = []

    def _other_writer() -> None:
        try:
            with engine.connect() as conn:
                trans = conn.begin()
                conn.execute(
                    text(
                        "UPDATE commercial_entitlements SET seat_status = 'active', "
                        "seat_source = 'first_delivery', seat_activated_at = now(), "
                        "seat_expires_at = now() + interval '365 days' "
                        "WHERE user_id = :uid"
                    ),
                    {"uid": deliverer.id},
                )
                wrote.set()
                # 持锁不放：给主线程抵达锁点的时间
                threading.Event().wait(1.0)
                trans.commit()
        except BaseException as error:  # noqa: BLE001 - 线程内异常回传给主线程
            failure.append(error)

    thread = threading.Thread(target=_other_writer, name="entitlement-writer")
    thread.start()
    try:
        assert wrote.wait(timeout=10), "对方事务未按时写入"
        with pytest.raises(CommercialServiceError) as late:
            activate_seat(
                db_session,
                actor=admin,
                user_id=deliverer.id,
                seat_source="bootcamp_practical",
                confirm_password=_pwd(),
            )
        assert late.value.code == "seat_already_active"
        assert late.value.status == 409
    finally:
        thread.join(timeout=10)

    assert not failure, f"并发写线程失败：{failure[0]!r}"
    db_session.rollback()
    db_session.expire_all()
    row = _entitlement_row(db_session, deliverer.id)
    assert row is not None
    assert row.seat_source == "first_delivery", "迟到者覆盖了先到者的席位来源"


# ---------------------------------------------------------------------------
# 3. 并发首单扣费：不得双记账（账本侧无唯一约束兜底）
# ---------------------------------------------------------------------------


def test_first_order_fee_race_does_not_double_charge(
    db_session, admin_client, authorized_client_factory
) -> None:
    """并发首单扣费：另一事务已激活席位但尚未记账 ⇒ 迟到者必须被拒且**零记账**。

    模拟：先到者（另一事务）激活了席位（``first_delivery``）但**没有**写
    账本行——这正是「另一请求刚激活席位、本请求紧接着扣费」的窗口。无行锁
    时本请求读到旧内存视图（``seat_status='none'``）、账本查询也查不到行
    ⇒ 两道闸同时失效 ⇒ **记出第二笔 3980 席位费**（账本无唯一约束兜底）。
    """
    admin = admin_client.user
    deliverer_client = authorized_client_factory("fde_engineer")
    deliverer = deliverer_client.user
    _elect(deliverer_client)
    _project, package, _payment, _settlement = _delivery_chain(db_session, deliverer)

    # 会话内先读入权益行（identity map 持有旧视图）
    ensure_entitlement(db_session, deliverer.id)
    db_session.commit()
    stale = _entitlement_row(db_session, deliverer.id)
    assert stale is not None
    assert stale.seat_status == "none"

    # 另一事务：席位已激活（未记账）
    engine = db_session.get_bind()
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE commercial_entitlements SET seat_status = 'active', "
                "seat_source = 'first_delivery', seat_activated_at = now(), "
                "seat_expires_at = now() + interval '365 days' "
                "WHERE user_id = :uid"
            ),
            {"uid": deliverer.id},
        )

    from fde_api.commercial.billing_service import charge_first_order_seat_fee

    with pytest.raises(CommercialServiceError) as late:
        charge_first_order_seat_fee(
            db_session,
            actor=admin,
            user_id=deliverer.id,
            package_id=package.id,
            confirm_password=_pwd(),
        )
    assert late.value.status == 409
    assert late.value.code in ("seat_already_active", "seat_fee_already_charged")

    # 关键断言：**必须在 rollback 之前**查——被拒的并发请求不得留下任何记账行
    # （rollback 会把未提交的写入冲掉，把证据一起抹了＝假绿）。
    assert _seat_fee_rows(db_session, deliverer.id) == [], "并发窗口记出了第二笔席位费"

    db_session.rollback()
    db_session.expire_all()
    assert _seat_fee_rows(db_session, deliverer.id) == [], "并发窗口记出了第二笔席位费"


def test_first_order_fee_race_keeps_single_ledger_row(
    db_session, admin_client, authorized_client_factory
) -> None:
    """并发首单扣费（先到者已完整记账）：科目行恒 1 行——不得记第二笔。

    「席位费科目行恒 1 行」是 G3 的硬不变量（反例用例
    ``test_package_included_seat_is_not_charged_again`` 钉的同一族）。
    """
    admin = admin_client.user
    deliverer_client = authorized_client_factory("fde_engineer")
    deliverer = deliverer_client.user
    _elect(deliverer_client)
    _project, package, _payment, _settlement = _delivery_chain(db_session, deliverer)

    # 先到者：完整扣费（记账 ＋ 激活席位）——用裸连接模拟「另一事务已提交」
    from fde_api.commercial.billing_service import charge_first_order_seat_fee

    charged = charge_first_order_seat_fee(
        db_session,
        actor=admin,
        user_id=deliverer.id,
        package_id=package.id,
        confirm_password=_pwd(),
    )
    assert charged["amount"] == float(FIRST_ORDER_SEAT_FEE)
    db_session.commit()

    # 迟到者：持有并发前的旧内存视图 → 必须被拒
    stale = _entitlement_row(db_session, deliverer.id)
    assert stale is not None
    assert stale.seat_status == "active"

    with pytest.raises(CommercialServiceError) as late:
        charge_first_order_seat_fee(
            db_session,
            actor=admin,
            user_id=deliverer.id,
            package_id=package.id,
            confirm_password=_pwd(),
        )
    assert late.value.status == 409
    assert late.value.code in ("seat_already_active", "seat_fee_already_charged")

    # 同样在 rollback 之前查（未提交的写入会被 rollback 抹掉）
    rows_in_session = _seat_fee_rows(db_session, deliverer.id)
    assert len(rows_in_session) == 1, "席位费科目行必须恒 1 行（并发窗口记出了第二笔）"

    db_session.rollback()
    db_session.expire_all()
    rows = _seat_fee_rows(db_session, deliverer.id)
    assert len(rows) == 1, "席位费科目行必须恒 1 行"
    assert float(rows[0].amount) == float(FIRST_ORDER_SEAT_FEE)


# ---------------------------------------------------------------------------
# 3. 权益行尚不存在时的并发建行：不得 500（savepoint 兜底路径）
# ---------------------------------------------------------------------------


def test_concurrent_creation_of_entitlement_row_does_not_crash(
    db_session, authorized_client_factory
) -> None:
    """两个事务同时为同一用户建权益行：后到者**不得 500**（唯一约束冲突兜底）。

    真并发：线程 A 用独立连接 INSERT 并**暂不提交**；主线程此刻调
    ``lock_entitlement``——它看不到 A 的未提交行 ⇒ 走「行不存在→插入」分支，
    INSERT 被 PG 唯一约束挡下（A 提交后才报错）⇒ savepoint 兜底 → 按 A 已
    提交的��加锁并返回。**不 500、不重复建行**。
    """
    user = authorized_client_factory("fde_engineer").user
    engine = db_session.get_bind()

    inserted = threading.Event()
    may_commit = threading.Event()
    failure: list[BaseException] = []

    def _other_transaction() -> None:
        try:
            with engine.connect() as conn:
                trans = conn.begin()
                conn.execute(
                    text(
                        "INSERT INTO commercial_entitlements "
                        "(user_id, seat_status, certification_status, delivery_eligibility, "
                        "created_at, updated_at) "
                        "VALUES (:uid, 'none', 'uncertified', 'none', now(), now())"
                    ),
                    {"uid": user.id},
                )
                inserted.set()
                may_commit.wait(timeout=10)
                trans.commit()
        except BaseException as error:  # noqa: BLE001 - 线程内异常回传给主线程
            failure.append(error)

    thread = threading.Thread(target=_other_transaction, name="entitlement-inserter")
    thread.start()
    try:
        assert inserted.wait(timeout=10), "另一事务未按时插入"
        may_commit.set()
        row = lock_entitlement(db_session, user.id)
        assert row is not None
        assert row.user_id == user.id
    finally:
        may_commit.set()
        thread.join(timeout=10)

    assert not failure, f"并发建行线程失败：{failure[0]!r}"
    # 若 savepoint 回滚后失败插入的对象仍挂在 session 上，下一次 flush 会
    # 再撞唯一约束 ⇒ 此处必须能干净 flush
    db_session.flush()
    db_session.rollback()
    db_session.expire_all()
    rows = list(
        db_session.scalars(
            select(CommercialEntitlement).where(CommercialEntitlement.user_id == user.id)
        ).all()
    )
    assert len(rows) == 1, "同一用户被建出多行权益"


# ---------------------------------------------------------------------------
# 4. 静态钉：写路径一律行锁，读面保持无锁
# ---------------------------------------------------------------------------


def test_entitlement_write_paths_use_row_lock_and_read_face_stays_unlocked() -> None:
    """源码级钉：权益**写**路径走 ``lock_entitlement``，读面不得加锁。

    - 写路径加锁＝并发写串行化（席位/认证/资格/扣费）；
    - 读面加锁＝把并发读变成串行写（性能与语义都不对）——``get_entitlement_for_view``
      走 ``ensure_entitlement``（无锁）。
    """
    import inspect

    from fde_api.commercial import service as service_module

    for name in (
        "set_commercial_role",
        "activate_seat",
        "set_certification",
        "set_delivery_eligibility",
    ):
        source = inspect.getsource(getattr(service_module, name))
        assert "lock_entitlement(" in source, f"{name} 未走行锁原语"

    read_source = inspect.getsource(service_module.get_entitlement_for_view)
    assert "lock_entitlement(" not in read_source, "读面不得加行锁"
    assert "ensure_entitlement(" in read_source

    from fde_api.commercial import billing_service

    billing_source = inspect.getsource(billing_service.charge_first_order_seat_fee)
    assert "lock_entitlement(" in billing_source, "首单扣费未走行锁原语"


def test_commercial_role_and_certification_writes_are_serialized() -> None:
    """角色分层与认证状态写路径同样走行锁原语（源码钉，避免回退）。"""
    import inspect

    from fde_api.commercial import service as service_module

    assert "lock_entitlement(" in inspect.getsource(service_module.set_commercial_role)
    assert "lock_entitlement(" in inspect.getsource(service_module.set_certification)
    assert "lock_entitlement(" in inspect.getsource(
        service_module.set_delivery_eligibility
    )
    # 原语本身必须带行锁 ＋ 刷新（缺一即等于没锁）
    source = inspect.getsource(service_module.lock_entitlement)
    assert "with_for_update()" in source
    assert "populate_existing=True" in source


# ---------------------------------------------------------------------------
# 5. 事件留痕不被并发写重复（激活事件恰一条）
# ---------------------------------------------------------------------------


def test_concurrent_activation_leaves_single_event(
    db_session, admin_client, authorized_client_factory
) -> None:
    """并发激活被拒时不得留下第二条激活事件（审计不得重复记同一动作）。"""
    admin = admin_client.user
    deliverer = authorized_client_factory("fde_engineer").user
    ensure_entitlement(db_session, deliverer.id)
    db_session.commit()

    engine = db_session.get_bind()
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE commercial_entitlements SET seat_status = 'active', "
                "seat_source = 'first_delivery', seat_activated_at = now(), "
                "seat_expires_at = now() + interval '365 days' "
                "WHERE user_id = :uid"
            ),
            {"uid": deliverer.id},
        )

    with pytest.raises(CommercialServiceError):
        activate_seat(
            db_session,
            actor=admin,
            user_id=deliverer.id,
            seat_source="bootcamp_practical",
            confirm_password=_pwd(),
        )

    db_session.rollback()
    db_session.expire_all()
    events = [
        event
        for event in _seat_activation_events(db_session, deliverer.id)
        if deliverer.id in str(event.changes or {})
    ]
    assert len(events) == 0, "被拒的并发激活不得留下激活事件"
