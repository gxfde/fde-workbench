"""meetings 蓝图：9 路由（goal-d5 六路由 + goal-d7 pause/resume/cost）。

api_catalog 只收只读四条（模板/会议状态/纪要/会议成本）；POST 召集/发言/
收敛/暂停/恢复属人工授权写路径，继续不收（沿门禁三路由与 d4 agents 先例）
——评审结论永远经人工收敛，AI 不代拍板。
"""

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.meetings import service

meetings_blueprint = Blueprint("meetings", __name__, url_prefix="/api/v1")


@meetings_blueprint.errorhandler(service.MeetingsServiceError)
def service_error(error):
    return error_response(error.code, error.message, error.status, error.detail or None)


def _payload():
    value = request.get_json(silent=True)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise service.MeetingsServiceError("invalid_request", "请求内容必须为 JSON 对象。", 400)
    return value


def _data(value):
    return jsonify({"data": value, "error": None})


@meetings_blueprint.post("/meetings")
@require_auth
def create_meeting():
    """召集评审会（人工开会；智能体召集走工具面 dispatch_agent_tool）。"""
    return _data(service.create_meeting(actor=g.current_user, payload=_payload())), 201


@meetings_blueprint.get("/meetings/<meeting_id>")
@require_auth
def get_meeting(meeting_id):
    """会议状态 + 话轮流（只读）。"""
    return _data(service.get_meeting(actor=g.current_user, meeting_id=meeting_id))


_LIST_LIMIT_DEFAULT = 50
_LIST_LIMIT_MAX = 200


def _pagination_args() -> tuple[int, int]:
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = _LIST_LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except ValueError:
            raise service.MeetingsServiceError("invalid_request", "limit 必须是整数。", 400) from None
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except ValueError:
            raise service.MeetingsServiceError("invalid_request", "offset 必须是整数。", 400) from None
    if not 1 <= limit <= _LIST_LIMIT_MAX:
        raise service.MeetingsServiceError(
            "invalid_request", f"limit 须在 1..{_LIST_LIMIT_MAX}。", 400
        )
    if offset < 0:
        raise service.MeetingsServiceError("invalid_request", "offset 不能为负。", 400)
    return limit, offset


@meetings_blueprint.get("/meetings")
@require_auth
def list_meetings():
    """会议列表（T-A8 桌面控制台，只读）：project 过滤＋有界分页。

    列表行不带话轮正文（防 N+1，话轮计数预聚合），话轮/纪要走既有详情端点
    按需取；人工控制台面，不进 api_catalog（沿 T-W6 workflow 列表与 B#9
    execution-facts 同款先例）。
    """
    limit, offset = _pagination_args()
    return _data(
        service.list_meetings(
            actor=g.current_user,
            project_id=request.args.get("project_id"),
            limit=limit,
            offset=offset,
        )
    )


@meetings_blueprint.post("/meetings/<meeting_id>/turns")
@require_auth
def add_turn(meeting_id):
    """创业者插话 / 点名角色发言（话轮预算硬墙，M6）。"""
    return _data(service.add_turn(actor=g.current_user, meeting_id=meeting_id, payload=_payload()))


@meetings_blueprint.post("/meetings/<meeting_id>/close")
@require_auth
def close_meeting(meeting_id):
    """收敛纪要（守卫复核引用闭合 + sealed_sha256 封存，不可变）。"""
    return _data(service.close_meeting(actor=g.current_user, meeting_id=meeting_id, payload=_payload()))


@meetings_blueprint.get("/meetings/<meeting_id>/minutes")
@require_auth
def get_minutes(meeting_id):
    """纪要三段式 + 溯源回链（triggered_by_run_id / topic_refs，M2）。"""
    return _data(service.get_minutes(actor=g.current_user, meeting_id=meeting_id))


@meetings_blueprint.get("/meeting-templates")
@require_auth
def list_meeting_templates():
    """评审会模板列表（gate_tier 三档；T2-lite/T3-adhoc）。"""
    return _data(service.list_meeting_templates())


@meetings_blueprint.get("/meeting-templates/<template_id>/checklist")
@require_auth
def get_template_checklist(template_id):
    """强制门模板的静态人工执行单（U9）：智能体层不可用时门降级为 checklist
    交人工执行，不阻塞交付（模板本就是门禁语义，checklist 是其人工形态）。
    """
    return _data(service.get_template_checklist(template_id))


@meetings_blueprint.post("/meetings/<meeting_id>/pause")
@require_auth
def pause_meeting(meeting_id):
    """M7 中断恢复：主持人暂停会议（恢复窗口 = 24h，超窗自动收场）。"""
    return _data(service.pause_meeting(actor=g.current_user, meeting_id=meeting_id))


@meetings_blueprint.post("/meetings/<meeting_id>/resume")
@require_auth
def resume_meeting(meeting_id):
    """M7 中断恢复：恢复暂停会议；≤24h 复活，超窗自动收场出未完成纪要并 409。"""
    return _data(service.resume_meeting(actor=g.current_user, meeting_id=meeting_id))


@meetings_blueprint.get("/meetings/<meeting_id>/cost")
@require_auth
def get_meeting_cost(meeting_id):
    """M9 成本按会议归集：召集计费 + 触发 run 累计（只读，进 api_catalog）。"""
    return _data(service.get_meeting_cost(actor=g.current_user, meeting_id=meeting_id))
