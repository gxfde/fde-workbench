"""回执 DSL 一期（借鉴登记 B#7；agent-autoloop 回执 DSL 的抽象方法论）。

设计原则（我方独立重写，按 AGENTS.md 红线第 8 条只取抽象、不复制上游正文与
结构化表达）：

- **字段白名单 + 未知字段拒绝**：回执 DSL 是**外部可写**的结构，必须按白名单
  逐字段校验；未知字段一律拒绝（不静默丢弃、不透传）——否则外部多写一个键
  就能绕过闸门。
- **容量上限**：整份 DSL 的规范化序列化不得超上限（对齐既有审批材料 64KB
  语境）——回执会进审批行/事件载荷，超限即拒绝而非截断。
- **两种人工介入动作**：
  - ``ask``：请求人工拍板。落既有 ``automation_approvals``（密码确认闸现成）。
  - ``later``：请求延后复查。落**最小到期挂点**——只表达「何时复查」的时点
    结构，**不做统一到期表**（那是借鉴登记 B#13 的 ``deadlines()`` 纯函数，
    本条不抢其活）。
- **失败走 B#2 降级路径**：DSL 不可解析时业务动作可能已执行，不能重做——
  落独立终态 ``succeeded_but_receipt_invalid``（拒绝同键重跑）。

命名说明：既有 ``AgentResult.receipt_state`` 是**产物清单扫描**语义（manifest
可解析与否），与本模块的**人工介入动作**语义正交，两套并存不互相覆盖。
"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.control.access import authorize_ai_capability, contains_sensitive_argument
from fde_api.control.models import AutomationApproval
from fde_api.extensions import db
from fde_api.jobs.outbox import utcnow
from fde_api.projects.permissions import project_access
from fde_api.workbench.models import OperationEvent, Project

# 容量上限：与既有审批材料上限同尺（workflows/executor.py 的
# _APPROVAL_PAYLOAD_LIMIT_BYTES = 64_000）。
RECEIPT_DSL_MAX_BYTES = 64_000

# later 挂点的复查时点上限（防止「永不复查」伪装成延后）。
LATER_MAX_DELAY_MINUTES = 60 * 24 * 30

# 审批有效期默认与上限（对齐 workflow human_approval 的 15 分钟默认）。
_ASK_DEFAULT_EXPIRES_MINUTES = 15
_ASK_MAX_EXPIRES_MINUTES = 60 * 24


# 合法动作 kind 集合（单一真源；判别联合与错误提示共用）。
RECEIPT_ACTION_KINDS = frozenset({"ask", "later"})


class ReceiptDslError(Exception):
    """DSL 解析/校验失败——调用方须走 B#2 降级路径，不得重做业务动作。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class _StrictModel(BaseModel):
    """未知字段一律拒绝（extra="forbid"）——外部可写结构的基类纪律。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AskAction(_StrictModel):
    """请求人工拍板。落既有 automation_approvals（密码确认闸现成）。"""

    kind: Literal["ask"] = "ask"
    capability: str = Field(min_length=1, max_length=100)
    reason: str = Field(default="", max_length=500)
    expires_minutes: int = Field(default=_ASK_DEFAULT_EXPIRES_MINUTES, ge=1, le=_ASK_MAX_EXPIRES_MINUTES)


class LaterAction(_StrictModel):
    """请求延后复查——**最小到期挂点**：只表达时点，不做统一到期表（B#13）。"""

    kind: Literal["later"] = "later"
    delay_minutes: int = Field(ge=1, le=LATER_MAX_DELAY_MINUTES)
    reason: str = Field(default="", max_length=500)


class ReceiptDsl(_StrictModel):
    """回执 DSL 顶层：一次回执 = 一个动作。

    ``action`` 用 **discriminated union**（按 ``kind`` 判别）而非普通联合——
    普通联合在 Pydantic 里会逐分支尝试并把**所有分支的错误**汇总（含无关分支
    的字段名），错误信息冗长且误导。判别联合只报实际命中分支的错误。
    """

    action: Annotated[AskAction | LaterAction, Field(discriminator="kind")]


# ---------------------------------------------------------------------------
# 解析与规范化
# ---------------------------------------------------------------------------


def as_ask(action: AskAction | LaterAction) -> AskAction:
    """动作类型守卫：非 ask 即拒（DSL 顶层已校验，这里是纵深防御）。"""
    if not isinstance(action, AskAction):
        raise ReceiptDslError("invalid_receipt", "该回执不是 ask 动作。")
    return action


def as_later(action: AskAction | LaterAction) -> LaterAction:
    """动作类型守卫：非 later 即拒（DSL 顶层已校验，这里是纵深防御）。"""
    if not isinstance(action, LaterAction):
        raise ReceiptDslError("invalid_receipt", "该回执不是 later 动作。")
    return action


def canonical_receipt_dsl(payload: Mapping[str, Any]) -> str:
    """规范化序列化（排序键、无多余空白、禁 NaN）——用于指纹与容量测量。"""
    return json.dumps(
        dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def parse_receipt_dsl(payload: Any) -> ReceiptDsl:
    """解析回执 DSL。

    - 非对象 / 非法 JSON 形状 → ``ReceiptDslError``。
    - **未知字段拒绝**：Pydantic ``extra="forbid"`` 命中即报错，指出字段名。
    - **容量上限**：规范化后超 64KB 即拒绝（不截断）。
    """
    if not isinstance(payload, Mapping):
        raise ReceiptDslError("invalid_receipt", "回执 DSL 必须是 JSON 对象。")
    try:
        canonical = canonical_receipt_dsl(payload)
    except (TypeError, ValueError) as exc:
        raise ReceiptDslError("invalid_receipt", f"回执 DSL 不是可规范化的 JSON：{exc}") from exc
    if len(canonical.encode("utf-8")) > RECEIPT_DSL_MAX_BYTES:
        raise ReceiptDslError(
            "receipt_too_large",
            f"回执 DSL 超过 {RECEIPT_DSL_MAX_BYTES} 字节上限。",
        )
    try:
        return ReceiptDsl.model_validate(dict(payload))
    except ValidationError as exc:
        # 报全部出错路径（嵌套用点连接，如 action.delay_minutes）——只报顶层
        # 会让「哪个字段错了」不可定位。
        fields = sorted(
            {
                ".".join(str(part) for part in err.get("loc", ()))
                for err in exc.errors()
                if err.get("loc")
            }
        )
        # 判别联合的 tag 不匹配时 Pydantic 只给 loc=("action",) 且 ctx.tag 是
        # **出错值**——合法值集合从模型自身取（避免把错值当合法值报出去）。
        if any(err.get("type") == "union_tag_invalid" for err in exc.errors()):
            allowed = "/".join(sorted(RECEIPT_ACTION_KINDS))
            detail = f"action.kind（动作 kind 仅可为 {allowed}）"
        else:
            detail = "、".join(fields) if fields else "结构不合法"
        raise ReceiptDslError("invalid_receipt", f"回执 DSL 校验失败：{detail}") from exc


def receipt_dsl_fingerprint(payload: Mapping[str, Any]) -> str:
    """规范化指纹（sha256）——审批行 arguments_sha256 用。"""
    return hashlib.sha256(canonical_receipt_dsl(payload).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# ask：落既有审批行（零新表零新路由）
# ---------------------------------------------------------------------------


def request_ask(
    *,
    project_id: str,
    requested_by: User,
    action: AskAction,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """ask 落 automation_approvals。

    纪律与既有 workflow human_approval 同源（不是复制，是同一仓内一致）：
    - **幂等**：request_key 由「项目 + 能力 + 规范化回执」派生，同一请求重复提交
      复用既有 pending 审批（崩溃恢复不重复建单）。
    - **敏感键拒绝**：审批材料命中敏感键即拒绝入审（与 DSH 审批同闸）。
    - **容量上限**：审批材料同样不得超 64KB。
    - **能力实时校验**：发起人当下须仍具备该 capability。
    - **风险档固定 4**：人工门 = 保守高险，诚实标注。
    """
    ask = as_ask(action)
    arguments: dict[str, Any] = {
        "kind": "agent.receipt.ask",
        "capability": ask.capability,
        "reason": ask.reason,
    }
    if context:
        arguments["context"] = dict(context)
    canonical = canonical_receipt_dsl(arguments)
    if len(canonical.encode("utf-8")) > RECEIPT_DSL_MAX_BYTES:
        raise ReceiptDslError(
            "receipt_too_large",
            f"审批材料超过 {RECEIPT_DSL_MAX_BYTES} 字节上限。",
        )
    if contains_sensitive_argument(arguments):
        raise ReceiptDslError(
            "sensitive_argument_rejected",
            "回执材料包含敏感键，拒绝进入审批。",
        )
    request_key = hashlib.sha256(
        f"{project_id}|{ask.capability}|{canonical}".encode("utf-8")
    ).hexdigest()[:160]
    with db.session() as session, session.begin():
        project = session.get(Project, project_id)
        if project is None:
            raise ReceiptDslError("project_not_found", "项目不存在或已被删除。")
        access = project_access(requested_by, project)
        if not access.can_view:
            raise ReceiptDslError("forbidden", "你没有该项目的操作权限。")
        decision = authorize_ai_capability(
            user=requested_by, capability=ask.capability, project=project
        )
        if not decision.allowed:
            raise ReceiptDslError(
                decision.reason or "permission_revoked",
                "发起人已不具备该回执所需能力，无法发起审批。",
            )
        existing = session.scalar(
            select(AutomationApproval).where(
                AutomationApproval.request_key == request_key,
                AutomationApproval.status == "pending",
            )
        )
        if existing is not None:
            return {"approval_id": existing.id, "created": False, "status": existing.status}
        approval = AutomationApproval(
            run_id=None,
            workflow_node_run_id=None,
            project_id=project.id,
            requested_by_user_id=requested_by.id,
            request_key=request_key,
            capability=ask.capability,
            tool_name="agent.receipt.ask",
            arguments_json=arguments,
            arguments_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            risk_level=4,
            status="pending",
            expires_at=utcnow() + timedelta(minutes=ask.expires_minutes),
            decision_reason="",
        )
        session.add(approval)
        session.flush()
        return {"approval_id": approval.id, "created": True, "status": approval.status}


# ---------------------------------------------------------------------------
# later：最小到期挂点（B#13 统一到期表落地前不越界）
# ---------------------------------------------------------------------------


def request_later(
    *,
    project_id: str,
    requested_by: User,
    action: LaterAction,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """later 落最小到期挂点。

    **边界声明（重要）**：本条只表达「何时复查」的时点结构与到期时刻，**不实现**
    统一到期表、**不实现**主动超时扫描、**不实现**统一 cron/not_before 计算——
    那是借鉴登记 B#13 的 ``deadlines()`` 纯函数职责。本条产出的挂点供 B#13 消费
    （B#13 落地时把本函数返回的 ``due_at`` 纳入其到期表即可，无需改动本条）。

    落点是既有 ``operation_events``（项目维度、只增不改）——零新表零新路由。
    """
    later = as_later(action)
    due_at = utcnow() + timedelta(minutes=later.delay_minutes)
    payload: dict[str, Any] = {
        "kind": "agent.receipt.later",
        "due_at": due_at.isoformat(),
        "delay_minutes": later.delay_minutes,
        "reason": later.reason,
    }
    if context:
        payload["context"] = dict(context)
    canonical = canonical_receipt_dsl(payload)
    if len(canonical.encode("utf-8")) > RECEIPT_DSL_MAX_BYTES:
        raise ReceiptDslError(
            "receipt_too_large",
            f"回执材料超过 {RECEIPT_DSL_MAX_BYTES} 字节上限。",
        )
    if contains_sensitive_argument(payload):
        raise ReceiptDslError(
            "sensitive_argument_rejected",
            "回执材料包含敏感键，拒绝记录。",
        )
    with db.session() as session, session.begin():
        project = session.get(Project, project_id)
        if project is None:
            raise ReceiptDslError("project_not_found", "项目不存在或已被删除。")
        access = project_access(requested_by, project)
        if not access.can_view:
            raise ReceiptDslError("forbidden", "你没有该项目的操作权限。")
        event = OperationEvent(
            actor_user_id=requested_by.id,
            project_id=project.id,
            target_type="agent_receipt",
            target_id=request_key_for_later(project_id, later),
            event_type="agent.receipt.later_requested",
            occurred_at=utcnow(),
            changes={
                "due_at": payload["due_at"],
                "delay_minutes": later.delay_minutes,
                "reason": later.reason,
                "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            },
        )
        session.add(event)
        session.flush()
        return {
            "event_id": event.id,
            "due_at": payload["due_at"],
            "delay_minutes": later.delay_minutes,
        }


def request_key_for_later(project_id: str, action: LaterAction) -> str:
    """later 挂点的目标标识（同一项目同 delay 同 reason 归一）。"""
    raw = f"{project_id}|{action.delay_minutes}|{action.reason}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


