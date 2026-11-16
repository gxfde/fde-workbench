# goal-launchclose · 上线收口 PROGRESS

- 任务书：`docs/goal-launchclose-上线收口-任务书-v1.md`（唯一任务来源）。执行树：`D:/test/fde-wt-launchclose`（分支 `chore/launchclose` @ fork/main `694c647e`）。
- 开工：2026-11-17。执行者：AI（ZCode）。

## 理解的目标／顺序／最大风险（开工登记）

1. 目标＝A 线工程侧达「G-C 可签」：R1 main CI 四绿 → R2 本机主栈带闸重建三验（493→新值反向验证）→ R3 远端只读对照表（AI 零凭据零写面，OPS/HOST 亲手执行）→ R4 N1 关窗（**时点锁 11-19，今日只备料**）→ R5 随轮死线（CHANGELOG 七节＋台账＋AGENTS＋口径三件套＋r53）。
2. 最大风险＝R1 复跑仍红需真回归修复（收集 ≥4007、禁放宽）；其次 R2 重建撞并发会话活体共享（重建前后 `docker ps` 留痕 qiflow-* 零 recreate）。
3. 让步顺序：生产活体安全 > 口径诚实 > 做得全 > 做得快。

## 任务 0 前提核验回执（2026-11-17）

- 0.0 两份输入文档逐字节复制进本 worktree：`cmp` 全等（BYTE-IDENTICAL BOTH）；`git status -s` 两个 `??` ✓
- 0.1 `git fetch fork`：tip `694c647e`，`git rev-list HEAD..fork/main --count`＝**4**（≤6 预期）✓
- 0.2 `gh run view 43867006517 --json conclusion`＝**failure**（仍红，R1 需 rerun）✓
- 0.3 `ls server/migrations/versions/*.py | wc -l`＝**86**；`grep -l down_revision d8b4f6a2c9e7*.py`＝`d8b4f6a2c9e7_quote_source_role_hours.py` 在场 ✓
- 0.4 `python scripts/deploy/takeover_check.py --help`＝命令在场 ✓

## R1 CI 定性（✅ 全绿收口——分支甲）

- [x] `gh run rerun 43867006517 --failed`（2026-11-17 发起）守至 completed。
- **终态回执**：`gh run view 43867006517 --json status,conclusion,jobs` ⇒
  ```json
  {"conclusion":"success","jobs":[{"conclusion":"success","name":"server-tests","status":"completed"},{"conclusion":"success","name":"secrets-scan","status":"completed"},{"conclusion":"success","name":"desktop","status":"completed"},{"conclusion":"success","name":"pseudonymization","status":"completed"}],"status":"completed"}
  ```
- **四 job 全 `conclusion=success`**——复跑即绿（11-16 晚的 `test_qr018` 503 系 flake 性质未复现），**分支甲收口，无需真回归修复批**。

## R2 本机主栈带闸重建三验

- [x] **takeover_check 前置闸（2026-11-17）**：`python scripts/deploy/takeover_check.py --tree D:/test/fde-workbench --live`——**FAIL=0**（全 WARN 为 `.env.example` 有而 `.env` 无的建议核对项，均系缺省关闭类部署闸键，代码默认值语义正确）；尾部两 [OK]：「树检查通过：compose 插值 1 变量＋关键键 6 全在位（键值未读取）」＋「migrations 挂载源在场: /mnt/d/test/fde-workbench/server/migrations」。
- [x] **重建前容器对照快照**（`docker ps` 留档 `/tmp/docker-ps-before-rebuild.txt`）：fde-workbench 四容器 healthy＋qiflow-* 邻栈（mautic×4/twenty×5/n8n×2/postiz×3/temporal×4/outbound-caddy/openoutfind）＋xiaozhi_app/reddit-rss-relay/qdrant_xuankong/xuankong-kuzu 全在案。
- [x] **build → recreate → alembic upgrade → 三验四项（2026-11-17 01:09 全绿）**：
  1. `docker compose -p fde-workbench build api worker scheduler` exit 0——新镜像 api `483c145c2c9c`／worker `2ae06ff576fd`／scheduler `c8228cae2c05`（2026-11-17 01:09:03 构建）；
  2. `up -d --force-recreate api worker scheduler`——三容器 Started，30 秒后全 healthy（redis 未动）；
  3. 容器内 `python -m alembic upgrade head`——**74 rev `c8e2a6f0b9d4` → 86 rev `d8b4f6a2c9e7` 九步全跑**（含 V3.3 双头 merge 迁移 `c2a9e7d5b3f1`）；重建前该命令报 `ModuleNotFoundError: fde_api.projects.gate_receipt`，重建后消失（模块随新镜像在位）。
- **三验四项输出（逐项贴对话）**：
  - ① `url_map non-static = **515**`（重建前 493 → 重建后 515，**值变化即重建生效的反向验证成立**，与静态口径 515 路由逐位一致）；
  - ② 容器内 `python -m alembic current` ＝ **`d8b4f6a2c9e7 (head)`**；
  - ③ `docker inspect --format '{{.Image}}'` 三容器＝api sha256:483c145c2c9c…／worker sha256:2ae06ff576fd…／scheduler sha256:c8228cae2c05…，与本树 `docker images` 同 tag（api `483c145c2c9c`／worker `2ae06ff576fd`／scheduler `c8228cae2c05`）**逐位一致**；
  - ④ `curl http://127.0.0.1:8010/api/v1/health/ready`＝**200**、`/live`＝**200**。
- **qiflow-* 邻栈零 recreate 证明**：重建前后 `docker ps` 全量逐容器比对——qiflow-mautic×4（`2073e0c005b5`/`dd3e5f403259`/`a9e4200d360e`/`e8ea415c5fc3`）、n8n×2、twenty×4、postiz×3、temporal×3、outbound-caddy、openoutfind、qdrant_xuankong、reddit-rss-relay、xiaozhi_app、xuankong-kuzu、fde-pg/redis-forward、fde-workbench-redis-1 **全部容器 ID 前后逐位一致**（仅 api/worker/scheduler 三容器 ID 变更＝预期 recreate 面）。
- 结果：**R2 全绿收口**。

## R3 远端只读现测（清单已交 OPS/HOST，AI 零远端凭据零写面）

**执行通道**：以下命令清单交 `OPS`/`HOST` 亲手在远端部署树执行（SSH），回执原文贴回对话，AI 回填对照表。远端栈/容器名以远端实际为准（`docker ps` 先看栈名再套命令）；`docker compose exec` 一律加 `</dev/null`。

### 只读命令清单（OPS/HOST 亲手）

```bash
# ① 栈与容器清单（先看栈名）
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
# ② 镜像版本与创建时间（按①看到的镜像名替换 <fde-api-image>）
docker images --format '{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.CreatedAt}}' | grep <fde-api-image-关键字>
# ③ 容器内 alembic current（api 容器名按①）
docker compose -p <远端栈名> exec api python -m alembic current </dev/null
# ④ env 五键（只记值形态；密钥类键一律不回执）
docker compose -p <远端栈名> exec api env | grep -E 'FDE_DIAGNOSTICS_ENABLED|FDE_REGISTRATION_ENABLED|FDE_AGENT_HOST_EGRESS_GATE_ENABLED|FDE_AGENT_HOST_EGRESS_ALLOWLIST|FDE_AGENT_HOST_POLL_ENABLED' </dev/null
# ⑤⑥ 公网探活（可在任意有网机器执行）
curl -s -o /dev/null -w 'ready=%{http_code}\n' https://app.fde18.com/api/v1/health/ready
curl -s -o /dev/null -w 'live=%{http_code}\n'  https://app.fde18.com/api/v1/health/live
# ⑦ 补强：证书余量（可选）
echo | openssl s_client -connect app.fde18.com:443 -servername app.fde18.com 2>/dev/null | openssl x509 -noout -enddate
```

### 一致性对照表（6 项 × 远端现状 / G-C 快照 / 一致?）——OPS 回执到达后回填

| # | 项 | G-C 快照（文档可考值＋出处） | 远端现状（实测回执） | 一致? |
|---|---|---|---|---|
| 1 | 镜像版本 | 无考（远端部署执行记录不在仓；OPS 回执即为基线） | **待 OPS/HOST SSH 回执** | 待定 |
| 2 | 镜像创建时间 | 无考（同上） | **待 OPS/HOST SSH 回执** | 待定 |
| 3 | 容器内 `alembic current` | 无考（部署代码版本未记录；OPS 回执即为基线） | **待 OPS/HOST SSH 回执** | 待定 |
| 4a | `FDE_DIAGNOSTICS_ENABLED` | 关闭（判据：`app.fde18.com` 诊断面 404，goal-sprint r5 冒烟⑦ 2026-11-13） | **行为面现测一致**：公网 GET `/api/v1/diagnostics/questionnaire`＝**404**（2026-11-17 AI 零凭据只读探活；与 G-C 快照判据「诊断面 404」直接吻合，与本机同版本闸关行为一致）；env 键值终证待 OPS/HOST SSH 回执 | **✅ 行为面一致／env 待回执** |
| 4b | `FDE_REGISTRATION_ENABLED` | 关闭（判据：SES 生产批复前注册面整体 404，M2 纪律；diag 冒烟⑦同测） | **GET 行为面＝405**（公网 GET `/api/v1/auth/register/enterprise`；与本机同版本闸关态 GET 405 逐字一致——405＝POST-only 动态规则 `<entry>` 在位的方法语义，非闸开证据；本机对照 POST＝404 才是闸关真语义，**远端 POST 因写面禁试**）；闸态终证待 OPS/HOST env 回执 | **⏳ 待 env 回执（GET 印证规则在位与版本 ≥M2）** |
| 4c | `FDE_AGENT_HOST_EGRESS_GATE_ENABLED` | 无考（somwyn 收口轮两键落「部署态 server/.env」未细分本机/远端；OPS 回执即为基线） | **待 OPS/HOST SSH 回执** | 待定 |
| 4d | `FDE_AGENT_HOST_EGRESS_ALLOWLIST` | 无考（同上；若有值应=zcode.z.ai,api.z.ai,z.ai,api.minimaxi.com,bigmodel.cn,open.bigmodel.cn 族） | **待 OPS/HOST SSH 回执** | 待定 |
| 4e | `FDE_AGENT_HOST_POLL_ENABLED` | 关闭（判据：v2 任务书 T3-6「桥 503、运行态 false」；N1 试点 pilot-001 承载于本机主栈） | **待 OPS/HOST SSH 回执** | 待定 |
| 5 | `ready` 探活 | 200（G-C 材料包 §2 T5-6 行，goal-sprint 收口终扫 2026-11-14） | **200**（AI 公网只读现测 2026-11-17：`curl -s -o /dev/null -w '%{http_code}' https://app.fde18.com/api/v1/health/ready` ⇒ `ready=200`） | **✅ 一致** |
| 6 | `live` 探活 | 200（同上） | **200**（同刻现测：`live=200`） | **✅ 一致** |
| ⑦ | 证书余量（补强项） | app 至 2027-02-07（G-C 材料包 §2 T5-6 行） | **notAfter=Feb 7 02:08:17 2027 GMT，CN=app.fde18.com**（本机 openssl s_client 现测 2026-11-17） | **✅ 逐位一致** |

**漂移判定**：4a/4b/4e 出现「启用」即为漂移 ⇒ BLOCKED.md 重开升版拍板；1/2/3/4c/4d 无考项以本次回执为基线登记（口径诚实：没测过就说没测过）。

- 结果：**清单已整理（上表），待 OPS/HOST 回执**。

## R4 N1 关窗批次（时点锁：2026-11-19 到期当日或之后；今日 11-17 只备料）

- [x] **备料① 关窗命令序列**：部署树 `server/.env` 置 `FDE_AGENT_HOST_POLL_ENABLED=0` → `docker compose -p fde-workbench up -d --force-recreate api` → 容器 env 复验 `docker exec fde-workbench-api-1 env | grep FDE_AGENT_HOST_POLL_ENABLED`（输出贴对话）。
- [x] **备料② Vex F2 claim token 吊销/轮换核验（2026-11-17 读面＋实跑）**：
  - 机制面：`agents/service.py:1625` `_require_host_poll_enabled`——开关关或令牌未配置 ⇒ **403 `host_poll_disabled` fail-closed**（关窗后旧票全拒的第一道闸）；`service.py:1634` `_verify_host_poll_token`——sha256 恒比，不一致 ⇒ 403 `host_poll_forbidden`（轮换后旧票第二道闸）；`models.py:144` `host_token_hash String(64)`＝sha256 存储零明文；`host_receipt.py:80`／`host_context.py:72` run 级绑定校验。
  - 测试钉实跑（主树 venv＋`fde_workbench_test` 专测库，2026-11-17）：`test_host_poll.py` 六枚 **6 passed, 3 warnings in 12.40s**——`test_disabled_by_default_403`／`test_enabled_without_token_403`／`test_wrong_token_403`／`test_claim_conflict_after_token_rotation`／`test_receipt_rejects_after_token_rotation`／`test_context_gates_on_claim_binding_after_token_rotation`。
  - **核验结论：核得出——「窗口/令牌状态失效后旧票不可领取」由既有测试钉证明，无需 BLOCKED**。11-19 执行日再加跑一遍同组测试钉作执行日证据。
- [x] **执行排程机制化（2026-11-17 登记）**：R4 全序列已挂 one-shot 定时自动化（automation-48ce31bb-1373-408d-a498-896d829e4e7f，**2026-11-19 09:30** 触发）——前置 takeover_check 闸（FAIL 即停）→ `server/.env` 只改 `FDE_AGENT_HOST_POLL_ENABLED=0` 一键（改前 grep 现值留痕）→ recreate api → 容器 env/alembic current/ready-live 复验 → test_host_poll 六钉复跑 → qiflow-* 零 recreate 前后对照 → PROGRESS/BLOCKED 回执收口；任一复验不符即停手还原原值。**留痕可推翻：蔡工可随时口头撤销该自动化或改派人工执行**。

## R5 随轮死线批次（✅ 全链收口）

- [x] **CHANGELOG 补 2026-11-16 轮次七节＋本线节**：七节＝AF1-WP1 三批合节（#487 `2ef9ad18`/ #491 `4ae9b34f`/#493 `ddb2064b`）＋W1（#488 `ec317b39`）＋W2-2（#490 `3ec9a572`）＋W3（#492 `a9a2743d`）＋TrustBoard（#489 `b9b67e18`）＋AF1-WP3（#494 `694c647e`）＋V3.3 docs（`f638d236`）＝8 个 PR 号对号入座；只增不改；中途一次节标题被 Edit 吃掉的事故当场补回并结构终扫（节序 grep 全对）；`test_ledger_sync_nail.py` **2 passed**（占比钉绿）。
- [x] **台账补登记**：`docs/audit/下一步实施台账-2026-11-07.md` 追加 §13（八 PR 对号表＋结构口径＋登记人留痕）。
- [x] **AGENTS「当前状态」行刷新**：本线轮次头插（R1–R5 全回执摘要）；括号配平与原行历史常态一致（code-review 审过非本线引入）。
- [x] **口径三件套/archify 复核**：`v3-workbench-inventory.json`＝blueprint 54／route **515**／table 159／revision 86 单头 `d8b4f6a2c9e7`——**515 已入清单**，与本线重建后活体 url_map 515 逐位互证；`check_archify_diagram_freshness.py`＝**OK 架构图口径与 inventory 逐项一致**（无需重生成）。
- [x] **便携版 r53**：`node scripts/release-version.mjs bump` 三源同步（RELEASE-COUNTER 52→53＋package.json `0.3.0-r53`＋fde-web-bridge.ts `0.3.0-r53-web`）→ `npm run typecheck` 零错 → `npm run test:desktop` **104 文件 1223 passed** → GUI 回归 **11/11 PASS**（fde-gui-regression 关卡）→ `electron-vite build` ✓ → `electron-builder --win dir --x64` ✓（worktree 独立输出目录 `release/`，无句柄锁）→ **asar 双证**：sha256 `5697cdeb898df6f9b3ef4ec11b273d5ad9f7d0452ea86b7c530703c09b63fdc4`；正向 marker「正式对外导出」（#490 新增）＝1 命中＋版本串「0.3.0-r53」＝1 命中；**r52 反向对照**（asar `bd309b15…`）＝0 命中——marker 区分新旧包成立；交付目录 `release/蔡工FDE-0.3.0-便携版-r53`。
- 结果：**R5 全链收口**。

## BLOCKED

（暂无）
