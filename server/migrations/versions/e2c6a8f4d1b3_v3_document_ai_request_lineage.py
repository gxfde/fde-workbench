"""document generation job AI request lineage (V3 T-D1, WB-DEF-6)

Adds ``document_generation_jobs.ai_request_id`` — the request_id handed to the
AI content call so the job row joins ``ai_call_audits`` directly. The same id
is frozen into ``project_document_versions.content_snapshot_json`` by the
generator, closing the version → audit lineage chain. Nullable: jobs that never
reach the AI path (non-PoV/SOW documents, saved-solution exports) stay NULL.
"""
from alembic import op
import sqlalchemy as sa

revision = "e2c6a8f4d1b3"
down_revision = "c7e1a9f3b5d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_generation_jobs",
        sa.Column("ai_request_id", sa.String(120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_generation_jobs", "ai_request_id")
