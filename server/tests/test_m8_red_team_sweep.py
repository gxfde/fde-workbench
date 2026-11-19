"""M8 红队爬扫：企业 A 账号全 API 爬扫企业 B 资源（GET 读面参数化）。

leader 任务书 :106-107 与 ADR-M3 §6 :44 定的最终兜底：用企业 A 账号逐条
爬扫企业 B 的读面，暴露盘点表外的疑似全局面。**本轮零生产代码改动**——
若某条读面坐实真实跨 org 越权，按 ADR-M3 :44 登记「待 M0 补充」＋
`xfail(strict=True)` 待销号，另开轮修，不得顺手改生产代码、不得据此申报
→「安全专项零高危」。

设计要点（对齐 team-lead 实施规格）：

- ``ROUTES`` 39 条 GET 读面，从 ``multi_tenant_harness`` 4 工厂造的 B 企业
  资源 ID 逐条拼出具体路径；企业 A token 打过去须 ``403/404``。
- **双阳性对照**：B 属主 token 同路径须 ``200``（防「全 404」假绿）；
  A 企业内与 B 属主**同角色**的账号仍须 ``403/404``（排除「403 其实由
  角色差异产生」的假绿）。两条都过才算 org 维度真收敛。
- **候选面动态派生**：``create_app().url_map`` 派生「GET＋路径含模板变量」
  的全部路由（现测 102 条），**绝不引用 ``docs/audit/v3-route-inventory.csv``
  作集合**（在途 PR 会改清单，且清单列是 AST 富化产物，CI 只钉
  (method,path)）；候选面条数只在基线断言处写死本轮实测值。
- **排除登记结构化**：``_EXCLUSION_RECORDS`` 每条带
  ``reason``／``exclusion_kind``／``verified_positive_control``／
  ``sweep_required``／``b_owner_status``／``measured``（三套 token 实测码）。
- **降级即红（反逃逸闸，本轮新增）**：并集恒等对「把爬扫面降级成排除登记」
  是不变量，故另配四道闸：
  ① 条数基线 ``len(ROUTES) == 41``／``len(_EXCLUSION_RECORDS) == 74``；
  ② **实测派生 must_sweep 必须为空**——凡「B 属主实测 200 且 A/同角色 A
     均被拒」的路由若停留在排除登记里即转红；
  ③ 排除登记的 ``measured`` 与**现测重测**逐条一致（登记不可伪造、不可陈旧）；
  ④ 声明与实测一致（``verified_positive_control`` ⇔ B 属主实测 200；
     ``sweep_required`` ⇔ 三套实测派生），且阳性对照可行者若仍被排除，
     必须是「角色面」唯一形态。
  ①②③④ 合起来既挡「删登记」也挡「移出 ROUTES 塞进排除」的双向降级，
  「移出 1 条 ＋ 移入 1 条」凑平条数同样转红。

覆盖面＝「测试判别力面」：本文件只证明用例在检验跨企业性，不跨面支撑
git 泄漏面或运行时日志·事件·审计面结论。
"""
from __future__ import annotations

import hashlib
import re
from uuid import uuid4

import pytest

from fde_api.agents.models import AgentArtifact, AgentRegistry, AgentRun
from fde_api.auth.tokens import issue_access_token
from fde_api.control.chat import AIConversation
from fde_api.data_engineering.models import DataProfile, TransformPlan, TransformRun
from fde_api.research.models import (
    ProjectResearchExport,
    ProjectResearchForm,
    ProjectResearchSubject,
)
from fde_api.workbench.models import OperationEvent
from multi_tenant_harness import (
    add_member,
    make_enterprise_org,
    make_project,
    make_user,
)


def _auth(user, settings):
    return {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


def _actual_routes(app):
    """(method, path) 集合——口径同 test_route_inventory_sync.py:25。"""
    actual = set()
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        methods = sorted(m for m in (rule.methods or []) if m not in {"HEAD", "OPTIONS"})
        actual.add(("|".join(methods), rule.rule))
    return actual


def _candidate_get_var_routes(app):
    """候选面＝url_map 里「支持 GET 且路径含模板变量」的全部路由（动态现测）。"""
    return {
        (method, path)
        for (method, path) in _actual_routes(app)
        if "GET" in method.split("|") and "<" in path
    }
# 本轮实际爬扫的 39 条高风险企业资源读面：key 为 (method, Flask rule)，
# value 为「用 B 企业资源 ID 拼出具体路径」的构造器。
# 条数基线由 test_m8_sweep_registry_count_and_semantic_baseline 钉住。
ROUTES = {
    ("GET", "/api/v1/agents/runs/<run_id>"): lambda w: f"/api/v1/agents/runs/{w['run'].id}",
    ("GET", "/api/v1/agents/runs/<run_id>/artifacts/<artifact_id>/content"): lambda w: f"/api/v1/agents/runs/{w['run'].id}/artifacts/{w['artifact'].id}/content",
    ("GET", "/api/v1/agents/runs/<run_id>/tool-calls"): lambda w: f"/api/v1/agents/runs/{w['run'].id}/tool-calls",
    ("GET", "/api/v1/ai/chat/conversations/<conversation_id>"): lambda w: f"/api/v1/ai/chat/conversations/{w['conversation'].id}",
    ("GET", "/api/v1/commercial/certification-records/<user_id>"): lambda w: f"/api/v1/commercial/certification-records/{w['user_b'].id}",
    ("GET", "/api/v1/commercial/entitlements/<user_id>"): lambda w: f"/api/v1/commercial/entitlements/{w['user_b'].id}",
    ("GET", "/api/v1/commercial/orgs/<org_id>/invitations"): lambda w: f"/api/v1/commercial/orgs/{w['org_b'].id}/invitations",
    ("GET", "/api/v1/commercial/role-assignments/<user_id>"): lambda w: f"/api/v1/commercial/role-assignments/{w['user_b'].id}",
    ("GET", "/api/v1/projects/<project_id>"): lambda w: f"/api/v1/projects/{w['project_b'].id}",
    ("GET", "/api/v1/projects/<project_id>/business-facts"): lambda w: f"/api/v1/projects/{w['project_b'].id}/business-facts",
    ("GET", "/api/v1/projects/<project_id>/contracts"): lambda w: f"/api/v1/projects/{w['project_b'].id}/contracts",
    ("GET", "/api/v1/projects/<project_id>/data-profiles"): lambda w: f"/api/v1/projects/{w['project_b'].id}/data-profiles",
    ("GET", "/api/v1/projects/<project_id>/data-profiles/<profile_id>"): lambda w: f"/api/v1/projects/{w['project_b'].id}/data-profiles/{w['profile_b'].id}",
    ("GET", "/api/v1/projects/<project_id>/delivery-plans"): lambda w: f"/api/v1/projects/{w['project_b'].id}/delivery-plans",
    ("GET", "/api/v1/projects/<project_id>/discovery/extractions"): lambda w: f"/api/v1/projects/{w['project_b'].id}/discovery/extractions",
    ("GET", "/api/v1/projects/<project_id>/documents"): lambda w: f"/api/v1/projects/{w['project_b'].id}/documents",
    ("GET", "/api/v1/projects/<project_id>/documents/delivery-records"): lambda w: f"/api/v1/projects/{w['project_b'].id}/documents/delivery-records",
    ("GET", "/api/v1/projects/<project_id>/evidence"): lambda w: f"/api/v1/projects/{w['project_b'].id}/evidence",
    ("GET", "/api/v1/projects/<project_id>/execution-facts"): lambda w: f"/api/v1/projects/{w['project_b'].id}/execution-facts",
    ("GET", "/api/v1/projects/<project_id>/files"): lambda w: f"/api/v1/projects/{w['project_b'].id}/files",
    ("GET", "/api/v1/projects/<project_id>/gantt"): lambda w: f"/api/v1/projects/{w['project_b'].id}/gantt",
    ("GET", "/api/v1/projects/<project_id>/gates"): lambda w: f"/api/v1/projects/{w['project_b'].id}/gates",
    ("GET", "/api/v1/projects/<project_id>/guidance"): lambda w: f"/api/v1/projects/{w['project_b'].id}/guidance",
    ("GET", "/api/v1/projects/<project_id>/guidance-analyses"): lambda w: f"/api/v1/projects/{w['project_b'].id}/guidance-analyses",
    ("GET", "/api/v1/projects/<project_id>/members"): lambda w: f"/api/v1/projects/{w['project_b'].id}/members",
    ("GET", "/api/v1/projects/<project_id>/ontology/candidates"): lambda w: f"/api/v1/projects/{w['project_b'].id}/ontology/candidates",
    ("GET", "/api/v1/projects/<project_id>/ontology/change-sets"): lambda w: f"/api/v1/projects/{w['project_b'].id}/ontology/change-sets",
    ("GET", "/api/v1/projects/<project_id>/ontology/glossary/promoted"): lambda w: f"/api/v1/projects/{w['project_b'].id}/ontology/glossary/promoted",
    ("GET", "/api/v1/projects/<project_id>/ontology/relation-types"): lambda w: f"/api/v1/projects/{w['project_b'].id}/ontology/relation-types",
    ("GET", "/api/v1/projects/<project_id>/ontology/terms"): lambda w: f"/api/v1/projects/{w['project_b'].id}/ontology/terms",
    ("GET", "/api/v1/projects/<project_id>/payments"): lambda w: f"/api/v1/projects/{w['project_b'].id}/payments",
    ("GET", "/api/v1/projects/<project_id>/presurvey-intake"): lambda w: f"/api/v1/projects/{w['project_b'].id}/presurvey-intake",
    ("GET", "/api/v1/projects/<project_id>/quotes"): lambda w: f"/api/v1/projects/{w['project_b'].id}/quotes",
    ("GET", "/api/v1/projects/<project_id>/requirements"): lambda w: f"/api/v1/projects/{w['project_b'].id}/requirements",
    ("GET", "/api/v1/projects/<project_id>/research/exports/<export_id>"): lambda w: f"/api/v1/projects/{w['project_b'].id}/research/exports/{w['export'].id}",
    ("GET", "/api/v1/projects/<project_id>/research/subjects"): lambda w: f"/api/v1/projects/{w['project_b'].id}/research/subjects",
    ("GET", "/api/v1/projects/<project_id>/solutions"): lambda w: f"/api/v1/projects/{w['project_b'].id}/solutions",
    ("GET", "/api/v1/projects/<project_id>/tasks"): lambda w: f"/api/v1/projects/{w['project_b'].id}/tasks",
    ("GET", "/api/v1/projects/<project_id>/test-plans"): lambda w: f"/api/v1/projects/{w['project_b'].id}/test-plans",
    ("GET", "/api/v1/projects/<project_id>/transform-plans"): lambda w: f"/api/v1/projects/{w['project_b'].id}/transform-plans",
    ("GET", "/api/v1/projects/<project_id>/transform-plans/<plan_id>"): lambda w: f"/api/v1/projects/{w['project_b'].id}/transform-plans/{w['plan_b'].id}",
    ("GET", "/api/v1/projects/<project_id>/transform-runs"): lambda w: f"/api/v1/projects/{w['project_b'].id}/transform-runs",
    ("GET", "/api/v1/projects/<project_id>/transform-runs/<run_id>"): lambda w: f"/api/v1/projects/{w['project_b'].id}/transform-runs/{w['run_b'].id}",
    ("GET", "/api/v1/projects/<project_id>/transform-runs/<run_id>/preview"): lambda w: f"/api/v1/projects/{w['project_b'].id}/transform-runs/{w['run_b'].id}/preview",
    ("GET", "/api/v1/projects/<project_id>/transform-runs/<run_id>/diff"): lambda w: f"/api/v1/projects/{w['project_b'].id}/transform-runs/{w['run_b'].id}/diff",
    ("GET", "/api/v1/projects/<project_id>/transform-runs/<run_id>/lineage"): lambda w: f"/api/v1/projects/{w['project_b'].id}/transform-runs/{w['run_b'].id}/lineage",
    ("GET", "/api/v1/projects/<project_id>/transform-runs/<run_id>/quality-feedback"): lambda w: f"/api/v1/projects/{w['project_b'].id}/transform-runs/{w['run_b'].id}/quality-feedback",
    ("GET", "/api/v1/projects/<project_id>/workflow-runs"): lambda w: f"/api/v1/projects/{w['project_b'].id}/workflow-runs",
    ("GET", "/api/v1/projects/<project_id>/workflows"): lambda w: f"/api/v1/projects/{w['project_b'].id}/workflows",
}
# 候选面中未纳入本轮爬扫的 73 条，逐条结构化登记：
#   reason                  —— 人读理由（必须含自身实测状态码）
#   exclusion_kind          —— 硬排除形态（阳性对照不可行/admin-only/
#                             公开面/内部服务间面/角色面）
#   verified_positive_control —— B 属主同路径实测 200（阳性对照可行）
#   sweep_required          —— 实测派生的「必须纳入 ROUTES 爬扫」判别式
#   b_owner_status          —— B 属主实测状态码（与 measured.b_owner 互锁）
#   measured                —— 三套 token 实测码（A / 同角色 A / B 属主）
# 数值口径来自基线 d092c2e 的 A/B/同角色 A 三状态码现测，并由
# test_m8_exclusion_registry_matches_live_measurement 逐条现测复核。
_EXCLUSION_RECORDS = {
    # AF1-WP4（docs/ai-fde/13 §7-B）：工程台两段式 token 读面——Bearer
    # eng-session/handover 鉴权（非用户 JWT 读面），JWT/匿名一律 403
    # （eng_missing_token/malformed），投影语义（一次性消费/白名单逐字段/
    # 租户钉定/跨租户 404 同形）由 tests/test_af1_wp4_eng_api.py 专项覆盖。
    ("GET", "/api/v1/eng/runs/<run_id>"): {
        "reason": "工程台两段式 token 面（AF1-WP4，Bearer eng token；非用户 JWT 读面）：A 实测 403、同角色 A 实测 403、B 属主实测 403——JWT 打进即 403 malformed，无跨企业语义可爬；专项闸在 test_af1_wp4_eng_api",
        "exclusion_kind": "internal_service",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 403,
        "measured": {"a": 403, "same_role_a": 403, "b_owner": 403},
    },
    ("GET", "/api/v1/admin/commercial/orgs/<org_id>/ai-budget"): {
        "reason": "admin-only 平台面，非企业 token 读面：A 实测 403、同角色 A 实测 403、B 属主实测 403；M6 已证 admin 全量可见是平台能力非漏洞",
        "exclusion_kind": "admin_only",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 403,
        "measured": {"a": 403, "same_role_a": 403, "b_owner": 403},
    },
    ("GET", "/api/v1/agents/host/runs/<run_id>/context"): {
        "reason": "宿主机器通道 X-Host-Poll-Token 闸面（goal-sprint r3 新增；非用户 JWT 读面，claim/receipt 同族）：A 实测 403、同角色 A 实测 403、B 属主实测 403——缺令牌即 403 host_poll_token_missing，JWT 不进鉴权，无跨企业语义可爬",
        "exclusion_kind": "internal_service",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 403,
        "measured": {"a": 403, "same_role_a": 403, "b_owner": 403},
    },
    ("GET", "/api/v1/ai/chat/messages/<turn_id>/progress"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/ai/executions/<execution_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/ai/lcsc-runs/<run_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/commercial/enterprise-quota/<subject_key>"): {
        "reason": "阳性对照不可行：A 实测 400、同角色 A 实测 400、B 属主同路径实测 400（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 400,
        "measured": {"a": 400, "same_role_a": 400, "b_owner": 400},
    },
    ("GET", "/api/v1/commercial/enterprise-spaces/<subject_key>"): {
        "reason": "阳性对照不可行：A 实测 400、同角色 A 实测 400、B 属主同路径实测 400（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 400,
        "measured": {"a": 400, "same_role_a": 400, "b_owner": 400},
    },
    ("GET", "/api/v1/commercial/opportunities/<opportunity_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/commercial/regional-partners/<partner_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/commercial/revenue-ledger/<entry_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/delivery-plans/<plan_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/diagnostics/leads/claims/<claim_id>"): {
        "reason": "公开匿名/分享只读面，非企业资源读面：A 实测 404、同角色 A 实测 404、B 属主实测 404",
        "exclusion_kind": "public_surface",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/diagnostics/share/<share_token>"): {
        "reason": "公开匿名/分享只读面，非企业资源读面：A 实测 404、同角色 A 实测 404、B 属主实测 404",
        "exclusion_kind": "public_surface",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/discovery/extractions/<extraction_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/dispatch/packages/<package_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/dispatch/packages/<package_id>/offers"): {
        "reason": "阳性对照不可行：A 实测 403、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 403, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/document-templates/<version_id>/download-url"): {
        "reason": "admin-only 平台面，非企业 token 读面：A 实测 403、同角色 A 实测 403、B 属主实测 403；M6 已证 admin 全量可见是平台能力非漏洞",
        "exclusion_kind": "admin_only",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 403,
        "measured": {"a": 403, "same_role_a": 403, "b_owner": 403},
    },
    ("GET", "/api/v1/extensions/plugins/<plugin_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/extensions/skills/<skill_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/extensions/skills/<skill_id>/versions"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/handover-packages/<package_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/industry-templates/<template_id>/versions"): {
        "reason": "角色面而非 org 隔离面：A 实测 403、同角色 A 实测 200、B 属主实测 200（同角色 A 亦可达 ⇒ org 隔离不适用，阳性对照不具 org 判别力）",
        "exclusion_kind": "role_surface",
        "verified_positive_control": True,
        "sweep_required": False,
        "b_owner_status": 200,
        "measured": {"a": 403, "same_role_a": 200, "b_owner": 200},
    },
    ("GET", "/api/v1/industry-templates/versions/<version_id>"): {
        "reason": "阳性对照不可行：A 实测 403、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 403, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/internal/dsh/approvals/<approval_id>"): {
        "reason": "内部 DSH 服务间面（静态令牌服务间面），非企业 token 读面：A 实测 401、同角色 A 实测 401、B 属主实测 401",
        "exclusion_kind": "internal_service",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 401,
        "measured": {"a": 401, "same_role_a": 401, "b_owner": 401},
    },
    ("GET", "/api/v1/internal/dsh/executions/<run_id>/knowledge"): {
        "reason": "内部 DSH 服务间面（静态令牌服务间面），非企业 token 读面：A 实测 401、同角色 A 实测 401、B 属主实测 401",
        "exclusion_kind": "internal_service",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 401,
        "measured": {"a": 401, "same_role_a": 401, "b_owner": 401},
    },
    ("GET", "/api/v1/interview-minutes/<minutes_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/meeting-templates/<template_id>/checklist"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/meetings/<meeting_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/meetings/<meeting_id>/cost"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/meetings/<meeting_id>/minutes"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/documents/<document_id>"): {
        "reason": "阳性对照不可行：A 实测 403、同角色 A 实测 403、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 403, "same_role_a": 403, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/documents/<document_id>/versions"): {
        "reason": "阳性对照不可行：A 实测 403、同角色 A 实测 403、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 403, "same_role_a": 403, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/documents/<version_id>/download-url"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/documents/<version_id>/preview-url"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/files/<version_id>/download-url"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/files/<version_id>/preview-url"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/files/items/<file_id>/versions"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/guidance-analyses/<analysis_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/change-sets/<change_set_id>/review-package"): {
        "reason": (
            "本体变更集评审包 HTML 导出面（V3.3 M2 段 2 步 6 / D8+D17）：FDE_ONTOLOGY_ENABLED 默认关闭（D12/D13 门控先于鉴权），"
            "默认夹具下 A/同角色A/B属主实测均为 404，无法在默认夹具内构造 200 正向对照；"
            "启用态的项目归属与跨租户 404 隔离由 test_ontology_ingest.py 专项契约钉覆盖"
        ),
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/ontology-bindings"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（V3.3 WP4 本体绑定面默认关闭——D12/D13 契约：关闭态一律 404 not_found，与「路径不存在」逐字节同形，禁用面不可区分 ⇒ B 属主非 200，阳性对照不可构造，同码假绿风险）；本轮夹具无该面启用前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/ontology-bindings/<binding_id>/lineage"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（V3.3 M3-WP4 绑定血缘面默认关闭——D12/D13 契约：关闭态一律 404 not_found，与「路径不存在」逐字节同形，禁用面不可区分 ⇒ B 属主非 200，阳性对照不可构造，同码假绿风险）；启用态跨租户 404 隔离由 test_ontology_m3_grounding 专测钉死",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/ontology-bindings/<binding_id>/action-requests/<request_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（V3.3 M4-WP3 Action 请求只读视图默认关闭——D12/D13 契约：关闭态一律 404 not_found，与「路径不存在」逐字节同形，禁用面不可区分 ⇒ B 属主非 200，阳性对照不可构造，同码假绿风险）；启用态跨租户 404 隔离由 test_ontology_m4_agent 专测钉死",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/ontology/change-sets/<change_set_id>"): {
        "reason": "阳性对照不可行：A 实测 403、同角色 A 实测 403、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 403, "same_role_a": 403, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/ontology/terms/<term_id>/impact"): {
        "reason": "阳性对照不可行：A 实测 403、同角色 A 实测 403、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 403, "same_role_a": 403, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/quotes/<quote_key>/draft"): {
        "reason": "阳性对照不可行：A 实测 403、同角色 A 实测 403、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 403, "same_role_a": 403, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/research/forms"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 409（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 409,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 409},
    },
    ("GET", "/api/v1/projects/<project_id>/research/forms/<form_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 409（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 409,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 409},
    },
    ("GET", "/api/v1/projects/<project_id>/research/subjects/<subject_id>/memo"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 400（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 400,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 400},
    },
    ("GET", "/api/v1/projects/<project_id>/research/subjects/<subject_id>/personal-memos"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 400（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 400,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 400},
    },
    ("GET", "/api/v1/projects/<project_id>/solutions/<solution_id>"): {
        "reason": "阳性对照不可行：A 实测 403、同角色 A 实测 403、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 403, "same_role_a": 403, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/solutions/<solution_id>/health"): {
        "reason": "阳性对照不可行：A 实测 403、同角色 A 实测 403、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 403, "same_role_a": 403, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/solutions/<solution_id>/review-trail"): {
        "reason": "阳性对照不可行：A 实测 403、同角色 A 实测 403、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 403, "same_role_a": 403, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/tasks/<task_id>"): {
        "reason": "阳性对照不可行：A 实测 403、同角色 A 实测 403、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 403, "same_role_a": 403, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/workflow-runs/<run_id>"): {
        "reason": "阳性对照不可行：A 实测 403、同角色 A 实测 403、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 403, "same_role_a": 403, "b_owner": 404},
    },
    ("GET", "/api/v1/simulation/proposals/<proposal_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/simulation/regression/results/<result_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/simulation/regression/suites/<suite_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/simulation/runs/<run_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/simulation/runs/<run_id>/evaluation"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/simulation/runs/<run_id>/trace"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/simulation/scenarios/<scenario_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/simulation/scenarios/<scenario_id>/versions"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/skills/<skill_id>/document"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/templates/<template_id>/versions/<version_id>/research-forms"): {
        "reason": "阳性对照不可行：A 实测 403、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 403, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/test-executions/<execution_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/test-plans/<plan_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/transcript-drafts/<draft_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/translator/translations/<translation_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/users/<user_id>/ai-access"): {
        "reason": "admin-only 平台面，非企业 token 读面：A 实测 403、同角色 A 实测 403、B 属主实测 403；M6 已证 admin 全量可见是平台能力非漏洞",
        "exclusion_kind": "admin_only",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 403,
        "measured": {"a": 403, "same_role_a": 403, "b_owner": 403},
    },
    ("GET", "/api/v1/projects/<project_id>/ontology/review-queue"): {
        "reason": "ontology 默认禁用（D12）→ 404 not_found；启用态跨租户 404 隔离由 test_m5_wp3_review_queue_telemetry 专测钉死（disabled 404 / 无绑定 409）",
        "exclusion_kind": "internal_service",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/projects/<project_id>/ontology/upgrade-blast-radius"): {
        "reason": "ontology 默认禁用（D12）→ 404 not_found；启用态跨租户 404 隔离由 test_m5_wp3_governance_blast_radius 专测钉死（disabled 404 / 无绑定 409 / 跨租户 404）",
        "exclusion_kind": "internal_service",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    # ↓↓ M6-WP0 D11 缝合：fork 支链（PR #482）simulation 域两条 GET 读面并入，
    # 登记沿 fork 侧实测原文（合并树上重测校验由下方语义闸承担）
    ("GET", "/api/v1/simulation/proposals/<proposal_id>/release-preview"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
    ("GET", "/api/v1/simulation/regression/jobs/<job_id>"): {
        "reason": "阳性对照不可行：A 实测 404、同角色 A 实测 404、B 属主同路径实测 404（B 属主非 200 ⇒ 阳性对照不可构造，同码假绿风险），本轮夹具无该资源前置状态",
        "exclusion_kind": "positive_control_infeasible",
        "verified_positive_control": False,
        "sweep_required": False,
        "b_owner_status": 404,
        "measured": {"a": 404, "same_role_a": 404, "b_owner": 404},
    },
}
# 人类可读视图（由 _EXCLUSION_RECORDS 派生，不单独维护，避免两处失同步）
_EXCLUDED_WITH_REASON = {route: rec["reason"] for route, rec in _EXCLUSION_RECORDS.items()}

# org 维度收敛的状态码（A / 同角色 A 被拒时只接受这两个码）
_ORG_BLOCK_CODES = (403, 404)

# 排除登记允许的五类形态（软排除＝阳性对照可行但未排；硬排除＝下面五类）
_EXCLUSION_KINDS = frozenset(
    {
        "positive_control_infeasible",
        "admin_only",
        "public_surface",
        "internal_service",
        "role_surface",
    }
)


def _derived_must_sweep(measured):
    """实测派生「必须纳入 ROUTES 爬扫」。

    判别式＝B 属主同路径 200（阳性对照可行）且 A 与同角色 A 均被 org 收敛
    （403/404）——此时该路由是货真价实的 org 隔离面，停留在排除登记里就是
    「降级逃逸」，必须转红。
    """
    return (
        measured["b_owner"] == 200
        and measured["a"] in _ORG_BLOCK_CODES
        and measured["same_role_a"] in _ORG_BLOCK_CODES
    )


def _measurement_ids(world):
    """排除登记重测用的 ID 映射：已知资源用真实 ID，未知资源用随机 hex。"""
    return {
        "project_id": world["project_b"].id,
        "org_id": world["org_b"].id,
        "user_id": world["user_b"].id,
        "export_id": world["export"].id,
        "form_id": world["form"].id,
        "subject_id": world["subject"].id,
        "run_id": world["run"].id,
        "artifact_id": world["artifact"].id,
        "conversation_id": world["conversation"].id,
        "action_id": world["action_id"],
        "template_id": uuid4().hex,
        "version_id": uuid4().hex,
        "document_id": uuid4().hex,
        "file_id": uuid4().hex,
        "task_id": uuid4().hex,
        "quote_key": uuid4().hex[:8],
        "analysis_id": uuid4().hex,
        "change_set_id": uuid4().hex,
        "term_id": uuid4().hex,
        "solution_id": uuid4().hex,
        "meeting_id": uuid4().hex,
        "minutes_id": uuid4().hex,
        "plan_id": uuid4().hex,
        "package_id": uuid4().hex,
        "extraction_id": uuid4().hex,
        "execution_id": uuid4().hex,
        "proposal_id": uuid4().hex,
        "result_id": uuid4().hex,
        "suite_id": uuid4().hex,
        "scenario_id": uuid4().hex,
        "translation_id": uuid4().hex,
        "plugin_id": uuid4().hex,
        "skill_id": uuid4().hex,
        "subject_key": uuid4().hex[:8],
        "partner_id": uuid4().hex,
        "entry_id": uuid4().hex,
        "opportunity_id": uuid4().hex,
        "claim_id": uuid4().hex,
        "share_token": uuid4().hex,
        "approval_id": uuid4().hex,
        "draft_id": uuid4().hex,
        "turn_id": uuid4().hex,
    }


def _build_measurement_path(rule, ids):
    """把规则里的模板变量换成具体 ID（未知变量用随机 hex）。"""
    return re.sub(r"<([^>]+)>", lambda m: str(ids.get(m.group(1), uuid4().hex)), rule)


def _b_markers(world):
    """B 企业标识（用于「200 但不得泄漏」的兜底断言）。"""
    return [
        str(world["project_b"].id),
        str(world["project_b"].project_code),
        str(world["org_b"].id),
        str(world["user_b"].id),
    ]


@pytest.fixture
def m8_world(db_session):
    """跨企业世界：两个企业 org、A 企业两账号（含与 B 属主同角色者）、
    B 企业属主与项目，以及挂在该项目上的 B 企业资源（导出/AI run/对话/
    待确认 API-action）。所有工厂均自带 ``db_session.commit()``——HTTP
    路由面测试若漏 commit，请求侧连接看不到数据，会退化成「列表空集」假绿。
    """
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "fde_engineer", org_id=org_a.id)
    user_a_lead = make_user(db_session, "project_lead", org_id=org_a.id)
    user_b = make_user(db_session, "project_lead", org_id=org_b.id)
    project_b = make_project(
        db_session, user_b, code=f"M8{uuid4().hex[:8]}", org_id=org_b.id
    )
    # 跨企业成员关系＝判别力关键场景：成员关系本身挡不住 org 维度。
    add_member(db_session, project_b, user_a)
    add_member(db_session, project_b, user_a_lead)

    subject = ProjectResearchSubject(
        project_id=project_b.id,
        subject_type="company",
        subject_key=f"subject-{uuid4().hex[:8]}",
        name="M8 隔离用例调研对象",
    )
    db_session.add(subject)
    db_session.flush()
    form = ProjectResearchForm(
        project_id=project_b.id,
        subject_id=subject.id,
        form_key=f"form-{uuid4().hex[:8]}",
        name="M8 隔离用例调研表",
    )
    db_session.add(form)
    db_session.flush()
    export = ProjectResearchExport(
        project_id=project_b.id,
        form_id=form.id,
        requested_by_user_id=user_b.id,
        status="queued",
    )
    db_session.add(export)

    registry = AgentRegistry(
        kind="zcode",
        name="M8 隔离用例智能体",
        enabled=True,
        capability_tier="agent.code.write",
        sandbox_profile="default",
        credential_ref=None,
        allowed_tools=["read_file"],
        max_cost_units=0,
        max_duration_ms=0,
    )
    db_session.add(registry)
    db_session.flush()
    run = AgentRun(
        project_id=project_b.id,
        agent_id=registry.id,
        initiated_by_user_id=user_b.id,
        capability_used="agent.code.write",
        context_ref="masked://m8-isolation-case",
        idempotency_key=f"m8-{uuid4().hex}",
    )
    db_session.add(run)
    db_session.flush()

    artifact = AgentArtifact(
        run_id=run.id,
        kind="doc",
        storage_ref=f"{run.id}/output/report.md",
        sha256=hashlib.sha256("# M8 隔离用例产物\n正文。\n".encode("utf-8")).hexdigest(),
        reviewed=False,
    )
    db_session.add(artifact)

    conversation = AIConversation(
        user_id=user_b.id,
        title="M8 隔离用例会话",
        project_id=project_b.id,
        source="desktop",
    )
    db_session.add(conversation)

    # AF2-WP1：画像报告行（B 项目资产——爬扫面新成员的阳性对照资源）
    profile_b = DataProfile(
        project_id=project_b.id,
        source_name="m8-profile.csv",
        input_sha256="c" * 64,
        truncated=False,
        table_count=1,
        tables_json=[],
        relation_candidates_json=[],
        samples_json={},
        created_by_user_id=user_b.id,
    )
    db_session.add(profile_b)

    # AF2-WP2：类型化转换计划行（B 项目资产——爬扫面新成员的阳性对照资源）
    plan_b = TransformPlan(
        project_id=project_b.id,
        plan_version="af2-wp2-v1",
        status="validated",
        source_profile_id=str(uuid4()),
        source_table="m8-plan-equipment",
        plan_json={"plan_version": "af2-wp2-v1"},
        validation_json={
            "valid": True,
            "errors": [],
            "dependency_graph": {"nodes": [], "edges": [], "topological_order": []},
            "output_columns": [],
        },
        created_by_user_id=user_b.id,
    )
    db_session.add(plan_b)
    db_session.flush()  # plan_b.id 落定（run_b.plan_id FK 引用需真实 id）

    # AF2-WP3：隔离执行记录行（B 项目资产——爬扫面新成员的阳性对照资源）
    run_b = TransformRun(
        project_id=project_b.id,
        plan_id=plan_b.id,
        plan_version="af2-wp2-v1",
        idempotency_key=f"m8-run-{uuid4().hex}",
        status="succeeded",
        input_anchor_json={"kind": "file_version", "file_version_id": str(uuid4())},
        output_rows_json=[{"eq_id": "EQ-1"}],
        output_row_count=1,
        output_columns_json=[{"name": "eq_id", "type": "string"}],
        reject_ledger_json=[],
        rejected_row_count=0,
        overflow_count=0,
        quality_report_json={},
        lineage_json=[{"step_id": "s1", "op": "select", "input_rows": 1, "output_rows": 1, "rejected_rows": 0}],
        conservation_json={"input_rows": 1, "output_rows": 1, "rejected_rows": 0, "overflow_count": 0, "ok": True},
        created_by_user_id=user_b.id,
    )
    db_session.add(run_b)

    action_id = uuid4().hex + uuid4().hex
    db_session.add(
        OperationEvent(
            actor_user_id=user_b.id,
            project_id=project_b.id,
            target_type="ai_api_action",
            target_id=action_id,
            event_type="ai.api.requested",
            changes={
                "description": "M8 隔离用例待确认操作",
                "operation": "projects.get",
                "parameters": {},
                "body": {},
                "query": {},
                "confirmation_required": True,
            },
        )
    )
    db_session.commit()

    return {
        "org_a": org_a,
        "org_b": org_b,
        "user_a": user_a,
        "user_a_lead": user_a_lead,
        "user_b": user_b,
        "project_b": project_b,
        "subject": subject,
        "form": form,
        "export": export,
        "run": run,
        "artifact": artifact,
        "conversation": conversation,
        "profile_b": profile_b,
        "plan_b": plan_b,
        "run_b": run_b,
        "action_id": action_id,
    }


@pytest.mark.parametrize("route", sorted(ROUTES), ids=lambda r: r[1])
def test_m8_cross_enterprise_a_token_cannot_read_b_resource(
    client, db_session, settings, m8_world, route
):
    """企业 A token 打企业 B 资源 ⇒ 403/404（或 200 但载荷不含 B 标识）。"""
    path = ROUTES[route](m8_world)

    blocked = client.get(path, headers=_auth(m8_world["user_a"], settings))
    assert blocked.status_code in (403, 404), (
        path,
        blocked.status_code,
        blocked.get_data(as_text=True)[:200],
    )
    # 「或载荷不含 B 标识」这一形态由下列两个 200 列表面用例承载；参数化爬扫面
    # 用严格 403/404，使身份/夹具取值的摘除式变异能确定性地转红（判别力自证）。
    assert all(
        marker not in blocked.get_data(as_text=True) for marker in _b_markers(m8_world)
    ), (path, "拒绝响应体泄漏 B 企业标识")

    # 同角色控制：A 企业账号即使与 B 属主同为 project_lead，仍须被 org 收敛，
    # 排除「403 其实由角色差异产生」的假绿。
    same_role = client.get(path, headers=_auth(m8_world["user_a_lead"], settings))
    assert same_role.status_code in (403, 404), (path, same_role.status_code)

    # 阳性对照：B 属主 token 同路径须 200，防「全 404」假绿
    #（先例 test_m3b_batch3_project_service.py:262-288）。
    # 例外：artifact 内容路由须工作区文件在场才能 204（B 属主 404 合法，
    # 完整三态验证由 test_m8_artifact_content_route_full_matrix 承担）。
    allowed = client.get(path, headers=_auth(m8_world["user_b"], settings))
    if "artifacts" in path and path.endswith("/content"):
        assert allowed.status_code == 404, (
            "artifact 内容路由在测试工作区无文件时 B 属主须 404",
            path,
            allowed.status_code,
        )
    else:
        assert allowed.status_code == 200, (
            path,
            allowed.status_code,
            allowed.get_data(as_text=True)[:200],
        )


def test_m8_sweep_surface_covers_every_candidate_get_read_face(app):
    """完整性钉：候选面 ≡ ROUTES ∪ 排除登记；未登记即红、陈旧登记即红。

    注：并集恒等对「把爬扫面降级成排除登记」是不变量（移出 ROUTES 后并集
    不变），故「降级即红」由另外两道语义闸承担（条数+实测基线、排除登记
    现测重测），见下两条用例。
    """
    candidate = _candidate_get_var_routes(app)
    accounted = set(ROUTES) | set(_EXCLUSION_RECORDS)
    assert candidate - accounted == set(), (
        "发现未登记的 GET 读面（须纳入 ROUTES 或补排除理由）：",
        sorted(candidate - accounted),
    )
    assert accounted - candidate == set(), (
        "登记面已陈旧（url_map 中不再存在）：",
        sorted(accounted - candidate),
    )
    assert set(ROUTES).isdisjoint(_EXCLUSION_RECORDS), (
        "同一条路由不得既被爬扫又被排除：",
        sorted(set(ROUTES) & set(_EXCLUSION_RECORDS)),
    )

    actual = _actual_routes(app)
    assert set(ROUTES) <= actual, (
        "ROUTES 含不存在的路由：",
        sorted(set(ROUTES) - actual),
    )
    assert all(method == "GET" for method, _ in ROUTES)

    assert all(reason.strip() for reason in _EXCLUDED_WITH_REASON.values()), (
        "排除登记必须逐条给出非空理由"
    )
    for route, rec in _EXCLUSION_RECORDS.items():
        codes = {str(code) for code in rec["measured"].values()}
        missing = sorted(code for code in codes if code not in rec["reason"])
        assert not missing, (
            route,
            "排除理由必须包含自身实测状态码",
            missing,
            rec["reason"],
        )


def test_m8_sweep_registry_count_and_semantic_baseline():
    """条数基线 ＋ 语义基线：让「移出 ROUTES ＋ 移入排除登记」的双向降级转红。

    ① 条数基线（本轮现算实测值，不沿用历史数）；
    ② 声明与实测一致（verified_positive_control / sweep_required /
       b_owner_status 与 measured 三套实测码互锁）；
    ③ **实测派生 must_sweep 必须为空**——凡「B 属主实测 200 且 A/同角色 A
       均被拒」的路由若停留在排除登记里即转红（正向降级逃逸口）；
    ④ 阳性对照可行者若仍被排除，必须是「角色面」唯一形态（org 隔离不适用）。
    """
    assert len(ROUTES) == 49, ("爬扫面条数基线被改动：", len(ROUTES))
    assert len(_EXCLUSION_RECORDS) == 74, (
        "排除登记条数基线被改动：",
        len(_EXCLUSION_RECORDS),
    )

    for route, rec in _EXCLUSION_RECORDS.items():
        measured = rec["measured"]
        assert rec["exclusion_kind"] in _EXCLUSION_KINDS, (route, rec)
        assert rec["b_owner_status"] == measured["b_owner"], (route, rec)
        assert rec["verified_positive_control"] == (
            measured["b_owner"] == 200
        ), (route, rec)
        assert rec["sweep_required"] == _derived_must_sweep(measured), (route, rec)

    must_sweep = {
        route
        for route, rec in _EXCLUSION_RECORDS.items()
        if _derived_must_sweep(rec["measured"])
    }
    assert must_sweep == set(), (
        "排除登记里存在「阳性对照可行且 org 维度收敛」的路由——必须纳入 ROUTES 爬扫：",
        sorted(must_sweep),
    )

    for route, rec in _EXCLUSION_RECORDS.items():
        if not rec["verified_positive_control"]:
            continue
        assert rec["exclusion_kind"] == "role_surface", (route, rec)
        assert rec["measured"]["same_role_a"] == 200, (route, rec)
        assert "角色" in rec["reason"], (route, rec["reason"])


def test_m8_exclusion_registry_matches_live_measurement(
    client, db_session, settings, m8_world
):
    """排除登记的实测证据必须与现测一致（登记不可伪造、不可陈旧）。

    这是「降级逃逸口」的第二道闸核心：把一条真实爬扫路由从 ROUTES 移进
    排除登记，就必须同时伪造 ``measured``，而伪造值与现测不符即转红——
    「移出 1 条 ＋ 移入 1 条」凑平条数也不例外。
    """
    # ROUTES 构造器：模板变量必须全部替换成真实 B 资源 ID
    for route, build in ROUTES.items():
        path = build(m8_world)
        assert "<" not in path and ">" not in path, (route, path)
        assert path.startswith("/api/v1/"), (route, path)

    ids = _measurement_ids(m8_world)
    headers = (
        _auth(m8_world["user_a"], settings),
        _auth(m8_world["user_a_lead"], settings),
        _auth(m8_world["user_b"], settings),
    )
    mismatches = []
    for route, rec in _EXCLUSION_RECORDS.items():
        path = _build_measurement_path(route[1], ids)
        live = tuple(client.get(path, headers=hdr).status_code for hdr in headers)
        declared = (
            rec["measured"]["a"],
            rec["measured"]["same_role_a"],
            rec["measured"]["b_owner"],
        )
        if live != declared:
            mismatches.append((route, live, declared))
    assert mismatches == [], (
        "排除登记的实测证据与现测不符（登记陈旧或被伪造）：",
        mismatches,
    )


def test_m8_a_token_never_sees_b_resources_in_200_list_surfaces(
    client, db_session, settings, m8_world
):
    """200 列表面：A 企业账号的项目列表与待确认 API-action 清单不得出现 B 标识。

    「或 200 但载荷不含 B 标识」这一形态由本用例承载（参数化爬扫面用严格
    403/404，使身份/夹具取值的摘除式变异能确定性转红）。
    """
    owner_projects = client.get(
        "/api/v1/projects", headers=_auth(m8_world["user_b"], settings)
    )
    assert owner_projects.status_code == 200
    assert m8_world["project_b"].id in {
        row["id"] for row in owner_projects.get_json()["data"]["items"]
    }

    response = client.get("/api/v1/projects", headers=_auth(m8_world["user_a"], settings))
    assert response.status_code == 200
    items = response.get_json()["data"]["items"]
    assert m8_world["project_b"].id not in {row["id"] for row in items}

    owner_actions = client.get(
        "/api/v1/ai/actions", headers=_auth(m8_world["user_b"], settings)
    )
    assert owner_actions.status_code == 200
    assert m8_world["action_id"] in {
        row["id"] for row in owner_actions.get_json()["data"]["items"]
    }

    actions = client.get("/api/v1/ai/actions", headers=_auth(m8_world["user_a"], settings))
    assert actions.status_code == 200
    identifiers = {row["id"] for row in actions.get_json()["data"]["items"]}
    assert m8_world["action_id"] not in identifiers


def test_m8_artifact_content_route_full_matrix(
    app, client, db_session, settings, m8_world, monkeypatch, tmp_path
):
    """#376（N3c）新增路由 GET /api/v1/agents/runs/<run_id>/artifacts/<artifact_id>/content

    参数化爬扫面里该路由走 B 属主 404（测试工作区无文件），此用例摆出
    原件后完整验证三态：A / 同角色 A 仍须 403（org 收敛不受文件在场影响）；
    B 属主须 200（can_manage＋文件在场所需，阳性对照完整）。
    """
    # 把 agent_workspace_root 指向 tmp_path，并摆出原件
    workspace_root = tmp_path / "agent-workspaces"
    monkeypatch.setitem(
        app.config,
        "SETTINGS",
        app.config["SETTINGS"].model_copy(
            update={"agent_workspace_root": str(workspace_root)}
        ),
    )
    artifact = m8_world["artifact"]
    org_b = m8_world["org_b"]
    run = m8_world["run"]
    content = "# M8 隔离用例产物\n正文。\n".encode("utf-8")
    target = workspace_root / "org" / org_b.id / run.id / "output" / "report.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)

    path = f"/api/v1/agents/runs/{run.id}/artifacts/{artifact.id}/content"

    # A（fde_engineer，已加入 B 项目）⇒ 403（can_manage 拒绝，org 收敛不依赖文件）
    blocked_a = client.get(path, headers=_auth(m8_world["user_a"], settings))
    assert blocked_a.status_code == 403, (path, blocked_a.status_code, blocked_a.get_data(as_text=True)[:200])

    # 同角色 A（project_lead，已加入 B 项目）⇒ 仍 403（角色差异不豁免 org 维度）
    same_role = client.get(path, headers=_auth(m8_world["user_a_lead"], settings))
    assert same_role.status_code == 403, (path, same_role.status_code)

    # B 属主（project_lead，B 企业创建者）⇒ 200（can_manage＋文件在场）
    allowed = client.get(path, headers=_auth(m8_world["user_b"], settings))
    assert allowed.status_code == 200, (
        path,
        allowed.status_code,
        allowed.get_data(as_text=True)[:200],
    )


# M5-WP3 合流：ontology 默认禁用（D12）→ review-queue / upgrade-blast-radius 404
ROUTES.update({
    k: v for k, v in list(ROUTES.items())
    if 'review-queue' not in k[1] and 'blast-radius' not in k[1]
})
