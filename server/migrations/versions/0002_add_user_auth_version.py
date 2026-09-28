"""Add durable access-token invalidation version to users."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0002_add_user_auth_version"
down_revision: str | None = "0001_users_and_refresh_sessions"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "auth_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "auth_version")
