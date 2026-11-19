# R1b：部署协调协议与验收规格

日期：2026-11-19。状态：隔离实现范围已定；真实部署接线未授权、未验证。本规格不改变现行部署命令，以 README 为准。

## 1. 入口与覆盖范围

| 入口 | 实测或源码锚点 | R1b 处置 |
|---|---|---|
| 手工部署、换树重建 | README「路线 A」「后端运维」；AGENTS 接管及三验；`compose.yaml` 的 `api/worker/scheduler` 和迁移挂载 | 首个拟接入计划＝常规更新；接线前仍按原流程人工串行 |
| 数据恢复、首次初始化、独立迁移、sandbox profile | README「换机迁移清单」及初始化；`compose.yaml` 的 `fde-sandbox-runner:latest` | 都是显式旁路，不塞进通用 `execute`。常规更新期间须由操作人排除；恢复演练归 R1c |
| 脚本提示 | `scripts/agents/start-run.py`、`set-credential.py`、`scripts/verify/verify_order_to_delivery_e2e.py` | 只打印命令，不执行部署；接线时改成指向 README，不在各脚本再造入口 |
| CI | `.github/workflows/ci.yml` 的 Alembic 用于隔离测试库；`scripts/check-secret-scan.sh` 的扫描容器非部署 | 不纳入生产协调 |
| Windows 定时任务 | 2026-11-19 只读盘点：`FDE-Bridge-Poll`（wscript）及 `FDE-Pipeline-Backup`、`FDE-Workbench-Backup`（bash）；均 Ready。未读启动参数，未运行 | Bridge 已有只读边界；两备份任务的目标、并发与一致性窗口仍待运维确认；不得以本表宣称没有其他写入口 |
| 历史文档、WSL 手工命令、异机与外部调度 | 仓内 grep 到历史用法，不等于现役入口；未查其它宿主 | 明确旁路，不能宣称已消除任何未接入入口的竞争 |

## 2. 冲突域与可信边界

- **首版按同一 Windows 宿主共用一个占用槽，串行一切受管部署**。不以工作树、context 名称、daemon 或 Compose 项目名给请求分桶：同一 daemon 不同项目可能共享 `fde-sandbox-runner:latest`；不同 daemon 也可能连接同一外部 PostgreSQL。先取安全的粗粒度，再由资源隔离证据决定能否放开。
- 生产接线只支持预登记的一个部署目标；目标指纹用于核对和审计，不是锁键。登记必须明确 Docker 目标的稳定身份、固定端点、Compose 项目、数据库/存储归属（在协调记录里只写非秘密目标指纹）。各步骤必须绑定同一目标；无法固定/复核端点或身份变化即拒绝执行，不按当前 context 默默换目标。
- 正式入口由所有 Windows/WSL 调用方转入同一个 Windows 宿主协调目录；不得从 checkout、当前目录、`TEMP`、用户传参或 Docker context 推导。R1b-3 须验证本地磁盘、同一目录、非重解析点、操作账户写权限一致。R1b-2 只用临时目录注入，**不设生产目录、不连 Docker**。
- 这是协作式协调，不是授权系统。不防可写目录的恶意管理员，不覆盖异机、手工 Compose/SQL、宿主重启后的状态丢失或磁盘故障。R1b-3 未证明重启后留存和重新核验前，重启后禁止无人值守恢复；若部署面存在跨宿主写入且没有可证明的独占写入口，不启用生产接线。

## 3. R1b-2 冻结协议

**文件布局**：测试注入可信、已存在的协调根；共用固定子目录 `active/`，其下唯一正式记录 `state.json`。原子 `mkdir(active)` 成功才获得资格；已存在即排他，哪怕为空、状态读不出、已过期或 PID 不在。状态采用同目录独占临时文件＋`os.replace`，禁止覆盖恢复成空闲。读到完整空槽或不符合文件/目录形状的状态，一律按未知占用处理。

**词汇与状态**：`idle` 只用于查询没有占用标记；`reserved` → `running` → `completed`，其他终态 `precondition_failed`、`execution_failed`、`verification_failed`、`unknown` 均保留占用。白名单步骤为 `preflight`、`apply`、`verify`。先落 `reserved`；前置判定成功后先落 `running/apply` 再调用写动作；明确成功返回才进入 `running/verify`。中断、超时、外部状态不明＝`unknown`；进程被硬杀来不及更新时看到的 `running` 只代表最后记录，绝不能当作健康或已停止。不按 TTL 或 PID 清锁，不自动重试。

**记录**：schema 版本、随机请求 ID、目标指纹、项目名、候选 Git SHA、步骤、状态、PID（仅诊断）、UTC 时间和固定原因码；严格枚举/长度/形状，异常文本、任意命令、完整环境、凭据和客户资料均不落盘。坏记录不回显原文；更新前核对上一条记录，换主则拒绝覆盖。回调 `SystemExit` 归入 `unknown`。

**状态 I/O**：协调根内 `state.guard` 是长期不移动的短时进程锁，查询、发布和释放由它串行；写者最多等 3 秒，查询争用返回 `unknown`。它不跨部署步骤持有，进程退出释放的只是文件锁，不是 `active/`。Windows 原生和 WSL 分开实测，两种文件锁不混用；正式 WSL 调用必须转发至原生入口。

**释放**：同一次执行的前置、写步骤、结果核验均成功，且 `completed` 记录写入成功后，只有持有者可释放；校对请求 ID，移除自己的记录后以非递归 `rmdir` 移除空占用目录，不清理陌生文件。释放中崩溃留下空槽时仍阻塞；释放失败不报执行完成。生产故障人工解除不在 R1b-2，不提供 `force`、reconcile 写面或删除命令；重新部署/回退不是清锁手段，也不会自动降库。

**接口与改动白名单**：下一实现轮只新增 `scripts/deploy/deployment_coordinator.py`、`tests/deploy/test_deployment_coordinator.py` 并更新本规格/进度；如现有 CI 通配能收集，不改 CI。协调核心提供 `inspect(root)` 和 `run(root, target, candidate, plan)`；`plan` 是实施者或测试明确构造的 `preflight/apply/verify` 内部调用接口，不暴露给 CLI 注入命令或生产环境变量。允许只读 `inspect`；不提供正式部署 CLI。现有业务代码、Compose、部署配置、迁移与真实 Docker 零改动。

## 4. 反例与验收

- 真实独立进程＋同一临时根＋不同 cwd 竞争：用同步标记确认获得者已进写步骤，再启动第二请求；只出现一次写动作，不用 sleep 猜时序。项目、别名甚至 daemon 标识不同也必须串行；区分「项目相同」与「占用槽相同」。
- 硬终止协调进程而隔离子进程仍工作：读面不改槽，下一请求拒绝；用进程间信号证明子进程活着后再终止，测试不得遗留后台进程。状态里的陈旧时间、虚假/复用 PID 均不触发回收。
- 预检失败、首次写状态失败或空/坏占用槽：零 `apply`；写步骤、验证失败或中断均不释放。成功写入 `completed` 后验证释放，下一独立请求可正常进入；释放失败仍可见待处置占用。
- 校验损坏记录和状态写入错误不泄漏输入，状态或路径不可读写不默认为空闲；Windows 或 WSL 任一未实跑都要逐平台注明，不能用 Linux CI 绿替代 Windows 文件语义证据。
- 变异检查至少证明两条：把「空槽算占用」或「验证失败保留占用」反转，各自至少一条测试变红且还原后复绿。

验收：`python -B -m unittest discover -s tests/deploy -p test_deployment_coordinator.py -v`；实测见 [PROGRESS.md](PROGRESS.md)。隔离验证不触共享 Docker、数据库、邮件或公网。

## 5. 生产接线止损（R1b-3）

若无法做到所有受管入口汇入同一固定目录、固定 Docker 目标、排除外部写口并核清定时备份，则仅保留 R1b-2 隔离证据，不对外宣称部署已受保护。接线前另列固定计划与实际命令、需要的运行权限、故障处置及人工解锁证据；锁内仍须串联候选核验、接管检查、备份、迁移、活体三验（路由数、迁移头、镜像 ID）与 readiness。任何前置/结果证据没取得，不用一条 ready 200 代替。
