"""handover 蓝图：8 路由（goal-tb tb4，T-B1 封包半）。

全部不进 api_catalog（业务对象不走 change_set 双轨，沿 dispatch.packages
与 transcripts 先例）。权限：查看=can_view；创建/编辑/封存/解封=can_manage；
交付登记=**admin**（D11 草案「delivered（登记对外交付）=admin」）。
"""

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.handover import service

handover_blueprint = Blueprint("handover", __name__, url_prefix="/api/v1")


@handover_blueprint.errorhandler(service.HandoverServiceError)
def service_error(error):
    return error_response(error.code, error.message, error.status, error.detail or None)


def _payload():
    value = request.get_json(silent=True)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise service.HandoverServiceError("invalid_request", "请求内容必须为 JSON 对象。", 400)
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
            raise service.HandoverServiceError("invalid_request", "limit 必须是整数。", 400) from None
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except ValueError:
            raise service.HandoverServiceError("invalid_request", "offset 必须是整数。", 400) from None
    if not 1 <= limit <= _LIST_LIMIT_MAX:
        raise service.HandoverServiceError(
            "invalid_request", f"limit 须在 1..{_LIST_LIMIT_MAX}。", 400
        )
    if offset < 0:
        raise service.HandoverServiceError("invalid_request", "offset 不能为负。", 400)
    return limit, offset


@handover_blueprint.post("/handover-packages")
@require_auth
def create_package():
    """创建草稿交付包（can_manage；items 逐项快照指针+指纹）。"""
    return _data(service.create_package(actor=g.current_user, payload=_payload())), 201


@handover_blueprint.get("/handover-packages")
@require_auth
def list_packages():
    """交付包列表（can_view）：project 过滤＋有界分页；items 走详情端点。"""
    limit, offset = _pagination_args()
    return _data(
        service.list_packages(
            actor=g.current_user,
            project_id=request.args.get("project_id"),
            limit=limit,
            offset=offset,
        )
    )


@handover_blueprint.get("/handover-packages/artifacts")
@require_auth
def available_artifacts():
    """封包挑选面：本项目已复核产物投影（只读；须先于 /<id> 路由注册）。"""
    project_id = request.args.get("project_id")
    if not project_id:
        raise service.HandoverServiceError("invalid_request", "project_id 必填。", 400)
    return _data(service.available_artifacts(actor=g.current_user, project_id=project_id))


@handover_blueprint.get("/handover-packages/<package_id>")
@require_auth
def get_package(package_id):
    """交付包详情（items+manifest 视图；draft 无 manifest）。"""
    return _data(service.get_package(actor=g.current_user, package_id=package_id))


@handover_blueprint.patch("/handover-packages/<package_id>")
@require_auth
def update_package(package_id):
    """编辑草稿包（label/items 全量替换；封存后 409）。"""
    return _data(service.update_package(actor=g.current_user, package_id=package_id, payload=_payload()))


@handover_blueprint.post("/handover-packages/<package_id>/seal")
@require_auth
def seal_package(package_id):
    """封存（can_manage）：逐项校验+冻结清单+manifest_sha256（规范化 JSON 哈希）。"""
    return _data(service.seal_package(actor=g.current_user, package_id=package_id))


@handover_blueprint.post("/handover-packages/<package_id>/unseal")
@require_auth
def unseal_package(package_id):
    """解封（can_manage）：sealed→draft，清封存三痕、unsealed_count 留痕。"""
    return _data(service.unseal_package(actor=g.current_user, package_id=package_id))


@handover_blueprint.post("/handover-packages/<package_id>/deliver")
@require_auth
def deliver_package(package_id):
    """交付登记（admin）：sealed→delivered 终态不可逆。"""
    return _data(service.deliver_package(actor=g.current_user, package_id=package_id))
