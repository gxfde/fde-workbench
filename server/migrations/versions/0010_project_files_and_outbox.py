"""Add project files, upload sessions, outbox events, and background jobs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0010_project_files_and_outbox"
down_revision: str | None = "0009_research_import_batches"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("UTC_TIMESTAMP(6)"),
        ),
        sa.Column(
            "updated_at",
            mysql.TIMESTAMP(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
        ),
    )


def _version() -> sa.Column:
    return sa.Column(
        "version", sa.Integer(), nullable=False, server_default=sa.text("1")
    )


def upgrade() -> None:
    op.create_table(
        "project_files",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False, server_default="attachment"),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("current_version_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        *_timestamps(),
        _version(),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "project_id",
            "category",
            "display_name",
            name="uq_project_files_project_category_name",
        ),
        sa.CheckConstraint(
            "category IN ('attachment', 'document')", name="ck_project_files_category"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')", name="ck_project_files_status"
        ),
    )
    op.create_index("ix_project_files_project_id", "project_files", ["project_id"])
    op.create_index(
        "ix_project_files_project_status", "project_files", ["project_id", "status"]
    )

    op.create_table(
        "project_file_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("file_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False, server_default="upload"),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("safe_filename", sa.String(length=255), nullable=False),
        sa.Column("extension", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("mime_type", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("bucket", sa.String(length=63), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("etag", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column(
            "scan_status",
            sa.String(length=24),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "preview_status",
            sa.String(length=24),
            nullable=False,
            server_default="none",
        ),
        sa.Column("preview_version_id", sa.String(length=36), nullable=True),
        sa.Column("uploaded_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="uploading",
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["file_id"], ["project_files.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["preview_version_id"], ["project_file_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"], ["project_file_versions.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "file_id", "version_number", name="uq_project_file_versions_file_version"
        ),
        sa.CheckConstraint(
            "version_number >= 1", name="ck_project_file_versions_number"
        ),
        sa.CheckConstraint(
            "status IN ('uploading', 'quarantined', 'available', 'rejected', 'failed')",
            name="ck_project_file_versions_status",
        ),
        sa.CheckConstraint(
            "scan_status IN "
            "('pending', 'scanning', 'clean', 'infected', 'error', 'not_required')",
            name="ck_project_file_versions_scan_status",
        ),
        sa.CheckConstraint(
            "preview_status IN ('none', 'pending', 'ready', 'failed')",
            name="ck_project_file_versions_preview_status",
        ),
    )
    op.create_index(
        "ix_project_file_versions_file_id", "project_file_versions", ["file_id"]
    )
    op.create_index(
        "ix_project_file_versions_status", "project_file_versions", ["status"]
    )

    # The circular current-version reference must be added after both tables exist.
    op.create_foreign_key(
        "fk_project_files_current_version",
        "project_files",
        "project_file_versions",
        ["current_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("file_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("expected_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "expected_mime_type", sa.String(length=120), nullable=False, server_default=""
        ),
        sa.Column("bucket", sa.String(length=63), nullable=False),
        sa.Column("storage_prefix", sa.String(length=512), nullable=False),
        sa.Column("multipart_upload_id", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="uploading"
        ),
        sa.Column("requested_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column(
            "completion_json", sa.JSON(), nullable=False
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["file_id"], ["project_files.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "project_id", "idempotency_key", name="uq_upload_sessions_project_idempotency"
        ),
        sa.CheckConstraint(
            "status IN ('uploading', 'completed', 'aborted', 'expired')",
            name="ck_upload_sessions_status",
        ),
    )
    op.create_index(
        "ix_upload_sessions_project_status", "upload_sessions", ["project_id", "status"]
    )
    op.create_index("ix_upload_sessions_expires_at", "upload_sessions", ["expires_at"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("topic", sa.String(length=80), nullable=False),
        sa.Column("aggregate_id", sa.String(length=36), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("UTC_TIMESTAMP(6)"),
        ),
        sa.Column("last_error", sa.Text(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('pending', 'dispatched', 'completed', 'failed')",
            name="ck_outbox_events_status",
        ),
    )
    op.create_index(
        "ix_outbox_events_status_available", "outbox_events", ["status", "available_at"]
    )
    op.create_index("ix_outbox_events_aggregate_id", "outbox_events", ["aggregate_id"])

    op.create_table(
        "background_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("UTC_TIMESTAMP(6)"),
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column(
            "active_key",
            sa.String(length=150),
            sa.Computed(
                "CASE WHEN status IN ('pending', 'queued', 'running') "
                "THEN CONCAT(job_type, ':', target_id) ELSE NULL END",
                persisted=True,
            ),
            nullable=True,
        ),
        *_timestamps(),
        _version(),
        sa.CheckConstraint(
            "status IN ('pending', 'queued', 'running', 'succeeded', 'failed')",
            name="ck_background_jobs_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_background_jobs_attempts"),
        sa.UniqueConstraint("active_key", name="uq_background_jobs_active_key"),
    )
    op.create_index(
        "ix_background_jobs_status_available", "background_jobs", ["status", "available_at"]
    )
    op.create_index(
        "ix_background_jobs_job_type_target", "background_jobs", ["job_type", "target_id"]
    )


def downgrade() -> None:
    op.drop_table("background_jobs")
    op.drop_table("outbox_events")
    op.drop_table("upload_sessions")
    op.drop_constraint(
        "fk_project_files_current_version", "project_files", type_="foreignkey"
    )
    op.drop_table("project_file_versions")
    op.drop_table("project_files")
