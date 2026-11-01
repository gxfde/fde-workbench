"""meetings 蓝图：6 路由（goal-d5，PartyMode §6 REST 增量）。

api_catalog 只收只读三条（模板/会议状态/纪要）；POST 召集/发言/收敛属
人工授权写路径，继续不收（沿门禁三路由与 d4 agents 先例）——评审结论
永远经人工收敛，AI 不代拍板。
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
