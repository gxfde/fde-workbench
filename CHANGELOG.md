# Changelog

本文件记录 FDE Workbench 开源版本的主要变化。版本号遵循语义化版本规范；首次公开源码版本为 `v0.1.0`。

## [未发布] — V3 实施 T-E3：bridge/任务证据统一入口（双通道落一等证据行，2026-11-03）

### 服务端（零迁移零路由零 DDL / task_service + bridge/sync 两处写入点挂接 / 零桌面改动）

- **任务侧**：`evidence_uri` + `evidence_hash` 齐备时，建任务/改任务同事务同步登记一等证据行（kind=`task`、captured_from=`human`、origin=`task:<task_key>`，大写 hash 归一小写）；同指纹幂等不增行，清空指针不动登记簿（证据不可变），只挂指针不落指纹不构成指纹不登记。写入点在乐观锁 rowcount 校验之后——stale 版本零证据副作用。
- **桥侧**：`apply_snapshot` 投影事务内把**已挂接 workbench 项目**的桥接采集登记为一等证据行（kind=`bridge`、captured_from=`bridge_sync:{run_id}` 机器通道、created_by 空）；openfde 按 engagement 指纹逐 slug、fdeops 按工作区级 registry_sha256；指纹不齐整（缺 hash / uri 越界）跳过不炸——投影是 4h 关键路径，证据不构成失败；同指纹幂等（内容不变不增行，内容变化=新指纹=不可变采集史新行）；`BridgeSyncRun.summary` 增 `evidence_created` 计数。
- **契约不动**：任务 DTO 与 engagement_view 均不暴露 evidence_id（沿 T-E2 gates_read 先例）；零新事件（任务侧 event_changes 已含证据字段变更；桥侧无 actor，summary+登记簿即审计）；登记路径仍不进 api_catalog（AI 不可写证据纪律不变）。
- **测试**：`test_project_tasks_api.py` +1（建/幂等/换指纹/清空/只指针 五段）+ `test_bridge_sync_flags.py` +1（挂接登记/未挂跳过/坏指纹跳过/重放幂等）。
- **口径**：业务表 **101 不变** / 迁移头 **`c1e5f9a3d7b2`（27 revision）不变** / 路由 **283 不变** / pytest **1782 收集 = 1776 passed + 6 skipped** / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d`（**api/worker/scheduler 三镜像**；迁移头不变，无需 alembic）。

## [未发布] — V3 实施 T-S1：Skill 治理态（draft/in_review/published/deprecated + 发布四闸，2026-11-03）

### 服务端（1 个迁移（唯一 DDL）/ 5 条新路由 / extensions_service 治理化 / 零桌面改动）

- **治理状态机**：`draft →(submit-review)→ in_review →(publish)→ published →(deprecate)→ deprecated`；编辑已发布公共 Skill 开新版本行并回 draft 重走治理。迁移 **`c1e5f9a3d7b2`**：`skill_definitions.status` 从扩展共用值域（active/disabled）切到治理四态（CHECK 换值域），存量 **active→published**（发布人暂记创建人）、**disabled→deprecated**；skill_definitions 加 published_by/at、skill_versions 加 input/output schema + test_report_json + reviewed_by（全可空，版本行不可变不变）。
- **发布四闸**：admin（system_operator）/ 密码确认（`invalid_password` 403）/ 状态须 in_review / 测试报告或显式 waive（`test_report_required` 409）；发布把版本行 `reviewed_by` 落为发布人（发布即审核背书）。回滚 = published 内改指旧版本行（版本行不可变），同密码+材料闸。
- **个人 Skill 自发布豁免**：保存即 published（owner 自治）；四闸只对公共 Skill。内置种子走服务端内部参数 `initial_status="published"` 直发布（内容可信），`_is_unchanged_builtin` 升级判定同步收敛。
- **消费方收敛（T-W1/T-W3 挂账清偿）**：MCP 工具面（`mcp_gateway._skills`）、工作流 skill.ref 定义期白名单（`published_skill_refs`）、执行器 skill 节点分派三处全部只认 `published`。
- **API 五条（278→283）**：submit-review / publish / rollback / deprecate / versions；content_sha256 指纹扩展覆盖全部发布材料（schema/测试报告变更即新版本）。
- **兼容**：既有 PATCH 启停开关保留旧值域作别名——个人 Skill 自愈发布（幂等）；公共 Skill 发布向 409 `governance_required`（开关不得旁路四闸），停用向照旧。桌面治理 UI（审核/发布按钮）挂后续轮。
- **测试**：NEW `test_skill_lifecycle.py` **7 例** + 修 5 处 active 语义既有用例（chat_mcp/executor/solution_skills/lcsc_other/extension_management PATCH 流）；`test_migrations.HEAD_REVISION` → `c1e5f9a3d7b2`。
- **口径**：业务表 **101 不变** / 迁移头 **`c1e5f9a3d7b2`（27 revision，+1）** / 路由 **283（+5）** / pytest **1780 收集 = 1774 passed + 6 skipped**（全量实跑 1209s） / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（skill 两表列变更 + 存量状态迁移；**api/worker/scheduler 三个镜像都要 build**）。

## [未发布] — V3 实施 T-W5：Workflow cancel/resume HTTP 面（服务端编排面收口，2026-11-03）

### 服务端（2 条新路由 / 零新表零迁移 / 零服务层改动 / 零桌面改动）

- **运行生命周期路由两条（276→278）**：POST `/api/v1/projects/{id}/workflow-runs/{rid}/cancel`（can_manage，幂等——重复取消 200 `cancelled=false`；终态 409 `already_terminal`；waiting_approval 可取消，pending 审批行不动）与 POST `…/resume`（can_manage，failed-only——failed/skipped 节点放回 pending 重投 `workflow.run`；其余 409 `not_resumable`）。服务层 `cancel_run`/`resume_run`（T-W3）直挂 HTTP，零服务层改动。
- **reconcile 收敛**：标题项已随 T-W3 落地（RECOVERABLE 增 `workflow.run` + worker-loss 钩子），本任务无残留。
- **测试**：`test_workflow_executor.py` **26→27**（HTTP 面：viewer 403 / 幂等取消 / already_terminal / 跨项目 404 / failed-only 恢复+节点回 pending / not_resumable）。
- **口径**：业务表 **101 不变** / 迁移头 **`d5b8e2f4a7c9`（26 revision）不变** / 路由 **278（+2）** / pytest **1773 收集 = 1767 passed + 6 skipped** / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d`（**api/worker/scheduler 三镜像**；迁移头不变，无需 alembic）。

## [未发布] — V3 实施 T-W4：Workflow 执行器 agent/human_approval 节点（审批复用 automation_approvals，2026-11-03）

### 服务端（1 个迁移（唯一 DDL）/ 零新路由 / 执行器+control 审批链扩展 / 零桌面改动）

- **human_approval 节点 = 复用 automation_approvals（设计 §3 落实）**：迁移 **`d5b8e2f4a7c9`**——`run_id` 放开可空 + 新增可空 `workflow_node_run_id` 反链（审批行=节点等待态的投影，FK CASCADE 随节点走，审计事实由 operation_events 承载）。分派即建审批：request_key=`wfnode:{节点行id}`、arguments_sha256 绑定输入快照、敏感键扫描（`contains_sensitive_argument` 提升为 control/access 公共函数，与 DSH 审批同闸）+ 64KB 上限、risk_level=4、15min 过期（`expires_minutes` 节点字段 1–1440 可调）；审批 id 挂节点幂等键 + pending 查重 ⇒ 崩溃恢复不重复建单。
- **拍板走既有任务中心入口（零新路由）**：`decide_automation_approval` 按 run_id 分支——workflow 审批经 `executor.settle_approval_node` **同事务**落节点终态（批准→succeeded 且 output 携 approval_id/拍板人/理由；拒绝/过期→failed）并**重投 workflow.run** 续跑；`dsh_approval_status` 惰性过期与 `execute_approved_dsh_tool` 同步加 workflow 守卫（审批无执行段）。
- **等待语义**：无 ready 且剩 waiting 节点 → run=`waiting_approval`（handler 正常返回；**有 failed 先断链收敛** FV-F1）；无人拍板则挂起（可取消），过期=拍板时惰性判定（主动清扫随 T-P1-5）；取消时 waiting 节点 cancelled、迟到拍板只落审批行不再驱动节点；resume 保持 failed-only。
- **agent 节点 = agents.start_run 同闸全链**（实时鉴权/月度预算/试点配额/T1/T6/沙箱/产物校验，绝不旁路）：幂等键 `wfnode-{节点行id}:{attempt}`——agents 对失败终态 run 拒绝同键重跑（V8），工作流以 **attempt 代际**表达「显式重试」（resume_run）；分派失败一律不叠加工作流自动重试（agents 自带重试族）；`params.solution_id` 透传使 agent_assisted/T1 方案闸随之生效。
- **定义期**：human_approval.capability 白名单 = 能力登记表去 `system.*`（validate_dag 注入参数，纯函数单测兼容）；四类之外未知类型的 start_run 422 守卫保留为防御（发布后白名单漂移场景）。
- **事件**：新增 `workflow_run_waiting_approval` / `workflow_run_approval_decided`。
- **测试**：`test_workflow_executor.py` **19→26**（审批批准/拒绝/过期/等待中取消+迟到拍板中和/幂等重入不重复建审批 + agent 全闸/能力拒绝不重试/run 失败不叠加重试）+ `test_workflow_definition.py` +1（capability 白名单）；`test_migrations.HEAD_REVISION` → `d5b8e2f4a7c9`。
- **口径**：业务表 **101 不变** / 迁移头 **`d5b8e2f4a7c9`（26 revision，+1）** / 路由 **276 不变**（零新路由）/ pytest **1772 收集 = 1766 passed + 6 skipped**（1764 + 8；实跑口径见 AGENTS.md）/ vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（automation_approvals 两列变更；**api/worker/scheduler 三个镜像都要 build**）。

## [未发布] — V3 实施 T-W3：Workflow 执行器（call/skill 节点 + §5 路由 + jobs handler，2026-11-03）

### 服务端（零新表零迁移 / 5 条新路由 / 新执行器模块 / 零桌面改动）

- **执行器**（NEW `workflows/executor.py`，设计 workflow-dag-v1 §3）：`workflow.run` 作为 background_jobs 新 job_type（决策 3：复用既有 outbox/lease/续租/reconcile/failure-hook 全套，绝不复制第二套队列）。主循环 = ready 调度（依赖全 succeeded，或 when 真值裁决放行）→ 节点独立事务执行 → 无 ready 全终态收敛 run；**每节点状态迁移独立事务、分派（HTTP/AI）一律在事务外**（产物先落表再前进=崩溃恢复锚点，2026-10-30 事故教训）。
- **call 节点 = api_execute 同闸绝不旁路**：鉴权/确认/项目 scope 每节点实时校验（发起人当下 AI 档位，run 级不冻结）；写类节点命中确认闸 → 节点 failed 携 action_id（诚实呈现未执行，T-W4 接审批前置）。**外副作用幂等（修 fde-v2 FV-F3 执行侧）**：写类（api_catalog write=True）节点分派前强制落节点级 `idempotency_key`（与 api_actions 完全同构 sha256 `[user_id, "wfnode-{节点行id}", data]`）——重试/崩溃恢复同键，api_execute 按 action 去重不二次外呼。
- **skill 节点 = pinned 版本确定性 AI 调用**：`key@版本` 固定版本 `instructions_text` 作 system_prompt、节点输入 JSON 作 prompt、`use_tools=False`（不签发 MCP token，工具面留在 call 节点）；T-S1 前沿用 active 语义（与 T-W1 校验口径一致）。
- **诚实语义**：占位符缺键 → 节点 failed `placeholder_missing`（绝不填空串，fde-v2 缺陷回归用例钉住）；断链 → run **failed** + 下游 skipped（修 FV-F1 不静默 done）；`when` 仅支持整串单占位符真值（表达式引擎待真实需求）；agent/human_approval 节点在 start_run 即 422 `unsupported_node_type`（不留必死 run，T-W4 开放）。
- **§5 路由五条（271→276）**：POST projects/{id}/workflows（can_manage）、POST …/{wid}/publish（admin 锁版）、POST …/{wid}/runs（can_manage，幂等键同 run 返回 200/新建 201，跨项目同键 409）、GET …/workflow-runs/{rid}（can_view 节点按拓扑序）、GET /api/v1/workflows（admin 平台模板）；**cancel/resume 的 HTTP 面随 T-W5**（服务层 cancel_run/resume_run 已可用）。
- **run 生命周期服务**：start_run（published 闸+幂等键先于定义查找） / cancel_run（停未执行节点、已执行外呼不回收、幂等） / resume_run（failed→重置 failed/skipped 节点复用产物）；事件目标新增 `workflow_run`（created/succeeded/failed/cancelled/resumed）。
- **jobs 接线**：`workflow.run` handler + worker-loss 收尾钩子（reconcile 放弃时 run 与悬挂节点推终态）+ RECOVERABLE_JOB_TYPES 增补（节点产物先落表=succeeded 即恢复锚点，重跑只处理未完成节点）；handler 入口恢复 queued→running 与死亡遗留 running 节点。
- **测试**：`test_workflow_executor.py` 新 **19 例**（§6 用例 4/5/6/7/8/11：链路与占位符原类型替换 / 版本钉住跨发布 / skill 钉版本指令 / 重试后成功与耗尽恢复复用产物 / 幂等键同构公式+跨重试恢复稳定 / 取消保留已成功节点 / 断链 failed+skipped / when 假值跳过 / 缺占位符不填空串 / 平台模板路由与项目内实例化 / outbox→worker 全链 / reconcile 钩子）。
- **口径**：业务表 **101 不变** / 迁移头 **`b7d9f1a3c5e2`（25 revision）不变**（零 DDL）/ 路由 **276**（+5）/ pytest **1764 收集 = 1758 passed + 6 skipped**（1745 + 19；实跑口径见 AGENTS.md）/ vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d`（server 代码烤进镜像；无迁移，alembic head 不动）。

## [未发布] — V3 实施 T-W2：Workflow 运行层（runs / node_runs 两表，2026-11-03）

### 服务端（2 张新表 / 1 个迁移 / **零新路由、零执行器、零服务逻辑改动** / 零桌面改动）

- **运行 + 节点运行双表**（迁移 **`b7d9f1a3c5e2`**，含 downgrade）：`workflow_runs`（固定 (definition_id, definition_version)——跑动中被改即受影响的 fde-v2 教训；run 级 `idempotency_key` **全局唯一**，修 fde-v2 FV-F3 无幂等重跑重复建单；status 七态 CHECK queued/running/waiting_approval/paused/succeeded/failed/cancelled；context_json=运行级入参占位符源；definition FK **RESTRICT**——执行史在则定义不可静默删，project FK CASCADE 项目隔离）+ `workflow_node_runs`（**UNIQUE(run_id, node_key)**；node_type 四类 CHECK（无 condition/wait，设计钉死）；status 八态 CHECK pending/ready/running/waiting/succeeded/failed/skipped/cancelled；attempt 计数；`depends_on` 定义侧冗余快照可追溯；节点级 `idempotency_key` 可空——外副作用节点必填由 T-W3 执行器强制；input_snapshot 执行前落审计可回放 / output_json 下游占位符解析源；run FK CASCADE）。
- **纯增量零改既有表**：T-W1 定义两表原样；执行器（ready 调度循环、重试、恢复）随 T-W3，路由随 T-W3 一起开。
- **配套**：`conftest` 清理序（node_runs → runs → definition_versions → definitions）、`test_migrations.HEAD_REVISION` → `b7d9f1a3c5e2`；`migrations/env.py` 按模块导入无需改、审计抽取脚本按模块自动发现无需改。
- **测试**：`test_workflow_runs.py`（新 11 例：默认态与版本钉住 / run 幂等键全局唯一（FV-F3 表级保证）/ 节点键 run 内唯一 run 间允许 / run 列守卫参数化 4 例 / 节点类型与状态守卫 / run 删除级联节点 / 定义删除 RESTRICT / 项目删除 CASCADE 带走 runs+nodes 且平台模板不阻拦）+ `test_migrations.py` +1（运行两表迁移往返保留 projects、定义两表共存）。
- **口径**：业务表 **101**（+2）/ 迁移头 **`b7d9f1a3c5e2`（25 revision）** / 路由 **271 不变** / api_catalog ENTRIES 94 不变 / pytest **1745 收集 = 1739 passed + 6 skipped**（1733 + 12；本机全量实跑 1851s）/ vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（新表）。

## [未发布] — V3 实施 T-W1：Workflow 定义层（两表 + dag_json 校验纯函数，2026-11-02）

### 服务端（2 张新表 / 1 个迁移 / **零新路由、零执行器** / 零桌面改动）

- **定义 + 不可变版本双表**（迁移 **`f2a4c6e8b1d3`**，含 downgrade）：`workflow_definitions`（draft/published/archived；发布递增 version；NULL project_id=平台模板）+ `workflow_definition_versions`（发布快照，(definition_id, version) 唯一，**写后不可变**——运行固定引用版本号，fde-v2 教训）。
- **`validate_dag` 纯函数先入 CI**（零执行器依赖，backlog T-W1 验收）：环检测=Kahn 拓扑并**点名环节点**（修 fde-v2 FV-F1）；未知依赖/自依赖/重复 key/未知类型/未知字段；**call.ref 必须 ∈ api_catalog ENTRIES**（白名单封 SSRF 面）；skill.ref 须为 active skill 的显式 `key@版本号`；agent.ref 须已启用；output 唯一且不遮上下文键；`{{placeholder}}` 须为运行上下文键或**传递上游**节点的 output；外部副作用无审批后继 → **P1 告警不阻断**（effect 结构化在 T-R2，P2 转强制）。违规一律 422 `dag_invalid` 携逐条 issues（code/message/node_key/detail）。
- **定义生命周期服务**（无 HTTP 路由——§5 路由随 T-W3 执行器一起开）：create（draft v1）→ update（已发布则自动 +1 开新草稿版本，版本行原样）→ publish（按**当前**白名单再校验后快照版本行；already_published 409）。事件 `workflow_definition_created/updated/published`（事件目标注册表新增 `workflow_definition`，平台模板 project_id 为 NULL）。
- **配套**：`migrations/env.py` 模型导入、`conftest` 清理序（版本行先于定义行）、`test_migrations.HEAD_REVISION`、审计抽取脚本模型清单。
- **测试**：`test_workflow_definition.py`（新 7 例：合法示例含拓扑序 / 环点名 / 结构与引用 / 三类 ref 白名单 / 占位符上下游 / 规则 9 告警 / 发布锁版本行+事件序）+ `test_migrations.py` +1（两表迁移往返保留 projects）。
- **口径**：业务表 **99**（+2）/ 迁移头 **`f2a4c6e8b1d3`（24 revision）** / 路由 **271 不变**（零新路由）/ pytest **1733 收集 = 1727 passed + 6 skipped**（+8；本机全量实跑期间机器休眠致 2 例连接中断失败，单跑复核绿，CI server-tests 干净复核）/ vitest 730 沿用。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（新表）。

## [未发布] — V3 实施 T-E1 + T-E2：一等证据表 project_evidence + 门禁证据挂接（2026-11-02）

### 服务端（1 张新表 / 1 个迁移 / 2 条路由 / 零桌面改动）

- **T-E1 一等证据表**：新模块 `fde_api/evidence/`（models / service / routes）+ 迁移 **`e1f3a5c7b9d2`**（`project_evidence`：UNIQUE(project_id, source_uri, content_sha256) 指纹即幂等键，kind 七类 CHECK，sha256 长度 CHECK，INDEX(project_id, kind)；project FK CASCADE、创建人 FK SET NULL；含 downgrade）。只存指针 + 指纹，不存原件（红线）。
- **API**：`POST /api/v1/projects/{id}/evidence`（can_manage；首次 201 `created=true`，同指纹 200 `created=false`——证据不可变，命中不改写 origin/captured_from）、`GET …/evidence?kind=&referenced_by=gate:Gx`（can_view；referenced_by 反查门禁清单项挂接）。错误码 `invalid_sha256` / `invalid_request` / `forbidden` / `project_not_found`。**有意不进 api_catalog**（AI 不可写证据，用例钉住）。
- **T-E2 门禁挂接**：`submit_gate_evidence` 每项先 `upsert_evidence`（kind=gate、origin=`gate:Gx/<清单项>`、captured_from=human），清单项 JSON 内挂 `evidence_id`，事件 `gate_evidence_submitted.items[]` 携 evidence_id；`_serialize_gate` 读时合并（历史清单项 `evidence_id=null`），**零 DDL**。同指纹二次提交幂等（行数不增、id 不变）。
- **并发安全**：`upsert_evidence` 在保存点内插入，撞唯一指纹回退后读回赢家，不向调用方抛 IntegrityError。
- **配套**：`migrations/env.py`、`conftest` 清理序、`test_migrations.HEAD_REVISION`、审计抽取脚本的 blueprint/模型清单均已登记新模块；`gate_service` 对 `evidence.service` 延迟导入（避免 projects⇄evidence 环）。
- **测试**：`test_evidence_registry.py`（新，6 例：指纹幂等与不可变 / 校验 / 权限与跨项目隔离 / kind 与 referenced_by 过滤 / 服务层入口 / 不进 catalog）+ `test_gates_api.py` +1（T-E2 挂接全链）+ `test_migrations.py` +1（迁移往返保留 projects）。
- **口径**：业务表 **97**（+project_evidence）/ 迁移头 **`e1f3a5c7b9d2`（23 revision）** / 蓝图路由 **271**（+2）/ blueprint 34 / api_catalog ENTRIES **94 不变** / pytest **1725 收集 = 1719 passed + 6 skipped**（+8，921.98s 全量实跑） / vitest 730 沿用。
- **部署**：`docker compose build && up -d` 后**须 `alembic upgrade head`**（新表）。

## [未发布] — V3 实施 T-P0-1：signoff 死锁修复（审计 WB-DEF-1，2026-11-02）

### 服务端修复（零迁移、零新路由、零桌面改动）

- **症状**（审计 WB-DEF-1，P0 功能阻断）：signoff checkpoint 唯一开闸点是 `handoff_run`，而它只收失败 / L1 降级 run；agent_assisted 方案经 generate-agent **正常 completed** 后既不能 handoff 又拿不到 pending → `POST …/signoff` 409 `signoff_not_pending` 与 `POST …/export-sow` 409 `solution_signoff_required` 永久互锁，SOW 一个字节都导不出。包声明 agent_assisted 而方案无 run 的形态同样死锁。
- **修复**：新增 `fde_api/agents/signoff.py::ensure_pending_signoff` 作为唯一幂等开闸入口（同方案至多一个 pending，只补空 run 软链不覆写）；`_finalize` 对非降级 completed 且绑定 solution 的 run 即时开出 pending（L1 维持「人工接管后再开闸」既有语义）；`handoff_run` 改走同一入口；`export_sow` 的 agent_assisted 闸拆成独立事务，拦下且无 pending 时**兜底开闸并先提交再抛 409**（闸本身不放宽），409 `details` 携 `signoff_checkpoint_id / signoff_status / remedy=resolve_pending_signoff / remedy_path`。
- **错误体**：`DocumentDraftServiceError`（= `SolutionServiceError`）新增可选 `detail`，solutions 蓝图错误处理器透传为 `error.details`（与 `AgentsServiceError` 同形；三参调用零改动）。
- **测试**：`test_solution_signoff.py` +5（端到端先红后绿：generate-agent completed → export 409 携指路 → 终审拍板 approved → export 200；无 run 兜底开闸且重复导出不重复开闸；驳回后再导出重开新一轮 pending；L1 降级 completed 不自动开闸仍走 handoff；开闸入口幂等/软链回填）。对旧代码实跑红：completed 后 checkpoint 数 0、409 无 details。
- **口径**：pytest 1717 收集 = 1711 passed + 6 skipped（d14 1712 + 本轮 5）；路由 269 / 表 96 / 迁移 22 不变；桌面零改动（vitest 730 沿用）。审计文档回写：`docs/implementation/v3-backlog.md` T-P0-1 → DONE（含实现偏差），风险登记册 / 差距矩阵 WB-DEF-1 → 已修复。

## [未发布] — V3 融合审计：Workbench × fde-v2 深度代码审计与 V3 升级实施方案（2026-11-02）

### 纯文档 + 审计脚本轮（零业务代码、零迁移、零部署）

- **主报告** `docs/architecture/蔡工FDE_Workbench_fde-v2架构融合审计与V3升级实施方案.md`（20 节 + Mermaid 五层架构图）：对 Workbench @0570384 与外部项目 fde-v2（快照≈上游 master@39e0e62，零执行只读审计）逐模块对照；核心裁决=**不引入 fde-v2 实现，只吸收四件经验证思想**（YAML DAG 形态 / 候选→人工确认闭环 / 证据"出处+源块"粒度 / BR 三要素机器可读纪律），七项 fde-v2 设计明确不搬（flow 执行器、运行时 DDL reconcile、隐式页面授权、exec 角色装配、user=None 全通、全量内省工具面、agentscope 团队）。
- **审计产物** `docs/audit/`：双仓基线、模块清单、路由清单 CSV（385 行=WB 269 url_map 枚举 + fde-v2 116 AST）、数据表清单 CSV（121 行=WB 96 表全字段+首建迁移归属 + fde-v2 17 DDL）、测试盘点与实跑终录、**17 能力域差距矩阵**（REUSE/EXTEND/NEW/DEFER 逐域裁决，含 Workbench 自身 14 项现状缺陷——WB-DEF-1 signoff 死锁为 P0 功能阻断）、风险登记册；`appendix/` 六份行号级原始证据报告。
- **架构设计** `docs/architecture/`：ontology-registry-v1（3 新表 terms+aliases / relation_types / change_sets + project_evidence 底座；6 个候选表经查重不建）、workflow-dag-v1（作为 background_jobs 新 job_type，不建第二套队列；四类节点；校验器纯函数先入 CI）、agent-policy-v1（权限五原则现状 VERIFIED 保持 + ToolGroup 只收窄 + Skill 以既有双表扩治理态）。
- **实施台账** `docs/implementation/`：v3-backlog（24 任务含文件/表/API/测试/回滚/复杂度）、v3-test-plan（本体/Workflow/权限安全/门禁交付物四族验收用例）。建议起手：T-P0-1 死锁修复 → T-E1/E2 一等证据表 → T-W1 DAG 校验器。
- **可复现抽取脚本** `scripts/audit/extract_{workbench,fde_v2}_inventory.py`（裸 Flask 注册全部 blueprint 枚举 url_map + Base.metadata，不调 create_app 零副作用；外部快照 `python -I` + AST/regex 零 import）。
- 实跑基线（本轮真实执行）：pytest 1700 passed + 6 skipped（1706 收集，与 d13 口径一致）/ vitest 730/730 / operations 14/14；fde-v2 verify 套件按不受信零执行纪律未跑（UNKNOWN 如实记录）。口径数字不变：96 表 / head `c3e7a9b1d5f4` / 路由 269 / ENTRIES 94。

## [未发布] — 派单 r12 签字执行：14 条留注归档 + B-③ 销号 + B-① 律师包定稿（2026-11-01）

### 纯文档销号轮（零代码）

- **留注 14 条签字归档**（设计文档 owner 交互签字）：12 条即归档（①②④⑧⑩⑪⑫⑰⑱⑲⑳㉑）+ 附条件 2 条勾选维持（③ 复购约束放宽 / ⑥ onsite 关键词派生）；需变更 5 条去向：⑤已执行（#55）、㉒已销号、⑨⑬随 B-① 等律师、⑦⑭⑮ 登记二期待办（⑭ 前置=行业→大类映射口径待业务给出）。
- **B-③ 拍板销号**：平台公司统一开票 + 预扣率表=税务总局 2025-16 公告口径确认（`WITHHOLDING_BRACKETS` 已是该口径，零改动）；衍生小项挂下次工程轮：`mark_payable` 扩开票方/税率字段必填。
- **B-① AI 法律研究底稿定稿 + 律师包待寄**：底稿（文档中心 06_派单引擎，官方条文抓取核实，**非法律意见**）倾向撮合引擎不落入算法备案义务/LLM 内部使用免大模型备案；用户拍板寄律师包、B-① 维持「需备案」零改动。台账 30.11。

## [未发布] — 派单 r12 拍板执行：B-④ 城市终版 + 留注⑤ 冷启动口径切换（2026-11-01）

### 首批城市名单定稿（全行业口径）

- **B-④ 拍板终版**：首发六城 = 上海/广州/深圳/杭州/成都/武汉（全行业服务口径 + 优先南方和一线城市；原苏锡常制造业走廊建议名单退役）。`seeds/dispatch_cities.json` 换终版（meta 记拍板来源）；**名单定稿≠开闸**——claim_enabled 仍全 false，开闸由 §6.4 三条件 + 城市开关驱动（B-① 备案完成+公示前 claim 维持降级态）。
- **留注⑤ 冷启动口径切换**：`settlements.py:_city_order_rank` 由交付席位 home_city 代理改为**包侧客户城**（企业代号第三段）；`cities.py` 新增公共助手 `package_client_city`/`city_from_enterprise_code`，cities/maintenance/settlements 三处城口径去重为一（maintenance `_client_city_of` 改委托）。
- **拍板销号（零改动）**：B-① 维持「需备案」（律师意见书仍是权威输入）；B-② 维持对公口径；直签豁免维持绝对封堵；P2-2 维持 5 态（留注㉒ 同步归档）；仿真器校准暂无数据继续等待。台账三十节 30.10 执行记录。
- 回归：种子断言/geo 钉子/冷启动夹具对齐新名单（档案城深圳≠包侧城杭州的反向回归钉）；桌面零改动。台账三十节 + 等待清单刷新（30.10）。

## [未发布] — 派单线收尾轮 r12：外部输入到达执行手册（2026-11-01）

### 零功能补码的落点普查轮

- **外部输入到达执行手册**（台账三十节）：八项外部输入（B-①备案/B-②托管/B-③开票与预扣率/B-④城市名单/P2-2 状态集/仿真器校准/留注签字/直签豁免）的"到达即执行"代码与数据落点逐项普查确认——落点全部存在，零补码；每项含分支动作、影响面与回归口径，任一输入到达按节执行即可。
- **C7 核实**：混合模式自动转换 job 已在 goal-r10 落地，8 例于本轮头复跑全绿——零重做。
- **留注编号勘误**：⑯为空号（r5→r6 跳号），实有定义 21 条；签字分类=12 归档 / 2 附条件 / 7 需变更。
- 联合口径不变：94 业务表 / head `f6a9c3e1d7b4` / 路由 252 / ENTRIES 86 / pytest 1563 收集 / vitest 695。

## [未发布] — 派单运维页簇 B3/B5/B6（2026-11-01）

### 争议处理 / 仿真对比 / 开闸运维（零迁移）

- **服务端五路由**（薄包装既有服务层，全部平台侧）：`GET /dispatch/disputes`（L0–L3 全量留痕；对账单只透出 `l0_report_source_uri` 指针——红线字段不内联本体）、`POST /dispatch/disputes`（人工打开仅 L1/L2——L0 由对账自动产；L1 金额 >¥50,000 → 422 `amount_above_l1`；快照锚=打开时包快照 §2.3 规则 2）、`POST /dispatch/disputes/{id}/resolve`（结论必填；close 直关；处罚类动作 100% 人工）、`POST /dispatch/simulator/replay`（历史包只读回放——当前池×当前规则版本再撮合画像，不落 offer；全链路种子化仿真留 CLI 沙箱库，绝不经 HTTP 触发写库）、`GET /dispatch/claim-gates`（§6.4 三条件+种子开关逐城可解释明细；开关在 seeds 文件，只读不翻转）。ENTRIES 74→**79** / 路由 234→**239**。
- **桌面三个平台侧 tab**（九子页簇收官）：「争议处理」（L0–L3 层级/状态标签 + 打开表单 + 裁决表单含直接关闭）、「仿真对比」（执行回放 → 摘要卡片（场景分布/Stage A 通过率/Top1 均分）+ 逐包 Top3 画像；口径=仿真不作真实成绩常驻声明）、「开闸运维」（逐城判定徽章 + 三条件 ✓/✗ + 拒单率；"改走代码流程——本页只读"）。
- 测试：服务端 `test_dispatch_b3ops_pages.py` 8 例（L0 禁人工打开/L1 上限 422/快照锚/裁决 409/回放降级 skipped+只读断言/开闸种子对齐）；桌面 `dispatch-ops.test.tsx` 9 例（路由解析/角色门/裁决流/打开校验/回放摘要/开闸判定）。台账二十八节。

## [未发布] — 派单调度台操作面 B2（2026-11-01）

### 平台侧调度台（零迁移）

- **服务端包留痕路由**：`GET /dispatch/packages/{package_id}/offers`（平台侧 only）——一包全量 offer 留痕（谁被派/接了/拒了、§6.2 窗口 deadline 服务端现算、§4.8 rank/explanation 释明、候选人身份），调度台据此决定代接单/重派。ENTRIES 73→74 / 路由 233→234。
- **桌面「调度台」tab**（第 6 子页，admin/project_lead 可见，动作权限服务端复核）：供给池候选勾选器（复用 `GET /profiles`，勾选即发布授权/指派名单）；包全景列表（draft 也在列）按状态出按钮——draft：等级覆盖（§4.5 必填 reason 留痕）+ 发布（携候选只读授权）；withdrawn/rejected/expired：重新发布（服务端 round+1 新版本对）；published：执行撮合（§4 两段式，结果面板展示场景 A/B/C + Top3 释明 + 资格门淘汰数）/ 指派 offer / 撤回（TRANSITIONS 仅 published 可撤）；offer 留痕面板 + offered 行「代接单」（`POST /accept` 携 delivery_user_id）。时间窗只展示不重算（B1 纪律延续）。
- 测试：服务端 `test_dispatch_b2_console.py` 6 例（全量留痕/claim 15 分钟窗/空留痕/非平台侧 403/未知包 404/轮次倒序）；桌面 `dispatch-console.test.tsx` 10 例（路由解析/状态动作映射/角色门 tab 隐藏/发布携候选/撮合可解释结果/指派/撤回/等级覆盖 reason 闸/留痕+代接单）。台账第二十六节增补 B2 项。

## [未发布] — 派单接单工作台 B1（2026-10-31）

### 交付工程师专区（循环终止后首期派单范围增强，零迁移）

- **服务端三读路由**：`GET /dispatch/offers/mine`（收件箱=候选人本人全量留痕 + §6.2 窗口 deadline 现算 + §4.8 算法释明只回本人）、`GET /dispatch/settlements/mine`（只回本人席位角色与金额，他席存在与金额零出现；预扣税原样透出不算净额——B-③ 未定不发明）、`GET /dispatch/profiles/me`（自助档案 + 在途计数，无档案 404）。ENTRIES 70→73 / 路由 230→233。
- **白名单 payload 增 `id` 支撑列**（资源标识非内容字段；授权方抢单/接包必须持有目标 id）——§9.5 隔离基线②键集测试同步更新并全基线复跑绿。
- **桌面「我的接单」tab**：收件箱 + 待响应倒计时（30s 刷新，窗口判定永不在前端复算）+ 接单/拒单按钮（原因枚举四选一只进留痕）+ 算法释明折叠 + 我的档案卡；**「我的结算」tab**（我的分成/计提基数/预扣税/打款状态）；**派单池抢单按钮**（claim 模式 published/offered 包详情展开内；开闸判定在服务端，claim_closed 可解释信息直显=§11 降级态 UX）。
- 测试：服务端 `test_dispatch_b1_console.py` 7 例 + r3 隔离/r4 回归；桌面 `dispatch-mine.test.tsx` 9 例。企业需求方专区不做（设计 §1.4-3 明确排除：客户不接触派单池）；评估与任务清单见台账第二十五节。

## [未发布] — goal-r11 派单引擎终止复核轮（2026-10-31）

### 循环终止——最终收口报告 v2（零功能改动）

- **§八 八项终止判定全部成立**：更新版收口报告 `docs/goal-r11-派单引擎收口.md` 取代 r8 版本成为唯一凭证（r8 的两项例外已由 r9/r10 消解）。全电池重测：服务端 1456+6s / 桌面 660 / typecheck 0 / 闸④覆盖率 **85%**（3,009 语句含 channel_guard 89% + simulator 81%）/ 负面清单 7 反例 / H5 口径 85 表·15 rev·head `c5d7e9f1a3b7`·路由 228·ENTRIES 68。
- H2/H3 以内测/仿真口径达标（基准原文「内测/仿真先行」）：H2 0.9565 / 工时占比 0.0716 / 毛利率 0.9717（r9 仿真工件，假设表全量回显，真实数据到位后复测校准）。
- 剩余事项全部外部输入依赖（备案/托管/税率/城市名单/P2-2/直签豁免/仿真器校准/留注签字/便携版重打包），逐项登记于台账第二十三节与收口报告第五节。

## [未发布] — goal-r10 派单引擎轮（2026-10-31）

### C7 混合模式自动转换 job（零迁移）

- **混合模式落地**（派单设计 §6.1「先 assign 指派，响应窗内无人接 → 转 claim」）：`dispatch/maintenance.py` 新增 `convert_stale_assign_to_claim` 挂 `run_maintenance` 节拍——assign 死亡（expired/rejected）包 × 城市 claim 开闸（§6.4）→ mode 翻转 + 按 §2.3 重发（round+1 新码新哈希 + §4.7 扩圈推进）+ `dispatch_c7_converted` 事件留痕；幂等（翻转后不再命中）；单包 SAVEPOINT 隔离不炸整批；城市未开闸安全空转（§11 降级态，人工重派路径不变）；零新增时间常数（24h 判死由上游 expire 按 §6.2 执行）。
- 测试：`test_dispatch_p2_r10_c7.py` 8 例（含转换后 claim_package 实抢闭环、幂等、降级空转、单包故障隔离、§6.4 拒单率条件真实生效验证）；r1–r9 回归全绿。口径：85 业务表 / 15 rev / head `c5d7e9f1a3b7`（零迁移）/ 路由 228 / ENTRIES 68 / 服务端 **1456 通过** / 桌面 660。轮次报告 `docs/goal-r10-派单引擎.md`；台账第二十二节。

## [未发布] — goal-r9 派单引擎轮（2026-10-31）

### P2-4 私单封堵 + 撮合仿真器（零迁移）

- **P2-4 私下接单封堵**（派单设计 §8.5）：新增 `dispatch/channel_guard.py` 三服务层钩子——H1 立项入口（`business_line` 随立项显式声明，派单线仅平台侧可立、专属 403 码）、H2 池内企业直签封堵（企业进过派单池后直签立项/报价 → 422 `private_deal_blocked`，复购走派单线放行）、H3 渠道正交（交付包只建在派单线项目上 → 422 `dispatch_line_required`）；封堵留痕走独立事务（主事务回滚后仍存活）。
- **撮合仿真器**（留注⑳）：新增 `dispatch/simulator.py`——历史包只读回放打分（P2-1 仿真对比数据源）+ 种子化全链路仿真（撮合/席位/时间常数走真实引擎，人工环节显式假设表采样）+ CLI `python -m fde_api.dispatch.simulator`（非沙箱库拒绝执行）。报告工件 `docs/dispatch-sim-r9-seed42.json`（H2/H3 内测/仿真口径，假设全量回显）。
- 测试：`test_dispatch_p2_r9_p24.py` 10 例 + `test_dispatch_p1_r9_sim.py` 4 例；r1–r8 回归全绿。口径：**85 业务表**（口径修订：不含 alembic_version）/ 15 rev / head `c5d7e9f1a3b7`（零迁移）/ 路由 228 / ENTRIES 68 / 服务端 1448 通过 / 桌面 660。轮次报告 `docs/goal-r9-派单引擎.md`；台账第二十一节。

## [未发布] — goal-r8 派单收口轮（2026-10-31）

### 派单引擎收口——开池四道闸全绿 + §八终止判定对照（零迁移）

- **C10 新人保护期**（§6.5）：撮合 Stage A 新增「前 5 单只推同城」——完成单数低于 `newcomer_protection_orders` 的候选强制非同城出局（推送范围收紧非资格淘汰），A5 明细带 `newcomer_city_only` 释明标记。
- **B1 防骚扰**（规则表 B1）：同包更早轮次拒过的候选本轮不再**主动推送**，与负面清单 #6「不因拒单限制接单机会」正交并存（本人仍可经 claim 主动抢）；stage_a 契约新增 `B1` 行；同步修正 r5 初版混淆两语义的测试。
- **§4.7 扩圈半径自动推进**：重派发布时 `redispatch_radius_km` 按 25→50→100→0 自动降档。
- **闸④覆盖率出具**：商业模块关键路径（报价/收款/合同/门禁/派单撮合结算）**84.9% ≥ 60%**（分母 2,637 语句），宽口径 71%——开池四道闸**全绿**。
- **收口报告**：`docs/goal-r8-派单引擎收口.md`——§八终止判定逐条对照（1/3/4/5/6/7/8 达成；2、3 带明示例外：P2-4 未立项、H2/H3 待真实数据）+ 附录 B 待签字清单（B-①②③④ + 留注①–㉒ + P2-2）+ 附录 A 修订建议（表 86/15 rev/路由 228/ENTRIES 68 重锚 + 新增冲突 A-⑧–⑪）。
- 测试：`test_dispatch_closeout_r8.py` 3 例；r1–r7 回归 94 例全绿。口径：86 表 / 15 rev / head `c5d7e9f1a3b7`（零迁移）。

## [未发布] — goal-r7 派单引擎轮（2026-10-31）

### 派单引擎 P2 批次（对照派单设计文档 v1.0 §8.5：P2-1/P2-3/P2-6；迁移 `c5d7e9f1a3b7`）

- **P2-1 桌面派单页簇**：`desktop/src/renderer/src/dispatch/` 三页——派单池（§9.2 白名单只读视图 + 详情展开 + 席位金额显示义务，响应体不含报价/收款明细字段断言）、能力档案与产能看板（四域分=晋级评定维度展示、在途/上限负载条）、权重与规则版本（只读 + 版本取值对照，仿真对比二期=留注⑳）；nav 全角色入口（交付方看被授权包，平台侧看全量），hash 路由 `#dispatch[/(pool|profiles|rules)]`；服务端支撑路由 GET `/dispatch/profiles`、`/dispatch/rules`（平台侧，ENTRIES +2）。
- **P2-3**：`projects.business_line` CHECK 放行 `'FDE_DISPATCH'`（§11.1 预留路径；写入入口随派单立项后续轮启用；存量数据零变化）。
- **P2-6**：`dispatch_cities.json` 扩字段钉子（subsidy_scheme 选填 + metro_group 必备断言——schema r4 已含，本轮补 P2-6 语义钉）。
- **P2-2（Project.status 枚举扩展）**：设计/规则表/BP 均未给出目标状态集——**不发明，待拍板**（台账第十九节留注）。
- 测试：服务端 `test_dispatch_p2_r7.py` 4 例 + 桌面 `dispatch-page.test.tsx` 6 例；r1–r6 回归 87 例全绿。
- 口径（goal-r7 实测）：86 表、迁移头 `c5d7e9f1a3b7`（15 revision）、路由 228（+2）、ENTRIES 68（+2）、桌面 660。轮次报告 `docs/goal-r7-派单引擎.md`；台账第十九节。

## [未发布] — goal-r6 派单引擎轮（2026-10-31）

### 派单引擎 P1 收官——§8.4 七项全过 + §8.1 八表齐（迁移 `b2c4d6e8f1a3`）

- **P1-6 报价归属**：`quotes.owner_user_id`（nullable FK users SET NULL + 索引；存量不回填=平台侧台账报价语义），创建即落 owner，归属过滤用例。
- **P1-7 留存策略**：`dispatch/maintenance.py` 留存扫描（撮合流水/评分 3 年、涉税 10 年——**报告只读不删档**，删除须人工合规审批，留注⑰）+ 维护作业 `dispatch.maintenance`（24h 节流）挂 `cli.scheduler` 主循环经 outbox 投递、handler 注册沿 research.export 模式；超时释放（r4 的 expire_stale_offers）一并挂入。
- **disputes 表**（§8.1 第 8 张，§6.6/§7.5）：L0 机器对账（逐包逐键比对结算应计 vs Payment 实收，差异>±¥1 自动草稿、幂等）+ L1 人工打开（48h 人工答复 SLA 字段、¥50,000 上限 422 走 L2）+ 人工裁决（**处罚类动作 100% 人工**，resolution 只能由平台侧写入）+ L0 对账单/依据只存 source_uri 指针 + snapshot_hash 锚定当时版本。
- 测试：`server/tests/test_dispatch_p1_r6.py` 8 例；r1–r5 全量回归 87 例全绿；ruff/mypy 无新错。
- 口径（goal-r6 实测）：86 表、迁移头 `b2c4d6e8f1a3`（14 revision）、路由 226、ENTRIES 66。轮次报告 `docs/goal-r6-派单引擎.md`；台账第十八节。

## [未发布] — goal-r5 派单引擎轮（2026-10-31）

### 派单引擎 P1-2 撮合核心（对照派单设计文档 v1.0 §4/§5 + 规则表 A-6，零迁移）

- **撮合核心**（§4.1–§4.8）：`dispatch/matching.py` + `dispatch/scoring.py`——Stage A 五资格门（等级/模块/行业/负载自动算上限/到场围栏）硬过滤出局不降权；场景裁决三选一：到场型字典序 (geo_tier, -level, -industry, -sla)、远程型加权（权重取 active 规则版本快照，无版本 → 422 `rule_version_required`=§11.1 降级态人工排序）、到场无候选场景 C 不自动派（事件留痕含淘汰明细）；§4.5 `required_level` 由 Quote 系数推导落库 + 发布前人工覆盖必填 reason 留痕；§4.7 扩圈链 geo_tier（同城/同省/邻接都市圈/全国，全国仅旗舰档）；§4.8 Top3 + `match_breakdown` 释明契约（stage_a 五门明细/stage_b/rank/explanation，对被派方展示）。
- **负面清单 A-6 七条逐条反例**（§8.8 开池四道闸之闸③全绿）：软画像零字段 schema 断言 / 排序签名无历史参数+同分不同历史同分 / 全包无轨迹语义静态检查 / 到场型字典序（同城弱者胜同省强者）+ 加权地理仅三档 / settlements 零工时扣减静态检查 / 被拒者下一轮仍可入选 / 全包零货运语义。
- **P1-4 options 枚举**：席位分配 / 场景类型 / 匹配模式 / 拒单原因四组随 /workbench/options 下发。
- 路由 +2（POST packages/{id}/match、packages/{id}/required-level），ENTRIES +2。
- 测试：`server/tests/test_dispatch_p1_r5.py` 12 例；全量 CI 门禁出具；桌面零改动。
- 口径（goal-r5 实测，rebase 到 goal-d1 合并态后）：84 表、13 revision / head `a7f3c1e9d5b2`（本轮零迁移）、路由 226（+2）、ENTRIES 66（+2）。轮次报告 `docs/goal-r5-派单引擎.md`；台账第十七节。

## [未发布] — goal-r4 派单引擎轮（2026-10-31）

### 派单引擎 P1 首批（对照派单设计文档 v1.0 §8.4：P1-1/P1-3/P1-5，零迁移）

- **P1-1 offer_service**（§6.2/§6.3/§6.7）：`dispatch/offer_service.py`——§6.3 乐观锁显式版本比对先行（冲突 409 `stale_version`，禁分布式锁）；同轮互斥（409 `offer_already_accepted`，包行 FOR UPDATE 串行化）+ 落选者自动 expired；claim 15 分钟确认窗 / assign 包响应窗超时批量释放（`expire_stale_offers`）；§6.7 拒单权（原因枚举 档期冲突/能力不匹配/距离/其他 只进 OperationEvent 留痕不进任何分值，**永不因配额拒绝拒单**——负面清单 A-6 #6 防护）；全拒后包 rejected=重派入口；§9.3 交接复用 `handover_accepted_member`（leader 为 actor）。路由 +4（指派发 offer / 接单 / 拒单 / 抢单登记），api_catalog ENTRIES 同步 +4。
- **P1-3 一致性测试**：api_catalog 每条 ENTRIES 逐条在 url_map 可解析（防目录漂移）+ dispatch 每条路由逐条在册（防脱册）——双向钉死。
- **P1-5 seeds 三处**：`gates.json` 加 `applicable_industries`（null=全行业通用；历史迁移回填哈希常量冻结不动，实时哈希由 `_gates_file_hash()` 现算）+ `dispatch_cities.json`（§12 六城建议名单，`claim_enabled` 全 false=§11.1 降级态）+ `acceptance_metrics.json`（BP §11 闸门指标投影）。
- **§6.4/C9 开闸评估**：`dispatch/cities.py`——claim_gate_status 三条件可解释明细（供给=active 档案 / 需求=近 90 天 published 包 / 拒单率<40% / 公示=规则版本存在为代理，留注⑨）+ 种子城市开关 AND；未开闸 403 `claim_closed`。
- 测试：`server/tests/test_dispatch_p1_r4.py` 14 例。全量 1386 passed + 6 skipped；桌面 654 与 typecheck 零改动全绿。
- 口径（goal-r4 实测）：83 表、迁移头 `f4b8c2d6e3a1`（12 revision，零迁移）、路由 224（+4）、ENTRIES 64（+4）。轮次报告 `docs/goal-r4-派单引擎.md`；台账第十六节。

## [未发布] — goal-r3 派单引擎轮（2026-10-31）

### 派单引擎 P0 簇②收尾——P0 8 项全落地（对照派单设计文档 v1.0 §8.3：P0-1/P0-2 + §9.5）

- **P0-1 交付包服务层**（§2.2/§2.3/§2.5）：`dispatch/packages.py`——canonical_json（键字典序/UTF-8 原样/Decimal→str/null/模块先排序）+ sha256 快照**发布时算一次即冻结**（改 solution/quote 不回写；撤回/拒绝/过期后重发 = dispatch_round+1 + 新编码 + 新哈希，版本对 Unique(project_id, round)）；§2.5 八态状态机通用迁移表（每次迁移写 OperationEvent）+ withdraw 的「本轮进行中 offer」防御守卫；发布前置=报价 finalized（422）；`PKG-{项目码尾段}-{轮次}` 编码；§9.3 接单交接以项目管理位（leader）为 actor 复用 `add_project_member(member)`（接单人本人交接前无 can_manage——留注⑧），幂等 + stale_version 重试。
- **P0-2 package_access 第三语义**（§9.1/§9.2）：`package_access` 表（package×user×role 三元组唯一，lead/seller/delivery/audit，可撤销）+ `dispatch/access.py`（无授权 404 不泄露存在性；admin 平台域放行）+ 交付包 API 字段白名单 12 项 + 交付方席位 40% 金额（发布时物化冻结到 `delivery_seat_amount`——禁 join quotes 的代价，留注⑥）+ `dispatch/routes.py` 6 路由（守卫路由层前置；管理动作平台侧 403；接单=平台侧或被指派人本人+delivery 授权双门槛，冒名 403）。api_catalog ENTRIES +6。
- **§9.5 隔离测试基线四条全绿**（开池四道闸之闸①）：跨主体访问 100% 拒绝（4 路由参数化 403/404）；响应体字段断言（键集精确等值、报价/收款/客户真名字段零出现）；静态检查（dispatch 读路径源级禁 Quote/Payment/Contract 引用、全包禁裸 `session.query(`）；渗透用例（越权接单 403、快照篡改无写入口 405、撤销授权重放 404 + 显式 re-grant 才复活）。
- 测试：新增 `server/tests/test_dispatch_p0_r3.py` 15 例；迁移 `f4b8c2d6e3a1`。全量 1372 passed + 6 skipped；桌面 654 与 typecheck 零改动全绿。
- 口径（goal-r3 实测）：83 表、迁移头 `f4b8c2d6e3a1`（12 revision）、路由 218（+6）、ENTRIES 60（+6）。轮次报告 `docs/goal-r3-派单引擎.md`；台账第十五节。

## [未发布] — goal-r2 派单引擎轮（2026-10-31）

### 派单引擎 P0 簇②表建设（对照派单设计文档 v1.0 §8.3：P0-3/P0-4/P0-7/P0-8）

- **P0-3 供给池档案**（§3.2/§3.3）：`fde_profiles`（一人一档：level 标量 L1–L4 + 四大子能力域独立评分轴 + 申报制标签 + 城市围栏 + 产能双列）+ `fde_level_evidence`（等级判定证据链：核验人/时刻/客观计数快照/依据单据只存 source_uri+sha256 指针）+ `dispatch/profiles.py`（L1–L4 晋级判据可复算查询——独立交付/复购/带教/四域短板下限，判据不足 422 `level_evidence_insufficient`，全过写证据链 + 更新档案 + `fde_level_promoted` 审计事件）。
- **P0-4 分成落库**（§7.2/§7.4）：`payments` 只加 `acceptance_passed_at` 一列（唯一约束不动、D+7/15/30/60 催款读时现算零改动）；`delivery_settlements` 席位级结算表（商务四席位 platform/region/city/delivery，与交付包执行四席位不同名不同义）+ `dispatch/settlements.py`（四席位 35/5/20/40、冷启动同城前 3 单 40/5/15/40、平台吸收舍入尾差保证 Σ=实收基数；劳务报酬**累计预扣法**（率表集中一处待法务确认）；状态机 draft→accrued→payable→paid/disputed，accrued 双条件=实收+G8 过门，payable 发票前置 422，paid 凭证指针）。双钩子：收款实收回填 upsert 结算草稿（无交付包项目纯 no-op）；G8 过门打标验收时刻并推进计提（晚到尾款收款即补，幂等）。
- **P0-7 配置常数**（§6.2）：`system_configuration` 增只读 `dispatch_constants` 节（时间常数 9 项 + Top-N + Stage B 权重 + 等级映射分 + 席位份额/冷启动 + 新人保护 + 拒单权，MappingProxyType 源级只读）——不进 PUBLIC_FIELDS（PUT 可写集精确等值校验天然拒改），实现代码唯一引用源，禁散落硬编码。
- **P0-8 规则版本**（§6.2/规则表 B9）：`dispatch_rule_versions` + `dispatch/rules.py`（30 天公示窗强制：生效日 < 发布日+30 天 → 422 `notice_window_required`；到点 published→active、原 active→retired 至多一个 active；快照必备节校验 admin-only；版本切换后旧 offer 的 `match_breakdown.rule_version` 永指当时版本）。
- **schema 调整**：`projects.enterprise_code` 全局唯一约束放宽为普通索引（派单 §3.3 复购判据要求同企业 ≥2 项目可表达；代号红线不动，三段两枚「·」格式校验保留——详见轮次报告留注③）。
- 测试：新增 `server/tests/test_dispatch_p0_r2.py`（12 例：L1/L2 证据链正反例、7 里程碑×四席位+累计预扣链、冷启动、状态机、G8 过门 API 全链路含晚到尾款补计提、配置只读断言、规则版本公示窗/角色/旧 offer 不回写）；`tests/conftest.py` 每用例清理序补派单六模型（FK 安全序）。
- 口径（goal-r2 实测）：82 张表、迁移头 `e3a7c5d9f2b8`（11 revision）、pytest 1357 passed + 6 skipped、桌面 654 用例零改动全绿。轮次报告 `docs/goal-r2-派单引擎.md`；台账新增第十四节。

## [未发布] — goal-r1 派单引擎轮（2026-10-31）

### 派单引擎 P0 双闸门（对照派单设计文档 v1.0 §8.3）

- **P0-5 门禁验收分离**（§9.4，§8.8 开池四道闸之二）：`gates` 加 `submitted_by_user_id` / `decided_by_user_id` / `is_delivery_party` 三列（迁移 `d2f6b4c8a1e9`）；`decide_gate` 双 403 防线——① 拍板人=该门禁证据执行人 → `gate_decider_conflict`（代码强制、先于其余业务校验，不可绕过）；② 交付方执行的 G8/G9 非 admin 拍板 → `gate_decider_role_required`（§11.3 方案①过渡口径）。单租户时代「同一用户提交+拍板」从 200 变 403，是刻意的硬闸门。
- **P0-6 events 白名单**（§2.5 坑 1）：`projects/events.py` 注册 `delivery_package` / `dispatch_offer` 两类 OperationEvent 目标（offer 的 project_id 经交付包反查）；为此按 §8.2 DDL 级约束先行落 `server/src/fde_api/dispatch/` 包两张骨架表（`delivery_packages`：8 态派单状态机 + `Unique(package_code)` + `Unique(project_id, dispatch_round)` + 扩圈半径 Check(25/50/100/0=全城哨兵)；`dispatch_offers`：`Unique(package_id, dispatch_round, candidate_user_id)` + 6 态 Check + VersionedMixin 乐观锁位 + `match_breakdown` JSON）——**服务逻辑零预埋**，发布/快照/匹配随 P0-1/P1 轮落位。
- 测试：新增 `server/tests/test_dispatch_p0.py`（6 例：两类事件目标写入、执行人自拍 403、交付方 G8 平台拍板、服务层防绕过、乐观锁位）；`test_gates_api.py`（5 例）与两个冒烟脚本改双拍板人（执行人=lead、拍板人=admin），门禁冒烟加「执行人拍自己的门 403」钉子。
- 口径（goal-r1 实测）：78 张表、迁移头 `d2f6b4c8a1e9`（10 revision）、pytest 1345 passed + 6 skipped、桌面 654 用例零改动全绿。轮次报告 `docs/goal-r1-派单引擎.md`；台账新增第十三节。

## [未发布] — goal-r3 技能循环（2026-10-30）

### 仓库健康巡检（G10）

- dynamic-workflows 编排只读巡检：**4 个只读子代理并行**（测试覆盖地图新鲜度 / docs 与代码漂移 / 依赖与 TODO / 台账逐节对账）→ **独立复核员**逐条复核 → 结构化报告。43 条原始发现全部坐实（0 驳回 0 存疑），**P1=0 / P2=14 / P3=29**。全程零变更——落盘走本 PR。
- 新增 `docs/仓库健康巡检-G10.md`：四面逐条发现（每条带 file:line 证据与复核状态）+ 下一批 backlog 三批建议（文档新鲜度批 / 依赖卫生批 / 功能欠账批，优先级逐条写明）。
- 关键坐实项：覆盖地图计数漂移 948→1330 collected（桌面 496→512，且 496/api-ipc(7) 写作时即不准）；「SES 未建」两处失效（G9 已预建默认关闭）；变量与密钥缺 8 个 FDE_SES_*；权限矩阵缺 mailing/SNS 例外鉴权行；**ruff/mypy/pre-commit 未入 lock，CI 门禁裸装最新**；台账对账 24 条中 5 条确认已完成、19 条仍待办（含 4 条 P2：research 三态 UI、PATCH-confirm 分叉、analyzing 对账、README 初始化节）。
- 随本 PR 修正自家文档两处（巡检发现）：`docs/SES发信模块-G9.md` §五闸门顺序归因（发信域约束在 service 前置，不在 decide_send）与 §八测试分桶（9+5+12+1=27）。
- 台账新增第十二节（backlog 三批推进）。

### SES 发信模块预建（G9｜WP-E）

- 新增 `server/src/fde_api/mailing/`：**默认整体关闭**（`FDE_SES_ENABLED=false` 时发送路径落 `drop_disabled`、SNS 回调端点一律 403，默认部署零行为影响、零 AWS 依赖——boto3 延迟导入，未启用时不 import AWS 栈）。SES 生产批复下来**只需改配置启用**，不改代码。
- 发送路径 `send_email`（service 函数，**不设 HTTP 路由**——避免未批复时出现可打的发信口）：闸门顺序固定 = 开关 → 发信域约束 → 幂等键 → 收件人抑制 → 当日限额（只数 UTC 当日）→ 打 SESv2；throttle 记事件并返 503（可重试）、拒收返 502（不可重试），失败不占发送台账。
- SNS 回调端点 `POST /api/v1/mailing/sns/events`：**签名即鉴权**（SNS 带不了工作台 JWT）——校验 Signature v1（RSA-SHA256，字段序按 AWS 固定顺序）+ `SigningCertURL` 限 `sns.*.amazonaws.com`（校验不过则**不发起任何外联**）+ `SubscribeURL` 同域限制 + `TopicArn` 白名单；退信/投诉只落地址 + 分类 + 通知 sha256 指纹，**不落通知原文**。
- 新增两表（迁移 `a9c3f1d8e2b4`）：`mailing_sends`（幂等键唯一）、`mailing_events`（`event_key` 唯一——SNS 是 at-least-once 投递，重放不重复计）。bounce/complaint = 地址级死刑（进抑制名单），delivery 不影响地址。
- 发信域口径落到配置校验器：FROM 必须落在 `FDE_SES_SEND_SUBDOMAIN` 子域内，主域 `somwyn.com` 启动即失败（`ses_sender_domain_forbidden`）。DKIM/SPF/DMARC 写 `docs/SES发信模块-G9.md` 不写死代码——**子域**加 SPF，**主域 SPF 不加 SES include**（否则扩大主域邮件面）。
- SNS 主题策略须带 `aws:SourceArn`（配置集 ARN）+ `aws:SourceAccount`——缺 `SourceArn` 即 confused-deputy 洞（任账号 SES 都能往我们主题灌事件）。AWS 凭证走 boto3 默认凭证链，不配进本模块、不进仓库。
- 新增 `server/tests/test_mailing_ses.py`（27 例，**零真实邮件**）：假客户端 + botocore Stubber + 自签证书验签；覆盖闸门顺序、bounce/complaint 抑制、幂等重放、坏签名/错主题/非法 JSON 拒绝、text/plain 报文解析、配置校验器。
- 依赖：`boto3>=1.36,<2`（pyproject + `requirements.lock` 钉 1.43.122/botocore 1.43.122/s3transfer 0.19.3）。

### 后台作业死亡后对账重排队（台账 §八 第 1 条落地，2026-10-30 晚）

- 问题：worker 被杀（OOM/部署/重启）时，它从 redis 队列弹走的作业 id 随进程一起消失——outbox 事件已 `dispatched`（派发器不再看它），`BackgroundJob.max_attempts`/`available_at`/`locked_until` 无人消费，于是作业永远停在 `running`，业务行（指引分析 `analyzing`、会话 turn `running`）永远停在中间态，前端每 2 秒轮询到天荒地老，唯一解法是手工 `RPUSH fde-jobs <id>`。这正是 10-30 登录事故里那笔孤儿作业的成因。
- 修复一（`jobs/worker.py`）：`run_job` 把「认领 + 执行 + 落终态」从**一个事务**拆成三段——认领（`status=running` + 租约 + `attempts+1`）先单独提交，执行期间由守护线程**续租**（默认 60s 一次，租约 5min），终态再单独写回。三个后果：① 在跑的作业对其他进程**可见**（此前全程只有 pending，对账无从分辨「有人在做」与「做的人死了」）；② 行锁只存在于认领那几毫秒，不再被 handler 全程占着（长任务钉着连接正是 10-30 锁雪崩的形状）；③ 租约过期从此是**死亡信号**而非「慢任务」信号。返回语义（not_found / already_terminal / leased / no_handler / failed / succeeded）保持不变。
- 修复二（`jobs/reconcile.py` 新增）：对账扫描捞两种无主作业——① `running` 且租约已过期（worker 死了）；② `pending`/`queued` 且超过 5 分钟无人认领（队列项丢了）。捞到之后：**可恢复类型重排队**（受 `max_attempts` 与 `available_at` 约束，入队前先提交库事务，队列项丢失下一轮按宽限期再捞），否则**落 failed** 并调用业务行收尾钩子，把业务行推到终态（前端停止轮询，用户看到「进程中断，请重试」）。
- 可恢复性按类型显式登记（不默认重跑）：`project.presurvey.analyze`/`ai.chat`/`ai.execute`/`file.scan`/`file.preview`/`document.generate`/`research.export` 可重排队——它们的 handler 都已跳过终态业务行，重跑不会覆盖已有结论；**`automation.execute` 不可重跑**（有对外副作用：发信、MCP 调用），死亡即落 failed 交人工重触发。
- 业务行收尾钩子（`jobs/handlers.py` 注册表 + 四处实现）：指引分析 → `analysis_worker_lost`；AI 会话 turn → `failed`（卡住的 turn 会让整个会话永久 `chat_busy`）；调研导出 → `failed`；自动化 run → `failed`。终态业务行（`ready`/`completed`/`succeeded`）一律不动——对账不许覆盖已有结果。
- 接线：worker 循环每 60s 扫一次（扫不出东西时零 DB 写）；另给运维留了手工口子 `flask reconcile-jobs`（容器被杀后可立即补投，不必等下一个周期）。
- 回归钉子：`tests/test_job_reconcile.py` 新增 15 例——租约过期重排队 / 活租约不动 / **被活 worker 行锁占住的作业被跳过（`FOR UPDATE SKIP LOCKED`）** / 孤儿 pending 重排队 / 新鲜 pending 不动 / 重排队后不热循环 / 次数用尽落 failed / 不可恢复类型落 failed / 指引分析与会话 turn 的收尾与「终态不被覆盖」/ 端到端（孤儿作业经对账后真的跑完）/ **认领状态对其他会话可见** / **执行期租约被续期**。

### AI 工具循环锁泄漏修复（生产事故回补，2026-10-30 晚）

- 事故：worker 跑 AI 聊天时工具调用撞 DB 连接断线，`_run_tools` 兜底吞掉异常继续循环，但共享会话带着未决事务与 `users` 表行锁停在 idle-in-transaction 十余分钟；登录路径的 `FOR UPDATE` 全体排队，gunicorn 超时杀 worker 又留下新的半死连接，锁滚雪球致登录 500。
- 修复：`server/src/fde_api/control/ai_tool_loop.py` 两处——① `_run_tools` except 分支立即 `session.rollback()`，工具异常不再让会话持锁过夜；② 主循环每轮工具执行完也 `db_session.rollback()`——工具循环工具全只读，回滚零损失，却保证下一次 provider 调用（最长 `timeout_seconds` 300 秒、零 DB 流量）不会骑在一个仍持有行锁的 idle-in-transaction 连接上（事故里 13 分钟的持锁窗口正是这个形态）。
- 回归钉子：`tests/test_ai_tool_loop.py` 新增 1 例（`OperationalError` 抛出时 `db.session()` 返回的会话在 with 块内恰被 rollback 两次：崩溃处理器一次 + 主循环每轮清理一次；17 例全绿）。
- 运维侧另两笔（无代码）：`pg_terminate_backend` 清锁 + worker 重启解堵；孤儿 pending 作业（outbox 已 dispatched、redis 队列项随重启丢失）手工 `RPUSH fde-jobs <id>` 补投。关联既有待办：台账 §八 第 1 条（进程死亡后无对账重排队）——已由本文件上一节的「后台作业死亡后对账重排队」落地，手工补投不再是唯一解法。

### 跨库只读验证脚本固化（G8）

- 新增 `scripts/verify/`（sql-queries 方法）：`run-verify.sh` + `verify-twenty-persons.sql` + `verify-n8n-executions.sql`——Twenty persons 总数/新增窗口/ICP 分布/去重命中，n8n 最近执行状态与耗时。连接参数全走环境变量（容器名/用户/库名，无口令：psql 在 db 容器内走本地 socket，脚本不读 .env）；每个会话显式 `BEGIN; SET TRANSACTION READ ONLY; … ROLLBACK;`；SQL 经 stdin 进容器（中文不走 argv）；输出仅计数不含客户明细。
- 口径：ICP 从笔记标题「冷邮件草稿 (ICP N)」提取每人最高分（≥70 培育 / 55–69 留档双层）；去重命中 = 同主邮箱挂多人（期望 0）。
- 宿主实跑一次并记录计数摘要到 `docs/验证脚本-G8.md`：persons 75（7d 新增 64，ICP 记分 9 全在 55–69 留档档）、重复邮箱 0（去重有效）、公共管道 4 成功（均值 27s）、QFhunterFeed01 2 成 3 败（运维信号，仅记录）。

### 意图差距审计（G7）

- 新增 `docs/意图差距审计-G7.md`：以 G2 七份意图文档 + AGENTS.md 红线为基线，逐边界核对代码执行点。**B1–B4 零差距**——门禁证据只收指针+64 位 hex sha256（`gate_service.py:520-548` + `workbench/models.py:544-547`，无 blob、无上传路由）；confirm 只能 canManage（`service.py:174-180` + `api_catalog` 零 guidance 条目，AI 无代拍板面）；bridge-poll 唯一进程出口是两个 openfde 只读子命令（`bridge-poll.mjs:68,101,110`，无写相 CLI、真相层零写面）；.env 不入 VCS 有可校验闭环（`.gitignore:1-5` + 全树仅两个 example 被跟踪 + gitleaks PASS 盲区规则）。
- F1 [P2→已处置]：「origin 永不 push」原本只有文档约束、无本地强制——本机已加 `git remote set-url --push origin FORBIDDEN-origin-is-upstream-use-fork`（push 必失败已实测，fetch 不变）；每台新克隆须重复，建议进 README 初始化节（台账十.1）。
- F2 [P3→已修]：G4 重写 `jobs.py` 使意图文档 4 处行号引用漂移、步骤 4 语义未反映自动重试——《系统意图-关键流程》《系统意图-自动化面》已同步更新。
- 台账新增第十节。

### 真实浏览器 UI 回归 harness（G6）

- 新增 `desktop/gui-harness/`：纯浏览器驱动 renderer 的回归 harness。dev-only Vite 配置（端口 5199）注入 `window.fde` 桥 shim（登录/刷新/`ApiResponse` 信封、deviceLabel→device_label 转换、401 刷新重试；`app.version` 返回裸字符串——三处契约此前只有 Electron 真机能验证），同源 `/api` 代理到 127.0.0.1:8010（浏览器有 CORS 而 Electron IPC 没有），并给生产 CSP 打 dev 补丁（`connect-src 'self'`、`style-src 'unsafe-inline'` 供 Vite 开发样式）。不引新依赖，不进打包产物。
- 新增 `desktop/gui-harness/regression.mjs`：仓库自带 playwright-core + 已装 Chromium 驱动两条链路 11 个断言点——①指引链：登录→项目→查看预调研分析→**只读 draft 态直接出现「确认并用于项目指引」按钮（R11 事故防线，浏览器实测通过）**→弹窗内编辑；②集成桥页：侧栏进入、状态文案、「立即采集」按钮在浏览器 harness 下被平台守卫拦为 `bridge_platform` 错误提示（与真机同代码路径）、采集反馈区可见；截图留本地（已 gitignore，含本机路径与项目代号）。
- 新增仓库技能 `.agents/skills/fde-gui-regression/SKILL.md`：harness 原理、启动/种子/运行命令、fixture 陷阱（enterprise_code 需两个「·」、module_keys 必须命中 ModuleCatalog）、断言口径与已知坑（hash 路由需点侧栏、Vite 单实例、中文经 `\uXXXX` 转义）。
- 回归报告 `docs/GUI回归-G6.md`：11/11 通过表、R11 防线结论、2 条 P3 finding（认领入口失败静默无提示——已记台账第九节；命名约定再次复核，与台账七.3 同源）。

### 代码评审门与回溯评审（G5）

- 新增 `docs/代码评审-G5.md`：PR #24 的参与者约定法评审报告（scope/dimensions/findings/coverage，含 9 条保留 finding 与 6 条驳斥成立的丢弃候选）、PR #17/#18 回溯评审、WP-B Serper 修复说明。
- 评审修复（随 PR #24 提交）：DSH 路径的裸 `JSONDecodeError`/`ControlServiceError` 逃出错误分类 → 结构化输出失败现在落 `ai_output_invalid`（可重试）/配置类不可重试，DSH 部署形态下重试能力不再静默失效；重试耗尽文案只在终态错误可重试时才劝「请重新发起分析」；存储对象缺失归入专用码 `source_object_missing`；限流/超时类瞬时错误重试前退避（契约失败不退避）；本地 DOCX 解析失败按确定性改为不可重试（存储读取 `OSError` 仍可重试，供应商侧提取失败不变）；重复投递不再对已终态分析二次调用 AI；每次尝试用独立请求号（上游去重不会挫败重试）；`python-docx` 声明下限提到 `>=1.2`（样本生成器用了 1.2.0 才有的 `add_comment`）。
- 新增回归钉子：重试语义 +7 例（请求号独立/退避双向/不可重试终态文案/存储缺失分类/终态守卫/任务仍为绿）、DSH 分类 +2 例。
- 回溯评审 PR #17/#18 发现 3 条（台账第七节）：PATCH 成功而 confirm 失败后前端版本与库态分叉致重试必 409（P2）、审核面板内无旧版源警示、认领命名约定无服务端保障。
- WP-B 修复交付（获客引擎 `AI_Find_Customer`，独立分支 `fix/serper-region-iso-codes`，commit 2c51e1a；其 origin 为上游仓库，不推送）：`_REGION_GEO` 由表自身 `gl` 值反查建 ISO-2 索引，ISO 码（US/CA/DE）不再落空致 Serper maps 400；键归一（下划线/连字符→空格）；命中失败打 warning（此前静默降级为全局搜索正是 400 无人察觉的原因）；引擎 +6 例，全量失败集合与改前逐条一致。

### 指引契约失败自动重试加固 + 对抗 DOCX 样本（G4）

- `server/src/fde_api/guidance/jobs.py`：预调研分析任务内自动重试——`GUIDANCE_ANALYSIS_RETRY_LIMIT = 1`（不含首次，测试钉死）。可重试失败（retryable=True 的 KimiError / GuidanceContractError 契约违反，即 MiniMax 概率性不守 JSON 合同的已知现象）先自动重试一次，仍失败才落 failed，failure_message 携带「已自动重试 N 次仍失败」的用户可见提示；不可重试（如 ai_service_not_configured）一次即败不消耗额度；source_missing 在构造 AI 客户端前拦截（零 AI 调用）；新增兜底分类 analysis_unexpected_error——未预期异常不再让分析卡在 analyzing（前端会无限轮询），且消息不携带异常串。每次尝试重新打开文件流。
- 对抗 DOCX 样本生成器 `server/tests/fixtures/presurvey/generate_fixtures.py`（9 种：空文档/空表格/合并单元格/批注/异常样式/缺失章节/超长段落/嵌套表格/非 ZIP 字节流；python-docx 1.2 程序化构建 + document.xml 最小注入），session 级构建到临时目录，二进制不入 git。
- 新增 `tests/test_guidance_adversarial_fixtures.py`（11 例）：两层解析（guidance 块抽取 / 本地全文提取 / Kimi 本地提取分类）对 9 样本的行为契约——畸形输入绝不崩溃、空内容失败为可分类错误（kimi_file_extract_failed retryable=True）、合并单元格全文层按 _tc 去重且块层按格位稳定引用、批注不泄漏进提取文本、异常样式不阻塞提取、嵌套表全文层递归可见（块层不可见，钉住两层差异）、超长段落整体提取。
- 新增 `tests/test_guidance_retry.py`（9 例）：重试语义钉子——契约失败重试一次后成功 / 耗尽后 failed 带 ai_output_invalid 与自动重试提示 / 调用次数恰为上限+1 / 不可重试一次即败 / 真实提取路径吃空表格样本落 kimi_file_extract_failed / source_missing 零 AI 调用 / 未预期异常落 analysis_unexpected_error 且消息无异常串 / 成功路径一遍 ready。
- conftest 清理清单补 `ProjectGuidanceAnalysis`/`ProjectPresurveySource`（此前测试库跨用例残留指引行会顶住 RESTRICT 外键清理）。

### 验收场景矩阵与缺口补测（G3）

- 新增 `docs/验收场景矩阵-G3.md`：指引链 / 集成桥手动采集 / SES 发信策略三链场景表（目标/起始/角色/分步/预期），每条映射钉住它的测试。
- 指引链补测 `desktop/tests/renderer/guidance-chain-scenarios.test.tsx`（8 例）：分析中→ready 自动开审进编辑态、failed 面板 role=alert 可见且无确认按钮、start() 失败 inline 可见、cancelled/queued/extracting 参数化占位展示、confirmed 卡片摘要 + `source_is_stale` 旧版重分析横幅（ProjectGuidanceCard 此前零测试）；集成桥链核对后无缺口（既有 13 例已覆盖全回路，platform 显式注入 win32/linux）。
- SES 策略先行 `server/src/fde_api/mailing/policy.py` + `server/tests/test_mailing_policy.py`（27 例）：四态分类（仅 throttle 可重试）、幂等闸门（同 message_id 判 duplicate 且先于限额/抑制）、每日限额（沙盒默认 10 可配）、总开关（未启用一律 drop_disabled）、发信域约束（仅配置子域，主域 somwyn.com 拒绝）、指数退避封顶——纯逻辑零 AWS 依赖，G9 在其上接客户端与 SNS 回调。
- 发现并记台账：cancelled 终态在审核面板仍显示「分析正在后台继续」占位（文案缺陷）；start() 失败提示不透传 failure_message 明细。

### 系统意图文档基线（G2）

- 新增 7 份意图文档（`docs/系统意图-*.md`，shipping-artifacts 方法，README 仍是部署唯一权威、交叉引用不复制）：架构与信任边界（根文档）、关键流程（预调研指引链/门禁/报价收款三链含鉴权点与 deny 例）、权限矩阵（三套角色体系 × 15 资源域）、变量与密钥（变量名×来源×轮换×风险，只写名不写值）、测试覆盖地图（现有 948+496+14 用例 / 建议 / 缺口三段）、定时任务（worker/scheduler/宿主 FDE-Bridge-Poll）、自动化面（AI 助手工具面/预调研管道/集成桥/任务中心，App 拥有副作用原则）。全部条目引用代码位置，作为 G7 意图比对基线。

### 内置手册与 UI 帮助 parity（PR #19）

- `help_manual.md` 补收「实操示例：证据文件怎么写（somwyn 样板）」整节与 G↔S 阶段映射（此前只在桌面端 HelpPage，help_fetch 检索不到）；新增双手册主题 parity 测试与 G↔S 映射与 `seeds/gates.json` 一致性测试，防两份手册再次分叉。

### 仓库级操作技能（G1）

- 固化 3 个仓库级 Agent 技能到 `.agents/skills/`（skill-creator 规范，随仓库分发）：
  - `fde-package-verify`：便携版打包全流程——electron-builder 产物 → asar sha256 → 中文 marker 字节验证（防控制台编码假阴性）→ 换新目录命名 r N+1 交付。
  - `fde-bridge-capture`：集成桥手动采集 runbook——`schtasks //Run`（Git Bash 双斜杠）或桌面「立即采集」按钮（同一代码路径）、`logs/bridge-poll.log` 验证到站、改 server 必须重建镜像、采集器只读纪律。
  - `fde-delivery-flow`：标准交付流检查单——分支 → push fork（永不 origin）→ PR → 4 CI 全绿 → 合并 → ff 本地 main → 删分支，每步验证点与常见事故对照。

## [未发布] — goal-r2 第二轮（2026-10-28）

安全口子、假绿灯与跨机口径一轮。**版本号未升**（按发布列车统一处理）。

### 安全（批次 G）

- **清除已入库的明文数据库口令**：备份脚本里的三条口令字面量（两条不同口令）已从工作树删除。凭据随 `2f90484` 入库，**视为已泄露，需人工轮换**（见交接清单）。
- **范围外备份管道移出仓库**：与 FDE 交付线无关的 n8n/Mautic/openoutfind 备份脚本迁至 `D:\test\AI外贸获客\scripts\`（副本 sha256 校验一致，仓库内可由 `git show 2f90484:scripts/backup-pipeline.sh` 恢复）。
- **集成桥读接口收敛门禁**：`GET /bridge/engagements`、`GET /bridge/status` 此前只要求登录（任意用户可枚举全部项目名与企业代号），现与写接口同级要求 `project_lead`。
- **登录限流键改为「用户名 + 来源 IP」复合键**：此前单个 IP 连错 5 次即可定向锁死任意用户名（含 admin）。Redis 不可用时记 WARNING（可观测），并可用 `FDE_LOGIN_RATE_FAIL_CLOSED=1` 切为 fail-closed。
- **秘密扫描线自证有效**：实测默认 gitleaks 规则对 `*_PASS=` 形态**整体漏报**（历史口令与随机探针同形态却一个抓一个不抓），新增 `.gitleaks.toml` 兜底规则与 `scripts/check-secret-scan.sh`（含 `--self-test` 哨兵自测）。

### 假绿灯（批次 H）

- **mypy 基线改计数法并纳入 tests**：旧实现按「文件+错误码+归一化消息」去重，实测 45 条基线条目掩盖了 181 次同类新增。
- **代号化检查不再吞错**：grep 退出码 1（无命中）与 ≥2（错误）区分；邮箱策略真正读取 `FDE_PSEUDONYM_EMAIL_POLICY`（缺省 fail）；黑名单提取 0 条即 FAIL；psql 失败不再当 0 行；`projects` 表 0 行即 FAIL（空库扫描等于没扫）。
- **CI 代号化 job 先迁移灌数再扫描**（原为空库扫描）。
- **冒烟脚本补真实断言**：auth 冒烟新增跨用户名隔离断言，commercial 冒烟种子管理员 try/finally 清理并断言归零。

### 跨机口径与运维（批次 I）

- pre-commit 三个钩子改走跨平台 node 入口（不再写死 Windows venv 路径）；README 更正 `.env` 模板来源与 venv 跨平台表述；操作手册路径参数化。
- compose 四服务统一 `restart: unless-stopped`；api healthcheck 改走 `/api/v1/health/ready`（真正校验依赖）；worker/scheduler 新增基于 Redis 心跳的 healthcheck（进程还在 ≠ 还在干活）。

### 打磨（批次 J）

- 业务枚举（价格档位 / 门禁五态 / C 分支 / SOW / 业务阶段）改由服务端 `GET /api/v1/workbench/options` 下发，前端保留本地兜底；存库值一律不变（旧中文标签数据照常可读）。
- 门禁汇总徽标改为按实际状态遍历（此前硬编码五态，服务端新状态会被静默丢弃）。
- 新增交付审计专用表 `document_delivery_records`（+ 迁移 `f3c8d2b7a1e5`），交付记录可按项目维度检索。
- C 分支触发档位收敛为单一常量；B 层分上下界都夹；扩展中心路由加角色门禁；预调研与调研导出的轮询失败对用户可见且失败后继续下一轮。
- **项目指引审核入口补缺**：指引卡片挂载时自动认领「已上传但尚未确认」的预调研源——此前分析/审核入口只在本次会话内上传后才出现，服务端（定时任务/历史会话）跑出的待审核指引在界面上没有任何入口；空状态文案同步提示审核入口。
- **指引审核弹窗只读态可确认**：确认按钮此前只在编辑模式渲染，用户从「查看预调研分析」进入的只读预览没有确认入口（得自己发现右上角「编辑」才能确认）；现在只读草稿底部直接显示「确认并用于项目指引」。

### 智能助手知识（help_fetch）

- 智能助手此前只拿到会话历史，「使用帮助」栏内容它一无所知（手册只在桌面前端渲染，服务端镜像里没有）。本轮把 `docs/工作台操作使用手册.md` 随 `server/` 源码烘进镜像（`fde_api/control/bundled/help_manual.md`），新增只读工具 `help_fetch`（按章节检索手册原文，带目录与分页），任意 AI 级别可用；对话入口注入工作台式 system prompt，引导「先查手册再作答」；新增公共 Skill `workbench-help`（`flask seed-public-skills` 灌入）。桌面「使用帮助」页同步注明智能助手内置同一份手册。

### 口径

- 服务端数据表 **73 → 74**（本轮新增 `document_delivery_records`）；迁移头 `e5b8a1c9d3f7` → `f3c8d2b7a1e5`。

## [v0.2.0] - 2026-10-26

交付流程与安全加固版本；桌面端与服务端版本号同步升至 `0.2.0`。

- 新增**门禁引擎 G1–G9**：pending → evidence → passed/failed 状态机（G9 支持 conditional_pass）；证据仅保存 `source_uri` 指针与 sha256 指纹，真实文件留在项目工作目录；claimed 与 accepted 分离。
- 新增**报价 / 收款（里程碑）/ 合同**商务看板与标准 FDE 项目模板派生。
- 项目工作台新增「门禁」「报价收款」页签；新增集成桥（本地 openfde / fdeops 工作目录的只读投影）与任务中心。
- 集成桥页新增「立即采集」按钮：桌面端一键触发宿主计划任务（与 4 小时周期同一代码路径），新快照到站自动刷新，无需等下一个采集窗口。
- 桌面端新增内嵌「使用帮助」：各模块操作说明、门禁 G1–G9 流程、实操示例与故障排查。
- 安全加固：登录连续失败限流（Redis 计数）、refresh token 轮换与改密即失效、API 容器非 root 运行、门禁证据哈希校验、CI 常驻 gitleaks 秘密扫描。
- 工程卫生：CI 并发取消与四 job 超时上限、pip/npm 缓存、全仓 LF 归一化、测试口令字面量收敛单点。
- README 按当前功能与 Docker Compose 部署路径重写，新增换机迁移清单。

## [v0.1.0] - 2026-09-28

首个开源源码版本。

- 提供 Electron 桌面端、Flask API、数据库迁移、后台 worker 与 scheduler 的源码。
- 提供项目、任务、调研、AI 机会、方案、交付文档、文件和管理员配置等工作台功能。
- 清理历史业务数据、客户资料、运行日志、访问凭据、对象存储文件和发布备份；仓库只保留通用示例与模板。
- 移除客户端自更新功能。升级需由部署者自行部署后端、执行迁移并重新打包客户端。
- 提供 MIT 许可证、安装部署说明、贡献指南和安全报告说明。

当前仅配置 macOS Apple Silicon（arm64）DMG 构建；没有 Windows 客户端。此版本是源码发布，不附带已签名、公证的安装包。公开部署前请更换首次登录密码和所有示例密钥，并阅读 README 的生产部署与安全说明。

本产品采用 vibe coding 方式开发；商用或处理真实数据前，应由部署者独立完成代码、安全、合规及业务适用性核验。
