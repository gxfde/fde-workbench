# AI 原生化学习闭环 2.0 设计稿-v1.1

> **性质**：设计轮产物（纯文档零代码零迁移零路由）。**设计稿 ≠ 实施授权**——批准后按 §4 拆轮排期，逐轮独立 PR、独立验收。
> **版本**：v1（PR #450，`a719943b`）→ **v1.1**（本版）：按五专家评审会（2026-11-13，《…-多专家评审-v1.md》）回写合并 P0 七项＋P1 全项；§6 六条拍板**全裁决**（1-4 条＋5 升／6 平台级，均蔡工 2026-11-13 确认）。
> **缘起**：蔡工 2026-11-13 拍板——①先立项正式设计稿；②进化载体聚焦「动态经验卡（Lessons）＋知识库 Skill」（零改码、密码审批热生效/回滚）并同步覆盖代码级 Prompt 模板。
> **取证基线**：fork/main `2054ea43` 现测锚点；评审轮补充现测（`evaluation_rules.py`/`extensions_service.py`/`runner.py` 等新锚随文标注）。

---

## §0 结论速览

1. **骨架全绿、回路六断**：L1/L2/L3＋V3.2 G4-G7＋N2/N4/N6 在役；「真执行→真归因→AI 起草→受控热生效→统计显著验证」主回路六断点（§1.2，全部实测；断点⑥＝生产 lessons 注入恒关的键名错配，评审会五方独立复核一致）。
2. **三载体协同热生效**（评审后定型）：
   - **Lessons**：`agent_lessons` 动态层（`LESS-DYN-` 前缀、不可变行、status CHECK）∪ seeds 出厂底座；装载零缓存直读＝真热生效；
   - **Skill**：**双闸链**＝`release_channel` 记账（密码）→ 既有 `publish_skill`（密码＋test_report）滚 `current_version_number`；AI 草稿**禁 personal scope**；回滚＝指针回指旧不可变版本行；
   - **Prompt Overlay**：`prompt_overlays` 追加式片段（≤200 字、陈述式句式闸、purpose 闭集白名单、**v1 排除 diagnostics.\* 公网面**）；装载函数 `ai/overlays.py` 在 `execute_ai_prompt`（DSH/降级分叉前）与 `DeepSeekClient.complete_json` 直连腿**两点共用**；指纹按注册表常量算（模板身份不破），归因走 `AICallAudit.context_payload_json` 显式列。
3. **污染防线升级（评审 P0-Ⅰ）**：蒸馏输入改**字段允许名单投影**——evidence_refs/reason/note 一律不进蒸馏面（L-A 判据证据逐字携带答案文本、L-B 模型可复述 rubric 关键句两处破口已实测闭合）。
4. **验证真化**：回归可配 adapter/model_mode；噪声带闸机械化（带与轴存档于套件、现算轴不符 ⇒ 409 fail-closed）；模型层判定独立 `model_verdict` 键不动既有 verdict 闭集。
5. **拆轮**：L4（真执行面＋三源归因＋AI 起草）→ L5（三载体热生效＋回归真化）→ L6（真实交付反哺）。

---

## §1 现状取证（`2054ea43` 现测；评审补充锚点随注）

### 1.1 已在役的骨架（不重造）

| 面 | 锚点（现测） | 事实 |
|---|---|---|
| 执行面 | `simulation/adapters/mock.py:36`；`adapters/real.py:105-187`（`:174-176` structured=False） | mock＝确定性替身；real＝宿主 zcode ≈30min/题 |
| 评估面 | `simulation/evaluator.py:112`（L-A＋L-B）；`:324-371`（L-C，`evaluator_id="human:{id}"` `:356`；**每次插新行无幂等**——`get_evaluation_report:311` 取 `human[-1]` 为终裁） | 幂等 `(run,层,评估器,规则版本)` `:136-143`；`model_mode="stub"` 缺省 `:117` |
| 归因账本 | `workbench/models.py:938`（AICallAudit，表 `:952`，`prompt_version/prompt_fingerprint` `:980-981`，**无 metadata 列**）；`ai/auditing.py:13`（purpose 必填）；`:47-54` 指纹语义＝**模板身份**（同模板不同输入同指纹） | 四层归因在位 |
| 提案面 | `simulation/improvement_service.py:210-325`（train-only `:238-251`、confirmed-only `:252-267`、指纹去重 `:269-280`，canonical=`{findings,target}` `:62-68`）；模型 `simulation/models.py:357-411`（`target_json:388`/`override_json:395-397` 只收 `{run_config:{…}}` `:294-302`/`release_json:411`；`models.py:363-364` 注释「正文零触碰」） | 提案状态机＋唯一指纹 |
| 发布通道 | `simulation/release_channel.py:88`（admin＋密码＋note＋回归计划在案 `:104-110`）；`:138` 回滚；`:179` 复审工单；静态钉「引用面 ⊆ {models, improvement_service, release_channel}」＝`improvement_service.py:9-11`（评审勘误：v1 引 :17-19 属行号漂移，符号语义吻合） | **受控记账面**——v1 要演进的正是在此 |
| Skill 面 | `control/skill_center.py:4-16`（DB 权威：`skill_definitions`/`skill_versions` 不可变版本行＋`current_version_number` 指针＋published 闸）；**写面在 `control/extensions_service.py`**（评审补测）：`publish_skill` 四重闸＝in_review＋`_require_system_operator`＋密码＋**test_report_json 或 waive**（`:374-381`）；`rollback_skill` 同尺（`:388-418`）；`save_personal_skill` **personal scope 保存即 published 零闸**（`:236`） | Skill 有独立审批闸＝**双闸链事实基础** |
| Prompt 面 | `ai/prompt_registry.py:36`（12 常量，key 点分风格如 `quality.testcase_draft`）；纪律 `:14-16`（版本-指纹双绑、正文不入库）；purpose 字面值为下划线风格（如 `quality_testcase_draft`，`quality/draft.py:60`）——**两种字符串并存**（评审 P1） | 注册表在役 |
| 回归面 | `simulation/regression_service.py:154-163`（`_run_group` 硬编码 mock＋缺省 stub）；候选合并 `:202-217`；过拟合闸 `generalization_gap>0.15` `:260-266`（**仅 note 文本，release 无机械拦截**——评审 P1） | 五项检查在位 |
| 知识面 | `agents/lessons.py:28/58/88`；接线 `agents/service.py:360-361`；配置 `config.py:207-209`（`agent_lessons_*`，env 键＝`FDE_AGENT_LESSONS_*`，缺省 enabled=**True**） | 渲染闸在位 |
| 读数面 | `docs/audit/训练场分布读数-L2底册-1.md`（噪声带 0.1049＝`rubric-v1|model:server` 轴锚点 n=3） | 判定规则已实证 |

### 1.2 六断点（全部实测）

1. **执行面失真**：默认 mock 测的是替身；real 30min/题不可迭代。
2. **归因面失明**：`analyze_run`（`improvement_service.py:136-143`）只读 L-A；L-B/L-C 完全不进归因。
3. **蒸馏面缺失**：无 AI 起草端点；提案无结构化载荷；桌面无创建入口（#448 在途补的是发布钮与原文视图）。
4. **验证面假绿**：回归写死 mock＋stub；噪声带未接。
5. **回流面断路**：发布只翻状态；lessons 锁静态文件；Skill 无起草接线；Prompt 无治理面。
6. **断点⑥（潜伏）**：`lessons.py:95/111/112` 读 `fde_agent_lessons_*` 而 `config.py:207-209` 字段名 `agent_lessons_*`——getattr 恒走缺省 False ⇒ **生产注入恒关**；测试假 settings（`test_lessons_wiring.py:145-147`）自带 fde_ 前缀键掩盖。**v1.1 裁定（评审）**：修 **lessons.py 侧**（改 config 名会造 `FDE_FDE_` 死键——CR-046 家族，`config.py:28-32` alias 先例）；.env.example 无该键 ⇒ 零部署兼容风险；**修复＝默认开启的行为翻转**（config 缺省 True）——L4 须带回归面＋假 settings 测试同步修正＋**用 `create_app` 真实 Settings 断言生效/可关的验收钉**（同坑已两次复发）。

---

## §2 六断点 × 方案设计（v1.1 按评审修订；否决留痕）

### 2.1 断点①：NEW `adapters/workbench.py`（API 内真模型执行面）【v1.1 重写】

- **适配器**：第三档 `adapter_mode="workbench"`（mock/real 保留）。probe＝真模型生成下一问；analyze/design＝真模型按 mock 同款 JSON 契约（结构化失败回落自由文本 `structured=False`，沿 `real.py` 语义）；implement/validate 复用确定性腿（real.py probe 委托 mock 先例）。
- **runner 改造（评审 P0-Ⅴ，v1 漏写）**：现有循环全程传同一 `base_ctx`（disclosed 恒空，`runner.py:161-178`）——改为循环内逐轮 `dataclasses.replace(base_ctx, disclosed=customer.disclosed_facts, config={**base_ctx.config, "history": history})`；mock 忽略新键 ⇒ 零回归。
- **候选载荷通道**：run config（`create_run` 放行任意 dict，`run_service.py:104-106`）→ `runner.py:172` 合入 `ctx.config["candidate_payload"]`；**run_key 含 config 指纹**（`run_service.py:41-50,123-130`）⇒ 基线/候选组天然分流。
- **注册两处**：`models.py:60 ADAPTER_MODES` ＋ `adapters/__init__.py:23-32 build_adapter`（闭集现无测试断言，扩值冲击面小——评审实测）。【**L4 施工勘误（2026-11-14）**：注册之外还有两处 DB 落点本稿漏记——`simulation_runs.adapter_mode` 列宽 `String(8)`（"workbench" 9 字符放不下，须扩 `String(16)`）与表上 `ck_simulation_runs_adapter_mode` CHECK 闭集 `('real','mock')`（须扩 `'workbench'`）；两处已随迁移① `d4b7e2f9a6c1` 落地，不随迁则 workbench 运行行在 DB 层必被拒。】
- **成本口径（评审修正）**：实际 **10 次模型调用/题**（6 probe＋4 相位，`runner.py:176-289`）；`cost_json` 现硬编码 `"tokens": 0`（`runner.py:315-321`）——须接 DeepSeekClient usage 回填，否则回归 cost_delta 失真。模型槽位 NEW `deepseek_simulation_workbench_model`（缺省回落评估槽位）；purpose=`simulation_workbench`（审计＋J-1＋注册表 +1）；**J-1 动态插值例外**：DB 载荷内插 system 消息须登记 `_KNOWN_EXCEPTION_VARIABLES`（`test_prompt_hygiene_jseries.py:31-52`，沿 `industry_template.context` 先例）。
- **执行方式**：单跑 30-60s 同步（`run_service.py:153-154`）会卡请求——单跑与回归一并走后台队列；桌面验收拆两层：CI 用 mock DeepSeekClient seam 钉（契约/回落/audit 行），真机证据另附 run id＋活库取证（沿 G9b 先例）。
- 否决：全量切 real；把 mock 做逼真。

### 2.2 断点②：`analyze_run` 三源化【v1.1 补查询口径】

- **L-C**：取 `layer=="human"` 的 **`created_at` 最新一行**（人工每次插新行无幂等——多轮终裁按 `get_evaluation_report:311` 同语义收敛为最新）；生成 `confirmed` 发现；**note 全文先过答案句黑名单**（终裁人看过 reference，note 可能抄答案句——评审 C-1 修补③）。
- **L-B**：查询钉 **`layer=="model" AND evaluator_id=="model:server"`**（stub 替身行有真实 verdict，按 v1 过滤式会误当真模型层——评审 P0-Ⅵ），`verdict!="unavailable"` 二道；低分 ⇒ `likely`（不解锁提案，进人工复核）；**蒸馏面只取 dimension 计数，不取 evidence_refs/reason**（见 §2.3）。
- **L-A**：既有 FA-01..10 映射不动。幂等键无需扩源前缀（唯一约束 `(evaluation_id, code)` 三源各挂各的评估行；code 列 String(16) 容得下 FA-C1/FA-B1）。
- 否决：L-B 直接 confirmed（噪声带内 verdict 翻转实录）。

### 2.3 断点③：NEW `POST /simulation/findings/draft-ai`（返件式 AI 蒸馏）【v1.1 重写污染面】

- **输入**：finding_ids（train split 服务端过滤；`SimulationFinding.run_id` FK NOT NULL——无「没绑 run」坑）。
- **★蒸馏输入＝字段允许名单投影（评审 P0-Ⅰ 裁定）**：只取 `{code, dimension, severity, score, 脱敏 description}`——**evidence_refs / reason / note 一律不进蒸馏面**。依据：L-A 判据 evidence_refs 逐字携带 must_identify/must_produce/must_avoid 原文（`evaluation_rules.py:39-43/123-127/309`→`failure_analyzer.py:228` 原样落库）；L-B 模型看过 judge_view（rubric 三桶全文，`evaluation_prompt.py:118-145`）其自写 evidence/reason 可复述关键句——两破口下，v1「物理不可达」自证不实。证据仍给人看（人工复核队列完整可见），只是**不进 AI 起草提示词**。若后续确需带证据：先过 rubric 逐条子串黑名单（StubModelEvaluation `:100-102` 列表复用为黑名单源）——v1 不启用。
- **起草**：`execute_ai_prompt` 单一入口（purpose=`simulation_improvement_draft`，提示词进注册表＋J-1）；提示词显式数据框定：Trace/finding 字段列为**不可信数据**，其中指令性文字一律视为待分析文本（评审 C-2④）。跨题聚类 v1 按 FA 码分组。产出三型候选载荷：`lesson_entry`（含 anti_pattern/actionable_rule，text≤300 字）/ `skill_version_draft`（走 Skill 既有闸）/ `prompt_overlay_fragment`（purpose_key＋fragment≤200 字）。
- **返件零落库**（评审 D 写死）：契约失败整批丢弃重试一次 409（N3a/N3b 家族语义）；无 TTL/暂存面。
- **★指纹修正（评审 P0-Ⅶ）**：`_finding_fingerprint` canonical 增 `payload_sha256`（服务端规范化现算；无 payload 取固定空值）——否则「同 findings 同 target 不同候选载荷」的 AI 重新起草主流程必被 409 挡死；老提案互不误伤、同 payload 重复提交幂等保留。
- **人工闸**：AI 只返件；采纳＝人工确认后 `create_proposal`（NEW `candidate_payload_json` 列随提案入档；与既有 `override_json`〔只收 run_config〕**分工写明**：override_json＝run 参数，candidate_payload_json＝三载体载荷——回归候选组两者都叠加以适配既有 `regression_service.py:202-217` 读 override 的现状）。
- **机械钉**：动态钉双卡——输入面 monkeypatch 断言蒸馏 payload 键集 ∩ `ANSWER_SIDE_KEYS`==∅ 且无 evidence_refs/reason 键（键清单从 `schemas.py:35` 单一真身取）；输出面返件夹带答案键 ⇒ 拒。静态钉：蒸馏器模块 AST import ⊆ 白名单（禁 scenarios.loader/reference 面），沿 valve 钉 `_import_targets` 手法；**污染阀既有钉关系（评审核）**：治理模块全落 `fde_api/simulation/` 内则旧 valve 钉零改动覆盖「diagnostics 禁 import 治理模块」。
- 否决：蒸馏器读 reference；AI 直接建提案。

### 2.4 断点④：回归真化＋噪声带闸【v1.1 机械化全套采纳评审设计】

- `_run_group` 参数化：`adapter_mode`/`model_mode` 从 `suite.baseline_config` 透传（缺省 mock/stub＝零回归）；候选组叠加提案 `override_json.run_config`＋`candidate_payload_json` 的 run 级沙箱注入（config 通道，§2.1）。
- **噪声带闸机械化（评审专家三设计）**：①`RunSummary` 加可选 `model_total: float|None=None`＋`evaluator_axis: str=""`（默认值＝既有构造点零改动）；②`compare()` 加 keyword-only `noise_band/noise_band_axis`，输出**独立** `model_verdict` 键（improved/regressed/within_noise/insufficient_data），**顶层 verdict 不动**——既有 4 个纯函数测试零改动、不撞 `ck_regression_results_verdict` CHECK 闭集；③判定值落 `deltas_json`；④**带与轴存档于套件**：`baseline_config_json.noise_band={axis,band,anchor_n}`；`run_regression` 现算轴 `f"{RUBRIC_VERSION}|model:{mode}"` 与存档轴逐位比对，不符 ⇒ **409 `noise_band_axis_mismatch`**（fail-closed——换评估器/模型强制重测锚点带的机械形态）；⑤四钉：within_noise 反例（Δ≤band 且 n≥3 ⇒ ≠improved）／n<3 ⇒ insufficient_data／轴不符 ⇒ 409／缺省常量==0.1049 与 L2 底册双锚。n 的口径＝套件场景数（run_key 幂等使重复回归不增样——评审 E 注记）。
- **过拟合发布闸接线（评审 P1-1 裁定）**：L5 在 `release_channel.release_proposal` 增查——该提案最近一次 `RegressionResult.overfit_risk=True` ⇒ 409（把 v1 的「不得进入发布审批」从 note 文本升级为机械拦截）。
- **异步化**：`model_mode=server` 或 `adapter=workbench` 转后台作业（注册沿 `jobs/handlers.py:44-69` 各域 register 模式＋可选入 `jobs/reconcile.py:80 RECOVERABLE_JOB_TYPES`；重跑幂等由结果指纹＋run_key 复用兜底）；**状态承载复用 BackgroundJob**（零迁移——评审裁定）；UI 轮询；stub/mock 小跑保持同步。
- 否决：单 run Δ 下结论（round16/十七轮证伪族）。

### 2.5 断点⑤：三载体热生效机制（v1.1 按评审重构）

**统一原则**：发布动作＝既有 `release_channel` 密码闸＋（Skill）既有 `publish_skill` 闸＝**双闸链**；生效＝运行时直读已发布行（无缓存＝真热生效；`_render_context` 每 run 一次，QPS 无压力）；回滚＝既有 `rollback_release`（状态翻回＋载荷行 retired，审计链不断）。

**A. Lessons**——NEW 表 `agent_lessons`（落 `agents/models.py`，读方就近、simulation→agents 单向无环——评审落点裁定）：
- 行 schema 与 seeds 同构闭集＋`status ∈ (draft,published,retired)`（CHECK 约束，非 VersionedMixin——评审）＋`source_proposal_id`；**动态行 id 独立前缀 `LESS-DYN-`**（seeds 为 LESS-SOP-，跨层 sha256 唯一、动态 id ∈ seeds id 写入即拒）；**text 变更＝新行**（`text_sha256` 服务端写入侧现算，忽略提案侧携带值——不可变版本行先例）；
- 装载＝seeds 底座（文件序在前）∪ published 动态行（(created_at,id) 序在后）；top_k 竞争时 **seed 优先**；`select_lessons` 逻辑零改动；**种子压制＝v1 局限登记**（证伪种子须改代码下线——评审 P1-5，登记不排期）；
- **热生效测试形状（评审 D）**：同进程两次 `knowledge_snippets_for`（真实 Settings）中间只动 DB 行状态——任何模块级缓存必红；seeds 腿 lru_cache 仅缓存文件腿；
- **宿主 zcode run 留痕**：该面不产生 ai_call_audits 行——lesson 注入快照落 `agent_runs` 快照列（`c8e2a6f0b9d4` frozen_tools 同构先例）或 operation_events（评审 D）。
- 否决：动态层写回 seeds（污染钉扫描面禁入）。

**B. Skill**——**双闸链（评审 P0-Ⅳ 重写）**：
- 链路＝AI 蒸馏起草 `SkillVersion` 草稿（**禁走 personal scope**——`save_personal_skill` 保存即 published 零闸＝绕开全链）→ 人工采纳入提案（`candidate_payload_json.skill_ref`）→ `release_channel` 发布（记账）→ **既有 `publish_skill`**（admin/系统操作员＋密码＋test_report）滚 `current_version_number`＝热生效；test_report 证据＝提案的 RegressionResult（waive 留痕备选）；
- 回滚＝`rollback_skill`（对目标版本同尺闸）指针回指旧不可变版本行；
- v1 验收判据据此改写：Skill 载体验收＝双闸全链走通，而非「发布即注入」。
- 否决：为 Skill 另建发布通道。

**C. Prompt Overlay**——NEW 表 `prompt_overlays`（落 `workbench/models.py`，与 AICallAudit 归因邻接——评审落点裁定）：
- 行＝{purpose_key≡**purpose 字面值**（下划线风格；发布时闭集校验，未登记 purpose 拒发布——评审 P1，解决与注册表 key 点分风格并存问题）、fragment（≤200 字、**仅陈述式**）、status、content_sha256（服务端现算、行不可变、改内容＝新行）、`min_prompt_version`（**数字尾缀解析**，防 v10<v2 乱序；注册表升版后 overlay 不自动失效——升版复核触发登记）、source_proposal_id}；
- **注入拓扑（评审 P0-Ⅱ 重写）**：NEW `ai/overlays.py::load_overlays(purpose)` 装载函数**两点共用**——`execute_ai_prompt`（在 DSH 腿与降级直连腿**分叉之前**注入，防降级路径丢 overlay）＋ `DeepSeekClient.complete_json` 直连腿头部（purpose 在其签名内，天然可得；DSH 关闭部署下 overlay 依然全覆盖）；workbench 适配器经同一函数自读注入自身 system prompt（§2.1）；
- **注入语义与指纹（评审裁定，否决「注入后全文哈希」）**：注入发生在 `compute_prompt_fingerprint` **之后**——指纹仍按注册表常量计算（模板身份、跨 run 聚合归因不破，`auditing.py:47-54` 语义保持）；overlay 归因走 **`AICallAudit` NEW `context_payload_json` 列**（`{"overlay_ids":[...],"overlay_sha256":[...]}`；PG JSON 包含查询可按 overlay 反查受影响调用）；
- **注入闸五件套（评审 C-2）**：①句式静态闸——fragment 限陈述式纪律条款，禁祈使句/第二人称/模式词黑名单（忽略、无视、重新设定、以上指令、system、instructions…中英双语）＋既有 200 字上限；②n-gram 防洗稿——fragment 与源 Trace/产物文本重合上限（被测方产出不得整句进入）；③审批面并排呈现**注入终文**＋purpose＋近 30 天该 purpose 调用量（影响面）；④蒸馏提示词数据框定（§2.3）；⑤**v1 purpose 白名单**：仅内网面（simulation/quality/plans/workflows/dispatch），**`diagnostics.*` 公网面排除**（公网诊断行为不经代码 PR 即可改写＝不可接受；开放须单独拍板）；
- **沙箱同尺**：回归候选组注入的 overlay 同过句式闸（防污染回归读数本身）；
- **N6 纪律受控演进声明**：常量本体零触碰（注册表纪律不变）；overlay 为蔡工 2026-11-13 拍板纳入的登记制例外（仅追加、密码闸、秒回滚、过回归闸）；**替换类改动仍走代码 PR**。✅ 已拍板升格 AGENTS.md 红线（§6-5，蔡工 2026-11-13「升」）——红线条款随 L5 实施轮落 AGENTS.md。
- **静态钉**：两新表**写引用面** ⊆ {各自 models, release_channel 执行器}（装载读面 lessons.py/overlays.py/ai_server_client.py 加入允许集）——沿既有 AST 钉手法（评审 P1-6）。
- 否决：热改代码常量；三载体三套闸；三个例外。

---

## §3 与在途/既有面的边界（v1 原文维持）

| 面 | 状态 | 关系 |
|---|---|---|
| PR #448（在途，桌面五断链） | OPEN | 其补发布钮＋原文视图；本稿 L4 创建/AI 起草入口、L5 发布钮挂真载荷建立其上，rebase 融合 |
| PR #426/#439（已合并） | 已合并 | L4 场景选择器建立在 r44 行为之上 |
| N6 质量路由 | 在役 | 不接——攒轴组样本，登记 L6 可选 |
| lessons 展示面 | 2026-11-12 拍板不增设 | 不重开 |

---

## §4 实施拆轮（v1.1 按评审扩容；批准后逐轮立任务书）

| 轮 | 内容（v1.1 扩容处加粗） | 验收判据 |
|---|---|---|
| **L4** 真执行面＋归因真化＋AI 起草 | NEW `adapters/workbench.py`＋**runner 逐轮 ctx 改造**＋**ADAPTER_MODES/build_adapter 注册**＋**cost usage 回填**＋workbench 槽位＋J-1 例外登记；`analyze_run` 三源化（**L-B 钉 model:server、L-C 取最新、note 黑名单**）；NEW `draft-ai`（**允许名单投影**＋返件零落库＋**指纹 payload_sha256**）＋`ImprovementProposal.candidate_payload_json` 加列（迁移①）；**断点⑥修 lessons.py＋默认开启翻转回归面＋假 settings 测试修正**；桌面「失败→AI 起草→建案」＋场景选择器 | workbench 单题端到端＝**CI mock seam 钉**（契约/回落/audit 行 purpose+version）＋**真机证据**（run id＋活库）两层；L-C confirmed/L-B likely 分流钉（U1/U2：likely 单独提案 409）；analyze_run 幂等钉（U3：多 human 行不增殖）；**真实 Settings（create_app）断言 lessons 生效/可关**；蒸馏输入键集钉（无 evidence_refs/reason 且 ∩ 答案键=∅）；指纹 payload_sha256 钉；mock/real 零回归；变异三连红→还原绿 |
| **L5** 三载体热生效＋回归真化 | NEW `agent_lessons`（agents/models.py）＋`prompt_overlays`（workbench/models.py）＋**`AICallAudit.context_payload_json` 加列**（**迁移②：两表＋一列**）；`ai/overlays.py` 两点共用装载＋注入五件套；`release_channel` 三支执行器＋**Skill 双闸链接线**＋**overfit 发布闸**；lessons 双层装载＋断点⑥回归；回归参数化＋噪声带四钉＋异步（**BackgroundJob 状态承载**）；桌面发布/回滚挂真载荷（融合 #448） | 发布→下一 run 注入（**overlay：audit 行 context_payload_json 在场；lesson：同进程两次调用行为钉**；skill：**双闸链走通**）；回滚→立即消失；噪声带四钉全绿；**overfit=True ⇒ release 409 反例钉**；两新表写面静态钉；**既有套件零回归显式条目**（regression/e2e/runner/improvement/lessons_wiring 全绿＋不带新键行为逐字节不变）；**审计清单三件套＋archify 四件套刷新＋迁移 docstring 父链登记＋test_migrations HEAD 断言**；污染钉全绿 |
| **L6** 真实交付反哺 | NEW 宿主侧只读脚本 `extract_case_from_project.py`（门禁 fail→pass 迁移与产物拒收 → 真相层 `import_card_v1` 候选卡；**宿主通道五边界先例裁定**：沿 `lead_ledger_append.py`〔人工发起＋只插不改＋幂等〕，服务端容器不直连宿主 CLI）；复用 L1 管线人工激活；L-C 原文核对视图收口 | 一次真实驳回/拒收→脱敏候选卡落真相层（不入仓/不入被扫面/代号化/人工激活）；**预算记账主体写明**（模拟域跑批以服务账号计） |

**顺序**：L4→L5 强串行；L6 独立可并行。**体量警示（评审）**：L4 实际改动面≈v1 列表×1.5（runner/注册/cost/J-1/测试/桌面均要动）——任务书排期按扩容列。

---

## §5 红线自证（v1.1 修订）

| 红线 | 落法 |
|---|---|
| 客户真实资料不入 git/远端 | 蒸馏输入＝simulation 域合成数据＋代号化 trace 的**允许名单投影**；L6 走 T-A2＋真相层（沿 lead_ledger_append 宿主脚本先例：人工发起＋只插不改＋幂等） |
| 评测集污染隔离 | **v1.1 修正自证**：reference 对**蒸馏面**不可达由允许名单投影机械保证（evidence_refs/reason/note 不进 AI 起草输入；L-A/L-B 证据携带答案原文的两处破口已实测并闭合）；返件双卡＋静态钉；seeds 禁动态写；治理模块落 simulation/ 内则旧 valve 钉零改动覆盖 |
| AI 不代拍板 | AI 只返件（零落库）；热生效恒经双闸（release_channel＋publish_skill）密码审批；L-B 只 likely；**审批面呈现注入终文＋影响面** |
| 进化可判定可归因 | audit 行 purpose＋常量指纹＋`context_payload_json`（overlay id+sha256 可 SQL 反查）；lesson 注入留痕（audit 或 agent_runs 快照）；RegressionResult↔proposal↔run 全链；噪声带轴存档＋mismatch 409 |
| 不自动改提示词（N6） | 常量零触碰；overlay 登记制例外（仅追加/密码闸/秒回滚/过回归闸/句式闸/purpose 白名单排除公网面）；替换仍走代码 PR；✅ **已拍板升格 AGENTS 红线（§6-5，2026-11-13）——随 L5 落 AGENTS.md** |
| 宿主通道五边界 | L6 脚本沿 lead_ledger_append 先例裁定并显式登记；服务端容器不直连宿主 CLI（workbench 走 API） |
| 按量付费 key/预算闸 | workbench/蒸馏/异步回归全走既有预算门；**模拟域跑批记账主体＝服务账号**（L4 写明）；CI 恒 mock seam、真机次数入任务书限额；全量回归（≈10 调用×134 题）配采样策略注记 |
| 多客户 M 线 | overlay/lesson v1 **平台级**生效（当前单租户实态）＋登记；✅ **已拍板平台级（§6-6，2026-11-13）**——按 org 作用域 L6 后再议 |
| 台账三同步 | 各实施轮随轮回写；审计清单三件套＋archify 随轮（L4/L5 DoD 显式列） |
| B#35 | 零第三方结构化表达（评审核验通过） |

## §6 拍板项（v1.1 更新：六条全裁决——蔡工 2026-11-13 确认 1-4＋「5 升 6 平台级」）

| # | 事项 | 推荐 | 裁决 |
|---|---|---|---|
| 1 | Overlay join key＝purpose 字面值且仅追加 | 确认 | ✅ **蔡工 2026-11-13 确认**（「4 条待拍板按你的推荐确认」） |
| 2 | workbench 模型槽位独立键、缺省回落评估槽位 | 确认 | ✅ 同上 |
| 3 | 噪声带缺省 0.1049＋轴绑定 | 确认 | ✅ 同上（v1.1 已升级为套件存档轴＋mismatch 409 机械形态） |
| 4 | L-B likely 复核：v1 仅列表标记不建审批流 | 确认 | ✅ 同上（复核动作＝人工按 L-C 路径补终裁） |
| 5 | **N6 受控例外升格 AGENTS.md 红线**（评审建议文案：「overlay 只许追加式片段（≤200 字）·purpose 闭集·经 release_channel 密码闸·替换式改动仍走代码 PR·prompt_registry 常量纪律零触碰」） | **升**（防未来轮次以先例扩权） | ✅ **升——蔡工 2026-11-13 确认**（「5 升 6 平台级」）；红线条款随 L5 实施轮落 AGENTS.md |
| 6 | **overlay/lesson 跨 org 生效口径**：v1 平台级（当前单租户实态）＋登记，按 org 作用域 L6 后再议 | 平台级＋登记 | ✅ **平台级——蔡工 2026-11-13 确认**（「5 升 6 平台级」）；按 org 作用域 L6 后再议 |

## §7 来源对照

独立撰写；机制描述以本仓代码为唯一事实源（§1 锚点现测于 `2054ea43`＋评审轮补测）；与《三缺口设计稿-2026-11-11》为接续关系（其 L1/L2/L3 已实施合并，本稿不推翻其任何拍板）。v1.1 修订依据＝《…-多专家评审-v1.md》§1 合并清单与 §7 处置表。
