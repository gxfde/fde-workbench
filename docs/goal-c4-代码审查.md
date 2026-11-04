# goal-c4-代码审查（智能体执行域：agents, ai, skills, jobs, meetings）

> 循环：goal-c ｜ 轮性质：审查+修复（P1 当轮修）｜ 日期：2026-11-04 ｜ 基于树：`6cccedb`（fork/main，#99）｜ 施工面：隔离 worktree `D:/test/fde-wt-c4`（分支 fix/goal-c4-agent-budget-and-resume-guards）

## 1 结论一句话 + 口径数字变化

**幂等键全链审计揪出「跨通道/跨重试/异常逃生」三类缝隙：retry 通道绕过平台月度预算闸（CR-012 P1，当轮修）、适配器非 SandboxError 异常路径沙箱容器泄漏（CR-015 P1，当轮修）、上下文 source_refs 脱敏双标尺（CR-017 P2，当轮修）；登记 3 条（CR-013 skill 计数无隔离 P2、CR-014 resume 审批键失活 P1 划归 c5、CR-016 outbox 死信箱 P3）；预算/超时/脱敏承诺核对 8 条全 ✓（fail-open 预算闸为有意设计、L2 超时终态收口、产物内容面脱敏依赖沙箱纪律=机制缺口登记）。口径数字：服务端测试 +3（retry 月度闸 1 + 沙箱异常回收 1 + refs 脱敏 2 拆成两例），零迁移零路由。**

## 2 审查方法与覆盖面（幂等键表 + 承诺核对表落报告）

### 2.1 方法

- 双引擎：`code-review`（幂等键全链 7 候选 + 预算/超时/脱敏 9 候选走驳斥关）+ `intended-vs-implemented`（agent-policy-v1/AGENTS.md T-W3-T-W5/T-S2 段意图锚逐条对照）；3 个子代理并行分审（① 幂等键全链表 ② 预算/超时/脱敏 ③ skill 治理+T-S2 计数+jobs outbox/reconcile+治理路由闸序），主会话逐条 E0 升级并**纠正 3 处子代理误判**（见 §6 教训）。
- 实际覆盖：`agents/`（service _finalize/handoff/retry/recover + adapter 三段 + context 脱敏 + signoff + tools 三重交集 + pilot + quota）、`ai/`（deepseek/kimi 预算门 + auditing 核算面 + 各域服务）、`skills`（control/models SkillDefinition/SkillVersion + extensions_service 治理路由 + 三处消费面 published 收敛核实）、`jobs/`（outbox/queue/reconcile/worker/handlers）、`meetings/`（convene 三重白名单 + T1/T2/T6 评审门联动 + 纪要封存防伪造）。
- **没看 & 为什么**：dispatch 三隔离与 8 态机（c6 冻结区）；ai 域 DSH 主路径记账全链路（CR-006 挂账 c8 销号，本轮只确认 `ai/deepseek.py:126` 直连门存在、`ai_server_client.execute_ai_prompt` 不过 agent 月度闸——与 c2 一致）。

### 2.2 幂等键表（键 × 写入方 × 消费方 × 重试路径，E0）

| 键 | 约束 | 写入方 | 重试/恢复行为 | 判定 |
|---|---|---|---|---|
| `workflow_runs.idempotency_key` | UNIQUE | executor.start_run L218 | cancel/resume 不触碰 run 键；resume 只重置节点 | ✓ |
| `workflow_node_runs.idempotency_key` | 表级可空 | 写类 call 节点 L696-699（api_actions 同构 sha256，分派前落）；human_approval L1137（=审批 id） | resume 保留键（测试 L995-1022 钉「恢复不换键」）；**human_approval stale 键失活=CR-014** | ⚠ |
| api_actions `identifier`（sha256） | Redis 锁 180s | execute_api L121-122 | 同节点跨 resume 键不变（execution_id=`wfnode-{行id}` 复用）→ 不二次外呼 ✓；**uncertain 折叠 succeeded=CR 观察项**（见下） | ⚠ |
| `agent_runs.idempotency_key` | 普通索引（注释：唯一约束封死重试链） | start/retry/workflow agent 节点 `wfnode-{id}:{attempt}`/rehearsal 前缀 | completed/在途复用；终态失败 409 `agent_run_retry_required`；**resume attempt 归零 → 同键命中 failed → 确定性 409（观察项，文档口径「开新代际」与实现矛盾）** | ⚠ |
| `automation_approvals.request_key` | UNIQUE(run_id, request_key)，workflow 行 run_id=NULL 实际失效 | executor L1111 | 防重只靠服务层双 SELECT（同事务）→ 防线纵深缺失（P3 观察） | ⚠ |
| `background_jobs (job_type,target_id)` 单活 | active 复用/终态开新 | queue.py L51-73 | reconcile 租约过期/孤儿 300s → recoverable 重投/耗尽 failure hook（**四类型无 hook=CR-016**） | ⚠ |

**跨重试/恢复缝隙专项结论**（子代理 ① 第 3 面交叉验证）：resume 后 `execution_id` **复用**（取节点行 id，不新建行）→ 「同节点跨 resume 二次外呼」**不成立**；真实缝隙在 CR-014（审批 stale 键）与 uncertain 折叠（写操作结果未确认被标 succeeded，下游占位符缺键才打 failed——不静默 done 但节点层「成功」断言虚高，**登记观察不修**）。

### 2.3 预算/超时/脱敏承诺核对（8 条，E0）

| # | 承诺 | 判定 | 证据 |
|---|---|---|---|
| 1 | start 过 agent_monthly_budget 平台闸 | ✓ | service.py:815-816 |
| 2 | **retry 也过月度闸** | **✗ → CR-012（当轮修）** | retry_run 925-1005 全文无 `_platform_month_spent` |
| 3 | ai_monthly_token_budget 直连面拒发不产生供应商请求 | ✓ | deepseek.py:117-147（409 语义、校验在 POST 前） |
| 4 | 预算闸 fail-open（设施故障放行） | ✓ 有意 | deepseek.py:118 注释 + :146 except 仅 warning |
| 5 | 超时→timeout 终态+产物不入库+L2 | ✓ | adapter.py:144-148 / service.py:445-447 |
| 6 | 超时 run 可 retry 受 V8 家族上限 2 + 指数退避 | ✓ | service.py:95/939-947/962-975 |
| 7 | 非 SandboxError 异常路径容器不悬挂 | **✗ → CR-015（当轮修）** | adapter.py:179 kill 在 try 外顺序执行 |
| 8 | 上下文脱敏「产物 grep 真实客户名/盘符零命中」 | ⚠ 仅渲染文本面成立；**source_refs 双标尺 → CR-017（当轮修）**；产物内容面=沙箱纪律非机制（登记） | context.py:146-165 + 测试强度评估 |

**DSH 记账腿（CR-006 挂账）本轮取证**：`ai/deepseek.py:149-156` DSH 成功路径直接 return 无审计落账；`control/ai_server_client.py`/`ai/kimi.py` grep `AICallAudit`/budget 零命中 → **`dsh_enabled=true` 时 `ai_monthly_token_budget` 对该面恒放行**（kimi 连直连腿预算门都没有）——CR-006 的「NEEDS-EVIDENCE」升级为 E0 结论，销号归 c8（预算口径仍属用户裁决面，登记不动码）。

## 3 发现清单（台账增删摘要）

| 编号 | 级别 | 状态 | 摘要 |
|---|---|---|---|
| CR-012 | P1 | **fixed（c4 PR）** | retry_run 绕过平台月度预算闸（跨月 retry 形同虚设） |
| CR-013 | P2 | open（登记，c5 评估） | skill 节点 `record_skill_usage` 无隔离——计数侧 DB 故障升级为消费侧故障（双份 AI 成本+状态背离） |
| CR-014 | P1 | open（**划归 c5 修**，workflows 轮次与 executor 全域回归一并按） | resume 后 human_approval 节点 stale 审批键复用 → run 永久卡 waiting_approval（唯一出口=cancel） |
| CR-015 | P1 | **fixed（c4 PR）** | 适配器非 SandboxError 异常路径沙箱容器泄漏（kill 顺序在 try 外） |
| CR-016 | P3 | open（登记，c8 基建轮裁决） | outbox 终态机未实装（审计死信箱）+ RECOVERABLE 四类型缺 failure hook（业务行悬空） |
| CR-017 | P2 | **fixed（c4 PR）** | 上下文渲染 source_refs 不经模式遮蔽（双标尺）；「产物 grep 零命中」断言自身从未测 refs 毒化面 |

**观察项（不占编号）**：① api_actions `uncertain` 被 workflow 折叠为节点 succeeded（不静默 done，但「成功」断言虚高，登记）；② workflow agent 节点 resume attempt 归零 → 同键命中 failed 终态 → 确定性 409（docstring「resume 开新代际」与实现矛盾，文档口径缺口，c5 按）；③ agent start 同键并发窗无唯一约束+无应用锁（注释认账取舍，低危）；④ `automation_approvals` 唯一约束对 workflow 行（run_id NULL）实际失效，防重靠服务层双查（纵深缺失）；⑤ convene 计费（run.token_cost +=2 独立提交）被 _finalize 绝对赋值覆写 + 工具面召集入口缺失（T1 agent 自动召集语义悬空）——两腿同源，工具面接线属新能力面，登记观察；⑥ 治理路由：PATCH 弃用向无 `skill_deprecated` 事件（审计不对称）/ 发布闸②schema 校验未实装（PROPOSED 已裁决放弃）/ in_review 无 reject 出口（同 key 重存静默换版）——三条均为设计缺口留痕，P3 观察；⑦ 治理读面任意登录用户可读公共 Skill 的 draft/in_review 版本正文与 test_report（可见性口径，非 published 收敛缺口——三处消费面已齐、无第四处）。

## 4 修复记录

**CR-012 / CR-015 / CR-017 → c4 PR**（fix/goal-c4-agent-budget-and-resume-guards → fork/main，squash）：

- **CR-012**：`retry_run` 家族上限检查后补同型月度闸（`budget>0 ∧ _platform_month_spent≥budget → 409 agent_budget_exhausted`），与 start 闸同口径同错误码。测试 +1（月花 100/预算 100 → retry 409 且家族不增；预算 0 对照放行）。
- **CR-015**：`ZcodeAdapter.run` 拆 `_listen_and_reclaim` 子方法，监听+扫描整体置于调用方 `try/finally`，`sandbox.kill()` 唯一回收点（幂等）。测试 +1（ExplodingProvider → RuntimeError 上抛且 `kill_count==1`）。
- **CR-017**：`render_masked_context` 的 `item_refs` 构造先过 `redact_patterns`（与正文同尺），`problem_refs` 收已遮蔽形态（产物校验对账同规）。测试 +2（毒化 refs 零原文命中 + 遮蔽计入 redactions）。
- **变异验证（三者全过）**：① 删 retry 月度闸 → 409 断言红（201 放行）→ 还原绿；② kill 还原为顺序调用（异常路径 kill_count=0）→ 沙箱回收用例红 → 还原绿；③ refs 还原为原样透传 → 2 个脱敏用例红 → 还原绿。零残留（`grep "if False"` 类探针无命中）。
- 本地前置门（c4 worktree）：ruff 绿；`scripts/check-python-types.py` 基线不变（279，artifacts 注解已补）；agent/meeting/sandbox 簇 74/74 绿。

## 5 未修与移交

- **CR-013（P2）**：`_dispatch_skill` 计数调用包 try/except（记 warning 不冒泡）——归 c5 workflows 轮次（executor 全域深审时一并按）。
- **CR-014（P1）划归 c5**：workflows/executor 修（L1058 加 status 判定 + 清键），与 c5 executor 回归同 PR 更稳。
- **CR-016（P3）**：c8 基建轮与 outbox 语义一并裁决（补 hook vs 文档降级）。
- **CR-006 销号证据已备（c8 用）**：DSH/kimi 记账腿 E0 结论见 §2.3；预算口径归属仍属用户裁决面（NEEDS-DECISION 候选，不动码）。
- **观察项 ①②⑤⑦**：登记不修，各归后续轮（②⑤ c5/c6，⑦ 桌面 c7）。
- **BLOCKED-EXTERNAL**：无。

## 6 教训（同步沉淀执行者记忆）

1. **「在发起前拦截」的闸要数通道**：平台月度闸只挂在 start，retry 是第二发起通道——凡「发起前」语义的闸，审计时枚举全部能创建新执行的入口（start/retry/recover/工作流分派），逐通道核；漏一条=封顶在该通道形同虚设。
2. **顺序调用的 kill/回收在异常路径必然失效**：「正常路径恒定回收」的断言只覆盖正常路径——资源回收必须走 finally，且变异验证要专测「非预期异常类型逃出」的路径（本仓 SandboxError 之外的异常=测试盲区，ExplodingProvider 注入是通用手法）。
3. **「grep 零命中」断言要审它自己**：脱敏承诺的既有测试样例全用良形 refs（`src-1`），毒化 refs 路径从未被测——复审承诺类断言时先问「断言面覆盖了承诺面的哪个子集」。
4. **子代理的 E0 结论仍要重算**：子代理把 `deviation_pct Numeric(7,4)` 读成 9999.9999（实为 999.9999，c3 同型教训再中）；本轮另纠正两处——「resume 开新代际」的 docstring 承诺（实为 attempt 归零）与「四类型缺 hook 概率极低」的弱化（实为 docstring 自称根治的五连死场景）。**子代理引文要按 DDL/注释语义复核一遍再定触发数字。**

## 7 门禁四件套（本轮收口）

- `npm run typecheck`：exit 0（桌面零改动，桌面 job CI 验证）
- `npm run test:server`（c4 worktree 全量）：**1860 passed + 6 skipped（26:06）exit 0**（含 c4 +3 用例 + 并行会话 #100/#101/#102 交付）
- `npm run test:desktop`：CI 4 job 全绿（c4 零桌面改动；本地口径 752，与 c3 一致）
- `python scripts/check-python-types.py`：基线不变（279 occurrences / 104 distinct）exit 0
- ruff 绿；agent 簇 74/74 绿。
- **CI 4 job 全绿 → PR #103 squash 合并 `c8aa08a`**（mergedAt 2026-11-04T14:09Z）；本地 main 经 `update-ref` ff 至 fork/main（其间并行会话合入 #100 T-G2/#101 T-O4b UI/#102 T-O4 UI，口径变化归各轮），分支本地+远端已删；`main...fork/main` = 0 0。

**注**：c4 在隔离 worktree `D:/test/fde-wt-c4` 施工（junction venv + 独立 .env 拷贝），主工作区被品牌轮+多会话占用（C-7）；commit 走 `--no-verify` 前等效检查（pre-commit 全量 pytest 26:06 exit 0 + ruff + mypy 均前置完成），CI 四 job 兜底。

## 8 后记（c5 轮回填）

CR-014（resume 审批键失活，P1）+ 子代理 F2/F3（agent resume 代际碰撞 + uncertain 折叠 succeeded，P1）划归 c5 workflows 轮与 executor 全域回归同 PR；CR-013（skill 计数无隔离 P2）、CR-016（outbox 死信箱 P3）归 c8。
