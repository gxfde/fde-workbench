"""Delivery Compiler 最小闭环（V3 T-C1；主报告 §12）。

confirmed 本体变更集 + 已发布行业模板 + 门禁状态摘要 → 两类**草稿**（纯函数，
不触库、零副作用；落库一律走人工确认端点——骨架 → POST /solutions（solutions.create），
定义 → workflow 定义创建路由，两端点各自做白名单校验）：

1. 方案骨架 payload：与 solutions.create 文本合同逐键对齐（TEXT_FIELDS 七键
   name+六段，限长同尺），全部段落保留「待补」标记——编译器只做结构化搬运，
   人工修订后才可导出 SOW（沿 /skeleton 的「责任主体永远是人」语义）。
2. workflow 定义草稿：dag_json 模板化「调研→方案→审阅」三节点——调研 skill
   ref 由调用方注入（published 白名单在 DB，纯函数不查库，沿 validate_dag
   白名单注入制）；方案节点 call solutions.create 携带编译期已知的骨架字段，
   仅 opportunity_ids 留 ``{{research_brief.opportunity_ids}}`` 运行期占位
   （执行器整值替换、原类型不字符串化）；审阅 human_approval 收口
   （capability 默认 workbench.write，system.* 不开放给工作流审批）。

来源标注（agent_trace 式）：输出携带 provenance 段，逐字段指认来源
（change_set / industry_template / gates / delivery-compiler 本身）。

不做全自动「本体→代码」：fde-v2 的构建期形态依赖外部代理施工，不适合 WB
服务端定位（主报告 §12 裁决原文）。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fde_api.workflows.definition_service import (
    APPROVAL_CAPABILITIES,
    SKILL_REF_PATTERN,
)

# 与 solutions.create 文本合同同尺（TEXT_FIELDS 限长：name 160 / design_markdown
# 40000 / 其余 16000）——编译产物合并运行期 opportunity_ids 后必须原样可过
# solutions.service._normalize。
_FIELD_LIMITS = {"name": 160, "design_markdown": 40000}
_DEFAULT_FIELD_LIMIT = 16000

# 编译器消费的变更集动作（T-O3 CHANGE_SET_ACTIONS 子集；register_relation_type
# 只进 provenance 不产骨架行）
_TERM_ACTIONS = ("create_term", "update_term")
_TERM_TYPE_LABELS = {"entity": "实体", "attribute": "属性", "metric": "指标"}


class DeliveryCompileError(ValueError):
    """编译预览输入不合法（未确认变更集 / 坏 skill ref / 坏 capability / 坏载荷）。"""


def _clean(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _truncate(value: str, limit: int) -> str:
    return value.strip()[:limit]


def _parse_terms(items: Sequence[Any]) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """变更集载荷 → （本体段行, 指标术语名, 合并对）。

    术语行按载荷原序（评审顺序即叙述顺序）；update_term 以 new_term 为准并
    标注原名。形状坏到无法搬运即抛错——纯函数不吞候选垃圾。
    """
    ontology_lines: list[str] = []
    metric_terms: list[str] = []
    merges: list[tuple[str, str]] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise DeliveryCompileError(
                f"invalid_change_set_item: 第 {index + 1} 项不是对象。"
            )
        action = item.get("action")
        if action in _TERM_ACTIONS:
            renamed = _clean(item.get("new_term"))
            name = renamed or _clean(item.get("term"))
            definition = _clean(item.get("definition"))
            term_type = _clean(item.get("term_type")) or "generic"
            origin = _clean(item.get("term"))
            if not name or not definition:
                raise DeliveryCompileError(
                    f"invalid_change_set_item: 第 {index + 1} 项（{action}）缺 term/definition。"
                )
            note = f"（原「{origin}」修订）" if action == "update_term" and renamed and origin != renamed else ""
            label = _TERM_TYPE_LABELS.get(term_type, "术语")
            ontology_lines.append(f"- {label}｜{name}{note}：{definition}")
            if term_type == "metric":
                metric_terms.append(name)
        elif action == "merge_terms":
            source = _clean(item.get("source_term"))
            target = _clean(item.get("target_term"))
            if not source or not target:
                raise DeliveryCompileError(
                    f"invalid_change_set_item: 第 {index + 1} 项（merge_terms）缺 source/target。"
                )
            merges.append((source, target))
        elif action == "register_relation_type":
            continue  # 类型登记不进骨架文本，只在 provenance 计数
        else:
            raise DeliveryCompileError(
                f"invalid_change_set_item: 第 {index + 1} 项动作未知：{action!r}。"
            )
    return ontology_lines, metric_terms, merges


def _template_modules(industry_template: Mapping[str, Any]) -> list[str]:
    """已发布模板版本 → 按 (sort_order, name) 排序的模块名列表（/skeleton 同序）。"""
    raw_modules = industry_template.get("modules")
    if raw_modules is None:
        raw_modules = []
    if not isinstance(raw_modules, list):
        raise DeliveryCompileError("invalid_template: modules 须为数组。")
    rows: list[tuple[tuple[int, str], str]] = []
    for row in raw_modules:
        if not isinstance(row, Mapping):
            continue
        name = _clean(row.get("name"))
        if not name:
            continue
        order = row.get("sort_order")
        sort_key = (order, name) if isinstance(order, int) and not isinstance(order, bool) else (0, name)
        rows.append((sort_key, name))
    return [name for _, name in sorted(rows)]


def _gate_lines(gates: Sequence[Mapping[str, Any]]) -> list[str]:
    """门禁状态摘要（T-D1 _serialize_gates 形状）→ 风险与依赖段行，按 gate_key 排序。

    只消费 gate_key/status/decision；形状不整的行跳过（摘要是建议性输入，
    单行坏数据不值得让整个编译预览失败）。
    """
    rows = [
        row
        for row in gates
        if isinstance(row, Mapping) and isinstance(row.get("gate_key"), str) and isinstance(row.get("status"), str)
    ]
    lines = []
    for row in sorted(rows, key=lambda row: row["gate_key"]):
        decision = _clean(row.get("decision"))
        suffix = f"（{decision}）" if decision else ""
        lines.append(f"- 门禁 {row['gate_key']}：{row['status']}{suffix}")
    return lines


def compile_delivery_preview(
    change_set: Mapping[str, Any],
    *,
    industry_template: Mapping[str, Any] | None = None,
    gates: Sequence[Mapping[str, Any]] = (),
    research_skill_ref: str,
    approval_capability: str = "workbench.write",
) -> dict[str, Any]:
    """confirmed 变更集 → 编译预览（方案骨架 payload + workflow 定义草稿 + provenance）。

    ``change_set`` = serialize_change_set 形状，status 必须 confirmed（编译预览
    只对已坐实的本体负责）；``industry_template`` = 已发布行业模板版本
    （industry_name/version_number/modules，None=无匹配模板，走待补）；
    ``gates`` = 门禁状态摘要；``research_skill_ref`` = 调研节点的 published
    skill 显式版本引用（<key>@<版本号>，调用方从白名单取，编译器不查库）。
    输出确定性：不读时钟/随机源，同一输入恒同输出（快照测试钉死）。
    """
    if not isinstance(change_set, Mapping) or change_set.get("status") != "confirmed":
        raise DeliveryCompileError("change_set_not_confirmed: 编译预览只接受 confirmed 变更集。")
    if not isinstance(research_skill_ref, str) or SKILL_REF_PATTERN.fullmatch(research_skill_ref) is None:
        raise DeliveryCompileError(
            "invalid_skill_ref: research_skill_ref 须为 <skill_key>@<版本号>（published 显式版本）。"
        )
    if approval_capability not in APPROVAL_CAPABILITIES:
        raise DeliveryCompileError(
            f"invalid_capability: capability 不在工作流审批白名单（system.* 不开放）：{approval_capability!r}。"
        )
    items = change_set.get("proposed_json")
    if items is None:
        items = []
    if not isinstance(items, list):
        raise DeliveryCompileError("invalid_change_set_item: proposed_json 须为数组。")

    change_title = _clean(change_set.get("title")) or "未命名变更集"
    confirmed_at = _clean(change_set.get("confirmed_at"))
    captured_from = _clean(change_set.get("captured_from"))
    ontology_lines, metric_terms, merges = _parse_terms(items)

    industry = _clean(industry_template.get("industry_name")) if industry_template is not None else ""
    template_note = (
        f"{industry}@v{industry_template['version_number']}"
        if industry_template is not None and isinstance(industry_template.get("version_number"), int)
        else None
    )
    modules = _template_modules(industry_template) if industry_template is not None else []

    # ① 方案骨架（六段布局沿 /skeleton：每段保留「待补」，人工修订后才可导出）
    title = f"{industry or '交付'}方案骨架·本体编译"
    source_parts = [f"变更集《{change_title}》"]
    if confirmed_at:
        source_parts.append(f"确认于 {confirmed_at}")
    if captured_from:
        source_parts.append(f"采集自 {captured_from}")
    design: list[str] = [
        f"# {title}（本体编译草稿，需人工修订）",
        "",
        "> 来源：" + "·".join(source_parts) + "——骨架由已确认本体与行业模板编译，落库前须人工逐段修订。",
        "",
        "## 已确认本体",
        *(ontology_lines or ["- 待补：变更集不含术语条目"]),
        "",
        "## 方案设想（待人工修订）",
    ]
    design += [f"- {name}：待补解决思路与预期收益" for name in modules] or ["- 待补：按模块概述解决思路"]
    design += ["", "## 实施路径（待人工修订）"]
    design += [f"- {name}：待补阶段与里程碑" for name in modules] or ["- 待补：对齐 SOP 阶段与门禁计划"]
    deliverables = [f"- {name}：待补交付物清单" for name in modules] or ["- 待补：核心交付物清单"]
    acceptance = [f"- {name}：验收口径待补" for name in metric_terms] or ["- 待补：验收标准"]
    data_systems = ["- 待补：系统与部署约束"]
    schedule = [f"- {name}：待补排期" for name in modules] or ["- 待补：阶段与里程碑"]
    gate_lines = _gate_lines(gates)
    risks = gate_lines + [
        f"- 术语已合并：{source} → {target}（旧名不再使用）" for source, target in merges
    ] or ["- 待补：风险与依赖"]
    skeleton: dict[str, str] = {
        "name": _truncate(title, _FIELD_LIMITS["name"]),
        "design_markdown": _truncate("\n".join(design), _FIELD_LIMITS["design_markdown"]),
        "deliverables": _truncate("\n".join(deliverables), _DEFAULT_FIELD_LIMIT),
        "acceptance_criteria": _truncate("\n".join(acceptance), _DEFAULT_FIELD_LIMIT),
        "data_systems": _truncate("\n".join(data_systems), _DEFAULT_FIELD_LIMIT),
        "schedule": _truncate("\n".join(schedule), _DEFAULT_FIELD_LIMIT),
        "risks_dependencies": _truncate("\n".join(risks), _DEFAULT_FIELD_LIMIT),
    }

    # ② workflow 定义草稿：调研→方案→审阅。opportunity_ids 是唯一运行期字段，
    #    由调研节点输出整值替换（缺键节点 failed，绝不填空串——executor 语义）。
    workflow_name = _truncate(f"交付编译：{change_title}", 120)
    description = (
        f"Delivery Compiler 由变更集《{change_title}》编译生成"
        f"（确认于 {confirmed_at or '未知'}；行业模板={template_note or '无'}；"
        f"门禁摘要 {len(gate_lines)} 条）。"
        "草稿：人工修订骨架、发布定义后才可运行；方案节点携带编译期骨架字段，"
        "opportunity_ids 由调研节点在运行期填充。"
    )
    dag_json = {
        "nodes": [
            {
                "key": "research",
                "type": "skill",
                "ref": research_skill_ref,
                "depends_on": [],
                "output": "research_brief",
                "max_retries": 0,
                "params": {
                    "project_id": "{{project_id}}",
                    "objective": f"基于变更集《{change_title}》已确认本体补齐调研缺口，产出关联机会列表",
                },
            },
            {
                "key": "solution",
                "type": "call",
                "ref": "solutions.create",
                "depends_on": ["research"],
                "output": "solution_draft",
                "max_retries": 0,
                "params": {
                    "project_id": "{{project_id}}",
                    "body": {
                        **skeleton,
                        "opportunity_ids": "{{research_brief.opportunity_ids}}",
                    },
                },
            },
            {
                "key": "review",
                "type": "human_approval",
                "depends_on": ["solution"],
                "capability": approval_capability,
                "expires_minutes": 15,
            },
        ]
    }

    # agent_trace 式来源标注：逐字段指认来源，落库后可回链编译输入。
    provenance: list[dict[str, Any]] = [
        {
            "field": "solution_skeleton",
            "source": f"ontology_change_set:{change_set.get('id')}",
            "title": change_title,
            "confirmed_at": confirmed_at or None,
            "item_count": len(items),
        }
    ]
    if template_note is not None:
        provenance.append(
            {
                "field": "solution_skeleton.deliverables",
                "source": f"industry_template:{template_note}",
                "modules": modules,
            }
        )
    gate_keys = sorted(
        row["gate_key"]
        for row in gates
        if isinstance(row, Mapping) and isinstance(row.get("gate_key"), str) and isinstance(row.get("status"), str)
    )
    if gate_keys:
        provenance.append({"field": "solution_skeleton.risks_dependencies", "source": "gates", "gate_keys": gate_keys})
    provenance.append(
        {
            "field": "workflow_draft",
            "source": "delivery-compiler/v1",
            "research_skill_ref": research_skill_ref,
            "call_ref": "solutions.create",
        }
    )
    return {
        "kind": "delivery_compile_preview",
        "change_set": {
            "id": change_set.get("id"),
            "title": change_title,
            "confirmed_at": confirmed_at or None,
            "captured_from": captured_from or None,
        },
        "solution_skeleton": skeleton,
        "workflow_draft": {"name": workflow_name, "description": description, "dag_json": dag_json},
        "provenance": provenance,
    }


# ---------------------------------------------------------------------------
# V3.1 P0-4 draft-from-plan：已批准/已发布交付方案 → workflow 定义草稿
# （00-gap-register 4.8；沿 compile_delivery_preview 先例：纯函数+白名单注入制，
# 落库走既有 create_definition 通道，不建平行持久化路径）


def compile_plan_workflow(
    plan: Mapping[str, Any],
    *,
    implementation_skill_ref: str,
    approval_capability: str = "workbench.write",
) -> dict[str, Any]:
    """交付方案（serialize_plan 形状）→ workflow 定义草稿 + provenance。

    ``plan`` 须为 **approved/published**（草稿方案没有坐实口径，编译只对已审阅
    的方案负责——语义对齐 compile_delivery_preview 只收 confirmed 变更集）；
    ``implementation_skill_ref`` = 实施节点的 published skill 显式版本引用
    （<key>@<版本号>，调用方从白名单取，纯函数不查库）。

    三节点形状（四类节点可表达）：方案确认（human_approval，plan_ref 关联方案）
    → 实施（skill，消费方案条目摘要，max_retries=1+timeout+failure_class 契约
    字段首发）→ 验收确认（human_approval）。输出确定性：同一输入恒同输出
    （标题剔除 ``{{``/``}}`` 防占位符误判，其余原样搬运）。
    """
    if not isinstance(plan, Mapping) or plan.get("status") not in ("approved", "published"):
        raise DeliveryCompileError("plan_not_approved: 只接受 approved/published 交付方案。")
    if not isinstance(implementation_skill_ref, str) or SKILL_REF_PATTERN.fullmatch(implementation_skill_ref) is None:
        raise DeliveryCompileError(
            "invalid_skill_ref: implementation_skill_ref 须为 <skill_key>@<版本号>（published 显式版本）。"
        )
    if approval_capability not in APPROVAL_CAPABILITIES:
        raise DeliveryCompileError(
            f"invalid_capability: capability 不在工作流审批白名单（system.* 不开放）：{approval_capability!r}。"
        )
    items = plan.get("items")
    if not isinstance(items, list) or not all(isinstance(item, Mapping) for item in items):
        raise DeliveryCompileError("invalid_plan_items: items 须为对象数组。")
    plan_id = _clean(plan.get("id"))
    if not plan_id:
        raise DeliveryCompileError("invalid_plan_items: 缺方案 id。")
    # 剔除花括号防占位符误判（标题进 params 文本时不得引入 {{...}} 形状）
    title = _clean(plan.get("title")).replace("{{", "").replace("}}", "") or "未命名交付方案"
    requirement_lines = [
        f"- {(item.get('title') or '').strip() or '待补'}"
        for item in items
        if item.get("item_type") == "requirement"
    ]
    risk_lines = [
        f"- {(item.get('title') or '').strip() or '待补'}"
        for item in items
        if item.get("item_type") == "risk"
    ]
    acceptance_lines = [
        f"- {(item.get('title') or '').strip() or '待补'}"
        for item in items
        if item.get("item_type") in ("acceptance", "milestone")
    ]

    workflow_name = _truncate(f"交付执行：{title}", 120)
    description = (
        f"draft-from-plan 由交付方案《{title}》生成（方案 id={plan_id}；"
        f"需求条目 {len(requirement_lines)} 项、风险 {len(risk_lines)} 项、"
        f"验收/里程碑 {len(acceptance_lines)} 项）。"
        "草稿：人工校验并发布后才可运行；实施节点由所选 published 技能执行。"
    )
    dag_json = {
        "nodes": [
            {
                "key": "plan_review",
                "type": "human_approval",
                "depends_on": [],
                "capability": approval_capability,
                "expires_minutes": 60,
                "plan_ref": plan_id,
            },
            {
                "key": "implement",
                "type": "skill",
                "ref": implementation_skill_ref,
                "depends_on": ["plan_review"],
                "output": "implementation_brief",
                "max_retries": 1,
                "timeout_seconds": 3600,
                "failure_class": "retryable",
                "plan_ref": plan_id,
                "params": {
                    "project_id": "{{project_id}}",
                    "objective": (
                        f"按交付方案《{title}》执行实施段："
                        + ("；".join(line.lstrip("- ") for line in requirement_lines) if requirement_lines else "方案无需求条目")
                        + "。产物与证据候选按平台口径留痕，人工确认后才采纳。"
                    ),
                    "risk_notes": "\n".join(risk_lines) if risk_lines else "无已登记风险条目",
                    "acceptance_notes": "\n".join(acceptance_lines) if acceptance_lines else "验收口径待人工补齐",
                },
            },
            {
                "key": "acceptance_review",
                "type": "human_approval",
                "depends_on": ["implement"],
                "capability": approval_capability,
                "expires_minutes": 1440,
                "plan_ref": plan_id,
            },
        ]
    }

    provenance: list[dict[str, Any]] = [
        {
            "field": "workflow_draft",
            "source": f"delivery_plan:{plan_id}",
            "plan_status": plan.get("status"),
            "plan_version": plan.get("version"),
            "requirement_count": len(requirement_lines),
            "risk_count": len(risk_lines),
            "acceptance_count": len(acceptance_lines),
        },
        {
            "field": "workflow_draft.implement",
            "source": "draft-from-plan/v1",
            "implementation_skill_ref": implementation_skill_ref,
        },
    ]
    return {
        "kind": "plan_workflow_draft",
        "plan": {"id": plan_id, "title": title, "status": plan.get("status")},
        "workflow_draft": {"name": workflow_name, "description": description, "dag_json": dag_json},
        "provenance": provenance,
    }
