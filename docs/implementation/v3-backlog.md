# V3 实施任务台账（backlog）

> 状态：全部 **PROPOSED**（基于 VERIFIED 审计设计）。任务 ID 与差距矩阵/风险登记册互引。
> 复杂度：S（≤1 天）/ M（数天）/ L（≥1 周）。均按既有 goal-d 循环节奏逐个交付，不并行开双实施线。
> 通用约定：所有服务端改动 → `docker compose build && up -d` → `alembic upgrade head`（README 纪律）；桌面改动 → 重打包 + asar 字节验证；CI 4 job 全绿才合并。

## P0（基线与数据治理）

### T-P0-1 修复 signoff 死锁（WB-DEF-1，域 10）— **DONE（2026-11-02，分支 fix/v3-t-p0-1-signoff-deadlock，squash 合并至 fork/main）**
- 目标：agent_assisted 方案无论 handoff 与否，export-sow 前必有可拍的 pending signoff。
- 前置：无。
- 修改文件：`server/src/fde_api/agents/service.py`（_finalize 成功路径：run completed 且 solution_id 存在且无 pending signoff → 建 checkpoint）；`server/src/fde_api/solutions/service.py`（export_sow 409 分支返回体增加 `remedy: "handoff_or_finalize"` 提示，可选兜底建 checkpoint）。
- DB：无。API：无新增。
- 测试：`server/tests/test_solution_signoff.py` 新增端到端用例（generate-agent completed→export 409→signoff 可拍→export 200）。
- 步骤：①复现用例先红 ②_finalize 补建 ③回归全量 pytest。
- 验收：死锁场景全链绿；既有 signoff 用例不回归。
- 回滚：revert 单 commit。
- 风险：completed 时建 checkpoint 需幂等（唯一 pending 查重）。
- 依赖：无。复杂度：**S**。
- **实施记录（与上文设计的偏差，按主报告纪律回写）**：
  - 开闸逻辑收敛为新模块 `server/src/fde_api/agents/signoff.py::ensure_pending_signoff`（上文未列该文件）：`_finalize` / `handoff_run` / `export_sow` 兜底三处共用同一幂等入口（同方案至多一个 pending；只补空 run 软链、不覆写）。
  - `_finalize` 开闸条件 = `solution_id and run.status == "completed" and not l1_path`：**L1（降级 completed）明确排除**，维持「人工接管 handoff 后再开闸」既有语义（上文「成功路径」的精确化）；失败 / T2 门拦截（run.status=failed）仍走 handoff。
  - export_sow 的「可选兜底建 checkpoint」**已实施**：闸拆为独立事务，兜底开闸先提交再抛 409（否则随事务回滚）；同时覆盖「包声明 agent_assisted 而方案无 run」这一审计未单列的死锁形态（无 handoff 可走）。驳回后再导出会重开新一轮 pending（不复用 rejected 行）。
  - 409 返回体 `details.remedy` 取值 `resolve_pending_signoff`（**非上文建议的** `handoff_or_finalize`——兜底开闸后正确指路是「去终审台拍板」），并携 `signoff_checkpoint_id / signoff_status / remedy_path`。
  - 错误体通道：`DocumentDraftServiceError`（= `SolutionServiceError`）新增可选 `detail`，solutions 蓝图错误处理器透传为 `error.details`（三参调用零改动）。
  - 测试：`test_solution_signoff.py` +5（端到端 / 无 run 兜底 / 驳回重开 / L1 零回归 / 入口幂等）；先对旧代码实跑红（completed 后 checkpoint 数 0、409 无 details）后转绿；全量 pytest 口径见 CHANGELOG。

### T-E1 一等证据表 project_evidence（域 3，先于本体）— **DONE（2026-11-02，与 T-E2 同 PR）**
- 目标：一次采集、多处引用、不可变、可审计的证据实体。
- 前置：无。修改文件：NEW `server/src/fde_api/evidence/{__init__,models,service,routes}.py`；注册 blueprint 于 `app.py`。
- DB：新表 project_evidence（设计见 ontology-registry-v1.md §2.1；迁移含 downgrade）。
- API：POST/GET /api/v1/projects/{id}/evidence（契约见该文档 §4）。
- 测试：NEW `server/tests/test_evidence_registry.py`。
- 步骤：模型+迁移 → service（sha256 幂等 upsert）→ 路由 → 测试。
- 验收：同指纹重复提交幂等；跨项目 404；不入 api_catalog（AI 不可写）。
- 回滚：alembic downgrade（新表零外键依赖，安全）。
- 风险：低。依赖：无。复杂度：**M**。
- **实施记录（与设计的偏差）**：
  - 表/迁移按 §2.1 原样落地（迁移 `e1f3a5c7b9d2`，含 downgrade；额外 CHECK sha256 长度=64）；`created_by_user_id` FK SET NULL。
  - POST 以 `created` 区分 **201 / 200**（设计只写了响应体）；命中同指纹**不改写**任何列（证据不可变，设计隐含、此处明文并用例钉住）；`captured_from` 缺省 `human`，通道前缀 bridge_sync:/agent_run:/job:/workflow_node: 校验。
  - `referenced_by` **目前只支持 `gate:G1–G9`**（T-E2 是唯一引用方；其它取值 400），不实现设计里的多态指针。
  - 新增事件 `evidence_registered`（挂 project 目标；幂等命中不记）。
  - `upsert_evidence` 保存点内插入，撞唯一约束回退重读（并发安全）；`gate_service` 对 `evidence.service` **延迟导入**（evidence.service 依赖 projects.events/permissions，模块级互导成环）。
  - 配套登记：`migrations/env.py` 模型导入清单、`conftest` 清理序、`test_migrations.HEAD_REVISION`、`scripts/audit/extract_workbench_inventory.py` blueprint/模型清单——**四处缺一都会假红**（`alembic check` / 模型⇔schema 对账 / 清理 FK / 抽取口径）。

### T-E2 门禁证据挂接 evidence_id（WB-DEF-8 部分）— **DONE（2026-11-02，与 T-E1 同 PR）**
- 目标：gates.evidence_checklist 项可携带 evidence_id；旧数据无感。
- 前置：T-E1。修改文件：`projects/gate_service.py`（submit 时 upsert evidence 并写入 evidence_id；序列化合并输出）。
- DB：gates 表加列 checklist 项内键（JSON 内字段，无 DDL）——实际零迁移。
- 测试：test_gates_api.py 扩展（提交→evidence 行存在→清单项挂接→二次提交同指纹幂等）。
- 验收/回滚/风险：如 T-E1。复杂度：**S**。
- **实施记录**：`submit_gate_evidence` 每项 `upsert_evidence(kind=gate, origin=gate:Gx/<label>, captured_from=human)` 后清单项挂 `evidence_id`，事件 items 携 evidence_id；`_serialize_gate` 读时合并（历史清单项 null）；零 DDL。同指纹二次提交 id 不变、行数不增（用例钉住）。`gates_read` AI 只读摘要**未**暴露 evidence_id（契约不动）。

### T-E3 bridge/任务证据统一入口
- 目标：ProjectTask.evidence_uri、bridge 投影可选写 evidence 行（captured_from 标来源）。
- 前置：T-E1。修改文件：`projects/task_service.py`、`bridge/sync.py`。
- 测试：test_file_previews/test_bridge_sync_flags 扩展。复杂度：**S**。

### T-O1 术语表 ontology_terms(+aliases) + 迁移（域 2）
- 目标：项目内术语/别名治理；根治导入同名重复（附录 D ⑨）。
- 前置：T-E1（change_sets 引用证据可选）。修改文件：NEW `server/src/fde_api/ontology/{__init__,models}.py`。
- DB：ontology_terms、ontology_term_aliases（ontology-registry-v1.md §2.2）。
- 测试：NEW `server/tests/test_ontology_registry.py`（术语部分：唯一约束/confirmed 不可变/合并保留来源）。
- 验收：§5 用例 1-4。回滚：downgrade。风险：低。复杂度：**M**。

### T-O2 关系/对象类型注册 ontology_relation_types + 接入
- 目标：subject_type 与 link_type 可注册（不动存量 CheckConstraint，服务层 ∪ 语义）。
- 前置：T-O1。修改文件：ontology/models.py；`research/subject_service.py`（_validate_link 659-670 改读注册表端点约束；白名单变 ∪）；`research/models.py` 仅加注释不改约束。
- DB：ontology_relation_types。测试：test_ontology_registry.py（注册类型/retired 禁新边/存量边可读）+ test_research_subjects_api 回归。
- 风险：∪ 语义不得放开内置两类的方向校验。复杂度：**M**。

### T-O3 变更集 ontology_change_sets（候选→人工确认闭环）
- 目标：批量变更事务单元+diff 评审+base 指纹并发防护；AI 候选唯一入口。
- 前置：T-O1。修改文件：ontology/service.py（propose/confirm/reject 事务）、routes.py。
- DB：ontology_change_sets。测试：change-set 状态机/base_conflict 409/AI 候选 confirm 前不物化。
- 风险：confirm 事务跨表物化需逐项补偿日志（失败回滚+事件记 partial）。复杂度：**M**。

### T-O4 导入别名去重接入
- 目标：research 导入遇同名不同 key → 产出合并候选 change_set 而非静默新建（imports.py:1261-1262 合成键路径）。
- 前置：T-O1/T-O3。修改文件：`research/imports.py`。测试：test_research_imports 扩展。复杂度：**S**。

## P1（可控自动化）

### T-W1 workflow 定义+版本表+DAG 校验器（域 5）
- 目标：definitions/definition_versions 两表；validate_dag 纯函数（环检测/白名单 ref/占位符/schema），先入 CI 无需执行器。
- 前置：无（校验器纯函数）。修改文件：NEW `server/src/fde_api/workflows/{__init__,models,definition_service}.py`。
- DB：两表。测试：NEW test_workflow_definition.py（§6 用例 1-3,5,7 的定义侧）。
- 验收：环/未知引用/非白名单 call.ref 一律 422 带明细。复杂度：**M**。

### T-W2 runs/node_runs 表+迁移
- 前置：T-W1。DB：workflow_runs、workflow_node_runs。复杂度：**S**。

### T-W3 executor：call+skill 节点
- 目标：`workflow.run` handler 注册进 jobs/handlers.py；call=api_execute 同闸、skill=published 固定版本；节点独立事务；ready 调度循环。
- 前置：T-W1/T-W2/T-S1（skill published 语义）。修改文件：NEW workflows/executor.py；EXTEND jobs/handlers.py、jobs/reconcile.py（RECOVERABLE 增 workflow.run）。
- 测试：test_workflow_executor.py（§6 用例 4-8,11）。复杂度：**M**。

### T-W4 executor：agent+human_approval 节点
- 前置：T-W3。审批复用 automation_approvals。测试：§6 用例 9-10。复杂度：**M**。

### T-W5 cancel/resume + reconcile 收敛
- 前置：T-W3。API：POST …/workflow-runs/{rid}/cancel。测试：§6 用例 8。复杂度：**M**。

### T-R1 agent_tool_groups（域 7）
- 目标：只读工具组目录（种子文件 `server/seeds/tool_groups.json`），allowed_tools 支持 group: 引用，resolve=交集。
- 修改文件：`agents/models.py`（或纯种子无表——**采用种子文件方案，零新表**）、`agents/tools.py`。测试：test_agents_fallback_chain 扩展（组不放宽/组引用未知工具拒绝）。
- 风险：低。复杂度：**S**。

### T-R2 工具目录结构化 effect/risk（域 9，含 WB-DEF-10）
- 修改文件：`control/mcp_gateway.py`（TOOLS 元组扩 effect/risk）、`control/api_catalog.py`（ENTRY 扩字段；export_sow/documents.generate 标 confirmation）。测试：test_ai_tool_loop/test_control_plane_api 扩展（目录扫描断言/写类确认流）。复杂度：**S**。

### T-S1 Skill 治理态扩展（域 8）
- 目标：status draft/in_review/published/deprecated；publish 四条闸；_skills 只回 published。
- 修改文件：`control/models.py`、`extensions_service.py`、`builtin_skills.py`、`mcp_gateway.py`。DB：skill_definitions 加 published_by/at（+status 枚举扩展需迁移）；skill_versions 加 input_schema/output_schema/test_report_json/reviewed_by。
- API：submit-review/publish/rollback/versions（agent-policy-v1 §2.4）。测试：NEW test_skill_lifecycle.py（§2.5 七用例）。
- 回滚：downgrade+revert。风险：存量 14 个 builtin 种子状态迁移（seed 直接 published）。复杂度：**M**。

### T-S2 Skill 回滚+效果统计
- 前置：T-S1。复杂度：**S**。

### T-J1 outbox 状态闭环（WB-DEF-9）
- 修改文件：`jobs/outbox.py`（mark_completed/mark_failed）、`jobs/worker.py`（settle 时回写）。测试：test_outbox 扩展。复杂度：**S**。

### T-J2 handler 自动重试 + job 取消 API（域 14）
- 修改文件：`jobs/worker.py`（指数退避≤max_attempts）、NEW admin 路由（POST /api/v1/admin/jobs/{id}/cancel，admin）。测试：test_worker/test_job_reconcile 扩展。复杂度：**M**。

### T-P1-4 resolve_signoff 双闸（WB-DEF-2）
- 修改文件：`solutions/service.py`（can_manage+档位）。测试：负向用例（viewer+高 AI 档→403）。复杂度：**S**。

### T-P1-5 审批过期清扫（WB-DEF-3）
- 修改文件：`control/scheduler.py`。测试：test_scheduling 扩展。复杂度：**S**。

### T-OBS1 降级 chat 落审计（WB-DEF-4）
- 修改文件：`ai/ai_server_client.py`、`control/ai_tool_loop.py`（request_id 前缀 direct-chat-*，成功/失败均 record）。测试：test_ai_server_direct_fallback 扩展。复杂度：**S**。

## P2（交付编译与质量闭环）

### T-G1 任务/workflow 产物→门禁证据候选（域 4，WB-DEF-8）
- 前置：T-E1/E2。修改文件：task_service、gate_service（attach_task_evidence_candidate；claim_status=None）；桌面 GateBoard 呈现候选与"采纳"按钮（走既有 evidence 提交闸）。
- 测试：候选出现/人工采纳/decide 闸不回归。复杂度：**M**。

### T-G2 template_hash 漂移呈现（WB-DEF-5）
- 修改文件：gate_service._serialize_gate（比对存储值 vs 当前 gates.json sha256，响应加 template_outdated: bool）。测试：test_gates_api。复杂度：**S**。

### T-D1 文档血缘补洞（WB-DEF-6/7）
- 修改文件：`documents/snapshots.py`（confirmed_research_values 加 revision_id 键）、`documents/ai_content.py`+`generator.py`（request_id 落 generation job 行并回写版本）、快照含 gates 摘要。
- 测试：test_document_snapshots 扩展（可反查 revision 与 ai_call_audits）。复杂度：**M**。

### T-C1 Delivery Compiler 最小闭环（P2 尾）
- 目标：change_set confirmed 后的"编译预览"：从 confirmed 本体+模板生成方案草稿骨架（复用 solutions /skeleton 路径）与 workflow 定义草稿（dag_json 模板化）。
- 前置：T-O3、T-W1。修改文件：NEW `server/src/fde_api/workflows/compiler.py`（纯函数：本体→dag 模板）。测试：compiler 快照测试。复杂度：**M**。

### T-I1 本体变更影响分析（域 2 §5 用例 6 扩展）
- 目标：impact_of_term(term_id) → 引用它的 subjects/links/forms/gates 证据列表。前置：T-O1。复杂度：**S**。

### T-UI1 桌面控制台三页（域 16）
- WorkflowConsole / GlossaryPage / SkillVersionsPage + vitest 用例。前置：对应 API。复杂度：**M**。

## P3（高级自主化——本轮仅立项不排期）

- 多 Agent 自适应编排（域 6 DEFER 观测项）；基于运行反馈的 Skill 改进（usage 统计→建议）；业务规则推理（ontology_rules 立项评估）；有限自动执行开放评估（依赖 P0-P2 验收全绿）。

## 依赖图（摘要）

```
T-E1 ── T-E2 ── T-G1 ──(gate 候选闭环)
 │     └ T-E3
 └ T-O1 ── T-O2
    │  └ T-O3 ── T-O4 ──(导入去重)
    └────── T-C1 ──(Delivery Compiler)
 T-W1 ── T-W2 ── T-W3 ── T-W4
              │      └ T-W5
              └ T-S1(published) ── T-S2
 T-P0-1 / T-P1-4 / T-P1-5 / T-OBS1 / T-J1 / T-J2 / T-R1 / T-R2：独立可并行（但仍串行交付）
 T-D1 / T-G2：独立
 T-UI1：依赖各 API 落地
```
