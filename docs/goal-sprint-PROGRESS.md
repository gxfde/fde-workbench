# goal-sprint PROGRESS

> 线：goal-sprint 上线冲刺（任务书＝`docs/goal-sprint-上线冲刺-任务书.md` v2）｜启动：2026-11-13（蔡工拍板「现在启动」）
> 断会话续接：读本文件接着做，别重做；每做完一项立刻更新。

## 开工回执（2026-11-13）

- **理解的目标**：把「对外受控试用就绪」剩余四闸（P2′ 实装／N1 试点闭环／D7 阈值／T-14b 收尾）串成 8 轮止损的有闸冲刺线；让步顺序＝**闸不代拍 > 窗口不失期 > 推得快**。
- **轮次顺序**：r1 N1 试点支持（进行中）→ r2 P2′ 服务端咬合面 → r3 端到端真机验收 → r4 D7 复审报告 → r5 T-14b 收尾 → r6 E8（条件轮，开工闸＝蔡工显式令）→ 收口终扫。
- **最大风险**：① N1 窗口 2026-11-19 截止，首个 run 迟迟不发起则 r1 空转（缓解：PROGRESS 明示发起入口，r2 起不空等）；② 与 goal-crv 并发的 PR 插队（缓解：隔离 worktree `D:/test/fde-wt-sprint`＋每轮开工 `git fetch fork` 对齐）；③ r2/r3 真机面依赖宿主环境（边界＝N2 已签核检查单两表 PASS 语义）。
- **拍板留痕**：蔡工 2026-11-13 选「现在启动」⇒ 任务书 v2 落「并行条款＋crv 吸收条款」，替代原「与 crv 串行、本线先行」默认。

## 任务 0 基线（2026-11-13 现测，每条带命令）

| 项 | 值 | 测法 |
|---|---|---|
| 基点 | fork/main `35ffbea`（#410 squash，2026-11-13 合并） | `git fetch fork && git rev-parse fork/main` |
| 在途 PR | **0** | `gh pr list --state open` |
| 施工树 | `D:/test/fde-wt-sprint`（分支 `goal-sprint-r1`，从基点建） | `git worktree add -b goal-sprint-r1 … fork/main` |
| pytest CI 基线 | **3473 passed + 8 skipped**（12m28s） | main run **43281011099**（#410 合并轮，四 job 绿）。本地不重跑全量的理由：docs 轮零代码增量＋并发会话共享 PG 对撞家族风险；CI 实测为权威口径 |
| mypy | **OK：baseline 277 occurrences / 102 distinct**（现测） | `server/.venv/Scripts/python.exe scripts/check-python-types.py`——★较 AGENTS 口径 279/104 漂移 −2，登记待收口轮核对（P3 文档漂移，本线不修） |
| typecheck | 绿（node+web 双 tsconfig 零错误） | `npm run typecheck` |
| 活库身份 | `fde_workbench` @ alembic **`b5d9e2f4a7c1`** ＝代码 head 逐位一致；PG 容器 `qiflow-twenty-db`（与 `verify-run-evidence.sql` 头注配方同源） | `psql -c "SELECT version_num FROM alembic_version;"` |
| T-14b 前置 | `diag.fde18.com` DNS 未配置（Non-existent domain） | `nslookup`（本会话 2026-11-13） |
| crv 吸收面 | **零域章**：goal-crv 总报告未出生；`docs/audit/全面代码审查报告-2026-11-10.md` 属 goal-review-fix 线（CR- 前缀，QR 计 0），非 crv 吸收对象 | `ls docs/audit/全面代码审查报告*` + `grep -c "QR-"` |
| 本地跑测配方 | venv 忽略 PYTHONPATH（教训⑭家族）：真路径 exe＋`sys.path.insert(0,'server/src')`＋`os.chdir(server)` | 本轮 r1 自测实证（三次试错定型） |

## r1 · N1 试点执行支持（进行中，窗口 2026-11-12~11-19）

### Agent 侧完成项（2026-11-13）

1. **四口径 SQL 采集实跑**（`scripts/verify/verify-run-evidence.sql`，只读 `BEGIN READ ONLY…ROLLBACK`，全四段合法执行）：
   - ★**证据闸翻转发现**：`approval_rows=2`（reviewed=2）——SQL 头注「活库当前 automation_approvals=0」已过时；`evidence_gate=HAS_RUN_EVIDENCE`。2 行均为 **2026-11-08 somwyn E2E 试点产物**（risk_level=4／workbench.write／workflow.human_approval，均 approved、否决率 0.0000、审批时效 p50=85.5s／p90=104.3s）。**含义**：D7「approval_rows=0 禁预支」的数据前提已松动——r4 复审报告有了极小样本数据源（n=2，且是 human_approval 语义、非 N1 zcode run 语义）；**阈值 N 仍归蔡工拍，本线不预支数值**。
   - **C 口径现出 2 行「执行落空」**（approved 超 1h 无 executed_at；id `df31cb16…`／`b789a318…`，均 11-08）——疑为 `workflow.human_approval` 能力下「审批即终点、无执行腿」的口径语义错配而非真脱节；**r4 报告轮须裁决该口径**（与 B 词表 `executed` 单列同源），登记不结论。
   - D 口径：确认失败锁事件 **0 行**。
2. **N1 窗口状态**：`agent_runs WHERE created_at>='2026-11-12'` ＝ **0**（历史总 12，均 somwyn 试点期）⇒ 蔡工尚未发起首个 run，符合「首个 run 亲手执行（H4）」待办。**发起入口（待蔡工）**：桌面端 AgentsConsole 发起 pilot-001 编码 run（N3 五问已拍：A 轨封闭集＝仅 pilot-001；产出物＝run 产物目录代码/diff/文档＋`--json` 汇总；确认人＝蔡工）。
3. **契约失败语义自测**：`server/tests/test_zcode_contract.py` **14 passed**（7.13s；含 `--json` 汇总形状／故障态明确失败码／版本钉 0.17.1／降级语义）。
4. **产物复核链路**：端点面由 N3c 已交付（artifacts content 读取面＋AgentsConsole 终审队列），r1 零新增代码；蔡工发起 run 后按既有复核流走，届时补 run 证据 sha256 登记。

### r1 待办（收口条件）

- [x] 蔡工发起首个 run（窗口 11-19 止）→ 2026-11-13/14 活库核实 `FDE-20261112-5CFF4FA2`（`pilot-001` 承载项目）已完跑 2 条生产 `host_poll` `agent_runs`（run-001 `b647945e…` 3/3＋run-002 `347fb585…` 5/5 **共 8/8 产物全部人工复核**＋#435 逐字节 sha256 自证 200）→ **窗口内闭环已兑现**（详记下方「r1 证据登记」与 r4 复审报告 §3.3）
- [ ] ~~或窗口关闭未跑成 → 如实登记「部分完成」转 r2~~（不适用：已在窗口内跑成）

### r1 证据登记（2026-11-14，AI 双侧现测后落账）

**run 面（项目 pilot-001 `7e931c55-42e7-4320-be7a-4a35f8ab3bb9` · 发起人 admin＝H4 亲手执行成立 · 售前智能体 `4410538c-17a1-499d-817e-cb8060a90795`／能力 `agent.module.presales`）**：

**run-001** `b647945e-4b6e-4010-a8da-e4913fe7430b`（idempotency `pilot-001-hostpoll-run-001` · 北京时 11-13 11:46 · completed/exit 0/无降级 · host_poll claim+receipt 齐 · 185s）：
- `output/manifest.json` sha256 `337df4624229273e1ea0abf4a4730e5f7ef052150275fba0cfc16801beb338ad`
- `output/presales-proposal-draft.md` sha256 `27019a85905f292d8e3f7bd364be2732689ef319db373aba2ecdf390f98eaedc`
- `output/requirement-clarification.md` sha256 `77d82fda1fcd7d936f2bc8257a23b3adf810a1930077186bffc2bc04437f5c30`
- 产物复核 **3/3**（reviewed_by=admin，2026-11-13 13:59）

**run-002** `347fb585-29d6-4bf8-a6e5-789bf80cfc9a`（idempotency `pilot-001-hostpoll-run-002` · 北京时 11-13 16:40 · completed/exit 0/无降级 · host_poll claim+receipt 齐 · 256s）：
- `output/presales-brief.md` sha256 `9fba8b489085bfa7898b12331fd2c2eb6523279f6b9c317f0af829f742efc118`
- `output/assumptions-and-gaps.md` sha256 `dc3f01ac83dc9c390d233ca947cd8ca159284d96858fd033f2d4453588347071`
- `output/solution-directions.md` sha256 `5cb5b17b2e3cc7d4725a6eea33dfe7d34d2aeb0f222e155f500bf731dfe54bc3`
- `output/delivery-plan.md` sha256 `38e6ae86428c6a96f1610d793ddb75fd781eda588f14aad66643d8833504f1b9`
- `output/discovery-questionnaire.md` sha256 `8f97c60a3b1361665a9f157992581a462e91852aa85a368fe07303e958cc8492`
- 产物复核 **5/5**（reviewed_by=admin，2026-11-14 00:14）

**核验方式**：磁盘原件（`D:/test/agent-workspaces/platform/<RUN_ID>/output/`）逐文件 `sha256sum` 与 `agent_artifacts.sha256` 库内指纹逐字一致（2026-11-13/14 两次现测）；原件已存仓库参考样板 `docs/售前产物参考/run-002-20261113/`（README 含 run-002 全量指纹）。

**证据闸快照**（verify-run-evidence.sql，2026-11-13 现测）：approval_rows=2 / reviewed=2 → **HAS_RUN_EVIDENCE**；审批时效 p50=85.5s / p90=104.3s、人工否决率 0.0000；C 口径 2 条 11-08 落空行待 r4 裁决；D 口径确认失败锁 0 行。→ r4 D7 复审轮数据前提达成。

### r1 变更面

- 本 PR：任务书 v2 落库＋本 PROGRESS＋CHANGELOG 节。**零生产代码零迁移零路由**（判定：`git diff <基点>..HEAD --stat -- server/src desktop/src server/migrations server/seeds` 应为空）。

### r2 开工前检查单（吸收条款执行记录位）

- [ ] `git fetch fork` 对齐＋查在途 PR
- [ ] 扫 goal-crv 已出域章 QR 台账（现测：零域章，2026-11-13）
- [ ] 建 `D:/test/fde-wt-sprint` 内新分支 `goal-sprint-r2`（从当时 fork/main）
- [ ] ★核对并发线 `feat/e8-fallback-e11-credentials`（E8/E11 落地线，2026-11-13 现测已在主树检出、基点 `35ffbea`）——若 E8 已实施合并：r6「条件轮」降级为「验收＋收口轮」，吸收条款照扫其改动面；两线同碰 `agents/` 域时按插队纪律处置

### r1 收口回执（2026-11-13）

- PR **#411** squash 合并 `5a3f276`；CI 四 job 全绿（权威 run **43291551524**：server-tests 12m20s／desktop 2m26s／pseudonymization 58s／secrets-scan 9s）。
- main 追平 fork/main＝`5a3f276`（主树被并发线检出 feat 分支 ⇒ 用 `git fetch fork main:main` 只推 ref 不动检出——共享树 HEAD 争用面新配方）；`goal-sprint-r1` 分支本地（树 diff 空＝squash 零漂移证明）＋远端均已删；sprint worktree 现 detached @ `5a3f276` 待 r2。
- r1 遗留：蔡工发起首个 run（窗口 11-19 止）后补证据 sha256 登记；未发起则窗口关闭如实登记转 r2。
  - ✅ **遗留清偿（2026-11-14）**：run ×2 窗口内完成 + 8/8 产物人工复核 + sha256 双侧现测一致 → 见「r1 证据登记」。**r1 全部收口，无遗留。**

## r2 · P2′ 服务端咬合面收口（2026-11-13，生产代码轮）

### 开工前检查单（吸收条款执行记录）

- [x] `git fetch fork` 对齐：基点 **`86722e6`**（#417 crv r5 合并轮）；在途 PR 仅 #6/#7（quickflying 10 月旧件，非活跃轮，不阻塞）。
- [x] 扫 goal-crv QR 台账（**已出 5 域章 98 行**，`docs/audit/全面代码审查报告-2026-11-13.md`）——与本轮改动面（agents 领取/回执/状态机）相交：**QR-073（P1）必吸**＋同函数 P2 两连 **QR-088/089 吸收**；QR-090（容器面 receipt ask）/086/087（retry）/091/092/094/095（spawn 段＝r3 面）**相邻不吸收**，照常走 QR→修复批轮。
- [x] ★核对并发线 `feat/e8-fallback-e11-credentials`：**已合并＝#414**（E8 只读降级层＋E11 凭据管理面，`8cbb21b`）⇒ **r6「条件轮」降级为「验收＋收口轮」**（吸收条款照扫其改动面）；本轮已核其改动（agents/credentials.py＋control/automation_*）与 P2′ 咬合面无交集冲突。
- [x] 建 `D:/test/fde-wt-sprint` 分支 `goal-sprint-r2`（从 `86722e6`）。

### 范围现测校正（重要）

P2′① 咬合半**已于 #204/#215（2026-11-08）落地**（迁移 `f6d3a9c1e7b2`：status CHECK＋`host_running`＋`execution_provider`/`host_claimed_at`/`host_token_hash`/`host_receipt_at`/`host_lost_at`；三路由 `GET /agents/host/status`／`POST /agents/host/claim`〔FIFO+skip_locked+幂等重领〕／`POST /agents/host/runs/{id}/receipt`；发起侧 202；`mark_host_lost` H4 只标记；config 默认全关）。**r2 不重造**——实际工作面＝crv 吸收＋N2 两事实接线＋§11.3 六约束核对（核对结论：约束①③④⑤⑥既有实现全部在场；②的幂等/鉴权在场但行锁有 QR-088 缺口，本轮补）。

### r2 变更面

- **QR-073（P1，吸收）**：NEW `workspace_files.is_unsafe_artifact_path()` 单一真身（盘符/反斜杠/根锚三形态）替换 `service._finalize`＋`host_receipt` 两处弱判定；且 unsafe 路径**不读文件不进 prepared＋回执面不落 AgentArtifact 行**（原实现只要 digest 形状合法就落行——Windows 裸跑态 `workspace/output/<盘符路径>` 的 Path 连接会替换基座直读宿主任意文件）。
- **QR-088（P2，吸收）**：claim 带 `run_id` 重领路径补 `with_for_update()`（等锁后重读最新状态判 403/幂等；FIFO 面保持 skip_locked）。
- **QR-089（P2，吸收）**：`agent_runs` 加可空 `frozen_tools` JSON 列（**迁移 `c8e2a6f0b9d4`，73→74 单头**）；`start_run` 落发起时刻三重交集快照；领取载荷（含续领分支）读快照，旧行 NULL 回落 registry 读（行为兼容）。
- **N2 两实测事实接线**：NEW `agents/host_preflight.py`（唯一真身，r3 宿主代理复用）——①provider 覆盖开关成对校验；②`defaultModelSelection` 键在场校验。接线点＝`run_host_channel` spawn 前（出站闸之前）；失败→既有 HostChannelError→L2 明确失败映射（零 spawn 零计费，重试由人 H4，不静默重试）。config 新键 `FDE_AGENT_HOST_ZCODE_CLI_CONFIG`。
- 测试：test_host_poll +6 例（参数化展开 10 项：rival 提交重读 403／frozen 快照／旧行回落／五形态路径零行×5／202 受理快照落库）、test_host_channel +5 例（参数化展开 10 项：preflight 正负例＋校验先于出站闸）；既有 host 三件套补 preflight 注入点（临时 CLI 配置＋env 开关清理）。
- **变异五连全红→字节级还原→绿**（M1 去行锁／M2 快照退实时／M3 路径退旧判定／M4 模型键短路／M5 成对短路）。★教训：M1 首版判别力不足——持锁者**未提交**时无锁实现的 UPDATE 同样阻塞在行锁上，测试假绿；改「rival **提交**后等锁重读判 403」形态才杀灭（判别力本身要验收的家族教训再现）。
- 验证：定向 155+ 例绿；ruff 绿；mypy **277/102 基线不变**；inventory 重提取（revision_count 73→74；路由 488/蓝图 52/表 153 不变）；防陈旧闸绿（图纸无迁移数声明，M4 纯迁移轮先例不重生 archify）；全量 pytest（见收口回执）。
- 环境注记：sprint worktree 新建独立 `server/.venv`（xdist worker 全新解释器不带 `-c` 前导 sys.path，主 venv editable 指向主树——每工作树一份环境纪律）。★教训：venv 必须按 CI 配方 `pip install -r requirements.lock -e ".[test,dev]"` 安装——裸 `pip install -e` 拉到 SQLAlchemy 2.1.8/新 pydantic，mypy 基线检查假红 9 条（全在未触碰文件）；且 `scripts/check-python-types.py` **优先用树内 server/.venv**（存在即用），同一命令在树内有/无 venv 时走不同解释器。
- ★CI 首轮红例与修复（run 43337413266 server-tests 1 failed）：`test_agent_execution_grant_wiring.py::test_host_channel_run_records_authorization_fingerprint`——该测试的 `_host_settings` 未带 `agent_host_zcode_cli_config`，CI（无 ~/.zcode/cli/config.json）撞本轮新增 spawn 前置校验 ⇒ run 落 L2 而非 completed。修复＝与 test_host_channel_service 同款注入（`c6a060f`）；全仓 `agent_host_zcode_bin` 构造点闭集复扫＝2 处均已注入。★教训：新增机械闸后，测试面的构造点闭集扫描要按 **settings 键名**（`agent_host_zcode_bin`）而非类名（`HostChannelSettings(`）——前者抓到了后者漏掉的 service 级构造点。

### r2 收口回执（2026-11-13）

- PR **#422** squash 合并 **`3dc07fe`**；PR CI 两轮（首轮 server-tests 1 红＝授权票据测试缺 preflight 注入点，`c6a060f` 修复）⇒ tip run **43340038319** 四 job 全绿（desktop/server-tests/secrets-scan/pseudonymization；另一同 sha run 43340030857 亦四绿）。合并树权威 main run **43342235002** 被并发合并取消（家族行为）⇒ 以 tip run **43343183487**（`979eeed`＝`3dc07fe`＋docs-only #423）为 superset 权威。
- main 追平：`git fetch fork main:main`（并发线 #418/#420/#421/#423 四 PR 插队窗口内落地）；`goal-sprint-r2` 远端已删、本地分支在 r3 分支建后删除；合并树 CHANGELOG 结构终扫零丢失（我方 r2 节＋节体逐字在场；插队方本就无 CHANGELOG 节）。
- 活体部署三验全绿（从本树 `-p fde-workbench` 接管）：**alembic 真实升级 `b5d9e2f4a7c1 → c8e2a6f0b9d4 (head)`**（frozen_tools 列上活库）／url_map **488** non-static ＝ 口径／三镜像逐位一致 api `33eff9e990a7`／worker `36c3e692e176`／scheduler `b949caac6a02`／ready 200。★部署配方坑：worktree 部署必须 `docker compose -p fde-workbench build/up`（不带 `-p` 落目录名项目，撞活体 8010 端口Bind 失败＋镜像 tag 错项目——首次 up 失败即发现，`-p fde-wt-sprint down` 清场后正名重build 接管）。
- 本地全量 pytest（lock 对齐前 sqlalchemy 2.1.8 环境）：3530 收集＝3527 passed＋8 skipped 内含 3 迁移口径钉红（`HEAD_REVISION` 常量＋`known==73` 双钉漏同步，当场修复复绿——新增迁移必同步两处口径钉入教训）＋1 zcode teardown 环境 ERROR（复跑绿）；CI 锁定环境为权威。mypy **277/102 基线不变**（lock 对齐 venv 复核；裸装 2.1.8 时假红 9 条已甄别为环境漂移）。
- r2 遗留移交 r3：宿主代理进程本体（轮询循环→spawn zcode→回执）；`adapter_missing` 解除回执落台账 §12（①实装＋N2 签核两项已齐，待 r3 真机验收）；crv 台账已 134 行（#423 r8 出 P1×2 迁移存储域）——r3 开工吸收扫描按新台账重扫。

## r3 · 端到端真机验收（2026-11-13，宿主代理进程本体轮）

### 开工前检查单（吸收条款执行记录）

- [x] `git fetch fork` 对齐：开工基点 **`876f7cc`**（#426）；r2 收口回执 `7fc37ff` 随分支首提交入库。★fork/main 在本轮窗口内又进 4 提交（#429 crv 收口/#427 crv r10/#430 首个 run 发起/#431 crv fixup/#428 回填）⇒ 收口前 rebase。
- [x] QR 台账重扫（147 行终态，#427 r10 闭合）：与本轮 agents 改动面**零新增相交**（QR-117/118＝富文本键名/上传 IntegrityError，前端域）；r2 扫描时挂给 r3 的 **QR-092/094/095 本轮吸收**（spawn/env 族），QR-086/087/090/091 相邻不吸收照走 QR→修复批轮。
- [x] ★并发线核对：#430「一键发起 agent run＋工作区根修复（首个 run 真机落库）」＝`scripts/agents/start-run.py` **人直调**既有 API（AI 不代发起红线合规——发起动作归人）、run `0ef28514` queued 落库、零生产代码改动。r3 不碰其面；N1 链的宿主消费半正是本轮宿主代理本体（生产 run 的自然领取在部署后，工程验收不碰生产 run）。
- [x] 分支 `goal-sprint-r3`（从 `876f7cc`＋r2 回执提交）。

### 范围定稿（五项，2026-11-13）

① **providerId 真机事实吸收**：2026-11-13 实测 zcode 0.17.1 schema strict——`defaultModelSelection={providerId,modelId}`，写 `providerKey` 被**整键丢弃**静默回退内置默认；r2 校验器查 providerKey 会对合法配置误拒 ⇒ 校验换 providerId（`host_preflight.py` docstring 带实测更正框）；`v3-backlog.md` N2 事实行的 providerKey 表述归并发线（a95af5a 族）修，r3 不碰避免冲突。② **宿主代理进程本体** NEW `agents/host_agent.py`＋**服务端 context 读取面** NEW 路由。③ **adapter.py spawn 段整体重划**（`adapter.py:93` 定向警示清偿，不得只换 argv）＋QR-094。④ QR-092/095 吸收。⑤ **真机验收＝工程级**（不创建生产 AgentRun＝H4 边界不碰；N1 首个生产 run 仍归蔡工亲手，窗口 11-19 止）。

### r3 变更面

- **宿主代理本体** NEW `server/src/fde_api/agents/host_agent.py`：`HostAgentConfig.from_env`（五必需 env 键＋闸开白名单空 fail-closed）／`HttpHostTransport`（协议：200 拆 `{data}` 信封／非 200 回完整信封读 error 码）／`preflight`（复用 host_preflight 同一对校验器，**fail-fast 于 claim 前**——部署半态不领取，避免 run 白挂 host_running）／`materialize_workspace`（run_id 形状钉＋根锚＋拒绝清单；空 task.md 不 spawn）／`build_receipt_payload`（产物 sha256 宿主侧现算＋`egress_audit` 有界摘要上行）／`run_once`（一次生命周期；spawn 失败如实回执 failed 不悬挂）／`main`（env 驱动，退出码 0/2/3/4/5）。生命周期红线（通道例外⑤）：**一次进程＝至多一次 claim→执行→receipt，run 终态即回收**；零凭据注入；spawn 真身＝`run_host_channel`（preflight＋契约 argv＋超时熔断＋⑦闸全复用）；真相层零接触。
- **服务端 context 读取面**：NEW `agents/host_context.py`（状态闸族：404 不存在／409 非 host_poll·未领取·已回执／403 令牌与领取不符／413 超 4MB；context_ref 前缀剥除重新 join 当前 Settings 根＋根锚校验；三面料逐字回传）＋第四条宿主路由 `GET /agents/host/runs/<run_id>/context`（**488→489**；独立路由非 claim 内联＝可幂等重取＋有界语义）。面料设计定稿：**服务端渲染一次、宿主逐字落盘**（不两侧各渲染——漂移温床）。
- **adapter.py spawn 段整体重划**：删虚构容器契约与 TODO 警示；`spawn_argv`＝契约层 `zc.build_cli_argv(prompt=zc.task_prompt(workspace), cwd=…)`（prompt 文字面并入契约层单一真身）；`ZcodeAdapter(*, cli_command="zcode")`；`AgentRunResult.summary_payload` 字段（`--json` 汇总随 result 回传回执保真）；QR-094 done 终态立即终止批内遍历（completed 不得被同批尾随越界 cost 翻成 budget_exceeded 丢产物）；`ManifestOutputScanner` 自 service 机械搬入（`_MANIFEST_FILE` 收归 workspace_files 单一真身，service 顶部再导出引用不变；热点预算只减不增）。
- **QR-092（宿主进程 env 白名单继承）**：`host_channel_env` 白名单前缀集（node 运行时＋Windows 定位＋`ZCODE_` provider 注入面＋代理透传）＋拒绝清单双层（`FDE_`/TOKEN/PASSWORD/SECRET/API_KEY/PRIVATE_KEY 子串即使命中允许前缀也剔除）。
- **QR-095（回执 exit_code 语义）**：缺/非 int ⇒ None（**不缺省 0**）；`status=completed` 而 exit≠0 ⇒ 降档 failed——服务端不认无凭据的「成功」。
- **pilot.py 警示换代**（真身清偿）：「执行契约已实装（宿主代理通道 goal-sprint r3），但试点窗口内尚无真实完成的 run」——文本与实装态一致。
- **★真机首跑撞出生产缺陷→⑦闸回环豁免**（`host_egress_proxy.py`）：首跑 EXIT=1、产物零。隔离两腿定位：裸跑腿全过（marker 产物＋manifest 双件）／闸腿复现（`APICallError: Cannot connect to API`＋审计 `tunnel_blocked 127.0.0.1:18787`）。真相＝zcode 运行时经**桌面端本地 broker（127.0.0.1:18787）**回环 IPC 取凭据/会话，其客户端**无视 NO_PROXY** 把回环 CONNECT 推进代理，闸按白名单拦截 ⇒ broker 不可达 ⇒ API 调用取消。修复＝**闸侧回环豁免**：回环目标 CONNECT 一律转发、审计新类别 `tunnel_loopback`（`proxy_env` 的 NO_PROXY 本就声明回环直连语义，zcode 不认账由闸侧补齐；⑦ 管出站互联网面，回环不出机器）；明文 absolute-form 仍一律拒绝（未观测到回环明文面，不预设放宽）。测试钉两例（部署态白名单不含 127.0.0.1 下回环中继＋localhost 别名；blocked 原钉保持）。★部署事实：本机形态 zcode CLI 依赖桌面端在场（broker 18787）——裸跑形态的前提归部署 runbook 详述（并发线 runbook 承载）。
- **回执携 ⑦ 审计证据**：`build_receipt_payload` 增 `egress_audit`（`summarize_audit` 有界形状：计数＋去重域名 ≤20，只记域名不记路径/内容——红线同构）；宿主代理单发进程里这是审计留证唯一出口（服务端 `agent_egress_audit` 事件落库择机接线）。
- 测试：NEW `test_host_agent.py` 15 例（from_env 闭集/egress 白名单闸/preflight 复用/materialize 逐字＋坏 run_id＋空 task.md fail-closed/全链指纹逐位/零凭据注入/失败回执/receipt 拒/claim 拒/preflight 先于 claim/ghost digest/HTTP 传输形状）＋autouse 清场夹具（本机真实 `ZCODE_PERSONAL_PROVIDER_CONFIG_FILE` 泄入防护——r2 教训复现）；test_host_poll +7（QR-095 两例＋context 五例含**令牌轮换领取绑定钉**＋HTTP 路由接线）；test_host_channel +3（env 白名单三层）；test_agents_adapter pin 换代＋QR-094 一例；test_host_egress_proxy 回环豁免换代。★M8 完整性钉吸收（全量复跑撞出）：新 GET context 面未登记 ⇒ `_EXCLUSION_RECORDS` 增 `internal_service` 条目（宿主机器通道令牌闸面、JWT 不进鉴权：A/同角色 A/B 属主现测 403×3，claim/receipt 同族；条数基线 64→65）——M8 红队套件 43 passed 复绿。
- NEW `scripts/verify/host_agent_real_machine_check.py`：工程级验收器——进程内 `ThreadingHTTPServer` 存根（status/claim/context/receipt 四咬合面与真实路由形状逐字段同源）＋**真实传输**（HttpHostTransport over loopback HTTP）＋**真实 spawn**（run_host_channel 默认 spawner→真 zcode 非交互）＋**真实 ⑦ 闸**（部署态同款六域白名单）＋TEMP 一次性隔离工作区（绝不触碰真相层）。

### r3 验证与真机验收回执

- **变异五连全数收口**（改→红→字节级还原→绿）：M1 env 拒绝层失效 2 红／M2 QR-094 1 红／M3 缺 exit_code 缺省 2 红／M4 preflight fail-fast 1 红／M5 领取绑定 1 红——★M5 判别力教训再现：单令牌设计下「他 token」在入口校验即 403，领取绑定检查**不可达**＝假绿；改**令牌轮换场景**（claim 后轮换服务端 token，原持有者读 context 必须撞绑定检查 403）才杀灭。★变异脚本三硬化（v3）：try/finally 强制还原（v2 曾 900s 超时崩溃残留生产变异一次——手工核验还原后补）；单趟 240s 超时如实报；**变异运行期间绝不并发编辑源码**。
- 定向套件 **171 passed**（9 文件＝r3 改动面测试文件全量，含回环豁免后复跑）；ruff 绿；mypy **277/102 基线不变**；inventory 重提取（route **488→489**／52 蓝图／153 表／74 rev 单头 `c8e2a6f0b9d4` 不变）＋route CSV＋archify 刷新（candidate.json 489＋finalize 四闸绿＋**整页实拍 preview 1440×2098**）。
- **★真机验收 VERIFY-R3 RESULT: PASS（判据六条全过）**：①一次生命周期收场回执 `status=completed`；②产物指纹字节级一致（receipt=`a34bc4d89fa48c40…`）；③真模型消耗 billable **195,582 tokens**（6 模型请求，GLM-5.3-Flash，zcode 0.17.1）；④context 咬合面被消费；⑤egress 审计全白名单域＋回环、**零 blocked**；⑥产物 marker（R3-VERIFY-OK）＋manifest 双件可校验。**工程级**：不创建生产 AgentRun（H4 不碰）；首个生产 run 的宿主消费在部署后自然发生（N1 链，#430 已 queued 落库）。
- ★环境窗口注记：本轮两次测试/变异超时窗口（M1/M2 v3 240s×2＋adapter 套件一次 39 ERROR setup 全红 454s）疑与并发会话共享 PG 对撞同族；单例复跑全绿（39 passed 15.7s／M1/M2 补验 3.9s＋4.7s）——环境假象如实登记，**CI 为权威**。
- **CI 首红清偿（2026-11-13）**：PR #433 首轮 server-tests 红＝`6 failed, 3588 passed, 8 skipped`（全集中 `tests/test_host_agent.py` 的 run_once 六例，错误原文＝`HostChannelError: zcode 默认模型未配置：/home/runner/.zcode/cli/config.json 缺少可用的 defaultModelSelection 键`）——根因＝单测未隔离 preflight 的默认模型配置路径，落 HOME 下 `~/.zcode/cli/config.json`（CI runner 无此文件⇒六例假红；本机真机态又使「缺键」负例不可达＝假绿家族）。**生产行为正确（fail-closed），只修测试隔离**：夹具在 tmp 内写合法 `defaultModelSelection` 配置（先 set、后 `payload.update(overrides)`⇒负例 override 仍生效）＋新增「缺省路径语义」钉（monkeypatch 桩 `default_cli_config_path` 并断言报错含该路径——不打桩则读真实 HOME＝环境依赖＝假绿家族）；CI-like 空 HOME 实测 `test_host_agent.py` 15 passed。★同款纪律已在 `test_host_channel.py` 落地（模块级 `_CLI_CONFIG_PATH` 写 tmp 合法配置）。
- **全量本地实测（首红清偿后重跑）**：`3596 passed + 7 skipped`（3297.63s／0:54:57，exit 0）＋定向 9 文件 `171 passed`（136.05s）。★并发取证：另一会话 `fde-wt-v33m2` 同窗跑 `pytest tests -q`＋`test_migrations.py`（独立库 `fde_workbench_v33m2_test`），主树 pre-commit pytest 抢同一 `fde_workbench_test` session advisory lock（实测 pid 186473 等锁 50min）⇒ 本地耗时不可作性能口径，**CI 为权威**。

### r3 待办（收口条件）

- [x] 台账 §12 `adapter_missing` 解除回执＋§4 P2-b 行收口＋§3 E10 解锁判定落记录
- [x] backlog T-Z1 状态行更新＋CHANGELOG r3 节＋AGENTS bullet
- [x] rebase fork/main（#431/#432 插队窗，已 rebase 至 `a122f28`）→ 全量 pytest（本地 3596 passed + 7 skipped 绿）→ PR **#433** → CI 四绿 → squash 合并 → 部署三验（url_map **489**／alembic `c8e2a6f0b9d4` head 不变／三镜像逐位）→ 收口回执回填（**收口回执见下节**）


### r3 收口回执（2026-11-13，PR #433 合并＋活体部署三验）

- **PR 与合并**：PR **#433**（`goal-sprint-r3`）→ **squash `93658650e74100b7916d373ec26104583cc3f58e`**（mergedAt 2026-11-13T08:29:15Z）＝fork/main 新顶。★**树哈希核对零漂移**：合并树 `0d7e9fb307c12ac4691909e463db96410422ec0a` ≡ 分支树（`git diff --stat` 空）。
- **CI 四绿**：run **43390885851**（head `704772a`）——server-tests ✅（15m52s）／desktop ✅／secrets-scan ✅／pseudonymization ✅。★**旧 SHA 红行残留登记**：run 43390878726（head `1d2119a`）server-tests 1 红＝`tests/test_ai_run_proposal.py::test_workflows_confirm_runs_and_audits_end_to_end` 事件顺序 flake（实测 `ai.api.started` ≠ `ai.api.requested`），r3 diff **不含** `ai/` 域与该测试文件＝跨线观察登记，**不在本轮修**；权威＝head SHA 对应的 run（`gh pr checks` 仍显示旧 SHA 红行时以 head SHA 的 run 为准）。
- **活体部署三验（全绿，从冲刺树 `D:\test\fde-wt-sprint` `docker compose -p fde-workbench build/up`）**：①活体 `url_map`＝**489**（non-static，≡ 本轮口径）；②容器内 `alembic current`＝**`c8e2a6f0b9d4 (head)`**、`alembic heads` 同（迁移头不变，本轮零迁移）；③三镜像 ID 与**本工作树构建产物**逐位一致——api `887c1f46f30f`／worker `e08c0cbaae70`／scheduler `f9356fbc6620`（容器 `.Image` 与 `docker images` 同 tag ID 归一后比对；短/长 ID 与 `sha256:` 前缀形式差异不作不符）。附：三容器 healthy、ready 200、live 200。
- **★部署配置保全与拓扑登记（本轮自查发现并当场还原）**：冲刺树 `server/.env` 相对主树缺 6 键（`FDE_AGENT_HOST_CHANNEL_ENABLED`／`FDE_AGENT_HOST_POLL_ENABLED`／`FDE_AGENT_HOST_POLL_TOKEN`／`FDE_AGENT_HOST_ZCODE_BIN`／`FDE_AGENT_HOST_ZCODE_CJS`／`FDE_AGENT_WORKSPACE_ROOT`）⇒ 先抄入保全（`.env` 被 gitignore 忽略，不进 VCS）。抄入后实测发现**把「宿主裸跑态（路线 B）」取值带进了「容器态（路线 A）」**：容器拿到 Windows 工作区根 `D:/test/agent-workspaces`＋host_poll 开关/令牌；而并发线《宿主代理裸跑部署runbook》明写「路线 A 的工作区在容器内、**host_poll 只能在路线 B 裸跑态使用**」⇒ 已在部署树**还原**（工作区根回 `/app/.fde-storage/agent-workspaces`＋移除 POLL 两键）→ recreate 后 env 逐项对平＝与部署前活体一致（**活体零行为漂移**）。**遗留登记（不裁决）**：容器态与裸跑态共用一份 `.env` 的长期解（compose `environment:` 覆写容器态工作区根，仿既有 `FDE_DATABASE_URL`／`FDE_REDIS_URL` 覆写模式）属并发线宿主通道部署拓扑域。
- **⑦闸留授权**：活体容器 env **无** `FDE_AGENT_HOST_EGRESS_GATE_ENABLED`／`FDE_AGENT_HOST_EGRESS_ALLOWLIST`（主树与冲刺树 `.env` 均无此二键）⇒ 本轮**不代拍重开**（闸不代拍），缺口记此留授权；r3 真机验收的闸腿走的是**部署态同款六域白名单的进程内闸**（工程级，非活体容器 env）。
- **r3 收口条件全部达成**：台账 §12 `adapter_missing` 解除回执＋§4 P2-b 行收口＋§3 **E10 解锁判定成立**（条件触发、不排期）＋backlog T-Z1 全收口＋CHANGELOG r3 节＋AGENTS bullet。
- **下一轮**：r4 D7 复审报告（D7 阈值归蔡工不预支）；N1 首个生产 run 仍待**蔡工亲手**发起（窗口 2026-11-19 止）。

---

## r4 · D7 四口径运行证据复审报告（2026-11-13，只读取证 + 报告与机械钉轮）

### 开工前检查单（吸收条款执行记录）

- `git fetch fork` 对齐 `fork/main` `4b79f5b4`（r3 收口 `e337ee70` 后并发线合入 PR **#435**「产物采纳流闭环＋宿主产物可读」，证实首个真实 `host_poll` 生产 run 已完跑并走通下游复核）；在途 open PR 仅 `#436`（`goal-crv-fix-b`）／`#424`（脚本兼容），与本轮文档及 D7 静态钉零交集。
- `goal-crv` 相邻项扫描：本轮不改生产源码，无新增吸收项。

### 活库只读实测与源码裁决（2026-11-13 09:42:27Z，`BEGIN READ ONLY … ROLLBACK`）

1. **`verify-run-evidence.sql` 实跑结果**：
   - `[0/4]` 数据闸：`approval_rows = 2`、`reviewed_rows = 2`、`evidence_gate = HAS_RUN_EVIDENCE: 交评估复审轮出运行证据报告`。
   - `[1/4] A` 审批时效：`(risk_level=4, capability=workbench.write)` `samples=2`、**`p50_s = 85.5`**、**`p90_s = 104.3`**（单行 `108.957s` / `62.100s`）。
   - `[2/4] B` 人工否决率：`(workbench.write, workflow.human_approval, 4)` `ok=2, rej=0, exp=0, executed_excluded=0`、**`reject_rate = 0.0000`**（`_REAL_RUNS` 演练排除后仍为 2）。
   - `[3/4] C` 执行落空：原始 SQL 命中 2 行（`df31cb16…`、`b789a318…`）⇒ **经源码状态机核实（`control/service.py:776, 791-796, 850-854, 873, 888-889`）正式裁决为跨轨假阳性**：只有 A 轨 DSH（`run_id IS NOT NULL AND workflow_node_run_id IS NULL`）存在 `execute_approved_dsh_tool` 执行后腿并写 `executed_at`；C 轨 `workflow.human_approval` 在 `decide_automation_approval` 同事务内调 `settle_approval_node` 置节点 `succeeded`（调执行入口显式抛 409 `approval_not_executable`），反链节点与 `workflow_run` `21fc3fa9…` 均已 `succeeded`。**分轨修正后真实执行落空 = 0 行**。B 口径 `executed` 词表同源裁决：A 轨规范分母须为 `approved + executed + rejected`（当前 `executed=0` 新旧公式数值恒同）。
   - `[4/4] D` 确认失败锁：**`0 rows`**（`operation_events` 572 行零命中，`ai.api.*` 事件 0 行＝零行使下的零事件）。
2. **`v3-p3` §3.2 三条责任主体断言实跑**：未双侧人签审批 = **0** ／ 孤儿或失活发起人 `workflow_run` = **0** ／ 空 actor `operation_events` = **0**（3/3 PASS）。
3. **N1 试点窗口闭环核实**：代号项目 `FDE-20261112-5CFF4FA2`（`pilot-001` 承载项目）在 2026-11-13 已有 **2 条蔡工亲手发起的生产 `host_poll` `agent_runs` `completed`**（`b647945e…` 3 件产物 **3/3 已人工复核**；`347fb585…` 5 件产物待复核），任务书 §9 硬指标 2 已兑现；宿主编码 run 走产物终审链不写 `automation_approvals`，且训练场 `SIM-V32-LAB` 9 行须排除出生产分母。
4. **支撑度与拍板位结论**：候选开放档（G4 / S / 比对）同类审批样本均为 **0** ⇒ 支撑度判定 **`insufficient_for_unfreeze`**；**D7 阈值拍板位明确落档为「待蔡工拍板」（零预支任何数值，闸态变更数 = 0）**，兑现任务书 §9 硬指标 3。

### r4 变更面

- **报告与台账**：NEW `docs/audit/D7-四口径运行证据复审报告-2026-11-13.md`（§0–§7 完整复审报告＋双层证据＋阈值拍板承接表）＋`docs/audit/D4-D7人工项推进包-2026-11-07.md` §4/§6 回填＋`docs/audit/下一步实施台账-2026-11-07.md` §2/§4/§11.4/§12 同步＋`docs/implementation/v3-backlog.md` P3/22:25 段同步＋本文件＋`CHANGELOG.md` r4 节＋`AGENTS.md` 当前状态 bullet。
- **机械钉**：NEW `server/tests/test_d7_evidence_report_nail.py`（静态防作弊钉：锁死报告七项必填节在场、拍板位必须保持「待蔡工拍板」且若出现未签字数值预支即判红、`v3-p3` §5 解冻判定表全 `PROPOSED` 未被偷改）。**零生产代码改动・零迁移・零新路由**（490/52/153/74 全不变）。

### r4 待办（收口条件）

- [x] 按推进包 §4 骨架出具真实四口径复审报告（含 C/B 口径源码级裁决与 N1 窗口实况）
- [x] 阈值拍板位状态明确落档为「待蔡工拍板」（零预支数值，闸态变更数 = 0）
- [x] 静态防预支机械钉 + 台账同步钉本地实跑全绿（PR 与 CI 四绿见收口回执，回填式）

---

## r5 · T-14b 收尾（`diag.fde18.com` 443 上线＋官网 CTA 锚点切换＋线上复测，2026-11-13）

### 开工前检查单与两条潜伏线上真缺陷修复

- `git fetch fork` 对齐 `fork/main` `67c0c867`（#440）；在途 open PR（`#443`/`#442`/`#441`/`#439`/`#424`）均与 T-14b 部署及台账面无冲突。
- **★真机缺陷 1（远端 `diag.fde18.com.conf` 漏写 `server` 级 `root`/`index`）**：SSH 预检 `141.95.33.198` 时发现 `/www/server/panel/vhost/nginx/diag.fde18.com.conf` 仅在 `location ^~ /.well-known/acme-challenge/` 内写了 `root`，`server` 级缺失 `root /www/wwwroot/diag.fde18.com; index index.html;`，导致 `/` 落入宝塔默认目录返回 **58,286B 的 `<title>Sorry, the website has been stopped</title>`**（状态码同为 200，前序只测 `%{http_code}` 漏检）。备份 `/root/diag.fde18.com.conf.bak-20261113-r5` 后补齐重载，恢复为 `1,246B` 工作台 SPA。
- **★真机缺陷 2（线上 `fde18.com/contact/` 的 `PUBLIC_FORM_KEY` 被前序部署截断）**：部署官网前提取线上联系页 `formKey` 时发现 `185827` 次部署因解析正则失误把残串 `formKey = \` 烤入线上页面导致表单回退失效；从远端历史备份 `/www/wwwroot/fde18.com.bak-20261110-140044/contact/index.html` 找回完整 36 位真 UUID 并随本次部署恢复（校验 `formKey_is_valid_uuid=True`，密钥全文零入库零打印）。

### 执行链与线上实测回执（任务书 §3 r5 行＋§9 硬指标 4 全兑现）

1. **DNS 前置（人工，蔡工亲手完成）**：阿里云云解析添加 `diag.fde18.com → 141.95.33.198` A 记录；权威 NS（`dns31/32.hichina.com`）与 `1.1.1.1`/`8.8.8.8` 实测全部命中 `141.95.33.198`。
2. **certbot 443 签证与 vhost 升级**：`certbot certonly --webroot -w /www/wwwroot/diag.fde18.com -d diag.fde18.com` 签发成功（Issuer `Let's Encrypt YR1`，有效期 `2026-11-13` 至 `2027-02-11`）；备份 `/root/diag.fde18.com.conf.bak-pre443-r5` 后升级为 80→`301 https://$host$request_uri`（保留 ACME challenge）＋443 SSL HTTP/2（CSP/X-Frame-Options/覆盖写 XFF 同主站）。
3. **`diag.fde18.com` 公网 HTTPS 7 项冒烟全绿**：①`http://diag.fde18.com/` → `301 https://diag.fde18.com/`；②`https://diag.fde18.com/` → `200`（SPA + CSP）；③JS 资产 `200`（`1,499,257B`，`x-diagnostic-token`/`#diagnostics` 在位）；④`health/ready` & `live` `200`；⑤`questionnaire` `200`（`7,233B`）；⑥`POST /api/v1/diagnostics/sessions` 真建匿名会话 `200`（`sid=8ab84475…`）；⑦闸隔离：`diag` 注册面 `404`、`app.fde18.com` 诊断面 `404`。
4. **官网仓 `caishide/fde-ops` 切换 CTA 与部署上线**：
   - PR **#55**（squash **`04f4220`**，`website-ci` runs `43423553682`/`43423561348` 全绿）：`/diagnosis-samples/` 主 CTA 切 `https://diag.fde18.com/#diagnostics`（政策补贴测算·免注册）、次 CTA 切 `https://diag.fde18.com/#diagnostics/sample`、辅助行保留初诊入口；E38 正式收回 `_APP_LINK_OK` 过渡豁免（`app.fde18.com` 全站零容忍）、E39 持 `diag` 双直链；变异 M1/M2 双红→字节级还原→绿；口径表升 v2.3（§4.18）、运营台账升 v1.6（row 21）。
   - 部署：`deploy-ovh-fde18.sh` STAMP **`20261113-201958`** exit 0（**99/99 PASS**＋85 文件＋IndexNow 50 URL 200×2）→ 推送部署 tag **`deploy-20261113-2019`** → 台账回执补记 PR **#56**（squash **`a2b40f1`**，CI 双绿）。
5. **本仓公网只读校验器与台账同步**：NEW `scripts/verify/verify_diag_public_live.py` 实跑 `VERIFY-R5-DIAG-PUBLIC-LIVE PASS`（6/6 全绿）；同步 `docs/architecture/获客诊断工具实施任务书-v1.md`（T-14 → ✅ 全收口，R-A 止损线起算日锚定 `2026-11-13`→`2027-02-13`）、`CHANGELOG.md` r5 节、`AGENTS.md` 当前状态头。**零后端/桌面生产代码改动・零迁移・零新路由**（490/52/153/74 不变）。

### r5 待办（收口条件）

- [x] 蔡工配齐 `diag.fde18.com` A 记录 → Let's Encrypt 443 签证生效＋nginx 80→301/443 上线
- [x] `fde-ops` 官网 CTA 切换 `diag.fde18.com` 双锚点＋收回 `app.fde18.com` 豁免（PR #55 `04f4220`＋tag `deploy-20261113-2019`＋PR #56 `a2b40f1`）
- [x] 公网 HTTPS 线上复测全绿（`verify_diag_public_live.py` 6/6 PASS；本仓 PR #445 `2bf8da42` 四绿收口）

---

## r6 · E8 实施与降级验收轮（E8/E11 意图↔实现逐条核对＋三处真缺口闭合修复＋台账同步，2026-11-14）

### 开工闸与并发吸收核对（任务书 §1 吸收条款＋§3 r6 行）

- **开工闸两项齐备**：① D7 四口径运行证据复审报告已于 r4 出齐合并（`#438` `05581872`）；② 蔡工显式下达开工令「继续推进 r6」（不跨闸不自动跳轮）。
- **`goal-crv` 吸收扫描**：遍历 `docs/goal-crv-r1..r10-*.md` 与 `docs/audit/全面代码审查报告-2026-11-13.md` 全量 147 条 QR 台账，检索 `automation_fallback` / `automation_jobs` / `credentials.py` / `dsh_runtime` / `AutomationTaskRun` / `DEGRADABLE_DSH_CODES` / `READ_ONLY_TOOLS`，仅 `goal-crv-r1:46` 正向确认 `DSHRuntimePool.execute` 开发态合法路径——**与 E8/E11 交集的 P0/P1 缺陷＝0 条**。
- **并发基线盘点**：PR `#414`（`8cbb21b`）已先行合入 E8 骨架（`control/automation_fallback.py`＋`control/automation_jobs.py`）与 E11 凭据管理面（`agents/credentials.py`＋三路由＋7 个 zcode 种子赋 `credential_ref="default"`）；`#440`（`67c0c867`）已对齐 `agent_pilot_max_runs=10`；`#441`（`d1126d3c`）＋`#446`（`4f4639fb`）已完成 `ai-eval` 四槽凭据接线并产出首份非 `insufficient_data` 报告（`pass` / `kpi=1.0` / `live 9/9`）。按台账 §12 与 `v3-backlog` 指派，本轮对 `#414` 执行 **N3 五问＋E11 意图↔实现（intended-vs-implemented）逐条验收**（注：同名外部技能已迁 `phuryn/product-engineering`，按其指引直接对规格与源码/测试逐行对账）。

### E8/E11 意图↔实现逐条对账与三处潜伏真缺口修复

1. **E11 智能体凭据管理面（100% 吻合，零生产改动）**：
   - `agents/credentials.py`＋`GET/POST/DELETE /api/v1/agents/credentials`：`is_platform_operator` 平台身份＋`system_operator` 双轴硬闸；凭据名正则 `^[A-Za-z0-9_]{1,120}$` 封死 `FDE_AGENT_<NAME>` 环境变量名注入；Fernet 加密派生链与 `agents/service.py::_decrypt_credential` 逐字节同源；响应仅回 `credential_configured: bool`（零明文零密文回显），且不进 `api_catalog`（98 ENTRIES 不变）；`seeds/agents.json` 7 个 `zcode` 型赋 `"default"`、3 个 `persona` 型保 `null`。`test_agent_credentials.py` 19 例全绿。
2. **E8 A 轨只读降级层（N3 五问核对抓出三处「测试绿而生产断/漏」真缺口并当场闭合）**：
   - **N3-Q1 任务封闭集** ✅：`DEGRADABLE_TASK_TYPES = frozenset({"ai"})`，`system` 任务与已成功任务恒返 `None` 不降级；`automation.execute` 不在 `RECOVERABLE_JOB_TYPES` 中，H4 不自动重试红线保持。
   - **N3-Q2/Q3/Q5 产出物、人工确认与诚实失败语义** ✅：降级不伪造宿主工作区 `sha256` 产物指针，落 `output_json.degraded=True`、`degraded_reason=error.code`、`degraded_confirmation_required=True`（蔡工逐件确认，H1/H11 不自动收敛）与显式只读产出描述；降级面自身再抛 `DSHRuntimeError` 时 `status="failed"` 且保留 `degraded=True` 留痕。
   - **★真缺口 1（N3-Q4 命名空间断层致真实任务 100% 无法降级）**：`control/service.py:281,418-425` 创建桌面端/ClawBot `AutomationTask` 时强制校验并持久化非空点分能力名（默认 `DEFAULT_AUTOMATION_CAPABILITIES = ["project.read", "project.summarize", "file.search"]`），而 `#414` 的 `automation_fallback._read_only_tools_for` 在 `capabilities` 非空时仅与下划线工具名 `READ_ONLY_TOOLS` 做字面相等匹配（交集为空 `()` ⇒ 恒返 `None`；原接线测试直接 ORM 塞 `requested_capabilities=[]` 掩盖了断层）。**修复**：`automation_fallback.py` 由 `mcp_gateway.TOOLS` 单一真身派生 `CAPABILITY_READ_ONLY_TOOLS` 与 `UNSCOPED_READ_ONLY_TOOLS`（`project.summarize` 共享项目只读工具集，命中点分只读能力时附带 5 项无能力门槛通用只读工具；直传下划线只读工具名保持精确同名兼容；纯写/编排能力集仍返 `()` → `None`）。
   - **★真缺口 2（N3-Q4 降级调用未收窄任务能力与工具白名单）**：`automation_jobs._record_degraded_execution` 虽把 `plan.allowed_tools` 写入 `output_json["degraded_allowed_tools"]`，但 `_run_degraded_readonly` 与 `ai_server_client._degraded_direct_result` 调 `direct_tool_completion` 时未传 `capabilities` 与 `allowed_tools`，导致模型实际拿到用户档位全量能力工具集，与审计留痕声称的白名单不一致。**修复**：`ai_tool_loop.tool_definitions` / `direct_tool_completion` 新增可选关键字参数 `capabilities` 与 `allowed_tools`；`automation_jobs` 显式透传 `capabilities=execution["allowed_tools"]`、`allowed_tools=plan.allowed_tools`，`ai_server_client.execute_ai_prompt` 两处降级分支透传 `capabilities=capabilities`。
   - **★真缺口 3（N3-Q4 执行期缺二次只读硬闸）**：`ai_tool_loop._run_tools` 原先只靠 `tool_definitions` 在模型 schema 层过滤 `READ_ONLY_TOOLS`，模型返回 `tool_calls` 时直接调 `call_tool`；因 `mcp_gateway.TOOLS["api_execute"]` 的 `capability=None`（内部靠 `workbench.write` 鉴权），一旦高权限账号在直连/降级循环中遇提示词注入或模型幻觉返回 `api_execute`，写库操作会被直接执行。**修复**：`_run_tools` 新增 `permitted_tools = _permitted_read_only_tools(allowed_tools)`（恒 `<= READ_ONLY_TOOLS`）执行前硬拦截，任何非只读或未授权工具（如 `api_execute` / `file_send_wechat` / `lcsc_search`）一律返回 `{"error": "forbidden", "message": "本次执行未开放该工具。"}`，绝不触达 `call_tool`。

### 验证回执

- **新增测试 +6 例**：`test_automation_fallback.py` +2（11→13：点分能力展开＋`project.summarize` 映射）、`test_automation_fallback_wiring.py` +1（5→6：真实 `POST /api/v1/task-center/automations` 点分能力创建→降级落账→工具收窄端到端）、`test_ai_tool_loop.py` +2（admin 身份写工具 `api_execute` 硬拦截＋能力与白名单双重收窄）、`test_ai_server_direct_fallback.py` +1（`execute_ai_prompt` 降级透传 `capabilities`）。
- **变异三连全真红→字节级还原（sha256 一致）→复绿**：M1 移除点分能力映射（`3b1fb920b3c9`，2 红）／M2 移除 `automation_jobs` 的 `allowed_tools` 透传（`a4fa3b3a5d99`，1 红）／M3 移除 `_run_tools` 执行期只读硬闸（`7dab87995c89`，2 红）。
- **广域回归与静态闸**：控制面与安全邻域 13 套件 **209 passed**＋`ruff check` 全绿＋`scripts/check-python-types.py` **OK（277 occurrences / 102 distinct 基线不变）**＋`check_archify_diagram_freshness.py` OK＋台账钉/D7 报告钉全绿。**零迁移・零新表・零新路由・零桌面改动**（现测结构口径 **490 路由 / 52 蓝图 / 153 表 / 75 rev 单头 `d4b8e1f6a9c3` / 98 ENTRIES** 不变）。

### r6 待办（收口条件）

- [x] 开工闸（D7 报告出齐＋蔡工显式令）与 `goal-crv` 吸收条款扫描确认（0 交集缺陷）
- [x] E8/E11 对照 N3 五问逐条意图↔实现核对，闭合 E8 三处真缺口（点分能力映射／降级收窄透传／`_run_tools` 执行期只读硬闸）并通过 +6 例回归与 M1–M3 变异三连
- [x] 台账同步（本文件＋下一步实施台账＋`v3-backlog.md`＋`CHANGELOG.md`＋`AGENTS.md`；PR 四绿合并与活体容器追平三验随合并闭环）

---

## 收口 · 上线就绪终扫（2026-11-14，任务书 §8/§9）

### §8 逐项终扫（对照 `docs/deployment/对外试用部署方案-v1.md` §8 十三项清单——技术判据引用 2026-11-09 T6 现测＋本轮只读复测，业务闸不代拍）

- **本轮新只读复测全绿**：①`https://app.fde18.com/api/v1/health/ready`＝`200`、`/live`＝`200`、官网 `https://fde18.com/`＝`200`；②证书有效（`app` 至 `2027-02-07`、`diag` 至 `2027-02-11`）；③公网 `8010/5432/6379` 三端口外探全部 `TimeoutError`（不可达，只 443 开放）；④四 compose 服务 healthy；⑤`VERIFY-R5-DIAG-PUBLIC-LIVE` 复跑 **PASS**（6/6）。
- **十三项技术判据**＝2026-11-09 T6 组现测 13/13 具备（含 R-T6-1 XFF 根治 PR #250）+ 本轮复测项无回归 ⇒ **维持具备**；`G-B`/`G-C` 闸未签、试用账号未发放 ⇒ 依原文纪律**不得发放任何登录信息**（待授权，见 BLOCKED.md #2）。
- **清单外现测发现两项共享活体风险**（跨栈 Redis 别名轮询＋healthcheck 探针 FAIL exit=0 无判别力）＝既有拓扑/代码问题，不属本线改动面 ⇒ 如实登记 `docs/goal-sprint-BLOCKED.md` #4/#5，处置待拍板。

### §9 六条硬指标终核（逐条贴证据）

1. **adapter_missing 解除** ✅：台账 §12 r3 回执在场（grep 命中 15 处；①实装＋N2 签核两项齐备，VERIFY-R3 PASS）。
2. **N1 试点窗口终态** ✅：活库现测 2 条 `host_poll` run 全 `completed`（`b647945e…` 3 件、`347fb585…` 5 件），**8/8 产物全部人工复核**（r4 时第二批 5 件待复核，本轮现测已清零）；sha256 指针纪律（`9fba8b48…`/`dc3f01ac…`/`5cb5b17b…` 等 8 枚指纹，原件永不入库）；窗口 11-19 止，到期处置归蔡工（BLOCKED.md #3）。
3. **D7 复审报告出齐＋拍板位明确** ✅：报告 r4 出齐（`docs/audit/D7-四口径运行证据复审报告-2026-11-13.md`），拍板位＝「待蔡工拍板」（零预支，闸态变更=0）。
4. **T-14b 终态** ✅：r5 全兑现，本轮 `verify_diag_public_live.py` 复跑 PASS。
5. **全部轮 PR 四 CI job 绿** ✅：r1 #411／r2 #422／r3 #433（#434 补记）／r4 #438／r5 #445／r6 #459 各自合并时四绿（r6 贴 run `43492400743` 一次四绿＋`43492413946` 复跑四绿）；活体三验绿（r6：url_map 490／alembic `d4b8e1f6a9c3 (head)`／三镜像 `ae558917…`/`936dfd58…`/`199d798e…` 逐位一致）；`git diff 35ffbea..fork/main --stat` 现测 201 files/+39262/−1362——含并行线（goal-crv、桌面、L 线等）按开工拍板并行条款并入的改动面，各轮自身宣称面已在本轮 PR diff 逐次核验。
6. **全程纪律** ✅：零闸代拍、零阈值预支、零证据造假；台账三同步见下。

### 台账三同步（§8）

- `CHANGELOG.md` 新增本收口节；`AGENTS.md` 新增本线收口行（动前验锚唯一性：r6 锚 count=1）；`docs/audit/下一步实施台账-2026-11-07.md` §12 追加收口行；本文件至此为**终态**（r1–r6＋收口全 ✅，冲刺线收官）。

### 收口待办

- [x] 部署方案 §8 验收清单逐项终扫（技术判据复测＋业务闸如实列待授权）
- [x] §9 六条硬指标逐条贴证据核验
- [x] `docs/goal-sprint-BLOCKED.md` 落盘（待授权 3 项＋共享活体风险 2 项）
- [x] 台账三同步＋本文件终态（随收口 PR 合并闭环）

---

## 收口拍板回写（2026-11-14，交互选择卡四项全按推荐项落定）

1. **D7 阈值**＝维持待拍板（`insufficient_for_unfreeze`，样本达标后再拍）；2. **G-C 签署与发放**＝整理签署材料包（NEW `docs/deployment/对外受控试用-G-C签署材料包-2026-11-14.md`；口径更正：G-B 已于 2026-11-10 有效签署，未签仅 G-C，剩余 `OWNER`/`HOST` 亲自项＝T5-7 外部真机登录＋改密＋写操作）；3. **N1 试点窗口**＝2026-11-19 按期关闭；4. **两项共享活体风险**＝单独立项一次修两项（NEW `docs/goal-liveinfra-活体基础设施修复-任务书-v1.md`，排期≠实施授权）。
拍板留痕全文见 `docs/goal-sprint-BLOCKED.md` 各条「拍板回写」行；本轮零代码零迁移零路由。
