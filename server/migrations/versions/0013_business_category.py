"""Add the business category column to project files and documents.

Introduces a fixed business stage (商务合约 / 预调研 / 调研 / PoV验证 / 生产部署 /
培训预交接) on both ``project_files`` and ``project_documents``. The column is
nullable: ``NULL`` (and by convention the client's 未分类) means the item is not
yet assigned a business stage. A ``CheckConstraint`` freezes the allowed value
set so the column cannot drift from the product-defined stages.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_business_category"
down_revision: str | None = "0012_research_form_nullable"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_BUSINESS_CATEGORIES_CHECK = (
    "business_category IS NULL OR business_category IN "
    "('商务合约', '预调研', '调研', 'PoV验证', '生产部署', '培训预交接')"
)


def upgrade() -> None:
    op.add_column(
        "project_files",
        sa.Column("business_category", sa.String(length=32), nullable=True),
    )
    op.create_check_constraint(
        "ck_project_files_business_category",
        "project_files",
        _BUSINESS_CATEGORIES_CHECK,
    )
    op.add_column(
        "project_documents",
        sa.Column("business_category", sa.String(length=32), nullable=True),
    )
    op.create_check_constraint(
        "ck_project_documents_business_category",
        "project_documents",
        _BUSINESS_CATEGORIES_CHECK,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_project_documents_business_category", "project_documents", type_="check"
    )
    op.drop_column("project_documents", "business_category")
    op.drop_constraint(
        "ck_project_files_business_category", "project_files", type_="check"
    )
    op.drop_column("project_files", "business_category")
