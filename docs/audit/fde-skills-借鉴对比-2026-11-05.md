# fde-skills 结构化对比与借鉴清单（2026-11-05）

> **性质**：只读对比轮（零代码、零迁移、零依赖）；全部结论基于本地一手实读，逐项标 `[已核实]`。
> **证据口径**：fde-skills 本地副本 `D:\test\FDE\knowledge\fde-skills`，`origin = https://github.com/bingyue/fde-skills.git`，HEAD `b8c6876`（17M，523 份 md）；**本轮未联网核对远端是否有更新，结论以本地 HEAD 为准**。我方代码与技能目录均为本机实读。
> **导航**：§0 对象界定 → §1 六维对比总表 → §2 目录对照 → §3 内容规范对照 → §4 功能/复用对照 → §5 扩展约束对照 → §6 可借鉴项（按优先级） → §7 不宜照搬 → §8 与总览的防重复立项 → §9 待确认。

---

## 0. 对象界定（本轮的三组对比对象）

用户所说「当前技能项目 / 当前工作区中其他已有 skills 项目」在本机可对应多个路径，为避免指代误判，**三组全部纳入并明确边界**：

| 组 | 实际路径 | 内容 | 证据 |
|---|---|---|---|
| **A · 当前技能项目**（工作区内、与交付系统同仓） | `D:\test\fde-workbench\.agents\skills\` | 4 个 `SKILL.md`：`fde-bridge-capture`(54 行) / `fde-delivery-flow`(61) / `fde-gui-regression`(75) / `fde-package-verify`(66) | 4 份全文已读 |
| **A' · 同项目的服务端技能资产层** | `server/src/fde_api/control/{builtin_skills.py, extensions_service.py, mcp_gateway.py, models.py}`、`workflows/{definition_service.py, executor.py}`、迁移 `c1e5f9a3d7b2` | 种子清单（11 个基础条目 + LCSC/方案类变体，`SKILLS` 后续被 6 次扩展）、治理四态、版本行不可变、发布四闸、pinned 版本消费、`skill_read` 工具面 | `control/models.py:207/234`、`extensions_service.py:346-385`、`definition_service.py:252-261` |
| **B · 其他已有 skills 项目**（本机可访问、非本工作区） | `C:\Users\P1\.workbuddy\skills\{fde, fde-engagement, openfde, storage-analyzer-windows}` + 同目录 40+ 通用技能包（n8n*/comfyui* 等） | `fde`：132 行主文件 + **45 个 `references/`** 路由式渐进披露；`fde-engagement`：58 行 + 4 `references/`，双轨编排；`openfde`：58 行 stub 指向 `FDE.md`；`storage-analyzer-windows`：SKILL.md + `scripts/` + `assets/` + `references/` | 目录与头部已读 |
| **B' · 当前 Expert 插件技能包** | `…\plugins\marketplaces\experts\plugins\senior-developer\skills\{browser-use, frontend-dev, fullstack-dev}` | front matter 带 `version`/`license`/`metadata.category`/`description_zh`；`references/` 分主题；`frontend-dev` 另带字体资产与 `scripts/` | `frontend-dev/SKILL.md:1-30` 已读 |
| **C · 参考项目 fde-skills** | `D:\test\FDE\knowledge\fde-skills` | AGPL-3.0-only、v1.0.0、中文默认；**60 个 canonical Skill / 12 类**、5 行业 Pack、4 Agent 适配器、5 案例、Python CLI + 3 份 JSON Schema + `skills.json` Registry + CI；`legacy/` 为 31 技能旧版归档 | `README.md`、`pyproject.toml`、`INDEX.md`、`CHANGELOG.md` 已读 |

> A 与 A' 必须一起看：A 是「给 AI 看的操作 runbook」，A' 是「产品内可治理、可版本化、可被工作流消费的技能资产」。这是本工作区与所有其他技能库最本质的结构差异。

---

## 1. 六维对比总表

| 维度 | A / A' 当前技能项目 | B / B' 其他已有 skills | C fde-skills | 关键差异结论 |
|---|---|---|---|---|
| **目标定位** | 保证**本仓库**的交付动作不出错：采集桥、PR 流、GUI 回归、便携版打包；A' 面向产品内 AI 技能治理 | 面向「人＋AI 怎么干活」：FDE 客户记忆双轨、CLI 编排、前端/全栈开发方法 | 面向 **FDE 方法本身**：把企业诊断→方案→评测→交付的 8 阶段沉淀为可复用能力库（`README.md`「核心原则」） | C 是**方法论资产库**；A 是**本仓操作纪律**；B 是**工具/流程编排**。三者不重叠，C 补的是「方法论条目化」这一层 |
| **目录组织** | `.agents/skills/<name>/SKILL.md`，单文件、无 `assets/` `examples/`；A' 权威在 DB（表 + Alembic） | 主 `SKILL.md` + `references/*.md`（`fde` 45 个）按需展开；部分带 `scripts/` `assets/` `_meta.json` | `skills/<12类>/<name>/{SKILL.md, assets/output-template.md, examples/example.yaml}` 三件套 + `schemas/ industries/ adapters/ examples/ src/ scripts/ tests/ docs/ legacy/` | C 的**目录深度与配套文件是契约的一部分**（`library.py::validate` 强制 `skills/<category>/<name>/` 四层）；A/B 只有主文件，靠正文内链接 |
| **内容规范** | front matter 仅 `name` + `description`（英文长描述内含触发词中英混排）；正文＝命令、排障表、红线、坑位，密度高 | 通用 Agent Skills 规范：`name`/`description`（+ 部分 `version`/`license`/`metadata`）；正文路由到 `references/` | **20 个必填字段的结构化契约**：`inputs/outputs/workflow(id,action,evidence)/constraints/quality_criteria/tools/dependencies/examples/evaluation/checks/severity/regression_cases/license/status`，`additionalProperties: false`（`schemas/skill.schema.json`） | C 是**机器可校验契约**，A/B 是**人读文档**；但 C 的 60 份 SKILL.md 行数 **100–104、中位数 101**，正文基本是 front matter 的复述，信息密度低于 A 的 54–75 行 |
| **功能范围** | 4 个 runbook；A' 有内置种子清单（11 基础条目 + LCSC/方案类变体）+ 治理四态 + 发布/回滚/弃用 + 效果统计 + pinned 版本执行 | 单技能能力包：`fde` 全周期客户工作、`openfde` 账本、`storage-analyzer-windows` 只读扫描 + HTML 报告 | 60 技能覆盖 12 类 FDE 方法、5 行业 overlay、4 宿主导出、5 端到端合成案例、离线评测基线 | 数量不在同一量级，但 C 的 60 个是**同模板批量生成**；A' 的 11 个是**具体工作台操作指令**，语义不可互换 |
| **复用方式** | A：宿主 IDE 自动发现 `.agents/skills/`；A'：MCP `skill_read`（`control/mcp_gateway.py:48`）+ 工作流 `skill.ref = <key>@<version>` 显式 pinned（`definition_service.py:252`） | WorkBuddy 用户级技能自动注入 + `references/` 渐进披露；`openfde` 靠 `FDE.md` 生成式指引 | `fde list/search/show/validate/registry build/export <agent>`；导出到 `.claude/skills` 等并附 `references/fde-contract.yaml` + LICENSE/NOTICE；导出清单 preflight、`--force` 只覆盖自己生成的文件（`src/fde_skills/adapters.py:69-115`） | **A' 的 DB 权威 + pinned 版本 + 发布闸强于 C 的文件权威 + `status` 枚举**；C 强在「一份源编译到多宿主」与导出安全语义 |
| **扩展约束** | 改技能走产品内治理闸（admin + 密码确认 + `in_review` + 测试报告或 waive，`extensions_service.py:346-385`）；改 runbook 走 4 CI job + PR 流；客户真实资料/密钥禁止入库 | 用户级技能无发布闸（`agent_created: true`）；靠 SKILL.md 内的红线文字约束 | `fde validate` 强制 schema/目录/name-category 一致/无 TODO 与 draft/workflow id 唯一/示例必填输入与输出字段一致/回归用例存在/依赖环/重复描述与正文/链接与锚点/路径穿越；CI `git diff --exit-code -- skills.json INDEX.md` 锁生成物一致性（`library.py:207-360`、`.github/workflows/ci.yml`）；贡献须 `AGPL-3.0-only` 且第三方材料做来源与许可审查 | **双方约束方向不同**：A' 强在「谁有权发布」，C 强在「内容是否自洽」。互补而非替代 |

---

## 2. 目录组织对照（具体到文件）

| 结构位 | A 当前 | B 其他 | C fde-skills | 评价 |
|---|---|---|---|---|
| 技能主文件 | `.agents/skills/<name>/SKILL.md`（4 份，单文件） | `<name>/SKILL.md`（+ `_meta.json`） | `skills/<category>/<name>/SKILL.md`（60 份，四层路径被校验器强制） | C 的 category 层是分类法落地点；A 只有 4 个，用不上 |
| 配套资产 | 无（命令与路径写在正文） | `references/`（fde 45 个）、`scripts/`、`assets/` | `assets/output-template.md` + `examples/example.yaml` **每个技能必备** | 三件套是 C 最值得抄的结构，但须缩为我方可填的最小集 |
| 机器索引 | DB `skill_definitions` / `skill_versions`（含 `content_sha256`） | 无（宿主扫描目录） | `skills.json`（`path` + `sha256` + 10 个元数据字段）＋ `INDEX.md` 双生成物 | 我方已有更强索引（DB + 版本 + 状态），**不该再立文件权威** |
| 规范与校验 | `AGENTS.md` 文字约定 + pytest 1900+ | 无仓库级校验 | `schemas/*.json` ×3、`src/fde_skills/library.py::validate`、`scripts/validate.py`、CI 3 Python 版本矩阵 | 校验器纪律值得抄，实现须落在 pytest |
| 历史资产 | git 历史 + `.workbuddy/memory/` | 无 | `legacy/`（11 类 + `_catalog`，31 技能旧版，byte-preserved 归档） | 归档纪律可参考；`NOTICE.md` 自述部分历史导入**无再分发许可**，不可当依赖 |
| 行业/示例层 | 无 | 无 | `industries/<5>/{pack.yaml, case.md, README.md}`、`examples/<5 案例>/{artifacts/*.md (8 阶段), case.yaml, eval.jsonl}` | 与我方「全行业扩展」方向有关，但合成案例撞客户资料红线 |

---

## 3. 内容规范对照（字段级）

| 规范项 | A / A' | B / B' | C fde-skills | 差异与可迁移性 |
|---|---|---|---|---|
| front matter 必填 | `name`, `description` | `name`, `description`；`frontend-dev` 另有 `version: 1.1.0` / `license: MIT` / `metadata.category` | 20 字段全必填，`additionalProperties: false`，`name` 正则 `^[a-z0-9]+(?:-[a-z0-9]+)*$`，`version` 语义化，`category` 12 值枚举 | 抄**字段语义**，不抄「20 全必填」——A 的 runbook 填不满 inputs/outputs/evaluation |
| 路由排除 | `description` 里堆触发词（中英混排） | `fde` 用 `### Routing` 段落；`frontend-dev` 有显式 `DO NOT TRIGGER` | `when_to_use` + **`when_not_to_use`**（各 ≥1、去重） | 「显式排除项」值得抄进 Skill 编写口径，降低近重复技能 |
| 步骤与证据 | 正文表格写「症状→处置」，无结构化 evidence | 正文叙述式 | `workflow: [{id, action, evidence}]`，每步必带证据 | 与我方 #29「验证/验收合同」、#22「反证判据」同向，但要挂 DB，不做 YAML 权威 |
| 验收 | `fde-package-verify` 两道字节验证；A' 发布闸要 `test_report` 或 `waive_reason` | 无 | `quality_criteria` + `evaluation.checks{id,criterion,severity}` + `regression_cases` + `negative_case` | **「反例」是 C 最有价值的单点**：把「失败时怎么办」变成可校验材料，可填进 `SkillVersion.test_report_json` |
| 输出契约 | 正文写产物路径/命名 | 无 | `outputs[].required_fields` 与 `example.yaml.expected.required_fields` **必须集合相等**（`library.py:271-273`） | 这条一致性校验可直接译为我方 pytest |
| 状态成熟度 | `draft→in_review→published→deprecated`（带审核人、密码确认、测试报告/waive、发布事件留痕） | 无 | `draft / ready / field-validated`；规范明写 **`ready` 仅代表通过结构校验，不代表现场验证** | 我方治理态更强，**不替换**；只补「published ≠ 现场已验证」口径 |
| 篇幅/密度 | 54–75 行，含具体命令、端口、编码坑、事故对照 | `fde` 132 行 + 45 个按需 references | 100–104 行×60，模板化、正文复述 front matter | **不宜照搬规模化产出**：换成模板会稀释 A 的高密度操作信息 |

---

## 4. 功能范围与复用方式对照

- **A' 已有而 C 没有**：治理四态与发布四闸（`extensions_service.py:346`）、版本行 `content_sha256` 不可变、回滚需复核旧版本测试报告（`:387-418`）、`skill_used_chat`/`skill_used_workflow` 双消费面计数、工作流 `skill.ref` 必须 `<key>@<version>` 且只认 published（白名单 `published_skill_refs`）、执行器用 pinned 版本 instructions 作 system_prompt 的确定性调用（`executor.py:882`）。**这些是我方的优势，借鉴时不能被覆盖。**
- **C 有而 A' 没有**：`fde skill create` 脚手架、`fde validate` 全库自洽校验、`skills.json` 机器索引 + 生成物 CI 锁、一源四宿主导出、`--force` 仅覆盖自己生成文件、行业 Pack 的「叠加不覆盖」组合、合成正/反例与输出模板三件套、`SOURCES.md`/`NOTICE.md` 的来源与许可审查纪律。
- **B 提供第三条路**：`references/` 渐进披露（`fde` 45 个文件、主文件仅 132 行）与 `FDE.md` 生成式指引（`openfde` 58 行 stub）。这正好补上我方 `skill_read` **全文单发、无分页/无按需加载**这一已核实缺口（总览 #8 / #32），且与 C 的 `references/fde-contract.yaml` 是同构思路——**两个项目指向同一个落点，应合并为一个工程项**。

---

## 5. 扩展约束对照

| 约束类型 | A / A' | B | C |
|---|---|---|---|
| 谁能新增/发布 | 公共技能：admin + 密码确认 + in_review + test_report/waive；个人技能自发布 | 用户级自由新增，无闸 | 任何人可提 PR，`status: draft` 不得进索引与导出；评审 7 条标准（`CONTRIBUTING.md`） |
| 内容自洽 | 靠人工 + pytest | 靠人工 | 12 类自动校验（schema/目录/重复/依赖环/链接/锚点/示例字段/输出后缀/回归用例/路径穿越/生成物 diff） |
| 依赖与组合 | `required_capabilities` 白名单 + `api_catalog` 白名单；`skill.ref` pinned | 由正文路由 | `dependencies` 无环校验；行业 Pack `extends` 只能引用已存在核心技能，显式选择集外技能会被拒（`industry-packs.md`） |
| 数据与许可 | 客户真实资料永不进 git/DB、密钥只写变量名、证据只存指针 + sha256 | 技能内红线文字 | AGPL-3.0-only、贡献即授权、第三方须保留 NOTICE 并登记 `SOURCES.md`；合成数据须标 `kind: synthetic` |
| 平台边界 | Windows 宿主 + Docker + 4 CI job；技能不得绕过权限 | WorkBuddy 宿主 | 4 个 IDE 目录；导出不发明工具权限、不削弱约束（`adapters.py:31-67`） |

---

## 6. fde-skills 可借鉴项（按优先级）

> 每条含：借鉴来源（具体文件）｜具体内容｜应用建议（落到我方具体位置）｜优先级｜适用条件｜需要调整之处。

### P0 · 先行（文档/口径级，零代码零迁移）

**B1 · 「published ≠ 现场已验证」成熟度口径 + 来源许可登记纪律**
- 来源：`docs/skill-spec/README.md`「Versioning and maturity」、`README.md`「Skill 的 `ready` 状态…不代表经过客户现场验证」、`CONTRIBUTING.md`「Contribution license」、`SOURCES.md` / `NOTICE.md`。
- 内容：把「内容已写完并通过结构校验」与「经过客户现场验证」显式分开；引用第三方技能材料前记录确切版本、许可与出处。
- 应用建议：写进 `AGENTS.md` 技能约定段与技能中心页面的状态说明；外部技能导入登记沿用 `SOURCES.md` 的字段形态，落 `docs/audit/`。
- 优先级：**P0（≈0.5 人日，纯文档）**。适用条件：无。
- 需调整：我方 `published` 是**治理通过**（比 `ready` 强得多，带审核人与测试报告），文案必须写「治理通过 ≠ 现场验证」，不能把状态值改名；**AGPL-3.0-only 授权条款不引入**，只抄登记纪律。

**B2 · 结构化契约的最小字段集（路由排除 + 步骤证据 + 验收 + 反例）**
- 来源：`schemas/skill.schema.json` 的 `when_not_to_use` / `workflow[].evidence` / `quality_criteria` / `evaluation.checks.severity` / `regression_cases`；`templates/skill/SKILL.md`。
- 内容：只取 5 组语义，**不取 20 字段全必填**：`when_not_to_use`、`workflow{id,action,evidence}`、`quality_criteria`、`evaluation{checks,regression_cases}`、`outputs[].required_fields`。
- 应用建议：作为 `SkillVersion.manifest_json` 的可选扩展键 + `.agents/skills/` 新技能的最小 front matter 建议；无需迁移（`manifest_json` 本来就是 JSON 列）。
- 优先级：**P0（口径先行，实现并入 P1）**。适用条件：新增或大改技能时启用，存量 4 个 runbook 不回填。
- 需调整：字段值允许中文；`severity` 三档映射我方既有风险闸；禁止把 `instructions_text` 拆成 YAML 双权威。

### P1 · 第二批（1–2 月窗口，复用既有 pytest 与 CI）

**B3 · 校验器纪律（12 类自洽检查）落 pytest**
- 来源：`src/fde_skills/library.py::validate`（`:207-360`）、`link_errors`（`:179-205`）、`safe_path`（`:64-84`）、`.github/workflows/ci.yml`。
- 内容：schema 自检、目录深度、`name`/`category` 与目录一致、draft/TODO 拒发布、workflow id 唯一、示例必填输入与输出字段一致、回归用例文件存在、输出后缀与声明类型匹配、依赖环、重复描述/正文、本地链接与锚点、越界路径、生成物 `git diff --exit-code`。
- 应用建议：`server/tests/test_skill_contract.py`（新），对 `.agents/skills/` 与 `builtin_skills.py` 种子清单做静态校验；挂现有 `server-tests` job，不新增 CI job。
- 优先级：**P1（≈1–2 人日）**。适用条件：技能数量增长到需要机械校验时（当前 4 + 11 已接近）。
- 需调整：**不引入** `PyYAML`/`jsonschema` 新运行时依赖（用已有 Python 标准库 + pytest）；「重复正文检测」要放宽为我方 4 个 runbook 的结构相似度阈值，避免误伤；生成物一致性改为「种子清单 ↔ DB 行」断言，而不是锁仓库文件。

**B4 · 正例 + 反例（negative_case）作为发布闸材料**
- 来源：`schemas/example.schema.json`（`kind: synthetic|anonymized|public`、`expected.artifact/decision/required_fields`、`checks`、`negative_case{input,expected}`）、`skills/delivery/delivery-handover/examples/example.yaml`、`assets/output-template.md`。
- 内容：每个技能附「一个正例 + 一个真实失败输入 + 有界恢复」；`required_fields` 与输出声明一致；反例不得被平均成分数。
- 应用建议：填进 `SkillVersion.test_report_json`（发布四闸已要求「测试报告或显式 waive」，`extensions_service.py:370-375`），把 `waive` 的比例压下来；与总览 **#22 三锚+四反例 / #29 验证合同**合并实施，不另立项。
- 优先级：**P1（≈1 人日 + 写材料）**。适用条件：公共技能发布；个人技能不强求。
- 需调整：所有示例必须标 `synthetic`，**禁止客户真实资料**（我方红线）；`negative_case` 描述的是「恢复动作」而非「打分阈值」，不要引入 fde-gym 的 uplift 口径造成二次立项。

**B5 · 分类法纪律与「先搜再建」防近重复**
- 来源：`INDEX.md`（12 类 60 技能索引）、`CONTRIBUTING.md` 开头「Search existing Skills before adding one. Prefer improving an existing workflow or adding industry context to creating a near-duplicate」、`skills.json` 的 `category/tags/status/dependencies/license/path/sha256`。
- 内容：新增技能前先查索引；优先改现有技能或加行业上下文，不建近重复条目；索引至少含名称、分类、标签、状态、依赖、许可、路径、指纹。
- 应用建议：技能中心列表补 `category/tags` 两列（DB 增列需迁移，可先放 `manifest_json` 免迁移）；`AGENTS.md` 加一条「新增技能先查中心」。
- 优先级：**P1（低代码）**。适用条件：技能数 > 20 或出现跨行业模板时。
- 需调整：**不照搬 12 类 FDE 方法分类**（我方是工作台操作/runbook 域），自建 4–6 类；`skills.json` 文件索引不建，DB 即索引。

### P2 · 条件触发

**B6 · 行业 Pack 的「叠加不覆盖」组合语义**
- 来源：`docs/skill-spec/industry-packs.md`、`schemas/industry.schema.json`、`industries/foreign-trade/pack.yaml`、`src/fde_skills/adapters.py::compose`。
- 内容：core AND industry 是**两份合同的并列**，不是字典覆盖；规则冲突记录待审并沿用更窄的现有授权；行业指标不能掩盖单个 critical 失败；Pack 不发消息、不执行工作流、不嵌凭据。
- 应用建议：与总览 **#15「Lens 正交叠加」**合并，作为将来全行业模板的组合规则；落在方案/指引模板层，不进技能执行器。
- 优先级：**P2**。适用条件：确有多行业模板并存且维护成本上升。
- 需调整：叠加必须带**项目级 scope 与 RBAC 边界**（C 是单机单用户，无此概念）；冲突处置要接我方人工审批而非「记录待审」即放行。

**B7 · 一源多宿主导出的安全语义**
- 来源：`src/fde_skills/adapters.py::export`（`:69-115`，preflight 全部写入、`.fde/exports/<agent>.json` 清单、`--force` 只许覆盖本适配器曾生成的文件、导出附 LICENSE/NOTICE 与 `references/fde-contract.yaml`）、`adapters/*/adapter.json`。
- 内容：导出前整批预检；记录生成清单；绝不覆盖非己方文件；许可与完整契约随包走。
- 应用建议：若将来要把服务端技能导出给 `.agents/skills/`、MCP、工作流三个消费面，抄这三条语义，由服务端生成并带 `content_sha256` 指纹。
- 优先级：**P2**。适用条件：出现「同一技能多处分发且被手工改过」的事故。
- 需调整：**权威必须在 DB**，导出物是派生物、不得反向同步；4 个 IDE 目录配置不抄（我方宿主是 WorkBuddy + 自有服务端）。

---

## 7. 不宜照搬清单

| 项 | 具体文件/证据 | 不照搬原因 | 替代做法 |
|---|---|---|---|
| 60 个模板化 SKILL.md 的规模化产出 | 全部 60 份行数 100–104、中位数 101；`delivery-handover/SKILL.md` 正文＝front matter 复述 | 信息密度低、重复骨架；我方 4 个 runbook 是命令/端口/编码坑/事故对照，模板化会稀释 | 只抄「三件套结构」与字段语义，内容仍按 runbook 写实 |
| 20 字段全必填 + `additionalProperties: false` | `schemas/skill.schema.json` required 列表 | 对操作型 runbook 是过度契约，`inputs/outputs/evaluation` 难以诚实填写，会催生占位文本 | B2 的 5 组最小字段集，允许缺省 |
| 12 类 FDE 方法分类与 8 阶段交付框架 | `README.md`「分类」表与「需求→…→Delivery」 | 与我方 **G1–G9 门禁**、工作台操作技能不同域；前序横评已裁决不搬八阶段 | 自建 4–6 类操作域分类 |
| `skills.json` / `INDEX.md` 作为文件权威 + CI 锁 diff | `.github/workflows/ci.yml` 末步 | 我方是 SQL 权威库 + Alembic；再立文件索引会形成双权威 | DB 导出为只读视图，pytest 校验种子↔DB 一致 |
| Python CLI 运行时 + 4 个 IDE 适配器 | `pyproject.toml`（`fde` 命令）、`adapters/{codex,claude-code,cursor,opencode}/` | 引入第二运行时与不存在的宿主；我方已有 `skill_read` + pinned 消费 + 治理 API | 只抄导出安全语义（B7） |
| `examples/` 5 个端到端合成案例与 `eval.jsonl` | `examples/*/artifacts/*.md`、`README.md`「案例数据和评测结果默认属于合成教学样本」 | 我方客户资料红线要求真实证据，合成案例易被误当成验证结果 | 反例只作为**发布材料**（B4），显式标 synthetic |
| AGPL-3.0-only 全库许可与 `legacy/` 历史导入 | `NOTICE.md`「Some historical imports have no recorded redistribution license」 | 许可传染且来源不明，商业交付系统不可引入；`legacy/` 是归档不是依赖 | 引用第三方只登记来源与许可（B1），不复制文件内容 |
| `status: draft/ready/field-validated` 状态值 | `docs/skill-spec/README.md` | 我方四态治理带审核人/密码/测试报告，语义更强，替换即退步 | 只抄「治理通过 ≠ 现场验证」口径 |

---

## 8. 与《开源项目借鉴总览》的关系（防重复立项）

本文是**专项对比**，不新增总览清单编号；可借鉴项与既有条目的映射如下，实施时应合并而非另起工程项：

| 本文条目 | 合并到总览 | 说明 |
|---|---|---|
| B2 结构化契约最小字段集 / B4 正反例 | **#29 验证/验收合同**、**#22 三锚+四反例** | #29 已明确「确认摘要只覆盖定义、人工接受保留真实 FAIL」；字段集挂 `SkillVersion.manifest_json` 与 `test_report_json`，不新开合同对象 |
| B3 校验器纪律 / B5 索引与分类 | **#8 Skill 两级注入**、**#32 固定目录+只读技能中心** | `skill_read` 全文单发无分页是已核实真缺口；B3 的静态校验并入 #32 的技能中心校验面，与 `fde` 的 45 个 `references/` 渐进披露同构 |
| B6 行业叠加 | **#15 Lens 正交叠加** | 同为「叠加不覆盖」，只做一次 |
| B1 成熟度与来源纪律 | **#27 上游基线锁定与出处决策记录** | 都是「出处/版本可查」纪律，写入同一份决策记录 |
| B7 导出安全语义 | 暂不立项 | 触发条件未到（见 §9） |

---

## 9. 待确认与假设

1. **指代确认**：本文把「当前技能项目」界定为 `fde-workbench/.agents/skills` + 服务端技能资产层；若您指的是用户级 `C:\Users\P1\.workbuddy\skills\fde` 系列（B 组），请把 B 组提升为基准重排借鉴优先级——B1/B2/B3 的结论方向不变，落点会改到用户级目录。
2. **远端状态**：本轮只读本地 git 副本（HEAD `b8c6876`，2026-10-07 CHANGELOG 为 Unreleased），**未联网核对 GitHub 上是否有更新**；若远端已有新版本，§1–§7 的结构结论需复核。
3. **未实跑**：`fde validate` / `pytest` / `fde export` 均**未在本机执行**（本机未装其 venv）；校验规则结论来自源码静态阅读，标注为 `[已核实·静态]`。
4. **许可判断非法律意见**：AGPL-3.0-only 与我方商用交付的兼容性未做法务审查，本文只按「不复制代码/内容、只译设计语义」的保守口径处理。
5. **是否并入总览**：本轮按用户要求只输出专项对比文档，**未改动《开源项目借鉴总览》**；如需把 B1–B7 作为 #35 起的新条目并入，请拍板。
6. **未核实项**：B 组 40+ 通用技能包仅统计了目录名，未逐一读取其内容规范；C 组 `legacy/` 31 个旧技能仅读 `README.md` 与 `NOTICE.md`，未逐份核对 skill 正文。
