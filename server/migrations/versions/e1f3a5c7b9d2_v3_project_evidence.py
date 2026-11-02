"""一等证据表 project_evidence（V3 T-E1，设计 ontology-registry-v1 §2.1）

一次采集、多处引用、不可变、可审计的证据实体：(project_id, source_uri,
content_sha256) 唯一指纹即幂等键；只存指针 + 指纹，不存原件（红线）。
gates 清单项挂接 evidence_id 走 JSON 内字段（T-E2，零 DDL，旧行读时合并为 null）。

Backup hint: additive only (one new table, no existing table touched);
downgrade drops the table and its index.
"""
import sqlalchemy as sa
from alembic import op

revision = "e1f3a5c7b9d2"
down_revision = "c3e7a9b1d5f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        # 指针（红线：不存原件）+ 指纹
        sa.Column("source_uri", sa.String(length=500), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        # 「出处+源块」粒度文本 / 来源通道（human | bridge_sync:{id} | agent_run:{id} | job:{id} | workflow_node:{id}）
        sa.Column("origin", sa.Text(), nullable=True),
        sa.Column("captured_from", sa.String(length=64), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "project_id", "source_uri", "content_sha256",
            name="uq_project_evidence_fingerprint",
        ),
        sa.CheckConstraint(
            "kind IN ('gate', 'task', 'guidance', 'research', 'bridge', 'workflow', 'solution')",
            name="ck_project_evidence_kind",
        ),
        sa.CheckConstraint(
            "char_length(content_sha256) = 64", name="ck_project_evidence_sha256_len"
        ),
    )
    op.create_index(
        "ix_project_evidence_project_kind", "project_evidence", ["project_id", "kind"]
    )


def downgrade() -> None:
    op.drop_index("ix_project_evidence_project_kind", table_name="project_evidence")
    op.drop_table("project_evidence")
