# V3 模块清单：fde-v2（快照 ≈ master@39e0e62，v2.3.0b0/v2.4.0-beta）

> 自动抽取：`scripts/audit/extract_fde_v2_inventory.py`（AST 装饰器 + DDL regex，零执行）；人工核查：附录 A/B/E。路由逐条见 `v3-route-inventory.csv`（repository=fde-v2@snapshot，116 行）；平台表 DDL 见 `v3-database-inventory.csv`（fde-v2 行，25 处含 fixture 标注）。对象/文档/脚本明细 JSON：`v3-fde-v2-inventory.json`。

## 1. 平台模块（fde_platform，49 py）

| 模块 | 行数 | 职责（VERIFIED，证据见附录） |
|---|---|---|
| web.py | 2103 | 单体 Flask 应用：页面+API 114 路由、agent2 反代 SSE、HITL confirm、flow/knowledge/integration/scheduler 管理 |
| runtime.py | 401 | `FdePlatform`：discover_apps 扫描 `app/<组>/<应用>/<应用>.py`、_load（importlib+schema.sql）、`call` L334-378（统一 commit/rollback、跨应用 self.fde.call） |
| db.py / sqlc.py | 445/400 | SQLite/PG 双轨连接；`compile_sql`：占位符改名→sqlglot AST→**审计列注入**（INSERT 4 列/UPDATE 2 列）→方言翻译（不可译函数拒译）→RETURNING；lru_cache 只缓存文本 |
| ddl.py | 179 | execute_schema：解析→注入审计列→方言渲染→reconcile_columns **只补列不删** |
| scanner.py / introspect.py / view_registry.py / contract_dump.py | 283/214/262/143 | 构建期契约层：AST 校验 self.fde.call 参数契约、doc_ref 悬空引用；公共方法反射 JSON Schema；view.js PAGE_META/svc() 字面量扫描；服务签名+返回样例 dump 到 _contracts.md |
| knowledge_graph.py | 780 | LightRAG 封装：只收设计文档（architecture/_contracts/brd/应用详设）+ rules 制度库；graphml 存储；export_entities 导出候选清单（自认"不是本体"） |
| agent_service.py | 605 | 独立进程 :4100，AgentScope create_app：leader/worker 团队、X-User-ID 租户、HITL ASK/ALLOW、_HITL_SERVICES 9 服务 |
| agent_roles.py / agent_tool_filter.py / agent_surface.py / agent_common.py | 357/91/73/61 | 角色装配（exec _roles.py）、工具过滤中间件（软剔除+硬 DENY）、工具面预算（组≤25/角色≤15）、read_app_doc |
| agentscope_bridge.py / builtin_tools.py / platform_mcp_tools.py / mcp_server.py / mcp_http.py | 595/278/186/294/245 | 工具桥（schema+execute 授权）、内置文件工具（路径穿越防护）、MCP stdio/HTTP（Bearer sha256） |
| flow.py / skills.py | 657/409 | YAML 流程（agent/call/skill；无环检测/无重试恢复取消幂等）；技能单表（draft→approved→deprecated） |
| scheduler.py / alerts.py / integration.py | 727/85/452 | APScheduler 进程内调度（无重试/幂等/分布式锁）；告警**拉取式**聚合四源；外部端点注册表（urllib 直连） |
| auth.py / users.py | 325/1218 | Cookie 会话 + before_request gate（登录+服务级授权+页面隐式放行）；RBAC 7 表 |
| llm.py / llm_admin.py | 558/92 | provider（Fernet 加密 api_key、重试 3×8s、优雅降级 NotConfigured）、admin 页 |
| shadowdb.py / dbguard.py | 313/198 | 测试隔离（复制库文件+env 重定向）/旧式移库锁 |
| 其他 | — | logging_config、config_paths、mobile(/m/)、view_watchdog、listsort、embed_service(FastAPI:9800 无鉴权)、rules_admin |

## 2. 应用层（app/，36 个对象目录 + 3 组）

| 组 | 对象数 | 说明 |
|---|---|---|
| psc（产销协同） | 22 | md_master×6 / demand×3 / plan×5 / strategy×3 / attainment / inventory_projection…；schema.sql 各自带 |
| nasa_pms（NASA 式项目管理） | 12 | requirement/wbs/review/risk/change_request/configuration_item/interface/decision/stakeholder… |
| e2e（样板） | 2 | member/task（brd/ 系据已冻结设计反推） |

**一个对象 = 约 10 个受控文件**：`<应用>.py`（聚合根+规则）、`schema.sql`、`README.md`（Agent 指南）、`HOWTOUSE.md`（注入 prompt）、`应用详设.md`、`前端详设.md`、`前端测试用例.md`、`view.js`、`view.html` + 运行期自建 `<应用>.db` 与 `resource/`。**无 manifest**——目录/文件名约定即协议。

组级资产：`brd/*.md`（唯一索引源）、`本体对象.md`+`术语表.md`（组根）、`architecture.md`+`architecture_review.md`、`_contracts.md`（冻结契约）、`_roles.py`、`_agent_tools.py`、`_flow_*.yaml`、`测试用例.md`、dashboard/process 组级页。

## 3. 构建期脚本（scripts/）

| 脚本 | 行数 | 作用 |
|---|---|---|
| book_to_brd.py | 515 | pdf/epub → brd/ 章节 md（幂等，默认拒覆盖） |
| run_gates.py | 389 | 门禁跑手：static/oracle/chain/view 四层编排 |
| scan_structure.py | 916 | T1 用例实参一致 / T2 空转断言=0 / T3 BR 三要素机器可读 / T4 BR 输出被 TC 断言引用（+known-issues 基线） |
| br_coverage.py / br_meta_check.py / term_coverage.py / view_coverage.py | 337/339/185/408 | BR 覆盖取证（只认 assert/record）；BR 字段对 schema.sql/方法名核对；术语覆盖（报告项非门禁）；前端菜单覆盖 |
| verify_agent_quality.py | 1161 | L1 工具轨迹/L2 事实/L3 结论=代码断言；L4 rubric=LLM 裁判（失效 SKIP）；需活环境 |
| verify_agent_rail.py / verify_agent_tools.py / verify_mcp_http.py | 211/329/214 | Playwright 长回合（需活环境）/静态工具面断言（入 static 门禁）/MCP HTTP 协议鉴权 |
| verify_app_edges.py / verify_ddl_reconcile.py / verify_pg_*.py / verify_*_isolation.py | — | 架构边三方对账 / ddl 对账六边界 / 方言翻译 / 影子库与组隔离自检 |
| verify_psc_oracles.py | 3211 | PSC 专属业务对账体检（应用清单写死） |

## 4. 前端（view/ + templates/）

原生 ES Module + Alpine.js（自带 3407 行）+ ECharts，无构建步骤；平台管理页 16 个 Jinja2 模板；`view/lib/api.js`（same-origin fetch、X-Fde-Page 注入、401→/login）；页面零登记（view_registry 扫描发现）。

## 5. 存储（全部为文件型，无 ORM、无迁移系统）

| 存储 | 内容 |
|---|---|
| config/auth.db | roles/users/service_grants/role_grants/role_page_grants/user_prefs/mcp_tokens（7 表） |
| config/scheduler.db | jobs/runs |
| config/integration.db | endpoints/call_logs |
| config/llm.db | llm_profiles |
| config/agent_alerts.db / skills.db / flow_runs.db | agent_alerts / skill / flow_runs+flow_run_history |
| config/agent_service.db + agent_workspaces/ | AgentScope 会话/团队/凭证（上游库管理 schema） |
| config/kg_storage/<组>/ | LightRAG graphml+向量库+LLM 缓存（可 --force 重建） |
| config/rules/ | 制度库 md/txt（当前仅 README） |
| app/<组>/<应用>/<应用>.db | 各应用业务表（schema.sql + 4 审计列） |
