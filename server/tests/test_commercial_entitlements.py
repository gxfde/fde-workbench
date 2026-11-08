"""商业化 G1：权益四分与角色分层（T-04/T-05，ADR-001/002/006 验收钉）。

钉住七件事：
1. 角色值域 R1–R4：任何以 L 开头的角色值一律 400（ADR-006 §2.1——代码与
   迁移中不出现以 L 开头的角色枚举值）；
2. **四类权益互不推导**（ADR-002 §2.2）：角色/席位/认证/交付资格/培训五个
   写原语各自只触碰自己的列组——若有人把四类塞进单一「会员等级」字段或
   加推导式，这些反例用例转红（≥3 条反例，任务书 §5 验收）；
3. `delivery_eligibility` 不覆盖 `fde_profiles.status`；唯一同步点=席位激活
   pending→active 单向升级（suspended/active 不动，档案缺失跳过不创建）；
4. 高风险写闸：admin 门 + 密码确认（缺/错一律拒绝），审计事件带
   request_id/前后状态且不含密码（敏感键与实现双保险）；
5. 权限：读面本人/admin，他人 403；未知用户 404；
6. 对外编号映射闭包（ladder.py 唯一转换入口）+ 静态钉：商业包与迁移文件
   中带引号的 L 编号字面量只允许出现在 ladder.py；
7. 迁移升级/兼容：head 上两表列与 CHECK 齐备；downgrade 至**本迁移的父
   版本**（显式 revision，非 ``-1``——后续迁移叠在头上时 ``-1`` 会退错版本）
   双表消失，回 head 恢复（additive 往返）；治理面不进 api_catalog。

"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from uuid import uuid4

from alembic import command
from sqlalchemy import inspect as sql_inspect
from sqlalchemy import select

from fde_api.commercial.ladder import EXTERNAL_LADDER_CODES, external_ladder_code
from fde_api.commercial.models import CommercialEntitlement
from fde_api.control.api_catalog import CATALOG
from fde_api.dispatch.models import FdeProfile
from fde_api.workbench.models import OperationEvent

from conftest import INITIAL_PASSWORD
from test_research_subjects_api import (  # noqa: F401  (pytest fixture)
    admin_client,
    authorized_client_factory,
    leader_client,
)

SERVER_SRC = Path(__file__).resolve().parent.parent / "src" / "fde_api"
MIGRATION_FILE = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "versions"
    / "e9c4a1f7b3d2_commercial_g1_entitlements.py"
)


def _pwd() -> str:
    return INITIAL_PASSWORD


def _role_url(user_id: str) -> str:
    return f"/api/v1/admin/commercial/users/{user_id}/role"


def _seat_url(user_id: str) -> str:
    return f"/api/v1/admin/commercial/users/{user_id}/seat-activation"


def _cert_url(user_id: str) -> str:
    return f"/api/v1/admin/commercial/users/{user_id}/certification"


def _elig_url(user_id: str) -> str:
    return f"/api/v1/admin/commercial/users/{user_id}/delivery-eligibility"


def _training_url(user_id: str) -> str:
    return f"/api/v1/admin/commercial/users/{user_id}/training"


def _read_url(user_id: str) -> str:
    return f"/api/v1/commercial/entitlements/{user_id}"


# ---------------------------------------------------------------------------
# 1. 角色值域：R1–R4 闭集，L 值一律拒绝（ADR-006）
# ---------------------------------------------------------------------------


def test_role_value_domain_rejects_l_prefixed_values(admin_client, authorized_client_factory) -> None:
    """角色值域闸：'L1'–'L4'（交付能力等级的值）作为角色分层一律 400——
    角色分层不落 L 编号；R 系合法；NULL=清空为未分层。"""
    target = authorized_client_factory("viewer").user
    for bad in ("L0", "L1", "L2", "L3", "L4", "R5", "r3", ""):
        denied = admin_client.post(
            _role_url(target.id), json={"role": bad, "confirm_password": _pwd()}
        )
        assert denied.status_code == 400, (bad, denied.get_json())
        assert denied.json["error"]["code"] == "invalid_commercial_role"

    ok = admin_client.post(
        _role_url(target.id), json={"role": "R3", "confirm_password": _pwd()}
    )
    assert ok.status_code == 200, ok.get_data(as_text=True)
    assert ok.json["data"]["entitlement"]["commercial_role"] == "R3"
    assert ok.json["data"]["changed"] is True

    # 平台权限角色不受影响（正交裁决：users.role 保持 viewer）
    assert target.role == "viewer"

    clear = admin_client.post(
        _role_url(target.id), json={"role": None, "confirm_password": _pwd()}
    )
    assert clear.status_code == 200
    assert clear.json["data"]["entitlement"]["commercial_role"] is None


# ---------------------------------------------------------------------------
# 2. 四类权益互不推导（≥3 反例：单一会员等级字段/派生式实现会转红）
# ---------------------------------------------------------------------------


def _prime_all(admin_client, user_id: str) -> None:
    assert (
        admin_client.post(_role_url(user_id), json={"role": "R3", "confirm_password": _pwd()}).status_code
        == 200
    )
    assert (
        admin_client.post(
            _cert_url(user_id),
            json={"certified": True, "source": "simulation_run:s1", "confirm_password": _pwd()},
        ).status_code
        == 200
    )
    assert (
        admin_client.post(
            _seat_url(user_id),
            json={"seat_source": "first_delivery", "confirm_password": _pwd()},
        ).status_code
        == 200
    )
    assert (
        admin_client.post(
            _elig_url(user_id), json={"eligibility": "eligible", "confirm_password": _pwd()}
        ).status_code
        == 200
    )


def test_role_change_touches_only_role(admin_client, authorized_client_factory) -> None:
    """反例①：改角色分层不动席位/认证/交付资格——「按角色推导权益」会转红。"""
    target = authorized_client_factory("viewer").user
    _prime_all(admin_client, target.id)
    before = admin_client.get(_read_url(target.id)).json["data"]["entitlement"]

    changed = admin_client.post(
        _role_url(target.id), json={"role": "R2", "confirm_password": _pwd()}
    )
    assert changed.status_code == 200
    after = changed.json["data"]["entitlement"]
    assert after["commercial_role"] == "R2"
    # 其余三类权益逐键不变（单一会员等级字段会在此翻车）
    assert after["subscription"] == before["subscription"]
    assert after["certification"] == before["certification"]
    assert after["delivery_eligibility"] == before["delivery_eligibility"]


def test_seat_activation_does_not_touch_certification_or_role(
    admin_client, authorized_client_factory
) -> None:
    """反例②：席位激活不动认证/角色/交付资格——「有席位即认证」派生式转红；
    同步只发生在 fde_profiles.status（pending→active 单向）。"""
    target = authorized_client_factory("viewer").user
    admin_client.post(
        _cert_url(target.id),
        json={"certified": False, "confirm_password": _pwd()},
    )
    activated = admin_client.post(
        _seat_url(target.id),
        json={"seat_source": "bootcamp_practical", "confirm_password": _pwd()},
    )
    assert activated.status_code == 200
    data = activated.json["data"]["entitlement"]
    assert data["subscription"]["seat_status"] == "active"
    assert data["subscription"]["seat_source"] == "bootcamp_practical"
    # 认证与角色零变化（ADR-002：认证是培训出口，不是席位的派生）
    assert data["certification"]["status"] == "uncertified"
    assert data["commercial_role"] is None
    assert data["delivery_eligibility"] == "none"

    # 已激活再激活 → 409（不静默换源/续期）
    dup = admin_client.post(
        _seat_url(target.id),
        json={"seat_source": "first_delivery", "confirm_password": _pwd()},
    )
    assert dup.status_code == 409
    assert dup.json["error"]["code"] == "seat_already_active"


def test_certification_change_does_not_touch_seat_or_role(
    admin_client, authorized_client_factory
) -> None:
    """反例③：认证翻转不动席位/角色——「认证即席位」派生式转红。

    顺序设计：认证发生在**席位未激活**时（seat=none），任何「认证顺手
    激活席位」的派生式都会让 subscription 从 none 可见翻转（变异可辨）。
    """
    target = authorized_client_factory("viewer").user
    before = admin_client.get(_read_url(target.id)).json["data"]["entitlement"]
    assert before["subscription"]["seat_status"] == "none"

    certified = admin_client.post(
        _cert_url(target.id),
        json={"certified": True, "source": "simulation_run:s2", "confirm_password": _pwd()},
    )
    assert certified.status_code == 200
    after = certified.json["data"]["entitlement"]
    assert after["certification"]["status"] == "certified"
    assert after["certification"]["source"] == "simulation_run:s2"
    # 席位仍是 none（变异敏感点：派生式会把 none 翻成 active 在此转红）
    assert after["subscription"]["seat_status"] == "none"
    assert after["subscription"]["seat_source"] is None
    assert after["commercial_role"] == before["commercial_role"]
    assert after["delivery_eligibility"] == before["delivery_eligibility"]

    # 反向再断言一次：已认证后再激活席位，认证不被席位动作触碰
    activated = admin_client.post(
        _seat_url(target.id),
        json={"seat_source": "first_delivery", "confirm_password": _pwd()},
    )
    assert activated.status_code == 200
    assert activated.json["data"]["entitlement"]["certification"]["status"] == "certified"
    assert activated.json["data"]["entitlement"]["commercial_role"] is None


def test_training_revocation_leaves_seat_active(
    admin_client, authorized_client_factory, db_session
) -> None:
    """反例④：培训权益（1:N 行）撤销不影响订阅权益——培训与订阅互不推导。"""
    target = authorized_client_factory("viewer").user
    admin_client.post(
        _seat_url(target.id),
        json={"seat_source": "bootcamp_mentorship", "confirm_password": _pwd()},
    )
    granted = admin_client.post(
        _training_url(target.id),
        json={"item_type": "mentoring", "confirm_password": _pwd(), "note": "陪跑营报名"},
    )
    assert granted.status_code == 200, granted.get_data(as_text=True)
    training_id = granted.json["data"]["training"]["id"]

    revoked = admin_client.post(
        f"{_training_url(target.id)}/{training_id}/revoke",
        json={"confirm_password": _pwd()},
    )
    assert revoked.status_code == 200
    assert revoked.json["data"]["training"]["status"] == "revoked"

    view = admin_client.get(_read_url(target.id)).json["data"]
    assert view["entitlement"]["subscription"]["seat_status"] == "active"
    assert all(t["status"] == "revoked" for t in view["trainings"])

    # 值域闸：非法 item_type 400
    bad = admin_client.post(
        _training_url(target.id), json={"item_type": "seat", "confirm_password": _pwd()}
    )
    assert bad.status_code == 400
    assert bad.json["error"]["code"] == "invalid_training_item_type"


# ---------------------------------------------------------------------------
# 3. fde_profiles.status 同步：唯一跨域点（pending→active 单向）
# ---------------------------------------------------------------------------


def test_seat_activation_syncs_pending_profile_only(
    admin_client, authorized_client_factory, db_session
) -> None:
    """席位激活：pending 档案升 active（事件记 fde_profile_status_sync）；
    suspended 不动；无档案行跳过不创建（档案创建归 dispatch 认证申请流）。"""
    pending_user = authorized_client_factory("viewer").user
    suspended_user = authorized_client_factory("viewer").user
    plain_user = authorized_client_factory("viewer").user
    db_session.add(FdeProfile(user_id=pending_user.id, status="pending"))
    db_session.add(FdeProfile(user_id=suspended_user.id, status="suspended"))
    db_session.commit()

    ok = admin_client.post(
        _seat_url(pending_user.id),
        json={"seat_source": "first_delivery", "confirm_password": _pwd()},
    )
    assert ok.status_code == 200
    db_session.expire_all()  # expire_on_commit=False：跨会话更新须显式失效缓存
    profile = db_session.get(FdeProfile, pending_user.id)
    assert profile.status == "active"

    event = db_session.scalars(
        select(OperationEvent)
        .where(OperationEvent.event_type == "commercial_seat_activated")
        .order_by(OperationEvent.occurred_at.desc())
    ).first()
    assert event is not None
    assert event.changes["fde_profile_status_sync"] == {"from": "pending", "to": "active"}
    assert event.changes["before"]["seat_status"] == "none"

    kept = admin_client.post(
        _seat_url(suspended_user.id),
        json={"seat_source": "first_delivery", "confirm_password": _pwd()},
    )
    assert kept.status_code == 200
    db_session.expire_all()
    assert db_session.get(FdeProfile, suspended_user.id).status == "suspended"

    missing = admin_client.post(
        _seat_url(plain_user.id),
        json={"seat_source": "first_delivery", "confirm_password": _pwd()},
    )
    assert missing.status_code == 200
    assert db_session.get(FdeProfile, plain_user.id) is None

    # delivery_eligibility 写原语零触碰 fde_profiles.status（并存裁决）
    elig = admin_client.post(
        _elig_url(plain_user.id),
        json={"eligibility": "eligible", "confirm_password": _pwd()},
    )
    assert elig.status_code == 200
    assert db_session.get(FdeProfile, plain_user.id) is None


# ---------------------------------------------------------------------------
# 4. 高风险写闸：admin 门 + 密码确认；审计事件带 request_id 且无密码
# ---------------------------------------------------------------------------


def test_admin_gate_rejects_non_admin(leader_client, authorized_client_factory) -> None:
    target = authorized_client_factory("viewer").user
    for url, payload in (
        (_role_url(target.id), {"role": "R1"}),
        (_seat_url(target.id), {"seat_source": "first_delivery"}),
        (_cert_url(target.id), {"certified": True}),
        (_elig_url(target.id), {"eligibility": "eligible"}),
        (_training_url(target.id), {"item_type": "training"}),
    ):
        denied = leader_client.post(url, json=payload)
        assert denied.status_code == 403, url
        assert denied.json["error"]["code"] == "commercial_admin_required"


def test_password_confirmation_required_on_every_write(
    admin_client, authorized_client_factory
) -> None:
    target = authorized_client_factory("viewer").user
    missing = admin_client.post(_role_url(target.id), json={"role": "R1"})
    assert missing.status_code == 400

    wrong = admin_client.post(
        _role_url(target.id), json={"role": "R1", "confirm_password": "wrong-pass"}
    )
    assert wrong.status_code == 403
    assert wrong.json["error"]["code"] == "invalid_password"

    for url, payload in (
        (_seat_url(target.id), {"seat_source": "first_delivery"}),
        (_cert_url(target.id), {"certified": True}),
        (_elig_url(target.id), {"eligibility": "eligible"}),
        (_training_url(target.id), {"item_type": "training"}),
    ):
        denied = admin_client.post(url, json=payload)
        assert denied.status_code == 400, url
        denied_wrong = admin_client.post(url, json={**payload, "confirm_password": "nope"})
        assert denied_wrong.status_code == 403, url


def test_audit_events_carry_request_id_and_never_the_password(
    admin_client, authorized_client_factory, db_session
) -> None:
    target = authorized_client_factory("viewer").user
    admin_client.post(_role_url(target.id), json={"role": "R4", "confirm_password": _pwd()})
    admin_client.post(
        _seat_url(target.id),
        json={"seat_source": "first_delivery", "confirm_password": _pwd()},
    )
    events = db_session.scalars(
        select(OperationEvent)
        .where(
            OperationEvent.target_type == "user",
            OperationEvent.event_type.in_(
                ["commercial_role_changed", "commercial_seat_activated"]
            ),
        )
        .order_by(OperationEvent.occurred_at.asc())
    ).all()
    assert [e.event_type for e in events] == [
        "commercial_role_changed",
        "commercial_seat_activated",
    ]
    for event in events:
        assert isinstance(event.changes.get("request_id"), str)
        assert event.changes["target_user_id"] == target.id
        assert event.project_id is None
        assert event.actor_user_id is not None
    # 密码不落事件（实现上从未写入 changes；敏感键正则是第二道保险）
    serialized = repr([e.changes for e in events])
    assert INITIAL_PASSWORD not in serialized
    assert "confirm_password" not in serialized


# ---------------------------------------------------------------------------
# 5. 读面权限与懒初始化缺省
# ---------------------------------------------------------------------------


def test_read_permission_self_admin_other_and_unknown(
    admin_client, leader_client, authorized_client_factory
) -> None:
    mine = authorized_client_factory("viewer")
    self_read = mine.get(_read_url(mine.user.id))
    assert self_read.status_code == 200
    data = self_read.json["data"]
    assert data["entitlement"]["commercial_role"] is None
    assert data["entitlement"]["subscription"]["seat_status"] == "none"
    assert data["entitlement"]["certification"]["status"] == "uncertified"
    assert data["entitlement"]["delivery_eligibility"] == "none"
    assert data["external_ladder_code"] is None
    assert data["trainings"] == []

    other = mine.get(_read_url(admin_client.user.id))
    assert other.status_code == 403
    assert other.json["error"]["code"] == "commercial_entitlement_forbidden"

    admin_view = admin_client.get(_read_url(mine.user.id))
    assert admin_view.status_code == 200

    unknown = admin_client.get(_read_url(f"ghost-{uuid4().hex}"))
    assert unknown.status_code == 404


# ---------------------------------------------------------------------------
# 6. 对外编号映射闭包 + 静态钉（唯一转换入口）
# ---------------------------------------------------------------------------


def _entitlement(role, seat_status, seat_source, certified) -> CommercialEntitlement:
    return CommercialEntitlement(
        user_id=f"u-{uuid4().hex}",
        commercial_role=role,
        seat_status=seat_status,
        seat_source=seat_source,
        certification_status="certified" if certified else "uncertified",
    )


def test_external_ladder_mapping_closure() -> None:
    """映射表闭包：任意 (角色, 席位, 认证) 组合的推导都落在拍板表内；
    未分层/R1 → None；R4 恒 L4；R2 按席位来源分档；R3 认证∧席位=独立态。"""
    roles = (None, "R1", "R2", "R3", "R4")
    seat_statuses = ("none", "active")
    seat_sources = (None, "first_delivery", "bootcamp_practical", "bootcamp_mentorship")
    for role in roles:
        for seat_status in seat_statuses:
            for seat_source in seat_sources:
                for certified in (False, True):
                    row = _entitlement(role, seat_status, seat_source, certified)
                    code = external_ladder_code(row)
                    assert code is None or code in EXTERNAL_LADDER_CODES
                    if role in (None, "R1"):
                        assert code is None
                    if role == "R4":
                        assert code == "L4"
                    if role == "R2":
                        if seat_status == "active" and seat_source == "bootcamp_mentorship":
                            assert code == "L3"
                        elif seat_status == "active" and seat_source == "bootcamp_practical":
                            assert code == "L2"
                        else:
                            assert code is None
                    if role == "R3":
                        if certified and seat_status == "active":
                            assert code == "L1"
                        else:
                            assert code == "L0"


def test_no_quoted_l_codes_outside_ladder_module() -> None:
    """静态钉（ADR-006 §2.3）：商业包与迁移文件中，带引号的 L 编号字面量
    只允许出现在 ladder.py（唯一转换入口）——散落换算即转红。"""
    quoted_l_code = r"('L0'|'L1'|'L2'|'L3'|'L4'|\"L0\"|\"L1\"|\"L2\"|\"L3\"|\"L4\")"
    offenders: list[str] = []
    for path in sorted(SERVER_SRC.glob("commercial/**/*.py")):
        text = path.read_text(encoding="utf-8")
        if path.name == "ladder.py":
            continue
        if re.search(quoted_l_code, text):
            offenders.append(str(path))
    if MIGRATION_FILE.exists():
        migration_text = MIGRATION_FILE.read_text(encoding="utf-8")
        if re.search(quoted_l_code, migration_text):
            offenders.append(str(MIGRATION_FILE))
    assert offenders == []


def test_commercial_governance_face_not_in_api_catalog() -> None:
    """治理面不进 api_catalog（AI 不可调用；dispatch admin 面同款边界）。"""
    offenders = [key for key in CATALOG if "commercial" in key]
    assert offenders == []


# ---------------------------------------------------------------------------
# 7. 迁移升级/兼容（additive 往返）
# ---------------------------------------------------------------------------


def test_migration_roundtrip_and_head_shape(engine, alembic_config) -> None:
    """head 上两表列/CHECK 齐备；downgrade -1 双表消失；回 head 恢复。"""
    inspector = sql_inspect(engine)
    tables = set(inspector.get_table_names())
    assert "commercial_entitlements" in tables
    assert "training_entitlements" in tables

    ent_cols = {c["name"] for c in inspector.get_columns("commercial_entitlements")}
    assert {
        "user_id",
        "commercial_role",
        "seat_status",
        "seat_source",
        "seat_activated_at",
        "seat_expires_at",
        "certification_status",
        "certification_source",
        "delivery_eligibility",
    } <= ent_cols
    ent_checks = {
        c["name"] for c in inspector.get_check_constraints("commercial_entitlements")
    }
    assert {
        "ck_commercial_entitlements_role",
        "ck_commercial_entitlements_seat_status",
        "ck_commercial_entitlements_seat_source",
        "ck_commercial_entitlements_certification",
        "ck_commercial_entitlements_delivery_eligibility",
    } <= ent_checks

    train_cols = {c["name"] for c in inspector.get_columns("training_entitlements")}
    assert {
        "id",
        "user_id",
        "item_type",
        "status",
        "purchased_at",
        "valid_from",
        "valid_until",
        "granted_by_user_id",
        "note",
    } <= train_cols

    command.downgrade(alembic_config, "e7c4a9d2f6b8")
    inspector = sql_inspect(engine)
    tables = set(inspector.get_table_names())
    assert "commercial_entitlements" not in tables
    assert "training_entitlements" not in tables

    command.upgrade(alembic_config, "head")
    inspector = sql_inspect(engine)
    assert "commercial_entitlements" in set(inspector.get_table_names())
    assert "training_entitlements" in set(inspector.get_table_names())


def test_service_write_primitives_are_independent_of_each_other() -> None:
    """源码级钉：每个写原语只写自己的列组（互不推导的静态面）。

    set_commercial_role 函数体内不得给席位/认证/交付资格列赋值；
    set_certification 不得给席位/角色列赋值；以此类推（ADR-002 §2.2）。
    """
    from fde_api.commercial import service

    forbidden = {
        "set_commercial_role": ("seat_status", "seat_source", "certification_status", "delivery_eligibility"),
        "set_certification": ("seat_status", "seat_source", "commercial_role", "delivery_eligibility"),
        "set_delivery_eligibility": ("seat_status", "seat_source", "commercial_role", "certification_status"),
    }
    for func_name, columns in forbidden.items():
        source = inspect.getsource(getattr(service, func_name))
        for column in columns:
            assert f"{column} =" not in source, (
                f"{func_name} 不应写 {column}（四类权益互不推导，ADR-002）"
            )
