# goal-launchclose · BLOCKED（待裁决清单）

> 任务书规矩：拿不准的写这里，跳过继续做别的，随交付提交。空的写「无」。

## 待外部输入（非阻塞，任务书预期时点内）

1. **~~R3 远端只读现测回执未到~~ ✅ 已收口（2026-11-17）**：蔡工拍板授权 AI 走只读 SSH 通道（任务书自留出口），AI 亲手执行四类零写面只读命令（`docker ps`／`docker images`／容器内 `alembic current`／env 五键 grep，`root@141.95.33.198` 经 `ovh_deploy_key` 密钥认证，零写面零密钥回执）。四段回执原文已贴对话并登记 PROGRESS；对照表 10/10 格回填完毕；**漂移判定＝4a/4b/4e 全部关闭态，零漂移，不重开升版拍板**。远端写操作=0。无遗留待办。

2. **~~R4 N1 关窗执行动作时点锁 2026-11-19~~ ✅ 已执行收口（2026-11-20 补执行）**：automation-48ce31bb 触发日 `lifecycleStatus=failed`/`runCount=0`（机制失效，无副作用）；时点锁拍板「到期当日**或之后**执行」仍有效，AI 于 2026-11-20 按备料序列亲手补执行——活体实态侦查（并发训练场线已接管活体，migrations 挂载源＝`fde-wt-rubricv2-deploy`）→ 最小侵入路径（该树 `.env` 置 0＋同树 recreate api＋主树 `.env` 同步置 0）→ 八步复验全绿（容器 env=0／alembic `f0a1b2c3d4e5 (head)` 不变／ready-live 200／test_host_poll 37 passed／qiflow-* 零 recreate）。逐项回执见 PROGRESS §R4 执行回执。**无遗留待办——本清单全部销项，goal-launchclose 线收口完毕。**

## 顺手活登记（不做，防越界）

- 无。本轮未发现值得登记的顺手活诱惑面（CHANGELOG/台账/AGENTS 均为任务书 R5 点名件）。

## 过程事故（如实留痕）

- 2026-11-17 查本机测试库连接参数时，psycopg 报错信息带出了 `FDE_DATABASE_URL` 全文（含本机开发库口令）进对话一次——本机开发库凭据（非远端、非生产），后续命令已改为 URL 零打印构造；该口令未写入任何文件/argv/交付物。登记留痕可推翻。
- 2026-11-20 R4 补执行构造测试库 URL 时同族事故第二次：psycopg `conninfo_to_dict` 对 `postgresql+psycopg://` dialect 形式 parse 失败，报错信息再次带出 `FDE_DATABASE_URL` 全文（含口令）进对话一次——根因＝SQLAlchemy dialect 形式须先剥成 `postgresql://` 再交 psycopg 解析（教训复利：**parse 失败路径同样泄露**，不止 traceback 位置）；该口令未写入任何文件/argv/交付物，修正后命令零打印跑通。登记留痕可推翻。
