"""move preview artifacts outside the user-visible version sequence

Revision ID: 0020_preview_version_namespace
Revises: 0019_project_creation_sources
"""

from alembic import op


revision = "0020_preview_version_namespace"
down_revision = "0019_project_creation_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preview rows share the immutable file-version table for storage and
    # access control, but their numbers must never consume v2/v3/... shown to
    # users. Existing rows are moved into an internal reserved namespace.
    op.execute(
        "UPDATE project_file_versions "
        "SET version_number = version_number + 1000000000 "
        "WHERE source = 'preview' AND version_number < 1000000000"
    )


def downgrade() -> None:
    # Keeping the reserved internal numbers is safe and avoids collisions with
    # user versions created after this migration.
    pass
