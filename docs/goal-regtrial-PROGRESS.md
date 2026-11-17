# goal-regtrial · 注册制试用开闸 进度账

任务书：`docs/goal-regtrial-注册制试用开闸-任务书-v1.md`（唯一任务来源）。
执行树：`D:/test/fde-wt-regtrial`（分支 `feat/regtrial-smtp`，自 fork/main tip `4dadbc64` 新建，不占评测树/部署树工作区）。
基线快照：2026-11-17。

---

## 任务 0 前提核验（执行树内复测，逐条贴输出）

| # | 命令 | 期望 | 实测 | 判定 |
|---|---|---|---|---|
| ① | `git log --oneline -1 fork/main` / `git rev-list HEAD..fork/main --count` | tip `4dadbc64`，count ≤3 | `4dadbc64 docs(gc): G-C 上线闸签署登记…(#502)` ／ count=**0** | ✅ |
| ② | `ls server/src/fde_api/mailing/` | 五件模块 | `__init__.py models.py policy.py routes.py service.py ses_client.py` | ⚠️ 口径差（见下） |
| ③ | `grep -c "def test" server/tests/test_mailing_ses.py` | 27 | **27** | ✅ |
| ④ | `ls desktop/src/renderer/src/commercial/EnterpriseRegisterPage.tsx` | 在场 | 在场（5101 字节） | ✅ |
| ⑤ | `grep -n "registration_enabled\|ses_enabled\|public_base_url" server/src/fde_api/config.py` | 三键在位 | `159:registration_enabled` / `162:public_base_url` / `179:ses_enabled` | ✅ |

**口径差登记（不构成停工，证据在案）**：任务书②写「=5」，实测 **6 个文件**＝五个实质模块
（policy/ses_client/service/routes/models）＋ `__init__.py`（包初始化文件，任务书列举时漏计）。
实质内容与任务书描述逐项一致 ⇒ 不停工，按实质模块口径推进。

**评测树侧说明（防止误判）**：评测树 `C:/Users/P1/.zcode/worktrees/a6c5/fde-workbench` 的 HEAD
停在 `f638d236`（落后 fork/main 13 个 PR），在该树跑①得 count=13 —— 这是**本地检出落后**的
既有常态，不是「tip 前进超预期」。任务书「>3 停报 BLOCKED」的口径针对执行树，
执行树自 fork/main tip 新建 ⇒ count=0 ✅。

**任务书入库**：评测树 → 执行树逐字节复制完成，sha256 双侧一致
`eba5422cdcbb9a195b1426183636317b435a8d85eedc9887adecc659b4aa7a3f`；`git status -s` 见
`?? "docs/goal-regtrial-注册制试用开闸-任务书-v1.md"`；随本线收口 PR 一并提交入库。

---

## 我理解的目标／顺序／最大风险（≤10 行）

1. **目标**：给 fde-workbench 加一条 provider 无关的 SMTP 发信通道（Zoho 形态），让注册面
   （四入口＋邮箱验证＋限流＋审核状态机，M2 已入库）能真正跑「注册→收验证邮件→验证→登录→写动作」，
   全程不等任何外部审批（SES 生产权限 2026-11-05 已被 AWS 拒绝，路线已冻结）。
2. **顺序**：R1 SMTP 通道 PR（核心）→ R2 配置面与红线修订（「SES 启用」→「发信通道启用」）→
   R3 前端注册入口可达性现测 → R4 本机主栈端到端（凭据到位才跑，否则 BLOCKED 备料）→
   R5 三同步＋收口 PR。
3. **最大风险 ①（架构）**：既有 `send_email` 与注册面开闸三条件写死 `settings.ses_enabled`，
   通道无关化必须**零回归**——既有 `FDE_SES_*` 键与 `test_mailing_ses.py` 27 例一字不动。
4. **最大风险 ②（配置面）**：新键必填校验与「两开关同开＝启动失败」要在 Settings 校验器层落地
   （fail-closed 早于首封信），且 SMTP 通道的发信域纪律不得弱于 SES 通道。
5. **最大风险 ③（凭据）**：SMTP 凭据＝OWNER 带外提供，未到位前 R4 端到端一步转 BLOCKED 备料，
   代码侧不空等。
6. **最大风险 ④（活体）**：本机主栈是跨会话共享资源，R4 重建后必做三验（url_map / alembic head /
   镜像 ID 逐位一致），只动 `fde-workbench` 前缀容器，qiflow-* 邻栈零触碰。

---

## R1 SMTP 发信通道 PR ✅

**代码面（零迁移零路由零蓝图零新表；口径不变 523 路由/55 蓝图/160 表/89 rev 单头 `b7f2d9e4c6a8`）**

| 文件 | 动作 | 要点 |
|---|---|---|
| `server/src/fde_api/mailing/smtp_client.py` | NEW | `SmtplibClient` 实现 `SesClient` 协议：标准库 `smtplib.SMTP`（465 走 `SMTP_SSL` 隐式 TLS）＋`starttls(context=ssl.create_default_context())`＋`login`＋`send_message`；返回 **message-id 头形态标识**（与随信 `Message-ID` 头一致，幂等台账语义不变）；错误分类沿用 `SesSendError`：认证/拒件/5xx＝`message_rejected`（不可重试）、4xx/连接失败/超时＝`throttle`（可重试）、扩展缺失（STARTTLS/AUTH）＝`send_failed`（不可重试，**不回落明文、不降级认证**） |
| `server/src/fde_api/mailing/channel.py` | NEW | 通道解析唯一权威：`CHANNEL_SES`/`CHANNEL_SMTP`、`resolve_channel`（两开关同开抛 `MailChannelConflictError`）、`channel_enabled`（冲突时按未启用＝fail-closed） |
| `server/src/fde_api/mailing/service.py` | EDIT | 新增模块级 `create_mail_client(settings)`（**通道分支在前、SES 工厂在后**——模块级名字调用时解析，既有四处 `monkeypatch("fde_api.mailing.service.create_ses_client")` 打桩继续命中同一 SES 路径，**既有测试文件零改动**）；`send_email` 改通道无关（开关→发信域→幂等→抑制→限额，五步闸门与 `policy` 一字不动；发件人与允许域根按通道取） |
| `server/src/fde_api/config.py` | EDIT | 新增 7 键（出厂全关）：`smtp_enabled`／`smtp_host`／`smtp_port`（587）／`smtp_username`／`smtp_password`（`SecretStr`）／`smtp_from`／`smtp_send_subdomain`；新校验器 `validate_smtp_configuration`：两通道互斥（`smtp_and_ses_enabled_conflict`）＋启用即必填齐（`missing_smtp_configuration`）＋发信域纪律（`smtp_sender_domain_forbidden`） |
| `server/src/fde_api/registration/service.py` | EDIT | `surface_open` 第二条件 `settings.ses_enabled` → `channel_enabled(settings)`（**开闸三条件通道无关**；docstring 同步修订） |
| `server/.env.example` | EDIT | 增 SMTP 段（注释态占位，真值永不进仓）＋修订三条件注释与限流实数 |
| `server/tests/test_mailing_smtp.py` | NEW | **32 例**（全部 mock smtplib，零真实发信） |
| `scripts/verify/verify_smtp_mutation.py` | NEW | 变异自证脚本（四锚点，红→还原→绿，字节级还原一致） |
| `scripts/verify/dummy_smtp_server.py` | NEW | 本地假 SMTP（STARTTLS 真握手＋自签证书＋落盘 JSONL） |
| `scripts/verify/verify_registration_trial.py` | NEW | 端到端链路驱动（逐环实测并贴输出；取信支持本地落盘与真实 IMAP） |

**测试回执（容器内跑 CI 同款：api 镜像＋本 worktree 源码＋专属测试库 `fde_workbench_regtrial_test`）**

```
tests/test_mailing_smtp.py tests/test_mailing_ses.py tests/test_registration_surface.py
tests/test_commercial_registration_throttle.py  →  116 passed in 112.35s
```
（NEW 32 例＋**既有 SES 27 例零回归**＋注册面两套件全绿）

**静态门禁回执**

```
ruff check --select F401,F841 src tests   →  All checks passed!
python scripts/check-python-types.py      →  OK: no new type errors (baseline 277 occurrences / 102 distinct, current 277)
```

**变异验证回执（`scripts/verify/verify_smtp_mutation.py`，脚本自证非人工声称）**

| 锚点 | 变异 | 变异后 | 还原后 |
|---|---|---|---|
| M1 `mailing/channel.py` | SMTP 分支摘除（解析成 SES） | 4 failed / 28 passed（红 ✅） | 32 passed（绿 ✅）sha256 `3dbc33d56ef5cd6b` 一致 |
| M2 `mailing/smtp_client.py` | 4xx 不再可重试 | 1 failed / 31 passed（红 ✅） | 32 passed（绿 ✅）sha256 `b5f4c0cc303a60f0` 一致 |
| M3 `registration/service.py` | 开闸条件退回只认 SES | 1 failed / 31 passed（红 ✅） | 32 passed（绿 ✅）sha256 `af5e90cd2a5ea440` 一致 |
| M4 `mailing/smtp_client.py` | 摘除 STARTTLS | 2 failed / 30 passed（红 ✅） | 32 passed（绿 ✅）sha256 `b5f4c0cc303a60f0` 一致 |

```
================ mutation summary ================
[PASS] 4 mutations all red->green, byte-identical restore
```

**零回归硬证据**：`git diff` 中既有 `FDE_SES_*` 键定义与 `test_mailing_ses.py` **零改动**
（SES 路径唯一入口 `create_ses_client` 未动；新增分支只在其前面）。

---

## R2 配置面与红线修订 ✅

- **AGENTS 红线**：「注册面公开写面纪律」①开闸三条件第二项 `SES 启用` → **`发信通道启用（SMTP 或 SES）`**
  （注记 OWNER 拍板与 SES 冻结事实）；③限流上限 → **实数 10/日/IP**（代码缺省 20 不动、部署面按 10 配；
  `FDE_REGISTRATION_RATE_FAIL_CLOSED` 公网须设 1＝fail-closed）；**新增红线一条**「发信通道 provider 无关
  （SMTP 通道）」——把通道互斥、必填校验、发信域纪律、TLS 强制、口令 `SecretStr`、错误分类六条写进红线面。
- **`.env.example`**：新增 SMTP 段（7 键注释态占位）＋三条件注释修订＋`FDE_REGISTRATION_IP_DAILY_LIMIT=10`。
- **代码缺省未动**：`registration_ip_daily_limit` 缺省 20 与 `registration_rate_fail_closed` 缺省 False
  **一字未改**（既有断言 `test_registration_surface.py:241` 钉住 20；改默认值＝改既有阈值，红线不允许）
  ⇒ 实数 10 与 fail-closed=1 由 OWNER 在部署 `.env` 落值（清单见 BLOCKED）。

---

## R3 前端注册入口可达性现测 ✅

**现测结论**：路由**已挂载**（`App.tsx:80` 公开面分支 + `App.tsx:114` 已登录分支 + `useHashRoute.ts:76`
解析 `#enterprise-register`），但**全仓无任何可见导航入口**（登录页无链接、侧栏无入口）⇒ 试用者拿不到入口
⇒ 按任务书「缺则补链接」补。

| 项 | 内容 |
|---|---|
| 改动 | `desktop/src/renderer/src/auth/LoginPage.tsx`：登录表单下方加「还没有账号？**企业自助注册**」链接（`href="#enterprise-register"`） |
| 用例 | `desktop/tests/renderer/login.test.tsx` 增 1 例（入口存在＋href 正确＋点击后进入「企业注册」页）；另修 hash 路由的用例间污染（`afterEach` 复位 `window.location.hash`——jsdom 同文件共享 window） |
| 验证 | `npm run typecheck` 零错；`npm run test:desktop` → **104 文件 1231 passed**（基线 1230 +1） |

---

## R4 本机端到端（假 SMTP 真 STARTTLS，全链 PASS）✅

**为什么用假 SMTP**：真发信需要 OWNER 的 SMTP 凭据（未到位）。为避免「代码写完但链路没跑过」，
本轮用**本地假 SMTP 服务器**（STARTTLS 真握手、自签证书、客户端 `SSL_CERT_FILE` 信任）把
「注册→收验证邮件→邮箱验证→登录→试用写动作」整条链路在**真容器活体 API**上跑通——
凭据到位后只需把发信端换成真 SMTP、取信端换成 IMAP，其余不变。

**逐环实测回执（gunicorn 活体 API，`PYTHONPATH` 指向本 worktree 源码）**

```
--- 起假 SMTP（STARTTLS） + API ---
[dummy-smtp] listening on 127.0.0.1:1025 sink=/tmp/dummy_smtp.jsonl tls=on
API_READY (3s)
--- 端到端链路 ---
[1] 探活 live: HTTP 200
[dummy-smtp] captured from=<no-reply@fde18.com> to=['<trial_user_1794907386@example.com>'] bytes=725 tls=True
[2] 注册: HTTP 201 user_id=dd195364-… state=pending_email verification_email=sent
[3] 收验证邮件: 来源=本地假 SMTP 落盘 正文字节=725
[4] 取出验证令牌: wmVbiI…(43 chars)
[5] 邮箱验证: HTTP 200 registration_state=active entry=enterprise
[6] 登录: HTTP 200 access_token=eyJhbG…(336 chars) role=project_lead
[7] 试用写动作（建项目）: HTTP 201 project_id=8a754b28-98a2-4694-a6b3-5bb5ab68282c
[8] 读回校验: HTTP 200
================ 端到端结果 ================
[PASS] 注册 → 收验证邮件 → 邮箱验证 → 登录 → 试用写动作 全链通过
```

**过程中撞出并修掉的真问题（全部当场修，非绕行）**

| 撞点 | 现象 | 处置 |
|---|---|---|
| 发信通道握手 | 假服务器未广告 AUTH ⇒ `SMTPNotSupportedError: SMTP AUTH extension not supported` | ①生产码错误文案修正为「不支持必要扩展（STARTTLS/AUTH）」；②假服务器补 AUTH PLAIN/LOGIN（真实服务器均支持） |
| 邮件正文编码 | 正文含中文 ⇒ MIME base64 ⇒ 令牌取错 | e2e 脚本改用 `email` 标准库解码 MIME（真邮箱 IMAP 取件同样需要） |
| 限流闸真实生效 | 连续跑用例撞 `registration_rate_limited`（10/日/IP 实数在起作用） | e2e 前清**自己**的限流桶（`auth:register:127.0.0.1`），不削弱闸门 |
| 注册入参 | `subject_key` 须 18 位统一社会信用代码且**校验位正确**（GB 32100 校验位算法） | e2e 用算得校验位的合法代号 |
| 立项载荷 | 非模板立项须自带 `project_snapshot`（`creation_source=manual`） | e2e 补 `project_snapshot.modules[].module_key` |

**真实凭据轮与远端开闸＝OWNER 清单（未执行，见 BLOCKED）**：本机**未动**部署树
`D:/test/fde-workbench` 的 compose/容器（共享活体，跨会话资源，本轮零触碰）；
端到端跑在**独立容器＋独立测试库**（`fde_workbench_regtrial_test`）上，不与本机主栈/其他会话互锁。

---

## R5 三同步＋收口 PR

| 同步面 | 内容 | 状态 |
|---|---|---|
| CHANGELOG | 新增「注册制试用开闸轮」节（R1–R5＋测试/变异/便携版/OWNER 遗留全记） | ✅ |
| 台账 | `docs/audit/下一步实施台账-2026-11-07.md` 追加 **§14 轮次补登记** | ✅ |
| AGENTS | 红线修订＋新增红线一条＋「当前状态」行刷新 | ✅ |
| 桌面交付物 | 便携版 **r55**：`release-version.mjs bump` 三源同步（RELEASE-COUNTER 54→55＋package.json `0.3.0-r55`＋web-bridge `0.3.0-r55-web`）；asar sha256 `cb54a006895cec382ce87b60501d6f092f549490fdf1172007fe615a149b1c5e`；中文 marker 字节双证：正向 `企业自助注册`＝1／`0.3.0-r55`＝1，**旧包 r53 反向零命中**；交付目录 `release/蔡工FDE-0.3.0-便携版-r55`（493M） | ✅ |
| PR | 分支 `feat/regtrial-smtp` → push fork → PR → 四 CI job 全绿 → **人工合并（蔡工）** | 见下 |

---

## BLOCKED

见 `docs/goal-regtrial-BLOCKED.md`（OWNER 清单三项：SMTP 真凭据 / 远端公网开闸 / 真发信轮复跑）。

---

## 合并回执（2026-11-18）

| 项 | 内容 |
|---|---|
| PR | #503（`feat/regtrial-smtp` → `main`），**squash 合并＝`af8577c4`**，mergedAt 2026-11-17T17:12:59Z（授权：蔡工 2026-11-18 交互拍板「A｜授权我合并 #503」） |
| 合并前处置 | 合并前 main 已被并发线推进（#504 接单→交付贯通验证轮 → #505/#506/#507/#508）⇒ **先 rebase 到新 main**：冲突仅 `AGENTS.md` 当前状态行与 `CHANGELOG.md` 节标题各一处，双方内容**逐字并存**（我方摘要在前、上游节序在后，AGENTS 行合成一行不丢两侧），结构终扫＝两侧内容锚 1/1 命中、冲突标记清零 → 强推 `6063695f` → 重跑 CI |
| CI（rebase 后两轮） | push run `44131095987` ＝ **success**；PR run `44131103464` ＝ **success**；四 job（desktop／server-tests／secrets-scan／pseudonymization）全 success |
| squash 漏笔核验 | `git show af8577c4` 文件表 **21 个**（与合并前一致）＋八处内容锚逐项命中（SmtplibClient／resolve_channel／test_mailing_smtp／企业自助注册／本文件「R4 本机端到端」／BLOCKED／CHANGELOG 节／AGENTS 红线）⇒ **无漏笔**（照 #496→#500 家族教训执行） |
| 主树 ff 核对 | `git pull --ff-only fork main` → main＝fork/main＝`af8577c4`，**双向偏移 0 笔**；main 侧内容锚复核命中；本线三份文档（任务书／PROGRESS／BLOCKED）已在库 |
| 合并未带出的事 | 远端写操作＝**0**；**本机主栈未重建**（本线代码尚未上活体）；便携版 **r55** 在主树 `release/蔡工FDE-0.3.0-便携版-r55/`（asar `cb54a006…`）；OWNER 三项（真凭据／远端公网开闸／真发信轮）仍未执行 |
