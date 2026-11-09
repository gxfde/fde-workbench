# V3 实施任务台账（backlog）

> 状态：**T-\* 任务 33 节全部 DONE**（P0–P2 全部 DONE 或核销；P3 四项已定案收口，见 §P3 与 v3-p3 三报告）；「开源借鉴清单登记」段 B#1–B#40（#127 登记 34 项＋#133 评审补登记 6 项）：**P0 先行批表 10 项 ✅ 已实施**（#128~#131），其余按逐条状态标注——PROPOSED/冻结/封存/修复项（登记≠排期≠默认实施）。任务 ID 与差距矩阵/风险登记册互引。
> 复杂度：S（≤1 天）/ M（数天）/ L（≥1 周）。均按既有 goal-d 循环节奏逐个交付，不并行开双实施线。
> **2026-11-06 新增节「售前主线登记（T-A 系列）」**：11 条（**T-A1..T-A9 / T-B1 / T-Z1**）**全部 PROPOSED（登记轮，零代码零迁移零路由）**——上位文档=`docs/architecture/售前驱动交付模式改造方案.md` v1.2，评审依据=`docs/audit/售前驱动交付模式改造方案-多专家评审-2026-11-06.md`（五专家 party mode）；**登记≠排期≠实施授权**，逐条闸见该节与 §拍板闸第 6 条。
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

### T-O2c 全局注册类型只读面（CR-032 偏差清偿③：无项目上下文消费方）— **DONE（2026-11-07）**
- 目标：行业模板/调研定义编辑器（全局面，无 project_id）此前无法拉取注册类型选项——T-O2 只开了项目内 relation-types 面（GET /projects/<id>/ontology/relation-types 是「全局 ∪ 项目内」合并面，且强依赖项目上下文）。
- 服务端：NEW `GET /api/v1/ontology/relation-types`（require_auth；**只收全局行** project_id=NULL——项目内类型只对本项目生效，进全局模板会在其他项目实例化时落空；`?kind=` 过滤、全状态返回；不进 api_catalog）。新蓝图 `global_ontology`（蓝图 40→41，路由 304→305）；审计三件套再生成。零迁移零新表。
- 桌面：`useRegistrySubjectTypes` 支持 `projectId=null` 走全局面＋`enabled` 会话门；`ResearchDefinitionEditor` 调研主体下拉补注册类型选项（内置 ∪ 注册 active ∪ 当前值兜底——fail-open/retired 不空白显示）；JSON 文件导入放宽对象类型码格式（值域权威在服务端），AI 生成路径维持内置五类（T-O2b 防幻觉基线）。pytest +3 / vitest +5。

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

## 售前主线登记（T-A 系列，2026-11-06 登记轮，**零代码零迁移零路由**）

> **上位文档**：`docs/architecture/售前驱动交付模式改造方案.md` v1.2（商业模式侧上位文档）；**评审依据**：`docs/audit/售前驱动交付模式改造方案-多专家评审-2026-11-06.md`（五专家 party mode 独立意见在 `docs/audit/experts/`）。
> **登记纪律**：本节**登记≠排期≠实施授权**（沿用开源借鉴登记段同款纪律）。每条须在实施轮启动前满足其「闸」列，且走既有 feature→PR→4 CI 流程。
> **编号口径**：T-A 系列与本文 T-P0/T-E/T-W/T-S/T-G/T-C/T-I/T-UI/T-D 及借鉴登记 B# **均为独立编号**，不互相映射（借鉴总览文首已声明两套编号独立）。本节新登记编号 **T-A1..T-A9 / T-B1 / T-Z1** 均经全文件查重，无撞名（既有 T-C1=Delivery Compiler、T-D1=文档血缘补洞，故避开 C/D 前缀）。
> **范围声明**：本主线是**售前业务链路**（访谈→事实分层→方案→报价→SOW），**不重造** V3 已收口的 workflow 定义/运行/节点/生命周期（T-W1..T-W5）、本体（T-O1..T-O4b）、Skill 治理（T-S1/T-S2）、门禁证据候选（T-G1/T-W7）、证据一等表（T-E1..T-E3）、Delivery Compiler（T-C1）、桌面控制台三页（T-W6/T-UI1）、只读执行事实链面板（B#9）。
> **与既有已落地项的边界**：T-UI1/T-W6 已交付的「workflow/术语表/Skill 版本」三页与 B#9 的「执行事实」页**均不含**本主线所需的三态入口、售前三层可视化、agents run 列表、meetings 列表 ⇒ 不构成重复立项；本主线控制台（T-A8）与 B#9 **事实链面板**（项目 tab「执行事实」，只读三源聚合）在**数据源与用途上不重叠**（前者=智能体运行态，后者=证据/审计事实链），**建议合批但界面分离**（待 T-A8 开工前拍板，见 §拍板闸 6）。

### T-A1 presurvey S3 前置闸的桌面可读提示与拦截反馈 — **DONE（2026-11-07 goal-ta3 核销——#156 已先行兑现，零补码）**
- 目标：G3（SOW-A 签署 + A 款预付到账 + 数据授权书四项勾选）未通过时，售前在桌面端能看见**可读的拦截原因与跳转入口**，而不是只见 409。
- 现状实测（fork/main@d3adf1c）：**闸已落地**——`server/src/fde_api/guidance/service.py:402` `_require_s3_gate`，在 `:41`（`set_presurvey_source`）与 `:63`（`create_analysis`）**两处强制调用**，未通过即抛 409 `presurvey_s3_gate_open`（`:413` 文案含四项清单）；门禁种子 `server/seeds/gates.json` G3 `evidence_checklist` 四项逐项对应。⇒ **本条不是「闸未落地」，是「闸缺桌面呈现」**（原方案 §2.3 G2 缺口结论已在 v1.2 订正）。

#### ✅ T-A1 核销轮（goal-ta3，2026-11-07，纯文档零代码——桌面呈现已由 #156 先行交付）
- **核销判定（fork/main@1a1d34e 实测）**：`PresurveyGateHint.tsx` 在位且已接线（`PresurveyAnalysisAction.tsx` 消费 409 `presurvey_s3_gate_open` 拦截态挂载）——①服务端 message 原文呈现；②G3 证据清单四项逐项渲染（claim_status 徽标沿用 GateBoard 的 claimed≠accepted 黄标语义）；③「前往门禁页」跳转锚 `gatesHref=#projects/{id}?tab=gates`（复用既有路由零新路由，点击直达门禁详情面）；④非门禁失败走原通用文案（通过时原路径零变化）。既有专项测试 `presurvey-gate-hint.test.tsx` **5 例全绿**（拦截态可读/四项清单+徽标语义/跳转锚/非门禁回退/gates 拉取失败降级）——登记验收四项全部被既有用例钉住，**零补码**（T-UI1 同款先例）。
- 登记「复杂度 S/回滚 revert 单 commit」等规格由 #156 实施轮兑现，本核销轮零 diff（本节与本核销记录本身除外）。
- 修改文件：`desktop/src/renderer/src/guidance/`（presurvey 录入卡）+ 错误码映射（复用既有 `GuidanceServiceError` → `error.details`，**零新错误码**）。
- DB：无。API：无新增（仅消费既有 409 `presurvey_s3_gate_open`）。
- 测试：桌面 vitest（拦截态渲染四项清单 + 跳转按钮存在/点击可达 G3 详情）；服务端零改动零用例。
- 验收：G3 未通过时桌面显四项目录与跳转；通过时原路径不变。
- 回滚：revert 单 commit（纯前端）。风险：低（错误体已含清单）。依赖：无。复杂度：**S**。
- 闸：**无**（可随第一阶段任一轮开工）；须走 PR→4 CI。

### T-A2 代号化自动替换层（入库前企业名→代号） — **已实施并合并（2026-11-06 PR #160 三道防线 + 2026-11-07 confirm 复核闸补齐，PR 见下）**
- 目标：售前上传访谈资料时，正文中的**真实企业名在入库前被自动替换为代号**，使「客户真实资料永不进 git 历史与远端」红线在**文件正文面**也成立（当前该红线只由 CI 扫数据库 dump 覆盖）。
- 现状实测（fork/main@d3adf1c）：① `scripts/check-pseudonymization.sh` 只扫 `pg_dump --data-only --inserts`（`:104`），**不扫上传文件的二进制内容** ⇒ 文件正文含真实企业名时 CI **静默通过**；② `server/src/fde_api/guidance/redaction.py:22` `redact_text` 已脱敏 email/mobile/idcard/landline，**故意不脱企业名**（企业名非 PII 格式）；③ **`redact_presurvey`（`redaction.py:31`）全仓零调用点**（`git grep` 仅命中定义处自身）⇒ presurvey 链（`ai/kimi.py` 抽取 → 落库）**当前零脱敏**；④ `projects.enterprise_code` 已是三段式代号（`client·industry·city`，格式检查 `check-pseudonymization.sh:206`）。
- 形态：**非-AI 纯函数层**（字典匹配 + 确定性替换，合借鉴登记 B#31「导入零模型调用」）。
- 修改文件：`server/src/fde_api/guidance/redaction.py`（新增企业名替换函数，与 `redact_text` 串联）；词典**种子文件**（`server/seeds/`——✅ 2026-11-06 拍板，见 §拍板闸 6②）；presurvey 抽取链接入点（`guidance/service.py` 的抽取落库前置）。
- **词典来源纪律（红线级）**：词典**不得**取自真相层 `D:/test/FDE/leads.md`（执行面不可触真相层，AGENTS.md 红线）⇒ 词典**抽到 DB/仓库内**，执行面只读 DB；CI 侧沿用既有合成 fixture `.github/ci-assets/synthetic-leads-blacklist.txt`（`ci.yml:85/105`）。
- **双向复用口径**：CI 扫库正则（`check-pseudonymization.sh:91` 中文 2–15 字 + 公司/集团/厂 结尾）与入库替换词典**须为同一份**——建议 bash/perl 侧提取收敛为 **Python 单点**（bash 调用），自测断言「替换器词典 == CI 词典」逐条一致。
- DB：无（✅ 2026-11-06 拍板：词典为**仓库内种子文件**，零迁移零 DB 依赖；CI 扫库与入库替换读同一个文件，一致性断言天然成立）。API：无新增（内部层）。
- 测试：**哨兵自测**（借鉴登记 B#11「从未真正运行过的检查等于没有检查」）——① 注入合成企业名断言确实被替换；② **误替换钉死**（该正则固有会抓「技术公司」「制造公司」类通用词）；③ 词典一致性断言（替换器词典 == CI 词典逐条）；④ **测试数据只用合成 fixture，真实客户资料不可作测试素材**（AGENTS.md 红线）。
- 验收：合成样本入库存中零真实企业名；非企业名文本零改动；误替换集合为空。
- 回滚：开关关闭即回退（原文不落库，回滚无数据面残留）。风险：中（正则误替换，靠②钉死）。依赖：无。复杂度：**M**。
- 闸：✅ **已拍板（2026-11-06，§拍板闸 6①）：分层失败语义**——替换器**异常**（词典加载失败/正则编译失败等机制性故障）→ **fail-closed 硬阻断入库**；**疑似企业名但词典未收录**（正则命中「技术公司」类通用词）→ **放行但记入待复核清单**，方案审核人 confirm 前必须复核。

#### ✅ T-A2 实施轮（2026-11-06，状态：**已实施并合并**——PR #160 → `d467fac`，CI 4 job 全绿，服务端 2016 passed / 6 skipped）

**实施澄清（与拍板原文的口径差异，须记入台账）**：闸①原文「疑似名**放行**但记入待复核清单」——若「放行」= 原文不改直接入库，则真实名仍进库，「客户真实资料永不进 git 与远端」红线在文件正文面失守。**实施口径取「放行 = 不阻断入库流程，原文不留库」**：疑似名**同样被替换为代号**（替换目标 = `projects.enterprise_code` 首段，如「客户A」），替换后记入复核清单交方案审核人 confirm 前复核。**通用词例外**（「技术公司」「制造公司」等无辨识度表述）→ 零改动、不进清单（哨兵②）。

**落地实现**：
- 新增 `server/src/fde_api/guidance/enterprise_dict.py`：词典加载器（种子文件 + `FDE_ENTERPRISE_DICT` 环境变量补充）、格式校验（fail-closed）、通用词判定（后缀通用词长度占比 ≥ 1/2）、候选前缀剥离（中文无词边界，正则会把句子前缀吞进候选）。
- 新增 `server/seeds/enterprise-names.txt`：仓库内种子词典（**只放合成示例**，真实企业名永不进 git）；CI `FDE_LEADS_MD` 已改指此文件（`ci.yml` pseudonymization job）。
- `guidance/redaction.py` 扩展：`redact_text_detailed`（返回 text + suspects + replaced）、`redact_presurvey`（聚合 suspects/replaced）；既有 `redact_text(value) -> str` 签名与语义保持不变（下游 `ai/project_draft.py` 零改动即受益）。
- **三道防线接入**（`guidance/jobs.py` worker 链）：① **进模型前**——`build_messages` 前替换全文（本地抽取腿不落存储，此处是全文接触外界的唯一出口）；② **落库前**——模型输出回显的企业名兜底替换（文本字段 + LIST_FIELDS 各项 + evidence 值）；③ **复核清单**——替换/疑似条目落 `operation_events`（`event_type=guidance.redaction_review`，B#9 事实链可查）。
- **fail-closed 落点**：词典机制性故障 → `RedactionConfigError` → worker 落 `failure_code=pseudonym_dict_unavailable`（**不重试**，分析落 failed 不卡 analyzing）；`ai/project_draft.py` 同路径补 catch → 503。
- **测试**：`server/tests/test_guidance_enterprise_redaction.py`（13 例：哨兵①②③④ + 分层失败语义 + 通用词 + 前缀剥离 + 词典一致性断言「CI fixture ⊆ 替换器词典」）；`server/tests/test_guidance_redaction_worker.py`（2 例：三道防线端到端 + fail-closed 不重试）。**测试数据全为合成**。

**本轮未做（须后续登记，不得默认扩范围）**：`agents/context.py` 的 `redact_patterns`（执行面上下文脱敏，走盘符/令牌/禁区词口径与 fail-closed `forbidden_terms` 断言）**未接企业名替换**——两条线口径不同，混做会破坏执行面既有断言；接入前须另立条目。

#### ✅ T-A2 补齐轮：confirm 复核闸（拍板 6① 机械强制；2026-11-07，消费 #160 事实源）

**补的是什么**：#160 把复核条目落了 `operation_events`（`guidance.redaction_review`，仅 entries 非空才落），但「方案审核人 **confirm 前必须复核**」没有消费点——confirm 无闸、读面无清单（桌面 B#9 面板亦 PROPOSED），复核只靠流程自觉。本小轮在 #160 原语之上补齐消费侧，零新事实源：

- **常量归位**：`REDACTION_EVENT_TYPE` 移到 `guidance/models.py`（写入方 jobs 与消费方 service 共享单一权威；jobs 以同名导入保持兼容，测试导入不受影响）。
- **confirm 复核闸**（`guidance/service.py::confirm_analysis`）：确认前按分析聚合复核事件（同名跨事件合并：occurrences 累加、`matched_dict` 求并、按名称排序）——清单非空且请求未显式 `redaction_reviewed=true`（路由只认字面 true，fail 向安全侧）→ **409 `redaction_review_required`**；带 ack 放行，动作随既有 `guidance_analysis_confirmed` 事件留痕（`redaction_reviewed`/`redaction_review_hits` 增量键），零新增状态面。
- **复核读面**：`get_analysis` 与 confirm 响应增派生字段 `redaction_review`（同一事件源聚合投影，不二次推导文本）——方案审核人的可见入口；桌面呈现随 T-A4/B#9 面接线（本小轮不做桌面）。
- **闸与来源种类无关**（translator_draft / presurvey_docx 同闸）；复核清单是「历史上替换了什么」的审计事实，编辑正文不改写清单。
- **测试**：NEW `server/tests/test_guidance_confirm_review_gate.py` 6 例（无 ack 409+零变更 / ack 放行+事件留痕 / 干净分析免 ack+事件 `redaction_reviewed=False` / 读面清单形状与排序 / 跨事件同名合并 / 编辑不改写审计清单）。零迁移零路由改动（既有端点加可选参数）零桌面改动；服务端变更 ⇒ 合并后 rebuild 三镜像（alembic 幂等 no-op）。

### T-A3 调研表三态流转（confirm/reject/revise）桌面入口 — **已实施并合并（2026-11-06 PR #163 → `5e27e49`，见下）**
- 目标：补齐「调研 → 方案」链路的桌面断点——三态流转目前**桌面零引用**（服务端状态机与端点已完整）。
- 现状实测：`server/src/fde_api/research/project_routes.py` 三条端点（confirm/reject/revise）齐备；桌面端 `desktop/src/renderer/src/research/` 对其**零引用**（台账 `docs/后续需求台账-F5与D11.md:29` 已记同一缺口）。
- **权限口径（2026-11-06 复审校准，方案 v1.2 §10 Q3；2026-11-06 实施轮再校准，见下）**：实测 `research/form_service.py`——`_require_fill`（`:966`）允许 `can_manage` **或** `can_update_assigned_tasks`（role≥fde_engineer），**revise 走 `_require_fill`（`:568`）⇒ member 可用**；`_require_confirm`（`:972`）强制 `can_manage`，**confirm/reject 调用点 `:347`/`:532` ⇒ member 恒 403**；`projects/permissions.py:35` member 角色 `can_manage=False`。⇒ **四闸校准后**：访谈助理=viewer（填表/提资料）；独立售前=fde_engineer+member（填表/**revise 打回重填**/录 presurvey 资料/生成方案草稿，**不可 confirm/reject 事实**）；方案审核=project_lead 或项目负责人（**confirm/reject 事实**、终审、导出 SOW）；交付专家=可声明 `agent_assisted`。**服务端权限模型零改动。**
- ⚠️ **实施轮再校准（2026-11-06，T-A3 实施实测，登记原文两处与服务端契约不符）**：
  1. **「revise 打回重填」口径错**——实测 `revise_form`（`form_service.py:561`）要求 `parent.status == "confirmed"`，否则 409 `research_form_not_confirmed`；它做的是「**基于已确认版本显式开新 draft 修订**」（记事件 `project_research_form_revised`），**不是打回重填**。真正的打回是 **reject**（`review_comment` 必填、**草稿保持可编辑**、记 `returned_by_user_id`/`return_comment`），但 reject 走 `_require_confirm` ⇒ **member 恒 403**。⇒ 校准后：**member 对已确认表可 revise（开新修订），对草稿表无任何三态动作**（打回只能由方案审核人做）。
  2. **验收标准两处错**——「confirm 要求必答字段全 **accepted**」→ 实测是「**visible 必填 answers 非空**」，缺失返 422 `research_required_fields_missing`（`form_service.py:356`）；「**reject/revise** 必填理由」→ 实测**仅 reject** 必填 `review_comment`（路由层 `set(payload) == {"version", "review_comment"}`），**revise 只收 `{version}`**。
- 修改文件：`desktop/src/renderer/src/research/ResearchForm.tsx`（三态操作区 + 权限显隐 + 必填校验 + 乐观锁 version 传递）、`ResearchWorkspace.tsx` / `ResearchOpportunity.tsx`（透传 `canManage`）、`styles.css`（三态区样式）；`desktop/tests/renderer/project-research.test.tsx`（用例）。
- DB：无。API：无新增（消费既有三端点）。
- 测试：桌面 vitest（三态按钮按权限显隐；confirm 必答字段缺失本地拦；reject 理由必填；409 版本冲突原样呈现不吞 + 403 可读提示）；服务端零改动。
- **回归风险（实测登记）**：research 域现有 **222 例**压在同一条链上（服务端 99 + 桌面 123）⇒ 若动前端数据契约（状态映射、乐观锁 version 传递）回归面大，**必须先跑全量再合**。
- 验收：三态可从桌面完成；member 可见 revise 不可见 confirm/reject；服务端 403/409 原样呈现。
- 回滚：revert 单 commit。风险：中（回归面大）。依赖：T-A2（代号化后入库）。复杂度：**M**。

#### ✅ T-A3 实施轮（2026-11-06，状态：**已实施并合并**——PR #163 → `5e27e49`，CI 4 job 全绿，桌面全量 69 文件 / 848 例全绿，服务端零改动）

**实施要点**：
- **三态入口落在 `ResearchForm.tsx`**（调研表详情页底部独立区块，与「保存调研内容」动作分离——避免把「确认事实」误读成「保存」）：
  - **确认事实**（`can_manage` 可见，仅 draft 态）：本地先按服务端同源口径校验 `completion.missing_required_field_keys`——缺失则本地拦下并点名字段，**不发请求**（服务端另有 422 `research_required_fields_missing` 兜底，两层同源不冲突）；
  - **驳回并留意见**（`can_manage` 可见，仅 draft 态）：展开理由输入框，**理由必填**（空则本地拦），提交后调 `reject` 带 `{version, review_comment}`；驳回意见回显在表单上（`returned_by_user_id`/`return_comment`）；
  - **创建修订版**（`can_update_assigned_tasks` 可见，仅 confirmed 态）：调 `revise` 带 `{version}`，服务端 201 返回新 draft 修订。
- **乐观锁**：`revision.version` 随请求下发；409 `stale_version` / `research_form_conflict` 走既有「刷新远端版本 / 比较差异 / 放弃本地修改」冲突面板，**不吞**。
- **错误呈现**：已知错误码给中文可执行提示（403 `forbidden`、422 `research_required_fields_missing`、409 `research_form_not_draft` / `research_form_not_confirmed`、400 `invalid_request`）；**未知错误码回落到服务端原文 `error.message`**，不吞不静默重试。
- **权限显隐口径与服务端同构**：桌面 `canManage`（admin 或项目负责人且 project_lead）↔ 服务端 `can_manage`；桌面 `canFill` ↔ `_require_fill`（`can_manage` 或 `can_update_assigned_tasks`）。`canManage` 设为**可选 prop 且默认「无权」**——安全默认：漏传时三态按钮不出现，而非误开放。

**与既有产品决策的冲突及裁决（重要）**：
- 既有用例 `edits a legacy confirmed form through the canonical save route while preserving its original revision` 钉住了「**桌面刻意不暴露 revise**；已确认表直接走标准 PATCH 保存，服务端 `_ensure_working_revision` 自动 fork 出新 draft，原修订不变」——这是 legacy confirmed 表的迁移兼容路径。**本轮保留该行为**：保存仍走 PATCH、不触发 `/revise`；`revise` 是**并行的显式留痕通道**，不是保存的替代路径。
- **revise 的增量价值**：PATCH 的隐式 fork（`_fork_working_revision`）**不记事件**，而 `revise_form` 记 `project_research_form_revised`（携 `parent_revision_number`/`revision_number`）⇒ 显式 revise 让「谁在何时基于已确认版本发起了修订」进 `operation_events` 事实链（B#9 可查）。台账登记时未识别这一增量价值，本轮明确其定位为**留痕通道**而非**唯一改稿路径**。
- **未收紧「已确认表只读」**：实施中曾试把 confirmed 表改为只读（改稿只能走 revise），**被既有用例判红后撤回**——已确认表可编辑是既有契约，服务端 PATCH 允许，桌面单方面收紧会造成「服务端允许、桌面拒绝」的行为分叉。

**测试**：`desktop/tests/renderer/project-research.test.tsx` 新增 describe「research form tri-state (T-A3)」**10 例**：权限显隐三态（管理员草稿 / 独立售前草稿 / 独立售前已确认）、创建修订版带版本、confirm 必答缺失本地拦、confirm 必答齐全后发出并转已确认态、reject 理由必填本地拦、reject 填理由后发出并回显意见、409 冲突原样呈现 + 刷新入口、403 可读提示。既有 63 例**零回归**（含被撤回的只读收紧那一条）。

### T-A4 事实/假设/待确认三层桌面可视化 — **已实施并合并（2026-11-06 PR #164 → `5b47c07`，见下）**
- 目标：客户原话 vs AI 推断 vs 待确认项**在桌面端视觉可分且可编辑**——支撑「售前录入的事实需客户确认」红线与 Q3 四闸的语义基础。
- 现状实测：`server/src/fde_api/guidance/ai_schema.py:6` `CLASSIFICATIONS = {customer_stated, ai_synthesized, ai_inferred, open_question, human_added}` 五分类**已内建**；`:60` evidence 引用必须命中 `source_refs`，否则 `unknown_source_ref` **拒收**（fail-closed）。⇒ 缺的是**呈现与编辑面**，非模型面。
- **实施轮勘误（2026-11-06，T-A4 实测，与登记原文三处出入）**：
  1. **fail-closed 只覆盖 AI 生成路径**：严格校验 `validate_guidance_output`（含 `:78` `missing_source_ref`「事实和 AI 判断必须引用原文」）**仅在 `guidance/jobs.py:144` 的 AI 生成路径调用**；**人工 PATCH 路径（`guidance/service.py:126`）只查「字段非空 + 是 list」，不查 `source_refs` 与 `classification` 合法性** ⇒ 「无锚点的事实类条目」在库里**确实可能存在**（历史数据 + 人工编辑留下的）。桌面侧的降级规则因此**不是冗余**，是必需的第二道闸。
  2. **登记未识别编辑态的元数据错位缺陷**：编辑态原为「整字段一个 textarea + 按行号索引继承元数据」（`changeItems` 用 `previous[index]` 回填 classification / source_refs / severity / module）。插入或删除一行会让**其余条目的分类与原文锚点整体错位**（把 A 的锚点贴到 B 的文字上），叠加第 1 条的弱校验 ⇒ 错位**静默落库**，不报错、不拒收。
  3. **服务端既有自动 fork 路径不记事件**：`_ensure_working_revision`（`form_service.py:915`）在 current 非 draft 时静默 fork 新修订且**不记 `operation_events`**；`revise_form` 才记 `project_research_form_revised` ⇒ 桌面侧若要做「谁在何时基于已确认版本发起修订」的留痕，必须走显式 revise 端点（与 T-A3 同一裁决）。
- 修改文件：`desktop/src/renderer/src/guidance/classificationLayers.ts`（**新增**：五分类→三层归属纯函数 + 降级规则 + 分类下拉可选集）、`GuidanceReview.tsx`（只读态三层分组呈现 + 编辑态**条目粒度**编辑器）、`styles.css`（三层视觉）；测试 `desktop/tests/renderer/guidance-classification-layers.test.tsx`（**新增**）。
- DB：无。API：无新增（消费既有 guidance 输出）。
- 测试：桌面 vitest（五类各自呈现；`ai_inferred` 项须带来源锚点；无锚点项显示为待确认而非事实；**编辑不丢元数据**——改/删条目后其余条目的分类与锚点不错位；无锚点条目不得被改成事实类分类）。
- 验收：客户原话与 AI 推断在界面上不可混淆；每条可溯源到具体访谈记录。
- 回滚：revert 单 commit。风险：低。依赖：T-A3。复杂度：**M**。

#### ✅ T-A4 实施轮（2026-11-06，状态：**已实施并合并**——PR #164 → `5b47c07`，CI run 42251482875 success，vitest 858；状态由洁癖收尾轮 2026-11-07 落定——原「实施中，待 CI 与 PR 收尾」已过期）

**三层归属规则**（`guidance/classificationLayers.ts`，纯函数）：
- **客户事实层** = `customer_stated`（客户原话）+ `human_added`（人工补录）；
- **AI 判断层** = `ai_synthesized`（AI 综合）+ `ai_inferred`（AI 推断）；
- **待确认层** = `open_question`（开口问题）**+ 任何「无原文锚点且非 human_added」的条目**（降级规则）。
- **降级规则的理由**：服务端 AI 路径已 fail-closed 拒收无锚点的事实/判断类（`ai_schema.py:78`），但人工 PATCH 路径弱校验不查 ⇒ 库里可能存在这类条目；桌面上把它们放进「客户事实」层等于替无锚点的判断背书。降级为「待确认」是保守且正确的呈现。

**只读态呈现**（`GuidanceItems` → 三层分组）：每层一个带色边框的区块（事实=绿 / AI=蓝灰 / 待确认=琥珀），每条展示 **分类标签 + 文本 + 来源锚点（`来源：{source_filename}`，无锚点显式写「无原文锚点」）+ 事实层的确认状态（客户已确认 / 未确认）**。原先只读态把条目渲染成纯文本 `<li>`（分类、锚点、确认态全部丢弃）。

**编辑态改造（顺带修掉元数据错位缺陷）**：从「整字段一个 textarea + 按行号继承元数据」改为**条目粒度编辑器**（每条一张卡片：分类下拉 + 锚点只读展示 + 「客户已确认」勾选 + 文本框 + 删除；字段级「新增条目」按钮默认 `human_added` / 无锚点 / 未确认）：
- 元数据与**条目对象**绑定，不再按行号重排 ⇒ 插入/删除条目不会让其余条目错位；
- **分类下拉的候选集受锚点约束**（无锚点条目只能选 `open_question` / `human_added`）——与服务端 `missing_source_ref` 同口径，不让桌面凭空造出「客户没说过的话」；
- 历史数据里「无锚点却是事实类」的条目，其当前值仍在候选集内（否则下拉显示空白，一保存就静默改掉分类）；
- 保存前过滤空文本条目（服务端 `invalid_text` 拒收空条目，而「新增条目」允许先建空行再填）。

**测试**：`desktop/tests/renderer/guidance-classification-layers.test.tsx` **9 例**——三层归属、无锚点降级（不混进客户事实层）、五类标签可读且客户原话与 AI 推断不可混淆、条目粒度呈现、改文本不动其余条目元数据、删条目不使其余条目错位、无锚点条目的分类候选集受限、新增条目默认人工补录且空条目不随保存提交、保存时保留分类与锚点（含 `confirmed`）。既有 guidance 22 例零回归。

### T-A5 方案三选项 + 取舍 + 明确不做 + 验收标准 骨架模板 — **已实施并合并（2026-11-06 PR #172 → `880997f`，见下）**
- 目标：方案骨架模板化，降低售前从零起草成本。
- **复用优先（登记即约束）**：`server/src/fde_api/solutions/service.py:895-945` **既有六段骨架**，`out_of_scope` 段即「明确不做」⇒ **零新列**，不新建方案结构。
- 修改文件：既有 solution 骨架的模板文案与 `out_of_scope` 预填（**不新增字段、不新增表**）。
- DB：无。API：无新增。
- 测试：服务端既有 solution 用例不回归 + 桌面模板渲染用例。
- 验收：三选项 + 取舍 + out_of_scope + 验收标准四段齐备且可导出。
- 回滚：revert 单 commit。风险：低。依赖：T-A4。复杂度：**S**。
- **实施轮勘误（2026-11-06，T-A5 实测，与登记原文三处出入）**：
  1. **「out_of_scope 段即『明确不做』」不成立——既有六段里没有独立的「明确不做」段**：实测 `_skeleton_text_fields` 的六段是 `design_markdown` / `deliverables` / `acceptance_criteria` / `data_systems` / `schedule` / `risks_dependencies`（`HEALTH_COVERAGE_FIELDS`），其中 **`out_of_scope` 只混排在 `risks_dependencies` 段里**，与「假设」「待确认问题」三类前缀同段（`- 本阶段不包含：…`）。⇒ 要满足验收的「out_of_scope 单独可见」，**必须新增一个独立段**（追加，不动既有段，否则既有 goal-d2 用例判红）。
  2. **「桌面模板渲染用例」不成立——桌面零改动**：实测桌面用**通用 Markdown 渲染器**消费 `design_markdown`（`desktop/src/renderer/src/solutions/SolutionDetailPage.tsx:94` 的 `MemoMarkdown`、`SolutionEditor.tsx:121` 的预览），**无任何硬编码段落清单** ⇒ 新增 `##` 段自动渲染。登记时误以为桌面需配套改代码 + 补用例，实际**桌面一行都不用改**。
  3. **另有一条骨架构建路径未接线**：`server/src/fde_api/workflows/compiler.py:compile_delivery_preview`（本体编译路径）**全仓无生产调用方**（仅 `server/tests/test_delivery_compiler.py` 引用）⇒ 本条**不覆盖该路径**——不扩大范围，不给未接线路径埋一套没人看的文案。
- **实施轮实际改动**：`server/src/fde_api/solutions/service.py` 的 `_skeleton_text_fields`（**唯一改动的生产文件**）——
  1. `design_markdown` **追加**「## 方案选项与取舍」段（选项 A / B / C + 取舍，四个占位行均带「待补」提示）；
  2. `design_markdown` **追加**「## 明确不做（本阶段不包含）」段（从 `analysis.out_of_scope_json` 搬运，无条目时落「- 待补：本阶段明确不做的范围」占位行；**本段不带 risks 段的「本阶段不包含：」前缀**——前缀是给 risks 段三类混排用的，独立成段后重复一遍就是噪音）；
  3. 新段前后留空行（含给既有「## 实施路径」段补一个前置空行）——售前是在 textarea 里直接改这段原始 markdown 的，空行是可扫读性的实际成本；**仅空白，不动任何既有段标题与条目文本**。
  - **只追加、不改既有段标题**：`## 方案设想（待人工修订）` / `## 实施路径（待人工修订）` 标题与 risks 段三类前缀全部原样保留（既有 delivery compiler 与 goal-d2 用例钉住）。
  - **段序固定**：方案设想 → 方案选项与取舍 → 实施路径 → 明确不做。

#### ✅ T-A5 实施轮（2026-11-06，状态：**已实施并合并**——PR #172 → `880997f`，CI 4 job 全绿，服务端零桌面改动；rebase 到 fork/main `f7ace0e` 后提交）

**合并过程留痕**（供后续轮复用）：首版 sha `3941522` 推送后，fork/main 已前进 6 个 PR（#166/#167/#168/#169/#171）⇒ 首次合并返回 405 `Pull Request has merge conflicts`。处置：rebase 到 `f7ace0e`，**仅台账一处冲突**（#169 洁癖收尾轮同时改写了 T-A4 状态行）——裁决取 HEAD 侧（#169 的版本更新更准，含 CI run id 与 vitest 858）；`solutions/service.py` 在 fork/main **未被改动，无代码冲突**。rebase 后定向回归 **42 passed**（含 fork/main 新增的 `test_guidance_confirm_review_gate` 6 例）。

**四段验收逐条落位**（台账验收口径）：
| 验收项 | 落位 | 形态 |
|---|---|---|
| 三选项 + 取舍 | `design_markdown` 新增「## 方案选项与取舍」段 | 选项 A/B/C + 取舍各一行，均带「待补」提示 |
| out_of_scope 单独可见 | `design_markdown` 新增「## 明确不做（本阶段不包含）」段 | 从 `out_of_scope_json` 搬运；无条目时落占位行 |
| 验收标准 | 既有 `acceptance_criteria` 段 | 成功标准条目 + 「（验收口径待补）」标记（既有行为，本轮钉住不回归） |
| 可导出 | `export_sow` 冻结快照 | `content_snapshot_json["solution"]["design_markdown"]` 含上述两段 |

**测试**：新增 `server/tests/test_solution_skeleton_options.py` **6 例**——三选项与取舍占位齐备（含「待补」提示）、「明确不做」独立成段且 risks 段既有「本阶段不包含」前缀不回归、段序固定、无 out_of_scope 时段落不消失（落占位行）、验收标准段搬运成功标准条目、新段进得去冻结的 SOW 快照（可导出）。既有 `test_goal_d2_s0_closeout.py` 追加 T-A5 断言（行业模板路径同样受益）；`test_delivery_compiler.py` / `test_project_solutions.py` / `test_solution_validation.py` 零回归（**36 passed**）。

**CI 实测口径**（#172 PR-head CI run 42277662998）：pytest **2062 passed + 6 skipped**（2068 收集）／vitest **862**（70 文件，桌面零改动不变）／mypy 279／路由 **304**（零新增路由）／零迁移零新表零新字段。


### T-A6 报价 claims 核验 → 冻结 SOW 的桌面闭环 — **已实施并合并（2026-11-07 PR #175 → `0a7806b`，见下）**
- 目标：售前能自己把报价从「估算」推到「核验通过」，并在核验通过后冻结导出 SOW，**不依赖工程师介入**。
- 现状实测：`server/src/fde_api/projects/quote_service.py` 链完整——`:137` B 层系数 = 0.9 + 总分×0.03；`:226` `_advance_claims` 逐字段推进 estimated→claimed；`:581` finalize；`:861` `claims_summary`（accepted/total）；`solutions/service.py` `export_sow` 强制传已冻结版本（AI 不二次改写）；`api_catalog.py:79` 建交付包需 `solution_id + quote_id`。
- 修改文件：`desktop/src/renderer/src/projects/CommercialBoard.tsx`（既有报价/收款/合同面板已含 `calibrate`/`finalize`/`render` ⇒ **本条是补齐状态推进与门禁提示，不是新建面板**）。
- DB：无。API：无新增。
- 测试：桌面 vitest（claims 未核验时导出 SOW 按钮禁用并给出缺项清单；核验后放行）。
- 验收：售前独立完成「报价核验 → 冻结 SOW」全链；未核验时导出被服务端闸拦住。
- 回滚：revert 单 commit。风险：低。依赖：T-A5。复杂度：**S**。

#### ✅ T-A6 实施轮（2026-11-07，状态：**已实施并合并**——PR #175 → `0a7806b`，CI run 42308398276 4 job 全绿，vitest 870；服务端零改动）

- **实施轮勘误（与登记原文三处出入，实测 `fork/main@39e6ed0` 后回写）**：
  1. **「未核验时导出被服务端闸拦住」不成立**——`export_sow`（`solutions/service.py:676`）服务端只有两道闸：AI 协同终审拍板（`solution_signoff_required`）与 design 必填（`solution_design_required`），**不查报价**（有意设计：SOW 是给客户的谈判材料，导出时报价常还在谈）。真正的报价闸在**交付包链路**：建包要求 `solution_id+quote_id`（`dispatch/routes.py:99`），发布要求 quote finalized（`dispatch/packages.py:267`，422 `quote_not_finalized`）+ 首单成交回填前必回校（`quote_service.py` `calibration_required`）。
  2. **「补齐状态推进与门禁提示」已是既有能力**——QuoteCard 既有 claims 逐字段推进（estimated→claimed→measured→accepted）、回校缓冲、成交回填、数字全核验徽标；本条**不是**补这个。
  3. **真正的缺口：建交付包桌面零入口**——`POST /api/v1/dispatch/packages` 全桌面零调用（只有 GET/publish/withdraw/offers 等），售前从「报价核验通过」到「交付包创建/发布（冻结快照）」的链在这里断。「冻结」语义 = publish 时快照哈希（`packages.py:66` `_snapshot_payload` §2.3 逐字段清单一次冻结）。
- **实施轮实际改动（桌面两处，服务端零改动零新 API）**：
  1. `desktop/src/renderer/src/solutions/SolutionDetailPage.tsx`——新增 `DeliveryPackageLauncher` 区块（方案详情页「建交付包」）：拉项目报价列表（`GET .../quotes`），默认选中 finalized 报价；草稿报价选项禁用；无 finalized 报价时给出可读清单（含跳「报价收款」页链接）并禁用创建按钮——**前置同口径闸提示**，不等服务端 422；提交走既有 `POST /api/v1/dispatch/packages`；错误映射 `package_exists`（已有包引导去调度台）/ `verifier_role_required`（权限说明）。挂载条件 `canManage && status !== 'archived'`。
  2. `desktop/src/renderer/src/projects/CommercialBoard.tsx`——QuoteCard finalized 后显示「下一步」引导行（跳方案设计页建交付包，说明发布时冻结快照与既有闸），链接 `#projects/{id}?tab=delivery`。
  3. 样式：`solutions.css` `.solution-package-launcher` 标题行对齐 `.solution-view-associated`；`styles.css` `.quote-next-step`。
  - **辅助入口不阻断主内容**：报价列表拉取失败静默降级（与 `SolutionHealthChip` 同纪律）；既有 42 例 solution-design 用例零回归。
- **测试**：`desktop/tests/renderer/solution-design.test.tsx` 新增 **5 例**——finalized 报价默认选中 + 草稿选项禁用 + `POST /dispatch/packages` 带 `solution_id+quote_id`、无 finalized 时可读清单 + 按钮禁用 + 零建包请求、只读用户与弃用方案隐藏区块、`package_exists`/`verifier_role_required` 中文呈现、报价卡 finalized 引导行（草稿报价不出现）。定向回归 **47 passed**（42 既有 + 5 新）；typecheck 全绿。
- **验收对照**：售前独立完成「报价核验 → 冻结 SOW」全链 = claims 推进（既有）→ 成交回填（既有）→ 方案详情建交付包（本轮新增入口）→ 调度台发布冻结快照（既有）；未核验时**建包入口前置拦截**（服务端 publish 闸 `quote_not_finalized` 兜底，口径同源）。

### T-A7 客户谈判版本管理（方案版本快照不可变，谈判稿与最终 SOW 分离） — **已实施并合并（2026-11-07 PR #178 → `9267240`，见下）**
> 分工注记（2026-11-07，§拍板闸 6⑨ 蔡工拍板逐字「T-A7另外一个会话在做」）：本条目由**并行会话**实施（#178 桌面实施与 #179 补账均已合并）；goal-ta 收尾会话对本条目**零触碰零实现**，仅留本事实注记，不重写其任何段落。
- 目标：谈判过程中的多版方案可追溯，**最终 SOW 只认冻结版本**，谈判稿不进 SOW。
- 现状实测：solution 版本冻结与 `export_sow` 强制传 version **已具备**（`solutions/service.py`）；缺的是**谈判稿与正式方案的分离位**与桌面呈现。
- DB：无（✅ 2026-11-06 拍板，§拍板闸 6③：**复用既有 solution 版本行**——谈判稿=未冻结版本，桌面把未冻结版本标注为「谈判稿」；**零新表零迁移**，独立谈判稿表=重复建模）。API：无新增。
- 测试：桌面 vitest（谈判稿不出现在 SOW 导出内容中；版本快照只读）。
- 验收：SOW 内容与所选冻结版本逐字一致；谈判稿可在版本列表中追溯但不可导出。
- 回滚：revert 单 commit。风险：低。依赖：T-A6。复杂度：**S**。

#### ✅ T-A7 实施轮（2026-11-07，状态：**已实施并合并**——PR #178 → `9267240`，CI run 42318566336 4 job 全绿，服务端零改动）
- **合并过程**：首版 sha `39eff6c` 的 desktop job 秒败——CI typecheck 抓到 `DocumentScopeRef.opportunity_scope` 声明过窄（测试 fixture 的 scope 字面量带 `opportunities: []` = 真实 `DocumentSummaryDto` 形态，TS2353 excess property；本地提交前未重跑 tsc 属流程失误）。修复对齐桌面主类型形态后 sha `262bcef` 重推，4 job 全绿。本地 vitest 不跑 tsc，**CI typecheck 是唯一硬闸**——桌面改动提交前必须本地 `npx tsc -p tsconfig.web.json --noEmit`。
- **CI 实测口径**：#178 PR-head run 42318566336（sha `262bcef`）vitest **882 passed**（71 文件 = 基线 870 + 12 新增）／pytest server-tests pass（服务端零改动不变）。
- **实施轮勘误（与登记原文三处出入，实测 fork/main@ef1b4d0 后回写）**：
  1. **「谈判稿与正式方案的分离位」不需要新实体**——solution 是单行 + 乐观锁整数 version（无版本历史表）；「冻结」语义已承载在 `project_solution_exports`（`(solution_id, solution_version)` 唯一键，每修订一份不可变 SOW 快照）+ 文档版本 `content_snapshot_json.solution` 逐字快照。登记所缺的「分离位」实为**桌面可见性**问题，不是数据建模问题。
  2. **「谈判稿可在版本列表中追溯」数据源已存在**——`GET /documents` 摘要序列化器（`draft_service._serialize_document_summary`）自带 `opportunity_scope.solution.{id,version}`（export_sow 每次导出都更新为导出时刻的方案版本）⇒ 桌面从既有接口即可反查「最新冻结进 SOW 的方案版本号」，**零新 API 成立**。
  3. **「谈判稿不出现在 SOW 导出内容中；版本快照只读」服务端已钉住**——`test_sow_export_freezes_saved_solution_without_ai_and_reuses_revision`（test_project_solutions.py:126-177）断言快照取导出时刻内容、后续修改不回流、草稿改写 409 `solution_source_readonly`、revise 伪快照 400 ⇒ 本轮**不重复实施服务端**。
- **实施轮实际改动**（桌面两文件 + 新增纯函数模块，服务端零改动零新 API 零迁移）：
  1. **NEW `desktop/src/renderer/src/solutions/frozenVersion.ts`**——`frozenSolutionVersion(documents, solutionId)`（从文档列表反查最新冻结方案版本，含 archived 快照=历史冻结事实，取最大版本号，忽略畸形 scope）+ `solutionVersionBadge(solutionVersion, frozenVersion)`（三态徽标：已冻结进 SOW / 谈判稿·已修改 / 谈判稿·未导出）。
  2. **`SolutionDetailPage.tsx`**——详情页头部加冻结状态徽标（复用全站 badge success/warning/muted 三档）；数据加载并行拉 `/documents`（**辅助数据源，失败静默降级**——SolutionHealthChip 同纪律）。
  3. **`SolutionExport.tsx`**——导出弹窗类型补 `solution_version` + `reused`（服务端 `_serialize_export` 本就返回，桌面此前未声明未展示）；弹窗文案明示「本 SOW 快照冻结的是方案 vN 的内容」+ reused 时「复用既有快照」。
- **既有产品决策裁决（防预取回归）**：方案**列表页**不加冻结徽标——既有用例 `uses the shared file library behind a collapsed SOW-only entry without creating documents here`（solution-design.test.tsx:184）钉住「列表页不预取 `/documents`」（SOW 文件懒加载契约）；冻结状态只在**详情页**呈现（决策点在详情：用户正要导出/建包时最需要知道冻结状态）。
- **测试**：NEW `desktop/tests/renderer/solution-frozen-version.test.tsx` **7 例**（反查空/非 SOW/多文档取最大/畸形 scope 忽略；徽标三态+防御性回退）；`solution-design.test.tsx` **+5 例**（详情页三态徽标 + `/documents` 拉取失败静默降级 + 导出弹窗版本明示与 reused 文案 + 弃用方案徽标保留）；桌面全量见 CI 实测。

### T-A8 agents run 列表 + meetings 会议纪要 两个桌面控制台 — **已实施并合并（2026-11-07 PR #182，含 #171 复核清单桌面收口，见下）**
- 目标：让售前与专家**看得见**智能体干了什么——「人看不见的自动化等于没有自动化」，这是「多养售前、少量专家」组织形态的前提条件。
- 现状实测（fork/main@d3adf1c）：`server/src/fde_api/agents/routes.py` **11 条**（list agents / run / run 详情 / handoff / retry / tool-calls / cost / fallback-rehearsal / recover / pilot-report / quota）、`server/src/fde_api/meetings/routes.py` **10 条**（创建/详情/插话/关闭/纪要/模板/清单/暂停/恢复/成本）——**两者均无列表端点**（`GET /agents/runs` 与 `GET /meetings` 零命中）⇒ **「服务端零改动」不成立**，列表 UI 无数据源。
- 修改文件：`server/src/fde_api/agents/routes.py` + `server/src/fde_api/meetings/routes.py`（**各补 1 条只读列表路由**）；`desktop/src/renderer/src/` 新建 agents/meetings 控制台页（样式参照既有 `workflows/WorkflowConsole.tsx`）。
- DB：无。API：**+2**（`GET /api/v1/agents/runs` 按 project/status/时间过滤＋分页；`GET /api/v1/meetings` 按 project 过滤）。
- 测试：服务端（列表权限 can_view / 局外人 403 / 分页上界 / 列表行不带嵌套详情防 N+1）；桌面 vitest（run 详情 / tool-calls / cost 三面板渲染）。
- **与 B#9 的关系（防重复立项）**：B#9 只读执行事实链面板（项目 tab「执行事实」，`GET /projects/{id}/execution-facts`，三源聚合 `project_evidence` + `operation_events` + `ai_call_audits`）**已于 2026-11-06 实施**（路由 +1=301，pytest 1985=1979+6s，桌面 `evidence/ExecutionFactChain.tsx`）⇒ **两者数据源与用途不重叠**（本条=智能体运行态与协作过程；B#9=证据/审计事实链）⇒ ✅ **已拍板（2026-11-06，§拍板闸 6⑥）：同 PR 批次交付、界面分离**（服务端都只是只读路由，合批省一轮 PR；数据源与用途不重叠，界面分离防认知负担）。
- **字段边界**：run 详情 / tool-calls / cost 三面板用现有单详情接口即可渲染；**diff / test_results / commit / known_risks 缺失**属 T-B1 artifacts 扩列范围，**不阻塞本条**。
- 验收：售前能在桌面看到 run 列表→详情→tool-calls→成本，以及会议纪要。
- 回滚：revert 单 commit（+2 路由零迁移可整撤）。风险：低。依赖：可与 T-A5..T-A7 并行。复杂度：**M**。

#### ✅ T-A8 实施轮（goal-ta2，2026-11-07，#171 复核清单桌面收口同批——**已实施**，状态与 CI 口径以 CHANGELOG 同名节为准）
- **服务端 +2 只读列表路由（零迁移零新表）**：`GET /api/v1/agents/runs`（`project_id`/`status`/`created_from`/`created_to` 过滤＋`limit`(1..200，默认 50)/`offset` 分页＋`truncated` 取 limit+1 行诚实标记）＋ `GET /api/v1/meetings`（`project_id` 过滤＋同款分页）。**有意不进 api_catalog**（人工控制台面，沿 T-W6 workflow 列表与 B#9 execution-facts 先例；ENTRIES 94 不变）。
- **可见性单一权威**：NEW `projects/permissions.py::visible_project_ids`（跨项目聚合时逐项目复用 `project_access` 判定，不在 SQL 重写第二套可见性规则）；单项目查询走既有 404（不存在）/403（can_view=False）两段语义。
- **防 N+1**：runs 列表行 = `_serialize_run(detail=False)`（纯列读，无 `agent`/`artifacts` 键）；meetings 列表行 = `_serialize_meeting(with_turns=False, turns_count=预聚合)`（无 `turns` 键；话轮计数走**单条分组查询**，替代逐行 SELECT——`_serialize_meeting` 加 `turns_count` 可选参，既有端点行为零变化）。详情/工具调用/纪要走既有单实体端点按需取。
- **桌面双控制台**：NEW `desktop/src/renderer/src/agents/AgentsConsole.tsx`（run 列表＋成本汇总头＋详情展开=run 详情[agent 名/产物指纹/复核态]＋工具调用表[放行/拦截]）＋ NEW `desktop/src/renderer/src/meetings/MeetingsConsole.tsx`（会议列表＋详情展开=话轮流＋**closed 会议才拉纪要**三段式呈现[共识/分歧/待办+sealed 指纹前缀]）；项目 tab 11→13（「智能体」「评审会」挂「工作流」之后）。**拍板 6⑥ 界面分离维持**：本两页=智能体运行态/协作过程，B#9「执行事实」tab 不动。写操作（handoff/retry/召集/收敛）不在控制台，403/409 原样呈现。
- **#171 复核清单桌面收口（同批）**：`GuidanceReview` 消费 `get_analysis.redaction_review`（**服务端唯一投影，前端不二次推导文本**）——清单非空时呈现条目（名称/次数/词典命中徽标）；confirm 撞 409 `redaction_review_required` 时呈现拦截提示，勾选「已复核」后重发显式 `redaction_reviewed: true`（路由只认字面 true）；干净分析 confirm **不带该键零额外负担**；本地读面缺清单时 409 触发单次回读读面（仍用服务端投影）。types.ts 增 `redaction_review?`（旧载荷无键兼容）+ `isRedactionReviewEntries` 守卫（畸形条目整组丢弃，fail 向保守）。
- **B#9 断言钉（同批）**：`test_execution_fact_chain.py` 增 `guidance.redaction_review` 事件钉——事件元数据（event_type）在事实链时间线可见，`changes.entries`（疑似企业名正文）**绝不外泄**（该事件 changes 携带未收录疑似名，泄露即破客户资料红线）；与既有「changes 不外泄」钉形成双钉。
- **测试**：服务端 NEW `test_agents_meetings_lists.py` 5 例（可见项目聚合+形状面/局外人 403+未知项目 404/status·时间过滤+分页校验+truncated/会议 turns_count 预聚合+行形状/未认证 401）＋事实链 +1 钉；桌面 NEW `agents-console` 6 例＋`meetings-console` 5 例＋`guidance-redaction-review` 4 例＋project-detail tab 清单钉同步（11→13 项）。变异四连全红→还原绿：M1 摘 can_view 闸（403 用例红）/ M2 摘 limit 上界（400 用例红）/ M3 serialize_fact_event 外泄 changes（**双钉齐红**）/ M4 桌面摘 ack 携带（409 用例红）。
- **口径勘误（教训 48：只认 CI 实测）**：#179 bullet 记桌面基线 882 已陈旧——main CI 实测（#179 合并 run 与 #180 PR-head run 双源）= **71 文件 887**；#181 后基线=**72 文件 897**（close-guard +10）。服务端基线 main@677746c 实测 **2067 passed + 6 skipped**。本轮 PR 预期：pytest **2073+6s**（+6）/ vitest **912**（75 文件）/ 路由 305→**307**（审计清单已重生成：route CSV +2 行、blueprint 41、表 105、36 rev、head `b2e8f4a6c9d3` 不变、DB CSV 零变化）。

### T-A9 录音转写草稿区 + 人工整理晋升机制（ASR 通道另立项） — **✅ DONE（实施轮 goal-tb tb1，2026-11-07，见文末实施记录）**
- 目标：录音场景下，**转写结果只落草稿区**，售前人工整理为访谈纪要并经客户确认后才入正式库。
- **红线依据（逐字）**：`D:/test/FDE/engagements/openfde/engagements/somwyn/raw/2026-10-27-FDE接触调研阶段资料入库SOP设计.md:109`「初诊录音转写（⚠️ **只转写不入正式库**，且必须先获口头同意）」、`:111`「**S2 明令「不录音转写入库」**…**边界是：企业主动发给你的文字可以存；你录的音不能存。** 这条线要守死」⇒ v1.1 原结论「转写文字可入库」**作废**（v1.2 §10 Q2 已改判）。
- **ASR 通道现状**：`server/src/fde_api/ai/kimi.py:39-43` MiniMax 官方 purpose 枚举共 5 项（`voice_clone` / `prompt_audio` / `video_understanding` / `t2a_async_input` / `video_generation_input`），**无音频转写项** ⇒ **ASR 通道需独立立项**（本条只登记工作台侧承接机制）。
- 修改文件：草稿区实体 + 清理作业（**独立表 + 独立文件根，物理隔离**）；presurvey 录入卡新增转写上传入口。
- DB：新表（草稿区；**T+7 自动清理**，草稿行**不可被方案/报价/SOW 引用**）；API：草稿写入/读取（**不进 api_catalog**）。
- 测试：服务端（草稿不可被正式库引用；清理作业按 T+7 生效；晋升须带客户确认人/时间戳/确认方式）；转写文本**同样过 T-A2 代号化管线**（不因「草稿」豁免）。
- 验收：草稿与正式库物理隔离；无客户确认的转写文本**无法**进入正式库。
- 回滚：alembic downgrade。风险：低。依赖：T-A2 + ASR 通道立项。复杂度：**M**。
- 闸：**ASR 通道立项并跑通**；且须先获**客户口头同意**方可录音。✅ **立项半已批（2026-11-07，§拍板闸 6⑨蔡工拍板「立项」）**：立项文档=`docs/architecture/录音转写ASR通道立项-v1.md`（红线锚点逐字引用 + 现状行级实测 + 通道选型拍板项清单 P1–P6，推荐本地 ASR 先行）。✅ **选型已拍板（2026-11-07，§拍板闸 6⑩，蔡工「ASR 通道选型：按你建议实施」）**：P1=opt-L 本地 ASR 先行，P1–P6 逐项落定见立项文档 §3.3.1（委托先例：按推荐项执行、留痕可推翻）。✅ **「跑通」半已闭合（横评真机实测随实施轮完成）**——客户口头同意属现场运营前置（录音发生前逐客户取得），平台侧已以 UI 注记钉住（「只收文本，录音原件永不进平台」）。
- **实施记录（goal-tb tb1，2026-11-07，PR 见 CHANGELOG 同名节）**：
  - **选型落定**：P1–P6 按推荐项落定（§拍板闸 6⑩）；横评报告=`docs/audit/ASR本地引擎横评-2026-11-07.md`——faster-whisper base 档（int8/CPU）中文 CER 8.6%、中英混说 6.5%、4× 实时（1h 访谈≈15min 出稿），胜出 whisper.cpp 同档（速度 1.5×于其、精度相当）；FunASR 因 torch 依赖过重不实测（如实注记）；测试音频=TTS 本地合成虚构文本（零客户资料），CER 经 OpenCC 繁简归一。
  - **DB（迁移 `d7b2f8a4c1e6`，36→37 rev，additive）**：`transcript_drafts`（草稿区，状态机 draft→promoted|expired|discarded，墓碑化清空正文/指纹/复核条目，7 条 CHECK 含「晋升必带三要素」「活动草稿必有正文」「墓碑必无正文」）+ `interview_minutes`（正式库，客户确认三要素 NOT NULL + redaction_hits 计数）；**物理隔离机械钉**=全库零外键指向 transcript_drafts（minutes.draft_id 纯字符串指针，metadata 扫描测试钉死）。
  - **API（7 条新路由，不进 api_catalog）**：草稿 POST/GET list/GET detail/discard/promote + 纪要 GET list/detail；权限=草稿读写 can_view（T-A3 校准「录入 member 已可用」同构）、晋升 can_manage；列表有界分页（50/200+truncated）、行不带正文。
  - **T-A2 代号化不豁免**：create/promote 两处 title/content/确认人文本先过 `redact_text_detailed`（词典命中→enterprise_code 首段代号、疑似同样替换）；词典不可用 fail-closed 503 `pseudonym_dict_unavailable`（guidance 同码）；复核条目（#160 同形状 name/occurrences/matched_dict）随草稿行存储+详情回显，墓碑时一并抹除；正式库只留命中计数。
  - **T+7 清理**：`purge_expired_drafts` 接入 cli scheduler 循环（与过期清扫/退避提醒同拍），到期活动草稿墓碑化+独立文件根（`FDE_TRANSCRIPT_DRAFT_ROOT`，默认 `.fde-transcript-drafts`，与 .fde-storage 不共根）子树删除；settings 注入参供调度外调用；skip_locked 防并发互堵。
  - **桌面**：NEW `transcripts/TranscriptDraftsPanel.tsx` 挂 overview tab guidanceSlot（presurvey 录入卡旁）——本地文件导入（只读文本进表单，原件永不上传）、草稿列表/详情（正文+复核清单徽标）、弃置、晋升表单（canManage 显隐同构）、纪要正式库列表/详情；加载失败 fail-静默（教训 51：不与页面级 alert 抢道），动作错误 alert 呈现。
  - **测试**：服务端 NEW `test_transcript_drafts.py` 8 例（代号化/fail-closed/权限 403-404-401/列表形状/晋升三要素四连 422+未来时戳 422/墓碑/T+7 清理幂等/零外键隔离钉）；变异三连全红→还原绿（摘三要素校验红/代号化改直通红/清理谓词取反红）；桌面 NEW `transcript-drafts-panel.test.tsx` 7 例。

### T-B1 agent_artifacts 扩列（diff/test_results）+ 产物→`handover_packages` 闭环 — **✅ DONE（扩列半 goal-tb tb2 #189 / 封包半 goal-tb tb4，2026-11-07，§拍板闸 6⑪ 委托拍板解封）**
- 目标：run 产物从「有 sha256 但无结构化内容」变成可封包的结项交付物。
- 现状实测：`agents/models.py:127` `AgentArtifact` 现有 `storage_ref`（指针）+ `sha256`（指纹）+ `kind` + `reviewed`，**无 diff / test_results 结构化列**；`dispatch/models.py:40-78` 已有 **`delivery_packages`（派单态，8 态机 + package_code + dispatch_round 唯一键 + sow_type）**；结项态交付包为台账 `docs/后续需求台账-F5与D11.md` §十三.4 **已裁决命名 `handover_packages`**（status draft→sealed→delivered + manifest_sha256 + 逐项 sha256 校验）⇒ **两包不可混用，产物闭环指向 `handover_packages`**。
- **落库形态纪律（借鉴登记 B#6《状态归属与对账-v1》§1 不变量「引用方永不复制真相，只持指针」）**：新列只能是**指针 + 指纹 + 可重建派生**——`storage_ref` 指向 diff/test_results 原件（留项目工作目录）、`sha256` 记指纹、结构化摘要（passed/failed 计数、退出码）为**可从原件重建的派生**；**不得复制原件进库**。
- **模块边界**：新列**只写不读**，dispatch 侧取数走 `project_evidence` 指针，避免 agents/dispatch/solutions 成环（否则须扩 `test_architecture_purity.py` 断言范围）。
- DB：**新迁移（additive-only）**——artifacts 加列 + `handover_packages` 新表；**不得修改已发布迁移**（README 纪律），`test_migrations` HEAD 钉同步，版本号同步（`desktop/package.json` + `server/pyproject.toml`），rebuild 后 `alembic upgrade head`。
- API：封包/解封/下载走新路由（**不进 api_catalog**——业务对象不走 change_set 双轨，沿用 `dispatch.packages_create` 的既有处理）。
- 测试：服务端（派生摘要可从原件重建、指纹不一致拒绝、封包逐项 sha256 校验、delivered 不可逆、权限闸）；桌面（封包清单呈现）。
- **封包前置**：✅ **D11 立项拍板已落（2026-11-07，§拍板闸 6⑪，蔡工「第3件需要拍板的按你建议处理」→ 按台账 §二草案+§十三.4 改名裁决执行）；「首批真实数据到位」按建议裁决＝不阻塞代码实现（测试合成 run 覆盖，投产使用自然等待真实 run）**。
- **封包实施记录（goal-tb tb4）**：
  - **DB（迁移 `e5f1a7c3b9d4`，38→39 rev，additive）**：`handover_packages`（draft→sealed→delivered + unseal 留痕 unsealed_count；**delivered 终态不可逆**；5 条 CHECK 含封存/交付完整性）+ `handover_package_items`（**指针+sha256 快照**，artifact_id 无 FK——B#6 真相原则，metadata 扫描钉死零外键指向 agent_artifacts；同包同产物唯一）。表名沿 §十三.4 改名裁决（与派单 delivery_packages 不混用）。
  - **API（+8 路由 315→323，不进 api_catalog）**：POST/GET list/GET detail/PATCH（draft 编辑）/seal/unseal/deliver + GET `handover-packages/artifacts`（挑选面=已复核产物投影）。权限=查看 can_view、创建/编辑/封存/解封 can_manage、**交付登记=admin 专属**（草案「delivered（登记对外交付）=admin」原样）。
  - **seal 语义**：冻结清单 + 逐项校验（存在/本项目/已人工复核〔与草案 status 闸同构〕/指纹一致 `fingerprint_drift` 409）+ `manifest_sha256`=清单规范化 JSON 哈希（测试复算钉死）。
  - **审计**：`handover_package_created/sealed/unsealed/delivered` 四事件（target=项目，changes 只带 id+元数据）。
  - **桌面**：NEW `handover/HandoverPackagesPanel.tsx` 挂 delivery tab（方案设计下方）——草稿组包（勾选已复核产物）/清单详情（指针+指纹）/封存/解封/交付登记（isAdmin 显隐）/manifest 指纹呈现。
  - **测试**：服务端 NEW `test_handover_packages.py` 6 例（快照+seal 冻结+manifest 复算/解封留痕/封包三闸/指纹漂移/deliver admin 专属+终态不可逆/读面权限+零外键隔离钉）；变异三连红→还原绿（摘 reviewed 闸/摘 admin 门/摘指纹校验）。桌面 NEW `handover-packages-panel.test.tsx` 5 例。**明确不做维持**：自动打包 zip、对外下载链接签名、合同条款联动。
- **实施记录（goal-tb tb2，2026-11-07，扩列半）**：
  - **DB（迁移 `b8e4d6f2a9c3`，37→38 rev）**：artifacts +`derived_summary` JSON 可空列（**可重建派生**——diff: files_changed/additions/deletions；test_results: passed/failed/errors/skipped+exit_code；解析不可达即零计数不发明数字；原件本体永不进库，B#6「指针+指纹+可重建派生」）+ `reviewed_by_user_id`（FK users SET NULL）+ `reviewed_at`；kind CHECK 置换扩 `'test_results'`（纯枚举扩展，T-J2 先例）。**`handover_packages` 表未建**（封包半挂 D11）。
  - **API（+1 路由 314→315，不进 api_catalog）**：`PATCH /agents/runs/{rid}/artifacts/{aid}` body `{reviewed: bool}`——can_manage（终审动作）；接受留 who/when，撤回清双痕；事件 `agent_artifact_reviewed` target=项目、changes 只带 id+布尔（不复制产物内容）。度量表「智能体产物被人工接受率」数据源自此存在（此前 reviewed 无写路径恒 0）。
  - **派生纯函数**：NEW `agents/artifact_summary.py`（`derive_artifact_summary(kind, content)`，2MB 解析上限；可重建性=同一原件二次派生逐位一致由测试钉住）；finalize 接线在产物入库同事务计算（exit_code 来自 run 结果合入摘要）。
  - **桌面**：AgentsConsole 产物行 +「标记复核/撤回复核」（canManage 显隐与 PATCH 闸同构；成功后重拉 run 详情回真不本地猜写）+ reviewed_at/derived_summary 呈现；版本号同步 **0.2.0→0.3.0**（desktop/package.json + server/pyproject.toml，登记原文要求的列车同步）。
  - **测试**：服务端 NEW `test_agent_artifact_acceptance.py` 5 例（diff 统计/测试计数+其余 kind 零派生+可重建一致性/PATCH 权限 403+双痕留清/跨 run 配对 404+非布尔 400+未知 run 404/详情扩列三键）；变异三连红→还原绿（摘 can_manage 闸红/撤回不清双痕红/跨 run 不校验红）。桌面 +2 例（canManage 显按钮+PATCH 形状/缺省无按钮）。
- 验收：一次 run 的产物可封包为 `handover_packages` 且逐项 sha256 可校验；原件不进库。
- 回滚：alembic downgrade（新表零外键依赖安全）；**已封包行不可逆**（指纹链已出系统，需人工处置）。风险：中（迁移纪律）。依赖：T-A8。复杂度：**M**。

### T-Z1 zcode 真机跑通 + 执行通道裁定 — **◐ 生产接线待实施（P2′① 宿主轮询代理——状态机咬合、领取/回执路由、H4 失联标记待实装）｜✅ dev 直连通道已实施并合并（2026-11-07 宿主裸跑态：agents/host_channel.py，config 默认关，pytest +22）**（沿革：实测半 DONE goal-tb tb3/#191 → 通道形态 DECIDED＝A〔20:08〕→ P2′ 咬合①〔20:38〕→ #193 契约层 zcode_contract.py 落地 → dev 直连通道实施轮落地）
- 目标：让编码智能体这条线**跑出真实证据**，同时**先实测再裁定执行通道形态**（不预先承诺复用 openfde）。
- **实测事实（2026-11-06 复审，登记为裁决依据）**：① zcode 装在 `D:/software/zcode`（Electron 应用 + 内置 CLI **0.17.1**），**不在 PATH** ⇒ 需 wrapper；② **provider 根因＝查找路径错位，非文件缺失**——`zcode-builtin.json` 实存于 `resources/config/provider/`（约 260KB / 35 templateId），而 CLI 查的是 `resources\glm\provider\` 与 `D:/config/provider/`（两者不存在）⇒ 修复＝部署一份到 `D:/config/provider/`；③ **`ZcodeAdapter` 契约错位**——`agents/adapter.py` 的 `spawn_argv` 按 `zcode run --task --output --events ndjson` 调用，**真实 zcode 0.17.1 无 `run` 子命令、无 `--task`/`--events`**，真实形态为 `zcode -p/--mode/--json/--cwd` 或 `zcode app-server`（stdio ZCode Protocol）⇒ **适配器 CLI 调用段必须重写**；④ **`--resume` 为布尔开关**（`[["--resume"],0]`，无 sessionId 取值）⇒ **「会话续接」能力未验证**（借鉴总览 §6.6 采集项口径：未核实则以降级路径为默认；B#2 repair 增强档维持降级）；⑤ `--json` 事件流格式**未实测**（实跑被 429 截断）。
- **执行通道关键实测（登记为开工前置）**：服务端跑在 Linux 容器内，**subprocess 够不到任何宿主侧编码 CLI**——`server/src/fde_api/bridge/__init__.py:3-8` 明示「openfde CLI 是宿主侧 Windows Node 工具（better-sqlite3 按 Win 编译 + pnpm/tsx），Linux 容器 subprocess 不到它——采集在宿主侧」；zcode 同为 Windows 宿主侧 Electron 工具 ⇒ **「工作台 Flask 侧直接 spawn zcode」不成立**，编码执行必须落在宿主侧进程空间。
- **第三阶段开工前的半天实测（必做项）**：**zcode 能否进 `sandbox-runner` 容器内执行**（`compose.yaml` sandbox 服务：`privileged: false` + `network_mode: none` + `tmpfs /workspace:size=512m`）。**能** ⇒ 容器内直连 `ZcodeAdapter`（方案 §5.3 沙箱红线完整成立，且不引入第二运行时）；**不能** ⇒ 在「给 openfde 加 zcode executor」与「自建 Windows 宿主侧 zcode 代理」之间定稿（两条都须先扩写通道授权并修 AGENTS.md「bridge 只读」红线，且按借鉴登记 B#35 登记 openfde 版本/许可/快照日期——实测 MIT、HEAD `a54be6c` 2026-10-27，距今未超 30 天失效线，**当前未登记**）。
- 修改文件：`agents/adapter.py`（CLI 调用段重写）；`docker/sandbox/Dockerfile`（zcode 0.17.1 CLI + provider 配置打进镜像或 wrapper 注入）；宿主侧代理脚本（路径待实测裁定）。
- DB：无。API：无新增。测试：适配器契约用例（真实 CLI 形态的 spawn 参数断言）；**实机跑通 ≠ 可回归测试**——事件流契约须以固定夹具回放方式落 pytest（借鉴登记 B#14 executor 对抗性测试组织，**其前置「决策逻辑抽纯函数重构」不在本条范围**）。

#### ✅ 实施轮（T-Z1 裁定 A 宿主通道，2026-11-07，feat/host-zcode-channel）

- **商用前置改判（用户拍板 2026-11-07）**：目前仅开发、尚未推向市场 ⇒ 暂不申请商用授权；**推向市场前须取得 zcode 供应商书面授予**（挂账保留，时点前置）。
- NEW `agents/host_channel.py`：宿主侧 zcode 代理——0.17.1 实测契约（`-p <task书路径> --json --cwd <workspace> --mode build` + `ELECTRON_RUN_AS_NODE=1`）；`--json` 单对象汇总解析（fail-closed，不伪造 completed）；超时=kill+communicate 回收（PIPE 不死锁）；预算超限按上限截断报 budget_exceeded（对齐容器版 B-2「越界不入账」）；**零凭据注入**（解密结果不进 argv/env/磁盘；出现未用凭据标 degraded 走 L1 强制人工终审）；workspace 拒绝清单复用 `FORBIDDEN_MOUNT_MARKERS`。
- 接线：config 新增 `agent_host_channel_enabled`（**默认 False**——容器内 server spawn 不到宿主桌面进程，仅宿主裸跑态开启）/`agent_host_zcode_bin`/`agent_host_zcode_cjs`（缺失时 503+L2 零计费 fail-closed）；`_execute_run` 开关分支产出与容器适配器同构 `AgentRunResult` ⇒ `_finalize`/C-1/T2 门/回执语义零改动复用；容器路径与虚构契约 `spawn_argv` 不动（T-Z1 裁定维持降级现状）。
- 测试 pytest **+22**（test_host_channel 19：argv/env 契约逐位/拒绝清单/--json 解析四态/超时/预算/凭据零外泄/spawn OSError；test_host_channel_service 3：开关关=容器路径零变化/开=宿主成功+落账/bin 缺失=L2）；变异四连全红→还原绿（M1 拒绝清单失效/M2 超时不 kill/M3 预算截断失效/M4 fail-closed 失效）。诚实缺失：宿主版无逐事件流 ⇒ tool_calls 恒空、运行期无逐工具留痕（模块 docstring 差异 2 登记）。
- DB 无迁移无新表；API 零新增路由（复用既有 POST /agents/{id}/run）；桌面零改动。server 变更 ⇒ 合并后 rebuild 三镜像（alembic 幂等 no-op）。

#### ◐ 实施轮 2（P2′① 生产接线·服务端咬合半，2026-11-08，feat/host-p2-claim-receipt）

- **范围（§11.3 六条约束 → 代码）**：迁移 `f6d3a9c1e7b2`（status CHECK 加 `host_running` + `execution_provider`/`host_claimed_at`/`host_token_hash`/`host_receipt_at`/`host_lost_at` 5 列）；三条宿主机器面路由（`GET /agents/host/status`、`POST /agents/host/claim`〔FIFO+skip_locked+幂等重领〕、`POST /agents/host/runs/{id}/receipt`〔终态与容器对齐 + 产物宿主侧 sha256 直录，`host:` 前缀指针〕）；发起侧 202 受理分支；`mark_host_lost` 失联只标记（H4）；config 三字段（默认全关）。pytest **+16**（test_host_poll.py）。
- **形态边界**：本半完成的是**服务端咬合面**（状态机+路由+落账）；**宿主代理进程本体**（轮询循环→spawn zcode→回执的独立进程，任务书 §9）仍待实施轮 3；`adapter_missing` 生产启用闸维持到「①实装 + D3 书面回执 + N2 联调签核」齐备。
- **与 V3.1 P1-1 分工**：授权票据（5.3）/execution_policy 命令白名单（5.4）/artifact size·mime·revoked 扩列（5.7）/RunEventProvider 协议替换 spawn 段（5.2 重构）归 V3.1 线（gap-register D-3 建议已消费 feat/host-zcode-channel 产出）。
- 验收：① zcode 在隔离环境内完成一次非交互执行并产出可校验产物；② `--json` 事件流格式取得实测样本并落夹具；③ 执行通道形态经实测裁定并回写本条。
- 回滚：适配器改动 revert 单 commit；镜像版本回退。风险：**高**（依赖外部 CLI 行为与配额）。依赖：T-B1。复杂度：**L**。
- 闸：**开工前须拍板**——① zcode 会话续接核查 + 商用条款核验（借鉴总览 §6.6 采集项 + 方案 §5.2 必答项）② 执行通道形态（实测后）③ 降级声明：zcode 若始终跑不通，kind 维持 `adapter_missing`，**不阻塞第一阶段主线**。
- **实测记录（goal-tb tb3，2026-11-07，报告=`docs/audit/T-Z1-zcode真机实测与通道裁定提案-2026-11-07.md`）**：
  - **闸①会话续接核查 ✅**——0.17.1 实测 `--resume <sessionId>` 为**取值开关**（本条登记原文「布尔开关」记载过时，勘误入档）+ `-c/--continue` 在；真机双跑验证同 sessionId 上下文携带（`--json` 汇总 payload 648B 样本存本地 tz1-probe，永不进仓）。**闸①商用条款核验 ⚠️**——zcode 本体无独立 LICENSE 授予文件（仅 Electron/Chromium 第三方许可+NOTICES 组件清单）；商用集成前须向供应商书面确认，如实挂账不代决。
  - **闸②实测证据**——容器内直跑四重阻断（node 20 缺 `node:sqlite`〔node:24-alpine 实测可跑=JS 层唯一硬阻断〕/ provider 配置缺 / 登录态缺 / `network_mode: none` 零 egress）；`--json` 实测为**单对象汇总**（非 ndjson 事件流；粒度事件流在 app-server stdio 协议）——适配器契约含义一并勘误。**裁定提案**：A=宿主侧 zcode 代理（推荐，零 sandbox 基座变更，沿 bridge-poll 宿主纪律）/ B=openfde 加 executor（须补 B#35 登记）/ C=容器内直连（不建议）；**无论 A/B 均须先办 AGENTS「bridge 只读」红线修订 + 商用条款确认两件拍板**，办结前编码执行通道维持 `adapter_missing` 降级（闸③原样生效）。
  - **适配器契约勘误（登记原文③④⑤三处）**：无 `run` 子命令（`-p` 单发）；`--resume` 取值；`--json` 单对象汇总。适配器 CLI 段重写随通道拍板后的实施轮执行（本实测轮零代码）。
- **拍板落地（2026-11-07 20:08，用户「D1–D3 按你推荐的拍板」；留痕 `docs/audit/D1-D3拍板留痕与实施轮交付-2026-11-07.md`）**：
  - **D1＝A 宿主侧 zcode 代理**（B 降为可选演进、C 否决）；**D2** AGENTS.md「bridge 只读」红线已显式扩写宿主侧写通道授权＋五条边界；**D3** 商用条款按「供应商书面确认后方可商用集成」拍板——**决策已定，外部书面回执仍缺**，回执到位前生产启用闸不解除。
  - **登记原文「修改文件」行口径校正**：`docker/sandbox/Dockerfile` **不再承载** zcode CLI／provider 镜像钉定（A 通道下 zcode 不进容器）；钉定对象改为宿主侧代理进程，`docs/试点前联调-iptables与zcodeCLI-检查单.md` 二表同步改写。
  - **本轮可独立验证的技术资产（零生产链路改动）**：NEW `agents/zcode_contract.py`（真实 CLI argv 生成 + `--json` 单对象汇总解析 + 汇总→监听段事件映射，纯函数零副作用）＋ NEW `server/tests/fixtures/zcode_json_summary.json`（脱敏夹具）＋ NEW `test_zcode_contract.py` 契约用例；供宿主代理与适配器实施轮共用同一形状，避免两边各写一套。
  - **`spawn_argv` 未机械改写的理由（防假象）**：A 通道下服务端容器的 `sandbox.exec → zcode` 整段执行位置不成立，只把 argv 从 `run --task --events ndjson` 换成 `-p --json --cwd` 会制造「契约修好了但仍跑不通」的假象；`adapter.py:93` 已加定向警示注释指向新契约模块，**spawn 段整体重划随 P2′ 架构决策执行**。
  - **P2′ 咬合方式 ✅ DECIDED（2026-11-07 20:38 用户「确认」按推荐）＝① 宿主轮询领取**：宿主→服务端**单向**（容器不反向连宿主）；领取／回执两条写路由**幂等且复用既有鉴权**，状态机纳入 `queued`／`host_running`；超时失联**只标记不自动重试**（H4）；凭据只在宿主内存管道、零落盘，客户真实资料零外发；`zcode_contract.py` 为**唯一 argv／汇总形状来源**。② 常驻长连接否决、③ 人工中转仅作①上线前降级验证。**形态层开工闸已解除，接线实装仍待实施轮**；`adapter_missing` 维持到「① 实装 + D3 书面回执 + N2 联调签核」三者齐备。〔20:08 原文「新识别待拍板、不预设形态」保留作决策沿革〕决策卡见台账 §11.3／本轮报告 §4。
  - **降级声明不变**：接线未实施 + D3 回执未到位期间，`kind` 维持 `adapter_missing`，**不阻塞第一阶段主线**（登记闸③原样生效）。

### 售前主线的度量口径（登记即声明，防「看起来达标」）

| 指标 | 数据源 | 可反证 | 口径 | 备注 |
|---|---|---|---|---|
| 访谈 → 合格机会所需时间 | 调研表 revision 时间戳 | ✅ | live | — |
| 方案从访谈到 SOW 的时间 | solution revision 时间戳 | ✅ | live | — |
| G1/G2/G3 一次通过率 | gate revision | ✅ | live | — |
| 人工返工率 | revision 版本差 | ✅ | live | — |
| 编码智能体一次测试通过率 | **依赖 T-B1 扩 test_results ⇒ 数据源目前不存在** | ⚠️ 需先补字段 | live | T-B1 前不可作验收线 |
| 智能体产物被人工接受率 | **`agent_artifacts.reviewed` 无写路径 ⇒ 接受率恒 0** | ⚠️ 需先补写路径 | live | 待 T-B1 同轮补 |
| G9 结果验收线达成率 | G9 `exit_condition`（B#21 已接线） | ✅ 但**阈值 0.8 为占位待校准**（借鉴总览 R4 纪律） | live | `uplift`/`kpi_oracle` 服务端零命中 ⇒ 当前不可机器判定 |
| 每项目占用工程师小时数 | **仓库自标 simulation 口径** | ❌ | simulation | **不可作商业主张验证依据** |
| 交付毛利率 | 同上 | ❌ | simulation | **不可作商业主张验证依据** |

**出口指标（登记口径）**：一个**代号化仿真项目**从访谈走到合格方案 + 冻结 SOW，每一步都有来源、版本、责任人和证据；**智能体不能越权修改、不能部署、不能自动过门**。⇒ **真实客户项目不可作测试素材**（AGENTS.md「客户真实资料永不进 git 历史与远端」红线），真实项目后置替换。

**「客户现场问题数量」指标登记为删除项**（不报即达标的反向激励）。

## 开源借鉴清单登记（2026-11-05 消费登记轮 B#1–B#34 ＋ **2026-11-06 评审补登记 B#35–B#40**，登记轮零代码。当前：P0 先行批表 10 项 ✅ 已实施（#128~#131），其余按逐条状态标注——PROPOSED/冻结/封存/修复项）

> **🔒 B# 线 FREEZE（2026-11-07，演进方向评估 v1.1 §七 P1-5 拍板落地）**：B# 登记号**封顶于 B#40**——停止新增任何 B# 条目（含「补登记」「遗漏补登」形态）；既有 40 条仍按本节逐条状态为准继续实施/核销/封存，**冻结≠作废**。解冻条件（须同时满足）：①既有 40 条全部到达终态（已实施/核销/封存/冻结有因）；②出现**方法级**新借鉴需求（现有条目无法表达的机制/协议/契约，非同源新轮次）；③用户显式拍板解冻。《开源项目借鉴总览-2026-11-05.md》与其《实施实况报告》自此转为**只读档案**（内容不再修订；上游 LICENSE/HEAD 变动复核义务按 AGENTS 红线第 8 条④继续有效，不受 freeze 影响）。评估依据：`实况报告:14-15,86`「Top3 与 P1 主线已全部清完、无需开工项、不建议为做而做」；40 条中 33 条为静态判据。

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
| B#28 | 门禁精确 revision CAS + 生命周期版本隔离 | 代码+**迁移** | `decide_gate` 增 `expected_revision` ＋ `gates` 加 `lifecycle_version`；版本交叉 409 不推进 version。**【2026-11-06 落点列口径订正】**：`expected_revision` **可选**（非必填，缺省＝旧客户端兼容、version 照常推进）、revision **复用既有 `gates.version`**（`VersionedMixin` 在位，**零新增 revision 列**）、**仅新增 `lifecycle_version`**、表名 `gates`（模型在 `workbench/models.py`）——照旧口径施工会新增冗余列并毁兼容契约 | **✅ 已实施（#130，按我方 schema 适配）：`expected_revision` **可选**（缺省=旧客户端兼容，version 照常推进）+ 复用既有 `gates.version`（VersionedMixin 在位，总览 revision ≡ 该列零新列）+ 新列 `lifecycle_version`（同迁移 `b2e8f4a6c9d3`）+ 行锁（_load_gate with_for_update 既有）+ 版本复核 409 `gate_revision_conflict` + 四用例（落后冲突零变更/命中生效推进/缺省兼容/形状 400）；**桌面 expected_revision 接线已落（2026-11-06 桌面实施轮①）**——门禁视图回传 `revision`（≡ 既有 `gates.version`，零新列）、GateBoard 拍板原样带回 `expected_revision`、409 `gate_revision_conflict` 如实呈现并刷新面板（人可基于新状态重拍）；旧服务端载荷无 `revision` 时不带该键（缺省＝旧客户端兼容）。桌面 vitest 825→828（+3）、服务端 +1 钉 |
| B#29 | 验证/验收合同契约（五点） | 文档 | 并入 B#21 一章（G8 conditional_pass / G9 有条件接受语义对齐）；schema 落 B#23 夹具期 | 与 B#21 同期。**✅ 已落盘（#128 同文档 §4）** |
| B#35 | 技能成熟度口径 + 来源/许可登记 | 文档 | AGENTS.md 技能约定段写「published＝治理通过 ≠ 现场验证」（不换状态值、不改发布四闸）；外部技能导入登记落 `docs/audit/`（字段沿用 `SOURCES.md`）。**【2026-11-06 由 PROPOSED 改判修复项】**：本条的价值在于把许可红线从草稿搬进权威基线——**须将 AGENTS.md 新增红线第 8 条（五项硬条款：抽象概念可用／结构化表达禁写入本仓含改数字·换措辞·重排的等价复现／PR 附来源对照表声明独立重写且评审否决等价复现／快照日期与失效判据（远端出现 LICENSE 或 HEAD 变动即复核、停更超 30 天失效重核）／legacy 许可混置须逐件核）逐字落进 `AGENTS.md` 与本节** | 零代码零迁移。**✅ 已实施（#133，技能契约轮 2026-11-06 核实销号）：AGENTS.md 红线第 8 条（五项硬条款逐字）+本节登记同 PR 合入——修复项产出（PR 合入）达成；B#36 实施时按本条红线执行「我方独立设计」** |
| B#36 | 技能结构化契约最小 5 组字段 | 文档 | `SkillVersion.manifest_json` 增可选扩展键（**免迁移**）＋ `.agents/skills/` 新技能 front matter 建议；存量 4 个 runbook **不回填**；**禁止把 `instructions_text` 拆成 YAML 双权威**（DB 仍是唯一权威）。只取 **5 组语义**，**不取 21 字段全必填、不设 `additionalProperties:false`** | 零迁移。**✅ 已实施（技能契约轮 #140，与 B#37 同批防口径漂移）：契约=`docs/architecture/技能结构化契约-v1.md`——manifest_json 五组可选扩展键（use_boundaries 适用边界/effects 副作用声明/evidence 证据口径/verification 验证状态（非状态注记）/failure_behavior 失败诚实，各组 ≤2 键、值类型 str/bool/list[str]），语义锚全部指向我方既有语义（评测协议 §4 五点风格/T-R2 effect 分面+P3 分类学/证据红线+T-G1·T-W7/B#35 成熟度/B#2 失败诚实）；基线键 version/source/read_only 不动+read_only×effects.write_actions 自洽律；键空间闭合枚举（{基线三键}∪{五组键}）防漂移、未知键不拒绝（不设 additionalProperties:false）；`.agents/skills/` front matter 建议=name+description 必填+契约键平铺点路径，存量 4 runbook 不回填、内置种子 manifest 不回填；禁 instructions_text 拆 YAML 双权威（DB 版本行唯一权威）。**硬判据履行：全部字段/类目名/规则文本为我方独立设计撰写，零 fde-skills 正文引用（Q18 前维持）** |
| B#37 | 技能自洽校验落 pytest | 测试 | 新建 `server/tests/test_skill_contract.py`，对 `.agents/skills/` 与 `control/builtin_skills.py` 种子清单做静态校验，挂现有 `server-tests` job（**不新增 CI job**）；**不引入 PyYAML/jsonschema 依赖**（标准库 + pytest）；生成物一致性改成「种子清单 ↔ DB 行」断言 | ≈1–2 人日。**✅ 已实施（技能契约轮 #140，与 B#36 同批）：新 `server/tests/test_skill_contract.py` 四钉（标准库 json/re/pathlib+pytest，零 PyYAML/jsonschema，挂现有 server-tests job 不新增 CI job）**——①runbook front matter 契约（name=目录名 fde- 前缀/description≥40/已知点路径键类型良构/正文非空）；②`builtin_skills.SKILLS` 种子静态契约（键唯一+形状/能力 ⊆ CAPABILITY_REQUIREMENTS 无重复/LEGACY 升级指纹键 ⊆ 现役键）；③种子 manifest 构造规则独立复算钉（version 三分档 1.2.0/1.1.4/1.0.0+source+read_only 推导，src 侧漂移即红）；④**种子清单 ↔ DB 行对账**（「生成物一致性」的落法——`seed_public_skills` 端到端：admin 建号→首轮 created==len(SKILLS) 全量落库→逐 key 断言 published 定义行+现行版本行 instructions/capabilities/manifest_json 逐位等于种子构造→契约自洽律库上复核→幂等二轮 0+版本行不增殖）。变异四连（read_only 推导翻转/runbook name 脱离目录名/种子加域外能力/version 分档漂移）逐一转红→反向替换还原绿。与 B#4 purity 测试同组织（tests/ 直挂零 fixture 复用） |
| B#38 | 三维标签 + 门禁行业字段填充 | 文档/数据 | **【2026-11-06 按 Q13 收窄】**只填 seed 条件项（`server/seeds/gates.json` 的 `applicable_industries`，字段已存在、G1–G9 实测 9 处字段值全为 `null`），并注记**现行国标版本锚点 + 核验日期 + 有效期≤6 月 + 合规 owner 核准**；**不得产出等保/信创清单挂 G8/G9 `evidence_checklist`**（§2.9 已把「等保/信创条目当合规依据」列为明确不照搬）；Frank `03-G端政府专项/*` **仅可引类目名**、不得作条目素材（无 LICENSE＝全部权利保留）；条目若落地须由我方依现行国标与客户招标文件**独立撰写**，正文走指针+sha256。「先搜再建」写进 AGENTS.md | 零迁移零依赖。**🔒 冻结（2026-11-06 评审）**：素材来自无 LICENSE 且停更（2026-07-07 后）的仓库＝强时效内容却无复核触发。**解冻前置**：B#35 许可硬条款落基线 ＋ 国标版本锚点/核验人/有效期字段就位 ＋ 本节登记生效；**形状**（挂 `evidence_checklist` 出清单）若坚持须由用户重拍 Q13 |
| B#39 | 现场应急分级处置 runbook | 文档 | 新建 `.agents/skills/fde-field-incident/SKILL.md`（沿用 `name`+`description` front matter）；**【2026-11-06 许可收窄】**分级定义与升级路径由我方独立撰写，**不得沿用 Frank 的四级表列名、六段时钟分段名、三级升级时长组合、三线并行表述**（版权保护编排与结构化表达，**改阈值·换措辞·重排的等价复现同样无权**）；**阈值唯一源＝实测 P50/P90/P99**（P90 定升级、P99 定最严档），**Frank 的 5/15/60/240 分钟不作基准**；与 `OperationEvent` 留痕、B#5 审批退避 SLA 联动；只写处置动作不写自动执行；通报模板只留我方字段（不落客户联系人电话等触红线字段） | 零迁移零依赖。**🔒 冻结（2026-11-06 评审）**：复制的是结构化表达，连「不复制正文」都未覆盖；阈值无数据来源。**解冻前置**：B#35 许可硬条款落基线 ＋ SLA 校准表产出 ＋ 本节登记生效 |
| B#40 | 两技能库专属「不做清单」与已合并项登记 | 文档 | 登记不做：60 个模板化技能批量产出／21 字段全必填／12 类分类与 8 阶段框架／`skills.json` 文件权威＋CI 锁 diff／Python CLI＋4 IDE 适配器／合成案例与 `legacy/` 历史导入／AGPL 全库许可／`draft·ready·field-validated` 状态值；不做 70 篇正文整体导入／7 段模板替换 `SKILL.md`／10 维分类与 G1–G9 并列／README 当机器索引／截断文件名／等保信创条目当合规依据／沙盘现阶段／技能组合自动执行化。已映射项不另立项：B4→B#22/B#29、B6/F1→B#15、B7 暂不立项、F3/F5→B#30、F4→B#21/B#22、F6 不立项 | 零代码。**🟡 负向登记（2026-11-06 登记，与 B#35 同一 PR 生效）**：防「已评估又重评」与「把 70 篇文档当技能包导入」两类重复事故；与 B#19/B#26 同为不做清单 |
| B#10 | 外部模型依赖契约成文 | 文档 | 写成 V3 通用契约（七条规则 M-1–M-7，我方自定义编号）：①开关默认 OFF 且关闭时判定逐字一致、零外部请求；②阈值是「建议值」非判定常数、调用时点读取、覆盖免重启；③失败≠错误而是「下一阶段」且既有路径原样继续；④传输层可注入、测试网络零依赖、地址密钥禁硬编码、客户端禁擅自裁剪请求体；⑤外部响应缺字段取保守值不推测、枚举表外值只留痕不参与判定、保守方向须写明；⑥日志只记哈希与长度禁记原文、必记「哪一阶段作出判定」的 source 标记、不新建存储；⑦调用方签名不破坏、新参数一律可选、显式意图预判顺序不得被新阶段翻转。与既有 W-8「断链不静默 done」（流程层：真失败须显性化）分工不混淆——本条管判定层降级，W-8 管流程层显性失败 | 零代码零迁移零路由零依赖。**✅ 已落盘（2026-11-06：`docs/architecture/外部模型依赖契约-v1.md`——含现状对照表、七条规则、差距清单（M-5/M-6 两条纯靠立规闭合）、八条可断言判据、复查机制；行级引用一律「符号名＋行号」双锚防基线漂移）**。**触发式复查**：新增任一外部模型阶段时，同 PR 内须逐条对照 M-1–M-7 给「满足/不满足/不适用」三选一 |
| B#9 | 只读执行事实链面板 | 代码（只读面） | 三源只读时间线归并：`project_evidence`＋`operation_events`（项目维度，过滤下推 SQL）＋`ai_call_audits`（**账号维度**——该表无项目外键，按 actor 过滤且响应明示 `ai_call_audit_scope="actor"`，不作项目切分假装）。时间倒序、limit 1–200 有界＋truncated；`operation_events.changes` 大载荷不外泄；AI 审计只投影调用事实元数据（无明文上下文）；「外部完成无真实回执=未知」——无回执即无行，前端呈现「无记录」，不由模型自述或时间线推断拼装「已完成」语义。与 autoloop A5 trace 视图同位整合（本条即其 V3 落点）；只读面**有意不进 api_catalog**（AI 不经此面读审计原始流，与证据登记同纪律） | **✅ 已实施（2026-11-06）**：服务端 GET `/api/v1/projects/{id}/execution-facts`（can_view；`fact_chain_blueprint`，路由 +1=301）＋ `NEW test_execution_fact_chain.py` 4 例（三源归并排序＋changes 不泄漏＋AI 字段白名单＋未知不编造／actor 隔离跨账号泄漏钉／过滤与 limit 有界＋非法 400／权限 viewer 200·外人 403·404·不进 api_catalog）＋变异三连（actor 过滤失效／changes 泄漏／scope 谎称全红）；桌面 NEW `evidence/ExecutionFactChain.tsx` 只读面板（项目 tab +1「执行事实」=11 tab；三源筛选、badge 类型标、账号维度明示、空态不编造；改 1 处 tab 断言数组）。零迁移零依赖；pytest **1985=1979+6s**（+4）/ vitest **825**（本条断言改 1 处不计增量；含并入的 UI-UX 黑金轮增量 791→825）/ mypy 279 不变 |
| B#7 | 回执 DSL 一期（ask + later） | 代码（契约层） | NEW `agents/receipt.py`：回执 DSL 为**外部可写结构**，故按白名单逐字段校验——**未知字段一律拒绝**（指出字段名，不静默丢弃、不透传，否则外部多写一个键即绕过闸门）；**容量上限**对齐既有审批材料 64KB 语境（超限拒绝不截断）。两种人工介入动作：**ask**＝请求人工拍板，落既有 `automation_approvals`（零新表零新路由，密码确认闸现成；幂等＝request_key 由「项目＋能力＋规范化回执」派生，复用既有 pending 审批；能力须在 `CAPABILITY_REQUIREMENTS` 白名单且发起人**当下**仍具备；风险档固定 4 诚实标高险；敏感键拒绝入审）；**later**＝请求延后复查，落**最小到期挂点**（`operation_events`，只表达 `due_at` 时点结构）。**边界声明**：later **不实现**统一到期表/主动超时扫描/统一 cron 计算——那是 B#13 的 `deadlines()` 纯函数职责，本条不越界（B#13 落地时把 `due_at` 纳入其到期表即可，无需改动本条）。DSL 不可解析 ⇒ 走 B#2 降级路径（业务动作可能已执行，不能重做 ⇒ 落独立终态 `succeeded_but_receipt_invalid`，拒绝同键重跑）。命名隔离：既有 `AgentResult.receipt_state` 是**产物清单扫描**语义，与本条**人工介入动作**语义正交，两套并存不互相覆盖 | 零迁移零路由零新表零依赖。**✅ 已实施（2026-11-06）**：NEW `server/src/fde_api/agents/receipt.py`（Pydantic `extra="forbid"` 白名单基类＋`as_ask`/`as_later` 纵深防御＋容量/敏感键双闸）＋ NEW `test_receipt_dsl.py` 7 例（顶层与 action 双层未知字段拒绝／非对象与未知动作拒绝／容量上限拒绝不截断／指纹顺序无关稳定／ask 建单与幂等复用＋风险档 4＋sha256 指纹／未知能力拒绝／敏感键拒绝／later 挂点字段闭集且无主动扫描器／delay 越界拒绝）＋变异四连。零迁移零路由零新表零依赖；pytest **1994=1988+6s**（+8，CI 复核）／vitest 828 不变／mypy 279 不变／路由 301 不变／表 105 不变；本条**有意不进 api_catalog**（AI 经既有通道投递，非 catalog 面） |

### P1 第二批（总览建议 1–2 月窗口，登记不展开）

B#7 回执 DSL 一期（前置=是否接受改 Skill 编写口径，待澄清 6.1-2）｜B#8+B#32 Skill 消费面两级注入+只读技能中心（`skill_read` 分页真缺口——**该真缺口已于 2026-11-06 待办池清欠轮实施闭合**：`mcp_gateway.skill_read` 加 16k 窗口 offset 分页＋next_offset/total_characters，T-S2 计数收敛为仅首读计一次，专项 pytest 5 例；**两级注入 `readBefore` 仍 PROPOSED；只读技能中心 A 面已于 2026-11-06 交互拍板⑤A 实施（见下方状态段）**）｜B#9 只读执行事实链面板｜B#10 外部模型依赖契约成文｜**B#11 门禁判据实施落点（承接 B#22）——落点设计已裁（2026-11-06；设计=`docs/architecture/门禁判据实施落点-v1.md`）**｜**B#12+B#31 外部文字禁入提示词+原件/派生分离——契约落盘（2026-11-06；契约=`docs/architecture/外部文字禁入与原件派生分离契约-v1.md`）**｜**B#13 统一到期语义目录+主动超时治理——A/B/C/D 四阶段全部实施（2026-11-06；契约=`docs/architecture/到期语义与主动超时治理-v1.md`，A=目录/审批基线、B=UploadSession #153、C=confirmation derived 原语、D=只读投影，详见下方实施状态更新）**｜**B#14 executor 对抗性测试组织（前置=决策逻辑抽纯函数重构）——✅ 已拍板直补（2026-11-06 交互拍板 opt A「直补对抗钉」）：五夹具族盘点＝①固定种子模拟／③迟到拍板／④双 definition_version 并存**已由现有 39 例覆盖**，②强杀不丢已确认／⑤节点独立事务失败恢复**为缺口**⇒ NEW `server/tests/test_workflow_executor_adversarial.py` 4 例直补两族（强杀族：worker_lost 收口后已 succeeded 产物零丢失＋resume 不重跑已确认读面；tx B 崩溃族：settle 落表崩溃→悬 running→恢复后幂等键不变＋attempt 保留；恢复底座：_recover_interrupted 只重置 running）；变异双红。**不做 2–3 周决策逻辑纯函数重构**（与总览「先攒真实故障史，三期做」裁决一致）。零迁移零路由零业务代码；pytest **2014=2008+6s**（+4，CI 复核）**｜**B#23 离线评测夹具 v0（前置＝四条件触发式解封：①客户量化验收线诉求成文 ②可回放 KPI 定义 ③`kpi_oracle` 责任人指定 ④只读回放 CI 静态断言；Q1–Q3 已于 2026-11-06 拍板＝「结果验收·仅文档级」）**｜B#24 过程成本计入+评测完整性留痕（依赖 B#23）｜**B#30 门禁前置清单自动复核+回退留痕——立项完成（2026-11-06；立项=`docs/architecture/门禁前置复核与回退留痕立项-v1.md`；A 面零迁移候选随下次 gate 轮、B 面 ✅ 已拍板（2026-11-06 交互拍板）＝opt1 维持现状——终态不可逆维持，零代码）**。**B#36 技能契约最小 5 组字段／B#37 技能自洽校验 pytest** 已于 2026-11-06 补登记于上方 P0 表（形态为文档/测试，实为 P1 可排期项，硬判据见各行）。

**B#13 实施状态更新（2026-11-06）**：`docs/architecture/到期语义与主动超时治理-v1.md`。核心裁决=统一**到期语义目录+各域原生转换器+条件触发的只读投影**，不建复制 `expires_at` 的通用事实表。审批主动超时由 T-P1-5 完成（`_expire_approval` 唯一原语+`sweep_expired_approvals`+scheduler 同拍）。**B#13-B 已实施（#153）**：UploadSession 到期 guard（行锁、`expires_at <= now`、迟到 sign/complete 409 零 storage/文件副作用、签名 TTL 不越会话截止）+ `files/expiration.py` cleanup claim（`skip_locked`/`completion_json.expiry_cleanup`/`file.upload.cleanup` outbox）+ worker 事务外 multipart abort（not-found 视成功、其他错误可恢复退避）+ scheduler 接线，复用既有 `expired`/`expires_at`，零迁移；专项+邻域共 65 passed。**B#13-C 已实施（本轮）**：derived state 裁决——`OperationEvent` append-only 完整保留，不追加 expiry event、不建后台 sweep（该域无清理副作用）；`control.api_actions.CONFIRMATION_WINDOW`+`confirmation_expired` 单原语统一 pending/status/decision 三处推导，边界对齐 `deadline <= now`；迟到决策 `action_expired` 409 零副作用；uncertain 防重放优先于到期、finished replay 越窗有效；专项 7 例。**B#13-D 已实施（本轮，触发条件=用户明确指示）**：`fde_api/expirations.py` 服务层只读 union + admin-only `GET /api/v1/expirations`（六字段逻辑视图，四域接入，`due` 统一 `<=`），零 DDL 不建 SQL view（防派生窗口规则双权威）；admin-only/limit(100,≤500)/稳定排序/domain+due 过滤；投影不写回不触发转换器，不进 api_catalog；专项 8 例；route 302/blueprint 40，105 表、迁移头不变。**A/B/C/D 全部 DONE**（#153 起分轮；C/D 同轮 2026-11-06，**CI 实测全量 2029 收集 = 2023 passed + 6 skipped**）。明确排除 worker lease/retry/outbox due、JWT/签名/Redis TTL、模型/进程 timeout、dispute SLA/meeting stale 等异质时钟。
**B#8 两级注入实施状态（2026-11-06，交互拍板⑦A 全链路）**：①契约扩组——技能结构化契约 v1 新增 §2.6 `references` 必读引用组（`required_reading` 执行前必读硬前置／`authoritative_sources` 冲突裁决软引用；语义锚=`fde-package-verify` 手写规则「README 冲突以 README 为准」升级为机器可读引用），键空间闭合枚举同步扩 `references` 组（B#37 闸验证通过）；②消费面两级接线——`skill_list` 列表面带 `when_to_use` 摘要（取自 use_boundaries 组，未填不带键＝缺省不误导）、`skill_read` 首页（offset=0）带引用清单（续页不带＝同一正文延续不重复噪音；良构校验 list[str] 全非空才出，类型不符缺省一律不带＝不猜不放宽；T-S2 计数语义不变）；③引用是仓库内相对路径，消费方用既有只读工具自行读取——引用不携带内容、不产生新读取权限（skill_list/skill_read 工具 schema 静态钉住不变）；④4 个 runbook 按「平铺点路径 + JSON 数组字面量」回填 use_boundaries+references（**种子 13 条维持 B#36「不回填」裁决不动**——扩组与回填不触碰该裁决，回填对象只有 .agents 侧 runbook）。NEW `tests/test_skill_readbefore.py` 5 例＋变异三连（列表不带摘要／续页也带引用／坏引用透传）逐一转红。零迁移零路由零新表；pytest **2056＝2050+6s**（+5，CI 复核）／vitest 858（零桌面改动）／mypy 279／路由 304／表 105／ENTRIES 94／迁移头 `b2e8f4a6c9d3`（36 rev）不变。**

**B#32 A 面实施状态（2026-11-06，交互拍板⑤「只做只读技能中心」）**：NEW `server/src/fde_api/control/skill_center.py`（**DB 权威只读浏览面**——取内容域弃文件目录形态：技能权威已在 `skill_definitions`/`skill_versions`（含 `content_sha256` 与不可变版本行），若另起文件系统 provider 会出现两个权威且漂移不可测，故只读 DB 权威、不引文件目录、不引依赖⇒无供应链闸）＋新增 2 条只读路由 `GET /api/v1/skills`（可选 `?scope=public|personal`，非法值按空处理不猜不放宽）与 `GET /api/v1/skills/<skill_id>/document`。**权限面与既有 `mcp_gateway._skills` 同尺**：`status=published`（draft/in_review 未过发布闸不外泄）＋ `scope=public` 或 `owner=当前用户`；不可见即 **404**（不区分「不存在」与「无权」，避免探测）。**不消费计数**——`skill_read` 读出指南才计一次消费（T-S2 语义），本面是治理浏览面（人看目录、下载文件），浏览一次就写一条 `skill_used_*` 会虚增「已消费」记录。列表 200 条上限＋正文 512KB 上限（超限拒绝不截断）。专项 pytest 5 例（`tests/test_skill_center.py`：可见性边界／正文与指纹／不可见即 404／scope 过滤／只读面零写入）；**变异四连逐一转红**：去 `status` 过滤（draft 泄露）／去 `owner` 限制（他人个人技能泄露）／浏览写消费计数（计数 +1）／正文面返回空正文。零迁移零新表零依赖；pytest **2049＝2043+6s**（+5，CI 复核）／路由 304（+2）／表 105／ENTRIES 94／迁移头 `b2e8f4a6c9d3`（36 rev）不变。**两级注入 `readBefore` 仍 PROPOSED**（需改 `manifest_json` 结构＋改写各技能的写前必读约束，耦合面大）。

**B#12+B#31 契约落盘与状态（2026-11-06）**：`docs/architecture/外部文字禁入与原件派生分离契约-v1.md`。**现状实测结论：架构已有机闭合 P-1/P-2（提示词权威层白名单）与 A-1/A-2/A-3（原件指针化+派生物三问血缘）**——全系统恰四处 system 组装点全部落在白名单内（`chat.py:189 _workbench_system_prompt`=代码常量+config+内置手册目录；`executor.py:1104`=治理面发布 instructions；`ai_content.py:115`=固定常量 system+外部数据走 user 角色 JSON；`direct_tool_completion` 形参面）；工具结果一律 tool 角色、`file_read`/`help_fetch` 带结果级 `"source"` 标记、`captured_from` 封闭枚举形状闸、`ai_request_id`/`revision_id` 血缘在位。**契约增量=①把散落的既有防线收拢为 P-1~P-5/A-1~A-5 十条我方规则＋封闭枚举白名单；②差距如实登记（lcsc_* 结果无 source 标记、direct_tool_completion 形参面无静态闸、A-4 无统一谓词、个人技能 owner 自治边界）**；③四条可断言判据（J-1 system 组装点枚举静态钉=未来执行轮靶点）＋触发式复查机制（新入口/新 AI 调用点/新工件类型同 PR 逐条对照）。**本条状态=契约已落盘；J 系判据已接线（2026-11-06 提示词卫生 J 系接线轮，#150 后）：NEW `server/tests/test_prompt_hygiene_jseries.py` 5 例——J-1 全仓 system role 组装点形态白名单 AST 钙定（常量/常量名/形参直传链/已登记例外四形态；域外新增即红，PR 须对照契约 §2 表登记）＋executor skill 节点 `system_prompt=instructions` 治理面附钉／J-2 四类不可信资料工具结果级 source 标记全钉（`file_read`=untrusted_project_file、`help_fetch`=workbench_help_manual 既有；`lcsc_search`/`lcsc_runs_read` 本轮补 `untrusted_storefront_content`——契约 §4 差距①闭合，P-3 标记腿全满足）＋`_serialize` 单一形状源附钉／J-3 `ai_content` system 纯常量构造钉（payload 变量泄漏即红）。变异三连（lcsc 标记删除／executor 接 prompt 变量／system 拼接 payload）逐一转红。零迁移零路由零依赖；pytest **1999=1993+6s**（+5，CI 复核）／mypy 279 不变。**差距②已拍板补静态钉（2026-11-06 交互拍板）**——对 `direct_tool_completion` 的 `system_prompt` 形参面做 AST 实参来源允许名单断言（与 J-1 同组织纯测试轮）：语义层约束升静态闸，新调用点引入域外实参即红。纯我方独立设计，零第三方正文引用（AGENTS 红线第 8 条履行）。**

**B#11 落点设计与状态（2026-11-06）**：`docs/architecture/门禁判据实施落点-v1.md`。**一句话裁决＝三锚四反例的宿主＝B#23 离线评测夹具的「评测器元验证层」**（它们验证的是打分检查器本身，不是交付物）；门禁面落点**已随 #131 冻结**（G9 exit_condition 含「三锚四反例全过」，钉 6 守护）；pytest 模板落点＝解封后 NEW `server/tests/test_eval_criteria_harness.py`。**诚实盘点：当前仓内尚无「打分型检查器」**（G1–G9 核验=人工；其余判定面全部布尔/枚举型）⇒ 三锚四反例现在没有可验证对象，是为 B#23 算分器预置的验收合同；**元验证语义（我方定义）＝评测器可用于任何「验收线达成」判定前必须先过元验证夹具，锚点不落位/反例漏抓 ⇒ 其输出不得作 G9 判定输入（insufficient_data 不变）**。逐判据落点表 11 行（3 锚+4 反例+3 附加规则：宿主/输入/断言形状/前置闸），阈值纪律=我方数据校准前不落常量。**本条状态=落点设计已裁，元验证层实施随 B#23 夹具期同窗（四条件解封），设计≠实施授权；判据语义零新增零改写。**

**B#30 立项拆分与状态（2026-11-06）**：`docs/architecture/门禁前置复核与回退留痕立项-v1.md`。**拆解＝A 面前置清单「证据漂移自动复核呈现」（T-G2 template_outdated 同构：清单项引用的 evidence 被同 source_uri 新 hash 行超越时序列化输出 `evidence_superseded: true`——呈现即提示四不动〔状态机/claim_status/拍板有效性/AI 权限〕，零迁移可实施，实施排下次 gate 轮＋桌面呈现面排 PR #132 落定后）＋B 面拍板回退通道与留痕合同（现状 passed/conditional_pass 为终态不可逆〔重交 409〕、failed 有重交回环；**是否开放终态回退＝业务拍板项**，三选项登记：opt1 维持现状／opt2 受限回退〔仅 conditional_pass 可回退 evidence 态、passed 不回退、gate_rolled_back 事件 reason 必填、验收分离与 CAS 沿用〕／opt3 只读复核队列）**。不做清单：不动 evidence 不可变性／不做定时自动重核（指针目标在平台外，「自动」仅指呈现层）／AI 不代拍板不代回退／不动四闸。**B 面已拍板（2026-11-06 交互拍板）＝opt1 维持现状——passed/conditional_pass 终态不可逆维持（重交 409 现状不变），零代码零迁移；理由：回退通道引入状态机新分支+桌面回退 UI（≈1–2 人日），当前无「拍完发现证据有误」的真实场景推动，错误拍板走线下留痕（OperationEvent 已有 from→to 留痕可追溯），opt2/opt3 保留为候选、真实诉求出现时重开。本条状态=**A 面已实施（2026-11-06 B#30-A 证据漂移呈现轮：`gate_service._superseded_evidence_ids` 同源行集有界比对＋`_serialize_gate` 项级 `evidence_superseded` 三调用点接线＋桌面 GateBoard「证据已换版」badge；零迁移零路由零新表；pytest +2 / vitest +1；「实施排下次 gate 轮＋桌面呈现面排 PR #132 落定后」两前置均已满足，#132 品牌轮 11-06 先行落定）、B 面已拍板收口（opt1 零实施面）。**

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
6. **售前主线闸（T-A 系列登记轮新增，2026-11-06；同日拍板轮收口 ①②③⑥，④⑤⑦⑧ 按登记口径确认）**：
   ① **T-A2 代号化未命中失败语义**——✅ **DECIDED（2026-11-06 拍板）：分层语义**——替换器**异常**（词典加载失败/正则编译失败等机制性故障）→ **fail-closed 硬阻断入库**（保红线完整性，与 `_render_context` 422 先例同构）；**疑似企业名但词典未收录**（正则命中「技术公司」类通用词）→ **放行但记入待复核清单**，方案审核人 confirm 前必须复核（复核点与「确认事实是拍板权」分工对齐，防全阻断崩可用性）。**两半均已落地**：fail-closed 随 #160（`pseudonym_dict_unavailable` 不重试）；**confirm 复核闸随补齐轮（2026-11-07）**——409 `redaction_review_required` + `redaction_reviewed=true` ack 事件留痕，清单从 #160 事件源聚合；
   ② **T-A2 词典形态**——✅ **DECIDED（2026-11-06 拍板）：仓库内种子文件**——词典存 `server/seeds/`（CI 扫库与入库替换**读同一个文件**，「词典一致性断言」天然成立），企业名词典变动频率极低（新客户才加一词）撑不起 DB 表成本，零迁移零 DB 依赖，变更走 git 审计；
   ③ **T-A7 谈判稿实体**——✅ **DECIDED（2026-11-06 拍板）：复用既有 solution 版本行**（登记默认获确认）——谈判稿=未冻结版本，最终 SOW 只认 frozen，桌面把未冻结版本标注为「谈判稿」即可；**零新表零迁移**，独立谈判稿表=对「方案版本快照不可变」既有设计的重复建模；
   ④ **T-B1 封包前置**——✅ **确认（按登记口径）**——D11 立项拍板 + 首批真实数据到位前**只做 artifacts 扩列，封包部分不开工**；
   ⑤ **T-Z1 执行通道形态**——✅ **DECIDED（2026-11-07 20:08 用户拍板「D1 按推荐」＝A 宿主侧 zcode 代理）**——开工前半天实测已由 #191 完成：容器内直连四重阻断（全在沙箱红线面）⇒ C 否决；裁定 A（与 `bridge-poll.mjs` 宿主纪律同构），B（openfde 加 executor）降为 A 落地后的可选演进，**不预设复用 openfde** 的登记口径原样满足；落地属实施轮，开口前须 zcode 商用条款书面授予。D2 红线修订与 D3 商用条款确认两前置同轮办结（D3 决策已定、**外部书面回执仍缺** ⇒ 生产启用闸不解除、`adapter_missing` 维持）。裁定依据=`docs/audit/T-Z1-zcode真机实测与通道裁定提案-2026-11-07.md` §2；
   ⑥ **T-A8 与 B#9 合批口径**——✅ **DECIDED（2026-11-06 拍板）：同 PR 批次交付、界面分离**——两者服务端改动都只是只读路由，合批省一轮 PR；界面分离因数据源与用途不重叠（T-A8=智能体运行态 agents runs + meetings；B#9=证据/审计事实链 `project_evidence`+`operation_events`+`ai_call_audits`），强行聚合徒增认知负担；
   ⑦ **§度量口径与 G9 关系**——✅ **DECIDED（2026-11-07 拍板，原「确认按登记口径」升格）**——并存（§8 过程指标不设阈值 + G9 结果验收线，不得互代）；**「工程师小时数/交付毛利率」接受 simulation 口径**；**埋点显式未立项**（待 T-B1 后评估）；商业主张验证以《商业验证决策单》线下台账为准；
   ⑧ **真实客户验收时点**——✅ **DECIDED（2026-11-07 拍板，原「确认按登记口径」升格）**——**2027-02-05 强制复评，以首个真实项目立项为先到者**；90 天止损线（无真实项目进链路，或人工工时占比 >70% 且无下降趋势）与线下台账 owner=蔡工，见 `docs/audit/商业验证决策单-2026-11-07.md`；
   ⑨ **售前主线收尾分工（goal-ta 循环，2026-11-07 蔡工拍板，三行逐字记录）**——✅ **DECIDED（2026-11-07）**：①「剩余T-A线本会话」——T-A1 / T-A8+B#9 合批 / T-A9 随 ASR 立项 / 工程卫生轮，归执行 goal-ta 循环提示词（`Goal提示词-交付工作台T-A收尾-goal-ta循环-v1.0.md`，文档中心 08_支撑材料/专题文档）的会话；②「T-A7另外一个会话在做，其它本会话可以做」——T-A7 为该会话**绝对禁区**（不认领、不开相关分支、不实现任何 T-A7 语义、遇 T-A7 分支/PR 零触碰零评论，backlog 对 T-A7 条目只加事实注记）；③T-A9 的 ASR 通道「**立项**」——文档轮（零代码零迁移），**立项≠实施**，T-A9 本体维持 PROPOSED，立项文档=`docs/architecture/录音转写ASR通道立项-v1.md`（含显式「待蔡工拍板」通道选型节），选型拍板后 T-A9 另开实施轮。
   ⑪ **T-B1 封包前置（D11 立项）拍板（goal-tb tb4，2026-11-07 蔡工委托「第3件需要拍板的按你建议处理」）**——✅ **DECIDED（2026-11-07）**：D11 立项按台账 §二草案+§十三.4 改名裁决执行（handover_packages 两表/delivered=admin 终态不可逆/manifest 规范化哈希/seal 逐项 sha256+复核闸）；「首批真实数据到位」**不阻塞代码实现**（合成 run 测试覆盖，投产自然等待真实 run）；document/file item_type 留扩展。封包半随 tb4 实施（T-B1 全条 DONE）。留痕可推翻（#124 先例）。
   ⑩ **ASR 通道选型（goal-tb 循环，2026-11-07 蔡工拍板，逐字）**——✅ **DECIDED（2026-11-07）**：「ASR 通道选型：按你建议实施。」——按 #124 委托先例，立项文档 §3.3 P1–P6 逐项按推荐项落定（§3.3.1）：**P1=opt-L 本地 ASR 先行**（红线同向零外发）/ P2=横评实测裁决 / P3=Windows 宿主裸跑 / P4=首版普通话 / P5=诚实失败 / P6=云默认不开（启用=新的显式拍板）。横评报告=`docs/audit/ASR本地引擎横评-2026-11-07.md`（faster-whisper base 档：CER 8.6%/6.5%，4× 实时；宿主裸跑确认）。T-A9 实施轮随之解封（goal-tb tb1 同日执行）。

   **拍板轮结论（2026-11-06）：8 项闸全部收口，无一阻塞 T-A1..T-A7 开工**——①②③⑥ DECIDED 已回写对应条目；④⑤⑦⑧ 本就是声明性约束（登记时已有明确结论），确认后维持原状。

**红线对照（登记即声明，上位维持）**：B#25 客户资料红线（真相永不入库/不进 git）；B#34 交付进程红线（仅内部自检夹具）；B#3 与红线同向；**P3 评估报告 §1「写类外呼/发信/付款永不降级」红线对本清单全部条目上位维持**——任何借鉴项不得引入写类 external 免事前确认面。

### 工程卫生：路由审计清单 CI 同步钉（goal-ta4，2026-11-07）

- **#174 教训机械化**：NEW `server/tests/test_route_inventory_sync.py`（+1 pytest）——url_map 实际路由 vs `docs/audit/v3-route-inventory.csv` 逐行对账（口径同生成器：static 剔除/HEAD-OPTIONS 剔除/method `|` 连接），漂移即红＋重生成指引。人工纪律（AGENTS「审计清单刷新有前置条件」）维持，新增机械闸兜底；**验收达标**：人为漏登一条路由（删 CSV 行）→ server-tests 红；正常轮零打扰（清单同步时钉绿，4~7s）。零业务代码零路由变更。

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

 售前主线（T-A 系列，2026-11-06 登记轮；串行交付，每轮一 PR）
 T-A2(代号化, ✅已实施) ── T-A3(三态UI, ✅已实施) ── T-A4(三层可视化, ✅已实施) ── T-A5(方案骨架, ✅已实施) ── T-A6(claims→SOW, ✅已实施并合并 #175) ── T-A7(谈判版本, ✅已实施并合并 #178)
 T-A1(S3闸提示)：✅已由 #156 兑现（goal-ta3 核销零补码）
 T-A8(agents+meetings 控制台，含 +2 只读列表路由)：✅已实施(goal-ta2，与 #171 收口同批)
 T-A9(转写草稿区)：✅ **DONE（2026-11-07 goal-tb tb1）**——依赖 T-A2(✅) + ASR 通道立项(✅6⑨) + 选型拍板(✅6⑩) 三闸齐清
 T-B1(artifacts 扩列 + handover_packages 闭环)：依赖 T-A8；新迁移 additive-only
 T-Z1(zcode 真机 + 执行通道裁定)：依赖 T-B1；开工前须实测 zcode 能否进 sandbox-runner 容器
```


---

## 22:25 交互拍板补录（2026-11-07，T-Z1 人工项方向，归属 backlog 实施登记）

> 用户「人工部分你使用交互式选择方式解决」；两轮 5 张交互卡片收口上一轮 6 项人工项。**方向先落文本、四闸维持关闭**；本段为现行口径，T-Z1 段 20:08／20:38 原文保留作沿革。

**统一口径（不得曲解）**：**方向已定 ≠ 闸已解除**。Q2/Q3/Q4 三项用户选择的是「推进方向」，其必填参数经 Q5=A 明确暂缓补录；在原件／责任人／证据／数值到位前，D3 生产启用闸、N1 试点授权、N2 真机联调签核、D7 阈值与 E8 实施**全部维持关闭**。`adapter_missing` 维持；H1–H13／N1–N7 一个不放宽；Agent 不代填外部事实、不代发起 run、不代跑真机、不造运行证据、不预支阈值（数字双层证据纪律）。

| 卡片 | 用户选项 | 已拍板的方向 | 必填参数（22:25 现状） | 闸状态（现行） | 依据 |
|---|---|---|---|---|---|
| Q1 PR #193 合并 | **A** | rebase 到 `c2fe869` → CI 复跑 4 job 全绿 → squash 合并 | 无 | **已授权执行**（合并仍以 CI 实测为准） | 交互卡片 Q1；PR 现态 OPEN |
| Q2 D3 商用回执 | **B** | 用户**主张**供应商书面回执已取得 | **原件本地指针 + sha256 + 回执日期未提供** | **不解除**：生产启用闸关闭、`adapter_missing` 维持；只记「用户主张，待补原件核验」，**不写「已核验／已确认」** | Q2 + Q5=A；#191 §1.3 |
| Q3 N1+N2 试点联调 | **C** | 授权推进首批试点与真机联调方向 | **授权人／首个 run 发起人／真机窗口日期未提供** | **不解除**：N1／N2 闸关闭；不代发起 run、不代跑真机、不造证据；准备件保持「填空即走」 | Q3 + Q5=A；H4、N1/N2 |
| Q4 N3+D7 增强闸 | **C** | 立项推进 A 轨诉求与 D7 阈值方向 | **A 轨产出物定义、交给谁确认、阈值 N 与依据未提供**；`approval_rows=0` | **不解除**：E8 不实施、D7 阈值仍空、不预支数值 | Q4 + Q5=A；§1.5 要素 4 |
| Q5 参数补录 | **A** | 三项参数暂缓补录，方向先落文本 | — | 四闸维持关闭 | Q5 |

**待补字段清单（人工，Agent 不代填）**
1. **D3**：回执原件本地路径 + sha256 + 回执日期；原件只留本地，仓库只登记指针 + sha256。核验人到位后才把状态从「主张」改为「已核验」。
2. **N1**：授权人、首个 run 发起人（**必须为人**）、试点项目与范围；**N2**：真机窗口日期、检查单两表 PASS/FAIL + 证据 sha256（全表 PASS 才算签核）。
3. **N3**：A 轨产出物定义、交给谁确认（H1/H11 不自动收敛）；**D7**：四口径复审报告出完后再填阈值 N 与人工否决率阈值，须带双层证据。

**交互方式**：`AskUserQuestion` 两轮共 5 题（第一轮 4 题、第二轮 1 题补参）；依据／收益／代价／推荐理由写在正文表格、卡片只用 A/B/C 编号（交互选择卡片规范）。20:08 与 20:38 原文全部保留作决策沿革。

**实施登记**：本补录**不新增 B# 编号**（#194 已把 B# 线 FREEZE 封顶 B#40，《借鉴总览》《实况报告》转只读档案，本轮不触碰）；T-Z1 接线实施轮的开工闸仍为「① 实装 + D3 原件核验 + N2 联调签核」三者齐备，本次交互未解除任何一项。PR #193 合并＝Q1=A 已授权执行。

---

## 架构评估十项实施登记（2026-11-08，来源：`docs/architecture/archify-diagrams` 架构评估）

> 十项＝P1×3 / P2×4 / P3×3，外加第六张架构图。性质：给**已上线**的架构补机械闸与
> 边界文档，不是新功能。两项拍板：`paused`＝保留 CHECK + 加机械钉；pytest 提速＝
> xdist + 每 worker 独立库 + CI 并行（均「按推荐执行 + 留痕可推翻」）。

| 项 | 事项 | 状态 | 落点 |
|---|---|---|---|
| P1-1 | 迁移链必须恰好一个 head | ✅ 已实施 | `server/tests/test_migrations.py::test_alembic_chain_has_exactly_one_head`（双来源互校：文件解析 + alembic `get_heads()`） |
| P1-2 | 工作流执行器按调度/分派/结算/恢复拆分 | ✅ 已实施 | `workflows/{executor,constants,dag_utils,serialization,settlement,dispatch,recovery}.py`；门面 `__all__` 63 个再导出名；另附 `test_source_size_budgets.py`（四个热点只钉不拆） |
| P1-3 | pytest 反馈环提速（1h+ → 分钟量级） | ✅ 已实施 | `tests/conftest.py`（每 worker 独立库／同库分 schema 两条隔离路径）+ `pytest-xdist` + CI `-n 4 --dist loadfile` + `test_xdist_isolation.py` |
| P2-4 | 结构口径同步钉 | ✅ 已实施 | `server/tests/test_structure_inventory_sync.py`（JSON ↔ 路由/蓝图/表/迁移链逐项对账） |
| P2-5 | 蓝图清单自动派生（消灭第二份真身） | ✅ 已实施 | `app.py::_BLUEPRINT_SPECS` + `iter_blueprints()` + `test_blueprint_registry_sync.py`（含「不得绕过注册表」静态钉） |
| P2-6 | `paused` 死值域 | ✅ 已实施（拍板：保留 CHECK + 机械钉） | `server/tests/test_workflow_run_status_domain.py`（形状钉 ×2 + 写入方钉） |
| P2-7 | 图纸防陈旧 + 六图刷新 | ✅ 已实施 | `scripts/audit/check_archify_diagram_freshness.py`（已接 CI）+ 六图重锚/重渲染 |
| P3-8 | Redis 降级行为文档 | ✅ 已实施 | `docs/architecture/降级与失败路径契约-v1.md` §1（**并修正评估稿两处事实错误**：派发信号在 Redis／登录限流默认 fail-open 可配） |
| P3-9 | 桌面发起 workflow run | ✅ 已实施 | `desktop/src/renderer/src/workflows/WorkflowConsole.tsx` + `workflow-console-launch.test.tsx` |
| P3-10 | Worker 横向扩缩容边界 | ✅ 已实施（文档化，不改实现） | 同上文档 §2（已安全六项 / 不宜扩三理由 / 可扩前提五条 / 缺口四条） |
| 图 | 第六张架构图「降级与失败路径」 | ✅ 已实施 | `docs/architecture/archify-diagrams/degradation/`（12 节点 / 8 边 / 3 车道，四闸全绿 + 整页实拍） |

**依赖关系**：P1-2 先行（其余项的锚点引用拆分后的模块）→ P2-5 → P2-4（对着注册表校验口径）
→ P2-7（对着机器口径校验图纸）；P1-3 与 P1-2 互不依赖（前者只碰 conftest/CI/依赖），
P3-8/P3-10 依赖 P1-2 后的行号锚点。

**未决与挂账**：①`ensure_background_job` 缺数据库唯一约束（多实例可能重复建 job）——已登记
于契约文档 §4-④，随「可扩前提 2」一起排期；②Redis 无守卫的三处（AI 确认密码计数 /
AI 执行状态读取 / 行业模板取消标记）登记于 §4-①~③，**不代拍板**；③`paused` 若将来要真启用，
需先拍板并补暂停/恢复语义（写入方钉会先红）。

---

## V3.1 试点遗留登记（2026-11-09，somwyn E2E 试点复盘产出；复盘报告=`docs/v3.1/pilot-复盘-somwyn-2026-11-09.md`）

> 试点本体 ✅ 达成（checklist #17 已回填）；本节登记试点暴露的真实缺陷与运维待办。
> 全部 PROPOSED（登记≠排期≠实施授权）；D1 复核项属人工动作不占工程排期。

| 项 | 事项 | 来源 | 优先级建议 | 落点/修复方向 |
|---|---|---|---|---|
| V31-P1 | **大纪要抽取在推理模型下必败**：MiniMax-M3.1-Flash（推理模型）reasoning_content 与正文共享 max_tokens，且供应商 completion **硬顶 16,384 tokens**——全文 244 行一次成抽时 reasoning 吃掉 16,383、正文零产出（finish_reason=length）→ `ai_output_invalid` 两连败；10K 字符纪要该组合**必败**（试点用人工整理稿绕过） | somwyn 试点 Step 2（全文版抽取两败，人工整理稿缓解） | ✅ **已实施（2026-11-09 同日轮，实弹定案后更正实现）** | 实弹定案（诊断六组+活体一批）：全文@32,768 → **>900s 未返回**（思考随预算变长）；`reasoning_split=true` → 正文零产出（更差）；40 行@8,192 → 思考吃满（预算必须给到硬顶）；40 行@16,384+片级限定提示词 → **JSON 完整**（30 事实+7 需求，177s）；60 行@16,384 → 触顶截断；**活体 40 行片仍有批次触顶**（同参数用量方差 13,105↔16,384——思考长度有方差，压线片长不可靠）⇒ 片长降 25 行+自适应二分兜底。⇒ **初版「预算 ×2 预留」被证伪并删除**（正解是把活拆小）。实施＝①按行切片 NEW `discovery/chunking.py`（25 行/片、1,600 字符/片，行号回基 `absolute = start_line + reported − 1`）②自适应降片长（被截断的片 `split_chunk` 一分为二再抽，深度上限 4；单行片诚实失败）③片级提示词 NEW `DISCOVERY_CHUNK_SYSTEM_PROMPT`（常量形态，思考 9,252→6,077–9,204 tokens 不伤覆盖）④分批抽取 + 行号回基合并 NEW `discovery/merge.py`（跨片事实/需求去重 + 引用下标重基）⑤截断诚实报错 `ai_output_truncated`（不可重试）+ 截断判定不依赖供应商措辞（`finish_reason=length` **或** 输出 token 触达请求预算）⑥实弹补漏＝`create_extraction` 幂等查找漏版本过滤（升版后 rerun 永远拿回旧行）→ 查找与唯一约束同形 + rerun 版本升代（冲突 409 指路新行）。**遗留口径**：切片参数按本部署模型实测标定，换模型需重标；跨片成立的需求可能被漏（如实登记）；全量 10 片成功的活体证据待 provider Token Plan 配额恢复后补（429 2056 上限，非代码问题） |
| V31-P2 | **批量分解 vs gunicorn timeout**：全量 9 任务单请求卡项目行锁 >120s 被 `--timeout 120` abort（零残留，重跑安全=幂等锚验证通过） | somwyn 试点 Step 6（分批 item_ids 缓解，9/9 成功） | P2 | runbook Step 6 增补「大方案 item_ids 分批」注记；服务端批量切片上限评估或 timeout 拍板 |
| V31-P3 | **转写草稿卷属主**：容器 `/app/.fde-transcript-drafts` 属主 root → 首写 PermissionError | somwyn 试点 Step 1（`chown fde:fde` 已临时修复） | P3 | 镜像/entrypoint 以运行属主（fde）预建目录 |
| V31-D1 | **审阅动作 admin 代执行复核**（人工项）：试点全程审阅动作（facts/reqs 接受、测试计划批准、执行登记）由 admin 代执行；本体 confirm 与 workflow 拍板已由 pilot.reviewer 决策分离完成 | somwyn 试点全程 | 人工复核 | 蔡工桌面端复核全部审阅动作（`operation_events` 逐条可回查） |
