"""B#13-C：API 高风险确认主动超时（derived-state 统一原语）合同钉。

立项契约 §5 B#13-C 裁决：OperationEvent append-only 纪律优先——到期
**不追加 expiry event、不 UPDATE/DELETE 原 request 行、不建后台 sweep**；
pending 列表 / action_status / decide_action 三路径由
``confirmation_expired`` 单原语推导（窗口常量单一权威），边界
``deadline <= now`` 到期（等于边界也到期，与 B#13-B/审批域同拍）；
迟到决策零副作用（不落 started/finished、不触碰目标）；
started-but-uncertain 防重放保护优先于到期，finished replay 不受窗口影响。
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy import update as sa_update

from fde_api.auth.passwords import hash_password
from fde_api.control.api_actions import (
    CONFIRMATION_WINDOW,
    action_status,
    confirmation_expired,
    decide_action,
    pending_actions,
)
from fde_api.control.service import ControlServiceError
from fde_api.workbench.models import OperationEvent
from test_ai_api_actions import invoke
from test_ai_server_chat_mcp import ai_context, make_project


def _awaiting_action(ai_context, db_session, *, password="test-window-pw"):
    """发起一个敏感写操作，落 awaiting_confirmation（同一 Projects.update 通道）。"""
    users, _ = ai_context
    user = users["admin"]
    user.password_hash = hash_password(password)
    db_session.commit()
    project = make_project(db_session, user)
    result = invoke(user, "projects.update", {"project_id": project.id},
        {"version": project.version, "status": "cancelled"})
    assert result["status"] == "awaiting_confirmation", result
    return user, project, result["action_id"], password


def _backdate_requested(db_session, identifier, *, seconds):
    """把 request 事件回拨指定秒数（只改 created_at，不改任何 changes 事实）。"""
    db_session.execute(sa_update(OperationEvent)
        .where(OperationEvent.target_id == identifier,
               OperationEvent.event_type == "ai.api.requested")
        .values(created_at=datetime.now(UTC) - timedelta(seconds=seconds)))
    db_session.commit()


def _events_of(db_session, identifier):
    return db_session.scalars(
        select(OperationEvent).where(OperationEvent.target_id == identifier)).all()


def test_window_constant_is_fifteen_minutes():
    """窗口常量单一权威值钉死（漂移即红）。"""
    assert CONFIRMATION_WINDOW == timedelta(minutes=15)


def test_predicate_boundary_is_inclusive():
    """deadline <= now 到期：恰等于边界即过期，提前一瞬仍有效（合同 §3.3）。"""
    event = OperationEvent(actor_user_id="u", target_type="ai_api_action",
        target_id="x", event_type="ai.api.requested", changes={})
    event.created_at = datetime(2026, 11, 6, 12, 0, 0, tzinfo=UTC)
    deadline = event.created_at + CONFIRMATION_WINDOW
    assert confirmation_expired(event, now=deadline) is True
    assert confirmation_expired(event, now=deadline - timedelta(microseconds=1)) is False


def test_within_window_pending_status_and_decision_all_await(ai_context, db_session):
    user, _project, identifier, _password = _awaiting_action(ai_context, db_session)
    assert [item["id"] for item in pending_actions(user)] == [identifier]
    assert action_status(user, identifier)["status"] == "awaiting_confirmation"


def test_expired_action_rejected_everywhere_with_zero_side_effects(ai_context, db_session):
    """过期后：pending 筛除、status 推导 expired、decision 拒绝；零写路径。"""
    user, project, identifier, password = _awaiting_action(ai_context, db_session)
    _backdate_requested(db_session, identifier, seconds=16 * 60)
    assert pending_actions(user) == []
    expired = action_status(user, identifier)
    assert expired["status"] == "expired"
    with pytest.raises(ControlServiceError) as caught:
        decide_action(user, identifier, password)
    assert caught.value.code == "action_expired"
    db_session.rollback()  # 结束本连接可重复读快照（同 test_ai_api_actions 纪律）
    assert {e.event_type for e in _events_of(db_session, identifier)} == {"ai.api.requested"}
    db_session.refresh(project)
    assert project.status == "active"  # 目标零副作用


def test_started_uncertain_survives_expiry_and_never_replays(ai_context, db_session):
    """started-but-uncertain 优先于到期：不报 expired、不重放、不追加事件。"""
    user, project, identifier, password = _awaiting_action(ai_context, db_session)
    db_session.add(OperationEvent(actor_user_id=user.id, project_id=project.id,
        target_type="ai_api_action", target_id=identifier, event_type="ai.api.started",
        changes={}))
    db_session.commit()
    _backdate_requested(db_session, identifier, seconds=16 * 60)
    assert action_status(user, identifier)["status"] == "uncertain"
    result = decide_action(user, identifier, password)
    assert result["status"] == "uncertain"
    db_session.rollback()
    assert {e.event_type for e in _events_of(db_session, identifier)} == {
        "ai.api.requested", "ai.api.started"}
    db_session.refresh(project)
    assert project.status == "active"


def test_finished_action_replays_even_when_window_passed(ai_context, db_session):
    """已完成操作 replay 不受窗口影响（到期不遮蔽既有结果）。"""
    user, _project, identifier, password = _awaiting_action(ai_context, db_session)
    assert decide_action(user, identifier, password)["status"] == "completed"
    db_session.execute(sa_update(OperationEvent)
        .where(OperationEvent.target_id == identifier)
        .values(created_at=datetime.now(UTC) - timedelta(hours=1)))
    db_session.commit()
    assert action_status(user, identifier)["status"] == "completed"
    assert decide_action(user, identifier, "not-needed")["status"] == "completed"
    assert pending_actions(user) == []


def test_all_three_paths_read_the_same_window_constant(ai_context, db_session, monkeypatch):
    """三路径共用模块常量：放大窗口后同一行从全拒回到全待（接线变异敏感）。"""
    user, _project, identifier, password = _awaiting_action(ai_context, db_session)
    _backdate_requested(db_session, identifier, seconds=20 * 60)
    assert pending_actions(user) == []
    assert action_status(user, identifier)["status"] == "expired"
    with pytest.raises(ControlServiceError):
        decide_action(user, identifier, password)
    monkeypatch.setattr(
        "fde_api.control.api_actions.CONFIRMATION_WINDOW", timedelta(minutes=30))
    assert [item["id"] for item in pending_actions(user)] == [identifier]
    assert action_status(user, identifier)["status"] == "awaiting_confirmation"
    with pytest.raises(ControlServiceError) as caught:
        decide_action(user, identifier, "wrong-password")
    assert caught.value.code == "invalid_password"  # 已越过到期闸，进入密码复核
