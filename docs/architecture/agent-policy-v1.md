# Agent 权限与 Skill 生命周期策略 v1（P1）

> 状态：现状部分 **VERIFIED**（证据：附录 C 1-10、F Q9；fde-v2 对照：附录 B 7-15、E 四/五）；扩展项 **PROPOSED**。
> 任务书"决策 5/6"的逐条落实。

## 1. 决策 5：Agent 权限治理——五条原则的现状与补强

### 1.1 现状基线（VERIFIED，保持不动）

| 原则 | 现状实现 | 证据 |
|---|---|---|
| 角色只收窄不扩大 | run 工具面 = agent.allowed_tools ∖ RUN_FACE_DENIED ∩ 发起人实时档位 ∩ 插件实时态；等级地板恒生效 | agents/tools.py:84-106；test_agents_fallback_chain.py:209/218/248 |
| 每次调用重新校验 | MCP 面：15min JWT 解码后**重载用户**（is_active/auth_version）+ capabilities=实时∩claims（只衰减）+ project 双重校验 | mcp_gateway.py:66-105；test_ai_server_chat_mcp.py:166-197 |
| 写/外副作用分类 | readOnlyHint 动态推导；写类 2（api_execute/file_send_wechat）；automation.execute 不可恢复重投 | mcp_gateway.py:271、reconcile.py:35-37 |
| 高风险绑定目标+版本审批 | automation_approvals：(run_id,request_key) 唯一 + arguments_sha256 + 15min + 一次性 + 执行前再鉴权 + 硬白名单 | control/service.py:561-843 |
| 直连不绕过 | 直连降级面只 READ_ONLY 13；DSH 回环走同一 MCP 端点 | ai_tool_loop.py:42-56；ai_server_client.py:135-199 |

### 1.2 补强项（PROPOSED）

**P1-R1 ToolGroup（域 7）**：`agent_tool_groups` 只读目录（种子随代码），agent.allowed_tools 支持 `group:research-readonly` 引用；resolve=交集（组永不扩大）。理由：现状每 agent 手写清单（agent_registry.allowed_tools），复用与审计成本高；fde-v2 证明"角色=预打包工具集"有效（附录 B 7），但其 exec 装配不可搬。

**P1-R2 结构化 effect/risk 元数据（域 9）**：TOOLS 与 api_catalog ENTRIES 增加 `effect: read|write_db|external` 与 `risk: 0-4`（与 automation_approvals.risk_level 同尺度）；tools/list annotations 同步；workflow 定义校验器消费（external 节点须审批后继）。修 WB-DEF-10（export_sow/documents.generate 未列 confirmation）。

**P1-R3 审批卫生（域 10）**：scheduler 每轮懒清扫过期 pending 审批（WB-DEF-3）；resolve_signoff 权限改 `can_manage + AI 档位` 双闸（WB-DEF-2）。

**P1-R4 运行中权限复查评估（P3）**：现状工具面 run 级冻结（WB-DEF-12 已记录，窗口内只读+断网）。P3 若开放 agent 节点进 workflow（长运行），改为每节点执行前重算工具面（复用 resolve 交集函数，成本=一次 DB 查询）。

### 1.3 明确不采用 fde-v2 的机制（教训清单）

| fde-v2 机制 | 不采用理由 |
|---|---|
| exec 装配 _roles.py 角色文件 | 任意代码执行面；WB 用数据行+种子 |
| 隐式页面授权（X-Fde-Page 派生服务放行） | 前端声明扩大权限，违背服务端中心 |
| system_prompt 首行角色标记 `<!--FDE_ROLE:-->` | 提示即权限的脆弱性；WB 用签名 token claims |
| user=None 全通语义 | 无鉴权模式全平台裸奔（E 四-4）；WB fail-closed |
| HITL 仅聊天路径（flow/scheduler 绕过） | FV-F2；WB workflow call=api_execute 同闸，external 必审批 |

## 2. 决策 6：Skill 生命周期——以 WB 现有双表为底座扩展

### 2.1 现状对照（VERIFIED）

| 治理项 | Workbench（skill_definitions+skill_versions） | fde-v2（skills.db 单表） | 裁决 |
|---|---|---|---|
| 草稿 | 无（建即 active 可被消费） | 有（draft） | EXTEND：新增 draft 态 |
| 审核 | 无 | 有（approve 人工闸；但守卫失效 R1 使其形同虚设） | EXTEND：in_review 态 + admin 密码确认（WB 统一收口） |
| 发布 | 无显式发布（current_version 即生效） | approved 即发布 | EXTEND：published 态+published_by/at（对齐 industry_template_versions 语义） |
| 测试报告 | 无 | 无 | EXTEND：skill_versions.test_report_json（发布闸消费） |
| 版本不可变 | **有**（content_sha256 唯一；同指纹只改元数据） | 无（原地 UPDATE） | REUSE（WB 优势，fde-v2 教训 FV-S1） |
| 发布前测试 | 无 | 无（仅形状校验） | EXTEND：publish 前必须 test_report_json 非空或显式 waive（留痕） |
| I/O 契约 | 无（manifest 任意 JSON） | 部分（{{key}} 执行期报错） | EXTEND：input_schema/output_schema json 列，publish 时 jsonschema 校验 |
| 运行版本固定 | 有（join current_version_number） | 无（读当前行） | REUSE；workflow skill 节点再显式钉版本号 |
| 回滚 | 无 | 无 | EXTEND：rollback 端点=set current 到历史版本行（版本行不可变故安全） |
| 弃用 | 有（disabled，_skills 过滤） | 有（deprecated） | REUSE |
| 效果评估 | 无 | 部分（usage_count/score） | P2：run 面累计 usage（operation_events 已有基础）→ **T-S2 DONE；P3 状态轮裁决（2026-11-05）：usage 维持「失败不计」对称语义不新开失败维度**——失败证据走 ai_call_audits/operation_events 人工审计面；重审触发器=首个真实改进建议需求（详见 docs/implementation/v3-p3-四项状态与闸清偿-v1.md §2）。**P3 评估报告轮（2026-11-05）：本行 T-R2 effect/risk 尺度上承边界梯度分类学 G0–G7+S——现役可降级集合=∅，写外呼/发信/付款类永不降级红线逐字维持（详见 docs/implementation/v3-p3-评估报告-有限自动执行-v1.md §1）** |

### 2.2 目标状态机（PROPOSED）

```
skill_definitions.status: draft → in_review → published → (deprecated | archived)
                              └──── rejected（回 draft 可改）
skill_versions:  内容不可变（既有）；draft 版本行可被删除（未发布前）
发布闸（publish_skill_version, admin+密码确认）:
  ①version 行存在且 definition=draft/in_review
  ②input/output schema jsonschema 合法
  ③test_report_json 非空 或 waive_tests=true（waive 记录操作人）
  ④required_capabilities ⊆ 创建者档位（既有，保持）
消费面（mcp_gateway._skills / workflow skill 节点）: 只回 published ∧ (public∨owner) ∧ capabilities⊆allowed（既有两闸保持）
回滚（rollback_skill_version, admin+密码确认）: current_version_number → 历史版本行；operation_events 留痕；新 run 立即生效（V12 收紧语义同向）
```

### 2.3 代码落点（PROPOSED）

EXTEND：`control/models.py`（status 枚举扩展+published_by/at；skill_versions 加 input_schema/output_schema/test_report_json/reviewed_by）、`control/extensions_service.py`（publish/rollback/submit_for_review 服务函数）、`control/builtin_skills.py`（种子直接 published）、`control/mcp_gateway.py`（_skills 过滤 status=published）。
不触碰：插件（plugin_*）体系、seat ledger、agents/tools 三重交集。

### 2.4 API（PROPOSED）

| Method/Path | 权限 | 说明 |
|---|---|---|
| POST /api/v1/extensions/skills/{id}/submit-review | owner/admin | draft→in_review |
| POST /api/v1/extensions/skills/{id}/versions/{n}/publish | admin+密码确认 | 发布闸四条 |
| POST /api/v1/extensions/skills/{id}/rollback | admin+密码确认 | {target_version} |
| GET /api/v1/extensions/skills/{id}/versions | admin/lead | 版本历史 |

### 2.5 验收测试（server/tests/test_skill_lifecycle.py，PROPOSED）

1. draft/in_review 不可被 skill_read 消费；2. 发布后内容不可变（改内容→新版本行，旧行原样）；3. 发布闸：无测试报告且未 waive → 409 test_report_required；waive 留操作人；4. schema 非法 → 422；5. 回滚后 skill_read 返回旧版+事件留痕；6. 非 admin publish → 403（对照 fde-v2 R1 教训写显式负向用例）；7. capability 收窄：required_capabilities 超创建者档位 → 403（既有行为回归）。
