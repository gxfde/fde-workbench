# AI 原生化差距评估 v1.1

**评估问题**：本项目离「AI 原生应用」还有多远？怎么才能成为真正的 AI 原生应用？

- **日期**：2026-11-09（评估框架经蔡工确认后落盘；含对 2026-11-08 口头评估的复核修正与圆桌评审改进，见 §9）
- **修订记录**：**v1**（2026-11-09 首版）→ **v1.1**（2026-11-09，七人圆桌评审后改进：通道事实实测化〔fallback 直连承役〕、四特征标尺化、Path 重排〔仪表化前置〕、派单推荐上调进 Path 1、新增缺口 G-15/G-16、分发边界注记；总判定不变）→ **v1.2**（2026-11-09 晚，第二轮活库实测后的事实回写：执行面**已在模拟场真实行使**（`agent_runs` 0→9、`agent_artifacts` 0→34 且全 `reviewed=False`）、模拟场已跑（`simulation_runs` 0→4）、审计 6→11 行、抽取 5 试 1 成；**总判定与四特征评分维持不变**，仅证据基线前移，见 §9 第 10 条）。评审裁决全文见 [AI原生化差距评估-评审报告-v1.md](./AI原生化差距评估-评审报告-v1.md)（R-01–R-14：采纳 12 · 部分采纳 2）。
- **分发边界**（R-11）：**内部评估文档，不随招商材料外发**；对外口径以 BP §1.3a 官方自评为准。BP §1.3a 证据表为 2026-11-01 历史快照（83 表时代），本评估全部为现测口径，两者不得混抄。
- **评估基线**：fork/main `f589801`（#232 试点复盘，2026-11-09）；file:line 锚点复核基线 `cddefd4`（#231）——#232 纯文档零代码，锚点不受影响；结构口径=`docs/audit/v3-workbench-inventory.json` 现测 **397 路由 / 49 蓝图 / 132 表 / 52 rev 单头 `b3e7c9d1a5f2`**；活库=2026-11-09 生产库两轮只读探针（docker exec + 只读 SQL）。
- **性质**：纯评估文档（零代码零迁移零路由）；**不构成任何实施授权**——§7 四路径均须随轮立项 + 拍板后才可施工。
- **配套台账**：[AI原生化差距台账-v1.md](./AI原生化差距台账-v1.md)（G-01–G-16，每条带 file:line 锚点 + 消解判据 + 体量/依赖 + 状态，供逐轮实施对账）。
- **配套施工单**：[AI原生化实施任务书-v1.md](./AI原生化实施任务书-v1.md)（leader 执行本：轮次编排 N1–N6、拍板闸 D-1–D-8、逐轮 DoD 与复测规程）。

## 0. 结论速览

| 问题 | 结论 |
|---|---|
| 抽离测试（移除 LLM 会怎样） | **不通过**——决策与账务主干（方案/测试计划/门禁/派单/报价/收款/合同/权益）全部存活，只有售前与执行面的 AI 管线崩塌 ⇒ **当前是 AI+（AI 增强）形态，不是 AI 原生**（结论有效期注记见 §1） |
| 四特征（信通院框架，0–3 标尺） | ①智能内生=**2/3**；②数据飞轮=**1/3**；③人机协同=**2/3**；④持续进化=**1/3**（标尺与翻分条件见 §4） |
| BP §1.3a 官方自评 L2+ | **复核成立**；到 L3 的三件事=决策位 AI 起草（含派单推荐，Path 1）+ 飞轮回流闭环（Path 2）；L4 ≈ AI Native 抽离测试通过的交付域形态 |
| 最关键的事实 | **飞轮首圈已于 2026-11-08→11-09 之间转过**（售前链首批真实数据落库）；承役通道是**降级直连**（调用 `used_fallback` 多为 True，DSH 未上岗）、抽取 **5 试 1 成**；**执行面（agent）已在模拟场真实行使**（`agent_runs` 9 条走宿主通道，全为 `sim:` 前缀，**真实订单仍为零**）、模拟场已跑 4 次——首圈证明「链路通」，不证明「成熟」 |
| 圆桌评审 | 2026-11-09 七人对抗评审：总判定维持；采纳 12 项改进；评审新发现缺口 **G-15**（桌面 AI 编排面）/ **G-16**（审计匿名行）；Path 重排为 **0→2a→1→2b→3→4** |
| 差距总量 | 16 条（台账 G-01–G-16，其中 G-12 已被 #231 消解）；四条路径 Path 0–4；**施工编排见任务书 N1–N6** |

## 1. 评估口径

四把尺子（前三把经蔡工确认；第四把系评审 R-07 补充）：

1. **抽离测试**：把系统里的 AI 模块整体拿掉——产品崩塌=AI 原生；只是降级=AI+。
2. **AI Native vs AI+**（信通院口径）：AI 的角色是「工具」还是「大脑」；业务流程是「原流程打补丁」还是「围绕 AI 重建」；人机关系是「人操作 AI」还是「人管理 AI Agent」。
3. **四特征**：①智能内生（AI 是心脏与调度中枢）②数据飞轮（业务执行产生数据持续优化 AI）③人机协同（AI Agent 是独立「第二工作主体」）④持续进化（AI 从使用中实时进化，而非只随版本更新）。
4. **AI 出错韧性**（评审补充）：AI 出错时系统的行为也是判据——本仓 fail-closed 家族（契约失败整批零写入、脱敏词典故障 fail-closed、`succeeded_but_receipt_invalid` 写错不重做）是 AI Native 化的**前置资产**而非成本。

**抽离面界定与结论有效期**（R-07 注记）：本系统当前的可抽离面=5 个 SYSTEM_PROMPT 常量 + `execute_ai_prompt` 单一入口 + 各直连客户端——抽离测试在此边界上成立。**agent 执行面（agent_runs、宿主通道、模拟场）一旦真实上岗，抽离面扩大，本结论须复测**；建议每季度或每采纳一条 Path 后重跑 §3 表。

**加权解读**（R-07 注记）：抽离测试按业务关键度加权——决策权威（门禁）与账务主干（报价/收款/合同）权重最高，售前辅助链权重次之。AI 在售前段全崩不翻转判定；反之，AI 若进入决策位，即使售前段全人工，判定也须重估。

**与 BP §1.3a 的对齐**：BP v4.0 §1.3a 的交付智能化等级 L1–L5（L1 人工交付 → L2 流程自动化 → L3 AI 辅助交付=「AI 生成初稿物、人工审核修改后交付；**AI 参与派单推荐**」→ L4 监督自主=「AI 端到端完成标准单全节点交付（含证据链），人只做异常处理、终审与客户沟通」→ L5 全自主）与本评估刻度天然同构：**L3=AI 进决策位含派单推荐（本评估 Path 1），L4=抽离测试通过的交付域形态（≈AI Native 语义），L5=全自主**。BP §1.3a 同时钉死命名空间：L1–L5 是系统智能化轴，人的五层角色 L0–L5 是职级轴，两轴互不引用；`fde_profiles.level`（个人资历轴）与 `agent_runs.fallback_level`（单 run 降级链 L0–L3，`agents/models.py:74` CHECK）都不是这条轴。

## 2. 结构基线与 AI 资产盘点（2026-11-09 现测）

**结构口径**（`docs/audit/v3-workbench-inventory.json`）：132 业务表 / 52 迁移（单链 head `b3e7c9d1a5f2`）/ 397 路由 / 49 蓝图；`api_catalog` 94 ENTRIES；pytest CI 2396 passed + 6 skipped（#228 run 42503516295）/ vitest 960 / mypy 279。

**AI 面资产（都已存在，这是「底子好」的一面）**：

| 资产 | 锚点 | 状态 |
|---|---|---|
| AI 单一入口 execute_ai_prompt（预算门+审计+降级直连） | `control/ai_server_client.py:186` | 在役；活库 6 次调用（全 fallback 直连承役） |
| DSH 版本化运行时客户端 | `control/dsh_runtime.py` | 默认关，**未承役** |
| 宿主侧 zcode 代理（裁定 A） | `agents/host_channel.py` | 默认关，零行使 |
| 宿主轮询领取/回执面 | `agents/`（#204 三路由） | 默认关，零行使 |
| MCP 工具面 **17** 个（15 只读 + 2 写） | `control/mcp_gateway.py:36`（写：`file_send_wechat` :39、`api_execute` :41） | 在役 |
| AI 发起写动作的 propose→密码确认→execute 模式 | `control/api_actions.py:33`（15min 确认窗） | 在役（模板价值见 Path 3） |
| AI 访问分层 ACCESS_RANK 五级 | `control/access.py:36` | 在役 |
| 单 run 降级链 L0–L3 | `agents/models.py:74`（CHECK） | 在役 |
| **AI 月度预算闸**（token/agent 两闸） | `FDE_AI_MONTHLY_TOKEN_BUDGET` / `FDE_AGENT_MONTHLY_BUDGET`（`server/.env.example`） | 在役（R-10：Path 实施须附成本判据） |
| **fail-closed 韧性家族**（第四把尺的存量资产） | discovery 契约失败整批零写入（`discovery/jobs.py:40` 重试后丢弃）、脱敏词典故障 fail-closed（`enterprise_dict.py`）、`succeeded_but_receipt_invalid` 诚实终态（`agents/models.py` CHECK） | 在役 |
| 提示词常量 **5** 个 | `discovery/prompt.py`（DISCOVERY_SYSTEM_PROMPT）、`ai/research_form_prompt.py:9`、`ai/industry_template_prompt.py:10,21`、`simulation/evaluation_prompt.py:17` | **仅 discovery 带版本戳**（G-13） |
| 机会点 golden set 23 例 | `server/tests/fixtures/ai/opportunity_golden_set.json` | 只测后处理，不连模型（G-10） |
| 模拟实验室 L-A/L-B/L-C 三层评估 | `simulation/evaluator.py:14`（三层定义）、`simulation/model_evaluation.py:168`（G9 真模型层） | L-B 已接真模型栈，活库零行使 |
| 交付效果评测协议 v0 | `docs/architecture/交付效果评测协议-v0.md` | 文档层冻结，无 CI 消费 |

## 3. 抽离测试（逐链）

把 LLM 从系统里整体拿掉，逐链看崩不崩（✅=存活，❌=崩塌）：

| 链路 | 移除 LLM 后 | 判定 | 锚点 |
|---|---|---|---|
| 交付方案生成 | ✅ 完全存活——**本就确定性拼装，从未调用 AI** | AI+ 证据 | `plans/service.py:64,75` |
| 测试计划生成 | ✅ 同上，注释明言「AI 用例通道为未来增强」 | AI+ 证据 | `quality/service.py:4,72` |
| 门禁 G1–G9 | ✅ 零 AI 调用；证据 captured_from 单一来源 `human` | AI+ 证据 | `projects/gate_service.py:231,275,362` |
| 派单撮合 | ✅ 纯规则引擎（「纯函数、无 DB 依赖」「零画像输入」） | AI+ 证据 | `dispatch/scoring.py:3,7` |
| 报价/收款/合同/权益/免费额度 | ✅ 规则+密码确认闸，无 AI | AI+ 证据 | `commercial/`（G1/G2 两轮） |
| 访谈事实抽取 | ❌ 崩——活库 5 试 1 成 | AI 在役（直连承役） | `discovery/jobs.py:108` |
| 售前分析/预调研 | ❌ 崩 | AI 在役 | `guidance/`（ai_prompt 管线） |
| 机会点候选 | ❌ 崩——golden set 只测 `_normalize_candidates` 后处理 | AI 在役 | `server/tests/test_ai_eval/test_ai_eval_opportunity.py:19` |
| 行业模板/调研表 AI 生成 | ❌ 崩 | AI 在役 | `ai/industry_template_prompt.py:10,21` |
| chat | ❌ 崩（16 轮真实会话在库） | AI 在役 | ai_chat_turns 表 |
| agent run（DSH/宿主通道） | ❌ 崩——通道在、默认关、活库 0 run | 结构在役 | `agents/host_channel.py`、`config.py:83,147,158` |
| workflow skill 节点 | ❌ 崩（use_tools=False 文本变换走 LLM） | 结构在役（首圈 1 节点真实行使） | `workflows/dispatch.py:316` |
| 模拟实验室 L-B 模型评估 | ❌ 崩（G9 已接真模型，活库 0 次） | 结构在役 | `simulation/model_evaluation.py:168` |

**判定**：决策权威（门禁拍板）、交付主干（方案/测试计划/派单）、账务主干（报价/收款/合同/权益）在无 LLM 的世界里**一行代码都不用改**。AI 是「内容处理器」，不是「调度中枢」⇒ **AI+**。抽离测试不过（有效期与加权注记见 §1）。

## 4. 四特征评分（0–3 标尺，R-06）

**标尺**：0=缺失；1=结构在役、未行使；2=有真实行使（回流/闭环未达成）；3=行使+回流闭环。每档翻分条件挂钩台账 G 条目——复测时按翻分条件判分，不再凭措辞。

**证据基线前移注记（v1.2）**：当日晚些时候的活库实测显示，执行面与模拟场**已从「结构在役」变为「有真实行使」**（`agent_runs` 9、`agent_artifacts` 34、`simulation_runs` 4）——②③④三项的「有真实行使」成分比 v1.1 更实。但**回流闭环四断点仍全断**（无提示词指纹、无 reviewed 消费、无 CI eval、无发布通道），且真实订单仍零行使 ⇒ **评分维持 2-1-2-1**——分数只在回流闭环达成时上行。

### ①智能内生 —— 2/3

**得 2 的依据**：售前 AI 管线有真实行使（§5：抽取成功 1 次、chat 16 轮、skill 节点 1 次）；执行面结构齐备（17 MCP 工具、L0–L3 降级链、预算闸、审计账本、宿主双通道），**且已在模拟场真实行使**（v1.2：9 条 agent run 走宿主通道、34 条产物落库）。
**未到 3 的缺口**：AI 不在调度位——**run 只能人发起**（17 个 MCP 工具无一可发起 agent/workflow run，`control/mcp_gateway.py:36`；发起路由全部面向人）；**DAG 只能人规划**（节点类型四值闭集 `workflows/constants.py:50`，图来源=人工模板 `server/seeds/workflow-templates.json` 或确定性编译器 `workflows/compiler.py:326`）；**决策位零 AI**（§3 前五行）。
**翻 3 条件**：G-02（受确认闸的 AI 发起）+ G-03（AI 起草 DAG）落地且执行面首跑。

### ②数据飞轮 —— 1/3

**得 1 的依据**：首圈已转（§5 售前链首批真实数据）——「业务执行产生数据」半圈从零变为一。
**未到 2 的缺口**：「数据反哺优化 AI」半圈**四断点一条未通**：
- **断点 a**：人工接受信号只写不读——`agents/service.py:1445` 写 `reviewed`，全仓无任何 AI 面消费点（仅 API 呈现 `:363`）；
- **断点 b**：审计账本无提示词指纹——`ai_call_audits` 列集（`workbench/models.py:920` 起）存 model/tokens/status，无 prompt 指纹/版本列 ⇒ 输出质量无法归因到提示词版本；且有 `purpose=None` 匿名行 2/6（G-16）；
- **断点 c**：golden set 不连模型（G-10）；CI 无 AI 评测 job（`.github/workflows/ci.yml` 仅四 job）；
- **断点 d**：模拟实验室改进链止于 `approved`（「只提案不落地」P8 四条强制落点，`simulation/improvement_service.py` 头注；静态钉 `server/tests/test_simulation_improvement.py:403`）。
**翻 2 条件**：首圈失败归因复盘（零代码，R-09）+ G-09/G-16 归因闭合。**翻 3 条件**：G-08/G-10/G-11/G-14 回流闭环。

### ③人机协同 —— 2/3

**得 2 的依据**（R-14 修正措辞：**结构接近达标、行使刚起步**）：Agent 作为「第二工作主体」的主体性结构最完整——独立 run 生命周期（queued→host_running→终态，含 `succeeded_but_receipt_invalid` 诚实终态）、逐 run 预算与 L0–L3 降级链、产物 sha256 指针化+人工接受/撤回面（tb2 轮）、宿主代理与授权 run 一一对应；首圈 2 个 `human_approval` 节点真实行使；桌面审阅面（DiscoveryPanel/AgentsConsole/GuidanceReview）在役。
**未到 3 的缺口**：**agent 第二主体只在模拟场上过班，真实订单仍零**（v1.2：9 条 run 全 `sim:` 前缀、34 条产物**全 `reviewed=False`**——人工接受信号连写都没写过）；AI 不能自启动（G-02）；桌面缺 AI 运行编排/多 run 管理面（G-15）；多 Agent 编排未开。
**翻 3 条件**：Path 0 首个含 agent run 的真实订单 + G-15 落地。

### ④持续进化 —— 1/3

**得 1 的依据**：评估基建在仓**且已真实跑过**——G9 真模型评估层（`simulation/model_evaluation.py:168` ServerModelEvaluation→`ai/deepseek` complete_json + `evaluation_schema` 严格契约 + `evaluation_prompt.py:17` 三纪律提示词）+ 交付效果评测协议 v0 文档层；v1.2 实测：`simulation_runs`=4 全 completed，审计 3 行 `purpose=simulation_evaluation`（`used_fallback=false`）。
**未到 2 的缺口**：**跑了但没回流**——CI 无模型评测 job（G-10，四 job 仍无 eval）；提示词版本化 1/5（G-13）；改进链无发布通道（G-11）；人工接受信号无消费点（G-08，34 条产物全 `reviewed=False`）。「从使用中实时进化」目前仍是零。
**翻 2 条件**：模拟场首跑（拿第一批真模型评估数据，R-11）+ G-13 版本注册。**翻 3 条件**：G-10/G-11/G-14。

## 5. 通道与活库现状（三次探针汇总）

**三条 AI 执行通道源码默认全关**：`config.py:83 dsh_enabled=False` / `:147 agent_host_channel_enabled=False` / `:158 agent_host_poll_enabled=False`。

**ai_call_audits 全 11 行明细**（2026-11-09 第二轮探针 6 行 + 当日晚第三轮探针新增 5 行，R-01 实测）：

| 日期 | purpose | model | used_fallback | status | tokens(in/out) |
|---|---|---|---|---|---|
| 11-06 | （空） | MiniMax-M3.1-Flash | True | succeeded | 194,887 / 12,911 |
| 11-08 | discovery_extract | MiniMax-M3.1-Flash | True | **failed / ai_output_invalid** | — |
| 11-08 | discovery_extract | 同上 | True | **failed / ai_output_invalid** | — |
| 11-08 | discovery_extract | 同上 | True | **failed / ai_output_invalid** | — |
| 11-08 | discovery_extract | 同上 | True | succeeded | 1,422 / 15,834 |
| 11-08 | （空） | 同上 | True | succeeded | 618 / 245 |
| 11-09 | simulation_evaluation | 同上 | **False** | succeeded | — |
| 11-09 | discovery_extract | 同上 | True | **failed / ai_output_invalid** | — |
| 11-09 | discovery_extract | 同上 | True | **failed / ai_output_invalid** | — |
| 11-09 | simulation_evaluation | 同上 | **False** | succeeded | — |
| 11-09 | simulation_evaluation | 同上 | **False** | succeeded | — |

**业务面数据对照（2026-11-08 首探 → 2026-11-09 复测 → 11-09 晚第三轮）**：

| 表 | 11-08 | 11-09 | 11-09 晚 | 读法 |
|---|---|---|---|---|
| discovery_extractions | 0 | 2 | **3** | 真实抽取已跑（**5 次调用 1 成**，见上表） |
| business_facts | 0 | 22 | **22** | 事实已入库 |
| requirements | 0 | 7 | **7** | 需求已结构化 |
| delivery_plans | 0 | 1 | **1** | 方案已生成（确定性生成器） |
| test_plans | 0 | 2 | **2** | 测试计划已生成 |
| workflow_runs | 0 | 1（succeeded） | **1（succeeded）** | 首个工作流跑通（形态见下） |
| ai_chat_turns | 16 | 16（15 completed + 1 failed） | **16** | 持平 |
| agent_runs / agent_artifacts | 0 | 0 | **9 / 34** | **执行面已在模拟场真实行使**（宿主通道承役，全 `sim:` 前缀 ⇒ 真实订单仍零）；34 条产物**全 `reviewed=False`** |
| simulation_runs / automation_task_runs | 0 | 0 | **4 / 0** | 模拟场已真跑 4 次（全 completed；对应 3 行 `simulation_evaluation` 审计且 `used_fallback=false`）；自动化任务面仍未行使 |

**首圈工作流形态**（第二轮探针）：定义 1 个 run，来源与 P0-4 `compile_plan_workflow` 三节点形吻合（控制台转码辨认定义名「交付执行：交付方案 v1（自动拼装草稿）」）；节点实测 **human_approval×2 + skill×1，全部 succeeded**——人机协同的首次真实行使。**#232 官方复盘互证**：run `21fc3fa9`（draft-from-plan `44ac0ea1` 编译，skill=`delivery-scope-documents@1`），两处审批由第二账号 pilot.reviewer 拍板（审批时延中位 1.43min），全程 ≈6.1h。

**读法**（R-01/R-09 修正 + v1.2 第三轮实测）：①承役通道是**降级直连**（11 行中 8 行 `used_fallback=true`）——DSH 版本化运行时未承役（不证明 DSH 坏，只证明它没上岗）；②抽取 **5 试 1 成**，失败码 `ai_output_invalid`=输出不合规整批丢弃——fail-closed 按设计工作；**根因已由 #232 试点复盘登记为 backlog V31-P1**（降级直连腿未按推理模型预留输出预算，MiniMax-M3.1-Flash 下大纪要抽取必败；成功例输入为人工整理稿，与该根因吻合）——行动项由「失败归因」转为「跟踪 V31-P1 消解后复测」（修复 PR **#235 在途**）；③2 行 `purpose=None`（占 11 行的 18%）——存在不带用途标识的调用方（G-16）；④样本量=1：首圈只证明「链路通」，不证明「成熟」；⑤**执行面已非零**（v1.2 更正）：9 条 agent run 全部走宿主通道、幂等键带 `sim:` 前缀 ⇒ **模拟场真实行使，真实客户订单仍零**；34 条产物**全 `reviewed=False`** ⇒ 人工接受信号「只写不读」之外，**连写都还没发生过**；⑥降级链已真实行使（2 条 timeout 带 `fallback_level=L2`），「写错不重做」诚实终态真实出现 1 次；⑦回流段四断点仍全断。

## 6. BP §1.3a 等级复核

BP v4.0 §1.3a 官方自评 **L2+（强 L2，向 L3 演进中）**（2026-11-01 口径；其证据表为历史快照，以本评估现测为准）。本次复核**成立**，并可细化：

- **L2 证据充分**：门禁 G1–G9、报价/收款/合同、派单规则引擎、SOP 状态机全部在役（§3 前五行）——「系统不通过门禁就走到不了下一步」成立。
- **已触及 L3 的部分比 BP 成文时更实**：2026-11-09 活库已出现**AI 真实出力的结构化链样本**（抽取成功→22 事实→7 需求）+ 首个工作流（2 人工审批+1 skill 节点）——L3 的「AI 生成初稿物→人审」语义在售前段有了真实样本。
- **L3 未达成的三件事**（=台账 Path 2a+1+2b；R-05 按 BP L3 口径补派单推荐）：①**决策位 AI 起草含派单推荐**——方案/测试计划生成器仍是确定性拼装（G-04/G-05），DAG 无人规划（G-03），派单无 AI 推荐（G-06）；②**飞轮回流闭环**——人工接受信号、审计归因（含 G-16 匿名行）、评测回归全部断链（G-07…G-11、G-13、G-14）；③**仪表化前置**——没有归因仪表之前上决策位 AI，跑出来的东西无法进化（R-04）。
- **L4=监督自主 ≈ AI Native 语义的交付域形态**：抽离测试通过+人只做异常处理与终审。BP §1.3a「P0–P1 推进 L3 落地、P2 之后探索标准单 L4」的节奏与本评估路径顺序一致。

## 7. 成为 AI 原生的路径（每条须随轮立项+拍板；顺序 R-04 重排）

**Path 0 · 前置通道跑通（存量闸，最优先）**：在受控试点（pilot-runbook C1–C7 前置闸）内开启执行通道，完成首个含 agent run 的真实订单至 G9。v1.2 实测：`agent_runs` 虽已有 9 条，但**幂等键全带 `sim:` 前缀**——「第二执行主体」只在上模拟场的班，**真实订单的数据前提仍未取得**。红线：宿主通道边界五条、H1–H13 强制人工节点不解除。
*变体开局（R-11）*：真实订单闸未开时，可先跑一次模拟场（G-12 评估栈已在仓）拿第一批真模型评估数据——**不替代**真实订单闸。

**Path 2a · 仪表化（前置，先于一切决策位 AI）**：①`ai_call_audits` 加 prompt_fingerprint/prompt_version 列（G-09，迁移）+ 全量调用强制 purpose 非空（G-16）；②消费 `reviewed`/验收信号驱动复审（G-08）；③首圈失败归因复盘（零代码，R-09）。理由（R-04）：无归因仪表的决策位 AI 不可审计、不可进化。

**Path 1 · AI 进决策位（翻抽离测试的第一步）**：把「AI 起草→人工审核→发布」两段式推进到四个位置——方案条目起草（G-04，依赖 G-09）、测试用例起草（G-05，quality 两段式审核戳先例，依赖 G-09；**建议作试点首发**，R-11）、DAG 草稿（G-03，`compile_plan_workflow` 输入侧 AI 化，产出仍走 validate+create_definition 人工通道）、**派单推荐**（G-06，按 BP L3 口径为组成部分；建议入口+人工终审，不夺权）。门禁拍板不 AI 化（红线），只补 AI 起草的证据候选链（G-07）。

**Path 2b · 评测回归与受控发布**：①golden set 接真实模型进 CI eval job，按交付效果评测协议 v0 出 uplift 报告（G-10，依赖 G-09）；②给模拟实验室改进提案建**受控发布通道**（发布闸+审计+可回滚），静态钉改语义而非删除（G-11）；③指标触发自动改进动作（G-14）。

**Path 3 · AI 提议+人确认（自主化的安全形态）**：把 `control/api_actions.py:33` 的 propose→密码确认→execute（15min 窗）模式扩到「发起 workflow/agent run」——AI 可提议，人一键确认（G-02）。**安全清单（R-03）**：取消语义（确认窗内 run 已被人取消时提议必须失效）、幂等键（同提议重复确认不双发）、授权绑定（票据须绑发起人+run+工作区，与宿主通道 grant 同构）三样必须在设计轮评审。

**Path 4 · 版本注册表与按质量路由（进化底座）**：全部 5 个 SYSTEM_PROMPT 常量进版本注册表（G-13），审计按版本归因，模型选择从人工配置走向按评测质量路由（消费 Path 2b 的 eval 产出）。

**建议顺序**：**Path 0 → 2a → 1 → 2b → 3 → 4**；**施工轮次编排见 [AI原生化实施任务书-v1.md](./AI原生化实施任务书-v1.md)（N1–N6；并行例外：N2 仪表化不依赖业务闸，可先开）**。**成本判据（R-10）**：每条 Path 实施轮须附 token/预算影响估算（预算闸 `FDE_AI_MONTHLY_TOKEN_BUDGET`/`FDE_AGENT_MONTHLY_BUDGET` 现成，评估先例=首圈单次抽取 1,422/15,834 tokens）。每条路径的逐条差距、消解判据、体量、依赖见台账。

## 8. 红线边界（评估与实施都不逾越）

- AI 不代拍板：门禁拍板、审批、终审永远是人工（H1–H13 强制人工节点）；AI 只起草、建议、候选。
- 客户真实资料不入库不入仓：AI 面只传代号化上下文（T-A2 三道防线、discovery fail-closed 脱敏）。
- 门禁证据只存 `source_uri` 指针 + sha256；AI 产物原件永不入库。
- 写外呼、发信、付款永不降级、永不自动（`file_send_wechat` 事前密码确认边界维持）。
- AI 审查不执行被审代码（红线第 7 条）；宿主通道五边界（红线第 5 条）。
- 「写错不重做」语义（`succeeded_but_receipt_invalid`）与 L0–L3 降级链是 AI 自主化的安全底座，Path 1–3 不得绕开。

## 9. 复核与评审记录

**对 2026-11-08 口头评估的修正**（1–5，落盘复核时）：

1. **三通道锚点漂移**：`config.py` 行号 80/144/155 → **83/147/158**。
2. **MCP 工具数**：16 → **17**（15 只读 + 2 写）。
3. **「模拟模型评估未接线」已过时**：#231 已落 G9 真模型评估层。遗留小漂移：`simulation/model_evaluation.py:10-11` 模块头 docstring 仍写「本轮未接线」（类 docstring `:168` 为权威），留给下一 V3.2 轮顺带清理。
4. **「飞轮未转过」已过时**：售前链首批真实数据落库——改写为「生产段已通、回流段全断」。
5. **提示词常量盘点**：4 → **5 个**（G9 新增；仍仅 discovery 带版本戳）。

**评审期间新增事实**（6–8，探针第二轮）：

6. **首圈通道实测**（第二轮探针时点；11-09 晚第三次探针后为 **5 试 1 成、审计 11 行**，见第 10 条）：6 次调用全部 `used_fallback=True`（降级直连承役，DSH 未上岗）；模型 MiniMax-M3.1-Flash；抽取 4 试 1 成（3 failed `ai_output_invalid`）；2 行 `purpose=None`（→G-16）。
7. **首圈工作流形态**：draft-from-plan 编译定义 1 个 run（human_approval×2+skill×1 全 succeeded）——人机协同首次真实行使。
8. **圆桌评审**：party-mode 七人对抗评审（评审报告-v1.md），R-01–R-14 裁决采纳 12 项/部分采纳 2 项；总判定维持；四特征标尺化、Path 重排（0→2a→1→2b→3→4）、派单推荐上调（R-05）、新增 G-15/G-16。
9. **并发轮 #232 并入（rebase 后对齐）**：somwyn 试点执行与复盘落档（`docs/v3.1/pilot-复盘-somwyn-2026-11-09.md`）——本评估 §5 探针所见的首圈数据有了官方来历（项目 `7042d7ab`、十步 E2E 全链走通、run `21fc3fa9`、指标 v31 七指标全有样本）；抽取 3 例 `ai_output_invalid` 的根因=backlog **V31-P1**（推理模型输出预算）。#232 纯文档零代码，全部 file:line 锚点不受影响。
10. **同日第三轮实测回写（v1.2，2026-11-09 晚）**：活库在同一天内又动了——`agent_runs` 0→**9**（宿主通道承役，全 `sim:` 前缀）、`agent_artifacts` 0→**34**（**全 `reviewed=False`**）、`simulation_runs` 0→**4**（全 completed）、`ai_call_audits` 6→**11** 行（`purpose` 空仍 2 行）、`discovery_extractions` 2→**3**（抽取累计 **5 试 1 成**）。**更正 v1.1 的两句过期表述**：「执行面（agent）零行使」→「执行面已在模拟场真实行使，**真实订单仍零**」；「模拟场零行使」→「模拟场已跑 4 次」。**总判定与四特征评分（2-1-2-1）维持**——回流段四断点（无提示词指纹／无 reviewed 消费／无 CI eval／无发布通道）仍全断。台账 v1.2 同步回写 G-01/G-08/G-10/G-11/G-12 附注/G-16 锚点，并新增「规划轮次」列对接施工单 N1–N6；施工单另立 `docs/architecture/AI原生化实施任务书-v1.md`（N1–N6 轮次编排 + 拍板闸 D-1–D-8 + 逐轮 DoD）。
