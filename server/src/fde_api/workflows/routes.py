"""Workflow 路由（V3 T-W3/T-W5，设计 workflow-dag-v1 §5）。

§5 七条全部开放（T-W3 五条：定义/发布/发起/详情/平台模板；T-W5 两条：cancel/resume
运行生命周期）。平台模板定义（project_id NULL）的创建走内部/admin 通道，只开放只读列表。
V3 T-W6 桌面控制台补两条只读列表挂件（项目定义列表 / run 列表，均 can_view）——
§5 设计面不变，见 backlog T-W6 实施记录偏差注记。
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.extensions import db
from fde_api.workflows import definition_service, executor
from fde_api.workflows.executor import WorkflowRunError

workflows_blueprint = Blueprint("workflows", __name__)


@workflows_blueprint.errorhandler(definition_service.WorkflowDefinitionError)
def definition_error(error):
    return error_response(error.code, error.message, error.status, error.detail or None)


@workflows_blueprint.errorhandler(WorkflowRunError)
def run_error(error):
    return error_response(error.code, error.message, error.status, error.detail or None)


def _payload() -> dict:
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise WorkflowRunError("invalid_request", "请求内容必须为 JSON 对象。", 400)
    return value


@workflows_blueprint.post("/api/v1/projects/<project_id>/workflows")
@require_auth
def create_workflow_route(project_id):
    """建工作流定义草稿（can_manage）：环/未知引用/占位符违规 → 422 dag_invalid 带明细。"""
    payload = _payload()
    with db.session() as session, session.begin():
        executor.load_project(session, g.current_user, project_id, manage=True)
        definition = definition_service.create_definition(
            session,
            actor=g.current_user,
            project_id=project_id,
            name=payload.get("name"),
            dag=payload.get("dag"),
            description=payload.get("description"),
        )
        data = {"definition": definition_service.serialize_definition(definition)}
    return jsonify({"data": data, "error": None}), 201


@workflows_blueprint.post("/api/v1/projects/<project_id>/workflows/<definition_id>/publish")
@require_auth
def publish_workflow_route(project_id, definition_id):
    """发布定义（admin）：锁版——dag_json 快照成不可变版本行。"""
    if g.current_user.role != "admin":
        raise WorkflowRunError("forbidden", "只有管理员可以发布工作流定义。", 403)
    with db.session() as session, session.begin():
        _project, definition = executor.load_definition(
            session, g.current_user, project_id, definition_id, manage=True
        )
        version = definition_service.publish_definition(
            session, actor=g.current_user, definition=definition
        )
        data = {
            "definition": definition_service.serialize_definition(definition),
            "version": version.version,
            "content_sha256": version.content_sha256,
        }
    return jsonify({"data": data, "error": None})


@workflows_blueprint.post("/api/v1/projects/<project_id>/workflows/<definition_id>/runs")
@require_auth
def start_workflow_run_route(project_id, definition_id):
    """发起运行（can_manage）：{context?, idempotency_key?}；同幂等键返回既有 run。"""
    payload = _payload()
    if "context" in payload and payload["context"] is not None and not isinstance(
        payload["context"], dict
    ):
        raise WorkflowRunError("invalid_request", "context 必须是对象。", 400)
    if "idempotency_key" in payload and payload["idempotency_key"] is not None and not isinstance(
        payload["idempotency_key"], str
    ):
        raise WorkflowRunError("invalid_request", "idempotency_key 必须是字符串。", 400)
    with db.session() as session, session.begin():
        run, created = executor.start_run(
            session,
            actor=g.current_user,
            project_id=project_id,
            definition_id=definition_id,
            context=payload.get("context"),
            idempotency_key=payload.get("idempotency_key"),
        )
        data = {
            "run": executor.serialize_run(run, executor.ordered_nodes(session, run)),
            "created": created,
        }
    return jsonify({"data": data, "error": None}), (201 if created else 200)


@workflows_blueprint.get("/api/v1/projects/<project_id>/workflows")
@require_auth
def list_project_workflows_route(project_id):
    """项目内定义列表（can_view，新者在前）——V3 T-W6 桌面控制台补面（§5 七条之外的只读挂件）。"""
    with db.session() as session:
        project = executor.load_project(session, g.current_user, project_id, manage=False)
        data = {"items": definition_service.list_definitions(session, project_id=project.id)}
    return jsonify({"data": data, "error": None})


@workflows_blueprint.get("/api/v1/projects/<project_id>/workflow-runs")
@require_auth
def list_workflow_runs_route(project_id):
    """项目内 run 列表（can_view，新者在前，有界）——T-W6 补面；列表行不带 nodes。"""
    raw = request.args.get("limit")
    if raw is None:
        limit = executor.RUN_LIST_LIMIT_DEFAULT
    else:
        try:
            limit = int(raw)
        except ValueError:
            raise WorkflowRunError("invalid_request", "limit 必须是整数。", 400)
        if not 1 <= limit <= executor.RUN_LIST_LIMIT_MAX:
            raise WorkflowRunError(
                "invalid_request", f"limit 须在 1..{executor.RUN_LIST_LIMIT_MAX}。", 400
            )
    return jsonify(
        {
            "data": executor.list_project_runs(actor=g.current_user, project_id=project_id, limit=limit),
            "error": None,
        }
    )


@workflows_blueprint.get("/api/v1/projects/<project_id>/workflow-runs/<run_id>")
@require_auth
def get_workflow_run_route(project_id, run_id):
    """run + 节点态树（can_view）。"""
    return jsonify({"data": executor.get_run_detail(actor=g.current_user, project_id=project_id, run_id=run_id), "error": None})


@workflows_blueprint.post("/api/v1/projects/<project_id>/workflow-runs/<run_id>/cancel")
@require_auth
def cancel_workflow_run_route(project_id, run_id):
    """取消运行（can_manage，幂等）：未执行节点 cancelled，已执行外呼不回收。"""
    return jsonify({"data": executor.cancel_run(actor=g.current_user, project_id=project_id, run_id=run_id), "error": None})


@workflows_blueprint.post("/api/v1/projects/<project_id>/workflow-runs/<run_id>/resume")
@require_auth
def resume_workflow_run_route(project_id, run_id):
    """恢复失败运行（can_manage）：failed/skipped 节点放回 pending，重投 workflow.run。"""
    return jsonify({"data": executor.resume_run(actor=g.current_user, project_id=project_id, run_id=run_id), "error": None})


@workflows_blueprint.get("/api/v1/workflows")
@require_auth
def list_platform_workflows_route():
    """平台模板工作流（admin，project_id NULL）。"""
    return jsonify({"data": {"items": executor.list_platform_definitions(actor=g.current_user)}, "error": None})
