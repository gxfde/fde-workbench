"""action_execution 域模型：``action_executions`` 执行记录（AE1-WP1）＋
``action_compensations`` 回滚批次（AE1-WP2）＋ ``action_execution_logs``
审计日志（AE1-WP4）＋ ``action_task_runs``/``action_task_nodes`` 多步编排
（AE2-WP2）。

纪律（契约 U1 / 53 号 / 54 号）：
- **零明文**：参数只存 ``params_sha256``，``params`` 明文不落库（U1
  x-audit.zero_plaintext；审计表归 WP4 另落）；AE2 编排表同口径——运行行只留
  ``definition_sha256`` 指纹、节点行只留 ``params_sha256``，图定义与节点参数
  明文**不落库**（契约 `_ae2-execution-contract-v1.json` x-audit-and-cost）；
- **幂等唯一约束**：``UNIQUE(org_id, idempotency_key)``（U1
  x-idempotency.constraint.ddl；新表新约束，既有约束零触碰——禁改清单第 6 项）;
- **status 闭集**：契约 ``ExecutionStatus`` 五值（succeeded/failed/cancelled/
  replayed/awaiting_approval）CHECK 机械约束；AE2 运行七态 ＋ 节点八值
  （编排契约 x-status-machine）同口径 CHECK 落库；
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

# AE2 编排状态闭集（编排契约 `_ae2-execution-contract-v1.json` x-status-machine）：
# 运行七态 ＋ 节点八值（与 Workbench `WorkflowNodeRun` 八值同义——语义对齐，
# 实现独立，禁改区零触碰）。
ACTION_TASK_RUN_STATUSES = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "compensating",
    "rolled_back",
    "compensation_failed",
)
ACTION_TASK_NODE_STATUSES = (
    "pending",
    "ready",
    "running",
    "waiting",
    "succeeded",
    "failed",
    "skipped",
    "cancelled",
)
ACTION_TASK_COMPENSATION_STATUSES = ("rolled_back", "not_supported", "failed", "noop")


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


class ActionTaskRun(Base, TimestampMixin):
    """一次多步运行（AE2-WP2，编排契约 ``_ae2-execution-contract-v1.json``）。

    纪律：
    - **零明文**：只留 ``definition_sha256`` 指纹（图定义与节点参数明文**不落库**
      ——编排契约 x-audit-and-cost）；节点参数指纹另落节点行 ``params_sha256``；
    - **运行级幂等**：``UNIQUE(org_id, idempotency_key)``（同键一行真身；跨租户同键
      互不影响——org_id 参与约束）；
    - **status 闭集**：七值 CHECK 落库（queued|running|succeeded|failed|
      compensating|rolled_back|compensation_failed）；
    - **append-only**：无 PATCH/DELETE 面；复放不落新行。
    """

    __tablename__ = "action_task_runs"
    __table_args__ = (
        CheckConstraint(
            f"status IN {ACTION_TASK_RUN_STATUSES!r}",
            name="ck_action_task_runs_status",
        ),
        CheckConstraint("node_count >= 1 AND node_count <= 32", name="ck_action_task_runs_node_count"),
        UniqueConstraint("org_id", "idempotency_key", name="uq_action_task_runs_org_idem"),
        Index("ix_action_task_runs_org_status", "org_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    # 租户面按值存（复用 orgs 标识体系，禁自造 tenant_id）
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    requester_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # 图定义指纹（canonical JSON → sha256 hex，64 位小写）；定义明文不落库
    definition_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    error_code: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    audit_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    cost_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    rollback_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    def snapshot(self) -> dict[str, Any]:
        return {
            "execution_id": self.id,
            "idempotency_key": self.idempotency_key,
            "org_id": self.org_id,
            "requester_id": self.requester_id,
            "definition_sha256": self.definition_sha256,
            "node_count": self.node_count,
            "status": self.status,
            "error_code": self.error_code,
            "error": self.error_json,
            "audit": self.audit_json,
            "cost": self.cost_json,
            "rollback": self.rollback_json,
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
        }


class ActionTaskNode(Base, TimestampMixin):
    """多步运行内的节点行（AE2-WP2）。

    纪律：
    - **依赖快照冗余**：``depends_on_json`` 是定义侧快照（定义后续演进不影响历史
      run 的可追溯性——同 ``WorkflowNodeRun.depends_on`` 口径，语义对齐、实现独立）；
    - **节点唯一**：``UNIQUE(run_id, node_key)``；
    - **status 闭集**：八值 CHECK 落库（pending|ready|running|waiting|succeeded|
      failed|skipped|cancelled）；
    - **零明文**：只留 ``params_sha256``；节点产物（output）留在 AE1 执行行
      （``action_execution_id`` 指向），编排表不复制业务产物。
    """

    __tablename__ = "action_task_nodes"
    __table_args__ = (
        CheckConstraint(
            f"status IN {ACTION_TASK_NODE_STATUSES!r}",
            name="ck_action_task_nodes_status",
        ),
        CheckConstraint(
            "compensation_status IS NULL OR compensation_status IN "
            f"{ACTION_TASK_COMPENSATION_STATUSES!r}",
            name="ck_action_task_nodes_compensation_status",
        ),
        CheckConstraint("attempt >= 0", name="ck_action_task_nodes_attempt"),
        UniqueConstraint("run_id", "node_key", name="uq_action_task_nodes_run_node"),
        Index("ix_action_task_nodes_run_status", "run_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("action_task_runs.id", ondelete="RESTRICT"), nullable=False
    )
    node_key: Mapped[str] = mapped_column(String(60), nullable=False)
    depends_on_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 节点级幂等键（确定性派生：sha256(run_key｜node_key｜canonical(action)) 前 32 位）
    node_idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    params_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # 指向 AE1 单步执行行（节点＝一次 AE1 单步执行）
    action_execution_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error_code: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    compensation_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    def snapshot(self) -> dict[str, Any]:
        return {
            "node_key": self.node_key,
            "status": self.status,
            "attempt": self.attempt,
            "action_execution_id": self.action_execution_id,
            "error_code": self.error_code,
            "error": self.error_json,
            "compensation_status": self.compensation_status,
        }
