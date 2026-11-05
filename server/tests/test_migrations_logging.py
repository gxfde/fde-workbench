"""CR-041：alembic env.py 不得禁用导入期创建的模块级 logger。

背景：``logging.config.fileConfig`` 默认 ``disable_existing_loggers=True``，
而 db_session 夹具每次 downgrade/upgrade 都会跑一遍 alembic → env.py 的
``fileConfig`` 被反复调用 → 所有「导入期创建的模块级 logger」
（``logging.getLogger(__name__)``，如 workflows/executor.py）被整体置
``disabled=True`` → 同一测试会话内 caplog 对这些 logger 永远空捕（此前只能
逐测试显式解禁，属基建缺陷而非业务行为）。

修复：env.py 显式 ``disable_existing_loggers=False``（只重配 alembic 自身的
logger，不动已存在的模块级 logger）。本文件把该行为钉住：修复前两条用例皆红。
"""

import logging

# 导入期创建（pytest 收集期，早于任何 alembic 运行）→ 复现 CR-041 的触发条件
logger = logging.getLogger(__name__)


def test_migration_run_keeps_import_time_loggers_enabled() -> None:
    """迁移跑完后，导入期创建的模块级 logger 不得处于 disabled 状态。"""
    assert logger.disabled is False


def test_caplog_captures_module_level_logger_records(caplog) -> None:
    """模块级 logger 的记录必须能被 caplog 捕获（不需逐测试显式解禁）。"""
    with caplog.at_level(logging.INFO, logger=__name__):
        logger.info("CR-041 探针：模块级 logger 应可被 caplog 捕获")
    assert "CR-041 探针" in caplog.text
