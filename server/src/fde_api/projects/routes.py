from __future__ import annotations

from typing import Any

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth, require_minimum_role
from fde_api.errors import error_response
from fde_api.projects.service import (
    PROJECT_STATUSES,
    ProjectServiceError,
    add_project_member,
    append_project_module,
    assign_project_default_tasks,
    cancel_project_module,
    create_project,
    get_project,
    list_project_members,
    list_projects,
    remove_project_member,
    update_project_member,
    update_project,
)
from fde_api.projects.gantt import get_project_gantt
from fde_api.projects.gate_service import (
    GateServiceError,
    decide_gate,
    list_project_gates,
    submit_gate_evidence,
)
from fde_api.projects.quote_service import (
    QuoteServiceError,
    calibrate_quote,
    create_quote,
    finalize_quote,
    list_quotes,
    render_quote_draft,
    update_quote_claim,
)
from fde_api.projects.payment_service import (
    PaymentServiceError,
    generate_payment_plan,
    payment_board,
    update_payment,
)
from fde_api.projects.contract_service import (
    ContractServiceError,
    list_contracts,
    record_contract,
)
from fde_api.projects.task_service import (
    TASK_STATUSES,
    TASK_UPDATE_FIELDS,
    batch_assign_project_tasks,
    create_project_task,
    get_project_task,
    list_project_tasks,
    update_project_task,
)


projects_blueprint = Blueprint("projects", __name__, url_prefix="/api/v1/projects")

CREATE_FIELDS = frozenset(
    {
        "name",
        "enterprise_code",
        "openfde_engagement",
        "fdeops_workspace",
        "background",
        "notes",
        # P2-4（派单设计 §8.5）：成交渠道随立项入口显式声明
        "business_line",
        "project_code",
        "planned_start_date",
        "planned_end_date",
        "template_version_id",
        "leader_user_id",
        "module_keys",
        "creation_source",
        "project_snapshot",
    }
)
REQUIRED_CREATE_FIELDS = frozenset(
    {
        "name",
        "enterprise_code",
        "planned_start_date",
        "leader_user_id",
        "module_keys",
    }
)
UPDATE_FIELDS = frozenset(
    {
        "version",
        "name",
        "enterprise_code",
        "openfde_engagement",
        "fdeops_workspace",
        "sop_phase",
        "background",
        "notes",
        "project_code",
        "planned_start_date",
        "planned_end_date",
        "leader_user_id",
        "status",
        "t6_review_disabled",
    }
)
MEMBER_CREATE_FIELDS = frozenset({"user_id", "role", "version"})
MEMBER_UPDATE_FIELDS = frozenset({"role", "version"})
VERSION_ONLY_FIELDS = frozenset({"version"})
BATCH_ASSIGNMENT_MODES = frozenset({"assignee", "collaborator"})


@projects_blueprint.get("")
@require_auth
def list_projects_route():
    query = _list_query()
    if query is None:
        return _invalid_request()
    projects, total = list_projects(actor=g.current_user, query=query)
    return jsonify(
        {
            "data": {
                "items": projects,
                "page": query["page"],
                "page_size": query["page_size"],
                "total": total,
            },
            "error": None,
        }
    )


@projects_blueprint.post("")
@require_minimum_role("project_lead")
def create_project_route():
    payload = _json_payload()
    if (
        payload is None
        or set(payload) - CREATE_FIELDS
        or not REQUIRED_CREATE_FIELDS <= set(payload)
    ):
        return _invalid_request()
    try:
        project = create_project(actor=g.current_user, input=payload)
        return jsonify({"data": project, "error": None}), 201
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.get("/<project_id>")
@require_auth
def get_project_route(project_id: str):
    try:
        project = get_project(actor=g.current_user, project_id=project_id)
        return jsonify({"data": project, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.patch("/<project_id>")
@require_minimum_role("project_lead")
def update_project_route(project_id: str):
    payload = _json_payload()
    if (
        not payload
        or set(payload) - UPDATE_FIELDS
        or type(payload.get("version")) is not int
        or payload["version"] < 1
        or not set(payload) - {"version"}
        or any(
            payload[field] is None
            for field in set(payload) - {"version", "planned_end_date"}
        )
    ):
        return _invalid_request()
    try:
        project = update_project(
            actor=g.current_user,
            project_id=project_id,
            expected_version=payload["version"],
            changes={key: value for key, value in payload.items() if key != "version"},
        )
        return jsonify({"data": project, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.get("/<project_id>/gates")
@require_auth
def list_project_gates_route(project_id: str):
    """P3 门禁引擎：项目 9 门禁状态 + 证据清单 + 最近门禁事件（全程可追溯）。"""
    try:
        data = list_project_gates(actor=g.current_user, project_id=project_id)
        return jsonify({"data": data, "error": None})
    except GateServiceError as error:
        return _gate_error(error)


@projects_blueprint.post("/<project_id>/gates/<gate_key>/evidence")
@require_auth
def submit_gate_evidence_route(project_id: str, gate_key: str):
    """提交门禁证据（A4 出处指针）：pending/failed → evidence，清单项 claim_status=claimed。"""
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        data = submit_gate_evidence(
            actor=g.current_user,
            project_id=project_id,
            gate_key=gate_key,
            payload=payload,
        )
        return jsonify({"data": data, "error": None})
    except GateServiceError as error:
        return _gate_error(error)


@projects_blueprint.post("/<project_id>/gates/<gate_key>/decision")
@require_auth
def decide_gate_route(project_id: str, gate_key: str):
    """人工核验（evidence → passed/conditional_pass/failed；G8 必带三态 decision）。"""
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        data = decide_gate(
            actor=g.current_user,
            project_id=project_id,
            gate_key=gate_key,
            payload=payload,
        )
        return jsonify({"data": data, "error": None})
    except GateServiceError as error:
        return _gate_error(error)


# ---- P4 报价/收款/合同（设计 §6）----


@projects_blueprint.get("/<project_id>/quotes")
@require_auth
def list_quotes_route(project_id: str):
    """报价台账列表 + 最近报价事件。"""
    try:
        data = list_quotes(actor=g.current_user, project_id=project_id)
        return jsonify({"data": data, "error": None})
    except QuoteServiceError as error:
        return _quote_error(error)


@projects_blueprint.post("/<project_id>/quotes")
@require_auth
def create_quote_route(project_id: str):
    """建报价（报价卡 v1.1 系数输入 → 公式价 → 锚点三分支）；preset=first_order_defaults
    走首单默认参数并强制三条硬约束。"""
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        data = create_quote(
            actor=g.current_user, project_id=project_id, payload=payload
        )
        return jsonify({"data": data, "error": None}), 201
    except QuoteServiceError as error:
        return _quote_error(error)


@projects_blueprint.post("/<project_id>/quotes/<quote_key>/claims")
@require_auth
def update_quote_claim_route(project_id: str, quote_key: str):
    """单字段 claim 前进（estimated→claimed→measured→accepted，只进不退）。"""
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        data = update_quote_claim(
            actor=g.current_user,
            project_id=project_id,
            quote_key=quote_key,
            payload=payload,
        )
        return jsonify({"data": data, "error": None})
    except QuoteServiceError as error:
        return _quote_error(error)


@projects_blueprint.post("/<project_id>/quotes/<quote_key>/calibrate")
@require_auth
def calibrate_quote_route(project_id: str, quote_key: str):
    """回校缓冲 ×2.0（首单结项 checklist 固定一步）：actual_hours + deviation_reason。"""
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        data = calibrate_quote(
            actor=g.current_user,
            project_id=project_id,
            quote_key=quote_key,
            payload=payload,
        )
        return jsonify({"data": data, "error": None})
    except QuoteServiceError as error:
        return _quote_error(error)


@projects_blueprint.post("/<project_id>/quotes/<quote_key>/finalize")
@require_auth
def finalize_quote_route(project_id: str, quote_key: str):
    """成交回填：最终价人拍板；低于成本×1.25 必须门票单；算让利额度；C 层三道校验。"""
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        data = finalize_quote(
            actor=g.current_user,
            project_id=project_id,
            quote_key=quote_key,
            payload=payload,
        )
        return jsonify({"data": data, "error": None})
    except QuoteServiceError as error:
        return _quote_error(error)


@projects_blueprint.get("/<project_id>/quotes/<quote_key>/draft")
@require_auth
def quote_draft_route(project_id: str, quote_key: str):
    """对外报价单 HTML 草稿（三档格式，无内部系数；草稿不自动发客户）。"""
    try:
        data = render_quote_draft(
            actor=g.current_user, project_id=project_id, quote_key=quote_key
        )
        return jsonify({"data": data, "error": None})
    except QuoteServiceError as error:
        return _quote_error(error)


@projects_blueprint.get("/<project_id>/payments")
@require_auth
def payment_board_route(project_id: str):
    """收款看板：里程碑行 + 现算状态/催款级（D+7/15/30/60）+ 应收/已收/逾期汇总。"""
    try:
        data = payment_board(actor=g.current_user, project_id=project_id)
        return jsonify({"data": data, "error": None})
    except PaymentServiceError as error:
        return _payment_error(error)


@projects_blueprint.post("/<project_id>/payments/plan")
@require_auth
def payment_plan_route(project_id: str):
    """按 SOW 生成收款计划（B 50/50、C 40/40/20、A 预付、D 月付；溯源映射表 v1.3）。"""
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        data = generate_payment_plan(
            actor=g.current_user, project_id=project_id, payload=payload
        )
        return jsonify({"data": data, "error": None}), 201
    except PaymentServiceError as error:
        return _payment_error(error)


@projects_blueprint.post("/<project_id>/payments/<milestone_key>")
@require_auth
def update_payment_route(project_id: str, milestone_key: str):
    """收款回填（金额/到账日/发票号）与到期日设置（催款级读时现算）。"""
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        data = update_payment(
            actor=g.current_user,
            project_id=project_id,
            milestone_key=milestone_key,
            payload=payload,
        )
        return jsonify({"data": data, "error": None})
    except PaymentServiceError as error:
        return _payment_error(error)


@projects_blueprint.get("/<project_id>/contracts")
@require_auth
def list_contracts_route(project_id: str):
    """合同台账（四类 SOW 补位视图；只存指针，PDF 在 fdeops）。"""
    try:
        data = list_contracts(actor=g.current_user, project_id=project_id)
        return jsonify({"data": data, "error": None})
    except ContractServiceError as error:
        return _contract_error(error)


@projects_blueprint.post("/<project_id>/contracts")
@require_auth
def record_contract_route(project_id: str):
    """登记/更新一份 SOW 合同台账（upsert by sow_type；source_uri 须 fdeops:// 指针）。"""
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        data = record_contract(
            actor=g.current_user, project_id=project_id, payload=payload
        )
        return jsonify({"data": data, "error": None})
    except ContractServiceError as error:
        return _contract_error(error)


@projects_blueprint.get("/<project_id>/members")
@require_auth
def list_project_members_route(project_id: str):
    try:
        members, project_version = list_project_members(
            actor=g.current_user, project_id=project_id
        )
        return jsonify(
            {
                "data": {"items": members, "project_version": project_version},
                "error": None,
            }
        )
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.post("/<project_id>/members")
@require_auth
def add_project_member_route(project_id: str):
    payload = _json_payload()
    if not _valid_member_payload(payload, MEMBER_CREATE_FIELDS):
        return _invalid_request()
    assert payload is not None
    try:
        member = add_project_member(
            actor=g.current_user,
            project_id=project_id,
            expected_version=payload["version"],
            user_id=payload["user_id"],
            role=payload["role"],
        )
        return jsonify({"data": member, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.patch("/<project_id>/members/<member_identifier>")
@require_auth
def update_project_member_route(project_id: str, member_identifier: str):
    payload = _json_payload()
    if not _valid_member_payload(payload, MEMBER_UPDATE_FIELDS):
        return _invalid_request()
    assert payload is not None
    try:
        member = update_project_member(
            actor=g.current_user,
            project_id=project_id,
            member_identifier=member_identifier,
            expected_version=payload["version"],
            role=payload["role"],
        )
        return jsonify({"data": member, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.delete("/<project_id>/members/<member_identifier>")
@require_auth
def remove_project_member_route(project_id: str, member_identifier: str):
    payload = _json_payload()
    if not _valid_member_payload(payload, VERSION_ONLY_FIELDS):
        return _invalid_request()
    assert payload is not None
    try:
        remove_project_member(
            actor=g.current_user,
            project_id=project_id,
            member_identifier=member_identifier,
            expected_version=payload["version"],
        )
        return "", 204
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.post("/<project_id>/tasks/assign-defaults")
@require_auth
def assign_project_default_tasks_route(project_id: str):
    payload = _json_payload()
    if not _valid_member_payload(payload, VERSION_ONLY_FIELDS):
        return _invalid_request()
    assert payload is not None
    try:
        assignments = assign_project_default_tasks(
            actor=g.current_user,
            project_id=project_id,
            expected_version=payload["version"],
        )
        return jsonify({"data": assignments, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.post("/<project_id>/tasks/batch-assignments")
@require_auth
def batch_assign_project_tasks_route(project_id: str):
    payload = _json_payload()
    assignments = payload.get("tasks") if payload is not None else None
    if (
        payload is None
        or set(payload) != {"member_user_id", "mode", "tasks"}
        or not isinstance(payload.get("member_user_id"), str)
        or not payload["member_user_id"].strip()
        or payload.get("mode") not in BATCH_ASSIGNMENT_MODES
        or not isinstance(assignments, list)
        or not assignments
        or len(assignments) > 200
        or any(
            not isinstance(item, dict)
            or set(item) != {"task_id", "version"}
            or not isinstance(item.get("task_id"), str)
            or not item["task_id"]
            or type(item.get("version")) is not int
            or item["version"] < 1
            for item in assignments
        )
        or len({item["task_id"] for item in assignments}) != len(assignments)
    ):
        return _invalid_request()
    try:
        result = batch_assign_project_tasks(
            actor=g.current_user,
            project_id=project_id,
            member_user_id=payload["member_user_id"],
            mode=payload["mode"],
            assignments=assignments,
        )
        return jsonify({"data": result, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.post("/<project_id>/modules")
@require_auth
def append_project_module_route(project_id: str):
    payload = _json_payload()
    if (
        payload is None
        or set(payload) != {"module_key", "planned_start_date", "version"}
        or not isinstance(payload.get("module_key"), str)
        or not isinstance(payload.get("planned_start_date"), str)
        or type(payload.get("version")) is not int
        or payload["version"] < 1
    ):
        return _invalid_request()
    try:
        module = append_project_module(
            actor=g.current_user,
            project_id=project_id,
            module_key=payload["module_key"],
            planned_start_date=payload["planned_start_date"],
            expected_version=payload["version"],
        )
        return jsonify({"data": module, "error": None}), 201
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.delete("/<project_id>/modules/<module_identifier>")
@require_auth
def cancel_project_module_route(project_id: str, module_identifier: str):
    payload = _json_payload()
    if not _valid_member_payload(payload, VERSION_ONLY_FIELDS):
        return _invalid_request()
    assert payload is not None
    try:
        module = cancel_project_module(
            actor=g.current_user,
            project_id=project_id,
            module_identifier=module_identifier,
            expected_version=payload["version"],
        )
        return jsonify({"data": module, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.get("/<project_id>/tasks")
@require_auth
def list_project_tasks_route(project_id: str):
    if set(request.args) - {"status", "module_key", "assignee_user_id"}:
        return _invalid_request()
    status = _query_text("status")
    if status is not None and status not in TASK_STATUSES:
        return _invalid_request()
    try:
        tasks = list_project_tasks(
            actor=g.current_user,
            project_id=project_id,
            query={
                "status": status,
                "module_key": _query_text("module_key"),
                "assignee_user_id": _query_text("assignee_user_id"),
            },
        )
        return jsonify({"data": {"items": tasks}, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.get("/<project_id>/gantt")
@require_auth
def get_project_gantt_route(project_id: str):
    try:
        return jsonify(
            {"data": get_project_gantt(actor=g.current_user, project_id=project_id), "error": None}
        )
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.get("/<project_id>/tasks/<task_id>")
@require_auth
def get_project_task_route(project_id: str, task_id: str):
    try:
        task = get_project_task(
            actor=g.current_user, project_id=project_id, task_id=task_id
        )
        return jsonify({"data": task, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.patch("/<project_id>/tasks/<task_id>")
@require_auth
def update_project_task_route(project_id: str, task_id: str):
    payload = _json_payload()
    if (
        not payload
        or set(payload) - (TASK_UPDATE_FIELDS | {"version"})
        or type(payload.get("version")) is not int
        or payload["version"] < 1
        or not set(payload) - {"version"}
    ):
        return _invalid_request()
    try:
        task = update_project_task(
            actor=g.current_user,
            project_id=project_id,
            task_id=task_id,
            expected_version=payload["version"],
            changes={key: value for key, value in payload.items() if key != "version"},
        )
        return jsonify({"data": task, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.post("/<project_id>/modules/<module_identifier>/tasks")
@require_auth
def create_project_task_route(project_id: str, module_identifier: str):
    payload = _json_payload()
    if (
        not payload
        or set(payload) - {
            "name",
            "description",
            "duration_days",
            "planned_start_date",
            "assignee_user_id",
            "collaborator_user_ids",
            "dependency_ids",
            "sop_node",
            "gate",
            "evidence_uri",
            "evidence_hash",
        }
        or not isinstance(payload.get("name"), str)
        or type(payload.get("duration_days")) is not int
        or payload["duration_days"] < 1
    ):
        return _invalid_request()
    try:
        task = create_project_task(
            actor=g.current_user,
            project_id=project_id,
            module_identifier=module_identifier,
            input=payload,
        )
        return jsonify({"data": task, "error": None}), 201
    except ProjectServiceError as error:
        return _service_error(error)


def _list_query() -> dict[str, Any] | None:
    if set(request.args) - {
        "search",
        "status",
        "leader_user_id",
        "industry",
        "module_key",
        "page",
        "page_size",
    }:
        return None
    page = _positive_int(request.args.get("page", "1"))
    page_size = _positive_int(request.args.get("page_size", "20"))
    status = request.args.get("status")
    if (
        page is None
        or page_size is None
        or page_size > 100
        or (status is not None and status not in PROJECT_STATUSES)
    ):
        return None
    return {
        "search": _query_text("search"),
        "status": status,
        "leader_user_id": _query_text("leader_user_id"),
        "industry": _query_text("industry"),
        "module_key": _query_text("module_key"),
        "page": page,
        "page_size": page_size,
    }


def _query_text(name: str) -> str | None:
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _positive_int(value: str) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _json_payload() -> dict[str, Any] | None:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else None


def _valid_member_payload(
    payload: dict[str, Any] | None, fields: frozenset[str]
) -> bool:
    return (
        payload is not None
        and set(payload) == fields
        and type(payload.get("version")) is int
        and payload["version"] > 0
        and ("user_id" not in fields or isinstance(payload.get("user_id"), str))
        and ("role" not in fields or isinstance(payload.get("role"), str))
    )


def _invalid_request():
    return error_response("invalid_request", "The request body is invalid.", 400)


def _service_error(error: ProjectServiceError):
    return error_response(error.code, error.message, error.status)


def _gate_error(error: GateServiceError):
    return error_response(error.code, error.message, error.status)


def _quote_error(error: QuoteServiceError):
    return error_response(error.code, error.message, error.status)


def _payment_error(error: PaymentServiceError):
    return error_response(error.code, error.message, error.status)


def _contract_error(error: ContractServiceError):
    return error_response(error.code, error.message, error.status)
