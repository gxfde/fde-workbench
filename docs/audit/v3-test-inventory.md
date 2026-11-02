# V3 测试盘点与实跑记录

- 盘点日期：2026-11-02。**实跑记录为本轮真实执行结果**；未执行的套件明确标注原因，不以"通过"表述。

## 1. Workbench 测试资产盘点（VERIFIED）

| 套件 | 框架 | 文件数/规模 | 运行命令 | 前置 |
|---|---|---|---|---|
| 服务端单测+集成 | pytest | server/tests 166 个 py（含 fixtures/、integration/） | `npm run test:server`（→ .venv python -m pytest，PYTHONPATH=src） | FDE_TEST_DATABASE_URL 或根 .env 的 FDE_DB_PASSWORD → PG 测试库 fde_workbench_test@15432（conftest 安全契约拒绝 dev 库） |
| 桌面端 | vitest | desktop 60 个测试文件 | `npm run test:desktop` | 无外部依赖 |
| 运维脚本 | node --test | tests/operations/*.test.mjs | `npm run test:operations` | 无 |
| 类型检查 | tsc | — | `npm run typecheck` | 无 |
| CI | GitHub Actions | 4 job：desktop / server-tests / gitleaks / pseudonymization | push/PR（fork） | Ubuntu 环境解耦（无 .env/TZ 依赖） |
| 打包验证 | fde-package-verify 技能 | asar 字节验证 | 桌面交付时 | — |

测试域覆盖抽样（文件名级）：auth（rate_limit/passwords/tokens）、permissions、gates（test_gates_api/test_run_review_gates/test_t6_gate）、documents（snapshots/versions/delivery/generator/qa）、solutions（signoff/validation/skills）、agents（idempotency/traceability/budget/pilot/sandbox/fallback）、control plane（test_control_plane_api 900+ 行级断言、ai_tool_loop、api_actions、chat_mcp）、jobs（worker/outbox/job_reconcile/scheduling/heartbeat）、research（models/subjects/forms/answers/imports）、guidance、dispatch r1-r12 全线、migration（test_migrations 升降级）、变异测试方法论（d11）。

## 2. Workbench 实跑记录（2026-11-02，本地 Windows）

| 套件 | 命令 | 结果 | 退出码 |
|---|---|---|---|
| 桌面端 vitest | npm run test:desktop | **730 passed / 730（60 文件全绿），400.78s** | 0 |
| 运维脚本 | npm run test:operations | **14 pass / 0 fail，0.78s** | 0 |
| 服务端 pytest | npm run test:server | **1700 passed / 6 skipped / 0 failed（1706 收集），1502.86s = 25:02** | 0 |

### 服务端实跑终录
- 启动 2026-11-02 07:32:17（本地），结束 ≈07:57；目标库 fde_workbench_test@127.0.0.1:15432（conftest 安全契约生效）。
- 终行：`1700 passed, 6 skipped, 7964 warnings in 1502.86s (0:25:02)`，退出码 0。
- 警告：7964 条，全部为 SQLAlchemy `TypeDecorator UTCTimestamp() cache_ok` 性能提示（非失败，既有已知噪声）。
- 环境备注（如实）：运行期间检测到另一会话在隔离工作树 `D:\test\fde-workbench-d14` 于 07:51 启动了并发全量 pytest（同一共享 PG 实例）。本运行仍全绿；但该并发形态与记忆"no-parallel-mutation"纪律冲突，后续基线实跑应避开并发会话窗口。

| 指标 | 值 |
|---|---|
| collected / passed / skipped / failed | 1706 / 1700 / 6 / 0 |
| 与 d13 口径（1706 收集=1700 passed+6 skipped）一致性 | **完全一致** |

## 3. fde-v2 测试资产盘点（VERIFIED 结构 / UNKNOWN 绿否）

| 层 | 内容 | 运行方式 | 本轮是否执行 |
|---|---|---|---|
| static | scanner（self.fde.call 参数契约/doc 悬空引用）、ddl_reconcile、pg_translate、dialect_render、verify_agent_tools（工具面预算/HITL 清单/角色口径零漂移/flow YAML 自洽） | `python scripts/run_gates.py --tier static` | **否**（不受信外部快照零执行纪律） |
| oracle | verify_psc_oracles.py（3211 行，psc 专属业务对账） | `--tier oracle` | 否 |
| chain | app/*/tests/verify_chain_*.py（55 个：e2e 4 / nasa_pms 28 / psc 23；影子库副本+进程内调用；含变异自检 run_mutation_check） | `--tier chain` | 否 |
| view | verify_view_*.py（playwright + 起平台子进程） | `--tier view` | 否 |
| 冒烟 | smoke_test.py（admin/admin 硬编码登录） | 部署后 | 否 |
| 单测框架 | **无 pytest/unittest**（零 import pytest）；无 CI（.github 不存在） | — | — |

结论：fde-v2 测试体系的"是否全绿"在本审计中 **UNKNOWN**；其结构（四层分层、影子库隔离、变异自检、known-issues 基线）已纳入差距矩阵域 11 借鉴清单。

## 4. 本轮未执行与原因汇总

| 项 | 原因 |
|---|---|
| fde-v2 全部 verify 脚本 | 不受信外部数据零执行纪律（任务书红线之一） |
| Workbench GUI 回归（fde-gui-regression） | 本轮为代码审计+方案，未做 UI 实操 |
| 真实 DSH（AI Server）联调 | 外部服务副作用面，未授权不调用 |
| 生产/dev 库查询 | 只读纪律（测试库除外） |
| docker rebuild / alembic | 未改服务端代码，无需 |
