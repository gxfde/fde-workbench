"""G-08：人工接受信号的**消费面**（AI 原生化差距台账 G-08）。

背景：``agent_artifacts.reviewed`` 此前**只写不读**——人工接受/撤回只落在
``agents/service.py::set_artifact_reviewed``（写）与 API 呈现（读字段），**没有任何
AI 面消费它**。台账 G-08 的消解判据＝「至少一个 AI 面消费点读取 reviewed」。

本模块把「人工接受」变成**可消费的复审信号**，并由 **chat 助手**读进上下文
（最小真消费点）：人工认可的产物回到 AI 的视野里，AI 回答时能引用「这套产物
被人工接受过」这一事实。

边界（红线）：

- 只带**元数据与指针**（kind / sha256 前缀 / 时间 / run 指针），**绝不复制产物
  正文**（产物原件只在宿主工作区与指纹）；
- **不自动改提示词**——信号只是上下文，不触发任何自动优化动作（自动进化是
  G-11 受控发布通道的职责）；
- **撤回即撤销认可**：``reviewed=False`` 的产物不进「已接受」清单。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable

ACCEPTED_CONTEXT_LIMIT = 10


def build_review_signals(rows: Iterable[Any]) -> list[dict[str, Any]]:
    """把「人工已接受」的产物聚合成复审信号（纯函数）。

    输入可以是 ORM 行或字典（键：``kind`` / ``reviewed`` / ``reviewed_at``），
    输出按产物类型聚合的信号列表：接受数 + 最近接受时间。

    只统计 ``reviewed=True``；``reviewed_at`` 缺失时按 0 处理（不影响计数）。
    """
    counters: dict[str, dict[str, Any]] = {}
    for row in rows:
        reviewed = row.get("reviewed") if isinstance(row, dict) else getattr(row, "reviewed", None)
        if not reviewed:
            continue
        kind = (row.get("kind") if isinstance(row, dict) else getattr(row, "kind", None)) or "unknown"
        reviewed_at = row.get("reviewed_at") if isinstance(row, dict) else getattr(row, "reviewed_at", None)
        signal = counters.setdefault(str(kind), {"kind": str(kind), "accepted_count": 0, "last_accepted_at": None})
        signal["accepted_count"] += 1
        if reviewed_at is not None:
            current = signal["last_accepted_at"]
            if current is None or reviewed_at > current:
                signal["last_accepted_at"] = reviewed_at
    signals = list(counters.values())
    signals.sort(key=lambda item: (-item["accepted_count"], item["kind"]))
    return signals


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value) if value is not None else ""


def accepted_artifact_context(session: Any, project_id: str, *, limit: int = ACCEPTED_CONTEXT_LIMIT) -> str:
    """项目内「人工已接受产物」的上下文块（纯元数据，无正文）。

    返回可直接贴进 AI **user 角色**上下文的文本块；无已接受产物时返回空串
    （调用方据此不注入任何内容）。
    """
    from sqlalchemy import select

    from fde_api.agents.models import AgentArtifact, AgentRun

    rows = session.execute(
        select(AgentArtifact, AgentRun)
        .join(AgentRun, AgentRun.id == AgentArtifact.run_id)
        .where(AgentRun.project_id == project_id, AgentArtifact.reviewed.is_(True))
        .order_by(AgentArtifact.reviewed_at.desc().nullslast())
        .limit(limit)
    ).all()
    if not rows:
        return ""
    signals = build_review_signals(
        [
            {
                "kind": artifact.kind,
                "reviewed": artifact.reviewed,
                "reviewed_at": artifact.reviewed_at,
            }
            for artifact, _run in rows
        ]
    )
    summary = "、".join(f"{item['kind']}×{item['accepted_count']}" for item in signals)
    lines = [
        "以下产物已被人工接受（仅元数据与指纹指针，未复制正文）：",
    ]
    for artifact, _run in rows:
        lines.append(
            f"- kind={artifact.kind} sha256={(artifact.sha256 or '')[:12]} "
            f"run={(artifact.run_id or '')[:8]} accepted_at={_iso(artifact.reviewed_at)}"
        )
    lines.append(f"汇总：{summary}（人工接受信号，仅供回答参考，不代表自动改写任何提示词）")
    return "\n".join(lines)


def project_review_signal_block(session: Any, project_id: str | None) -> str:
    """chat 上下文的信号块入口；无项目或无信号时返回空串。"""
    if not project_id:
        return ""
    try:
        return accepted_artifact_context(session, project_id)
    except Exception:  # noqa: BLE001 - 信号是增益项，取不到不阻塞问答
        return ""
