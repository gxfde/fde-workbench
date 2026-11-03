# Ontology Registry v1 设计（P0）

> 状态：**PROPOSED → 部分 IMPLEMENTED**——§2.1 `project_evidence` 与 §4 evidence 两行已于 2026-11-02 实施（T-E1/T-E2，迁移 `e1f3a5c7b9d2`；实现偏差见 backlog）；**§2.2 `ontology_terms`+`ontology_term_aliases` 已于 2026-11-03 实施（T-O1，迁移 `a3e7c1f9b5d2`；零路由，服务原语 create/confirm/merge 为 T-O3 confirm 的物化层，偏差见 backlog T-O1 实施记录——用例 1/2 的 HTTP 面随 T-O3 补齐）**；**§2.3 `ontology_relation_types` 已于 2026-11-03 实施（T-O2，迁移 `b8d3f1a5c7e2`；3 条路由 GET/POST/retire，服务层 ∪ 接入 `_validate_link`；偏差见 backlog T-O2 实施记录——subject_type 值域本轮只落登记不开放使用）**；**§2.4 `ontology_change_sets` 已于 2026-11-03 实施（T-O3，迁移 `c9e3a7d1b5f8`；7 条路由=GET terms+change-sets 六条，验收分离+base 指纹并发防护；偏差见 backlog T-O3 实施记录与 §2.4 落地裁决）**；**§2.3 的 subject_type 值域已于 2026-11-03 开放（T-O2b，迁移 `b5d9e3f7a1c6`——三处 CHECK 枚举→码格式+列宽 32→60；新建值域「内置 ∪ active 注册 − project」由单原语闸门把守，偏差见 backlog T-O2b 实施记录）**。基于 VERIFIED 现状审计设计；现状证据见 docs/audit/appendix/workbench-D-ontology-research-raw.md。
> 原则：不建平行实体体系。实体=既有 `project_research_subjects`；本设计只补 WB 完全缺失的三件：**术语治理、关系类型注册、变更集审核**，外加一等证据表（evidence，域 3 共享底座）。

## 1. 决策依据（对照任务书"决策 1/2"）

**决策 1（正式本体 vs 知识图谱）**：分层裁定——
1. 文档/访谈材料 = files + guidance sources（现状已有，REUSE）；
2. RAG 检索索引 = **不建**（WB 无全文检索消费方；fde-v2 LightRAG 层被其自证为"非治理层"，附录 A B11）；
3. 候选业务对象 = AI discover 产物（现状：不落库只回前端，正确，保持）+ 变更集里的 proposed 行；
4. 审核后的正式本体 = **本设计的 confirmed terms/relations + 既有 confirmed subjects**；
5. 业务规则/状态机 = gates + form revision + SOP（现状已有，REUSE）；
6. 业务系统事实 = bridge 投影（单向，文件永远赢，REUSE）。
防"检索结果当业务事实"的机制：**AI 产物永不直接写 registry 表**，一律进 change_sets.proposed_json，人工 confirm 后才物化（沿用 guidance adopt→confirm 闭环样板，附录 D ⑥）。

**决策 2（最小可行模型）**：候选表名逐个裁决（先查重后新增）：

| 候选表 | 裁决 | 理由（现状查重） |
|---|---|---|
| ontology_packages | **不建** | projects.template_snapshot/research_snapshot 已承担"项目冻结包"；knowledge_snapshots 已承担内容寻址快照 |
| ontology_versions | **不建**（复用） | VersionedMixin.version + form_revisions 修订链 + template version_number 三套版本机制已存在（附录 D ④） |
| ontology_terms | **建**（P0） | 无任何术语表；subject_key 只防重不治术语（附录 D ⑨"完全缺失"） |
| ontology_term_aliases | **建**（并入 terms 表 alias 列 or 子表，见 §2） | 同义词/别名是治理刚需（导入合成键绕开 key 冲突的根治面） |
| ontology_entities | **不建** | project_research_subjects 就是 typed entity（5 类型）；类型硬编码问题用"类型注册"解决而非新实体表 |
| ontology_relations | **不建表，建类型注册表** | project_research_subject_links 已是有类型边+唯一边+同项目 FK；缺的是 link_type 可注册而非硬编码 2 种 |
| ontology_relation_types | **建**（P0，含 subject_type 扩展注册） | 附录 D ③"link_type 白名单硬编码" |
| ontology_rules | **DEFER**（P2 评估） | 业务规则已散布在详设/gates/SOP；无消费方前不建空壳 |
| ontology_evidence_links | **不建**（用 evidence 一等表反链） | 见 domain 3；evidence.referenced_by 多态指针优于每域一张链接表 |
| ontology_review_decisions | **不建表**（复用 change_sets 状态+reviewer 列） | 沿用 guidance confirm 的 reviewed_by/at 模式 |
| ontology_change_sets | **建**（P0） | operation_events 只有 changes 摘要，无"批量变更事务单元+diff 评审"（附录 D ⑥"缺失"） |

## 2. 表设计（全部 PROPOSED；Alembic 单链新增，含 downgrade）

### 2.1 `project_evidence`（域 3 底座，先建）— **IMPLEMENTED（T-E1，迁移 `e1f3a5c7b9d2`）**

| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK projects.id, NOT NULL, ON DELETE CASCADE | 项目隔离 |
| kind | VARCHAR(24) CHECK in (gate, task, guidance, research, bridge, workflow, solution) | 证据种类 |
| source_uri | VARCHAR(500) NOT NULL | 指针（红线：不存原件） |
| content_sha256 | CHAR(64) NOT NULL | 指纹 |
| origin | TEXT | 出处文本（吸收 fde-v2 "出处+源块"粒度：如 `访谈纪要 2026-10-30 §3 / file_version:uuid / brd 章节`） |
| captured_from | VARCHAR(64) | human \| bridge_sync:{id} \| agent_run:{id} \| job:{id} \| workflow_node:{id} |
| created_by_user_id | UUID FK users.id SET NULL | |
| created_at / updated_at | TIMESTAMPTZ | |
| 约束 | UNIQUE(project_id, source_uri, content_sha256)；INDEX(project_id, kind) | 幂等去重 |

迁移策略：新表 + gates.evidence_checklist 项加可空 `evidence_id`（读时合并，旧行不受影响）。

### 2.2 `ontology_terms`+aliases — **IMPLEMENTED（T-O1，2026-11-03，迁移 `a3e7c1f9b5d2`）**

| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK projects.id, NOT NULL, CASCADE | **项目内术语**（跨项目共享词表已有 module_catalog 先例，但术语先项目内起步） |
| term | VARCHAR(120) NOT NULL | 规范业务名 |
| term_type | VARCHAR(32) CHECK in (entity, attribute, metric, alias_target, generic) | |
| definition | TEXT NOT NULL | 定义（确认后不可原地改，改走 change_set 新版本） |
| status | VARCHAR(16) CHECK in (draft, confirmed, superseded, merged) | 沿用 guidance 状态机语义 |
| canonical_term_id | UUID FK ontology_terms.id SET NULL | 合并指向：merged 行指向保留行 |
| version | INTEGER（乐观锁） | |
| confirmed_by_user_id / confirmed_at | FK users.id / TIMESTAMPTZ | 审核 |
| created_by_user_id / created_at / updated_at | | |
| 约束 | UNIQUE(project_id, term)；CHECK (status='merged' ⇒ canonical_term_id IS NOT NULL) | |

子表 `ontology_term_aliases`：id / term_id FK CASCADE / alias VARCHAR(120) / UNIQUE(project_id, alias)（同项目别名唯一，防同名冲突累积——根治附录 D ⑨ 的导入重复问题）。

### 2.3 `ontology_relation_types`（类型注册，同时服务 subject_type 扩展）— **IMPLEMENTED（T-O2，2026-11-03，迁移 `b8d3f1a5c7e2`）**

> **T-O2b 落地（2026-11-03，迁移 `b5d9e3f7a1c6`）**：subject_type 值域开放——research 侧三处 CHECK（subjects/templates/import_batches）枚举→码格式、列宽 32→60；新建值域=「内置 ∪ 注册表 active 行 − project」，闸门在 `create_subject_in_transaction`（人工+导入同闸）；retired 禁新建存量只读、draft 未拍板不入值域；注册类型本轮仅根级（无父级规则）、tracking_code=None；快照按行上实际类型分组不丢存量；AI 幻觉基线（缺省内置五类）与模板五类完整性基线不放开。

| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK projects.id NULL | NULL=全局（仅 admin 可建），非 NULL=项目内 |
| kind | VARCHAR(16) CHECK in (subject_type, link_type) | 一次解决两类硬编码：subject_type 5 值 CheckConstraint 与 link_type 2 值白名单 |
| code | VARCHAR(60) NOT NULL | 如 `opportunity_risk`、`subject_type:system` |
| label / description | VARCHAR(120) / TEXT | |
| allowed_source_types / allowed_target_types | JSON | link_type 的端点约束（替代服务层 `_validate_link` 硬编码方向） |
| status | VARCHAR(16) CHECK in (draft, active, retired) | retired 后新边禁用、存量边只读 |
| is_active, version, created_by, timestamps | | |
| 约束 | UNIQUE(COALESCE(project_id,'全局'), kind, code) | |

**实现注意（兼容边界）**：research/models.py 的 CheckConstraint(163-166) 与 subject_service.py:31-34 白名单**不动**（存量语义冻结）；注册表启用后服务层改为"注册表 ∪ 内置五类/两类"，新类型只经注册表进入。`_validate_link`（659-670）改读注册表端点约束。

**T-O2 落地裁决（偏差明细见 backlog T-O2 实施记录）**：
- **∪ 接入已生效**：`_validate_link` 改为「内置优先 + 注册表」——内置两类关系类型的端点约束是存量语义，注册表**不得覆盖内置码**（注册内置码一律 409 `duplicate_code`），因此「∪ 语义不得放开内置方向校验」的风险条由**机制**保证而非约定。
- **作用域语义落地**：设计稿的 `UNIQUE(COALESCE(project_id,'全局'), kind, code)` 落为「项目内 UNIQUE(project_id, kind, code) + 全局部分唯一索引（project_id IS NULL）」两段；**项目内类型遮蔽同名全局类型**（端点约束可按项目定制），全局类型对所有项目生效。
- **subject_type 值域本轮只落登记不开放使用**：登记 `kind=subject_type` 的行合法且可被关系类型的端点约束引用，但**新建调研对象仍只能取内置五类**——`project_research_subjects` / `template_research_forms` / `project_research_import_batches` 三处 CheckConstraint 冻结（设计兼容边界 + backlog 口径），放开值域会连带表单定义、文档映射、文档快照、AI 模板 schema 四处消费方（漏一处即静默丢数据），属独立一轮（backlog T-O2b）。
- **HTTP 面**：设计 §4 的 `GET/POST /projects/{id}/ontology/relation-types` 已开，另加一条 `POST …/relation-types/{id}/retire`（让 §5 用例 7 的「retired 后建边 409」在人工路径上可达）；三条路由均**不进 api_catalog**（人工路径，AI 候选走 change_set）。

### 2.4 `ontology_change_sets`（批量变更事务单元 + diff 评审）— **IMPLEMENTED（T-O3，2026-11-03）**

> **T-O3 落地裁决（实现偏差回写）**：①状态机补 `submit` 路由（§4 表未列）——`not_in_review`
> 错误码预设了评审态，且 base 指纹语义是「提交时受影响行指纹」，submit 即并发防护锚点；
> ②`captured_from` 括注落成列（仅服务层原语可写，HTTP 人工路径拒收）；③载荷动作域本轮开
> create_term/update_term/merge_terms/register_relation_type（项目内类型），**create_subject/
> link_subjects 暂不开放**（propose 即 payload_schema 点名拒绝——业务对象候选走既有表单/导入
> 人工路径，避免双轨）；④update_term 语义：UNIQUE(project, term) 使同名新行不可共存，**同名
> 修订=原行受控改写**（旧定义随 confirmed 事件逐项结果留档，change-set confirm 是全系统唯一
> definition 写路径——用例 3 的「不可原地改」不变式保持），**改名（new_term）才是行级取代**
> （新行 confirmed+原行 superseded 指 canonical+原名转别名）——状态域的 `superseded` 由此获得
> 真实产出场景，`draft` 由变更集占用（同 T-O2 先例）；⑤confirm 单事务**全成全败**（无 partial），
> 「补偿日志」以全有全无+事件逐项结果承载；⑥验收分离：拍板人 ≠ 提交人（403，沿 gate P0-5）。

| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK projects.id NOT NULL CASCADE | |
| title / description | VARCHAR(200) / TEXT | |
| proposed_json | JSONB NOT NULL | 变更载荷：[{action: create_term\|update_term\|merge_terms\|register_relation_type\|create_subject\|link_subjects, target…, before, after}]（AI 候选也走这里，captured_from 标 agent_run） |
| diff_summary | TEXT | 人读摘要 |
| status | VARCHAR(16) CHECK in (draft, in_review, confirmed, rejected, superseded) | |
| base_snapshot_sha256 | CHAR(64) | 提交时受影响行的内容指纹（confirm 时校验未被并发改） |
| submitted_by / confirmed_by / rejected_reason / timestamps / version | | |
| 约束 | INDEX(project_id, status) | |

confirm 语义（服务层，PROPOSED）：事务内 ①校验 base 指纹 ②逐项物化（terms/subjects/links 写入）③旧 confirmed 术语→superseded/merged ④operation_events 记 `ontology_change_set_confirmed`（携带逐项结果）。rejected 只改状态留 reason。

## 3. 代码落点（PROPOSED）

| 文件（新增） | 职责 |
|---|---|
| server/src/fde_api/evidence/__init__.py, models.py | project_evidence 模型 |
| server/src/fde_api/evidence/service.py | `upsert_evidence(session, project_id, kind, source_uri, sha256, origin, captured_from)`（sha256 幂等）、`list_evidence(project_id, referenced_by=None)` |
| server/src/fde_api/evidence/routes.py | POST/GET /api/v1/projects/{id}/evidence（require_auth+can_view；写 can_manage） |
| server/src/fde_api/ontology/__init__.py, models.py, service.py, routes.py | terms/relation_types/change_sets 模型与服务（`propose_change_set`/`confirm_change_set`/`merge_terms`/`register_relation_type`） |
| server/migrations/versions/<new>_v3_ontology_registry.py | 四表迁移（含 downgrade drop） |

**EXTEND 既有文件**：control/ontology.py（ONTOLOGY dict 保留为只读投影，新增注释指向 registry；不删除以免破坏 MCP ontology_read 契约）；gate_service.submit_gate_evidence（写 evidence 行+清单项挂 evidence_id）；research/subject_service（导入路径改走 alias 去重：同名不同 key → 提示合并候选而非静默新建）；research/models.py（links 校验读注册表）。

**不触碰**：research 既有表结构（零列改写，类型注册走服务层 ∪ 语义）、guidance/translator 全链、bridge。

## 4. API 契约（PROPOSED，全部 require_auth）

| Method/Path | 权限 | 请求 | 响应 | 错误码 | 幂等 |
|---|---|---|---|---|---|
| POST /projects/{id}/evidence | can_manage | {kind, source_uri, content_sha256, origin?, captured_from?} | {evidence, created: bool} | 400 invalid_sha256 / 403 | UNIQUE 去重天然幂等 |
| GET /projects/{id}/evidence?kind=&referenced_by= | can_view | — | {items[]} | — | — |
| GET /projects/{id}/ontology/terms?q= | can_view | — | {items[]} | — | — |
| POST /projects/{id}/ontology/change-sets | can_manage | {title, proposed_json, description?} | {change_set(draft)} | 400 payload_schema | — |
| GET /projects/{id}/ontology/change-sets?status= | can_view | — | {items[]} | 400 status | — |
| GET /projects/{id}/ontology/change-sets/{csid} | can_view | — | {change_set} | 404 | — |
| POST /projects/{id}/ontology/change-sets/{csid}/submit | can_manage | — | {change_set(in_review+指纹)} | 409 invalid_transition | — |
| POST /projects/{id}/ontology/change-sets/{csid}/confirm | can_manage（且提交人≠确认人，沿用拍板人≠执行人纪律） | — | {change_set, results[]} | 403 change_set_decider_conflict / 409 base_conflict / 409 not_in_review / 400 change_set_item_failed | — |
| POST …/change-sets/{csid}/reject | can_manage（且提交人≠确认人） | {reason} | {change_set(rejected)} | 403 change_set_decider_conflict / 409 invalid_transition / 400 reason | — |

**T-O3 落地注**：上表 change-sets 六行与 GET terms 已实施（T-O3，2026-11-03）；submit 与 GET×2 为
设计表外补充（同 T-O2 retire 先例）；confirm/reject 请求体简化为无体/`{reason}`（设计草拟的
`{confirm: true}` 不需要——状态机已区分）；全部不进 api_catalog（AI 不可触达拍板路径）。
| GET/POST /projects/{id}/ontology/relation-types | can_view / can_manage（scope=global 另需 admin） | {kind, code, label?, description?, allowed_source_types?, allowed_target_types?, scope?} | {relation_type, created} | 409 duplicate_code / 409 / 400 invalid_request | — |
| POST /projects/{id}/ontology/relation-types/{rtid}/retire | can_manage | — | {relation_type} | 409 invalid_transition | — |

审批要求：confirm 必须真人会话（沿用 gate 纪律）；AI 无法触达这些路由（不进 api_catalog，同 signoff 纪律 test_signoff_never_in_catalog）。

**T-O2 落地注**：上表 relation-types 三行已实施（T-O2，2026-11-03）；`scope` 字段区分项目内/全局登记（设计稿只说「全局=project_id 为空、仅 admin 可建」，未给落库入口，本轮以 scope 承载）。

## 5. 验收测试（server/tests/test_evidence_registry.py、test_ontology_registry.py，PROPOSED）

1. 候选不自动成为发布本体：AI 产 change_set（captured_from=agent_run）→ confirm 前 terms 表无行。**（T-O3 已实施并覆盖）**
2. 跨项目：另一项目用户 GET/POST terms/change-sets → 404/403（project_access）。**（T-O3 已实施并覆盖）**
3. confirmed 不可原地改：直接 PATCH term definition → 409 immutable（须走 change_set supersede）。**（T-O3 已实施并覆盖——「supersede」落定为改名分支 new_term；同名修订=受控改写见 §2.4 裁决④）**
4. 合并保留来源：merge_terms 后被并行 status=merged、canonical 指向保留行、alias 写入、operation_events 有逐项记录。
5. 证据不可变历史：gate 证据二次提交 → evidence 表幂等唯一；gates 行 operation_events 保留旧指针记录。
6. 变更影响分析（P2 扩展位）：term superseded 后，引用该 term 的 subjects/links 列表可查询（服务层 `impact_of_term`）。
7. relation_types：注册新 link_type→建边成功；retired 后建边 409、存量边可读。**（T-O2 已实施并覆盖）**

## 6. 复杂度与排期

T-E1~E3（evidence）S/M；T-O1（terms+迁移）M；T-O2（relation_types 接入 _validate_link）M；T-O3（change_sets confirm 事务）M；T-O4（alias 去重接入导入）S。详见 docs/implementation/v3-backlog.md。
