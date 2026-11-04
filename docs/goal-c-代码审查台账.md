# goal-c 代码审查总台账

> 循环：goal-c（全面代码审查，v1.0，2026-11-04 编制）｜ 纪律：审修分离——发现先入账，P0/P1 当轮修复，P2/P3 登记不修。
> 状态机：`open → confirmed（证据升 E0）→ fixed（附 PR）｜ wontfix（理由）｜ dismissed（误报，理由）｜ needs-decision（交用户）`
> 证据等级：E0=本仓实测（命令+输出摘录）｜ E1=子代理/文档结论（定级前须升 E0）｜ E2=推断（禁止定级/动手）
> 分包轮次：c1 基线+意图对照（纯审查）→ c2 auth/users/control/system_configuration/health → c3 交付主链 → c4 agents/ai/skills/jobs/meetings → c5 workflows/ontology/research → c6 dispatch/bridge/workbench/metrics/modules → c7 desktop → c8 基建/GUI 回归/收口

## 轮次状态

| 轮 | 分包 | 状态 | 报告 |
|---|---|---|---|
| c1 | 基线 + 全仓意图对照 | **已完成 2026-11-04**（纯审查轮；门禁四件套全绿；4 发现入账） | docs/goal-c1-代码审查.md |
| c2 | 身份/权限/治理面 | **已完成 2026-11-04**（闸矩阵 14 行；CR-005 当轮修→PR #93 已合并 `9bc342e`；CR-006 登记；CR-007 修→PR #95） | docs/goal-c2-代码审查.md |
| c3 | 交付主链（projects/solutions/documents/guidance/templates/evidence/files/storage/mailing/translator） | **已完成 2026-11-04**（隔离矩阵 86 路由全绿；CR-008/010 P1 修 + CR-009 P2 补测试→PR #98 已合并 `e3b8350`；CR-011 P3 登记） | docs/goal-c3-代码审查.md |
| c4 | 智能体执行域（agents/ai/skills/jobs/meetings） | **已完成 2026-11-04**（CR-012/015/017 当轮修→PR #103 已合并 `c8aa08a`；CR-014 P1 划归 c5；CR-013/016 登记；3 子代理分审） | docs/goal-c4-代码审查.md |
| c5 | 工作流+本体（workflows/ontology/research） | **已完成 2026-11-05**（CR-014/019/020 P1 当轮修→PR；7 项 P2/P3 登记不修；3 子代理分审+变异验证） | docs/goal-c5-代码审查.md |
| c6–c8 | 见上 | 未开始 | — |

## 发现总表

| 编号 | 级别 | 状态 | 一句话 | file:line | 轮次 |
|---|---|---|---|---|---|
| CR-001 | P1 | open | 红线①「改名只改这一个文件」被 5 处硬编码产品名证伪 | 见详情 | c1 |
| CR-002 | P2 | confirmed | 共享测试库对外来迁移链戳无自愈，worktree 会话互踩→全量 E | server/tests/conftest.py:149 | c1 |
| CR-003 | P3 | open | V3 审计报告 §20 实施跟踪停更于 T-S1（缺 T-S2/T-W6 注记） | 审计报告 §20 | c1 |
| CR-004 | P3 | open | AGENTS.md 口径数字滞后于 #88 实测（293/1830/732 vs 295/1831/实测） | AGENTS.md 口径行 | c1 |
| CR-005 | P1 | fixed | workflow skill 节点消费面缺「public∨owner」与「capabilities⊆allowed」两闸（agent-policy-v1:67 明文两闸） | workflows/executor.py `_dispatch_skill` | c2 |
| CR-006 | P2 | confirmed | skill 节点 AI 消费绕过双预算闸（agent_monthly_budget 仅拦 agent run；DSH 主路径记账面 NEEDS-EVIDENCE） | agents/service.py:813 / ai/deepseek.py:126 | c2 |
| CR-007 | P2 | fixed | CI desktop job 间歇红：`navigation.test.tsx` 重定向断言与 React passive effect 抢跑（effect 未 flush 即读 hash） | desktop/tests/renderer/navigation.test.tsx:147 | c2 |
| CR-008 | P1 | fixed | signoff「同方案至多一个 pending」无并发防线：SELECT-then-INSERT 无行锁/无部分唯一约束，双 run 并发 `_finalize` 可双插 pending | agents/signoff.py:30-48 / agents/models.py:216-231 | c3 |
| CR-009 | P2 | fixed | G8-stop 结算联动 `flag_g8_stop_settlement` 零测试载体（gate_service:504 调用点，tests 全仓 grep 命中 0） | projects/payment_service.py:347-374 | c3 |
| CR-010 | P1 | fixed | quote_service 数值防御不自洽：deviation 先落库后 400 检查（Numeric(7,4) 可被 10⁵ 倍偏差击穿→500）、create 侧 cash_cost 无 MAX 上限、finalize 同型 | projects/quote_service.py:292 / 527 / 638 | c3 |
| CR-011 | P3 | open | mailing/translator/guidance 三包意图锚分散 4 份文档，V3 主报告无集中裁决行（NEEDS-EVIDENCE 定级，倾向 P3 文档补齐） | V3 审计 §13 / 各 goal-d 台账 | c3 |
| CR-012 | P1 | fixed（PR #103 已合并 `c8aa08a`） | `retry_run` 绕过平台月度预算闸：start 有 `agent_monthly_budget` 闸（service.py:815），retry（925-1005）只查家族/退避/试点，未重判月度闸 → 月预算用满后仍可用 retry 发新 run | agents/service.py:925 | c4 |
| CR-013 | P2 | open | `record_skill_usage`（skill 节点，executor.py:964）无 try/except 包裹：计数微事务自带提交，但调用点若抛 DB 异常 → 被 `_execute_node` 兜底 catch 为 dispatch_crashed(retryable=True) → 已成功那次 AI 调用被丢弃重跑（双份 AI 成本）+ 节点误标 failed，违反 T-S2「失败不计」对称语义 | workflows/executor.py:960-966 | c4 |
| CR-014 | P1 | **fixed（c5 PR）** | `resume_run` 后 human_approval 节点仍复用 stale 审批键：approval 被 reject/expired 后节点 failed，resume 回 pending 但 `_dispatch_human_approval` 仍按旧键 reuse 已终态审批 → 节点再次 waiting 挂死 | workflows/executor.py:1058 | c4 |
| CR-015 | P1 | fixed（PR #103 已合并 `c8aa08a`） | `ZcodeAdapter.run` 非 SandboxError 异常路径沙箱容器泄漏：`sandbox.kill()` 在 try 之后顺序执行，`event_provider.poll()`/`output_scanner.scan()` 抛非 SandboxError 时容器 `sleep infinity` 悬挂 | agents/adapter.py:179 | c4 |
| CR-016 | P3 | open | outbox_events 四态终态机未实装（只写 pending/dispatched），completed/failed 态与 attempts/last_error 列空置=审计死信箱；RECOVERABLE 四类型缺 failure hook，耗尽后业务行悬空 | jobs/outbox.py:41 / reconcile.py:159 | c4 |
| CR-017 | P2 | fixed（PR #103 已合并 `c8aa08a`） | 上下文渲染 source_refs 不经模式遮蔽：带盘符的 source_ref（如 `C:\客户\…`）原样进 context.md 与 problem_refs，与正文脱敏双标尺 | agents/context.py:153 | c4 |
| CR-019 | P1 | **fixed（c5 PR）** | `resume_run` 对**全部** failed/skipped 节点 attempt 归零——agent 节点幂等键 `wfnode-{行id}:{attempt}` 撞回 `:1` 失败终态（agents V8 拒同键重跑）→ agent 节点每次 resume 确定性 409，永远救不活（docstring「resume 开新代际」与实现矛盾，c4 观察项②） | workflows/executor.py:341-352 | c5 |
| CR-020 | P1 | **fixed（c5 PR）** | 写类 call 节点结果未确认（`uncertain`=started 无 finished；`cancelled`）被折叠为节点 `succeeded`——FV-F1「断链不静默 done」红线虚高；同键去重在 api_actions 层兜底不二次外呼，但节点层「成功」断言失真 | workflows/executor.py:885-893 | c5 |
| CR-021 | P2 | open（登记不修，c6/c8 裁决） | 本体变更集 confirm/reject 双 confirm 写偏差：`confirm_change_set`/`reject_change_set`/`submit_change_set` 状态翻转**无行锁无 CAS**（`row.status != X` 先读后写），两拍板人并发 confirm 可双双物化（物化原语自身幂等键+UNIQUE 兜底不炸，但 409 语义失守 + 双份事件） | ontology/service.py:1206/1275/1066 | c5 |
| CR-022 | P2 | open（登记不修） | cancel_run 与 in-flight call/skill 分派写偏差：cancel 提交 run=cancelled 后，已发出的外呼/ AI 调用返回成功被节点 guard（node.status∉pending/ready/running）静默丢弃——api_actions 留有成功记录但节点 output_json=null，「已执行外呼不回收（诚实呈现）」承诺面缺展示通道 | workflows/executor.py:301-322 vs :714-727 | c5 |
| CR-023 | P3 | open（登记不修） | cancel_run/resume_run 无行锁无 CAS：双 admin 并发 cancel 双份事件+双 outbox（队列去重兜底）；cancel 与 decide 竞争可产生「cancelled run 下 succeeded 审批节点」矛盾态（分派层对终态 run 早退，无一致性损坏） | workflows/executor.py:307-322/331-361 | c5 |
| CR-024 | P3 | open（登记不修） | 调研导入同文件多级造数：`_load_parent_candidates`（imports.py:420）在行创建前扫描父级候选——文件内新建的部门/流程对本批后续行 role 的「父级」列不可见 → preview 零报错、commit 确定性 `parent_not_found`（非静默错数据，preview 体验缺口） | research/imports.py:420/1445 | c5 |
| CR-025 | P3 | open（登记不修） | `update_definition_dag`（definition_service.py:525）零 HTTP 路由——已发布定义无修订出口（`publish_definition` 对 published 行 409 `already_published` 且无编辑路由），docstring 承诺「修改定义会自动开新草稿版本」面缺失；模块 docstring 与路由面漂移 | workflows/definition_service.py:525-551 | c5 |
| CR-026 | P3 | open（登记不修） | 变更集 `register_relation_type` 物化端点校验仅在 confirm 才跑（propose 只查形状）——AI 多条目变更集一条坏端点码即全事务回滚 409（设计内「全成全败」，但人工路由同操作 propose 期等价校验更早，两侧不对称） | ontology/service.py:1182-1203/826-842 | c5 |

---

## CR-001 · P1 · 红线①产品名单一来源被证伪（5 处硬编码）

- **状态**：open（c1 纯审查轮，修复随 c2+ 修复轮走 PR）
- **file:line**：
  - `desktop/src/main/lcsc-finish-dialog.ts:16` — BrowserWindow `title:'蔡工FDE智能交付系统 · 查询结束'`
  - `desktop/src/main/lcsc-runner.ts:68` — BrowserWindow `title: '立创查询执行跟踪 · 蔡工FDE智能交付系统'`
  - `desktop/src/main/index.ts:212` — BrowserWindow `title: '立创商城 · 蔡工FDE智能交付系统内置浏览器'`
  - `desktop/src/renderer/index.html:11` — `<title>蔡工FDE智能交付系统</title>`（主窗口文档标题面）
  - `server/src/fde_api/control/chat.py:60` — 内置助手系统提示词「你是蔡工FDE智能交付系统的内置智能助手…」（助手自述=运行时界面文案）
- **意图锚**：`AGENTS.md` 红线①原文：「产品名只从 `desktop/src/renderer/src/brand.ts` 取……任何界面、窗口标题、提交文案里**不再硬编码产品名**——改名只改这一个文件。」另 `brand.ts` 头注释自称「全站所有出现产品名的地方……都从这里取值」。
- **触发路径**：下一次产品改名，开发者按红线只改 `brand.ts` → 上述 5 处残留旧名：3 个 BrowserWindow 窗口标题、主窗口文档标题（`index.html`）、AI 助手自述口径。该路径已被实证发生一次：#87 更名提交 `9c9d120` 恰恰是**手工逐文件同步**这 5 处（diff 为证），证明「只改这一个文件」的承诺在当前实现下不成立。
- **驳斥记录**：最强反驳①=「main 进程独立打包，无法 import renderer 的 brand.ts，硬编码是架构约束」——不成立：`brand.ts` 是纯常量模块，vite main bundle 可相对路径引入（或抽 `desktop/src/shared/brand.ts` 双侧引用），`index.html` 可走 vite 插件/define 注入，`chat.py` 可取自 config 常量；#87 同 commit 已在改这 5 个文件，说明改造成本可控却未做。最强反驳②=「LCSC 工具窗口不算产品界面」——不成立：三个标题全部携带产品全名，是用户可见的窗口标题面，红线「任何窗口标题」无豁免子句。
- **证据等级**：E0（grep 实测输出 + `git show 9c9d120` diff）
- **建议修法**：抽双侧共享品牌常量模块供 main/renderer 引用；`index.html` 标题由构建注入或运行时 `setTitle` 覆盖；`chat.py` 系统提示词产品名改 config 常量；补一条「brand.ts 之外零产品名硬编码」的静态检查测试防复发。
- **修复 PR**：—（待修复轮）
- **备注**：同轮驳回项——`desktop/src/renderer/src/assets/logo-*.svg` 的 `<title>` 与 `styles.css:2` 注释为资产元数据/注释非界面文案，不入账；服务端 `fde_api/__init__.py:1` docstring 非界面文案，不入账。

## CR-002 · P2 · 共享测试库对外来迁移链戳无自愈（worktree 会话互踩）

- **状态**：confirmed（当日两轮全量 E 实证 + 根因 E0 取证）
- **file:line**：`server/tests/conftest.py:149`（`command.downgrade(config, "base")` → `upgrade head` 的自愈路径只覆盖已知链内戳）
- **意图锚**：conftest 自身设计意图（L135-137 注释）：「会话级 PG advisory lock……持锁串行化整个测试会话」——设计预期同库复用与并行，但自愈假设「戳在本链内」。
- **触发路径**（当日实测，三次实发）：
  ① 2026-11-04 上午：worktree 会话（`D:/test/fde-wt-t-o4b`，分支 `feat/v3-t-o4b-subject-merge`）携带**未提交**迁移 `d4e6f8a2c7b9_v5_subject_merge.py` 跑 pytest → 共享库 `fde_workbench_test` 的 `alembic_version` 被盖为外来戳 → 主工作区 pytest session fixture `downgrade base` 无法从不认识的外来戳回退 → `alembic.util.exc.CommandError: Can't locate revision identified by 'd4e6f8a2c7b9'` → 全部依赖 DB 的用例 setup 即 E（不依赖 DB 的 `test_ai_eval` 全绿，特征鲜明）。手工 `DROP SCHEMA public CASCADE` 重建后恢复。
  ② 同日 c2 轮中复发一次（同外来戳，conftest 自愈后 t-o4b 会话再次盖戳）。
  ③ **2026-11-04 c3 开工预检（第三发）**：`D:/test/fde-wt-t-g1`（分支 `feat/v3-t-g1-gate-evidence-candidates`）携带未提交迁移 `c7e1a9f3b5d8_v5_gate_evidence_candidates.py` 盖戳 → 主工作区 `test_migrations.HEAD_REVISION` 已被 #91 T-O4b 更新至 `d4e6f8a2c7b9`（32 rev），测试库戳 `c7e1a9f3b5d8` 不在本链 → 再次 `DROP SCHEMA public CASCADE` 重建（conftest 自 upgrade + 灌种子）；重建时**零在途 pytest**（C-9 核过）。注：#91 合并后 `d4e6f8a2c7b9` 本身已进主链，第一发的「外来戳」性质随之消失——戳漂移问题不因对方合并而自愈。
- **驳斥记录**：反驳①=「advisory lock 已解决并行问题」——不成立：锁只串行化会话执行，不解决「库的戳漂到另一条链」；锁释放后戳仍是外来的。反驳②=「等对方跑完就好」——不成立：戳是持久的，对方跑完不会自行恢复。
- **证据等级**：E0（CommandError 原文；`SELECT version_num FROM alembic_version` = `d4e6f8a2c7b9`；`ls D:/test/fde-wt-t-o4b/server/migrations/versions/` 命中该文件；`git log --all -- "*d4e6f8a2c7b9*"` 零命中=未提交文件）
- **建议修法（NEEDS-DECISION，改测试基建约定）**：方案 a——conftest 捕获 `CommandError("Can't locate revision")` 时自动 `DROP SCHEMA public CASCADE` 重建后重试 upgrade（附显著 warning 日志）；方案 b——worktree 模板强制 `FDE_TEST_DATABASE_URL` 指向独立库（当前 `D:/test/fde-wt-t-o4b/.env` 实测**无**此覆盖）。
- **修复 PR**：—（P2 登记不修，除非 c8 基建轮顺手且用户认可方案）

## CR-003 · P3 · V3 审计报告 §20 实施跟踪停更于 T-S1

- **状态**：open
- **file:line**：`docs/architecture/蔡工FDE_Workbench_fde-v2架构融合审计与V3升级实施方案.md` §20（最终决策与下一步行动）：条目 6/7/8（T-W4/T-W5/T-S1）均带「→ 已完成（…见 backlog T-x 实施记录）」注记，**T-S2（#86）与 T-W6（#88）无对应条目/注记**。
- **意图锚**：`AGENTS.md` V3 段：「新增表/接口全标 PROPOSED，实现偏差须回写该报告」。偏差细节实际已回写 backlog（T-S2/T-W6 实施记录齐全，T-W6 的 293→295 偏差另回写 workflow-dag-v1 §5 注记）——缺的只是主报告 §20 的状态注记。
- **触发路径**：后人按审计报告 §20 查实施状态 → 以为 T-S2/T-W6 未做 → 重复施工或误判覆盖面。
- **驳斥记录**：反驳=「backlog 已有完整实施记录，主报告缺注记无实害」——部分成立：信息无丢失，但 AGENTS.md 点名「回写该报告」的承诺面只剩一半，意图对照意义上仍属文档漂移，故 P3 登记。
- **证据等级**：E0（grep §20 条目清单实测）
- **建议修法**：§20 补 T-S2/T-W6 两条「已完成」注记（含偏差指针），文档轮顺手。
- **修复 PR**：—

## CR-004 · P3 · AGENTS.md 口径数字滞后于 #88

- **状态**：open
- **file:line**：`AGENTS.md` 口径行：「蓝图路由 **293**」「pytest **1830 收集 = 1824 passed + 6 skipped**」「vitest **732/732**」；「当前状态」bullet 列表缺 T-W6 实施条目（#88 只把节标题改成了「V3 T-W6 后」，正文未跟上）。
- **意图锚**：AGENTS.md 自我声明「口径数字（实测 2026-11-04 …）」+ goal-c 收口判据「AGENTS.md 口径与实测一致」。
- **触发路径**：任何按 AGENTS.md 口径做开工预检的会话 → 路由数对不上（293 vs 实测 295）→ 误判有未登记的路由变更。
- **驳斥记录**：反驳=「#88 有 5 行 AGENTS.md 改动，说明当轮更新过」——查 `git show b89a8f3 -- AGENTS.md` 实测只改了节标题一行语义，数字与 bullet 未更新，反驳不成立。
- **证据等级**：E0（本轮实测：路由 295 / pytest 1831 收集 / vitest 见 c1 报告实测；`git show b89a8f3 -- AGENTS.md` diff）
- **建议修法**：口径行更新为实测值（295 / 1831 / vitest 实测），补 T-W6 bullet 一条（三页全 NEW + 2 只读路由 + usage 块消费）。
- **修复 PR**：—（c1 收口或下一文档轮顺手；改动前遵守 C-7 共享文件纪律）

---

## CR-005 · P1 · workflow skill 节点消费面缺两闸（所有权 + 档位）——已修复

- **状态**：**fixed**（c2 当轮修复；分支 fix/goal-c2-skill-node-consumption-gates）
- **file:line**：`server/src/fde_api/workflows/executor.py` `_dispatch_skill`（修复前：查询仅 `skill_key + status=published`，无 scope/owner 过滤、无档位比对）
- **意图锚**：`docs/architecture/agent-policy-v1.md:67` 明文：「消费面（mcp_gateway._skills / workflow skill 节点）: 只回 published ∧ (public∨owner) ∧ capabilities⊆allowed（既有两闸保持）」。T-S1 只收口了 published 一闸（三处消费面），另两闸在执行器分派面缺失；同文件 T-S1 裁决行声称「消费面两闸保持」与实现不符。
- **触发路径①（档位越级）**：admin 经 UserAIAccessDialog 把某 project_lead 的 AI 档位显式降为 assistant_read（授权档位独立于角色）→ 该 lead 仍可发起含 skill 节点（ref 技能 required_capabilities=["agent.plan.generate"]，project_operator 档）的 run → 修复前 execute_ai_prompt 只拒 `disabled` → AI 调用执行；**同一技能经 MCP `skill_read`/`_skills` 会被 `required_capabilities ⊆ allowed` 过滤拒绝**——同技能两把尺子。
- **触发路径②（跨用户私有内容泄漏）**：用户 A 的个人技能（scope=personal，`UNIQUE(namespace_key, skill_key)` 允许跨命名空间同名）发布后 → 同项目 can_manage 用户 B 建定义引用该 skill_key（定义期白名单 `published_skill_refs` 亦无 owner 过滤，校验通过）→ B 发起 run → 修复前 A 的私有 instructions 进 system_prompt，AI 答案落 node_run 结果 → 项目 can_view 成员可见 A 私有内容。
- **驳斥记录**：①「use_tools=False 无副作用不越界」——不成立：AI 消费本身是档位/预算治理的能力资源，且 A 的私有 instructions 是 A 的数据，跨用户进入他人 run 即边界穿越；②「定义已过发布审所以内容已公开」——不成立：published ≠ public，MCP 面 owner 过滤证明意图就是两者不同；③「execute_ai_prompt 有 disabled 闸兜底」——只覆盖最底层，assistant_read↔project_operator 的档位差距不被覆盖。
- **证据等级**：E0（意图行 + 两侧代码 + UNIQUE 约束 + 白名单查询全文）
- **修复**：`_dispatch_skill` 会话内补三查——initiator 装载+is_active（对齐 call 节点既有语义）、`scope≠public ∧ owner≠initiator → skill_ref_forbidden`、`required_capabilities − capabilities_for_level(effective_ai_access(initiator)) → ai_access_insufficient`（均 retryable=False，失败不计消费）；`initiator_id` 重绑收窄类型。零迁移零路由。
- **验证**：新增 3 用例（档位拒绝/所有权拒绝/所有者本人+档位内放行对照）31/31 绿；变异验证（两闸条件置 False）→ 2 用例红 1 对照绿 → 还原 → 31/31 绿、零残留；ruff 绿；mypy 基线不变（279）。
- **修复 PR**：见 c2 报告 §4。

## CR-006 · P2 · skill 节点 AI 消费绕过双预算闸

- **状态**：confirmed（主腿 E0；DSH 记账腿 NEEDS-EVIDENCE）
- **file:line**：`agents/service.py:813`（`agent_monthly_budget` 仅在 agent run start_run 发起前拦截）；`ai/deepseek.py:126`（`ai_monthly_token_budget` 在本地直连路径调用前检查）
- **意图锚**：`agents/service.py:10-11` 自述「平台月度 agent_monthly_budget……在发起前拦截」（"平台月度"措辞为平台级花费心智）；`config.py:48` E7 `ai_monthly_token_budget`。
- **触发路径**：workflow skill 节点调 `execute_ai_prompt` → 既不过 agent_monthly_budget（那是 agents 域闸）→ DSH 主路径下也未见 ai_monthly_token_budget 检查（deepseek.py 的预算检查在本地直连路径；DSH 路径的 provider_usage 是否回灌 ai.auditing 预算账本未取证）→ 平台 AI 月度预算对 skill 节点花费不可见。
- **驳斥记录**：①「skill 是文本变换花费可忽略」——不成立：无上限的消费面与预算心智冲突，且 16384 max_tokens/节点×N 节点×M run 并不小；②「agent_monthly_budget 本来就只是 agent 域的」——部分成立：若裁决意图就是 agent 域闸，则缺口缩小为「skill 花费完全不入任何预算账本」——仍需用户裁决归属（故 NEEDS-DECISION 候选）。
- **证据等级**：主腿 E0（两侧代码）；DSH 记账腿 **NEEDS-EVIDENCE**（c8 基建轮取证：DSH usage → ai.auditing 回灌链路）。
- **建议修法**：裁决预算口径后——a) execute_ai_prompt 前置预算检查统一拦截；b) 或明确 skill 节点花费入 ai.auditing 账本并接受 DSH 主路径记账。登记不修，c8 处理。
- **修复 PR**：—

## CR-007 · P2 · 桌面导航重定向断言与 React passive effect 抢跑（CI desktop job 间歇红）

- **状态**：confirmed → **fixed（PR #95 已合并 `2986b3e`，本地 main 已 ff）**
- **file:line**：`desktop/tests/renderer/navigation.test.tsx:137,147,157,173,181`（`expect(location.hash).toBe(...)` 同步读 hash）
- **意图锚**：`docs/goal-c2` 交付链纪律 + 仓库既有惯例——同仓 `desktop/tests/renderer/new-project.test.tsx:233,414,440`、`project-research.test.tsx:1064,1069`、`project-detail.test.tsx:711` 对 hash 断言一律用 `await waitFor(() => expect(location.hash).toBe(...))`；唯 `navigation.test.tsx` 五处用同步读，属同仓异例。
- **触发路径**：非管理员直接访问 `#extensions`（或 `#templates`/`#pilot`/`#projects/new`/空 hash）→ `App.tsx:50-53` 的 `useEffect` 才把 `window.location.hash` 改写为 `#projects`，而 `ProjectsPage` 的 `<h1 aria-label="项目工作台">` 在**同一次 commit 的 render 阶段**就已可见 → `await screen.findByRole("heading", …)` 只保证 DOM 出现，**不保证 passive effect 已 flush**（React 18 passive effect 经 scheduler 的 macrotask 调度）→ 下一行同步读 `location.hash` 拿到改写前的旧值 `#extensions` → 断言红。
- **E0 证据**：① CI run `41750471652` desktop job 日志原文：`AssertionError: expected '#extensions' to be '#projects'`，`❯ tests/renderer/navigation.test.tsx:147:27`，`Tests 1 failed | 749 passed (750)`；② **同一 SHA `05f3773` 的另一次 run（`41750462216` push 事件）desktop 全绿**——同一提交、同一测试集、两种结果 ⇒ 非确定性 ⇒ 排除「本次改动引入」（PR #93 只改 `server/src/fde_api/workflows/executor.py` + `server/tests/test_workflow_executor.py`，与 desktop job 无交集）；③ 本地同文件连跑 8 次全绿（`npx vitest run tests/renderer/navigation.test.tsx --no-file-parallelism` × 8）⇒ 抖动依赖 CI runner 的调度时序（Ubuntu runner 更快 → effect flush 晚于断言）。
- **驳斥记录**：①「本地 8/8 绿 ⇒ 测试没问题，CI 红是 CI 环境问题」——不成立：断言依赖 passive effect flush 时序本身就是缺陷，同仓其余 hash 断言早已统一用 `waitFor`（等「hash 变成目标值」这一事实而非等「DOM 出现」）；②「只 extensions 一处红，其余四处同形为何不红」——不成立：五处断言形状相同，落在哪一处取决于 auth promise resolve 与 effect 调度 的相对时序，属随机；③「算 c7 桌面轮的事，本轮不管」——不成立：本轮交付链硬性要求 4 个 CI job 全绿，一个随机红的 desktop job 直接卡住 c2→c3 的推进，且 c3–c8 每轮交付都要过同一道闸；④「改 App.tsx 让 hash 同步改写更早」——不成立：那是拿生产代码迁就测试时序，且 hash 改写本就应在 effect 里做（渲染期改 hash 会引入 render 副作用）。
- **证据等级**：**E0**（CI 日志原文 + 同 SHA 双 run 对照 + 本地 8 次复跑 + 同仓既有 `waitFor` 惯例）。
- **修复**：五处「hash 必须改写」的断言改为 `await waitFor(() => expect(location.hash).toBe(...))`（与同仓既有写法一致）；「admin 保持 #pilot」那处是「不变」语义（同步断言即正解）不动。仅改测试文件，零生产代码改动、零迁移零路由。
- **建议修法（已实施）**：同上。
- **修复 PR**：#95

## CR-008 · P1 · signoff「同方案至多一个 pending」无并发防线

- **状态**：confirmed → **fixed（PR #98 `e3b8350`）——advisory lock 串行开闸段；双线程并发回归钉 test_signoff_concurrency（变异：删 lock→双插红）**
- **file:line**：`server/src/fde_api/agents/signoff.py:30-48`（`ensure_pending_signoff` SELECT-then-INSERT）；`server/src/fde_api/agents/models.py:216-231`（`SolutionReviewCheckpoint` 表 args 只有三个 CHECK + 一个普通复合 Index，**无 UNIQUE、无部分唯一索引**）。
- **意图锚**：AGENTS.md T-P0-1 段 + `agents/signoff.py:3` docstring 原文：「同方案至多一个 `pending` signoff；已有 pending 时只补 run 软链……绝不重复开闸」。对照同仓 `evidence/models.py:24-27` 的 `uq_project_evidence_fingerprint` 部分唯一约束先例——本系统对「同资源至多一个」语义的既有做法是 DB 约束兜底。
- **触发路径**：同一方案、同一幂等键的两个并发 `start_run`（不同 `idempotency_key`，如客户端/重试各带一个 key）→ 两 worker 各自 `run queued→completed` → 各自 `session.begin()` 内 `ensure_pending_signoff`：READ COMMITTED 下双方 SELECT pending 均 None（对方 INSERT 未提交）→ 双双 INSERT → 同方案两行 pending。`_finalize` 侧（`agents/service.py:428`）未锁方案行，兜底事务（`solutions/service.py:680`）虽对项目行 `with_for_update` 但 `_finalize` 不锁——两侧无交集锁。后果：`resolve_signoff`（`solutions/service.py:339-345`）按 created_at 取最早 pending 收口，第二行成孤儿永远滞留；`solution_review_trail`（L276-281）取**最新** pending 展示 → 终审台口径漂移。
- **驳斥记录**：①「SELECT-then-INSERT 在单事务内语义成立」——成立，但 docstring 承诺的幂等语义是跨事务的（三处调用来自三个独立 `session.begin()` 块：`agents/service.py:488`/`:909`/`solutions/service.py:658`），单事务内正确不等于并发正确；②「概率低」——两个 run 并发 finalize 同方案 = 同方案双 agent 跑，`start_run` 无「同方案在途 run 唯一」约束（幂等键是 key 维度而非 solution 维度），真实用户可触发。
- **证据等级**：结构面 E0（无锁无 UNIQUE 的直读）；双插后果腿 E2（未构造双事务实跑，PG READ COMMITTED 行为）——**修法前须 E0 实证**：双线程 advisory-free 并发调 `ensure_pending_signoff` 断言行数=2。
- **建议修法**：`ensure_pending_signoff` 入口先 `SELECT pg_advisory_xact_lock(hashtext('fde_signoff:' || :solution_id))`（同仓 `quote_service.py:592` 的 `fde_quote_first_order` 先例同构）→ 锁内 SELECT-then-INSERT；可选加固：迁移加部分唯一索引 `UNIQUE (solution_id, checkpoint_type) WHERE checkpoint_type='signoff' AND status='pending'`（零 DDL 冲突：存量数据每方案至多一 pending，合法形态全兼容）——迁移走 goal-d 三件套。P1 当轮修。
- **修复 PR**：#98（`e3b8350`，已合并）

## CR-009 · P1 · G8-stop 结算联动零测试载体

- **状态**：confirmed → **fixed（PR #98 `e3b8350`）——test_gates_api +2 用例（有行打 g8_stop 标记+事件 / 无行只留事件）**
- **file:line**：`server/src/fde_api/projects/payment_service.py:347-374`（`flag_g8_stop_settlement`）+ `gate_service.py:504-508`（decide G8 stop 时调用）。
- **意图锚**：`payment_service.py` 函数 docstring 原文：「G8 stop 也按合同结算（SOP §S8 拍板三态）：门禁引擎 decide stop 时联动给 G8 尾款行打 `settlement_reason='g8_stop'`——B 尾款照收」。
- **触发路径**：`decide_gate(project, "G8", decision="stop")` → 尾款行打标记。两个无载体分支：(a) G8 计划内无尾款行 → 只留事件不落标记；(b) 重复 stop 拍板 → note 追加不重复。
- **E0 证据**：`grep -rn "g8_stop\|flag_g8_stop" server/tests/` 命中 **0**；`test_gates_api.py` G8 用例只覆盖 conditional_pass/decision 必填（L133-197）；`test_dispatch_p0_r2.py` 的 `_g8_passed` 是手工插 passed 行、非 decide-stop 路径。
- **驳斥记录**：「stop 是罕见分支不值得测」——不成立：本函数是 SOP 拍板三态的结算联动点，错打标记=尾款计提口径错，且「无行只留事件」分支是纯控制流，缺测试=下轮无回归网。P1（测试缺口类：语义承诺无载体，按 c3 验收「signoff 异常路径各一条触发路径」同类标准当轮补）。
- **证据等级**：E0（零命中 grep + 调用点直读）。
- **建议修法**：`test_gates_api.py` 或新文件补 2 用例：decide stop 有尾款行→`settlement_reason='g8_stop'` + 事件；无尾款行→只事件不落标记；重复 stop→幂等。
- **修复 PR**：#98（`e3b8350`，已合并）

## CR-010 · P1 · quote_service 数值防御不自洽（500 而非 400 + cash_cost 无上限）

- **状态**：confirmed → **fixed（PR #98 `e3b8350`）——create 侧 cash_cost 加 MAX 闸 + calibrate 侧 deviation 前置 400 闸；test_quote_numerical_guards 4 例（变异：删双闸→2 红）**
- **file:line**：
  ① `quote_service.py:527-530`（calibrate：`quote.deviation_pct = deviation` **先落库**，L536 的 99.99 上限检查的是 `calibrated_buffer` 不是 deviation）+ `workbench/models.py:721` `deviation_pct: Numeric(7,4)`（整数位 3，上限 999.9999——注：子代理初报 9999.9999 系误读，实为 999.9999）；
  ② `quote_service.py:292-295`（create：`cash_cost` 只拒负数、无 MAX；对照 `MAX_INPUT_MONEY=10⁷` L122 已用于 `final_amount` L574）+ `workbench/models.py:693-695` `labor_cost/total_cost/formula_price: Numeric(12,2)`（上限 99,999,999,999.99，cash=5×10¹⁰ 可击穿）；
  ③ `quote_service.py:638`（finalize：`final_deviation_pct = (final−anchor_low)/anchor_low`，final≤10⁷、anchor_low≥18000 合法极小偏差 <100% 内；但 cash_cost 超上限使 total_cost 先溢出，同 ② 型）。
- **意图锚**：`quote_service.py:120` 注释原文：「数值入参的合理上限（工程防御，非方法论取值）：超出即视为录入错误**拒 400**」。
- **触发路径**：① ideal=0.01（合法 L286）+ calibrate actual=9999（合法 L511 ≤10000）→ deviation≈999,899.99 > Numeric(7,4) → `session.flush()` 抛 `DataError` → 全局 `errors.py:31` 捕获为 500；② create cash_cost=5×10¹⁰ → labor/total/formula 溢出 → 同 500。
- **驳斥记录**：「10⁵ 倍工时偏差工程上 unrealistic」——部分成立，但守卫自述口径就是「超出=录入错误拒 400」，500 违反自身文档约定；且 ② 的 cash_cost 是开放整数入参，无 realistic 假设可依托。修复成本极低（deviation 校验前移 + cash_cost 加 MAX + finalize 侧同型补 400），零风险。
- **证据等级**：代码路径 E0（先落库后检查直读）；「Numeric 溢出→DataError→500」结果腿 E2——**修法前须 E0 实证**（单条 pytest 构造 10⁵ 偏差断言 500，或直连 PG 验列上界）。
- **建议修法**：calibrate 中 `deviation` 超 `Decimal("999")` 先 400（对齐 L536 既有 400 语义，改检查对象与位置）；create 侧 `cash_cost > MAX_INPUT_MONEY` 拒 400；finalize 侧对 `final_deviation_pct` 同型防御。三处纯服务层 400 化，零迁移零路由。P1 当轮修。
- **修复 PR**：#98（`e3b8350`，已合并）

## CR-011 · P3 · mailing/translator/guidance 意图锚分散（NEEDS-EVIDENCE 定级）

- **状态**：open（c3 发现，P3 登记不修）
- **file:line**：`docs/architecture/蔡工FDE_Workbench_fde-v2架构融合审计与V3升级实施方案.md` §13（三包仅出现在「不触碰」边界行）；意图实际分散于：`docs/SES发信模块-G9.md`（mailing）/ `docs/goal-d13·d14`（translator）/ goal-d 各台账（guidance adopt 闭环）。
- **意图锚**：intended-vs-implemented 纪律——意图没写在一处可查的地方即「意图未记录」。实现面零走样（A6「不触碰」+ 各包既有文档逐条吻合，见 c3 报告 §2）。
- **驳斥记录**：「§13 不触碰行已够」——部分成立：不触碰是边界声明不是意图锚；三包各自独立文档存在且自洽，缺的只是主报告集中指针。P3 文档漂移，登记。
- **证据等级**：E0（四份文档位置实测）。定级腿 E2（「是否足够」属文档治理判断）→ P3 封顶。
- **建议修法**：V3 主报告 §13 或 §20 补三包指针行（同 CR-003 类，文档轮顺手）。
- **修复 PR**：—

## CR-012 · P1 · retry_run 绕过平台月度预算闸

- **状态**：confirmed → **fixed（PR #103 `edd6cda`，已合并 `c8aa08a`，分支已删，本地 main 已 ff）**
- **file:line**：`agents/service.py:925-1005`（`retry_run` 全文）；对照 `:815-816`（`start_run` 月度闸）
- **意图锚**：`agents/service.py:10-11` 模块 docstring 自述「平台月度 agent_monthly_budget……在发起前拦截」；「发起」未限定 start/retry 两通道。
- **触发路径**：平台月消耗 99/100 → start 409 `agent_budget_exhausted`；但任一失败/超时/超预算 run 经 `POST /agents/runs/{id}/retry` 不重判月度闸 → 超额 run 经 retry 通道放行；**跨月形态**（1/31 失败 → 2/1 retry）月度封顶在 retry 腿形同虚设。
- **驳斥记录**：①「退避 30s + 上限 2 次，暴露窗口小」——不成立：窗口不止退避期，月度闸按自然月切，跨月 retry 无拦截面；②「retry 语义是原 start 的延续」——恰恰因此更该过同一道闸（家族重试不豁免预算口径）。
- **证据等级**：E0（双路径代码对照：retry 全文无 `_platform_month_spent` 调用，start 有）。
- **修复**：retry_run 家族上限检查后补同型月度闸（`budget>0 ∧ _platform_month_spent≥budget → 409 agent_budget_exhausted`），零迁移零路由；测试 `test_agent_budget.py::test_retry_run_also_checks_platform_monthly_budget`（月花 100/预算 100 → retry 409 + 家族不增；预算 0 对照放行）。
- **修复 PR**：#103（`edd6cda`，已合并 `c8aa08a`）。

## CR-013 · P2 · skill 节点计数调用无隔离（计数侧故障升级消费侧故障）

- **状态**：open（c4 发现，登记不修——修复涉 executor 节点事务语义，归 c5 轮次评估）
- **file:line**：`workflows/executor.py:960-966`（`record_skill_usage` 在 `_dispatch_skill` 末尾、无 try/except）
- **意图锚**：AGENTS.md T-S2 段「计数走独立微事务（自带 `session.begin()` 提交，穿越共享会话回滚存活）」+ `record_skill_usage` docstring「分派失败不计——失败是噪声不是效果」。
- **触发路径**：skill 节点 AI 调用**已成功** → 紧随其后的 `record_skill_usage` 微事务遇 DB 瞬断抛异常 → 被 `_execute_node` 兜底（executor.py:637-645）catch 为 `dispatch_crashed(retryable=True)` → 节点 failed 重投 → 同一逻辑节点**双份真实 AI 调用 + 双份计数**，且「消费成功」被记为「节点失败」——把计数侧故障升级成了消费侧故障。chat 侧（`ai_tool_loop.py:111`）有 try/except 覆盖，唯 workflow 面裸露。
- **驳斥记录**：「微事务与主会话同源 DB，双故障同时发生概率极低」——部分成立，故 P2 非 P1；但 T-S2「自带提交才能存活」的对称语义被破坏的方向是实害（双份 AI 成本 + 状态背离）。
- **证据等级**：E0（调用点无防护直读 + 兜底 catch 路径直读）。
- **建议修法**：`_dispatch_skill` 计数调用包 try/except（记 warning 不冒泡）；归 c5 workflows 轮次修（executor 全域深审时一并按）。
- **修复 PR**：—

## CR-014 · P1 · resume 后 human_approval 节点 stale 审批键复用（run 永久卡 waiting_approval）

- **状态**：confirmed → **fixed（c5 PR）**——c5 P1 修复面第一条
- **file:line**：`workflows/executor.py:338-345`（resume 重置块不碰 `idempotency_key`）+ `:1058-1061`（stale 键复用分支**无 status 检查**）+ `:1137`（waiting 挂键）
- **意图锚**：AGENTS.md T-W5 段「failed-only resume：failed/skipped 回 pending 重投」+ T-W4「崩溃恢复不重复建单」。
- **触发路径**：approval 被 **reject**（节点 failed，`idempotency_key` 仍=审批 id）或惰性过期（`approval_expired`）→ run failed → `resume_run`：节点 failed→pending、`attempt=0`、**键不动** → 主循环重派 → `_dispatch_human_approval` L1058 命中终态审批 → 直接 `return existing.id` → 节点重新 waiting、run=`waiting_approval`；而 `decide_automation_approval` 对非 pending 行早退（control/service.py:723-724）→ 无人可拍板；resume 又 409 `not_resumable`（waiting_approval≠failed）→ **run 唯一出口=cancel**。
- **驳斥记录**：「L1058 注释『崩溃恢复：审批已建，直接复用』本就为 pending 审批设计」——注释语义是崩溃恢复（审批应还活着），stale 键指向的已终态审批不属于该语义；代码缺「键所指审批已终态 → 清键重建」分支，且 L1062 的 pending 查询在 L1058 命中时不可达。
- **证据等级**：E0（全链行号直读；resume 用例 test_workflow_executor.py:395-457/817-866 均不含 human_approval reject→resume 组合，无测试钉）。
- **修复**（c5）：`_dispatch_human_approval` 复用分支加 `existing.status == "pending"` 判定；终态时清 `node.idempotency_key=None`，落到下方「按 `workflow_node_run_id` 查 pending / 或新建」路径。测试 `test_workflow_executor.py::test_human_approval_rejected_resume_creates_fresh_pending`（reject→resume→**新建** pending 审批（≠旧键）→人工批准→run succeeded，全链收敛）；变异验证：删 status 判定还原旧行为→该测试红（复用终态审批，run 卡 waiting）→还原绿。
- **修复 PR**：c5 PR（goal-c5-workflow-executor-guards）。

## CR-015 · P1 · 适配器非 SandboxError 异常路径沙箱容器泄漏

- **状态**：confirmed → **fixed（PR #103，`edd6cda`，CI 中）**
- **file:line**：`agents/adapter.py:144-182`（原：监听段 `event_provider.poll()` / `output_scanner.scan()` 抛非 SandboxError → `adapter.run` 未走到尾部 `sandbox.kill()`）+ `service.py:609-625`（外层只 `except SandboxError`）
- **意图锚**：`adapter.py:3-6` docstring 三阶段「回收（kill 沙箱 + 扫描 output 产物清单）」+ `sandbox.py:13`「销毁回收——kill 后容器销毁」（V2-④ 硬边界）；容器 `sleep infinity`（sandbox.py:281），悬挂=宿主资源泄漏。
- **触发路径**：run 执行中事件流 ndjson 解析炸 / 扫描器文件系统异常（非 SandboxError）→ 异常上抛 service 层 → 500 + run 行已置 running 后卡死（`recover_run` 15 分钟窗口可救 run 行，**无人再持有容器句柄**）→ 容器永久悬挂。
- **驳斥记录**：「`stuck_recovered` 管理面可收口」——不成立：恢复面只改 run 行状态，不清理悬挂容器（全仓无第二处 `handle.kill` 调用点）；「正常路径 kill 恒定发生」——成立，缺陷只在异常逃生路径。
- **证据等级**：E0（kill 顺序位置 + service 层 except 面直读）。
- **修复**：`run()` 拆分 `_listen_and_reclaim` 子方法，监听+扫描整体置于 `try/finally`，`sandbox.kill()` 唯一回收点在 finally（幂等）；测试 `test_agents_adapter.py::test_non_sandbox_exception_still_reclaims_sandbox`（ExplodingProvider → RuntimeError 上抛且 `kill_count==1`）。
- **修复 PR**：#103（`edd6cda`，已合并 `c8aa08a`）。

## CR-016 · P3 · outbox 终态机未实装 + RECOVERABLE 四类型缺 failure hook

- **状态**：open（c4 发现，P3 登记不修；功能闭环由 job 行兜住，属审计死信箱）
- **file:line**：`jobs/outbox.py:41,78-80`（只写 pending→dispatched）+ `jobs/models.py:42-43`（四态枚举 + attempts/last_error 列空置）；`jobs/reconcile.py:80-90`（`RECOVERABLE_JOB_TYPES` 含 file.scan/file.preview/document.generate/ai.execute）vs 全仓 `register_job_failure_handler` 注册表（四类型**均无 hook**）。
- **意图锚**：reconcile.py docstring 原文「The business row … stays in extracting/analyzing/running forever … the business row is pushed to a terminal state through the registered failure hook」。
- **触发路径**：同一 job 连续 5 轮 worker 级死亡（每轮 5min 租约过期重投再死）→ 耗尽 → `_fail_job` → `get_job_failure_handler("document.generate")` 返回 None → job 行 failed 但业务行（DocumentGenerationJob/ProjectFileVersion.scan_status）永久悬空 → 前端「生成中」无限转圈。
- **驳斥记录**：「概率极低（需五连死）」——成立，故 P3；但 docstring 自称「根治」的承诺面与注册表实际覆盖不符，文档漂移+防线缺口双挂。
- **证据等级**：E0（grep 注册表 + outbox 写入点全量直读）。
- **建议修法**：四类型补 failure hook（终态推进 + 事件）或 reconcile 文档降级承诺；归 c8 基建轮与 outbox 语义一并裁决。
- **修复 PR**：—

## CR-017 · P2 · 上下文渲染 source_refs 不经模式遮蔽（双标尺）

- **状态**：confirmed → **fixed（PR #103，`edd6cda`，CI 中）**
- **file:line**：`agents/context.py:153-157`（`item_refs` 原样进 `rendered_refs` 与 `problem_refs`；对照 `:149` 相邻的 `text` 走 `_clean`=双标尺）
- **意图锚**：`context.py:7-8` 模块 docstring「真相层路径 … 永不出现」+「产物 grep 真实客户名/盘符零命中」（c4 复审该断言自身：全部脱敏用例断言对象是**渲染文本面**，source_refs 样例全为 `src-1` 良形，毒化 refs 路径从未被测——子代理测试强度评估命中）。
- **触发路径**：已确认 ProblemItem 的 `source_ref` 形如 `C:\客户\材料\扫描件.pdf`（真实资料指针）→ 渲染产物 `- [C:\客户\材料\扫描件.pdf] …` 盘符原样落 context.md；终检 `assert_sanitized` 只查禁区词不查盘符模式。
- **驳斥记录**：「source_ref 设计上是代号引用」——字段契约不约束 ref 形态（`_clean` 只覆盖 text/classification，:149-152 与 :154 相邻即见双标尺），毒化时点不同来源同一路径；「产物面才是要害」——context.md 是沙箱内 AI 的直接读入面，盘符入文=线索回传风险。
- **证据等级**：E0（漏检直读 + 测试用例 refs 全良形 grep）。
- **修复**：`item_refs` 构造先过 `redact_patterns`（与正文同尺），`problem_refs` 收已遮蔽形态（产物校验对账只比对遮蔽形态，两侧同规）；测试 `test_agent_context_sanitization.py` +2（毒化 refs 零原文命中 + 遮蔽计入 redactions）。
- **修复 PR**：#103（`edd6cda`，已合并 `c8aa08a`）。

## CR-019 · P1 · resume 对 agent 节点 attempt 归零 → 幂等键撞回失败终态（确定性 409）

- **状态**：confirmed → **fixed（c5 PR）**
- **file:line**：`workflows/executor.py:338-345`（原：`node.attempt = 0` 对**全部** failed/skipped 节点无差别归零）；对照 `_dispatch_agent` L1018 `idempotency_key = f"wfnode-{node_id}:{attempt}"` + agents V8「对失败终态 run 拒同键重跑」。
- **意图锚**：executor.py:25-26 模块 docstring 原文：「工作流以 attempt 代际表达『显式重试』（resume_run / retryable 崩溃恢复**各开新代际**）」；agents/service.py V8 终态拒同键语义。
- **触发路径**：agent 节点失败（exit 1 → `agent_run_failed`，`wfnode-{行id}:1` 落 failed 终态）→ run failed → `resume_run`：`node.attempt=0` → 主循环 `_begin_node` +1 得 attempt=1 → `start_run(idempotency_key="wfnode-{行id}:1")` → agents 查同键命中 **failed 终态** → 409 `agent_run_retry_required` → 节点 failed、`_NodeFailure(retryable=False)` → **每次 resume 都撞同一终态，agent 节点永远救不活**（唯一出路=人工 cancel 后重开 run）。call/skill/human 节点的 attempt 仅用于退避与「每轮恢复重置」，归零无害——缺陷只在 agent 语义面。
- **驳斥记录**：「agent 节点失败后本就需人工介入，救不活是设计」——不成立：docstring 明文承诺 resume 开新代际，且 call/skill 同类节点 resume 后即恢复成功（test :817-866），agent 面不对称；「撞 409 是 agents 层保守闸」——该闸防的是**同一次**执行的重放，跨代际重试（attempt+1 新键）是设计内合法通道。
- **证据等级**：E0（executor 行号直读 + agents V8 语义 + c4 子代理观察项②首报，本轮升级）。
- **修复**（c5）：`resume_run` 重置块改 `if node.node_type != "agent": node.attempt = 0`——agent 保留 attempt，`_begin_node` +1 开新代际（`wfnode-{行id}:2`）；call/skill/human 照旧归零（「每轮恢复重置」语义不变）。测试 `test_workflow_executor.py::test_agent_node_resume_preserves_attempt_new_generation`（first run exit 1 failed→resume 代际 2 成功，`agent_run.idempotency_key==wfnode-{id}:2`）；变异验证：恢复全类型归零→该测试红（`'failed' == 'succeeded'`）→还原绿。
- **修复 PR**：c5 PR（goal-c5-workflow-executor-guards）。

## CR-020 · P1 · 写类 call 节点 uncertain/cancelled 折叠为 succeeded（FV-F1 红线虚高）

- **状态**：confirmed → **fixed（c5 PR）**
- **file:line**：`workflows/executor.py:854-893`（`_dispatch_call` 原分支：仅 `awaiting_confirmation`/`running` 上抛，`uncertain`/`cancelled` 落入尾部 `return result` → 节点 succeeded）；对照 `control/api_actions.py:90-92`（`status` 取值域含 `uncertain`=「操作已开始，结果尚未确认」/`cancelled`）。
- **意图锚**：AGENTS.md T-W3 段 FV-F1「占位符缺键→failed 不填空串、断链→run failed」+ executor 模块 docstring「外副作用幂等：写类 call 节点分派前落 api_actions 同构 sha256 幂等键」——**成功**语义=该写操作**确实落库**。
- **触发路径**：写类 call 节点（如 `projects.create`）的 `execute_api` 返回 `status=uncertain`（外呼 started 未收到 finished 回执）或 `cancelled`（被另一通道取消）→ 原代码仅检查 `awaiting_confirmation`/`running` → `result` 原样 return → `_settle_node_success` 把节点标 `succeeded`、`output_json` 存下未确认结果 → **下游占位符消费一个「没落库」的对象 id**（断链静默 done，FV-F1 核心红线）；节点层 `len(calls)` 断言虚高，audit 面看不到这次未确认。
- **驳斥记录**：「api_actions 层同键去重，重跑也不会二次外呼，无害」——去重兜住**外呼**面，兜不住**节点 succeeded 语义面**：下游已按成功继续，真实落库与否无从追溯；「uncertain 是罕见竞态」——恰是「写操作结果未确认」这一 FV-F1 定义的核心场景，不该折叠成功。
- **证据等级**：E0（api_actions.py:90-92 status 域 + executor 分支缺失直读 + c4 子代理 F3 首报，本轮升级）。
- **修复**（c5）：`_dispatch_call` 在 `running` 分支后增 `if status in ("uncertain","cancelled"): raise _NodeFailure("action_not_confirmed", ..., retryable=False)`——结果未确认按失败断链（不静默 done），同键去重在 api_actions 层兜底不二次外呼；人工核实目标状态后再处置。测试 `test_write_call_node_uncertain_and_cancelled_fail_not_succeeded`（uncertain→failed；resume 重派→cancelled→仍 failed，非 succeeded）；变异验证：折叠回 succeeded→该测试红（`'succeeded' == 'failed'`）→还原绿。
- **修复 PR**：c5 PR（goal-c5-workflow-executor-guards）。

## CR-021 · P2 · 本体变更集双 confirm 写偏差（无行锁/CAS）

- **状态**：open（c5 登记不修，交 c6/c8 或后续工程轮裁决）
- **file:line**：`ontology/service.py:1206`（`confirm_change_set`）/`:1275`（`reject_change_set`）/`:1066`（`submit_change_set`）——三处状态翻转均「读 `row.status` 判合法→物化→`row.status=X`」，**无 `with_for_update` 无 CAS**。
- **意图锚**：T-O3「confirm 复核指纹+单事务逐项物化全成全败，409 base_conflict 并发漂移零物化」——base 指纹只防**本体内容**漂移，不防**同一变更集被两拍板人并发 confirm**。
- **触发路径**：变更集 in_review，两拍板人 A/B 并发 confirm（均过「拍板人≠提交人」验收分离）→ A、B 各自 `row.status=="in_review"` 先读通过 → 各自物化 → A、B 各自 `row.status="confirmed"`+事件。物化原语（create_term/update_term/merge_terms）自身幂等键+UNIQUE 约束兜底不炸数据，但：① 409 `not_in_review` 语义失守（第二次 confirm 本应 409 却 200）；② 双份 `ontology_change_set_confirmed` 事件 + 双份物化副作用（update_term 同名受控改写两次、merge_terms 逐项 OperationEvent 两次）。
- **驳斥记录**：「本体 confirm 低频，双拍板人并发概率可忽略」——概率低≠不修，但**修=加行锁/CAS 属 P2 小改**，非 P0/P1，本轮登记不动码；「验收分离已防提交人自拍板」——只防自拍板，不防双拍板人并发。
- **证据等级**：E1（子代理首报，本轮 grep 直读确认无 `with_for_update`，未实测并发路径→定级 P2 不升级 P1）。
- **建议修法**：`_load_change_set` 或 confirm/reject/submit 入口 `row = session.get(...).with_for_update()` 行锁，或 UPDATE ... WHERE status=旧值 CAS 检 rowcount；归后续工程轮。
- **修复 PR**：—

## CR-022 · P2 · cancel_run 与 in-flight call/skill 分派写偏差（外呼成功被静默丢弃）

- **状态**：open（登记不修；「诚实呈现」承诺面缺口，概率毫秒窗口）
- **file:line**：`workflows/executor.py:301-322`（`cancel_run` 提交 run=cancelled+节点 cancelled）vs `:714-727`（`_settle_node_success` guard `node.status∉(pending,ready,running)` 早退）。
- **意图锚**：`cancel_run` docstring L302「已执行外呼不回收（诚实呈现）」。
- **触发路径**：worker 正处 `_dispatch_call`（`execute_api` HTTP in-flight L846-865）或 `execute_ai_prompt` in-flight（L967-974）时，另一请求 `cancel_run` 提交 → 外呼/AI 调用**已真实发生** → worker 返回后 `_settle_node_success` reload，node=cancelled（不在 guard 白名单）→ 成功产物**静默丢弃**（output_json=null）→ api_actions 留有成功记录但节点面看不到，「诚实呈现」承诺缺展示通道。agent 节点安全（durable AgentRun 实体+独立 settle 复查），call/skill 无等价锚。
- **驳斥记录**：「guard 早退是设计（run 已取消语义）」——对节点面成立，但 api_actions 成功行与节点 cancelled 面矛盾，审计者无从判断该外呼是否真发生；「窗口毫秒级」——成立，故 P2 不 P1。
- **证据等级**：E1（子代理首报，行号直读；未实测并发窗口）。
- **建议修法**：`_settle_node_success` 对 cancelled 节点补一条「外呼已成功但 run 已取消」的 OperationEvent 或 output_json 落 `dropped_after_cancel=true`；归后续轮。
- **修复 PR**：—

## CR-023 · P3 · cancel_run/resume_run 无行锁/CAS（双 admin 并发生命周期写）

- **状态**：open（登记不修；单租户本地桌面产品，人驱动并发，队列入口去重兜底）
- **file:line**：`workflows/executor.py:307-322`（cancel）/`:331-361`（resume）——对照 `control/service.py:719` `with_for_update(of=AutomationApproval)`（审批面有锁，run 生命周期面无）。
- **触发路径**：双 admin 并发 cancel → 双 `workflow_run_cancelled` 事件 + 双 outbox（`ensure_background_job` 单活 guard 去重，不二次执行）；cancel 与 `decide_automation_approval` 竞争 → 「cancelled run 下 succeeded 审批节点」矛盾态（分派层对终态 run 早退，无一致性损坏，仅状态矛盾无消费者告警）。
- **驳斥记录**：「事件/outbox 双份是审计噪声非损坏」——成立；「概率低（双 admin 同点）」——成立，P3。
- **证据等级**：E1（行号直读；未实测双 admin 并发）。
- **修复 PR**：—

## CR-024 · P3 · 调研导入同文件多级造数父级不可见（preview 零报错、commit 确定性 parent_not_found）

- **状态**：open（登记不修；fail-safe 非静默错数据，preview 体验缺口）
- **file:line**：`research/imports.py:420`（`_load_parent_candidates` 在行创建**前**扫描既有父级候选）/`:1445`（`_resolve_parent` 抛 `parent_not_found`）。
- **触发路径**：一份 CSV 内先建部门「华东部」再建 5 行 role 挂 `父级=华东部` → 扫描时「华东部」未落库（候选=空）→ 5 行 commit 确定性 `parent_not_found`；而 `_validate_import_row`（L1253）仅对 department/opportunity 类型查父级 → role 行 preview 零报错。
- **驳斥记录**：「单文件多级造数本就未承诺（schema 只保证一级导入）」——成立；「commit 大声失败、preview 可复用重排」——fail-safe，P3。
- **证据等级**：E1（行号直读；未实测多级 CSV）。
- **修复 PR**：—

## CR-025 · P3 · update_definition_dag 零路由（已发布定义无修订出口，docstring 漂移）

- **状态**：open（登记不修；T-W1「零路由」有意分阶段，docstring 承诺面漂移）
- **file:line**：`workflows/definition_service.py:525-551`（函数体，grep 全仓 `server/src` 零调用点，仅测试引用）；`routes.py` 仅 `create_definition`/`publish_definition`。
- **触发路径**：已发布定义要改 `params` 键/新增占位符 → `publish_definition` 对 published 行 409 `already_published` 且**无编辑路由** → 唯一出路=删（run 史 RESTRICT FK 挡）或建第二个定义。
- **驳斥记录**：「T-W1 有意 staged surface，修订路由挂账后续轮」——成立，故 P3；但模块 docstring L4-13 明文写「update（已发布则自动开新草稿版本）→ publish」，承诺面与路由面漂移，需回写或补路由。
- **证据等级**：E0（grep 零调用点 + routes.py 直读）。
- **修复 PR**：—

## CR-026 · P3 · 变更集 register_relation_type 端点校验仅在 confirm（多条目一条坏码全事务回滚）

- **状态**：open（登记不修；设计内「全成全败」，与人工路由 propose 期校验不对称）
- **file:line**：`ontology/service.py:1182-1203`（`_materialize_register_relation_type` confirm 期跑 `register_relation_type` 端点校验）/`:826-842`（`_normalize_change_set_item` propose 期只查形状「不触 DB 状态」）。
- **触发路径**：AI 多条目变更集含一条 `register_relation_type(link_type, allowed_source_types=[bogus])` → propose/submit 通过（形状合法）→ confirm 单项 409 `change_set_item_failed` → 全事务回滚，其余 29 条好条目一并作废，评审人须 reject 全组重提。
- **驳斥记录**：「全成全败+base 指纹是 T-O3 设计保证，坏码属漂移类错误 confirm 本应抓」——成立；「与人工路由同操作 propose 期等价校验更早」不对称面，登记观察。
- **证据等级**：E1（行号直读；未实测 30 条目变更集）。
- **修复 PR**：—

## 驳回/观察记录（不占编号）

- **旧产品名残留扫描**：`qiflow` 命中 7 个 tracked 文件（README.md / compose.yaml / server/Dockerfile / scripts/check-pseudonymization.sh / scripts/verify/run-verify.sh / docs/代码评审-G5.md / docs/验证脚本-G8.md）——逐条核对全部是**外部基建资源名**（`automation_qiflow-net` docker 网络、`qiflow-twenty-db` 容器、WSL `qiflow-outbound` 目录、历史验证记录引用），非产品名界面面；改名会破坏现网部署。**dismissed**。
- **audit §14 行内自相矛盾**：「新增 8 表……（9 张）」同句自我修正，实义无歧义，cosmetic。**dismissed**。
- **共享测试库拉锯战实录**（CR-002 佐证）：2026-11-04 上午主工作区与 t-o4b worktree 三组 pytest 并存，advisory lock（全程持有）保证了持锁会话结果可信，排队会话将因戳漂移失败——已并入 CR-002 证据。
