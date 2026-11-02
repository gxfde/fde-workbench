# V3 审计基线：蔡工 FDE Workbench（仓库 A）

- 审计日期：2026-11-02。审计人：ZCode 审计子代理组 + 主控（本文档）。
- 结论可信度标注：`VERIFIED` = 已从代码/命令输出验证；`PARTIALLY VERIFIED` = 部分验证；`UNKNOWN` = 未验证。

## 1. 仓库标识与 Git 基线 — VERIFIED

| 项 | 值 |
|---|---|
| 本地根目录 | `D:\test\fde-workbench` |
| 当前分支 | `fde-v2`（本地工作分支，注意与外部项目 fde-v2 同名纯属巧合——这是 Workbench 自己的 v2 工作分支） |
| HEAD commit | `05703844d7434f0dc2eefc6e62bc6ad96f7b7bb6`（0570384，"补正：翻译槽位独立 base_url …（goal-d13 补正轮）(#66)"） |
| 上游权威 | `fork` = https://github.com/caishide/fde-workbench（push 目标）；`origin` = https://github.com/gxfde/fde-workbench（上游，push 已封禁：`FORBIDDEN-origin-is-upstream-use-fork`） |
| 未提交变更 | 全部为 untracked，无已跟踪文件修改：`compose-fork-d8.yaml`、docs/ 下 10 个产品/架构文档（docx/html/md）、`scripts/gen_*.py` 4 个文档生成脚本、`城市合伙人招商路演/` 目录。**不含 server/ 或 desktop/ 代码改动** |
| 本地 main 状态 | **已核对（git ls-remote，不动本地 ref）**：本地 main = 本地 fde-v2 = fork/main（远端）= `0570384`，三者一致，无落后/领先；本地分支 fde-v2 在 fork 上无同名远端分支（纯本地工作分支） |
| 合并时远端状态（补记） | 本审计 PR（#68）跑 CI 期间 fork/main 前进至 `1f913ed`（#67 goal-d14：翻译模型来源改挂「AI 聊天」同源解析；改动 `server/src/fde_api/translator/jobs.py`、`config.py`、`server/.env.example`、2 个翻译测试文件、桌面 `SystemConfigurationPage.tsx` 与 3 份文档；**零迁移、零新路由**；d14 后 pytest 口径 1712 收集 = 1706 passed + 6 skipped，较本审计 §3/§7 的 1700+6 多出翻译模型来源六用例）。**本审计全部结论与口径仍以 `0570384` 为准**；d14 改动按文件判断不触及本审计的 signoff / 门禁 / 本体 / 工作流 / outbox 路径，但未逐条复核其对 WB-DEF-4（降级直连 AI 调用审计）等 AI 客户端相关结论的影响 → `NEEDS VERIFICATION`（下一轮开工前先对齐 fork/main 重跑 `scripts/audit/extract_workbench_inventory.py`） |
| 开工前对齐（补记②，2026-11-02，T-P0-1 轮） | 在 `04c8a39`（= #68 合并后、d14 之后）重跑 `scripts/audit/extract_workbench_inventory.py`：路由 **269** / blueprint 33 / 表 **96** / 迁移 **22** / head `c3e7a9b1d5f4` 均不变——VERIFIED；`v3-route-inventory.csv` 仅 2 行 `test_file` 列刷新（translator 两条路由新增 `test_translator_model_source.py` 覆盖），已随 T-P0-1 轮入库。T-P0-1 本身零迁移零路由，口径数字不变 |
| 开工后口径变化（补记③，2026-11-02，T-E1/T-E2 轮） | 本审计后首个带 DDL 的实施：+1 表 `project_evidence`（**97 表**）、+1 迁移 `e1f3a5c7b9d2`（**23 revision**，head 变更）、+2 路由（**271**，证据登记簿 GET/POST，有意不进 api_catalog，ENTRIES 94 不变）、+1 blueprint（34）。重跑 `scripts/audit/extract_workbench_inventory.py`（已登记新 blueprint/模型模块）核对一致。本目录 CSV/JSON 清单仍是审计基线产物（0570384 + d14 两行刷新），**未**按新口径重生成——待本体表（T-O1）落地后整体刷新 |
| 开工后口径变化（补记④，2026-11-02，T-W1 轮） | +2 表 `workflow_definitions`/`workflow_definition_versions`（**99 表**）、+1 迁移 `f2a4c6e8b1d3`（**24 revision**）、**零路由**（校验器纯函数入 CI，无 HTTP 面）；抽取脚本模型清单同步。CSV 仍为审计基线产物 |

## 2. 技术栈与运行形态 — VERIFIED

- **后端**：Python 3.13 / Flask + SQLAlchemy（非 Flask-SQLAlchemy，自研 `Database` 包装，`server/src/fde_api/extensions.py:11-48`）+ psycopg（PostgreSQL）。Gunicorn 于 Docker 容器 `fde-workbench-api-1`（127.0.0.1:8010）。
- **桌面端**：Electron + Vite + React + TypeScript（`desktop/`，136 个 ts/tsx 于 desktop/src）；API 经 `desktop/src/renderer/src/api/client.ts`（createApiClient 工厂 + 会话快照刷新）→ IPC → 主进程 → HTTP。
- **数据库**：PostgreSQL（Docker，dev 实例项目名 `fde-workbench`；测试库 `fde_workbench_test` @ 127.0.0.1:15432，`server/tests/conftest.py:66-73` 安全契约：禁回落 dev 库、库名白名单）。
- **缓存/队列**：Redis（队列 = 自研 Redis list `fde-jobs`，非 RQ/Celery）。
- **AI 服务**：外部 DSH「AI Server」运行时（`control/dsh_runtime.py`，dsh-*/plugin 命名）为编排主体；降级直连 DeepSeek / Kimi（kimi-k3）/ MiniMax（OpenAI 兼容客户端，独立槽位 base_url）。翻译管道 kimi-k3（goal-d13）。
- **容器分工**：api / scheduler（自研轮询 `flask scheduler`，非 APScheduler）/ worker（`flask worker`）/ redis；代码烤进镜像——改 server/ 后必须 rebuild + up -d + alembic upgrade head。
- **宿主 Windows / Git Bash**；docker 经 `wsl -d Ubuntu-24.04 -- docker`。

## 3. 代码规模（脚本自动抽取，`scripts/audit/extract_workbench_inventory.py`）— VERIFIED

| 指标 | 值 | 校验 |
|---|---|---|
| server/src Python 文件 | 216 | find 计数 |
| server/tests Python 文件 | 166 | find 计数 |
| 蓝图路由 | **269**（33 个 blueprint） | 裸 Flask 注册全部 blueprint 后枚举 `url_map`；与 AGENTS.md 口径一致 |
| SQLAlchemy 业务表 | **96**（不含 alembic_version） | `Base.metadata`（`fde_api.auth.models.Base`）；与 AGENTS.md 口径一致 |
| Alembic revision | **22**，root `ebb003a5c3a8`（baseline_pg）→ head **`c3e7a9b1d5f4`**（t6_review_project_toggle），单链无分叉 | AST 解析 revision/down_revision |
| 表 → 首建迁移映射 | 96/96 全部有 create_table 归属 | 见 `v3-database-inventory.csv` |
| api_catalog ENTRIES | 94（GET 48 / POST 35 / PATCH 9 / DELETE 2） | 附录 C 实测计数 |
| MCP TOOLS 注册 | 17 个（写类 2：api_execute、file_send_wechat） | `control/mcp_gateway.py:32-51` |
| builtin skills | 14（种子升级制） | `control/builtin_skills.py` |
| 桌面端 vitest | 730/730（d13 口径，串行 --no-file-parallelism） | AGENTS.md；本轮实跑结果见 §7 |
| 服务端 pytest | 1706 收集 = 1700 passed + 6 skipped（d13 口径） | AGENTS.md；本轮实跑结果见 §7 |

## 4. 模块地图（server/src/fde_api，24 个包/模块）— VERIFIED

`auth`（JWT 会话+角色 rank）、`ai`（DeepSeek/Kimi 客户端、AI 执行 SSE、行业模板/问卷/机会提示词服务、auditing）、`agents`（S1 编程工作台：registry/runs/artifacts/tool_calls/sandbox/pilot/quota）、`bridge`（openfde/fdeops 真相层单向投影）、`control`（控制平面：access 五档、mcp_gateway、api_catalog+api_actions、ai_tool_loop、ontology/knowledge、automation、skills/extensions/plugins、scheduler、chat、lcsc、weixin、task_board、ai_server_client）、`dispatch`（派单撮合）、`documents`（模板/草稿/版本/生成/快照/交付记录）、`files`（项目文件与版本）、`guidance`（调研指南/预勘/采纳）、`health`（心跳）、`jobs`（outbox/background_jobs/worker/reconcile/queue）、`mailing`（SES 退信）、`meetings`（评审会+T2/T6）、`metrics`（只读聚合）、`modules`、`projects`（项目+SOP+门禁 G1–G9+任务）、`research`（调研对象/机会/问卷/答案/导入导出）、`solutions`（方案+signoff+export-sow）、`storage`、`system_configuration`、`templates`（行业模板）、`translator`（翻译门户）、`users`、`workbench`（模型大本营 21 表）。

## 5. 测试与 CI — VERIFIED

- 文档权威：`README.md`（332 行；§快速搭建 路线 A Docker Compose / 路线 B 本地 venv、§后端运维/数据库迁移（L190）/镜像与代码变更（L201）、§开发与测试（L259）、§打包桌面端（L275）、§换机迁移清单（L235））；`AGENTS.md` 只放红线与陷阱。
- 测试命令（root package.json）：`npm run test:server`（`scripts/run-server-tests.mjs` → `server/.venv/Scripts/python.exe -m pytest`，PYTHONPATH=src）、`npm run test:desktop`（vitest）、`npm run test:operations`（node --test tests/operations）。
- 服务端测试安全契约：`FDE_TEST_DATABASE_URL` 或从根 `.env` 读 `FDE_DB_PASSWORD` 拼 `127.0.0.1:15432/fde_workbench_test`；拒绝非 postgresql+psycopg 驱动与非法库名（conftest.py:35-91）。
- CI：`.github/workflows/ci.yml`，4 个 job（desktop / server-tests / gitleaks / pseudonymization），跑 Ubuntu——Windows-only 路径（schtasks/wsl/盘符）均已可注入 mock。
- 迁移系统：Alembic（`server/alembic.ini` + `server/migrations/versions`），升级 `docker compose exec api alembic upgrade head`。

## 6. 环境与红线（影响审计范围）

- `.env` / `server/.env`（FDE_DB_PASSWORD / FDE_JWT_SECRET / FDE_BRIDGE_TOKEN）gitignored——密钥不进审计文档。
- 客户真实资料只存代号（pseudonymization CI 强制）；门禁证据只存 `source_uri` 指针 + sha256，原件留在本地 fdeops 目录。
- 本审计为**只读**：未改业务代码、未跑迁移、未调用带副作用外呼（实跑的测试全部打在专用测试库 fde_workbench_test 上）。

## 7. 本轮实跑测试基线

- 执行命令与真实结果见 `docs/audit/v3-test-inventory.md` §实跑记录（server pytest / desktop vitest / operations）。
- 任何"无法执行"的套件都会在该文件记录原因，不以"通过"表述。

## 8. 无法读取/未验证项

- 生产库真实数据分布（如 gates.template_hash 存量值）——未连库查询。
- DSH（AI Server）外部运行时内部实现——不在本仓库。
- 桌面端逐屏 UI 行为——仅静态读代码与测试，未做 GUI 实操（fde-gui-regression 技能不在本轮范围）。
- ~~GitHub 远端 fork/main 与本地的一致性~~ → 已用 `git ls-remote` 核对一致（见 §1）。
