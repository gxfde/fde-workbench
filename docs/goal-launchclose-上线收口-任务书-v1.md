# goal-launchclose · 上线收口任务书 v1

你是执行者，本文档是你唯一任务来源，中途没人可问——拿不准的写 `docs/goal-launchclose-BLOCKED.md`（待裁决清单），跳过继续做别的，随交付提交。断了/换新会话：先读 `docs/goal-launchclose-PROGRESS.md`（进度账）接着做，别重做，每做完一项立刻更新。

**这活为什么干**：上线前评测报告 v1.1（`docs/audit/上线前评测报告-2026-11-17.md`，party 评审追改版）判定 A 线「对外受控试用」有条件可放行，但工程态有三个 P0（main CI 红／本机主栈活体漂移／远端部署态未现测）＋关窗与文档债。本线干完 = A 线工程侧达到「G-C 可签」状态：CI 绿、本机活体三验绿、远端现测一致性有据、N1 窗口按期关闭、11-16 轮次文档债清偿。

**让步顺序**：生产活体安全 > 口径诚实（没测过就说没测过）> 做得全 > 做得快。
**法与情报**：「只允许／不许」违反即失败；「建议」有更好的路可走，在 PROGRESS 记一句为什么。AGENTS.md 红线全文适用（密钥不落盘不进 argv、客户资料零外发、`origin` 永不 push、AI 不代拍 G-C、AI 不持远端凭据）。

## 我替领导拍的板

- 评测报告三拍板卡未获应答，按「按推荐执行＋留痕可推翻」生效：①报告已追改 v1.1；②**远端部署树不升版**，维持 G-C 判据快照（只做只读现测核对）；③本任务书＝单轮收口（P0×3＋P1 关窗，文档债/r53 随轮死线）。
- **R3 远端现测执行通道**＝命令清单交 OPS/HOST 亲手执行、回执回填（猜的：AI 持远端凭据涉红线）。猜错代价＝若蔡工授权只读 SSH 通道，改走通道，其余不变。
- **R4 关窗时点**＝2026-11-19 窗口到期当日或之后执行；到期前只备料不执行（窗口仍生效）。
- **R1 复跑仍红**＝按真回归修复（不降级挂账、不放宽测试）。猜错代价＝白修一个 flake，半小时量级。

## 界限

- **独立 worktree 施工**（`git worktree add` 自 fork/main tip 新建），不占用评测树与部署树的工作区。
- **两份输入文档目前只在评测工作树、未入库**（untracked）——你自建的 worktree 里没有它们。开工第一步先把下面两个绝对路径的文件**逐字节复制**进你的 worktree 同名相对路径（Windows 同机直接复制）：
  - 评测报告 v1.1：`C:/Users/P1/.zcode/worktrees/a6c5/fde-workbench/docs/audit/上线前评测报告-2026-11-17.md`
  - 本任务书：`C:/Users/P1/.zcode/worktrees/a6c5/fde-workbench/docs/goal-launchclose-上线收口-任务书-v1.md`
  - 复制后 `git status -s` 应见两个 `??` 文件；**两文件随本线收口 PR 一并提交入库**（任务书落库归档＝交付物之一，丢失即重新复制）。
- 白名单：`server/**`、`desktop/**`、`scripts/**`、`docs/**`、`.agents/**` 常规变更面；部署树 `D:/test/fde-workbench` 仅限 compose 构建/recreate 操作与 `server/.env` 的 R4 两动作（只许改 `FDE_AGENT_HOST_POLL_ENABLED` 一键）。
- 判卷标准碰都不许碰：`.github/workflows/ci.yml`、既有测试断言与阈值不得放松。
- 最诱人的顺手活（顺手重构、顺手修无关 bug、顺手升依赖）→ `BLOCKED.md` 登记，不做。
- 收不回的操作（远端任何写面、G-C 代签、删除数据、改权限）→ 停下写 `BLOCKED.md` 做别的。

## 现状与任务 0

评测基线（2026-11-17 现测）：
- fork/main tip `694c647e`；CI run `43867006517` server-tests **1 failed**（`test_crv_batch_a.py::test_qr018…` → `project_creation_failed` 503）／3996 passed／10 skipped；desktop/secrets-scan 绿。
- 本机主栈：镜像 `0c221083b29d`（2026-11-15T07:31 构建）、url_map **493**、容器内 `python -m alembic current` 报 **ModuleNotFoundError: fde_api.projects.gate_receipt**；`/app/migrations` 挂载 `D:/test/fde-workbench/server/migrations`（86 文件，头 `d8b4f6a2c9e7`）；ready/live 200。
- 结构口径：54 蓝图／515 路由／159 表／86 rev 单头 `d8b4f6a2c9e7`（本地 `f638d236` 检出，落后 fork/main 2 PR）。

**任务 0（前提核验，逐条跑、贴输出）**：
0. **先落两份输入文档**：按「界限」节的两个绝对路径，把评测报告 v1.1 与本任务书复制进你 worktree 的同名相对路径；`git status -s` 贴输出（应见两个 `??`）。复制不到＝文件丢失，立即报 BLOCKED 停工。
1. `git fetch fork && git log --oneline -3 fork/main && git rev-list HEAD..fork/main --count`——对齐基线，tip 前进超过预期（>6）即停报 BLOCKED。
2. `gh run view 43867006517 -R caishide/fde-workbench --json conclusion --jq .conclusion`——确认仍 `failure`（若已被他人复跑转绿，R1 改为登记收口）。
3. `ls server/migrations/versions/*.py | wc -l`（=86）＋`grep -l "down_revision" server/migrations/versions/d8b4f6a2c9e7*.py`（在场）。
4. `python scripts/deploy/takeover_check.py --help`（命令在场；2026-11-17 已亲验）。

对不上就停，证据写 BLOCKED.md 最上面，只做不受影响部分；核对无误后把「理解的目标／顺序／最大风险」≤10 行写进 PROGRESS.md 再动工。

## 任务（按依赖排序）

**R1 CI 定性**（先做：决定是否追加修复批）
`gh run rerun 43867006517 -R caishide/fde-workbench --failed`，守至 server-tests `completed`。
- 全绿（四 job `conclusion=success`）→ 分支甲收口，登记回执。
- 仍红 → 真回归分支：systematic-debugging 定位根因 → 修复提交（生产码与测试同 PR；禁 skip/放宽断言/mock 被测；server 收集数 ≥4007）→ 新 PR 重守四绿。

**R2 本机主栈带闸重建三验**（次做：若 R1 真回归，重建须含修复后代码，故排后）
- 先闸：`python scripts/deploy/takeover_check.py --tree D:/test/fde-workbench --live`——FAIL 项先补齐再动，输出贴对话。
- 部署树内：`docker compose -p fde-workbench build api worker scheduler` → `docker compose -p fde-workbench up -d --force-recreate api worker scheduler` → 容器内 `python -m alembic upgrade head`。
- **三验（输出逐项贴对话）**：①容器内 url_map non-static 计数（重建前 493 → 重建后新值，**值变化即重建生效的反向验证**）；②容器内 `python -m alembic current`＝`d8b4f6a2c9e7 (head)`；③`docker inspect --format '{{.Image}}'` 三容器＝本树 `docker images` 同 tag 构建 ID；④`curl http://127.0.0.1:8010/api/v1/health/ready` 与 `/live`＝200。
- 死规矩：只动 `fde-workbench` 前缀容器（同网络 qiflow-* 邻栈零触碰）；禁 `docker compose down` 全局面；recreate 仅 api/worker/scheduler。

**R3 远端部署树只读现测**（可并行）
把以下只读清单整理进 PROGRESS 交 OPS/HOST 亲手执行，回执回填一致性对照表（6 项×远端现状/G-C 快照/一致?）：镜像版本与创建时间／容器内 `alembic current`／`FDE_DIAGNOSTICS_ENABLED`·`FDE_REGISTRATION_ENABLED`·出站闸两键·`FDE_AGENT_HOST_POLL_ENABLED` env 五键／`https://app.fde18.com` ready-live 探活。**漂移 ⇒ BLOCKED.md 重开升版拍板，不擅动远端**。AI 零远端凭据、零远端写面。

**R4 N1 关窗批次**（时点锁：2026-11-19 到期当日或之后；提前只备料）
- 部署树 `server/.env` 置 `FDE_AGENT_HOST_POLL_ENABLED=0` → recreate api → 容器 env 复验输出贴对话。
- claim token 吊销/轮换核验（Vex F2）：读 `agents/host_*` 鉴权面与 token sha256 存储形态，以既有测试钉输出证明窗口/令牌状态失效后旧票不可领取；核不出 ⇒ BLOCKED.md。
- 窗口关闭登记回执（PROGRESS＋台账登记行）。

**R5 随轮死线批次**（并入收口 PR）
- CHANGELOG 补 2026-11-16 轮次七节（#487/#488/#489/#490/#491/#492/#493/#494 对应 W1/W2-2/W3/TrustBoard/AF1-WP1b/WP3/V3.3 docs——按实际 PR 对号），只许新增节不许改旧节。
- 台账（`docs/audit/下一步实施台账-2026-11-07.md`）补登记＋AGENTS「当前状态」行刷新＋口径三件套/archify 复核（路由 515 是否已入清单，差则重生成）。
- 便携版 **r53**：三源 bump（RELEASE-COUNTER 52→53＋desktop/package.json＋web 桥）→ `npm run typecheck && npm run test:desktop` → 打包 → asar 字节验证（正向 marker＋r52 反向对照全过），独立输出目录防句柄锁。

## 规矩

- **防作弊**：CI 绿只认 `conclusion=success` 全四 job；禁 skip/todo/放宽断言/改阈值/`|| true`；测试收集数 ≥4007 基线；CHANGELOG 只增不改。
- **Skill 关卡（DoD 硬性，不是建议）**：开工 `Skill(fde-delivery-flow)`（认领前查在途 PR）；R1 真回归 `Skill(systematic-debugging)`；R2/R4 部署动作前后 `Skill(verification-before-completion)`；R5 r53 `Skill(fde-gui-regression)`＋`Skill(fde-package-verify)`；PR 前 `Skill(code-review)` 只读 diff；收尾 `Skill(neat-freak)`。
- 工作流：feature 分支 → push fork（`origin` 永不 push）→ PR → 四 CI job 全绿 → **人工合并（蔡工）**。
- 三道止损：同一验收连败 3 次换下一项；活体状态比开工差（三验恶化）→ 立即回滚原镜像并如实报告；或跑满 5 轮——满轮即停，如实汇报卡在哪。

## 完成条件（两条硬指标）

1. **度量**：main tip（或真回归修复 PR）CI 四 job `conclusion=success`；本机主栈三验三项输出＋ready/live 200 全部贴在对话（含 493→新值的反向验证）；r53 asar 验证全过。
2. **约束**：远端一致性对照表完成且**远端写操作=0**；R4 仅在窗口到期后执行、容器 env 复验输出在案；本机 qiflow-* 邻栈容器零 recreate（`docker ps` 前后对照）。

每条判据贴实际命令输出（含反向验证红→绿证据），只说做完了不算。`BLOCKED.md` 随交付提交，空的写「无」。
