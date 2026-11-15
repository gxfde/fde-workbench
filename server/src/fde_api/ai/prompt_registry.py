"""提示词版本注册表（AI 原生化 N6／差距台账 G-13，单一权威）。

每个模块级 ``*SYSTEM_PROMPT*`` 常量必须在此登记（``test_prompt_registry.py``
AST 钉住「全常量必注册」）；``version_of(module, constant)`` 是各提示词模块
取版本标签的唯一通道（模块侧只 re-export，不再自持字面量）。

两层数据：
- ``version``：版本标签，写入 ``ai_call_audits.prompt_version`` ⇒ 审计行可按
  版本分组（G-13 复测）；
- ``content_sha256``：**注册时**常量正文的 sha256 字面量。测试逐条重算比对——
  改了提示词正文而不同步改注册表（升版本＋换指纹）⇒ 红。这封死「版本与内容
  脱钩（改内容不升版本 ⇒ 归因失效）」风险（任务书 N6 风险①）。

纪律（任务书 N6「明确不做」）：不自动改提示词内容；不在无评测数据时自动切
模型（见 ``ai/model_routing.py``）；提示词正文绝不入库——本表只存版本与指纹，
与「证据只存指针+sha256」同款纪律。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptRegistration:
    """单条提示词注册：身份（module+constant）↔ 版本 ↔ 注册时内容指纹。"""

    key: str
    module: str
    constant: str
    version: str
    content_sha256: str | None = None
    derived_of: str | None = None


PROMPT_REGISTRATIONS: tuple[PromptRegistration, ...] = (
    PromptRegistration(
        key="discovery.extract",
        module="fde_api.discovery.prompt",
        constant="DISCOVERY_SYSTEM_PROMPT",
        version="discovery-prompt-v2",
        content_sha256="0f496dcf49459f43885737aff6ab53bf1166e6a616777ccc9dc3d21abb6eaf40",
    ),
    PromptRegistration(
        key="discovery.extract_chunk",
        module="fde_api.discovery.prompt",
        constant="DISCOVERY_CHUNK_SYSTEM_PROMPT",
        version="discovery-prompt-v2",
        content_sha256="9ac5275858e0011b25c1424baf406eef46af88d2ca9e03670dd5679042e15191",
        derived_of="discovery.extract",
    ),
    PromptRegistration(
        key="industry_template.chat",
        module="fde_api.ai.industry_template_prompt",
        constant="CHAT_SYSTEM_PROMPT",
        version="industry-template-chat-prompt-v1",
        content_sha256="d65019ce72974ca9d3527da83218e92c0c6d508fd0cbc3327cee3612f50aebd7",
    ),
    PromptRegistration(
        key="industry_template.generation",
        module="fde_api.ai.industry_template_prompt",
        constant="GENERATION_SYSTEM_PROMPT",
        version="industry-template-gen-prompt-v1",
        content_sha256="c166108839267b7f8e57888974971a11bbecdf6489a166e5a4020f2723a6cc14",
    ),
    PromptRegistration(
        key="research_form.generate",
        module="fde_api.ai.research_form_prompt",
        constant="SYSTEM_PROMPT",
        version="research-form-prompt-v1",
        content_sha256="69017859d8a41587233a42f06b2e7d66bc1a6e6a244c89edeff31f1a13ef0ac5",
    ),
    PromptRegistration(
        key="simulation.evaluation",
        module="fde_api.simulation.evaluation_prompt",
        constant="SYSTEM_PROMPT",
        version="simulation-eval-prompt-v1",
        content_sha256="7783334b36fd299b7df769eaa9247f552c87977b3c8bc3fcb8bf63c96dab6c36",
    ),
    PromptRegistration(
        key="simulation.diagnostic_judge",
        module="fde_api.simulation.diagnostic_judge",
        constant="SYSTEM_PROMPT",
        version="diagnostic-judge-prompt-v1",
        content_sha256="ce85704be5acc3a34dc8a8979d141fb22028f901a5bb62de584f25c88e1c18c2",
    ),
    PromptRegistration(
        key="quality.testcase_draft",
        module="fde_api.quality.draft",
        constant="QUALITY_TESTCASE_DRAFT_SYSTEM_PROMPT",
        version="quality-draft-prompt-v1",
        content_sha256="ef9cf9c9efd2fe78c5cd586d4275c09947fbdae95f45b3da5d4f19c714abe35f",
    ),
    PromptRegistration(
        key="plans.delivery_plan_draft",
        module="fde_api.plans.draft_ai",
        constant="DELIVERY_PLAN_DRAFT_SYSTEM_PROMPT",
        version="plan-draft-prompt-v1",
        content_sha256="5e115d7e31df0319bdb5d0e0ad62dd94e69e5ab4c43720ec988d65efef842ba5",
    ),
    PromptRegistration(
        key="workflows.dag_draft",
        module="fde_api.workflows.draft_ai",
        constant="WORKFLOW_DAG_DRAFT_SYSTEM_PROMPT",
        version="workflow-dag-prompt-v1",
        content_sha256="fb3b2b30ec068ca57556775d4a89b49397e685592f13e08fbb9ff02bfdd623b5",
    ),
    PromptRegistration(
        key="diagnostics.report",
        module="fde_api.diagnostics.prompts",
        constant="DIAGNOSTIC_REPORT_SYSTEM_PROMPT",
        version="diagnostic-report-prompt-v2",
        content_sha256="043025d9401e495d16c58d54c75356fcec8a23904ce2ae7eedcf40d4d4a748e7",
    ),
    PromptRegistration(
        key="dispatch.match_recommend",
        module="fde_api.dispatch.recommend_ai",
        constant="DISPATCH_RECOMMENDATION_SYSTEM_PROMPT",
        version="dispatch-recommend-prompt-v1",
        content_sha256="59d134126e34df723b89de83e6f9770e3ca59cba15847d07ea0931c660768983",
    ),
    PromptRegistration(
        key="simulation.workbench",
        module="fde_api.simulation.adapters.workbench",
        constant="WORKBENCH_SYSTEM_PROMPT",
        version="simulation-workbench-prompt-v1",
        content_sha256="2cce0765d33d4c2e7730771a145d3406085b01eb0323ec72c33ba24bdf927baf",
    ),
    PromptRegistration(
        key="simulation.improvement_draft",
        module="fde_api.simulation.improvement_draft",
        constant="IMPROVEMENT_DRAFT_SYSTEM_PROMPT",
        version="simulation-improvement-draft-prompt-v1",
        content_sha256="8cec4edef64a2b2f50c6edb644406716ffdd85ce85f061919b2ec87b1296e831",
    ),
)

_LOOKUP: dict[tuple[str, str], PromptRegistration] = {
    (entry.module, entry.constant): entry for entry in PROMPT_REGISTRATIONS
}


def version_of(module: str, constant: str) -> str:
    """取提示词常量的注册版本标签；未注册即 KeyError（fail-loud）。"""
    entry = _LOOKUP.get((module, constant))
    if entry is None:
        raise KeyError(
            f"prompt not registered: {module}.{constant} —— 请在 ai/prompt_registry.py 登记版本"
        )
    return entry.version


def registration_of(module: str, constant: str) -> PromptRegistration:
    """取完整注册行（测试与审计面用）。"""
    entry = _LOOKUP.get((module, constant))
    if entry is None:
        raise KeyError(f"prompt not registered: {module}.{constant}")
    return entry
