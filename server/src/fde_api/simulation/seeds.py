"""内置案例种子（V3.2 G2）。

6 个基线案例文件（``seeds/CASE-*.json``）→ 物化 **18 行**（6 案例 × 3 客户行为
变体）。物化是纯函数（``materialize_variant``），种子入库幂等：已存在
``(scenario_key, variant, version=1)`` 的分支跳过，不重复插入、不覆盖既有版本。

播种只在 **V3.2 自己的迁移/引导路径**里调用；不改动既有种子机制
（``workbench/seed.py`` 等），避免与 V3.1 在建能力耦合。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from fde_api.simulation.models import SimulationScenario
from fde_api.simulation.scenarios.loader import list_case_files, load_case_file, materialize_variant
from fde_api.simulation.schemas import normalize_tags

VARIANTS = ("normal", "vague", "complex")


def build_seed_rows() -> list[dict[str, Any]]:
    """从基线案例文件物化全部种子行（纯函数，不落库）。"""
    rows: list[dict[str, Any]] = []
    for path in list_case_files():
        base = load_case_file(path)
        case_code = base["case_code"]
        content = base["content"]
        reference = base.get("reference")
        for variant in VARIANTS:
            materialized = materialize_variant(content, variant)
            materialized["case_code"] = case_code
            rows.append(
                {
                    "scenario_key": case_code,
                    "name": base["name"],
                    "industry": base.get("industry", "general"),
                    "variant": variant,
                    "difficulty": base.get("difficulty", "standard"),
                    "split": base.get("split", "train"),
                    "status": "active",
                    "tags": normalize_tags(base.get("tags")),
                    "content_json": materialized,
                    "reference_json": reference,
                    "rubric_version": base.get("rubric_version", "rubric-v1"),
                    "source_kind": "seed",
                    "source_ref": path.name,
                    "version": 1,
                }
            )
    return rows


def seed_scenarios(session) -> dict[str, Any]:
    """幂等播种内置案例。返回 ``{"inserted": n, "skipped": n}``。"""
    rows = build_seed_rows()
    inserted = 0
    skipped = 0
    for row in rows:
        existing = session.scalar(
            select(SimulationScenario.id).where(
                SimulationScenario.scenario_key == row["scenario_key"],
                SimulationScenario.variant == row["variant"],
                SimulationScenario.version == 1,
            )
        )
        if existing is not None:
            skipped += 1
            continue
        session.add(
            SimulationScenario(
                scenario_key=row["scenario_key"],
                name=row["name"],
                industry=row["industry"],
                variant=row["variant"],
                difficulty=row["difficulty"],
                split=row["split"],
                status=row["status"],
                tags=list(row["tags"]),
                content_json=row["content_json"],
                reference_json=row["reference_json"],
                rubric_version=row["rubric_version"],
                source_kind=row["source_kind"],
                source_ref=row["source_ref"],
                created_by_user_id=None,
                version=1,
            )
        )
        inserted += 1
    session.flush()
    return {"inserted": inserted, "skipped": skipped, "total": len(rows)}
