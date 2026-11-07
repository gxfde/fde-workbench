# 蔡工 FDE Workbench V3.1 智能交付自动化升级路线图与 Goal 实施任务书

-   **基线仓库：** https://github.com/caishide/fde-workbench
-   **已检查基线提交：**
    `73680946f4ef020aab39eb16cc093f3e5284e22b`（2026-11-07）
-   **执行工具：** ZCode（Codex 可接续）
-   **目标：** 以真实代码为准，分阶段将现有
    Agent、Workflow、Ontology、Gate、访谈和项目任务能力串成可审计的 FDE
    交付闭环。

> 重要边界：本任务书依据此前对指定提交和若干核心路径的检查，不代表全仓逐行审计，也不代表本轮重新运行过测试。开工第一步必须核对当前
> HEAD、文件结构、模型、路由、迁移和测试。文中接口及表结构是目标设计，不得未经核验直接照搬。

------------------------------------------------------------------------

## 1. 总体决策

### 1.1 V3.1 目标闭环

**客户资料/访谈 → 转写 → 事实与需求抽取 → 人工确认 → 本体候选 → Change
Set 审批 → 交付方案 → Workflow 草稿 → 人工发布 → 任务/Agent 执行 →
自动测试 → 证据汇总 → Gate 审核 → 交付验收 → 经验沉淀。**

### 1.2 设计原则

1.  确定性 Workflow 是骨架和状态机；Agent
    只做受限的理解、判断、归纳和生成。
2.  数据库是事实源；关键事实、需求、规则和验收标准必须有来源指针。
3.  AI 生成内容先进入草稿/审核区，不直接写正式业务事实或本体。
4.  Workflow 负责执行证据，`projects/gate_service.py`
    负责门禁决策；Agent 不能自行宣布 G1--G9 通过。
5.  对外发送、生产环境变更、删除覆盖、签约付款等高风险动作必须人工批准。
6.  ZCode 执行器必须与模型层解耦；纯 CLI 契约不等于宿主 CLI 已接通。
7.  先做一个脱敏制造业项目的纵向切片，再抽象成平台能力。
8.  不以 Agent 数量为
    KPI，以节省工时、返工率、产物接受率、流程完成率和证据完整性衡量。

### 1.3 明确不做

-   不推倒重写现有 Agent、Workflow、Ontology、Gate、项目/任务体系。
-   不整体复制其他开源项目，不建立第二套任务系统、状态机或门禁。
-   不在核验现有能力前新增平行表、路由或服务。
-   不让 Agent 自动审批需求、本体、Workflow 发布或 G1--G9。
-   未完成商用条款、安全代理和真实联调前，不得声称 ZCode 已接通。
-   不引入不必要的付费模型或 SaaS，优先复用现有 AI
    Server、模型配置、Skill 和工具体系。

------------------------------------------------------------------------

## 2. 当前代码基线与核验范围

此前检查所见的主要路径：

  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  能力                    代码位置                                                                                                    V3.1 策略
  ----------------------- ----------------------------------------------------------------------------------------------------------- ------------------------------------
  访谈草稿/纪要           `server/src/fde_api/transcripts/service.py`、`models.py`、`routes.py`                                       扩展结构化抽取和来源审核

  访谈前端                `desktop/src/renderer/src/transcripts/TranscriptDraftsPanel.tsx`                                            增加事实/需求审核

  Agent                   `server/src/fde_api/agents/service.py`、`adapter.py`、`context.py`、`tools.py`、`models.py`、`receipt.py`   扩展受控交付执行

  Agent 前端              `desktop/src/renderer/src/AgentsConsole.tsx`                                                                运行、授权、产物、审核和失败可视化

  ZCode 契约              `server/src/fde_api/agents/zcode_contract.py`                                                               当前是 CLI
                                                                                                                                      参数/结果契约层，需补宿主代理边界

  Workflow                `server/src/fde_api/workflows/definition_service.py`、`executor.py`、`models.py`、`routes.py`               复用 DAG 执行器

  Ontology                `server/src/fde_api/ontology/models.py`、`service.py`、`routes.py`                                          补来源关系和稳定 ID 关联

  Gate                    `server/src/fde_api/projects/gate_service.py`                                                               保持唯一门禁决策入口

  后台任务                `background_jobs/`、`outbox_events/`、Worker/Scheduler                                                      异步抽取、可靠派发、指标

  旧控制面                `server/src/fde_api/control/ontology.py`、`mcp_gateway.py`、`access.py`、`ai_tool_loop.py`                  核对与新模块职责，防止重复
  ------------------------------------------------------------------------------------------------------------------------------------------------------------------------

此前仓库状态台账曾记录约 107 张业务表、38 个迁移 revision、315
个服务端路由、94 个 API Catalog 条目；测试台账曾记录 pytest 2,116
项（2,110 passed、6 skipped）及桌面端 Vitest 927
项。这些数字是历史台账，不是本轮重新执行结果。此前台账也曾记录
`agent_runs=0`、`workflow_runs=0`，开工时必须重新查库。

### P0-0 必须先完成的代码核验

ZCode 先生成 `docs/v3.1/00-baseline-audit.md`，不得先改业务代码：

1.  `git status`、当前分支、HEAD SHA、未提交修改。
2.  本任务书列出的文件是否存在，实际类、函数、路由和测试路径。
3.  相关 ORM 模型、表、索引、外键、枚举、Alembic revision。
4.  API Catalog 与实际路由差异。
5.  Agent、Workflow、Ontology、Gate 的状态机和事件调用链。
6.  `control/ontology.py` 与 `ontology/` 的职责重叠。
7.  当前 Agent/Workflow
    运行数量、失败分布、产物接受/撤回数量；无数据库时注明。
8.  按 `AGENTS.md` 运行测试，保存环境、命令、通过/失败/跳过数量。
9.  检查 `zcode_contract.py` 是否只是纯函数；不得假定有 spawn/宿主代理。
10. 每项改造标记为复用、扩展、新建或暂缓，并解释原因。

交付：`00-baseline-audit.md`、`00-data-model-map.md`、`00-test-baseline.md`、`00-gap-register.md`。未完成核验，不得新增表或批量改代码。

------------------------------------------------------------------------

## 3. 目标架构和数据流

``` text
访谈/文件/客户资料
      |
资料接入、脱敏、转写/解析
      |
事实与需求抽取 Agent
      |---- 来源定位：时间戳、段落、页码、文件指针、SHA256
      v
事实/需求审核队列 --人工确认-->
      |
本体候选 --Change Set 审批-->
      |
正式 Ontology / 领域对象
      |
交付方案生成 Agent --人工审核-->
      |
Workflow Draft Generator --人工发布-->
      |
现有 Workflow Executor
  call / skill / agent / human_approval
      |
任务执行、ZCode（安全批准后）、产物
      |
自动测试、证据校验
      |
Gate Service --授权人员批准-->
      |
验收、指标、Skill 改进草稿
```

关键关系： - Fact/Requirement 必须能回溯原始 source。 - Ontology
Candidate 必须引用已确认事实/需求。 - Delivery Plan
条目必须映射需求、领域对象、风险、任务或验收标准。 - Workflow Node/Run
必须关联项目、方案条目、任务和证据。 - Gate
证据由执行记录、测试结果和人工审核组成。 - 大文件只保存文件指针和
SHA256，不把音视频/Base64 放入业务表。

------------------------------------------------------------------------

## 4. 路线图与阶段依赖

  -------------------------------------------------------------------------------------------
  阶段                   优先级                        预计时间 交付
  ---------------------- ---------------- --------------------- -----------------------------
  P0-0 基线审计          P0                             1--2 天 真实代码地图、测试/数据基线

  P0-1                   P0                             3--5 天 来源可追溯的审核闭环
  访谈事实与需求结构化                                          

  P0-2 本体候选与领域 ID P0                             3--5 天 候选→审批→物化

  P0-3                   P0                             3--5 天 方案版本及任务映射
  方案生成与任务分解                                            

  P0-4 Workflow          P0                             3--5 天 模板、校验、人工发布
  模板与草稿生成                                                

  P1-2                   P1                             3--5 天 测试计划、报告、证据
  自动测试与证据评估                                            

  P1-1 ZCode             P1                      5--10 天或更长 安全授权、执行收据、产物
  宿主执行通道                                                  

  P1-3                   P1                             3--5 天 指标、Skill 改进提案
  交付指标与经验沉淀                                            

  P2 真实项目试点        P2                             2--4 周 端到端试点与复盘
  -------------------------------------------------------------------------------------------

周期只是排程估算。顺序不可跳跃；P1-2
可先做测试计划和证据模型，真实自动执行需依赖安全执行器。

------------------------------------------------------------------------

## 5. P0-1：访谈事实与需求结构化

### 目标

把现有转写草稿转成可审核的事实、需求、角色、流程、系统、痛点、规则、约束和待澄清问题。每个事实都必须带来源定位。

### 先检查并优先扩展

-   `transcripts/service.py`
-   `transcripts/models.py`
-   `transcripts/routes.py`
-   `agents/service.py`
-   `agents/context.py`
-   `agents/tools.py`
-   现有文件指针、Agent Artifact 和审计机制。

### 目标数据模型（不是未经核验就照搬的建表命令）

若现有模型无法承载，再考虑：

**`discovery_extractions`** - `id`, `project_id`, `source_type`,
`source_id/source_ref` -
`status`（queued/running/review_required/accepted/rejected/failed） -
`agent_run_id`, `prompt_version`, `model_profile_id` - `created_by`,
`created_at`, `completed_at`, `error_code`

**`business_facts`** - `id`, `project_id`, `extraction_id` -
`fact_type`（process/role/system/rule/data_object/metric/constraint/pain_point/decision） -
`subject`, `predicate`, `object_value` - `confidence`, `source_ref`,
`source_locator` -
`review_status`（pending/accepted/rejected/needs_clarification） -
`reviewed_by`, `reviewed_at`, `review_comment`

**`requirements`** - `id`, `project_id`, `requirement_key`, `title`,
`description` -
`requirement_type`（functional/non_functional/data/integration/security/operational） -
`priority`, `acceptance_criteria`, `status` - `approved_by`,
`approved_at`, `created_at`, `updated_at`

**`requirement_sources`** - `id`, `requirement_id`, `fact_id`,
`source_ref`, `source_locator` - 唯一约束，防止重复关联。

若已有通用需求/发现模型，扩展它们；不要为了遵循表名而重复建表。`source_fact_ids`
长期应使用关系表，而不是 JSON ID 数组。

### API 目标语义（先与现有路由对照）

-   `POST /api/projects/{project_id}/discovery/extractions`
-   `GET /api/projects/{project_id}/discovery/extractions`
-   `GET /api/discovery/extractions/{id}`
-   `POST /api/discovery/extractions/{id}/run`
-   `GET /api/projects/{project_id}/business-facts`
-   `PATCH /api/business-facts/{id}/review`
-   `GET /api/projects/{project_id}/requirements`
-   `PATCH /api/requirements/{id}/review`

如果现有 API 已覆盖，复用并补字段、权限、审计和 API
Catalog，不得增加同义路由。

### Agent JSON 契约示例

``` json
{
  "facts": [{
    "fact_type": "process",
    "subject": "询盘处理",
    "predicate": "当前步骤",
    "object_value": {"step": "销售人工分配"},
    "confidence": 0.91,
    "source_locator": {
      "type": "transcript_segment",
      "start_ms": 12000,
      "end_ms": 18500
    },
    "needs_clarification": false
  }],
  "requirements": [],
  "roles": [],
  "systems": [],
  "processes": [],
  "business_rules": [],
  "open_questions": []
}
```

约束： - Schema
校验失败、来源定位不存在或越界，整批进入失败/待审核，不得静默部分写入。 -
推断必须标记为 inference，并进入人工审核。 - 无来源事实不得自动接受。 -
同一 source + extractor version + prompt version 重试必须幂等。 -
原始访谈草稿和正式纪要现有审批流程不得被绕过。

### 测试与验收

-   Schema、置信度边界、来源定位、去重、状态机单测。
-   抽取任务→后台执行→结果持久化→审核→需求批准集成测试。
-   跨项目越权、伪造 source_ref、重放请求安全测试。
-   UI 批量审核、澄清、来源跳转、失败恢复测试。
-   验收：关键事实可回看来源；拒绝/澄清不污染正式数据；审核有操作者/时间/理由；重试不重复创建。

------------------------------------------------------------------------

## 6. P0-2：本体候选和领域对象稳定 ID

### 目标

复用 `ontology/models.py`、`service.py`、`routes.py`
中的术语、别名、关系类型和 Change Set。AI
只能创建候选；人工批准后事务性物化。逐步让业务对象通过稳定 `term_id`
或领域对象 ID 关联，而不是依赖名称字符串。

### 核验点

1.  Candidate 是否关联来源事实、需求、项目和定位。
2.  别名冲突检测是否覆盖跨项目范围。
3.  Change Set 是否记录提交人、审批人、理由和版本。
4.  物化是否事务化、幂等、可审计。
5.  合并、停用、重命名是否有影响分析和回滚策略。
6.  评估业务表外键改造，先从一个试点实体开始，不做全库大迁移。
7.  明确旧 `control/ontology.py` 与新 `ontology/` 的职责，先做
    ADR，不直接删除旧模块。

### 目标 API 语义

-   `POST /api/projects/{project_id}/ontology/candidates/generate`
-   `GET /api/projects/{project_id}/ontology/candidates`
-   `PATCH /api/ontology/candidates/{id}/review`
-   `POST /api/ontology/change-sets/{id}/submit`
-   `POST /api/ontology/change-sets/{id}/approve`
-   `POST /api/ontology/change-sets/{id}/materialize`

先复用现有接口。

### 测试/验收

候选重复、别名冲突、非法关系、来源未批准、未批准不得物化、物化幂等、并发审批、事务回滚、外键迁移兼容、审计完整。至少一个试点实体通过稳定
ID 关联，旧数据仍可读取。

------------------------------------------------------------------------

## 7. P0-3：交付方案生成与任务分解

### 目标

从已批准需求、事实和本体生成可审核 Delivery
Plan，并映射到现有项目任务表，不新建平行任务系统。

### 先检查模块

-   `solutions/`
-   `documents/`
-   `projects/` 项目、阶段、任务、依赖服务
-   `agents/context.py`、`agents/service.py`
-   Ontology 查询服务。

### 方案至少包含

目标/范围/非目标、当前与目标流程、业务对象/角色/系统/接口、需求及来源、自动化机会、技术架构、风险/假设/依赖、阶段和任务、负责人角色、任务依赖、Definition
of Done、验收标准和证据要求。工时/报价必须标明估算与假设。

### 数据结构

先查现有方案文档和项目任务模型。确有缺口再新增： -
`delivery_plans`：项目、版本、状态、生成 Agent Run、审核人、批准时间。 -
`delivery_plan_items`：条目类型、标题、说明、优先级、来源需求、领域对象、验收标准、风险。 -
`delivery_plan_task_links`：方案条目与现有 task ID 关联。

任务仍以原有任务表为事实源，不复制任务字段。

### API 目标语义

-   `POST /api/projects/{project_id}/delivery-plans/generate`
-   `GET /api/projects/{project_id}/delivery-plans`
-   `GET /api/delivery-plans/{id}`
-   `PATCH /api/delivery-plans/{id}/review`
-   `POST /api/delivery-plans/{id}/items/{item_id}/create-task`
-   `POST /api/delivery-plans/{id}/publish`

### 约束和验收

-   方案引用已批准需求；未批准项只能标记为待确认假设。
-   创建任务先预览，支持选择性创建，幂等防重复。
-   未确定负责人时分配角色/待认领，不随意指派员工。
-   方案变更生成新版本，不覆盖已批准历史。
-   任务依赖无环、验收标准非空、方案到任务映射可追溯。

------------------------------------------------------------------------

## 8. P0-4：Workflow 模板和自动生成

### 目标

复用现有
`workflows/definition_service.py`、`executor.py`、`models.py`、`routes.py`，由方案生成
Workflow Draft，人工校验并发布。

### 第一批模板

1.  需求发现：访谈导入→转写/解析→事实抽取→审核→需求确认。
2.  方案与实施计划：读取需求/本体→方案生成→审批→任务创建→计划发布。
3.  自动化交付：开发任务→Agent/人工执行→测试→证据汇总→Gate 审核→归档。

### 节点契约字段

`node_type`、`node_key`、版本、输入/输出 JSON
Schema、超时、重试策略、幂等键、权限范围、可用工具、是否需要人工审批、失败分类、补偿动作、项目/方案/需求/任务关联、产物和证据引用。

### 数据扩展

优先扩展现有 Workflow Definition/Node/Run/NodeRun： - 关联
`project_id`、`delivery_plan_id`、`delivery_plan_item_id`。 - 保存模板
ID/版本、Schema 版本、evidence refs、artifact refs、审批记录。
若现有字段已满足，不新增字段。

### API 目标语义

-   `GET /api/workflows/templates`
-   `POST /api/projects/{project_id}/workflows/draft-from-plan`
-   `POST /api/workflows/{id}/validate`
-   `POST /api/workflows/{id}/publish`
-   `POST /api/workflow-runs/{id}/cancel`
-   `POST /api/workflow-runs/{id}/resume`

### Gate 规则

Workflow 只能提交证据；`gate_service.py`
是唯一门禁决策入口。证据必须校验类型、来源、时间、操作者和项目范围。Agent
只能提示证据齐备与否，不得改变 Gate 状态。

### 测试/验收

DAG 环检测、缺依赖、Schema
不匹配、发布后不可变、版本升级、重试/恢复/取消/超时、Outbox
重复投递、审批节点不可绕过、Gate 唯一写入口、失败节点可定位。

------------------------------------------------------------------------

## 9. P1-1：Agent 执行与 ZCode 宿主代理

### 现状判断

`server/src/fde_api/agents/zcode_contract.py` 已有 CLI
参数构造、`--resume` 参数、`--json` 汇总解析和结果到 Agent
事件映射。它不是完整执行器，不能据此宣称已 spawn ZCode 或已接入宿主机。

### 安全前置条件

以下全部通过之前禁止真实项目执行：

1.  ZCode 使用条款/商用权限书面确认。
2.  宿主代理只监听认证的本机/内网通道，不暴露公网任意命令端口。
3.  每次 Run 使用短期授权票据，绑定用户、项目、Run、工作目录和允许动作。
4.  命令/工具白名单，禁止任意 shell 拼接。
5.  工作目录规范化校验，防 `..`、符号链接逃逸。
6.  默认禁止访问密钥、凭据目录和无关项目。
7.  网络默认受限，按域名白名单开放。
8.  超时、取消、进程树回收和资源限额。
9.  stdout/stderr 脱敏，日志不得记录 API Key、Cookie、Token。
10. 产物记录路径指针、SHA256、大小、MIME、时间、Run ID。
11. 文件变更可审计，危险操作二次人工确认。
12. 宿主代理离线时明确失败，回退人工任务，不伪造成功。

### 建议文件（仅在现有 Adapter 无法扩展时新增）

-   `agents/execution_provider.py`：执行 Provider 协议。
-   `agents/zcode_provider.py`：服务端到宿主代理的受限客户端。
-   `agents/host_agent_contract.py`：宿主代理请求/响应 Schema。
-   `agents/execution_policy.py`：权限、路径、命令和超时策略。
-   `agents/execution_receipt.py`：执行收据；若 `receipt.py`
    已覆盖则扩展原文件。
-   宿主代理应作为独立进程/服务，具体位置按仓库部署和 Windows
    环境决定，不得将不可信 CLI 直接塞进 Web API 进程。

### 运行记录字段（优先扩展 Agent Run/Artifact）

Run：`execution_provider`、`host_agent_id`、`authorization_id`、`workspace_ref`、`resume_session_ref`、开始/结束时间、`exit_code`、终止原因、执行状态、策略快照
hash。

Artifact：`path_ref`、`sha256`、`size_bytes`、`mime_type`、`created_by_run_id`、审核状态、审核人和时间。

### API 目标语义

-   `POST /api/agents/runs/{id}/authorize-execution`
-   `POST /api/agents/runs/{id}/start`
-   `POST /api/agents/runs/{id}/resume`
-   `POST /api/agents/runs/{id}/cancel`
-   `GET /api/agents/runs/{id}/execution-receipt`

均需项目权限、显式授权、审计、幂等和撤销能力。

### 测试/验收

未授权/过期授权拒绝；错绑用户/项目/Run
拒绝；路径穿越、符号链接逃逸、命令注入、环境变量泄漏测试；超时/取消回收整个进程树；续接会话受用户/项目/授权约束；非零退出码不得标成功；产物
hash 可复算；宿主离线可人工接管。

分级开放：A 只读探测/模拟；B 脱敏仓库、无外网、无生产凭据；C
人工批准后允许有限文件修改和测试命令；D
小范围真实项目。每级安全评审后才能升级。

------------------------------------------------------------------------

## 10. P1-2：自动测试和交付证据

### 目标

根据已批准需求与任务验收标准生成测试计划，执行允许的测试，保存报告并检查证据完整性。

### 优先复用

Agent Run/Artifact/Receipt、Workflow 节点、项目任务、Gate Evidence
和文件存储。只有不存在可复用质量模块时，才考虑
`server/src/fde_api/quality/`。

### 目标数据概念（先核验）

-   `test_plans`：需求/任务、版本、生成者、审核状态。
-   `test_cases`：前置条件、步骤、预期结果、风险等级、自动化标志。
-   `test_executions`：环境、测试套件、起止时间、结果、日志指针。
-   `evidence_links`：测试执行、产物、需求、任务和 Gate 关联。

### API 目标语义

-   `POST /api/tasks/{id}/test-plans/generate`
-   `GET /api/tasks/{id}/test-plans`
-   `PATCH /api/test-plans/{id}/review`
-   `POST /api/test-plans/{id}/execute`
-   `GET /api/test-executions/{id}`
-   `POST /api/projects/{id}/evidence/validate`

### 约束与验收

每条批准需求至少有测试或明确人工验收方式；测试用例可追溯需求；模型生成用例先审核；生产环境测试默认禁止；失败结果不能被摘要
Agent 改写为成功；报告指针/hash 可验证；Gate
只接收类型和项目范围正确的证据。

------------------------------------------------------------------------

## 11. P1-3：指标和经验沉淀

### 目标

统一采集真实交付事件，分析 Agent/Skill/Workflow 表现；Skill
改进先形成提案，经审核后发布新版本。

### 事件

`agent_run_started/completed/failed/cancelled`、`artifact_created/accepted/rejected/revoked`、`workflow_run_started/completed/failed/cancelled`、`workflow_node_retry`、`requirement_approved/rejected`、`ontology_change_approved/materialized`、`delivery_plan_approved`、`task_rework`、`gate_passed/rejected/blocked`。

事件统一包含项目、主体
ID、Actor、时间、版本、结果、耗时、错误分类和关联对象；不得放客户敏感正文。

### 优先复用

现有审计事件、Outbox、Agent Run、Workflow Run、Artifact
审核记录、Task、Gate 和 Skill 版本。仅在无法聚合时考虑： -
`delivery_metric_daily`：按日期、项目类型、Agent/Skill/Workflow 聚合。 -
`skill_improvement_proposals`：来源样本、建议差异、评估、审核人、目标版本。

### API 目标语义

-   `GET /api/analytics/delivery/overview`
-   `GET /api/analytics/delivery/projects/{id}`
-   `GET /api/analytics/agents/performance`
-   `GET /api/analytics/skills/performance`
-   `POST /api/skills/{id}/improvement-proposals`
-   `PATCH /api/skill-improvement-proposals/{id}/review`

### 指标口径

-   访谈整理耗时、事实来源可追溯率、需求结构化率、本体候选采纳率。
-   方案转任务率、Workflow 完成率、Agent
    产物接受率、自动测试首次通过率。
-   返工率、人工介入次数、项目节省工时。
-   样本不足显示"数据不足"；重试不重复计数；Skill
    已发布版本不可原地修改；跨客户学习必须脱敏和隔离。

------------------------------------------------------------------------

## 12. 数据库/API/前端工程规范

### 数据库

-   先扩展后收缩（expand/backfill/contract），避免大表锁表。
-   每次迁移有升级验证、回滚或不可逆说明。
-   外键先校验旧数据；审计/证据默认不级联删除。
-   状态值复用项目 Enum/常量。
-   评估
    `project_id + status + created_at`、`source_ref`、`agent_run_id`
    等索引。
-   写操作有权限、对象归属、状态机和幂等检查。
-   API Catalog、OpenAPI、权限配置、前端类型和文档同步。
-   不存音视频 Base64 或大型文件正文。

### 前端

优先改已有页面： -
`TranscriptDraftsPanel.tsx`：事实、来源、接受/拒绝/澄清、需求确认。 -
项目详情：Discovery、本体变更、方案版本、Workflow 运行。 -
方案页：审核、来源、选择性生成任务。 - Workflow 页：模板、Draft
预览、节点权限/Schema、发布确认、证据。 -
`AgentsConsole.tsx`：授权、运行、日志脱敏、产物审核、失败/续接/取消。 -
任务详情：测试计划、测试结果、验收证据。 -
Dashboard：周期、接受率、返工率、人工介入、样本量。

每个页面处理 loading/empty/error/permission denied/stale
data/重复提交/取消。不得以静态 mock 作为真实验收。

### 权限矩阵原则

Agent 可生成草稿，不得批准正式事实/需求、本体 Change Set、Workflow
发布或 Gate。项目成员按角色触发任务；项目负责人/授权审核人审批；宿主 CLI
执行需单次显式授权。生产环境变更仍需独立审批。所有关键写操作记录
Actor、对象、前后状态、时间、理由、来源 Run 和请求 ID。

------------------------------------------------------------------------

## 13. 测试质量门槛

1.  单元：Schema、状态机、幂等、权限、策略、解析器。
2.  集成：DB 事务、Outbox、Worker、Workflow 节点。
3.  API：认证、授权、跨项目隔离、输入校验、分页。
4.  前端：审核、状态、失败恢复、权限显示。
5.  E2E：至少一个完整脱敏项目从访谈到交付验收。
6.  安全：路径穿越、命令注入、越权、重放、敏感日志、文件访问。
7.  回归：G1--G9、项目/任务、Agent/Skill/Workflow、报价合同等既有能力。
8.  新增服务端逻辑必须有测试；新增路由必须有权限测试；迁移必须有升级和兼容测试。
9.  不新增未解释的 skip；失败必须修复或作为明确阻塞，不能伪造结果。
10. 按 `AGENTS.md` 的真实命令执行 lint、类型检查、格式检查和全量测试。

每次报告环境版本、命令、通过/失败/跳过数量、失败详情、耗时；不要只写"测试通过"。

------------------------------------------------------------------------

## 14. 实施顺序与首个纵向切片

严格顺序： 1. P0-0 基线审计（无业务代码修改）。 2. P0-1 访谈事实/需求。
3. P0-2 本体候选与稳定 ID。 4. P0-3 方案与任务分解。 5. P0-4 Workflow
Draft。 6. P1-2 测试计划和证据能力。 7. P1-1 ZCode
宿主执行通道（安全门通过后）。 8. P1-3 指标与 Skill 学习。 9. P2
真实项目试点。

首个纵向切片限制： - 一份脱敏访谈文本； - 抽取 10--30
条事实/需求候选； - 人工审核； - 生成一份交付方案； - 方案转 3--10
个现有任务； - 生成一个 Workflow Draft； - 人工发布并执行非生产节点； -
生成测试/证据报告； - Gate Service + 授权审核人完成验收。

### 衡量成功

实施前后同口径比较：人工工时、来源可追溯率、方案转任务率、Agent
产物接受率、Workflow
成功率、测试首次通过率、返工率和人工介入次数。没有真实数据不得写性能承诺。

------------------------------------------------------------------------

## 15. 可直接交给 ZCode 的 Goal 循环总提示词

``` text
你是蔡工 FDE Workbench V3.1 的资深架构师、全栈工程师、测试工程师和安全审计员。
严格执行《蔡工 FDE Workbench V3.1 智能交付自动化升级路线图与 Goal 实施任务书》。

总目标：
在不破坏现有项目、任务、G1-G9 Gate、Agent、Skill、Workflow、Ontology、审计和权限体系的前提下，
打通访谈→事实/需求→本体审批→交付方案→Workflow Draft→受控执行→测试证据→人工验收→经验指标。

最高规则：
1. 先读 AGENTS.md、项目文档和本任务书。
2. 先检查 git status、branch、HEAD；不得覆盖用户未提交修改。
3. 第一个 Goal 只做 P0-0 基线审计，不改业务代码。
4. 所有实现先定位真实模型、服务、路由、测试、迁移；本任务书的接口和表名是目标语义，不代表当前不存在。
5. 优先复用；新增表、路由、服务、字段必须说明现有能力为何不足。
6. 不建立第二套任务系统、Workflow 执行器、Ontology 或 Gate 状态机。
7. AI 输出的事实、需求、本体、方案、测试计划和 Workflow 均先进入草稿/审核。
8. Agent 不得批准正式需求、本体 Change Set、Workflow 发布或 G1-G9 Gate。
9. zcode_contract.py 是 CLI 契约层；宿主代理、安全授权、真实联调未完成前，禁止声称 ZCode 已接通。
10. 不执行生产变更、不对客户发送消息、不删除用户数据、不读取无关密钥或访问未授权目录。
11. 所有实现有测试；不得跳过失败、伪造测试结果或只做静态 UI。
12. 每阶段先提交方案、文件/模型/API/UI/测试清单和风险；完成后给出真实改动和证据。
13. 推断不能伪装成客户事实；客户数据跨项目学习前必须脱敏和权限隔离。
14. 只完成当前阶段，不自行跳阶段。

循环：
A 检查阶段前置条件；
B 阅读相关代码并画调用链/数据流；
C 提出最小改动方案；
D 高风险设计等待用户确认；
E 实现一个可独立验收的小切片；
F 运行针对性测试和必要回归；
G 检查迁移、权限、审计、幂等、错误恢复和安全；
H 更新 docs/v3.1 状态台账；
I 汇报完成项、文件、迁移、API、测试、风险和下一步；
J 只有阶段验收通过才进入下一阶段。

阶段顺序：
P0-0 → P0-1 → P0-2 → P0-3 → P0-4 → P1-2 → P1-1 → P1-3 → P2。
每个 Goal 只做一个阶段或明确子切片，不得一次性大改全仓。

每轮必须汇报：
- 当前 SHA、分支、阶段状态；
- 修改文件及原因；
- 新增/变更表、字段、索引、迁移；
- API、权限、API Catalog；
- 前端变化；
- 测试命令和通过/失败/跳过数量；
- 安全、兼容、回滚结果；
- 验收证据、未完成事项和阻塞；
- 是否允许进入下一阶段。

现在开始：只做 P0-0 基线审计，不修改业务代码。
```

------------------------------------------------------------------------

## 16. 阶段状态记录模板

保存为 `docs/v3.1/phase-status.md`：

``` markdown
# V3.1 阶段状态
- 基线 SHA：
- 当前分支：
- 当前阶段：
- 状态：not_started / in_progress / blocked / completed
- 开始/完成时间：

## 本阶段目标
## 真实代码定位
## 设计决策及理由
## 修改文件
## 数据库迁移
## API / 权限 / API Catalog
## 前端变化
## 测试命令与结果
## 安全检查
## 数据兼容与回滚
## 验收证据
## 遗留问题
## 是否允许进入下一阶段
```

建议文档目录：

``` text
docs/v3.1/
  00-baseline-audit.md
  00-data-model-map.md
  00-test-baseline.md
  00-gap-register.md
  architecture.md
  api-contracts.md
  data-model.md
  security-review.md
  phase-status.md
  pilot-runbook.md
  pilot-retrospective.md
  decisions/
    ADR-001-reuse-existing-workflow.md
    ADR-002-ontology-ownership.md
    ADR-003-host-agent-security-boundary.md
```

------------------------------------------------------------------------

## 17. V3.1 最终验收清单

-   [ ] 基线审计、数据模型图和测试基线归档。
-   [ ] 访谈事实/需求可追溯到原始来源。
-   [ ] 事实/需求支持接受、拒绝、澄清和审计。
-   [ ] 本体候选不能绕过 Change Set 审批。
-   [ ] 至少一个试点领域对象使用稳定 ID，旧数据兼容。
-   [ ] 交付方案引用已批准需求并有版本。
-   [ ] 方案条目幂等映射到现有项目任务。
-   [ ] Workflow Draft 可生成、校验、人工发布。
-   [ ] Workflow 可恢复、取消、重试且幂等。
-   [ ] Gate Service 是唯一门禁状态决策入口。
-   [ ] Agent 产物有来源、hash、审核和撤回信息。
-   [ ] 测试失败不能被 Agent 摘要改写为成功。
-   [ ] ZCode 未通过安全审批时保持关闭并可人工接管。
-   [ ] 如接通
    ZCode，授权、沙箱、超时、取消、脱敏、产物校验和真实联调全部通过。
-   [ ] 指标口径统一，样本不足不误导。
-   [ ] Skill 改进经草稿、审核和版本化发布。
-   [ ] 至少一个脱敏端到端试点完成并复盘。
-   [ ] 全量回归通过，或已知基线失败有批准说明。
-   [ ] 无未解决高危安全问题。

**最终原则：** V3.1 不是让 Agent
自主做所有事，而是让每个交付动作具备明确输入、权限、状态、来源、证据、审核和回滚路径，在可控边界内减少重复劳动，同时保留人的最终决策权。
