# 可维护性与扩展性官评审意见

## A. 总评

**判定：有条件通过 — 方向成立，但存在 3 处 P0 与 4 处 P1 的「重复立项 / 条件触发项被提前做 / 证据格式不合规」问题，须先修订再进入实施排期。**

方案的核心架构判断（控制面 + 执行面 + 桥接层）是正确的，且与借鉴总览 §0 的横评裁决一致：**不引入第二运行时、不换执行体、把现有骨架当已存在的执行器**。这一点方案做对了——§2.1 用 5 条实测证据推翻了「工作台缺编程执行层」的原对话误判，§10 Q5 明确「DSH 不作为第二家编码智能体」（理由：`control/dsh_runtime.py:1` 的协议定位 + 本机无 8020 监听），与总览 §0 DSH 专项结论④「装官方 DSH 不会自动满足我方协议」完全同向。

但方案存在**三个系统性问题**：

**问题一（最重）：方案全文零处引用借鉴总览，§11 文档关系表里也没有它。** 实测 `grep -n "借鉴\|开源\|v3-backlog\|Lens\|总览\|B#" docs/audit/售前驱动交付模式改造方案-待评审.md` 只命中 2 行，且都是无关命中（:129 讲合同条款、:403 提 `v3-backlog.md` 但只为说明「G4 台账无对应条目，建议新立」）。这意味着方案在**完全没有对照借鉴总览既有裁决**的情况下，就重新铺开了 8 项第五阶段工作、重新设计了七阶段 SOP、重新提出了方案三选项契约。凡是总览已定选型、已登记、已判「条件触发」或「负向登记」的地方，本方案都存在**重复立项或越权**的风险。

**问题二：§7 第五阶段 8 项中，至少 5 项与已登记/已落地能力重叠，2 项与条件触发裁决冲突。** 其中「交付物模板化 / Skill 化 / 插件市场」三项直接撞上总览 #36/#37（已实施未提交，提交 `48128fe` 存在于 `feat/v3-b36-b37-skill-contract`，未合入 `fork/main`）与既有 `control/extensions_service.py` 的插件治理体系；「CI/CD、部署审批」撞 #3 审查不执行被审代码红线与既有 `automation_approvals` 闸；「回滚」撞既有 Skill rollback（`control/extensions_service.py:387`）与 `T-S1` 审计缺口收口。

**问题三：方案作为一份「方案/评审类文档」，其自身证据格式不符合总览 #33 的四列要求**（命令／退出码／可观察结果／未验证项），且 `docs/verification/` 目录在 `fork/main` 上零命中（实测 `git ls-tree -r --name-only fork/main -- docs/verification` 空输出）。方案 §2 的 30 处 `file:line` 引用是**好的**，但缺「未验证项」这一列——而方案自己的 §10 Q5 就有多处「属运行态，文档不作断言」（:53），恰恰是 #33 要求显式落列的内容。

---

## B. 逐条比对表

| 借鉴总览要点 | 方案中的位置 | 判定 | 问题描述 / 证据 |
|---|---|---|---|
| **#15 Lens 正交叠加**（⏸ 条件触发；触发条件＝多行业并存导致选一模板维护成本实测失控；当前 3 行业整体模板够用） | §4 S1「选行业模板与首期模块」（:137）；§7 第一阶段（:224-235）无 Lens 提及 | **已一致（未越权）** | 方案未提出 Lens 叠加机制，未提前做条件触发项。技术实施文档 S0-6（`docs/技术实施方案-智能体交付工作台.md:37`）定的首批仍是「2–3 个行业」种子，与总览「当前 3 行业够用」一致。**但方案 §4 S1「选行业模板」在多行业/多客户场景下的可复用性未表态**——见 E-3。 |
| **#16 交付编译器契约清单**（⏸ 条件触发；触发＝上游 90 天内有 release tag 且 CI 转绿，由产品 owner 提请重评；上游 0 测试 0 CI，声明非验证） | §4 S4「三选项与取舍 / 推荐 / 明确不做 / 验收标准」（:140）；§7 第一阶段第 4 项「方案三选项 + 取舍 + 明确不做 + 验收标准 的骨架模板」（:231） | **存在冲突（越权风险）** | 总览 #16 的触发条件是「FDEP Kit 上游发 release + CI 转绿」，即**契约清单的来源是上游验证过的 INVARIANTS**。方案 §4 S4 与 §7 第一阶段第 4 项要做的「三选项 + 取舍 + 明确不做 + 验收标准 骨架模板」，实质就是**模板解析→方案骨架的确定性契约**——即 #16 的事。**证据**：方案 :140 写「`solutions.skeleton`（模板草稿）、`solutions.organize`（AI 建议不落库）」，而 `server/src/fde_api/solutions/service.py:797` `create_solution_skeleton` 已是**确定性搬运**实现（`_skeleton_text_fields` :895-945 纯拼装，「AI 不参与内容生成」，:800 docstring）。**判定**：方案在 §7 第一阶段要做的是「**给既有确定性骨架加三选项段落**」——这是产品功能扩展，不是「建立交付编译器契约清单」（后者指 P1–P10 级别的解析确定性/幂等/输入顺序无关/未知标识符拒绝**不变式**）。两者**概念不同但表述易混**。→ 见 C-1（待澄清项，不建议替代总览裁决）。 |
| **#33 文档职责分层 + 验证证据格式**（⬜ 待实施；落点＝新建 `docs/verification/` 目录与证据模板（命令／退出码／可观察结果／未验证项四列）；审查／评估类报告的证据索引统一采用该格式；台账 Task 勾选须附最窄验证命令） | 全文证据格式（§2 全表 30 处 `file:line`）；§10 Q5「DSH 是否真在本机环境启用属运行态，文档不作断言」（:53） | **明显偏离** | 方案**未采用四列证据格式**：全文 `grep -c "退出码\|未验证项\|可观察结果"` 命中 **0**；`grep -c "\.py:"` 命中 30（有 file:line，好），`grep -c "grep "` 命中 2（G3/G4 的 grep 断言，:80/:81）。**缺口**：①无「退出码」列——如 :80 `grep -rln "transcri\|audio\|录音" server/src` 声称「仅命中这两处且语义不符」，实测该命令确实只命中 `ai/kimi.py` 与 `control/chat.py`（另命中 `.pyc`，方案表述略偏）；②无「未验证项」列——方案 :53 自己在正文里承认「DSH 是否真在本机环境启用属运行态，文档不作断言」，这正是 #33 要显式成列的内容，目前只在散文里。**且 `docs/verification/` 目录在 `fork/main` 零命中**（实测 `git ls-tree -r --name-only fork/main -- docs/verification` 空）。→ C-2。 |
| **#31 原件/派生分层 + stale 判定**（⬜ 待实施；与 #12 合并实施；落点＝`project_evidence` 补 `bytes`＋`mtimeMs` 供 stale 判定；原件留工作目录不进仓库不入库；加断言「导入／预览／转换不产生任何 AI 调用」） | §10 Q1「原文留本地 raw/ 不入库」（:295、:302）；§7 第二阶段「产物→交付包」（:243-247）；§4.2 run 返回结构（:157-161） | **存在冲突（缺失 stale 判定）** | Q1 决策「入库前替换为代号，原文留本地 raw/」**与 #31「原件留项目工作目录」的落点纪律同向**，这部分一致。但 **#31 的核心机制在方案中零覆盖**：实测 `server/src/fde_api/evidence/models.py:21` `ProjectEvidence` 只有 `source_uri` + `content_sha256` + `origin` + `captured_from`，**无 `bytes`、无 `mtimeMs`**——即 stale 判定的载体不存在。方案 Q1 说「售前自行留存于本地 raw/」，那**原始访谈资料被售前改了之后，已入库的代号化正文如何知道它 stale 了？** 方案无答案。**且 §7 第二阶段「产物→交付包」在原件失效时怎么办，方案完全未写**——`agent_artifacts` 只有 `storage_ref` + `sha256`（`agents/models.py:124-142`），封包时按 sha256 校验能发现「内容变了」，但发现之后走什么流程（重跑 / 标记待重新确认 / 阻断封包）方案无契约。→ C-3。 |
| **#36 技能结构化契约**（✅ 已实施·未提交；`SkillVersion.manifest_json` 增可选扩展键，免迁移；5 组语义；存量 4 个 runbook 不回填） | §7 第五阶段「Skill 化」（:255） | **存在冲突（重复立项）** | 方案 §7 第五阶段的「Skill 化」若指「把交付流程沉淀为 Skill」，则与已实施未提交的 #36 载体**完全重合**。**证据**：`feat/v3-b36-b37-skill-contract` 提交 `48128fe`（实测 `git merge-base --is-ancestor 48128fe fork/main` → **NOT in fork/main**）已落《技能结构化契约 v1》五组语义（`use_boundaries`/`effects`/`evidence`/`verification`/`failure_behavior`），载体是 `SkillVersion.manifest_json`（`control/models.py:245`，JSON 列免迁移）。方案 §7 第五阶段未提「Skill 化」要解决什么问题、落在哪张表，**存在与 #36 撞车、重复定义「Skill 该长什么样」的风险**。→ C-4。 |
| **#37 技能自洽校验**（✅ 已实施·未提交；`server/tests/test_skill_contract.py` 169 行；标准库+pytest，零新依赖） | §7 第五阶段「Skill 化」（:255） | **存在冲突（重复立项）** | 同上。#37 已建好「Skill 内容是否自洽」的机器闸（实测 `git show 48128fe:server/tests/test_skill_contract.py` 头 12 行：四钉＝runbook front matter／种子静态／manifest 规则／种子↔DB 对账）。方案第五阶段若另起一套「Skill 化」校验，将与 #37 形成**两个 Skill 校验器**。 |
| **#19 / #26 / #40 三份「不做清单」（负向登记，防重复立项）** | §7 第五阶段 8 项（:255）；§7 第三阶段「git worktree / PR / CI 编排层（可考虑直接复用 openfde `worktree` + `run`）」（:247）；§10 Q6（:358-368） | **明显偏离（重复立项）** | 逐项核对 §7 第五阶段 8 项：<br>①**CI/CD** — 撞 #3「审查不执行被审代码」红线（已由 #128 落 AGENTS.md 红线第 7 条）；②**部署审批** — **已落地**：`control/models.py:163-200` `AutomationApproval` 已有完整闸（`request_key` 唯一、`arguments_sha256`、15min 过期、`risk_level` CHECK）；③**回滚** — **已落地**：`control/extensions_service.py:387` `rollback_skill` + `control/routes.py:107` 路由 + backlog T-S1/T-S2 审计事件收口；④**运行监控** — 撞既有 `metrics/service.py:51` `build_metrics_report`；⑤**线上问题反馈** — 撞既有 `mailing/models.py:82` `feedback_type` + `mailing/policy.py:44` `feedback_is_retryable`；⑥**交付物模板化** — 撞既有 `templates/service.py`（`copy_template_version`:393／`publish_template_version`:467／`serialize_template_snapshot`:630）+ `documentTemplates/DocumentTemplatesPage.tsx`；⑦**Skill 化** — 撞 #36/#37（见上）；⑧**插件市场** — 撞已落地 `control/dsh_market.py:24` `sync_dsh_market` + `:117` `search_dsh_market` + `control/routes.py:193/208` 两路由 + `extensions_service.py` 插件变更治理。**8 项中 7 项有既有载体或已登记裁决**。→ C-5。 |
| **§5 四态实施节奏**（已兑现／本轮可排期／零载体／封存） | §10 决策后实施顺序表（:386-392） | **存在冲突（未标四态）** | 方案 :386-392 的五行表把「一·访谈→SOW」到「并行·ASR 通道」并列为五个阶段，**但未标注每项在借鉴总览 §5 四态中的位置**。总览 §5.1 已兑现清单含 #1/#2/#3/#4/#5/#6/#21/#22/#29/#27/#28/#8/#32/#10/#35 共 14 条，**禁二次立项**；§5.4 第二批含 #7–#14/#30/#31/#32/#36/#37。方案第三阶段「openfde 编排接入」中的「git/worktree/PR/CI 编排」若落地，会与 #31（原件/派生）、#12（外部文字禁入提示词）在**资料导入链路**上产生交叉——方案未识别这一点。 |
| **§1 跨项目合并原则表** | 全文无引用 | **明显偏离** | 方案独立提出的三处新建（「三段式桥接层 B1/B2/B3」§3 图 :113-117；「四级能力闸」§6+§10 Q3 :315-328；「三种交付模式」§4.1 :145-153）**均未对照合并原则表自检**。其中「四级能力闸」与既有 `control/access.py:36-42` `ACCESS_RANK`（5 档）+ `auth/permissions.py` `ROLE_RANK`（4 档）的**双重位阶体系**存在概念交叠——方案 Q3 说「不建新表」是对的，但「四级能力闸」这个**新名词**与既有 `access.py:72-75` 的 `agent.*` 能力档位（`agent.plan.generate`≤project_operator 等）的关系未说明。 |
| **§6.5 拍板决议索引 Q1–Q18** | §10 Q1–Q7（:293-380） | **编号冲突风险** | 方案的「Q1–Q7」与总览「Q1–Q18」**是两套独立编号体系**，且方案未声明。方案 Q1（代号化边界）与总览 Q1（结果验收 vs 静态打分）**语义完全不同**。方案 :290「七项全部已决（用户交互式拍板）」的表述会让读者误以为与总览 §6.5 是同一批决议。→ E-4。 |
| **§7 许可硬条款**（5 条；R2 决议要求逐字落进 `v3-backlog`/`AGENTS.md`；B#35 修复项） | §9 红线清单（:277-284） | **已一致（但可加强）** | 方案 :283「需再加一条脱敏断言（CI 已有 gitleaks，需再加一条脱敏断言）」方向与总览 #35「先搜再建」（新增技能先查技能中心）同向；但方案 §7 第五阶段「Skill 化」若引入外部技能材料，**未提许可登记义务**。总览 §7 第 4 条要求「引用第三方材料前登记确切版本、许可、出处与快照日期」。→ D-3。 |
| **#4 purity 架构测试**（✅ 已实施 #129/#130；`server/tests/test_architecture_purity.py`） | §7 第二阶段「`agent_artifacts` 增 diff/test_results」（:245）；§10 Q6（:360） | **存在冲突（新耦合热点未被 purity 约束覆盖）** | 实测 `fork/main:server/tests/test_architecture_purity.py` 只锁了 **workflows/ ↔ control** 一条环（4 条断言：workflows 顶层不 import control.service/routes、control.service 只延迟 import workflows、workflows 内核不读 env/flask、零产品名硬编码）。**agents/dispatch/solutions 三者之间的环完全没有测试保护**。实测当前已有：`solutions/service.py:14` 顶层 import `agents.models` + `:180` 函数内延迟 import `agents.service`（注释明写「延迟导入：避免 agents⇄solutions 环」），`agents/service.py:87-88` 顶层 import `dispatch.agent_assisted` + `dispatch.models`。方案第二阶段若把 diff/test_results 塞进 `agent_artifacts` 并让 dispatch 侧读，**agents→dispatch→agents 环会立刻实体化**。→ C-6。 |
| **#7 回执 DSL 一期**（⬜ 待实施；新 `agents/receipt.py`；Pydantic + 未知字段拒绝；ask/later） | §5.1 统一适配器协议（:173-177）；§4.2 run 返回结构（:157-161） | **存在冲突（重复立项）** | 方案 §5.1 提出统一适配器协议 `prepare_workspace · validate_request · run · collect_result · cancel · health_check` + 「统一输出：`status / summary / changed_files / commit+diff / test_results / artifact_references / known_risks / cost / logs / sha256`」，§4.2 提「每次 run 必须返回的结构」。**这正是 #7 回执 DSL 的内容**（Pydantic + 字段白名单 + 未知字段拒绝）。实测 `server/src/fde_api/agents/receipt.py` **不存在**（#7 确未实施），#7 状态为「⬜ 待实施」。方案 §5.1 用「统一适配器协议」这个**新名字**做同一件事，**未声明与 #7 的关系**。同时 `fork/main:server/src/fde_api/agents/adapter.py:66-78` `AgentRunResult` 已有 9 个结构化字段（含 B#2 的 `receipt_state`），方案 :177 的 11 字段清单**与既有字段无映射表**。→ C-7。 |
| **#12 外部文字禁入提示词硬边界**（⬜ 待实施；渲染层强制；外部来源内容只入文件不落仓库；提示词只放受控引用） | §5.3 执行隔离红线（:191-198）；§9 红线第 3 条（:283） | **已一致** | 方案 :283「执行面不可触真相层：沙箱不挂 `D:\test\FDE\…`、不挂 `.env`；脱敏渲染 fail-closed」与 #12/#31 的落点纪律同向。`agents/service.py:332` `_render_context` 已是 fail-closed 422 实现。**本项是方案与总览一致度最高的一处。** |
| **#21/#22/#29 交付效果评测协议 + 验收合同**（✅ 已实施 #128/#131；`docs/architecture/交付效果评测协议-v0.md`；G9 exit_condition 已挂接） | §4 S7（:143）「人工核验 accepted」；§8 成功度量（:259-269） | **已一致（但缺引用）** | 方案 §4 S7 的「门禁证据提交 → 人工核验 accepted」与既有 G8/G9 `claimed≠accepted` 语义一致。**但方案 §8 把「G8 验收一次通过率」列为指标（:269）却未引用协议 v0**，且 #22 已明确阈值 0.8 是「占位·待我方数据校准」（总览 R4 决议），方案若据此设 KPI 会踩未校准阈值。→ D-2。 |
| **§0「不引入第二运行时」裁决 + #20 DSH 条件触发** | §10 Q5（:341-356） | **已一致（本方案最大加分项）** | 方案 :349「DSH 的职责是 AI Server 编排层（工具调用、审批、预算记账），与『编码执行器』不是同一位置，兼用会造成职责重叠」——与总览 §0 DSH 专项结论④「装官方 DSH 不会自动满足我方协议，适配层仍需自写」+ Q8「不立项自写适配层」完全一致。**方案 §5.1「扩展它，而不是另起一套」也对**（实测 `agents/adapter.py:105` `class ZcodeAdapter` / `kind = "zcode"`）。 |
| **#8/#32 Skill 两级注入 + 只读技能中心**（✅ 已实施 #138，核心缺口已闭合；两级注入整体仍 PROPOSED） | §7 第五阶段「Skill 化」；§4 S7（:143） | **存在冲突（部分越权）** | 总览 §5.2 口径澄清明确：「#138 闭合的是『skill_read 全文单发无分页』这一核心缺口，但『两级注入』与『只读技能中心』整体仍 PROPOSED」。方案 §7 第五阶段把「Skill 化」整包铺开，**未区分已闭合与仍 PROPOSED 两部分**。 |

---

## C. 必须修改项

### P0-1｜§7 第一阶段第 4 项「方案三选项骨架」与条件触发项 #16 的边界必须写清，否则构成越权

**问题**：§4 S4（:140）与 §7 第一阶段第 4 项（:231）提出的「方案三选项 + 取舍 + 明确不做 + 验收标准 的骨架模板」，在读者视角与总览 #16「交付编译器契约清单」高度同形——两者都指向「方案模板的结构化字段化」。而 #16 是**条件触发**项，总览 §5.5 明确列在「长期与封存 → 条件触发」下，触发判据是「90 天内有 release tag 且 CI 转绿，由产品 owner 提请重评」（§6.5 R4 附注 / §5.5）。

**证据**：
- 总览 :132「| **16** | ⏸ 条件触发 | … | **交付编译器契约清单**（解析确定性/幂等/输入顺序无关/未知标识符拒绝） | 写成 V3「模板解析→方案骨架→文档渲染→Skill 注入」契约清单。**须标注上游 0 测试 0 CI，是声明非验证** | 条件触发。配合 #14 落地后价值更大 |」
- 总览 :599「**条件触发**：**#15、#16、#20、#34**（触发判据依赖 §6.6 数据；#16 触发＝90 天内有 release tag 且 CI 转绿，由产品 owner 提请重评…）」
- 方案 :231「4. 方案三选项 + 取舍 + 明确不做 + 验收标准 的骨架模板」
- 方案 :140「`solutions.skeleton`（模板草稿）… 需接三选项与取舍」

**建议改法**（不与总览裁决矛盾）：在方案 §7 第一阶段第 4 项与 §4 S4 各自加一句**边界声明**：「本项是**产品模板的字段扩展**（给既有确定性骨架 `solutions/service.py:797` `create_solution_skeleton` 增加三选项/取舍/明确不做/验收标准四段占位），**不新建『交付编译器契约清单』**（不变式：解析确定性/幂等/输入顺序无关/未知标识符拒绝）；后者属借鉴总览 #16 条件触发项，触发判据未满足，本轮不动。」**同时在 §11 文档关系表补一行**，把本方案登记为借鉴总览 #15/#16 的**下游消费者**而非并列文档。

---

### P0-2｜§7 第五阶段 8 项必须逐项标注「既有载体 / 已登记裁决 / 真正新增」，否则构成重复立项

**问题**：§7 第五阶段（:253-255）「CI/CD、部署审批、回滚、运行监控、线上问题反馈、交付物模板化、Skill 化、插件市场」以逗号平铺，**无一项标注其既有载体**。实测 8 项中 **7 项已有实现或已登记裁决**：

**证据**（逐项）：
| 第五阶段项 | 既有载体（实测） |
|---|---|
| 部署审批 | `server/src/fde_api/control/models.py:163-200` `AutomationApproval`：`request_key` 唯一约束（:171）、`arguments_sha256`（:193）、`expires_at`（:195）、`risk_level` CHECK 3–4（:170）、`workflow_node_run_id` FK（:182-185） |
| 回滚 | `control/extensions_service.py:387` `rollback_skill`；`control/routes.py:107` `POST /extensions/skills/<skill_id>/rollback`；backlog T-S1 四条治理事件已收口 |
| 插件市场 | `control/dsh_market.py:24` `sync_dsh_market`／`:117` `search_dsh_market`；`control/routes.py:193` `GET /extensions/marketplace/search`／`:208` `POST /extensions/marketplace/sync`；`extensions_service.py:828` `_validate_plugin_action` |
| 交付物模板化 | `templates/service.py:393` `copy_template_version`／`:467` `publish_template_version`／`:630` `serialize_template_snapshot`；桌面 `documentTemplates/DocumentTemplatesPage.tsx`（DOCX 模板上传/发布/停用/下载） |
| 运行监控 | `metrics/service.py:51` `build_metrics_report`（只读聚合 + `insufficient_data` 口径） |
| 线上问题反馈 | `mailing/models.py:82` `feedback_type`；`mailing/policy.py:44` `feedback_is_retryable` |
| Skill 化 | 借鉴总览 #36/#37 已实施未提交（`48128fe`，未合 fork/main） |

**唯一真正没有载体的是 CI/CD 与 git/PR 编排**——但方案 §10 Q6（:358-368）已裁决「不自建 git/worktree/PR 逻辑，复用 openfde」，且 §11（:403）已自认「G4 当前台账无对应条目，建议新立」。**即第五阶段 8 项里 7 项可查账、1 项需新立，而方案把它们并列成了同一批「持续改进」工作。**

**建议改法**：把 §7 第五阶段改为**带载体标注的分类表**：
- **A 类·已有载体，本阶段只补缺口**（部署审批 / 回滚 / 插件市场 / 交付物模板化 / 运行监控 / 线上反馈）——写明「既有 X（file:line），本阶段拟补 Y」；
- **B 类·已登记裁决，不得重开**（Skill 化 → 挂 #36/#37 的 PR 合入，不另起炉灶）；
- **C 类·真新增，需新立台账条目**（CI/CD 与 git/PR 编排 → 走 §11 已建议的「新立」，进 `docs/implementation/v3-backlog.md`）。

---

### P0-3｜方案 §2 的证据格式必须补齐 #33 四列，并新建 `docs/verification/`

**问题**：总览 #33（:139）明确要求：「新建 `docs/verification/` 目录与证据模板（**命令／退出码／可观察结果／未验证项四列**）；**审查／评估类报告的证据索引统一采用该格式**；台账 Task 勾选须附最窄验证命令」。方案**正是一份审查/评审类文档**（§2「现状校正（VERIFIED，代码实测）」、§3「目标架构（PROPOSED）」、§10「决策台账」），但：

**证据**：
- 方案全文 `grep -c "退出码\|未验证项\|可观察结果"` = **0**（无四列格式）
- `docs/verification/` 在 `fork/main` 零命中：`git ls-tree -r --name-only fork/main -- docs/verification` → 空输出
- 方案 :53 自己承认「**但** DSH 是否真在本机环境启用属运行态，文档不作断言」——这正是「未验证项」，却只写在散文里，未成列
- 方案 :349-350「本机**未部署 DSH**：无 8020 监听（`dsh_base_url` 默认 `http://127.0.0.1:8020`）、`/d/test/FDE/` 下无 DSH 仓库、compose 与 `.env.example` 均无 dsh 条目」——这条**有命令、可能也有退出码与可观察结果**，但仍是散文而非四列行
- 反面实证：方案 :80 的 G3 grep 断言「`grep -rln "transcri\|audio\|录音" server/src` 仅命中这两处且语义不符」——实测该命令**同时命中 `control/__pycache__/chat.cpython-313.pyc`**；方案 :81 的 G4 断言「`grep -rln "worktree\|git " server/src` 零命中」——实测**命中 `server/src/.mypy_cache/3.12/cache.*.db` 三个二进制缓存文件**。这两条不是「结论错」而是「**命令未排除缓存/二进制、退出码未记录**」——正是 #33 要解决的形态

**建议改法**：
1. 方案 §2 前新增一节「§2.0 证据口径」，声明本方案采用 #33 四列格式，并给出 `docs/verification/` 模板的**最小可用形态**（四列：命令／退出码／可观察结果／未验证项）。
2. §2.1 / §2.2 / §2.3 三张表各增两列：`验证命令（含退出码）` 与 `未验证项`。至少把 G3/G4 两条 grep 断言**重跑为排除缓存的形式**（如 `grep -rn --include='*.py' -l 'worktree' server/src`），并把「mypy_cache / __pycache__ 命中」列入未验证项或直接以 `--include` 排除。
3. 在 §11 文档关系表补一行：`docs/verification/`（待建，借鉴总览 #33 落点）——**并声明本方案自身是 #33 的第一个适用对象**（借鉴总览 #33 是「⬜ 待实施」状态，且是低成本的「1 个目录模板＋3 条 AGENTS.md 条款」；方案作为评审类文档，先行落地它比事后补更符合总览 §4.5 D6 的价值判断「证据可复核、需求与代码不脱节」）。

---

### P1-4｜§7 第二阶段「`agent_artifacts` 增 diff/test_results」必须先做模块边界裁决，防止 agents⇄dispatch 环实体化

**问题**：方案 :245「`agent_artifacts` 增加 diff / test_results 结构化字段」+ :246「产物指纹接入 `delivery_package` 封包」+ :389 决策后顺序表「二 · 执行层可见与咬合」，把 **agents（执行面）→ dispatch（控制面派单）** 的数据流坐实。但当前架构里 agents 与 dispatch 是**单向**的：

**证据**：
- `agents/service.py:87-88` 顶层 import `dispatch.agent_assisted` + `dispatch.models`（agents → dispatch）
- `dispatch/packages.py:25-34` 顶层 import 里**无 agents**（dispatch 不依赖 agents）
- `solutions/service.py:14` 顶层 import `agents.models` + `:180` 函数内**延迟** import `agents.service`，注释明写「延迟导入：避免 agents⇄solutions 环」
- `fork/main:server/tests/test_architecture_purity.py` 只锁了 **workflows/ ↔ control** 一条环（4 条断言），**agents / dispatch / solutions 三者之间零断言**

即：**若把 diff/test_results 落到 `agent_artifacts` 并让 dispatch 侧读取以做封包，agents→dispatch→agents 环会立刻实体化，且没有任何测试会拦住它。** 而总览 #4（✅ 已实施 #129/#130）确立的纪律正是「用静态断言锁模块边界与纪律」，且明确列举了「实证已存在：projects↔control 导入环」这类先例。

**建议改法**：在方案 §7 第二阶段下增「模块边界裁决」小节，明确三选一并写进 PR：
- **选项 A（推荐，与既有惯例同构）**：`agent_artifacts` 的新字段**只写不读**（由 agents 侧在 run 完成时落库）；封包时 dispatch 侧**通过 `project_evidence` 指针 + sha256** 取数，不直接 import agents 模型——沿用 `solutions/service.py:288` 已有的「按 run_id 查 AgentArtifact」模式反向复用（把该查询下沉为共享查询函数放 `evidence/` 而非 `agents/`）；
- 选项 B：新字段读走 dispatch API（跨模块 HTTP/服务调用），代价是延迟与一致性；
- 选项 C：接受 agents⇄dispatch 环，**则必须同步扩 `test_architecture_purity.py` 的断言范围**（把 agents/dispatch/solutions 三方纳入），否则环会静默形成。
无论选哪条，**方案 §7 第二阶段的交付物里必须包含「模块边界断言」这一项**，否则 #4 的纪律在新边界上失效。

---

### P1-5｜§10 Q1 与 §7 第二阶段「产物→交付包」必须补 stale 判定语义（#31）

**问题**：方案 §10 Q1（:295-302）决策「入库时把正文中的真实企业名替换为代号，原文留在本地 raw/ 不入库」。这与总览 #31「原件留项目工作目录、不进仓库不入库」同向，**一致**。但 #31 的**另一半——stale 判定**在方案中零覆盖：

**证据**：
- 总览 :122「按 `bytes`＋`mtimeMs` 变化把旧派生的 `parse.status` 标 `stale`（「原件已经改变，需要重新识别」）… `project_evidence` 补 `bytes`＋`mtimeMs` 用于 stale 判定；加断言测试「导入／预览／转换不产生任何 AI 调用」」
- 总览 §5.2 第 3 顺位：「**#12 + #31** 外部文字禁入提示词 + 原件/派生分离 | ≈1–2 人日 | 合流实施…`project_evidence` 补 `bytes`+`mtimeMs` 供 stale 判定」
- 实测 `server/src/fde_api/evidence/models.py:21-49` `ProjectEvidence` 字段：`kind` / `source_uri` / `content_sha256` / `origin` / `captured_from` / `created_by_user_id` — **无 `bytes`、无 `mtimeMs`**
- 方案 :302「原文由售前自行留存于本地 raw/（遵循 somwyn「raw/ 只增不改」纪律）」——「只增不改」约束的是原件，但**入库的代号化派生**若与原件脱钩（售前换了原件、或代号化字典漏替换导致正文残缺），**无人能发现**
- 方案 §7 第二阶段（:243-247）与 §4.2（:157-163）均**未描述原件失效时产物怎么办**：`agent_artifacts` 只有 `storage_ref` + `sha256`（`agents/models.py:124-142`），封包校验能发现「内容变了」，但**之后走什么流程无契约**（重跑？标「待重新确认」？阻断封包？）

**建议改法**：在 §10 Q1 的「落地约束」段补一句：「代号化正文入库时同步落 `bytes`＋`mtimeMs`（`project_evidence` 零 DDL 可行性待核，字段载体见 #31 落点），使**原件变更 → 派生 stale** 可判定；stale 派生不得直接进入交付包封包，须重跑代号化或人工确认。」并在 §7 第二阶段「产物→交付包」下补一条产物失效处理契约：「sha256 不符时 → 标记 `stale` + 通知 + 不自动封包」，与 §9 红线第 1 条「AI 不代拍板」同源（**失效产物不得由 AI 自行决定重跑或放行**）。

---

### P1-6｜§7 第二阶段的「交付包」命名必须用 `handover_packages`，不得用 `delivery_package`

**问题**：方案 :84（G7）、:246、:389 三处使用 `delivery_package` 指代「结项交付包」。这**与既有派单表 `delivery_packages` 撞名**——台账 §十三.4 已就此专门裁决。

**证据**：
- `docs/后续需求台账-F5与D11.md:208`：「**[P2·命名冲突] D11 草案 `delivery_package` 与派单 `delivery_packages` 同名不同义**：本台账二节 D11（结项打包，draft→sealed→delivered，manifest_sha256）与派单引擎 `delivery_packages`（8 态派单机，§2.5）撞名。D11 未实施、派单表已落库——**D11 若日后实施必须改名（建议 `handover_packages`）**」
- 同文件 :654：「① D11 封包不含能力交接 | **降级为设计约束，不立项** | D11 全链路零命中…」
- 同文件 :663：「4. 命名沿用 §十三.4 的 `handover_packages`（避与派单 `delivery_packages` 撞名），**不再单独立项**」
- 实测派单表已落库：`server/src/fde_api/dispatch/models.py:55-57` `ck_delivery_packages_dispatch_status`（8 态：`draft/published/offered/assigned/accepted/rejected/expired/withdrawn`）；`server/src/fde_api/dispatch/packages.py` 服务层已落地
- 实测 D11 未实施：`grep -rn "handover_packages\|delivery_package_item\|manifest_sha256" server/src desktop/src server/migrations` → **零命中**
- 方案 :84 与 :163 把 G7 定为「真实缺口」、§7 第二阶段把它列为「执行层可见与咬合」——**但台账 :654 已把它「降级为设计约束，不立项」**，前置拍板项＝「D11 是否立项 + 首批真实客户数据到位」

**建议改法**：
1. 方案三处 `delivery_package` 统一改名为 **`handover_packages`**（并注明台账 §十三.4 已登记此改名，「属重复发现」）。
2. §7 第二阶段「产物→`delivery_package` 闭环」**加前置条件**：「本项须先满足台账 §十三.4 的前置拍板＝**D11 是否立项 + 首批真实客户数据到位**；在此之前只做 `agent_artifacts` 字段扩展与 `agent_artifacts → project_evidence` 指针接线，不建表、不建封包服务层。」

---

### P1-7｜§5.1「统一适配器协议 + 统一输出 11 字段」必须与既有 `AgentRunResult` 字段和借鉴总览 #7 建立映射

**问题**：方案 :173-177 提出适配器协议六方法 + 统一输出 11 字段。实测既有 `AgentRunResult`（`fork/main:server/src/fde_api/agents/adapter.py:66-78`）已有 9 个字段，方案清单**与之无映射**，且**与总览 #7（回执 DSL 一期，⬜ 待实施）撞车**——#7 的落点就是「新 `agents/receipt.py`：Pydantic + 未知字段拒绝」，即「回执字段白名单契约」。

**证据**：
- `fork/main:server/src/fde_api/agents/adapter.py:66-78`：`status` / `exit_code` / `token_cost` / `duration_ms` / `artifacts` / `tool_calls` / `degraded` / `degraded_reason` / `receipt_state`（B#2 加）
- `server/src/fde_api/agents/receipt.py` **不存在**（实测 `ls` → No such file）⇒ #7 确未实施
- 总览 :111「| 7 | ⬜ 待实施 | … | **回执 DSL 一期（ask+later）** | 新 `agents/receipt.py`：Pydantic + 未知字段拒绝；ask 落任务中心审批行（密码确认闸现成）、later 挂统一到期表；失败走 #2 降级路径；容量对齐我方 64KB 语境。**resolve/events 三期且必须先过风险闸**…」
- 方案 :177「统一输出：`status / summary / changed_files / commit+diff / test_results / artifact_references / known_risks / cost / logs / sha256`」
- 方案 :185「能否返回结构化结果 | 否则产物只能靠扫目录猜，与 `agent_artifacts` 的 sha256 链断裂」——**这条是切中要害的**：现有 `ArtifactFile`（`adapter.py:43`）确实只带 `storage_ref` + `sha256`，`sha256` 链已在，但 diff/test_results 确实缺

**建议改法**：§5.1 增一张**字段映射表**（既有 `AgentRunResult` 9 字段 ↔ 方案 11 字段 ↔ 落点），并明确声明：「本节的『统一输出契约』属借鉴总览 **#7 回执 DSL** 的落点，本方案只提出**字段需求清单**（diff/test_results 缺口），**不新建第二套回执契约**；实施时按 #7 的 `agents/receipt.py` + Pydantic 白名单一次做完，不另起协议。」另加一句：「未知字段拒绝」与 #7 一致，**新增字段须走白名单扩展而非宽松解析**。

---

### P2-8｜§5.1 适配器协议六方法须标注「扩展现有 `ZcodeAdapter` 而非新建接口层」的具体落点

**问题**：方案 :171「现有 `ZcodeAdapter`（`agents/adapter.py:105-108`，`kind = "zcode"`）已经走对了方向——**扩展它，而不是另起一套**」，方向正确，但六方法清单与既有实现无对照，且 `cancel` / `health_check` 在既有适配器中不存在。

**证据**：实测 `server/src/fde_api/agents/adapter.py` 全部方法：`__init__`:110 / `agent_id`（property）:116 / `run`:119 / `_judge_tool_call`:195；`ZcodeAdapter` 只有 `run` 一个公开执行方法。取消能力在 service 层（`agents/service.py:882` `handoff_run` / `:927` `retry_run`），不在 adapter 层；健康检查在 `control/mcp_gateway.py:217` 层面。

**建议改法**：§5.1 补一行落点表，逐方法标注「既有 / 需新增 / 落在哪层」，避免把「adapter 层新增方法」误读为「另建一层接口」。

---

## D. 可选优化项

- **D-1｜§4 S4 的「三选项」段落可直接复用既有 `design_markdown` 骨架结构，无需新模型。** 实测 `solutions/service.py:895-945` `_skeleton_text_fields` 已产出六段固定结构（客户愿景与阶段目标／关键业务问题／方案设想／实施路径 + deliverables/acceptance_criteria/data_systems/schedule/risks），且 `risks` 段已按 `labeled()` 合并「假设 / 本阶段不包含 / 待确认问题」三类前缀（:930-935）——**「明确不做」已有落点**（`out_of_scope_json` → 「本阶段不包含」）。方案 §7 第一阶段第 4 项可注明「三选项与取舍落 `design_markdown` 段内，`明确不做` 复用既有 `out_of_scope` 段，零新列」——这会显著降低该阶段的实际工作量，也避免与既有六段结构形成双权威。

- **D-2｜§8 成功度量的「G8 验收一次通过率」不应直接对照 `uplift ≥ 0.8`。** 总览 R4 决议明确 0.8/0.2/0.95/0.05/0.5 五个阈值均为「**占位·待我方数据校准**」，且「Q6/Q18 法务结论前不得定稿 PASS 线」。方案 §8（:259-269）把「G8 验收一次通过率」列为门禁质量指标，建议注明「本轮不设阈值；阈值校准前只统计分布，不设 KPI 阈值」，与总览 §6.6「样本 <30 条 ⇒ 标 `insufficient_data` **不拍板**」的纪律一致。

- **D-3｜§7 第五阶段「Skill 化」若引入外部技能材料，须挂 #35 许可登记义务。** 总览 §7 五条硬条款第 1/3/4 条：抽象概念可用、结构化表达禁写入本仓、独立重写须声明「来源对照表」、引用前登记确切版本/许可/出处/快照日期。方案 §9（:277-284）新增的 4 条红线未覆盖许可项，建议在 §9 增第 5 条：「引用第三方技能材料须登记版本/许可/出处/快照日期并声明独立重写」，指向 `docs/audit/`（#35 落点）。

- **D-4｜§11 文档关系表补两行。** ①`docs/audit/开源项目借鉴总览-2026-11-05.md`（v1.8）——本方案是其**下游消费者**，需逐条对照登记；②`docs/audit/开源项目借鉴总览-多专家评审-2026-11-06.md`（4 角色 party mode）。当前 §11 表只有 5 行，**零行提到借鉴总览**——这是本次评审发现的最直接的结构性缺陷。

---

## E. 待澄清的开放问题与风险清单

- **E-1｜待澄清：方案 §7 第五阶段与借鉴总览 §5 四态的对应关系，需用户裁决。** 方案把 8 项铺成第五阶段；总览 §5.1 已兑现 14 条（**禁二次立项**）、§5.2 本轮可排期 3 项（#9 / #7 / #12+#31）、§5.4 第二批 10 项、§5.5 条件触发 4 项 + 负向登记 3 项 + 封存 1 项。**建议由用户裁决**：第五阶段的 8 项是否即对应总览 §5.2/§5.4 的既有条目（若是，应改写为「引用总览条目号」而非新起炉灶）；若确为新增（如 CI/CD 编排），应先在 `docs/implementation/v3-backlog.md` 登记（方案 §11 :403 已自认要新立）。**理由**：直接改写第五阶段可能与用户「先做售前主线、持续改进后置」的商业节奏冲突，故不由本评审直接改。

- **E-2｜待澄清：方案 §4 S4 的「三选项骨架」是否构成对 #16 条件触发裁决的越权，需用户裁决。** 见 C-1。**建议由用户裁决**：本方案第一阶段是否要做「交付编译器契约清单」这一层（不变式级），还是只做「产品模板字段扩展」。**理由**：#16 的触发条件是上游 release + CI 转绿，若我方**主动定义**自己的方案模板不变式，则本质是「我方自建契约」而非「借鉴 FDEP 的契约」——此时应考虑的是「要不要顺手把自建的不变式也写下来」，而这恰好会**提前消耗掉 #16 的触发理由**。本评审不推荐任一方向。

- **E-3｜多行业/多客户/多执行体的横向扩展性，方案未给判据。** §4 S1 只写「选行业模板与首期模块」（:137），全文「行业」只出现这 1 次。总览 #15 的触发判据已量化到可采集：「各客户类型的模板数、近季度修改次数、因行业差异新增分支数、维护人时」，owner＝产品 owner，截止＝评审日+14 天，产出《触发判据数据采集表》（§6.6 第一行）。**风险**：方案 §4 的七阶段 SOP 在第三、四阶段会逐步分叉（方案 :141 S5「合同模板与法务条款清单（新建）」已现行业分叉苗头），若无「模板维护成本」判据，多客户铺开后维护成本失控时**没有客观信号**判断该不该上 Lens 叠加。**建议**：方案 §8 成功度量中增一行「模板维护成本（按客户类型分：模板数/近季改动次数/新增分支数/维护人时）」，口径对齐总览 §6.6，**先采集、后裁决**，不预设阈值。

- **E-4｜方案 §10「Q1–Q7」与借鉴总览 §6.5「Q1–Q18」编号体系冲突，需重编号或加前缀。** 方案 :288「## 10. 决策台账 Q1–Q7（2026-11-06 用户拍板）」，:291「**DECIDED**（用户 2026-11-06 拍板）」。两套编号**语义完全不同**（方案 Q1＝代号化边界；总览 Q1＝结果验收 vs 静态打分）。总览 §6.5 开头已声明「清单编号 #1–#40 不变」且是「本文档内的决议索引」；方案在自己的 §10 未声明编号独立性。**风险**：跨文档引用时会出现「Q1」歧义——例如「#15 的触发条件依赖 §6.6 数据」与「方案 Q1 已拍板」放在一起会被误读。**建议**：方案改为「D1–D7（Decision）」或加前缀（如「方案 Q-P1」），并在 §10 抬头显式声明「本节编号与借鉴总览 §6.5 的 Q1–Q18 无关」。

- **E-5｜风险：`agents/meetings` 桌面控制台（方案 §10 Q7 :370-380）被归入第一阶段「主线」，但其 UI 消费的服务端接口涉及 `agents/routes.py` 11 条 + `meetings/routes.py` 8 条，与 #12「外部文字禁入提示词」的渲染层加固、#31 的原件派生分层**在同一批 UI 上叠加**。**建议**：Q7 落地时**同 PR 附带 #12/#31 的渲染层断言**（总览 §5.2 已把 #12+#31 列为「合流实施」，成本 ≈1–2 人日），避免 UI 先上、边界后补导致两次返工。

- **E-6｜风险：方案 §4 S2 依赖的 G3（录音转写）实测结论是「MiniMax 官方 purpose 枚举无 file-extract/音频转写项」（:310），但方案把它推到「并行 · ASR 通道 另立项」（:392）。**该立项**不在借鉴总览任何条目覆盖范围内**（总览零命中 ASR/转写），且 §7 第四阶段「第二家编码智能体」与「ASR 通道」是两件事被并列在实施顺序表的最后一行。**建议**：明确 ASR 通道是「本方案自创新增项，需在 backlog 单独立条目」，并说明其与 #10「外部模型依赖契约」（✅ 已实施 #139）的**关系**——若 ASR 走外部模型服务，则 §10 的 M-1–M-7 七条规则**自动适用**（总览 :114「新增任一外部模型阶段时，同 PR 内须逐条对照 M-1–M-7」），方案 §5.2 的「凭据如何托管」只覆盖了 CLI 类接入，未覆盖 ASR 这类 API 类接入。**建议在 §5.2 增一行「ASR/其他 API 类外部服务的凭据托管与外部模型契约适用性」**。

- **E-7｜方案未处理「第二家编码智能体」的横向扩展判据，第四阶段仅给 5 条供应商选择标准（:251）。** §5.1 的统一适配器协议是**正确方向**，但方案未说明「第二家接入时，若其输出无法满足统一输出契约怎么办」——既有 `AgentRunResult.receipt_state`（B#2）已给出降级路径（`succeeded_but_receipt_invalid` + 不重跑），方案 §5.1 的协议清单里**缺 `receipt_state` 类似的降级面**。**建议**：§5.1 六方法协议补一条「降级面：回执面损坏时的独立终态」，并注明「沿用 B#2 已实施的 `receipt_state` 四态（`ok`/`no_output`/`files_without_manifest`/`manifest_invalid`），不新造」。

- **E-8｜方案 §11 :403 自认「G4（git/PR/CI/部署）当前台账无对应条目，建议新立」——但 #14「executor 对抗性测试组织」的前置是「决策逻辑抽纯函数重构（2-3 周）」，#16 需「配合 #14 落地后价值更大」。**若 G4 真要立项（git/PR/CI 编排），它会大量新增工作流节点类型与执行分支**，与 #14 的重构窗口**大概率同期**，届时 `workflows/executor.py` 会同时承受「G4 新节点类型」与「#14 固定种子夹具族」两重改动。**建议**：方案 §7 明确 G4 新立条目的**落点是否在 `workflows/` 包内**——若是，须在 §7 声明「G4 与 #14 的 executor 重构合并同一窗口」（对应总览 §5.6 纪律「合并实施不重复立项」），并同步说明新增的 pytest 需挂既有 `server-tests` job（**不新增 CI job**，参照 #37 的做法）。

---

**审查落点小结**：本方案在**架构方向、执行体不换、D/AI 不代拍板、复用而非另起**四个核心判断上与借鉴总览完全一致，这是它最大的优点；问题集中在**「没有对照借鉴总览就重新铺开了已经有裁决的事项」**这一条系统性缺陷上。P0 三项（#16 边界声明、第五阶段载体标注、#33 四列证据格式 + `docs/verification/`）都是**修订性**而非**推翻性**——改完之后方案可直接进入排期，不需要重做架构。P1 四项中，P1-4（模块边界裁决）与 P1-6（`handover_packages` 命名）属**必须在开工前定**，否则会形成不可逆的耦合与表名污染。

[Agent ID: agent-c39b1241-9303-4635-9f81-9e2124da28b7]