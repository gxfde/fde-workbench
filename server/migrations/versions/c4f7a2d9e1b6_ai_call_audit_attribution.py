"""AI 调用审计归因仪表（N2 仪表化轮；AI 原生化差距台账 G-09 / G-16）。

两件事，**additive + 一处收紧**（不改既有行的业务语义）：

1. **G-09 提示词归因**：``ai_call_audits`` 加两列——
   - ``prompt_fingerprint`` VARCHAR(64)：**指令源文本**的 sha256（模板身份：
     同模板不同输入同指纹；提示词正文绝不落库）；
   - ``prompt_version`` VARCHAR(60)：提示词版本标签（未登记版本者留空，
     随 G-13 版本注册表逐步填充）。
   两列**可空**：历史行与未登记版本者不阻断。

2. **G-16 归因闭合**：``purpose`` 由可空收紧为 **NOT NULL** + CHECK
   （``purpose IS NOT NULL AND length(purpose) >= 1``）。收紧前先把存量
   匿名行（2 行，调用方已不可回溯）统一回填为 ``legacy_unattributed``——
   **不删行、不改其它列**，只让「无用途标识的调用」在账本上可见可查。
   新调用由入口强制传 purpose（``ai/auditing.py`` 单一入口 + 调用点静态钉），
   因此收紧后不存在写不进去的路径。

Backup hint: additive columns + purpose 收紧；downgrade 先删 CHECK 与两列，
再把 ``legacy_unattributed`` 行还原为 NULL 并放开 purpose 可空（回到收紧前
形状；其余行的 purpose 一律不动）。
"""
import sqlalchemy as sa
from alembic import op

revision = "c4f7a2d9e1b6"
down_revision = "d5f9a3c7e1b4"
branch_labels = None
depends_on = None

LEGACY_PURPOSE = "legacy_unattributed"


def upgrade() -> None:
    op.add_column(
        "ai_call_audits",
        sa.Column("prompt_version", sa.String(length=60), nullable=True),
    )
    op.add_column(
        "ai_call_audits",
        sa.Column("prompt_fingerprint", sa.String(length=64), nullable=True),
    )
    # 存量匿名行：调用方已不可回溯 ⇒ 统一标记为可见可查的「来源不明」，
    # 而不是删行或留 NULL（NULL 会被新 CHECK 拒）。
    op.execute(
        f"UPDATE ai_call_audits SET purpose = '{LEGACY_PURPOSE}' WHERE purpose IS NULL"
    )
    op.alter_column(
        "ai_call_audits",
        "purpose",
        existing_type=sa.String(length=60),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_ai_call_audits_purpose",
        "ai_call_audits",
        "purpose IS NOT NULL AND length(purpose) >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_ai_call_audits_purpose", "ai_call_audits", type_="check"
    )
    op.drop_column("ai_call_audits", "prompt_fingerprint")
    op.drop_column("ai_call_audits", "prompt_version")
    op.execute(
        f"UPDATE ai_call_audits SET purpose = NULL WHERE purpose = '{LEGACY_PURPOSE}'"
    )
    op.alter_column(
        "ai_call_audits",
        "purpose",
        existing_type=sa.String(length=60),
        nullable=True,
    )
