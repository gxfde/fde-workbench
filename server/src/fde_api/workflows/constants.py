"""工作流执行器的共享常量与异常（架构评估 P1-2：executor.py 拆分第一刀）。

从 executor.py 原样抽出，让「调度分派 / 结算 / 恢复 / dag 纯函数」四个子模块
共享同一份真值——拆完不允许出现第二份常量或第二份异常类（两个模块各 raise
一个同名异常会让 `except` 漏捕，是拆分类重构最常见的事故）。

本模块是拆分后依赖图的**根**：不依赖任何包内模块，也不 import 任何外部重物。
"""
from __future__ import annotations

from typing import Any


class WorkflowRunError(Exception):
    """运行生命周期错误（HTTP 面与内部调用共用；shape 同 WorkflowDefinitionError）。"""

    def __init__(
        self, code: str, message: str, status: int, detail: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail or {}


class _NodeFailure(Exception):
    """节点分派失败（内部信号：由 _settle_node_failure 落表，绝不外抛出 handler）。"""

    def __init__(self, code: str, message: str, *, retryable: bool):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class _MissingPlaceholder(Exception):
    def __init__(self, name: str):
        super().__init__(name)
        self.name = name


WORKFLOW_JOB_TYPE = "workflow.run"
TERMINAL_RUN_STATUSES = ("succeeded", "failed", "cancelled")
TERMINAL_NODE_STATUSES = ("succeeded", "failed", "skipped", "cancelled")
# B#1 跳数熔断（agent-autoloop decide 语义）：重投代际链长上限——resume_run
# 每次拍板重投 hops+1（继承不清零），入口超限 honest failed(hops_exceeded)。
MAX_RUN_HOPS = 8
# 四类节点全部落地（T-W3：call/skill；T-W4：agent/human_approval）；守卫防未来类型漏实现
SUPPORTED_NODE_TYPES = ("call", "skill", "agent", "human_approval")
# CR-022：节点被取消后在途派发返回的稳定标记（node.error / output_json 键）
CANCELLED_AFTER_DISPATCH_MARKER = "cancelled_after_dispatch"
# 审批材料体上限（与 control.service.create_dsh_approval_request 同口径）
_APPROVAL_PAYLOAD_LIMIT_BYTES = 64_000
# 重试退避（指数，封顶）；测试里 monkeypatch 基数即可归零——
# 注意：这两个常量由 executor.py 门面**动态**读取（settlement 内函数内惰性导入
# 门面），所以 monkeypatch executor._RETRY_BACKOFF_BASE_SECONDS 仍然生效。
_RETRY_BACKOFF_BASE_SECONDS = 1.0
_RETRY_BACKOFF_CAP_SECONDS = 20.0
