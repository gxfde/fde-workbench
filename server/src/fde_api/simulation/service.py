"""模拟场景库服务（V3.2 G2）。

职责：案例 CRUD、版本管理、复制、导入导出、分类与标签。

**版本语义**：一行 = 一个不可变版本快照。内容变更不原地改，而是**追加新版本**
（G1 §4.4）。某 (scenario_key, variant) 的**有效状态 = 其最大版本行**；
列表默认只返回有效版本（``include_history=true`` 才返回全史）。

**权限**：复用既有能力档语义（``control/access.py`` 的 level 体系），**不改**
该共享文件——读与写场景库都要求 ``project_operator`` 档（fde_engineer /
project_lead / admin）；``viewer``（assistant_read）无权访问训练场运营面。

**参考答案可见性**：本服务面向**人类运营者**，返回完整场景（含参考答案）——
参考答案的隔离约束作用于**被测方装载路径**（``scenarios/loader.py`` 的 Tester
View / Customer View），不是人机界面。场景内容为合成训练材料，不含客户真实资料。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from fde_api.auth.models import User
from fde_api.control.access import ACCESS_RANK, effective_ai_access
from fde_api.extensions import db
from fde_api.simulation.models import (
    SCENARIO_DIFFICULTIES,
    SCENARIO_SPLITS,
    SCENARIO_STATUSES,
    SCENARIO_VARIANTS,
    SimulationScenario,
)
from fde_api.simulation.schemas import normalize_tags
from fde_api.simulation.scenarios.loader import materialize_variant
from fde_api.simulation.scenarios.validator import ERROR_MESSAGES, validate_scenario
from fde_api.simulation.scenarios.versioning import derive_next_row, next_version
from fde_api.workbench.models import OperationEvent

# 场景库读写所需能力档（project_operator 档 = fde_engineer 及以上）
REQUIRED_LEVEL = "project_operator"

LIST_PAGE_SIZE = 50
MAX_LIST_PAGE_SIZE = 200


class ScenarioServiceError(Exception):
    """场景库服务错误（code 为稳定机器可读契约）。"""

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail or {}

    def __str__(self) -> str:  # pragma: no cover - 调试用
        return f"{self.code}: {self.message}"


# ---------------------------------------------------------------------------
# 权限与事件
# ---------------------------------------------------------------------------


def _require_level(user: User, level: str = REQUIRED_LEVEL) -> None:
    actual, _source = effective_ai_access(user)
    if ACCESS_RANK.get(actual, 0) < ACCESS_RANK[level]:
        raise ScenarioServiceError(
            "forbidden", "当前账号无权访问模拟训练场。", 403
        )


def _record(
    session,
    actor: User,
    event_type: str,
    target: SimulationScenario,
    changes: dict[str, Any],
) -> None:
    """模拟域事件直接落 operation_events（不扩 ``projects/events.py`` 的目标注册表）。

    ``project_id`` 恒为 None——模拟对象不属于任何真实项目（G1 §3.2 P1）。
    """
    session.add(
        OperationEvent(
            actor_user_id=actor.id,
            project_id=None,
            target_type="simulation_scenario",
            target_id=target.id,
            event_type=event_type,
            changes=changes,
        )
    )


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------


def _serialize(row: SimulationScenario, *, include_content: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": row.id,
        "scenario_key": row.scenario_key,
        "name": row.name,
        "industry": row.industry,
        "variant": row.variant,
        "difficulty": row.difficulty,
        "split": row.split,
        "status": row.status,
        "tags": list(row.tags or []),
        "version": row.version,
        "rubric_version": row.rubric_version,
        "source_kind": row.source_kind,
        "source_ref": row.source_ref,
        "note": row.note,
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if include_content:
        payload["content"] = dict(row.content_json or {})
        payload["reference"] = dict(row.reference_json) if row.reference_json else None
    return payload


def _row_to_dict(row: SimulationScenario) -> dict[str, Any]:
    return {
        "scenario_key": row.scenario_key,
        "name": row.name,
        "industry": row.industry,
        "variant": row.variant,
        "difficulty": row.difficulty,
        "split": row.split,
        "status": row.status,
        "tags": list(row.tags or []),
        "content_json": dict(row.content_json or {}),
        "reference_json": dict(row.reference_json) if row.reference_json else None,
        "rubric_version": row.rubric_version,
        "source_kind": row.source_kind,
        "source_ref": row.source_ref,
        "note": row.note,
    }


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------


def _effective_versions(session, scenario_key: str | None = None) -> list[SimulationScenario]:
    """返回每个 (scenario_key, variant) 的**最大版本行**（有效状态）。"""
    stmt = select(SimulationScenario)
    if scenario_key:
        stmt = stmt.where(SimulationScenario.scenario_key == scenario_key)
    rows = list(session.scalars(stmt.order_by(SimulationScenario.scenario_key, SimulationScenario.variant, SimulationScenario.version)))
    latest: dict[tuple[str, str], SimulationScenario] = {}
    for row in rows:
        latest[(row.scenario_key, row.variant)] = row
    return list(latest.values())


def list_scenarios(
    *,
    actor: User,
    split: str | None = None,
    industry: str | None = None,
    variant: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    include_history: bool = False,
    limit: int = LIST_PAGE_SIZE,
) -> dict[str, Any]:
    """场景库列表（默认只返回每个分支的有效版本）。"""
    _require_level(actor)
    if split is not None and split not in SCENARIO_SPLITS:
        raise ScenarioServiceError("invalid_request", "split 取值非法。")
    if variant is not None and variant not in SCENARIO_VARIANTS:
        raise ScenarioServiceError("invalid_request", "variant 取值非法。")
    if status is not None and status not in SCENARIO_STATUSES:
        raise ScenarioServiceError("invalid_request", "status 取值非法。")
    capped = max(1, min(int(limit), MAX_LIST_PAGE_SIZE))

    with db.session() as session:
        if include_history:
            stmt = select(SimulationScenario)
            if split:
                stmt = stmt.where(SimulationScenario.split == split)
            if industry:
                stmt = stmt.where(SimulationScenario.industry == industry)
            if variant:
                stmt = stmt.where(SimulationScenario.variant == variant)
            if status:
                stmt = stmt.where(SimulationScenario.status == status)
            rows = list(
                session.scalars(
                    stmt.order_by(
                        SimulationScenario.scenario_key,
                        SimulationScenario.variant,
                        SimulationScenario.version,
                    )
                )
            )
        else:
            rows = _effective_versions(session)
            if split:
                rows = [row for row in rows if row.split == split]
            if industry:
                rows = [row for row in rows if row.industry == industry]
            if variant:
                rows = [row for row in rows if row.variant == variant]
            if status:
                rows = [row for row in rows if row.status == status]
        if keyword:
            needle = keyword.strip().lower()
            rows = [
                row
                for row in rows
                if needle in row.name.lower() or needle in row.scenario_key.lower()
            ]
        total = len(rows)
        page = rows[:capped]
        return {
            "items": [_serialize(row) for row in page],
            "total": total,
            "truncated": total > len(page),
        }


def get_scenario(*, actor: User, scenario_id: str) -> dict[str, Any]:
    """场景详情（按 id）。"""
    _require_level(actor)
    with db.session() as session:
        row = session.get(SimulationScenario, scenario_id)
        if row is None:
            raise ScenarioServiceError("not_found", "场景不存在。", 404)
        return _serialize(row)


def list_versions(*, actor: User, scenario_key: str) -> dict[str, Any]:
    """某案例（业务键）的全部分支与版本历史。"""
    _require_level(actor)
    with db.session() as session:
        rows = list(
            session.scalars(
                select(SimulationScenario)
                .where(SimulationScenario.scenario_key == scenario_key)
                .order_by(
                    SimulationScenario.variant,
                    SimulationScenario.version,
                )
            )
        )
        return {
            "scenario_key": scenario_key,
            "items": [_serialize(row) for row in rows],
            "total": len(rows),
        }


# ---------------------------------------------------------------------------
# 写入
# ---------------------------------------------------------------------------


def _validate_payload(
    *,
    scenario_key: str,
    variant: str,
    split: str,
    content: Any,
    reference: Any,
) -> None:
    errors = validate_scenario(
        content, reference, scenario_key=scenario_key, variant=variant, split=split
    )
    if errors:
        raise ScenarioServiceError(
            "invalid_scenario",
            "场景内容校验未通过。",
            422,
            {
                "errors": errors,
                "messages": [ERROR_MESSAGES.get(code, code) for code in errors],
            },
        )


def _apply_variant_materialization(
    content: dict[str, Any], variant: str
) -> dict[str, Any]:
    """变体物化：基线场景 → 独立变体场景（移除 variant_overrides 本身）。"""
    if variant == "normal":
        materialized = materialize_variant(content, "normal")
        return materialized
    return materialize_variant(content, variant)


def create_scenario(*, actor: User, payload: dict[str, Any]) -> dict[str, Any]:
    """创建场景（版本 1）。content 必填；变体内容按 variant 物化。"""
    _require_level(actor)
    content = payload.get("content")
    if not isinstance(content, dict):
        raise ScenarioServiceError("invalid_request", "content 必填且必须是对象。")
    variant = payload.get("variant") or "normal"
    if variant not in SCENARIO_VARIANTS:
        raise ScenarioServiceError("invalid_request", "variant 取值非法。")
    split = payload.get("split") or "train"
    if split not in SCENARIO_SPLITS:
        raise ScenarioServiceError("invalid_request", "split 取值非法。")
    difficulty = payload.get("difficulty") or "standard"
    if difficulty not in SCENARIO_DIFFICULTIES:
        raise ScenarioServiceError("invalid_request", "difficulty 取值非法。")
    status = payload.get("status") or "draft"
    if status not in SCENARIO_STATUSES:
        raise ScenarioServiceError("invalid_request", "status 取值非法。")

    materialized = _apply_variant_materialization(content, variant)
    explicit_key = payload.get("scenario_key")
    if isinstance(explicit_key, str) and explicit_key.strip():
        scenario_key = explicit_key.strip()
        # 显式指定业务键时**不改写** content.case_code——两者不一致必须由
        # 校验器报出（scenario_key_mismatch），不得在此静默「修好」。
    else:
        derived_key = materialized.get("case_code")
        if not isinstance(derived_key, str) or not derived_key.strip():
            raise ScenarioServiceError("invalid_request", "scenario_key 必填。")
        scenario_key = derived_key.strip()
        materialized["case_code"] = scenario_key
    reference = payload.get("reference")
    _validate_payload(
        scenario_key=scenario_key,
        variant=variant,
        split=split,
        content=materialized,
        reference=reference,
    )
    name = payload.get("name") or materialized.get("case_code")

    with db.session() as session:
        existing = list(
            session.scalars(
                select(SimulationScenario).where(
                    SimulationScenario.scenario_key == scenario_key,
                    SimulationScenario.variant == variant,
                )
            )
        )
        if existing:
            raise ScenarioServiceError(
                "conflict",
                "该业务键与变体已存在，请改用编辑（追加新版本）。",
                409,
                {"scenario_key": scenario_key, "variant": variant},
            )
        row = SimulationScenario(
            scenario_key=scenario_key,
            name=str(name)[:160],
            industry=str(payload.get("industry") or materialized.get("industry") or "general")[:64],
            variant=variant,
            difficulty=difficulty,
            split=split,
            status=status,
            tags=normalize_tags(payload.get("tags")),
            content_json=materialized,
            reference_json=dict(reference) if isinstance(reference, dict) else None,
            rubric_version=str(payload.get("rubric_version") or "rubric-v1")[:32],
            source_kind=str(payload.get("source_kind") or "manual")[:16],
            source_ref=payload.get("source_ref"),
            note=payload.get("note"),
            created_by_user_id=actor.id,
            version=1,
        )
        session.add(row)
        session.flush()
        _record(
            session,
            actor,
            "simulation_scenario_created",
            row,
            {"scenario_key": row.scenario_key, "variant": row.variant, "version": row.version},
        )
        session.commit()
        return _serialize(row)


def update_scenario(
    *, actor: User, scenario_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """编辑场景 → **追加新版本**（既有版本不可变，不原地改）。"""
    _require_level(actor)
    with db.session() as session:
        current = session.get(SimulationScenario, scenario_id)
        if current is None:
            raise ScenarioServiceError("not_found", "场景不存在。", 404)
        if current.status == "archived":
            raise ScenarioServiceError(
                "conflict", "已归档场景不可编辑。", 409, {"scenario_id": scenario_id}
            )
        updates = dict(payload)
        variant = updates.get("variant") or current.variant
        split = updates.get("split") or current.split
        content = updates.get("content")
        if content is None:
            content = current.content_json
        if not isinstance(content, dict):
            raise ScenarioServiceError("invalid_request", "content 必须是对象。")
        materialized = _apply_variant_materialization(content, variant)
        # 未带 case_code 时继承既有值；带了但与业务键不一致 ⇒ 交校验器报错，
        # 不在此静默改写（与 create 同纪律）。
        if not isinstance(materialized.get("case_code"), str) or not materialized.get(
            "case_code"
        ):
            materialized["case_code"] = current.scenario_key
        reference = updates.get("reference", current.reference_json)
        _validate_payload(
            scenario_key=current.scenario_key,
            variant=variant,
            split=split,
            content=materialized,
            reference=reference,
        )
        versions = list(
            session.scalars(
                select(SimulationScenario.version).where(
                    SimulationScenario.scenario_key == current.scenario_key,
                    SimulationScenario.variant == variant,
                )
            )
        )
        derived = derive_next_row(
            _row_to_dict(current),
            {
                **updates,
                "variant": variant,
                "split": split,
                "content_json": materialized,
                "reference_json": dict(reference) if isinstance(reference, dict) else None,
                "tags": normalize_tags(updates.get("tags", current.tags)),
            },
            next_version_number=next_version(versions),
        )
        row = SimulationScenario(
            scenario_key=derived["scenario_key"],
            name=str(derived["name"])[:160],
            industry=str(derived["industry"])[:64],
            variant=derived["variant"],
            difficulty=derived["difficulty"],
            split=derived["split"],
            status=derived["status"],
            tags=list(derived["tags"]),
            content_json=derived["content_json"],
            reference_json=derived["reference_json"],
            rubric_version=derived["rubric_version"],
            source_kind=derived["source_kind"],
            source_ref=derived["source_ref"],
            note=derived["note"],
            created_by_user_id=actor.id,
            version=derived["version"],
        )
        session.add(row)
        session.flush()
        _record(
            session,
            actor,
            "simulation_scenario_versioned",
            row,
            {
                "scenario_key": row.scenario_key,
                "variant": row.variant,
                "version": row.version,
                "previous_version": current.version,
            },
        )
        session.commit()
        return _serialize(row)


def duplicate_scenario(
    *, actor: User, scenario_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """复制场景 → 新业务键（版本 1）。"""
    _require_level(actor)
    with db.session() as session:
        source = session.get(SimulationScenario, scenario_id)
        if source is None:
            raise ScenarioServiceError("not_found", "场景不存在。", 404)
        new_key = payload.get("scenario_key")
        if not isinstance(new_key, str) or not new_key.strip():
            raise ScenarioServiceError("invalid_request", "scenario_key 必填。")
        new_key = new_key.strip()
        clash = session.scalar(
            select(func.count())
            .select_from(SimulationScenario)
            .where(
                SimulationScenario.scenario_key == new_key,
                SimulationScenario.variant == source.variant,
            )
        )
        if clash:
            raise ScenarioServiceError(
                "conflict", "目标业务键已存在。", 409, {"scenario_key": new_key}
            )
        content = dict(source.content_json or {})
        content["case_code"] = new_key
        row = SimulationScenario(
            scenario_key=new_key,
            name=str(payload.get("name") or f"{source.name}（副本）")[:160],
            industry=source.industry,
            variant=source.variant,
            difficulty=source.difficulty,
            split=payload.get("split") or source.split,
            status="draft",
            tags=list(source.tags or []),
            content_json=content,
            reference_json=dict(source.reference_json) if source.reference_json else None,
            rubric_version=source.rubric_version,
            source_kind="manual",
            source_ref=f"duplicate_of:{source.id}",
            note=payload.get("note"),
            created_by_user_id=actor.id,
            version=1,
        )
        session.add(row)
        session.flush()
        _record(
            session,
            actor,
            "simulation_scenario_duplicated",
            row,
            {"source_id": source.id, "scenario_key": row.scenario_key},
        )
        session.commit()
        return _serialize(row)


def archive_scenario(*, actor: User, scenario_id: str) -> dict[str, Any]:
    """归档场景 → 追加一个 status=archived 的新版本（历史版本仍可运行）。"""
    _require_level(actor)
    with db.session() as session:
        current = session.get(SimulationScenario, scenario_id)
        if current is None:
            raise ScenarioServiceError("not_found", "场景不存在。", 404)
        versions = list(
            session.scalars(
                select(SimulationScenario.version).where(
                    SimulationScenario.scenario_key == current.scenario_key,
                    SimulationScenario.variant == current.variant,
                )
            )
        )
        derived = derive_next_row(
            _row_to_dict(current),
            {"status": "archived"},
            next_version_number=next_version(versions),
        )
        row = SimulationScenario(
            scenario_key=derived["scenario_key"],
            name=derived["name"],
            industry=derived["industry"],
            variant=derived["variant"],
            difficulty=derived["difficulty"],
            split=derived["split"],
            status="archived",
            tags=list(derived["tags"]),
            content_json=derived["content_json"],
            reference_json=derived["reference_json"],
            rubric_version=derived["rubric_version"],
            source_kind=derived["source_kind"],
            source_ref=derived["source_ref"],
            note=derived["note"],
            created_by_user_id=actor.id,
            version=derived["version"],
        )
        session.add(row)
        session.flush()
        _record(
            session,
            actor,
            "simulation_scenario_archived",
            row,
            {"scenario_key": row.scenario_key, "variant": row.variant},
        )
        session.commit()
        return _serialize(row)


def import_scenarios(*, actor: User, payload: dict[str, Any]) -> dict[str, Any]:
    """批量导入场景（逐条校验；非法条目不阻断其余条目，错误逐条回显）。"""
    _require_level(actor)
    items = payload.get("scenarios")
    if not isinstance(items, list) or not items:
        raise ScenarioServiceError("invalid_request", "scenarios 必填且必须是非空数组。")
    created: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            failures.append({"index": index, "code": "invalid_request", "message": "条目必须是对象。"})
            continue
        try:
            created.append(create_scenario(actor=actor, payload=item))
        except ScenarioServiceError as error:
            failures.append(
                {"index": index, "code": error.code, "message": error.message, "detail": error.detail}
            )
    return {"created": created, "created_count": len(created), "failures": failures}


def export_scenarios(
    *,
    actor: User,
    scenario_key: str | None = None,
    split: str | None = None,
    variant: str | None = None,
    include_reference: bool = True,
) -> dict[str, Any]:
    """导出现场景（有效版本）。默认含参考答案——导出是运营者操作。"""
    _require_level(actor)
    with db.session() as session:
        rows = _effective_versions(session, scenario_key)
        if split:
            rows = [row for row in rows if row.split == split]
        if variant:
            rows = [row for row in rows if row.variant == variant]
        items: list[dict[str, Any]] = []
        for row in rows:
            item: dict[str, Any] = {
                "scenario_key": row.scenario_key,
                "name": row.name,
                "industry": row.industry,
                "variant": row.variant,
                "difficulty": row.difficulty,
                "split": row.split,
                "status": row.status,
                "tags": list(row.tags or []),
                "rubric_version": row.rubric_version,
                "content": dict(row.content_json or {}),
            }
            if include_reference:
                item["reference"] = dict(row.reference_json) if row.reference_json else None
            items.append(item)
        return {"items": items, "total": len(items)}
