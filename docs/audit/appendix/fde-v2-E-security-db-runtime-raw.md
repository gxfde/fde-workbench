# 附录 E（原始证据）：fde-v2 安全 / 数据库 / 运行时 / 测试体系 / 前端 审计

> 生成方式：独立审计子代理对 `D:\test\FDE\knowledge\fde-v2`（快照）只读审计。以下为子代理报告原文。审计日期：2026-11-02。
> 快照溯源补充（主控核对）：上游 `github.com/chenxi84/fde-v2` 默认分支 master、293 commits、HEAD `39e0e62d2d2a`（2026-09-29T03:16:07Z，"fix(部署): nginx 上游连接复用…"，经 GitHub API 查询）。本地快照文件 mtime 全部为 2026-09-29 11:16（本地 UTC+8 = 03:16 UTC），与该提交时间一致 ⇒ **推定快照≈master@39e0e62**（推定，非 git 验证）。

## 一、实际读取文件清单

**核心（全文精读）**：`main.py`(230)、`fde.py`(22)、`pyproject.toml`(38)、`fde_platform/web.py`(2103)、`runtime.py`(401)、`db.py`(445)、`sqlc.py`(400)、`dbguard.py`(198)、`shadowdb.py`(313)、`ddl.py`(179)、`auth.py`(325)、`users.py`(1218)、`scheduler.py`(727)、`alerts.py`(85)、`logging_config.py`(49)、`config_paths.py`(43)、`mobile.py`(33)、`integration.py`(452)、`embed_service.py`(69)、`view_watchdog.py`(149)、`listsort.py`(115)、`llm_admin.py`(92)、`agent_admin.py`(237)、`rules_admin.py`(164)、`mcp_http.py`(245)、`view_registry.py`(262)、`view/lib/api.js`(136)。

**部分精读 + grep**：`llm.py`(558，L70–200)、`agent_service.py`(605，L1–80/410–470/560–605)、`agentscope_bridge.py`(595，授权段)、`builtin_tools.py`(278，L40–100)、`contract_dump.py`(143)、`skills.py`/`flow.py`/`knowledge_graph.py`(grep 表名与路径)、`view/lib/shell.js`(487)、`view/pages/workbench.js`(154)、`app/e2e/member/view.js`(68)。

**部署**：`Dockerfile`(17)、`Dockerfile.embed`(17)、`docker-compose.yml`(92)、`nginx.conf`(102)、`nginx_proxy_params.conf`(34)、`requirements.txt`(30)、`requirements-embed.txt`(7)、`.gitignore`(93)、`.dockerignore`(11)、`config/.env.example`(19)、`config/rules/README.md`(24)（`config/` 下仅此两文件）。

**测试**：`scripts/verify_group_isolation.py`(153)、`smoke_test.py`(85)、`verify_shadow_isolation.py`(165)、`verify_pg_live.py`(263)、`verify_pg_translate.py`(319)、`verify_dialect_render.py`(120)、`verify_test_script_encoding.py`(189)、`verify_psc_oracles.py`(3211，头 50)、`run_gates.py`(389)、`app/e2e/tests/verify_chain_e2e.py`(459)、`verify_view_e2e.py`(416)、样板 verify（头 30）。`templates/`(16 文件 1696 行)、`static/`(2 文件 754 行) 仅 ls+wc。

## 二、逐条结论

### 1. 入口与启动 — **VERIFIED**
- 入口 `main.py:130 main()`：`load_dotenv(config/.env)`（`FDE_MOCK=1` 追加 `mock.env`）→ `from fde_platform.web import app, platform`（import 期即 `platform.load_all()`）→ 7 个可插拔组件按 try-import 注册（auth/scheduler/llm_admin/agent_admin/rules_admin/mcp_http/mobile）→ `waitress.serve(app, threads=THREADS, channel_request_lookahead=1)`，无 waitress 回落 `app.run(debug=False)`。
- 默认 `HOST=127.0.0.1`、`PORT=4000`、`THREADS=64`（`web.py:52–67`）；Docker 下 `PLATFORM_HOST=0.0.0.0`。
- 环境变量全集：`PLATFORM_HOST/PORT/THREADS`、`SECRET_KEY`、`DATABASE_URL`、`FDE_PG_POOL_MIN/MAX/TIMEOUT/RECYCLE`、`AGENT_SERVICE_URL`、`AGENT_HOST`、`AGENT_BACKEND`、`AGENT_SERVICE_DB`、`FDE_EMBED_URL`、`FDE_KG_EMBED_MODEL/DIM`、`HF_ENDPOINT`、`LLM_MASTER_KEY`、`LLM_BASE_URL/API_KEY/MODEL`、`FDE_TIMEZONE`、`DEPLOY_MODE`、`FDE_MOCK`、测试隔离 `FDE_DB_ROOT/FDE_CONFIG_ROOT/SKILL_DB`。
- **版本漂移**：`web.py:51 VERSION="v2.4.0-beta"` vs `pyproject.toml:5 version="2.3.0b0"`。

### 2. 数据库 — **VERIFIED**
- **SQLite 默认路径**：业务库 `app/<组>/<应用>/<应用>.db`（`runtime.py:226`，`FDE_DB_ROOT` 可重定向）；平台库 `config/*.db`。`_open_sqlite`（`db.py:94–101`）设 WAL / busy_timeout=5000 / foreign_keys=ON / Row 工厂。
- **PG 切换**：`DATABASE_URL` 以 `postgresql` 开头即切；首选 SQLAlchemy Engine（pool_pre_ping），回落 psycopg2 ThreadedConnectionPool。连接失败重试 5 次×3s 后**静默回退 SQLite**（`db.py:424–427`）。每应用一个 PG schema `组_应用`（L430–440）。
- **事务边界**：**平台托管**。`runtime.FdePlatform.call`（L334–378）每次调用取新连接，正常返回→commit；异常→rollback；finally close。无 autocommit；应用代码不碰 commit。
- **审计字段注入 = AST 改写（sqlglot）**：`sqlc._compile_cached`（L329–364）：① 词法 tokenizer 把 `?` 按文本顺序改名 `:p0..`；② sqlglot parse；③ `_inject_audit` 对 INSERT 每行 VALUES / INSERT…SELECT 追加 `created_at/updated_at/created_by/updated_by`，UPDATE 的 SET 追加 `updated_at/updated_by`；④ 不可翻译函数（STRFTIME/JULIANDAY/PRINTF/DATE/TIME）PG 下明确报错；⑤ PG 自增主键 INSERT 自动追加 RETURNING；⑥ lru_cache(512) 只缓存 SQL 文本；⑦ 参数个数不匹配抛错。审计值 = ctx["userno"]。

### 3. 表结构来源 / 迁移 / 影子库 — **VERIFIED**
- 业务表：应用目录必选 `schema.sql` → `ddl.execute_schema`：解析→注入 4 审计列→时间函数改写→方言渲染→`reconcile_columns` **只补列不删列**（NOT NULL 无默认即报错）。
- **无版本化迁移系统**（无 alembic/版本表）；靠 CREATE TABLE IF NOT EXISTS + 对账补列 + 各模块内联 ALTER TABLE ADD COLUMN try/except。
- `shadowdb.py` 是**测试隔离**（copy 库文件到 tempdir + 环境变量重定向），不是变更验证影子库；`dbguard.py` 是旧路（移走真库+独占锁）。
- 系统表清单见第三节。

### 4. 鉴权 — **VERIFIED**
- **登录**：Flask 签名 Cookie 会话（非 JWT），`session["username"]`。secret_key：env → `config/.secret_key` → 自动生成。
- **密码**：werkzeug scrypt/pbkdf2。**MIN_PASSWORD_LEN=4**；`/change-password` 要求 ≥6（两处口径不一）。首启播种 **admin/admin**。
- **RBAC**：`roles(is_admin)` → `users.role`；授权单位 `应用.服务`：role_grants ∪ service_grants；`role_page_grants` 前端页面授权 → 隐式服务放行（`auth._implicit_page_grant`，`view_registry.page_services()` 静态扫描 `svc("app","svc")` 字面量派生边）。`is_admin` 全通；**`user is None`（无鉴权模式）也全通**。
- **每请求校验点**：唯一 `app.before_request(gate)`（auth.py:109–155）：白名单 {/login,/logout,/favicon.ico,/change-password,/mcp} + /static/；未登录 401/302；/auth/* 仅 admin；view_args 含 app_name+service → 服务级授权，仅 app_name → 应用可见。**非 `<app_name>` 路由的管理操作靠各视图内联 is_admin 检查**——这正是 R1/R2 漏检的根源。
- **group 隔离**（verify_group_isolation.py）：检查 skills/agent_alerts/flow_run_history 三表写入带 module、组视角=本组∪平台级、前端取数带 group=。

### 5. SQL 安全 — **VERIFIED**
- 平台层全部参数化（`?` → 编译层命名参数）；应用 SQL 经 sqlc 必须可解析、参数数匹配否则抛错。残余 f-string SQL 均无 HTTP 可控路径（schema/表名为常量）。

### 6. 文件读写 — **VERIFIED**
- 上传 `POST /api/apps/<app>/files`：`safe_filename`（剥 /、\、..、控制字符）→ `resource/import-file/`。**无文件类型/大小限制**（仅 nginx 50m；Flask 未设 MAX_CONTENT_LENGTH）。
- 下载/删除：`builtin_tools._resolve` 白名单目录 + `resolve()` 后 `target.parent == base` 严格判定 → **路径穿越防护有效**。

### 7. 异步任务 / 告警 — **VERIFIED**
- `scheduler.py`：APScheduler BackgroundScheduler（进程内线程），misfire_grace_time=600, coalesce=True, max_instances=1。任务表 jobs、运行表 runs（每任务保留 200 条）。执行 `run_job_now` → `_platform.call(app, service, ctx=run_as_user 的 ctx)`。**无重试、无幂等键、无取消（删任务即 remove_job）**；单进程调度，多副本部署会重复触发（无分布式锁）。
- 另一套"自主运行"定时任务走 agent_service 的 `/schedule/`（AgentScope 调度唤醒 leader），与 scheduler.db 无关。
- `alerts.py` 不"触发"告警：raise_alert 是 Agent 工具的落库端；`/api/alerts` 是**拉取式聚合**四源（psc 库存投影 / scheduler runs / integration call_logs / agent_alerts）。无推送。

### 8. 日志与审计 — **VERIFIED**
- `logging_config`：root DEBUG，控制台 INFO，文件 `config/logs/fde.log` 按天轮转保留 30 天。web.py 多处仍用 print。
- **无统一操作审计表**。数据级审计靠 4 审计列；调用级日志 `runtime._log_integration_call` → `integration.call_logs`（request_summary 服务入参截断**明文落库**）。用户管理操作（建用户/改密/授权）**无审计记录**。
- MCP 令牌明文经 `flash()` 放进签名 Cookie（base64 可读，一次性）。

### 9. 外部副作用 — **VERIFIED**
- `integration.py` = **端点注册表**（应用声明 _EXTERNAL_ADAPTERS 或名含 gateway 被发现），配置 url/http_method/auth_type/timeout/retries/mock。`test_endpoint` 用 urllib.urlopen 发真实请求，404/405 自动改 GET 重试。**无邮件、无 webhook**。
- `embed_service.py`：独立 FastAPI `0.0.0.0:9800`，`POST /embed` **无任何鉴权**（compose 未暴露端口）。
- LLM 调用：llm.py OpenAI 兼容/Anthropic；agent 路径 web.py 反代 agent_service（httpx，X-User-ID 注入）。**无幂等/去重**。

### 10. 敏感信息存储 — **VERIFIED**
- LLM API Key：`llm_profiles.api_key_enc` Fernet 加密，主密钥 env `LLM_MASTER_KEY` → `config/llm_master.key`（自动生成 chmod 600）；支持 `env:<VAR>` 间接引用。
- 集成凭证：复用 llm_master.key；**密钥文件不存在时明文落库**，解密失败返回原文。
- MCP 令牌：sha256 存哈希。`.gitignore` 覆盖 config/.env|llm_master.key|.secret_key|*.db；**`.dockerignore` 未排除** llm_master.key、.secret_key、config/.env、certs/、pgdata/。
- `web.py:861–865` 解密 API Key 后以明文 JSON 经 HTTP POST 给 agent_service（容器内网）。

### 11. 测试体系 — **VERIFIED**
- **无 pytest/unittest**（零 import pytest）。全部为自带 main() 的 verify_*.py 脚本，退出码 0/1 + `VERIFY_RESULT: PASS|FAIL`。
- `python scripts/run_gates.py [--tier static|oracle|chain|view|--all]` 四层：static（scanner/ddl_reconcile/pg_translate/dialect_render/agent_tools，纯静态）、oracle（verify_psc_oracles 直连 SQLite 对账，不 import 被测代码）、chain（verify_chain_*，影子库+进程内 FdePlatform().call，不需起服务）、view（verify_view_*，playwright+起平台子进程+影子库）。
- `smoke_test.py`：以 **admin/admin 硬编码**登录部署后环境冒烟。
- **可 CI 化**：static/oracle/chain 层无外部依赖可直接入 CI；view 层需 playwright；PG 层需 PG。仓内**无 .github/**。`app/` 下 tests：**55 个**（e2e 4 / nasa_pms 28 / psc 23）。
- 本审计按纪律**未执行任何 verify 脚本**（只读），其"当前是否全绿"未验证。

### 12. 部署 — **VERIFIED**
- compose 5 服务：fde-v2（build .，PG URL `fde:fde@postgres`）、agent-service（同镜像）、embed、postgres:15（./pgdata）、nginx:alpine（**唯一对外 443**）。
- nginx：TLS 1.2/1.3，/mcp 透传 Authorization，SSE proxy_buffering off。**无 80→443 重定向、无 HSTS**。
- 健康检查：http.client GET / 仅要求 getresponse()；postgres pg_isready。
- Dockerfile：python:3.11-slim，**root 运行（无 USER）**，COPY . .，构建期跑 patch_agentscope.py。

### 13. 前端 — **VERIFIED**
- 技术栈：**原生 ES Module + Alpine.js**（view/lib/alpine.esm.js 自带）+ ECharts；**无构建步骤**。平台管理页 Jinja2 模板 16 个。
- 页面注册：**零登记、扫描即发现**——view.js 内 PAGE_META 正则解析；svc("app","svc") 字面量派生页→服务边供隐式授权；mtime 令牌缓存。
- 通信契约：api.js fetch same-origin，统一 {status:"ok",data}/{status:"error",...}；401→/login；svc() 注入 X-Fde-Page。contract_dump.py dump 服务签名+真实返回样例到 _contracts.md（契约冻结）。

## 三、系统表清单

| 库文件 | 表名 | 用途 | DDL 位置 | 主键 / 外键 |
|---|---|---|---|---|
| config/auth.db | roles | 角色（is_admin） | users.py:78–83 | PK name |
| | users | 用户/密码哈希/角色 | users.py:85–96 | PK id；FK role→roles.name；UNIQUE username |
| | service_grants | 个人服务特授 | users.py:98–104 | PK(user_id,app,service)；FK user_id CASCADE |
| | role_grants | 角色服务授权 | users.py:106–112 | PK(role,app,service) |
| | role_page_grants | 角色页面授权 | users.py:114–119 | PK(role,page_id) |
| | user_prefs | UI 偏好 JSON | users.py:120–126 | PK(user_id,pref_key) |
| | mcp_tokens | MCP Bearer 令牌 sha256 | users.py:130–138 | PK id；UNIQUE token_hash |
| config/scheduler.db | jobs / runs | 定时任务/运行日志 | scheduler.py:61–86 | PK id；runs.FK job_id CASCADE |
| config/integration.db | endpoints / call_logs | 端点配置（凭证加密）/调用日志 | integration.py:31–67 | PK id；call_logs.FK endpoint_id |
| config/llm.db | llm_profiles | LLM 配置（api_key_enc） | llm.py:76–89 | PK role |
| config/agent_alerts.db | agent_alerts | Agent 上报告警 | alerts.py:23–33 | PK id |
| config/skills.db | skill | 技能库 | skills.py:31 | PK id |
| config/flow_runs.db | flow_runs / flow_run_history | 流程进度/历史 | flow.py:69,81 | — |
| config/agent_service.db | AgentScope 上游表 | 会话/消息/agent/credential/schedule | agent_service.py:56–59 | **UNKNOWN**（上游库管理） |
| app/<组>/<应用>/<应用>.db | 各应用业务表 | schema.sql + 4 审计列 | ddl.py:21–41 注入 | 随 schema.sql |
| PG 模式 | 同上 | 每应用一 schema `组_应用` | db.py:430–440 | 同上 |

## 四、HTTP 路由清单（114+ 装饰器，按模块）

**鉴权总则**：除白名单外全部先过 `auth.gate`（登录必需）；"admin"=视图内联检查；"服务闸"=gate 按 view_args 自动授权；"—"=仅登录。

**auth.py**（白名单）：GET|POST /login、GET /logout、GET|POST /change-password。
**users.py**（/auth/*，仅 admin）：GET|POST /auth/users、POST /auth/users/<u>/reset|mcp_tokens|role|grants|delete、POST /auth/roles、/auth/roles/<n>/grants|pages|admin|delete。
**web.py 页面**：GET /、/group/<k>、/app/<path>、/view/*、/app/<g>/<p>.js|.html、/favicon.ico、/integration。
**web.py API**：/api/me、/api/view_registry(+rescan= admin)、/api/my_pages、/api/prefs/<key>、/api/view_boot、/api/groups、/api/apps、/api/apps/<app>/services、**POST /api/apps/<app>/call/<service>（服务闸）**、/api/mcp/tools（全量未过滤）、/api/flow-service-options、/api/scan、GET|POST /api/apps/<app>/files、GET|DELETE .../files/<dir>/<path>、ALL /api/agent2/*（chat/stream、sessions、confirm）、GET|POST /api/agent-schedules(+toggle/delete，**无 admin**)、/api/skills、POST /api/skills/<id>/approve|deprecate|rate（admin）、GET|POST /api/flows（POST=admin）、DELETE /api/flows/<g>/<k>（admin）、/api/flow-runs、GET /api/scheduler-jobs、POST /api/scheduler-jobs(+toggle|run|delete=admin)、/api/knowledge(+upload|index|delete=admin)、/api/knowledge/query、/api/agent-overview、/api/alerts、GET /api/integration/endpoints、**POST /api/integration/endpoints（无 admin）**、/api/integration/endpoints/<id>（DELETE 仅组校验）、**POST /api/integration/test/<id>（无 admin）**、/api/integration/discover|logs|stats。
**scheduler.py**：GET /scheduler、POST /scheduler/jobs(+edit|toggle|run|delete)（服务授权内联）。
**llm_admin.py**：GET /llm、POST /llm/save|test、GET /llm/api（admin 内联）。
**agent_admin.py**：GET /agent-admin、/permission、/status（admin 内联）；**POST /agent-admin/skills/<id>/approve|reject|deprecate|rate 守卫失效（R1）**。
**rules_admin.py**：GET /rules-admin、POST upload|delete|index|query、GET /status（admin 内联，正确）。
**mcp_http.py**（白名单）：POST /mcp（Bearer）、GET /mcp 405、DELETE /mcp（无鉴权，仅删内存 sid）。
**mobile.py**：GET /m/。
**embed_service.py**（独立进程）：GET /、POST /embed（无鉴权）。

## 五、安全风险清单（有代码证据）

| # | 严重度 | 风险 | 证据 |
|---|---|---|---|
| R1 | **高** | **管理守卫返回值被丢弃 → 任意登录用户可审批/否决/弃用/评分 skill**。`_admin_guard()` 返回 redirect 但未 return，函数继续执行。被审批的 skill 会注入 leader 提示词并被 Agent 照步骤执行 | agent_admin.py:187–218（4 个 POST 路由均裸调用）；对比 rules_admin.py:76–78 正确写法 |
| R2 | **高** | **SSRF + 响应回显**：任意登录用户可保存任意 url 的 endpoint，再 test 让服务器 urlopen 并返回 body_preview[:500]。可探测内网 agent-service:4100、embed:9800、postgres、云元数据；404/405 自动改 GET 扩大面 | web.py:2049–2073、2086–2091；integration.py:336–376 |
| R3 | 中 | **非 admin 可指定 run_as_user 以他人（含 admin）身份运行任务** → 审计字段伪造 | scheduler.py:566–584、338–347、187–214 |
| R4 | 中 | **无 CSRF 防护**：Cookie 会话 + 表单 POST 无 token；未显式设 SAMESITE/SECURE | grep 全仓无 csrf；web.py:85 |
| R5 | 中 | admin/admin 默认口令 + **auth.db 被删即自动复活 admin/admin**；MIN_PASSWORD_LEN=4；登录无限速 | users.py:152–177,68；auth.py:128 |
| R6 | 中 | .dockerignore 未排除 llm_master.key、.secret_key、config/.env、certs/、pgdata/ → COPY . . 可将密钥烤进镜像层 | .dockerignore:1–11；Dockerfile:8 |
| R7 | 中 | 集成凭证在 llm_master.key 缺失时明文落库，解密失败返回原文 | integration.py:98–116 |
| R8 | 中 | PG 口令 fde:fde 硬编码入仓；容器 root 运行；无 HSTS | docker-compose.yml:10,59–60；Dockerfile 无 USER |
| R9 | 低-中 | agent_service 完全信任 X-User-ID 头（同机进程可伪造 admin）；embed_service 0.0.0.0 无鉴权 | agent_service.py:427,603–605；embed_service.py:69 |
| R10 | 低 | admin 可经 /llm/test 传任意 base_url+空 api_key+role → 服务器把已存密钥发往该 URL（admin 边界内） | llm_admin.py:69–80；llm.py:542–545 |
| R11 | 低 | /api/mcp/tools、/api/flow-service-options 向任意登录用户返回全量服务定义（含未授权应用） | web.py:570–594 |
| R12 | 低 | 入参截断明文落 call_logs；MCP 令牌明文进 Cookie；/mcp DELETE 无鉴权 | runtime.py:386；users.py:1066；mcp_http.py:203–210 |
| R13 | 低 | skills.DB_PATH 相对路径且 import 期求值，不走 config_path()，cwd 不同落错位置 | skills.py:26 |
| R14 | 低 | 版本漂移 v2.4.0-beta vs 2.3.0b0；TEMPLATES_AUTO_RELOAD 生产开启；上传无大小/类型限制 | web.py:51,85；pyproject.toml:5 |

## 六、无法验证的项

1. agent_service.db 表结构与 X-User-ID 消费方式（agentscope 2.0.6 第三方+补丁，仓内无源码）— UNKNOWN。
2. skills.py / flow.py / knowledge_graph.py / agentscope_bridge.py 全文逐行（另见附录 B 专项审计覆盖了前三者）— PARTIALLY。
3. 95 个应用 .py 的业务 SQL 是否有 f-string 拼接（平台层已覆盖，应用层未扫描）— UNKNOWN。
4. verify_psc_oracles.py 3211 行与 verify_view_* 的断言覆盖面 — PARTIALLY。
5. 运行时行为（SQLite→PG 静默回退、Fernet 密钥权限、waitress 断连回调）：未执行 — UNKNOWN。
6. templates/*.html XSS（|safe/render_template_string）— PARTIALLY（web.py:320 为常量模板）。
7. /static/ 白名单与真实文件集 — PARTIALLY。
