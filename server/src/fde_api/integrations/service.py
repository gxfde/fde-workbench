"""项目本体绑定服务（V3.3 WP4 段 1）。

职责：绑定 CRUD + 升级留痕状态机 + 与 ontology-service 的一致性校验
（pinned_version_id 必须是 runtime 上真实存在的已发布版本，I5——draft 不可
被生产 Agent/Workflow 使用）。runtime 不可达 → 拒绝写（契约 §3：降级不降
红线，绑定是交付控制面写操作）。

评审加固（Fde-Ontology docs/v3.3/m2/02-code-review-workbench-2026-11-13.md）：
- W-C：全部端点项目访问控制（project_access.can_view；不存在/无权 → 404，
  S-01 不泄露存在性）；
- W-B/D10：I5 调用发 org 上下文 + 真实 project_id（段 2 起 org = 项目归属
  projects.org_id；段 1 的 FDE_ONTOLOGY_ORG_ID 配置已退役——租户身份不得
  来自外部配置，§15 红线）；
  approve 时对目标版本**再次** I5 复核（propose→approve 间版本可能下架；
  兼修"审批不触 runtime"的写不降级违约）；
- W-D：错误分型契约——runtime 404 → 409 version_not_published（spec：draft
  409）、401/403 → 502 runtime_auth（配置错误不伪装领域错误）；
- W-A/E：单活跃绑定（active_marker uq）+ upgrade_pending 生命周期 + retire 后
  可重绑 + 并发行锁 + 不泄内部异常文本。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from flask import current_app
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from fde_api.auth.models import User
from fde_api.errors import NOT_FOUND_MESSAGE
from fde_api.evidence.service import upsert_evidence
from fde_api.extensions import db
from fde_api.integrations.models import (
    ACTIVE_MARKER,
    OntologyBindingUpgrade,
    ProjectOntologyBinding,
)
from fde_api.integrations.ontology_client import (
    OntologyAuthError,
    OntologyClient,
    OntologyClientError,
    OntologyConflict,
    OntologyUnavailable,
)
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access
from fde_api.workbench.models import Project

BINDING_ROLES = ("primary",)

# D16：批注回执的包 ID = 内容寻址 sha256（契约 §5：内容寻址，重复导出可检测）
_ANNOTATION_PACKAGE_ID = re.compile(r"^[0-9a-f]{64}$")
_ANNOTATION_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class BindingError(ValueError):
    """带 HTTP 状态的绑定业务错误。"""

    def __init__(self, message: str, status: int = 400, code: str = "binding_error") -> None:
        self.message = message
        self.status = status
        self.code = code
        super().__init__(message)


def ensure_enabled() -> None:
    """D12/D13：本体绑定面未启用 ⇒ 404（不确认面存在）。

    对齐主线 diagnostics_enabled 先例：蓝图无条件进 _BLUEPRINT_SPECS
    （蓝图注册表单一真身机器闸 P2-5），门控收敛在服务层——禁用面与
    不存在面不可区分，无存在性泄露；flag 关时不产生任何对本体运行时
    的出站调用（fail-closed，§15 红线）。

    D13：文案复用 `errors.NOT_FOUND_MESSAGE`——与「路径不存在」的全局 404
    信封**逐字节同形**（code/message/details 全同），未鉴权探针无法由
    响应差异反推该路径存在。
    """
    settings = current_app.config["SETTINGS"]
    if not getattr(settings, "ontology_enabled", False):
        raise BindingError(NOT_FOUND_MESSAGE, status=404, code="not_found")


def client_from_settings() -> OntologyClient:
    settings = current_app.config["SETTINGS"]
    assert settings.ontology_api_key is not None
    assert settings.ontology_signing_key is not None
    return OntologyClient(
        settings.ontology_base_url,
        settings.ontology_api_key.get_secret_value(),
        settings.ontology_signing_key.get_secret_value(),
        timeout=settings.ontology_timeout_seconds,
    )


def _validated_annotation(annotation: Mapping[str, Any]) -> dict[str, str | None]:
    """D16 批注回执入参校验（形状不合 ⇒ 400，零写入零出站）。

    契约（integration-contract §5 + data-model §162）：意见落 project_evidence，
    kind=ontology_annotation，captured_from=ontology_review:<package_id>；
    package_id 是内容寻址 sha256（64 hex）。
    """
    if not isinstance(annotation, Mapping):
        raise BindingError("annotation must be an object", code="invalid_request")
    package_id = str(annotation.get("review_package_id", "")).strip().lower()
    if not _ANNOTATION_PACKAGE_ID.fullmatch(package_id):
        raise BindingError(
            "annotation.review_package_id must be a 64-hex content address",
            code="invalid_request",
        )
    content_sha256 = str(annotation.get("content_sha256", "")).strip().lower()
    if not _ANNOTATION_SHA256.fullmatch(content_sha256):
        raise BindingError(
            "annotation.content_sha256 must be a 64-hex sha256",
            code="invalid_request",
        )
    source_uri = str(annotation.get("source_uri", "")).strip()
    if not 0 < len(source_uri) <= 500:
        raise BindingError(
            "annotation.source_uri must be a 1-500 character pointer",
            code="invalid_request",
        )
    origin = annotation.get("origin")
    if origin is not None:
        if not isinstance(origin, str) or len(origin) > 2000:
            raise BindingError(
                "annotation.origin must be a string of at most 2000 characters",
                code="invalid_request",
            )
        origin = origin.strip() or None
    return {
        "review_package_id": package_id,
        "content_sha256": content_sha256,
        "source_uri": source_uri,
        "origin": origin,
    }


def _record_annotation_receipt(
    session: Any, *, actor: User, project: Project, annotation: Mapping[str, Any]
) -> str:
    """D16：批注回执落 project_evidence（kind=ontology_annotation），返回证据行 id。

    幂等：指纹 (project_id, source_uri, content_sha256) 命中既有行则原样复用
    （证据不可变，不改写任何列）；新建行落审计事件（§15 写操作须审计）。
    """
    package_id = str(annotation["review_package_id"])
    row, created = upsert_evidence(
        session,
        project_id=project.id,
        kind="ontology_annotation",
        source_uri=str(annotation["source_uri"]),
        content_sha256=str(annotation["content_sha256"]),
        origin=annotation["origin"],
        captured_from=f"ontology_review:{package_id}",
        created_by_user_id=str(actor.id),
    )
    if created:
        record_event(
            session,
            actor,
            "evidence_registered",
            project,
            {
                "evidence_id": row.id,
                "kind": "ontology_annotation",
                "source_uri": str(annotation["source_uri"]),
                "content_sha256": str(annotation["content_sha256"]),
                "captured_from": f"ontology_review:{package_id}",
            },
        )
    return row.id


def _project_org(project: Project) -> str:
    """D10 段 2：I5 调用的 org 上下文 = **项目归属**（projects.org_id）。

    段 1 曾用 FDE_ONTOLOGY_ORG_ID 配置（orgs 轨道未合流时的唯一可用来源）；
    orgs 轨道合流后退役该配置——租户身份不得来自外部配置（§15 红线：不允许
    仅凭客户端/配置传来的租户身份就信任租户身份）。

    项目无 org 归属 ⇒ 409 project_org_missing（fail-closed）：判定发生在一切
    业务校验与**任何出站调用**之前——绑定面绝不以空 org 去打扰 runtime。
    """
    org_id = project.org_id
    if not org_id:
        raise BindingError(
            "project has no organization attribution (org_id is empty)",
            status=409,
            code="project_org_missing",
        )
    return org_id


def _verified_snapshot(
    client: OntologyClient,
    *,
    actor: User,
    org_id: str,
    ontology_id: str,
    version_id: str,
    project_id: str,
) -> dict[str, Any]:
    """I5：绑定仅指发布版本（draft 409；评审 W-D/W-B/D10）。"""
    try:
        body = client.get_version_snapshot(
            actor_id=str(actor.id),
            org_id=org_id,
            project_id=project_id,
            ontology_id=ontology_id,
            version_id=version_id,
        )
    except OntologyUnavailable as exc:
        raise BindingError(
            f"ontology runtime unreachable: {exc}", status=503, code="ontology_unavailable"
        ) from exc
    except OntologyAuthError as exc:
        # 配置错误（key 失效//org 错）必须显性暴露，不得伪装成领域错误
        raise BindingError(
            "ontology runtime rejected credentials (check FDE_ONTOLOGY_* config)",
            status=502,
            code="runtime_auth",
        ) from exc
    except OntologyConflict as exc:
        raise BindingError(
            "ontology runtime conflict during I5 verification",
            status=502,
            code="runtime_conflict",
        ) from exc
    except OntologyClientError as exc:
        raise BindingError(
            f"ontology runtime failure: {exc}", status=502, code="runtime_error"
        ) from exc
    status = body.pop("_status", 500)
    if status != 200:
        raise BindingError(
            "pinned_version_id is not a published version on the runtime (I5)",
            status=409,
            code="version_not_published",
        )
    return body


def _load_accessible_project(session: Any, actor: User, project_id: str) -> Project:
    """W-C/S-01：项目不存在或无 view 权 → 统一 404（不泄露存在性）。"""
    project = session.get(Project, project_id)
    if project is None or not project_access(actor, project).can_view:
        raise BindingError("project not found", status=404, code="not_found")
    return project


def _pending_upgrades(session: Any, binding_id: str) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(OntologyBindingUpgrade)
        .where(OntologyBindingUpgrade.binding_id == binding_id)
        .order_by(OntologyBindingUpgrade.created_at)
    ).all()
    return [u.snapshot() for u in rows]


def list_bindings(*, actor: User, project_id: str) -> list[dict[str, Any]]:
    ensure_enabled()
    session = db.session()
    _load_accessible_project(session, actor, project_id)
    bindings = session.scalars(
        select(ProjectOntologyBinding)
        .where(ProjectOntologyBinding.project_id == project_id)
        .order_by(ProjectOntologyBinding.created_at)
    ).all()
    out = []
    for b in bindings:
        item = b.snapshot()
        item["pending_upgrades"] = _pending_upgrades(session, b.id)  # 审批人发现入口（评审）
        out.append(item)
    return out


def create_binding(*, actor: User, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_enabled()
    ontology_id = str(payload.get("ontology_id", "")).strip()
    version_id = str(payload.get("pinned_version_id", "")).strip()
    if not ontology_id or not version_id:
        raise BindingError("ontology_id and pinned_version_id are required", code="invalid_request")
    binding_role = str(payload.get("binding_role", "primary"))
    if binding_role not in BINDING_ROLES:
        raise BindingError(
            f"binding_role must be one of {BINDING_ROLES}", code="invalid_request"
        )
    session = db.session()
    try:
        with session.begin():
            project = _load_accessible_project(session, actor, project_id)
            # D10 段 2：org 上下文取自项目归属（fail-closed：无 org 即拒写，
            # 且发生在任何出站调用之前）
            org_id = _project_org(project)
            client = client_from_settings()
            verified = _verified_snapshot(
                client, actor=actor, org_id=org_id, ontology_id=ontology_id,
                version_id=version_id, project_id=project_id,
            )
            # 重绑允许：仅 active/upgrade_pending 占位（retired 可重绑，评审 W-A）
            dup = session.scalars(
                select(ProjectOntologyBinding).where(
                    ProjectOntologyBinding.project_id == project_id,
                    ProjectOntologyBinding.ontology_id == ontology_id,
                    ProjectOntologyBinding.active_marker.is_not(None),
                )
            ).first()
            if dup is not None:
                raise BindingError(
                    "project already bound to this ontology", status=409, code="binding_exists"
                )
            binding = ProjectOntologyBinding(
                org_id=org_id,
                project_id=project_id,
                ontology_id=ontology_id,
                pinned_version_id=version_id,
                # 以 runtime 核实响应回填版本标签（不信任客户端自报，评审 W-D）
                pinned_version=str(verified.get("version", ""))[:32],
                binding_role=binding_role,
                status="active",
                active_marker=ACTIVE_MARKER,
                bound_by_user_id=str(actor.id),
            )
            session.add(binding)
            session.flush()
            return binding.snapshot()
    except BindingError:
        raise
    except IntegrityError as exc:
        raise BindingError(
            "project already bound to this ontology", status=409, code="binding_exists"
        ) from exc
    except Exception as exc:
        current_app.logger.exception("create_binding failed")
        raise BindingError("binding failed", status=500, code="binding_failed") from exc


def propose_upgrade(
    *, actor: User, project_id: str, binding_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    ensure_enabled()
    to_version_id = str(payload.get("to_version_id", "")).strip()
    if not to_version_id:
        raise BindingError("to_version_id is required", code="invalid_request")
    # §5.2："版本升级必须有差异审查"——差异材料与变更集指针缺一不可（评审 W-D）
    diff_summary = str(payload.get("diff_summary", "")).strip()
    source_change_set_id = str(payload.get("source_change_set_id", "")).strip()
    if not diff_summary or not source_change_set_id:
        raise BindingError(
            "diff_summary and source_change_set_id are required for upgrade review (§5.2)",
            code="invalid_request",
        )
    session = db.session()
    try:
        with session.begin():
            project = _load_accessible_project(session, actor, project_id)
            org_id = _project_org(project)
            binding = session.get(ProjectOntologyBinding, binding_id)
            if (
                binding is None
                or binding.project_id != project_id
                or binding.status not in ("active",)
            ):
                raise BindingError("binding not found", status=404, code="not_found")
            if binding.org_id != org_id:
                raise BindingError(
                    "binding organization attribution mismatch (project re-attributed)",
                    status=409,
                    code="binding_org_mismatch",
                )
            # 行锁串行化并发提案（评审 W-A：双提案竞态）
            binding = session.scalars(
                select(ProjectOntologyBinding)
                .where(ProjectOntologyBinding.id == binding_id)
                .with_for_update()
            ).first()
            assert binding is not None  # 上一步已验存在
            if to_version_id == binding.pinned_version_id:
                raise BindingError("upgrade target equals current pin", code="invalid_request")
            client = client_from_settings()
            verified = _verified_snapshot(
                client, actor=actor, org_id=org_id, ontology_id=binding.ontology_id,
                version_id=to_version_id, project_id=project_id,
            )
            pending = session.scalars(
                select(OntologyBindingUpgrade).where(
                    OntologyBindingUpgrade.binding_id == binding_id,
                    OntologyBindingUpgrade.status == "proposed",
                )
            ).first()
            if pending is not None:
                raise BindingError(
                    "an upgrade proposal is already pending", status=409, code="upgrade_pending"
                )
            upgrade = OntologyBindingUpgrade(
                binding_id=binding_id,
                from_version_id=binding.pinned_version_id,
                to_version_id=to_version_id,
                to_version=str(verified.get("version", ""))[:32],
                diff_summary=diff_summary,
                source_change_set_id=source_change_set_id,
                status="proposed",
                proposed_by_user_id=str(actor.id),
            )
            session.add(upgrade)
            binding.status = "upgrade_pending"  # data-model §3 状态位
            binding.version += 1
            session.flush()
            return upgrade.snapshot()
    except BindingError:
        raise
    except IntegrityError as exc:
        raise BindingError(
            "an upgrade proposal is already pending", status=409, code="upgrade_pending"
        ) from exc
    except Exception as exc:
        current_app.logger.exception("propose_upgrade failed")
        raise BindingError("upgrade proposal failed", status=500, code="upgrade_proposal_failed") from exc


def approve_upgrade(
    *,
    actor: User,
    project_id: str,
    binding_id: str,
    upgrade_id: str,
    decision: str,
    annotation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_enabled()
    if decision not in ("approved", "rejected"):
        raise BindingError("decision must be approved|rejected", code="invalid_request")
    # D16：批注入参形状校验先于一切（零写入、零出站）
    validated = _validated_annotation(annotation) if annotation is not None else None
    session = db.session()
    try:
        with session.begin():
            project = _load_accessible_project(session, actor, project_id)
            org_id = _project_org(project)
            # 行锁串行化：propose/approve/approve 竞态统一收敛（评审 W-A/E）
            binding = session.scalars(
                select(ProjectOntologyBinding)
                .where(ProjectOntologyBinding.id == binding_id)
                .with_for_update()
            ).first()
            if (
                binding is None
                or binding.project_id != project_id
                or binding.status != "upgrade_pending"
            ):
                raise BindingError("binding not found", status=404, code="not_found")
            if binding.org_id != org_id:
                raise BindingError(
                    "binding organization attribution mismatch (project re-attributed)",
                    status=409,
                    code="binding_org_mismatch",
                )
            upgrade = session.scalars(
                select(OntologyBindingUpgrade)
                .where(OntologyBindingUpgrade.id == upgrade_id)
                .with_for_update()
            ).first()
            if upgrade is None or upgrade.binding_id != binding_id:
                raise BindingError("upgrade proposal not found", status=404, code="not_found")
            if upgrade.status != "proposed":
                raise BindingError(
                    "upgrade proposal already acted", status=409, code="upgrade_already_acted"
                )
            if upgrade.proposed_by_user_id == str(actor.id):
                raise BindingError(
                    "proposer cannot approve own upgrade (I4)", status=403, code="self_approval"
                )
            # D16：批注回执入 evidence（审批/升级须留证据，§15）
            if validated is not None:
                upgrade.annotation_evidence_id = _record_annotation_receipt(
                    session, actor=actor, project=project, annotation=validated
                )
            if decision == "approved":
                # approve 时点二次 I5（写不降级 + propose→approve 间版本可能下架）
                client = client_from_settings()
                verified = _verified_snapshot(
                    client, actor=actor, org_id=org_id, ontology_id=binding.ontology_id,
                    version_id=upgrade.to_version_id, project_id=project_id,
                )
                # retire 旧行不删行（§5.2 保留历史绑定），新 pin 落 active 行
                binding.status = "retired"
                binding.active_marker = None
                binding.version += 1
                successor = ProjectOntologyBinding(
                    org_id=org_id,
                    project_id=project_id,
                    ontology_id=binding.ontology_id,
                    pinned_version_id=upgrade.to_version_id,
                    pinned_version=str(verified.get("version", ""))[:32],
                    binding_role=binding.binding_role,
                    status="active",
                    active_marker=ACTIVE_MARKER,
                    bound_by_user_id=str(actor.id),
                    approved_by_user_id=str(actor.id),
                )
                session.add(successor)
            else:
                # rejected → 绑定恢复 active（upgrade_pending 是暂挂态，评审 W-A）
                binding.status = "active"
                binding.active_marker = ACTIVE_MARKER
                binding.version += 1
            upgrade.status = decision
            upgrade.approved_by_user_id = str(actor.id)
            upgrade.acted_at = datetime.now(UTC)
            session.flush()
            return successor.snapshot() if decision == "approved" else upgrade.snapshot()
    except BindingError:
        raise
    except IntegrityError as exc:
        current_app.logger.exception("approve_upgrade integrity failure")
        raise BindingError(
            "upgrade approval conflict", status=409, code="upgrade_conflict"
        ) from exc
    except Exception as exc:
        current_app.logger.exception("approve_upgrade failed")
        raise BindingError("upgrade approval failed", status=500, code="upgrade_approval_failed") from exc


# ---- M3 数据接地质量检查与双层血缘只读代理（D21 / WP4③）----


def _load_active_binding_for_project(
    session: Any, actor: User, project_id: str, binding_id: str
) -> tuple[str, ProjectOntologyBinding]:
    """校验项目访问权（S-01）+ 提取项目 org_id（D10）+ 锁定活跃绑定（S-13）。"""
    project = _load_accessible_project(session, actor, project_id)
    org_id = _project_org(project)
    binding = session.get(ProjectOntologyBinding, binding_id)
    if (
        binding is None
        or binding.project_id != project_id
        or binding.status not in ("active", "upgrade_pending")
    ):
        raise BindingError("binding not found", status=404, code="not_found")
    if binding.org_id != org_id:
        raise BindingError(
            "binding organization attribution mismatch (project re-attributed)",
            status=409,
            code="binding_org_mismatch",
        )
    return org_id, binding


def _translate_runtime_call(call_fn: Any) -> dict[str, Any]:
    """统一映射 OntologyClient / MockOntologyAdapter 异常到显性 BindingError（§14-4 禁吞错）。"""
    try:
        body: dict[str, Any] = call_fn()
    except OntologyUnavailable as exc:
        raise BindingError(
            f"ontology runtime unreachable: {exc}", status=503, code="ontology_unavailable"
        ) from exc
    except OntologyAuthError as exc:
        raise BindingError(
            "ontology runtime rejected credentials (check FDE_ONTOLOGY_* config)",
            status=502,
            code="runtime_auth",
        ) from exc
    except OntologyConflict as exc:
        raise BindingError(
            f"ontology runtime conflict: {exc}", status=409, code="runtime_conflict"
        ) from exc
    except OntologyClientError as exc:
        raise BindingError(
            f"ontology runtime failure: {exc}", status=502, code="runtime_error"
        ) from exc
    status = int(body.pop("_status", 500))
    if status == 404:
        raise BindingError(
            str(body.get("message", "grounding target not found on runtime")),
            status=404,
            code="not_found",
        )
    if status == 429:
        raise BindingError(
            str(body.get("message", "ontology connector rate limited")),
            status=429,
            code="rate_limited",
        )
    if status >= 400:
        raise BindingError(
            str(body.get("message", "ontology runtime request rejected")),
            status=status,
            code=str(body.get("code", "runtime_rejected")),
        )
    return body


def check_binding_grounding(
    *, actor: User, project_id: str, binding_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """D21 / WP4③：触发项目已固定本体版本的对象类型接地质量检查（强制 pinned_version_id）。"""
    ensure_enabled()
    object_type_key = str(payload.get("object_type_key", "")).strip()
    if not object_type_key:
        raise BindingError("object_type_key is required", code="invalid_request")
    session = db.session()
    org_id, binding = _load_active_binding_for_project(session, actor, project_id, binding_id)
    client = client_from_settings()
    return _translate_runtime_call(
        lambda: client.check_grounding(
            actor_id=str(actor.id),
            org_id=org_id,
            project_id=project_id,
            ontology_id=binding.ontology_id,
            version_id=binding.pinned_version_id,
            object_type_key=object_type_key,
        )
    )


def get_binding_lineage(
    *,
    actor: User,
    project_id: str,
    binding_id: str,
    object_type: str | None = None,
    object_ref_id: str | None = None,
) -> dict[str, Any]:
    """D21 / WP4③：只读查询项目已固定本体版本的双层血缘（强制 pinned_version_id）。"""
    ensure_enabled()
    session = db.session()
    org_id, binding = _load_active_binding_for_project(session, actor, project_id, binding_id)
    client = client_from_settings()
    clean_ot = object_type.strip() if isinstance(object_type, str) and object_type.strip() else None
    clean_ref = (
        object_ref_id.strip() if isinstance(object_ref_id, str) and object_ref_id.strip() else None
    )
    return _translate_runtime_call(
        lambda: client.get_lineage(
            actor_id=str(actor.id),
            org_id=org_id,
            project_id=project_id,
            ontology_id=binding.ontology_id,
            version_id=binding.pinned_version_id,
            object_type=clean_ot,
            object_ref_id=clean_ref,
        )
    )

