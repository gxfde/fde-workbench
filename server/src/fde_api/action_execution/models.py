"""action_execution 域模型：``action_executions`` 执行记录（AE1-WP1）＋
``action_compensations`` 回滚批次（AE1-WP2）＋ ``action_execution_logs``
审计日志（AE1-WP4）。

纪律（契约 U1 / 53 号）：
- **零明文**：参数只存 ``params_sha256``，``params`` 明文不落库（U1
  x-audit.zero_plaintext；审计表归 WP4 另落）；
- **幂等唯一约束**：``UNIQUE(org_id, idempotency_key)``（U1
  x-idempotency.constraint.ddl；新表新约束，既有约束零触碰——禁改清单第 6 项）;
- **status 闭集**：契约 ``ExecutionStatus`` 五值（succeeded/failed/cancelled/
  replayed/awaiting_approval）CHECK 机械约束；
- **append-only**：无 PATCH/DELETE 面；复放不落新行（同键一行真身）；
  审计表（WP4）同口径——一行一执行、无 JSON 自由列（C-08 响应体零回显的
  结构保证）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.workbench.models import Base, TimestampMixin, new_uuid

ACTION_EXECUTION_STATUSES = ("succeeded", "failed", "cancelled", "replayed", "awaiting_approval")


class ActionExecution(Base, TimestampMixin):
    __tablename__ = "action_executions"
    __table_args__ = (
        CheckConstraint(
            f"status IN {ACTION_EXECUTION_STATUSES!r}",
            name="ck_action_executions_status",
        ),
        CheckConstraint("risk_level >= 0 AND risk_level <= 4", name="ck_action_executions_risk"),
        UniqueConstraint("org_id", "idempotency_key", name="uq_action_executions_org_idem"),
        Index("ix_action_executions_org_status", "org_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    # 租户面按值存（契约 OrgId string 1..64；复用 orgs 模型的标识体系，禁自造 tenant_id）
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    requester_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    connector_id: Mapped[str] = mapped_column(String(128), nullable=False)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    params_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    risk_level: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    replayed_from_execution_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    audit_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    cost_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    rollback_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    def snapshot(self) -> dict[str, Any]:
        return {
            "execution_id": self.id,
            "idempotency_key": self.idempotency_key,
            "org_id": self.org_id,
            "requester_id": self.requester_id,
            "action_id": self.action_id,
            "action_type": self.action_type,
            "connector_id": self.connector_id,
            "method": self.method,
            "params_sha256": self.params_sha256,
            "dry_run": self.dry_run,
            "risk_level": self.risk_level,
            "approval_id": self.approval_id,
            "status": self.status,
            "output": self.output_json,
            "error_code": self.error_code,
            "replayed_from_execution_id": self.replayed_from_execution_id,
            "audit": self.audit_json,
            "cost": self.cost_json,
            "rollback": self.rollback_json,
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
        }


class ActionCompensation(Base, TimestampMixin):
    """回滚批次登记（AE1-WP2，U1 ``x-rollback``）。

    一次 ``rollback_action`` ＝ 一行批次：``status`` 四态闭集
    （``rolled_back|not_supported|failed|noop``）＋ ``compensations_json`` 逐条
    补偿登记（条目 ``{compensation_id, kind, target, status, detail}``，
    ``status ∈ succeeded|failed|skipped``）＋ ``error_json`` 诚实失败对象。

    幂等（U1 ``x-rollback.idempotency`` / U2 S-AE-03 A3）：``execution_id``
    唯一＝一回滚批次真身——重复回滚短路复用既有批次（补偿副作用计数不增）。
    零明文：``target`` 只携带 ``connector_id/method#params_sha256 前缀`` 锚。
    """

    __tablename__ = "action_compensations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('rolled_back', 'not_supported', 'failed', 'noop')",
            name="ck_action_compensations_status",
        ),
        UniqueConstraint("execution_id", name="uq_action_compensations_execution"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("action_executions.id", ondelete="RESTRICT"), nullable=False
    )
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    requester_id: Mapped[str] = mapped_column(String(64), nullable=False)  # 回滚发起人
    rollback_key: Mapped[str | None] = mapped_column(String(160), nullable=True)  # U1 形参；缺省由 execution_id 派生
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    compensations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def snapshot(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "org_id": self.org_id,
            "requester_id": self.requester_id,
            "status": self.status,
            "compensations": self.compensations_json,
            "error": self.error_json,
            "reason": self.reason,
            "created_at": str(self.created_at),
        }


class ActionExecutionLog(Base, TimestampMixin):
    """审计日志（AE1-WP4，契约 U1 ``$defs/AuditObject`` 9 必填 ＋ ``$defs/CostObject`` 3 字段）。

    - **一行一执行**：``execution_id`` UNIQUE——复放不落新行（同键一行真身，
      与 ``action_executions`` 的复放口径一致）；一次执行恰一条审计行；
    - **append-only**：无 PATCH/DELETE 面；写入只发生在执行终态（succeeded），
      失败路径不落审计行（无真实起止时间即不伪造；失败留痕在
      ``action_executions.error_json``）；
    - **零明文（C-08 结构保证）**：窄列结构，**无任何 JSON 自由列**——params
      只落 ``params_sha256``（64 hex），上游响应体整段不落库（审计面不存在
      可回显的字段）；
    - **成本预算**：``estimated_usd`` ≥ 0 且 T4 单任务累计 ≤ $0.10（51:213）；
    - **租户面**：按值存 ``org_id``（复用 orgs 标识体系，禁自造 tenant_id）。
    """

    __tablename__ = "action_execution_logs"
    __table_args__ = (
        CheckConstraint("duration_ms >= 0", name="ck_action_execution_logs_duration"),
        CheckConstraint("tool_calls >= 0", name="ck_action_execution_logs_tool_calls"),
        CheckConstraint("estimated_usd >= 0", name="ck_action_execution_logs_usd"),
        CheckConstraint("char_length(params_sha256) = 64", name="ck_action_execution_logs_sha_length"),
        UniqueConstraint("execution_id", name="uq_action_execution_logs_execution"),
        Index("ix_action_execution_logs_org_started", "org_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("action_executions.id", ondelete="RESTRICT"), nullable=False
    )
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    connector_id: Mapped[str] = mapped_column(String(128), nullable=False)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    params_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_usd: Mapped[Any] = mapped_column(Numeric(12, 6), nullable=False)

    def snapshot(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "org_id": self.org_id,
            "connector_id": self.connector_id,
            "method": self.method,
            "params_sha256": self.params_sha256,
            "actor_user_id": self.actor_user_id,
            "approval_id": self.approval_id,
            "started_at": str(self.started_at),
            "finished_at": str(self.finished_at),
            "duration_ms": self.duration_ms,
            "cost": {
                "tool_calls": self.tool_calls,
                "duration_ms": self.duration_ms,
                "estimated_usd": float(self.estimated_usd),
            },
            "created_at": str(self.created_at),
        }
