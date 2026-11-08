"""商业化 G2：企业免费额度（T-07，ADR-004/ADR-007 验收钉）。

钉住八件事：
1. 主体键=统一社会信用代码规范化（mod-31 校验位）——大小写/空格/连字符
   归一；校验失败 400 ``invalid_subject_key``（ADR-004 §1.1）；
2. **额度键挂主体而非账号**（任务书 §6 验收核心）：同主体重复授予幂等
   （changed=False、行数恒 1）；换账号启动 409 ``quota_bound_to_other_account``
   ——「额度按账号计」的实现（按用户建行/允许改绑）在这些断言上转红；
3. **六项交付物恰好全真**才算完成：缺失/未真逐键点名 409、多余键 400
   （闭集拒绝）——「未齐不算完成」（ADR-004 §1.5）；
4. 企业确认=绑定账号本人、必须发生在完成之后；admin 不得代企业确认；
5. 体验档上限触限即受限（used >= cap 拒绝）；上限数值禁止无上限/非正整数
   （ADR-004 §1.8 占位缺省但结构完整）；
6. 高风险写双闸（授予/完成=admin+密码确认）+ 事件带 request_id 且无密码
   （ADR-007）；
7. 读面权限四态（绑定账号/admin/他人 403/未知 404）；
8. 免费边界元数据读面（六项/七项不免费/三档无数值/占位上限标注/三入口
   注册表）+ 治理面不进 api_catalog；迁移 additive 往返（downgrade 至**本
   迁移的父版本**显式 revision——``-1`` 会被后续叠在头上的迁移顶掉）。
"""

from __future__ import annotations

import pytest
from alembic import command
from sqlalchemy import inspect as sql_inspect
from sqlalchemy import select, text

from fde_api.commercial.models import (
    EXPERIENCE_LIMITS,
    FREE_DIAGNOSIS_DELIVERABLES,
    FREE_EXCLUSIONS,
    FREE_TRIAL_ENTRIES,
    EnterpriseFreeQuota,
)
from fde_api.commercial.quota_service import (
    CommercialServiceError,
    assert_entry_scope_allows,
    check_experience_limit,
    normalize_subject_key,
    start_diagnosis,
)
from fde_api.control.api_catalog import CATALOG
from fde_api.workbench.models import OperationEvent

from conftest import INITIAL_PASSWORD
from test_research_subjects_api import (  # noqa: F401  (pytest fixture)
    admin_client,
    authorized_client_factory,
    leader_client,
)

VALID_USCC = "91350100M000100Y43"  # 公开样本（mod-31 校验通过）
BAD_CHECKSUM_USCC = "91350100M000100Y44"  # 仅末位改 4（校验位必败）


def _pwd() -> str:
    return INITIAL_PASSWORD


def _grant_url() -> str:
    return "/api/v1/admin/commercial/enterprise-quota/grant"


def _quota_url(uscc: str) -> str:
    return f"/api/v1/commercial/enterprise-quota/{uscc}"


def _complete_url(uscc: str) -> str:
    return f"/api/v1/admin/commercial/enterprise-quota/{uscc}/complete"


def _all_deliverables() -> dict[str, bool]:
    return {key: True for key in FREE_DIAGNOSIS_DELIVERABLES}


def _grant(admin_client, uscc: str = VALID_USCC, name: str = "测试企业甲"):
    return admin_client.post(
        _grant_url(),
        json={"subject_key": uscc, "display_name": name, "confirm_password": _pwd()},
    )


# ---------------------------------------------------------------------------
# 1. 主体键规范化与校验位
# ---------------------------------------------------------------------------


def test_subject_key_normalization_and_checksum_rejection(admin_client) -> None:
    normalized = normalize_subject_key(" 91350100m000100y-43 ")
    assert normalized == VALID_USCC

    for bad in (
        BAD_CHECKSUM_USCC,  # 校验位错
        "91350100M000100Y4",  # 17 位
        "I1350100M000100Y43",  # 非法字符 I（字符集排除 I/O/S/V/Z）
        None,
        12345,
    ):
        try:
            normalize_subject_key(bad)
        except CommercialServiceError as error:
            assert error.code == "invalid_subject_key", bad
        else:  # pragma: no cover - 防恒真
            raise AssertionError(f"expected rejection: {bad!r}")

    api_bad = admin_client.post(
        _grant_url(),
        json={"subject_key": BAD_CHECKSUM_USCC, "display_name": "x", "confirm_password": _pwd()},
    )
    assert api_bad.status_code == 400
    assert api_bad.json["error"]["code"] == "invalid_subject_key"


# ---------------------------------------------------------------------------
# 2. 高风险写双闸（ADR-007）
# ---------------------------------------------------------------------------


def test_grant_requires_admin_and_password(leader_client, admin_client) -> None:
    denied = leader_client.post(
        _grant_url(),
        json={"subject_key": VALID_USCC, "display_name": "x", "confirm_password": _pwd()},
    )
    assert denied.status_code == 403
    assert denied.json["error"]["code"] == "commercial_admin_required"

    # admin 自身也必须带密码：缺失 400 / 错误 403
    missing = admin_client.post(
        _grant_url(), json={"subject_key": VALID_USCC, "display_name": "x"}
    )
    assert missing.status_code == 400
    wrong = admin_client.post(
        _grant_url(),
        json={"subject_key": VALID_USCC, "display_name": "x", "confirm_password": "wrong-pass"},
    )
    assert wrong.status_code == 403
    assert wrong.json["error"]["code"] == "invalid_password"


def test_grant_idempotent_per_subject_never_second_row(
    admin_client, authorized_client_factory, db_session
) -> None:
    """同主体重复授予幂等（一次一主体）；**额度键挂主体**——若实现按账号
    计（per-user 行/可重复建），本断言转红（任务书 §6 变异验收面）。"""
    first = _grant(admin_client)
    assert first.status_code == 200, first.get_data(as_text=True)
    assert first.json["data"]["changed"] is True
    assert first.json["data"]["quota"]["state"] == "granted"

    # 不同 admin 再授予同主体：changed=False、绝不新建
    second_admin = authorized_client_factory("admin")
    again = second_admin.post(
        _grant_url(),
        json={"subject_key": VALID_USCC.lower(), "display_name": "改名尝试", "confirm_password": _pwd()},
    )
    assert again.status_code == 200
    assert again.json["data"]["changed"] is False
    assert again.json["data"]["quota"]["subject_display_name"] == "测试企业甲"

    from fde_api.commercial.models import EnterpriseFreeQuota, EnterpriseQuotaSubject

    assert db_session.scalar(select(EnterpriseFreeQuota.subject_key).where(
        EnterpriseFreeQuota.subject_key == VALID_USCC
    )) == VALID_USCC
    assert len(db_session.scalars(select(EnterpriseQuotaSubject.subject_key)).all()) >= 1


# ---------------------------------------------------------------------------
# 3. 启动绑定与换账号不重置
# ---------------------------------------------------------------------------


def test_start_binds_account_blocks_other_accounts_and_restart(
    admin_client, authorized_client_factory
) -> None:
    user_a = authorized_client_factory("viewer")
    user_b = authorized_client_factory("viewer")
    assert _grant(admin_client).status_code == 200

    started = user_a.post(f"{_quota_url(VALID_USCC)}/start", json={})
    assert started.status_code == 200
    assert started.json["data"]["quota"]["state"] == "in_progress"
    assert started.json["data"]["quota"]["bound_user_id"] == user_a.user.id

    # 换账号不得重新开始（反例面：按账号计/可改绑的实现在此转红）
    blocked = user_b.post(f"{_quota_url(VALID_USCC)}/start", json={})
    assert blocked.status_code == 409
    assert blocked.json["error"]["code"] == "quota_bound_to_other_account"

    # 本人重启幂等
    again = user_a.post(f"{_quota_url(VALID_USCC)}/start", json={})
    assert again.status_code == 200
    assert again.json["data"]["changed"] is False


def test_start_race_serializes_on_row_lock(
    admin_client, authorized_client_factory, db_session
) -> None:
    """并发启动必须串行化（行锁＋刷新）——否则两个账号可同时读到 ``granted``
    并各自写入绑定账号＝**额度被重发**（换账号不重置的硬不变量被击穿）。

    模拟：裸连接提交「另一账号已启动」，本会话的 identity map 仍持有
    并发前的旧实例（``expire_on_commit=False`` 属性不过期）——正是并发窗口
    里第二个请求持有的内存视图；写路径的「行锁重读」必须见已提交真值。
    """
    user_a = authorized_client_factory("viewer")
    user_b = authorized_client_factory("viewer")
    assert _grant(admin_client).status_code == 200

    # 会话内先读入额度行（identity map 持有旧视图）
    stale = db_session.get(EnterpriseFreeQuota, VALID_USCC)
    assert stale is not None
    assert stale.state == "granted"

    # 裸连接模拟「另一账号已提交启动」
    engine = db_session.get_bind()
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE enterprise_free_quota SET state = 'in_progress', "
                "bound_user_id = :uid, bound_at = now() WHERE subject_key = :sk"
            ),
            {"uid": user_b.user.id, "sk": VALID_USCC},
        )

    # 迟到的启动（持有旧内存视图）必须被重读后的真值拒
    with pytest.raises(CommercialServiceError) as late:
        start_diagnosis(db_session, actor=user_a.user, subject_key_raw=VALID_USCC)
    assert late.value.code == "quota_bound_to_other_account"
    assert late.value.status == 409

    db_session.rollback()
    db_session.expire_all()
    fresh = db_session.get(EnterpriseFreeQuota, VALID_USCC)
    assert fresh.bound_user_id == user_b.user.id  # 迟到者不得覆盖绑定
    assert fresh.state == "in_progress"


# ---------------------------------------------------------------------------
# 4. 六项交付物完成判据
# ---------------------------------------------------------------------------


def test_completion_requires_exactly_six_true(
    admin_client, authorized_client_factory, db_session
) -> None:
    user = authorized_client_factory("viewer")
    assert _grant(admin_client).status_code == 200
    assert user.post(f"{_quota_url(VALID_USCC)}/start", json={}).status_code == 200

    # 五键 → 点名缺失
    five = {k: True for k in list(FREE_DIAGNOSIS_DELIVERABLES)[:5]}
    missing_one = admin_client.post(
        _complete_url(VALID_USCC), json={"deliverables": five, "confirm_password": _pwd()}
    )
    assert missing_one.status_code == 409
    assert missing_one.json["error"]["code"] == "deliverables_incomplete"
    assert "next_steps" in missing_one.json["error"]["message"]

    # 六键但一个 False → 仍点名
    one_false = dict(_all_deliverables())
    one_false["diagnosis_report"] = False
    false_case = admin_client.post(
        _complete_url(VALID_USCC), json={"deliverables": one_false, "confirm_password": _pwd()}
    )
    assert false_case.status_code == 409

    # 多余键 → 400 闭集拒绝
    extra = dict(_all_deliverables())
    extra["free_unlimited_service"] = True
    extra_case = admin_client.post(
        _complete_url(VALID_USCC), json={"deliverables": extra, "confirm_password": _pwd()}
    )
    assert extra_case.status_code == 400

    # 恰好六键全真 → 完成
    ok = admin_client.post(
        _complete_url(VALID_USCC), json={"deliverables": _all_deliverables(), "confirm_password": _pwd()}
    )
    assert ok.status_code == 200, ok.get_data(as_text=True)
    assert ok.json["data"]["quota"]["state"] == "completed"
    assert ok.json["data"]["quota"]["completed_at"] is not None

    # 完成后再启动 → 409（终态无重启）
    restart = user.post(f"{_quota_url(VALID_USCC)}/start", json={})
    assert restart.status_code == 409
    assert restart.json["error"]["code"] == "quota_completed"

    # 完成前置闸：granted 态（未启动）直接完成 → 409 quota_not_in_progress
    uscc2 = _another_uscc(VALID_USCC)
    assert normalize_subject_key(uscc2) == uscc2
    assert _grant(admin_client, uscc=uscc2, name="测试企业丙").status_code == 200
    second = admin_client.post(
        _complete_url(uscc2), json={"deliverables": _all_deliverables(), "confirm_password": _pwd()}
    )
    assert second.status_code == 409
    assert second.json["error"]["code"] == "quota_not_in_progress"


# ---------------------------------------------------------------------------
# 5. 企业确认：绑定账号本人、必须完成之后、admin 不得代确认
# ---------------------------------------------------------------------------


def test_confirm_rules(admin_client, authorized_client_factory) -> None:
    user = authorized_client_factory("viewer")
    other = authorized_client_factory("viewer")
    assert _grant(admin_client).status_code == 200

    # 未完成不可确认
    early = user.post(f"{_quota_url(VALID_USCC)}/confirm", json={})
    assert early.status_code == 409
    assert early.json["error"]["code"] == "quota_not_completed"

    assert user.post(f"{_quota_url(VALID_USCC)}/start", json={}).status_code == 200
    assert (
        admin_client.post(
            _complete_url(VALID_USCC),
            json={"deliverables": _all_deliverables(), "confirm_password": _pwd()},
        ).status_code
        == 200
    )

    # 他人（非绑定账号）不可确认——admin 亦然（不代企业确认）
    for outsider in (other, admin_client):
        denied = outsider.post(f"{_quota_url(VALID_USCC)}/confirm", json={})
        assert denied.status_code == 403
        assert denied.json["error"]["code"] == "quota_confirm_forbidden"

    # 绑定账号确认 → 终态留痕；重复确认幂等
    ok = user.post(f"{_quota_url(VALID_USCC)}/confirm", json={})
    assert ok.status_code == 200
    assert ok.json["data"]["quota"]["enterprise_confirmed_at"] is not None
    again = user.post(f"{_quota_url(VALID_USCC)}/confirm", json={})
    assert again.status_code == 200
    assert again.json["data"]["changed"] is False


# ---------------------------------------------------------------------------
# 6. 体验档上限（触限即受限）
# ---------------------------------------------------------------------------


def test_three_trial_entries_isolated() -> None:
    """三入口隔离（任务书 §6 验收「创业者不能取到企业真实商机」）。

    企业＝真实业务问题／创业者＝模拟体验／交付者＝脱敏模拟项目考核——
    非企业入口取用 ``real_business`` 即拒（403）。
    """
    assert set(FREE_TRIAL_ENTRIES) == {"enterprise", "founder", "deliverer"}
    assert FREE_TRIAL_ENTRIES["enterprise"]["scope"] == "real_business"
    assert FREE_TRIAL_ENTRIES["enterprise"]["subject_key_required"] is True
    assert FREE_TRIAL_ENTRIES["founder"]["subject_key_required"] is False
    assert FREE_TRIAL_ENTRIES["deliverer"]["subject_key_required"] is False

    for entry in ("founder", "deliverer"):
        try:
            assert_entry_scope_allows(entry, "real_business")
        except CommercialServiceError as error:
            assert error.code == "trial_entry_scope_forbidden", entry
            assert error.status == 403
        else:  # pragma: no cover - 防恒真
            raise AssertionError(f"{entry} must not access real_business")

    # 各入口自有域放行
    assert assert_entry_scope_allows("enterprise", "real_business") == "real_business"
    assert assert_entry_scope_allows("founder", "simulation") == "simulation"
    assert (
        assert_entry_scope_allows("deliverer", "sanitized_simulation")
        == "sanitized_simulation"
    )

    for bad_entry in ("guest", "", None, 7):
        try:
            assert_entry_scope_allows(bad_entry, "simulation")
        except CommercialServiceError as error:
            assert error.code == "invalid_trial_entry"
        else:  # pragma: no cover
            raise AssertionError(f"expected rejection: {bad_entry!r}")


def test_experience_limit_exceeded_at_cap() -> None:
    founder_cap = EXPERIENCE_LIMITS["founder"]["simulation_runs"]
    deliverer_cap = EXPERIENCE_LIMITS["deliverer"]["simulation_runs"]
    assert founder_cap != deliverer_cap  # 两档独立配置

    check_experience_limit("founder", "simulation_runs", founder_cap - 1)  # 未触限
    try:
        check_experience_limit("founder", "simulation_runs", founder_cap)  # 触限（used >= cap）
    except CommercialServiceError as error:
        assert error.code == "experience_limit_exceeded"
        assert error.status == 409
    else:  # pragma: no cover
        raise AssertionError("cap not enforced")

    check_experience_limit("deliverer", "simulation_runs", deliverer_cap - 1)

    # **按资源分别计数**：mentor_sessions 的上限不得误伤 simulation_runs 计数
    mentor_cap = EXPERIENCE_LIMITS["founder"]["mentor_sessions"]
    assert founder_cap - 1 >= mentor_cap  # 前者数值大于后者——若两资源共用一个计数器必被误拒
    check_experience_limit("founder", "simulation_runs", founder_cap - 1)

    for bad_kind in ("enterprise", "admin", None):
        try:
            check_experience_limit(bad_kind, "simulation_runs", 0)
        except CommercialServiceError as error:
            assert error.code == "invalid_experience_kind"
        else:  # pragma: no cover
            raise AssertionError(f"expected rejection: {bad_kind!r}")

    try:
        check_experience_limit("founder", "unknown_resource", 0)
    except CommercialServiceError as error:
        assert error.code == "invalid_experience_resource"
    else:  # pragma: no cover
        raise AssertionError("expected rejection for unknown resource")


# ---------------------------------------------------------------------------
# 7. 读面权限 + 审计事件 + 免费边界元数据
# ---------------------------------------------------------------------------


def test_read_permission(admin_client, authorized_client_factory) -> None:
    user = authorized_client_factory("viewer")
    assert _grant(admin_client).status_code == 200
    # 未绑定前只有 admin 可读
    assert user.get(_quota_url(VALID_USCC)).status_code == 403
    assert admin_client.get(_quota_url(VALID_USCC)).status_code == 200
    user.post(f"{_quota_url(VALID_USCC)}/start", json={})
    assert user.get(_quota_url(VALID_USCC)).status_code == 200
    other = authorized_client_factory("viewer")
    assert other.get(_quota_url(VALID_USCC)).status_code == 403
    # 合法但未授予的另一主体 → 404
    missing = admin_client.get(_quota_url(_another_uscc(VALID_USCC)))
    assert missing.status_code == 404


def _another_uscc(seed: str) -> str:
    chars = "0123456789ABCDEFGHJKLMNPQRTUWXY"
    weights = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)
    base = list(seed)
    base[0] = "5" if base[0] != "5" else "6"
    total = sum(chars.index(base[i]) * w for i, w in enumerate(weights))
    base[17] = chars[(31 - total % 31) % 31]
    return "".join(base)


def test_grant_event_audited_without_password(
    admin_client, authorized_client_factory, db_session
) -> None:
    assert _grant(admin_client).status_code == 200
    event = db_session.scalars(
        select(OperationEvent)
        .where(OperationEvent.event_type == "commercial_quota_granted")
        .order_by(OperationEvent.occurred_at.desc())
    ).first()
    assert event is not None
    assert isinstance(event.changes.get("request_id"), str)
    assert event.changes["subject_key"] == VALID_USCC
    assert INITIAL_PASSWORD not in repr(event.changes)
    assert "confirm_password" not in repr(event.changes)


def test_free_diagnosis_profile_meta(admin_client) -> None:
    resp = admin_client.get("/api/v1/commercial/free-diagnosis-profile")
    assert resp.status_code == 200
    data = resp.json["data"]
    assert data["deliverables"] == list(FREE_DIAGNOSIS_DELIVERABLES)
    assert len(data["exclusions"]) == len(FREE_EXCLUSIONS) == 7
    # 三档纯描述：label/description 均字符串，无数值区间
    for tier in data["project_tiers"].values():
        assert isinstance(tier["label"], str)
        assert isinstance(tier["description"], str)
    # 三入口注册表可见且各带域与隔离声明
    assert set(data["trial_entries"]) == {"enterprise", "founder", "deliverer"}
    for key, spec in data["trial_entries"].items():
        assert isinstance(spec["label"], str)
        assert isinstance(spec["scope"], str)
        assert spec["allowed_scopes"], key
        assert "real_business" not in spec["allowed_scopes"] or key == "enterprise"
    assert data["trial_entries"]["enterprise"]["subject_key_required"] is True
    # 上限结构完整且禁止无上限（每档每资源为正整数）
    assert data["experience_limits_placeholder"] is True  # 占位缺省如实标注
    for caps in data["experience_limits"].values():
        assert set(caps) == {"simulation_runs", "mentor_sessions"}
        assert all(isinstance(v, int) and v > 0 for v in caps.values())


def test_governance_face_not_in_api_catalog() -> None:
    offenders = [
        key
        for key in CATALOG
        if "commercial" in key or "enterprise-quota" in key or "free-diagnosis" in key
    ]
    assert offenders == []


# ---------------------------------------------------------------------------
# 8. 迁移 additive 往返
# ---------------------------------------------------------------------------


def test_quota_migration_roundtrip(engine, alembic_config) -> None:
    inspector = sql_inspect(engine)
    assert "enterprise_quota_subjects" in set(inspector.get_table_names())
    assert "enterprise_free_quota" in set(inspector.get_table_names())
    quota_checks = {
        c["name"] for c in inspector.get_check_constraints("enterprise_free_quota")
    }
    assert {
        "ck_enterprise_free_quota_state",
        "ck_enterprise_free_quota_bound_shape",
        "ck_enterprise_free_quota_completed_shape",
        "ck_enterprise_free_quota_confirm_requires_completed",
    } <= quota_checks

    command.downgrade(alembic_config, "e9c4a1f7b3d2")
    inspector = sql_inspect(engine)
    assert "enterprise_free_quota" not in set(inspector.get_table_names())
    assert "enterprise_quota_subjects" not in set(inspector.get_table_names())

    command.upgrade(alembic_config, "head")
    inspector = sql_inspect(engine)
    assert "enterprise_free_quota" in set(inspector.get_table_names())
    assert "enterprise_quota_subjects" in set(inspector.get_table_names())
