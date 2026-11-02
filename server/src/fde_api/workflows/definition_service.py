"""Workflow 定义服务（V3 T-W1；设计 workflow-dag-v1 §2「dag_json schema」+ §5）。

两块职责：
1. ``validate_dag``——**纯函数**，不触库：环检测（Kahn 拓扑，修 fde-v2 FV-F1）、
   未知引用、call.ref 白名单（api_catalog ENTRIES，封 SSRF 面）、skill.ref 必须是
   存在的 active skill 版本（显式 `key@版本号`）、agent.ref 必须可用、output 唯一、
   {{placeholder}} 必须是运行上下文键或**传递上游**节点的 output、节点字段白名单。
   规则 9（外部副作用须审批）P1 只告警不阻断（工具目录 effect 结构化在 T-R2）。
2. 定义生命周期：create（draft v1）→ update（已发布则自动开新草稿版本）→
   publish（快照成不可变版本行，发布时按**当前**白名单再校验一次）。路由在 §5，
   随 T-W3 执行器一起开（backlog T-W1 文件清单不含 routes）。
"""
from __future__ import annotations

import json
import re
from collections.abc import Collection
from datetime import datetime, timezone
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.agents.models import AgentRegistry
from fde_api.auth.models import User
from fde_api.control.api_catalog import CATALOG
from fde_api.control.models import SkillDefinition, SkillVersion
from fde_api.projects.events import record_event
from fde_api.workflows.models import NODE_TYPES, WorkflowDefinition, WorkflowDefinitionVersion

NODE_KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,59}")
NAME_PATTERN = re.compile(r".{1,120}", re.DOTALL)
SKILL_REF_PATTERN = re.compile(
    r"(?P<key>[A-Za-z0-9][A-Za-z0-9_.-]{0,99})@(?P<version>[1-9][0-9]{0,5})"
)
PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}")
# 运行上下文键（run 级入参），与节点 output 同占位符语法；design 示例即 {{project_id}}
DEFAULT_CONTEXT_KEYS = frozenset({"project_id", "run_id", "initiated_by_user_id"})
MAX_RETRIES_LIMIT = 10
APPROVAL_EXPIRES_RANGE = (1, 24 * 60)


class WorkflowDefinitionError(Exception):
    def __init__(self, code: str, message: str, status: int, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail or {}


@dataclass(frozen=True)
class DagIssue:
    code: str
    message: str
    node_key: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "node_key": self.node_key,
        }
        if self.detail:
            payload["detail"] = self.detail
        return payload


@dataclass(frozen=True)
class DagValidation:
    errors: tuple[DagIssue, ...]
    warnings: tuple[DagIssue, ...]
    order: tuple[str, ...]  # 无环时的确定性拓扑序；有环为 ()

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------------
# 纯函数（不触库）
# ---------------------------------------------------------------------------


def canonical_dag_json(dag: Any) -> str:
    """规范化 JSON（键序 + 紧凑 + 非ASCII原样）：content_sha256 的指纹基础。"""
    return json.dumps(dag, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dag_sha256(dag: Any) -> str:
    return sha256(canonical_dag_json(dag).encode("utf-8")).hexdigest()


def _placeholders(value: Any, found: list[str] | None = None) -> list[str]:
    found = [] if found is None else found
    if isinstance(value, str):
        found.extend(PLACEHOLDER_PATTERN.findall(value))
    elif isinstance(value, dict):
        for item in value.values():
            _placeholders(item, found)
    elif isinstance(value, list):
        for item in value:
            _placeholders(item, found)
    return found


def validate_dag(
    dag: Any,
    *,
    call_refs: Collection[str],
    skill_refs: Collection[str],
    agent_refs: Collection[str],
    context_keys: Collection[str] = DEFAULT_CONTEXT_KEYS,
) -> DagValidation:
    """dag_json 校验纯函数：返回 (errors, warnings, 拓扑序)；白名单由调用方注入。"""
    if not isinstance(dag, dict):
        return DagValidation((DagIssue("dag_not_object", "dag_json 必须是对象。"),), (), ())
    errors: list[DagIssue] = []
    warnings: list[DagIssue] = []
    unknown_top = set(dag) - {"nodes"}
    if unknown_top:
        errors.append(
            DagIssue("unknown_field", f"dag_json 不支持字段：{'、'.join(sorted(unknown_top))}。")
        )
    nodes = dag.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errors.append(DagIssue("nodes_required", "nodes 必须是非空数组。"))
        return DagValidation(tuple(errors), (), ())

    # 1. key 唯一、非空、模式约束 + 节点字段白名单
    by_key: dict[str, dict[str, Any]] = {}
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(DagIssue("node_not_object", f"nodes[{index}] 必须是对象。"))
            continue
        key = node.get("key")
        if not isinstance(key, str) or not NODE_KEY_PATTERN.fullmatch(key):
            errors.append(
                DagIssue(
                    "invalid_node_key",
                    "key 须为 1–60 字符、以小写字母开头，仅含小写字母/数字/下划线。",
                    detail={"index": index},
                )
            )
            continue
        if key in by_key:
            errors.append(DagIssue("duplicate_node_key", f"节点 key 重复：{key}。", key))
            continue
        by_key[key] = node

    allowed_node_fields = {
        "key", "type", "ref", "depends_on", "when", "output", "max_retries",
        "params", "max_cost_units", "capability", "expires_minutes", "effect",
    }
    outputs: dict[str, str] = {}
    deps_map: dict[str, list[str]] = {}
    for key, node in by_key.items():
        extra = set(node) - allowed_node_fields
        if extra:
            errors.append(
                DagIssue("unknown_field", f"节点 {key} 不支持字段：{'、'.join(sorted(extra))}。", key)
            )
        node_type = node.get("type")
        if node_type not in NODE_TYPES:
            errors.append(
                DagIssue("unknown_node_type", f"节点 {key} 的 type 须为 {'/'.join(NODE_TYPES)}。", key)
            )
        deps = node.get("depends_on")
        if deps is None:
            deps = []
        if not isinstance(deps, list) or not all(isinstance(dep, str) for dep in deps):
            errors.append(DagIssue("invalid_depends_on", f"节点 {key} 的 depends_on 须为字符串数组。", key))
            deps = []
        clean_deps: list[str] = []
        for dep in deps:
            if dep == key:
                errors.append(DagIssue("self_dependency", f"节点 {key} 依赖自身。", key))
            elif dep not in by_key:
                errors.append(
                    DagIssue(
                        "unknown_dependency",
                        f"节点 {key} 依赖不存在的节点：{dep}。",
                        key,
                        {"dependency": dep},
                    )
                )
            else:
                clean_deps.append(dep)
        deps_map[key] = clean_deps
        when = node.get("when")
        if when is not None and (not isinstance(when, str) or not when.strip()):
            errors.append(DagIssue("invalid_when", f"节点 {key} 的 when 须为非空表达式字符串或 null。", key))
        output = node.get("output")
        if output is not None:
            if not isinstance(output, str) or not NODE_KEY_PATTERN.fullmatch(output):
                errors.append(
                    DagIssue("invalid_output", f"节点 {key} 的 output 须为 1–60 字符的标识符。", key)
                )
            elif output in context_keys:
                errors.append(
                    DagIssue("output_shadows_context", f"节点 {key} 的 output 与运行上下文键冲突：{output}。", key)
                )
            elif output in outputs:
                errors.append(
                    DagIssue("duplicate_output", f"output 名重复：{output}（{outputs[output]} 与 {key}）。", key)
                )
            else:
                outputs[output] = key
        max_retries = node.get("max_retries", 0)
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or not 0 <= max_retries <= MAX_RETRIES_LIMIT:
            errors.append(
                DagIssue("invalid_max_retries", f"节点 {key} 的 max_retries 须为 0–{MAX_RETRIES_LIMIT} 的整数。", key)
            )
        params = node.get("params", {})
        if params is not None and not isinstance(params, dict):
            errors.append(DagIssue("invalid_params", f"节点 {key} 的 params 须为对象。", key))
        effect = node.get("effect")
        if effect is not None and effect not in ("read", "external"):
            errors.append(DagIssue("invalid_effect", f"节点 {key} 的 effect 须为 read 或 external。", key))

        ref = node.get("ref")
        if node_type == "call":
            if not isinstance(ref, str) or ref not in call_refs:
                errors.append(
                    DagIssue(
                        "call_ref_not_whitelisted",
                        f"节点 {key} 的 call.ref 不在 api_catalog 白名单：{ref!r}。",
                        key,
                        {"ref": ref},
                    )
                )
        elif node_type == "skill":
            if not isinstance(ref, str) or SKILL_REF_PATTERN.fullmatch(ref) is None:
                errors.append(
                    DagIssue(
                        "invalid_skill_ref",
                        f"节点 {key} 的 skill.ref 须为 <skill_key>@<版本号>（显式版本）。",
                        key,
                        {"ref": ref},
                    )
                )
            elif ref not in skill_refs:
                errors.append(
                    DagIssue(
                        "skill_ref_not_published",
                        f"节点 {key} 引用的 skill 版本不存在或未发布：{ref}。",
                        key,
                        {"ref": ref},
                    )
                )
        elif node_type == "agent":
            if not isinstance(ref, str) or ref not in agent_refs:
                errors.append(
                    DagIssue(
                        "agent_ref_unavailable",
                        f"节点 {key} 引用的 agent 不存在或未启用：{ref!r}。",
                        key,
                        {"ref": ref},
                    )
                )
            max_cost = node.get("max_cost_units", 0)
            if isinstance(max_cost, bool) or not isinstance(max_cost, int) or max_cost < 0:
                errors.append(DagIssue("invalid_max_cost_units", f"节点 {key} 的 max_cost_units 须为非负整数。", key))
        elif node_type == "human_approval":
            if ref is not None:
                errors.append(DagIssue("unexpected_ref", f"human_approval 节点不接受 ref。", key))
            capability = node.get("capability")
            if not isinstance(capability, str) or not capability.strip():
                errors.append(DagIssue("approval_capability_required", f"human_approval 节点 {key} 必填 capability。", key))
            expires = node.get("expires_minutes", 15)
            low, high = APPROVAL_EXPIRES_RANGE
            if isinstance(expires, bool) or not isinstance(expires, int) or not low <= expires <= high:
                errors.append(
                    DagIssue("invalid_expires_minutes", f"节点 {key} 的 expires_minutes 须为 {low}–{high} 的整数。", key)
                )

    # 2. 环检测 = Kahn 拓扑排序（修 fde-v2 FV-F1）；只沿已知依赖走
    indegree = {key: len(deps) for key, deps in deps_map.items()}
    children: dict[str, list[str]] = {key: [] for key in by_key}
    for key, deps in deps_map.items():
        for dep in deps:
            children[dep].append(key)
    queue = sorted(key for key, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while queue:
        key = queue.pop(0)
        order.append(key)
        for child in children[key]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
                queue.sort()
    if len(order) != len(by_key):
        cyclic = sorted(key for key in by_key if key not in order)
        errors.append(
            DagIssue(
                "cycle_detected",
                f"依赖成环，涉及节点：{'、'.join(cyclic)}。",
                None,
                {"nodes": cyclic},
            )
        )
        order = []

    # 8. 占位符：运行上下文键 或 传递上游节点的 output
    if order:
        ancestors: dict[str, set[str]] = {}
        for key in order:
            ancestor_set: set[str] = set()
            for dep in deps_map[key]:
                ancestor_set.add(dep)
                ancestor_set |= ancestors[dep]
            ancestors[key] = ancestor_set
        for key, node in by_key.items():
            visible_outputs = {
                name for name, owner in outputs.items() if owner in ancestors[key]
            }
            scanned: list[str] = []
            scanned.extend(_placeholders(node.get("params", {})))
            when = node.get("when")
            if isinstance(when, str):
                scanned.extend(_placeholders(when))
            for placeholder in scanned:
                root = placeholder.split(".", 1)[0]
                if root in context_keys or root in visible_outputs:
                    continue
                if root in outputs:
                    errors.append(
                        DagIssue(
                            "placeholder_not_upstream",
                            f"节点 {key} 引用的 {{{{{placeholder}}}}} 由 {outputs[root]} 产出，但其不是本节点上游。",
                            key,
                            {"placeholder": placeholder, "producer": outputs[root]},
                        )
                    )
                else:
                    errors.append(
                        DagIssue(
                            "unknown_placeholder",
                            f"节点 {key} 引用了未声明的占位符 {{{{{placeholder}}}}}。",
                            key,
                            {"placeholder": placeholder},
                        )
                    )

    # 9. 外部副作用须审批：P1 告警不阻断（effect 结构化在 T-R2，P2 转强制）
    if order:
        descendants: dict[str, set[str]] = {key: set() for key in by_key}
        for key in reversed(order):
            descendant_set: set[str] = set()
            for child in children[key]:
                descendant_set.add(child)
                descendant_set |= descendants[child]
            descendants[key] = descendant_set
        for key, node in by_key.items():
            if node.get("type") == "call" and node.get("effect") == "external":
                if not any(
                    by_key[descendant].get("type") == "human_approval"
                    for descendant in descendants[key]
                ):
                    warnings.append(
                        DagIssue(
                            "external_effect_without_approval",
                            f"节点 {key} 声明外部副作用但下游无 human_approval（P1 告警，P2 强制）。",
                            key,
                        )
                    )
    return DagValidation(tuple(errors), tuple(warnings), tuple(order))


def assert_valid_dag(validation: DagValidation) -> None:
    if validation.ok:
        return
    raise WorkflowDefinitionError(
        "dag_invalid",
        "工作流定义校验未通过，详见 issues。",
        422,
        {
            "errors": [issue.as_dict() for issue in validation.errors],
            "warnings": [issue.as_dict() for issue in validation.warnings],
        },
    )


# ---------------------------------------------------------------------------
# 白名单装配（库 → 纯函数入参）
# ---------------------------------------------------------------------------


def catalog_call_refs() -> frozenset[str]:
    """call.ref 白名单 = api_catalog ENTRIES（封 SSRF 面）。"""
    return frozenset(CATALOG)


def published_skill_refs(session: Session) -> frozenset[str]:
    """skill.ref 白名单 = active skill 的既有版本号 `skill_key@version_number`（T-S1 起收敛为 published 语义）。"""
    rows = session.execute(
        select(SkillDefinition.skill_key, SkillVersion.version_number)
        .join(SkillVersion, SkillVersion.skill_id == SkillDefinition.id)
        .where(SkillDefinition.status == "active")
    ).all()
    return frozenset(f"{skill_key}@{version}" for skill_key, version in rows)


def available_agent_refs(session: Session) -> frozenset[str]:
    """agent.ref 白名单 = 已启用的 agent_registry.id。"""
    return frozenset(
        session.scalars(select(AgentRegistry.id).where(AgentRegistry.enabled.is_(True)))
    )


def validate_dag_against_registry(session: Session, dag: Any) -> DagValidation:
    return validate_dag(
        dag,
        call_refs=catalog_call_refs(),
        skill_refs=published_skill_refs(session),
        agent_refs=available_agent_refs(session),
    )


# ---------------------------------------------------------------------------
# 定义生命周期（无 HTTP 路由——§5 路由随 T-W3 执行器一起开）
# ---------------------------------------------------------------------------


def _assert_name(name: object) -> str:
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name.strip() if isinstance(name, str) else ""):
        raise WorkflowDefinitionError("invalid_request", "name 必须是 1–120 字符。", 400)
    return name.strip()


def _assert_dag_payload(dag: object) -> dict[str, Any]:
    if not isinstance(dag, dict) or not isinstance(dag.get("nodes"), list) or not dag["nodes"]:
        raise WorkflowDefinitionError("invalid_request", "dag_json 必须是含非空 nodes 数组的对象。", 400)
    return dag


def create_definition(
    session: Session,
    *,
    actor: User,
    project_id: str | None,
    name: str,
    dag: dict[str, Any],
    description: str | None = None,
) -> WorkflowDefinition:
    clean_name = _assert_name(name)
    _assert_dag_payload(dag)
    assert_valid_dag(validate_dag_against_registry(session, dag))
    definition = WorkflowDefinition(
        project_id=project_id,
        name=clean_name,
        description=(description or "").strip() or None,
        dag_json=dag,
        status="draft",
        version=1,
        content_sha256=dag_sha256(dag),
        created_by_user_id=actor.id,
    )
    session.add(definition)
    session.flush()
    record_event(
        session,
        actor,
        "workflow_definition_created",
        definition,
        {
            "name": definition.name,
            "version": definition.version,
            "content_sha256": definition.content_sha256,
            "node_count": len(dag["nodes"]),
        },
    )
    return definition


def update_definition_dag(
    session: Session, *, actor: User, definition: WorkflowDefinition, dag: dict[str, Any]
) -> WorkflowDefinition:
    if definition.status == "archived":
        raise WorkflowDefinitionError("definition_archived", "该定义已归档，不能修改。", 409)
    _assert_dag_payload(dag)
    assert_valid_dag(validate_dag_against_registry(session, dag))
    new_sha = dag_sha256(dag)
    if definition.content_sha256 == new_sha:
        raise WorkflowDefinitionError("definition_unchanged", "定义内容未变化。", 409)
    if definition.status == "published":
        # 已发布版本锁定：再改动自动开新草稿版本（版本行不可变，旧版本原样保留）
        definition.version += 1
        definition.status = "draft"
        definition.published_by_user_id = None
        definition.published_at = None
    definition.dag_json = dag
    definition.content_sha256 = new_sha
    session.flush()
    record_event(
        session,
        actor,
        "workflow_definition_updated",
        definition,
        {"version": definition.version, "content_sha256": new_sha, "status": definition.status},
    )
    return definition


def publish_definition(
    session: Session, *, actor: User, definition: WorkflowDefinition
) -> WorkflowDefinitionVersion:
    if definition.status == "archived":
        raise WorkflowDefinitionError("definition_archived", "该定义已归档，不能发布。", 409)
    if definition.status == "published":
        raise WorkflowDefinitionError(
            "already_published", f"版本 {definition.version} 已发布；修改定义会自动开新草稿版本。", 409
        )
    # 发布前按当前白名单再校验（catalog / skill / agent 可能已变）
    assert_valid_dag(validate_dag_against_registry(session, definition.dag_json))
    now = datetime.now(timezone.utc)
    version = WorkflowDefinitionVersion(
        definition_id=definition.id,
        version=definition.version,
        dag_json=definition.dag_json,
        content_sha256=definition.content_sha256 or dag_sha256(definition.dag_json),
        published_by_user_id=actor.id,
        published_at=now,
    )
    session.add(version)
    definition.status = "published"
    definition.published_by_user_id = actor.id
    definition.published_at = now
    session.flush()
    record_event(
        session,
        actor,
        "workflow_definition_published",
        definition,
        {"version": definition.version, "content_sha256": version.content_sha256},
    )
    return version


def list_versions(session: Session, definition_id: str) -> list[WorkflowDefinitionVersion]:
    return list(
        session.scalars(
            select(WorkflowDefinitionVersion)
            .where(WorkflowDefinitionVersion.definition_id == definition_id)
            .order_by(WorkflowDefinitionVersion.version.asc())
        )
    )
