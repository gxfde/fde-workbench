# V3.1 缺口裁决台账（00-gap-register）

- 基线：fork/main `65db88c`（2026-11-07，P0-0 现测；行号锚钉定该提交）
- 裁决四档：**复用**（现状即可承接，零改动）/ **扩展**（改既有表/服务/路由/UI）/ **新建**（无承接体，论证后新建）/ **暂缓**（需业务拍板或前置闸未过，不排期）
- 任务书 §1.3 纪律：不核验现有能力前不得新增平行表/路由/服务——本台账即为核验结论。**每项新建均已用 grep/结构核验证明无既有承接体**（关键负结论附核验方式）。

---

## P0-1 访谈事实与需求结构化

| # | 能力 | 裁决 | 现状锚 | 理由/缺口 |
|---|---|---|---|---|
| 1.1 | 转写草稿区+正式纪要生命周期 | **复用** | transcripts/models.py:47,119；service.py:248-481；T+7 purge cli.py:250 | T-A9 已交付：draft→promoted/expired/discarded、客户端确认三元组、墓碑纪律、独立文件根 |
| 1.2 | 企业名脱敏三道防线+复核闸 | **复用** | guidance/redaction.py:88-130；confirm 闸 service.py:252-258（409 redaction_review_required）；REDACTION_EVENT_TYPE models.py:23 | 新抽取管线应原样套用（进模型前/落库前/复核清单事件），词典机制 fail-closed |
| 1.3 | 抽取后台任务骨架 | **复用** | outbox+background_jobs+RECOVERABLE 集（jobs/handlers.py:70-117）；范式=project.presurvey.analyze（guidance/jobs.py:98-223，含失败码阶梯+worker_lost 失败钩子） | 克隆该管线形状注册新 job_type 即可 |
| 1.4 | AI 输出 JSON 契约校验范式 | **复用** | guidance/ai_schema.py:43-93（精确键集/条数上限/五分类枚举/**source_ref 闭合校验 missing_source_ref/unknown_source_ref**） | P0-1 的 facts/requirements 契约校验器应同构新写（键不同、纪律同） |
| 1.5 | 结构化事实存储 | **新建** | 负结论核验：`__tablename__` 全集 109 表无 requirements/business_facts/discovery_extractions/requirement_sources；全仓 grep 零命中。最近邻=guidance 11 个 JSON 列（models.py:117-127），但为文档级 JSON 块非规范化行、无逐条审阅态、源仅限预调研 DOCX/translator | 任务书 P0-1 数据模型四表成立；**但条目分类枚举/审阅字段应与 guidance 五分类对齐复用**（customer_stated/ai_synthesized/ai_inferred/open_question/human_added），避免第二套分类学 |
| 1.6 | 逐条审阅（接受/拒绝/澄清） | **扩展+新建** | 现状=guidance 整版 confirm+桌面条目编辑器（GuidanceReview.tsx:174-195，confirmed 复选框/分类下拉）；无逐条 review_status 行级状态机 | business_facts 行级 review_status（pending/accepted/rejected/needs_clarification）为新建；UI 按 GuidanceReview 范式扩展 |
| 1.7 | 来源定位（时间戳/分段/页码） | **新建** | transcripts 正文=无结构文本块，无 segment 模型；docx_extract.py:34-45 有 paragraph/table 细粒度 ref 先例（legacy 腿）；现役 Kimi 腿锚点收敛为单引用 kimi-file:<id>（guidance/jobs.py:122） | source_locator 结构（transcript_segment+start_ms/end_ms）需新建；interview_minutes/transcript_drafts 已有 content_sha256 可作外层指纹 |
| 1.8 | 转写正文分段化（VTT/SRT 解析） | **扩展** | TranscriptDraftsPanel.tsx:160-166 已接受 .vtt/.srt 导入但当作纯文本 | 若锚点要走时间段，草稿入库时需解析 cue 段（或首版锚点退化为行号/字符偏移——设计决策留 P0-1 方案） |
| 1.9 | 事实/需求审阅桌面 UI | **扩展** | TranscriptDraftsPanel.tsx（458 行，现纯文本视图）；GuidanceReview.tsx（195 行，审阅范式） | 在 transcripts/ 或新 discovery/ 页挂事实清单+锚点跳转+批量审阅；loading/empty/error 纪律按任务书 §12 |
| 1.10 | 需求→方案/任务/验收的下游引用 | **新建（本阶段仅立表）** | solutions.acceptance_criteria 为自由文本（models.py:30）；无 requirement 消费方 | P0-3 才消费；本阶段保证 requirement_key 稳定+requirement_sources 唯一约束 |

**P0-1 不做清单**：不动 guidance 现有管线（预调研 DOCX 通道原样）；不做音频入库（红线：大文件只存指针）；不绕过 minutes 客户确认流（任务书约束原文遵守）。

## P0-2 本体候选与领域对象稳定 ID

| # | 能力 | 裁决 | 现状锚 | 理由/缺口 |
|---|---|---|---|---|
| 2.1 | 变更集提案→提交→确认/否决（含物化） | **复用** | ontology/service.py:871-1331：submit 行锁+base_snapshot_sha256 指纹闸、confirm 决策分离 403+单事务全成全败、reject 留痕；路由 12 条 | 任务书 §6 API 目标里的 submit/approve/materialize 已有等价物（confirm 即 approve+materialize 原子步）；**不得加同义路由** |
| 2.2 | AI 候选通道（captured_from） | **复用（机制）/扩展（生产方）** | captured_from 服务层专属（HTTP 拒收 service.py:1779-1781）；现存唯一生产方=research_import（imports.py:1400） | P0-1 落地后新增 `agent_run:{id}`/`discovery:{id}` 生产方；候选关联已确认事实/需求=扩展 proposed_json 条目带 fact/requirement 指针（校验其已 accepted） |
| 2.3 | 候选去重/别名冲突（项目内） | **复用** | UNIQUE(project,term)+UNIQUE(project,alias)+提交时占位名占用快照（service.py:1006-1071） | — |
| 2.4 | 跨项目别名冲突检测 | **暂缓（业务拍板项）** | 现状=所有唯一性项目内（UNIQUE 含 project_id）；无跨项目扫描 | 任务书 §6-2 要求覆盖跨项目范围，但项目间隔离可能是刻意设计（多租户数据边界）——**开 P0-2 前须蔡工拍板**：仅告警（只读呈现冲突提示）还是硬闸；默认建议=只读告警不动唯一性约束 |
| 2.5 | 业务对象稳定 term_id 关联（试点实体） | **扩展** | 全仓无 term_id FK（ontology/service.py:36-40 自述）；subjects/forms/gates 全靠名字精确匹配（impact_of_term 即此合同） | 从一个试点实体起步（建议 project_research_subjects：加可空 term_id FK+回填脚本+读路径兼容名字匹配旧数据）；**不做全库大迁移**（任务书 §6-6 原文） |
| 2.6 | 合并/停用/改名影响分析与回滚 | **复用** | merge_terms 原语（链一跳化+逐项事件）；impact_of_term 三面清单（subjects/links/forms）+T-I1 只读路由 | 回滚=变更集否决路径（物化前）；物化后回滚无通道（与 Gate 终态不可逆同哲学，如实登记） |
| 2.7 | ADR：control/ontology vs ontology/ | **新建（文档）** | control/ontology.py 仅 75 行静态字典+MCP ontology_read 唯一消费方；零代码重叠（00-baseline-audit §8） | 产 ADR-002-ontology-ownership：声明语义投影 vs 治理层职责、MCP 契约冻结、不删旧模块 |

## P0-3 交付方案生成与任务分解

| # | 能力 | 裁决 | 现状锚 | 理由/缺口 |
|---|---|---|---|---|
| 3.1 | 方案文本承载+版本+冻结 | **复用** | project_solutions（TEXT_FIELDS 七键+乐观锁 version+generated_by/agent_run_id/confidence 血缘）；ProjectSolutionExport 冻结快照（UNIQUE(solution,version)）；T-A5 骨架三选项/取舍/明确不做；T-A6 报价→派单包冻结 | 方案行已有版本化与 AI 血缘 |
| 3.2 | 骨架从已确认输入生成 | **复用** | solutions/service.py:804-971（要求 confirmed guidance，409 solution_skeleton_guidance_required）；workflows/compiler.py:143-317（confirmed 变更集→骨架+三节点草稿，纯函数+provenance） | P0-3 生成器应改为消费「已批准需求集」，沿用 skeleton/compiler 双先例 |
| 3.3 | delivery_plans/items/task_links | **新建** | 负结论核验：`delivery_plan` 全仓 grep 零命中；无方案条目级结构 | 需求映射（条目→requirement_id/领域对象/验收标准/风险）无承接体；任务仍以 project_tasks 为唯一事实源（任务书原文），links 只存映射 |
| 3.4 | 条目→任务创建（预览/选择性/幂等） | **扩展** | task_service.create_project_task（依赖无环校验+工作日排期+指派校验）；task_key 项目内唯一=幂等锚 | 新增「从方案条目批量预览创建」服务（复用单条原语循环+task_key 命名约定防重复）；未定负责人→default_assignee_role 已有（不指派具体人） |
| 3.5 | 方案引用已批准需求 | **新建（字段级）** | solutions 现仅挂 opportunities（M2M） | delivery_plan_items.requirement_ids（或链接表）+「未批准项只能标待确认假设」校验 |
| 3.6 | 方案变更新版本不覆盖历史 | **复用** | solution version 乐观锁+export 冻结快照 | delivery_plans 状态机照抄 draft→reviewed→approved→superseded 模式 |

## P0-4 Workflow 模板与草稿生成

| # | 能力 | 裁决 | 现状锚 | 理由/缺口 |
|---|---|---|---|---|
| 4.1 | 定义生命周期+发布不可变+发布时复校 | **复用** | definition_service.py:486-596（draft→published；快照不可变；publish 时按现行白名单复校验） | — |
| 4.2 | DAG 校验（环/call 白名单/skill 钉版/占位符链/外效审批告警） | **复用** | definition_service.py:119-466 | 新节点契约字段（4.4）需配套新校验规则=扩展 |
| 4.3 | 执行器四类节点+幂等+hops+审批复用+恢复 | **复用** | executor.py 全量（B#1/B#28/CR-019/CR-022 等已收口）；对抗钉 test_workflow_executor_adversarial | — |
| 4.4 | 节点契约字段（timeout/输入输出 Schema/权限范围/工具/失败分类/补偿/方案关联） | **扩展** | 节点参数白名单现 12 键（definition_service.py:171-174）；timeout/Schema/失败分类/补偿/plan 关联全缺 | 分两步：先扩白名单+校验（草稿期字段），执行器按字段增强（失败分类→error 码规范化；补偿=新节点类型或显式人工节点，**补偿语义需设计轮拍板**） |
| 4.5 | 平台模板底座 | **复用** | project_id NULL=平台模板（models.py:61-62）+admin 只读列表（routes.py:162-166） | 底座在，**无种子通道**（seeds/ 无 workflow 文件；模板创建走内部 create_definition 无 HTTP） |
| 4.6 | 三套模板内容（需求发现/方案实施/自动化交付） | **新建** | 负结论核验：seeds/ 九个文件无 workflow 模板；活库 workflow_definitions=0 | 种子 JSON+load_seeds 注册+（可选）定义期内部创建通道；模板 dag 直接可用现有四类节点表达 |
| 4.7 | 模板列表非 admin 面 | **扩展** | 现仅 admin GET /api/v1/workflows | 加 can_view 项目成员可见的模板列表（或放宽现有路由权限）——权限策略变更需拍板 |
| 4.8 | draft-from-plan 生成 | **扩展** | compiler.py compile_delivery_preview 先例（纯函数+人工确认落地，任务书 §8 目标的最小样板） | 泛化为从 delivery_plan 生成；落库走既有 draft 创建路由（不新建平行入口） |
| 4.9 | 独立 validate 端点 | **扩展** | 校验现内联于 create/update/publish | 加 POST …/workflows/{id}/validate 干跑端点（复用 validate_dag，只读） |
| 4.10 | 发布权限（现 admin-only） | **暂缓（拍板项）** | routes.py:61-62 | 任务书要求「人工发布」未指定角色；放开到 can_manage 是权限面扩张，需蔡工拍板后实施 |
| 4.11 | Gate 唯一决策入口纪律 | **复用** | 现状已满足：workflow 只能经 output_json.gate_evidence 挂候选（executor.py:752-804），采纳唯一入口=真人提交闸 | P0-4 测试新增「证据类型/项目范围校验」时沿 gate_service 既有闸 |

## P1-1 Agent 执行与 ZCode 宿主代理

| # | 能力 | 裁决 | 现状锚 | 理由/缺口 |
|---|---|---|---|---|
| 5.1 | zcode CLI 契约（0.17.1 真实表面） | **复用** | zcode_contract.py（纯函数，本审计第 7 节核验） | 直接作为宿主通道的参数/汇总解析层 |
| 5.2 | adapter 虚构 spawn 段 | **扩展（重构）** | adapter.py:99-113 spawn_argv 建模不存在的 `zcode run --task/--events`；docstring 自认与真实 CLI 相悖；sandbox 镜像不装 zcode→生产预期 L2 | P1-1 核心改造点：接 execution provider 协议替换 spawn 段；**先对齐在途会话 feat/host-zcode-channel+feat/tz1-host-proxy-contract 的成果再动工** |
| 5.3 | 短期授权票据（绑用户/项目/run/工作目录/动作） | **扩展** | MCP 15min JWT（mcp_gateway.py:58-85：user+auth_version+project+execution+capabilities，_identity 活体复验） | 票据原型可复用；需扩展 run/workspace 绑定与 agent_run 域 issuer |
| 5.4 | 命令/工具白名单+路径规范化 | **扩展** | 工具名三重交集（tools.py:196-227）；artifact unsafe_path 校验（service.py:451-453）；沙箱挂载黑名单+网络 egress 白名单（sandbox.py） | 命令级白名单/工作目录规范化（防 ../symlink 逃逸）为新建策略模块 execution_policy（任务书建议文件清单成立） |
| 5.5 | 宿主代理进程+Provider 协议 | **新建** | 负结论核验：全仓零宿主代理/零 zcode spawn（baseline §7）；宿主代理须独立进程（任务书 §9），不入 Web API 进程 | P1-1 主体；分级开放 A→D 与 12 条安全前置全部未过——**未拍板前保持关闭** |
| 5.6 | AgentRun 执行字段 | **扩展** | 现有 context_ref/exit_code/token_cost/duration_ms/degraded | 补 execution_provider/host_agent_id/authorization_id/workspace_ref/resume_session_ref/策略快照 hash（一迁移） |
| 5.7 | Artifact size/mime/revoked | **扩展** | 现 storage_ref/sha256/kind/reviewed(+by/at)/derived_summary | 补 size_bytes/mime_type 列；revoked=复核撤回态（现仅布尔翻转，撤回留痕弱） |
| 5.8 | 执行收据 | **扩展** | receipt_state 四态分类+回执 DSL（ask/later）已落地 | 「provider 执行收据」（exit_code/终止原因/资源峰值等）为 receipt 语义第三条腿，receipt.py:19-21 已预留语义正交声明 |
| 5.9 | 密码确认/敏感键扫描/幂等键 | **复用** | api_actions 全套；contains_sensitive_argument；sha256 幂等键构造 | authorize-execution 端点直接复用确认流形态 |
| 5.10 | 商用条款/安全评审 | **暂缓（闸）** | 任务书 §9 前置 1（使用条款书面确认）未达成；B 线商务身份材料在文档中心 | 全通道在闸通过前默认关闭+人工接管（任务书验收清单原文） |

## P1-2 自动测试与交付证据

| # | 能力 | 裁决 | 现状锚 | 理由/缺口 |
|---|---|---|---|---|
| 6.1 | 测试产物承载 | **复用** | agent_artifacts.kind=test_results 已在值域；sha256+复核 | 测试报告作为 artifact 的通道现成 |
| 6.2 | 证据登记+门禁校验 | **复用** | project_evidence 指纹幂等；gate 提交闸+候选采纳；execution-facts 时间线 | — |
| 6.3 | test_plans/test_cases/test_executions | **新建** | 负结论核验：quality/ 模块不存在；test_plan/test_case/test_execution 全仓 grep 零命中 | 三表+需求追溯（每条批准需求至少一条用例或人工验收方式）；模型生成用例先进审核态（权限矩阵） |
| 6.4 | 生产环境测试禁止/失败不可改写 | **扩展（纪律实现）** | ai 摘要不改事实的既有钉（B#2 家族）；无环境维度字段 | test_executions.environment 字段+校验；「失败结果不能被摘要 Agent 改写为成功」需钉测试 |
| 6.5 | evidence/validate 端点 | **扩展** | 现 POST …/evidence 为登记；无批量校验语义 | 按任务书语义做只读校验端点（类型/来源/时间/操作者/项目范围） |

## P1-3 指标与经验沉淀

| # | 能力 | 裁决 | 现状锚 | 理由/缺口 |
|---|---|---|---|---|
| 7.1 | 指标报表骨架+样本不足语义 | **复用** | metrics/service.py:61-228（10 指标+insufficient_data+_REAL_RUNS 演练排除） | 新指标进同一报表（不建平行指标面） |
| 7.2 | 事件采集 | **复用+扩展** | operation_events 22 目标类型；gate_*/workflow_run_* 等事件多已在；缺 requirement_approved、ontology_change_materialized（现 confirmed 含物化结果）、delivery_plan_*、task_rework、artifact_accepted/rejected/revoked | 新域事件随各阶段落地时逐个补（target_type 注册表同步扩） |
| 7.3 | 工作流域指标 | **扩展** | metrics 现无 workflow 域（完成率/审批时延/hops 分布） | — |
| 7.4 | delivery_metric_daily 聚合表 | **暂缓** | 现报表即席聚合足够（活库=零数据）；建表须先证聚合不足（任务书 §11 原文「仅在无法聚合时考虑」） | — |
| 7.5 | skill_improvement_proposals | **暂缓** | skill 版本治理四事件在位；消费量闸未过（P3 立项裁决维持）；活库消费事件=1 | 首个真实改进建议需求出现时再立项（agent-policy §2.1 已回写） |

---

## 横切工程纪律（各阶段统一适用，源自任务书 §12-13 与 AGENTS）

1. 迁移一律 expand/backfill/contract；新表三件套（env.py 注册+test_migrations HEAD+conftest 清理序）。
2. 新路由必须：权限测试+（治理面）不进 api_catalog 的显式声明+（AI 面）catalog 五元同步；**改蓝图必须同步 extract_workbench_inventory.py 的 BLUEPRINTS 并重生成审计 CSV**（两次踩坑教训）。
3. 口径四层记账：AGENTS 口径行/CHANGELOG 节/AGENTS bullet/审计 CSV——缺一即静默断档（教训 51）。
4. server 改动 ⇒ rebuild 三镜像+alembic；桌面改动 ⇒ 便携版重打包+asar 验证挂账。
5. AI 输出一律草稿/审核态落地；决策分离（decider≠submitter）沿 Gate/ChangeSet 既有 403 语义。
6. 大文件只存指针+sha256（红线）；客户真实资料永不入库。

## 拍板项汇总（开工前需蔡工确认）

| # | 议题 | 建议 |
|---|---|---|
| D-1 | P0-2 跨项目别名冲突：告警还是硬闸 | 建议：只读告警（不动项目内唯一约束） |
| D-2 | P0-4 工作流发布权限：维持 admin-only 还是放宽 can_manage | 建议：维持现状，试点期由 admin 发布 |
| D-3 | P1-1 宿主通道与在途会话线（feat/host-zcode-channel 等）的对齐归属 | 建议：P0-0 合并后先读该线产出再定 P1-1 施工面 |
| D-4 | P0-1 锚点粒度：时间戳分段 vs 行号/字符偏移（取决于转写格式约定） | 建议：首版支持 transcript_segment(ms)+行号双形态，契约层闭合枚举 |
