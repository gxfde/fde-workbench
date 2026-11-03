"""V3 T-W3/T-W4/T-W5：workflow 执行器——四类节点、节点独立事务、断链不静默、幂等恢复。

覆盖设计 workflow-dag-v1 §6 用例 4-8、11（§5 路由与权限随本文件一起钉住）：
- run 生命周期：published 闸 / 未知节点 422 / 幂等键同 run 返回（用例 5）/ 取消（用例 8）；
- 执行循环：占位符解析（缺键→failed 不填空串）/ 版本钉住（用例 7）/ 断链 failed+skipped
  不静默 done（用例 11）/ 重试后成功与耗尽恢复复用产物（用例 4）；
- 外副作用幂等：写类 call 节点 idempotency_key 与 api_actions 同构、跨重试/恢复稳定
  （用例 6）；outbox→worker 全链与 reconcile 放弃钩子；
- T-W4：agent 节点走 agents.start_run 全闸（拒绝不重试 / run 失败不叠加工作流重试）、
  human_approval 复用 automation_approvals（waiting→拍板→重投；拒绝/过期断链；
  等待中取消；幂等重入不重复建审批）；
- T-W5：cancel/resume 的 HTTP 面（幂等取消 / failed-only 恢复 / 权限与错误码）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from test_agents_d4_harness import (  # noqa: F401  (pytest fixture 再导出)
    ScriptedEvents,
    d4_app,
    d4_settings,
    make_user,
    prime_run,
    seed_agent,
)
from test_document_drafts_api import _add_viewer_member, _persist_project
from test_gates_api import AuthorizedClient
from test_workflow_definition import _dag

from conftest import INITIAL_PASSWORD
from fde_api.agents.models import AgentRun
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.control.api_catalog import CATALOG
from fde_api.control.dsh_runtime import DSHRuntimeError
from fde_api.control.models import AutomationApproval, SkillDefinition, SkillVersion
from fde_api.control.service import ControlServiceError, decide_automation_approval
from fde_api.jobs.handlers import get_handler
from fde_api.jobs.models import BackgroundJob
from fde_api.jobs.outbox import dispatch_pending, utcnow
from fde_api.jobs.reconcile import RECOVERABLE_JOB_TYPES, reconcile_jobs
from fde_api.jobs.worker import run_job
from fde_api.workbench.models import OperationEvent
from fde_api.workflows.definition_service import (
    create_definition,
    dag_sha256,
    publish_definition,
    update_definition_dag,
)
from fde_api.workflows.executor import (
    WORKFLOW_JOB_TYPE,
    WorkflowRunError,
    cancel_run,
    list_platform_definitions,
    resume_run,
    run_workflow_run,
    start_run,
)
from fde_api.workflows.models import WorkflowNodeRun, WorkflowRun

READ_REF = "modules.catalog"
WRITE_REF = "projects.create"


# ---------------------------------------------------------------------------
# 造数与假件
# ---------------------------------------------------------------------------


def _node(key, deps=(), *, ref=READ_REF, **extra):
    return {"key": key, "type": "call", "ref": ref, "depends_on": list(deps), **extra}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _make_definition(db_session, leader, project, *nodes, publish=False):
    dag = _dag(*(nodes or (_node("gather", output="subjects"),)))
    definition = create_definition(
        db_session, actor=leader, project_id=project.id, name=f"编排{uuid4().hex[:4]}", dag=dag
    )
    if publish:
        publish_definition(db_session, actor=leader, definition=definition)
    db_session.commit()
    return definition


def _start(db_session, leader, project, definition, **kwargs):
    run, created = start_run(
        db_session,
        actor=leader,
        project_id=project.id,
        definition_id=definition.id,
        **kwargs,
    )
    db_session.commit()
    return run, created


def _node_map(db_session, run_id) -> dict[str, WorkflowNodeRun]:
    return {
        node.node_key: node
        for node in db_session.scalars(
            select(WorkflowNodeRun).where(WorkflowNodeRun.run_id == run_id)
        )
    }


def _install_fake_api(monkeypatch, calls: list, *, fail_times: int = 0, error_status: int = 404):
    """假 execute_api：记录调用；前 fail_times 次抛 ControlServiceError。"""
    from fde_api.control import api_actions

    def fake_execute_api(**kwargs):
        calls.append(
            {
                "operation": kwargs["operation"],
                "parameters": kwargs.get("parameters"),
                "body": kwargs.get("body"),
                "query": kwargs.get("query"),
                "execution_id": kwargs["claims"].get("execution_id"),
                "project_id": kwargs["claims"].get("project_id"),
                "user_id": kwargs["user"].id,
            }
        )
        if len(calls) <= fail_times:
            raise ControlServiceError("transient", "临时失败。", error_status)
        return {"http_status": 200, "result": {"items": [1, 2, 3]}}

    monkeypatch.setattr(api_actions, "execute_api", fake_execute_api)


def _install_fake_ai(monkeypatch, calls: list, *, fail_times: int = 0):
    """假 execute_ai_prompt：记录调用（system_prompt/prompt/execution_id）。"""
    from fde_api.control import ai_server_client

    def fake_execute_ai_prompt(**kwargs):
        calls.append(kwargs)
        if len(calls) <= fail_times:
            raise DSHRuntimeError("dsh_timeout", "DSH 执行超时，请稍后重试。", retryable=True)
        return "润色结果"

    monkeypatch.setattr(ai_server_client, "execute_ai_prompt", fake_execute_ai_prompt)


def _zero_backoff(monkeypatch) -> None:
    from fde_api.workflows import executor

    monkeypatch.setattr(executor, "_RETRY_BACKOFF_BASE_SECONDS", 0)


def _seed_skill(db_session, leader, *, key: str, versions: list[str]) -> SkillDefinition:
    skill = SkillDefinition(
        scope="public",
        namespace_key="test",
        skill_key=key,
        name="测试技能",
        description="",
        status="published",
        current_version_number=len(versions),
        created_by_user_id=leader.id,
    )
    db_session.add(skill)
    db_session.flush()
    for index, instructions in enumerate(versions, start=1):
        db_session.add(
            SkillVersion(
                skill_id=skill.id,
                version_number=index,
                instructions_text=instructions,
                manifest_json={},
                required_capabilities=[],
                content_sha256=_sha(f"{key}:{index}:{instructions}"),
                created_by_user_id=leader.id,
            )
        )
    db_session.commit()
    return skill


def _client_for(client, db_session, settings, *, role: str) -> AuthorizedClient:
    user = User(
        username=f"wfexec.{role}.{uuid4().hex[:8]}",
        display_name=f"WfExec {role}",
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return AuthorizedClient(
        client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    )


# ---------------------------------------------------------------------------
# run 生命周期（§6 用例 5 / 未支持类型 / published 闸）
# ---------------------------------------------------------------------------


def test_start_run_requires_published_definition(db_session, settings):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    definition = _make_definition(db_session, leader, project, _node("gather"))

    with pytest.raises(WorkflowRunError) as raised:
        _start(db_session, leader, project, definition)
    assert raised.value.status == 409 and raised.value.code == "definition_not_published"

    publish_definition(db_session, actor=leader, definition=definition)
    db_session.commit()
    run, created = _start(db_session, leader, project, definition)
    assert created and run.status == "queued" and run.definition_version == 1


def test_start_run_rejects_unknown_node_types(db_session, settings):
    """执行器侧防御守卫：四类之外的类型在 start_run 即 422（不留必死 run）。

    定义期校验本就会拦未知类型（T-W1 规则 3），此守卫防的是发布后白名单漂移
    （校验器放行了一个执行器尚未实现的类型）——手工绕过定义期校验构造该场景。
    """
    from fde_api.jobs.outbox import utcnow
    from fde_api.workflows.models import WorkflowDefinition, WorkflowDefinitionVersion

    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    dag = {"nodes": [{"key": "wait", "type": "wait", "depends_on": []}]}
    definition = WorkflowDefinition(
        project_id=project.id,
        name=f"漂移{uuid4().hex[:4]}",
        dag_json=dag,
        status="published",
        version=1,
        created_by_user_id=leader.id,
    )
    db_session.add(definition)
    db_session.flush()
    db_session.add(
        WorkflowDefinitionVersion(
            definition_id=definition.id,
            version=1,
            dag_json=dag,
            content_sha256=dag_sha256(dag),
            published_by_user_id=leader.id,
            published_at=utcnow(),
        )
    )
    db_session.commit()
    with pytest.raises(WorkflowRunError) as raised:
        _start(db_session, leader, project, definition)
    assert raised.value.status == 422 and raised.value.code == "unsupported_node_type"
    assert raised.value.detail["node_types"] == ["wait"]


def test_start_run_idempotency_key_returns_same_run(db_session, settings):
    """§6 用例 5：同幂等键返回同一 run；跨项目同键 409（FV-F3 全局唯一）。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    other = _persist_project(db_session, leader, code=f"WF{uuid4().hex[:4]}")
    definition = _make_definition(db_session, leader, project, _node("gather"), publish=True)

    key = f"biz-{uuid4().hex}"
    first, created_first = _start(db_session, leader, project, definition, idempotency_key=key)
    second, created_second = _start(db_session, leader, project, definition, idempotency_key=key)
    assert created_first and not created_second and first.id == second.id

    with pytest.raises(WorkflowRunError) as raised:
        _start(db_session, leader, other, definition, idempotency_key=key)
    assert raised.value.status == 409 and raised.value.code == "idempotency_conflict"

    auto, _ = _start(db_session, leader, project, definition)
    assert auto.idempotency_key and auto.idempotency_key != key


# ---------------------------------------------------------------------------
# §5 路由与权限
# ---------------------------------------------------------------------------


def test_routes_create_publish_start_detail_and_permissions(
    db_session, settings, client
):
    leader = _client_for(client, db_session, settings, role="project_lead")
    admin = _client_for(client, db_session, settings, role="admin")
    viewer = _client_for(client, db_session, settings, role="viewer")
    project = _persist_project(db_session, leader.user, code=f"WE{uuid4().hex[:4]}")
    _add_viewer_member(db_session, project, viewer.user)

    dag = _dag(_node("gather", output="subjects", params={"project_id": "{{project_id}}"}))
    # 项目负责人建定义 → 201 draft
    response = leader.post(
        f"/api/v1/projects/{project.id}/workflows", json={"name": "编排", "dag": dag}
    )
    assert response.status_code == 201, response.get_json()
    definition_id = response.get_json()["data"]["definition"]["id"]
    assert response.get_json()["data"]["definition"]["status"] == "draft"

    # leader 发布 → 403（§5：admin）；admin 发布 → 200 锁版
    assert (
        leader.post(
            f"/api/v1/projects/{project.id}/workflows/{definition_id}/publish", json={}
        ).status_code
        == 403
    )
    published = admin.post(
        f"/api/v1/projects/{project.id}/workflows/{definition_id}/publish", json={}
    )
    assert published.status_code == 200, published.get_json()
    assert published.get_json()["data"]["version"] == 1

    # 发起运行：201 created；同幂等键重放 → 200 created=false
    body = {"context": {}, "idempotency_key": f"route-{uuid4().hex}"}
    started = leader.post(
        f"/api/v1/projects/{project.id}/workflows/{definition_id}/runs", json=body
    )
    assert started.status_code == 201, started.get_json()
    run_id = started.get_json()["data"]["run"]["id"]
    replay = leader.post(
        f"/api/v1/projects/{project.id}/workflows/{definition_id}/runs", json=body
    )
    assert replay.status_code == 200
    assert replay.get_json()["data"]["run"]["id"] == run_id
    assert replay.get_json()["data"]["created"] is False

    # 详情：负责人 / 成员 viewer 200
    detail = leader.get(f"/api/v1/projects/{project.id}/workflow-runs/{run_id}")
    assert detail.status_code == 200
    payload = detail.get_json()["data"]["run"]
    assert payload["status"] == "queued" and len(payload["nodes"]) == 1
    assert viewer.get(f"/api/v1/projects/{project.id}/workflow-runs/{run_id}").status_code == 200

    # 跨项目（负责人自己的另一个项目，无此 run）→ 404
    other = _persist_project(db_session, leader.user, code=f"WF{uuid4().hex[:4]}")
    assert leader.get(f"/api/v1/projects/{other.id}/workflow-runs/{run_id}").status_code == 404


def test_create_route_rejects_cycle_with_dag_invalid(db_session, settings, client):
    leader = _client_for(client, db_session, settings, role="project_lead")
    project = _persist_project(db_session, leader.user, code=f"WE{uuid4().hex[:4]}")
    cycle = _dag(_node("a", ["b"]), _node("b", ["a"]))
    response = leader.post(
        f"/api/v1/projects/{project.id}/workflows", json={"name": "环", "dag": cycle}
    )
    assert response.status_code == 422
    error = response.get_json()["error"]
    assert error["code"] == "dag_invalid"
    assert any(issue["code"] == "cycle_detected" for issue in error["details"]["errors"])


def test_platform_templates_route_admin_only_and_runs_in_project(db_session, settings, client):
    """平台模板（project_id NULL）：GET /api/v1/workflows 仅 admin；模板可在项目内实例化。"""
    admin = _client_for(client, db_session, settings, role="admin")
    leader = _client_for(client, db_session, settings, role="project_lead")
    project = _persist_project(db_session, leader.user, code=f"WE{uuid4().hex[:4]}")
    template = create_definition(
        db_session,
        actor=admin.user,
        project_id=None,
        name=f"平台模板{uuid4().hex[:4]}",
        dag=_dag(_node("gather")),
    )
    publish_definition(db_session, actor=admin.user, definition=template)
    db_session.commit()

    assert leader.get("/api/v1/workflows").status_code == 403
    listed = admin.get("/api/v1/workflows")
    assert listed.status_code == 200
    assert template.id in [item["id"] for item in listed.get_json()["data"]["items"]]

    with pytest.raises(WorkflowRunError) as raised:
        list_platform_definitions(actor=leader.user)
    assert raised.value.status == 403

    run, created = _start(db_session, leader.user, project, template)
    assert created and run.project_id == project.id


def test_routes_cancel_and_resume_lifecycle_and_permissions(
    db_session, settings, client
):
    """T-W5：cancel/resume 的 HTTP 面——幂等取消 / failed-only 恢复 / 权限与跨项目 404。

    服务层语义（已执行保留、waiting 审批中和、重投 outbox）由本文件既有服务级用例
    钉住；此处验证 §5 路由挂接、can_manage 闸与 §5 错误码。
    """
    leader = _client_for(client, db_session, settings, role="project_lead")
    viewer = _client_for(client, db_session, settings, role="viewer")
    project = _persist_project(db_session, leader.user, code=f"WE{uuid4().hex[:4]}")
    _add_viewer_member(db_session, project, viewer.user)
    definition = _make_definition(
        db_session, leader.user, project, _node("gather"), publish=True
    )

    # 取消：viewer 403 → leader 200 cancelled=true（未执行节点 cancelled）；重复取消幂等
    run, _ = _start(db_session, leader.user, project, definition)
    cancel_url = f"/api/v1/projects/{project.id}/workflow-runs/{run.id}/cancel"
    assert viewer.post(cancel_url, json={}).status_code == 403
    cancelled = leader.post(cancel_url, json={})
    assert cancelled.status_code == 200, cancelled.get_json()
    assert cancelled.get_json()["data"]["cancelled"] is True
    assert cancelled.get_json()["data"]["run"]["status"] == "cancelled"
    again = leader.post(cancel_url, json={})
    assert again.status_code == 200 and again.get_json()["data"]["cancelled"] is False

    # 终态不可取消（§5 错误码 already_terminal）；跨项目 404 不泄露存在性
    done, _ = _start(db_session, leader.user, project, definition)
    done.status = "succeeded"  # 直改终态以验证 409 分支（check 约束内合法值）
    db_session.commit()
    done_response = leader.post(
        f"/api/v1/projects/{project.id}/workflow-runs/{done.id}/cancel", json={}
    )
    assert done_response.status_code == 409
    assert done_response.get_json()["error"]["code"] == "already_terminal"
    other = _persist_project(db_session, leader.user, code=f"WF{uuid4().hex[:4]}")
    assert (
        leader.post(
            f"/api/v1/projects/{other.id}/workflow-runs/{run.id}/cancel", json={}
        ).status_code
        == 404
    )

    # 恢复：仅 failed 可恢复 → running + failed 节点放回 pending；其余 409 not_resumable
    failed, _ = _start(db_session, leader.user, project, definition)
    nodes = _node_map(db_session, failed.id)
    nodes["gather"].status = "failed"
    nodes["gather"].error = "transient:临时失败。"
    failed.status = "failed"  # 直改以验证 HTTP 面（服务层恢复语义已由用例 4 钉住）
    db_session.commit()
    resume_url = f"/api/v1/projects/{project.id}/workflow-runs/{failed.id}/resume"
    assert viewer.post(resume_url, json={}).status_code == 403
    resumed = leader.post(resume_url, json={})
    assert resumed.status_code == 200, resumed.get_json()
    payload = resumed.get_json()["data"]
    assert payload["run"]["status"] == "running" and payload["reset_nodes"] == 1
    assert payload["run"]["nodes"][0]["status"] == "pending"
    non_resumable = leader.post(
        f"/api/v1/projects/{project.id}/workflow-runs/{done.id}/resume", json={}
    )
    assert non_resumable.status_code == 409
    assert non_resumable.get_json()["error"]["code"] == "not_resumable"


# ---------------------------------------------------------------------------
# 执行循环：链路 / 占位符 / 版本钉住（§6 用例 7）
# ---------------------------------------------------------------------------


def test_executor_runs_chain_and_resolves_placeholders(db_session, settings, monkeypatch):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    calls: list = []
    _install_fake_api(monkeypatch, calls)
    definition = _make_definition(
        db_session,
        leader,
        project,
        _node("gather", output="subjects", params={"project_id": "{{project_id}}"}),
        _node(
            "draft",
            ["gather"],
            output="hint",
            params={"first": "{{subjects.result.items.0}}"},
        ),
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    run_workflow_run(run.id)

    fresh = db_session.get(WorkflowRun, run.id)
    db_session.expire(fresh)
    assert fresh.status == "succeeded" and fresh.error is None
    assert fresh.started_at is not None and fresh.finished_at is not None
    assert fresh.context_json["project_id"] == project.id
    assert fresh.context_json["run_id"] == run.id
    assert fresh.context_json["initiated_by_user_id"] == leader.id

    nodes = _node_map(db_session, run.id)
    assert nodes["gather"].status == "succeeded" and nodes["gather"].attempt == 1
    assert nodes["gather"].input_snapshot == {"project_id": project.id}
    assert nodes["gather"].output_json == {"http_status": 200, "result": {"items": [1, 2, 3]}}
    assert nodes["draft"].input_snapshot == {"first": 1}  # 原类型替换，不字符串化
    assert nodes["draft"].output_json == {"http_status": 200, "result": {"items": [1, 2, 3]}}
    assert [call["operation"] for call in calls] == [READ_REF, READ_REF]
    assert calls[0]["execution_id"].startswith("wfnode-")
    assert calls[0]["project_id"] == project.id
    assert calls[0]["user_id"] == leader.id

    events = db_session.scalars(
        select(OperationEvent)
        .where(
            OperationEvent.target_type == "workflow_run", OperationEvent.target_id == run.id
        )
        .order_by(OperationEvent.created_at, OperationEvent.id)
    ).all()
    assert [event.event_type for event in events] == [
        "workflow_run_created",
        "workflow_run_succeeded",
    ]


def test_definition_version_pinned_across_publish(db_session, settings, monkeypatch):
    """§6 用例 7：发布 v2 后旧 run 仍按 v1 快照展示与执行。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    calls: list = []
    _install_fake_api(monkeypatch, calls)
    definition = _make_definition(
        db_session, leader, project, _node("only", output="a"), publish=True
    )
    old_run, _ = _start(db_session, leader, project, definition)
    update_definition_dag(
        db_session, actor=leader, definition=definition, dag=_dag(_node("first"), _node("second", ["first"]))
    )
    publish_definition(db_session, actor=leader, definition=definition)
    db_session.commit()
    new_run, _ = _start(db_session, leader, project, definition)

    run_workflow_run(old_run.id)
    run_workflow_run(new_run.id)

    db_session.expire_all()
    assert old_run.definition_version == 1 and new_run.definition_version == 2
    assert set(_node_map(db_session, old_run.id)) == {"only"}
    assert set(_node_map(db_session, new_run.id)) == {"first", "second"}
    assert len(calls) == 3  # v1 一次 + v2 两次（各自按钉住版本执行）


# ---------------------------------------------------------------------------
# skill 节点（pinned 版本 + use_tools=False）
# ---------------------------------------------------------------------------


def test_skill_node_uses_pinned_version_instructions(db_session, settings, monkeypatch):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    skill = _seed_skill(db_session, leader, key="polisher", versions=["V1 指令", "V2 指令"])
    calls: list = []
    _install_fake_api(monkeypatch, calls)
    ai_calls: list = []
    _install_fake_ai(monkeypatch, ai_calls)
    definition = _make_definition(
        db_session,
        leader,
        project,
        _node("gather", output="subjects", params={"project_id": "{{project_id}}"}),
        {
            "key": "draft",
            "type": "skill",
            "ref": "polisher@1",  # 钉 v1（库里已有 v2）
            "depends_on": ["gather"],
            "output": "hint",
            "params": {"src": "{{subjects.result.items.1}}"},
        },
        _node("ship", ["draft"], params={"note": "{{hint.text}}"}),
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "succeeded"
    nodes = _node_map(db_session, run.id)
    assert nodes["draft"].status == "succeeded"
    assert nodes["draft"].output_json == {"text": "润色结果"}
    assert len(ai_calls) == 1
    assert ai_calls[0]["system_prompt"] == "V1 指令"  # 钉住版本，不是 current v2
    assert ai_calls[0]["use_tools"] is False
    assert ai_calls[0]["project_id"] == project.id
    assert ai_calls[0]["execution_id"].startswith("wfnode-")
    assert nodes["ship"].input_snapshot == {"note": "润色结果"}
    # V3 T-S2：pinned 版本完成一次确定性调用即消费——workflow 面计数钉 v1（不是 current v2）
    usage = db_session.scalars(
        select(OperationEvent).where(
            OperationEvent.target_type == "skill_definition",
            OperationEvent.target_id == skill.id,
            OperationEvent.event_type == "skill_used_workflow",
        )
    ).all()
    assert len(usage) == 1
    assert usage[0].actor_user_id == leader.id
    assert usage[0].changes == {"surface": "workflow", "version": 1}


# ---------------------------------------------------------------------------
# 失败 / 重试 / 恢复（§6 用例 4、11）
# ---------------------------------------------------------------------------


def test_node_failure_retries_then_succeeds(db_session, settings, monkeypatch):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    skill = _seed_skill(db_session, leader, key="flaky", versions=["指令"])
    _install_fake_api(monkeypatch, [])
    ai_calls: list = []
    _install_fake_ai(monkeypatch, ai_calls, fail_times=2)
    _zero_backoff(monkeypatch)
    definition = _make_definition(
        db_session,
        leader,
        project,
        {
            "key": "draft",
            "type": "skill",
            "ref": "flaky@1",
            "max_retries": 2,
        },
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "succeeded"
    nodes = _node_map(db_session, run.id)
    assert nodes["draft"].attempt == 3 and nodes["draft"].status == "succeeded"
    assert len(ai_calls) == 3
    # V3 T-S2：失败 attempt 不计消费——3 次 AI 调用只有成功那次落 1 条 skill_used_workflow
    usage = db_session.scalars(
        select(OperationEvent).where(
            OperationEvent.target_type == "skill_definition",
            OperationEvent.target_id == skill.id,
            OperationEvent.event_type == "skill_used_workflow",
        )
    ).all()
    assert len(usage) == 1 and usage[0].changes == {"surface": "workflow", "version": 1}


def test_retries_exhausted_run_failed_and_resume_reuses_outputs(
    db_session, settings, monkeypatch
):
    """§6 用例 4：耗尽 → run failed（§3 终态语义优先于「paused」）；恢复只补跑
    失败/跳过节点，已完成节点产物复用（不重复执行）。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    _seed_skill(db_session, leader, key="flaky", versions=["指令"])
    api_calls: list = []
    _install_fake_api(monkeypatch, api_calls)
    _install_fake_ai(monkeypatch, [], fail_times=99)
    _zero_backoff(monkeypatch)
    definition = _make_definition(
        db_session,
        leader,
        project,
        _node("gather", output="subjects"),
        {
            "key": "draft",
            "type": "skill",
            "ref": "flaky@1",
            "depends_on": ["gather"],
            "max_retries": 1,
        },
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    run_workflow_run(run.id)

    db_session.expire_all()
    failed = db_session.get(WorkflowRun, run.id)
    assert failed.status == "failed"
    nodes = _node_map(db_session, run.id)
    assert nodes["gather"].status == "succeeded" and nodes["gather"].attempt == 1
    assert nodes["draft"].status == "failed" and nodes["draft"].attempt == 2  # 1 + max_retries

    # 恢复：AI 修好后只补跑 draft；gather 的 output 原样复用
    monkeypatch.setattr("fde_api.control.ai_server_client.execute_ai_prompt", lambda **kw: "好了")
    result = resume_run(actor=leader, project_id=project.id, run_id=run.id)
    assert result["reset_nodes"] == 1
    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "succeeded"
    nodes = _node_map(db_session, run.id)
    assert nodes["gather"].attempt == 1  # 未重复执行
    assert nodes["gather"].output_json == {"http_status": 200, "result": {"items": [1, 2, 3]}}
    assert nodes["draft"].attempt == 1 and nodes["draft"].status == "succeeded"
    assert len(api_calls) == 1


def test_broken_chain_not_silently_done(db_session, settings, monkeypatch):
    """§6 用例 11：上游 failed 且下游无 when → run failed、下游 skipped（不静默 done）。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    calls: list = []
    _install_fake_api(monkeypatch, calls, fail_times=1, error_status=404)
    definition = _make_definition(
        db_session,
        leader,
        project,
        _node("gather", output="subjects", max_retries=3),
        _node("draft", ["gather"]),
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "failed"
    nodes = _node_map(db_session, run.id)
    assert nodes["gather"].status == "failed"
    assert nodes["gather"].attempt == 1  # 404 非重试类：即使 max_retries=3 也不重试
    assert nodes["draft"].status == "skipped" and nodes["draft"].error == "upstream_not_succeeded"


def test_when_bypass_skips_failed_upstream_dependent(db_session, settings, monkeypatch):
    """when 引用失败上游 → 假值裁决 → skipped（不是 failed）；run 仍 failed。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    calls: list = []
    _install_fake_api(monkeypatch, calls, fail_times=1, error_status=404)
    definition = _make_definition(
        db_session,
        leader,
        project,
        _node("gather", output="subjects", max_retries=3),
        {"key": "draft", "type": "call", "ref": READ_REF, "depends_on": ["gather"], "when": "{{subjects}}"},
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "failed"
    nodes = _node_map(db_session, run.id)
    assert nodes["draft"].status == "skipped"  # when 假值：跳过而非失败


def test_missing_placeholder_fails_node_not_empty_string(db_session, settings, monkeypatch):
    """fde-v2 缺陷回归：占位符缺键 → 节点 failed 带 placeholder_missing，不填空串。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    calls: list = []
    _install_fake_api(monkeypatch, calls, fail_times=1, error_status=404)
    definition = _make_definition(
        db_session,
        leader,
        project,
        _node("gather", output="subjects", max_retries=3),
        {
            "key": "draft",
            "type": "call",
            "ref": READ_REF,
            "depends_on": ["gather"],
            "when": "{{run_id}}",  # 上下文恒真：放行执行
            "params": {"q": "{{subjects.result.items.0}}"},  # 上游 failed → 缺键
        },
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "failed"
    nodes = _node_map(db_session, run.id)
    assert nodes["draft"].status == "failed"
    assert nodes["draft"].error == "placeholder_missing:subjects.result.items.0"
    assert nodes["draft"].input_snapshot is None


# ---------------------------------------------------------------------------
# 外副作用幂等（§6 用例 6）
# ---------------------------------------------------------------------------


def test_write_call_node_idempotency_key_stable_across_retries(
    db_session, settings, monkeypatch
):
    """§6 用例 6：写类 call 节点幂等键 = api_actions 同构 sha256，跨重试稳定；
    execution_id 同键 ⇒ 真实 api_execute 层按 action 去重，不二次外呼。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    calls: list = []
    _install_fake_api(monkeypatch, calls, fail_times=1, error_status=503)  # 首次可重试失败
    _zero_backoff(monkeypatch)
    definition = _make_definition(
        db_session,
        leader,
        project,
        _node("create", ref=WRITE_REF, max_retries=2),
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "succeeded"
    node = _node_map(db_session, run.id)["create"]
    assert node.attempt == 2 and node.idempotency_key
    # 与 api_actions.execute_api 同构：sha256(json([user_id, "wfnode-{行id}", data]))
    expected = hashlib.sha256(
        json.dumps(
            [leader.id, f"wfnode-{node.id}", {"operation": WRITE_REF, "parameters": {}, "body": {}, "query": {}}],
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()
    assert node.idempotency_key == expected
    # 重试两次调用拿到同一 execution_id ⇒ 同 action id，api_execute 层去重
    assert calls[0]["execution_id"] == calls[1]["execution_id"] == f"wfnode-{node.id}"


def test_write_node_idempotency_survives_resume(db_session, settings, monkeypatch):
    """恢复轮：resume 后重派仍用同一节点行 id ⇒ 同幂等键，不二次外呼。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    calls: list = []
    _install_fake_api(monkeypatch, calls, fail_times=99, error_status=503)
    _zero_backoff(monkeypatch)
    definition = _make_definition(
        db_session, leader, project, _node("create", ref=WRITE_REF, max_retries=0), publish=True
    )
    run, _ = _start(db_session, leader, project, definition)
    run_workflow_run(run.id)
    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "failed"
    key_before = _node_map(db_session, run.id)["create"].idempotency_key

    monkeypatch.setattr(
        "fde_api.control.api_actions.execute_api",
        lambda **kwargs: {"http_status": 200, "result": {"ok": True}, "status": "completed"},
    )
    resume_run(actor=leader, project_id=project.id, run_id=run.id)
    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "succeeded"
    node = _node_map(db_session, run.id)["create"]
    assert node.idempotency_key == key_before  # 恢复不换键
    assert node.attempt == 1


# ---------------------------------------------------------------------------
# 取消（§6 用例 8）
# ---------------------------------------------------------------------------


def test_cancel_run_keeps_succeeded_and_cancels_pending(db_session, settings):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    definition = _make_definition(
        db_session,
        leader,
        project,
        _node("gather", output="subjects"),
        _node("draft", ["gather"]),
        _node("ship", ["draft"]),
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)
    # 模拟执行中途：gather 已成功、其余未启动
    nodes = _node_map(db_session, run.id)
    nodes["gather"].status = "succeeded"
    nodes["gather"].output_json = {"http_status": 200, "result": {}}
    db_session.commit()

    result = cancel_run(actor=leader, project_id=project.id, run_id=run.id)
    assert result["cancelled"] is True and result["run"]["status"] == "cancelled"
    by_key = {node["node_key"]: node for node in result["run"]["nodes"]}
    assert by_key["gather"]["status"] == "succeeded"  # 已执行保留（外呼不回收，诚实呈现）
    assert by_key["draft"]["status"] == "cancelled"
    assert by_key["ship"]["status"] == "cancelled"

    again = cancel_run(actor=leader, project_id=project.id, run_id=run.id)
    assert again["cancelled"] is False  # 幂等
    run_workflow_run(run.id)  # 终态：handler 直接返回
    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "cancelled"

    done_run, _ = _start(db_session, leader, project, definition)
    done_run.status = "succeeded"  # 直改终态以验证 409 分支（check 约束内合法值）
    db_session.commit()
    with pytest.raises(WorkflowRunError) as raised:
        cancel_run(actor=leader, project_id=project.id, run_id=done_run.id)
    assert raised.value.status == 409 and raised.value.code == "already_terminal"


# ---------------------------------------------------------------------------
# outbox → worker 全链 + reconcile 放弃钩子
# ---------------------------------------------------------------------------


def test_outbox_dispatch_and_worker_run_job_integration(db_session, settings, monkeypatch):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    calls: list = []
    _install_fake_api(monkeypatch, calls)
    definition = _make_definition(db_session, leader, project, _node("gather"), publish=True)
    run, _ = _start(db_session, leader, project, definition)

    class _Queue:
        def __init__(self):
            self.ids: list[str] = []

        def enqueue(self, job_id: str) -> None:
            self.ids.append(job_id)

    queue = _Queue()
    result = dispatch_pending(db_session, queue)
    assert result.dispatched == 1 and len(queue.ids) == 1
    db_session.commit()

    assert get_handler(WORKFLOW_JOB_TYPE) is not None
    assert run_job(queue.ids[0]) == "succeeded"

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "succeeded"
    job = db_session.scalars(
        select(BackgroundJob).where(
            BackgroundJob.job_type == WORKFLOW_JOB_TYPE, BackgroundJob.target_id == run.id
        )
    ).one()
    assert job.status == "succeeded"


def test_reconcile_treats_workflow_run_as_recoverable_and_fails_run_when_exhausted(
    db_session, settings, monkeypatch
):
    assert WORKFLOW_JOB_TYPE in RECOVERABLE_JOB_TYPES
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    definition = _make_definition(db_session, leader, project, _node("gather"), publish=True)
    run, _ = _start(db_session, leader, project, definition)
    job = BackgroundJob(job_type=WORKFLOW_JOB_TYPE, target_id=run.id, status="running",
                        attempts=5, max_attempts=5, locked_until=None)
    db_session.add(job)
    node = _node_map(db_session, run.id)["gather"]
    node.status = "running"  # worker 死亡时的悬挂态
    db_session.commit()

    class _Queue:
        def enqueue(self, job_id: str) -> None:  # pragma: no cover - 不应走到
            raise AssertionError("attempts exhausted must not requeue")

    result = reconcile_jobs(db_session, _Queue())
    assert result.failed == 1

    db_session.expire_all()
    settled = db_session.get(WorkflowRun, run.id)
    assert settled.status == "failed" and "worker_lost" in (settled.error or "")
    node = _node_map(db_session, run.id)["gather"]
    assert node.status == "failed" and node.error == "worker_lost"


# ---------------------------------------------------------------------------
# T-W4：human_approval 节点（复用 automation_approvals）
# ---------------------------------------------------------------------------


def _approval_definition(db_session, leader, project):
    return _make_definition(
        db_session,
        leader,
        project,
        _node("gather", output="subjects"),
        {
            "key": "approve",
            "type": "human_approval",
            "depends_on": ["gather"],
            "capability": "workbench.write",
            "output": "signoff",
        },
        _node("ship", ["approve"], params={"note": "{{signoff.decision}}"}),
        publish=True,
    )


def _waiting_approval(db_session, run_id, node_key="approve"):
    node = _node_map(db_session, run_id)[node_key]
    approval = db_session.scalar(
        select(AutomationApproval).where(AutomationApproval.workflow_node_run_id == node.id)
    )
    assert approval is not None
    return node, approval


def test_human_approval_wait_approve_then_resume(db_session, settings, monkeypatch):
    """§6 用例 10 前半：waiting_approval 挂起 → 任务中心批准 → 节点 succeeded → 重投收敛。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    calls: list = []
    _install_fake_api(monkeypatch, calls)
    definition = _approval_definition(db_session, leader, project)
    run, _ = _start(db_session, leader, project, definition)

    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "waiting_approval"
    node, approval = _waiting_approval(db_session, run.id)
    assert node.status == "waiting" and node.idempotency_key == approval.id
    assert approval.run_id is None and approval.status == "pending"
    assert approval.request_key == f"wfnode:{node.id}"
    assert approval.capability == "workbench.write" and approval.risk_level == 4
    assert approval.tool_name == "workflow.human_approval"
    assert approval.arguments_json["workflow_run_id"] == run.id
    assert approval.arguments_json["node_key"] == "approve"
    assert len(approval.arguments_sha256) == 64
    assert _node_map(db_session, run.id)["ship"].status == "pending"

    # 幂等重入：handler 重跑不建第二条审批
    run_workflow_run(run.id)
    count = db_session.scalar(
        select(func.count())
        .select_from(AutomationApproval)
        .where(AutomationApproval.workflow_node_run_id == node.id)
    )
    assert count == 1

    # 拍板批准（与任务中心同一入口 decide_automation_approval）：节点 succeeded
    decide_automation_approval(
        user=leader,
        approval_id=approval.id,
        decision_value="approve",
        password=INITIAL_PASSWORD,
        reason="放行",
    )
    db_session.expire_all()
    node, approval = _waiting_approval(db_session, run.id)
    assert approval.status == "approved" and node.status == "succeeded"
    assert node.output_json["decision"] == "approved"
    assert node.output_json["approval_id"] == approval.id

    run_workflow_run(run.id)  # 拍板重投后的 handler

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "succeeded"
    nodes = _node_map(db_session, run.id)
    assert nodes["ship"].status == "succeeded"
    assert nodes["ship"].input_snapshot == {"note": "approved"}
    assert len(calls) == 2
    events = {
        event.event_type
        for event in db_session.scalars(
            select(OperationEvent).where(
                OperationEvent.target_type == "workflow_run", OperationEvent.target_id == run.id
            )
        ).all()
    }
    assert "workflow_run_waiting_approval" in events
    assert "workflow_run_approval_decided" in events


def test_human_approval_rejected_fails_chain(db_session, settings, monkeypatch):
    """拒绝 → 节点 failed（断链语义）→ 重投后 run failed + 下游 skipped（FV-F1）。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    calls: list = []
    _install_fake_api(monkeypatch, calls)
    definition = _approval_definition(db_session, leader, project)
    run, _ = _start(db_session, leader, project, definition)
    run_workflow_run(run.id)
    db_session.expire_all()
    node, approval = _waiting_approval(db_session, run.id)

    decide_automation_approval(
        user=leader,
        approval_id=approval.id,
        decision_value="reject",
        password="",
        reason="不同意",
    )
    db_session.expire_all()
    node, approval = _waiting_approval(db_session, run.id)
    assert approval.status == "rejected"
    assert node.status == "failed" and node.error == "approval_rejected:不同意"

    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "failed"
    nodes = _node_map(db_session, run.id)
    assert nodes["ship"].status == "skipped" and nodes["ship"].error == "upstream_not_succeeded"


def test_human_approval_expiry_lazily_fails_node_on_decide(db_session, settings, monkeypatch):
    """§6 用例 10 后半：过审批复「拍板时惰性判定」语义 → 409 + 节点 failed → 断链。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    calls: list = []
    _install_fake_api(monkeypatch, calls)
    definition = _approval_definition(db_session, leader, project)
    run, _ = _start(db_session, leader, project, definition)
    run_workflow_run(run.id)
    db_session.expire_all()
    node, approval = _waiting_approval(db_session, run.id)
    approval.expires_at = utcnow() - timedelta(seconds=1)
    db_session.commit()

    with pytest.raises(ControlServiceError) as raised:
        decide_automation_approval(
            user=leader,
            approval_id=approval.id,
            decision_value="approve",
            password=INITIAL_PASSWORD,
            reason="迟到的拍板",
        )
    assert raised.value.status == 409 and raised.value.code == "approval_expired"

    db_session.expire_all()
    node, approval = _waiting_approval(db_session, run.id)
    assert approval.status == "expired"
    assert node.status == "failed" and node.error == "approval_expired:操作审批已过期。"

    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "failed"
    assert _node_map(db_session, run.id)["ship"].status == "skipped"


def test_cancel_waiting_run_late_decision_is_neutralized(db_session, settings, monkeypatch):
    """等待中取消：waiting 节点 cancelled；迟到的批准只落审批行，不再驱动节点。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    calls: list = []
    _install_fake_api(monkeypatch, calls)
    definition = _approval_definition(db_session, leader, project)
    run, _ = _start(db_session, leader, project, definition)
    run_workflow_run(run.id)
    db_session.expire_all()

    result = cancel_run(actor=leader, project_id=project.id, run_id=run.id)
    assert result["cancelled"] is True
    db_session.expire_all()
    node, approval = _waiting_approval(db_session, run.id)
    assert node.status == "cancelled" and run.status == "cancelled"

    decide_automation_approval(
        user=leader,
        approval_id=approval.id,
        decision_value="approve",
        password=INITIAL_PASSWORD,
        reason="取消后才拍",
    )
    db_session.expire_all()
    node, approval = _waiting_approval(db_session, run.id)
    assert approval.status == "approved"  # 决定如实落审批行
    assert node.status == "cancelled"  # 节点不再被审批驱动

    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "cancelled"


# ---------------------------------------------------------------------------
# T-W4：agent 节点（agents.start_run 同闸；沙箱适配器按 d4 harness 注入假件）
# ---------------------------------------------------------------------------


def test_agent_node_runs_full_start_run_gates(db_session, d4_settings, d4_app, monkeypatch):
    """agent 节点走 agents.start_run 全闸；输出携 agent_run_id 供下游占位符引用。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    agent = seed_agent(
        db_session,
        d4_settings,
        capability="project.read",
        allowed_tools=(),
        credential_ref=f"zcode-{uuid4().hex[:6]}",
    )
    prime_run(d4_app)  # 假沙箱 + 脚本事件 done(exit 0)
    calls: list = []
    _install_fake_api(monkeypatch, calls)
    definition = _make_definition(
        db_session,
        leader,
        project,
        _node("gather", output="subjects"),
        {
            "key": "classify",
            "type": "agent",
            "ref": agent.id,
            "depends_on": ["gather"],
            "output": "verdict",
        },
        _node("report", ["classify"], params={"v": "{{verdict.agent_run_id}}"}),
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    with d4_app.app_context():
        run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "succeeded"
    nodes = _node_map(db_session, run.id)
    assert nodes["classify"].status == "succeeded" and nodes["classify"].attempt == 1
    output = nodes["classify"].output_json
    assert output["agent_run_status"] == "completed" and output["agent_run_id"]
    agent_run = db_session.get(AgentRun, output["agent_run_id"])
    assert agent_run.idempotency_key == f"wfnode-{nodes['classify'].id}:1"
    assert agent_run.project_id == project.id
    assert agent_run.initiated_by_user_id == leader.id
    assert agent_run.capability_used == "project.read"
    assert nodes["report"].input_snapshot == {"v": agent_run.id}
    assert len(calls) == 2  # gather + report 都走 api_execute 同闸


def test_agent_node_gate_refusal_fails_node_without_retry(db_session, d4_settings, d4_app):
    """实时能力闸（每节点）：发起人不具备 agent 能力档 → 节点 failed，max_retries 不叠加。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    agent = seed_agent(
        db_session,
        d4_settings,
        capability="agent.system.tool",  # system_operator 档：project_lead 不具备
        allowed_tools=(),
        credential_ref=f"zcode-{uuid4().hex[:6]}",
    )
    prime_run(d4_app)  # 闸在分派前：假沙箱不应被触达
    definition = _make_definition(
        db_session,
        leader,
        project,
        {"key": "classify", "type": "agent", "ref": agent.id, "max_retries": 3},
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    with d4_app.app_context():
        run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "failed"
    node = _node_map(db_session, run.id)["classify"]
    assert node.status == "failed" and node.attempt == 1
    assert "无权" in (node.error or "")


def test_agent_node_run_failure_fails_node_without_workflow_retry(
    db_session, d4_settings, d4_app
):
    """沙箱 run 终态 failed → 节点 failed（agents 自带重试族，工作流不叠加自动重试）。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    agent = seed_agent(
        db_session,
        d4_settings,
        capability="project.read",
        allowed_tools=(),
        credential_ref=f"zcode-{uuid4().hex[:6]}",
    )
    prime_run(d4_app, events=ScriptedEvents([[{"type": "done", "exit_code": 1}]]))
    definition = _make_definition(
        db_session,
        leader,
        project,
        {"key": "classify", "type": "agent", "ref": agent.id, "max_retries": 3},
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    with d4_app.app_context():
        run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "failed"
    node = _node_map(db_session, run.id)["classify"]
    assert node.status == "failed" and node.attempt == 1
    assert (node.error or "").startswith("agent_run_failed:")
