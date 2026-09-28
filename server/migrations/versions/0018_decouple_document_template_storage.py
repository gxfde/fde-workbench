"""decouple document template assets from project files

Revision ID: 0018_template_asset_storage
Revises: 0017_async_research_exports
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_template_asset_storage"
down_revision = "0017_async_research_exports"
branch_labels = None
depends_on = None


SYSTEM_PROJECT_CODE = "SYS-DOC-TEMPLATES"


def upgrade() -> None:
    op.add_column(
        "document_template_versions",
        sa.Column("docx_original_filename", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "document_template_versions",
        sa.Column("docx_mime_type", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "document_template_versions",
        sa.Column("docx_bucket", sa.String(length=63), nullable=True),
    )
    op.add_column(
        "document_template_versions",
        sa.Column("docx_storage_key", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "document_template_versions",
        sa.Column("docx_size_bytes", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "document_template_versions",
        sa.Column("docx_etag", sa.String(length=128), nullable=True),
    )

    connection = op.get_bind()
    legacy_rows = connection.execute(
        sa.text(
            """
            SELECT dtv.id,
                   pfv.original_filename,
                   pfv.mime_type,
                   pfv.bucket,
                   pfv.storage_key,
                   pfv.size_bytes,
                   pfv.etag
              FROM document_template_versions AS dtv
              JOIN project_file_versions AS pfv
                ON pfv.id = dtv.docx_file_version_id
            """
        )
    ).mappings()
    for row in legacy_rows:
        connection.execute(
            sa.text(
                """
                UPDATE document_template_versions
                   SET docx_original_filename = :original_filename,
                       docx_mime_type = :mime_type,
                       docx_bucket = :bucket,
                       docx_storage_key = :storage_key,
                       docx_size_bytes = :size_bytes,
                       docx_etag = :etag,
                       docx_file_version_id = NULL
                 WHERE id = :id
                """
            ),
            dict(row),
        )

    system_project = connection.execute(
        sa.text(
            "SELECT id, source_template_version_id FROM projects "
            "WHERE project_code = :code"
        ),
        {"code": SYSTEM_PROJECT_CODE},
    ).mappings().first()
    if system_project is None:
        return

    project_id = system_project["id"]
    source_template_version_id = system_project["source_template_version_id"]
    source_template_id = connection.execute(
        sa.text(
            "SELECT template_id FROM industry_template_versions WHERE id = :id"
        ),
        {"id": source_template_version_id},
    ).scalar()

    connection.execute(
        sa.text(
            "UPDATE project_files SET current_version_id = NULL "
            "WHERE project_id = :project_id"
        ),
        {"project_id": project_id},
    )
    connection.execute(
        sa.text(
            "DELETE FROM project_file_versions WHERE file_id IN "
            "(SELECT id FROM project_files WHERE project_id = :project_id)"
        ),
        {"project_id": project_id},
    )
    connection.execute(
        sa.text("DELETE FROM project_files WHERE project_id = :project_id"),
        {"project_id": project_id},
    )
    connection.execute(
        sa.text("DELETE FROM projects WHERE id = :project_id"),
        {"project_id": project_id},
    )
    connection.execute(
        sa.text("DELETE FROM industry_template_versions WHERE id = :id"),
        {"id": source_template_version_id},
    )
    if source_template_id is not None:
        connection.execute(
            sa.text(
                "DELETE FROM industry_templates WHERE id = :id "
                "AND NOT EXISTS (SELECT 1 FROM industry_template_versions "
                "WHERE template_id = :id)"
            ),
            {"id": source_template_id},
        )


def downgrade() -> None:
    # The removed synthetic project is intentionally not recreated. Rolling
    # back only removes the direct metadata columns; bundled templates continue
    # to provide the source DOCX fallback.
    op.drop_column("document_template_versions", "docx_etag")
    op.drop_column("document_template_versions", "docx_size_bytes")
    op.drop_column("document_template_versions", "docx_storage_key")
    op.drop_column("document_template_versions", "docx_bucket")
    op.drop_column("document_template_versions", "docx_mime_type")
    op.drop_column("document_template_versions", "docx_original_filename")
