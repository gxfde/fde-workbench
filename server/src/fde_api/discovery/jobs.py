"""discovery 抽取后台任务（V3.1 P0-1）：克隆 guidance/jobs.py 管线纪律。

- 状态推进 queued→running→{review_required|failed}；终态重复投递零动作。
- AI 调用走 ``execute_ai_prompt`` 单一入口（预算门+审计+降级直连全复用）。
- 契约失败一次自动重试（概率性畸形输出）；瞬时错误退避后重试。
- 源文本入库时已经 T-A2 代号化（transcripts 闸），输入不二次脱敏；
  模型输出端逐字符串字段过 ``redact_text_detailed`` 兜底 + 复核事件。
- 整批失败零写入（任务书：不得静默部分写入）。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from fde_api.control.ai_server_client import DSHRuntimeError, execute_ai_prompt
from fde_api.discovery.contract import DiscoveryContractError, validate_extraction_output
from fde_api.discovery.models import (
    BusinessFact,
    DiscoveryExtraction,
    PROMPT_VERSION,
    Requirement,
    RequirementSource,
    REDACTION_EVENT_TYPE,
)
from fde_api.discovery.prompt import DISCOVERY_SYSTEM_PROMPT
from fde_api.extensions import db
from fde_api.guidance.enterprise_dict import DICT_FAILURE_CODE, RedactionConfigError
from fde_api.guidance.redaction import redact_text_detailed
from fde_api.jobs.handlers import register_handler, register_job_failure_handler
from fde_api.transcripts.models import InterviewMinutes, TranscriptDraft
from fde_api.workbench.models import OperationEvent, Project

logger = logging.getLogger(__name__)

CONTRACT_RETRY_LIMIT = 1
TRANSIENT_RETRY_CODES = frozenset({"ai_rate_limited", "ai_timeout", "ai_service_unavailable", "ai_unavailable"})
RETRY_BACKOFF_SECONDS = 1.0
UNEXPECTED_FAILURE_CODE = "discovery_unexpected_error"
WORKER_LOST_CODE = "discovery_worker_lost"
OUTPUT_INVALID_CODE = "ai_output_invalid"


def _redact_out(value: str, *, project_code: str, sink: list[dict[str, Any]]) -> str:
    """输出端兜底脱敏（guidance 第③层同构）：命中词典/疑似均替换并记复核。"""
    result = redact_text_detailed(value, project_code=project_code)
    for suspect in result.suspects:
        sink.append({"name": suspect.name, "occurrences": suspect.occurrences, "matched_dict": False})
    for name in result.replaced:
        sink.append({"name": name, "occurrences": 1, "matched_dict": True})
    return result.text


def _redact_object(value: Any, *, project_code: str, sink: list[dict[str, Any]]) -> Any:
    if isinstance(value, str):
        return _redact_out(value, project_code=project_code, sink=sink)
    if isinstance(value, list):
        return [_redact_object(item, project_code=project_code, sink=sink) for item in value]
    if isinstance(value, dict):
        return {key: _redact_object(item, project_code=project_code, sink=sink) for key, item in value.items()}
    return value


def _project_code(session, project_id: str) -> str:
    return session.scalar(select(Project.enterprise_code).where(Project.id == project_id)) or ""


def _source_content(session, extraction: DiscoveryExtraction) -> str:
    if extraction.source_type == "interview_minutes":
        row = session.get(InterviewMinutes, extraction.source_id)
        if row is None:
            raise LookupError("source_missing")
        return row.content
    row = session.get(TranscriptDraft, extraction.source_id)
    if row is None or row.content is None:
        raise LookupError("source_missing")
    return row.content


def handle_discovery_extraction(job) -> None:
    session = db.session()
    try:
        extraction = session.get(DiscoveryExtraction, job.target_id)
        if extraction is None or extraction.status in {"review_required", "failed"}:
            # 终态重复投递零动作；queued→running 由本 handler 独占推进
            if extraction is not None and extraction.status == "running":
                pass  # 崩溃恢复残留：继续走（幂等由契约与全量覆写保证）
            elif extraction is None or extraction.status != "queued":
                return
        extraction.status = "running"
        session.commit()
        try:
            content = _source_content(session, extraction)
        except LookupError:
            _fail(session, extraction, "source_missing", "抽取源（纪要/草稿）已不存在。")
            return
        project_code = _project_code(session, extraction.project_id)
        redaction_entries: list[dict[str, Any]] = []
        model_name: str | None = None
        attempts = 0
        while True:
            attempts += 1
            try:
                answer = execute_ai_prompt(
                    user_id=extraction.created_by_user_id,
                    prompt=content,
                    system_prompt=DISCOVERY_SYSTEM_PROMPT,
                    use_tools=False,
                    project_id=extraction.project_id,
                    execution_id=f"discovery:{extraction.id}:{attempts}",
                    purpose="discovery_extract",
                    prompt_version=PROMPT_VERSION,
                    return_metadata=True,
                )
                if not isinstance(answer, dict):
                    answer = dict(text=answer, model={})
                model_name = str(((answer.get("model") or {}).get("name") or "")) or None
                text = answer["text"]
                payload = json.loads(text) if isinstance(text, str) else text
                draft = validate_extraction_output(payload)
                break
            except (json.JSONDecodeError, DiscoveryContractError) as error:
                code = getattr(error, "code", None)
                path = getattr(error, "path", "")
                if attempts > CONTRACT_RETRY_LIMIT:
                    logger.warning(
                        "discovery contract violation not recovered (%s at %s)",
                        code, path,
                    )
                    _fail(
                        session, extraction, OUTPUT_INVALID_CODE,
                        "AI 返回的抽取结果格式不正确（已自动重试仍失败），请重跑或更换模型。",
                    )
                    return
                # 概率性契约失败：立即重试（不退避——guidance 同裁）
            except DSHRuntimeError as error:
                if error.code not in TRANSIENT_RETRY_CODES or attempts > CONTRACT_RETRY_LIMIT:
                    _fail(session, extraction, error.code, error.public_message)
                    return
                time.sleep(RETRY_BACKOFF_SECONDS)
            except RedactionConfigError:
                _fail(
                    session, extraction, DICT_FAILURE_CODE,
                    "企业名词典不可用，为守住「客户名不入库」红线已阻断本次抽取，请联系管理员修复词典配置。",
                )
                return
        # 输出端逐字符串兜底脱敏（subject/predicate/object_value 内所有字符串）
        facts = []
        for item in draft["facts"]:
            facts.append({
                **item,
                "subject": _redact_out(item["subject"], project_code=project_code, sink=redaction_entries),
                "predicate": _redact_out(item["predicate"], project_code=project_code, sink=redaction_entries),
                "object_value": _redact_object(item["object_value"], project_code=project_code, sink=redaction_entries),
            })
        source_ref = f"{extraction.source_type}:{extraction.source_id}"
        # 整批写入（此前零业务写入——失败路径无残留）
        fact_rows: list[BusinessFact] = []
        for item in facts:
            if item["needs_clarification"]:
                classification, review_status = "open_question", "needs_clarification"
            elif item["inference"]:
                classification, review_status = "ai_inferred", "needs_clarification"
            else:
                classification, review_status = "customer_stated", "pending"
            fact_row = BusinessFact(
                project_id=extraction.project_id,
                extraction_id=extraction.id,
                fact_type=item["fact_type"],
                classification=classification,
                subject=item["subject"],
                predicate=item["predicate"],
                object_value=item["object_value"],
                confidence=item["confidence"],
                source_ref=source_ref,
                source_locator=item["source_locator"],
                review_status=review_status,
            )
            session.add(fact_row)
            fact_rows.append(fact_row)
        session.flush()
        for item in draft["requirements"]:
            requirement = Requirement(
                project_id=extraction.project_id,
                extraction_id=extraction.id,
                created_by_user_id=extraction.created_by_user_id,
                requirement_key=f"R-{requirement_suffix(session, extraction.project_id)}",
                title=item["title"],
                description=item["description"],
                requirement_type=item["requirement_type"],
                priority=item["priority"],
                acceptance_criteria=item["acceptance_criteria"],
                # 无来源事实支撑 → 待澄清（任务书：无来源不得自动接受）
                status="pending" if item["source_fact_indexes"] else "needs_clarification",
            )
            session.add(requirement)
            session.flush()
            for index in item["source_fact_indexes"]:
                session.add(
                    RequirementSource(
                        requirement_id=requirement.id,
                        fact_id=fact_rows[index].id,
                        project_id=extraction.project_id,
                        source_ref=source_ref,
                        source_locator=fact_rows[index].source_locator,
                    )
                )
        extraction.status = "review_required"
        extraction.ai_model = model_name
        extraction.ai_generated_at = datetime.now(UTC)
        extraction.completed_at = datetime.now(UTC)
        extraction.failure_code = None
        extraction.failure_message = None
        extraction.redaction_entries = redaction_entries or None
        if redaction_entries:
            session.add(
                OperationEvent(
                    actor_user_id=extraction.created_by_user_id,
                    project_id=extraction.project_id,
                    target_type="discovery_extraction",
                    target_id=extraction.id,
                    event_type=REDACTION_EVENT_TYPE,
                    changes={"entries": redaction_entries},
                )
            )
        session.commit()
    except Exception as error:  # noqa: BLE001 - 抽取绝不能卡在 running 态
        logger.warning("discovery extraction unexpected failure (%s)", type(error).__name__)
        session.rollback()
        stuck = session.get(DiscoveryExtraction, job.target_id)
        if stuck is not None:
            _fail(session, stuck, UNEXPECTED_FAILURE_CODE, "抽取过程出现未预期错误，请重跑；若持续失败请检查源文本。")
    finally:
        session.close()


def requirement_suffix(session, project_id: str) -> str:
    import uuid

    return uuid.uuid4().hex[:8]


def _fail(session, row: DiscoveryExtraction, code: str, message: str) -> None:
    row.status = "failed"
    row.failure_code = code
    row.failure_message = message
    row.completed_at = datetime.now(UTC)
    session.commit()


def register_discovery_extraction_handler() -> None:
    register_handler("project.discovery.extract", handle_discovery_extraction)


def fail_extraction_on_worker_loss(session, job) -> None:
    row = session.get(DiscoveryExtraction, job.target_id)
    if row is None or row.status in {"review_required", "failed"}:
        return
    row.status = "failed"
    row.failure_code = WORKER_LOST_CODE
    row.failure_message = "抽取进程中断（后台任务进程退出），请重跑。"


def register_discovery_extraction_failure_handler() -> None:
    register_job_failure_handler("project.discovery.extract", fail_extraction_on_worker_loss)
