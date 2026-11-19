"""action_execution_logs table (AE1-WP4 audit ledger)

One audit row per terminal execution (U1 contract $defs/AuditObject 9 required
fields + $defs/CostObject 3 fields): execution anchor (UNIQUE — replay does not
append a row, one audit line per execution) + zero plaintext (params only as
64-hex sha256; NO JSON free-form column — upstream response body cannot be
echoed into the ledger by construction, C-08) + cost registration
(tool_calls / duration_ms / estimated_usd, T4 task budget <= $0.10 per 51:213).
Append-only.
"""
from alembic import op
import sqlalchemy as sa

revision = "e2b4d6f8a0c2"
down_revision = "d9e3f5a7c1b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_execution_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "execution_id",
            sa.String(36),
            sa.ForeignKey("action_executions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("connector_id", sa.String(128), nullable=False),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("params_sha256", sa.String(64), nullable=False),
        sa.Column("actor_user_id", sa.String(64), nullable=False),
        sa.Column("approval_id", sa.String(128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("estimated_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("duration_ms >= 0", name="ck_action_execution_logs_duration"),
        sa.CheckConstraint("tool_calls >= 0", name="ck_action_execution_logs_tool_calls"),
        sa.CheckConstraint("estimated_usd >= 0", name="ck_action_execution_logs_usd"),
        sa.CheckConstraint("char_length(params_sha256) = 64", name="ck_action_execution_logs_sha_length"),
        sa.UniqueConstraint("execution_id", name="uq_action_execution_logs_execution"),
    )
    op.create_index(
        "ix_action_execution_logs_org_started",
        "action_execution_logs",
        ["org_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_action_execution_logs_org_started", table_name="action_execution_logs")
    op.drop_table("action_execution_logs")
