"""action_execution 域模型：``action_executions`` 执行记录（AE1-WP1）。

纪律（契约 U1 / 53 号）：
- **零明文**：参数只存 ``params_sha256``，``params`` 明文不落库（U1
  x-audit.zero_plaintext；审计表归 WP4 另落）；
- **幂等唯一约束**：``UNIQUE(org_id, idempotency_key)``（U1
  x-idempotency.constraint.ddl；新表新约束，既有约束零触碰——禁改清单第 6 项）;
- **status 闭集**：契约 ``ExecutionStatus`` 五值（succeeded/failed/cancelled/
  replayed/awaiting_approval）CHECK 机械约束；
- **append-only**：无 PATCH/DELETE 面；复放不落新行（同键一行真身）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, Index, Integer, String, UniqueConstraint, text
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
