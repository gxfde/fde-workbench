# 附录 F（原始证据）：Workbench 门禁 G1–G9 / 方案与文档版本化 / 数据血缘 / 后台任务 审计

> 生成方式：独立审计子代理对 `D:\test\fde-workbench`（分支 fde-v2 @ 0570384）只读审计。以下为子代理报告原文。审计日期：2026-11-02。

## 1. 实际读取文件清单

| 模块 | 文件 | 行数 |
|---|---|---|
| 门禁 | server/src/fde_api/projects/gate_service.py | 680（全读） |
| | server/src/fde_api/projects/routes.py | 787（全读） |
| | server/src/fde_api/projects/events.py | 215（全读） |
| | server/src/fde_api/projects/permissions.py | 41（全读） |
| | server/src/fde_api/workbench/models.py | 938（235–617、875–938 精读） |
| | server/seeds/gates.json | 239（全读） |
| 方案 | solutions/models.py / routes.py / service.py | 75 / 112 / 960（全读） |
| | agents/models.py | 245（60–245） |
| | agents/service.py | 1197（385–483、745–794、870–923） |
| | meetings/service.py | 1365（1236–1350） |
| 文档 | documents/models.py | 428（全读） |
| | draft_service.py 1165（401–528）/ generator.py 1081 / snapshots.py 302 / version_service.py 1172 / ai_content.py 118 / project_routes.py 412 | |
| | ai/auditing.py | 109（全读） |
| 后台 | jobs/{models,queue,outbox,worker,reconcile,handlers}.py | 101/73/91/193/204/110（全读） |
| | cli.py | 316（120–316） |
| | control/models.py 390 / control/scheduler.py 118 / control/automation_jobs.py 163（全读）/ control/service.py 996（595–843）/ control/mcp_gateway.py 288（30–89）/ control/api_catalog.py 126 | |
| | bridge/sync.py | 318（85–135） |
| 迁移 | f7a2c9e4b1d3 27 / d2f6b4c8a1e9 244 / f3c8d2b7a1e5 91 / c5e9b3d7a1f5 78（全读） | |
| 测试 | 14 个指定文件读全部 test 函数名；test_gates_api.py(195) 全读；test_solution_signoff 228–311、test_solution_validation 149–210、test_document_snapshots 159–205 断言精读 | |
| 桌面 | desktop/src/renderer/src/projects/GateBoard.tsx 492（107–210）/ solutions/SignoffConsole.tsx 155 / api/client.ts 208 | |

## 2. 逐条结论

### 门禁

**Q1. G1–G9 定义与存储 — VERIFIED**
- 定义唯一来源 `server/seeds/gates.json`（烘进镜像，非 DB 表）：G1 线索资格门(S1) / G2 真需求门(S2) / G3 诊断开工门(S3) / G4 试点签约门(S4) / G5 建档门(S5) / G6 发现门(S6) / G7 设计门(S7) / G8 试点毕业门(S8) / G9 上线门(S10)。每条含 `gate_name`、`node_key`、`exit_condition`、`evidence_checklist[]`、`signer_role`、`decision_semantics`、`fail_exit`、`source_uri`、`source_sha256`（映射表 v1.3 行级出处）。
- 存储表 `gates`，模型 `Gate`（workbench/models.py:560-617）：`status` CHECK IN `('pending','evidence','passed','conditional_pass','failed')`；`decision` CHECK IN `('proceed','pivot','stop')` 或 NULL；`evidence_checklist` JSON 数组，每项 `{label, claim_status: None|'claimed'|'accepted', source_uri, content_hash}`；`evidence_uri`/`evidence_hash`（首项镜像）；`template_hash`；`submitted_at`/`decided_at`；`submitted_by_user_id`/`decided_by_user_id`（FK users SET NULL）；`is_delivery_party` bool；`UniqueConstraint(project_id, gate_key)`。
- 审批无独立表：拍板事实 = decided_by_user_id + decided_at + status + decision 四列合写；留痕走 `operation_events`（event_type ∈ gates_instantiated / gate_evidence_submitted / gate_decided）。

**Q2. 状态流转统一控制 — VERIFIED**
全部 `Gate.status` 赋值只存在于 `gate_service.py`：
- `ensure_project_gates` L91-123：首访懒实例化 9 行 pending（先 SELECT…FOR UPDATE 项目行防并发双份）。
- `submit_gate_evidence` L222-310：pending/failed/evidence → evidence；passed/conditional_pass 拒 409 gate_already_decided；校验 content_hash 64hex、source_uri ≤500。
- `decide_gate` L313-518：仅 evidence → 终态；硬闸序：拍板人≠执行人（403 gate_decider_conflict L352-360）→ 交付方 G8/G9 须 admin（403 gate_decider_role_required L363-372）→ conditional_pass 仅 G9（L384-389）→ G8 pass 必带 decision（L390-409）→ accepted_labels ⊆ claimed（L431-438）→ 全部 accepted 才 passed（L443-453）。
绕过路径排查（grep 全仓 `gate.status =` / `Gate(`）：
- projects/routes.py:93-110 UPDATE_FIELDS 不含门禁字段；workbench/seed.py 无 Gate 写入；bridge/sync.py:92-128 只写 BridgeEngagement/BridgeSyncRun。
- AI 工具：mcp_gateway.py:42,166-169 `gates_read` → summarize_project_gates（只读，刻意剥离 source_uri/hash）；api_catalog.py 无任何 gates 条目（grep 零命中），api_execute 无法触达。
- 只读消费方：payment_service.py:290-293、guidance/service.py:410-411、dispatch/profiles.py:55-58 仅 SELECT。
结论：**不存在绕过 gate_service 的写路径**。

**Q3. 门禁与其他实体关联 — VERIFIED（关联普遍为弱关联，无 FK）**
- Gate ↔ Project：FK project_id CASCADE（唯一硬 FK）。
- Gate ↔ ProjectTask：**无 FK**。`ProjectTask.gate String(10)` + `evidence_uri/evidence_hash`（models.py:447-452），task_service.py:742-747 仅正则校验格式，任务证据不回填门禁清单。
- Gate ↔ SopNode：经模板 node_key 软关联（`_sop_nodes_for_templates` L546-562）。
- Gate ↔ documents / solutions / signoff / T6：**全部无关联**。signoff 是 solution_review_checkpoints（FK project_solutions.id）；T6 是 agents/service.py:759-784 start_run 前置闸（查 review_meetings + review_meeting_minutes 的 t6_gate_satisfied + projects.t6_review_disabled），与 gates 表零交集。
- Gate → Payment 单向副作用：G8 pass 时调 mark_acceptance_passed（payment_service.py:311）、decision=stop 时 flag_g8_stop_settlement（L348）。
- Gate ↔ 派单：is_delivery_party 由 ProjectMember.role=='member' 现算（L267-273），非 FK。

**Q4. 自动化结果能否转门禁证据 — VERIFIED（不能；门禁无自动检查记录）**
- 不存在任何代码把 agent run / background job / bridge 采集结果写入 gates.evidence_checklist。submit_gate_evidence 唯一入口是 HTTP 路由（actor=g.current_user 必为真人会话）。因此自动化结果**既不会自动批准，也不会自动提交**。
- "自动检查 vs 人工批准"分离：门禁层只有执行人 vs 拍板人两个**人类**角色分记；无"机器检查"列。真正的自动/人工分离在方案层：AgentArtifact.reviewed 默认 False，C-1 校验自动写失败原因，只有 resolve_signoff approved 才翻 True（solutions/service.py:364-377）。

**Q5. gate_template_hash / dispatch_p0_gate_separation — VERIFIED**
- f7a2c9e4b1d3：加 gates.template_hash String(64)，回填硬编码 `f52afe88…`。运行时 `_gates_file_hash()`（L83-88）取 seeds/gates.json 文件 sha256，实例化时冻结（L120）。**实测当前文件 sha256 = `180c4809…`**（gates.json 在 eb009e1/9570a2a/ff90614 三次变更），与回填值不同 → 存量项目与新项目 template_hash 不一致。`_serialize_gate` L650 原样回传，**无任何代码比对存储值与当前值**。
- d2f6b4c8a1e9：加 submitted_by_user_id / decided_by_user_id（FK users SET NULL）+ is_delivery_party；同时建 delivery_packages、dispatch_offers。"分离" = P0-5 执行人/拍板人分离，由 decide_gate L352-372 代码强制。

### 方案与文档

**Q6. 生成与版本化 — VERIFIED**
- 方案 project_solutions（solutions/models.py:12-52）：**就地可变**，update_solution L432-433 setattr 直接覆盖字段，version += 1（L437）；无方案版本表，历史仅靠 operation_events。generated_by IN ('human','agent') + agent_run_id FK agent_runs。生成方式：POST /solutions（同步纯人工）、/ai-organize（同步 DeepSeek complete_json，L489-503，只返建议 saved=False）、/skeleton（同步模板搬运无 AI）、/<id>/generate-agent（委托 agents.start_run 沙箱 run，completed 才接线 L202-220）。
- 文档四表：project_documents（身份）/ project_document_versions（不可变链）/ project_document_drafts（可变编辑态）/ document_generation_jobs。export_sow（L631-731）与 request_document_generation（draft_service.py:401-528）同构：建 ProjectDocumentVersion(source='generated', status='draft', sha256='') + DocumentGenerationJob(queued) + enqueue_outbox('document.generate')，**渲染在 worker 异步**（generator.py:204-293）。AI 字段仅 pov_plan/sow 且无已存方案时调 DeepSeek（ai_content.py:29）。
- 版本字段：version_number 按文档唯一、parent_version_id 链、source ∈ generated/online_revised/manual_upload、status ∈ draft/confirmed/archived。

**Q7. 输入快照与血缘 — PARTIALLY VERIFIED**
- build_document_snapshot（snapshots.py:51-75）冻结 project/enterprise/guidance/research（仅 confirmed revision）/subjects/tasks/members/captured_at → source_snapshot_json。test_document_snapshots.py:159,179 验证"按 subject id 不按名"与"tasks/members/research 入快照"。
- content_snapshot_json 含 field_overrides、ai_fields（首代冻结，generator.py:830-837）、solution（serialize_solution 冻结）、sow_format_version=2、agent_trace{agent_run_id, degraded, fallback_level, artifacts[kind,sha256]}（L711）。
- 可追踪：调研答案值（但 confirmed_research_values L78-117 **不存 revision_id**）；agent run（经 agent_trace + ProjectSolution.agent_run_id）。
- **不可追踪**：门禁证据文件（不入快照）；knowledge_snapshots（仅 AutomationTaskRun.knowledge_snapshot_id 引用，文档不引用）；ai_call_audits（ai_content.py:98 request_id=f"document-content-{uuid4()}" 不落版本行，无法从版本 join 回模型调用）。

**Q8. 不可变性 — VERIFIED**
- ProjectDocumentVersion 内容字段写后冻结：generator.py:837 首次生成时写 content_snapshot_json，再生成走 frozen_ai_fields（L809-812）；_is_already_generated（L740-741）sha256 非空或状态终态即短路（test_handle_document_generation_is_idempotent）。状态列可变：confirm（version_service.py:378-380）、前一 confirmed 归档（L376）、archive（L461）。
- 重试：_retry_failed_export（solutions/service.py:744-754）仅 sha256=='' 且无活跃 job 时**重排同一版本**，不建新版、不覆盖成功内容。_ensure_docx_file_version（generator.py:985-995）命中已有 docx_file_version_id 时覆写占位文件字节（L1036-1048），但只发生在 sha256 为空的占位态。
- 重新生成 = 新 version_number（request_document_generation / online_revise），历史版本永不覆写。可变对象：ProjectDocumentDraft、DocumentGenerationJob.status（_mark_job L1051-1065）、ProjectSolution。

**Q9. signoff 流程 — VERIFIED（含死锁风险）**
- 表 solution_review_checkpoints（agents/models.py:212-245）：checkpoint_type IN (template,rule,knowledge,signoff)、status IN (pending,approved,rejected)、required_level、reviewer_user_id、evidence_ref、handoff_run_id（c5e9b3d7a1f5 加列）。
- **创建唯一路径**：agents/service.py:907-916 handoff_run（run 失败/L1 且携 solution_id）建 pending, required_level='project_manager'。全仓 `SolutionReviewCheckpoint(` 仅此一处实例化。
- 拍板：POST /solutions/<id>/signoff → resolve_signoff（solutions/service.py:319-400）：无 pending 409 signoff_not_pending；权限闸 = effective_ai_access(actor) 档 ≥ required_level（**AI 访问档，非项目角色**；项目侧仅 can_view）；approved 翻 AgentArtifact.reviewed；事件 solution_signoff_resolved 带 attempt。状态机 pending → approved | rejected，终态。
- 与 export-sow：L644-659 若存在 DeliveryPackage(solution_id=…, agent_assisted=True) 则要求 approved checkpoint，否则 409 solution_signoff_required；闸在复用路径之前。不进 api_catalog（L117 注释 + test_signoff_never_in_catalog）。

### 后台任务

**Q10. jobs 模块 — VERIFIED**
- outbox_events（jobs/models.py:37-63）：topic / aggregate_id / payload_json / status(pending,dispatched,completed,failed) / attempts / available_at / last_error。**代码只写 pending→dispatched**（outbox.py:77-81），completed/failed 无写入点。
- background_jobs（L66-101）：job_type / target_id / status(pending,queued,running,succeeded,failed) / attempts / max_attempts=5 / available_at / locked_until / locked_by / active_key。**幂等键** = 生成列 active_key = CASE WHEN status IN (pending,queued,running) THEN job_type||':'||target_id END + UNIQUE → 同目标同时只有一个活跃 job；ensure_background_job（queue.py:51-73）复用或新建。
- 队列：Redis list `fde-jobs`（queue.py:17-48）rpush/lpop，非 RQ。
- Worker：cli.py:145-182 自研循环：心跳 → dispatch_pending → 定期 _reconcile_jobs → dequeue → run_job。run_job（worker.py:56-90）：_claim 短事务（running、attempts++、租约 5min、token）→ 续租线程每 60s（L162-193）→ handler → _settle 按 token 守卫（L131-159）。
- 重试：handler 抛异常直接 failed（L76-83），**无自动重试**；仅 reconcile 对"worker 死亡"重排。取消：background_jobs 无取消 API。
- Reconcile（reconcile.py:110-181）：running 且租约过期 / pending,queued 超 300s → 类型在 RECOVERABLE_JOB_TYPES 且 attempts<max 则重排，否则 failed + worker_lost:<reason> + 业务行收尾钩子；automation.execute 刻意不可恢复。
- Scheduler：**非 APScheduler**。cli.py:210-245 `flask scheduler` 自研轮询（5–300s），调 dispatch_due_automations（control/scheduler.py:62-94）+ 每日 dispatch.maintenance；control/scheduler.py:97 自写 cron 解析。
- 节点级依赖：**无**。无 DAG，仅 outbox 串链（document.generate 成功后 enqueue_outbox('file.preview')，generator.py:268-272）。

**Q11. automation 三表 — VERIFIED**
- 存在：control/models.py:72-107 automation_tasks、L128-158 automation_task_runs、L161-195 automation_approvals，建于 ebb003a5c3a8_baseline_pg。
- 写入：dispatch_due_automations（scheduler.py:80-88）按 idempotency_key=schedule:<task>:<ts> 建 run + enqueue_outbox('automation.execute')；执行 execute_automation_run（automation_jobs.py:19-121）→ 权限实时复核 → build_project_snapshot 写 knowledge_snapshot_id → dsh_runtime.execute。
- 审批绑定：control/service.py:628-645 由 DSH 工具调用触发建 AutomationApproval(run_id FK, project_id FK, request_key, capability, tool_name, arguments_json, arguments_sha256, risk_level 3–4, expires 15min)，run → waiting_approval；decide_automation_approval（L683-754）人工+密码 → approved(run running)/rejected(run cancelled)；execute_approved_dsh_tool（L781-843）校 sha256 完整性 + 再鉴权 + **白名单仅 task.batch_assign/project_tasks.batch_assign** → executed。审批目标是工具调用，与门禁/文档无关。

## 3. 关键调用链

1. **门禁证据提交**：POST /api/v1/projects/<pid>/gates/<G>/evidence（routes.py:203）→ submit_gate_evidence（gate_service.py:222）→ _load_project_for_gates(manage=True) → _load_gate FOR UPDATE → 写 gates.evidence_checklist/status='evidence'/submitted_by_user_id/is_delivery_party → record_event('gate_evidence_submitted') → operation_events。
2. **门禁拍板**：POST .../gates/<G>/decision（routes.py:222）→ decide_gate（L313）→ 五道校验 → 写 gates.status/decision/decided_by_user_id/decided_at → [G8 pass] mark_acceptance_passed → payments/delivery_settlements；[stop] flag_g8_stop_settlement → record_event('gate_decided')。
3. **门禁懒实例化**：GET .../gates → list_project_gates（L139）→ ensure_project_gates（L91，锁项目行）→ 9 × Gate(template_hash=_gates_file_hash()) → record_event('gates_instantiated')。
4. **SOW 导出 → 文档版本**：POST .../solutions/<sid>/export-sow → export_sow（service.py:631）→ [agent_assisted] signoff 闸 → ProjectDocument upsert → build_document_snapshot → _create_placeholder_docx → ProjectDocumentVersion + DocumentGenerationJob + enqueue_outbox('document.generate') → ProjectSolutionExport → record_event。
5. **文档生成 worker**：flask worker（cli.py:145）→ dispatch_pending（outbox.py:50）→ ensure_background_job → Redis → run_job（worker.py:56）→ _document_generate_handler（generator.py:303）→ handle_document_generation（L204）→ _build_context（AI 字段冻结）→ render_docx → QA → _ensure_docx_file_version → 写 version.sha256 + _mark_job('succeeded') → enqueue_outbox('file.preview')。
6. **方案终审 signoff**：POST .../solutions/<sid>/signoff → resolve_signoff（service.py:319）→ 查 pending checkpoint → effective_ai_access 档闸 → 写 checkpoints.status/reviewer_user_id/evidence_ref → [approved] UPDATE agent_artifacts SET reviewed=True WHERE linked_solution_id=… → record_event。
7. **handoff 建 checkpoint**：POST /api/v1/agents/runs/<rid>/handoff → handoff_run（agents/service.py:872）→ 写 agent_runs.handoff_user_id/fallback_level='L3' → SolutionReviewCheckpoint(signoff, pending, project_manager, handoff_run_id)。
8. **自动化审批**：DSH 工具请求 → control/service.py:628 AutomationApproval(pending) + run waiting_approval → decide_automation_approval（L683，人工+密码）→ execute_approved_dsh_tool（L781）→ batch_assign_project_tasks_in_session → executed。
9. **下载 → 交付审计**：GET .../<vid>/download-url → get_document_download_url（version_service.py:716）→ draft 拒 409 → sign_download → record_event('document_version_delivered') + _record_delivery（L640，幂等键 version:sha256:actor）→ document_delivery_records。
10. **Reconcile**：worker 定时 → reconcile_jobs（reconcile.py:110，FOR UPDATE SKIP LOCKED）→ 重排或 _fail_job → get_job_failure_handler 业务行收尾（如 fail_run_on_worker_loss 置 automation_task_runs.status='failed'）。

## 4. 相关表清单

| 表名 | 模型类 | 文件 | 关键字段 | 迁移 |
|---|---|---|---|---|
| gates | Gate | workbench/models.py:560 | status, decision, evidence_checklist(JSON), template_hash, submitted_by_user_id, decided_by_user_id, is_delivery_party | b4e8c1a7d2f6 / f7a2c9e4b1d3 / d2f6b4c8a1e9 |
| sop_nodes | SopNode | workbench/models.py:512 | node_key(UQ), gate_key, source_uri, content_hash | b4e8c1a7d2f6 |
| operation_events | OperationEvent | workbench/models.py:879 | target_type, target_id, event_type, changes(JSON) | ebb003a5c3a8 |
| ai_call_audits | AICallAudit | workbench/models.py:908 | request_id, purpose, model, tokens, status | e5b8a1c9d3f7 |
| project_solutions | ProjectSolution | solutions/models.py:12 | version, status, generated_by, agent_run_id, source_json | ebb003a5c3a8 / d9c3e7f1a5b8 |
| project_solution_exports | ProjectSolutionExport | solutions/models.py:66 | solution_id+solution_version(UQ), document_id, document_version_id | ebb003a5c3a8 |
| solution_review_checkpoints | SolutionReviewCheckpoint | agents/models.py:212 | checkpoint_type, required_level, status, reviewer_user_id, handoff_run_id | d9c3e7f1a5b8 / c5e9b3d7a1f5 |
| agent_runs / agent_artifacts | AgentRun / AgentArtifact | agents/models.py:60/124 | status, degraded, fallback_level, idempotency_key / sha256, reviewed, linked_solution_id | d9c3e7f1a5b8 |
| project_documents | ProjectDocument | documents/models.py:149 | document_type, business_code, current_version_id, status, opportunity_scope_json | ebb003a5c3a8 / b8d4f2a6c0e8 |
| project_document_versions | ProjectDocumentVersion | documents/models.py:248 | version_number(UQ), source, status, parent_version_id, source_snapshot_json, content_snapshot_json, sha256 | ebb003a5c3a8 |
| project_document_drafts | ProjectDocumentDraft | documents/models.py:220 | field_overrides_json, rich_text_json, version | ebb003a5c3a8 |
| document_generation_jobs | DocumentGenerationJob | documents/models.py:333 | document_version_id, status, attempts | ebb003a5c3a8 |
| document_delivery_records | DocumentDeliveryRecord | documents/models.py:374 | delivery_key(UQ), version_id, sha256, actor_username | f3c8d2b7a1e5 |
| outbox_events | OutboxEvent | jobs/models.py:37 | topic, aggregate_id, status, available_at | ebb003a5c3a8 |
| background_jobs | BackgroundJob | jobs/models.py:66 | job_type, target_id, status, locked_until, locked_by, active_key(计算列 UQ) | ebb003a5c3a8 |
| automation_tasks / _task_runs / _approvals | AutomationTask / AutomationTaskRun / AutomationApproval | control/models.py:72/128/161 | schedule_kind, next_run_at / idempotency_key(UQ), knowledge_snapshot_id / run_id+request_key(UQ), arguments_sha256, status | ebb003a5c3a8 |
| delivery_packages | DeliveryPackage | dispatch/models.py | solution_id, agent_assisted | d2f6b4c8a1e9 / b8c2d6f0a4e7 |

## 5. 相关路由清单

| method | path | handler | 装饰器 |
|---|---|---|---|
| GET | /api/v1/projects/{id}/gates | list_project_gates_route | @require_auth（服务层 can_view） |
| POST | …/gates/{gate_key}/evidence | submit_gate_evidence_route | @require_auth（服务层 can_manage） |
| POST | …/gates/{gate_key}/decision | decide_gate_route | @require_auth（can_manage + 拍板人≠执行人） |
| PATCH | /api/v1/projects/{id} | update_project_route | @require_minimum_role("project_lead")（含 t6_review_disabled） |
| POST | …/solutions/{sid}/export-sow | export_sow | @require_auth（_require_project_manager） |
| POST | …/solutions/{sid}/signoff | resolve_signoff | @require_auth（can_view + AI 访问档） |
| POST | …/solutions/{sid}/generate-agent | generate_agent_solution | @require_auth（can_manage + agents 鉴权） |
| GET | …/solutions/{sid}/review-trail | solution_review_trail | @require_auth |
| POST | …/documents/{did}/generate | request_document_generation_route | @require_auth（_require_document_editor） |
| POST | …/documents/{did}/revise | online_revise_route | @require_auth（editor） |
| POST | …/documents/{vid}/confirm | confirm_document_version_route | @require_auth（_require_project_lead） |
| POST | …/documents/{vid}/archive | archive_document_version_route | @require_auth（can_manage） |
| GET | …/documents/{vid}/download-url | document_download_url_route | @require_auth（draft 拒 409） |
| GET | …/documents/delivery-records | document_delivery_records_route | @require_minimum_role("project_lead") |
| POST | /api/v1/agents/runs/{rid}/handoff | handoff_run | @require_auth |
| MCP | gates_read | mcp_gateway.py:166 | capability project.read（只读） |

## 6. 风险与差距（均有代码证据）

1. **signoff 死锁**：SolutionReviewCheckpoint(signoff) 唯一创建点是 handoff_run（agents/service.py:907）。若 DeliveryPackage.agent_assisted=True 的方案经 generate-agent 正常 completed（无 handoff），则无 pending checkpoint → resolve_signoff 409 signoff_not_pending、export_sow 409 solution_signoff_required，SOW 永远导不出。测试 test_solution_signoff.py:35-42 _checkpoint 直接插库绕过了该路径。
2. **template_hash 漂移未呈现**：当前 gates.json sha256 `180c4809…` ≠ 迁移回填 `f52afe88…`，_serialize_gate 只回传不比对，存量项目清单与模板不一致无人感知。
3. **AI 调用血缘断链**：ai_content.py:98 request_id 随机生成不落 project_document_versions，ai_call_audits 无法反查到具体文档版本；organize_solution 同理。
4. **调研快照无 revision_id**：confirmed_research_values 只存值，审计时无法证明"生成时用的是第几次确认"。
5. **任务级证据与门禁脱钩**：ProjectTask.gate/evidence_uri/evidence_hash 仅字符串，与 gates 行无 FK、不回填清单，两套证据口径并存。
6. **证据重提覆写**：submit_gate_evidence L251-256 直接 update 清单项指针，前一次 source_uri/content_hash 只留在 operation_events.changes，gates 行无历史。
7. **outbox_events 状态不闭环**：completed/failed 两值无写入点，表只能停在 dispatched。
8. **AI 可直接触发生成**：api_catalog.py:57,61 收编 solutions.export_sow、documents.generate，而 confirmation 仅 DELETE/.archive/.deprecate → AI api_execute 可无确认排队文档生成并触发 worker 内 DeepSeek 调用；缓解项是 draft 下载闸。
9. **signoff 权限口径**：resolve_signoff 项目侧只要 can_view，决定权在 effective_ai_access 档位，与项目管理权限不一致（viewer 成员若持高 AI 档理论上可拍板）。
10. **handler 异常无重试**：worker.py:76-83 一次异常即 failed，max_attempts 只在 reconcile 生效。

## 7. 无法验证的项

- 运行时行为（未跑 pytest/docker）：租约续期、SKIP LOCKED 并发、Redis 队列实际表现均为代码推断。
- 生产库 gates.template_hash 实际分布。
- effective_ai_access 的档位推导规则（control/access.py，另见附录 C 已覆盖）。
- dsh_runtime.execute 外部运行时的幂等与副作用。
- 桌面端除 GateBoard.tsx/SignoffConsole.tsx 外的页面是否存在其他门禁/文档写调用。
- DocumentGenerationJob.status='cancelled' 的写入点（grep 未见，可能为预留值）。
