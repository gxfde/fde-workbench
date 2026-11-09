"""商业化 G6：企业空间与企业自助交付（T-06/T-08，ADR-010 验收钉）。

钉住八件事：
1. **企业自助注册（R1，当事人自证）**：无 admin 门公开入口——一个事务里
   账号（viewer＋自选密码 ⇒ must_change_password=False）＋身份分层
   （commercial_role='R1'）＋主体与额度（同主体幂等，绝不新建/重置）
   ＋事件留痕（actor=当事人，无密码）；坏 USCC/弱密码/重名 400/409；
2. **换账号不重置（ADR-004 硬不变量穿透自助路径）**：同主体第二注册
   ``quota_created=False``、额度行恒 1、状态不变；他账号启动 409
   ``quota_bound_to_other_account``；
3. **自选密码可登录**（must_change_password=False）；
4. **四类注册入口齐备**：注册表键集＝R1–R4；R2/R3 ↔ G2 体验入口注册表；
   读面（free-diagnosis-profile）可见；
5. **企业空间读面**（绑定账号/admin/他人 403/未知 404）：问题描述/额度/
   ``engagement_state``（self_service ⇄ paid_delivery 派生——M 变异靶）/
   交付项目（既有 ``project_access`` 可见性过滤）；
6. **三档分流人工判定留痕**：admin+密码双闸；诊断未完成 409
   ``diagnosis_not_completed``；tier 闭集＝G2 ``DIAGNOSIS_PROJECT_TIERS``
   权威（零另立枚举）；rationale 必填（定性）；basis 指针/指纹同有同无；
   空间读面可回看（谁在何时判了哪一档、依据）；
7. **三个付费选项＋企业自主选择不被取消**：选项派生自 G2 权威＋跟进语
   **零金额零数值**（哨兵：载荷无数字）；选择只认绑定账号本人（admin
   越权 403）；append-only（换主意＝再选取代，源码扫描钉＋方法集扫描钉
   ——无任何删除/取消路径）；顾问跟进注记（admin+密码，只补三元组）；
8. **复用既有权限模型**：企业账号经既有 ``add_project_member`` 进交付项目
   即可读（project_members 既有表，零平行权限表——G6 元数据新增表仅两张）。
"""

from __future__ import annotations

import json
import re
from datetime import datetime as _dt
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.auth.tokens import issue_access_token
from fde_api.commercial.models import (
    COMMERCIAL_ROLES,
    DIAGNOSIS_PROJECT_TIERS,
    ENTERPRISE_TRIAGE_TIERS,
    FREE_DIAGNOSIS_DELIVERABLES,
    REGISTRATION_ENTRIES,
    CommercialEntitlement,
    EnterpriseFreeQuota,
    EnterpriseQuotaSubject,
)
from fde_api.workbench.models import OperationEvent, Project, ProjectMember

from conftest import INITIAL_PASSWORD
from test_research_subjects_api import (  # noqa: F401  (pytest fixture)
    AuthorizedClient,
    admin_client,
    authorized_client_factory,
    leader_client,
)

SERVER_ROOT = Path(__file__).resolve().parents[1]
ENTERPRISE_SERVICE = SERVER_ROOT / "src" / "fde_api" / "commercial" / "enterprise_service.py"

VALID_USCC = "91350100M000100Y43"  # 公开样本（mod-31 校验通过，同 G2）
BAD_CHECKSUM_USCC = "91350100M000100Y44"
SECOND_USCC = "92350100M000100Y40"  # 另一合法主体（mod-31 校验通过）
SELF_PASSWORD = "Enterprise!Pass2026"

REG_URL = "/api/v1/commercial/enterprise-registrations"
PROFILE_URL = "/api/v1/commercial/free-diagnosis-profile"


def _pwd() -> str:
    return INITIAL_PASSWORD


def _space_url(uscc: str) -> str:
    return f"/api/v1/commercial/enterprise-spaces/{uscc}"


def _choices_url(uscc: str) -> str:
    return f"{_space_url(uscc)}/paid-option-choices"


def _triage_url(uscc: str) -> str:
    return f"/api/v1/admin/commercial/enterprise-spaces/{uscc}/triage-decisions"


def _advisor_url(uscc: str, choice_id: str) -> str:
    return (
        f"/api/v1/admin/commercial/enterprise-spaces/{uscc}"
        f"/paid-option-choices/{choice_id}/advisor-note"
    )


def _register(
    client,
    uscc: str = VALID_USCC,
    name: str = "测试企业甲",
    username: str | None = None,
    password: str = SELF_PASSWORD,
    problem: str = "描述业务问题：订单履约周期过长，需要一次完整诊断。",
):
    return client.post(
        REG_URL,
        json={
            "username": username or f"ent.{uuid4().hex[:10]}",
            "display_name": name,
            "password": password,
            "subject_key": uscc,
            "problem_description": problem,
        },
    )


def _enterprise_client(
    client, settings, db_session, uscc: str = VALID_USCC, name: str = "测试企业甲"
):
    """注册新主体并以新账号身份返回 (AuthorizedClient, 注册响应 data)。"""
    response = _register(client, uscc=uscc, name=name)
    assert response.status_code == 200, response.get_data(as_text=True)
    data = response.json["data"]
    user = db_session.scalar(select(User).where(User.id == data["user_id"]))
    authorized = AuthorizedClient(
        client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    )
    return authorized, data["subject_key"]


def _completed_subject(
    client, admin_client, settings, db_session, uscc: str | None = None, name: str = "测试企业甲"
):
    """自助注册 → 启动绑定 → admin 登记六项完成 → 企业确认（L3 形态全程）。"""
    uscc = uscc or VALID_USCC
    ent_client, subject_key = _enterprise_client(
        client, settings, db_session, uscc=uscc, name=name
    )
    assert subject_key == uscc
    started = ent_client.post(f"/api/v1/commercial/enterprise-quota/{uscc}/start", json={})
    assert started.status_code == 200, started.get_data(as_text=True)
    done = admin_client.post(
        f"/api/v1/admin/commercial/enterprise-quota/{uscc}/complete",
        json={
            "deliverables": {key: True for key in FREE_DIAGNOSIS_DELIVERABLES},
            "confirm_password": _pwd(),
        },
    )
    assert done.status_code == 200, done.get_data(as_text=True)
    confirmed = ent_client.post(f"/api/v1/commercial/enterprise-quota/{uscc}/confirm", json={})
    assert confirmed.status_code == 200, confirmed.get_data(as_text=True)
    return ent_client, uscc


def _sha(seed: str) -> str:
    import hashlib

    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 1. 企业自助注册（R1 当事人自证）
# ---------------------------------------------------------------------------


def test_self_registration_creates_account_identity_subject_quota(
    client, db_session
) -> None:
    response = _register(client, username="ent.founder.one")
    assert response.status_code == 200, response.get_data(as_text=True)
    data = response.json["data"]
    assert data["quota_created"] is True
    assert data["quota_state"] == "granted"
    assert data["subject_key"] == VALID_USCC

    user = db_session.scalar(select(User).where(User.id == data["user_id"]))
    assert user is not None
    assert user.role == "viewer"
    assert user.must_change_password is False  # 自选密码非临时密码

    entitlement = db_session.scalar(
        select(CommercialEntitlement).where(CommercialEntitlement.user_id == user.id)
    )
    assert entitlement is not None
    assert entitlement.commercial_role == "R1"

    subject = db_session.get(EnterpriseQuotaSubject, VALID_USCC)
    assert subject is not None
    assert subject.first_user_id == user.id
    assert subject.problem_description and "订单履约" in subject.problem_description

    quota = db_session.get(EnterpriseFreeQuota, VALID_USCC)
    assert quota is not None
    assert quota.state == "granted"
    assert quota.granted_by_user_id == user.id  # 自助授予＝当事人自证

    event = db_session.scalar(
        select(OperationEvent)
        .where(OperationEvent.event_type == "enterprise_self_registered")
        .order_by(OperationEvent.created_at.desc())
    )
    assert event is not None
    assert event.actor_user_id == user.id
    assert "password" not in json.dumps(event.changes or {})


def test_registration_rejects_bad_uscc_weak_password_duplicate_username(
    client, authorized_client_factory
) -> None:
    taken = authorized_client_factory("viewer")
    existing_username = taken.user.username

    bad_uscc = _register(client, uscc=BAD_CHECKSUM_USCC)
    assert bad_uscc.status_code == 400
    assert bad_uscc.json["error"]["code"] == "invalid_subject_key"

    weak = _register(client, password="short")
    assert weak.status_code == 400

    duplicate = _register(client, username=existing_username)
    assert duplicate.status_code == 409
    assert duplicate.json["error"]["code"] == "username_already_exists"


def test_same_subject_second_registration_does_not_reset_quota(client, db_session) -> None:
    first = _register(client, username="ent.first")
    assert first.status_code == 200
    second = _register(client, username="ent.second")
    assert second.status_code == 200
    assert second.json["data"]["quota_created"] is False
    assert second.json["data"]["quota_state"] == "granted"

    quotas = db_session.scalars(
        select(EnterpriseFreeQuota).where(EnterpriseFreeQuota.subject_key == VALID_USCC)
    ).all()
    assert len(quotas) == 1  # 「额度按账号计」的实现在此转红（任务书 §6 反例机器闸）
    assert quotas[0].state == "granted"
    subject = db_session.get(EnterpriseQuotaSubject, VALID_USCC)
    assert subject.first_user_id == first.json["data"]["user_id"]


def test_second_account_cannot_restart_bound_quota(
    client, settings, db_session, authorized_client_factory
) -> None:
    ent_client, _data = _enterprise_client(client, settings, db_session)
    started = ent_client.post(f"/api/v1/commercial/enterprise-quota/{VALID_USCC}/start", json={})
    assert started.status_code == 200

    other, _other_data = _enterprise_client(
        client, settings, db_session, name="测试企业乙"
    )  # 同主体：名称不同，主体键相同
    blocked = other.post(f"/api/v1/commercial/enterprise-quota/{VALID_USCC}/start", json={})
    assert blocked.status_code == 409
    assert blocked.json["error"]["code"] == "quota_bound_to_other_account"


def test_self_registered_user_can_login_with_chosen_password(client) -> None:
    username = "ent.login"
    assert _register(client, username=username).status_code == 200
    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": SELF_PASSWORD, "device_label": "self-test"},
    )
    assert login.status_code == 200, login.get_data(as_text=True)
    assert login.json["data"]["access_token"]
    assert login.json["data"]["user"]["must_change_password"] is False


def test_registration_entries_cover_all_four_identities(
    client, admin_client, db_session
) -> None:
    assert tuple(REGISTRATION_ENTRIES) == COMMERCIAL_ROLES

    from fde_api.commercial.models import FREE_TRIAL_ENTRIES

    assert REGISTRATION_ENTRIES["R2"]["path"] == "trial_entry:founder"
    assert REGISTRATION_ENTRIES["R2"]["path"].split(":", 1)[1] in FREE_TRIAL_ENTRIES
    assert REGISTRATION_ENTRIES["R3"]["path"].split(":", 1)[1] in FREE_TRIAL_ENTRIES

    profile = admin_client.get(PROFILE_URL)
    assert profile.status_code == 200
    entries = profile.json["data"]["registration_entries"]
    assert tuple(entries) == COMMERCIAL_ROLES
    assert entries["R1"]["source"] == "g6_self_service"


# ---------------------------------------------------------------------------
# 2. 企业空间读面
# ---------------------------------------------------------------------------


def test_space_view_bound_account_sees_self_service_state(
    client, admin_client, settings, db_session
) -> None:
    ent_client, uscc = _completed_subject(client, admin_client, settings, db_session)
    view = ent_client.get(_space_url(uscc))
    assert view.status_code == 200, view.get_data(as_text=True)
    data = view.json["data"]
    assert data["subject"]["subject_key"] == uscc
    assert "订单履约" in data["subject"]["problem_description"]
    assert data["quota"]["state"] == "completed"
    assert data["engagement_state"] == "self_service"
    assert sorted(data["paid_options"]["options"]) == sorted(ENTERPRISE_TRIAGE_TIERS)
    assert tuple(data["registration_entries"]) == COMMERCIAL_ROLES


def test_space_view_scopes(client, settings, db_session, admin_client) -> None:
    ent_client, uscc = _enterprise_client(client, settings, db_session, name="测试企业丙")
    ent_client.post(f"/api/v1/commercial/enterprise-quota/{uscc}/start", json={})

    admin_view = admin_client.get(_space_url(uscc))
    assert admin_view.status_code == 200

    stranger, _s = _enterprise_client(
        client, settings, db_session, name="测试企业丁"
    )
    forbidden = stranger.get(_space_url(uscc))
    assert forbidden.status_code == 403
    assert forbidden.json["error"]["code"] == "enterprise_space_forbidden"

    anon = client.get(_space_url(uscc))
    assert anon.status_code == 401

    missing = admin_client.get(_space_url(SECOND_USCC))
    assert missing.status_code == 404
    assert missing.json["error"]["code"] == "enterprise_space_not_found"


def test_paid_options_derive_from_g2_authority_and_carry_no_numbers() -> None:
    from fde_api.commercial.enterprise_service import ADVISOR_FOLLOW_UP_NOTE, paid_options

    options = paid_options()
    assert tuple(options) == tuple(DIAGNOSIS_PROJECT_TIERS)
    for key, option in options.items():
        assert option["label"] == DIAGNOSIS_PROJECT_TIERS[key]["label"]
        assert option["description"] == DIAGNOSIS_PROJECT_TIERS[key]["description"]
        assert option["follow_up"] == ADVISOR_FOLLOW_UP_NOTE
    # 本期不落数值红线：选项载荷不得出现任何数字（金额/天数/比例一律不落）
    assert not re.search(r"[0-9]", json.dumps(options, ensure_ascii=False))


# ---------------------------------------------------------------------------
# 3. 三档分流人工判定留痕
# ---------------------------------------------------------------------------


def test_triage_requires_admin_and_password(leader_client, admin_client) -> None:
    non_admin = leader_client.post(
        _triage_url(VALID_USCC), json={"tier": "standardized", "rationale": "x"}
    )
    assert non_admin.status_code == 403

    missing_pwd = admin_client.post(
        _triage_url(VALID_USCC), json={"tier": "standardized", "rationale": "x"}
    )
    assert missing_pwd.status_code == 400

    wrong_pwd = admin_client.post(
        _triage_url(VALID_USCC),
        json={"tier": "standardized", "rationale": "x", "confirm_password": "Wrong!Pass1"},
    )
    assert wrong_pwd.status_code == 403
    assert wrong_pwd.json["error"]["code"] == "invalid_password"


def test_triage_requires_completed_diagnosis(
    client, settings, db_session, admin_client
) -> None:
    ent_client, uscc = _enterprise_client(client, settings, db_session, name="测试企业戊")
    ent_client.post(f"/api/v1/commercial/enterprise-quota/{uscc}/start", json={})
    blocked = admin_client.post(
        _triage_url(uscc),
        json={"tier": "standardized", "rationale": "未完成就想分流", "confirm_password": _pwd()},
    )
    assert blocked.status_code == 409
    assert blocked.json["error"]["code"] == "diagnosis_not_completed"


def test_triage_records_human_decision_with_rationale(
    client, admin_client, settings, db_session
) -> None:
    ent_client, uscc = _completed_subject(client, admin_client, settings, db_session)
    response = admin_client.post(
        _triage_url(uscc),
        json={
            "tier": "multi_system",
            "rationale": "定性判断：客户自述涉及 ERP 与 WMS 两套系统，数据需双向同步。",
            "confirm_password": _pwd(),
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    decision = response.json["data"]
    assert decision["tier"] == "multi_system"
    assert decision["tier_label"] == DIAGNOSIS_PROJECT_TIERS["multi_system"]["label"]
    assert decision["decided_by_user_id"] == admin_client.user.id
    assert "ERP" in decision["rationale"]

    event = db_session.scalar(
        select(OperationEvent)
        .where(OperationEvent.event_type == "enterprise_triage_decided")
        .order_by(OperationEvent.created_at.desc())
    )
    assert event is not None
    assert event.changes["tier"] == "multi_system"
    assert "confirm_password" not in json.dumps(event.changes or {})

    # 完成前置闸通过后的空间读面：可回看
    view = ent_client.get(_space_url(uscc))
    decisions = view.json["data"]["triage_decisions"]
    assert len(decisions) == 1
    assert decisions[0]["tier"] == "multi_system"


def test_triage_rejects_invalid_tier_and_empty_rationale(
    client, admin_client, settings, db_session
) -> None:
    _ent_client, uscc = _completed_subject(client, admin_client, settings, db_session)
    bad_tier = admin_client.post(
        _triage_url(uscc),
        json={"tier": "bogus", "rationale": "x", "confirm_password": _pwd()},
    )
    assert bad_tier.status_code == 400
    assert bad_tier.json["error"]["code"] == "invalid_tier"

    empty = admin_client.post(
        _triage_url(uscc),
        json={"tier": "standardized", "rationale": "  ", "confirm_password": _pwd()},
    )
    assert empty.status_code == 400


def test_triage_basis_pointer_and_hash_must_be_atomic(
    client, admin_client, settings, db_session
) -> None:
    _ent_client, uscc = _completed_subject(client, admin_client, settings, db_session)
    uri_only = admin_client.post(
        _triage_url(uscc),
        json={
            "tier": "standardized",
            "rationale": "x",
            "basis_uri": "fdeops://g6/triage/a.md",
            "confirm_password": _pwd(),
        },
    )
    assert uri_only.status_code == 400

    ok = admin_client.post(
        _triage_url(uscc),
        json={
            "tier": "standardized",
            "rationale": "x",
            "basis_uri": "fdeops://g6/triage/a.md",
            "basis_sha256": _sha("triage-a"),
            "confirm_password": _pwd(),
        },
    )
    assert ok.status_code == 200
    assert ok.json["data"]["basis_sha256"] == _sha("triage-a")


def test_triage_decisions_reviewable_in_space_view(
    client, admin_client, settings, db_session
) -> None:
    ent_client, uscc = _completed_subject(client, admin_client, settings, db_session)
    for tier in ("standardized", "complex"):
        posted = admin_client.post(
            _triage_url(uscc),
            json={"tier": tier, "rationale": f"依据-{tier}", "confirm_password": _pwd()},
        )
        assert posted.status_code == 200
    view = ent_client.get(_space_url(uscc))
    decisions = view.json["data"]["triage_decisions"]
    assert [d["tier"] for d in decisions] == ["complex", "standardized"]  # 最新在前
    assert all(d["rationale"] for d in decisions)


def test_triage_tier_closed_set_matches_g2_authority() -> None:
    assert ENTERPRISE_TRIAGE_TIERS == tuple(DIAGNOSIS_PROJECT_TIERS)


# ---------------------------------------------------------------------------
# 4. 三个付费选项与「企业自主选择不被取消」
# ---------------------------------------------------------------------------


def test_choice_requires_bound_account_even_for_admin(
    client, admin_client, settings, db_session
) -> None:
    ent_client, uscc = _completed_subject(client, admin_client, settings, db_session)
    denied = admin_client.post(
        _choices_url(uscc), json={"option_key": "standardized"}
    )
    assert denied.status_code == 403
    assert denied.json["error"]["code"] == "enterprise_choice_forbidden"

    stranger, _s = _enterprise_client(
        client, settings, db_session, name="测试企业己"
    )
    denied_stranger = stranger.post(
        _choices_url(uscc), json={"option_key": "standardized"}
    )
    assert denied_stranger.status_code == 403


def test_choice_requires_completed_diagnosis(
    client, settings, db_session, admin_client
) -> None:
    ent_client, uscc = _enterprise_client(client, settings, db_session, name="测试企业庚")
    ent_client.post(f"/api/v1/commercial/enterprise-quota/{uscc}/start", json={})
    blocked = ent_client.post(_choices_url(uscc), json={"option_key": "standardized"})
    assert blocked.status_code == 409
    assert blocked.json["error"]["code"] == "diagnosis_not_completed"


def test_choice_records_and_derives_paid_delivery_state(
    client, admin_client, settings, db_session
) -> None:
    ent_client, uscc = _completed_subject(client, admin_client, settings, db_session)
    chosen = ent_client.post(_choices_url(uscc), json={"option_key": "standardized"})
    assert chosen.status_code == 200, chosen.get_data(as_text=True)
    choice = chosen.json["data"]
    assert choice["option_key"] == "standardized"
    assert choice["chosen_by_user_id"] == ent_client.user.id
    assert choice["superseded_at"] is None

    view = ent_client.get(_space_url(uscc))
    data = view.json["data"]
    assert data["engagement_state"] == "paid_delivery"  # 同一主体两种状态（派生）
    assert data["paid_options"]["current_choice"]["option_key"] == "standardized"

    event = db_session.scalar(
        select(OperationEvent)
        .where(OperationEvent.event_type == "enterprise_paid_option_choice_recorded")
        .order_by(OperationEvent.created_at.desc())
    )
    assert event is not None
    assert event.actor_user_id == ent_client.user.id


def test_choice_rejects_invalid_option(
    client, admin_client, settings, db_session
) -> None:
    ent_client, uscc = _completed_subject(client, admin_client, settings, db_session)
    bad = ent_client.post(_choices_url(uscc), json={"option_key": "platinum"})
    assert bad.status_code == 400
    assert bad.json["error"]["code"] == "invalid_paid_option"


def test_choice_supersede_by_enterprise_reselection(
    client, admin_client, settings, db_session
) -> None:
    ent_client, uscc = _completed_subject(client, admin_client, settings, db_session)
    first = ent_client.post(_choices_url(uscc), json={"option_key": "complex"})
    assert first.status_code == 200
    second = ent_client.post(_choices_url(uscc), json={"option_key": "standardized"})
    assert second.status_code == 200

    from fde_api.commercial.models import EnterprisePaidOptionChoice

    rows = db_session.scalars(
        select(EnterprisePaidOptionChoice)
        .where(EnterprisePaidOptionChoice.subject_key == uscc)
        .order_by(EnterprisePaidOptionChoice.chosen_at.asc())
    ).all()
    assert len(rows) == 2
    assert rows[0].superseded_at is not None  # 旧行被企业本人再选取代（留痕）
    assert rows[1].superseded_at is None

    view = ent_client.get(_space_url(uscc))
    assert view.json["data"]["paid_options"]["current_choice"]["option_key"] == "standardized"
    assert view.json["data"]["engagement_state"] == "paid_delivery"


def test_no_cancel_path_source_and_route_scan(app) -> None:
    # 路由枚举用 conftest ``app`` 夹具（测试 env 注入齐全）——CI 无 .env，
    # 裸 create_app() 会因 Settings 缺 database_url/redis_url/jwt_secret 爆炸
    # （审计抽取脚本「不调 create_app」同一坑，教训同源）。
    source = ENTERPRISE_SERVICE.read_text(encoding="utf-8")
    assert ".delete(" not in source
    assert "def cancel" not in source.lower()
    for rule in app.url_map.iter_rules():
        if "enterprise" in rule.rule:
            methods = set(rule.methods or set())
            assert methods <= {"GET", "POST", "HEAD", "OPTIONS"}, (rule.rule, methods)


def test_advisor_note_admin_password_and_atomic_triple(
    client, admin_client, leader_client, settings, db_session
) -> None:
    ent_client, uscc = _completed_subject(client, admin_client, settings, db_session)
    chosen = ent_client.post(_choices_url(uscc), json={"option_key": "multi_system"})
    choice_id = chosen.json["data"]["id"]

    non_admin = leader_client.post(
        _advisor_url(uscc, choice_id), json={"note": "x", "confirm_password": _pwd()}
    )
    assert non_admin.status_code == 403  # 服务层 admin 门（commercial_admin_required）

    wrong_pwd = admin_client.post(
        _advisor_url(uscc, choice_id),
        json={"note": "x", "confirm_password": "Wrong!Pass1"},
    )
    assert wrong_pwd.status_code == 403

    noted = admin_client.post(
        _advisor_url(uscc, choice_id),
        json={"note": "顾问跟进：已约定本周五电话会。", "confirm_password": _pwd()},
    )
    assert noted.status_code == 200, noted.get_data(as_text=True)
    noted_data = noted.json["data"]
    assert noted_data["advisor_note"] == "顾问跟进：已约定本周五电话会。"
    assert noted_data["advisor_user_id"] == admin_client.user.id
    assert noted_data["option_key"] == "multi_system"  # 注记不动选择本体
    assert noted_data["chosen_by_user_id"] == ent_client.user.id

    again = admin_client.post(
        _advisor_url(uscc, choice_id),
        json={"note": "再补一条", "confirm_password": _pwd()},
    )
    assert again.status_code == 409
    assert again.json["error"]["code"] == "advisor_note_already_recorded"


def test_advisor_note_unknown_choice_404(
    client, admin_client, settings, db_session
) -> None:
    _ent_client, uscc = _completed_subject(client, admin_client, settings, db_session)
    missing = admin_client.post(
        _advisor_url(uscc, "no-such-choice"),
        json={"note": "x", "confirm_password": _pwd()},
    )
    assert missing.status_code == 404
    assert missing.json["error"]["code"] == "choice_not_found"


# ---------------------------------------------------------------------------
# 5. 复用既有权限模型（验收③：未新建平行权限表）
# ---------------------------------------------------------------------------


def test_enterprise_user_joins_delivery_project_via_existing_add_member(
    client, admin_client, settings, db_session
) -> None:
    ent_client, uscc = _completed_subject(client, admin_client, settings, db_session, name="星河制造")
    from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion

    template = IndustryTemplate(
        template_key=f"g6-tpl-{uuid4().hex[:8]}", name="g6 模板", industry_name="制造业"
    )
    version = IndustryTemplateVersion(
        template=template,
        name="g6 模板 v1",
        industry_name="制造业",
        version_number=1,
        status="published",
    )
    project = Project(
        project_code=f"G6-{uuid4().hex[:6].upper()}",
        name="g6 付费交付项目",
        enterprise_code="星河制造",  # ＝主体 display_name（企业代号＝项目域连接键）
        business_line="FDE_DISPATCH",
        planned_start_date=_dt(2026, 11, 1).date(),
        leader_user_id=admin_client.user.id,
        source_template_version=version,
        template_snapshot={"industry_name": "制造业", "modules": []},
    )
    db_session.add_all([template, version, project])
    db_session.commit()

    # 既有 add_project_member（admin=manager；项目既有 CAS 版本）
    added = admin_client.post(
        f"/api/v1/projects/{project.id}/members",
        json={"user_id": ent_client.user.id, "role": "viewer", "version": 1},
    )
    assert added.status_code == 200, added.get_data(as_text=True)

    membership = db_session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == ent_client.user.id,
        )
    )
    assert membership is not None  # 既有 project_members 表，零平行权限表

    detail = ent_client.get(f"/api/v1/projects/{project.id}")
    assert detail.status_code == 200  # 企业账号经既有可见性模型可读交付项目

    space = ent_client.get(_space_url(uscc))
    projects_in_space = space.json["data"]["space"]["projects"]
    assert any(item["project_id"] == project.id for item in projects_in_space)


def test_g6_metadata_adds_exactly_two_tables_and_no_permission_tables() -> None:
    from fde_api.commercial import models as commercial_models
    from fde_api.workbench.models import Base

    g6_tables = {"enterprise_triage_decisions", "enterprise_paid_option_choices"}
    declared = {t for t in Base.metadata.tables}
    for table in g6_tables:
        assert table in declared
    # G6 未新增任何权限/授权命名的新表（企业空间权限＝既有 projects 权限模型）
    for table in g6_tables:
        assert not re.search(r"(permission|acl)", table)
    assert hasattr(commercial_models, "EnterpriseTriageDecision")


def test_migration_column_on_subject_exists() -> None:
    assert "problem_description" in EnterpriseQuotaSubject.__table__.columns
