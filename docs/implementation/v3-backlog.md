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

### T-E3 bridge/任务证据统一入口 — **DONE（2026-11-03）**
- 目标：ProjectTask.evidence_uri、bridge 投影可选写 evidence 行（captured_from 标来源）。
- 前置：T-E1。修改文件：`projects/task_service.py`、`bridge/sync.py`。
- 测试：test_file_previews/test_bridge_sync_flags 扩展。复杂度：**S**。
- **实施记录（与设计的偏差，按主报告纪律回写）**：
  - **测试文件纠偏**：设计提示的 test_file_previews 与任务证据无关（文件预览域）——任务侧用例落 `test_project_tasks_api.py`（+1，建/幂等/换指纹/清空/只指针 五段），桥侧落 `test_bridge_sync_flags.py`（+1，挂接登记/未挂跳过/坏指纹跳过/重放幂等）。
  - **任务侧写入点两处**：`create_project_task`（依赖块后，同事务）与 `update_project_task`（乐观锁 rowcount 校验**之后**、record_event 之前——stale 版本零证据副作用）；统一走新私有助手 `_sync_task_evidence`：双字段齐备才登记（只挂指针不落指纹不构成指纹），kind=task、captured_from=human、origin=`task:<task_key>`、hash 归一小写；幂等沿用 upsert_evidence。**清空指针不删登记簿**（证据不可变，一等表语义优先于任务字段）。
  - **桥侧挂在投影事务内**（apply_snapshot 步骤①，advisory lock 保护下）：只对**已挂接** workbench 项目的 slug 写（openfde_engagement / fdeops_workspace 反查）；openfde 逐 slug 按 stdout_sha256、fdeops 按工作区级 registry_sha256（注册表口径=一次扫描一个指纹）；captured_from=`bridge_sync:{run_id}`、created_by=NULL（机器通道）；kind=bridge。指纹不齐整（缺 hash / uri 空·越界）**跳过不炸**——投影是 4h 关键路径，证据永远是锦上添花；DB 级故障不上吞，随投影一起落 failed run（与既有 all-or-nothing 一致）。`summary` 增 `evidence_created` 计数。
  - **契约不动**：任务 DTO 与 engagement_view 均不暴露 evidence_id（沿 T-E2 gates_read 先例）；零新事件——任务侧既有 event_changes 已含 evidence 字段变更，桥侧无 actor（OperationEvent 需真人），summary+登记簿即审计轨迹。
  - **零迁移零路由零 DDL**：evidence_uri/evidence_hash 是 ProjectTask 既有列；登记路径仍不进 api_catalog（AI 不可写证据纪律不变——桥侧是服务端内部调用不经 HTTP）。
  - mypy 花絮：新调用点引用 `project.id` 触发 `_load_project` 的 `Project|None` 标注新增 2 处 union-attr——直接改用路径参数 `project_id`（同值），不扩基线。

### T-O1 术语表 ontology_terms(+aliases) + 迁移（域 2）— **DONE（2026-11-03）**
- 目标：项目内术语/别名治理；根治导入同名重复（附录 D ⑨）。
- 前置：T-E1（change_sets 引用证据可选）。修改文件：NEW `server/src/fde_api/ontology/{__init__,models}.py`。
- DB：ontology_terms、ontology_term_aliases（ontology-registry-v1.md §2.2）。
- 测试：NEW `server/tests/test_ontology_registry.py`（术语部分：唯一约束/confirmed 不可变/合并保留来源）。
- 验收：§5 用例 1-4。回滚：downgrade。风险：低。复杂度：**M**。
- **实施记录（与设计的偏差，按主报告纪律回写）**：
  - **文件清单纠偏**：backlog 只列 models.py，但「confirmed 不可变 / 合并保留来源」两条测试验收需要生命周期逻辑 → 加 NEW `ontology/service.py`（设计 §3 本就规划 ontology/{models,service,routes} 三件）；测试落 `test_ontology_registry.py` **7 例**（生命周期+不可变 / 入参归一 / 唯一+别名占用 / 合并保留来源链 / 别名 DB 唯一 / CHECK 拒非法态 / api_catalog 钉子）+ `test_migrations.py` 迁移往返 **1 例**（head 上自引用外键落 canonical/merged 对）。
  - **零路由（T-W1 先例）**：设计 §4 术语公开面只有只读 GET；写路径一律 change_sets propose→confirm（AI 候选永不直接写表）→ 术语 REST 面（GET terms + change-set 三条）随 T-O3 routes.py 一并开；本轮 service.py 是 confirm 事务的**物化原语**（create_term 支持 `initial_status="confirmed"` 直落，T-S1 种子先例）。用例 1（confirm 前不物化）与用例 2（跨项目 403）的 HTTP 面随 T-O3 补齐——本轮验收实盖用例 3/4 + 两用例的服务层等价面（draft→confirm 两段式、查询恒按 project_id 过滤）。
  - **合并保留来源语义落定**：source→merged 指向 target；target 转写获得 source 规范名为别名（`_ensure_alias` 排除 source 自身——其名字即将让位，否则永远撞不上）；source 既有别名**不动**（别名→merged→canonical 链解析，不可变优先）；**链一跳化**：曾并入 source 的 merged 行重指 target（依赖行 version 递增），不存在 merged→merged→…链；逐项 OperationEvent `ontology_term_merged`（merged_term/canonical_term_id/canonical_term/alias_added/repointed），事件目标注册表 +`ontology_term`（projects/events.py 三处）。
  - **事件口径**：merge 必记事件（用例 4 逐项记录）；create/confirm 原语**事件静默**——T-O3 change-set confirm 事件统一「携带逐项结果」，原语再记就是双写噪声（实施偏差，回写备 T-O3 设计时裁决）。
  - **一个名字一个概念**：create_term 预检**别名占用先于同名检查**（合并后名字既存 merged 行又存别名，「已并入 X」比「已存在」更有用）；merged 行名占位是设计语义（UNIQUE(project, term) 绝对 + 不可变历史）；DB 层 CHECK 拒 merged 无指向 / 非法 term_type / 非法 status。
  - **口径**：**101→103 表**、迁移头 `a3e7c1f9b5d2`（**28 rev**）、路由 283 不变、ENTRIES 94 不变、pytest **1790 收集 = 1784 passed + 6 skipped**（+8）；**改 server + 新迁移 ⇒ rebuild 后必 `alembic upgrade head`**（api/worker/scheduler 三镜像）。花絮①：本地全量误带 `-p no:warnings` 使 SAWarning 泄入 CLI 捕获输出、`test_workbench_seed`「只打印计数」假红——canonical 调用（无该 flag）单文件复跑 10 绿，权威计数以 pre-commit 钩子全量为准。花絮②：`session.execute(update(...)).rowcount` 触发 mypy `Result[Any]` attr-defined——改 ORM 逐行重指，顺带把依赖行 version 递增补齐（语义更对）。

### T-O2 关系/对象类型注册 ontology_relation_types + 接入 — **DONE（2026-11-03）**
- 目标：subject_type 与 link_type 可注册（不动存量 CheckConstraint，服务层 ∪ 语义）。
- 前置：T-O1。修改文件：ontology/models.py；`research/subject_service.py`（_validate_link 659-670 改读注册表端点约束；白名单变 ∪）；`research/models.py` 仅加注释不改约束。
- DB：ontology_relation_types。测试：test_ontology_registry.py（注册类型/retired 禁新边/存量边可读）+ test_research_subjects_api 回归。
- 风险：∪ 语义不得放开内置两类的方向校验。复杂度：**M**。
- **实施记录（与设计的偏差，按主报告纪律回写）**：
  - **∪ 接入已生效（风险条由机制保证）**：`_validate_link` 改为「**内置优先** + 注册表」——内置两类关系类型的端点约束是存量语义，注册表**不得覆盖内置码**（注册 `opportunity_role`/`opportunity_process` 一律 409 `duplicate_code`），因此「∪ 语义不得放开内置方向校验」不靠约定靠机制；注册表类型按 `allowed_source_types`/`allowed_target_types` 判方向，方向不符仍 422 `invalid_research_subject_link`；retired 类型禁新边 409 `link_type_retired`（存量边只读，既有边行不动）；未知类型 422 且错误消息附当前可用类型清单（可行动）。内置集合与注册表保留名单的一致性由测试钉住（`SUBJECT_TYPES`/`LINK_SUBJECT_TYPES` ↔ `BUILTIN_*_CODES`，防漂移）。
  - **作用域语义落地**：设计稿 `UNIQUE(COALESCE(project_id,'全局'), kind, code)` 落为「项目内 `UNIQUE(project_id, kind, code)` + 全局**部分唯一索引**（`project_id IS NULL`）」两段（COALESCE+uuid 混型不可行）；**项目内类型遮蔽同名全局类型**（端点约束可按项目定制），全局类型对所有项目生效；解析函数 `find_relation_type`/`list_relation_types` 统一按「项目内优先、全局兜底」。
  - **subject_type 值域本轮只落登记不开放使用**（**最重要的边界**）：登记 `kind=subject_type` 的行合法、可被关系类型端点约束引用，但**新建调研对象仍只能取内置五类**——三处 DB CheckConstraint（`project_research_subjects` / `template_research_forms` / `project_research_import_batches`）按设计兼容边界冻结；放开值域会连带 `research/definitions.py`、`ai/research_form_service.py`、`documents/mapping.py`、`documents/snapshots.py`、`ai/industry_template_schema.py` 五处消费方（漏一处即静默丢数据），复杂度超出 M。**留 T-O2b 独立一轮**（值域开放 + 五处消费方对齐）。本轮 `research/models.py` 按口径**仅加注释不改约束**。
  - **文件清单纠偏**：backlog 只列 models.py，但「retired 禁新边」需要可触达的人工停用路径 ⇒ 加 NEW `ontology/routes.py`（3 条路由）+ `ontology/service.py` 扩 HTTP 面（登记/停用/列表，人工路径，**不进 api_catalog**，钉子测试在位）；事件目标注册表 +`ontology_relation_type`（全局类型 project_id 为空 ⇒ 事件挂全局面，同平台模板定义先例）。
  - **HTTP 面（§4 对齐 + 一条扩展）**：设计 §4 的 `GET/POST /projects/{id}/ontology/relation-types` 已开；另加 `POST …/relation-types/{id}/retire`——否则「retired 后建边 409」在人工路径上不可达（§5 用例 7 要求可触发）；全局登记入口设计稿未给（只说「project_id 为空、仅 admin 可建」），本轮以请求体 `scope=project|global` 承载，`global` 另需 admin。
  - **登记入口是人工路径**：类型登记/停用直接落表并记 `ontology_relation_type_registered`/`_retired` 事件（与 T-O1 的「原语事件静默」不同——本轮的 HTTP 面不是 T-O3 change-set 的物化通道，不存在双写）；AI 候选路径仍只能走 change_set（T-O3）。
  - **状态取值域**：CHECK 含 `draft`（留给 T-O3 变更集：提出的类型先落 draft，confirm 转 active），本轮登记入口直落 `active`，`retired` 为终态（重复停用 409 `invalid_transition`）。
  - **口径**：**103→104 表**、迁移头 `b8d3f1a5c7e2`（**29 rev**）、路由 **283→286**（+3）、ENTRIES 94 不变（`research.link` 描述同步：端点约束按注册类型校验）、pytest **1798 收集 = 1792 passed + 6 skipped**（T-O2 +8：注册表 7 + 迁移往返 1）、vitest 730 不变（零桌面改动）。**改 server + 新迁移 ⇒ rebuild 后必 `alembic upgrade head`**（api/worker/scheduler 三镜像）。

### T-O2b 对象类型值域开放（接 T-O2 注册表的 subject_type 一侧）— **DONE（2026-11-03，分支 feat/v3-t-o2b-subject-type-domain，squash 合并至 fork/main）**
- 目标：让 T-O2 登记的 `kind=subject_type` 真正可用于新建调研对象/表单/导入批次。
- 前置：T-O2（注册表已登记对象类型并可被关系类型端点约束引用）。
- 改动面：①三处 DB CheckConstraint 放宽（`project_research_subjects` / `template_research_forms` / `project_research_import_batches`）；②服务层白名单 `CLIENT_SUBJECT_TYPES`（subject_service）/ `_IMPORT_SUBJECT_TYPES`（imports）/ `SUBJECT_TYPES` 校验（research/definitions.py、ai/research_form_service.py）改「内置 ∪ 注册表」；③消费方对齐：`documents/mapping.py`、`documents/snapshots.py`（按 `SUBJECT_TYPES` 逐类型建快照——漏改即静默丢该类型内容）、`ai/industry_template_schema.py`（完整性校验）。
- 风险：值域放宽是**存量语义变更**（约束从枚举变格式），须评估存量数据与历史导入的兼容；文档快照漏一类即静默丢内容。
- 复杂度：**L**（超出 M，故与 T-O2 分轮）。
- **实施记录（2026-11-03）**：
  - **迁移 `b5d9e3f7a1c6`（31 rev）**：三处 subject_type CHECK 枚举→码格式 `^[a-z][a-z0-9_]{0,59}$`（对齐注册表 `_CODE_PATTERN`），三列宽 32→60（对齐 `ontology_relation_types.code`）。无数据改写——枚举值是格式的子集，存量全兼容；downgrade 收窄时超长注册码行会被枚举 CHECK 挡下（保护语义，测试钉住）。
  - **两把尺子（ontology/service）**：`known_subject_type_codes`（引用解析，含 retired）不变；新增 `usable_subject_type_codes`——**新建**值域只收 active 行（draft=未拍板提案、retired=禁新建存量只读，都拦闸外），project_id=None 即全局域。
  - **单原语闸门**：`create_subject_in_transaction` 里 `_ensure_subject_type_allowed`——人工创建与导入 commit 汇聚同一原语，一处把守「内置 ∪ active 注册 − project」；错误码新设 400 `unsupported_subject_type`（形状非法仍 invalid_request）。project 根类型永不可建（显式排除，注册表本就不得覆盖内置码）。
  - **导入三闸一致**：`authorize_subject_import` 改为**带回**该项目可导入域（内置 ∪ active − project）→ preview 形参化（缺省退回内置四类，旧调用兼容）→ store 绑定点复核 → commit 侧由原语复核（覆盖 preview→commit 30 分钟 TTL 内 retire 窗口）；commit 的 `ResearchSubjectServiceError` 转 `ImportServiceError`，路由契约不变。
  - **父级裁决**：注册类型无父级规则（`_PARENT_TYPES` 无条目）→ **本轮仅允许根级**（有 parent 即 `invalid_subject_parent`）；跟踪码无前缀 → `tracking_code=None`。层级规则留后续轮。
  - **功能域白名单冻结**：`MEMO_SUBJECT_TYPES`（subject_service + memo_merge_service）是备忘录功能范围不是值域，注册类型对象暂不进备忘录/合并——零改动，注释钉住。
  - **消费方对齐**：`documents/snapshots.py` 按**行上实际值**分组（内置 canonical 序在前、注册/退役类型按名字母序跟随）——retire 只禁新建不禁存量，快照永不丢类型；`documents/mapping.py` 允许域从**已发布 research definition 派生**（内置 ∪ 定义声明类型），保持纯函数不查注册表；`research/definitions.py` 加 `allowed_subject_types` 参（缺省=内置五类，纯函数语义不变）；`form_service` 两处、`ai/research_form_service` 两处生成器、`template_service` 四处、`validate_generated_template`（含 `templates/service` 落库权威校验与 AI 预筛同域）全部传「内置 ∪ active」。
  - **AI 幻觉基线与完整性基线不放开**：AI 生成表单缺省仍只认内置五类（调用方显式传注册域才放宽）；行业模板**五类内置调研表必备**不变（开放值域 ≠ 放弃底线），全局注册类型可作第六类追加。
  - **契约变化**：subject 创建/导入的「根类型/未知类型」错误码 `invalid_request`→`400 unsupported_subject_type`（旧契约测试同步改写）；零路由零桌面改动（ENTRIES 94、路由 293 不变）。
  - **口径**：105 表不变、迁移头 `c9e3a7d1b5f8`→**`b5d9e3f7a1c6`**（30→**31 rev**）、业务路由 **293** 不变、ENTRIES **94** 不变、pytest **1818 收集 = 1812 passed + 6 skipped**（T-O2b +10：值域域测试 9 + 迁移往返 1）、vitest 730 不变。**改 server + 新迁移 ⇒ rebuild 后必 `alembic upgrade head`**（api/worker/scheduler 三镜像）。

### T-O3 变更集 ontology_change_sets（候选→人工确认闭环）— **DONE（2026-11-03，分支 feat/v3-t-o3-change-sets，squash 合并至 fork/main）**
- 目标：批量变更事务单元+diff 评审+base 指纹并发防护；AI 候选唯一入口。
- 前置：T-O1。修改文件：ontology/service.py（propose/confirm/reject 事务）、routes.py。
- DB：ontology_change_sets。测试：change-set 状态机/base_conflict 409/AI 候选 confirm 前不物化。
- 风险：confirm 事务跨表物化需逐项补偿日志（失败回滚+事件记 partial）。复杂度：**M**。
- **实施记录（2026-11-03）**：
  - **一表+迁移**：`ontology_change_sets`（迁移 `c9e3a7d1b5f8`，30 rev，additive-only）。列域=设计 §2.4 原文（title/proposed_json/diff_summary/status/base_snapshot_sha256/提交与拍板留痕）+ `captured_from`（候选来源标记，如 `agent_run:<id>`——设计 §2.4 括注「captured_from 标 agent_run」落成列；仅服务层原语可写，HTTP 人工路径显式拒收）。CHECK 状态域含 `superseded`（设计原文保留位，本轮状态机不产出该态）。
  - **状态机**：draft →(submit)→ in_review →(confirm)→ confirmed / →(reject)→ rejected；draft 亦可 reject（撤回）。**submit 是设计 §4 表外的一条**——§4 只列 propose/confirm/reject，但 confirm 错误码 `not_in_review` 预设了评审态，而 base 指纹的语义是「提交时受影响行指纹」，故 submit 作为并发防护锚点落地（同 T-O2 retire 先例：为让验收用例在人工路径可达而补路由）。
  - **base 指纹**：submit 与 confirm 复核共用同一采集器 `_change_set_base_descriptor`——逐项对受影响面采快照（术语行全量含 definition；别名占用；关系类型项目行+全局行双快照），canonical JSON sha256。同时覆盖「既有行被并发改写」与「占位名凭空出现/消失」两类漂移，一律 409 `base_conflict` 零物化。
  - **confirm 单事务全成全败**：任一项物化失败→整体回滚（无 partial），错误 `change_set_item_failed` 点名项次与原因——设计风险条写的「补偿日志」以全有全无+事件逐项结果承载（强一致性优于补偿）。confirmed 事件 `ontology_change_set_confirmed` 携带逐项 results（设计强制）；propose/submit/reject **不落事件**（变更集行本身即审计记录：created_by/submitted_by/rejected_reason 全在行上）。
  - **载荷动作域裁决**：T-O3 开 `create_term`（直落 confirmed）/`update_term`/`merge_terms`/`register_relation_type`（只登记项目内类型，全局登记留 admin 人工路由——lesson 15）；**`create_subject`/`link_subjects` 设计列有、本轮不开放**（propose 即 `payload_schema` 点名拒绝——业务对象候选走既有表单/导入人工路径，避免与既有写路径双轨）。before/after 由服务端在物化结果里实测生成，不信任候选自报。
  - **update_term 语义裁决（对设计「新版本行」的落地解释）**：UNIQUE(project, term) 使同名新行不可共存。同名修订=**原行受控改写**（definition/term_type，version+1，旧定义随事件 results 留档）——change-set confirm 是全系统唯一 definition 写路径，「confirmed 不可原地改」不变式保持（无 change-set 之外的编辑路由/原语）；改名分支（`new_term`）才是行级取代：新行 confirmed + 原行 `superseded` 指 canonical + 原名转别名（合并保留来源同一纪律）——`superseded` 由此获得真实产出场景。
  - **验收分离（P0-5 纪律移植）**：confirm 与 reject 均要求拍板人 ≠ 提交人（403 `change_set_decider_conflict`，沿 gate `gate_decider_conflict` 先例）。
  - **路由 +7（286→293）**：GET terms（T-O1 欠账的只读面，?q= 名/别名检索）、change-sets GET×2/POST/submit/confirm/reject；全部**有意不进 api_catalog**（红线钉子测试扩展到三面）。`_load_project` 文案泛化为「本体操作权限」。
  - **事件双记裁决**：merge 走 T-O1 原语时其 `ontology_term_merged` 事件保留（term 级溯源），叠 change-set 级 confirmed 事件——粒度不同不算双写（T-O1 遗留裁决点，就此定案）。
  - **口径**：104→**105 表**、迁移头 `b8d3f1a5c7e2`→**`c9e3a7d1b5f8`**（29→**30 rev**）、业务路由 286→**293**（+7）、ENTRIES 94 不变、pytest **1808 收集 = 1802 passed + 6 skipped**（T-O3 +9：变更集 8 + 迁移往返 1）、vitest 730 不变（零桌面改动）。**改 server + 新迁移 ⇒ rebuild 后必 `alembic upgrade head`**（api/worker/scheduler 三镜像）。

### T-O4 导入别名去重接入 — **DONE（2026-11-03，分支 feat/v3-t-o4-import-dedupe，squash 合并至 fork/main）**
- 目标：research 导入遇同名不同 key → 产出合并候选 change_set 而非静默新建（imports.py 合成键路径 `_subject_key(preview_id, type, row)` 每行各异）。
- 前置：T-O1/T-O3。修改文件：`research/imports.py`。测试：test_research_imports 扩展。复杂度：**S**。
- **实施记录（2026-11-03）**：
  - **两把尺子裁决**：**文件内同名=致命行错误 `duplicate_name`**（`_batch_duplicate_errors` preview 报且首行干净、commit 同尺复核——文件是用户声明，歧义由人解决）；**文件 vs 项目既有 active 同名（同类型）=让位**（`_load_same_name_subjects`，with_for_update 与父级候选同款锁纪律）——撞名行不再静默新建，归档行不拦重建、跨类型同名不去重（不同实体）。
  - **合并候选三面呈现**：结果载荷新键 `merge_candidates`（name/row/description/matched_subject{id,name,tracking_code}，被让位行说明无损保留）；跟踪码只发真正新建的行（`allocate_tracking_codes` 计数改 len(creates)，新号接既有最大值无空洞）；**全让位=合法成功**（empty_import 检查从「subjects 空后置」改为「rows 空前置」；版本照常 +1；收据回放带候选，旧收据无键补空表向后兼容）。
  - **change_set 提案（实现偏差回写）**：台账原文「产出合并候选 change_set」落地为**术语层概念登记提案**而非 subject 合并动作——`_propose_import_merge_change_set` 对无术语/别名占用且 ≤TERM_MAX_LENGTH=120 的候选名按首现序去重提案 `create_term`（definition=被让位行说明，超长截 120），draft+`captured_from="research_import:<preview_id>"`，走 T-O3 submit→confirm 人工拍板坐实「一个名字一个概念」，拒绝无残留。**不开 subject 合并动作**：T-O3「业务对象不走 change_set 双轨」裁决仍成立，subject 合并原语牵动表单/答案/链接/跟踪码，L 级别另行立项（遗留候选：T-O4b）。>50 项截断并在 description 注明；ontology/service 新增占位检查原语 `existing_term_names`（任意状态术语行 ∪ 别名）。
  - **桌面端契约同步（预估外改动，偏差记录）**：台账「修改文件 imports.py」之外，桌面 `isResearchImportResultDto` 精确键集 +`merge_candidates` 必须同步（不同步=桌面拒收一切成功响应）——`ResearchImportMergeCandidateDto` 类型+`isResearchMergeCandidateDto` 验证器+测试。preview 载荷零变化（duplicate_name 走既有 errors 通道，`isImportError` 形状校验直透）。
  - **测试**：`test_research_imports.py` +7（批内致命/让位+提案+跟踪码钉子/全让位+回放/术语占用不提案/confirm 闭环+验收分离/跨类型不去重/超长截断）；桌面 +1。有界查询测试上限 1→2（T-O4 恒定 +1 次同名扫描，反乘法不变量保持）。
  - **口径**：105 表不变、**零迁移**（head `b5d9e3f7a1c6` 31 rev 不变）、路由 293 不变、ENTRIES 94 不变、pytest **1825 收集 = 1819 passed + 6 skipped**（+7）、vitest **731**（+1）。零部署迁移（改 server 仍须 rebuild 三镜像 + up -d，无需 alembic）。

## P1（可控自动化）

### T-W1 workflow 定义+版本表+DAG 校验器（域 5）— **DONE（2026-11-02）**
- 目标：definitions/definition_versions 两表；validate_dag 纯函数（环检测/白名单 ref/占位符/schema），先入 CI 无需执行器。
- 前置：无（校验器纯函数）。修改文件：NEW `server/src/fde_api/workflows/{__init__,models,definition_service}.py`。
- DB：两表。测试：NEW test_workflow_definition.py（§6 用例 1-3,5,7 的定义侧）。
- 验收：环/未知引用/非白名单 call.ref 一律 422 带明细。复杂度：**M**。
- **实施记录**：迁移 `f2a4c6e8b1d3`（两表，含 downgrade）；校验规则 1–8 全部阻断、规则 9（外部副作用须审批）按设计 P1 **只告警**（工具目录 effect 结构化在 T-R2 后转强制）；call.ref 白名单=api_catalog ENTRIES 全集（含只读），执行时还叠 `api_execute` 同闸（T-W3）；skill 白名单=active skill 既有版本（**已随 T-S1 收敛 published 语义**）；运行上下文键暂 `project_id/run_id/initiated_by_user_id`；事件目标注册表新增 `workflow_definition`（platform 模板 project_id=NULL）。**零路由**（§5 的 6 条路由随 T-W3 执行器+runs 一起开，避免先开无执行器的空面）。

### T-W2 runs/node_runs 表+迁移 — **DONE（2026-11-03）**
- 前置：T-W1。DB：workflow_runs、workflow_node_runs。复杂度：**S**。
- **实施记录**：迁移 `b7d9f1a3c5e2`（两表，含 downgrade）。run 固定 (definition_id, definition_version)；run 级 `idempotency_key` **全局唯一**（FV-F3 表级保证，跨定义/项目也拒）；`definition_id` FK **RESTRICT**（执行史在则定义不可静默删，与版本行 CASCADE=定义内部快照语义区分）+ `project_id` FK CASCADE（项目隔离；平台模板定义 project_id=NULL 不阻拦项目删除）。node_runs：UNIQUE(run_id, node_key)、node_type/status CHECK、attempt 计数、`depends_on` 冗余快照、节点级 `idempotency_key` 表级可空（**外副作用节点必填由 T-W3 执行器强制**，T-R2 effect 结构化前先由类型推断）、input_snapshot/output_json。状态机七态/八态按 workflow-dag-v1 §2（ready=依赖全绿待调度，T-W3 消费）。**零路由零执行器零服务改动**。

### T-W3 executor：call+skill 节点 — **DONE（2026-11-03）**
- 目标：`workflow.run` handler 注册进 jobs/handlers.py；call=api_execute 同闸、skill=published 固定版本；节点独立事务；ready 调度循环。
- 前置：T-W1/T-W2/T-S1（skill published 语义）。修改文件：NEW workflows/executor.py；EXTEND jobs/handlers.py、jobs/reconcile.py（RECOVERABLE 增 workflow.run）。
- 测试：test_workflow_executor.py（§6 用例 4-8,11）。复杂度：**M**。
- **实施记录（与设计的偏差，按主报告纪律回写）**：
  - **T-S1 前置按 T-W1 先例悬置（已清偿，2026-11-03 T-S1 落地）**：skill 节点执行与定义期白名单均已收敛 published 语义（executor._dispatch_skill / published_skill_refs）；skill 执行 = pinned 版本 `instructions_text` 作 system_prompt 的确定性 AI 调用（`execute_ai_prompt(use_tools=False)`，不签发 MCP token——skill 只做文本变换，工具面属于 call 节点），`execution_id=wfnode-{node 行 id}` 跨重试/恢复稳定可审计。
  - **§5 路由开五条**（271→276）：POST projects/{id}/workflows（can_manage，建草稿）、POST …/{wid}/publish（admin，锁版）、POST …/{wid}/runs（can_manage，201/200 按幂等命中）、GET projects/{id}/workflow-runs/{rid}（can_view，节点按拓扑序）、GET /api/v1/workflows（admin 平台模板）；**POST …/workflow-runs/{rid}/cancel 与 resume 的 HTTP 面随 T-W5**（服务层 cancel_run/resume_run 本轮已可用并有测试钉住）。
  - **用例 4 的「paused→resume」精确化为 failed + resume_run**（§3 终态语义优先：有 failed → run failed，修 FV-F1 不静默 done）；resume 把 failed/skipped 节点放回 pending（attempt 归零=计数按每轮恢复重置），已完成节点产物原样复用。
  - **agent/human_approval 节点在 start_run 即 422 `unsupported_node_type`**（不留必死 run；T-W4 开放时移除）。
  - **外副作用幂等（用例 6）**：写类（api_catalog write=True）call 节点由执行器在分派前强制落节点级 `idempotency_key`——与 `api_actions.execute_api` 完全同构的 sha256（`[user_id, "wfnode-{node行id}", {operation,parameters,body,query}]`），节点行跨重试/恢复稳定 ⇒ api_execute 层按 action id 去重，不二次外呼；effect 结构化仍待 T-R2，当前按 catalog write 字段推断。
  - **写类 call 节点撞 confirmation 闸 → 节点 failed**（error 携 action_id，诚实呈现"未执行"）；T-W4 human_approval 落地后接审批前置。
  - call 参数约定：params 中匹配 ref 路径模板的键 → path 参数（字符串）；保留键 `body`（对象）→ 请求体；其余 → query。
  - **when 的 T-W3 最小语义**：仅支持整串单占位符，取 JSON 值 Python 真值；缺键/其它形态一律假值（诚实不猜）→ 依赖断链时 skip 而非执行；表达式引擎待真实需求。
  - 运行上下文：run.context_json = 默认三键（project_id/run_id/initiated_by_user_id）+ 调用方自定义键（仅落库；定义期占位符白名单仍只有默认键，T-W1 校验未动）。
  - 恢复语义：RECOVERABLE 增 workflow.run（节点产物先落表=succeeded 即锚点）；handler 入口把 worker 死亡遗留的 running 节点放回 pending；reconcile 放弃（尝试耗尽）时钩子把 run 置 failed + 悬挂节点置 failed。
  - 事件：新增目标 `workflow_run`（workflow_run_created / succeeded / failed / cancelled / resumed）。
  - 测试：test_workflow_executor.py **19 例**（用例 4/5/6/7/8/11 + 路由权限/平台模板/断链/when 跳过/缺占位符/outbox→worker 全链/reconcile 钩子）；test_migrations HEAD 不变（零 DDL）。

### T-W4 executor：agent+human_approval 节点 — **DONE（2026-11-03）**
- 前置：T-W3。审批复用 automation_approvals。测试：§6 用例 9-10。复杂度：**M**。
- **实施记录（与设计的偏差，按主报告纪律回写）**：
  - **审批复用落地形态**：automation_approvals 加**可空** `workflow_node_run_id` 反链 + `run_id` 放开可空（迁移 `d5b8e2f4a7c9`，head 变更 25→26 rev；本任务唯一 DDL）。审批行=节点等待态的投影：反链 FK **CASCADE**（沿 node_runs.run_id 的 CASCADE 语义，审计事实由 operation_events 承载）；`uq_automation_approvals_run_request` 对 NULL run_id 不生效 ⇒ request_key 约定 `wfnode:{节点行id}`（全局唯一）+ 分派前 pending 查重双保险（崩溃恢复不重复建单，审批 id 挂节点幂等键作恢复锚点）。
  - **拍板入口 = 既有任务中心 `decide_automation_approval`（零新路由）**：decide 按 run_id 是否为空分支——automation 审批照旧写 task_run；workflow 审批经 `_settle_workflow_node` → `executor.settle_approval_node` **同事务**落节点终态（approve→succeeded，output 携 approval_id/拍板人/理由；reject/expired→failed）并重投 workflow.run。落点在公共字段（拍板人/理由）赋值**之后**调用，节点产物才带真实理由（首轮实现踩过：settle 在 reason 赋值前读到空串）。
  - **等待语义**：无 ready 且剩 waiting 节点 → run=`waiting_approval`（handler 正常返回、job 完成；**有 failed 先断链收敛** FV-F1）；拍板重投续跑，`_recover_interrupted` 把 waiting_approval 放回 running、`_settle_run` 对非终态不盖 finished_at。无人拍板则挂起（可取消）；**过期判定沿用「拍板时惰性判定」既有语义**（T-P1-5 清扫器落地前不做主动清扫）。取消：waiting 节点 cancelled、pending 审批行不动（迟到拍板只落审批行、不再驱动节点——settle 落点要求节点仍 waiting）。resume_run 保持 failed-only（waiting_approval 提示先拍板或取消）。
  - **审批材料**：`{kind, workflow_run_id, node_key, input_snapshot}` + sha256 指纹 + **敏感键扫描**（`_contains_sensitive_argument` 提升为 `control/access.contains_sensitive_argument` 公共函数，DSH 审批与 workflow 审批同闸）+ 64KB 上限（同 create_dsh_approval_request 口径）；risk_level 固定 4（人工门=保守高险标注）；`dsh_approval_status` 惰性过期与 `execute_approved_dsh_tool` 同步加 workflow 分支守卫（审批无执行段，409 approval_not_executable）。
  - **定义期**：human_approval.capability 白名单 = `CAPABILITY_REQUIREMENTS` 去 `system.*`（`APPROVAL_CAPABILITIES`）；validate_dag 注入参数 `capabilities`（None 跳过=纯函数单测兼容，生产路径 `validate_dag_against_registry` 注入）；risk_level/expires_minutes 既有校验不变。
  - **agent 节点 = `agents.service.start_run` 同闸全链**（实时鉴权/预算/试点/T1/T6/沙箱/产物校验，绝不旁路），幂等键 `wfnode-{节点行id}:{attempt}`——agents 对失败终态 run 拒绝同键重跑（V8），工作流以 **attempt 代际**表达「显式重试」（resume/可重试崩溃恢复各开新代际；同 attempt 重复投递命中 completed 复用）；分派失败一律 retryable=False（agents 自带重试族，工作流不叠加）；分派未预期异常对 agent 节点也**非重试**（避免同图二次拉起沙箱 run）。`params.solution_id` 占位符解析后透传（agent_assisted/T1 方案闸随之生效）；`difficulty`/`max_cost_units` 节点字段未开放（后者属 agent 注册表授权成本档，T6 闸按注册表判）。
  - start_run 422 守卫保留为防御（四类全支持后实际不可达；未知类型用例靠绕过定义期校验手工构造「发布后白名单漂移」场景）。
  - 事件：`workflow_run_waiting_approval`（run 挂起）/ `workflow_run_approval_decided`（拍板落点）。
  - 测试：test_workflow_executor.py **19→26**（审批批准/拒绝/过期/等待中取消+迟到拍板中和/幂等重入 + agent 全闸/能力拒绝不重试/run 失败不叠加工作流重试；unsupported 用例改未知类型）+ test_workflow_definition.py +1（capability 白名单，system.* 排除）；test_migrations HEAD 钉 `d5b8e2f4a7c9`（往返含 downgrade 先清 workflow 审批行再恢复 NOT NULL）。

### T-W5 cancel/resume + reconcile 收敛 — **DONE（2026-11-03）**
- 前置：T-W3。API：POST …/workflow-runs/{rid}/cancel。测试：§6 用例 8。复杂度：**M**。
- **实施记录（与设计的偏差，按主报告纪律回写）**：
  - **HTTP 面 = 服务层两条路由挂接（零服务层改动、零 DDL 零迁移）**：POST `/api/v1/projects/{id}/workflow-runs/{rid}/cancel` 与 `…/resume`（均 can_manage，闸在 `load_project(manage=True)`；跨项目 404 不泄露存在性）。路由总数 276→**278**。标题里的「reconcile 收敛」已随 T-W3 落地（RECOVERABLE 增 `workflow.run` + worker-loss 钩子 `_fail_run_on_worker_loss` + 放弃时 run/悬挂节点 failed，测试钉住），本任务无残留。
  - **cancel 幂等语义照服务层**：非终态 → 200 `cancelled=true`（未执行节点 cancelled，已执行外呼不回收）；重复取消 → 200 `cancelled=false`；终态 → 409 `already_terminal`；waiting_approval 可取消（pending 审批行不动，迟到拍板被 token 守卫中和——T-W4 语义）。
  - **resume failed-only**：failed → 200 `reset_nodes`（failed/skipped 放回 pending、attempt 归零，重投 `workflow.run`）；其余状态 → 409 `not_resumable`（waiting_approval 提示先拍板或取消）。
  - 测试：test_workflow_executor.py **26→27**（新增 `test_routes_cancel_and_resume_lifecycle_and_permissions`：viewer 403 / 幂等取消 / already_terminal / 跨项目 404 / failed-only 恢复+节点回 pending / not_resumable；服务层语义由既有用例 4/8 钉住，HTTP 用例直改状态造终态/失败场景）；test_migrations HEAD 不变。
  - **同轮附带修复（CI 实测暴露的既有隐性 flake）**：`test_workflow_definition.py::test_definition_publish_locks_immutable_version_rows` 的事件断言裸查 `operation_events` **无 order_by**（堆物理序，PR #77 CI 同码双 run 一绿一红、实际 `[updated, published, created, published]`）→ 补 `order_by(occurred_at, id)` 定序（occurred_at=事务级时间戳各 commit 微秒互异；id 是 uuid4 不可作决胜键）。与本任务功能面无关，测试唯一改动。
  - 桌面控制台（run 列表/取消/恢复按钮）随 T-W6；当前 HTTP 面即 API 完整面。

### T-R1 agent_tool_groups（域 7）
- 目标：只读工具组目录（种子文件 `server/seeds/tool_groups.json`），allowed_tools 支持 group: 引用，resolve=交集。
- 修改文件：`agents/models.py`（或纯种子无表——**采用种子文件方案，零新表**）、`agents/tools.py`。测试：test_agents_fallback_chain 扩展（组不放宽/组引用未知工具拒绝）。
- 风险：低。复杂度：**S**。

### T-R2 工具目录结构化 effect/risk（域 9，含 WB-DEF-10）
- 修改文件：`control/mcp_gateway.py`（TOOLS 元组扩 effect/risk）、`control/api_catalog.py`（ENTRY 扩字段；export_sow/documents.generate 标 confirmation）。测试：test_ai_tool_loop/test_control_plane_api 扩展（目录扫描断言/写类确认流）。复杂度：**S**。

### T-S1 Skill 治理态扩展（域 8）— **DONE（2026-11-03）**
- 目标：status draft/in_review/published/deprecated；publish 四条闸；_skills 只回 published。
- 修改文件：`control/models.py`、`extensions_service.py`、`builtin_skills.py`、`mcp_gateway.py`。DB：skill_definitions 加 published_by/at（+status 枚举扩展需迁移）；skill_versions 加 input_schema/output_schema/test_report_json/reviewed_by。
- API：submit-review/publish/rollback/versions（agent-policy-v1 §2.4）。测试：NEW test_skill_lifecycle.py（§2.5 七用例）。
- 回滚：downgrade+revert。风险：存量 14 个 builtin 种子状态迁移（seed 直接 published）。复杂度：**M**。
- **实施记录（与设计的偏差，按主报告纪律回写）**：
  - **状态机（定义级）**：`draft →(submit-review)→ in_review →(publish)→ published →(deprecate)→ deprecated`；编辑已发布公共 Skill → 新版本行 + 定义回 draft（重走治理，复活路径天然存在）；迁移 `c1e5f9a3d7b2`（head 26→**27 rev**，本任务唯一 DDL）：CHECK 换值域 + 存量数据迁移（**active→published**（published_by 暂记 created_by、published_at=now）、**disabled→deprecated**）+ skill_definitions.published_by/at + skill_versions.input_schema_json/output_schema_json/test_report_json/reviewed_by_user_id（全可空；版本行不可变语义不变）。
  - **发布四闸落地**：①admin（system_operator）②**密码确认**（verify_password，`invalid_password` 403，沿 solutions 弃用先例）③状态须 in_review（否则 409 `not_in_review`）④**测试报告或显式 waive**（版本行 test_report_json 非空或 waive_reason ≤500 字，否则 409 `test_report_required`）。发布只置定义态+发布人戳并把版本行 reviewed_by 落为发布人（发布即审核背书）。
  - **个人 Skill 豁免治理工作流（自发布语义）**：保存即 published（owner 自治；个人技能本就 owner-only 可见），四闸只对公共 Skill 生效——审计 B12/B13 的治理缺口针对的是公共面。
  - **种子兼容**：`save_public_skill` 增服务端内部参数 `initial_status`（仅种子路径传 `"published"`，HTTP 面不暴露）；`_is_unchanged_builtin` 升级判定随治理态收敛 `status=="published"`；存量种子由迁移升为 published，下次 seed 升级链路不断。
  - **指纹扩展**：content_sha256 canonical 覆盖 instructions+manifest+capabilities+**input_schema+output_schema+test_report**（发布材料整体不可变；补一份测试报告也开新版本重走治理）。
  - **API 五条（278→283）**：POST `…/extensions/skills/{id}/submit-review`、`…/publish`{password, waive_reason?}、`…/rollback`{version, password, waive_reason?}、`…/deprecate`、GET `…/versions`（公共任何登录用户可读，个人 owner-only；回滚=published 内改指 current_version_number 到旧版本行，同密码+材料闸——agent-policy §2.4 四条 API 之外补 deprecate，因状态机需要显式出口）。
  - **消费方收敛（T-W1/T-W3 挂账清偿）**：`mcp_gateway._skills`、`published_skill_refs`（定义期 skill.ref 白名单）、`executor._dispatch_skill` 三处 `status=="active"` 全部收敛 `"published"`。
  - **既有 PATCH 开关调和（backlog 未列的隐藏面）**：桌面扩展页「停用/启用」走 `PATCH /extensions/skills/{id}`{status: active|disabled}——零桌面改动前提下保留旧值域作别名（active↔published / disabled↔deprecated）：个人 Skill=owner 自愈发布（幂等 no-op）；公共 Skill 的发布向开关 **409 `governance_required`**（开关不得旁路四闸），停用向照旧可用。桌面治理 UI（submit-review/publish 按钮）挂后续轮。
  - **迁移实现教训**：首轮把数据 UPDATE 写在 add_column 之前（引用尚不存在的列）——conftest 每会话 downgrade base→upgrade head 即红，测试库先于 CI 暴露；列先行→约束换值→迁数据的顺序才对。
  - 测试：NEW test_skill_lifecycle.py **7 例**（四闸逐一可见/契约+报告免 waive/编辑回 draft 重走治理+公共开关防旁路/回滚材料闸+already_current+404/弃用退出+复活封路/个人自发布+PATCH 幂等/CHECK 状态域自检）+ 修 5 处 active 语义既有用例（chat_mcp make_skill、executor _seed_skill、solution_skills/lcsc_other 的 _is_unchanged_builtin 自测、extension_management 的「建→停→改名重存」PATCH 流改治理语义）；test_migrations HEAD 钉 `c1e5f9a3d7b2`（往返含数据迁移双向归位）。

### T-S2 Skill 回滚+效果统计 — **DONE（2026-11-03，分支 feat/v3-t-s2-skill-usage-stats，squash 合并至 fork/main）**
- 前置：T-S1。复杂度：**S**。
- **实施记录（与设计的偏差，按主报告纪律回写）**：
  - **回滚已随 T-S1 落地**（POST …/rollback + 同密码材料闸），本任务唯一新增面=**效果统计**（agent-policy §2.4「效果评估：run 面累计 usage，operation_events 已有基础」）。
  - **T-S1 审计缺口顺带收口**：gap-matrix 域 8 验收「回滚留 operation_events」在 T-S1 未落地（publish/rollback/deprecate 零事件）——本轮补齐四条治理事件 `skill_review_submitted / skill_published（version+waive_reason）/ skill_rolled_back（from_version+to_version+waive_reason）/ skill_deprecated`，与生命周期服务函数同事务落表；闸失败（403 错密码 / 409 材料）不留事件（有测试钉住）。
  - **双消费面计数**：`skill_used_chat`（MCP `skill_read` 成功读出指南，mcp_gateway 落点）+ `skill_used_workflow`（executor `_dispatch_skill` 按 pinned 版本完成一次确定性 AI 调用）。**失败不计**（AI 异常/重试是噪声不是效果；skill_ref_unavailable=内容未被消费）；attempt 代际各计一次（resume 重跑的每次都真消费了）。skill_list 只浏览不计数。
  - **关键实现约束——独立微事务**：直连 AI 工具循环每轮 tool 后**回滚共享会话**（ai_tool_loop 假定工具只读），经 call_tool 的消费计数必须自带已提交事务才能存活——`record_skill_usage` 自开 `db.session()+begin()`（与 run_lcsc_skill 穿过 call_tool 自管事务的先例同构），有专项测试钉「call_tool 后 rollback 事件仍在」。
  - **导环教训（实现偏差）**：原计划把 SkillDefinition 注册进 projects/events.py 的 `_TARGET_TYPES` 走公共 `record_event`——顶层 `from fde_api.control.models import …` 会经重型 `control/__init__`（→control.routes→control.service→projects.service）反转 projects↔control 导入序，实测 import 即环。改为 control 层 `_event` 直落 `OperationEvent`（api_actions.py:73 同构）：`target_type="skill_definition"`、`project_id=None`（Skill 不挂项目：公共技能全局面/个人仅 owner）、changes 键固定非敏感（version/surface/from_version/to_version/waive_reason）。事件注册表未扩——record_event(SkillDefinition) 未来若被调用仍 TypeError，属已知边界。
  - **统计读出（零新路由，283 不变）**：GET …/extensions/skills/{id}/versions 响应新增 `usage` 块——`{total, chat, workflow, last_used_at, by_version, truncated}`；有界扫描（最近 1000 条消费事件，新→旧）Python 侧聚合（metrics/service 同款模式），触顶 `truncated=true` 诚实标注；治理事件不进 usage；by_version 供回滚决策（旧版本还在被 workflow pinned 引用吗）。桌面端本就不消费 versions 端点，零桌面改动（vitest 731 不变）。
  - 测试：test_skill_lifecycle.py **7→11**（治理事件四类+闸失败零事件 / chat 计数+回滚存活+404 不计数 / usage 汇总含零值与按版本 / truncated 诚实标注）+ test_workflow_executor.py 两用例扩展（pinned v1 消费断言 / 失败 attempt 不计消费）；零迁移零新表（operation_events 直落），test_migrations HEAD 不变 `b5d9e3f7a1c6`。

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
