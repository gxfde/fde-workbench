"""AE1-WP3 Mock 桩（Q9 实测定稿——AE1 侧夹具，53 号 §3 WP3）。

仓库内此前零 Mock 实现（AE0 侦察 Q1：grep 零命中）；本件从零落两桩＋
workbench 服务面，全部绑回环固定端口（与白名单 v1.3 base_url 一致）：

- **mock.erp**（``127.0.0.1:5001``，GET ``/mock-erp/inventory``）：**纯读桩**
  （白名单 allowed_side_effects：Mock 侧不写任何持久状态）——按 ``sku``
  返回确定性库存行，带请求计数（S-AE-06 A1/A3「零连接」断言的锚）；
- **mock.email**（``127.0.0.1:5002``，POST ``/mock-email/send``）：**可计数
  副作用桩**（白名单唯一外部写副作用锚点）——收件箱内存列表逐条 append，
  响应带 ``message_id``/``delivered_count``/``mailbox_count``；
- **workbench**（``127.0.0.1:8010``）：``create_app`` 真身（KD-01/workflow
  连接器的内部 API 面；JWT bearer 鉴权沿生产路径）。

端口/路径实测口径（Q9 回填白名单 notes 的事实底座）：三服务在本机回环
绑定成功＋连接器适配层真 HTTP 往返（非 in-process stub）＝「localhost+
固定端口可实测」的证据；公网形态归 AE3。

幂等语义归属：Mock 桩**不**自带幂等（同键去重由 AE1 执行器 L2 复放通道
保证——白名单 mock.email ``idempotency_assertion``「同键 3 次响应一致＋
收件箱新增 1 条」即执行器层语义的桩侧观测面）。
"""
from __future__ import annotations

import threading
from typing import Any

from flask import Flask, jsonify, request
from werkzeug.serving import make_server


class PortOccupiedError(RuntimeError):
    """桩栈目标端口被外部服务占用（fail-fast，钉侧转 skip）。"""


class MockStack:
    """mock.erp + mock.email 桩栈（线程化 make_server；计数器/收件箱可检视可重置）。"""

    def __init__(self) -> None:
        self.erp_requests = 0
        self.email_requests = 0
        self.inbox: list[dict[str, Any]] = []
        self._servers: list[Any] = []
        self._threads: list[threading.Thread] = []

    # ---- mock.erp（纯读桩） ---------------------------------------------------

    def _erp_app(self) -> Flask:
        app = Flask("mock-erp")
        stack = self

        @app.get("/mock-erp/inventory")
        def inventory():  # type: ignore[untyped-decorator]
            stack.erp_requests += 1
            sku = request.args.get("sku")
            warehouse = request.args.get("warehouse_id", "wh-default")
            # 确定性纯读：sku 在册即 42 件（零持久状态，每次同参同响应）
            items = [{"sku": sku, "quantity": 42, "warehouse": warehouse}] if sku else []
            return jsonify({"items": items, "count": len(items)})

        return app

    # ---- mock.email（可计数副作用桩） ------------------------------------------

    def _email_app(self) -> Flask:
        app = Flask("mock-email")
        stack = self

        @app.post("/mock-email/send")
        def send():  # type: ignore[untyped-decorator]
            stack.email_requests += 1
            payload = request.get_json(silent=True) or {}
            message_id = f"msg-{stack.email_requests:04d}"
            stack.inbox.append(
                {
                    "message_id": message_id,
                    "to": payload.get("to"),
                    "subject": payload.get("subject"),
                    "body": payload.get("body"),
                }
            )
            return jsonify(
                {"message_id": message_id, "delivered_count": 1, "mailbox_count": len(stack.inbox)}
            )

        @app.get("/mock-email/inbox")
        def inbox():  # type: ignore[untyped-decorator]
            return jsonify({"items": list(stack.inbox), "count": len(stack.inbox)})

        return app

    # ---- 生命周期 -------------------------------------------------------------

    def start(self) -> None:
        self._start_app(self._erp_app(), 5001)
        self._start_app(self._email_app(), 5002)

    def _start_app(self, app: Flask, port: int) -> None:
        server = make_server("127.0.0.1", port, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._servers.append(server)
        self._threads.append(thread)

    def stop(self) -> None:
        for server in self._servers:
            server.shutdown()
        for thread in self._threads:
            thread.join(timeout=5)
        self._servers.clear()
        self._threads.clear()

    def reset(self) -> None:
        """每测试重置计数与收件箱（桩侧零跨测试残留）。"""
        self.erp_requests = 0
        self.email_requests = 0
        self.inbox.clear()


class WorkbenchService:
    """workbench 真身服务面（create_app → 回环端口；KD-01/workflow 内部 API 面）。

    **端口占用回退**：本机开发环境 8010 可能被既有 dev server／wslrelay 占用
    （Windows bind 共存语义下请求会打到旧实例＝JWT 401 之类的静默错位）——
    构造时显式探测，占用即回退 **ephemeral 端口**（``port=0``），实际端口读
    ``server_address[1]``；钉侧把白名单快照 base_url 的 ``:8010`` 注入为实际
    端口（测试装置级快照构造，非运行时篡改——生产门仍用冻结快照原文）。"""

    def __init__(self, settings: Any, port: int = 8010) -> None:
        import socket as _socket

        from fde_api.app import create_app

        probe = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        try:
            occupied = probe.connect_ex(("127.0.0.1", port)) == 0
        finally:
            probe.close()
        if occupied and port != 0:
            port = 0  # 回退 ephemeral（诚实可观测：钉经 actual_port 断言真 HTTP）
        self._server = make_server("127.0.0.1", port, create_app(settings), threaded=True)
        self.port = int(self._server.server_address[1])
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=5)
