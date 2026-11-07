"""V3.1 P0-1：discovery 四表（discovery_extractions/business_facts/requirements/
requirement_sources，2026-11-08）。

任务书 §5 目标模型的落地形（00-gap-register P0-1 裁决）：
- 七组示例收敛为 facts[].fact_type 十值 + requirements 独立组；
- classification 对齐 guidance 五分类；
- 抽取行 status 四值（accepted/rejected 为派生态不物化，B#13-C 先例）；
- 幂等键 (project, source_type, source_id, extractor_version, prompt_version)。

Backup hint: additive only; downgrade drops child-first
(requirement_sources → requirements → business_facts → discovery_extractions).
"""
import sqlalchemy as sa
from alembic import op


revision = "c3d5e7f9a1b4"
down_revision = "e8b1d5f9a3c7"
branch_labels = None
depends_on = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "discovery_extractions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("extractor_version", sa.String(length=40), server_default="discovery-extractor-v1", nullable=False),
        sa.Column("prompt_version", sa.String(length=40), server_default="discovery-prompt-v1", nullable=False),
        sa.Column("ai_model", sa.String(length=120), nullable=True),
        sa.Column("ai_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=60), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("redaction_entries", sa.JSON(), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'review_required', 'failed')",
            name="ck_discovery_extractions_status",
        ),
        sa.CheckConstraint(
            "source_type IN ('interview_minutes', 'transcript_draft')",
            name="ck_discovery_extractions_source_type",
        ),
        sa.CheckConstraint(
            "(status <> 'failed') OR (failure_code IS NOT NULL AND failure_code <> '')",
            name="ck_discovery_extractions_failed_reason",
        ),
        sa.CheckConstraint(
            "(status <> 'failed') OR (failure_message IS NOT NULL)",
            name="ck_discovery_extractions_failed_message",
        ),
        sa.CheckConstraint("char_length(source_sha256) = 64", name="ck_discovery_extractions_sha_len"),
        sa.UniqueConstraint(
            "project_id", "source_type", "source_id", "extractor_version", "prompt_version",
            name="uq_discovery_extractions_source_version",
        ),
    )
    op.create_index(
        "ix_discovery_extractions_project_status", "discovery_extractions", ["project_id", "status"]
    )
    op.create_table(
        "business_facts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("extraction_id", sa.String(length=36), nullable=False),
        sa.Column("fact_type", sa.String(length=20), nullable=False),
        sa.Column("classification", sa.String(length=20), server_default="customer_stated", nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("predicate", sa.String(length=200), nullable=False),
        sa.Column("object_value", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("source_ref", sa.String(length=80), nullable=False),
        sa.Column("source_locator", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.String(length=500), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["extraction_id"], ["discovery_extractions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "fact_type IN ('process', 'role', 'system', 'rule', 'data_object', "
            "'metric', 'constraint', 'pain_point', 'decision', 'open_question')",
            name="ck_business_facts_fact_type",
        ),
        sa.CheckConstraint(
            "classification IN ('customer_stated', 'ai_synthesized', 'ai_inferred', 'open_question', 'human_added')",
            name="ck_business_facts_classification",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected', 'needs_clarification')",
            name="ck_business_facts_review_status",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_business_facts_confidence_range",
        ),
        sa.CheckConstraint(
            "classification NOT IN ('open_question', 'ai_inferred') OR review_status = 'needs_clarification' OR reviewed_by_user_id IS NOT NULL",
            name="ck_business_facts_inference_review",
        ),
        sa.CheckConstraint(
            "review_status NOT IN ('accepted', 'rejected') OR (reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_business_facts_review_stamp",
        ),
        sa.CheckConstraint(
            "review_status <> 'pending' OR (reviewed_by_user_id IS NULL AND reviewed_at IS NULL)",
            name="ck_business_facts_pending_unstamped",
        ),
        sa.UniqueConstraint("extraction_id", "fact_type", "subject", "predicate", name="uq_business_facts_batch_identity"),
    )
    op.create_index("ix_business_facts_project_review", "business_facts", ["project_id", "review_status"])
    op.create_index("ix_business_facts_extraction", "business_facts", ["extraction_id"])
    op.create_table(
        "requirements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("extraction_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("requirement_key", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("requirement_type", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=10), server_default="medium", nullable=False),
        sa.Column("acceptance_criteria", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("approved_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.String(length=500), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["extraction_id"], ["discovery_extractions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "requirement_type IN ('functional', 'non_functional', 'data', 'integration', 'security', 'operational')",
            name="ck_requirements_type",
        ),
        sa.CheckConstraint("priority IN ('high', 'medium', 'low')", name="ck_requirements_priority"),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'needs_clarification')",
            name="ck_requirements_status",
        ),
        sa.CheckConstraint(
            "status NOT IN ('accepted', 'rejected') OR (approved_by_user_id IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_requirements_review_stamp",
        ),
        sa.CheckConstraint(
            "status <> 'pending' OR (approved_by_user_id IS NULL AND approved_at IS NULL)",
            name="ck_requirements_pending_unstamped",
        ),
        sa.UniqueConstraint("project_id", "requirement_key", name="uq_requirements_project_key"),
    )
    op.create_index("ix_requirements_project_status", "requirements", ["project_id", "status"])
    op.create_table(
        "requirement_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("requirement_id", sa.String(length=36), nullable=False),
        sa.Column("fact_id", sa.String(length=36), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("source_ref", sa.String(length=80), nullable=False),
        sa.Column("source_locator", sa.JSON(), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["requirement_id"], ["requirements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["fact_id"], ["business_facts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("requirement_id", "fact_id", name="uq_requirement_sources_requirement_fact"),
    )
    op.create_index("ix_requirement_sources_requirement", "requirement_sources", ["requirement_id"])
    op.create_index("ix_requirement_sources_fact", "requirement_sources", ["fact_id"])


def downgrade() -> None:
    op.drop_index("ix_requirement_sources_fact", table_name="requirement_sources")
    op.drop_index("ix_requirement_sources_requirement", table_name="requirement_sources")
    op.drop_table("requirement_sources")
    op.drop_index("ix_requirements_project_status", table_name="requirements")
    op.drop_table("requirements")
    op.drop_index("ix_business_facts_extraction", table_name="business_facts")
    op.drop_index("ix_business_facts_project_review", table_name="business_facts")
    op.drop_table("business_facts")
    op.drop_index("ix_discovery_extractions_project_status", table_name="discovery_extractions")
    op.drop_table("discovery_extractions")
