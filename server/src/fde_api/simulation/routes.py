"""模拟训练场 API（V3.2 G2）。

蓝图前缀 ``/api/v1/simulation``。**有意不进 api_catalog**——这是训练场治理面
（与 ``ontology`` 全局面、``agents`` admin 面、``expirations`` 投影面同款惯例），
AI 不经此面读写模拟资产。

权限：全部端点要求 ``project_operator`` 档（fde_engineer / project_lead /
admin）；``viewer`` 档无权访问。鉴权走既有 ``require_auth`` 装饰器 + 服务层
能力档判定（服务层是唯一权威，路由层不复制判定逻辑）。
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.simulation import (
    evaluator,
    improvement_service,
    regression_service,
    release_channel,
    run_service,
    service,
)

simulation_blueprint = Blueprint("simulation", __name__, url_prefix="/api/v1/simulation")


@simulation_blueprint.errorhandler(service.ScenarioServiceError)
def service_error(error):
    return error_response(error.code, error.message, error.status, error.detail or None)


def _payload() -> dict:
    value = request.get_json(silent=True)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise service.ScenarioServiceError(
            "invalid_request", "请求内容必须为 JSON 对象。", 400
        )
    return value


def _data(value):
    return jsonify({"data": value, "error": None})


def _int_arg(name: str, default: int | None = None) -> int | None:
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise service.ScenarioServiceError("invalid_request", f"{name} 必须是整数。", 400)


# ---------------------------------------------------------------------------
# 场景库
# ---------------------------------------------------------------------------


@simulation_blueprint.get("/scenarios")
@require_auth
def list_scenarios():
    """场景列表（默认每个分支只返回有效版本；include_history=true 返回全史）。"""
    data = service.list_scenarios(
        actor=g.current_user,
        split=request.args.get("split"),
        industry=request.args.get("industry"),
        variant=request.args.get("variant"),
        status=request.args.get("status"),
        keyword=request.args.get("q"),
        include_history=request.args.get("include_history") == "true",
        limit=_int_arg("limit", service.LIST_PAGE_SIZE) or service.LIST_PAGE_SIZE,
    )
    return _data(data)


@simulation_blueprint.post("/scenarios")
@require_auth
def create_scenario():
    """创建场景（版本 1）。"""
    data = service.create_scenario(actor=g.current_user, payload=_payload())
    return _data(data), 201


@simulation_blueprint.get("/scenarios/<scenario_id>")
@require_auth
def get_scenario(scenario_id):
    """场景详情。"""
    return _data(service.get_scenario(actor=g.current_user, scenario_id=scenario_id))


@simulation_blueprint.patch("/scenarios/<scenario_id>")
@require_auth
def update_scenario(scenario_id):
    """编辑场景（内容变更追加新版本 201；纯 draft⇄active 状态切换原地更新 200）。"""
    body = _payload()
    data = service.update_scenario(
        actor=g.current_user, scenario_id=scenario_id, payload=body
    )
    status_code = 200 if service._is_status_only_toggle(body) else 201
    return _data(data), status_code


@simulation_blueprint.post("/scenarios/<scenario_id>/duplicate")
@require_auth
def duplicate_scenario(scenario_id):
    """复制场景 → 新业务键。"""
    data = service.duplicate_scenario(
        actor=g.current_user, scenario_id=scenario_id, payload=_payload()
    )
    return _data(data), 201


@simulation_blueprint.post("/scenarios/<scenario_id>/archive")
@require_auth
def archive_scenario(scenario_id):
    """归档场景（追加 archived 新版本）。"""
    data = service.archive_scenario(actor=g.current_user, scenario_id=scenario_id)
    return _data(data)


@simulation_blueprint.get("/scenarios/<scenario_id>/versions")
@require_auth
def list_versions(scenario_id):
    """某案例（业务键）的全部分支与版本历史。"""
    with_version_key = request.args.get("scenario_key")
    if not with_version_key:
        current = service.get_scenario(actor=g.current_user, scenario_id=scenario_id)
        with_version_key = current["scenario_key"]
    return _data(service.list_versions(actor=g.current_user, scenario_key=with_version_key))


@simulation_blueprint.post("/scenarios/import")
@require_auth
def import_scenarios():
    """批量导入场景（逐条校验，非法条目逐条回显）。"""
    return _data(service.import_scenarios(actor=g.current_user, payload=_payload()))


@simulation_blueprint.get("/scenarios/export")
@require_auth
def export_scenarios():
    """导出现场景（有效版本）。"""
    include_reference = request.args.get("include_reference") != "false"
    data = service.export_scenarios(
        actor=g.current_user,
        scenario_key=request.args.get("scenario_key"),
        split=request.args.get("split"),
        variant=request.args.get("variant"),
        include_reference=include_reference,
    )
    return _data(data)


# ---------------------------------------------------------------------------
# 模拟运行（G3）
# ---------------------------------------------------------------------------


@simulation_blueprint.get("/runs")
@require_auth
def list_runs():
    """运行列表。"""
    data = run_service.list_runs(
        actor=g.current_user,
        scenario_id=request.args.get("scenario_id"),
        status=request.args.get("status"),
        split=request.args.get("split"),
        limit=_int_arg("limit", run_service.LIST_PAGE_SIZE) or run_service.LIST_PAGE_SIZE,
    )
    return _data(data)


@simulation_blueprint.post("/runs")
@require_auth
def create_run():
    """创建模拟运行（``execute=true`` 时立即执行一次）。"""
    data = run_service.create_run(actor=g.current_user, payload=_payload())
    return _data(data), 201


@simulation_blueprint.get("/runs/<run_id>")
@require_auth
def get_run(run_id):
    """运行详情。"""
    include_context = request.args.get("include_context") == "true"
    return _data(
        run_service.get_run(
            actor=g.current_user, run_id=run_id, include_context=include_context
        )
    )


@simulation_blueprint.post("/runs/<run_id>/execute")
@require_auth
def execute_run(run_id):
    """执行一次模拟运行（同步）。真实适配面不可用时明确 409，不静默退回 mock。"""
    return _data(run_service.execute_run(actor=g.current_user, run_id=run_id))


@simulation_blueprint.post("/runs/<run_id>/cancel")
@require_auth
def cancel_run(run_id):
    """取消运行（终态不可取消）。"""
    return _data(run_service.cancel_run(actor=g.current_user, run_id=run_id))


@simulation_blueprint.post("/runs/<run_id>/retry")
@require_auth
def retry_run(run_id):
    """重试运行（attempt+1 派生新键；failed_hard 不可重试）。"""
    data = run_service.retry_run(actor=g.current_user, run_id=run_id)
    return _data(data), 201


@simulation_blueprint.get("/runs/<run_id>/trace")
@require_auth
def list_traces(run_id):
    """读取运行 Trace（seq 游标分页）。"""
    data = run_service.list_traces(
        actor=g.current_user,
        run_id=run_id,
        phase=request.args.get("phase"),
        after_seq=_int_arg("after_seq"),
        limit=_int_arg("limit", run_service.TRACE_PAGE_SIZE) or run_service.TRACE_PAGE_SIZE,
    )
    return _data(data)


# ---------------------------------------------------------------------------
# 评估（G4）
# ---------------------------------------------------------------------------


@simulation_blueprint.post("/runs/<run_id>/evaluate")
@require_auth
def evaluate_run(run_id):
    """评估一次运行：L-A 规则层（+ 可选 L-B 模型层），落评估行。"""
    include_model = request.args.get("include_model") != "false"
    model_mode = request.args.get("model_mode") or "stub"
    try:
        data = evaluator.evaluate_run(
            actor=g.current_user,
            run_id=run_id,
            include_model=include_model,
            model_mode=model_mode,
        )
    except evaluator.EvaluationError as error:
        return error_response(error.code, error.message, error.status)
    return _data(data)


@simulation_blueprint.get("/runs/<run_id>/evaluation")
@require_auth
def get_evaluation(run_id):
    """读取评估报告（按层并列，不合并）。"""
    try:
        data = evaluator.get_evaluation_report(actor=g.current_user, run_id=run_id)
    except evaluator.EvaluationError as error:
        return error_response(error.code, error.message, error.status)
    return _data(data)


@simulation_blueprint.post("/runs/<run_id>/evaluation/human")
@require_auth
def record_human_evaluation(run_id):
    """人工抽检结论（L-C）：留痕，**不覆盖**机器原行。"""
    try:
        data = evaluator.record_human_evaluation(
            actor=g.current_user, run_id=run_id, payload=_payload()
        )
    except evaluator.EvaluationError as error:
        return error_response(error.code, error.message, error.status)
    return _data(data), 201


# ---------------------------------------------------------------------------
# 失败分析与改进提案（G5）
# ---------------------------------------------------------------------------


@simulation_blueprint.get("/findings")
@require_auth
def list_findings():
    """失败发现清单。"""
    try:
        data = improvement_service.list_findings(
            actor=g.current_user, run_id=request.args.get("run_id")
        )
    except service.ScenarioServiceError as error:
        return error_response(error.code, error.message, error.status, error.detail or None)
    return _data(data)


@simulation_blueprint.post("/findings/<finding_id>/adjudicate")
@require_auth
def adjudicate_finding(finding_id):
    """失败发现人工裁定（条款③写面）：confirm/reject 单向＋detail_json 留痕；
    再终裁收敛口径由 effective 投影承接——治理面动作，不进 api_catalog。"""
    try:
        data = improvement_service.adjudicate_finding(
            actor=g.current_user, finding_id=finding_id, payload=_payload()
        )
    except service.ScenarioServiceError as error:
        return error_response(error.code, error.message, error.status, error.detail or None)
    return _data(data)


@simulation_blueprint.post("/runs/<run_id>/analyze")
@require_auth
def analyze_run(run_id):
    """失败分析（三源化，学习闭环 2.0 L4）：L-A 规则层＋L-B 真模型层（likely）
    ＋L-C 人工终裁最新行（confirmed）；幂等不增殖。"""
    try:
        data = improvement_service.analyze_run(actor=g.current_user, run_id=run_id)
    except service.ScenarioServiceError as error:
        return error_response(error.code, error.message, error.status, error.detail or None)
    return _data(data)


@simulation_blueprint.post("/findings/draft-ai")
@require_auth
def draft_findings_ai():
    """AI 蒸馏起草（学习闭环 2.0 L4 断点③；**不进 api_catalog**——治理审阅面）。

    返件式零落库：蒸馏输入＝字段允许名单投影（evidence_refs/reason/note 不进
    起草面）；产出三型候选载荷（lesson_entry / skill_version_draft /
    prompt_overlay_fragment）；契约失败整批丢弃重试一次 ⇒ 409
    ``ai_draft_contract_failed``。采纳＝人工确认后经 ``create_proposal``
    （candidate_payload 随提案入档）；AI 通道故障按 DSH 同尺映射。
    """
    from fde_api.control.ai_server_client import DSHRuntimeError
    from fde_api.simulation import improvement_draft

    payload = _payload()
    try:
        data = improvement_draft.draft_improvements(
            actor=g.current_user, finding_ids=payload.get("finding_ids")
        )
    except DSHRuntimeError as error:
        return error_response(error.code, error.public_message, 503 if error.retryable else 409)
    return _data(data)


@simulation_blueprint.get("/proposals")
@require_auth
def list_proposals():
    """改进提案清单。"""
    try:
        data = improvement_service.list_proposals(
            actor=g.current_user,
            status=request.args.get("status"),
            target_kind=request.args.get("target_kind"),
        )
    except service.ScenarioServiceError as error:
        return error_response(error.code, error.message, error.status, error.detail or None)
    return _data(data)


@simulation_blueprint.post("/proposals")
@require_auth
def create_proposal():
    """由失败发现生成改进提案（**只提案，不落地**）。"""
    try:
        data = improvement_service.create_proposal(
            actor=g.current_user, payload=_payload()
        )
    except service.ScenarioServiceError as error:
        return error_response(error.code, error.message, error.status, error.detail or None)
    return _data(data), 201


@simulation_blueprint.get("/proposals/<proposal_id>")
@require_auth
def get_proposal(proposal_id):
    """提案详情。"""
    try:
        data = improvement_service.get_proposal(
            actor=g.current_user, proposal_id=proposal_id
        )
    except service.ScenarioServiceError as error:
        return error_response(error.code, error.message, error.status, error.detail or None)
    return _data(data)


@simulation_blueprint.patch("/proposals/<proposal_id>")
@require_auth
def update_proposal(proposal_id):
    """编辑提案（仅草稿态）。"""
    try:
        data = improvement_service.update_proposal(
            actor=g.current_user, proposal_id=proposal_id, payload=_payload()
        )
    except service.ScenarioServiceError as error:
        return error_response(error.code, error.message, error.status, error.detail or None)
    return _data(data)


@simulation_blueprint.post("/proposals/<proposal_id>/decide")
@require_auth
def decide_proposal(proposal_id):
    """审批提案（approve/reject）——**审批 ≠ 发布**。"""
    try:
        data = improvement_service.decide_proposal(
            actor=g.current_user, proposal_id=proposal_id, payload=_payload()
        )
    except service.ScenarioServiceError as error:
        return error_response(error.code, error.message, error.status, error.detail or None)
    return _data(data)


@simulation_blueprint.get("/proposals/<proposal_id>/release-preview")
@require_auth
def preview_proposal_release(proposal_id):
    """发布前并排预览（L5 注入闸五件套③：注入终文＋purpose＋近 30 天调用量＋过拟合闸状态）。"""
    try:
        data = release_channel.preview_proposal_release(
            actor=g.current_user, proposal_id=proposal_id
        )
    except service.ScenarioServiceError as error:
        return error_response(error.code, error.message, error.status, error.detail or None)
    return _data(data)


@simulation_blueprint.post("/proposals/<proposal_id>/release")
@require_auth
def release_proposal(proposal_id):
    """发布提案（N4 G-11 受控发布通道：admin＋密码＋回归计划在案；可回滚）。

    **发布 ≠ 自动落地**：只动提案状态与 release_json（受控记账面），生产
    提示词/Skill/本体正文零触碰——正文改动仍由人工在治理面实施。
    """
    try:
        data = release_channel.release_proposal(
            actor=g.current_user, proposal_id=proposal_id, payload=_payload()
        )
    except service.ScenarioServiceError as error:
        return error_response(error.code, error.message, error.status, error.detail or None)
    return _data(data)


@simulation_blueprint.post("/proposals/<proposal_id>/rollback")
@require_auth
def rollback_release(proposal_id):
    """回滚已发布提案（published → approved；原发布字段保留，审计链不断）。"""
    try:
        data = release_channel.rollback_release(
            actor=g.current_user, proposal_id=proposal_id, payload=_payload()
        )
    except service.ScenarioServiceError as error:
        return error_response(error.code, error.message, error.status, error.detail or None)
    return _data(data)


# ---------------------------------------------------------------------------
# 回归与盲测（G6）
# ---------------------------------------------------------------------------


@simulation_blueprint.get("/regression/suites")
@require_auth
def list_regression_suites():
    """回归套件清单。"""
    try:
        data = regression_service.list_suites(actor=g.current_user)
    except service.ScenarioServiceError as error:
        return error_response(error.code, error.message, error.status, error.detail or None)
    return _data(data)


@simulation_blueprint.post("/regression/suites")
@require_auth
def create_regression_suite():
    """创建回归套件（可按 split 自动取该集全部场景）。"""
    try:
        data = regression_service.create_suite(
            actor=g.current_user, payload=_payload()
        )
    except service.ScenarioServiceError as error:
        return error_response(error.code, error.message, error.status, error.detail or None)
    return _data(data), 201


@simulation_blueprint.get("/regression/suites/<suite_id>")
@require_auth
def get_regression_suite(suite_id):
    """套件详情。"""
    try:
        data = regression_service.get_suite(actor=g.current_user, suite_id=suite_id)
    except service.ScenarioServiceError as error:
        return error_response(error.code, error.message, error.status, error.detail or None)
    return _data(data)


@simulation_blueprint.post("/regression/suites/<suite_id>/run")
@require_auth
def run_regression_suite(suite_id):
    """跑一次回归对比（stub+mock 同步 201；model:server 或 workbench 转后台作业返回 202）。"""
    payload = _payload()
    try:
        data = regression_service.run_regression(
            actor=g.current_user,
            suite_id=suite_id,
            proposal_id=payload.get("proposal_id"),
            force_sync=bool(payload.get("force_sync")),
        )
    except service.ScenarioServiceError as error:
        return error_response(error.code, error.message, error.status, error.detail or None)
    status_code = 202 if data.get("queued_async") else 201
    return _data(data), status_code


@simulation_blueprint.get("/regression/jobs/<job_id>")
@require_auth
def get_regression_job(job_id):
    """查询异步回归后台作业状态（供桌面端轮询）。"""
    try:
        data = regression_service.get_regression_job_status(
            actor=g.current_user, job_id=job_id
        )
    except service.ScenarioServiceError as error:
        return error_response(error.code, error.message, error.status, error.detail or None)
    return _data(data)


@simulation_blueprint.get("/regression/results")
@require_auth
def list_regression_results():
    """回归结果清单。"""
    try:
        data = regression_service.list_results(
            actor=g.current_user, suite_id=request.args.get("suite_id")
        )
    except service.ScenarioServiceError as error:
        return error_response(error.code, error.message, error.status, error.detail or None)
    return _data(data)


@simulation_blueprint.get("/regression/results/<result_id>")
@require_auth
def get_regression_result(result_id):
    """回归结果详情。"""
    try:
        data = regression_service.get_result(
            actor=g.current_user, result_id=result_id
        )
    except service.ScenarioServiceError as error:
        return error_response(error.code, error.message, error.status, error.detail or None)
    return _data(data)
