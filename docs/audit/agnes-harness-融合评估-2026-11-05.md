# Agnes Harness 对 fde-v3 升级的实质性帮助与融合可行性评估

- 评估日期：2026-11-05；评估对象：`https://github.com/AgnesAI-Labs/agnes-harness`（下称 AGH），本地只读检出 `D:\test\_agnes-harness-review`（sparse checkout，HEAD `2bfde24`）。
- 对照基线：fde-v3 升级目标见 `docs/architecture/蔡工FDE_Workbench_fde-v2架构融合审计与V3升级实施方案.md`（v1.0，2026-11-02）、`AGENTS.md` §28–51、`docs/implementation/v3-backlog.md`、`docs/implementation/v3-迁移进度对照-fde-v2建议-2026-11-04.md`。
- 结论口径：**VERIFIED**（仓库/代码证据）/ **PROPOSED**（建议，尚未实施）/ **UNKNOWN**（无法确认，见 §十）。本报告为只读评估轮：**零代码、零迁移、零依赖引入、零种子改写**。

---

## 0. 执行摘要（先给结论）

**融合结论：不能把 AGH 融合进 fde-v3 作为架构组成部分或能力依赖；可以且只应该以「参考设计 + 测试方法论 + 外部对照样本」的形式纳入。** 其中构成「实质性帮助」的仅 3 项（§4.1），全部是方法论与验收纪律，不是可移植的代码；「有限帮助」5 项（§4.2）；其余为「无直接帮助」（§4.3）。

三条决定性理由：

1. **层不同**：AGH 是 FDE 现场的**插件化 Agent 执行运行时**（`README.zh-CN.md` L64、L88）；fde-v3 是**交付管理系统**（门禁 G1–G9、方案、文档、派单、收款、本体、工作流），AI 编排交由外部 DSH 承担（升级方案 §2 限制 5）。引入 AGH = 引入第二运行时，与升级方案 §19-7「agentscope 进程内多 Agent 团队：引入第二运行时…DSH 已承担编排」的既有裁决正面冲突。
2. **栈不同**：AGH 要求 Node **≥24.10** + pnpm 10.34.5 + mise + 两个原生模块（`package.json` L5-8、`AGENTS.md` L51-53、`verification.zh-CN.md` L10-19）；fde-v3 是 Python ≥3.12,<3.14 / Flask ≥3.1 / SQLAlchemy ≥2 / PG16 / Alembic 32 rev / Electron 43.4.1（`server/pyproject.toml`、`desktop/package.json`、`AGENTS.md` §51）。无共用运行时，无共用包管理器，无共用事实源。
3. **红线冲突**：AGH 普通插件是**进程内受信代码、不隔离任意插件代码**（`README.zh-CN.md` L69、`security.zh-CN.md` L19）；**不承诺外部副作用 exactly-once**（`contracts-v0.1.zh-CN.md` L83、`README.zh-CN.md` L256）；**旧环境不做数据迁移**（`upgrade-from-previous.zh-CN.md` L7、`versioning.zh-CN.md` L19）；Windows 产品级端到端/L1 沙箱未验收（`limitations.zh-CN.md` L12-14）。fde-v3 的红线恰恰相反：证据只存 `source_uri`+sha256、交付禁跑客户代码、外副作用幂等键+不可恢复重投、全部变更走 Alembic 单链、运行在 Windows 宿主。

**时间线校正（重要）**：V3 升级方案 2026-11-02 定稿，P0–P1 共 26 任务在 2026-11-04 前已 DONE（`AGENTS.md` §34–51），**全仓 grep AGH 零命中**（docs/architecture、docs/implementation、docs/audit、AGENTS.md）。AGH 仓库创建于 2026-09-22、最近 push 2026-11-04T14:56Z。因此 AGH **对「fde-v2→fde-v3 升级过程本身」没有效率收益**——它不可能影响已完成的设计决策。帮助窗口只存在于 V3 的 **P2 收尾、P3 评估与下一轮重构**。

---

## 1. 事实基线

### 1.1 仓库事实（GitHub API + 本地检出，全部 VERIFIED）

| 项 | 事实 | 依据 |
|---|---|---|
| 身份 | 公有、非 fork、非归档、非禁用；默认分支 `main`；Apache-2.0；主语言 TypeScript | `/repos` API |
| 时间 | 创建 `2026-09-22T17:18:54Z`；更新 `2026-11-04T15:46:21Z`；push `2026-11-04T14:56:15Z` | `/repos` API |
| 热度 | 1724 stars / 93 forks / 6 open issues / 3 subscribers / size 452059 KB（含 `docs/assets` 演示媒体） | `/repos` API |
| 发布 | **0 个 GitHub Release**（`/releases` 返回 `[]`）；tags 仅 `v0.1.0-preview` + 4 个 `archive/2026-…` 归档 tag | `/releases`、`/tags` API |
| 规模 | tracked 文件 **7572**；`packages/` 6391（约 70 个 workspace 包）、`tools/` 444、`examples/` 413、`docs/` 227、`templates/` 41；**2486 个测试文件**；4 个 workflow（ci / browser / e2e-web / e2e-web-nightly） | `git ls-tree -r` |
| 文档 | 中英双语逐篇成对（`*.md` + `*.zh-CN.md`），覆盖 develop / extend / guide / maintainers / reference 五组 | 目录树 |
| 提交 | 最近可见 14 条全部落在 2026-11-04 约 8 小时内、4 位作者；contributors 共 12 人，前三为 2959 / 712 / 708 次 | `/commits?per_page=30`、`/contributors` |
| 构建 | Node ≥24.10（`.node-version` 固定补丁）、pnpm 10.34.5、mise、需 `build:native`（@agnes/host 与 @agnes/system-node） | `package.json` L5-8、`verification.zh-CN.md` L10-19 |

### 1.2 成熟度与维护状态：必须分「工程成熟」与「产品成熟」

| 面 | 判定 | 依据 |
|---|---|---|
| **工程成熟度** | **高** | `ci.yml` 三平台分片（Windows 3 shard，L74-76）、heavy tier 真实进程测试（L203-297）、SEA 打包烟测（L335-400）、`gen:check` 生成物一致性、`tools/guards` 硬性文件/函数行上限、`git diff --exit-code` 工作树清洁门（L62/L192/L297）；`state-ownership.zh-CN.md` 逐类状态列唯一权威/副本/不一致规则/恢复；`contracts-v0.1.zh-CN.md` 有 stable/experimental 合同清单与冻结就绪清单（L219-242） |
| **产品成熟度** | **pre-alpha** | `README.zh-CN.md` L15 badge、L239-256 状态表、L260-261 FAQ「能用于生产环境吗？暂时还不能」；`limitations.zh-CN.md` L11「没有公共 npm 发布、消费者安装器或自动更新承诺」；`versioning.zh-CN.md` L7「预览阶段的配置、协议和扩展接口可能出现破坏兼容性的变化」；`contracts-v0.1.zh-CN.md` L11「两种标签都不代表生产就绪」 |
| **Windows** | **有 CI 单测，无产品级验收**（勿混为一谈） | `ci.yml` L74-76 有 windows-latest 三分片、L210 夜间 heavy 覆盖 windows；但 `limitations.zh-CN.md` L12-14 明确「Windows 完整端到端验收未验证」「没有已验证的 L1 命令沙箱」，`security.zh-CN.md` L59-61「获准命令使用当前系统账户执行，应用检查不能隔离任意 shell」；README badge 只称 macOS/Linux 为持续维护的检查 |
| **维护政策** | **封闭** | `CONTRIBUTING.md` L15「代码与文档 PR 目前限受邀内部开发者，**外部 PR 不接受**」→ 定制无法回流上游，fork 即永久分叉 |
| **数据兼容** | **无迁移承诺** | `upgrade-from-previous.zh-CN.md` L7「旧环境不做数据迁移」；`versioning.zh-CN.md` L19「运行数据不迁移」；`contracts-v0.1.zh-CN.md` L15「退役格式明确拒绝并提示使用新的空 home，不做转换或沿用旧字节的信任摘要」 |
| **稳定性自述** | **明确不承诺 exactly-once** | `contracts-v0.1.zh-CN.md` L83「没有外部效果 exactly-once 或受管网络 send fence 保证」；`state-ownership.zh-CN.md` A4「没有结算的 effect 保持*未知*，交人工对账，绝不自动重放」；`README.zh-CN.md` L256 |

### 1.3 fde-v3 基线（对照锚）

- **升级目标**（实施方案 §1、§7、§13、§20）：不是"引入 fde-v2"，而是吸收四件思想；五层架构 A Engagement OS（REUSE）/ B Ontology Registry / C Delivery Compiler / D Workflow Engine / E Quality；新增端点一律不进 `api_catalog`（AI 不可直接触达）。
- **现状**（`AGENTS.md` §51）：105 张业务表、Alembic 32 rev head `d4e6f8a2c7b9`、296 路由、`api_catalog` ENTRIES 94、pytest 1838（1832 passed + 6 skipped）、vitest 752/752。
- **硬约束**：客户真实资料只留本地 `D:\test\FDE\…`；门禁证据只存 `source_uri`+sha256；密钥不入 VCS；`origin` 永不 push；每调用实时鉴权/MCP 只衰减 token；外副作用必审批 + 同构 sha256 幂等键 + 不可恢复重投；变更走 4 个 CI job 全绿 + 单 commit revert。
- **演进方向**（`v3-backlog.md` P3 段）：多 Agent 自适应编排（DEFER 观测项）、基于运行反馈的 Skill 改进、业务规则推理、有限自动执行——**明确「本轮仅立项不排期」**。
- **扩展现状**：服务端已有 `control/extensions_service.py`、`builtin_skills.py`、`plugin_seeds.py`、`mcp_gateway.py`、`api_catalog.py`、`extension_management_routes.py`，即 Python 模块 + 白名单工具面，不是插件容器运行时。

---

## 2. 核心定位与主要能力

**定位**：面向 Forward Deployed Engineering 的开源**智能体执行底座**——"LLM 是大脑，Jev 是小脑，Harness 是记忆，MHS 是身体"（`README.zh-CN.md` L33-37）；"把现场差异写进插件，让 Harness 负责执行并留下记录，把验证过的能力带到下一个项目"（L37、L64）。客户端（Web/CLI/TUI/SDK）连到每个 home 一个 App Server，Core 拥有持久事实/授权/恢复，Worker 承载插件版本，**连默认 Loop 也是插件**（L88）。对照文 `why-agh.zh-CN.md` L27 明说 FDE 定义是"工程师深入业务现场，通过系统集成、验证和迭代完成交付"。

**七项主要能力**（`README.zh-CN.md` L92-152）：① 业务 Agent 即插件；② 插件热升级时进行中会话保留原版本代码；③ Web/CLI/TUI/SDK 共享后台会话与恢复；④ 工具审批 + Trace 轨迹时间轴；⑤ Agent 起草 Skill/插件 → 人工审阅后发布（保留起草会话与审阅者）；⑥ 岗位界面（前端槽位/联动插件）；⑦ MHS 设备协议接入（进行中）。

**它明确不是**（L66-71）：不是托管服务、**不是任意插件代码的沙箱**、不是认证设备驱动、**还没有定型**（API/配置/插件接口可能有破坏性变更）。

---

## 3. 与 fde-v3 架构、功能边界、演进方向的匹配度

| 维度 | AGH | fde-v3 | 匹配判定 |
|---|---|---|---|
| 系统层 | Agent 执行运行时 | 交付管理系统，AI 编排外包给 DSH | **不同层**（升级方案 §1「不是同层系统」的同构判断） |
| 唯一事实源 | append-only `events` 账本（哈希链 `(session_key, seq)`）+ 文件/SQLite 元数据（`state-ownership.zh-CN.md` A1-A10） | PG 关系表 + Alembic 单链 + 乐观锁 | **存储范式冲突** |
| AI 编排 | 自带 Loop / provider / model-adapter / child-agent 八类 provider（`contracts-v0.1.zh-CN.md` L93-105） | DSH 外部黑盒（实施方案 §2 限制 5） | **第二运行时，已裁决不引入**（§19-7） |
| 扩展形态 | 全插件化：工具/Loop/适配器/面板/Skills/连接/服务/应用（`README.zh-CN.md` L64） | Python 模块 + extensions_service + MCP 白名单 17+94 | **形态重叠，载体不兼容** |
| 版本固定 | session → generation pin，覆盖全部插件代码（`state-ownership.zh-CN.md` D1/D2） | run → 固定 `definition_version`、skill pinned 版本（`AGENTS.md` §35、§37） | **思想已吸收，粒度不同** |
| 候选→确认 | 候选→测试→权限裁决→发布（`agent-built-plugins.zh-CN.md` L9、L83-100） | `ontology_change_sets` confirm / T-S1 发布四闸 / T-G1 产物候选挂起 | **已有闭环，可强化** |
| 审批 | 三类信任 + 一次/会话/持久授权 + policyDigest（`security.zh-CN.md` L11-23、`state-ownership.zh-CN.md` L178） | sha256 目标绑定 + 15min + 一次性 + 门禁五道闸 | **功能重叠** |
| 证据 | 事实链只读面板、产物引用 + 摘要（`fact-chain.zh-CN.md`） | `project_evidence`（指针+指纹）、`ai_call_audits`、`operation_events` | **数据底座已有，统一只读视图缺位** |
| 演进方向 | Jev 结构化决策、child-agents、Skill 自成长、有限自动执行、Webhook 无人值守 | P3 明确 DEFER 且"立项不排期" | **方向有交集，但被明确推迟** |

---

## 4. 三分类判定（每条给仓库依据 + V3 证据锚点）

### 4.1 实质性帮助（3 项，均为参考设计/方法论，非可移植代码）

**① 状态归属与对账框架** — `docs/develop/state-ownership.zh-CN.md` 全篇。
依据：把每类状态归为**权威 / 投影 / 缓存 / 观测 / Pin** 五分（L17-27），逐类列"唯一权威、修改端口、副本、不一致规则、恢复"（A–H 八章），并给出 8 条不变量（L208-217：每个事实一个写入方、模型可见即已记录、投影可丢弃、期望与实际分开、Pin 是选择不是默认值、崩溃落在提交点某一侧、身份不符失败关闭、生效标签要诚实）；还诚实列出未关闭缺口 G6/G10（L219-235）。
V3 锚点：实施方案 §8 的"不建平行实体体系"、§7 的"Engagement OS = 唯一事实源"是同一思想的口头版，但 V3 没有一份覆盖 `project_evidence` / `ontology_*` / `workflow_*` / `documents` 四层的形式化对账说明。
**可落地**：写成 V3 内部《状态归属与对账》自检清单 + 一组 pytest 断言（候选 confirm 前不物化、快照可从权威重建、指纹不一致拒绝），零依赖零迁移。

**② 崩溃恢复与对抗性测试组织** — `verification.zh-CN.md` L1-40、`ci.yml` L203-297、`testing.zh-CN.md` L45-80 / L111-131、`tools/rsi-eval/`。
依据：`createAuthorTestkit` 覆盖冷恢复、双 generation 并存、审批拒绝路径、工具执行中途升级（L45-80）；`startModelFaultServer` 可编程注入 HTTP 429/503、截断 SSE、畸形 SSE（L111-131）；录制回放对凭据/ID 脱敏且 `assertConsumed()` 防止漏跑（L82-107）；fast/heavy 分层与 eight provider conformance runner（L143-153）；`tools/rsi-eval/fixtures/` 含 `prime-session-aborted-refine` / `repeat-failure` / `stdout-trap` / `source-read` 等对抗夹具，其 README 自述通过**复盘 180 次运行的账本**（不调模型）发现"66 次 skill 保存全被 `unavailable` 拒绝""30 个 workflow run 未计入完成率"——这正是"数字双层证据"的实测形态。
V3 锚点：项目记忆里 agent-autoloop 评估已判定"我方最缺的测试类＝状态机对抗性验证（固定种子模拟 + 强杀不丢 + 变异检查），当前仅 pytest"；`v3-test-plan.md` 的 Workflow 10 用例族偏功能正确性。
**可落地**：给 `workflows/executor.py` 补固定种子 fixture + 强杀不丢 + 迟到拍板 + 双 definition_version 并存 + 节点独立事务失败恢复；不引入任何 AGH 代码。

**③ 只读执行证据链（Fact Chain）** — `docs/guide/fact-chain.zh-CN.md` L1-30、`contracts-v0.1.zh-CN.md` L63-67。
依据：从**回答 / 工具 / 交付物 / 候选来源**四类入口打开同一个只读面板（L7-9）；"面板只读，不运行工具、导入旧代码、改变信任或迁移会话"（L13）；证据表明确区分"请求记录 / 工具结果 / 产物引用 / 候选来源 / 外部完成"，其中**外部完成没有真实回执时为未知，模型自述不够**（L19-25）；"不完整图会标注，不补造连接""事实图不构成外部恰好一次执行保证"（L27-29）。
V3 锚点：服务端 grep `trajectory|trace_view|timeline` 只命中 `documents/generator.py` 的甘特图、`solutions/service.py:605` 的 `_agent_trace`、以及 `AIServerChat.tsx` 的 `tool_trace` 数组；**无统一事实链视图**。但数据底座（`project_evidence` 指针+指纹、`ai_call_audits`、`operation_events`）已齐。
**可落地**：这是唯一可论证的功能层真缺口，补法是 V3 自研只读面板（复用既有表 + can_view），不是移植 AGH；须保留"外部完成未知不编造"这条纪律。

### 4.2 有限帮助（5 项：已有等价物，或改造成本 > 收益）

| 项 | AGH 依据 | V3 等价物 | 判定 |
|---|---|---|---|
| 固定代码 / 实时资源 | `contracts-v0.1.zh-CN.md` L136-148（新会话绑当前 generation、旧会话保 pin，MCP/Skills 下一轮生效） | `workflow_definition_versions` 不可变 + run 固定版本 + skill pinned（`AGENTS.md` §35、§37、§40） | 形态已有；AGH 粒度到全插件代码与容器，改造成本远大于收益 |
| 工具策略元数据 / deny 优先 | L38 `ToolMeta` 的 replay/risk、L160 能力 atoms 计入能力哈希、"标签不参与授权" | T-R1 工具组、T-R2 effect/risk、MCP 白名单（`v3-backlog.md`） | 可作校验器细化参考（如"能力声明不能签发权限"），非缺口 |
| 审批语义与自动审查 | `security.zh-CN.md` L21-55；`state-ownership.zh-CN.md` L178 用 `policyDigest` 只对授权相关字段求摘要，避免模型路由变化使整份 profile hash 失配 | 审批绑定目标参数 sha256 + 15min + 一次性 + 门禁五道闸 | `policyDigest` 是具体可迁移的小设计；但 V3 不绑定整份 profile，适用性有限 |
| 双语文档 / 工具链 pin / guards / gen:check | `AGENTS.md` L23-61、`ci.yml` L44-62、`verification.zh-CN.md` L30-40 | V3 已有 4 CI job + `AGENTS.md` 纪律 + inventory CSV | 仅"生成物一致性检查"与"文档示例可执行校验"值得抄；`limitations`/`verification` 两页形态（单页列全部已知边界 + 单页列实际跑过什么）值得抄 |
| FDE 教学示例 | `examples/fde/README.zh-CN.md` L7-13：知识问答 / 财务对账 / 客服分流 / 数据报告 / 运维巡检 | V3 已有 G1–G9 SOP 与试点手册 | 内容层参考，与架构无关；示例自述"使用合成数据，不是行业产品"（L5） |

### 4.3 无直接帮助（明确排除）

- **产品能力面**：MHS/MOS 设备协议、Computer Use、语音对话、Web 面板槽位/skin、Jev/TypeSafe 决策、child-agents、ACP/Codex/Claude 适配器、MCP 连接池、SEA 打包——与 V3 交付管理职责无交集，且多落在 P3 DEFER。
- **自报成绩**：`README.zh-CN.md` L203-209 的 ALE 榜单 21.7% 通过率 / 42.7 分是结果数字，不是可复用能力；README 自己也注"成绩随模型版本、设置与工具配置而变化"。
- **存储实现**：AGH 的 ledger 哈希链 / registers 投影 / `agnes-lock.json` / generation 快照（`state-ownership.zh-CN.md` A、B、D 章）与 V3 PG+Alembic 冲突；实施方案 §19-2 已把"运行时 DDL reconcile + SQLite 静默回退 PG"列为不照搬项。
- **热升级/包信任运行时**：需要整套 Node 进程、文件锁、原生模块，是运行时组件而非可摘模块。

---

## 5. 可复用 / 借鉴清单（按用户点名的四类）

### 5.1 模块

| 模块 | 可复用性 | 依据 |
|---|---|---|
| 全部 `packages/*`（约 70 个 workspace 包） | **否** | TypeScript / Node 24 / pnpm workspace 内部导出；`contracts-v0.1.zh-CN.md` L34「作者通过声明的包出口导入合同…请固定源码版本」；`versioning.zh-CN.md` L11 多数包 `0.0.0` 未发布且 `private: true` |
| `tools/guards/*` | **仅思想** | Vitest + TS 实现；V3 是 pytest，无法直接跑 |
| `tools/rsi-eval/*` | **仅 fixture 设计** | 离线账本夹具 + `recompute.ts` 不调模型；绑定 AGH ledger 格式 |
| `examples/fde/*` | **仅内容参考** | 合成数据教学插件 |

### 5.2 设计约定（建议抄）

五分法状态归属；8 条不变量；固定代码 + 实时资源分离；期望/实际分离且"没有任何路径由期望推导实际"；Pin 是选择不是默认值；崩溃落在提交点某一侧；身份不符失败关闭；能力声明不是授权（"`agnes.provides` 展示标签不参与授权"，`contracts-v0.1.zh-CN.md` L159）；事实链不补造连接；回执按阶段诚实报告（`agent-built-plugins.zh-CN.md` L56-67 六阶段证据阶梯：草稿生成 / 结构验证 / 候选测试通过 / 安装验证 / 浏览器外观验证 / 已发布，且"不能仅据源码测试说皮肤本身没问题"）。

### 5.3 数据 / 接口约定（冲突为主，两处可借鉴）

- **不移植**：`(session_key, seq)` 事件账本 + 哈希链、`registers` 投影、`writer_claims` 租约、`agnes-lock.json` 包锁、generation 快照目录、JSONL/SQLite persistence contract——V3 用 PG + Alembic + 乐观锁，且实施方案 §19-2 已裁决不照搬同类做法。
- **可借鉴 A**：双哈希审批绑定——`candidateHash` + `reviewHash`，"草稿编辑、审阅副本损坏、已安装基线改变都会拒绝旧审批"（`agent-built-plugins.zh-CN.md` L87-98），且 **Agent 无法自行批准/拒绝**（L98）。V3 T-S1 发布闸已有 `content_sha256` + 测试报告，补"审阅摘要哈希 + 编辑即作废旧审批"是零迁移小增强。
- **可借鉴 B**：版本准入三段身份——`apiRange` / `codecVersion` / `HARNESS_VERSION`（`contracts-v0.1.zh-CN.md` L17-26、`versioning.zh-CN.md` L15），对 V3 workflow 定义与 skill schema 的版本兼容判定有参考；但 V3 已有 `definition_versions` + `skill_versions`，属细化而非缺口。
- **同构非增量**：产物引用只存摘要/指针、读取时校验精确 MIME 与 size（`contracts-v0.1.zh-CN.md` L63-67）——与 V3 "证据只存 `source_uri`+sha256" 红线同构，说明红线方向正确，不构成新帮助。

### 5.4 测试与文档

- **测试组织（建议抄）**：fast/heavy 分层（`AGENTS.md` L70）、八类 provider conformance runner（`testing.zh-CN.md` L143-153）、HTTP/SSE 故障注入（L111-131）、录制回放脱敏与消费断言（L82-107）、冷恢复/双 generation/拒绝路径（L45-80）、硬性文件与函数行上限（`verification.zh-CN.md` L30-40）、CI 三平台分片 + 工作树清洁门（`ci.yml`）、"测试中的跳过项与未验证范围必须如实保留"（`verification.zh-CN.md` L40）。
- **文档组织（建议抄两页形态）**：`reference/limitations` 单页列全部已知边界、`maintainers/verification` 单页列实际跑过的命令与范围；`docs/develop/source-map` 定位归属包；`NOTICE` + `maintainers/provenance` 逐项列第三方许可（Cordis/Cosmokit MIT、DeepSeek 部分 MIT、JevLoop Apache-2.0、Nous Research MIT）。V3 已有中文文档体系与 inventory CSV，缺的是"已知限制/验证范围"两页的显式化。

---

## 6. 对升级效率、稳定性、可维护性、扩展性、兼容性的实际收益

| 维度 | 若采纳「参考设计 + 测试方法论」（§4.1/§5） | 若「融合组件 / 引入运行时」 |
|---|---|---|
| 升级效率 | **低**：升级方案 11-02 定稿、26 任务 11-04 前完成、全仓未引用 AGH，本轮只能改善 P2 收尾与 P3 评估，不能回溯加速已完成工作 | **负**：需重写栈或双栈并存，量级 ≥ 一个完整子系统；且违反实施方案 §17「不并行开第二实施线」 |
| 稳定性 | **中高**：对抗性测试 + 状态对账能补 V3 已识别的真实缺口（状态机验证、四层事实源一致性） | **负**：AGH 明确不承诺 exactly-once、无结算 effect 保持未知（`contracts-v0.1` L83、`state-ownership` A4），与 V3「幂等键 + 不可恢复重投」语义冲突；pre-alpha API 破坏性变更 |
| 可维护性 | **中**：文档/测试纪律与缺口显式化降低后续会话误判 | **负**：外部 PR 不接收（`CONTRIBUTING.md` L15）→ fork 永久分叉；无数据迁移；约 70 个包 + 2486 测试文件的维护面 |
| 扩展性 | **低**：V3 扩展走 Python 模块 + MCP 白名单，当前不缺插件容器 | **似高实负**：引入 Node 24 运行时、pnpm/mise、原生编译与 Windows 未验收路径，扩展面反而变成约束 |
| 兼容性 | **零成本**：纯文档 / 纯 pytest，不动表、不动路由、不动种子 | **负**：Node≥24.10/pnpm 10.34.5/native vs Python 3.12/Flask/Electron 43；AGH home 含会话正文与工具参数（`security.zh-CN.md` L182 自述需检查用户输入/路径），与 V3 客户资料红线叠加出新的数据出境面 |

---

## 7. 四种融合方式的可行性、冲突、重叠、依赖、风险与成本

| 方式 | 可行性 | 冲突点 | 功能重叠 | 依赖约束 | 维护风险 | 改造成本 | 裁决 |
|---|---|---|---|---|---|---|---|
| **① 架构组成部分**（AGH 作 V3 执行层） | **不可行** | 第二运行时（§19-7 已裁决）；PG 关系表 vs ledger 双事实源；外副作用语义相反；Windows 产品级未验收；客户资料红线 | Workflow / Skill / 审批 / 证据四域全面重叠 | 全栈 Node 24 + 原生构建 + 独立 home/daemon/worker | pre-alpha API 破坏性变更、无迁移、外部 PR 封闭 | 重写或双栈并存，最高 | **否决** |
| **② 能力复用**（拷贝模块/包） | **不可行** | TS/Node24；`contracts-v0.1` L34 要求固定源码版本；NOTICE 多方许可需逐项继承 | 与 `extensions_service`/`mcp_gateway` 已有能力重叠 | pnpm workspace 内部导出，多数包 `0.0.0`+`private` | 摘出的模块随上游漂移即失效 | 高（需重写为 Python 或维护第二构建链） | **否决** |
| **③ 外部引用**（独立部署，经 MCP/HTTP 对接） | **理论可行，当前不建议** | V3 已有 DSH 外部编排；AGH Web 只监听回环且"不是带远程登录/反向代理支持的公共服务"（`limitations.zh-CN.md` L15）；`security.zh-CN.md` L166 明说不要暴露公网 | 与 DSH 的 Agent 编排职责重叠 | 独立进程 + 双向鉴权 + 凭据/客户资料边界重新验收 | 两侧版本各自演进，契约无稳定承诺（experimental 为主） | 中高（一个独立部署 + 适配层 + 安全验收） | **暂缓** |
| **④ 参考设计**（只抄约定、测试组织、校验规则） | **可行，推荐** | 无（不改运行时、不改数据模型） | 无新增重叠 | 零新增依赖 | 零（结论落在 V3 自有文档与 pytest） | 低（文档 + 一组用例） | **采纳** |

方式 ④ 与 V3 既有方法论一致：实施方案 §1「不是引入 fde-v2，而是吸收四件经过验证的思想」、§19「七项不照搬」、`AGENTS.md` §33「裁决=不引入 fde-v2 实现只吸收思想」。

---

## 8. 优先级排序与纳入范围（可据此决策）

| 优先 | 动作 | 落点 | 前置 / 验收 | 分类 |
|---|---|---|---|---|
| **P0-1** | 写 V3《状态归属与对账》自检清单，覆盖 `project_evidence` / `ontology_*` / `workflow_*` / `documents` 四层（五分法 + 8 不变量 + 缺口表） | `docs/architecture/`（PROPOSED） | 零代码；下一轮纳入文档校验；每类状态须写明"不一致时谁说了算" | 实质性 |
| **P0-2** | 给 `workflows/executor.py` 补对抗性 pytest：固定种子、强杀不丢、迟到拍板、双 `definition_version` 并存、节点独立事务失败恢复；采用 rsi-eval 的"离线 fixture + 重算不调模型"组织 | `server/tests/`（PROPOSED） | 不引入 AGH 代码；须显式列出跳过项与未验证范围 | 实质性 |
| **P1-3** | T-G1 / T-S1 补"审阅摘要哈希 + 编辑即作废旧审批"（双哈希）+ 六阶段证据阶梯验收用例 | 依附既有任务，单独立项 | 零迁移；须证明"测试通过 ≠ 已安装 ≠ 已发布" | 实质性（强化） |
| **P1-4** | 只读执行证据面板：从交付物 / AI 回答反查 `project_evidence` + `ai_call_audits` + `operation_events` | `desktop/` + 只读 API（PROPOSED） | 单独立项；面板只读、外部完成显示"未知"不编造 | 实质性（功能缺口，自研） |
| **P2-5** | 把 AGH 登记为「外部对照样本」写进 `docs/audit/` 索引，注明观察窗口与重评触发条件 | 本报告 + 索引 | 纯文档 | 有限 |
| **P2-6** | 补一份 V3《已知限制》与《验证记录》两页形态文档 | `docs/`（PROPOSED） | 纯文档，须如实记录未验证范围 | 有限 |

**不建议纳入**：任何 AGH 代码/包/依赖声明、运行时替换、MCP 对接、fork 维护、`package.json` 或 `pyproject.toml` 变更、任何 Alembic 迁移、种子文件改写、把 AGH 列为 V3 的架构组件。

**重评触发条件（明确可验证，四者未满足前结论不变）**：① AGH 发布正式 v0.1（非 preview）+ 公开 npm 包与 semver 兼容承诺；② Windows 产品级端到端验收与 L1 沙箱完成；③ 上游开放外部 PR 或给出数据迁移承诺；④ V3 P3「多 Agent / 有限自动执行」正式立项排期。

---

## 9. 明确融合结论

1. **能否融合进升级后的 fde-v3 作为架构组成部分或能力依赖：不能。** 层、栈、事实源、安全语义、平台验收、维护政策六项同时不成立；且与 V3 已完成的 §19-7「不引入第二运行时」裁决直接冲突。
2. **能否作为外部引用（并行运行时）：当前不能推荐。** 待 §8 重评条件满足且 V3 P3 立项后再评估。
3. **能否作为参考设计 / 能力借鉴：能，且是唯一推荐方式。** 实质性帮助 3 项（状态归属框架、对抗性测试组织、只读事实链），有限帮助 5 项，其余无直接帮助。全部落在文档与 pytest，不改变 V3 架构、依赖与红线。
4. **对「fde-v2 → fde-v3 升级」这一动作本身的帮助：无直接帮助**（时间线在后 + 全仓未引用）。对 V3 后续 P2 收尾、P3 评估与下一轮重构：有上述 3 项。
5. 本轮未实施任何工程改动；§8 全部为 PROPOSED，需按 V3 既有 goal 循环逐任务立项，不并行开第二实施线。

---

## 10. 无法确认的信息与所依据假设（不把推测当事实）

| # | 项 | 现状 | 本报告采用的假设 | 若假设不成立的影响 |
|---|---|---|---|---|
| 1 | V3 的「DSH AI Server」与 `why-agh.zh-CN.md` L17 链接的 `deepseek-ai/deepseek-harness`（文中缩写 dsh）是否同源 | **2026-11-05 晚已核实**：`server/src/fde_api/control/dsh_runtime.py:1` docstring 明写 "Versioned client for the separately deployed **DeepSeek Harness adapter**"；`config.py:74` / `ai_server_client.py:168` 协议为 FDE 自定 `fde-dsh-v1`；官方仓库 `deepseek-ai/deepseek-harness` 真实存在（MIT / TypeScript / topic `dsh`） | **二者相关但不等同**：V3 依赖的是**单独部署的适配层**，不是官方 CLI 本体；AGH 是借鉴 DSH「一切皆插件」理念的独立项目 | **结论不翻转，反而加强**——V3 已有明确的外部 Agent 编排位（DSH），再引入 AGH 仍是第二运行时；§1 三条硬理由与 §7 裁决全部维持 |
| 2 | 1724 stars、ALE 21.7% / 42.7 分 | 仅 README 自报与 API 计数，未独立核验榜单、复现脚本与统计口径 | **不作为能力证据**，只作热度事实 | 不影响裁决（结论不依赖成绩） |
| 3 | 是否有企业生产部署案例 | 文档无案例，FAQ 明说"暂时还不能"用于生产 | **假设无生产验证** | 若存在大规模生产案例，成熟度档可上调，但栈/层/红线冲突不变 |
| 4 | 长期维护与版本节奏 | 建仓约 6 周、0 Release、最近提交集中在 11-04 单日、外部 PR 不接收 | **假设破坏性变更会持续** | 若发布稳定版并开放贡献，方式 ③ 可重评 |
| 5 | 是否可只用境内模型 | NOTICE 提到 DeepSeek 部分代码；演示默认 Agnes 2.5/3.0，adapter 支持 Claude/Codex；V3 是否强制境内模型尚未拍板（项目记忆中 agent-autoloop 评估列为待用户确认） | **假设 V3 的 AI 编排仍走现有 DSH，不因 AGH 改变模型合规边界** | 若强制境内模型，方式 ①②③ 的合规成本进一步上升，④ 不受影响 |
| 6 | V3 桌面端是否已有统一事实链视图 | grep 仅见 `AIServerChat.tsx` 的 `tool_trace` 数组、`documents/generator.py` 甘特图 `timeline`、`solutions/service.py:605` `_agent_trace`；**未逐页走查 116 个 tsx** | **假设不存在统一只读事实链面板** | 若已有，§4.1 ③ 从"实质性"降为"有限帮助" |
| 7 | AGH 全部源码的逐行审计 | 精读 17 份关键文档/配置 + 目录树 + API 元数据；**未逐行审 6391 个 `packages/` 文件** | 模块级可复用性判定基于公开合同、目录结构与构建约束，不基于逐文件代码审阅 | 不影响"不引入代码"的结论；若未来要摘模块需补一轮行号级审计 |

### 校正记录（2026-11-05 晚，DSH 身份专项核查后）

上表第 1 项原写作「假设二者不是同一系统」，现据代码事实校正。**注意不要与 `.workbuddy/memory/2026-10-26.md:209` 的历史记录混淆**——该日志记录「DSH = `AgnesAI-Labs/agnes-harness`（AGH）」，与 `dsh_runtime.py:1` 的 docstring 冲突；核对 AGH 仓库 `why-agh.zh-CN.md` L17 可知 AGH 只是**引用/借鉴** `deepseek-ai/deepseek-harness` 的「一切皆插件」理念，并非 DSH 本体。以本校正记录为准。

补充事实（同样不改变裁决）：`deepseek-ai/deepseek-harness` 为 **developer preview**，README 明示 "THERE WILL BE COMPATIBILITY-BREAKING CHANGES"，`SAFETY.md` 明示未经安全审计、不得视为生产可用、建议一次性 VM/容器运行；官方只提供 `npx @deepseek-ai/dsh web`（Web UI，默认 3080）与 `dsh --profile headless`，未实现 V3 所需的 `fde-dsh-v1`（`/v1/executions`、`Idempotency-Key`、`X-FDE-Protocol-Version`、MCP 回环 token、`/internal/dsh/...` 回调）。**本机全仓无适配层源码**，故「不引入 AGH」之外，V3 自身的 DSH 启用也仍是运维挂账、未实施。

---

## 11. 证据来源清单

**AGH 侧**（本地只读检出 `D:\test\_agnes-harness-review`，HEAD `2bfde24`）：
`README.zh-CN.md`、`AGENTS.md`、`CONTRIBUTING.md`、`SECURITY.md`（索引）、`package.json`、`pnpm-workspace.yaml`、`NOTICE`、`.github/workflows/ci.yml`、`docs/reference/limitations.zh-CN.md`、`docs/develop/contracts-v0.1.zh-CN.md`、`docs/develop/state-ownership.zh-CN.md`、`docs/guide/security.zh-CN.md`、`docs/guide/fact-chain.zh-CN.md`、`docs/guide/why-agh.zh-CN.md`、`docs/guide/upgrade-from-previous.zh-CN.md`、`docs/extend/agent-built-plugins.zh-CN.md`、`docs/extend/testing.zh-CN.md`、`docs/maintainers/versioning.zh-CN.md`、`docs/maintainers/verification.zh-CN.md`、`examples/fde/README.zh-CN.md`、`tools/rsi-eval/README.md` 与 `fixtures/`、`tools/guards/src/` 目录清单。
**GitHub API**：`/repos`、`/commits?per_page=30`、`/contributors`、`/tags`、`/releases`、`/contents/`。

**fde-v3 侧**：`AGENTS.md`（§28–51 现状与口径）、`docs/architecture/蔡工FDE_Workbench_fde-v2架构融合审计与V3升级实施方案.md`（§1/§2/§7/§13/§19/§20）、`docs/implementation/v3-backlog.md`（P3 段、T-G1、T-S1、T-R1/R2）、`docs/implementation/v3-迁移进度对照-fde-v2建议-2026-11-04.md`、`docs/implementation/v3-test-plan.md`、`server/pyproject.toml`、`desktop/package.json`、`server/src/fde_api/` 与 `desktop/src/renderer/src/` 定向 grep。

---

### 附：本轮产出

新增本报告 1 份（`docs/audit/agnes-harness-融合评估-2026-11-05.md`）；纯文档轮，未改动任何业务代码、台账、迁移、种子或依赖。
