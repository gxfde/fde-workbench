# goal-d5 · 交付工作台升级轮次报告（2026-11-01）

> 输入：goal-d4 报告 + 《交付工作台升级 PRD v1.0 定稿》§4 F4 + 《技术实施方案-智能体交付工作台》§2/§3.2/§6 + PartyMode 评审会需求与设计 §6/§8 + 总纲 §5 + goal 循环提示词 v1.0（goal-d5 节）。
> 本轮 Goal（S1 评审会最小闭环 T2 lite）：**`review_meetings` 三表 + meetings 蓝图 6 路由 + 工具面 `meeting_convene`/`meeting_get_minutes` + 纪要三段式 `sealed_sha256` 封存 + run 状态机 T2 强制钩子（未过门不放行 → `review_gate_open`）。**

## 〇、开工预检（只读实测）

- fork/main `9a2c659`（PR #50 合并，d4 提交 `fc65902` 在顶）；并发会话在主工作区有未提交改动（dispatch/gates/api_catalog/台账——派单 B 系与 goal-r4 会话），本轮全程隔离 worktree `D:\test\fde-d5-wt`（fork/main 基线 + junction + env 拷贝），零接触。
- 基线（fork/main 实测）：91 业务表（92 含 alembic_version）/ head `d9c3e7f1a5b8`（16 revision）/ 蓝图路由 246 / ENTRIES 83 / pytest 1541 收集 / vitest 695。
- 施工准绳冲突裁决：代码实测 > PRD > 设计文档 > 规则表 > BP。

## 一、差距清单（本轮覆盖项）

| # | 能力项 | 目标（出处） | 现状（改动前，代码证据） | 定级 | 对应行动 |
|---|---|---|---|---|---|
| 1 | 评审会三表 | `review_meetings`(+gate_tier/triggered_by_run_id/trigger/min_difficulty)/`review_meeting_turns`/`review_meeting_minutes`（技术文档 §2 + PartyMode §6 原文） | 零存在；评审会无任何落库载体 | P0 | 3 新表迁移（head 顺延 1 位）；PartyMode §6 原文列 + 技术文档决议增量列逐列对齐 |
| 2 | meetings 蓝图 | POST /meetings、GET /{id}、POST /{id}/turns、POST /{id}/close、GET /{id}/minutes、GET /meeting-templates（PartyMode §6 REST 增量） | 零存在 | P0 | `meetings` 蓝图 6 路由；api_catalog 只收只读三条（沿 d4 agents 先例） |
| 3 | T2-lite 模板 | S2 lite：守卫+1 模块智能体、2 话轮（技术文档 §1 S1-5）；三档门 lite/std/full=2/8/12 轮（总纲 UM-1/PM-5） | 零存在 | P0 | `meetings/templates.py` 常量注册表（T2-lite 首发；std/full 随 d7）；GET /meeting-templates 读它 |
| 4 | 工具面 +2 | `meeting_convene`（只读发起/计费+占预算/每 run ≤2 次/capability=`agent.meeting.convene`/默认不在白名单/denied 落 agent_tool_calls）+ `meeting_get_minutes`（只读/会话内自动可读自己触发的纪要）（技术文档 §3.2） | 零存在；d4 适配器只判白名单不执行工具 | P0 | `meetings/service.py::dispatch_agent_tool`——agent 申请人模型的三重白名单 + 计费 + 限额 + denied 留痕（落点决议见 §二.7） |
| 5 | 纪要三段式 + 封存 | 共识/分歧/待办三段；守卫复核 source_refs 闭合，失败拒封存标 degraded；封存写 sealed_sha256（技术文档 §6；PartyMode §5.3 每轮收敛） | 零存在 | P0 | close 服务层：三段式校验 + 引用闭合守卫 + `sealed_sha256`（sha256(规范化 JSON)）+ 纪要不可变（二次 close 409） |
| 6 | T2 强制钩子 | worker 在 run 状态迁移点检查模板强制门，未满足（无对应 sealed minutes）迁移被拒返回 `review_gate_open`——状态机级强制非 prompt（技术文档 §6；U2） | 零存在；d4 `_finalize` 对 solution 绑定 run 的产物直接落 linked_solution_id 进终审通道，无任何门 | P0 | `_finalize` 挂 T2 门：solution 绑定的 completed run 必须有已封存强制评审纪要（triggered_by_run_id 直链或 topic_refs.solution_id 侧链）；缺失 → run failed + `review_gate_open` 409 + 产物留痕不提交（linked_solution_id=None，沿 C-1「留证不进终审」模式） |
| 7 | 会中只读（M4/U8 d5 切片） | 会中全角色（含召集 agent）只读，写工具一律 denied（技术文档 §6；PartyMode §1.3） | 无工具面可断言 | P0 | 工具面 frozenset 恒等于 {meeting_convene, meeting_get_minutes}；面外工具名 dispatch 一律 denied 落 agent_tool_calls |
| 8 | 不做边界 | T1/T3/T4/T5 门与自主召集（d6）；修订回路 ≤2 轮（U4，d6）；S1–S6 全模板与角色卡 persona（d7）；会议成本并入 run 台账全链（U6 全量，d6——本轮只落 convene 计费事件）；纪要进 Stage A/B 证据（M10，d6+） | —— | —— | 明确不越界：8 态机/隔离基线/dispatch 模块零触碰 |

## 二、行动说明

分支 `feat/delivery-d5-review-meetings`（1 迁移 + 10 文件 + 3 新测试文件），全程隔离 worktree（fork/main `9a2c659` 基线）。动了什么：

### 1. 三表迁移（`f6a9c3e1d7b4`，down_revision `d9c3e7f1a5b8`）

- `review_meetings`：PartyMode §6 原文列（project_id/template_id/status live-paused-closed/topic_refs/turn_budget/hosted_by_user_id）+ 技术文档 §2 决议增量（`gate_tier` lite-std-full 三档门 UM-1、`triggered_by_run_id` D7 关联落会议侧、`trigger` mandatory-adhoc-manual、`min_difficulty` T4 预留列）+ `convened_by_agent_id`（工具面召集留召集 agent）+ `degraded`（守卫拒封存标注）。
- `review_meeting_turns`：PartyMode §6 原文（meeting_id CASCADE/seq/speaker_agent_id XOR speaker_user_id Check/content JSON）+ (meeting_id, seq) 唯一。
- `review_meeting_minutes`：三段 consensus/disputes/todos JSON + `sealed_sha256`（64hex Check + meeting_id 唯一 = 一会一纪要）。
- `triggered_by_run_id` 软引用不设 FK（沿 `agent_runs.retry_of` 偏离先例：run 归档清理不被 RESTRICT 卡死）；`test_migrations.py` HEAD 常量同步；`conftest.py` 清理序 minutes→turns→meetings 先于 agent_registry/projects/users；**`migrations/env.py` 显式注册 meetings 模型**（`alembic check` 元数据比对模型装载靠 env 显式 import——漏注册会让 autogenerate 把三新表判成「应删除」，全量首跑抓出后即修）。

### 2. meetings 模块（`server/src/fde_api/meetings/`）

- **`templates.py` 模板注册表**：T2-lite 首发（守卫 quality_guard + 1 模块智能体、2 话轮、trigger=mandatory、三段式）——技术文档 §2「模板入 templates 体系或独立种子表实现时定」取常量注册表（心智沿 `CAPABILITY_REQUIREMENTS`，门禁语义随代码评审演进；std/full 与 S1–S6 内容蒸馏随 d7）。同时承载工具面常数：`MEETING_AGENT_TOOLS`（只读二面 frozenset）、`MEETING_CONVENE_COST_UNITS=2`、`MEETING_CONVENE_LIMIT_PER_RUN=2`。
- **`service.py`**：召集（人工 can_manage / 工具面三重白名单双通道，模板派生 gate_tier/trigger/turn_budget）；话轮（XOR 发言者、预算硬墙 M6）；收敛（三段式契约键集精确、分歧条目必须 ≥2 方论点+冲突标注 M3、守卫复核引用闭合=topic_refs∪话轮 refs、`sealed_sha256=sha256(规范化 JSON)` 封存不可变二次 close 409）；纪要读取（M2 回链 triggered_by_run_id/topic_refs）。
- **`routes.py`**：6 路由挂 `/api/v1`（POST /meetings、GET /meetings/{id}、POST turns、POST close、GET minutes、GET /meeting-templates）；api_catalog 只收只读三条（83→86），召集/发言/收敛人工写路径不收（沿门禁与 d4 agents 先例）。
- **工具面 `dispatch_agent_tool`**：agent 执行面工具网关——三重白名单（enabled / `allowed_tools` 显式声明 `meeting_convene`（默认不在任何白名单 U1）/ `authorize_ai_capability('agent.meeting.convene')` 实时鉴权）+ 计费占预算（+2 落触发 run.token_cost，越 registry max_cost_units 拒）+ 每 run ≤2 次（U7）+ `meeting_get_minutes` 只读且仅自己触发的纪要（会话内自动可读）+ 面外工具一律 denied（U8/M4 d5 切片）。

### 3. T2 强制钩子（`agents/service.py::_finalize`，技术文档 §6）

- 门锚点=「artifact 提交终审」在本同步栈的对应迁移点：**solution 绑定的 completed run**（`linked_solution_id` 落库即进入方案终审通道）。无已封存强制纪要（`t2_gate_satisfied`：trigger='mandatory' 的已封存纪要，run 直链/幂等键家流域 `triggered_by_run_id` 命中，或 `topic_refs.solution_id` 侧链命中）→ 迁移被拒：run failed + `degraded_reason="review_gate_open"` + 409 失败码可见 + 产物留痕但 `linked_solution_id=None`（沿 C-1「留证不进终审」模式，补会后同键 retry 放行）。
- 无 solution 绑定的探索性 run 不进终审通道，门不适用——**d4 行为零回归**（全量 1541 基线用例零改动通过）。
- 偏离登记：技术文档 §6 原文「worker 在 run 状态迁移点检查」——本仓库同步 Flask 栈无独立 worker（d4 已登记的同一偏离），钩子由服务层 `_finalize` 承接，语义等价（状态机级强制，非 prompt）。

### 4. 行为变更单列

**零既有路由/契约行为变更。** 纯增量：3 新表 + 6 新路由 + 3 只读 catalog 条目 + agents `_finalize` 新增门逻辑。回滚：`alembic downgrade -1` 可逆。

**既有测试适配 1 处**（d1 G3 闸先例、d3→d4 allowlist 断言升级同款演进）：`test_agent_traceability.py::test_t1_reverse_chain` 是全仓唯一经服务层绑定 solution 的 run 用例——T2 门按设计拦下它；按门语义补「T2-lite 会议 + 封存」前置三行（空引用三段式=守卫平凡闭合），T-1 反查链本体断言零改动。其余 1541 基线用例零改动通过。

### 5. 设计决议登记（偏离/澄清原文处）

1. **工具面落点**：技术文档 §3.2 表头「mcp_gateway 增量」按行为事实拆读——denied 落 `agent_tool_calls`（run_id NOT NULL FK）+ `agent_registry.allowed_tools` 白名单是 agent 执行面语义，故落 `meetings/service.dispatch_agent_tool`（未来编排中枢接线点）；桌面 `mcp_gateway.TOOLS` 是用户 AI 对话面（actor=人、无 run_id 可挂留痕），不收这两个工具。
2. **纪要收敛人**：PartyMode §5.2「超限主持人强制收敛」d5 切片=预算硬墙（超限 409 后唯一出路 close）+ 人工收敛；编排中枢自动收敛（Killjoy）随 d7。M6 判据「超限强制收敛」以「预算生效 + 收敛放行」两断言覆盖。
3. **话轮预算与门的关系**：T2 门只认「已封存强制纪要」，不认话轮数——lite 2 轮是预算上限不是达标线（0 话轮亦可封存，守卫只复核引用闭合）。
4. **家族语义**：纪要对幂等键家族生效（评审针对产物与方案，不针对单次尝试）——被门拦下的 run1 召集封存后，同键 retry（run2）放行。
5. **deny 语义**：拒绝路径的 denied 留痕与 degraded 标注走独立事务提交——拒绝本身回滚，痕迹永不丢（denied 必留痕红线）。

## 三、验证结论

| 判据 | 结果 | 命令与证据摘要 |
|---|---|---|
| M2 纪要三段式 + 溯源 | ✅ | `test_minutes_traceable_to_agent_run_m2`：minutes → `triggered_by_run_id` → run → 产物 sha256 反查链闭合；GET minutes 带回链字段 |
| M3 分歧原样保留 | ✅ | `test_disputes_preserved_with_conflict_m3`：双方论点文本逐一断言相等 + conflict 标注；单方伪分歧 400 `invalid_dispute` |
| M4 会中只读（d5 切片） | ✅ | 面断言 `MEETING_AGENT_TOOLS == {meeting_convene, meeting_get_minutes}`；`test_out_of_surface_tool_denied_and_recorded_u8`：`file.write` 403 + denied 留痕（写类工具全量面随 d6/d7 mcp 网关扩展） |
| M6 话轮预算 | ✅ | `test_turn_budget_wall_then_close_m6`：lite=2 硬墙 409 → close 收敛封存 → 二次 close 409 不可变 |
| U1 三重白名单 | ✅ | 未声明 agent：403 `not_in_allowlist` + `agent_tool_calls` denied 留痕；三重全过 → 召集成立 + allowed 留痕 |
| U2 T2 强制门 | ✅ | 跳过尝试：solution 绑定 run → 409 `review_gate_open` + run failed + 产物 `linked_solution_id=None` 不进终审；放行双路径（topic_refs.solution_id 侧链新发起 / triggered_by_run_id 家族 retry）实测 201 |
| U7 每 run ≤2 次 | ✅ | 第 3 次召集 409 `convene_limit_exceeded` + denied 留痕 |
| 计费+占预算 | ✅ | 召集 +2 落触发 run.token_cost；越 run 预算（cap 3）409 `convene_budget_exhausted`、成本停在 2 |
| 守卫复核 | ✅ | 未知引用 422 `source_ref_unknown` + meeting.degraded=true（独立事务，拒绝回滚不丢标注）；补正后封存放行 |
| 迁移可逆 | ✅ | conftest 每 session down→up 双跑（17 revision 全链）；`alembic check` 元数据比对通过（env.py 注册修复后） |
| 目录完整性 | ✅ | `test_meetings_catalog_readonly_three_only`：只读三条在目录、POST 路径零收录 |
| 变异闭环 | ✅ | 6 变异各「红→还原→绿」：M1 `t2_gate_satisfied→return True`（门拆除）→ gates 红；M2 限额 `>=→>`（松动）→ U7 红；M3 `existing is not None→False`（封存可变）→ M6 红；M4 `if unknown→if False`（守卫拆除）→ 守卫红；M5 计费 `+=2→+=0`（清零）→ 计费/预算双红；M6 `_record_denied_now` 首行 return（留痕吞噬）→ U1/U8 双红；还原后 3 文件 22/22 绿、`git diff` 零残留 |
| 全量 | ✅ | pytest **1563 收集 = 1557 passed / 6 skipped / 0 failed**（基线 1541 + 22 新用例；首跑抓出 env.py 模型注册缺失 + T-1 门适配两处，修复后复跑全绿）；vitest **695/695**（零改动）；typecheck 零错误 |
| ruff / mypy | ✅ | All checks passed / 基线 OK（当前 279，基线 289——顺带消化 10 处旧账，沿 d4 先例不动基线文件） |

**反假绿灯四条自检**：① 声明=断言（M2/M3/M4/M6/U1/U2/U7/U8 逐条有具名用例，docstring 判据对应断言体）；② 变异验证（6 处新逻辑逐点破坏全红，见上表）；③ 真执行（守卫/denied/封存断言全部真写真读 DB，无 mock 掉被测路径）；④ 数字实测（1563/1557/6/695/252/86/94 全部本轮命令实测，非抄录）。

## 四、下一轮建议 + 新登记差距（进台账）

**goal-d6（S1 收口 + 试点启动）**：
1. 降级链全链：L1 纯模型直连（只读工具+强制终审）/ L2 模板填空（d4 已接线）/ L3 handoff（d4 已接线）；`degraded` 全链路标注（UI+导出）。
2. V4（A-1/B-1/E-1 手动可触发）+ V11 degraded 标注 + V12 插件 disable 同步 + V3 后半（三重交集完整）。
3. `solutions.generate-agent` 路由 + `solution.agent_run_id` 自动接线（T-1 的 SOW export 行段同轮）。
4. 试点开关：30 天/20 run 计数器 + 拦截率/一次通过率/单会成本报告导出（UM-1）；O-8/UM-5 阈值机制挂起待数据。
5. 挂账迁移：run 卡死恢复（同步执行 crash 留 running 态）；真实 iptables 生效性 + 沙箱镜像内 zcode CLI 版本钉定（试点前人工联调）。

**新登记差距（进台账节二十九）**：
1. 会议成本并入触发 run 的台账聚合（U6 全量——本轮只落 convene 单次计费，话轮/收敛成本随 S2 编排器产生时归集）。
2. 会议模板内容蒸馏（D10：SOP 九卡/报价卡/门禁验收表/移交四件套）——S1–S6 全模板 + std/full 档随 d7（PM-1 待蔡工审定）。
3. T3 自主召集（reason 必填 U3）/ T4 高难度加座（U10，`min_difficulty` 列已预留）/ T5 降级恢复补审——d6/d7。
4. 修订回路 ≤2 轮 + 超限 `ai_manual_handoff`（U4，技术文档 §6 第 4 条）——d6。
5. 纪要作 Stage A/B 闸门证据引用（M10，走 `source_uri+sha256` 通道）——d6+。
6. 中断恢复（paused ≤24h，M7）——会议会话层随 S2 编排器（d7）。
7. 观测指标「评审后一次终审通过率」「强制门拦截率」——试点期（d6）埋点。
