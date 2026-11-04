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
| c3 | 交付主链（projects/solutions/documents/guidance/templates/evidence/files/storage/mailing/translator） | **进行中 2026-11-04**（隔离矩阵 86 路由全绿；CR-008/010 P1 修、CR-009 P2 补测试，PR 交付中） | docs/goal-c3-代码审查.md |
| c4–c8 | 见上 | 未开始 | — |

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
| CR-008 | P1 | open | signoff「同方案至多一个 pending」无并发防线：SELECT-then-INSERT 无行锁/无部分唯一约束，双 run 并发 `_finalize` 可双插 pending | agents/signoff.py:30-48 / agents/models.py:216-231 | c3 |
| CR-009 | P2 | open | G8-stop 结算联动 `flag_g8_stop_settlement` 零测试载体（gate_service:504 调用点，tests 全仓 grep 命中 0） | projects/payment_service.py:347-374 | c3 |
| CR-010 | P1 | open | quote_service 数值防御不自洽：deviation 先落库后 400 检查（Numeric(7,4) 可被 10⁵ 倍偏差击穿→500）、create 侧 cash_cost 无 MAX 上限、finalize 同型 | projects/quote_service.py:292 / 527 / 638 | c3 |
| CR-011 | P3 | open | mailing/translator/guidance 三包意图锚分散 4 份文档，V3 主报告无集中裁决行（NEEDS-EVIDENCE 定级，倾向 P3 文档补齐） | V3 审计 §13 / 各 goal-d 台账 | c3 |

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

- **状态**：open（c3 发现，当轮修）
- **file:line**：`server/src/fde_api/agents/signoff.py:30-48`（`ensure_pending_signoff` SELECT-then-INSERT）；`server/src/fde_api/agents/models.py:216-231`（`SolutionReviewCheckpoint` 表 args 只有三个 CHECK + 一个普通复合 Index，**无 UNIQUE、无部分唯一索引**）。
- **意图锚**：AGENTS.md T-P0-1 段 + `agents/signoff.py:3` docstring 原文：「同方案至多一个 `pending` signoff；已有 pending 时只补 run 软链……绝不重复开闸」。对照同仓 `evidence/models.py:24-27` 的 `uq_project_evidence_fingerprint` 部分唯一约束先例——本系统对「同资源至多一个」语义的既有做法是 DB 约束兜底。
- **触发路径**：同一方案、同一幂等键的两个并发 `start_run`（不同 `idempotency_key`，如客户端/重试各带一个 key）→ 两 worker 各自 `run queued→completed` → 各自 `session.begin()` 内 `ensure_pending_signoff`：READ COMMITTED 下双方 SELECT pending 均 None（对方 INSERT 未提交）→ 双双 INSERT → 同方案两行 pending。`_finalize` 侧（`agents/service.py:428`）未锁方案行，兜底事务（`solutions/service.py:680`）虽对项目行 `with_for_update` 但 `_finalize` 不锁——两侧无交集锁。后果：`resolve_signoff`（`solutions/service.py:339-345`）按 created_at 取最早 pending 收口，第二行成孤儿永远滞留；`solution_review_trail`（L276-281）取**最新** pending 展示 → 终审台口径漂移。
- **驳斥记录**：①「SELECT-then-INSERT 在单事务内语义成立」——成立，但 docstring 承诺的幂等语义是跨事务的（三处调用来自三个独立 `session.begin()` 块：`agents/service.py:488`/`:909`/`solutions/service.py:658`），单事务内正确不等于并发正确；②「概率低」——两个 run 并发 finalize 同方案 = 同方案双 agent 跑，`start_run` 无「同方案在途 run 唯一」约束（幂等键是 key 维度而非 solution 维度），真实用户可触发。
- **证据等级**：结构面 E0（无锁无 UNIQUE 的直读）；双插后果腿 E2（未构造双事务实跑，PG READ COMMITTED 行为）——**修法前须 E0 实证**：双线程 advisory-free 并发调 `ensure_pending_signoff` 断言行数=2。
- **建议修法**：`ensure_pending_signoff` 入口先 `SELECT pg_advisory_xact_lock(hashtext('fde_signoff:' || :solution_id))`（同仓 `quote_service.py:592` 的 `fde_quote_first_order` 先例同构）→ 锁内 SELECT-then-INSERT；可选加固：迁移加部分唯一索引 `UNIQUE (solution_id, checkpoint_type) WHERE checkpoint_type='signoff' AND status='pending'`（零 DDL 冲突：存量数据每方案至多一 pending，合法形态全兼容）——迁移走 goal-d 三件套。P1 当轮修。
- **修复 PR**：—（本轮修）

## CR-009 · P1 · G8-stop 结算联动零测试载体

- **状态**：open（c3 发现，当轮补测试）
- **file:line**：`server/src/fde_api/projects/payment_service.py:347-374`（`flag_g8_stop_settlement`）+ `gate_service.py:504-508`（decide G8 stop 时调用）。
- **意图锚**：`payment_service.py` 函数 docstring 原文：「G8 stop 也按合同结算（SOP §S8 拍板三态）：门禁引擎 decide stop 时联动给 G8 尾款行打 `settlement_reason='g8_stop'`——B 尾款照收」。
- **触发路径**：`decide_gate(project, "G8", decision="stop")` → 尾款行打标记。两个无载体分支：(a) G8 计划内无尾款行 → 只留事件不落标记；(b) 重复 stop 拍板 → note 追加不重复。
- **E0 证据**：`grep -rn "g8_stop\|flag_g8_stop" server/tests/` 命中 **0**；`test_gates_api.py` G8 用例只覆盖 conditional_pass/decision 必填（L133-197）；`test_dispatch_p0_r2.py` 的 `_g8_passed` 是手工插 passed 行、非 decide-stop 路径。
- **驳斥记录**：「stop 是罕见分支不值得测」——不成立：本函数是 SOP 拍板三态的结算联动点，错打标记=尾款计提口径错，且「无行只留事件」分支是纯控制流，缺测试=下轮无回归网。P1（测试缺口类：语义承诺无载体，按 c3 验收「signoff 异常路径各一条触发路径」同类标准当轮补）。
- **证据等级**：E0（零命中 grep + 调用点直读）。
- **建议修法**：`test_gates_api.py` 或新文件补 2 用例：decide stop 有尾款行→`settlement_reason='g8_stop'` + 事件；无尾款行→只事件不落标记；重复 stop→幂等。
- **修复 PR**：—（本轮修）

## CR-010 · P1 · quote_service 数值防御不自洽（500 而非 400 + cash_cost 无上限）

- **状态**：open（c3 发现，当轮修）
- **file:line**：
  ① `quote_service.py:527-530`（calibrate：`quote.deviation_pct = deviation` **先落库**，L536 的 99.99 上限检查的是 `calibrated_buffer` 不是 deviation）+ `workbench/models.py:721` `deviation_pct: Numeric(7,4)`（整数位 3，上限 999.9999——注：子代理初报 9999.9999 系误读，实为 999.9999）；
  ② `quote_service.py:292-295`（create：`cash_cost` 只拒负数、无 MAX；对照 `MAX_INPUT_MONEY=10⁷` L122 已用于 `final_amount` L574）+ `workbench/models.py:693-695` `labor_cost/total_cost/formula_price: Numeric(12,2)`（上限 99,999,999,999.99，cash=5×10¹⁰ 可击穿）；
  ③ `quote_service.py:638`（finalize：`final_deviation_pct = (final−anchor_low)/anchor_low`，final≤10⁷、anchor_low≥18000 合法极小偏差 <100% 内；但 cash_cost 超上限使 total_cost 先溢出，同 ② 型）。
- **意图锚**：`quote_service.py:120` 注释原文：「数值入参的合理上限（工程防御，非方法论取值）：超出即视为录入错误**拒 400**」。
- **触发路径**：① ideal=0.01（合法 L286）+ calibrate actual=9999（合法 L511 ≤10000）→ deviation≈999,899.99 > Numeric(7,4) → `session.flush()` 抛 `DataError` → 全局 `errors.py:31` 捕获为 500；② create cash_cost=5×10¹⁰ → labor/total/formula 溢出 → 同 500。
- **驳斥记录**：「10⁵ 倍工时偏差工程上 unrealistic」——部分成立，但守卫自述口径就是「超出=录入错误拒 400」，500 违反自身文档约定；且 ② 的 cash_cost 是开放整数入参，无 realistic 假设可依托。修复成本极低（deviation 校验前移 + cash_cost 加 MAX + finalize 侧同型补 400），零风险。
- **证据等级**：代码路径 E0（先落库后检查直读）；「Numeric 溢出→DataError→500」结果腿 E2——**修法前须 E0 实证**（单条 pytest 构造 10⁵ 偏差断言 500，或直连 PG 验列上界）。
- **建议修法**：calibrate 中 `deviation` 超 `Decimal("999")` 先 400（对齐 L536 既有 400 语义，改检查对象与位置）；create 侧 `cash_cost > MAX_INPUT_MONEY` 拒 400；finalize 侧对 `final_deviation_pct` 同型防御。三处纯服务层 400 化，零迁移零路由。P1 当轮修。
- **修复 PR**：—（本轮修）

## CR-011 · P3 · mailing/translator/guidance 意图锚分散（NEEDS-EVIDENCE 定级）

- **状态**：open（c3 发现，P3 登记不修）
- **file:line**：`docs/architecture/蔡工FDE_Workbench_fde-v2架构融合审计与V3升级实施方案.md` §13（三包仅出现在「不触碰」边界行）；意图实际分散于：`docs/SES发信模块-G9.md`（mailing）/ `docs/goal-d13·d14`（translator）/ goal-d 各台账（guidance adopt 闭环）。
- **意图锚**：intended-vs-implemented 纪律——意图没写在一处可查的地方即「意图未记录」。实现面零走样（A6「不触碰」+ 各包既有文档逐条吻合，见 c3 报告 §2）。
- **驳斥记录**：「§13 不触碰行已够」——部分成立：不触碰是边界声明不是意图锚；三包各自独立文档存在且自洽，缺的只是主报告集中指针。P3 文档漂移，登记。
- **证据等级**：E0（四份文档位置实测）。定级腿 E2（「是否足够」属文档治理判断）→ P3 封顶。
- **建议修法**：V3 主报告 §13 或 §20 补三包指针行（同 CR-003 类，文档轮顺手）。
- **修复 PR**：—

## 驳回/观察记录（不占编号）

- **旧产品名残留扫描**：`qiflow` 命中 7 个 tracked 文件（README.md / compose.yaml / server/Dockerfile / scripts/check-pseudonymization.sh / scripts/verify/run-verify.sh / docs/代码评审-G5.md / docs/验证脚本-G8.md）——逐条核对全部是**外部基建资源名**（`automation_qiflow-net` docker 网络、`qiflow-twenty-db` 容器、WSL `qiflow-outbound` 目录、历史验证记录引用），非产品名界面面；改名会破坏现网部署。**dismissed**。
- **audit §14 行内自相矛盾**：「新增 8 表……（9 张）」同句自我修正，实义无歧义，cosmetic。**dismissed**。
- **共享测试库拉锯战实录**（CR-002 佐证）：2026-11-04 上午主工作区与 t-o4b worktree 三组 pytest 并存，advisory lock（全程持有）保证了持锁会话结果可信，排队会话将因戳漂移失败——已并入 CR-002 证据。
