"""action_task_runs + action_task_nodes tables (AE2-WP2 multi-step orchestration)

One row per multi-step run (orchestration contract
`_ae2-execution-contract-v1.json` v1.0.0, 54 号 §3 WP2): request identity
(run-level idempotency key + org/requester) + definition digest (zero
plaintext — the graph definition and node params never land in the DB) +
terminal status (closed set per x-status-machine.run) + audit/cost/rollback
snapshots; one node row per graph node (node_key + depends_on snapshot +
node status closed set + derived node idempotency key + params digest +
pointer to the AE1 single-step execution row).

Append-only (no PATCH/DELETE surface; replay does not insert a new row —
one row per (org_id, idempotency_key) per x-idempotency). Existing tables and
constraints are untouched (禁改清单第 6/10 项).
"""
from alembic import op
import sqlalchemy as sa

revision = "b3e8c7d1a9f4"
down_revision = "e2b4d6f8a0c2"
branch_labels = None
depends_on = None

RUN_STATUSES = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "compensating",
    "rolled_back",
    "compensation_failed",
)
NODE_STATUSES = (
    "pending",
    "ready",
    "running",
    "waiting",
    "succeeded",
    "failed",
    "skipped",
    "cancelled",
)
COMPENSATION_STATUSES = ("rolled_back", "not_supported", "failed", "noop")


def upgrade() -> None:
    op.create_table(
        "action_task_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("requester_id", sa.String(64), nullable=False),
        sa.Column("definition_sha256", sa.String(64), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(24), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("error_code", sa.String(80), nullable=False, server_default=sa.text("''")),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("audit_json", sa.JSON(), nullable=False),
        sa.Column("cost_json", sa.JSON(), nullable=False),
        sa.Column("rollback_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', "
            "'compensating', 'rolled_back', 'compensation_failed')",
            name="ck_action_task_runs_status",
        ),
        sa.CheckConstraint("node_count >= 1 AND node_count <= 32", name="ck_action_task_runs_node_count"),
        sa.UniqueConstraint("org_id", "idempotency_key", name="uq_action_task_runs_org_idem"),
    )
    op.create_index(
        "ix_action_task_runs_org_status", "action_task_runs", ["org_id", "status"]
    )
    op.create_table(
        "action_task_nodes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("node_key", sa.String(60), nullable=False),
        sa.Column("depends_on_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("node_idempotency_key", sa.String(160), nullable=False),
        sa.Column("params_sha256", sa.String(64), nullable=False),
        sa.Column("action_execution_id", sa.String(36), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=False, server_default=sa.text("''")),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("compensation_status", sa.String(20), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["action_task_runs.id"], name="fk_action_task_nodes_run", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'running', 'waiting', 'succeeded', "
            "'failed', 'skipped', 'cancelled')",
            name="ck_action_task_nodes_status",
        ),
        sa.CheckConstraint(
            "compensation_status IS NULL OR compensation_status IN "
            "('rolled_back', 'not_supported', 'failed', 'noop')",
            name="ck_action_task_nodes_compensation_status",
        ),
        sa.CheckConstraint("attempt >= 0", name="ck_action_task_nodes_attempt"),
        sa.UniqueConstraint("run_id", "node_key", name="uq_action_task_nodes_run_node"),
    )
    op.create_index(
        "ix_action_task_nodes_run_status", "action_task_nodes", ["run_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_action_task_nodes_run_status", table_name="action_task_nodes")
    op.drop_table("action_task_nodes")
    op.drop_index("ix_action_task_runs_org_status", table_name="action_task_runs")
    op.drop_table("action_task_runs")
