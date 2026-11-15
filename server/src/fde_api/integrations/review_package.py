"""评审包 HTML 渲染（D8：渲染归 Workbench 消费侧，消费 GET /change-sets/{id} 详情）。

契约（``ontology-integration-contract.md`` §5）：评审包 = diff_summary + 逐项 payload
人读视图 + 每项证据引用（``evidence_quote`` + ``source_location``）+ 审批状态；
``review_package_id`` = 内容 sha256（内容寻址 ⇒ 重复导出可检测）；安全 = 客户名沿用
代号化名 + 水印 + 包 ID；导出动作落审计事件（§15 数据导出审计留痕）。

纪律：
- 渲染内容**不含时间戳**——否则同一 change-set 两次导出的包 ID 会漂移，破坏内容寻址
  语义（批注回执的 ``captured_from=ontology_review:<package_id>`` 依赖该稳定性）；
- 包 ID = **去掉包 ID 行本身**的渲染内容的 sha256（自引用不可能哈希）；
- 全部文本经 ``html.escape``（防注入）；证据引用只存指针与原文引用，不外发客户原文
  （评审包是本地响应，不是对外推送）；
- runtime 404/不可达/鉴权失败一律显性转译为 ``BindingError``（绝不渲染幽灵 200 HTML）。
"""

from __future__ import annotations

import hashlib
from html import escape
from typing import Any

from fde_api.auth.models import User
from fde_api.extensions import db
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

_PAYLOAD_FIELDS = (
    "display_name",
    "description",
    "materialization",
    "data_type",
    "cardinality",
    "confidence",
    "fact_or_inference",
    "suggested_owner",
)


def _payload_view(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    for key in _PAYLOAD_FIELDS:
        if key in payload:
            lines.append(f"<li><b>{escape(key)}</b>：{escape(str(payload[key]))}</li>")
    for key in ("conflicts", "unresolved_questions"):
        values = payload.get(key)
        if isinstance(values, list) and values:
            items = "".join(f"<li>{escape(str(value))}</li>" for value in values)
            lines.append(f"<li><b>{escape(key)}</b><ul>{items}</ul></li>")
    return f"<ul>{''.join(lines)}</ul>"


def _item_block(index: int, item: dict[str, Any]) -> str:
    payload = item.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    return (
        "<section>"
        f"<h3>#{index} {escape(str(item.get('op', '')))} "
        f"{escape(str(item.get('entity_type', '')))} / "
        f"{escape(str(item.get('entity_key', '')))}</h3>"
        f"{_payload_view(payload)}"
        "<p><b>evidence_quote</b>：<q>"
        f"{escape(str(payload.get('evidence_quote', '')))}</q></p>"
        "<p><b>source_location</b>：<code>"
        f"{escape(str(payload.get('source_location', '')))}</code></p>"
        "</section>"
    )


def _fetch_change_set(
    client: Any,
    *,
    actor_id: str,
    org_id: str,
    project_id: str,
    change_set_id: str,
) -> dict[str, Any]:
    try:
        detail = client.get_change_set(
            actor_id=actor_id,
            org_id=org_id,
            project_id=project_id,
            change_set_id=change_set_id,
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
            "ontology runtime conflict while loading change-set",
            status=409,
            code="runtime_conflict",
        ) from exc
    except OntologyClientError as exc:
        raise BindingError(
            f"ontology runtime failure: {exc}",
            status=502,
            code="runtime_error",
        ) from exc

    if not isinstance(detail, dict):
        raise BindingError("invalid runtime response", status=502, code="runtime_error")
    status = int(detail.get("_status", 200))
    if status == 404:
        raise BindingError(
            "change-set not found",
            status=404,
            code="not_found",
        )
    if status != 200:
        raise BindingError(
            f"unexpected ontology runtime status {status}",
            status=502,
            code="runtime_error",
        )
    return detail


def render_review_package(actor: User, project_id: str, change_set_id: str) -> str:
    """渲染评审包 HTML（含包 ID 与水印），并落导出审计事件。"""
    ensure_enabled()
    session = db.session()
    project = _load_accessible_project(session, actor, project_id)
    org_id = _project_org(project)
    client = client_from_settings()
    detail = _fetch_change_set(
        client,
        actor_id=str(actor.id),
        org_id=org_id,
        project_id=project_id,
        change_set_id=change_set_id,
    )
    items = detail.get("proposed_json")
    items = items if isinstance(items, list) else []
    approvals = detail.get("approvals")
    approvals = approvals if isinstance(approvals, list) else []

    blocks = [
        _item_block(index, item)
        for index, item in enumerate(items, start=1)
        if isinstance(item, dict)
    ]
    approval_rows = "".join(
        "<li>"
        f"{escape(str(entry.get('role', '')))}："
        f"{escape(str(entry.get('decision', entry.get('status', ''))))}"
        "</li>"
        for entry in approvals
        if isinstance(entry, dict)
    )
    watermark = f"项目代号 {project.project_code}｜仅限授权评审人内部使用"
    body = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        "<title>本体评审包</title></head><body>"
        "<h1>本体评审包</h1>"
        f"<p>change-set：<code>{escape(str(change_set_id))}</code></p>"
        f"<p>状态：{escape(str(detail.get('status', '')))}</p>"
        f"<p>变更摘要：{escape(str(detail.get('diff_summary', '')))}</p>"
        f"<p>水印：{escape(watermark)}</p>"
        f"<h2>候选条目（{len(blocks)}）</h2>"
        f"{''.join(blocks) if blocks else '<p>（无条目）</p>'}"
        f"<h2>审批状态</h2><ul>{approval_rows or '<li>（无记录）</li>'}</ul>"
        "</body></html>"
    )
    package_id = hashlib.sha256(body.encode("utf-8")).hexdigest()
    record_event(
        session,
        actor,
        "ontology_review_package_exported",
        project,
        {
            "change_set_id": change_set_id,
            "review_package_id": package_id,
            "item_count": len(blocks),
        },
    )
    session.commit()
    return body.replace(
        "</body>",
        f"<p>review_package_id：<code>{package_id}</code></p></body>",
    )


__all__ = ["render_review_package", "BindingError"]
