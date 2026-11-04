# goal-c1-代码审查（基线 + 全仓意图对照）

> 循环：goal-c（审查+修复型）｜轮性质：**纯审查轮，无修复**｜日期：2026-11-04｜执行：ZCode 会话（fork/main 权威，开工预检通过）

## 1 结论一句话 + 口径数字变化

**意图对照三锚全扫完成：七条红线 6 绿 1 违（CR-001，P1），README/compose/CI/脚本口径全对上，V3 裁决落实整体成立但抓出 2 条文档漂移（CR-003/004）；意外收获是共享测试库外来戳事故（CR-002，P2，当日两次实发，已修复并 E0 取证）。门禁四件套全绿，口径数字零变化。**

口径数字（本包实测 2026-11-04）：

| 项 | 提示词基线 | 实测 | 判定 |
|---|---|---|---|
| 业务表 | 105 | 105（grep `__tablename__`） | ✓ |
| 迁移 head | `b5d9e3f7a1c6`（31 rev） | 同（test_migrations.py 常量 + 抽取脚本） | ✓ |
| 蓝图路由 | 295 | 295（36 蓝图，零副作用抽取脚本 `scripts/audit/extract_workbench_inventory.py`） | ✓ |
| api_catalog ENTRIES | 94 | 94（直 import 计数） | ✓ |
| pytest 收集 | 1831 | 1831（`--collect-only`） | ✓ |
| pytest 实跑 | 1825 passed + 6 skipped | **1825 passed, 6 skipped（57:34）** | ✓ |
| vitest | 750 | **750/750（复跑全绿）** | ✓ |
| 门禁 typecheck | — | **exit 0** | ✓ |
| 门禁 mypy（scripts/check-python-types.py） | — | **exit 0** | ✓ |
| 门禁 test:server | — | **exit 0，1825+6s** | ✓ |
| 门禁 test:desktop | — | **exit 0，750/750**（首跑 745+5 失败→单文件复跑 25/25 绿→全量复跑 750/750 绿，判定为环境抖动，见 §6-6） | ✓ |

**git 面变化**：fork/main 自提示词编制后前进一格——`b89a8f3`（#88）→ `46dfd4f`（**#89**，docs-only README 能力面同步，本会话开工时所在 docs 分支 `7f560bb` 的 squash 合并，2026-11-04 并行会话完成）。代码面与 #88 等价，全部口径数字不受影响；本地 main 与 fork/main 对齐（`0 0`）。

## 2 审查方法与覆盖面

- **方法**：`intended-vs-implemented` 三锚逐条取证（每条意图先立锚、再找实现证据、错配按是否跨界定级）；`code-review` 的驳斥关纪律用于每条候选发现（最强反驳写不出排除理由才入账）。全部证据 E0 本包实测（grep / git show / git log --all / PG 直查 / 抽取脚本），零 E1/E2 入账。未用子代理：意图对照是文档↔代码逐条核对，主会话批量 grep 更直接；c2+ 分包深审将按执行卡 #9 用 dynamic-workflows 编排。
- **已看**：AGENTS.md 七条红线逐条实现证据（brand.ts 单一来源全仓 grep、env 追踪面、evidence 模型字段、bridge-poll.mjs 全文 fs/CLI 面、remote pushurl、package 身份字段 × #87 diff、pseudonymization CI job + 合成种子）；README 全部可执行命令 vs 实体存在性（npm scripts ×2 层 / compose.yaml 五服务 / load_seeds.py / bootstrap-open-source CLI / CI 四 job）；V3 audit §14 PROPOSED 标注 + §20 实施跟踪 + backlog T-W6/T-S2 实施记录 + fde-v2 代码零引入核查。
- **没看 & 为什么**：业务逻辑正确性深审（c2–c7 分包轮的正事）；dispatch 冻结区逐行核查（c6 的事，本轮只确认纪律面文件存在）；gitleaks 全仓（c8 的事）。

## 3 发现清单（台账增删摘要）

### 3.1 七条红线记分板（意图对照①验收项）

| # | 红线（AGENTS.md） | 判定 | E0 证据 |
|---|---|---|---|
| 1 | 产品名只从 brand.ts 取，不再硬编码 | **✗ 违反 → CR-001（P1）** | grep 实测 5 处硬编码（main 3 窗口标题 + index.html title + chat.py 提示词）；`git show 9c9d120` 证明 #87 更名靠手工同步 |
| 2 | 客户真实资料代号化 | ✓ | CI `pseudonymization` job 扫 migrated+seeded 库（ci.yml:83）；`server/seeds/*` 全合成数据；代号 somwyn 贯穿 |
| 3 | 密钥不入 VCS | ✓ | `git ls-files` 仅 `.env.example`/`server/.env.example`；.gitignore 三行覆盖 |
| 4 | 门禁证据只存指针+sha256 | ✓ | `evidence/models.py` 行=(project, source_uri, content_sha256) + CHECK 64 位 |
| 5 | bridge-poll.mjs 只读纪律 | ✓ | fs 仅 `existsSync/readdirSync/readFileSync`；CLI 仅 `engagement list`/`status`（SLUG_RE `^[a-z0-9][a-z0-9-]{0,79}$` 白名单）；唯一 POST=自家 API |
| 6 | origin 永不 push | ✓ | `git remote -v`：origin pushurl=`FORBIDDEN-origin-is-upstream-use-fork` |
| 7 | 便携版目录名不随产品名 | ✓ | name=`@fde-workbench/desktop` / appId=`org.fdeworkbench.desktop` / artifactName=`FDE-Workbench-*` 均无产品名且 9c9d120 未触碰 |

⚠「意图未记录」：无——七条红线在 AGENTS.md 均有明文；README 口径（部署/命令/迁移/打包）与实际脚本、compose.yaml 五服务（sandbox-runner 带 `profiles=["sandbox"]` 默认不启）、CI 四 job 全部对上；V3 裁决落实面：audit §14 九表全标 PROPOSED、§20 逐项「已完成」注记至 T-S1、fde-v2 在 server/desktop 代码中仅以注释形式出现（吸收思想零引入）、backlog 实施记录齐全。

### 3.2 新增发现

**新增 4 条**（详见 `docs/goal-c-代码审查台账.md`）：

| 编号 | 级别 | 状态 | 一句话 |
|---|---|---|---|
| CR-001 | P1 | open | 红线①「改名只改这一个文件」被 5 处硬编码产品名证伪（main 3 窗口标题 + index.html title + chat.py 助手提示词；#87 更名即靠手工同步这 5 处完成） |
| CR-002 | P2 | confirmed | 共享测试库对外来迁移链戳无自愈：t-o4b worktree 未提交迁移 `d4e6f8a2c7b9` 盖戳 → 主工作区全量 E；当日两次实发 |
| CR-003 | P3 | open | V3 audit §20 实施跟踪停更于 T-S1，缺 T-S2/T-W6「已完成」注记 |
| CR-004 | P3 | open | AGENTS.md 口径数字滞后（293/1830/732 vs 实测 295/1831/实测）+ 缺 T-W6 bullet |

**驳回 2 项**：旧名 `qiflow` 命中 7 文件——全是外部基建资源名（docker 网络/容器名/WSL 目录），非产品名界面面；audit §14「新增 8 表…（9 张）」同句自正，cosmetic。

**驳斥关全记录**在台账各条目（含 CR-001 的「main 进程无法 import renderer」与「工具窗口不算产品界面」两条反驳的排除理由）。

## 4 修复记录

**N/A（纯审查轮，无代码修复）**；变异验证 N/A（理由：零修复代码）。

例外——**环境修复（非代码）**：测试库 `fde_workbench_test` 被外来迁移戳卡死（`Can't locate revision identified by 'd4e6f8a2c7b9'`）→ `DROP SCHEMA public CASCADE` + `CREATE SCHEMA public` 重建（连接凭据取自根 `.env`，只动测试库），conftest 自行 `upgrade head` + `seed_reference_data` 恢复到权威链。修复后全量 1825+6s 绿即为回归证据。

## 5 未修与移交

- **CR-001（P1）**：移交下一轮修复 PR。修法四件：共享品牌常量模块（main/renderer 双侧）、index.html 标题构建期注入或运行时 setTitle、chat.py 产品名改 config、补防复发静态检查测试。**注意 C-7**：AGENTS.md/brand 相关文件可能是并行会话（品牌轮）在途面，动手前先 `git status`。
- **CR-002（P2）**：**NEEDS-DECISION**——方案 a（conftest 捕获外来戳自动重建）vs 方案 b（worktree 强制独立测试库 env）待用户拍板；拍板前 c2+ 各轮开工预检加一步「查测试库戳是否在本链」。
- **CR-003/004（P3）**：文档轮顺手（audit §20 两条注记 + AGENTS.md 口径行/bullet 更新）。
- **BLOCKED-EXTERNAL**：无。**needs-decision**：CR-002。**外部等待**：无。

## 6 教训（已沉淀执行者 memory）

1. **server pytest 全量 E（非 F）= 先查测试库戳**：worktree 会话的未提交迁移会把 `fde_workbench_test` 的 `alembic_version` 盖成外来戳，conftest 的 `downgrade base → upgrade head` 自愈只覆盖链内戳；配方 = `SELECT version_num` 查戳 → `git log --all -- "*<戳>*"` 零命中即未提交迁移 → 查各 worktree versions 目录定位 → `DROP SCHEMA public CASCADE` 重建（conftest 会自 upgrade+灌种子）。
2. **advisory lock 全程持有 ⇒ 持锁会话结果永远可信**：多会话并存时最早拿到 `fde_workbench_test_session` 锁的跑是干净的，排队会话才会互踩——不必因为「有别的 pytest 在跑」就判自己这轮作废。
3. **pytest 管道块缓冲 8KB**：健康跑的日志可能长时间「冻结」在 384 字节（只有收集头），真信号在 `pg_stat_activity`（每秒 ROLLBACK = 每用例事务清理）；判挂先查 PG 活动，别急着杀进程。
4. **并发会话识别用命令行不看内存**：`powershell Get-CimInstance Win32_Process -Filter "Name='python.exe'"` 给 PID+创建时间+完整命令行，能分清「我的 run-server-tests 派生」与「外来 worktree pytest」；tasklist 只给内存会误判。
5. **第一印象也要过驳斥关**：本轮最初把全量 E 归因「并发 pytest 冲突」，停跑重跑仍 E——单文件前台复现才抓到真根因（戳漂移）。与 code-review 技能同构：证据不全不下结论。
6. **vitest 全量 5 失败的抖动定性实录**：失败全为 focus 断言形态、全在本会话未触碰文件（extensions/gate-board/users.test.tsx），单文件复跑 25/25 绿，全量复跑 750/750 绿——d6 三判据命中两条 + 己方零桌面改动；第三判据（stash 对照）因工作树里有品牌轮会话在途改动（LoginPage/styles.css/svg 4 个 M）受 C-7 禁令不可做，其余证据已足够定性为「并行会话 mid-run 编辑窗口抖动」。复跑期间在途改动仍在——单文件绿与全量绿都成立，说明那些改动本身不破坏测试，破坏的是「跑的中途文件被改」这一事件。
