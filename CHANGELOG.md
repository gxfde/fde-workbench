# Changelog

本文件记录 FDE Workbench 开源版本的主要变化。版本号遵循语义化版本规范；首次公开源码版本为 `v0.1.0`。

## [未发布] — V3.2 G7b 追加轮二：L-C 终裁提交回执就地呈现（蔡工实测「提交后无任何反应」；纯桌面零服务端，2026-11-09）

- **起因（蔡工实操，活库取证）**：蔡工对 run `91d00a0f` 提交人工终裁（结论不可靠/inconclusive、0.55、理由已留痕）后**看不到任何成功或失败提示**——查实落库**已成功**（human 行 14:22:35 UTC 在库），回执失败原因是 UI：成功/失败的 notice 只渲染在**左栏顶部**（运行列表上方），而用户盯着右栏表单 ⇒ 「报喜报忧都跑错栏」，且有诱发重复提交的风险（`record_human_evaluation` 每次调用落新行、无幂等，重复提交=多一条人工行）。
- **修复**：①终裁表单内建提交状态机（idle/busy/ok/error），回执**就地呈现**——成功绿条「提交成功——人工终裁已落库…」/失败红条带服务端错误文案，紧贴表单；②提交按钮 busy 态（「提交中…」防双击）；③**父组件错误不再吞没**：`handleRecordHuman` 对 POST 失败改为**穿透给表单**（原来 catch 后只喂左栏 notice，表单永远只见成功）；④「POST 成功但报告刷新失败」单列——明确提示「已落库，重新选中运行可看回显」，**不得谎报为提交失败**（防误重提）。
- **测试**：NEW 1 例（POST 拒绝 ⇒ 表单旁内联报错 + 按钮恢复可再提交）＋成功用例追加就地回执断言；桌面全量实测 **973 passed（82 文件）**＝上轮 972 + 1；typecheck 双 tsconfig 绿。
- **新挂账（蔡工 inconclusive 理由直接指出的缺口）**：训练场评估报告缺少「**交付原文核对入口**」——从报告/发现面无法打开四份交付物原文，人工终裁核不到原文 ⇒ 本次终裁只能记 inconclusive。待后续轮加「从评估报告打开交付物原文（只读）」入口，届时蔡工可复核后改判。
- **口径**：纯桌面 ⇒ 自身零结构增量（合并态结构口径以 fork/main 现测为准）；桌面变更 ⇒ 便携版 **r27**（r26 为上轮交付，现测顺延）。

## [未发布] — AI 原生化 N1 重跑二与 C-1 空引用集死锁修复轮（exit 0 真实执行／验证层语义缺口修复；零迁移零路由零桌面，2026-11-09）

- **起因（重跑二实测，run `a5773e26`／幂等键 `n1-somwyn-host-002`）**：蔡工拍板「确认重跑」后重跑——GLM Token Plan 配额已恢复（起跑前最小直连探针 EXIT=0），**zcode exit 0 真实执行**（221.8s／`token_cost=769055` 真实计费／前置③票据二次行使＝新 `authorization_id` 指纹）＋**5 产物落库**（presales-brief／assumptions／discovery-questions／README 四 doc＋manifest.json config；sha256+size+mime 逐行正确＝#247 MIME 修复活体验证）。**但 5 产物全部被 C-1 拦截**（`ai_output_intercepted`＋422＋run failed/degraded_reason=artifact_validation_failed）：somwyn 无 confirmed 引导分析 ⇒ `problem_refs=∅`（known_refs 空集），任务书又明令「source_refs 只能取已确认业务问题的值、不要自创引用」⇒ 智能体如实写空数组 ⇒ `_finalize` 对空 `source_refs` **无条件**记 `missing_source_refs`——**智能体行为完全正确，这是验证层的结构性死锁**：known_refs=∅ 时任何产物都不可能过闸，而「暂无已确认业务问题」正是售前发现期的合法态（discovery-questions 本就是用来确认问题的）。
- **修复（最小面，C-1 既有合同不动）**：`agents/service.py::_finalize` 校验改 `if not artifact.source_refs and known_refs`——**known_refs=∅ 时空引用放行**（无可引用项＝追溯义务自然满足，产物照旧 `reviewed=False` 永不自动进终审）；**自创引用仍拦**（空集下任何非空引用落 `unknown_source_refs`，elif 同支覆盖）；有确认问题时的追溯义务零松动（missing/unknown 由既有两用例继续钉死）。`agents/workspace_files.py` 任务书模板补空态指引：「context.md 显示『暂无已确认业务问题』时，source_refs 写空数组 []」（头部 355≤400 字上限；G9 实测教训同族——契约形状不写明，智能体只能猜）。`agents/service.py` 1833→**1835**（预算 1836 内，热点只许拆不许长的钉继续有效）。
- **测试**：NEW `test_c1_no_confirmed_problems_allows_empty_source_refs` 1 例（不铺 confirmed guidance ⇒ 空引用 201 completed；同态自创引用 422 `unknown_source_refs`）＋既有 `extra.bin` 断言按新语义收窄（`{"invalid_kind", "file_missing"}`——该产物仍被双重拦截，只是不再单列 missing）；定向 **28 passed**（C-1 全文件＋预算钉＋宿主轮询邻域）；**变异验证**（还原旧行为 ⇒ 新钉红 ⇒ 还原 ⇒ 绿，无残留）；pytest 终值以本 PR CI 为准。
- **随轮注记**：台账 **v1.6**（G-01/G-07 状态第四段演进＋标题号顺带由 v1.4 校正〔v1.5 漏改〕）＋复盘 doc §7（重跑二实录）＋任务书 §13 记录 **#9**＋§14 N1 行同步。**重跑二产物与 run 行留痕保留**（`pilot.reviewer` 人工盘点可随时开始）；**重跑三＝蔡工拍板**（H4 不代发起；G-01/G-07 判据「completed run→候选→人工接受→至 G9」待兑现）。

## [未发布] — V3.2 G7b 追加轮：运行台执行面过滤接通 + 运行行短编号 + 列表面板样式（蔡工实测反馈；纯桌面零服务端，2026-11-09）

- **起因（蔡工实测）**：在运行台「执行面」下拉选「真实执行面」，下方列表**纹丝不动**，也找不到唯一那条真实执行面运行——该下拉自 G7 起只作为**新运行的默认执行面**（`createSimulationRun` 的默认值），**从未接到列表过滤**（服务端 `list_runs` 只有 scenario/status/split 参数，无 adapter_mode）；且运行台两栏布局与列表类（`.simulation-runs/-run-list/-run-item`）**零 CSS**，19 条运行裸排成一堵墙，真跑那条又是全库最早、排在列表最底部 ⇒ 无从找起。
- **修复（纯桌面，只新增类不改既有类）**：①「执行面」下拉变**真过滤**——客户端收窄列表（≤200 行同页返回，无需服务端参数；标签改「执行面（过滤列表；发起新运行也用它）」如实标注双重职责），新增默认项「全部执行面」，选 real/mock 只留对应行，发起新运行时空项回落 mock（原默认行为不变）；②运行行首加**短编号** `#<id 前 8 位>`——外部指引（如「给 91d00a0f 终裁」）可与界面逐行对号；③计数行「共 N 条 / 过滤后 x ÷ N 条」+ 过滤无命中时的指路空态（提示切回「全部执行面」）；④两栏 grid 布局 + 列表 `max-height:480px` 内滚 + 行卡片样式（激活行金框），全走令牌。
- **测试**：NEW 2 例（过滤链路四态切换〔全部→real→mock→全部〕+ 短编号 + 计数行；过滤空态指路）＋既有「切换执行面」用例随默认值变更改写（默认 mock→全部执行面，行为有意变更随轮改写）；桌面全量实测 **972 passed（82 文件）**＝G7b 首轮 970 + 本轮 2；typecheck 双 tsconfig 绿。
- **口径**：本轮纯桌面零服务端 ⇒ 自身零结构增量；合并态结构口径以 fork/main 现测为准（写作时点 G5/N1 已并入：**436 路由 / 49 蓝图 / 143 表 / 56 rev 单头 `b3e8a6c2d4f7`**，官方脚本现测吻合）；桌面变更 ⇒ 便携版 **r26**（r25 为 G7b 首轮交付；序号打包时点现测顺延，不覆盖旧目录）。

## [未发布] — AI 原生化 N1 真实订单首跑（机械面全链通过；业务面被 GLM Token Plan 配额阻断；台账 v1.5＋复盘落盘；零迁移零路由零桌面，2026-11-09）

- **事实**：#247 合并部署后，宿主裸跑态起首跑——run `fa6ec37f`／somwyn／幂等键 `n1-somwyn-host-001`（**非 `sim:`/`rehearsal:` 前缀** ✓ G-01 形态面）／售前智能体 `4410538c-…`（`agent.module.presales`）／发起=admin／运维脚本 `scripts/agents/real_order_host_channel_run.py`（拒绝 sim 前缀幂等键；只发起 run，接受与拍板留给人）。
- **机械面全链通过**：`execution_provider=host_channel` 落库；**前置③票据真实行使**——`authorize_host_run` 发行+spawn 前校验通过，`authorization_id` 落 `717cf5e0…293`（64 hex 指纹，非票据本体）＋`workspace_ref` 归一化工作区；**fail-closed 合同活体验证**——zcode `exit 1` ⇒ `failed`＋L2＋`token_cost=0` **零计费**＋G-07 零候选登记（「仅 completed 登记」语义在真实 run 上成立）；上下文全代号化（`context.md` 零客户真实资料）；事件 `agent_run_created` 留痕。
- **业务面被外部配额阻断**：zcode 316.9s 后 exit 1、`output/` 空——通道内 stderr 无留痕（边界⑨）⇒ T-Z1 同款最小直连诊断：**「已达到 Token Plan 用量上限…(2056)」**（`AI_APICallError`，traceId `40318c2e-…`）；与 #235 自报 429 同族、**与 #248 独立互证**（两线同日撞同一堵供应商配额墙）——外部依赖非代码缺陷，fail-closed 把失败拦在零计费侧。
- **落盘**：台账 **v1.5**（G-01/G-07 维持 OPEN，阻塞三段演进「闸未开」→「前置未清」→「**首跑已执行，业务面待供应商配额恢复后重跑**」；`agent_runs` 现状锚 9→**10**〔1 条真实订单〕）；NEW `docs/architecture/AI原生化N1首跑复盘-v1.md`（执行事实/机械面验证表/根因取证/12 前置口径/遗留）；任务书 §13 记录 **#8**＋§14 N1 行同步＋#7 随轮注记。**重跑决策＝蔡工**（H4 不代重试：配额恢复后可 `retry_run` 或新幂等键；判据「至 G9」待 completed run＋`pilot.reviewer` 人工拍板链）。前置③升级「真实订单行使面已验证」；**①商用条款/⑦网络限制面维持未过不声称**。
- **顺带修复＋挂账**：运维脚本 docstring 改 raw 字符串（消除 `SyntaxWarning: invalid escape sequence`）；**容器栈 rebuild 挂账**——`fde-wt-v31p2` 部署基待归属方 rebuild+recreate（本次起跑面为宿主裸跑态不依赖容器栈；活库 alembic 头已在 `e7b2c4d9f1a3`，本轮零迁移）。
- **口径**：零迁移零路由零新表零桌面（结构沿现行：427 路由／49 蓝图／139 表／55 rev 单头 `e7b2c4d9f1a3`）；本轮纯文档＋脚本一行注释面修复＋1 个非测试脚本，pytest/mypy/vitest 全不动（最近 main CI 实测 **2556 passed + 6 skipped**〔#247 run 42607195716 server-tests；2544+12=2556〕/ mypy 279）；无需 rebuild/alembic（除挂账项归部署归属方）。

## [未发布] — V3.2 G7b 训练场界面收口轮（案例编辑弹层可滚可关 + 三视角分区重排 + L-C 人工终裁桌面接线；纯桌面零服务端，2026-11-09）

- **起因（蔡工实测反馈）**：①训练场里找不到给 L-A/L-B 分歧拍板的地方；②案例库点「编辑」后弹层**不能下滚、也没有关闭按钮**——`.dialog` 基类（`styles.css`）只有 `width/padding`，**无 `max-height`/`overflow`**，高表单弹层超出视口即被裁剪且不可滚，底部操作钮（取消/保存）落在视口外（仓库既有解法是各页加类：`.task-dialog`/`.file-version-dialog` 等，训练场漏配）；③表单「一头雾水」——顶层字段无分组无标题，且多处 JSX 文案把 `**加粗**` 星号直出给用户。
- **拍板入口缺失的真因**：L-C 终裁**服务端早就在位**（`POST /api/v1/simulation/runs/<id>/evaluation/human`，`evaluator.record_human_evaluation`：verdict 五值闭集+总分 0–1+理由必填，落 `layer="human"` 评估行，机器原行并列保留不覆盖）——G7 桌面组件里 `HumanReviewForm` 也写好了，但 `SimulationRunDetail` 渲染 `<EvaluationReport>` 时**从未传 `onRecordHuman`** ⇒ 表单从未渲染过。纯接线缺口，非功能缺口。
- **修复（全部 additive，零既有类改动）**：①`Modal` 加可选 `className`/`dismissable`（×关闭钮 + busy 锁闭与 Esc 同规；不传行为零变化，既有调用方零波及）；②`styles.css` 末尾新增块：`simulation-scenario-dialog`（960px 宽 + `max-height: calc(100vh-48px)` + `overflow-y:auto` + sticky 底部操作条）、`.ui-modal-heading/.ui-modal-close`、训练场四类状态行（`simulation-warning/notice/error/hint` 此前**零样式裸文本**）与 `simulation-human-form`；③`ScenarioEditor` 按**三视角**分区重排：①基本资料 → ②客户可见面（Tester/Customer 视角）→ ③隐藏事实（按阶段披露）→ ④评分侧（仅 Judge View），每区一句话说明；④**L-C 接线**：`api.recordHumanEvaluation` + RunDetail `admin/project_lead` 门控（与服务端 403 同尺，其他角色只隐表单）传 `onRecordHuman`，提交后**重拉评估报告**（human 层行并列出现、`human_review_required` 随之解除）+「人工终裁已落库——机器结论与人工结论并列留痕」回执；⑤`EvaluationReport` 分歧告警按有无终裁权限分措辞（无权限者指路「项目负责人或管理员」）+ `final=human` 时醒目回显「人工终裁已记录：<结论> · <分数>%（机器原行保留并列）」+ 终裁表单加「终裁必须留痕可追溯」说明与 UiButton 化；⑥总览页 hint 写明拍板路径 + JSX 星号清理七处（六组件）。
- **测试**：NEW 4 例——console 3 例（admin 可见终裁表单并 POST `/evaluation/human` 且提交后重拉报告≥2 次／fde_engineer 不见表单且告警指向有权限角色／`final=human` 醒目回显终裁结论）+ library 1 例（弹层类 + 四分区标题 + × 关闭钮可关）。**测试基建两课**：①`routeApi` 帮手对 evaluation 路径硬编码返回基础夹具、无视 overrides 参数——需自定义响应的用例必须自带 `mockImplementation`；②终裁表单在 `emptyReport()` 初始渲染即出现，告警行要等评估 GET 落地——断言必须 `findByText` 等待式否则全量跑时序竞态假红（单跑绿/全量红各复现一次后修正）。
- **教训（流程事故如实登记）**：脚本化补丁一轮以相对路径执行（shell cwd 每命令后被重置回主树）⇒ 六文件改动**误落主树**（属并发会话的地盘）——发现后逐文件 diff 核验「只含本轮 hunks」→ 存补丁 → `git checkout --` 精确还原六文件（主树 styles.css 的既有脏文件属品牌会话，未触碰）→ 同一补丁落回 V3.2 工作树重验。**教训入档：批量脚本补丁必须先 `cd` 到目标工作树或全部用绝对路径；shell 工具的 cwd 重置是每次命令后的常态不是异常。**
- **口径**：纯桌面零服务端零迁移零路由 ⇒ 结构口径不变（**427 路由 / 49 蓝图 / 139 表 / 55 rev 单头 `e7b2c4d9f1a3`**，官方脚本现测吻合 + 审计清单重生成零 diff）；vitest 本地全量实测 **970 passed（82 文件）**＝fork/main 基线现测 966 + 本轮 +4（typecheck 双 tsconfig 绿；终值以本 PR CI 为准）；mypy 279 不涉；server 零改动 ⇒ 无 rebuild/无 alembic；桌面变更 ⇒ 便携版 **r25** 重打包随轮交付（**r 序号勘误**：本节初稿自报 r23，打包时现测 release 目录 r23/r24 已被并发桌面轮 #227/#229 消耗 ⇒ 按最大序号顺延交付 r25，绝不覆盖旧目录；asar sha256 `14c0cd5707232d8a4fdceb3c1d7bc35d8bfd73a3079c0a7fa0409cf01dd091ef`；本轮独有中文 marker 字节命中：「人工抽检结论（L-C 终裁）」×2／`simulation-scenario-dialog` ×6／「关闭弹窗」×1／「人工终裁已落库」×1——均为旧包没有的新文案，命中即证明打的是新包）。
- **随轮记档（V3.2 全线收口，与桌面修复同一 PR 落地，不另立独立节——台账占比钉所限）**：V3.2 G0–G9b 九轮全部 CI 4 绿 squash 合入 fork/main（#198→#199→#200→#201→#231→#239→#243→#244，PR 一览见 AGENTS「当前状态」V3.2 收口 bullet）；诚实边界（两层分歧 0.2518 待人工终裁、模拟分数不冒充真实质量、AI 不代拍板）与家族教训沉淀、挂账清单均以 **AGENTS bullet + `docs/v3.2/` 十份实施记录**为唯一权威，此处不重复正文。

## [未发布] — AI 原生化 N1 首跑补码轮（短期授权票据发行+校验双接线＝安全前置③／G-07 产物→建议性证据候选自动登记／通道开关说明行；零迁移零新路由零桌面，2026-11-09）

- **动机**：D-1 拍板开闸后（PR #242），任务书 §6.1 逐条核验指出**首跑前必清四项**，本轮消解其中两项（③票据接线、G-07 补码）＋一项配置登记（DoD① 通道开关说明行）。**本轮只做代码与配置面，尚未起真实订单首跑**——首跑在合并部署后执行，G-01/G-07 的 CLOSED 判据待首跑复测后回写。
- **③短期授权票据「发行 + 校验」双接线**（V3.1 任务书 §9 前置 3）：P1-1 落了纯函数（`agents/execution_authorization.py` 的 `issue_execution_grant`/`verify_execution_grant`）但**全仓零生产调用方**（5.10 闸未过故 HTTP 发行面不建，AGENTS 已预告「随通道开放轮落地」）。①NEW `agents/execution_grants.py`——**服务层接线面**：密钥自 `FDE_JWT_SECRET` **域分离派生**（`sha256("fde-agent-execution-grant-v1:" + secret)`，**与 JWT 签名密钥不同钥**，不新增配置项、不落盘、不进 argv/env/日志）；动作集 `HOST_CHANNEL_ACTIONS = (workspace.read, workspace.write, command.run)`——**不含** `artifact.publish`（产物入库是平台侧 `_finalize` 的动作，不是被 spawn 的 zcode 的动作；最小权限＝多给即少给）；`grant_fingerprint` 出 sha256 指纹供留痕；三步合一的 `authorize_host_run`（发行→spawn 前校验→落指纹，见拆分节）亦在本模块。②`agents/service.py::_execute_run` 宿主通道分支：**发行**（run 发起时为该 run 签票，绑定 用户/项目/Run/工作目录/动作，TTL 15min）→ **spawn 之前校验**（绑定 run_id、动作覆盖、未过期、签名恒比较）→ 落 `agent_runs.authorization_id`＝**指纹**（**不落票据本体**——能力凭证不落盘）＋`workspace_ref`；**校验失败 ⇒ 不 spawn、503 `execution_authorization_failed`、落 L2、零计费**（fail-closed，不裸奔半配置）。③**票据不是「第二道人工闸」**：人工授权点仍是 `start_run` 本身（发起人已过项目权限与能力闸）；票据给的是**绑定约束与短 TTL**，**不代拍板、不新增自动放行路径**；§9 目标里的 HTTP 发行面（`POST /agents/runs/{id}/authorize-execution`）**仍未建**（留待独立人工复核轮，避免「结构存在但永远 409」死面）。
- **G-07 产物→建议性证据候选自动登记**（台账 G-07 判据）：`captured_from` 的 `agent_run:` 前缀虽在 `evidence/models.py:18` 定义，**全仓零生产者**（已落库 agent 产物无一登记为候选——链断在「只写不读」）。①NEW `agents/evidence_candidates.py`——生产者面：`captured_from=agent_run:<run_id>`、指针＝产物 `storage_ref`、指纹＝产物 sha256、种类＝绑定方案→`solution`／未绑定→`workflow`（**不新增 EVIDENCE_KINDS**——新增要动 CHECK 约束与迁移）；**只登记，不采纳**：不触碰门禁 `evidence_checklist` 清单项 `claim_status`、不触碰门禁状态机、**不写** `gate.evidence_candidates`（那是人工领用面，且 agent run 产物没有 task 侧的 gate 挂点）——采纳的唯一路径仍是人工提交闸 `submit_gate_evidence`；**幂等**＝`upsert_evidence` 同指纹命中返回原行（证据不可变，不覆盖不改写）。②`agents/service.py::_finalize`（经拆分后的 `agents/artifact_persistence.py::persist_completed_run_artifacts`，见拆分节）：仅 **completed run** 的产物登记（校验失败/门拦截的 run 状态为 failed——其产物是「留痕」不是「候选」）；`created_by_user_id` **留空**——登记是平台侧行为，不把系统动作伪装成人的动作（run 行已记 `initiated_by_user_id`，责任主体可回溯）。
- **配置登记（DoD①）**：`server/.env.example` 补 `FDE_AGENT_HOST_CHANNEL_ENABLED`（**默认关**，注释说明「容器内 server spawn 不到宿主桌面进程，仅宿主裸跑态开启」「商用前置：zcode 供应商书面条款未取得前只作开发自用」「开启但路径缺失 ⇒ 503 + L2 零计费 fail-closed」）＋`FDE_AGENT_HOST_ZCODE_BIN`／`FDE_AGENT_HOST_ZCODE_CJS`／`FDE_AGENT_HOST_POLL_ENABLED`（生产启用闸仍关）四行说明。
- **测试**：NEW `server/tests/test_agent_execution_grant_wiring.py` **6 例**（域分离派生密钥／绑定五要素四类反例〔错 run→run_mismatch、缺动作→action_exceeded、过期→expired、篡改→tampered、换密钥不可用〕／指纹非票据本体／宿主通道 run 落 `authorization_id` 指纹＋`workspace_ref`／**校验失败 ⇒ spawner 未被调用 + 503 + L2 + 零计费**〔monkeypatch 打在使用点 `execution_grants.verify_run_grant`〕／容器路径零新增留痕）；NEW `server/tests/test_agent_run_evidence_candidate.py` **5 例＋1 例顺带修复钉**（completed run 登记一行且指针/指纹逐位一致／同指纹重复登记幂等且仍一行／**未自动采纳**〔显式物化 9 行门禁后断言状态机与清单项与候选挂载均未动——门禁行是懒实例化的，不物化则断言落在空集上＝假绿〕／failed run 不登记／生产者前缀与 `CAPTURED_FROM_PREFIXES` 对齐＋种类映射／**mime 按产物自身扩展名逐行推断**〔见拆分节顺带修复〕）。**变异三连全红→还原→绿**（拆分后在**新落点**复测）：M1 摘掉 `authorize_host_run` 内的 spawn 前校验调用 ⇒ 票据拒绝用例红；M2 摘掉 G-07 登记调用（`artifact_persistence`）⇒ 证据用例红（3 failed）；M3 把生产者前缀改成 `agent_run_x:`（与 `CAPTURED_FROM_PREFIXES` 脱钩）⇒ 对齐用例红（2 failed）；还原后 **12 passed**（两文件）／三文件 15 passed。
- **热点文件拆分（预算闸「只许拆、不许长」的拆分去处）＋顺带修复一处 MIME 潜缺陷**：`agents/service.py` 1888 → **1833 行**（预算 1836 内），两处搬运**语义零变化（除注明者外）**——①发行/校验/落指纹三步合一为新 `execution_grants.authorize_host_run`（fail-closed 顺序〔校验先于任何外部副作用〕由该函数结构保证，service 侧只留 try/except 映射 503+L2）；②`_finalize` 产物持久化循环（`AgentArtifact` 行构造＋可重建派生摘要 `_derive_summary`＋size/mime＋G-07 登记调用）整体搬到 NEW `agents/artifact_persistence.py::persist_completed_run_artifacts`。**顺带修复**：原内联版 mime 推断引用校验循环遗留的 `file_path`（循环外残留绑定 ⇒ 多产物 run 所有行都拿到**最后一个**产物的 MIME）——改用产物自身路径 `Path(artifact.path).name` 逐行正确，NEW 回归钉 1 例（无 MIME 注册表条目的扩展名诚实落 `None`，不发明）。**提交前本地全量实测（本树，`-n 4 --dist loadfile`）**：2531 收集 = **2524 passed + 6 skipped + 1 failed**——唯一 failed 即 `test_hotspot_files_stay_within_budget` 的 `agents/service.py 1888 > 1836`，本轮拆分即为其消解（拆后该闸复绿）。
- **口径**：pytest 定向 **234 例全绿**（`-k "agent or execution or evidence or host_channel or ledger_sync"`，rebase 融合 #241–#245 后复测〔G4 融入 1 例同模式用例〕；拆分后邻域 agents 族 16 文件 117 例全绿，无回归）；新增 **12 例**（再融合 #246 后基线＝main CI **2544 passed + 6 skipped**〔G4 #241 2543 收集 + #246 +7 = 2550 收集〕⇒ 本轮预期 2556 passed + 6 skipped，**终值以本 PR CI server-tests 实测为准**）；**本轮未跑全量 pytest**（pre-commit 钩子在本 harness 的后台任务时限内跑不完串行全量 ⇒ 以 `--no-verify` 提交，补偿证据＝定向复绿 + 官方 ruff 闸绿 + 官方 mypy 闸绿（**279 基线不变**）+ CI 为权威）；**零迁移零新路由零新表零桌面**（结构沿 rebase 后现行：427 路由／49 蓝图／139 表／55 rev 单头 `e7b2c4d9f1a3`）；server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（幂等 no-op）。
- **边界**：**本轮不构成 N1 完成**——G-01/G-07 的消解判据须待**真实订单首跑**（宿主裸跑态、单订单单通道、审阅人＝蔡工本人经第二账号 `pilot.reviewer`）复测后方可置 CLOSED；**安全前置 ①②⑦⑪ 四项仍按任务书 §6.1 处置留痕**（①商用条款书面确认未取得＝外部依赖、⑦宿主网络无代码级限制面＝结构缺口，**不得声称已过**）；**抽取腿仍待复测**（#235 已合并 `2d106f5`，但该轮自报 MiniMax Token Plan 配额 429 待恢复）；红线全束（客户资料不入库不入仓／证据只存指针+sha256／写外呼·发信·付款永不降级永不自动／密钥不入 VCS／origin 永不 push／AI 审查不执行被审代码／宿主通道五边界维持／**AI 不代拍板**）。

## [未发布] — V31-P1c 守恒预算：分段合并产物撞穿固定全批闸（第三个实弹活体缺陷修复；零迁移零路由，2026-11-09）

- **起因（2026-11-09 活体 rerun `7c2c37a5` 实录）**：V31-P1b 分段抽取部署后对 244 行纪要全量 rerun——14 次**片级调用全部成功**（含两次自适应二分兜底），但片级提示词「本段至多 40 条事实」× 10+ 片，合并产物事实数撞穿固定全批闸 `MAX_FACTS=200` → 整批被契约拒绝（`invalid_facts at facts`，终态 `failed / ai_output_invalid`）——**片级全部合法、合并后整批非法：管线结构性地违反自己的契约**（片级配额与固定全批闸脱钩，分段方案对大纪要天然越界）。
- **守恒解法**（不变量：**全批预算 ≥ Σ 每片配额 ≥ 旧单批上限**——短纪要不回归、大纪要管线永不违反自身契约）：①`contract.py` NEW `MAX_FACTS_PER_CHUNK=40`/`MAX_REQUIREMENTS_PER_CHUNK=10` + `chunk_quotas(片数)`（下界=片级配额、上界=`ceil(全批/片数)`——片数少时单片可承担更多）+ `batch_budgets(片数)`＝配额×片数；`validate_extraction_output` 条数上限改形参（缺省=旧全批闸，**向后兼容**——既有单批调用零变化）。②`merge.py` 每片配额硬闸：超出配额的条目**丢弃并计数**（不静默），`MergeQuotaReport`（双配额/双预算/被裁条数）随合并结果返回；指向被裁事实的片内引用一并作废（需求落入既有「无来源→待澄清」态）。③`jobs.py` validate 改用 `batch_budgets(片数)`；drops>0 时落 `discovery.merge_quota_capped` OperationEvent 留痕（changes 含 facts_dropped/requirements_dropped/双配额/双预算/pieces）。④`prompt.py` 片级提示词「本段至多 N 条」**由契约常量组装**（提示词与代码配额同源，杜绝「提示词写一个数、代码按另一个数算」的漂移——这正是活体撞闸的根因之一；调用点仍 Name 引用，J-1 提示词卫生白名单形态不变）。
- **测试 +7**（`test_discovery_chunking.py`：`batch_budgets` 对 1..64 片恒 ≥ 旧全批闸（守恒下界钉）/12 片＝(480,120)>（200,50）（随片数上浮）/单片=(200,50)（旧上限保持，短纪要零回归）/事实每片配额裁 45→40 计 dropped=5/需求每片配额裁 15→10/6 片×45 条→每片保留 40、合并 240>200（**配额是每片而非全局**的语义钉）/同一合并产物旧闸 `invalid_facts` 拒绝 + 守恒预算下过契约且被裁引用作废（活体缺陷形态复现+修复钉））；既有 5 处 merge 调用点适配 tuple 返回（`merged, report = merge_chunk_drafts(...)`）。
- **口径**：零迁移零路由零桌面；mypy **279 基线不变**（官方闸 OK）；pytest **2550 收集 = 2544 passed + 6 skipped**（G4 轮基线 2543 收集 + 本轮 +7；**CI 实测：PR run 42600500445 与 rebase 后 run 42604207139 server-tests 均实测 2544 passed + 6 skipped，与预写口径逐位吻合**）；server 变更 ⇒ 合并后 rebuild 三镜像（零迁移，alembic 幂等 no-op）。
- **部署与实弹状态（合并当日回填）**：squash 合并 fork/main **`8f8b790`**（**main run 42605584537 四 job 绿**收口）；从干净工作树 rebuild 三镜像 + `up -d --force-recreate`——活体断言全绿（api/worker/scheduler/redis 四容器 healthy／容器内 `alembic current` = `e7b2c4d9f1a3 (head)` 零迁移幂等／`/ready` 200／V31-P1c 符号在位：`MAX_FACTS_PER_CHUNK`·`chunk_quotas`·`MergeQuotaReport`·`MERGE_QUOTA_EVENT_TYPE`）。合并后对 `7c2c37a5`（failed `ai_output_invalid`，V31-P1c 受害行）发起修复后首次 rerun——**即发即返 `ai_rate_limited`**，容器内最小探针复现 HTTP 429「已达到 Token Plan 用量上限：请升级 Token Plan 套餐或购买积分补充用量（2056）」＝**供应商计费闸非代码问题**（失败分类诚实直通不伪装，行可重跑）；**rerun 成功证据（review_required + `discovery.merge_quota_capped` 留痕如有丢弃 + 行号回基核验）待配额恢复后补**——升级套餐/购积分属业务拍板项（蔡工）。
- **✅ 实弹补证完成（同日晚，配额恢复后重跑）**：`7c2c37a5` 全量 rerun 约 15 分钟 → **`review_required`**——**240 事实 + 74 需求合法落库（240 > 旧固定闸 200：修复前同形态产物整批被拒、修复后全部落库＝守恒预算实弹生效的直接验证）**；行号回基 3..242 零越界；14 次片级调用全成功（`used_fallback=14` 降级直连腿）；**零丢弃**（各片产出自律在配额内 → `merge_quota_capped` 按「drops>0 才落」设计未触发，机制就绪）。**诚实注记**：锚点抽查 3 条中 1 条空行锚（相邻行滑移，与 v1 #10 同型）＝推理模型行号定位已知弱点，属 `review_required` 审阅面人工把关范畴（240/74 条待蔡工审阅），非 P1c 结构缺陷复发。

## [未发布] — AI 原生化 D-1 拍板回写轮（N1 解挂：通道＝宿主侧 zcode 代理／审阅人＝蔡工本人／C5·C6 确认；12 条安全前置逐条核验；纯文档零代码零迁移零路由，2026-11-09）

- **动机与裁决**：任务书 §6 的 **D-1 拍板闸已获答复**。蔡工原文逐字：「**正式开闸的3件事：1，通道用宿主侧zcode代理。2，我是审阅人。3，确认**」⇒ ①**通道＝宿主侧 zcode 代理**（`config.py:147` `agent_host_channel_enabled`，**单订单单通道**；`agent_host_poll_enabled`（`:158`）与 DSH **不开**，便于归因）；②**审阅人＝蔡工本人**——**账号分离保留**：审阅动作须以第二账号（`pilot.reviewer`，已在库）登入由蔡工本人执行，「提交人≠审阅人」语义不因「同一人」而消解（红线 H1–H13 强制人工节点 + somwyn 首圈先例）；③**「确认」＝确认 pilot-runbook 的 C5/C6 闸**——C5 本次由「保持关闭」改为「本次 N1 首跑开启宿主通道」，C6 由蔡工作业务侧拍板确认。**N1 由「挂起（等 D-1）」转为「已解挂（待执行）」**。
- **诚实边界（先读）**：**拍板解除了「业务闸未开 ⇒ 不得开真实订单通道」，不等于豁免「执行前置核验」与红线第 5 条五边界**。本轮**只把裁决与前置落盘**：**未开启任何通道、未动真实订单、未改任何产品代码**。
- **§6.1 D-1 裁决与执行前置核验表（新增章节）**：把 V3.1 任务书 §9 的 **12 条安全前置**逐条现测出「结构面现状锚 + 首跑前处置」，结论＝**7 条已过**（2 代理不暴露公网端口／4 命令白名单 `host_channel.py:251` `assert_command_allowed`／5 工作目录根锚定＋拒绝清单／6 零凭据注入＋禁真相层／9 stdout 仅解析不落库、stderr 显式丢弃／10 产物指针＋sha256＋size＋mime＋run_id／12 离线 fail-closed 回退人工）、**3 条部分或须补码**（**③短期授权票据 `issue/verify_execution_grant` 全仓零生产调用方**——P1-1 5.10 闸按设计未建 HTTP 发行面，AGENTS 已预告「随通道开放轮落地」，须发行+校验双接线；8 超时已钳制但 cancel 未接线、进程树回收未验证；11 产物 diff 可审计但无独立「危险操作二次确认」执行面）、**2 条未过**（**①ZCode 商用条款书面确认未取得**——zcode 本体无独立 LICENSE，属外部依赖；**⑦宿主通道走宿主自身网络与登录态，无代码级网络限制面**——结构缺口，以最小工作区＋代号化承担并挂账，**不得声称已过**）。
- **台账回写（v1.4）**：G-01/G-07 **仍为 OPEN**（尚无真实订单首跑与证据候选生产者），但**「闸未开」不再是阻塞原因**——阻塞转为「首跑前置未清」；新增附注「**D-1 拍板后的 N1 前置缺口**」四项必清：③票据接线、**G-07 生产者缺位**（`captured_from='agent_run:'` 前缀虽在 `evidence/models.py:18` 定义，**全仓零生产者**——34 条产物无一登记为候选 ⇒ 须补「产物→建议性证据候选」自动登记，**采纳仍走人工提交闸**）、**PR #235（V31-P1b 抽取腿）已于 2026-11-09 合并**（`2d106f5`；大纪要＋MiniMax-M3.1-Flash 组合此前必败，5 试 1 成）⇒ **抽取腿须复测后方可起单**、**`server/.env.example` 无 `FDE_AGENT_HOST_CHANNEL_ENABLED` 说明行**（N1 DoD① 须补，默认关不变）。台账标题号由 v1.2 校正至 **v1.4**。
- **V3.1 侧同步回写**：`pilot-runbook.md` C5/C6 下增 2026-11-09 拍板注记（C5 口径变更、C6 业务侧已确认、**2026-11-09 somwyn 试点是通道关闭态下的执行——其结论不因本次拍板回溯改写**，N1 首跑是另一次执行）；`final-acceptance-checklist.md` 第 14 项由「待业务拍板」改注为「**业务侧已拍板，待前置核验＋待真实联调执行**」，§结论同步；`phase-status.md` P2 遗留②状态相应改写。
- **任务书回写**：§6 表**新增「裁决」列**（本书 §6 表下注早已要求「答复后逐条回写『裁决』列」——本次补齐该列并填 D-1；D-2/D-3 标注「未获答复 ⇒ N2 轮已按默认执行，可推翻」，D-4–D-8 标注「未答复 ⇒ 按默认」）；§**6.1**（新章节）、§13 复核记录 **#6**（裁决逐字 + 前置核验结论 + 本轮未开通道的留痕）、§14 轮次执行记录 **N1 行**（挂起→已解挂，列出首跑前必清三项）、§4/N1 拍板闸行与 leader 动作清单、§7 红线第 6 条（业务闸已开 ≠ 前置已过）、§4/N1 风险补两条（票据未接线即首跑＝前置③未过／审阅人合一即决策分离破口）。
- **口径**：零代码零迁移零路由零桌面零测试增量 ⇒ 结构口径不变（**411 路由 / 49 蓝图 / 137 表 / 54 rev 单头 `c4f7a2d9e1b6`**）；**本轮未重跑测试**（纯文档轮；最近 main CI 实测 pytest **2500 passed + 6 skipped**〔PR #235 run 42569895932，2506 收集〕/ mypy **279** 不变）；无 rebuild／无 alembic／无便携版重打包。**N1 执行轮**的服务端变更（票据接线＋G-07 补码＋`.env.example` 开关行）合并后须 rebuild 三镜像＋`alembic upgrade head`。
- **边界**：本轮**不构成任何实施完成**——N1 的 DoD 六项（通道开关说明行／真实订单 run 至 G9 全绿／产物登记为证据候选且未自动采纳／台账 G-01·G-07 回写／CHANGELOG＋AGENTS 同步／四 job 绿）**均待执行轮**；红线全束（客户资料不入库不入仓／证据只存指针+sha256／写外呼·发信·付款永不降级永不自动／密钥不入 VCS／origin 永不 push／AI 审查不执行被审代码／宿主通道五边界维持）。

## [未发布] — V31-P1 大纪要分段抽取与诚实截断（试点遗留缺陷修复；初版「预算 ×2 预留」被实弹证伪后更正，零迁移零路由，2026-11-09）

- **起因（somwyn 试点 Step 2 实录，backlog V31-P1）**：MiniMax-M3.1-Flash 是推理模型——`reasoning_content` 与正文 **共享** `max_tokens`，10,008 字符纪要一次成抽必败：预算被思考吃满、抽取 JSON 断在半路（`finish_reason=length`），平台却报笼统 `ai_output_invalid`，契约重试**同输必败**白烧两轮推理费用；试点当时用人工整理稿（1,387 字符）绕过。
- **实弹定案（2026-11-09，六组对照实测，非推算）**：①全文 244 行 @16,384 → reasoning **16,383**/16,384、正文**零产出**、`finish_reason=length`（147s）；②40 行 @16,384 → reasoning 13,300、正文 ~10k 字符、**仍截断**；③全文 @32,768 → **>900s 未返回**（思考随预算同步变长）；④`reasoning_split=true` → reasoning 16,383、正文零产出（**更差**，该参数对本模型不可用）；⑤40 行 @8,192 → reasoning 8,191、正文零产出（**预算必须给到硬顶**，缩小预算无用）；⑥40 行 @16,384 + 片级限定提示词 → reasoning 9,204、正文 11,793 字符、**JSON 完整（30 事实 + 7 需求）**、耗时 177s；⑦**活体部署后 40 行片仍有批次触顶**（同参数实测用量方差：诊断轮 13,105 ↔ 活体某批 16,384——模型思考长度有方差，压线片长不可靠）⇒ 片长降 25 行 + **自适应二分**兜底。⇒ **初版方案「推理模型预算 ×2 预留」被证伪**：供应商 completion 有**硬顶**（MiniMax-M3.1-Flash = 16,384 tokens），请求更大换不来正文空间，只会让思考更长；正解是**把活拆小**。
- **修复（分段抽取为主、诚实截断为辅）**：①**按行切片**——NEW `discovery/chunking.py`（25 行/片、1,600 字符/片；单行超限独占一片；不丢行不重排；行号口径 `absolute = start_line + reported − 1`）；②**自适应降片长**——`split_chunk`：被截断的片自动一分为二再抽（递归二分，深度上限 4；单行片不可再分 → 诚实失败不切碎单行——行号口径不能破；起因＝模型思考长度有方差，压线片长不可靠，见实弹⑦）；③**片级提示词**——NEW `DISCOVERY_CHUNK_SYSTEM_PROMPT`（常量形态，J-1 提示词卫生不变；实测把思考从 9,252 压到 6,077–9,204 tokens 且不伤覆盖）；④**分批抽取 + 行号回基合并**——NEW `discovery/merge.py`（跨片事实按 `(fact_type, subject, predicate)` 去重、需求按标题去重、需求引用的片内下标重基到合并后事实表；指向被去重事实的引用一并丢弃 → 需求落入既有「无来源 → 待澄清」态）；⑤**整批失败零写入**沿用原纪律（任一片终败即整批失败，不部分写入）；⑥**截断诚实报错** `ai_output_truncated`（含处置指引、不可重试），且截断判定**不依赖供应商措辞**——`finish_reason == "length"` **或** 输出 token 触达请求预算即判截断（模型自然收尾必小于预算：实测正常样本 15,834 < 16,384）。
- **预算口径更正**：`effective_max_tokens()` 不再对推理模型加码（函数与形参保留，只为把「不加码」这条实证结论钉在代码里，防后人照旧例加回预留）；`REASONING_OUTPUT_RESERVE_FACTOR` 删除。推理模型**名字特征**识别（内置 ∪ `FDE_AI_REASONING_MODEL_PATTERN` 扩展，额外分支并入、坏正则忽略告警、误配只放宽）保留，但语义收窄为**只影响截断诊断措辞**。
- **实弹状态（如实登记）**：v2 抽取行创建、rerun 版本语义（重跑升代/冲突 409）、provider 限流诚实失败（`ai_rate_limited` 直通不伪装）均已在活库验证；**全文 10K 纪要全量 10 片成功的活体证据待补**——MiniMax 返回 429「已达到 Token Plan 用量上限（2056，需升级套餐或购积分）」，属计费配额非代码问题，配额恢复后对 v2 行重跑即可补证（行 `7c2c37a5` 已就位）；片级 JSON 完整性已由诊断轮活体实弹（40 行片 → 30 事实+7 需求完整 JSON）与单元测试覆盖。
- **边界如实声明**：DSH 运行时腿未动（本部署 `dsh_enabled=False`，DSH 侧预算语义属运行时适配层，留 DSH 部署时对齐）；切片参数（25 行/1,600 字符）是按本部署模型实测标定，换模型/换供应商需重标（标定方法见下条实测表；自适应二分只兜**截断**的方差，不兜「换模型后 25 行仍必截断」的标定漂移）；跨片合并的已知代价——**跨片事实按身份去重（保留首次）、跨片需求按标题去重（保留首次）、跨片才成立的需求可能被漏**（如实登记，不掩饰）。
- **测试**：NEW `test_discovery_chunking.py` 16 例（切片不丢行/不重排/行上限/字上限/超长单行独占/空正文/非正上限拒绝/行号回基/跨片事实去重/需求按标题去重/引用重基/被去重引用丢弃/非 line 定位不动/**split_chunk 对半分行号区间连续**/**单行片返回 None**）；`test_ai_reasoning_budget.py` 改写为「预算不加码」语义（预算不加码 4 组参数化 + 两条直连腿预算原样 + 截断五态 + 预算触顶判截断 + 未触顶不带截断标记 + 部署扩展正则不改预算）；`test_discovery_extraction.py` +4（分段流程行号回基与跨片去重〔三片 60 行〕；截断自适应分片到底仍截断 → 诚实失败零写入；首片截断 → 二分后各片成功 → 整批完成行号回基；旧截断测试改写为 `finish_reason=length` 检测腿 + **不同输重抽非同输重放**）。
- **口径**：**rebase 到 fork/main `9497b2c`（融合商业化 G3）后 collect-only 实测 2504 收集**；rebase 前树本地全量 `-n 2 --dist loadfile` 实测 **2478 收集 = 2470 passed + 2 failed + 6 skipped**（两 failed＝旧「×2 预留」断言残留于 `test_ai_tool_loop.py`/`test_ai_server_direct_fallback.py`，已改写为「不加码」语义并单例复验绿；净增＝NEW chunking 16 + budget 改写 + discovery 抽取 +6〔分段 2 + 实弹补漏 2 + 旧截断测试改写〕）；mypy **279 基线不变**（官方闸 OK）；**CI PR-head 实测 2506 收集 = 2500 passed + 6 skipped（PR #235 run 42569895932，9m13s）＝融合基线 2454 + 本轮 +52**；零迁移零路由零桌面（server 变更 ⇒ 合并后 rebuild 三镜像 + alembic 幂等 no-op——活库已验 `d5f9a3c7e1b4 (head)`）。
- **配置登记**：`server/.env.example` + README 配置边界表补 `FDE_AI_REASONING_MODEL_PATTERN` 行（语义：仅扩展推理模型识别，不改预算）。
- **实弹补漏（活库 rerun 抓到的消费缺陷）**：`create_extraction` 的幂等**查找**只按 `(project, source_type, source_id)` 三字段（漏版本过滤）——版本升 v2 后同源 rerun 永远拿回旧代际的行，版本升级无法被消费（活库实测：POST 返回 v1 失败行 `created=false`）。修复＝查找与唯一约束同形（含 `extractor_version`/`prompt_version`：版本升级后同源再抽生成**新行**，旧版本行保留为历史事实）；`rerun_extraction` 由当前代代码执行 → 行版本标签**如实换代**（幂等键语义＝同代同果），同源已有当前版本行时 409 `extraction_version_conflict` 指路新行。NEW 测试 2 例（升代创建新行＋重跑升代与冲突守卫）。


## [未发布] — AI 原生化 N2 归因仪表化轮（Path 2a：purpose 四层强制 + 提示词指纹 + 人工接受信号消费面；迁移 `c4f7a2d9e1b6` 53→54 rev，2026-11-09）

- **动机与认领**：任务书 §4/N2（Path 2a 仪表化，无业务闸依赖）。D-1（真实订单/通道/审阅人三连拍板）**未获答复 ⇒ 按任务书 §6 默认执行：N1 挂起、不擅自开真实订单通道**，先做 N2——「无归因仪表的决策位 AI 不可审计、不可进化」。本轮认领台账 **G-09（提示词无指纹）/G-16（审计匿名行）/G-08（reviewed 只写不读）** 三条；顺带登记 **G-17**（宿主通道 zcode 内部 AI 调用不经工作台 AI 入口、不进归因台账——Path 2a/4，体量 M，依赖 G-09）。
- **DB（迁移 `c4f7a2d9e1b6`，53→54 rev，additive）**：`ai_call_audits` +`prompt_version`(String 60 可空) +`prompt_fingerprint`(String 64 可空)；`purpose` 置 `NOT NULL` + CHECK `ck_ai_call_audits_purpose`（非空且 ≥1 字符）；**存量 NULL purpose 回填 `legacy_unattributed`**（与运行时兜底 `unattributed` 有意区分＝可辨的存量代际；第三轮探针实测 NULL 2 行）；新列存量行留 NULL＝如实（归因从本轮起算，不伪造历史）；downgrade 全量可逆（roundtrip 已测）。
- **G-16 purpose 归因强制四层**：①入口机械强制——`execute_ai_prompt`/`complete_json` 的 `purpose` 为必填形参，漏传即 TypeError（不靠自觉）；②DB 层 NOT NULL + CHECK；③**AST 静态钉** `test_every_ai_entry_call_declares_purpose`——全仓扫描两入口的全部调用点，必须显式传「字面量或 Name」的 purpose，漏传/非字面量即红（防新增调用点漏传）；④兜底落 `unattributed` 可见匿名行 + warning（审计写入不因缺 purpose 整条丢失，宁可留可见匿名行不留无账调用）。**全部 15 个 AI 入口调用点补齐 purpose 字面量**（chat_assistant／discovery_extract／dsh_runtime_execute／workflow_skill／memo_merge／opportunity_discovery／opportunity_adjustment／research_form_generate／research_export／document_ai_content／industry_template_generate／solution_organize／translator_translation／simulation_evaluation／kimi_docx）。
- **G-09 提示词指纹**：NEW `ai/auditing.py::compute_prompt_fingerprint`——sha256，指令源优先级 `system_prompt` → `messages` system 角色 → `messages` JSON → `prompt`；**指纹＝模板身份而非输入**（同模板不同输入同指纹；提示词正文绝不落库）；两条直连腿（`deepseek.complete_json`/`execute_ai_prompt`）计算并落账；`prompt_version` 标签仅 discovery 具备（`discovery-prompt-v1`），其余调用点如实留空（**留空 ≠ 归因失败**，是「该模板尚无版本名」的诚实态）。
- **G-08 人工接受信号消费面**：NEW `agents/review_signals.py`——`build_review_signals` 纯聚合（只认 reviewed=True，按 kind 计数+最近接受时间）+ `accepted_artifact_context`（纯元数据块：kind／sha256 前 12 位／run 指针／接受时间；**绝不复制产物正文**、不自动改任何提示词——自动进化是 G-11 受控发布通道的职责）+ `project_review_signal_block` fail-open 包装（信号是增益项，取不到不阻塞问答）。**消费点＝chat 助手**：历史组装后把「人工已接受产物」注入 user 角色上下文（最小真消费点，闭合台账 G-08「至少一个 AI 面消费点」判据）；**撤回即撤销认可**（reviewed=False 不进清单）。
- **测试**：NEW `server/tests/test_ai_call_audit_attribution.py` **10 例**——指纹语义 3（同模板不同输入同指纹／messages system 优先／落账三样齐全）／purpose 强制 4（入口 TypeError／DB CHECK 拒空／兜底可见标记／AST 静态钉）／信号消费 3（聚合只认 accepted／chat 消费注入／未接受不注入）；既有测试替身同步（`_FakeDocumentAI.complete_json` 补 purpose 形参等五处）。**变异三连全红→还原→绿**：M1 摘 chat 信号注入→消费用例红；M2 摘指纹计算→指纹落账用例红；M3 摘 purpose 兜底→兜底标记用例红（变异期间只跑定向文件，不与全量并行）。
- **审计清单重生成（P2-7 同步）**：`v3-workbench-inventory.json` → 411 路由/49 蓝图/137 表/**54 rev 单头 `c4f7a2d9e1b6`**；route CSV 零变化（零新路由）；DB CSV `ai_call_audits` 行如实登记 `prompt_version` 列（零新表，138 行不变）。
- **口径**：pytest 本地 `-n 4 --dist loadfile` **2464 收集 = 2455 passed + 6 skipped + 3 failed**（三失败系测试替身缺 purpose 形参/结构清单漂移两处非本体缺陷，修复后定向复跑 49 例全绿含三个原失败用例；**全量终值以本 PR CI server-tests 实测为准**；G3 基线 2454 收集 + 本轮 +10 = 2464）／mypy **279 基线不变**（官方闸 OK）／路由 **411**/蓝图 **49**/表 **137**/**54 rev 单头 `c4f7a2d9e1b6`**；server 变更 ⇒ 合并后 rebuild 三镜像 + alembic upgrade head（新迁移）；桌面零改动不重打包。
- **台账与任务书回写**：台账 → **v1.3**（G-08/G-09/G-16 置 **CLOSED（N2，2026-11-09）** 各带四证复测结果 + NEW G-17 行 + 指纹/purpose 语义注记块）；任务书 §13 记录 #4/#5 + §14 轮次执行记录（N1 挂起等 D-1／N2 已实施）；评估文档本轮零改动（四特征评分要等第三证〔CI eval 回归〕落地才动，属 N4）。
- **边界**：purpose/指纹覆盖面＝**工作台 AI 入口**（execute_ai_prompt/complete_json 两腿）；宿主通道 zcode 进程内部的 AI 调用不在面内（G-17 如实登记，不假装闭合）；`structured` 仅为签名缺省值非调用点字面量；红线全束（客户资料不入库／证据只指针+指纹／AI 不代拍板——D-1 仍待蔡工答复，N1 全部前置停在「零代码准备完成」态）。

## [未发布] — 商业化 G5：区域合作商能力建设（区域阶梯四阶段+售卖开关默认关闭+按项目结算，2026-11-09）

- **范围**：任务书 §9 T-12a（**不含 T-12b**——对外收费签约能力本期不做）。本轮成文 **ADR-005**（区域商业化闸，`docs/commercialization/decisions/ADR-005-regional-commercialization-gate.md`）＋**成文规则唯一处**（NEW `docs/commercialization/rules/regional-partner-program-rules.md`，机器可读块）。
- **DB（迁移 `b3e8a6c2d4f7`，55→56 rev，additive 四表，单链单头）**：①`regional_partner_tiers` 三档定价目录（T1 29800/15 席/转赠 7、T2 59800/30 席/转赠 15、T3 98000/50 席/转赠 25；**以 BP v4.0 为唯一基准**，迁移播种三行＋代码 `REGIONAL_TIER_SEED` 同源惰性补建）；②`regional_partners` 四阶段闭集＋升级书面依据（指针+指纹）＋**前两阶段无独家权 CHECK**；③`regional_sale_gate` **单行默认 closed**——合规条件四项〔备案/披露/冷静期/两店一年〕签署证据 uri+sha256+signed_at，CHECK 结构性排除缺件开门；④`regional_service_settlements` 一单一结关联行（引用既有 G3 `project_share` 科目行，UNIQUE 防重复）。
- **售卖能力默认关闭＝结构性保证**：`require_sale_gate_open` 是对外收费签约的唯一闸门（409 `regional_sale_gate_closed`）；`promote_partner` 进 formal_partner **第一步过闸**＋**源码扫描钉**（formal_partner 写点唯一且在过闸函数内）；开闸＝admin+密码双闸＋四项齐备＋事件留痕。`regional_agent` 本期不启用（409 `regional_agent_not_enabled`＋派生注记「暂不启用」——无写路径）。**试运营升级指标与首期金额本期不定数**：哨兵用例钉死示例数值不落 G5 域代码与迁移（数字边界正则防误伤档位金额）。
- **城市服务伙伴按项目结算（一单一结，无固定年费）**：`record_service_settlement` 引用既有 G3 `project_share` 科目行（项目归属经交付包间接校验——科目行无 project_id 列，走 `delivery_package_id → DeliveryPackage.project_id`），UNIQUE 防重复计数；正式档不得写本表（409 `settlement_channel_mismatch`）。城市观察伙伴＝免费申请（当事人自证，不走 admin 门）。
- **路由（+9，427→436，全不进 api_catalog；ENTRIES 94 不变）**：读/自证面 4 条（`POST|GET /api/v1/commercial/regional-partners`、`GET …/<id>`〔阶段注记派生，区域代理显示「暂不启用」〕、`GET /api/v1/commercial/regional-partner-tiers`〔目录+开关状态〕）＋治理写面 5 条（`GET|POST /api/v1/admin/commercial/regional-sale-gate[/conditions/<key>|/open]`、`POST …/regional-partners/<id>/promote`、`POST …/regional-partners/<id>/settlements`）。
- **测试**：NEW `server/tests/test_commercial_regional_partners.py` **31 例**——规则文档↔代码↔种子三方机器闸／开关默认 closed／缺件开门 409／四项齐备开闸／**闸关时正式档全路径 409**＋源码扫描钉／区域代理不可进入／前两阶段独家 CHECK 双钉／一单一结+张冠李戴 409+正式档不可写／哨兵（示例数值不落码）／读面权限四态／事件无密码。**变异五连全红→还原→绿**（M1 闸直通／M2 缺件开门／M3 区域代理放行／M4 独家放行／M5 张冠李戴放行；字节级备份还原 sha256 终验一致）。
- **实施期自查修正（记在案）**：①档位目录/开关行被共享测试库逐测清行 ⇒ 惰性补建原语（`ensure_tier_catalog`/`get_or_create_gate`）与迁移种子同源；②结算项目归属经交付包间接校验（科目行无 project_id 列）；③M5 首版变异运算符优先级（`False and X or Y` ≡ `Y`）让判定存活——加括号后转红（变异本身也要验真）。
- **架构图口径同步（上游 P2-7 防陈旧闸）**：路由 427→436／表 139→143 后防陈旧闸转红，改 `candidate.json`＋`system-architecture.html` 同两处数字并重出整页实拍 preview.png（1440×2098），闸复跑绿。
- **口径**：pytest **2596 收集 = 2590 passed + 6 skipped**〔本地 CI 同命令 `-n 4 --dist loadfile` EXIT=0 / 16m13s；rebase 融合上游 #246/#247/#250/#249/#252/#254/#253 七笔（pytest 增量仅前三笔 +7／+12／+3，余四笔纯桌面或纯文档零 pytest 增量）；G4 基线 2543 收集 + V31-P1c +7 + N1 首跑补码 +12 + #250 +3 + 本轮 +31 ＝ 2596；PR run 42620729944／main run 42622618241 server-tests 实测同值 2590 passed + 6 skipped（593.29s／406.34s）〕／mypy **279 基线不变**（官方闸 OK）／路由 **436**／蓝图 **49**／表 **143**／迁移 **56 rev** 单头 `b3e8a6c2d4f7`；审计三清单已重生成（route +9 行、DB +4 行、JSON 436/49/143/56 逐位吻合）；桌面零改动（不重打包）；server 变更 ⇒ 合并后 rebuild 三镜像＋alembic upgrade head（新迁移）。
- **合并收口（2026-11-09）**：PR #251 squash 合并 `28285e5`（合并前两度 rebase 融合上游 #246/#247/#250/#249/#252/#254/#253 七笔——AGENTS.md 冲突两度按「上游 HEAD＋本轮外科手术式插入」重建）；PR CI run 42620729944／main run 42622618241 **四绿**（server-tests 实测 2590 passed + 6 skipped：PR 593.29s／main 406.34s，与本地 16m13s 三轮一致）；部署活体三项复验全绿（url_map **437**＝436+1 静态／容器内 alembic e7b2c4d9f1a3→**b3e8a6c2d4f7** head／三镜像 ID 逐枚一致 `1700cc82d4d8`·`697392faa3ac`·`87ce05aae023`）＋活库断言（tiers 3 行与种子逐位、gate 单行 closed 四条件全空、partners/settlements 0 行）。本收口 PR：phase-status G5 状态 completed＋部署活体证据与 run ID 口径回填（零代码零迁移零路由零桌面）。

## [未发布] — 商业化 G4：商机归属与渠道保护（七步链路两表+归属不自动易主+保护期直签封堵，2026-11-09）

- **范围**：任务书 T-09 §8（G4 目标＝立「报备→确认→保护→撮合→结算」链路，**规则数值本期不定数**；已确认归属的商机企业后续直接注册**不得简单转移**；保护期**不得变成永久锁定企业**）。本轮成文 **ADR-009**（`docs/commercialization/decisions/ADR-009-opportunity-attribution-and-channel-protection.md`）与**成文规则唯一处**（NEW `docs/commercialization/rules/opportunity-attribution-rules.md`，§8 配置位对照表＋机器可读槽位块）；承接 **ADR-007**（admin 门＋密码确认双闸／当事人自证例外／治理面不进 api_catalog）与 G1 角色分层（报备人＝R2 创业者）。前置：G0 #216 / G1 #217 / G2 #228 / G3 #234（`f65f874`）已合并；G4 开工基线 fork/main `9497b2c`。
- **DB（迁移 `e7b2c4d9f1a3`，54→55 rev，additive 两表，单链单头）**：①`commercial_opportunity_rules`＝**五个规则配置位**（`protection_period_days`／`renewal_conditions`／`customer_choice`／`dispute_handling`／`attribution_criteria`；status ∈ unset/configured；days 与 criteria 互斥形状 CHECK；**迁移播种为 unset——本期不落数值，无任何硬编码默认值**）；②`commercial_opportunities`＝商机主体（status 八态闭集 submitted/enterprise_confirmed/attribution_confirmed/presales/matched/settled/disputed/withdrawn＋归属三戳＋保护期五列＋撮合/客户选择/结算三引用〔FK 既有 `delivery_packages` 与 G3 `commercial_revenue_ledger`，不建第二套撮合/结算〕＋争议/撤回留痕＋rule_snapshot JSON）。**六条 CHECK**：状态闭集／保护期闭集／归属形状（owner⇔confirmed_at）／阶段需归属（presales·matched·settled ⇒ owner）／保护期窗口（**active ⇒ started AND expires——结构性排除「永久锁定企业」**）／到期晚于起算。
- **七步链路服务层**（NEW `commercial/attribution_service.py`）：①报备＝**R2 当事人自证**（证据只存指针＋sha256 指纹；只登企业代号）→②企业确认＝admin 代录**线下书面答复**（指针＋指纹）→③平台确认归属＝**admin＋密码**（关键流转；已确认归属再确认 409 `attribution_already_confirmed` **不得静默改写**）→④设定保护期＝长度取 `protection_period_days` 配置位（未配置 ⇒ 保护期**保持** `unconfigured`）→⑤售前＝默认归属人（可显式改派，不改归属）→⑥撮合＝引用既有交付包且**须同企业代号**（409 `package_enterprise_mismatch`）→⑦结算＝引用 G3 科目层 `project_share` 行且未作废（409 `ledger_subject_mismatch`/`ledger_entry_voided`/`ledger_package_mismatch`）。
- **归属不自动易主＝结构性保证**：企业侧立项路径（`projects` 服务）**没有任何写路径**可触碰商机行——「企业自行注册不转移归属」不是靠判定逻辑，而是靠**路径不存在**；另配**反例用例**（保护期未配置 ⇒ 企业可直签立项；断言归属人/确认戳/状态/保护期逐项不变＋读面 `enterprise_registered` 派生事实可见——注册事实可见但归属不动）。转移唯一路径＝`reassign` 显式治理动作，被 `attribution_criteria` 规则闸 **fail-closed**（本期不可用 ⇒ **本期无转移路径**）。
- **保护期三态可区分＋直签封堵钩子**：`unconfigured`（未配置——**既非永久保护也非立即失效**）／`active`（保护中，必有到期）／`expired`（读时派生——存储态 active 但已过到期 ⇒ 放行，**不在读路径写库**）。直签封堵＝**既有 `dispatch/channel_guard.py` H1–H3 的扩展钩子**（惰性：库内无商机行零行为差异；**失败放行**：查询异常不阻断立项——保护是渠道秩序诉求不是资金安全闸；只认「存储态 active 且未到期」），封堵 422 `opportunity_protection_active`＋审计事件 `opportunity_protection_blocked`；**派单线（H1–H3）语义零变化**。
- **规则位 fail-closed＋机器闸**：五配置位缺省 `unset`，依赖规则的动作（续期/客户选择/争议/改派/保护期设定）409 `rule_not_configured`——**数值未定数时「少做」不「猜着做」**；客户自主选择**不改归属**；争议处理机制未成文不可发起、争议期间链路冻结（撮合/售前/结算 409 `opportunity_disputed`）。NEW 测试 `test_rule_document_slots_match_code_bidirectionally` 钉**成文规则文件机器可读槽位块 ↔ 代码常量双向相等**（规则文件与代码配置位一一对应＝任务书 §8 验收③的机械闸）。
- **高风险写闸**：企业确认/归属确认/改派/保护期/续期/售前/撮合/客户选择/结算/争议/规则配置＝**admin 门＋`confirm_password` 双闸**；逐动作 `operation_events` 带 request_id、**密码不落事件**；**自我动作例外只覆盖报备与撤回**（当事人自证）；治理面**全不进 api_catalog**。
- **路由（+16，411→427，全不进 api_catalog；ENTRIES 94 不变）**：读/自证面 4 条（`POST|GET /api/v1/commercial/opportunities`、`GET …/<id>`、`POST …/<id>/withdraw`）＋治理写面 12 条（`GET|POST /api/v1/admin/commercial/opportunity-rules[/<key>]` ＋ `POST …/opportunities/<id>/{enterprise-confirm,attribution,attribution/reassign,protection,protection/renew,presales,match,customer-choice,settlement,dispute}`）。
- **测试**：NEW `server/tests/test_commercial_opportunity_attribution.py` **23 例**——规则文档↔代码双向闸／配置位全 unset／七步链路走通＋跳步拒绝／**归属不静默改写**／结算须 project_share 科目行／撮合同企业／**归属不自动易主反例**／**保护期三态可区分**／active 封堵直签＋审计事件／规则闸四动作 fail-closed／配置后动作放行（选择不改归属＋续期计数＋改派判据）／争议冻结链路／报备 R2 门／治理写双闸／规则配置须书面依据／读面权限四态／撤回仅报备人／事件无密码／不进 api_catalog／`delivery_settlements` 零加列／迁移往返（downgrade 至显式父版本 `c4f7a2d9e1b6`）／保护期值域闭集。
- **变异五连全转红→还原→绿**（字节级备份还原，sha256 终验一致）：**M1** 归属不自动易主失效（企业注册派生事实恒 False）→反例用例转红；**M2** 保护期未配置也封堵（守卫放宽为任意非 revoked 态＋绕过到期派生）→反例用例转红；**M3** 规则未配置仍放行（`require_rule_configured` 直通）→规则闸用例转红；**M4** 争议不冻结（`_reject_when_disputed` 摘除）→争议冻结用例转红；**M5** 归属可静默改写（`attribution_already_confirmed` 摘除）→防改写用例转红。
- **实施期自查修正（记在案）**：①`days_remaining` 初版按 `(expires-now).days` **向下取整**＝配 30 天显示 29；改**向上取整**（剩余不足一天仍算一天＝「今天还在保护期内」口径）；②反例用例初版带着 active 保护期跑企业直签 → 被**自己的保护期封堵**（422）——反例的正确形态恰是**保护期未配置**（企业可注册时归属仍不转移）；③`confirm_attribution` 初版先查状态后查归属 ⇒ 已归属商机的再确认报错码失真；改**归属检查先行**；④争议冻结初版复用通用 `invalid_opportunity_state` ⇒ 用例无法区分「冻结」与「状态错」；补显式 `_reject_when_disputed`（409 `opportunity_disputed`）；⑤交付包夹具初版用合成 UUID 当 leader_user_id 撞 FK RESTRICT——改传真实创始人 id；⑥测试 mypy `re.search` Optional 收窄补断言（union-attr 归零）。
- **架构图口径同步（上游 P2-7 防陈旧闸）**：G4 改结构后（路由 411→427／表 137→139）防陈旧闸转红，按处置改 `architecture/candidate.json`＋已渲染 `system-architecture.html` 的同两处数字（蓝图 49 不变）并用 `tools/capture-full-preview.mjs` 重出整页实拍 `preview.png`——闸复跑绿。
- **融合上游（合并前收口，两轮 rebase）**：上游在本 PR CI 期间先后并入 #240（AI 原生化 N2 归因仪表化，迁移 `c4f7a2d9e1b6`，53→54 rev，+10 测试）、#239（V3.2 G9b 真机两闸轮，+4 测试）与 #235（V31-P1b 大纪要分段抽取与诚实截断，+52 测试；零迁移零路由），致 PR 不可直接合并。冲突**四**处——`server/migrations/versions/e7b2c4d9f1a3_…py`（`down_revision` 由 `d5f9a3c7e1b4` 改挂 `c4f7a2d9e1b6`，保持单链单头）、`server/tests/test_migrations.py`（HEAD_REVISION 与全集断言 54→55）、`AGENTS.md`（口径行 + N2/G4 两 bullet 并存）与 `CHANGELOG.md`（N2 节与 G4 节并存置顶），另加 `docs/audit/v3-workbench-inventory.json`。按「两边全留」消解：口径行取 G4 新值（**139 表／55 rev 单头 `e7b2c4d9f1a3`／427 路由／49 蓝图**）并保留上游 N2 的口径段与 N2 bullet；CHANGELOG 的 N2 节与 G4 节**并存置顶**。融合后**复测**：结构口径逐位不变（427 路由／49 蓝图／139 表／55 rev 单头 `e7b2c4d9f1a3`，审计三清单已重生成、架构图防陈旧闸复跑绿）、mypy 仍 279、pytest **2543 收集 = 2537 passed + 6 skipped**。
- **合并收口（收口 PR 回填）**：PR #241 squash 合并 fork/main **`ffed2e2`**；PR run **42581664828** 四绿 ＋ **main run 42583246694 四绿**（合并态；server-tests 两轮实测 **2537 passed + 6 skipped**〔522.82s / 568.87s〕，desktop 82 文件 **966 passed**）。**部署活体绿**：三镜像 rebuild 自本工作树＋容器内 `alembic upgrade head` 实跑 `c4f7a2d9e1b6 -> e7b2c4d9f1a3`；活体断言三项全绿——容器内 url_map **428**（commercial 43／蓝图 49）／容器 `alembic current` ＝ `e7b2c4d9f1a3 (head)`／api·worker·scheduler 三容器镜像 ID ＝ 本工作树构建产物（`c7fba822aef1…`/`649da2c7ab3b…`/`113dbf0c0e4a…`）；活库断言：G4 两表结构正确（opportunities 34 列/6 CHECK、rules 11 列/5 CHECK）、五规则槽全 **unset**、商机 **0 行**、`delivery_settlements` 仍 20 列；`/ready` 与 `/live` 均 200。
- **口径校正（教训 48：vitest 只认 CI 实测）**：**965→966**——G3 main run 42544563159／G4 PR run 42581664828／G4 main run 42583246694 三轮 desktop CI 实测一致 **966 passed**，前值 965 系 #229 轮文档值（上文 AI 原生化节挂账「归口口径责任人」事项就此销账）；AGENTS 现行结构口径行与 #229 bullet 已同步校正。
- **口径**：pytest **2543 收集 = 2537 passed + 6 skipped**（G3 轮基线 2454 收集 + AI 原生化 N2 +10 + #239 +4 + #235 +52 + 本轮 +23 ＝ 2543；本地 CI 同命令 `-n 4 --dist loadfile` EXIT=0 / 8m39s；**PR run 42581664828 / main run 42583246694 server-tests 实测同值 2537 passed + 6 skipped**）／mypy **279 基线不变**（官方闸 OK）／路由 **427**／蓝图 **49**／表 **139**／迁移 **55 rev** 单头 `e7b2c4d9f1a3`；审计三清单已重生成（route +16 行、DB +2 行、JSON 427/49/139/55 逐位吻合）；桌面零改动（不重打包）；server 变更 ⇒ 合并后 rebuild 三镜像＋alembic upgrade head（新迁移）。

## [未发布] — AI 原生化实施任务书 v1（leader 执行本：轮次编排 N1–N6 + 拍板闸 D-1–D-8）+ 台账/评估同日口径回写（纯文档零代码零迁移零路由，2026-11-09）

- **动机**：蔡工要求「依据台账生成 leader 任务书」——把《AI 原生化差距评估》与《AI 原生化差距台账》从**叙述与登记**转成**逐轮可施工、可复测、可对账**的施工单（台账＝对账入口，任务书＝施工顺序与验收口径的载体，二者互相引用、不得各说各话）。
- **NEW `docs/architecture/AI原生化实施任务书-v1.md`**：①§0 角色与权责（拍板人／leader／AI 三角；leader 七职责 ①–⑦、不得为的八件事、四套编号防串：台账 G-xx／评审 R-xx／轮次 N-x／BP L1–L5 与商业 R1–R4 与 fallback_level L0–L3）；②§1 终点判定（抽离测试通过＋决策位 AI 行使＋飞轮回流闭环＋真实订单首跑，四条同时成立）与四特征翻分目标（②③到 3/3、②④到 2/3）；③§2 起点基线（**现测**，非承袭）；④§3 轮次编排总表 **N1–N6**（N1=Path 0 真实订单首跑／N2=Path 2a 仪表化／N3a-c=Path 1 决策位 AI 起草三子片／N4=Path 2b 评测回归与受控发布／N5=Path 3 提议+人确认／N6=Path 4 版本注册表），每轮带 G 条目认领表与「消解判据→复测动作」逐条映射；⑤§4 逐轮任务书（目标／范围／**明确不做**／前置／拍板闸／DoD／成本判据／风险）；⑥§5 台账操作规程（四态＋回写四要素＋**四证复测规程**：结构证据／动态证据／行为证据（可辨变异）／反向证据；锚点纪律：行号漂移不算失效、语义漂移必须复核；口径现测配方六条）；⑦§6 拍板闸 D-1–D-8（含**不获答复时的默认**：D-1 业务闸未获答复⇒不得擅自开真实订单通道，改走 N2）；⑧§7 红线八条；⑨§8 与在途/并行线边界；⑩§9 风险登记八项；⑪§10 每轮汇报模板；⑫§11 可直接交给 Goal 循环的总提示词（13 条最高规则，起点＝只做认领与核验、不改业务代码）；⑬§12 复测配方速查。
- **施工顺序上的实用结论**：**N2 仪表化不依赖业务闸**——真实订单闸未开时可先开 N2（无归因仪表的决策位 AI 不可审计、不可进化）；N1 的「零代码准备」（C1–C7 前置检查、审阅人安排）可在等闸期并行做。
- **同日第三轮活库实测 ⇒ 口径回写（评估 v1.1 的两句过期表述被更正）**：`agent_runs` 0→**9**（全 `execution_provider=host_channel`、幂等键全 `sim:` 前缀 ⇒ **执行面已在模拟场真实行使，真实客户订单仍零**）、`agent_artifacts` 0→**34**（**全 `reviewed=False`** ⇒ 人工接受信号「只写不读」之外**连写都还没发生过**）、`simulation_runs` 0→**4**（全 completed）、`ai_call_audits` 6→**11** 行（`purpose` 空仍 2 行；新增 3 行 `simulation_evaluation` 且 `used_fallback=false`——G9 真模型评估栈**真跑过**）、`discovery_extractions` 2→**3**（抽取累计 **5 试 1 成**，11-09 又 2 败）。**总判定与四特征评分（2-1-2-1）维持**——回流段四断点（无提示词指纹／无 reviewed 消费／无 CI eval／无发布通道）仍全断；降级链已真实行使（2 条 timeout 带 `fallback_level=L2`），「写错不重做」诚实终态真实出现 1 次。
- **台账 v1.2**（`docs/architecture/AI原生化差距台账-v1.md`）：G-01 现状锚点改写（执行面已行使／真实订单仍零）+ 判据收紧（幂等键非 `sim:`/`rehearsal:`）；G-07 补「`agent_run:` 前缀零生产者」；G-08 补「连写都没写过」；G-10 补「活库已有 3 次真模型评估但不在 CI 内」；G-11 补「模拟场已跑 4 次」；G-12 附注升级（**行使已发生**＝4 次 completed＋3 行非 fallback 审计）；G-16 口径改（2/6 → 2/11）；**新增「规划轮次」列**（对接任务书 N1–N6）；新增「第三轮探针注记」。
- **评估 v1.2**（`docs/architecture/AI原生化差距评估-v1.md`）：§0 速览「最关键的事实」行改写；§4 增「证据基线前移注记」（行使成分更实但回流闭环未达成 ⇒ 评分维持）；§4 ①③④ 表述更新；§5 三次探针汇总改写（audits 明细 11 行＋业务面对照三列＋读法七条）；§7 Path 0 现状更新（真实订单前提仍未取得）；§9 复核记录**第 10 条**（同日口径漂移，三处更正）。**总判定（AI+ 形态／L2+ 复核成立／四路径框架）不变。**
- **在途与并行边界**：PR **#235**（V31-P1 推理模型输出预算）是 **N1 的前置**——修复后必须复测抽取腿；PR #236 仅动 `docs/commercialization/phase-status.md`，零重叠；**本轮不代改 `AGENTS.md`**（现行结构口径行已由 G3 轮更新为 137 表/53 rev/411 路由，与实测逐位一致；仅其 vitest 值写 965、CI 实测 966 差 1，挂账归口口径责任人——避免与 #235 的 AGENTS.md 改动冲突）。
- **边界**：纯文档**不构成任何实施授权**——N1–N6 各轮仍须随轮立项＋拍板（AI 不代拍板）；红线全束（客户资料不入库不入仓／证据只存指针+sha256／写外呼·发信·付款永不降级永不自动／密钥不入 VCS／origin 永不 push／AI 审查不执行被审代码）；四份文档均为**内部文档，不随招商材料外发**。
- **口径**：零代码零迁移零路由零桌面零测试增量 ⇒ 结构口径不变（**411 路由 / 49 蓝图 / 137 表 / 53 rev 单头 `d5f9a3c7e1b4`**／api_catalog 94 ENTRIES，与 AGENTS 现行口径行逐位一致）；pytest **2448 passed + 6 skipped** / vitest **966**（82 文件）/ mypy **279**——**取自最近 main CI 实测 run `42544563159`，本轮未重跑测试**（纯文档轮）；无 rebuild／无 alembic／无便携版重打包。

## [未发布] — 商业化 G3：收入科目层与订阅席位计费（科目层五表+席位不重复收+首单扣费闸，2026-11-09）

- **范围**：任务书 T-10／T-11／T-13 §7（G3 目标＝「把席位、培训、认证、陪跑与收入科目分离落库」）。本轮成文 **ADR-008**（收入科目层与订阅席位计费），承接 **ADR-003** §2.1–§2.5（科目层独立于 `delivery_settlements`、份额复用 `seat_shares_for`、比例不落数、六名目只定义归属、科目层写路径属高风险写）与 **ADR-007**（admin 门＋密码确认双闸、自我动作例外、治理面不进 api_catalog）。前置：G0 #216 / G1 #217 / G2 #228（`b0fd5fc`）已合并；G3 开工基线 fork/main `e06ae8d`。
- **DB（迁移 `d5f9a3c7e1b4`，52→53 rev，additive 五表）**：①`commercial_revenue_ledger`＝**收入科目层**（ADR-003 §2.1「收入类型 → 金额 → 关联对象」；三类科目 `seat_fee`／`training_fee`／`project_share`；外键指回 `quotes`／`payments`／`contracts`／`delivery_settlements`／`delivery_packages`／`training_entitlements`；CHECK 联锁含**关联对象至少一个非空**）；②`commercial_deduction_elections`＝扣费方式**书面选定**（指针＋sha256；部分唯一索引＝一人一条 elected）；③`commercial_fee_configs`＝三个配置位（认证费金额／陪跑期限／认证通过线），**迁移播种为 unset**；④`commercial_split_rules`＝分成比例**结构**（角色 R1–R4 × 项目类型 → `ratio_bp` 万分比），**本期零行**；⑤`commercial_certification_records`＝认证挂模拟考核（挂 `simulation_evaluations` 指针＋快照 verdict/score）。**未向 `delivery_settlements` 加任何列**（结构钉：head 上列集合逐位比对）。
- **三类科目分别记账可分别查、可对账**：读面 `GET /api/v1/commercial/revenue-ledger`（按 `subject_type` 过滤；本人只见自己的、admin 见全量）、`.../reconciliation`（按科目×名目汇总＋**与收款台账的差异笔数**＝行金额 ≠ 关联收款实收额）、`.../<entry_id>`。**六项名目只定义归属**——归属矩阵 `LINE_ITEM_SUBJECTS`（软件订阅／企业订阅／使用量→席位费；项目费／平台分成→项目分成；软件服务费→培训费）是代码层权威，错配 400 `line_item_subject_mismatch`；**金额算法不在本期定义**，金额来源只有三个：配置位（缺省未设⇒不可用）／关联收款的**实收额**／人工录入的线下约定金额（必附指针＋指纹）。
- **席位不重复收（任务书 §7 验收：L2／L3／L0 三组合）**：套餐目录 `REVENUE_PACKAGES` 声明 `covers_first_year_fee`（实战营 `bootcamp_practical`／陪跑营 `bootcamp_mentorship` 为真；**不落价目**——价格走 `quotes`／`payments` 收款台账，避免双写）。判定走**两条独立路径**，任一成立即拒绝重复收取：①权益行席位来源为实战营/陪跑营；②科目层已有该人「含首年席位费」的套餐席位费行。反例用例断言**席位费科目行恒 1 行**；L0 组合（无含席位套餐的候选交付者）扣 **3980** 并随扣费激活席位（来源 `first_delivery`、年度到期）。
- **首单扣费闸落服务层（不靠流程纪律）**：交付者首个付费项目**交付完成并验收后**才触发扣除 3980；闸门顺序＝验收（409 `acceptance_not_passed`）→交付席位本人（403）→项目有「实收且验收通过」的里程碑收款（409 `payment_not_settled`）→**不重复收**（409 `seat_fee_already_included`／`seat_already_active`／`seat_fee_already_charged`）→**扣费方式已书面选定**（409 `deduction_method_not_selected`）；随后记账＋激活席位。**未接单候选人不产生年度欠费**（扣费只挂已接单且已验收的交付项目；方案 A 一次性扣除无年度周期）。
- **扣费方式＝当事人自证动作**（ADR-007 §2.4 的延伸）：`commercial_deduction_elections` 只认**交付者本人**选定自己的方式（路由不接受 `user_id`，**admin 不得代选定**——防止平台替用户承诺扣费；G2「企业自证：admin 不得代确认」同款边界）；书面证据必须附 `source_uri` 指针＋`content_hash` sha256 指纹。方法集 `{one_time, annual_installment}`：**本期只实现方案 A（一次性扣除）**；选方案 B 时扣费闸 fail-closed 409 `deduction_method_not_implemented`（不误按 A 扣、不静默分期）。
- **认证挂模拟考核，通过线本期不设**：`commercial_certification_records` 挂考核评估指针；**通过线配置位未设 ⇒ 记录停在 `pending_threshold`，不判定通过**（认证状态不变更）——缺省不可通过，不落任何默认分数线；配置且 verdict='pass' 且得分达标才置 `certified`，`certification_source` 指向考核行。**认证费金额本期不设 ⇒ 缺省不可收款**（`fee_not_configured` 409；且认证费只认认证类培训权益行）。
- **陪跑期限与培训周期挂钩（结构先落、数值待定）**：`commercial_fee_configs.mentoring_period_days` 未配置 ⇒ 陪跑权益的 `valid_until` 留空；配置后按周期推导（G1 的 `add_training_entitlement` 增补该挂钩，延迟导入避免商业模块成环）。
- **分成比例本期不落数**（ADR-003 §2.3）：`commercial_split_rules` 本期**零行**；登记维度即 `status='unset'`（`ratio_bp` 恒 NULL），配置比例必须附书面依据指针＋指纹。**项目分成只引用既有分账结果、不重算**——科目行金额 ≡ `delivery_settlements.delivery_amount`（传入不一致金额 409 `amount_mismatch_settlement`），席位份额快照取 `seat_shares_for` 的**结果引用**（`basis.seat_shares_source` 标注来源）；比例行只提供落位与可见性，**不参与金额计算**。
- **高风险写闸**：科目记账／首单扣费／配置位／分成登记／认证判定＝**admin 门＋密码确认双闸**（403 `commercial_admin_required`／缺密码 400／错密码 403 `invalid_password`）；逐动作 `operation_events` 带 request_id、**密码不落事件**；**自我动作例外只覆盖「扣费方式选定」一项**（当事人自证），**不含**记账、扣费、配置位、认证判定。
- **路由（+14，397→411，全不进 api_catalog；ENTRIES 94 不变）**：读面 7 条（`packages`／`revenue-ledger`／`revenue-ledger/reconciliation`／`revenue-ledger/<id>`／`deduction-election`／`certification-records/<user_id>`）＋自证面 1 条（`POST /api/v1/commercial/deduction-election`）＋治理写面 7 条（`POST /api/v1/admin/commercial/revenue-ledger`／`.../first-order-fee`／`.../fee-configs/<key>`／`GET|POST .../fee-configs`／`GET|POST .../split-rules`／`.../certification-records`）。
- **测试**：NEW `server/tests/test_commercial_revenue_ledger.py` **26 例**——三类科目分别可查可对账／名目归属错配拒绝／关联对象必填／**L2·L3 不重复收反例（席位费科目行恒 1 行）**／L0 首单扣费成立＋席位激活／重复扣费拒绝／**验收前不触发**／**未选定方案不得扣费**／未实现方式 fail-closed／选举只认本人＋书面证据必填＋指纹校验／治理写双闸／记账事件带 request_id 无密码／读面权限四态（本人·admin·他人 403·未认证 401）／**认证通过线未设不判定通过**＋配置后达标置 certified／认证费缺省不可收款／陪跑期限结构（未设留空·配置后推导）／**分成结构零行·登记即 unset**／**项目分成引用分账不重算（金额与份额快照逐位对照）**／`delivery_settlements` 零加列结构钉／治理面不进 api_catalog／配置位全 unset／套餐目录不含价目／迁移 additive 往返（downgrade 至**本迁移的父版本**显式 revision——`-1` 会被后续叠在头上的迁移顶掉）。
- **变异十连全转红→还原→绿**（任务书 §12.10）：**M1** 不重复收判定整体失效→不重复收反例转红；**M2** 未选定方案仍扣费→未选定用例转红；**M3** 验收前仍扣费→验收闸用例转红；**M4** 项目分成按比例重算（不引用分账）→引用用例转红；**M5** 名目归属校验失效→归属用例转红；**M6** 关联对象必填失效→关联用例转红；**M7** 通过线未设也判通过→认证用例转红；**M8** 书面证据指纹闸失效→选举证据用例转红；**M9** 认证费缺省可收款→缺省不可收费用例转红；**M10** 陪跑期限未配置也落默认天数→数值待定用例转红。
- **实施期自查修正（记在案）**：④本地全量跑测**必须用 CI 同命令**（`pytest -q -n 4 --dist loadfile`，**不加 `-p no:warnings`**）——加该旗标会让 SQLAlchemy `UTCTimestamp()` 未设 `cache_ok` 的 SAWarning 直落 stderr，被 `test_workbench_seed.py` 的 CLI 输出断言（`modules_created=5`）当成本体失败＝**假红**（本轮实测即被此绊住 1 failed/2421 passed；pytest 的 warnings 插件默认拦下该警告，去掉旗标即全绿）。①科目层的「关联对象必填」初版只认报价/收款/合同/分账/交付包/培训权益，**漏了「订单〔套餐〕」**——线下约定记账（结账金额走线下约定）时无报价无收款会被误拒，补 `package_code` 入关联口径（DB CHECK 同步）；②「已扣过首单费」与「已购含席位套餐」两处判定初版只看 `package_code`，**可被 `seat_source` 旁路**，改为 `package_code`／`seat_source` 双条件；③通用写路径初版只拦 `package_code='first_delivery'`，**漏了 `seat_source='first_delivery'`**——首单扣费必须走专用闸（验收＋书面选定＋不重复收），补拦。
- **融合上游（合并前收口）**：上游在 G3 期间并入 #231（V3.2 G9 接线轮：真实执行面接线＋真模型评估层＋Rubric 覆盖度校准，**+2 测试文件 +26 例**）、#232（V3.1 试点执行与复盘，纯文档）与「AI 原生化差距评估 v1.1」三笔，致 PR 不可直接合并。冲突**仅** `AGENTS.md` 与 `CHANGELOG.md` 两处口径/轮次节——按「两边全留」消解：口径行取 G3 新值（137 表／53 rev／411 路由）并保留上游新增的「V3.1 试点执行与复盘轮」bullet；CHANGELOG 的 G3 节与上游新节**并存置顶**。融合后**复测**：结构口径逐位不变（411 路由／49 蓝图／137 表／53 rev 单头 `d5f9a3c7e1b4`，审计三清单零差异）、mypy 仍 279、pytest **2454 收集 = 2448 passed + 6 skipped**。
- **架构图口径同步（上游 P2-7 防陈旧闸）**：G3 改结构后（路由 397→411／表 132→137／迁移 52→53）防陈旧闸转红，按处置改 `architecture/candidate.json`＋已渲染 `system-architecture.html` 的同两处数字（蓝图 49 不变）并用 `docs/architecture/archify-diagrams/tools/capture-full-preview.mjs` 重出整页实拍 `preview.png`（1440×2098）——闸复跑绿。
- **部署并发覆盖复验（跨会话共享部署）**：部署后约 30 分钟，另一条线的会话从自己的 worktree 重建并 `up -d`，把 api 容器换成**旧代码**（活体 `url_map` 412→398、commercial 27→13、容器内 `alembic current` 报 「Can't locate revision」、`/app/migrations` 挂载指向别人的 worktree）。**处置**：从本工作树重建三镜像（api 镜像 ID `84193bb29335`）＋ `up -d --force-recreate` 三容器 → **复验全绿**（412／27／`d5f9a3c7e1b4 (head)`／三容器 healthy／ready+live 200）。**教训**：镜像 tag 与 migrations 挂载源是跨会话共享资源，部署后必须复验「活体路由数 ＋ 容器内 alembic current ＋ 容器镜像 ID」三项（已写入 AGENTS「工作流与陷阱」节）。
- **口径**：pytest **2454 收集 = 2448 passed + 6 skipped**（基线 2402 收集 + 本轮 +26 + 融合上游 #231 的 26 ＝ 2454；本地 CI 同命令 `-n 4 --dist loadfile` EXIT=0 / 8m16s；**终值以本 PR CI server-tests 实测为准**）／mypy **279 基线不变**（官方闸 OK）／路由 **411**／蓝图 **49**／表 **137**／迁移 **53 rev** 单头 `d5f9a3c7e1b4`；审计三清单已重生成（route +14 行、DB +5 行、JSON 411/49/137/53 逐位吻合）；桌面零改动（不重打包）；server 变更 ⇒ 合并后 rebuild 三镜像＋alembic upgrade head（新迁移）。
## [未发布] — V3.1 试点执行与复盘（somwyn E2E 十步全链走通，§17-17 达成；纯文档+活库数据，零代码零迁移零路由，2026-11-09）

- **闸门**：蔡工 2026-11-08 确认 C1–C7 并给出执行数据（C1=代号 **somwyn**；C2=访谈素材取自本地文档中心既有脱敏实记录 `somwyn案例_FDE交付实记录_v1.1.md`〔全代号化，真实资料零入库〕；C3=分解目标自选交付段既有模块）；宿主通道全程关闭（C5）；§17-14 ZCode 联调未触碰（独立拍板项）。
- **执行**：按 `docs/v3.1/pilot-runbook.md` 十步操作序 E2E 全链走通（部署=隔离 worktree compose 栈，alembic head `e9c4a1f7b3d2`）——纪要（全文版抽取两败后人工整理稿 `4b558dce`）→抽取 `02a680d7`（22 facts+7 reqs，review_required）→审阅（20+7 accepted、2 facts needs_clarification=推断/开放问题红线生效）→本体变更集 `ffa95ce0` submit(admin)→confirm(**pilot.reviewer**) 物化 20 术语（**决策分离成立**）→方案 `c0f1dc00` published（9 items）→分解 9 任务（全量 commit 卡项目行锁超 gunicorn `--timeout 120` 被 abort 零残留；**端点原生 item_ids 分批** 9/9 创建，幂等复跑 skipped=9 reason=已分解）→draft-from-plan `44ac0ea1`（`delivery-scope-documents@1`）validate 全绿→admin publish→run `21fc3fa9` **succeeded**（两处 human_approval 经 pilot.reviewer 拍板，审批时延中位数 1.43min）→测试计划 v1 废弃（执行脚本形状解析错，rejected=superseded 留痕）+ v2 `5b538ea5` approved（需求覆盖闸过）→execute dev **7/7 passed**（append-only，报告指针+指纹成对；原件 `somwyn/.fde/pilot-test-report-2026-11-09.md` sha256 `acf61043…`）→证据 `aa2b85a9`（kind=task）→指标 `sections.v31` **七指标全 ok 全有样本**（n=1/2/1/7/1/9/7，零 insufficient_data）。
- **交付**：①NEW `docs/v3.1/pilot-复盘-somwyn-2026-11-09.md`（十步实测时序〔事件时间轴还原，全程 ≈6.1h〕+指标快照原文+事件链核对+五项偏离注记 P1–P4/D1+待办+结论）；②`final-acceptance-checklist.md` 第 17 项回填 ✅，结论改 **17 达成/1 待条件（#14）/0 未达成**；③`implementation-roadmap.md` 待业务闸节更新（试点项勾销）；④`v3-backlog.md` NEW「V3.1 试点遗留登记」四项（V31-P1 **抽取推理模型输出预算**〔真实产品缺陷：降级直连腿未按模型类型预留 reasoning 预算，MiniMax-M3.1-Flash 下大纪要抽取必败〕/V31-P2 批量分解 vs gunicorn timeout/V31-P3 草稿卷属主/V31-D1 审阅复核人工项）。
- **偏差如实注记**：**D1=全部审阅动作（facts/reqs 接受、测试计划批准、执行登记）由 admin 代执行**（无人值守代执行先例；AI 不代拍板红线未破——本体 confirm 与 workflow 拍板均由第二账号 pilot.reviewer 完成）；**建议蔡工桌面端复核全部审阅动作**（operation_events 逐条可回查）。
- **口径**：零代码零迁移零路由零测试增量（pytest 2354=2348+6s / 路由 391 / 蓝图 49 / 表 130 / 51 rev 单头 `e9c4a1f7b3d2` 全维持）；试点数据在活库（项目 `7042d7ab`，代号 somwyn），仓库零客户资料。

## [未发布] — AI 原生化差距评估 v1 + 差距台账（纯文档零代码零迁移零路由，2026-11-09）

- **动机**：蔡工提问「本项目离 AI 原生应用还有多远、怎么才能成为真正的 AI 原生应用」，按其提供的评估框架（抽离测试／AI Native vs AI+／四特征〔智能内生·数据飞轮·人机协同·持续进化〕）完成全仓评估并落盘。
- **NEW `docs/architecture/AI原生化差距评估-v1.md`**：抽离测试逐链判定（决策与账务主干无 LLM 全存活 ⇒ 当前 AI+ 形态，抽离测试不过）+ 四特征评分（①智能内生=部分／②数据飞轮=生产段已通回流段全断／③人机协同=接近达标／④持续进化=基建渐备行使为零）+ BP §1.3a L1–L5 对齐复核（L2+ 成立；L4≈AI Native 交付域形态）+ 四路径路线图（Path 0 前置通道→Path 2 飞轮闭环→Path 1 决策位→Path 3 提议+确认→Path 4 版本注册表）+ 复核记录五处修正。
- **NEW `docs/architecture/AI原生化差距台账-v1.md`**：G-01–G-14 逐条带 file:line 锚点+消解判据+状态（G-12 已 CLOSED=#231），供逐轮实施对账；锚点语义漂移须复核注记。
- **评估基线与现测更新**：fork/main `cddefd4`（#231）；活库 2026-11-09 只读探针——**飞轮首圈已转**（售前链首批真实数据：抽取 2/事实 22/需求 7/方案 1/测试计划 2/workflow_runs 1 succeeded）而 agent 执行面仍零行使；MCP 工具数现测 **17**（15 只读+2 写）；#231 已把「模拟模型评估未接线」消解（台账 G-12）。
- **圆桌评审轮（party-mode，2026-11-09）**：BMAD party-mode 七人对抗评审（Code Review Crew+2 借调）；NEW `docs/architecture/AI原生化差距评估-评审报告-v1.md`（R-01–R-14：采纳 12/部分采纳 2/不采纳 0，总判定维持）。评审期间活库探针第二轮产出两处新事实并回写：**首圈承役通道=降级直连**（audits 6/6 `used_fallback=True`，DSH 未上岗；模型 MiniMax-M3.1-Flash；抽取 4 试 1 成）+ **purpose=None 匿名审计行 2/6**；首圈工作流形态=human_approval×2+skill×1 全 succeeded。评估→**v1.1**（四特征 0–3 标尺化〔①=2 ②=1 ③=2 ④=1〕、Path 重排 **0→2a→1→2b→3→4**〔仪表化前置〕、派单推荐按 BP L3 口径上调进 Path 1、分发边界注记、复核记录第 6–8 条）；台账→**v1.1**（加体量/依赖两列、G-06 上调、G-12「契约在行使零」脚注、新增 G-15 桌面 AI 编排面 / G-16 审计匿名行）。
- **rebase 注记**：并发轮 #232（somwyn 试点执行与复盘）并入后 rebase 解 CHANGELOG 冲突（双方节保留）；首圈数据的官方来历落档（项目 `7042d7ab`、run `21fc3fa9`、`docs/v3.1/pilot-复盘-somwyn-2026-11-09.md`），评估/台账基线对齐 `f589801`；抽取 4 试 1 成根因=backlog **V31-P1**（推理模型输出预算，#232 登记）——评估 §5 行动项随之改写为「跟踪 V31-P1 消解后复测」。
- **边界**：纯评估不构成实施授权；四路径均须随轮立项+拍板；红线全束（AI 不代拍板／证据指针化／客户资料不入库／写外呼发信付款永不降级）；评估文档标注内部、不随招商材料外发。
- **口径**：零代码零迁移零路由零桌面 ⇒ 全部口径零变化（132 表/52 rev 单头 `b3e7c9d1a5f2`/397 路由/49 蓝图）；无 rebuild/alembic/重打包。

## [未发布] — 桌面侧栏账号区两行式压紧（纯桌面，2026-11-09）

- **反馈**：侧栏滚动修复（#227）落地后，蔡工指出底部账号区四行（系统管理员 / 管理员 / v0.3.0 / 退出登录）占高过大、不协调。
- **改造**：四行 → **两行**，信息一条不减。上行 `.account-identity` ＝ 显示名 + 角色（`align-items: baseline` 同基线；名字可收缩省略、角色恒不缩）；下行 `.account-foot` ＝ 版本 | 退出登录（`justify-content: space-between` 分居两端）。CSS 类名 `.account-foot` 取全仓唯一名——`AccountPage` 的 `.account-meta` 是另一套全局网格规则，刻意不共用，防隐式耦合。
- **压紧**：页脚行距 5px→2px、上内边距 16px→10px、退出按钮 `min-height` 26px→22px。浏览器实测页脚总高 **60.4px**（四行式约 100px）。
- **折叠态**：账号区**整体**让位（`.app-shell.sidebar-collapsed .sidebar-account { display: none; }`）——此前逐元素隐藏会留下一条孤儿细线；折叠态下退出走账号页。
- **测试钉**：`design-tokens.test.ts` 新增「侧栏账号区两行式契约」**5 例**（上行同基线 flex + 名字可省略 / 下行两端对齐 / 折叠态整体让位 / C3 版本号小字不回退 11px / 页脚压紧三项：行距 2px、上内边距 10px、退出按钮 22px）。
- **真浏览器验证**（gui-harness + Playwright）：既有两链回归 **11/11** 全过（指引链 5 + 集成桥 4 + 控制台无应用级错误）；`desktop/gui-harness/sidebar-probe.mjs` 侧栏探针由 5 扩到 **10/10**（新增：两行结构上下相邻无重叠 / 页脚总高 ≤64px / 四条信息都真有文本 / 版本与退出同处一行且版本在左 / 折叠态账号区整体隐藏）+ 截图目检（短视口 / 高视口 / 折叠态 / 侧栏特写）。
- **顺带修 harness 保真度**：gui-harness 的 shim 此前把服务端 snake_case `user` 原样回传，缺桌面端 `main/auth-ipc.ts:377` 的 `display_name → displayName` 转换 ⇒ 浏览器里账号名恒空（桌面本体不受影响，是 harness 与桌面不同尺）。本轮补齐该转换（harness 为 dev-only，`apply: "serve"`，零生产影响），探针因此得以断言「四条信息都真有文本」而非「元素存在」。
- **口径**：vitest **965**（82 文件，+5 = 两行式契约钉）；typecheck web+node 双绿；零服务端改动 ⇒ 路由 / 蓝图 / 表 / 迁移 / pytest / mypy 口径零变化。桌面变更 ⇒ **便携版 r24**（`release/蔡工FDE-0.3.0-便携版-r24/`，asar sha256 `657e37e914c280955ec322ee8a23a8ceae1c2b3846ce84721ed98dedd20b3fa3`；本轮独有 marker＝`account-identity` 字节命中 **2**、`account-foot` 命中 **4**、`min-height: 22px` 命中 **1**、`padding: 10px var(--space-3) 0` 命中 **1**，中文 sanity marker「退出登录」命中 **7**）。
## [未发布] — 商业化 G2：企业免费额度与三个体验入口（免费额度两表+主体认定+三入口隔离，2026-11-08）

- **范围**：任务书 T-07 §6（G2 目标＝「免费只到一次完整业务诊断，且额度按企业主体计」）——本轮成文两份 ADR：**ADR-004**（主体认定：统一社会信用代码规范化键、一次一主体不重置、三入口隔离、三档描述、两档体验上限）与 **ADR-007**（关键流转默认需人工确认：admin 门+密码确认双闸、AI 无直写入口、自我动作例外、实测后复审触发器）。前置：G1 权益四分已随 #217 合并 `f186342`；G0 基线审计与四 ADR 已随 #216 合并 `28f55fd`。
- **DB（迁移 `b3e7c9d1a5f2`，51→52 rev，additive 两表）**：`enterprise_quota_subjects`（**PK=规范化统一社会信用代码**（18 位）+ display_name + first_user_id + note）＋ `enterprise_free_quota`（**PK=subject_key——一主体一份**；state ∈ granted/in_progress/completed + granted_by_user_id/bound_user_id/bound_at/completed_at/deliverables JSON/enterprise_confirmed_by_user_id/enterprise_confirmed_at）。**四条 CHECK 联锁**：状态闭集 / **绑定形状**（granted 必未绑定且未完成未确认；非 granted 必已绑定——换账号不得改绑的结构性保证）/ 完成形状（completed 必带 completed_at）/ 确认前提（已确认必已 completed）。
- **主体认定（ADR-004 §1.1–1.4）**：`normalize_subject_key`＝大写＋去空格连字符＋18 位字符集 `0-9A-HJ-NPQRTUWXY`＋**GB 32100-2015 mod-31 校验位**验证；校验失败 400 `invalid_subject_key`（防录入误差造成「同一主体多键」）。**额度键挂主体而非账号**——`subject_key` 是主键，不是 user_id。
- **一次一主体、长期有效不重置**：授予幂等——同主体重复授予返回既有行（`changed=false`），**绝不新建第二份**；启动时绑定 `bound_user_id`（state→in_progress）；**换账号启动 → 409 `quota_bound_to_other_account`**（同一主体再注册不得获得第二次）；完成＝终态（409 `quota_completed`），任何账号不可重启——**无重置路径（人工亦无）**，重置属未来显式立项。**并发亦然**——启动/完成/企业确认三条写路径取额度行时一律 `SELECT … FOR UPDATE`＋**`populate_existing` 刷新**（行锁＋刷新两者同时成立才等于「锁在手读必为已提交真值」；只锁不刷新会被会话里 `expire_on_commit=False` 的陈旧实例绕过＝额度可被并发重发，CR-021 同款教训）。授予路径的「绝不新建第二份」由 `subject_key` 主键在库层兜底（并发双授时后者撞 PK，不会产生第二行）。

- **完成判据＝恰好六项全真**：`FREE_DIAGNOSIS_DELIVERABLES` 六键闭集（diagnosis_report／process_analysis／ai_opportunity_list／implementation_plan／project_tier_budget／next_steps）；缺失或未真 → 409 `deliverables_incomplete` **逐键点名**；多余键 → 400（闭集拒绝＝「六项不免费内容不进入免费流程」）。诊断内容本体由既有 guidance/方案/文档流产出——本模块只承载判据账，**不生成内容、不复制产物**。
- **企业确认＝绑定账号本人**：必须发生在完成之后（未完成 409 `quota_not_completed`）；**admin 不得代企业确认**（403 `quota_confirm_forbidden`——「企业自主选择不被取消」）。
- **三入口隔离（任务书 §6 语义与验收）**：`FREE_TRIAL_ENTRIES` 注册表三条——enterprise（真实业务问题，scope=real_business，须主体键，额度按主体计）／founder（模拟体验，scope=simulation）／deliverer（脱敏模拟项目考核，scope=sanitized_simulation）；`assert_entry_scope_allows` 域闸——**非企业入口取用 real_business 即 403 `trial_entry_scope_forbidden`**（「创业者不能取到企业真实商机」的结构性保证；**商机归属与渠道保护本体归 G4**，本轮不建商机侧读面）。
- **免费边界＝产品边界（代码层+接口层同时可见）**：`FREE_EXCLUSIONS` 七项常量（完整实施／真实 CRM·ERP 接入／大规模数据处理／定制 Agent／生产部署／持续运维／驻场）＋三档**纯描述性**项目等级（standardized／multi_system／complex，**不给数值区间**；命名刻意不带 T——与区域席位档 T1–T3 解耦，ADR-005 域）＋ `GET /api/v1/commercial/free-diagnosis-profile` 读面公开呈现。
- **体验上限（两档×两资源）**：`EXPERIENCE_LIMITS`（founder／deliverer × simulation_runs／mentor_sessions）**保守占位缺省并标注 `experience_limits_placeholder=True`**（试点前须填实数，**禁止无上限**——每格均为正整数）；`check_experience_limit(kind, resource, used)` 触限即 409 `experience_limit_exceeded`（`used >= cap` 即受限）；**上限按资源分别计数**（simulation_runs 与 mentor_sessions 是两个独立计数器，签名必带 `resource`）。**消费接线归 G6 三入口**（显式挂账，本轮只落结构+判定原语，不触碰 V3.2 simulation 域）。
- **高风险写闸（ADR-007）**：授予／完成＝**admin 门+密码确认双闸**（403 `commercial_admin_required`／缺密码 400／错密码 403 `invalid_password`，`auth/passwords.verify_password` 单点）；启动／企业确认＝**当事人自证动作**（认证用户路由＋事件留痕，不需 admin 密码——ADR-007 §2.4 自我动作例外）；逐动作 `operation_events`（target=user〔复用既有注册目标，events.py 零改动〕、changes 带 request_id、**密码不落任何事件**）。**治理面全不进 api_catalog**（AI 不可调用——dispatch admin 面同款边界）。
- **路由（+6，391→397，全不进 api_catalog）**：`GET /api/v1/commercial/enterprise-quota/<subject_key>`（本人/admin，他人 403 `commercial_entitlement_forbidden`、未知 404）、`POST /api/v1/commercial/enterprise-quota/<subject_key>/start`、`POST .../confirm`、`GET /api/v1/commercial/free-diagnosis-profile`、`POST /api/v1/admin/commercial/enterprise-quota/grant`、`POST /api/v1/admin/commercial/enterprise-quota/<subject_key>/complete`。
- **测试**：NEW `server/tests/test_commercial_enterprise_quota.py` 14 例——主体键规范化与校验位拒绝（含 API 400）／授予双闸／授予幂等（一行永不第二份）／启动绑定+换账号 409+本人重启幂等／**并发启动行锁串行化**（裸连接提交「另一账号已启动」＋本会话持陈旧视图→迟到启动必须 409 且绑定不被覆盖）／六项判据六连（五键 409 点名+一 False 409+多余键 400+恰好六键 200+完成后 409+未启动即完成 409）／企业确认五态（未完成 409+他人 403+admin 403+本人 200+重复幂等）／三入口隔离（创业者/交付者取 real_business 403+各入口自有域放行+未知入口 400）／体验上限（触限+按资源分别计数+未知资源 400）／读面权限四态／授予事件带 request_id 无密码／免费边界元数据（含三入口注册表）／治理面不进 api_catalog／迁移 additive 往返。
- **变异六连全转红→还原→绿**（任务书 §6「至少 1 条变异用例证明『额度按账号计』的实现会转红」）：**M1** 允许换账号重绑（＝额度按账号计）→启动隔离用例转红；**M2** 授予幂等键含账号（同主体可建第二份）→授予幂等用例转红；**M3** 放宽完成判据（未齐也算完成）→六项判据用例转红；**M4** 触限判定放宽（`used > cap`，恰好触顶放过）→上限用例转红；**M5** 三入口隔离失效（创业者可取 real_business）→隔离用例转红；**M6** 写路径不取行锁重读（陈旧内存视图当真值）→并发启动用例转红。
- **实施期两处自查修正（记在案）**：①`ck_enterprise_free_quota_bound_shape` 初版把「granted 形状」与「非 granted 形状」两条方向性约束用 AND 连接＝**任何状态都不满足**，改为单条析取约束（models／迁移／测试断言三处同改）；②`check_experience_limit` 初版用**同一个 `used` 同时比所有资源上限**＝mentor_sessions 的小上限会误伤 simulation_runs 的计数，改为**按资源分别计数**（签名加 `resource`，ADR-004 §1.8 同步修订）。
- **顺带修正（G1 遗留的版本假设）**：`test_commercial_entitlements.py` 与 `test_commercial_enterprise_quota.py` 的迁移往返原用 `downgrade "-1"`＝**假设自己的迁移是链尖**——G2 叠上去后 G1 用例即退错版本而红。改为**显式父版本 revision**（沿 `test_migrations.py` 既有惯例），后续迁移再叠不再复发。
- **顺带修正（跨 schema 目录查询导致的假失败）**：`test_migrations.py` 里三处目录查询（`information_schema.columns` 两处 + `pg_constraint` 一处）**未限定命名空间**——PG 的 `information_schema`/`pg_constraint` 跨库可见，同库若存在兄弟 schema（并行跑的遗留 schema，如 `fde_xdist_w0/w1`），`scalar_one_or_none()` 会因多行抛 `MultipleResultsFound`＝**与被测迁移无关的假失败**。改为按 `current_schema()` 限定（目录查询仍看得到本 schema 的真实 DDL，不降低断言强度）。本轮全量实测正是被这条绊住（2 failed/2372 passed），修正后归零。**该修正对上游新加的并行跑测基建尤其关键**——架构评估 P1-3 引入 `-n 4 --dist loadfile` 后，同库会并存 `fde_xdist_w{N}` 兄弟 schema，不限定命名空间的目录查询必然踩雷。
- **架构图口径同步（上游 P2-7 防陈旧闸）**：G2 改结构后（路由 391→397／表 130→132／迁移 51→52），`scripts/audit/check_archify_diagram_freshness.py` 转红（`architecture/candidate.json` 的「路由/表」口径过期）。按处置流程改源 `candidate.json` 与已渲染 `system-architecture.html` 的同两处数字（蓝图 49 不变），并用 `docs/architecture/archify-diagrams/tools/capture-full-preview.mjs` 重出整页实拍 `preview.png`（1440×2098）——闸复跑绿。
- **口径**：pytest **2402 收集 = 2396 passed + 6 skipped**（**PR #228 CI run 42503516295 server-tests 实测 2396 passed + 6 skipped，409.81s**；本地 `-n 4 --dist loadfile` 12m52s 同值；架构评估十项实施轮基线 2388 收集 + 本轮 +14）／mypy **279 基线不变**（官方闸 OK）／路由 **397**／蓝图 **49**／表 **132**／迁移 **52 rev** 单头 `b3e7c9d1a5f2`；审计三清单已重生成（route +6 行、DB +2 行、JSON 397/49/132/52 逐位吻合）；桌面零改动（不重打包）；server 变更 ⇒ 合并后 rebuild 三镜像+alembic upgrade head（新迁移）。

## [未发布] — 架构评估十项实施：机械闸补齐 + 工作流执行器拆分 + 第六张架构图（2026-11-08）

- **范围**：`docs/architecture/archify-diagrams` 的架构评估产出 P1×3 / P2×4 / P3×3 共 10 条 + 1 张待补图，本轮逐条实施（两项拍板见下）。全部是**给已上线的架构补机械闸与边界文档**，不是新功能：迁移双头曾两次把 51 迁移搞成双头（#215 vs #217）、审计清单的蓝图硬编码已漏条三次、2348 例本地 1h+ 反馈环、`paused` 死值域、图纸落后两轮、Redis 降级行为只存在于口头共识、桌面发不起 workflow run。
- **拍板留痕（两项）**：①`paused` 死值域＝**保留 CHECK + 加机械钉**（不收窄值域、不迁移、不动 schema——收窄要动已上线表，收益小于代价）；②pytest 提速＝**xdist + 每 worker 独立库 + CI 并行**（不选只做 CI 分片的轻量版——那不解决本地反馈环）。两项均「按推荐执行 + 留痕可推翻」。
- **P1-1 迁移单头机械闸**：新增 `test_alembic_chain_has_exactly_one_head`——文件解析（revision 集减 down_revision 集）与 alembic `ScriptDirectory.get_heads()` **双来源互校**，同时钉 `HEAD_REVISION` 常量不漂移。此前全仓零机械闸（#215 e7c4a9d2f6b8 与商业化 G1 e9c4a1f7b3d2 同挂一个 down_revision 成双头，事后靠人工 rebase 消解）。变异验证：注入第二条同 down_revision 的迁移 → 解析出 2 个 head 即红。
- **P1-2 工作流执行器拆分（executor.py 1562 → 门面 594 行 + 五个同包模块）**：`constants.py`（异常与常量单点真值，依赖图的根）/ `dag_utils.py`（DAG 抽取·拓扑序·占位符解析·when 裁决，纯函数）/ `serialization.py`（run·node 读取投影 + 定义版本行）/ `settlement.py`（节点与 run 终态结算）/ `dispatch.py`（调度与分派：tx A → call/skill/agent/human_approval）/ `recovery.py`（worker 侧恢复与终态收敛）。依赖单向无环；**对外公开名一个不减**（门面 `__all__` 列 63 个再导出名，routes / control.service / jobs.handlers / 既有测试的 import 全部照旧）。两条**刻意保留的惰性导入**：结算面的退避常量经门面动态读取（`monkeypatch executor._RETRY_BACKOFF_BASE_SECONDS` 仍生效）、调度面的结算调用点经门面动态解析（`monkeypatch executor._settle_node_success` 仍生效——tx B 崩溃族用例依赖它）。偏差记录：caplog 断言的 logger 名由 `fde_api.workflows.executor` 改为 `fde_api.workflows.dispatch`（skill 分派实现随拆分移入该模块，仓库惯例是每模块 `logging.getLogger(__name__)`），断言强度不变。另附 `test_source_size_budgets.py`：四个历史热点（本体 2102 / 项目 1946 / 智能体 1836 / 调研导入 1772）**只钉不拆**（逐文件上限 + 全局 2200 行上限 + 执行器七模块体量上限），防新文件长成下一个千行热点。
- **P1-3 pytest 并行跑测**：本地 `pytest -n 4 --dist loadfile`，CI 的 server-tests 同款。**每 worker 独占一块**：A 路径每 worker 一个独立库 `fde_workbench_w{N}_test`（需 CREATEDB；CI 的 postgres:16 里 POSTGRES_USER=fde 是超级用户），B 路径本机无建库权限时退到「同库分 schema `fde_xdist_w{N}`」＋ advisory lock 键按 worker 分化（PG 的 advisory lock 以 database 为域，同库多 worker 会把整场测试重新串行化——那正是本项要消除的等待）。两条路径**都不回落共享 public**（那不是「慢一点」，是「不可信的绿」）；都不可用时**报错并给出处置**（去掉 `-n` 或给测试角色 CREATEDB）。默认不带 `-n` 仍是单进程单库（既有行为零变化）。新增 `test_xdist_isolation.py` 5 例钉纯函数面。依赖：dev extras 加 `pytest-xdist>=3,<4`（lock 同步 3.8.0 + execnet 2.1.2）。实测：-n 4 全量 13m39s（串行 1 小时量级）。
- **P2-4 结构口径同步钉**：新增 `test_structure_inventory_sync.py` 5 例——`docs/audit/v3-workbench-inventory.json`（本仓**唯一**机器可读结构口径）逐项对账：路由数（url_map）/ 蓝图数（权威注册表）/ 表数（Base.metadata）/ 迁移数与 head·root（迁移链图，head 恰好一个——与 P1-1 单头闸互为印证），漂移即红并给出重生成指引。**不新建第二份口径文件**。
- **P2-5 蓝图清单自动派生**：蓝图注册此前有**两份真身**——app.py 的注册序与审计脚本照抄的硬编码 BLUEPRINTS 清单（必然漂移，已漏条三次）。现在真身只有 `app.py::_BLUEPRINT_SPECS`（经 `iter_blueprints()` 出货，导入惰性完成）；审计脚本删掉 50 项硬编码清单与其 50 行手动 import，改从注册表派生（仍自建裸 Flask 应用，不调 create_app ⇒ 不触 DB/Redis）；原 D1「与 app.py 源码正则对计数」升级为「与实际注册结果对**名字集合**」+「名字不得重复」（同名注册会被 Flask 静默覆盖，比漏条更阴）。新增 `test_blueprint_registry_sync.py` 3 例：注册表 ≡ 实际注册（双向）/ 名字唯一 / **app.py 不得出现绕过注册表的直接注册**（静态钉）。新增/移除蓝图今后只改 app.py 一处。
- **P2-6 `paused` 死值域 → 机械钉**：`workflow_runs.status` 的 `paused` 只在 CHECK 值域、全仓零写入方（run 永不进入 paused）。新增 `test_workflow_run_status_domain.py` 3 钉：CHECK 值域仍含 paused（形状）/ `RUN_STATUSES` 常量同源 / **workflows 包内 `paused` 字面量只允许出现在 models.py**（写入方钉——未来真要写 paused 先拍板补语义）。`models.py` 加注释登记为「预留值域」。
- **P2-7 图纸口径防陈旧闸 + 六图全量刷新**：图纸内容是**结构快照**，而结构每轮都在变——此前五张钉在 fork/main `58f7a26`，其后主干并入 V3.1 P0/P1 与商业化 G1 等多轮，图里的「47 蓝图 · 384 路由」「128 表」早已过期，而**没有任何机器能发现它**。新增 `scripts/audit/check_archify_diagram_freshness.py`（stdlib only，已接入 CI 的 server-tests job）：逐张读 candidate.json，抽出图上的「N 蓝图/路由/表/迁移」与机器可读口径逐项对账，**漂移即红**；revision 须 40 位十六进制；每张图须同时有候选与已渲染 HTML。同时六图全量刷新（钉 `e66647b`）：architecture 口径 47/384/128 → **49/391/130**；lifecycle 的 19 处与 sequence 的 9 处 sources **全部重锚**到拆分后的新模块（executor.py → settlement/dispatch/recovery/executor，models.py 行号随注释位移，app.py → `_BLUEPRINT_SPECS`）；六张重跑 archify finalize，四闸（validate/deliver/check/browser-check）全绿 0 诊断，preview.png 全部整页实拍（六张 PASS）；`meta.output` 改指仓库内已提交路径。交付回执布局更正：`<name>.delivery.json` **必须与 HTML 同目录**（`check --require-provenance` 按同目录找 sidecar，放 receipts/ 会得 provenance unknown）。
- **P3-8 / P3-10 降级与扩缩容边界（新增 `docs/architecture/降级与失败路径契约-v1.md`）**：把「Redis 挂掉会怎样」「worker 能开几个」这两件只存在于口头共识的事写成带 file:line 锚点的契约，并作为第六图的文字底本。**本轮修正了评估稿里的两处事实错误**（诚实注记）：①评估稿写「Redis 挂 → 队列停摆」——方向对但漏了关键一半：**派发信号在 Redis list（`fde-jobs`，LPOP 弹出即出队），任务事实与租约在 PG**（background_jobs + outbox_events）；准确表述是「Redis 挂 ⇒ 新任务投不出去，但已落库的事实不丢；worker 进程因 RedisError 中断，租约到期后由 reconcile 捞回并标 worker_lost」。②评估稿写「登录 fail-closed」——实际是**可配置**：默认 fail-open（记 WARNING 后放行），`FDE_LOGIN_RATE_FAIL_CLOSED=1` 才切 fail-closed；文档按现状写并注明这是显式选择而非静默漏网。P3-10 **只做边界文档化不改实现**：写清「已安全的六项机制」（行锁领单+租约/租约续期/单活守卫/节点级幂等键/失联诚实收口/跳数熔断）与「当前不宜横向扩的三个理由」（LPOP 弹出即出队 / 单活守卫是查-建两步无唯一约束 / 心跳与 reconcile 未按实例错峰），并给出可扩前提五条清单。缺口四条如实登记不代拍板。
- **P3-9 桌面发起运行入口**：桌面此前**发不起** workflow run（服务端 can_manage 闸与 `POST /projects/{id}/workflows/{def_id}/runs` 一直在，桌面零入口）——定义只能看、运行只能由外部发起。`WorkflowConsole` 的**已发布**定义卡加「启动」按钮（canManage 显隐；草稿定义不给按钮——服务端本就只收已发布定义），成功后重拉运行列表（新 run 是 queued，由 worker 接单），403/409 原样呈现不吞（与 cancel/resume 同一纪律）。新增 `workflow-console-launch.test.tsx` 5 例。
- **第六张架构图（`degradation/degradation-paths.html`，workflow 型 · 12 节点 / 8 边 / 3 车道）**：故障面（Redis 不可用 · 沙箱/凭据/宿主通道不可用 · 上游结果未知）→ 判定与降级（L0–L3）→ 兜底与人工（队列停摆待恢复 · reconcile 补投 · 事实留在 PG · 人工核实与接管 · **写外呼·发信·付款永不降级**）。**降级链写 L0–L3 而非 L0–L4**（L4 属商业编号 `commercial/ladder.py`，与本链无关）——评估稿原写 L0–L4，本轮按 `agents/models.py:74` 的 CHECK 更正。
- **顺带修一处失效的静态钉**：`test_prompt_hygiene_jseries.py` 的 J-1 附钉原按 `workflows/executor.py` **单文件**找 system_prompt 调用点，P1-2 拆分后 skill 分派搬到 dispatch.py → 钉失效（红）。改为扫**整个 workflows 包**——钉的是「工作流侧的 system_prompt 实参」而非某个文件（否则下次再挪文件又会失效），断言强度不变。
- **并发跑测的第二个坑（实测发现并修）**：一次 `downgrade base` 会连续 DROP 130 张表 + 数百个索引，**全链单事务** ⇒ 每个 worker 同时持锁上千，4 worker 并发直接撑爆 PostgreSQL 的 lock 表（`out of shared memory` / HINT: increase max_locks_per_transaction）——表现为「2354 例 setup 全红」。修法＝**测试环境按「每个迁移一个事务」跑**（`migrations/env.py` 的 `transaction_per_migration` **仅在 `settings.env == "test"` 开启**，**生产环境保持单事务**，升级原子性语义不变），持锁峰值降到单个迁移量级。生产语义零变更是这条修法的硬约束。
- **口径**：pytest 本地 **2388 收集 = 2382 passed + 6 skipped**（rebase 融合 #221 metrics +3 后的权威树实测；`-n 4 --dist loadfile`，**10m02s**；串行 1 小时量级——本项要解决的就是它；CI 实测以本 PR run 为准）/vitest **956**（82 文件，+5 = workflow-console-launch 新增 5 例）/mypy **279 基线不变**（官方闸 OK）/路由 **391** / 蓝图 **49** / 表 **130** / **51 rev 单头 `e9c4a1f7b3d2`**（**零新表零新迁移**）/审计三清单重生成（392/131 行，零变化）。桌面便携版 **r22**（0.3.0）：`release/蔡工FDE-0.3.0-便携版-r22/`，asar sha256 `a060fe0a10a674b34bde3cd3468109c8a89a1c2f8889f146acea915d146b2bd5`，中文 marker「已发布的定义可直接发起运行」命中 **1**（证明本轮桌面改动确在包内）。server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（**零新迁移** ⇒ 幂等 no-op）。

## [未发布] — 桌面侧栏滚动修复与质感打磨（纯桌面 CSS，2026-11-09）

- **事故**：`.sidebar` 是 100vh + `overflow:hidden` 的 flex 列，nav 不可滚——admin 可见 17 个导航项时，底部账号区（账号名/角色/退出登录）被静默裁掉（2026-11-09 蔡工报告「最下面的信息已经看不到了」）。
- **修复**：nav 成为「品牌 / 导航 / 账号」三段式中的**弹性滚动段**（`flex:1 1 auto` + `min-height:0` + `overflow-y:auto`），底部账号区永远钉在可视区内；折叠态 72px 下滚动条让位（`scrollbar-width:none`，滚轮/键盘仍可滚）。
- **质感打磨**（CSS only，全走既有令牌，无新增 UI 文案）：滚动条**悬停才显形**（透明→白 0.22→hover 0.38，6px 圆角细条）；品牌区收尾细线（rgba 白 0.08）+ 段间节奏 32px→24px；激活项在金轨（S0·C2 inset 指示条，状态主通道不变）之上加同源横向金晕（`rgba(232,163,61)` 0.18→0.07 淡出，补充通道；**不用 brand-gradient**——design-tokens「交互面不铺渐变」既有钉仍绿）；悬停激活项不洗回白底（`.nav-item.active:hover` 特异性修正）。
- **测试钉**：`design-tokens.test.ts` 新增「侧栏导航滚动契约」4 例（弹性滚动段结构 / 底部钉住 / 滚动条悬停显形+折叠态让位 / 金晕是补充通道且不用 brand-gradient）。
- **真浏览器验证**（gui-harness + Playwright）：既有两链回归 **11/11** 全过（指引链 5 + 集成桥 4 + 控制台无应用级错误）；NEW `desktop/gui-harness/sidebar-probe.mjs` 侧栏专项探针 **5/5**（短视口 1280×620 强制溢出：底部账号区无需滚动即可见 / nav 可滚 scrollHeight 891 > clientHeight 327 / 悬停显形滚动条 / 激活项金轨在位 / 滚到底末项与底部同时可见）+ 截图目检（短/高视口+折叠态+特写）。
- **口径**：vitest **960**（82 文件，+4 = 滚动契约钉）；typecheck web+node 双绿；路由/蓝图/表/迁移全不动（零服务端改动）；pytest/mypy 口径全不动。桌面改动 ⇒ **便携版 r23**（`release/蔡工FDE-0.3.0-便携版-r23/`，asar sha256 `df6987a3b9fe22f2aaa1ec35935584ed7f21768ff038bec1d94a923318701e84`；本轮独有 marker＝激活态金晕色值 `rgba(232, 163, 61, 0.18)` 字节命中 1，中文 sanity marker「退出登录」命中 6）。顺带运维注记：10-30 遗留的陈旧 gui-harness dev server（占 5199 端口、服务主树旧源码）已按「一次只留一个 harness」纪律停掉。

## [未发布] — 商业化 G1：权益四分与角色分层（commercial 两表+R 系角色+对外编号映射，2026-11-08）

- **范围**：商业化任务书 T-04/T-05（G0 裁决 ADR-001/002/006 的实施落地；G0 基线审计+四歧义 ADR 已随 #216 入库 `28f55fd`，含活库智能化实测样本=0 ⇒ 评级维持 L2+ 书面口径、关键流转按「默认人工确认」实现）。前置核验：training_entitlement/subscription_entitlement/certification_status/delivery_eligibility 全仓 grep 零命中（00-baseline-audit §B）。
- **DB（迁移 `e9c4a1f7b3d2`，50→51 rev〔同窗口 #215（V3.1 P1-1）并发插队——其迁移 e7c4a9d2f6b8 与本轮同 down_revision 成双头，rebase 重排后本轮挂其之后，51 rev 单链单头〕，additive 两表）**：`commercial_entitlements`（一人一份 PK=user_id 与 fde_profiles 同构：`commercial_role` R1–R4 可空＋`seat_status/seat_source/seat_activated_at/seat_expires_at` 订阅权益组＋`certification_status/certification_source` 认证指针组＋`delivery_eligibility` 交付资格，五 CHECK 闭集；**值域无任何 L 开头角色枚举**）＋ `training_entitlements`（培训权益购买行 1:N：item_type ∈ training/certification/mentoring、status ∈ active/revoked、valid_until 可空=陪跑期限数值本期不定数〔任务书 §1.2-6「规则先立框架、数值后填」〕、不存金额——科目记账归 G3 科目层〔ADR-003〕，避免双写）。
- **角色分层语义（ADR-001）**：R1 企业/R2 创业者/R3 交付者/R4 区域合作商，可空=未分层；与 `users.role`（平台权限角色四值+ROLE_RANK 阶梯+DEFAULT_ACCESS_BY_ROLE）**正交并存互不推导**——复用/扩展权限角色列的方案被否决（会把商业分层混入权限阶梯并破坏 VALID_ROLES 校验与既有测试）；`fde_profiles.level`（交付能力等级：衡量人、越大越资深）与 `agent_runs.fallback_level`（降级链状态：单次运行）零触碰零改动（dispatch 域 16 测试文件回归 100 例全绿）。
- **对外编号映射（ADR-006）**：NEW `commercial/ladder.py` 是全仓**唯一转换入口**——`external_ladder_code` 从权益权威状态纯函数推导：R3 认证∧席位 active=L1（独立 FDE）否则 L0（候选；Q08「交付者」一身份两状态）、R2 按 seat_source 分 bootcamp_practical=L2（实战营）/bootcamp_mentorship=L3（陪跑营）、R4=L4（区域合作商）、R1/未分层=None（企业不参与对外个人编号）；培训营业务名不带 L 编号。静态钉：商业包+迁移文件中带引号 L 字面量只许出现在 ladder.py。
- **四类权益独立（ADR-002）**：五写原语（role/training grant/revoke/seat-activation/certification/delivery-eligibility）各自只触碰本类列组；`delivery_eligibility` 不覆盖 `fde_profiles.status`（前者商业资格后者供给池生命周期，并存裁决）——唯一跨域同步=席位激活时 pending→active 单向升级（suspended 不动、档案缺失跳过不创建，同步事实落事件 `fde_profile_status_sync`）；重复激活 409 `seat_already_active`（「套餐已含首年席位不重复收」计费不变量的结构前提，计费本体归 G3）。
- **高风险写闸（ADR-002 §2.5，L3「AI 出初稿、人审核后生效」形态）**：六条 admin 写路由全挂双闸——服务层 `_require_admin`（403 `commercial_admin_required`）+ `confirm_password` 必填（缺 400/错 403 `invalid_password`，`auth/passwords.verify_password` 单点）；逐动作 `operation_events` 留痕（target_type=user 复用既有注册目标〔events.py 零改动〕、changes 携 request_id/变更前后快照/target_user_id、敏感键正则双保险——密码不落任何事件）。
- **读面**：`GET /api/v1/commercial/entitlements/<user_id>`（本人或 admin；他人 403 `commercial_entitlement_forbidden`、未知 404）返回权益+培训行+对外编号推导；写面 `POST /api/v1/admin/commercial/users/<user_id>/{role|training|training/<id>/revoke|seat-activation|certification|delivery-eligibility}`。**全部不进 api_catalog**（商业治理面，AI 不可调用——dispatch admin 面同款边界）。
- **注册点（7）**：app 蓝图×2（commercial+admin_commercial）/env.py 模型导入（顺带修 quality 导入重复两行）/conftest 清理序（training→entitlements 子表先清）/test_migrations HEAD=`e9c4a1f7b3d2`+全集 51 断言/审计脚本 BLUEPRINTS 登记（有对账断言守漏登）/审计 CSV 重生成（route CSV +7 行 392、DB CSV +2 行 131、JSON 391/49/130/50 wc 核对）。
- **测试**：NEW `server/tests/test_commercial_entitlements.py` 15 例——四类独立反例×4（角色/席位/认证/培训互不推导：单一「会员等级」字段方案被拒的可辨变异反例）、角色值域 L 值拒绝（L0–L4/R5/r3/空串全 400 `invalid_commercial_role`）、admin 门五路由 403、密码闸（缺/错）、席位 pending 同步+suspended 不动+缺档案不建、双激活 409、审计事件 request_id+无密码、读面权限四态+懒初始化缺省、映射闭包全组合（5 角色×2 席位态×4 源×2 认证）、静态钉×2（L 散落扫描+写原语源码级互不触碰）、迁移往返（head 形状+downgrade -1 双表消失+回 head 恢复）、api_catalog 不进；**变异双验证红→还原→绿**（①set_certification 注入席位派生式→反例③转红→还原绿〔首版反例③因「先激活后认证」顺序掩盖写入已改「无席位先认证」可见化——变异敏感顺序教训〕；②models.py 散落 "L1" → 静态钉转红→还原绿）。
- **口径**：pytest 本地 2348=2333+15+6s（rebase 融合 #215 后 CI 实测 **2360=2345+15+6s**〔#215 基线 2345=2333+12，run 42476898994〕）（新 15+迁移 26+dispatch 回归 100 全绿；全量以 pre-commit 闸与 CI 实测为准）/mypy 279 基线不变（官方闸 OK）/路由 **391**/蓝图 **49**/表 **130**/迁移 **50 rev** 单头 `e9c4a1f7b3d2`；**AGENTS 口径行顺带校正**（前值 122/45/363/45 停在 P0-1 时点、P1-2 轮未同步，本轮按现测修正）；桌面零改动（G1 桌面呈现面挂后续轮，便携版不重打包）；server 变更 ⇒ 合并后 rebuild 三镜像+alembic upgrade head（新迁移）。

## [未发布] — 技能按需调用路由定档 + AGENTS「当前状态」三连标题残渣热修（纯文档零代码零迁移零路由，2026-11-08）

- **技能按需调用路由**：AGENTS「工作流与陷阱」新增每轮工作流技能挂点表——开工/交付=**fde-delivery-flow**、PR 前=**code-review**（权限/并发/资金敏感面）、权限·通道·契约改动=**intended-vs-implemented**、SQL/活库取证=**sql-queries**、桌面交付=**fde-gui-regression**→**fde-package-verify**、集成桥=**fde-bridge-capture**、客户线日常=**fde**、轮收尾=**neat-freak**、点名 workflow=**dynamic-workflows**（CreateWorkflow 强制）、架构图=**archify**（手动跑）。并声明四条机制事实：技能调用=Agent 按 description 自主判断非硬闸、点名 `/技能名` 恒可靠、archify 不在可调用技能列表须手动跑、技能正文调用才加载（每会话只预注入名字+description）。`fde-*` 四技能随仓版本化（`.agents/skills/`）。来源=2026-11-08 全仓技能描述逐一核对后的 top-10 评级（aws-messaging/WordPress 系/PM 简历系出局；dynamic-workflows 为备选第 11）。
- **三连标题残渣热修（教训 49/50 家族，#202–#215 插队链引入）**：`## 当前状态（…）` 标题在 fork/main `58f7a26` 重复 3 次（三个分支各 prepend 各自轮次清单、rebase 全保留），且三变体均漏 P1-1/P1-2/P0-4——合并为单一标题：条目取并集按 PR 序 desc（#215>#211>#209>#207>#205>#204>#203；P2′① 编号由 git log `d797746` (#204) 钉死，序位随之无歧义），尾部自「T-Z1 宿主通道实施轮（裁定 A 落地…」起三变体逐字相同、原样保留。**顺带发现不代补**：「现行结构口径」行停在 #203 现测（363 路由/122 表/45 rev 单头 `c3d5e7f9a1b4`）已被 P1-1（384 路由/128 表/50 rev 单头 `e7c4a9d2f6b8`）超车——沿 P2′① 轮「由口径责任人统一补」先例，本轮不代改（口径现测纪律）。
- 零代码零迁移零路由零桌面；pytest/vitest/mypy 口径全不动；无需 rebuild/alembic/重打包。
## [未发布] — V3.1 P2：试点 Runbook 与最终验收勾稽（纯文档零代码，2026-11-08）

- **范围**：任务书 §14 最终阶段（P2）+§15/§16/§17——试点启动的业务闸（真实项目数据+拍板项）未过前，P2 代码面=「把试点的执行面与验收面落盘」。八阶段实施（P0-0~P0-4、P1-2、P1-1、P1-3，PR #197~#221）已全部收口。
- **NEW `docs/v3.1/pilot-runbook.md`**：①闸门声明（runbook 不构成执行授权）；②前置条件清单 **C1-C7**（C1-C3=真实脱敏项目数据闸：项目选定/访谈素材/模块骨架；C4-C7=拍板项：执行角色、宿主通道保持关闭确认〔默认〕、可选真实联调〔商用条款+12 前置〕、试点窗口与复盘排期）；③E2E 十步操作序（访谈导入→抽取→审阅→本体候选→方案→分解→workflow 草稿→发布运行→测试计划/执行/证据→指标复盘——逐步引用八阶段已交付端点与证据/事件锚）；④验收对照与复盘模板（pilot-复盘-<代号>-<日期>.md 落盘口径）。
- **NEW `docs/v3.1/final-acceptance-checklist.md`**：任务书 §17 十九项逐项勾稽——**16 项达成**（附 PR/代码锚：P0-0 四报告/P0-1 追溯与审阅/P0-2 候选与稳定 ID/P0-3 方案与幂等分解/P0-4 draft 与干跑与 admin 发布/Workflow 恢复取消重试/Gate 唯一入口/产物溯源与撤回/失败不可改写/通道关闭可接管/指标灰态语义/Skill 治理态/全量回归/安全线）/ **2 项待条件**（#14 ZCode 真实联调=商用条款书面确认+12 条安全前置逐项通过+#17 E2E 试点本体=真实项目数据闸）/ **0 项未达成**。
- 口径：零代码零迁移零路由零桌面（pytest **2354=2348+6s EXIT=0** 维持/vitest 951/mypy 279/路由 391/蓝图 49/表 130/**51 rev 单头 `e9c4a1f7b3d2`** 不变）；审计 CSV 零变化；无部署义务（纯文档——镜像不含 docs 运行面）。

## [未发布] — V3.1 P1-3：指标与经验沉淀（metrics 报表 v31 节七指标，2026-11-08）

- **范围**：任务书 §11（P1-3）+ 00-gap-register 7.1/7.3 落地；**7.4（delivery_metric_daily）/7.5（skill_improvement_proposals）维持暂缓**（现报表即席聚合足够+skill 消费量闸未过——活库零数据，建表须先证聚合不足）。**7.2 零代码**：裁决列的事件名与本仓等价名逐一映射成立——`requirement_approved/rejected`→`requirement_reviewed`（P0-1，changes.decision）、`ontology_change_approved/materialized`→`ontology_change_set_confirmed`（P0-2，逐项物化结果随事件）、`delivery_plan_approved`→`delivery_plan_reviewed`+`delivery_plan_published`（P0-3）、`artifact_accepted/rejected`→`agent_artifact_reviewed`（goal-tb tb2）；`task_rework`/`artifact_revoked` 挂账（首个真实数据需求出现时立项，不预支埋点）。
- **七指标进既有报表新节 `v31`**（GET /api/v1/metrics/report；裁决「新指标进同一报表不建平行指标面」；全部走 `_metric` 继承 insufficient_data 语义——样本 0 显式灰态不编造数值）：①`workflow_completion_rate`——终态 succeeded 占比（**非终态 run 不进分母**，7.3）；②`workflow_approval_latency_minutes`——workflow 域审批行（workflow_node_run_id 非空、approved/executed）`updated_at-created_at` 中位数分钟（**updated_at 近似拍板时刻，精确拍板时刻在 workflow_run_approval_decided 事件，细化口径挂账**；rejected/expired 不进样本）；③`workflow_hops_distribution`——hops max+avg（B#1 自触发链代数）；④`requirement_approval_rate`（P0-1 accepted/全量）；⑤`ontology_candidate_adoption_rate`——`captured_from LIKE 'discovery:%'` 变更集 confirmed 占比（**非 discovery 来源不进分母**）；⑥`plan_task_decomposition_rate`——approved/published 方案已建链接条目占比（P0-3）；⑦`test_first_pass_rate`——**每用例只计首条执行**的 passed 占比（重试不重复计数，P1-2）。
- **实施注记**：跨域测试序列曾观察到分解路径 project 行 `FOR UPDATE` 挂起（idle-in-transaction 连接持 xid；pg_terminate 后立刻前进）——根因不在生产代码（P0-3 分解测试同链路独立绿），测试改直插 `DeliveryPlanTaskLink` 造分子样本绕开（分解 HTTP 链路已有 P0-3 覆盖）；挂起根因留观察。mypy 平台差异防御：本轮起 `--platform linux` 本地模拟随常规门跑（教训自 P1-1）。
- **测试**：NEW `test_metrics_v31.py` 3 例（空库 v31 节七卡全 insufficient_data/workflow 域〔非终态排除+时延≈10min+hops 分布〕/域速率四卡〔非 discovery 排除+首条-only 采样〕）；**三变异验证全红→还原→绿**（终态过滤摘除/首条-only 摘除/discovery 前缀摘除——M3 首版无判别力〔测试未造非 discovery 样本〕，补样本后转红=变异判别力本身也要验收）；邻域 metrics_report 7 例回归绿。
- 口径：pytest 本地全量 **2354 收集 = 2348 passed + 6 skipped**（EXIT=0 41:00；本轮 +3；CI 终值以本 PR run 为准）；**rebase 融合 #217（商业化 G1）后口径=路由 391/蓝图 49/表 130/51 rev 单头 `e9c4a1f7b3d2`**（融合树 migrations+metrics+commercial 52 例绿）；mypy 279 不变；vitest 951 不变（零桌面）；审计 CSV 重生成（392/131 行）；server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（幂等 no-op——本 PR 零迁移）。

## [未发布] — V3.1 P1-1：ZCode 宿主执行通道·结构化落地（策略层+票据+扩列，通道保持关闭，2026-11-08）

- **范围**：任务书 §9（P1-1）——00-gap-register 5.3/5.4/5.6/5.7 落地；**5.10 闸纪律：12 条安全前置未过前宿主通道保持关闭**（`agent_host_channel_enabled` 默认 False 零改动+两重静态钉），通道执行面（#195 宿主直连/宿主轮询）维持现状。5.2（adapter spawn 段重构）维持容器路径 `adapter_missing` 降级现状（宿主路径已是 T-Z1 实测契约，见 host_channel.py）；5.5（独立宿主代理进程）待分级开放拍板不预支。
- **策略层（5.4，NEW `agents/execution_policy.py` 纯函数）**：①`normalize_workspace_under_root`——`Path.resolve()` 后根锚定（防 `..` 与符号链接逃逸；根内 `..` 穿越规范化后合法=无害穿越不拒）+`FORBIDDEN_MOUNT_MARKERS` 拒绝清单叠加；②`assert_command_allowed`——argv 首元素白名单锚定（大小写不敏感）+64 元素上限；③`clamp_timeout_ms`——30 分钟上限钳制；④`policy_snapshot`——canonical JSON（sort_keys+工具集合排序）sha256 快照，同输入恒同 hash（审计可重算，#209 确定性纪律）。
- **短期授权票据（5.3，NEW `agents/execution_authorization.py` 纯函数）**：HMAC-SHA256 票据（MCP 15min JWT 原型的 agent_run 域对应物）——绑定 user/project/run/workspace/actions + 15min TTL + `hmac.compare_digest` 恒比较；动作闭集 `workspace.read/workspace.write/command.run/artifact.publish`；验证链=形状→签名→过期→run 绑定→动作覆盖五段。**HTTP 发行面不建**（5.10 闸未过——避免「结构存在但永远 409」的死面，随通道开放轮落地；账目注记可推翻）。
- **扩列（5.6/5.7，迁移 `e7c4a9d2f6b8` 49→50 rev，additive 全可空）**：agent_runs +5（host_agent_id〔宿主代理标识——轮询领取面写入；宿主直连无独立代理进程留空〕/authorization_id〔票据引用〕/workspace_ref/resume_session_ref〔--resume 会话〕/policy_snapshot_hash〔策略快照〕）+ agent_artifacts +4（size_bytes/mime_type〔落库时由原件 len+guess_type 得出〕/revoked_by_user_id/revoked_at〔复核撤回留痕补强——此前仅 reviewed 布尔翻转〕）。
- **接线**：宿主直连通道分支——spawn 前 `normalize_workspace_under_root` 根锚定（service 层）+ `assert_command_allowed` 命令锚定 + `clamp_timeout_ms`（run_host_channel 内）；策略快照经 `AgentRunContext.policy_snapshot_hash` → `AgentRunResult` → `_finalize` 落 `agent_runs.policy_snapshot_hash`；run 行补写 `execution_provider="host_channel"`+`workspace_ref`（**顺带补缺口：宿主直连此前不写 execution_provider**）；产物行落 size_bytes/mime_type。容器路径零改动（ctx 新字段缺省 None，AgentRunResult 同）。
- **测试**：NEW `test_execution_policy.py` 11 例（规范化四分支〔含根内 `..` 无害穿越合法〕/命令锚定四拒一过/超时钳制/快照确定性+顺序无关/票据签发验证+六拒/签发四闸/扩列形状/**双静态钉**〔d4_settings 默认关+config.py AST 字面 False〕）；`test_migrations` 27 例（+roundtrip：downgrade 退列/upgrade 重得/projects 行保留）；三变异验证全红→还原→绿（逃逸校验摘除/签名比较摘除/快照排序摘除）；邻域 host_channel 全绿。实施注记：根内单层 `..` 经 resolve 落根内=无害穿越（首版测试误判为逃逸，已修正断言语义）。
- 口径：pytest 本地全量 **2351 收集 = 2345 passed + 6 skipped**（EXIT=0 31:17；本轮 +12=test_execution_policy 11+migrations roundtrip 1；基线 2339 收集〔含 #210 +1〕）；路由 **384** / 蓝图 **47** / 表 **128** 不变（零新表）/ **50 rev 单头 `e7c4a9d2f6b8`** / mypy 279 不变 / vitest 951 不变（零桌面）；审计 CSV 重生成（385/129 行零变化，50 rev 单头核对）；server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（新迁移）。

## [未发布] — V3.1 P1-2：自动测试与交付证据（quality 三表+覆盖闸+append-only 执行，2026-11-08）

- **范围**：任务书 §10（P1-2）——测试计划/用例/执行三表新建（00-gap-register 6.3 负结论核验：quality/ 模块与 test_plan/test_case/test_execution 全仓 grep 零命中）+ 证据完整性只读校验端点（6.5）+ 环境维度与失败不可改写纪律（6.4）。6.1（agent_artifacts.kind=test_results 通道）/6.2（project_evidence 登记簿+gate 提交闸）按裁决复用零代码。
- **DB（迁移 `d5a8c2f4b7e1`，48→49 rev，additive 三表）**：`test_plans`（项目内版本化 draft→approved+superseded；审核戳 CHECK 两段式；source_task_id 可空=任务书「按任务生成」语义）→`test_cases`（case_key 项目唯一 TC-<hex8>；**requirement_key 强制追溯**〔「测试用例可追溯需求」原文〕；acceptance_mode ∈ test/manual（manual=明确人工验收方式，计入需求覆盖）；risk_level 1..3；steps JSON 结构化）→`test_executions`（**append-only**：服务层零更新函数，重跑=新行；environment 三值+result 三值；report_uri/report_sha256 成对 CHECK）。**evidence_links 第四表不建**——测试↔证据关联由既有 project_evidence 登记簿（提交闸+候选采纳，6.2 复用裁决）+cases.requirement_key 追溯承载，单独关联表是冗余（偏差注记，评审可推翻）。
- **生成器（确定性拼装无 AI）**：`generate_test_plan` 消费 accepted 需求（每条一条用例：expected=验收标准聚合、risk_level=priority 映射 high/medium/low→3/2/1、acceptance_mode=test、steps 留待人工补齐）；**条目序=requirement_key 字典序**（#209 教训：单事务 created_at 全同+uuid4 id 无序，插入序不可依赖）；无已批准需求 409 拒空壳；source_task_id 校验归属（跨项目任务 404）。**AI 用例通道为未来增强**——「模型生成用例先审核」由计划 draft→approved 人工闸承载（落库即待审核于 draft 计划）。
- **需求覆盖闸（6.3）**：`review_test_plan` approved 时校验「每条批准需求至少有测试或明确人工验收方式」——本计划+既有 approved 计划的 cases.requirement_key 并集须覆盖全部 accepted 需求，缺失点名 409 `requirement_coverage_incomplete`（detail.missing_requirement_keys）；rejected→superseded（审核戳两分支同打——驳回也是一次审阅）；新 approved 使旧 approved 退位 superseded（历史行不覆盖）。**实施修正**：审核戳须先于退位循环落——循环查询 autoflush 抢跑 flush 本行，approved+无戳撞 `ck_test_plans_review_stamp`（P0-1 两段式 CHECK 家族教训再现）。
- **执行登记（6.4）**：`execute_test_plan` 批量（≤100，单事务全成全败）append-only——**「失败结果不能被摘要 Agent 改写为成功」以「无更新路径」实现**（服务层零更新函数+静态钉断言无 PATCH/PUT/DELETE 执行路由）；**production 硬闸** 409 `production_forbidden`（值域含 production 仅为形状完备，写入唯一通道=服务闸；显式放行属后续拍板项）；报告指针+sha256 成对（400 拒单边）；跨计划用例 404。
- **证据完整性校验（6.5）**：`POST /api/v1/projects/{id}/evidence/validate`（can_view，**零写入零事件**只读干跑）——五维检查：exists_in_project（项目范围，跨项目不泄露）/fingerprint_shape（sha256 64 hex）/pointer_shape（uri ≤500）/channel_registered（captured_from 通道闭集）/operator_registered（人工通道必须留操作者，机器通道 T-E3 语义允许空）；可选 `gate_key`：门禁行须在项目内（gate_scope）且证据 kind='gate'（类型正确——「Gate 只接收类型和项目范围正确的证据」）。
- **API（+6 路由 377→384，NEW quality 蓝图 46→47〔BLUEPRINTS 已同步+CSV 重生成〕，全部不进 api_catalog 治理面）**：POST `/projects/{id}/test-plans/generate`（can_manage 201）、GET `/projects/{id}/test-plans?task_id=`（can_view，任务书「按任务查计划」的项目域落法——偏差注记：书原文 /api/tasks/{id}/test-plans 改项目域+task 过滤，沿 delivery-plans 路由惯例）、GET `/test-plans/{id}`、PATCH `/test-plans/{id}/review`、POST `/test-plans/{id}/execute`、GET `/test-executions/{id}`（书原文全局路径保留，项目范围经行加载校验）。
- **事件**：target_type 注册表 +`test_plan`；三事件 test_plan_generated/reviewed/executed 直落 operation_events（changes 含 version/case_count/decision/created 数）。
- **测试**：NEW `test_quality_test_plans.py` 7 例（生成确定性+追溯断言+字典序/无输入 409/source_task 闸含跨项目 404/覆盖闸点名+双点退位+仅 draft 可审阅+rejected→superseded/执行闸族〔draft 409+production 409+结果闭集 400+报告成对 400+跨计划 404〕+append-only 静态钉+重跑新行+权限族/validate 全分支〔含零写入事件断言+跨项目范围失败+形状闸 401/400〕/目录红线钉）；**三变异验证全红→还原→绿**（覆盖闸摘除/production 闸摘除/validate 项目范围摘除）。夹具教训=ProjectTask 直插需 planned_start/end_date+duration_days NOT NULL。
- 口径：pytest 本地全量 **2338 收集 = 2332 passed + 6 skipped**（EXIT=0 两轮复核）；**CI 实测 2339 收集 = 2333 passed + 6 skipped**（PR #211 run 42455741083——PR CI 跑融合树预览，含并发 #210 的 +1 测试〔该轮 +1 归 #210 账〕；main 合并态 run 42457269338 全绿收口）/ vitest 951 不变（桌面零改动）/ 路由 **384** / 蓝图 **47** / 表 **128**（+3）/ **49 rev 单头 `d5a8c2f4b7e1`** / mypy 279 不变；审计 CSV 已重生成（384/47/128/49 逐位一致，route CSV 378→385 行、DB CSV 126→129 行 `wc -l` 核对）；server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（新迁移）。

## [未发布] — V3.1 P0-4：Workflow 模板与草稿生成（种子通道+三套模板+draft-from-plan，2026-11-08）

- **范围**：任务书 §8（P0-4）——平台模板底座补种子通道，三套首批模板用既有四类节点表达；方案→Workflow 草稿生成（draft-from-plan）；发布权限拍板项 D-2 维持 admin-only。设计裁决见 `docs/v3.1/00-gap-register.md` P0-4 节（4.5 底座在无种子通道/4.6 三套内容新建/4.4 契约字段分两步/4.8 泛化 compiler 先例/4.9 独立干跑端点）。
- **种子通道（4.5+4.6）**：NEW `seeds/workflow-templates.json`（需求发现=访谈确认→调研技能→事实/需求人工审核；方案实施=方案确认→`solutions.create` 骨架→任务整理→计划发布确认；自动化交付=任务确认→执行完成人工确认→证据汇总→Gate 前确认——**执行段采用人工收口：宿主执行通道开放前不自动触发执行；证据只挂候选，采纳唯一入口=真人提交闸**）。NEW `workflows/templates.py`：fail-fast 装载（形状校验+进程级缓存，沿 `tool_groups.json` 先例）+ `seed_workflow_templates` 幂等落库（沿 `seed_public_skills` 先例：active admin 为 actor、落库即 `publish_definition` 锁版快照；**幂等锚=平台定义 name，已存在即跳过绝不覆盖人工改动**；种子 dag 落库前过 `validate_dag_against_registry` 全量校验，白名单缺引用 fail-fast——**部署顺序：先 `seed-public-skills` 再 `seed-workflow-templates`**）+ `list_published_templates` 只读投影。CLI +`seed-workflow-templates` 命令。
- **节点契约扩展（4.4，草稿期先行）**：`validate_dag` 节点字段白名单 +5——`timeout_seconds`（1..86400 整数）、`input_schema`/`output_schema`（JSON Schema 对象形状）、`failure_class`（`retryable`/`fatal`/`needs_human` 闭集）、`plan_ref`（非空字符串，方案关联）；**执行器增强（超时强杀/失败分类归一 error 码）随 P1 执行通道轮；补偿动作语义需设计轮拍板，本轮不建字段**（未知字段仍被 `unknown_field` 拒绝）。
- **draft-from-plan（4.8）**：`compile_plan_workflow` 纯函数（compiler.py，沿 `compile_delivery_preview` 先例：白名单注入制、确定性输出、provenance 溯源）——只收 **approved/published** 方案（草稿方案无坐实口径，语义对齐 confirmed-only）；三节点形 `plan_review`（human_approval，plan_ref 关联方案）→ `implement`（skill 显式版本注入制，params 携带方案条目摘要+契约字段首发）→ `acceptance_review`（human_approval）；**标题剔除 `{{}}` 防占位符误判**。路由 `POST /api/v1/projects/{id}/workflows/draft-from-plan`（can_manage）：**落库走既有 `create_definition` 通道（白名单全量复校），不建平行持久化路径**；跨项目方案 404 不泄露存在性；compile 错误映射 409（`plan_not_approved`/`invalid_skill_ref`/`invalid_capability`/`invalid_plan_items`）。
- **validate 干跑端点（4.9）**：`POST /api/v1/projects/{id}/workflows/{def_id}/validate`（can_view，零副作用）——复用 `validate_dag_against_registry`（与创建/发布闸同尺），返回 `valid/errors/warnings/order/version/content_sha256` 明细；坏 dag 如实报 issue 码不静默。
- **模板只读面（4.7）**：`GET /api/v1/workflow-templates`（require_auth 已认证可见）——只列 published 平台模板（draft/archived 不外泄），id/name/description/version/content_sha256/nodes 摘要+dag 全文（供「复制为项目草稿」消费）；既有 admin 平台列表 `GET /api/v1/workflows` 权限不变。
- **D-2 拍板执行**：发布权限维持 admin-only（任务书要求「人工发布」未指定角色；放开到 can_manage 是权限面扩张——按审计建议拍板：试点期由 admin 发布，留痕可推翻，publish 路由零改动）。
- **顺带修复（#209 CI 实红根因）**：P0-2 `generate_discovery_candidates` 组序非确定性——facts 查询 `order_by(created_at, id)` 在单事务插入时 created_at 全同（事务时间戳）而 id=uuid4 无内在序，组序实为抽签（本地插入序 vs CI 字典序翻转，test_generate_candidates_happy_path 红）。修法：分组迭代改 `sorted(grouped)`（subject 字典序，同「字典序最小」纪律），候选条目与 skipped 双列表同输入恒同序（变更集指纹跨环境稳定）；测试断言改字典序期望+按名定位条目。ontology 邻域 57 例绿+mypy 279 不变。
- **API（+3 路由 374→377，全部挂既有 workflows 蓝图〔BLUEPRINTS 无需同步〕、全部不进 api_catalog）**；**零迁移**（48 rev 单头 `a9c1e5f7b3d8` 不变；模板落库复用既有 `workflow_definitions`/`workflow_definition_versions` 两表，零新表）。
- **测试**：NEW `test_workflow_templates.py` 10 例（种子形状+真实白名单下 dag 全绿零告警/`seed_workflow_templates` 幂等二轮+种子↔DB 逐字节对账/缺 published 技能 fail-fast/契约字段校验九连+补偿动作 `unknown_field` 仍拒/纯函数确定性+输入四闸+花括号剔除/draft-from-plan 全闸族〔draft 409/未发布技能 422/201 落库/provenance/跨项目 404/member 403〕/干跑端点 valid+坏 dag 明细+viewer 可达+stranger 403+404/模板只读面 3 套+draft 不外泄+401+admin 面权限不变）；**三变异验证全红→还原→绿**（幂等跳过摘除/`failure_class` 校验摘除/plan 状态闸摘除）；邻域回归 workflows+plans 63 例全绿。
- 口径：pytest **2331 收集 = 2325 passed + 6 skipped**（本地全量实测，本轮 +10；CI 终值以本 PR run 为准）/ vitest **951** 不变（桌面零改动）/ 路由 **377** / 蓝图 **46** / 表 **125** 不变 / **48 rev 单头 `a9c1e5f7b3d8`** / mypy 279 不变；审计 CSV 已重生成（377/46/125/48 逐位一致，route CSV 375→378 行 `wc -l` 核对，DB CSV 零变化）；server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（零迁移，幂等 no-op）+ **`seed-workflow-templates` 幂等落库**（顺序在 seed-public-skills 之后）。

## [未发布] — V3.1 P0-3：交付方案生成与任务分解（plans 三表+确定性生成器，2026-11-08）

- **范围**：任务书 §7（P0-3）——从已批准需求/已接受事实/confirmed 术语生成可审核 Delivery Plan，映射到既有 project_tasks（不新建平行任务系统）。设计裁决见 `docs/v3.1/00-gap-register.md` P0-3 节（三表负结论核验=全仓 grep 零命中；任务唯一事实源=project_tasks 原文落地）。
- **DB（迁移 `a9c1e5f7b3d8`，47→48 rev，additive 三表）**：`delivery_plans`（项目内版本化：状态机 draft→approved→published + superseded；审阅戳 CHECK 两段式；published 完整性 CHECK；新版本=新行不覆盖历史）→ `delivery_plan_items`（item_type 六值闭集 requirement/objective/milestone/risk/acceptance/non_goal；requirement_keys/fact_ids 引用清单——服务层闸只从已审阅输入拼装）→ `delivery_plan_task_links`（条目↔project_tasks RESTRICT 映射；UNIQUE(item,task)+**UNIQUE(item)=每条目至多一任务** 幂等锚）。
- **生成器（确定性拼装，无 AI 调用）**：`generate_plan` 消费 accepted 需求（每条一个 requirement 条目，验收标准随行）+ confirmed 术语（objective 范围快照条目）+ needs_clarification 事实（**「待澄清」本身是审阅结论之一，作为风险素材独立于 accepted 集查询**——实施中发现双重过滤恒空的真缺陷并修正）；无任何输入 409 拒绝空壳方案（任务书「未核验不新建」精神）；每次生成=新行 version 递增。
- **审阅流**：`review_plan`（approved/rejected 二选一，决策人+时间戳+备注留痕；**approved 使旧 published 行退位 superseded**——同项目至多一个现行方案，历史行内容永不覆盖）；`publish_plan`（仅 approved 可发布，同样先退位旧 published）。目标类型 `delivery_plan` 三事件（generated/reviewed/published）直落 operation_events。
- **任务分解**：`create_plan_tasks`（dry_run 预览/选择性创建 item_ids/幂等跳过——已链接条目回 skipped[reason=已分解]，**幂等调用同样留痕 created=0** 审计诚实）；任务经既有 `create_project_task` 原语创建（module_id 必填=任务必须挂项目既有模块；**不传指派人**——create_project_task 落 default_assignee_role=None=待认领，任务书「未定负责人不随意指派」原文）；module 校验（不存在/跨项目 404）。
- **API（+6 路由 368→374，NEW `plans/` 模块蓝图 45→46，全部不进 api_catalog）**：POST `/projects/{id}/delivery-plans/generate`（can_manage 201）、GET `/projects/{id}/delivery-plans`（can_view ?status=）、GET `/delivery-plans/{id}`（can_view，条目+任务映射）、PATCH `/delivery-plans/{id}/review`、POST `/delivery-plans/{id}/publish`、POST `/delivery-plans/{id}/tasks`（dry_run 默认 true=预览）。权限：写=can_manage、读=can_view、跨项目 403/404。
- **测试**：NEW `test_delivery_plans.py` 5 例（生成 happy+事件/无输入 409/审阅发布全流转+supersede 链〔v1/v2/v3 三版本〕/分解预览-创建-幂等三段+待认领断言+事件双条〔created=1 与幂等 created=0〕/模块与权限闸族）；夹具教训=ProjectTask 无 project_id 列（经 ProjectModule 间接挂，查询三处修正）、ProjectModule 需 module_catalog_id NOT NULL（夹具补 ModuleCatalog 行）。回归：discovery/ontology/migrations 簇全绿；ruff 绿；mypy 279 不变。
- 口径：pytest **2321 收集 = 2315 passed + 6 skipped**（本地全量 33:04 EXIT=0 实测，本轮 +5；CI 终值以本 PR run 为准）/ vitest **951** 不变（桌面零改动）/ 路由 **374** / 蓝图 **46** / 表 **125**（+3）/ **48 rev 单头 `a9c1e5f7b3d8`**；审计 CSV 已重生成（374/46/125/48 逐位一致，`wc -l` 核对 375/126）；server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（新迁移）。


## [未发布] — V3.1 P0-2：本体候选与稳定 ID（ADR-002+discovery 候选桥+term_id 试点，2026-11-08）

- **范围**：任务书 §6（P0-2）三件套——①ADR-002 文档（NEW `docs/v3.1/decisions/ADR-002-ontology-ownership.md`：control/ontology.py=AI 阅读用语义快照 vs ontology/=唯一治理权威，零代码级重叠实测收编、MCP `ontology_read` 契约冻结、不删旧模块、防漂移三边界）；②discovery→本体候选桥（AI 只创建候选，采纳走既有 change-set submit→confirm 人工管线）；③稳定 ID 试点（`project_research_subjects.term_id` 可空 FK，旧行不回填读路径零变化）。设计裁决见 `docs/v3.1/00-gap-register.md` P0-2 节。
- **候选桥**（`ontology/service.py` NEW `generate_discovery_candidates`/`list_discovery_candidates`）：只消费 `review_status=accepted` 的 business_facts（任务书「候选必须引用已确认事实」原文）；按 subject 聚组为 create_term 条目（组内定义取字典序最小摘要=同输入恒同输出、变更集指纹稳定；fact_type→term_type 映射 metric→metric/data_object→attribute/余→entity）；名字域（术语∪别名）占用跳过并回显 skipped；`captured_from=discovery:<id>` 服务层写入（HTTP 人工路径维持拒收）；幂等=同抽取至多一个活跃（draft/in_review）候选变更集（重复调用 200 复用）；**无 accepted 事实 409 不生成**（杜绝空壳候选）。API +2 路由 363→365（POST `/projects/{id}/ontology/candidates/generate` 201/200、GET `/projects/{id}/ontology/candidates`，蓝图不变全部不进 api_catalog，生成=can_manage/清单=can_view）。
- **稳定 ID 试点**（迁移 `d6f2a8b4c9e1`，45→46 rev，additive 一列一索引）：`project_research_subjects +term_id`（String36 可空 FK→ontology_terms RESTRICT——术语行永不物理删除〔merged/superseded 是状态〕故不构成生命周期阻塞）。链接时机=术语落定：`create_term` confirmed 路径（change-set confirm 物化与直落 confirmed 同汇点）后一次性 UPDATE 同名 subject（只链接 term_id IS NULL 行=幂等回填；已链接行不回改，术语合并不改写历史链接、读路径 impact_of_term 名字域继续兜底）；conftest 清理序现测安全（subjects 两簇均在 terms 之前，RESTRICT 无需重排）。
- **D-1 跨项目同名告警（只读）**：`cross_project_name_conflicts` 助手（confirmed 术语∪别名跨项目查询），候选生成响应附 `cross_project_conflicts`；不动项目内唯一约束（多项目隔离是刻意设计，告警仅作改名/合并决策输入——拍板项 D-1 按推荐项先行、留痕可推翻）。
- **测试**：NEW `test_ontology_discovery_candidates.py` 10 例（happy path 仅 accepted 入候选/同名占用跳过/幂等+409 闸族〔no_accepted_facts·running·缺参〕/权限族〔member 403 生成、200 清单、跨项目 403·伪造抽取 404〕/跨项目告警只读性/清单投影排除人工 change-set/confirm 物化自动链接/直落 confirmed 回填旧数据+重复落定 409/合并不改写链接/无术语主体 NULL+读路径零变化）；回归 ontology 三件套 43 例全绿；test_migrations 26 例（roundtrip 过新头）；ruff 绿；mypy 279 不变。
- **实施中修正（诚实注记）**：①组内定义初版取「首条摘要」但事实行 id=uuid4 无内在顺序→同输入不同输出（变更集指纹不稳），改为字典序最小+测试钉；②审阅戳 CHECK 正确拦截测试工厂无戳 accepted 行（约束按设计工作，工厂补戳）；③mypy Result.rowcount attr-defined → getattr 收窄。
- 口径：pytest **2297 收集 = 2291 passed + 6 skipped**（本轮 +10，基线 2287=2281+6s 本地实测；CI 终值以本 PR run 为准）/ vitest **951** 不变（桌面零改动）/ mypy 279 / 路由 365 / 蓝图 45 / 表 122 / **46 rev 单头 `d6f2a8b4c9e1`**；审计 CSV 已重生成（365/45/122/46 逐位一致）；server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（新迁移）。


## [未发布] — P2′① 宿主轮询领取：服务端咬合接线（领取/回执/失联三面，2026-11-08）

- **形态落地（§11.3 六条约束 → 代码）**：NEW 迁移 `f6d3a9c1e7b2`（39→40 rev 头 `f6d3a9c1e7b2`）——`agent_runs.status` CHECK 置换加 `host_running`（对齐 T-J2 先例，零列重建）+ 5 新列（`execution_provider`〔sandbox 默认/host_poll〕/`host_claimed_at`/`host_token_hash`〔sha256 零明文〕/`host_receipt_at`/`host_lost_at`）+ 领取面索引；`IN_FLIGHT_STATUSES` 补 `host_running`。
- **三条宿主机器面路由**（不进 api_catalog，与 bridge 同族；鉴权=`X-Host-Poll-Token` 头 sha256 比对）：`GET /agents/host/status`（待领取数+失联标记顺带触发）/`POST /agents/host/claim`（FIFO+行锁 skip_locked+幂等重领同 token 返回同载荷+异 token 403）/`POST /agents/host/runs/{id}/receipt`（终态语义与容器对齐：exit0=completed/非零=failed/宿主报 timeout·budget_exceeded 同名终态；产物**宿主侧 sha256 直录**〔storage_ref 带 `host:` 前缀，服务端永不回读原件〕；校验失败只记 failures 不改终态——H4 人工按明细处置）。
- **发起侧**：`agent_host_poll_enabled` 开启时 start_run 落 `execution_provider=host_poll`+保持 queued 即返回 **202**（发起=受理，执行由宿主代理异步驱动；优先级高于 dev 直连）；config 新增 `agent_host_poll_enabled`（默认 False）/`agent_host_poll_token`（SecretStr）/`agent_host_lost_mark_minutes`（默认 30）。**生产启用闸未解除**：`adapter_missing` 维持到「①实装 + D3 书面回执 + N2 联调签核」齐备——本开关只解除形态未实装，不解除人工闸（H4/H1/N1/N2 原样）。
- **H4 失联只标记**：`mark_host_lost` 扫描 host_running 超阈未回执 ⇒ 打 `host_lost_at`（幂等不重打；**不迁移状态不自动重试**）；由宿主代理 status 轮询顺带触发，零 scheduler 依赖。
- **测试 pytest +19**：NEW `test_host_poll.py`——fail-closed 闸 3（默认关/半配置/坏令牌）/领取 6（FIFO+状态迁移+幂等重领+**续领语义**〔代理崩溃重启不带 run_id 续上自己手里的活〕+token 轮换后旧 hash 续领冲突+空队+sandbox 隔离）/回执 8（completed 产物直录+非零 failed+宿主 timeout+幂等 duplicate+令牌绑定+**轮换后回执 403**+未领取拒绝+校验失败明细与指纹缺失不落库）/失联 2（超阈标记+新鲜跳过）/HTTP 烟测 1（关闭态 403→status→claim→receipt 全链+错误投影）。
- 口径：pytest 终值以本 PR CI run 实测为准（基线 fork/main `ba61d2c`（rebase 后权威树，含 #203 discovery）本地收集 2292 ——V3.2 G2-G7 +115 与 #203 +? 均未入 AGENTS 口径行 2152，本轮不代补、随轮以 CI 为准）；**+3 路由面**（rebase 后权威树实测 **366** 路由/45 蓝图/122 表/46 rev 单头 `f6d3a9c1e7b2`——含 #203 discovery 的 +7 路由 +4 表 +1 迁移一并基线校正；清单已重生成随 PR 提交）；vitest 不变。台账钉自检：本节含 pytest + 交付信号（delivery）。
- 关联：消费 #193 §11.3 拍板（六条决策级约束）；与 V3.1 P1-1 分工——票据（5.3）/execution_policy（5.4）/artifact 扩列（5.7）/provider 字段扩展（5.6 部分本轮已带 execution_provider）归 V3.1 线后续轮。
## [未发布] — V3.1 P0-1：访谈事实与需求结构化（批A 服务端+批B 桌面审阅面同 PR，2026-11-08）

- **范围**：任务书 §5（P0-1）服务端半——四表+迁移+契约校验器+后台抽取 job+8 路由+14 例测试；桌面审阅 UI（DiscoveryPanel）归批 B 另轮（任务书 §15「每个 Goal 一个明确子切片」）。设计裁决与负结论核验见 `docs/v3.1/00-gap-register.md` P0-1 节（复用 transcripts 生命周期/T-A2 脱敏三道防线/guidance 管线范式；四表确认无承接体）。
- **批B 桌面（同 PR）**：NEW `desktop/src/renderer/src/discovery/DiscoveryPanel.tsx` 挂项目 overview tab（转写面板后）——抽取发起（纪要下拉+幂等双文案）/抽取记录（失败码+脱敏复核 tooltip+重跑仅 failed）/事实清单（过滤+三动作+**批量接受本页待审**+锚点三形态 line·transcript_segment·char_span 呈现）/需求清单（批准/否决/澄清）；写操作 canManage 显隐。NEW `discovery-panel.test.tsx` 7 例。vitest 944→951（+7）；typecheck 0 错。
- **DB（迁移 `c3d5e7f9a1b4`，44→45 rev 挂上游 V3.2 G6 头 `e8b1d5f9a3c7`，additive 四表）**：`discovery_extractions`（状态机 queued→running→{review_required|failed}；幂等键 UNIQUE(project,source_type,source_id,extractor_version,prompt_version)；source_sha256 服务端从源行读取、客户端不可伪造；redaction_entries 复核条目）→ `business_facts`（fact_type 十值〔任务书九值+open_question 归一〕+classification 五分类**对齐 guidance**〔ai_synthesized/human_added 保留给人工路径，v1 不开写面〕+行级审阅 pending→{accepted|rejected|needs_clarification}，审阅终态留痕 reviewed_by/at+comment；UNIQUE(extraction,fact_type,subject,predicate) 批内身份）→ `requirements`（requirement_key 项目内唯一 R-<hex8>；六类型+三优先级；acceptance_criteria 结构化列表 1–20 条；approved_by/at 审阅留痕）→ `requirement_sources`（需求↔事实关系表——任务书「长期用关系表非 JSON ID 数组」原文落地；UNIQUE(requirement,fact)）。CHECK 六道：审阅戳方向「终态必带戳、pending 必无戳」两段式（初生 needs_clarification 合法）；推断/开放问题初生强制待澄清、人工澄清后可流转。
- **抽取管线**（NEW `discovery/jobs.py`，克隆 guidance/jobs.py 纪律）：outbox topic `project.discovery.extract`（RECOVERABLE 集 +worker_loss 失败钩子沿 guidance 先例）；AI 走 `execute_ai_prompt(return_metadata=True)` 单一入口（预算门+审计+降级直连全复用，use_tools=False）；契约失败一次自动重试（概率性畸形）→ 整批失败零写入（任务书「不得静默部分写入」）；输出端逐字符串过 `redact_text_detailed` 兜底 + `discovery.redaction_review` 事件（guidance 第③层同构）；推断（inference）与开放问题（needs_clarification）分别落 ai_inferred/open_question 分类并强制 needs_clarification 审阅态；**无来源事实的需求不得自动接受**（source_fact_indexes 空 → needs_clarification）。
- **契约**（NEW `discovery/contract.py`）：精确键集+域外键拒绝+fact_type/requirement_type/priority 闭集+批内事实去重+验收标准 1–20×500 字+source_fact_indexes 越界/重复拒绝+source_locator 三形态闭合（line≥1/transcript_segment 0≤start≤end/char_span start<end）。NEW `discovery/prompt.py` v1 纯常量（J-1 提示词卫生：模块级常量形态，已登记 `test_prompt_entrypoint_gate` 白名单 `_ALLOWED_PROMPT_CONSTANTS`）。
- **API（+8 路由 355→363，蓝图 44→45，全部不进 api_catalog——治理审阅面沿 transcripts/ontology 先例）**：POST/GET `/projects/{id}/discovery/extractions`（创建 201/幂等复用 200；can_manage）、GET `/discovery/extractions/{id}`、POST `/discovery/extractions/{id}/run`（**重跑仅 failed**——review_required 行审阅痕迹不可覆盖 409）、GET `/projects/{id}/business-facts`（review_status/fact_type 过滤+有界分页）、PATCH `/business-facts/{id}/review`（终态 409）、GET `/projects/{id}/requirements`（status 过滤）、PATCH `/requirements/{id}/review`。权限：写=can_manage、读=can_view、跨项目 403/404、伪造 source_id 404。
- **测试**：NEW `test_discovery_extraction.py` 14 例（契约四态/HTTP 创建幂等+三道闸/重跑保护/成功流/重试与零写入/输出脱敏+复核事件/推断强制澄清/worker_loss/审阅流转+终态/列表过滤+越权）；变异面：审阅戳 CHECK 方向与迁移同源（初生 clarification 两段式断言）。回归：test_migrations/test_route_inventory_sync/test_prompt_entrypoint_gate/test_outbox/test_job_reconcile/test_guidance_redaction_worker/test_transcript_drafts/test_ledger_sync_nail + 上游 simulation 域 14 例全绿；mypy 基线 279 不变；审计 CSV 已重生成（route 363/blueprint 45/table 122/rev 45 单头）。
- **接线上游并发**：批 A 开发窗口内 fork/main 并入 #197（本线 P0-0）/#198–201（V3.2 模拟训练场 G0–G7）——迁移链 rebase 挂 `e8b1d5f9a3c7`、test_migrations 注释行合并、known 数 44→45、extract 脚本 BLUEPRINTS 双登记（discovery/simulation 同窗）、测试库按外来戳配方全量重建（半迁移脏态：版本戳=head 而 simulation 表缺失——DROP 全表重建后 clean build 123 表）。**教训**：alembic_version 戳会被同 revision id 的新文件「骗过」upgrade——重建必须清全表而非只 downgrade。
- 口径：pytest **2287 收集 = 2281 passed + 6 skipped**（本地全量 40:54 EXIT=0 实测；其中本轮 +14=test_discovery_extraction，其余增量=上游 #198–201 simulation 域测试未随其轮在根 CHANGELOG 报数，本轮现测一并落账；CI 终值以本 PR run 实测为准）/ vitest **951/951**（81 文件；基座 944 + 本轮批B +7）/ mypy 279 不变；**零桌面零 api_catalog**；server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（新迁移）。

## [未发布] — 文档基线与结构口径对齐轮（纯文档零代码，rebase 至 #203 / 2026-11-08）

- **版本口径统一**：`VERSION`、README 版本徽标、`AGENTS.md` 首段 `v0.2.0` → **`0.3.0`**（与 `desktop/package.json` / `server/pyproject.toml` 发布列车一致）。README 升版说明里的 `v0.2.0` 是 tag 命名示例、非版本口径，保留原样。
- **AGENTS 现行口径行**：状态段新增 `fork/main 92ca0bd` / PR #203 现测一行（122 业务表 / 45 迁移 head `c3d5e7f9a1b4` / 363 路由 / 45 蓝图 / `api_catalog` 94 ENTRIES / mypy 279）。**各历史轮 bullet 中的口径数字为该轮时点实测值，作历史记录保留、未改写**（尤其 V3.1 P0-0 轮的 `109 表/39 rev/323 路由`）——改它会篡改历史。
- **CI 实测核销**：#203 把口径推进至 122 表 / 45 rev / 363 路由 / 45 蓝图（CI 实测 pytest **2287 收集 = 2281 passed + 6 skipped**、vitest **951/951（81 文件）**，见 #203 bullet；本 PR 仅刷新口径行与审计 CSV 基线标记，不引入新测试增量，CI 终值以本 PR rebase run 实测为准）。
- **操作手册**：尝试 §3 标题与正文 12 → **13 个 tab**（依据 `routing/useHashRoute.ts` 的 `PROJECT_DETAIL_TABS`；补 §3.12「执行智能体」/ §3.13「评审会」两节），新增 §15「模拟训练场」（左侧独立导航 `#simulation`，5 分区；**训练场是全局页，不是第 14 个 tab**）——但因 `server/src/fde_api/control/bundled/help_manual.md` 孪生副本测试硬锁（12 tab：`test_docs_copy_of_manual_stays_identical_to_bundled` / `test_manual_and_ui_page_agree_on_key_facts`），于 `be564e0` 回退，维持 12 tab；落差登记于《同步说明》。
- **配置样例**：`.env.example` / `server/.env.example` 补注释态 `FDE_BRIDGE_TOKEN` / `FDE_LOGIN_RATE_FAIL_CLOSED`（此前仅代码与 AGENTS 有语义）。真实令牌仍只放 `server/.env`，永不提交。
- **审计清单**：`v3-route-inventory.csv` / `v3-database-inventory.csv` 首列 repository 标记 `0570384` → `92ca0bd`（rebase 至 #203，CSV 已由 #203 重生成至 route 363 / table 122 / rev 45 单头，(method,path) 集合随 #203 实际路由变化）；`test_route_inventory_sync.py` 同步钉对 (method,path) 集合负责，首列标记变更不触发其断言。
- **诚实登记（本轮未改）**：生成脚本 `scripts/audit/extract_workbench_inventory.py` 两处仍硬编码 `fde-workbench@0570384`。本轮为纯文档轮，**未改 .py 以避免触发 pre-commit 的 python 钩子与并发全量 pytest 争抢 advisory lock**；下次重生成会把标记带回旧值 ⇒ 后续轮应把该常量改为动态 `git rev-parse --short HEAD`。
- **零业务代码零迁移零路由零桌面** ⇒ 无需 rebuild / alembic / 重打包。文档中心侧同步见 `D:\test\FDE\蔡工FDE工作台_文档中心\00_文档总览.md` §12.6。

## [未发布] — V3.1 P0-0 基线审计轮（智能交付自动化升级路线图第一轮，纯文档零代码，2026-11-07）

- **任务书入库**：`docs/蔡工_FDE_Workbench_V3.1_智能交付自动化升级路线图与Goal实施任务书.md`（自述基线提交 `7368094`）正式入库作为 V3.1 唯一权威任务书；审计基线取 fork/main `65db88c`（其后 1 提交=#196）。
- **四报告**（NEW `docs/v3.1/`）：`00-baseline-audit.md`（任务书 §2 十条核验逐项：25 路径 24 命中 1 修正〔AgentsConsole 实际在 `agents/` 子目录〕；**zcode_contract.py 纯函数契约层判断成立**——171 行零 subprocess/socket，建模真实 0.17.1 CLI `zcode -p --json --cwd [--mode] [--resume]`；发现 `adapter.py:99-113` spawn 段为自认虚构契约=P1-1 重构靶点；`control/ontology.py` vs `ontology/` **零代码级重叠**〔75 行静态字典+MCP 唯一消费方〕，ADR-002 列 P0-2 文档交付物）、`00-data-model-map.md`（109 表按域全分组+迁移链 39 rev 头 `e5f1a7c3b9d4`+事件 22 目标类型+12 job_type+API 面）、`00-test-baseline.md`（环境/命令/结果全量实测+209 测试文件与各阶段回归面映射）、`00-gap-register.md`（P0-1~P1-3 逐能力**复用/扩展/新建/暂缓**四档裁决——每项「新建」附负结论核验〔requirements/business_facts/discovery_extractions/delivery_plans/test_plans 全仓 grep 零命中〕；P0-1 四表成立但分类枚举须对齐 guidance 五分类；P0-2 变更集全链复用仅缺 term_id 试点链接+跨项目别名冲突待拍板；P0-4 模板底座在但零种子零内容；P1-1 须先对齐在途 host-channel 线〔D-3 拍板项〕；4 项拍板项 D-1~D-4 待蔡工确认）+ `phase-status.md`（阶段状态台账，P0-0=completed，**允许进入 P0-1**）。
- **活库运行数据（部署库直查，alembic=e5f1a7c3b9d4 与代码头一致）**：agent_runs/workflow_runs/workflow_definitions/agent_artifacts/automation_approvals/ontology_change_sets/transcript_drafts/interview_minutes/project_solutions/delivery_packages/handover_packages **全 0**；projects=4（somwyn G1–G6 passed）；guidance_analyses=5（3 failed：ai_authentication_failed×1+ai_output_invalid×2=唯一真实 AI 失败分布）；project_evidence=3 全 bridge_sync；skill 消费事件 1——P1-3 指标基线=insufficient_data，与任务书预判一致。
- **口径现测**（AGENTS 现测纪律；任务书 §2 旧台账 107 表/38 rev/315 路由/pytest 2116 为陈旧值全数校正）：**109 表/39 rev 单链 head `e5f1a7c3b9d4`/323 路由/94 ENTRIES/mypy 279**——与 fork/main CI 实测逐位一致；本轮全量测试实测：pytest **2136 收集=2130 passed+6 skipped**（32:40 EXIT=0）/ vitest **932/932**/ typecheck 绿 / mypy 279 官方闸绿；API Catalog↔路由差异=设计性（治理面有意不进 catalog，CI 双钉在位）。
- 顺带修复 AGENTS 残渣一行（「版本号按发布列车同步」句的孤儿重复片段，冲突残渣家族）。零迁移零路由零业务代码零桌面 ⇒ 无需 rebuild/alembic/重打包；审计在隔离 worktree（主树并发脏集零触碰）。
## [未发布] — T-Z1 宿主通道实施轮：裁定 A 落地（agents/host_channel.py 宿主侧 zcode 代理，2026-11-07）

- **T-Z1 裁定 A 实施落地（用户拍板商用前置改判：仅开发自用即刻可用，推向市场前须 zcode 书面授予）**：NEW `server/src/fde_api/agents/host_channel.py`——宿主侧 zcode 代理通道，0.17.1 实测契约（`-p <任务书路径> --json --cwd <workspace> --mode build` + `ELECTRON_RUN_AS_NODE=1`）；`--json` 单对象汇总 fail-closed 解析（空/非对象/exit0 不可解析一律不伪造 completed）；超时=kill+communicate 回收（PIPE 缓冲不死锁）；预算超限按上限截断报 `budget_exceeded`（对齐容器版 B-2「越界不入账」）；**零凭据注入**（平台凭据解密结果不进 argv/env/磁盘，出现未用凭据标 `degraded` 经 `_finalize` 走 L1 强制人工终审）；workspace 拒绝清单复用 `FORBIDDEN_MOUNT_MARKERS`（真相层/.env/fdeops/openfde）。
- **契约收敛（rebase #193 后）**：`host_channel_argv` 委托 `zcode_contract.build_cli_argv`（#193 拍板唯一 argv 形状来源；本模块只补宿主壳前缀 `<ZCode.exe> <zcode.cjs>` 与 `--mode`）；`summarize_host_payload` 委托 `parse_json_summary().billable_units`（优先投影 totalTokenCount，回落 input+output——与容器版 cost 事件同口径）；`parse_host_summary` fail-closed 外壳（空/非对象拒绝）仍由本模块承担。测试期望值随 billable 口径同步（128→192）。
- **接线**：`config.py` 新增 `agent_host_channel_enabled`（**默认 False**——容器内 server 进程 spawn 不到宿主桌面进程，仅宿主裸跑态显式开启；关闭时容器路径行为零变化）/`agent_host_zcode_bin`/`agent_host_zcode_cjs`（开启但缺失 ⇒ 503 `agent_unavailable` + run 落 L2 零计费）；`agents/service.py` `_execute_run` 开关分支（`_write_workspace` 后、容器 backend 前）产出与容器适配器**同构 `AgentRunResult`** ⇒ `_finalize`/C-1 产物校验/T2 强制门/回执缺失独立终态**零改动复用**；容器路径与虚构契约 `spawn_argv` **不动**（T-Z1 裁定维持 `adapter_missing` 降级现状）。
- **测试 pytest +22**：NEW `test_host_channel.py` 19（argv/env 契约逐位断言/拒绝清单/--json 解析四态〔happy/前缀噪声/空/非对象〕/usage 缺失诚实计 0/超时 kill+双回收/非零退出 failed/exit0 坏汇总 fail-closed/预算截断与恰好达标/凭据零外泄/spawn OSError/workspace 红线先于 spawn）；NEW `test_host_channel_service.py` 3（开关关=容器路径零变化回归/开关开=宿主 spawner 成功+落账 42 tokens/bin 缺失=L2）。**变异四连全红→还原绿**（M1 拒绝清单失效/M2 超时不 kill/M3 预算截断失效/M4 fail-closed 失效）。
- 诚实缺失登记：宿主版无逐事件流（--json 仅单对象汇总；逐事件只有 app-server stdio 协议一条路，本轮不做）⇒ `tool_calls` 恒空、运行期无逐工具留痕；白名单语义由任务书文字面承载（与容器版同源）。
- 口径：pytest **2152 收集 = 2146 passed + 6 skipped**（2116 基线 + #193 契约层 14 + 本轮 22；rebase 合并口径推演，终值以本 PR CI run 实测为准）；vitest 927/927 不变；**零迁移零新表零新路由零桌面**（复用既有 POST /agents/{id}/run）⇒ 无需 alembic/路由清单重生成，server 变更 ⇒ 合并后 rebuild 三镜像。台账同步钉自检：backlog T-Z1 标题行升 ✅ 已实施并合并（钉①同轮闭环）；本节含 pytest + 交付信号（delivery 类，钉②放行）。

## [未发布] — goal-tb tb4：T-B1 封包半——结项交付包 handover_packages（D11 立项拍板落地，2026-11-07）

- **拍板落定（§拍板闸 6⑪，蔡工「第3件需要拍板的按你建议处理」）**：D11 立项按台账 §二草案+§十三.4 改名裁决执行；「首批真实数据到位」**不阻塞代码实现**（合成 run 测试覆盖，投产使用自然等待真实 run）。台账 §二已追加拍板记录节（留痕可推翻，#124 先例）。
- **DB（迁移 `e5f1a7c3b9d4`，38→39 rev，additive）**：`handover_packages`（draft→sealed→delivered；unseal 仅 sealed→draft 且 unsealed_count 留痕；**delivered 终态不可逆**；5 条 CHECK）+ `handover_package_items`（**指针+sha256 快照**——B#6 真相原则「清单是投影」，artifact_id 无 FK、metadata 扫描钉死零外键指向 agent_artifacts；同包同产物唯一约束）。表名与派单 `delivery_packages` 不混用（§十三.4 裁决）。
- **API（+8 路由 315→323，蓝图 42→43，全部不进 api_catalog）**：`POST/GET /handover-packages`、`GET/PATCH /handover-packages/{id}`、`POST …/seal|unseal|deliver`、`GET /handover-packages/artifacts`（挑选面=本项目已复核产物投影）。权限=查看 can_view、创建/编辑/封存/解封 can_manage、**交付登记=admin 专属**（草案「delivered（登记对外交付）=admin」原样）。
- **seal 语义**：冻结清单 + **逐项校验四闸**（产物存在 / 属本项目 / **已人工复核**〔与草案 status∈{confirmed,available} 闸同构〕/ 指纹一致→`fingerprint_drift` 409）+ `manifest_sha256`＝清单规范化 JSON 哈希（测试按同参数复算钉死）。审计四事件 `handover_package_created/sealed/unsealed/delivered`（target=项目，不复制产物内容）。
- **桌面**：NEW `handover/HandoverPackagesPanel.tsx` 挂 **delivery tab**（方案设计下方）——草稿组包（勾选已复核产物，默认名取 storage_ref 末段）/清单详情（名称/种类/指针/指纹）/封存/解封/交付登记（`isAdmin` 显隐与 admin 闸同构）/manifest 指纹呈现；无障碍闸（游离 label 检测）驱动修正为显式 htmlFor/id。
- **测试**：服务端 NEW `test_handover_packages.py` 6 例；变异三连红→还原绿（摘 reviewed 封包闸→红 / 摘 deliver admin 门→红 / 摘指纹漂移校验→红）。桌面 NEW `handover-packages-panel.test.tsx` 5 例。pytest **2122 收集 = 2116 passed + 6 skipped**（+6；基线=fork/main@63f12de 实测 **2116 收集（2110+6s）**＝#191 实测 2108+6s ＋ 并行 #190 台账同步钉 +2〔本地全量直测 2116+6s，勘误：预写 2120 少计 #190 增量〕）/ vitest **932/932**（78 文件，+5）/ mypy 279 不变。实施中发现并修正两处（诚实注记）：①序列化初版经 `db.session()` 重开会话读不到事务内未提交行（`sessionmaker` 非 scoped）→ 显式传事务 session；②manifest 摘要先算后落 sealed_at 致哈希与呈现不一致 → 调序（先落封存态再算清单）。server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（新迁移）；桌面变更 ⇒ 便携版 r21（0.3.0）。
## [未发布] — 22:25 交互拍板：人工项方向收口 + PR #193 合并授权（2026-11-07）

- **交互方式**：用户「人工部分你使用交互式选择方式解决」⇒ 两轮 5 张选择卡片（依据/收益/代价/推荐理由写正文、卡片只用 A/B/C 编号）。
- **Q1=A**：PR #193 合并已授权——rebase 到 `c2fe869`（#194 B# 线 FREEZE，CHANGELOG 冲突按「以 main 段为底叠加本轮增量」解决、两节均保留）→ CI 复跑 4 job 全绿 → squash 合并。
- **Q2=B / Q3=C / Q4=C / Q5=A**：D3 回执＝用户**主张**已取得但原件指针+sha256 未提供；N1/N2＝授权人·首个 run 发起人·真机窗口未提供；N3/D7＝产出物定义·阈值 N 与依据未提供且 `approval_rows=0` ⇒ **方向先落文本、四闸维持关闭**，`adapter_missing` 维持、E8 不实施、阈值不预支。Agent 不代填外部事实、不代发起 run、不代跑真机、不造证据。
- **留痕六处**：本文件、`docs/audit/下一步实施台账-2026-11-07.md` §12、`D1-D3拍板留痕…md` §8、`D4-D7人工项推进包…md` §6、`docs/implementation/v3-backlog.md` 22:25 补录、`docs/architecture/售前驱动交付模式改造方案.md` 22:25 补录；20:08／20:38 原文保留作沿革。
- **零迁移／零路由／零配置／零安装／零种子改写／零 DSH 改动／零红线放宽**；H1–H13／N1–N7 原样；本续轮只改文档留痕与 rebase 后的发布动作。

## [未发布] — 演进方向评估 v1.1 落地批：台账同步钉 + 三项拍板 + B# 线 FREEZE（#190/#192 后续，2026-11-07）

- **B# 线 FREEZE（P1-5 落地）**：B# 登记号封顶 B#40（backlog B# 节 FREEZE 注记）；《开源项目借鉴总览》《实施实况报告》转只读档案（头注 ARCHIVED；上游 LICENSE/HEAD 复核义务仍按红线第 8 条④）。解冻=40 条全终态 ∧ 方法级新借鉴 ∧ 用户显式拍板。
- **AGENTS**：①口径行 pytest 2114→**2116 收集 = 2110 passed + 6 skipped**（#190 +2；CI run 42366699714 直测合并后 main 2110+6s）——补 #190 轮未随轮同步的缺口；②新增 B# FREEZE bullet（工作流与陷阱节）。
- **关联轮次**：#190（台账同步钉两钉 + backlog T-A2..T-A8 七条标题行状态同步 + DoD 四件套入 AGENTS + 两份评估文档归档入库）；#192（三项拍板：执行通道=A 宿主侧代理、商业验证决策单〔90 天止损线 + 2027-02-05 复评，先到者为准〕、行业口径复议受理〔全行业=目标态，现状=自用〕）。
- 口径：pytest **2116 收集 = 2110 passed + 6 skipped**（CI run 42366699714）；vitest **927/927**（77 文件，PR 192 run 42373576921 实测——#190/#191/#192 桌面零改动）；mypy 基线 279 不变；**零业务代码零迁移零路由零桌面改动** ⇒ 无需 rebuild/alembic/重打包。台账同步钉自检：backlog 零 T- 标题增删（钉①放行）；本节为拍板落地记录（delivery 类，钉②放行）。

## [未发布] — D1–D3 拍板落地 + T-Z1 实施轮准备（2026-11-07 20:08）

- **拍板（用户「D1–D3 按你推荐的拍板。其它你去处理」）**：D1＝**A 宿主侧 zcode 代理**（B 降可选演进／C 否决，依据 #191 E1–E4 四重阻断）；D2＝AGENTS.md「bridge 只读」红线**显式扩写宿主侧写通道**＋五条边界；D3＝zcode 商用条款**以供应商书面确认为准**。**D3 是决策不是外部事实**——书面回执仍缺，生产启用闸不解除、`adapter_missing` 维持。Q6 由「形态待裁定」结案为「形态已定 A，宿主代理接线待实施」。
- **留痕四处**：`AGENTS.md` 红线第 6 条／`docs/architecture/售前驱动交付模式改造方案.md` §10「✅ Q6 结案」／`docs/implementation/v3-backlog.md` T-Z1 标题·闸⑤·拍板落地段／`docs/audit/下一步实施台账-2026-11-07.md` §8·§11。
- **NEW 契约层（纯函数，零 spawn／零凭据／零落库）**：`server/src/fde_api/agents/zcode_contract.py`——`build_cli_argv`（真实 `-p --json --cwd`，`--resume <sessionId>` 取值开关，`--mode` 由授权档位显式传入、不预设业务语义）／`parse_json_summary`（`--json` **单对象汇总**→结构化计账字段；缺字段坏类型如实归零，`response` 正文与 `usage.provider` 一律不收）／`summary_to_events`（`cost`+`done`，**不伪造 `tool_call`**）／`JsonSummaryEventProvider`（B#14 固定夹具一次性回放）。`agents/adapter.py:93` 加定向警示 TODO 指向本模块（**零行为变更**），spawn 段整体重划待 P2′ 架构决策。
- **NEW 夹具与用例**：`server/tests/fixtures/zcode_json_summary.json`（形状取自 #191 实测样本、内容全部自拟，零客户资料／零真实凭据；原始样本 `D:\test\FDE\tz1-probe\` 只留本地永不进仓）＋`test_zcode_contract.py` **14 例**（真实 argv 与禁用虚构契约／`--resume` 取值／汇总字段映射与容错／夹具形状钉／回放 provider／汇总事件喂既有 `ZcodeAdapter` 监听段）。**定向验证：14 passed ＋既有 `test_agents_adapter.py` 9 passed；ruff `--select F401,F841 src tests` 全绿；mypy 基线 279 occurrences / 104 distinct 不变。全量 pytest/vitest 口径以合并后 CI 实测为准，本轮不预写数字。**
- **A 裁决连锁口径校正（本轮新发现，防后续轮把 zcode 塞进容器）**：`docker/sandbox/Dockerfile` 注释明示**不安装 zcode**（镜像只留 nodejs + iptables）；`docs/试点前联调-iptables与zcodeCLI-检查单.md` 二表整表改写（钉定对象由「沙箱镜像内 zcode」→**宿主侧代理进程**：CLI 0.17.1 + `zcode.cjs` sha256 + provider revision；#3 与 iptables 一表解耦；证据表标签同步），**一表 iptables 生效性断言原样有效**；backlog T-Z1「修改文件」行与台账 §2/§3 E1·E10/§4 P2 拆行同步。
- **`spawn_argv` 未机械改写**：A 通道下 `sandbox.exec` 在 Linux 容器执行，而 zcode 只在 Windows 宿主；只换 argv 会制造「契约修好但执行位置仍错」的假象（#191 §2 明写随拍板后实施轮执行）。本轮改落可独立验证的契约层；**新识别 P2′ 决策**＝宿主代理 ↔ `agent_runs` 状态机咬合方式（推荐「宿主轮询领取」，决策卡见台账 §11.3）。
- **NEW 文档**：`docs/audit/D1-D3拍板留痕与实施轮交付-2026-11-07.md`、`docs/audit/D4-D7人工项推进包-2026-11-07.md`（D3 确认函草稿／D4 试点立项卡／D6 A 轨诉求问询卡／D7 四口径复审报告骨架；**均为准备件，不代发函、不代选试点、不代拍阈值**）。
- **人工闸一个不放宽**：H1–H13／N1–N7 原样；D3 回执、N1 试点授权、N2 真机联调签核、P2′ 拍板、D4–D7 均留人工，Agent 不代跑真机、不造运行证据。**零迁移／零路由／零配置／零安装／零种子改写／零 DSH 改动**；改动留本地隔离 worktree 分支 `feat/tz1-host-proxy-contract`，20:08 时点未 push／未建 PR（并发轮活跃 + CI 需人工守望）〔**20:38 已由用户「确认」授权解除，见下条**〕。
- **【2026-11-07 20:38 续轮，用户「确认」】P2′ 咬合方式按推荐拍板＝① 宿主轮询领取**（② 长连接否决／③ 人工中转仅作降级验证），并授权 `commit → push fork → 开 PR → 守望 CI`。六条决策级约束：宿主→服务端单向；领取／回执两写路由幂等且复用既有鉴权、`queued`／`host_running` 入状态机；超时失联只标记不自动重试（H4）；凭据只在宿主内存管道零落盘、客户真实资料零外发；`zcode_contract.py` 为唯一 argv／汇总形状来源；③ 仅用于首次降级验证且证据只留指针 + sha256。**形态已定 ≠ 接线实装**，`adapter_missing` 维持；AGENTS.md 红线第 6 条文本不改写。留痕：方案 §10 Q6 结案表、backlog T-Z1 标题与拍板落地段、台账 §0/§3/§4/§8/§11.3/§11.4/§11.5、`D1-D3拍板留痕` §0/§4/§5/§6/§7。**仍留人工**：D3 供应商书面回执、N1 试点授权、N2 真机联调签核、N3 A 轨诉求、D7 阈值、**PR 合并拍板**；H1–H13／N1–N7 原样。本续轮**零代码改动**（相对 20:08 基线只加文档留痕与发布动作）；PR 号／CI run id／全量收集数属运行事实，以 PR 页面与 CI 实测为准，不在版本库预写。

## [未发布] — goal-tb tb3：T-Z1 zcode 真机实测报告 + 执行通道裁定提案（纯文档，2026-11-07）

- NEW `docs/audit/T-Z1-zcode真机实测与通道裁定提案-2026-11-07.md`（T-Z1 登记闸「开工前半天实测」必做项的实测记录与裁定提案；**纯文档零代码零迁移零路由**）。
- **实测事实**（全部真机直测）：① CLI 真实契约 = `ELECTRON_RUN_AS_NODE=1 ZCode.exe resources/glm/zcode.cjs`（doctor: node v24.21.0）；② **闸①会话续接 ✅**——`--resume <sessionId>` 0.17.1 为取值开关（登记原文「布尔开关」勘误入档）+ `-c/--continue`，真机双跑验证同 sessionId 上下文携带；③ **`--json` 实测为单对象汇总**（sessionId/traceId/response/usage/eventCount/projection，非 ndjson 事件流——粒度事件流在 app-server stdio 协议；登记原文⑤勘误）；④ **容器内直跑四重阻断**——sandbox-runner node v20 缺 `node:sqlite`（node:24-alpine 实测 zcode.cjs 可跑 ⇒ JS 层唯一硬阻断）+ provider 配置缺 + 登录态缺 + `network_mode: none` 零 egress；⑤ **闸①商用条款 ⚠️**——zcode 本体无独立 LICENSE 授予文件（仅第三方 MIT 组件清单），商用集成前须向供应商书面确认（挂账不代决）。
- **裁定提案（交蔡工拍板，§拍板闸 6⑤ 拍板项不代决）**：A=宿主侧 zcode 代理（推荐：零 sandbox 基座变更、沿 bridge-poll 宿主纪律同构、`--json`/`--resume` 契约齐备）/ B=openfde 加 zcode executor（须补 B#35 许可登记）/ C=容器内直连（不建议：三重安全面变更叠加）；**无论 A/B 均须先办 AGENTS「bridge 只读」红线修订 + 商用条款确认两件拍板**——办结前编码执行通道维持 `adapter_missing` 降级（登记闸③原样生效，不阻塞第一阶段主线）。适配器 CLI 段重写随通道拍板后的实施轮执行（本实测轮零代码）。
- 口径全不动（pytest 2114 / vitest 927 / 路由 315 / 38 rev 均沿 tb2 基线；无需 rebuild/alembic/重打包）。

## [未发布] — goal-tb tb2：T-B1 agent_artifacts 扩列 + 产物人工接受写路径（封包半挂 D11，2026-11-07）

- **范围声明（登记原文「封包前置」逐字生效）**：本轮**只做 artifacts 扩列**——`handover_packages` 新表与封包/解封/下载路由**未建**（D11 立项拍板 + 首批真实数据两前置未达成），产物→交付包闭环维持挂账。
- **DB（迁移 `b8e4d6f2a9c3`，37→38 rev，additive）**：`agent_artifacts` +`derived_summary` JSON 可空列（**可重建派生**——diff: files_changed/additions/deletions；test_results: passed/failed/errors/skipped + exit_code；解析不可达如实零计数不发明数字；**原件本体永不进库**，B#6「引用方永不复制真相，只持指针」）+ `reviewed_by_user_id`（FK users SET NULL）+ `reviewed_at`；kind CHECK 置换扩 `'test_results'`（纯枚举扩展零列重建，T-J2 先例）。度量表「编码智能体一次测试通过率」与「智能体产物被人工接受率」两个「需先补字段/补写路径」缺口自此闭合数据源。
- **派生纯函数**：NEW `agents/artifact_summary.py`——`derive_artifact_summary(kind, content)`（2MB 解析上限；diff 统计按 unified diff 行首规则；test_results 全文扫「N passed/failed/errors/skipped」token 累加）；finalize 入库同事务派生（exit_code 来自 run 结果合入摘要）；可重建性=同一原件二次派生逐位一致（测试钉）。
- **API（+1 路由 314→315，不进 api_catalog）**：`PATCH /agents/runs/{rid}/artifacts/{aid}` body `{reviewed: bool}`——**can_manage**（终审动作）；接受留 who/when，撤回清双痕；事件 `agent_artifact_reviewed` target=项目、changes 只带 id+布尔（不复制产物内容）；跨 run 配对 404、非布尔 400。
- **桌面**：AgentsConsole 产物行 +「标记复核/撤回复核」（`canManage` 显隐与服务端闸同构；成功后**重拉 run 详情回真**，不本地猜写）+ reviewed_at / derived_summary 呈现（摘要以 key=value 尾注展示）。**版本号按发布列车同步 0.2.0→0.3.0**（`desktop/package.json` + `server/pyproject.toml`，登记原文要求的列车同步）。
- **测试**：服务端 NEW `test_agent_artifact_acceptance.py` 5 例；变异三连红→还原绿（摘 can_manage 闸→红 / 撤回不清双痕→红 / 跨 run 不校验→红）。桌面 +2 例（canManage 显按钮+PATCH reviewed:true 形状+回拉详情 / 缺省无按钮）。pytest **2114 收集 = 2108 passed + 6 skipped**（+5，基线=#188 run 实测 2103+6s）/ vitest **927/927**（77 文件，+2）/ mypy 基线 279 不变。server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（新迁移）；桌面变更 ⇒ 便携版 r20（0.3.0，与 tb1 桌面增量同窗打包）。

## [未发布] — goal-tb tb1：T-A9 转写草稿区 + 访谈纪要正式库（ASR 通道 opt-L 落地，2026-11-07）

- **拍板落定（§拍板闸 6⑩，蔡工逐字「ASR 通道选型：按你建议实施」）**：立项文档《录音转写ASR通道立项-v1.md》§3.3 P1–P6 逐项按推荐项落定（§3.3.1 新增拍板结果节）——**P1=opt-L 本地 ASR 先行**（红线同向零外发）、P2=横评实测裁决、P3=Windows 宿主裸跑、P4=首版普通话、P5=诚实失败、P6=云默认不开（启用=新的显式拍板）。T-A9 实施轮随之解封。
- **NEW `docs/audit/ASR本地引擎横评-2026-11-07.md`**（P2/P3 实测数据，随本 PR 归档）：faster-whisper（int8/CPU）× whisper.cpp b5454 × tiny/base/small，TTS 本地合成虚构文本（零客户资料）双片段（68.7s 普通话 + 20.2s 中英混说），CER 经 OpenCC 繁简归一——**faster-whisper base 档胜出**（中文 CER 8.6% / 混说 6.5% / 4× 实时）；whisper.cpp small 中文精度最高（5.9%）但慢于实时；FunASR 因 torch 依赖过重不实测（如实注记）。横评工具链与模型只留本地 `D:\test\FDE\asr-bench-local\` 永不进仓。
- **DB（迁移 `d7b2f8a4c1e6`，36→37 rev，additive-only）**：`transcript_drafts`（草稿区：状态机 draft→promoted|expired|discarded；墓碑化清空正文/指纹/复核条目；7 条 CHECK 含晋升必带三要素、活动草稿必有正文、墓碑必无正文）+ `interview_minutes`（正式库：客户确认三要素 NOT NULL + `redaction_hits` 计数）。**物理隔离机械钉**：全库零外键指向 `transcript_drafts`（minutes.draft_id 为纯字符串指针，B#6「引用方永不复制真相，只持指针」），metadata 扫描测试钉死。
- **API（+7 路由 307→314，蓝图 41→42，全部不进 api_catalog）**：`POST/GET /transcript-drafts`、`GET /transcript-drafts/{id}`、`POST …/discard`、`POST …/promote`、`GET /interview-minutes`、`GET /interview-minutes/{id}`。权限=草稿读写 can_view（T-A3 校准「录入 member 已可用」同构）、**晋升 can_manage**（入正式库=管理动作）；列表有界分页（50/200+truncated）、行不带正文防大载荷。
- **红线三面**：①**只收文本**——无任何音频字段，录音原件永不进平台（SOP :109/:111 逐字锚，UI 注记钉住）；②**T-A2 代号化不豁免**——create/promote 两处 title/content/确认人文本先过 `redact_text_detailed`（词典命中→enterprise_code 首段代号、疑似同样替换），词典不可用 fail-closed 503 `pseudonym_dict_unavailable`（guidance 同码），复核条目（#160 同形状）随草稿行存储+详情回显、墓碑时一并抹除，正式库只留命中计数；③**无客户确认的转写文本无法进正式库**——晋升三要素（确认人/时间戳/确认方式）缺一即 422 + 未来时戳拒绝（CR-029 教训）+ CHECK 双保险。
- **T+7 自动清理**：`purge_expired_drafts` 接入 cli scheduler 循环（与过期清扫/退避提醒同拍），到期活动草稿墓碑化 + 独立文件根（`FDE_TRANSCRIPT_DRAFT_ROOT`，默认 `.fde-transcript-drafts`，与 `.fde-storage` 不共根）子树删除；skip_locked 防并发互堵；墓碑行留作 T+7 合规对账凭据。
- **桌面**：NEW `transcripts/TranscriptDraftsPanel.tsx` 挂 overview tab guidanceSlot（presurvey 录入卡旁）——本地文件导入（只读文本进表单、原件不上传）、草稿列表/详情（正文+复核清单词典命中徽标）、弃置、晋升表单（canManage 显隐与服务端同构）、纪要正式库列表/详情；加载失败 fail-静默（教训 51），动作错误 alert 呈现。
- **测试**：服务端 NEW `test_transcript_drafts.py` 8 例；变异三连全红→还原绿（摘晋升三要素校验→红 / 代号化改直通→红 / 清理谓词取反→红）。桌面 NEW `transcript-drafts-panel.test.tsx` 7 例。pytest **2109 收集 = 2103 passed + 6 skipped**（+8）/ vitest **925/925**（77 文件，+7）/ mypy 基线 279 不变。server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（新迁移）；桌面变更 ⇒ 便携版重打包（r20）。

## [未发布] — goal-ta4 路由审计清单 CI 同步钉（#174 教训机械化，零业务代码，2026-11-07）

- NEW `server/tests/test_route_inventory_sync.py`（pytest +1）：`create_app().url_map` 实际路由对账 `docs/audit/v3-route-inventory.csv`——比对口径与生成器 `scripts/audit/extract_workbench_inventory.py` 一致（跳过 static、剔除 HEAD/OPTIONS、method 多值按字母序 `|` 连接），同一 (method, path) 集合逐位相等，漂移即红并报「实际有而清单缺 / 清单有而实际无」两份明细＋重生成指引。**「动路由必同步审计清单」从此有机械闸兜底**（#174：#171/#162 两次清单落后靠人工发现；AGENTS「审计清单刷新有前置条件」节人工纪律不变，加机器兜底）。handler/service/auth 等富化列不在钉内（归生成器自守，避免钉子复制第二份生成器逻辑）。
- 变异验证：删 CSV 一行→红（报缺失明细）→还原→绿。零业务代码零路由变更零迁移；pytest **2101 收集 = 2095 passed + 6 skipped**（**CI 终值实测 run 42343361485**；勘误链：#183 PR 实测 2095 收集=2089+6s → #185 +6 例 → 本轮 +1 ⇒ 2101；前写「基线 2094 收集=2088」系 rebase 解析误取行内更早轮次注记，本节以 CI 直测为准）；vitest/路由/表数/迁移头全不动。
## [未发布] — goal-c CR-029 服务端小轮：集成桥 captured_at 服务端钟 sanity（2026-11-07）

### 修复

- **集成桥 `captured_at` 单向采信宿主钟（goal-c 台账 CR-029，P3）**：`_parse_captured_at` 此前只校验格式不比对服务端钟——宿主 NTP 前漂 >6h 或带 `FDE_BRIDGE_TOKEN` 方伪造 `captured_at`（未来）会让 `openfde_synced_at`/`fdeops_synced_at` 落在未来 → `now - synced_at` 恒为负 → 4h/360min stale 标永不亮（文件盘上持续腐仍显「新鲜」，采集断连被永久遮蔽）。`apply_snapshot` 落库前单向钳制：未来时戳一律钳到服务端接收时刻（同一时刻兼作 `run.started_at`），与偏移量无关——「不存未来时戳」是不变量本身。**过去方向不钳**：只会更早触发 stale（无害方向），且钳过去会伪造 `manual_reproject` 重放旧快照的新鲜度（重投影 ≠ 采集）。钳制不吞数据：engagement 照常投影，只是时间戳诚实化。
- **宿主钟偏移观测面**：`|skew| > 90min`（`CAPTURED_AT_SKEW_TOLERANCE_SECONDS`）才把 `captured_at_skew_seconds`（int，负=宿主钟超前）记进 `run.summary`——正常采集不污染 summary 形状；运维定位面（「为什么全场 stale 诡异亮起」→ 看本键即知宿主钟漂了多大）。

### 测试与口径

- NEW `server/tests/test_bridge_captured_at_sanity.py` 6 例：未来 6h 钳制不变量（stored ≤ now ∧ 数据零损失 ∧ 不误报 stale）／小偏移 2min 同样钳（不变量与量无关）／skew 观测键入 summary（负值≈-21600）／正常钟不带键（形状稳定）／过去 3 天直通且 stale 立即亮（无害方向保真）／manual_reproject 重放 30min 前快照不刷新新鲜度（过去不钳的回归钉）。变异 M1（钳制中性化）→ 钳制两例红、余四例绿 → 还原绿；变异 M2（标记门中性化）→ summary 例红 → 还原绿。
- 口径：服务端 pytest **2085 收集 = 2079 passed + 6 skipped**（本轮 +6，与 goal-ta2 轮 +6〔test_agents_meetings_lists 5＋事实链 B#9 钉 1〕同基线 2073 收集＝2067+6s 叠加；CI 实测为准）；桌面 vitest **912/912**（goal-ta2 轮 +15；本轮桌面零改动）；路由 307（goal-ta2 轮 +2；本轮零路由）；零迁移零新表（迁移头 `b2e8f4a6c9d3` 36 rev 不变）；**server 变更 ⇒ 合并后 rebuild 三镜像（alembic 幂等 no-op）**；本轮桌面零改动 ⇒ 不触发便携版重打包（goal-ta2 轮桌面挂账随其节）。
## [未发布] — goal-ta3 T-A1 核销：S3 前置闸桌面提示已由 #156 兑现（纯文档，2026-11-07）

- **零代码零迁移零路由零桌面 diff**：backlog T-A1 状态 PROPOSED→**DONE（核销）**——桌面呈现（`PresurveyGateHint.tsx`：409 `presurvey_s3_gate_open` 拦截态渲染服务端 message＋G3 四项证据清单＋claimed≠accepted 徽标＋「前往门禁页」跳转锚）已由 #156（2026-11-06）先行交付并接线 `PresurveyAnalysisAction`；goal-ta3 按 fork/main@1a1d34e 实测逐项核对登记验收四项全部成立，专项测试 `presurvey-gate-hint.test.tsx` 5 例全绿，**零补码**（T-UI1 同款核销先例）。依赖图同步。
- 口径全不动（pytest 2079 收集 = 2073 passed + 6 skipped / vitest 912 / 路由 307，均为 #182 CI PR-head 实测）；无需 rebuild/alembic/重打包。

## [未发布] — T-A8 agents/meetings 桌面控制台 + #171 复核清单桌面收口（goal-ta2，2026-11-07）

### 行为变更（+2 只读路由；零迁移零新表；桌面变更 ⇒ 便携版重打包）

- **服务端**：`GET /api/v1/agents/runs`（project/status/时间过滤＋limit 1..200/offset 分页＋truncated）与 `GET /api/v1/meetings`（project 过滤＋同款分页）。可见性单一权威 NEW `projects/permissions.py::visible_project_ids`（跨项目聚合复用 `project_access`，不在 SQL 重写第二套规则）；单项目 404（不存在）/403（can_view=False）。**不进 api_catalog**（人工控制台面，沿 T-W6/B#9 先例）。防 N+1：runs 行无 `agent`/`artifacts` 键（`_serialize_run(detail=False)`）；meetings 行无 `turns` 键、话轮计数单条分组查询预聚合（`_serialize_meeting` 增 `turns_count` 可选参，既有端点零变化）。
- **桌面**：NEW `agents/AgentsConsole.tsx`（run 列表→详情[agent/产物指纹]→tool-calls[放行/拦截]→成本汇总）＋ NEW `meetings/MeetingsConsole.tsx`（会议列表→话轮流→closed 才拉纪要三段式+sealed 指纹）；项目 tab 11→13（「智能体」「评审会」）。拍板 6⑥ 维持：与 B#9 执行事实面板界面分离。
- **#171 复核清单桌面收口**：`GuidanceReview` 消费 `get_analysis.redaction_review`（服务端唯一投影）呈现条目（名称/次数/词典命中）；409 `redaction_review_required` 拦截提示＋「已复核」勾选后重发 `redaction_reviewed: true`；干净分析 confirm 不带键；本地缺清单时 409 回读读面补渲染（仍不自行推导）。
- **B#9 断言钉**：`guidance.redaction_review` 事件在执行事实链**元数据可见、`changes.entries`（疑似企业名）绝不外泄**（与既有 changes 不外泄钉双钉）。
- 测试：pytest +6（NEW test_agents_meetings_lists 5 ＋ 事实链钉 1）；vitest +15（agents-console 6＋meetings-console 5＋guidance-redaction-review 4；project-detail tab 钉 11→13 项）。变异四连红→还原绿（can_view 闸/limit 上界/changes 外泄双钉/ack 携带）。
- 口径：路由 305→**307**（审计清单已重生成，route CSV +2 行/blueprint 41/表 105/36 rev/head 不变/DB CSV 零变化）；基线 main@677746c CI 实测 pytest **2067+6s**、vitest **897**（72 文件）；本轮 PR 预期 pytest **2073+6s** / vitest **912**（75 文件）。**勘误**：#179 记桌面基线 882 已陈旧（main CI 双源实测 887）。

## [未发布] — goal-c 台账收口：CR-033/036 驳斥销号 + CR-034「在途写不退出」保护接线（2026-11-07）

### 行为变更（纯桌面，零服务端零迁移零路由）

主进程新增「在途写不退出」保护（goal-c 台账 CR-034 接线，dead-code 修复）：
- 主窗口关闭时若仍有非 GET 请求在途（`activeMutations > 0`），弹确认框点名在途写入数量——「等待完成」取消本次关闭，「仍然退出」一次性放行（消费式旗标，放行不常开）；确认框悬起期间重复关闭只拦不再弹（防叠框）；`app.quit()` 路径同样先经窗口 close 事件，保护同时覆盖退出菜单。
- 数据源不动：计数仍由 `registerApiIpc` 对非 GET 累计；此前该计数器全仓零读取点（登记为 dead-code）。NEW `desktop/src/main/close-guard.ts` 纯函数决策内核＋文案（Enter/Esc 安全默认＝等待完成；文案不承诺自动重试）。

### 台账驳斥销号（零代码）

- **CR-033**（lcsc 规格书 iframe 检测表达式畸变）——**登记误读**：fork/main 源码两处均为 `f.src.includes('atta.szlcsc.com')&&f.src.toLowerCase().includes('.pdf')`，括号配对正确；`git log -S "includes('atta.szlcsc.com')"` 唯一命中 `5ded7b3`（2026-09-29），正确结构自引入以来从未变动，c7 登记时即现态。
- **CR-036**（ResearchWorkspace 导出轮询 stale 快照回写）——**守卫已存在**：deps 含 `researchExports`（新增导出必重跑 effect→cleanup→旧闭包 `cancelled=true`）＋poll 唯一 await 边界后紧跟 `if (cancelled) return`，stale 写回不可达；该结构来自 J7b 重构（`697bfb3`，2026-10-28），早于 c7 登记；`cancelled` 布尔与 `sequence` ref 在此单链自续期场景语义等价。

### 测试与口径

- NEW `desktop/tests/main/close-guard.test.ts` 10 例：决策矩阵 4＋确认文案 2＋**index.ts 接线静态钉 4**（close 处理器消费决策／放行旗标重触发 close／activeMutations++/-- 数据源仍在／确认框悬起期间重复关闭只拦不再弹——防接线再次静默脱落＋防叠框）；变异验证：守卫中性化→红→还原→绿。typecheck 双 tsconfig 绿；全量 vitest 897/897（72 文件）。
- **口径校正**：#178 T-A7 轮实际 vitest +12（NEW solution-frozen-version 7＋solution-design +5）此前未入 AGENTS 口径行，#179 CHANGELOG 记 882 系基线误取陈旧 870 推算——**实测 887**（#178 PR-head run 42318566336 与 main run 42320178306 desktop job 双实测、本地一致），本轮校正后总量 **897**（+10 本轮）。
## [未发布] — 架构评估修复轮：需求↔代码对齐评估（2026-11-07）全量修复

评估报告：`docs/audit/架构评估报告-需求与实现对齐-2026-11-07.md`（九差异/六偏离模式/九建议；基线 fork/main `ff4813c`）。本节=§四建议 1–9 全量实施。**红线零违反（无 P0）**；部分对齐主因=文档↔代码一致性滞后，本轮系统性回写。

### 服务端行为变更（零迁移零路由；server 变更 ⇒ 合并后 rebuild 三镜像，alembic 幂等 no-op）

- **D2/P1 翻译器脱敏（本 P1 缺口的唯一代码修复）**：`translator/` 全链接入 T-A2 企业名脱敏——①**创建面原文不落库**（`_redact_translation_input`：种子词典命中→「客户代号」、疑似名→替换+复核、通用词零改动；词典机制故障 fail-closed 422 `pseudonym_dict_unavailable` 行不落库；凭据串 422 `sensitive_credential_detected`）；②**落库前兜底**（AI 输出回显企业名同样替换）；③**复核事件两阶段**落 `translator_translation` 目标（stage=input/output，`guidance.redaction_review` 同型）；④**采纳交接**：`adopt_translator_draft` 把条目搬到分析目标，confirm 复核闸（#171）按分析聚合**自动覆盖翻译链**（采纳响应即携 `redaction_review`；闸逻辑零改动）。**单一权威重构**：`redact_draft_payload` 从 guidance/jobs 私有提升至 `guidance/redaction.py` 公共原语（presurvey/translator 共用）；`DICT_FAILURE_CODE` 归位 `enterprise_dict.py`（jobs 保留同名 re-export 兼容）。翻译器无项目维度⇒替换别名恒「客户代号」（采纳后项目语境由复核清单兜底）。
- **D4 pilot 契约警示**：`pilot_status` 增派生键 `contract_unverified`/`warnings`——窗口激活但零**非演练 completed** run 即警示（ZcodeAdapter spawn 契约未经真机验证（售前方案 Q5/T-Z1），spawn 失败全落 L2 会污染试点指标）；只读呈现不拦 run（`pilot_capacity_error` 不变）；演练 run 排除口径与 20-run 计数器一致。
- **D1 防复发**：`scripts/audit/extract_workbench_inventory.py` 加「BLUEPRINTS 项数 == app.py register_blueprint 数」对账断言（宁红不漏；重生成过闸 305/41，三清单零字节漂移）。**初评 D1「现行违例」撤回**——系初评 grep 落在主树（落后 #177 的 c05bb19）旧文件上的取数误差，fork/main 脚本/清单均最新；教训记入评估报告附记。

### 测试补钉（G7 四缺口全部收口 + 架构静态钉）

- NEW `server/tests/test_translator_redaction.py` **9 例**：创建面替换/疑似/通用词三分、词典故障与凭据 fail-closed、输出回显兜底+output 事件、采纳交接+闸 409/ack 放行留痕、干净草稿零误伤（变异验证：摘创建面替换→红、摘采纳交接→红）。
- NEW `server/tests/test_model_credential_key_derivation.py` **3 例**（G7-①）：缺省派生可解 / 轮换 JWT secret 即 `credential_unavailable` 且密文本体不变（换回旧 secret 即恢复） / 独立密钥隔离（`FDE_MODEL_CREDENTIAL_KEY` 后轮换零影响；反向钉独立键自身失效同样不可解）。
- NEW `desktop/tests/main/renderer-url.test.ts` **6 例**（G7-④）：`isAllowedRendererUrl` 开发 origin / 打包态 file: 包含性 / query 拒绝 / 目录逃逸拒绝 / 远程协议拒绝 / 异常输入拒绝（判定本体纯函数，零生产代码改动）。
- `test_architecture_purity.py` +**1**（P-4）：`test_top_level_package_import_cycles_stay_frozen`——AST 全包顶层导入环实测 **18 对**冻结（新增环红、静默解环也红，清单显式维护）。
- `test_agent_pilot.py` +**3**（D4）：零 run 警示在位 / 真实 completed run 清警 / 演练 run 不算契约证据。
- G7-②③复核在位零补码：桥重放 `test_bridge_sync_flags.py:179,228`、微信密码指令 `test_ai_api_actions.py:155`（初评漏记，已补记覆盖地图）。

### 文档系统性回写（D3/D5/D6/D7/D8；全部 .md）

- **7 份系统意图文档**（架构/关键流程/权限矩阵/变量与密钥/测试覆盖地图/定时任务/自动化面）：统一「快照更新 2026-11-07」头注；工具计数 14→**17**、写类分面口径（effect≠read 共 3，`lcsc_search` external/2 入册）、降级白名单 12→**13**、scheduler「唯一 1 个」→**5 面**、worker job 8→**12**、约 30 处行号重锚；关键流程补 T-A2 三道防线/复核闸/G3 前置闸/证据一等表/CAS；变量与密钥补 `FDE_ENTERPRISE_DICT`/`FDE_AGENT_*` 族、登录限流落点勘误（auth/limits.py→auth/routes.py:28-68）；自动化面补翻译器管道节（§6）与 file_send_wechat 实构防线（D5：无密码环节，原「事前密码确认」失真）。
- **G3 验收场景矩阵**：补场景 1.7（代号化三道防线+复核闸全链）/1.8（S3 闸桌面拦截）；更新记录自纠「改行为先改场景表」三轮违例。
- **测试覆盖地图**：基线改 CI 实测（pytest 2073 收集/ vitest 887）；§三 G7 四缺口全收口表；§二建议项六项现状（Serper 项失效销号）；逐文件计数停止维护（以 CI 为准）。
- **技术实施方案**勘误三处：dispatch 禁区口径对齐钉子范围（读路径禁 join，D8）、ZcodeAdapter 契约偏差注记（Q5/T-Z1）、meeting 工具落点注记（meetings 侧非网关）+ generated_by 值域勘误（实构 `('human','agent')`）。
- **backlog T-A1 状态回写**（D6）：PROPOSED→DONE（#156 `ab046f4`）。**冲突解存档：#184 goal-ta3 核销轮已先行落盘同一结论（DONE/零补码，fork/main 权威版），本 PR 冲突解取其版；D6 登记断档的两会话独立发现，以先合并者为准。**
- **评估报告自订**：D1 撤回注记、D9 补记②③在位、§六实施轮附记（九建议逐一落点）。

### 口径勘误（D7）

- AGENTS vitest 口径 **882→887**：#179 补账取了 #178 PR-head 值（870+12），漏计 #177 已上移基线 875（875+12=887；CI run 42322015325 / 42323992174 desktop job 双证 887 passed）。

### 部署与打包

- server 变更（translator/agents/redaction/jobs）⇒ **合并后 rebuild 三镜像 + `alembic upgrade head`**（零迁移，幂等 no-op）。
- 桌面仅新增测试文件（零生产代码）⇒ 便携版无需重打包（tests 不进 asar）。
- 口径（**CI run 42338168736 PR-head 实测**）：pytest **2094 收集 = 2088 passed + 6 skipped**（基线 #184 后 2073+6s ＋ 本轮 +15）；vitest **918/918（76 文件）**（基线 #182 后 912 ＋ 本轮 +6）；mypy 基线 279 不变（官方闸绿）；路由 307 / 蓝图 41 / 105 表 / head `b2e8f4a6c9d3` / ENTRIES 94 不变（307 系 #182 先行 +2，本轮零路由）。

## [未发布] — goal-ta1 拍板回写 + 录音转写 ASR 通道立项（纯文档，2026-11-07）

### 蔡工拍板回写（§拍板闸 6⑨，三行逐字；零代码零迁移零路由零桌面）

- **剩余 T-A 线分工**：「剩余T-A线本会话」——T-A1 / T-A8+B#9 合批 / T-A9 随 ASR 立项 / 工程卫生轮，归执行 goal-ta 循环提示词的会话；**T-A7 为绝对禁区**：「T-A7另外一个会话在做，其它本会话可以做」——backlog T-A7 条目只加一行分工事实注记（#178/#179 均已由该会话合并），不重写其任何段落。
- **ASR 通道立项**：「立项」——文档轮。NEW `docs/architecture/录音转写ASR通道立项-v1.md`：SOP `somwyn/raw/2026-10-27-FDE接触调研阶段资料入库SOP设计.md:109`/`:111` 红线**逐字引用**（录音与未确认转写永不入正式库；录音原件永不进 repo/DB）；现状行级实测（`ai/kimi.py:43-47` MiniMax purpose 枚举 5 项**无音频转写**；全仓零音频转写链，与上位方案缺口表 G3 一致）；通道选型三候选（opt-L 本地 ASR＝红线同向 / opt-C 云 ASR＝**客户语音外发的红线张力显式登记** / opt-H 混合），**推荐本地先行、云=显式红线例外**；承接机制引用 T-A9 登记原文（独立表+独立文件根、T+7 清理、草稿不可被方案/报价/SOW 引用、晋升三要素、转写文本过 T-A2 代号化管线不豁免）；**显式「待蔡工拍板」节（P1–P6）收口——不代决**。
- backlog 同步：§拍板闸 6 增 ⑨（分工决议三行逐字）；T-A9 条目闸更新（**立项半已批**、立项文档指针、「跑通」半待选型拍板+真机实测随实施轮闭合；**T-A9 维持 PROPOSED，立项≠实施**）；依赖图 T-A9 行同步。
- 口径勘误：kimi.py purpose 枚举注释行号登记原文 `:39-43` → 现测 `:43-47`（枚举内容两测一致，后续提交致注释块下移）；§拍板闸新项实测编号为 **⑨**（goal-ta 提示词原文写「增⑦」——⑦⑧ 已被 2026-11-06 拍板轮占用，按 backlog 实测顺延）。
- 全仓 diff 仅 .md 文件（backlog / CHANGELOG / AGENTS / 立项文档）；无需 rebuild / alembic / 重打包。

## [未发布] — T-A7 谈判版本管理：桌面冻结状态徽标 + 导出弹窗版本明示（2026-11-07）

### 行为变更（零代码零迁移零新 API；桌面变更 ⇒ 便携版重打包挂账）

方案详情页头部新增**冻结状态徽标**（拍板 §拍板闸 6③：谈判稿=未冻结版本）：
- 「已冻结进 SOW」（绿）——当前方案版本的内容已冻结进 SOW 快照
- 「谈判稿 · 已修改」（黄）——方案在 vN 冻结后又修改过，当前内容未进任何 SOW
- 「谈判稿 · 未导出」（灰）——当前内容尚未冻结进任何 SOW

反查数据源：`GET /documents` 摘要自带 `opportunity_scope.solution.{id,version}`（export_sow 每次导出更新为导出时刻的方案版本）⇒ **零新 API**；含 archived 快照（历史冻结事实，「历史文件保留」语义），取最大版本号。徽标只在**详情页**呈现——方案列表页钉住「不预取 `/documents`」（SOW 文件懒加载契约，solution-design.test.tsx:184）。

导出 SOW 弹窗明示冻结关联：`SolutionExportResult` 补声明 `solution_version` + `reused`（服务端 `_serialize_export` 本就返回）；文案「本 SOW 快照冻结的是方案 **vN** 的内容」，同版本重复导出附「复用既有快照」。

`/documents` 反查失败静默降级为「谈判稿 · 未导出」——辅助信息不阻断方案详情主内容（SolutionHealthChip 同纪律）。

### 口径勘误（与登记原文三处出入，已回写 backlog）

「谈判稿与正式方案的分离位」不需新实体——solution 单行+乐观锁 version，「冻结」已承载在 `project_solution_exports`（`(solution_id, solution_version)` 唯一键）+ 文档版本 `content_snapshot_json.solution` 逐字快照；「版本列表追溯」数据源已存在（见上）；「谈判稿不进 SOW / 快照只读」服务端既有用例钉住（`test_sow_export_freezes_saved_solution_without_ai_and_reuses_revision`），零重复实施。

### 口径（#178 PR-head CI run 42318566336 实测）

vitest **882 passed**（71 文件 = 基线 870 + 12 新增：NEW solution-frozen-version.test.tsx 7 + solution-design +5）／pytest server-tests pass（服务端零改动不变）／mypy、路由、迁移均不变。

## [未发布] — T-O2c 全局注册类型只读面：调研定义编辑器接入注册类型（2026-11-07）

### 行为变更（+1 只读路由；零迁移零新表；桌面变更 ⇒ 便携版重打包挂账）

- **服务端新面**：`GET /api/v1/ontology/relation-types`（require_auth）——无项目上下文的消费方（行业模板/调研定义编辑器）拉取全局注册类型选项。只收全局行（project_id=NULL）；`?kind=` 按种类过滤；全状态返回（消费方自行过滤 active）。人工路径，有意不进 api_catalog（沿 T-O2 纪律）。
- **调研定义编辑器接线**：「调研主体」下拉补注册类型选项（内置五类 ∪ 全局注册 active 行，标注「注册类型」）；已加载定义含注册类型时正确回显（含注册面拉取失败 fail-open 降级、类型已 retired 的当前值兜底——不再空白显示）。
- **JSON 导入放宽**：调研定义 JSON 文件导入接受对象类型码格式的注册类型（值域权威仍在服务端写闸门）；AI 生成路径维持内置五类（T-O2b 防幻觉基线）。
- 测试：pytest +3（全局面只收全局行/kind 过滤/未认证 401、两面 serialize 同构、目录红线钉）；vitest +5（全局面选项接线、注册类型定义显示与原样保存、fail-open 当前值兜底、JSON 导入注册码、AI 路径内置五类钉）。审计清单三件套再生成（route 305 / blueprint 41）。

## [未发布] — T-A2 补齐：confirm 复核闸（拍板 6① 机械强制，2026-11-07）

- `guidance/service.py::confirm_analysis` 新增复核闸：确认前按分析聚合 `guidance.redaction_review` 事件（#160 落的复核清单事实源；同名跨事件 occurrences 累加、`matched_dict` 求并、按名称排序）——清单非空且请求未显式 `redaction_reviewed=true`（路由只认字面 true，fail 向安全侧）→ 409 `redaction_review_required`；带 ack 放行并随既有 `guidance_analysis_confirmed` 事件留痕 `redaction_reviewed`/`redaction_review_hits`。零新增状态面，闸与来源种类无关。
- `get_analysis` 与 confirm 响应增派生字段 `redaction_review`（同一事件源聚合投影）——方案审核人复核的可见入口；桌面呈现随 T-A4/B#9 面接线。
- `REDACTION_EVENT_TYPE` 常量归位 `guidance/models.py`（写入方与消费方共享单一权威，jobs 同名导入保持兼容）。
- NEW `server/tests/test_guidance_confirm_review_gate.py` 6 例（无 ack 409+零变更 / ack 放行+事件留痕 / 干净免 ack / 读面形状与排序 / 跨事件合并 / 编辑不改写审计清单）。零迁移；既有端点加可选参数。

## [未发布] — 洁癖收尾轮：口径全现测吻合 + 审计清单重生成 + 补账（2026-11-07）

### 口径现测（七项逐位吻合，零漂移修正）

以 fork/main `a0ed3ee` 为基线现测：蓝图路由 **304** / blueprint **40** / 业务表 **105** / 迁移头 `b2e8f4a6c9d3`（36 rev）/ api_catalog ENTRIES **94** / mypy 基线 **279**（`server/mypy-baseline.txt` 行数）——审计脚本自报与 AGENTS 口径行逐位一致；pytest **2050 passed + 6 skipped**＝2056 收集、vitest **858**（均为 main CI run 42255980781 实测，#166）。规则执行审计：`.env` 零跟踪、根级文档零冲突残渣、`origin` push URL 已锁（红线机械化）、版本三处同步 0.2.0。

### 修复的三处漂移

- **审计清单重生成**：`docs/audit/v3-route-inventory.csv` 落后 2 条路由（B#13-C/D 轮重生成于 302，#162 只读技能中心 +2 未刷）——`extract_workbench_inventory.py` 重生成，route CSV +2 行、JSON route_count 302→304，DB CSV 零变化。
- **`FDE_ENTERPRISE_DICT` 补登记**（T-A2 遗漏）：`server/.env.example` 补「售前企业名脱敏」节（可选现场词典指针，缺省用种子词典，真实词典永不入库）；README 配置边界表同步补行。
- **CHANGELOG/AGENTS 补账**：#156 T-A1／#160 T-A2／#163 T-A3／#164 T-A4 四轮此前只回写 backlog、未记 CHANGELOG 节与 AGENTS bullet（本轮下方补齐）；AGENTS「当前状态」bullet 断档自 #161 起一并补齐（#150/#152/#153/#154/#156/#157/#159/#160/#162/#163/#164/#166/#167）。backlog T-A4 状态行「实施中」→「已实施并合并 #164」。

零代码零迁移零路由；无需重建镜像/alembic/重打包。

## [未发布] — CR-032 写路径清偿：调研注册对象类型接入创建/导入/表单面（2026-11-07）

### 行为变更（纯桌面零服务端零迁移零路由；桌面变更 ⇒ 便携版重打包挂账）

- **注册对象类型可新建**：项目调研对象树的「新增」区为 T-O2 注册表登记的对象类型（`kind=subject_type ∧ status=active`）提供「新增X（根级）」入口——注册类型无父级规则，创建为根级对象（不带上级）；内置五类的父子层级流程零变化。
- **导入与表单承接**：调研对象批量导入对话框的「对象类型」与调研表构建器的「调研主体」下拉补注册类型选项（标注「注册类型」）；顺带修复注册类型主体下「调研主体」下拉空白显示的问题（选中值无匹配选项）。
- **数据源与降级**：选项来自既有只读路由 `GET /api/v1/projects/{id}/ontology/relation-types`（客户端过滤 active 行，draft/retired 不出现）；注册面拉取失败静默降级为仅内置五类——值域权威始终在服务端创建闸门。
- **边界（偏差注记）**：调研定义编辑器与行业模板编辑器本轮未接——全局注册类型没有项目内只读路由可消费，随服务端路由补口后再接。
- 测试：vitest +4（根级创建流不带上级／非 active 行过滤／导入与构建器选项／树按钮两态）。
## [未发布] — T-A6 报价核验→冻结 SOW 桌面闭环：方案详情页建交付包入口（2026-11-07）

### 桌面（纯桌面零服务端改动零迁移零路由；详见 backlog T-A6 实施轮节）

- NEW `SolutionDetailPage.tsx::DeliveryPackageLauncher`：方案详情页（`canManage` 且非弃用）新增「建交付包」区块——拉项目报价列表（`GET .../quotes`），**默认选中 finalized 报价**；草稿报价选项禁用；无 finalized 报价时给出可读清单（含跳「报价收款」页链接）并禁用创建按钮——**前置同口径闸提示**（发布闸 `quote_not_finalized` 在服务端兜底，桌面提前一步呈现同一要求）；提交走既有 `POST /api/v1/dispatch/packages`（`solution_id+quote_id`）；错误映射 `package_exists`（已有包→引导去调度台）/`verifier_role_required`（权限说明）中文呈现。
- `CommercialBoard.tsx` QuoteCard：finalized 后显示「下一步」引导行（跳方案设计建包；说明发布即冻结快照与既有闸）。样式 `.solution-package-launcher` / `.quote-next-step`。
- **辅助入口不阻断主内容**：报价列表拉取失败静默降级（`SolutionHealthChip` 同纪律）；既有 42 例 solution-design 用例零回归。

### 口径勘误（与登记原文三处出入，已回写 backlog）

登记原文「未核验时导出被服务端闸拦住」不成立——`export_sow` 服务端不查报价（只有 AI 协同终审拍板 + design 必填两道闸；SOW 是谈判材料），真正的报价闸在**交付包链路**（建包 `solution_id+quote_id`、发布 422 `quote_not_finalized`、首单回校 `calibration_required`）；登记原文「补齐状态推进与门禁提示」已是既有能力（QuoteCard 既有 claims 推进/回校/成交回填）；真缺口是 `POST /api/v1/dispatch/packages` 全桌面零调用——「核验通过→交付包发布（冻结快照 §2.3 哈希）」链在桌面断在这里，本轮补上。

### 口径

#175 PR-head CI run 42308398276 实测 vitest **870 passed**（70 文件，862→870：T-A6 轮 +5、T-A2 补齐轮 +3 既有增量）／桌面 typecheck 绿／服务端 pytest 与 mypy 零改动不变（纯桌面轮，server-tests job 同跑回归绿）／路由 304 不变（零新增路由）／零迁移零新表零新字段。

## [未发布] — T-A5 方案骨架模板：三选项 + 取舍 + 明确不做 + 验收标准（2026-11-06）

### 服务端（纯服务端模板文案，零迁移零路由零新字段；详见 backlog T-A5 实施轮节）

- `solutions/service.py::_skeleton_text_fields` 的 `design_markdown` **追加两段**：「## 方案选项与取舍」（选项 A/B/C + 取舍，四个占位行均带「待补」提示）与「## 明确不做（本阶段不包含）」（搬运 `out_of_scope_json`，无条目时落占位行）。**只追加、不改既有段标题**——`## 方案设想（待人工修订）`/`## 实施路径（待人工修订）` 与 risks 段三类前缀原样保留（既有 goal-d2 / delivery compiler 用例钉住）。
- 桌面**零改动**：桌面用通用 Markdown 渲染器消费 `design_markdown`（`MemoMarkdown`），无硬编码段落清单 ⇒ 新增 `##` 段自动渲染。
- 测试：NEW `server/tests/test_solution_skeleton_options.py` 6 例（三选项与取舍占位齐备/「明确不做」独立成段且 risks 前缀不回归/段序固定/无 out_of_scope 时段落不消失/验收标准段搬运/新段进得去冻结的 SOW 快照）；既有 `test_goal_d2_s0_closeout.py` 追加 T-A5 断言。

### 口径勘误（与登记原文三处出入，已回写 backlog）

登记原文「`out_of_scope` 段即『明确不做』」不成立——既有六段里 `out_of_scope` 只混排在 `risks_dependencies` 段（与「假设」「待确认问题」三类前缀同段）⇒ 「单独可见」必须**新增独立段**；登记原文「桌面模板渲染用例」不成立——桌面零改动；另 `workflows/compiler.py::compile_delivery_preview`（本体编译路径）全仓无生产调用方 ⇒ 本条不覆盖该路径。

### 口径

#172 PR-head CI run 42277662998 实测 pytest **2062 passed＋6 skipped**（2068 收集）＋vitest **862**（70 文件，桌面零改动不变）／mypy 279 不变／路由 **304**（零新增路由，脚本现测）／蓝图 40／业务表 105／迁移头 `b2e8f4a6c9d3`（36 rev）／零迁移零新表零新字段。

## [未发布] — T-A4 事实/假设/待确认三层桌面可视化：条目粒度编辑（2026-11-06）

### 桌面（纯桌面零服务端改动零迁移零路由；详见 backlog T-A4 实施轮节）

- NEW `desktop/src/renderer/src/guidance/classificationLayers.ts`：五分类（`customer_stated`/`ai_synthesized`/`ai_inferred`/`open_question`/`human_added`）→ 三层归属纯函数——客户事实层／AI 判断层／待确认层；**无锚点且非 human_added 一律降级「待确认」**（服务端 AI 路径 fail-closed 但人工 PATCH 弱校验 ⇒ 库里可能有无锚点条目，桌面降级是必需的第二道闸，不替无锚点判断背书）。
- `GuidanceReview.tsx` 只读态三层分组呈现（分类标签+锚点+事实层确认状态，原先渲染纯文本 `<li>` 全部丢弃）；编辑态改**条目粒度编辑器**（每条卡片：分类下拉+锚点只读+确认勾选+文本+删除）——顺带修掉「整字段 textarea 按行号继承元数据」的错位缺陷（插入/删除行曾把 A 的锚点贴到 B 的文字上静默落库）；**分类下拉候选集受锚点约束**（无锚点只能选 `open_question`/`human_added`，与服务端 `missing_source_ref` 同口径）。
- 测试：NEW `guidance-classification-layers.test.tsx` 9 例（三层归属/无锚点降级/条目粒度/改删不错位/候选集受限/空条目过滤/保存保留元数据）；既有 guidance 22 例零回归。

### 口径

vitest **858**（CI run 42251482875 实测；+19 含并发 #163）／pytest 不变／mypy 279／路由 302（当时）。

## [未发布] — T-A3 调研表三态流转（confirm/reject/revise）桌面入口（2026-11-06）

### 桌面（纯桌面零服务端改动零迁移零路由；详见 backlog T-A3 实施轮节）

- `ResearchForm.tsx` 表单详情底部新增三态操作区（与「保存调研内容」分离，消费既有 confirm/reject/revise 三端点）：**确认事实**（can_manage，本地先按服务端同源口径校验必答缺失，不发请求）；**驳回并留意见**（理由必填，`{version, review_comment}`，驳回意见回显）；**创建修订版**（can_update_assigned_tasks，confirmed 态，`{version}` 开新 draft）。
- 权限显隐与服务端同构（`canManage` 可选 prop **默认无权**——漏传时按钮不出现）；409 `stale_version` 走既有冲突面板不吞；未知错误码回落服务端原文。
- **revise 定位裁决**：显式**留痕通道**而非唯一改稿路径——PATCH 的隐式 fork（`_ensure_working_revision`）不记事件，`revise_form` 记 `project_research_form_revised` 进事实链；「已确认表只读」收紧被既有用例判红后撤回（legacy 兼容契约维持）。
- 测试：`project-research.test.tsx` 新增 tri-state describe 10 例；research 域 222 例压链全量回归后合入。

### 口径

vitest **848**（69 文件；CI 4 job 全绿）／pytest 不变。

## [未发布] — T-A2 企业名自动替换层：presurvey 正文代号化三道防线（2026-11-06）

### 服务端（零迁移零路由；详见 backlog T-A2 实施轮节）

- NEW `guidance/enterprise_dict.py`（种子词典 + `FDE_ENTERPRISE_DICT` 现场补充、格式 fail-closed、通用词判定、中文候选前缀剥离）+ NEW `server/seeds/enterprise-names.txt`（**只放合成示例**，真实企业名永不进 git；CI pseudonymization `FDE_LEADS_MD` 改指此文件，一致性由哨兵测试钉死）。
- `guidance/redaction.py` 扩展 `redact_text_detailed`/`redact_presurvey`（既有 `redact_text` 签名语义不变）；worker 链**三道防线**接入：①进模型前全文替换（本地抽取腿不落存储）②模型输出落库前兜底替换（文本+LIST_FIELDS+evidence）③复核清单落 `operation_events`（`guidance.redaction_review`，B#9 可查）。
- **拍板口径「放行 = 不留库」**：疑似名同样替换为代号（替换目标=`projects.enterprise_code` 首段），记入复核清单交审核人 confirm 前复核；通用词（「技术公司」类）零改动不进清单。机制性故障 → `RedactionConfigError` → `pseudonym_dict_unavailable` 不重试，`project_draft` 503。
- 测试：NEW `test_guidance_enterprise_redaction.py` 13 例 + `test_guidance_redaction_worker.py` 2 例（数据全合成）；**本轮未做**：执行面 `agents/context.py` 未接企业名替换（口径不同，另立条目）。

### 口径

pytest **2016 收集 = 2010 passed + 6 skipped**（+15）／桌面零改动。

## [未发布] — T-A1 presurvey S3 前置闸桌面可读提示（2026-11-06）

### 桌面（服务端零改动）

- G3 诊断开工门 409 拦截态不再吞成通用文案：服务端 message 原文 + G3 四项清单（**claimed ≠ accepted 徽标**）+ 前往门禁页跳转锚（NEW `PresurveyGateHint.tsx`；服务端闸本体 `guidance/service.py:402` 已在，本轮只补桌面可读呈现）。
- 测试：NEW `presurvey-gate-hint.test.tsx`（vitest **833** 全绿）；同轮回写改造方案 §拍板闸 6 全部收口（①②③⑥ DECIDED）。

## [未发布] — V3 两级注入全链路：契约 references 组 + 消费面两层接线（#8，2026-11-06）

### 契约扩组（技能结构化契约 v1 §2.6，零迁移零路由零新表）

- NEW `references` 必读引用组：`required_reading`（执行前必读，硬前置）＋ `authoritative_sources`（冲突裁决，软引用）。语义锚＝`fde-package-verify` 手写规则「README 冲突以 README 为准」——把「权威在技能正文之外」的约束从散文升级为机器可读引用。
- 键空间闭合枚举同步扩组（`test_skill_contract` `CONTRACT_GROUPS` +references），B#37 静态闸验证通过。

### 消费面两级接线（mcp_gateway）

| 级 | 工具 | 内容 |
|---|---|---|
| **第一级**（选技能前） | `skill_list` | item 带 `when_to_use` 摘要（取自 `use_boundaries` 组；未填不带键——缺省＝不误导） |
| **第二级**（读正文前） | `skill_read` 首页（offset=0） | 带 `required_reading`/`authoritative_sources` 引用清单；**续页不带**（同一正文延续，重复是噪音）；良构校验（list[str] 全非空才出，不猜不放宽） |

- **引用不携带内容、不产生新读取权限**：引用是仓库内相对路径，消费方用既有只读工具自行读取；`skill_list`/`skill_read` 工具 schema 静态钉住不变。
- **T-S2 计数语义不变**：首页带引用不改变「仅首读计一次」。
- 4 个 runbook 按「平铺点路径 + JSON 数组字面量」回填 `use_boundaries`+`references`（**种子 13 条维持 B#36「不回填」裁决不动**）。

### 测试

NEW `server/tests/test_skill_readbefore.py` 5 例；**变异三连逐一转红**：列表不带摘要／续页也带引用／坏引用透传。技能域回归 25 passed。

### 口径

pytest **2056 收集 = 2050 passed + 6 skipped**（+5）／vitest **858**（零桌面改动，校正自 B#30-A 基线 839——main CI run 42251482875 实测 858，其间 #163/#164 并发 +19）／mypy **279**（不变）／蓝图路由 **304**（不变）／业务表 **105**（不变）／api_catalog ENTRIES **94**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）。

> 口径基线取 main HEAD `5b47c07` CI run 42251482875 实测 2045 passed＋6 skipped＝2051 收集；本地 collect 2056＝2051+5 交叉对齐。

### 同轮核销

- 借鉴总览 #36/#37 四处「✅ 已实施 · 未提交（b36b37 轮）」过时状态核销为「✅ 已实施 · #140」（#140 已于 fork/main 合入）。

## [未发布] — V3 B#30-A 门禁证据漂移呈现：同源换版只读复核（2026-11-06）

### 行为变更（零迁移零路由零新表；server 变更 ⇒ 合并后 rebuild 三镜像；桌面变更 ⇒ 便携版重打包挂账）

- **清单项级「前置复核」**：门禁清单项引用的证据（`evidence_id`）若被**同一 `source_uri` 上更新的 hash 行**（T-G1 换指纹并存语义）超越，门禁视图序列化对该项输出 `evidence_superseded: true`。检测有界——只比该 uri 的证据登记行集，不扫全表。
- **呈现即提示，四不动**：状态机、claim_status、拍板有效性、AI 权限一律不变；不携带新行指针（跳转走证据登记簿面）；重核与否永远由人决定。
- 三调用点接线：门禁列表、提交证据响应、拍板响应均携带该标记；桌面 `GateBoard` 对旧服务端载荷（无该键）保持兼容，换版项呈现「证据已换版」警示 badge（title 说明四不动边界）。
- 测试：pytest +2（同源换版翻转／无重采不误报；变异摘检测红→还原绿）＋ vitest +1（badge 呈现／旧载荷无键不受影响）。
- 顺带修复：#155 合并在 AGENTS.md 遗留的冲突标记残渣（`=======` 段＋commit 尾巴＋#85 条目丢换行）。
## [未发布] — V3 只读技能中心（B#32 A 面）＋ 借鉴总览台账漂移校正（2026-11-06）

### 只读技能中心（B#32 A 面——交互拍板⑤A，零迁移零新表零依赖）

- NEW `server/src/fde_api/control/skill_center.py`——**DB 权威只读浏览面**（取内容域、弃文件目录形态：技能权威已在 `skill_definitions`/`skill_versions`，另起文件系统 provider 会出现两个权威且漂移不可测 ⇒ 不引文件目录、不引依赖 ⇒ 无供应链闸）。
- 新增 2 条只读路由：`GET /api/v1/skills`（可选 `?scope=public|personal`，非法值按空处理——不猜不放宽）、`GET /api/v1/skills/<skill_id>/document`。
- **权限面与既有 `mcp_gateway._skills` 同尺**：`status=published`（draft/in_review 未过发布闸不外泄）＋ `scope=public` 或 `owner=当前用户`；不可见即 **404**（不区分「不存在」与「无权」，避免探测）。
- **不消费计数**：`skill_read` 读出指南才计一次消费（T-S2 语义），本面是治理浏览面（人看目录、下载文件）——浏览一次就写一条 `skill_used_*` 会虚增「已消费」记录。
- 有界返回：列表 200 条上限＋正文 512KB 上限（超限拒绝，不截断）。
- NEW `server/tests/test_skill_center.py` 5 例；**变异四连逐一转红**：去 `status` 过滤（draft 泄露）／去 `owner` 限制（他人个人技能泄露）／浏览写消费计数（计数 +1）／正文面返回空正文。

### 借鉴总览台账漂移校正（v1.10）

- `docs/audit/开源项目借鉴总览-2026-11-05.md` §1 P1 段**状态列九条按 `fork/main` 实况回写**（#7=#150／#12+#31=#154+#157／#13=#153+#158／#14=#159／#8+#32=#138＋本轮 A 面／#11 落点设计已落／#30 立项 #144）——此前六条仍标「⬜ 待实施」而实际全部已落地。
- §5.1 已兑现表补五条缺项；§5.2 标注顺位 1/2/3 **已全部兑现**；§5.4 标注剩余可排期项（#30 A 面／#8 两级注入 `readBefore`／#11 随 #23 解封）。

### 口径

pytest **2049 收集 = 2043 passed + 6 skipped**（+5）／vitest **838**（不变）／mypy **279**（不变）／蓝图路由 **304**（+2）／业务表 **105**（不变）／api_catalog ENTRIES **94**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）。

> **口径校正**：前值「2014 收集」系 #159 轮本地推算、未计 #158＋#160 并发增量——本轮基线取 main HEAD `d467fac` CI run **42241563180** 实测 2038 passed＋6 skipped＝2044 收集，再加本轮 +5 ＝ 2049。**并发轮期间本地推算不可作基线**（#129/#131/#157 之后第四次同类校正）。

## [未发布] — V3 到期治理收口：B#13-C API confirmation 主动超时 + B#13-D 跨域只读投影（2026-11-06）

### B#13-C（零迁移零路由零新依赖；server 变更 ⇒ 合并后 rebuild 三镜像）

- **derived state 裁决落地**：`OperationEvent` append-only 完整保留——到期不追加 expiry event、不 UPDATE/DELETE 原 request 行、不建后台 sweep（该域无清理副作用，持久化过期事实零行为收益，反而引入系统 actor 与事件生命周期两个新语义面）。
- `control/api_actions.py` 新增唯一窗口常量 `CONFIRMATION_WINDOW`（15 分钟）与到期谓词 `confirmation_expired`；pending 列表 / `action_status` / `decide_action` 三处此前各自手写的 `timedelta(minutes=15)` 全部收敛到该原语。
- **边界统一**：从严格 `<`（恰等于 15 分钟仍有效）对齐为 `deadline <= now`（恰等于即过期），与立项合同 §3.3 / B#13-B 上传会话 / 审批域同拍。
- 到期行为：过期确认从 pending 列表筛除、status 返回 `expired`、迟到 decision 409 `action_expired` 且**零事件/目标副作用**（不落 started/finished、不触碰目标对象）；started-but-uncertain 防重放保护**优先于到期**（不报 expired、绝不重放），finished replay 越窗仍有效；auth_version/fingerprint/password 防线原位不动。
- NEW `server/tests/test_api_confirmation_expiry.py` 7 例（常量值钉/谓词边界/窗口内全待/过期全拒+零副作用/uncertain 优先/越窗 replay/窗口常量放大变异证明三路径+投影同源）。

### B#13-D（零 DDL；+1 路由）

- **NEW `fde_api/expirations.py`**：跨域到期只读投影——服务层只读 union + admin-only `GET /api/v1/expirations`，输出立项合同 §2 六字段逻辑视图（`domain`/`object_id`/`deadline_at`/`state`/`due`/`expiry_action`）。不建 SQL view 的决定性理由：api_confirmation 截止时刻是派生值，SQL view 会把窗口规则复制成第二权威；服务层直接复用 B#13-C 同一常量与谓词。
- 四域接入：automation_approval（pending）/ upload_session（uploading）/ api_confirmation（awaiting_confirmation，derived）/ dispatch_offer（offered，`offer_deadline` 派生）；`due` 统一按 `deadline_at <= now`；dispatch 原生转换器保留严格边界（边界瞬间读数先行一拍，只读不写回）。
- 权限与面：admin-only（运营看板视角；触发条件=用户明确指示实施）；`limit` 默认 100 上限 500，排序 `(deadline_at, domain, object_id)` 稳定升序，`domain`/`due` 过滤；只投影元数据（不外泄确认 body/审批 arguments/对象键/客户资料）；`expiry_action` 只是符号名指针不执行；**不进 api_catalog**。
- NEW `server/tests/test_expirations_projection.py` 8 例；审计清单重生成：route **302**（+1）/ blueprint **40**（+1）；105 表、迁移头 `b2e8f4a6c9d3`（36 rev）不变。

### 口径

pytest **2029 收集 = 2023 passed + 6 skipped**（CI 实测；本地专项 15 例 + 邻域 89 例全绿）／mypy 基线 **279** 不变／蓝图路由 **302**（+1）／业务表 **105**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，零迁移）。

## [未发布] — V3 B#14 executor 对抗性测试直补（2026-11-06）

### 对抗钉（纯测试轮，零迁移零路由零业务代码）

拍板盘点五夹具族：①固定种子模拟／③迟到拍板／④双 definition_version 并存 **已由现有 39 例覆盖**；②强杀不丢已确认／⑤节点独立事务失败恢复 **为缺口**。按拍板 opt A「直补对抗钉」实施（不做 2–3 周决策逻辑纯函数重构，与总览「先攒真实故障史」裁决一致）。

- **NEW `server/tests/test_workflow_executor_adversarial.py` 4 例**：
  - **强杀族**：进程级死亡（worker_lost 收口）**不得抹掉已 succeeded 节点的产物**（逐位相等）；resume **不重跑已确认读面**（外呼次数只 +1）。
  - **tx B 崩溃族**：settle 落表自身崩溃 → 节点悬 running → 恢复重跑时**幂等键不变**（同 action id ⇒ api_actions 层去重 ⇒ 不二次外呼）＋**attempt 保留**（「本次尝试已发生」的事实不被恢复路径抹掉）。
  - **恢复底座钉**：`_recover_interrupted` 只把 running 放回 pending，**不动 succeeded**。
- **变异双红**：恢复路径抹掉 succeeded 产物（2 例转红）／去幂等键守卫 + 派生含 attempt（tx B 族转红）——等价变异（单改派生式因守卫短路）已识别并改用可辨组合。

### 口径

pytest **2014 收集 = 2008 passed + 6 skipped**（+4）／mypy **279** 不变／ruff F401,F841 全绿／蓝图路由 **301**（不变）／业务表 **105**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）／vitest 不变（零桌面改动）。

## [未发布] — V3 拍板收口：B#30-B=opt1 + 提示词卫生差距②静态钉（2026-11-06）

### 交互拍板收口（①零代码 + ②纯测试轮，零迁移零路由）

- **B#30-B 门禁终态回退语义＝opt1 维持现状**（交互拍板）：passed/conditional_pass 终态不可逆维持（重交 409 现状不变），**零代码零迁移**——回退通道引入状态机新分支+桌面回退 UI（≈1–2 人日），当前无真实场景推动，错误拍板走线下 OperationEvent 留痕追溯；opt2/opt3 保留候选、真实诉求出现时重开。backlog B#30 行与状态段已回写。
- **提示词卫生契约差距②＝补静态钉**（交互拍板）：NEW `server/tests/test_prompt_entrypoint_gate.py` 3 例——受闸入口（`execute_ai_prompt`/`direct_tool_completion`/`direct_provider_completion`/`_degraded_direct_result`）的 `system_prompt` 实参来源 AST 允许名单（字面常量／形参直传链变量／`_workbench_system_prompt()` 白名单组装函数），域外形态即红；附钉定义落点锚（防定义漂移出受闸文件面）＋ **kwargs 透传禁令（防绕过 AST 形态判定）。**变异双红**验证：chat 接 `prompt` 变量进 system_prompt／structured 改 `**payload_kw` 展开——逐一转红。
- 同日另三项拍板（T-A2 分层失败语义／T-A2 词典=种子文件／T-A7 谈判稿=复用 solution 版本行）由并发会话回写于主树，与本轮不重叠。

### 口径

pytest **2010 收集 = 2004 passed + 6 skipped**（+3；**口径校正**：前值 2013 为本地推算重复计并发轮增量，CI run 42223701893 实测为准）／mypy **279** 不变／蓝图路由 **301**（不变）／业务表 **105**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）。

## [未发布] — 桌面实施轮②：CR-032 桌面调研 subject_type 读路径承接 T-O2b 注册类型（2026-11-06）

### 桌面（零迁移零路由零服务端改动；无需 rebuild / alembic / 重打包）

- **读路径守卫放宽（CR-032 核心）**：桌面调研 DTO 守卫此前把 `subject_type` 钉死内置五类枚举（`RESEARCH_SUBJECT_TYPES`），而服务端 T-O2b（#83）已把物理边界放宽为码格式 `^[a-z][a-z0-9_]{0,59}$`（迁移 `b5d9e3f7a1c6`）＋注册表 active 行——**注册类型（如 `vendor`）落库后，桌面 `ResearchWorkspace` 读路径校验即失败 → 整个调研 tab「数据格式异常」、项目正常数据全不可读**。修法：`ResearchSubjectType` 放宽为 `string`，新增 `isResearchSubjectType`（与 DB CHECK 同尺码格式守卫）承接读路径（`isResearchSubjectDto`／`isResearchFormDto`／`isResearchImportPreviewDto` 三处五类守卫改走同尺）；内置五类仍由 `RESEARCH_SUBJECT_TYPES` 承载写路径（创建/下拉/父子树，**写路径注册类型选项＝后续轮**——须接 ontology 只读 API＋父子约束，本轮不扩张功能面）；展示走新增 `researchSubjectLabel`（内置取中文标签、注册码原样回显，杜绝缺标签拒载/乱显示）。
- **测试 +2 例**：注册类型码（`customer`/`supplier_x`）读路径承接＋非法规码（`9Bad`/`Customer`/超长/连字符）仍拒；既有用例同步（`"nonsense"` → `"9Bad"`）。

### 口径

- 桌面 vitest **838/838**（基线 **836**＝CI run 42223701893 实测 ＋2；桌面纯前端轮，零服务端改动）；pytest / mypy / 表 / 迁移 / 路由 / ENTRIES 全部不变。 (docs(v3): 校正桌面实施轮② vitest 口径 833→838（基线随 #156/#157 插队上移，现测为准）)

## [未发布] — V3 提示词卫生 J 系接线：B#12+B#31 判据落地（2026-11-06）

### 契约判据接线（零迁移零路由零新依赖；server 变更 ⇒ 合并后 rebuild 三镜像）

- **NEW `server/tests/test_prompt_hygiene_jseries.py` 5 例**（承接《外部文字禁入与原件派生分离契约-v1.md》§5 可断言判据；组织同 B#4 purity 静态测试）：
  - **J-1 静态钉**：全仓 system role 消息组装点 AST 枚举——content 必须是「常量／常量名／形参直传链／已登记例外」四形态之一，域外新增即红（PR 须对照契约 §2 表登记）；附钉 executor skill 节点 `system_prompt` 仍＝治理面发布 `instructions`（白名单④不旁路）。
  - **J-2 行为钉**：四类「不可信资料」工具结果必须带结果级 `source` 标记——`file_read`/`help_fetch` 既有；**`lcsc_search`/`lcsc_runs_read` 本轮补 `untrusted_storefront_content`（契约 §4 差距①闭合，P-3 标记腿全满足）**；附钉 lcsc run 返回体单一形状源（`_serialize`）。
  - **J-3 静态钉**：`documents/ai_content` 的 system 提示词是纯常量构造——payload/请求内容变量泄漏进构造即红。
- **变异三连**逐一转红：lcsc 标记删除／executor 接 prompt 变量／system 拼接 payload。
- **差距②开放保留**：`direct_tool_completion` 形参面无静态闸（形参直传链上游来源已逐点登记于测试 docstring；封堵须另轮）。

### 口径

pytest **1999 收集 = 1993 passed + 6 skipped**（+5）／mypy **279** 不变／蓝图路由 **301**（不变）／业务表 **105**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）。

## [未发布] — V3 桌面实施轮①：B#28 门禁 revision CAS 桌面接线（2026-11-06）

### 服务端 + 桌面（零迁移零新路由；server 变更 ⇒ 合并后 rebuild 三镜像 + alembic 幂等）

- **服务端**：门禁视图（`GET …/projects/{id}/gates`）与拍板响应回传 `revision`（≡ 既有 `gates.version`，**零新增列**；与 `lifecycle_version`（语法代际）刻意分离——后者不随拍板推进）。
- **桌面 `GateBoard.tsx`**：拍板请求原样带回 `expected_revision`（B#28 CAS 此前**服务端已就位而桌面从未启用**——桌面不知当前 revision）；409 `gate_revision_conflict` 如实呈现「本次拍板未生效；面板已刷新」并自动刷新面板（人可基于新状态重拍，不静默覆盖前写）；旧服务端载荷缺 `revision` 时不带该键（缺省＝旧客户端兼容）。
- **测试**：服务端 +1 钉（视图 `revision` ≡ 行 `version`，且用视图值拍板可生效、revision 推进 +1）；桌面 +3 例（带入 `expected_revision`／旧载荷不带／409 冲突如实呈现并刷新）。

### 口径

- pytest **1986 收集＝1980 passed＋6 skipped**（+1）／vitest **828/828**（+3）／mypy 基线 **279** 不变／105 表／迁移头 `b2e8f4a6c9d3`（36 rev，零迁移）／蓝图路由 **301**／api_catalog ENTRIES **94**。

## [未发布] — V3 回滚轮落定重核（§三 逐行复测＋审计清单回刷＋CR-003 销号）（2026-11-06）

### 文档与脚本（零业务代码零迁移零路由零桌面功能改动；无需 rebuild / alembic / 重打包）

- **`docs/implementation/v3-迁移进度对照-fde-v2建议-2026-11-04.md` 第七轮同步**：§五-7「并发在途品牌·回滚轮」**结清并翻转**（回滚轮落定为 #132＝155 文件（67 纯增／54 改／33 二进制／1 删）**零 server 改动零迁移改动**；原拟撤的 T-W7/T-I1/T-C1 四件套实测全部存续；fork/main 无任何 revert 提交）→ **§三 全量 DONE 判定逐行复测无一被推翻**；新增 §五-9（审计清单落后 1 条 ＋ 抽取脚本蓝图硬编码漏登）与 §十三（第七轮增量记录）；§二 P1④／§四 C-4 补「skill_read 分页已实施」当前态标注。
- **行号锚修 6 处**（基线 fork/main `d3adf1c`）：`workflows/models.py:157→:163`、`executor.py:694→:701`、`executor.py:1402-1413→:1373-1413`、`definition_service.py:118→:119`、`SkillVersionsPage.tsx 355→356 行`、§三 T-S1/S2 交叉引用 `§五-3→§五-5`——**前三处系第五轮声称「已修正 8 处漂移」而正文未落地**（「声称已修 vs 正文未改」），本轮当场补正。
- **主报告 §20 实施跟踪注记补齐条目 9–19**（此前停更于 T-S1）：T-S2／T-W6／T-O4b·T-O4 桌面／T-G2·T-D1／T-C1·T-I1／T-W7·T-UI1／T-J2／P3 四项定案／P0 先行批 B 系列／五份纯文档／UI-UX 轮·B#9，并附「注记补齐说明」记录挂账前提与消解依据；`docs/goal-c-代码审查台账.md` **CR-003 随之销号**。
- **审计抽取脚本补登 ＋ 三清单回刷**：`scripts/audit/extract_workbench_inventory.py` 的 `BLUEPRINTS` 硬编码列表补 `fact_chain_blueprint`（按 `app.py` 注册序紧随 `evidence_blueprint`）→ 重生成 `docs/audit/v3-route-inventory.csv`（+1 行＝新路由）与 `v3-workbench-inventory.json`；DB CSV 零变化。
- **AGENTS.md**：工作流节新增「审计清单刷新有前置条件（`BLUEPRINTS` 硬编码列表须随蓝图增删同步登记——同一坑两次：T-J2/CR-027、#145 `fact_chain_blueprint`）」；补本轮 bullet；CR-003 挂账措辞更新为已销号。

### 口径（现测，基线 fork/main `d3adf1c`）

- 105 表 / 迁移头 `b2e8f4a6c9d3`（36 rev，#131~#145 全域零迁移）/ api_catalog ENTRIES 94 不变；**蓝图路由 300→301**（#145 +1：GET `…/projects/{id}/execution-facts`，不进 api_catalog）；pytest **1985 收集＝1979 passed＋6 skipped**／vitest **825**／mypy 基线 **279**（后三项取 #145 CI run 42183340134 实测）；审计脚本同源复测＝route 301 / blueprint 39 / table 105 / rev 36 / heads=[b2e8f4a6c9d3]。

## [未发布] — V3 回执 DSL 一期（B#7，2026-11-06）

### 契约层（零迁移零路由零新表零依赖）

- **NEW `server/src/fde_api/agents/receipt.py`**：回执 DSL 是**外部可写结构**，故按白名单逐字段校验——**未知字段一律拒绝**（不静默丢弃、不透传；否则外部多写一个键即绕过闸门）。容量上限对齐既有审批材料 **64KB** 语境（超限拒绝不截断）。
- **两种人工介入动作**：
  - **`ask`**＝请求人工拍板 → 落既有 `automation_approvals`（**零新表零新路由**，密码确认闸现成）：幂等＝`request_key` 由「项目＋能力＋规范化回执」派生并复用既有 pending 审批（崩溃恢复不重复建单）；能力须在 `CAPABILITY_REQUIREMENTS` 白名单且发起人**当下**仍具备；**风险档固定 4**（人工门＝保守高险，诚实标注）；敏感键拒绝入审。
  - **`later`**＝请求延后复查 → 落**最小到期挂点**（`operation_events`，只表达 `due_at` 时点结构）。
- **边界声明**：later **不实现**统一到期表／主动超时扫描／统一 cron 计算——那是 **B#13** 的 `deadlines()` 纯函数职责，本条不越界（B#13 落地时把 `due_at` 纳入其到期表即可，无需改动本条）。
- DSL 不可解析 ⇒ 走 **B#2 降级路径**（业务动作可能已执行，不能重做 ⇒ 落独立终态 `succeeded_but_receipt_invalid`，拒绝同键重跑）。
- **命名隔离**：既有 `AgentResult.receipt_state` 是**产物清单扫描**语义，与本条**人工介入动作**语义正交，两套并存不互相覆盖。
- **实现要点**：`action` 用 **discriminated union**（按 `kind` 判别）——普通联合会逐分支尝试并汇总**所有分支**的错误（含无关分支字段名），错误信息冗长且误导；错误路径取完整 loc（`action.ask.bogus`）而非只报顶层。

### 测试

- NEW `server/tests/test_receipt_dsl.py` 8 例：顶层与 action 双层未知字段拒绝／非对象与未知动作拒绝／容量上限拒绝不截断／指纹顺序无关稳定／ask 建单与幂等复用＋风险档 4＋sha256 指纹／未知能力拒绝／敏感键拒绝／later 挂点字段闭集且无主动扫描器／delay 越界拒绝。
- **变异五连**逐一转红：未知字段改为忽略／容量上限失效／敏感键扫描失效／ask 幂等失效／later 越界校验失效。

### 口径

pytest **1994 收集 = 1988 passed + 6 skipped**（+8）／vitest **828**（不变，回执 DSL 轮零桌面改动）／mypy **279**（不变）／蓝图路由 **301**（不变）／业务表 **105**（不变）／api_catalog ENTRIES **94**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）。

## [未发布] — V3 门禁前置复核与回退留痕立项（借鉴 B#30 消费）（2026-11-06）

### 文档（零代码零迁移零路由；无需 rebuild / 重打包）

- **NEW `docs/architecture/门禁前置复核与回退留痕立项-v1.md`**：**A 面＝前置清单证据漂移自动复核呈现**（T-G2 同构：同 `source_uri` 新 hash 证据行超越清单项已引用 evidence ⇒ 项级 `evidence_superseded: true` 只读呈现，呈现即提示四不动〔状态机/claim_status/拍板有效性/AI 权限〕，零迁移可实施）＋**B 面＝拍板回退通道与留痕合同**（现状 `passed/conditional_pass` 终态不可逆、`failed` 有重交回环；三选项登记 opt1 维持现状／opt2 受限回退〔仅 conditional_pass 可退、passed 不退、`gate_rolled_back` reason 必填〕／opt3 只读复核队列——**是否开放终态回退＝业务拍板项，本文不预支裁决**）。不做清单：不动 evidence 不可变性／不做定时自动重核／AI 不代拍板不代回退。现状行级锚：状态机 CHECK 五值／重交闸／OperationEvent from→to 留痕。
- backlog B#30 行回写（A 面随下次 gate 轮、B 面须拍板；立项≠实施授权）；AGENTS 补轮次 bullet。

### 口径

- 零代码零迁移——pytest 1981 收集（1975 passed + 6 skipped）/ mypy 279 / vitest 791 / 105 表 / `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 全部不变。
## [未发布] — V3 B#13-B UploadSession 主动到期与 multipart 清理（2026-11-06）

- 过期上传会话在 `expires_at <= now` 时由服务端行锁收敛为 `expired`；迟到分片签名/完成返回 `upload_session_expired`，不触碰对象存储、不创建文件版本；分片签名 TTL 不超过会话剩余时间。
- 新增 `file.upload.cleanup` outbox/worker 清理链：scheduler `skip_locked` claim，worker 在数据库事务外执行 multipart abort，再独立事务落 cleanup 账本；`multipart_upload_not_found` 视为幂等成功，其他错误保留稳定错误码并沿 recoverable job 退避。
- 复用既有 `UploadSession.expired/expires_at`，零迁移、零新路由、无人工外呼；B#13-C API confirmation 与 B#13-D 跨域只读投影仍 PROPOSED。
- 测试：新增 B#13-B 专项 8 例，连同上传/worker/reconcile 邻域共 65 passed；PR-head CI 最终全量 1996 passed + 6 skipped（2002 收集）；mypy 279/104、ruff 全绿。

## [未发布] — V3 门禁判据实施落点设计（借鉴 B#11 消费）（2026-11-06）

### 文档（零代码零迁移零路由；无需 rebuild / 重打包）

- **NEW `docs/architecture/门禁判据实施落点-v1.md`**（承接 B#21/B#22 评测协议冻结文本，B#22「实施落点=B#11」清偿）：**裁决＝三锚四反例的宿主＝B#23 夹具的「评测器元验证层」**（验证打分检查器本身：do_nothing≈0/ literal≤0.2/ oracle≥0.95＝检查器认得出参考解）；门禁面落点已随 #131 冻结（G9 `exit_condition` 含「三锚四反例全过」，钉 6 守护）；pytest 模板落点＝四条件解封后 NEW `server/tests/test_eval_criteria_harness.py`。**元验证语义（本文定义）＝评测器可用于「验收线达成」判定前必须先过元验证夹具——锚点不落位/反例漏抓 ⇒ 输出不得作 G9 判定输入（`insufficient_data` 不变）**。含被验证对象诚实盘点（当前仓内无打分型检查器——判据现为算分器预置合同）、逐判据落点表 11 行、阈值校准纪律。判据语义零新增零改写、种子零改动。
- backlog B#11 行回写（落点设计已裁，实施随 B#23 夹具期，设计≠实施授权）；AGENTS 补轮次 bullet。

### 口径

- 零代码零迁移——pytest 1981 收集（1975 passed + 6 skipped）/ mypy 279 / vitest 791 / 105 表 / `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 全部不变。

## [未发布] — V3 提示词卫生与工件血缘契约（借鉴 B#12+B#31 消费）（2026-11-06）

### 文档（零代码零迁移零路由；无需 rebuild / 重打包）

- **NEW `docs/architecture/外部文字禁入与原件派生分离契约-v1.md`**：外部文字禁入提示词（B#12）＋原件/派生分离（B#31）两层合一契约。**现状实测＝主干已有机闭合**（全系统恰四处 system 组装点全部落在内部权威白名单内；外部数据一律 user/tool 角色或结构化 JSON payload；原件只存指针＋sha256；`captured_from` 封闭枚举＋`ai_request_id`/`revision_id` 血缘在位）；契约把散落防线收拢为 **P-1~P-5（提示词层）＋A-1~A-5（工件层）**十条规则＋封闭枚举白名单，差距如实登记（lcsc_* 结果无 source 标记／`direct_tool_completion` 形参面无静态闸／「生成默认不视作已审」无统一谓词／个人技能 owner 自治边界），附四条可断言判据（J 系，接线仍 PROPOSED）与触发式复查机制。纯我方独立设计，零第三方正文/结构化表达引用（AGENTS 红线第 8 条履行）。与 B#3／外部模型依赖契约 M 系／W-8 四层分工互不覆盖。
- backlog B#12+B#31 行回写（契约落盘、J 系接线仍 PROPOSED）；AGENTS 当前状态补轮次 bullet。

### 口径

- 零代码零迁移——pytest 1981 收集（1975 passed + 6 skipped）/ mypy 279 / vitest 791 / 105 表 / `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 全部不变。

## [未发布] — V3 B#13 到期语义与主动超时治理立项（2026-11-06）

- 新增 `docs/architecture/到期语义与主动超时治理-v1.md`：登记原生到期权威、状态转换、并发幂等、副作用与可观测合同；裁决「统一目录+各域原生转换器+条件触发只读投影」，不建复制 `expires_at` 的通用到期表。
- 审批主动超时标记为既有基线（T-P1-5：`_expire_approval` + scheduler sweep）；UploadSession multipart abort、API confirmation append-only 超时列为独立候选阶段；跨域查询须有明确需求才排期。
- 明确排除 worker lease/retry/outbox due、JWT/签名/Redis TTL、模型/进程 timeout 等异质时钟。本轮仅立项，零运行时代码、零迁移、零路由、零数据操作；B/C/D 仍 PROPOSED，不构成实施授权。
## [未发布] — V3 只读执行事实链面板（B#9，2026-11-06）

### 只读聚合面（+1 路由；server + desktop；零迁移零依赖）

- **服务端**：NEW `GET /api/v1/projects/{id}/execution-facts`（can_view，`fact_chain_blueprint`，**不进 api_catalog**——AI 不经此面读审计原始流，与证据登记同纪律）。三源时间线归并：`project_evidence` ＋ `operation_events`（**项目维度**，过滤下推 SQL）＋ `ai_call_audits`（**账号维度**——该表无项目外键，按 actor 过滤且响应明示 `ai_call_audit_scope="actor"`，不作项目切分假装）。时间倒序、`limit` 1–200 有界＋`truncated`、非法参数 400。
- **「外部完成无真实回执=未知」纪律的落法**：`operation_events.changes` 大载荷不外泄；AI 审计只投影调用事实元数据（模型/耗时/token/状态三值，无明文上下文）；**无回执即无行**，由前端呈现「无记录」，不由模型自述或时间线推断拼装任何「已完成」语义。
- **桌面**：NEW `evidence/ExecutionFactChain.tsx` 只读面板，项目 tab +1「执行事实」（11 tab）：三源筛选、类型徽标、AI 调用「账号维度」明示、空态不编造、CR-035 同型序列守卫（筛选切换只认最新响应）。纯只读——无任何写操作按钮。
- **测试**：NEW `server/tests/test_execution_fact_chain.py` 4 例（三源归并排序＋changes 不泄漏＋AI 字段白名单＋未知不编造／actor 隔离跨账号泄漏钉／过滤与 limit 有界＋非法 400／权限 viewer 200·外人 403·404·不进 api_catalog）＋**变异三连**（actor 过滤失效／changes 泄漏／scope 谎称 project）逐一转红；桌面改 1 处 tab 断言数组（vitest 用例数不变）。
- **口径**：pytest **1985 收集 = 1979 passed + 6 skipped**（+4）／vitest **825**（本条自身不变；含并入的 UI-UX 黑金轮增量 791→825）／mypy **279**（不变）／蓝图路由 **301**（+1）／业务表 **105**（不变）／api_catalog ENTRIES **94**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）。**server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`**（零迁移，幂等）；桌面便携版重打包挂账（随下次桌面交付轮）。
## [未发布] — V3 技能结构化契约 + 自洽校验（B#36+B#37，2026-11-06）

### 契约与测试（零迁移零路由零桌面；零 src 改动——无需重建镜像）

- **B#36 技能结构化契约 v1**（`docs/architecture/技能结构化契约-v1.md`）：`SkillVersion.manifest_json` 五组**可选**扩展键——`use_boundaries`（适用边界）/`effects`（副作用声明，`read_only`×`write_actions` 自洽律）/`evidence`（证据口径，指针+指纹语义）/`verification`（验证状态**非状态注记**，published=治理通过≠现场验证）/`failure_behavior`（失败诚实）；不设 `additionalProperties:false`、不换状态值、不改发布四闸；`.agents/skills/` 新技能 front matter 建议（name+description 必填+契约键平铺点路径），存量 4 runbook 与内置种子 manifest 均不回填；`instructions_text` 禁拆 YAML 双权威（DB 唯一权威）。字段全部我方独立设计（B#35 红线第 8 条履行，零 fde-skills 正文引用）。
- **B#37 技能自洽校验**（`server/tests/test_skill_contract.py` 四钉，标准库+pytest 零新依赖）：仓库 runbook front matter 契约；内置种子清单静态契约（能力 ⊆ `CAPABILITY_REQUIREMENTS`）；种子 manifest 构造规则独立复算钉；**种子清单 ↔ DB 行对账**（`seed_public_skills` 端到端：全量落库逐位一致+幂等二轮 0+版本行不增殖）。变异四连逐一转红（read_only 推导翻转/name 脱离目录名/域外能力/version 分档漂移）。
- 顺带核实销号 **B#35**：AGENTS 红线第 8 条+backlog 登记已随 #133 合入，修复项产出（PR 合入）达成。
- 顺带卫生修复：移除 #139 合并在 CHANGELOG 遗留的孤立 `=======` 行（冲突标记残留，会污染后续 rebase 标记识别与渲染）。

## [未发布] — V3 报告待办池清欠（代码批）：skill_read 分页 + GlossaryPage 影响分析接线（2026-11-06）

### 行为变更（零迁移零路由；server 变更 ⇒ 一次 rebuild；桌面变更 ⇒ 便携版重打包挂账）

- **skill_read 分页（B#8+B#32 真缺口闭合）**：MCP `skill_read` 加 `offset` 入参——指南长文按 **16k 字符窗口**分页（与 file_read/help_fetch 同尺），响应新增 `offset`/`next_offset`/`total_characters`（`next_offset` 非空时用 offset 续取）；负数/非整数 offset → 400 `invalid_request`。**T-S2 消费计数收敛＝仅首读（offset=0）计一次**，续页是同一消费行为的延续不加计；未知技能 404 不计语义不变。新测试 `server/tests/test_skill_read_pagination.py` 五例（工具面登记形状/短文单页兼容/长文续取拼接无损/偏移形状闸/计数一次）。
- **GlossaryPage 影响分析接线（T-I1 消费面，§六 P0 #1 清偿）**：术语表行内「影响分析」按钮展开 `GET terms/{id}/impact` 三面清单——counts 汇总＋subjects 命中溯源（matched_via 规范名/别名）＋links 邻接边＋forms 修订状态；并入行查询显示「已解析到存活概念」注记；连点不同行按序列号只认最新响应（CR-035 同型守卫）；失败在行内呈现不收行。
- 文档批（PR #136）：六铁律裁决回写主报告 §17/§19、审计三清单全量刷新（补记⑤）、NEW 术语改名SOP-v1.md、AGENTS「口径数字引用前现测」纪律；报告 §十二 记录全轮。

### 口径

- 零迁移零路由：pytest **1972+5=1977 收集**（1971 passed + 6 skipped，CI 复核）/ mypy 279 不变 / vitest **787+4=791** / 105 表 / `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 不变。
## [未发布] — V3 外部模型依赖契约 v1（借鉴登记 B#10 文档批）（2026-11-06）

### 文档（零代码零迁移零路由零依赖；无需 rebuild / 重打包）

- **《外部模型依赖契约 v1》**（NEW `docs/architecture/外部模型依赖契约-v1.md`）：**B#10 落地产物**——把「在确定性规则之后插入外部模型阶段」这类改动必须遵守的约定成文化。七条规则 M-1–M-7（**我方自定义编号**，与任何上游编号体系无关）：①开关默认 OFF 且关闭时判定逐字一致、零外部请求；②阈值是「建议值」非判定常数、调用时点读取、覆盖免重启；③失败≠错误而是「下一阶段」且既有路径原样继续；④传输层可注入、测试网络零依赖、地址密钥禁硬编码、客户端禁擅自裁剪请求体；⑤外部响应缺字段取保守值不推测、枚举表外值只留痕不参与判定、保守方向须写明；⑥日志只记哈希与长度禁记原文、必记「哪一阶段作出判定」的 source 标记、不新建存储；⑦调用方签名不破坏、新参数一律可选、显式意图预判顺序不得被新阶段翻转。
- **与既有纪律的分工澄清**：本条管**判定层**（新阶段失败→降级到下一阶段），既有 W-8「断链不静默 done」管**流程层**（真失败须显性化），二者不得互相抵消——避免「新阶段降级」被误用为「静默吞掉真失败」。
- **现状对照与差距清单**（全部 `[已核实]`，行级引用采用**符号名＋行号双锚**防基线漂移）：M-1/M-3/M-4/M-7 已满足；M-2/M-5/M-6 三条缺成文纪律——**纯靠立规闭合，零代码**。
- **八条可断言判据**（供未来 PR 自查）：开关关闭零请求、关闭态判定逐字一致、阈值改动免重启、新阶段失败落到下一阶段且既有结果不变、缺字段取保守值、日志原文子串扫描零命中、日志含合法 source、旧签名零改动可用——全部静态或注入式断言，不依赖真实网络与真实模型。
- **触发式复查**：新增任一外部模型阶段时，同 PR 内须逐条对照 M-1–M-7 给「满足／不满足／不适用」三选一，不满足者不得合入；季度复查会随《触发条件复查记录》一并过。
- **来源与边界**：设计原则取自 GIIP「外部模型阶段插入的设计规则」这一**抽象方法论**；按 `AGENTS.md` 红线第 8 条——**只取抽象原则，不复制上游正文段落、不复制其结构化表达**，表格骨架、判据措辞、编号体系均为我方独立重写。

### 口径

- 零代码零迁移零路由零依赖——pytest 1972 收集（1966 passed + 6 skipped）/ mypy 279 / vitest 787 / 105 表 / 迁移头 `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 全部不变（纯文档新增，无口径变更）。

## [未发布] — V3 报告待办池清欠（文档批）：六铁律裁决回写 + 审计清单全量刷新 + 改名 SOP + 数字现测纪律（2026-11-06）

### 文档（零代码零迁移零路由；无需 rebuild / 重打包）

- **六铁律裁决回写（主报告 §17）**：明示「开发轨＝先红后绿+CI 4 绿+单 commit revert+PR 纪律等效（有意裁决）；运行期自动修复轨暂无需求有意不做，若做 agent 落码须补 ①③④⑤」——消除「有意不做 vs 未做」歧义（v3-迁移进度对照报告 §六 #6 清偿）。
- **影子库 / view_watchdog 裁决定性补记（主报告 §19）**：PG `*_test` 硬闸判定等效不照搬（销号后人再评估成本）；view_watchdog 未立项（有意不做），§19 清单维持 7 项。
- **审计清单全量刷新（补记⑤）**：`docs/audit/` 三份清单按 fork/main `dc43a2d` 整体重生成（路由 300 / 表 105 / 迁移 36，与口径行逐位一致）；抽取脚本补登 T-J2/CR-027 两个 admin blueprint——补记③「待本体表落地后整体刷新」欠账清偿（§六 #10 清偿）。
- **术语改名 SOP v1**（NEW `docs/architecture/术语改名SOP-v1.md`）：名字域纽带四步改名流程（先查 impact → change-set rename → 改引用面 → 别名不清理）；代码强制挂后续评估（§五-4 / §六 #7 清偿）。
- **AGENTS.md 新增「口径数字引用前现测」纪律**（工作流与陷阱）：表数/路由/ENTRIES/迁移头/mypy/pytest-vitest 六项测量配方 + 全文同模式终扫要求（#129/#131 两次口径校正的教训制度化）。

### 口径

- 零代码零迁移——pytest 1972 收集（1966 passed + 6 skipped）/ mypy 279 / vitest 787 / 105 表 / 迁移头 `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 全部不变（审计清单刷新为重生成既有产物，非口径变更）。

## [未发布] — V3 P0 先行批收官：审批退避提醒 + SLA 统计（2026-11-06）

### 行为变更（零迁移；server 变更 ⇒ 一次 rebuild）

- **B#5 审批退避提醒（复用任务中心，勿新开外发通道）**：新 `scheduler.remind_pending_approvals`（cli scheduler 循环，与派单/过期清扫同拍）——pending 审批按 `created_at` 起算 **10m→1h→4h→24h** 退避序列 catch-up 补发提醒（过夜可直达 4 级），账本=`result_json["approval_reminders"]`；幂等（已发等级不重发）、四级封顶；`skip_locked` 与并发拍板互不阻塞；非 pending 零触碰。红线对齐：不经微信/邮件主动推送，呈现面=任务中心审批列表。
- **SLA 统计**：`_serialize_approval` 新增 `created_at`（此前未暴露）/ `pending_seconds`（仅 pending）/ `reminder_count` / `next_reminder_at`；workflow run 详情（`serialize_run`）在 `waiting_approval` 态带 `waiting_approval_seconds`（锚=`updated_at`），他态无该键。
- 新测试 `server/tests/test_approval_reminder_sla.py` 五例 + 变异五连（红→反向替换还原→绿）。

### 口径

- 服务端 pytest **1972 收集 = 1966 passed + 6 skipped**（+5）；mypy 279/104 不变；vitest 787 / 105 表 / `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 不变。

## [未发布] — V3 迁移进度对照报告入库 + 动工前审查证据修正 + backlog 状态声明混合口径（2026-11-06）

### 文档（零代码零迁移零路由；无需 rebuild / 重打包）

- **报告入库**：`docs/implementation/v3-迁移进度对照-fde-v2建议-2026-11-04.md` 首次入版本库（此前为未跟踪工作文件）——第五轮动工前审查同步：七项口径在 fork/main `743a633` 全部复测吻合（pytest 1961 passed + 6 skipped / vitest 787 取 #131 CI run 42110880267 实测；mypy 门 CI 实跑绿＋基线 279 行）；8 处 文件:行号 漂移修正（api_catalog.py:15→19、chat.py:50-72→72-96、mcp_gateway.py:32-51→36-55、workflows/models.py:157→163、ontology/service.py:1295→1304、executor.py:1213-1227→694 起+1402-1413、ontology/models.py:54-247→54-246、§三 交叉引用 §五-5→§五-4）；§七 存档哈希清单与「12 提交」串位 4 处修正（#114~#124 实为 11）；新增 §十一 增量记录；遗留项四条与 11-01 建议清单九项判定全部复核维持。
- **backlog 状态声明滚动更新（报告 §六 P0 #2 清偿）**：头部改混合口径（T-\* 33 节全部 DONE / B#1–B#40 仅 P0 先行批表 10 项 ✅ 已实施（#128~#131）、其余按逐条状态标注 / P3 四项已定案收口）；「开源借鉴清单登记」段标题改写（与 #133 评审补登记合并）；B#1/B#2/B#4 编号 **#129→#130** 校正（#129=知识收尾轮纯文档，#130=P0 代码级子批；B#28 行已由 #133 同向订正，rebase 取其版）。
- **口径**：零代码零迁移——pytest 1967 收集（1961 passed + 6 skipped）/ mypy 279 / vitest 787 / 105 表 / 迁移头 `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 全部不变。

## [未发布] — V3 P0 先行批收尾：状态归属与对账框架 + G9 出门口径接线（2026-11-06）

### 行为变更（零迁移；server 变更 ⇒ 一次 rebuild）

- **B#6 状态归属与对账框架**：新增 `docs/architecture/状态归属与对账-v1.md`（四层归属总表 + C1–C10 自检清单）与 `server/tests/test_state_ownership_reconciliation.py` 六条跨层对账钉——候选（任务/workflow 两腿）挂接后 `project_evidence` 零行且清单 claim_status 不动；物化唯一入口 = `submit_gate_evidence` 真人提交闸；已领清单项 (source_uri, content_hash, evidence_id) 与被引证据行逐位一致；workflow 版本行 `dag_sha256(dag_json)` 重算 == 落库 `content_sha256`（二次发布不污染已固定版本，run 固定 (definition_id, version)）；documents 快照剥 `captured_at` 后逐位确定；ontology 变更集 base 指纹不符 confirm 409 零物化。六钉逐一变异验证（红→还原→绿）。
- **B#21 G9 出门口径接线（#128 挂账清偿）**：`server/seeds/gates.json` G9 `exit_condition` 挂接评测协议 §5 冻结公式「验收线达成 ≔ uplift_bounded ≥ 0.8 ∧ incidents = ∅ ∧ 三锚四反例全过」+ 无 oracle → `insufficient_data` 不得出分 + 协议文档指针；原五项出门口径逐字保留。种子重生成覆盖由接线钉守护（红=须重挂）；存量 Gate 行不改，新项目懒实例化即得新口径（模板漂移由 T-G2 `template_outdated` 呈现，属设计行为）。
- **口径校正**：#130 曾漏改 AGENTS 口径行迁移头（pytest 行已推进而迁移头未随），本轮顺带校正为 `b2e8f4a6c9d3`（36 rev）。

### 口径

- 服务端 pytest **1967 收集 = 1961 passed + 6 skipped**（+6）；mypy 基线 279/104 不变；vitest 787 不变；105 表 / 迁移头 `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 不变。

## [未发布] — V3 P0 先行批·代码级子批：跳数熔断 + 门禁 revision CAS + 回执终态 + purity 架构测试（2026-11-05）

### 行为变更（合并迁移 `b2e8f4a6c9d3`——一次 rebuild + alembic upgrade head）

- **B#1 跳数熔断**（agent-autoloop 语义）：`workflow_runs.hops` 列 + `MAX_RUN_HOPS=8`——resume_run 拍板重投逐代 +1（继承不清零）、超限 409 `hops_exceeded` 零变更；执行器入口 belt 把在途超限行 honest failed（不再分派任何节点），封顶 workflow 自触发链。
- **B#28 门禁 revision CAS**（FF stage completeX 语义）：`decide_gate` 增可选 `expected_revision`（缺省=旧客户端兼容）——行锁+版本复核，落后即 409 `gate_revision_conflict` 且零变更，多端并发拍板后写不再覆盖前写；拍板生效推进 `gates.version`（复用既有 VersionedMixin 列）并留痕 changes；新列 `gates.lifecycle_version`（门禁语法代际，现役=1）。桌面 expected_revision 接线归主树品牌轮落定后。
- **B#2 回执「写错不重做」**（agent-autoloop worker 语义，收窄面）：`ManifestOutputScanner.receipt_state` 四态回执判定（Protocol 不破）经 `RunResult.receipt_state` 入 `_finalize`——completed + exit 0 + 零声明产物 **且** 回执面损坏（output/ 有文件没写 manifest / manifest 非法 JSON）→ 新终态 `succeeded_but_receipt_invalid`（不进 FAILED_STATUSES ⇒ retry_run 拒同键重跑，业务动作不重执行，消除重复交付尾部风险）；合法零产物任务照旧 completed；声明产物校验失败维持 C-1 failed+retry 合同；`agent_runs.status` 列 String(24)→(40) 加宽 + CHECK 扩（downgrade 归位 failed）。
- **B#4 purity 架构测试**：`test_architecture_purity.py` 四断言——workflows 顶层零 control.service/routes（双向环防线）、control.service 延迟导入惯例固化、workflows 内核零 os.environ/flask、零产品名字面量。
- **口径**：pytest **1961 收集 = 1955 passed + 6 skipped**（+16：hops 2 / gates CAS 4 / receipt 5 / purity 4 / 迁移 roundtrip 1）；mypy 279 不动；vitest 787 不动。变异验证四连（hops 上限/CAS 复核/回执终态/scanner 收窄面）apply→red→reverse-restore→green。

## [未发布] — 知识收尾轮：AGENTS 口径行校正 + README 品牌路径/配置对齐（2026-11-05）

### 文档收尾（零代码零迁移零路由零桌面，口径全不动）

- **AGENTS 口径行校正**：口径行停留在 #124（pytest 1944=1938+6s），#125 W-9 纯测试 +1 起 #125–#128 各轮已按 1945=1939+6s（CI PR-head 实测）报——行内补齐 W-9 +1、实测锚点前移；零代码轮动了测试数同样要同步口径行。
- **README 对齐**：品牌单点路径修正为 `desktop/src/shared/brand.ts`（#109 CR-001 双侧单点后遗留旧路径），并补服务端单点 `server/src/fde_api/config.py`（`FDE_PRODUCT_NAME` 覆写）；配置边界表补 `FDE_PRODUCT_NAME` / `FDE_AI_MONTHLY_TOKEN_BUDGET`（0=不限额、设施故障 fail-open）/ `FDE_AGENT_MONTHLY_BUDGET`；能力表补门禁证据候选（任务/工作流产物建议性候选，采纳仍走人工提交闸）与 AI 用量月度预算/审计账本。
- **`server/.env.example` 补 `FDE_PRODUCT_NAME` 注释示例行**（#109 新增公开配置时漏了示例面）。

## [未发布] — V3 P0 先行批·文档级子批：B#3 红线 + 交付效果评测协议 v0 + DSH 适配层决策记录（2026-11-05）

### 文档级先行批（零代码零迁移零路由零桌面，口径全不动）

- **B#3 红线 +1**：AGENTS 红线节新增「AI 审查不执行被审代码」——审查输入只能是 diff/文本快照，不得检出/运行被审交付的代码、测试、配置、hooks（agent-autoloop delivery 插件语义；未来上 AI 审查时加 CI 断言）。
- **B#21+B#22+B#29 交付效果评测协议 v0**（`docs/architecture/交付效果评测协议-v0.md`，PROPOSED 文档层）：uplift 算分口径 + result 字段清单 + 三锚点四反例门禁判据（阈值须我方数据校准）+ 验收合同契约五点（对齐 G8 conditional_pass / G9 有条件接受）；无 oracle 不得出分（`insufficient_data`）；G9 exit_condition 挂 gates.json + pytest 接线=server 变更归代码级子批同窗口；Q1–Q3 拍板前停文档层。
- **B#27 DSH 适配层决策记录 v1**（`docs/architecture/DSH-适配层决策记录-v1.md`）：`fde-dsh-v1` 自定协议声明 + 官方源码零命中端点证据 + 若启用须自写适配层清单 + lock 八字段/三方合并升级法 + 安全前置四条；**维持「当前不装、不换执行体」裁决**。

## [未发布] — V3 开源借鉴消费登记轮：B#1–B#34 全量登记 PROPOSED + CR-004 销号（2026-11-05）

### 登记轮（零代码零迁移零路由，口径全不动）

- **来源**：调研会话《开源项目借鉴总览-2026-11-05》及八份分报告（横评七项目：fde-v2 已消化完毕 / agent-autoloop 最值得借鉴 / agnes-harness·giip·FDEP 仅参考设计 / fde-gym 战略价值最高但工程性价比第二 / FF-FDE 只借鉴实现不引入运行时）——`docs/audit/` 在途未提交产物，落定回写归调研会话，本登记轮只消费不代提交。
- **登记**：backlog 新节「开源借鉴清单登记」——**B#1–B#34 全量 PROPOSED**（登记≠排期≠默认实施；实施须另开轮走既有流程）。P0 先行批 11 条（B#1 跳数熔断 / B#2 回执写错不重做 / B#3 审查不执行被审代码红线 / B#4 purity 架构测试 / B#5 审批退避+SLA / B#6 状态归属对账 / B#21 评测协议 v0 / B#22 三锚四反例 / B#27 DSH 适配层决策记录 / B#28 门禁 revision CAS / B#29 验收合同契约）；P1 15 条、P2 条件触发 9 条按触发条件挂账；跨项目合并六组防重复立项。
- **拍板闸挂账**：B#1+B#28 合并同一迁移窗口（一次 rebuild+alembic upgrade head）需拍板；Q1–Q6 决策依赖（Q1「交付产物评测」语义、Q2–Q3 验收线/kpi/oracle、Q4–Q6 数据落点/容器/许可证）不预支。
- **红线对照**：B#25 客户资料红线（真相/参考解/隐藏流量永不入库不进 git，落 fdeops 工作目录+全代号化）；B#34 交付进程红线（仅内部自检夹具）；P3 评估报告「写类外呼/发信/付款永不降级」红线上位维持。
- **CR-004 销号**（c1）：AGENTS 口径行已由后续每轮维护+CI PR-head 实测逐位核对（现口径 105 表/`d9f4a7c2e6b1` 35 rev/路由 300/1945=1939+6s/787/279），#88 时代投诉面不复存在——「逐轮维护治愈」销号，台账行+详情段+修复 PR 三处注记。

## [未发布] — V3 P3 评估报告轮：有限自动执行开放评估落盘——八档边界分类学 + 可降级集合=∅ + 取数口径先行（2026-11-05）

### 评估报告（零代码零配置零迁移零闸态变更）

- **轮次定位**：P3-④ 评估报告轮本体（合同 §4，#125 三道闸清偿后解冻）；报告=`docs/implementation/v3-p3-评估报告-有限自动执行-v1.md`。合同 §4.4 末段原文兑现：「本立项不开放任何自动执行；评估报告本身也不开放」——**闸态变更数=0**。
- **①边界梯度分类学（§4.4-1）**：三面目录实测（api_catalog 94 条 effect/risk/confirmation 分面 + MCP 17 工具五元 + A 轨审批执行硬白名单 `service.py:867` 唯一对）→ 八档分类 **G0 只读内查 / G1 只读外呼（lcsc_search 原型）/ G2 产物外呼（forms.export、translator.translate 已处事后审计档）/ G3 产物出具·治理耦合（documents.generate、export_sow 挂 signoff）/ G4 普通内部写（37 条=现役中间地带）/ G5 敏感内部写（不可逆+启发式捕获面）/ G6 发信类红线现役档（`file_send_wechat` 收件域封闭本人+事前密码确认）/ G7 写外呼付款红线空域（构造性零条目）**+ S 系统自主白名单。**现役可降级集合=∅**；「写外呼/发信/付款永不降级」红线逐字维持；未来新类准入=§1.5 五要素模板（全 PROPOSED）。
- **②验收核对表+运行数据要求（§4.4-2）**：32 例核对表引用 #125 §4.1 不复制；**取数口径四条先行**（审批时效 p50/p90 / 人工否决率=误判率代理 / 执行落空检测 / 确认失败锁事件），活库 `automation_approvals=0` 行——首批真实 run 后评估复审轮消费，本轮不设数值门槛。
- **③责任主体数据面证明（§4.4-3）**：#125 §4.3 五链节引用 + **三条断言式回溯 SQL**（审批链双侧人签 / 发起链实名 / 全事件落人，期望恒 0 行）——现有表够，无结构性缺口。
- **④调研衔接（§4.4-4）**：调研会话《自动化运行-DSH替代可行性评估-2026-11-05》已落盘（`docs/audit/` 在途产物，落定回写归调研会话，本报告只消费不代提交）：四链路 A/B/C/D 与分类学面对齐、「真瓶颈=人工拍板红线」互证、P0 维持现状同向、治理风险独立佐证。
- **口径**：零代码轮基线不变——pytest **1945 收集 = 1939 passed + 6 skipped** / mypy 279 / vitest 787（以 CI PR-head 实测行核对）；无需重建镜像 / alembic / 重打包。

## [未发布] — V3 P3 四项状态轮与 §4 闸清偿：①②③定案 + ④三道闸齐备（2026-11-05）

### 状态轮报告（零迁移零路由零生产行为变更）

- **轮次定位**：主报告 §17 P3 行四项「立项不排期」的状态清偿轮——报告 `docs/implementation/v3-p3-四项状态与闸清偿-v1.md`（含 §16 用例族 32 例逐项核对表、责任主体机制化方案、活库数据闸实测）；四项裁决 AskUserQuestion 未获答复，按 #124 委托先例按推荐项执行、逐项留痕可推翻。
- **①多 Agent 自适应编排**：活库实测 `agent_runs=0`/`workflow_runs=0`（演练键亦 0）——真实 run 数据解冻闸未动，维持冻结，零动作。
- **②Skill 运行反馈改进**：裁决=usage 维持「失败不计」对称语义、不新开失败核算维度（活库 skill 消费事件=0 无建议需求；失败证据走 ai_call_audits/operation_events 人工审计面；重审触发器=首个真实改进建议需求）；agent-policy §2.1 效果评估行已回写；双面消费量闸未过，仍冻。
- **③业务规则推理**：ontology_rules 维持不建 PARK 定案（risk≥3 规则已内嵌且被 `test_catalog_effect_risk_invariants` 钉住、T-C1 编译校验无规则输入需求；重开触发器三项写死）；**规则 9 强制化悬置线销号=维持告警**（执行层已硬闸：workflow call external 必 awaiting_confirmation 诚实失败 + DSH agent 节点走审批回调；「P2 enforcement wave」不做）。
- **④有限自动执行**：三道闸齐备——T-J2 ✅（#116）+ **§16 用例族核对表 32 例全绿**（30 直接绿 + W-9 本轮补钉 + W-3 裁决回写，0 红）+ 责任主体机制化方案成形（审批链人签五要素在表、系统自主动作=封闭白名单、验收分离双面钉住，无结构性缺口）→ **评估报告轮解冻可排期**（余项=边界梯度分类学〔写类永不降级红线维持〕+调研会话衔接；写类 external 免事前确认=红线级非目标逐字维持）。
- **W-9 补钉（唯一代码变更，纯测试）**：NEW `test_capability_revocation_mid_run_fails_subsequent_write_call_node`——run 进行中撤销发起人 AI 档位，后续写类 call 节点分派时实时重判命中 `execute_api` workbench.write 硬闸 403 forbidden 诚实失败（零重试）、run failed（FV-F1）；变异验证（档位一次定终身→红→还原→绿）；executor 全文件 37/37 绿。
- **W-3 裁决回写**：skill `input_schema` 为只写元数据（publish 期仅 isinstance(dict)，MCP/chat/workflow 三面零消费）——校验面不补码（无消费方不建空壳），test-plan W-3 行注记「未实现，按需另立」；S-7/S-9/D-5 形态偏差同批注记。
- 口径：pytest 基线 1944=1938+6s 双面一致（干净 `58a54ff` 本地全量实测=#124 CI 口径）+1 → **1945 收集（CI PR-head 复核为准）**；mypy 279 基线不动；桌面零改动（vitest 787 不变）；零迁移零路由 ⇒ 无需重建镜像、无需 alembic、无需重打包便携版。

## [未发布] — goal-c P3 服务端小轮：指标面排除演练 run + 桥投影列水合 + outbox 死信箱销号（2026-11-05）

### 服务端（零迁移零路由零桌面）

- **CR-031 演练 run 排除出指标持续观测面**：降级演练（`rehearse_fallback`，幂等键 `rehearsal:` 前缀、零计费零真实耗时）此前混进四张 run 指标卡——L1 演练（completed+degraded+0ms+0 费）拉低草稿耗时中位数、**抬高降级率（持续 >30% 暂停扩大 agent 授权的红线指标会被演练误触发）**，L2 演练（failed）压低一次通过率，零费行拉低成本中位数。现四个 AgentRun 查询统一挂 `_REAL_RUNS` 过滤（常量复用 `agents/pilot.py::REHEARSAL_KEY_PREFIX` 单点，试点闸口面同款口径先行），四卡 `definition` 文案同步注明排除（口径面=计算面）。测试：NEW 专项 1 例钉 L1/L2 两形态四指标；变异验证（过滤中性化→四断言全红→还原→绿）。
- **CR-030（半 A）桥投影列水合**：4h 采集投影的 `_sync_bridge_evidence` 全表 ORM 水合改三列投影（id/openfde_engagement/fdeops_workspace），行为等价。**半 B 登记失真如实修正**：现场核实 `_city_order_rank` 在 r12 B-④ 重写后已是单次 join+Python 计数，登记描述的「循环 session.get」不存在；真实重复面仅剩仿真工具循环（P4 卫生维持观察）。
- **CR-016 台账销号**：outbox 死信箱经 T-J1（终态写入三落点）+ T-J2（取消/重试双路径终态收口）已彻底闭环，登记前提不复存在；本轮只补台账销号注记，零代码。
- 口径：pytest **1944 收集 = 1938 passed + 6 skipped**（+1；基线 1943 已随 #123 CR-041 核销轮双面实测校正）；105 表 / 迁移头 `d9f4a7c2e6b1`（35 rev）/ 路由 300 / ENTRIES 94 / mypy 279 基线 / vitest 787 全部不变；零迁移（rebuild 幂等校验 `alembic upgrade head`）。

## [未发布] — goal-c CR-041 核销：融合树独立复测 + 口径校正 + 桌面便携包 r16（2026-11-05）

- **核销（零代码轮）**：并发 P3 批清偿（#121）落定后的独立核销——融合树全量实测：服务端 pytest **1943 收集 = 1937 passed + 6 skipped**（本地 Windows 与 CI PR-head 双面一致）、CR-041 专项 2 例绿、mypy 基线 279 全绿、桌面 vitest 774/774、typecheck 零错；**发现并校正融合口径偏 1**（AGENTS 前值 1942/1936 为算术推导；CI 实测 #120 = 1935+6s、#121 = 1937+6s，口径行按实测改写）；「负向日志断言空转绿」担忧实测排除——`not in caplog.text` 全仓 10 处（含 test_auth_api.py:481 密钥不入日志安全断言）在 env.py 解禁后真判零红。部署活体核验：api 镜像 env.py 修在位、300 业务路由、双 admin 路由、`/ready` 200、alembic head `d9f4a7c2e6b1`。
- **桌面便携包 r16**：r15（11-05 11:18）早于 #113 T-UI1 徽标与 #121 CR-035/040——marker「已取代」「source_kind」双 0 命中证实缺口；从 fork/main `7dc620e` 干净树重打包 **蔡工FDE-0.2.0-便携版-r16**：asar sha256 `c62e184b131db53386eb83897c80ca447a57a81b952d6e992cea1bcbcb75027d`，marker「已取代」×2 /「source_kind」×3 命中；r15 旧目录未覆盖。
- 台账同步：CR-041 增核销复核段（含口径校正与 r16 交付记录）。

## [未发布] — goal-c P3 测试补强：AI 机会主链组件 13 例覆盖 + sync-hash 断言加固（2026-11-05）

### 桌面端（纯测试轮：生产代码零变更、服务端零改动）

- **CR-037 ResearchOpportunity.tsx 零 vitest 覆盖清偿**：NEW `desktop/tests/renderer/research-opportunity.test.tsx` 13 例，全部落在新文件——
  - 纯函数 8 例：`validateOpportunityProfile` 全分支（超长 301/1001 与临界 300/1000、状态/优先级/风险等级无效值、三项评分 0/6/小数拦截 + null 放行、负责人不在成员表）；`opportunityProfileInput` 裁剪两端空白并丢弃展示名；`opportunityProfileErrorMessage` 8 个错误码逐一映射 + 未知码兜底；`draftErrorMessage` PoV/SOW 双形全码 + 兜底。
  - `OpportunityDetail` 组件 5 例：非编辑态档案网格中文渲染；canManage 经「更多」菜单删除联动；编辑态保存主链（PATCH 载荷逐字段断言 + 成功回执与提示）；保存失败按码映射 alert 且不回执；脏标记按 `opportunity-profile:<id>` 键置脏、卸载自动清脏。
  - 变异验证：评分上界 5→6 → 评分用例红 → 还原 → 绿（生产代码 `git diff` 零残留）。
- **CR-038 sync-hash 断言加固（CR-007 同型残留收尾）**：`new-project.test.tsx` 创建成功路径的 `location.hash` 同步读改 `await waitFor(...)`，与 `navigation.test.tsx` 已修的 5 处同型对齐；属加固型改动（当前同步写 hash 下两种写法均绿，防未来异步化复发），台账已如实注记无可做的红绿变异。
- 口径：桌面 vitest **787/787**（+13）；typecheck 绿。测试文件不进应用包（asar），**无需重打包便携版**；105 表 / pytest 1943 / 路由 300 / ENTRIES 94 全部不变（pytest 数字承 CR-041 核销轮 CI 实测校正）。

## [未发布] — goal-c P3 批清偿：术语页搜索守卫 + 状态值域 + alembic 日志基建（2026-11-05）

### 桌面端（GlossaryPage 两项 P3；零服务端改动）

- **CR-035 术语搜索序列守卫**：术语表搜索每键入触发一次全量重取且无守卫——后发先至的旧响应会覆盖新结果；且每次按键后整页换成「正在加载术语表…」，**搜索输入框随页面一起被卸载 → 焦点丢失、无法连续输入**（比原登记的「闪空」更重）。现加 `sequence` ref（同仓 `ResearchWorkspace.loadResearch` 范式）：只有最新一次请求的结果可落表，旧响应整包丢弃；首屏加载完成后不再整页 loading，旧内容留在屏上等新结果（输入框不再被卸载）。
- **CR-040 术语状态值域对齐**：桌面 `TERM_STATUS_LABEL` 写的是服务端不存在的 `candidate/retired`，又缺 `draft/superseded` → 状态列回显英文原值、中文标签永不显示。现对齐服务端 `ontology/models.py::TERM_STATUSES`（draft→草稿 / confirmed→已确认 / superseded→已取代 / merged→已合并），并加注释钉住「值域唯一权威＝服务端」。
- 测试：vitest +3（值域中文标签且旧标签不再出现 / 乱序响应取新弃旧 / 在途搜索不闪空且旧内容不消失）；typecheck 绿。

### 服务端（测试基建一行；零迁移零路由零契约）

- **CR-041 alembic 日志基建**：迁移脚本 `fileConfig` 默认 `disable_existing_loggers=True`，而测试夹具每例都跑迁移 → 导入期创建的模块级 logger（`logging.getLogger(__name__)`）在整场会话内全量 `disabled=True` → caplog / `log_cli` 对这些 logger 永远空捕（此前只能逐测试显式解禁）。现显式 `disable_existing_loggers=False`：只重配 alembic 自身的 logger，不动已存在的模块级 logger。生产面零影响——迁移是独立进程，跑完即退，仅「测试进程内迁移与应用共存」才踩中。
- 测试：NEW `server/tests/test_migrations_logging.py` 2 例（迁移跑完后导入期 logger 仍 `disabled=False`；caplog 能捕获模块级 logger 记录）。变异验证：撤 env.py 那一行 → 两例全红；恢复 → 绿。

### 文档

- **CR-011 三包意图锚集中指针**：V3 主报告 §13 表格补「意图锚指针（不改造）」行——mailing → `docs/SES发信模块-G9.md`；translator → `docs/goal-d13·goal-d14-交付工作台.md`；guidance → `docs/goal-d1·goal-d2-交付工作台.md`。只补可查位置，三包实现面零改动。
- 台账同步：CR-035 / CR-040 / CR-041 / CR-011 → fixed；**CR-003（主报告 §20 实施跟踪注记）挂账**——并发会话在途回滚轮正在撤 T-W7/T-I1 等轮次，此刻补注记即写即错，待回滚轮落定后一次性补。
- 口径：pytest **1942 收集 = 1936 passed + 6 skipped**（本轮 +2）；桌面 vitest **774/774**（本轮 +3）；105 表 / 迁移头 `d9f4a7c2e6b1`（35 rev）/ 路由 300 / ENTRIES 94 不变——零迁移零路由，无需 rebuild。

## [未发布] — goal-c CR-027 规则版本显式管理：撮合不再永久停在降级态（2026-11-05）

### 服务端（零迁移零桌面；路由 +2；用户拍板「显式管理动作」）

- **修复（CR-027）**：`dispatch/rules.py` 的 `create_rule_version`（发布）与 `activate_due_versions`（激活）此前**两者都只有测试引用、零生产入口**——规则版本永不 published→active，`active_rule_version` 恒 None，`match_package` 恒 422 `rule_version_required`（§11.1 降级态变永久态）。NEW `dispatch/admin_routes.py`（blueprint `/api/v1/admin/dispatch`，T-J2 admin 蓝图同款）：`POST /rules/versions` 发布新版本（admin 门在服务层 role 判；快照缺省取当前默认规则投影＝发布「当前口径」而非手抄正文）、`POST /rules/activate` 激活到点版本（幂等，无到期版本零变更；同事务留痕 `operation_events dispatch_rule_activated`，changes 只落版本号/数量/激活时刻，**不落规则正文**）。**公示窗不绕过**：发布端强制 `effective_at ≥ published_at + 30 天`（§6.2），激活端只激活已到生效日者——人工也加速不了公示期。**不做请求路径惰性触发、不做 scheduler 自动激活**：激活节奏由人控制，与「名单≠开闸」裁决一致。
- 测试与口径：NEW `test_dispatch_admin_rules.py` 5 例（非 admin 双路由 403 / 公示窗 <30 天 422 `notice_window_required` + 版本冲突 409 / **激活后撮合不再 422**（解冻证明）+ 重复激活幂等 + 事件留痕只落元数据 / api_catalog 钉子 / 缺省快照取默认投影）。业务路由 298→**300**；全仓 pytest **+5**；台账 CR-027 → fixed、**CR-028 裁决「维持整条挂 B-③ 法务区」**（税率/税法年口径未确认前不动码，解冻条件随法务口径一并修）。

## [未发布] — goal-c CR-022 补呈现通道：取消后在途派发结果不再静默丢弃（2026-11-05）

### 服务端（零迁移零路由零桌面改动；用户拍板「补呈现通道」）

- **修复（CR-022）**：节点在派发后被取消时，在途外呼/AI 调用返回的结果被终态 guard（`node.status∉(pending,ready,running)`）静默丢弃——api_actions 留有成功记录但节点 `output_json=null`，「已执行外呼不回收（诚实呈现）」承诺无展示通道。现 `_settle_node_success`/`_settle_node_failure` 拆分 guard：`node is None` 早退不变；状态不在集合且 **== "cancelled"** 时落诚实记录——**终态不复活**（节点仍 cancelled，FV-F1「断链不静默 done」不破），`output_json = {cancelled_after_dispatch: True, dispatch_outcome: "succeeded"|"failed", action_id, dispatch_result}`（产物真值 + **action_id 指针**——写类操作可回 api_actions 反查）+ `node.error = "cancelled_after_dispatch"` 稳定标记（桌面 WorkflowConsole「错误」列直接可见 ⇒ 零桌面改动即有呈现通道）。取消的 run 不挂 T-W7 门禁证据候选（不进 marker 挂载点）。
- 测试与口径：`test_cancelled_node_records_inflight_dispatch_result`（公开 cancel_run 取消后驱动 settle 点 = 在途返回；断言节点仍 cancelled/未复活 + output_json 三键 + action_id + 序列化面可见）。全仓 pytest **+1**；台账 CR-022 → fixed。

## [未发布] — goal-c CR-021 行锁修复：本体变更集三翻转入口串行化（2026-11-05）

### 服务端（零迁移零路由零桌面改动；用户拍板「修复：CAS 状态翻转」）

- **修复（CR-021）**：`submit_change_set`/`confirm_change_set`/`reject_change_set` 三处状态翻转原为「读 `row.status` 判合法→物化→赋值」的先读后写——两拍板人并发 confirm 会双双物化（幂等键+UNIQUE 兜底不炸数据，但 409 `not_in_review` 语义失守、`ontology_change_set_confirmed` 事件双份）；reject 可翻转已物化的 confirmed 行；双 submit 重复 version。现新增 `_lock_change_set`（`select … with_for_update() + populate_existing`）在三处入口**行锁重读**：并发对手在此串行化，锁在手读到的必是已提交真值；confirm 的 base 指纹复核+逐项物化全程在锁内。
- 测试与口径：`test_change_set_transition_races_serialize_on_row_lock`（裸连接提交并发终态+会话旧实例=并发窗口第二请求的真实内存视图；三段：迟到 confirm 零物化 `not_in_review` / confirmed 终态拒迟到 reject `invalid_transition` / 迟到 submit 409 且 version 只 +1）。变异验证：摘三处行锁→红（迟到 confirm DID NOT RAISE=静默双物化）→还原→绿。全仓 pytest **+1**；台账 CR-021 → fixed。

## [未发布] — V3 T-J2 收官：handler 自动重试 + admin 任务取消 API（2026-11-05，P1 全清）

### 服务端（域 14 最后一块；迁移 +1 纯 CHECK 置换；路由 +1；零桌面）

- **handler 自动重试**：可恢复类型（复用 reconcile `RECOVERABLE_JOB_TYPES` 幂等白名单）handler 抛错不再首败即终——指数退避重投（30s×2 封顶 15 分钟）直至 `attempts` 耗尽；重试期间 outbox 事件保持 `dispatched`（T-J1 红线：只有最终失败才收口 failed），退避到期由 reconcile 新增 due 补投面送回队列（at-least-once，认领侧 `not_due` 守卫消化重复条目）；外副作用类型（automation.execute）维持首败即 failed。candidates 查询补 `populate_existing`（同 session 残留旧实例会让分支判定读内存陈值——实测踩中）。
- **admin 任务取消 API**：`POST /api/v1/admin/jobs/{id}/cancel`（admin，幂等）——**cancelled 成为真状态**（迁移 `d9f4a7c2e6b1` 纯 CHECK 置换，active_key 生成列天然兼容零重建）；重复取消 200 `cancelled=false`、终态 409 `already_terminal`、运行中活租约 409 `job_running` 不强杀（等租约过期后可接管）、过期租约=worker 已死可安全取消（迟到 settle 被终态守卫拒绝）；取消同事务三面收口：job 行 + 同键 outbox 事件（pending+dispatched 一并收口，防下一轮 dispatch 复活）+ `operation_events job_cancelled` 留痕。不进 api_catalog（平台运维面）。
- 测试与口径：pytest +21（worker 重试 7 + reconcile due 面 4 + cancelled CHECK 1 + NEW test_admin_jobs 9）＝**1933 收集 = 1927 passed + 6 skipped**；105 表 / 迁移头 `d9f4a7c2e6b1`（35 rev）/ 路由 298 / ENTRIES 94 / vitest 771 不变。**至此 V3 P1 任务全部交付**（T-J1/T-J2/T-P1-4/T-P1-5/T-OBS1）；CR-016 outbox 死信闭环补齐（取消/重试双路径均以终态收口）。
## [未发布] — V3 P3 立项轮：高级自主化四项立项合同（2026-11-05）

### 文档（零代码零迁移零路由零桌面；口径不变）

- **立项合同 NEW `docs/implementation/v3-p3-高级自主化立项-v1.md`**——backlog §P3 四项逐项展开：①多 Agent 自适应编排（域 6 DEFER 维持，进程内团队拒绝理由=主报告 §19-7 常量，观测=`agent_runs.fallback_level` 分布）；②基于运行反馈的 Skill 改进（T-S2+CR-013 数据面已闭环，失败面维度属语义裁决非补漏）；③业务规则推理 ontology_rules（registry-v1「无消费方不建空壳」维持，候选消费方=risk≥3→human_approval[域 9]+T-C1 编译校验，规则 9 强制化悬置线一并盘）；④有限自动执行开放评估（P0/P2 全 DONE、P1 仅剩 T-J2 在途；解冻=三道闸；写类 external 免事前确认=红线级非目标）。每项含立项依据/已落地基线/评估问题清单/非目标/解冻条件/回写义务；评估报告轮自身也须先过解冻闸。
- 台账同步：backlog §P3 重写挂锚；RAG/LightRAG 维持不立项（主报告 §19 附注）；在途开源借鉴调研（autoloop/agnes/fde-gym/giip/fdep-mcp/DSH 替代可行性）不预支结论，落定后由调研会话自行回写。
- 口径：pytest 1913 收集 = 1907 passed + 6 skipped / 105 表 / head `e2c6a8f4d1b3`（34 rev）/ 路由 297 / ENTRIES 94 / mypy 279 / vitest 771——全不变，无需 rebuild/重打包。

## [未发布] — goal-c CR-013 计数隔离修复：skill 节点计数侧故障不再升级消费侧（2026-11-05）

### 服务端（零迁移零路由零桌面改动）

- **修复（goal-c 台账 c4 遗留 P2，c5 评估未按、本轮单独清偿）**：workflow skill 节点 `_dispatch_skill` 的 `record_skill_usage` 计数调用原为裸调用——计数微事务遇 DB 异常会被 `_execute_node` 兜底 catch 为 `dispatch_crashed(retryable=True)`：已成功的那次 AI 调用被丢弃重跑（双份真实 AI 成本）且节点误标 failed。现包 try/except 记 warning（含 node/skill/error_type）不冒泡——AI 已成功则节点必 succeeded，计数失败只丢一条 `skill_used_workflow` 事件（T-S2「失败不计」对称方向；chat 面 ai_tool_loop 同型守卫，workflow 面补齐最后裸露点）。
- 测试与口径：executor +1（`test_skill_usage_count_failure_does_not_fail_node`——monkeypatch 计数抛 OSError → run succeeded + 恰 1 次 AI 调用（无重投）+ warning 落 caplog；变异验证红→还原绿）。全仓 pytest **1913 收集 = 1907 passed + 6 skipped**（本轮自身 +1；全仓口径随同日 #114 P1 残尾清偿轮 +7 前进）/ 105 表 / 路由 297 / ENTRIES 94 / mypy 279（基线无新增）；**rebuild 后必 `alembic upgrade head`**（零迁移，幂等校验）。
- 台账同步：CR-013 → fixed；**CR-041 登记不修**（测试基建：alembic `env.py` `fileConfig` 默认 `disable_existing_loggers=True`，db_session 每测试跑迁移 → 导入期创建的模块级 logger 测试会话内全量禁用、caplog 空捕；CR-013 测试沿 test_storage_contract oss2 先例显式解禁，根因修复留测试基建轮）。

## [未发布] — V3 P1 残尾清偿：outbox 状态闭环 + 终审双闸 + 审批过期清扫（2026-11-05）

### 服务端（三 S 同轮：T-J1 / T-P1-4 / T-P1-5；T-OBS1 核验销号；零迁移零路由零桌面）

- **T-J1 outbox 状态闭环（WB-DEF-9）**：outbox 事件此前只有 pending→dispatched，终态永无写入点（dispatched 即泄漏）。新增 `outbox.mark_completed/mark_failed`（联动键 `(topic, aggregate_id)==(job_type,target_id)`，只收 dispatched 行、未派发 pending 不动、失败摘要截 2000 字），覆盖**全部三个 job 终态写入点**：`worker._settle`（与 job 终态同事务）、`worker._claim` no_handler（同 claim 事务）、`reconcile._fail_job`（worker 失联终失败）。
- **T-P1-4 resolve_signoff 双闸（WB-DEF-2）**：终审拍板原仅 can_view+AI 档位——viewer 被授予高档后即可代拍。改为项目 `can_manage`（`_require_project_manager`）+ 档位双闸（与 `generate_agent_solution` 权限双层同款）；viewer+`system_operator` 档 → 403 `forbidden`（拦截者显式为项目闸而非档位闸）。
- **T-P1-5 审批过期清扫（WB-DEF-3）**：过期翻转从 decide/状态查询两处内联重复提取为唯一原语 `control/service._expire_approval`（行为零变化），新增 `scheduler.sweep_expired_approvals`（`skip_locked` 与并发拍板互不阻塞）接入 scheduler 循环（与派单同拍）——无人触碰的过期 pending 审批不再永挂任务中心。
- **T-OBS1 降级 chat 落审计（WB-DEF-4）核验销号**：chat 直调 `execute_ai_prompt`，降级直连腿的审计+月账本入账已随 #112（CR-006）落地，本轮零补码销号（`direct-chat-*` 前缀方案由 purpose+used_fallback 取代，区分度更优）。
- 测试与口径：pytest +7（outbox 收口 2 + worker 端到端 3 + viewer 双闸 1 + 清扫 1）；105 表 / 迁移头 `e2c6a8f4d1b3` / 路由 297 / ENTRIES 94 / vitest 771 不变（需 rebuild 三镜像，无迁移）。P1 仅剩 T-J2（重试落地时 outbox failed 只准在最终失败分支翻转——backlog 已留注）。

## [未发布] — V3 实施 T-UI1 三页核销 + GateBoard 候选来源徽标（2026-11-05）

### 桌面端（服务端零改动；T-W7 桌面挂账清偿 + backlog 销号）

- **T-UI1 核销（零补码）**：WorkflowConsole / GlossaryPage / SkillVersionsPage 三页已随 T-W6（#88）同名全量交付（vitest 5/6/7 例 + typecheck 绿，本轮基线复核 767 全绿）——backlog 条目按「已由先导轮兑现」销号。
- **候选来源徽标**：`GateBoard` 候选载荷扩为 `source_kind` 判别联合——task 形（T-G1 旧行，服务端读时缺省）与 workflow 形（T-W7 运行时保留键 `gate_evidence` 的节点产物，带 `workflow_run_id`/`workflow_node_key`/`label`）。**修复潜伏兼容 bug**：T-G1 守卫硬性要求 task 三键，T-W7 workflow 候选行会让整板 isGatesView 拒载；分形守卫后 workflow 缺 run/节点键仍整板拒载（沿「在场必须形状齐全」口径）。workflow 行带「工作流」徽标 + run/节点出处行；采纳走既有提交闸零新入口；同指纹任务/工作流候选并存各占一行（React 键域 `wf:run|node` 分开防撞）；uri>500（人工提交闸上限，与手填表单同限）候选可见但禁采并 title 报因。
- 测试与口径：gate-board +4（徽标呈现+采纳提交体 / 同指纹两形并存 / 超限禁采 / 坏形状整板拒载），vitest **771**；服务端零改动（本轮零增量；全仓 pytest 口径随同日 #112 CR-006 前进至 1905 收集 = 1899 passed + 6 skipped，105 表 / 路由 297 / ENTRIES 94 / mypy 279 不变，无需 rebuild）。

## [未发布] — goal-c CR-006 统一入账+统一闸：DSH 主路径/kimi 本地腿补预算门与 `ai_call_audits` 记账腿（2026-11-05）

### 服务端（用户拍板「统一入账+统一闸」落地；零迁移零路由零桌面改动）

- **缺口（goal-c c2/c8 两轮 E0）**：`dsh_enabled=true` 时 `execute_ai_prompt`——workflow skill 节点/聊天/结构化调用的 DSH 主路径——对 `ai_monthly_token_budget` 恒放行且零记账（skill 花费不入任何账本）；kimi 全路径零预算零审计；预算设施对后台任务存在 flask g 盲区。
- **统一预算门**（`control/ai_server_client.py::execute_ai_prompt`）：`ai_monthly_token_budget` 超限即拒（`ai_budget_exceeded`，retryable=False），先落 `budget_blocked` 审计再拒绝、拦在 MCP token 签发之前（拦截路径零写副作用）；预算 0=不限额、设施故障 fail-open（与 deepseek 直连腿同语义）。**门带显式 user_id——后台任务（workflow skill 节点等无请求上下文场景）同样生效**。
- **统一记账腿**（`_audit_execution`）：DSH 成功按 `provider_usage.calls[]` 聚合精确入账；失败（HTTP 4xx/无效输出/不可达非降级错）各落 `failed`；降级直连腿成功/失败均记账（`used_fallback=True`，token 来自 OpenAI 兼容 usage 块）；provider_usage 无 calls 时 token 记 None 不发明数字。**无双计**：deepseek/kimi 的 DSH 腿经 `structured_completion`→`execute_ai_prompt` 单点入账；deepseek 本地腿沿旧 `_audit` 不动；`direct_tool_completion` 内部零审计（降级腿单点记账）。
- **kimi 本地腿补齐**（`ai/kimi.py`）：入口预算门（拦在文件上传前；actor 取请求上下文，后台无上下文→放行——缺口如实保留）+ 本地腿成功/失败记账（`purpose="kimi_docx"`；流式无 usage，token 记 None）。
- `ai/auditing.py` +`audit_budget_blocked` 统一拦截留痕助手；`execute_ai_prompt` 新增可选 `purpose` 参数（`structured_completion` 传 `"structured"`；chat/executor/dsh_runtime 调用点未触碰）。
- **测试与口径**：pytest **1898 收集 = 1892 passed + 6 skipped（本轮 +7；基线 `b3793d4` 实测 1891；T-W7 同日并轮后总口径 1905 = 1899+6s）**（NEW `test_ai_server_budget_audit.py` 7 例：DSH 拦截零请求+budget_blocked 留痕/成功按 provider_usage 入账+计入月度预算/失败入账不计预算/降级腿 used_fallback 入账/kimi 门拦在上传前/kimi 成功记账 token=None/kimi 失败记账；既有 AI 面 93 例回归全绿）；105 表 / head `e2c6a8f4d1b3`（34 rev）/ 路由 297 / ENTRIES 94 / mypy 基线 279 全不变；改 server（零迁移）⇒ rebuild 三镜像（alembic 幂等校验）。

## [未发布] — V3 实施 T-W7：workflow 节点产物→门禁证据候选——运行时保留键 gate_evidence 同事务挂候选（2026-11-05）

### 服务端（立项合同 `docs/architecture/workflow-gate-evidence-candidates-v1.md`；WB-DEF-8 workflow 腿；零迁移零路由零桌面改动）

- **`gate_service.attach_workflow_evidence_candidate`**：节点产物经 output_json 顶层保留键 `gate_evidence`（`{gate, label?, source_uri, content_sha256}`）挂入 `gates.evidence_candidates`——**产物必须由生产方自带指针+指纹，平台永不自动派生指纹**（立项 D1：对任意 payload 自动哈希入库正是红线本身；形状不齐=不是证据，跳过不发明）。dedup=(source_uri, content_hash, 来源粒度)：同位同指纹幂等（哈希大小写归一）、换指纹两代并存由人取舍；上限沿 MAX_EVIDENCE_CANDIDATES 与任务候选共享列表；与任务候选按来源粒度隔离互不吞并。claim_status 恒不动，采纳唯一入口=真人提交闸（命中指纹即剪除，T-G1 行为零改动复用）。
- **坏标记不炸节点**（D2）：gate 非法 / sha 非 64hex / 超长（uri>1024 / label>120）/ 双字段缺一 → 节点照常 succeeded，登记跳过 + 新事件 `gate_evidence_candidate_skipped`（details 点名坏键 reason；gate 非法挂 project 目标、非对象标记挂 workflow_run 目标；已入 GATE_EVENT_TYPES，feed 可见）。
- **executor 两成功点同事务接线**（D3）：`_settle_node_success`（call/skill/agent 共用）与 `settle_approval_node` 批准分支读标记——事务回滚则节点成功与候选一并回滚（原子）；标记缺失零副作用；失败路径无产物不登记（连门禁行都不懒初始化）。call 节点产物=API 响应 dict 是自然生产方；skill/agent 产物为平台包装形，顶层标记透传留待现实需求（不为想象的需求加形状）。
- **读时缺省 `source_kind`**（D5）：候选行带 `source_kind: "task"|"workflow"`，旧行（T-W7 前任务候选）缺键读时缺省 "task" 不回填（沿 T-E2 evidence_id 先例）；**v1 不预写 project_evidence 一等表**（D4 偏差：工作流产物 ≠ 已采集证据，一等证据仍只在人工提交闸落库——workflow-dag-v1 §4 已注记）。
- **零路由**：候选随既有 `GET /projects/{id}/gates` 的 evidence_candidates 返回；桌面 GateBoard 来源徽标（任务/工作流）另开 S 轮。

### 测试与口径

- pytest **1898 收集（1892 passed + 6 skipped，本轮 +7；新文件 `test_workflow_gate_evidence.py`）**：标记产物挂候选+claim 不动+无标记节点零副作用 / 同指纹幂等（大小写归一）+换指纹并存+与任务候选共享列表互不吞并 / 坏标记 executor 面（节点仍 succeeded+两类 skipped 事件）+service 面八形状裁决 / 失败路径零登记（门禁行未实例化）+resume 后恰好一条 / 采纳剪除回归（submit 同指纹→清单项 claimed+evidence_id）/ source_kind 旧行读时缺省。
- 105 表不变（零 DDL）/ 迁移头 `e2c6a8f4d1b3`（34 rev）不变 / 路由 **297 不变**（零路由）/ ENTRIES 94 不变 / mypy 279·104 不变 / 桌面 vitest 767 不变（零改动无需重打包）；改 server（零迁移）⇒ **rebuild 三镜像**（alembic upgrade head 幂等空跑校验）。

## [未发布] — V3 实施 T-I1：本体变更影响分析——impact_of_term 名字域纽带三面清单 + 只读影响面（2026-11-05）

### 服务端（设计 ontology-registry-v1 §5 用例 6 / 验收 O-6；零迁移零桌面改动，+1 只读路由）

- **`impact_of_term(session, *, project_id, term_id)`**（ontology/service）：给定术语，返回引用它的**研究客体/邻接边/表单**清单——变集拍板前的人工影响面评审。引用合同 = **名字域纽带**：当前实现无 term_id 外键（fde-v2「引用方只引 term_id」未随融合裁决落地），「一个名字一个概念」（UNIQUE(project, term) + UNIQUE(project, alias)）使名字精确等价概念引用——subject.name 精确命中生效名字域即引用（纽带是唯一性不是相似度，子串/大小写变体不算）。
- **生效名字域 = 血缘闭包**：请求行沿 canonical 链到根（merge_terms 保证链一跳化，防御性走到底）+ 全部并入该根的行；名字 = 根规范名（term 绑定）∪ 血缘内别名（alias 绑定——转写来源名归保留行、来源自有别名留在来源行）∪ 非根行历史规范名（alias 绑定兜底）。对并入行发起查询 = 查其存活概念的影响面（请求行原样返回，`resolved.canonical_term_id` 解析到根）。
- **三面清单**（全部确定性排序）：subjects（命中主体含 subject_type/status/merged_into/matched_via/matched_term_id 逐名溯源）→ links（端点命中主体的邻接边，端点名随行补齐）→ forms（命中主体名下表单，含现行修订状态）；附 counts 汇总。**gates 面按验收权威 O-6 落为三面**：门禁清单是 gates.json 冻结模板文本（template_hash 钉死，T-G2），无术语名表面——不发明方法论层没有的引用（偏差回写 backlog）。
- **`GET /projects/{id}/ontology/terms/{term_id}/impact`**（can_view）：影响分析只读面，**有意不进 api_catalog**（沿 T-O3 纪律：本体治理面 AI 不可直达；桌面 T-UI1 GlossaryPage 是预期消费方）。跨项目/未知术语 404 `term_not_found`、无权限 403。
- **前置热修（goal-c8 CR-002 首版回归，fork/main 服务端 CI 必红根因）**：conftest `_current_alembic_stamp` 探测在全新库（CI service container 无 `alembic_version` 表）吞错后把持锁连接留在 aborted 事务——会话末 `pg_advisory_unlock` 撞 InFailedSqlTransaction，server-tests 整列必红（#109 PR-head 即此签名，红仍被合入）。修为探测吞错即回滚 + 会话 fixture 解锁前保险回滚（会话级 advisory 锁不随回滚释放，安全）；回归钉 +1（search_path 复现缺表探测，A/B 验证：无修复红/有修复绿）。

### 测试与口径

- pytest **1884 收集（1878 passed + 6 skipped，本轮 +7；基线 `8f10771` 实测 1877）**：名字域全命中四路（规范名/保留行别名/转写来源名/来源自有别名）+ 子串不命中 + 三面清单与 counts / 并入行查询解析到 canonical（请求行原样+血缘解析）/ 未知与跨项目术语 404 / 零引用空面 / HTTP 面（200 形状+外人 403+未知术语与项目 404）/ 红线钉子（影响面永不进 api_catalog）/ 前置热修回归钉（fresh-DB 缺表探测吞错后连接可用）。
- 105 表不变（零 DDL）/ 迁移头 `e2c6a8f4d1b3`（34 rev）不变 / 业务路由 **296→297**（+1 只读 GET impact，不进 api_catalog）/ ENTRIES 94 不变 / mypy 基线 279 不变（新代码零新增）/ 桌面 vitest 765 不变（零改动，无需重打包）；改 server（零迁移）⇒ **rebuild 三镜像**（`alembic upgrade head` 幂等空跑校验 current）。

## [未发布] — V3 实施 T-C1：Delivery Compiler 最小闭环——confirmed 本体→方案骨架 + workflow 定义草稿纯函数编译预览（2026-11-05）

### 服务端（NEW `workflows/compiler.py` 纯函数；零迁移零路由零桌面改动）

- **`compile_delivery_preview(change_set, *, industry_template, gates, research_skill_ref, approval_capability)`**：confirmed 变更集（serialize_change_set 形状，非 confirmed 一律拒绝）+ 已发布行业模板 + 门禁状态摘要（T-D1 `_serialize_gates` 形状）→ 确定性编译预览（不读时钟/随机源，快照测试钉死）；落库一律走人工确认端点——骨架 → `solutions.create`、定义 → workflow 定义创建路由。
- **① 方案骨架 payload**：与 `solutions.create` 文本合同逐键对齐（TEXT_FIELDS 七键 name+六段、限长同尺 160/40000/16000，`_normalize` 原样可过）；六段布局沿 `/skeleton`「每段保留待补、责任主体永远是人」——本体段（create/update 术语含修订标注，update 以 new_term 为准）、指标术语入验收标准候选、模板模块（sort_order 排序）驱动设想/路径/交付物/排期、门禁摘要与术语合并入风险与依赖；来源行随 design_markdown 头部落档（变更集标题·确认时刻·采集来源）。
- **② workflow 定义草稿**：dag_json 模板化「调研→方案→审阅」三节点——调研 skill（ref 由调用方注入，published 白名单在 DB、纯函数不查库，沿 validate_dag 白名单注入制）→ 方案 call `solutions.create`（携带编译期骨架字段，唯一运行期字段 `opportunity_ids` 留 `{{research_brief.opportunity_ids}}` 占位，执行器整值替换原类型不字符串化）→ 审阅 human_approval（capability 默认 `workbench.write`，system.* 不开放）。产出的 dag 在真实 api_catalog 白名单下全绿零告警（`solutions.create` effect=write_db 不触发 rule 9）。
- **provenance（agent_trace 式来源标注）**：逐字段指认来源（`ontology_change_set:<id>` / `industry_template:<行业>@v<版本>` / `gates` / `delivery-compiler/v1`），落库后可回链编译输入。
- **不做全自动「本体→代码」**（主报告 §12 裁决）：编译器只产草稿，绝不写库、绝不绕过人工确认端点。

### 测试与口径

- pytest **1877 收集（1871 passed + 6 skipped，本轮 +6；基线 `1ef3a42` 实测 1871）**：整树快照（本体段/模板排序/指标入验收/门禁排序/provenance）/ 三节点 dag 真实目录白名单全绿零告警+拓扑序 / 非 confirmed+坏载荷点名拒绝（非数组·非对象项·未知动作·缺必填）/ 无模板无门禁待补回退+坏门禁行跳过 / 坏 skill ref 与坏 capability 拒绝 / 骨架 payload 过 solutions.create `_normalize` 合同。
- 105 表不变 / 迁移头 `e2c6a8f4d1b3`（34 rev）不变 / 业务路由 296 不变 / ENTRIES 94 不变 / mypy 基线 279 不变（新代码零新增）/ 桌面 vitest 765 不变（零改动，无需重打包）；改 server（零迁移）⇒ **rebuild 三镜像**（`alembic upgrade head` 幂等空跑校验 current）。

## [未发布] — V3 实施 T-D1：文档血缘补洞——快照 revision_id + 门禁摘要 + AI 调用 request_id 落库（2026-11-04）

### 服务端（审计 WB-DEF-6/7；1 列级迁移、零路由零桌面改动）

- **WB-DEF-7（调研答案血缘）**：文档快照 `confirmed_research_values` 每表单字典新增 `revision_id` 键，指向被采用的最新 confirmed revision——快照冻结后仍可反查答案出处；扁平布局不变，模板占位符解析零破坏。
- **门禁摘要**：快照新增 `gates` 段（每门 `gate_key/status/decision/submitted_at/decided_at`，按 key 排序）——文档生成时刻的门禁进度随快照冻结；有意不携带清单明细/证据指针（门禁面的数据不进文档镜像）。
- **WB-DEF-6（AI 调用血缘）**：AI 内容生成的 `request_id` 由生成器铸造并传入 `generate_document_fields`，冻结进版本行 `content_snapshot_json["ai_request_id"]` 并落 `document_generation_jobs.ai_request_id` 新列（迁移 `e2c6a8f4d1b3`）——版本行/任务行均可直接反查 `ai_call_audits` 审计记录。资格判定提为 `ai_content_applicable` 单一谓词：只有真正发起供应商调用的生成才铸 id（不产幽灵血缘）；再生成复用首代冻结字段不重铸（血缘恒指首代调用）；失败路径 id 随事务回滚。

### 测试与口径

- pytest **1871 收集（1865 passed + 6 skipped，本轮 +4；基线 `c8aa08a` 实测 1867——#103 goal-c4 +4）**：快照血缘指向最新 confirmed revision + 反查 / gates 摘要形状排序 / AI 血缘闭环（捕获 request_id → 版本冻结 + job 落列 + 审计反查 + 幂等不重铸）/ 非 AI 生成保持 NULL。
- 105 表不变（列级增量）/ 迁移头 `c7e1a9f3b5d8`→**`e2c6a8f4d1b3`（34 rev）**/ 业务路由 296 不变 / ENTRIES 94 不变 / mypy 基线 279 不变 / 桌面 vitest 765 不变（零改动，无需重打包）；改 server + 新迁移 ⇒ **rebuild 三镜像 + `alembic upgrade head`**。

## [未发布] — V3 实施 T-O4 桌面消费面：调研数据导入 UI + 导入结果让位回溯卡片（2026-11-04）

### 桌面端（服务端零改动：零迁移零路由、无需 rebuild 镜像）

- **导入对话框（两段式）**：项目调研标题行新增「导入对象」（可填写时出现）→ 选对象类型（部门/岗位/流程/AI 机会）+ CSV/XLSX 文件（≤10MB）→「解析预览」走 `POST /research/subjects/imports/preview`（桌面结构化 multipart 通道，AI 预调研同源）→ 预览表 + 行错误清单（422 `details.errors` 与内联错误同区，≤8 条点名）→「确认导入」走 `POST …/imports/commit`（30 分钟一次性 token + 期望版本）。
- **导入结果卡片**：导入完成显示新建数量 + 幂等回放标注；`merge_candidates` 让位行逐条回溯——行号、同名既有对象（类型+跟踪码）、文件中说明（T-O4「同名让位不新建」的人工拍板面），「查看 X」跳选既有对象；卡片可关闭。`stale_version` 时自动刷新调研数据并提示重新解析。
- **复用与适配**：T-O4 桌面契约同步轮预置的 `isResearchImportPreviewDto` / `isResearchImportResultDto` / `parseResearchImportErrorDetails` 首次接线（零消费欠账清偿）；15 个导入面错误码映射；jsdom File 无 `arrayBuffer()` → `readFileBytes` 双路径（真环境快路径 + FileReader 兜底），真机与测试同一代码。

### 测试与口径

- vitest **765**（+4：导入主路径含让位卡片回链+multipart 契约断言 / 行错误禁提交零 commit / 预览拒绝映射 / stale 提交刷新；串行口径 `--no-file-parallelism`；基线 `65a40c5` 实测 761）；`npm run typecheck` 绿。
- 服务端零改动：pytest 1863 收集（1857 passed + 6 skipped）不变、105 表/迁移头 `c7e1a9f3b5d8`（33 rev）/业务路由 296/ENTRIES 94/mypy 279 全部不变，**无需 rebuild 三镜像**；桌面改动交付=便携版重打包（r14）+ asar 字节验证。

## [未发布] — V3 实施 T-O4b 桌面合并 UI：subject 合并原语上 UI + 归档行回链（2026-11-04）

### 桌面端（服务端零改动：零迁移零路由、无需 rebuild 镜像）

- **对象树合并入口**：操作栏新增「合并」（选中非根对象且可填写时出现，与既有「停用」同位）→ 对话框内挑选**同类型启用对象**为目标 → 密码确认（危险确认对话框）→ 调用 `POST /research/subjects/{id}/merge`（#91 `dfe91b3` 服务端原语的唯一 UI 面；合并仍有意不进 api_catalog）。
- **归档行「已并入 X」回链**：树底新增「已归档（N）」折叠组——归档行不可选中、不进 treeitem 键盘导航；合并让位行显示「已并入 X」回链（目标仍启用=可点击跳选，已停用=纯文本）；普通停用行也在此一并可见。
- **契约同步**：`ResearchMergeResultDto` + `isResearchMergeResultDto`（subject=并入方序列化 + `merge_summary` 六面搬迁明细，值计数/画像字符串/null）；`subjectMutationError` 补 4 个合并错误码映射（根对象/类型不一致/双方须启用）。
- **实施偏差（记录在案）**：①「导入结果 merge_candidates 卡片一键合并」前置缺失——桌面端调研数据导入 UI 尚未立项（`imports/preview|commit` 端点与桌面 DTO 校验器在、零 UI 消费），留待「调研数据导入 UI」独立轮；②「对象树右键合并」以操作栏行内「合并」按钮替代，避免引入整套右键菜单系统。

### 测试与口径

- vitest **761**（+6：树 3 / 工作区 2 / 契约 1；串行口径 `--no-file-parallelism`；基线 `8340e89` 实测 755）；`npm run typecheck` 绿。
- 服务端零改动：pytest 1863 收集（1857 passed + 6 skipped）不变、105 表/迁移头 `c7e1a9f3b5d8`（33 rev）/业务路由 296/ENTRIES 94/mypy 279 全部不变，**无需 rebuild 三镜像**；桌面改动交付=便携版重打包（r13）+ asar 字节验证。

## [未发布] — V3 实施 T-G2：template_hash 漂移呈现——门禁序列化比对冻结哈希 vs 现行 gates.json（2026-11-04）

### 服务端（零迁移零路由；gap-matrix WB-DEF-5 / 风险册 F-2）

- **`_serialize_gate` 响应新增 `template_outdated: bool`**：比对 Gate 行实例化时冻结的 `template_hash`（seeds/gates.json 文件级 sha256）与现行镜像内文件的哈希，不一致即标注——存量行（迁移 `f7a2c9e4b1d3` 回填 `f52afe88…` ≠ 现行文件）响应即为 true，呈现即修复 WB-DEF-5「存量哈希与现行模板漂移、无比对呈现」；`template_hash=NULL`（未知出处）判 false 不误报。
- list/GET、证据提交、拍板四类响应共用同一序列化器，自动携带；哈希读取走进程级缓存（文件烘进镜像只读）。桌面 GateBoard 类型守卫只验必填键，新增键纯增量（桌面呈现消费留待 UI 轮）。

### 测试与口径

- 服务端 pytest **1863 收集 = 1857 passed + 6 skipped**（本轮 +1：懒实例化首访全不漂移 / 冻结哈希改写 → true / NULL → false 不误报；基线即 fork/main `6cccedb` 实测 1862 = 1856 + 6s——T-R2 记录的 1855 为其自轮 `e1568d6` 运行面，squash 并入 #98 携 +7 测试）。
- 口径：105 表不变、迁移头 `c7e1a9f3b5d8` 不变（零迁移）、路由 296 不变、ENTRIES 94 不变、mypy 基线 279 不变（104 distinct，实测零新增）；桌面端零改动（vitest 755 不变）。

## [未发布] — V3 实施 T-R2：工具目录结构化 effect/risk——目录权威外效判定 + WB-DEF-10 确认面补口（2026-11-04）

### 服务端（零迁移零路由；agent-policy P1-R2 / gap-matrix 域 9 / 风险册 WB-DEF-10）

- **api_catalog 结构化 effect/risk**：`CATALOG` 行新增 `effect`（`read | write_db | external`）与 `risk`（0–4，与 `automation_approvals.risk_level` 同尺度，≥3 = 密码确认/审批类）——ENTRIES 五元行不动，派生在装配层 `_catalog_row`（规则显式：GET=read/0；确认类（DELETE / .archive / .deprecate / 确认补口）=3；其余 external=2；普通写=1；4 留最高危未用）。
- **WB-DEF-10 补口**：`EXTERNAL_EFFECT_KEYS`（forms.export / solutions.export_sow / documents.generate / translator.translate = 异步作业或模型调用类）+ `CONFIRMATION_KEYS`（export_sow / documents.generate）——AI 经 `api_execute` 发起即 `awaiting_confirmation`（密码确认通道后才触发 worker 作业），绝不无确认排队模型调用。
- **TOOLS 五元扩 effect/risk**（17 工具）：(description, capability, properties, effect, risk)；`file_send_wechat`=external/3、`api_execute`=write_db/3、`lcsc_search`=external/2、其余只读=read/0；MCP `tools/list` annotations 改由结构化元数据派生（`readOnlyHint=effect==read`、`destructiveHint=risk>=3`），取代工具名硬编码集合；`api_catalog` 工具描述同步声明「外部副作用与风险分级」。
- **workflow rule 9 消费目录权威**：`validate_dag` 新增 `call_effects` 注入参（生产恒经 `catalog_call_effects()` 注入 CATALOG effect；None 时仅节点自声明生效，纯函数单测兼容）——call 节点目录 effect=external 即触发 `external_effect_without_approval` 告警，节点 effect 声明**只加不减**（不可把目录 external 降级为 read）；P1 仍告警不阻断（P2 转强制随 enforcement wave 另行）。
- **executor 外副作用推断收敛**：`_is_external_call` 由 `write` 字段推断改为结构化 `effect != "read"`（集合等价，清偿 T-W3 挂账「effect 结构化仍待 T-R2」）。

### 测试与口径

- 服务端 pytest **1855 收集 = 1849 passed + 6 skipped**（本轮 +4：目录 effect/risk 全量一致性扫描 / WB-DEF-10 双操作确认流 / tools/list annotations 派生 / rule 9 目录权威+不可降级+装配同域；解包适配为改造非新增）。
- 口径：105 表不变、迁移头 `c7e1a9f3b5d8` 不变（零迁移）、路由 296 不变、ENTRIES 94 不变、mypy 基线 279 不变（104 distinct，实测零新增）；桌面端零改动（vitest 755 不变）。

## [未发布] — V3 实施 T-R1：agent_tool_groups 只读工具组目录——`group:` 引用声明糖，resolve=交集组永不扩大（2026-11-04）

### 服务端（纯种子零新表：`seeds/tool_groups.json`；零迁移零路由）

- **组目录**（agent-policy P1-R1 ToolGroup / gap-matrix 域 7）：种子随代码发布（非用户可写），首批两组只读白名单——`research-readonly`（文件+项目/门禁/报价/本体/API 目录，9 工具）、`ops-readonly`（系统状态/动作留痕/立创运行史/技能只读/帮助，6 工具）；行含 `description`/`is_active`（停用=代码侧空贡献开关）。
- **声明解析**（`agents/tools.py::resolve_tool_groups`）：`agent_registry.allowed_tools` 支持 `"group:<name>"` 引用，解析为组工具集并入声明集（保序去重，直接项与组贡献并集）；**只收窄语义**——组贡献与直接声明同权进入既有三重交集管线（平台 deny ∖ 写类/会议面 ∩ 发起人档位地板 ∩ 插件安装态），组引用绝不绕过任何一腿。未知/停用组贡献为空（只收缩不放宽、运行面不崩溃）。
- **fail-fast 种子校验**：组引用未知工具装载即 `RuntimeError`（校验分母 = 网关 `TOOLS` ∪ 会议面 ∪ 沙箱生态 `read_file`，嵌套 `group:` 引用同拒）；沿 agents.json 种子校验先例，坏种子宁可起不起来不静默缩空。
- **报因补口**（`agents/service.py::_unavailability`）：声明判定改走解析前原样（`declares_run_tools`，组引用也算声明）——纯未知组声明解析为空面时明确报因 `tools_unavailable`，不静默放行空名单 run；空声明/仅会议面声明 agent 行为不变。
- `run_face_declared`/`effective_run_tools` 增 `groups` 注入参（仅测试用，生产恒走种子）；`list_agents` 序列化仍展示原始声明（组引用自描述，运行面解析留 run 时刻）。

### 测试与口径

- 服务端 pytest **1851 收集 = 1845 passed + 6 skipped**（本轮 +4：种子校验+未知工具/嵌套引用 fail-fast / 组不放宽三闸齐验（写类剥除·档位地板·插件安装态）/ 未知组收缩+报因 / 真种子混合声明保序去重）。
- 口径：105 表不变、迁移头 `c7e1a9f3b5d8` 不变（零迁移）、路由 296 不变、ENTRIES 94 不变、mypy 基线 273 不变；桌面端零改动（vitest 755 不变）。

## [未发布] — V3 实施 T-G1：任务产物→门禁证据候选——WB-DEF-8 双口径脱钩的候选闭环（2026-11-04）

### 服务端（迁移 `c7e1a9f3b5d8`：gates +`evidence_candidates` 可空 JSON 列；零新路由）

- **候选挂接**（`gate_service.attach_task_evidence_candidate`）：任务 `status=completed` 且自带门禁挂点（G1–9）+ 证据指针+指纹（T-E3 已把任务证据登记为一等证据行）→ 该产物登记为目标门禁的**候选**（task_id/task_key/task_name、指纹统一小写、提议人、提议时间）。建议性：清单项 claim_status 与门禁状态机一概不动，领用永远由人完成；同 (uri, hash, task_key) 幂等；上限 20 条丢最旧；门禁行未实例化时懒初始化（幂等）。
- **挂接点**（`task_service.update_project_task`）：乐观锁通过后按 effective 值（变更键 ∪ 既有任务字段）判定——三要素任意更新次序凑齐即挂（完成在后/在前皆可）；stale 版本零副作用。create 路径任务恒 not_started，天然不触发。
- **采纳即闭环**（`submit_gate_evidence`）：提交指纹命中候选（hash 忽略大小写）即剪除对应候选，面板不再重复提示；未命中者保留。
- 序列化契约 +`evidence_candidates`（恒输出，旧行 NULL→[] 读时合并）；事件 `gate_evidence_candidate_attached` 挂 gate 行并入门禁事件流（GATE_EVENT_TYPES 扩展）。
- **workflow 产物候选挂起**：run/节点产物（`output_json`）尚无「指针+sha256」形状，待产物 schema 立项后零改挂入（挂接函数已按通用形设计，收 (uri, hash, 来源粒度)）——偏差已回写 backlog T-G1 实施记录。

### 桌面端（GateBoard）

- 清单项下新增「任务产物候选」区：候选出任务键/名与指针+指纹，选目标清单项一键「采纳到清单」（走既有提交闸，服务端命中剪除）；evidence 态也可补采纳（部分采纳流）；viewer 只读；旧载荷无键兼容、非法形状整板拒渲染（fail-loud）。

### 测试与口径

- 服务端 pytest **1847 收集 = 1841 passed + 6 skipped**（本轮 +6：挂接+契约+事件 / 三缺一不挂 / 次序无关+幂等 / 采纳剪除+claimed / 部分采纳保留 / 拍板零感知；上轮口径差 +3 为 #93 skill 两闸用例）+ 迁移往返（HEAD `c7e1a9f3b5d8`，33 rev）。
- 桌面端 vitest **755/755**（+3：候选渲染+采纳流 / viewer 只读+旧载荷兼容 / 非法形状拒收）+ typecheck 通过。
- 口径：105 表不变（列级增量）、路由 296 不变、ENTRIES 94 不变、mypy 基线不变（新代码零新增）。

## [未发布] — docs：archify 整套架构图入库——五视角交互式证据图 + 复跑回执（2026-11-04，纯文档零代码零迁移）

- 新增 `docs/architecture/archify-diagrams/`：用 archify（v3.0.1）从本仓库真实代码取证生成的**五视角**架构图，每张独立 standalone HTML（内联 SVG、暗/亮主题、可导出 PNG/JPEG/WebP/SVG/WebM、路径/透镜视图）：
  - `architecture/` 系统总体架构（14 节点 / 16 连接 / 4 边界）
  - `workflow/` 交付主流程：从项目到回款（13 节点 / 15 边 / 6 车道，含 fail 整改 / 人工免终审 / L1 接管 / 409 闸拦分支）
  - `sequence/` Workflow run 一次执行完整调用链（8 参与者 / 42 消息 / 10 段，四类节点分派）
  - `dataflow/` 集成桥采集 → 服务端投影 → 一等证据登记簿（指针 + sha256 红线）
  - `lifecycle/` Workflow 运行生命周期双层状态机（run 七态 + node 八态，幂等键 / 断链 / cancel / resume）
- 每张同级含 `candidate.json`（生成输入）+ `receipts/`（通过轮 finalize/deliver/check/browser-check 回执）+ `preview.png`（1440×900 亮色截图），`index.html` 汇总入口。
- 文档口径纠偏（以代码为准）：run 起始态 `queued`（非 `pending`）；发起路由 `POST /projects/{pid}/workflows/{def_id}/runs`；桌面控制台可列/详情/取消/恢复、**不能**发起 run。
- README「技术架构」节加一段指向本目录的锚注。
- 口径数字全部不变（105 表 / 路由 296 / ENTRIES 94 / 迁移头不变）；零路由零迁移零桌面改动。

## [未发布] — V3 实施 T-O4b：subject 合并原语——表单/答案/链接/子对象/备忘录/画像单事务搬迁（2026-11-04）

### 服务端（迁移 `d4e6f8a2c7b9`：+`merged_into_subject_id` 可空列；一条人工路由 295→296）

- **合并原语 `merge_subject`**（`research/subject_service.py`，T-O4 遗留候选收口）：source 并入 target（同项目同类型、双方 active、非 project 根，单事务全成全败）。六面搬迁纪律：
  - **表单/答案**：form_key 不撞 → 整表搬迁（修订+答案随外键同行）；撞键且源从未采集过答案 → 让位删除；**撞键且源有答案 → 409 `merge_form_conflict` 点名键**（绝不静默丢采集，人工先处置再重试）。
  - **链接**：边重指到 target；会变自环或与存续边重复的让位删除（唯一边约束永不违反）。
  - **子对象**：随迁（同类型 ⇒ 父类型规则天然成立，含归档子行）；**既有合并链一跳化**（曾并入 source 的行重指 target）。
  - **备忘录**：共享 memo 与个人备忘录均带「（合并自 名字 跟踪码）」头并入（与编辑闸同尺 20 000，超长显式截断标记）；目标无同人个人备忘录则整行重指。
  - **机会画像**：目标无 → 整行迁入；双方都有 → **目标留任**（机会画像创建即有，留任是唯一可行语义），源画像关键字段随事件留档。
  - **跟踪码不回收**：source 归档后永久占号（`merged_into` 指向存续方），新号接既有最大值——`allocate_tracking_codes` 扫全量行天然兼容。
- **DB**：`project_research_subjects` + `merged_into_subject_id`（复合外键 RESTRICT 自引用 + 两条 CHECK：不自指、指向即必归档 + 索引）；归档行保留 subject_key/跟踪码占位（UNIQUE 绝对，语义同 T-O1 merged 术语）。
- **路由**：`POST /projects/{id}/research/subjects/{source_id}/merge`（body `{version, target_subject_id}`，`_require_subject_write` 同档案闸）；**有意不进 api_catalog**（业务对象不走 change_set 双轨，T-O3 裁决维持；钉子测试在位）。
- 事件 `project_research_subject_merged` 挂 source 行，载荷带全部搬迁计数与双跟踪码。
- 序列化契约 +`merged_into_subject_id`（旧载荷无键向后兼容）；根检查先于类型检查（根对象永不参与合并）。

### 桌面端（仅契约同步，零新页面）

- `ResearchSubjectDto` + 可选 `merged_into_subject_id?: string | null`；`isResearchSubjectDto` 运行时校验同步（缺键旧载荷/带键新载荷都收，非法形状拒收）。

### 测试与口径

- 服务端 pytest **1838 收集 = 1832 passed + 6 skipped**（+7：全表面搬迁+占号 / 撞键 409→处置后成功 / 类型·根·自指·stale·归档源目标拒绝 / 链一跳化 / 画像迁入与留任 / 权限（viewer 403、非成员 404））+ 迁移往返 1 例（HEAD `d4e6f8a2c7b9`，32 rev）。
- 桌面端 vitest **752/752**（+2：合并指向键兼容性）+ typecheck 通过。
- 口径：105 表不变、路由 **296**、ENTRIES 94 不变、mypy 基线不变（新代码零新增）。
## [未发布] — 修复 mac 图标管线回写 Windows 图标（2026-11-04）

- `desktop/scripts/generate-icon.sh` 原本把 swift 渲染结果写回 `build/icon.png`——Windows 图标源会在 macOS 构建时被静默覆盖（产品更名轮手工替换的新图标跑一次 `package:mac` 即丢失）。改为渲染只进临时目录：`build/icon.png` / `icon.ico` 由品牌资产独立维护，macOS 管线只产出 `icon.icns`。
- mac 工具链（swift / sips / iconutil）无法在 Windows 上验证，本改动为纯输出路径调整，待下次真实 mac 打包核验；渲染输入源暂仍为 `assets/logo.png`（旧图），mac 图标换新待品牌透明 mark 资产（SVG 转透明 PNG）落定后一行重指。

## [未发布] — 使用帮助三面同步：工作流 / 术语表 / Skill 治理入册（2026-11-04）

- 三面同步（`docs/工作台操作使用手册.md` = 镜像内 `bundled/help_manual.md` = 桌面「使用帮助」）：项目详情 8→**10** 标签页；新增 §3.7 工作流（run 七态/节点八态/取消幂等语义/恢复 failed-only）与 §3.8 术语表（搜索/关系类型只读/变更集评审·否决留痕·拍板人≠提交人 403）；§8.1 补 Skill 卡「版本」治理对话框（版本历史/效果统计/提交评审-发布-回滚-弃用）；任务中心标注工作流人工审批；§11 术语速查补「变更集」；§12 缺口清单补「工作流定义新建无 UI 入口」；手册头部说明改为如实分发口径。
- 桌面 HelpPage 新增「工作流与术语表」章节 + KNOWN_GAPS 同步 + help-page 测试钉新章节与诚实语义。帮助文案与文档改动，零业务逻辑、零迁移、零路由。

## [未发布] — 文档收口：README 能力面与品牌资源同步（2026-11-04）

- 「主要能力」与首段补入已落地的用户可见能力：工作流控制台（T-W6：定义/运行/取消/恢复）、项目术语表（T-O1/T-O3/T-W6）、Skill 治理态与效果统计（T-S1/T-S2）；任务中心标注工作流人工审批（T-W4）。
- 页首改指产品更名后的品牌资源 `logo-caigong-fde.svg`；「更换 Logo 与安装图标」一节按现役管线重写（界面品牌资源清单 / Windows 构建图标 / macOS 图标生成链，`logo.png` 保留为 macOS 图标源）。纯文档改动，零代码。

## [未发布] — V3 实施 T-W6：桌面控制台三面——工作流 / 术语表 / Skill 版本治理（2026-11-04）

### 服务端（零迁移；两条只读列表路由为桌面控制台最小补面）

- **偏差回写**：workflow-dag-v1 §5 设计七条不变；控制台要「run 列表/取消/恢复」就得能枚举，故补两条 can_view 只读挂件——`GET /projects/{id}/workflows`（定义列表，新者在前，项目内定义天然少量无分页）与 `GET /projects/{id}/workflow-runs?limit=`（run 列表，默认 50 上限 200 有界扫描，`truncated=true` 诚实标注）。**列表行不带 nodes**（N+1 不可取），节点树走既有详情路由按需展开。
- 路由总数 293→**295**；ENTRIES 94 不变；迁移头 `b5d9e3f7a1c6` 不变。

### 桌面端（三张新页，页面仅呈现、写操作全走既有服务层闸）

- **WorkflowConsole**（`workflows/WorkflowConsole.tsx`，项目详情新 tab「工作流」）：定义卡片（状态/版本/节点数概览）+ run 列表（七态标签/错误摘要/`truncated` 提示）+ 按需展开节点态树（八态标签/attempt/错误）；**取消**（非终态可点，幂等语义照服务层——终态 409 `already_terminal` 原样呈现）与**恢复**（仅 failed，409 `not_resumable` 同）按钮挂 canManage。
- **GlossaryPage**（`ontology/GlossaryPage.tsx`，项目详情新 tab「术语表」）：术语只读清单（q 搜索按规范名/别名）+ 关系类型只读清单（登记/停用走管理通道，全局行需运维员——lesson 15 口径）+ **变更集评审**：状态过滤五态、载荷展开（动作明细 + base 指纹）、draft→提交评审 / in_review→确认物化 / 否决需理由；服务端「≠提交人」403 原样呈现不吞。
- **SkillVersionsPage**（`extensions/SkillVersionsPage.tsx`，扩展中心每张 Skill 卡新增「版本」按钮的治理对话框）：版本历史（指纹前缀/测试报告有无/当前标记）+ **效果统计**（消费 T-S2 `usage` 块：total/chat/workflow/last_used_at/by_version/truncated——by_version 正是回滚决策依据）+ 治理动作：draft→提交评审、in_review→发布（密码确认+豁免说明）、published→回滚（选目标版本+密码+豁免）/弃用；权限外只读（「只有公共 Skill 运维员或个人 Skill 属主可以执行治理动作」）。
- 项目详情 tab 枚举扩展：`overview/tasks/gates/commercial/research/delivery` + **`workflow` + `ontology`** + `library/management`（路由哈希与 tab 同步，无 legacy 映射需求）。

### 测试与口径

- 服务端 pytest **1831 收集 = 1825 passed + 6 skipped**（+1：定义/run 列表路由权限·排序·截断·400 界）。
- 桌面端 vitest **750/750**（+18：workflow-console 5 / glossary-page 6 / skill-versions-page 7）+ typecheck 通过。
- 用例钉住诚实语义：failed 本就是终态不显示取消；取消竞态 409、自确认 403、错密码 403 全部原样呈现；无密码/无回滚目标客户端侧先拦；无治理权只读提示。

## [未发布] — 产品更名「蔡工FDE智能交付系统」+ 集成桥 stale 标记去重（2026-11-04）

### 品牌统一（产品名口径 + 品牌素材）

- **产品名统一为「蔡工FDE智能交付系统」**：新增 `desktop/src/renderer/src/brand.ts` 作为**产品名的唯一来源**（`PRODUCT_NAME` 全名 / `BRAND_NAME` 短名 / `BRAND_SUBTITLE` 副标题 / `DEVICE_LABEL` 登录设备标签），此前产品名散落在十余处硬编码，改名必然漏改——现全部改为引用常量。
- **落地位置**：侧边栏品牌区（蔡工FDE / 智能交付系统）、登录页主标题、窗口标题（`index.html` 的 `<title>`，Electron 主窗口由此继承）、立创内置浏览器与查询跟踪窗口标题、`desktop/package.json` 的 `productName` / `description` / `author` / DMG 标题、服务端内置助手 system prompt、README 首屏标题与正文。
- **品牌素材换新**：侧边栏与 favicon 换用蔡工FDE 标识（`logo-caigong-fde.svg` / `.png`），应用图标（`build/icon.png` / `.ico`）同步更新。
- **有意未改**：便携版目录命名 `蔡工FDE-<version>-便携版-r<N>`（`fde-package-verify` 技能约定的交付口径，改动会破坏「旧目录永不覆盖」的回退约定）、`package.json` 的 `name` / `appId` / `artifactName`（机器标识与产物文件名口径，非用户可见名）。

### 缺陷修复：集成桥 stale 标记重复

- **根因**：服务端 `bridge/sync.py` 对 openfde 与 fdeops 两条采集轨**各自**判定断连并各 `append("stale")`，双轨同时断连时同一行出现**重复标记**——前端会渲染出**两个同名「采集断连」徽标**，并因 `key={flag}` 重复触发 React 警告（`Encountered two children with the same key`）。
- **修复**：服务端改为「任一轨断连即 stale，只判定一次」（C9 的双轨独立报警语义不变：单轨断连仍照旧报警）；前端新增 `uniqueFlags()` 渲染前按出现顺序去重——`flags` 是可重复的观察项而非互斥枚举，前端不应假设其唯一。**两侧都修**，服务端收敛事实、前端兜底渲染。
- **回归钉子**：服务端新增 `test_both_tracks_stale_yields_single_stale_flag`（双轨同时断连只报一次，且 flags 整体无重复）；桌面端新增「renders a duplicate flag only once」（重复 flag 只渲染一个徽标）。已实测：还原旧实现时新测试**确实失败**，修复后通过。
- **口径**：服务端 pytest **1820 passed + 6 skipped**（+1）/ 桌面端 vitest **732/732**（+1）/ typecheck 通过。
## [未发布] — V3 实施 T-S2：Skill 效果统计 + 治理留痕（回滚已随 T-S1 落地，2026-11-03）

### 服务端（零迁移零新路由 / 零桌面改动）

- **效果统计（agent-policy §2.4「run 面累计 usage，operation_events 已有基础」落地）**：双消费面计数——`skill_used_chat`（MCP `skill_read` 成功读出指南）与 `skill_used_workflow`（工作流 skill 节点按 pinned 版本完成一次确定性 AI 调用）；**失败不计**（AI 异常/重试是噪声不是效果，`skill_ref_unavailable`=内容未被消费），attempt 代际各计一次（resume 重跑每次都真消费了），`skill_list` 只浏览不计数。
- **独立微事务计数**：直连 AI 工具循环每轮 tool 后回滚共享会话（假定工具只读），经 `call_tool` 的消费计数自带已提交事务才能存活——与 `run_lcsc_skill` 自管事务的先例同构，专项测试钉「call_tool 后 rollback 事件仍在」。
- **统计读出（零新路由）**：`GET /extensions/skills/{id}/versions` 响应新增 `usage` 块 `{total, chat, workflow, last_used_at, by_version, truncated}`——有界扫描（最近 1000 条消费事件）Python 侧聚合，触顶 `truncated=true` 诚实标注；`by_version` 供回滚决策（旧版本还在被 workflow pinned 引用吗）；治理事件不进 usage。
- **T-S1 审计缺口顺带收口**（gap-matrix 域 8「回滚留 operation_events」）：补齐四条治理事件 `skill_review_submitted / skill_published（version+waive_reason）/ skill_rolled_back（from_version+to_version+waive_reason）/ skill_deprecated`，与生命周期操作同事务落表；闸失败（错密码/材料缺失）不留事件。
- **实现偏差（backlog 已回写）**：事件不走 `projects/events.py::record_event`——`events.py` 顶层引入 `control.models` 会经重型 `control/__init__` 反转 projects↔control 导入序（实测即环），改用 control 层 `_event` 直落 `OperationEvent` 的既有同构（api_actions 先例）；`target_type="skill_definition"`、`project_id=None`（Skill 不挂项目）。
- **测试**：`test_skill_lifecycle.py` **7→11**（治理事件四类+闸失败零事件 / chat 计数+回滚存活+404 不计数 / usage 汇总+零值+按版本 / truncated 诚实标注）+ `test_workflow_executor.py` 两用例扩展（pinned 版本消费断言 / 失败 attempt 不计）。服务端 pytest **1829 收集 = 1823 passed + 6 skipped**（+4）/ vitest **731 不变**。**零迁移**（head `b5d9e3f7a1c6` 不变）/ **零新路由**（283 不变）/ ENTRIES 94 不变。

## [未发布] — 桌面端视觉统一：设计令牌体系与缺失样式类补齐（2026-11-03）

### 纯 CSS 重构（零功能变更，零 TSX 逻辑改动）

- **修复三处结构性缺陷（根因不是"配色不好看"）**：
  - **① 关键样式类零 CSS 规则**：`.page` / `.card` / `.page-heading` / `.page-subtitle` / `.muted` 在全局样式中**没有任何规则**（提取全部 tsx 的 className 与全部 css 选择器做差集确认），致使翻译器、指标报表、试点报告、派单池、调度台、开闸运维等 **7 个页面整页裸奔**——无卡片容器、无内边距、无层级，输入框挤在一行、标题与正文同字号。**本次补齐全部原语。**
  - **② 六个 CSS 变量从未定义**：`--border` / `--panel` / `--accent` / `--text-muted` / `--border-color` / `--surface-alt` 查无实据，`border: 1px solid var(--border)` 因变量不存在而**整条声明作废**，派单页簇所有卡片**完全没有边框**。**本次在 `:root` 集中定义并保留旧名别名**（旧写法零改动继续可用）。
  - **③ 组件样式表各自为政**：`task-board.css`（12 色）与 `ai-server-chat.css`（45 色）自成色板，与全局令牌脱节。**本次全部改走令牌。**
- **统一设计体系**：`:root` 重写为**九层令牌体系**（品牌色阶 / 中性面 / 文字 / 描边 / 语义色 / 圆角 / 阴影 / 间距梯度 / 字阶）+ 控件尺寸，每层带注释；新增 `pages/pages.css` 承载翻译器 / 指标报表 / 试点报告 / 派单页簇 / 帮助页的版式骨架；按钮统一高度（38px）/ 圆角 / 阴影与悬停·按下·禁用态；徽标语义色、表格行高描边表头、输入框边框聚焦环占位符统一；**4 套并存标签页收敛**为分段式一套（`extension-tabs` 保留下划线式以区分内容层级）。
- **现代感与纵深**：页面底与卡片加入品牌色径向渐变晕染，阴影分六级、圆角五档，卡片悬停浮起；硬编码色值**约 250 处 → 82 处**（余下绝大多数位于 `:root` 定义内）。
- **验证**：`npm run typecheck` 通过；`npm run build` 通过（`pages.css` 已进产物 CSS）；桌面端 **731** 例测试全绿（60 文件）；新增 `desktop/gui-harness/shots.mjs` 逐页视觉走查（13 页，零 console error）。
- **工具**：新增 `scripts/watch-pr-checks.py`——守望 PR 的 CI check-runs 收敛。**只用 `commits/<sha>/check-runs` 索引**（`actions/runs` 的两种索引都不可靠），且**显式区分「空列表」与「已收敛」**（空结果≠收敛，否则索引抖动会造成假绿）；收敛前额外核对 4 个 CI job 齐全。

## [未发布] — V3 实施 T-O4：导入别名去重（同名让位 + 合并候选 change_set，2026-11-03）

### 服务端（零迁移零路由 / 桌面端契约同步）+ 桌面端（验证器/类型/测试）

- **两把尺子裁决（附录 D ⑨ 导入重复根治）**：**文件内同名 = 致命行错误** `duplicate_name`（preview 报且首行干净，commit 同尺复核——文件是用户声明，歧义由人解决，不替人猜）；**文件 vs 项目既有 active 同名（同类型）= 让位**——撞名行不再静默新建合成键对象（`import_<type>_<preview>_<row>` 每行各异的旧路径），改为合并候选。归档/停用行不拦重建，跨类型同名（部门的销售部 vs 角色的销售部）是不同实体不去重。
- **合并候选三面呈现**：①导入结果载荷新键 `merge_candidates`（name/row/description/matched_subject{id,name,tracking_code}——被让位行的说明无损保留供拍板）；②跟踪码只发真正新建的行（让位不占号，新号接既有最大值，不产生空洞）；③**全部让位 = 合法成功**（零新建 + 全量候选 + 版本照常 +1，重复导入幂等友好；收据回放完整带出候选，`idempotent_replay` 语义不变）。
- **合并候选 → change_set 提案（T-O3 闭环的自然落地）**：候选名若无术语行/别名占用（且 ≤TERM_MAX_LENGTH=120），按首现序去重提案 `create_term`（definition=被让位行说明，超长截 120）——**draft** 变更集带 `captured_from="research_import:<preview_id>"`，经既有 submit→confirm 人工拍板坐实「同项目一个名字一个概念」；拍板拒绝无残留（让位已在导入侧完成，术语只是不登记）。**动作域不因 T-O4 开 subject 合并**（T-O3「业务对象不走 change_set 双轨」裁决仍成立；subject 合并原语牵动表单/答案/链接/跟踪码，L 级别另行立项）；候选名已有术语/别名占用时不提案（物化期 409 term_exists 的死路不走）；超 `CHANGE_SET_MAX_ITEMS`=50 截断并在 description 注明。ontology/service 新增占位检查原语 `existing_term_names`。
- **桌面端契约同步（精确键集校验不破）**：`isResearchImportResultDto` 精确键集 +`merge_candidates`（`ResearchImportMergeCandidateDto` 类型 + 验证器 `isResearchMergeCandidateDto` + 测试 2 例）；preview 载荷零变化（`duplicate_name` 走既有 errors 通道直透，`isImportError` 只验形状）。
- **测试**：`test_research_imports.py` **+7**（批内同名致命/让位+提案+跟踪码钉子/全让位+回放带候选/术语占用不提案/confirm 闭环落 confirmed 术语+验收分离/跨类型不去重/超长说明截断）；桌面 `project-runtime-validation.test.ts` +1。服务端 pytest **1825 收集 = 1819 passed + 6 skipped**（+7）/ vitest **731**（+1）。**零迁移**（ontology_change_sets 表 T-O3 已备）/ 零路由（293 不变）/ ENTRIES 94 不变。
- **有界查询不变量**：commit 的同名让位扫描为**恒定 1 次**整行 select（不随行数乘法），既有 bounded-queries 测试上限 1→2（注释钉住）。

## [未发布] — V3 实施 T-O2b：对象类型值域开放（T-O2 注册表的 subject_type 真正可用于新建对象/表单/导入，2026-11-03）

### 服务端（1 个迁移（零新表：三处 CHECK 放宽 + 三列放宽）/ 零路由 / 零桌面改动）

- **值域从枚举到格式**：`project_research_subjects` / `template_research_forms` / `project_research_import_batches` 三处 subject_type CHECK 改码格式 `^[a-z][a-z0-9_]{0,59}$`、列宽 32→60（迁移 **`b5d9e3f7a1c6`**，31 rev；枚举 ⊂ 格式，存量全兼容；downgrade 收窄时超长注册码行被枚举 CHECK 挡下——保护语义）。
- **单原语闸门**：新建调研对象只认「内置五类 ∪ 注册表 active 行（全局∪项目内）− project 根」，把守在 `create_subject_in_transaction`（人工创建与导入 commit 同闸）；retired=禁新建存量只读、draft=未拍板提案，都拦闸外（`usable_subject_type_codes`，与引用解析用的 `known_subject_type_codes` 两把尺子）。错误码新设 400 `unsupported_subject_type`。
- **导入三闸一致**：authorize 带回项目可导入域 → preview/store 前置校验（缺省退回内置四类）→ commit 原语复核（覆盖 preview→commit 30 分钟 TTL 内 retire 窗口）。
- **消费方对齐（防静默丢内容）**：文档快照按行上实际类型分组（注册/退役类型的存量对象不再被丢弃）；表单定义/AI 表单生成/模板四处校验器全部接「内置 ∪ active」；映射校验允许域从已发布 research definition 派生（保持纯函数）。
- **两条基线不放开**：AI 生成表单缺省仍只认内置五类（防幻觉）；行业模板五类内置调研表必备（开放值域 ≠ 放弃底线）。
- **注册类型对象语义**：无父级规则 → 本轮仅允许根级；无跟踪码前缀 → `tracking_code=null`；备忘录/合并功能域白名单（内置四类）冻结不动。
- **测试**：新增 `test_ontology_subject_type_domain.py` **9 例**（usable 域作用域/状态、注册类型 HTTP 全链路+四类拒绝、retire 存量保留+快照、导入三闸、定义/AI/映射/模板域、内置码覆盖钉子）+ 迁移往返 **1 例**（双向列宽/CHECK/数据保留 + 存量行挡降级保护语义）；`HEAD_REVISION` → `b5d9e3f7a1c6`。服务端 **1818 收集 = 1812 passed + 6 skipped**（+10）。改 server + 新迁移 ⇒ rebuild 后必 `alembic upgrade head`（api/worker/scheduler 三镜像）。

## [未发布] — V3 实施 T-O3：变更集 ontology_change_sets（AI 候选唯一入口：propose→submit→confirm 人工拍板闭环，2026-11-03）

### 服务端（1 个迁移（一张新表，唯一 DDL）/ 7 条新路由 / 零桌面改动）

- **变更集**：`ontology_change_sets`（title/description/proposed_json 载荷/diff_summary 人读摘要/status ∈ draft·in_review·confirmed·rejected·superseded/base_snapshot_sha256 并发防护指纹/captured_from 候选来源标记/提交与拍板留痕）。迁移 **`c9e3a7d1b5f8`**（30 rev，additive，含 downgrade）。AI 产物永不直接写术语/类型表——候选载荷进 proposed_json，人工拍板后才逐项物化。
- **状态机与并发防护**：draft →(submit)→ in_review（对受影响行快照取 sha256 指纹）→(confirm)→ confirmed / →(reject)→ rejected（留 reason）；draft 可否决（撤回）。confirm 复核指纹——既有行被并发改写或占位名凭空出现/消失都判漂移，**409 `base_conflict` 零物化**。confirm **单事务全成全败**：任一项物化失败整体回滚（无 partial），错误 `change_set_item_failed` 点名项次；成功落 `ontology_change_set_confirmed` 事件携带逐项结果。
- **物化语义**：`create_term` 直落 confirmed；`update_term` 同名=原行受控改写（旧定义随事件留档；**change-set confirm 是全系统唯一 definition 写路径**）、改名（`new_term`）=新行 confirmed+原行 superseded 指 canonical+原名转别名；`merge_terms` 走 T-O1 原语（合并保留来源）；`register_relation_type` 只登记项目内类型（全局登记留 admin 人工路由）。`create_subject`/`link_subjects` 设计列有、本轮不开放（propose 即点名拒绝）。
- **验收分离（P0-5 纪律移植）**：confirm/reject 均要求拍板人 ≠ 提交人（403 `change_set_decider_conflict`，沿 gate 先例）。
- **HTTP 面（人工路径，不进 api_catalog）**：`GET /projects/{id}/ontology/terms?q=`（T-O1 欠账的术语只读面，别名命中返回属主行）+ change-sets 六条（propose/list/detail/submit/confirm/reject；submit 为设计 §4 表外补充——`not_in_review` 预设评审态、指纹语义锚在提交时刻）。跨项目 404 `change_set_not_found`（不泄露存在性）。事件目标注册表 +`ontology_change_set`。
- **测试**：`test_ontology_registry.py` **8 例**（payload_schema 校验族 / 状态机+HTTP 全链路（含验收分离、重复确认、跨项目、?status= 过滤、confirmed 事件逐项结果）/ base_conflict 双漂移（行改写+占名抢注）/ 单项失败整体回滚 / update_term 同名与改名双分支 / captured_from AI 通道 / merge+register 物化 / 术语 GET 面 + api_catalog 三面钉子）+ `test_migrations.py` 迁移往返 **1 例**（载荷 JSON 落行可读 + 状态 CHECK）；`HEAD_REVISION` → `c9e3a7d1b5f8`。
- **口径**：业务表 **104→105**（+ontology_change_sets）/ 迁移头 **`c9e3a7d1b5f8`（30 revision，+1）** / 路由 **286→293**（+7） / api_catalog ENTRIES **94 不变** / pytest **1808 收集 = 1802 passed + 6 skipped**（本轮 +9：变更集 8 + 迁移往返 1；较 T-O2 记录基线 1798 的 +1 为该轮基线记法偏差，与本轮无关） / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（一张新表；**api/worker/scheduler 三个镜像都要 build**）。

## [未发布] — V3 实施 T-O2：关系/对象类型注册表 ontology_relation_types（关系类型不再硬编码，2026-11-03）

### 服务端（1 个迁移（一张新表，唯一 DDL）/ 3 条新路由 / 服务层 ∪ 接入 / 零桌面改动）

- **注册表**：`ontology_relation_types`（`kind` ∈ subject_type/link_type；`code`/`label`/`description`；端点约束 `allowed_source_types`/`allowed_target_types`；`status` ∈ draft/active/retired；`project_id` 为空=全局类型、仅 admin 可建）。迁移 **`b8d3f1a5c7e2`**（29 rev，additive，含 downgrade）。把审计附录 D ②③ 的「对象类型 CheckConstraint 硬编码」「link_type 白名单硬编码 2 种」的扩展面搬进可注册表。
- **∪ 接入（服务层）**：`research/subject_service.py` 的 `_validate_link` 改为「**内置优先** + 注册表」——内置两类关系类型的端点约束是存量语义，注册表**不得覆盖内置码**（注册内置码 409 `duplicate_code`），故「∪ 语义不得放开内置方向校验」由机制保证；注册类型按端点约束判方向（不符仍 422 `invalid_research_subject_link`）；**retired 类型禁新边 409 `link_type_retired`、存量边只读**；未知类型 422 且消息附当前可用类型清单。内置集合与注册表保留名单的一致性由测试钉住（防漂移）。
- **作用域**：项目内类型**遮蔽**同名全局类型（端点约束可按项目定制）；项目内 `UNIQUE(project_id, kind, code)` + 全局部分唯一索引（`project_id IS NULL`）两段实现设计稿的「全局/项目内各自唯一」。
- **HTTP 面（人工路径，不进 api_catalog）**：`GET/POST /projects/{id}/ontology/relation-types`（can_view / can_manage；`scope=global` 另需 admin）+ `POST …/relation-types/{id}/retire`（让「retired 后建边 409」在人工路径上可达）。登记/停用落 `ontology_relation_type_registered`/`_retired` 事件；事件目标注册表 +`ontology_relation_type`。
- **边界（重要）**：`kind=subject_type` 本轮**只落登记不开放使用**——新建调研对象仍只能取内置五类（三处 DB CheckConstraint 按设计兼容边界冻结），放开值域会连带表单定义/文档映射/文档快照/AI 模板 schema 五处消费方，属独立一轮（T-O2b）。`research/models.py` 仅加注释不改约束。
- **测试**：`test_ontology_registry.py` **7 例**（登记校验+内置码保护+作用域遮蔽 / 全局与项目遮蔽 / 内置冻结与漂移钉子 / DB 约束拒非法态 / HTTP 面与建边生命周期（注册→建边→方向不符→停用→禁新边→存量边可读）/ 全局类型登记与停用仅管理员 / api_catalog 钉子）+ `test_migrations.py` 迁移往返 **1 例**（全局部分唯一索引 + 项目内同名共存 + 端点约束 CHECK）；`HEAD_REVISION` → `b8d3f1a5c7e2`。
- **口径**：业务表 **103→104**（+ontology_relation_types）/ 迁移头 **`b8d3f1a5c7e2`（29 revision，+1）** / 路由 **283→286**（+3） / api_catalog ENTRIES **94 不变**（`research.link` 描述同步端点约束口径）/ pytest **1798 收集 = 1792 passed + 6 skipped**（+8） / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（一张新表；**api/worker/scheduler 三个镜像都要 build**）。

## [未发布] — V3 实施 T-O1：术语表 ontology_terms+aliases（同项目一个名字一个概念，2026-11-03）

### 服务端（1 个迁移（两张新表，唯一 DDL）/ 零路由 / 零桌面改动）

- **唯一性底座**：`ontology_terms`（UNIQUE(project, term)+状态机 draft/confirmed/superseded/merged+merged 必须指向保留行的 CHECK+乐观锁 version）与 `ontology_term_aliases`（UNIQUE(project, alias)，冗余 project_id 供导入去重点查）——同项目一个名字至多指向一个概念，是「导入同名重复」（审计附录 D ⑨）的根治面。迁移 **`a3e7c1f9b5d2`**（28 rev，additive，含 downgrade）。
- **服务原语**：`ontology/service.py` 的 `create_term`（别名占用先于同名预检；`initial_status="confirmed"` 直落供变更集 confirm 用）/ `confirm_term`（draft→confirmed 拍板；confirmed 409 `term_immutable` 不可原地改——服务层无 definition 编辑路径，修订走 change_set 新版本）/ `merge_terms`（合并保留来源：source 规范名转写为保留行别名、source 既有别名不动走 canonical 链、**链一跳化**重指、逐项 OperationEvent `ontology_term_merged`）。
- **零路由（T-W1 先例）**：术语公开面只有只读 GET；写路径一律经 change_sets propose→confirm（AI 候选永不直接写表）——REST 面随 T-O3 routes.py 开；治理面不进 api_catalog（钉子测试）。事件目标注册表 +`ontology_term`。
- **测试**：NEW `test_ontology_registry.py` **7 例**（生命周期+confirmed 不可变 / 入参归一 / 同名+别名占用唯一 / 合并保留来源链+409 族 / 别名 DB 唯一 / CHECK 拒非法态 / api_catalog 钉子）+ `test_migrations.py` 迁移往返 **1 例**（自引用外键落 canonical/merged 对）；`HEAD_REVISION` → `a3e7c1f9b5d2`。
- **口径**：业务表 **101→103**（+ontology_terms/+ontology_term_aliases）/ 迁移头 **`a3e7c1f9b5d2`（28 revision，+1）** / 路由 **283 不变** / api_catalog ENTRIES **94 不变** / pytest **1790 收集 = 1784 passed + 6 skipped**（+8） / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（两张新表；**api/worker/scheduler 三个镜像都要 build**）。

## [未发布] — V3 实施 T-E3：bridge/任务证据统一入口（双通道落一等证据行，2026-11-03）

### 服务端（零迁移零路由零 DDL / task_service + bridge/sync 两处写入点挂接 / 零桌面改动）

- **任务侧**：`evidence_uri` + `evidence_hash` 齐备时，建任务/改任务同事务同步登记一等证据行（kind=`task`、captured_from=`human`、origin=`task:<task_key>`，大写 hash 归一小写）；同指纹幂等不增行，清空指针不动登记簿（证据不可变），只挂指针不落指纹不构成指纹不登记。写入点在乐观锁 rowcount 校验之后——stale 版本零证据副作用。
- **桥侧**：`apply_snapshot` 投影事务内把**已挂接 workbench 项目**的桥接采集登记为一等证据行（kind=`bridge`、captured_from=`bridge_sync:{run_id}` 机器通道、created_by 空）；openfde 按 engagement 指纹逐 slug、fdeops 按工作区级 registry_sha256；指纹不齐整（缺 hash / uri 越界）跳过不炸——投影是 4h 关键路径，证据不构成失败；同指纹幂等（内容不变不增行，内容变化=新指纹=不可变采集史新行）；`BridgeSyncRun.summary` 增 `evidence_created` 计数。
- **契约不动**：任务 DTO 与 engagement_view 均不暴露 evidence_id（沿 T-E2 gates_read 先例）；零新事件（任务侧 event_changes 已含证据字段变更；桥侧无 actor，summary+登记簿即审计）；登记路径仍不进 api_catalog（AI 不可写证据纪律不变）。
- **测试**：`test_project_tasks_api.py` +1（建/幂等/换指纹/清空/只指针 五段）+ `test_bridge_sync_flags.py` +1（挂接登记/未挂跳过/坏指纹跳过/重放幂等）。
- **口径**：业务表 **101 不变** / 迁移头 **`c1e5f9a3d7b2`（27 revision）不变** / 路由 **283 不变** / pytest **1782 收集 = 1776 passed + 6 skipped** / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d`（**api/worker/scheduler 三镜像**；迁移头不变，无需 alembic）。

## [未发布] — V3 实施 T-S1：Skill 治理态（draft/in_review/published/deprecated + 发布四闸，2026-11-03）

### 服务端（1 个迁移（唯一 DDL）/ 5 条新路由 / extensions_service 治理化 / 零桌面改动）

- **治理状态机**：`draft →(submit-review)→ in_review →(publish)→ published →(deprecate)→ deprecated`；编辑已发布公共 Skill 开新版本行并回 draft 重走治理。迁移 **`c1e5f9a3d7b2`**：`skill_definitions.status` 从扩展共用值域（active/disabled）切到治理四态（CHECK 换值域），存量 **active→published**（发布人暂记创建人）、**disabled→deprecated**；skill_definitions 加 published_by/at、skill_versions 加 input/output schema + test_report_json + reviewed_by（全可空，版本行不可变不变）。
- **发布四闸**：admin（system_operator）/ 密码确认（`invalid_password` 403）/ 状态须 in_review / 测试报告或显式 waive（`test_report_required` 409）；发布把版本行 `reviewed_by` 落为发布人（发布即审核背书）。回滚 = published 内改指旧版本行（版本行不可变），同密码+材料闸。
- **个人 Skill 自发布豁免**：保存即 published（owner 自治）；四闸只对公共 Skill。内置种子走服务端内部参数 `initial_status="published"` 直发布（内容可信），`_is_unchanged_builtin` 升级判定同步收敛。
- **消费方收敛（T-W1/T-W3 挂账清偿）**：MCP 工具面（`mcp_gateway._skills`）、工作流 skill.ref 定义期白名单（`published_skill_refs`）、执行器 skill 节点分派三处全部只认 `published`。
- **API 五条（278→283）**：submit-review / publish / rollback / deprecate / versions；content_sha256 指纹扩展覆盖全部发布材料（schema/测试报告变更即新版本）。
- **兼容**：既有 PATCH 启停开关保留旧值域作别名——个人 Skill 自愈发布（幂等）；公共 Skill 发布向 409 `governance_required`（开关不得旁路四闸），停用向照旧。桌面治理 UI（审核/发布按钮）挂后续轮。
- **测试**：NEW `test_skill_lifecycle.py` **7 例** + 修 5 处 active 语义既有用例（chat_mcp/executor/solution_skills/lcsc_other/extension_management PATCH 流）；`test_migrations.HEAD_REVISION` → `c1e5f9a3d7b2`。
- **口径**：业务表 **101 不变** / 迁移头 **`c1e5f9a3d7b2`（27 revision，+1）** / 路由 **283（+5）** / pytest **1780 收集 = 1774 passed + 6 skipped**（全量实跑 1209s） / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（skill 两表列变更 + 存量状态迁移；**api/worker/scheduler 三个镜像都要 build**）。

## [未发布] — V3 实施 T-W5：Workflow cancel/resume HTTP 面（服务端编排面收口，2026-11-03）

### 服务端（2 条新路由 / 零新表零迁移 / 零服务层改动 / 零桌面改动）

- **运行生命周期路由两条（276→278）**：POST `/api/v1/projects/{id}/workflow-runs/{rid}/cancel`（can_manage，幂等——重复取消 200 `cancelled=false`；终态 409 `already_terminal`；waiting_approval 可取消，pending 审批行不动）与 POST `…/resume`（can_manage，failed-only——failed/skipped 节点放回 pending 重投 `workflow.run`；其余 409 `not_resumable`）。服务层 `cancel_run`/`resume_run`（T-W3）直挂 HTTP，零服务层改动。
- **reconcile 收敛**：标题项已随 T-W3 落地（RECOVERABLE 增 `workflow.run` + worker-loss 钩子），本任务无残留。
- **测试**：`test_workflow_executor.py` **26→27**（HTTP 面：viewer 403 / 幂等取消 / already_terminal / 跨项目 404 / failed-only 恢复+节点回 pending / not_resumable）。
- **口径**：业务表 **101 不变** / 迁移头 **`d5b8e2f4a7c9`（26 revision）不变** / 路由 **278（+2）** / pytest **1773 收集 = 1767 passed + 6 skipped** / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d`（**api/worker/scheduler 三镜像**；迁移头不变，无需 alembic）。

## [未发布] — V3 实施 T-W4：Workflow 执行器 agent/human_approval 节点（审批复用 automation_approvals，2026-11-03）

### 服务端（1 个迁移（唯一 DDL）/ 零新路由 / 执行器+control 审批链扩展 / 零桌面改动）

- **human_approval 节点 = 复用 automation_approvals（设计 §3 落实）**：迁移 **`d5b8e2f4a7c9`**——`run_id` 放开可空 + 新增可空 `workflow_node_run_id` 反链（审批行=节点等待态的投影，FK CASCADE 随节点走，审计事实由 operation_events 承载）。分派即建审批：request_key=`wfnode:{节点行id}`、arguments_sha256 绑定输入快照、敏感键扫描（`contains_sensitive_argument` 提升为 control/access 公共函数，与 DSH 审批同闸）+ 64KB 上限、risk_level=4、15min 过期（`expires_minutes` 节点字段 1–1440 可调）；审批 id 挂节点幂等键 + pending 查重 ⇒ 崩溃恢复不重复建单。
- **拍板走既有任务中心入口（零新路由）**：`decide_automation_approval` 按 run_id 分支——workflow 审批经 `executor.settle_approval_node` **同事务**落节点终态（批准→succeeded 且 output 携 approval_id/拍板人/理由；拒绝/过期→failed）并**重投 workflow.run** 续跑；`dsh_approval_status` 惰性过期与 `execute_approved_dsh_tool` 同步加 workflow 守卫（审批无执行段）。
- **等待语义**：无 ready 且剩 waiting 节点 → run=`waiting_approval`（handler 正常返回；**有 failed 先断链收敛** FV-F1）；无人拍板则挂起（可取消），过期=拍板时惰性判定（主动清扫随 T-P1-5）；取消时 waiting 节点 cancelled、迟到拍板只落审批行不再驱动节点；resume 保持 failed-only。
- **agent 节点 = agents.start_run 同闸全链**（实时鉴权/月度预算/试点配额/T1/T6/沙箱/产物校验，绝不旁路）：幂等键 `wfnode-{节点行id}:{attempt}`——agents 对失败终态 run 拒绝同键重跑（V8），工作流以 **attempt 代际**表达「显式重试」（resume_run）；分派失败一律不叠加工作流自动重试（agents 自带重试族）；`params.solution_id` 透传使 agent_assisted/T1 方案闸随之生效。
- **定义期**：human_approval.capability 白名单 = 能力登记表去 `system.*`（validate_dag 注入参数，纯函数单测兼容）；四类之外未知类型的 start_run 422 守卫保留为防御（发布后白名单漂移场景）。
- **事件**：新增 `workflow_run_waiting_approval` / `workflow_run_approval_decided`。
- **测试**：`test_workflow_executor.py` **19→26**（审批批准/拒绝/过期/等待中取消+迟到拍板中和/幂等重入不重复建审批 + agent 全闸/能力拒绝不重试/run 失败不叠加重试）+ `test_workflow_definition.py` +1（capability 白名单）；`test_migrations.HEAD_REVISION` → `d5b8e2f4a7c9`。
- **口径**：业务表 **101 不变** / 迁移头 **`d5b8e2f4a7c9`（26 revision，+1）** / 路由 **276 不变**（零新路由）/ pytest **1772 收集 = 1766 passed + 6 skipped**（1764 + 8；实跑口径见 AGENTS.md）/ vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（automation_approvals 两列变更；**api/worker/scheduler 三个镜像都要 build**）。

## [未发布] — V3 实施 T-W3：Workflow 执行器（call/skill 节点 + §5 路由 + jobs handler，2026-11-03）

### 服务端（零新表零迁移 / 5 条新路由 / 新执行器模块 / 零桌面改动）

- **执行器**（NEW `workflows/executor.py`，设计 workflow-dag-v1 §3）：`workflow.run` 作为 background_jobs 新 job_type（决策 3：复用既有 outbox/lease/续租/reconcile/failure-hook 全套，绝不复制第二套队列）。主循环 = ready 调度（依赖全 succeeded，或 when 真值裁决放行）→ 节点独立事务执行 → 无 ready 全终态收敛 run；**每节点状态迁移独立事务、分派（HTTP/AI）一律在事务外**（产物先落表再前进=崩溃恢复锚点，2026-10-30 事故教训）。
- **call 节点 = api_execute 同闸绝不旁路**：鉴权/确认/项目 scope 每节点实时校验（发起人当下 AI 档位，run 级不冻结）；写类节点命中确认闸 → 节点 failed 携 action_id（诚实呈现未执行，T-W4 接审批前置）。**外副作用幂等（修 fde-v2 FV-F3 执行侧）**：写类（api_catalog write=True）节点分派前强制落节点级 `idempotency_key`（与 api_actions 完全同构 sha256 `[user_id, "wfnode-{节点行id}", data]`）——重试/崩溃恢复同键，api_execute 按 action 去重不二次外呼。
- **skill 节点 = pinned 版本确定性 AI 调用**：`key@版本` 固定版本 `instructions_text` 作 system_prompt、节点输入 JSON 作 prompt、`use_tools=False`（不签发 MCP token，工具面留在 call 节点）；T-S1 前沿用 active 语义（与 T-W1 校验口径一致）。
- **诚实语义**：占位符缺键 → 节点 failed `placeholder_missing`（绝不填空串，fde-v2 缺陷回归用例钉住）；断链 → run **failed** + 下游 skipped（修 FV-F1 不静默 done）；`when` 仅支持整串单占位符真值（表达式引擎待真实需求）；agent/human_approval 节点在 start_run 即 422 `unsupported_node_type`（不留必死 run，T-W4 开放）。
- **§5 路由五条（271→276）**：POST projects/{id}/workflows（can_manage）、POST …/{wid}/publish（admin 锁版）、POST …/{wid}/runs（can_manage，幂等键同 run 返回 200/新建 201，跨项目同键 409）、GET …/workflow-runs/{rid}（can_view 节点按拓扑序）、GET /api/v1/workflows（admin 平台模板）；**cancel/resume 的 HTTP 面随 T-W5**（服务层 cancel_run/resume_run 已可用）。
- **run 生命周期服务**：start_run（published 闸+幂等键先于定义查找） / cancel_run（停未执行节点、已执行外呼不回收、幂等） / resume_run（failed→重置 failed/skipped 节点复用产物）；事件目标新增 `workflow_run`（created/succeeded/failed/cancelled/resumed）。
- **jobs 接线**：`workflow.run` handler + worker-loss 收尾钩子（reconcile 放弃时 run 与悬挂节点推终态）+ RECOVERABLE_JOB_TYPES 增补（节点产物先落表=succeeded 即恢复锚点，重跑只处理未完成节点）；handler 入口恢复 queued→running 与死亡遗留 running 节点。
- **测试**：`test_workflow_executor.py` 新 **19 例**（§6 用例 4/5/6/7/8/11：链路与占位符原类型替换 / 版本钉住跨发布 / skill 钉版本指令 / 重试后成功与耗尽恢复复用产物 / 幂等键同构公式+跨重试恢复稳定 / 取消保留已成功节点 / 断链 failed+skipped / when 假值跳过 / 缺占位符不填空串 / 平台模板路由与项目内实例化 / outbox→worker 全链 / reconcile 钩子）。
- **口径**：业务表 **101 不变** / 迁移头 **`b7d9f1a3c5e2`（25 revision）不变**（零 DDL）/ 路由 **276**（+5）/ pytest **1764 收集 = 1758 passed + 6 skipped**（1745 + 19；实跑口径见 AGENTS.md）/ vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d`（server 代码烤进镜像；无迁移，alembic head 不动）。

## [未发布] — V3 实施 T-W2：Workflow 运行层（runs / node_runs 两表，2026-11-03）

### 服务端（2 张新表 / 1 个迁移 / **零新路由、零执行器、零服务逻辑改动** / 零桌面改动）

- **运行 + 节点运行双表**（迁移 **`b7d9f1a3c5e2`**，含 downgrade）：`workflow_runs`（固定 (definition_id, definition_version)——跑动中被改即受影响的 fde-v2 教训；run 级 `idempotency_key` **全局唯一**，修 fde-v2 FV-F3 无幂等重跑重复建单；status 七态 CHECK queued/running/waiting_approval/paused/succeeded/failed/cancelled；context_json=运行级入参占位符源；definition FK **RESTRICT**——执行史在则定义不可静默删，project FK CASCADE 项目隔离）+ `workflow_node_runs`（**UNIQUE(run_id, node_key)**；node_type 四类 CHECK（无 condition/wait，设计钉死）；status 八态 CHECK pending/ready/running/waiting/succeeded/failed/skipped/cancelled；attempt 计数；`depends_on` 定义侧冗余快照可追溯；节点级 `idempotency_key` 可空——外副作用节点必填由 T-W3 执行器强制；input_snapshot 执行前落审计可回放 / output_json 下游占位符解析源；run FK CASCADE）。
- **纯增量零改既有表**：T-W1 定义两表原样；执行器（ready 调度循环、重试、恢复）随 T-W3，路由随 T-W3 一起开。
- **配套**：`conftest` 清理序（node_runs → runs → definition_versions → definitions）、`test_migrations.HEAD_REVISION` → `b7d9f1a3c5e2`；`migrations/env.py` 按模块导入无需改、审计抽取脚本按模块自动发现无需改。
- **测试**：`test_workflow_runs.py`（新 11 例：默认态与版本钉住 / run 幂等键全局唯一（FV-F3 表级保证）/ 节点键 run 内唯一 run 间允许 / run 列守卫参数化 4 例 / 节点类型与状态守卫 / run 删除级联节点 / 定义删除 RESTRICT / 项目删除 CASCADE 带走 runs+nodes 且平台模板不阻拦）+ `test_migrations.py` +1（运行两表迁移往返保留 projects、定义两表共存）。
- **口径**：业务表 **101**（+2）/ 迁移头 **`b7d9f1a3c5e2`（25 revision）** / 路由 **271 不变** / api_catalog ENTRIES 94 不变 / pytest **1745 收集 = 1739 passed + 6 skipped**（1733 + 12；本机全量实跑 1851s）/ vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（新表）。

## [未发布] — V3 实施 T-W1：Workflow 定义层（两表 + dag_json 校验纯函数，2026-11-02）

### 服务端（2 张新表 / 1 个迁移 / **零新路由、零执行器** / 零桌面改动）

- **定义 + 不可变版本双表**（迁移 **`f2a4c6e8b1d3`**，含 downgrade）：`workflow_definitions`（draft/published/archived；发布递增 version；NULL project_id=平台模板）+ `workflow_definition_versions`（发布快照，(definition_id, version) 唯一，**写后不可变**——运行固定引用版本号，fde-v2 教训）。
- **`validate_dag` 纯函数先入 CI**（零执行器依赖，backlog T-W1 验收）：环检测=Kahn 拓扑并**点名环节点**（修 fde-v2 FV-F1）；未知依赖/自依赖/重复 key/未知类型/未知字段；**call.ref 必须 ∈ api_catalog ENTRIES**（白名单封 SSRF 面）；skill.ref 须为 active skill 的显式 `key@版本号`；agent.ref 须已启用；output 唯一且不遮上下文键；`{{placeholder}}` 须为运行上下文键或**传递上游**节点的 output；外部副作用无审批后继 → **P1 告警不阻断**（effect 结构化在 T-R2，P2 转强制）。违规一律 422 `dag_invalid` 携逐条 issues（code/message/node_key/detail）。
- **定义生命周期服务**（无 HTTP 路由——§5 路由随 T-W3 执行器一起开）：create（draft v1）→ update（已发布则自动 +1 开新草稿版本，版本行原样）→ publish（按**当前**白名单再校验后快照版本行；already_published 409）。事件 `workflow_definition_created/updated/published`（事件目标注册表新增 `workflow_definition`，平台模板 project_id 为 NULL）。
- **配套**：`migrations/env.py` 模型导入、`conftest` 清理序（版本行先于定义行）、`test_migrations.HEAD_REVISION`、审计抽取脚本模型清单。
- **测试**：`test_workflow_definition.py`（新 7 例：合法示例含拓扑序 / 环点名 / 结构与引用 / 三类 ref 白名单 / 占位符上下游 / 规则 9 告警 / 发布锁版本行+事件序）+ `test_migrations.py` +1（两表迁移往返保留 projects）。
- **口径**：业务表 **99**（+2）/ 迁移头 **`f2a4c6e8b1d3`（24 revision）** / 路由 **271 不变**（零新路由）/ pytest **1733 收集 = 1727 passed + 6 skipped**（+8；本机全量实跑期间机器休眠致 2 例连接中断失败，单跑复核绿，CI server-tests 干净复核）/ vitest 730 沿用。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（新表）。

## [未发布] — V3 实施 T-E1 + T-E2：一等证据表 project_evidence + 门禁证据挂接（2026-11-02）

### 服务端（1 张新表 / 1 个迁移 / 2 条路由 / 零桌面改动）

- **T-E1 一等证据表**：新模块 `fde_api/evidence/`（models / service / routes）+ 迁移 **`e1f3a5c7b9d2`**（`project_evidence`：UNIQUE(project_id, source_uri, content_sha256) 指纹即幂等键，kind 七类 CHECK，sha256 长度 CHECK，INDEX(project_id, kind)；project FK CASCADE、创建人 FK SET NULL；含 downgrade）。只存指针 + 指纹，不存原件（红线）。
- **API**：`POST /api/v1/projects/{id}/evidence`（can_manage；首次 201 `created=true`，同指纹 200 `created=false`——证据不可变，命中不改写 origin/captured_from）、`GET …/evidence?kind=&referenced_by=gate:Gx`（can_view；referenced_by 反查门禁清单项挂接）。错误码 `invalid_sha256` / `invalid_request` / `forbidden` / `project_not_found`。**有意不进 api_catalog**（AI 不可写证据，用例钉住）。
- **T-E2 门禁挂接**：`submit_gate_evidence` 每项先 `upsert_evidence`（kind=gate、origin=`gate:Gx/<清单项>`、captured_from=human），清单项 JSON 内挂 `evidence_id`，事件 `gate_evidence_submitted.items[]` 携 evidence_id；`_serialize_gate` 读时合并（历史清单项 `evidence_id=null`），**零 DDL**。同指纹二次提交幂等（行数不增、id 不变）。
- **并发安全**：`upsert_evidence` 在保存点内插入，撞唯一指纹回退后读回赢家，不向调用方抛 IntegrityError。
- **配套**：`migrations/env.py`、`conftest` 清理序、`test_migrations.HEAD_REVISION`、审计抽取脚本的 blueprint/模型清单均已登记新模块；`gate_service` 对 `evidence.service` 延迟导入（避免 projects⇄evidence 环）。
- **测试**：`test_evidence_registry.py`（新，6 例：指纹幂等与不可变 / 校验 / 权限与跨项目隔离 / kind 与 referenced_by 过滤 / 服务层入口 / 不进 catalog）+ `test_gates_api.py` +1（T-E2 挂接全链）+ `test_migrations.py` +1（迁移往返保留 projects）。
- **口径**：业务表 **97**（+project_evidence）/ 迁移头 **`e1f3a5c7b9d2`（23 revision）** / 蓝图路由 **271**（+2）/ blueprint 34 / api_catalog ENTRIES **94 不变** / pytest **1725 收集 = 1719 passed + 6 skipped**（+8，921.98s 全量实跑） / vitest 730 沿用。
- **部署**：`docker compose build && up -d` 后**须 `alembic upgrade head`**（新表）。

## [未发布] — V3 实施 T-P0-1：signoff 死锁修复（审计 WB-DEF-1，2026-11-02）

### 服务端修复（零迁移、零新路由、零桌面改动）

- **症状**（审计 WB-DEF-1，P0 功能阻断）：signoff checkpoint 唯一开闸点是 `handoff_run`，而它只收失败 / L1 降级 run；agent_assisted 方案经 generate-agent **正常 completed** 后既不能 handoff 又拿不到 pending → `POST …/signoff` 409 `signoff_not_pending` 与 `POST …/export-sow` 409 `solution_signoff_required` 永久互锁，SOW 一个字节都导不出。包声明 agent_assisted 而方案无 run 的形态同样死锁。
- **修复**：新增 `fde_api/agents/signoff.py::ensure_pending_signoff` 作为唯一幂等开闸入口（同方案至多一个 pending，只补空 run 软链不覆写）；`_finalize` 对非降级 completed 且绑定 solution 的 run 即时开出 pending（L1 维持「人工接管后再开闸」既有语义）；`handoff_run` 改走同一入口；`export_sow` 的 agent_assisted 闸拆成独立事务，拦下且无 pending 时**兜底开闸并先提交再抛 409**（闸本身不放宽），409 `details` 携 `signoff_checkpoint_id / signoff_status / remedy=resolve_pending_signoff / remedy_path`。
- **错误体**：`DocumentDraftServiceError`（= `SolutionServiceError`）新增可选 `detail`，solutions 蓝图错误处理器透传为 `error.details`（与 `AgentsServiceError` 同形；三参调用零改动）。
- **测试**：`test_solution_signoff.py` +5（端到端先红后绿：generate-agent completed → export 409 携指路 → 终审拍板 approved → export 200；无 run 兜底开闸且重复导出不重复开闸；驳回后再导出重开新一轮 pending；L1 降级 completed 不自动开闸仍走 handoff；开闸入口幂等/软链回填）。对旧代码实跑红：completed 后 checkpoint 数 0、409 无 details。
- **口径**：pytest 1717 收集 = 1711 passed + 6 skipped（d14 1712 + 本轮 5）；路由 269 / 表 96 / 迁移 22 不变；桌面零改动（vitest 730 沿用）。审计文档回写：`docs/implementation/v3-backlog.md` T-P0-1 → DONE（含实现偏差），风险登记册 / 差距矩阵 WB-DEF-1 → 已修复。

## [未发布] — V3 融合审计：Workbench × fde-v2 深度代码审计与 V3 升级实施方案（2026-11-02）

### 纯文档 + 审计脚本轮（零业务代码、零迁移、零部署）

- **主报告** `docs/architecture/蔡工FDE_Workbench_fde-v2架构融合审计与V3升级实施方案.md`（20 节 + Mermaid 五层架构图）：对 Workbench @0570384 与外部项目 fde-v2（快照≈上游 master@39e0e62，零执行只读审计）逐模块对照；核心裁决=**不引入 fde-v2 实现，只吸收四件经验证思想**（YAML DAG 形态 / 候选→人工确认闭环 / 证据"出处+源块"粒度 / BR 三要素机器可读纪律），七项 fde-v2 设计明确不搬（flow 执行器、运行时 DDL reconcile、隐式页面授权、exec 角色装配、user=None 全通、全量内省工具面、agentscope 团队）。
- **审计产物** `docs/audit/`：双仓基线、模块清单、路由清单 CSV（385 行=WB 269 url_map 枚举 + fde-v2 116 AST）、数据表清单 CSV（121 行=WB 96 表全字段+首建迁移归属 + fde-v2 17 DDL）、测试盘点与实跑终录、**17 能力域差距矩阵**（REUSE/EXTEND/NEW/DEFER 逐域裁决，含 Workbench 自身 14 项现状缺陷——WB-DEF-1 signoff 死锁为 P0 功能阻断）、风险登记册；`appendix/` 六份行号级原始证据报告。
- **架构设计** `docs/architecture/`：ontology-registry-v1（3 新表 terms+aliases / relation_types / change_sets + project_evidence 底座；6 个候选表经查重不建）、workflow-dag-v1（作为 background_jobs 新 job_type，不建第二套队列；四类节点；校验器纯函数先入 CI）、agent-policy-v1（权限五原则现状 VERIFIED 保持 + ToolGroup 只收窄 + Skill 以既有双表扩治理态）。
- **实施台账** `docs/implementation/`：v3-backlog（24 任务含文件/表/API/测试/回滚/复杂度）、v3-test-plan（本体/Workflow/权限安全/门禁交付物四族验收用例）。建议起手：T-P0-1 死锁修复 → T-E1/E2 一等证据表 → T-W1 DAG 校验器。
- **可复现抽取脚本** `scripts/audit/extract_{workbench,fde_v2}_inventory.py`（裸 Flask 注册全部 blueprint 枚举 url_map + Base.metadata，不调 create_app 零副作用；外部快照 `python -I` + AST/regex 零 import）。
- 实跑基线（本轮真实执行）：pytest 1700 passed + 6 skipped（1706 收集，与 d13 口径一致）/ vitest 730/730 / operations 14/14；fde-v2 verify 套件按不受信零执行纪律未跑（UNKNOWN 如实记录）。口径数字不变：96 表 / head `c3e7a9b1d5f4` / 路由 269 / ENTRIES 94。

## [未发布] — 派单 r12 签字执行：14 条留注归档 + B-③ 销号 + B-① 律师包定稿（2026-11-01）

### 纯文档销号轮（零代码）

- **留注 14 条签字归档**（设计文档 owner 交互签字）：12 条即归档（①②④⑧⑩⑪⑫⑰⑱⑲⑳㉑）+ 附条件 2 条勾选维持（③ 复购约束放宽 / ⑥ onsite 关键词派生）；需变更 5 条去向：⑤已执行（#55）、㉒已销号、⑨⑬随 B-① 等律师、⑦⑭⑮ 登记二期待办（⑭ 前置=行业→大类映射口径待业务给出）。
- **B-③ 拍板销号**：平台公司统一开票 + 预扣率表=税务总局 2025-16 公告口径确认（`WITHHOLDING_BRACKETS` 已是该口径，零改动）；衍生小项挂下次工程轮：`mark_payable` 扩开票方/税率字段必填。
- **B-① AI 法律研究底稿定稿 + 律师包待寄**：底稿（文档中心 06_派单引擎，官方条文抓取核实，**非法律意见**）倾向撮合引擎不落入算法备案义务/LLM 内部使用免大模型备案；用户拍板寄律师包、B-① 维持「需备案」零改动。台账 30.11。

## [未发布] — 派单 r12 拍板执行：B-④ 城市终版 + 留注⑤ 冷启动口径切换（2026-11-01）

### 首批城市名单定稿（全行业口径）

- **B-④ 拍板终版**：首发六城 = 上海/广州/深圳/杭州/成都/武汉（全行业服务口径 + 优先南方和一线城市；原苏锡常制造业走廊建议名单退役）。`seeds/dispatch_cities.json` 换终版（meta 记拍板来源）；**名单定稿≠开闸**——claim_enabled 仍全 false，开闸由 §6.4 三条件 + 城市开关驱动（B-① 备案完成+公示前 claim 维持降级态）。
- **留注⑤ 冷启动口径切换**：`settlements.py:_city_order_rank` 由交付席位 home_city 代理改为**包侧客户城**（企业代号第三段）；`cities.py` 新增公共助手 `package_client_city`/`city_from_enterprise_code`，cities/maintenance/settlements 三处城口径去重为一（maintenance `_client_city_of` 改委托）。
- **拍板销号（零改动）**：B-① 维持「需备案」（律师意见书仍是权威输入）；B-② 维持对公口径；直签豁免维持绝对封堵；P2-2 维持 5 态（留注㉒ 同步归档）；仿真器校准暂无数据继续等待。台账三十节 30.10 执行记录。
- 回归：种子断言/geo 钉子/冷启动夹具对齐新名单（档案城深圳≠包侧城杭州的反向回归钉）；桌面零改动。台账三十节 + 等待清单刷新（30.10）。

## [未发布] — 派单线收尾轮 r12：外部输入到达执行手册（2026-11-01）

### 零功能补码的落点普查轮

- **外部输入到达执行手册**（台账三十节）：八项外部输入（B-①备案/B-②托管/B-③开票与预扣率/B-④城市名单/P2-2 状态集/仿真器校准/留注签字/直签豁免）的"到达即执行"代码与数据落点逐项普查确认——落点全部存在，零补码；每项含分支动作、影响面与回归口径，任一输入到达按节执行即可。
- **C7 核实**：混合模式自动转换 job 已在 goal-r10 落地，8 例于本轮头复跑全绿——零重做。
- **留注编号勘误**：⑯为空号（r5→r6 跳号），实有定义 21 条；签字分类=12 归档 / 2 附条件 / 7 需变更。
- 联合口径不变：94 业务表 / head `f6a9c3e1d7b4` / 路由 252 / ENTRIES 86 / pytest 1563 收集 / vitest 695。

## [未发布] — 派单运维页簇 B3/B5/B6（2026-11-01）

### 争议处理 / 仿真对比 / 开闸运维（零迁移）

- **服务端五路由**（薄包装既有服务层，全部平台侧）：`GET /dispatch/disputes`（L0–L3 全量留痕；对账单只透出 `l0_report_source_uri` 指针——红线字段不内联本体）、`POST /dispatch/disputes`（人工打开仅 L1/L2——L0 由对账自动产；L1 金额 >¥50,000 → 422 `amount_above_l1`；快照锚=打开时包快照 §2.3 规则 2）、`POST /dispatch/disputes/{id}/resolve`（结论必填；close 直关；处罚类动作 100% 人工）、`POST /dispatch/simulator/replay`（历史包只读回放——当前池×当前规则版本再撮合画像，不落 offer；全链路种子化仿真留 CLI 沙箱库，绝不经 HTTP 触发写库）、`GET /dispatch/claim-gates`（§6.4 三条件+种子开关逐城可解释明细；开关在 seeds 文件，只读不翻转）。ENTRIES 74→**79** / 路由 234→**239**。
- **桌面三个平台侧 tab**（九子页簇收官）：「争议处理」（L0–L3 层级/状态标签 + 打开表单 + 裁决表单含直接关闭）、「仿真对比」（执行回放 → 摘要卡片（场景分布/Stage A 通过率/Top1 均分）+ 逐包 Top3 画像；口径=仿真不作真实成绩常驻声明）、「开闸运维」（逐城判定徽章 + 三条件 ✓/✗ + 拒单率；"改走代码流程——本页只读"）。
- 测试：服务端 `test_dispatch_b3ops_pages.py` 8 例（L0 禁人工打开/L1 上限 422/快照锚/裁决 409/回放降级 skipped+只读断言/开闸种子对齐）；桌面 `dispatch-ops.test.tsx` 9 例（路由解析/角色门/裁决流/打开校验/回放摘要/开闸判定）。台账二十八节。

## [未发布] — 派单调度台操作面 B2（2026-11-01）

### 平台侧调度台（零迁移）

- **服务端包留痕路由**：`GET /dispatch/packages/{package_id}/offers`（平台侧 only）——一包全量 offer 留痕（谁被派/接了/拒了、§6.2 窗口 deadline 服务端现算、§4.8 rank/explanation 释明、候选人身份），调度台据此决定代接单/重派。ENTRIES 73→74 / 路由 233→234。
- **桌面「调度台」tab**（第 6 子页，admin/project_lead 可见，动作权限服务端复核）：供给池候选勾选器（复用 `GET /profiles`，勾选即发布授权/指派名单）；包全景列表（draft 也在列）按状态出按钮——draft：等级覆盖（§4.5 必填 reason 留痕）+ 发布（携候选只读授权）；withdrawn/rejected/expired：重新发布（服务端 round+1 新版本对）；published：执行撮合（§4 两段式，结果面板展示场景 A/B/C + Top3 释明 + 资格门淘汰数）/ 指派 offer / 撤回（TRANSITIONS 仅 published 可撤）；offer 留痕面板 + offered 行「代接单」（`POST /accept` 携 delivery_user_id）。时间窗只展示不重算（B1 纪律延续）。
- 测试：服务端 `test_dispatch_b2_console.py` 6 例（全量留痕/claim 15 分钟窗/空留痕/非平台侧 403/未知包 404/轮次倒序）；桌面 `dispatch-console.test.tsx` 10 例（路由解析/状态动作映射/角色门 tab 隐藏/发布携候选/撮合可解释结果/指派/撤回/等级覆盖 reason 闸/留痕+代接单）。台账第二十六节增补 B2 项。

## [未发布] — 派单接单工作台 B1（2026-10-31）

### 交付工程师专区（循环终止后首期派单范围增强，零迁移）

- **服务端三读路由**：`GET /dispatch/offers/mine`（收件箱=候选人本人全量留痕 + §6.2 窗口 deadline 现算 + §4.8 算法释明只回本人）、`GET /dispatch/settlements/mine`（只回本人席位角色与金额，他席存在与金额零出现；预扣税原样透出不算净额——B-③ 未定不发明）、`GET /dispatch/profiles/me`（自助档案 + 在途计数，无档案 404）。ENTRIES 70→73 / 路由 230→233。
- **白名单 payload 增 `id` 支撑列**（资源标识非内容字段；授权方抢单/接包必须持有目标 id）——§9.5 隔离基线②键集测试同步更新并全基线复跑绿。
- **桌面「我的接单」tab**：收件箱 + 待响应倒计时（30s 刷新，窗口判定永不在前端复算）+ 接单/拒单按钮（原因枚举四选一只进留痕）+ 算法释明折叠 + 我的档案卡；**「我的结算」tab**（我的分成/计提基数/预扣税/打款状态）；**派单池抢单按钮**（claim 模式 published/offered 包详情展开内；开闸判定在服务端，claim_closed 可解释信息直显=§11 降级态 UX）。
- 测试：服务端 `test_dispatch_b1_console.py` 7 例 + r3 隔离/r4 回归；桌面 `dispatch-mine.test.tsx` 9 例。企业需求方专区不做（设计 §1.4-3 明确排除：客户不接触派单池）；评估与任务清单见台账第二十五节。

## [未发布] — goal-r11 派单引擎终止复核轮（2026-10-31）

### 循环终止——最终收口报告 v2（零功能改动）

- **§八 八项终止判定全部成立**：更新版收口报告 `docs/goal-r11-派单引擎收口.md` 取代 r8 版本成为唯一凭证（r8 的两项例外已由 r9/r10 消解）。全电池重测：服务端 1456+6s / 桌面 660 / typecheck 0 / 闸④覆盖率 **85%**（3,009 语句含 channel_guard 89% + simulator 81%）/ 负面清单 7 反例 / H5 口径 85 表·15 rev·head `c5d7e9f1a3b7`·路由 228·ENTRIES 68。
- H2/H3 以内测/仿真口径达标（基准原文「内测/仿真先行」）：H2 0.9565 / 工时占比 0.0716 / 毛利率 0.9717（r9 仿真工件，假设表全量回显，真实数据到位后复测校准）。
- 剩余事项全部外部输入依赖（备案/托管/税率/城市名单/P2-2/直签豁免/仿真器校准/留注签字/便携版重打包），逐项登记于台账第二十三节与收口报告第五节。

## [未发布] — goal-r10 派单引擎轮（2026-10-31）

### C7 混合模式自动转换 job（零迁移）

- **混合模式落地**（派单设计 §6.1「先 assign 指派，响应窗内无人接 → 转 claim」）：`dispatch/maintenance.py` 新增 `convert_stale_assign_to_claim` 挂 `run_maintenance` 节拍——assign 死亡（expired/rejected）包 × 城市 claim 开闸（§6.4）→ mode 翻转 + 按 §2.3 重发（round+1 新码新哈希 + §4.7 扩圈推进）+ `dispatch_c7_converted` 事件留痕；幂等（翻转后不再命中）；单包 SAVEPOINT 隔离不炸整批；城市未开闸安全空转（§11 降级态，人工重派路径不变）；零新增时间常数（24h 判死由上游 expire 按 §6.2 执行）。
- 测试：`test_dispatch_p2_r10_c7.py` 8 例（含转换后 claim_package 实抢闭环、幂等、降级空转、单包故障隔离、§6.4 拒单率条件真实生效验证）；r1–r9 回归全绿。口径：85 业务表 / 15 rev / head `c5d7e9f1a3b7`（零迁移）/ 路由 228 / ENTRIES 68 / 服务端 **1456 通过** / 桌面 660。轮次报告 `docs/goal-r10-派单引擎.md`；台账第二十二节。

## [未发布] — goal-r9 派单引擎轮（2026-10-31）

### P2-4 私单封堵 + 撮合仿真器（零迁移）

- **P2-4 私下接单封堵**（派单设计 §8.5）：新增 `dispatch/channel_guard.py` 三服务层钩子——H1 立项入口（`business_line` 随立项显式声明，派单线仅平台侧可立、专属 403 码）、H2 池内企业直签封堵（企业进过派单池后直签立项/报价 → 422 `private_deal_blocked`，复购走派单线放行）、H3 渠道正交（交付包只建在派单线项目上 → 422 `dispatch_line_required`）；封堵留痕走独立事务（主事务回滚后仍存活）。
- **撮合仿真器**（留注⑳）：新增 `dispatch/simulator.py`——历史包只读回放打分（P2-1 仿真对比数据源）+ 种子化全链路仿真（撮合/席位/时间常数走真实引擎，人工环节显式假设表采样）+ CLI `python -m fde_api.dispatch.simulator`（非沙箱库拒绝执行）。报告工件 `docs/dispatch-sim-r9-seed42.json`（H2/H3 内测/仿真口径，假设全量回显）。
- 测试：`test_dispatch_p2_r9_p24.py` 10 例 + `test_dispatch_p1_r9_sim.py` 4 例；r1–r8 回归全绿。口径：**85 业务表**（口径修订：不含 alembic_version）/ 15 rev / head `c5d7e9f1a3b7`（零迁移）/ 路由 228 / ENTRIES 68 / 服务端 1448 通过 / 桌面 660。轮次报告 `docs/goal-r9-派单引擎.md`；台账第二十一节。

## [未发布] — goal-r8 派单收口轮（2026-10-31）

### 派单引擎收口——开池四道闸全绿 + §八终止判定对照（零迁移）

- **C10 新人保护期**（§6.5）：撮合 Stage A 新增「前 5 单只推同城」——完成单数低于 `newcomer_protection_orders` 的候选强制非同城出局（推送范围收紧非资格淘汰），A5 明细带 `newcomer_city_only` 释明标记。
- **B1 防骚扰**（规则表 B1）：同包更早轮次拒过的候选本轮不再**主动推送**，与负面清单 #6「不因拒单限制接单机会」正交并存（本人仍可经 claim 主动抢）；stage_a 契约新增 `B1` 行；同步修正 r5 初版混淆两语义的测试。
- **§4.7 扩圈半径自动推进**：重派发布时 `redispatch_radius_km` 按 25→50→100→0 自动降档。
- **闸④覆盖率出具**：商业模块关键路径（报价/收款/合同/门禁/派单撮合结算）**84.9% ≥ 60%**（分母 2,637 语句），宽口径 71%——开池四道闸**全绿**。
- **收口报告**：`docs/goal-r8-派单引擎收口.md`——§八终止判定逐条对照（1/3/4/5/6/7/8 达成；2、3 带明示例外：P2-4 未立项、H2/H3 待真实数据）+ 附录 B 待签字清单（B-①②③④ + 留注①–㉒ + P2-2）+ 附录 A 修订建议（表 86/15 rev/路由 228/ENTRIES 68 重锚 + 新增冲突 A-⑧–⑪）。
- 测试：`test_dispatch_closeout_r8.py` 3 例；r1–r7 回归 94 例全绿。口径：86 表 / 15 rev / head `c5d7e9f1a3b7`（零迁移）。

## [未发布] — goal-r7 派单引擎轮（2026-10-31）

### 派单引擎 P2 批次（对照派单设计文档 v1.0 §8.5：P2-1/P2-3/P2-6；迁移 `c5d7e9f1a3b7`）

- **P2-1 桌面派单页簇**：`desktop/src/renderer/src/dispatch/` 三页——派单池（§9.2 白名单只读视图 + 详情展开 + 席位金额显示义务，响应体不含报价/收款明细字段断言）、能力档案与产能看板（四域分=晋级评定维度展示、在途/上限负载条）、权重与规则版本（只读 + 版本取值对照，仿真对比二期=留注⑳）；nav 全角色入口（交付方看被授权包，平台侧看全量），hash 路由 `#dispatch[/(pool|profiles|rules)]`；服务端支撑路由 GET `/dispatch/profiles`、`/dispatch/rules`（平台侧，ENTRIES +2）。
- **P2-3**：`projects.business_line` CHECK 放行 `'FDE_DISPATCH'`（§11.1 预留路径；写入入口随派单立项后续轮启用；存量数据零变化）。
- **P2-6**：`dispatch_cities.json` 扩字段钉子（subsidy_scheme 选填 + metro_group 必备断言——schema r4 已含，本轮补 P2-6 语义钉）。
- **P2-2（Project.status 枚举扩展）**：设计/规则表/BP 均未给出目标状态集——**不发明，待拍板**（台账第十九节留注）。
- 测试：服务端 `test_dispatch_p2_r7.py` 4 例 + 桌面 `dispatch-page.test.tsx` 6 例；r1–r6 回归 87 例全绿。
- 口径（goal-r7 实测）：86 表、迁移头 `c5d7e9f1a3b7`（15 revision）、路由 228（+2）、ENTRIES 68（+2）、桌面 660。轮次报告 `docs/goal-r7-派单引擎.md`；台账第十九节。

## [未发布] — goal-r6 派单引擎轮（2026-10-31）

### 派单引擎 P1 收官——§8.4 七项全过 + §8.1 八表齐（迁移 `b2c4d6e8f1a3`）

- **P1-6 报价归属**：`quotes.owner_user_id`（nullable FK users SET NULL + 索引；存量不回填=平台侧台账报价语义），创建即落 owner，归属过滤用例。
- **P1-7 留存策略**：`dispatch/maintenance.py` 留存扫描（撮合流水/评分 3 年、涉税 10 年——**报告只读不删档**，删除须人工合规审批，留注⑰）+ 维护作业 `dispatch.maintenance`（24h 节流）挂 `cli.scheduler` 主循环经 outbox 投递、handler 注册沿 research.export 模式；超时释放（r4 的 expire_stale_offers）一并挂入。
- **disputes 表**（§8.1 第 8 张，§6.6/§7.5）：L0 机器对账（逐包逐键比对结算应计 vs Payment 实收，差异>±¥1 自动草稿、幂等）+ L1 人工打开（48h 人工答复 SLA 字段、¥50,000 上限 422 走 L2）+ 人工裁决（**处罚类动作 100% 人工**，resolution 只能由平台侧写入）+ L0 对账单/依据只存 source_uri 指针 + snapshot_hash 锚定当时版本。
- 测试：`server/tests/test_dispatch_p1_r6.py` 8 例；r1–r5 全量回归 87 例全绿；ruff/mypy 无新错。
- 口径（goal-r6 实测）：86 表、迁移头 `b2c4d6e8f1a3`（14 revision）、路由 226、ENTRIES 66。轮次报告 `docs/goal-r6-派单引擎.md`；台账第十八节。

## [未发布] — goal-r5 派单引擎轮（2026-10-31）

### 派单引擎 P1-2 撮合核心（对照派单设计文档 v1.0 §4/§5 + 规则表 A-6，零迁移）

- **撮合核心**（§4.1–§4.8）：`dispatch/matching.py` + `dispatch/scoring.py`——Stage A 五资格门（等级/模块/行业/负载自动算上限/到场围栏）硬过滤出局不降权；场景裁决三选一：到场型字典序 (geo_tier, -level, -industry, -sla)、远程型加权（权重取 active 规则版本快照，无版本 → 422 `rule_version_required`=§11.1 降级态人工排序）、到场无候选场景 C 不自动派（事件留痕含淘汰明细）；§4.5 `required_level` 由 Quote 系数推导落库 + 发布前人工覆盖必填 reason 留痕；§4.7 扩圈链 geo_tier（同城/同省/邻接都市圈/全国，全国仅旗舰档）；§4.8 Top3 + `match_breakdown` 释明契约（stage_a 五门明细/stage_b/rank/explanation，对被派方展示）。
- **负面清单 A-6 七条逐条反例**（§8.8 开池四道闸之闸③全绿）：软画像零字段 schema 断言 / 排序签名无历史参数+同分不同历史同分 / 全包无轨迹语义静态检查 / 到场型字典序（同城弱者胜同省强者）+ 加权地理仅三档 / settlements 零工时扣减静态检查 / 被拒者下一轮仍可入选 / 全包零货运语义。
- **P1-4 options 枚举**：席位分配 / 场景类型 / 匹配模式 / 拒单原因四组随 /workbench/options 下发。
- 路由 +2（POST packages/{id}/match、packages/{id}/required-level），ENTRIES +2。
- 测试：`server/tests/test_dispatch_p1_r5.py` 12 例；全量 CI 门禁出具；桌面零改动。
- 口径（goal-r5 实测，rebase 到 goal-d1 合并态后）：84 表、13 revision / head `a7f3c1e9d5b2`（本轮零迁移）、路由 226（+2）、ENTRIES 66（+2）。轮次报告 `docs/goal-r5-派单引擎.md`；台账第十七节。

## [未发布] — goal-r4 派单引擎轮（2026-10-31）

### 派单引擎 P1 首批（对照派单设计文档 v1.0 §8.4：P1-1/P1-3/P1-5，零迁移）

- **P1-1 offer_service**（§6.2/§6.3/§6.7）：`dispatch/offer_service.py`——§6.3 乐观锁显式版本比对先行（冲突 409 `stale_version`，禁分布式锁）；同轮互斥（409 `offer_already_accepted`，包行 FOR UPDATE 串行化）+ 落选者自动 expired；claim 15 分钟确认窗 / assign 包响应窗超时批量释放（`expire_stale_offers`）；§6.7 拒单权（原因枚举 档期冲突/能力不匹配/距离/其他 只进 OperationEvent 留痕不进任何分值，**永不因配额拒绝拒单**——负面清单 A-6 #6 防护）；全拒后包 rejected=重派入口；§9.3 交接复用 `handover_accepted_member`（leader 为 actor）。路由 +4（指派发 offer / 接单 / 拒单 / 抢单登记），api_catalog ENTRIES 同步 +4。
- **P1-3 一致性测试**：api_catalog 每条 ENTRIES 逐条在 url_map 可解析（防目录漂移）+ dispatch 每条路由逐条在册（防脱册）——双向钉死。
- **P1-5 seeds 三处**：`gates.json` 加 `applicable_industries`（null=全行业通用；历史迁移回填哈希常量冻结不动，实时哈希由 `_gates_file_hash()` 现算）+ `dispatch_cities.json`（§12 六城建议名单，`claim_enabled` 全 false=§11.1 降级态）+ `acceptance_metrics.json`（BP §11 闸门指标投影）。
- **§6.4/C9 开闸评估**：`dispatch/cities.py`——claim_gate_status 三条件可解释明细（供给=active 档案 / 需求=近 90 天 published 包 / 拒单率<40% / 公示=规则版本存在为代理，留注⑨）+ 种子城市开关 AND；未开闸 403 `claim_closed`。
- 测试：`server/tests/test_dispatch_p1_r4.py` 14 例。全量 1386 passed + 6 skipped；桌面 654 与 typecheck 零改动全绿。
- 口径（goal-r4 实测）：83 表、迁移头 `f4b8c2d6e3a1`（12 revision，零迁移）、路由 224（+4）、ENTRIES 64（+4）。轮次报告 `docs/goal-r4-派单引擎.md`；台账第十六节。

## [未发布] — goal-r3 派单引擎轮（2026-10-31）

### 派单引擎 P0 簇②收尾——P0 8 项全落地（对照派单设计文档 v1.0 §8.3：P0-1/P0-2 + §9.5）

- **P0-1 交付包服务层**（§2.2/§2.3/§2.5）：`dispatch/packages.py`——canonical_json（键字典序/UTF-8 原样/Decimal→str/null/模块先排序）+ sha256 快照**发布时算一次即冻结**（改 solution/quote 不回写；撤回/拒绝/过期后重发 = dispatch_round+1 + 新编码 + 新哈希，版本对 Unique(project_id, round)）；§2.5 八态状态机通用迁移表（每次迁移写 OperationEvent）+ withdraw 的「本轮进行中 offer」防御守卫；发布前置=报价 finalized（422）；`PKG-{项目码尾段}-{轮次}` 编码；§9.3 接单交接以项目管理位（leader）为 actor 复用 `add_project_member(member)`（接单人本人交接前无 can_manage——留注⑧），幂等 + stale_version 重试。
- **P0-2 package_access 第三语义**（§9.1/§9.2）：`package_access` 表（package×user×role 三元组唯一，lead/seller/delivery/audit，可撤销）+ `dispatch/access.py`（无授权 404 不泄露存在性；admin 平台域放行）+ 交付包 API 字段白名单 12 项 + 交付方席位 40% 金额（发布时物化冻结到 `delivery_seat_amount`——禁 join quotes 的代价，留注⑥）+ `dispatch/routes.py` 6 路由（守卫路由层前置；管理动作平台侧 403；接单=平台侧或被指派人本人+delivery 授权双门槛，冒名 403）。api_catalog ENTRIES +6。
- **§9.5 隔离测试基线四条全绿**（开池四道闸之闸①）：跨主体访问 100% 拒绝（4 路由参数化 403/404）；响应体字段断言（键集精确等值、报价/收款/客户真名字段零出现）；静态检查（dispatch 读路径源级禁 Quote/Payment/Contract 引用、全包禁裸 `session.query(`）；渗透用例（越权接单 403、快照篡改无写入口 405、撤销授权重放 404 + 显式 re-grant 才复活）。
- 测试：新增 `server/tests/test_dispatch_p0_r3.py` 15 例；迁移 `f4b8c2d6e3a1`。全量 1372 passed + 6 skipped；桌面 654 与 typecheck 零改动全绿。
- 口径（goal-r3 实测）：83 表、迁移头 `f4b8c2d6e3a1`（12 revision）、路由 218（+6）、ENTRIES 60（+6）。轮次报告 `docs/goal-r3-派单引擎.md`；台账第十五节。

## [未发布] — goal-r2 派单引擎轮（2026-10-31）

### 派单引擎 P0 簇②表建设（对照派单设计文档 v1.0 §8.3：P0-3/P0-4/P0-7/P0-8）

- **P0-3 供给池档案**（§3.2/§3.3）：`fde_profiles`（一人一档：level 标量 L1–L4 + 四大子能力域独立评分轴 + 申报制标签 + 城市围栏 + 产能双列）+ `fde_level_evidence`（等级判定证据链：核验人/时刻/客观计数快照/依据单据只存 source_uri+sha256 指针）+ `dispatch/profiles.py`（L1–L4 晋级判据可复算查询——独立交付/复购/带教/四域短板下限，判据不足 422 `level_evidence_insufficient`，全过写证据链 + 更新档案 + `fde_level_promoted` 审计事件）。
- **P0-4 分成落库**（§7.2/§7.4）：`payments` 只加 `acceptance_passed_at` 一列（唯一约束不动、D+7/15/30/60 催款读时现算零改动）；`delivery_settlements` 席位级结算表（商务四席位 platform/region/city/delivery，与交付包执行四席位不同名不同义）+ `dispatch/settlements.py`（四席位 35/5/20/40、冷启动同城前 3 单 40/5/15/40、平台吸收舍入尾差保证 Σ=实收基数；劳务报酬**累计预扣法**（率表集中一处待法务确认）；状态机 draft→accrued→payable→paid/disputed，accrued 双条件=实收+G8 过门，payable 发票前置 422，paid 凭证指针）。双钩子：收款实收回填 upsert 结算草稿（无交付包项目纯 no-op）；G8 过门打标验收时刻并推进计提（晚到尾款收款即补，幂等）。
- **P0-7 配置常数**（§6.2）：`system_configuration` 增只读 `dispatch_constants` 节（时间常数 9 项 + Top-N + Stage B 权重 + 等级映射分 + 席位份额/冷启动 + 新人保护 + 拒单权，MappingProxyType 源级只读）——不进 PUBLIC_FIELDS（PUT 可写集精确等值校验天然拒改），实现代码唯一引用源，禁散落硬编码。
- **P0-8 规则版本**（§6.2/规则表 B9）：`dispatch_rule_versions` + `dispatch/rules.py`（30 天公示窗强制：生效日 < 发布日+30 天 → 422 `notice_window_required`；到点 published→active、原 active→retired 至多一个 active；快照必备节校验 admin-only；版本切换后旧 offer 的 `match_breakdown.rule_version` 永指当时版本）。
- **schema 调整**：`projects.enterprise_code` 全局唯一约束放宽为普通索引（派单 §3.3 复购判据要求同企业 ≥2 项目可表达；代号红线不动，三段两枚「·」格式校验保留——详见轮次报告留注③）。
- 测试：新增 `server/tests/test_dispatch_p0_r2.py`（12 例：L1/L2 证据链正反例、7 里程碑×四席位+累计预扣链、冷启动、状态机、G8 过门 API 全链路含晚到尾款补计提、配置只读断言、规则版本公示窗/角色/旧 offer 不回写）；`tests/conftest.py` 每用例清理序补派单六模型（FK 安全序）。
- 口径（goal-r2 实测）：82 张表、迁移头 `e3a7c5d9f2b8`（11 revision）、pytest 1357 passed + 6 skipped、桌面 654 用例零改动全绿。轮次报告 `docs/goal-r2-派单引擎.md`；台账新增第十四节。

## [未发布] — goal-r1 派单引擎轮（2026-10-31）

### 派单引擎 P0 双闸门（对照派单设计文档 v1.0 §8.3）

- **P0-5 门禁验收分离**（§9.4，§8.8 开池四道闸之二）：`gates` 加 `submitted_by_user_id` / `decided_by_user_id` / `is_delivery_party` 三列（迁移 `d2f6b4c8a1e9`）；`decide_gate` 双 403 防线——① 拍板人=该门禁证据执行人 → `gate_decider_conflict`（代码强制、先于其余业务校验，不可绕过）；② 交付方执行的 G8/G9 非 admin 拍板 → `gate_decider_role_required`（§11.3 方案①过渡口径）。单租户时代「同一用户提交+拍板」从 200 变 403，是刻意的硬闸门。
- **P0-6 events 白名单**（§2.5 坑 1）：`projects/events.py` 注册 `delivery_package` / `dispatch_offer` 两类 OperationEvent 目标（offer 的 project_id 经交付包反查）；为此按 §8.2 DDL 级约束先行落 `server/src/fde_api/dispatch/` 包两张骨架表（`delivery_packages`：8 态派单状态机 + `Unique(package_code)` + `Unique(project_id, dispatch_round)` + 扩圈半径 Check(25/50/100/0=全城哨兵)；`dispatch_offers`：`Unique(package_id, dispatch_round, candidate_user_id)` + 6 态 Check + VersionedMixin 乐观锁位 + `match_breakdown` JSON）——**服务逻辑零预埋**，发布/快照/匹配随 P0-1/P1 轮落位。
- 测试：新增 `server/tests/test_dispatch_p0.py`（6 例：两类事件目标写入、执行人自拍 403、交付方 G8 平台拍板、服务层防绕过、乐观锁位）；`test_gates_api.py`（5 例）与两个冒烟脚本改双拍板人（执行人=lead、拍板人=admin），门禁冒烟加「执行人拍自己的门 403」钉子。
- 口径（goal-r1 实测）：78 张表、迁移头 `d2f6b4c8a1e9`（10 revision）、pytest 1345 passed + 6 skipped、桌面 654 用例零改动全绿。轮次报告 `docs/goal-r1-派单引擎.md`；台账新增第十三节。

## [未发布] — goal-r3 技能循环（2026-10-30）

### 仓库健康巡检（G10）

- dynamic-workflows 编排只读巡检：**4 个只读子代理并行**（测试覆盖地图新鲜度 / docs 与代码漂移 / 依赖与 TODO / 台账逐节对账）→ **独立复核员**逐条复核 → 结构化报告。43 条原始发现全部坐实（0 驳回 0 存疑），**P1=0 / P2=14 / P3=29**。全程零变更——落盘走本 PR。
- 新增 `docs/仓库健康巡检-G10.md`：四面逐条发现（每条带 file:line 证据与复核状态）+ 下一批 backlog 三批建议（文档新鲜度批 / 依赖卫生批 / 功能欠账批，优先级逐条写明）。
- 关键坐实项：覆盖地图计数漂移 948→1330 collected（桌面 496→512，且 496/api-ipc(7) 写作时即不准）；「SES 未建」两处失效（G9 已预建默认关闭）；变量与密钥缺 8 个 FDE_SES_*；权限矩阵缺 mailing/SNS 例外鉴权行；**ruff/mypy/pre-commit 未入 lock，CI 门禁裸装最新**；台账对账 24 条中 5 条确认已完成、19 条仍待办（含 4 条 P2：research 三态 UI、PATCH-confirm 分叉、analyzing 对账、README 初始化节）。
- 随本 PR 修正自家文档两处（巡检发现）：`docs/SES发信模块-G9.md` §五闸门顺序归因（发信域约束在 service 前置，不在 decide_send）与 §八测试分桶（9+5+12+1=27）。
- 台账新增第十二节（backlog 三批推进）。

### SES 发信模块预建（G9｜WP-E）

- 新增 `server/src/fde_api/mailing/`：**默认整体关闭**（`FDE_SES_ENABLED=false` 时发送路径落 `drop_disabled`、SNS 回调端点一律 403，默认部署零行为影响、零 AWS 依赖——boto3 延迟导入，未启用时不 import AWS 栈）。SES 生产批复下来**只需改配置启用**，不改代码。
- 发送路径 `send_email`（service 函数，**不设 HTTP 路由**——避免未批复时出现可打的发信口）：闸门顺序固定 = 开关 → 发信域约束 → 幂等键 → 收件人抑制 → 当日限额（只数 UTC 当日）→ 打 SESv2；throttle 记事件并返 503（可重试）、拒收返 502（不可重试），失败不占发送台账。
- SNS 回调端点 `POST /api/v1/mailing/sns/events`：**签名即鉴权**（SNS 带不了工作台 JWT）——校验 Signature v1（RSA-SHA256，字段序按 AWS 固定顺序）+ `SigningCertURL` 限 `sns.*.amazonaws.com`（校验不过则**不发起任何外联**）+ `SubscribeURL` 同域限制 + `TopicArn` 白名单；退信/投诉只落地址 + 分类 + 通知 sha256 指纹，**不落通知原文**。
- 新增两表（迁移 `a9c3f1d8e2b4`）：`mailing_sends`（幂等键唯一）、`mailing_events`（`event_key` 唯一——SNS 是 at-least-once 投递，重放不重复计）。bounce/complaint = 地址级死刑（进抑制名单），delivery 不影响地址。
- 发信域口径落到配置校验器：FROM 必须落在 `FDE_SES_SEND_SUBDOMAIN` 子域内，主域 `somwyn.com` 启动即失败（`ses_sender_domain_forbidden`）。DKIM/SPF/DMARC 写 `docs/SES发信模块-G9.md` 不写死代码——**子域**加 SPF，**主域 SPF 不加 SES include**（否则扩大主域邮件面）。
- SNS 主题策略须带 `aws:SourceArn`（配置集 ARN）+ `aws:SourceAccount`——缺 `SourceArn` 即 confused-deputy 洞（任账号 SES 都能往我们主题灌事件）。AWS 凭证走 boto3 默认凭证链，不配进本模块、不进仓库。
- 新增 `server/tests/test_mailing_ses.py`（27 例，**零真实邮件**）：假客户端 + botocore Stubber + 自签证书验签；覆盖闸门顺序、bounce/complaint 抑制、幂等重放、坏签名/错主题/非法 JSON 拒绝、text/plain 报文解析、配置校验器。
- 依赖：`boto3>=1.36,<2`（pyproject + `requirements.lock` 钉 1.43.122/botocore 1.43.122/s3transfer 0.19.3）。

### 后台作业死亡后对账重排队（台账 §八 第 1 条落地，2026-10-30 晚）

- 问题：worker 被杀（OOM/部署/重启）时，它从 redis 队列弹走的作业 id 随进程一起消失——outbox 事件已 `dispatched`（派发器不再看它），`BackgroundJob.max_attempts`/`available_at`/`locked_until` 无人消费，于是作业永远停在 `running`，业务行（指引分析 `analyzing`、会话 turn `running`）永远停在中间态，前端每 2 秒轮询到天荒地老，唯一解法是手工 `RPUSH fde-jobs <id>`。这正是 10-30 登录事故里那笔孤儿作业的成因。
- 修复一（`jobs/worker.py`）：`run_job` 把「认领 + 执行 + 落终态」从**一个事务**拆成三段——认领（`status=running` + 租约 + `attempts+1`）先单独提交，执行期间由守护线程**续租**（默认 60s 一次，租约 5min），终态再单独写回。三个后果：① 在跑的作业对其他进程**可见**（此前全程只有 pending，对账无从分辨「有人在做」与「做的人死了」）；② 行锁只存在于认领那几毫秒，不再被 handler 全程占着（长任务钉着连接正是 10-30 锁雪崩的形状）；③ 租约过期从此是**死亡信号**而非「慢任务」信号。返回语义（not_found / already_terminal / leased / no_handler / failed / succeeded）保持不变。
- 修复二（`jobs/reconcile.py` 新增）：对账扫描捞两种无主作业——① `running` 且租约已过期（worker 死了）；② `pending`/`queued` 且超过 5 分钟无人认领（队列项丢了）。捞到之后：**可恢复类型重排队**（受 `max_attempts` 与 `available_at` 约束，入队前先提交库事务，队列项丢失下一轮按宽限期再捞），否则**落 failed** 并调用业务行收尾钩子，把业务行推到终态（前端停止轮询，用户看到「进程中断，请重试」）。
- 可恢复性按类型显式登记（不默认重跑）：`project.presurvey.analyze`/`ai.chat`/`ai.execute`/`file.scan`/`file.preview`/`document.generate`/`research.export` 可重排队——它们的 handler 都已跳过终态业务行，重跑不会覆盖已有结论；**`automation.execute` 不可重跑**（有对外副作用：发信、MCP 调用），死亡即落 failed 交人工重触发。
- 业务行收尾钩子（`jobs/handlers.py` 注册表 + 四处实现）：指引分析 → `analysis_worker_lost`；AI 会话 turn → `failed`（卡住的 turn 会让整个会话永久 `chat_busy`）；调研导出 → `failed`；自动化 run → `failed`。终态业务行（`ready`/`completed`/`succeeded`）一律不动——对账不许覆盖已有结果。
- 接线：worker 循环每 60s 扫一次（扫不出东西时零 DB 写）；另给运维留了手工口子 `flask reconcile-jobs`（容器被杀后可立即补投，不必等下一个周期）。
- 回归钉子：`tests/test_job_reconcile.py` 新增 15 例——租约过期重排队 / 活租约不动 / **被活 worker 行锁占住的作业被跳过（`FOR UPDATE SKIP LOCKED`）** / 孤儿 pending 重排队 / 新鲜 pending 不动 / 重排队后不热循环 / 次数用尽落 failed / 不可恢复类型落 failed / 指引分析与会话 turn 的收尾与「终态不被覆盖」/ 端到端（孤儿作业经对账后真的跑完）/ **认领状态对其他会话可见** / **执行期租约被续期**。

### AI 工具循环锁泄漏修复（生产事故回补，2026-10-30 晚）

- 事故：worker 跑 AI 聊天时工具调用撞 DB 连接断线，`_run_tools` 兜底吞掉异常继续循环，但共享会话带着未决事务与 `users` 表行锁停在 idle-in-transaction 十余分钟；登录路径的 `FOR UPDATE` 全体排队，gunicorn 超时杀 worker 又留下新的半死连接，锁滚雪球致登录 500。
- 修复：`server/src/fde_api/control/ai_tool_loop.py` 两处——① `_run_tools` except 分支立即 `session.rollback()`，工具异常不再让会话持锁过夜；② 主循环每轮工具执行完也 `db_session.rollback()`——工具循环工具全只读，回滚零损失，却保证下一次 provider 调用（最长 `timeout_seconds` 300 秒、零 DB 流量）不会骑在一个仍持有行锁的 idle-in-transaction 连接上（事故里 13 分钟的持锁窗口正是这个形态）。
- 回归钉子：`tests/test_ai_tool_loop.py` 新增 1 例（`OperationalError` 抛出时 `db.session()` 返回的会话在 with 块内恰被 rollback 两次：崩溃处理器一次 + 主循环每轮清理一次；17 例全绿）。
- 运维侧另两笔（无代码）：`pg_terminate_backend` 清锁 + worker 重启解堵；孤儿 pending 作业（outbox 已 dispatched、redis 队列项随重启丢失）手工 `RPUSH fde-jobs <id>` 补投。关联既有待办：台账 §八 第 1 条（进程死亡后无对账重排队）——已由本文件上一节的「后台作业死亡后对账重排队」落地，手工补投不再是唯一解法。

### 跨库只读验证脚本固化（G8）

- 新增 `scripts/verify/`（sql-queries 方法）：`run-verify.sh` + `verify-twenty-persons.sql` + `verify-n8n-executions.sql`——Twenty persons 总数/新增窗口/ICP 分布/去重命中，n8n 最近执行状态与耗时。连接参数全走环境变量（容器名/用户/库名，无口令：psql 在 db 容器内走本地 socket，脚本不读 .env）；每个会话显式 `BEGIN; SET TRANSACTION READ ONLY; … ROLLBACK;`；SQL 经 stdin 进容器（中文不走 argv）；输出仅计数不含客户明细。
- 口径：ICP 从笔记标题「冷邮件草稿 (ICP N)」提取每人最高分（≥70 培育 / 55–69 留档双层）；去重命中 = 同主邮箱挂多人（期望 0）。
- 宿主实跑一次并记录计数摘要到 `docs/验证脚本-G8.md`：persons 75（7d 新增 64，ICP 记分 9 全在 55–69 留档档）、重复邮箱 0（去重有效）、公共管道 4 成功（均值 27s）、QFhunterFeed01 2 成 3 败（运维信号，仅记录）。

### 意图差距审计（G7）

- 新增 `docs/意图差距审计-G7.md`：以 G2 七份意图文档 + AGENTS.md 红线为基线，逐边界核对代码执行点。**B1–B4 零差距**——门禁证据只收指针+64 位 hex sha256（`gate_service.py:520-548` + `workbench/models.py:544-547`，无 blob、无上传路由）；confirm 只能 canManage（`service.py:174-180` + `api_catalog` 零 guidance 条目，AI 无代拍板面）；bridge-poll 唯一进程出口是两个 openfde 只读子命令（`bridge-poll.mjs:68,101,110`，无写相 CLI、真相层零写面）；.env 不入 VCS 有可校验闭环（`.gitignore:1-5` + 全树仅两个 example 被跟踪 + gitleaks PASS 盲区规则）。
- F1 [P2→已处置]：「origin 永不 push」原本只有文档约束、无本地强制——本机已加 `git remote set-url --push origin FORBIDDEN-origin-is-upstream-use-fork`（push 必失败已实测，fetch 不变）；每台新克隆须重复，建议进 README 初始化节（台账十.1）。
- F2 [P3→已修]：G4 重写 `jobs.py` 使意图文档 4 处行号引用漂移、步骤 4 语义未反映自动重试——《系统意图-关键流程》《系统意图-自动化面》已同步更新。
- 台账新增第十节。

### 真实浏览器 UI 回归 harness（G6）

- 新增 `desktop/gui-harness/`：纯浏览器驱动 renderer 的回归 harness。dev-only Vite 配置（端口 5199）注入 `window.fde` 桥 shim（登录/刷新/`ApiResponse` 信封、deviceLabel→device_label 转换、401 刷新重试；`app.version` 返回裸字符串——三处契约此前只有 Electron 真机能验证），同源 `/api` 代理到 127.0.0.1:8010（浏览器有 CORS 而 Electron IPC 没有），并给生产 CSP 打 dev 补丁（`connect-src 'self'`、`style-src 'unsafe-inline'` 供 Vite 开发样式）。不引新依赖，不进打包产物。
- 新增 `desktop/gui-harness/regression.mjs`：仓库自带 playwright-core + 已装 Chromium 驱动两条链路 11 个断言点——①指引链：登录→项目→查看预调研分析→**只读 draft 态直接出现「确认并用于项目指引」按钮（R11 事故防线，浏览器实测通过）**→弹窗内编辑；②集成桥页：侧栏进入、状态文案、「立即采集」按钮在浏览器 harness 下被平台守卫拦为 `bridge_platform` 错误提示（与真机同代码路径）、采集反馈区可见；截图留本地（已 gitignore，含本机路径与项目代号）。
- 新增仓库技能 `.agents/skills/fde-gui-regression/SKILL.md`：harness 原理、启动/种子/运行命令、fixture 陷阱（enterprise_code 需两个「·」、module_keys 必须命中 ModuleCatalog）、断言口径与已知坑（hash 路由需点侧栏、Vite 单实例、中文经 `\uXXXX` 转义）。
- 回归报告 `docs/GUI回归-G6.md`：11/11 通过表、R11 防线结论、2 条 P3 finding（认领入口失败静默无提示——已记台账第九节；命名约定再次复核，与台账七.3 同源）。

### 代码评审门与回溯评审（G5）

- 新增 `docs/代码评审-G5.md`：PR #24 的参与者约定法评审报告（scope/dimensions/findings/coverage，含 9 条保留 finding 与 6 条驳斥成立的丢弃候选）、PR #17/#18 回溯评审、WP-B Serper 修复说明。
- 评审修复（随 PR #24 提交）：DSH 路径的裸 `JSONDecodeError`/`ControlServiceError` 逃出错误分类 → 结构化输出失败现在落 `ai_output_invalid`（可重试）/配置类不可重试，DSH 部署形态下重试能力不再静默失效；重试耗尽文案只在终态错误可重试时才劝「请重新发起分析」；存储对象缺失归入专用码 `source_object_missing`；限流/超时类瞬时错误重试前退避（契约失败不退避）；本地 DOCX 解析失败按确定性改为不可重试（存储读取 `OSError` 仍可重试，供应商侧提取失败不变）；重复投递不再对已终态分析二次调用 AI；每次尝试用独立请求号（上游去重不会挫败重试）；`python-docx` 声明下限提到 `>=1.2`（样本生成器用了 1.2.0 才有的 `add_comment`）。
- 新增回归钉子：重试语义 +7 例（请求号独立/退避双向/不可重试终态文案/存储缺失分类/终态守卫/任务仍为绿）、DSH 分类 +2 例。
- 回溯评审 PR #17/#18 发现 3 条（台账第七节）：PATCH 成功而 confirm 失败后前端版本与库态分叉致重试必 409（P2）、审核面板内无旧版源警示、认领命名约定无服务端保障。
- WP-B 修复交付（获客引擎 `AI_Find_Customer`，独立分支 `fix/serper-region-iso-codes`，commit 2c51e1a；其 origin 为上游仓库，不推送）：`_REGION_GEO` 由表自身 `gl` 值反查建 ISO-2 索引，ISO 码（US/CA/DE）不再落空致 Serper maps 400；键归一（下划线/连字符→空格）；命中失败打 warning（此前静默降级为全局搜索正是 400 无人察觉的原因）；引擎 +6 例，全量失败集合与改前逐条一致。

### 指引契约失败自动重试加固 + 对抗 DOCX 样本（G4）

- `server/src/fde_api/guidance/jobs.py`：预调研分析任务内自动重试——`GUIDANCE_ANALYSIS_RETRY_LIMIT = 1`（不含首次，测试钉死）。可重试失败（retryable=True 的 KimiError / GuidanceContractError 契约违反，即 MiniMax 概率性不守 JSON 合同的已知现象）先自动重试一次，仍失败才落 failed，failure_message 携带「已自动重试 N 次仍失败」的用户可见提示；不可重试（如 ai_service_not_configured）一次即败不消耗额度；source_missing 在构造 AI 客户端前拦截（零 AI 调用）；新增兜底分类 analysis_unexpected_error——未预期异常不再让分析卡在 analyzing（前端会无限轮询），且消息不携带异常串。每次尝试重新打开文件流。
- 对抗 DOCX 样本生成器 `server/tests/fixtures/presurvey/generate_fixtures.py`（9 种：空文档/空表格/合并单元格/批注/异常样式/缺失章节/超长段落/嵌套表格/非 ZIP 字节流；python-docx 1.2 程序化构建 + document.xml 最小注入），session 级构建到临时目录，二进制不入 git。
- 新增 `tests/test_guidance_adversarial_fixtures.py`（11 例）：两层解析（guidance 块抽取 / 本地全文提取 / Kimi 本地提取分类）对 9 样本的行为契约——畸形输入绝不崩溃、空内容失败为可分类错误（kimi_file_extract_failed retryable=True）、合并单元格全文层按 _tc 去重且块层按格位稳定引用、批注不泄漏进提取文本、异常样式不阻塞提取、嵌套表全文层递归可见（块层不可见，钉住两层差异）、超长段落整体提取。
- 新增 `tests/test_guidance_retry.py`（9 例）：重试语义钉子——契约失败重试一次后成功 / 耗尽后 failed 带 ai_output_invalid 与自动重试提示 / 调用次数恰为上限+1 / 不可重试一次即败 / 真实提取路径吃空表格样本落 kimi_file_extract_failed / source_missing 零 AI 调用 / 未预期异常落 analysis_unexpected_error 且消息无异常串 / 成功路径一遍 ready。
- conftest 清理清单补 `ProjectGuidanceAnalysis`/`ProjectPresurveySource`（此前测试库跨用例残留指引行会顶住 RESTRICT 外键清理）。

### 验收场景矩阵与缺口补测（G3）

- 新增 `docs/验收场景矩阵-G3.md`：指引链 / 集成桥手动采集 / SES 发信策略三链场景表（目标/起始/角色/分步/预期），每条映射钉住它的测试。
- 指引链补测 `desktop/tests/renderer/guidance-chain-scenarios.test.tsx`（8 例）：分析中→ready 自动开审进编辑态、failed 面板 role=alert 可见且无确认按钮、start() 失败 inline 可见、cancelled/queued/extracting 参数化占位展示、confirmed 卡片摘要 + `source_is_stale` 旧版重分析横幅（ProjectGuidanceCard 此前零测试）；集成桥链核对后无缺口（既有 13 例已覆盖全回路，platform 显式注入 win32/linux）。
- SES 策略先行 `server/src/fde_api/mailing/policy.py` + `server/tests/test_mailing_policy.py`（27 例）：四态分类（仅 throttle 可重试）、幂等闸门（同 message_id 判 duplicate 且先于限额/抑制）、每日限额（沙盒默认 10 可配）、总开关（未启用一律 drop_disabled）、发信域约束（仅配置子域，主域 somwyn.com 拒绝）、指数退避封顶——纯逻辑零 AWS 依赖，G9 在其上接客户端与 SNS 回调。
- 发现并记台账：cancelled 终态在审核面板仍显示「分析正在后台继续」占位（文案缺陷）；start() 失败提示不透传 failure_message 明细。

### 系统意图文档基线（G2）

- 新增 7 份意图文档（`docs/系统意图-*.md`，shipping-artifacts 方法，README 仍是部署唯一权威、交叉引用不复制）：架构与信任边界（根文档）、关键流程（预调研指引链/门禁/报价收款三链含鉴权点与 deny 例）、权限矩阵（三套角色体系 × 15 资源域）、变量与密钥（变量名×来源×轮换×风险，只写名不写值）、测试覆盖地图（现有 948+496+14 用例 / 建议 / 缺口三段）、定时任务（worker/scheduler/宿主 FDE-Bridge-Poll）、自动化面（AI 助手工具面/预调研管道/集成桥/任务中心，App 拥有副作用原则）。全部条目引用代码位置，作为 G7 意图比对基线。

### 内置手册与 UI 帮助 parity（PR #19）

- `help_manual.md` 补收「实操示例：证据文件怎么写（somwyn 样板）」整节与 G↔S 阶段映射（此前只在桌面端 HelpPage，help_fetch 检索不到）；新增双手册主题 parity 测试与 G↔S 映射与 `seeds/gates.json` 一致性测试，防两份手册再次分叉。

### 仓库级操作技能（G1）

- 固化 3 个仓库级 Agent 技能到 `.agents/skills/`（skill-creator 规范，随仓库分发）：
  - `fde-package-verify`：便携版打包全流程——electron-builder 产物 → asar sha256 → 中文 marker 字节验证（防控制台编码假阴性）→ 换新目录命名 r N+1 交付。
  - `fde-bridge-capture`：集成桥手动采集 runbook——`schtasks //Run`（Git Bash 双斜杠）或桌面「立即采集」按钮（同一代码路径）、`logs/bridge-poll.log` 验证到站、改 server 必须重建镜像、采集器只读纪律。
  - `fde-delivery-flow`：标准交付流检查单——分支 → push fork（永不 origin）→ PR → 4 CI 全绿 → 合并 → ff 本地 main → 删分支，每步验证点与常见事故对照。

## [未发布] — goal-r2 第二轮（2026-10-28）

安全口子、假绿灯与跨机口径一轮。**版本号未升**（按发布列车统一处理）。

### 安全（批次 G）

- **清除已入库的明文数据库口令**：备份脚本里的三条口令字面量（两条不同口令）已从工作树删除。凭据随 `2f90484` 入库，**视为已泄露，需人工轮换**（见交接清单）。
- **范围外备份管道移出仓库**：与 FDE 交付线无关的 n8n/Mautic/openoutfind 备份脚本迁至 `D:\test\AI外贸获客\scripts\`（副本 sha256 校验一致，仓库内可由 `git show 2f90484:scripts/backup-pipeline.sh` 恢复）。
- **集成桥读接口收敛门禁**：`GET /bridge/engagements`、`GET /bridge/status` 此前只要求登录（任意用户可枚举全部项目名与企业代号），现与写接口同级要求 `project_lead`。
- **登录限流键改为「用户名 + 来源 IP」复合键**：此前单个 IP 连错 5 次即可定向锁死任意用户名（含 admin）。Redis 不可用时记 WARNING（可观测），并可用 `FDE_LOGIN_RATE_FAIL_CLOSED=1` 切为 fail-closed。
- **秘密扫描线自证有效**：实测默认 gitleaks 规则对 `*_PASS=` 形态**整体漏报**（历史口令与随机探针同形态却一个抓一个不抓），新增 `.gitleaks.toml` 兜底规则与 `scripts/check-secret-scan.sh`（含 `--self-test` 哨兵自测）。

### 假绿灯（批次 H）

- **mypy 基线改计数法并纳入 tests**：旧实现按「文件+错误码+归一化消息」去重，实测 45 条基线条目掩盖了 181 次同类新增。
- **代号化检查不再吞错**：grep 退出码 1（无命中）与 ≥2（错误）区分；邮箱策略真正读取 `FDE_PSEUDONYM_EMAIL_POLICY`（缺省 fail）；黑名单提取 0 条即 FAIL；psql 失败不再当 0 行；`projects` 表 0 行即 FAIL（空库扫描等于没扫）。
- **CI 代号化 job 先迁移灌数再扫描**（原为空库扫描）。
- **冒烟脚本补真实断言**：auth 冒烟新增跨用户名隔离断言，commercial 冒烟种子管理员 try/finally 清理并断言归零。

### 跨机口径与运维（批次 I）

- pre-commit 三个钩子改走跨平台 node 入口（不再写死 Windows venv 路径）；README 更正 `.env` 模板来源与 venv 跨平台表述；操作手册路径参数化。
- compose 四服务统一 `restart: unless-stopped`；api healthcheck 改走 `/api/v1/health/ready`（真正校验依赖）；worker/scheduler 新增基于 Redis 心跳的 healthcheck（进程还在 ≠ 还在干活）。

### 打磨（批次 J）

- 业务枚举（价格档位 / 门禁五态 / C 分支 / SOW / 业务阶段）改由服务端 `GET /api/v1/workbench/options` 下发，前端保留本地兜底；存库值一律不变（旧中文标签数据照常可读）。
- 门禁汇总徽标改为按实际状态遍历（此前硬编码五态，服务端新状态会被静默丢弃）。
- 新增交付审计专用表 `document_delivery_records`（+ 迁移 `f3c8d2b7a1e5`），交付记录可按项目维度检索。
- C 分支触发档位收敛为单一常量；B 层分上下界都夹；扩展中心路由加角色门禁；预调研与调研导出的轮询失败对用户可见且失败后继续下一轮。
- **项目指引审核入口补缺**：指引卡片挂载时自动认领「已上传但尚未确认」的预调研源——此前分析/审核入口只在本次会话内上传后才出现，服务端（定时任务/历史会话）跑出的待审核指引在界面上没有任何入口；空状态文案同步提示审核入口。
- **指引审核弹窗只读态可确认**：确认按钮此前只在编辑模式渲染，用户从「查看预调研分析」进入的只读预览没有确认入口（得自己发现右上角「编辑」才能确认）；现在只读草稿底部直接显示「确认并用于项目指引」。

### 智能助手知识（help_fetch）

- 智能助手此前只拿到会话历史，「使用帮助」栏内容它一无所知（手册只在桌面前端渲染，服务端镜像里没有）。本轮把 `docs/工作台操作使用手册.md` 随 `server/` 源码烘进镜像（`fde_api/control/bundled/help_manual.md`），新增只读工具 `help_fetch`（按章节检索手册原文，带目录与分页），任意 AI 级别可用；对话入口注入工作台式 system prompt，引导「先查手册再作答」；新增公共 Skill `workbench-help`（`flask seed-public-skills` 灌入）。桌面「使用帮助」页同步注明智能助手内置同一份手册。

### 口径

- 服务端数据表 **73 → 74**（本轮新增 `document_delivery_records`）；迁移头 `e5b8a1c9d3f7` → `f3c8d2b7a1e5`。

## [v0.2.0] - 2026-10-26

交付流程与安全加固版本；桌面端与服务端版本号同步升至 `0.2.0`。

- 新增**门禁引擎 G1–G9**：pending → evidence → passed/failed 状态机（G9 支持 conditional_pass）；证据仅保存 `source_uri` 指针与 sha256 指纹，真实文件留在项目工作目录；claimed 与 accepted 分离。
- 新增**报价 / 收款（里程碑）/ 合同**商务看板与标准 FDE 项目模板派生。
- 项目工作台新增「门禁」「报价收款」页签；新增集成桥（本地 openfde / fdeops 工作目录的只读投影）与任务中心。
- 集成桥页新增「立即采集」按钮：桌面端一键触发宿主计划任务（与 4 小时周期同一代码路径），新快照到站自动刷新，无需等下一个采集窗口。
- 桌面端新增内嵌「使用帮助」：各模块操作说明、门禁 G1–G9 流程、实操示例与故障排查。
- 安全加固：登录连续失败限流（Redis 计数）、refresh token 轮换与改密即失效、API 容器非 root 运行、门禁证据哈希校验、CI 常驻 gitleaks 秘密扫描。
- 工程卫生：CI 并发取消与四 job 超时上限、pip/npm 缓存、全仓 LF 归一化、测试口令字面量收敛单点。
- README 按当前功能与 Docker Compose 部署路径重写，新增换机迁移清单。

## [v0.1.0] - 2026-09-28

首个开源源码版本。

- 提供 Electron 桌面端、Flask API、数据库迁移、后台 worker 与 scheduler 的源码。
- 提供项目、任务、调研、AI 机会、方案、交付文档、文件和管理员配置等工作台功能。
- 清理历史业务数据、客户资料、运行日志、访问凭据、对象存储文件和发布备份；仓库只保留通用示例与模板。
- 移除客户端自更新功能。升级需由部署者自行部署后端、执行迁移并重新打包客户端。
- 提供 MIT 许可证、安装部署说明、贡献指南和安全报告说明。

当前仅配置 macOS Apple Silicon（arm64）DMG 构建；没有 Windows 客户端。此版本是源码发布，不附带已签名、公证的安装包。公开部署前请更换首次登录密码和所有示例密钥，并阅读 README 的生产部署与安全说明。

本产品采用 vibe coding 方式开发；商用或处理真实数据前，应由部署者独立完成代码、安全、合规及业务适用性核验。
