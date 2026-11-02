# 附录 D（原始证据）：Workbench 本体/知识/调研/指南/行业模板 实码审计

> 生成方式：独立审计子代理对 `D:\test\fde-workbench`（分支 fde-v2，HEAD `0570384`）只读审计（grep/Read）。以下为子代理报告原文。审计日期：2026-11-02。

## 1. 实际读取文件清单

| 文件 | 行数 |
|---|---|
| server/src/fde_api/control/ontology.py | 70 |
| server/src/fde_api/control/knowledge.py | 176 |
| server/src/fde_api/control/models.py（1-180 重点 KnowledgeSnapshot/AutomationTaskRun） | 390 |
| server/src/fde_api/control/routes.py | 374 |
| server/src/fde_api/control/mcp_gateway.py（80-200） | 288 |
| server/src/fde_api/control/automation_jobs.py（grep 定位） | — |
| server/src/fde_api/control/service.py（540-565 dsh_knowledge_for_run） | — |
| server/src/fde_api/research/models.py（全文） | 620 |
| server/src/fde_api/research/subject_service.py（全文） | 911 |
| server/src/fde_api/research/form_service.py（84-705） | 1130 |
| server/src/fde_api/research/project_routes.py（全文） | 505 |
| server/src/fde_api/research/imports.py（结构+400-470、1141-1185、1261） | 1552 |
| server/src/fde_api/research/definitions.py、answers.py、reorder_service.py、template_service.py、template_routes.py、export_service.py、export_jobs.py（函数级定位） | — |
| server/src/fde_api/guidance/ 全部 9 文件 | 131+486+93+35+52+208+53+98+57 |
| server/src/fde_api/templates/routes.py（全文）、service.py（1-520） | 252 / 1137 |
| server/src/fde_api/ai/research_form_service.py（全文） | 458 |
| server/src/fde_api/ai/ai_opportunity_service.py（全文） | 295 |
| server/src/fde_api/ai/opportunity_adjustment.py（全文） | 66 |
| server/src/fde_api/ai/industry_template_service.py（全文） | 236 |
| server/src/fde_api/ai/routes.py（路由骨架）、executions.py（函数级） | — |
| server/src/fde_api/workbench/models.py（63-333、819-905） | 938 |
| 迁移 a7f3c1e9d5b2（全文）、a1d3f5b7c9e2（全文）、b4e8c1a7d2f6（头部 80 行）、ebb003a5c3a8（create_table 索引） | — |
| 测试抽查：test_ai_opportunity_prompt.py(160)、test_research_form_ai.py、test_industry_template_ai_draft.py(133)、test_guidance_adoption.py、test_presurvey_intake.py、test_control_plane_api.py(629-640)、test_research_models.py、imports/reorder 相关 | — |

## 2. 逐条结论

**① control/ontology.py 是纯静态语义目录，不是本体引擎。**
- 证据：`ontology.py:8-70` 只有一个模块级 `ONTOLOGY` dict（`version: "fde-business-ontology-2"`，21 个 entity 文本说明、约 25 条 relations 三元组文本、9 条 invariants 文本）。无表、无 CRUD、无路由、无版本管理。
- 唯一调用方：`control/mcp_gateway.py:106-108`，MCP 工具 `ontology_read` 把 dict 原样返回给 DSH 外部 agent（只读）。桌面端无任何 ontology 引用。**VERIFIED**

**② control/knowledge.py 是"项目级知识快照"物化器，不是 RAG、不是文件内容索引。**
- `knowledge.py:21-167 build_project_snapshot`：把 Project/ProjectModule/ProjectTask/ProjectFile(+current_version 元数据)/ProjectResearchSubject/ProjectResearchPersonalMemo 拼成 `SCHEMA_VERSION="fde-ontology-v1"` 的 payload，`sha256` 规范化 JSON（148-149），按 `(project_id, content_sha256)` 唯一约束去重后写 `knowledge_snapshots` 表（`control/models.py:110-126`）。
- 数据存哪：PG 表 `knowledge_snapshots`（payload_json 全量 JSON）。文件只进 `content_ref` 元数据（id/sha256/mime），不索引正文。
- 与 ontology.py 的关系：代码上零耦合——两者都喂给同一个 MCP gateway（`mcp_gateway.py:173` 的 `project_read` 工具用快照 payload）。消费方：`automation_jobs.py:66`（每次 run 挂快照）、`control/service.py:544 dsh_knowledge_for_run`（`/api/v1/internal/dsh/executions/<run_id>/knowledge`，DSH service token 鉴权）。**VERIFIED**

**③ 调研域 ER（全部 VERIFIED，research/models.py）**
- `projects` 1—N `project_research_subjects`（models.py:149-216；`project_id` FK + 复合自引用 FK `(project_id,parent_subject_id)`；`subject_type ∈ {project,department,role,process,opportunity}`（CheckConstraint 163-166）；唯一 `(project_id, subject_key)`、`(project_id, tracking_code)`（role→JOB-nnnn、opportunity→OPP-nnnn，`subject_service.py:28,538-566`）；status active/archived；version 乐观锁）。
- opportunity 是 subject 的类型化子身份：`project_ai_opportunity_profiles`（models.py:254-280，PK=subject_id，1:1；`opportunity_status ∈ discovered/assessing/ready/converted/paused`、三项 1-5 评分、`evidence_json`、`ai_generated` 布尔）。
- 有类型业务链接：`project_research_subject_links`（313-365；`link_type ∈ {opportunity_role, opportunity_process}`（服务层白名单+方向校验 `_validate_link` 659-670）；唯一边 `(source,target,link_type)`、禁自环；双复合 FK 强制同项目，另有 ORM 事件监听器 414-442 同步/拒绝跨项目）。
- 问卷：`project_research_forms`（445-505；唯一 `(subject_id, form_key)`；`source_template_research_form_id` 可空 FK；`current_revision_id`）→ `project_research_form_revisions`（542-593；`revision_number` 递增、`status ∈ draft/confirmed/archived`、`parent_revision_id` 版本链、`definition_snapshot` JSON 冻结定义、`returned_by/at/comment` 驳回留痕）→ `project_research_answers`（596-620；唯一 `(revision_id, field_key)`、`value_json`、`source_template_research_field_id`）。
- 个人备忘 `project_research_personal_memos`（219-252，唯一 project+subject+user）；导入回执 `project_research_import_batches`（283-310，幂等）；导出 `project_research_exports`（508-539）。
- 模板侧：`industry_templates`→`industry_template_versions`（draft/published/inactive）→`template_modules`→`template_tasks`→`template_task_dependencies`；`template_research_forms`→`template_research_sections`→`template_research_fields`（58-146）。项目立项时冻结：`projects.source_template_version_id + template_snapshot + research_snapshot`（workbench/models.py:290-297）。
- 模块（module）= 项目实施单元：`project_modules`（FK project + module_catalog）；调研表通过 `module_key` 与模块弱关联（form_service.py:155-157）。

**④ 证据 / 版本 / 审核 / 冲突四项逐项**
- 来源证据：**有（JSON 内嵌，无一等证据表）**。`project_ai_opportunity_profiles.evidence_json`（AI 发现时逐字校验 `answer_excerpt` 必须来自源文本，ai_opportunity_service.py:225-233 `quoted()`）；guidance `evidence_json` + 每条目 `source_refs`（guidance/ai_schema.py:53-56 校验引用必须存在）；门禁证据 `gates.evidence_uri/evidence_hash`、`sop_nodes.source_uri/content_hash`（b4e8c1a7d2f6 迁移 38-71）；bridge 投影 `openfde_source_uri/openfde_content_hash`（workbench/models.py:838-844）。**VERIFIED**
- 版本：**有，三层**。行级乐观锁 `VersionedMixin.version`；记录级修订链 `project_research_form_revisions`（parent_revision_id）与 `project_guidance_analyses.version_number`；内容级快照 `knowledge_snapshots`（sha256 内容寻址）、`definition_snapshot`、`template_snapshot/research_snapshot`。**VERIFIED**
- 审核：**有**。表单 revision `draft→confirmed`（`confirm_form_revision` form_service.py:339-384）+ 驳回（517-551）；guidance `draft→confirmed→superseded`（`confirm_analysis` service.py:185-245，reviewed_by/reviewed_at，旧 confirmed 自动 superseded）；模板 `draft→published`（published_by/at）。confirmed revision 不可变（`assert_revision_mutable`，research/models.py:53-55）。**VERIFIED**
- 冲突处理：**部分**。同项目重复靠唯一约束；**无合并逻辑、无术语冲突检测**——导入的 subject_key 是合成键 `import_{type}_{preview_id}_{row}`（imports.py:1261-1262），同名实体重复导入会各建一行，去重全靠人工；无 merge 端点。**PARTIALLY VERIFIED**

**⑤ 访谈/文件/答案/bridge 事实 → 业务模型的转换路径**
- 访谈记录与文件：无独立"访谈"表；现场记录落在 subject.memo / personal_memo（20k 字文本）和 file_reference 型问卷答案。**VERIFIED**
- 问卷答案：`project_research_answers.value_json`，受 `answers.py validate_answer` 按 definition_snapshot 校验（10 种 field_type、条件显显隐）。**VERIFIED**
- bridge 采集（业务系统事实）：`bridge_engagements` 只是真相层（openfde ledger.db / fdeops .registry 文件）的**单向投影**（"文件永远赢"），**不会转成任何业务模型**；无 subject/机会生成管道。**VERIFIED**
- AI 生成问卷：入口 `POST /api/v1/ai/industry-template/research-form/generate`（admin）与 `POST /api/v1/ai/project-research-form/generate`（admin/lead/fde）。输入 = 模板版本或 project+subject + requirement + existing_forms；输出 = 一份完整 form 定义 JSON（`ai/research_form_service.py:1` docstring 明言 "without persisting it"——**不落库**）。持久化走人工确认后的常规端点 `POST /projects/{id}/research/forms`。
- AI 机会提示词：入口 `POST /api/v1/ai/project-ai-opportunities/discover`。服务读当前 revision 答案与备忘录组装 evidence_sources（ai_opportunity_service.py:39-108），DeepSeek 输出 candidates（≤8 条），`_normalize_candidates` 强校验证据可溯源（225-233）。**结果不落库**，返回前端；落库走 `POST /projects/{id}/research/subjects`（subject_type=opportunity，携带 opportunity_profile.evidence/ai_generated=true，subject_service.py:763-794 接受 evidence 最多 50 条 dict）。adjust 流程同理只回 proposal。SSE 执行态存 Redis，不进 DB。**VERIFIED**

**⑥ guidance 模块**
- adoption（采纳流）：`translator/routes.py:63-75 POST /translations/<id>/adopt` → `guidance/service.py:248-332 adopt_translator_draft`：ready 翻译草稿 → 新建 `ProjectGuidanceAnalysis`（version_number 递增，status=draft，source_kind=translator_draft，唯一约束 `(project_id, translation_id)` 防重复采纳 + IntegrityError 兜底），O-3 额度落 `seat_action_ledger`，事件 `translator_draft_adopted`。**这确实是"候选→人工编辑→确认"雏形**：AI/翻译产物只是 draft，须 lead/admin `confirm_analysis`（185-245）才 confirmed 并 superseded 旧版。**VERIFIED**
- redaction：`guidance/redaction.py:12-28`——正则检测密码/密钥/token（命中直接抛 `SensitiveCredentialDetected` 拒绝送 AI），邮箱/手机/座机/身份证替换为脱敏占位。**VERIFIED**
- m10_evidence：迁移 `a1d3f5b7c9e2` 实际 schema 变更只有：guidance 加 source_kind/translation_id + 唯一约束 + source_file 双列放宽 nullable，及 seat ledger 枚举放宽。"纪要证据"本体仍是 baseline 已有的 `project_guidance_analyses.evidence_json`（每条目 source_refs 指向 `kimi-file:{file_version_id}`）。**VERIFIED（证据基座=既有字段，非新表）**
- 另有 G3 前置闸 `_require_s3_gate`（service.py:402-416）：S3 开工门未 passed 禁止 DOCX 分析；轻量录入卡 `presurvey_intakes`（1:1）S1-S2 即可填。**VERIFIED**

**⑦ industry template**
- 结构：**关系表而非 JSON schema 文件**；JSON 快照只在立项时冻结进 `projects.template_snapshot/research_snapshot`（projects/service.py:126-149）。
- AI draft 流程：`POST /api/v1/ai/industry-template/chat`（咨询不落库）→ `POST .../generate` → `generate_project_configuration`（对 active module_catalog 校验，失败带错重试一次）→ `templates/service.py:215-295 create_ai_template_draft` **原子落库** IndustryTemplate + v1 draft 版本 + 模块 + 可选 research forms + 事件。取消走 Redis 标记。
- 版本/发布：**有**。`version_number` 唯一、`status ∈ draft/published/inactive`、`published_by_user_id/published_at`（workbench/models.py:98-141）；发布即锁版——`update_draft_version` 非 draft 报 immutable（service.py:326-330 注释明言堵过 admin 打穿的口子）；修改走 copy→draft→publish（389-460）。**VERIFIED**

**⑧ 项目隔离与权限**
- research/guidance 全部业务表带 `project_id` FK；subject 链接双复合 FK 数据库级强制同项目；`research_forms` 亦复合 FK `(project_id, subject_id)`。**VERIFIED**
- 跨项目共享（有意为之，全局无 project_id）：`module_catalog`、`industry_templates/versions`、`template_modules/tasks`、`template_research_*`。
- 权限检查两层：路由层 `@require_auth` + 模板/AI 路由 `@require_role`；服务层统一 `project_access(actor, project)`（can_view/can_manage/can_update_assigned_tasks）。**VERIFIED**

**⑨ 重复实体 / 跨项目引用 / 术语冲突**
- 唯一约束：`(project_id, subject_key)`、`(project_id, tracking_code)`、link 唯一边、`(subject_id, form_key)`、`(revision_id, field_key)`、guidance `(project_id, translation_id)`、knowledge `(project_id, content_sha256)`、模板 `(template_id, version_number)`。**VERIFIED**
- 跨项目引用：subject 父子/链接/表单三处复合 FK + ORM 监听器堵死。**VERIFIED**
- 术语/实体冲突：**无任何机制**——无术语表、无同义词/别名、无名称查重（name 可重复，身份靠 subject_key/tracking_code）；导入合成键绕开 key 冲突 ⇒ 同名不同 key 的重复实体可无限累积，唯一治理手段是人工 archive。**VERIFIED（缺失确认）**

## 3. 关键调用链（7 条）

1. `POST /api/v1/projects/<pid>/research/subjects` → `research/project_routes.py:72 create_subject_route` → `subject_service.create_subject`(54) → 锁项目行 + `create_subject_in_transaction`(484) → `next_tracking_code`(538) + `initialize_subject_forms`（form_service.py:131，从 `projects.research_snapshot` 物化表单）→ 写 `project_research_subjects / project_ai_opportunity_profiles / project_research_forms / project_research_form_revisions` + `operation_events`。
2. `POST /api/v1/projects/<pid>/research/forms/<fid>/confirm` → `project_routes.py:429` → `form_service.confirm_form_revision`(339) → 必填项校验 → revision.status=confirmed → `operation_events(project_research_form_confirmed)`。
3. `POST /api/v1/projects/<pid>/guidance-analyses` → `guidance/routes.py:35` → `create_analysis`(service.py:58) → G3 闸 + 源文件校验 → 插入 draft 行 → `enqueue_outbox("project.presurvey.analyze")` → worker `jobs.handle_presurvey_analysis`(43) → KimiFileClient + redaction/validate → 回写 `project_guidance_analyses`（analysis_state=ready）→ 人工 `POST .../confirm` → confirmed + 旧版 superseded + 源文件版本 deprecate。
4. `POST /api/v1/translator/translations/<id>/adopt` → `guidance/service.adopt_translator_draft`(248) → 新 `ProjectGuidanceAnalysis(source_kind=translator_draft)` + `seat_action_ledger` + 事件。
5. `POST /api/v1/ai/project-ai-opportunities/discover` → `ai/routes.py:134` → `ai_opportunity_service.discover_ai_opportunities`(39) → 读 forms 当前 revision answers + memos → DeepSeek → `_normalize_candidates`(210，证据逐字校验) → **仅返回 JSON，不写库**；持久化回到链 1（前端保存）。
6. `POST /api/v1/ai/industry-template/generate` → `industry_template_service.generate_template_draft`(58) → `templates/service.create_ai_template_draft`(215) → 原子建模板+draft 版本+模块+research forms+事件；发布 `POST /industry-templates/versions/<id>/publish` → `publish_template_version`(463)。
7. DSH/自动化：`AutomationTaskRun` → `automation_jobs.py:66 build_project_snapshot`（或 MCP `project_read`）→ `knowledge.py:21` → sha256 去重写 `knowledge_snapshots` → `GET /api/v1/internal/dsh/executions/<run_id>/knowledge`（service token）→ `control/service.dsh_knowledge_for_run`(544)；MCP `ontology_read`（mcp_gateway.py:106）→ 静态 `ONTOLOGY` dict。

## 4. 相关表清单

| 表名 | 模型类 | 文件 | 关键字段 | 迁移 revision |
|---|---|---|---|---|
| project_research_subjects | ProjectResearchSubject | research/models.py:149 | project_id, parent_subject_id, subject_type, subject_key(UQ), tracking_code(UQ), status, version | ebb003a5c3a8(baseline) |
| project_ai_opportunity_profiles | ProjectAIOpportunityProfile | research/models.py:254 | subject_id(PK/FK), opportunity_status, priority, 三评分, evidence_json, ai_generated | baseline |
| project_research_subject_links | ProjectResearchSubjectLink | research/models.py:313 | project_id, source/target_subject_id, link_type, UQ 边 | baseline |
| project_research_forms | ProjectResearchForm | research/models.py:445 | project_id, subject_id, source_template_research_form_id, form_key(UQ), current_revision_id, version | baseline |
| project_research_form_revisions | ProjectResearchFormRevision | research/models.py:542 | form_id, revision_number(UQ), status(draft/confirmed/archived), parent_revision_id, definition_snapshot, returned_by/at/comment | baseline |
| project_research_answers | ProjectResearchAnswer | research/models.py:596 | revision_id, field_key(UQ), value_json, source_template_research_field_id | baseline |
| project_research_personal_memos | ProjectResearchPersonalMemo | research/models.py:219 | project_id+subject_id+user_id(UQ), memo, version | baseline |
| project_research_import_batches | ProjectResearchImportBatch | research/models.py:283 | id(PK=preview_id), project_id, subject_type, expected/committed_project_version, result_json | baseline |
| project_research_exports | ProjectResearchExport | research/models.py:508 | project_id, form_id, status, project_file_id, file_version_id | baseline |
| template_research_forms/sections/fields | TemplateResearch* | research/models.py:58/94/117 | template_version_id, form_key(UQ), subject_type, module_key; field_type ∈ 10 种 | baseline |
| presurvey_intakes | PresurveyIntake | guidance/models.py:21 | project_id(PK), industry/scale/region/interview_mode/interviewee_roles/customer_vision… | a7f3c1e9d5b2 |
| project_presurvey_sources | ProjectPresurveySource | guidance/models.py:56 | project_id(PK), project_file_id, current_file_version_id, version | baseline |
| project_guidance_analyses | ProjectGuidanceAnalysis | guidance/models.py:73 | project_id, version_number(UQ), source_kind(presurvey_docx/translator_draft), translation_id(UQ 组合), source_file_id/version_id, source_sha256, status(draft/confirmed/superseded), analysis_state(6 态), 11 个 *_json 清单字段, evidence_json, ai_model, reviewed_by/at, version | baseline + a1d3f5b7c9e2 |
| industry_templates / industry_template_versions | IndustryTemplate / IndustryTemplateVersion | workbench/models.py:74/98 | template_key(UQ), latest_published_version_number；version: version_number(UQ 组合), status(draft/published/inactive), published_by/at | baseline |
| module_catalog | ModuleCatalog | workbench/models.py:63 | module_key(UQ 全局), name(UQ), is_active | baseline |
| projects | Project | workbench/models.py:235 | source_template_version_id, template_snapshot(JSON), research_snapshot(JSON), sop_phase, business_line, version | baseline + b4e8c1a7d2f6 |
| sop_nodes / gates | SopNode / Gate | workbench/models.py:512/560 | source_uri/content_hash；gates: evidence_uri/evidence_hash, status, decision | b4e8c1a7d2f6 |
| knowledge_snapshots | KnowledgeSnapshot | control/models.py:110 | project_id, schema_version(fde-ontology-v1), content_sha256(UQ 组合), payload_json | baseline |
| automation_task_runs | AutomationTaskRun | control/models.py:128 | knowledge_snapshot_id(FK), status, idempotency_key | baseline |
| operation_events | OperationEvent | workbench/models.py:879 | actor/project/target_type/target_id/event_type/occurred_at/changes | baseline |
| bridge_engagements / bridge_sync_runs | BridgeEngagement / BridgeSyncRun | workbench/models.py:819/847 | slug(UQ), openfde/fdeops 双轨 source_uri+content_hash+状态 JSON | baseline |

## 5. 相关路由清单

| Method | Path | Handler | 权限 |
|---|---|---|---|
| GET/POST | /api/v1/projects/<pid>/research/subjects（+reorder） | project_routes.py:46/62/72 | require_auth（服务层写权限） |
| PATCH/DELETE | …/research/subjects/<sid>（memo、personal-memo、links 同前缀） | project_routes.py:150-297 | require_auth + 服务层 |
| POST | …/research/subjects/imports/preview、/commit | project_routes.py:94/121 | require_auth + authorize_subject_import |
| GET/POST | …/research/forms（+definition/confirm/reject/revise/export） | project_routes.py:300-476 | require_auth（fill=成员；confirm/reject=lead/admin） |
| GET/PUT | …/presurvey-intake；POST …/presurvey-source | guidance/routes.py:78-91/20 | require_auth（写 manage=True） |
| GET/POST/PATCH | …/guidance-analyses（+revisions/confirm、GET /guidance） | guidance/routes.py:28-98 | require_auth（写 manage=True；confirm 记 reviewed_by） |
| POST | /api/v1/translator/translations/<id>/adopt | translator/routes.py:63 | require_auth（owner/admin + 项目 manage） |
| GET/POST/PATCH/DELETE | /api/v1/industry-templates[/versions/…]（publish/deactivate/copy） | templates/routes.py:28-191 | 读 admin/project_lead；写 admin |
| GET/POST/PATCH/DELETE | /api/v1/industry-templates/<tid>/versions/<vid>/research-definition | research/template_routes.py | require_role |
| POST | /api/v1/ai/industry-template/chat、/generate、/research-form/generate | ai/routes.py:71-109 | admin |
| POST | /api/v1/ai/project-research-form/generate、/project-ai-opportunities/discover、/adjust | ai/routes.py:111-142 | admin/project_lead/fde_engineer + 服务层项目权 |
| POST/GET | /api/v1/ai/executions[…] | ai/routes.py:42-69 | admin/project_lead/fde_engineer |
| GET | /api/v1/internal/dsh/executions/<rid>/knowledge（及 approvals/execute） | control/routes.py:273-323 | DSH service token（verify_service_token） |
| MCP | 工具 ontology_read / project_read / file_read 等 | control/mcp_gateway.py:100+ | 签名 claims + capability 白名单 |

## 6. 可复用 vs 缺失（面向 Ontology Registry）

| 本体注册表要素 | 现状 | 可复用资产（精确表/字段） |
|---|---|---|
| 实体注册（typed entity） | 部分可复用 | `project_research_subjects`（5 类型枚举 + 稳定 ID + subject_key + tracking_code）；局限：类型是 CheckConstraint 硬编码，不可扩展 |
| 关系注册（typed relation） | 部分可复用 | `project_research_subject_links`（有类型边 + 唯一 + 同项目 FK）；局限：link_type 白名单硬编码 2 种 |
| 受控词表 | 可复用 | `module_catalog`（全局 module_key）；`sop_nodes.node_key` |
| 证据链接 | 弱复用 | `project_ai_opportunity_profiles.evidence_json`、`project_guidance_analyses.evidence_json/source_refs`、`gates.evidence_uri/hash`、`bridge_engagements.*_source_uri/content_hash`——全是 JSON 内嵌或列指针，无一等 evidence 表（无独立 ID/类型/版本/多实体反链） |
| 版本 | 强复用 | `VersionedMixin.version`（乐观锁）、`project_research_form_revisions`（修订链+快照）、`industry_template_versions.version_number+status`、`knowledge_snapshots.content_sha256`（内容寻址） |
| 审核/批准 | 强复用 | revision/guidance/template 三套 draft→confirmed/published 状态机 + reviewed_by/at + operation_events 审计 |
| 变更集（changeset/diff 评审） | 缺失 | operation_events 只有 changes 摘要，无 diff 实体、无批量变更事务单元 |
| 术语/同义词/术语冲突 | 完全缺失 | 无 glossary/term/alias 表；ontology.py 是静态说明文本，无 CRUD |
| 实体合并/去重 | 完全缺失 | 无 merge 端点；导入合成键允许同名重复累积 |
| 跨项目共享本体 + 治理 | 缺失（仅模板词表全局共享且无治理流程） | industry_template_versions 可作"已发布共享资产"的先例（publish 锁版 + 快照冻结） |
| 本体本身的可写/版本化 | 缺失 | ONTOLOGY dict 由代码发布列车携带（"fde-business-ontology-2"），无表无历史 |
| AI 候选→采纳管线 | 部分复用 | discover/adjust/generate 均不落库（好）；guidance adopt+confirm 是唯一"候选→审核→采纳"闭环样板，可推广到术语/实体候选 |

## 7. 无法验证的项

1. `ebb003a5c3a8_baseline_pg.py` 仅按 create_table 索引核对表存在性与关键约束来源，未逐列比对全部 96 表。
2. Desktop 端仅 grep 级确认 AI 候选"前端保存回常规 API"的交互（未逐屏核）。
3. `control/service.py`（44KB）只精读 dsh_knowledge_for_run 与路由引用面。
4. 迁移 a1d3f5b7c9e2 中 "M10 纪要证据" 与 PartyMode §8 文档的对应关系只能以迁移 docstring 为证。
5. `research/exports、answers、reorder、definitions` 为函数级大纲 + 关键段精读。

**总裁定**：本体层 = **静态语义目录（只读，供外部 agent 消费）+ 派生式项目快照**；调研/指南层 = **相当成熟的"项目内类型化实体 + 修订/确认/证据内嵌"业务模型**，具备草稿→确认→驳回→修订与来源溯源纪律；但**不是可写的正式本体引擎**——无术语表、无关系类型注册、无一等证据实体、无变更集与合并去重，AI 产出全部走"建议不落库、人工经常规 API 落库"的保守路线（guidance 采纳流是唯一例外闭环）。
