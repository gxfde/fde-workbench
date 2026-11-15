"""discovery 事实 → 结构化候选 → 直提 POST /change-sets（WP4④ / D17）。

fail-closed 纪律：
- 关闭面 ⇒ 404（``ensure_enabled``，D12/D13）；
- 项目不存在 / 无访问权 ⇒ 404（S-01 不泄露存在性）；无管理权 ⇒ 403；
- 项目无 org 归属 ⇒ 409 ``project_org_missing``（D10/D15）；
- 源文本加载严格钉死 ``row.project_id == project_id``（§15 跨项目隔离）；
  墓碑态 ``TranscriptDraft``（``content is None``）不作为可切片源；
- 无可直提候选 ⇒ 400 ``no_pushable_candidates``（**不建空 change-set**）；
- 本地校验全过之后才发生出站调用（零副作用前置）；
- 候选只取**人工审阅定案**的事实，且 ``evidence_quote`` 必须逐字原文（D17）；
- 出站成功落 ``operation_events``（§15 写操作必须有审计）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.discovery.models import BusinessFact
from fde_api.extensions import db
from fde_api.integrations.candidates import build_candidates
from fde_api.integrations.ontology_client import (
    OntologyAuthError,
    OntologyClientError,
    OntologyConflict,
    OntologyUnavailable,
)
from fde_api.integrations.service import (
    BindingError,
    _load_accessible_project,
    _project_org,
    client_from_settings,
    ensure_enabled,
)
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access
from fde_api.transcripts.models import InterviewMinutes, TranscriptDraft


def _load_source_texts(
    session: Any, project_id: str, source_refs: set[str]
) -> dict[str, str]:
    """按 source_ref（``"<source_type>:<id>"``）取本项目原文正文（只读指针，不落库）。"""
    texts: dict[str, str] = {}
    for ref in sorted(source_refs):
        source_type, _, ident = ref.partition(":")
        if not ident:
            continue
        row: InterviewMinutes | TranscriptDraft | None
        if source_type == "interview_minutes":
            row = session.get(InterviewMinutes, ident)
        elif source_type == "transcript_draft":
            row = session.get(TranscriptDraft, ident)
        else:
            continue
        if row is None or row.project_id != project_id:
            continue
        content = getattr(row, "content", None)
        if isinstance(content, str) and content:
            texts[ref] = content
    return texts


def _invoke_submit_candidates(
    client: Any,
    *,
    actor_id: str,
    org_id: str,
    project_id: str,
    ontology_id: str,
    extraction_id: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        result = client.submit_candidates(
            actor_id=actor_id,
            org_id=org_id,
            project_id=project_id,
            ontology_id=ontology_id,
            title=f"discovery:{extraction_id}",
            items=items,
            captured_from=f"discovery:{extraction_id}",
            description="Workbench discovery 抽取并经人工审阅定案的候选",
        )
    except OntologyUnavailable as exc:
        raise BindingError(
            f"ontology runtime unreachable: {exc}",
            status=503,
            code="ontology_unavailable",
        ) from exc
    except OntologyAuthError as exc:
        raise BindingError(
            "ontology runtime rejected credentials (check FDE_ONTOLOGY_* config)",
            status=502,
            code="runtime_auth",
        ) from exc
    except OntologyConflict as exc:
        raise BindingError(
            "ontology runtime reported a conflict while submitting candidates",
            status=409,
            code="runtime_conflict",
        ) from exc
    except OntologyClientError as exc:
        raise BindingError(
            f"ontology runtime failure: {exc}",
            status=502,
            code="runtime_error",
        ) from exc

    status = int(result.get("_status", 201))
    if status == 404:
        raise BindingError(
            "ontology not found on runtime",
            status=404,
            code="ontology_not_found",
        )
    if status == 422:
        raise BindingError(
            "ontology runtime rejected candidate payload",
            status=422,
            code="candidate_validation_failed",
        )
    if status not in (200, 201):
        raise BindingError(
            f"unexpected ontology runtime status {status}",
            status=502,
            code="runtime_error",
        )
    return result


def submit_discovery_candidates(
    actor: User,
    project_id: str,
    *,
    ontology_id: str,
    extraction_id: str,
) -> dict[str, Any]:
    """discovery 输出 → 六件套候选 → 直提 POST /change-sets（WP4④ / D17）。"""
    ensure_enabled()
    session = db.session()
    project = _load_accessible_project(session, actor, project_id)
    if not project_access(actor, project).can_manage:
        raise BindingError("forbidden", status=403, code="forbidden")
    org_id = _project_org(project)
    facts = list(
        session.execute(
            select(BusinessFact).where(
                BusinessFact.project_id == project_id,
                BusinessFact.extraction_id == extraction_id,
            )
        ).scalars()
    )
    if not facts:
        raise BindingError(
            "no discovery facts for this extraction", status=404, code="facts_not_found"
        )
    source_refs = {str(fact.source_ref) for fact in facts if fact.source_ref}
    build = build_candidates(
        facts=facts,
        source_texts=_load_source_texts(session, project_id, source_refs),
    )
    if not build.items:
        raise BindingError(
            "no pushable candidates (no accepted fact with a restorable evidence quote)",
            status=400,
            code="no_pushable_candidates",
        )
    client = client_from_settings()
    result = _invoke_submit_candidates(
        client,
        actor_id=str(actor.id),
        org_id=org_id,
        project_id=project_id,
        ontology_id=ontology_id,
        extraction_id=extraction_id,
        items=build.items,
    )
    change_set_id = result.get("id")
    record_event(
        session,
        actor,
        "ontology_candidates_submitted",
        project,
        {
            "ontology_id": ontology_id,
            "extraction_id": extraction_id,
            "change_set_id": change_set_id,
            "item_count": len(build.items),
            "skipped_count": len(build.skipped),
        },
    )
    session.commit()
    return {
        "change_set_id": change_set_id,
        "status": result.get("status"),
        "item_count": len(build.items),
        "skipped": build.skipped,
        "unresolved_questions": build.unresolved_questions,
    }
