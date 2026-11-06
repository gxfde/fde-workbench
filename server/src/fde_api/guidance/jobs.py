from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from flask import current_app
from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.agents.quota import record_action as record_seat_action
from fde_api.ai.kimi import KimiError, KimiFileClient
from fde_api.extensions import db, object_storage
from fde_api.files.models import ProjectFileVersion
from fde_api.guidance.ai_prompt import build_kimi_presurvey_analysis_messages
from fde_api.guidance.ai_schema import GuidanceContractError, LIST_FIELDS, validate_guidance_output
from fde_api.guidance.enterprise_dict import RedactionConfigError, enterprise_names
from fde_api.guidance.models import ProjectGuidanceAnalysis
from fde_api.guidance.redaction import redact_text_detailed
from fde_api.jobs.handlers import register_handler, register_job_failure_handler
from fde_api.storage.base import StorageNotFoundError
from fde_api.workbench.models import OperationEvent, Project

logger = logging.getLogger(__name__)

# 同一任务内的自动重试上限（不含首次尝试）。契约失败（ai_output_invalid）是
# MiniMax 级模型概率性不守 JSON 合同的已知现象：一次自动重试即可消化绝大多数，
# 上限必须有测试钉住——无上限会在模型持续吐畸形输出时把 worker 拖死。
GUIDANCE_ANALYSIS_RETRY_LIMIT = 1

# 退避只对瞬时错误有意义：限流/超时/服务不可用。契约违反不在此列。
TRANSIENT_RETRY_CODES = frozenset({"ai_rate_limited", "ai_timeout", "ai_service_unavailable", "ai_unavailable"})
RETRY_BACKOFF_SECONDS = 1.0

# 存储对象缺失（文件被外部删除）属于确定性故障：重试没有意义，但也不能
# 混进「未预期错误」——运维需要能区分它和真 bug。
SOURCE_OBJECT_MISSING_CODE = "source_object_missing"

# 兜底分类：KimiError / GuidanceContractError 之外的未预期异常。异常路径下
# 分析一定会落 failed（不会卡在 analyzing 让前端无限轮询）；进程被杀死
# （OOM/部署）不在本保证内——那条路由对账任务收尾（见 jobs/reconcile.py）。
UNEXPECTED_FAILURE_CODE = "analysis_unexpected_error"

# worker 进程死亡（OOM/部署）导致的中断：分析没跑完，也没人能再跑。
WORKER_LOST_CODE = "analysis_worker_lost"

# T-A2 代号化闸①第①层：词典机制性故障（种子缺失/格式坏）不可重试也不可放行——
# 放行等于把「企业名可能漏替换」的文件直接送进模型与库，违反代号化红线。
# 文案指引售前联系管理员补词典，而不是「请重试」。
DICT_FAILURE_CODE = "pseudonym_dict_unavailable"
DICT_FAILURE_MESSAGE = "企业名词典不可用，为守住「客户名不入库」红线已阻断本次分析，请联系管理员修复词典配置。"

# T-A2 复核事件类型：疑似企业名清单落 operation_events（B#9 事实链三源之一），
# 方案审核人 confirm 前可从执行事实页看到本次分析替换/疑似了哪些名字。
REDACTION_EVENT_TYPE = "guidance.redaction_review"


def _project_code(session: Session, project_id: str) -> str:
    """enterprise_code（三段式「客户A·行业·城市」）作为替换目标代号；取不到回退空。"""
    return session.scalar(select(Project.enterprise_code).where(Project.id == project_id)) or ""


def _redact_content(content: str, *, project_code: str) -> tuple[str, list[dict[str, Any]]]:
    """进模型前的企业名替换：词典命中→代号；疑似（正则命中未收录）→同样替换并复核。

    返回（替换后全文, 复核条目列表）。复核条目只含名字与出现次数——不含上下文
    原句（上下文可能携带手机号等已脱敏内容，没必要二次复制）。
    """
    result = redact_text_detailed(content, project_code=project_code)
    entries = [
        {"name": suspect.name, "occurrences": suspect.occurrences, "matched_dict": False}
        for suspect in result.suspects
    ]
    for name in result.replaced:
        entries.append({"name": name, "occurrences": 1, "matched_dict": True})
    return result.text, entries


def _write_redaction_event(
    session: Session, analysis: ProjectGuidanceAnalysis, entries: list[dict[str, Any]], actor_id: str
) -> None:
    if not entries:
        return
    session.add(
        OperationEvent(
            actor_user_id=actor_id,
            project_id=analysis.project_id,
            target_type="project_guidance_analysis",
            target_id=analysis.id,
            event_type=REDACTION_EVENT_TYPE,
            changes={"entries": entries},
        )
    )


def handle_presurvey_analysis(job) -> None:
    session = db.session()
    try:
        analysis = session.get(ProjectGuidanceAnalysis, job.target_id)
        # 终态直接跳过：同一目标的重复投递不得二次调用 AI 覆盖已有结论。
        if analysis is None or analysis.analysis_state in {"ready", "cancelled", "failed"}:
            return
        analysis.analysis_state = "extracting"
        session.commit()
        version = session.get(ProjectFileVersion, analysis.source_file_version_id)
        if version is None:
            _fail(session, analysis, "source_missing", "预调研源文件不存在。")
            return
        analysis.analysis_state = "analyzing"
        session.commit()
        settings = current_app.config["SETTINGS"]
        client = KimiFileClient(
            base_url=settings.kimi_base_url,
            api_key=settings.kimi_project_presurvey_api_key,
            model=settings.kimi_project_presurvey_model,
            timeout_seconds=settings.kimi_timeout_seconds,
            local_extract=settings.kimi_local_docx_extract,
            openai_compatible=settings.kimi_openai_compatible,
        )
        source_ref = f"kimi-file:{analysis.source_file_version_id}"
        project_code = _project_code(session, analysis.project_id)
        redaction_entries: list[dict[str, Any]] = []
        attempts = 0
        while True:
            attempts += 1
            try:
                # 每次尝试重新开流：上一次尝试已消费/关闭了流。
                with object_storage.current.open_stream(version.storage_key) as stream:
                    payload = client.analyze_docx_json(
                        stream=stream,
                        filename=analysis.source_filename,
                        # 每次尝试一个独立请求号：上游若按请求号去重，
                        # 复用同一个 id 会让第二次拿回第一次的坏结果。
                        request_id=f"{job.id}:{attempts}",
                        # T-A2：全文进模型前先过企业名替换（词典命中→代号；
                        # 疑似→同样替换）。docx 全文在本地抽取腿里不落任何存储，
                        # 这里是它接触外界的唯一出口，必须在此完成代号化。
                        build_messages=lambda content: build_kimi_presurvey_analysis_messages(
                            _redact_and_build(content, project_code=project_code, sink=redaction_entries),
                            source_ref,
                        ),
                    )
                draft = validate_guidance_output(payload, source_refs={source_ref})
                break
            except KimiError as error:
                # 只有可重试错误（限流/超时/偶发畸形输出）才消耗重试额度；
                # ai_service_not_configured 这类配置问题重试也不会好。
                # 重试会重新走 build_messages → sink 已累积上一轮条目，先清空
                # 防复核清单重复计数（输入替换每轮都是全量重做）。
                redaction_entries.clear()
                if not error.retryable or attempts > GUIDANCE_ANALYSIS_RETRY_LIMIT:
                    _safe_fail(
                        session, job.target_id, error.code,
                        # 只有终态错误本身可重试时，「请重新发起分析」才是对的
                        # 建议：配置类/认证类失败重试无意义，原文照传。
                        _exhausted_message(error.public_message, attempts, retryable=error.retryable),
                    )
                    return
                _backoff_before_retry(error)
            except RedactionConfigError:
                # T-A2 闸①第①层：词典机制性故障 → fail-closed 硬阻断（不重试）。
                _safe_fail(session, job.target_id, DICT_FAILURE_CODE, DICT_FAILURE_MESSAGE)
                return
            except StorageNotFoundError:
                # 存储对象已被删除：确定性故障，重试无用，但必须单独分类。
                _safe_fail(
                    session, job.target_id, SOURCE_OBJECT_MISSING_CODE,
                    "预调研源文件已不存在，请重新上传后再发起分析。",
                )
                return
            except GuidanceContractError as error:
                if attempts > GUIDANCE_ANALYSIS_RETRY_LIMIT:
                    logger.warning(
                        "guidance contract violation not recovered (%s at %s)",
                        error.code, error.path,
                    )
                    _safe_fail(
                        session, job.target_id, "ai_output_invalid",
                        _exhausted_message("AI 返回的项目指引格式不正确。", attempts, retryable=True),
                    )
                    return
                # 契约失败是概率性问题，立即重试（退避只会白白拉长等待）。
        # T-A2 兜底层：模型输出可能回显企业名（输入替换拦不住输出端）。
        # 只对文本与 JSON 字段值做替换；evidence 结构不动（source_ref 校验
        # 已由 validate_guidance_output 保证）。
        project_code = project_code or _project_code(session, analysis.project_id)
        draft = _redact_draft_payload(draft, project_code=project_code, sink=redaction_entries)
        analysis.customer_vision = draft["customer_vision"]
        analysis.current_phase_objective = draft["current_phase_objective"]
        analysis.executive_summary = draft["executive_summary"]
        analysis.evidence_json = draft["evidence"]
        for field in LIST_FIELDS:
            setattr(analysis, f"{field}_json", draft[field])
        analysis.ai_model = settings.kimi_project_presurvey_model
        analysis.ai_generated_at = datetime.now(UTC)
        analysis.analysis_state = "ready"
        analysis.failure_code = ""
        analysis.failure_message = ""
        analysis.version += 1
        # T-A2 复核清单落 operation_events（B#9 事实链可查）；actor=分析创建人
        _write_redaction_event(session, analysis, redaction_entries, analysis.created_by_user_id)
        # O-3（goal-d7）：一次预调研分析 = 一次 ai_chat 动作，成功就绪时计
        # （失败/重试不计）；seat 归集 = 分析创建人；超额只标注不拦截
        record_seat_action(
            session,
            project_id=analysis.project_id,
            user_id=analysis.created_by_user_id,
            action_type="ai_chat",
            ref_id=analysis.id,
            quota_monthly=int(getattr(settings, "seat_action_quota_monthly", 100) or 0),
        )
        session.commit()
    except Exception as error:  # noqa: BLE001 - 分析绝不能卡在 analyzing 态
        # 只记录异常类型：异常串可能携带用户文档内容，不进日志。
        logger.warning("presurvey analysis unexpected failure (%s)", type(error).__name__)
        _safe_fail(
            session, job.target_id, UNEXPECTED_FAILURE_CODE,
            "分析过程出现未预期错误，请重试；若持续失败请检查文件后重新发起分析。",
        )
    finally:
        session.close()


def _redact_and_build(content: str, *, project_code: str, sink: list[dict[str, Any]]) -> str:
    """build_messages 适配：替换全文并把复核条目累积进 sink。"""
    redacted, entries = _redact_content(content, project_code=project_code)
    sink.extend(entries)
    return redacted


def _redact_draft_payload(
    draft: dict[str, Any], *, project_code: str, sink: list[dict[str, Any]]
) -> dict[str, Any]:
    """落库前对模型输出做企业名兜底替换。

    - 文本字段（customer_vision / current_phase_objective / executive_summary）
      直接替换；
    - LIST_FIELDS 各项为 list[dict]，对其中每个 str 值递归替换；
    - evidence_json 只处理其 value 里的 str 值（键是内部 ref 结构不碰）。
    替换命中继续累积进 sink（matched_dict 按「词典兜底命中」计）。
    """
    names = enterprise_names()
    if not names:
        return draft

    def replace_str(value: str) -> str:
        hits: list[str] = []
        text = value
        for name in names:
            if name in text:
                text = text.replace(name, project_code or "客户代号")
                hits.append(name)
        if hits:
            sink.extend({"name": h, "occurrences": 1, "matched_dict": True} for h in hits)
        return text

    out = dict(draft)
    for key in ("customer_vision", "current_phase_objective", "executive_summary"):
        out[key] = replace_str(out.get(key, "") or "")
    for field in LIST_FIELDS:
        items = out.get(field)
        if isinstance(items, list):
            out[field] = [
                {k: replace_str(v) if isinstance(v, str) else v for k, v in item.items()}
                if isinstance(item, dict) else item
                for item in items
            ]
    evidence = out.get("evidence")
    if isinstance(evidence, dict):
        out["evidence"] = {k: replace_str(v) if isinstance(v, str) else v for k, v in evidence.items()}
    return out


def _exhausted_message(public_message: str, attempts: int, *, retryable: bool = True) -> str:
    """重试耗尽后的用户可见文案。

    retryable=False 时不加「请重新发起分析」：配置/认证类失败重试无意义，
    让用户重新发起只会得到同一个失败。
    """
    retries = attempts - 1
    if retries <= 0:
        return public_message
    if not retryable:
        return f"{public_message}（已自动重试 {retries} 次仍失败）"
    return f"{public_message}（已自动重试 {retries} 次仍失败，请重新发起分析）"


def _backoff_before_retry(error: KimiError) -> None:
    """限流/超时类瞬时错误重试前短暂退避。

    契约违反（ai_output_invalid）不走这里——那是概率性问题，立即重试更合适。
    """
    if error.code not in TRANSIENT_RETRY_CODES:
        return
    time.sleep(RETRY_BACKOFF_SECONDS)


def _safe_fail(session, analysis_id: str, code: str, message: str) -> None:
    session.rollback()
    row = session.get(ProjectGuidanceAnalysis, analysis_id)
    if row is not None:
        _fail(session, row, code, message)


def _fail(session, row: ProjectGuidanceAnalysis, code: str, message: str) -> None:
    row.analysis_state = "failed"
    row.failure_code = code
    row.failure_message = message
    row.version += 1
    session.commit()


def register_presurvey_analysis_handler() -> None:
    register_handler("project.presurvey.analyze", handle_presurvey_analysis)


def fail_analysis_on_worker_loss(session, job) -> None:
    """Close out an analysis whose worker died mid-flight.

    The analysis row is what the UI polls; leaving it in ``extracting`` or
    ``analyzing`` means an endless poll for a result nobody will produce.
    """
    row = session.get(ProjectGuidanceAnalysis, job.target_id)
    if row is None or row.analysis_state in {"ready", "cancelled", "failed"}:
        return
    row.analysis_state = "failed"
    row.failure_code = WORKER_LOST_CODE
    row.failure_message = "分析进程中断（后台任务进程退出），请重新发起分析。"
    row.version += 1


def register_presurvey_analysis_failure_handler() -> None:
    register_job_failure_handler("project.presurvey.analyze", fail_analysis_on_worker_loss)
