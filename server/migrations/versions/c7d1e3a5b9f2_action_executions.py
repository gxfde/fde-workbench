"""action_executions table (AE1-WP1 single-step action executor)

One row per action execution (U1 contract v1.0.3, 53 号 §3 WP1): request
identity (idempotency key + 10-field semantic fingerprint) + terminal status
(closed set per ExecutionStatus) + params fingerprint (zero plaintext) +
audit/cost/rollback snapshots. Append-only; replay does not insert a new row
(one row per (org_id, idempotency_key) — U1 x-idempotency constraint DDL).
"""
from alembic import op
import sqlalchemy as sa

revision = "c7d1e3a5b9f2"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("requester_id", sa.String(64), nullable=False),
        sa.Column("action_id", sa.String(128), nullable=False),
        sa.Column("action_type", sa.String(64), nullable=True),
        sa.Column("connector_id", sa.String(128), nullable=False),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("params_sha256", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("risk_level", sa.Integer(), nullable=False),
        sa.Column("approval_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=False, server_default=sa.text("''")),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("replayed_from_execution_id", sa.String(36), nullable=True),
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
            "status IN ('succeeded', 'failed', 'cancelled', 'replayed', 'awaiting_approval')",
            name="ck_action_executions_status",
        ),
        sa.CheckConstraint("risk_level >= 0 AND risk_level <= 4", name="ck_action_executions_risk"),
        sa.UniqueConstraint("org_id", "idempotency_key", name="uq_action_executions_org_idem"),
    )
    op.create_index(
        "ix_action_executions_org_status", "action_executions", ["org_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_action_executions_org_status", table_name="action_executions")
    op.drop_table("action_executions")
