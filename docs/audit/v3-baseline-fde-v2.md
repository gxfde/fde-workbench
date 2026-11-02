# V3 审计基线：fde-v2（仓库 B）

- 审计日期：2026-11-02。审计方式：只读快照审计（该仓库属外部下载的不受信数据，全程零执行、零 import）。

## 1. 仓库标识与版本 — VERIFIED（快照溯源为推定）

| 项 | 值 |
|---|---|
| 本地目录 | `D:\test\FDE\knowledge\fde-v2` |
| 自身 git 历史 | **无**。该目录是宿主仓库 `D:\test\FDE`（remote=caishide/fde-ops，branch=main，HEAD 8f4ea34）下的**未跟踪快照**（knowledge/ 不入 git） |
| 上游 | `github.com/chenxi84/fde-v2`，默认分支 master，293 commits |
| 上游 HEAD（2026-11-02 查询 GitHub API） | `39e0e62d2d2a`（2026-09-29T03:16:07Z，"fix(部署): nginx 上游连接复用 + 带耗时的访问日志"） |
| 快照溯源推定 | 本地全部文件 mtime = 2026-09-29 11:16（UTC+8）= 03:16 UTC，与上游 HEAD 提交时间**逐分钟吻合** ⇒ 推定快照 ≈ master@39e0e62。**推定，非 git 校验**（PARTIALLY VERIFIED） |
| 版本号 | `pyproject.toml` = 2.3.0b0；`fde_platform/web.py:51 VERSION = "v2.4.0-beta"`；README 宣称 v2.4.0 已落地 DML 编译层——**两处版本漂移**（pyproject 注释自称需同步） |

## 2. 技术栈 — VERIFIED（pyproject.toml + 源码 import）

- **Web**：Flask ≥2.0 + waitress（非 gunicorn/uvicorn 主服务）；模板 Jinja2。
- **DB**：SQLite 默认（WAL/busy_timeout/foreign_keys=ON，`db.py:94-101`），每应用一个 `.db`；PG 可选（psycopg2/SQLAlchemy engine 或原生池），每应用一个 schema `组_应用`；**PG 连不上会静默回退 SQLite**（db.py:424-427）。
- **Agent 框架**：agentscope==2.0.6（构建期 `scripts/patch_agentscope.py` 打两个源码补丁：toolkit extra_factory 元组、schedule timezone）。
- **调度**：APScheduler BackgroundScheduler（进程内，单副本；无分布式锁）。
- **KG**：lightrag-hku ≥1.5（LightRAG）+ pyvis；独立 embedding 服务（FastAPI+uvicorn:9800，sentence-transformers，主进程不装）。
- **SQL 编译**：sqlglot（SQLite→PG 方言翻译 + AST 审计列注入）。
- **其他**：openai ≥1.0、apscheduler、openpyxl/xlrd、statsforecast==2.1.1（psc 销量预测）、cryptography（Fernet）、python-dotenv。
- **无 pytest / 无 CI**（.github 不存在）：测试全部为自带 main() 的 `verify_*.py` 脚本（仓内 71 个，其中 app/ 下 55 个），由 `scripts/run_gates.py` 分 static/oracle/chain/view 四层编排。

## 3. 代码规模（脚本自动抽取，`scripts/audit/extract_fde_v2_inventory.py`，AST/regex 零执行）— VERIFIED

| 指标 | 值 |
|---|---|
| 文件总数 | 631（py 163 / md 288 / ts-js 51 / json-yaml 9） |
| Flask 路由装饰器 | **116**（@app.route 71 / @bp.route 40 / @auth_bp.route 3 / @app.get+@app.post 2；AST 抽取口径，附录 E 人工清点为 114+，以脚本 CSV 为准） |
| 平台系统表 DDL | **17** 处真实建表（+1 users_new 升级路径 + fixture 若干已标注排除）：roles/users/service_grants/role_grants/role_page_grants/user_prefs/mcp_tokens（auth.db）、jobs/runs（scheduler.db）、endpoints/call_logs（integration.db）、llm_profiles（llm.db）、agent_alerts（agent_alerts.db）、skill（skills.db）、flow_runs/flow_run_history（flow_runs.db） |
| 应用组 | 3（psc 产销协同 22 对象 / nasa_pms 项目管理 12 对象 / e2e 样板 2 对象）= **36 个对象目录** |
| design-plus 规格文档 | 25 个 md（约 5900 行） |
| fde_platform 平台模块 | 49 个 py（web.py 2103 行最大） |

## 4. 架构速写（详见附录 A/B/E）

- **构建期（生成应用）**：md 规格驱动的外部 AI 代理执行轨（Claude Code 照 design-plus/ 规格逐步产出文件），产物直接落 `app/<组>/` 文件树，**不经任何平台任务系统**；平台只提供 5 个本地脚本（book_to_brd / knowledge_graph index+export / contract_dump / scanner / run_gates）。
- **运行期（fde_platform）**：启动时 `discover_apps` 扫描 `app/<组>/<应用>/<应用>.py` + 必选 schema.sql → importlib 加载 → ddl.execute_schema（注入 4 审计列 + 方言渲染 + 只补列 reconcile）→ `introspect.list_services` 把聚合根公共方法反射成 JSON Schema → Web 表单 / MCP tools / Agent 工具三面共用 → 一切调用经 `FdePlatform.call`（统一 commit/rollback + sqlc AST 审计注入）。
- **Agent 面**：agent_service.py（:4100，独立进程）用 AgentScope 组装 leader/worker 团队；角色下沉 `app/<组>/_roles.py`；工具面=角色∩用户授权；HITL 仅聊天路径（`_HITL_SERVICES` 9 个服务名 + `_meta.dangerous`）。
- **流程**：`app/<组>/_flow_*.yaml`（agent/call/skill 三类节点；进度落 flow_runs.db；无环检测/无节点重试/无恢复/无取消/无幂等）。
- **Skill**：config/skills.db 单表（draft→approved→deprecated；version 计数器非不可变；无发布前测试；无回滚）。

## 5. 部署 — VERIFIED

- compose 5 服务：fde-v2（waitress）、agent-service（同镜像）、embed（9800 内网）、postgres:15（fde:fde 硬编码）、nginx:alpine（唯一对外 443，TLS1.2/1.3，无 HSTS/80 跳转）。
- Dockerfile：python:3.11-slim，**root 运行**，COPY . . 后打 agentscope 补丁；`.dockerignore` 未排除 config/llm_master.key、config/.secret_key、config/.env、certs/、pgdata/（密钥可能烤进镜像层）。

## 6. 测试体系（本审计未执行任何脚本）— VERIFIED（结构）/ UNKNOWN（是否全绿）

- `python scripts/run_gates.py [--tier static|oracle|chain|view|--all]`：static（scanner 参数契约、ddl_reconcile、pg 方言翻译、agent 工具面预算/HITL 清单/角色口径零漂移、flow YAML 自洽——纯静态）→ oracle（verify_psc_oracles 直连 SQLite 对账，psc 专属）→ chain（verify_chain_* 影子库+进程内调用，不起服务）→ view（verify_view_* playwright + 起平台子进程）。
- 断言风格：`✓/✗` + `VERIFY_RESULT: PASS|FAIL` 退出码；chain 层含**变异测试**（故意改坏源码验证用例会红）。
- smoke_test.py 以 admin/admin 硬编码登录部署环境冒烟。
- **本审计按不受信数据零执行纪律，未运行任何 verify 脚本**；"当前是否全绿"记为 UNKNOWN。

## 7. 与 Workbench 的形态对照（一句话版）

fde-v2 = **"md 规格驱动、AI 代理施工、约定优于配置"的代码生成平台 + 内省式运行时**（业务逻辑=受控文件树，平台不参与设计生成）；Workbench = **"传统三层 + 迁移化 schema + 服务端鉴权中心 + AI 保守接入"的交付管理系统**。二者都以"项目/组"为隔离单元、都有 MCP 工具面，但治理重心完全不同（fde-v2 治理代码生成质量，Workbench 治理交付流程与证据）。

## 8. 无法读取/未验证项

1. 平台轨 groupbuild（/groupbuild 页面、groupbuild_runner）——design-plus 文档引用但快照中无代码（UNKNOWN，疑似文档超前或未提交）。
2. agentscope 2.0.6 内部行为与 agent_service.db 表结构——第三方库，仓内无源码。
3. 95 个应用 .py 的业务 SQL 逐行（平台层安全已覆盖，应用层未全扫）。
4. 运行时行为（SQLite→PG 静默回退实际触发、Fernet 密钥文件权限）——零执行。
5. verify 脚本是否当前全绿——未执行。
6. 快照与上游 master@39e0e62 的逐文件一致性——无 git 对象可比对，仅 mtime 推定。
