# AI 原生化 N1 真实订单首跑复盘 v1（2026-11-09）

**一句话结论**：首跑**已真实执行**（幂等键 `n1-somwyn-host-001`，非 sim/演练前缀 ✓）——**机械面全链通过**（宿主通道分支行使、前置③票据发行+校验+指纹落库、fail-closed 终态合同），**业务面被 GLM Token Plan 供应商配额（错误 2056）阻断**：run 终态 `failed`＋L2＋**零计费**＋零候选登记。G-01/G-07 维持 **OPEN**，待供应商配额恢复后**重跑**（重试决策＝蔡工，H4 不代重试）；本复盘不宣称 N1 完成。

---

## 1. 执行事实（活库行级留痕）

| 项 | 值 |
| --- | --- |
| run_id | `fa6ec37f-4a9d-4013-99a0-10ffe1edd978` |
| 幂等键 | `n1-somwyn-host-001`（**非 `sim:`/`rehearsal:` 前缀**——G-01 判据形态面 ✓） |
| 项目 | somwyn（代号 `FDE-20261025-9BF8E4AE`，`7042d7ab-bc25-4726-a456-b6af674ce901`） |
| 智能体 | 售前智能体 `4410538c-17a1-499d-817e-cb8060a90795`（capability `agent.module.presales`，kind=zcode） |
| 发起人 | `admin`（蔡工主账号；审阅动作按 D-1 由蔡工本人经第二账号 `pilot.reviewer` 另行执行） |
| 事件 | `agent_run_created` @ 2026-11-09 11:35:10 UTC |
| 终态 | `failed`，`fallback_level=L2`，`exit_code=1`，`duration_ms=316869`（约 5.3 min），`token_cost=0`（**零计费**） |
| 执行证据 | `execution_provider=host_channel`；`authorization_id=717cf5e0f7b65f87d6efa64af485c3e7ab3e6b12d24682a2b64f8d420f140293`（**64 hex 指纹，非票据本体**）；`workspace_ref=D:\test\agent-workspaces\fa6ec37f-…`（归一化工作区） |
| 产物/候选 | `output/` 空（zcode 未产出）；`project_evidence` 中 `captured_from=agent_run:fa6ec37f…` **0 行** |
| 通道环境 | 宿主裸跑态：`FDE_AGENT_HOST_CHANNEL_ENABLED=1`＋zcode bin/cjs＋工作区根 `D:\test\agent-workspaces`（真相层之外）；容器内 server 不参与本次执行（T-Z1 裁定 A 前提） |

## 2. 机械面逐项验证（本轮首跑真实行使）

| # | 机械面 | 首跑证据 | 结论 |
| --- | --- | --- | --- |
| 1 | 宿主通道分支（T-Z1 裁定 A） | `execution_provider=host_channel` 落库 | ✅ 真实行使 |
| 2 | **前置③ 票据发行+校验+指纹**（#247 `authorize_host_run`） | `authorization_id` 落 64 hex 指纹、`workspace_ref` 落归一化工作区；校验通过后才开始 spawn | ✅ **真实订单行使面验证**（此前仅结构面/测试面） |
| 3 | 策略层工作区根锚定（P1-1） | `workspace_ref` 落在 `FDE_AGENT_WORKSPACE_ROOT` 内 | ✅ |
| 4 | **fail-closed 终态合同** | zcode `exit 1` ⇒ `failed`＋L2＋`token_cost=0` | ✅ 活体验证（失败不裸奔、不虚计费） |
| 5 | G-07「仅 completed 登记」语义（#247） | failed run 零候选登记（`evidence_candidates=0`） | ✅ 活体验证（失败产物是留痕不是候选——本 run 无产物可留，语义一致） |
| 6 | 上下文脱敏（红线②） | `context.md` 全代号化（项目代号+沙箱纪律，零客户真实资料） | ✅ |

## 3. 失败根因取证（外部依赖，非代码缺陷）

- 通道内失败无 stderr 留痕（边界⑨：stdout 仅解析、stderr 显式丢弃）⇒ 按 T-Z1 真机实测同款做**最小直连诊断**（非生产 run，诊断工作区在真相层之外、取证后已清理）：
  - `zcode -p "回复一个字：好" --json` ⇒ `EXIT=1`，stderr 重复报 **「已达到 Token Plan 用量上限：请升级 Token Plan 套餐或购买积分补充用量。(2056)」**，`AI_APICallError` / `Turn execution failed (traceId: 40318c2e-48b4-415c-8f20-7bfff9a0beca)`。
- **同族互证**：与 #235（V31-P1b）自报的 MiniMax Token Plan 429 同族（供应商计费配额，非代码问题）；与 **#248**（V31-P1c 部署回填「rerun 撞供应商计费闸」）独立互证——两线同日撞同一堵供应商配额墙。
- 判定：**外部依赖阻断**（与任务书 §6.1 前置①「商用条款」同族的外部挂账项，非本仓缺陷；fail-closed 合同按设计把失败拦在零计费侧）。

## 4. 与 12 条安全前置的关系（诚实口径）

- 前置 **③（短期授权票据）**：由「结构面已接线」升级为「**真实订单行使面已验证**」（指纹落库＋spawn 前校验通过）。
- 前置 **①（商用条款）/⑦（宿主网络无代码级限制面）**：**维持未过、不声称**（本次执行以最小工作区＋代号化承担风险，挂账不变）。
- 前置 **8（cancel 未接线/进程树回收未验证）/11（无独立危险操作二次确认面）**：维持「部分」，本次未新增证据。
- 红线全束维持：零客户资料入库（context 全代号）、产物零入库（无产物）、AI 不代拍板/不代重试、单订单单通道。

## 5. 遗留与下一步

1. **重跑（决策＝蔡工）**：GLM Token Plan 配额恢复（供应商侧窗口重置或升级套餐）后，可 `retry_run`（failed 终态、售前类＝内副作用 retry 族允许）或以新幂等键重发。**H4：不代发起/接管/重试**——本复盘只留操作面，不代执行。
2. **G-01/G-07 CLOSED 判据**（台账 v1.5 维持 OPEN）：待 completed run 的产物→候选登记（G-07 判据兑现）→ 蔡工经 `pilot.reviewer` 走人工接受与 G7/G8/G9 拍板（G-01 判据至 G9）。
3. **容器栈 rebuild 挂账**：#247 已合并，`fde-wt-v31p2` 部署基的容器栈（api/worker/scheduler）**待部署归属方 rebuild+recreate**（本轮回写 PR 不越权接管他会话栈；本次首跑起跑面为宿主裸跑态，不依赖容器栈；#246 部署已将活库 alembic 头推至 `e7b2c4d9f1a3`，本轮零迁移）。
4. **运维脚本小修**（随回写 PR）：`scripts/agents/real_order_host_channel_run.py` 文件头 docstring 非 raw 字符串触发 `SyntaxWarning: invalid escape sequence '\s'`（纯提示性告警，改 raw 字符串消除）。
5. 首跑工作区 `D:\test\agent-workspaces\fa6ec37f-…` 与 run 行**保留不清理**（可追溯留痕）。

## 6. 阻塞原因三段演进（台账口径）

| 阶段 | 台账版本 | G-01/G-07 阻塞原因 |
| --- | --- | --- |
| D-1 前 | v1.3 | 闸未开（业务闸未拍板） |
| D-1 后 | v1.4 | 首跑前置未清（③票据/G-07 生产者/抽取腿复测/开关说明行） |
| **首跑后（本轮，v1.5）** | v1.5 | **首跑已执行——机械面全链通过；业务面待供应商配额恢复后重跑** |

---

## 7. 重跑二补记（2026-11-09 晚，配额恢复后；台账 v1.6）

**一句话**：蔡工拍板「确认重跑」后重跑执行（幂等键 `n1-somwyn-host-002`）——**配额面解除**（zcode exit 0 真实执行 221.8s／`token_cost=769055` 真实计费），**业务面推进到 C-1 产物校验闸后被结构性死锁拦下**：somwyn 无 confirmed 引导分析 ⇒ `problem_refs=∅`（known_refs 空集），任务书令「source_refs 只取已确认问题值、不要自创」⇒ 智能体如实写空数组 ⇒ C-1 `missing_source_refs` 把全部 5 产物判死 ⇒ run failed＋`ai_output_intercepted`＋422。**智能体行为完全正确；这是验证层的语义缺口**（「暂无已确认业务问题」＝售前发现期合法态，产出的 discovery-questions 本就是用来确认问题的）。G-07「仅 completed 登记」语义二次活体验证（failed run 零候选）。

| 项 | 重跑二值 |
| --- | --- |
| run_id | `a5773e26-6ee3-4637-b2dc-2f89016035c6` |
| 终态 | `failed`（degraded_reason=`artifact_validation_failed`），`exit_code=0`，`duration_ms=221780`，`token_cost=769055`（真实计费） |
| authorization_id | `9f609637135e8b2d…de02681`（新指纹，前置③票据二次行使） |
| 产物 | 5 行落库（presales-brief／assumptions／discovery-questions／README＝doc，manifest.json＝config；sha256+size+mime 逐行正确＝#247 MIME 修复活体验证），`reviewed=False` 全部 |
| evidence_candidates | 0（仅 completed 登记，failed 语义二次成立） |

**修复（随轮 PR）**：`_finalize` C-1 校验改 `if not artifact.source_refs and known_refs`（known_refs=∅ 时空引用放行；自创引用仍拦；有确认问题时追溯义务零松动）＋任务书模板补空态指引（「暂无已确认业务问题时 source_refs 写空数组 []」）；NEW 回归钉 1 例＋既有 `extra.bin` 断言按新语义收窄；`service.py` 1833→1835（预算 1836 内）。**G-01/G-07 维持 OPEN**——判据「completed run→候选登记→人工接受→至 G9」待**重跑三**（决策＝蔡工，H4 不代发起）；重跑二 5 产物与 run 行留痕保留（`pilot.reviewer` 可随时人工盘点留痕，不依赖重跑三）。
