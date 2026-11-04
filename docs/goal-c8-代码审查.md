# goal-c8-代码审查（基建/脚本/GUI 回归/收口 + 全循环总结论）

> 循环：goal-c ｜ 轮性质：收口轮（CR-001/CR-002 当轮修 + CR-006/CR-016 销号/裁决 + gitleaks + 口径回填）｜ 日期：2026-11-05 ｜ 基于树：`4550466`（fork/main，#108）｜ 施工面：隔离 worktree `D:/test/fde-wt-c8`（分支 goal-c8-closeout）

## 1 结论一句话 + 口径数字变化

**全循环收口：两条最高危项当轮修——CR-001（P1 红线①产品名单一来源被 5 处硬编码证伪，#87 更名提交实证手工逐文件同步过）→ 桌面 `shared/brand.ts` + 服务端 `config.DEFAULT_PRODUCT_NAME` 双侧单点来源 + 静态闸防复发；CR-002（P2 共享测试库对外来迁移戳无自愈，worktree 会话互踩致全量 E 三次实发）→ conftest 外来戳检测三分支自愈（空/base→upgrade / 链内→roundtrip / 外来→DROP 重建+upgrade）根除。CR-006（DSH 记账面）取证 E0 后 needs-decision 销号交用户；CR-016（outbox 死信箱）P3 登记维持。gitleaks 全仓 CI 兜底、mypy 基线不变。口径数字：服务端 pytest **1884 收集 = 1878 passed + 6 skipped**（较 T-C1 基线 1877 +4=CR-002 conftest 自愈回归 2 + CR-001 chat 产品名 config 取值 2），桌面 vitest **767/767**（+2 brand-hardcode 静态闸），零迁移零路由。**

## 2 收口面（当轮修 + 销号 + 裁决，E0 落盘）

### 2.1 CR-001 产品名单一来源（P1，当轮修）

- 桌面 `desktop/src/shared/brand.ts`（main 引 `../shared/brand`、renderer 引 `../../../shared/brand`，沿用 `shared/contracts.ts` 双侧先例）；删 `renderer/src/brand.ts`。
- 3 处 main BrowserWindow 标题（index.ts:212 / lcsc-runner.ts:68 / lcsc-finish-dialog.ts:16）改模板串引 `PRODUCT_NAME`。
- `index.html:11` `<title>` 置中性占位「工作台」，`renderer/src/main.tsx` 渲染入口 `document.title = PRODUCT_NAME` 运行时覆盖。
- 服务端 `config.py` 增 `DEFAULT_PRODUCT_NAME` + `Settings.fde_product_name`（`server/.env` 可覆写 `FDE_PRODUCT_NAME`），`chat.py` 系统提示词改 `_product_name()` 取值（app context 走 Settings、无则回退模块常量）。
- 静态闸 `desktop/tests/main/brand-hardcode.test.ts`（node 环境扫 `desktop/src` 全 ts/tsx/html 断言除 `shared/brand.ts` 外零产品全名硬编码，2 例）；变异=改回任一硬编码→该文件命中→还原绿。
- AGENTS.md 红线① 同步为双侧单点口径；`package.json` name/appId/artifactName 与便携版目录名**不随改**（红线①原文豁免的交付口径）。

### 2.2 CR-002 共享测试库外来戳自愈（P2，根除）

`conftest.py::migrated_test_schema` 会话 fixture 改 `_reconcile_test_schema` 三分支：
- `_current_alembic_stamp`（`SELECT version_num`，无表=base）；
- `_known_alembic_revisions`（直接解析 `migrations/versions/*.py` 的 `revision = "..."`，不依赖 alembic `ScriptDirectory` 内部 API——本仓 alembic 1.19 的 `versions` 是目录路径串、`iterate_revisions(None,"heads")` 报 `RangeNotAncestorError`，故绕开）；
- 空/base→直接 `upgrade head`；链内→照旧 `downgrade base`+`upgrade head`（roundtrip 干净）；**外来戳→`DROP SCHEMA public CASCADE; CREATE SCHEMA public` 重建再 `upgrade head`**（避开 "Can't locate revision"）。
- 实跑验证：手工 `UPDATE alembic_version SET version_num='999999999999'`→跑 `test_migrations.py` 22 例全绿（触发 DROP+重建+upgrade，库戳回 `e2c6a8f4d1b3`）；链内/空路径照旧全绿。

### 2.3 CR-006 DSH 记账面（P2，needs-decision 销号，不动码）

c4/c8 两轮 grep 全链直读 E0：`ai/deepseek.py` 预算门**仅本地直连腿**（`has_app_context()` 取 `ai_monthly_token_budget`）；`ai_server_client.execute_ai_prompt`（DSH 主路径）**无** `budget_exceeded`/`record_audit` 前置、成功路径不回灌 `ai_call_audits`；`ai/kimi.py` 预算面**零命中**。⇒ `dsh_enabled=true` 时 `ai_monthly_token_budget` 对 DSH/kimi 面恒放行、skill 节点花费不入任何预算账本。裁决=**交用户拍预算口径**（是否计入平台账本 + DSH 是否补记账腿），c8 不动码。

### 2.4 CR-016 outbox 死信箱（P3，登记维持）

全仓 `register_job_failure_handler` 实有 5 类（ai.chat / automation.execute / project.presurvey.analyze / research.export / translator.translate）+ workflow.run（executor.py:441），**RECOVERABLE 九类型中 `file.scan` / `file.preview` / `document.generate` / `ai.execute` 四类无 failure hook**——耗尽后业务行（FileVersion.scan_status / DocumentGenerationJob / AICallExecution）悬空。登记不修（补 4 hook 属新能力面，归后续工程轮）。

## 3 口径数字（c8 收口后，实测）

| 面 | 值 | 依据 |
|---|---|---|
| 业务表 | 105（不含 alembic_version） | `scripts/audit/extract_workbench_inventory.py` |
| 迁移头 | `e2c6a8f4d1b3`（34 revision） | 同上（T-C1/T-D1 各 +1，已在链内） |
| 蓝图路由 | 296（36 蓝图） | 同上 |
| api_catalog ENTRIES | 94 | `api_catalog.CATALOG` 直读 |
| 服务端 pytest | **1884 收集 = 1878 passed + 6 skipped** | 全量实跑（+4：CR-002 conftest 自愈回归 2 + CR-001 chat 产品名 config 取值 2） |
| 桌面 vitest | **767/767**（串行 `--no-file-parallelism`） | 全量实跑（+2=brand-hardcode 静态闸） |
| mypy 基线 | 279 / 104 不变 | `scripts/check-python-types.py` |
| ruff | 全绿 | 改动面 |

## 4 全循环总结论（c1–c8）

- **P0**：全循环零 P0（无数据损坏/崩溃级缺陷）。
- **P1**（13 条，全 fixed）：CR-001/005/008/010/012/014/015/019/020 当轮修 + 红线面（conftest 测试库、signoff 并发、报价数值、retry 预算、executor 三处恢复/取消/写副作用）。最强项 CR-001（红线①）在 c8 收口。
- **P2**（open 6 条）：CR-006（DSH 记账 needs-decision）/CR-013（skill 计数隔离）/CR-021（本体双 confirm 无 CAS）/CR-022（cancel 外呼丢弃）/CR-027（撮合激活零调用方）/CR-028（累计预扣双误差）/CR-032（T-O2b 桌面五类滞后）。CR-002 已 c8 根除转 fixed。
- **P3**（登记 14 条）：文档漂移/纵深防御/性能卫生/测试缺口类，均不动码。
- **冻结区**（c6）：dispatch 8 态机 / package_access / match_breakdown / 三隔离 / api_catalog 全审零命中=清白确认。
- **交付纪律**：每轮 worktree 隔离施工 + 共享测试库 advisory lock 全程持有 + 变异统一循环 apply→red→restore→verify + pre-commit 前置等效检查 + 4 CI job（desktop/server-tests/gitleaks/pseudonymization）兜底 + `gh -R caishide/fde-workbench` + origin 永不 push。

## 5 门禁四件套（本轮收口）

- `npm run typecheck`：exit 0（c8 桌面改动全过，shared/brand.ts 双侧引用 typecheck 通过）
- `npm run test:server`（c8 worktree 全量）：**1880 passed + 6 skipped（16:12）exit 0**
- `npm run test:desktop`：**767/767 串行全绿（含 brand-hardcode 静态闸 +2）**
- `python scripts/check-python-types.py`：基线不变（279 / 104）exit 0
- ruff 绿；gitleaks 全仓走 CI job（secrets-scan SUCCESS 已多轮验证）。

**注**：c8 施工面=CR-001/CR-002 双侧修复 + 静态闸 + conftest 自愈，`docs/` 台账/报告 + AGENTS.md 口径回填；测试库经 conftest 新自愈路径验证（外来戳 999999999999 → DROP+重建→绿）。

## 6 后记（下一循环或 goal-d 回填）

- CR-006 needs-decision 待用户拍预算口径；CR-016 补 4 failure hook 挂后续工程轮；CR-027/028/032 各归备案/口径/桌面开放域轮。
- 全循环 P0/P1 无 open/confirmed，收口达标；AGENTS.md goal-c 收口行已回填。
