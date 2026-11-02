"""Worker handler registry keyed by background job type."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

Handler = Callable[["BackgroundJob"], None]
# Marks the business row of a job as failed when the worker holding it died.
# The reconciler (jobs/reconcile.py) calls it so the UI stops polling a task
# that can never finish.
FailureHandler = Callable[["Session", "BackgroundJob"], None]

_HANDLERS: dict[str, Handler] = {}
_FAILURE_HANDLERS: dict[str, FailureHandler] = {}


def register_handler(job_type: str, handler: Handler) -> None:
    _HANDLERS[job_type] = handler


def get_handler(job_type: str) -> Handler | None:
    return _HANDLERS.get(job_type)


def register_job_failure_handler(job_type: str, handler: FailureHandler) -> None:
    _FAILURE_HANDLERS[job_type] = handler


def get_job_failure_handler(job_type: str) -> FailureHandler | None:
    return _FAILURE_HANDLERS.get(job_type)


def clear_handlers() -> None:
    _HANDLERS.clear()
    _FAILURE_HANDLERS.clear()
    ensure_default_handlers()


def ensure_default_handlers() -> None:
    """Register the built-in handlers if they are not already present."""
    from fde_api.documents.generator import register_document_generation_handler
    from fde_api.files.previews import register_file_preview_handler
    from fde_api.files.processors import register_file_scan_handler
    from fde_api.guidance.jobs import register_presurvey_analysis_handler
    from fde_api.research.export_jobs import register_research_export_handler
    from fde_api.ai.executions import register_ai_execution_handler
    from fde_api.control.automation_jobs import register_automation_handler
    from fde_api.control.chat import execute_chat_job

    if get_handler("file.scan") is None:
        register_file_scan_handler()
    if get_handler("file.preview") is None:
        register_file_preview_handler()
    if get_handler("document.generate") is None:
        register_document_generation_handler()
    if get_handler("project.presurvey.analyze") is None:
        register_presurvey_analysis_handler()
    if get_handler("research.export") is None:
        register_research_export_handler()
    if get_handler("automation.execute") is None:
        register_automation_handler()
    if get_handler("ai.chat") is None:
        register_handler("ai.chat", execute_chat_job)
    if get_handler("ai.execute") is None:
        register_ai_execution_handler()
    if get_handler("dispatch.maintenance") is None:
        from fde_api.dispatch.maintenance import register_dispatch_maintenance_handler

        register_dispatch_maintenance_handler()
    # goal-d9：翻译器管道（outbox → worker，沿预调研分析重试语义）
    if get_handler("translator.translate") is None:
        from fde_api.translator.jobs import register_translator_handler

        register_translator_handler()
    # V3 T-W3：workflow 执行器（call/skill 节点；agent/human_approval 随 T-W4）。
    # handler 内部同时注册 worker-loss 收尾钩子（run/悬挂节点推终态）。
    if get_handler("workflow.run") is None:
        from fde_api.workflows.executor import register_workflow_handler

        register_workflow_handler()

    # 业务行收尾钩子：worker 死亡时把业务行推到终态（否则前端永远轮询）。
    from fde_api.control.automation_jobs import register_automation_failure_handler
    from fde_api.control.chat import register_chat_failure_handler
    from fde_api.guidance.jobs import register_presurvey_analysis_failure_handler
    from fde_api.research.export_jobs import register_research_export_failure_handler

    if get_job_failure_handler("project.presurvey.analyze") is None:
        register_presurvey_analysis_failure_handler()
    if get_job_failure_handler("ai.chat") is None:
        register_chat_failure_handler()
    if get_job_failure_handler("research.export") is None:
        register_research_export_failure_handler()
    if get_job_failure_handler("automation.execute") is None:
        register_automation_failure_handler()
    if get_job_failure_handler("translator.translate") is None:
        from fde_api.translator.jobs import register_translator_failure_handler

        register_translator_failure_handler()


from fde_api.jobs.models import BackgroundJob  # noqa: E402  (late import to avoid cycle)

try:
    ensure_default_handlers()
except Exception:  # noqa: BLE001 - a resolution failure must not break imports
    # 静默吞掉会让全部 handler「消失」（任务全部 no_handler）且无人察觉——
    # 至少把失败留在日志里。
    logger.warning("default handler registration failed", exc_info=True)
