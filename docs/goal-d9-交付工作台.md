# goal-d9 · 交付工作台升级轮次报告（2026-11-01）

## 〇、预检（只读）

- fork/main = `b4ad9c5`（goal-d8 合并基线），worktree `D:/test/fde-workbench-d9` 分支 `feat/goal-d9`（unset-upstream + node_modules/server/.venv junction + .env/server/.env 拷贝）。
- 并发会话主树痕迹核对：6 M（docs/台账、gates.json、api_catalog、dispatch models/packages/routes）+ ?? 未跟踪，与 d8 收口时一致，全程未碰；本地 main 仍 755e429（ff 顺延）。
- 循环队列：goal-d9 = P3 翻译器全量启动（d8 报告 §四建议 + 台账节三十三 #4/#6）。

## 一、差距清单（本轮覆盖项）

| # | 能力项 | 目标（出处） | 现状（代码证据，b4ad9c5） | 定级 | 行动 |
|---|---|---|---|---|---|
| 1 | P3 翻译器：AI 翻译管道 + 落库 | PRD §3.2 P3「引导式翻译」；d8 报告 §四 | `#/translator` 纯前端骨架（preview.ts 启发式，不调 AI 不落库，提交 disabled）；服务端无 /translator 任何路由 | 本轮 | 新模块 `translator/`（表+服务+jobs+路由），AI 管道走既有文本 JSON 提炼栈（DeepSeekClient.complete_json，与 research_form/project_draft 同栈；决议①），输出过 `validate_guidance_output` 全契约 |
| 2 | 终审台「产物+纪要」合并视图 + 拍板收口 | PRD §3.2 P3；总纲 U5；d8 报告 §四 | U5 `GET .../review-trail`（d6）只吐会议+纪要；signoff checkpoint 只有创建（handoff_run）**无收口端点**——pending checkpoint 永远无人能 approved/rejected；桌面 SolutionDetailPage 只有降级徽标 | 本轮 | ①`POST /solutions/{id}/signoff` 拍板收口（approved/rejected + 权限档闸 + attempt 计数 + 事件留痕）；②review-trail 响应扩 artifacts + signoff 状态（终审台单端点数据源）；③桌面合并视图（产物表+纪要+拍板按钮） |
| 3 | 指标埋点三件转实 | PRD §10 P0/持续观测；台账节三十三 #4 | metrics/service 三卡硬编码 insufficient（sow_first_pass/senior_intervention/interception，d8 诚实口径） | 本轮 | ①拍板事件=signoff 收口 record_event（②落点）；②介入时长=handoff 事件（已有 agent_run_handoff）↔拍板事件按 run_id 配对；③拦截事件=C-1 422 落账点补 record_event（产物已落 reviewed=False，事件补计数语义）；三卡改实算，样本 0 仍 insufficient（_metric 既有语义） |
| 4 | agent_assisted 桌面化 | d8 报告 §四建议 | 服务端白名单已透出 agent_assisted/difficulty 两键（d8）；桌面 dispatch 页零消费 | 本轮 | 派单控制台/接单池行+详情：难度档位徽标 + 协同状态 + 声明/撤销按钮（accepted 且本人为接单人或 admin） |

**验收判据**：翻译链路实测（表单→job→AI→契约校验→落库 ready，confirmed 全 False）；终审台合并视图可用且拍板全链（权限档 403/无 pending 409/approve+reject 事件链/attempt 递增）；埋点三件有数即 ok、空库仍 insufficient；agent_assisted 桌面按钮状态守卫；8 态机/隔离基线零触碰；pytest/vitest 全量绿 + 变异闭环 + 迁移双跑 + 容器四重。

**不做边界（防蔓延）**：翻译草稿→项目 guidance 录入卡「采纳流」挂账；翻译草稿人工编辑/逐条确认 UI 挂账；export-sow 是否强制 signoff approved（拍板闸语义）不动挂账；artifacts reviewed 标记在拍板 approved 时的翻转语义挂账（本轮零触碰 reviewed 列）；U6 话轮成本归集/M10 Stage A/B/std-full 模板/试点前 iptables+CLI 联调/D10 五项承前挂账；翻译管道 provider 不接 kimi 文件客户端（决议①）。

## 二、行动说明

### 决议登记

- **决议 ①（翻译管道 provider）**：循环提示词写「AI 翻译管道（kimi）」；代码实测=文本 JSON 提炼栈是 `DeepSeekClient.complete_json`（research_form/project_draft 同栈，可注入+可重试+降级链齐备），而 `KimiFileClient` 是 DOCX 文件客户端（预调研专用，翻译器无文件输入不适用）。按冲突裁决顺序（代码实测 > 设计文档）走 DeepSeek 文本栈，provider 经 `deepseek_translator_model` settings 单点可换——「kimi 化」挂账（换 provider 只改 settings/注入点）。
- **决议 ②（拍板路径不进 api_catalog）**：`POST /solutions/{id}/signoff` 是人工拍板动作本体，按红线「api_catalog 不收代拍板写路径」有意不收编（测试钉住）；translator.translate（创作类写，AI 只出草稿无拍板语义）沿 agent_assisted_declare 先例收编。
- **决议 ③（资深介入时长配对键）**：`solution_review_checkpoints.handoff_run_id` 新列（软引用无 FK，沿 triggered_by_run_id/retry_of 偏离先例）——L3 接管→拍板收口按 run 配对，事件 payload 携带 run_id；报表取事件序计算。
- **决议 ④（翻译草稿个人席位资产）**：translator_translations 无项目维度（created_by 归集，本人或 admin 可读）；O-3 计费挂账（seat_action_ledger.project_id NOT NULL，翻译器额度计量随「采纳流」一并落）。
- **决议 ⑤（潜伏 bug 家族全修）**：实施桌面化时发现派单桌面页簇 12 处对 `apiRequest` 返回值再取 `.data`——而 renderer 客户端（client.ts `unwrapApiResponse`，先于派单页簇存在）已解包 `{data,error}` 信封，二级取值恒 undefined → **B1/B2 派单列表页线上恒渲染为空**（潜伏至今未被发现：单测 mock 喂的是信封，假绿）。本轮机械修复全部 12 处（DispatchPool/Console/MyOffers×2/MySettlements/Disputes/ClaimGates/CapabilityProfiles/RuleVersions/Simulator/Console offer-trail+match）+ 测试 mock 适配解包后载荷（dispatch-page/mine/console/ops 四文件）。

### 变更清单

- **迁移 1 个** `c5e9b3d7a1f5`（20 revision）：+`translator_translations` 表（状态机 pending/running/ready/failed）+ `solution_review_checkpoints.handoff_run_id` 列（additive only，downgrade 先列后表）。96 业务表（97 含 alembic_version）。
- **服务端新模块** `translator/`（models/ai_prompt/jobs/service/routes 五件 + `__init__`）：POST /translations（创建+outbox 投递）/ GET /translations（本人最近 20）/ GET /translations/{id}（轮询，创建人或 admin）；job 处理器沿预调研重试语义（瞬时退避/契约立即重试/耗尽 failed 分类可见/终态幂等/worker-loss 钩子/reconcile 可重投）。
- **solutions**：+`POST /<solution_id>/signoff`（拍板收口：pending 闸 409 + 权限档闸 403 + attempt=rejected 数+1 + 事件 `solution_signoff_resolved` 携 run_id）；review-trail 扩 `artifacts`（幂等键家族 ∪ checkpoint.handoff_run_id 并入——handoff 路 L1/L3 产物进终审台）+ `signoff` 块；handoff_run 落 checkpoint.handoff_run_id。
- **agents**：C-1 422 拦截点补事件 `ai_output_intercepted`（产物行承载「哪份被拒」，事件承载「发生了拦截」计数语义）。
- **metrics**：三卡转实算（SOW 一次拍板率=首拍板事件 approved 占比/介入时长=接管→拍板中位小时数/拦截率=拦截事件÷(completed+拦截)）；空库仍 insufficient（_metric 语义）。
- **dispatch**：白名单 +`accepted_user_id`（资源 id 先例，声明按钮门控）。
- **桌面**：TranslatorPortalPage 全量接线（提交→800ms 轮询→AI 草稿卡：severity/module/classification 徽标+「AI 草稿·待人工确认」+失败码透出；本地启发式预览保留）；新 SignoffConsole 组件挂 SolutionDetailPage（产物+纪要+拍板三区合并）；DispatchPool/Console 难度档位徽标+协同状态+声明/撤销按钮（接单人本人/admin 两通道）。
- **api_catalog** +2（91→93）；蓝图路由 264→**268**（translator 3 + signoff 1）。
- **行为变更声明**：start_run C-1 拦截路径新增一次事件写入（行为不变，多一行 OperationEvent）；handoff 语义零变化（仅多落一列）；review-trail 响应新增两键（既有三键不动，旧消费者零破坏）；既有测试适配 3 处（test_metrics_report 空库三卡断言、test_migrations HEAD、test_dispatch_p0_r3 白名单键数）+ 桌面 dispatch 四测试文件 mock 解包适配（决议⑤连带）。回滚：`alembic downgrade -1` + 代码回滚。

## 三、验证结论

| 判据 | 结果 |
|---|---|
| 翻译链路实测 | ✅ 表单→outbox→job→AI（注入假客户端）→`validate_guidance_output` 全契约→ready 落库；13 用例（401/字段校验 3 组/outbox 投递/成功草稿 confirmed 全 False/契约违约重试 1 次耗尽 ai_output_invalid/瞬时退避 ai_rate_limited/不可重试一次败/终态重放幂等/worker-loss 终态/本人作用域+admin 通道/RECOVERABLE 钉子） |
| 终审台拍板全链 | ✅ 9 用例（401+路由存在/无 pending 409/低档 403 signoff_level_required/decision+evidence_ref+多余字段 400 三组/approve 200 事件 attempt=1/驳回→再批 attempt=2 事件序/run 软链携带/review-trail 合并视图 artifacts+signoff（handoff 路家族并入）/catalog 红线钉子） |
| 埋点三件转实 | ✅ 空库三卡 insufficient（value 0.0/None 语义分卡）；造事件后 sow_first_pass=0.5（首事件口径）/senior_hours=2.0（run 配对，未成对 run 不计）/interception=0.5（1/(1 completed+1 拦截)）；有数即 ok、无数即灰 |
| agent_assisted 桌面化 | ✅ 派单池/控制台难度档位+协同状态显示；声明按钮双通道（接单人本人/admin 管理通道）+ 服务端强校验试错透出；6 用例（含非接单人不可见） |
| pytest | **1666 收集 = 1660 passed / 6 skipped / 0 failed**（d8 1643→+23：translator 13 + signoff 9 + metrics 转实 1；首轮全量 1665 在新 metrics 用例落盘前启动，终验轮 1666 全绿） |
| vitest / typecheck | **721/721 全绿串行**（60 文件；+8 新用例 + 16 例解包契约适配）；typecheck 零错误 |
| ruff / mypy | All checks passed；mypy 基线脚本 OK（baseline 289 / current 279，无新增；frozenset→set 入参修复 1 处） |
| 迁移双跑 | ✅ down→up→down→up 干净（b8c2d6f0a4e7 ↔ c5e9b3d7a1f5）；96 业务表 |
| 变异闭环 | **9×9 红绿**（TRA1 空诉求放行/TRA2 草稿不落库/TRA3 不可重试消耗额度/SGN1' 档位比较翻转/SGN2 attempt 恒 1/MET1 首事件口径翻转/MET2' 时长方向翻转/WEB1 拍板 decision 互换/DSP1' 声明门控放行）。过程记录：2 处变异初版设计无效当场重设计（SGN 值域未翻转→比较符翻转；MET 配对键数据不触发→方向翻转）；DSP1 揭出测试空洞（未展开行）→加固用例后红；TRA1 残留一次由快照字节级核对抓痕→回写清零复绿（d7/d8 同款教训第三次验证有效） |

**反假绿灯四条自检**：①全量数字为正规口径实测（pytest 20:13 单跑两轮、vitest --no-file-parallelism 串行）；②非并发变异（单进程顺序执行，快照唯一）；③CI 差异预案=server-tests 跑 mypy 基线脚本（本地已同口径）；④"全绿"不含 skip 伪装（6 skip 为既有平台性跳过，数量与基线一致）。

## 四、遗留与下轮建议

### 挂账（新登记，台账节三十四）

| # | 事项 | 时点 |
|---|---|---|
| 1 | 翻译草稿「采纳流」：草稿升格为项目 guidance 录入卡/分析版（+O-3 翻译器额度计量随路落） | P3 下一增量 |
| 2 | 翻译草稿人工编辑/逐条确认 UI（当前 ready 草稿只读展示，确认动作无落点） | P3 下一增量 |
| 3 | 翻译管道 provider kimi 化（settings `deepseek_translator_model` 单点，换栈成本低） | 待蔡工拍板模型选型 |
| 4 | export-sow 与 signoff 的强制关系（拍板通过是否为 SOW 导出前置闸）——当前两者独立，语义待拍板 | 待蔡工拍板 |
| 5 | artifacts reviewed 列在拍板 approved 时的翻转语义（本轮零触碰） | 终审流细化 |
| 6 | 桌面 dispatch 页簇串行化 flake：全量并发跑出现资源性假失败（单跑/串行全绿），已固定用串行口径 | 观测 |

### 下轮建议（goal-d10）

- **P3 收口**：采纳流（翻译草稿 → 项目 guidance，决议④的额度计量同路落）+ 草稿确认 UI；「创业者独立闭环 ≥90%」指标开始积累。
- **M10 Stage A/B 证据引用联动**（试点前，台账节三十三 #1）：纪要作派单证据。
- **试点前人工联调**：真实 iptables + zcode CLI 钉定（台账节三十三 #8）。
- D10 五项待蔡工拍板（S 编号映射/九卡原句/报价卡数值禁区/G3 会闸关系/审定流程）+ 本轮新增 #3/#4 两项。
