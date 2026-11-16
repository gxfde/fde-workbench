"""agent_tool_calls 加载荷审计留痕三列——AF1-WP4 N1（docs/ai-fde/13 §6.2）

工程台「工具历史/Diff/校验错误」回查面此前无数据源：``AgentToolCall`` 只有
tool_name/decision/capability/reason/duration_ms，dry_validate 候选与
violations 不可回查；直连循环 trace 仅内存（挂账「直连循环持久审计留痕」）。

本迁移（append-only 加列，既有列语义零变化）：
- ``request_json`` / ``response_json``：JSON 文本载荷（64KB 上限，截断由
  ``payload_audit.audit_payload`` 在写入侧保证）；
- ``payload_truncated``：截断标记位（存量行 server_default false）。

缺省 NULL/false＝存量路径零行为变化；denied 留痕照旧（越权反查连载荷可回查）。
"""
import sqlalchemy as sa
from alembic import op

revision = "a1e5f9c3d7b2"
down_revision = "d8b4f6a2c9e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_tool_calls", sa.Column("request_json", sa.Text(), nullable=True))
    op.add_column("agent_tool_calls", sa.Column("response_json", sa.Text(), nullable=True))
    op.add_column(
        "agent_tool_calls",
        sa.Column(
            "payload_truncated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # 工程台 token 标记表（一次性消费/客户端绑定/吊销；jti 派生 key——token
    # 明文零落库）。主键即派生 key（String 48 hex），零 FK：标记独立于用户/组织
    # 行生命周期，随运维清理。
    op.create_table(
        "eng_token_marks",
        sa.Column("id", sa.String(length=96), primary_key=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    op.drop_table("eng_token_marks")
    op.drop_column("agent_tool_calls", "payload_truncated")
    op.drop_column("agent_tool_calls", "response_json")
    op.drop_column("agent_tool_calls", "request_json")
