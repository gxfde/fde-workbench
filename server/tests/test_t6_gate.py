"""goal-d11：T6 高成本 run 前评审强制门（总纲 §2.2 T6）。

- 判据 = 拟用 agent 的授权成本档（max_cost_units；0 = 单 run 不限额 = 最高
  成本档，必触发）超全局阈值（settings.t6_review_cost_threshold，0 = 全局关）。
- 项目级关闭：projects.t6_review_disabled（PATCH 布尔，非布尔 400）。
- 放行条件 = 已封存 T6 模板强制纪要侧链该项目（topic_refs.project_id）；
  auto 纪要排除（决议 4）。
- 闸序：协同声明 → T1 → T6（T6 在 solution 块外——不带 solution 的 run 同受闸）。
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from test_agents_d4_harness import (
    api_client,
    prime_run,
    seed_agent,
)
from test_agents_d4_harness import (  # noqa: F401  (pytest fixture)
    d4_app,
    d4_client,
    d4_settings,
)
from test_document_drafts_api import _persist_project

from fde_api.app import create_app
from fde_api.meetings.templates import MEETING_TEMPLATES

_MINUTES_OK = {
    "consensus": [{"text": "性价比评审通过", "source_refs": []}],
    "disputes": [],
    "todos": [],
}


@pytest.fixture
def t6_settings(d4_settings):
    return d4_settings.model_copy(update={"t6_review_cost_threshold": 100})


@pytest.fixture
def t6_app(t6_settings):
    app = create_app(t6_settings)
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def t6_client(t6_app):
    return t6_app.test_client()


def _setup(db_session, client, settings, *, max_cost_units: int = 500, project_toggle: bool | None = None):
    leader = api_client(client, db_session, settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"T6{uuid4().hex[:6]}")
    if project_toggle is not None:
        patched = leader.patch(
            f"/api/v1/projects/{project.id}",
            json={"version": project.version, "t6_review_disabled": project_toggle},
        )
        assert patched.status_code == 200, patched.json
    agent = seed_agent(db_session, settings, max_cost_units=max_cost_units)
    return leader, project, agent


def _start(leader, agent, project, *, key: str | None = None):
    return leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": key or f"t6:{uuid4().hex}"},
    )


def _seed_t6_minutes(leader, project, *, auto: bool = False, db_session=None) -> str:
    convened = leader.post(
        "/api/v1/meetings",
        json={
            "project_id": project.id,
            "template_id": "T6-lite",
            "topic_refs": {"project_id": project.id},
        },
    )
    assert convened.status_code == 201, convened.json
    meeting_id = convened.json["data"]["id"]
    if auto:
        # manual close 会剥掉 todos 的 auto 键（防伪造自动标记）——auto 纪要
        # 只能由 Killjoy/超时收场产生，这里直建行复现该形态。
        from fde_api.extensions import db as _db
        from fde_api.meetings.models import ReviewMeetingMinutes

        session = _db.session()
        try:
            with session.begin():
                session.add(
                    ReviewMeetingMinutes(
                        meeting_id=meeting_id,
                        consensus=_MINUTES_OK["consensus"],
                        disputes=[],
                        todos=[{"text": "自动收尾", "auto": True}],
                        sealed_sha256="a" * 64,
                    )
                )
        finally:
            session.close()
        return meeting_id
    sealed = leader.post(f"/api/v1/meetings/{meeting_id}/close", json=_MINUTES_OK)
    assert sealed.status_code == 200, sealed.json
    return meeting_id


def test_t6_disabled_by_default(db_session, d4_client, d4_app, d4_settings) -> None:
    """默认阈值 0（全局关）：高档 agent 的 run 不受闸——v0.2.0 行为零回归。"""
    leader, project, agent = _setup(db_session, d4_client, d4_settings)
    prime_run(d4_app)
    assert _start(leader, agent, project).status_code == 201


def test_t6_blocks_when_tier_exceeds_threshold(db_session, t6_client, t6_settings, t6_app) -> None:
    leader, project, agent = _setup(db_session, t6_client, t6_settings)
    prime_run(t6_app)
    body = _start(leader, agent, project)
    assert body.status_code == 409, body.json
    error = body.json["error"]
    assert error["code"] == "t6_gate_open"
    assert error["details"]["gate"] == "T6"
    assert error["details"]["threshold"] == 100


def test_t6_zero_units_is_highest_tier(db_session, t6_client, t6_settings, t6_app) -> None:
    """max_cost_units=0 = 单 run 不限额 = 最高成本档，必触发（决议 1）。"""
    leader, project, agent = _setup(db_session, t6_client, t6_settings, max_cost_units=0)
    prime_run(t6_app)
    body = _start(leader, agent, project)
    assert body.status_code == 409
    assert body.json["error"]["code"] == "t6_gate_open"


def test_t6_below_threshold_passes(db_session, t6_client, t6_settings, t6_app) -> None:
    leader, project, agent = _setup(db_session, t6_client, t6_settings, max_cost_units=50)
    prime_run(t6_app)
    assert _start(leader, agent, project).status_code == 201


def test_t6_passes_with_sealed_minutes(db_session, t6_client, t6_settings, t6_app) -> None:
    leader, project, agent = _setup(db_session, t6_client, t6_settings)
    prime_run(t6_app)
    _seed_t6_minutes(leader, project)
    assert _start(leader, agent, project).status_code == 201


def test_t6_minutes_of_other_project_do_not_satisfy(db_session, t6_client, t6_settings, t6_app) -> None:
    """跨项目不放行：T6 纪要侧链的是发起项目——别项目的性价比结论不算数。"""
    leader, project, agent = _setup(db_session, t6_client, t6_settings)
    prime_run(t6_app)
    other = _persist_project(db_session, leader.user, code=f"T6B{uuid4().hex[:6]}")
    _seed_t6_minutes(leader, other)
    body = _start(leader, agent, project)
    assert body.status_code == 409
    assert body.json["error"]["code"] == "t6_gate_open"


def test_t6_auto_minutes_do_not_satisfy(db_session, t6_client, t6_settings, t6_app) -> None:
    """auto 纪要不作强制门证据（决议 4）：auto 收敛纪要放不高成本 run。"""
    leader, project, agent = _setup(db_session, t6_client, t6_settings)
    prime_run(t6_app)
    _seed_t6_minutes(leader, project, auto=True, db_session=db_session)
    body = _start(leader, agent, project)
    assert body.status_code == 409
    assert body.json["error"]["code"] == "t6_gate_open"


def test_t6_project_toggle_disables_gate(db_session, t6_client, t6_settings, t6_app) -> None:
    """项目级关闭（总纲「可按项目关闭」）：t6_review_disabled=true 后放行。"""
    leader, project, agent = _setup(
        db_session, t6_client, t6_settings, project_toggle=True
    )
    prime_run(t6_app)
    assert _start(leader, agent, project).status_code == 201
    detail = leader.get(f"/api/v1/projects/{project.id}").json["data"]
    assert detail["t6_review_disabled"] is True


def test_t6_patch_rejects_non_bool(db_session, t6_client, t6_settings) -> None:
    leader, project, _agent = _setup(db_session, t6_client, t6_settings)
    body = leader.patch(
        f"/api/v1/projects/{project.id}",
        json={"version": project.version + 1, "t6_review_disabled": "false"},
    )
    assert body.status_code == 400


def test_t6_gate_applies_without_solution(db_session, t6_client, t6_settings, t6_app) -> None:
    """T6 在 solution 块外：不带 solution 的 run 同受闸（项目级门）。"""
    leader, project, agent = _setup(db_session, t6_client, t6_settings)
    prime_run(t6_app)
    body = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": f"t6ns:{uuid4().hex}"},
    )
    assert body.status_code == 409
    assert body.json["error"]["code"] == "t6_gate_open"


def test_t6_template_registered() -> None:
    template = MEETING_TEMPLATES["T6-lite"]
    assert template["gate"] == "T6"
    assert template["trigger"] == "mandatory"
