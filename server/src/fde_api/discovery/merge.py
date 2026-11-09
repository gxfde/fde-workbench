"""分段抽取结果的行号回基与合并（V31-P1b，纯函数）。

合并口径（跨片）：

1. **行号回基**：模型回报的是片内行号，按 ``chunk.start_line`` 回基成全文
   绝对行号（``source_locator.type == "line"`` 才回基；其他定位类型原样）；
2. **事实去重**：跨片可能出现同一 ``(fact_type, subject, predicate)``
   （相邻片重复陈述同一事实），保留**首次**出现（片序在前者优先）；
3. **需求去重**：跨片可能重复提出同一需求（按标题归一去重），保留首次；
4. **引用重基**：需求的 ``source_fact_indexes`` 是**片内**下标，合并后要
   映射到合并事实表的下标；指向被去重丢弃的事实的引用一并丢弃（需求因此
   落入「无来源事实支撑 → 待澄清」态，由调用方按既有口径处理）。

合并结果仍走既有契约校验（``validate_extraction_output``）——整批上限
（facts ≤200 / requirements ≤50）与唯一性纪律不变。
"""

from __future__ import annotations

from typing import Any

from fde_api.discovery.chunking import TranscriptChunk


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
) -> dict[str, Any]:
    """把各片抽取结果合并成一份整批输出（纯函数，无 IO）。

    ``pairs`` 为 ``(切片, 该片的规范化抽取结果)`` 序列，顺序即片序。
    """
    facts: list[dict[str, Any]] = []
    requirements: list[dict[str, Any]] = []
    seen_fact_identities: set[tuple[str, str, str]] = set()
    seen_titles: set[str] = set()

    for chunk, draft in pairs:
        chunk_facts = draft.get("facts") or []
        # 片内下标 → 合并后下标（被去重丢弃的映射为 None）
        index_map: list[int | None] = []
        for item in chunk_facts:
            identity = (item["fact_type"], item["subject"], item["predicate"])
            if identity in seen_fact_identities:
                index_map.append(None)
                continue
            seen_fact_identities.add(identity)
            index_map.append(len(facts))
            facts.append({**item, "source_locator": rebase_locator(item["source_locator"], chunk)})
        for item in draft.get("requirements") or []:
            title = item["title"]
            key = _normalize_title(title)
            if key in seen_titles:
                continue
            seen_titles.add(key)
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
    return {"facts": facts, "requirements": requirements}
