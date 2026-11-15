"""M6-WP0 D11：双平行迁移主线收单（merge 迁移，零 DDL）。

本地 80 链（head ``e9c4b7a1d5f8``，M5 全量）与 fork/main 77 链（head
``a9f3e5c7b1d2``）共享 74 revision、各自从 ``c8e2a6f0b9d4`` 分叉（本地
独有 6 / fork 独有 3，无同名 revision id；WP0 执行细则①，merge-tree
实测 4 处真冲突全数按 A 主干口径解）。P1 §7④ 裁决 merge 非 rebase。

两支链 DDL 无语义交叠（本地支链=WP4/WP5 六增量；fork 支链=commercial
batch D 加固〔零 DDL〕+ Loop2-L4 candidate payload 加列 + Loop2-L5
lessons/prompt_overlays 两表），并卷只需图收单：本迁移零 DDL，仅把双
head 收敛为唯一 head，使任一支链 stamp 的环境经 ``alembic upgrade head``
平滑走完对侧增量（fork 头 a9f3e5c7b1d2 的开发库/历史测试库同理）。

V3.3 M6-WP0 前提门禁（P1 2026-11-15 签署 af30253；细则②）。
"""
revision = "c2a9e7d5b3f1"
down_revision = ("e9c4b7a1d5f8", "a9f3e5c7b1d2")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
