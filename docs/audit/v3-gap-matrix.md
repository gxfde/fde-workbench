# V3 融合差距矩阵（17 能力域）

- 基线：Workbench @ `0570384`（分支 fde-v2，96 表/269 路由/22 迁移）；fde-v2 快照 ≈ `master@39e0e62`（v2.3.0b0，17 平台表/116 路由/无迁移系统）。
- 证据索引：附录 A（fde-v2 流水线/本体）、B（fde-v2 工作流/Agent/Skill）、C（WB 控制平面）、D（WB 本体/调研）、E（fde-v2 安全/DB/运行时）、F（WB 门禁/文档/任务），均在 `docs/audit/appendix/`。
- 状态口径：已实现 / 部分实现 / 缺失 / 待核实。可信度：VERIFIED（代码行级证据）/ PARTIALLY VERIFIED / PROPOSED（本文档中的新增设计，一律如此标注）。

## 0. 总览矩阵

| # | 能力域 | Workbench | fde-v2 | 建议动作 | 优先级 | 可信度 |
|---|---|---|---|---|---|---|
| 1 | 项目与交付生命周期 | 已实现（项目+SOP+G1–G9+任务+派单+收款） | 部分实现（应用=聚合根树，无交付流程概念） | REUSE（WB 全套）+ EXTEND（G8/G9 与派单闭环已有） | — | VERIFIED |
| 2 | 业务本体与 DDD 建模 | 部分实现（静态 ontology.py + 类型化调研实体） | 部分实现（md 规格九步法 + KG 候选清单，自认非本体） | EXTEND（research 域）+ NEW（术语表/一等证据/变更集） | P0 | VERIFIED |
| 3 | 证据链和来源追溯 | 部分实现（source_uri+sha256 指针散布 4 处，无一等证据表） | 部分实现（KG 出处=文件+chunk；BR 依赖输入文本） | NEW（evidence 一等表）+ EXTEND（各指针列挂接） | P0 | VERIFIED |
| 4 | 业务流程与状态机 | 已实现（gates 5 态 + form/guidance/template 状态机 + SOP 节点） | 部分实现（详设 md 状态机为文本；运行时无流程引擎） | REUSE；EXTEND（任务证据与门禁清单挂钩） | P2 | VERIFIED |
| 5 | Workflow DAG | 缺失（job 单原子、无节点图） | 部分实现（flow.py 三类节点；无环检测/重试/恢复/取消/幂等） | NEW（definitions/runs/node_runs 三表）+ REUSE（background_jobs/outbox/worker） | P1 | VERIFIED |
| 6 | 多 Agent 编排 | 部分实现（DSH 外部编排 + 单 agent 沙箱 run + L0-L3 降级） | 已实现（AgentScope leader/worker 团队 + flow 节点） | DEFER（编排主体留在 DSH；WB 只做受控 call/skill 节点） | P3 | VERIFIED |
| 7 | Agent Role 与 ToolGroup | 部分实现（capability 五档 + agent.allowed_tools + 三重交集；无角色预设/工具组） | 已实现（_roles.py + 工具过滤中间件 + 预算 ≤25/15） | EXTEND（角色预设=纯收窄白名单；不引入 fde-v2 exec 装配） | P1 | VERIFIED |
| 8 | Skill 生命周期 | 部分实现（skill_versions 不可变 + active/disabled；无 review 态/测试报告/回滚） | 部分实现（draft→approved→deprecated；version 计数器可变；无测试/回滚） | EXTEND（WB 表加 review 态 + 发布门禁 + 回滚；不抄 fde-v2 单表） | P1 | VERIFIED |
| 9 | MCP 与 API 工具调用 | 已实现（MCP TOOLS 17 + api_catalog 94 + 只衰减 token + 双闸） | 已实现（三面共桥 + 全量服务暴露 + MCP Bearer） | REUSE（WB）；EXTEND（结构化 risk/external_side_effect 元数据） | P1 | VERIFIED |
| 10 | 权限与审批 | 已实现（实时鉴权/审批一次性/密码确认/执行前复查；发现 2 处口径缺陷） | 部分实现（gate+授权；守卫失效 R1/SSRF R2/无 CSRF R4） | REUSE；EXTEND（修 signoff 权限口径 + 审批过期清扫） | P0 | VERIFIED |
| 11 | 测试与质量门禁 | 已实现（pytest 1700+ / vitest 730 / CI 4 job / 变异测试史） | 部分实现（verify 脚本四层 + 变异自检；无 CI、需活环境、psc 专属 oracle） | REUSE（pytest 体系）+ EXTEND（workflow/ontology/skill 门禁用例） | P0 | VERIFIED |
| 12 | 交付文档生成 | 已实现（四表模型/异步渲染/快照冻结/不可变版本/交付审计） | 缺失（无文档生成模块；_contracts.md 是 API 契约非交付文档） | REUSE；EXTEND（血缘补 revision_id + ai_call 反查） | P2 | VERIFIED |
| 13 | 数据库迁移和版本 | 已实现（Alembic 22 revision 单链 + CI 环境解耦） | 缺失（无迁移系统；启动 reconcile 只补列；PG 静默回退 SQLite） | REUSE（WB）；**不引入** fde-v2 reconcile 机制 | — | VERIFIED |
| 14 | 异步任务、重试与恢复 | 部分实现（outbox+lease+token+reconcile 白名单；handler 无自动重试、无取消、状态不闭环） | 弱（APScheduler 单进程；无重试/幂等/分布式锁） | REUSE（WB 骨架）+ EXTEND（节点级重试/取消/outbox 闭环） | P1 | VERIFIED |
| 15 | 可观测性、审计和成本 | 部分实现（operation_events + ai_call_audits + 预算三层；降级路径不落审计） | 弱（无操作审计表；LLM 无成本记录；call_logs 入参明文） | EXTEND（审计补洞：降级 chat 落账、outbox 闭环） | P1 | VERIFIED |
| 16 | 前端与桌面端交互 | 已实现（Electron+React+契约测试 730） | 部分实现（无构建 Alpine.js + 扫描发现；无桌面端） | REUSE；EXTEND（工作流/本体控制台页面） | P2 | VERIFIED |
| 17 | 部署和运维 | 已实现（compose 四服务 + 健康检查 + 心跳 + CI） | 部分实现（compose 五服务；root 运行、密钥入镜像风险、无 HSTS） | REUSE（WB）；不复制 fde-v2 部署面 | — | VERIFIED |

---

## 逐域详表（每域 17 字段）

### 域 1：项目与交付生命周期

| 字段 | 内容 |
|---|---|
| Workbench 现状 | 已实现：projects（template_snapshot/research_snapshot 立项冻结）、project_modules/tasks、SOP 节点、G1–G9 门禁、报价/合同/收款、派单（dispatch 8 表）、交付包 |
| Workbench 证据 | workbench/models.py:235-617；gate_service.py 全文；dispatch/models.py 8 表；附录 F Q1–Q5 |
| fde-v2 现状 | 部分实现：应用（聚合根树）即"项目"，无交付流程/合同/收款概念；组=隔离单元 |
| fde-v2 证据 | runtime.py:90-132 discover_apps；附录 A B9 |
| 差距 | 两者"项目"含义不同：fde-v2 是代码生成目标应用，WB 是交付管理对象——不可互换，只可借鉴其"立项=冻结快照"思想（WB 已有） |
| 建议动作 | **REUSE**（WB 全套不动，作为 Engagement OS 层事实源） |
| 目标文件 | 无改动 |
| 数据模型 | 无新表 |
| 接口 | 已有（projects 蓝图 31 路由） |
| 安全影响 | 无 |
| 实施任务 | 无（仅回归保障） |
| 测试与验收 | 既有 test_projects_api / test_gates_api 继续作准 |
| 优先级 | — |
| 依赖 | — |
| 可信度 | VERIFIED |

### 域 2：业务本体与 DDD 建模

| 字段 | 内容 |
|---|---|
| Workbench 现状 | 部分实现：`control/ontology.py` 为**静态 dict**（fde-business-ontology-2，仅 MCP ontology_read 消费）；调研域有类型化实体（5 类 subject）、有类型边（2 种 link_type 硬编码）、修订/确认状态机；无术语表、无一等证据、无变更集、无合并去重 |
| Workbench 证据 | ontology.py:8-70；research/models.py:149-365（CheckConstraint 163-166、links 白名单 31-34）；附录 D ①③④⑨⑩ |
| fde-v2 现状 | 部分实现：候选识别=KG 导出清单（自认"不是本体"）；聚合根/BR 建模=md 规格流程（架构设计.md Skill 六步启发式）；机器可校验仅"边对账 + BR 三要素"两个窄面；无本体库/版本/审核/diff |
| fde-v2 证据 | knowledge_graph.py:602-715（"不做判断、不划边界"）；本体对象.md 头部自认；附录 A B6/B7 |
| 差距 | **两边都没有"可治理的正式本体"**。WB 离正式本体最近（类型化实体+修订链+确认流已成型）；fde-v2 的价值是"从材料到候选"的方法论（KG 导出带出处/源块）与 BR 三要素机器可读纪律，而非实现 |
| 建议动作 | **EXTEND**（research 域扩为 Ontology Registry 底座）+ **NEW**（术语表 ontology_terms、关系类型注册 ontology_relation_types、变更集 ontology_change_sets 三件最小新表） |
| 目标文件 | EXTEND：server/src/fde_api/control/ontology.py（拆为 registry 服务的只读投影）、research/models.py、research/subject_service.py。NEW（PROPOSED）：server/src/fde_api/ontology/{__init__,models,service,routes,glossary}.py |
| 数据模型 | 复用：project_research_subjects/_links/_form_revisions、module_catalog。新增（PROPOSED）：ontology_terms、ontology_term_aliases、ontology_relation_types、ontology_change_sets（详设计见 docs/architecture/ontology-registry-v1.md） |
| 接口 | 已有：POST /projects/{id}/research/subjects 等。拟新增（PROPOSED）：GET/POST /api/v1/projects/{id}/ontology/terms、POST …/ontology/change-sets、POST …/ontology/change-sets/{id}/confirm |
| 安全影响 | 术语/关系类型默认项目内（project_id+复合 FK 同项目）；全局词表仅 admin；confirm 需 can_manage；候选（AI 产）永不自动 confirm |
| 实施任务 | 见 v3-backlog.md T-O1~T-O4 |
| 测试与验收 | 候选不自动成为发布本体；跨项目读写被复合 FK+服务层拒绝；confirmed 不可原地改；术语合并保留来源；删除证据不改历史引用 |
| 优先级 | **P0** |
| 依赖 | 域 3（一等证据表先行） |
| 可信度 | 现状 VERIFIED；方案 PROPOSED |

### 域 3：证据链和来源追溯

| 字段 | 内容 |
|---|---|
| Workbench 现状 | 部分实现：4 处指针式证据（gates.evidence_uri/hash、sop_nodes、opportunity/guidance evidence_json、bridge source_uri/hash）——**JSON 内嵌或列指针，无一等证据实体**（无独立 ID/类型/版本/多实体反链）；证据重提覆写旧指针（F-风险 6） |
| Workbench 证据 | 附录 D ④、F Q1/Q6；submit_gate_evidence L251-256 |
| fde-v2 现状 | 部分实现：KG 导出行带"出处 file_path + 源块 chunk-id"可回查 brd 原文；BR 依赖输入是文本声明；无需求条目级双向矩阵 |
| fde-v2 证据 | knowledge_graph.py:573-599 _origin_cell/_src_cell；附录 A B8 |
| 差距 | WB 缺"一次采集、多处引用、不可变、可审计"的证据实体；fde-v2 的"出处+源块"粒度值得吸收为 evidence 表的 origin 字段设计 |
| 建议动作 | **NEW**（project_evidence 一等表）+ **EXTEND**（4 处现有指针列迁挂 evidence_id，旧数据双写兼容） |
| 目标文件 | NEW（PROPOSED）：server/src/fde_api/evidence/{__init__,models,service,routes}.py；EXTEND：gate_service.py（submit 时建/复用 evidence 行）、guidance/service.py、research subject_service.py |
| 数据模型 | 新增（PROPOSED）project_evidence：id/project_id/kind(gate|task|guidance|research|bridge|workflow)/source_uri/content_sha256/origin(文本出处)/captured_from(auto|human|agent_run_id|job_id)/created_by/created_at；唯一 (project_id, source_uri, content_sha256)。既有 gates.evidence_checklist 项加 evidence_id 可空列 |
| 接口 | 拟新增（PROPOSED）：POST /api/v1/projects/{id}/evidence（去重幂等 by sha256）、GET …/evidence?referenced_by=gates.G5 |
| 安全影响 | 证据仍只存指针+sha256（红线不变）；不落原件；跨项目 evidence 引用被 project_id 复合 FK 拒绝 |
| 实施任务 | T-E1~T-E3（backlog）——**T-E1/T-E2 已实施 2026-11-02**（`fde_api/evidence/` + 迁移 `e1f3a5c7b9d2` + 门禁清单项挂接），T-E3 待办 |
| 测试与验收 | 同 sha256 重复提交幂等；删除/替换 evidence 不改 gates 历史决策行（operation_events 仍完整）；bridge 投影写入走 evidence 去重 |
| 优先级 | **P0** |
| 依赖 | 无（最底层） |
| 可信度 | 现状 VERIFIED；方案 PROPOSED |

### 域 4：业务流程与状态机

| 字段 | 内容 |
|---|---|
| Workbench 现状 | 已实现：gates 5 态+decision、form revision draft→confirmed/archived、guidance draft→confirmed→superseded、template draft→published/inactive、sop_nodes（node_key/gate_key） |
| Workbench 证据 | 附录 F Q1、D ④⑦；gate_service.py:313-518 |
| fde-v2 现状 | 部分实现：状态机写在详设 md（PERM+状态机章节）为规范文本，运行时无流程引擎；schema 无状态约束生成 |
| fde-v2 证据 | 应用设计.md:271-330；附录 A A2 |
| 差距 | WB 已是强项；缺口是**任务级证据与门禁清单脱钩**（ProjectTask.gate 仅字符串、不回填 gates.evidence_checklist，F-风险 5） |
| 建议动作 | **REUSE** + **EXTEND**（任务完成→自动生成 gate 证据**候选**记录，人工在门禁页采纳；绝不自动 accepted） |
| 目标文件 | EXTEND：server/src/fde_api/projects/task_service.py、gate_service.py（新增 attach_task_evidence_candidate） |
| 数据模型 | gates.evidence_checklist 项扩 {label, claim_status, source_uri, content_hash, evidence_id, suggested_by(task_id|workflow_node_run_id)}；不新建表（用域 3 evidence） |
| 接口 | 已有 evidence/decision 路由；拟新增（PROPOSED）POST …/gates/{G}/evidence-candidates/{item}/adopt |
| 安全影响 | 采纳动作仍走 submit_gate_evidence 同一闸（can_manage+人类会话）；AI/工作流只能写候选 |
| 实施任务 | T-G1（backlog） |
| 测试与验收 | agent run 产物可转为候选并出现在门禁页；claim_status 仍需人工 accepted；decide 五道闸不回归 |
| 优先级 | P2（先修 P0 死锁） |
| 依赖 | 域 3 |
| 可信度 | 现状 VERIFIED；方案 PROPOSED |

### 域 5：Workflow DAG

| 字段 | 内容 |
|---|---|
| Workbench 现状 | 缺失：background_jobs 是 (job_type,target_id) 单原子；outbox 串链仅 file.preview 一例；无节点图/I-O 契约/节点重试/取消 |
| Workbench 证据 | jobs/models.py:66-101、generator.py:268-272；附录 C 13、F Q10 |
| fde-v2 现状 | 部分实现：flow.py YAML 三类节点（agent/call/skill）、when/until/max_loop、同层线程池并行、进度落 flow_runs(+history)；**无环检测（环致静默 done）、无节点重试/恢复/取消/幂等、call 节点越权失败不中止、绕过 HITL** |
| fde-v2 证据 | flow.py:127-166/590-657；附录 B 2-6 |
| 差距 | fde-v2 证明"声明式 YAML DAG"形态可行，但其执行器在可靠性五件套（环检测/重试/恢复/取消/幂等）上全部缺位且有两处安全取舍（绕 HITL、静默 done）——**实现不可搬运，形态与教训可搬运** |
| 建议动作 | **NEW**（workflow 三表 + 验证器 + 编排 handler）+ **REUSE**（background_jobs/outbox/worker/handlers 注册制/lease/reconcile——不建第二套队列） |
| 目标文件 | NEW（PROPOSED）：server/src/fde_api/workflows/{__init__,models,definition_service,executor,handlers,routes}.py；EXTEND：jobs/handlers.py 注册 workflow.run、jobs/reconcile.py RECOVERABLE 白名单 |
| 数据模型 | 新增（PROPOSED）：workflow_definitions(id/project_id 可空·模板级、name、dag_json、status draft/published/archived、version、content_sha256)、workflow_runs(id/definition_id+definition_version 固定、status queued/running/waiting_approval/paused/succeeded/failed/cancelled、idempotency_key 唯一、initiated_by)、workflow_node_runs(id/run_id/node_key、status pending/running/succeeded/failed/skipped/waiting、attempt、input_snapshot、output_json、idempotency_key、error) |
| 接口 | 拟新增（PROPOSED）：POST /api/v1/projects/{id}/workflows（定义）、POST …/workflows/{wid}/runs、POST …/workflow-runs/{rid}/cancel、GET …/workflow-runs/{rid} |
| 安全影响 | 节点执行全部走既有鉴权：call 节点=api_execute 同闸（capability+project scope）、agent 节点=agents.start_run 同闸、human_approval 节点=automation_approvals 同闸；外副作用节点默认不可恢复重投（沿用 RECOVERABLE 白名单哲学） |
| 实施任务 | T-W1~T-W6（backlog） |
| 测试与验收 | 环检测拒绝；未知节点/依赖/schema 拒绝；节点失败重试 n 次后暂停可恢复；幂等键阻止重复副作用；已完成节点恢复时跳过；运行固定 definition_version |
| 优先级 | **P1** |
| 依赖 | 域 14（jobs 骨架已在）、域 10（审批复用） |
| 可信度 | 现状 VERIFIED；方案 PROPOSED |

### 域 6：多 Agent 编排

| 字段 | 内容 |
|---|---|
| Workbench 现状 | 部分实现：编排主体=外部 DSH（AI Server）；WB 侧单 agent 沙箱 run + L0-L3 降级链 + handoff（L3 转人工）+ automation（DSH 执行+审批回调）；WB 自身无多 Agent 团队语义 |
| Workbench 证据 | 附录 C 6/14、F 链 7 |
| fde-v2 现状 | 已实现：AgentScope TeamCreate/AgentCreate/TeamSay（角色模板注入）、InMemoryMessageBus、flow 跨角色节点（psc 产销协同 5 节点链真实用例） |
| fde-v2 证据 | agent_service.py:589-597；_flow_forecast_to_plan.yaml；附录 B 9 |
| 差距 | fde-v2 的多 Agent 是**进程内 agentscope 团队**（X-User-ID 租户、无鉴权内网）；WB 的 DSH 是外部黑盒编排。把 agentscope 团队搬进 WB=引入第二套运行时与新的信任面，收益不明 |
| 建议动作 | **DEFER**（P3 再评估；在 workflow 的 agent 节点内允许 DSH 内部自行多步，WB 只约束工具面与预算） |
| 目标文件 | 无（记录决策） |
| 数据模型 | 无 |
| 接口 | 无 |
| 安全影响 | 避免新增内网无鉴权服务面（fde-v2 R9 教训） |
| 实施任务 | 无（观测项：agent_runs.fallback_level 分布） |
| 测试与验收 | — |
| 优先级 | P3 |
| 依赖 | 域 5 落地并积累运行数据 |
| 可信度 | VERIFIED（现状与差距） |

### 域 7：Agent Role 与 ToolGroup

| 字段 | 内容 |
|---|---|
| Workbench 现状 | 部分实现：capability 五档+约 30 capability 最低档位表；agent_registry.allowed_tools 声明；run 工具面=声明∖deny∩发起人∩插件（**只收窄不扩大**）；无"角色预设/工具组"一等概念 |
| Workbench 证据 | control/access.py:14-65、agents/tools.py:84-106；附录 C 4 |
| fde-v2 现状 | 已实现：_roles.py 角色文件（exec 装配）+ 两层过滤中间件 + 工具面预算（≤25/组、≤15/角色）+ 角色标记注入 system prompt |
| fde-v2 证据 | agent_roles.py:43-75/312-329、agent_tool_filter.py:37-63；附录 B 7 |
| 差距 | WB 每个 agent 手写 allowed_tools 无预设复用；fde-v2 的"角色=预打包工具集"思想可吸收，但 exec 装配/文件级角色不可搬 |
| 建议动作 | **EXTEND**（agent_tool_groups 只读目录表：组名→工具名集合，仅为 allowed_tools 的**子集收缩器**；永不扩大用户授权） |
| 目标文件 | EXTEND（PROPOSED）：agents/models.py、agents/tools.py（resolve_allowed_tools 支持 `group:<name>` 引用并求交集）、control/access.py 不动 |
| 数据模型 | 新增（PROPOSED）agent_tool_groups(name 唯一、tools json、description、is_active)——种子随代码发布（非用户可写），或复用 seeds/*.json 模式 |
| 接口 | 拟新增（PROPOSED）：GET /api/v1/agents/tool-groups（admin/lead 只读） |
| 安全影响 | 组只能收窄（resolve 时求交集，代码注释与测试锁定"组不放宽"）；组变更只影响新 run（沿用 V12 收紧语义） |
| 实施任务 | T-R1（backlog） |
| 测试与验收 | 组∪用户∩插件仍不超发起人档位；撤销插件后新 run 工具面收紧；组引用不存在的工具在定义时校验拒绝 |
| 优先级 | P1 |
| 依赖 | 无 |
| 可信度 | 现状 VERIFIED；方案 PROPOSED |

### 域 8：Skill 生命周期

| 字段 | 内容 |
|---|---|
| Workbench 现状 | 部分实现：skill_definitions+skill_versions（content_sha256 唯一、**版本不可变**、current_version_number）、status 仅 active/disabled、种子升级制（管理员编辑不覆写）；无 review/published 态、无发布前测试报告、无回滚、manifest 无 I/O schema 校验 |
| Workbench 证据 | control/models.py:198-239、extensions_service.py:223-253；附录 C 9 |
| fde-v2 现状 | 部分实现：draft→approved→deprecated + 人工审批闸（run 只认 approved）；version 计数器**原地改写非不可变**、无发布前测试、无回滚、无 I/O schema |
| fde-v2 证据 | skills.py:28-48/176-253/346-361；附录 B 12-13 |
| 差距 | 两者互补：WB 有不可变版本链（fde-v2 没有），fde-v2 有 review/approve 治理态（WB 没有）。**以 WB 表为底座扩展治理态**，不新建一套 |
| 建议动作 | **EXTEND**（skill_definitions.status 扩 draft/in_review/published/deprecated；发布闸=校验 I/O schema+可选测试报告；回滚=set current_version_number 到历史版本行） |
| 目标文件 | EXTEND（PROPOSED）：control/models.py、control/extensions_service.py（publish_skill_version/rollback_skill_version）、control/builtin_skills.py（种子状态 published） |
| 数据模型 | 改表（PROPOSED）：skill_definitions.status 枚举扩展+published_by/published_at；skill_versions 加 input_schema/output_schema（json，可空）+test_report_json（可空）+reviewed_by |
| 接口 | 拟新增（PROPOSED）：POST /api/v1/extensions/skills/{id}/versions/{n}/publish（admin+密码确认）、POST …/rollback、GET …/versions |
| 安全影响 | run 面（mcp_gateway._skills）只回 published 且版本固定为 current；回滚留 operation_events |
| 实施任务 | T-S1~T-S2（backlog） |
| 测试与验收 | draft/in_review 不可被 skill_read 消费；发布后内容不可变（同 sha256 只改元数据沿用）；回滚后 run 读到旧版且留痕 |
| 优先级 | P1 |
| 依赖 | 无 |
| 可信度 | 现状 VERIFIED；方案 PROPOSED |

### 域 9：MCP 与 API 工具调用

| 字段 | 内容 |
|---|---|
| Workbench 现状 | 已实现：MCP TOOLS 17（readOnlyHint 动态推导、写类 2）、api_catalog ENTRIES 94（write 派生、confirmation 规则）、15 分钟只衰减 JWT+实时重载用户、api_execute 双闸+敏感确认、直连降级面只 READ_ONLY 13 |
| Workbench 证据 | 附录 C 1-3/6、D 链 7 |
| fde-v2 现状 | 已实现（形态不同）：introspect 反射全量公共服务为工具（约 180+）、三面共桥（Web/MCP/Agent）同授权口径、MCP HTTP Bearer sha256；缺陷：stdio 缺省全通、/api/mcp/tools 全量未过滤、platform_read_app_doc 无应用过滤 |
| fde-v2 证据 | 附录 B 15、E 风险 R1'/R11'、五-3' |
| 差距 | WB 工具面小而受控（17+94） vs fde-v2 大而全量；WB 缺结构化 external_side_effect/risk 元数据（现为注释级，C-2） |
| 建议动作 | **REUSE**（WB 架构）+ **EXTEND**（TOOLS/api_catalog 条目加结构化 effect: read|write_db|external、risk: 0-4 列，与 automation_approvals.risk 对齐） |
| 目标文件 | EXTEND（PROPOSED）：control/mcp_gateway.py（TOOLS 元组扩字段）、control/api_catalog.py（ENTRY 加 effect/risk） |
| 数据模型 | 无新表（代码内目录为主）；automation_approvals.risk_level 语义对齐 |
| 接口 | tools/list annotations 已有；扩 destructiveHint↔external 两个 hint |
| 安全影响 | external 类工具一律进确认流/审批流；目录与审批 risk 口径一致后可做"risk≥3 必须 human_approval"工作流规则 |
| 实施任务 | T-R2（backlog） |
| 测试与验收 | 目录扫描断言每条目有 effect/risk；file_send_wechat/automation 类标 external；写类不进直连面（既有测试不回归） |
| 优先级 | P1 |
| 依赖 | 无 |
| 可信度 | 现状 VERIFIED；方案 PROPOSED |

### 域 10：权限与审批

| 字段 | 内容 |
|---|---|
| Workbench 现状 | 已实现（整体强）：实时鉴权、审批 (run_id,request_key)+sha256+15min+一次性+执行前复查+硬白名单、密码确认（auth_version+指纹陈旧）、agent 天花板=发起人。审计发现 3 处缺陷：①signoff 死锁（agent_assisted 方案 completed 无 handoff 则永远导不出 SOW）②signoff 权限口径=AI 档位而非项目角色（viewer+高 AI 档可拍板）③审批过期懒翻转无清扫（无越权窗口，卫生问题） |
| Workbench 证据 | F 风险 1/9、C 5/R3 |
| fde-v2 现状 | 部分实现且有高危洞：管理守卫返回值丢弃（R1 任意登录用户可审批 skill）、SSRF（R2）、run_as_user 伪造（R3）、无 CSRF（R4）、admin/admin 复活（R5） |
| fde-v2 证据 | 附录 E 五 |
| 差距 | 权限架构 WB 全面占优；fde-v2 的教训（守卫必须 return、管理操作统一收口）反证 WB "唯一写路径"设计的正确性 |
| 建议动作 | **REUSE** + **EXTEND**（修缺陷 ①②③：①generate-agent completed 时自动建 signoff checkpoint（或 export 前兜底创建+提示）；②resolve_signoff 权限改 can_manage+档位双闸；③scheduler 每轮懒清扫过期审批） |
| 目标文件 | EXTEND：solutions/service.py（resolve_signoff 双闸）、agents/service.py（_finalize 成功路径建 checkpoint）、control/scheduler.py（过期清扫）、control/service.py |
| 数据模型 | 无新表；automation_approvals 状态机不变 |
| 接口 | 已有；行为修正 |
| 安全影响 | 修复后：agent_assisted 全路径必有 pending signoff 可拍；拍板人必须是项目管理者 |
| 实施任务 | T-P0-1（死锁，**P0**）、T-P1-4/5（口径+清扫） |
| 测试与验收 | 死锁：generate-agent completed→export 409→signoff 可拍→export 通过（端到端）；权限：viewer+system_operator 拍板被 403 |
| 优先级 | **P0**（死锁）/ P1（其余） |
| 依赖 | 无 |
| 可信度 | VERIFIED |

### 域 11：测试与质量门禁

| 字段 | 内容 |
|---|---|
| Workbench 现状 | 已实现：pytest 1706 收集（本轮实跑见 test-inventory）、vitest 730、CI 4 job（desktop/server-tests/gitleaks/pseudonymization）、迁移测试 test_migrations、变异测试方法论（d11 沉淀） |
| Workbench 证据 | 基线文档 §5；server/tests 166 文件 |
| fde-v2 现状 | 部分实现：verify 脚本四层 + 变异自检（短路校验使 TC 变红）+ known-issues 基线管理；无 CI、oracle psc 专属、view 层需活环境 |
| fde-v2 证据 | 附录 A A4、E 11 |
| 差距 | WB 缺"发布物质量门禁"（skill 发布前测试、workflow 定义校验入 CI）；fde-v2 的 known-issues 基线法可借鉴到 WB 审计遗留项管理 |
| 建议动作 | **REUSE** + **EXTEND**（新增域 2/5/8 的测试族；workflow DAG 校验做成纯函数直接进 CI） |
| 目标文件 | NEW（PROPOSED）：server/tests/test_workflow_definition.py、test_ontology_registry.py、test_skill_lifecycle.py、test_evidence_registry.py |
| 数据模型 | 无 |
| 接口 | 无 |
| 安全影响 | 测试覆盖即门禁（发布闸依赖测试报告字段） |
| 实施任务 | 各域任务内含；T-T1 汇总（backlog） |
| 测试与验收 | 新域用例全绿且入 CI server-tests job |
| 优先级 | P0（随域 2/3）、P1（随域 5/7/8） |
| 依赖 | 对应域实现 |
| 可信度 | 现状 VERIFIED；扩展 PROPOSED |

### 域 12：交付文档生成

| 字段 | 内容 |
|---|---|
| Workbench 现状 | 已实现：四表模型（身份/不可变版本/草稿/任务）、worker 异步渲染、build_document_snapshot 冻结输入、首代 AI 字段冻结、重试不覆盖、交付审计幂等；血缘断点：confirmed_research_values 不存 revision_id、ai_call_audits request_id 不落版本行、门禁证据不入快照 |
| Workbench 证据 | 附录 F Q6-Q8、风险 3/4 |
| fde-v2 现状 | 缺失（无交付文档生成；_contracts.md 为 API 契约文档） |
| 差距 | 无可搬运实现；仅吸收"契约冻结"思想（已有） |
| 建议动作 | **REUSE** + **EXTEND**（血缘补洞三件：快照存 revision_id、request_id 双向落点、门禁状态入快照） |
| 目标文件 | EXTEND：documents/snapshots.py（confirmed_research_values 加 revision_id）、documents/ai_content.py（request_id 写回 generation job）、generator.py（快照含 gates 摘要） |
| 数据模型 | 无新表；content/source_snapshot_json 结构扩展（向后兼容键） |
| 接口 | 已有 |
| 安全影响 | 无 |
| 实施任务 | T-D1（backlog） |
| 测试与验收 | 生成后可从版本行反查 ai_call_audits 与 research revision；旧快照无新键不报错 |
| 优先级 | P2 |
| 依赖 | 无 |
| 可信度 | 现状 VERIFIED；方案 PROPOSED |

### 域 13：数据库迁移和版本

| 字段 | 内容 |
|---|---|
| Workbench 现状 | 已实现：Alembic 22 revision 单链（root ebb003a5c3a8→head c3e7a9b1d5f4）、CI 环境解耦、test_migrations 升降级测试 |
| fde-v2 现状 | 缺失：无迁移系统（CREATE IF NOT EXISTS + reconcile 只补列 + 内联 ALTER try/except）；PG 失败静默回退 SQLite；audit 列注入在 DDL 层 |
| 差距 | fde-v2 的 AST 审计列注入对 WB 无意义（WB 用 ORM+迁移）；**明确不引入**其"运行时改库"机制（与 WB 迁移纪律冲突） |
| 建议动作 | **REUSE**（WB）；新增表全部走 Alembic 单链推进 |
| 目标文件 | server/migrations/versions/（新 revision 逐项交付） |
| 数据模型 | 域 2/3/5/7/8 各自迁移 |
| 接口 | — |
| 安全影响 | 迁移前快照备份纪律沿用 README |
| 实施任务 | 各域任务内含 |
| 测试与验收 | test_migrations 升降级覆盖新表；发布列车核对 head |
| 优先级 | 随域 |
| 依赖 | — |
| 可信度 | VERIFIED |

### 域 14：异步任务、重试与恢复

| 字段 | 内容 |
|---|---|
| Workbench 现状 | 部分实现：outbox→Redis list→background_jobs（active_key 单活跃、lease 5min+续租、token 守卫、reconcile 白名单 8 类+failure handler 收尾、心跳）；缺口：handler 异常无自动重试（max_attempts 只在 reconcile 生效）、无取消 API、outbox completed/failed 无写入点（状态不闭环） |
| Workbench 证据 | 附录 C 11、F Q10/风险 7/10 |
| fde-v2 现状 | 弱：APScheduler 单进程（无分布式锁，多副本重复触发）、无重试/幂等/取消 |
| 差距 | WB 骨架显著占优；需补三件：可重试 handler 语义（指数退避≤max_attempts）、outbox 状态闭环（dispatch 成功后 handler 侧回写）、workflow 节点级恢复（域 5） |
| 建议动作 | **REUSE** + **EXTEND**（三件补齐；workflow 作为新 job_type 接入既有注册制——**不建第二套队列**） |
| 目标文件 | EXTEND：jobs/worker.py（重试策略）、jobs/outbox.py（mark_completed/mark_failed）、jobs/models.py（状态迁移约束）、jobs/handlers.py（注册 workflow.run） |
| 数据模型 | outbox_events 状态机补 completed/failed 写入点（无 schema 变更，代码补） |
| 接口 | 拟新增（PROPOSED）：POST /api/v1/admin/jobs/{id}/cancel（admin，幂等；RECOVERABLE 语义外的不强杀） |
| 安全影响 | 取消走 admin+operation_events 留痕；外副作用 job 取消=只阻止未执行部分 |
| 实施任务 | T-J1~T-J2（backlog） |
| 测试与验收 | handler 抛错→attempts<max 自动退避重试；outbox 终态可查；取消后 job 不再被 reconcile 重排 |
| 优先级 | P1 |
| 依赖 | 无（域 5 依赖它） |
| 可信度 | 现状 VERIFIED；方案 PROPOSED |

### 域 15：可观测性、审计和成本

| 字段 | 内容 |
|---|---|
| Workbench 现状 | 部分实现：operation_events（业务变更）、ai_call_audits（tokens/status/budget_blocked/月度汇总）、agent 成本三层（平台月预算/run 熔断/seat ledger）、心跳；缺口：DSH 降级直连 chat 不落 ai_call_audits（预算失真 C-R4）、outbox 不闭环（域 14）、无统一 trace id 贯穿 |
| Workbench 证据 | 附录 C 8/R4 |
| fde-v2 现状 | 弱：无操作审计表（数据级 4 审计列除外）、LLM 无成本记录、call_logs 入参截断明文、密钥可能入 Cookie/日志 |
| 差距 | WB 占优；fde-v2 教训=入参明文落库要脱敏（WB 的 redaction/csanitization 已有对应物） |
| 建议动作 | **EXTEND**（降级路径统一走 auditing.record：request_id 前缀 direct-chat-*；月度预算口径修正） |
| 目标文件 | EXTEND：ai/ai_server_client.py、control/ai_tool_loop.py（写入点）、ai/auditing.py（无改动复用） |
| 数据模型 | 无新表 |
| 接口 | — |
| 安全影响 | 审计 fail-open 语义保持（R7 已记录为显式取舍） |
| 实施任务 | T-OBS1（backlog） |
| 测试与验收 | 降级 chat 完成后 ai_call_audits 有行；tokens_used_this_month 计入该路径 |
| 优先级 | P1 |
| 依赖 | 无 |
| 可信度 | 现状 VERIFIED；方案 PROPOSED |

### 域 16：前端与桌面端交互

| 字段 | 内容 |
|---|---|
| Workbench 现状 | 已实现：Electron+Vite+React、api/client 会话刷新、契约测试（test_frontend_enum_contract）、730 vitest、内嵌帮助 |
| fde-v2 现状 | 部分实现：无构建 Alpine.js+扫描发现、隐式页面授权（X-Fde-Page 派生服务放行——**WB 不可采用**，等于前端声明权限）、无桌面端 |
| 差距 | fde-v2 无可搬运前端；其"页面→服务边静态扫描"只在其隐式授权模型下有意义 |
| 建议动作 | **REUSE** + **EXTEND**（新增：工作流控制台页、本体术语页、Skill 版本管理页——均挂既有 api client 模式） |
| 目标文件 | NEW（PROPOSED）：desktop/src/renderer/src/workflows/WorkflowConsole.tsx、ontology/GlossaryPage.tsx、extensions/SkillVersionsPage.tsx |
| 数据模型 | 无 |
| 接口 | 消费域 2/5/8 新接口 |
| 安全影响 | 页面仅呈现；写操作走既有 require_auth+服务层闸 |
| 实施任务 | T-UI1（backlog，P2） |
| 测试与验收 | vitest 组件用例+枚举契约测试 |
| 优先级 | P2 |
| 依赖 | 域 2/5/8 接口 |
| 可信度 | 现状 VERIFIED；方案 PROPOSED |

### 域 17：部署和运维

| 字段 | 内容 |
|---|---|
| Workbench 现状 | 已实现：compose 四服务（api/scheduler/worker/redis）+pg、healthcheck、心跳、CI 4 job、镜像内代码（改后 rebuild+alembic 纪律）、打包便携版+asar 字节验证 |
| fde-v2 现状 | 部分实现：五服务 compose、nginx TLS；root 运行、.dockerignore 漏密钥、无 HSTS、PG 口令硬编码 |
| 差距 | fde-v2 部署面多项不达标，**不搬运**；唯一可借鉴：nginx SSE 配置经验（WB 不经 nginx，无关） |
| 建议动作 | **REUSE**（WB 部署不动，新表走迁移） |
| 目标文件 | docker-compose.yml 仅在新增服务时评估（本轮零新增服务） |
| 数据模型 | — |
| 接口 | — |
| 安全影响 | 保持密钥不入镜像（WB 已达标） |
| 实施任务 | 无 |
| 测试与验收 | 既有 CI 全绿 |
| 优先级 | — |
| 依赖 | — |
| 可信度 | VERIFIED |

---

## 审计中发现的 Workbench 自身缺陷清单（与差距矩阵正交，先行修复）

| 编号 | 严重度 | 缺陷 | 证据 | 处置 |
|---|---|---|---|---|
| WB-DEF-1 | 高（功能阻断） | signoff 死锁：agent_assisted 方案正常 completed 无 handoff → 无 pending checkpoint → signoff 409 / export 409 永久卡死 | F 风险 1；agents/service.py:907-916 唯一创建点 | T-P0-1（P0）**已实施 2026-11-02**（`agents/signoff.py` 统一开闸 + `_finalize` 即开 + export 兜底） |
| WB-DEF-2 | 中（权限口径） | resolve_signoff 项目侧仅 can_view，拍板权=AI 档位，viewer+高 AI 档可拍板 | F 风险 9 | T-P1-4 |
| WB-DEF-3 | 低（卫生） | 过期审批懒翻转无后台清扫 | C R3 | T-P1-5 |
| WB-DEF-4 | 中（观测失真） | DSH 降级直连 chat 不落 ai_call_audits，月预算失真 | C R4 | T-OBS1 |
| WB-DEF-5 | 低（信息不呈现） | gates.template_hash 漂移（存量 f52afe88 vs 现 180c4809）无比对呈现 | F 风险 2 | T-G2 |
| WB-DEF-6 | 中（审计断链） | ai_call_audits request_id 不落文档版本行 | F 风险 3 | T-D1 |
| WB-DEF-7 | 低（数据口径） | confirmed_research_values 不存 revision_id | F 风险 4 | T-D1 |
| WB-DEF-8 | 低（双口径） | ProjectTask.gate 证据与 gates 清单脱钩 | F 风险 5 | T-G1 |
| WB-DEF-9 | 低（状态机） | outbox completed/failed 无写入点 | F 风险 7 | T-J1 |
| WB-DEF-10 | 低（确认面） | api_catalog 中 export_sow/documents.generate 未列 confirmation（AI 可无确认触发生成） | F 风险 8 | T-R2 一并处理 |
