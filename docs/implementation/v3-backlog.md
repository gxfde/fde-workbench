# V3 实施任务台账（backlog）

> 状态：**T-\* 任务 33 节全部 DONE**（P0–P2 全部 DONE 或核销；P3 四项已定案收口，见 §P3 与 v3-p3 三报告）；「开源借鉴清单登记」段 B#1–B#40（#127 登记 34 项＋#133 评审补登记 6 项）：**P0 先行批表 10 项 ✅ 已实施**（#128~#131），其余按逐条状态标注——PROPOSED/冻结/封存/修复项（登记≠排期≠默认实施）。任务 ID 与差距矩阵/风险登记册互引。
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

### T-O4b subject 合并原语（T-O4 遗留候选收口，L）— **DONE（2026-11-04，分支 feat/v3-t-o4b-subject-merge，squash 合并至 fork/main）**
- 目标：同名重复调研对象的唯一治理出口——source 并入 target，牵动表单/答案/链接/子对象/备忘录/机会画像/跟踪码的原子搬迁；T-O3「业务对象不走 change_set 双轨」裁决维持（合并不进变更集，也不进 api_catalog）。
- 前置：T-O4（导入让位产生合并候选）。修改文件：`research/models.py`（+`merged_into_subject_id` 列）、`research/subject_service.py`（merge_subject + _relocate_subject_surfaces + 序列化键）、`research/project_routes.py`（+1 路由）。
- DB：迁移 `d4e6f8a2c7b9`（31→**32 rev**）——可空列 + 复合外键（RESTRICT 自引用）+ 两条 CHECK（不自指；指向即必归档）+ 索引，含 downgrade。
- **实施记录（2026-11-04）**：
  - **六面搬迁纪律**：①表单——键不撞整表搬迁（修订+答案随外键同行）、撞键且源无答案让位删除（current_revision 指针先摘再删，RESTRICT 顺序）、**撞键且源有答案 409 `merge_form_conflict` 点名键**（绝不静默丢采集）；②链接——边重指 target，自环/与存续边重复者删除（搬迁前先把「不触 source 的全量边」建成集合，重指后即时并集去重）；③子对象随迁（同类型 ⇒ 父类型规则天然成立，含归档子行），既有合并链一跳化（沿 T-O1 术语合并先例，依赖行 version 递增）；④共享 memo 与个人备忘录带「（合并自 名字 跟踪码）」头并入（与编辑闸同尺 20 000 超长显式截断；个人备忘录目标无同人行则整行重指）；⑤机会画像目标无→整行迁入、双有→**目标留任+源画像字段随事件留档**（画像创建即有，留任是唯一可行语义，为裁决点）；⑥**跟踪码不回收**——归档行永久占号，`allocate_tracking_codes` 扫全量行天然越过。
  - **闸序**：自指 400 → stale_version → project 根 409 `research_subject_root_immutable`（**先于类型检查**，根对象永不参与合并）→ 类型一致 409 → 双方 active 409 → 表单冲突 409。source 让位 = archived + `merged_into` 指向 + version+1；subject_key/跟踪码原地保留占位（UNIQUE 绝对，同 T-O1 merged 术语语义——同名重建仍被让位行挡住，归档行即历史）。
  - **路由 +1（295→296）**：`POST /projects/{id}/research/subjects/{source_id}/merge`，body `{version, target_subject_id}`，`_require_subject_write` 同档案闸（can_manage or can_update_assigned_tasks）；**有意不进 api_catalog**（钉子测试 `test_merge_route_never_in_catalog`），非成员 404 `project_not_found`（调研域隐藏存在性口径）、viewer 403。事件 `project_research_subject_merged` 挂 source，载荷带全部计数+双跟踪码+被弃画像摘要。
  - **序列化契约**：`_serialize_subject` +`merged_into_subject_id`（恒输出，null=未让位）——服务端契约钉（test_research_subjects_api 根对象用例）与桌面 `ResearchSubjectDto` 可选键+运行时校验双同步（旧载荷缺键兼容，T-O4 桌面契约同步先例重演）。
  - **测试**：NEW `test_research_subject_merge.py` 7 例（全表面搬迁+响应摘要计数+列表序列化+占号验证 / 撞键 409→人工处置→重试成功且零残留 / 根·类型·自指·stale·归档源·归档目标六拒绝 / 链一跳化 / 画像迁入与留任双分支+事件留档 / viewer 403·非成员 404 / catalog 钉子）；`test_migrations` HEAD `d4e6f8a2c7b9`；conftest 清理序 +「merged_into 置空」（同表自引用先解除再删行）。
  - **口径**：105 表不变（列级增量）、迁移头 `b5d9e3f7a1c6`→**`d4e6f8a2c7b9`**（**32 rev**）、业务路由 295→**296**（+1）、ENTRIES 94 不变、pytest **1838 收集 = 1832 passed + 6 skipped**（+7）、vitest **752**（+2）。**改 server + 新迁移 ⇒ rebuild 后必 `alembic upgrade head`**（api/worker/scheduler 三镜像）。
  - **桌面 UI 补轮（2026-11-04，分支 feat/v3-t-o4b-merge-ui，遗留 UI 轮收口）**：对象树操作栏「合并」入口（选中非根对象且 canFill；对话框挑**同类型启用对象**为目标 → 密码确认 → `POST /research/subjects/{source_id}/merge`）+ 树底「已归档（N）」折叠组（归档行不可选中、不进 treeitem 键盘导航；合并让位行「已并入 X」回链——目标仍启用=可点击跳选，已停用=纯文本；普通停用行一并可见）；契约 `ResearchMergeResultDto` + `isResearchMergeResultDto`，`subjectMutationError` 补 4 错误码映射（root_immutable/type_mismatch/source|target_not_active）。测试 +6（树 3 / 工作区合并流+错误映射 2 / 契约 1），vitest **761**（基线 `8340e89` 实测 755），typecheck 绿；服务端零改动（pytest 1863 / 105 表 / head `c7e1a9f3b5d8` / 路由 296 / ENTRIES 94 / mypy 279 全不变，无需 rebuild），便携版重打包 r13 + asar 字节验证。
  - **实施偏差（记录在案）**：①「导入结果 merge_candidates 卡片一键合并」**前置缺失**——桌面端调研数据导入 UI 未立项（`/research/subjects/imports/preview|commit` 端点与桌面 DTO 校验器在、零 UI 消费），留待「调研数据导入 UI」独立轮（已于同日收口，见下节）；②「对象树右键合并」以操作栏行内「合并」按钮替代（与既有停用同位同模式），避免引入整套右键菜单系统。

### 调研数据导入 UI（T-O4b 偏差①新立候选收口，M）— **DONE（2026-11-04，分支 feat/v3-research-import-ui，squash 合并至 fork/main）**
- 目标：`imports/preview|commit` 端点（T-O4，d14 前）的桌面消费面——CSV/XLSX 批量创建调研对象 + 导入结果 `merge_candidates` 卡片（T-O4「同名让位」语义的人工回溯面），补齐 T-O4b 桌面轮挂账的前置缺失。
- 修改文件：NEW `research/ResearchImportDialog.tsx`；EXTEND `research/ResearchWorkspace.tsx`（入口/结果卡片/stale 刷新）、`styles.css`；服务端零改动。
- **实施记录（2026-11-04）**：
  - **对话框两段式**：类型（内置四类非 project）+ 文件（CSV/XLSX ≤10MB 客户端预检）→ `POST /research/subjects/imports/preview`（复用桌面结构化 multipart 通道 `kind:"multipart_file"`：`fields.subject_type` + `file.bytes`，AI 预调研/文档模板同源）→ 预览表（行/名称/说明/父级）+ 行错误清单；存在校验错误即禁提交（服务端本就 422 `invalid_research_import`，`details.errors` 与预览内联错误共用同一展示区）→ `POST …/imports/commit`（`{preview_token, version}`），错误行 ≤8 条点名、超出计数。
  - **工作区接线**：标题行「导入对象」入口（canFill）；导入完成 → 结果卡片（新建 N + 幂等回放标注 + merge_candidates 让位回溯：行号/同名既有对象（类型+跟踪码）/文件中说明 + 「查看 X」跳选既有对象）；`stale_version` 时 `onStale` 触发 `loadResearch`，对话框内提示重新解析再提交。
  - **复用零改动**：`isResearchImportPreviewDto` / `isResearchImportResultDto` / `parseResearchImportErrorDetails`——T-O4 桌面契约同步轮预置的校验器首次接线，零消费欠账清偿；`researchImportError` 映射 15 个导入面错误码。
  - **jsdom 适配**：File 无 `arrayBuffer()`（jsdom 26 实测）→ `readFileBytes` 双路径（真环境快路径 + FileReader 兜底），真机与测试同一组件代码。
  - **测试 +4**（导入主路径含让位卡片回链 + multipart body 契约断言 / 行错误禁提交零 commit / 预览拒绝映射（415 仅支持 CSV/XLSX）/ stale 提交触发刷新），vitest **765**（基线 fork/main `65a40c5` 实测 761，+4），typecheck 绿；服务端零改动（pytest 1863 收集 = 1857 passed + 6 skipped / 105 表 / head `c7e1a9f3b5d8` / 路由 296 / ENTRIES 94 / mypy 279 全不变，无需 rebuild），便携版重打包 r14 + asar 字节验证。

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

### T-W6 桌面控制台（域 16）— **DONE（2026-11-04，分支 feat/v3-t-w6-desktop-console，squash 合并至 fork/main）**
- 前置：T-W3/T-W5/T-S1/T-S2/#85（样式令牌）。复杂度：**S**（设计稿口径；实际 S+，见偏差）。
- **实施记录**：
  - **三张新页全 NEW**（gap-matrix 域 16 目标文件兑现）：`workflows/WorkflowConsole.tsx`（项目 tab「工作流」）、`ontology/GlossaryPage.tsx`（项目 tab「术语表」）、`extensions/SkillVersionsPage.tsx`（扩展中心 Skill 卡「版本」对话框）。页面仅呈现；写操作（cancel/resume/change-set submit/confirm/reject/skill 治理四动作）全走既有 require_auth+服务层闸，403/409 原样呈现不吞。
  - **实现偏差（§5 设计面之外补两条只读路由，已回写 workflow-dag-v1 §5 注记）**：T-W5 挂账句「当前 HTTP 面即 API 完整面」对「run 列表」不成立——控制台要枚举就得有列表面。补 `GET /projects/{id}/workflows`（定义列表 can_view，无分页——项目内定义天然少量）与 `GET /projects/{id}/workflow-runs?limit=`（run 列表 can_view，默认 50 上限 200 有界扫描 + `truncated` 诚实标注；**列表行不带 nodes** 防 N+1，节点树走既有详情路由按需展开）。路由 293→**295**。权限语义：非成员 403 forbidden（load_project），项目不存在才 404。
  - **usage 块消费**（T-S2 数据源闭环）：SkillVersionsPage 呈现 total/chat/workflow/last_used_at/by_version/truncated——by_version 直接服务回滚决策（旧版本还在被 workflow pinned 引用吗）。
  - **诚实语义钉进测试**：failed 本就是终态不显示取消（TERMINAL_RUN_STATUSES）；取消竞态 409 already_terminal / resume 非 failed 409 not_resumable / 自确认 403 / 错密码 403 全部 alert 呈现；无密码/无回滚目标客户端侧先拦（不发无效请求）；无治理权只读提示。
  - 测试：服务端 +1（`test_routes_list_definitions_and_runs_permissions_and_bounds`：can_view 闸/局外人 403/排序/limit 0·非整数·201 三种 400/截断诚实/行无 nodes）；桌面 vitest **731→749**（workflow-console 5 / glossary-page 6 / skill-versions-page 7）+ typecheck 绿。服务端 pytest **1830 收集 = 1824 passed + 6 skipped**。零迁移（head `b5d9e3f7a1c6` 不变）/ ENTRIES 94 不变。
  - 项目 tab 枚举 8→10（+workflow/+ontology），`PROJECT_DETAIL_TABS` 与 tab 栏同源，无 legacy 映射需求。

### T-R1 agent_tool_groups（域 7）— **DONE（2026-11-04）**
- 目标：只读工具组目录（种子文件 `server/seeds/tool_groups.json`），allowed_tools 支持 group: 引用，resolve=交集。
- 修改文件：`agents/models.py`（或纯种子无表——**采用种子文件方案，零新表**）、`agents/tools.py`。测试：test_agents_fallback_chain 扩展（组不放宽/组引用未知工具拒绝）。
- 风险：低。复杂度：**S**。
- **实施记录**：
  - **纯种子零新表兑现**：`server/seeds/tool_groups.json`（`_comment` 锚注 + 两行组：`research-readonly` 9 工具 = read_file+项目/门禁/报价/本体/API 目录检索面；`ops-readonly` 6 工具 = 系统状态/动作留痕/立创运行史/技能只读/帮助；行含 `description`/`is_active`——停用组=代码侧空贡献开关，装载即不暴露）。首批组有意不收写类/会议面/插件锚点工具——前两类被 run 面恒剥，插件类按发起人实时安装态另判，种子保持「纯只读」自描述。
  - **解析=交集（组永不扩大，V3-R4「只收窄」代码化）**：`resolve_tool_groups` 把 `group:<name>` 展开并入声明集（保序去重，直接项+组贡献并集）后走既有三重交集管线——组贡献与直接声明同权过 平台 deny ∖ 写类/会议面 ∩ 发起人档位地板 ∩ 插件安装态，组引用本身不新增任何旁路。未知/停用组贡献为空（只收缩不放宽、运行面不崩溃）。
  - **fail-fast 种子校验**：组引用未知工具装载即 RuntimeError（分母=`KNOWN_TOOL_NAMES`=网关 TOOLS ∪ MEETING_AGENT_TOOLS ∪ 沙箱生态 `SANDBOX_TOOL_NAMES`{read_file}；嵌套 `group:` 引用因不在全集内同拒）；沿 agents.json 校验先例（进程级 lru_cache，坏种子宁可起不起来）。
  - **报因补口（backlog 未列的隐藏面）**：`_unavailability` 原以解析后分母判「声明过 run 面」——纯未知组声明解析为空会被当「没声明过」静默放行空名单 run。新增 `declares_run_tools`（解析前原样判定，组引用也算声明）作报因闸：声明过但解析+三重闸后全灭 → `tools_unavailable`。空声明/仅会议面 agent 行为不变。
  - **测试注入链**：`run_face_declared`/`effective_run_tools` 增 `groups=` 注入参（生产恒走种子，仅供测试整链替换）——注入组贡献能穿透 effective_run_tools 验三重闸。`list_agents` 序列化仍展示原始声明（组引用自描述，解析留 run 时刻冻结语义不变：在跑 run 不重算）。
  - 测试：test_agents_fallback_chain **+4**（真种子装载+未知工具/嵌套引用 fail-fast / 组不放宽三闸齐验：写类剥除·档位地板 project_lead 拒 lcsc_search·插件目录声明未安装 admin 也剥 / 未知组收缩+tools_unavailable 报因+混合声明不受污染 / 真种子混合声明保序去重+停用组空贡献）；pytest **1847→1851 收集（1845 passed + 6 skipped）**。零迁移（head `c7e1a9f3b5d8` 不变）/ 路由 296 不变 / ENTRIES 94 不变 / mypy 基线 273 不变 / 桌面零改动（vitest 755 不变）。

### T-R2 工具目录结构化 effect/risk（域 9，含 WB-DEF-10）— **DONE（2026-11-04）**
- 修改文件：`control/mcp_gateway.py`（TOOLS 元组扩 effect/risk）、`control/api_catalog.py`（ENTRY 扩字段；export_sow/documents.generate 标 confirmation）。测试：test_ai_tool_loop/test_control_plane_api 扩展（目录扫描断言/写类确认流）。复杂度：**S**。
- **实施记录（与设计的偏差，按主报告纪律回写）**：
  - **api_catalog：结构化字段落在 CATALOG 装配层而非 ENTRIES 行**（偏差：原计划「ENTRY 扩字段」）——ENTRIES 保持五元不动，新增 `_catalog_row` 装配函数派生 `effect`（read|write_db|external）/`risk`（0–4，与 automation_approvals.risk_level 同尺度）两字段；派生规则显式：GET=read/0、确认类=3、其余 external=2、普通写=1（4 留最高危未用）。消费面（api_actions/mcp_gateway/definition_service/executor）全走 CATALOG，ENTS 行扩字段无消费者受益反添 94 行维护负担。两个显式集合承载例外：`EXTERNAL_EFFECT_KEYS`（forms.export/solutions.export_sow/documents.generate/translator.translate=异步作业或模型调用）、`CONFIRMATION_KEYS`（export_sow/documents.generate——**WB-DEF-10 补口**：确认面不再只看 DELETE/.archive/.deprecate 后缀，AI 经 api_execute 发起即 awaiting_confirmation，密码确认后才触发 worker 内模型调用）。
  - **TOOLS 五元**：(description, capability, properties, effect, risk)——`file_send_wechat`=external/3、`api_execute`=write_db/3、`lcsc_search`=external/2（外网只读浏览，risk<3 不入审批类）、其余 13 只读=read/0。**tools/list annotations 改派生**（readOnlyHint=effect==read、destructiveHint=risk>=3），取代工具名硬编码集合（file_send_wechat 由 non-destructive 修正为 destructive=确认类，标注保真即本任务目的）；解包适配 5 处（mcp_gateway.call_tool / ai_tool_loop.tool_definitions / 三处测试）。agents/tools.py 与 extensions_service.py 为索引式消费零改动。
  - **workflow rule 9 消费目录权威**：`validate_dag` 增 `call_effects` 注入参（**沿 T-W4 capabilities=None 先例**：None=仅节点自声明生效，纯函数单测兼容；生产 `validate_dag_against_registry` 恒经新增 `catalog_call_effects()` 注入）——目录 effect=external 即触发 `external_effect_without_approval`；节点 effect 声明**只加不减**（不可把目录 external 降级为 read，与 T-R1 组永不扩大同构）。**P1 仍告警不阻断**——backlog T-W1 行「T-R2 后转强制」按 workflow-dag-v1 原文收敛为：结构化=T-R2（本轮），强制=P2 enforcement wave（rule 9 代码注释原文口径），无路由无生产定义 ⇒ 行为零影响。
  - **executor `_is_external_call` 收敛**：`write` 字段推断改结构化 `effect != "read"`（两集合按派生规则恒等价，清偿 T-W3 挂账「effect 结构化仍待 T-R2」）。
  - 测试：test_ai_api_actions **+2**（effect/risk 全目录一致性扫描+派生规则锁定 / WB-DEF-10 双操作确认流）；test_ai_server_chat_mcp **+1**（annotations 派生断言）；test_workflow_definition **+1**（目录权威+不可降级+未注入兼容+装配同域）；test_ai_tool_loop/test_help_fetch_tool 解包适配顺带断言结构化元数据；pytest **1851→1855 收集（1849 passed + 6 skipped）**。零迁移（head `c7e1a9f3b5d8` 不变）/ 路由 296 不变 / ENTRIES 94 不变 / mypy 基线 279 不变（104 distinct，实测零新增；T-R1 记录的「273」为笔误口径，基线文件 279 行自 #76 未动）/ 桌面零改动（vitest 755 不变）。

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

### T-J1 outbox 状态闭环（WB-DEF-9）— **DONE（2026-11-05，与 T-P1-4/T-P1-5 同轮）**
- 修改文件：`jobs/outbox.py`（mark_completed/mark_failed）、`jobs/worker.py`（settle 时回写）。测试：test_outbox 扩展。复杂度：**S**。
- **实施记录（与设计的偏差，按主报告纪律回写）**：
  - 联动键 = `(topic, aggregate_id) == (job_type, target_id)`（`dispatch_pending` 去重所用的同一对），落库为 `outbox.mark_completed/mark_failed(session, job_type, target_id[, last_error])`——只翻转仍处 `dispatched` 的事件；未派发的 `pending` 行不动（属于未来派发），`last_error` 截断 2000 字。
  - **三个终态写入点全覆盖**（原设计只列 worker.settle 一处）：①`worker._settle` 成功/失败与 job 终态**同事务**收口；②`worker._claim` no_handler 终失败在 claim 事务内同步收口；③`reconcile._fail_job`（worker 失联终失败）同键收口。settle 的 stale-token/already-terminal 分支不写 outbox（归属新 claim 的 settle）。
  - 测试：test_outbox +2（completed 只收 dispatched/pending 不动/未知键零命中；failed 错误摘要 2000 截断）+ test_worker +3（成功/失败/no_handler 三条端到端：enqueue→dispatch→run_job→事件终态断言）。

### T-J2 handler 自动重试 + job 取消 API（域 14）— **DONE（2026-11-05，独立轮）**
- 修改文件：`jobs/worker.py`（指数退避≤max_attempts）、NEW admin 路由（POST /api/v1/admin/jobs/{id}/cancel，admin）。测试：test_worker/test_job_reconcile 扩展。复杂度：**M**。
- 注：重试落地时失败语义从「首败即 failed」变「退避重试至 attempts 耗尽」——outbox failed 收口（T-J1）必须只在最终失败分支触发，不得每败一次就翻转。
- **实施记录（与设计的偏差，按主报告纪律回写）**：
  - **重试**：`run_job` 异常分支改走 `_handle_failure`——决策事务先行（retry 分支提交后再走 `_settle`，后者自开事务且入口先 rollback）；可重试集合**复用 reconcile 的 `RECOVERABLE_JOB_TYPES`**（handler 抛错=副作用状态未知，只有声明过幂等跳过的类型才可重跑），非可恢复类型（automation.execute）维持首败即 failed。退避 30s 起步 ×2 封顶 900s（`_retry_delay(attempts)`）；重试行落 `queued`+未来 `available_at`，**outbox 事件保持 dispatched 不动**（T-J1 红线，专项测试钉住）。终失败（耗尽/非可恢复）才经 `_settle` 收口 outbox failed。
  - **due 重投面（设计未列，必要补码）**：重试分支只落库不投 redis——`available_at` 过期后的补投由 reconcile 新增第三候选 shape 承担（queued + available_at ∈ [grace_cutoff, due_floor)，`DUE_REQUEUE_DELAY_SECONDS=10` 迟滞窗把刚 requeue 已投递的正常行挡在门外），投递语义 at-least-once（`ReconcileResult.due_enqueued` 计数，行不动）；认领侧配套 `_claim` 新增 `not_due` 守卫（queued+未来 available_at 不认领），重复投递的早到条目被安全丢弃、不烧 attempts。
  - **陈旧身份映射防护**：candidates 查询加 `execution_options(populate_existing=True)`——同 session 残留旧行实例（内存 pending 态）会让 per-row 判定读到内存陈值走错分支（实测踩中：无防护时重试等待行被误判孤儿重排）；`_settle` 的 populate_existing 同款先例。
  - **cancelled 是真状态（设计未提，迁移 `d9f4a7c2e6b1` 35 rev）**：幂等取消要区分「已取消」（200 cancelled=false）与「跑完/失败」（409 already_terminal），failed+last_error 前缀区分不了；纯 CHECK 约束置换零数据迁移——active_key 生成列对一切非活跃态本就产出 NULL，cancelled 天然释放 (job_type,target_id) 槽位，无需重建生成列。`TERMINAL_JOB_STATUSES` 常量统一三终态；`_claim`/`_settle` 终态检查、`dispatch/maintenance` 24h 节拍门（cancelled 计入「已完结」）同步。
  - **cancel 路由**：NEW `jobs/admin_routes.py`（blueprint `/api/v1/admin/jobs`，注册 app.py，路由 297→298）——admin 门（service 层 role 判，agents 先例）；**不强杀**：running+活租约 409 `job_running`（线程杀不掉，强落终态只会白烧外呼；运营正确动作=停 worker 等租约过期），running+**过期**租约=worker 已死可安全接管（迟到 settle 被终态守卫拒绝，专项测试钉住）；幂等：重复取消 200 cancelled=false 且不追加留痕；同事务三面收口=job 行+`outbox.cancel_for_job`（**pending+dispatched 一并收口**——与 mark_failed 只收 dispatched 的刻意差异：留着 pending 行下一轮 dispatch 会为同键新建 job 复活已取消工作；取消后新提交事件照常新建 job 属合法新工作）+ `operation_events job_cancelled`（changes 只落 job_type/target_id/previous_status/outbox_closed，E7 纪律）。不进 api_catalog（平台运维面，evidence/本体治理同款边界）。
  - 测试：test_worker +7（退避字段与 attempt 计数/outbox 中间态保持 dispatched 红线/耗尽终失败才收口 outbox/瞬时故障恢复全链 completed/非可恢复首败即终/not_due 守卫不烧 attempts/取消后迟到失败不覆盖）+ test_job_reconcile +4（due 补投行不动/退避等待零动作/cancelled 永不被清扫/失败→due 补投→二跑成功闭环）+ test_outbox_models +1（CHECK 接受 cancelled 且槽位释放同键可开新 job）+ test_admin_jobs NEW 9 条（主路径三面收口+reconcile 不复活/幂等/终态 409×2/活租约 409/过期租约接管/pending 可取消/非 admin 403/404）+ test_migrations HEAD 推进 35。**零桌面改动**（vitest 771 不变）。

### T-P1-4 resolve_signoff 双闸（WB-DEF-2）— **DONE（2026-11-05，与 T-J1/T-P1-5 同轮）**
- 修改文件：`solutions/service.py`（can_manage+档位）。测试：负向用例（viewer+高 AI 档→403）。复杂度：**S**。
- **实施记录**：`_load_project_for_view`（can_view）→ `_load_project_for_update` + `_require_project_manager`（can_manage），与 `generate_agent_solution` 的「权限双层」同款先例；错误面靠既有别名 `SolutionServiceError = DocumentDraftServiceError` 直接面世 403 `forbidden`。测试：test_solution_signoff +1——viewer 成员 + 显式 `UserAIAccessGrant(system_operator)`（档位闸可通过）仍 403 `forbidden`（证明拦截者是 can_manage 而非档位闸）+ checkpoint 留 pending + 同项目 lead 照常拍板 200。

### T-P1-5 审批过期清扫（WB-DEF-3）— **DONE（2026-11-05，与 T-J1/T-P1-4 同轮）**
- 修改文件：`control/scheduler.py`。测试：test_scheduling 扩展。复杂度：**S**。
- **实施记录（与设计的偏差，按主报告纪律回写）**：
  - 先把过期翻转从 decide/`dsh_approval_status` 两处**内联重复**提取为唯一原语 `control/service._expire_approval(session, approval, *, reviewer, now)`（审批行 expired+version+1；挂 automation run → failed(approval_expired)；workflow 节点审批 → `_settle_workflow_node(approved=None)` 断链语义）——两处惰性判定改调原语，行为零变化。
  - `scheduler.sweep_expired_approvals(now=None, limit=100)`：pending+expires_at 到期批量经原语翻转，`with_for_update(skip_locked=True)` 与并发拍板互不阻塞；**接线在 `cli.py` scheduler 命令循环**（派单同拍，`expired_approvals=N` 回显；`--once` 同样生效）——backlog 原列文件不含 cli.py，此为必要接缝。
  - 测试落点：审批测试在 control 面而非 test_scheduling（那是工作台任务排期）——test_control_plane_api +1（未过期零翻转不动 → 过期翻转 1 且 run→failed/approval_expired → 幂等二轮零翻转）。

### T-OBS1 降级 chat 落审计（WB-DEF-4）— **DONE（2026-11-05 核验收口，由 #112 CR-006 覆盖）**
- 修改文件：`ai/ai_server_client.py`、`control/ai_tool_loop.py`（request_id 前缀 direct-chat-*，成功/失败均 record）。测试：test_ai_server_direct_fallback 扩展。复杂度：**S**。
- **核验记录（零补码）**：chat 入口 `control/chat.py` 直调 `execute_ai_prompt`——DSH 降级直连腿即其内部 `_degraded_direct_result`，已被 #112（CR-006 统一入账轮）补上成功/失败审计腿（used_fallback=True、provider_usage 计额入 `ai_monthly_token_budget` 月账本），WB-DEF-4 的两个病灶（不落 ai_call_audits / 月预算失真）均已闭环，测试见 test_ai_server_budget_audit.py。设计里的 `direct-chat-*` request_id 前缀不再需要：#112 的审计行携带 purpose + used_fallback + execution_id（=chat turn id 原样），区分度优于前缀方案。

## P2（交付编译与质量闭环）

### T-G1 任务/workflow 产物→门禁证据候选（域 4，WB-DEF-8）— **DONE（2026-11-04，分支 feat/v3-t-g1-gate-evidence-candidates）**
- 目标：审计 WB-DEF-8「任务级证据与门禁清单双口径脱钩」的候选闭环——任务完成且自带挂点与指针+指纹时，产物以**候选**身份出现在门禁面板，人工采纳走既有提交闸；绝不自动领用（claim_status=None 语义：候选不动领用态）。
- 原计划修改文件：task_service、gate_service；桌面 GateBoard。实际一致。
- **实施记录（2026-11-04）**：
  - **挂接语义（风险登记册「任务完成→证据候选」）**：`gate_service.attach_task_evidence_candidate`——只有 `status=completed` 的任务才产出候选（in_progress 挂指针只是「准备中」，产物尚不承诺存在）；三要素 gate ∈ G1-9 / evidence_uri / evidence_hash 缺一不挂；候选条目 {source_uri, content_hash（统一小写）, task_id, task_key, task_name, proposed_by_user_id, proposed_at}；同 (uri, hash, task_key) 幂等；上限 20 条丢最旧；门禁行未实例化时 `ensure_project_gates` 懒初始化后再挂。候选是建议性提示，**清单项 claim_status 与门禁状态机一概不动**。
  - **挂接点**：`task_service.update_project_task` 乐观锁 rowcount 通过后（stale 零副作用，同 T-E3 `_sync_task_evidence` 位置），按 effective 值（变更键取 scalar_values ∪ 未变更键取 ORM 属性——`synchronize_session=False` 下后者仍准确）判定，三要素任意更新次序凑齐即挂（完成在后/在前皆可）。create 路径任务恒 `not_started`，天然不触发。project 形参放 `Project | None`、None 即跳过——只为不新增 mypy 基线错误（调用点 `_require_project_view` 已挡 None）。延迟导入 gate_service（同包跨模块，沿 T-E3 延迟导入先例防初始化环）。
  - **采纳即闭环**：`submit_gate_evidence` 提交指纹命中候选（uri 相等且 hash 忽略大小写）即剪除对应候选；未命中者保留——采纳是候选唯一剪除入口。**零新路由**：候选随 `_serialize_gate` 输出（恒输出 `evidence_candidates`，旧行 NULL→[] 读时合并），采纳复用既有 `POST /gates/{key}/evidence`。事件 `gate_evidence_candidate_attached` 挂 gate 行，`GATE_EVENT_TYPES` 扩展并入门禁事件流。
  - **桌面 GateBoard**：清单项下「任务产物候选」区——候选出任务键/名+指针+指纹，下拉选目标清单项一键「采纳到清单」（走既有提交闸）；evidence 态也可补采纳（部分采纳流，`adoptable = 非 passed/conditional_pass`）；viewer 只读；`isGatesView` 可选键校验（旧载荷缺键合法，非法形状整板拒渲染 fail-loud）。
  - **DB**：迁移 `c7e1a9f3b5d8`（32→**33 rev**）——gates +`evidence_candidates` 可空 JSON 列，含 downgrade；纯增量零数据改写，候选是建议性数据、downgrade 丢弃属回退应有语义。
  - **实现偏差回写（原计划「任务/workflow 产物」）**：**workflow 产物候选挂起**——`workflow_node_runs.output_json` 是任意 JSON、无「source_uri + sha256」形状，强行把任意产物当证据会踩红线（门禁证据只收指针+指纹）；挂接函数已按通用形设计（收 uri/hash/来源粒度），待产物 schema 立项后零改挂入。本轮交付任务→候选闭环（任务侧证据形状 T-E3 已定且校验齐备）。
  - **测试**：NEW `server/tests/test_gate_evidence_candidates.py` 6 例（挂接+序列化契约+事件载荷 / 三缺一（未完成·缺挂点·缺指纹）不挂 / 次序无关+同指纹幂等（候选与事件都不重复）/ 采纳剪除+清单项 claimed+evidence_id（hash 大写提交验证忽略大小写）/ 部分采纳保留他者 / 拍板零感知（候选在场过门照常、未采纳候选不剪））；`test_migrations` HEAD `c7e1a9f3b5d8`。桌面 `gate-board.test.tsx` +3（渲染+采纳流走提交闸 / viewer 只读+旧载荷无键兼容 / 非法形状拒收）。
  - **口径**：105 表不变（列级增量）、迁移头 `d4e6f8a2c7b9`→**`c7e1a9f3b5d8`**（**33 rev**）、路由 **296 不变**（零新路由）、ENTRIES 94 不变、pytest **1847 收集 = 1841 passed + 6 skipped**（本轮 +6；相对上轮报口径 1832 的 +9 中 +3 为 #93 skill 两闸用例）、vitest **755**（+3）、mypy 基线不变（新代码零新增）。改 server + 新迁移 ⇒ rebuild 后必 `alembic upgrade head`。

### T-W7 workflow 节点产物→门禁证据候选（域 14，WB-DEF-8 workflow 腿）— **DONE（2026-11-05，立项合同 `docs/architecture/workflow-gate-evidence-candidates-v1.md` 同日实施）**
- 目标：清偿 T-G1 §实现偏差回写的挂起项——`output_json` 任意 JSON 不强行当证据；产物经**运行时保留键 `gate_evidence`**（生产方自带 source_uri + sha256，平台永不自动派生指纹）在节点 succeeded 同事务挂入 `gates.evidence_candidates`（复用 T-G1 通用挂接形），claim_status 恒 None，采纳仍走真人提交闸。
- 修改文件：`workflows/executor.py`（call/skill :725 与 agent :1194 两处成功点读标记）、`projects/gate_service.py`（新原语 `attach_workflow_evidence_candidate`，≈40 行，复用 ensure_project_gates / MAX 上限 / 事件）；坏标记跳过 + 事件 `gate_evidence_candidate_skipped`。
- 契约要点：dedup=(source_uri, content_hash, `wf:{run_id}:{node_key}`)；attempt 重试同指纹幂等、换指纹新候选并存（CR-019 代际语义）；`captured_from=workflow_node:{run_id}:{node_key}`（T-E3 已预留前缀）；候选行 `source_kind: "task"|"workflow"`（旧行读时缺省 task）；**零 DDL 零迁移零路由**（v1 不预写 project_evidence 一等表——偏差已回写 workflow-dag-v1 §4 注记）。
- 测试：test_workflow_executor / 候选面扩展（验收 12 八段：出现/幂等/换指纹并存/坏标记跳过/无标记零副作用/失败路径不登记/采纳剪除回归/缺键兼容）。桌面 GateBoard 来源徽标另开 S 轮。复杂度：**M**。前置：T-G1 / T-W3 / T-W4（均已 DONE）。
- **实施记录（2026-11-05）**：`gate_service.attach_workflow_evidence_candidate`（四形状校验 → 坏标记 skipped 事件挂 project 目标 → ensure_project_gates 懒初始化 → dedup（含哈希大小写归一）→ 挂行（§5 shape 逐键）→ attached 事件挂 gate 目标）；executor `_attach_gate_evidence_marker` 接线 `_settle_node_success`（call/skill/agent 共用成功点）与 `settle_approval_node` 批准分支（现合同 output 无标记=零副作用，接线为未来包装层零改生效）——同事务原子（节点成功与候选一并回滚）；非对象标记在 executor 层拦下（skipped 挂 workflow_run 目标）；`_serialize_gate` 的 evidence_candidates 读时缺省 `source_kind="task"`（旧行不回填，沿 T-E2 先例）。**与立项稿偏差=零**：D3 的 captured_from 仅属未来一等表写入路径（D4 裁决 v1 不预写 project_evidence），故候选行不落该键。测试新文件 `test_workflow_gate_evidence.py` 7 例（失败路径与恢复并成一例）+ 邻近回归（candidates/gates_api/executor 49 例）全绿；`event code` 侧 `gate_evidence_candidate_skipped` 已入 GATE_EVENT_TYPES（feed 可见）。**桌面挂账销账（2026-11-05 T-UI1 核销轮）**：GateBoard 候选来源徽标已落地——候选载荷扩为 `source_kind` 判别联合（task 旧行读时缺省 / workflow 带 run·节点键·label），分形守卫顺带修复 T-G1 守卫硬性要求 task 三键致 workflow 候选行整板拒载的潜伏 bug；workflow 行「工作流」徽标+出处行、采纳走既有提交闸、uri>500 可见禁采；vitest +4（→771）。

### T-G2 template_hash 漂移呈现（WB-DEF-5）— **DONE（2026-11-04）**
- 修改文件：gate_service._serialize_gate（比对存储值 vs 当前 gates.json sha256，响应加 template_outdated: bool）。测试：test_gates_api。复杂度：**S**。
- **实施记录（与设计的偏差，按主报告纪律回写）**：
  - 按设计落`_serialize_gate`：`template_outdated = bool(gate.template_hash) and gate.template_hash != _gates_file_hash()`（冻结哈希 vs 现行镜像内 seeds/gates.json 的 sha256，后者进程级缓存——文件烘进镜像只读）。**NULL=未知出处判 false 不误报**（列可空；迁移 `f7a2c9e4b1d3` 后实际不再有 NULL，语义只为防御）。
  - **漂移即存量事实**：回填常量 `f52afe88…` ≠ 现行文件哈希 ⇒ 既有项目 9 门全量 true，符合风险册 F-2 预期（呈现即修复，不做自动刷新实例——清单冻结语义不动，是否重挂新模板留给人工轮）。
  - list/GET、证据提交、拍板响应共用同一序列化器四调用面自动携带；桌面 GateBoard 类型守卫只验必填键零破坏（桌面呈现消费留待 UI 轮，本轮范围=后端字段）。
  - 测试：test_gates_api **+1**（懒实例化首访全不漂移 / 冻结哈希改写 → true / NULL → false；注意**首个 gates 访问才触发懒实例化**，前置 UPDATE 会落空——先 GET 再改哈希复 GET）；pytest **1863 收集（1857 passed + 6 skipped，本轮 +1）**——基线即 fork/main `6cccedb` 实测 collect-only 1862（1856+6s）：T-R2 记录 1855 是其自轮 `e1568d6` 运行面（基于 ef34ce0 不含 #98），squash `6cccedb` 基于 `e3b8350` 并入 #98 goal-c3 的 +7 测试（G8-stop ×2 / 报价数值闸 ×3 / signoff 并发 ×2），diff 实测归因闭合。零迁移（head `c7e1a9f3b5d8` 不变）/ 路由 296 不变 / ENTRIES 94 不变 / mypy 基线 279 不变（104 distinct）/ 桌面零改动（vitest 755 不变）。

### T-D1 文档血缘补洞（WB-DEF-6/7）— **DONE（2026-11-04）**
- 修改文件：`documents/snapshots.py`（confirmed_research_values 加 revision_id 键）、`documents/ai_content.py`+`generator.py`（request_id 落 generation job 行并回写版本）、快照含 gates 摘要。
- 测试：test_document_snapshots 扩展（可反查 revision 与 ai_call_audits）。复杂度：**M**。
- **实施记录（与设计的偏差，按主报告纪律回写）**：
  - **WB-DEF-7（revision_id）**：`confirmed_research_values` 每表单字典新增 `revision_id` 键（指向被采用的最新 confirmed revision），血缘键先落位、答案随后——扁平布局不变，`research.<form>.<field>` 占位符解析零破坏；极端同名模板字段会覆盖血缘键（文档内容优先，取舍在案：模板循环迭代表单字典会看到该键）。快照即冻结答案出处，反查 `session.get(ProjectResearchFormRevision, id)` 直达。
  - **gates 摘要**：快照新增 `gates` 段——每门 `{gate_key, status, decision, submitted_at, decided_at}`，按 gate_key 排序；**有意不携带**清单明细/证据指针/候选（文档需要「生成时刻门禁走到哪」，不是门禁第二份镜像）；门禁未实例化项目为 `[]`。
  - **WB-DEF-6（request_id）**：`generate_document_fields` 增 keyword-only `request_id` 参数（缺省自铸兼容旧调用）；`generator._build_context` 在**新鲜 AI 分支**铸 `document-content-{uuid4()}` 传入并冻结进 `content_snapshot_json["ai_request_id"]`（与 `ai_fields` 同处，D3/E1 来源真值伴生）；`handle_document_generation` 随后 `_stamp_job_ai_request_id` 把同值落 `document_generation_jobs.ai_request_id` 新列（迁移 `e2c6a8f4d1b3`，33→34 rev，可空、downgrade 直删）——job 行可直接 join `ai_call_audits`，版本行经 content_snapshot 反查。
  - **幽灵血缘防线（设计外新增，测试驱动）**：初版在资格判定前铸 id，非 AI 文档（无机会范围的 PoV/SOW、非 PoV/SOW 类型）会冻结无审计行对应的 id。修复=资格判定提为 `ai_content.ai_content_applicable(document)` 单一谓词，`generate_document_fields` 守卫与 `_build_context` 铸造分支同源——只有真正发起供应商调用的文档才铸 id。复用首代冻结字段的再生成（D10）不重铸，血缘恒指首代调用；失败路径 id 随事务回滚（失败版本无内容可追溯）；方案导出（has_saved_solution）无 AI 调用故无 id。
  - 桌面零改动：桌面只消费 `field_overrides`，不解析 `source_snapshot_json`/`ai_request_id`（`_serialize_version` 的 content_snapshot 全量外泄面早已存在，新键纯增量）。`ai_request_id` 不进 api_catalog、零新路由。
  - **测试**：test_document_snapshots **+2**（最新 confirmed revision 指向+反查 / gates 摘要形状+排序+无清单键）+ 既有全量用例扩 2 断言（revision_id 类型、空 gates）；test_document_generator **+2**（AI 血缘闭环：伪造客户端捕获 request_id → 版本冻结+job 落列+`ai_call_audits` 反查+幂等再生成不重铸 / 非 AI 生成 job 列保持 NULL 且 content_snapshot 无键）；`test_migrations` HEAD `e2c6a8f4d1b3`。
  - **口径**：105 表不变（列级增量）、迁移头 `c7e1a9f3b5d8`→**`e2c6a8f4d1b3`**（**34 rev**）、业务路由 **296 不变**（零新路由）、ENTRIES 94 不变、pytest **1871 收集 = 1865 passed + 6 skipped**（本轮 +4；基线 `c8aa08a` 实测 collect 1867——#103 goal-c4 较 #102 的 1863 +4）、mypy 基线 **279 不变**（新代码零新增）、桌面 vitest 765 不变（零改动）。改 server + 新迁移 ⇒ rebuild 后必 `alembic upgrade head`。

### T-C1 Delivery Compiler 最小闭环（P2 尾）— **DONE（2026-11-05）**
- 目标：change_set confirmed 后的"编译预览"：从 confirmed 本体+模板生成方案草稿骨架（复用 solutions /skeleton 路径）与 workflow 定义草稿（dag_json 模板化）。
- 前置：T-O3、T-W1。修改文件：NEW `server/src/fde_api/workflows/compiler.py`（纯函数：本体→dag 模板）。测试：compiler 快照测试。复杂度：**M**。
- **实施记录（与设计的偏差，按主报告纪律回写）**：
  - **输入合同**：`compile_delivery_preview(change_set, *, industry_template, gates, research_skill_ref, approval_capability="workbench.write")`——change_set 取 serialize_change_set 形状且 status 必须 confirmed（编译预览只对已坐实本体负责）；industry_template 取已发布行业模板版本（industry_name/version_number/modules，None=无匹配走待补）；gates 沿 T-D1 `_serialize_gates` 形状（只消费 gate_key/status/decision，坏行跳过不炸整个预览）。
  - **「复用 /skeleton 路径」的落法**：复用其**文本合同与六段布局**（TEXT_FIELDS 七键、限长同尺 160/40000/16000、每段保留「待补」、模块按 sort_order 排序），不跨包 import solutions 私有助手——骨架 payload 经合并运行期 opportunity_ids 后原样可过 `_normalize`（测试动态钉死），落库走 POST /solutions 人工端点；溯源行随 design_markdown 头部落档（变更集标题·确认时刻·采集来源），另附 provenance 段（agent_trace 式逐字段来源指认）。
  - **dag 三节点裁决**：调研=skill（**ref 注入制**——published 白名单在 DB，纯函数不查库，沿 validate_dag 白名单注入制先例；SKILL_REF_PATTERN 与 APPROVAL_CAPABILITIES 复用 definition_service 常量前置校验）；方案=call `solutions.create`（编译期骨架字段全量携带=「模板化」本义，唯一运行期字段 opportunity_ids 留 `{{research_brief.opportunity_ids}}` 占位——执行器整值替换原类型不字符串化）；审阅=human_approval（capability 白名单校验，system.* 不开放）。`solutions.create` 目录 effect=write_db ⇒ rule 9 不触发（告警面只盯 external），审阅节点按设计保留为人工收口而非 rule 9 补丁。
  - **骨架语义映射**：create/update 术语入「已确认本体」段（update 以 new_term 为准并标注原名）；**指标型术语（term_type=metric）入验收标准候选**（本体即验收口径来源）；merge_terms 入风险与依赖段（旧名不再使用=交付物措辞依赖）；register_relation_type 只进 provenance 计数不产骨架行。
  - **零路由零 DDL**：编译预览无 HTTP 面（接线待后续编排/UI 轮）；输出确定性（不读时钟/随机源）支撑整树快照测试。
  - **测试**：NEW `test_delivery_compiler.py` 6 例（整树快照 / 三节点 dag 真实目录白名单全绿零告警+拓扑序 (research, solution, review) / 非 confirmed+五类坏载荷点名拒绝 / 无模板无门禁待补回退+坏门禁行跳过 / 坏 skill ref·capability 拒绝 / 骨架 payload 过 `_normalize` 合同）。
  - **口径**：105 表不变（零 DDL）、迁移头 `e2c6a8f4d1b3`（34 rev）不变、业务路由 **296 不变**（零新路由）、ENTRIES 94 不变、pytest **1877 收集 = 1871 passed + 6 skipped**（本轮 +6；基线 `1ef3a42` 实测 1871）、mypy 基线 **279 不变**（新代码零新增）、桌面 vitest 765 不变（零改动）。改 server（零迁移）⇒ rebuild 三镜像。

### T-I1 本体变更影响分析（域 2 §5 用例 6 扩展）— **DONE（2026-11-05，分支 feat/v3-t-i1-ontology-impact，squash 合并至 fork/main）**
- 目标：impact_of_term(term_id) → 引用它的 subjects/links/forms/gates 证据列表。前置：T-O1。复杂度：**S**。
- **实施记录（与设计的偏差，按主报告纪律回写）**：
  - **引用合同 = 名字域纽带**：fde-v2 设计的「引用方（研究客体、表单、门禁）只引 term_id」未随融合裁决落地（吸收思想不引实现）——当前 schema 无 term_id 外键，T-O4 导入去重/术语治理的真实纽带是「一个名字一个概念」（UNIQUE(project, term) + UNIQUE(project, alias)）。影响分析据此落为**精确名匹配**：subject.name 命中生效名字域即引用该概念；纽带是唯一性不是相似度，子串/大小写变体不算命中。
  - **生效名字域 = 血缘闭包**：请求行沿 canonical 链到根（merge_terms 已保证链一跳化，防御性走到底）∪ 全部并入该根的行；名字 = 根规范名（via=term）∪ 血缘内别名（via=alias：转写来源名归保留行、来源自有别名留在来源行——逐名 term_id 溯源）∪ 非根行历史规范名（via=alias 兜底，转写被占位防御跳过时不丢名）。对并入行发起查询 = 查其存活概念的影响面（term 段原样返回请求行，resolved.canonical_term_id 指根）。
  - **三面清单**：subjects（命中主体：类型/状态/merged_into/matched_via/matched_term_id）→ links（**端点命中主体的邻接边**——设计 §5.6「引用该 term 的 links」的落法：引用主体改名，边语义随动；端点名随行补齐）→ forms（命中主体名下表单 + 现行修订状态）；counts 汇总；全清单确定性排序。
  - **gates 面偏差**：backlog 目标句的 gates 一词按验收权威 O-6（impact_of_term 返回引用它的 subjects/links/forms）落为三面——门禁清单是 gates.json 冻结模板文本（template_hash 钉死，T-G2），无任何术语名表面；为 gates 发明术语引用会踩门禁铁律「工程层不得发明方法论层没有的东西」。未来若门禁清单项引入术语挂接（如 G? 清单项挂 term_id），影响分析可零改扩第四面（返回形状未预留死键）。
  - **+1 只读路由**：`GET /projects/{id}/ontology/terms/{term_id}/impact`（can_view）——设计 §4 未列本条（设计只说「服务层可查询」），开 HTTP 面是为让人工评审在变集拍板前可达（同 T-O2 retire 先例：为让验收在人工路径可达而补路由），桌面 T-UI1 GlossaryPage 是预期消费方；**有意不进 api_catalog**（沿 T-O3 纪律，既有钉子测试 `/ontology/terms` 路径断言自动覆盖）。
  - **跨包 import 方向**：ontology.service → research.models（models 叶子模块）——方向恒 research.*_service → ontology.service → research.models，无环（research/__init__ 仅 docstring）。
  - **前置热修（CI 解堵，非 backlog 项）**：rebase 后首轮 PR CI 红，定位为 **goal-c8 CR-002 首版回归**（#109）：conftest `_current_alembic_stamp` 探测在全新库（CI service container 无 alembic_version 表）吞 UndefinedTable 后未回滚——持锁连接留在 aborted 事务，会话末 `pg_advisory_unlock` 必撞 InFailedSqlTransaction → server-tests 整列红（#109 PR-head 即此签名，红仍被合入；本地共享库戳已知故绿，具隐蔽性）。修为「探测吞错即回滚 + 解锁前保险回滚」两行（会话级 advisory 锁不随回滚释放）；回归钉 `test_stamp_probe_missing_table_rolls_back_connection`（search_path 复现缺表探测，A/B 验证无修复红/有修复绿；**教训：不能用 RENAME alembic_version 复现——会话 fixture 持锁事务持有其 ACCESS SHARE 直至会话结束，会自锁死等**）。
  - **测试**：NEW `test_ontology_impact.py` 6 例（名字域四路全命中+子串不命中+三面清单与 counts / 并入行查询解析到 canonical / 未知与跨项目术语 404 / 零引用空面 / HTTP 面+访问控制 / 红线钉子不进 catalog）+ 热修回归钉 1 例。
  - **口径**：105 表不变（零 DDL）、迁移头 `e2c6a8f4d1b3`（34 rev）不变、业务路由 **296→297**（+1 只读，不进 api_catalog）、ENTRIES 94 不变、pytest **1884 收集 = 1878 passed + 6 skipped**（本轮 +7；基线 `8f10771` 实测 1877）、mypy 基线 **279 不变**（新代码零新增）、桌面 vitest 765 不变（零改动）。改 server（零迁移）⇒ rebuild 三镜像。

### T-UI1 桌面控制台三页（域 16）— **DONE（2026-11-05，核销轮——零补码）**
- WorkflowConsole / GlossaryPage / SkillVersionsPage + vitest 用例。前置：对应 API。复杂度：**M**。
- **核销记录（2026-11-05）**：三页已随 T-W6（#88）同名全量交付（`workflows/WorkflowConsole.tsx` / `ontology/GlossaryPage.tsx` / `extensions/SkillVersionsPage.tsx` + vitest 5/6/7 例 + typecheck 绿，本轮基线复核 767 全绿）——按「已由先导轮兑现」销号，零补码。同轮附带清偿 T-W7 桌面挂账：GateBoard 候选来源徽标（`source_kind` 判别联合 + 分形守卫，修复 workflow 候选行整板拒载的潜伏 bug；vitest +4 → 771），见 T-W7 实施记录尾注。

## P3（高级自主化——**2026-11-05 立项完成；同日状态轮清偿：①②仍冻 ③PARK ④三道闸齐备；同日评估报告轮落定：§4.4 四问全答、可降级集合=∅、本报告不开放——P3 四项全部定案收口，余=数据回流+评估复审轮**）

四项合同见 **`docs/implementation/v3-p3-高级自主化立项-v1.md`**（各节含立项依据/已落地基线/评估问题清单/非目标/解冻条件/风险；全局红线与范围外=RAG 不立项、在途开源借鉴调研不预支）。解冻前不开实施轮，评估报告轮自身也须先过解冻闸。**状态轮报告=`docs/implementation/v3-p3-四项状态与闸清偿-v1.md`**（2026-11-05，含 §16 用例族 32 例逐项核对表、责任主体机制化方案、活库数据闸实测；裁决按推荐项拍板、逐项留痕可推翻）：

- 多 Agent 自适应编排（域 6 DEFER 观测项）——立项 §1；进程内团队拒绝理由（主报告 §19-7）是常量；观测=`agent_runs.fallback_level` 分布，**真实 run 数据积累是解冻闸**——状态轮活库实测 `agent_runs=0`/`workflow_runs=0`，闸未动，**仍冻**。
- 基于运行反馈的 Skill 改进（usage 统计→建议）——立项 §2；T-S2+CR-013（#115）数据正确性已闭环；**状态轮裁决：失败面维持「失败不计」对称语义不新开核算维度**（消费量=0 无建议需求；失败证据走 ai_call_audits/operation_events 人工审计面；重审触发器=首个真实改进建议需求；agent-policy §2.1 已回写）；**双面消费量闸未过**（活库 skill 消费事件=0），仍冻。
- 业务规则推理（ontology_rules 立项评估）——立项 §3；「无消费方不建空壳」维持；**状态轮裁决：ontology_rules 维持不建 PARK**（两候选消费方均「可做非被需要」——risk≥3 规则已内嵌且被 `test_catalog_effect_risk_invariants` 钉住、T-C1 编译校验无规则输入需求；重开触发器=第二条 risk≥3 规则需配置化 / T-C1 规则输入需求 / 业务点名规则）；**规则 9 强制化悬置线销号：维持告警**（执行层已硬闸——workflow call external 必 awaiting_confirmation 诚实失败 + DSH agent 节点走审批回调，定义期强制只省一次诚实失败的提前量，「P2 enforcement wave」不做）。
- 有限自动执行开放评估（依赖 P0-P2 验收全绿）——立项 §4；**三道闸齐备（2026-11-05 状态轮清偿）**：T-J2 落定（#116）✅ + §16 用例族核对表全绿（32 例：30 直接绿+W-9 本轮补钉变异验证+W-3 input_schema 后腿裁决不建）✅ + 责任主体机制化方案成形（审批链人签五要素在表+系统自主动作封闭白名单，无结构性缺口）✅ → **评估报告轮解冻可排期**（余项=边界梯度分类学〔写类永不降级红线维持〕+调研会话衔接；运行证据待首批真实 run）；写类 external 免事前确认=红线级非目标。**评估报告轮已落定（同日，报告=`docs/implementation/v3-p3-评估报告-有限自动执行-v1.md`）**：三面目录实测（api_catalog 94 + MCP 17 + A 轨审批硬白名单 service.py:867）→ 八档分类学 G0–G7+S；**现役可降级集合=∅**（G3 产物出具两条/G5 不可逆写五条裁决不降级留痕可推翻；G6 发信类现役唯一成员 `file_send_wechat` 收件域封闭+事前密码确认红线钉死；G7 写外呼/付款构造性零条目）；§1.5 准入五要素模板（全 PROPOSED）+ §2.2 取数口径四条 + §3.2 责任主体断言 SQL 三条先行（活库审批行=0，首批真实 run 后评估复审轮）；调研会话《自动化运行-DSH替代可行性评估》已落盘、四条结论消费同向（P0 维持现状=本报告不开放互证）；**闸态变更数=0，零代码零配置零迁移**。

## 开源借鉴清单登记（2026-11-05 消费登记轮 B#1–B#34 ＋ **2026-11-06 评审补登记 B#35–B#40**，登记轮零代码。当前：P0 先行批表 10 项 ✅ 已实施（#128~#131），其余按逐条状态标注——PROPOSED/冻结/封存/修复项）

**来源**：调研会话《开源项目借鉴总览-2026-11-05》（横评**九项目**：fde-v2 / agent-autoloop / agnes-harness / giip-fde-agent / sample-fdep-mcp-server / fde-gym / FF-FDE-Delivery-Workbench / fde-skills / Frank-FDE-Skills）及分报告——`docs/audit/` 下**在途未提交产物**（落定回写归调研会话，本轮只消费登记、不代提交、不复制其证据链）。登记编号沿用总览原文 **B#1–B#40**；条目细节、来源 file:line、分项目裁决以总览原文为准，本节只挂决策骨架。

**登记状态**：全部 **PROPOSED**——实施须另开轮并走既有流程（feature 分支→PR→4 CI job→合并→实现偏差回写本节）；「登记≠排期≠默认实施」。

> **2026-11-06 多专家评审后的登记补正**（详见 `docs/audit/开源项目借鉴总览-多专家评审-2026-11-06.md`，P0 4／P1 11／P2 6）：
> ①**B#28 落点列口径订正**（见下表，原写「必填＋新增 revision 列＋`project_gates`」与实际实现不符，照做会新增冗余列并毁兼容契约）；
> ②**补登记 B#35–B#40 六行**——此前六条**零载体**（已拍板却无执行载体），其中 **B#35 改判修复项**（把许可硬条款逐字落进 `AGENTS.md` 与本节，是闭环零载体的最短路径）；**B#38/B#39 冻结**（许可红线未落地即被当作门禁的负向实证）；**B#25 改「封存（永锁）」**（触发条件已被 Q1/Q3–Q7 逐条否定）；
> ③**B#23/B#24 前置改「四条件触发式解封」**（客户量化验收线诉求成文／可回放 KPI／`kpi_oracle` 责任人／只读回放 CI 静态断言），非单纯「Q1–Q3 拍板」；
> ④**B#36/B#37 加硬判据**：不得逐字搬 fde-skills 的 12 类类目名/规则文本；**法务结论（Q18）前不得引用 fde-skills 任何正文**；
> ⑤**状态口径纪律**：本节一律用**逐条编号**表述状态，**不采信任何汇总分母**（`CHANGELOG.md:48`「11 条」vs `AGENTS.md:32`「12/13」、35 vs 36 rev 均属 fork/main 自身口径漂移）。

### P0 先行批（总览建议 ≈2–4 人日 + 文档；**实施前须拍板**）

| 编号 | 名称 | 形态 | 落点 | 闸 |
|---|---|---|---|---|
| B#1 | 跳数熔断（workflow 自触发链 hops 上限） | 代码+**迁移** | `workflow_runs` 加 `hops` 列 + 执行器入口 >8 → failed(`hops_exceeded`) + 留痕 + 通知；拍板重投**继承不清零**用例 | **✅ 已实施（P0 代码级子批 #130）：`workflow_runs.hops` 列（迁移 `b2e8f4a6c9d3`）+ `MAX_RUN_HOPS=8`（resume 重投口 409 拒绝+入口 belt honest failed）+ 双用例（逐代累加继承不清零/字面量播种变异敏感）** |
| B#2 | 回执「写错不重做」 | 代码 | `agents/service.py` 增 `succeeded_but_receipt_invalid` 终态；与 V8 失败终态拒同键重跑的交互写清；repair 按 CLI 能力降级 | 零迁移；zcode 会话能力未核实（待澄清 6.1-4）。**✅ 核心已实施（#130，收窄面）：`ManifestOutputScanner.receipt_state` 四态分类（ok/no_output/files_without_manifest/manifest_invalid，Protocol 不破）经 `RunResult.receipt_state` 入 `_finalize`——completed+exit0+零声明产物且回执面损坏 → `succeeded_but_receipt_invalid` 独立终态（不进 FAILED_STATUSES ⇒ retry_run 拒同键重跑）+ `agent_runs.status` 列 String(24)→(40)+CHECK 扩（同迁移）+ 五用例（终态/合法零产物不误伤/C-1 兼容钉/干净对照/scanner 五态）；**实施中发现并修正两处计划缺腿**（教训 41）：①首版把声明产物校验失败也折入新终态撞 C-1「failed→retry 恢复」既有合同（I-1 幂等复用同撞）→ 收窄到回执面损坏；②合法零产物任务须与回执缺失可区分 → adapter 面 receipt_state 信号。repair 按 CLI 能力降级档待 zcode 会话能力核实后评估** |
| B#3 | 审查不执行被审代码（红线） | 文档 | AGENTS.md 红线 +1（未来上 AI 审查时加 CI 断言） | 立规≈0 成本。**✅ 已落盘（P0 文档级子批 #128：AGENTS 红线节第 7 条）** |
| B#4 | purity 架构测试 | 测试 | pytest：workflows/ 不 import control service/routes 层（环导入实证已存在）、kernel 类模块不读 os.environ/flask、无产品硬编码 | 成本=1 测试文件。**✅ 已实施（#129 `tests/test_architecture_purity.py` 四断言：双向环防线/control.service 延迟导入惯例固化/内核零 env·flask/零「蔡工」字面量——落地前实测全绿）** |
| B#5 | 审批退避提醒 + SLA 统计 | 代码 | 挂起审批按退避序列提醒（复用任务中心，勿新开外发通道）+ 挂起时长统计进 run 详情 | 零迁移。**✅ 已实施（#135：`scheduler.remind_pending_approvals` 与派单/过期清扫同拍——10m→1h→4h→24h 退避序列 catch-up 补发，账本=result_json["approval_reminders"] 零迁移，幂等封顶 4 级；审批序列化加 pending_seconds/reminder_count/next_reminder_at（任务中心呈现面，零新外发）；workflow run 详情 waiting_approval 态带 waiting_approval_seconds（锚=updated_at）；五用例+变异五连〔口径漂移/单发退化/域外触碰/秒数归零/锚点漂移〕）** |
| B#6 | 状态归属与对账框架 | 文档+测试 | 《状态归属与对账》自检清单（project_evidence/ontology_*/workflow_*/documents 四层）+ pytest 断言（候选 confirm 前不物化/快照可重建/指纹不一致拒绝） | 零迁移。**✅ 已实施（#131：`docs/architecture/状态归属与对账-v1.md` 四层归属总表+C1–C10 自检清单 + `tests/test_state_ownership_reconciliation.py` 六跨层钉——候选两腿挂接后 project_evidence 零行且清单不动/物化唯一入口/引用-实体逐位一致/版本行指纹可重算（v2 发布不污染 v1）/文档快照剥 captured_at 后逐位确定/ontology base_conflict 零物化；六钉逐一变异验证红→还原绿；既有单面专测映射见文档 §2）** |
| B#21 | 交付效果评测协议 v0（uplift 算分口径） | 文档 | `docs/`：result 字段清单 + G9「上线门」exit_condition「验收线达成」挂接；**不引入任何代码** | 无 oracle 不得出分（`insufficient_data`）；Q1–Q3 影响深度。**✅ 协议已落盘（#128 `docs/architecture/交付效果评测协议-v0.md` §1/§2/§5）；gates.json 种子挂接=接线项归代码级子批同窗口；✅ 接线已实施（#131：G9 exit_condition 挂 §5 冻结公式 `验收线达成 ≔ uplift_bounded ≥ 0.8 ∧ incidents = ∅ ∧ 三锚四反例全过` + insufficient_data 边界 + 协议指针，原五项出门口径逐字保留；种子重生成覆盖由钉 6 守护；存量 Gate 行不改（T-G2 template_outdated 呈现漂移属设计））** |
| B#22 | 门禁判据升格（三锚点+四类反例） | 文档 | 与 B#21 同一份文档一章 + pytest 断言模板（先成文不接线）；实施落点=B#11（不另立判据）；**阈值须我方数据校准，不得照抄上游** | 同 B#21。**✅ 已落盘（#128 同文档 §3；接线归代码级子批）** |
| B#27 | DSH 适配层决策记录 | 文档 | 写明 `fde-dsh-v1` 是自定协议、官方源码零命中端点；若启用 `FDE_DSH_*` 须自写适配层（lock 八字段+三方合并升级法）；**维持「当前不装」裁决** | 零代码。**✅ 已落盘（#128 `docs/architecture/DSH-适配层决策记录-v1.md`）** |
| B#28 | 门禁精确 revision CAS + 生命周期版本隔离 | 代码+**迁移** | `decide_gate` 增 `expected_revision` ＋ `gates` 加 `lifecycle_version`；版本交叉 409 不推进 version。**【2026-11-06 落点列口径订正】**：`expected_revision` **可选**（非必填，缺省＝旧客户端兼容、version 照常推进）、revision **复用既有 `gates.version`**（`VersionedMixin` 在位，**零新增 revision 列**）、**仅新增 `lifecycle_version`**、表名 `gates`（模型在 `workbench/models.py`）——照旧口径施工会新增冗余列并毁兼容契约 | **✅ 已实施（#130，按我方 schema 适配）：`expected_revision` **可选**（缺省=旧客户端兼容，version 照常推进）+ 复用既有 `gates.version`（VersionedMixin 在位，总览 revision ≡ 该列零新列）+ 新列 `lifecycle_version`（同迁移 `b2e8f4a6c9d3`）+ 行锁（_load_gate with_for_update 既有）+ 版本复核 409 `gate_revision_conflict` + 四用例（落后冲突零变更/命中生效推进/缺省兼容/形状 400）；**桌面 expected_revision 接线维持 blocked**（`GateBoard.tsx` 在品牌轮冻结区，无 ETA/owner，判据＝品牌轮 PR 合入） |
| B#29 | 验证/验收合同契约（五点） | 文档 | 并入 B#21 一章（G8 conditional_pass / G9 有条件接受语义对齐）；schema 落 B#23 夹具期 | 与 B#21 同期。**✅ 已落盘（#128 同文档 §4）** |
| B#35 | 技能成熟度口径 + 来源/许可登记 | 文档 | AGENTS.md 技能约定段写「published＝治理通过 ≠ 现场验证」（不换状态值、不改发布四闸）；外部技能导入登记落 `docs/audit/`（字段沿用 `SOURCES.md`）。**【2026-11-06 由 PROPOSED 改判修复项】**：本条的价值在于把许可红线从草稿搬进权威基线——**须将 AGENTS.md 新增红线第 8 条（五项硬条款：抽象概念可用／结构化表达禁写入本仓含改数字·换措辞·重排的等价复现／PR 附来源对照表声明独立重写且评审否决等价复现／快照日期与失效判据（远端出现 LICENSE 或 HEAD 变动即复核、停更超 30 天失效重核）／legacy 许可混置须逐件核）逐字落进 `AGENTS.md` 与本节** | 零代码零迁移。**✅ 已实施（#133，技能契约轮 2026-11-06 核实销号）：AGENTS.md 红线第 8 条（五项硬条款逐字）+本节登记同 PR 合入——修复项产出（PR 合入）达成；B#36 实施时按本条红线执行「我方独立设计」** |
| B#36 | 技能结构化契约最小 5 组字段 | 文档 | `SkillVersion.manifest_json` 增可选扩展键（**免迁移**）＋ `.agents/skills/` 新技能 front matter 建议；存量 4 个 runbook **不回填**；**禁止把 `instructions_text` 拆成 YAML 双权威**（DB 仍是唯一权威）。只取 **5 组语义**，**不取 21 字段全必填、不设 `additionalProperties:false`** | 零迁移。**✅ 已实施（技能契约轮 #140，与 B#37 同批防口径漂移）：契约=`docs/architecture/技能结构化契约-v1.md`——manifest_json 五组可选扩展键（use_boundaries 适用边界/effects 副作用声明/evidence 证据口径/verification 验证状态（非状态注记）/failure_behavior 失败诚实，各组 ≤2 键、值类型 str/bool/list[str]），语义锚全部指向我方既有语义（评测协议 §4 五点风格/T-R2 effect 分面+P3 分类学/证据红线+T-G1·T-W7/B#35 成熟度/B#2 失败诚实）；基线键 version/source/read_only 不动+read_only×effects.write_actions 自洽律；键空间闭合枚举（{基线三键}∪{五组键}）防漂移、未知键不拒绝（不设 additionalProperties:false）；`.agents/skills/` front matter 建议=name+description 必填+契约键平铺点路径，存量 4 runbook 不回填、内置种子 manifest 不回填；禁 instructions_text 拆 YAML 双权威（DB 版本行唯一权威）。**硬判据履行：全部字段/类目名/规则文本为我方独立设计撰写，零 fde-skills 正文引用（Q18 前维持）** |
| B#37 | 技能自洽校验落 pytest | 测试 | 新建 `server/tests/test_skill_contract.py`，对 `.agents/skills/` 与 `control/builtin_skills.py` 种子清单做静态校验，挂现有 `server-tests` job（**不新增 CI job**）；**不引入 PyYAML/jsonschema 依赖**（标准库 + pytest）；生成物一致性改成「种子清单 ↔ DB 行」断言 | ≈1–2 人日。**✅ 已实施（技能契约轮 #140，与 B#36 同批）：新 `server/tests/test_skill_contract.py` 四钉（标准库 json/re/pathlib+pytest，零 PyYAML/jsonschema，挂现有 server-tests job 不新增 CI job）**——①runbook front matter 契约（name=目录名 fde- 前缀/description≥40/已知点路径键类型良构/正文非空）；②`builtin_skills.SKILLS` 种子静态契约（键唯一+形状/能力 ⊆ CAPABILITY_REQUIREMENTS 无重复/LEGACY 升级指纹键 ⊆ 现役键）；③种子 manifest 构造规则独立复算钉（version 三分档 1.2.0/1.1.4/1.0.0+source+read_only 推导，src 侧漂移即红）；④**种子清单 ↔ DB 行对账**（「生成物一致性」的落法——`seed_public_skills` 端到端：admin 建号→首轮 created==len(SKILLS) 全量落库→逐 key 断言 published 定义行+现行版本行 instructions/capabilities/manifest_json 逐位等于种子构造→契约自洽律库上复核→幂等二轮 0+版本行不增殖）。变异四连（read_only 推导翻转/runbook name 脱离目录名/种子加域外能力/version 分档漂移）逐一转红→反向替换还原绿。与 B#4 purity 测试同组织（tests/ 直挂零 fixture 复用） |
| B#38 | 三维标签 + 门禁行业字段填充 | 文档/数据 | **【2026-11-06 按 Q13 收窄】**只填 seed 条件项（`server/seeds/gates.json` 的 `applicable_industries`，字段已存在、G1–G9 实测 9 处字段值全为 `null`），并注记**现行国标版本锚点 + 核验日期 + 有效期≤6 月 + 合规 owner 核准**；**不得产出等保/信创清单挂 G8/G9 `evidence_checklist`**（§2.9 已把「等保/信创条目当合规依据」列为明确不照搬）；Frank `03-G端政府专项/*` **仅可引类目名**、不得作条目素材（无 LICENSE＝全部权利保留）；条目若落地须由我方依现行国标与客户招标文件**独立撰写**，正文走指针+sha256。「先搜再建」写进 AGENTS.md | 零迁移零依赖。**🔒 冻结（2026-11-06 评审）**：素材来自无 LICENSE 且停更（2026-07-07 后）的仓库＝强时效内容却无复核触发。**解冻前置**：B#35 许可硬条款落基线 ＋ 国标版本锚点/核验人/有效期字段就位 ＋ 本节登记生效；**形状**（挂 `evidence_checklist` 出清单）若坚持须由用户重拍 Q13 |
| B#39 | 现场应急分级处置 runbook | 文档 | 新建 `.agents/skills/fde-field-incident/SKILL.md`（沿用 `name`+`description` front matter）；**【2026-11-06 许可收窄】**分级定义与升级路径由我方独立撰写，**不得沿用 Frank 的四级表列名、六段时钟分段名、三级升级时长组合、三线并行表述**（版权保护编排与结构化表达，**改阈值·换措辞·重排的等价复现同样无权**）；**阈值唯一源＝实测 P50/P90/P99**（P90 定升级、P99 定最严档），**Frank 的 5/15/60/240 分钟不作基准**；与 `OperationEvent` 留痕、B#5 审批退避 SLA 联动；只写处置动作不写自动执行；通报模板只留我方字段（不落客户联系人电话等触红线字段） | 零迁移零依赖。**🔒 冻结（2026-11-06 评审）**：复制的是结构化表达，连「不复制正文」都未覆盖；阈值无数据来源。**解冻前置**：B#35 许可硬条款落基线 ＋ SLA 校准表产出 ＋ 本节登记生效 |
| B#40 | 两技能库专属「不做清单」与已合并项登记 | 文档 | 登记不做：60 个模板化技能批量产出／21 字段全必填／12 类分类与 8 阶段框架／`skills.json` 文件权威＋CI 锁 diff／Python CLI＋4 IDE 适配器／合成案例与 `legacy/` 历史导入／AGPL 全库许可／`draft·ready·field-validated` 状态值；不做 70 篇正文整体导入／7 段模板替换 `SKILL.md`／10 维分类与 G1–G9 并列／README 当机器索引／截断文件名／等保信创条目当合规依据／沙盘现阶段／技能组合自动执行化。已映射项不另立项：B4→B#22/B#29、B6/F1→B#15、B7 暂不立项、F3/F5→B#30、F4→B#21/B#22、F6 不立项 | 零代码。**🟡 负向登记（2026-11-06 登记，与 B#35 同一 PR 生效）**：防「已评估又重评」与「把 70 篇文档当技能包导入」两类重复事故；与 B#19/B#26 同为不做清单 |
| B#10 | 外部模型依赖契约成文 | 文档 | 写成 V3 通用契约（七条规则 M-1–M-7，我方自定义编号）：①开关默认 OFF 且关闭时判定逐字一致、零外部请求；②阈值是「建议值」非判定常数、调用时点读取、覆盖免重启；③失败≠错误而是「下一阶段」且既有路径原样继续；④传输层可注入、测试网络零依赖、地址密钥禁硬编码、客户端禁擅自裁剪请求体；⑤外部响应缺字段取保守值不推测、枚举表外值只留痕不参与判定、保守方向须写明；⑥日志只记哈希与长度禁记原文、必记「哪一阶段作出判定」的 source 标记、不新建存储；⑦调用方签名不破坏、新参数一律可选、显式意图预判顺序不得被新阶段翻转。与既有 W-8「断链不静默 done」（流程层：真失败须显性化）分工不混淆——本条管判定层降级，W-8 管流程层显性失败 | 零代码零迁移零路由零依赖。**✅ 已落盘（2026-11-06：`docs/architecture/外部模型依赖契约-v1.md`——含现状对照表、七条规则、差距清单（M-5/M-6 两条纯靠立规闭合）、八条可断言判据、复查机制；行级引用一律「符号名＋行号」双锚防基线漂移）**。**触发式复查**：新增任一外部模型阶段时，同 PR 内须逐条对照 M-1–M-7 给「满足/不满足/不适用」三选一 |

### P1 第二批（总览建议 1–2 月窗口，登记不展开）

B#7 回执 DSL 一期（前置=是否接受改 Skill 编写口径，待澄清 6.1-2）｜B#8+B#32 Skill 消费面两级注入+只读技能中心（`skill_read` 分页真缺口——**该真缺口已于 2026-11-06 待办池清欠轮实施闭合**：`mcp_gateway.skill_read` 加 16k 窗口 offset 分页＋next_offset/total_characters，T-S2 计数收敛为仅首读计一次，专项 pytest 5 例；**两级注入+只读技能中心整体仍 PROPOSED 待拍板**）｜B#9 只读执行事实链面板｜B#10 外部模型依赖契约成文｜**B#11 门禁判据实施落点（承接 B#22）——落点设计已裁（2026-11-06；设计=`docs/architecture/门禁判据实施落点-v1.md`）**｜**B#12+B#31 外部文字禁入提示词+原件/派生分离——契约落盘（2026-11-06；契约=`docs/architecture/外部文字禁入与原件派生分离契约-v1.md`）**｜**B#13 统一到期语义目录+主动超时治理——立项完成（2026-11-06；契约=`docs/architecture/到期语义与主动超时治理-v1.md`）**｜B#14 executor 对抗性测试组织（前置=决策逻辑抽纯函数重构）｜**B#23 离线评测夹具 v0（前置＝四条件触发式解封：①客户量化验收线诉求成文 ②可回放 KPI 定义 ③`kpi_oracle` 责任人指定 ④只读回放 CI 静态断言；Q1–Q3 已于 2026-11-06 拍板＝「结果验收·仅文档级」）**｜B#24 过程成本计入+评测完整性留痕（依赖 B#23）｜B#30 门禁前置清单自动复核+回退留痕。**B#36 技能契约最小 5 组字段／B#37 技能自洽校验 pytest** 已于 2026-11-06 补登记于上方 P0 表（形态为文档/测试，实为 P1 可排期项，硬判据见各行）。

**B#13 立项拆分与状态（2026-11-06）**：`docs/architecture/到期语义与主动超时治理-v1.md`。核心裁决=统一**到期语义目录+各域原生转换器+条件触发的只读投影**，不建复制 `expires_at` 的通用事实表。审批主动超时已由 T-P1-5 完成（`_expire_approval` 唯一原语+`sweep_expired_approvals`+scheduler 同拍），本立项只登记并要求回归合同，不重复施工。拆分：A=本轮立项/现状目录；B=UploadSession 到期拒绝+multipart abort/失败重试（候选，需单独代码轮先解决远端副作用原子性）；C=API confirmation append-only 到期事实/视图（候选，需单独裁决）；D=跨域只读查询（无用户/运营需求则不做）。明确排除 worker lease/retry/outbox due、JWT/签名/Redis TTL、模型/进程 timeout、dispute SLA/meeting stale 等异质时钟。**本条状态=已立项，B/C/D 仍 PROPOSED，立项≠实施授权。**

**B#12+B#31 契约落盘与状态（2026-11-06）**：`docs/architecture/外部文字禁入与原件派生分离契约-v1.md`。**现状实测结论：架构已有机闭合 P-1/P-2（提示词权威层白名单）与 A-1/A-2/A-3（原件指针化+派生物三问血缘）**——全系统恰四处 system 组装点全部落在白名单内（`chat.py:189 _workbench_system_prompt`=代码常量+config+内置手册目录；`executor.py:1104`=治理面发布 instructions；`ai_content.py:115`=固定常量 system+外部数据走 user 角色 JSON；`direct_tool_completion` 形参面）；工具结果一律 tool 角色、`file_read`/`help_fetch` 带结果级 `"source"` 标记、`captured_from` 封闭枚举形状闸、`ai_request_id`/`revision_id` 血缘在位。**契约增量=①把散落的既有防线收拢为 P-1~P-5/A-1~A-5 十条我方规则＋封闭枚举白名单；②差距如实登记（lcsc_* 结果无 source 标记、direct_tool_completion 形参面无静态闸、A-4 无统一谓词、个人技能 owner 自治边界）**；③四条可断言判据（J-1 system 组装点枚举静态钉=未来执行轮靶点）＋触发式复查机制（新入口/新 AI 调用点/新工件类型同 PR 逐条对照）。**本条状态=契约已落盘，J 系判据接线仍 PROPOSED（接线≠本文授权）；纯我方独立设计，零第三方正文引用（AGENTS 红线第 8 条履行）。**

**B#11 落点设计与状态（2026-11-06）**：`docs/architecture/门禁判据实施落点-v1.md`。**一句话裁决＝三锚四反例的宿主＝B#23 离线评测夹具的「评测器元验证层」**（它们验证的是打分检查器本身，不是交付物）；门禁面落点**已随 #131 冻结**（G9 exit_condition 含「三锚四反例全过」，钉 6 守护）；pytest 模板落点＝解封后 NEW `server/tests/test_eval_criteria_harness.py`。**诚实盘点：当前仓内尚无「打分型检查器」**（G1–G9 核验=人工；其余判定面全部布尔/枚举型）⇒ 三锚四反例现在没有可验证对象，是为 B#23 算分器预置的验收合同；**元验证语义（我方定义）＝评测器可用于任何「验收线达成」判定前必须先过元验证夹具，锚点不落位/反例漏抓 ⇒ 其输出不得作 G9 判定输入（insufficient_data 不变）**。逐判据落点表 11 行（3 锚+4 反例+3 附加规则：宿主/输入/断言形状/前置闸），阈值纪律=我方数据校准前不落常量。**本条状态=落点设计已裁，元验证层实施随 B#23 夹具期同窗（四条件解封），设计≠实施授权；判据语义零新增零改写。**

### P2 条件触发 / 长期滋养（登记不展开）

B#15 Lens 正交叠加（触发=多行业模板成本失控实测）｜B#16 交付编译器契约清单（上游 0 测试，声明非验证）｜B#17 编号知识 Claim 库｜B#18 纪律补强｜B#19 明确不做清单（负向知识）｜B#20 DSH 替代内评（=P3 评估报告 §4 已消费的调研报告，条件触发）｜**B#25 变体体系三期 —— 🔒 封存（永锁，2026-11-06 评审）**：原触发条件（可量化可回放真实 KPI＋用户确认产品化＋Q5 容器/境内模型口径通过）已被 Q1/Q3/Q4/Q5/Q6/Q7 逐条预先否定 ⇒ 条件在当前决议下永不可满足，**移出季度复查清单**；若将来推翻 Q5/Q7 须由用户重拍决议再解封（原则不变：真相/参考解/隐藏流量永不入库不进 git，落 fdeops 工作目录＋全代号化——客户资料红线）｜B#26 fde-gym 专属不做清单（负向知识）｜B#33 文档职责分层+验证证据格式（`docs/verification/` 模板）｜B#34 项目运行预览隔离（触发=上预览能力；**我方红线禁止交付进程跑客户代码——仅内部自检夹具**）。**B#38/B#39/B#40 已于 2026-11-06 补登记于上方 P0 表**（B#38/B#39 冻结、B#40 负向登记）。

### 跨项目合并六组（防重复立项，登记为合并组）

对抗性测试→B#14 一项｜结果验收与反证→「交付效果评测」一期 B#21/#22 文档→二期 B#23/#24 夹具→三期 B#25 变体（#11 只作实施落点）｜事实链→B#9 一项｜两级注入→B#8（+#32）一项｜外部模型纪律→B#10 一份契约｜状态一致性→B#6 一份清单+pytest｜门禁与验收合同→B#21/#22/#29 文档→B#28/#30 状态机→B#23 夹具｜DSH/外部执行体→B#27 一份决策记录（结论仍「当前不装、不换执行体」）。

### 拍板闸与待澄清（全部挂账，登记轮不预支）

1. **B#1+B#28 合并迁移窗口**（一次 rebuild+alembic upgrade head）——实施轮启动前须拍板；
2. **Q1**「交付产物评测」=静态质量打分 vs 上线后业务结果验收？（改路线：若前者 B#21–#25 整体降 P2）；
3. **Q2** 是否有真实客户要求量化验收线？哪个环节？；**Q3** 是否存在可量化可回放 kpi、谁定义 oracle？（无 oracle ⇒ uplift 不成立，B#21/#22 停文档层）；
4. Q4 代号化题库/隐藏数据落 fdeops 工作目录的落点与权限；Q5 每 run 一容器/境内模型口径；Q6 上游许可证链法务口径；
5. 待澄清 6.1 原遗留：B#7 Skill 口径顺延与否、B#15/B#20 触发判据业务数据、zcode CLI 会话续接能力。

**红线对照（登记即声明，上位维持）**：B#25 客户资料红线（真相永不入库/不进 git）；B#34 交付进程红线（仅内部自检夹具）；B#3 与红线同向；**P3 评估报告 §1「写类外呼/发信/付款永不降级」红线对本清单全部条目上位维持**——任何借鉴项不得引入写类 external 免事前确认面。

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
