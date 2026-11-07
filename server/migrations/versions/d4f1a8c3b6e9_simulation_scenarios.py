"""V3.2 G2：模拟场景库 simulation_scenarios 单表（2026-11-08）

FDE 交付模拟训练场（Delivery Simulation Lab）第一张表：案例库的唯一权威载体。
一行 = 一个**不可变版本快照**，业务键 = (scenario_key, variant, version)：
同一案例的三个客户行为变体（normal/vague/complex）是三条独立分支，各自分支版本化。

隔离纪律（V3.2 G0/G1 P1）：本表**故意没有** project_id 列——模拟场景不属于任何
真实项目，从根上杜绝模拟数据混入真实项目视图/成本/证据口径。

Backup hint: additive only; downgrade drops the single table.
"""
import sqlalchemy as sa
from alembic import op


revision = "d4f1a8c3b6e9"
down_revision = "e5f1a7c3b9d4"
branch_labels = None
depends_on = None


def _timestamp_columns() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "simulation_scenarios",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scenario_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("industry", sa.String(length=64), nullable=False),
        sa.Column("variant", sa.String(length=16), server_default="normal", nullable=False),
        sa.Column("difficulty", sa.String(length=16), server_default="standard", nullable=False),
        sa.Column("split", sa.String(length=16), server_default="train", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("reference_json", sa.JSON(), nullable=True),
        sa.Column("rubric_version", sa.String(length=32), server_default="rubric-v1", nullable=False),
        sa.Column("source_kind", sa.String(length=16), server_default="manual", nullable=False),
        sa.Column("source_ref", sa.String(length=200), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "scenario_key",
            "variant",
            "version",
            name="uq_simulation_scenarios_key_variant_version",
        ),
        sa.CheckConstraint(
            "variant IN ('normal', 'vague', 'complex')",
            name="ck_simulation_scenarios_variant",
        ),
        sa.CheckConstraint(
            "split IN ('train', 'regression', 'blind')",
            name="ck_simulation_scenarios_split",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="ck_simulation_scenarios_status",
        ),
        sa.CheckConstraint(
            "difficulty IN ('basic', 'standard', 'hard')",
            name="ck_simulation_scenarios_difficulty",
        ),
        sa.CheckConstraint(
            "source_kind IN ('seed', 'manual', 'import')",
            name="ck_simulation_scenarios_source_kind",
        ),
    )
    op.create_index(
        "ix_simulation_scenarios_split_status",
        "simulation_scenarios",
        ["split", "status"],
    )
    op.create_index(
        "ix_simulation_scenarios_industry",
        "simulation_scenarios",
        ["industry"],
    )
    op.create_index(
        "ix_simulation_scenarios_key",
        "simulation_scenarios",
        ["scenario_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_simulation_scenarios_key", table_name="simulation_scenarios")
    op.drop_index("ix_simulation_scenarios_industry", table_name="simulation_scenarios")
    op.drop_index(
        "ix_simulation_scenarios_split_status", table_name="simulation_scenarios"
    )
    op.drop_table("simulation_scenarios")
