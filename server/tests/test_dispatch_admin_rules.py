"""goal-c CR-027：admin 规则版本显式管理面（发布 + 激活）。

根因回顾：`dispatch/rules.py` 的 `create_rule_version` / `activate_due_versions`
此前只有测试引用、零生产入口 → 规则版本永不 published→active →
`active_rule_version` 恒 None → 撮合恒 422 `rule_version_required`（§11.1
降级态变永久态）。用户 2026-11-05 拍板走**显式管理动作**（admin 决定激活
节奏，与「名单≠开闸」一致；不做惰性触发/自动激活）。

本文件钉四件事：
1. admin 门：非 admin 两条路由全 403；
2. 公示窗不绕过：发布生效日 < 发布日 +30 天 → 422 `notice_window_required`；
3. 激活闭环：到点版本经 admin 激活 → `active_rule_version` 有值 → **撮合不再 422**
   （这是本轮真正的解冻证明）；重复激活幂等（activated=0）；
4. 边界：留痕（operation_events `dispatch_rule_activated`，只落元数据）+
   **不进 api_catalog**（平台治理面，AI 不可调用）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from fde_api.control.api_catalog import CATALOG
from fde_api.dispatch.errors import DispatchServiceError
from fde_api.dispatch.matching import match_package
from fde_api.dispatch.models import DispatchRuleVersion
from fde_api.workbench.models import OperationEvent

from test_research_subjects_api import (  # noqa: F401  (pytest fixture)
    admin_client,
    authorized_client_factory,
    leader_client,
)

PUBLISH_URL = "/api/v1/admin/dispatch/rules/versions"
ACTIVATE_URL = "/api/v1/admin/dispatch/rules/activate"


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def test_admin_gate_rejects_non_admin(admin_client, leader_client) -> None:
    """非 admin 两条路由全 403（平台治理面）。"""
    denied = leader_client.post(
        PUBLISH_URL,
        json={
            "version_no": 1,
            "effective_at": _iso(datetime.now(timezone.utc) + timedelta(days=31)),
        },
    )
    assert denied.status_code == 403
    assert denied.json["error"]["code"] == "rule_admin_required"

    denied_activate = leader_client.post(ACTIVATE_URL, json={})
    assert denied_activate.status_code == 403
    assert denied_activate.json["error"]["code"] == "rule_admin_required"


def test_publish_enforces_notice_window(admin_client) -> None:
    """公示窗不绕过：生效日须 ≥ 发布日 +30 天（§6.2）；人工加速不了公示期。"""
    now = datetime.now(timezone.utc)
    too_soon = admin_client.post(
        PUBLISH_URL,
        json={"version_no": 1, "effective_at": _iso(now + timedelta(days=10))},
    )
    assert too_soon.status_code == 422
    assert too_soon.json["error"]["code"] == "notice_window_required"

    ok = admin_client.post(
        PUBLISH_URL,
        json={"version_no": 1, "effective_at": _iso(now + timedelta(days=31))},
    )
    assert ok.status_code == 200, ok.get_data(as_text=True)
    data = ok.json["data"]
    assert data["version_no"] == 1
    assert data["status"] == "published"  # 未到生效日不自动 active
    assert data["effective_at"]

    # 版本号冲突 → 409（服务层既有校验）
    conflict = admin_client.post(
        PUBLISH_URL,
        json={"version_no": 1, "effective_at": _iso(now + timedelta(days=32))},
    )
    assert conflict.status_code == 409
    assert conflict.json["error"]["code"] == "version_conflict"


def test_activate_unblocks_matching_and_is_idempotent(admin_client, db_session) -> None:
    """激活闭环：到点版本经 admin 激活 → 撮合不再 422 rule_version_required。

    这是 CR-027 的解冻证明——此前撮合路径永远停在 §11.1 降级态。"""
    from test_dispatch_p1_r5 import _onsite_package, _profile, _user
    from fde_api.dispatch.packages import publish_package

    admin, package = _onsite_package(db_session)
    publish_package(db_session, actor=admin, package_id=package.id)
    good = _user("cr27.noversion", role="fde_engineer")
    _profile(
        db_session,
        good,
        level="L2",
        module_tags=["pre_diagnosis"],
        industry_tags=["制造业"],
        home_city="广州",
    )
    db_session.flush()

    # 零生产入口时代：撮合恒 422
    with pytest.raises(DispatchServiceError) as degraded:
        match_package(db_session, actor=admin, package_id=package.id)
    assert degraded.value.code == "rule_version_required"

    # 造一个「已到生效日」的 published 版本（发布时点已过公示窗，故直接落库）
    due = DispatchRuleVersion(
        version_no=1,
        status="published",
        rule_snapshot={
            "stage_b_weights": {"level": 40, "industry": 30, "sla": 20, "geo_remote": 10},
            "level_score_map": {"L1": 40, "L2": 60, "L3": 80, "L4": 100},
            "seat_shares": {"platform": 35, "region": 5, "city": 20, "delivery": 40},
        },
        effective_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add(due)
    db_session.commit()

    activated = admin_client.post(ACTIVATE_URL, json={})
    assert activated.status_code == 200, activated.get_data(as_text=True)
    assert activated.json["data"]["activated"] == 1
    assert activated.json["data"]["active_version_no"] == 1

    # 幂等：无到期版本则零变更
    again = admin_client.post(ACTIVATE_URL, json={})
    assert again.status_code == 200
    assert again.json["data"]["activated"] == 0

    db_session.expire_all()
    row = db_session.scalar(
        select(DispatchRuleVersion).where(DispatchRuleVersion.version_no == 1)
    )
    assert row.status == "active"

    # 留痕：只落元数据（版本号/数量），不落规则正文（E7 纪律）
    event = db_session.scalar(
        select(OperationEvent).where(
            OperationEvent.event_type == "dispatch_rule_activated"
        )
    )
    assert event is not None
    assert event.changes["activated"] == 1
    assert event.changes["active_version_no"] == 1
    assert "rule_snapshot" not in event.changes

    # 解冻证明：撮合不再 422（走完 Stage A/B，产出 offer 或场景 C 降级）
    db_session.expire_all()
    package = db_session.get(type(package), package.id)
    result = match_package(db_session, actor=admin, package_id=package.id)
    assert result is not None


def test_admin_dispatch_routes_never_in_catalog() -> None:
    """红线钉子：规则版本治理是人工动作，AI 不可调用（本体治理同款边界）。"""
    paths = {str(entry["path"]) for entry in CATALOG.values()}
    assert not any("/admin/dispatch" in path for path in paths)
    assert not any("admin" in key for key in CATALOG)


def test_publish_snapshot_defaults_to_current_constants(admin_client, db_session) -> None:
    """缺省快照取当前默认规则投影（发布「当前口径」而非手抄正文）。"""
    now = datetime.now(timezone.utc)
    published = admin_client.post(
        PUBLISH_URL,
        json={"version_no": 7, "effective_at": _iso(now + timedelta(days=31))},
    )
    assert published.status_code == 200, published.get_data(as_text=True)
    db_session.expire_all()
    row = db_session.scalar(
        select(DispatchRuleVersion).where(DispatchRuleVersion.version_no == 7)
    )
    assert row is not None and row.status == "published"
    assert row.rule_snapshot["stage_b_weights"]  # 默认投影非空
    assert row.published_by_user_id is not None
