"""data_profiles connector source_kind + version/snapshot anchors (AF2-WP1 batch 2)

source_kind two-state ("file" | "connector") per decision D5: connector
profiles come from ontology-service introspection (api-spec 1.3.8-af2) with
masking done inside the runtime connector sandbox; workbench only persists
statistics + masked samples + version/snapshot anchors. Existing file rows
default to "file"; anchor columns stay NULL for file profiles. Append-only
artifact discipline unchanged (no PATCH/DELETE route; relation candidates
never promoted — 03 §77).
"""
from alembic import op
import sqlalchemy as sa

revision = "d5e6f7a8b9c0"
down_revision = "c3d8e7a2f1b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "data_profiles",
        sa.Column("source_kind", sa.String(16), nullable=False, server_default="file"),
    )
    op.add_column("data_profiles", sa.Column("ontology_id", sa.String(64), nullable=True))
    op.add_column(
        "data_profiles", sa.Column("ontology_version_id", sa.String(64), nullable=True)
    )
    op.add_column("data_profiles", sa.Column("snapshot_sha256", sa.String(80), nullable=True))
    op.add_column("data_profiles", sa.Column("data_source_key", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("data_profiles", "data_source_key")
    op.drop_column("data_profiles", "snapshot_sha256")
    op.drop_column("data_profiles", "ontology_version_id")
    op.drop_column("data_profiles", "ontology_id")
    op.drop_column("data_profiles", "source_kind")
