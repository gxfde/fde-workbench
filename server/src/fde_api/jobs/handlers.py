"""Worker handler registry keyed by background job type."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Handler = Callable[["BackgroundJob"], None]

_HANDLERS: dict[str, Handler] = {}


def register_handler(job_type: str, handler: Handler) -> None:
    _HANDLERS[job_type] = handler


def get_handler(job_type: str) -> Handler | None:
    return _HANDLERS.get(job_type)


def clear_handlers() -> None:
    _HANDLERS.clear()
    ensure_default_handlers()


def ensure_default_handlers() -> None:
    """Register the built-in handlers if they are not already present."""
    from fde_api.documents.generator import register_document_generation_handler
    from fde_api.files.previews import register_file_preview_handler
    from fde_api.files.processors import register_file_scan_handler
    from fde_api.guidance.jobs import register_presurvey_analysis_handler
    from fde_api.research.export_jobs import register_research_export_handler
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


from fde_api.jobs.models import BackgroundJob  # noqa: E402  (late import to avoid cycle)

try:
    ensure_default_handlers()
except Exception:  # noqa: BLE001 - a resolution failure must not break imports
    pass
