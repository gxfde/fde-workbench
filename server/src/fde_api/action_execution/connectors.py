"""AE1-WP3 连接器白名单门＋SSRF 回环反向预检＋Header 白名单＋真 HTTP 派发。

白名单快照（``whitelist.json``）＝docs 仓冻结件 v1.3.2 的仓内只读副本（v1.3.2＝评审轮 D3 KD-02/D4 登记落痕，2026-11-20）
（变更只能走白名单改版 v2＋评审；**缺失/损坏 fail-closed 全拒**——禁改
清单第 5/7 项：不得回退「任意 URL 可调」）。匹配三元组＝
``(connector_id, method, http_binding)`` 精确匹配（Q6b 追认字段口径：
method＝动作方法名，http_binding＝内层 ``{http_method, path}``）。

安全四件套（52 号 §2 D2 拍板落痕）：
- **白名单**：本模块 L3 门真身（三元组精确匹配；加载期深拷贝固化——
  运行时改内存快照不生效，S-AE-06 A5）；
- **SSRF 预检**（Q7 回环反向收紧）：主机须命中白名单 base_url 集
  （localhost＋固定端口），解析后**全部 IP 须为回环**（127.0.0.0/8、::1）
  ——解析出任何非回环 IP 即 403（DNS 重绑定前置拦截）；禁跟随重定向；
- **Header 白名单**（C-13）：出站头＝固定基线（Content-Type/Accept/
  User-Agent）＋逐连接器登记允许头（Authorization/X-Api-Key/
  Idempotency-Key）——调用方不得自定义任何头（params 头名字段→422）；
- **fail-closed 默认关**：一切判定失败 403 ``tool_not_allowed``。

错误码纪律（Q8）：15 码闭集外的执行期失败（上游非 2xx/超时/连接失败）
映射闭集内 ``tool_not_allowed``＋``details.reason``/``details.http_status``
标注（不扩闭集、不自造码）；上游响应体原文**零回显**（C-08）。

KD-01 归一化（53 号 Q14 终判）：``workbench.ontology`` read 的
``{data:{items:[…]}}`` 端点信封 → ``output = {ontologies: [{ontology_id,
name, org_id}…], count: int}``（id→ontology_id、term→name、请求方 org_id），
使任务集 T4-001 冻结断言逐字可判定；不得原样透传端点信封。
"""
from __future__ import annotations

import copy
import ipaddress
import json
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from fde_api.action_execution.errors import ActionExecutionError

logger = logging.getLogger(__name__)

SNAPSHOT_PATH = Path(__file__).resolve().parent / "whitelist.json"

# C-13 固定基线头（ ae_rule：固定基线＋逐连接器登记允许头；调用方零自定义）
_BASELINE_HEADERS = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "fde-ae1-executor/1.0"}
_API_KEY_PLACEHOLDER = "ae1-placeholder-not-a-real-credential"
_CALLER_HEADER_KEYS = frozenset(
    k.lower()
    for k in (
        "authorization",
        "x-api-key",
        "idempotency-key",
        "x-request-id",
        "cookie",
        "set-cookie",
        "x-csrf-token",
        "proxy-authorization",
    )
)


def load_whitelist(path: str | None = None) -> dict[str, Any]:
    """只读加载白名单快照（fail-closed：缺失/损坏/形态不完整即拒）。"""
    target = Path(path) if path else SNAPSHOT_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ActionExecutionError(
            "tool_not_allowed",
            "连接器白名单缺失或损坏（fail-closed）。",
            details={"reason": "whitelist_load_failed", "error": type(error).__name__},
        ) from None
    if not isinstance(raw, dict) or not isinstance(raw.get("connectors"), list) or not raw.get("version"):
        raise ActionExecutionError(
            "tool_not_allowed",
            "连接器白名单形态不完整（fail-closed）。",
            details={"reason": "whitelist_shape_invalid"},
        )
    # 深层形态逐条校验（评审 P7a）：损坏白名单的任何形态破缺都 fail-closed，
    # 绝不让 AttributeError/ValueError 之类裸异常冒泡成 500。
    for conn in raw["connectors"]:
        if not isinstance(conn, dict) or not isinstance(conn.get("id"), str) or not conn.get("id"):
            raise ActionExecutionError(
                "tool_not_allowed",
                "连接器白名单形态不完整（fail-closed）。",
                details={"reason": "whitelist_shape_invalid"},
            )
        try:
            urllib.parse.urlsplit(str(conn.get("base_url", "")))
        except ValueError:
            raise ActionExecutionError(
                "tool_not_allowed",
                "连接器白名单形态不完整（fail-closed）。",
                details={"reason": "whitelist_shape_invalid"},
            ) from None
        bindings = conn.get("http_bindings", [])
        if not isinstance(bindings, list) or any(not isinstance(b, dict) for b in bindings):
            raise ActionExecutionError(
                "tool_not_allowed",
                "连接器白名单形态不完整（fail-closed）。",
                details={"reason": "whitelist_shape_invalid"},
            )
    return copy.deepcopy(raw)  # 深拷贝固化（S-AE-06 A5：运行时改原 dict 不生效）


class ConnectorWhitelist:
    """L3 门真身：三元组前两腿 ``(connector_id, method)`` 精确匹配。

    加载期固化（构造即深拷贝）；**无任何运行时注册入口**——白名单变更
    只能走改版 v2＋评审（禁改清单第 5/7 项）。``check`` 命中返回连接器
    spec dict，未命中一律 403 ``tool_not_allowed``。
    """

    def __init__(self, snapshot: dict[str, Any]) -> None:
        self._snapshot = copy.deepcopy(snapshot)
        self._by_id: dict[str, dict[str, Any]] = {
            str(conn["id"]): conn for conn in self._snapshot["connectors"] if isinstance(conn, dict) and conn.get("id")
        }

    def check(self, connector_id: str, method: str) -> dict[str, Any]:
        spec = self._by_id.get(connector_id)
        if spec is None or method not in spec.get("methods", []):
            # fail-closed 留痕（白名单 constraints.fail_closed.ae_rule「403 并写
            # 审计事件」——评审 P16：应用日志腿，零 params/响应体）
            logger.info(
                "ae_whitelist_rejected connector=%s method=%s", connector_id, method
            )
            raise ActionExecutionError("tool_not_allowed", "连接器或方法未在白名单注册（fail-closed）。")
        return spec

    def base_urls(self) -> list[str]:
        return [str(conn.get("base_url", "")) for conn in self._snapshot["connectors"]]

    def binding_for(self, spec: dict[str, Any], method: str) -> dict[str, str]:
        """三元组第三腿：method 在 ``methods[]`` 中的下标 ↔ ``http_bindings[]``
        下标一一对应（v1.1 校准口径）；越界＝白名单登记不完整 → fail-closed。"""
        methods = spec.get("methods", [])
        bindings = spec.get("http_bindings", [])
        try:
            index = methods.index(method)
            binding = bindings[index]
        except (ValueError, IndexError):
            raise ActionExecutionError(
                "tool_not_allowed",
                "白名单 http_binding 登记不完整（fail-closed）。",
                details={"reason": "whitelist_binding_missing"},
            ) from None
        return {"http_method": str(binding.get("http_method", "")), "path": str(binding.get("path", ""))}


def ssrf_precheck(url: str, whitelist: dict[str, Any]) -> None:
    """SSRF 回环反向预检（Q7）：主机∈白名单 base_url 集＋解析即校验
    （不等连接）——解析后全部 IP 须为回环（127.0.0.0/8、::1），任何非回环
    IP 即 403（DNS 重绑定前置拦截）。"""
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    port = parsed.port
    allowed_hosts: set[tuple[str, int | None]] = set()
    for base in ConnectorWhitelist(whitelist).base_urls():
        bp = urllib.parse.urlsplit(base)
        allowed_hosts.add((bp.hostname or "", bp.port))
    if (host, port) not in allowed_hosts:
        raise ActionExecutionError(
            "tool_not_allowed",
            "目标主机未在白名单登记（SSRF 面 fail-closed）。",
            details={"reason": "ssrf_host_not_allowed"},
        )
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ActionExecutionError(
            "tool_not_allowed",
            "目标主机解析失败（SSRF 预检 fail-closed）。",
            details={"reason": "ssrf_resolve_failed"},
        ) from None
    for info in infos:
        ip = str(info[4][0])
        if not _is_loopback(ip):
            raise ActionExecutionError(
                "tool_not_allowed",
                "目标主机解析出非回环地址（SSRF 回环反向规则）。",
                details={"reason": "ssrf_non_loopback_ip"},
            )


def _is_loopback(ip: str) -> bool:
    """回环判定（127.0.0.0/8、::1；白名单 v1.3 四连接器全回环）。"""
    try:
        return ipaddress.ip_address(ip.strip("[]")).is_loopback
    except ValueError:
        return False


def expand_path_template(
    spec: dict[str, Any], params: dict[str, Any], binding: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any]]:
    """白名单 path 模板展开：``{x}`` ← params.x（展开后移除）；返回
    ``(不含 query 的 URL, 剩余 params)``——剩余面由调用方按动词分流
    （GET → query string；POST → JSON body）。**目标地址恒来自白名单
    base_url**——params 无法改写（S-AE-06 A3 口径的机制保证）。

    ``binding``（评审 P9）：三元组第三腿——由调用方按 ``binding_for``
    解析结果传入；缺省退回 ``http_bindings[0]``（单 method 连接器等价）。"""
    resolved = binding if binding is not None else spec["http_bindings"][0]
    base = str(spec.get("base_url", "")).rstrip("/")
    path = str(resolved.get("path", ""))
    rest = dict(params)
    for key in list(rest):
        token = "{" + key + "}"
        if token in path:
            value = rest.pop(key)
            if not isinstance(value, (str, int, float, bool)):
                raise ActionExecutionError(
                    "validation_failed",
                    "路径模板参数须为标量。",
                    details={"reason": "path_param_not_scalar", "param": key},
                )
            path = path.replace(token, urllib.parse.quote(str(value), safe=""))
    return base + path, rest


def build_request_url(spec: dict[str, Any], params: dict[str, Any]) -> str:
    """GET 语义全链 URL（模板＋剩余 params → query string；A3 钉锚）。"""
    url, rest = expand_path_template(spec, params)
    if rest:
        url = url + "?" + urllib.parse.urlencode(rest)
    return url


def reject_caller_headers(params: dict[str, Any]) -> None:
    """C-13：params 里出现头名字段 → 422 validation_failed（调用方不得
    自定义任何出站头；不静默透传）。头名识别口径：命中已知头名闭集，
    **或键名含 ``-``**（HTTP 头风格键——业务参数为小写蛇形）。"""
    for key in params:
        if isinstance(key, str) and (key.lower() in _CALLER_HEADER_KEYS or "-" in key):
            raise ActionExecutionError(
                "validation_failed",
                "params 含请求头名字段（出站头白名单禁止调用方自定义头）。",
                details={"reason": "caller_header_forbidden", "header": key},
            )


def build_outbound_headers(*, auth_type: str, token: str | None, idempotency_key: str) -> dict[str, str]:
    """出站头构造（C-13）：固定基线＋逐连接器登记允许头——头集由代码构造，
    非调用方透传；凭据头值只来自凭据句柄/内部签发，绝不取自 params。"""
    headers = dict(_BASELINE_HEADERS)
    headers["Idempotency-Key"] = idempotency_key
    if auth_type == "bearer_token" and token:
        headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "api_key":
        # AE0–AE1 占位凭据（constraints.oauth_flow：Mock 面零真实凭据；
        # 真实凭据句柄解析归 AE3）
        headers["X-Api-Key"] = _API_KEY_PLACEHOLDER
    else:
        # 评审 P7b：登记外的 auth_type → fail-closed 拒绝（不得静默无凭据头外呼）
        raise ActionExecutionError(
            "tool_not_allowed",
            "连接器凭据形态未登记（fail-closed）。",
            details={"reason": "auth_type_not_registered"},
        )
    return headers


def map_upstream_failure(*, status: int | None, body: str, reason: str) -> ActionExecutionError:
    """上游非 2xx／超时／连接失败 → 15 码闭集内 ``tool_not_allowed``＋
    details 标注（Q8 映射口径；**响应体原文零回显**——C-08）。"""
    details: dict[str, Any] = {"reason": reason}
    if status is not None:
        details["http_status"] = status
    return ActionExecutionError(
        "tool_not_allowed",
        "连接器上游调用失败（闭集映射；details 见 reason/http_status）。",
        details=details,
    )


def normalize_output(*, connector_id: str, method: str, payload_json: Any, org_id: str) -> dict[str, Any]:
    """KD-01 归一化（53 号 Q14 终判）：``workbench.ontology`` read 的
    ``{data:{items:[…]}}`` 信封 → ``{ontologies:[{ontology_id,name,org_id}…],
    count}``；``mock.erp`` query_inventory 的 ``{items:[…]}`` → items[0] 展开
    为 ``{sku,quantity,available}``（T4-002/005 冻结断言可判定，KD-01 同构；
    available 取桩侧事实源零派生）；其余 mock.*/workbench.workflow 透传上游
    最小业务结果（成功态信封外壳不回显）。"""
    if connector_id == "workbench.ontology" and method == "read":
        # KD-01 失败腿（评审 P3——U1 x-normalization.rule 逐字）：error 非 null
        # 或 data 缺失 → 归一化失败按上游错误映射，**不产出伪 output**。
        if not isinstance(payload_json, dict) or payload_json.get("error") is not None or not isinstance(
            payload_json.get("data"), dict
        ):
            raise map_upstream_failure(status=None, body="", reason="normalization_failed")
        items = payload_json["data"].get("items") or []
        ontologies = [
            {"ontology_id": item.get("id"), "name": item.get("term"), "org_id": org_id}
            for item in items
            if isinstance(item, dict)
        ]
        return {"ontologies": ontologies, "count": len(ontologies)}
    if connector_id == "mock.erp" and method == "query_inventory":
        items = (payload_json or {}).get("items") or []
        if not items:
            return {}
        row = items[0] if isinstance(items[0], dict) else {}
        return {"sku": row.get("sku"), "quantity": row.get("quantity"), "available": row.get("available")}
    if isinstance(payload_json, dict) and isinstance(payload_json.get("data"), dict):
        return payload_json["data"]  # 最小业务结果（剥信封外壳）
    return payload_json if isinstance(payload_json, dict) else {}


class HttpDispatch:
    """Dispatch Protocol 真身：白名单三元组＋SSRF 预检＋Header 白名单＋
    真 HTTP 外呼（禁跟随重定向；超时上限；响应体零回显）。"""

    def __init__(
        self,
        *,
        whitelist: ConnectorWhitelist,
        token: str | None = None,
        timeout_seconds: float = 5.0,
        whitelist_snapshot: dict[str, Any] | None = None,
    ) -> None:
        self._whitelist = whitelist
        self._token = token
        self._timeout = timeout_seconds
        self._snapshot = whitelist_snapshot  # ssrf_precheck 用（base_url 集）

    def call(self, request: dict[str, Any]) -> dict[str, Any]:
        spec = self._whitelist.check(request["connector_id"], request["method"])
        binding = self._whitelist.binding_for(spec, request["method"])
        params = request.get("params") or {}
        if not isinstance(params, dict):
            raise ActionExecutionError("validation_failed", "params 须为 JSON 对象。")
        reject_caller_headers(params)
        url_base, remaining = expand_path_template(spec, params, binding)
        http_method = binding["http_method"].upper()
        if http_method == "GET":
            url = url_base + ("?" + urllib.parse.urlencode(remaining) if remaining else "")
            body: bytes | None = None
        else:
            url = url_base  # POST 剩余 params 走 JSON body（不进 query string）
            body = json.dumps(remaining, ensure_ascii=False).encode("utf-8")
        snapshot = self._snapshot or load_whitelist()
        ssrf_precheck(url, snapshot)
        headers = build_outbound_headers(
            auth_type=str(spec.get("auth_type", "")),
            token=self._token,
            idempotency_key=str(request["idempotency_key"]),
        )
        req = urllib.request.Request(url, data=body, headers=headers, method=http_method)
        opener = urllib.request.build_opener(_NoRedirect)
        # 评审 P8：请求声明的 timeout_seconds 接线（1..300 契约域），与服务端
        # 构造上限取小——声明字段不再是被接受后忽略的死字段。
        effective_timeout = min(self._timeout, float(request.get("timeout_seconds") or self._timeout))
        try:
            with opener.open(req, timeout=effective_timeout) as response:
                status = response.status
                data = response.read(5_000_001)  # 评审 P7a：响应体 5MB 上限（防内存耗尽）
        except urllib.error.HTTPError as error:
            error.read()  # 消费后丢弃（零回显）
            raise map_upstream_failure(status=error.code, body="", reason="connector_upstream_error") from None
        except urllib.error.URLError as error:
            reason = "connector_timeout" if isinstance(error.reason, TimeoutError) else "connector_connect_failed"
            raise map_upstream_failure(status=None, body="", reason=reason) from None
        except (TimeoutError, socket.timeout):
            raise map_upstream_failure(status=None, body="", reason="connector_timeout") from None
        if status < 200 or status >= 300:
            raise map_upstream_failure(status=status, body="", reason="connector_upstream_error")
        # 评审 P6：2xx 非 JSON／非 UTF-8 → 闭集映射（不裸异常 500、锁行诚实翻 failed）
        if len(data) > 5_000_000:
            raise map_upstream_failure(status=status, body="", reason="connector_upstream_error")
        try:
            payload = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise map_upstream_failure(status=status, body="", reason="connector_upstream_error") from None
        return normalize_output(
            connector_id=request["connector_id"],
            method=request["method"],
            payload_json=payload,
            org_id=str(request.get("org_id", "")),
        )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁跟随重定向（constraints.ssrf_precheck：redirect/30x 即失败面）。"""

    def redirect_request(self, req: Any, fp: Any, code: Any, msg: Any, headers: Any, newurl: Any) -> None:
        return None  # 返回 None＝不跟随（urllib 抛 HTTPError 携带 3xx 状态）
