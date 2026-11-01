# goal-d6 交付报告 · S1 收口 + 试点启动（降级链全链 + V3/V4/V11/V12 + U3–U6/U9 + 试点开关）

> 循环依据：《交付工作台升级 PRD v1.0 定稿》§4 P1 + 《技术实施方案-智能体交付工作台》§1 S1-7/§3.2/§6 + 《自动交付能力设计》§2.3/§2.4/§3 + 《需求与设计总纲》§5 + goal 循环提示词 v1.0（goal-d6 节）+ goal-d5 报告 §四建议。
> 基线：fork/main `b990333`（d5 合并点）。**本轮零迁移**（无新表新列；head 保持 `f6a9c3e1d7b4`）。

## 〇、预检（开工前实测）

- fork/main = `b990333`（fetch 后无并发新提交）；主树并发会话 6 M + 4 untracked 痕迹与 d5 末一致——全程隔离 worktree（`D:\test\fde-wt-d6`，junction `.venv`/`node_modules` + env 拷贝），零接触主树。
- 现状盘点：d4 已落 `agent_runs` 降级列族（`degraded`/`degraded_reason`/`fallback_level`/`retry_of`/`idempotency_key`/`cost_owner_*`/`handoff_user_id`）与 `ProjectSolution` E3 列族（`generated_by`/`agent_run_id`/`template_id`/`confidence`）；A-1→L2（沙箱失败零计费）与 L3（handoff→`ai_manual_handoff`）已在；缺口=L1 形态、fallback_level 标注、B 类降级去向、V3 交集前两重、V12 插件联动、generate-agent 接线、试点开关。

## 一、差距清单（本轮闭环项 → 触点）

| # | 缺口 | 判定依据 | d6 落点 |
|---|---|---|---|
| 1 | L1 形态缺失（D 类降级 completed 无层级标注、无强制人工终审） | 自动交付 §3.3 L1 行 + V4 | agents/service `_finalize` 标 `fallback_level=L1` + 产物不自动进终审 + handoff 接受 L1 |
| 2 | B 类（timeout/budget/failed）降级去向未标注 | §3.2 B 类「L1 或 L2」+ 技术文档 §6 | 终态非 completed → `fallback_level=L2`（无产物 → 模板填空；登记决议 ②） |
| 3 | V4「每级手动可触发」无生产触发面 | V4 判定原文 | admin rehearsal 端点（L1/L2）；L0=start_run、L3=handoff 既有手动面 |
| 4 | V3 三重交集只有第三重（adapter 声明白名单） | §2.3 原文 + V3 | `agents/tools.py` `effective_run_tools`：网关集 ∩ 能力集 ∩ 声明集 ∖ 写类默认拒 ∩ 插件安装态 |
| 5 | V12 插件 disable 无 agent 联动 | §2.4 P-1 | 插件类 capability 实时看安装态；声明工具全失效 → `tools_unavailable` 明确报因 |
| 6 | `solutions.generate-agent` 路由缺失；`agent_run_id` 无人写 | 技术文档 §10 + V9 | solutions 5 路由之一：内部复用 `agents.start_run`，completed+过门才接线 |
| 7 | U5 终审台纪要回链缺失 | 总纲 U5 | `GET .../solutions/{id}/review-trail`（家族 ∪ solution 侧链全会议+纪要） |
| 8 | SOW 导出无 agent 溯源行段 + 降级标注（V9 尾环 + V11 导出半） | V9/V11 + d5 报告 §四.3 | export_sow `content_snapshot["agent_trace"]` 段 |
| 9 | 试点开关缺失（30 天/20 run + UM-1 报告） | PRD §10 试点 + S1-7 | Settings 试点族 + start_run 闸 + `GET /agents/pilot-report` |
| 10 | U4 未决分歧不拦修订回路 | 总纲 U4 + 技术文档 §6 | retry 对 gate-blocked 家族查最新强制纪要 disputes 非空 → 409 升级人工 |
| 11 | U3 T3 自主召集无模板、reason 无约束 | 总纲 U3 | `T3-adhoc` 模板（trigger=adhoc）+ reason 必填落 topic_refs 计入纪要回链 |
| 12 | U9 强制门 checklist 降级面缺失 | 总纲 U9 + 技术文档 §6 | `GET /meeting-templates/{id}/checklist` 静态人工执行单 |
| 13 | run 卡死恢复（同步栈 crash 留 queued/running） | d5 报告挂账.5 | `POST /agents/runs/{id}/recover`（stale 阈值闸）+ 报告观测 stuck 计数 |
| 14 | V11 UI 半边（桌面无降级/溯源徽标） | V11「UI 与导出件」 | SolutionDto 溯源字段 + 详情页徽标 + vitest |

**不做边界（本轮明确不做，防蔓延）**：T4 加座/T5 恢复补审（d7，`min_difficulty` 列已预留）；S1–S6 全模板与 std/full 档（d7，PM-1 待蔡工审定）；Killjoy 自动收敛与会议中断恢复 M7（d7 编排器）；话轮/收敛成本归集（U6 全量随 S2 成本事件，本轮维持 convene 单次计费）；O-3 额度 seat 归集（d7）；O-8/UM-5 阈值自动判定（试点期人工评，本轮只出报告数）；真实 iptables 生效性与沙箱镜像 CLI 钉定（人工联调，见 §四）；L1 直连的模型调用实现（同步栈下 L1=降级产物形态标注+强制人工终审，生成动作仍由降级 run 的既有产物承载——登记决议 ①）。

## 二、行动与设计决议

### 1. 降级链全链（#1/#2/#3）——agents/service.py

- **决议 ①（L1 在同步栈的诚实形态）**：自动交付 §3.3 的 L1=「无沙箱纯模型直连生成、只读工具、强制人工终审」。本仓同步 Flask 栈无独立直连生成通道，而 D 类（tool_denied → run 继续、降级 completed）恰是「降级形态产物」的唯一既有事实源——d6 把 `completed+degraded` 判为 L1：`fallback_level="L1"` + 产物 **`linked_solution_id=None`（即使 T2 门已放行）**+ handoff 扩展接受 L1 completed（转人工终审 → 既有 signoff checkpoint 收口）。语义等价性：L1 产物永不自动进终审通道（强制人工终审 ✅）、降级可见（V11 ✅）、只读约束由降级收窄纪律承载（§2.3 降级态只读）。**不做**伪装的「直连模型调用」。
- **B 类去向（决议 ②）**：timeout/budget_exceeded/failed 终态 → `fallback_level="L2"`（产物不入库已成立，人走模板填空；§3.2 给的是「L1 或 L2」二选，取 L2 因无产物可降级审）。
- **V4 手动触发**：`POST /api/v1/agents/agents/{agent_id}/fallback-rehearsal`（admin；body `{level: L1|L2, project_id}`）：不跑沙箱不调用模型，创建演练 run 行走与真实故障**同一**标注/留痕代码路径（`_apply_fallback`），零计费、`degraded_reason="fallback_rehearsal"`、幂等键前缀 `rehearsal:`（报告指标可排除）、事件 `agent_fallback_rehearsed`。L0=正常 start_run；L3=handoff（本就是人工触发面）。
- handoff_run 扩展：`FAILED_STATUSES` 之外接受「completed + `fallback_level=L1`」的 run（转人工终审）；L1 run 已 handoff 过再 handoff → 409 既有语义。

### 2. V3 后半 + V12（#4/#5）——agents/tools.py（新）

- **决议 ③（工具名字空间裁决）**：§2.3 的「mcp_gateway 工具白名单」按名字空间分段求值——网关 TOOLS 是用户 AI 对话面工具集（actor=人），agent run 面工具名是沙箱/适配器生态（d5 已按同一事实把会议工具面落 `meetings.dispatch_agent_tool`，报告 §二.7 先例）。run 面交集=声明集 ∖ 平台 deny 集（写类 `api_execute`/`file_send_wechat` 默认不授予 + 会议面二工具不入 run ctx）∖ 能力不可行集；**网关名字空间**工具（名字在 TOOLS 中）才做 capability 腿实时判定：等级地板恒生效（`CAPABILITY_REQUIREMENTS`，插件安装绝不放宽门槛）且插件类 capability 另加实时安装态闸（V12）；沙箱生态工具名由声明集 + adapter 逐调用判定承载（d4 V3 前半不变）。全部落 `effective_run_tools`。
- start_run/retry 用 effective 集构建 `ctx.allowed_tools`（新 run 按最新白名单重建 ✅；在跑 run 不中断=同步栈允许名单在发起时刻冻结，§2.4 原文）。
- `_unavailability` 增分支：run 面声明工具非空但收紧后为空 → `tools_unavailable`（list_agents 明确报因 + start_run 拒；仅会议面声明的 agent 不受影响）。
- 插件安装是 per-user 语义（`PluginInstallation` UniqueConstraint(plugin,user)）——agent run 继承发起人的权限天花板（「要求人在回路上」，§2.3）。

### 3. generate-agent 接线 + review-trail + SOW 溯源段（#6/#7/#8）——solutions/service+routes

- `POST /api/v1/projects/{pid}/solutions/{sid}/generate-agent`（body `{agent_id, idempotency_key?}`）：can_manage + 复用 `agents_service.start_run`（鉴权/白名单/幂等/预算/门全链不重写）；completed → 独立小事务 `solution.agent_run_id=run.id` + `generated_by='agent'`（E3 列语义双写；接线幂等，重复调用同 run 不重复建事件）+ 事件 `solution_agent_wired`；409（gate_open/校验失败/预算）原样透传不接线。L1 降级 completed 照实接线——接线是溯源事实不是终审放行，降级形态经 agent_trace/徽标显性。
- `GET /api/v1/projects/{pid}/solutions/{sid}/review-trail`（can_view）：`topic_refs.solution_id == sid` ∪ `triggered_by_run_id ∈ agent_run_id 幂等键家族` 的全部会议 + 纪要（未封存标 sealed=false 不吐 minutes 内容）——U5 终审台回链。收 api_catalog（只读，+1 → 87）。
- export_sow：`content_snapshot["agent_trace"]` = `{agent_run_id, generated_by, degraded, fallback_level, degraded_reason, artifacts:[{kind, sha256}]}`（run 存在时）——V9 SOW→run→sha256 闭环 + V11 导出标注一段双收。

### 4. 试点开关（#9）——agents/pilot.py（新）+ Settings

- Settings 试点族：`agent_pilot_enabled=False` / `agent_pilot_window_days=30` / `agent_pilot_max_runs=20` / `agent_pilot_started_at=""`（ISO 空=以最早 agent_run.created_at 推导，无 run=未启动）。
- start_run 闸：试点启用、窗口内、run 数 ≥ max → 409 `pilot_run_limit_exceeded`（30 天/20 run 先到为准；窗口过完不再拦——试点结束报告定升级）。rehearsal run 计数排除（幂等键 `rehearsal:` 前缀）。
- `GET /api/v1/agents/pilot-report`（admin）：试点状态 + 指标——拦截率 `review_gate_open 拦截数 / (拦截数 + 过门产物 run 数)`、一次通过率 `过门产物 run 中 retry_of IS NULL 占比`、单会成本 `allowed meeting_convene 留痕数×2 / 会议总数`（U6 口径：convene 计费落触发 run.token_cost，台账聚合天然一致）、降级率 `degraded/total`、熔断率 `timeout+budget/total`、run 成本中位数、stuck 计数（queued/running 且超 stale 阈值）。**只出数不判阈**（O-8/UM-5 人工评）。

### 5. U4 / U3 / U9 / 卡死恢复（#10–#13）

- U4：retry_run 对 `degraded_reason=="review_gate_open"` 的原 run 增查**家族**最新已封存强制纪要（`triggered_by_run_id` ∈ 幂等键家族——与 `meeting_get_minutes` 的「只能读自己触发的会」所有权语义一致，修订回路的纪要输入面就是家族会）——`disputes` 非空 → 409 `revision_disputes_open`（升级人工，带 minutes_id/run_id）；重试上限 2 与「超限转人工」既有（d4）。solution 侧链会议仍按 d5 语义作门证据，但不作 agent 修订回路的分歧源（人若在侧链会留分歧，直接人工收口即可，不必经 agent retry）。
- U3：`T3-adhoc` 模板（gate=T3、trigger=adhoc、lite 档 2 轮）；create_meeting/dispatch convene 对 adhoc 模板要求 `reason`（1..160，strip 非空）→ 缺失 400 `reason_required`；reason 落 `topic_refs["reason"]`（纪要回链 get_minutes 可见=计入纪要）。
- U9：`GET /api/v1/meeting-templates/{id}/checklist` 输出静态人工执行单（模板 attendees/sections → 步骤化）；人工路径（L2 模板填空不经 run、L1 产物强制人工终审、L3 全人工）天然不被 T2 门阻塞——门只拦 agent 自动提交面。
- 卡死恢复：Settings `agent_recover_stale_minutes=15`；`POST /api/v1/agents/runs/{id}/recover`（发起人或 admin；status ∈ queued/running；`updated_at` 距今 ≥ 阈值）→ failed + `degraded_reason="stuck_recovered"` + 事件 `agent_run_recovered`（恢复后 retry/handoff 两路既有语义即可走）。

### 6. V11 桌面（#14）

- `serialize_solution` 增 `generated_by`/`agent_run_id`/`agent_degraded`（run join，只读推导）；SolutionDto 可选字段 + SolutionDetailPage 溯源徽标（智能体生成/降级）+ vitest。isSolution 宽松校验不破。

## 三、验收判据（逐条，全部本包实测）

| 判据 | 用例/断言 | 结果 |
|---|---|---|
| V3 | 写类（api_execute/file_send_wechat）+ 会议面工具在 effective 集被剥离；网关名字空间按能力腿判定；沙箱生态名由声明+adapter 承载 | ✅ test_v3_write_and_meeting_tools_stripped |
| V4 | L0=正常 run；L1=rehearsal 形态 + D 类真实降级双路径；L2=A-1 既有 + rehearsal + B 类 timeout 标注；L3=handoff 既有 | ✅ rehearsal_l1_l2 / tool_denied_lands_l1 / timeout_lands_l2 / normal_run_handoff_still_l3 |
| V11 | L1 产物 linked=None；SOW content_snapshot.agent_trace（degraded/指纹）；桌面 SolutionProvenanceBadge 三态 | ✅ l1_forced_manual_review / sow_export_carries_agent_trace / solution-provenance.test 4 用例 |
| V12 | 安装 disable → 新 run 白名单即时收紧；全失效 → tools_unavailable（列表报因+start 409）；等级地板不被安装放宽 | ✅ v12_plugin_disable / v12_all_tools_dead |
| U3 | T3-adhoc 缺 reason 400 reason_required（三重白名单先行）；带 reason 建会且 topic_refs.reason 入纪要回链；人工 T2-lite 带 reason 400；adhoc 纪要不放行强制门 | ✅ u3_t3_adhoc_requires_reason / u3_adhoc_minutes_not_gate_evidence |
| U4 | 未决分歧家族纪要 → retry 409 revision_disputes_open（带 minutes_id/run_id）；无分歧家族纪要 → retry 放行；重试上限转人工（d4 既有） | ✅ u4_open_disputes / u4_clean_minutes |
| U5 | review-trail 列家族（triggered_by_run_id）+ 侧链（topic_refs.solution_id）会议；封存吐三段+sealed_sha256、未封存只给状态 | ✅ review_trail_lists_family_and_side_link |
| U6 | 单会成本=allowed meeting_convene 计费×2/会议数（pilot 报告口径）；会议计费落触发 run.token_cost（d5 既有）聚合天然一致 | ✅ pilot_report_metrics（1×2/2=1.0） |
| U9 | checklist 端点输出三段式人工执行单（步骤化、未知模板 404）；人工路径不被 T2 门阻塞（门只拦 agent 自动提交面） | ✅ u9_checklist_endpoint |
| 试点 | 窗口内 20 run 闸（fixture 压到 2）409+明细；演练 run 不计数；窗口走完不拦；关闭不拦；报告 admin-only；六指标数值断言 + stuck 计数 | ✅ test_agent_pilot 6 用例 |
| 恢复 | 卡死 run 过阈值 → failed+stuck_recovered+事件；新鲜窗口 409；终态 409；成员非发起人 403（外人 403 project_forbidden）；admin 兜底放行 | ✅ recover_stuck / recover_fresh_window |
| 接线 | generate-agent 201 → agent_run_id+generated_by 双写+事件；gate_open 409 透传不接线；幂等 200 wired_now=False 不重复建事件；failed 形态 wired=False；权限/校验/archive 409 | ✅ test_solution_agent_wiring 11 用例 |
| 迁移 | 零迁移：head 保持 `f6a9c3e1d7b4`，94 表（95 含 alembic_version）不变 | ✅ |
| 口径 | 蓝图路由 **258**（252+6）；api_catalog ENTRIES **87**（86+1 只读 review-trail） | ✅ create_app 实测 |
| 全量 | pytest **1586 passed / 6 skipped / 0 failed**（基线 1557+6 → +29 新增）；typecheck 零错误；ruff All checks passed；mypy 273 < 基线 282（触碰文件零错误） | ✅ 实测 |
| vitest | **699/699 全绿（56 文件全过）**（695 基线 + 4 新增；串行模式 `npm test`）。过程口径：并发会话 npm 重建主树 node_modules 期间的三轮全量出现 2–4 个漂移失败，全部落在未触碰文件、逐文件重跑全绿、失败集轮间轮换（详见「假绿灯自检」）——扰动窗口结束后最终轮整轮干净 | ✅ 699/699 |

**变异闭环（fail-fast，6 处各红→还原→绿，还原以 /tmp/d6-mutbak `.bak` 字节级 diff 验证）**：

| # | 变异点 | 目标用例 | 红→绿 |
|---|---|---|---|
| ① | `_finalize` L1 产物挂载反转（去 l1_path） | tool_denied_lands_l1 | ✅ |
| ② | start_run 试点闸旁路 | pilot_run_cap_blocks_excess | ✅ |
| ③ | `_require_adhoc_reason` 拆除 | u3_t3_adhoc_requires_reason | ✅ |
| ④ | retry 分歧闸拆除 | u4_open_disputes | ✅ |
| ⑤ | recover 终态检查拆除 | recover_fresh_window_and_terminal_states | ✅ |
| ⑥ | 插件安装态闸拆除 | v12_plugin_disable | ✅ |

**反假绿灯自检**：①「零既有测试改动」复核——既有服务端用例零改动全绿；桌面仅 harness 级新增（patch 方法），无既有用例逻辑改动。②桌面全量四轮：扰动窗口内三轮 2–4 个漂移失败（extensions/research-definition-editor/navigation 等未触碰文件，逐个单独重跑全绿、失败集轮间轮换）；基线对照轮（暂存本包桌面改动）695/695 干净 + 扰动平息后最终轮 **699/699 全绿**——抖动与本包 diff 无关，判定为并发会话 npm 重建主树 node_modules 期间的资源扰动。③变异 6 处均以「还原后目标用例复绿 + 与备份字节级 diff 一致」收口，未用 git checkout。④pytest 全量 21 分钟单跑零失败零漂移——服务端口径以该轮为准。

**既有一个行为面修正登记**：V3 交集初版按字面把非网关工具名剥空（会误伤 d4 测试语料与真实沙箱生态声明）→ 修正为名字空间分段（决议③），d4/d5 语料零适配通过；本轮对既有测试的适配累计为 **harness 增 patch 方法 + 0 处用例逻辑改动**。

## 四、下一轮建议 + 新登记差距

- **goal-d7（S2 编排 + 额度 + 角色卡）**：模块智能体挂编排中枢；T1/T4/T5 门 + S1–S6 全模板（D10 蒸馏 + PM-1 蔡工审定）；角色卡 persona + PM-2 三层防火墙；Killjoy 自动收敛 + M7 中断恢复；O-3 额度 seat 归集 + 加油包 + UI 透明化。
- 新登记差距（进台账）：①话轮/收敛成本事件归集（U6 全量，随 S2 编排器）②L1 直连模型通道（若未来引入异步生成栈，fallback_level=L1 语义已备）③checkpoint 人工拍板 UI 流（signoff 桌面操作页）④pilot-report 桌面报表页（当前 API JSON）⑤真实 iptables 生效性 + 沙箱镜像 zcode CLI 版本钉定（试点前人工联调，见台账）⑥插件能力登记表种子（lcsc.browse 等插件 capability 的 PluginPackage 种子数据）⑦meetings POST 写路径 catalog 收录复议（维持不收，登记为口径备忘）。
