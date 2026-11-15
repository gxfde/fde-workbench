# AI 原生化学习闭环 2.0 设计稿——多专家评审纪要-v1

> **性质**：评审会纪要（纯文档零代码）。评审对象＝《AI原生化学习闭环2.0-设计稿-v1》（PR #450，squash `a719943b`）。
> **评审会**：蔡工 2026-11-13 指令「4 条待拍板按推荐确认＋召开专家会议全面讨论评审」。五位评审官并行独立评审、逐锚实测（基线 `2054ea43`），证据密度对齐仓内先例（`docs/audit/experts/` 五段式）。
> **处置**：本纪要 §1 会议结论与合并 P0/P1 清单已逐条回写设计稿 **v1.1**（同 PR）；§6 新增待拍板 2 条待蔡工裁决。

---

## §0 判定汇总

| 评审官 | 视角 | 判定 | P0 | P1 |
|---|---|---|---|---|
| 专家一 | 架构与治理 | 有条件通过 | 2 | 4 |
| 专家二 | 实现可行性 | 可落地，3 处 P0 须先修 | 3 | 6 |
| 专家三 | 测试与验证 | 有条件通过 | 2 | 3 |
| 专家四 | 数据与迁移 | 有条件通过 | 2 | 5 |
| 专家五 | 红线与安全 | 原则可行，2 P0 先修再批 | 2 | 2 |

**共识**：六断点诊断全部实测为真（含断点⑥ lessons 键名恒关——五位独立复核一致）；三载体架构方向与拆轮顺序成立；**照 v1 现稿施工会在七处撞墙**，全部可在设计层修复，不推翻架构。

---

## §1 会议结论（合并 P0 清单——v1.1 已逐条回写）

| # | 合并 P0（来源） | 一句话裁定 | v1.1 落点 |
|---|---|---|---|
| P0-Ⅰ | **污染单向阀两处真破口**（专家五 C-1；专家一佐证） | v1「reference 物理不可达」自证不实：L-A 判据 evidence_refs 逐字携带答案侧文本（`evaluation_rules.py:39-43/123-127/309`→`failure_analyzer.py:228` 原样落库）；L-B 模型看过 judge_view（含 rubric 三桶），自写 evidence/reason 可复述关键句；既有键名闸查键不查值、redact 不脱答案句 ⇒ 攻击链可复现。**裁定**：蒸馏输入改**字段允许名单投影**（只取 code/dimension/severity/score/脱敏 description——evidence_refs/reason/note 一律不进蒸馏面）＋机械钉（蒸馏 payload 键集 ∩ 答案键名 = ∅、无 evidence_refs 键）；L-C note 同过答案句黑名单 | §2.3 重写＋§5 行改写 |
| P0-Ⅱ | **Overlay 注入拓扑失真**（专家一 P0-1＋专家二 P0-3） | `DeepSeekClient` 9 处直连实例化；DSH 关闭时 `complete_json` 直连腿不经 `execute_ai_prompt`；workbench 自述复用直连腿 ⇒ overlay 对学习闭环自身执行面不生效。**裁定**：NEW 装载函数 `ai/overlays.py::load_overlays(purpose)` 下沉两点共用——`execute_ai_prompt`（DSH 腿+降级腿分叉**之前**）与 `DeepSeekClient.complete_json` 直连腿头部（purpose 在其签名内，天然可得）；workbench 适配器经同一函数自读注入 | §2.5C 重写 |
| P0-Ⅲ | **Overlay 新提示词注入面缺闸**（专家五 C-2＋专家一 P1-4/P1-3） | 脱敏≠去指令注入；`misleading_request` 字段即设计好的诱导文本；公网 `diagnostics.report` purpose 可被治理片段改写；purpose（下划线）≠注册表 key（点分）两字面值并存。**裁定**：五件套防线——①句式静态闸（仅陈述式纪律条款：禁祈使句/第二人称/模式词黑名单中英＋既有 200 字上限）；②n-gram 防洗稿（被测方产出不得整句进 overlay）；③审批面并排呈现注入终文＋purpose＋近 30 天影响面调用量；④蒸馏提示词显式数据框定（Trace 列为不可信数据）；⑤`purpose_key ≡ purpose 字面值`＋发布时闭集校验＋**v1 白名单排除 `diagnostics.*` 公网面** | §2.5C 增补 |
| P0-Ⅳ | **Skill 载体「零新治理」不成立**（专家一 P0-2） | skill 写面在 `control/extensions_service.py`：`publish_skill` 四重闸（in_review＋system_operator＋密码＋**test_report_json 或 waive**）；`save_personal_skill` personal scope **保存即 published 零闸**；`rollback_skill` 对目标版本同尺。**裁定**：明写**双闸链**＝release_channel 记账 → `publish_skill` 滚指针；AI 草稿**禁走 personal scope**（免审直发布＝绕开全链）；test_report 证据＝提案的 RegressionResult（waive 留痕备选） | §2.5B 重写 |
| P0-Ⅴ | **workbench 执行面接线缺口**（专家二 P0-1＋P1-1） | runner 访谈循环全程传同一 `base_ctx`（disclosed 恒空，`runner.py:161-178`）——真模型 probe 看不到客户已说什么。**裁定**：循环内逐轮 `dataclasses.replace(base_ctx, disclosed=…, config={…, "history": …})`；候选载荷通道＝run config → `ctx.config["candidate_payload"]`（run_key 含 config 指纹⇒基线/候选天然分流）；`ADAPTER_MODES` 与 `build_adapter` 注册 workbench；实际 10 次调用/题；`cost_json` 硬编码 tokens:0（`runner.py:315-321`）须接 usage 回填 | §2.1 重写 |
| P0-Ⅵ | **L-B/L-C 查询口径**（专家二 P0-2＋专家三 E-1） | stub 替身行有真实 verdict——按 v1 过滤式会把 stub 当真模型层；L-C 无幂等多行。**裁定**：L-B 钉 `evaluator_id=="model:server"`（`verdict!="unavailable"` 二道）；L-C 取 `created_at` 最新一行；幂等键无需扩源前缀（唯一约束 (evaluation_id, code) 三源各挂各的评估行天然不撞） | §2.2 补写 |
| P0-Ⅶ | **提案指纹挡死 AI 重新起草**（专家四 P0-1） | `_finding_fingerprint` canonical 只含 {findings, target}——同 findings 同 target 不同候选载荷的二次起草必 409。**裁定**：canonical 增 `payload_sha256`（服务端规范化现算；无 payload 取固定空值——老提案互不误伤、同 payload 重复提交幂等保留） | §2.3 补写 |

**合并 P1（v1.1 一并回写）**：噪声带闸机械化全套（专家三 P0-1 设计采纳：`RunSummary` 可选 `model_total/evaluator_axis`、`compare()` keyword-only `noise_band` 输出独立 `model_verdict` 键不动顶层 verdict、带与轴落 `baseline_config_json` 存档、现算轴不符 ⇒ 409 fail-closed、四钉）；断点⑥修 `lessons.py` 侧（config 侧会造 `FDE_FDE_` 死键——CR-046 家族）＋**修复＝默认开启的行为翻转**须带真实 Settings 验收钉（`create_app` 实例，非 SimpleNamespace——同一坑已两次复发）；指纹按注册表常量计算（模板身份），overlay 注入发生在指纹计算**之后**，归因走 `AICallAudit` NEW `context_payload_json` 列（否决「注入后全文哈希」——破坏模板聚合归因，auditing.py:47-54 注释语义）；`candidate_payload_json`（三载体载荷）与 `override_json`（run 参数）分工写明；lessons 动态行 `LESS-DYN-` 前缀＋不可变行＋sha256 服务端现算＋种子压制登记 v1 局限；`min_prompt_version` 数字尾缀解析＋升版复核触发登记；J-1 `_KNOWN_EXCEPTION_VARIABLES` 登记动态插值例外；回归异步状态承载复用 BackgroundJob（零迁移）；过拟合发布闸 L5 接线（提案最近 RegressionResult.overfit_risk=True ⇒ release 409）；两新表**写引用面**静态钉 ⊆ {models, release_channel}（装载读面加入允许集）；表落点 `agent_lessons`→`agents/models.py`、`prompt_overlays`→`workbench/models.py`；宿主 zcode run 无 audit 行——lesson 注入留痕走 `agent_runs` 快照列（frozen_tools 同构先例）或 operation_events；L4/L5 DoD 补清单三件套＋archify＋迁移 docstring 父链＋既有套件零回归条目；workbench 验收拆 CI mock seam 钉＋真机证据两层；蒸馏返件**零落库**写死；§5 补三条自证（宿主通道五边界按 `lead_ledger_append.py` 先例裁定／模拟域跑批预算记账主体／overlay 跨 org 登记）；release_channel 行数入 size budget 观察。

**锚点勘误**：ImprovementProposal 实位于 `simulation/models.py:357-411`（v1 §1.1 上下文歧义，v1.1 已点名包路径）；`release_channel` 静态钉实为 `improvement_service.py:9-11`（v1 引 :17-19 属轻微漂移，按符号重 grep 语义吻合）。

---

## §2 专家一：架构与治理评审意见（判定：有条件通过）

### A. 总评
六断点诊断全部实测为真（断点⑥逐条复核无一虚报）。三载体方向正确、与仓内先例一致。但两个 P0：①「execute_ai_prompt 单一入口」声明与真实调用拓扑不符；②Skill「零新治理」与既有 skill 独立审批闸事实冲突。修完可进拆轮。

### C. 必须修改项
- **P0-1** Overlay 注入点失真：`grep DeepSeekClient(` 实测 9 处直接实例化；DSH 关闭时 `deepseek.py:171` 起直连腿永不经 `execute_ai_prompt`；且 §2.1 workbench 自述复用直连腿——overlay 对回路自身执行面在最常见部署形态（DSH 关）下不生效，回路自断。建议三选一：(a) 注入下沉两点共用装载函数；(b) workbench 强制走 execute_ai_prompt；(c) 明示 overlay 不覆盖 simulation purpose（与回路目标矛盾，不推荐）。另须处理 `structured_completion` 包装指令（`ai_server_client.py:564`）的追加顺序。
- **P0-2** Skill 双闸链：`publish_skill`（`extensions_service.py:359-390`）四重闸＝in_review＋`_require_system_operator`＋密码＋test_report_json 或 waive（:374-381）；`rollback_skill`（:388-418）同尺；`save_personal_skill` personal scope 保存即 published（:236）。§0.3「全部经 release_channel」与 §2.5B「指针建议」自相矛盾；L5 验收对 skill 载体天然不成立。建议：明写双闸链；AI 草稿禁 personal scope；交代 test_report 路径。
- **P1-3** overlay `purpose_key` 命名空间：purpose（下划线，`quality/draft.py:60`）≠注册表 key（点分，`prompt_registry.py:88`，12 key 全量核对）——join 落空＝overlay 静默失效。声明 `purpose_key ≡ purpose 字面值`＋发布闭集校验。
- **P1-4** overlay 适用 purpose 闭集：`diagnostics.report` 在注册表（:108-114）且是公网免注册写面——不经代码 PR 即可改写公网诊断行为。v1 白名单仅内网面，diagnostics.* 排除或单独拍板。
- **P1-5** Lessons 双层无种子压制：「seeds 永为底座」⇒ 证伪的种子经验只能改代码下线；无跨层去重。加 supersedes 字段或明示 v1 局限并登记；sha256 跨层唯一。
- **P1-6** 静态钉形状：现行钉 `ImprovementProposal 引用面 ⊆ {models, improvement_service, release_channel}`（`improvement_service.py:9-11`）；两新表不钉则任何模块可直接写表绕过 release_channel。

### D. 可选优化
① overlay 追加在 `compute_prompt_fingerprint`（`ai_server_client.py:331`）之后执行，保指纹＝模板身份、overlay id 单独入审计；② `system_prompt=None` 调用形态（discovery 任务腿）下 overlay 落点需定义；③ 异步化沿 `jobs/queue.py`＋RECOVERABLE_JOB_TYPES 登记；④ 表落点 `agent_lessons`→`agents/models.py`（simulation→agents 单向无环）、`prompt_overlays`→`workbench/models.py`（与 AICallAudit 邻接）；⑤ `release_channel.py`（现 231 行）+3 执行器后入 size budget 名单。

### E. 待澄清
| # | 事项 | 依据 |
|---|---|---|
| E-1 | DSH 关闭部署下 overlay 覆盖策略三选一 | `deepseek.py:162-171` 双腿分叉；9 处直连实例化 |
| E-2 | Skill AI 草稿 test_report 闸路径与 scope | `extensions_service.py:236,374-381` |
| E-3 | **N6 受控例外应升 AGENTS.md 红线（建议：升）**——现行纪律执行面是 docstring＋AST 钉（管不到 DB 侧片段）；设计稿是单轮文档，未来轮次 agent 只见 AGENTS.md 会拿先例扩权。红线文案建议：「overlay 只许追加式片段（≤200 字）·purpose 闭集·经 release_channel 密码闸·替换式改动仍走代码 PR·prompt_registry 常量纪律零触碰」 | `prompt_registry.py:14-16` |
| E-4 | L-C 多轮终裁 evaluator 幂等键 | `evaluator.py:136-143,356-357` |

### 结论
诊断质量扎实（锚点除静态钉行号轻微漂移外逐位命中）。修 P0 两项＋P1-3/4 并把 N6 例外升 AGENTS 红线后，本稿可作施工依据。

---

## §3 专家二：实现可行性评审意见（判定：可落地，3 处 P0 须先修）

### A. 总评
骨架选型正确（三载体全映射既有在役机制，无重造轮子）。但 ①workbench probe 在现有 runner 下拿不到已披露事实与历史；②L-B 查询会把 stub 替身行当真模型层；③Overlay 注入点与 workbench 通道物理不通。「≈8 次调用」仅在 implement/validate 复用确定性腿时成立。

### C. 必须修改项
- **P0-1** runner 改造：`runner.py:161-173` 构造 base_ctx（disclosed=()）；`:177-178` 循环内全程传同一 base_ctx；`:214-215` 循环结束才挂 disclosed；客户回复只写 trace（`TraceWriter` 纯写面 `trace.py:17-73`）。最小改法：循环内逐轮 `dataclasses.replace(base_ctx, disclosed=customer.disclosed_facts, config={**base_ctx.config, "history": history})`；mock 忽略新键、real probe 委托 mock（`real.py:57-59` 先例）⇒ 零回归。候选载荷路径：`run.context_json`→create_run config（任意 dict 放行 `run_service.py:104-106`）→`runner.py:172` 合入 ctx.config→workbench 读 `ctx.config["candidate_payload"]`；run_key 含 config 指纹（`run_service.py:41-50,123-130`）⇒ 基线/候选天然分流。注册两处：`models.py:60 ADAPTER_MODES`＋`adapters/__init__.py:23-32 build_adapter`。
- **P0-2** L-B 钉 `evaluator_id=="model:server"`（stub 腿产出真实 verdict，`model_evaluation.py:82,152`；同 run 可并存两行，`evaluator.py:193-199`）；L-C 取最新（`record_human_evaluation:349-368` 每次插新行无幂等；`get_evaluation_report:311` 取 human[-1]）。幂等键结论：不需扩源前缀——唯一约束 (evaluation_id, code)（`models.py:324-327`）三源各挂各的评估行；code 列 String(16) 容得下 FA-C1/FA-B1。
- **P0-3** Overlay 与 workbench 通道不重叠（同专家一 P0-1）。推荐 workbench 侧自行读 overlay（与 candidate_payload 同路径）；或改走 execute_ai_prompt（代价：8 调用全走用户预算门＋DSH）。
- **P1-1** runner 实际调适配器 **10 次**（6 probe＋4 产物相位，`runner.py:176-289`）；`runner.py:315-321` cost_json 硬编码 `"tokens": 0`——须接 DeepSeekClient usage 回填，否则回归 cost_delta 失真。
- **P1-2** 断点⑥修 lessons.py 侧：`config.py:316-317` env_prefix="FDE_" ⇒ 字段 `agent_lessons_*` 的 env 键就是 `FDE_AGENT_LESSONS_*`；改 config 名会造 `FDE_FDE_` 死键（CR-046 家族，`config.py:28-32` alias 先例）；.env.example 现无该键（grep 零命中）⇒ 修 lessons.py 零部署兼容风险。**但 config 缺省 enabled=True ⇒ 修复＝默认开启的行为翻转**——L4 须带回归面＋`test_lessons_wiring.py:145-147` 假 settings 同步修正。
- **P1-3** J-1 动态插值：DB 载荷内插进 system 消息撞 `test_prompt_hygiene_jseries.py:68-75` 静态文本钉——按 `industry_template.context` 先例登记 `_KNOWN_EXCEPTION_VARIABLES`（:31-52）。
- **P1-4** AICallAudit 无 metadata 列（末列 prompt_fingerprint，`workbench/models.py:980-986`）——「记 overlay id 集合」需加列迁移；L5「迁移×1 两表」少计。
- **P1-5** 异步状态承载：作业注册点＝`jobs/handlers.py:44-69`＋可选 `jobs/reconcile.py:80 RECOVERABLE_JOB_TYPES`；RegressionResult 无 status 列——UI 轮询需状态面。
- **P1-6** `_run_group` 参数化简单：`:158`/`:163` 两值从 baseline_config 透传即可（`create_run:99-100` 闭集兜底）。

### D. 可选优化
噪声带 0.1049 实测口径是「同 run 重评的评估器噪声」而回归 Δ 是跨组均值差——组间方差未单测可补注记；draft-ai train 过滤无坑（finding.run_id FK NOT NULL `models.py:340-345`）；workbench 响应回显 model_mode/candidate 指纹便于对账；单跑 workbench 同步 30-60s（`run_service.py:153-154`）——桌面单跑也宜入队。

### E. 待澄清
L-C findings code 取值与多轮增殖语义｜L-B 阈值口径与聚类形状｜overlay 双路径（DSH＋降级）注入与指纹语义｜回滚路径执行器｜n≥3 的 n＝套件场景数（run_key 幂等使重复回归不增样）｜L4×#448 rebase 融合。

### 结论
方向可批准，实施前按 C 节修订。体量复核：**L4 最容易爆**（原列「NEW workbench.py＋analyze_run＋端点」实际还要动 runner、ADAPTER_MODES/build_adapter、cost 记账、J-1 例外、假 settings 测试、桌面两处）；L5 次之；L6 独立低风险。

---

## §4 专家三：测试与验证评审意见（判定：有条件通过）

### A. 总评
六断点逐锚复核为实。三源归因、热生效/回滚、污染双卡均可落成机器钉。最大风险：噪声带若落 compare() 顶层 verdict 会打红 4 个既有纯函数测试＋撞 `ck_regression_results_verdict` CHECK 闭集；「过拟合不得进发布审批」只是 note 文本、release 通道并无机械拦截。

### C. 必须修改项
- **P0-1** 噪声带机械化（推荐分工＝compare 判定纯函数、service 装配＋轴校验）：①`RunSummary` 加可选 `model_total: float|None=None`＋`evaluator_axis: str=""`（默认值＝既有构造点零改动）；②`compare()` 加 keyword-only `noise_band/noise_band_axis`，输出**独立** `model_verdict` 键（improved/regressed/within_noise/insufficient_data），顶层 verdict 不动——`test_simulation_regression.py:221-262` 四个纯函数测试零改动即绿；③模型层判定值落 `deltas_json`，不进 verdict 列（CHECK 闭集五值，加值即撞迁移）；④轴绑定权威落 `RegressionSuite.baseline_config_json` 内 `{noise_band:{axis,band,anchor_n}}`；run_regression 现算轴 `f"{RUBRIC_VERSION}|model:{mode}"` 与存档轴逐位比对，不符 ⇒ **409 noise_band_axis_mismatch**（fail-closed 不静默套旧带）；⑤四钉：within_noise 反例／n<3⇒insufficient／轴不符⇒409／缺省常量==0.1049 与 L2 底册双锚。
- **P0-2** 断点⑥验收钉必须用 `create_app` 真实 Settings 实例断言生效/可关——否则同一坑第三次复发（变异判别力家族教训）。
- **P1-1** 过拟合闸二选一：钉现状（措辞改「风险标记钉」）或 L5 显式新增 release 闸（查该提案最近 RegressionResult.overfit_risk）——不能含糊。
- **P1-2** L5 补「既有套件零回归」显式条目：test_simulation_regression/e2e/runner/improvement/lessons_wiring 全绿＋baseline_config 不带新键时行为逐字节不变。已核：这些测试全部显式传 adapter_mode:"mock"（e2e:154 断言 meta）；ADAPTER_MODES 闭集无测试断言（grep 零命中），扩 "workbench" 冲击面小。
- **P1-3** workbench 端到端验收拆两层：CI 钉（mock DeepSeekClient seam：契约/结构化回落 structured=False/audit 行 purpose+prompt_version——沿 N3a 先例）＋真机证据（run id＋活库取证）。

### D. 可选优化
①三源变异三连形状：U1 造 human 行⇒confirmed＋create_proposal 201（复用既有 confirmed-only 闸）；U2 造 model 低分行⇒likely 在场且**单独**提案 409；U3 连跑两次 analyze_run 计数不变＋多 human 行不增殖（M3 判别力落在新增收敛面）；②热生效测试：同进程两次 `knowledge_snippets_for`（真实 Settings）中间只动 DB 行状态——任何模块级缓存必红；seeds 腿 lru_cache 只可缓存文件腿；HTTP 层 release→包含/rollback→消失；③lessons 合并序钉：seeds（文件序）前、动态按 (created_at,id) 后；动态 id ∈ seeds id ⇒ 写入即拒；top_k=1 同 tag 恒取 seed；④overlay 注入须在 DSH/降级两路分叉**之前**；⑤污染双钉与旧 valve 钉关系：治理模块若全落 `fde_api/simulation/` 内，既有钉零改动即覆盖；动态钉输入面 monkeypatch 断言蒸馏 payload 键集∩ANSWER_SIDE_KEYS==∅（键清单从 schemas.py:35 单一真身取）。

### E. 待澄清
L-C 多行收敛（=取最新，建议写死）｜异步「202 受理＋轮询终态」验收条目｜L-B 复核流若后续建流与钉面漂移｜CI 恒 mock seam＋真机限额｜baseline_config 无 schema 校验（轴校验已兜底）。

### 结论
放行前提＝C 项四条落进 §4/§2.4。D-1/D-4 建议随任务书写入。

---

## §5 专家四：数据与迁移评审意见（判定：有条件通过）

### A. 总评
表名零撞车（153 个 __tablename__ grep 现测）；口径 153→155、rev 74→76 与 inventory（table_count=153, revision_count=74, heads=[c8e2a6f0b9d4]）逐位一致。两 P0：指纹挡起草、审计列缺归属。锚点勘误：ImprovementProposal 实在 `simulation/models.py:357-411`。

### C. 必须修改项
- **P0-1** 指纹 canonical 增 `payload_sha256`（`improvement_service.py:62-68`/`:269-280`/`models.py:371` 唯一约束）——L4 主流程「返件→采纳→重新起草不同 payload」必被挡。老/新提案指纹天然不同互不误伤。
- **P0-2** AICallAudit 加 JSON 列（如 `context_payload_json={"overlay_ids":[...],"overlay_sha256":[...]}`）——全文哈希无法反推 overlay 集合；「按 overlay 反查受影响 run」不可实现。注入顺序与指纹语义须钉死。L5「迁移×1 两表」要么并列要么改口径。
- **P1-1** `candidate_payload_json`（三载体载荷）与既有 `override_json`（`models.py:395-397` 注释「{run_config:{...}}」，`improvement_service.py:294-302` 严格只收该形状）分工写明——回归现读 override_json（`regression_service.py:202-217`），否则两条注入通道。
- **P1-2** L4/L5 DoD 缺：审计清单三件套重生成＋archify 四件套＋`test_migrations` HEAD 断言＋迁移 docstring 父链登记（沿 `c8e2a6f0b9d4:3` 格式；施工以迁移 docstring 现测 head 为父，不抄台账行）。
- **P1-3** 动态 lesson id：seeds 样式 `LESS-SOP-001..010`（`seeds/lessons.json:5-91`）——动态行须独立前缀（如 LESS-DYN-）＋id 唯一；text 变更＝新行（text_sha256 绑定不可变），沿 skill_versions 不可变版本行先例。
- **P1-4** sha256 一律写入侧服务端现算（忽略提案侧携带值）；`min_prompt_version` 比较算法未定（v10<v2 字典序乱序——数字尾缀解析或登记序）；注册表升版后 overlay 不自动失效（重复注入风险）——升版复核触发须登记。
- **P1-5** join key 两字符串并存（同专家一 P1-3）。

### D. 可选优化
①表落点：agent_lessons→agents/models.py（simulation→agents 零依赖单向）；prompt_overlays→control/models.py 或 workbench/models.py（与 AICallAudit 聚合）；②静态钉扩钉须把装载读面（lessons.py/ai_server_client.py）加进允许集；③宿主 zcode run 不产生 audit 行——L5「audit 行带 lesson 指纹」在该面不可满足：`agent_runs` 快照列（`c8e2a6f0b9d4` frozen_tools 同构先例）或 operation_events；④status 用 CheckConstraint 非 VersionedMixin（仅 int 计数，与状态机语义不符）；⑤回滚 published→retired 不删行（指纹可对账、审计链不断）；再发布复活 vs 新行待拍板；⑥L-B likely 零迁移可落（confidence 现住 root_causes_json[].confidence，`improvement_service.py:256`）。

### E. 待澄清
审计列形状与迁移归属｜lesson 指纹在无 AI 调用 run 的落点｜再发布复活语义｜min_prompt_version 算法｜join key 命名面｜L4/L5 路由表数口径行归属（490→491、153→155、rev 74→76）｜断点⑥修法（已裁定 lessons.py 侧）。

### 结论
P0-1/P0-2 必须在立任务书前回写；P1 五项随修订补齐；修订后 §4 拆轮表可直接作 L4/L5 任务书骨架。

---

## §6 专家五：红线与安全评审意见（判定：原则可行，两 P0 先修再批）

### A. 总评
锚点现测扎实，主干合红线（单闸收敛、AI 只返件、N6 例外留痕）。但 §2.3「reference 物理不可达」经代码核实**不成立**（L-A/L-B 两旁路均实证），且 overlay 新注入面缺指令注入闸。§5 自证表漏 3 条。均可设计层修。

### C. 必须修改项
- **C-1【P0】污染两破口**：①`evaluation_rules.py:39-43/123-127/309` L-A 判据 evidence_refs 逐字携带 must_identify/must_produce/must_avoid 全文，`failure_analyzer.py:228` 原样拷进 Finding 落库——**今天库里每条 finding 的 evidence_refs 就含 reference 原文**；②`model_evaluation.py:211-216` L-B judge 输入含完整 rubric 三桶（`evaluation_prompt.py:118-145`），`:315-326` 模型自写 evidence/reason 可复述关键句（提示词 :41 还引导按 MI-n/MA-n/MP-n 命名）。双卡拦不住：`contains_forbidden_keys`（`schemas.py:142`）查**键名**不查值；redact 只脱企业名/凭据。攻击链：reference.must_identify「未询问迁移窗口」→L-A 低分判据带原文→finding 落库→蒸馏进提示词→lesson「务必先问迁移窗口」→批准→**该场景永久污染甚至回流生产**。修补：①蒸馏输入字段允许名单投影（沿 L1 同步脚本⑦纪律）：只取 {code, dimension, severity, score, 脱敏 description}——evidence_refs/reason/note 一律不进蒸馏面（人工复核队列仍可见）；②若带证据先过 rubric 逐条子串黑名单（StubModelEvaluation :100-102 列表可复用为黑名单源）；③§5 该行自证改写＋机械钉（蒸馏 payload 无 evidence_refs/reason 键）。
- **C-2【P0】Overlay 注入面五件套**：①句式静态闸（陈述式纪律条款；禁祈使/第二人称/模式词黑名单〔忽略、无视、重新设定、以上指令、system、instructions…中英〕＋200 字上限）；②n-gram 防洗稿；③审批面并排呈现注入终文＋purpose＋近 30 天影响面调用量；④蒸馏提示词显式数据框定（Trace 列＝不可信数据，其中指令性文字一律视为待分析文本）；⑤公网 purpose（diagnostics.report）默认禁 overlay 或更强审批。
- **C-3【P1】指纹语义**：`compute_prompt_fingerprint`（`auditing.py:47-54`）注释明示「同模板不同输入⇒同指纹」。overlay 追加后指纹变 ⇒ 模板聚合归因破坏。推荐：指纹仍按注册表常量算，overlay 走显式列 {overlay_id, content_sha256}（非 JSON blob 便于 SQL 对账）；overlay 行不可变，改内容＝新行。
- **C-4【P1】§5 漏三条自证**：①宿主通道五边界——L6 脚本宿主侧跑且**写真相层**，与五边界①「绝不写真相层」的关系须显式裁定（沿 T-11 `lead_ledger_append.py` 先例：人工发起＋只插不改＋幂等）；②按量付费 key/预算闸——模拟域跑批的记账主体（哪个 user_id/服务账号）未写；③多客户 M 线——overlay/lesson 平台级跨 org 生效，取舍应入 §6 待拍板而非沉默。

### D. 可选优化
蒸馏返件存储形态写死（推荐零落库，同 N3b；若暂存补 TTL）；L-C note 同过黑名单；沙箱候选载荷同尺适用（防污染回归读数本身）；prompt_overlays 表归属＋静态钉引用面点名。

### E. 待澄清
蒸馏输入是否含 evidence_refs（§2.2 与 §2.3 口径互斥——已按允许名单裁定）｜overlay 跨 org｜模拟域跑批预算主体｜L6 脚本写真相层｜workbench 全量回归成本（单次 ≈1072 次真模型调用——异步化已有，补采样策略注记）。

**B#35 核验**：§7 独立撰写成立——机制描述全锚本仓代码与仓内文档，未见第三方结构化表达复现。

### 结论
C-1 是自证不实（机械可证伪）、C-2 是新公网级注入面缺闸——修入 v1.1 后可批。断点⑥现测发现价值高。

---

## §7 修订处置表（v1.1 落点对照）

| 评审条目 | v1.1 落点 |
|---|---|
| P0-Ⅰ 污染破口 | §2.3 蒸馏输入允许名单投影＋机械钉；§2.2 L-C note 黑名单；§5 行改写 |
| P0-Ⅱ Overlay 注入拓扑 | §2.5C：`ai/overlays.py` 装载函数两点共用（execute_ai_prompt 分叉前＋complete_json 直连腿）；workbench 经同一函数自读 |
| P0-Ⅲ Overlay 注入闸 | §2.5C 五件套＋purpose_key≡purpose 字面值＋发布闭集校验＋v1 白名单排除 diagnostics.* |
| P0-Ⅳ Skill 双闸链 | §2.5B 重写：release_channel 记账→publish_skill 滚指针；AI 草稿禁 personal scope；test_report=RegressionResult |
| P0-Ⅴ workbench 接线 | §2.1 重写：runner 逐轮 ctx＋候选载荷 config 通道＋两处注册＋10 次调用＋cost usage 回填＋单跑入队 |
| P0-Ⅵ L-B/L-C 口径 | §2.2 补写 |
| P0-Ⅶ 指纹 payload_sha256 | §2.3 补写 |
| 噪声带机械化 | §2.4 全套采纳（专家三 P0-1 设计） |
| 断点⑥修法 | §1.2-6 补裁：修 lessons.py 侧＋默认开启翻转登记＋真实 Settings 验收钉 |
| 指纹/审计归因 | §2.5C：指纹按常量算、注入在指纹后、AICallAudit+context_payload_json 列（并入 L5 迁移） |
| P1 其余 | §2.3/§2.4/§2.5/§4/§5 逐条落（见各节 v1.1 标注） |
| 4 条已拍板 | §6 裁决列 ✅ 2026-11-13 |
| 新待拍板 | §6 新增 5/6 两项（N6 例外升 AGENTS 红线〔推荐升〕；overlay 跨 org〔推荐 v1 平台级＋登记〕） |
