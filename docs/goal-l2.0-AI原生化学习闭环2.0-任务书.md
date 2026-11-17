# goal-l2.0 AI 原生化学习闭环 2.0 总循环任务书

## 目标与依据

把「真执行→真归因→AI 起草→受控热生效→统计显著验证」主回路的**六断点**闭环，按已批准设计稿逐轮施工：

- **唯一设计权威**＝`docs/architecture/AI原生化学习闭环2.0-设计稿-v1.md`（**v1.1**，含五专家评审合并 P0 七项与 §6 六条拍板全裁决）；评审依据＝`docs/architecture/AI原生化学习闭环2.0-设计稿-多专家评审-v1.md`。本任务书只做**轮次化施工编排**，机制细节以设计稿为准——冲突时设计稿 v1.1 ＞ 任务书；施工中发现设计稿锚点漂移须回写勘误（口径引用前现测纪律）。
- **拍板全落档（2026-11-13）**：①Overlay join key＝purpose 字面值且仅追加；②workbench 槽位独立键、缺省回落评估槽位；③噪声带缺省 0.1049＋轴绑定（已机械化＝套件存档轴＋mismatch 409）；④L-B likely 仅列表标记不建审批流；⑤N6 受控例外**升格 AGENTS.md 红线**（随 L5 落条款）；⑥overlay/lesson **平台级**生效＋登记（org 作用域 L6 后再议）。
- **排期≠实施授权**：L4/L5/L6 每轮开工须蔡工点名（「开L4」式），认领前必查在途 PR（fde-delivery-flow 技能）。

## 红线（全程有效）

- 禁 push `origin`（gxfde）；分支与 PR 只推 `fork`，`gh` 必带 `-R caishide/fde-workbench`；分支命名 `feat/loop2-l{4|5|6}`。
- 工作树：本线沿用 `D:/test/fde-wt-uilib`；主树与他线在途 worktree（`fde-wt-crv*` 等）禁碰；根 `node_modules` junction 删树前先 `rmdir` 摘链。
- **AI 不代拍板**：AI 蒸馏恒返件零落库；热生效恒经 `release_channel`（＋Skill `publish_skill`）密码审批；L-B 只 likely 不解锁提案；审批面呈现注入终文＋影响面。
- **污染防线**：蒸馏输入＝字段允许名单投影（evidence_refs/reason/note 一律不进 AI 起草面）；返件双卡（输入键集钉＋输出夹带拒）＋蒸馏器模块 AST 静态钉；seeds 禁动态写；治理模块全落 `fde_api/simulation/` 内（旧 valve 钉零改动覆盖）；两新表禁落 seeds/真相层面。
- **N6**：`prompt_registry.py` 常量本体零触碰（overlay 是登记制例外——仅追加/密码闸/秒回滚/过回归闸；替换式改动仍走代码 PR）。
- 客户真实资料不入 git/远端；L6 原件只落真相层 `D:\test\FDE\knowledge\`，仓库侧只存指针＋sha256；禁触 `.env`（密钥永不打印，检查器只读键名或长度）。
- **宿主通道五边界**：L6 宿主脚本沿 `lead_ledger_append.py` 先例（人工发起＋只插不改＋幂等）；服务端容器不直连宿主 CLI。
- 变异禁并行全量；脚本必 `Write` 落 `.py` 执行，禁 heredoc 与复杂 `python -c`。

## Goal 循环机制（每轮同构）

1. **认领**：`git fetch fork` 对齐最新 main → 查在途 PR → 蔡工点名后开工，建分支推 fork。
2. **施工**：按轮次清单（下节）；每机械钉配新测；**变异红→真红→`try/finally` 文件拷贝还原核 sha256→全绿**（禁 `git checkout --`）。
3. **本地闸**：定向 pytest ＋ `ruff check` ＋ `python scripts/check-python-types.py`（279 基线零新增）＋ `pytest server/tests/test_architecture_purity.py server/tests/test_source_size_budgets.py server/tests/test_ledger_sync_nail.py`；涉桌面跑 `npm run typecheck`＋`npm run test:desktop`。
4. **PR 与判定**：推 fork 开 PR（PR 前 code-review 技能）；判定＝**最新 head commit 的 4 必需 CI job 全绿**（`gh api repos/caishide/fde-workbench/commits/<HEAD>/check-runs` 全读，不信 watch exit code；已知 flake 家族 `test_task_decomposition_preview_commit_idempotent`/`test_ai_run_proposal` rerun 即绿）→ squash 合并 → 对齐本地 main → 删分支。
5. **活体三验**（server 变更轮，沿七撞纪律）：`wsl -d Ubuntu-24.04 -- docker compose -p fde-workbench build api worker scheduler` ＋ `up -d --force-recreate` ＋ 容器内 `alembic upgrade head` → 三项复验（活体 `url_map` 条数≡口径、容器内 `alembic current`≡本轮 head、容器镜像 ID≡本树构建产物）＋ `health/ready` 200。
6. **台账三同步随轮**：CHANGELOG `delivery` 节（守 ≤20% 钉）＋AGENTS bullet（独立追加禁重写）＋backlog；审计清单三件套＋archify 四件套随轮（L4/L5 DoD 显式列，含迁移轮 route CSV/DB CSV）。
7. **止损**：同轮真红 ≥2 次 ⇒ 落 `docs/goal-l2.0-BLOCKED.md` 停损待裁；禁删测、降断言、涨行数预算、无理由 skip/xfail。

## 轮次

### L4 真执行面＋归因真化＋AI 起草（迁移①：`ImprovementProposal.candidate_payload_json` 加列）

**体量警示（评审）**：实际改动面 ≈ 设计稿 §2.1 清单 ×1.5（runner/注册/cost/J-1/测试/桌面全要动）——可拆服务端/桌面两个 PR 分批走。

1. **workbench 执行面**：NEW `simulation/adapters/workbench.py`（第三档 `adapter_mode="workbench"`；probe/analyze/design＝真模型按 mock 同款 JSON 契约、结构化失败回落 `structured=False` 沿 real.py 语义；implement/validate 复用确定性腿）；`models.py:60 ADAPTER_MODES`＋`adapters/__init__.py:23-32 build_adapter` **两处注册**；runner 循环内逐轮 `dataclasses.replace(base_ctx, disclosed=customer.disclosed_facts, config={**base_ctx.config, "history": history})`（`runner.py:161-178` disclosed 恒空修正；mock 忽略新键＝零回归）；候选载荷通道 run config→`ctx.config["candidate_payload"]`（run_key 含 config 指纹 ⇒ 基线/候选组天然分流）；`cost_json` 接 DeepSeekClient usage 回填（现硬编码 `tokens:0`，`runner.py:315-321`）。
2. **模型槽位与审计**：NEW `deepseek_simulation_workbench_model`（缺省回落评估槽位；缺端点/密钥 fail-closed）；purpose=`simulation_workbench`（注册表 +1＋J-1 白名单 +1＋`_KNOWN_EXCEPTION_VARIABLES` 动态插值例外登记，沿 industry_template.context 先例）；执行走 `execute_ai_prompt` 单一入口。
3. **异步化**：单跑与回归一并走后台队列（`run_service.py:153-154` 同步 30-60s 会卡请求）；CI 用 mock DeepSeekClient seam 钉契约/回落/audit 行（purpose+version）；真机证据另附 run id＋活库取证（沿 G9b 先例）。
4. **analyze_run 三源化**：L-C＝`layer=="human"` 按 `created_at` **最新行**（人工插行无幂等，按 `get_evaluation_report:311` 同语义收敛）＋note 全文过**答案句黑名单**；L-B＝查询钉 `layer=="model" AND evaluator_id=="model:server"`＋`verdict!="unavailable"` 二道 ⇒ `likely`（不解锁提案；likely 单独提案 409）；L-A＝FA-01..10 不动；幂等键 `(evaluation_id, code)` 三源各挂各行。
5. **AI 蒸馏起草**：NEW `POST /simulation/findings/draft-ai`（**返件式零落库**，不进 api_catalog）——输入 finding_ids（train split 服务端过滤）；**蒸馏输入＝字段允许名单投影** `{code, dimension, severity, score, 脱敏 description}`，evidence_refs/reason/note 一律不进；`execute_ai_prompt` purpose=`simulation_improvement_draft`（注册表＋J-1）＋提示词显式数据框定（Trace/finding 字段列为不可信数据）；跨题聚类 v1 按 FA 码分组；产出三型候选载荷 `lesson_entry`（text≤300 字）/`skill_version_draft`/`prompt_overlay_fragment`（fragment≤200 字）；契约失败整批丢弃重试一次 409；**`_finding_fingerprint` canonical 增 `payload_sha256`**（服务端规范化现算，无 payload 取固定空值；老提案互不误伤、同 payload 幂等保留）；采纳＝人工确认后 `create_proposal`（NEW `candidate_payload_json` 列随提案入档；与 `override_json` 分工：override＝run 参数、candidate＝三载体载荷）。
6. **断点⑥修正（默认开启翻转）**：修 `agents/lessons.py:95/111/112` 键名 `fde_agent_lessons_*`→`agent_lessons_*`（**只修 lessons.py 侧**——改 config 侧造 `FDE_FDE_` 死键，CR-046 家族）；假 settings 测试（`test_lessons_wiring.py:145-147`）同步修正；**验收钉＝`create_app` 真实 Settings 断言注入生效/可关**（同坑两次复发家族）。
7. **桌面**：「失败→AI 起草→建案」＋场景选择器（建立在 #448/#426/#439 行为之上，融合 rebase）。
8. **验收判据**：workbench 单题端到端两层（CI seam 钉＋真机 run id＋活库）；L-C confirmed/L-B likely 分流钉（U1/U2）；analyze_run 幂等钉（U3 多 human 行不增殖）；真实 Settings lessons 验收钉；蒸馏输入键集钉（无 evidence_refs/reason 且 ∩ 答案键＝∅，键清单从 `schemas.py:35` 单一真身取）＋输出返件夹带答案键拒；静态钉蒸馏器模块 import ⊆ 白名单（禁 scenarios.loader/reference 面）；指纹 payload_sha256 钉；mock/real 零回归；变异三连红→还原→绿。
9. **预算**：模拟域跑批记账主体＝**服务账号**（写明）；真机 workbench 调用次数入本轮限额（开工时与蔡工确认额度，配额购买属 OWNER 决策）；全量回归（≈10 调用×134 题）配采样策略注记。

### L5 三载体热生效＋回归真化（迁移②：`agent_lessons`＋`prompt_overlays` 两表＋`AICallAudit.context_payload_json` 一列）

强串行于 L4。

1. **Lessons 动态层**：NEW 表 `agent_lessons`（落 `agents/models.py`；行 schema 与 seeds 同构闭集＋`status ∈ (draft,published,retired)` CHECK＋`source_proposal_id`；动态行 id 前缀 `LESS-DYN-`，与 seeds `LESS-SOP-` 跨层 sha256 唯一、动态 id ∈ seeds id 写入即拒；text 变更＝新行，`text_sha256` 服务端写入侧现算）；装载＝seeds 底座（文件序在前）∪ published 动态行（(created_at,id) 序在后），top_k 竞争 seed 优先；`select_lessons` 零改动；**热生效测试形状**＝同进程两次 `knowledge_snippets_for`（真实 Settings）中间只动 DB 行状态（任何模块级缓存必红；seeds 腿 lru_cache 仅缓存文件腿）；宿主 zcode run 留痕＝lesson 注入快照落 `agent_runs` 快照列（`c8e2a6f0b9d4` frozen_tools 同构）或 operation_events。
2. **Prompt Overlay**：NEW 表 `prompt_overlays`（落 `workbench/models.py`；purpose_key≡**purpose 字面值**下划线风格、发布时闭集校验未登记 purpose 拒发布；fragment ≤200 字仅陈述式；content_sha256 服务端现算行不可变改内容＝新行；`min_prompt_version` 数字尾缀解析防 v10<v2；source_proposal_id）；NEW `ai/overlays.py::load_overlays(purpose)` **两点共用**＝`execute_ai_prompt`（DSH/降级分叉**之前**，防降级路径丢 overlay）＋`DeepSeekClient.complete_json` 直连腿头部（purpose 在签名内；DSH 关闭部署下全覆盖）；注入发生在 `compute_prompt_fingerprint` **之后**（指纹仍按注册表常量算），overlay 归因走 `AICallAudit.context_payload_json`（`{"overlay_ids":[…],"overlay_sha256":[…]}`，PG JSON 包含查询可反查）；**注入闸五件套**：句式静态闸（禁祈使句/第二人称/模式词黑名单中英双语）／n-gram 防洗稿／审批面并排呈现注入终文＋purpose＋近 30 天该 purpose 调用量／蒸馏提示词数据框定／v1 purpose 白名单仅内网面（simulation/quality/plans/workflows/dispatch）**排除 `diagnostics.*` 公网面**；沙箱同尺（回归候选注入的 overlay 同过句式闸）。
3. **Skill 双闸链**：AI 蒸馏起草 `SkillVersion` 草稿**禁 personal scope**（`save_personal_skill` 保存即 published 零闸＝绕开全链，须闸死）；采纳→提案（`candidate_payload_json.skill_ref`）→`release_channel` 发布（记账）→既有 `publish_skill`（admin/系统操作员＋密码＋test_report）滚 `current_version_number`＝热生效；test_report 证据＝提案的 RegressionResult（waive 留痕备选）；回滚＝`rollback_skill` 同尺闸指针回指旧不可变版本行。
4. **release_channel 三支执行器＋overfit 发布闸**：lessons/skill/overlay 三支（**写引用面 ⊆ {各自 models, release_channel 执行器}**，装载读面 lessons.py/overlays.py/ai_server_client.py 入允许集——静态钉沿 AST 手法）；`release_proposal` 增查该提案最近一次 `RegressionResult.overfit_risk=True` ⇒ 409（机械拦截）；回滚＝既有 `rollback_release`（状态翻回＋载荷行 retired，审计链不断）。
5. **回归真化＋噪声带闸**：`_run_group` 参数化 `adapter_mode`/`model_mode` 从 `suite.baseline_config` 透传（缺省 mock/stub＝零回归）；候选组叠加 `override_json.run_config`＋`candidate_payload_json` run 级沙箱注入（config 通道）；噪声带机械化：`RunSummary` 可选 `model_total/evaluator_axis`（默认值＝既有构造点零改动）→ `compare()` keyword-only `noise_band/noise_band_axis` 输出**独立** `model_verdict` 键（顶层 verdict 与 CHECK 闭集不动）→ 带＋轴存档 `baseline_config_json.noise_band={axis,band,anchor_n}` → 现算轴 `f"{RUBRIC_VERSION}|model:{mode}"` 与存档轴不符 ⇒ 409 `noise_band_axis_mismatch` fail-closed；**四钉**：within_noise 反例（Δ≤band 且 n≥3 ⇒ ≠improved）／n<3 ⇒ insufficient_data／轴不符 409／缺省常量==0.1049 与 L2 底册双锚；n 口径＝套件场景数（run_key 幂等不增样）；`model_mode=server` 或 `adapter=workbench` 转后台作业（`jobs/handlers.py:44-69` register 模式＋可选入 `RECOVERABLE_JOB_TYPES`；**BackgroundJob 状态承载零迁移**）＋UI 轮询；stub/mock 小跑保持同步。
6. **AGENTS.md 红线升格（§6-5 拍板「升」）**：落红线条款「overlay 只许追加式片段（≤200 字）·purpose 闭集·经 release_channel 密码闸·替换式改动仍走代码 PR·prompt_registry 常量纪律零触碰」＋**overlay/lesson 平台级生效登记（§6-6 拍板）**；独立 bullet 追加，禁重写既有行（锚点唯一性先验，教训 92）。
7. **桌面**：发布/回滚挂真载荷（融合 #448）。
8. **验收判据**：发布→下一 run 注入（overlay：audit 行 `context_payload_json` 在场可 SQL 反查；lesson：同进程行为钉；skill：**双闸链全链走通**）；回滚→立即消失；噪声带四钉全绿；overfit=True ⇒ release 409 反例钉；两新表写面静态钉；**既有套件零回归显式条目**（regression/e2e/runner/improvement/lessons_wiring 全绿＋不带新键行为逐字节不变）；审计清单三件套＋archify 四件套刷新＋迁移 docstring 父链登记＋`test_migrations` HEAD 断言；污染钉全绿。

### L6 真实交付反哺（独立，可与 L4/L5 并行；零迁移）

1. NEW 宿主侧只读脚本 `scripts/extract_case_from_project.py`（门禁 fail→pass 迁移与产物拒收 → 真相层 `import_card_v1` 候选卡）；**宿主通道五边界先例裁定**＝沿 `lead_ledger_append.py`（人工发起＋只插不改＋幂等＋找不到登记面 fail-closed）；服务端容器不直连宿主 CLI。
2. 复用 L1 管线人工激活（审阅卡→curl 导入→桌面核对→PATCH 激活）。
3. L-C 原文核对视图收口（G7b 挂账「交付原文核对入口」，入口做好后可改判历史终裁）。
4. 预算记账主体写明（模拟域跑批以服务账号计）。
5. **验收判据**：一次真实驳回/拒收→脱敏候选卡落真相层（不入仓/不入被扫面/代号化/人工激活）；宿主脚本只插不改＋幂等钉。
6. 可选：N6 质量路由攒轴组样本（登记不排期）。

## 轮次状态（随轮更新）

| 轮 | 状态 | PR | 迁移 | 备注 |
|---|---|---|---|---|
| L4 | ✅ 已实施并合并（服务端 PR #455 → `7e99b658`＋桌面 PR #467 → `ce4a9bde`；活体升迁 `d4b7e2f9a6c1`） | #455 / #467 | ① `d4b7e2f9a6c1`（candidate_payload_json 加列＋adapter_mode 列宽/CHECK 扩值勘误） | 勘误：设计稿 §2.1 漏记列宽与 CHECK 两处 DB 落点，已随迁 ① 落地；活体冒烟检出直连四元组缺口当轮闭合 |
| L5 | ✅ 已实施（三载体热生效＋回归真化噪声带四钉＋异步 BackgroundJob＋AGENTS 红线升格＋桌面并排预览/真载荷回执/异步轮询） | 随本轮 PR 合入 | ② `a9f3e5c7b1d2`（`agent_lessons`＋`prompt_overlays`＋`ai_call_audits.context_payload_json`） | 变异四连红→sha256 还原→绿；493 路由 / 155 表 / 77 迁移；清单与架构图四件套同步 |
| L6 | ✅ 已实施并合并（PR #476 → `55ff1187`；宿主侧只读抽取脚本＋T-A2 脱敏＋L1 四重闸衔接＋幂等/安全双闸钉；条款③ L-C 原文核对视图挂账顺延见挂账登记） | #476 | 零迁移零路由零表 | 测试 4 例＋邻域回归 34 例＋变异四连红→sha256 还原→绿；**真机反哺实证已闭环**：试点项目 `FDE-20261025-9BF8E4AE` → 候选卡 `IMP-PRJ-FDE-20261025-9BF-98C9CE`（sha256 `f51feff1…c7c3829`）落真相层 `案例候选\l6-candidates\`，幂等复跑 already_exists 同指纹＝只插不改活体实证；便携版 r52（asar `bd309b15…`，承载 L5 桌面改动）；L-6 批跑 IP 按 run 派生可顺带 |
| 收尾轮 | ✅ 已实施并合并（2026-11-18，#510/#511/#512/#513/#514 五 PR CI 四绿；回归判定环收口＝**回归通过＋首个改善向信号**〔模型轴 +0.2318 improved，两登记判据全过〕；「反哺有效」维持未知） | #510 `e43e729a`／#511 `9a03b88c`／#512 `74722cf1`／#513 `6612691b`／#514 `f8aa4d1b` | 零迁移零路由零表 | 排除纪律（failed run 不进判定分母＋幸存者偏差闸）＋PHASE 预算 32768 两档标定＋materialized 落库丢失修复＋seed 压制消解（动态行保底 1 席）＋L-C 原文核对只读视图（条款③只读面）＋r56 便携版；活体两轮三验全绿；报告＝`docs/audit/学习闭环收尾轮-回归判定环收口报告-2026-11-18.md` |

## 挂账登记

- seed 压制＝~~v1 局限（证伪种子须改代码下线）~~ **✅ 已清偿（收尾轮 #512 `74722cf1`，2026-11-18）**——`knowledge_snippets_for` 两段选择：published 动态行保底 1 席（seeds 让末席），无匹配动态行逐字节零变化，seeds 稀缺时动态按序补足；3 钉＋变异红→还原→绿。
- overlay/lesson 按 org 作用域——§6-6 拍板 L6 后再议。
- **L6 条款③（L-C 原文核对视图收口，G7b 挂账「交付原文核对入口」）——✅ 只读面已收口（收尾轮 #513 `6612691b`，2026-11-18）**：发现卡证据条原文展开（`<details>`「原文核对（N）」标注 AI 蒸馏面不携带）＋同页既有 L-C 人工评估行 note 原文＋交付物原文展开（#448）⇒ 运行详情页三要素并排＝只读核对视图完整；**改判历史 L-C 终裁的写面留后续轮（须拍板，owner＝下一个被点名的桌面轮）**——**设计稿已备**：`docs/architecture/L-C改判写面-设计稿-v1.md`（PROPOSED，2026-11-18：现测盘点「终裁行写面已在＋重复插行＝再终裁天然在场」，真缺口四项＝supersede 联动〔P0，查询口径收敛推荐〕／finding 状态迁移端点〔P1〕／终裁历史链读面〔P2〕／状态字段语义空转；四项待拍板带推荐项，W1 服务端＋W2 桌面拆轮）。
- 全量回归采样策略——L4 开工时注记。
- PR #448（在途桌面五断链）——L4/L5 rebase 融合。
- 真机额度——每轮开工时与蔡工确认（MiniMax 配额购买属 OWNER 决策）。
- **L6 party 评审三裁定（2026-11-15 蔡工拍板「按建议处理」，评审会即 Code Review Crew＋红线特聘圆桌）**：
  1. **发起权裁定（Vex 提案＋蔡工裁）**——L6 真机实证由 AI 会话持用户指令「接着那个任务继续完成」执行真相层写入，登记为 `lead_ledger_append` 先例「人工显式发起」的**合法形态**（授权措辞＝用户当轮指令＋当轮汇报＋留痕可推翻）；后续宿主写面操作沿用同形态，须在轮次回执中显式登记发起语境，不得以会话惯性升级写入面。
  2. **manifest 并发无锁挂账（Dana 口径）——✅ 已清偿（2026-11-15 挂账清偿轮，蔡工「按推荐执行」扩围）**——`candidate_manifest.json` 读-改-写段已入 `O_EXCL` 独占锁（跨平台 Windows 宿主适用）：并发双实例单方 `manifest_lock_busy` fail-closed（不等待不轮询，重跑即可）；锁 mtime 超 30s 视为崩溃残留强拆；卡文件本体幂等不丢语义不变。两钉：持锁拒写／陈旧强拆（变异红→sha256 还原→绿）。
  3. **信号有效性置信度（Level 提案）**——「管线可用」＝高（真机 n=1 实证）；「反哺信号有效」＝**未知**，禁止在收口报告中写绿；消解条件＝首批候选卡人工激活进训练场跑出分数后升格。**首点证据已落（收尾轮 2026-11-18）**：首条动态行 LESS-DYN-PROP-BE6DE878 激活后 v3 回归模型轴 +0.2318 improved（两登记判据全过）——**单场景族 n=3 单点，仍维持未知不升档**；升格须多点证据（跨场景族/跨行业复现）。
  ③排序修复已随评审追改轮落地（`ORDER BY` 加 `occurred_at` 破平局＋确定性测试钉）；**残界「同事务批量代录 `occurred_at` 仍打平」也已清偿（同轮挂账清偿）**——配对逻辑升级为两遍纯函数 `pair_gate_transitions`（fail 池 ＋ pass 按 `occurred_at` 升序消费最近前因）：全打平时 `<=` 仍成立 ⇒ **只可能错配 fail note，不可能漏检迁移链**；fail 严格晚于 pass 不配对（语义同旧）。全打平确定性钉（1 fail＋1 pass 全字段时间戳相等＋pass id 字典序在前，变异 `<=`→`<` 必红）。
  **同轮清偿（importlib 单一真身，Yui 第一笔）**——`IMPORT_CASES_PATH` 提为模块级常量（仓库布局知识单处书写）＋在场钉（L1 挪位未同步即红）＋加载失败转 `CaseExtractionError`（裸堆栈不再外泄）。**未实施留痕**：Yui 第二笔（677 行单文件拆分）＝抑制性警告非指令，仅在文件再增长时触发；Level「billing_actor_policy 机制化」＝动生产记账链路，需独立轮立项（用户选择题未答，按推荐执行＋留痕可推翻）⇒ **✅ 已由 billing 机制化轮清偿（2026-11-15，见挂账登记末条）**。
- **billing_actor_policy 机制化（Level 评审发现④）——✅ 已清偿（billing 机制化轮，2026-11-15，蔡工点名开工）**——L6 候选卡 `billing_actor_policy: "service_account"` 由「声明字段」落实为代码机制：①独立配置键 `Settings.simulation_ai_actor_username`（env `FDE_SIMULATION_AI_ACTOR_USERNAME`，opt-in 留空＝机制关回落既有行为，与诊断域键隔离防跨域串账）；②NEW `simulation/ai_actor.py::resolve_simulation_ai_actor`（配置了账号但不存在/停用 ⇒ `simulation_ai_unavailable` 503 fail-closed，空值不 503）；③`ai/auditing.py` 模块级 `ai_actor_override` ContextVar，`current_actor_id()` 读序升级为 override→请求上下文→None；④`evaluator.py` `include_model` 分支 server 腿解析服务账号后**同一值双注入**（`ai_actor_override`＝预算闸＋审计归因腿，`ai_actor_id`＝DSH structured_completion 腿），`try/finally` 逆序 reset 不泄漏；stub 腿不解析（确定性腿零回归）。候选卡 provenance 字段**保持政策常量 `service_account` 不变**（拍板③），机制由 NEW `tests/test_simulation_billing_actor.py` 7 例（含预算闸判别力／双 fail-closed／无串账）＋变异双锚 M1/M2 真红→还原绿证明。
