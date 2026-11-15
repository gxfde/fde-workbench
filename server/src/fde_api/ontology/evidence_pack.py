"""M5-WP3①：对客「冻结证据评审包」（Frozen Evidence Pack，D30，独立新模块）。

职责（工作令 §3 WP3 条 1 / D30 / 决议 03 §6-3 / 改进单 M5-OPT-2）：一键导出
项目阶段证据的只读 HTML/JSON 包 + I7 ``ontology_annotation`` 异人签收回执验真。

D30 四闸（黑名单废除后的物理等价物）：
- **显式只读 DTO 字段白名单投影**——``build_pack_payload`` 只从白名单键取值，
  S-07 ``connection_ref`` / S-20 ``unresolved_questions`` / ``internal_only`` /
  内部人锚列不进白名单即物理出不了包（模型未来加列也不外泄）；
- **离线 HTML 安全**——全值 ``html.escape`` + 零脚本静态
  ``CSP: default-src 'none'; style-src 'unsafe-inline'; img-src data:``，
  渲染不含时间戳（同一内容两次导出逐位一致，M2 review_package 同款纪律）；
- **服务端 HMAC 防伪**——独立密钥（``FDE_ONTOLOGY_EVIDENCE_PACK_HMAC_KEY``）
  对 ``(org_id, package_id, pinned_version_id, pack_sha256)`` 四元组签名，
  废除裸 SHA-256 防伪（改包重算即失配）；密钥缺省 fail-closed（503 拒导出）；
- **异人签收（SoD）**——客户线下签章后 FDE 拖入回执，服务端复核 HMAC 并硬拦
  「经办导出人 = acceptor」自批（导出人锚 = 导出审计事件）。

包 ID 口径（M1 契约 §5）：``review_package_id`` = 白名单 payload canonical
JSON 的 sha256（内容寻址，重复导出可检测）；回执落 ``project_evidence``
（``kind=ontology_annotation``、``captured_from=ontology_review:<package_id>``，
I7 指针+指纹，不复制原始件）。

纯函数（投影/包 ID/HMAC/渲染）100% 确定性生成并支持离线重放验证（工作令
§1 条 6）；导出/签收全程 OperationEvent 留痕。本模块不触碰
``ontology/service.py``（2102 行守卫，D30 明令）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from html import escape
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.evidence.models import ProjectEvidence
from fde_api.integrations.models import ProjectOntologyBinding
from fde_api.workbench.models import Gate, OperationEvent, Project

# ---- D30 白名单（唯一出闸通道；加字段须评审，默认拒绝） ----

# 证据行对客白名单：标识 + 指针 + 指纹（I7 语义锚点可出，句柄/人锚/内部
# 求值摘要不可出——action_request_id/logic_eval_digest/created_by_* 均排除）
_PACK_EVIDENCE_FIELDS = (
    "evidence_id",
    "kind",
    "source_uri",
    "content_sha256",
    "origin",
    "captured_from",
    "ontology_id",
    "pinned_version_id",
    "object_ref_id",
)
# Gate 行对客白名单：结论态可出，执行人/拍板人人锚不可出
_PACK_GATE_FIELDS = (
    "gate_key",
    "status",
    "decision",
    "submitted_at",
    "decided_at",
)
# 治理摘要对客白名单（D32 双指纹 + D31 处置闭环；undisposed 条目仅含
# change_set_id/status，与 runtime 键同形；degraded 进白名单——工作令 §1
# 条 4「对客透明标注本体校验在线/降级态」，party 评审 P2-C 修复。
# compiler_telemetry **不进**白名单：D31/§1 条 3 钉「平台内部编译器遥测
# SLO」——内部健康度不向客户暴露，防免改率被客户当作验收 KPI（古德哈特）
# ——P1 拍板 D2=移除）
_PACK_GOVERNANCE_FIELDS = (
    "ontology_id",
    "version",
    "snapshot_sha256",
    "domain_schema_sha256",
    "site_binding_sha256",
    "candidate_disposition",
    "sla_aging",
    "gate_ready",
    "degraded",
)

# 零脚本静态 CSP（D30 原文口径；零 <script> 是渲染器硬纪律）
_PACK_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"

PACK_VERSION = 1


class EvidencePackError(ValueError):
    """证据包导出/签收失败（code 进响应体，形状同 BindingError）。"""

    def __init__(self, message: str, *, status: int = 400, code: str = "invalid_request") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


# ---------------------------------------------------------------- 纯函数层


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _project_fields(row: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    return {key: row[key] for key in fields if key in row}


def build_pack_payload(
    *,
    project_code: str,
    ontology_id: str,
    pinned_version: str,
    pinned_version_id: str,
    governance: Mapping[str, Any],
    gates_view: Sequence[Mapping[str, Any]],
    evidence_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """白名单投影（唯一出闸通道）：任何白名单外键在此被物理丢弃。"""
    return {
        "pack_version": PACK_VERSION,
        "project_code": str(project_code),
        "ontology": {
            "ontology_id": str(ontology_id),
            "pinned_version": str(pinned_version),
            "pinned_version_id": str(pinned_version_id),
            **_project_fields(governance, _PACK_GOVERNANCE_FIELDS),
        },
        "gates": [_project_fields(gate, _PACK_GATE_FIELDS) for gate in gates_view],
        "evidence": [_project_fields(row, _PACK_EVIDENCE_FIELDS) for row in evidence_rows],
    }


def compute_package_id(payload: Mapping[str, Any]) -> str:
    """内容寻址包 ID（M1 契约 §5：review_package_id = 内容 sha256）。"""
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def sign_pack(
    *,
    org_id: str,
    package_id: str,
    pinned_version_id: str,
    pack_sha256: str,
    hmac_key: str,
) -> str:
    """服务端 HMAC-SHA256（D30 四元组；hexdigest，离线重放同值）。"""
    message = _canonical_json(
        {
            "org_id": org_id,
            "package_id": package_id,
            "pinned_version_id": pinned_version_id,
            "pack_sha256": pack_sha256,
        }
    )
    return hmac.new(hmac_key.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_pack_signature(
    *,
    org_id: str,
    package_id: str,
    pinned_version_id: str,
    pack_sha256: str,
    signature: str,
    hmac_key: str,
) -> bool:
    """重算四元组签名比对（常数时间；任一分量篡改即失配）。"""
    expected = sign_pack(
        org_id=org_id,
        package_id=package_id,
        pinned_version_id=pinned_version_id,
        pack_sha256=pack_sha256,
        hmac_key=hmac_key,
    )
    return hmac.compare_digest(expected, str(signature))


def render_pack_html(payload: Mapping[str, Any], *, package_id: str, signature: str) -> str:
    """离线 HTML 渲染：全值 escape + 零脚本 CSP + 水印 + 包 ID（确定性）。"""
    ontology_raw = payload.get("ontology")
    ontology: Mapping[str, Any] = ontology_raw if isinstance(ontology_raw, Mapping) else {}
    evidence_raw = payload.get("evidence")
    evidence: list[Any] = evidence_raw if isinstance(evidence_raw, list) else []
    gates_raw = payload.get("gates")
    gates: list[Any] = gates_raw if isinstance(gates_raw, list) else []

    def _row(key: str, value: Any) -> str:
        return f"<li><b>{escape(key)}</b>：{escape(str(value))}</li>"

    evidence_rows = "".join(
        "<section><h3>#%d %s</h3><ul>%s</ul></section>"
        % (
            index,
            escape(str(row.get("kind", ""))),
            "".join(_row(k, v) for k, v in row.items()),
        )
        for index, row in enumerate(
            [r for r in evidence if isinstance(r, Mapping)], start=1
        )
    )
    gate_rows = "".join(
        "<li>%s：%s（decision=%s）</li>"
        % (
            escape(str(g.get("gate_key", ""))),
            escape(str(g.get("status", ""))),
            escape(str(g.get("decision", "—"))),
        )
        for g in gates
        if isinstance(g, Mapping)
    )
    governance_rows = "".join(
        _row(k, v) for k, v in ontology.items() if k in _PACK_GOVERNANCE_FIELDS
    )
    # M5-WP3⑥（party 评审 P2-C）：降级态显式标注——客户离线打开包即可见
    # 导出那一刻本体校验不在线（透明标注，不静默半空治理段）。
    degraded_banner = (
        "<p><strong>⚠ 本体校验降级态：导出时本体运行时不在线，治理摘要"
        "不完整（以本地证据清单为准）。</strong></p>"
        if ontology.get("degraded") is True
        else ""
    )
    watermark = f"项目代号 {escape(str(payload.get('project_code', '')))}｜仅限授权评审人内部使用"
    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        f"<meta http-equiv=\"Content-Security-Policy\" content=\"{_PACK_CSP}\">"
        "<title>冻结证据评审包</title></head><body>"
        "<h1>冻结证据评审包</h1>"
        f"{degraded_banner}"
        f"<p>水印：{watermark}</p>"
        f"<p>pack_version：{escape(str(payload.get('pack_version', '')))}</p>"
        f"<h2>本体钉版</h2><ul>{governance_rows or '<li>（未启用本体面）</li>'}</ul>"
        f"<h2>门禁状态</h2><ul>{gate_rows or '<li>（无门禁行）</li>'}</ul>"
        f"<h2>证据清单（{len([r for r in evidence if isinstance(r, Mapping)])}）</h2>"
        f"{evidence_rows or '<p>（无证据行）</p>'}"
        f"<p>review_package_id：<code>{escape(package_id)}</code></p>"
        f"<p>HMAC 签名：<code>{escape(signature)}</code></p>"
        "</body></html>"
    )


# ---------------------------------------------------------------- 服务层


def _load_hmac_key(settings: Any) -> str:
    from pydantic import SecretStr

    key = getattr(settings, "ontology_evidence_pack_hmac_key", None)
    if not isinstance(key, SecretStr) or not key.get_secret_value():
        raise EvidencePackError(
            "证据包防伪密钥未配置（FDE_ONTOLOGY_EVIDENCE_PACK_HMAC_KEY）。",
            status=503,
            code="evidence_pack_not_configured",
        )
    return key.get_secret_value()


def _load_pack_project(
    session: Session, actor: Any, project_id: str, *, require_manage: bool = False
) -> Project:
    """S-01：项目不存在或无权 → 统一 404（不泄露存在性）。

    M5-WP3⑤（party 评审 P1）：签收是写路径（落证据行 + 事件）——
    ``require_manage=True`` 时校验 can_manage；导出保持 can_view 只读投影。
    """
    from fde_api.projects.permissions import project_access

    project = session.get(Project, project_id)
    if project is not None:
        access = project_access(actor, project)
        allowed = access.can_manage if require_manage else access.can_view
    else:
        allowed = False
    if project is None or not allowed:
        raise EvidencePackError("project not found", status=404, code="not_found")
    return project


def _governance_view(
    session: Session, project: Project, actor: Any, settings: Any, client: Any
) -> dict[str, Any]:
    """治理段（诚实缺省三态）：disabled → included=False；不可达 → degraded。"""
    if not getattr(settings, "ontology_enabled", False):
        return {"included": False}
    binding = session.scalars(
        select(ProjectOntologyBinding).where(
            ProjectOntologyBinding.project_id == project.id,
            ProjectOntologyBinding.status == "active",
        )
    ).first()
    if binding is None:
        return {"included": False, "reason": "no_active_binding"}
    if client is None:
        from fde_api.integrations.service import client_from_settings

        client = client_from_settings()
    try:
        summary = client.get_version_governance_summary(
            actor_id=actor.id,
            org_id=binding.org_id,
            project_id=binding.project_id,
            ontology_id=binding.ontology_id,
            version_id=binding.pinned_version_id,
        )
    except Exception:
        return {
            "included": True,
            "degraded": True,
            "ontology_id": binding.ontology_id,
            "pinned_version_id": binding.pinned_version_id,
            "pinned_version": binding.pinned_version,
        }
    if int(summary.get("_status", 200)) != 200:
        return {
            "included": True,
            "degraded": True,
            "ontology_id": binding.ontology_id,
            "pinned_version_id": binding.pinned_version_id,
            "pinned_version": binding.pinned_version,
        }
    return {"included": True, "degraded": False, **summary}


def export_evidence_pack(
    session: Session,
    *,
    actor: Any,
    project_id: str,
    settings: Any,
    client: Any = None,
) -> dict[str, Any]:
    """导出冻结证据评审包（只读投影 + HMAC + 审计留痕）。

    返回 ``{package_id, pack_sha256, signature, html, evidence_count,
    pinned_version_id, governance}``；导出事件
    ``ontology_evidence_pack_exported`` 是签收异人验真的导出人锚。
    """
    hmac_key = _load_hmac_key(settings)
    project = _load_pack_project(session, actor, project_id)
    governance = _governance_view(session, project, actor, settings, client)
    binding = session.scalars(
        select(ProjectOntologyBinding).where(
            ProjectOntologyBinding.project_id == project.id,
            ProjectOntologyBinding.status == "active",
        )
    ).first()
    evidence_rows = session.scalars(
        select(ProjectEvidence).where(ProjectEvidence.project_id == project.id)
        .order_by(ProjectEvidence.id)
    ).all()
    gates_view = session.scalars(
        select(Gate).where(Gate.project_id == project.id).order_by(Gate.gate_key)
    ).all()

    def _evidence_view(row: ProjectEvidence) -> dict[str, Any]:
        return {
            "evidence_id": row.id,
            "kind": row.kind,
            "source_uri": row.source_uri,
            "content_sha256": row.content_sha256,
            "origin": row.origin,
            "captured_from": row.captured_from,
            "ontology_id": row.ontology_id,
            "pinned_version_id": row.pinned_version_id,
            "object_ref_id": row.object_ref_id,
        }

    def _gate_view(gate: Gate) -> dict[str, Any]:
        return {
            "gate_key": gate.gate_key,
            "status": gate.status,
            "decision": gate.decision,
            "submitted_at": str(gate.submitted_at) if gate.submitted_at else None,
            "decided_at": str(gate.decided_at) if gate.decided_at else None,
        }

    payload = build_pack_payload(
        project_code=project.project_code,
        ontology_id=binding.ontology_id if binding else "",
        pinned_version=binding.pinned_version if binding else "",
        pinned_version_id=binding.pinned_version_id if binding else "",
        governance=governance,
        gates_view=[_gate_view(g) for g in gates_view],
        evidence_rows=[_evidence_view(r) for r in evidence_rows],
    )
    pack_sha256 = compute_package_id(payload)
    signature = sign_pack(
        org_id=project.org_id or "",
        package_id=pack_sha256,
        pinned_version_id=binding.pinned_version_id if binding else "",
        pack_sha256=pack_sha256,
        hmac_key=hmac_key,
    )
    html = render_pack_html(payload, package_id=pack_sha256, signature=signature)

    from fde_api.projects.events import record_event

    record_event(
        session,
        actor,
        "ontology_evidence_pack_exported",
        project,
        {
            "package_id": pack_sha256,
            "pack_sha256": pack_sha256,
            "pinned_version_id": binding.pinned_version_id if binding else "",
            "evidence_count": len(evidence_rows),
            "degraded": bool(governance.get("degraded")),
        },
    )
    session.commit()
    return {
        "package_id": pack_sha256,
        "pack_sha256": pack_sha256,
        "signature": signature,
        "pinned_version_id": binding.pinned_version_id if binding else "",
        "evidence_count": len(evidence_rows),
        "governance": governance,
        "html": html,
    }


def _validate_annotations(annotations: Any) -> list[dict[str, Any]]:
    # M5-WP3③（party 评审 P2-1）：容量硬限——条目数与 origin 长度封顶，
    # 拒绝灌库/巨文本经签名包对客投递（annotation 上限对齐常规批处理量级）。
    if not isinstance(annotations, list) or not annotations:
        raise EvidencePackError("annotations 必须为非空数组。")
    if len(annotations) > 200:
        raise EvidencePackError("annotations 条目数超限（≤200）。")
    checked: list[dict[str, Any]] = []
    for item in annotations:
        if not isinstance(item, Mapping):
            raise EvidencePackError("annotations 条目必须为对象。")
        source_uri = str(item.get("source_uri", "")).strip()
        content_sha256 = str(item.get("content_sha256", "")).strip().lower()
        if not source_uri or len(source_uri) > 500:
            raise EvidencePackError("annotation.source_uri 缺失或超长（≤500）。")
        if len(content_sha256) != 64 or any(c not in "0123456789abcdef" for c in content_sha256):
            raise EvidencePackError("annotation.content_sha256 必须为 64 位十六进制。")
        origin = item.get("origin")
        if origin is not None and len(str(origin)) > 200:
            raise EvidencePackError("annotation.origin 超长（≤200）。")
        checked.append(
            {
                "source_uri": source_uri,
                "content_sha256": content_sha256,
                "origin": str(origin) if origin else None,
            }
        )
    return checked


def _find_export_event(
    session: Session, project_id: str, package_id: str
) -> OperationEvent | None:
    """按包 ID 找导出留痕（低频事件，Python 侧过滤避免 JSON 方言差异）。

    M5-WP3 P3（回植前置评审）：锚定**首次**导出（created_at 升序取首条命中）
    ——内容寻址使同包可被第二人幂等重导出，若锚取最新事件，首经办人即可经
    他人重导出洗掉 SoD 拦截（换锚自签收）。
    """
    events = session.scalars(
        select(OperationEvent)
        .where(
            OperationEvent.project_id == project_id,
            OperationEvent.event_type == "ontology_evidence_pack_exported",
        )
        .order_by(OperationEvent.created_at.asc(), OperationEvent.id.asc())
    ).all()
    for event in events:
        if str((event.changes or {}).get("package_id", "")) == package_id:
            return event
    return None


def import_annotation_receipt(
    session: Session,
    *,
    actor: Any,
    project_id: str,
    payload: Mapping[str, Any],
    settings: Any,
) -> dict[str, Any]:
    """I7 批注回执签收：HMAC 复核 + 异人 SoD 硬拦 + 逐条落证据（幂等）。

    fail-closed 三闸（顺序即防线）：
    ① 签名对不上 → 400 ``pack_signature_invalid``（篡改/伪造包）；
    ② 无对应导出留痕 → 409 ``export_record_missing``（流程不合法）；
    ③ 导出人 = acceptor → 403 ``self_acceptance_forbidden``（SoD）。
    """
    from fde_api.evidence.service import upsert_evidence

    required = {"review_package_id", "pack_sha256", "pinned_version_id", "signature", "annotations"}
    if not isinstance(payload, Mapping) or set(payload) - required:
        raise EvidencePackError("请求字段无效。")
    package_id = str(payload.get("review_package_id", "")).strip().lower()
    pack_sha256 = str(payload.get("pack_sha256", "")).strip().lower()
    pinned_version_id = str(payload.get("pinned_version_id", "")).strip()
    signature = str(payload.get("signature", "")).strip()
    for name, value in (
        ("review_package_id", package_id),
        ("pack_sha256", pack_sha256),
    ):
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise EvidencePackError(f"{name} 必须为 64 位十六进制。")
    if not pinned_version_id or not signature:
        raise EvidencePackError("pinned_version_id/signature 必填。")
    annotations = _validate_annotations(payload.get("annotations"))

    hmac_key = _load_hmac_key(settings)
    project = _load_pack_project(session, actor, project_id, require_manage=True)
    if not verify_pack_signature(
        org_id=project.org_id or "",
        package_id=package_id,
        pinned_version_id=pinned_version_id,
        pack_sha256=pack_sha256,
        signature=signature,
        hmac_key=hmac_key,
    ):
        raise EvidencePackError("证据包签名复核失败（包可能被篡改）。", code="pack_signature_invalid")

    event = _find_export_event(session, project.id, package_id)
    if event is None:
        raise EvidencePackError(
            "该包无本项目的导出留痕，不可签收。",
            status=409,
            code="export_record_missing",
        )
    exporter_id = str(event.actor_user_id)
    if exporter_id == str(actor.id):
        raise EvidencePackError(
            "异人职责分离（SoD）：经办导出人不得自签收同一评审包。",
            status=403,
            code="self_acceptance_forbidden",
        )

    from fde_api.projects.events import record_event

    accepted = 0
    duplicated = 0
    evidence_ids: list[str] = []
    for annotation in annotations:
        # M5-WP3 D1（P1 拍板：零 DDL 方案）：source_uri 编码包 ID 前缀——
        # 唯一键 (project, source_uri, content_sha256) 因此天然按包隔离，
        # 跨包同文件批注各自成行；source_uri 与 captured_from 双锚同源。
        scoped_uri = f"ontology_review:{package_id}|{annotation['source_uri']}"
        if len(scoped_uri) > 500:
            raise EvidencePackError(
                "annotation.source_uri 与包 ID 组合后超长（≤500）。"
            )
        row, created = upsert_evidence(
            session,
            project_id=project.id,
            kind="ontology_annotation",
            source_uri=scoped_uri,
            content_sha256=annotation["content_sha256"],
            origin=annotation["origin"],
            captured_from=f"ontology_review:{package_id}",
            created_by_user_id=str(actor.id),
            ontology_ref=None,
        )
        evidence_ids.append(row.id)
        if created:
            accepted += 1
        else:
            duplicated += 1
    record_event(
        session,
        actor,
        "ontology_annotation_receipt_imported",
        project,
        {
            "package_id": package_id,
            "accepted": accepted,
            "duplicated": duplicated,
            "exported_by": exporter_id,
        },
    )
    session.commit()
    return {
        "package_id": package_id,
        "accepted": accepted,
        "duplicated": duplicated,
        "evidence_ids": evidence_ids,
    }


__all__ = [
    "EvidencePackError",
    "build_pack_payload",
    "compute_package_id",
    "export_evidence_pack",
    "import_annotation_receipt",
    "render_pack_html",
    "sign_pack",
    "verify_pack_signature",
]
