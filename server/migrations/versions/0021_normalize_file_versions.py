"""normalize user file versions after preview artifacts are separated

Revision ID: 0021_normalize_file_versions
Revises: 0020_preview_version_namespace
"""

from alembic import op


revision = "0021_normalize_file_versions"
down_revision = "0020_preview_version_namespace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use a temporary namespace so the per-file unique constraint cannot
    # collide while legacy v1/v3/v6 sequences are compacted to v1/v2/v3.
    op.execute(
        "UPDATE project_file_versions AS target "
        "JOIN ("
        "  SELECT id, ROW_NUMBER() OVER ("
        "    PARTITION BY file_id ORDER BY version_number, id"
        "  ) AS normalized_number "
        "  FROM project_file_versions WHERE source <> 'preview'"
        ") AS ranked ON ranked.id = target.id "
        "SET target.version_number = ranked.normalized_number + 500000000"
    )
    op.execute(
        "UPDATE project_file_versions "
        "SET version_number = version_number - 500000000 "
        "WHERE source <> 'preview' AND version_number >= 500000000"
    )


def downgrade() -> None:
    # The legacy gaps cannot be reconstructed without reintroducing preview
    # artifacts into the user-visible sequence.
    pass
