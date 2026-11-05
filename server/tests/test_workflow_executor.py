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
import logging
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

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


def _seed_skill(
    db_session,
    leader,
    *,
    key: str,
    versions: list[str],
    scope: str = "public",
    required_capabilities: list[str] | None = None,
) -> SkillDefinition:
    skill = SkillDefinition(
        scope=scope,
        namespace_key="test" if scope == "public" else f"personal:{leader.id}",
        skill_key=key,
        name="测试技能",
        description="",
        status="published",
        current_version_number=len(versions),
        created_by_user_id=leader.id,
        owner_user_id=leader.id,
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
                required_capabilities=required_capabilities or [],
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


def test_routes_list_definitions_and_runs_permissions_and_bounds(
    db_session, settings, client
):
    """T-W6 桌面控制台补面：定义列表 + run 列表（can_view 闸 / 排序 / 截断诚实标记）。

    两条只读路由在 §5 设计七条之外（偏差已回写 backlog 与 workflow-dag-v1 §5 注记）：
    控制台要「run 列表/取消/恢复」就得能枚举；列表行不带 nodes（N+1 不可取）。
    """
    leader = _client_for(client, db_session, settings, role="project_lead")
    viewer = _client_for(client, db_session, settings, role="viewer")
    outsider = _client_for(client, db_session, settings, role="project_lead")
    project = _persist_project(db_session, leader.user, code=f"WE{uuid4().hex[:4]}")
    _add_viewer_member(db_session, project, viewer.user)

    draft = _make_definition(db_session, leader.user, project, _node("gather"))
    published = _make_definition(
        db_session, leader.user, project, _node("deliver"), publish=True
    )

    # 定义列表：can_view 可读（viewer 含草稿）、局外人 403、跨项目隔离
    list_url = f"/api/v1/projects/{project.id}/workflows"
    assert (
        outsider.get(list_url).status_code == 403
    )  # 非成员 → load_project forbidden（404 仅在项目不存在时）
    viewer_list = viewer.get(list_url)
    assert viewer_list.status_code == 200, viewer_list.get_json()
    items = viewer_list.get_json()["data"]["items"]
    assert [row["status"] for row in items] == ["published", "draft"]  # 新者在前
    assert {row["id"] for row in items} == {draft.id, published.id}

    # run 列表：行不带 nodes；?limit= 截断诚实；非法 limit 400；权限闸同定义列表
    run_a, _ = _start(db_session, leader.user, project, published)
    run_b, _ = _start(db_session, leader.user, project, published)
    runs_url = f"/api/v1/projects/{project.id}/workflow-runs"
    assert outsider.get(runs_url).status_code == 403
    assert viewer.get(f"{runs_url}?limit=0").status_code == 400
    assert viewer.get(f"{runs_url}?limit=nope").status_code == 400
    assert viewer.get(f"{runs_url}?limit=201").status_code == 400
    capped = viewer.get(f"{runs_url}?limit=1")
    assert capped.status_code == 200, capped.get_json()
    capped_payload = capped.get_json()["data"]
    assert capped_payload["truncated"] is True and len(capped_payload["items"]) == 1
    assert "nodes" not in capped_payload["items"][0]
    full = viewer.get(runs_url)
    full_payload = full.get_json()["data"]
    assert full_payload["truncated"] is False
    assert {row["id"] for row in full_payload["items"]} == {run_a.id, run_b.id}
    assert {row["definition_id"] for row in full_payload["items"]} == {published.id}
    assert full_payload["items"][0]["status"] in (
        "queued",
        "running",
    )  # 无执行器消费（测试环境）保持初值


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


def test_skill_usage_count_failure_does_not_fail_node(db_session, settings, monkeypatch, caplog):
    """CR-013 计数隔离：计数微事务故障不得升级为消费侧失败。

    skill 节点 AI 调用已成功后 record_skill_usage 抛 DB 异常，只记 warning——
    若裸露冒泡会被 _execute_node 兜底 catch 为 dispatch_crashed(retryable=True)
    重投：同一逻辑节点双份 AI 成本 + 「消费成功」误标 failed（T-S2 对称语义；
    chat 面 ai_tool_loop 对工具异常同型有守卫，唯 workflow 面曾裸露）。
    """
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    _seed_skill(db_session, leader, key="flaky-count", versions=["指令"])
    calls: list = []
    _install_fake_api(monkeypatch, calls)
    ai_calls: list = []
    _install_fake_ai(monkeypatch, ai_calls)

    from fde_api.control import extensions_service

    def _count_blip(**_kwargs):
        raise OSError("counting micro-transaction blip")

    monkeypatch.setattr(extensions_service, "record_skill_usage", _count_blip)
    definition = _make_definition(
        db_session,
        leader,
        project,
        {"key": "draft", "type": "skill", "ref": "flaky-count@1", "output": "hint"},
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    # 既有测试基建特性：alembic env.py 每次迁移都 fileConfig（默认
    # disable_existing_loggers=True），导入期创建的模块级 logger 会被全量禁用
    # ——与 test_storage_contract 对 oss2 sdk_logger 的解禁先例同型。
    logging.getLogger("fde_api.workflows.executor").disabled = False
    with caplog.at_level(logging.WARNING, logger="fde_api.workflows.executor"):
        run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "succeeded"
    nodes = _node_map(db_session, run.id)
    assert nodes["draft"].status == "succeeded"
    assert nodes["draft"].output_json == {"text": "润色结果"}
    assert len(ai_calls) == 1  # 无重投——没有第二份 AI 成本
    assert any(
        "workflow skill usage count failed" in record.message for record in caplog.records
    )


def test_skill_node_denies_initiator_below_required_capabilities(db_session, settings, monkeypatch):
    """CR-005 消费面档位闸：发起人 AI 档位低于技能 required_capabilities 时拒绝。

    授权档位独立于角色（admin 可随时下调）：project_lead 显式降为 assistant_read
    后，required_capabilities 含 project_operator 档能力的技能在工作流中不得消费
    （agent-policy-v1 §T-S1 消费面契约，与 mcp_gateway._skills 同口径）。
    """
    from fde_api.control.models import UserAIAccessGrant

    leader = make_user(db_session, "project_lead")
    db_session.add(
        UserAIAccessGrant(
            user_id=leader.id,
            access_level="assistant_read",
            granted_by_user_id=leader.id,
        )
    )
    db_session.commit()
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    skill = _seed_skill(
        db_session,
        leader,
        key="tiered",
        versions=["指令"],
        required_capabilities=["agent.plan.generate"],  # project_operator 档
    )
    ai_calls: list = []
    _install_fake_ai(monkeypatch, ai_calls)
    definition = _make_definition(
        db_session,
        leader,
        project,
        {"key": "draft", "type": "skill", "ref": "tiered@1", "output": "hint"},
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "failed"
    nodes = _node_map(db_session, run.id)
    assert nodes["draft"].status == "failed"
    assert nodes["draft"].error is not None and "ai_access_insufficient" in nodes["draft"].error
    assert ai_calls == []  # 闸在消费前，AI 从未被调用
    usage = db_session.scalars(
        select(OperationEvent).where(
            OperationEvent.target_type == "skill_definition",
            OperationEvent.target_id == skill.id,
            OperationEvent.event_type == "skill_used_workflow",
        )
    ).all()
    assert usage == []  # 分派失败不计消费（T-S2 语义）


def test_skill_node_denies_other_users_personal_skill(db_session, settings, monkeypatch):
    """CR-005 消费面所有权闸：个人技能仅所有者可在工作流中消费。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    _seed_skill(db_session, leader, key="private-hint", versions=["私有指令"], scope="personal")
    ai_calls: list = []
    _install_fake_ai(monkeypatch, ai_calls)
    definition = _make_definition(
        db_session,
        leader,
        project,
        {"key": "draft", "type": "skill", "ref": "private-hint@1", "output": "hint"},
        publish=True,
    )
    admin = make_user(db_session, "admin")
    run, _ = _start(db_session, admin, project, definition)

    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "failed"
    nodes = _node_map(db_session, run.id)
    assert nodes["draft"].status == "failed"
    assert nodes["draft"].error is not None and "skill_ref_forbidden" in nodes["draft"].error
    assert ai_calls == []  # 所有者的私有指令不进任何 AI 调用


def test_skill_node_allows_owner_personal_skill_within_tier(db_session, settings, monkeypatch):
    """CR-005 对照：所有者本人消费个人技能且档位覆盖 required_capabilities → 正常执行。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    _seed_skill(
        db_session,
        leader,
        key="own-hint",
        versions=["私有指令"],
        scope="personal",
        required_capabilities=["agent.code.write"],  # project_manager 档 = leader 角色默认
    )
    ai_calls: list = []
    _install_fake_ai(monkeypatch, ai_calls)
    definition = _make_definition(
        db_session,
        leader,
        project,
        {"key": "draft", "type": "skill", "ref": "own-hint@1", "output": "hint"},
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


def test_capability_revocation_mid_run_fails_subsequent_write_call_node(
    db_session, settings, monkeypatch
):
    """§16 用例族 W-9（权限撤销即时生效，P3 四项状态轮核对表补钉）：run 进行
    中撤销发起人 AI 档位 → 后续写类 call 节点**分派时**实时重判
    （_dispatch_call 每节点重算 effective_ai_access，非 start 时一次定终身），
    命中 execute_api 写面 workbench.write 硬闸 → 403 forbidden 诚实失败
    （403 非暂态不重试）→ run failed（FV-F1 断链不静默）。已成功节点产物
    不受影响；MCP 面撤销回归见 test_ai_server_chat_mcp（180/211）。"""
    from fde_api.control import api_actions
    from fde_api.control.models import UserAIAccessGrant

    leader = make_user(db_session, "project_lead")  # 角色默认 project_manager：含 workbench.write
    project = _persist_project(db_session, leader, code=f"RV{uuid4().hex[:4]}")
    calls: list = []
    real_execute_api = api_actions.execute_api

    def revoke_on_first_dispatch(**kwargs):
        calls.append(kwargs["operation"])
        if len(calls) == 1:
            # 节点 1 分派在途：此刻撤销发起人档位（独立会话提交，下一节点
            # 分派的 effective_ai_access 开新事务实时读到 disabled）。
            with Session(db_session.bind) as session:
                session.add(
                    UserAIAccessGrant(
                        user_id=leader.id,
                        access_level="disabled",
                        granted_by_user_id=leader.id,
                        reason="W-9：run 进行中撤销",
                    )
                )
                session.commit()
            return {"http_status": 200, "result": {"items": [1, 2, 3]}}
        return real_execute_api(**kwargs)

    monkeypatch.setattr(api_actions, "execute_api", revoke_on_first_dispatch)
    definition = _make_definition(
        db_session,
        leader,
        project,
        _node("peek", ref=READ_REF),
        _node("apply", ref=WRITE_REF, deps=("peek",)),
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "failed"
    nodes = _node_map(db_session, run.id)
    assert nodes["peek"].status == "succeeded" and nodes["peek"].attempt == 1
    apply_node = nodes["apply"]
    assert apply_node.status == "failed" and apply_node.attempt == 1  # 403 非暂态：零重试
    # 落表格式 f"{code}:{message}"（_settle_node_failure）；闸=execute_api 写面 workbench.write
    assert apply_node.error == "forbidden:本次 AI 执行未获写入授权。"
    assert calls == [READ_REF, WRITE_REF]  # 撤销发生在两节点之间，写节点真实走到闸


# ---------------------------------------------------------------------------
# 取消（§6 用例 8）
# ---------------------------------------------------------------------------


def test_cancelled_node_records_inflight_dispatch_result(db_session, settings):
    """CR-022 补呈现通道：节点在派发后被取消，在途外呼/AI 调用返回的结果
    不得被终态守卫静默丢弃——终态不复活（仍 cancelled），但「确实执行了」
    落到 output_json（标记+产物+action_id 指针）+ node.error 稳定标记
    （桌面 WorkflowConsole 错误列可见，零桌面改动即有呈现）。"""
    from fde_api.workflows import executor as executor_module

    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    definition = _make_definition(
        db_session,
        leader,
        project,
        _node("gather", output="subjects"),
        _node("draft", ["gather"]),
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    cancelled = cancel_run(actor=leader, project_id=project.id, run_id=run.id)
    assert cancelled["cancelled"] is True

    # 在途 call 节点返回成功（写类操作带 action_id → 可回 api_actions 反查）
    executor_module._settle_node_success(
        run.id,
        "draft",
        {"action_id": "act-cr22-1", "http_status": 200, "result": {"ok": True}},
    )
    # 在途 AI 调用（skill 形态）返回失败
    executor_module._settle_node_failure(
        run.id,
        "gather",
        1,
        {"type": "skill", "ref": "builtin.summary@1"},
        executor_module._NodeFailure("ai_timeout", "上游超时。", retryable=False),
    )

    db_session.expire_all()
    by_key = _node_map(db_session, run.id)
    draft = by_key["draft"]
    assert draft.status == "cancelled"  # 终态不复活
    assert draft.output_json["cancelled_after_dispatch"] is True
    assert draft.output_json["dispatch_outcome"] == "succeeded"
    assert draft.output_json["action_id"] == "act-cr22-1"
    assert draft.output_json["dispatch_result"]["result"] == {"ok": True}
    assert draft.error == "cancelled_after_dispatch"

    gather = by_key["gather"]
    assert gather.status == "cancelled"
    assert gather.output_json["dispatch_outcome"] == "failed"
    assert "ai_timeout" in gather.output_json["dispatch_result"]["error"]
    assert gather.error == "cancelled_after_dispatch"

    # 序列化面可见（API 消费方零改动即得诚实呈现）
    serialized = {n["node_key"]: n for n in cancelled["run"]["nodes"]}
    assert serialized["draft"]["output_json"] is None  # 取消当时尚无在途结果
    detail = executor_module.serialize_run(
        db_session.get(WorkflowRun, run.id), list(_node_map(db_session, run.id).values())
    )
    detail_by_key = {n["node_key"]: n for n in detail["nodes"]}
    assert detail_by_key["draft"]["output_json"]["cancelled_after_dispatch"] is True


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


# ---------------------------------------------------------------------------
# goal-c c5：P1 三修回归（CR-014 stale 审批键 / CR-019 agent 恢复代际 /
# CR-020 写类节点结果未确认不折叠 succeeded）
# ---------------------------------------------------------------------------


def test_human_approval_rejected_resume_creates_fresh_pending(
    db_session, settings, monkeypatch
):
    """goal-c CR-014：resume 是全新分派——旧幂等键所指的审批已 rejected（终态）时
    不得复用（否则节点重新挂到终态审批，run 永久卡 waiting_approval，唯一出口
    只剩 cancel）：清键后按节点行查 pending / 或新建；随后人工拍板收敛 succeeded。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    calls: list = []
    _install_fake_api(monkeypatch, calls)
    definition = _approval_definition(db_session, leader, project)
    run, _ = _start(db_session, leader, project, definition)
    run_workflow_run(run.id)
    db_session.expire_all()
    node, approval = _waiting_approval(db_session, run.id)
    key_before = node.idempotency_key
    assert key_before == approval.id

    decide_automation_approval(
        user=leader,
        approval_id=approval.id,
        decision_value="reject",
        password="",
        reason="第一轮不同意",
    )
    run_workflow_run(run.id)  # 断链：approve failed + ship skipped → run failed
    db_session.expire_all()
    stale_key = _node_map(db_session, run.id)["approve"].idempotency_key
    assert stale_key == key_before  # 终态审批键留在节点上——resume 必须能挣脱它

    resume_run(actor=leader, project_id=project.id, run_id=run.id)
    run_workflow_run(run.id)
    db_session.expire_all()
    new_node = _node_map(db_session, run.id)["approve"]
    new_approval = db_session.scalar(
        select(AutomationApproval).where(
            AutomationApproval.workflow_node_run_id == new_node.id,
            AutomationApproval.status == "pending",
        )
    )
    assert new_approval is not None and new_approval.id != key_before
    assert new_node.status == "waiting" and new_node.idempotency_key == new_approval.id

    decide_automation_approval(
        user=leader,
        approval_id=new_approval.id,
        decision_value="approve",
        password=INITIAL_PASSWORD,
        reason="改主意了",
    )
    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "succeeded"
    nodes = _node_map(db_session, run.id)
    assert nodes["approve"].status == "succeeded"
    assert nodes["ship"].status == "succeeded" and nodes["ship"].input_snapshot == {"note": "approved"}


def test_agent_node_resume_preserves_attempt_new_generation(
    db_session, d4_settings, d4_app
):
    """goal-c CR-019：agent 节点幂等键 = wfnode-{行id}:{attempt}，agents V8 对失败
    终态拒同键重跑——resume 必须保留 attempt（_begin_node +1 开新代际），归零会
    每次撞回 `:1` 的 failed 终态 → 确定性 409，agent 节点永远救不活。
    本例：first run 失败终态（exit 1）→ resume 代际 2 成功收敛。"""
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
        db_session, leader, project, {"key": "classify", "type": "agent", "ref": agent.id}, publish=True
    )
    run, _ = _start(db_session, leader, project, definition)

    with d4_app.app_context():
        run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "failed"
    node = _node_map(db_session, run.id)["classify"]
    assert node.status == "failed" and node.attempt == 1

    prime_run(d4_app)  # 事件工厂每 run 新克隆：本轮脚本=done(exit 0)
    resume_run(actor=leader, project_id=project.id, run_id=run.id)
    with d4_app.app_context():
        run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "succeeded"
    node = _node_map(db_session, run.id)["classify"]
    assert node.status == "succeeded" and node.attempt == 2  # 新一代际，不归零
    assert node.error is None
    agent_run = db_session.get(AgentRun, node.output_json["agent_run_id"])
    assert agent_run.idempotency_key == f"wfnode-{node.id}:2"  # 新代际键≠:1 失败终态


def test_write_call_node_uncertain_and_cancelled_fail_not_succeeded(
    db_session, settings, monkeypatch
):
    """goal-c CR-020：写类节点结果未确认（started 无 finished→uncertain；被
    取消→cancelled）不得折叠为 succeeded——FV-F1「断链不静默 done」红线。
    action_not_confirmed 非可重试（api_actions 同键去重兜底不二次外呼），故
    max_retries 不叠加自动重试：uncertain 当轮 1 次外呼即断链；cancelled 分支
    经 resume 重派才摸到（call 节点 resume attempt 归零→_begin_node +1）。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WE{uuid4().hex[:4]}")
    calls: list = []

    def fake_uncertain_then_cancelled(**kwargs):
        calls.append(kwargs["operation"])
        if len(calls) == 1:
            return {"http_status": 200, "result": {}, "status": "uncertain", "action_id": "act-1"}
        return {"http_status": 200, "result": {}, "status": "cancelled", "action_id": "act-1"}

    monkeypatch.setattr("fde_api.control.api_actions.execute_api", fake_uncertain_then_cancelled)
    _zero_backoff(monkeypatch)
    definition = _make_definition(
        db_session, leader, project, _node("create", ref=WRITE_REF, max_retries=2), publish=True
    )
    run, _ = _start(db_session, leader, project, definition)

    # 第一轮：uncertain（started 无 finished）→ 节点 failed，**不是** succeeded；
    # 非可重试 ⇒ max_retries=2 不叠加，当轮仅 1 次外呼。
    run_workflow_run(run.id)
    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "failed"
    node = _node_map(db_session, run.id)["create"]
    assert node.status == "failed" and node.attempt == 1
    assert (node.error or "").startswith("action_not_confirmed:")
    assert "uncertain" in node.error
    assert len(calls) == 1

    # 第二轮：resume 重派 → call 节点 attempt 归零重开，fake 走到 cancelled 分支
    # → 仍 failed（不是 succeeded），坐实 cancelled 也不折叠。
    resume_run(actor=leader, project_id=project.id, run_id=run.id)
    run_workflow_run(run.id)
    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "failed"
    node = _node_map(db_session, run.id)["create"]
    assert node.status == "failed"
    assert (node.error or "").startswith("action_not_confirmed:")
    assert "cancelled" in node.error
    assert len(calls) == 2


def test_resume_increments_hops_across_generations_without_reset(
    db_session, settings, monkeypatch
):
    """B#1：拍板重投是「重投代际」边——hops 逐代累加继承不清零；修好后正常
    续跑且 hops 冻结在已达代际数（执行不再累加）。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"HP{uuid4().hex[:4]}")
    _seed_skill(db_session, leader, key="flaky", versions=["指令"])
    _install_fake_api(monkeypatch, [])
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
    first = db_session.get(WorkflowRun, run.id)
    assert first.status == "failed"
    assert first.hops == 0

    # 第一代拍板重投：hops 0 → 1
    resume_run(actor=leader, project_id=project.id, run_id=run.id)
    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).hops == 1
    run_workflow_run(run.id)  # AI 仍坏 → 再失败，hops 不回退
    db_session.expire_all()
    again = db_session.get(WorkflowRun, run.id)
    assert again.status == "failed"
    assert again.hops == 1

    # 第二代重投：hops 1 → 2（继承不清零）
    resume_run(actor=leader, project_id=project.id, run_id=run.id)
    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).hops == 2

    # 修好后正常续跑成功；hops 冻结在已达代际数
    monkeypatch.setattr(
        "fde_api.control.ai_server_client.execute_ai_prompt", lambda **kw: "好了"
    )
    run_workflow_run(run.id)
    db_session.expire_all()
    done = db_session.get(WorkflowRun, run.id)
    assert done.status == "succeeded"
    assert done.hops == 2


def test_hops_cap_refuses_resume_and_entry_fails_inflight(db_session, settings):
    """B#1：代际上限——resume 在重投口 409 拒绝（零变更）；入口 belt 把在途
    超限行 honest failed（不再分派任何节点）。"""
    from fde_api.workflows.executor import MAX_RUN_HOPS, WorkflowRunError

    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"HP{uuid4().hex[:4]}")
    _seed_skill(db_session, leader, key="once", versions=["指令"])
    definition = _make_definition(
        db_session,
        leader,
        project,
        _node("gather", output="subjects"),
        {"key": "draft", "type": "skill", "ref": "once@1", "depends_on": ["gather"]},
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    row = db_session.get(WorkflowRun, run.id)
    row.status = "failed"
    row.hops = 8  # 与 MAX_RUN_HOPS 合同钉死（字面量播种，变异敏感）
    db_session.commit()

    with pytest.raises(WorkflowRunError) as exc:
        resume_run(actor=leader, project_id=project.id, run_id=run.id)
    assert exc.value.code == "hops_exceeded"
    assert exc.value.status == 409
    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).hops == MAX_RUN_HOPS  # 零变更

    # 入口 belt：在途超限行直接 failed（error 前缀留痕），不进入节点循环
    row = db_session.get(WorkflowRun, run.id)
    row.status = "running"
    row.hops = 9  # 超合同上限一步（字面量播种，变异敏感）
    db_session.commit()
    run_workflow_run(run.id)
    db_session.expire_all()
    failed = db_session.get(WorkflowRun, run.id)
    assert failed.status == "failed"
    assert (failed.error or "").startswith("hops_exceeded")
