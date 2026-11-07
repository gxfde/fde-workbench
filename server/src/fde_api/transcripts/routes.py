"""transcripts 蓝图：7 路由（goal-tb tb1，T-A9）。

全部不进 api_catalog（沿真相层与业务对象纪律：草稿区/纪要不走 change_set
双轨、不是 AI 工具面；参照 T-W6 列表与 dispatch.packages 先例）。
权限：草稿写入/读取=项目成员（can_view，沿 T-A3 校准「录入 member 已可用」）；
晋升=can_manage（入正式库=管理动作）。
"""

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.transcripts import service

transcripts_blueprint = Blueprint("transcripts", __name__, url_prefix="/api/v1")


@transcripts_blueprint.errorhandler(service.TranscriptsServiceError)
def service_error(error):
    return error_response(error.code, error.message, error.status, error.detail or None)


def _payload():
    value = request.get_json(silent=True)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise service.TranscriptsServiceError("invalid_request", "请求内容必须为 JSON 对象。", 400)
    return value


def _data(value):
    return jsonify({"data": value, "error": None})


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
            raise service.TranscriptsServiceError("invalid_request", "limit 必须是整数。", 400) from None
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except ValueError:
            raise service.TranscriptsServiceError("invalid_request", "offset 必须是整数。", 400) from None
    if not 1 <= limit <= _LIST_LIMIT_MAX:
        raise service.TranscriptsServiceError(
            "invalid_request", f"limit 须在 1..{_LIST_LIMIT_MAX}。", 400
        )
    if offset < 0:
        raise service.TranscriptsServiceError("invalid_request", "offset 不能为负。", 400)
    return limit, offset


@transcripts_blueprint.post("/transcript-drafts")
@require_auth
def create_draft():
    """创建转写草稿（文本载荷；录音原件永不进平台——只收宿主侧产出/人工文本）。"""
    return _data(service.create_draft(actor=g.current_user, payload=_payload())), 201


@transcripts_blueprint.get("/transcript-drafts")
@require_auth
def list_drafts():
    """草稿列表（T+7 临时区，含墓碑供合规对账）：project/status 过滤＋有界分页。

    列表行不带正文与复核条目（防大载荷），正文走详情端点按需取；
    人工控制台面，不进 api_catalog。
    """
    limit, offset = _pagination_args()
    return _data(
        service.list_drafts(
            actor=g.current_user,
            project_id=request.args.get("project_id"),
            status=request.args.get("status"),
            limit=limit,
            offset=offset,
        )
    )


@transcripts_blueprint.get("/transcript-drafts/<draft_id>")
@require_auth
def get_draft(draft_id):
    """草稿详情（活动草稿带正文+复核条目；墓碑只回指针与时间戳）。"""
    return _data(service.get_draft(actor=g.current_user, draft_id=draft_id))


@transcripts_blueprint.post("/transcript-drafts/<draft_id>/discard")
@require_auth
def discard_draft(draft_id):
    """人工弃置草稿（墓碑化：正文/指纹/复核条目整组抹除 + 文件根清空）。"""
    return _data(service.discard_draft(actor=g.current_user, draft_id=draft_id))


@transcripts_blueprint.post("/transcript-drafts/<draft_id>/promote")
@require_auth
def promote_draft(draft_id):
    """晋升：人工整理纪要 + 客户确认三要素 → interview_minutes 正式库（can_manage）。"""
    return _data(
        service.promote_draft(actor=g.current_user, draft_id=draft_id, payload=_payload())
    )


@transcripts_blueprint.get("/interview-minutes")
@require_auth
def list_minutes():
    """访谈纪要列表（正式库）：project 过滤＋有界分页；正文走详情端点。"""
    limit, offset = _pagination_args()
    return _data(
        service.list_minutes(
            actor=g.current_user,
            project_id=request.args.get("project_id"),
            limit=limit,
            offset=offset,
        )
    )


@transcripts_blueprint.get("/interview-minutes/<minutes_id>")
@require_auth
def get_minutes(minutes_id):
    """纪要详情（正文+指纹+客户确认三要素）。"""
    return _data(service.get_minutes(actor=g.current_user, minutes_id=minutes_id))
