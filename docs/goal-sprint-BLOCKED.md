# goal-sprint BLOCKED / 待授权登记

> 任务书 §4：「拿不准的写 `docs/goal-sprint-BLOCKED.md`」；§8：「BLOCKED.md 随收口 PR 提交」。
> 本线 r1–r6 与收口终扫全程无 Agent 侧阻塞项；以下为**收口终扫现测发现的共享活体风险与待授权业务闸**，全部不属于本线改动面。
> **✅ 四项已于 2026-11-14 经交互选择卡由蔡工拍板**（推荐项前置、留痕可推翻）——逐项留痕见各条「拍板回写」行；由此派生的两份新件：`docs/deployment/对外受控试用-G-C签署材料包-2026-11-14.md`（拍板②）与 `docs/goal-liveinfra-活体基础设施修复-任务书-v1.md`（拍板④）。

## 待授权（业务闸，Agent 不代拍）

1. **D7 阈值拍板**：四口径复审报告已于 r4 出齐（`docs/audit/D7-四口径运行证据复审报告-2026-11-13.md`），阈值拍板位维持「待蔡工拍板」（零预支，闸态变更=0）。
   **拍板回写（2026-11-14）**：**维持待拍板**——支撑度 `insufficient_for_unfreeze`（候选开放档同类样本＝0），样本达标后再拍；拍板材料包（报告 §6 承接表）已在库随取。
2. **G-C 上线闸签署与试用账号发放**（口径更正：G-A 已签 2026-11-09、G-B 已有效签署 2026-11-10，未签的只有 G-C；十三项技术判据已现测具备）。
   **拍板回写（2026-11-14）**：**整理签署材料包**——已落 `docs/deployment/对外受控试用-G-C签署材料包-2026-11-14.md`（三闸现状＋G-C 剩余判据逐项指针＋T5-7 外部真机执行指引＋签署三步＋值守/回收预案成文＋证据索引＋分发告知义务）；T5-7（外部真机登录＋改密＋写操作）与 G-C 签署、口令发放均归 `OWNER`/`HOST` 亲手，AI 不代签不代发。
3. **N1 试点窗口到期处置**：窗口 2026-11-12～2026-11-19；窗口内 2 条 `host_poll` run 全 `completed` 且 8/8 产物已人工复核（2026-11-14 现测），窗口 11-19 到期后的续期/关闭/回收决策归蔡工。
   **拍板回写（2026-11-14）**：**按期关闭**——11-19 到期后如实登记窗口关闭；宿主通道转回待授权态；r4 复审证据已固化，无需续期。

## 共享活体风险沿革（2026-11-14：#4 已消解，#5 经复核撤销）

以下问题描述与初次拍板保留作历史记录；当前结论以各条「实修回执」为准，已无本节待实施修复项。

4. **跨栈 Redis 服务别名冲突（DNS 轮询）**：`fde-workbench-*` 栈与 `fde-wt-deploy-diag-*` 栈（本机遗留 compose 栈）共存于同一 Docker 网络 `automation_qiflow-net`，两栈 compose 服务别名同为 `redis` ⇒ Docker DNS 对名 `redis` 轮询解析。现测证据：`fde:health:worker` 键落在 `fde-workbench-redis-1`、`fde:health:scheduler` 键落在 `fde-wt-deploy-diag-redis-1`（跨栈串写）。影响面＝心跳观测分裂＋后台队列 `lpush/brpop` 理论上可被对栈 worker 消费（当前 `background_jobs` 无 running/queued 行，暂无实害）。处置选项（改 compose 网络别名唯一化或两栈分网）＝生产拓扑变更，超出收口轮零代码范围且涉另一栈 ⇒ 待蔡工拍板后单独立项。
   **拍板回写（2026-11-14，与 #5 合并处置）**：**单独立项一次修两项**——立项任务书已落 `docs/goal-liveinfra-活体基础设施修复-任务书-v1.md`（R1 别名唯一化择 A：本栈 network alias 唯一名＋`FDE_REDIS_URL` 同步；R2 探针按 check 结果置 exit code）；实施排期待蔡工显式令（排期≠实施授权）。
   **实修回执（2026-11-14，goal-liveinfra R1 清退轮）**：**R1 已消解**——蔡工交互拍板 R1 修法择「清退 diag 孤儿栈」（而非 compose 改名/分网）＋时点「立即开工」；因 本机 diag 部署源树 `D:/test/fde-wt-deploy-diag` 已被删、diag 栈 4 容器成孤儿（api 卡 `created` 因外部端口 8010 被主栈占用，仅 worker/scheduler/redis running），实修＝`docker stop`＋`docker rm` 全 4 个 diag 容器（本机孤儿 diag 容器零残留；远端 diag.fde18.com 公网部署不在本次处置范围；diag redis volume 保留 dangling 不越界）。清退后活体验证全绿：`redis` alias 唯一解析 `172.18.0.4`（`getent hosts redis`×8 全 `.4`，不再 .4/.14 轮询）；`fde:health:worker`＋`fde:health:scheduler` 键回归主栈 redis；worker `fail` 1→0 恢复 healthy；主栈 4 容器全 healthy、ID 不变（**主栈零 recreate**）。**主栈 compose 与 `FDE_REDIS_URL` 零改动**——R1 择 A「本栈改名」方案因 diag 已清退而不再需要。
5. **容器 healthcheck 探针 FAIL 不置非零退出码**：`python -m fde_api.health.heartbeat scheduler` 在键缺失时输出 `FAIL ...` 但 `exit=0`（2026-11-14 实测），⇒ healthcheck「healthy」对心跳缺失无判别力（#72 族）。修复（探针按 check 结果置 exit code）＝服务端生产代码改动 ⇒ 待单独立项，不混入收口 PR。
   **拍板回写（2026-11-14）**：与 #4 合并单独立项一次修两项（同上任务书 R2）；修复前 live「healthy」对心跳缺失无判别力的现状如实维持，靠人工观测兜底。
   **实修回执（2026-11-14，goal-liveinfra R1 清退轮）**：**R2 现镜像不成立，无需修复**——重测活体真身（`D:/test/fde-wt-crv2` 构建产物，crv2 源码与镜像逐字一致）`server/src/fde_api/health/heartbeat.py:97 return 0 if healthy else 1`＋`:102 raise SystemExit(main())`，`docker exec fde-workbench-worker-1 python -m fde_api.health.heartbeat worker` 现测 **exit=0**（心跳键新鲜）；强制 absent-key（指向 `172.18.0.4` 已删 key 场景）复测 **exit=1**。本条早期收口终扫「FAIL 却 exit=0」的观测未能复现，疑似 shell 引号或退出码捕获问题，具体成因未证实；现镜像探针 FAIL 语义已正确置非零 exit code，healthcheck「healthy」对心跳缺失具判别力，本条撤销，无生产代码改动。
