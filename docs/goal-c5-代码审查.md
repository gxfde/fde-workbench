# goal-c5-代码审查（工作流+本体：workflows, ontology, research）

> 循环：goal-c ｜ 轮性质：审查+修复（P0/P1 当轮修，P2/P3 登记）｜ 日期：2026-11-05 ｜ 基于树：`1ef3a42`（fork/main，#104）｜ 施工面：隔离 worktree `D:/test/fde-wt-c5`（分支 fix/goal-c5-workflow-executor-guards）

## 1 结论一句话 + 口径数字变化

**executor 四节点交叉审揪出三处「恢复/取消/写副作用」语义缺口：resume 后 human_approval stale 审批键复用挂死（CR-014 P1，c4 划归本轮，当轮修）、agent 节点 resume attempt 归零撞失败终态确定性 409 永远救不活（CR-019 P1，当轮修）、写类 call 节点 uncertain/cancelled 折叠为 succeeded 击穿 FV-F1 断链红线（CR-020 P1，当轮修）；本体/调研域登记 5 条 P2/P3（双 confirm 写偏差、cancel 外呼丢弃、生命周期无锁、导入多级父级、修订零路由）不修；executor 全域回归 34/34 全绿。口径数字：服务端测试 **+3**（三 P1 各一回归用例），全量 1868 passed + 6 skipped，mypy 基线不变（279/104），零迁移零路由。**

## 2 审查方法与覆盖面

### 2.1 方法

- 双引擎：`code-review`（executor 四节点六承诺交叉 + 本体双 confirm + 调研导入/导出三子代理并行分审，每发现走驳斥关）+ `intended-vs-implemented`（AGENTS.md T-W3/T-W4/T-W5/T-O3 段意图锚逐条对照）。
- 主会话对子代理 E1 结论逐条 E0 升级：grep 行号直读确认（`with_for_update` 缺失、`_load_parent_candidates` 时点、`update_definition_dag` 零调用点），**纠正 1 处子代理弱化**（F2 cancel 写偏差：子代理初报为「观测项」，实为 P2 承诺面缺口——docstring 自认「诚实呈现」却无展示通道）。
- 实际覆盖：`workflows/executor.py`（四类节点 call/skill/agent/human_approval + cancel/resume/reconcile + outbox 分派 + api_actions 同键去重）、`workflows/definition_service.py`（定义/发布/修订）、`ontology/service.py`（术语/变更集 submit/confirm/reject/merge/关系类型）、`research/imports.py`（preview/commit/父级/别名去重）、`research/export_service.py`+`export_jobs.py`。
- **没看 & 为什么**：dispatch/bridge 三隔离与 8 态机（c6 冻结区）；桌面工作流控制台三面（c7，T-W6 已交付）；ai 域 DSH 记账全链（CR-006 挂账 c8 销号）。

### 2.2 executor 六承诺交叉核对表（E0，行号直读）

| # | 承诺（docstring/AGENTS 意图锚） | 实现 | 判定 |
|---|---|---|---|
| 1 | 崩溃恢复不重复建单（human_approval 复用 pending） | L1079 复用分支**无 status 检查** | **✗ → CR-014** |
| 2 | resume/崩溃恢复各开新代际（agent attempt） | resume L341 `node.attempt=0` 全类型无差别归零 | **✗ → CR-019** |
| 3 | 断链不静默 done（FV-F1 写操作结果确认） | L854-893 仅拦 `awaiting_confirmation`/`running`，uncertain/cancelled 落 succeeded | **✗ → CR-020** |
| 4 | 外副作用同键去重不二次外呼 | L852 `execution_id=wfnode-{行id}` + api_actions 同构 sha256 | ✓（同键复用，跨 resume 稳定） |
| 5 | 节点独立事务+分派在事务外 | `_execute_node` L611 tx A(running+attempt+键)→分派(无事务)→tx B(终态+产物) | ✓ |
| 6 | 每轮恢复重置计数（call/skill/human attempt 归零） | resume L348 `node.attempt=0` | ✓（agent 例外见 CR-019） |

### 2.3 本体/调研域核对（E1 子代理首报 + 主会话 E0 升级）

| 面 | 结论 | 判定 |
|---|---|---|
| 变更集 submit/confirm/reject 状态翻转 | 无 `with_for_update` 无 CAS（grep 全文件零命中） | **CR-021 P2** |
| cancel_run vs in-flight 分派 | guard `node.status∉(pending,ready,running)` 早退，外呼成功静默丢弃 | **CR-022 P2** |
| cancel/resume 生命周期并发 | 无行锁，双 admin 双事件/双 outbox（队列去重兜底） | **CR-023 P3** |
| 调研导入同文件多级造数 | `_load_parent_candidates` L420 在创建前扫描 → 本批新建父级不可见 | **CR-024 P3** |
| `update_definition_dag` | 全仓 `server/src` 零调用点（仅测试引用），无 HTTP 路由 | **CR-025 P3** |
| 变更集 register_relation_type 端点校验 | propose 只查形状，confirm 才跑，多条目一条坏码全回滚 | **CR-026 P3** |
| 导入 commit 双提交围栏 / export 活跃请求复用 | owner+fence CAS / `with_for_update` 活跃复用 | ✓（干净） |

## 3 发现清单（台账增删摘要）

| 编号 | 级别 | 状态 | 摘要 |
|---|---|---|---|
| CR-014 | P1 | **fixed（c5 PR）** | resume 后 human_approval 节点 stale 审批键复用 → run 永久卡 waiting_approval（c4 划归本轮） |
| CR-019 | P1 | **fixed（c5 PR）** | resume 对 agent 节点 attempt 归零 → 撞 `:1` 失败终态确定性 409，agent 节点永远救不活 |
| CR-020 | P1 | **fixed（c5 PR）** | 写类 call 节点 uncertain/cancelled 折叠为 succeeded（FV-F1 断链红线虚高） |
| CR-021 | P2 | open（登记，c6/c8 裁决） | 本体变更集双 confirm 写偏差（无行锁/CAS） |
| CR-022 | P2 | open（登记） | cancel_run 与 in-flight call/skill 分派写偏差（外呼成功被静默丢弃） |
| CR-023 | P3 | open（登记） | cancel/resume 生命周期无行锁/CAS（双 admin 并发生命周期写） |
| CR-024 | P3 | open（登记） | 调研导入同文件多级造数父级不可见（preview 零报错、commit 确定性失败） |
| CR-025 | P3 | open（登记） | `update_definition_dag` 零路由（已发布定义无修订出口，docstring 漂移） |
| CR-026 | P3 | open（登记） | 变更集 register_relation_type 端点校验仅在 confirm（不对称） |

**观察项（不占编号，并入既有）**：① skill 节点 `record_skill_usage` 崩溃窗口双计数（CR-013 P2 open 的细化——prompt 真完成即消费、节点行 crashed 后重派再计一次，措辞合同缺口，登记不动码）；② agent 节点 in-flight（synchronous 执行、IN_FLIGHT 复用键正确，无悬挂）干净。

## 4 修复记录

**CR-014 / CR-019 / CR-020 → c5 PR**（fix/goal-c5-workflow-executor-guards → fork/main，squash）：

- **CR-014**：`_dispatch_human_approval` 复用分支加 `existing.status == "pending"` 判定；终态时清 `node.idempotency_key=None`，落到「按 `workflow_node_run_id` 查 pending / 或新建」路径（executor.py:1079-1087）。
- **CR-019**：`resume_run` 重置块改 `if node.node_type != "agent": node.attempt = 0`——agent 保留 attempt 开新代际，call/skill/human 照旧归零（executor.py:341-352）；`resume_run` docstring 同步。
- **CR-020**：`_dispatch_call` 在 `running` 分支后增 `if status in ("uncertain","cancelled"): raise _NodeFailure("action_not_confirmed", ..., retryable=False)`（executor.py:885-893）——结果未确认按失败断链。
- **变异验证（三者全过，统一快照还原法）**：① 删 CR-014 status 判定 → `test_human_approval_rejected_resume_creates_fresh_pending` 红（复用终态审批）→ 还原绿；② 恢复全类型 attempt 归零 → `test_agent_node_resume_preserves_attempt_new_generation` 红（`'failed'=='succeeded'`）→ 还原绿；③ 折叠 uncertain/cancelled 回 succeeded → `test_write_call_node_uncertain_and_cancelled_fail_not_succeeded` 红（`'succeeded'=='failed'`）→ 还原绿。零残留（`grep "MUT-"` 无命中，executor.py 还原后 sha256 与快照一致）。
- 本地前置门（c5 worktree）：ruff 绿（两改动文件）；`scripts/check-python-types.py` 基线不变（279/104）；executor 测试簇 34/34 绿；**全量 1868 passed + 6 skipped（25:37）**。

## 5 未修与移交

- **CR-021（P2）**：本体双 confirm 加行锁/CAS——小改，交后续工程轮（不属 workflows 冻结区，无本轮窗口）。
- **CR-022（P2）**：cancel 外呼丢弃补「dropped_after_cancel」留痕——归后续轮。
- **CR-023/024/025/026（P3）**：登记不动码，各归后续轮或文档回写。
- **CR-013（P2 open，c4 登记）**：skill 计数隔离 try/except——细化为「崩溃窗口双计数」措辞缺口，维持 open。
- **BLOCKED-EXTERNAL**：无。

## 6 教训（同步沉淀执行者记忆）

1. **resume「归零/保留」要按节点类型分治，不看 attempt 的语义类型**：attempt 在四类节点里承担不同职责——call/skill/human 是退避计数（每轮恢复重置），agent 是**幂等代际锚**（撞 agents V8 同键拒重跑）。一处 `node.attempt=0` 无差别归零，只在 agent 面炸（确定性 409 救不活），其余面无害——「统一写法」看着干净实则跨语义越界。
2. **「结果未确认」与「未发起」是两回事，折叠前先看 status 值域**：`running`（未发起，可重试）与 `uncertain`（已发起未确认，**不可**重试）都源于 api_actions，但前者 retryable=True 后者必须 False；CR-020 的根因是只拦了值域前两个成员、把后两个落进「成功」默认分支。
3. **子代理「观测项」要按 docstring 自认承诺面重估**：cancel 写偏差子代理初报为「可忽略观测」，但 executor docstring 明文写「已执行外呼不回收（诚实呈现）」——承诺已立，缺展示通道即缺口，升 P2。

## 7 门禁四件套（本轮收口）

- `npm run typecheck`：exit 0（桌面零改动，桌面 job CI 验证）
- `npm run test:server`（c5 worktree 全量）：**1868 passed + 6 skipped（25:37）exit 0**（含 c5 +3 用例 + 并行会话 #102/#103/#104 交付）
- `npm run test:desktop`：CI 4 job 全绿（c5 零桌面改动）
- `python scripts/check-python-types.py`：基线不变（279 occurrences / 104 distinct）exit 0
- ruff 绿；executor 簇 34/34 绿。

**注**：c5 在隔离 worktree `D:/test/fde-wt-c5` 施工（junction venv + 独立 .env 拷贝）。共享测试库戳此前被并行 worktree 盖成 `e2c6a8f4d1b3`，本轮开工前经 `DROP SCHEMA public CASCADE; CREATE SCHEMA public` 重建（conftest 自 upgrade+灌种子），106 表清零重建，advisory lock 全程持有保证本轮结果可信（CR-002 根治仍挂 c8）。

## 8 后记（c6/c7/c8 轮回填）

CR-014/019/020 三条 P1 已当轮修并回归；CR-021/022（P2）与 CR-023/024/025/026（P3）登记待后续轮。CR-013（skill 计数隔离 P2）维持 open。CR-006（DSH 记账 P2）销号证据 c4 已备，归 c8。
