"""V3.1 P1-1：执行面扩列（agent_runs +5 / agent_artifacts +4，2026-11-08）。

任务书 §9「运行记录字段」的落地形（00-gap-register 5.6/5.7 裁决；全可空
additive——旧行读路径零变化）：

- agent_runs：host_agent_id（宿主代理标识——轮询领取面写入；宿主直连通道
  无独立代理进程留空）/ authorization_id（短期票据引用——HTTP 发行面随
  5.10 闸开放轮落地）/ workspace_ref / resume_session_ref（--resume 会话）/ 
  policy_snapshot_hash（execution_policy.policy_snapshot 快照，审计可重算）；
- agent_artifacts：size_bytes/mime_type（落库时由原件得出）+ revoked 留痕
  （revoked_by_user_id/revoked_at——复核撤回补强，此前仅 reviewed 布尔翻转）。

Backup hint: additive only; downgrade drops the added columns.
"""
import sqlalchemy as sa
from alembic import op


revision = "e7c4a9d2f6b8"
down_revision = "d5a8c2f4b7e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("host_agent_id", sa.String(length=120), nullable=True))
    op.add_column("agent_runs", sa.Column("authorization_id", sa.String(length=64), nullable=True))
    op.add_column("agent_runs", sa.Column("workspace_ref", sa.String(length=255), nullable=True))
    op.add_column("agent_runs", sa.Column("resume_session_ref", sa.String(length=120), nullable=True))
    op.add_column("agent_runs", sa.Column("policy_snapshot_hash", sa.String(length=64), nullable=True))
    op.add_column("agent_artifacts", sa.Column("size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("agent_artifacts", sa.Column("mime_type", sa.String(length=120), nullable=True))
    op.add_column(
        "agent_artifacts",
        sa.Column("revoked_by_user_id", sa.String(length=36), nullable=True),
    )
    op.add_column("agent_artifacts", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_agent_artifacts_revoked_by",
        "agent_artifacts",
        "users",
        ["revoked_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_agent_artifacts_revoked_by", "agent_artifacts", type_="foreignkey")
    op.drop_column("agent_artifacts", "revoked_at")
    op.drop_column("agent_artifacts", "revoked_by_user_id")
    op.drop_column("agent_artifacts", "mime_type")
    op.drop_column("agent_artifacts", "size_bytes")
    op.drop_column("agent_runs", "policy_snapshot_hash")
    op.drop_column("agent_runs", "resume_session_ref")
    op.drop_column("agent_runs", "workspace_ref")
    op.drop_column("agent_runs", "authorization_id")
    op.drop_column("agent_runs", "host_agent_id")
