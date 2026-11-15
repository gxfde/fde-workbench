"""学习闭环 2.0 L5（迁移②）：动态经验卡＋提示词覆层＋审计归因列。

- ``agent_lessons``：动态经验行（与 ``seeds/lessons.json`` 同构 schema），
  由改进提案采纳后创建，status=draft→published 后经 release_channel
  热生效；``entry_id`` 前缀 ``LESS-DYN-``，与 seeds ``LESS-SOP-`` 跨层
  经 ``text_sha256`` 唯一约束防重；text 变更＝开新行（行不可变纪律）。
- ``prompt_overlays``：提示词覆层（追加式条款，fragment≤200 字），经
  release_channel 发布后在两点装载读面（``execute_ai_prompt``＋
  ``DeepSeekClient.complete_json``）注入；``content_sha256`` 行不可变。
- ``ai_call_audits.context_payload_json``：overlay 归因列（可空）——
  值形如 ``{"overlay_ids":[…],"overlay_sha256":[…]}``（PG JSON 包含
  查询可反查）；未使用 overlay 的调用行留 NULL，既有构造点零回归。

幂等：新建两表＋加列一次；downgrade 对称可逆（drop 列→drop 表顺序）。
Backup hint: 两新表＋一可空列；零数据改写、零回填。
"""
from alembic import op
import sqlalchemy as sa

revision = "a9f3e5c7b1d2"
down_revision = "d4b7e2f9a6c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. agent_lessons（动态经验卡，agents 域表簇）
    # ------------------------------------------------------------------
    op.create_table(
        "agent_lessons",
        sa.Column("id", sa.String(length=36), nullable=False),
        # 稳定业务键（如 LESS-DYN-001）；跨层与 seeds 不重号
        sa.Column("entry_id", sa.String(length=32), nullable=False),
        sa.Column(
            "capability_tags",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        # 经验正文（≤300 字纪律，蒸馏提示词数据框定）
        sa.Column("text", sa.Text(), nullable=False),
        # 服务端写入侧现算（正文不可变；变更＝新行）
        sa.Column("text_sha256", sa.String(length=64), nullable=False),
        # 来源指针（SOP 章节 / 提案 ref）
        sa.Column("source_ref", sa.String(length=500), nullable=True),
        # 产生本条的改进提案（软链：提案归档清理不连带经验行）
        sa.Column(
            "source_proposal_id",
            sa.String(length=36),
            sa.ForeignKey("improvement_proposals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="draft",
            nullable=False,
        ),
        # 行业过滤（可选）；空列表＝全行业
        sa.Column(
            "industries",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
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
        sa.UniqueConstraint("entry_id", name="uq_agent_lessons_entry_id"),
        sa.UniqueConstraint(
            "text_sha256", name="uq_agent_lessons_text_sha256"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'retired')",
            name="ck_agent_lessons_status",
        ),
        sa.Index("ix_agent_lessons_status", "status"),
        sa.Index("ix_agent_lessons_created", "created_at"),
    )

    # ------------------------------------------------------------------
    # 2. prompt_overlays（提示词覆层，workbench 域表簇）
    # ------------------------------------------------------------------
    op.create_table(
        "prompt_overlays",
        sa.Column("id", sa.String(length=36), nullable=False),
        # purpose_key ≡ prompt_registry purpose 字面值（下划线风格）；
        # 发布时闭集校验——未登记 purpose 拒发布。
        sa.Column("purpose_key", sa.String(length=60), nullable=False),
        # 追加式条款正文（≤200 字；句式静态闸拦截祈使/第二人称）
        sa.Column("fragment", sa.String(length=200), nullable=False),
        # 服务端写入侧现算（fragment 不可变）
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        # 数字尾缀比较防 v10<v2（v3⇒3、v10⇒10；字符串比较会错位）
        sa.Column("min_prompt_version", sa.String(length=20), nullable=True),
        # 产生本条的改进提案（软链：提案归档清理不连带覆层行）
        sa.Column(
            "source_proposal_id",
            sa.String(length=36),
            sa.ForeignKey("improvement_proposals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="draft",
            nullable=False,
        ),
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
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'retired')",
            name="ck_prompt_overlays_status",
        ),
        sa.Index("ix_prompt_overlays_purpose", "purpose_key"),
        sa.Index("ix_prompt_overlays_status", "status"),
    )

    # ------------------------------------------------------------------
    # 3. ai_call_audits.context_payload_json（overlay 归因列，可空）
    # ------------------------------------------------------------------
    op.add_column(
        "ai_call_audits",
        sa.Column("context_payload_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_call_audits", "context_payload_json")
    op.drop_table("prompt_overlays")
    op.drop_table("agent_lessons")
