# 蔡工 FDE Workbench × fde-v2 架构融合审计与 V3 升级实施方案

- 版本：v1.0（2026-11-02）。审计执行：ZCode 审计子代理组（6 个专项）+ 主控复核。
- 基线：**Workbench @ `0570384`**（分支 fde-v2，96 业务表 / 269 路由 / 22 迁移 head `c3e7a9b1d5f4`）；**fde-v2 快照 ≈ 上游 master@`39e0e62`**（v2.3.0b0，本地无 git 历史，mtime 推定）。
- 结论口径：`VERIFIED` / `PARTIALLY VERIFIED` / `PROPOSED` 三态贯穿全文；新增设计全部 PROPOSED 并落到文件/表/接口。

---

## 1. 执行摘要

对两个仓库完成了真实代码审计（非文档推断）：Workbench 精读覆盖门禁/方案/文档/任务/控制平面/调研/本体六大域（6 份行号级证据报告，附录 A–F）；fde-v2 以零执行纪律完成流水线/本体/工作流/Agent/Skill/安全六线审计。自动抽取产出 385 行路由清单与 121 行表清单（脚本入库 `scripts/audit/`）。

**核心结论一（融合的真实价值边界）**：fde-v2 与 Workbench 不是同层系统。fde-v2 是"md 规格驱动、AI 代理施工"的**代码生成平台**（构建期九步法 + 运行期内省平台），其平台轨 groupbuild 代码在快照中缺失、无迁移系统、测试无 CI、存在 2 个高危洞（管理守卫失效 R1、SSRF R2）与 14 项可证据化风险；Workbench 是**交付管理系统**，在权限（每次调用实时鉴权/token 只衰减/审批一次性）、版本（alembic 22 链/不可变文档版本）、测试（pytest 1700+/vitest 730 实跑绿）三个维度全面占优。**因此 V3 不是"引入 fde-v2"，而是吸收其四件经过验证的思想**：①声明式 YAML DAG 形态（剔除其执行器全部可靠性缺陷）；②"候选→人工确认"的治理闭环形态（其 skills 审批闸与 Workbench guidance adopt 流同构）；③证据"出处+源块"粒度；④BR 三要素机器可读的质量纪律。

**核心结论二（Workbench 自身缺陷）**：审计发现 14 项 Workbench 现状缺陷（WB-DEF-1~14，全部行号证据），其中 **WB-DEF-1 signoff 死锁为功能阻断级**（agent_assisted 方案正常 completed 无 handoff → SOW 永久导不出 409），列 P0 立即修复。

**核心结论三（V3 蓝图）**：五层架构中 Engagement OS（现有）、Quality（部分现有）为 REUSE/EXTEND；Ontology Registry（术语/类型注册/变更集/一等证据 4+1 新表）、Workflow Engine（定义/版本/run/节点 3+1 新表，作为 background_jobs 新 job_type 不建第二套队列）、Delivery Compiler（纯函数编译预览）为受控新增。P0=证据一等表+本体最小闭环+死锁修复；P1=Workflow（call/skill 先行）+Skill 治理态+工具组+权限卫生；P2=证据候选接门禁+血缘补洞+编译器；P3=多 Agent 与自动执行（明确 DEFER）。

## 2. 审计范围与限制

**范围**：Workbench 服务端 24 模块 + 桌面端 + 迁移 + 测试（精读 ~90 文件，行号级）；fde-v2 全部平台模块 + 2 个应用组样例 + design-plus 规格 + 脚本（精读 ~60 文件）。
**限制（如实声明）**：
1. fde-v2 为不受信外部快照：**零执行**（未跑任何 verify 脚本，"是否全绿"= UNKNOWN）；快照与上游一致性仅 mtime 推定（本地无 git 对象）。
2. fde-v2 第三方依赖（agentscope 2.0.6 内部、lightrag 内部）无源码，相关结论标 UNKNOWN/PARTIALLY。
3. Workbench 运行时行为（SKIP LOCKED 并发、租约续期实测）为代码+测试断言推断，未做动态压测。
4. 生产库数据分布（如 gates.template_hash 存量）未查库。
5. DSH（AI Server）为外部黑盒，仅审接口契约侧。
6. 本轮**只审计与写文档**：未改业务代码、未跑迁移、未部署、未外呼（与任务书"先审计后实施"一致）。

## 3. 两个仓库的技术基线

详文：`docs/audit/v3-baseline-workbench.md`、`docs/audit/v3-baseline-fde-v2.md`。对照速览：

| 维度 | Workbench | fde-v2 |
|---|---|---|
| 形态 | Flask+SQLAlchemy API（Docker 4 服务）+ Electron 桌面端 | Flask+waitress 单体（compose 5 服务）+ 无构建 Alpine.js 前端 |
| 数据 | PG 16，96 表，alembic 22 链 | SQLite 默认（每应用一库）/PG 可选（静默回退），17 平台表，**无迁移系统** |
| 鉴权 | JWT+角色 rank+AI 五档+MCP 只衰减 token | Cookie 会话+RBAC 授权表；无鉴权模式全通 |
| Agent | DSH 外部编排+单 run 沙箱+L0-L3 降级 | AgentScope 进程内团队+flow 编排 |
| 工具面 | MCP 17+catalog 94（白名单制） | 内省全量 ~180+（开放制） |
| 测试 | pytest 1706 收集/CI 4 job | verify 脚本四层/无 CI/未执行 |
| 交付 | 门禁/方案/文档/派单/收款全链 | 无交付概念（应用即产物） |

## 4. 核心模块及调用链

（全部 VERIFIED，完整版见附录 C/D/F 的"关键调用链"节）六条主干：

1. **门禁**：`POST /projects/{id}/gates/{G}/evidence` → gate_service.submit_gate_evidence（FOR UPDATE）→ gates.evidence_checklist → `POST …/decision` → decide_gate 五道闸（拍板人≠执行人→G8/G9 admin→conditional 仅 G9→G8 必带 decision→accepted⊆claimed）→ operation_events；G8 pass→mark_acceptance_passed。全仓无第二写路径（grep 证实）。
2. **文档生成**：export_sow → [agent_assisted signoff 闸] → DocumentVersion(draft,sha256='') + GenerationJob + outbox('document.generate') → worker handle_document_generation → build_document_snapshot 冻结输入 → render_docx → 版本 sha256 落库 → outbox('file.preview')；幂等短路（sha256 非空/终态）。
3. **MCP 工具鉴权**：DSH → POST /internal/ai/mcp → _identity（15min JWT→重载用户→实时档∩claims）→ call_tool（注册表+capability）→ _project（claims+project_access）→ handler。
4. **审批**：DSH → /internal/dsh/executions/{run}/approvals → AutomationApproval(pending, sha256, 15min) → run=waiting_approval → 桌面 decision（人工+密码）→ execute_approved_dsh_tool（approved 态+sha256 复核+再鉴权+硬白名单）→ executed 一次。
5. **自动化调度**：flask scheduler → dispatch_due_automations（SKIP LOCKED+幂等键）→ run(queued)+outbox('automation.execute') → worker execute_automation_run（逐 capability 复查）→ dsh_runtime.execute（Idempotency-Key）→ 回调终态。
6. **调研→方案**：POST /ai/project-ai-opportunities/discover（读 confirmed 答案+备忘→DeepSeek→证据逐字校验→**只回建议不落库**）→ 人工 POST /research/subjects 落库 → guidance adopt/confirm 同构闭环。

fde-v2 侧四条（详见附录 A/B）：构建期九步法（文件树即状态）；`POST /api/apps/<app>/call/<svc>` → gate 授权 → FdePlatform.call（统一事务+sqlc AST 审计注入）；聊天工具链（AgentScope→bridge.execute 授权）；flow 执行（拓扑分层并行→flow_runs.db）。

## 5. 逐模块差距矩阵

**`docs/audit/v3-gap-matrix.md`**：17 能力域 × 17 字段全覆盖（每域含 Workbench/fde-v2 现状+证据、差距、REUSE/EXTEND/NEW/DEFER 裁决、目标文件、数据模型、接口、安全影响、实施任务、验收、优先级、依赖、可信度）。要点：REUSE 8 域、EXTEND 12 处、NEW 3 件（evidence/ontology 三表/workflow 三表）、DEFER 3 件（多 Agent 团队/RAG/规则推理）；高优先差距 5 项全部追到调用链级。

## 6. 数据库与接口映射

- **路由**：`docs/audit/v3-route-inventory.csv`（385 行 = WB 269 [url_map 枚举，33 蓝图，鉴权列分布：require_auth 213/require_role 31/require_minimum_role 8/bridge_token 1/开放 16] + fde-v2 116 [AST 装饰器]）。test_file 列启发式匹配 87/269 WB 路由有直接测试命中。
- **数据表**：`docs/audit/v3-database-inventory.csv`（121 行 = WB 96 表全字段[PK/FK/索引/版本字段/项目隔离/首建迁移 revision，96/96 有迁移归属] + fde-v2 25 处 DDL[17 真实+fixture 标注]）。
- **新增映射**：§14（表）与 §15（API）。

## 7. 目标架构与架构图

五层（任务书 §七 A–E 评估结论）：**A. Engagement OS**=现有 projects/gates/documents/solutions/dispatch/research（REUSE，唯一事实源）；**B. Ontology Registry**=NEW（terms/relation_types/change_sets）+EXTEND(research subjects/links)+evidence 底座；**C. Delivery Compiler**=NEW 纯函数（本体+模板→方案骨架/workflow 草稿）；**D. Workflow Engine**=NEW（definitions/runs/node_runs）挂在现有 jobs/outbox/worker 之上；**E. Quality & Evolution**=pytest 族扩展+发布闸+证据候选接门禁。

```mermaid
flowchart TB
  subgraph EOS[A. Engagement OS — 现有，事实源]
    PRJ[projects/gates G1-G9/sop] --- RES[research subjects/links/forms]
    DOC[documents versions] --- SOL[solutions+signoff]
    DSP[dispatch/payments]
  end
  subgraph REG[B. Ontology Registry — V3 新增]
    EV[(project_evidence NEW)]
    TM[(ontology_terms+aliases NEW)]
    RT[(ontology_relation_types NEW)]
    CS[(ontology_change_sets NEW)]
  end
  subgraph WF[D. Workflow Engine — V3 新增，复用 jobs]
    WD[(workflow_definitions+versions NEW)]
    WR[(workflow_runs NEW)]
    WN[(workflow_node_runs NEW)]
    BJ[background_jobs/outbox/worker 现有]
  end
  subgraph CQ[C. Delivery Compiler / E. Quality — P2]
    CMP[compiler.py NEW 本体→方案/workflow 草稿]
    QA[pytest 族扩展 + skill 发布闸]
  end
  DSH[DSH AI Server 外部编排] -->|MCP 只衰减 token|MCP[mcp_gateway/api_catalog 现有]
  RES -->|confirmed 实体| REG
  CS -->|confirm 物化| RES
  WF -->|call 节点|MCP
  WF -->|agent 节点| AG[agents.start_run 沙箱 现有]
  WF -->|human_approval| AP[automation_approvals 现有]
  WF -->|证据候选| EV
  EV -->|采纳仍走人工闸| PRJ
  REG -->|编译预览| CMP
  CMP --> SOL
  CMP --> WD
  BJ -.驱动.-> WR
```

依赖方向（单向）：Registry←Engagement（读 confirmed）；Compiler←Registry；Workflow 只调既有闸（MCP/agents/approvals），不直写业务表（除证据候选）；Quality 横切。事务边界：change_set confirm=单事务逐项物化+事件；workflow 每节点独立事务先落表再前进（崩溃恢复锚点）；外副作用节点幂等键+不可恢复重投哲学（沿用 automation.execute）。错误恢复：workflow=节点级重试+paused 恢复+cancel；registry=base 指纹 409；文档=既有 sha256 短路。

## 8. Ontology Registry 设计

**`docs/architecture/ontology-registry-v1.md`**（P0）。决策要点：不建平行实体体系（subjects 就是实体）；ontology_packages/versions/entities/relations/evidence_links/review_decisions 六个候选表经查重**全部不建**（各有既有等价物），只建 terms+aliases/relation_types/change_sets 三件 + evidence 底座；AI 产物唯一入口=change_sets.proposed_json，confirm 前不物化（防"检索结果当业务事实"）；类型注册用 ∪ 语义不动存量 CheckConstraint。

## 9. Workflow DAG 设计

**`docs/architecture/workflow-dag-v1.md`**（P1）。决策要点：不复制队列——workflow 是 background_jobs 新 job_type；四类节点（call/skill/agent/human_approval，无 condition/wait——when+depends_on 已覆盖）；校验器纯函数先入 CI（环检测修 fde-v2 静默 done、call.ref 白名单封 SSRF、published skill 显式版本）；执行=每节点走既有闸（绝不旁路 api_execute/start_run/approvals）；fde-v2 执行器五项可靠性缺陷全部作为 V3 验收用例的反向锚。

## 10. Agent 权限与 Skill 生命周期

**`docs/architecture/agent-policy-v1.md`**（P1）。决策要点：五条权限原则现状全部 VERIFIED 保持（每调用实时鉴权/只衰减/写外副作用显式/审批绑定 sha256 目标/直连不绕过）；补强=ToolGroup（只收窄交集，种子文件零新表）+effect/risk 结构化元数据+审批卫生三件；Skill 以 WB 双表为底座扩 draft/in_review/published/deprecated+发布四闸（含测试报告或显式 waive）+回滚（版本行不可变故安全），**明确不采用** fde-v2 的 exec 装配角色、隐式页面授权、prompt 角色标记、user=None 全通、聊天-only HITL 五项机制。

## 11. G1–G9 集成方案（决策 4 落实）

- 职责铁三角维持并强化：**Workflow 执行产证据候选**（gate_evidence 标记→project_evidence→checklist 候选项 claim_status=None）；**Gate Service 唯一状态机**（submit/decide 唯一 HTTP 入口=真人会话，全仓无第二写路径已 VERIFIED）；**人工拍板**（五道闸不动；Agent 文字输出≠门禁通过——api_catalog 无 gates 条目且 grep 证实）。
- 新增仅"采纳"一步（人工点击把候选转正式证据提交，走既有 submit 闸）。
- 顺带修复：template_hash 漂移呈现（T-G2）；任务证据与清单脱钩（T-G1）。

## 12. Delivery Compiler 方案（P2，最小闭环）

输入=confirmed change_set + industry_template（published）+ gates 状态摘要；输出两类**草稿**：①方案骨架（复用既有 solutions /skeleton 纯模板路径，附 agent_trace 式来源标注）；②workflow 定义草稿（dag_json 模板化：调研→方案→审阅三节点）。纯函数（`workflows/compiler.py`）无副作用、可快照测试；落库一律走人工确认端点。**不做**全自动"本体→代码"（fde-v2 的构建期形态依赖外部代理施工，不适合 WB 服务端定位）。

## 13. 文件级改造清单（P0/P1 全量；PROPOSED 路径已标注）

| 动作 | 文件 | 任务 |
|---|---|---|
| NEW | server/src/fde_api/evidence/{__init__,models,service,routes}.py | T-E1 |
| NEW | server/src/fde_api/ontology/{__init__,models,service,routes}.py | T-O1~O3 |
| NEW | server/src/fde_api/workflows/{__init__,models,definition_service,executor,compiler,routes}.py | T-W1~W5/T-C1 |
| NEW | server/tests/test_{evidence,ontology,workflow_definition,workflow_executor,skill_lifecycle}_registry.py | 随任务 |
| NEW | server/seeds/tool_groups.json；desktop/src/renderer/src/{workflows/WorkflowConsole,ontology/GlossaryPage,extensions/SkillVersionsPage}.tsx | T-R1/T-UI1 |
| EXTEND | projects/gate_service.py、projects/task_service.py、solutions/service.py、agents/service.py、agents/tools.py、control/{models,extensions_service,builtin_skills,mcp_gateway,api_catalog,scheduler,service}.py、research/{subject_service,models,imports}.py、documents/{snapshots,ai_content,generator}.py、jobs/{outbox,worker,handlers,reconcile}.py、ai/{ai_server_client,ai_tool_loop}.py、bridge/sync.py、app.py（新蓝图） | 各任务 |
| 迁移 | server/migrations/versions/ 新增 4 个 revision（evidence；ontology×2；workflow×2；skill 扩列——按发布列车分批） | 各任务 |
| 不触碰 | workbench/models.py 既有列、guidance/translator 全链、bridge 投影语义、dispatch、meetings、DSH 客户端协议 | 兼容边界 |
| 意图锚指针（不改造） | docs/SES发信模块-G9.md（mailing 发信模块：默认整体关闭 + 启用清单）、docs/goal-d13-交付工作台.md 与 docs/goal-d14-交付工作台.md（translator 管道切 kimi-k3 与独立槽位）、docs/goal-d1-交付工作台.md 与 docs/goal-d2-交付工作台.md（guidance 预调研/确认流与 P0 四指标埋点） | CR-011：三包意图锚集中可查位置（只补指针，不动三包实现面） |

## 14. 数据表和迁移设计

新增 8 表（全部 PROPOSED，结构全文见 ontology-registry-v1 §2 / workflow-dag-v1 §2）：`project_evidence`、`ontology_terms`、`ontology_term_aliases`、`ontology_relation_types`、`ontology_change_sets`、`workflow_definitions`、`workflow_definition_versions`、`workflow_runs`、`workflow_node_runs`（9 张）；扩列 2 处（skill_definitions/skill_versions 治理列）。通用约定：UUID PK、project_id 复合 FK CASCADE（项目隔离）、version 乐观锁、status CHECK、created/updated、reviewer/confirmed_by 审核列、content_sha256 指纹；**全部走 Alembic 单链新增+downgrade**，历史数据零改写（evidence_id 可空列/JSON 内新键向后兼容）。等价表查重结论见 §8（六个候选表不建的理由）。

## 15. API 契约

新增端点四组（全部 PROPOSED，完整 schema 见三份架构文档 §4-§5）：
1. 证据：POST/GET `/api/v1/projects/{id}/evidence`（can_manage/can_view；sha256 幂等）。
2. 本体：GET terms；POST/confirm/reject change-sets（can_manage+提交人≠确认人）；GET/POST relation-types（全局 admin）。
3. 工作流：POST workflows（draft）/publish（admin）/runs（422 dag_invalid 带）；GET runs 树；POST cancel。
4. Skill：submit-review/publish/rollback/versions（admin+密码确认）。
共同纪律：**不进 api_catalog**（AI 不可直接触达，同 signoff 先例）；错误码 400/403/404/409/422 语义与既有体系一致；幂等策略逐端点注明。

## 16. 测试、安全和验收标准

- 实跑基线（本轮真实执行，2026-11-02）：**服务端 pytest 1700 passed / 6 skipped / 0 failed（1706 收集，25:02，exit 0，与 d13 口径完全一致）**；**vitest 730/730 passed（60 文件，400.78s，exit 0）**；**operations 14/14 pass（0.78s，exit 0）**。详录与环境备注见 `docs/audit/v3-test-inventory.md`。fde-v2 verify 套件按零执行纪律未跑（原因已记录）。
- 验收体系：`docs/implementation/v3-test-plan.md`——本体 8 用例族（候选不自动发布/跨项目拒/confirmed 不可变/合并保留来源/证据历史/影响分析/类型注册/导入去重）、Workflow 10 用例族（环检测→固定版本）、权限安全 9 用例族（注入不扩权/撤销即时/审批不复用/日志不泄密/发布越权）、门禁交付物 5 用例族（Agent 文字≠门禁/快照血缘/迁移升降级）。
- 安全红线重申：证据只存指针+sha256；新表全 project_id 隔离；AI 不可写本体/门禁/发布端点；外副作用必审批且不可恢复重投。

## 17. 分阶段实施计划

| 阶段 | 内容 | 任务 | 出口判据 |
|---|---|---|---|
| P0 | 死锁修复 + 证据一等表 + 本体最小闭环（terms/types/change_sets+导入去重） | T-P0-1、T-E1~E3、T-O1~O4 | 死锁端到端绿；本体 8 用例族绿；全量 pytest/vitest 绿 |
| P1 | Workflow（call/skill 先行→agent/approval→cancel/resume）+Skill 治理+工具组+权限卫生+jobs 补强 | T-W1~W5、T-S1~S2、T-R1~R2、T-J1~J2、T-P1-4/5、T-OBS1 | Workflow 10 用例族绿；skill 发布闸上 CI；4 CI job 绿 |
| P2 | 证据候选接门禁 + 文档血缘补洞 + Compiler 最小闭环 + 影响分析 + 桌面三页 | T-G1~G2、T-D1、T-C1、T-I1、T-UI1 | 门禁候选端到端；版本行可反查 ai_call/revision；打包 asar 验证过 |
| P3 | 多 Agent 自适应/Skill 进化/规则推理/有限自动执行 | 立项不排期 | P0–P2 安全可靠性验收全绿后评估 |

节奏：纳入既有 goal-d 循环逐任务交付（每任务独立 PR→CI 4 绿→合并→ff main→更新本报告状态列）；不并行开第二实施线。

**六铁律裁决回写（2026-11-06，v3-迁移进度对照报告 §六 #6 清偿）**：fde-v2 建议「BUG 回路六铁律」对 WB 的判定在此明示——**开发轨**（人/agent 开发代码）以既有「先红后绿测试 + CI 4 绿 + 单 commit revert + PR 纪律」等效（即本章节奏行所载流程，此为有意裁决非缺口）；**运行期自动修复轨暂无需求，有意不做**——若未来做 agent 落码（P3 立项 §3 评估时），须补 ①逐字 old→new 替换 / ③改前备份 / ④语法门 ast.parse / ⑤自动重测 四件（②白名单已有等价物＝api_catalog 白名单制；⑥对账消项已有等价物＝B#6《状态归属与对账》六跨层钉）。红线级部分回写先行落地三处：AGENTS 红线第 7 条（B#3「AI 审查不执行被审代码」）、B#2 回执「写错只重写不重做」语义（agent_runs 终态 `succeeded_but_receipt_invalid`）、#126 评估报告「写类外呼/发信/付款永不降级、现役可降级集合=∅」。

## 18. 风险与回滚策略

**`docs/audit/v3-risk-register.md`**：WB 现状缺陷 14 项（1 高 4 中 9 低，全部行号证据）、fde-v2 教训 11 项（不构成 WB 现网风险，仅防重蹈）、V3 实施风险 8 项（含 workflow 资源面、Registry 双轨分裂、迁移兼容、越权回归、双轨证据不一致）。回滚策略：全部新表 alembic downgrade 安全（零外键反依赖）；每个任务单 commit revert；种子文件无状态；桌面页独立路由可整体隐藏；发布火车任意站点可止步（各阶段出口判据独立）。

## 19. 不建议照搬的 fde-v2 设计（7 项，均有代码证据）

1. **flow.py 执行器**：环静默 done、无重试/恢复/取消/幂等、call 越权不中止、绕 HITL（附录 B 2-6）——只搬 YAML 形态与节点三分法。
2. **运行时 DDL reconcile + SQLite 静默回退 PG**：与迁移纪律冲突（附录 E 2-3）。
3. **隐式页面授权（X-Fde-Page 派生服务放行）**：前端声明=权限扩大（附录 E 4）。
4. **exec 装配 _roles.py + system_prompt 角色标记**：任意代码执行面与提示即权限（附录 B 7）。
5. **无鉴权模式 user=None 全通 + stdio MCP 缺省全通**：fail-open 部署面（附录 E R5'/R9'）。
6. **内省全量工具面（~180 服务直暴露）**：WB 白名单制（17+94）在攻击面上量级更优（附录 B/E 对照）。
7. **agentscope 进程内多 Agent 团队**：引入第二运行时+内网服务面，DSH 已承担编排（附录 B 9 vs C 6）。
另：LightRAG 知识图谱层其自身定位即"检索层非治理层"（本体对象.md 自认非本体），WB 无消费方前不引入（P3 评估）。

**补记（2026-11-06，两项裁决定性回写——v3-迁移进度对照报告 §六 #10 清偿；非新增照搬对象，上方清单维持 7 项）**：

- **SQLite 影子库测试隔离（fde-v2 形态）**：WB 用 PG `*_test` 专用库硬闸（仅 psycopg / 库名白名单 / host 回环 / advisory lock 串行，`server/tests/conftest.py:61-91`）——形态更严，**判定等效、不照搬**；本条即「后人再评估成本」的销号定性（方法论清单 P2「影子库」项就此闭合）。
- **view_watchdog 卡死现场取证**：WB 无 e2e 卡死取证等价物，**未立项（有意不做）**——代码零命中，仅文档两处提及（`docs/audit/v3-fde-v2-module-inventory.md:23`、`docs/audit/appendix/fde-v2-E:8` 上游文件清单）；如未来上长驻自动化执行面（P3）再评估。

## 20. 最终决策与下一步行动

**决策**（对应任务书六大决策）：①本体分层裁定=文档/候选/正式/规则/事实五层各归其位，RAG 不建；②最小模型=3 新表+底座（6 候选表查重不建）；③Workflow=jobs 新 job_type 不复制队列，与 automation 三表职责边界=触发器/DSH 会话 vs 编排/节点；④G 门禁铁三角不动，workflow 只产证据候选；⑤权限五原则保持+三补强，fde-v2 五机制明确不用；⑥Skill=WB 双表扩治理态不另建。

**下一步 3 件事**（建议顺序）：
1. **T-P0-1 signoff 死锁修复**（S，独立 PR，先红后绿端到端用例）——现网功能阻断，收益立现。**→ 已完成（2026-11-02，fix/v3-t-p0-1-signoff-deadlock；实现偏差——统一开闸模块 `agents/signoff.py`、L1 排除、export 兜底开闸先提交再 409、`remedy=resolve_pending_signoff`——已回写 backlog T-P0-1「实施记录」）**
2. **T-E1 一等证据表 + T-E2 门禁挂接**（M）——全部 V3 数据治理的地基，且立即改善门禁证据审计（历史指针不再覆写）。**→ 已完成（2026-11-02，fix/v3-t-e1-e2-evidence；偏差——POST 201/200 按 created、referenced_by 仅 gate:Gx、新事件 evidence_registered、延迟导入——见 backlog T-E1/T-E2 实施记录）**
3. **T-W1 DAG 校验器（纯函数）先行入 CI**（M）——零执行器依赖即可锁定定义质量，为 P1 铺路且无运行时风险。**→ 已完成（2026-11-02，feat/v3-t-w1-workflow-definitions；两表 + 纯函数 1–8 阻断 / 9 告警；零路由——偏差见 backlog T-W1 实施记录）**
4. **T-W2 runs/node_runs 两表**（S）——执行器的地基，纯增量。**→ 已完成（2026-11-03，feat/v3-t-w2-workflow-runs；迁移 `b7d9f1a3c5e2`，run 幂等键全局唯一修 FV-F3、definition RESTRICT / project CASCADE、节点 depends_on 冗余快照——见 backlog T-W2 实施记录）**
5. **T-W3 执行器（call+skill 节点）+ §5 路由**（M）——Workflow 线业务价值的第一块闭环。**→ 已完成（2026-11-03，feat/v3-t-w3-workflow-executor；`workflow.run` handler 复用 jobs 全套、节点独立事务、call=api_execute 同闸+写类节点同构幂等键、skill=pinned 版本确定性 AI 调用、§5 五条路由（cancel/resume HTTP 随 T-W5）、agent/human_approval start_run 即 422 随 T-W4；skill published 语义按 T-W1 先例待 T-S1 收敛——偏差见 backlog T-W3 实施记录；下一步 T-W4 / T-W5 或 T-S1）**
6. **T-W4 执行器 agent/human_approval 节点**（M）——四类节点闭环；human_approval 复用 automation_approvals（迁移 `d5b8e2f4a7c9`：run_id 可空 + workflow_node_run_id 反链），拍板走既有任务中心零新路由，agent 走 agents.start_run 同闸（attempt 代际幂等键）。**→ 已完成（2026-11-03，feat/v3-t-w4-agent-approval-nodes；偏差——审批反链 FK CASCADE/迟到拍板中和/attempt 代际幂等/分派失败不叠加重试/capability 白名单=登记表去 system.*——见 backlog T-W4 实施记录；下一步 T-W5 / T-S1 / T-E3 / T-O1）**
7. **T-W5 cancel/resume HTTP + reconcile 收敛**（M）——Workflow 服务端面收口：cancel（幂等，终态 409）/resume（failed-only，409 not_resumable）两条 can_manage 路由（276→278），reconcile 收敛已随 T-W3 落地无残留。**→ 已完成（2026-11-03，feat/v3-t-w5-cancel-resume；零服务层改动零迁移，服务层 cancel_run/resume_run 直挂 HTTP——见 backlog T-W5 实施记录；下一步 T-S1 / T-E3 / T-O1 或 T-W6 桌面控制台）**
8. **T-S1 Skill 治理态扩展**（M）——`draft/in_review/published/deprecated` 四态 + 发布四闸（admin/密码确认/in_review/测试报告或 waive）+ `_skills` 只回 published；迁移 `c1e5f9a3d7b2`（27 rev），路由 +5（submit-review/publish/rollback/deprecate/versions）=283；T-W1/T-W3 的 skill published 挂账清偿。**→ 已完成（2026-11-03，feat/v3-t-s1-skill-governance；偏差——个人 Skill 自发布豁免/种子内部参数直发布/PATCH 启停开关旧值域作别名防旁路——见 backlog T-S1 实施记录；下一步 T-E3 / T-O1 / T-W6 / T-S2）**
9. **T-S2 Skill 效果统计 + 治理留痕**（M）——双消费面计数 `skill_used_chat`／`skill_used_workflow`（失败不计、attempt 代际各计一次、`skill_list` 不计数）＋ versions 响应增 `usage` 块（total/chat/workflow/last_used_at/by_version/truncated，有界 1000 条 Python 聚合）＋ 治理四事件（skill_review_submitted/published/rolled_back/deprecated）直落 `operation_events`。**→ 已完成（2026-11-03，#86；零迁移零新路由零桌面改动；计数走独立微事务——直连 AI 工具循环每轮回滚共享会话，自带提交才能存活）**
10. **T-W6 桌面控制台三面**（M）——NEW `WorkflowConsole.tsx`＋`GlossaryPage.tsx`＋`SkillVersionsPage.tsx`，另补两条 can_view 只读挂件（GET 定义列表／GET run 列表，有界 50/200＋truncated、**行不带 nodes 防 N+1**）。**→ 已完成（2026-11-04，#88；实现偏差——T-W5「HTTP 面即完整面」对 run 列表不成立，补两条只读挂件，路由 293→295；偏差已回写 backlog T-W6＋`workflow-dag-v1` §5 注记）**
11. **T-O4b 桌面合并 UI ＋ T-O4 桌面导入 UI**（S）——对象树合并入口＋归档行回链（`ResearchMergeResultDto` 契约）；调研导入 preview/commit 两段式对话框＋导入结果让位回溯卡片。**→ 已完成（2026-11-04，#101/#102；服务端零改动）**
12. **T-G2 门禁 template_hash 漂移呈现 ＋ T-D1 文档血缘补洞**（M）——`_serialize_gate` 增 `template_outdated`（冻结哈希 vs 现行 `gates.json`，NULL 判 false 不误报）；快照 `revision_id`＋gates 摘要＋AI `request_id` 闭环反查 `ai_call_audits`（单一谓词防幽灵血缘）。**→ 已完成（2026-11-04，#100/#104；T-D1 迁移 `e2c6a8f4d1b3`；T-G2 迁移 `f7a2c9e4b1d3` 回填）**
13. **T-C1 Delivery Compiler ＋ T-I1 本体变更影响分析**（M）——`compile_delivery_preview` 纯函数（confirmed 变更集＋行业模板＋门禁摘要 → ①方案骨架 payload ②workflow 定义草稿 dag_json ③provenance；真实目录白名单全绿、落库走人工确认端点）；`impact_of_term` 名字域纽带三面清单（subjects/links/forms；引用合同＝名字域纽带，血缘闭包＝canonical 链到根∪并入行）。**→ 已完成（2026-11-05，#105/#107；T-C1 零迁移零路由零桌面；T-I1 +1 只读路由 297、不进 api_catalog；gates 面按验收权威 O-6 落三面＝偏差回写 backlog）**
14. **T-W7 workflow 产物→证据候选 ＋ T-UI1 三页核销与 GateBoard 徽标**（M）——运行时保留键 `gate_evidence`＋坏标记不炸节点＋同事务原子挂候选；候选 `source_kind` 判别联合修复 workflow 候选整板拒载潜伏 bug。**→ 已完成（2026-11-05，#111/#113；**铁三角全链接线**——门禁候选采纳的唯一入口仍是真人提交闸）**
15. **T-J2 handler 自动重试 ＋ admin 取消 API**（S）——`run_job` 异常走 `_handle_failure`（可重试集合复用 `RECOVERABLE_JOB_TYPES`、30s×2 封顶 900s、outbox 保持 `dispatched`＝T-J1 红线）＋NEW `jobs/admin_routes.py`；迁移 `d9f4a7c2e6b1`（35 rev，cancelled 真状态纯 CHECK 置换）。**→ 已完成（2026-11-05，#116；路由 297→298）**
16. **P3 高级自主化四项**（—）——①多 Agent 自适应编排 ②Skill 运行反馈改进 ③业务规则推理 ④有限自动执行开放评估。**→ 已完成（2026-11-05 立项 #117 → 状态轮 #125 → 评估报告 #126）：四项全部定案收口**——①多 Agent 仍冻（活库 `agent_runs=0`／`workflow_runs=0`）②Skill 失败面维持「失败不计」、双面消费量闸未过仍冻③`ontology_rules` 维持不建 PARK＋**规则 9 强制化悬置线销号＝维持告警**（执行层硬闸已闭环，「P2 enforcement wave」不做）④评估轮解冻后报告落定（八档 G0–G7＋S、**现役可降级集合＝∅**、本报告不开放，闸态变更 0）。**→ 附：桌面影响分析消费面（GlossaryPage 行内三面清单）已随 2026-11-06 待办池清欠轮接线**
17. **P0 先行批（开源借鉴线 B 系列）**（M）——**属另一条「七项目横评」借鉴线**（含 fde-v2 但编号体系独立，**不计入本报告 §二 的 fde-v2 迁移任务计数**）：代码级 **B#1 跳数熔断**（`workflow_runs.hops`＋`MAX_RUN_HOPS=8`）／**B#2 回执终态**（`succeeded_but_receipt_invalid`＋scanner 四态）／**B#4 purity 架构测试**（四断言静态探针）／**B#28 门禁 revision CAS**（`decide_gate` 增可选 `expected_revision`＋`gates.lifecycle_version`，409 `gate_revision_conflict`）／**B#5 审批退避提醒＋SLA 统计**；文档级 **B#3 审查不执行被审代码**（AGENTS 红线第 7 条）／**B#6 状态归属与对账**（四层归属总表＋六跨层钉 pytest）／**B#21 交付效果评测协议 v0**（uplift 算分口径＋三锚点四类反例＋G9 `exit_condition` 接线）／**B#22 门禁判据升格**／**B#27 DSH 适配层决策记录**（维持「当前不装」）／**B#29 验收合同五点**。**→ 已完成（2026-11-05~11-06，#128~#131＋#135；合并迁移 `b2e8f4a6c9d3`（36 rev）；Q1–Q3 未拍板前 B#21–#25 停文档/夹具层，B#23 离线夹具未解封）**
18. **五份纯文档立项/契约**（S）——术语改名 SOP（`术语改名SOP-v1`，名字域纽带四步改名）／外部文字禁入与原件派生分离契约（提示词层白名单＋工件层五原则）／门禁判据实施落点（裁决＝评测器元验证层）／门禁前置复核与回退留痕立项（A 面证据漂移呈现候选 ＋ B 面回退语义待拍板 opt1/opt2/opt3）／到期语义与主动超时治理立项。**→ 已完成（2026-11-06，#137/#142/#143/#144/#141；零代码零迁移零路由零桌面；**立项≠实施授权**，实施排后续轮）**
19. **UI-UX 黑金 B/S0/S1 全量落地 ＋ B#9 只读执行事实链面板**（M）——token 单一真源＋a11y 钩子＋品牌资产＋官网单页（155 文件（67 纯增／54 改／33 二进制／1 删；13557 插入＋591 删除）、**零 server 改动、零迁移改动**，删改集中于品牌资产与桌面 UI、**未触及任何 V3 轮次文件**，品牌单点 `desktop/src/shared/brand.ts` 未移动）；B#9 事实链只读面（NEW GET `…/projects/{id}/execution-facts`，can_view、三源归并、**有意不进 api_catalog**）＋桌面 NEW `ExecutionFactChain.tsx`（项目 tab 10→11）。**→ 已完成（2026-11-06，#132/#145；路由 300→301、pytest 1985 收集＝1979 passed＋6 skipped、桌面 vitest 825）**

**§20 实施跟踪注记补齐说明（2026-11-06）**：本节此前停更于 T-S1（条目 8）——T-S2 及其后全部轮次无对应条目。原因是并发品牌·回滚轮在途，补注记须逐轮核对「哪些轮次仍在基线上」，**补即写即错**，故按 goal-c 台账 CR-003 挂账待落定后一次性补。**该回滚轮已于 2026-11-06 15:02 落定为 #132（零 server 改动、零迁移改动；删改集中于品牌资产与桌面 UI、未触及任何 V3 轮次文件）**，V3 实施进度对照报告 §三 全量判定逐行复测**无一被推翻**，故条目 9–19 一次性补齐。**注记口径**：每条只写「做了什么 ＋ 偏差指针」，实现细节一律指 backlog 实施记录与 `docs/implementation/v3-迁移进度对照-fde-v2建议-2026-11-04.md`（第七轮）；B 系列条目仅登记跨线事实、不改写本报告 §二 的 fde-v2 判定。

---

### 附：交付物清单（全部实际落盘）

| 文件 | 状态 |
|---|---|
| docs/architecture/蔡工FDE_Workbench_fde-v2架构融合审计与V3升级实施方案.md（本文） | ✅ |
| docs/audit/v3-baseline-workbench.md / v3-baseline-fde-v2.md | ✅ |
| docs/audit/v3-workbench-module-inventory.md / v3-fde-v2-module-inventory.md | ✅ |
| docs/audit/v3-route-inventory.csv（**workbench 302 行＝表头＋301 路由**；fde-v2 116 行已分仓至 `v3-route-inventory-fde-v2.csv` 117 行） | ✅（2026-11-06 第七轮随 #145 回刷：脚本补登 `fact_chain_blueprint` 后重生成） |
| docs/audit/v3-database-inventory.csv（**workbench 106 行＝表头＋105 表**；fde-v2 25 行分仓至 `v3-database-inventory-fde-v2.csv` 26 行） | ✅ |
| docs/audit/v3-test-inventory.md | ✅（pytest 1700+6s / vitest 730 / ops 14 实跑终录已回填——**此为审计期实跑快照记录，非当前口径**，当前口径见 AGENTS.md「当前状态」节） |
| docs/audit/v3-gap-matrix.md（17 域）/ v3-risk-register.md | ✅ |
| docs/audit/appendix/{A–F 六份行号级原始审计报告} | ✅ |
| docs/architecture/ontology-registry-v1.md / workflow-dag-v1.md / agent-policy-v1.md | ✅ |
| docs/implementation/v3-backlog.md（**33 个 T-\* 任务节全 DONE ＋ 开源借鉴登记段 B#1–B#40**）/ v3-test-plan.md（四族用例） | ✅ |
| scripts/audit/extract_{workbench,fde_v2}_inventory.py（可复现抽取） | ✅ |
