"""action_execution 错误面：15 码闭集 + 域错误类型（契约 U1 x-error-codes）。

闭集纪律（Q8 拍板口径）：AE1 不自造新码、不扩闭集（扩走契约 v2 决策单）；
闭集外运行时情形映射到闭集内码、原始码在 ``details`` 标注保证可观测
（``service._UNWIRED_DISPATCH`` 的 ``connector_adapter_not_wired`` 即此落法）。
"""
from __future__ import annotations

# code → HTTP 状态（U1 x-error-codes.codes 逐码对齐；两枚「诚实失败态」码
# rollback_not_supported/compensation_failed 以 200 + error 对象返回）。
ERROR_STATUS: dict[str, int] = {
    "validation_failed": 422,
    "approval_required": 403,
    "approval_not_found": 404,
    "approval_not_approved": 409,
    "approval_expired": 409,
    "approval_integrity_failed": 409,
    "self_review_forbidden": 409,
    "permission_revoked": 403,
    "tool_not_allowed": 403,
    "not_found": 404,
    "idempotency_mismatch": 409,
    "idempotency_in_flight": 409,
    "rollback_not_supported": 200,
    "compensation_failed": 200,
    "sensitive_argument_forbidden": 422,
}


class ActionExecutionError(Exception):
    """域错误（同 ``ControlServiceError`` 形；缺省 status 取闭集注册表）。"""

    def __init__(self, code: str, message: str, status: int | None = None, details: dict | None = None):
        if code not in ERROR_STATUS:
            # 闭集外码在构造层即拒——错误面本身也不得成为扩码通道。
            raise ValueError(f"AE 错误码闭集外：{code}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status if status is not None else ERROR_STATUS[code]
        self.details = details
