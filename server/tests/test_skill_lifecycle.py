"""V3 T-S1：Skill 治理态——draft/in_review/published/deprecated 全生命周期。

覆盖 agent-policy-v1 §2.5 七用例族（形态随 WB 既有服务语义落地，偏差见 backlog
T-S1 实施记录）：
- 公共 Skill 保存即 draft，未发布不出现在 MCP 工具面（mcp_gateway._skills）与
  工作流 skill.ref 白名单（published_skill_refs）；
- 发布四闸：admin / 密码确认（invalid_password 403）/ in_review / 测试报告或显式 waive；
- 携契约 schema + 测试报告的版本免 waive 直发；
- 编辑已发布 Skill → 新版本回 draft（重走治理），发布闸 409 not_in_review；
- 回滚 = published 内改指旧版本行（版本行不可变），同密码+材料闸；
- 弃用退出工具面并封死发布路径，复活=重新编辑；
- 个人 Skill 自发布豁免治理工作流（owner 自治，四闸只对公共 Skill）。
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from conftest import INITIAL_PASSWORD as PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.control.mcp_gateway import _skills as mcp_skills
from fde_api.control.models import SkillDefinition, UserAIAccessGrant
from fde_api.workflows.definition_service import published_skill_refs

from test_gates_api import AuthorizedClient


def _skill_payload(key=None, **extra):
    payload = {
        "key": key or f"skill-{uuid4().hex[:8]}",
        "name": "治理测试技能",
        "description": "T-S1 生命周期测试",
        "instructions": "只做文本总结，不执行其它操作。",
        "manifest": {"entrypoint": "SKILL.md", "format": "markdown"},
        "required_capabilities": [],
    }
    payload.update(extra)
    return payload


def _fresh(session):
    session.expire_all()


def _surface(session, user) -> set[str]:
    """MCP 工具面上的 skill_key 集合（allowed=空集 + required_capabilities=[] 即可入围）。"""
    return {skill.skill_key for skill, _version in mcp_skills(session, user, set())}


@pytest.fixture
def authorized_client_factory(client, db_session, settings):
    def create(role: str) -> AuthorizedClient:
        user = User(
            username=f"skilllife.{role}.{uuid4().hex[:8]}",
            display_name=f"SkillLife {role}",
            role=role,
            password_hash=hash_password(PASSWORD),
            must_change_password=False,
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        return AuthorizedClient(
            client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
        )

    return create


@pytest.fixture
def operator(authorized_client_factory, db_session):
    """admin + system_operator 档（公共 Skill 治理人）。"""
    client = authorized_client_factory("admin")
    db_session.add(
        UserAIAccessGrant(
            user_id=client.user.id,
            granted_by_user_id=client.user.id,
            access_level="system_operator",
            reason="skill lifecycle",
        )
    )
    db_session.commit()
    return client


def _save_public(operator, **extra):
    response = operator.post(
        "/api/v1/extensions/skills/public", json=_skill_payload(**extra)
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]


def _publish(operator, skill_id, *, waive="治理测试豁免：生命周期用例", **extra):
    submitted = operator.post(
        f"/api/v1/extensions/skills/{skill_id}/submit-review", json={}
    )
    # 已在 in_review（如用例先行单独提交过）也算就绪
    assert submitted.status_code == 200 or (
        submitted.status_code == 409
        and submitted.get_json()["error"]["code"] == "not_submittable"
    ), submitted.get_json()
    body = {"password": PASSWORD, **extra}
    if waive is not None:
        body["waive_reason"] = waive
    return operator.post(f"/api/v1/extensions/skills/{skill_id}/publish", json=body)


def test_public_skill_lifecycle_publish_gates(db_session, authorized_client_factory, operator):
    """保存即 draft → 四闸逐一可见 → waive 发布 → 工具面/白名单/审核戳齐。"""
    viewer = authorized_client_factory("viewer")
    data = _save_public(operator)
    skill_id, key = data["id"], data["key"]
    assert data["status"] == "draft"

    _fresh(db_session)
    assert key not in published_skill_refs(db_session)
    assert key not in _surface(db_session, viewer.user)

    # 非治理人提交审核 → 403；重复提交 → 409
    denied = viewer.post(f"/api/v1/extensions/skills/{skill_id}/submit-review", json={})
    assert denied.status_code == 403
    assert (
        operator.post(f"/api/v1/extensions/skills/{skill_id}/submit-review", json={}).status_code
        == 200
    )
    again = operator.post(f"/api/v1/extensions/skills/{skill_id}/submit-review", json={})
    assert again.status_code == 409 and again.get_json()["error"]["code"] == "not_submittable"

    # 密码闸：错误密码 403 invalid_password
    wrong = operator.post(
        f"/api/v1/extensions/skills/{skill_id}/publish",
        json={"password": "wrong-password", "waive_reason": "x"},
    )
    assert wrong.status_code == 403 and wrong.get_json()["error"]["code"] == "invalid_password"

    # 材料闸：无测试报告且无 waive → 409
    gated = operator.post(
        f"/api/v1/extensions/skills/{skill_id}/publish", json={"password": PASSWORD}
    )
    assert gated.status_code == 409
    assert gated.get_json()["error"]["code"] == "test_report_required"

    published = _publish(operator, skill_id)
    assert published.status_code == 200, published.get_json()
    body = published.get_json()["data"]
    assert body["status"] == "published" and body["published_at"] is not None

    _fresh(db_session)
    assert f"{key}@1" in published_skill_refs(db_session)
    assert key in _surface(db_session, viewer.user)

    versions = viewer.get(f"/api/v1/extensions/skills/{skill_id}/versions")
    assert versions.status_code == 200
    rows = versions.get_json()["data"]["versions"]
    assert len(rows) == 1 and rows[0]["is_current"] and rows[0]["has_test_report"] is False
    assert rows[0]["reviewed_by_user_id"] == operator.user.id


def test_contract_and_test_report_publish_without_waive(db_session, operator):
    """携 input/output schema + 测试报告的版本：免 waive 直发。"""
    schema = {"type": "object", "properties": {"text": {"type": "string"}}}
    data = _save_public(
        operator,
        input_schema=schema,
        output_schema=schema,
        test_report={"cases": 3, "passed": 3, "source": "lifecycle-test"},
    )
    published = _publish(operator, data["id"], waive=None)
    assert published.status_code == 200, published.get_json()

    rows = operator.get(f"/api/v1/extensions/skills/{data['id']}/versions").get_json()["data"]["versions"]
    assert rows[0]["has_test_report"] is True
    assert rows[0]["input_schema"] == schema and rows[0]["output_schema"] == schema


def test_edit_resets_published_skill_to_draft(db_session, authorized_client_factory, operator):
    """编辑已发布公共 Skill → 新版本回 draft（退出工具面/白名单），重走治理后 v2 发布。"""
    viewer = authorized_client_factory("viewer")
    data = _save_public(operator)
    key = data["key"]
    assert _publish(operator, data["id"]).status_code == 200
    _fresh(db_session)
    assert f"{key}@1" in published_skill_refs(db_session)

    # 公共 Skill 的旧开关不能旁路发布闸（桌面兼容语义：409 指路 submit-review/publish）
    bypass = operator.patch(
        f"/api/v1/extensions/skills/{data['id']}", json={"status": "active"}
    )
    assert bypass.status_code == 409
    assert bypass.get_json()["error"]["code"] == "governance_required"

    edited = operator.post(
        "/api/v1/extensions/skills/public",
        json=_skill_payload(key=key, instructions="新版本指令：补充输出格式要求。"),
    )
    assert edited.status_code == 201
    body = edited.get_json()["data"]
    assert body["status"] == "draft" and body["current_version"] == 2

    # 草稿期：发布闸直接拦（须先提交审核），白名单/工具面退出
    _fresh(db_session)
    assert published_skill_refs(db_session) == set() or all(
        not ref.startswith(f"{key}@") for ref in published_skill_refs(db_session)
    )
    assert key not in _surface(db_session, viewer.user)
    early = operator.post(
        f"/api/v1/extensions/skills/{data['id']}/publish",
        json={"password": PASSWORD, "waive_reason": "x"},
    )
    assert early.status_code == 409 and early.get_json()["error"]["code"] == "not_in_review"

    assert _publish(operator, data["id"]).status_code == 200
    _fresh(db_session)
    assert f"{key}@2" in published_skill_refs(db_session)


def test_rollback_restores_previous_version_with_gates(db_session, operator):
    """回滚 = published 内改指旧版本行；目标版本同样过材料闸；同版本/未知版本 409/404。"""
    key = f"rollback-{uuid4().hex[:8]}"
    v1 = _save_public(operator, key=key)
    assert _publish(operator, v1["id"]).status_code == 200
    v2 = operator.post(
        "/api/v1/extensions/skills/public",
        json=_skill_payload(key=key, instructions="第二版指令。"),
    ).get_json()["data"]
    assert _publish(operator, v2["id"]).status_code == 200

    # 目标版本（v1）无测试报告 → 须 waive
    gated = operator.post(
        f"/api/v1/extensions/skills/{v1['id']}/rollback",
        json={"version": 1, "password": PASSWORD},
    )
    assert gated.status_code == 409
    assert gated.get_json()["error"]["code"] == "test_report_required"

    rolled = operator.post(
        f"/api/v1/extensions/skills/{v1['id']}/rollback",
        json={"version": 1, "password": PASSWORD, "waive_reason": "回滚到 v1 复核"},
    )
    assert rolled.status_code == 200, rolled.get_json()
    assert rolled.get_json()["data"]["current_version"] == 1

    same = operator.post(
        f"/api/v1/extensions/skills/{v1['id']}/rollback",
        json={"version": 1, "password": PASSWORD, "waive_reason": "x"},
    )
    assert same.status_code == 409 and same.get_json()["error"]["code"] == "already_current"
    missing = operator.post(
        f"/api/v1/extensions/skills/{v1['id']}/rollback",
        json={"version": 9, "password": PASSWORD, "waive_reason": "x"},
    )
    assert missing.status_code == 404 and missing.get_json()["error"]["code"] == "version_not_found"


def test_deprecate_exits_surface_and_blocks_publish(db_session, authorized_client_factory, operator):
    """弃用退出工具面/白名单；重复弃用 409；弃用后发布 409（复活=重新编辑）。"""
    viewer = authorized_client_factory("viewer")
    data = _save_public(operator)
    key = data["key"]
    assert _publish(operator, data["id"]).status_code == 200
    _fresh(db_session)
    assert key in _surface(db_session, viewer.user)

    deprecated = operator.post(f"/api/v1/extensions/skills/{data['id']}/deprecate", json={})
    assert deprecated.status_code == 200
    assert deprecated.get_json()["data"]["status"] == "deprecated"

    _fresh(db_session)
    assert key not in _surface(db_session, viewer.user)
    assert all(not ref.startswith(f"{key}@") for ref in published_skill_refs(db_session))

    again = operator.post(f"/api/v1/extensions/skills/{data['id']}/deprecate", json={})
    assert again.status_code == 409 and again.get_json()["error"]["code"] == "not_deprecatable"
    blocked = operator.post(
        f"/api/v1/extensions/skills/{data['id']}/publish",
        json={"password": PASSWORD, "waive_reason": "x"},
    )
    assert blocked.status_code == 409 and blocked.get_json()["error"]["code"] == "not_in_review"


def test_personal_skills_are_self_published(db_session, authorized_client_factory):
    """个人 Skill 自发布豁免治理：保存即 published 进 owner 工具面；版本视图 owner-only。"""
    engineer = authorized_client_factory("project_lead")
    stranger = authorized_client_factory("viewer")
    response = engineer.post("/api/v1/extensions/skills/personal", json=_skill_payload())
    assert response.status_code == 201, response.get_json()
    body = response.get_json()["data"]
    assert body["status"] == "published" and body["published_at"] is not None

    _fresh(db_session)
    assert body["key"] in _surface(db_session, engineer.user)
    assert body["key"] not in _surface(db_session, stranger.user)

    own = engineer.get(f"/api/v1/extensions/skills/{body['id']}/versions")
    assert own.status_code == 200 and own.get_json()["data"]["versions"][0]["is_current"]
    leaked = stranger.get(f"/api/v1/extensions/skills/{body['id']}/versions")
    assert leaked.status_code == 404

    # 既有 PATCH 开关与治理态调和：个人 published 幂等 no-op；公共被 409 指路治理流
    noop = engineer.patch(
        f"/api/v1/extensions/skills/{body['id']}", json={"status": "active"}
    )
    assert noop.status_code == 200 and noop.get_json()["data"]["status"] == "published"

    # 个人 Skill 无治理操作面：权限闸先于 scope 检查——非治理人 403（不区分存在性），
    # 治理人（admin）对 personal 拿 404（scope!=public）
    payload = {"password": PASSWORD, "waive_reason": "x", "version": 1}
    for action in ("submit-review", "publish", "rollback", "deprecate"):
        path = f"/api/v1/extensions/skills/{body['id']}/{action}"
        assert engineer.post(path, json=payload).status_code == 403


def test_skill_definitions_constraint_accepts_governance_states(db_session):
    """模型 CHECK 已切治理四态：published/draft 可落库（迁移往返由 test_migrations 钉）。"""
    from fde_api.auth.passwords import hash_password

    owner = User(
        username=f"skilllife.ck.{uuid4().hex[:8]}",
        display_name="SkillLife CK",
        role="project_lead",
        password_hash=hash_password(PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(owner)
    db_session.flush()
    for status in ("draft", "in_review", "published", "deprecated"):
        db_session.add(
            SkillDefinition(
                scope="public",
                namespace_key="lifecycle-test",
                skill_key=f"ck-{status}-{uuid4().hex[:6]}",
                name="状态域自检",
                description="",
                status=status,
                current_version_number=1,
                created_by_user_id=owner.id,
            )
        )
    db_session.commit()
    rows = db_session.scalars(
        select(SkillDefinition).where(SkillDefinition.namespace_key == "lifecycle-test")
    ).all()
    assert {row.status for row in rows} == {"draft", "in_review", "published", "deprecated"}
