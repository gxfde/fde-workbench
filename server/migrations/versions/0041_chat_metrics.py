"""Provider-reported token usage for completed AI chat turns."""
from alembic import op
import sqlalchemy as sa

revision = "0041_chat_metrics"
down_revision = "0040_lcsc_skill_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ai_chat_turns", sa.Column("metrics_json", sa.JSON(), nullable=True))
    op.execute("UPDATE ai_chat_turns SET metrics_json = JSON_OBJECT() WHERE metrics_json IS NULL")
    op.alter_column("ai_chat_turns", "metrics_json", existing_type=sa.JSON(), nullable=False)


def downgrade():
    op.drop_column("ai_chat_turns", "metrics_json")
