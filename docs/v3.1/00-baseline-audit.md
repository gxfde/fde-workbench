# V3.1 P0-0 基线审计（00-baseline-audit）

- 审计日期：2026-11-07
- 审计基线：fork/main `65db88c53dab1bcdea24dd9d9ad4e212acd0fc24`（#196 T-B1 封包半；任务书自述基线 `7368094` 之后 1 个提交，差异仅 #196）
- 审计方式：隔离 worktree `D:/test/fde-wt-v31p0`（branch `feat/v31-p0-0-baseline-audit`，干净树），零业务代码修改
- 任务书：`docs/蔡工_FDE_Workbench_V3.1_智能交付自动化升级路线图与Goal实施任务书.md`（本 PR 一并入库）
- 配套报告：`00-data-model-map.md`（数据模型全图）、`00-test-baseline.md`（测试基线）、`00-gap-register.md`（复用/扩展/新建裁决台账）

## 1. git 状态（P0-0 清单第 1 项）

| 位置 | 状态 |
|---|---|
| 权威树 fork/main | `65db88c`（本审计基线） |
| 审计 worktree | `feat/v31-p0-0-baseline-audit` @ `65db88c`，工作区干净（除本报告新增文件与拷入的 `.env`/junction，均不入库） |
| 主树 `D:/test/fde-workbench` | on `main` @ `c05bb19`，**落后 fork/main 23 个提交**（按 AGENTS 纪律不 ff，属正常状态）；工作区有并发会话的未提交修改（`brand/caigong-fde/**`、4 个 `*.css`）与本任务书（原为未跟踪文件）——**未被本审计触碰、未被覆盖** |
| 活跃并发 worktree（零重叠注记） | `feat/tz1-host-proxy-contract`、`feat/host-zcode-channel`（T-Z1/P1-1 方向，另一会话在途）；`feat/eval-v11-landing` 等 docs 轮。本 P0-0 纯文档，零文件交集 |

历史台账口径（任务书 §2 所引"约 107 表/38 rev/315 路由/pytest 2116/vitest 927"）为**旧值**；本轮现测见 §4 与 `00-data-model-map.md`。

## 2. 任务书 §2 文件清单核验（P0-0 清单第 2 项）

25 项路径逐一核验，**24 项原路径命中，1 项路径修正**：

| 任务书路径 | 实况 |
|---|---|
| `transcripts/service.py`、`models.py`、`routes.py` | ✅ 存在（T-A9 立项产物：草稿区+正式纪要，详见 §6） |
| `desktop/.../transcripts/TranscriptDraftsPanel.tsx` | ✅ 458 行 |
| `agents/service.py`、`adapter.py`、`context.py`、`tools.py`、`models.py`、`receipt.py` | ✅ 存在（agents/ 共 15 文件，另有 `zcode_contract.py`、`signoff.py`、`pilot.py`、`quota.py`、`sandbox.py`、`seeds.py`、`artifact_summary.py`、`routes.py`） |
| `agents/zcode_contract.py` | ✅ 存在，171 行，**纯函数契约层（第 9 项专项结论见 §7）** |
| `desktop/.../AgentsConsole.tsx` | ⚠️ **实际路径 `desktop/src/renderer/src/agents/AgentsConsole.tsx`**（364 行，T-A8 交付） |
| `workflows/definition_service.py`、`executor.py`、`models.py`、`routes.py` | ✅ 存在（另有 `compiler.py` 317 行＝P0-3/P0-4 的直接先例） |
| `ontology/models.py`、`service.py`、`routes.py` | ✅ 存在（247/1879/217 行） |
| `projects/gate_service.py` | ✅ 1028 行，唯一门禁决策入口 |
| `control/ontology.py`、`mcp_gateway.py`、`access.py`、`ai_tool_loop.py` | ✅ 存在（职责重叠结论见 §8） |
| `background_jobs/`、`outbox_events/`、Worker/Scheduler | ✅ `jobs/` 模块（models/handlers/outbox/queue/worker/reconcile/admin_routes）+ `cli.py` scheduler 循环 |

任务书未列但 V3.1 相关的现存模块（后续阶段会用到）：`guidance/`（预调研结构化事实）、`meetings/`（内部评审会）、`solutions/`、`evidence/`、`handover/`（T-B1 结项交付包）、`dispatch/`、`metrics/`、`translator/`、`research/`（调研对象/表单）。

## 3. 口径现测（AGENTS「引用前现测」纪律）

| 口径 | 现测值 | 测量配方 |
|---|---|---|
| 业务表 | **109** | `__tablename__` 去重 grep；CI 钉 `docs/audit/v3-database-inventory.csv`（110 行=109 表+表头） |
| 迁移 | **39 revision 单链**，head `e5f1a7c3b9d4`（handover_packages） | revision 集 − down_revision 集（首版解析误报 4 heads 系 `down_revision: Union[...]` 类型注解形态所致，修正后单链无孤儿） |
| 蓝图路由 | **323** | `@[A-Za-z_0-9]+\.(route|get|post|patch|put|delete)(` 装饰器计数；CI 钉 `docs/audit/v3-route-inventory.csv`（324 行=323+表头） |
| api_catalog ENTRIES | **94** | awk 计数（AI 可调用精选面，≠全路由镜像） |
| mypy 基线 | **279 occurrences / 104 distinct** | `scripts/check-python-types.py` 官方闸，EXIT=0 |
| pytest / vitest | 见 `00-test-baseline.md`（本轮全量实测） | |

任务书 §2 的"107 表/38 rev/315 路由"为旧台账值：现差 = T-B1 三迁移（d7b2f8a4c1e6 transcript_drafts → b8e4d6f2a9c3 agent_artifacts 扩列 → e5f1a7c3b9d4 handover 两表）与 T-A8/T-B1 路由增量。**引用本报告数字为准。**

## 4. 运行数据（活库实测，P0-0 清单第 7 项）

活库：`fde-workbench-api-1` 容器内经 `FDE_DATABASE_URL` 直查，`alembic_version = e5f1a7c3b9d4`（与代码 head 一致，部署在位）。查询时间 2026-11-07。

| 表 | 行数 | 说明 |
|---|---|---|
| agent_runs | **0** | 无真实/演练 run |
| workflow_runs / workflow_definitions | **0 / 0** | 无模板无运行 |
| agent_artifacts / automation_approvals | **0 / 0** | 产物接受/撤回数无从统计 |
| ontology_change_sets / project_solutions / delivery_packages / handover_packages | 0 | — |
| transcript_drafts / interview_minutes | 0 | 转写通道尚无使用 |
| projects | 4 | `P1示例项目`(draft)、`somwyn`(active)、`qiflow`(active)、`GUI regression project`(draft) |
| project_tasks | 8 | — |
| gates | 18 | 2 项目×9 门：somwyn G1–G6 **passed**、G7–G9 pending；另一项目全 pending |
| project_guidance_analyses | 5 | 1 confirmed+ready、1 draft+ready、**3 failed（`ai_authentication_failed`×1、`ai_output_invalid`×2）**——唯一的真实 AI 失败分布 |
| project_evidence | 3 | 全部 `captured_from=bridge_sync:{run_id}`（集成桥通道） |
| ai_call_audits / seat_action_ledger | 1 / 0 | — |
| skill_definitions | 14（public+published） | `skill_used_chat` 事件 1 次 |

结论：**Agent/Workflow/测试/指标域全部无运行数据**（与任务书预判一致）；现存真实痕迹集中在门禁推进（G1–G6）、集成桥证据与预调研 AI 失败样本。P1-3 指标基线为 insufficient_data；§14 "实施前后同口径比较"须先建立采集，无数据不得写性能承诺。

## 5. 状态机与事件链（P0-0 清单第 5 项）

四条核心状态机（行号锚见 `00-data-model-map.md` §3）：

1. **AgentRun**（agents/models.py:67-71，7 值 CHECK）：`queued→running→{completed | succeeded_but_receipt_invalid | failed | timeout | budget_exceeded}`；失败族经 `retry_run` 新行同 idempotency_key（family≤3、指数退避）；卡死 `recover_run→failed(stuck_recovered)`；降级链 `fallback_level` L0–L3。产物复核仅 `reviewed` 布尔（T-B1 已加 reviewed_by/at；无 revoked 状态）。
2. **Workflow**：定义 `draft→published→archived`（发布快照 `workflow_definition_versions` 不可变；发布=admin-only）；运行 7 态含 `waiting_approval`（`paused` 声明未用）；节点 8 态；`hops` 熔断 MAX=8；人工审批复用 `automation_approvals`（`wfnode:` 键，拍板经任务中心回投 `workflow.run`）。
3. **Ontology ChangeSet**（ontology/service.py:871-1331）：`draft→in_review→{confirmed | rejected}`（`superseded` 保留未用）；`base_snapshot_sha256` 并发指纹闸 + 决策分离 403；确认＝单事务逐项物化全成全败。术语 `draft→confirmed→{superseded | merged}`。
4. **Gate**（gate_service.py）：`pending→evidence→{passed | conditional_pass | failed}`；清单项 `claim_status: null→claimed→accepted`；拍板 `expected_revision` CAS + 决策分离 + G8/G9 交付方限制；Agent 只能挂证据候选（task/workflow 两源），**没有任何路径让 AI 改门禁状态**——与任务书 §1.2-4 权限矩阵现状一致。

事件链：业务事件统一走 `projects/events.py::record_event`（`_TARGET_TYPES` 22 种目标类型闭集 + 敏感键脱敏 + 环路/不支持值防护）；治理事件走 control 层 `_event` 同构直落 `operation_events`（skill 治理等，避开 projects↔control 导入环）；异步派发经 `outbox_events`（pending→dispatched→completed/failed）→ `background_jobs`（12 个 job_type，`active_key` 单活闸）→ worker 租约/对账/失败钩子全链在位。

## 6. transcripts/ 现状（P0-1 的直接基座）

T-A9 已落地**通道层**而非抽取层（详见 gap-register P0-1 节）：

- `transcript_drafts`（草稿区，T+7 自动清理）：`draft→{promoted|expired|discarded}` 墓碑态、`content_sha256`、`redaction_entries`（复用 T-A2 企业名脱敏，疑似名同样替换）、`source_kind manual|asr`、客户端确认三元组；文件落独立根 `.fde-transcript-drafts`。
- `interview_minutes`（正式库）：唯一晋升路径 `promote_draft`（can_manage + 客户确认三元组强制）；`draft_id` 刻意无 FK（B#6 只持指针）。
- **无 AI 抽取**：transcripts 模块零 AI 调用；正文是无结构文本块，无时间戳/分段锚点（对照 V3.1 目标 `source_locator{type: transcript_segment, start_ms…}` 为全量缺口）。
- 结构化事实的现存最近邻是 `guidance/`（预调研 DOCX→Kimi 抽取→五分类+锚点校验+复核闸，`ai_schema.py`），其管线模式（outbox 任务、失败码阶梯、三道脱敏、确认闸）是 P0-1 应克隆的范式；但其锚点在现役 Kimi 腿收敛为单引用 `kimi-file:<version_id>`（文档级）。

## 7. zcode_contract.py 专项核验（P0-0 清单第 9 项）

**结论：任务书判断成立——纯 CLI 契约层，无任何执行能力。**

- 171 行，imports 仅 `json/collections.abc/dataclasses/pathlib/typing`；零 subprocess/socket/requests/DB。
- `build_cli_argv` 建模的真实 CLI 表面：`zcode -p <prompt> --json --cwd <cwd> [--mode <mode>] [--resume <sessionId>]`（`ZCODE_CLI_VERSION="0.17.1"`，钉 2026-11-07 真机实测）；docstring 明示真实 CLI **无 `run` 子命令、无 `--task`/`--events`**。
- `parse_json_summary/summary_to_events/JsonSummaryEventProvider`：单 JSON 汇总解析→仅 `cost`+`done` 两事件，不伪造 tool_call，不采集正文。
- 全仓无任何代码 spawn zcode 或连接宿主代理；`zcode_contract` 符号仅测试引用。
- **重要发现（P1-1 立项输入）**：`agents/adapter.py:99-113` 的 `spawn_argv` 仍建模**虚构的注册期契约**（`zcode run --task … --events ndjson`），与真实 0.17.1 CLI 相悖（adapter.py:93-98 TODO 自认）；`docker/sandbox/Dockerfile` 明确不装 zcode（编码 CLI 归宿主代理进程空间）→ 现役生产路径 `service.py:657` 的 spawn 段预期失败落 L2。另一会话在 `feat/host-zcode-channel`/`feat/tz1-host-proxy-contract` worktree 在途施工宿主通道——P1-1 开工前必须先对齐该线成果，避免平行重建。

## 8. control/ontology.py vs ontology/ 职责重叠（P0-0 清单第 6 项）

**结论：零代码级重叠，纯概念重叠；无死代码，但缺 ADR。**

- `control/ontology.py`（75 行）＝静态 `ONTOLOGY` 字典（`fde-business-ontology-2`：21 实体/24 关系/9 不变量），唯一消费方是 MCP 工具 `ontology_read`（mcp_gateway.py:112，原样返回）+ 一个测试；文件头 docstring（2026-11-03 T-O1）已声明"只读语义投影，治理已迁一等表"。
- `ontology/` 模块＝真实治理层（terms/aliases/relation_types/change_sets 四表 + 服务原语 + 路由），与 `control/ontology.py` 无共享符号、无导入关系。
- 任务书 §6-7 要求的 ADR（ADR-002-ontology-ownership）**尚不存在** → 登记入 gap-register P0-2 交付物（文档级，不改代码）。

## 9. api_catalog 与实际路由差异（P0-0 清单第 4 项）

- 全路由 323 vs catalog ENTRIES 94：**设计性差异非漂移**——catalog 是「AI 经 `api_execute` 可调用」的精选白名单（五元：描述/能力/参数/effect/risk），治理面/管理面/admin 面路由**有意不进** catalog（AGENTS 红线多轮钉子）。
- 一致性由 CI 双钉保证：`test_route_inventory_sync.py`（route CSV ↔ url_map 逐行对账，#174 事故后机械化）+ `test_catalog_*` 系列（effect/risk 不变量等）。
- V3.1 各阶段新路由按既有纪律分流：AI 可调用→进 catalog；人工治理面→不进并在路由 docstring 声明。

## 10. 能力总评（复用/扩展/新建一览；逐项裁决见 00-gap-register.md）

| 阶段 | 可直接复用 | 需扩展 | 确需新建 |
|---|---|---|---|
| P0-1 访谈事实/需求 | transcripts 草稿/纪要生命周期、T-A2 脱敏三道防线、guidance 抽取管线范式（outbox 任务+ai_schema 校验+复核闸）、GuidanceReview 审阅 UI 范式 | 锚点模型（文档级→分段级）、逐条审阅态（现仅整版确认） | `discovery_extractions`/`business_facts`/`requirements`/`requirement_sources` 四表＋抽取 job_type＋提示词/契约＋事实/需求审阅 UI |
| P0-2 本体候选/稳定 ID | change-set 全链（提案→提交→确认物化/否决、指纹闸、决策分离）、merge/impact 原语 | captured_from 生产方（agent_run:）、候选↔事实/需求关联、试点实体 term_id 稳定链接 | 跨项目别名冲突检测（现仅项目内唯一，**需先拍板是否为刻意隔离**）；ADR-002 文档 |
| P0-3 方案/任务分解 | solutions（T-A5 骨架/T-A6 冻结）、project_tasks 全套（依赖/CAS/指派）、compiler.py 先例 | 方案条目↔需求/任务映射 | `delivery_plans`/`delivery_plan_items`/`delivery_plan_task_links`（全仓 grep 零命中） |
| P0-4 Workflow 模板 | 定义生命周期+执行器+平台模板底座（project_id NULL）、hops/CAS/审批复用、`validate_dag` | 节点契约字段（现白名单 12 键缺 timeout/schema/失败分类/补偿/方案关联）、模板种子化、发布权限策略、draft-from-plan（compiler.py 泛化） | 三套模板内容＋模板列表语义路由＋独立 validate 端点 |
| P1-1 ZCode 宿主通道 | zcode_contract（0.17.1 纯契约）、api_actions 密码确认流、MCP 15min 短票、沙箱网络/回收/脱敏原语 | AgentRun 执行字段（provider/host_agent_id/authorization_id/workspace_ref/resume_session_ref）、artifact size/mime | 宿主代理进程＋Provider 协议＋execution_policy/receipt（**先对齐在途 host-channel 会话线**） |
| P1-2 自动测试/证据 | agent_artifacts（`kind=test_results` 已在值域）、project_evidence、gate 证据校验 | evidence/validate 语义 | `test_plans`/`test_cases`/`test_executions`（quality/ 模块不存在，grep 零命中）；evidence_links 视关联需求定 |
| P1-3 指标/经验沉淀 | metrics 报表（10 指标+_REAL_RUNS 过滤）、operation_events、skill 版本治理 | 新事件类型（gate_*/workflow_* 多数已有）、工作流域指标 | delivery_metric_daily/skill_improvement_proposals（**先证聚合不足再建**） |

## 11. 审计边界声明

- 本审计基于 4 个并行只读代码深查（transcripts/guidance、agents/zcode、workflows/jobs、ontology/gate/tasks/solutions 四域）+ 机械口径现测 + 活库直查；行号锚以 `65db88c` 为准，后续提交会漂移。
- 活库为生产部署库（非测试库）；测试基线见 `00-test-baseline.md`。
- 未运行任何被审代码之外的构建；未修改任何业务代码、迁移、路由。
