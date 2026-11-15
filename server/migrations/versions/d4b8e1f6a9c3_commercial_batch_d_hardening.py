"""商业域批 D 加固迁移：席位到期非空 CHECK + 兼任指针扩长 500 + 结算科目唯一索引（goal-crv-fix2 r3，2026-11-13）。

链位：接 goal-sprint r2 白名单快照列 c8e2a6f0b9d4 之后（单头 74→75）。

修复条目：
1. QR-055：`commercial_entitlements` 增加 CHECK `ck_commercial_entitlements_active_requires_expiry`
   （`seat_status <> 'active' OR seat_expires_at IS NOT NULL`）；升级前对历史遗留无到期时刻的
   active 行以 `COALESCE(seat_activated_at, now()) + interval '1 year'` 幂等补齐。
2. QR-057：`commercial_role_assignments.source_uri` 列宽由 `String(255)` 扩至 `String(500)`，
   对齐服务层 `_URI_MAX = 500`。
3. QR-059：`commercial_opportunities.settled_ledger_entry_id` 增加部分唯一索引
   `uq_commercial_opportunities_settled_ledger`（`WHERE settled_ledger_entry_id IS NOT NULL`），
   数据库层兜底防同一 `project_share` 科目行被多条商机重复引用结算。

Backup hint: widens column + adds check constraint and partial unique index; downgrade reverses in order.
"""
import sqlalchemy as sa
from alembic import op

revision = "d4b8e1f6a9c3"
down_revision = "c8e2a6f0b9d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE commercial_entitlements "
            "SET seat_expires_at = COALESCE(seat_activated_at, now()) + interval '1 year' "
            "WHERE seat_status = 'active' AND seat_expires_at IS NULL"
        )
    )
    op.create_check_constraint(
        "ck_commercial_entitlements_active_requires_expiry",
        "commercial_entitlements",
        "seat_status <> 'active' OR seat_expires_at IS NOT NULL",
    )
    op.alter_column(
        "commercial_role_assignments",
        "source_uri",
        existing_type=sa.String(length=255),
        type_=sa.String(length=500),
        existing_nullable=False,
    )
    op.create_index(
        "uq_commercial_opportunities_settled_ledger",
        "commercial_opportunities",
        ["settled_ledger_entry_id"],
        unique=True,
        postgresql_where=sa.text("settled_ledger_entry_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_commercial_opportunities_settled_ledger",
        table_name="commercial_opportunities",
    )
    op.alter_column(
        "commercial_role_assignments",
        "source_uri",
        existing_type=sa.String(length=500),
        type_=sa.String(length=255),
        existing_nullable=False,
        postgresql_using="LEFT(source_uri, 255)",
    )
    op.drop_constraint(
        "ck_commercial_entitlements_active_requires_expiry",
        "commercial_entitlements",
        type_="check",
    )
