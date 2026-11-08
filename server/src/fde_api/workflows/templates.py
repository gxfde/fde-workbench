"""Workflow 平台模板种子通道（V3.1 P0-4，00-gap-register 4.5/4.6）。

底座复用既有两件（不新建表/列）：``project_id NULL`` = 平台模板定义
（workflows/models.py），发布通道 = ``publish_definition`` 锁版快照。本模块只补三件：

1. 种子文件装载（``seeds/workflow-templates.json``，任务书 §8 第一批三套模板：
   需求发现/方案实施/自动化交付，全部用既有四类节点表达）——fail-fast 形状校验 +
   进程级缓存（沿 agents/tools.py 的 tool_groups.json 装载先例）；
2. 幂等落库 ``seed_workflow_templates``（沿 builtin_skills.seed_public_skills 先例：
   active admin 为 actor；种子内容可信，落库即经 ``publish_definition`` 锁版）。
   幂等锚 = 平台定义行 name（种子名单受控；已存在即跳过，绝不覆盖人工改动——
   模板演进走新模板名，存量行不改，语义同 T-G2 存量冻结）。种子 dag 落库前过
   ``validate_dag_against_registry`` 全量校验：白名单缺引用 → fail-fast
   （部署顺序：先 ``seed-public-skills`` 再 ``seed-workflow-templates``）；
3. 已认证只读浏览面 ``list_published_templates``（模板是产品能力目录而非敏感
   资产，dag 全文携带；发布权限维持 admin-only = 拍板项 D-2 裁决）。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.workflows.definition_service import (
    NODE_KEY_PATTERN,
    NAME_PATTERN,
    assert_valid_dag,
    create_definition,
    publish_definition,
    validate_dag_against_registry,
)
from fde_api.workflows.models import NODE_TYPES, WorkflowDefinition

_SEEDS_DIR = Path(__file__).resolve().parents[3] / "seeds"
_TEMPLATE_FIELDS = {"key", "name", "description", "dag"}
# 允许出现在种子模板里的节点契约字段白名单子集——模板是平台的确定性资产，
# 超出本集合的（如 plan_ref）只应出现在项目内草稿，不进种子。
_TEMPLATE_NODE_FIELDS = {
    "key", "type", "ref", "depends_on", "output", "max_retries", "params",
    "capability", "expires_minutes", "timeout_seconds", "failure_class",
    "input_schema", "output_schema",
}


def _load_seeds(path: Path) -> tuple[dict[str, Any], ...]:
    """种子文件 → 形状校验后的模板元组（fail-fast；坏种子宁可拒绝启动不静默吞）。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise RuntimeError("workflow-templates.json seed unavailable") from error
    if not isinstance(raw, list) or not raw:
        raise RuntimeError("workflow-templates.json seed empty")
    seen_keys: set[str] = set()
    seen_names: set[str] = set()
    templates: list[dict[str, Any]] = []
    for index, row in enumerate(raw):
        if not isinstance(row, dict) or set(row) - _TEMPLATE_FIELDS or set(row) != _TEMPLATE_FIELDS:
            raise RuntimeError(f"workflow-templates.json seed row {index} invalid")
        key = row["key"]
        name = row["name"]
        if not isinstance(key, str) or not NODE_KEY_PATTERN.fullmatch(key) or key in seen_keys:
            raise RuntimeError(f"workflow-templates.json seed row {index} invalid key")
        if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name) or name in seen_names:
            raise RuntimeError(f"workflow-templates.json seed row {index} invalid name")
        seen_keys.add(key)
        seen_names.add(name)
        dag = row["dag"]
        if not isinstance(dag, dict) or not isinstance(dag.get("nodes"), list) or not dag["nodes"]:
            raise RuntimeError(f"workflow-templates.json seed row {index} dag invalid")
        for node in dag["nodes"]:
            if not isinstance(node, dict) or set(node) - _TEMPLATE_NODE_FIELDS:
                raise RuntimeError(f"workflow-templates.json seed row {index} node invalid")
            if node.get("type") not in NODE_TYPES:
                raise RuntimeError(f"workflow-templates.json seed row {index} node type invalid")
        description = row["description"]
        if not isinstance(description, str) or not description.strip():
            raise RuntimeError(f"workflow-templates.json seed row {index} description invalid")
        templates.append({"key": key, "name": name, "description": description.strip(), "dag": dag})
    return tuple(templates)


@lru_cache(maxsize=1)
def load_workflow_template_seeds() -> tuple[dict[str, Any], ...]:
    """种子模板（进程级缓存——文件烘进镜像只读，装载一次足够）。"""
    return _load_seeds(_SEEDS_DIR / "workflow-templates.json")


def seed_workflow_templates(session: Session) -> dict[str, int]:
    """平台模板幂等落库：缺失的创建并锁版发布，已存在的跳过（绝不覆盖）。

    返回 ``{"created": 本轮新建数, "total": 种子总数}``。白名单缺引用
    （published skill / catalog call）时由 ``validate_dag_against_registry`` 抛
    ``WorkflowDefinitionError``——部署顺序必须先 seed-public-skills。
    """
    admin = session.scalar(
        select(User)
        .where(User.role == "admin", User.is_active.is_(True))
        .order_by(User.id)
        .limit(1)
    )
    if admin is None:
        raise RuntimeError("active_admin_required")
    seeds = load_workflow_template_seeds()
    existing_names = set(
        session.scalars(
            select(WorkflowDefinition.name).where(WorkflowDefinition.project_id.is_(None))
        )
    )
    created = 0
    for seed in seeds:
        if seed["name"] in existing_names:
            continue
        assert_valid_dag(validate_dag_against_registry(session, seed["dag"]))
        definition = create_definition(
            session,
            actor=admin,
            project_id=None,
            name=seed["name"],
            dag=seed["dag"],
            description=seed["description"],
        )
        publish_definition(session, actor=admin, definition=definition)
        created += 1
    return {"created": created, "total": len(seeds)}


def list_published_templates(session: Session) -> list[dict[str, Any]]:
    """已发布平台模板只读投影（已认证可见；不含 draft/archived）。"""
    rows = session.scalars(
        select(WorkflowDefinition)
        .where(WorkflowDefinition.project_id.is_(None), WorkflowDefinition.status == "published")
        .order_by(WorkflowDefinition.published_at.desc(), WorkflowDefinition.id.asc())
    ).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "version": row.version,
            "status": row.status,
            "content_sha256": row.content_sha256,
            "published_at": row.published_at.isoformat() if row.published_at else None,
            "nodes": [
                {"key": node.get("key"), "type": node.get("type")}
                for node in row.dag_json.get("nodes", [])
                if isinstance(node, dict)
            ],
            "dag_json": row.dag_json,
        }
        for row in rows
    ]
