"""分段抽取结果的行号回基与合并（V31-P1b 纯函数；V31-P1c 加每片配额硬闸）。

合并口径（跨片）：

1. **行号回基**：模型回报的是片内行号，按 ``chunk.start_line`` 回基成全文
   绝对行号（``source_locator.type == "line"`` 才回基；其他定位类型原样）；
2. **事实去重**：跨片可能出现同一 ``(fact_type, subject, predicate)``
   （相邻片重复陈述同一事实），保留**首次**出现（片序在前者优先）；
3. **需求去重**：跨片可能重复提出同一需求（按标题归一去重），保留首次；
4. **引用重基**：需求的 ``source_fact_indexes`` 是**片内**下标，合并后要
   映射到合并事实表的下标；指向被去重丢弃的事实的引用一并丢弃（需求因此
   落入「无来源事实支撑 → 待澄清」态，由调用方按既有口径处理）；
5. **每片配额硬闸（V31-P1c）**：每片事实/需求条数不超过配额（配额由
   ``contract.chunk_quotas(片数)`` 守恒分配）——超出部分**丢弃并计数**
   （不静默：计数随合并报告返回，由调用方留痕）。这保证
   **合并条数 ≤ 全批预算**恒成立（否则管线会违反自己的契约——V31-P1c
   活体实测：244 行纪要 12 片合并后事实数撞穿固定 200 闸，整批被拒）。

合并结果仍走既有契约校验（``validate_extraction_output``）——唯一性纪律
不变；条数上限按 ``contract.batch_budgets(片数)`` 上浮（守恒预算）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fde_api.discovery.chunking import TranscriptChunk
from fde_api.discovery.contract import chunk_quotas


@dataclass(frozen=True)
class MergeQuotaReport:
    """合并配额报告（事实/需求配额、被配额裁掉的条数）。"""

    fact_quota: int
    requirement_quota: int
    fact_budget: int
    requirement_budget: int
    facts_dropped: int
    requirements_dropped: int


def _normalize_title(title: str) -> str:
    return title.strip().lower()


def rebase_locator(locator: dict[str, Any], chunk: TranscriptChunk) -> dict[str, Any]:
    """行号回基（只动 line 型定位的行号，其余键原样）。"""
    rebased = dict(locator)
    if rebased.get("type") == "line" and isinstance(rebased.get("line"), int):
        rebased["line"] = chunk.rebase_line(int(rebased["line"]))
    return rebased


def merge_chunk_drafts(
    pairs: list[tuple[TranscriptChunk, dict[str, Any]]],
    *,
    fact_quota: int | None = None,
    requirement_quota: int | None = None,
) -> tuple[dict[str, Any], MergeQuotaReport]:
    """把各片抽取结果合并成一份整批输出（纯函数，无 IO）。

    ``pairs`` 为 ``(切片, 该片的规范化抽取结果)`` 序列，顺序即片序。
    返回 ``(合并草稿, 配额报告)``——配额报告供调用方留痕（被裁条数）。
    """
    pieces = max(1, len(pairs))
    default_fact_quota, default_requirement_quota = chunk_quotas(pieces)
    fact_quota = default_fact_quota if fact_quota is None else fact_quota
    requirement_quota = default_requirement_quota if requirement_quota is None else requirement_quota

    facts: list[dict[str, Any]] = []
    requirements: list[dict[str, Any]] = []
    seen_fact_identities: set[tuple[str, str, str]] = set()
    seen_titles: set[str] = set()
    facts_dropped = 0
    requirements_dropped = 0

    for chunk, draft in pairs:
        chunk_facts = draft.get("facts") or []
        # 片内下标 → 合并后下标（被去重丢弃的映射为 None）
        index_map: list[int | None] = []
        kept_in_piece = 0
        for item in chunk_facts:
            identity = (item["fact_type"], item["subject"], item["predicate"])
            if identity in seen_fact_identities:
                index_map.append(None)
                continue
            if kept_in_piece >= fact_quota:
                # 每片配额硬闸：超出配额的事实丢弃并计数（引用一并作废）
                index_map.append(None)
                facts_dropped += 1
                continue
            seen_fact_identities.add(identity)
            kept_in_piece += 1
            index_map.append(len(facts))
            facts.append({**item, "source_locator": rebase_locator(item["source_locator"], chunk)})
        kept_requirements_in_piece = 0
        for item in draft.get("requirements") or []:
            title = item["title"]
            key = _normalize_title(title)
            if key in seen_titles:
                continue
            if kept_requirements_in_piece >= requirement_quota:
                requirements_dropped += 1
                continue
            seen_titles.add(key)
            kept_requirements_in_piece += 1
            source_indexes: list[int] = []
            for local_index in item.get("source_fact_indexes") or []:
                if not isinstance(local_index, int) or isinstance(local_index, bool):
                    continue
                if local_index < 0 or local_index >= len(index_map):
                    continue
                mapped = index_map[local_index]
                if mapped is None or mapped in source_indexes:
                    continue
                source_indexes.append(mapped)
            requirements.append({**item, "source_fact_indexes": source_indexes})
    report = MergeQuotaReport(
        fact_quota=fact_quota,
        requirement_quota=requirement_quota,
        fact_budget=fact_quota * pieces,
        requirement_budget=requirement_quota * pieces,
        facts_dropped=facts_dropped,
        requirements_dropped=requirements_dropped,
    )
    return {"facts": facts, "requirements": requirements}, report
