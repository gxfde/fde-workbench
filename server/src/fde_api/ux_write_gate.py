"""写入暂停单点（G4 发布回退演练）。

回退到无保护版本之前，必须先暂停三条「确认快照」写入——否则回退窗口内的写入
不受条件保护，却会以正常成功事件落库。这三条是：

- `POST /projects/<id>/gates/<gate_key>/evidence`（门禁证据提交，含首次）
- `POST /projects/<id>/gates/<gate_key>/decision`（门禁人工裁定）
- `POST /handover-packages/<id>/deliver`（交付登记）

桌面端直连、仓内脚本、网页代理都打同一个 API，所以**服务端一处开关即覆盖全部
入口**；反向代理/网关只能挡网页那条路径，`compose.yaml` 把 8010 暴露在回环上时
桌面与脚本可绕过，因此不作为暂停手段。

命中暂停的请求在授权之后、任何写入之前被拒：不落业务成功事件，也不因暂停而
泄漏资源存在性（未授权仍是原来的 403/404）。
"""

from __future__ import annotations

from flask import current_app, has_app_context

PAUSED_CODE = "write_preconditions_paused"
PAUSED_MESSAGE = "写入已暂停（发布回退窗口）。本次未提交，请稍后重试。"


def writes_paused() -> bool:
    """当前实例是否处于写入暂停态。无应用上下文（脚本直调服务层）视为未暂停。"""
    if not has_app_context():
        return False
    return bool(current_app.config["SETTINGS"].ux_write_paused)
