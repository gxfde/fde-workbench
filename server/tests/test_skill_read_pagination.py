"""skill_read 分页（报告待办池清欠·B#8+B#32 真缺口）：16k 窗口 + next_offset 续取。

分页语义与 file_read / help_fetch 同构（help_bundle 同取 16_000 窗口）；T-S2 消费
计数只在首读（offset=0）计一次——续页是同一消费行为的延续，不重复计数（失败不计
与 404 不计的既有语义不变，test_skill_lifecycle 另有专钉）。
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from conftest import INITIAL_PASSWORD as PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.control.mcp_gateway import TOOLS, call_tool
from fde_api.control.models import UserAIAccessGrant
from fde_api.control.service import ControlServiceError
from fde_api.workbench.models import OperationEvent

from test_gates_api import AuthorizedClient


_WINDOW = 16_000


def _skill_payload(instructions: str | None = None, **extra):
    payload = {
        "key": f"skill-{uuid4().hex[:8]}",
        "name": "分页测试技能",
        "description": "skill_read 分页用例",
        "instructions": instructions or "只做文本总结，不执行其它操作。",
        "manifest": {"entrypoint": "SKILL.md", "format": "markdown"},
        "required_capabilities": [],
    }
    payload.update(extra)
    return payload


@pytest.fixture
def publisher(client, db_session, settings):
    """admin + system_operator 档（公共 Skill 治理人，四闸可过）。"""
    user = User(
        username=f"skillpage.admin.{uuid4().hex[:8]}",
        display_name="SkillPage admin",
        role="admin",
        password_hash=hash_password(PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.add(
        UserAIAccessGrant(
            user_id=user.id,
            granted_by_user_id=user.id,
            access_level="system_operator",
            reason="skill read pagination",
        )
    )
    db_session.commit()
    return AuthorizedClient(
        client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    )


def _save_and_publish(publisher, **extra) -> str:
    saved = publisher.post("/api/v1/extensions/skills/public", json=_skill_payload(**extra))
    assert saved.status_code == 201, saved.get_json()
    skill_id = saved.get_json()["data"]["id"]
    submitted = publisher.post(f"/api/v1/extensions/skills/{skill_id}/submit-review", json={})
    assert submitted.status_code == 200, submitted.get_json()
    published = publisher.post(
        f"/api/v1/extensions/skills/{skill_id}/publish",
        json={"password": PASSWORD, "waive_reason": "分页用例豁免"},
    )
    assert published.status_code == 200, published.get_json()
    return skill_id


def _usage_events(db_session, skill_id: str) -> list[OperationEvent]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(OperationEvent).where(
                OperationEvent.target_type == "skill_definition",
                OperationEvent.target_id == skill_id,
                OperationEvent.event_type == "skill_used_chat",
            )
        )
    )


def test_skill_read_registers_offset_property():
    """工具面登记：properties 增 offset（skill_id 仍必填），read/0 不变。"""
    description, capability, properties, effect, risk = TOOLS["skill_read"]
    assert set(properties) == {"skill_id", "offset"}
    assert properties["offset"] == {"type": "integer", "minimum": 0}
    assert effect == "read" and risk == 0 and capability is None
    assert "next_offset" in description


def test_skill_read_short_instructions_single_page(db_session, publisher):
    """短指南：整页返回、next_offset=None——旧行为（全文单发）对短文完全兼容。"""
    skill_id = _save_and_publish(publisher)
    text = "只做文本总结，不执行其它操作。"
    value = call_tool(db_session, user=publisher.user, claims={}, allowed=set(),
                      name="skill_read", arguments={"skill_id": skill_id})
    assert value["instructions"] == text
    assert value["offset"] == 0 and value["next_offset"] is None
    assert value["total_characters"] == len(text)


def test_skill_read_long_instructions_pages_and_continues(db_session, publisher):
    """长指南：首读 16k 窗口 + next_offset 续取；拼接逐字等于原文。"""
    tail = "尾段内容，续页可得。"
    text = ("甲" * (_WINDOW + 500)) + tail
    skill_id = _save_and_publish(publisher, instructions=text)

    first = call_tool(db_session, user=publisher.user, claims={}, allowed=set(),
                      name="skill_read", arguments={"skill_id": skill_id})
    assert len(first["instructions"]) == _WINDOW
    assert first["next_offset"] == _WINDOW
    assert first["total_characters"] == len(text)

    second = call_tool(db_session, user=publisher.user, claims={}, allowed=set(),
                       name="skill_read",
                       arguments={"skill_id": skill_id, "offset": first["next_offset"]})
    assert second["instructions"] == text[_WINDOW:]
    assert second["offset"] == _WINDOW and second["next_offset"] is None

    # 分页无损：两页拼接逐字等于原文
    assert first["instructions"] + second["instructions"] == text


def test_skill_read_rejects_invalid_offset(db_session, publisher):
    """偏移形状闸：负数/非整数 → 400 invalid_request（不泄内层）。"""
    skill_id = _save_and_publish(publisher)
    for bad in (-1, "0", 1.5, [0], None):
        with pytest.raises(ControlServiceError) as excinfo:
            call_tool(db_session, user=publisher.user, claims={}, allowed=set(),
                      name="skill_read", arguments={"skill_id": skill_id, "offset": bad})
        assert excinfo.value.status == 400
        assert excinfo.value.code == "invalid_request"


def test_skill_read_counts_usage_once_per_read_session(db_session, publisher):
    """T-S2 计数随分页收敛：首读计一次，续页不重复计；未知技能 404 不计。"""
    text = "甲" * (_WINDOW + 10)
    skill_id = _save_and_publish(publisher, instructions=text)
    db_session.rollback()

    first = call_tool(db_session, user=publisher.user, claims={}, allowed=set(),
                      name="skill_read", arguments={"skill_id": skill_id})
    assert first["next_offset"] is not None
    db_session.rollback()  # 直连工具循环每轮 tool 后就这么做（ai_tool_loop._run_tools 语义）
    assert len(_usage_events(db_session, skill_id)) == 1

    call_tool(db_session, user=publisher.user, claims={}, allowed=set(),
              name="skill_read", arguments={"skill_id": skill_id, "offset": first["next_offset"]})
    db_session.rollback()
    assert len(_usage_events(db_session, skill_id)) == 1  # 续页不加计

    with pytest.raises(ControlServiceError) as excinfo:
        call_tool(db_session, user=publisher.user, claims={}, allowed=set(),
                  name="skill_read", arguments={"skill_id": f"missing-{uuid4().hex[:6]}"})
    assert excinfo.value.status == 404
    db_session.rollback()
    assert len(_usage_events(db_session, skill_id)) == 1
