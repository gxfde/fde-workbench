# V3.1 数据模型地图（00-data-model-map）

- 基线：fork/main `65db88c`（2026-11-07 现测）；配套 `00-baseline-audit.md` §3 测量配方
- 总口径：**109 张业务表**（不含 `alembic_version`）、**39 revision 单链**、head `e5f1a7c3b9d4`、路由 **323**、api_catalog ENTRIES **94**
- 行号锚钉定于 `65db88c`，引用时若 HEAD 前进需复核

## 1. 迁移链（尾部）

```
… e2c6a8f4d1b3(T-D1 文档血缘) → d9f4a7c2e6b1(T-J2 job cancelled)
  → b2e8f4a6c9d3(P0 批: hops/CAS/receipt) → d7b2f8a4c1e6(T-A9 transcript_drafts)
  → b8e4d6f2a9c3(T-B1 agent_artifacts 扩列) → e5f1a7c3b9d4(T-B1 handover_packages) [HEAD]
```

链首 `ebb003a5c3a8`（baseline_pg, down=None）；revision 集−down_revision 集＝单 head，无孤儿分支。

## 2. 表清单（按模块域分组，109 张）

| 模块 | 表数 | 表名 |
|---|---|---|
| workbench（项目主干） | 21 | projects, project_members, project_modules, project_tasks, project_task_collaborators, project_task_dependencies, gates, quotes, payments, contracts, sop_nodes, module_catalog, industry_templates, industry_template_versions, template_modules, template_tasks, template_task_dependencies, operation_events, ai_call_audits, bridge_engagements, bridge_sync_runs |
| control（治理/插件/技能） | 15+4* | automation_tasks, automation_task_runs, automation_approvals, skill_definitions, skill_versions, plugin_packages, plugin_installations, plugin_installation_revisions, plugin_change_requests, plugin_catalog_syncs, knowledge_snapshots, channel_bindings, ai_model_configs, ai_provider_configs, user_ai_access_grants；*另有 4 张定义在非 models.py：ai_conversations, ai_chat_turns（chat.py）、ai_model_preferences（model_preferences.py）、lcsc_skill_runs（lcsc_skills.py） |
| research（调研域） | 12 | project_research_subjects, project_research_subject_links, project_research_forms, project_research_form_revisions, project_research_answers, project_research_import_batches, project_research_exports, project_research_personal_memos, project_ai_opportunity_profiles, template_research_forms, template_research_sections, template_research_fields |
| agents | 7 | agent_registry, agent_runs, agent_artifacts, agent_tool_calls, agent_credentials, seat_action_ledger, solution_review_checkpoints |
| documents | 7 | document_templates, document_template_versions, project_documents, project_document_versions, project_document_drafts, document_generation_jobs, document_delivery_records |
| dispatch（派单/商务） | 8 | fde_profiles, fde_level_evidence, dispatch_offers, dispatch_rule_versions, delivery_packages, delivery_settlements, package_access, disputes |
| ontology | 4 | ontology_terms, ontology_term_aliases, ontology_relation_types, ontology_change_sets |
| workflows | 4 | workflow_definitions, workflow_definition_versions, workflow_runs, workflow_node_runs |
| transcripts | 2 | transcript_drafts, interview_minutes |
| handover | 2 | handover_packages, handover_package_items |
| guidance | 3 | presurvey_intakes, project_presurvey_sources, project_guidance_analyses |
| meetings | 3 | review_meetings, review_meeting_turns, review_meeting_minutes |
| solutions | 3 | project_solutions, project_solution_opportunities, project_solution_exports |
| jobs（异步底座） | 2 | background_jobs, outbox_events |
| files | 3 | project_files, project_file_versions, upload_sessions |
| auth | 2 | users, refresh_sessions |
| mailing | 2 | mailing_events, mailing_sends |
| evidence | 1 | project_evidence |
| translator | 1 | translator_translations |
| 其他 | 1 | system_configuration（system_configuration.py） |

CI 对账钉：`docs/audit/v3-database-inventory.csv`（109 表）与 `docs/audit/v3-route-inventory.csv`（323 行）由 `scripts/audit/extract_workbench_inventory.py` 生成（**BLUEPRINTS 硬编码清单——新增/删蓝图必须同步登记**，AGENTS 已两次踩坑）。

## 3. V3.1 核心域模型要点（P0-0 深查结论）

### 3.1 Agent 执行（agents/models.py:34-257）

- `agent_runs.status` CHECK 7 值：queued/running/completed/**succeeded_but_receipt_invalid**/failed/timeout/budget_exceeded；`fallback_level` L0–L3；`idempotency_key`（160，索引非唯一——重试族共享，服务层去重）；`context_ref` 仅掩码上下文指针；`retry_of` 软链无 FK。
- `agent_artifacts`：kind ∈ {code,doc,diff,config,**test_results**}；`storage_ref`(255)+`sha256`(64,CHECK)；复核= `reviewed` 布尔+`reviewed_by_user_id/reviewed_at`（T-B1）；`derived_summary` JSON；**无 size/mime/revoked**（P1-1 扩展点）。
- `agent_registry`（kind: zcode/codex/claude_code/opencode/persona；credential_ref 刻意无 FK）、`agent_tool_calls`（allowed/denied 决策留痕）、`seat_action_ledger`（4 类座位动作）、`solution_review_checkpoints`（signoff 闸）。

### 3.2 Workflow（workflows/models.py）

- `workflow_definitions`：status draft/published/archived；`version`+`content_sha256`；project_id NULL=平台模板；发布快照 `workflow_definition_versions`（(definition_id,version) 唯一，不可变）。
- `workflow_runs`：7 态含 waiting_approval；`idempotency_key` 全局唯一；`definition_version` 钉版；`hops`（B#1 熔断，resume 逐代 +1）。
- `workflow_node_runs`：(run_id,node_key) 唯一；8 态；`attempt` 代际（agent 节点 resume 保留=新幂等代）；`depends_on` 快照；外副作用 `idempotency_key`（call=sha256 结构键、agent=`wfnode-{id}:{attempt}`、approval=审批行 id）。
- **无 delivery_plan_id/模板 ID/Schema 版本字段**（P0-4 扩展点）；节点参数白名单 12 键（key/type/ref/depends_on/when/output/max_retries/params/max_cost_units/capability/expires_minutes/effect）。

### 3.3 Ontology（ontology/models.py）

- `ontology_terms`：UNIQUE(project,term)+状态机 draft/confirmed/superseded/merged；`canonical_term_id` 自指（合并链一跳化）。
- `ontology_term_aliases`：UNIQUE(project,alias)＝「一个名字至多一个概念」（名字域纽带的唯一性根基）。
- `ontology_relation_types`：kind subject_type|link_type；project_id NULL=全局（部分唯一索引）；项目内遮蔽全局。
- `ontology_change_sets`：draft/in_review/confirmed/rejected（superseded 保留）；`base_snapshot_sha256` 并发闸；`captured_from` 仅服务层可写（HTTP 拒收）。
- **全仓无任何业务表持 term_id FK**（ontology/service.py:36-40 自述）——业务对象↔本体全靠名字精确匹配（P0-2 核心缺口）。

### 3.4 Gate 与证据（workbench/models.py:560-629 + evidence/）

- `gates`：UNIQUE(project,gate_key)；五态 pending/evidence/passed/conditional_pass/failed；`evidence_checklist` JSON（label/claim_status/source_uri/content_hash/evidence_id）；`evidence_candidates` JSON（T-G1，task/workflow 两源）；`version`（CAS revision）+`lifecycle_version`（语法代际，刻意分离）；`template_hash`（T-G2 漂移呈现）。种子 G1–G9（gates.json）。
- `project_evidence`：UNIQUE(project,source_uri,content_sha256) 指纹幂等不可变；kind 7 值；captured_from 封闭枚举（human/bridge_sync:{id}/agent_run:{id}/job:{id}/workflow_node:{id}）；只存指针+指纹（红线）。

### 3.5 任务（workbench/models.py:393-509）

- `project_tasks`：task_key 项目内唯一；六态 not_started/in_progress/blocked/completed/cancelled；乐观锁 version；`gate` 纯字符串 G1–9（**无 FK**）；`evidence_uri/hash`（T-E3 挂证据）；`default_assignee_role`+`assignee_user_id`；依赖表无自环。**无 acceptance/方案关联字段**（P0-3 扩展点）。

### 3.6 访谈/转写（transcripts/models.py）

- `transcript_drafts`：四态含墓碑；`content_sha256`+`redaction_entries`（与 guidance 复核事件同形）；T+7 `expires_at/ cleaned_at`；7 条 CHECK（墓碑全空/确认三元组/sha 长度）。
- `interview_minutes`：`draft_id` 唯一无 FK；`redaction_hits` 只存计数不存名字。

### 3.7 guidance（预调研结构化事实）

- `project_guidance_analyses`：版本化（version_number 项目内唯一+乐观锁）；analysis_state 6 态；**11 个 JSON 列表字段承载五分类条目**（{text,classification,source_refs,confirmed}）；source 锚= source_file_id/version_id+`source_sha256`（文档级）；确认闸消费 `guidance.redaction_review` 事件聚合。

### 3.8 结项交付包（handover/，T-B1）

- `handover_packages`：draft→sealed→delivered；封包三元组+`manifest_sha256`；拆封计数审计；delivered admin-only 不可逆。`handover_package_items`：v1 仅 artifact 类型、artifact_id 无 FK 指针+冻结快照。

## 4. 事件与异步底座

- **operation_events**：`record_event` 22 种 target_type 闭集（projects/events.py:74-98：project/member/module/task/gate/quote/payment/contract/file/file_version/research_form/research_subject/delivery_package/dispatch_offer/workflow_definition/workflow_run/ontology_term/ontology_relation_type/ontology_change_set/industry_template_version/module_catalog/user）；敏感键脱敏+环路防护。
- **outbox_events**：pending→dispatched→completed/failed；(status,available_at) 扫描；与 background_jobs 终态同事务收口（T-J1）。
- **background_jobs**：6 态+租约（locked_until/by/token 守卫）；`active_key` 生成列唯一（单活）；12 个 job_type（file.scan/file.preview/file.upload.cleanup/document.generate/project.presurvey.analyze/research.export/automation.execute/ai.chat/ai.execute/dispatch.maintenance/translator.translate/workflow.run）；RECOVERABLE 集合缺 automation.execute 与 dispatch.maintenance（外副作用/扫描型）。
- **automation_approvals**：UNIQUE(run_id,request_key)（workflow 腿 run_id NULL→SQL 不去重，代码层 wfnode 键去重）；risk_level CHECK 3..4。

## 5. API 面（323 路由 × 94 catalog）

- catalog＝AI 经 api_execute 的白名单（五元组含 effect read/write_db/external 与 risk 0–4；WB-DEF-10：export_sow/documents.generate=external+confirmation）；治理面有意不进。
- 关键既有路由锚（V3.1 复用面）：workflows 9 条（routes.py:38-166，平台模板列表 admin-only）；ontology 12 条（terms/impact/relation-types/change-sets）；transcripts 7 条；guidance 9 条；evidence 3 条（含 execution-facts 三源时间线）；handover 8 条；admin jobs/dispatch 各 1。
- V3.1 目标语义对照结论（详 gap-register）：`POST …/workflows/{id}/validate`、模板列表非 admin 面、`discovery/*`、`delivery-plans/*`、`test-plans/*`、`agents/runs/{id}/authorize-execution` 等**均不存在**；cancel/resume（workflow、jobs）已存在。
