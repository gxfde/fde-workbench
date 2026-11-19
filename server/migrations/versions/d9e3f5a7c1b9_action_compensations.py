"""action_compensations table (AE1-WP2 rollback batches)

One row per rollback invocation (U1 contract x-rollback): execution anchor
(UNIQUE — one rollback batch per execution, re-invocation short-circuits to
the existing batch = idempotent rollback, zero repeated compensation side
effects) + four-state honest terminal status (rolled_back / not_supported /
failed / noop) + per-item compensation ledger (zero plaintext: target carries
connector/method + params_sha256 prefix anchor only). Append-only.
"""
from alembic import op
import sqlalchemy as sa

revision = "d9e3f5a7c1b9"
down_revision = "c7d1e3a5b9f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_compensations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "execution_id",
            sa.String(36),
            sa.ForeignKey("action_executions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("requester_id", sa.String(64), nullable=False),
        sa.Column("rollback_key", sa.String(160), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("compensations_json", sa.JSON(), nullable=False),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('rolled_back', 'not_supported', 'failed', 'noop')",
            name="ck_action_compensations_status",
        ),
        sa.UniqueConstraint("execution_id", name="uq_action_compensations_execution"),
    )


def downgrade() -> None:
    op.drop_table("action_compensations")
