架构设计官评审意见

## A. 总评

方案在**架构方向上是成立的**：它没有重造已有的执行层（§2.1/§2.2 的现状校正逐条经我实测核对基本准确），"控制面（业务事实源）+ 执行面（agent 编排）+ 桥接层（缺口）"的三段划分与 V3 五层架构（`docs/architecture/蔡工FDE_Workbench_fde-v2架构融合审计与V3升级实施方案.md:69`）方向一致，Q1–Q4、Q6、Q7 七项决策经逐条实测复核**均与代码事实相符、无臆断**。**但方案存在一处对基准文献的事实性误判，和一处边界纪律越线。**

**最关键的一条**：方案的 **§10 Q5（`:341`–`:356`）把 DSH 与 zcode 放在"第二家编码智能体"的同一维度比较，并得出"DSH 不作为第二家"**，这与借鉴总览 **#20 裁决（§1:136）与 Q8 拍板（§6.5:677）不是同一件事**。总览 Q8 的决议原文是"**不立项自写 `fde-dsh-v1` 适配层、维持 `dsh_enabled=False`，但 #27 写成适配层立项书备选**"——即 DSH 的问题是"**要不要自写适配层**"，而不是"要不要当第二家编码器"。方案 Q5（`:343`）"DSH 不作为第二家编码智能体"与（`:356`）"DSH 若日后要承担编码执行，需先厘清与现有 AI Server 编排层的职责边界，另立架构决策"这两句，实际上把 #20 的"条件触发"降格成了"另立架构决策"，**回避了总览 Q8 已拍板的"写适配层立项书备选"这一具体动作**。这是本方案与基准之间唯一需要用户裁决的硬冲突（详见 C-1）。

第二个问题：**Q6（`:358`–`:368`）复用 openfde 做 git/worktree 编排，与借鉴总览 §0 核心裁决"只借鉴实现／不引入运行时／不融合平台"存在边界张力**。openfde 是**独立仓库、独立运行时（Node ≥22 + pnpm monorepo + better-sqlite3 逐 engagement SQLite）**，`packages/core/src/dispatch/executors.ts:141` 的 codex executor 在 `bypass` 档直接传 `--dangerously-bypass-approvals-and-sandbox`，**没有我方沙箱的容器隔离**（`server/src/fde_api/agents/sandbox.py:218`/`:287`）。方案 §5.3 自己写了"每次 run 独立容器／独立 worktree／默认 `--network none`"的红线（`:193`–`:194`），Q6 又要把执行面交给一个**无容器隔离的第二运行时**——这两条在同一份文档里互相拆台（详见 C-2）。

---

## B. 逐条比对表

| 借鉴总览要点 | 方案中的位置 | 判定 | 问题描述 / 证据 |
|---|---|---|---|
| **#1 跳数熔断**（已实施 #130） | 全文未提及；§3 架构图 `:119` 画 `PKG --> WF --> RUN` 链路 | **已一致**（无冲突） | 方案未提出任何绕过 hops 熔断的编排路径。实施证据：`fork/main:server/src/fde_api/workflows/executor.py:79` `MAX_RUN_HOPS = 8`、`:346` `if run.hops >= MAX_RUN_HOPS` → `:348` `"hops_exceeded"`。方案 §7 第三阶段"run 产物→交付包 + openfde 编排接入"若走 `wfnode-{行id}:{attempt}` 幂等键（`fork/main:AGENTS.md:38` T-W4 既有惯例），hops 仍继承不清零，无矛盾。 |
| **#2 回执终态**（已实施 #130，`succeeded_but_receipt_invalid`） | §2.2 `:65` 列 `retry_run`（幂等）；§4.2 `:163` 称"AgentToolCall 记 denied 但不记测试结论"；Q5 `:347` 称 zcode 有 `--resume <sessionId>` | **存在冲突** | 方案 §4.2（`:163`）在描述 run 产出缺口时**只提"没有 diff 与 test_results 结构化落库字段"，完全没提 #2 已落地的事务终态**；而 Q5（`:347`）把 zcode 的 `--resume` 直接当作"会话恢复"能力满足，实测 `D:/software/zcode/resources/glm/zcode.cjs` 中 `"--resume"` 存在**但无参数占位（`[["--resume"],0]`）**——即布尔开关而非 `<sessionId>` 取值。总览 §5.1:551 明确 #2 已实施且"实施时收窄到回执面损坏"，且 §6.5:696 已拍板"**不接 #2 增强档**，按 §6.6 做能力核查"。方案 §5.1 的 `cancel`/`health_check` 等新协议项也未说明如何与既有终态语义共存。 |
| **#3 审查不执行被审代码**（AGENTS.md 红线 #133 已落基线） | §4.2 `:158`–`:160` 要求每次 run 返回 `diff / test_results`；§5.3 `:198` 允许"安装依赖、访问外网、部署→人工审批" | **已一致** | 方案要求"AI 审查输入是 diff/文本快照"而非执行被审代码，与 `fork/main:AGENTS.md:13` 红线一致。§4.2 `:158` 明确产出是 `changed_files / diff / test_results`（文本/结构化快照），非"检出并运行"。**唯一需注意**：§4.2 的 `test_results` 由**执行侧**（沙箱内跑测试）产出，这与"审查不执行"不冲突（执行在被审代码自己的沙箱内、审查方只读 diff），但方案未显式区分这两者，建议补一句以免误读为"AI 审查跑客户测试"。 |
| **#4 purity 架构测试**（已实施 #130，`tests/test_architecture_purity.py`） | 全文未提及 | **已一致**（潜在风险） | 方案本身不违反现有 purity 边界（`fork/main:server/tests/test_architecture_purity.py` 钉 `workflows/`顶层不 import `control.service/routes`、`workflows/` 不读 `os.environ`/`current_app`、零"蔡工"字面量）。**但**：Q6 若把编排逻辑放进 `server/src/fde_api/` 的新模块并直接 `import`/调用 openfde CLI 或读 openfde 的 SQLite ledger，会触及"内核不读环境/不摸外部状态"的 purity 精神边界，且 §4.2 的 `diff/test_results` 落库若放在 `workflows/` 内核包会违反既有分层。建议方案补一行落点约束。 |
| **#6 状态归属与对账**（已实施 #131，《状态归属与对账-v1》+ 六跨层钉） | §3 架构图 `:118`–`:122`；§4 S6 `:142`；§7 第二/三阶段 `:243`–`:246` | **存在冲突** | 方案 §3 图把 `ART -.B2.-> PKG`（`:121`）画成 run 产物直接流向交付包、`SOL -.交付包快照.-> WF`（`:122`），**未标注任何权威/派生边界**。而《状态归属与对账-v1》§1 已明确四层归属不变量（`fork/main:docs/architecture/状态归属与对账-v1.md`）：`project_evidence` 不可变指纹三元组、**引用方永不复制真相只持指针**、`workflow_*` 版本行发布即冻结、documents快照"可重建"不落库。方案 §4.2（`:158`–`:160`）提出把 `diff / test_results / changed_files` **结构化落库到 `agent_artifacts`**——这正是"复制真相到引用方"的形态，与 #6 的"引用方永不复制真相，只持指针"不变量直接抵触。 |
| **#10 外部模型依赖契约成文** | 全文未提及 | **明显偏离** | 总览 §5.2:567 顺位 1＝#10（≈0.5 人日，纯文档，**本轮可排期**）。实施证据：`fork/feat/v3-external-model-contract` 分支提交 `a9eda14` 已落 `docs/architecture/外部模型依赖契约-v1.md`（**尚未合入 fork/main**，`git ls-tree fork/main docs/architecture/` 无此文件）。方案的 §5.2"接入三家前必须逐项确认"（`:179`–`:189`）正是**外部模型依赖契约**的同构内容（凭据托管／商用许可／版本钉死），但方案把它写成"接入前的必答项"而非"可复用的既有契约文档"，存在**重复立项风险**。 |
| **#11 门禁/检查器对抗性判据实施落点**（承接 #22） | §7 第一阶段 `:230`；§2.3 G2 `:79` | **存在冲突** | **G2 主张本身不成立**：方案 §2.3 G2（`:79`）称"presurvey 路由只有 source/list/create/detail/patch/revision/confirm/intake 八条，**未见独立的 S3 前置检查接口**"。实测 `server/src/fde_api/guidance/service.py:402` 有 `_require_s3_gate(session, project_id)`，且在 `:41`（`set_presurvey_source`）与 `:63`（`create_analysis`）**两处已实际调用**，未通过即抛 409 `presurvey_s3_gate_open`（`:412`–`:416`），文案与 G3 的 `evidence_checklist`（SOW-A 签署 / A 款预付到账 / 数据授权书四项勾选，见 `fork/main:server/seeds/gates.json` G3）逐项对应；`fork/main` 同文件同状。**S3 前置闸已落地，只是它是"闸内嵌式"而非独立路由**——方案的 G2 缺口结论与 §7 第一阶段第 3 项"presurvey 的 S3 前置闸落地"（`:230`）均据此需修正。 |
| **#12 外部文字禁入提示词硬边界** | §2.2 `:71`（脱敏渲染）；§5.3 `:196`（不挂真相层）；§9 红线 3 `:283` | **已一致** | 方案 §9 红线 3"执行面不可触真相层"与 §5.3"绝不挂真相层（`D:\test\FDE\…`）"与 #12 的"外部来源内容只入文件、提示词只放受控引用（路径+sha256）"方向一致；`fork/main:AGENTS.md:8` 红线"客户真实资料永不进 git 历史与远端"被方案正确继承。**但方案 §4.2（`:158`–`:160`）把 diff/test_results 直接落库，与 #12 的"渲染断言资料非指令"配套纪律（登记走 evidence 指纹）需对齐（见 #6 行）。 |
| **#13 统一到期表 + 审批主动超时** | §4 S6–S7 `:142`–`:143`；§3 图 `:120` `MTG -.强制门.-> WF` | **已一致** | 方案未提出第二套定时/到期机制；既有 `automation_approvals`（`(run_id, request_key)` 唯一 + `arguments_sha256` + 15min一次性 + 执行前再鉴权，方案 `:198` 已准确复述）继续作为唯一审批闸。方案 §5.3 明确"安装依赖、访问外网、部署→人工审批（`automation_approvals` 既有闸）"，未新建审批面。**注**：#13 本身仍是 `⬜ 待实施`（总览 §1:117），方案 §3 图 `:120` 把 `meetings` 作为"强制门"直接指向 workflow，需与 #13 的"审批主动超时"排期对齐，但方案未宣称已实现，故不判冲突。 |
| **#14 executor 对抗性测试组织** | 全文未提及 | **明显偏离** | 总览 §1:118 标 `⬜ 待实施`，且总览明示前置＝"决策逻辑抽纯函数（2–3 周重构）"。方案 §5.1（`:169`–`:177`）提出**统一适配器协议**（`prepare_workspace / validate_request / run / collect_result / cancel / health_check` 六方法），这正是 #14 的前置重构形态，但方案把它写成"扩展 `ZcodeAdapter`"（`:171`）的顺手工程，未识别其与 #14 的同源性与前置成本。实测现有 `server/src/fde_api/agents/adapter.py` 只有 `ZcodeAdapter.run`（`:119`）与 `_judge_tool_call`（`:195`），**六方法中5 个不存在**。 |
| **#19 明确不做清单（负向登记）** | 全文未提及；§7 第五阶段 `:255` 含"CI/CD、部署审批、回滚、运行监控、线上问题反馈、交付物模板化、Skill 化、插件市场" | **明显偏离** | 总览 §1:135 标 `⬜ 待实施（负向登记）`，用途是"登记『不做+理由』防后续重复立项"。方案 §7 第五阶段（`:253`–`:255`）一次性把 **8 项**（CI/CD、部署审批、回滚、运行监控、线上问题反馈、交付物模板化、Skill 化、插件市场）列为路线，且 §7 第五阶段与 §11 文档关系表（`:398`–`:404`）**均未对 #19/#26/#40 三份负向清单做交叉核对**。其中"Skill 化"与 #36/#37（技能结构化契约 + 自洽校验，已实施/待合入）重叠、"插件市场"与 `dsh_market_*`（`fork/main:server/src/fde_api/config.py:79`–`:82`，独立市场注册表）重叠，均有二次立项风险。 |
| **#20 DSH 替代内评（条件触发）** | §10 Q5 `:341`–`:356`；§2.1 `:53`；§7 第三/四阶段 `:390`–`:391` | **存在冲突** | 见 A段与 C-1。核心：总览 §6.5 Q8（`:677`）拍板"不立项自写 `fde-dsh-v1` 适配层、维持 `dsh_enabled=False`，但 **#27 写成适配层立项书备选**"，§5.1:557 记 #27"v1 落盘（**按 Q8 补「立项书备选」章节**）"。方案 Q5（`:343`）"DSH 不作为第二家编码智能体"、`:356`"DSH 若日后要承担编码执行…另立架构决策"，**只否了"编码执行"这个从未被拍板的方向，完全未提"适配层立项书备选"**。而已落盘的 `fork/main:docs/architecture/DSH-适配层决策记录-v1.md` §6 原文确写"P1（**协议适配层立项**）…维持条件触发"（`:48`）。方案 §2.1（`:53`）称"DSH 是否真在本机环境启用属运行态，文档不作断言"——但 `fork/main:server/src/fde_api/config.py:80` `dsh_enabled: bool = False` 是**代码事实**（非运行态），且 `.env.example` 无任何 dsh 条目（实测 `grep -in dsh .env.example` 零命中）——此处表述可更硬。 |
| **#21 交付效果评测协议 v0**（已实施 #128+#131） | §3 图 `:122` `SOL -.交付包快照.-> WF`；§4 S7 `:143`；§8 成功度量 `:259`–`:269` | **已一致**（但遗漏一处） | 方案 §8 成功度量表（`:261`–`:269`）的指标（"一次通过率""人工返工率""智能体产物被人工接受率""交付毛利率"）**全部是过程/效率指标，没有一条是结果验收指标**（业务 KPI 改善度）。而总览 §1:98 的 #21 是"交付效果"算分协议（`uplift = (kpi − kpi_baseline)/(kpi_oracle − kpi_baseline)`、PASS=0.8 截断、`incidents→uplift≤0`、无 oracle不得出分），且 **#21 已接线进 G9 `exit_condition`**（`fork/main:server/seeds/gates.json` G9：`验收线达成 ≔ uplift_bounded ≥ 0.8 ∧ incidents = ∅ ∧ 三锚四反例全过`）。方案 §8 的北极星（`:273`）"智能体不能越权修改、不能部署、不能自动过门"是**纪律北极星**，不是结果验收北极星——两者不冲突，但方案 §8 完全未提 G9 已有的结果验收口径，属**遗漏而非矛盾**。 |
| **#22 门禁判据升格（三锚点 + 四类反例）**（已实施 #128） | §9 红线 `:279`–`:284`；§8 `:271`–`:273` | **已一致** | 方案 §9 四条红线（AI 不代拍板 / AI 不出法律条款 / 执行面不可触真相层 / 售前不得代客户拍板）与 #22 的"检查器空转 ≠ 守住"精神一致；§7 第一阶段出口指标（`:235`）"每一步都有来源、版本、责任人和证据"与 #29 验收合同"指标溯源"一致。方案未新增任何弱于三锚四反例的检查器口径。**建议**：§8 度量表可增一列"是否可反证"，接入 #22 已有判据文本（`fork/main:docs/architecture/交付效果评测协议-v0.md` §3）。 |
| **#26 fde-gym 专属不做清单（负向登记）** | 全文未提及 | **明显偏离** | 与 #19 同理。方案 §7 第五阶段（`:255`）"CI/CD、部署审批、回滚、运行监控"与 #25（封存永锁，`:137` 明确"变体体系 + 每 run 一容器"永锁）的边界需要显式隔离；§4.2（`:163`）要求落库 `test_results`、§4 S7（`:143`）"CI → 人工代码审查"这些动作若被理解为"我方要建评测夹具/容器评测"，会撞 #25 永锁与 #3 红线。方案未做此声明。 |
| **#27 DSH 适配层决策记录**（已实施 #128） | §10 Q5 `:345`–`:356`；§2.1 `:53`；§2.3 G5 `:82` | **明显偏离** | 方案 §2.1（`:53`）称 DSH"**已有 enabled/runtime_version 抽象与健康回报**"，引 `control/dsh_runtime.py:36,45-53`、`control/mcp_gateway.py:217` 回报 `ai_server_enabled`/`runtime_version`。实测：`fork/main:server/src/fde_api/control/dsh_runtime.py:1` 文档头确为"Versioned client for the separately deployed DeepSeek Harness adapter"、`:39` `class DSHRuntimeClient`、`:45`–`:53` 构造参数含 `runtime_version`/`protocol_version`——**方案的这部分准确**。但方案**完全没有引用已落盘的决策记录本身**（`fork/main:docs/architecture/DSH-适配层决策记录-v1.md`，含 §2 四条事实基线、§3 适配层必写清单、§4 lock 八字段 + 三方合并升级法、§5 安全前置四条）。**最关键**：§5 安全前置第 2 条已实测 `sdk-minimal` **pins `danger-full-access`**、`session-log-deepseek` **默认上传未接受的日志事件**（≤8 MiB/请求）⇒ "接客户资料＝绝对禁止"。方案 Q5（`:349`）已正确指出 DSH 是"AI Server 编排层（工具调用、审批、预算记账）"，但**未引用这条安全前置**，也未说明 DSH 未来若启用会把**客户资料**置于"可执行模型生成代码 + 默认上传日志"的运行时前。 |
| **#28 门禁精确 revision CAS**（已实施 #130） | §4 S7 `:143`；§3 图 `:120`；§2.2 `:62` | **已一致** | 方案 §4 S7（`:143`）的 S7 阶段串"run 产物 → diff/测试/制品/风险/成本 → CI → 人工代码审查 → 客户演示 → 人工验收 → 产物登记 → 门禁证据提交 → 人工核验 accepted"与 #28 门禁 CAS 无矛盾；方案未提出绕过 `expected_revision` 的路径。**注**：#28 桌面接线维持 blocked（总览 §6.5 R3，`:667`），而方案 §7 第二阶段（`:237`–`:241`）要做桌面端交付看板——若该看板涉及门禁操作，须避开 `GateBoard.tsx` 品牌轮冻结区（`desktop/src/renderer/src/` 下无 `gate` 目录，GateBoard 在冻结区）。方案未提及此约束。 |
| **#29 验证/验收合同契约**（已实施 #128） | §3.1 `:129`（法务条款清单）；§4.2 `:155`–`:163`；§8 `:259`–`:273` | **已一致** | 方案 §3.1（`:129`）"AI 可以做检查清单与缺项提示，不能自行改写这些条款"与 #29 §4 五点（尤其第 3 点"人工接受不粉饰，保留真实 NOT_RUN/FAIL、证据缺口、数值与说明"）方向一致；方案 §9 红线 2（`:282`）"AI 不出法律条款"与 Q4 决策（`:330`–`:339`）"工作台只存指针与缺项检查"完全对齐。**注**：#29 第 5 点"精确操作一律拒绝过期摘要（15min 窗）"在方案中无对应——方案的"冻结 SOW"（`:233`）是版本不可变，与摘要过期语义不同源，不冲突。 |
| **#33 文档职责分层 + 验证证据格式**（⬜ 待实施） | §11 文档关系表 `:396`–`:404`；全文证据引用格式 | **明显偏离** | 总览 §1:139：#33 的落点是"写进我方 `AGENTS.md`：新建 `docs/verification/` 目录与证据模板（**命令／退出码／可观察结果／未验证项四列**）；审查／评估类报告的**证据索引统一采用该格式**；台账 Task 勾选须附最窄验证命令"。**实测 `docs/verification/` 目录不存在**（`ls docs/verification` → NOT EXIST），#33 仍是 `⬜ 待实施`。而本方案正是一份"审查／评估类报告"，其 §2 全部证据（`:49`–`:85`）与 §10全部决策依据（`:293`–`:380`）采用**"文件:行号 + 结论"**格式，**无"可观察结果／未验证项"四列结构**，与 #33 待立的目标格式不一致。方案也未引用该条。**注**：这不是"违反"——#33 未落地，格式尚未强制——但方案作为新产出的评审/方案文档，正是 #33 声明要覆盖的形态类型。 |
| **§7 许可硬条款**（#35 已落基线，`fork/main:AGENTS.md:14`） | 全文**零次**提及（`grep -n "借鉴\|开源\|autoloop\|fde-gym\|FF-\|许可\|LICENSE\|AGPL"` 仅命中 `:129` 一处，且是"第三方软件与开源许可"这句**业务合同条款**，与许可硬条款无关） | **存在冲突**（文档级） | 方案 §5.1（`:171`）"扩展它，而不是另起一套"、§5.2（`:189`）"已有先例：`docs/试点前联调-iptables与zcodeCLI-检查单.md` 要求钉死 zcode CLI 版本 + 二进制 sha256，防供应链漂移"、§7 第三阶段（`:390`）"版本钉死与 sha256 校验沿用"——这些是**我方自己**的供应链纪律，与**第三方开源材料的许可纪律**是两件事。方案 Q6（`:358`–`:368`）要复用 **openfde**（第三方 MIT 仓库，`D:/test/FDE/openfde/LICENSE` 首行 "MIT License"、`:3` "Copyright (c) 2026 Ziboyan Wang"）作为编排层——这在许可上**无障碍**（MIT），但方案**未做任何出处登记**（版本/许可/快照日期），而 §7 硬条款第 4 条要求"引用第三方材料前登记确切版本、许可、出处**与快照日期**；远端出现 LICENSE 或 HEAD 变动即复核；**停更超 30 天的本地快照失效重核**"。实测 openfde 最后提交 `a54be6c 2026-10-27`，距今2026-11-06 为 **10 天**，未超 30 天 ✅；但**未登记**。 |
| **§5.6 纪律（实施偏差须回写 / 禁二次立项）** | §10 决策台账 `:288`–`:291`；§11 文档关系表 `:396`–`:404` | **存在冲突** | 方案 §10 抬头（`:291`）自订"**状态：DECIDED（用户 2026-11-06 拍板）。实现偏差须回写本节**"——这只回写方案自身，**未回写 `docs/implementation/v3-backlog.md` 与借鉴总览 §1 状态列**（总览 §5.6:603 原文要求两处都回写；§1:3 明确"实施状态以 fork/main 的 `v3-backlog.md` 为准"）。更实质的问题在 §11（`:396`–`:404`）：文档关系表把 `docs/implementation/v3-backlog.md` 描述为"V3 任务台账。G4（git/PR/CI/部署）**当前台账无对应条目**，建议新立"——**这是二次立项的直接候选**。总览 §1 的跨项目合并原则表（`:143`–`:156`）与 §5.6（`:601`–`:605`）的核心纪律是"所有借鉴项走既有流程（feature 分支→PR→4 CI job→合并）；**实施偏差须回写**"，方案在 §11 提出"建议新立"却未说明它与 §5.2 本轮可排期三项（#10 / #9 / #7）及 §5.4 第二批（#7–#14、#30、#31、#32、#36、#37）的关系。**另**：方案 §2.3 G4（`:81`）称"服务端无 git/worktree/PR/CI/部署编排"并作为"该投钱的地方"，但 §11 同时说"当前台账无对应条目，建议新立"——**新增工作项未走 backlog 登记流程**。 |
| **§0 核心裁决「只借鉴实现／不引入运行时／不融合平台」** | §10 Q6 `:358`–`:368`；§7 第三阶段 `:243`–`:247` | **存在冲突** | 见 C-2。openfde 不是"借鉴实现"，而是**把另一个运行时接进来当执行面**：`D:/test/FDE/openfde/package.json` `"name": "openfde-monorepo"`、`"engines": {"node": ">=22"}`、monorepo（`packages/core`、`apps/cli`）；`packages/core/src/dispatch/executors.ts:141` codex 在 `bypass` 档传 `--dangerously-bypass-approvals-and-sandbox`；`packages/core/src/dispatch/runner.ts:163`–`:172` 在**宿主进程**里 `resolve(options.repo)` + `ensureWorktree` + `spawn`——**无容器、无网络隔离**。我方沙箱基线是 `server/src/fde_api/agents/sandbox.py:218`（per-run 容器）+ `compose.yaml:142`–`:145`（`privileged: false` / `network_mode: none` / `tmpfs /workspace:size=512m`）。方案 §5.3（`:193`）自己写"每次 run 独立容器／独立 worktree；**只挂 workspace**"与"默认 `--network none`"，Q6 却把执行交给无此隔离的第二运行时 ⇒ **同一文档内的红线自我拆台**。 |

---

## C. 必须修改项

### P0-1｜Q5 对 DSH 的处置与总览 Q8 拍板不一致，需用户裁决

**问题**：方案 §10 Q5（`:343`、`:356`）以"DSH 不作为第二家编码智能体"结案，把 DSH 议题**重定向到"是否当编码执行器"**。但总览 §6.5 Q8（`:677`）的实际拍板是"**不立项自写 `fde-dsh-v1` 适配层、维持 `dsh_enabled=False`，但 #27 写成适配层立项书备选**"，且 §5.1:557 记 "#27 v1 落盘（按 Q8 补「立项书备选」章节）"。已落盘的 `fork/main:docs/architecture/DSH-适配层决策记录-v1.md:48` 原文亦为"P1（**协议适配层立项**）与 P2（zcode/codex 编程类后端）维持条件触发"。方案 §10 Q5 未提"适配层立项书备选"这一具体动作，等于把已拍板的一项产出省略掉了。

**证据**：
- 方案 `:343`「**DSH 不作为第二家编码智能体**」、`:356`「DSH 若日后要承担编码执行，需先厘清与现有 AI Server 编排层的职责边界，另立架构决策，不在本轮范围。」
- 总览 `:677` Q8 决议行：「**推进门禁包**：不立项自写 `fde-dsh-v1` 适配层、维持 `dsh_enabled=False`，但 **#27 写成适配层立项书备选**」
- 总览 `:557`：「**#27** DSH 适配层决策记录｜#128｜v1 落盘（**按 Q8 补「立项书备选」章节**）」
- `fork/main:docs/architecture/DSH-适配层决策记录-v1.md:48`：「P1（**协议适配层立项**）与 P2（zcode/codex 编程类后端）维持条件触发，触发=用户澄清具体自动化诉求环节。」

**建议改法**：**待澄清：方案与总览 Q8 冲突，建议由用户裁决，理由是——**（1）方案的 Q5 结论"DSH 不作第二家"与 Q8 拍板并不矛盾，二者谈的是不同问题（执行器位置 vs 适配层立项），但方案把 Q5标为"DECIDED ✅"会造成"DSH 议题已结案"的误导；（2）Q8 的产出义务（#27 补"适配层立项书备选"章节）在方案 §10 无对应项，方案未回写该产出；（3）方案 §2.1（`:53`）"DSH 是否真在本机环境启用属运行态，文档不作断言"可更硬——`fork/main:server/src/fde_api/config.py:80` `dsh_enabled: bool = False` 是代码事实，`.env.example` 无 dsh 条目。建议在 Q5 中增一段"与总览 Q8 的关系"：明确引用 Q8 三要素（不立项适配层 / 维持 `dsh_enabled=False` / #27 写成立项书备选），并把 §5.1（`:53`）改为"配置默认关闭"而非"运行态未确认"。

---

### P0-2｜Q6 复用 openfde 编排与「不引入运行时」裁决及方案自身 §5.3 红线冲突

**问题**：Q6（`:360`）"不自建 git/worktree/PR 逻辑……openfde 负责 worktree / agent 进程 / 权限档位"、落地约束（`:368`）"依赖 openfde 常驻可用"。这把一个**独立 Node 运行时**接成执行面，与总览 §0 核心裁决"**只借鉴实现，不引入运行时**"（`:38` 对 FF 的裁决措辞，`:77` 复述）以及 §2.9 对技能库的"**不引入文件权威／CLI／第二运行时**"（`:39`）构成边界张力。更直接的是：**方案 §5.3 自己规定的执行隔离红线，openfde 不满足**。

**证据**：
- 方案 `:193`「每次 run 独立容器 / 独立 worktree；**只挂 workspace**」、`:194`「默认 `--network none`」
- 我方沙箱：`server/src/fde_api/agents/sandbox.py:218`（`create` per-run 容器）、`:287`（`exec_argv` 凭据经 `docker exec -e` 注入）、`:266`（`--network` 参数化）、`compose.yaml:142`–`:145`（`privileged: false` / `network_mode: none` / `tmpfs /workspace:size=512m`）
- openfde：`D:/test/FDE/openfde/packages/core/src/dispatch/runner.ts:163`–`:172`（宿主进程 `resolve(repo)` + `ensureWorktree` + `spawn`，**无容器**）；`packages/core/src/dispatch/executors.ts:141`「`args.push("--dangerously-bypass-approvals-and-sandbox")`」（codex bypass 档**显式关闭沙箱**）；`packages/core/src/dispatch/executors.ts:60`「`CLAUDE_ALLOWED_TOOLS = ["Bash(openfde:*)", "Bash(git:*)", "Read", "Grep", "Glob", "Edit", "Write"]`」（允许任意 Bash）；`D:/test/FDE/openfde/package.json` `"engines": {"node": ">=22"}`
- 边界纪律：总览 `:38`「只借鉴实现，不引入运行时」、`:39`「不引入文件权威／CLI／第二运行时」、`:71`「AGH＝**第二运行时冲突**」
- 我方既有纪律：`fork/main:AGENTS.md:11`「`scripts/bridge-poll.mjs` 只读纪律：只调 openfde **只读 CLI** + 读文件，**绝不写真相层**」；`scripts/bridge-poll.mjs:9`–`:10`「只读纪律：本脚本只调 openfde 只读命令（engagement list / status）+ 读文件，绝不写真相层；**写命令（remember/ingest/log/debrief）不在采集器白名单内**」
- 依赖未声明：`package.json` 无 openfde 依赖项；`server/pyproject.toml:11`–`:26` 依赖清单无 openfde；`compose.yaml` 无 openfde 服务条目（方案 `:368` 已自认"本仓库 compose 无 openfde 服务条目"，但未解决依赖声明问题）

**建议改法**：**待澄清：方案与总览 §0「不引入运行时」冲突，建议由用户裁决，理由是——** Q6 触碰的是总览 §0 一级边界（引入第二运行时），不是普通实现细节；但我**不直接推荐**任何替代做法（既不推荐自建，也不推荐换用其他编排层）。建议方案在 Q6 落地约束中补齐三项裁决所需信息，交给用户拍板：(a) openfde 的执行体是否必须受我方沙箱纪律约束（断网 / 容器 / 单挂载）——若"是"，则 openfde 需被改造或只用作**纯 git/worktree 库**而非执行体；(b) 若 Q6 成立，openfde 的版本/许可/快照日期须按 §7 硬条款第 4 条登记（实测 MIT、HEAD `a54be6c` 2026-10-27、快照未超 30 天）；(c) openfde 与 `fde-dsh-v1` 适配层（#20/#27）在本仓的**运行时排他**关系需写明——我方已有 `control/dsh_runtime.py` 一个"单独部署的 Harness 适配器"位置，Q6 再引入一个常驻 Node 运行时，二者的边界需要一句裁决。

---

### P0-3｜§2.3 G2 与 §7 第一阶段第 3 项的缺口结论不成立（S3 前置闸已落地）

**问题**：方案 §2.3 G2（`:79`）断言"presurvey 路由只有 source/list/create/detail/patch/revision/confirm/intake 八条，**未见独立的 S3 前置检查接口**"，并据此把"presurvey 的 S3 前置闸落地"列为 §7 第一阶段第 3 项（`:230`）与 §4 S6（`:142`）缺口。实测该闸**已落地并已接入两条调用路径**，只是实现形态是"服务层内嵌闸"而非"独立路由"。

**证据**：
- `server/src/fde_api/guidance/service.py:402`–`:416`：`def _require_s3_gate(session, project_id)`，`:410` 查 `Gate.gate_key == "G3"`、`:411` `if gate is None or gate.status != "passed"` → `:412` 抛 `GuidanceServiceError("presurvey_s3_gate_open", "需先通过 G3 诊断开工门（SOW-A 签署、A 款到账、数据授权书四项勾选），才能上传预调研文件或发起 AI 分析。", 409)`
- 调用点：同文件 `:41`（`set_presurvey_source`）与 `:63`（`create_analysis`）——**两个入口都被闸住**；`fork/main` 同文件同状（`:41`/`:63`/`:402`）
- 门禁种子：`fork/main:server/seeds/gates.json` G3 `exit_condition: "三件套齐全"`、`evidence_checklist: ["诊断报告（数字全 claimed）", "SOW-A 签署", "A 款预付到账", "数据授权书四项勾选"]`、`contract_payment: "SOW-A 签署 + A 款预付到账 + 数据授权书四项勾选"`、`decision_semantics: ["pass","fail"]`（无 conditional_pass）

**建议改法**：把 §2.3 G2 从"缺口"降级为"**已落地但缺 UI 入口**"（与 G1 同一形态），并把 §7 第一阶段第 3 项改为"**S3 前置闸的桌面端提示与拦截反馈**"（如给出 G3 未通过时的可读原因与跳转），不再列为"落地"。§2.1 "原对话现状大面积过时"的整体结论不受影响——该结论已被 §2.1 的其他条目独立支撑。

---

### P1-1｜§4.2 的产物结构化落库与 #6 状态归属不变量抵触

**问题**：方案 §4.2（`:155`–`:163`）要求每次 run 返回并落库 `changed_files / diff / test_results / build_results / lint / security_scan / known_risks / artifact_references / logs`，并在 §7 第三阶段（`:245`）明确"`agent_artifacts` 增加 diff / test_results 结构化字段"。这与 #6《状态归属与对账-v1》§1 的不变量"**引用方永不复制真相，只持指针**"冲突。

**证据**：
- `fork/main:docs/architecture/状态归属与对账-v1.md` §1 第 1 行：`project_evidence` 真相持有方 = 指纹三元组，**"引用方永不复制真相，只持指针；证据原件永不入库"**；`workflow_*` 行 = "发布即冻结、版本行不可变"，"run 随时可从版本行重装同一张图"；documents = "纯读派生快照，**不落库**"
- 既有产物模型：`server/src/fde_api/agents/models.py:137` `storage_ref: Mapped[str] = mapped_column(String(255), nullable=False)` + `:138` `sha256`——**现有设计就是指针 + 指纹**，`:136` 注释明写"# source_uri 风格指针（证据原件留在项目工作目录，不进仓库/数据库）"
- 方案 §4.2 原文（`:163`）：「现有 `agent_artifacts` 有 sha256，但**没有 diff 与 test_results 的结构化落库字段**」

**建议改法**：把 §4.2 的落库形态改为**指针 + 指纹 + 可重建派生**三件套：`storage_ref` 指向 diff/test_results 原件（留项目工作目录）、`sha256` 记录指纹、结构化摘要（如 `test_results` 的 passed/failed 计数与退出码）作为**可从原件重建的派生**。同时在 §4.2 增一行显式声明"diff/test_results 属执行侧产出，**审查侧只读快照不执行被审代码**"，避免与 #3 红线产生阅读歧义（#3 已落 `fork/main:AGENTS.md:13`）。

---

### P1-2｜§2.2 与 §10 Q5 未标出 #2 已落地终态，且 zcode `--resume` 能力表述不实

**问题**：方案 §2.2（`:65`）把 `retry_run`（幂等）列为既有能力、§4.2（`:163`）描述 run 产出缺口时**完全未提 #2 的独立终态 `succeeded_but_receipt_invalid`**；§10 Q5（`:347`）把 zcode 的 `--resume <sessionId>` 当作已满足的"会话恢复"要件。

**证据**：
- #2 已实施：`fork/main:server/src/fde_api/agents/models.py:66` status CHECK 含 `"succeeded_but_receipt_invalid"`；`fork/main:server/src/fde_api/agents/service.py:472` `run.status = "succeeded_but_receipt_invalid"`；总览 `:551`「**#2** 回执终态｜#130｜`succeeded_but_receipt_invalid` 独立终态（实施时收窄到「回执面损坏」）」
- 总览 §6.5:696「zcode CLI 会话续接｜**不接 #2 增强档**｜按 §6.6 做能力核查；#2 已实施且以 repair 降级路径为默认」；§6.6:709 采集项「zcode CLI 会话续接｜平台 owner｜评审日 +14 天｜…**三项全支持**才启用 #2 repair 增强档，否则维持降级路径」
- 实测 zcode：`D:/software/zcode/resources/glm/zcode.cjs` 中 `"--resume"` 出现为 `[["--resume"],0]`——**布尔开关，无 `<sessionId>` 取值**；方案 `:347` 写「`--resume <sessionId>`」不准确（对照：`executors.ts` 中 claude 是 `args.push("--resume", input.resumeSessionId)` 带值）

**建议改法**：§2.2 增加一行"回执面损坏独立终态 `succeeded_but_receipt_invalid`（#2 已实施）"；§4.2 的产出缺口表述与该终态对齐；Q5 把 `--resume` 改为"**存在 `--resume` 开关（无 sessionId 取值）**"，并按 §6.6 口径标注"zcode 会话续接能力核查未完成 ⇒ #2 repair 增强档维持降级路径"（总览 §6.6 采集项 owner＝平台 owner、截止＝评审日+14 天）。

---

### P1-3｜§7 第五阶段与 §11 "建议新立" 未对负向清单与 backlog 登记纪律做交叉核对

**问题**：§7 第五阶段（`:253`–`:255`）一次性铺开 8 项；§11（`:403`）对 `v3-backlog.md` 写"G4（git/PR/CI/部署）**当前台账无对应条目，建议新立**"。这与 §5.6 纪律（`总览:601`–`:605`："所有借鉴项走既有流程…**实施偏差须回写 `v3-backlog.md` 与本清单**"）以及 §5.2/§5.4 已排期清单存在二次立项风险。

**证据**：
- 方案 `:255`「CI/CD、部署审批、回滚、运行监控、线上问题反馈、交付物模板化、Skill 化、插件市场」
- 方案 `:403`「`docs/implementation/v3-backlog.md`｜V3 任务台账。G4（git/PR/CI/部署）**当前台账无对应条目**，建议新立」
- 总览 `:135` #19、`:138` #26、`:141` #40 三份"不做清单"均 `⬜ 待实施（负向登记）`，用途是"防后续重复立项"
- 已在册的重叠项：#36 技能结构化契约（`fork/main:docs/implementation/v3-backlog.md` B#36）、#37 技能自洽校验（B#37）、`dsh_market_*` 插件市场（`fork/main:server/src/fde_api/config.py:79`–`:82`）、#33 文档职责分层（`总览:139`）
- 状态核对：实测 `git show fork/main:docs/implementation/v3-backlog.md | grep "worktree\|git 编排\|PR 编排\|CI 编排\|G4"` **零命中**——方案"台账无对应条目"的判断**成立**

**建议改法**：§7 第五阶段拆为两栏——「已登记待排期（挂 backlog B# 编号）」与「**未登记·需先走 backlog 登记轮**」；对"Skill 化"标注"挂 B#36/B#37"、对"插件市场"标注"挂 `dsh_market_*` 既有配置面"；§11 的"建议新立"改为"**待登记**（走 feature→PR→4 CI 的 backlog 登记轮，与 §5.2/§5.4 合并）"。§10 抬头（`:291`）的"实现偏差须回写本节"应补"**并回写 `docs/implementation/v3-backlog.md` 与借鉴总览 §1 状态列**"。

---

### P1-4｜§5.1 统一适配器协议未识别与 #14 的同源前置

**问题**：§5.1（`:169`–`:177`）提出六方法适配器协议，但未识别这正是 #14 的前置重构（总览 §1:118 标"前置＝决策逻辑抽纯函数（**2–3 周重构**）"），也未说明与 #2 终态、#4 purity 边界的共存。

**证据**：
- 方案 `:174`「`prepare_workspace · validate_request · run · collect_result · cancel · health_check`」
- 现状：`server/src/fde_api/agents/adapter.py` 仅 `ZcodeAdapter.run`（`:119`）与 `_judge_tool_call`（`:195`），**六方法中 5 个不存在**；`AgentRunResult`（`:66`–`:76`）字段为 `status/exit_code/token_cost/duration_ms/artifacts/tool_calls/degraded/degraded_reason`——**已含 cancel/degrade语义**
- 总览 `:118` #14「⬜ 待实施｜…｜**前置：决策逻辑抽纯函数（2–3 周重构）**」

**建议改法**：§5.1 增加一行"本节六方法协议与 B#14（executor 对抗性测试组织）的前置重构同源 ⇒ 合并实施，避免二次立项；本轮 §7 第三阶段只做 zcode 单适配器落地，不预支协议抽象"。**不推荐**改变 §5.1 的协议设计本身。

---

## D. 可选优化项

1. **§8 成功度量表增"结果验收"一栏**：现表 7 类指标全为过程/效率口径。G9 `exit_condition` 已挂 `uplift_bounded ≥ 0.8 ∧ incidents = ∅ ∧ 三锚四反例全过`（`fork/main:server/seeds/gates.json`），可加一行"结果验收：G9 验收线达成率（口径见《交付效果评测协议-v0》；阈值 0.8 为**占位·待我方数据校准**）"。注意总览 R4（`:668`）要求阈值标占位，不得当正式 PASS 线。

2. **§4 S6/S7 补 #28 桌面接线约束**：`GateBoard.expected_revision` 接线维持 blocked（总览 R3 `:667`，判据＝品牌轮 PR 合入）。若 §7 第二阶段的"交付看板"涉及门禁操作，须避开 `desktop/src/renderer/src/` 品牌轮冻结区。

3. **§10 Q5 补 DSH 安全前置引用**：`fork/main:docs/architecture/DSH-适配层决策记录-v1.md` §5 第 2 条已实测官方 SDK 两个红线级默认值（`sdk-minimal` pins `danger-full-access`、`session-log-deepseek` 默认上传日志）。方案 Q5 已正确指出 DSH 是"AI Server 编排层"，补一句这条能显著提升"DSH 未来若接客户资料为何仍需前置"的判断质量。

4. **§5.1/§5.2 引用已存在的 #10 外部模型依赖契约**：`fork/feat/v3-external-model-contract`（`a9eda14`）已落 `docs/architecture/外部模型依赖契约-v1.md`（未合入 fork/main）。方案 §5.2 的"接入三家前必须逐项确认"表与该契约同构，引用可省一次重复写作。

5. **§11文档关系表补两条已落盘文档**：《DSH-适配层决策记录-v1》《交付效果评测协议-v0》《状态归属与对账-v1》均在 `fork/main:docs/architecture/` 下，方案 §11（`:398`–`:404`）只列了 4 份文档，遗漏了这三份——而 Q5/Q8 的裁决正依赖它们。

6. **§9 红线清单补一条"产出形态纪律"**：`agent_artifacts` 新增列只能是**指针 + 指纹 + 可重建派生**，不得复制 diff/test_results 原件进库（与 #6 一致，见 P1-1）。

7. **§5.3 补 #3 红线的显式引用**：`fork/main:AGENTS.md:13`「AI 审查不执行被审代码——AI 审查/评审的输入只能是 diff/文本快照；不得检出、不运行被审交付的代码、测试、配置或 hooks」。方案 §4.2 要求 run 产出 diff/test_results，是 #3 的**适用前提**，引用一句能同时满足 #3 与 #6 的双重对齐。

---

## E. 待澄清的开放问题与风险清单

| # | 待澄清项 | 为什么必须由用户/owner 裁决 | 依据与证据 |
|---|---|---|---|
| E-1 | **Q6 是否构成"引入第二运行时"** | 这是借鉴总览 §0 一级边界（"只借鉴实现，不引入运行时"），不是实现细节。openfde 是独立 Node ≥22 monorepo 运行时，host 进程 spawn、无容器隔离、codex bypass 档显式关沙箱。裁决方向不同 ⇒ 实施形态完全不同。 | 总览 `:38`/`:77`；`D:/test/FDE/openfde/package.json`；`packages/core/src/dispatch/runner.ts:163`–`:172`；`packages/core/src/dispatch/executors.ts:141` |
| E-2 | **Q5 的 DSH 处置是否已结案** | 总览 Q8 已拍板"不立项适配层 + 维持 `dsh_enabled=False` + #27 写成立项书备选"，方案 Q5 却标 DECIDED 且未提"立项书备选"。是"补写 Q8 三要素"还是"重拍 DSH 议题"，须用户定。 | 总览 `:677`、`:557`；`fork/main:docs/architecture/DSH-适配层决策记录-v1.md:48` |
| E-3 | **openfde 作为执行体时，我方沙箱红线是否仍然成立** | 若"不成立"，等于 §5.3（`:191`–`:198`）整节红线被 Q6 架空；若"成立"，openfde 需被改造或降级为纯 git/worktree 库。两种结局对工作量差一个量级。 | 方案 `:193`–`:194` vs `:360`；`agents/sandbox.py:218`/`:287` vs `executors.ts:141` |
| E-4 | **openfde 是否违反既有"只读"边界纪律** | 我方对 openfde 的既有契约是**只读**（`fork/main:AGENTS.md:11`、`scripts/bridge-poll.mjs:9`–`:10` 明确写命令不在白名单）。Q6 要求 openfde **写** worktree/branch/run——这是边界扩张，须显式授权并写进 AGENTS.md 红线。 | `fork/main:AGENTS.md:11`；`scripts/bridge-poll.mjs:9`–`:10`；`packages/core/src/dispatch/runner.ts:161`–`:200`（写 task 状态 + worktree） |
| E-5 | **Q3 能力分级与调研表三态权限存在实质冲突** | Q3（`:315`–`:328`）定"独立售前 = fde_engineer + member，可确认事实"，但调研表 confirm/reject/revise 三态**强制 `can_manage`**（admin 或项目负责人且 role≥project_lead）；`project_access` 对 member 一律返回 `can_manage=False`。若"独立售前"不具 can_manage，则 Q3 表中"确认事实"能力**在现有服务端实现下不可用**。 | 方案 `:322`–`:325`；`server/src/fde_api/research/form_service.py:972`–`:974` `_require_confirm` → `project_access(...).can_manage` 403；`server/src/fde_api/projects/permissions.py:32`–`:41`（member 恒 `can_manage=False`）；`server/src/fde_api/research/project_routes.py:463`–`:505`（三态路由）；台账 `docs/后续需求台账-F5与D11.md:29` 亦记"权限=项目负责人+admin" |
| E-6 | **`delivery_package` 与既有 `delivery_packages` 表的语义重名** | 方案 §7（`:246`）与 §2.3 G7（`:84`）多处用 `delivery_package` 指"结项交付包"，而既有 `delivery_packages`（`dispatch/models.py:40`–`:43`）是**派单态包**（8 态机 + `package_code` + `dispatch_round` 唯一键 + `sow_type`）。若新增表取同名，迁移与语义都会撞车——需先定名（另起 `delivery_bundle` 之类）或明确二者关系。 | `server/src/fde_api/dispatch/models.py:40`–`:78`；`docs/后续需求台账-F5与D11.md:38`–`:39`（草案 `delivery_package`：`status` draft→sealed→delivered + `manifest_sha256`） |
| E-7 | **§7 第三阶段「产物→`delivery_package` 闭环」的迁移纪律未写** | 方案全文仅 Q3（`:328`）出现"零迁移零路由新增"一句；§7（`:245`–`:246`）要求 `agent_artifacts` 加列 + 新交付包表，**未写"只加不改、不得修改已发布迁移、应新增迁移、alembic head 同步、版本号同步"**。README 明文要求"不得修改已发布迁移，应新增迁移"（`README.md:201`），版本号需 `desktop/package.json` 与 `server/pyproject.toml` 同步（`README.md:309`）。 |方案 `:245`–`:246`；`README.md:201`；`README.md:307`–`:309`；`server/src/fde_api/workbench/models.py:129`–`:131`（既有 CHECK 约束 ⇒ 加列涉及迁移） |
| E-8 | **§2.3 G8「S2 红线」的出处与边界表述需收敛** | 方案 `:85` 引 `openfde fde -e somwyn` 的 Never violate 段「S2 红线（录音不可存）」。实测该红线的真实文本在 `D:/test/FDE/engagements/openfde/engagements/somwyn/raw/2026-10-27-FDE接触调研阶段资料入库SOP设计.md:111`：「**S2 明令「不录音转写入库」**……**边界是：企业主动发给你的文字可以存；你录的音不能存。**」，而同文件 `:109` 写「初诊录音转写（⚠️ **只转写不入正式库**，且必须先获口头同意）」。**注意 `:109` 的「只转写不入正式库」与方案 Q2（`:306`）"转写出的文字按『企业主动发来的文字』同等对待入库"直接抵触**。Q2 结论（转写文字可入库）会越过真实红线原文（转写文字**不入正式库**）。这是本方案风险最高的单点，须回原文逐字裁决。 | `D:/test/FDE/engagements/openfde/engagements/somwyn/raw/2026-10-27-FDE接触调研阶段资料入库SOP设计.md:109`/`:111`/`:146`；`D:/test/FDE/engagements/fdeops/somwyn/FDE.md:58`–`:119`（Never violate 段实际**无"录音"条目**，方案 `:85` 的引证位置与实际存储位置不符） |
| E-9 | **§2.1 的证据基线是本地 `main`（落后 fork/main 25 提交）** | 方案 `:5` 声明"以2026-11-06 仓库代码实测为准"，但其全部 `文件:行号` 引用是在本地 `main`（HEAD `4a6b821`）上取的，而 `fork/main` 已领先 **25 提交**（权威=fork/main，`fork/main:AGENTS.md:30`）。抽查发现引用行号已漂移：`agents/service.py` `start_run` 本地 `:662` vs fork/main `:709`；`executor.py` `SUPPORTED_NODE_TYPES` 本地 `:78` vs fork/main `:81`；`config.py` `dsh_protocol_version` 本地 `:74` vs fork/main `:84`；`solutions/service.py` `export_sow` 本地 `:669` vs fork/main `:676`；`agents/models.py` `AgentArtifact` 本地 `:124` vs fork/main `:125`。方案声明的"VERIFIED"因此只在本地 main 上成立。 | 实测：`git rev-list --count main..fork/main` = 25；`git log --oneline fork/main -1` = `602001a`；`fork/main:AGENTS.md:30`「本地 main 允许落后——**权威=fork/main**（开新轮先 fetch 对齐）」；上列行号漂移 |
| E-10 | **§4.2 的 `cost`/`logs` 字段与既有成本账本重复** | `agent_runs` 已记 `token_cost`/`duration_ms`/`max_cost_units`，另有 `agents/quota.py`、`agents/pilot.py` 与月度预算账本（`fork/main:AGENTS.md` CR-006 轮"统一入账"）。方案 §4.2 再列 `cost`/`logs` 需确认是派生展示还是新增存储（新增即触发迁移纪律，见 E-7）。 | `server/src/fde_api/agents/adapter.py:66`–`:76`（`AgentRunResult.token_cost/duration_ms`）；`server/src/fde_api/agents/models.py:52`–`:53`（`max_cost_units`/`max_duration_ms`） |

---

**评审结论**：方案的**架构方向成立、现状校正准确、七项决策中六项经实测无臆断**；但 **P0-1（Q5 与总览 Q8 冲突）** 与 **P0-2（Q6 引入第二运行时 vs §0裁决及方案自身沙箱红线）** 两项必须由用户裁决后才能进入实施排期；**P0-3（G2 缺口结论不成立）** 与 **P1-1（产物落库与 #6 归属不变量抵触）** 须在文档层面直接修正。此外 **E-5（Q3 与调研表 confirm 权限冲突）** 与 **E-8（Q2 与 S2 红线原文抵触）** 是两处会影响功能正确性而非仅表述的实质问题，建议一并优先处置。

[Agent ID: agent-92fddb59-6baa-40a6-87a8-b596ee112d53]