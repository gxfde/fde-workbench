"""V3 T-C1：Delivery Compiler 最小闭环——纯函数编译预览的快照与合同测试。

钉死三件事：①同一输入恒同输出（快照字面量整树比对）；②产出的 dag_json 在
真实 api_catalog 白名单 + 注入 skill ref 下全绿零告警（调研→方案→审阅闭环，
rule 9 无外效告警）；③骨架 payload 与 solutions.create 文本合同逐键兼容
（合并运行期 opportunity_ids 后原样可过 _normalize）。
"""
from __future__ import annotations

import pytest

from fde_api.solutions.service import _normalize as normalize_solution_payload
from fde_api.workflows.compiler import DeliveryCompileError, compile_delivery_preview
from fde_api.workflows.definition_service import (
    APPROVAL_CAPABILITIES,
    catalog_call_effects,
    catalog_call_refs,
    validate_dag,
)

SKILL_REF = "delivery-research@1"

CONFIRMED_CHANGE_SET = {
    "id": "cs-001",
    "project_id": "p-001",
    "title": "首次本体定稿",
    "proposed_json": [
        {"action": "create_term", "term": "渠道门店", "term_type": "entity", "definition": "线下直营与加盟门店统称。"},
        {"action": "create_term", "term": "门店动销率", "term_type": "metric", "definition": "月度 SKU 售罄比率。"},
        {
            "action": "update_term",
            "term": "会员体系",
            "new_term": "会员增长体系",
            "term_type": "generic",
            "definition": "以留存与复购为核心的增长机制。",
        },
        {"action": "merge_terms", "source_term": "门店", "target_term": "渠道门店"},
        {"action": "register_relation_type", "kind": "link_type", "code": "supplies_to"},
    ],
    "status": "confirmed",
    "captured_from": "research_import:preview-9",
    "confirmed_at": "2026-11-05T02:00:00+00:00",
}

TEMPLATE = {
    "industry_name": "连锁零售",
    "version_number": 2,
    "modules": [
        {"name": "门店运营", "sort_order": 2},
        {"name": "会员营销", "sort_order": 1},
        {"name": "数据底座", "sort_order": 3},
    ],
}

GATES = [
    {"gate_key": "G8", "status": "passed", "decision": "proceed", "submitted_at": None, "decided_at": None},
    {"gate_key": "G1", "status": "evidence", "decision": None, "submitted_at": None, "decided_at": None},
]


def _compile(**overrides):
    kwargs: dict[str, object] = {
        "industry_template": TEMPLATE,
        "gates": GATES,
        "research_skill_ref": SKILL_REF,
    }
    kwargs.update(overrides)
    return compile_delivery_preview(CONFIRMED_CHANGE_SET, **kwargs)


EXPECTED_DESIGN_MARKDOWN = "\n".join(
    [
        "# 连锁零售方案骨架·本体编译（本体编译草稿，需人工修订）",
        "",
        "> 来源：变更集《首次本体定稿》·确认于 2026-11-05T02:00:00+00:00"
        "·采集自 research_import:preview-9——骨架由已确认本体与行业模板编译，落库前须人工逐段修订。",
        "",
        "## 已确认本体",
        "- 实体｜渠道门店：线下直营与加盟门店统称。",
        "- 指标｜门店动销率：月度 SKU 售罄比率。",
        "- 术语｜会员增长体系（原「会员体系」修订）：以留存与复购为核心的增长机制。",
        "",
        "## 方案设想（待人工修订）",
        "- 会员营销：待补解决思路与预期收益",
        "- 门店运营：待补解决思路与预期收益",
        "- 数据底座：待补解决思路与预期收益",
        "",
        "## 实施路径（待人工修订）",
        "- 会员营销：待补阶段与里程碑",
        "- 门店运营：待补阶段与里程碑",
        "- 数据底座：待补阶段与里程碑",
    ]
)

EXPECTED_SKELETON = {
    "name": "连锁零售方案骨架·本体编译",
    "design_markdown": EXPECTED_DESIGN_MARKDOWN,
    "deliverables": "- 会员营销：待补交付物清单\n- 门店运营：待补交付物清单\n- 数据底座：待补交付物清单",
    "acceptance_criteria": "- 门店动销率：验收口径待补",
    "data_systems": "- 待补：系统与部署约束",
    "schedule": "- 会员营销：待补排期\n- 门店运营：待补排期\n- 数据底座：待补排期",
    "risks_dependencies": (
        "- 门禁 G1：evidence\n- 门禁 G8：passed（proceed）\n- 术语已合并：门店 → 渠道门店（旧名不再使用）"
    ),
}

EXPECTED_PROVENANCE = [
    {
        "field": "solution_skeleton",
        "source": "ontology_change_set:cs-001",
        "title": "首次本体定稿",
        "confirmed_at": "2026-11-05T02:00:00+00:00",
        "item_count": 5,
    },
    {
        "field": "solution_skeleton.deliverables",
        "source": "industry_template:连锁零售@v2",
        "modules": ["会员营销", "门店运营", "数据底座"],
    },
    {"field": "solution_skeleton.risks_dependencies", "source": "gates", "gate_keys": ["G1", "G8"]},
    {
        "field": "workflow_draft",
        "source": "delivery-compiler/v1",
        "research_skill_ref": SKILL_REF,
        "call_ref": "solutions.create",
    },
]

EXPECTED = {
    "kind": "delivery_compile_preview",
    "change_set": {
        "id": "cs-001",
        "title": "首次本体定稿",
        "confirmed_at": "2026-11-05T02:00:00+00:00",
        "captured_from": "research_import:preview-9",
    },
    "solution_skeleton": EXPECTED_SKELETON,
    "workflow_draft": {
        "name": "交付编译：首次本体定稿",
        "description": (
            "Delivery Compiler 由变更集《首次本体定稿》编译生成"
            "（确认于 2026-11-05T02:00:00+00:00；行业模板=连锁零售@v2；门禁摘要 2 条）。"
            "草稿：人工修订骨架、发布定义后才可运行；方案节点携带编译期骨架字段，"
            "opportunity_ids 由调研节点在运行期填充。"
        ),
        "dag_json": {
            "nodes": [
                {
                    "key": "research",
                    "type": "skill",
                    "ref": SKILL_REF,
                    "depends_on": [],
                    "output": "research_brief",
                    "max_retries": 0,
                    "params": {
                        "project_id": "{{project_id}}",
                        "objective": "基于变更集《首次本体定稿》已确认本体补齐调研缺口，产出关联机会列表",
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
                        **EXPECTED_SKELETON,
                        "opportunity_ids": "{{research_brief.opportunity_ids}}",
                    },
                },
                {
                    "key": "review",
                    "type": "human_approval",
                    "depends_on": ["solution"],
                    "capability": "workbench.write",
                    "expires_minutes": 15,
                },
            ]
        },
    },
    "provenance": EXPECTED_PROVENANCE,
}


def test_compile_confirmed_change_set_full_preview_snapshot():
    """整树快照：本体段（含修订标注）/ 模板排序 / 指标入验收 / 门禁排序 / provenance。"""
    assert _compile() == EXPECTED


def test_compiled_dag_passes_catalog_whitelist_without_warnings():
    """三节点 dag 在真实目录白名单下全绿：write_db 不触发 rule 9，占位符合法。"""
    preview = _compile()
    validation = validate_dag(
        preview["workflow_draft"]["dag_json"],
        call_refs=catalog_call_refs(),
        skill_refs=frozenset({SKILL_REF}),
        agent_refs=frozenset(),
        capabilities=APPROVAL_CAPABILITIES,
        call_effects=catalog_call_effects(),
    )
    assert validation.ok, [issue.as_dict() for issue in validation.errors]
    assert not validation.warnings
    assert validation.order == ("research", "solution", "review")


def test_compile_rejects_unconfirmed_change_set_and_bad_items():
    """只编译 confirmed；载荷非数组 / 非对象项 / 未知动作 / 缺必填字段一律点名。"""
    with pytest.raises(DeliveryCompileError, match="change_set_not_confirmed"):
        compile_delivery_preview(
            {**CONFIRMED_CHANGE_SET, "status": "in_review"}, research_skill_ref=SKILL_REF
        )
    bad_payloads = [
        "不是数组",
        ["不是对象"],
        [{"action": "create_subject"}],
        [{"action": "create_term", "term": "无定义"}],
        [{"action": "merge_terms", "source_term": "缺目标"}],
    ]
    for payload in bad_payloads:
        with pytest.raises(DeliveryCompileError, match="invalid_change_set_item"):
            compile_delivery_preview(
                {**CONFIRMED_CHANGE_SET, "proposed_json": payload}, research_skill_ref=SKILL_REF
            )


def test_compile_without_template_or_gates_falls_back_to_placeholders():
    """无模板走待补、无术语走待补；门禁摘要坏行跳过、好行保留；dag 仍全绿。"""
    minimal = {
        "id": "cs-002",
        "title": "纯类型登记",
        "status": "confirmed",
        "proposed_json": [{"action": "register_relation_type", "kind": "link_type", "code": "supplies_to"}],
    }
    preview = compile_delivery_preview(
        minimal,
        industry_template=None,
        gates=({"gate_key": "G9", "status": 1}, {"gate_key": "G2", "status": "passed"}),
        research_skill_ref=SKILL_REF,
    )
    skeleton = preview["solution_skeleton"]
    assert skeleton["name"] == "交付方案骨架·本体编译"
    assert "- 待补：变更集不含术语条目" in skeleton["design_markdown"]
    assert skeleton["deliverables"] == "- 待补：核心交付物清单"
    assert skeleton["acceptance_criteria"] == "- 待补：验收标准"
    assert skeleton["schedule"] == "- 待补：阶段与里程碑"
    assert skeleton["risks_dependencies"] == "- 门禁 G2：passed"
    assert preview["change_set"]["confirmed_at"] is None
    assert preview["change_set"]["captured_from"] is None
    assert [entry["source"] for entry in preview["provenance"]] == [
        "ontology_change_set:cs-002",
        "gates",
        "delivery-compiler/v1",
    ]
    validation = validate_dag(
        preview["workflow_draft"]["dag_json"],
        call_refs=catalog_call_refs(),
        skill_refs=frozenset({SKILL_REF}),
        agent_refs=frozenset(),
        capabilities=APPROVAL_CAPABILITIES,
        call_effects=catalog_call_effects(),
    )
    assert validation.ok


def test_compile_rejects_bad_skill_ref_and_capability():
    """skill ref 须显式版本；capability 须在审批白名单（system.* 不开放）。"""
    for bad_ref in ("delivery-research", "key@0", "key@v1", ""):
        with pytest.raises(DeliveryCompileError, match="invalid_skill_ref"):
            _compile(research_skill_ref=bad_ref)
    for bad_capability in ("system.health", "no.such_capability", ""):
        with pytest.raises(DeliveryCompileError, match="invalid_capability"):
            _compile(approval_capability=bad_capability)


def test_skeleton_payload_passes_solutions_create_normalization():
    """骨架七键即 solutions.create 文本合同；合并运行期机会 id 原样过 _normalize。"""
    preview = _compile()
    skeleton = preview["solution_skeleton"]
    assert set(skeleton) == {
        "name",
        "design_markdown",
        "deliverables",
        "acceptance_criteria",
        "data_systems",
        "schedule",
        "risks_dependencies",
    }
    opportunity_ids = ["op-" + "1" * 33]
    normalized = normalize_solution_payload({**skeleton, "opportunity_ids": opportunity_ids})
    assert normalized["name"] == skeleton["name"]
    assert normalized["design_markdown"] == skeleton["design_markdown"]
    assert normalized["risks_dependencies"] == skeleton["risks_dependencies"]
    assert normalized["opportunity_ids"] == opportunity_ids
