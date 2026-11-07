"""transcripts 服务：T-A9 草稿区承接 + T+7 清理 + 人工整理晋升（goal-tb tb1）。

红线落点（立项文档 §1/§4）：
- **只收文本不收音频**：录音原件永不进 repo/DB/远端——API 载荷是文本，
  无任何音频字段；引擎字段只是宿主侧来源标注。
- **T-A2 代号化不豁免**：create/promote 两处 title/content/确认人文本先过
  ``redact_text_detailed``（词典不可用 fail-closed 硬阻断，沿 guidance 同码）。
- **物理隔离**：草稿正文落独立文件根 + 独立表；正式库（interview_minutes）
  只持草稿指针（draft_id 无 FK）；「草稿不可被正式库引用」由 models 元数据
  零外键 + 测试钉死。
- **晋升三要素**：确认人（代号化文本）/时间戳（拒绝未来时戳，CR-029 教训）/
  确认方式（封闭枚举）缺一即 422，无客户确认的转写文本无法进正式库。
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import UTC, datetime, timedelta
from typing import Any

from flask import current_app
from sqlalchemy import select

from fde_api.guidance import enterprise_dict
from fde_api.guidance.enterprise_dict import RedactionConfigError
from fde_api.guidance.redaction import redact_text_detailed
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access, visible_project_ids
from fde_api.transcripts.models import (
    CONFIRMATION_METHODS,
    DRAFT_STATUSES,
    SOURCE_KINDS,
    InterviewMinutes,
    TranscriptDraft,
)
from fde_api.workbench.models import Project, User
from fde_api.extensions import db

MAX_DRAFT_CHARS = 100_000
MAX_TITLE_CHARS = 200
MAX_CONFIRMED_BY_CHARS = 160
MAX_ENGINE_CHARS = 60
_LIST_LIMIT_DEFAULT = 50
_LIST_LIMIT_MAX = 200


class TranscriptsServiceError(Exception):
    def __init__(self, code: str, message: str, status: int, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.detail = detail or {}


def _error(code: str, message: str, status: int = 400, detail: dict[str, Any] | None = None) -> TranscriptsServiceError:
    return TranscriptsServiceError(code, message, status, detail)


def _session() -> Any:
    return db.session()


def _settings():
    return current_app.config["SETTINGS"]


# ---------------------------------------------------------------------------
# T-A2 代号化（与 guidance/_redact_content 同形状；fail-closed 同码）


def _redact_text(value: str, *, project_code: str) -> tuple[str, list[dict[str, Any]]]:
    """进库前的企业名替换：词典命中→代号；疑似（正则命中未收录）→同样替换。

    返回（替换后全文, 复核条目）。条目只含名字与出现次数，不含上下文原句
    （与 guidance 同纪律）。词典不可用 → RedactionConfigError 由调用方
    fail-closed 转特定错误码（不因「草稿」豁免——SOP :109/:111 红线）。
    """
    result = redact_text_detailed(value, project_code=project_code)
    entries = [
        {"name": suspect.name, "occurrences": suspect.occurrences, "matched_dict": False}
        for suspect in result.suspects
    ]
    entries.extend({"name": name, "occurrences": 1, "matched_dict": True} for name in result.replaced)
    return result.text, entries


def _redact_or_block(value: str, *, project_code: str) -> tuple[str, list[dict[str, Any]]]:
    try:
        return _redact_text(value, project_code=project_code)
    except RedactionConfigError:
        raise _error(
            enterprise_dict.DICT_FAILURE_CODE,
            "企业名词典不可用，为守住「客户名不入库」红线已阻断本次写入，请联系管理员修复词典配置。",
            503,
        ) from None


def _project_code(session: Any, project_id: str) -> str:
    """enterprise_code（三段式「客户A·行业·城市」）作为替换目标代号；取不到回退空。"""
    return session.scalar(select(Project.enterprise_code).where(Project.id == project_id)) or ""


# ---------------------------------------------------------------------------
# 草稿独立文件根（物理隔离：与 .fde-storage 上传存储不共根）


def _draft_dir(draft_id: str, settings=None):
    root = (settings or _settings()).transcript_draft_root
    return root / draft_id


def _write_draft_file(draft_id: str, content: str) -> None:
    directory = _draft_dir(draft_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "transcript.txt").write_text(content, encoding="utf-8")


def _remove_draft_dir(draft_id: str, settings=None) -> None:
    shutil.rmtree(_draft_dir(draft_id, settings), ignore_errors=True)


# ---------------------------------------------------------------------------
# 校验


def _require_str(payload: dict[str, Any], key: str, *, required: bool, max_len: int, code: str) -> str | None:
    value = payload.get(key)
    if value is None:
        if required:
            raise _error(code, f"{key} 必填。", 422)
        return None
    if not isinstance(value, str) or not value.strip():
        raise _error(code, f"{key} 必须是非空字符串。", 422)
    if len(value) > max_len:
        raise _error(code, f"{key} 超长（上限 {max_len} 字符）。", 422, {"limit": max_len})
    return value


def _parse_confirmed_at(payload: dict[str, Any], *, now: datetime) -> datetime:
    raw = payload.get("client_confirmed_at")
    if not isinstance(raw, str) or not raw.strip():
        raise _error("invalid_confirmation", "client_confirmed_at 必填（客户确认时间戳）。", 422)
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise _error("invalid_confirmation", "client_confirmed_at 不是合法的 ISO 8601 时间戳。", 422) from None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(UTC)
    if value > now + timedelta(minutes=5):
        # CR-029 教训：拒绝未来时戳（允许 5 分钟时钟偏移）
        raise _error("invalid_confirmation", "客户确认时间戳不能晚于当前时间。", 422)
    return value


def _validate_confirmation_triple(payload: dict[str, Any], *, now: datetime) -> tuple[str, datetime, str]:
    confirmed_by = _require_str(
        payload, "client_confirmed_by", required=True, max_len=MAX_CONFIRMED_BY_CHARS, code="invalid_confirmation"
    )
    assert confirmed_by is not None  # required=True 保非空；mypy 收窄
    confirmed_at = _parse_confirmed_at(payload, now=now)
    method = payload.get("client_confirmation_method")
    if method not in CONFIRMATION_METHODS:
        raise _error(
            "invalid_confirmation",
            f"client_confirmation_method 必须是 {'/'.join(CONFIRMATION_METHODS)} 之一（客户确认方式三要素）。",
            422,
        )
    return confirmed_by, confirmed_at, method


# ---------------------------------------------------------------------------
# 项目装载与权限（meetings 同构：404 未知名 / 403 越权）


def _load_project_for(session: Any, actor: User, project_id: str, *, manage: bool) -> Project:
    project = session.get(Project, project_id)
    access = project_access(actor, project) if project else None
    if project is None or access is None:
        raise _error("project_not_found", "项目不存在或无权访问。", 404)
    if manage and not access.can_manage:
        raise _error("project_forbidden", "需要项目管理权限。", 403)
    if not manage and not access.can_view:
        raise _error("project_forbidden", "无权访问该项目。", 403)
    return project


def _load_draft_for(session: Any, actor: User, draft_id: str, *, manage: bool) -> tuple[TranscriptDraft, Project]:
    draft = session.get(TranscriptDraft, draft_id)
    if draft is None:
        raise _error("draft_not_found", "转写草稿不存在。", 404)
    project = _load_project_for(session, actor, draft.project_id, manage=manage)
    return draft, project


# ---------------------------------------------------------------------------
# 序列化


def _serialize_draft(row: TranscriptDraft, *, detail: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "status": row.status,
        "source_kind": row.source_kind,
        "engine": row.engine,
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at.isoformat(),
        "expires_at": row.expires_at.isoformat(),
        "cleaned_at": row.cleaned_at.isoformat() if row.cleaned_at else None,
        "client_confirmed_by": row.client_confirmed_by,
        "client_confirmed_at": row.client_confirmed_at.isoformat() if row.client_confirmed_at else None,
        "client_confirmation_method": row.client_confirmation_method,
        "promoted_ref": row.promoted_ref,
    }
    if detail and row.status == "draft":
        # 正文与复核条目只在活动草稿详情出现（墓碑无正文可回放——T+7 语义）
        data["content"] = row.content
        data["content_sha256"] = row.content_sha256
        data["redaction_entries"] = row.redaction_entries or []
    return data


def _serialize_minutes(row: InterviewMinutes, *, detail: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "draft_id": row.draft_id,
        "redaction_hits": row.redaction_hits,
        "client_confirmed_by": row.client_confirmed_by,
        "client_confirmed_at": row.client_confirmed_at.isoformat(),
        "client_confirmation_method": row.client_confirmation_method,
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at.isoformat(),
    }
    if detail:
        data["content"] = row.content
        data["content_sha256"] = row.content_sha256
    return data


# ---------------------------------------------------------------------------
# 草稿区


def create_draft(*, actor: User, payload: dict[str, Any]) -> dict[str, Any]:
    session = _session()
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise _error("invalid_request", "project_id 必填。", 400)
    content = _require_str(payload, "content", required=True, max_len=MAX_DRAFT_CHARS, code="invalid_draft")
    title = _require_str(payload, "title", required=False, max_len=MAX_TITLE_CHARS, code="invalid_draft")
    source_kind = payload.get("source_kind", "manual")
    if source_kind not in SOURCE_KINDS:
        raise _error("invalid_draft", f"source_kind 必须是 {'/'.join(SOURCE_KINDS)} 之一。", 422)
    engine = payload.get("engine")
    if source_kind == "asr":
        if not isinstance(engine, str) or not engine.strip():
            raise _error("invalid_draft", "asr 来源必须标注引擎（engine）。", 422)
        engine = engine.strip()[:MAX_ENGINE_CHARS]
    elif engine is not None:
        raise _error("invalid_draft", "manual 来源不带 engine 标注。", 422)

    now = datetime.now(UTC)
    with session.begin():
        project = _load_project_for(session, actor, project_id, manage=False)
        code = _project_code(session, project.id)
        assert content is not None  # required=True 保非空；mypy 收窄
        redacted_content, entries = _redact_or_block(content, project_code=code)
        redacted_title = ""
        title_entries: list[dict[str, Any]] = []
        if title:
            redacted_title, title_entries = _redact_or_block(title, project_code=code)
        entries = list(entries) + list(title_entries)
        draft = TranscriptDraft(
            project_id=project.id,
            created_by_user_id=actor.id,
            title=redacted_title or None,
            content=redacted_content,
            content_sha256=hashlib.sha256(redacted_content.encode("utf-8")).hexdigest(),
            redaction_entries=entries,
            source_kind=source_kind,
            engine=engine,
            status="draft",
            expires_at=now + timedelta(days=_settings().transcript_draft_retention_days),
        )
        session.add(draft)
        session.flush()
        _write_draft_file(draft.id, redacted_content)
        record_event(session, actor, "transcript_draft_created", project, {
            "draft_id": draft.id,
            "source_kind": source_kind,
            "engine": engine,
            "redaction_hits": len(entries),
            "expires_at": draft.expires_at.isoformat(),
        })
        return _serialize_draft(draft, detail=True)


def list_drafts(
    *, actor: User, project_id: str | None, status: str | None, limit: int, offset: int
) -> dict[str, Any]:
    session = _session()
    if status is not None and status not in DRAFT_STATUSES:
        raise _error("invalid_request", "status 不是合法的草稿状态。", 400)
    rows_query = select(TranscriptDraft).order_by(TranscriptDraft.created_at.desc(), TranscriptDraft.id)
    if project_id is not None:
        project = _load_project_for(session, actor, project_id, manage=False)
        rows_query = rows_query.where(TranscriptDraft.project_id == project.id)
    else:
        visible = visible_project_ids(session, actor)
        if not visible:
            return {"items": [], "total": None, "limit": limit, "offset": offset, "truncated": False}
        rows_query = rows_query.where(TranscriptDraft.project_id.in_(visible))
    if status is not None:
        rows_query = rows_query.where(TranscriptDraft.status == status)
    rows = list(session.scalars(rows_query.offset(offset).limit(limit + 1)))
    truncated = len(rows) > limit
    return {
        "items": [_serialize_draft(row, detail=False) for row in rows[:limit]],
        "total": None,
        "limit": limit,
        "offset": offset,
        "truncated": truncated,
    }


def get_draft(*, actor: User, draft_id: str) -> dict[str, Any]:
    session = _session()
    with session.begin():
        draft, _project = _load_draft_for(session, actor, draft_id, manage=False)
        return _serialize_draft(draft, detail=True)


def discard_draft(*, actor: User, draft_id: str) -> dict[str, Any]:
    session = _session()
    now = datetime.now(UTC)
    with session.begin():
        draft, project = _load_draft_for(session, actor, draft_id, manage=False)
        if draft.status != "draft":
            raise _error("draft_not_active", "只有活动草稿可弃置。", 409)
        draft.status = "discarded"
        draft.content = None
        draft.content_sha256 = None
        draft.redaction_entries = None
        draft.cleaned_at = now
        _remove_draft_dir(draft.id)
        record_event(session, actor, "transcript_draft_discarded", project, {"draft_id": draft.id})
        return _serialize_draft(draft, detail=True)


def promote_draft(*, actor: User, draft_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """晋升：人工整理稿 + 客户确认三要素 → interview_minutes 正式库。

    草稿正文随晋升抹除（墓碑 + 指针），文件根子树一并删除——草稿区是
    T+7 临时区，晋升后的正文本体住在正式库，不双份留存在草稿侧。
    """
    session = _session()
    now = datetime.now(UTC)
    with session.begin():
        draft, project = _load_draft_for(session, actor, draft_id, manage=True)
        if draft.status != "draft":
            raise _error("draft_not_active", "只有活动草稿可晋升。", 409)
        title = _require_str(payload, "title", required=True, max_len=MAX_TITLE_CHARS, code="invalid_minutes")
        content = _require_str(payload, "content", required=True, max_len=MAX_DRAFT_CHARS, code="invalid_minutes")
        assert title is not None and content is not None  # required=True 保非空；mypy 收窄
        confirmed_by, confirmed_at, method = _validate_confirmation_triple(payload, now=now)

        code = _project_code(session, project.id)
        redacted_title, title_entries = _redact_or_block(title, project_code=code)
        redacted_content, entries = _redact_or_block(content, project_code=code)
        hits = len(entries) + len(title_entries)

        minutes = InterviewMinutes(
            project_id=project.id,
            created_by_user_id=actor.id,
            draft_id=draft.id,
            title=redacted_title,
            content=redacted_content,
            content_sha256=hashlib.sha256(redacted_content.encode("utf-8")).hexdigest(),
            redaction_hits=hits,
            client_confirmed_by=confirmed_by,
            client_confirmed_at=confirmed_at,
            client_confirmation_method=method,
        )
        session.add(minutes)
        session.flush()
        draft.status = "promoted"
        draft.content = None
        draft.content_sha256 = None
        draft.redaction_entries = None
        draft.client_confirmed_by = confirmed_by
        draft.client_confirmed_at = confirmed_at
        draft.client_confirmation_method = method
        draft.promoted_ref = f"interview_minutes:{minutes.id}"
        draft.cleaned_at = now
        _remove_draft_dir(draft.id)
        record_event(session, actor, "transcript_draft_promoted", project, {
            "draft_id": draft.id,
            "minutes_id": minutes.id,
            "redaction_hits": hits,
        })
        record_event(session, actor, "interview_minutes_created", project, {
            "minutes_id": minutes.id,
            "draft_id": draft.id,
            "confirmation_method": method,
        })
        return {"draft": _serialize_draft(draft, detail=True), "minutes": _serialize_minutes(minutes, detail=True)}


def purge_expired_drafts(*, now: datetime | None = None, limit: int = 100, settings=None) -> int:
    """T+7 自动清理（cli scheduler 同拍）：到期活动草稿 → expired 墓碑 + 文件根清空。

    系统动作不落 OperationEvent（无 actor）；墓碑行本身即 T+7 合规对账凭据。
    skip_locked 与并发读写互不阻塞。settings 注入参供调度外调用方（测试）显式
    指定文件根——不传时读 current_app（flask cli 命令天然持有 app 上下文）。
    """
    current = (now or datetime.now(UTC)).astimezone(UTC)
    session = _session()
    purged = 0
    try:
        with session.begin():
            drafts = list(session.scalars(
                select(TranscriptDraft)
                .where(TranscriptDraft.status == "draft", TranscriptDraft.expires_at <= current)
                .order_by(TranscriptDraft.expires_at, TranscriptDraft.id)
                .with_for_update(skip_locked=True)
                .limit(limit)
            ))
            for draft in drafts:
                draft.status = "expired"
                draft.content = None
                draft.content_sha256 = None
                draft.redaction_entries = None
                draft.cleaned_at = current
                _remove_draft_dir(draft.id, settings)
            purged = len(drafts)
            return purged
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 访谈纪要正式库


def list_minutes(
    *, actor: User, project_id: str | None, limit: int, offset: int
) -> dict[str, Any]:
    session = _session()
    rows_query = select(InterviewMinutes).order_by(InterviewMinutes.created_at.desc(), InterviewMinutes.id)
    if project_id is not None:
        project = _load_project_for(session, actor, project_id, manage=False)
        rows_query = rows_query.where(InterviewMinutes.project_id == project.id)
    else:
        visible = visible_project_ids(session, actor)
        if not visible:
            return {"items": [], "total": None, "limit": limit, "offset": offset, "truncated": False}
        rows_query = rows_query.where(InterviewMinutes.project_id.in_(visible))
    rows = list(session.scalars(rows_query.offset(offset).limit(limit + 1)))
    truncated = len(rows) > limit
    return {
        "items": [_serialize_minutes(row, detail=False) for row in rows[:limit]],
        "total": None,
        "limit": limit,
        "offset": offset,
        "truncated": truncated,
    }


def get_minutes(*, actor: User, minutes_id: str) -> dict[str, Any]:
    session = _session()
    with session.begin():
        row = session.get(InterviewMinutes, minutes_id)
        if row is None:
            raise _error("minutes_not_found", "访谈纪要不存在。", 404)
        _load_project_for(session, actor, row.project_id, manage=False)
        return _serialize_minutes(row, detail=True)
