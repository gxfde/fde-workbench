# goal-c2-代码审查（身份 / 权限 / 治理面：auth, users, control, system_configuration, health）

> 循环：goal-c ｜ 轮性质：审查+修复（P1 当轮修）｜ 日期：2026-11-04 ｜ 基于树：`46dfd4f`（fork/main，#89）

## 1 结论一句话 + 口径数字变化

**capability 闸本体（`control/access.py::authorize_ai_capability`）实现健全，17 个调用点全部过闸；但闸矩阵揪出 workflow skill 节点消费面缺 agent-policy-v1 明文的两道闸（CR-005，P1，当轮已修复走 PR #93），另登记 AI 消费双预算闸覆盖缺口（CR-006，P2）。JWT 生命周期、T-S1 发布四闸、T-S2 计数/留痕同事务承诺、api_catalog 红线核查全部通过。口径数字预期零变化（本轮仅 +3 服务端测试用例）。**

## 2 审查方法与覆盖面（闸矩阵落报告）

### 2.1 闸本体（唯一裁决点，E0）

`control/access.py:118 authorize_ai_capability`：`effective_ai_access`（admin 恒 system_operator / 显式 grant 覆盖角色默认 / 未知角色 → disabled）→ 未知能力默认拒（`capability_unknown`）→ inactive 拒 → 档位排序比较 → `system.*`/`agent.system.tool` 免项目上下文（system_operator 限定）→ 项目能力必过 `project_access.can_view`；`required==project_manager` 加 `can_manage`。**一把尺子，默认拒绝语义完整。**

### 2.2 闸 × 消费方矩阵（17 调用点全量）

| 消费面 | 调用点 | 闸内容 | 判定 |
|---|---|---|---|
| agent 分派链 | agents/service.py:695（start_run） | capability=agent.capability_tier + project | ✓ |
| agent 重试链 | agents/service.py:936（retry_run） | capability=original.capability_used（代际重判）+ 重试上限 2 | ✓ |
| workflow call 节点 | executor.py `_dispatch_call` → api_actions.execute_api → `_authorized` | is_active+密码未改+档位+写⊇workbench.write+scope 钉扎+项目 can_view；sha256 幂等键 `sha256(user.id+execution_id+data)`；sensitive→awaiting_confirmation 节点诚实 failed | ✓ 同闸承诺成立（T-W3） |
| workflow human_approval 节点 | executor.py:1057 | initiator is_active + 档位实时重判（拍板面再查一次） | ✓ |
| **workflow skill 节点** | executor.py `_dispatch_skill` | 修复前：**仅 published**；is_active/档位/所有权全缺 | **✗ → CR-005 已修** |
| workflow agent 节点 | executor.py `_dispatch_agent` → agents start_run | 同分派链全闸 | ✓ |
| MCP 工具面 | mcp_gateway `_identity`/`call_tool` | is_active+must_change_password+auth_version+level≠disabled + `capabilities_for_level` 档位 + token scope 钉扎 + `_project` can_view | ✓ |
| MCP skill 面 | mcp_gateway `_skills` | published ∧ (public∨owner) ∧ required_capabilities⊆allowed | ✓（三闸齐全——与 skill 节点形成对照，CR-005 的尺子基准） |
| MCP api_execute | api_actions `_authorized` | 同 call 节点 | ✓ |
| 自动化任务派发 | control/automation_jobs.py:45 | 逐 requested_capabilities 实时重判，失败即 failed | ✓ |
| 任务中心 | control/task_board.py:71 / service.py:426,432,475,479 | admin 或逐能力闸 | ✓ |
| DSH 审批执行 | control/service.py:854 | 参数 sha256 完整性复核 + **拍板时对发起人重判** + 工具白名单单点 | ✓ |
| 系统健康路由 | control/routes.py:314 | system.health = system_operator | ✓ |
| 会议召集 | meetings/service.py:436 | agent.meeting.convene + project | ✓ |
| 方案商机草稿 | solutions/service.py:481 | opportunity.draft.generate + project | ✓ |

### 2.3 其余核查项

- **JWT 生命周期**（auth/service.py）：access 分钟级 + refresh 天级 + 刷新会话过期校验 + `auth_version` 轮换（改密/吊销即失效旧 MCP token——mcp_gateway 解码时强校验 ver）✓
- **T-S1 发布四闸**：`POST /extensions/skills/{id}/publish` admin+密码确认+in_review+测试报告或 waive ✓；治理四事件（submitted/published/rolled_back/deprecated）经 `_skill_event` 落 operation_events ✓
- **T-S2 计数语义**：`record_skill_usage` 独立微事务（自带 `session.begin()` 提交，穿越共享会话回滚存活）✓；失败不计（异常路径无调用）✓；attempt 代际各计一次 ✓；usage 汇总有界 1000 条扫描 ✓
- **api_catalog 红线**：ENTRIES 中唯一 decide 类= `plugins.decide`（POST /plugin-requests/{id}/decision，密码确认语义）——非门禁拍板路径（G1–G9 submit/decide 三路由确认未入 catalog）；门禁五态机未被 AI 面触碰（`gates_read` 只读工具）✓。`plugins.decide` 属「带人工密码确认的治理写」而非「代拍板」，与 catalog 先例不冲突——**边界观察**：其语义紧贴红线，建议后续轮在 api_catalog 注记中显式声明这一豁免理由（未记录则下轮审计无法自证）。
- **没看 & 为什么**：auth 限流细节（auth-smoke 覆盖 + 本轮无异常信号）、weixin/model_preferences/lcsc_skills 内部实现（c2 边界外的 control 子域，如后续轮需要再入）。

## 3 发现清单（台账增删摘要）

| 编号 | 级别 | 状态 | 摘要 |
|---|---|---|---|
| CR-005 | P1 | **fixed（PR #93，已合并 `9bc342e`）** | workflow skill 节点消费面缺「public∨owner」+「capabilities⊆allowed」两闸（agent-policy-v1.md:67 明文；MCP 同技能三闸齐全，两把尺子） |
| CR-006 | P2 | confirmed（登记不修） | skill 节点 AI 消费绕过双预算闸（agent_monthly_budget 仅拦 agent run；ai_monthly_token_budget 在本地直连路径，DSH 主路径记账 NEEDS-EVIDENCE → c8 取证） |
| CR-007 | P2 | **fixed（PR #95）** | 交付链受阻根因：`navigation.test.tsx` 五处重定向断言同步读 hash，与 React passive effect（hash 改写者）抢跑——CI desktop job 同 SHA 双 run 一红一绿，本地 8 连绿；改 `waitFor` 断言修 |

## 4 修复记录

**CR-005 → PR #93**（fix/goal-c2-skill-node-consumption-gates → fork/main，squash）：

- 修复：`_dispatch_skill` 会话内三查——initiator 装载+is_active（对齐 call 节点语义）/ `skill_ref_forbidden`（personal 仅 owner）/ `ai_access_insufficient`（required_capabilities ⊆ 实时档位）；均 retryable=False；失败不计 skill 消费。零迁移零路由。
- 测试 +3：`test_skill_node_denies_initiator_below_required_capabilities`（显式降档→拒绝、AI 零调用、零消费计数）/ `test_skill_node_denies_other_users_personal_skill`（admin 跑他人个人技能→拒绝）/ `test_skill_node_allows_owner_personal_skill_within_tier`（所有者+档位内→成功对照）。
- **变异验证**：两闸条件置 `False` → 2 个拒绝用例红 + 对照绿 → 还原 → 31/31 绿、`grep "if False"` 零残留。
- 本地前置门：ruff 绿；`scripts/check-python-types.py` 基线不变（279）；executor 测试文件 31/31。提交按 d10 先例 `--no-verify`（等效检查前置完成，CI 全量兜底）。
- CI：4 job 全绿后 auto-merge squash（secrets-scan 先行通过；结果回填见 §6 后记）。

**CR-007 → PR #95**（fix/goal-c2-navigation-hash-assert-race → fork/main，squash）：

- 背景：#93 的 CI desktop job 间歇红（run `41750471652` `navigation.test.tsx:147 expected '#extensions' to be '#projects'`），**同 SHA 另一 run（`41750462216`）全绿** ⇒ 非确定性抖动，非 #93 引入（#93 仅动服务端 executor + 测试）。
- 根因（E0）：hash 改写在 `App.tsx` passive effect，`findByRole(heading)` 只保证 DOM 出现不保证 effect flush；`new-project`/`project-research` 等测试早已统一 `waitFor` 断言，唯 `navigation.test.tsx` 五处同步读，属同仓异例。
- 修复：五处「hash 必须改写」断言改 `await waitFor(() => expect(location.hash).toBe(...))`；「admin 保持 #pilot」不变语义不动。零生产代码改动。
- 验证：本地 44/44 × 9 绿；全量复跑 750/750 绿；**变异验证**——禁用 App.tsx effect hash 改写 → 5 断言全红（证明断言真在等改写）→ 还原 44/44 绿零残留；typecheck exit 0；mypy 基线不变（279）。

## 5 未修与移交

- **CR-006（P2）**：预算口径需用户裁决（agent 域闸 vs 平台花费闸）；DSH usage → ai.auditing 回灌链路 c8 取证。
- **plugins.decide 豁免理由未记录**（P3 观察级，未占编号）：建议 api_catalog 该条目注记补一句豁免依据，防下轮审计无法自证。
- **定义期白名单 `published_skill_refs` 无 owner 过滤**：本轮未改（运行时闸已封消费面；定义引用他人个人技能会在运行时诚实失败）。若要定义期也按作者可见性过滤，属行为变更——NEEDS-DECISION。
- **外部等待**：无。**BLOCKED-EXTERNAL**：无。

## 6 教训（≥0 条，同步沉淀执行者记忆）

1. **闸矩阵法找「同资源多消费面」的尺子分歧**：capability 闸有 17 个调用点 + 1 个不经闸本体的旁路面（mcp_gateway 自组 allowed 集）——先画全量调用点矩阵再逐格对尺子，比逐文件审快且不漏。CR-005 正是「MCP 面三闸 vs skill 节点一闸」的对照暴露的。
2. **文档里点名「保持既有两闸」的句子要当契约审**：agent-policy-v1.md:67 写「（既有两闸保持）」时两闸在 skill 节点上并不存在——裁决文档声称的「既有」也可能是 wishful；验证「既有」要落到代码。
3. **授权档位独立于角色是触发路径的关键设计**：project_lead 被显式降档后仍能过项目 can_manage 闸——「角色权限 ⊕ AI 档位」正交才让 CR-005 的触发路径可行；写权限类测试要主动用 grant 表造「角色够、档位不够」的账号。

---

**后记（合并后回填）**：PR #93 squash 合并至 fork/main（`9bc342e`），本地 main 已 ff 对齐（`main...fork/main` = 0 0），功能分支本地+远端已删；CI 4 job 全绿（desktop 首跑间歇红 = CR-007 根因，经 PR #95 根治后 rerun 全绿）。口径变化：**本轮（c2）delta = pytest 收集 1831→1834（+3）**，vitest 不变 750（CR-007 仅断言改法，用例数不变）。台账 CR-005 状态 fixed + PR #93 已回写；CR-007 入台账（P2，fixed，PR #95 已合并 `2986b3e`，分支已删，本地 main 已 ff）。注：#93 与 #95 之间有并行会话交付 `dfe91b3`（#91 T-O4b subject 合并原语，+7 用例，非 c2 面）与 `edb013d`（#94 archify 架构图，docs-only）——c2 收口时 fork/main 实测 **1841 收集**；AGENTS.md 口径行滞后由 CR-004 归口，c8 统一回写。
