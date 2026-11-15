# goal-liveinfra · 活体基础设施修复任务书 v1

> **线名**：goal-liveinfra（活体基础设施修复）｜**立项依据**：goal-sprint 收口终扫 2026-11-14 两项现测发现（`docs/goal-sprint-BLOCKED.md` #4/#5）；**蔡工拍板**：2026-11-14 交互选择卡「单独立项一次修两项」。
> **当前状态**：运维处置已完成，PR #474 待 CI 四绿后合并；R1 按蔡工后续拍板清退本机 diag 孤儿栈，主栈零 recreate；R2 经重测撤销，零生产代码改动。最终范围与验收证据以 §6 为准。
> **立项沿革**：§1–§5 保留最初问题判断、备选方案与排期待定记录；其中「不动 diag 栈」「一次 recreate」及 R2 修复要求已由 §6 的后续拍板与实测结论替代。不引入新监控面，不改业务行为。

## 1. 背景与问题定义

### R1 跨栈 Redis 服务别名 DNS 轮询（部署拓扑）
`fde-workbench-*` 栈与 `fde-wt-deploy-diag-*` 栈（本机遗留 compose 栈，非远端 diag.fde18.com 公网服务）共存于同一 Docker 网络 `automation_qiflow-net`，两栈 compose 服务别名同为 `redis` ⇒ Docker DNS 对名 `redis` **轮询解析**。现测证据（2026-11-14）：`fde:health:worker` 键落在 `fde-workbench-redis-1`、`fde:health:scheduler` 键落在 `fde-wt-deploy-diag-redis-1`（跨栈串写）。影响面＝心跳观测分裂＋后台队列 `lpush/brpop` 理论上可被对栈 worker 消费（后续摸底更正：两栈实际共用 `twenty-db:5432/fde_workbench`，原「独立 DB／拿错库 run_id」推断撤销；重复 worker 仍有跨栈消费队列的风险，摸底时无 running/queued 行，未观察到实际误消费）。

### R2 healthcheck 探针 FAIL 不置非零退出码（服务端）
compose healthcheck 命令 `python -m fde_api.health.heartbeat <name>` 在心跳键缺失时输出 `FAIL no heartbeat key` 但 **exit=0**（2026-11-14 实测）⇒ 容器「healthy」对心跳缺失无判别力（I4 心跳设计「卡住即 unhealthy」的语义被探针架空；worker 卡死事件 2026-11-14 实测发生、靠人工 restart 恢复）。

## 2. 修复方案

### R1 Redis 别名唯一化（择 A，B 备选）
- **A（推荐）**：`fde-workbench` 栈 compose 内将 redis 服务别名改为栈内唯一名（如 `redis` 保留服务名、network alias 增设 `fde-workbench-redis`，`FDE_REDIS_URL` host 同步改），diag 栈不动——本栈容器 recreate 后 DNS 不再与 diag 栈轮询。
- **B（备选，若 A 受网络插件限制）**：为本栈单建独立网络（`fde-workbench-net`），redis/api/worker/scheduler 全部迁入并从 `automation_qiflow-net` 摘除（注意：该网络同时承载其他跨栈 forward 容器，摘除前须核对 `fde-pg-forward`/`fde-redis-forward` 的依赖方向）。
- 涉及文件：`compose.yaml`（服务别名/网络/`FDE_REDIS_URL`）＋`.env.example` 相关注释；属部署配置面，零 Python 代码。

### R2 healthcheck 探针置 exit code
- `server/src/fde_api/health/heartbeat.py` 的 `__main__` 块：现单参模式语义核实后，改为 **check 语义**（healthcheck 场景）：键缺失/过期 ⇒ 打印 `FAIL ...` 并 `sys.exit(1)`；健康 ⇒ 打印 `OK ...` 并 `exit=0`。
- ⚠️ 先核实现网是否有其他调用方依赖「单参＝beat 写入」语义（`compose.yaml` 两处 healthcheck、值守脚本、文档）；若有，healthcheck 命令改调显式 `--check` 子命令，beat 语义保留——**调用面清查结论写进 PR 描述**。
- 测试：新增/改造用例钉住「键缺失 ⇒ exit 1」「键新鲜 ⇒ exit 0」；变异验证（删探针判别分支 ⇒ 红）。

## 3. 轮次与验收判据

| # | 内容 | 验收 |
|---|---|---|
| 单轮 | R1 compose 别名唯一化＋R2 探针 exit code，同 PR 交付 | ①两栈各自 redis 内心跳键归位（`docker exec <本栈redis> KEYS fde:health:*` 含 worker+scheduler 且 diag 栈不再新增本栈键，连续观测 ≥2 周期）；②探针变异验证：手删心跳键 ⇒ 下一探针周期容器转 `unhealthy`（先在隔离参数下验证，防误伤生产）；③活体三验（url_map/alembic current/镜像 ID）；④CI 四 job 绿；⑤diag 栈复核零扰动（其容器 healthy、其心跳键仍归其栈） |

## 4. 闸与红线

- **部署闸**：recreate 涉共享活体，执行前 `takeover_check.py --tree <部署树> --live`；与并发线部署窗口错峰；recreate 后三验＋心跳归位观测。
- **红线**：H1–H13/N1–N7 不变；不代拍部署窗口（recreate 时点如与并发线冲突，如实挂 BLOCKED 等窗口）；`FDE_REDIS_URL` 变更属部署态配置，`.env` 差异按 takeover 检查器口径登记。

## 5. 排期

**立项即排期待定**（不与并发线抢窗口）；实施授权＝本任务书在库＋蔡工对实施时点的显式令（排期≠实施授权惯例）。

## 6. 终态（goal-liveinfra R1 清退轮，2026-11-14）

**蔡工交互拍板**：①R1 修法＝**清退 diag 孤儿栈**（非本栈 compose 改名/分网）；②时点＝**立即开工**（`#472` 已收尾、无 recreate 窗口冲突）。

**R1 实修（已消解，主栈零 recreate）**：本机 diag 部署源树 `D:/test/fde-wt-deploy-diag` 已删、diag 栈 4 容器成孤儿（api 卡 `created` 因外部端口 8010 被主栈占用），实修＝`docker stop`＋`docker rm` 全 4 个 diag 容器（`fde-wt-deploy-diag-{worker,scheduler,redis,api}-1`），本机孤儿 diag 容器零残留；远端 diag.fde18.com 公网部署不在本次处置范围；diag redis volume `fde-wt-deploy-diag_fde_redis` 保留 dangling 不越界。主机侧 `fde-redis-forward`/`fde-pg-forward` 为独立常驻 forwarder（非 diag compose 服务），保留，现随 alias `redis` 唯一解析回归主栈 `.4`。活体验证全绿：`redis` alias 唯一持主 `fde-workbench-redis-1`(172.18.0.4)、`getent hosts redis`×8 全 `.4`；`fde:health:{worker,scheduler}` 键回归主栈 redis；worker `fail` 1→0 恢复 healthy；主栈 4 容器全 healthy、ID 不变。**主栈 `compose.yaml` 与 `.env` 零改动**——R1「择 A 本栈改名」方案因 diag 已清退而不再需要，`FDE_REDIS_URL` 维持原值。

**R2 判定反转（缺陷不成立，零代码改动）**：重测活体真身（`D:/test/fde-wt-crv2` 构建产物，crv2 源码与镜像逐字一致）`server/src/fde_api/health/heartbeat.py:97 return 0 if healthy else 1`＋`:102 raise SystemExit(main())`——absent-key **exit=1**、present-key **exit=0**，`docker exec fde-workbench-worker-1 python -m fde_api.health.heartbeat worker` 现测 **exit=0**（键新鲜）。本任务书 §1/§2 早期记「FAIL 却 exit=0」的观测未能复现，疑似 shell 引号或退出码捕获问题，具体成因未证实；现镜像探针 FAIL 语义已正确置非零 exit code，healthcheck「healthy」对心跳缺失具判别力 ⇒ R2 撤销，`heartbeat.py` 零改动、无需新增/改造探针测试用例。

**遗留**：diag redis volume `fde-wt-deploy-diag_fde_redis` 保留 dangling（越界不删，待后续运维窗口评估）；diag 栈 4 容器本体已清退，若本机 diag compose 栈日后重建须以唯一网络别名重新立项，不回归本缺陷。
