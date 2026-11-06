# sample-fdep-mcp-server（Partner FDE Delivery Kit）对 fde-v3 的对照评估

- 评估日期：2026-11-05；评估对象：`D:\test\FDE\knowledge\sample-fdep-mcp-server`，本地只读副本，git HEAD `470fa2b`（2026-11-02），remote `https://github.com/aws-samples/sample-fdep-mcp-server.git`（下称 **FDEP Kit**）。
- 对照基线：fde-v3 升级目标与约束见 `docs/architecture/蔡工FDE_Workbench_fde-v2架构融合审计与V3升级实施方案.md`（v1.0，2026-11-02）、`AGENTS.md` §28–51、`docs/implementation/v3-backlog.md`、`docs/implementation/v3-迁移进度对照-fde-v2建议-2026-11-04.md`；口径沿用 `docs/audit/agnes-harness-融合评估-2026-11-05.md`。
- 结论口径：**VERIFIED**（仓库/代码证据）/ **PROPOSED**（建议，尚未实施）/ **UNKNOWN**（无法确认，见 §10）。本轮为只读评估轮：零代码、零迁移、零依赖、零种子改写。
- 范围约定：本文只给评估结论与纳入范围，不展开实现步骤、操作指南或代码。

---

## 0. 执行摘要（结论先行）

**融合结论：不采纳该仓库作为 fde-v3 的整体方案、架构组件或运行时依赖；采纳「局部借鉴」——仅取其设计约定、契约清单与内容分类框架，且必须经适配后以 V3 自有形态表达。** 四种融合方式中，「参考设计」是唯一推荐档；「架构组成部分 / 能力复用 / 外部引用」三档均否决或暂缓。

三条决定性理由：

1. **云与场景绑定**：FDEP Kit 是「在 AWS 上构建 AI-native 应用」的交付知识包——9 个 program 全部基于 Bedrock / CDK / AgentCore / Well-Architected / AI-DLC，27 份参考模式含可运行 CDK、Python agent、React UI（`README.md` L3-5、L194-206；`documentation/REFERENCES.md` L1-20）。fde-v3 是**全行业、非云绑定、境内运行**的交付管理系统（用户已明确工作台不再仅服务制造业），升级方案 §2 限制 5 把 AI 编排定为外部 DSH 黑盒。内容层几乎不可直接用。
2. **MCP 方向相反**：FDEP Kit 是 **MCP Server 提供方**——stdio 本地进程，向 Kiro / Claude / Cursor 等 13 个 IDE 客户端暴露 12 个工具（`README.md` L170-176、L219-223）。fde-v3 是 **MCP 工具被调方**——DSH → `POST /internal/ai/mcp` → `mcp_gateway.call_tool` → 注册表 + 实时鉴权（升级方案 §3-3 / §7 架构图 L94）。两者不在同一条链路上，接入即引入第二编排面，与升级方案 §19-7「不引入第二运行时」、§17「不并行开第二实施线」冲突。
3. **交付红线相反**：FDEP Kit 的 `fde_render` / `fde_install_assets` 把 steering、skills、`state/` 文件**写入客户工作区磁盘**，并驱动 Agent 生成、部署客户代码（`MCP-TOOLS.md` L140-161、L288-315）。fde-v3 红线是「客户真实资料永不进 git 与数据库」「门禁证据只存 `source_uri`+sha256」「交付禁跑客户代码」（`AGENTS.md` 红线节）。文件落地形态不能直接迁移。

**但相对 agnes-harness，本仓库有两点明显更近**：① 它是**纯数据驱动的方法包**（`programs/` 157 个 YAML/MD 文件，`ADD-A-PROGRAM.md` L3「programs are data, not code」），与 V3 已有的 `skill_definitions` / 行业模板 / SOP 种子同构；② 它的 **Lens 正交叠加模型**、**10 条可测不变量**、**引用索引两级注入** 正好落在 V3 已登记的演进缺口上。因此结论不是「无帮助」，而是「帮助集中在设计层、且范围很窄」。

**时间线校正**：V3 升级方案 2026-11-02 定稿、26 个任务 11-04 前已 DONE；全仓 grep `fdep|fdep-mcp|sample-fdep` 零命中（本轮核验 `docs/architecture`、`docs/implementation`、`docs/audit`、`AGENTS.md`）。本地副本 HEAD 亦为 11-02。故 FDEP Kit **对「fde-v2→v3 升级动作本身」无直接帮助**；帮助窗口只在 P2 收尾、P3 评估与下一轮重构。

---

## 1. 事实基线

### 1.1 仓库事实（本地副本 + git，全部 VERIFIED）

| 项 | 事实 | 依据 |
|---|---|---|
| 身份 | AWS 官方样例 `aws-samples/sample-fdep-mcp-server`，**MIT-0**（无署名义务）；`package.json` name `fde-kit` v0.5.0 | `LICENSE`、`package.json` L2-3、remote -v |
| 维护 | **18 次提交、3 位作者、0 个 tag**；CHANGELOG 最新条目 `0.5.1 / 2026-08-10`，git HEAD `470fa2b / 2026-11-02`（依赖审计合并） | `git log`、`git tag`、`CHANGELOG.md` L8 |
| 规模 | 270 个文件：`programs/` 157、`core/src/` 34、`lenses/` 26、`adapters/` 20、`documentation/` 10、`schemas/` 6、`scripts/` 3、`pipelines/` 3 | 全树统计 |
| 栈 | Node **>=22**（`engines`；README L70 写 22+，`QUICKSTART.md` L13 写 20+，**文档不一致**）；4 个 pinned 运行时依赖（ajv / ajv-formats / handlebars / yaml）；无原生模块、无 post-install；TypeScript strict | `package.json` L21-29、`tsconfig.json`、`README.md` L267-269 |
| 形态 | stdio MCP Server，**12 个工具**；零出站网络调用；只读自身目录 + 仅写指定 `engagementDir` | `bin/fdep-mcp.mjs` L1-20、`MCP-TOOLS.md` L337-344 |
| 目录 | 9 programs / 6 industry lenses / 13 platform adapters / 6 JSON Schemas / 3 pipeline YAML | `README.md` L192-240、`ls` |
| 五原语 | Intention（schema 校验的客户状态）/ Program（skills+steering+exitCriteria+激活谓词）/ Lens（行业叠加）/ Adapter（平台渲染）/ MCP server（薄门面） | `README.md` L180-188 |

### 1.2 成熟度与维护状态：必须区分「设计完整」与「工程验证」

| 面 | 判定 | 依据 |
|---|---|---|
| **设计完整度** | **中高** | 6 份 JSON Schema（`engagement` / `intention` / `lens` / `program` / `skill` / `steering`）；`INVARIANTS.md` 10 条可测契约；手写递归下降 DSL 解析器（`core/src/expression/index.ts` L2-5：`No eval, no Function, no require, no dynamic import`；L334-336 `ALLOWED_IDENTIFIERS` 白名单拒绝未知标识符，对应 P5/P10）；resolver 五阶段 + 确定性排序（`resolver/index.ts` L37-118） |
| **工程验证** | **低（关键限制）** | 仓库内 **0 个测试文件**（`core/test/` 仅 `.gitkeep`）；**0 个 `.github` 文件 / 0 条 CI workflow**；`INVARIANTS.md` L3 声称「enforced by the test suite」，`CONTRIBUTING.md` L59 却自注「Run test suite (**if tests exist**)」；`ADD-A-PROGRAM.md` L3 明说新增 program 「No new tests required」。`precommit` 脚本存在但无 CI 强制 |
| **产品成熟度** | **样例 / 非产品化** | 0 Release、0 tag；CHANGELOG 仅两条（0.5.0 首发、0.5.1 修复）；`CONTRIBUTING.md` 定位为样例贡献；依赖靠 `overrides` 逐项锁版本 |
| **安全面** | **声明较完整，实际规则为空** | `core/src/security/` 四件套：path-validation（遍历 / 符号链接 / 系统目录 / 盘符根，L63-152）、secrets 扫描（gitleaks 式）、portability 扫描（禁客户名进知识包）、session-limits（50 intention / 64KB / 512KB，`MCP-TOOLS.md` L339-342）；但 `programs/.portability.yaml` 实际为 **`disallowed: []`（空规则）**，扫描器 opt-in 且当前无命中项 |
| **维护政策** | **开放但轻量** | `CONTRIBUTING.md` 接受 Fork + PR（优于 AGH 的「外部 PR 不接受」）；但 3 位作者、18 提交、0 tag，不能作为长期依赖 |

> **对评估的影响**：§4 中「10 条不变量」只能作为**契约清单**借鉴，不能当作「已验证的工程纪律」引用；这是与 agnes-harness（2486 个测试文件）最实质的成熟度反差。

### 1.3 fde-v3 基线（对照锚）

- **升级目标**（实施方案 §1 / §7 / §13 / §20）：吸收 fde-v2 四件思想，五层架构 A Engagement OS（REUSE）/ B Ontology Registry / C Delivery Compiler / D Workflow Engine / E Quality；新增端点一律不进 `api_catalog`。
- **现状**（`AGENTS.md` §51）：105 张业务表、Alembic 32 rev head `d4e6f8a2c7b9`、296 路由、`api_catalog` ENTRIES 94、pytest 1838、vitest 752。
- **已有等价物（本轮核实，避免重复立项）**：
  - **行业模板体系已完整**：`workbench/models.py:74` `IndustryTemplate` + `IndustryTemplateVersion`（`RESTRICT`）、`workbench/seed.py:423` 3 行业 published v1、`solutions/service.py:859` 按行业名 casefold 精确匹配最新已发布版本、`research_form_service.py`、`dispatch/scoring.py:36` 业务大类随模板库落位、桌面端「行业模板」管理页。
  - **完成定义已有**：G1–G9 门禁清单项、T-S1 Skill 发布四闸（admin + 密码确认 + in_review + 测试报告或显式 waive）、`definition_service.validate_dag`。
  - **按需读已有（部分）**：`file_read` 带 offset + 16k 窗口、`help_fetch` 带 `next_offset` 分页（`mcp_gateway.py:44-46`、L195-207）；**但 `skill_read` 输入仅 `skill_id`、直接返回整份 `instructions_text`，无分页无索引**（`mcp_gateway.py:48`、L220-230）——项目记忆里登记的缺口属实。
  - **代号化 CI 已有**：`.github/workflows/ci.yml:83` `pseudonymization` job + `scripts/check-pseudonymization.sh --self-test`，扫**数据库**中的手机号 / 身份证 / 邮箱 / 真实企业名，含哨兵自测与「空库即失败」守卫。
  - **不可变与幂等已有**：`operation_events`、`workflow_definition_versions` 不可变、`api_actions` 同构 sha256 幂等键、`jobs/reconcile.py`；服务端 grep `replay_from|checksum|history.jsonl` **零命中**。
- **硬约束**：客户真实资料只留本地 `D:\test\FDE\…`；证据只存 `source_uri`+sha256；密钥不入 VCS；`origin` 永不 push；每调用实时鉴权；外副作用必审批 + 幂等键；4 个 CI job 全绿 + 单 commit revert。
- **演进方向**（`v3-backlog.md` P3）：多 Agent 自适应编排（DEFER）、Skill 运行反馈改进、业务规则推理、有限自动执行——明确「本轮仅立项不排期」。

---

## 2. 核心定位与主要能力

**定位**：面向 FDE 的「交付知识包 + 解析渲染引擎」。输入客户 Intention（行业、目标、AI 成熟度、是否受监管），引擎用**加权激活谓词**选出 program，按行业把 lens 叠加到 program，渲染成目标 IDE 的 steering/skills 文件，并在交付过程中通过 `fde_patch_intention` 回写发现、再次 `fde_resolve`，形成 README L42-62 自称的 **Loop Engineering**（共享状态变更 / 产物交接 / 重解析三机制）。

**主要能力**：① 12 个 MCP 工具（`fde_load_intention` / `fde_resolve` / `fde_render` / `fde_get_skill` / `fde_patch_intention` / `fde_aim_assess` / `fde_install_assets` 等）；② 受限 DSL 加权激活 + 确定性评分（`program.yaml` 的 `applicability[].when/weight`、`lens.yaml` 的 `activation.rules`）；③ Lens 只增不减叠加（`LENSES.md` L12：`addSteering` / `addSkills` / `addExitCriteria` / `overrideExitCriteria`）；④ 状态 append-only `history.jsonl` + sha256 checksum + replay-from-history（`core/src/state/index.ts` L255-345、CHANGELOG L28）；⑤ `.fde-manifest.json` 引用索引与 `readBefore` 契约（`documentation/REFERENCES.md` L23-45）；⑥ 13 平台适配器声明式注册（`adapters/manifest.json`）；⑦ 安全四件套（路径 / 密钥 / 可移植性 / 会话上限）。

**它明确不是**：不调用 AWS API、不联网、不托管服务（`README.md` L164、L260-269）；但**执行侧依赖 AWS MCP Server 部署 CDK/Bedrock**（L71），即「本地渲染 + 外部执行」分工。

---

## 3. 与 fde-v3 架构、功能边界、演进方向的匹配度

| 维度 | FDEP Kit | fde-v3 | 匹配判定 |
|---|---|---|---|
| 系统层 | 交付知识包 + IDE 侧 MCP Server | 交付管理系统 + DSH 外部编排 | **不同层，且 MCP 方向相反** |
| 事实源 | 磁盘 YAML/MD + `state/*.json` + `history.jsonl` | PG 关系表 + Alembic 单链 + 乐观锁 | **存储范式冲突** |
| 内容域 | AWS 专属（Bedrock/CDK/AgentCore/WA/AI-DLC） | 全行业、蔡工 SOP v2.4.6、境内 | **几乎不可复用** |
| 行业扩展 | Lens 与 Program 正交叠加，基础内容不变 | 行业模板整体选用（3 行业 published v1）+ 精确匹配 | **形态不同，思想可借鉴** |
| 激活方式 | 受限 DSL + 权重评分 + 重解析循环 | 人工选模板 + 行业名精确匹配 + G1–G9 固定门禁 | **V3 无加权激活层**（但 P3 才可能立项） |
| 完成定义 | program `exitCriteria`（artifact-exists 等） | 门禁清单项 + 证据指针 + 发布四闸 | **已有等价物，语义更严** |
| 知识消费 | `.fde-manifest.json` 索引 + `readBefore` + 按需单文件 | `file_read`/`help_fetch` 分页；`skill_read` 全文单发 | **索引层是真缺口，已有部分基础** |
| 扩展形态 | programs 纯 YAML+MD，加内容无需改核心代码 | `skill_definitions`/`skill_versions` + 发布四闸 + api_catalog 白名单 | **同构，但 V3 治理更严** |
| 测试纪律 | 10 条不变量声明，仓库 0 测试文件 / 0 CI | 4 CI job + 1838 pytest + 752 vitest | **V3 明显更成熟，反向对照** |
| 演进方向 | Program 自激活、AIM 评估、重解析循环 | P3 才讨论规则推理与自适应编排（DEFER） | **方向有交集但被明确推迟** |

---

## 4. 三分类判定（每条给仓库依据 + V3 证据锚点）

### 4.1 实质性帮助（3 项，全部是设计约定 / 契约清单，非可移植代码）

**① Lens 正交叠加模型 + 保守性契约 —— 最贴合 V3「扩展为全行业」的目标**
- 仓库依据：`LENSES.md` L12「Lenses never remove program content. They only add or override exit criteria」；`resolver/index.ts` L60-62 按 lens id 升序保证叠加顺序确定、L86-105 对 steering/skills/exitCriteria 去重排序、L118 检测跨 lens 叠加冲突；`INVARIANTS.md` P6「无匹配 lens 时有效内容 == 基础内容」；`lenses/manufacturing-lens/lens.yaml` 给出 `targetProgram` + `addSteering` 的最小声明形状。
- V3 锚点：行业模板是**整体选一**（`solutions/service.py:859` 按行业名 casefold 精确匹配、`IndustryTemplateVersion` 一个版本带五模块 + 调研表），没有「基础方法包不变、行业只叠加增量」这一层。工作台从制造业扩到全行业时，整体模板会随行业数线性膨胀。
- **判定为增量，但须去重**：V3 行业模板体系本身已完整，故这不是「缺行业能力」，而是**演进形态参考**；优先级取决于是否出现多行业并存需求，不能当成立即缺口。

**② 10 条可测不变量作为交付编译器契约清单**
- 仓库依据：`INVARIANTS.md` P1–P10（解析确定性、输入顺序无关、渲染幂等、平台无关、DSL 安全求值、Lens 组合保守性、patch 幂等、MCP 与直调等价、可移植扫描覆盖、未知标识符加载期拒绝）。
- V3 锚点：V3 有 `definition_service.validate_dag`（环检测 / `api_catalog` 白名单 / skill 显式版本 / 占位符传递）与 4 CI job，但**没有一份覆盖「模板解析 → 方案骨架 → 文档渲染 → Skill 注入」的形式化契约清单**；`docs/audit/agnes-harness-…md` §4.1 ② 也已判定「状态机对抗性验证」是 V3 已识别缺口。
- **限制必须写明**：该仓库 0 测试文件、0 CI（§1.2），P1–P10 是**声明**而非被执行的纪律。可借鉴的是「该测什么」，不是「它验证过了」。

**③ `.fde-manifest.json` 引用索引 + `readBefore` 契约（两级注入）**
- 仓库依据：`documentation/REFERENCES.md` L23-45：manifest 列出 `{ file, skillId, category, readBefore }`，Agent 在写某类产物前**必须**先读指定 reference；`fde_get_skill` 支持 `file=` 参数只取单个 reference；`fde_install_assets` 让大批量资产「不经模型上下文」直接落盘（`MCP-TOOLS.md` L290）。
- V3 锚点：`mcp_gateway.py:48` 的 `skill_read` 无 offset、直接返回整份 `instructions_text`（已核实）；项目记忆里 fde-v2 的「HOWTOUSE 300–600 tok 常驻 / README 按需读」两级注入本就是已登记的借鉴项，但 V3 尚未落到 Skill 消费面。
- **判定**：这是 V3 **已登记缺口**的一个成形参照设计，且 V3 已有 `help_fetch`/`file_read` 分页基础，兼容性最好。

### 4.2 有限帮助（5 项：已有等价物、当前为空实现、或改造成本 > 收益）

| 项 | FDEP Kit 依据 | V3 等价物 / 限制 | 判定 |
|---|---|---|---|
| 受限 DSL 有界求值 | `expression/index.ts` L2-5、L334-336、L493-497；`ADD-A-PROGRAM.md` L82 运算符白名单 | `validate_dag` 已有白名单与占位符校验；V3 **没有加权激活谓词层**，P3 才可能讨论规则推理 | 思想同构；V3 当前无承载对象，且引入表达式解析器会带来新的安全审阅面 |
| State checksum + append-only history + replay + merge-only | `state/index.ts` L255-345、`CHANGELOG.md` L28、L17「`current.yaml` 绝不从零重写」 | V3 有 `operation_events` / 不可变 `definition_versions` / `reconcile` / sha256 幂等键；**无 replay 重建**，且 PG 事务与文件 JSONL 形态不同 | 负向知识（merge-only、校验和对账）值得记；存储实现不移植 |
| Portability 扫描（禁客户名进可复用知识包） | `security/portability.ts` L1-15、`programs/.portability.yaml` | V3 `check-pseudonymization.sh` 扫**数据库客户明文**并带 `--self-test` 哨兵，角度互补 | 角度确有补充价值，但上游规则为 `disallowed: []` **空实现**、扫描器 opt-in、无 CI 强制；只能抄角度不能抄实现 |
| 会话上限 / 路径校验 / stderr JSON 审计 / 密钥扫描 | `MCP-TOOLS.md` L339-344、`security/path-validation.ts` L63-152、`secrets.ts` L1-15 | V3 已有 15min JWT 实时鉴权、`_project` claims+project_access、10MB/500k 截断、zip-bomb 防护、gitleaks CI | 已有且更严，无增量 |
| 6 个行业 lens 的分类框架与 9 个 program 的结构 | `LENSES.md` L18-108、`documentation/PROGRAMS.md` | V3 行业模板 3 行业 + SOP 16 节点 G1–G9 | 分类框架可作对照；**内容全部境外合规（PCI-DSS/HIPAA/GxP/SR 11-7）与 AWS 服务绑定，不可直接用** |

### 4.3 无直接帮助（明确排除）

- **AWS 技术内容**：27 份参考模式、CDK/Strands/Bedrock AgentCore/CloudWatch GenAI、AI-DLC 三阶段、AIM 六视角成熟度模型——与 V3 全行业境内交付无交集；且 V3 交付禁跑客户代码。
- **13 个 IDE 适配器**：V3 是 Electron 桌面端 + 自研页面，不向 Kiro/Claude/Cursor/Copilot 渲染 `.kiro/`、`.claude/`、`.github/instructions/` 配置。
- **MCP Server 运行时本体**：stdio 进程、`npx` 自动安装、Node 22、`bin/fdep-mcp.mjs` 工作区探测——V3 的 MCP 面是 `mcp_gateway` 被调侧，接入等于新增编排面。
- **写客户工作区 / 生成部署客户代码**：`fde_render`、`fde_init_workspace`、`fde_install_assets` 的文件落地链路与 V3 证据红线冲突。
- **`fde_aim_assess` 与 Loop Engineering 编排**：V3 已有售前录入卡 / 调研表 / G1–G9 固定门禁，且 P3 明确 DEFER 自适应编排；README L42-62 的「重解析循环」在 12 个工具里并无独立原语，只是 `patch_intention` + 再调 `resolve` 的文档层用法（`handlers.ts` L497、L790-795），不构成可移植引擎能力。

---

## 5. 可融合范围（用户点名五项的结论）

### 5.1 可借鉴的设计 / 模块 / 能力（收敛为 3 类）

| 类别 | 具体内容 | 性质 |
|---|---|---|
| 设计约定 | Lens 正交叠加（只增不减、确定性顺序、跨 lens 冲突检测、无匹配时保持基础内容）；受限 DSL 的「加载期拒绝未知标识符」「纯求值无 IO」；`readBefore` 引用契约；merge-only 状态纪律；10 条不变量的检查项 | 契约与不变量，非代码 |
| 内容分类框架 | Program = skills + steering + exitCriteria + 激活谓词；Lens = 行业增量层；Adapter = 平台声明式注册；pipelines 四阶段（intent→assess→transform→ai-native） | 结构分类，内容需全量替换 |
| 校验 / 文档形态 | `INVARIANTS.md` 单页列全部可测契约；6 份 JSON Schema 分对象定义；`schemas/intention.schema.json` 的 `additionalProperties: false` 收紧输入 | 文档与校验形态 |

### 5.2 可融合到 fde-v3 的具体范围（四个子域，均属 V3 自有表达的参考输入）

| V3 子域 | 可纳入的结论 | 边界 |
|---|---|---|
| **B 层 Ontology Registry / 行业模板子域** | Lens 叠加模型作为「行业模板从整体选一演进到基础包 + 行业增量」的参考形态 | 不引入 `lens.yaml` / `program.yaml` 文件体系；不替代 `IndustryTemplateVersion`；不改 `solutions/service.py:859` 精确匹配口径 |
| **C 层 Delivery Compiler / Skill 消费面** | 两级注入：索引层常驻、正文按需；`readBefore` 式「产出某类产物前必读某参考」契约 | 落在 `mcp_gateway.skill_read` / `extensions_service` 现有能力内；不改 `api_catalog` 白名单、不改鉴权链 |
| **D 层 Workflow Engine / 校验面** | P1–P10 中「确定性、幂等、输入顺序无关、未知标识符拒绝」作为 `validate_dag` 与文档渲染的契约检查项 | 不引入表达式解析器；不新增运行时；V3 已有测试基座承接 |
| **E 层 Quality / CI 面** | 「可复用交付资产内禁客户特定名称」这一扫描角度，补 V3 `check-pseudonymization.sh` 只扫数据库的盲区 | 上游为 `disallowed: []` 空规则，只抄角度；V3 已有 `--self-test` 哨兵与判级纪律，不需要照搬实现 |

**明确不纳入的 V3 域**：DSH / `ai_tool_loop` / `mcp_gateway` 鉴权与工具注册表、G1–G9 门禁铁三角与证据表、PG + Alembic 迁移链、`operation_events` / `api_actions` 幂等语义、桌面端 Electron 页面与产品名令牌、客户资料与密钥红线。

### 5.3 与现有实现的兼容性

- **数据层兼容性：高**——上述 3 类借鉴全部落在文档、契约与既有 Python 模块内，零新表、零迁移、零依赖、零种子改写，不触碰 `source_sha256` 溯源链。
- **运行时兼容性：高**——不新增 Node 进程、不新增 MCP server、不改 stdio/HTTP 传输面，与 DSH 外部编排职责不重叠。
- **治理兼容性：需注意**——V3 T-S1 对 Skill 发布要求「测试报告或显式 waive」，而 FDEP Kit `ADD-A-PROGRAM.md` L3 主张「No new tests required」、`INVARIANTS.md` 的测试声称又无测试文件支撑；**这是反向对照，不可把它的「无测试」惯例带进 V3**。
- **内容兼容性：低**——AWS 与境外合规内容须 100% 舍弃，仅保留结构分类。

### 5.4 需要适配或舍弃的部分

| 处理 | 内容 | 原因 |
|---|---|---|
| **必须舍弃** | AWS 服务内容与 27 参考模式、AI-DLC、AIM、13 适配器、stdio MCP Server 本体、客户工作区文件落地、客户代码生成与部署 | 场景/云/红线三重不匹配 |
| **必须适配** | Lens 叠加 → V3 行业模板版本化结构；受限 DSL → V3 已有 `validate_dag` 白名单（不新建解析器）；`readBefore` 索引 → V3 `skill_read` 分页 / 引用索引；10 不变量 → V3 pytest 契约检查项；portability 角度 → V3 代号化 CI 的资产侧扩展 | 载体从文件 YAML 换成 PG 关系表 + Python 服务 |
| **仅作负向知识** | 「0 测试文件却声称测试强制」「`disallowed: []` 空规则」「Node 版本文档 20+/22+ 不一致」「CHANGELOG 落后 HEAD 近 3 个月」 | 防止后续会话把声明当已验证能力 |

### 5.5 潜在冲突、风险与成本

| 风险 / 冲突 | 触发条件 | 影响 |
|---|---|---|
| 第二编排面 / 第二运行时 | 把 FDEP Kit 作为 MCP Server 挂到 V3 | 与 §19-7、§17 正面冲突；DSH 与 kit 双份「激活哪些能力」决策，事实源分裂 |
| 客户资料红线 | 沿用 `fde_render` 写 `state/`、intention `notes` 自由文本 | 客户明文可能落到工作区文件；V3 只存代号 + `source_uri`+sha256 |
| 交付禁跑客户代码 | 沿用「生成 CDK/agent/UI 并部署」链路 | 与 V3 交付边界相反 |
| 治理降级 | 沿用「加 program 无需测试」 | 削弱 T-S1 发布四闸 |
| 维护不可依赖 | 0 Release / 0 tag / 18 提交 / 3 作者 / 0 CI / 0 测试 | 若形成代码依赖，上游漂移即失效；虽 MIT-0 无署名义务、Fork+PR 开放，仍不足以承担架构角色 |
| 境内合规 | 内容默认 AWS 与境外合规框架，执行侧需 `aws-mcp` 外网端点 | 与 V3 境内运行、模型合规未拍板的边界冲突 |

---

## 6. 四种融合方式裁决

| 方式 | 可行性 | 冲突点 | 功能重叠 | 依赖约束 | 维护风险 | 改造成本 | 裁决 |
|---|---|---|---|---|---|---|---|
| **① 架构组成部分**（作为 V3 方法包引擎） | **不可行** | 第二运行时；PG vs 文件状态；MCP 方向相反；客户工作区落地；AWS 绑定 | 行业模板 / Skill 治理 / 完成定义 / CI 代号化四域全面重叠 | Node 22 + stdio 进程 + 客户工作区写权限 | 样例级维护（0 tag/0 Release/0 CI） | **最高**：9 program 内容全量重写 + 13 适配器替换为 Electron + 文件状态改 PG + 删除代码生成链路 | **否决** |
| **② 能力复用**（拷模块 / 包） | **不可行** | TS/Node22 vs Python 3.12；`core/src/mcp/handlers.ts` 46KB 与 12 工具绑定自身 catalog；MIT-0 虽无署名义务但代码无承载对象 | 与 `mcp_gateway` / `extensions_service` / `validate_dag` 重叠 | 4 依赖 + workspace `core` | 摘出模块随上游漂移即失效 | **高**：需 Python 重写或维护第二构建链 | **否决** |
| **③ 外部引用**（独立 MCP Server 对接） | **理论可行，当前不建议** | V3 已有 DSH 外部编排；kit 只监听 stdio 无远程能力；`fde_render` 写客户工作区；执行侧需 `aws-mcp` 外网 | 与 DSH 的能力激活职责重叠 | 独立 Node 进程 + 生命周期 + 凭据/客户资料边界重验 | 两侧各自演进，无 semver/Release 承诺 | **中高**：一个独立进程 + 适配层 + 安全验收 | **暂缓** |
| **④ 参考设计**（只抄约定、契约清单、分类框架） | **可行，推荐** | 无（不改运行时、数据模型、依赖） | 无新增重叠 | 零新增依赖 | 零（结论落在 V3 自有文档与 pytest） | **低**（文档 + 契约检查项） | **采纳** |

方式 ④ 与 V3 既有方法论一致：实施方案 §1「不是引入 fde-v2，而是吸收四件经过验证的思想」、§19 七项不照搬、§17 不并行开第二实施线。相对 agnes-harness，FDEP Kit 在方式 ③ 上的技术门槛更低（纯 stdio、零网络、4 依赖、MIT-0、开放 PR），但**职责重叠与红线冲突不变**，故仍不推荐。

---

## 7. 对升级效率、稳定性、可维护性、扩展性、兼容性的实际收益

| 维度 | 采纳「局部借鉴」（方式 ④） | 若「整体融合 / 引入运行时」（方式 ①②③） |
|---|---|---|
| 升级效率 | **低但为正**：升级已收口，只改善 P2 收尾与下一轮行业扩展设计；不回溯已完成的 26 任务 | **负**：需重写栈或双栈并存，违反 §17；且样例级成熟度需先补测试与 CI |
| 稳定性 | **中**：确定性/幂等/顺序无关契约 + 引用索引能补 V3 已登记的 `skill_read` 与状态机验证缺口；不引入新失败面 | **负**：文件状态 checksum 与 PG 事务双事实源；0 测试文件意味着无回归保障 |
| 可维护性 | **中**：契约清单与负向知识降低后续会话误判；V3 测试基座现成 | **负**：0 Release / 0 tag / 3 作者 / 0 CI；AWS 内容需长期与蔡工 SOP 双份维护 |
| 扩展性 | **中高（唯一明显收益）**：Lens 叠加形态直接服务「从制造业扩到全行业」，避免模板线性膨胀 | **似高实负**：9 program + 6 lens 全 AWS 绑定，扩展每行业都要先做内容替换 |
| 兼容性 | **零成本**：纯文档 / 纯契约，不动表、路由、种子、依赖 | **负**：Node 22 / stdio / 客户工作区写 / `aws-mcp` 外网端点，与 V3 栈与境内边界冲突 |

---

## 8. 优先级排序与纳入范围（可据此决策）

| 优先 | 纳入结论 | 判断依据 | 分类 |
|---|---|---|---|
| **P0-1** | Lens 正交叠加模型纳入 V3 行业模板演进的参考形态 | 唯一贴合「扩展为全行业」目标的结构性设计；V3 行业模板已有但为整体选一；§4.1 ① 双侧证据 | 实质性 |
| **P0-2** | P1–P10 中「确定性 / 幂等 / 输入顺序无关 / 未知标识符拒绝」纳入 V3 交付编译器契约清单 | V3 已有 `validate_dag` 与 pytest 基座，但无形式化契约清单；与 AGNES 评估「状态机对抗性验证」结论同向；须标注上游未验证 | 实质性 |
| **P1-3** | 两级注入与 `readBefore` 契约纳入 Skill 消费面参考 | V3 `skill_read` 全文单发无分页已核实为真缺口；`file_read`/`help_fetch` 已有分页基础，兼容性最好 | 实质性 |
| **P2-4** | 「可复用交付资产内禁客户特定名称」角度纳入代号化门禁的补充视角 | V3 现扫数据库明文，资产侧为盲区；但上游 `disallowed: []` 空规则，优先级下调 | 有限 |
| **P2-5** | 登记为外部对照样本，记录 0 测试 / 0 CI / 空规则等负向知识 | 防止后续会话把声明当能力、重复立项 | 有限 |

**不建议纳入（范围红线）**：任何 FDEP Kit 代码 / 包 / 依赖声明、stdio MCP Server 进程、13 适配器、9 program 与 6 lens 的 AWS 内容、AIM 评估、文件状态与 `history.jsonl` 实现、客户工作区文件落地、`package.json` 或 `pyproject.toml` 变更、任何 Alembic 迁移、种子或 SOP 文本改写、把该仓库列为 V3 架构组件。

**重评触发条件（四者未满足前结论不变）**：① 上游出现正式 Release / tag 与 semver 兼容承诺，并补上测试与 CI；② 出现非 AWS 绑定、可替换内容的通用交付方法包引擎；③ V3 P3「业务规则推理 / 自适应编排」正式立项排期，需要加权激活层；④ 多行业并存导致现有整体模板维护成本实测失控。

---

## 9. 明确融合结论

1. **是否采纳该仓库：不采纳为项目依赖或组件；采纳为「局部借鉴」的参考样本。** 采纳范围严格限定于 §8 的 5 项结论，其中实质性帮助 3 项、有限帮助 2 项，全部是设计约定与契约清单，不含任何可移植代码。
2. **适合局部借鉴还是整体融合：只适合局部借鉴。** 整体融合（方式 ①②）与否决项在层、栈、云绑定、MCP 方向、交付红线、成熟度六项同时不成立；外部引用（方式 ③）技术上比 agnes-harness 更容易，但职责重叠与红线冲突未解，当前暂缓。
3. **可融合范围**：B 层行业模板子域（叠加形态）、C 层 Skill 消费面（两级注入）、D 层校验面（契约检查项）、E 层 CI 面（资产侧可移植角度）；四域均只输入结论，不引入文件体系或运行时。
4. **兼容性**：局部借鉴为零代码 / 零迁移 / 零依赖 / 零种子改写，与 V3 现有栈、鉴权链、红线完全兼容；整体引入则六项冲突。
5. **必须舍弃**：AWS 与境外合规内容、IDE 适配器、stdio MCP Server、客户工作区文件落地、客户代码生成与部署、以及「加内容无需测试」的治理惯例。
6. **对「fde-v2→fde-v3 升级」动作本身：无直接帮助**（时间线在后 + 全仓零引用）。对 V3 后续 P2 收尾、全行业扩展设计与下一轮重构：有 §4.1 三项参考价值。
7. 本轮未实施任何工程改动；§8 全部为 PROPOSED，需按 V3 既有 goal 循环逐任务立项，不并行开第二实施线。

---

## 10. 无法确认的信息与所依据假设（不把推测当事实）

| # | 项 | 现状 | 本报告采用的假设 | 若假设不成立的影响 |
|---|---|---|---|---|
| 1 | 本地副本是否等于上游当前 HEAD、GitHub 是否有 Release / stars / issues | 只读本地 git（HEAD `470fa2b`，remote 指向 aws-samples），**本轮未联网核验 GitHub API**；0 tag 为本地事实 | 假设本地副本代表上游公开内容，且上游无正式 Release | 若上游已有 Release 与 CI，§1.2 成熟度档应上调，但层/栈/红线冲突不变，整体融合结论不翻转 |
| 2 | V3 行业模板是否已具备「叠加」能力 | 定向 grep `workbench/`、`solutions/service.py`、`dispatch/scoring.py` 与文档；**未逐页走查 148 个 tsx 与全部模板服务** | 假设 V3 无正交叠加层，模板为整体选一 | 若已有叠加实现，§4.1 ① 从「实质性」降为「有限帮助」，P0-1 撤销 |
| 3 | V3 是否已有 `.fde-manifest` 式引用索引层 | 已核实 `skill_read` 无分页（`mcp_gateway.py:48`、L220-230），并见 `file_read`/`help_fetch` 分页；**未逐项排除 `api_catalog` / `dsh_market` 中可能存在别的索引** | 假设不存在按产物类别的 `readBefore` 索引 | 若已有，§4.1 ③ 降为「有限帮助」 |
| 4 | `INVARIANTS.md`「由测试套件强制」与仓库 0 测试文件的矛盾 | `core/test/.gitkeep` 为唯一文件、0 个 `.github` 文件；`CONTRIBUTING.md` L59 自注「if tests exist」 | 假设测试未随发布打包，P1–P10 为声明性契约 | 若测试存在于仓库外并真实运行，§1.2「工程验证低」应上调，但借鉴内容仍是清单本身 |
| 5 | `portability` 扫描是否真正生效 | `.portability.yaml` 为 `disallowed: []`，扫描器设计为 opt-in | 假设当前无实际拦截规则 | 若上游另有规则来源，§4.2 该项可从「有限」上调，但仍不改变整体裁决 |
| 6 | Node 版本口径 | README L70 与 `engines` 为 22+，`QUICKSTART.md` L13 为 20+ | 按 `package.json engines >=22` 取 22 | 仅影响「外部引用」方式的部署成本估算，不影响裁决 |
| 7 | 逐行审计覆盖度 | 精读 README、CHANGELOG、CONTRIBUTING、INVARIANTS、MCP-TOOLS、PROGRAMS、LENSES、ADD-A-PROGRAM、QUICKSTART、REFERENCES、USER-GUIDE 关键段 + 定向读 `expression` / `resolver` / `state` / `security` / `mcp/tools.ts` / `bin` 与 program、lens、schema、pipeline 样例；**未逐行审 34 个 `core/src` 文件与 157 个 `programs/` 内容文件** | 模块级判定基于公开契约、目录结构与定向源码，不基于全量代码审阅 | 不影响「不引入代码」的结论；若未来要摘模块需补一轮行号级审计 |
| 8 | V3 的 DSH 与 FDEP Kit 执行侧 `aws-mcp` 是否有关联 | 两者都经 MCP，但实施方案 §2 限制 5 明确 DSH 为外部黑盒；无任何文档建立关联 | 假设二者不同源，且 V3 不自建 Agent 运行时、不引入 AWS 执行链 | 若 V3 计划接入 AWS 执行链，方式 ③ 需重评，境内合规成本上升 |

---

## 11. 证据来源清单

**FDEP Kit 侧**（本地只读副本 `D:\test\FDE\knowledge\sample-fdep-mcp-server`，HEAD `470fa2b`）：
`README.md`、`CHANGELOG.md`、`CONTRIBUTING.md`、`LICENSE`、`package.json`、`tsconfig.json`、`bin/fdep-mcp.mjs`、`documentation/INVARIANTS.md`、`documentation/MCP-TOOLS.md`、`documentation/PROGRAMS.md`、`documentation/LENSES.md`、`documentation/ADD-A-PROGRAM.md`、`documentation/QUICKSTART.md`、`documentation/REFERENCES.md`、`documentation/USER-GUIDE.md`（关键段）、`core/src/expression/index.ts`、`core/src/resolver/index.ts`、`core/src/state/index.ts`、`core/src/security/portability.ts`、`core/src/security/secrets.ts`、`core/src/security/path-validation.ts`、`core/src/mcp/tools.ts`、`core/src/mcp/handlers.ts`（定向）、`schemas/intention.schema.json`、`adapters/manifest.json`、`programs/.portability.yaml`、`programs/agentpath/program.yaml`、`lenses/manufacturing-lens/lens.yaml`、`pipelines/default.yaml`、全树清单与 `git log` / `git tag` / `git remote -v`。

**fde-v3 侧**：`AGENTS.md`（红线与现状）、`docs/architecture/蔡工FDE_Workbench_fde-v2架构融合审计与V3升级实施方案.md`（§1/§2/§3/§7/§13/§17/§19/§20）、`docs/implementation/v3-backlog.md`（P3 段）、`docs/implementation/v3-迁移进度对照-fde-v2建议-2026-11-04.md`、`docs/audit/agnes-harness-融合评估-2026-11-05.md`（口径）、`server/src/fde_api/workbench/models.py`、`workbench/seed.py`、`solutions/service.py`、`dispatch/scoring.py`、`control/mcp_gateway.py`、`control/extensions_service.py`、`control/api_catalog.py`、`server/seeds/gates.json`、`scripts/check-pseudonymization.sh`、`.github/workflows/ci.yml`、`desktop/src/renderer/src/` 定向 grep。

---

### 附：本轮产出

新增本报告 1 份（`docs/audit/sample-fdep-mcp-server-融合评估-2026-11-05.md`）；纯文档轮，未改动任何业务代码、台账、迁移、种子或依赖。
