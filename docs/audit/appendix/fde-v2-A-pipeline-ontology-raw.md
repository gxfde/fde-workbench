# 附录 A（原始证据）：fde-v2 构建流水线 / 应用生成 / 本体与知识图谱 代码审计

> 生成方式：独立审计子代理对 `D:\test\FDE\knowledge\fde-v2`（外部快照，pyproject version=2.3.0b0，无自身 git 历史）全程只读、零执行。以下为子代理报告原文，供主报告引用；结论状态标注（VERIFIED / PARTIALLY VERIFIED / UNKNOWN）由该子代理基于真实文件行号给出。审计日期：2026-11-02。

---

## 一、实际读取文件清单（路径 + 行数）

**顶层文档**：README.md(319)、CLAUDE.md(130)、AGENTS.md(30)、HOW-TO-USE.md(233)、main.py(230，抽读)、pyproject.toml(version 行)。

**design-plus/（23 个 md 共 5925 行，全部 ls+wc；精读/抽读如下）**：架构设计.md(443，全读)、工具链使用说明.md(495，全读)、从材料到BRD.md(308，全读)、一键生成.md(111，全读)、CONVENTION.md(433，目录级+引用核对)、应用设计.md(1090，三要素节抽读)、验证门禁.md(634，章节清单+关键节抽读)；其余（应用编码/应用测试/测试执行/前端四步/迭代执行/BUG修复/多智能体方案/流程编排方案/智能体角色声明/VIEW_CONVENTION 等）经 README/CLAUDE 交叉引用核对存在性。

**fde_platform/**：knowledge_graph.py(780，全读)、ddl.py(179，全读)、sqlc.py(400，全读)、scanner.py(283，全读)、introspect.py(214，全读)、view_registry.py(262，全读)、contract_dump.py(143，全读)、config_paths.py(43，全读)、rules_admin.py(164，全读)、runtime.py(401，全读)、agent_common.py(61，全读)、agentscope_bridge.py(595，140-250/400-430 抽读)、db.py(grep 关键行)、web.py(2103，knowledge 路由 grep)、agent_roles.py(结构 grep)。

**scripts/**：run_gates.py(389，全读)、br_coverage.py(337，全读)、term_coverage.py(185，全读)、view_coverage.py(408，前 120 行+判据 grep)、br_meta_check.py(339，头 60 行)、scan_structure.py(916，前 180 行+T1-T4 grep)、verify_app_edges.py(193，全读)、verify_ddl_reconcile.py(169，全读)、book_to_brd.py(515，前 150 行)、structure_known.txt/psc_oracles_known.txt(存在性)。

**app/**：psc 组与 nasa_pms 组全目录树；精读 psc/demand 全模块（demand.py 430、schema.sql 15、README 67、HOWTOUSE 27、应用详设.md 733、前端详设 155、前端测试用例 168、view.js 211、view.html 184，合计 1990 行）；psc/_roles.py(15)、psc/_agent_tools.py(125)、nasa_pms/_agent_tools.py(70)；nasa_pms 的 本体对象.md/术语表.md/architecture_review.md 头部、kg_config.json、e2e/brd/00-目录.md。

---

## 二、逐条结论

### A. 架构与应用生成

**A1. 构建时流水线与运行时平台如何分工；哪些阶段有代码执行，哪些只是 md 规范**
结论：构建期是「**md 规格驱动的外部 AI 代理（Claude Code 等）执行轨**」+ 少量本地脚本；运行时平台（fde_platform）只做发现/加载/路由/鉴权/Agent/MCP，**不参与设计生成**。九步法 ①②④⑥⑧（分析型：产出文档）完全由代理照 `design-plus/` 规格执行，零平台代码；③⑦（编码型）也是代理写文件；⑤⑨（执行型）是「代理把用例翻译成脚本再真跑」。有真实代码执行的构建期环节仅五处：材料转换 `scripts/book_to_brd.py`、KG 索引/导出 `python -m fde_platform.knowledge_graph index/export`、契约冻结 `python -m fde_platform.contract_dump`、静态扫描 `python -m fde_platform.scanner`、门禁跑手 `scripts/run_gates.py`。
证据：`design-plus/工具链使用说明.md:3`「执行体（Claude Code 等 AI 代理或工程师）按本说明…直接逐步执行，产物直接落 app/<组>/，**不经平台任务系统**」；`design-plus/一键生成.md:3`「类型：流程编排（不产出文档，只定义顺序/停止点/交接/完成判据）」。
⚠ 重大发现：`工具链使用说明.md:4` 提到「**平台轨**（/groupbuild 页面一键任务卡片）另见《groupbuild使用说明.md》」，但该文件在仓库中**不存在**；全仓 grep `groupbuild` 仅命中 `fde_platform/llm.py:5,62` 的注释（builder 模型档案、groupbuild_runner 注入取消标志）——平台轨的任务系统代码在此快照中缺失，属文档超前于实现（或未提交）。
状态：**VERIFIED**（手工轨分工）；平台轨 **UNKNOWN**（引用的文件与页面代码缺失）。

**A2. 每个阶段的输入、输出、产物存储位置；阶段间如何传递**
结论：全部以**文件系统**为载体（app/<组>/ 目录树），无任何「阶段状态表」。速查表见 `工具链使用说明.md:443-470`：
- 上游材料轨：`app/<组>/book/`（原始 pdf/epub，不入索引不入 git）→ book_to_brd.py → `brd/第NN章-*.md`（唯一索引源）→ `kg_config.json`（分类框架）→ `kg_storage/<组>/`（KG）→ `app/<组>/本体对象.md`+`术语表.md`（组根，刻意不放 brd/ 防反馈环，`从材料到BRD.md:255-258`）。
- ① `architecture.md`（聚合根清单+卡+关系图+跨应用调用方向表）+ `architecture_review.md`（覆盖度+处置表）；② 每应用 `应用详设.md`（US/BR/FUNC/PERM+状态机+BR 三要素）；③ `<应用>.py`+`schema.sql`+`README.md`+`HOWTOUSE.md`；④ 整组一份 `测试用例.md`；⑤ `tests/verify_chain_<组>.py`(+partN)；契约冻结 `python -m fde_platform.contract_dump` → `_contracts.md`（`contract_dump.py:49-129`，运行时不加载，纯前端段依赖屏障）；⑥ `前端详设.md`+组级 `前端详设/dashboard.md`；⑦ `view.{js,html}`+组级 `dashboard.{js,html}`；⑧ 逐应用 `前端测试用例.md`；⑨ `tests/verify_view_*.py`；⑩ `_roles.py`；⑪ `_flow_*.yaml`。
阶段间传递＝下游读上游文件（③ 必须有 ② 详设，⑥ 只认最终冻结的 `_contracts.md`）。
状态：**VERIFIED**。

**A3. 阶段失败能否重试/恢复；有无状态持久化**
结论：无任务级状态持久化（无「跑到第几步」的表），靠**产物文件即状态 + 幂等重入**：`README.md:249`「可重入：每步幂等地吃上游产物→写本步产物」。机制级保障：book_to_brd.py 默认拒绝覆盖已有 brd/（`--force` 重建）；KG 索引有 LLM 提示词缓存（`kv_store_llm_response_cache.json` 按组，`从材料到BRD.md:294`）且增量 add/remove 幂等（`knowledge_graph.py:358-375`）；契约两级冻结（初始/最终，最终为硬门禁，`工具链使用说明.md:254-256`）；run_gates.py 对子检查有分层超时与「Page crashed 才重试一次」策略（`run_gates.py:294-339`）；测试隔离用影子库副本不伤真库（`shadowdb`，CLAUDE.md:69-101）。BUG 收敛回路（8.5 步）以 `tests/BUGS_<组>.md` 台账留痕。
状态：**VERIFIED**（手工轨）；平台轨恢复机制 **UNKNOWN**。

**A4. 质量门禁是代码自动验证还是 Agent 自报告；具体查什么**
结论：**两层混合——机器闸 + 执行体自检**。机器部分（`run_gates.py` 跑手，static+oracle 两层默认，退出码判 PASS/FAIL，不依赖代理自报告）：
- `fde_platform.scanner`（scanner.py:164-250 `scan_report`）：AST 校验全部 `self.fde.call` 的目标存在性+参数契约（未知/缺必传/重复/位置过多），另有 `doc_ref_report`（scanner.py:138）查 .py 源码里指向不存在 design-plus md 的悬空引用。
- `verify_ddl_reconcile.py`：临时库验证 ddl 对账补列六条边界。
- `verify_pg_translate.py`/`verify_dialect_render.py`：SQL 编译层与多方言渲染（postgres/mysql/tsql/oracle）无 SQLite 残留。
- `verify_shadow_isolation.py`/`verify_group_isolation.py`：隔离底座自检、组数据隔离对账。
- `verify_app_edges.py`（declared_edges/backend_edges/frontend_edges，:69-139）：architecture.md 声明边 ↔ 后端 `self.fde.call` ↔ 前端 `svc()` 字面量三方对账，判假声明/漏声明/仅视图层三类；缺声明表判 **SKIP 并出声**（:175-180）。
- `verify_test_script_encoding.py`：GBK 控制台打印崩溃预防。
- `scan_structure.py`（T1-T4，:531-780）：T1 用例实参逐参一致；T2 空转断言=0；T3 详设每条 BR 的 `依赖输入/输出/生效点` 三要素机器可读；T4 每条 BR 的 `输出` 字段被至少一条 TC 断言引用（取证本体 `br_coverage.py:148-231`，只认 assert/record/rec 断言）。
- oracle 层 `verify_psc_oracles.py --scenario`：PSC 专属对账体检（run_gates.py:133-137 自认写死应用清单，非 psc 组跳过）。
Agent 自报告部分：各步「覆盖度=100%」的报告（architecture_review.md、详设覆盖度、用例四要素覆盖）由执行体出具；`term_coverage.py`（:119-181）明确是「取证/报告工具，不是门禁」，默认不设分数线；`工具链使用说明.md:163-165` 明说「architecture.md 总表↔术语表」的命名核对「目前是人工项」。
状态：**VERIFIED**（混合结构如实存在；机器闸覆盖 BR 三要素/输出断言/边对齐/前端 V1-V5，其余靠自检）。

**A5. 运行时如何从对象定义生成 DDL/CRUD/视图（调用链）**
结论：**DDL 是「解析+增强」而非生成**（schema.sql 是应用自带的真相源）；**CRUD 不是生成而是内省暴露**（公共方法即服务）；**视图是扫描装配**。
- DDL：`runtime.FdePlatform._load()`（runtime.py:187-256）加载主文件后读必选 schema.sql → `db.get_connection` → `db.dialect_of(conn)` → `ddl.execute_schema`（ddl.py:170-179）：`parse_schema`(sqlglot, read="sqlite") → `_inject_audit_columns`（注入 created_at/updated_at/created_by/updated_by，ddl.py:21-41）→ `_time_funcs`（datetime('now') → CURRENT_TIMESTAMP）→ `build_ddl` 按方言渲染 → `reconcile_columns`（对已有表只补列绝不删，ddl.py:136-167）。SQLite 库文件被删时 `FdePlatform.call` 内自愈重建（runtime.py:357-362）。
- CRUD/服务：`introspect.list_services`（introspect.py:117-160）用 `inspect.signature` 读公共方法 → JSON Schema → 三入口共用（Web 表单 / `introspect.to_mcp_tool` 的 MCP+function calling / Agent）。调用统一走 `FdePlatform.call`（runtime.py:334-378）：解析→新实例注入 ctx/db/fde→执行→commit/rollback。
- DML 编译：`db.py:74-78` `_SqliteConnection.execute` / `db.py:377-383` `_PgConnection.execute` → `sqlc.compile_sql`（sqlc.py:370-400）：词法序占位符改名 `:p0`→AST 审计注入→不可映射函数拦截(`_check_unmappable`, sqlc.py:172-201，STRFTIME/JULIANDAY/PRINTF/DATE/TIME 拒绝)→PG 追加 RETURNING→驱动占位符风格→`%` 转义。lru_cache 只缓存 SQL 文本不缓存参数值（sqlc.py:329-335）。
- 视图：`view_registry._scan`（view_registry.py:112-184）扫 `view.js` 的 `PAGE_META` 正则 + `svc("app","service")` 字面量 → `registry()/boot_manifest()/page_services()`（后者供 auth 页面派生隐式放行）；mtime 令牌缓存。
状态：**VERIFIED**。

### B. 本体与领域建模

**B6. 对象候选识别、聚合根分析、实体/值对象/关系/BR 建模在哪里实现**
结论：分层实现——**候选识别是代码+LLM**（`knowledge_graph.export_entities`，knowledge_graph.py:602-715：读 graphml 摊平成 markdown 清单，按关联数降序、带出处/源块，明确「不做判断、不划边界、不生成代码」）；**聚合根分析是纯文档流程**（`design-plus/架构设计.md` = Skill 规格 fde-aggregate-identification，Step1-6 启发式：名词提取→三类判别（候选聚合根/值对象子实体/主数据）→一致性边界→聚合根卡→关系图→命名审核；产物 `architecture.md`）；**BR 建模是文档+机械兜底**（`应用设计.md` 三要素模板：`依赖输入`/`输出`/`生效点`，应用设计.md:271-330；`scan_structure.py` T3 判「读得出」，`br_meta_check.py` 判「写的东西存不存在」——输出对 schema.sql 真实列、生效点对真实方法名）。实测样例：nasa_pms 一本 297 页手册抽出 3344 实体/4080 关系（本体对象.md 头部），最终聚合根 11 个。
状态：**VERIFIED**。

**B7. 是否存在「正式本体数据库」；有无版本/审核/冲突解决/差异比较**
结论：**不存在正式本体库**。三个「本体-ish」产物全是 markdown/文件：① `app/<组>/本体对象.md`（KG 导出候选清单，文件头自认「**不是本体**（无层级/属性/公理），也不是领域模型（无标识/不变量/聚合边界）」——本体对象.md 头部与 knowledge_graph.py:654-657 双处声明）；② `术语表.md`（原词→业务名三列表，人工/半人工维护，「表一旦存在即为唯一来源，此后只增不改」是从材料到BRD.md:197 的纪律，无工具强制）；③ `config/kg_storage/<组>/graphml`（LightRAG 图，可 `--force` 重建，无版本）。**无本体版本管理、无审核工作流**（唯一「审核」是 architecture_review.md 处置表的一次性人工确认+一键生成.md:52 的唯一人工停止点）、**无冲突解决机制、无差异比较工具**（契约冻结的两版 diff、术语表演化 diff 均为人工比对）。
状态：**VERIFIED**（结论=缺失，且项目文档自身对此有清醒认知）。

**B8. 是否保存来源证据（需求来源/访谈/文档引用）**
结论：**部分保存，粒度到「文档+chunk」，不到需求条目级**。KG 导出清单每行带「出处」（file_path，缺失时从 source_id chunk 反推，knowledge_graph.py:573-589 `_origin_cell`）与「源块」（`chunk-003 等23处`，`_src_cell` :592-599），可回查 brd/ 原文。详设头部写溯源链（demand 应用详设.md:4「输入来源：architecture.md 聚合根卡 #11 + brd/05-毛需求发布和净需求运算.md §5.1~§5.5」）。BR 的 `依赖输入` 声明输入产生方（含「⚠ stub，系统内无产生方」的诚实标注，demand 详设 BR-04/06/07）。但：无访谈记录结构、无「业务方原始需求句→BR→TC→代码」的双向追溯矩阵（只有 BR→断言单向机械对账）；e2e 样板 brd/ 是**据已冻结设计反推**的（CLAUDE.md:59-61 自曝含同源成分）。
状态：**PARTIALLY VERIFIED**。

**B9. 项目（app）隔离；跨 app 引用处理**
结论：组=一级目录即隔离单元。`runtime.discover_apps`（runtime.py:90-132）：组内应用名唯一（冲突抛 FdeError），跨组允许重名；`_resolve_app`（:279-296）按「qualname 精确→调用方同组→全局唯一→歧义报错」解析；`scanner.scan_report` 同口径（scanner.py:184-199）。每应用一个同名 `.db`（或 PG schema），`FDE_DB_ROOT` 环境变量支持测试隔离（runtime.py:225-226）。Agent 侧数据隔离有专项对账 `verify_group_isolation.py`（run_gates.py:103-109，skill/告警/运转动态三块组归属）。KG 按组独立 workspace（`kg_dir()/<组>`）。跨 app 引用=**ID 弱引用不建物理外键 + `self.fde.call` 按名运行期绑定**（demand_pool README：「`material_no` 是对 `md_material.material_no` 的弱引用，不建物理外键，不做级联」）。
状态：**VERIFIED**。

**B10. 变更影响分析；verify_ddl_reconcile.py 做了什么**
结论：**无通用「对象变更→影响面」分析工具**。最接近的四件：① `verify_app_edges.py`——改代码后对账架构声明边漂移；② `fde_platform.scanner`——签名契约左移；③ `ddl.reconcile_columns`——schema.sql 加列时对已有库自动补列（只加不删）；④ `迭代执行.md` 的人工纪律（先读五文档→改代码+同步改文档→改签名必须重跑 contract_dump→scanner+verify_chain+verify_view）。`verify_ddl_reconcile.py`（:99-165）**不是业务影响分析**，而是 ddl 模块自身的验收脚本：在临时库上验证六条边界——老库缺列被补且数据不动、审计列补齐、幂等、新库正常建表、NOT NULL 无默认值的列补不了时**显式报错**、schema 删掉的列不会被自动删。对「对象变更→视图/工作流/详设联动」无任何自动分析。
状态：**PARTIALLY VERIFIED**（该有的机制=人工纪律+静态对账，无影响分析引擎）。

**B11. knowledge_graph.py 是 RAG 检索层还是可治理的正式业务语义层**
结论：**是 RAG 检索层（LightRAG 1.5.7 封装），不是可治理语义层**。数据来源：`_collect_docs`（knowledge_graph.py:107-141）只收**设计文档**——组级 architecture.md、_contracts.md、`brd/*.md`、各应用 `应用详设.md`（前端详设/README 明确不纳入）；`group=="rules"` 时收 `config/rules/*.md` 制度库。存储：本地 `config/kg_storage/<组>/`（graphml+NanoVectorDB+LLM 缓存），`--force` 全量重建。消费方式三条：Agent 工具 `platform_query_knowledge`（agentscope_bridge.py:192-209，默认查 rules 组，**描述里明文分工**：「应用组的业务规则（BR/FUNC/字段）是结构化的，请用 platform_read_app_doc 精确读应用详设，不要用本工具」）；web `/api/knowledge*` 路由（web.py:1682-1773）；`/rules-admin` 管理页（rules_admin.py）。工程细节到位：嵌入服务探活防「静默 None 编答案」（`_embed_not_ready`，:378-398）、显式关 rerank（:411-420）、kg_config.json 组级抽取配置（gleaning/entity_types/language/并发，:202-266）、防反馈环（导出物不放 brd/）。治理能力（本体版本/审核/冲突/diff）为零。
状态：**VERIFIED**。

**B12. config/rules 是什么；由谁加载；运行时如何生效**
结论：**企业非结构化制度库**（config/rules/README.md：规章制度/SOP/行业规范的 .md/.txt 自由文本），不是权限规则、不是业务规则引擎。加载：`knowledge_graph._collect_rules_docs`（:95-104）rglob 收集 → `index rules` 建 LightRAG 索引；rules_admin.py 提供上传/删除/全量索引/查询页。运行时「生效」=**纯咨询式语义检索**，不强制任何行为；当前快照 config/rules/ 下只有 README.md，制度库为空。
状态：**VERIFIED**。

---

## 三、关键调用链（文本）

```
【构建期 · 材料轨】
app/<组>/book/*.pdf ─book_to_brd.py(markitdown/pandoc 转换+切章+页眉剔除)→ app/<组>/brd/第NN章-*.md
  ─(人工抽样写 kg_config.json)→ python -m fde_platform.knowledge_graph index <组>
      → _collect_docs → LightRAG.ainsert(llm=llm.get_provider("operator"), embed=embed_service:9800)
      → config/kg_storage/<组>/graphml ─ export_entities → app/<组>/本体对象.md ─(人工)→ 术语表.md
【构建期 · 九步法（AI 代理照 design-plus/ 规格）】
brd/+本体对象.md+术语表.md ─①→ architecture.md + architecture_review.md(处置表,人工确认=唯一停止点)
  ─②→ <应用>/应用详设.md(US/BR/FUNC/PERM+三要素) ─③→ <应用>.py + schema.sql + README + HOWTOUSE
  ─④→ 测试用例.md ─⑤→ tests/verify_chain_<组>.py(真跑) ─8.5→ BUGS 台账收敛
  ─契约冻结: python -m fde_platform.contract_dump <组> → FdePlatform.load_all+introspect → _contracts.md
  ─⑥→ 前端详设.md ─⑦→ view.{js,html}+dashboard ─⑧→ 前端测试用例.md ─⑨→ verify_view_*.py(playwright+影子库)
  ─⑩⑪→ _roles.py / _flow_*.yaml ─验收→ python scripts/run_gates.py(static+oracle→VERIFY_RESULT)

【运行期 · 平台启动】
main.py → fde_platform.web(app, platform) → FdePlatform.load_all → discover_apps(app/)
  → _load: importlib 加载 <应用>.py → _find_aggregate_class → 读 schema.sql
  → db.get_connection → db.dialect_of → ddl.execute_schema(parse→注入审计列→方言渲染→reconcile_columns) → commit

【运行期 · 服务调用】
浏览器/REST POST /api/apps/<app>/call/<svc> → users.is_effectively_granted 授权
  → FdePlatform.call(runtime.py:334) → _resolve_app → 实例化+注入 ctx/db/fde
  → method(inst,**params) → self.db.execute → sqlc.compile_sql(AST 翻译+审计注入+占位符命名) → 驱动执行
  → commit / FdeError→rollback；跨应用: self.fde.call → BoundFde.call → FdePlatform.call(ctx 透传)

【运行期 · 视图装配】
/view/<组>/ → web → view_registry._scan(view.js PAGE_META + svc 字面量) → boot_manifest(菜单)
  → auth 按 page_services 派生隐式放行边(X-Fde-Page)

【运行期 · 知识检索】
Agent platform_query_knowledge → agentscope_bridge → knowledge_graph.query_sync(rules)
  → _embed_not_ready 探活 → LightRAG.aquery(hybrid, enable_rerank=False)
```

---

## 四、数据存储清单

| 位置 | 内容 | 定义位置 |
|---|---|---|
| `app/<组>/`（组根） | brd/*.md、book/、本体对象.md、术语表.md、kg_config.json、architecture.md、architecture_review.md、_contracts.md、_roles.py、_agent_tools.py、_flow_*.yaml、测试用例.md、前端测试用例.md、dashboard/process 组级页 | knowledge_graph.py:71-79、工具链使用说明 §四 |
| `app/<组>/<应用>/`（一个对象=约 10 文件） | `<应用>.py`(聚合根+规则)、schema.sql(DDL)、README.md(Agent 操作指南)、HOWTOUSE.md(注入 prompt)、应用详设.md、前端详设.md、前端测试用例.md、view.js/view.html；运行期自建 `<应用>.db` + `resource/import-file\|export-file` | runtime.py:187-233、builtin_tools |
| `app/<组>/tests/` | verify_chain_*.py(+partN)、verify_view_*.py、BUGS_*.md、测试报告 | 测试执行.md 规格 |
| `config/kg_storage/<组>/` | LightRAG graphml+向量库+kv 缓存（可重建） | knowledge_graph.kg_dir() |
| `config/rules/` | 企业制度库 .md/.txt（当前仅 README） | knowledge_graph.RULES_DIR:79 |
| `config/` 其余 | auth.db(users/mcp_tokens)、scheduler.db、agent_service.db(102.6MB 对话)、flow_runs.db、agent_alerts.db、logs/、.secret_key | config_paths.py、CLAUDE.md:79-89 |
| `scripts/structure_known.txt`、`psc_oracles_known.txt` | known-issues 基线（修好必须删） | scan_structure.py:72、验证门禁.md §七 |
| `view/` | 平台前端（lib/pages，业务不碰） | CLAUDE.md:44 |

**一个「对象」的组成（以 psc/demand 为例）**：9 个受控文件（.py/.sql/.md×6/.js/.html）+ 2 个运行期自建（.db/resource）。**无 manifest、无 .json 配置**——全靠文件名与目录约定推导（README.md:42）。平台加载路径：`discover_apps` 只认 `<组>/<应用>/<应用>.py`；`view_registry` 只认 `view.js`；`knowledge_graph._collect_docs` 只认固定 md 名单。

---

## 五、风险与差距观察（对照「可治理正式本体/证据链/版本审核」）

1. **本体层是「候选清单+纪律」，不是资产**：本体对象.md 自认非本体；术语表唯一来源地位靠流程纪律维持（term_coverage 是报告项不判失败；「只增不改」无工具守护）；无本体版本/审核/冲突/diff 任何一环。领域模型的真正正本是 `architecture.md`+各 `应用详设.md` 的自由文本——机器可校验的只有「边」（verify_app_edges）与「BR 三要素」（T3/T4）两个窄面。
2. **覆盖度大量依赖生成者自报告**：各步「覆盖度=100%」由执行体（即产物作者）出具；机械兜底覆盖 BR 断言、参数一致、空转断言、前端 V1-V5，但「BRD 每张单据都识别了」「每个 US 有用例」等核心覆盖判断仍是自检，存在「既当运动员又当裁判」的结构性风险——项目自己也承认这类漂移史（view_coverage 文档头：PSC 曾报 100% 实际菜单三处不同数）。
3. **文档↔实现漂移在发生中**：本快照内 `工具链使用说明.md:4` 引用的《groupbuild使用说明.md》不存在、平台轨代码缺失（llm.py 仅剩注释残迹）；`从材料到BRD.md:56` 引用的《从 BRD 到系统》也不存在。scanner 的 doc_ref_report 只扫 .py→design-plus 引用，md↔md 引用无人查。
4. **证据链浅层**：出处=file_path+chunk id 可回查原文是亮点，但无需求条目 ID 贯穿（业务原句→BR→TC→断言→代码无双向矩阵）；e2e 样板 BRD 系反推（CLAUDE.md 自曝）。
5. **变更影响分析缺位**：改聚合根字段波及面（视图/flow/详设/弱引用方）全靠迭代执行.md 人工先读清单；verify_ddl_reconcile 只验 ddl 模块自身行为。
6. **oracle 门禁 PSC 专属**：run_gates.py:133-137 明示 verify_psc_oracles 应用清单写死，推广需按验证门禁.md §九 参数化——门禁强度因组而异。
7. **KG 时效无守护**：设计文档变更不触发重索引，`_contracts.md` 冻结版与代码的一致性只靠「重跑 dump」纪律+时间戳核对，无自动 diff。
8. **SQL 方言硬边界**：sqlc._UNMAPPABLE 明确拒绝 STRFTIME/JULIANDAY/DATE/TIME/PRINTF 翻译（宁拒不静默错值），跨库迁移有明确天花板。
9. **信任边界**：schema.sql 与 <应用>.py 是构建期产物，平台启动即动态 import 并执行 DDL——仓库内容即信任根，无签名/校验环节。
10. 版本号不一致：pyproject.toml=2.3.0b0，README.md:34 宣称 v2.4.0 已落地 DML 编译层（代码确实在 sqlc.py）——版本管理与叙述存在漂移。

---

## 六、无法读取或无法验证的项

1. **平台轨 groupbuild**（/groupbuild 页面、groupbuild_runner、任务状态持久化）：文档引用但代码不存在于本快照——UNKNOWN。
2. **第三方库实际行为**（lightrag-hku、agentscope 2.0.6、apscheduler、sqlglot 具体版本）：未安装未执行，仅从调用侧代码推断——UNKNOWN（不属本仓代码）。
3. **verify_psc_oracles.py（3211 行）**：仅读文件头与 run_gates/CLAUDE.md 的引用描述，未逐行精读其 3211 行对账判据——PARTIALLY VERIFIED。
4. **verify_agent_quality.py（1161 行）与 scripts/agent_quality/cases.jsonl**：未精读（Agent 回答质量 eval，属运行期 Agent 域）。
5. **flow.py（657 行）**：仅读结构 grep 与文档引用，未逐行验证 DAG 执行器细节（另见附录 B，已由工作流专项审计覆盖）。
6. **web.py（2103 行）**：仅 grep knowledge/路由相关段落，未通读全部路由（另见附录 C）。
7. 运行期产物（.db、kg_storage 实例、agent_service.db）在快照中不存在（被 gitignore），存储清单中标注的表结构仅从建库代码推断。
