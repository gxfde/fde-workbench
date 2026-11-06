测试与质量官评审意见

## A. 总评

**结论：方案在「做什么」上大体成立，在「怎么证明做到了」上系统性缺位。本轮不能按「已可进入实施」放行。**

核心问题一句话：**方案 §7 的「出口指标」与 §8 的「成功度量」是把"看起来有验收"当成了"验收可执行"**。全文 412 行中，`pytest` 出现 **0 次**、`自测` **0 次**、`哨兵` **0 次**、`验收线` **0 次**、`exit_condition` **0 次**、`CAS` **0 次**、`可测` **0 次**、`复现` **0 次**（实测 grep 计数）。唯一带测试语义的两处是 §9 红线 3「需再加一条脱敏断言」（第 283 行）和 §5.2 第 189 行「版本钉死与 sha256 校验沿用…检查单（人工项，Agent 不代跑）」——后者恰恰把验证挂在人工身上，不是可回归机制。

三条具体断裂：

1. **Q1 的代号化自动替换是方案自己新增的一道防线，却没有为它设计任何验证。** 方案 §10 Q1（第 298 行）自己论证了 `check-pseudonymization.sh` 只扫数据库 dump、不扫文件二进制、因而"CI 门禁**静默通过**"。这是方案给出的最有价值的一条负面实证。但方案随即把修复责任完全交给"入库时替换"，而**没有为替换器设计哨兵自测**（注入假企业名 → 验证替换器确实替换 → 验证误替换率）。按 `check-pseudonymization.sh:21` 自己写的纪律——"没自测过的校验器等于没有校验器"——**这道新防线目前就是"从未真正运行过的检查"**。而且实测显示：`server/src/fde_api/guidance/redaction.py:31` 的 `redact_presurvey()` 在全仓**零调用**（`git grep redact_presurvey` 仅命中定义行），说明"入库前脱敏"这条链在代码上并不存在，Q1 是从零新建；`guidance/service.py:425` 的 `_validated_intake_fields` 只做长度/类型校验，**不做任何脱敏**。

2. **§8 的 10 类指标中，多数数据源不存在或口径不可反证。** 最关键的两条——「每个项目占用的工程师小时数」（方案标为"「少养工程师」主张的**直接验证指标**"）与「交付毛利率」——在仓库中只存在于 `server/src/fde_api/dispatch/simulator.py:672` 的 `platform_hours_share` 与 `:673` 的 `gross_margin`，而这两个字段是 **simulation 口径**（`simulator.py:16` 明写"口径 = simulation：指标是「假设表 × 真实引擎」的合成结果，不冒充真实业务数据"）。也就是说：方案用来证明核心商业主张的指标，取自一个**被仓库自己标注为"不冒充真实数据"的合成仿真器**。

3. **与借鉴总览 #11/#14/#22/#28 的落地状态完全没有对接。** #11（三锚点+四类反例挂 G8/G9）与 #14（executor 对抗性测试）至今仍是 `⬜ 待实施`（`v3-backlog.md:429` 登记行明载），#21/#22 停在"协议已成文但机器未接线"（实测 `server/src` 对 `uplift|kpi_oracle|kpi_baseline` **零命中**）。方案 §4 S7 第 143 行串起的那条 S7 门禁链（"人工核验 accepted"），与 G9 `exit_condition` 里已写死的 `uplift_bounded ≥ 0.8 ∧ incidents = ∅ ∧ 三锚四反例全过`（`server/seeds/gates.json` G9）**没有任何衔接描述**。方案 §8 的 10 类指标与 G9 已有的验收线构成事实上的双轨，且两轨的口径、数据源、裁决关系一处未写。

**但方案的证据纪律本身值得肯定**：§2 逐条标注 VERIFIED、给文件:行号，且我逐条抽验了 §2.2/§2.3 的行号——`guidance/ai_schema.py:6` CLASSIFICATIONS ✅、`workflows/executor.py:81` SUPPORTED_NODE_TYPES ✅（方案写 78，实际 81）、`projects/quote_service.py:581` finalize ✅、`solutions/service.py:676` export_sow ✅（方案写 669）、`control/access.py:72` ✅、`auth/models.py:16` viewer ✅。**问题不是行号错，而是行号全部指向 `main`（本地落后 fork/main 约 24 个提交，diff 76 文件/5980 行），且行号只能证明"能力存在"，不能证明"能力有测试"。** 方案 §2 全篇零 pytest 引用——这正是本次评审要指出的核心缺口。

---

## B. 逐条比对表

| 借鉴总览要点 | 方案中的位置 | 判定 | 问题描述 / 证据 |
|---|---|---|---|
| **#11** 门禁/检查器对抗性判据实施落点：把 `check-pseudonymization.sh` 哨兵自测推广为通用 pytest 断言模板（三锚点+四类反例），挂 G8/G9 门禁检查器 | §10 Q1（第 298 行）引用了"哨兵自测"的存在；§9 红线 3（第 283 行）提"需再加一条脱敏断言"；全文无 pytest 字样 | **明显偏离** | #11 的实施落点是"**通用** pytest 断言模板 + 挂 G8/G9 门禁检查器"。方案：(a) 零 pytest 引用；(b) **Q1 提出的"入库时自动替换企业名"是全新机制，方案没有为它设计任何哨兵自测**（无"注入假企业名 → 验证被替换 → 误替换率"）；(c) 未提挂 G8/G9。实测 `check-pseudonymization.sh:21` 自己写明"没自测过的校验器等于没有校验器"——按此纪律，Q1 换来的新防线目前正是"从未真正运行过的检查"。**这是本方案最重的一条 P0。** |
| **#22** 门禁判据升格三锚四反例（do_nothing≈0 / literal≤0.2 / oracle≥0.95；shortcut≤0.8 / bypass≤0.05 / memorised 跨变体跌穿0.5 / alternate 只报告不封顶；跨变体均值 0.5/0.8；变体角度≥3；judge 输出含对象数、0 个不算通过） | §8 全文；§4 S7（第 143 行）门禁链 | **明显偏离** | 方案零处提及三锚四反例。实测 G9 `exit_condition` 已写死 `三锚四反例全过`（`server/seeds/gates.json`），而 §4 S7 串的验收链末端只写"人工核验 accepted"，**没有"三锚四反例全过"这一环**。更严重：方案 §8 立的 10 类指标全部是"过程/效率类"（时间、一次通过率、复用率、成本、毛利率），**没有一条是"这个分数测的确实是它声称测的东西"类**——即 #22 要防的"检查器空转"未被纳入度量面。 |
| **#14** executor 对抗性测试组织：给 `workflows/executor.py` 补固定种子模拟、强杀不丢已确认、迟到拍板、双 definition_version 并存、节点独立事务失败恢复；前置＝决策逻辑抽纯函数（2–3 周重构） | §5.1 六方法适配器协议（第 169–177 行）；§7 第三阶段"zcode 真机跑通"（第 390 行）；§7 第二阶段"执行层可见与咬合" | **明显偏离** | #14 要求的是**可回归的夹具族**，方案 §7 第三阶段的验收词是"**zcode 真机跑通**"——**实机跑通 ≠ 可回归测试**，跑通一次无法阻止下一次回归。实测 #14 五项的现状：`workflows/executor.py` 对 `seed|random` **零命中**（无固定种子模拟）；`dispatch/simulator.py:429` 有 `seed: int = 42` 但那是派单仿真，与 executor 无关；迟到拍板已有 1 例（`test_workflow_executor.py:1477`）；双 definition_version 已有 1 例（`:575`）；强杀恢复有实现无专项用例（`executor.py:559 _recover_interrupted`）。**即 5 项中 3 项无覆盖，而方案对这 3 项零感知。** 且方案未提 #14 的前置"决策逻辑抽纯函数（2–3 周重构）"——方案的"第三阶段"只有 PATH wrapper + provider 配置 + 镜像钉版 + 人工检查单，**不含任何 executor 侧测试工程项**。 |
| **#28** 门禁 revision CAS：`expected_revision` 可选 + 复用 `gates.version` + `lifecycle_version`；版本交叉 409 `gate_revision_conflict` 且不推进 version | §4 S7（第 143 行）；§10 Q3 引用 `projects/permissions.py:21` 的 `project_access` | **明显偏离** | 方案 §4 S7 的门禁链把"人工核验 accepted"作为末端，**完全没有 revision CAS 的位置**：多人并发拍同一门禁时，方案没有任何一处说"两个 FDE 同时核验会怎样"。实测服务端 CAS **已完整**（`projects/gate_service.py:376-397`，4 条 pytest 覆盖于 `test_gates_api.py:361/387/414/425`），但桌面 `GateBoard.expected_revision` 接线 **blocked**（`git grep expected_revision fork/main -- desktop` **零命中**；借鉴总览 §6.5 R3 已拍板维持 blocked）。**方案 Q7 决定做 agents/meetings 控制台、§4 S7 又要串门禁链，却未识别桌面 CAS 未接线这一既有缺口**——这是"方案漏看已有工程状态"的实例。 |
| **#21** G9 `exit_condition`＝`uplift_bounded ≥ 0.8 ∧ incidents = ∅ ∧ 三锚四反例全过`（无 oracle → `insufficient_data` 不得出分） | §4 S7（第 143 行）；§8 成功度量 | **存在冲突** | G9 已有的验收线与 §8 的 10 类指标构成双轨，两轨口径、数据源、裁决关系一处未写。实测：`server/src` 对 `uplift|kpi_oracle|kpi_baseline` **零命中** ⇒ 协议已成文但机器未接线（借鉴总览 #21 明载此口径）。方案 §8 却要新立"门禁质量：G1/G2/G3 一次通过率"等指标，**且完全没有交代它与 G9 既有验收线谁优先、冲突时听谁的**。按 §6.5 R4，`0.8` 仍是"占位·待我方数据校准"——方案若把 §8 指标当验收线用，等于绕过了 R4 的校准闸。 |
| **#33** 文档职责分层 + 验证证据格式：审查/评估类报告统一采用「命令／退出码／可观察结果／未验证项」四列；`docs/verification/` 目录与证据模板 | §2 现状校正（VERIFIED/文件:行号）；§10 Q1–Q7 决策台账 | **存在冲突** | 方案自称"证据口径：本文所有「现状」主张均以 2026-11-06 仓库代码实测为准（文件:行号）"（第 5 行），但：**(a) 全文零处使用四列格式**；**(b) 全文零处标注"未验证项"**——例如 §10 Q5 第 348 行的 zcode 阻塞点（provider 配置缺失）、§10 Q6 第 366 行的 openfde 安装、§10 Q5 第 350 行的"本机未部署 DSH"，全部写成实测断言而无退出码/可观察结果/未验证标记；**(c) 全文零 pytest 引用**（实测 grep 计数 0），即所有"实测"只有文件:行号一条腿。实测仓库侧 `docs/verification/` 目录**不存在**（`git ls-tree` 零命中）、`AGENTS.md` 中 `verification|最窄验证|未验证项` **零命中** ⇒ #33 本身也未落地，方案连"对照一个未落地的标准"都未提。 |
| **§1 跨项目合并原则**（对抗性测试→#14 一项；结果验收与反证→#21/#22→#23/#24→#25；门禁与验收合同→#21/#22/#29→#28/#30→#23，**不新开架构项**） | §7 实施顺序表（第 386–392 行）；§10 决策后的实施顺序 | **存在冲突** | 方案 §7 的五阶段表是一条**全新的实施轴**（主线/咬合/zcode/第二家/ASR），**与 v3-backlog 的 B# 登记体系零交叉**。实测 `v3-backlog.md:429` 登记行明确列出 B#11/B#14/B#23/B#24/B#30 五条仍在册未实施。方案新增的"代号化自动替换""S3 前置闸""条款清单勾选"三项**均未在 backlog 登记**（`git grep 售前驱动交付 fork/main` 零命中）。按 §5.6 纪律"所有借鉴项走既有流程（feature 分支→PR→4 CI job→合并）；**实施偏差须回写 `v3-backlog.md` 与本清单**"——方案未回写，即绕过了合并原则的防重复立项机制。 |
| **§6.5 R1–R4**（R4：协议 v0 阈值 `0.8`/`0.2`/`0.95`/`0.05`/`0.5` 标"占位·待我方数据校准"，**Q6/Q18 法务结论前不得定稿 PASS 线**；R3：#28 桌面接线维持 blocked） | §8 成功度量；§10 Q1/Q5 | **存在冲突** | 方案 §8 直接把验收指标写成可判定的成功线，但未继承 R4 的"占位·待校准"标记机制。方案 §8 的「G8 验收一次通过率」等指标一旦写成数字目标，即等于在 Q6（法务口径）未出前替 G9 定稿了验收线。R3 同理：方案 Q7 决定做桌面控制台、§4 S7 要串门禁链，但未声明"GateBoard.expected_revision 接线属品牌轮冻结区，本次不抢"。 |
| **§6.6 数据采集清单**（每行有 owner/截止/达标判据/完成定义；"样本 <30 条 ⇒ 标 `insufficient_data` **不拍板**"；验收人＝蔡工） | §8 成功度量；§7 各阶段"出口指标" | **明显偏离** | 方案 §7 第一阶段出口指标（第 235 行）"一个真实客户项目能从访谈走到合格方案 + 冻结 SOW，每一步都有来源、版本、责任人和证据"——**无 owner、无截止、无达标阈值、无完成定义、无验收人**，且"合格方案"未定义。§8 的 10 类指标同样全部无阈值、无口径、无样本量下限、无"样本不足则不拍板"条款。按 §6.6 的纪律，样本 <30 条不拍板；方案对"首个客户项目"这种必然 n=1 的样本没有任何标注。 |

---

## C. 度量指标可测性逐条评估表

§8 的 10 类指标（方案第 261–269 行）逐条评估。"数据源是否存在"以 `fork/main`（权威分支）实测为准。

| 方案 §8 指标 | 数据源是否存在 | 是否可反证 | 结论 |
|---|---|---|---|
| **售前效率**：访谈 → 合格机会所需时间；方案从访谈到 SOW 的时间 | **部分存在**。`presurvey_intakes` 有 `created_at/updated_at`（`guidance/service.py:381`），`projects` 有 `created_at`；但"访谈"的起点无埋点——录音转写链不存在（G3），presurvey 录入卡的 `interview_mode`/`interviewee_roles` 只是文本字段（`_validated_intake_fields`，`guidance/service.py:425`）。**"合格机会"无定义字段** | **不可反证**。构造反例：一个项目把 `customer_vision` 从 2000 字写到 2000 字、把 `phase_objective` 填满并 `confirm`——"访谈→合格机会"耗时接近 0，因为起点终点都是人为填的 | **不可测**。无起点事件、无"合格"判定口径。需先定义"合格机会"的可判定字段，并显式排除"补填旧项目"污染 |
| **门禁质量**：G1/G2/G3 一次通过率；人工返工率 | **一次通过率：数据源存在**。`gate_decided` 事件（`projects/gate_service.py:556`）留痕 `changes`，`metrics/service.py:99-117` 已有 `sow_first_pass_rate` 的同型实现可复用。G1/G2/G3 对应 S1/S2/S3（`server/seeds/gates.json`）。**人工返工率：无定义**（是"打回重提"？"再次核验"？"改方案再提交"？——方案未定义计数单元） | **一次通过率：可反证**（首次 `gate_decided` 非 pass 即失败，事件序列可查）。**人工返工率：不可反证**——无分母定义，无法区分"返工"与"正常二次提交" | **一次通过率可用但未定义口径**；**人工返工率不可测**。需按 §6.6 补口径定义 + owner + 达标阈值 + 样本下限 |
| **人力结构**：**每个项目占用的工程师小时数**（"「少养工程师」主张的**直接验证指标**"） | **不存在（真实口径）**。唯一同名字段是 `dispatch/simulator.py:672` 的 `platform_hours_share`，属 **simulation 口径**（`simulator.py:16` 明写"不冒充真实业务数据"；`:90` "口径=simulation（假设表×真实引擎）的合成结果，非真实业务数据"）。真实侧只有 `quotes.actual_hours`（`workbench/models.py:732`，**成交后 48h 内台账回填**，即单项目报价工时，非"占用的工程师小时数"，且人工录入） | **不可反证（且口径本身是构造的）**。反例一：只做 `simulation` 跑一次，`platform_hours_share=0.0` 即"达标"，但零真实交付发生。反例二：把全部交付归到"平台主导"模式，`actual_hours` 填 0，指标归零，但工程师实际做了大量集成工作——**模式归类本身就是人工判断，无机器可核** | **最严重的一条**。方案把它标为"直接验证指标"，但数据源是仓库自己声明为"非真实业务数据"的合成仿真器，且真实侧的人工录入可任意填写。**"少养工程师"这一商业主张，用现状数据无法被证伪。** 需先定义可核的工时归集面（哪些动作算"占用工程师小时"、谁记、在哪记），并把 simulation 口径与 live 口径在指标表里分列、禁止混用 |
| **复用**：标准交付物复用率；标准方案骨架复用率 | **部分存在但无复用血缘**。`project_solutions.template_id`（`solutions/models.py:46`，FK `industry_template_versions`）可算"方案骨架来自模板"的比例；`ProjectGuidanceAnalysis`（`solutions/models.py` 有 SolutionVersion）有 `version_number` 序列。**但"交付物复用"无对应字段**——`agent_artifacts` 只有 `storage_ref`/`sha256`（`agents/models.py:135-139`），无"此产物派生自哪个既有交付物"字段 | **不可反证**。反例：把一个项目复制成 N 个（每份 solution 都指向同一 `template_id`），复用率 100%，但零真实复用 | **不可测**。需补派生血缘字段（`derived_from_artifact_id` 之类）并定义"复用"≠"同模板多实例" |
| **执行质量**：编码智能体任务一次测试通过率；智能体产物被人工接受率 | **一次测试通过率：数据源不存在**。`agent_artifacts` 无 `test_results` 字段（实测 `git grep test_results -- agents/models.py` 零命中）；`AgentToolCall` 只记 `decision`（allowed/denied），不记测试结论。方案 §4.2 第 163 行**自己承认**"没有 diff 与 test_results 的结构化落库字段"——**指标依赖尚未存在的字段**。**产物被接受率：数据源半存在**——`agent_artifacts.reviewed`（`agents/models.py:141`）存在，但实测 `git grep reviewed -- agents/routes.py` **零命中** ⇒ 无写路径可翻转该字段 | **不可反证**。反例一：所有 run 都失败 ⇒ 分母为 0，一次通过率按现有 metrics 惯例会返回 `0.0` 或 `None`（`metrics/service.py:93` 惯例），**"全部失败"与"没有数据"不可区分**——这恰是 #22「0 个不算通过」要防的情形，方案未引用。反例二：`reviewed` 恒为 `False`（无写路径）⇒ 接受率恒 0 | **不可测，且是"指标依赖尚未存在的字段"**。这不是度量口径问题，是数据底座缺口。方案须先在 §7 第三阶段把 `diff/test_results` 落库列为**前置**，指标才能成立 |
| **经济性**：每个客户验收项目的智能体成本；**交付毛利率** | **智能体成本：数据源存在但口径偏**。`agent_runs.token_cost`（`agents/models.py:98`）＋ `cost_owner_type`（project/seat/platform，`:112`），`metrics/service.py:183-189` 已有 `run_cost_median_units`（口径＝token_cost 中位数，**单位非货币**）。**毛利率：数据源不存在**。唯一 `gross_margin` 在 `dispatch/simulator.py:673`（simulation 口径）。真实侧 `quotes.final_amount`（`workbench/models.py:721`，成交后 48h 内回填）+ `quotes.actual_hours`（`:732`）+ `labor_cost`（报价时算出的**估算**值），**三者分属"估算/回填"两条时间线，且无"实际交付成本"表** | **不可反证**。反例一：把所有 `cost_owner_type` 标为 `seat`（不是 `project`），则"每个客户验收项目的智能体成本"分子归零 —— **`cost_owner_type` 是人工/服务侧赋值，无机器判定"这个 run 到底服务于哪个客户项目"**。反例二：毛利率分母用 `final_amount`、分子用报价时的 `labor_cost`（估算非实际），而 `actual_hours` 又是人工回填 ⇒ **毛利率可被录入数字直接决定** | **智能体成本口径偏（token≠货币，且可被 cost_owner 归属洗白）**；**毛利率不可测**，且与"人力结构"那条共享同一个 simulation 口径陷阱 |
| **客户面**：客户现场问题数量；G8 验收一次通过率 | **现场问题数量：数据源不存在**。`OperationEvent`（`workbench/models.py:891`）记系统内事件，但无"客户现场问题"的登记入口——`meetings` 是评审会不是现场问题。**G8 一次通过率：数据源存在**（`gate_decided` 事件，`G8` 的 `decision_semantics` 为 `['proceed','pivot','stop']`，`gates.json`） | **G8 一次通过率：可反证**（首个 `gate_decided` 的 `decision` 非 `proceed` 即失败）。**现场问题数量：不可反证**——无登记面 ⇒ 恒 0；且"现场问题"若改为事后统计，**问题被不报 = 指标变好**，是典型的 Goodhart 反例 | **G8 一次通过率可用**；**现场问题数量不可测且指标方向有害**（不报即达标）。需明确登记面 + 口径（谁登记、什么算现场问题） |

**C 表小结**：§8 的 10 类指标中——

- **可测且可反证**：G1/G2/G3 一次通过率、G8 验收一次通过率（2 条，均依赖 `gate_decided` 事件，需补口径定义）
- **数据源存在但口径可被洗白**：智能体产物被人工接受率（`reviewed` 无写路径）、每个客户验收项目的智能体成本（`cost_owner_type` 可被归属洗白）
- **依赖尚未存在的字段**：编码智能体任务一次测试通过率（`test_results` 未落库，方案 §4.2 自认）
- **口径未定义**：人工返工率、访谈→合格机会时间
- **无数据源且不可反证**：每个项目占用的工程师小时数、交付毛利率、现场问题数量、标准交付物复用率（5 条）
- **指标方向有害**：客户现场问题数量（不报即达标）

**即 10 类指标中只有 2 条在补口径后可直接用，5 条当前完全不可测，其中 2 条（人力结构、毛利率）恰是方案用来验证核心商业主张的。** 方案第 271–273 行的"北极星"验收条件（"一个真实客户项目能够从访谈走到 SOW、交付、验收和归档"）本身是一个 **n=1 的存在性陈述**——它没有失败判据：走不通就是"还没到时候"，因此**永不失败、不可反证**。

---

## D. 必须修改项（P0/P1/P2 排序）

### P0-1 ｜为 Q1 代号化自动替换设计哨兵自测，并挂 G8/G9（#11 实施落点）

- **问题**：Q1（第 293–302 行）引入一条全新防线（入库时企业名自动替换），无任何验证机制。按 `check-pseudonymization.sh:21`「没自测过的校验器等于没有校验器」，未自测即等于没有。
- **必须补**：①替换器函数的 pytest 断言模板——注入假企业名（取自 `.github/ci-assets/synthetic-leads-blacklist.txt` 的合成名，**不得用真实客户名**）→ 断言正文零命中 + 占位符在位；②**误替换钉**——注入"不构成企业名的中文短词"（如"技术公司""集团公司"这类 `leads.md` 正则会误抓的通用词）→ 断言未被替换，量化误替换率上限；③断言**替换发生在 `redact_text` 之后、落库之前**（Q1 落地约束原文），即两条防线串联顺序被钉住；④该模板按 #11 挂 G8/G9 门禁检查器。
- **注意**：Q1 落地约束说"企业名词典来源 = `leads.md` 黑名单（`:91` 的中文 2–15 字 + 公司/集团/厂 结尾正则），同一份词典双向复用"。实测 `check-pseudonymization.sh:90-92` 用的是 perl 码位区间正则 `([\x{4E00}-\x{9FA5}]{2,15}(?:公司|集团|厂))`——**这个正则会抓到"技术公司""设备制造厂"这类通用词**。误替换率不是理论风险，是当前词典的必然属性。方案必须处理这一点（词典过滤规则或分行业白名单），否则售前录入的正常表述会被大面积替换。
- **附带**：实测 `guidance/redaction.py:31` 的 `redact_presurvey()` 全仓零调用；`guidance/service.py:425` 的 `_validated_intake_fields` 只做长度/类型校验、不脱敏。Q1 说"替换发生在 `redact_text` 之后、落库之前"，但这条链在代码上不存在，方案需指明插入点（`save_presurvey_intake` 与 `handle_presurvey_analysis` 两条落库路径都要覆盖，且 `guidance/jobs.py:43` 的 worker 路径独立于 route）。

### P0-2 ｜§7 三阶段补"测试策略"章节，区分"实机跑通"与"可回归测试"（#14）

- **问题**：§7 第三阶段（第 390 行）的验收词只有"zcode 真机跑通"。实机跑通是一次性的、可回归测试是持续的，两者不可互替。
- **必须补**：①每个阶段的"出口指标"必须区分**人工一次性动作**（如 §7 第三阶段的"试点前联调检查单执行（人工项）"，方案第 390 行自己标了"人工项"，这是好的）和**可回归机器闸**（pytest/CI 断言）；②第三阶段须明确 zcode 适配器的**回归夹具**落点——至少覆盖 `agents/adapter.py` 的 `kind = "zcode"`（实测 `fork/main:110`）在无 PATH/无 provider 配置时**必须报 `adapter_missing` 而非崩溃或静默成功**（现有 `agents/service.py:200-202` 已实现该分支，需钉住）；③第一/二阶段改 `guidance`/`research`/`solutions`/`agents`/`meetings` 五个域时，须在出口指标里写明**对应的既有测试文件与用例数会被改动**（见 P1-1），并要求给出改前改后的 pytest 口径数。
- **#14 关联**：借鉴总览 #14 明确前置是"决策逻辑抽纯函数（2–3 周重构）"。方案 §7 第三阶段不含此重构。**不要求方案照搬 #14 的完整五项**（那属于 #14 工程项），但方案不能在没有 adversarial test 意识的情况下把"实机跑通"当作执行层的验收终点。若认为 #14 应在本轮启动 → **待澄清：建议由用户裁决**（#14 在 `v3-backlog.md:429` 仍登记为待实施，且 §6.5 拍板"与 autoloop sim 三件套裁决合并＝先攒真实故障史，三期做"）。

### P0-3 ｜§8 成功度量重写：区分 live/simulation 口径、给出数据源与失败判据

- **问题**：§8 把 simulation 口径字段（`simulator.py:672 platform_hours_share`、`:673 gross_margin`）当作核心商业主张的"直接验证指标"，且 10 类指标中 5 条无数据源。
- **必须补**：①§8 表格增两列「**数据源（文件:行号）**」「**live / simulation**」；simulation 口径的字段**不得**作为商业主张验证依据，只能标为假设；②「每个项目占用的工程师小时数」「交付毛利率」两条必须改写为"**待埋点**"或"**当前不可测**"，不得以现状数据表述为可验证；③每条指标补 §6.6 四要素（owner／截止／达标判据／完成定义）＋"样本 <30 条 ⇒ `insufficient_data` 不拍板"；④「客户现场问题数量」必须先有登记面，否则**建议由用户裁决是否保留**（不报即达标的反向激励）；⑤明确 §8 指标与 G9 `exit_condition` 的**优先级关系**——按 §6.5 R4，`0.8` 等阈值仍是"占位·待我方数据校准"，Q6 法务口径未出前不得定稿 PASS 线，§8 不得单方面定稿。

### P0-4 ｜方案补 #33 四列证据格式，并标出"未验证项"

- **问题**：方案自称"证据口径：所有现状主张以实测为准（文件:行号）"（第 5 行），但全文零 pytest 引用、零"未验证项"标记。§2 的"实测"只有文件:行号一条腿——**行号只证明符号存在，不证明行为被测过**。
- **必须补**：①§2 每条"现状"增一列「**验证方式**」（pytest 文件:用例名／grep 命令／脚本退出码），对只能静态核实的一律标 `[静态·未跑]`；②新增「**未验证项清单**」小节，收纳至少：§10 Q5 的 zcode provider 配置缺失与 PATH 缺失（第 348 行，实机未跑）、§10 Q6 的 openfde `npm ls -g` 全局安装（第 366 行）、§10 Q5 的 DSH 无 8020 监听（第 350 行）、§2.3 G4/G5 的 grep 零命中结论（第 81–82 行）、§5.2 第 189 行"版本钉死与 sha256 校验"（方案已自标"人工项"，应并入此清单）；③方案本身按 #33 落 `docs/verification/` 证据模板。

### P1-1 ｜§7 回归风险面量化（实测数据已具备）

实测 `fork/main` 现有覆盖（本次评审逐文件统计 `def test_` 数）：

| 阶段 | 受影响域 | 现有服务端测试（文件:用例数） | 现有桌面测试（文件:用例数） |
|---|---|---|---|
| 一（主线） | guidance | `test_guidance_adoption` 10／`test_guidance_adversarial_fixtures` 10／`test_guidance_ai_schema` 8／`test_guidance_docx_extract` 1／`test_guidance_models` 1／`test_guidance_redaction` 2／`test_guidance_retry` 16 ＝ **48** | `guidance-chain-scenarios` 6／`guidance-review-confirm` 5／`presurvey-intake-card` 4／`presurvey-mount-claim` 3／`presurvey-polling` 1 ＝ **19** |
| 一（主线） | research | `test_research_answers` 12／`test_research_definitions` 17／`test_research_export_naming` 2／`test_research_form_ai` 3／`test_research_forms_api` 29／`test_research_imports` 42／`test_research_models` 17／`test_research_subject_merge` 7／`test_research_subjects_api` 28 ＝ **157** | `project-research` 79／`research-definition-editor` 44／`research-opportunity` 13／`research-subject-tree` 6 ＝ **142** |
| 一（主线） | solutions | `test_project_solutions` 11／`test_solution_agent_wiring` 12／`test_solution_signoff` 20／`test_solution_skills` 3／`test_solution_validation` 5 ＝ **51** | `solution-design` 31／`solution-provenance` 4／`signoff-console-and-dispatch` 6 ＝ **41** |
| 二 | agents | `test_agents_adapter` 9／`test_agents_fallback_chain` 15／`test_agent_context_sanitization` 8／`test_agent_gates_d7` 11／`test_agent_idempotency` 6／`test_agent_traceability` 2／`test_agent_budget` 5／`test_agent_pilot` 6／`test_agent_assisted_integration` 17 ＝ **79** | 无独立 agents 桌面测试（`desktop/src/renderer/src` 无 `agents/` 目录，方案 §2.3 G6 自认） |
| 二 | meetings | `test_meetings_service` 9／`test_meeting_orchestration` 15／`test_meeting_tools` 8 ＝ **32** | 无 |
| 三 | 沙箱/适配器 | `test_sandbox_isolation` 8／`test_agents_d4_harness` **0** ＝ **8** | — |
| 三 | workflows/executor | `test_workflow_executor` 39／`test_workflow_definition` 9／`test_workflow_runs` 8 ＝ **56** | — |
| — | 门禁 | `test_gates_api` 13／`test_t6_gate` 11／`test_run_review_gates` 5 ＝ **29** | `gate-board` 13 |

**风险评估**：

- **高风险点 1 —— `test_agents_d4_harness.py` 实测 0 个 `def test_`**：文件名暗示覆盖 D4 harness，但按 `def test_` 计数为 0。需在改动前确认其实际形态（可能是 class 内方法或参数化），**不得假定它提供了保护**。
- **高风险点 2 —— `test_research_imports.py` 42 例、`test_research_forms_api.py` 29 例、`test_research_subjects_api.py` 28 例、桌面 `project-research` 79 例、`research-definition-editor` 44 例**：research 域是第一阶段"补三态 UI 入口"的落点（`research/project_routes.py:461/475/496` 三条 confirm/reject/revise 端点，实测 desktop 零引用，方案 §2.3 G1 已核实），**服务端已有 99 例 + 桌面 123 例 = 222 例直接压在同一条链上**。改 UI 入口时若动了前端数据契约（如状态映射、乐观锁 version 传递），回归面巨大。方案 §7 未提这一风险。
- **中风险点 3 —— `test_solution_signoff.py` 20 例 + `test_project_solutions.py` 11 例**：Q1 的替换机制一旦作用于方案/SOW 导出链（方案 §9 红线 2 要求"SOW 导出必须绑定已冻结的方案版本"），会触及 `solutions/service.py:676` 的 `export_sow` 及其终审闸（方案 §2.2 第 62 行述及 `solutions/service.py:673-684`）。实测 `export_sow` 在 `fork/main:676`，方案写 669（指向本地 `main`）——**行号基准不一致，改动方案须先对齐权威分支**。
- **低风险点 4 —— `test_agents_d4_harness` 0 例 + 桌面无 agents 测试**：第二/三阶段做 agents 控制台时**几乎无前端回归保护**，需要新写。
- **基准口径**：仓库当前 pytest 口径 **1972**（`AGENTS.md` 口径行，= 1966 passed + 6 skipped），vitest **791**。方案 §7 每个阶段的出口指标应写明"pytest 1972 +N / vitest 791 +M"这类可核口径，否则"完成了"无法判定。

### P1-2 ｜§4 S7 门禁链补 revision CAS 与 G9 验收线的衔接

- **问题**：§4 S7（第 143 行）的链条末端只写"人工核验 accepted"，缺两件事：①**并发拍板**——两个 FDE 同时核验同一门禁时，`expected_revision` CAS 是唯一拦截机制（实测 `projects/gate_service.py:376-397` + 4 条 pytest 于 `test_gates_api.py:361/387/414/425`）；②**G9 验收线**——G9 的 `exit_condition` 已含"三锚四反例全过"，链条里没有这一环。
- **必须补**：§4 S7 补一行"并发核验 → `expected_revision` CAS（`gate_service.py:376`）→ 版本交叉 409 `gate_revision_conflict` 零变更"，并注明桌面 `GateBoard.expected_revision` **接线属品牌轮冻结区、判据＝品牌轮 PR 合入**（借鉴总览 §6.5 R3 已拍板维持 blocked，`git grep expected_revision fork/main -- desktop` 零命中）。方案 Q7 决定做桌面控制台时**不得顺手宣称门禁链的并发安全已闭合**。

### P1-3 ｜方案在 backlog / 借鉴总览登记，防重复立项

- **问题**：方案新增三项机制（代号化自动替换、S3 前置闸、条款清单勾选）+ 五阶段实施轴，`git grep 售前驱动交付 fork/main` 零命中 ⇒ 未进 `v3-backlog.md`，未回写借鉴总览。
- **必须补**：按借鉴总览 §5.6「实施偏差须回写 `docs/implementation/v3-backlog.md` 与本清单」，方案 §11 增一行"本轮新增登记：B#41（代号化入库替换）｜B#42（S3 前置闸）｜B#43（合同条款清单勾选）"，并在借鉴总览 §1 相应标注与 #11/#14/#21/#22/#28 的关系。**注意 R2 已拍板"本轮不改 backlog（并发回滚轮未落定：本地落后 19 提交、155 脏改动）"——本次实测本地已落后 **24** 个提交、76 文件/5980 行 diff ⇒ 该前置条件仍不成立，登记时点需用户裁决。**

### P2-1 ｜§2 证据行号基准统一到权威分支

实测：方案 §2 引用的行号全部指向本地 `main`（落后 fork/main 24 提交），而 `AGENTS.md:32` 明写"**权威=fork/main**（开新轮先 fetch 对齐）"。对照实测差异：`agents/service.py` `_render_context` 本地 330 / fork 350、`start_run` 本地 662 / fork 709、`handoff_run` 本地 880 / fork 927；`quote_service.py` finalize 本地 564 / fork 581；`solutions/service.py` export_sow 本地 669 / fork 676；`workflows/executor.py` SUPPORTED_NODE_TYPES 方案写 78 / fork 实际 81；`control/api_catalog.py` agent_assisted_declare 本地 114 / fork 118。方案第 5 行声称"以 2026-11-06 仓库代码实测为准"但未声明基准分支。**须在 §2 抬头显式声明基准＝`fork/main`@`248132c`，并给出对齐后的行号**（或改用符号名＋锚点，避免行号腐化）。

### P2-2 ｜§5.1 统一适配器协议补"未就绪契约"

实测 `agents/service.py:200-202`：`agent.kind != "zcode"` ⇒ 返回 `"adapter_missing"`。方案 §5.1 列了六方法协议（`prepare_workspace / validate_request / run / collect_result / cancel / health_check`），但**未规定"适配器未就绪"时必须返回可判定的不可用原因而非抛异常/静默成功**。第一至三家接入时这正是最容易出错的地方。建议 §5.1 增一行「未就绪 ⇒ 返回 `adapter_missing`（对齐 `agents/service.py:200`），不得抛异常、不得静默成功」，并以 pytest 钉住。

### P2-3 ｜§2.3 G7/G6 与 §7 阶段顺序的一致性复核

方案 §7 第二阶段含 agents/meetings 桌面控制台（Q7 已并入第一阶段主线），而 §7 表格"第二阶段"仍写"补执行层的桌面控制台（G6）"，§10 决策后顺序表又把它并入第一阶段——**同一节内两处表述不一致**。实测 `desktop/src/renderer/src` 确无 `agents/`、`meetings/` 目录（仅 `pilot/PilotReportPage.tsx`、`solutions/QuotaMeter.tsx`、`solutions/SignoffConsole.tsx` 引用 agents，方案 §2.3 G6 属实）。建议统一表述并标明"Q7 决策后 = 并入第一阶段"。

---

## E. 可选优化项

1. **§8 增一列「反例构造」**（每条指标写一句"什么情况算它没做到"）。这正是 #22 的精神内核，且能立刻暴露"客户现场问题数量"这类反向指标。
2. **§7 第一阶段出口指标改为可核断言**：把"每一步都有来源、版本、责任人和证据"落成具体字段清单——来源=`source_refs`（`guidance/ai_schema.py:6` 五分类已强制）、版本=`ProjectGuidanceAnalysis.version`（`guidance/service.py:132` 递增）、责任人=`created_by_user_id`（`:174`）、证据=`evidence_json`。这四条**全部已落库**，方案 §7 出口指标可直接绑定到既有字段，是最省力的一处可测化改造。
3. **§10 Q1 复用 `check-pseudonymization.sh` 的词典，但把提取逻辑从 bash/perl 提取为 Python 单点**：`extract_blacklist()`（`check-pseudonymization.sh:85-93`）当前是 perl 正则，与替换器若各写一份正则，两边漂移是必然的（bash 与 Python 的中文码位区间边界处理不同——脚本注释 `:86-89` 本身就记载了 GNU grep 多字节区间不可移植、实测三环境三种结果）。建议词典提取收敛为一个 Python 实现，bash 侧改为调用它，**并在替换器自测里直接断言"替换器用的词典 == CI 扫描器用的词典"**（字典序逐条比对）。这同时消除 §10 Q1 的"同一份词典双向复用"目前只是文字承诺的风险。
4. **§2.3 G3（录音转写链缺失）补一个 grep 复核口径**：方案第 80 行称 `grep -rln "transcri\|audio\|录音" server/src` "仅命中这两处且语义不符"——实测 `server/src` 对 `transcri|audio` 的命中需逐一确认语义，建议把该 grep 命令与其输出原文写进 `docs/verification/`（#33 格式），因为"grep 零命中"是最易随代码演进而失效的证据。
5. **§8「复用率」补一条负向指标**（"新建重复物比例"）：复用率是典型的可被"复制 N 份"洗白的指标，配一条反向指标成本极低。
6. **方案 §11 增一节「与借鉴总览未落地条目的关系」**：把 Q1 对应 #11、§7 三阶段对应 #14、§4 S7 对应 #21/#22/#28 三组关系列明，避免读者误以为本方案是独立于既有借鉴体系的第四条轴。

---

## F. 待澄清的开放问题与风险清单

### F.1 需用户裁决（不由测试与质量官代决）

| # | 问题 | 背景 | 不裁决的后果 |
|---|---|---|---|
| **F-1** | **§8 的 10 类指标与 G9 已有验收线（`uplift_bounded ≥ 0.8 ∧ incidents = ∅ ∧ 三锚四反例全过`）是取代、并存还是补充？** | G9 `exit_condition` 已写死（`server/seeds/gates.json`）；方案 §8 未提。按 §6.5 R4，0.8 是"占位·待我方数据校准"，Q6 法务口径未出 | §8 指标与 G9 验收线并存双轨且口径冲突；一旦 §8 被当验收线用，等于在 R4 校准闸外单方面定稿 PASS 线 |
| **F-2** | **「每个项目占用的工程师小时数」「交付毛利率」是否接受"当前不可测"这一结论？** 若不接受，需要先立工时归集埋点（哪些动作算、谁记、在哪记）——这是独立工程项，不在方案 §7 五阶段内 | 唯一数据源 `simulator.py:672/673` 是 simulation 口径（`simulator.py:16` 自述"不冒充真实业务数据"） | 方案 §1「不用养太多 FDE 工程师」这一商业主张的"直接验证指标"用合成仿真器验证 ⇒ 主张被证伪的风险不可控，且未来一旦被引用为决策依据即为事实性错误 |
| **F-3** | **是否在方案 §7 第三阶段纳入 #14 的 executor 对抗性测试（前置：决策逻辑抽纯函数，2–3 周重构）？** | #14 在 `v3-backlog.md:429` 仍登记待实施；§6.5 拍板"与 autoloop sim 三件套裁决合并＝先攒真实故障史，三期做"。方案 §7 第三阶段无任何 executor 测试工程项 | "zcode 真机跑通"成为执行层唯一验收终点，下一次回归无人拦截；#14 继续挂账 |
| **F-4** | **Q1 的企业名词典误替换问题如何处置？** `check-pseudonymization.sh:91` 的正则 `([\x{4E00}-\x{9FA5}]{2,15}(?:公司\|集团\|厂))` 会命中"技术公司""制造厂"等通用表述 | 实测该正则在 `extract_blacklist()`（`:90-92`）中生效，是 CI 扫库与 Q1 替换共用的唯一词典 | 入库替换会大面积替换售前正常表述，误替换率不可接受；且**若不先量化误替换率，替换器本身就会变成 #11 意义上的"未自测检查器"** |
| **F-5** | **方案新增机制登记进 backlog 的时点？** §6.5 R2 已拍板"本轮不改 backlog"，理由是"并发回滚轮未落定：本地落后 19 提交、155 脏改动"；本次实测本地已落后 **24** 提交、76 文件/5980 行 diff | `git grep 售前驱动交付 fork/main` 零命中 | 方案三项新机制不入台账 ⇒ 重演"重复立项"事故（借鉴总览 §1 跨项目合并原则的核心目的） |
| **F-6** | **§8「客户现场问题数量」是否保留？** | 无登记面 ⇒ 恒 0；且若事后统计，"不报即达标"是反向激励 | 指标方向有害，比不可测更危险 |

### F.2 事实性风险清单（已实测，供实施排期参考）

| # | 风险 | 实测证据 | 影响阶段 |
|---|---|---|---|
| **R-1** | **Q1 替换点不存在**：`redact_presurvey()` 全仓零调用；`_validated_intake_fields` 只做长度/类型校验；worker 路径 `guidance/jobs.py:43 handle_presurvey_analysis` 独立于 route | `git grep redact_presurvey fork/main` 仅命中定义行 `redaction.py:31` | 一 |
| **R-2** | **`agent_artifacts` 无 `diff`/`test_results` 字段** ⇒ §8「一次测试通过率」的数据源尚不存在（方案 §4.2 第 163 行自认，但 §8 仍把它列为指标） | `git grep test_results -- agents/models.py` 零命中；`AgentToolCall` 只有 `decision` | 三 |
| **R-3** | **`agent_artifacts.reviewed` 无写路径** ⇒ §8「产物被人工接受率」恒为 0 | `git grep reviewed -- agents/routes.py` 零命中（`agents/service.py` 只读该字段并回填 `:340/524`） | 二、三 |
| **R-4** | **桌面 `GateBoard.expected_revision` 未接线**（借鉴总览 §6.5 R3 拍板 blocked，判据＝品牌轮 PR 合入）⇒ §4 S7 门禁链的并发安全在桌面侧不成立 | `git grep expected_revision fork/main -- desktop` 零命中 | 二 |
| **R-5** | **`test_agents_d4_harness.py` 按 `def test_` 计数为 0** ⇒ 不得假定它为 agents D4 提供回归保护 | 实测计数 0 | 二、三 |
| **R-6** | **agents/meetings 无任何桌面端测试**（`desktop/src/renderer/src` 无 `agents/`、`meetings/` 目录；`desktop/tests/renderer/` 65 个文件中无 agents/meetings 测试） | 实测目录清单 + 文件清单 | 二 |
| **R-7** | **`server/src` 对 `uplift|kpi_oracle|kpi_baseline` 零命中** ⇒ #21 协议"已成文但机器未接线"，G9 的 `exit_condition` 当前不可机器判定 | 实测 `git grep` 零命中 | 全程 |
| **R-8** | **方案 §2 证据行号基准为本地 `main`（落后 fork/main 24 提交），而 `AGENTS.md:32` 明写"权威=fork/main"** | 见 P2-1 的逐项行号对照 | 全程 |
| **R-9** | **方案文档本身在版本控制外**：`docs/audit/开源项目借鉴总览-2026-11-05.md` 与本方案均为 untracked（`git status` 显示 `??`），借鉴总览第 3 行自述"本地在途草稿（未提交、未过 PR/4 CI）" | `git log --all -- <file>` 零命中 | 文档质量门禁 |
| **R-10** | **#33 本身未落地**：`docs/verification/` 目录不存在，`AGENTS.md` 对 `verification|最窄验证|未验证项` 零命中 ⇒ 方案 §2/§10 无格式可对照，只能自建 | 实测 `git ls-tree` / `git grep` | 文档质量门禁 |

---

## 评审官附注（给 party mode 主持）

本轮评审的三条可操作主线，按优先级：

1. **P0-1（Q1 哨兵自测）是最重的一条**——方案自己写下了"CI 门禁**静默通过**"这个负面实证，却把修复的唯一保障交给了新机制，而新机制本身无验证。这是本次评审的核心发现，建议直接进入下一轮必改清单。
2. **§8 的"看起来有验收"问题**——10 类指标中 5 条无数据源、2 条的核心数据源是仓库自标"非真实数据"的仿真器。方案第 271–273 行的"北极星"是 n=1 存在性陈述，无失败判据。这不是措辞问题，是需要重写一节的问题。
3. **与借鉴总览的落地脱节**——#11/#14 仍是待实施，方案 §7 第三阶段无任何对抗性测试工程项，#28 桌面接线 blocked 未被识别。方案 §7 与 `v3-backlog.md` 的 B# 体系零交叉，需先登记再排期。

**明确不建议**：本评审不建议以本方案更优为由绕开 #11/#14/#21/#22/#28 的既定裁决，也不建议用新指标替代 G9 验收线。若方案认为某条借鉴点在此轮场景下应调整，正确写法是"待澄清：建议由用户裁决"（见 F-1～F-6），而非直接另立机制。

**未验证项声明**：本评审的 §2/§10 结论中，"方案文档内容"部分为**已读全文**（412 行，逐行）；"仓库代码"部分全部以 `fork/main`@`248132c` 为基准实测（git cat-file / git grep / git ls-tree）；**未实跑 pytest、vitest、CI**（故本报告不引用任何"用例通过"结论，只引用"用例存在"与计数）；**未实跑 zcode/openfde**；**未连接活库**（故 `agent_runs`/`workflow_runs` 真实行数未实测，§8 各指标的实际样本量未知）。测试用例计数方法：`grep -c "^\s*def test_"`（对 `class` 内方法与参数化可能低估，已在 R-5 单列说明）。

[Agent ID: agent-c930248c-6044-428b-8b9b-a83a9cd3ad07]