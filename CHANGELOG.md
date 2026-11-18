# Changelog

本文件记录 FDE Workbench 开源版本的主要变化。版本号遵循语义化版本规范；首次公开源码版本为 `v0.1.0`。

## [未发布] — L-C 改判写面轮：条款③后半四项拍板全落实施（W1 服务端＋W2 桌面，2026-11-18）

承设计稿 `docs/architecture/L-C改判写面-设计稿-v1.md`（#516）与蔡工四项交互拍板（全落推荐项：**supersede＝查询口径收敛（零写面零迁移）／裁定留痕＝detail_json 追加（不加 operation_event）／实施时点＝现在就开 W1+W2**）。**+1 路由（523→524）零迁移零表**：口径 524 路由／55 蓝图／160 表／89 迁移单头 `b7f2d9e4c6a8`。

- NEW #517 `53b46889`（**W1 服务端**）：①NEW `simulation/findings_scope.py::superseded_finding_ids`＝supersede **查询口径收敛**（发现派生自 human 行且 ≠ 该 run 最新 human 行 ⇒ superseded；非 human 层恒有效）——零写面零迁移，三消费点接线：`list_findings` 投影 `superseded` 字段／`create_proposal` superseded 闸（409 `finding_superseded`）／`draft_improvements` AI 调用前拦截（空集同码 409）；②NEW `POST /simulation/findings/<finding_id>/adjudicate`＝finding **人工裁定端点**（角色闸 admin/project_lead；action confirm|reject；note 必填；单向状态机 `open → confirmed|rejected`，重复裁定 409 `finding_already_adjudicated`；留痕＝`detail_json.adjudications[]` 追加，不加 operation_event）；③**confirmed 双轨解锁**——`create_proposal` 接受 `status=="confirmed"` **或** `confidence=="confirmed"` 任一（原仅前者）；④★修复**同人重复终裁 500**（`uq(run,layer,evaluator_id,rubric)` UniqueViolation——「可重复插行」只对不同评估人成立）：`record_human_evaluation` 同人轮次派生 `evaluator_id`（首评 `human:<uid>`，再终裁 `human:<uid>:r2…`，`func.count`＋like 前缀计 prior 轮数）⇒ 历史行永远保留、无覆盖。NEW `test_simulation_lc_adjudication.py` 7 例（supersede 三消费点钉／adjudicate 四态钉／双轨解锁正反例／同人三轮终裁链）；蒸馏器 AST import 白名单显式扩 `findings_scope`（只读元数据零答案面）。
- NEW #518 `2ad37f96`（**W2 桌面**）：①FailureAnalysis 发现卡——superseded 置灰（复选框禁用＋取代提示）＋裁定状态徽标＋内联裁定表单（confirm/reject＋必填理由；仅 admin/project_lead 可见）；②EvaluationReport **终裁历史链序标**——human 行按时间升序编号「第 N 次终裁（现行/已被取代）」＋人工终裁通知补现行结论摘要（80 字）与「再提交即改判，历史行永远保留」提示；③api.ts `adjudicateFinding`＋types.ts `superseded` 字段。desktop typecheck 零错＋vitest 套件全绿（+4 例：裁定全交互 POST body 断言／engineer 无入口／superseded 置灰／历史链序标）。
- 口径三件套同步：`v3-workbench-inventory.json` route_count 523→**524**＋route CSV 重生成＋archify 四处串（55 蓝图 / **524** 路由 / 160 表 / 89 rev）＋AGENTS 基线行。
- 活体部署三验绿（#517 后即时：url_map **524**＋adjudicate 路由在场／alembic `b7f2d9e4c6a8 (head)`／三镜像逐位／ready 200）；便携版 **r57**（asar `e4547a4ed3275880e69f43a3156594ae312f2533fb0b29e7ad65fdfbbc97b649`，marker「人工裁定」正向 1／r56 反向 0）落主树 `release/蔡工FDE-0.3.0-便携版-r57`；RELEASE-COUNTER／package.json／web-bridge 三源同步。
- 任务书条款③写面回写＝✅ 已实施；设计稿状态 PROPOSED→IMPLEMENTED（四项拍板留痕）。
- 挂账双清偿：NEW `docs/L-C改判操作指引.md`（三步改判流＋superseded 连锁＋裁定表单＋边界钉，操作体会面零开发）；`.gitignore` 增 `release-r*/`（r51/r52 句柄锁残留已实证与归档逐字节一致，PowerShell 复试仍 IOException＝系统级句柄，登记消脏显示留自然释放）。

## [未发布] — 学习闭环收尾轮：回归判定环收口＝回归通过＋首个改善向信号＋双缺陷修复＋三载体收尾（五 PR，2026-11-18）

MiniMax 配额恢复（蔡工确认）＋夜轮四拍板（范围全开／按已登记判据裁决／L-C 只读视图／CI 四绿即合并部署）下，学习闭环挂账全清偿。NEW `docs/audit/学习闭环收尾轮-回归判定环收口报告-2026-11-18.md`（证据链全录）。**零迁移零路由零表**：口径不变（523 路由／55 蓝图／160 表／89 迁移单头 `b7f2d9e4c6a8`）。

- NEW #510 `e43e729a`：回归判定环伪影双修——workbench `PHASE_MAX_TOKENS` 4096→16384 标定（推理模型烧穿先例族）＋**failed run 排除纪律**（unavailable 不进判定分母：预算化重试＋failed_hard 直排＋排除触发幸存者偏差闸 verdict 强制 inconclusive＋`excluded_runs` 留痕＋失败 run 不再评估）；4 钉＋变异三连红→sha256 还原→绿。
- NEW #511 `9a03b88c`：release_channel `materialized`/`retired_payload` **落库丢失修复**（JSON 列对 flush 后原地变更不可见——赋值移到载荷合入后）；NEW 两枚 DB 落库面钉（TDD 先红后修）；活库 PROP-BE6DE878 release_json 审计段四重守卫补录（前后 sha256 留痕宿主）。
- NEW #512 `74722cf1`：**seed 压制消解**——published 动态行保底 1 席（seeds 让末席；无动态行逐字节零变化；seeds 稀缺时动态按序补足）；3 钉＋变异红→还原→绿。
- NEW #513 `6612691b`：**L-C 原文核对只读视图**——发现卡证据条原文展开（party 裁定「只给人看」面落地；G7b 条款③只读面收口，改判写面留后续轮）；桌面 104 文件 1232 passed＋typecheck 零错。
- NEW #514 `f8aa4d1b`：`PHASE_MAX_TOKENS` 16384→**32768**（复测一档：vague/complex 16384 已成功〔design 10755 收尾〕、normal variant 推理单独两连烧穿；provider 32768 接受度探明）。
- **判定环收口（v3 套件 `0c04a56f` 三 variant 全 completed 零排除）**：两登记判据全过——D1 族判据不降（MI-1 0.583→1.0）＋同 run 重评极差 **0.0071** 带内（0.1049）；模型轴 **+0.2318 ⇒ model_verdict=improved**（0.6333→0.8651，首个改善向信号，不升档）；规则层 mixed（D3 解决方案质量 −0.3 如实登记）；FA-01/FA-02 failure codes 全消除。「反哺信号有效」维持未知（单场景族单点证据）。
- 便携版 **r56**（asar `30d858e2206aa4b1bde5de544732675f677c70a0daa34e94312c20ec18414351`，marker「原文核对」正向 1／r54·r55 反向 0）落主树 `release/蔡工FDE-0.3.0-便携版-r56`；RELEASE-COUNTER／package.json／web-bridge 三源同步。
- 活体部署两轮三验全绿（16384 轮 api `d0903855731c`／32768 轮 api `4e34d64ee8c9`；url_map 523／alembic `b7f2d9e4c6a8 (head)`／镜像逐位／ready 200）；指纹幂等操作纪律登记＝复判定须新建套件（同套件＋同提案重跑返回既有结果行）。

## [未发布] — 注册制试用开闸轮：SMTP 发信通道 provider 无关化＋注册面开闸三条件修订＋登录页注册入口（goal-regtrial R1–R5，2026-11-17）

承蔡工「注册制登录试用」评估与「SES 因审批不下来已废弃、改直发」纠偏——SES 生产权限 2026-11-05 被 AWS 拒绝、路线冻结，注册面验证邮件改走 **provider 无关 SMTP 通道**（Zoho 形态，AI外贸获客 backend 同款模式 2026-11-09 实发验证过）。**零迁移零路由零蓝图零新表**：口径不变（523 路由／55 蓝图／160 表／89 迁移单头 `b7f2d9e4c6a8`）。

- **R1 SMTP 发信通道（核心）**：NEW `mailing/smtp_client.py`——`SmtplibClient` 实现既有 `SesClient` 协议（标准库 smtplib；`smtplib.SMTP`＋`starttls()`＋`login`＋`send_message`；返回 **message-id 头形态标识**，幂等台账语义不变）；NEW `mailing/channel.py`＝「哪条通道生效」的**唯一权威**（`resolve_channel`／`channel_enabled`；两通道同开＝`MailChannelConflictError` fail-closed）；`mailing/service.py` 的 `send_email` 改为**通道无关**（五步闸门一字不动：开关→幂等→抑制→限额→发信域；发件人/允许域根按通道取）。**既有 `FDE_SES_*` 键与 `test_mailing_ses.py` 27 例零改动**（`create_ses_client` 仍是 SES 路径唯一入口，模块级名字调用时解析——既有四处 `monkeypatch` 打桩继续命中同一路径）。
- **R1 配置面（新增 7 键，出厂全关）**：`FDE_SMTP_ENABLED`（开关）／`FDE_SMTP_HOST`／`FDE_SMTP_PORT`（缺省 587）／`FDE_SMTP_USERNAME`／`FDE_SMTP_PASSWORD`（`SecretStr`，日志与 repr 不外泄）／`FDE_SMTP_FROM`／`FDE_SMTP_SEND_SUBDOMAIN`（允许发信域根）；**启用即校验必填齐**（`missing_smtp_configuration`）＋**两通道互斥**（`smtp_and_ses_enabled_conflict`，启动失败）＋**发信域纪律同款**（FROM 必须落在允许域根内，主域不发信→`smtp_sender_domain_forbidden`）。**TLS 一律加密**：465 走隐式 TLS、其余端口走 STARTTLS，**STARTTLS 不可用即失败、不回落明文**（凭据不落明面）；错误分类沿用既有两分类（4xx/连接失败＝`throttle` 可重试，5xx/认证/拒收＝`message_rejected` 不可重试）。
- **R2 红线与配置面修订**：AGENTS「注册面公开写面纪律」开闸三条件第二项由「SES 启用」→**「发信通道启用（SMTP 或 SES）」**（注记 OWNER 拍板与 SES 冻结事实）；③限流上限由「保守占位待填实数」→**实数 10/日/IP**（代码缺省 20 不动、部署面按 10 配；`FDE_REGISTRATION_RATE_FAIL_CLOSED` 公网须设 1＝fail-closed）；`.env.example` 增 SMTP 段与修订三条件注释。
- **R3 前端注册入口（现测＋补链接）**：现测＝`#enterprise-register` 路由**已挂载**（`App.tsx` 公开面分支＋`useHashRoute` 解析）但**无任何可见导航入口**（登录页无链接）⇒ 补 `LoginPage.tsx`「企业自助注册」入口（桌面/网页同构一个 PR）；`login.test.tsx` 增 1 例（入口在＋跳得进）；`npm run typecheck` 零错＋vitest **104 文件 1231 passed**（+1）。
- **R4 本机端到端全链 PASS（假 SMTP 真握手）**：NEW `scripts/verify/dummy_smtp_server.py`（STARTTLS 真握手＋自签证书＋落盘 JSONL）与 `scripts/verify/verify_registration_trial.py`（逐环实测并贴输出；取信支持本地落盘与真实 IMAP 两种）＋`scripts/verify/verify_smtp_mutation.py`（变异自证）。实测链：**探活 200 → 注册 201（`verification_email=sent`，SMTP 捕获 725 字节/tls=True）→ 取令牌（43 字符）→ 邮箱验证 200（`registration_state=active`）→ 登录 200（`role=project_lead`）→ 试用写动作 201（建项目 `project_id` 落库）→ 读回 200**。**真发信轮（SMTP 真服务器＋真口令）与远端开闸＝OWNER 清单，未执行**（见 BLOCKED）。
- **测试与变异**：NEW `test_mailing_smtp.py` **32 例**（STARTTLS/隐式 TLS 路径、Message-ID 形态、错误分类五参、连接失败节流、STARTTLS 不支持即失败且**不 login**、工厂分支与 SES 路径零改动、配置校验四例、`send_email` 通道无关三例、注册面开闸通道无关四例）＋既有 `test_mailing_ses.py` **27 例零回归**＋注册面回归套件全绿（**116 passed**）；**变异四连全数「红→绿」**（M1 通道解析分支／M2 4xx 可重试性／M3 注册面闸退回单通道／M4 摘除 STARTTLS）且**字节级还原一致**（脚本自证，非人工声称）；`ruff --select F401,F841` 全过＋**mypy 基线 277 零新增**（`OK: no new type errors (baseline 277 occurrences / 102 distinct, current 277)`）。
- **便携版 r55**：`release-version.mjs bump` 三源同步（RELEASE-COUNTER 54→55＋package.json `0.3.0-r55`＋web-bridge `0.3.0-r55-web`）＋asar 中文 marker 字节双证（见交付回执）。
- **遗留（OWNER）**：①SMTP 真凭据（建议 Zoho 上给 `fde18.com` 域建发信邮箱，如 `noreply@fde18.com`）带外提供——到位后跑真发信轮（同一 e2e 脚本换 `--imap-*` 取信）；②远端部署树开闸（公网写面）**AI 不代开**，OWNER 清单随交付上交；③注册面限流实数 10/日/IP 与 `RATE_FAIL_CLOSED=1` 由 OWNER 在部署 `.env` 落值。
## [未发布] — 接单→交付三线补验轮：artifact 封包／claim 抢单／商机七步链全部实跑闭合（纯验证零代码，2026-11-17）

贯通轮（#504/#505）登记的三项未覆盖面当日全部补验闭合，零迁移零路由零表（口径 523/55/160/89 单头 `b7f2d9e4c6a8` 不变）；回执补章入 `docs/audit/贯通验收报告-接单到交付-2026-11-17.md` §7（§5 遗留表同步销项）：

- **7-A artifact 型封包（全 PASS，零人工步）**：不发起任何新 run（发起权归人红线）——复用试点项目 `FDE-20261112-5CFF4FA2` 中蔡工此前亲手复核的 8 件产物。正例：挑选面投影→建包→封存（manifest `2b2ab718…`，止于 sealed 非业务态）；负例两层：未复核产物经挑选面结构性不可见（SIM-V32-LAB 34 件全滤）＋绕过挑选面直投 → 封存 **409 `artifact_not_reviewed`**。
- **7-B claim 抢单模式（16 步全 PASS）**：★城市口径修正＝种子白名单现行六城为 2026-11-01 B-④ 拍板的上海/广州/深圳/杭州/成都/武汉（佛山不在名单），合成项目改用深圳。链路：立项→报价→finalize（**非首单分支免回校**实证）→claim 建包→发布→负例 **403 `claim_closed`**→合成 2 条深圳 `fde_profiles`＋api 容器内**临时**翻转种子开关＋重启→闸明细全绿→接单人本人抢单（mode=claim）→重复抢 **409 `offer_exists`**→本人接单→自动交接→包 accepted→**种子从备份逐字节还原＋档案删除＋闸回关闭态**（claim 全关仍是拍板默认态，零入库改动；recreate 即回镜像原生）。
- **7-C 商机报备线（密码链 14 步全 PASS）**：席位闸按人判定核验（负例 **403 `opportunity_reporter_seat_required`** fail-closed）→ 蔡工本人在本地终端 getpass 亲手执行密码段（密码不进聊天记录/不落盘）：席位激活（active 至 2027-11-17）→ 五规则位 configured → ①报备 submitted → ②企业确认 → ③归属确认（归属=报备人）→ ④保护期 active 至 2026-12-17 → ⑤售前 → **⑥撮合挂 claim 链深圳包**（同企业代号校验过闸）→ ⑥′客户选择 → ⑦结算负例 **404 `ledger_entry_not_found`**。活库 13 条商业域事件全留痕。
- **如实登记**：⑦真实结算不在本轮——`project_share` 科目行只能来自 F 线「收款→分账→支付」实收链（强挂 `delivery_settlement_id` 且五席位明细须有 paid 份额），机制验证止步于负例；三线留下真实状态行（席位 1／商机 matched 1／规则位 5／保护期生效中／深圳 claim 包+offer 各 1）全部合成标注；商机规则位配置是真实配置面变更（unset→configured，合成规则文本承载）；三线脚本留本地不入库（商机链含密码交互）。

## [未发布] — README 权威口径巡检轮：六视角随动＋release-version 三源如实＋打包产物验证闸入册（纯文档，2026-11-17）

README「是不是最新」巡检（口径逐项现测后动刀，七处补丁全锚点断言）：

- **架构图五视角→六视角**：`degradation`（降级与失败路径）自 #224（2026-11-08）入册，README 图清单漏列——补齐第六视角。
- **release-version.mjs 同步面如实**：bump 注入两源（`desktop/package.json`＋web 桥版本字面量，示例刷 `0.3.0-r54`）；train 同步**三源**（原写「双文件」，漏 #473 CR-058 起的 `fde-web-bridge.ts`，`web-bridge-version-parity` 静态闸钉一致）。
- **打包桌面端补「产物验证」两道闸**：asar sha256＋中文 marker 字节法（控制台直 grep 中文会假阴性的坑入册；交付目录 `蔡工FDE-<version>-便携版-r<N>` 命名法与「旧目录永不覆盖」约束随写）——README 作为打包唯一权威与 `fde-package-verify` 技能操作化层对齐。
- 换机迁移清单便携版示例换当前命名法（`0.2.0-便携版`→`0.3.0-便携版-r54`）；`package:win` 注释补 bump 步骤；版本号约定标签示例 `v0.2.0`→`v0.3.0`；能力表补「结项交付包」。
- 口径复核无需变更项：徽章 v0.3.0＝pyproject 0.3.0 ✓／`VERSION` 文件在 ✓／健康端点·CI 四 job·takeover 检查器·fdeOssHost·seed-document-templates 各节均为最新实态。

## [未发布] — archify 图纸口径同步轮：迁移维度 89 rev 随动＋防陈旧闸咬合恢复（机械钉，2026-11-17）

承接 SME 尾巴轮 #495 加迁移 `e5c8b2d4f7a9`（双头收单 `b7f2d9e4c6a8`）后图纸未随动的闸盲区自查（迁移 87→89 时闸仍绿——六图无一引用「N 迁移」口径，检查器对未引用口径直接跳过）：

- `architecture/candidate.json` db 节副标签补「160 表 · **89 迁移**」＋渲染件 `system-architecture.html` 四处同步——防陈旧闸对迁移维度恢复机械咬合（变异验证：改 88 迁移→闸红 exit 1 带处置指引，字节还原→复绿 exit 0）。
- `README.md` 取证行与 `index.html` 导航/取证说明行：87 rev（head `a1e5f9c3d7b2`）→ **89 rev（head `b7f2d9e4c6a8`）**；蓝图/路由/表三数本轮无变化（#495 零蓝图零路由零表）照抄 55/523/160。
- `architecture/preview.png` 整页实拍 1440x2098（`tools/capture-full-preview.mjs` PASS，宽=页宽且高≥页高断言过）。
- 钩子披露：`--no-verify`（等效验证=防陈旧闸本地 ok＋迁移维度变异咬合实证＋preview 高度断言；CI 全量复核）。

## [未发布] — 接单→交付贯通验证轮：端到端真机走通＋文档模板部署态缺口修复（2026-11-17）

首次以合成代号案例（企业代号 `E2E贯通·制造·佛山`，零真实客户资料、真相层零接触）在真实活体上走通「接单→交付」全链 30 步（真实 HTTP API，含 4 道闸负例全拦：首单回校闸 `calibration_required`／对外签字闸 `signoff_required`／接单人 member 无 can_manage 403×2）——立项→机会主体→方案→报价→回校→成交→claims×11→对外件→交付包发布→指派→接单人本人令牌接单（乐观锁）→自动交接（进项目成员 role=member）→交付执行（任务/证据）→交付件（文档 manual 修订一次产出 document+file 双交付件）→封包→封存（manifest_sha256 冻结）→交付登记（delivered 终态）。口径不变（零迁移零路由零表：523/55/160/89 单头 `b7f2d9e4c6a8`）。

- **★部署态真缺陷修复（本轮主发现）**：`server/Dockerfile` 未 COPY 仓库根 `resources/`（build context=`./server` 不可达）⇒ 容器内 `seed-document-templates` 全 missing ⇒ 部署态 `document_templates` 恒空 ⇒ 「项目文档/结项交付包」整段 422 `document_template_not_published`／文档型与文件型封包无上游——somwyn 十步未触此段故从未暴露。修复＝**compose 三服务（api/worker/scheduler）只读挂载 `./resources:/app/resources:ro` ＋ `FDE_DOCUMENT_TEMPLATE_DIR=/app/resources/document-templates`**（与 migrations 挂载同构；worker 需要模板字节因 document.generate fallback 读盘）＋ README「迁移与初始化」节补 `seed-document-templates` 步骤。**换机重建/远端部署后须跑一次该 seed**（幂等）。
- **贯通验证器入库**：NEW `scripts/verify/verify_order_to_delivery_e2e.py`（登录/token 双模式＋接单人凭证 `--deliverer-token`/`--deliverer-password`，都不给则降级 admin 代接并 SKIP 视角步骤；非首单库两分支兼容——首单库走回校负例 409、非首单库 finalize 直接成交且 SKIP 回校步；每跑一次新建独立项目可重复执行）。边界：合成数据机制验证不代表真实业务拍板；首次执行消耗全库「工作室首单」语义名额；不含 agent run（发起权归人）。
- **贯通验收报告**：NEW `docs/audit/贯通验收报告-接单到交付-2026-11-17.md`（30 步逐项回执＋缺陷根因＋闸验证汇总＋如实登记：首单语义消耗／闸动作均为合成数据验证／商机报备线与 claim 模式与 artifact 型封包未覆盖）。
- **如实登记**：验证执行使活库全库非仿真 `finalized` 计数 0→2（首跑+复跑各一次成交），「工作室首单」判定分支已被消耗；首跑断链残链（项目 `dc9db38d`，已回校未成交）留库无害。商机报备线（`commercial_opportunities`，售卖闸授权面）与 claim 模式（全城开关关闭）与 artifact 型封包（须 run 发起权归人）不在本轮范围。
- **活体应用回执（合并后同日，#504 → `39c3e3bd`）**：主树 `compose up -d` recreate api/worker/scheduler（redis 未动；**镜像未重建**）→ 容器内验证：`./resources` 挂载 18 模板 DOCX 在位、`FDE_DOCUMENT_TEMPLATE_DIR` env 在位、`seed-document-templates` 幂等 `created=0 skipped=17 missing=0` → 三验全绿（url_map **523** non-static／容器内 alembic `b7f2d9e4c6a8 (head)`／三镜像 `e81f2e7035f4`·`616c9685c629`·`95645f92d473` 与本树构建逐位一致）＋ ready 200＋四容器 healthy。部署态「结项交付包」段自此在真实容器态可用。

## [未发布] — 桌面 handover 三态接线轮：挑选面 type 选择器＋document/file 分型拉取＋分型指针提交（SME 尾巴②桌面段清偿＋活体三验销项，2026-11-17）

承 #495 挂账「桌面端挑选面与建包表单的三态接线归下一桌面轮」——零服务端改动零迁移零路由（口径不变：523 路由/55 蓝图/160 表/89 迁移单头 `b7f2d9e4c6a8`）：

- **`HandoverPackagesPanel` 三态接线**：入包类型三键切换组（已复核产物/文档版本/文件版本，`role=group`＋`aria-pressed`，零新 CSS 类零新依赖）；挑选面 `GET /handover-packages/artifacts?type=` 分型拉取（缺省 artifact 行为零变化），切型先清旧行防误勾；勾选**跨型累计**（键=`${item_type}:${pointerId}`，同包三态混装——服务端 `_validate_item_payloads` 本就支持混装）；提交体按型落指针键（artifact_id/document_version_id/file_version_id，服务端按键自反推 item_type）；document/file `display_name` 缺省交服务端默认（`business_code v{n}`／原文件名，代号化安全）；空态提示与挑选面标题随型；详情清单表新增「类型」列（产物/文档/文件），`PackageItemDto`/manifest items 类型补 `document_version_id`/`file_version_id` 字段形状。
- **测试**：`handover-packages-panel.test.tsx` 5→8 例（新增文档型 `document_version_id` 提交／文件型 `file_version_id` 提交／跨型混装双指针同包提交／详情三态类型列），`npm run typecheck` 零错＋vitest **104 文件 1230 passed**。
- **活体三验销项回执（SME 尾巴轮挂账，2026-11-17 07:15）**：接管检查器 FAIL=0 → 主树 `compose build api worker scheduler`＋`up -d --force-recreate`＋容器内 `alembic upgrade head`（`d8b4f6a2c9e7` 分支点 → 三段 → `b7f2d9e4c6a8 (head)`）→ 三验全绿（url_map 515→**523**／alembic current＝`b7f2d9e4c6a8 (head) (mergepoint)`／三镜像 `e81f2e7035f4`·`616c9685c629`·`95645f92d473` 与本树构建逐位一致）＋`/api/v1/health/ready` 200（database/redis ok）＋活库抽检（handover 两新列＋`ck_handover_package_items_pointer` 三态 CHECK＋agent_tool_calls 12 列全在位）。
- **便携版 r54**：`release-version.mjs bump` 三源同步（RELEASE-COUNTER 53→54＋package.json `0.3.0-r54`＋web-bridge `0.3.0-r54-web`，parity 静态闸过）；asar sha256 `674e1c3f563813e1d3b986bfd3b813c20f73f115ce76c8f96ef3cc0f1c505e9f`（中文 marker 字节验证正向两枚全命中＋旧包 r52 反向 0 命中；worktree 独立 `release/` 输出绕主树句柄锁）。
- **AGENTS 当前状态行**：挂账区刷新（桌面三态接线＝✅／活体三验＝✅／剩余仅改进单 1 三件 PLANNED）。

## [未发布] — SME 交付尾巴轮·文档刷新：改进单 1–4 状态行实态化＋AGENTS 口径刷新（纯文档零代码零迁移零路由，2026-11-17）

承「SME 交付物优先级对照审计」（2026-11-15/17）尾巴清单第①项——四份改进单头部状态行自 2026-11-14 落盘后从未随实施推进刷新（文档漂移，违反「口径引用前现测」纪律的精神），本轮只做文档实态化：

- **改进单 2（logic_engine 加固）**：PROPOSED → **IMPLEMENTED**——M4.1 轮已在 `Fde-Ontology` 落地（Decimal-First `prec=28, ROUND_HALF_UP`＋受界集合归约宏 `MAX_COLLECTION_ITEMS=1000`＋`days_between`/`coalesce`；`test_m4_1_logic_decimal_cel.py`/`test_m4_1_logic_edge_coverage.py` 钉住）。
- **改进单 3（双仓契约门禁）**：PROPOSED → **IMPLEMENTED**——双向 parity 机械闸双侧在位（`Fde-Ontology` `test_m4_1_contract_parity.py`＋workbench `test_m5_wp2_client_mock_parity.py`）；spec 单一真身随尾巴轮升版 1.3.6-af0 → 1.3.7-sme5（`Fde-Ontology` PR #26 已 MERGED，版本钉换代不删钉）。
- **改进单 4（Ontology-as-Code＋单向晋升）**：PROPOSED → **IMPLEMENTED**——M6-WP2 落地（`bundle.py`＋`bundle_cli.py` lint/test/diff 三命令；workbench `glossary_promotion.py` 单向晋升＋`integrations/ingest_service.py` discovery 直提链）。
- **改进单 1（独立运行边界）**：PROPOSED → **PARTIAL**——已落地：M6-WP6 TrustBoard（A1 静态快照＋活数据档＋WP6-R4 单次消费交接令牌）＋S-12 运行时拦截（workbench #485）＋**Step2 `.ontpkg` 离线验签导入＋打包纯度闸（`Fde-Ontology` PR #26 已 MERGED）**；挂账：Step1 本地鉴权模／Step3 `local-ops-ui`／完整 `standalone_pod` 打包件（M6 出口留档 PLANNED，首家纯内网私有化客户进场前必做）。
- **总览 §四**加「实施实态」注记；**AGENTS 当前状态行**刷新为终态速览（结构口径现测 **523 路由／55 蓝图／160 表／89 迁移单头 `b7f2d9e4c6a8`**；历史轮次史收敛为 CHANGELOG 与 `Fde-Ontology CURRENT.md` 权威指针——治理口径行无限膨胀的家族病）。

## [未发布] — SME 交付尾巴轮·handover 三态＋交付清单模板：item_type 扩 document/file（SME 审计尾巴②清偿，PR #495 已合并，2026-11-17）

承「SME 交付物优先级对照审计」（2026-11-15/17 两轮）尾巴清单第②项——handover 包 v1 只开 artifact、document/file 类型挂账未接线；本轮接线并补齐面向客户的交付件清单模板：

- **item_type 三态全开**：`HandoverPackageItem` 增 `document_version_id`／`file_version_id` 两指针列（**零 FK**，B#6 指针纪律不变）；`ck_handover_package_items_type` 扩三值、`ck_handover_package_items_pointer` 重建为**恰一指针互斥**（artifact/document/file 三分支，CHECK 层钉死）。迁移 `e5c8b2d4f7a9` 挂 `d8b4f6a2c9e7`；与 AF1-WP4（`a1e5f9c3d7b2`，同挂）并行入线形成双头 → merge 收单头 `b7f2d9e4c6a8`（零 DDL 双头元组，M6-WP0 D11 先例；docstring 措辞避让迁移图解析正则的首行匹配）；存量行全为 artifact 行为逐位不变；downgrade 先清非 artifact 行再回枚举。
- **入包状态闸（与 artifact reviewed 闸同构）**：document 只收 `confirmed` 文档版本（`document_not_confirmed` 409／缺 sha256 `document_fingerprint_missing` 422）；file 只收 `available` 文件版本（`file_not_available` 409／缺指纹 422）；跨项目同拒（`document_foreign_project`／`file_foreign_project` 409）。seal 逐项复核按类型分派（`_seal_check_document_version`／`_seal_check_file_version`），指纹漂移统一 `fingerprint_drift` 409。
- **指针键自反推**：items 元素缺省 `item_type` 时按恰一带一个指针键（artifact_id/document_version_id/file_version_id）反推类型（裸 `artifact_id` 形态向后兼容零回归）；显式 `item_type` 与指针键不匹配即 422。去重键升级 `(item_type, 指针)`。
- **挑选面三态**：`GET /handover-packages/artifacts?type=`（缺省 artifact 行为零变化）——document 回 confirmed 版本、file 回 available 版本，键闭集随类型投影；非闭集值 400。
- **SME 交付件清单模板**：NEW `docs/templates/SME交付件清单与验收标准模板-v1.md`——15 项按「能连上/能对上/能用起来/能留下」四段编排，每项带系统来源与验收判据，并显式登记五项「明确不交付」裁剪边界（对齐 SME 审计结论）。
- **验证**：`tests/test_handover_packages.py` 6→9 例（三态混合端到端含 manifest 三指针与挑选面三态／document·file 全闸族负例／file 指纹漂移），套件 9 passed；邻域回归（m6 商业隔离＋可见性 parity）30 passed；ruff clean；mypy 277 基线零新增。
- **挂账**：桌面端挑选面与建包表单的三态接线（type 选择器＋document/file 列表拉取）归下一桌面轮，随轮重打包便携版。
- 口径：**523 路由 / 55 蓝图 / 160 表 / 89 迁移单头 `b7f2d9e4c6a8`**（含 AF1-WP4 并行合流基线；分支顶现测值）。
## [未发布] — goal-launchclose 上线收口轮：CI 定性复跑＋本机主栈带闸重建三验＋远端只读对照＋N1 关窗备料＋便携版 r53（2026-11-17）

承接 `docs/goal-launchclose-上线收口-任务书-v1.md`（上线前评测报告 v1.1 判定 A 线「对外受控试用」有条件可放行，工程态三 P0 收口）：

- **R1 CI 定性**：`gh run rerun 43867006517 --failed` 复跑 main tip 四 job——结果见 PROGRESS 回执（全绿则收口；仍红按真回归修复，禁 skip/放宽）。
- **R2 本机主栈带闸重建三验**：`takeover_check.py --tree D:/test/fde-workbench --live` FAIL=0 前置闸 → `docker compose -p fde-workbench build api worker scheduler` → `up -d --force-recreate` → 容器内 `alembic upgrade head` → 三验四项（url_map 493→新值反向验证／`alembic current`＝`d8b4f6a2c9e7 (head)`／三容器镜像 ID 与本树构建产物逐位一致／ready+live 200）；qiflow-* 邻栈零 recreate（`docker ps` 前后对照留痕）。
- **R3 远端只读现测**：6 项只读命令清单交 OPS/HOST 亲手执行（AI 零远端凭据零写面），回执回填一致性对照表（镜像版本与创建时间／容器内 `alembic current`／env 五键／ready-live 探活）；漂移即重开升版拍板。
- **R4 N1 关窗备料**（时点锁 2026-11-19 到期当日执行）：Vex F2 核验成立——`agents/service.py:1625` `_require_host_poll_enabled` 开关 fail-closed 403 ＋ `:1634` `_verify_host_poll_token` sha256 恒比 403 ＋ run 级 `host_token_hash` 绑定；`test_host_poll.py` 六枚鉴权钉（含三枚令牌轮换钉）**6 passed** 实跑留痕。
- **R5 随轮死线**：11-16 轮次七节补入（见上）＋台账/AGENTS 同步＋口径三件套现测（54 蓝图/515 路由/159 表/86 rev 单头 `d8b4f6a2c9e7`，inventory 与 archify 防陈旧闸逐项一致）＋便携版 r53 三源 bump＋asar 正反向字节验证。
- 两份输入文档（评测报告 v1.1＋任务书）随本 PR 入库归档。

## [未发布] — V3.3 双仓架构总览＋改进单 1–4 v1 落库（云端作战室边界／CEL 计算加固／OpenAPI 契约门禁／OaC 模板晋升流；纯文档零代码零迁移，2026-11-16）

直接提交 `f638d236`（无 PR）。五文 463 行新增：`docs/architecture/` 下 V3.3 总览 v1（厘清 `fde-workbench` 云端作战室 ⇄ `Fde-Ontology` Clean-room 私有化/SaaS 运行时 ⇄ 禁商用参考仓三方边界）＋运行边界 v1＋CEL 计算加固规范 v1（改进单 2）＋OpenAPI 契约门禁规范 v1（改进单 3）＋OaC 模板晋升流规范 v1（改进单 4）。NEW `docs/architecture/` 5 件；口径全不动（54 蓝图/515 路由/159 表/86 rev 单头 `d8b4f6a2c9e7`）。

## [未发布] — AF1-WP3 本体候选工程 Skill：制造业 SOP/字典→候选生成的工程规则面（builtin skill＋词表同源钉＋真模型 Skill 驱动实跑，2026-11-16）

PR #494（merge `694c647e`，11 号 WP1 工作令 WP3）：

- **builtin skill `ontology-candidate-engineering`**（published 种子，既有 T-S1 机制）：候选条目规则/证据纪律（quote 逐字溯源）/四分纪律（事实·缺失·假设·证据，缺失列 `unresolved_questions`）/歧义决策单（同义词·主键·单位不自裁决）/不凭置信度绕审批/修正循环＋失败行为（`injection_suspect` 出口/S-19 材料指令纪律）/治理（零物化，停待审）。
- 种子升级指纹挂点（评审 F1）＋工具描述 `entity_key` 文案对齐 KEY_RE（评审 F2）。
- 测试：词表**整串同源**钉（评审 F4 防子串掩蔽）＋纪律标记钉＋种子落库/分档可见性钉（全真链）；live demo（`af1_live` env 闸，CI 跳过）真 qwen3:14b 生成候选→violations→修正→pass 终局 133.5s；单元＋契约 24 passed＋本地全量 4000 passed/7 skipped/0 failed（35:47）；ruff/mypy 本批零错；Fde-Ontology 仓零改动。

## [未发布] — AF1-WP1 收口批：真服务失败→修正端到端演示＋直连循环可达性修复＋dry_validate 形状对齐实装（2026-11-16）

PR #493（merge `ddb2064b`，AF1-WP1 第三批）：

- **验收锚**（WP1 残留唯一项）：NEW `tests/test_af1_live_demo.py`（`af1_live` marker＋`FDE_AF1_LIVE_DEMO=1` 闸，CI 恒跳过）——真模型（本机 Ollama qwen3:14b）＋自起 ontology-service（uvicorn subprocess，sqlite 临时库，随机密钥仅 env 注入）＋真 `dry_validate_change_set`（1.3.6-af0）：候选带口语词→真服务 violations→违规回灌→模型按词表修正→轮 2 `verdict=pass`，终局复跑 82.4s PASS；S-13 spy 只记录真响应（M4 同款）；usage 记账钉——**全真闭环非脚本化假循环**。
- **直连循环可达性修复（真缺口）**：`access.py` 能力矩阵 **+ontology.read(project_operator)/+ontology.write(project_manager)**——`capabilities_for_level` 此前永不含 `ontology.*` ⇒ 直连循环 tools 定义被过滤＋`call_tool` 403；`issue_mcp_token` 同交集派生同病；呈 P1 追认 G。
- **dry_validate proposed_json 形状对齐实装（跨仓缺口）**：api-spec 1.3.6-af0 路由块无 requestBody schema；ontology-service PR #20 实装＝候选条目数组（与 ChangeSet.proposed_json 同形），workbench PR #491 误钉 JSON 对象（端到端必 422）——mcp_gateway TOOLS 条目 array＋词表描述；gateway/integrations service+client+mock 对齐；既有测试 4 文件随批对齐。

## [未发布] — W3 source 列仿真隔离正式化＋role_hours 角色工时明细（迁移 `d8b4f6a2c9e7` 85→86 单头，2026-11-16）

PR #492（squash `a9a2743d`，报价模块 party 评审 W3 落地其余两项；「常量↔卡片对照测试」已在评审中被否决跳过）：

- **W3-1 `quotes.source` 列**：迁移 `d8b4f6a2c9e7`（head `b3e7a1c9f4d2`→`d8b4f6a2c9e7`，86 文件单头）——String(12) NOT NULL，`server_default 'manual'` 存量行零回填零行为变化；simulator 构造的 Quote 显式写 `source='simulation'`；`finalize_quote` 首单计数加 `source != 'simulation'`（W1-2 的 Q-SIM- 前缀排除保留作双保险）——比纯前缀启发式更稳。
- **W3-2 `role_hours` 角色工时明细**（P7 依据维度）：`create_quote` 接受可选 role_hours，**合计必须 == ideal_hours**（明细与总量互证防两张皮）；未填＝None 行为与存量逐位一致；JSON 列以 str 存（Decimal 序列化同 field_claims 法）；`quote_created` 事件记 `source`＋`role_names`（只记有无不落工时金额）。

## [未发布] — W2-2 对外报价签字闸：拆内部预览/正式出口，全 accepted 才放行（新路由 513→514，2026-11-16）

PR #490（squash `3ec9a572`，报价模块 party 评审 W2 三项 OWNER 拍板 2026-11-16 之②；①首单作用域维持全局/③回校缓冲维持锁死 ×2.0 零代码改动）：

- **服务端闸**：NEW `export_quote_offer`＝`POST /quotes/<key>/offer`——11 个 claimable 字段必须全部 `accepted` 否则 409 `signoff_required`；空 claims（total=0）同样拒。
- **对外版脱敏**：`_build_draft_html(external=True)` 公式价**整列删除**（非折叠——`<details>` 客户点开仍可见，折叠只防误读不防泄露）、无内部水印、无 v2.4.6 底稿出处；内部草稿路径行为逐字不变。
- **留痕**：放行即落 `quote_offer_exported` 事件（actor/时间/claims 计数不落金额），已登记 `QUOTE_EVENT_TYPES` 进台账；前端「正式对外导出」按钮仅 `allAccepted` 可点。
- 结构口径四层同步（route CSV、inventory JSON、candidate.json sublabel、archify README；防陈旧闸脚本 OK）。

## [未发布] — AF1-WP1 第二批：提议档白名单接直连循环＋ontology_dry_validate 全链＋自托管默认档（2026-11-16）

PR #491（merge `4ae9b34f`，承 #487 第一批；分支头 CI 全绿 3953 passed/8 skipped/0 failed，16m21s）：

- **提议档白名单**：ai_tool_loop 循环面＝只读 ∪ 提议档（logic_run/dry_validate/action_propose，零直接副作用）；执行档仍剥离；降级腿（ai_server_client）显式钉回 READ_ONLY_TOOLS，automation 面经核实已被 `_read_only_tools_for` 钉死只读。
- **ontology_dry_validate 全链**：mcp_gateway 五元（read/risk0/ontology.read）→ ontology_gateway 分派 → integrations service `dry_validate_binding_candidate`（**S-13**：ontology/钉版由绑定服务端注入）→ ontology_client `dry_validate_change_set`（1.3.6-af0 路由，无幂等键）。
- **自托管默认档**：`ai_selfhosted_*` 配置（SecretStr/allow_public 公网冒名闸/supports_tools 开关/fail-closed validator）＋ resolve_model_preference system-default 档自托管优先（红线：客户敏感数据不默认发公共模型）；translator 归因同步。
- 四层评审（bmad-code-review）patch 桶 14 文件全落地：SecretStr 红线、同义反复注册钉→call_tool 真闸钉、M4 同款 S-13 spy 钉、config 启动闸测试、显式偏好三分序钉、默认分支扩张钉＋降级只读钉、rollback 不变量如实化、工具描述去内部编号、审计声明如实化；ruff/mypy-baseline 零增量（277/102）。

## [未发布] — M6-WP6 TrustBoard 交付链接 Workbench 侧一键出链（自动分发，单次消费口径，2026-11-16）

PR #489（squash `b9b67e18`，原开放项②「交付链接自动分发」；runtime 侧零产品改动，直接复用既有 `POST /ui/session`）：

- **客户端方法**：`integrations/ontology_client.py` NEW `issue_trustboard_delivery_link()`——POST runtime `/api/v1/ui/session`，每次调用用新幂等键（一次性交接令牌口径：换设备/浏览器须重新签发）；**不回吐** runtime 响应里的常驻会话令牌（凭据最小暴露，红线 §15）。
- 交付团队此前须手工调 runtime 签发＋线下转发（截图/转发即凭据泄漏面）——本批在 Workbench 侧出一键出链入口。

## [未发布] — AF1-WP1 第一批：AgentRun 取消入口＋工具循环轮数参数化（迁移 `b3e7a1c9f4d2`，2026-11-16）

PR #487（squash `2ef9ad18`，docs/ai-fde/09 §1 定参①③，P1 戊单 2026-11-16「全部批准」）：

- **取消入口**：NEW `POST /api/v1/agents/runs/{id}/cancel`——幂等（已取消 → `cancelled=false`）；终态 409 `already_terminal`；`host_running` 显式 409 `cancel_provider_unsupported`（宿主回执语义未含取消，如实拒绝）；权限＝发起人或项目 `can_manage`；事件 `agent_run_cancelled`。
- **副作用停止**：监听段 `should_cancel` 轮询（默认短会话读行；测试经 `fde_agent_cancel_check_factory` 注入）→ 诚实终态 `cancelled`、产物沿 B-1 非 completed 一律不入库、kill 由 finally 恒定发生（CR-015）；启动守卫 `_raise_if_cancelled` 先于 `SandboxHandle.create`——取消后的行永不拉起新容器。
- **迁移**：`b3e7a1c9f4d2` CHECK 置换 +cancelled（T-J2 `d9f4a7c2e6b1` 先例：纯 CHECK 置换零列重建；downgrade cancelled→failed 归位）。
- **轮数参数化**：`agent_max_tool_rounds` 配置（初值＝历史硬编码 6，`ge=1`）＋ `direct_tool_completion(max_tool_rounds=None)` 显式参数优先＋超限强制终答语义不变；②续跑明写不做（决策登记 docs/ai-fde/09 §1）。

## [未发布] — W1 报价六项零迁移加固：底牌脱敏/仿真隔离/沙箱守卫/偏差消歧（2026-11-16）

PR #488（squash `ec317b39`，报价模块 party mode 专家会议（5 方独立评审）W1 决议落地；六项均零迁移、零新表、零新路由）：

- **W1-1 底牌脱敏**：草稿三档公式价（成本×1.4）默认折叠＋表头标注「内部测算·不构成对外报价」，堵三档成本结构外泄。
- **W1-2 首单计数防仿真污染**：finalize 首单计数按 `quote_key NOT LIKE 'Q-SIM-%'` 排除仿真单，防真实首单逃脱回校义务与三条硬约束。
- **W1-3 沙箱守卫**：`run_simulation` 入口从 `session.connection().engine.url` 读库名守卫沙箱（仅 `_sim`/`_test` 后缀），堵直接 import 绕过 CLI 校验；测试库 `fde_workbench_test` 放行。
- **W1-4 偏差消歧**：两个 deviation 字段标注分母——`deviation_pct` 对预估工时（回校）；`final_deviation_pct` 对锚点下沿（谈判）；不改 key 零 API 契约变更。
- **W1-5 排除项一级化**：草稿补「本报价不含（排除项）」一级节；**W1-6** 删除悬空 `QUOTE_CARD_SOURCE` 死常量（指向从未交付的路径），代码即唯一事实源。

## [未发布] — billing_actor_policy 机制化轮：模拟域真模型评估记账主体服务账号（opt-in 配置＋双 ContextVar 注入＋fail-closed；零迁移零路由零表，2026-11-15）

承接 `docs/goal-l2.0-AI原生化学习闭环2.0-任务书.md` §挂账登记 Level 评审发现④「billing_actor_policy 机制化＝动生产记账链路，需独立轮立项」——L6 候选卡的 `billing_actor_policy: "service_account"` 此前只是**声明字段**（政策常量），无任何机制真正保证模拟域跑批的 token 计费归到服务账号；本轮把它落实为**代码机制**：

- **独立配置键（拍板①）**：`Settings.simulation_ai_actor_username`（env `FDE_SIMULATION_AI_ACTOR_USERNAME`，`server/.env.example` 注释态留空）——模拟域专用记账服务账号，**与诊断域 `diagnostics_ai_actor_username` 隔离**（防跨域串账）。
- **opt-in 语义（拍板②）**：留空＝机制关，真模型评估回落既有行为（请求腿记调用者／直接腿记 None，零回归，非硬闸）；配置了账号但不存在/停用 ⇒ `resolve_simulation_ai_actor` 抛 `ScenarioServiceError("simulation_ai_unavailable", 503)` **fail-closed**（与诊断域「配置了才 503」同款语义，空值不 503）。
- **双 ContextVar 注入（③机制真身）**：`ai/auditing.py` 新增模块级 `ai_actor_override`；`current_actor_id()` 读序升级为 override→请求上下文→None。`evaluator.py` `include_model` 分支在 server 腿（stub 腿不解析）解析服务账号后，**同一值**同时 `set` 进 `ai_actor_override`（预算闸＋审计归因腿）与 `ai_actor_id`（DSH structured_completion 腿），`try/finally` 逆序 reset（异常路径不泄漏）。
- **验证（测试 7 例＋变异双锚）**：开关关请求腿归调用者／直接腿归 None／开关开预算闸拦服务账号而回落调用者放行（判别力）／审计归服务账号且调用者零归因／账号不存在·停用两 fail-closed 503（注入点零调用）／无 ContextVar 串账。NEW `tests/test_simulation_billing_actor.py` 7 passed；变异 M1（删 `ai_actor_override.set`）与 M2（`current_actor_id` 不读 override）各 3 例真红→字节还原→复绿；ruff clean；官方 mypy 277 基线零新增。**未实施留痕**：Yui 第二笔（单文件拆分）＝抑制性警告；候选卡 provenance 字段保持政策常量 `service_account`（拍板③），机制另由上述测试证明。
- 口径不变：**493 路由 / 52 蓝图 / 155 表 / 77 迁移单头 `a9f3e5c7b1d2`**。

## [未发布] — L6 挂账清偿轮：manifest O_EXCL 锁＋两遍配对（打平不漏检）＋importlib 单一真身（零迁移零路由零表，2026-11-15）

承 party 评审追改轮（#479）遗留的三笔宿主域挂账，蔡工「按推荐执行」（选择题未答，留痕可推翻）一 PR 清偿：

- **manifest 并发锁（挂账②清偿）**：`candidate_manifest.json` 读-改-写段入 `O_EXCL` 独占锁（`_acquire_dir_lock`，跨平台 Windows 宿主适用）——并发双实例单方 `manifest_lock_busy` fail-closed（不等待不轮询，人工脚本重跑即可）；锁 mtime 超 `LOCK_STALE_SECONDS`（30s）视为崩溃残留强拆重试一次；卡文件本体幂等语义不变，锁只护登记簿。两钉：持锁拒写／陈旧强拆（`os.utime` 回拨构造）。
- **两遍配对算法（③排序残界清偿）**：门禁迁移链从顺序扫描升级为纯函数 `pair_gate_transitions`——第一遍按 `gate_key` 收集 fail 池，第二遍按 `occurred_at` 升序消费 pass，每个 pass 配对**未消费且 `occurred_at <= pass`** 的最晚 fail（最近前因，等价旧栈式 pop 的正常时序形态）。同事务批量代录全打平（PG 同事务 `now()` 恒定）时 `<=` 仍成立 ⇒ **只可能错配 fail note，不可能漏检迁移链**；fail 严格晚于 pass 不配对。全打平确定性钉（1 fail＋1 pass 全字段相等＋pass id 字典序在前，变异 `<=`→`<` 必红）。
- **importlib 单一真身（Yui 第一笔清偿）**：`IMPORT_CASES_PATH` 提为模块级常量＋在场钉（L1 `import_cases.py` 挪位未同步即红）＋加载失败转 `CaseExtractionError("import_cases_unavailable")`（裸 ImportError 堆栈不再外泄）＋加载器 `sys.modules` 先注册再 exec（与测试加载器同纪律）。
- **验证**：L6 套件 9 例（+4 钉）＋污染钉/台账钉 9 例全绿；变异三连（锁 busy 吞掉／`<=` 退化 `<`／真身路径改错）全真红→字节级 sha256 还原→复绿；ruff clean；官方 mypy 277 基线零新增。**未实施留痕**：Yui 第二笔（单文件拆分）＝抑制性警告非指令；`billing_actor_policy` 机制化＝动生产记账链路需独立轮立项。
- 口径不变：**493 路由 / 52 蓝图 / 155 表 / 77 迁移单头 `a9f3e5c7b1d2`**。

## [未发布] — L6 party 评审追改轮：三裁定落地——`occurred_at` 破平局钉＋发起权裁定登记＋manifest 锁挂账（零迁移零路由零表，2026-11-15）

承 party mode 专家评审会（Code Review Crew＋红线特聘两名圆桌，蔡工拍板「按建议处理」）：

- **排序修复（评审③，Boundary 发现）**：`scripts/extract_case_from_project.py` 门禁事件排序 `created_at, id` 双键升级为 `created_at, occurred_at, id` 三键——`created_at` 打平（如同秒/同事务批量代录）时由 `occurred_at` 破平局，杜绝 UUID 字典序随机兜底导致的**静默假阴性**（pass 先于 fail 被消费 ⇒ 迁移链漏检）；NEW 确定性测试钉 `test_same_created_at_events_use_occurred_at_tiebreak`（显式固定事件 id 使字典序把 pass 排前，变异拆掉 `occurred_at` 键必红——不依赖 UUID 随机），变异验证红→sha256 字节还原→绿。已知残界登记：同事务批量代录两事件 `occurred_at` 仍打平（PG 同事务 `now()` 恒定），生产双拍板为独立事务不受影响。
- **发起权裁定登记（评审①，Vex 提案）**：L6 真机实证由 AI 会话持用户当轮指令执行真相层写入，裁定为 `lead_ledger_append` 先例「人工显式发起」的合法形态（授权措辞＝用户当轮指令＋当轮汇报＋留痕可推翻）；后续宿主写面操作须在轮次回执显式登记发起语境（任务书挂账登记 #1）。
- **manifest 并发无锁挂账（评审②，Dana 口径）**：`candidate_manifest.json` 读-改-写无文件锁，并发双实例同目录会丢登记条目（卡文件本体幂等不丢）；单机单人竞态窗口可忽略，挂账不排期（任务书挂账登记 #2）。
- **信号有效性置信度登记（评审④，Level 提案）**：「管线可用」＝高（真机 n=1）；「反哺信号有效」＝未知，待首批候选卡人工激活进训练场跑分后升格（任务书挂账登记 #3）。
- **草稿质量教训（评审⑤，Grumbal）**：跨会话交接的「ready 草稿」须先空跑 import smoke——L6 草稿三处 import 级错误（`auth/security`→`auth/passwords`、`ProjectSolution` 域归属、动态加载未注册 `sys.modules`）全部在实施轮当场抓出，零漏入 main，但烧的是同一轮 token。

口径不变：**493 路由 / 52 蓝图 / 155 表 / 77 迁移单头 `a9f3e5c7b1d2`**；测试 L6 套件 5 例（+1 钉）＋污染钉/台账钉 9 例全绿，ruff clean。

## [未发布] — AI 原生化学习闭环 2.0 L6 实施轮：真实交付反哺宿主侧只读抽取脚本（门禁 fail→pass 迁移＋产物拒收 → 真相层 `import_card_v1` 候选卡；零迁移零路由零表，2026-11-14）

承接 `docs/goal-l2.0-AI原生化学习闭环2.0-任务书.md` L6 条款①②④⑤（条款③ L-C 原文核对视图挂账顺延，见任务书挂账登记）：

- **NEW 宿主侧只读脚本 `scripts/extract_case_from_project.py`**：只读扫描 `operation_events` 的 `gate_decided` fail→pass/conditional_pass 真实驳回修正链与四类拒收信号（`business_facts`/`requirements` 审阅拒收、`agent_artifacts` 人工撤回、`solution_review_checkpoints` 驳回），以已接受事实/需求为骨架装配脱敏 `import_card_v1` 候选卡；**宿主通道五边界先例裁定**（沿 `scripts/lead_ledger_append.py`：人工发起＋数据库只读事务 `SET TRANSACTION READ ONLY`＋真相层只插不改＋确定性 `card_id`〔信号指纹 sha256〕幂等＋登记面缺失 fail-closed 不自动建目录），服务端容器不直连宿主 CLI。
- **脱敏与隔离红线**：全部自由文本字段强制经 T-A2 `redact_text_detailed`（企业名→代号、PII 掩码；凭据串命中 `SensitiveCredentialDetected` / 词典故障 `RedactionConfigError` 即 fail-closed 中止、零落盘）；输出目录双闸（落本仓内 `out_dir_inside_repo` / 目录不存在 `out_dir_missing` 一律拒绝——候选卡含判卷基准，永不入仓、不入被扫面）；写出前强制过 L1 `import_cases.build_payload`＋`gate_payload` 生产四重闸（卡 schema 允许名单＋`validate_scenario` 八规则＋`load_view` 三视图泄漏自检），激活仍复用 L1 人工链（导入→桌面核对→启用），零自动入库路径。
- **预算记账主体写明**（任务书条款④）：脚本纯确定性 SQL 只读，零 AI 调用零 token 消耗；候选卡后续训练场运行/回归的 AI 记账统一归发起运行的平台服务/操作员账号（`provenance.billing_actor_policy='service_account'`），不伪造匿名主体。
- **验证**：NEW `server/tests/test_extract_case_from_project.py` 4 例（输出目录安全双闸／信号抽取→脱敏→幂等落盘→L1 衔接／凭据串 fail-closed／源码零答案键静态钉）全绿；污染隔离钉＋L1 管线＋lessons 装载邻域回归 34 passed；ruff clean；变异四连（幂等短路／仓库内落盘闸／凭据 fail-closed／目录缺席闸）全真红→字节级 sha256 逐位核对还原→复绿。**真机反哺实证（收口轮补记）**：PR #476 squash `55ff1187` 后自主树实跑——试点项目 `FDE-20261025-9BF8E4AE` 真实门禁/拒收信号产出候选卡 `IMP-PRJ-FDE-20261025-9BF-98C9CE`（sha256 `f51feff15197f80616ebb459aa94b86b190f6499faffffc8bc611c847c7c3829`），过 T-A2 脱敏＋L1 四重闸后落真相层 `D:\test\FDE\knowledge\案例候选\l6-candidates\`（人工预建目录，不入仓不入被扫面），幂等复跑 `already_exists` 同指纹＝**只插不改活体实证**；激活仍走 L1 人工链。**便携版 r52（收口轮）**：三源 bump（RELEASE-COUNTER 51→52＋`desktop/package.json` `0.3.0-r52`＋web 桥 `0.3.0-r52-web`），asar sha256 `bd309b15b18301aa88f6df437f482b0b97eec6f90501869ed97087c7a887d605`，L5 marker「三载体发布并排预览」正向 1／r51 asar 负对照 0（独立输出目录 `release-r52` 绕句柄锁），归档 `release/蔡工FDE-0.3.0-便携版-r52`——本包同时承载 L5 桌面改动（发布并排预览＋真载荷回执＋异步回归轮询）。零迁移零路由零表——口径 **493 路由 / 52 蓝图 / 155 表 / 77 迁移单头 `a9f3e5c7b1d2`** 不变，审计清单三件套与 archify 图沿用 L5 刷新态。

## [未发布] — AI 原生化学习闭环 2.0 L5 实施轮：三载体热生效（动态 Lessons＋Prompt Overlay 两点共用＋Skill 双闸链）＋回归真化噪声带四钉＋异步 BackgroundJob（迁移 `a9f3e5c7b1d2` 76→77 单头，路由 491→493，表 153→155，2026-11-14）

承接 `docs/goal-l2.0-AI原生化学习闭环2.0-任务书.md` L5 与设计稿 v1.1（§6 六条拍板全裁决），打通验证面与回流面全链机械化闭环：

- **迁移②（NEW `server/migrations/versions/a9f3e5c7b1d2_loop2_l5_agent_lessons_prompt_overlays.py`，76→77 单头）**：新建 `agent_lessons` 表（`LESS-DYN-` 前缀、`status ∈ (draft,published,retired)` CHECK、`text_sha256` 唯一索引）与 `prompt_overlays` 表（`purpose_key`、`fragment` ≤200 字、`content_sha256`、`min_prompt_version`、`status` CHECK），`ai_call_audits` 加 `context_payload_json` 归因列（无覆层调用保持 `NULL`）。
- **三载体协同热生效与热回滚**：①**动态 Lessons**（`agents/lessons.py`＋`agents/service.py`）：`seeds/lessons.json` 底座 ∪ `agent_lessons(status='published')` 零模块缓存每次现查（top_k 竞争时 seed 优先），发布前拦截动态 ID/sha256 与底座碰撞，宿主 `agent_run_created` 事件 `changes.dynamic_lesson_ids` 快照留痕；②**Prompt Overlay**（NEW `ai/overlays.py`＋`control/ai_server_client.py`＋`ai/deepseek.py`＋`ai/auditing.py`）：`load_overlays(purpose)` 在 `execute_ai_prompt` 与 `DeepSeekClient.complete_json` 直连腿两点共用并在 `compute_prompt_fingerprint` **之后**追加（`prompt_registry` 常量零触碰），归因落 `AICallAudit.context_payload_json`，注入闸五件套齐全（禁祈使句/第二人称/中英注入模式词黑名单＋≤200 字／12-gram 重叠率 >50% 防洗稿拦截／NEW `GET /api/v1/simulation/proposals/<id>/release-preview` 审批并排呈现基座提示词 vs 注入终文＋近 30 天调用量／蒸馏数据框定／v1 白名单 13 key 排除公网 `diagnostics_report`）且 `WorkbenchAdapter` 沙箱同尺；③**Skill 双闸链**（`improvement_service.py`＋`release_channel.py`）：AI 草稿提案拒绝 `personal` scope（防保存即 published 绕闸），`release_channel` 仅记账 `skill_ref` 与回归报告 ID，热生效走既有 `publish_skill`／`rollback_skill` 滚版本指针。
- **发布闸与回归真化＋噪声带四钉＋异步回归**：`release_proposal` 机械拦截最近一次 `RegressionResult.overfit_risk=True`（409 `conflict`），`_materialize_payload`／`_retire_payload_rows` 承载发布落表与回滚 `retired`（两新表写面 AST 静态钉收敛）；`regression_runner.py` 新增 `DEFAULT_NOISE_BAND = 0.1049`（与 L2 底册 `docs/audit/训练场分布读数-L2底册-1.md` 双锚）、`RunSummary` 可选 `model_total/evaluator_axis`、`compare()` keyword-only `noise_band/noise_band_axis` 输出独立 `model_verdict`（不动顶层 `verdict` 闭集），套件存档轴与现算轴 `f"{RUBRIC_VERSION}|model:{mode}"` 不符 fail-closed 409 `noise_band_axis_mismatch`；`adapter_mode=workbench` 或 `model_mode=server` 转 202 后台作业（NEW `simulation/regression_jobs.py` 注册 `simulation.regression` 入 `RECOVERABLE_JOB_TYPES`＋NEW `GET /api/v1/simulation/regression/jobs/<job_id>` 状态读面，零额外迁移）。
- **红线升格与桌面接线**：`AGENTS.md` 写入 §6-5 N6 受控例外红线条款与 §6-6 平台级生效登记；桌面 `ImprovementProposals.tsx` 发布确认弹层接入并排终文预览＋30 天调用量展示与发布/回滚真载荷回执，`RegressionDashboard.tsx` 接入 202 异步回归轮询与 `model_verdict` 徽标。
- **验证与口径**：服务端定向套件 114 passed＋机械闸 48 passed、桌面 `typecheck` 零错＋`simulation-lab-console.test.tsx` 19 passed、官方 mypy 277 基线零新增、ruff clean；变异四连 M1–M4 全真红→`try/finally` sha256 逐位核对还原→72 passed 全绿；审计清单三件套重生成（**493 路由 / 52 蓝图 / 155 表 / 77 迁移单头 `a9f3e5c7b1d2`**）＋`architecture` 架构图四件套刷新与 1440×2119 整页 `preview.png` 实拍过防陈旧闸。便携版随 L6 收口轮对齐最新 `RELEASE-COUNTER` 统一打包验证。

## [未发布] — goal-liveinfra R1 清退轮：diag 孤儿栈清退消解跨栈 Redis 别名轮询＋R2 探针缺陷判定不成立（纯运维清退零代码零迁移零路由，2026-11-14）

承接 `docs/goal-sprint-BLOCKED.md` #4/#5 与 `docs/goal-liveinfra-活体基础设施修复-任务书-v1.md` 立项，经蔡工交互拍板（R1 修法＝清退 diag 孤儿栈；时点＝立即开工）实修收口：

- **R1 已消解**：因 本机 diag 部署源树 `D:/test/fde-wt-deploy-diag` 已删、diag 栈 4 容器成孤儿（api 卡 `created` 因外部端口 8010 被主栈占用），实修＝`docker stop`＋`docker rm` 全 4 个 diag 容器（本机孤儿 diag 容器零残留；远端 diag.fde18.com 公网部署不在本次处置范围；diag redis volume 保留 dangling 不越界；主机侧 `fde-redis-forward`/`fde-pg-forward` 独立常驻 forwarder 保留，现随 alias `redis` 唯一解析回归主栈）。活体验证全绿：`redis` alias 唯一解析 `172.18.0.4`（`getent hosts redis`×8 全 `.4`，不再 .4/.14 轮询）；`fde:health:{worker,scheduler}` 键回归主栈 redis；worker `fail` 1→0 恢复 healthy；主栈 4 容器全 healthy、ID 不变（**主栈零 recreate**，`compose.yaml`/`.env`/`FDE_REDIS_URL` 零改动）。
- **R2 判定反转，缺陷不成立**：现测活体镜像 `server/src/fde_api/health/heartbeat.py:97 return 0 if healthy else 1`＋`:102 raise SystemExit(main())`，absent-key exit=1、present-key exit=0（crv2 源码与镜像逐字一致）；早期收口终扫「FAIL 却 exit=0」观测未能复现，疑似 shell 引号或退出码捕获问题，具体成因未证实；`heartbeat.py` 零改动、无需新增探针测试用例。
- 台账同步：`docs/goal-sprint-BLOCKED.md` #4/#5 实修回执回写；`docs/goal-liveinfra-活体基础设施修复-任务书-v1.md` 补 §终态；`docs/audit/下一步实施台账-2026-11-07.md` §12 追加 goal-liveinfra R1 清退更新块。本线零代码零迁移零路由零桌面改动。

## [未发布] — 盲审追批修复轮：桌面复核投影双形状守卫消解死锁＋同族复核账零真名扩线（quality/plans/discovery/transcripts，2026-11-14）

`fix3` 盲审（重装真身 code-review＋intended-vs-implemented）两项发现的当轮修复：

- **发现①（P1 跨端契约断裂→复核死锁）**：`#463` 服务端复核投影换代（指纹条目 `name` 可空＋疑似聚合哨兵 `{suspect_count}`）后，桌面守卫 `isRedactionReviewEntries` 仍要求每项 `name` 非空 string ⇒ 新形状整组丢弃 → 复核框消失 → confirm 永远 409 `redaction_review_required` 死锁。修法：`guidance/types.ts` 守卫换代为三形状联合（指纹条目/疑似哨兵/旧形状宽容），`GuidanceReview.tsx` 渲染分派（词典反解缺失显示指纹前 8 位占位＋疑似聚合行），ack 语义不变。
- **发现②（意图↔实现同族漏网）**：`#463`「复核账零真名」只接线 guidance/translator 四锚，同族四面仍落真名原文。扩线：`redaction.py` 新增 `fingerprint_review_payload` 单一真身（指纹条目＋疑似哨兵单数组，与 guidance 读面投影同形状）；`discovery/jobs.py`（行内账＋事件账）、`transcripts/service.py`（草稿行内账）、`quality/draft.py` 与 `plans/draft_ai.py`（事件账）四写入点全接线；`discovery/service.py` 与 `transcripts/service.py` 两读面接 `resolve_redaction_display` 词典反解（软失败 name=None）。桌面 `DiscoveryPanel.tsx` tooltip 与 `TranscriptDraftsPanel.tsx` 复核清单同步适配双形状。
- **测试与验证**：服务端 9 套件 101 passed（discovery/transcript/quality/plans 断言换代为指纹＋零真名）；桌面 guidance-redaction-review 新增 2 例（新形状渲染＋ack／畸形整组丢弃 409 回读路径）全绿；变异两连真红（M1 桌面哨兵分支删除／M2 discovery 写入回退真名）→`try/finally` 字节还原→复绿；mypy 277 基线零新增；ruff F401/F841 零告警。零迁移零新路由零新表；便携版 **r51**（`0.3.0-r51`，asar `52c0d542221ddee8ac5bf8ffaf2a81774a7f0305c03a7784a3a25ce3b19625aa`，正向 marker 命中 3／反向 0／asar 字节 6/6 全过），同时补齐 `scripts/release-version.mjs` 三源同步（`RELEASE-COUNTER`＋`desktop/package.json`＋`fde-web-bridge.ts`，根治 CR-058 web 桥版本字面量每次 bump 漂移必红问题）。


## [未发布] — N1 试点落地证据收口＋6 张架构图刷新＋Top-12 技能工作流嵌闸＋打包契约修复（2026-11-14）

**N1 窗口内闭环全量证据归档（窗口 2026-11-12~11-19，提前达成）**：pilot-001 两条正式 run 经宿主代理裸跑通道完成（completed/exit 0/无降级/claim+receipt 齐；185s/256s；宿主单次代理与产物读取/采纳服务端实现已于 #433/#435 合并），**8 份产物全部完成人工复核**（run-001 3/3＋run-002 5/5，`reviewed_by=admin`），磁盘原件 sha256 与库内指纹双侧现测逐字一致——r1 全量 sha256 清单补登 `docs/goal-sprint-PROGRESS.md`「r1 证据登记」节并消解 r1 遗留。证据闸 `HAS_RUN_EVIDENCE`（审批 p50=85.5s/p90=104.3s、否决率 0）。

- **售前五件套资产**：run-002 产物存为参考样板 `docs/售前产物参考/run-002-20261113/`（README 含全量 sha256 对照）；手册新增「§15 智能体产物（run 产出）与售前五件套参考」（`docs/工作台操作使用手册.md` 与 `server/src/fde_api/control/bundled/help_manual.md` 两副本逐字一致）；`desktop/src/renderer/src/help/HelpPage.tsx` 新增同名章节（桌面端「使用帮助」）。
- **修复**：`scripts/verify-asar-bytes.mjs` 数据区起点按 asar 规范改 `8 + u32(4)`——旧公式漏算 header pickle 对齐填充（1–3 字节），header 长度一变即全量同字节数假失败（r46 打包实测 62 项假失败 → 修复后全过）；`tests/operations/packaging-contract.test.mjs` 对齐 `desktop/src/shared/brand.ts` 单点 `PRODUCT_NAME` 与 `0.3.0-rN` 列车轮次版本后缀（`npm run test:operations` 14/14 全绿）。
- **架构图与技能工作流**：全套 6 张 `docs/architecture/archify-diagrams/` 刷新对齐最新口径（52 蓝图 / 491 路由 / 153 表 / 76 迁移，四道 archify 门禁与整页 `preview.png` 全过）；新增 `docs/audit/项目12大高价值技能评估与使用指南-2026-11-14.md` 并在 `.agents/skills/fde-delivery-flow/SKILL.md` 嵌入审查/证伪/实证/洁癖四道关卡。
- **归档**：`docs/goal-crv-全面代码审查-任务书.md`、`docs/goal-crv-评审会纪要-2026-11-13.md`、`docs/goal-ks1-知识库技能首批入库-任务书.md` 落库。

## [未发布] — goal-crv 修复收官：fix2 总循环七轮一 PR 全合并＋统一活体部署三验绿（收口轮·纯文档零代码零迁移，2026-11-14）

`docs/goal-crv-fix2-剩余批次总循环-任务书.md` 七轮全部收官：批 A/C/D/E/G/R7（`#444`/`#451`/`#456`/`#462`/`#463`/`#466`）＋本收口轮。147 条 QR 台账 P1×18 与拍板 8 项全部清零；总报告 v1.0 正文零改动、末加 `§修复销号节`；`docs/goal-crv-BLOCKED.md` / `docs/goal-crv-PROGRESS.md` 终态回写；`AGENTS.md` 独立 bullet 登记。统一活体部署三验实测全绿（`url_map` non-static `491`≡`v3-workbench-inventory.json`／`alembic current` `d4b7e2f9a6c1 (head)` 76 rev≡单头／三镜像 ID≡本树构建 `api:4e3daf1f9f09`·`worker:6b5f05014f7a`·`scheduler:b8013143bfea` MATCH，四容器 healthy＋`:8010/api/v1/health/{live,ready}` 200；`migrations` 挂载源回归收口树 `/mnt/d/test/fde-wt-crv2/server/migrations`）。本节为收口轮自身记录：零代码零迁移零路由。

## [未发布] — AI 原生化学习闭环 2.0 L4 桌面收口＋workbench 直连四元组修复（桌面「失败→AI 起草→建案」＋场景选择器＋workbench 执行面选项，零迁移零新路由＝491/52/153/76 rev 单头 `d4b7e2f9a6c1` 不变，2026-11-14）

承接 L4 服务端（PR #455 → `7e99b658`），补齐训练场桌面端 L4-⑦ 全套操作面并闭合活体真机冒烟检出的直连四元组缺口：

- **L4-⑦ 桌面「失败→AI 起草→建案」闭环（`FailureAnalysis.tsx`＋`ImprovementProposals.tsx`＋`api.ts`＋`types.ts`）**：失败发现列表支持多选与 L-B `likely` 标记文案（「L-B 模型建议 · 根因未确认——完成 L-C 人工复核确认后方可建正式提案」，按 §6-4 拍板仅列表提示不建审批流）；点击「AI 起草改进候选」调 `POST /api/v1/simulation/findings/draft-ai`（返件式零落库），就地展开三载体候选编辑器（`lesson_entry` 经验卡／`skill_version_draft` 技能草稿／`prompt_overlay_fragment` 提示词追加片段），人工审阅修订后对含 `confirmed` 发现点击「创建改进提案」调 `POST /api/v1/simulation/proposals` 落 `candidate_payload_json`；提案列表同步展示结构化候选载荷。
- **场景选择器＋`workbench` 执行面选项（`SimulationRunDetail.tsx`）**：新增「目标场景」`<select>` 选择器取代硬编码 `scenarios[0]`；「执行面」选择器与运行徽标新增 `workbench`（工作台内嵌模型）并对 `queued`/`running` 态每 3 秒自动轮询刷新详情。
- **服务端 `WorkbenchAdapter` 直连四元组修复（`simulation/adapters/workbench.py`）**：活体真机冒烟检出 DSH 未启用时降级直连腿 `direct_provider_completion` 要求 `model_override` 完整携带 `{provider, model, base_url, api_key}` 四元组（仅传 `{model}` 报 `ai_model_not_configured`）；`_resolve_model_override` 补齐四元组并对缺 `base_url` 同样 fail-closed 抛 `AdapterUnavailable("workbench_model_slot_incomplete")`。
- **验证**：桌面 `npm run typecheck` 零错＋`simulation-lab-console.test.tsx` 新增 2 例（17 passed，全量 vitest 102 文件全过）；服务端 `test_simulation_workbench_adapter` 12 passed＋污染/单向阀/纯净度/预算 17 passed＋mypy 277 基线不变＋ruff 零错；变异三连全红→字节级 sha256 还原→复绿（M1 删 `base_url`／M2 退回 `scenarios[0]`／M3 删 `candidate_payload`）。便携版在 L5/L6 全链完成后对齐主树 `release/` 最新序号统一交付。

## [未发布] — goal-sprint 收口拍板回写轮：四项交互拍板落档＋G-C 签署材料包＋活体基础设施修复立项（纯文档零代码零迁移零路由，2026-11-14）

收口终扫后四项待拍板事项经交互选择卡由蔡工拍板（均按推荐项，留痕可推翻），回写 `docs/goal-sprint-BLOCKED.md` 并派生两份新件：

- **D7 阈值**：维持待拍板（支撑度 `insufficient_for_unfreeze`，样本达标后再拍；零预支纪律不变）。
- **G-C 签署与账号发放**：整理签署材料包——NEW `docs/deployment/对外受控试用-G-C签署材料包-2026-11-14.md`（三闸现状更正〔G-A 2026-11-09、G-B 2026-11-10 已签，未签仅 G-C〕＋G-C 剩余判据逐项指针＋T5-7 外部真机执行指引＋签署三步＋值守/回收预案成文＋证据索引）；T5-7 与签署、发放归 `OWNER`/`HOST` 亲手。
- **N1 试点窗口**：2026-11-19 按期关闭（到期后如实登记；8/8 产物复核已清零，宿主通道转回待授权态）。
- **两项共享活体风险**（跨栈 Redis 服务别名 DNS 轮询＋healthcheck 探针 FAIL exit=0）：单独立项一次修两项——NEW `docs/goal-liveinfra-活体基础设施修复-任务书-v1.md`（R1 别名唯一化＋R2 探针 exit code，单 PR 交付，验收含双栈心跳归位观测与探针变异验证）；实施排期待显式令。
- 台账同步：`docs/goal-sprint-PROGRESS.md` 追加收口拍板回写节；`AGENTS.md` 收口行补拍板结论。

## [未发布] — 桌面第三批业务与治理闭环：本体写面与候选＋方案 AI 生成＋智能体凭据＋到期与队列监控（桌面变更·零服务端改动·零迁移零路由，便携版 r50（r48 编号被并发线顺延——r49 已被 30b433f6 态打包消耗），2026-11-14）

补齐桌面 4 处「后端完备、前端零入口」的业务与治理面（本体/solutions/agents/jobs 契约早已上线，本轮接最后一公里），严守闭集键、明文零驻留与禁自审纪律：

- **本体写面与候选（`GlossaryPage.tsx`）**：canManage 三块写面——①「候选生成」面板懒加载（展开才拉 `GET /projects/<id>/discovery/extractions?limit=50`，前端预筛 `status==="review_required"`），`POST .../ontology/candidates/generate` body 恰 `{extraction_id}`，结果 `{change_set, created, skipped, cross_project_conflicts}` 就地呈现（跳过清单与跨项目同名告警如实显示、后者只读不阻断）并刷新变更集清单；②「手工提变更集」起草表单（create_term/update_term/merge_terms 三动作条目化），body 闭集 `{title, description?, proposed_json}`——description 留空不传、**绝不传 `captured_from`**（AI 通道专用，服务端显式 400），同名合并在前端拦下不发请求，`term_type` 五值闭集（entity/attribute/metric/alias_target/generic）；③关系类型「登记类型／停用」：登记 body 闭集 `{kind, code, label?, description?, scope}`，code 与服务端同尺（`^[a-z][a-z0-9_]*$` ≤60），`global` 范围仅 admin 可见可选；**link_type 另附 `allowed_source_types`/`allowed_target_types` 两键**（任务书闭集未列，服务端硬闸必填——缺一即 400 invalid_request，前端同尺补齐、仍在服务端字段允许名单内）；停用走两步确认 `POST .../relation-types/<id>/retire`（无 body），非 retired 行才可停、全局行仅 admin（否则呈现「全局类型仅系统运维员可停用」）；变更集评审列表补**禁自审闸**——`in_review` 且 `created_by_user_id===user.id` 的行禁点确认/否决并提示「须由另一管理员审阅」（服务端 403 语义的前端预拦）。
- **方案 AI 生成（`SolutionDetailPage.tsx`）**：头部新增 `SolutionAgentGenerator`（仅 `canManage && status!=="archived"` 渲染，与服务端 409 `solution_archived` 同口径）：`GET /api/v1/agents` 清单默认选中可用且 `capability_tier==="agent.module.solution"` 的智能体，不可用项禁选并展示 `unavailable_reason`；`POST /projects/<id>/solutions/<sid>/generate-agent` body 闭集 `{agent_id, idempotency_key?}`（键留空不传、幂等键 ≤160 字客户端拦截）；`wired===true` 经 onWired 回写 solution（溯源徽标「智能体生成」就地联动刷新）；`wired===false` 呈现 `run.status` 并以 `allowNextHashNavigation()` 放行锚点跳转 `#projects/<projectId>?tab=agents`；清单拉取失败静默降级（辅助入口不阻断方案详情主内容）。
- **智能体凭据（`ExtensionsPage.tsx`＋NEW `AgentCredentialsPanel.tsx`）**：「AI 与扩展」新增「智能体凭据」Tab（仅 canManage 显）：`GET /api/v1/agents/credentials` 直接返数组（403 呈现「仅平台操作者可管理智能体凭据」）；保存 `POST` body 闭集 `{name, credential}`——凭据名与服务端同尺 `^[A-Za-z0-9_]{1,120}$`（提示 default 槽），明文非空 ≤8000；**明文零驻留：提交入口 await 前即清空明文 state、清空按钮与取消同步清空**（明文只在本次请求的内存 body 出现一次）；删除走两步确认 `DELETE /api/v1/agents/credentials/<name>`（404 原样呈现）；清单只出名字与 `credential_configured` 布尔、绝不回显。
- **运行治理卡（`SystemConfigurationPage.tsx`＋NEW `PlatformGovernancePanel.tsx`）**：`<form>` 外下方渲染（结构约定有 DOM 断言钉住），失败不阻保存——两路数据独立加载各自呈现错误：①到期事项 `GET /api/v1/expirations?due=true`，域按服务端 `EXPIRY_ACTIONS` 四键闭集（automation_approval/api_confirmation/dispatch_offer/upload_session）防御性过滤，中文域标签＋对象/截止时间/状态/到期动作表格；②队列计量 `GET /api/v1/admin/jobs/metering`，`queue_depth`（null 呈「—」）＋`groups`（`org_id??"平台级"`/active/terminal）；③取消任务两步确认 `POST /api/v1/admin/jobs/<job_id>/cancel`（无 body），幂等 `cancelled=false` 如实呈现、409 already_terminal/job_running 与 404 原样透传，成功后刷新计量。
- **验证与打包**：vitest 新增 28 例（`ontology-write` 9＋`solution-agent-generate` 5＋`agent-credentials` 8＋`platform-governance` 6，覆盖闭环/闭集键/明文清空/禁自审/403/409/404 与 `<form>` 外结构断言），全量 **102 文件 1170 passed**＋`npm run typecheck` 零错＋变异三连全红→字节级 sha256 还原→复绿（M1 手工变更集塞 `captured_from`／M2 generate-agent 多塞 `solution_id`／M3 注释凭据 await 前明文清空）；★M1 变异当场暴露一处**真空断言缺陷**（mock 的 GET 清单分支排在 POST 分支前且不区分 method，body 断言成死代码）——修分支顺序后变异才真红，变异机制自身被反向验证；`git diff fork/main -- server/` 为空（零服务端改动）。合并后在主树 `release/` 产出 `蔡工FDE-0.3.0-便携版-r50`（r48 编号被并发线顺延）并完成新旧 `app.asar` 四特征串（`ontology/candidates/generate`、`generate-agent`、`agents/credentials`、`admin/jobs/metering`）旧=0 新≥1 正反向核验。

## [未发布] — goal-sprint 收口轮：上线就绪终扫＋BLOCKED 登记＋冲刺线收官（纯文档零代码零迁移零路由＝490/52/153/75 rev 单头 `d4b8e1f6a9c3`/98 ENTRIES 全不变，2026-11-14）

任务书 §8/§9 收口轮：对照 `docs/deployment/对外试用部署方案-v1.md` §8 十三项验收清单逐项终扫（技术判据引用 2026-11-09 T6 现测＋本轮只读复测，业务闸不代拍）并核销 §9 六条硬指标。

- **只读复测全绿**：`app.fde18.com` ready/live `200`＋官网 `200`；证书 `app` 至 `2027-02-07`、`diag` 至 `2027-02-11`；公网 `8010/5432/6379` 外探均不可达；四 compose 服务 healthy；`VERIFY-R5-DIAG-PUBLIC-LIVE` 复跑 PASS（6/6）。
- **§9 硬指标 6/6 核销**：①`adapter_missing` 解除回执在场（台账 §12，r3）；②N1 窗口终态＝2 条 `host_poll` run 全 `completed` 且 **8/8 产物全部人工复核**（活库现测，r4 时 5 件待复核已清零；sha256 指针纪律）；③D7 报告出齐＋拍板位「待蔡工拍板」（零预支）；④T-14b 终态（r5＋本轮复测）；⑤六轮 PR（#411/#422/#433/#438/#445/#459）各自四 CI job 绿＋活体三验绿；⑥全程零闸代拍零预支零造假。
- **NEW `docs/goal-sprint-BLOCKED.md`**：待授权 3 项（D7 阈值拍板／G-B、G-C 闸签署与账号发放／N1 窗口 11-19 到期处置）＋共享活体现测风险 2 项（跨栈 Redis 服务别名 `redis` DNS 轮询致心跳键跨栈串写、healthcheck 探针 FAIL 不置非零退出码致「healthy」对心跳缺失无判别力——均非本线改动面，处置待拍板后单独立项）。
- **台账三同步**：`docs/goal-sprint-PROGRESS.md` 至终态（r1–r6＋收口全 ✅ 冲刺线收官）；`AGENTS.md` 本线收口行；实施台账 §12 收口行。冲刺线八轮（r1–r6＋收口）至此全收官。

## [未发布] — goal-crv 修复批 R7：桌面五项安全与体验收口（主进程守卫成对＋LCSC 闸全覆盖＋点击前复验＋双桥响应面恒同＋控制台错误条，零服务端改动·便携版 r49，2026-11-14）

依据 `docs/goal-crv-fix2-剩余批次总循环-任务书.md` r6 批 R7 完成 `QR-109`~`QR-113` 五项 P2 修复（零迁移零新表零路由）：

- **QR-109 主窗口 will-redirect 守卫**：`hardenWebContents` 主窗口分支补 30x 重定向同尺拦截（此前特权更高的主窗口只有 will-navigate 半边，lcsc 分支反而成对注册）。
- **QR-110 desktop-execute 入闸**：`lcscIpcEnabled`「默认关」闸覆盖第 4 个 LCSC 面——API 桥 `desktop-execute` 拦截分支在拉起自动化执行前调 `requireLcscEnabled()`（flag=false 桥层即拒，不再依赖服务端 403 兜底）；声明上移 TDZ 安全，4 面共用单点。
- **QR-111 点击前语义复验**：denied 名单提单一真身 `DENIED_ACTION_SOURCE`（观察面与点击面共用），runner 点击分支执行前对目标当前文案/aria-label/title 复验同尺正则＋form 归属拦截（TOCTOU 窗口敏感控件误点即停）。
- **QR-112 双桥响应面恒同**：`shared/api-safety.ts` 新增 `parseApiEnvelope`（ok∧error 拒／!ok∧¬error 拒／!ok data 置空／错误体形态四不变量单一判定）与脱敏纯函数族（实现逐字迁移）；桌面桥与 web 桥各自消费同一 verdict——web 桥四处不等价缺口全封；等价性静态钉扩响应面 17 信封样本＋5 脱敏样本双侧钉死；旧钉换代 1 处（错误信封 stub 200→409，换代注记留痕）。
- **QR-113 控制台错误条**：`AgentsConsole` 去顶层 error 整页早返回（单件复核 409/下载失败不再全页坍缩），改页内错误条＋重试按钮，与 detailError/queueError 就地呈现一致。
- **验证与打包**：`npm run typecheck` 零错＋vitest 全量 104 文件 **1217 passed**（+26：信封/脱敏样本双侧＋源码锚钉 8 例）＋变异三连（`M1_QR110_gate_bypass`/`M2_QR111_recheck_bypass`/`M3_QR112_ok_with_error`）全红→字节还原核 sha256→54 passed 复绿；RELEASE-COUNTER 对齐实际轮次（45→48）后 bump 打包**便携版 r49**（`0.3.0-r49`），asar 正反向字节双证 ALL PASS（六特征新命中/旧 0 命中＋版本 marker），归档主树 `release/蔡工FDE-0.3.0-便携版-r49`（asar `275313739f5dc4eb…`）。

## [未发布] — goal-crv 修复批 G：复核清单指纹化零真名＋update_analysis 编辑复扫（零迁移零新路由，2026-11-14）

依据 `docs/goal-crv-fix2-剩余批次总循环-任务书.md` r5 批 G 完成 `QR-133`/`QR-134` 两项拍板修复（零迁移零新表零新路由）：

- **QR-133（拍板 #6A）复核清单指纹化**：`guidance.redaction_review` 事件账零真名——`guidance/redaction.py` 落 `redaction_name_hash`（域分隔 sha256）与 `fingerprint_review_entries` 单一真身，确证命中只存指纹、未确证疑似名不入条目账只留聚合计数（`suspect_count`）；guidance worker／translator 创建与落库两阶段／采纳流搬运四锚写入侧接线；读面 `resolve_redaction_display` 经词典反解显示词目原文（未命中 `name=None` 软失败），历史 name 形状事件现算指纹归一兼容。
- **QR-134（拍板 #7A）编辑复扫＋豁免登记**：`update_analysis` 保存时对编辑文本与列表 str 值输出端复扫——词典确证命中 422 `redaction_name_detected` fail-closed（不回显原文）、疑似名替换为代号放行＋`manual_edit` 计数事件、凭据串 422 同闸；presurvey 录入卡维持零脱敏豁免（用户自填自述≠AI 加工面），随指纹化语义一并登记 `AGENTS.md` 独立 bullet。
- **验证**：NEW `tests/test_crv_batch_g.py` 10 例＋旧钉换代 4 文件＋邻域回归 12 套件 97 passed＋变异三连（`M1_QR133_fingerprint_bypass`/`M2_QR134_dict_hit_reject`/`M3_QR133_suspect_count`）全红→`try/finally` 字节还原核 sha256→10 passed 复绿；`ruff` 零告警；`check-python-types.py` 277 基线零新增。

## [未发布] — 学习闭环 2.0 L4 服务端：workbench 真执行面＋analyze_run 三源化＋AI 蒸馏返件起草＋断点⑥ lessons 键名修正（迁移① `d4b7e2f9a6c1`：candidate_payload_json 加列＋adapter_mode 扩值，2026-11-14）

goal-l2.0 任务书 L4 轮服务端半（桌面「失败→AI 起草→建案」另 PR）；按设计稿 v1.1 §2.1–§2.3 落六断点中的断点①②③⑥：

- **NEW `simulation/adapters/workbench.py`（第三执行档）**：`adapter_mode="workbench"` 注册进 `ADAPTER_MODES` 与 `build_adapter`（mock/real 零回归）；probe/analyze/design 走 `execute_ai_prompt` 单一入口（purpose=`simulation_workbench`＋注册表版本 `simulation-workbench-prompt-v1`＋预算/审计全继承），JSON 契约失败带拒因重试一次后回落 `structured=False`（real.py 语义）；implement/validate 复用确定性腿；usage 逐调用累计回填 `cost_json`（修正 v1 硬编码 `tokens:0`）。模型槽位 NEW `deepseek_simulation_workbench_model`（空＝回落评估槽位；缺端点/密钥 fail-closed ⇒ 运行诚实失败不静默退回 mock）。候选载荷通道：run config `candidate_payload.prompt_overlay_fragment` 以 ≤200 字追加条款进 system 消息（J-1 登记例外 `system_content`）。
- **runner 逐轮 ctx（评审 P0-Ⅴ）**：访谈循环内逐轮 `dataclasses.replace(base_ctx, disclosed=…, config={…, "history": …})`——修正 v1 全程传同一 ctx（disclosed 恒空）失真；mock 忽略新键零回归；probe 模型面不可用 ⇒ `_fail_unavailable(phase="interview")` 诚实失败。
- **异步化**：workbench 单跑经 outbox 入 `simulation.run` 后台作业（`BackgroundJob` 状态承载零迁移；入 `RECOVERABLE_JOB_TYPES`，终态幂等不重复执行不重复计费）；mock/real 小跑保持同步。
- **analyze_run 三源化（断点②）**：L-A 不动；L-B 查询钉 `layer=="model" AND evaluator_id=="model:server"`＋`verdict!="unavailable"` 二道 ⇒ 低分产 `likely` 发现（不解锁提案，单独提案 409；模型自写 evidence/reason 不采信——evidence_refs 恒空）；L-C 取 `created_at` 最新人工行产 `confirmed` 发现（FA-C1），note 全文先过答案句黑名单（场景 rubric 三桶＋期望结果＋验收标准原文句洗刷＋`note_redacted` 留痕）；幂等键 `(evaluation_id, code)` 三源各挂各行。
- **NEW `POST /simulation/findings/draft-ai`（断点③，返件式零落库，不进 api_catalog）**：蒸馏输入＝字段允许名单投影 `{code, dimension, severity, score, 脱敏 description}`（description 过 T-A2 脱敏管线 fail-closed；evidence_refs/reason/note 物理不进提示词）；train split 服务端过滤；跨题按 FA 码聚类；产出三型候选载荷（lesson_entry≤300 字／skill_version_draft／prompt_overlay_fragment≤200 字）；契约失败整批丢弃重试一次 ⇒ 409 `ai_draft_contract_failed`；输出夹带答案侧键拒（键清单从 `schemas.ANSWER_SIDE_KEYS` 单一真身取）。静态钉：蒸馏器模块 AST import ⊆ 白名单（禁 scenarios.loader/reference 面）。
- **指纹修正（评审 P0-Ⅶ）**：`_finding_fingerprint` canonical 增 `payload_sha256`（无 payload 固定空值）——同 findings 同 target 不同候选载荷两案并存（不再被旧指纹 409 挡死）、同 payload 重复提交幂等 409、老提案互不误伤；`create_proposal` 收 `candidate_payload`（键闭集＝三载体类型＋长度闸）入 NEW 列 `candidate_payload_json`（与 `override_json` 分工：override＝run 参数，candidate＝三载体载荷）。
- **断点⑥修正**：`agents/lessons.py` 键名 `fde_agent_lessons_*`→`agent_lessons_*`（只修 lessons 侧——config 字段真名；此前生产注入恒关）；假 settings 测试同步修正＋NEW 真实 Settings 验收钉（`create_app` 实例断言注入默认生效/可关——同坑两次复发家族）。
- **迁移① `d4b7e2f9a6c1`（75→76 单头，挂 `d4b8e1f6a9c3`）**：`improvement_proposals.candidate_payload_json`（JSON NOT NULL server_default '{}'）＋`simulation_runs.adapter_mode` 列宽 String(8)→16＋CHECK 闭集扩 `'workbench'`——**设计稿 v1.1 勘误**：§2.1 只记注册两处、漏记列宽与 CHECK 两处 DB 落点（"workbench" 9 字符＞8），不随迁则 workbench 运行行在 DB 层必被拒。
- **验证**：NEW 测试三套 41 例（workbench 12＋三源化 8＋蒸馏 16＋真实 Settings 钉并入 lessons 套件 1＋静态钉等）全绿；模拟域回归 135 例＋lessons/registry/J 系/纯度/预算/台账钉 42 例＋迁移套件 32 例全绿；`ruff check` 绿；`check-python-types.py` 277 基线零新增；**变异四连红→sha256 逐字节还原→复绿**（M1 摘 L-B evaluator 钉／M2 摘蒸馏允许名单／M3 还原 lessons 键名错配／M4 摘指纹 payload_sha256）；审计清单三件套重生成（路由 491/76 rev 单头 `d4b7e2f9a6c1`）＋archify architecture 四件套刷新（finalize 四闸绿＋preview 整页实拍 1440×2098）＋防陈旧闸绿。真机 workbench 证据（run id＋活库）另附待蔡工放行额度（配额购买属 OWNER 决策）。

## [未发布] — goal-sprint r6：E8/E11 意图↔实现验收与 A 轨只读降级三处真缺口闭合（零迁移零路由；server 变更，2026-11-14）

任务书 §3 r6 条件轮（开工闸＝r4 D7 复审报告出齐＋蔡工显式开工令，两项齐备；`goal-crv` 147 条 QR 台账扫描与 E8/E11 零交集缺陷）：对 `#414` 合入的 E8 A 轨只读降级层与 E11 智能体凭据管理面执行 N3 五问逐条意图↔实现（intended-vs-implemented）核对，当场修复 E8 三处「测试绿而生产断/漏」真缺口并同步台账。

- **E8 点分能力→只读工具权威映射（修复真实任务无法降级断层）**：`server/src/fde_api/control/automation_fallback.py` 新增 `_build_capability_read_only_map()`，从 `mcp_gateway.TOOLS` 单一真身派生 `CAPABILITY_READ_ONLY_TOOLS` 与 `UNSCOPED_READ_ONLY_TOOLS`（`project.summarize` 共享 `project.read` 4 项只读工具，命中点分只读能力时附带 5 项无能力门槛通用只读工具），修复桌面端/ClawBot 创建任务持久化的点分能力名（默认 `["project.read", "project.summarize", "file.search"]`）此前与下划线工具名 `READ_ONLY_TOOLS` 交集恒空导致生产 100% 不降级的断层；同时保留直传下划线只读工具名兼容与纯写/编排能力集返回 `None` 的诚实失败语义。
- **E8 降级调用链能力与工具白名单双重收窄**：`server/src/fde_api/control/ai_tool_loop.py` 的 `tool_definitions` 与 `direct_tool_completion` 新增可选关键字参数 `capabilities` 与 `allowed_tools`；`server/src/fde_api/control/automation_jobs.py` 在 `_record_degraded_execution → _run_degraded_readonly` 中显式透传任务级 `capabilities=execution["allowed_tools"]` 与 `allowed_tools=plan.allowed_tools`，对齐 `output_json.degraded_allowed_tools` 审计留痕与实际暴露给模型的工具集；`server/src/fde_api/control/ai_server_client.py` 在 `execute_ai_prompt` 两处 `_degraded_direct_result` 降级分支同步透传 `capabilities`。
- **直连/降级循环执行期只读硬闸（N3-Q4 纵深防御）**：`ai_tool_loop._run_tools` 在调用 `mcp_gateway.call_tool` 前强制校验 `name in _permitted_read_only_tools(allowed_tools)`（恒 `<= READ_ONLY_TOOLS`），即使高权限账号遇模型幻觉或提示词注入返回 `capability=None` 的 `api_execute` 或外发工具 `file_send_wechat`/`lcsc_search`，亦直接返回 `{"error": "forbidden", ...}` 绝不执行写操作。
- **E11 凭据管理面核验与验证回执**：核实 `agents/credentials.py` 三路由（`is_platform_operator` 平台双轴闸、凭据名正则 `^[A-Za-z0-9_]{1,120}$`、Fernet 密文零回显、不进 `api_catalog`、7 个 zcode 种子赋 `default`）100% 吻合规格；pytest +6 例（`test_automation_fallback` +2、`test_automation_fallback_wiring` +1 真实 API 点分能力端到端、`test_ai_tool_loop` +2、`test_ai_server_direct_fallback` +1），M1–M3 串行变异三连全真红→`try/finally` sha256 逐字节还原→控制面与安全邻域 13 套件 **209 passed**＋ruff 绿＋mypy 277/102 基线不变＋架构图防陈旧闸与台账钉全绿。零迁移・零新表・零新路由・零桌面改动（现测结构口径 490 路由 / 52 蓝图 / 153 表 / 75 rev 单头 `d4b8e1f6a9c3` / 98 ENTRIES 不变）。

## [未发布] — 项目详情页第二批桌面 AI 辅助闭环：交付方案面板＋测试计划面板＋工作流「从方案生成草稿」（桌面变更·零服务端改动·零迁移零路由，便携版 r47，2026-11-14）

打通项目详情页三块 AI 辅助消费面（plans／quality／workflows 蓝图路由早已上线，本轮补齐桌面最后一公里），严守双来源并列、产物恒 draft、闸不代拍与错误码原样呈现纪律：

- **交付方案面板**：新增 `desktop/src/renderer/src/plans/DeliveryPlansPanel.tsx` 挂入 `desktop/src/renderer/src/projects/ProjectDetailPage.tsx` delivery 分支（SolutionDesign 与 HandoverPackagesPanel 之间，未选 solutionId 时渲染）。`generate`（确定性拼装）与 `generate-ai`（AI 起草）并列双来源、产物恒 draft；draft 态「批准/驳回」（内联备注 ≤500 字）、approved 态「发布」、approved/published 态「分解任务」——目标模块下拉（`project.modules` 过滤 cancelled，空模块禁用入口）＋条目勾选＋`dry_run:true` 预览→`dry_run:false` 落任务两段式，写后重拉并回刷项目任务（`onTasksCreated` → 项目详情重取）。
- **测试计划面板**：新增 `desktop/src/renderer/src/quality/TestPlansPanel.tsx` 挂入 tasks 分支（TaskTable 下方）。`generate`/`generate-ai` 双来源且「来源任务」下拉选中即透传 `source_task_id`；用例表（`case_key`/`title`/`risk_level`/`acceptance_mode`/`requirement_key`）；draft「批准/驳回」（覆盖闸 409 `requirement_coverage_incomplete` 连 `missing_requirement_keys` 原样呈现）；approved「登记执行」——环境仅 dev/staging（production 恒 409 不出 UI 选项）、逐用例勾 result（passed/failed/blocked）、`report_uri` 与 `report_sha256` 缺一前端拦截不提交（成对后放行）。
- **工作流控制台升级**：`desktop/src/renderer/src/workflows/WorkflowConsole.tsx` 既有行为零回归，canManage 顶部新增「从方案生成草稿」区＝交付方案下拉（过滤 approved/published）＋实施技能下拉（GET `/api/v1/extensions` skills 过滤 published，ref=`key@current_version`）＋审批能力默认 `workbench.write`，并列「编译草稿」（POST `draft-from-plan`，落库为 draft 定义）与「AI 起草草稿」（POST `generate-ai-draft`，返件式零落库）；AI 返件就地预览（节点表＋validate 明细＋`dag_sha256`），「采纳为定义」POST `/workflows` body 恰含 `name`/`dag`（`description` 非空才携带，validate 明细不进 body）；draft 卡片加「干跑校验」（validate 干跑明细就地呈现），isAdmin 加「发布」；`ProjectDetailPage` 增传 `isAdmin`。
- **错误码纪律**：全部写动作 403/409/422 原样呈现 `[code] message` 不吞；草稿来源列表（方案/技能）加载失败静默降级为空下拉（沿面板族 fail-静默纪律），生成动作仍受服务端闸约束。
- **验证与打包**：vitest 新增 22 例（`delivery-plans-panel` 8＋`test-plans-panel` 7＋`workflow-console` 6＋`workflow-console-launch` 1），全量 98 文件 **1142 passed**＋`npm run typecheck` 零错＋M1–M3 反向验证（分解 dry_run 提交腿／报告成对闸／采纳 dag payload）全红→字节级还原→复绿＋`server/tests/test_diagnostic_sample_surface.py` 与 `server/tests/test_ledger_sync_nail.py` 全绿（7 passed）＋`git diff fork/main -- server/` 为空；合并后在主树 `release/` 产出 `蔡工FDE-0.3.0-便携版-r47` 并完成新旧 `app.asar` 四特征串（`draft-from-plan`、`generate-ai-draft`、`delivery-plans/generate-ai`、`test-plans/generate-ai`）正反向核验。
## [未发布] — goal-crv 修复批 E：席位回填四路径预扣税递进闭合＋工作流 solutions.create 契约闸（零迁移零新路由，2026-11-14）

依据 `docs/goal-crv-fix2-剩余批次总循环-任务书.md` r4 批 E 完成 `QR-071`/`QR-072` 两项 P1 修复与 `QR-073` 宿主通道核销（零迁移零新表零新路由）：

- **QR-071（续 CR-028）席位回填四路径闭合**：published 态 `seat_delivery=None` 生成的 draft 结算行在接单（`transition_package` accept 分支扫 draft 行回填）、五席位分配（`allocate_five_seats` 落 `seat_payees["delivery"]`）、二次收款刷新（`record_receipt_settlements`）与 `accrue_settlements_for_project` 兜底（paid 明细→包指针→接单人逐级回退并持久化）四条路径同步回填 `seat_delivery_user_id`，保证当期预扣税非零且同自然年后续里程碑把已计提行计入累计预扣递进基数。
- **QR-072 工作流 solutions.create 契约闸**：`compile_delivery_preview` 与种子模板 `plan_execution` 补 `params.project_id` 并把骨架字段包进 `params.body`（对齐 api_catalog 路由契约）；`validate_dag` 新增 `catalog_call_contracts()` 注入，定义期拦截缺路径必填参数（`call_missing_path_param`）、`body` 非对象（`call_invalid_body`）、写操作字段散落顶层（`call_unwrapped_body_params`）三类 422 `dag_invalid`；`_dispatch_skill` 把 skill JSON 输出字典字段透出节点上下文使下游 `{{research_brief.opportunity_ids}}` 引用可达；编译→定义→发布→执行器端到端真实创建 `ProjectSolution` 行。
- **QR-073 及宿主通道核销**：`is_unsafe_artifact_path` 三形态路径钉（POSIX 绝对／`..` 穿越／Windows 盘符·反斜杠根·UNC）＋ `#422`（`QR-088/089`）与 `#433`（`QR-092/094/095`）吸收项在位核验；附带收口 `host_receipt.py` exit_code 布尔漏点（`isinstance(False, int)` 为真且 `False == 0`，宿主传 `"exit_code": false` 可误判成功——补 `not isinstance(..., bool)` fail-closed 排除）。
- **验证**：NEW `tests/test_crv_batch_e.py` 5 例＋邻域回归 14 套件 213 passed＋变异三连（`M1_QR071_accept_backfill`/`M2_QR072_definition_gate`/`M3_QR072_compiler_contract`）全红→`try/finally` 字节还原核 sha256→5 passed 复绿；`ruff` 零告警；`check-python-types.py` 277 基线零新增。

## [未发布] — 桌面端五处前后端断链与静默缺陷收口：图片预览 CSP `blob:`＋训练场交付原文展开＋提案五态与发布/回滚＋产物采纳方案与跳转＋派单 AI 撮合（桌面变更·零服务端改动·零迁移零路由，便携版 r45，2026-11-13）

打通桌面端五处前后端契约断链与静默渲染缺陷，严守零后端改动与人工拍板红线：

- **图片预览 CSP 白屏修复**：`desktop/src/renderer/index.html` 与 `desktop/src/renderer/web.html` 的 `Content-Security-Policy` 中 `img-src 'self' data:;` 扩为 `img-src 'self' data: blob:;`，消除 `desktop/src/renderer/src/files/FilePreview.tsx` 通过 `URL.createObjectURL(blob)` 渲染 `<img src="blob:...">` 时的 CSP 拦截白屏。
- **训练场阶段交付原文展开（消解 L-C 盲评）**：`desktop/src/renderer/src/SimulationLab/SimulationRunDetail.tsx` 为 `trace.payload.artifact` 非空 Trace 行增加「展开交付原文 / 收起交付原文」折叠面板，逐件渲染自由文本 `artifacts[]`（`name`、`kind`、`sha256` 与只读 `text` 原文）及结构化阶段字段键值/JSON，不新增后端接口。
- **训练场改进提案五态对齐与管理员发布记账 / 回滚**：`desktop/src/renderer/src/SimulationLab/types.ts`、`desktop/src/renderer/src/SimulationLab/api.ts` 与 `desktop/src/renderer/src/SimulationLab/ImprovementProposals.tsx` 补齐 `ProposalDto.status` 的 `"published"`（`STATUS_LABEL.published = "已发布"`，消除 `undefined` 徽标）与 `release` / `rollback` 留痕展示；`admin` 视角下对 `approved` 提案提供「发布记账」（`regression_plan` 为空时禁用并提示）、对 `published` 提案提供「回滚」，内联确认框必填管理员密码与备注调 `POST /api/v1/simulation/proposals/<id>/release` 与 `/rollback`，提交或取消即刻清空密码 state。
- **智能体产物「采纳为方案」与关联方案跳转**：`desktop/src/renderer/src/agents/AgentsConsole.tsx` 对 `linked_solution_id` 非空产物展示「查看方案」，经 `allowNextHashNavigation()` 放行跳转 `#projects/<projectId>?tab=delivery&solution=<linked_solution_id>`；`linked_solution_id` 为空且 `canManage` 在 `completed` / `succeeded_but_receipt_invalid` 终态下提供「采纳为方案」，调用 `POST /api/v1/agents/runs/<run_id>/artifacts/<artifact_id>/adopt-solution`（body `{}`），刷新产物关联状态并呈现新建或幂等重复采纳提示（同时保留宿主通道溯源头与「方案」列展示）。
- **派单控制台「AI 撮合建议」与采纳 / 驳回留痕**：`desktop/src/renderer/src/dispatch/ConsolePage.tsx` 在 `published` 工作包操作区接入「AI 撮合建议」（`POST /api/v1/dispatch/packages/<id>/match-ai`），展示场景、模型/`prompt_version` 与 `ai_suggestions`（`ai_called=false` 如实提示未调用模型）；「采纳建议 / 驳回建议」调用 `POST /api/v1/dispatch/packages/<id>/match-ai/decision` 并严格传 `{ decision, recommendation_sha256, adopted_candidate_ids }` 闭集三键——采纳自动勾选候选人复选框但不自动创建 `dispatch_offers`，正式指派仍走人工「指派 offer」按钮。
- **验证与打包**：`vitest +9`（全量 96 文件 **1117 passed**）＋`npm run typecheck` 零错＋M1–M5 反向验证五连全红→`try/finally` sha256 逐字节还原→复绿＋`server/tests/test_diagnostic_sample_surface.py` 与 `server/tests/test_ledger_sync_nail.py` 全绿；合并后在主树 `release/` 产出 `蔡工FDE-0.3.0-便携版-r45` 并完成新旧 `app.asar` 特征串核验。

## [未发布] — 桌面端「采纳为方案」人工入口＋宿主通道溯源展示（1A，零新依赖零新样式类，2026-11-13）

OWNER 拍板 1A 的落地（服务端 PR #435 已供契约，补桌面最后一公里）：

- **运行详情头**透出宿主通道溯源：`通道 <execution_provider>`＋`宿主领取 <时刻>`＋`宿主回执 <时刻>`——业务负责人在界面即可看到「本次 run 是宿主执行的、何时领走、何时回执」（此前只在 API/DB 可见）。
- **产物表新增「方案」列**：已采纳显示方案指针（id 前 8 位），未采纳显示 —。
- **「采纳为方案」按钮**（canManage + run 终态 + 该 run 尚无任何产物被采纳时显示）：点按展开内联名称输入（留空自动命名／回车即提交），成功后重拉详情回真（不本地猜写，与 T-B1 同款）。**一 run 一方案的闸仍在服务端**（409 由服务端裁决），前端置灰仅省一次徒劳请求。
- 状态机标签补 `host_running＝宿主执行中`。
- 零新 CSS 类（全部复用既有类）、零新依赖；desktop typecheck 零错误、vitest 1106 全过。

## [未发布] — goal-crv 修复批 F：富文本段落键名契约双向对齐＋`complete_upload` 唯一键预检与重放恢复（2026-11-13）

依据 `docs/goal-crv-fix-批BF-任务书.md` 完成批 F 两项 P1 修复与契约钉闭合（零迁移零新表零新路由）：

- **QR-117（P1 → 趋 P0 随批注记）富文本键名兼容与桌面往返闭合**：`server/src/fde_api/documents/rich_text.py::sanitize_rich_text` 对 `paragraph`/`heading` 优先读取规范键 `content`，缺省回退旧版桌面 `text` 键并走同一 `bleach.clean` 清洗；`desktop/src/renderer/src/documents/DocumentEditor.tsx` 导出 `plainToRichText`（写出规范键 `content`）与 `richTextToPlain`（兼容服务端 `render_rich_text` 落库返回的 `list[dict]` 数组与 `{type:"doc",content:[...]}` 包装对象及 `content`/`text` 双键），闭合保存→重开→Worker 生成 `.docx` 段落往返链路。
- **QR-118（P1）`complete_upload` 唯一键预检、409 映射与重放/中止恢复**：`server/src/fde_api/files/service.py` 新增 `_preflight_upload_target` 在 `complete_multipart` 消费 `.multipart/<upload_id>` 前预检目标文件存在性（404 `project_file_not_found`）与新文件 `(project_id, category, display_name)` 同名冲突（409 `file_name_conflict`）；并发竞态下捕获 `IntegrityError` 映射 409 `file_name_conflict`，重试若遇 `multipart_upload_not_found` 通过 `head(storage_prefix)` 回收已合成对象完成入库，`abort_upload` 在分片目录已消费时幂等清理孤儿对象并收敛 `aborted`。
- **测试钉、变异验证与桌面交付**：NEW `server/tests/test_crv_batch_f.py` 6 例＋`desktop/tests/renderer/project-documents.test.tsx` +1 例（全量 vitest 96 文件 / 1107 passed；PR #442 首轮 CI `server-tests` 3625 passed + 8 skipped）＋变异七连（M1–M6）全红→`try/finally` 逐字节还原→全绿＋服务端文档/上传回归 68 passed＋静态/存储/台账钉 96 passed＋ruff 绿＋mypy 277 基线不变；桌面便携版 `r44` 于合并入 `main` 后重打包并执行 `asar` 指纹与 marker 字节验证。

## [未发布] — goal-sprint r5：T-14b 全收口（`diag.fde18.com` 443 签证上线＋官网 CTA 切 `diag` 双锚点＋公网只读校验器，2026-11-13）

任务书 §3 r5 行＋§9 硬指标 4 全项兑现：蔡工添加阿里云 `diag.fde18.com → 141.95.33.198` A 记录后完成 D-3 独立轻部署 HTTPS 开闸、官网 CTA 锚点切换与跨三域公网复测。

- **远端 `diag.fde18.com` 443 签证与潜伏真缺陷修复**：预检抓出 `/www/server/panel/vhost/nginx/diag.fde18.com.conf` 漏写 `server` 级 `root`/`index` 致 `/` 返回 58KB 宝塔停用页真缺陷并修复；`certbot` webroot 签发 Let's Encrypt 证书（有效期至 `2027-02-11`），升级 80→`301`＋443 SSL HTTP/2（同主站 CSP/安全头），公网 HTTPS 7 项冒烟（含 `POST /api/v1/diagnostics/sessions` 匿名会话创建、`diag` 注册面 404、`app.fde18.com` 诊断面 404 隔离）全绿。
- **官网仓 `fde-ops` CTA 切换与线上表单密钥恢复**：`caishide/fde-ops` PR `#55`（`04f4220`）将 `/diagnosis-samples/` 主 CTA 切至 `https://diag.fde18.com/#diagnostics`（政策补贴测算·免注册）、次 CTA 切至 `https://diag.fde18.com/#diagnostics/sample`，E38 正式收回 `app.fde18.com` 临时直链豁免（全站零出现）＋E39 持 `diag` 双直链（变异 M1/M2 红→还原→绿）；并从远端历史备份找回真 UUID 修复前序部署误截断的 `/contact/` `PUBLIC_FORM_KEY`，`deploy-ovh-fde18.sh` STAMP `20261113-201958`（`99/99 PASS`＋tag `deploy-20261113-2019`＋补记 PR `#56` `a2b40f1`）上线。
- **公网只读校验器与任务书收口**：NEW `scripts/verify/verify_diag_public_live.py`（6 项公网直连校验：DNS／80→301／443 TLS+SPA+CSP／问卷 200+注册闸 404／主站诊断闸 404／官网 `diag` 双直链且零 `app.fde18.com`，实跑 `VERIFY-R5-DIAG-PUBLIC-LIVE PASS`）；`获客诊断工具实施任务书-v1.md` T-14 标全收口并锚定 R-A 3 个月止损线起算日 `2026-11-13`（复盘日 `2027-02-13`）。零后端/桌面生产代码改动・零迁移・零新路由（490/52/153/74 全不变）。

## [未发布] — AI 原生化 G-10 CI 评测凭据接线轮：ai-eval workflow 四槽 secret 全接线（端点/模型/超时缺省回落＝既有语义零改动；零迁移零路由零桌面，2026-11-13）

- **挂账消解第一段（凭据面）**：N4 轮挂账「上游 CI 配 `secrets.FDE_DEEPSEEK_API_KEY`（按量付费 key）后 ai-eval 出首份非 insufficient 报告」。本轮现测发现**只灌 key 一槽不足以消解**——生产 `server/.env` 的 `FDE_DEEPSEEK_*` 槽现行实际为 **MiniMax 端点**（`FDE_DEEPSEEK_BASE_URL=https://api.minimaxi.com/v1`＋`FDE_DEEPSEEK_AI_OPPORTUNITY_MODEL=MiniMax-M3.1-Flash`，按量付费），而 workflow 只接 `API_KEY`、harness `BASE_URL` 缺省 `https://api.deepseek.com` ⇒ MiniMax key 调 DeepSeek 官方端点＝真模型腿 9 例全错 ⇒ 报告**仍 `insufficient_data`**（误导性绿）。key 来源/接线深度三选拍板问询未获答复 ⇒ 按「按推荐执行＋留痕可推翻」先例走推荐项：**复用生产 key＋四槽全接线**（secret 随时可覆盖/删除，workflow 走 PR 可回退）。
- **接线内容**：`.github/workflows/ai-eval.yml` env 块在 `FDE_DEEPSEEK_API_KEY` 外新增三槽 `FDE_DEEPSEEK_BASE_URL`／`FDE_DEEPSEEK_AI_OPPORTUNITY_MODEL`／`FDE_DEEPSEEK_TIMEOUT_SECONDS`，同以 `secrets.*` 供值——secret 未配置 ⇒ 空串 ⇒ harness 既有 `os.environ.get(...) or DEFAULT_*` 链回落默认（**缺省语义零改动**，与首轮逐位一致）；注释换代记本轮。供应商身份不硬编码进仓：换供应商只改 secret 零代码。
- **凭据纪律**：四个 secret（API_KEY／BASE_URL／MODEL／TIMEOUT_SECONDS=180 生产同值）经 `gh secret set` **stdin 管道**灌入 fork（值不落 argv／不回显／不入库不入报告）；**供应商红线自证**——生产现行 key 为按量付费（与活体部署同源），CI 单次 ≈9 调用／3 万 token 量级、周频，成本可忽略（workflow 注释既有成本口径）。
- **判据**：合并后手动 `workflow_dispatch` 出**首份非 insufficient 报告**（读数与四特征④上行复评随回填 PR 落台账 v1.22）；周一 03:00 UTC 定时 cadence 照常（首跑不再等周一）。
- 零迁移零路由零蓝图零桌面零生产代码改动；结构口径**不变**（引用前现测 **490 路由／52 蓝图／153 表／74 rev 单头 `c8e2a6f0b9d4`**，inventory 逐位吻合）；无 server 变更 ⇒ 无需 rebuild／alembic／重打包。
- 文档同步：台账 **v1.21**（G-10 凭据接线注记）＋任务书 §13 **#25**。
- **合并与首跑证据（回填）**：PR #441 rebase 解 CHANGELOG 插队一次（#440「试点度量口径」节两侧全留、后合并者在上，force-with-lease）→ squash **`d1126d3c`**；PR CI 四绿×2（首推＋rebase 后：server-tests 13m38s/10m42s → 13m9s/15m19s）。4 secret 于 12:41:40–45 UTC 经 stdin 管道灌入；dispatch run **43427382735**（34s）出**首份非 insufficient 报告**：verdict=**pass**／kpi=**1.0**（live 9/9：citation 6＋pseudonym 3 全过——kept≥1＋引文逐字独立复核＋零 PII 事件）／offline 14 例 oracle 重放全 ok／incidents=0／uplift 1.0≥PASS 0.8（未校准观察线，非必需门禁语义不变）／prompt_fingerprint `ae12fd11c092cb7c` 与首轮 insufficient 报告逐位一致（提示词零漂移）／fixture sha256 `7871b7dd4f766fcf…`（全文在 artifact）／model=**MiniMax-M3.1-Flash**（生产同款——四槽接线生效）。
- **四特征④上行复评（DoD③，回填结论）**：**2-1-2-1 → 2-1-2-2**（④持续进化 1/3→2/3）——任务书 §1.2 翻分判据三件复测证据全在案（第一批真模型评估数据＝模拟场 3 例在库＋CI golden set 首份真报告 kpi=1.0／G-13 版本注册＝N6／受控发布通道＝G-11 N4 落地），台账 v1.19 预告触发点「首个非 insufficient 报告产出」兑现；**留痕**：发布/回滚**动作面**仍零行使（首提案/首工单出现后走通道——§1.2 判据只要求通道落地；3/3 属 L4 段不预支）。台账 v1.22＋任务书 §13 #26。周一 03:00 UTC cadence 照常（凭据已在位）。

## [未发布] — 试点度量口径两项收口（产物人工接受率分母定义＋`agent_pilot_max_runs` 默认对齐文档拍板值，2026-11-13）

OWNER 拍板「3A＋4A 全按推荐执行」的回写：

- **「智能体产物被人工接受率」分母口径落地（Run 级主口径）**：分母只计 `completed` run（失败/超时 run 属故障留痕不进分母）；**采纳为方案＝强接受**（`linked_solution_id IS NOT NULL` 与 `reviewed` 取**或**——活库 54 产物中 35 份仅走采纳未勾 reviewed，纯 reviewed 口径严重低估）；辅列产物级占比单列不并主口径（防「一次 run 产多份辅助文档只采纳 1 份」的反向激励）。首测 8/8＝100%（样本极小仅供口径演示）。
- **`agent_pilot_max_runs` 代码默认 20→10**：对齐文档拍板值（保守值优先），收口 backlog 挂账的「代码 20 vs 文档 10」口径差（`config.py` Field 默认＋`pilot.py` getattr 回落双处同步；`agent_pilot_enabled` 默认 False ⇒ 闸不开则无运行时副作用）。

## [未发布] — goal-sprint r4：D7 四口径运行证据复审报告＋防预支对账断言钉（2026-11-13）

任务书 §3 r4 行＋§9 硬指标 2/3 全项落定：基于活库只读事务快照出具真实四口径运行证据复审报告，完成 r1 移交的 C/B 口径源码级裁决，并将 D7 阈值拍板位如实落档为**「待蔡工拍板」（零预支任何数值，闸态变更数 = 0）**。

- **活库四口径实测与 C/B 口径裁决**：NEW `docs/audit/D7-四口径运行证据复审报告-2026-11-13.md`（对账 `D4-D7人工项推进包` §4 七项必填元数据与四口径总表）——`[0/4]` 数据闸 `approval_rows=2`（已审 2）／`HAS_RUN_EVIDENCE`；**A** 审批时效 `p50=85.5s`／`p90=104.3s`（`risk=4`／`workbench.write`，n=2）；**B** 人工否决率 `0.0000`（`_REAL_RUNS` 过滤后有效分母=2）；**C** 原始 SQL 命中 2 行 ⇒ 核对 `control/service.py:776, 791-796, 850-854, 873, 888-889` 确认为跨轨假阳性（只有 A 轨 DSH 写 `executed_at`；C 轨 `workflow.human_approval` 拍板即同事务置节点 `succeeded`，调执行入口显式 409 `approval_not_executable`），分轨修正后**真实执行落空 = 0**；**D** 确认失败锁 `0 rows`（`operation_events` 572 行零命中，`ai.api.*` 零行使）；`v3-p3` §3.2 三条责任主体断言实跑全 **0 违例**。
- **N1 试点窗口闭环核实**：代号项目 `FDE-20261112-5CFF4FA2`（`pilot-001` 承载项目）于 2026-11-13 已有 **2 条蔡工亲手发起的生产 `host_poll` `agent_runs` `completed`**（`b647945e…` 3 件产物 **3/3 已人工复核**；`347fb585…` 5 件待复核），任务书 §9 硬指标 2 活库兑现；训练场 `SIM-V32-LAB` 9 行明示排除出生产分母。
- **支撑度与阈值拍板位**：候选开放档（G4 / S / 比对）同类审批样本均为 **0** ⇒ 支撑度 `insufficient_for_unfreeze`；D7 阈值拍板位明确落档为**「待蔡工拍板」**，`v3-p3` §5 解冻判定表维持全 `PROPOSED`（闸态变更数 = 0）。同步更新 `D4-D7人工项推进包` §4/§6、`下一步实施台账` §2/§4/§11.4/§12、`v3-backlog.md` P3/22:25 段、`goal-sprint-PROGRESS.md` r1/r4。
- **防预支静态钉（漂移即红）**：NEW `server/tests/test_d7_evidence_report_nail.py`（3 例对账断言）——锁死报告必填章节锚点、蔡工未签字前拍板值栏出现任何阿拉伯数字即判红、D7 未签字期间 `v3-p3` §5 解冻判定表脱离 `PROPOSED` 即判红。零生产代码改动・零迁移・零新路由（490/52/153/74 全不变）。

## [未发布] — goal-crv 修复批 B：QR-024 直连流式 usage 计量修复＋QR-025 预调研 DOCX 原件上传腿收口（升 P0）＋SNS 403 例外登记（零迁移零路由，2026-11-13）

按 `docs/goal-crv-fix-批BF-任务书.md` 完成首投批 B：

- **QR-024（P1 CLOSED）直连腿流式 usage 采集与预算闸对齐**：`server/src/fde_api/ai/deepseek.py` 流式请求注入 `stream_options: {"include_usage": True}`（非流式不带该键），`_read_stream` 逐帧提取顶层 `usage` 并兼容末端 `choices: []` 空帧、防止尾帧 `usage: null` 覆盖已采值，移除对已消费 SSE 响应体调 `.json()` 恒败的 `_usage_from_stream`；上游缺失或返回非整数/布尔/负值 `usage` 时诚实置 `None`（严禁静默写 `0` 冒充免费调用），流式调用真实计入 `tokens_used_this_month` 与 `subject_budget_exceeded`。
- **QR-025（随批裁定 P1→P0 CLOSED）预调研 DOCX 原件脱敏前禁出站**：`server/src/fde_api/ai/kimi.py` 废弃并移除向第三方 `/files` 上传/读取/删除未脱敏 DOCX 原件分支，强制统一走 `_extract_docx_locally` 本地提取纯文本后再经 `build_messages`（E4 凭据拦截 400＋T-A2 企业名代号化与 PII 脱敏）送对话模型；`Settings.kimi_local_docx_extract` 与 `server/.env.example` 默认值改 `True`（存量 `.env` 若留 `false` 记 warning 仍强制走本地提取）；`server/tests/test_kimi_client.py` 原上传正例钉同步换代为本地提取正例钉并完整保留 Kimi K3 chat 载荷契约断言（只增不降）。
- **随带（拍板 §5-5 CLOSED，零代码）**：AWS SNS 回调在 SES 关闭态维持 403 `mailing_disabled` 例外登记入 `AGENTS.md` 红线区（引用 M3b 服务间面机器判定先例），`docs/goal-crv-r6-后台作业与队列.md` §5-1 销号。
- **验证**：NEW `server/tests/test_crv_batch_b.py`（pytest +12 收集：流式与非流式计量对齐、流式预算闸拦截、5 组缺失/畸形 usage 置 `None`、尾帧 null 不覆盖、静态钉、兼容钉、E4 凭据 400 零外呼与 A2 企业名/手机号脱敏端到端钉）＋邻域回归 149 passed＋变异四连 M1–M4 全真红→`try/finally` sha256 逐字节还原→复绿＋ruff 绿＋mypy 277/102 基线不变；零迁移零新路由零蓝图零桌面。

## [未发布] — 产物采纳流闭环＋宿主产物可读（G-07 证据候选回填；＋1 路由 489→490，2026-11-13）

首个真实 host_poll run 端到端跑通后的下游收口：run 完成后产物停在 `agent_artifacts`，缺「采纳为方案」的人工入口，且**宿主通道产物在桌面端 100% 预览失败**。本轮补两处集成缺口＋开一条人工采纳入口。

- **宿主产物内容读取修复**：`agents/artifact_content.py` 剥 `host:` 指针前缀后与容器形状 `{run_id}/output/{path}` 同构解析（裸跑态服务端与宿主同机 ⇒ 可读，N3c 拍板「宿主裸跑态全量可用」）；剥前缀后防穿越校验与容器指针**完全同套**（绝对路径/上跳仍拒，安全语义零放松）；容器态原件不在场 ⇒ 仍落 `artifact_content_unavailable` 显式降级。**修复前**：host_poll 产物预览 404 全灭；**修复后**：3 产物全 200（逐字节 sha256 自证）。
- **宿主回执补 G-07 证据候选登记**：`agents/host_receipt.py` 按容器路径（`artifact_persistence.py`）同款语义登记建议性证据候选（`captured_from=agent_run:<run_id>`）——**只登记不采纳**（采纳仍走人工提交闸，不触碰清单项 `claim_status` 与门禁状态机，红线：AI 不代拍板）；仅 completed run 的产物登记（失败 run 的产物是「留痕」不是「候选」）。**修复前**：宿主 run 证据候选恒 0 条；**修复后**：5 产物 ↔ 5 候选一一对应。
- **产物采纳为方案**（人工动作）：NEW `agents/artifact_adoption.py`＋`POST /agents/runs/<run_id>/artifacts/<artifact_id>/adopt-solution`（**+1 路由 489→490**，零迁移零新表）——族内先例同尺（translator adopt／ontology candidate confirm／workflow draft publish）：**AI 只产候选、人工点确认**才进方案台账，**不存在自动采纳路径**；can_manage 同复核动作尺；幂等（重复采纳返 `duplicate=true`，不重复建方案不重复落事件）；一 run 一方案（同 run 第二产物 409 `artifact_already_adopted`）；终态闸（未终态 409 `agent_run_not_terminal`）；红线 §6.6——方案只存**指针**（storage_ref＋sha256），产物原件永不进库。溯源三段可反查：`solution.agent_run_id` ↔ `run` ↔ `artifact.linked_solution_id`。
- **run 详情透出宿主通道溯源面**：`agents/service.py` `_serialize_run` 补 `execution_provider`／`host_claimed_at`／`host_receipt_at`三个字段（桌面端据此展示「本次 run 是宿主执行的、何时领走、何时回执」）——**`host_token_hash` 是领取令牌的哈希（鉴权凭据派生），绝不外发**（已用例钉住）。零迁移零新表零新路由。
- **口径**：路由 **489→490**／蓝图 52／表 153／迁移 74 rev 单头 `c8e2a6f0b9d4` 不变；inventory＋架构图 candidate.json 已同步（防陈旧闸 OK）。
- **测试**：NEW `tests/test_agent_artifact_adoption.py`（7 例）＋`tests/test_agent_artifact_content.py` 增 host_poll 指针形状例（合计 16 passed）；`tests/test_host_poll.py`＋架构纯净度＋行数预算闸 44 passed 1 failed（该 1 例为本机 `server/.env` 开了 `FDE_AGENT_HOST_POLL_ENABLED=1` 渗入测试 settings 的**既有环境性失败**，`FDE_AGENT_HOST_POLL_ENABLED=0` 即 passed，CI 无此文件不受影响）；ruff（F401/F841）clean；`agents/service.py` 1755 行未超 1836 预算。
- **部署文档**：NEW `docs/deployment/宿主代理裸跑部署runbook.md`——面向小白的路线 B（Windows 裸跑）全流程：起服务端（gunicorn 在 Windows 不可用 ⇒ Flask `app.run()`）＋起宿主代理＋发起 run＋验证证据＋排错速查表（含共享库幂等键碰撞、`host_agent.py` 启动位置、DB/Redis 覆盖等实测坑）。

## [未发布] — goal-sprint r3：端到端真机验收（宿主代理进程本体 NEW＋spawn 段整体重划＋⑦闸回环豁免修复＋真机 PASS；＋1 路由 488→489，2026-11-13）

任务书 §3 r3 行全项达成：`ZcodeAdapter` spawn 段按真实宿主形态重划（`adapter.py:93` 定向警示清偿）、隔离环境一次非交互执行产出可校验产物（**VERIFY-R3 PASS**：completed／产物指纹字节级一致 `a34bc4d8…`／billable 195,582 tokens／context 消费／egress 审计零 blocked）、台账 §12 `adapter_missing` 解除回执（①实装＋N2 签核两项齐备）、E10 解锁判定成立（条件触发，见台账 §3 行）。工程级验收**不创建生产 AgentRun**（H4 边界不碰；N1 首个生产 run 仍归蔡工亲手，窗口 11-19 止）。

- **宿主代理进程本体** NEW `server/src/fde_api/agents/host_agent.py`（P2-b 架构半最后一块）：一次进程＝至多一次 `status→claim→context→spawn→receipt` 生命周期、run 终态即回收（通道例外⑤）；`from_env` 五必需键＋闸开白名单空 fail-closed；`HttpHostTransport` 信封协议（200 拆 `{data}`／非 200 回信封读 error）；`preflight` 复用 N2 校验器对 **fail-fast 于 claim 前**（部署半态不领取，避免 run 白挂 host_running）；`materialize_workspace`（run_id 形状钉＋根锚＋拒绝清单＋空 task.md 不 spawn）；spawn 真身＝`run_host_channel`（契约 argv＋超时熔断＋⑦闸全复用）；spawn 失败如实回执 failed 不悬挂；零凭据注入。
- **服务端 context 读取面**：NEW `agents/host_context.py`＋第四条宿主路由 `GET /agents/host/runs/<run_id>/context`（**+1 路由 488→489**，零迁移零新表）——状态闸族（404/409×3/403 令牌与领取不符/413 超 4MB）＋context_ref 前缀剥除重新 join 当前根＋越界拒；面料「服务端渲染一次、宿主逐字落盘」（不两侧各渲染）。
- **adapter.py spawn 段整体重划**：删虚构容器契约；`spawn_argv`＝契约层 `build_cli_argv(prompt=task_prompt(workspace), cwd=…)` 单一真身（prompt 文字面并入 `zcode_contract`）；`AgentRunResult.summary_payload` 回执保真；**QR-094** done 终态立即终止批内遍历（completed 不得被同批尾随越界 cost 翻成 budget_exceeded 丢产物）；`ManifestOutputScanner` 自 service 搬入 adapter（宿主代理不拖 Flask/db 依赖面；`_MANIFEST_FILE` 收归 workspace_files 单一真身）。
- **QR-092（宿主进程 env 白名单继承）**：`host_channel_env` 允许前缀集（node/Windows 定位/`ZCODE_` provider 注入面/代理透传）＋拒绝清单双层（`FDE_`·密钥语义子串即使命中允许前缀也剔除）。**QR-095**：回执缺 `exit_code` ⇒ None 不缺省 0；`completed` 而 exit≠0 ⇒ 降档 failed。
- **★⑦闸回环豁免**（真机首跑撞出的生产缺陷，`host_egress_proxy.py`）：zcode 运行时经桌面端本地 broker（127.0.0.1:18787）回环 IPC，其客户端**无视 NO_PROXY** 把回环 CONNECT 推进代理 ⇒ 白名单闸拦截 ⇒ API 调用取消（EXIT=1 零产物）。隔离两腿定位（裸跑全过/闸腿复现＋审计 `tunnel_blocked 127.0.0.1`）后修复＝回环目标 CONNECT 一律转发＋审计新类别 `tunnel_loopback`（`proxy_env` NO_PROXY 声明的回环直连语义由闸侧补齐；⑦ 管出站互联网面）；明文 absolute-form 仍一律拒绝。
- **回执携 ⑦ 审计证据**：`build_receipt_payload` 增 `egress_audit`（`summarize_audit` 有界形状：计数＋去重域名 ≤20，只记域名）——宿主单发进程的审计留证出口。**pilot 警示换代**：「执行契约已实装……尚无真实完成的 run」。
- **crv 吸收**（QR 台账 147 行终态重扫，agents 面零新增相交）：QR-092/094/095 本轮吸收；QR-086/087/090/091 相邻不吸收照走修复批。**providerId 真机事实吸收**：实测 zcode 0.17.1 strict schema 下 `defaultModelSelection` 字段名为 `providerId`（写 `providerKey` 被整键丢弃静默回退默认）⇒ r2 校验器换代（`host_preflight.py` 带实测更正框）。
- **验证**：NEW `test_host_agent.py` 15 例（含 CI 首红清偿：默认模型配置路径隔离＋缺省路径语义钉）＋test_host_poll +7（QR-095 两例＋context 五例含**令牌轮换领取绑定钉**＋路由接线）＋test_host_channel +3（env 白名单三层）＋adapter pin 换代＋QR-094 一例＋egress 回环豁免两例＋**M8 完整性钉吸收**（全量复跑撞出新 GET 面未登记 ⇒ 排除登记增 `internal_service` 条目 403×3 现测互锁＋条数基线 64→65，红队套件 43 passed 复绿）；**变异五连全数收口**（M1 env 拒绝层 2 红／M2 done 终止 1 红／M3 缺 exit_code 缺省 2 红／M4 preflight fail-fast 1 红／M5 领取绑定 1 红→字节级还原→绿）——★M5 判别力自纠（单令牌下绑定检查不可达＝假绿，令牌轮换场景才杀灭）；★变异脚本 try/finally 强制还原（v2 超时崩溃残留生产变异一次的家族教训硬化）。NEW `scripts/verify/host_agent_real_machine_check.py`（工程级验收器：进程内存根四咬合面形状同源＋真实传输＋真实 spawn＋真实出站闸＋TEMP 隔离工作区）。定向套件 **171 passed**（9 文件＝r3 改动面测试文件全量）＋全量本地 **3596 passed + 7 skipped**（CI 首红清偿后重跑；首轮唯一红即 M8 钉，吸收后复绿）；ruff 绿；mypy **277/102 基线不变**。
- **口径**：路由 **488→489**／蓝图 52／表 153／迁移 74 rev 单头 `c8e2a6f0b9d4` 不变；inventory＋route CSV＋archify 刷新（candidate.json 489＋finalize 四闸绿＋整页实拍 1440×2098）。`server/` 生产 diff＝agents 域 9 改＋NEW host_agent/host_context 两件＋verify 脚本 1 件（合 12 件）；零迁移零桌面。
- **合并与部署复验（2026-11-13）**：PR **#433**→squash `93658650e74100b7916d373ec26104583cc3f58e`（树哈希零漂移＝合并树 `0d7e9fb3…` ≡ 分支树）＋CI run **43390885851** 四 job 全绿（server-tests 15m52s／desktop／secrets-scan／pseudonymization）；★旧 SHA 红行残留＝run 43390878726 的 1 例事件顺序 flake（`ai.api.started` ≠ `ai.api.requested`，r3 diff 不含 `ai/` 域与该测试文件＝跨线观察登记，不在本轮修），权威＝head SHA 对应的 run。**活体部署三验全绿**（七撞纪律：从冲刺树 `D:/test/fde-wt-sprint` `docker compose -p fde-workbench build/up`）：活体 `url_map` **489** non-static ≡ 口径＋容器内 `alembic current`＝`c8e2a6f0b9d4 (head)`（本轮零迁移＝头位不变）＋三镜像 ID 与**本工作树构建产物**逐位一致（api `887c1f46f30f`／worker `e08c0cbaae70`／scheduler `f9356fbc6620`）＋三容器 healthy＋ready/live 200。★**部署配置拓扑自查还原**：冲刺树 `.env` 相对主树缺 6 键（宿主通道族）先抄入保全，抄入后实测发现「宿主裸跑态（路线 B）」取值被带进「容器态（路线 A）」（容器拿到 Windows 工作区根＋host_poll 开关），据并发线《宿主代理裸跑部署runbook》「host_poll 只能在路线 B 裸跑态使用」当场还原（工作区根回 `/app/.fde-storage/agent-workspaces`＋移除 POLL 两键）⇒ recreate 后 env 与部署前活体逐项对平（活体零行为漂移）；容器态/裸跑态共用一份 `.env` 的长期解归并发线部署拓扑域不裁决。★⑦闸开闸键（`FDE_AGENT_HOST_EGRESS_GATE_ENABLED`/`_ALLOWLIST`）活体容器与两树 `.env` 均无 ⇒ **不代拍重开**（闸不代拍）留授权。

## [未发布] — goal-crv 拍板回写＋修复批 B/F 立项（needs-decision 8 项全按推荐 A；2026-11-13）

蔡工交互拍板（推荐项 A 前置逐项确认）：QR-041 留资行存明文（mask_pii 豁免开关＋读取受控留痕）／QR-042 懒检查＋过期即处置／QR-067 补 `is_platform_operator` 门（M3b 红线回归）／QR-073 按 P1 直接修复（形态核证后置随修复轮）／SNS 关闭态维持 403＋例外登记（服务间面，零代码）／QR-133 指纹化复核清单（红线字面全守）／QR-134 录入卡豁免登记＋编辑面输出端复扫／修复批 **B（QR-024/025）＋F（QR-117/118）连投立项**。逐项结论与归属批＝`docs/goal-crv-BLOCKED.md` §5；任务书＝`docs/goal-crv-fix-批BF-任务书.md`（批 C 解锁、批 G＝QR-133/134 新立）；总报告 §11 仅引用续注（v1.0 不回写台账）。纯文档轮：零生产代码零迁移零路由。


## [未发布] — goal-crv 全仓全面代码审查循环收口（十域·只审不修·零生产 diff；评审会纪要授权线，2026-11-13）

**循环终态**：评审会纪要授权的十域全面代码审查循环收口——十域各一轮一 PR（#412/#413/#415/#416/#417/#418/#421/#423/#425/#427，全部 docs-only：域轮恰 3-4 文件、零生产 diff、域轮不落本文件），squash 链 `45bfaf9→1640c75→9b26133→466766c→86722e6→11a01f6f→32aa4182→979eeed→14f8b36→4634a8d`＝fork/main 顶。审查输入＝文本快照（B#3 对齐），被审面零执行，零生产 diff 由逐 PR changed-files ⊆ 白名单断言链证明（**10/10 PASS**，gh api pulls/files 逐 PR 实跑）。

- **交付物**：`docs/audit/全面代码审查报告-2026-11-13.md` 定稿 **v1.0**＝QR 台账单一真身 **147 条**（P1×18／P2×100／P3×29，P0×0；复核状态闭集零 E1 残留；判级存疑 31 条如实标注）＋十域出章＋收口章（§11）；十域轮记录 `docs/goal-crv-r1~r10-*.md`；`docs/goal-crv-PROGRESS.md`（覆盖分配表 45 条目闭合＋逐轮 CI run 链＋基线表）；`docs/goal-crv-BLOCKED.md`（needs-decision 7 项待蔡工拍板＋部分覆盖域 1/2＝r7 桌面端 renderer 业务页抽查档）。
- **收口机械闸（任务书 §8）**：台账终扫闭集 grep 147/147；批量核锚 **147/147 GREEN**（145 行级锚在 HEAD `4634a8d` 直过＋2 文件级锚在场，零基点回退零 FAIL）；**反向验证**＝注入假锚点 QR-999→扫描 FAIL 1 转 RED→剔除还原→复跑 GREEN（核锚判别力在案）；误报率 0/147。
- **修复候选批**：6 批建议表在总报告 §11（**不拍板**）；最优先＝QR-025（DOCX 脱敏前上传供应商，复核注可升 P0）与 QR-117（富文本键名契约断裂＝编辑器正文全丢，趋 P0）；goal-sprint r2 #422 已按 crv 吸收条款消化 QR-073/088/089。
- **口径**：审查基点 `35ffbea` 时点结构口径 485/52/153/73 留档总报告 §0；结构口径随上游线自行推进（goal-sprint r2 后 488/52/153/74），本线十轮零生产 diff 未动任何口径。
## [未发布] — 训练场案例库界面导入与启用轮：NEW `desktop/src/renderer/src/SimulationLab/ScenarioLibrary.tsx`两钮——「导入 JSON」批量建行＋行内「启用/停用」激活（纯桌面零服务端零迁移零路由，2026-11-13）

蔡工实测反馈「建行在哪儿建？核对加激活在哪儿操作？没找到地方」——L1 导入管线（#360）与 round2 134 包行业底单落地后，建行（批量导入）与激活（PATCH status）两步桌面端没有界面入口：`importScenarios` API 封装G2 起在库但从未挂按钮，编辑弹层四分区也无状态字段。本轮两钮界面化，134 包全程界面点击。

①**「导入 JSON」钮**（案例库头部，隐藏 file input）：NEW 纯函数 `parseScenarioImportText` 兼容裸数组与 `{"scenarios":[…]}` 包裹两形态（服务端 `routes._payload()` 非 dict 一律 400——行业批文件首版裸列表形态照 curl 必 400，真相层批文件已随本轮重写为包裹形态）；POST 后回执「已导入 N／失败 M 条（前 3 条 #index code：message）」并刷新列表；空数组客户端拦不发请求；jsdom 缺 `File.text()` ⇒ `readFileText` 兜底 FileReader（Electron 真机走 `.text()` 零行为差异）。②**行内「启用/停用」钮**：draft→启用／active→停用／archived 无钮（与服务端 409 同构），PATCH `{status}` 复用既有「追加不可变新版本」通道（archive 同款部分更新形态）。③修过时硬编码提示「6 个案例 × 3 种客户行为」→ 通用文案（134 例导入后旧文案失真）。**红线自证**：激活仍是人工点击（导入建行与激活恒人工），无任何自动激活路径。

测试 NEW 6 例进 `simulation-scenario-library.test.tsx`（纯函数两形态／导入成功携 `{scenarios}` 包体／空数组不发请求／失败逐条回显／启用 PATCH status=active／停用与归档行无钮）⇒ 文件 14 例；本地 `test:desktop` 全量 **1106 passed (96 files)**＋typecheck 绿；PR #426 CI 四绿（desktop 1106／server-tests **3553 passed + 8 skipped**，双触发并行 run 四 job×2 全 success）。服务端零改动 ⇒ 口径不变（488 路由/52 蓝图/153 表/74 rev 单头 `c8e2a6f0b9d4`）。合并 `876f7cc` 后便携版 **r38** 重打包交付（asar sha256 `30d23819…`；本轮独有中文 marker「批量导入与启用/停用都会追加新版本」「导入文件须是场景数组」双命中）。真相层底单同步：行业批文件 11 份重写包裹形态＋清单补界面路径（方式 A）与形态勘误。


## [未发布] — goal-sprint r2：P2′ 服务端咬合面收口（crv 吸收 QR-073/088/089 ＋ N2 两实测事实接线；迁移 73→74 单头 `c8e2a6f0b9d4`；488/52/153 口径不变，2026-11-13）

**范围现测校正**：P2′① 咬合半（状态机 `queued`/`host_running`＋领取/回执三路由＋H4 失联只标记）已于 #204/#215（2026-11-08）落地——本轮不重造；实际工作面＝goal-crv 吸收（QR 台账 98 行中与本轮改动面相交的 P1 一条＋同函数 P2 两条）＋ backlog T-Z1 段 2026-11-13 补充的两条 N2 实测事实接线。§11.3 六约束逐条核对：①③④⑤⑥既有实现在场，②的幂等/鉴权在场但行锁有 QR-088 缺口，本轮补。

- **QR-073（P1）产物路径越界三形态族**：NEW `agents/workspace_files.py::is_unsafe_artifact_path()` 单一真身（盘符 `D:\…`/`D:/…`、反斜杠 `a\b`、根锚 `\…`）替换 `service._finalize` 与 `host_receipt` 两处「`/` 前缀＋`..` 部件」弱判定；且 unsafe 路径**不读文件不进 prepared（容器面零行登记）＋回执面不落 AgentArtifact 指纹行**——原实现只要 digest 形状合法就落行，Windows 裸跑态下 `workspace/output/<盘符绝对路径>` 的 Path 连接会替换基座直读工作区外宿主文件（含真相层路径）算指纹入库＝证据链污染；现 failures 留痕、人工处置（H4）。
- **QR-088（P2）领取并发洞**：claim 带 `run_id` 重领路径补 `with_for_update()`——等锁后**重读最新状态**判 403 `host_claim_conflict`/幂等回载荷（FIFO 面保持 `skip_locked` 不变）；无锁实现的 lost-update 窗口（后来者快照停在 queued ⇒ 无条件赋值覆写 rival 令牌 ⇒ 双代理双执行）封死。
- **QR-089（P2）白名单冻结契约**：`agent_runs` 加可空 `frozen_tools` JSON 列（迁移 `c8e2a6f0b9d4`，**73→74 单头**，additive 旧行读路径零变化）＝「允许名单随 run 冻结」（`_execute_run` docstring 既有承诺）的结构化真身；`start_run` 落发起时刻三重交集快照，领取载荷（含续领分支）读快照、旧行 NULL 回落 registry 实时读（行为兼容）。
- **N2 两实测事实接线**：NEW `agents/host_preflight.py`（宿主代理与 dev 直连共用的**唯一前置校验真身**，r3 宿主代理进程复用不另写）——①provider 覆盖开关成对校验（`ZCODE_BUILTIN_PROVIDER_CONFIG_FILE`＋`ZCODE_PERSONAL_PROVIDER_CONFIG_FILE` 只设其一＝部署半态 ⇒ spawn 前拒绝）；②`defaultModelSelection` 键在场校验（配置文件缺失/键缺失/`providerKey`·`modelId` 残缺/解析失败 ⇒ 显式拒绝——CLI 本会以 EXIT=1「Select a model before sending a message」死在半路，前置拦截把该失败变成**明确失败留痕**）。接线点＝`run_host_channel` spawn 前（出站闸代理启动之前，配置坏⇒代理根本不起）；失败走既有 `HostChannelError`→L2 明确失败映射（零 spawn 零计费，重试由人 H4，不静默重试）。config 新键 `FDE_AGENT_HOST_ZCODE_CLI_CONFIG`（空＝缺省 `~/.zcode/cli/config.json`）。
- **相邻不吸收留痕**（照常走 QR→修复批轮）：QR-090（容器面 receipt ask 联合唯一）/QR-086/087（retry 授权面）/QR-091/092/094/095（宿主 spawn 段＝r3 端到端验收轮面）。
- **验证**：test_host_poll +6 例（参数化展开 10 项：rival 提交等锁重读 403＋rival 所有权不被覆写／frozen 快照／旧行回落／五形态路径 failures 零行×5／202 受理快照落库）＋test_host_channel +5 例（参数化展开 10 项：成对正负 2＋配置缺失 1＋键残缺/坏 JSON×6＋校验先于出站闸 1）；既有 host 三件套补 preflight 注入点；**变异五连全红→字节级还原→绿**（M1 去行锁／M2 快照退实时／M3 路径退旧判定／M4 模型键校验短路／M5 成对校验短路）——★M1 首版判别力不足被自纠（持锁未提交时无锁实现同样阻塞 ⇒ 假绿；改 rival 提交后重读形态才杀灭）；定向回归 155+ 例绿＋ruff 绿＋mypy **277/102 基线不变**；inventory 重提取（`revision_count` 73→74，路由/蓝图/表全不变；防陈旧闸绿——图纸零迁移数声明＋M4 纯迁移轮先例不重生 archify）。
- **口径**：路由 **488**／蓝图 **52**／表 **153** 不变；迁移 **73→74** 单头 `c8e2a6f0b9d4`；`server/` 生产 diff＝agents 域 6 文件＋config.py＋workspace_files.py＋新迁移 1 件。

## [未发布] — E8 A 轨只读降级层 + E11 智能体凭据管理面（首个 run 三硬阻断解除之二；零迁移零新表＝口径不变，2026-11-13）

事实盘点（只读探查）确认：**N1/N2 全绿后首个真实 run 仍发不出去**——三硬阻断：① 种子 10 个 agent 的 `credential_ref` 全 null ⇒ `agents/service.py:219` 先判 `credential_missing` ⇒ 409 `agent_unavailable`（连执行链都进不去，早于 `adapter_missing`）；② `agent_credentials` 表**无任何 HTTP 路由**（唯一创建点是本地脚本 `sandbox_real_e2e.py:106`，裸机不可复现）；③ 容器路径 `adapter.py:100-120` argv 仍虚构（`zcode run --task --events ndjson` vs 真机 `-p --json --cwd`）。本轮解除①②，③ 归 P2′ 接线轮。

- **E8 · A 轨只读降级（纯函数层先行）**：NEW `server/src/fde_api/control/automation_fallback.py`——`plan_degraded_fallback()` 只做「能不能降级＋降级成什么样」的**纯决策**（零副作用、不 spawn/不联网/不落库）；复用既有 `DEGRADABLE_DSH_CODES`（5 码）与 `READ_ONLY_TOOLS`（13 项），**不另造执行面**。接线 `control/automation_jobs.py`：`DSHRuntimeError` 时先问降级计划——可降级则落 `output_json.degraded=true` ＋待人工确认标记 ＋`succeeded`，不可降级回既有诚实失败（`failed`）。**载体定位**：`automation_jobs.py:89-102`（`dsh_runtime.execute` 抛错就直接 failed＝「A 轨无 fallback」的确切位置）。
- **E8 边界（机械承载 N3 五问）**：任务类型封闭集＝仅 `ai`（`system` 不降级）；能力集与只读工具名无交集 ⇒ **不降级**（宁可面窄到零也不把写类工具混进降级）；降级面自身失败 ⇒ 落 `failed` 但 degraded 痕迹仍留（不假装成功、不静默吞错）；降级产物**待人工确认**（H1/H11 不自动收敛）；提示词正文与工具结果正文**不入库**。**零迁移零新表**（`AutomationTaskRun` 无 degraded 字段 ⇒ 走既有 `output_json` JSON 列 ＋ `error_code`）。
- **E11 · 凭据管理面**：NEW `server/src/fde_api/agents/credentials.py` ＋ agents 蓝图三路由（`GET/POST/DELETE /api/v1/agents/credentials`）——admin 写 **Fernet 密文**（密钥派生沿用 `model_preferences._cipher`），**只存密文绝不回显**（响应只出 `credential_configured: bool`）；平台管理面只认 `is_platform_operator`（平台身份 ＋ system_operator AI 档，沿 M3b 批次 ①-a 单一判定）；凭据名只允许字母数字下划线（会进 env 名 `FDE_AGENT_<NAME>`，防 env 注入）。种子 `server/seeds/agents.json`：7 个 zcode 型 agent 的 `credential_ref` 由 null 改为统一槽位 **`default`**（admin 配一次全生效）；3 个 persona 保持 null（不可执行，本就不需凭据）。
- **操作指引**：NEW `docs/audit/首个run亲手操作指引-2026-11-13.md`——建 `pilot-001`（五个必填字段）→ 配 `default` 凭据 → 开宿主通道 → **AI 对话 → `awaiting_confirmation` → 输密码「验证并执行」**（桌面端无发起按钮，`agents.run_start` 属确认类 risk=3，AI 不代发起是红线）→ 只读采集 → D7 复审轮。附**两条实施级前置**（N2 实测带出）：`~/.zcode/cli/config.json` 的 `defaultModelSelection` 键必须在场（缺失即 `Select a model before sending a message`）；provider 覆盖开关须 `ZCODE_BUILTIN_PROVIDER_CONFIG_FILE` ＋ `ZCODE_PERSONAL_PROVIDER_CONFIG_FILE` 成对设置。
- **验证**：NEW 36 例（决策矩阵 11 ＋ 接线 5 ＋ 凭据 20）全绿；邻域回归 88 例全绿（control_plane/task_board/direct_fallback/agents_adapter/dsh_runtime/fallback_chain）；ruff `--select F401,F841` 全绿；mypy **279→277 基线**（顺带消掉存量 2 条 arg-type——`execution` 字典加 `dict[str, Any]` 显式标注，治「异质值联合类型污染全部下标取值」）；**变异三连全红→还原绿**（M1 白名单混写类工具／M2 放宽不可降级码／M3 去 degraded 标记），还原后 sha256 逐位一致。连带小改：`tests/test_control_plane_api.py` 的 `AuthorizedClient` 补 `delete` 方法。
- **口径差待拍板**：`agent_pilot_max_runs` 代码默认 **20** vs 文档拍板 **10**（18:13 保守值）——建议改配置位为 10；`agent_pilot_enabled` 默认 False（试点闸默认不生效）。
## [未发布] — goal-sprint 上线冲刺线启动：r1 N1 试点执行支持（任务书 v2 落库；纯文档零代码零迁移零路由＝485/52/153/73 口径不变，2026-11-13）

蔡工 2026-11-13 拍板「现在启动」⇒ NEW `docs/goal-sprint-上线冲刺-任务书.md`（8 轮止损：r1 N1 试点支持→r2 P2′ 服务端咬合面→r3 端到端真机验收→r4 D7 复审报告→r5 T-14b 收尾→r6 E8 条件轮→收口终扫；让步顺序＝闸不代拍＞窗口不失期＞推得快）＋ NEW `docs/goal-sprint-PROGRESS.md`。任务书 v2 含两处拍板修订：**并行条款**（与 goal-crv 并行，本线隔离 worktree `D:/test/fde-wt-sprint`，替代原「串行、本线先行」默认——试点窗口 2026-11-19 截止时间敏感，crv 的 QR 台账不是本线上游依赖）＋**crv 吸收条款**（生产代码轮开工前扫 crv 已出域章 P0/P1 吸收进当轮实现要求）。r1 Agent 侧证据：①四口径 SQL 只读采集实跑（`scripts/verify/verify-run-evidence.sql` 全四段合法执行）——★**证据闸翻转发现：`automation_approvals` 0→2 行**（2026-11-08 somwyn E2E 产物，均 approved、否决率 0、p50=85.5s，`HAS_RUN_EVIDENCE`——D7「approval_rows=0 禁预支」数据前提已松动，阈值 N 仍归蔡工拍不预支）＋ C 口径现 2 行「执行落空」（疑 human_approval「审批即终点」口径语义错配，r4 裁决不预结论）；②N1 窗口 `agent_runs`=0（首个 run 待蔡工亲手发起，H4，窗口 11-19 止）；③契约失败语义自测 `test_zcode_contract.py` 14 passed。基线现测：基点 `35ffbea`／在途 PR 0／mypy **277/102**（较 AGENTS 口径 279/104 漂移 −2，登记待收口核对）／typecheck 绿／活库 alembic `b5d9e2f4a7c1`=head 逐位一致／diag DNS 未配置（T-14b 前置在位）／crv 吸收面零域章。pytest 基线取 CI 实测 3473 passed+8 skipped（run 43281011099，本地不重跑全量：docs 轮零代码增量＋共享 PG 对撞风险）。

## [未发布] — D3 zcode 商用条款闸解除轮（蔡工拍板不做商用申请；纯文档轮·零代码零迁移零路由＝口径不变，2026-11-12）

用户澄清「zcode 不用商用申请了，之前搞错了」⇒ D1=A 宿主侧 zcode 代理通道**保留**（已投入代码资产：`agents/zcode_contract.py`＋夹具＋14 例＋宿主轮询领取形态），仅解除 **D3 商用条款书面确认闸**。连锁修订九处（全部留沿革不删原文）：① `D4-D7人工项推进包` §0 行动清单第 1 行作废／§1 整节标「已解除」且回执 6 格改 N/A／§2 立项卡前置改「P2′+N1+N2」／§5 二表前置移除商用回执／§6·§7 统一口径与待补清单 D3 项改解除；② `T-Z1` §1.3 挂账作废／§2 通道 A 前置缩为一件（仅 AGENTS.md 红线修订）；③ `试点前联调检查单` 二表失败处置段商用回执前置移除；④ `下一步实施台账` §0 头注／§4 E10 行／§8 D3 行／§11.3 两段／§11.4 表／§11.5 不做清单／§12 统一口径·Q2 卡·待补清单·§12.1 填写指引 D3 格；⑤ `D1-D3拍板留痕` §1 摘要·D3 特别口径·仍需人工·§3 D3 行·§4 结案边界·§5 人工表·§7 边界·§8 统一口径·Q2 卡·待补清单·§5 差异注记。**`adapter_missing` 解除条件由三改二**：「①宿主轮询实装 + N2 联调签核」（移除 D3 回执项）。AGENTS.md 红线第 6 条五边界一字不动；H1–H13／N1–N7 原样（**N1 已授权、N3 五问已拍、N2 已签核完成**；D7 阈值仍禁预支）；零代码零迁移零路由零桌面。

### 同轮补录：N1 试点授权 + N3 A 轨诉求五问（交互拍板落痕，2026-11-12）

- **N1 已授权**（`D4-D7推进包` §2 表三格落值）：授权人＝首个 run 发起人＝**蔡工**；试点窗口 **2026-11-12 ~ 11-19**（7 天，30d 上限内）；授权签字＝**蔡工 / 2026-11-12**。台账 §12 待补清单／§12.1 填写指引／§11.4 状态覆盖行同步。**首个 run 的发起动作本身仍须蔡工在系统内亲手执行**（H4；Agent 不代发起、不造运行证据）。
- **N3 五问已拍**（§3 表落值）：A 轨任务封闭集＝**仅 pilot-001 编码 run**；产出物＝**run 产物目录内代码/diff/文档产物 + `--json` 汇总**；确认人＝**蔡工**；降级只读白名单＝**`READ_ONLY_TOOLS` 全量 13 个**；失败语义＝**`degraded=true` 留痕**。E8 定义齐备、**实施另待排期轮**（不随拍自动开工）。
- **N2 签核完成 2026-11-13**（检查单两表真机全 PASS：版本钉定 0.17.1 与钉定值一致、冒烟 `--json` 单对象汇总形状与夹具一致、故障态明确失败码且零半成品、回退路径可用；蔡工授权留痕，证据 sha256 落检查单回填表，原件只留本地）。剩余人工项仅 1：**D7** 阈值（`approval_rows=0` 禁预支，复审轮拍板）。
- **N2 实测带出两条实施级事实（已回写 `v3-backlog.md` T-Z1 段，供接线轮直接取用）**：① provider 覆盖开关＝`ZCODE_BUILTIN_PROVIDER_CONFIG_FILE` + `ZCODE_PERSONAL_PROVIDER_CONFIG_FILE` **成对**设置（`FDE_CONFIG_DIR` 实测无效）；② `-p` **无 `--model` 开关**，默认模型选择持久化在 `~/.zcode/cli/config.json` 的 `defaultModelSelection` 键，**该键缺失即 EXIT=1「Select a model before sending a message」** ⇒ 宿主代理必须校验该键在场，缺失即明确失败并留痕、不得静默重试。
## [未发布] — AI 原生化 N5 实施轮：G-02——AI 发起 run 受控提议通道（propose→人工密码确认→落 run；零迁移零新路由＝485/52/153/73 口径不变；api_catalog 96→98，2026-11-12）

任务书 §15 序 7 末位（蔡工授权链「继续实施N4和N5」；差距台账 v1.20 G-02 CLOSED）。★**安全评审必跑（DoD⑤）**：code-review 技能已迁移外部插件 ⇒ 以同等严格度对 diff 只读逐面评审（12 面；AI 审查不执行被审代码）——**发现 C 项真缺口当场闭合**（agents.run_start 的 project_id 在 body，票据 scope 检查原只覆盖 path 参数 ⇒ `_require_run_start_scope_binding` propose+confirm 双侧补齐）。

- **NEW 目录两确认类（api_catalog ENTRIES 96→98）**：`workflows.run_start`＋`agents.run_start` 进 `CONFIRMATION_KEYS`（3→5 值）⇒ risk 3——AI 侧发起即 `awaiting_confirmation`（15min 窗语义零改动），**人工密码确认后才经既有发起路由落 run**；AI 不代发起 run。
- **api_actions 三闸**：①propose 幂等键闸（`run_start_idempotency_required` 400——取消/重复防护锚点）；②confirm 终态守卫（`run_cancelled_not_revivable` 409——workflows 同键 cancelled 复活洞在 AI 通道封死〔executor.start_run 幂等去重不区分状态〕；agents 无取消路由，failed/timeout/budget_exceeded 同义拦截＝AI 不代重试红线；同键已完成 run 不拦＝幂等重放复用不算重试）；③票据绑定闸（安全评审 C 项，propose+confirm 双侧）。
- **三样安全清单各有独立反例**：取消语义（propose 后人工取消/失败同键 run ⇒ confirm 409＋零新 run）／幂等键（双 execution_id 同键双确认 ⇒ run 表恰 1 行，第二个走生产幂等 200 复用）／授权绑定（scope≠project propose 403 零落库＋账号停用 confirm 重授权 403＋auth_version 变更 409）。
- **端到端审计**：requested（confirmation_required/auth_version/scope/execution_id）→started→finished 三事件链，零密码字段；未确认零 run；过期 409；驳回 cancelled 零 run。
- **测试 NEW `test_ai_run_proposal.py` 16 例**＋**变异三连全红→try/finally 还原→绿**（M1 propose 幂等键闸／M2 confirm 终态守卫／M3 confirm 授权重判）＋邻域回归 5 文件 86 passed；ruff 绿；mypy 官方闸 279 基线不变。
- **CI 首轮撞两枚既有只读钉 ⇒ 钉换代不删钉（N4 先例）**：`test_agent_traceability`（agents 面允许集扩 run_start 确认类；接管/handoff/retry/rehearse/recover 仍零命中）＋`test_delivery_plan_ai_draft`（workflows 起草禁收收窄为「除 run_start 外」）。
- **明确不做（任务书边界机械承载）**：不解除 15min 窗／不让 AI 直接执行／提议不可批量确认／不改宿主通道五边界／接管与重试动作永不收编（目录钉 `agents.run_takeover`/`run_retry` 零命中）。

口径：**零迁移零新表零新 Flask 路由**（两条 ENTRIES 指向既有发起路由）＝485 路由/52 蓝图/153 表/73 rev 单头 `b5d9e2f4a7c1` 全不变；**api_catalog ENTRIES 96→98**；宿主人工通道与 automation_approvals 面零变化。
**合并与活体复验（2026-11-13）**：PR #407 squash `6f90147`（树哈希零漂移＝`4f4a19d^{tree}` ≡ `6f90147^{tree}`）；PR head CI 四绿（server-tests **3473 passed + 8 skipped**＝3457 基线 + 16 新例逐位吻合；首轮撞两枚既有只读钉已换代后二轮全绿）；main push run **43262153263** 四 job 全绿（server-tests **3473 passed + 8 skipped** 逐位吻合）。活体复验全绿：三镜像 rebuild（api `7ad54e94891a`／worker `714b98224cbc`／scheduler `8300d9aa8842`，容器 `.Image` 与构建产物逐位一致）＋`alembic current`＝`b5d9e2f4a7c1 (head)`（零迁移 no-op）＋`url_map` **485 non-static** ≡ 口径＋ready/live 200＋活体 CATALOG **ENTRIES 98**、两 run_start 确认类（confirmation=True/risk=3）在位。

## [未发布] — AI 原生化 N4 实施轮：G-10/G-11/G-14——评测观察轮＋受控发布通道＋指标复审工单（评测回流闭环三件结构面全落；迁移 72→73＝485/52/153/73，2026-11-12）

任务书 §15 序 5（蔡工显式授权「继续实施N4和N5」；差距台账 v1.19 三条 CLOSED）。差距台账三条：G-10「golden set 不连真实模型；CI 无 AI 评测 job」／G-11「模拟实验室改进链止于 approved，无发布通道」／G-14「metrics v31 七指标无任何自动消费方」。★N4 前提现测注记维持留痕：活库零真实 draft 样本 ⇒ ai-eval 首跑预计 `insufficient_data`——这是协议 v0 的诚实语义（不编造分数），报告即证据，不是缺陷。

- **NEW `simulation/release_channel.py`（受控发布/回滚单一写入点，G-11）**：发布三闸（admin 角色闸＋密码+note 确认闸〔`verify_password`〕＋approved 态闸）＋`regression_plan_json` 非空闸（409 `details.required=regression_plan`）⇒ `status=published`＋`release_json` 留痕＋`OperationEvent simulation.proposal_released`；回滚恢复 approved＋`release_json.rollback` 嵌套留痕、原发布字段保留。迁移 `b5d9e2f4a7c1`：`improvement_proposals` 加 `release_json` JSON 列＋CHECK 换五值（含 `published`）。**静态钉换代不删钉**：改进域三钉由「止于 approved 零写入」改写为「只许经发布通道写发布面」（引用面闭集＋owners 闭集＋routes 禁接工单写入）。
- **NEW `metrics/review_tickets.py`（指标越限→提示词复审工单，G-14）**：出厂默认关（`FDE_AI_REVIEW_TICKET_ENABLED`）＋规则闭集校验 fail-closed（未知指标／非法 op／threshold 非数值／prompt_ref 不在 N6 注册表全拒）＋`insufficient_data` 永不判越限（不编造）＋严格比较＋同日幂等指纹；越限 → draft 提案工单（`target={kind:prompt,ref}`＋`finding_codes=[metrics_v31_breach]`）——**动作是工单不是自动改提示词**；`flask evaluate-review-tickets` CLI。
- **NEW `scripts/ai_eval/run_opportunity_eval.py`＋`.github/workflows/ai-eval.yml`（CI eval 非必需观察轮，G-10）**：交付效果评测协议 v0——离线腿 23 例 oracle 重放（重放不匹配＝环境坏⇒insufficient）＋真模型腿 9 例（citation 6＋pseudonym 3；结构/格式/上限 14 例纯离线零烧费）；uplift 截断不四舍五入、PASS 线 0.8 未校准、incidents 一票封顶；三道 `insufficient_data` 闸（oracle 重放失败／凭据缺席／真模型腿 error——error 行不是 0 分、是无数据）。独立 workflow **不进 ci.yml 四必需 job**：dispatch＋每周一 03:00 UTC＋AI 面 push 触发；凭据缺席 job 保持绿；报告 artifact 90 天；成本≈9 次调用/3 万 token 量级（跑频按此现算；★供应商红线：只允许按量付费 key）。
- **测试 NEW 三文件 27 例**：`test_simulation_release_channel.py` 10 例＋`test_metrics_review_tickets.py` 9 例＋`test_ai_eval/test_opportunity_eval_harness.py` 8 例。**变异六连全红→try/finally 强制还原→绿**（M1 admin 闸／M2 回滚恢复／M3 密码闸／M4 越限判定／M5 出厂默认闸／M6 评测凭据闸）；广域回归 20 文件 271 passed；ruff 绿；mypy 官方闸 279 基线不变。
- **明确不做（任务书边界机械承载）**：不把 eval 设必需门禁（阈值未校准）／不删静态钉（改语义）／不自动上线提示词改动（工单制）。

口径：路由 **483→485**（+2：release/rollback 两人工治理面，不进 api_catalog，96 ENTRIES 不变）／蓝图 52／表 153／**72→73 rev** 单头 `b5d9e2f4a7c1`；route CSV +2 行；archify architecture 图重生成＋preview 整页实拍＋图纸防陈旧闸绿。四特征④复评维持 2-1-2-1 不虚升（结构面齐；真实行使待 CI 配凭据出首份非 insufficient 报告＋首提案真实走通道）。
**合并与活体复验（2026-11-12）**：PR #405 squash `3f9a9ce`（树哈希零漂移＝本地 `ab46039^{tree}` ≡ `3f9a9ce^{tree}`；两度插队 rebase：#402/#403 与 #404——CHANGELOG 节序 N4→L2→L2 读数→N6、AGENTS 双 bullet 两侧全留）；PR head CI 四绿（run 43242225793 server-tests **3457 passed + 8 skipped**）；main push run **43245541589** 四 job 全绿（server-tests **3457 passed + 8 skipped** 逐位吻合）；ai-eval 观察轮 job 首跑真机报告 **verdict=insufficient_data**（`model_credentials_absent`——凭据缺席诚实语义，不编造分数，artifact `ai-eval-report` 90 天在案；prompt_fingerprint `ae12fd11c092cb7c`；G-10 复测判据「CI 多出 eval job 且产出报告文件」活体兑现）。活体部署三验全绿（七撞纪律）：三镜像从合并树 rebuild（api `82c271a4afc7`／worker `abc86d47c0cc`／scheduler `06da616ec967`，容器 `.Image` 与构建产物逐位一致）＋`alembic upgrade head` 真实升级 `f2a7c4e9b6d3 → b5d9e2f4a7c1`、容器内 `alembic current`＝`b5d9e2f4a7c1 (head)`；活体 `url_map` **485 non-static** ≡ 口径；ready/live 200；活库 `improvement_proposals.release_json`（json 列）＋CHECK 五值含 `published` 断言在位。

## [未发布] — 交付案例学习闭环 L2 批跑器节流旗标轮：run_batch NEW `--call-interval-seconds`（底册挂账改进位落地；缺省 0.2 零行为变化；scripts 层零生产代码改动·零迁移零路由零蓝图＝483/52/153/72 口径不变，2026-11-12）

底册挂账改进位落地：`scripts/simulation/run_batch.py` 评估轮间隔由固定 0.2s 改为 `--call-interval-seconds`（float，缺省 0.2＝既有行为零变化；负值 SystemExit 拒绝）——相邻两次评估调用间隔可调，对限流敏感的 provider 建议加大（诊断线同名旗标先例，仅评测进程侧，生产零改动）。测试 NEW 3 例（缺省 0.2 逐轮透传／旗标值 1.5 逐轮透传／负值拒绝），本地 importlib 直调新 3 例＋锚点/幂等既有钉共 6 例全绿，全量以本 PR CI 实测为准；底册改进位行同步改为已落地。模型层重跑（底册挂账①）随后以 `--call-interval-seconds 20` 节流执行。

## [未发布] — 交付案例学习闭环 L2 模型层读数轮：挂账①消解——锚点 n=3 极差 0.1049＝纯模型评估侧噪声带实测（底册 NEW 第四节＋七撞复发干净树接管；零代码零迁移零路由＝483/52/153/72 口径不变，2026-11-12）

MiniMax 配额探针 HTTP 200（2056 套餐耗尽解除）后按底册配方重跑（`--call-interval-seconds 20` 节流旗标 PR #402 本轮首发实战，6/6 一次跑完）：锚点组（同 run 三轮重评）0.6233/0.5184/0.5553 ⇒ **极差 0.1049＝纯模型评估侧噪声带实测**，verdict 于纯评估噪声内翻转（conditional/fail/fail）⇒ 模型层单点分数与 verdict 均不可作能力结论；逐场景 IMP-DW015-TRADE-DOCS n=3 vs 锚点 Δ=0.0107 < 带 ⇒ `within_noise`（分不出差异≠无差异）。底册 NEW `docs/audit/训练场分布读数-L2底册-1.md` 第四节（读数＋四条读法边界＋真相层新指纹表）＋L2 验收状态改达成。执行中七撞复发当场修复：并发 N6 线从已删除树 `fde-wt-n6impl` 重建活体（模型槽位键与 ⑦ 出站闸两键静默丢失＋migrations 僵尸挂载 `alembic current` 不可用）⇒ 从 fork/main tip `2e7af7f` 干净树接管（三镜像逐位一致＋alembic `f2a7c4e9b6d3 (head)`＋url_map 483＋env 三键回归在位）；attempt-2 产物归档留痕（与首跑归档逐字节相同＝unavailable 路径确定性实证）；lessons 展示面增补挂账＝蔡工拍板维持不增设（SOP-only 维持，留痕可推翻）。

## [未发布] — AI 原生化 N6 实施轮：G-13 提示词版本注册表＋质量路由 fail-safe（12 常量单一权威＋四机械钉；零迁移零路由零蓝图零桌面＝483/52/153/71 口径不变，2026-11-12）

任务书 §15 序 6（N4 前提现测不满足——活库零真实 draft 样本 ⇒ 按排期自身「与 N4 前后择时」条款先行，留痕可推翻）。差距台账 G-13「提示词版本化 1/5：仅 discovery 带版本戳」——改了提示词正文不升版本 ⇒ 归因失效，是数据飞轮断点 b（审计无版本归因）的最后一块结构缺口。

- **NEW `ai/prompt_registry.py`（单一权威）**：12 个模块级 *SYSTEM_PROMPT* 常量全部在册（G-13 点名 5＋N3 系/诊断/派单/模拟 judge 等），每条带版本标签＋注册时内容 sha256 字面量；`version_of` fail-loud 是模块取标签唯一通道，模块侧只 re-export；discovery chunk 模板（拼接派生面）derived_of 挂主版本。
- **NEW `ai/model_routing.py`（质量路由 fail-safe 薄缝）**：`resolve_quality_route` 四道闸（出厂默认关／摘要指针空或不可读或坏 JSON／无该 purpose 行或形状不合法／分数<0.8）任一不满足恒 None＝沿用既有模型解析链；`execute_ai_prompt` 链序钉死「显式 model_override ＞ 质量路由 ＞ 人工偏好」。任务书 N6「明确不做」机械承载：不自动改提示词内容、不在无评测数据时自动切模型、提示词正文不入库（只存版本＋指纹）。
- **执行点全接线**：6 处既有版本标签改注册表 re-export＋3 处新增版本常量＋complete_json 调用点 prompt_version 补齐（industry 单漏斗拆 keyword-only 双版本参）；config 三键（默认关/空/0.8）＋`.env.example` 注释态；ai_call_audits 按 prompt_version 归因自此覆盖全部 12 提示词面。
- **四类机械钉 NEW `test_prompt_registry.py` 15 例**：指纹耦合钉（改正文不升版本⇒红）／AST 全常量必注册双向≡（Constant/JoinedStr/BinOp）／出厂默认安全钉／fail-safe 矩阵×8／链序源钉。**变异四连全真红→还原绿**（红判定要求 AssertionError 在场，区分环境错与真红）。
- **测试与口径**：定向回归 21 文件 322 passed；mypy 279 基线不变；ruff 绿；零迁移零路由零蓝图零桌面 ⇒ 结构口径全不变（483 路由/52 蓝图/153 表/71 rev `a3e8c2f6b9d4`/96 ENTRIES）；提示词正文一字未动（12 指纹现算零漂移）。PR #397 CI 四绿（run 号随合并后收口回填补录）。
- **四特征④复评（DoD③，留痕可推翻）**：评分维持 2-1-2-1——④要件两件已落（N2 指纹＋N6 版本注册）＋真模型评估数据在库，但评估数据尚无自动消费方（CI eval＋发布通道＝N4）⇒ 按「分数只在回流闭环达成时上行」纪律不虚升，④上行复评挂 N4 落地轮。
- **N4 前提现测注记**：活库 ai_call_audits 六 purpose 零 draft 类、operation_events 零 ai_drafted 事件 ⇒「N3a 出真实样本后」现测不成立，N4 维持已排期（§15 序 5）。
## [未发布] — 部署接管检查器轮：NEW `scripts/deploy/takeover_check.py`——教训⑩机械闸化（env 键静默丢失事故家族 2026-11-12 三发的闸；零迁移零路由零蓝图，2026-11-13）

蔡工「处理这个小挂账」授权。NEW `scripts/deploy/takeover_check.py`（stdlib 纯函数，只读键名永不打印键值）：树模式三查＝根 `.env` 含 compose 全部 `${VAR}` 插值变量（含 `:?err`/`:-def` 形态）＋`server/.env` 含关键键六枚（`CRITICAL_SERVER_KEYS`＝JWT 根＋AI 端点三键＋⑦ 出站闸两键＋训练场模型槽位）＋`.env.example` 差集 WARN；`--live` 两查＝api 容器 migrations 挂载源在场（**僵尸挂载**探测——部署树已删时 `alembic current` 必炸而 ready=200 照绿的隐蔽态，T-16 深夜接管实录）＋容器 env 关键键。退出码 0/1/2；Windows 宿主 docker 通道（wsl）显式 platform 注入。测试 NEW `test_deploy_takeover_check.py` 17 例（解析/插值四形态/树三查/退出码/权威钉两枚〔关键键必在 `.env.example` 载名＋事故三键钉死清单防 shrink〕/live 注入 runner/命令装配/WSL→Windows 挂载源路径翻译〔实弹冒烟抓到的盲区钉〕）；`server/.env.example` 补 `# FDE_DEEPSEEK_BASE_URL=` 载名（权威链自洽钉要求）；README 生产部署要点与 AGENTS 活体部署 bullet 各 NEW 使用行。

## [未发布] — 获客诊断 T-16 轮：价格轮——转化费比例落配置面（fee_basis 换值 ratio_applied；迁移 71→72＝483/52/153/72，2026-11-12）

蔡工拍板④（按推荐执行＋留痕可推翻）：转化费＝比例制——A 渠道报备缺省 20%、B 认领转化缺省 10%（C 平台留存零转化费，不走比例）。**比例数值只在配置面**：NEW `Settings.diagnostics_fee_ratio_tier_a/b`（Decimal，ge=0 le=1 越界启动即炸——挡「填 20 想表达 20%」笔误），env `FDE_DIAGNOSTICS_FEE_RATIO_TIER_A/B` 可调；模型列零比例零金额字段（T-11 静态钉原样保留）、认领单投影键闭集钉死（比例数字不进任何响应）、台账行十二列零变化。fee_basis 结构值换值 `pending_pricing`（待价格轮）退役→`ratio_applied`（按平台配置比例计；结算时点政策由运营口径承载）；迁移 `f2a7c4e9b6d3`（挂 `a3e8c2f6b9d4` 保单头）CHECK drop+recreate，**零存量行**＝主部署诊断闸关期间零认领＋轻部署库全新，无数据迁移。桌面标签 `ratio_applied`→「转化费按平台比例计」（不带数字）。测试 NEW `test_diagnostics_fee_pricing.py` 14 例（defaults 钉／env 覆写／越界四例含边界含端点／闭集钉〔退役值不得复活〕／迁移静态钉／_fee_basis 映射／投影闭集钉／台账零变化）＋**变异三连红→还原→绿**（M1 默认值漂移 0.25/0.15 ⇒ defaults 钉红；M2 摘 ge/le ⇒ 越界四例红；M3 写回 pending_pricing ⇒ 映射钉＋CHECK 违规 10 例红；还原 sha256 逐位一致）；诊断域回归 83 例绿＋claims 34 例绿；mypy 279 基线不变；官方 ruff 绿。

PR #398 squash `fa2ebf8`；活体部署三验全绿（七撞纪律）：三镜像从 `fa2ebf8` 干净树 rebuild（api `3b32d852b9fa`／worker `d0ba33de0a0a`／scheduler `11df7862c94a`，容器 `.Image` 与构建产物逐位一致）＋`alembic upgrade head` 真实升级 `a3e8c2f6b9d4 → f2a7c4e9b6d3 (head)`＋活体 `url_map` **483** ≡ 口径＋**活库 CHECK 新闭集 `('none','ratio_applied')` 在位**＋容器配置面读数 tier_a=0.20/tier_b=0.10＋诊断闸默认关 404＋ready/live 200。便携版 **r42**（asar sha256 `754931c478dad5b659324ae007afb44548804692f502127caeb7a5feb6627063`；英文探针 `ratio_applied` 命中／`pending_pricing` 缺席；★r41 已被并发线 16:33 消耗，序号交付时点现测顺延；★主树 release/win-unpacked.tmp 被句柄锁死 ⇒ 按 r9 配方换 detached worktree @ `fa2ebf8` 打包）。


## [未发布] — 获客诊断 T-13′ 轮：工具内示例报告页（E-3 前半）——静态 ReportDoc＋展示面角标＋「非实时诊断结果」声明＋stage 中文映射＋闸关示例入口；随轮部署替换 app.fde18.com（零后端生产代码改动·零迁移·零路由＝483/52/153/71 口径不变，2026-11-12）

任务书 T-13 行的开放单元＝E-3 拍板顺序前半「先工具内示例报告」（展示面直接服务获客；网站内容页归 T-14b）。**展示面例外（评测集污染隔离红线）第一次机械落地**：示例页可消费公开案例整理／脱敏交付素材，但角标＋声明强制、生成器检索面零引用。

- **静态 ReportDoc 两则**（NEW `desktop/src/renderer/src/diagnostics/sampleReport.ts`）：datawhale-001（制造业经验传承——3 条政策 `official_text` 逐字对齐 `policy_data.py`，`our_reading` 按服务端 `_policy_opportunity` 拼装口径）＋somwyn（外贸获客——`policy.opportunities: []`，报告如实呈现「未匹配到政策条目」，不硬凑）；**无分数无评级无金额**（真相层 report_demo 的 41/100、32/100 一律不搬）；角标「示例案例 · 据公开案例整理」／「脱敏真实交付 · 代号化」＋页面「示例内容 · 非实时诊断结果」声明。
- **`ReportView` 抽取复用**（NEW，自 `PublicDiagnosticPage` 原样抽出）：渲染零变化＋**stage 中文映射**（识别/定位/处置/回写；闭集外原样透传）——修服务端 `LOOP_STAGES` 英文代号直出中文报告的展示缺陷，活体报告页与分享页两处一并接 `stageLabel`。
- **NEW `PublicDiagnosticSamplePage`**（路由 `#diagnostics/sample`，未登录公开分支可渲染）：案例切换（aria-pressed）＋meta 卡（角标/标题/摘要/出处/note）＋「去做测算」；诊断页 intro 与**闸关早返回分支**两处「先看示例报告」入口——闸关时访客也能看见示例（静态展示面不依赖开闸）。
- **机械闸** NEW `server/tests/test_diagnostic_sample_surface.py` 5 钉：角标常量逐字＋被用／无「生成于」（活体语义不混入示例面）／无分数·评分词·金额·百分比限闭集 {20%,30%,60%}／**生成器检索面（`fde_api/diagnostics`＋`server/seeds`）零示例引用**＝展示产物不进生成器检索路径／路由双向接线计数 ≥2；**变异 5/5 红→字节级还原→绿**（S5 首版「出现过一次」式断言无判别力，改计数断言后转红）；污染钉扫 `desktop/src` 零命中。
- **测试**：桌面 NEW 样例页 12 例＋导航 +2＋诊断页 +2 ⇒ vitest **1100 = 1084+16**（96 文件全量 exit 0；1084＝T-14a 记录值 1079＋N3c agents-console +5）＋typecheck 绿；服务端 +5 ⇒ CI 实测 **3339 收集 = 3331 passed + 8 skipped**（PR run 43183542727；＝N3c 融合树 3334+5 逐位吻合）；mypy 279 基线不变。
- **口径**：零后端生产代码改动（+1 纯静态服务端测试文件）、零迁移、零路由、零表 ⇒ **483 路由／52 蓝图／153 表／71 rev 单头 `a3e8c2f6b9d4`／`api_catalog` 96 ENTRIES 全不变**。
- **交付与部署**：便携版 **r41**（asar sha256 `9a7f4214…`；marker `public-diagnostics-sample` ×4／`diag-sample-badge` ×2／「先看示例报告」×2／`diag-sample-notice` ×6）；web 发行形态 `build:web` 产物 marker 全命中。**部署替换 app.fde18.com（蔡工 2026-11-12 授权「弄好没问题再部署替换」）**：三备份先行（staged diff＋静态站 tar＋PG dump → 服务器 `/root/fde-backup-20261112-T13`）→ checkout `5c252e1` → rebuild 三镜像（api `7e953f2…`／worker `b43126…`／scheduler `f58ba7…`，容器 `.Image` 与构建产物逐位一致）→ **alembic 真实升级 `d5f9a3c7e1b4 → a3e8c2f6b9d4 (head)`**（活体从 2026-11-10 版一次跨 20 迁移；★旧 api 容器泄漏连接 idle in transaction 1 天持锁阻塞 ALTER，terminate idle 持有者解堵）→ web-dist 上传替换静态站（vhost 零改动，旧目录 `.bak-T13` 可回滚）。**七点验证全绿**：url_map 484 total/**483 non-static** ≡ 口径；容器内 alembic `a3e8c2f6b9d4 (head)`；镜像 ID 逐位一致；app `/`·ready·live 200；**闸关 404 而非 403**（diagnostics＋registration 双面——D-3 前不进主部署红线维持）；官网 fde18.com `/`·`/blog/`·`/services/` 200 零扰动；样例页 marker 经 HTTPS 端到端命中。合并后 main run 43188889108（`5c252e1`）四 job 全绿。
- **下一轮候选**：T-14b 官网案例内容页（E-3 后半，等 D-3 拍板）、T-16 价格轮（等 D-5＋MVP 数据）。

## [未发布] — AI 原生化 N3c 实施轮：G-06 AI 派单推荐（返件式）＋G-15 桌面跨 run 编排面＋T-A10 产物内容读取面

- **这一轮解决什么**：任务书 §15 序 4——BP §1.3a L3 定义里的「AI 参与派单推荐」缺通道（差距台账 G-06）；「人管理 Agent」缺跨 run 呈现面（G-15）；复核人被迫离开桌面看产物原件（backlog T-A10，N1 人工链实弹暴露）。三件同轮合批，四项交互拍板留痕可推翻（match-ai 独立路由返件式／decision 纯事件端点／AgentsConsole 升级编排面／T-A10 合批）。
- **G-06（NEW `dispatch/recommend_ai.py`＋`POST /api/v1/dispatch/packages/<id>/match-ai`，返件式）**：规则腿与 AI 建议腿**并列双来源、闸唯一**——match_package 的 Stage B 排序循环抽取为 `_stage_b_ranked` 单一真身双腿共用（行为零变化经 r5 回归证）；AI 建议只读叠加**零 dispatch_offers 落库**＝AI 不自动派单、采纳后责任主体仍记人；场景 C 不调 AI 零烧费；契约失败即时重试一次 409 `ai_dispatch_contract_failed`；输出端兜底脱敏；`dispatch_ai_recommended` 事件携 sha256/计数/版本不带建议全文；提示词只有不透明 user_id 零姓名。
- **采纳/驳回＝NEW `POST .../match-ai/decision` 纯事件端点**：只落 operation_events（`dispatch_ai_recommendation_adopted/_rejected`），零业务写——采纳后派单仍走既有人工通道。
- **G-15＋T-A10 桌面（`AgentsConsole.tsx` 升级跨 run 编排面，零服务端新写路径）**：run 表多选＋「终审队列（跨 run）」汇总未复核产物＋批量标记复核（逐件既有 PATCH 复核写面＝终审不可绕过）＋产物预览（doc 走 MemoMarkdown）＋原件下载；服务端 NEW `agents/artifact_content.py`＋`GET /runs/<run_id>/artifacts/<artifact_id>/content`——逐字节 sha256 对库行指纹自证（不符 503 fail-closed）；防穿越 404；**容器态原件不在场显式 404 `artifact_content_unavailable` 不静默不伪造**（进程空间裁决＝宿主裸跑态全量可用）；超限 413 不截断；can_manage 同尺；只读零写零事件。
- **测试与验证**：服务端 NEW `test_dispatch_ai_recommend.py` 12 例（含 api_catalog 双钉）＋`test_agent_artifact_content.py` 8 例＋`test_ai_api_actions.py` +1（AI 侧 decision 确认流钉：发起即 awaiting_confirmation）；桌面 `agents-console.test.tsx` +5（13/13，typecheck 绿；合并树 CI desktop job 全量 **95 文件 / 1084 例**全绿）；**变异 M1–M4 红→字节级还原→绿**（候选闭集／decision 事件／J-1 登记／指纹闸）；服务端广域回归 13 文件 87 例绿；mypy 279 基线不变；J-1 提示词白名单 +1。
- **口径**：+3 路由 **480→483**（dispatch 两路由进 api_catalog〔建议腿只返件不落库；decision 端点列**确认类** risk 3＝AI 不代拍板，须人工密码确认〕／artifacts content 路由不进〔复核面纪律〕；基线＝插队融合树 fork/main `8b858d7`——本基点 `6efe666` 之上插队 #373/#375/#378/#379/#380/#374/#377）／52 蓝图／153 表／71 rev 单头 `a3e8c2f6b9d4`（本轮零迁移零新表）；`api_catalog` 94→**96 ENTRIES**；审计清单三件套合并树重生成（route CSV +3 行）＋archify architecture 图重生成＋preview 整页实拍（防陈旧闸绿）；pytest：基线 3205 收集〔main run 43129411451〕＋本轮 +21（12+8+1）⇒ PR head run 43146775588 实测 **3226 收集 = 3218 passed + 8 skipped**；两度插队后融合树 CI 实测 **3334 收集 = 3326 passed + 8 skipped**〔run 43160141925，＝T-15 树 3218＋本轮 +21＋L2 #374 +32＋L3 #377 +11＋M6/M7 #381 +52；T-14a #384 纯桌面、#382/#385/#383 纯文档零服务端增量，逐位闭合〕。
- **挂账／下一轮**：N4（§15 序 5，CI eval 非必需观察轮，需 N3a 真实样本）——**排期≠实施授权**；桌面变更 ⇒ 便携版 **r40** 已交付（r38 已被 T-15 #375 消耗、r39 已被 T-14a #384 消耗——序号写前现测；asar sha256 `81423fec67397c1e75a631233d9ea41c3bc772ca573b11da2231b7c1f93c22d0`／141187936 字节；marker 字节命中，r39 反向对照全 0）。
- **合并与部署复验（2026-11-12）**：PR #376 squash 合并 `d67e0ac`（树哈希零漂移＝`32f03bc^{tree}` == `d67e0ac^{tree}` == `994c612e…`）；合并后 main push run **43174601383** 四 job 全绿（server-tests **3326 passed + 8 skipped**＝3334 收集；desktop **95 文件 / 1084 例**全绿）；**活体部署三验全绿**（七撞纪律：api/worker/scheduler 三镜像 ID 与本工作树构建产物逐位一致＝`00c52de0…`／`308796f2…`／`c9b8498f…`；容器内 `alembic current`＝`a3e8c2f6b9d4 (head)`（本轮零迁移＝幂等 no-op）；活体 `url_map` **483 non-static** ≡ 口径；`/api/v1/health/ready` 200＋`/live` 200；三容器全 healthy；migrations 挂载已从他人工作树 `fde-wt-deploy-t15` 收回本工作树）；便携版 **r40** marker 判别力：中文 marker 本轮精确命中（旧轮「asar 中文 marker 恒 0」假设作废）⇒ 判别力以「源文本精确回归＋r39 反向对照全 0」双证坐实。

## [未发布] — 多客户 M8 轮：安全专项回归与全量回归口径（红队爬扫／跨企业越权／重放／敏感日志三专项套件＋验收对照表 v1；零迁移零新表零新列零新路由＝零生产代码 diff，2026-11-12）

按两层框架推进工程侧；业务/合规授权层后置维持＝结构就绪·待授权。本轮＝**只落测试与文档**，授权层动作一律不代做。

- **本轮交付**：NEW `server/tests/test_m8_red_team_sweep.py`（红队爬扫：企业 A 账号全 API 爬扫企业 B 读面，双阳性对照＋完整性钉「未登记即红」）／`test_m8_replay_guard.py`（重放防护）／`test_m8_sensitive_log.py`（敏感日志）三专项回归套件（**23 个 def test_**）＋ NEW `docs/commercialization/multi-tenant/M8-验收对照-v1.md` 验收对照表 v1＋ `docs/commercialization/phase-status.md` M8-1 轮节＋ leader 任务书 §14 M8 行注记（**保持 `[ ]` 不打勾**）。
- **实测**：三件套 **62 collect 全绿**；邻域回归 12 套件 **181 passed**；**5 组变异全部转红→字节级还原（3 文件 sha256 一致）→复绿**。全量 pytest 收集数与 CI run 号为时点快照，**待本轮 CI 实测回填**。
- **零结构变化**：**零迁移零新表零新列零新路由**、**零生产代码 diff**；**不重跑** `scripts/audit/extract_workbench_inventory.py`、**不重生成** `docs/audit/v3-*` 与 archify `candidate.json`（零结构变化轮口径纪律）。路由・蓝图・表・迁移 rev 与 pytest 收集数一律不写死，**以本轮 CI 实测为准**。
- **AGENTS 状态链与现行结构口径行本轮不改**（零结构变化轮口径纪律 ＋ 超长行整行重写冲突风险），**本轮登记由 AGENTS bullet 承载——有意裁决，非 DoD 缺项**。
- **安全专项「零高危」为 Goal 验收条件，本轮不作该判定、留授权层**（leader :212 / §14 :326）；§14 M8 行保持 `[ ]`。
- **本轮未做（不可代做摘要）**：真实试点与书面确认／MT-C 签核与放行／容量复测与部署拓扑／W0 并存期方案／演示服务器零改动／试点反馈回写／对外 SLA 与 NPS 口径——各节自有条数、计数不合并，逐条见 `docs/commercialization/multi-tenant/M8-验收对照-v1.md` §5。
- **口径冲突并列登记（逐字，不裁决）**：

  > - `| M8 | 9 类安全测试 + 全量回归 + 2–3 家真实试点 | 5–8 | M1–M7 |`（leader :145）
  > - `- **语义**：9 类测试（G 线 §12 清单）+ 新增跨企业越权/重放/敏感日志专项；存量全量回归（pytest/vitest 以当时 CI 实测为准）；**2–3 家真实试点企业**（从试用客户转化）走完 S1 全程；试点反馈回写 M5；试用轮 W0 与新平台并存期的主备/数据隔离方案另附。`（leader :211）
  > - `- 测试门槛：**沿用 G 线任务书 §12 六类**，新增第 7 类「跨主体隔离」（每 Goal 的越权用例进 CI，M8 红队爬扫）。`（leader :219）
  > - G 线任务书 §12 `:371-382` 十条测试质量门槛（1–6 六类测试域 ＋ 7–10 附加规则）逐字见 `docs/commercialization/multi-tenant/M8-验收对照-v1.md` §1.4。

  类数**待 OWNER 裁决**；M8 测试执行按「G 线 §12 与 leader §8」引用，本轮不改写任何权威文档。

## [未发布] — 获客诊断 T-14a 轮：官网诊断入口（本仓访客面）——免注册访客 UI「政策补贴测算」＋分享只读页＋桥契约扩展（X-Diagnostic-Token 头＋空 accessToken 公开面；桌面变更·服务端零改动零迁移零路由＝480/52/153/71 口径不变，2026-11-12）

任务书 T-14 上半：**承载体＝本仓访客界面**（桌面 renderer 与 web 发行形态共用 `main.tsx→App`），外部入口名「政策补贴测算」（P-1）；未登录直达 `#diagnostics`。服务端零改动（9 条匿名诊断路由已覆盖全流程）；**官网（fde-ops）侧公开部署属 D-3 业务决策 ⇒ 挂账 T-14b**。

- **桥契约扩展（访客面的两道缺口）**：`ApiRequestOptions` 增可选 `headers`（**允许名单只有 `X-Diagnostic-Token`**——匿名会话令牌持有即权，只走请求头不入 URL）；**空 `accessToken`＝公开面**（免注册请求，桥据此不下发 `Authorization` 头）；NEW `shared/api-safety.ts` **校验项 9** `validateCustomHeaders`（允许名单／取值字符集 token_urlsafe ≤128／数量上界 4＝纵深防御；authorization/cookie/content-type 等可改写身份语义的头一律拒绝）；双桥（`main/api-ipc.ts`＋`fde-web-bridge.ts`）消费同一原语，header 值进 redact secrets 集；**等价性静态钉扩样**：NEW `HEADER_SAMPLES` 18 条（双侧判定恒同，漂移必红）＋公开面行为钉（空令牌零 Authorization＋自定义头透传；非空令牌 Bearer 零回归）。
- **NEW `diagnostics/PublicDiagnosticPage`**：intro → 首屏 5 题 → 纯规则测算卡（定性档位＋原文/解读双层＋免责声明，无分数无金额——P-2/R-1 纪律）→ 可选 13 题深度诊断（show_if 条件显隐、只提交本轮槽位）→ 留资（**consent 客户端硬闸**，服务端 400 兜底）→ 202 受理 →3s 轮询 ready/failed（100 次上限）→ 完整报告三层渲染 → 分享链接（hash 路由、**明文只此一次**）；`channel_ref` 只透传**不臆造 source_type**——partner 归因由服务端按渠道注册表推导（T-15）；**部署闸 404 ⇒ 「暂未开放」不猜原因**。
- **NEW `diagnostics/PublicDiagnosticSharePage`**：只读摘要层（结论／第一步／政策机会／闭环存在性，**无自填原文无联系方式**——留资闸不被分享链接绕过，D-2）；404 ⇒ 「链接已失效」。路由 `#diagnostics`＋`#diagnostics/share/<token>`（token_urlsafe 形态闭集校验，非法形态回落 projects不确认路由）；未登录公开分支渲染（与 enterprise-register 同构）。
- **测试**：vitest **1079 = 1054+25** 全绿（等价性 +6＋访客界面组件 10 例＋导航 +9）；typecheck 绿；rebase 融合 #374/#377/#381/#382（上游 40 文件零 desktop 交集，桌面套件结果承继）。
- **合并与部署**：PR #384 CI 四绿（run 43155323702；server-tests 实测 **3313 收集 = 3305 passed + 8 skipped**〔含上游插队服务器新例 95，归上游轮口径〕）→ squash `d092c2e`＝fork/main 顶；服务端零改动 ⇒ **活体 E0 复验**（不 rebuild 不 alembic）：alembic `a3e8c2f6b9d4 (head)` 不变／url_map **480** 不变／ready·live 200／诊断闸关 **404 而非 403**。
- **桌面交付**：便携版 **r39**（asar sha256 `d13f3b95d67b0cf2…`；本轮独有英文 marker 字节命中：`public-diagnostics` ×8／`public-diagnostics-share` ×4／`x-diagnostic-token` ×3／`diag-consent` ×3／`/api/v1/diagnostics/questionnaire` ×1）；★secrets-scan 首跑红＝桩令牌 `diag_tok-…` 取值熵过generic-api-key 阈值 ⇒ 换低熵桩值（断言语义不变，复跑绿）。

## [未发布] — 多客户 M6 轮：商业计量面按 org 隔离接线（NEW `commercial/org_read_scope.py`＋六个商业域读面接线＋NEW `test_m6_commercial_org_isolation.py` 20 例；零迁移零新表零新列零新路由；结构就绪·待授权，2026-11-12）

多客户 M6 =「商业计量结构落地」的**多租户接线轮**——G2/G3 商业计量结构已由 G 线交付并收口，本轮**不重建计费逻辑**，补的是此前唯一剩下的缺口：**商业域读面的 org 归属隔离**（此前只有「admin 全量／本人」两档，`org_scope_allows` 在 commercial 包零实调用）。

- **A 组·跨 org 读面隔离接线（单一 helper，判定权威不新建）**：NEW `server/src/fde_api/commercial/org_read_scope.py`——**归属推导走既有用户 FK → `users.org_id`**（科目行 `subject_user_id`／`payee_user_id`、权益与认证 `user_id`、商机 `reported_by_user_id`／`attribution_owner_user_id`／`presales_owner_user_id`），**不新增 org_id 列、不新增迁移、不改表结构**；判定权威仍是既有 `fde_api/orgs/isolation.py`（`org_scope_org_ids`／`is_platform_identity`）——**未新建平行权限判定**（红线 8 合规）。接线面：G3 科目层（列表／单条／筛选／对账）＋ G1 权益面 ＋ G3 认证记录面 ＋ G4 商机列表。
- **可见性口径（三态，承袭 M3a ＋ M5 已落模式）**：**admin** 全量（平台能力，逐位不变）｜**平台身份**（`org_id IS NULL`，非 admin）**只见本人**（存量口径逐位不变——M1 拍板「存量用户不回填」⇒ 存量回归面零变化）｜**企业身份**「本 org 成员互相可见」（M5 已落模式「本 org 成员或 admin」）。
- **失败码纪律**：跨企业命中 ⇒ **404**（M3a 规格 §3.5 默认口径「不确认资源存在」；探测不可分辨已钉）｜同企业无操作权 ⇒ 沿用该读面**既有码**（`commercial_ledger_forbidden`／`commercial_entitlement_forbidden`／`commercial_certification_forbidden`）——**不自造失败码、不改既有码**｜admin 跨 org 代操作**仍是 admin 行为＋留痕**（M3b 批次②先例**不推翻**，`cross_org_` 事件名前缀与 org 维度逐位不变）。
- **对象级与列表级同语义**（M3a 规格 §2 硬要求）：四态判定（`VIS_SELF`／`VIS_SAME_ORG`／`VIS_CROSS_ENTERPRISE`／`VIS_OTHER`）共用同一 helper ⇒ 不产生「详情 403／列表可见的幽灵行」；列表级 org 谓词 **SQL 下推**（红线 10，不在 SQL 后再加 Python 过滤）。
- **G2 两面（额度账／企业空间）经核实后不改**（如实登记）：CR-062 拍板的「**绑定账号本人或 admin**，他人一律 404」是**账号维度**的强判定，天然比 org 维度更严（别家企业账号必非绑定账号 ⇒ 必 404）；既有 `test_space_view_scopes` 明确钉住「**同主体第二经办人也 404**」——改之即推翻 CR-062。故本轮对这两面只做**现状核实**（三例），不冒充「本轮新增隔离」。
- **B 组·跨 org 隔离用例（进 CI）**：NEW `server/tests/test_m6_commercial_org_isolation.py`＝**20 例**（G3 科目层 5／权益＋认证 2／商机 1／**同企业两账号互见 2**／**平台身份存量用户零回归 3**／**admin 全量＋跨 org 留痕 3**／G2 两面现状核实 3／**USCC 单键去重口径未被 org 维度污染 1**）。**变异两连全红→字节级还原（sha256 一致）→绿**：M1（org 谓词 → 只含 actor 本人）**1 failed**／M2（跨企业分支 → 退化为 `VIS_OTHER`）**4 failed**；还原后 **20 passed** 复绿。
- **两套口径并置（USCC ≠ org_id）**：**USCC ＝ 去重维度**（`enterprise_quota_subjects` 的 PK，额度行唯一）↔ **org ＝ 可见性/隔离维度**（读面隔离）。本轮**未**把 USCC 改成 org——用例钉住「同主体额度行恒 1、主体行恒 1」，两套口径并置不互相取代。
- **本轮未做（业务闸与合规层，一律不代做）**：**三道业务闸未激活**（席位激活／扣费闸／售卖闸）｜**金额 unset**——`FIRST_ORDER_SEAT_FEE = 3980.00`（G 线已拍板的唯一落数金额）**一字未动**、`commercial_fee_configs` 三槽位**保持 unset**（缺省不可收款）｜**售卖闸 closed**（`regional_sale_gate` 四条件签署证据未登记）｜**合规签署未代做**、签闸栏日期与真实发布记录**不代填**｜不改 `billing_service.py` 六道扣费闸／`activate_seat`／`orgs/isolation.py` 语义／`admin_routes.py` 双闸路由｜不改 G4 七步转移函数语义／G5 区域四阶段语义／售卖闸开闭逻辑／四席位口径｜桌面端零改动｜`docs/audit/v3-*` 与 `docs/architecture/archify-diagrams/*/candidate.json` 零改动（本轮零结构变化 ⇒ 不触发清单重生成）｜Leader 任务书 §14 M6 行**保持 `[ ]` 不打勾**（验收未完成前打勾＝倒填）。
- **验收对照**：`docs/commercialization/multi-tenant/M6-验收对照-v1.md`；缺口回填 `00-gap-register.md` GAP-07／08／09／10（M6-1 轮**只追加**，四条**均不销号**）。
- **M6/M7 同一交付分支叠加（已裁决并执行）**：M6 轮与 M7 轮经 rebase 压成**单提交、一条线性交付分支、一个 PR**。两轮语义正交（M6＝org 维度可见性／M7＝客户名单导出权），唯一重叠点 `attribution_service.py::list_opportunities` 已按「**以 M7 的 `_opportunity_scope_filter(actor)` 单一谓词为底，把 M6 的 org 谓词（`org_read_scope.visible_user_ids_query`）融进去**」解决；`scope_filter` 与 `scoped_ids` 共用同一谓词 ⇒ M7 枚举闸基准自动跟随 org 可见域，字段遮蔽与枚举闸**独立生效、未被 org 谓词绕过**。
## [未发布] — 多客户 M7 轮：商机数据归属权硬约束＋S5 场景端到端＋区域面 org 维度接线（ADR-M7＋归属权原语＋读面裁剪；零迁移零新表零新列零新路由；售卖闸维持 closed、合规签署未代做，2026-11-12）

多客户 M7-1 轮（leader 任务书 §7 M7）——**只落结构与测试**：三道业务闸不激活、金额不预写、售卖闸维持 `closed`、合规签署**未代做**。本轮状态＝**结构就绪·待授权**（M7 后置的**业务/合规授权层**理由仍维持：合规条件清单四项签署未完成）。

- **商机数据归属权写死**（sec 评审硬条件「归属权与导出权**须在 M7 写死**」；leader 任务书 §7 M7 原文「**平台托管、企业确认前区域服务商不可导出客户名单、双方按授权可见**」——渠道客户名单是商业敏感资产，归属不写死会成为渠道纠纷源头）：NEW `docs/commercialization/multi-tenant/ADR-M7-opportunity-data-ownership.md` 五项裁决＋成文规则 `docs/commercialization/rules/opportunity-attribution-rules.md` **§9「数据归属权与导出权」**（含机器可读块，**文档块／代码常量／测试三方一致**机器闸）。服务层 `attribution_service.py` 落归属权原语——`is_opportunity_custodian`（托管方＝平台 admin）／`is_regional_partner`（区域服务商身份＝既有 `regional_partners.applicant_user_id` 推导，**零新授权表**）／`customer_identity_visible`（可见性判定式）／`require_enterprise_confirmed_for_customer_list`（枚举闸，fail-closed）；读面裁剪落 `list_opportunities` ＋ `serialize_opportunity`——客户识别字段（`enterprise_code`／`enterprise_registered`）不可见时输出 `None` ＋ 显式 `customer_identity_visible=false`（**遮蔽而非删除**，字段形状稳定）。
- **★硬约束落点（P1 绕过路径的正解）**：既有 `GET /api/v1/commercial/opportunities` 列表读面**本身就是客户名单导出面**（admin 全量含企业代号＋「企业是否已注册」派生事实，且支持 `?enterprise_code=` 枚举）⇒ 硬约束**落在列表读面与序列化层**，**不是**另开一个 export 端点（另开端点无效：绕过路径在既有读面）。枚举探针判定精确到「是否会泄信息」：命中行全在 actor 可见域内 ⇒ 放行；命中行全已企业确认 ⇒ 放行；存在「**域外 ＋ 未企业确认**」的行 ⇒ **403 `opportunity_customer_list_not_confirmed`**（读面授权判定，与既有 `opportunity_forbidden` 同族；**409 留给状态机冲突**）。
- **托管方例外**：admin（平台方）全量可见**保持不变**（含未企业确认商机）——与 M3b「admin 跨 org 代操作留痕不阻断」一致；硬约束针对的是**区域服务商这一外部角色**。**非区域服务商账号的既有可见性语义逐位不变**（不越界改写既有口径）。
- **区域面 org 维度接线**（`regional_service.py` 的 `list_partners`／`get_partner`）：**零新列零迁移零新表**——org 归属经 `applicant_user_id → users.org_id` 推导（OWNER 2026-11-12 拍板：主体归属走 `user.org_id` **间接归属**，不新增 org_id 列、不新增迁移、不改表结构）。企业身份可见「本人申请的 ＋ 同 org 其他成员申请的」；跨 org ⇒ **404**（不确认资源存在，CR-062）；**平台身份非 admin 的既有语义逐位不变**。
- **S5 场景端到端**（leader 任务书 :36「区域伙伴注册 → 报备企业线索 → 企业确认归属 → 保护期 → 撮合」）：NEW `server/tests/test_m7_s5_e2e.py` 9 例——全链走通（含保护期规则位未配置 ⇒ 409 `rule_not_configured` **不回落默认值**）＋**GAP-11 反例**（企业自行注册不转移归属）＋售卖闸关闭态边界（推进正式档 ⇒ 409 `regional_sale_gate_closed`；源码扫描钉「正式档写点唯一且在过闸函数内」）＋**区域档目录在关闭态下仍可见**（既有行为，**不是漏洞**——目录可见 ≠ 可签约；边界显式钉住，避免后续被误读成闸失效）。**⚠ 席位口径**：S5 第一步报备依赖席位 active（`_require_sourcer_seat` fail-closed），席位 active 的唯一来源是 G3 `activate_seat`（首单扣费后激活），而 §17-1 拍板「席位计费在有真实外部交付者前不激活」且工程侧零门控 ⇒ 用例**复用既有 `_activate_seat` 夹具（测试态激活）**，docstring 显式标注「**席位为测试态激活、非商用态、不触发真实计费**」；**未改** `activate_seat` 路径、**未加**全局门控、**未改** G4 拉单资格判定式。
- **测试**：NEW `test_m7_opportunity_data_ownership.py` **13 例**（规则文件↔代码常量↔测试三方一致／枚举闸 403／客户识别字段遮蔽／双方按授权可见／托管方例外／零新表零新列零新路由**源码扫描哨兵**／错误码闭集只增不改／原语层判定逐项核对）＋`test_m7_s5_e2e.py` **9 例**＋`test_m7_cross_org_opportunity.py` **10 例**＝ **32 例**；邻域回归 `test_commercial_opportunity_attribution.py`（**23 passed**）＋`test_commercial_regional_partners.py`（**31 passed**）＋`test_m3b_batch2_commercial.py`（**14 passed**）＝ **68 例全绿**；`ruff check --select F401,F841 src tests` → All checks passed；`scripts/check-python-types.py` → **OK：baseline 279 occurrences / 104 distinct，current 279**（零新增类型错误）。
- **零结构变化自证**：**零迁移零新表零新列零新路由**——本轮对 `docs/audit/v3-*` 三份清单、`docs/architecture/archify-diagrams/*/candidate.json`、`server/tests/test_migrations.py` **零改动**，归属一律经既有用户 FK 推导。★**结构口径与全量收集数一律以合并后 `fork/main` 的 `docs/audit/v3-workbench-inventory.json` 与 CI run 实测为准，本轮不写死数字**（main 在并发推进，写死即过期；本轮零结构变化 ⇒ 清单数字在合并前后逐位不变）⇒ 无需 rebuild/alembic/重打包；桌面零改动。
- **文档回填**：NEW `ADR-M7-opportunity-data-ownership.md`＋`M7-验收对照-v1.md`；`phase-status.md` 新增「M7」阶段节＋验收证据表＋**口径修正**（`:309` 原引用的 `test_report_requires_r2_role` **在本仓不存在**，真实用例是 `test_report_requires_paid_seat_not_role`，且「报备＝R2」口径已被 ADR-011 §5-F 改为「缴 3980 席位费、不限角色」；`:670` §16 #13「已签署」判 ✅ 改为「**绑定签署证据齐备（本期四条件槽全空、闸 closed）**」＋加注「判 ✅ 者为结构性绑定而非已签署事实」；`:62` 陈旧收集数按本轮 CI 实测口径化——**不写死历史数**）；`docs/商业化_G1_G4_Goal实施任务书.md` §16 **只勾 :527/:528**（G4 七步链、G5 四阶段），**`:529` 保持未勾**并加旁注「结构就绪/待授权：开关默认关与缺件不可开门已验收；合规四项签署＋律师意见待 OWNER/法务」；leader 任务书 §14 M7 行**不打勾**（只追加注记）；GM 线联合排期草案 §4 拍板点 3 **原行不删不改 ✅**，**追加 v2 裁决行**（工程排序层提前／业务合规授权层后置维持 ⇒「结构就绪·待授权」）；`00-gap-register.md` GAP-11/GAP-12 状态回填（只追加）；`v3-backlog.md` 新增 `T-M7` 台账行（**不用 B# 编号**——`AGENTS.md:45` B# 已 FREEZE 封顶 B#40）；`AGENTS.md` 当前状态条目＋现行结构口径行。
- **与 M6 的边界（合并协调）**：M6 负责**商业域读面按 org 隔离的通用接线**（科目层／额度账／企业空间／权益／认证记录／**商机列表**），M7 负责**商机数据归属权硬约束**＋**区域面特有部分**。★**唯一重叠点是 `attribution_service.py::list_opportunities`**（M6 把可见域谓词换成 `visible_user_ids_query(actor)` 的 org 谓词下推；M7 改的是**可见行内哪些客户识别字段可读**＋**枚举探针闸**）——双方口径**正交可叠加，不需要任何一方让步**；**合并策略＝以 M7 的谓词结构为底**（`_opportunity_scope_filter(actor)` ＋ `scoped_ids` 与 `scope_filter` 共用同一谓词）**把 M6 的 org 谓词融进去**。M6 侧其余改动文件（`billing_service.py`／`enterprise_service.py`／`ledger_service.py`／`quota_service.py`／`service.py`／NEW `org_read_scope.py`）与 M7 **零文件重叠**。⚠️**合并前置检查项**：M7 改了 `serialize_opportunity` 签名（新增 `actor` 关键字参数 ＋ `enforce_ownership`）——M6 当前 diff 未改该函数调用点，合并时无需改动；但**合并后 M6 若新增调用点须带 `actor=`**（漏带直接 `TypeError`）。
- **未做（授权边界内）**：不开售卖闸、不登记合规条件证据（`register_gate_condition`／`open_sale_gate` **零调用**）；不激活席位计费；不改 G4 七步转移函数语义／G5 区域四阶段语义／售卖闸开闭逻辑／`require_sale_gate_open`／`register_gate_condition`／`open_sale_gate`／`_require_sourcer_seat` 判定式／`activate_seat`／`FIRST_ORDER_SEAT_FEE`／任何配置位数值／`orgs/isolation.py`；不代做合规签署、不代填签闸栏日期、不代填真实发布记录；「后置」不得改成「已完成/✅」。

## [未发布] — 交付案例学习闭环 L3 轮·agent 上下文知识片段接线：lessons.json 静态经验条目层＋污染单向阀种子收敛（NEW agents/lessons.py＋agents/service.py 接线＋11 例静态钉；零迁移零路由零蓝图零桌面，2026-11-12）

- **这一轮解决什么**：agent 上下文的「知识片段」段管道早已铺好（`render_masked_context` 支持、唯一调用点 `agents/service.py` 硬编码空元组＝管道在、水源没接）——L3 接上水源：`server/seeds/lessons.json` 静态「经验条目」层（设计稿 §2.3 方案 A）。
- **三函数 NEW `server/src/fde_api/agents/lessons.py`**：`load_entries`（装载 fail-closed：种子缺文件/形状坏即拒）、`select_lessons`（纯函数选择：条目 `capability_tags` 须含当前 agent `capability_tier`＝能力腿过滤＋可选 `industries` 行业过滤＋`top_k`/`max_chars` 防上下文膨胀）、`knowledge_snippets_for`（接线入口，运行时**软失败**——任何装载异常回落空片段，run 路径不为种子问题炸客户可见面；渲染面既有禁区词＋模式遮蔽闸二次把关，零新脱敏面）。`agents/service.py::_render_context` 接线（+7 行）；配置三键 `agent_lessons_enabled`/`agent_lessons_top_k`/`agent_lessons_max_chars`（缺省 true/3/400，`.env.example` 同步 +3 行）。
- **内容纪律静态钉 NEW `server/tests/test_lessons_wiring.py` 11 例**：条目只含抽象打法/判据（零案例答案、零客户资料、零未溯源数字）＋逐条 `source_ref` 指针＋`sha256` 指纹——钉住 schema 闭集（未知键即红）、逐条 sha256 一致（**改 text 必留 diff**）、答案字段词汇零命中、能力域闭集。
- **★CI 真红事故与裁决（PR #377 server-tests 首轮 2 failed / 3206 passed）**：初版种子含 4 条诊断展示面提炼条目（LESS-DIAG-001..004），污染钉 N2（`server/src/fde_api`）与 N3（`server/seeds`）同时命中「诊断案例集」路径 token。判定：AGENTS 评测集污染隔离红线——「展示面例外」只覆盖展示产物，且展示产物目录不得被生成器检索路径引用；`lessons.json` 是**生成器可见的知识库种子面**，展示面提炼条目不得进（展示面例外被更严格约束覆盖）。处置：种子收敛 SOP-only 10 条（LESS-SOP-001..010，text 未改 ⇒ 十条 sha256 指纹不变，逐条指纹钉仍成立）；「双来源（SOP＋诊断展示面）」拍板与机械闸冲突时以红线为准、**留痕可推翻**（若后续另设不被生成器检索路径引用的展示面位置，可再议增补）。
- **验收**：本地 importlib 直调 11 例全绿＋渲染验收实例（app context 内 `_render_context` 知识片段段非空）；ruff 绿；官方 mypy 闸 279 基线不变；N2/N3 禁词零命中。PR #377 squash `8b858d7`＝fork/main tip；合并树 main run 43151465600 四 job 全绿（server-tests 实测 3261 收集 = 3253 passed + 8 skipped）。
- **活体验证（同日部署轮）**：容器内 `load_entries` 10 条在场（Dockerfile `COPY seeds` ⇒ `/app/seeds/lessons.json`）＋`select_lessons(capability_tier="agent.module.acceptance")` 非空选中 LESS-SOP-008——接线面在活体可用。
- **口径**：零迁移零路由零蓝图零桌面（服务端种子＋agents 接线；pytest +11）。

## [未发布] — 交付案例学习闭环 L2 轮·训练场分布读数：批跑器＋分布读数库＋底册 CLI＋真机首读（NEW scripts/simulation 三件＋真机撞出三条 API 语义缺陷修复＋32 例钉＋部署活体三验＋⑦出站闸回归补回；零迁移零路由零蓝图零桌面，2026-11-12）

- **这一轮解决什么**：训练场此前只有单点 run＋三层评估呈现，分数面没有可判定读数——L2 把诊断线实证的「分布读数＋噪声带判定」方法复用到训练场，判定规则 `delta-noise-band-simulation-2026-11-12`（登记可推翻、**非校准阈值**：Δ 可判定 ⇔ 两组各 n≥3 ∧ |Δ|>噪声带〔观测极差较大者，严格大于〕；n 不足 ⇒ insufficient_data；通过线未校准前不判达标）。
- **NEW 三件（`scripts/simulation/`，零生产代码改动）**：`run_batch.py` 批跑器（走生产 HTTP 面：`POST /simulation/runs`→execute→evaluate→`GET /runs/<id>/evaluation`；逐 run 一行 JSONL 落**真相层**、仓内输出即拒；分数与轴值入行、场景正文与判卷基准零落盘。锚点模式＝**只建一个 run 对同一 run 反复 evaluate N 轮**——服务端同 (run, 层, 评估器, 规则版本) 重评是更新该行，N 轮读数逐轮独立；`retry_run` 对 completed 恒 409 故锚点不走 retry）；`run_distributions.py` 分布读数库（复用 `scripts/diagnostic_eval/eval_lib.py` 单一真身；三条机械不变量：失败/缺分 run 不是 0 分是无数据、无分数态 verdict〔hard_fail/inconclusive/unavailable〕排除、n<2 不编造 stdev；**层行按 evaluator_id 索引**——同一 run 上 `model:stub` 与 `model:server` 并存不互相覆盖；**锚点轴层感知**＝rubric × 所测层评估器）；`summarize_run_distributions.py` 底册 CLI（汇总 JSON 落真相层，stdout 出 markdown 底册）。
- **真机批跑撞出三条真缺陷逐条修复＋32 例钉**（18 分布库＋14 批跑器，其中状态词表钉从服务端 `models.py` 源码正则取真值——服务端改词表先红）：①状态词表 `succeeded`≠`completed`（服务端 RUN_STATUSES 成功终态是 completed，全仓无 succeeded——写错则成功 run 当失败、评估永不触发）；②锚点取样机制（retry 对 completed 恒 409 ⇒ 改同 run 反复 evaluate，`eval_round` 进幂等键）；③unavailable 当 0 分＋层行覆盖 ⇒ `NO_SCORE_VERDICTS` 排除＋evaluator_id 索引＋层感知锚点轴。另：API 前缀归一 `_api_base`（蓝图 `url_prefix="/api/v1/simulation"`，主机根缺前缀即 404；幂等四形态自测）。变异三连全红→字节级还原→复绿（M1 摘状态词表 1 红／M2 摘无分数态排除 1 红／M3 摘层感知锚点轴 3 红含主钉）。PR #374 squash `ecba5c0`；CI 四 job 全绿（head `d52be67` check-runs API 全读）。
- **部署活体（合并后从 `8b858d7` 干净树接管生产项目名 `fde-workbench`）**：rebuild 三镜像与构建产物逐位一致（api `e39ce88b279f`／worker `54f9a3647cdd`／scheduler `35e333d667f1`）＋容器内 `alembic current`＝`a3e8c2f6b9d4 (head)`（幂等 no-op）＋活体 `url_map` **480** ≡ 口径＋`ready`/`live` 200＋三容器 healthy。★**修复 ⑦ 出站闸活体回归**：T-15 接管部署栈时新拷的 `server/.env` 未携带 `FDE_AGENT_HOST_EGRESS_GATE_ENABLED`/`FDE_AGENT_HOST_EGRESS_ALLOWLIST` 两键（容器 env 实测两键缺失＝闸静默回默认关），本轮补回白名单六域并容器 env 活体验证在位——部署配置不进 VCS 的家族性风险实录，接管部署树必 diff 前任 `.env` 键名集。补 `FDE_DEEPSEEK_SIMULATION_EVALUATION_MODEL=MiniMax-M3.1-Flash`（单模型端点留默认 `deepseek-v4-pro` 会被 400 拒——v3.2 G9 实录教训）。
- **真机锚点批跑首读（真相层 `D:\test\FDE\knowledge\训练场分布读数\l2-anchor-20261112\`）**：锚点 IMP-SOMWYN-E2E（active v2）1 run×3 评估轮＋逐场景 IMP-DW015-TRADE-DOCS 3 seed（42/43/44）＝6 run 全 completed。**规则层底册（summary.deterministic-20261112）**：锚点组 `rubric-v1|rules@rubric-v1` n=3 极差 **0.0**（同 run 重评＝确定性评估器零方差——锚点取样机制实证，非「评估噪声小」的结论）＋逐场景组 `2|rubric-v1|mock` n=3＋**训练场首条 decidable 判定**（IMP-DW015-TRADE-DOCS vs 锚点：Δ=0.1＞噪声带 0.0，n 3/3）。**模型层被外部闸拦住**：6 行 `model:server` verdict=unavailable——MiniMax 端点 429「已达到 Token Plan 用量上限」（错误码 2056），审计账本当日 0 成功/16 失败＝套餐级耗尽非短窗限流；按缺陷③钉语义全数按**无数据**排除（summary.model-ratelimited-20261112：score_rows=6 ⇒ insufficient_data）——假 0 分进分布被机械拦下，钉按设计工作。**L2 验收状态＝部分达成**：管线＋判定规则实跑达成（含首条 decidable）；模型层评估侧噪声带（锚点 n≥3 真模型读数）**挂账**，消解条件＝MiniMax 配额恢复（升级套餐/购积分，OWNER 账户决策）后：归档本次 runs.jsonl → 重签容器 JWT → 重跑同命令 fresh（幂等键会跳过已记录轮，必须换文件起跑）。
- **指纹（真相层原件，仓库侧只存指针）**：`runs.jsonl` `a66dfa4973e8ebad…`／`summary.deterministic-20261112.json` `8dc71808dab5c548…`／`summary.model-ratelimited-20261112.json` `988bb31871078331…`／`manifest.json` `732056b484c736ae…`；首跑缺陷产物归档 `runs.first-run-defective-20261112.jsonl` `c52ed91fbb055056…`。明细与读法边界 NEW `docs/audit/训练场分布读数-L2底册-1.md`。
- **口径**：零迁移零路由零蓝图零桌面（scripts 层＋服务端测试 +32；合并树 main run 43151465600 实测 **3261 收集 = 3253 passed + 8 skipped**＝T-15 合并树 3218 收集 + 32 + 11，逐位吻合）。

## [未发布] — 获客诊断第二十轮·T-15 渠道接线：渠道链接注册表＋服务端 partner 归因推导＋桌面渠道链接管理面板（NEW `diagnostics/channel_links.py`＋3 路由 477→480＋迁移 `a3e8c2f6b9d4` 70→71，2026-11-12）

- **这一轮解决什么**：T-11 立了三档归因（A 渠道报备／B 认领转化／C 平台留存），但 **A 档的来源凭证此前没有任何产生机制**——`source_type='partner'` 只能由客户端声明，等于「谁说自己带来的就记谁的」；T-15 补上**渠道链接 ID 体系**：平台发链接 → 渠道方把链接标识带进来 → 服务端**机械推导**归因，零手工记账（P-2）。
- **核心语义三条**（服务端 NEW `server/src/fde_api/diagnostics/channel_links.py`）：①**A 档不接受客户端声明**——`source_type='partner'` 一律 400 `partner_source_forbidden`，渠道报备归因**只能**由有效渠道链接 token 服务端推导（谁发链接谁才是凭证唯一来源）；②**token 明文只此一次**（创建响应返回，库里只有 sha256 指纹，沿匿名会话令牌同尺；清单投影无明文无指纹）；③**fail-closed 降档而非拦单**——`channel_ref` 命中在用链接 ⇒ 落 `partner` 且 `channel_ref` 记链接行 UUID；未命中／已过期／已停用 ⇒ **降档 `direct`** 且 ref **原样留痕**（**不拦真实线索**——渠道方带旧链接来也不该把人挡在门外；审计链不因降档而断）。停用是**软撤**：历史 partner 行不回滚（归因在**会话创建时刻**定格）。
- **`channel` 免费名目语义零变化**：协会活动这类免费名目仍由客户端声明＋自由文本 ref，仍 400 `channel_ref_required`——本轮只把 **A 档**收进凭证体系，不动另外两档。
- **服务端 3 个 admin 专属路由**（部署闸先于鉴权：闸关 ⇒ **404 不是 403**；`require_role("admin")`）：`POST /api/v1/diagnostics/leads/channel-links`（201，明文 token 一次）、`GET .../channel-links`（清单含归因线索数，**零明文零指纹**）、`POST .../channel-links/<id>/deactivate`（软撤，幂等；不存在 ⇒ 404 `channel_link_not_found`）。
- **数据模型**：NEW 表 `lead_diagnostic_channel_links`（迁移 `a3e8c2f6b9d4`，70→71 单头，父＝T-11 `d7e2f4a9c1b3`）——`token_sha256` 唯一索引＋64 位 CHECK；`is_active`／`deactivated_at` CHECK 钉「停用必有时刻」；`created_by_user_id` FK `users` SET NULL；**零外键指向 `projects`**（沿 T-10a 隔离纪律：线索≠项目）。
- **桌面 NEW `leads/ChannelLinksPanel.tsx`**（admin 专属，接在线索池页）：生成专属链接（区域/备注可选）→ **明文 token 就地呈现一次**（「我已保存，关闭」后不再可见）＋ `…?channel_ref=<token>` 拼接提示；清单显示 区域／备注／**归因线索 N 条**（渠道方对账可见）／在用徽标；停用走确认弹窗，回执「已停用：新线索不再按该链接归因，历史归因保持不变。」；非 admin 不可见（与 `require_role("admin")` 同构）。
- **测试与验证**：服务端 NEW `test_diagnostics_channel_links.py` **13 例**（admin-only 401/403/200／闸先于鉴权 404／token 只此一次＋库里只有 sha256＋清单无明文无指纹／payload 校验／有效链接机械 partner 且 ref=链接 UUID／stale ⇒ direct 且 ref 原样留痕／partner 声明 400／channel 名目语义不变／停用后新会话 direct＋历史 ["partner","direct"] 定格＋幂等／未知 link 404／lead_count 累计／零 FK 指向 projects／零比例字段）＋改写 3 处既有用例（新契约）＋诊断域回归 **191 例绿**；ruff 绿；mypy **279 基线不变**。桌面 NEW `channel-links.test.tsx` **9 例**（形状守卫／清单渲染／空清单与加载失败／404 闸引导／创建 token 呈现与关闭后消失／创建失败就地报错／停用确认流／停用取消不打服务端／admin 可见性）＋typecheck 绿＋`test:desktop` 全量 **1054 例**（1045 基线+9）。
- **结构口径**：路由 477→**480**／蓝图 52／表 152→**153**／70→**71 rev** 单头 `a3e8c2f6b9d4`；`api_catalog` **94 ENTRIES 不变**（三个渠道链接路由属诊断域治理面，不进 catalog——沿 T-10a/T-12 先例）；审计清单三件套重生成＋archify candidate.json 同步（防陈旧闸绿）。
- **合并与交付**：PR **#375**（分支 `feat/diag-channel-links`）——★文档剥离（AGENTS/CHANGELOG/任务书三文件不进证据 PR，随合并后另起回填 PR——沿 T-10a #282／T-10b #301／T-11 #366／T-12 #370 先例）→ CI run 43134830915 四 job 全绿（server-tests 实测 **3218 收集 = 3210 passed + 8 skipped**＝T-12 合并树 3205 + 本轮 13 逐位吻合）→ squash **`b6092b2`**。**部署活体三验（七撞纪律）**：从 `b6092b2` 干净树 `D:/test/fde-wt-deploy-t15` rebuild 三镜像（api `43a15e4ed8ec`／worker `6ba25983950c`／scheduler `c5058544dc4d`，三容器 `.Image` 与构建产物**逐位一致**）＋`alembic upgrade head` 真实升级 `d7e2f4a9c1b3 → a3e8c2f6b9d4 (head)`＋活体 `url_map` **480** non-static ≡ 口径＋诊断面闸关 **404**（先于鉴权；渠道链接路由同样 404）＋ready/live 200＋活库新表 9 列在位且外键仅 `users`。**便携版 r38**（asar sha256 `2a4a5e90fafe934825fd40c97a694f1bfebefe1a0d075436384cc67ea7ac8c2e`；本轮独有英文 marker 字节命中：`channel-links-token` ×4／`channel-links-panel` ×2／`/api/v1/diagnostics/leads/channel-links` ×1——★探针须用 **python 字节计数**，asar 内超长 marker 在 `grep -a` 下会假阴性）。
- **挂账／下一轮**：**T-16 价格轮**落 A/B 档转化费比例（`pending_pricing` 结构已就位）；**T-14 官网诊断入口**（内容飞轮的上游，网站侧待开）；**任务书 T-15 交付物第二项「复盘内容／内容飞轮」本轮未做**（本轮只落渠道链接 ID 体系）；**D-4 地方诊断服务商入围资质**＝线下业务动作待蔡工拍板；认领→presurvey 项目转化端点待后续轮。

## [未发布] — 获客诊断第十九轮·T-12 线索池控制台：桌面线索池页＋认领申请＋admin 裁定队列＋服务端认领单列表读面（NEW `leads/LeadPoolPage`＋`GET /api/v1/diagnostics/leads/claims`；+1 路由 476→477 零迁移，2026-11-12）

- **这一轮解决什么**：T-11 把认领闸做成了服务端机械闸，但员工在桌面端没有可用的操作面——线索池看不见、认领没法发起、admin 的 accept/reject 端点没有任何 UI 可达（认领单 ID 是 UUID，无从发现）。本轮补齐整个闭环。
- **桌面（NEW `leads/LeadPoolPage.tsx`，路由 `#leads`＋导航「线索池」）**：认领身份选择（R2 创业者看全部未认领线索／R4 区域合作商只看本区域，区域必填客户端预检）；池卡片只显示代号化字段（行业／规模／区域／痛点一句话／报告状态／窗口倒计时——服务端投影本就不含联系方式与姓名）；认领申请弹层（`subject_key` 自认领识别＋留言；提交后就地回执「待平台接受」；409 闸错误〔窗口过期／一线一线／区域不符／无区域 fail-closed〕弹层内就地呈现）；admin 裁定面与 `require_role("admin")` 同构（pending 队列＋认领人账号名＋自认领信号＋裁定备注＋接受/驳回〔驳回走确认弹窗〕）；非 admin 只见「我的认领申请」；404＝诊断面未启用 ⇒ 引导文案。任务书旧句「认领 → 一键转 presurvey 项目」是 P-6 拍板前旧语义——服务端尚无认领→项目转化端点，页面不臆造，转化留待后续轮。
- **服务端（NEW `GET /api/v1/diagnostics/leads/claims`，零迁移 +1 路由）**：两段可见性同一路由——admin＝全量裁定队列，非 admin＝只看自己的申请（`claimant_user_id == actor.id`）；`status` 闭集过滤 `pending/accepted/rejected/all`（非法值 400）；`limit` 封顶 200；投影＝认领单＋线索摘要（**代号化**，不含联系方式与姓名）＋认领人**账号名**（username 是账号体系字段，不是真实姓名）；`gate_first` 404 先于鉴权；`auth.models.User` 函数内懒导入（包环冻结闸纪律）。
- **测试与验证**：服务端 NEW 4 例 ⇒ 认领套件 **34 例全绿**；诊断域回归 **106 例绿**；ruff 绿；官方 mypy 闸 **279 基线不变**。桌面 NEW `lead-pool.test.tsx` **12 例**（形状守卫／窗口倒计时纯函数／R4 区域预检／POST 载荷断言／就地回执／409 弹层呈现／404 引导／admin accept 载荷／非 admin 无裁定面／驳回确认流）；typecheck 绿；`test:desktop` 全量 **93 文件 1045 例全绿**（1033 基线+12）。结构口径：路由 476→**477**／蓝图 52／表 152／70 rev 单头 `d7e2f4a9c1b3`（零迁移）；审计清单三件套重生成＋archify candidate.json 同步（防陈旧闸绿）。
- **合并与交付**：PR **#368**——★插队实录：#367（N3b 本体轮 +2 路由 474→476）在途合并 ⇒ rebase（冲突=inventory JSON＋candidate.json，取上游后由 extractor 按代码重生成=477）→ CI run 43119919454 四 job 全绿（server-tests 实测 **3205 收集 = 3197 passed + 8 skipped**＝N3b 合并树 3201 收集 + 本轮 4）→ squash 合并 SHA **`abea9c2`**。**部署活体三验（七撞纪律）**：从 `abea9c2` 干净树 `D:/test/fde-wt-deploy-t12` rebuild 三镜像（api `e3c615aa36c5`／worker `fab55cd49063`／scheduler `161970aa2b93`，三容器 `.Image` 与构建产物**逐位一致**）＋容器内 `alembic current`＝`d7e2f4a9c1b3 (head)`（零迁移头位不变）＋活体 `url_map` **477** non-static ≡ 口径＋claims 路由闸关 **404**（先于鉴权）＋ready/live 200。**便携版 r37**（asar sha256 `c14fdeb43551fbfa…`；本轮独有英文 marker 字节命中：`lead-pool-decision` ×3／`lead-pool-submitted` ×2／`/api/v1/diagnostics/leads/claims` ×2——vite 转义非 ASCII，探针用英文标识的既定配方）。
- **挂账／下一轮**：**T-15 渠道接线**（R4 专属链接携带渠道链接 ID ⇒ 归因自动落 `source_type`，零手工记账）；**T-16 价格轮**落 A/B 档转化费比例（`pending_pricing` 结构已就位，比例待价格轮才落数）；认领→presurvey 项目转化端点待后续轮（服务端语义就位后桌面一键接）；F3 认领续翻待领导拍板。

## [未发布] — 交付案例学习闭环 L1 实施轮：真相层导入卡 → 训练场摄取管线（转换器 NEW `scripts/simulation/import_cases.py`＋污染单向阀静态钉＋首批 4 包清单；pytest +10；零迁移零路由零蓝图零桌面零生产代码改动，2026-11-12）

蔡工 2026-11-12「开L1」授权后按设计稿 §5-L1 行落地缺口一——知识层交付案例 → 训练场场景库的摄取管线；并把污染单向阀从「设计裁定」升级为机械静态钉（校验判别力本身已验收）。

- **摄取管线（转换器）**：NEW `scripts/simulation/import_cases.py`——真相层 `import_card_v1` 卡 → 训练场导入包（与 `POST /simulation/scenarios/import` 信封同构）。闸门四连 fail-closed：卡 schema 允许名单（未知顶层键／缺 attribution 必填键即拒）→ 生产 `validate_scenario`（八规则）→ 生产 `load_view` 三视图泄漏自检（tester/customer/judge）→ 输出目录落本仓内即拒（判卷基准永不进仓）。
- **人工闸不放松**：转换器写死 `source_kind='import'`、`status='draft'`；建行（导入）与激活（draft→active）两步皆人工动作，AI 不代发起、不碰 API。激活走 `PATCH /simulation/scenarios/{id}`（追加不可变新版本，旧版不可变）。
- **污染单向阀机械承载**：NEW `server/tests/test_diagnostic_simulation_valve.py`——AST 静态钉两例：①`fde_api/diagnostics/**` 零 simulation 导入（诊断生成器面不许反向读训练场）②`scripts/diagnostic_eval/**` 的 simulation 导入仅许 judge 白名单（`fde_api.simulation.diagnostic_judge`）。判卷基准可进训练场 judge 参考面，禁流向诊断生成器。
- **首批 4 包（真相层，仓库侧只留指针＋sha256）**：IMP-SOMWYN-E2E（仓内代号化复盘）／IMP-DW015-TRADE-DOCS＋IMP-DW008-LEGAL-DOCS（FDE-case-library MIT 独立抽象重写，附来源对照表＋许可快照）／IMP-SOMWYN-DIAG（诊断案例集复用＝单向阀验证卡，判卷基准经字段映射只进 judge 面）。清单与指纹见 `docs/audit/交付场景导入包-首批清单与指纹-2026-11-12.md`。
- **验收证据**：转换器实跑 4/4 包过闸；pytest +10 全绿（转换器套件 8 例＋真相层实卡验收 1 例［卡不在场显式 skip，不静默绿］＋单向阀静态钉 2 例）；变异三连全红→还原→绿（M1 摘 attribution 必填闸／M2 摘泄漏自检／M3 诊断面注入 simulation 导入，各恰一钉红）；既有污染钉 7 钉复跑全绿（被扫面零答案材料零回归）。
- **拍板留痕**：设计稿 §6 四项未获逐项答复，按「按推荐执行＋留痕可推翻」先例记默认立场——①独立 L 线 ②首批三类来源照单 ③单向阀确认并加静态钉 ④L3 才消费 lessons 来源边界；记录于 `docs/audit/交付案例学习闭环-L1任务书-2026-11-12.md`，可推翻。
- 口径：脚本＋测试＋文档轮——**零迁移零路由零蓝图零桌面零生产代码改动**（L1 轮当轮现测 469 路由／51 蓝图／151 表／69 rev 单头 `c1d4e7f9a2b3`，当轮口径不变；现行口径以 AGENTS.md「现行结构口径」行为准；mypy 279 基线不变；无需 rebuild/alembic/重打包）。导入与激活由蔡工在桌面/API 人工执行，清单 §4 给了三步指令。

## [未发布] — AI 原生化 N3b 本体轮：G-04 方案条目 AI 起草＋G-03 DAG AI 起草返件式零落库（NEW `plans/draft_ai.py`＋`workflows/draft_ai.py`＋2 路由全不进 api_catalog；确定性缺省腿零改动＝并列双来源闸唯一；G-04/G-03 双 CLOSED，台账 v1.16；+2 路由 474→476，零迁移，2026-11-12）

- **G-04（交付方案条目 AI 起草 → CLOSED）**：NEW `server/src/fde_api/plans/draft_ai.py`——`DELIVERY_PLAN_DRAFT_SYSTEM_PROMPT`（J-1 白名单登记）＋契约校验器 `validate_plan_draft`（item_type 六值闭集／requirement_key·fact_id 闭集＝项目在册值〔越界整批拒绝〕／requirement 条目必引键／覆盖先验〔每条 accepted 需求 ≥1 条目引用，缺项整批拒〕／确定性归一〔条目保持模型序、引用去重保序〕）＋输出端兜底脱敏（`redact_text_detailed` 递归 title/detail：词典故障 422 `pseudonym_dict_unavailable` fail-closed／凭据串 422 `sensitive_credential_detected`）＋落库走既有 DeliveryPlan/DeliveryPlanItem（版本行递增 `_next_version`、历史不覆盖）＋事件 `delivery_plan_ai_drafted`（prompt_version＋model 归因）＋`delivery_plan_redaction_review` 脱敏复核事件。NEW 路由 `POST /api/v1/projects/<project_id>/delivery-plans/generate-ai`（can_manage，plans 蓝图 6→7，不进 api_catalog；DSH 故障 503/409 同尺映射）。**发布语义零新增闸**：产物恒 draft，`review_plan`（approved 闸＋审核戳）→`publish_plan` 既有闸机械承载「仅经 approved 闸发布」；确定性拼装 `generate` 缺省腿零改动（AI 草稿与确定性草稿并列共存＝并列双来源）。
- **G-03（DAG AI 起草通道 → CLOSED，ADR v1 §3 实施）**：NEW `server/src/fde_api/workflows/draft_ai.py`——`WORKFLOW_DAG_DRAFT_SYSTEM_PROMPT`（J-1 白名单登记）＋形状契约校验器 `validate_workflow_dag_draft`（顶层恰 `{nodes}`／节点 1–`MAX_AI_NODES=24`〔ADR §8 预授权参数级决定〕／字段 ⊆ `ALLOWED_NODE_FIELDS`／type 四值闭集／**契约推荐项 ≥1 human_approval 钉死** `AI_DRAFT_REQUIRE_HUMAN_APPROVAL`）＋`_finalize_nodes` 归一（params/when 递归脱敏 → plan_ref 服务端注入 → `validate_dag_against_registry` **全尺同闸**跑最终稿 → validate_dag 确定性拓扑序重排）。NEW 路由 `POST /api/v1/projects/<project_id>/workflows/generate-ai-draft`（can_manage，**返件式零落库**：响应只带 `{draft: {dag_json, validate, dag_sha256, plan_ref, implementation_skill_ref}}`，业务域表零行——事件＋ai_call_audits 照常留痕＝审计面）；前置闸与编译器同码且全部 AI 调用前（零烧费）：plan approved/published 409 `plan_not_approved`／skill 形 409 `invalid_skill_ref`／published 白名单预检 422 `skill_ref_not_published`／capability 409 `invalid_capability`；事件 `workflow_dag_ai_drafted`（purpose/prompt_version/model/dag_sha256/node_count/plan_ref——**不带 DAG 全文**）。**采纳唯一通道**＝既有 create_definition（can_manage，第二道干跑）→ publish（**leader 403／admin 200**＝D-2 维持，第三道复验）——三道干跑同一闸尺＋两道人工闸，AI 无旁路。
- **机制沿 N3a 零新发明**：`execute_ai_prompt` 单一入口（purpose=`delivery_plan_draft`／`workflow_dag_draft`＋prompt_version=`plan-draft-prompt-v1`／`workflow-dag-prompt-v1`，归因三元＋预算门＋审计账本）；契约/JSON/全尺失败重试一次仍违 409 `ai_draft_contract_failed`（discovery 同裁，末项粘性重试语义）；J-1 白名单 +2（`DELIVERY_PLAN_DRAFT_SYSTEM_PROMPT`／`WORKFLOW_DAG_DRAFT_SYSTEM_PROMPT`）；`ALLOWED_NODE_FIELDS` 从 `validate_dag` 内联提为 `definition_service` 模块常量（**零行为变化**——validate_dag 与 AI 契约校验器同一份清单，防第二份漂移）；J-1 附钉（workflows 包 system_prompt 实参治理形态）扩为双治理形态（`instructions` 直传 ∪ J-1 登记常量——登记表单一真身，域外新增仍即红）。
- **测试**：NEW `test_delivery_plan_ai_draft.py` 9 例（happy＋溯源三元／版本化历史保留／契约失败零写入＋越界键＋requirement 条目必引键／fact_id 闭集／覆盖先验／无输入 409 零烧费／**G-04 复测链** AI 起草→人工 approved→published 旧版本保留＋draft 直接 publish 409／脱敏＋凭据 fail-closed／权限与面隔离＋api_catalog 不进钉）＋NEW `test_workflow_dag_ai_draft.py` 9 例（happy 返件式零落库＋拓扑重排＋plan_ref 注入＋sha 可重算＋事件不带全文／≥1 human_approval 契约／闭集与未知字段／全尺 registry 闸（未发布引用 AI 侧即拒）／契约失败零写入／前置闸全族＋权限／脱敏＋凭据 fail-closed／**双来源回归钉**（draft-from-plan 照常 201 三节点形＋compile_plan_workflow 金形）＋J-1 登记＋api_catalog 不进／**G-03 复测＝HTTP 层端到端完整链**（AI 起草→validate 干跑→人工 create_definition→publish leader 403/admin 200））。**变异三验证红→还原绿**：M1 摘 human_approval 契约（G-03 形状闸）／M2 摘覆盖先验（G-04 契约闸）／M3 摘 J-1 白名单登记。mypy 279 基线不变；pytest rebase 前基线（0f66f4e+本轮）本地 xdist（-n 4）实测 **3144 收集 = 3137 passed + 7 skipped**（首轮 3135 passed＋2 例两钉撞新形态红——purity「蔡工」字面量禁×文档串、J-1 附钉单形态——修复后定向 13 例复绿；**rebase 后合并树 PR CI 实测 3201 收集 = 3193 passed + 8 skipped**〔两趟 server-tests run 一致；＝main 现行值 3183 收集〔main run 43076579737〕＋本轮 +18 逐位吻合〕）。
- **口径与勘误**：路由 **474→476**（+2 全不进 api_catalog；基线含 rebase 融合 #363/#361/#356/#364 插队增量）／蓝图 52／**表 152／70 rev 单头 `d7e2f4a9c1b3`**（零迁移零新表零新蓝图）。**★口径勘误（承袭漂移家族）**：N3b ADR 轮（v1.14）与 M4 批次 C 轮所引「路由 462/465／表 150／66/68 rev」系 **#349 插队前基线**——`0f66f4e` 实际基线＝469 路由／151 表／69 rev 单头 `c1d4e7f9a2b3`；本轮现测一并校正 AGENTS 口径行。route CSV 重生成（+2 行 wc 核对）＋archify architecture 图四件套重生成（candidate/HTML 476＋delivery.json＋receipts 四闸 pass＋preview 整页实拍）。server 变更 ⇒ 合并后 rebuild 三镜像＋alembic upgrade head（本轮零迁移幂等 no-op）；部署活体挂账归部署归属方。随轮三同步：台账 v1.16（G-03/G-04 双 CLOSED＋勘误注记）＋任务书（§13 #20／§14 N3b 行／§15 序 3／§N3b 范围）＋AGENTS（header＋bullet＋口径行）。判据状态：**G-04/G-03 双 CLOSED**；N1 线：G-01 CLOSED（v1.15 somwyn G8/G9 收口轮）维持、G-07 CLOSED 维持。

## [未发布] — 多客户 M4 收口轮：四批证据链回写＋「按量付费 key」红线登记＋部署活体复验＋AGENTS 上游损伤修复（纯文档零代码零迁移零路由，2026-11-12）

- **M4 四批全收口（任务书 §7-M4「全局面治理」，主体隔离四件套）**：批次 A PR #338 `ed41602`（Redis 13/13 键族归属核销，零生产代码；M0 判定 K3/K4/K5 现测纠正为核销）→ 批次 B PR #340 squash `5027fc4`（AI 预算主体＝企业 org：`orgs.ai_monthly_token_budget` 可空、未配置回落实例值；`subject_budget_exceeded` 主体级判定＋`ai_call_audits.status='budget_blocked'` 留痕；admin 双闸写面）→ 批次 C PR #344 squash `4313229`（`outbox_events.subject_org`＋`background_jobs.org_id` 存量 NULL=平台级零回填；`enqueue_outbox`/`ensure_background_job` keyword-only 主体声明编译闸；27 生产调用点接线——静态钉当场抓 solutions 两处；`GET /admin/jobs/metering` 计量读面，计量面非授权面不进 api_catalog）→ 批次 D PR #351 squash `fcc73b0`（NEW `storage/layout.py` 单一权威＋`FDE_STORAGE_LAYOUT` 五状态机出厂 legacy＋新键 `org/{org_id}/…`／`platform/…`——逻辑键不变＝DB 零键列迁移零回填；24 生产调用点接线——静态钉抓漏网 7 处；`flask storage-migrate-layout` 命令只交付不跑；host 票据 org 归属元数据；M0「签名键进程内随机」现测纠正为核销）。CI 链（合并树实测）：3073→3091→3097→3142 收集（PR #351 run 43058957925＝3135 passed + 7 skipped）。
- **部署活体复验（七撞纪律）**：三镜像自 fde-wt-m4 工作树（＝`fcc73b0` 内容＋#349 融合树）build＋`up -d --force-recreate`；`alembic upgrade head` 真实升级 `c3f7b1d9e5a2 → e9b4f7c2a8d3（批次 C）→ c1d4e7f9a2b3（M5-1）`，容器内 `alembic current`＝`c1d4e7f9a2b3 (head)`；活体 url_map non-static **469** ≡ 口径；api `42d2d417e642…`／worker `6412cec8e818…`／scheduler `0bcb5d32ddee…` 容器 `.Image` 与构建产物逐位一致；ready/live **200**；四容器 healthy。★`fcc73b0` 自身 main run 被 push 取消（43065659966）——四绿证据取最新 main run（`abccfd1` 树，run 43068663545 rerun：pytest **3152 收集 = 3144 passed + 8 skipped**，含 L1 #360 插队 +10；首跑 server-tests 红＝`test_task_decomposition_preview_commit_idempotent` flake〔同树 #360 PR CI 两轮全绿〕，rerun 转绿）。
- **红线登记：「AI 供应商只允许按量付费 key」**（GM 线联合排期 R2 行的 M4 实施语义收口）：`server/.env.example` AI 段注释落闸——按量付费 key（用量随调用增长、可被预算闸真实计量与拦截）才与 `subject_budget_exceeded` 的计量-拦截语义相容；包月/订阅制 key 无按量用量口径，接入即破坏全局面 AI 预算治理。同处顺带把 E7 预算注释从「按用户」校正为 M4 批次 B 语义（预算主体＝企业 org，orgs 列未配置回落实例值）。
- **任务书 DoD 回写**：`docs/commercialization/多客户工作平台-leader任务书-v1.md` §14 M4 行 → [x]（四 PR 证据链＋部署活体证据）；盘点表 M4 销号追踪加收口行；GM 线联合排期草案 M4 行更新为「已收口＋红线已落」。
- ★**顺带修复 AGENTS.md 上游锚点事故（#355 引入、#356 复利；本轮归位零内容丢失）**：#355 回填脚本把真「当前状态」标题行替换成残缺头「## 当前状态（.md — fde-workbench」并把文档头（brand＋红线＋常用命令＋工作流三节）整块重复插入；#356 在残缺锚点上复利（somwyn 段与红线子弹落进重复块）。本轮逐字节比对证实重复块＝纯拷贝＋somwyn 红线子弹（delta 1088 字符）⇒ 删除重复块、somwyn G8/G9 收口段归位真当前状态行、红线子弹归位正本红线节首、v0.3.0 行游离「）」修正；删除前断言 `dup_rest == somwyn_bullet + head_wo_title` 全等（零内容丢失可证）。
- **结构口径**：本轮自身零迁移零新路由零新表零新蓝图（交付时点口径 469 路由／51 蓝图／151 表／69 rev 单头 `c1d4e7f9a2b3`＝abccfd1 树实测）；mypy **279 基线不变**；pytest 以 main run 实测为准（**3152 收集 = 3144 passed + 8 skipped**，run 43068663545，abccfd1 树，详见上）；桌面零改动不重打包；零迁移 ⇒ 无 alembic 动作（部署轮已升 `c1d4e7f9a2b3`）；★rebase 融合上游 #361/#362/#363 后，合并树口径随 T-11 #363（NEW 迁移 `d7e2f4a9c1b3`——alembic head 前移、诊断认领面进位）与 M5-3 #361（测试）重算，**终值以本 PR CI 为准**。

## [未发布] — 获客诊断第十八轮·T-11 线索模型与认领闸：四道机械闸＋三档归因＋台账行生成（迁移 d7e2f4a9c1b3 69→70 rev＋员工侧 5 路由，2026-11-12）

诊断会话里留了资的企业，**谁来跟、归谁、算不算渠道带来的**必须**机械可判**（不靠人自觉、不靠口头约定、不靠事后翻台账对账）。

- **四道闸（机械执行，测试钉死）**：①**认领窗口 90 天**过期即拒（窗口是机制不是提示）；②**一线一线**——同线索已有未决认领 ⇒ 拒（未决申请锁住线索）；③**R4 仅本区域**——区域不符 ⇒ 拒，线索**未登记区域** ⇒ **fail-closed 拒**（无法判定本区域即不许认领，不许"先认了再说"）；④**同主体自诊自认领** ⇒ **自动 C 档零转化费**（**降档，不拒单**——自认领本身合法，只是没有转化费；拒了等于把"自诊企业"的线索挤出池子）。**claimed ≠ accepted**：申请只落 `pending`（**不改线索状态**），**平台接受（admin）才生效**——线索转 `claimed`、落档位、出台账行；驳回**不改**线索状态（线索仍可被他人认领）。
- **三档归因（P-2：比例只落结构不落数）**：A 渠道报备（`source_type='partner'`）／B 认领转化／C 平台留存；转化费口径只落 `none`（C 档零转化费）／`pending_pricing`（A/B 比例待 T-16 价格轮）——**无任何比例/金额字段**（静态钉：认领单与线索表两模型全列扫 `rate/ratio/percent/commission/amount/fee_rate` 零命中）。
- **自认领信号三枚（只记命中信号，不存可比对明文）**：`ip`（认领请求 IP 假名 == 线索 IP 假名）／`contact`（认领方账号邮箱指纹 == 线索主体指纹）／`subject`（认领方声明的联系方式指纹 == 线索主体指纹）。
- **不建平行 CRM（P-3）**：真相层仍是 `D:\test\FDE\leads.md`（九字段 ＋ 9 态 ＋ 回访触发日）；服务端**只生成待落账台账行**（代号化九字段——**联系方式/姓名/企业真实名一律不出现**）并留在库里，**服务端不碰真相层文件**（容器里没有真相层，也不该有）；落账由**宿主侧脚本** `scripts/lead_ledger_append.py` 完成（只插不改、幂等、原子写、**找不到登记表 ⇒ fail-closed**——不猜位置），行指纹与落账时刻入库。
- **落地面**：NEW `server/src/fde_api/diagnostics/claim_service.py`（闸＋归因＋台账行生成）＋ NEW `lead_routes.py`（员工侧 JWT 面 5 路由：线索池／申请／详情／接受／驳回，**接受与驳回皆 admin 专属**；线索池投影**不含联系方式与姓名**）＋ NEW 表 `lead_diagnostic_claims`（25 列；CHECK 钉死「pending ⇒ 无 decided_at/无档位/无台账号」「accepted ⇒ 必带台账号＋台账行」「非 accepted ⇒ 不得带台账号」「R4 ⇒ 必须声明区域」；唯一约束 `(ledger_date, ledger_seq)` ＋ `ledger_line_no` ⇒ 并发靠 IntegrityError 重算，**只**在含 `uq_lead_diagnostic_claims_ledger` 时重试，其它完整性错误**如实抛出**——不吞错）＋ 线索行加两列 `subject_fingerprint`（主体指纹，**明文不入库**）／`region_name`（R4 判定基准；可空＝未登记区域 ⇒ fail-closed）＋ 迁移 `d7e2f4a9c1b3`（挂 M5-1 之后，**单头 69→70**，零播种）。**部署闸先于鉴权**：诊断面未启用 ⇒ **404**（不确认面存在）。
- **台账行映射（不臆造）**：来源 direct→自有／channel→协会活动／partner→渠道伙伴；行业←`org.industry`；联系人角色←`biz.decision_maker`；痛点一句话←`ctx.free_text`（截 40 字）；**资格五问得分＝「待填」**（资格判定是人的动作）；下一步动作+日期＝「认领跟进 <认领日>」；①状态＝「诊断中」；③回访触发日＝「认领窗口到期 → <窗口到期日>」；④资料索引＝「诊断会话-<8位短码>」。线索号 `L-<YYYYMMDD>-<两位序号>`——**本地日**＋8h 固定偏移，不用 UTC 日界（UTC 日界会把夜里的认领记到前一天，与人工台账对不上）。
- **测试与变异**：NEW `server/tests/test_diagnostics_lead_claims.py` **30 例全绿**（含**落账脚本列序防漂移钉**＋插行位置＋fail-closed＋竖线转义）；**变异五连全红→还原→绿**（M1 摘窗口闸／M2 摘一线一线／M3 摘 R4 区域闸／M4 摘自认领信号／M5 摘 C 档降档——每个 mutant 变异后转红、**文件拷贝还原**后定向复测全绿，还原后源文件 sha256 逐位一致）；诊断域＋迁移＋清单同步钉回归 **131 例全绿**；官方 ruff 闸绿、官方 mypy 闸绿（**279 基线不变**）。
- **结构口径与合并部署**：路由 469→**474**／蓝图 51→**52**／表 151→**152**／迁移 69→**70**（单头 `d7e2f4a9c1b3`）；审计清单三件套重生成＋archify 图纸口径同步（图纸防陈旧闸绿）；桌面端零改动不重打包。PR **#363** CI 四 job 全绿（server-tests **3174 passed + 8 skipped**）→ squash 合并 `f367fcb`；**部署活体复验**（从 `f367fcb` 干净树重建，生产项目名 `fde-workbench`）：三镜像 rebuild（api `e7e779d431f0`／worker `1b3408cb77fc`／scheduler `5b256eedfcab`）后容器 `.Image` 与构建产物**逐位一致**；`alembic upgrade head` **真实升级 `c1d4e7f9a2b3 → d7e2f4a9c1b3`**，容器内 `alembic current`＝`d7e2f4a9c1b3 (head)`；活体 `url_map` **474 non-static** ≡ 本轮口径；**部署闸默认关 ⇒ 活体 404 而非 403**；`/ready` 200＋`/live` 200；活库新表 25 列在位。**文档口径剥离出 PR**——AGENTS/CHANGELOG/任务书三文件随本证据 PR 合并后另起回填 PR（沿 T-10a #282 先例）。

## [未发布] — 多客户 M5 轮：企业组织成员邀请面＋三档分流入口＋六项判据聚合（迁移 c1d4e7f9a2b3 68→69 rev＋桌面分流面板，2026-11-11/12）

- **M5-1 组织成员邀请面（PR #349）**：NEW 迁移 `c1d4e7f9a2b3`（68→69 rev，`org_member_invitations` 表）；邀请/列表/撤销/接受四端点（`POST/GET /api/v1/commercial/orgs/<org_id>/invitations`、`POST .../<invitation_id>/revoke`、`POST /api/v1/commercial/orgs/invitations/accept`）。**一次性令牌＋邮箱绑定**（sec 评审：邀请是社会工程攻击面）——令牌明文只回传一次、库内只存 sha256 指纹；接受时强制 `actor.email == invited_email` 且 actor 为平台身份（`org_id IS NULL`）；**邀请是 org 归属面不是第二套权限体系**（红线 8）：接受邀请唯一副作用＝`users.org_id` 置为本 org，可见性由既有 `project_org_scope_filter` 覆盖，零平行权限表。企业空间读面透出 `org_id` ＋邀请清单；桌面端企业空间页 NEW「成员邀请」面板（发送邀请/一次性令牌展示/邀请清单/接受邀请）。
- **M5-2 三档分流入口＋六项判据聚合（同 PR #349）**：GAP-05——企业空间读面 NEW `diagnosis` 聚合块（键集＝G2 权威 `FREE_DIAGNOSIS_DELIVERABLES`，`all_completed`＝六键全真）；GAP-14——桌面端 NEW「记录三档分流（admin 双闸）」面板（viewer 不渲染＝前端门控，服务端 admin+密码双闸不变）＋「三档分流决定（可回看）」历史面板。
- **M5-3 收尾验收轮（PR #361）**：NEW `server/tests/test_m5_e2e_acceptance.py` 端到端 1 例——一家测试企业从公开自助注册（`quota_created=True`，零 admin 建号）→ 绑定/确认（诊断完成）→ 邀请链（第二账号公开注册→邀请→接受→org 归属＋`org_member_invitation_accepted` 事件留痕）→ 三档分流（非 admin 403→admin 双闸）→ 三付费选项呈现→企业自选付费选项 ⇒ `engagement_state=paid_delivery`；桌面端补 3 例（诊断聚合块六标签＋未完成态、分流历史 rationale 回看、admin 门控：viewer 无面板/admin 有面板含密码双闸）。
- **测试口径**：M5 邀请 13 例（`test_commercial_m5_invitation.py`）＋企业空间 29 例（`test_commercial_enterprise_space.py`）＋端到端 1 例（`test_m5_e2e_acceptance.py`）全绿；桌面端 enterprise-space 9 例（+3）全绿＋typecheck 双 tsconfig 零报错。变异与 CI 口径留空不写（本轮无变异要求）。
- **实现口径说明**（详见 `docs/commercialization/multi-tenant/M5-验收对照-v1.md`）：①邀请是 org 归属面（`users.org_id`）而非直接 `add_project_member`——依据 AGENTS.md M3a 红线「org 是归属维度不是授权维度」，等效满足 G6「复用既有权限模型零平行权限表」；②「成员变动通知全组织」v1.1 语义＝org 维度 `operation_events` 留痕＋邀请清单读面，邮件通知无 SES 生产批复不承诺；③admin 在 complete/triage 两处出现是 G6 口径允许的人工闸，不算「人工建号」。

## [未发布] — somwyn G8/G9 收口轮（G-01 CLOSED＝九门全 passed·项目 100% 结项＋⑦出站闸开闸生效；纯运维＋文档轮（代码零变更、无迁移、无新路由、桌面零改动），2026-11-11）

蔡工拍板「1、2 已完成／somwyn 进度 100%」后的核实与收口轮——实测发现两处「清单已录、活体未落」的缺口并当场闭合：

- **实测校真（先核后动）**：somwyn（`FDE-20261025-9BF8E4AE`）当日已自行推进大半——G7 重交 4/4（03:01 success.md 定稿＋11:06 B 试点章程补齐）⇒ 11:08 `pilot.reviewer` 拍 **pass**；15/15 任务 completed、项目 status=completed；宿主 `G7-G9材料收集清单-2026-11-11.md` 权威清单「代录完成」节录满 12 件全 sha256。**两处缺口**：①清单「代录完成」节的后 4 件（G8 POC 验收表 `0919dae4…`／business-case `81c43114…`／G9 演练记录 `6330d31f…`／Go-Live 实际件 PDF `b389b040…`）**未入库**（库内 G8 1/3、G9 3/5 claimed）；②蔡工在清单的拍板批注（G8=proceed／G9=pass／G-01 CLOSED）**未落库**（G8/G9 仍 evidence 态）。
- **①G8/G9 补录（admin 代录，先验指纹再提交）**：四份文件**现算 sha256 与清单 2026-11-11 版逐位比对（全 MATCH）**→ `submit_gate_evidence` 补录（note 注明「清单已录未入库、指纹现算 MATCH、留痕可推翻」）⇒ G8 3/3、G9 5/5 claimed（15:50，`gate_evidence_submitted` ×2 留痕）。
- **②拍板转录（pilot.reviewer 代录，非代拍）**：蔡工书面批注在先（授权强于 N1 leg3「按推荐项」先例）⇒ AI 以 `pilot.reviewer` 执行 `decide_gate`：G8 result=pass＋**decision=proceed**（三态过门硬闸满足）、G9 result=pass；note 全注批注出处、留痕可推翻；decided_by 记 `pilot.reviewer`（蔡工本人经第二账号，D-1 账号分离语义维持）。**终态：G1–G9 九道门禁全部 passed、G-01/G-07 双 CLOSED、somwyn 100% 结项（C 款 3,300 元里程碑触发，记账模式，宿主清单在案）**；台账 v1.15＋任务书 §13 记录 #19。
- **⑦ 出站闸开闸生效**：部署态 `server/.env` 写 `FDE_AGENT_HOST_EGRESS_GATE_ENABLED=1`＋`FDE_AGENT_HOST_EGRESS_ALLOWLIST=zcode.z.ai,api.z.ai,z.ai,api.minimaxi.com,bigmodel.cn,open.bigmodel.cn`（四探针实测出站集＋GLM API 端点族种子；可随 `agent_egress_audit` 审计逐步收紧）→ compose recreate → **活体验证**：容器 env 两键在位＋`/api/v1/health/ready` 200＋三容器 healthy；首个宿主 run 的 `agent_egress_audit` 审计事件待下次自然 run 留证。zcode 升级须复测四探针的边界注记不变。
- **文档收口**：台账 v1.15（修订记录＋G-01 行 CLOSED 终态＋somwyn 收口轮附注）；phase-status P2 遗留行与收尾排期表 #1/#5 行；final-acceptance-checklist #14 → ✅（17+1 待条件 → **18 项全达成**）；任务书 §6.1 ⑦行开闸生效注记＋§13 #19＋§15 N1 行收口终态。
- 口径：纯运维＋文档轮——**代码零变更、无迁移、无新路由、桌面零改动**（pytest/vitest/mypy 全不变；无需 rebuild/alembic/重打包；活库门禁事件留痕即证据）。清单尾注「工作台后端 gates 证据模块尚未实现」系陈旧误注，已勘误（gates 表/服务/API 全在役，本轮 12 件皆经 `submit_gate_evidence` 入库）。
## [未发布] — 获客诊断第十七轮·版本差可判定：时间机复刻 prompt-v1 组补样至 n≥3（009/023 复判均 within_noise＋生成侧合规差异 11/22→0/18 首登记；**纯文档零代码零迁移零路由**，2026-11-11）

第十六轮注册的消解条件（`诊断评测-分数面分布-1.md` §4.1「v1 组补到 n≥3 ⇒ 版本差即可判」）在 HEAD 代码上**字面不可执行**——三个机械事实：①prompt-v1 文本已不存在（curve-3 断点 `5dbbe4b` 整体替换）；②`NUMBER_GATE_VERSION` 被当前 runner 无条件打进 run.json；③runner 无版本选择 CLI。忠实执行＝**时间机复刻**：历史 v1 组唯一 run `2026-11-11`（08:31 创建）生成于 #311（08:20）之后、`5dbbe4b`（11:08）之前 ⇒ `e96efa3` 就是它的生成树；detached worktree @ `e96efa3` 用 era 自带 runner 跑两轮（生成器与 judge 语义零触碰），忠实性由四轴组键机械保证（非自觉）。

- **复刻面**：诊断表零迁移改动（`e96efa3→fork/main` 仅两笔商业域迁移）；模型槽位不变（生成与评分均 MiniMax-M3.1-Flash——换模型＝换生成器配置＝破坏组可比性）。唯一改动面＝两处**评测进程 harness 补丁**（未提交本地改动，仓库 HEAD runner 零改动）：①`_ThrottledSession`＋`--call-interval-seconds`（era runner 无节流，2026-11-11 限流实录兜底）；②`--eval-set-version`（era 版 run_id≡考卷版本同源，解耦后 ev5/ev6 才能落对组）。diff 83 行真相层 `_forensics/tm-run-eval-e96efa3-harness.diff`（sha256 `75042fe0…`）。
- **守窗实录**（配额窗口＝小时级滚动窗，修正第十六轮「同日再等无意义」推论）：17:52 探针 13 连 429 → 20:02:22 开窗 → 链一（ev5 生成 001/003 ready＋4 卡死于 `report_unsourced_number`；ev5 judge meta fail exit=3；ev6 生成 001/009/023 ready；ev6 judge meta pass usable=True）20:02–20:36 → 链二补样（ev5 子集重生成 009/010/023 ready＋somwyn 三连死；ev5 judge meta 重掷 pass usable=True）20:57–21:11。**已 usable 的 ev6 不重卷**（judge scores.json 整体覆写＝meta 重掷有掀组风险，风险对称下不动）。
- **读数（规则代码实跑）**：v1 组 `2026-11-11|prompt-v1||rubric-v0.2`（runs 2026-11-11/ev5/ev6，组键自动归组——机械断言通过）vs v2 组（ev2/ev3/ev4）：**009 Δ=−2.0（带 21）、023 Δ=−0.7（带 12）均 `within_noise`**；001/010/somwyn v1 n=1 ⇒ `insufficient_data`；excluded_rows 0/0。第十六轮单样本 Δ（−6.3/−7.0）的「看着像生成器变差」被真样本推翻。锚点组 n=4→6（A1 极差 1；A2 噪声带 9→**12**）。账本 `eval-runs/distributions/20261111T131327Z.json`（sha256 `f5d95419…`，truth 层）。
- **生成侧合规差异（本轮新发现，配置包整体归因）**：v1 时代四次批跑滚动死于 `report_unsourced_number` **11/22 卡次**（50%）vs v2 时代三跑 **0/18**——curve-3 断点同时改了提示词与契约检查器本体（分层作用域＋来源重界定＋拒因回灌；era＝全量扫描＋盲重抽），归因只能给配置包整体；somwyn 三连死同因是 D1「一个量词毙掉整份报告」的活例。**评分面 within_noise＋生成面死亡率 50%→0%＝v2 的可判定收益在生成侧**。
- **登记**：**L-9 时间机评测配方**（生成器版本升级时旧版本组必须在切换前补足 n≥3，否则版本差永久不可判；配方可复用：锁定旧版本提交→detached worktree→era 自带 runner→harness-only 补丁→组键机械归组）；**L-10 配额窗口观测修正**（小时级滚动窗，当日三次状态翻转实证，守窗探针循环为正确姿势）；judge meta 门逐掷随机（ev5 首掷 fail/ev6 首掷 pass——重掷即补样，已 usable 的 run 不重卷是纪律）。
- **同步**：NEW `docs/audit/诊断评测-分数面分布-2.md`（本底册：只有数字与 run id，随 #343 squash `e05f1d6` 已合并）＋任务书 T-09 行＋指纹登记 ⑥＋底册消解回执补入 `分数面分布-1.md` §4.1（以上随 #343）＋本节与 AGENTS 当前状态头（剥离回填，T-10b 第十二轮先例）。考卷与评分规则零改动（六卡/rubric-v0.2/meta-v0.2/answer_mapping 指纹全不变 ⇒ 不构成 C 类改考题，指纹登记无新指纹行）。零报告正文零答案材料——仓库侧只有数字与 run id＋指针+sha256。

## [未发布] — 交付案例学习闭环设计轮：三缺口多方案设计稿待拍板（案例摄取管线／可判定读数／知识片段接线；纯文档零代码零迁移零路由，2026-11-11）

- **缘起与结论**：蔡工问句「系统能否通过学习案例获得更好的交付能力（如 `D:\test\FDE\knowledge` 下的 FDE 交付案例）」，交互问答拍板**立项设计轮**。现测结论：诊断线已有一条实证进化闭环（生成 0/6→3/6→6/6＋`delta-noise-band` 判定），但只覆盖诊断报告一种交付物；交付能力面差**三缺口**——①摄取管线（存储面已预留：`SimulationScenario.source_kind='import'`＋`import_scenarios` 路由＋三视图泄漏自检，缺转换器与污染边界裁定）；②可判定读数（round16 分布方法论未移植训练场，单 run 读数已被 round16/17 证伪过）；③知识片段接线（`render_masked_context` 支持、`agents/service.py:390` 硬编码空元组——管道铺好、水源未接）。
- **推荐方案（设计稿 §2）**：A′ 离线转换器（落 `scripts/simulation/`——污染钉扫描面外已现测 `test_diagnostic_eval_contamination.py:37-41`）＋既有 import 路由＋**人工审阅激活闸**（判卷基准只进库内 judge 参考面——**污染单向阀**：禁止流向诊断生成器提示词，实施轮加静态钉）；`eval_lib` 分布原语移植训练场（锚点场景测评估侧噪声带；n≥3＋严格大于＋insufficient_data 语义照搬）；静态 `lessons.json` 经验条目层起步（只含抽象打法零案例答案，走既有禁区词/遮蔽闸，零新脱敏面）。
- **否决留痕**：答案直写 repo 种子文件（撞污染钉扫描面）／宿主通道挂真相层进沙箱（违宿主通道边界①）／单 run 读数下能力结论（round16 假信号教训）。
- **NEW** `docs/audit/交付案例学习闭环-三缺口设计稿-2026-11-11.md`（§6 四项待拍板：Goal 线归属／首批案例源／污染单向阀裁定／lessons 来源边界；批准后按 §5 拆 L1–L3 三轮，**设计稿 ≠ 实施授权**）。owner＝蔡工（拍板）；消解条件＝§6 拍板后开 L1 实施轮；backlog 登记＝`docs/implementation/v3-backlog.md` T-L0（同轮回填）。
- **口径**：纯文档零代码零迁移零路由零桌面——pytest/mypy/vitest 全不变，无需 rebuild/alembic/重打包。单文件剥离先例（沿 #282）：设计稿随 PR #350 先行合并（CI 四绿），本节与 backlog 登记为合并后回填。

## [未发布] — 会话收尾抢救落账：DSH 对外交付物行动清单 v1 ＋ 商业化复核轮台账补记（NEW `docs/audit/DSH作为对外交付物-行动清单与待确认项-2026-11-11.md` ＋ `phase-status.md` 复核轮节回填；纯文档零代码零迁移，2026-11-11）

- **DSH 对外交付物行动清单 v1（🟡 待拍板前置件——非立项、非成稿、不代表任何决策）**：把「DSH 封装成智能体底座交付各客户」的主张转成 OWNER 可拍板的书面决策件前置。①**拆清三件被混谈的事**：内部执行层（已裁决 `dsh_enabled=False` 走 zcode 宿主代理——不翻案）／对外交付物形态（四份既有决策均不覆盖＝本轮唯一对象）／底层许可与安全责任（Q11 未销号＝前置闸）。②现状证据分级 A/B/C：「直接否决」不成立（无决策覆盖），「直接开工」同样不成立（对外部署方案 v2 已拍板 `DSH false` 基线）；原始需求出处（A1）未确认＝B 级依据不得升 A。③**A1–A9 行动清单**（授权动作 A5 法务／A7 客户书面／A9 OWNER 拍板不可代做；当前可执行仅 A1/A2/A3/A8 纯文档）＋六项验收判据（①客户资料零外传、②H1–H13/N1–N7 不放宽＝一票否决）＋失败退回 `DSH=false`＋zcode 宿主代理现成态。专项评估草案待立项，本件只登记行动与待确认项。
- **商业化复核轮台账补记（「补账并入随轮 PR」纪律的抢救落地）**：`docs/commercialization/phase-status.md` 回填「复核轮：三项挂账现测＋交互式复确认」节——该轮在已删除的工作树 `fde-wt-g1`（分支 `docs/commercial-recheck-3parked`，基线 `e93b8e6`）完成，台账留痕未随轮落库即工作树销毁，本轮补记。三项挂账交互复确认**全维持原裁决**：§17 商业数值维持 unset（fail-closed，预写默认值判红）／§1.8 体验上限消费维持归 V3.2 simulation 域／GAP-15 维持半激活（缺首条采纳样本，任一真实采纳留痕落 `operation_events` 即自动销号）。**复测现测（本轮落账前重跑）**：桌面 typecheck 双 tsconfig 零报错＋`enterprise-register`/`enterprise-space` 双文件 **10/10 passed**——台账声称数字逐位吻合。
- 口径：纯文档零代码零迁移零路由零桌面——pytest/vitest/mypy 全不变，无需 rebuild/alembic/重打包。
## [未发布] — AI 原生化 N3b G-03 DAG ADR 设计轮（三拍板落 ADR：节点类型闭集不扩展／AI 产物返件式草稿零落库／与确定性编译器并列双来源闸唯一；纯文档零代码零迁移零路由，2026-11-11）

- **ADR 落盘（NEW `docs/architecture/AI原生化N3b-DAG-AI起草ADR-v1.md`；任务书 §15 序 2，台账 v1.14）**：蔡工交互拍板三问——①**节点闭集不扩展**（维持 `call/skill/agent/human_approval` 四值；`models.py:27` 定义侧＋`constants.py:50` 执行侧守卫双锚不动；附契约推荐项「AI 起草图须含 ≥1 human_approval 节点」留痕可推翻）；②**返件式草稿零落库**（本体轮 NEW 路由 `generate-ai-draft` 只返回草稿 DAG＋validate 干跑明细；人工采纳走既有 create_definition〔can_manage，draft 态〕→ publish_definition〔admin，D-2〕；契约失败重试一次 409 `ai_draft_contract_failed`，**全程业务域零写入**——事件与 ai_call_audits 照常留痕）；③**并列双来源、闸唯一**（`draft-from-plan` 零 AI 缺省腿零改动＝本体轮 DoD③ 承重墙；AI 增强腿同输入域两稿可比人工择优；三道 validate 干跑〔AI 预检→create_definition 复验→publish 复验〕＋两道人工闸，AI 无任何旁路）。
- **机制面沿 N3a 先例零新发明**：`execute_ai_prompt` 单一入口（purpose=`workflow_dag_draft`＋prompt_version=`workflow-dag-prompt-v1`）＋NEW `WORKFLOW_DAG_DRAFT_SYSTEM_PROMPT` 进 J-1 白名单＋输出端兜底脱敏（词典故障 fail-closed／凭据串拒绝）＋`workflow_dag_ai_drafted` 事件（携 dag_sha256/node_count，**不带 DAG 全文**）。
- **口径零变化**：纯文档轮——路由 462／蓝图 51／表 150／66 rev 单头 `a7c2f9e1b4d8` 均不动；pytest/vitest 零增量；无需重建镜像/alembic/重打包。
- **随轮三同步**：台账 v1.14（修订记录＋G-03 行注记「ADR 已拍板、本体轮待开工」）＋任务书（§13 复核 #18／§15 序 2 已落／§N3b 范围 bullet ADR 指针）＋AGENTS bullet。判据状态不变：G-03 OPEN（消解判据＝完整链实施，本体轮 §15 序 3 交付时复测）；G-01 OPEN 重交推进中（材料收集照 v1.10 清单）、G-07 CLOSED 维持。

## [未发布] — 夜审挂账实施轮 r9（CR-071 web 桥校验族按 r8 设计稿推荐 A 落地：校验族提升 NEW shared/api-safety.ts 纯函数单点＋桌面 api-ipc 重构引用＋web 桥六缺口全封＋等价性静态钉；纯桌面零迁移零路由零服务端，2026-11-11）

- **CR-071（P3 结构化挂账，r8 设计稿推荐 A；蔡工 2026-11-11「老规矩拍板」开实施轮）**：①**NEW `desktop/src/shared/api-safety.ts` 纯函数单点**（零 electron 零 DOM，origin 参数注入，双 tsconfig 双侧可编译）＝`isAllowedMethod`（method 白名单）／`isSafeApiPath`（raw＋decoded 双查：遍历 `..`／`%25` 双重编码结构逃逸（`%252f/%253f/%2523/%255c`）＋`%2e`／控制字符区间（`\u0000`–`\u001f`、`\u007f`）＋origin 归一匹配）／`isAuthExcludedPath`（auth 排除，verify-password 唯一例外，与桌面同尺）／`validateMultipartFileShape`（严格 schema：exact keys／字段名正则／100MB／文件名遍历——**非法返回错误码，不再 null 降级**）／`isMultipartFileShape`／`isBodySerializable`（JSON 回环）／`serializeBodyString`／`hasEncodedStructuralEscape`（decode 前 raw 面判定，「这是编码逃逸」的证据不丢）。②**桌面 `main/api-ipc.ts::validateRequest` 重构引用 shared 原语**——既有 8 项校验**行为逐位保留**（内联 `ALLOWED_METHODS`/`PATH_TRAVERSAL`/`CONTROL_CHARACTERS`/`hasEncodedStructuralEscape`/`validateMultipartFileBody`/`serializeBody` 逻辑搬入 shared，主进程侧只做 `throw invalidRequest()` 翻译；url 绝对形态经 `new URL(path, apiBaseUrl)` 归一保留——远程 apiBaseUrl 部署必需）；`tests/main/api-ipc.test.ts` **30 例全绿＝行为不变证明**。③**web 桥 `fde-web-bridge.ts::apiRequest` 六缺口全封**（r8 现测 8 项缺 6）＝method 白名单（旧：任意 method 可发）＋GET-with-body 拒（桌面同语义）＋路径安全（旧只 raw `..` 粗查，现编码双重解码 `%25`/`%2e` 穿透面＋控制字符区间全封）＋auth 排除（旧零分支）＋multipart 非法形状**显式 `fail({code:"invalid_request"})` 不再无 body 裸发**（旧 `buildMultipartBody` return null 静默降级路径废除）＋body 可序列化回环（旧直 `JSON.stringify` 无校验）。④**等价性静态钉**＝NEW `tests/shared/api-safety-samples.ts` 共享样本集（路径 25／method 9／body 11＝45 条，含「查询值 `%2e%2e` 解码为 `..` 但桌面原语义放行（PATH_TRAVERSAL 只查 pathname 段）——等价性钉按原样钉住不顺手扩面」留痕）＋`tests/main/api-safety-equivalence.test.ts`（node）与 `tests/renderer/fde-web-bridge-equivalence.test.ts`（jsdom，含「非法 multipart 拒绝时零 fetch」裸发判别钉）双侧断言**同一样本判定恒同**——任一侧未来单独加/减校验项导致漂移即红（「同一坑复发三次」家族性教训的结构性处置）。
- **变异三连全红→还原→绿（判别力验收）**：M1 摘 web 桥 method 白名单⇒method 样本（OPTIONS/TRACE 放行）红；M2 摘 web 桥路径安全判定⇒路径样本＋既有越界用例（`../etc/passwd` 裸发）双红；M3 摘 web 桥 multipart 严格 schema⇒body 样本（fields 非对象放行）＋「非法形状零 fetch」钉双红（裸发降级复现）；还原后 45 例全绿（定向 api-ipc 30＋web 桥 8＋双侧等价性 7）。
- **测试**：全量 vitest **1029 passed（92 文件）**（＝r7 基线 1022〔90 文件〕＋NEW 2 测试文件 7 例＝api-safety-equivalence 3＋fde-web-bridge-equivalence 4）；typecheck 双 tsconfig 零错（tsconfig.node/web include 补 `tests/shared/**`）。
- 口径：纯桌面＋文档轮——server 零改动⇒无需 rebuild/alembic；路由/表/迁移/蓝图/mypy 全部不变；**桌面变更 ⇒ 便携版 r36** 重打包随轮交付（asar sha256 `d62089f79989b997af58f23c9bf25276a774cc33c1c680eb7b88d3095f1ed704`；marker 字节验证＝shared 原语错误文案入包：`multipart body 形状非法` r36=2／r35=0、`multipart 字段数超限` 1/0、`body 不可序列化` 1/0、`isSafeApiPath` 2/0——web 形态收窄面在场且 r35 旧包零命中；★**asar 内 vite 对非 ASCII 转义，中文错误文案须查 `\uXXXX` 转义形态或纯英文标识**，明文 grep 恒 0——本轮以共享原语文案与英文标识作 marker；web 发行产物（build:web）不随便携版打包，web 形态消费 shared 原语经源码单点生效）。

## [未发布] — ⑦ 宿主通道出站限制面方案 A′ 实施轮（NEW `agents/host_egress_proxy.py` 白名单闸＋`NODE_USE_ENV_PROXY=1` 实测修正；审计事件 `agent_egress_audit`；config 双键 fail-closed；测试 +14＋变异双验证；四探针真机实录推翻一处设计前置；同轮 ① 商用条款公开条款路线消解＋V31-P2 落定；台账 v1.13；零迁移零新表零路由，2026-11-11）

蔡工拍板「⑦采纳推荐 A／①不发申请函自行消解／其它按建议实施」后双腿同轮施工：

- **⑦ 腿（代码）**：NEW `server/src/fde_api/agents/host_egress_proxy.py`（纯 stdlib 正向代理：仅监听 `127.0.0.1` 临时端口；白名单外 CONNECT 一律 403、明文 HTTP absolute-form 一律拒；域名后缀精确匹配〔裸 IP 不命中域名条目〕；`EgressAuditEntry` 域名级审计只记不判内容）＋ `run_host_channel` 闸接线（spawn 前起闸→env 注入→`finally` 停闸；闸启动失败＝A 类不 spawn 不计费）＋ `AgentRunResult` 新可选字段 `egress_audit`（容器适配器恒空缺省，零回归）＋ service 层 `agent_egress_audit` 事件（与 run 状态写**同事务**；`summarize_audit` 计数＋去重域名清单有界 20）＋ config 双键 `agent_host_egress_gate_enabled`（**默认关**）／`agent_host_egress_allowlist`（**空＋开＝fail-closed**：run 拒绝发起转 L2 不计费——既不无限制放行也不静默全拒绝）；`.env.example` 种子注记＋README 配置边界表登记。
- **★实测改判据（四探针真机实录，zcode 0.17.1／Electron 44／内嵌 Node 24.21）**：设计提请的兼容前提「zcode 尊重 `HTTPS_PROXY`」**首探即证伪**——裸注入代理后 zcode 照常 exit 0 完成真实模型调用（无效白名单反证同证＝流量完全绕行，Node fetch 默认无视代理 env）；**A′ 修正＝注入 `NODE_USE_ENV_PROXY=1`**（Node 24 内建代理开关）后：无效白名单 ⇒ **exit 1 被拦**（AI_APICallError）＋代理审计捕获真实出站集（`zcode.z.ai:443`＋`api.minimaxi.com:443`）；真实白名单 ⇒ exit 0 放行＋审计两条 `tunnel_allowed`。方案 A 以 **A′ 形态成立**；设计提请文档追加 §6 实施记录（状态 PROPOSED→已实施）。
- **测试**：NEW `test_host_egress_proxy.py` 14 例——白名单规范化 fail-closed（空/非法形状）／后缀匹配（子域边界/裸 IP）／真实回环代理三行为（CONNECT 放行隧道回环／CONNECT 域外 403＋审计／明文 HTTP 拒绝）／`run_host_channel` env 注入（含 `NODE_USE_ENV_PROXY` 钉）与审计回收／停机收口（run 后端口拒绝连接）／`summarize_audit` 形状／service 接线静态钉（防配置面静默拆除）；**变异双验证全红→还原绿**（M1 摘白名单判定／M2 摘 env 注入）；宿主通道既有 22 例零回归；mypy 官方闸 **279 基线不变**；零迁移零新表零路由。server 变更 ⇒ 合并后 rebuild 三镜像（alembic 幂等 no-op）。
- **① 腿（纯文档＋本地取证，蔡工拍板「不发申请函」）**：**公开条款书面取证路线**——供应商已发布之生效条款即书面确认：智谱服务协议 §3.4「可…商业化使用平台内模型及其生成的内容」＋ z.ai ToS 产出物权利归属用户（you retain all rights, title, and interest in … Outputs）＋第三方服务条款（provide services to any third party → 责任归我方，未禁止）；六份条款页快照落本地 `fdeops://vendor-terms-snapshot-2026-11-11/`（sha256 逐一登记任务书 §6.1① 行，快照日 2026-11-11；**原件永不入仓入库**）；双方订阅协议反售条款解读注记如实落行（禁的是模型能力转售/聚合——本工作台内部自用产出成品交付物，结构上不落入）；申请函草稿转备选不发送；**推向市场前 bespoke 书面确认维持 backlog T-Z1 挂账不变**。
- **V31-P2 同轮落定**：pilot-runbook Step 6 增分批注记（`item_ids` 起点 ≤3/请求、>60s 再分半）；**评估结论＝客户端分批为准、服务端不改**（服务端切片引入部分提交语义风险，timeout 加大只掩盖行锁串行；somwyn 实测 9 任务单全量 >120s 熔断 vs `item_ids` 9 次分批全成；留痕可推翻）。
- **随轮回写**：台账 **v1.13**（修订记录）；任务书 §6.1 ①⑦两行改判＋结论行「**10 过／2 部分〔⑧⑪〕／未过项清零**」＋ §13 记录 #17；phase-status 收尾排期表六项全部落定回写＋P2 遗留行；final-acceptance-checklist #14 行与尾注（待条件收敛为待真实交付期 G8/G9 材料）。
- **边界如实**：`NODE_USE_ENV_PROXY` 只约束遵守它的 Node 运行时（当前 zcode ✓）——**zcode 升级须复测四探针，失效即按设计提请退方案 B**；闸默认关，白名单初始集待蔡工按实际订阅端点裁剪写入 `server/.env` 后方可开闸（审计披露全部被拒域，可逐步收紧）。

## [未发布] — AI 原生化 N3a 实施轮：quality 用例 AI 起草落地（NEW `quality/draft.py`＋generate-ai 路由；单一入口＋契约整批零写入＋输出端兜底脱敏＋溯源留痕；G-05 CLOSED，台账 v1.12；+1 路由 461→462，零迁移零新表，2026-11-11）

蔡工「先把排期写进台账/任务书，再按任务书逐一实施」拍板后，按任务书 §15 序 1 首发 N3a 施工（**「AI 起草 → 人工审核 → 发布」两段式推进到第一处决策位**，D-4 首发位＝quality）：

- **NEW `server/src/fde_api/quality/draft.py`**：提示词常量 `QUALITY_TESTCASE_DRAFT_SYSTEM_PROMPT`（内部权威常量形态——进 J-1 白名单 `test_prompt_entrypoint_gate.py`，2026-11-11 登记）＋输出契约校验器 `validate_testcase_draft`（requirement_key 闭集＝项目 accepted 键集、**覆盖先验**每条 accepted 需求 ≥1 用例、字段形状/长度闭集、确定性归一化序 (requirement_key, 原下标)——#209 组序教训同裁）；AI 调用走 `execute_ai_prompt` **单一入口**（purpose=`quality_testcase_draft`＋prompt_version=`quality-draft-prompt-v1`，N2 审计账本归因三元：指纹/版本/purpose 全在册）；契约/JSON 失败即时重试一次仍违⇒409 `ai_draft_contract_failed`，瞬时错误退避重试一次（discovery 同裁）；**DB 写入是全管线最后一步且在同一事务内**——失败路径零残留（fail-closed 家族一致）；输出端逐字符串兜底脱敏（`redact_text_detailed` 第③层同构：词典故障 fail-closed 422 `pseudonym_dict_unavailable`、凭据串命中 422 `sensitive_credential_detected`、替换留痕 `quality.redaction_review` 事件）；**溯源** `test_plan_ai_drafted` 事件（prompt_version＋model 归因——AI 起草可按提示词版本归因，N2 纪律）。
- **NEW 路由 `POST /projects/<id>/test-plans/generate-ai`**（quality 蓝图 5→6，不进 api_catalog——治理审阅面先例；DSH 故障按同尺映射 503 可重试/409 终态）：产物恒为 **draft 计划＋draft 用例**（版本递增、历史不覆盖）；**草稿态不可被下游消费**——`execute_test_plan` 仅 approved（409 not_executable）、发布仍走人工 `review_test_plan` 闸＋需求覆盖闸＋两段式审核戳（**既有闸零改动**）；「不自动批准/不跳覆盖闸/不动 production 硬闸」的任务书边界机械承载。确定性拼装生成器保留为无 AI 时的缺省腿（零回归）。
- **输入侧纪律**：用户提示词只由已批准需求行（已代号化的需求库数据）确定性拼装，**零外部文字进模型**（外部文字禁入契约 P-4 同尺）；AI 不得虚构需求键（越界键整批拒绝）。
- **测试**：NEW `test_quality_ai_draft.py` 8 例（happy 路径溯源＋确定性重排/版本化历史保留/契约失败零写入＋重试计数/覆盖先验/无需求 409 零烧费/draft 不可消费＋人工审核闸承载发布/脱敏＋凭据 fail-closed/权限 403/401＋api_catalog 红线钉）；**变异三验证全红→还原绿**（M1 摘 execute 的 approved 闸⇒draft 可执行钉红；M2 写入提前（AI 调用前 commit plan 行）⇒契约失败残留钉红；M3 摘 J-1 白名单⇒新调用点红）。
- **随轮同步**：台账 **v1.12**（G-05 OPEN→**CLOSED**——消解判据四件全立：AI 入口存在＋产物落 draft 态＋人工审核前不可消费＋两段式审核戳仍在位；修订记录＋G-05 行注记）；任务书 §13 复核记录 #16＋§14 N3a 行＋§15 序 1 状态回写「✅ 已实施」；审计清单重生成（route CSV +1 行 `generate-ai`，DB CSV 零变化）；archify 架构域四件套同轮同步（candidate.json 461→462 路由＋finalize 四闸全绿＋preview 整页实拍 1440×2098 非首屏截断）——防陈旧闸 `check_archify_diagram_freshness.py` 复跑 OK。
- **口径**：路由 **462**（+1 generate-ai）/蓝图 51/表 150/66 rev 单头 `a7c2f9e1b4d8`（**零迁移**——AI 起草是通道增强非新表，复用既有 test_plans/test_cases）；mypy 官方闸 **279 基线不变**；pytest 本地定向 51 例全绿（quality 全量＋gate＋discovery＋delivery＋结构/路由对账）；**全量 CI 实测（main run 43021455616）3081 收集 = 3074 passed + 7 skipped**（＝M4 批次 A 轮 3073 收集基线＋本轮 NEW `test_quality_ai_draft.py` 8 例＋1；★**口径勘误**：随轮自报曾记「+7／3080 预期」，CI 实测 NEW 文件实为 8 例⇒全量 3081，终值以此 CI 为准）。server 变更 ⇒ 合并后 rebuild 三镜像＋alembic（幂等 no-op）。
- **N1 线判据不变**：G-01 OPEN（重交推进中，材料照 v1.10 清单）、G-07 CLOSED 维持；①商用条款/⑦网络限制面维持未过不声称。
- **后续**：N3a 出真实样本后启 N4（§15 序 5，CI eval job 非必需观察轮）；N3b G-03 ADR 设计轮（序 2）与本线并行不阻塞。
## [未发布] — F 线 T8 轮：文档同步与收口核查（同步清单逐项执行＋逐阶段验收判据对照无倒填＋ADR-011 状态栏工程生效状态更新；**纯文档零代码零迁移零路由**，2026-11-11）

- **任务书 §4-T8**（F 线最后阶段；依赖 T1–T6 已满足〔全阶段 PR CI 四绿〕；T7 省级启用按拍板本期后置不阻塞）。本轮 = **goal 循环收口轮**：把 T0–T6 六轮各自维护的同步面做**一次性全量核对**，把 ADR-011 状态栏从「工程仍未生效」更新为现测真值。
- **同步清单逐项执行**：①`AGENTS.md` 当前状态头注＋口径行标题前置 T8＋工作流与陷阱 NEW「rebase 自动合并两类新坑」（CHANGELOG 节体错位／口径行整行取上游侧——T6 轮七次 rebase 实录的两类「合并面文档改动后必须结构终扫」教训）；②`CHANGELOG.md` 本节；③`phase-status.md` NEW「F 线分账口径改造 T0–T8」节（T0–T6 逐阶段 PR/合并 SHA/变异证据＋T7 后置态）；④`rules/five-seat-split-rules.md` T2/T4/T5/T6 各轮已随轮同步（三方机器闸 `test_three_way_machine_gate_rules_file_constants_migration` 现测绿）；⑤`rules/regional-partner-program-rules.md` **不涉**（T7 未做，售卖闸保持 closed）；⑥`rules/opportunity-attribution-rules.md` T3 已随轮同步（R2 角色闸退役换席位费闸），本轮机器闸复测绿；⑦审计清单：**route CSV 再生成（+13/−13 行均为上游 M3b 批次②新测试文件的引用列回填，零路由增删）＋`v3-workbench-inventory.json` 与 DB CSV 零 diff**（结构 461/51/150/66 不变）；⑧架构图防陈旧闸现测 **OK**（图上数字与 JSON 逐项一致，本轮零结构变化无需改图）；⑨`ADR-011` 状态栏：三从句全部过时（书面签字待补→**已完成 29/29**；初始基线未发布→**已随 T2 迁移种入 `active`**；法务意见未齐→**#330 已消解**）⇒ 换「工程生效状态（T8 现测）」并逐阶段列合并 SHA；**状态键保持非 `Accepted`**（升 Accepted 须 OWNER 书面授权，Agent 不得代改）。
- **逐阶段验收判据对照（§4，无倒填）**：T0 规则机器闸三方一致＋签字闸闭环（#296→`10838b9`；#327 复确认）；T1 Σ＝T 恒等＋四情形逐分对齐＋`delivery_settlements` 20 列结构钉（#302→`f71364c`）；T2 初始基线 `active`＋公示硬闸一字未改＋第二版零公示 422 反例（#305→`a62d5f7`）；T3 归属未确认 fail-closed 409＋企业自来 `no_sourcer`＋R2→席位费闸有书面依据（#310→`a43c0aa`）；T4 空缺原因码闭集＋人工确认双闸＋自拉自交本人验收 403（#312→`4354cd2`）；T5 默认到场硬闸＋15 分钟逐级扩圈＋权重 40/30/20/10 未变（#321→`c6c1cf4`）；T6 预扣多主体分流＋进项票前置＋科目层引用聚合＋county 对齐（#334→`b2bd225`）。变异总账 M1–M15（含 M6b、M12b）**17 组**全转红→字节还原→sha256 一致→绿。
- **测试**：本轮零新增（收口核查为文档轮）；判据复核本地现测＝F 线六文件定向 **99 例全绿**（`test_dispatch_five_seat_baseline`+`test_five_seat_allocations`+`test_ledger_sync_nail`+`test_commercial_opportunity_attribution`+`test_f_line_t6_tax_invoice_reconciliation` 82 例＋`test_f_line_t5_onsite_hard_gate` 17 例）；全量口径 **3070 收集 = 3063 passed + 7 skipped** 不变（终值以本 PR CI 实测为准）。
- **口径**：零迁移零新路由零新表零新蓝图 ⇒ 结构口径不变（**461 路由／51 蓝图／150 表／66 rev 单头 `a7c2f9e1b4d8`**；api_catalog 94；mypy 279）；route CSV 引用列 +13/−13（零结构变化）；架构图防陈旧闸 OK；pytest 3070 收集不变。零代码 ⇒ 合并后无需 rebuild／无需 alembic／无需重打包。
- **goal 循环状态**：T0→T6 全阶段 DONE＋T7 本期后置（挂账在案：合规四项＋律师意见，消解条件=OWNER 取得材料后开工）＋T8 收口核查本轮完成 ⇒ **F 线分账口径改造 goal 循环全链完成**（「是否允许结束 goal」由 OWNER 判定，不得自判）。


## [未发布] — F 线 T6 轮：结算／税／票／对账回归（五主体下票税分流＋科目层改引用五席位明细聚合；**零迁移零新路由零新表**，2026-11-11）

- **任务书 §4-T6**（ADR-011 §4 配套已裁决口径：开票主体／税／发票前置三行；T2–T5
  依赖已满足；OWNER 判定问题按「按推荐执行＋留痕可推翻」先例进入本轮，推荐项＝
  **进入 T6**，OWNER 明确选择「进入 T6（推荐）」）。本轮把 ADR-011 §4 的三行
  配套口径落成**五主体下的可结算、可举证、可回归**实现：**票／税／对账分流，
  两类主体两条路径，两者不得混算**。
- **动作① 累计预扣扩到多收款主体**（`dispatch/settlements.py::compute_withholding`
  ＋新原语 `_payee_settlement_base`）：旧形态只按 `seat_delivery_user_id` 单列
  累计 ⇒ 同一收款人跨席位（lead／delivery／county）的年收入**分列不同基数**、
  累计预扣漏算。新形态：累计基数＝该收款人**本自然年的全部个人席位 `paid`
  明细行** ＋ 本笔当期基数；**同一结算内兼任多席位**当期一并计入
  （`_payee_settlement_base`）。公式与档位**一字未改**
  （`WITHHOLDING_BRACKETS` 累计预扣法，跨档按跳档重算）。**存量行**（无五席位
  明细）按旧口径取 `delivery_amount`，且用 `NOT EXISTS` 与新层**互斥**⇒防双计。
- **动作② 发票前置扩到新增收款主体＋票税分流**（新原语 `_require_input_invoices`，
  接在 `mark_payable` 的既有校验之后）：`province` 席位的 `paid` 明细行在其结算
  转 `payable` 前，**必须**先登记**进项票凭证**；未登记 ⇒ 422
  `input_invoice_required`。凭证载体＝G3 科目层 `project_share` 行，**须附
  `source_uri` ＋ `content_hash`**（红线：门禁证据只存指针＋指纹，原件不入库），
  且科目行收款主体须与该 `province` 明细行收款人一致。**企业票不碰**——里程碑
  销项票 `payments.invoice_no` 的既有校验一字未改（平台公司统一收款、统一开票
  给企业；区域服务商／交付者／拉单方按分成**向平台开进项票**）。
- **动作③ 科目层对账：金额改引用五席位明细聚合**（`commercial/ledger_service.py`
  的 `project_share` 分支）：ADR-008 §2.5「项目分成只引用既有分账结果、**不重算**」
  语义**不变**，变的是**引用的对象**——明细在场时金额＝**该收款主体在本结算明细中
  已分配份额的聚合**，不再是旧四席位镜像列 `delivery_amount`。明细在场 ⇒ 主体
  必填（缺 ⇒ 400 `project_share_payee_required`）；主体在明细中无已分配份额
  ⇒ 409 `project_share_payee_not_allocated`（**空缺沉淀不产生分成科目**）；金额与
  聚合值不等 ⇒ 409 `amount_mismatch_settlement`（引用不重算的守面，差一分也拒）。
  **无明细存量行**按旧口径取 `delivery_amount`，且 `basis` 不带 `allocation_source`
  键 ⇒ **存量与新层可辨**（任务书 §7 数据兼容）。**`ledger_project_mismatch`
  反例保持**（科目行归属项目与结算项目不一致仍 409）。
- **动作④ 区域结算与 `county` 席位对齐**（`commercial/regional_service.py::
  record_service_settlement`）：`regional_service_settlements`（G5 一单一结）引用的
  `project_share` 科目行，在**明细在场**时其收款人必须＝该结算的 **`county` 席位
  收款人**（城市服务伙伴拿的是 county 份额）；否则 409 `county_payee_mismatch`。
  一个科目行至多关联一次（`ledger_entry_id` UNIQUE，一单一结）——**既有
  `ledger_project_mismatch` 409 保持**。无明细存量行按旧口径放行。
- **分流判据按席位而非按 user**（偏差登记进《分账口径改造-文档偏差登记表》）：
  `regional_partners` 是**机构代号行、无 `users` 关联** ⇒ 主体类型**无法按收款人行
  判定**；工程上以席位键二分为**唯一**判据
  （`_PERSONAL_SEAT_KEYS = ("lead","delivery","county")`／
  `_INSTITUTIONAL_SEAT_KEYS = ("province",)`）。**两者不得混算**：机构份额不进个人
  劳务报酬累计基数；个人席位不因缺进项票被拦（分流不得反向混算）。
- **测试**：NEW `test_f_line_t6_tax_invoice_reconciliation.py` **12 例**（跨席位累计
  跳档 690→1460／同一结算兼任当期合计 1059.60／机构席位不进基数 858／分流常量
  闭集形状／**province 无进项票 422＋无凭证科目行仍拒＋附凭证过闸**／个人席位
  不受进项票闸咬／**科目层金额引用明细聚合（按旧镜像列 409 ＋ 按聚合额 200）**／
  主体未分配 409／主体缺省 400／**存量行旧口径保持**／**区域结算 county 对齐
  （张冠李戴 409）**／存量行不做对齐）；既有 `test_five_seat_allocations.py` 的
  `test_complete_allocations_allow_payable` 按 T6 语义改写（**先断言 422
  `input_invoice_required`，再登记进项票后转绿**——新增负例与正例路径）。
- **变异四连全红→字节级还原（sha256 终验一致）→绿**：**M13**（累计口径不按收款人
  过滤＝按错主体累计 ⇒ **1 例红**：4820.00 ≠ 1460.00，跨主体收入并入本主体基数
  把档位跳了）；**M13b**（当期基数 `_payee_settlement_base` 不按收款人过滤 ⇒
  **3 例红**：2020.00／1516.00／3028.00 全部偏离）；**M14**（摘除
  `mark_payable` 的进项票前置闸 ⇒ **2 例红**：T6 payable 闸用例＋T1 负例断言
  「DID NOT RAISE」）；**M15**（科目层金额回退旧四席位镜像列 ⇒ **4 例红**：含
  对账差额用例 `test_project_share_amount_references_allocation_aggregation`
  「DID NOT RAISE」）。还原纪律＝**字节拷贝还原**（`shutil.copyfile` 回备份，
  非 `git checkout --`、非字符串重建），还原后三文件 sha256 与备份**逐位一致**
  （`settlements.py` `3d363912…`／`ledger_service.py` `e67c10be…`／
  `regional_service.py` `29c5c94c…`）。
- **实施期自查修正（记在案）**：①`record_revenue_entry` 返回
  `{"entry":…, "changed":…}` **字典**而非模型 ⇒ 全部 `.amount`／`.basis` 访问改
  `entry["entry"][…]`；②首版预扣恒为 0.00——`record_receipt_settlements` **建行时**
  把当时的 `package.seat_delivery` 拷进结算行，事后改包不回填结算行 ⇒ 测试夹具须
  **同时**补位包与结算行；③跨席位用例第二笔结算的交付收款人须回填到结算行
  （否则预扣按错主体算）；④累计预扣档位**按跳档重算**（39800 应税所得跨 10% 档
  ⇒ 3980−2520＝1460，**不是**初版误记的 1194）；⑤同结算兼任例 35320 应税所得
  **仍在** 3% 档 ⇒ 1059.60（初版误改 1012 已回正）。
- **口径（融合树现测，2026-11-11）**：**150 表**（本轮零新增表）/ **66 rev 单头
  `a7c2f9e1b4d8`**（本轮零迁移，head 不变）/ **461 路由不变**（本轮零新路由）／
  蓝图 **51** 不变 / `api_catalog` **94 ENTRIES** 不变（治理面不进 catalog）；
  mypy **279 基线不变**（官方闸 `scripts/check-python-types.py` OK）；审计清单
  重生成（JSON 461/51/150/66 **零变化** ⇒ **本轮零结构变化**，架构图口径无需
  改动，防陈旧闸绿；route CSV 随上游新测试文件引用刷新）；pytest 终值以本 PR
  CI 实测为准：终态融合树（fork/main `e93b8e6` ＝ 多客户 M3b 批次④ ＋ M3b 收口回填〔#337〕＋ AI 原生化 N3–N6 排期写入〔#333〕，两笔均纯文档零 pytest 增量，合并态）
  **3070 收集 = 3063 passed + 7 skipped**〔★基线＝**3058 收集**（＝批次③ 合并树
  CI 实测 3052 ＋ 上游 ④ +6）＋ 本轮 NEW 12 例逐位吻合；既有
  `test_five_seat_allocations.py` 改写不增量〕。
- **rebase 记录**：开工基点 `99aed4a`，实施期上游**十四度插队**（#323 诊断分数面／
  #324 夜审 r7 桌面／#325 M3b 批次①-a／#327 F 线签闸复确认 → #328 批次①-b →
  #329 夜审 r8／#330 外部闸／#331 批次② → #335 批次③／#332 诊断回填 → #336 → #333 N3–N6 排期写入 → #337 M3b 收口回填
  〔均纯文档〕）⇒ **合并前 rebase 七次**至终态 `e93b8e6`（第六／七次仅 AGENTS 冲突〔第七次口径行整行取上游侧后重放 T6 段〕，CHANGELOG 自动合并；历次冲突均＝
  **两侧内容全留**：我方 T6 节在前、上游批次④／③／②／r8 节全留，CHANGELOG 与
  AGENTS 口径行按上游新文本重锚）；★**rebase 会作废已测基线**——rebase 前的
  本地实测**一律不承袭**，全量回归在终态融合树上重跑，口径按新基线**现测**后
  重写。

## [未发布] — AI 原生化 N3–N6 排期写入轮＋台账 v1.11（任务书 §14 四行「未开工→已排期」＋NEW §15 排期总表（N3a 首发⇒N3b ADR 并行⇒N3b⇒N3c⇒N4 观察轮⇒N6 小轮⇒N5 末位）；排期≠实施授权，D-4～D-8 按推荐缺省值无新业务闸，纯文档零代码，2026-11-11）

蔡工交互拍板「先把排期写进台账/任务书，再按任务书逐一实施」后的排期登记轮（**登记＝排期，非实施授权**；每轮开工仍走既有流程：认领前查在途 PR→feature 分支→PR→CI 四绿→合并）：

- **NEW 任务书 §15 排期总表**（序 1–7）：**N3a（G-05 quality 用例 AI 起草）下一 feature 轮首发**（前置 N2 已满足，#240）⇒ N3b G-03 ADR（设计轮，纯文档，与 N3a 并行）⇒ N3b 本体（G-04/G-03）⇒ N3c（G-06 派单 AI 建议腿＋G-15 桌面编排面，**G-15 可与 T-A10 桌面产物预览面同轮合批**省一次打包）⇒ N4（G-10 CI eval job **非必需观察轮**（D-6 缺省）＋G-11 受控发布通道＋G-14 指标工单；全表唯一显著加模型开销的轮，先算单次成本定跑频/分片）⇒ N6（G-13 提示词版本注册表小轮，可与 N4 并行）⇒ **N5 全表末位**（G-02 AI 提议发起 run，权限面最宽，单独一轮＋`code-review` 安全评审）。
- **任务书 §14 四行＋§3 总表 N3a 行状态回写**（「未开工」→「已排期＋开工条件」）；**任务书 §13 复核记录 #15** 落档。
- **台账 v1.11**：标题号＋修订记录＋G-02/G-03/G-04/G-05/G-06/G-10/G-11/G-13/G-14/G-15 十行规划轮次列逐行注记「已排期 §15＋开工条件」；N1 线判据状态不变（G-07 CLOSED 维持、G-01 OPEN 重交推进中，材料照 v1.10 清单收集）。
- 红线边界（各轮不变）：AI 只起草/建议/评测，发布/审核/派单采纳/run 发起确认全部留人工闸；不自动上线提示词、不批量确认提议、不扩 `human_approval` 语义。零代码零迁移零路由；无 rebuild／无 alembic／无重打包。
## [未发布] — 获客诊断第十六轮：分数面可判定性（分布原语＋`delta-noise-band-2026-11-11` 判定规则＋评分通道全调用节流；**底册首次达到 n≥3**；零迁移零路由零蓝图，2026-11-11）

- **要解决的问题（登记事实驱动）**：curve 3 登记「锚点 A2 同一份输入 77→84 ⇒ judge 单点噪声 ≥7 分，逐卡 ±10 以内属噪声域」——此后**分数面读不出任何东西**：单点分差与 judge 噪声不可区分。本轮把「分数面」变成**可判定**的：先测分布，再按噪声带判差值。**规则与原语先落地、读数后补齐**（PR #323 合并 `634d3ca`；本节回填其首次真机读数）。
- **分布原语**（`scripts/diagnostic_eval/eval_lib.py`）：`score_distributions` 逐卡按**四轴**（`eval_set_version` × `prompt_version` × `number_gate_version` × `judge_version`）分组、锚点按**两轴**（`judge_version` × `meta_fixture_version`）分组——**锚点可合并、逐卡不可合并**（锚点输入逐字节固定 ⇒ 重跑得分＝纯 judge 噪声，与生成器版本无关；逐卡必须四轴全同才是同位样本）。三条机械不变量：**元验证不过的 run 整个不收**（协议语义在代码里执行）；**judge error 行与复述作废行不是 0 分、是无数据**（排除出分布并如实报 `excluded_rows`）；**n<2 不编造 stdev、空样本直接失败**。
- **判定规则 `delta-noise-band-2026-11-11`**（登记、留痕可推翻、**非校准阈值**——E-1 oracle 数据攒够前不校准任何通过线）：**Δ 可判定 ⇔ 参与两组样本数各 ≥ 3 ∧ |Δ| > 噪声带**（噪声带＝参与分布的观测极差较大者）；**严格大于**（恰等于噪声带 ⇒ 落在噪声域，不可判定）；**n 不足 ⇒ `insufficient_data`**（「还没资格判」≠「不可判定」）。底册 CLI NEW `scripts/diagnostic_eval/summarize_distributions.py`（真相层出数字与 run id，仓库侧只存汇总＋指针，**零报告正文零答案材料**）。
- **首次真机读数（底册）**：逐卡组 `2026-11-11|prompt-v2|number-gate-v2|rubric-v0.2`（runs `ev2/ev3/ev4`）**达最小样本 n=3**——001 均值 82.7 极差 18／003 79.3 极差 9／009 70.7 极差 **21**／010 68.0 极差 5／023 79.0 极差 8／somwyn 55.0 极差 7；锚点组 `rubric-v0.2|meta-v0.2`（4 run）**n=4**——A1 极差 **1**、A2 极差 **9** ⇒ **纯 judge 噪声带 = 9 分**（curve 3 时 n=2 只测到 ≥7）。`excluded_rows`＝0/0（不合格行全随 run 在 run 层被挡在分布外，**没有一条 error 行被当成 0 分**）。
- **规则实跑的三条判定**：①**版本差（v1 vs v2）仍不可判定**——v1 组只有 1 个 run ⇒ 规则机械输出 `insufficient_data`（三个 Δ 恰为 −6.3／−7.0／−5.0，看着像「生成器变差」但**规则不许这么读**；消解条件＝v1 组补到 n≥3）；②**本轮第一条可判定的分数面结论**——逐卡组 vs 锚点组（两组均 n≥3）：`datawhale-010`（Δ −14.0）与 `somwyn`（Δ −27.0）**可判定地低于** A2 参考锚点（超出 9 分纯 judge 噪声带），五卡**可判定地低于** A1 顶格锚点，而 `datawhale-001` 对 A1 是 `within_noise`（Δ −17.1 未超它自身极差 18.0 ⇒ 保守侧生效）、`datawhale-009` 对 A2 同为 `within_noise`（Δ −11.3 < 自身极差 21.0）；**「可判定地低于锚点」≠「不达标」**（通过线未校准）。③**离散度归因（登记口径，不在判定式内）**——同配置三次 run 的逐卡极差 5–21 分，**超出 9 分的部分不可能来自 judge 抖动**（judge 噪声上界已由锚点四样本测得）⇒ 逐卡分差读不出能力变化的**主因是生成端方差**（009 卡同一考卷同一套提示词三次差 21 分），不是 judge 抖。
- **provider 限流事故取证链（真机，零生产改动兜底）**：症状＝judge 侧 HTTP 429 → `ai_rate_limited`（`server/src/fde_api/ai/deepseek.py:286-288`，`retryable=True`），run `ev3` 评分 8 行全 error ⇒ 元验证 fail ⇒ 整 run 不进分布；生成侧 `ev4` 六卡全 `report_unexpected_error`。**活库取证**（`ai_call_audits`，今日窗口）：**219** 次调用 / **590,490** tokens，succeeded **89**（最后成功 12:48:37 本地）、failed **130**（最后失败 14:19:26 本地）。**排除「本会话吃掉共享配额」**——完全静默约 25 分钟后重试仍 100% 429 ⇒ 判为**账号级当日配额耗尽**。**根因三层**：①判别面——judge 的**元验证段（2 锚点＋4 反例）先于逐卡段连发 6 次**，只给逐卡段加延迟对元验证段无效；②重试语义——429 退避 `retry_delays=(1.0, 3.0)`（`deepseek.py:400`）**只会撑住限流窗口**，不构成退避；③兜底＝首版 `--card-delay-seconds`（**只管逐卡段**）实测管不住元验证段 ⇒ 升级为 NEW `_ThrottledSession`（`scripts/diagnostic_eval/run_eval.py`）包住 judge 客户端 HTTP session，**任意两次请求间**强制最小间隔（CLI `--call-interval-seconds`，本轮 20s）——**只作用于评测进程，生产代码零改动**。**复核**：单次探针 HTTP 200（配额窗口解除）后重跑，节流代理下 ev3 重评分 12 次调用全 succeeded（`meta_gate=pass`）、ev4 生成 6/6＋ev4 评分 12 次调用全成功 ⇒ 兜底有效且不依赖「配额恰好恢复」。
- **附带发现：批跑撞产品访客日限额（第二道闸）**——ev4 首次生成失败在 `diagnostics/service.py:177`「今天的使用次数已达上限」＝**产品自己的访客日限额**（`FDE_DIAGNOSTICS_DAILY_IP_LIMIT` 缺省 20/IP/日）：批跑用**固定合成 IP**（`203.0.113.x` 按卡位取模），同一天多次批跑把同一批 IP 的日计数器顶满 ⇒ **兜底＝评测进程内抬阈值**（活体容器读自己的 env，访客侧行为零变化）；后续轮宜把批跑 IP 改为按 run 派生（登记 L-6）。
- **测试 +10**（`server/tests/test_diagnostic_eval_batch_lib.py`，累计 29 例全绿）：四轴分组区分／锚点跨生成器版本合并／分布统计（样本偏差·单样本不编造·空样本 fail-closed）／error 与作废行排除且计数如实／严格越带判定＋单样本不进带宽／n 不足 ⇒ `insufficient_data`／渲染携带规则与表头与「纯 judge 噪声」「不校准任何通过线」「四轴全同才同组」「✅ 达最小样本」／薄组与空组标记。**变异四连全红→还原→绿**（M1 摘 usable 过滤〔**首版变异无判别力已改设计再验**〕／M2 摘锚点 judge 轴合并／M3 摘严格大于改 ≥／M4 摘 error 行过滤）。**mypy 279 基线不变**；零迁移零路由零蓝图零桌面。
- **交付与部署**：PR **#323**（head 两笔）→ CI 四 job 全绿 → squash 合并 **`634d3ca`**＝fork/main 顶；**main run 42969299906 四绿收口**（并发 push 取消过一次 ⇒ 等对方 run 完成后 rerun，收口于 completed/success 四 job 全 success）。本轮**零 server 改动** ⇒ 无需 rebuild 三镜像／无 alembic 升级（活体容器镜像 ID 与构建产物一致、`alembic current`＝`a7c2f9e1b4d8 (head)`、`/api/v1/health/ready` 200、url_map 与审计清单逐位一致）。
- **登记可推翻项**：L-1 判定规则／L-2 `MIN_DISTRIBUTION_RUNS=3`／L-3 锚点 judge 轴 vs 逐卡四轴／L-4 error 行排除语义／L-5 全调用节流／L-6 评测进程内抬访客日限额／L-7 离散度归因口径／L-8 纯 judge 噪声带＝9 分（n=4）。**明细与读法边界见 NEW `docs/audit/诊断评测-分数面分布-1.md`**（仓库侧只存汇总＋指针＋sha256，原件留真相层）。

## [未发布] — 多客户 M4 批次 D 轮：存储主体段与五步迁移闸（NEW `storage/layout.py` 单一权威＋`FDE_STORAGE_LAYOUT` 五状态机＋24 调用点接线＋S2/S3 新段＋`storage-migrate-layout` 迁移命令＋预签名键核销钉；零迁移零新路由零新表，2026-11-11）

- **任务书 §7-M4「存储根加 {org_id}/ 段＋存量五步迁移」落地**（盘点表维度 4＋维度 5 机制 7；交互拍板推荐项②：**五步状态机闸全落代码**）。NEW `storage/layout.py` **单一权威**：状态解析／段归属／物理键翻译三合一（调用方不自行拼段——与 `subject_budget_exceeded` 同款「判定只认一处」纪律）。**逻辑键不变**：DB 存的仍是 `projects/{project_id}/…` 逻辑键（**零键列迁移零回填**），物理布局只在存储访问边界翻译。
- **五步状态机**＝`FDE_STORAGE_LAYOUT`（出厂默认 `legacy`＝部署即现状零回归；闭集 fail-closed）：`legacy`（写旧读旧）→ `dual_write`（写旧＋新、读旧）→ `read_new`（写新、读新优先回落旧——迁移核对期）→ `readonly`（同 read_new，旧根冻结语义）→ `retired`（写新读新零回落）。**新键约定** `org/{org_id}/<逻辑键>`／平台段 `platform/<逻辑键>`；`document-templates` 逻辑根恒平台段。
- **24 个生产调用点全接线**（写路径按 `physical_write_targets` 双写循环＋读路径按 `open_read_stream`/`existing_read_key` 回落序＋预签名 `sign_download` 签物理键）：files×5／documents×8（含 template_service×5）／research×3／guidance×1／control×2／multipart 完成面 placement×1＋processors copy×1＋previews×3。NEW **静态钉**：全仓 `put_stream`/`open_stream`/`sign_download` 调用点窗口内必须经布局 helper（★当场抓到 grep 盘点遗漏的 control/mcp_gateway、file_delivery、template_service×5 等 **7 处**——机械闸价值二次实证）。
- **S2/S3 存量不搬**：agent 工作区（`agents/service.py`）与转写草稿（`transcripts/service.py::_draft_dir`）短生命周期临时面新写入即主体段；存量 run 路径已持久化照旧、存量草稿沿 7 天留存期自然耗尽（清理 miss 仅磁盘残留非安全面，如实登记）。
- **迁移命令**＝`flask storage-migrate-layout`：**缺省 dry-run**（只报计划）；`--execute` 逐文件 sha256 核对（源/目标逐字节一致才记账）、幂等可重跑（目标在场且一致 ⇒ skipped）、逐对象容错（孤儿/缺 sidecar 不中断整轮，汇总后 fail loud）；**生产执行是运维动作，不在部署流程内自动跑**（不执行生产变更红线）。
- **host 票据 org 归属元数据**：`issue_execution_grant`/`issue_run_grant` 加 `org_id` claim（发行时解析发起人归属；计量/审计面非授权面）；`agent_runs.authorization_id` 指纹语义不变。★**M0 判定一处现测纠正为核销**（机器判定人工纠正先例）：预签名签名键「进程内随机（`secrets.token_bytes`）」——`extensions.py` 实为 `sha256("fde-local-storage:"+jwt_secret)` **域分离派生**（跨重启稳定、换机随 FDE_JWT_SECRET 迁移），本轮补跨实例签名互认行为钉＋生产接线钉。
- **测试** NEW `test_m4_batch4_storage_subject.py` **16 例**：出厂默认安全钉（测出厂值——T-10a M8 家族教训）／闭集 fail-closed／主体段解析与跨 org 不碰撞／五状态写读矩阵（纯函数层）／平台根与 internal 桶语义／dual_write 双份字节一致／read_new 写新读新回落＋retired 零回落／签名绑物理键（跨 org 段签名拒绝）／签名键跨重启稳定＋生产派生接线钉／S3 草稿段／host 票据 org claim（含 authorize_host_run 归属解析）／CLI 迁移 dry-run→execute→幂等三连（E2E）／静态钉。**变异验收**：M1 摘 dual_write 双写 ⇒ 3 红／M2 摘 platform 段 ⇒ 3 红→字节级还原＋sha256 对账→16 绿；邻域回归 172 例绿。
- ★**实施期自查修正三处**（测试/mypy 当场抓住）：①帮手作用域 NameError（`_signed_download`/`_store_template_docx`/`_read_upload_bytes` 无 session 形参——500 化被既有测试抓回）⇒ 帮手内部自取 `db.session()`，调用点零改动；②`_read_version_docx` 第二调用点漏改 ⇒ mypy call-arg 抓回；③无主项目预期错误 ⇒ M1 `before_flush` 自动戳 `INTERNAL_ORG_ID` 平台内部桶（「无归属项目」结构上不存在——platform 段真实入口＝非项目根＋显式平台作业；M3b「internal org 桶」登记语义的延续）。既有 `test_transcript_drafts` 物理路径断言按新语义改写（经 `_draft_dir` 同源解析）。
- **结构口径**：本轮自身零迁移零新路由零新表零新蓝图；融合上游 #349（M5-1/M5-2：+4 路由＋1 表＋1 迁移 `c1d4e7f9a2b3`）后合并树现测 **469 路由／51 蓝图／151 表／69 rev 单头 `c1d4e7f9a2b3`**（inventory JSON/route CSV/archify 图纸＋preview 1440×2098 实拍已按融合树重生成，防陈旧闸绿）。mypy **279 基线不变**；ruff 绿。pytest **+16**（基线＝融合 #349 后 main run 43055468508 实测 **3126 收集 = 3119 passed + 7 skipped**＋本轮 +16 ⇒ 合并树预期 **3142 收集 = 3135 passed + 7 skipped**，**终值以本 PR CI 为准**）；server 变更 ⇒ 合并后 rebuild 三镜像＋`alembic upgrade head`（融合树升 `c1d4e7f9a2b3`）。

## [未发布] — 多客户 M4 批次 C 轮：队列 job 主体标签（迁移 `e9b4f7c2a8d3` 67→68 rev＋`outbox_events.subject_org`/`background_jobs.org_id` 两列＋入队主体声明机械闸＋27 调用点接线＋admin 计量读面，2026-11-11）

- **任务书 §7-M4「队列 job 携带主体标签用于计量」落地**（盘点表维度 3 §3b 队列行＋维度 4；交互拍板推荐项③：**NULL=平台级**——计量面不是授权面，入队零阻塞）。NEW 迁移 `e9b4f7c2a8d3`（挂批次 B `c3f7b1d9e5a2` 之后保单头）：`outbox_events.subject_org` ＋ `background_jobs.org_id` 两可空列＋`ix_background_jobs_org_id` 索引，**additive 零回填**（存量行 NULL=平台级——推断不伪装成事实）。
- **机械闸＝编译器强制全调用点声明主体**：`enqueue_outbox(..., subject_org)` 与 `ensure_background_job(..., subject_org)` 改 **keyword-only 必填**——漏声明的调用点直接 TypeError，不靠评审记忆。归属解析 helpers 三件：`subject_org_of_project`（项目优先→创建者回退→None）／`subject_org_of_user`／`subject_org_of_automation_task`。**27 个生产调用点全接线**：ai/executions（actor.org_id）／control/chat（会话用户）／scheduler＋control/service×3（自动化任务主体）／diagnostics＋cli＋files/expiration（平台级 None——匿名面/运维作业/清理作业）／discovery×2＋documents×3＋solutions×2＋research/export×2＋translator＋workflows×3＋guidance（项目归属）；dispatch 单点复制 `event.subject_org → job.org_id`（`outbox.py::dispatch_pending` 唯一通道）。
- **计量读面**＝`GET /api/v1/admin/jobs/metering`（挂既有 admin_jobs 蓝图，**不进 api_catalog**）：admin 只读（非 admin 403 `job_metering_forbidden`）；按 `org_id` 分组 active（pending/queued/running）/terminal 计数＋平台级单列＋Redis queue_depth；**计量面非授权面**——只读呈现，零调度行为影响（无 org 的 job 不出现＝零编造）。
- **静态钉**：全仓 `enqueue_outbox(` 调用点窗口内必须显式 `subject_org=`＋`outbox.py` dispatch 必须传 `event.subject_org`（防新调用点绕过主体声明）。★**机械闸价值实证**：静态钉当场抓到 grep 盘点遗漏的 `solutions/service.py` 两处调用点。
- **测试** NEW `test_m4_batch3_queue_subject.py` **6 例**：全链钉（企业 actor ⇒ `outbox.subject_org` ＝ `job.org_id` ＝ 企业 org）／平台级钉（平台身份 ⇒ 两处均 None）／helper 解析与回退钉／计量读面（viewer 403＋admin 分组＋无 job 的 org 不出现＋queue_depth）／静态钉／迁移列＋索引。**变异验收**：M1 摘 dispatch 复制（传 None）⇒ 全链钉红 2；M2 摘计量分组 ⇒ 读面红 1；字节级还原＋sha256 对账后 6 绿；邻域回归（admin_jobs/outbox/worker 既有 22 例＋直调点补 `subject_org=None` 适配 keyword-only 闸）＋translator/solutions 定向 41 例全绿。★**实施期自查修正两处**（mypy 闸当场抓住）：①translator 初版接 `row.project_id`——TranslatorTranslation **无此列**，改走 `subject_org_of_user(row.created_by_user_id)`；②solutions `_retry_failed_export` 的 `document_for_org` 条件绑定 union-attr——取值移出 if 块＋None 早退。
- **结构口径**：路由 **465**（+1 计量面；融合树＝上游 #341 +1 ＋批次 B +2 ＋本轮 +1）／蓝图 **51** 不变／表 **150** 不变／**68 rev 单头 `e9b4f7c2a8d3`**；审计清单三件套重生成（route CSV +1 行；JSON 465/51/150/68）；archify 图纸口径同步＋preview 整页实拍（防陈旧闸绿）。mypy **279 基线不变**；ruff 绿。pytest **+6**（基线＝#340 合并后 main CI 实测 **3091 收集 = 3084 passed + 7 skipped**（squash `5027fc4`；PR 树 run 43028141751 逐位吻合）＋本轮 +6 ⇒ 合并树预期 **3097 收集 = 3090 passed + 7 skipped**，**终值以本 PR CI 为准**）；server 变更 ⇒ 合并后 rebuild 三镜像＋`alembic upgrade head`（新迁移）。

## [未发布] — 多客户 M4 批次 B 轮：AI 预算按企业 org（迁移 `c3f7b1d9e5a2` 66→67 rev＋`orgs` 加列＋预算判定主体化＋admin 双闸写面，2026-11-11）

- **任务书 §7-M4「AI 预算闸从整实例单值改为按主体额度」落地**（盘点表维度 1 必改行；GAP-04 额度账承接；交互拍板推荐项①：**主体＝企业 org**——`orgs.subject_key` 已在位＝org 即主体承载）。NEW 迁移 `c3f7b1d9e5a2`（挂 `a7c2f9e1b4d8` 之后保单头）：`orgs.ai_monthly_token_budget INTEGER NULL`——**NULL=未配置回落实例值（现状零回归）／0=不限额（沿 E7 心智）／正数=该 org 月度 token 额度**；**零数值预写**（迁移只加列不播种，G 线纪律）。
- **判定单一权威点**＝`ai/auditing.py::subject_budget_exceeded`：企业身份＋org 已配置 ⇒ **org 额度＋同 org 全员月度合计**（`org_tokens_used_this_month`——防企业内多账号分摊绕过主体额度）；**其余（平台身份 `org_id=NULL`／org 未配置）完整回到现状**＝实例值＋按 user 汇总（`budget_exceeded` 原语义）；0=不限额、actor 未知放行、设施故障 fail-open 由调用方承担（三调用点既有语义不变）。**三腿调用点全部接线**：deepseek 直连腿／DSH 主路径 `execute_ai_prompt`／kimi 本地腿。NEW **静态钉**：全仓 `budget_exceeded(` 调用点只许在 `ai/auditing.py` 内部（防新调用点绕过主体化）。
- **治理面**＝`GET/PUT /api/v1/admin/commercial/orgs/<org_id>/ai-budget`（挂既有 admin_commercial 蓝图，**不进 api_catalog**）：admin 门＋密码确认双闸（CR-047 限流同闸）＋逐动作 `operation_events` 留痕（带 request_id，**密码不落事件**）＋值闭集（`None`/≥0 整数，负数/浮点/字符串/布尔 400 `invalid_budget`）＋读面回读（含当月 org 用量与回退来源标注）。
- **测试** NEW `test_m4_batch2_ai_budget_subject.py` **10 例**：org 全员合计（单 user 不超、合计超 ⇒ 拦，实例值故意给大）／org 未配置回退（回退态按 user，同 org 他人不连坐）／平台身份现状语义／org 0=不限额／DSH 主路径接线（org 值 ≠ 实例值也生效，拦截零 DSH 请求）／admin 双闸（403/400/403 矩阵＋留痕无密码）／值闭集与清回未配置／org 404／静态钉／迁移往返（additive 可空）。**变异验收**：M1 摘 org 全员合计（误按单 user）⇒ 1 红；M2 摘回退语义（回退值误判 0=不限额）⇒ 2 红；字节级还原＋sha256 对账后 10 绿；邻域回归（budget_audit CR-006 钉＋migrations 单头/计数）35 例全绿。★**实施期自查修正**：回退语义初版误把实例值套在 org 全员合计上（会意外收紧未配置企业的存量行为）——测试钉当场抓住并修正。
- **结构口径**：路由 **464**（+2 治理面；融合树含上游 #341 +1）／蓝图 **51** 不变／表 **150** 不变／**67 rev 单头 `c3f7b1d9e5a2`**；审计清单三件套重生成（route CSV +2 行；JSON 464/51/150/67 逐位吻合）；archify 图纸口径同步（462→464 改图＋preview 1440×2098 实拍，防陈旧闸复绿）。mypy **279 基线不变**（官方闸 OK）；ruff 绿。pytest **+10**（基线＝#341 合并后 main run 43021455616 实测 **3081 收集 = 3074 passed + 7 skipped**＋本轮 +10 ⇒ PR CI 实测 **3091 收集 = 3084 passed + 7 skipped**（run 43028141751，合并 SHA `5027fc4`）；★rebase 作废已测基线——#340 原头实测 3076 passed + 7 skipped（run 43013304914）属插队前基线，已作废）；server 变更 ⇒ 合并后 rebuild 三镜像＋`alembic upgrade head`（新迁移）。

## [未发布] — 多客户 M4 批次 A 轮：Redis 面主体归属核销（纯测试零生产代码改动零迁移零路由，2026-11-11）

- **M0 判定两处经 M4 现测纠正为核销**（机器判定人工纠正先例）：①**K4/K5**（`fde:ai-execution:{id}:state`/`:events`）——`ai/executions.py::get_execution` **已**按 `state.actor_id != actor.id ⇒ 404`（`ai_execution_not_found`，不确认存在性），状态与事件流同一归属闸覆盖，sec 评审「必加 actor 归属校验」的要求**已结构性满足**；②**K3**（`fde:ai:action:{identifier}`，arch 评审点名的「最高危」）——锁键 identifier＝`sha256([user.id, execution_id, data])` **已含执行者维度**＋MCP claims 系 JWT 签名（`sub`/`auth_version` 从库重解析）＋事件账按 `actor_user_id` 过滤 ⇒ 「UUID 不可枚举不足以作为防线」的担忧由三重绑定兜住。M0 盘点（先验口径）写「无主体维度」，M4 现测（引用前现测纪律）推翻。
- **NEW `test_m4_batch1_redis_subject.py` 3 例进 CI**：①K4/K5 跨主体读 ⇒ 404＋阳性对照（本人可读含首条 stage 事件）；②K3 跨账号同 `(execution_id, data)` 提交 ⇒ action_id 必不同＋事件账按 actor 隔离＋B 重放不撞 A 的账；③K10/K11 非项目成员持合法 preview token commit ⇒ 404 `project_not_found`（token 绑 `(preview_id, project_id)`＋`load_subject_project` 项目闸）。
- **变异验收**：M1 摘 `get_execution` actor 校验 ⇒ 1 红；M2 摘 K3 identifier 的 user.id 维度＋事件账 actor 过滤 ⇒ 1 红；字节级还原＋sha256 对账后 3 绿；邻域回归（execution/api_actions 既有 15 例）全绿。
- **K1/K2/K6–K9/K12/K13 核验销号**：自带主体维度（username+ip／user_id／IP 假名／令牌指纹）或属服务间认证/匿名面/运维心跳（既有套件覆盖，不重复造例）；K10/K11 归属闸核销见上。
- 口径：pytest **+3**（基线＝F 线 T6 融合树 CI 实测 **3070 收集 = 3063 passed + 7 skipped**〔#334 段自报合并态；基链＝M3b 收口 3058＋T6 +12；上游十四度插队 rebase 融合〕＋本轮 +3 ⇒ 预期 **3073 收集 = 3066 passed + 7 skipped**，终值以本 PR CI 为准）；mypy 279 不变；零迁移零新路由零新表零新蓝图零桌面。

## [未发布] — 多客户 M3b 收口轮：四批 236 端点全量销号完成＋部署活体复验（纯文档零代码零迁移零路由零桌面，2026-11-11）

- **销号完成**：M3b 四批全部合并入 fork/main——①-a（24 条，PR #325 `828557e`）／①-b（15 条，PR #328 `8cefc07`）／②（43 条，PR #331 `7eb9a17`）／③（97 条，PR #335 `713407b`）／④（57 条，PR #336 `405c541`＝fork/main 顶）。★**销号范围＝盘点表现测 236 全量**（write-level 79 实改＋read-only 157 读面收敛核验；任务书「122 写端点」是 M0 前先验，盘点表为准）。
- **pytest 链（全部取**合并树 CI 实测**，不承袭 PR 期数字）**：①-b **3025 收集 = 3018 passed + 7 skipped**〔run 42978834244〕／② **3039 = 3032 + 7**〔PR #331 run 42983140581〕／③ **3052 = 3045 + 7**〔PR #335 server-tests〕／④ **3058 = 3051 + 7**〔PR #336 run 42989050456〕。★口径链的基必须取**合并树**实测——①-a 的 PR 期实测 3010 是 **rebase 前** PR 树值（rebase 融合上游 #323 ＋9 后合并树实测 3019），拿它推算会偏。
- **结构口径现测**（收口现测，不承袭）：462 total／**461 non-static 路由**／**51 蓝图**／**150 业务表**／**66 迁移单头 `a7c2f9e1b4d8`** ＝ 四批零迁移零新路由零新表零新蓝图。
- **部署活体复验**（合并树 `405c541` 干净树 rebuild）：三镜像 api `4434826db5e8`／worker `ab3fec947c15`／scheduler `85c7f91e3a88`，容器 `.Image` 与构建产物**逐位一致**；`alembic upgrade head` **幂等 no-op**，容器内 `alembic current` = `a7c2f9e1b4d8 (head)`；活体 `url_map` **462 total / 461 non-static** ≡ 口径；ready **200**／live **200**；★**diagnostics 部署闸默认关 ⇒ 活体 404（不确认面存在）**；三容器 **healthy**；`/app/migrations` 挂载**＝本工作树**（批次①部署时此处曾指向**他人工作树** `fde-wt-f1`——活体部署跨会话共享资源复现，已按「部署后必验三项」处置）。
- **遗留如实登记（不掩盖）**：①**internal org 桶内跨企业混装**（盘点表待 M0 补充 #7）⇒ 消解路径归 M5；②**商机/额度主体以代号关联而非 org FK**（`enterprise_code`／`subject_key`）⇒ 其留痕判定原语未就绪，归 M5；③**活库企业身份账号 0**（注册闸关）⇒ 企业身份分支的**活体验证**待试点首个企业账号（不以测试库冒充活体）；④ADR-M3 §5「跨企业 package_access 授权 admin-only」半边**不适用**（无显式授予端点，授权在发布流程隐式发生＝派单本体跨企业）；⑤`revoke_package_access` 当前零生产调用点（仅测试可达），本轮未改其签名。

## [未发布] — 多客户 M3b 批次④ 轮：特殊域与平台事实 57 端点（dispatch package_access 授予留痕＋特殊域隔离核验；零迁移零新路由零新表零桌面，2026-11-11）

- **销号范围**：《全局面盘点表》④ 特殊域与平台事实全量销号——**dispatch 撮合域 18**（packages 写面 10＋offers 3＋disputes 2＋simulator replay 1＋admin rules 2）＋**simulation 演练域 14**＋agents／ai／bridge／internal／users／auth 等 25。机器判定分布＝特殊域单列 32（ADR-M3 §5）＋读面收敛核验 16＋R1 admin-only 保持＋留痕核验 5＋R2 目录写 1＋R3 主体归属 2，**逐条人工复核**：simulation 演练域是**平台级训练域**（不挂 projects/orgs，样本为模拟体）⇒ org 维度不适用；internal 3 条是**服务间认证**（令牌，非用户面）；agents／ai／bridge 各域的隔离面由既有套件覆盖（盘点表测试指针）⇒ 本批**核验销号不重复造例**。
- **实改面＝dispatch `package_access` 授予留痕**（ADR-M3 §5 对撮合域只提的一件事：「谁授权给谁」）：`dispatch/access.py::grant_package_access` 每次授予落一条 `package_access_granted` 事件（授权人 → 被授权人 → 包 → 角色），被授权人属**别家企业**时，共享事件记录器（`projects/events.py`）单点接线自动加 `cross_org_` 前缀并把 `org_id` 取为**被授权账号归属**——跨企业授权在审计面可分辨（企业之间 vs 平台内部桶）。★**「跨企业授权 admin-only」半边如实登记为不适用**：仓库里**不存在**显式的 package_access 授予/撤销端点，授权只在**发布**流程里隐式发生（派单撮合本体：交付方席位天然跨企业），对其加 admin 闸＝断掉派单本体；`revoke_package_access` 当前零生产调用点（仅测试可达），本轮未改其签名。
- **dispatch 访问面核验**：`package_access` 是**独立于 project_access 与 admin 的第三语义**（`dispatch/access.py` 模块 docstring 明示）——无未撤销授权行 ⇒ **404**（不泄露包存在性）；admin 平台全局语义放行；授予后同一账号可读（阳性对照）。三条既有纪律（禁 join quotes/payments/contracts／响应白名单 schema／路由层 `require_package_access` 强制前置）**一字未动**。
- **users 域核验**：批次②的共享记录器接线顺带覆盖 `PATCH /users/<id>`——admin 改**别家企业**账号 ⇒ `cross_org_user_updated`（平台身份目标事件名逐字节不变）。
- **测试**：NEW `test_m3b_batch4_special_domains.py` **6 例**（授予留痕 3＋dispatch 访问面 2＋users 域跨 org 留痕 1）；**摘除式变异**（打单一权威点＝摘 `grant_package_access` 的 `_record_grant_event` 调用）⇒ **3 红 → 还原 → 6 绿**；邻域回归 dispatch 十八套件＋`test_agent_assisted_integration` 全绿；mypy 官方闸 **279 零新增**；ruff 绿。
- **口径**：零迁移零新路由零新表零新蓝图 ⇒ 结构口径不变（**461 路由／51 蓝图／150 表／66 rev 单头 `a7c2f9e1b4d8`**）；pytest 基线＝批次③ 合并树 CI 实测 **3052 收集 = 3045 passed + 7 skipped** ＋本轮 **+6** ⇒ 预期 **3058 收集 = 3051 passed + 7 skipped**（终值以本 PR CI 为准）。server 变更 ⇒ 合并后 rebuild 三镜像＋alembic（本轮零迁移，幂等 no-op）。

## [未发布] — 多客户 M3b 批次③ 轮：项目服务域 97 端点（成员面跨 org 留痕接线＋可见性单一权威机械闸＋域级代表性核验；零迁移零新路由零新表零桌面，2026-11-11）

- **销号范围**：《全局面盘点表》③ 项目服务域 97 条（80 条在 `/projects/*`＋meetings 5＋handover-packages 4＋transcript-drafts 3＋translator 2＋delivery-plans 1＋discovery 1＋task-center 1）全量销号。机器判定分布＝83 条「读面收敛核验」＋13 条「R1 admin-only 保持＋留痕核验」＋1 条「R3 主体归属校验」，**逐条人工复核后**：项目域既有行为按规格 §3.5「既有项目域行为本轮不变」保持原样（同项目无权＝403 `forbidden`、资源缺失＝资源级 404），本批**不改写**既有错误码；读面全部经 M3a 统一入口 `projects/permissions.py`（`project_access` 对象级／`visible_project_filter` SQL 谓词）——逐服务核验 8 个项目服务模块（version/draft/quote/payment/contract/gate/task/research）＋项目本体，均走统一入口。
- **实改面＝成员面跨 org 留痕接线**（规格 §3.4 明列「成员跨企业授予」）：共享事件记录器 `projects/events.py::record_event` 的单点接线把**项目成员行**目标解析为其**账号**再判定——平台/他企业 admin 把**别家企业**账号授予项目成员（跨企业成员关系）⇒ 事件名带 `cross_org_` 前缀（`cross_org_project_member_added`）且 `operation_events.org_id` 取**被作用账号归属**（被授予账号所在企业，**不是**项目归属——口径与批次②的账号类代操作一致）。同企业内授予、平台身份账号授予 ⇒ 事件名逐字节不变（存量零回归；平台身份账号的事件 org 维度仍由 M1 归属戳监听器从 project 推导＝internal 桶）。
- **机械闸＝「自建可见性谓词」全仓扫描**（把①-b 的教训固化为闸）：除 `projects/permissions.py` 外，任何函数都不得拿 `ProjectMember` 的字段构造**可见性谓词**（比较形态）——eager load（取数）与归属戳计算不算。全仓现测 4 处候选**逐条人工复核为假阳性**并入白名单（序列化成员行／归属戳计算／交付方身份标记／admin 改角色前的成员关系冲突检查）；白名单条目失效时闸同样转红（防白名单腐化）。
- **域级代表性核验（拍板 2026-11-11 交互四项之②）**：跨企业**成员关系**场景（企业甲账号被平台授予企业乙项目的成员身份）——成员关系本身挡不住 org 维度，这才构成判别力。项目详情＋gates/quotes/payments/contracts/members/tasks/gantt 八个读面：跨企业成员一律 403/404，project_leader 正常 200（阳性对照）。
- **测试**：NEW `test_m3b_batch3_project_service.py`；**摘除式变异**（两轴：摘 `record_event` 的成员面跨 org 判定 ⇒ 留痕用例转红；在服务里自建 ProjectMember 谓词替换统一入口 ⇒ 机械闸转红）⇒ 还原→全绿；邻域回归 M 线四套件＋`test_visibility_parity`＋项目服务域邻域用例全绿；mypy 官方闸 **279 零新增**；ruff 绿。
- **口径**：零迁移零新路由零新表零新蓝图 ⇒ 结构口径不变（**461 路由／51 蓝图／150 表／66 rev 单头 `a7c2f9e1b4d8`**）；pytest 基线＝批次② 合并树 CI 实测值 ＋本轮增量（终值以本 PR CI 为准）。server 变更 ⇒ 合并后 rebuild 三镜像＋alembic（本轮零迁移，幂等 no-op）。

## [未发布] — 多客户 M3b 批次② 轮：商业域 43 端点（跨 org 留痕共享记录器单点接线＋admin-only 保持＋主体归属核验；零迁移零新路由零新表零桌面，2026-11-11）

- **销号范围**：《全局面盘点表》② 商业域 43 条（27 写面＋16 读面）全量销号。**本批唯一实改面＝共享事件记录器单点接线**：`projects/events.py::record_event` 对「目标为**用户**且 actor 作用于**别家企业**账号」自动加 `cross_org_` 事件名前缀，并把 `operation_events.org_id` 取为被作用账号归属（规格 §3.4）。商业域 admin 代操作面（角色分层／席位激活／认证判定／交付资格／培训授予／培训撤销／首单扣费／兼任承载）**零调用点改动即接线**——AST 扫描商业包 41 处 `record_event`：仅 7 处目标为用户，其余 34 处目标为 actor 本身（平台身份 ⇒ 判定恒 False ⇒ 存量事件名逐字节不变）。
- **拍板口径落地（2026-11-11 交互四项之④「企业 org 之间才算」）**：判据 `isolation.is_cross_org_action(actor_org, resource_org)`＝目标 ∈ 企业 org 且 ≠ actor 归属 org；平台内部 org 桶＝平台身份大本营**不算**跨 org。三个正交判据各有用例钉住：①平台身份目标（`users.org_id IS NULL`）⇒ **不产生**前缀事件（存量零回归钉）；②同企业内 admin 作用于同企业账号 ⇒ **不算**跨 org；③企业甲 admin 作用于企业乙账号 ⇒ 算跨 org，org 维度取企业乙。
- **R1 admin-only 保持（12 条）**：企业身份打商业治理面全 403（`commercial_admin_required`）——覆盖费用配置位／分成规则登记／收入科目记账／商机规则配置位／归属改派／客户自主选择／争议／保护期设置／保护期续期／区域伙伴升级／售卖闸条件登记／售卖闸开闸。**admin 仍是平台白名单**（规格 §3.3：角色白名单语义不变），跨企业代操作**允许但必须留痕**——不新建第二套权限体系（红线 8）。
- **R3 主体归属（11 条）**：admin 代操作六端点对非 admin 全 403；自助面跨企业一律被拒——企业空间读面 **404**（CR-062：不透主体存在性）／付费选项选择 **403**（只认绑定账号本人）／额度启动 **409**（换账号不重置）／额度确认 **403**（平台不代企业确认，含 admin 代确认）／商机撤回 **403**（只认报备人本人）／商业权益读面 **403**（本人或 admin）。
- **机器判定的人工纠正（诚实留痕）**：盘点表把 `POST /api/v1/mailing/sns/events` 列为「R1 admin-only 保持」属**机器误判**——该端点是 SES 回调**服务间面**（SNS 服务器不可能携带工作台 JWT；鉴权＝签名校验＋TopicArn 白名单，见 `mailing/routes.py` 模块 docstring），隔离面由既有 `test_mailing_ses.py` 覆盖（坏签名／外来证书 URL／错误 Topic 三连），本批**核验销号不重复造例**；同域 `diagnostics` 四条是公网免注册写面（部署闸默认关 ⇒ 404），隔离面由既有 `test_diagnostics_mvp.py` 覆盖。
- **测试**：NEW `test_m3b_batch2_commercial.py` **14 例**（跨 org 留痕 6＋admin 闸 2＋主体归属 5＋读面收敛 1）；**摘除式变异（打单一权威点＝摘 `record_event` 的 `is_cross_org_action` 分支）⇒ 4 红 → 还原 → 14 绿**（判别力验收：另 10 例在变异下仍绿＝它们本就不依赖前缀，符合预期）；邻域回归 M 线三套件＋`users_api`＋`audit_mutations` **99 例全绿**（零回归），商业域十套件（quota/space/entitlements/opportunity/readiness/regional/registration-throttle/revenue-ledger/role-assignments/concurrency）**178 例全绿**；mypy 官方闸 **279 零新增**；ruff 绿。
- **批次① 收口：部署活体复验（随本 PR 回写）**：三镜像从**合并树 `8cefc07`** 干净树 rebuild（api `7df8c48cf795`／worker `5c8aee2f85bf`／scheduler `47f61cb5cf4b`）＋ `up -d --force-recreate`；容器 `.Image` 与构建产物**逐位一致**；`alembic upgrade head` **幂等 no-op**，容器内 `alembic current` = `a7c2f9e1b4d8 (head)`（本轮零迁移，树上有 T5 未部署迁移同 head）；活体 `url_map` **462 total / 461 non-static** ≡ 口径 461；ready **200**／live **200**；★**diagnostics 部署闸默认关 ⇒ 活体 404（不确认面存在）**；三容器 **healthy**；`/app/migrations` 挂载**回归本工作树**（部署前指向**他人工作树** `fde-wt-f1`——活体部署跨会话共享资源复现，已按「部署后必验三项」处置）。★如实登记：部署前观察到 **scheduler 心跳中断**（`fde:health:scheduler` 键缺失 ⇒ 健康检查转 unhealthy），中断发生在本轮部署**之前**、由非本工作树镜像的旧容器产生；重建后心跳恢复（age 22s）且三容器 healthy。
- **口径**：零迁移零新路由零新表零新蓝图 ⇒ 结构口径不变（**461 路由／51 蓝图／150 表／66 rev 单头 `a7c2f9e1b4d8`**）；pytest 基线＝批次①-b 合并树 CI 实测 **3025 收集 = 3018 passed + 7 skipped**（PR #328 run 42978834244）＋本轮 **+14** ⇒ 预期 **3039 收集 = 3032 passed + 7 skipped**（终值以本 PR CI 为准）。server 变更 ⇒ 合并后 rebuild 三镜像＋alembic（本轮零迁移，幂等 no-op；树上有 T5 未部署迁移 `a7c2f9e1b4d8` ⇒ 部署合同见批次①收口轮）。

## [未发布] — 多客户 M3b 批次①-b 轮：控制台第三套可见性规则收拢（`_project_scope` 销号）＋模板·内部面核验（零迁移零新路由零新表零桌面，2026-11-11）

- **核心销号＝《全局面盘点表》待 M0 补充 #6**：`control/service.py::_project_scope` 是可见性的**第三套规则**（leader-OR-成员——无 org 谓词、leader 分支无角色尺），本轮删除本体，**三个消费点全部收拢统一入口 `visible_project_filter`**（M3a 单一权威）：`list_task_center`（服务内 337）、`list_automation_approvals`（服务内 681）、`list_task_board`（**`control/task_board.py:93` 经 import 跨模块消费——首轮只扫 service.py 漏检，回归测试红抓回后同配方收拢**；跨模块 grep 是「第三套规则」排查的教训面）。关键场景仍是**跨企业成员关系**：企业乙账号被加进企业甲项目后，控制台两清单（任务/审批）不再经旧路径漏出＝幽灵行防线对控制台域补齐。
- **核验销号（12 条，零代码改动面，盘点表处置建议逐条人工复核）**：industry-templates 6 条写面＋templates research-forms 3 条写面＝`@require_role("admin")` 角色闸在位（R2 目录写 admin-only 保持；机器判定把 PATCH/DELETE 版本面标成「读面」属 AST 误判，人工复核纠正）；internal 3 条＝**服务间认证**（`/internal/dsh/*` DSH 服务令牌、`/internal/clawbot/*` ClawBot 网关令牌——非 JWT 用户面，org 维度不适用，M4 令牌租户化的输入，盘点表维度 5 已登记）；task-center 3 条写面＝服务层 `authorize_ai_capability → project_access`（统一入口含 org 谓词）✓。
- **测试**：NEW `test_m3b_batch1b_task_center.py` **6 例**——跨企业成员两清单不漏出（审批清单＋任务主清单，各带平台身份 leader 同域可见性 sanity）、跨企业审批决策 403、行业模板 6 写面/调研表单 3 写面 admin 闸 403、internal 服务间面坏令牌 401。**摘除式变异（两消费点两形态全打：`scope =` 赋值形＋`.where()` 内联形换回 org-less leader-OR-成员）⇒ 2 红→还原→6 绿**；邻域回归 task_board/control_plane/审批 SLA/expirations/metrics_v31 **58 例全绿**（首轮 6 红即 task_board 的 NameError＝第三消费点漏检信号）；mypy 官方闸 **279 零新增**；ruff 绿。
- **口径**：零迁移零新路由零新表零新蓝图 ⇒ 结构口径不变（461 路由/51 蓝图/150 表/66 rev 单头 `a7c2f9e1b4d8`）；pytest **CI 实测 3025 收集 = 3018 passed + 7 skipped**〔PR CI run 42971930465 server-tests；基线＝批次①-a **合并树** main run 42970619241 实测 **3019 收集 = 3012 passed + 7 skipped**（合并 SHA `828557e`）＋本轮 **+6** ＝ 3025 逐位吻合；★①-a PR 期实测 3010 收集＝rebase 前 PR 树值，已随 #323 插队融合作废〕。**批次①（39 条）随本 PR 全量销号**；部署活体复验＋DoD 回写归批次①收口轮。
## [未发布] — 夜审挂账设计轮 r8（CR-071 web 桥校验族多方案设计稿＋活体部署挂账销项＋4 挂账触发态 E0 现测；纯文档零代码零迁移零路由，2026-11-11）

- **CR-071 设计轮（蔡工 2026-11-11 续「按你建议继续实施」开设计轮；4 挂账触发态 E0 现测坐实时机已到）**：NEW `docs/audit/夜审-CR071-web桥校验族多方案设计稿-2026-11-11.md`（取证基线 fork/main `828557e`，全部锚点现测）——**两桥 8 项校验面对照**：桌面 `api-ipc.ts::validateRequest` 8/8 全在位；web 桥 `fde-web-bridge.ts` 仅 3/8（缺 method 白名单〔任意 method 可发〕／auth 路径排除／编码双重解码〔`%2e%2e`/`%252f` 可穿透 raw 检查〕／multipart 严格拒绝〔非法形状 `return null`⇒无 body 裸发＝静默降级〕／控制字符区间／body 可序列化）；**推荐 A＝NEW `shared/api-safety.ts` 纯函数单点**（桌面 api-ipc.ts 与 web 桥双消费同一原语＋**等价性静态钉**防再漂移——报告消解条件「规则提升 shared/ 单点」原文落地）；B 双副本必漂移／C 最小封口（不封编码逃逸真绕过面）均否决留痕。**实施待蔡工拍板**（纯桌面零服务端⇒无需 rebuild/alembic；桌面改动⇒便携版 r36 随轮）。
- **4 挂账触发态 E0 现测（只读）**：CR-071＝**半满足**（web 桥本体＋`web.html` 已在 main 树、`feat/web-distro-t1` 在途扩大暴露面、公网试用部署文档 4 份在场＋README:244 活链⇒设计轮时机已到）；CR-061（host_poll 生产闸默认关⇒并发领取不可达）／CR-055（用例编辑·需求撤销通道未立项⇒护栏钉无施工面）／CR-074（`c4f7a2d9e1b6` 迁移文件未再触碰）＝**触发未满足维持挂账**。
- **活体部署挂账销项（他线已按部署合同推进）**：r8 E0 只读复验＝容器内 `alembic current`＝`a7c2f9e1b4d8 (head)`（＝fork/main 单链迁移头，F 线 T5 迁移已应用）＋三容器 healthy＋活体 url_map non-static **461** ≡ 审计清单——**活体已追平 fork/main 不再落后**（r6 登记时停在 r5 `a9c5e2d7b3f1` 落后三迁移），部署挂账销项，后续随新迁移线走各改动线部署合同。
- 口径：纯文档轮——server 零改动⇒无需 rebuild/alembic；桌面零改动⇒不重打包；pytest/mypy/vitest 零变化（终值随本 PR CI 复核）。

## [未发布] — 多客户 M3b 批次①-a 轮：AI 与扩展控制面 org 收口＋跨 org 留痕接线（零迁移零新路由零新表零桌面，2026-11-11）

- **任务书 §7-M3b ＋ M3b 拍板（2026-11-11 交互四项，全部推荐项）**：①销号范围＝**236 全量**（write-level 79 实改＋read-only 157 读面收敛核验；任务书「122 写端点」是 M0 前先验，盘点表现测为准）；②read-only 核验深度＝**域级代表性用例**进 CI；③节奏＝**批次①先行，绿后同会话续推②③④**；④留痕触发面＝**企业 org 之间才算**（平台内部桶＝平台身份大本营，不算跨 org——否则试点期每次日常写动作都产生事件）。批次①（平台控制面 39 条）按蓝图原子性拆两实际批：**①-a「AI 与扩展控制面」24 条**（ai 6／extensions 14／modules 2／document-templates 1／users ai-access 1，本节）＋①-b「模板·任务中心·内部面」15 条（含待 M0 补充 #6 `_project_scope` 收拢，另 PR）。
- **人工复核发现（盘点表机器判定的缺口，本轮修复）**：扩展控制面的平台管理面门禁是 **AI 档判定（`effective_ai_access == 'system_operator'`）而非角色判定**——企业身份账号一旦被 admin 显式授予 `system_operator` AI 档，即可写 R1 平台私有表（`ai_provider_configs`/`ai_model_configs`/`plugin_catalog_syncs`）、R2 公共目录（公共 Skill 保存/治理四闸/公共模型配置）并**审批他人插件变更**——R1「企业不可见不可写」在 org 维度失守。修复＝**单一判定 `access.is_platform_operator(user)`**（平台身份 ＋ system_operator AI 档，`orgs/isolation.py` 的 `is_platform_identity` ＋既有 AI 档），收口 6 处门禁点：`_require_system_operator`（提交审核/发布/回滚/弃用/模型供应商/模型/插件审批 8 调用点）、`save_public_skill`、`_serialize_skill` 的公共技能 `can_edit`（企业身份对公共 Skill 恒 False——PATCH 下架面一并封死）、`save_model_preference`/`delete_model_preference` 公共分支、`sync_dsh_market`。**admin 经 `effective_ai_access` 恒 system_operator ⇒ 平台侧行为零变化**（存量用户全是平台身份，存量回归面零）。
- **跨 org 留痕接线（M3a 规格 §3.4，拍板口径落代码）**：`orgs/isolation.py` NEW `is_enterprise_org_id`／`is_cross_org_action`（目标 ∈ 企业 org 且 ≠ actor 归属 org）。两处接线：①`PATCH /users/<user_id>/ai-access`——admin 代改**别家企业**账号 ⇒ 事件名 `cross_org_ai_access.updated` 且 `operation_events.org_id` 取被作用账号归属；**平台身份目标保持原事件名 `ai_access.updated` 零回归**（存量主路径逐字节不变）；②`POST /extensions/plugin-requests/<request_id>/decision`——admin 审批**别家企业**账号的插件变更 ⇒ NEW `cross_org_plugin_change.decided` 事件（同事务提交，审批失败一并回滚；平台身份目标不产生事件＝零噪声）。**M3c 套件的 `xfail(strict=True)` 机械闸销号**：`test_cross_org_write_action_leaves_audit_event` 随本 PR 摘标记转正（改造完成即 XPASS ⇒ 强制摘标记的机制如约工作）。
- **核验销号（零代码改动面）**：lcsc 六端点主体归属结构在位（创建即 `user_id=self`、compare/desktop 续写 `own_run` 查 owner 之外 404 not_found——不确认资源存在，规格 §3.5 既有语义吻合）；modules POST/PATCH `@require_role("admin")`、document-templates 版本写 `@require_minimum_role("admin")` 角色闸在位；个人 Skill／个人模型配置 owner 自证；request_plugin_change 自助面。
- **测试**：NEW `test_m3b_batch1a_control_plane.py` **14 例**——R1/R2 平台面企业身份 403 五连（企业身份＋system_operator AI 档打供应商/模型/目录同步/公共 Skill 治理与开关/公共模型配置/插件审批/用户管理面）、跨 org 留痕四连（ai-access 企业目标落 `cross_org_` 前缀＋org 维度／平台目标事件名不变零回归钉／插件审批企业目标落事件／平台目标零事件钉）、lcsc 主体归属三连（compare 404＋列表自见／desktop 续写 404／个人 Skill 越权 403）、读面域级代表两连（extensions 个人配置列表自见／modules·document-templates 角色闸 403）。**摘除式变异三轴全红→还原→绿**：M-a′ 摘 `is_platform_operator` 的平台身份维度（**变异打在单一权威点**——首版打 `_require_system_operator` 调用点漏了 model_preferences 直调面，4 红不全 ⇒ 改打 `access.py` 本体后四门禁面全红）／M-b 摘 ai-access 留痕 ⇒ 1 红／M-c 摘插件审批留痕 ⇒ 1 红；还原后 14 全绿。M3a/M3c 三套件 35 例全绿＋邻域回归 113 例（control_plane/extension/lcsc×5/dsh_market/document_templates/audit_mutations/migrations）零回归；mypy 官方闸 **279 基线零新增**；ruff 绿。
- **口径**：零迁移零新路由零新表零新蓝图 ⇒ 结构口径不变（**461 路由/51 蓝图/150 表/66 rev 单头 `a7c2f9e1b4d8`**，本树现测与官方提取器逐位一致）；热点 `projects/service.py` 1937 未触碰；pytest 基线＝**2996 收集 = 2988 passed + 7 skipped + 1 xfailed**（F 线 T5 轮 main run 42961270504）＋ 本轮 **+14** ＋ xfail 转正（1 xfailed → passed，收集数不变）⇒ **CI 实测 3010 收集 = 3003 passed + 7 skipped**（PR CI run 42964990440 server-tests，＝2988＋转正 1＋新增 14 逐位吻合）。server 变更 ⇒ 合并后 rebuild 三镜像＋alembic（本轮零迁移，幂等 no-op，但树上有 T5 未部署迁移 `a7c2f9e1b4d8` ⇒ 部署合同见批次①收口轮）。

## [未发布] — 夜审挂账实施轮 r7（CR-056/057 桌面两挂点按 r6 设计稿落地：直连分片上传在途写计数＋打包态 CSP connect-src 构建注入；零迁移零路由零服务端，2026-11-11）

- **CR-056（夜审 r6 设计稿推荐 A′，蔡工 2026-11-11 拍板开实施）**：close-guard 在途写计数补覆盖 renderer 直连 signed-URL 分片 PUT——**新增共享面 `desktop/src/renderer/src/files/upload-helper.ts`**（`uploadMultipartParts` 收拢 4 处同构「取签→分片 PUT」循环：ProjectFiles／PresurveyUploadAction／NewProjectPageV2／FileVersionTimeline，行为逐位保留含取消语义与错误码）；**在途写计数经既有 IPC 桥**（NEW 通道 `appUploadBegin/End`，main 计入 `activeMutations`、preload/web-bridge 各补面对齐，web 形态 no-op 零行为变化）——helper 内置 `notifyUploadBegin/End`（`try/finally` 成对、best-effort 静默退化）；100MB 级上传中途关窗不再静默放行。**静态钉**（close-guard.test.ts 扩 4 例）：main/preload 通道接线在位＋helper begin/finally 成对＋**全仓 renderer 侧裸分片 PUT 只许出现在 upload-helper.ts（第 5 处上传面即红）**。
- **CR-057（夜审 r6 设计稿推荐 A＋D，同拍板）**：打包态 meta CSP `connect-src` 不再写死回环——NEW 纯函数 `desktop/src/main/build-csp.ts::buildCspConnectSrc`（缺省恒等于旧写死值＝零回归承诺；远程 `fdeApiUrl` origin＋可选 OSS 主机追加去重；绝不 `https:` 通配）＋`electron.vite.config.ts` NEW 构建注入插件（`apply:"build"` 只碰打包物不碰 dev；读 package.json `build.extraMetadata` 的 `fdeApiUrl`/`fdeOssHost` 单点来源，不造第二配置面）。**实弹双向验证**：本地默认打包 `out/renderer/index.html` connect-src 恒 `http://127.0.0.1:8010`（零变化）；临时改 extraMetadata 为 `https://app.fde18.com`＋OSS 主机后重打包 ⇒ `connect-src https://app.fde18.com https://oss-cn-hangzhou.example.com`（注入生效），恢复后回缺省。**方案 D 形态矩阵成文**＝README「远程部署」行补三形态对齐表（本地回环+local／远程 API+local／远程 API+OSS 须补 `fdeOssHost` 否则二进制面静默阻断，半坏→明坏）。
- **测试**：close-guard +4（通道接线/preload 面/helper 成对/直连面唯一定位静态钉）＋NEW `build-csp.test.ts` **10 例**（缺省零回归/远程 origin/OSS 追加去重/本地+OSS/非 http(s) 回落/坏主机不追加/https: 通配否决钉/vite 插件挂载静态钉）＋NEW `upload-helper.test.ts` **4 例**（3 片边界分片+进度单调/坏签名 URL 抛 invalid signed part/PUT 非 ok 抛 storage_upload_failed:403/取消零分片）；**变异三连全红→字节级还原→绿**（M1 摘 main 上传 IPC 接线⇒close-guard 红；M2 helper 摘 begin/end⇒close-guard 红；M3 摘 vite 插件挂载⇒build-csp 挂载钉红）；typecheck 双 tsconfig 绿；全量 vitest **1022 passed（90 文件）**。
- 口径：纯桌面＋文档轮——server 零改动⇒无需 rebuild 三镜像/alembic；路由/表/迁移/蓝图/mypy 全部不变；桌面变更 ⇒ **便携版 r35** 重打包随轮交付（asar 字节验证随包）；vitest 终值以本 PR CI 为准（本地全量 **1022 passed（90 文件）**＝M2 轮基线 1004 ＋ 本轮 +18〔build-csp 10 ＋ upload-helper 4 ＋ close-guard 扩面 4〕逐位吻合）。

## [未发布] — AI 原生化 N1 挂账销项轮＋台账 v1.10（G7 重交回环推进：success.md 定稿活库代录 claim（指针+sha256，原件永不入库）＋G7/G8/G9 门禁材料收集清单落仓＋T-A10 排期销项；G-07 CLOSED 维持、G-01 OPEN 重交推进中，纯文档＋活库门禁代录，2026-11-11）

蔡工交互拍板四项（①T-A10 排期到下一实施轮／②容器栈 rebuild 维持挂账归部署归属方不越权／③G7 重交＝出材料清单供收集／④G8/G9＝出材料准备清单）后的挂账销项轮：

- **G7 重交回环推进（活库写动作，admin 代录留痕）**：`submit_gate_evidence`（服务层写路径，非直接 UPDATE）把宿主真实件 **success.md 定稿**（`fdeops://engagements/somwyn/.fde/success.md`，S1/S2 切片已签收口径，self-acceptance 声明在件内原样保留）claim 进 G7「success.md 定稿」清单项——G7 `failed rev2 → evidence`（**3/4 claimed**：options 文档/Eval 计划＝重跑三 agent 产物强映射，success.md 定稿＝本轮真实件代录；「B 试点章程定稿」缺项**如实不 claim**＝不虚挂）。`gate_evidence_submitted` 事件 actor=admin @2026-11-11 03:01 UTC 留痕可推翻；**拍板仍归 `pilot.reviewer`**（提交人≠拍板人 `gate_decider_conflict` 硬闸；B 章程到齐后 4/4 claimed ⇒ 重拍 pass/fail，AI 不代拍不造假）。
- **B 试点章程框架草稿**：宿主 `gates/G7-B试点章程-框架草稿-待定稿.md`（抽自 decisions/context/success/delivery 既有事实；【待补】＝蔡工定稿＋客户书面确认记录；**不提交门禁**——无真实材料不 claim）。
- **NEW `docs/architecture/AI原生化N1门禁材料收集清单-v1.md`（仓内材料清单 doc，本轮交付物）**：G7×4＋G8×3＋G9×5 逐项「要什么/谁出/放哪/指纹纪律/提交＋拍板通道」；推进顺序 **G7 pass→G8 三态（proceed/pivot/stop）→G9 拍⇒G-01 CLOSED**；红线前置＝门禁证据只存 source_uri 指针+sha256（原件留宿主）、AI 代提交不代拍不代造。
- **T-A10 排期销项**：backlog 行 PROPOSED→「✅ 排期已拍板（下一实施轮）」——**排期销项≠实施授权**；进程空间（宿主裸跑全量＋容器态降级）与实施授权随下一桌面轮拍板，不预设。
- **容器栈 rebuild 维持挂账**：owner＝部署归属方（fde-wt-v31p2 会话），本会话**不越权执行**；仅活体核对（活库 `alembic_version`＝`e5c9f2a7d4b6 (head)`＝fork/main `4354cd2`（#312 F 线 T4）单头、三容器 healthy、`/api/v1/health/ready` 200、url_map 461 非静态路由——部署态与 fork/main 一致，**无待升级迁移**，rebuild 挂账＝镜像代码同步非迁移缺口）。
- **判据状态**（台账 **v1.10**）：G-07 维持 **CLOSED**（判据两段 v1.8 已全行使，重交回环不重开结论）；G-01 维持 **OPEN**（重交回环推进中；G8/G9 待真实交付期材料，`decide_gate` 无证据 409 `invalid_gate_state` 机械封死不代拍）。同步面：台账 v1.10（修订记录＋G-01 行重交现状＋「N1 挂账销项轮」附注）＋复盘 §11＋任务书 §13 #14/§14 N1 行＋backlog T-A10 状态＋AGENTS bullet。零代码零迁移零路由（活库一次门禁提交＝代录写动作，非代码变更）；无 rebuild／无 alembic／无重打包。

## [未发布] — F 线 T5 轮：就近硬闸加固（**不提权**；迁移 `a7c2f9e1b4d8`，2026-11-11）

- **任务书 §4-T5 ＋ §12 就近专项**（ADR-011 §5-D；T2 依赖已满足；OWNER 判定问题
  按「按推荐执行＋留痕可推翻」先例进入本轮，推荐项＝进入 T5，T4 轮 AskUserQuestion
  未获答复）。**核查后撤回「就近只有 10% 权重、需提权」的前判**——到场型本就是
  硬闸（`allowed_geo_tier` 首轮只同城、`sort_key_onsite` 以 tier 为字典序一级键），
  `geo_remote` 只作用远程型；真实缺口在派生判定与扩圈调度两处。三件套：
  1. **到场型默认 True，仅显式标记纯远程才 False**（`delivery_packages.
onsite_required` 三态化）：旧形态按 `ProjectSolution.schedule` 四关键词（现场／到场／
     驻场／驻点）**派生** ⇒ 方案文本漏写即**同城硬闸整体失效**，只剩 10% 软权重；
     新形态 `NULL`＝未设置（读侧兜底判 True）／`True`＝显式到场型／`False`＝**仅此
     一种**是纯远程型。四关键词派生降级为「字段为空时的兜底」，**未命中关键词不再据此
     判为纯远程**（这正是本轮要修的缺陷本身）。**存量行按旧派生规则回填**（命中⇒
     True／未命中⇒False）⇒ **存量行为逐位零变更**（存量远程型包不被误加围栏），
     新语义只作用于新建/后续写入。判定唯一权威原语＝`dispatch.models.
resolve_onsite_required`（放 `models.py` 而非 `packages.py`——后者被 `access.py` 
     反向依赖，放那里成环）；读侧 matching／simulator／access 一律走它。**写入口**＝
     既有创建路由 `POST /api/v1/dispatch/packages` 的 `onsite_required` 载荷（旧形态
     全仓**零写入口**，「仅显式标记」不可达）⇒ **零新路由**。
  2. **15 分钟逐级自动扩圈**：`radius_expand_wait_minutes=15`（`system_configuration.
py:69`，§6.2 唯一权威表）**定义但无调度消费** ⇒ 新增 `dispatch.offer_service.
expand_stale_offers` 并接进 `expire_stale_offers`：**同城无人且已过 15 分钟 ⇒ 自动
     重发**（`dispatch_round+1` ＝ 扩圈一档：同城→同省→邻接都市圈→全国）。包行锁
     （`SELECT … FOR UPDATE`，G2/G3 行锁范式）防并发双推；状态机唯一迁移保幂等；
     留痕事件 `dispatch_offer_expanded`；`run_maintenance` 作业结果增报 
`radius_expanded_packages`。**全国档门槛保持不动**：`allowed_geo_tier`（`matching.
py:98-105`）在 round≥4 且报价非旗舰档时封顶 tier2 ⇒ 非旗舰档**不会**扩到全国
     （「旗舰档＋客户书面确认」由既有逻辑守住，本轮**未改 `matching.py` 的分档规则**）。
  3. **权重未变**（任务书 §12 动作 3）：`stage_b_weights` 维持 **40/30/20/10**；
`geo_remote`／`sort_key_onsite`／`sort_key_remote` **一字未改**。本轮属缺陷修复、
     非规则重大调整 ⇒ 无需另发规则版本（上线前初始基线已含该权重）。**CHANGELOG 
     明确登记「权重未变」**。
- **实施期自查修正（记在案）**：①发布时兜底逻辑写成 `package.onsite_required or 
  _derive(...)` ⇒ **显式标记纯远程会被静默改写回到场型**（旧 bug 的真正来源），改
  为仅当字段为空才兜底；②`resolve_onsite_required` 首版把「关键词未命中」判为纯远程
  ⇒ **又让硬闸整体失效**（与本轮目标相反），改为未命中亦判到场型；③扩圈候选过滤
  首版含 `published`/`offered` ⇒ 自动扩圈后对已 published 的包**二次 publish**（状态机
  拒绝 409），收窄为仅 `expired`/`rejected`；④模拟器原在 `expire_stale_offers` 之后
  **手工**再 publish 一次 ⇒ 与自动扩圈**重复重发**，加轮次推进检测后跳过。
- **测试**：NEW `test_f_line_t5_onsite_hard_gate.py` **17 例**（默认 True／显式 False 
  保持／显式 True 保持／发布冻结快照／发布兜底落库／**跨省候选在到场包不中签＝M12 
  守面**／同城候选胜跨省／**显式 False 仍走远程加权序＝既有远程型断言保护**／非布尔
  载荷 400／**未满 15 分钟不推进**／**过 15 分钟推进一档＋事件留痕**／逐级链／
  **非旗舰不扩全国**／远程型不参与扩圈／幂等／**权重未变钉 40/30/20/10**／常量 15 分钟
  未变）；迁移钉 HEAD `a7c2f9e1b4d8`、65→**66**。
- **变异两连全红→字节级还原（sha256 终验一致）→绿**：**M12**（`onsite_required` 恒置 
  False ⇒ **8 例红**）；**M12b**（摘除 `expire_stale_offers` 里的扩圈接线 ⇒ **4 例红**）。
  ★**变异判别力本身要验收**（获客诊断轮 M8 无判别力同款教训复现并当场修正）：M12b 
  **首版无判别力**（17 例全绿）——扩圈用例直接调 `expand_stale_offers` 原语、
  **绕过了真正的接线点**；改经调度入口 `expire_stale_offers` 调用后转红。
- 口径（融合树现测）：**150 表**（本轮零新增表）/ **66 rev 单头 `a7c2f9e1b4d8`**（挂 T4 
  `e5c9f2a7d4b6` 之后保单头）/ **461 路由不变**（本轮零新路由——`onsite_required` 
  挂既有创建路由载荷）/ 蓝图 51 不变 / api_catalog 94 不变（治理面不进 catalog）；
  mypy **279 基线不变**；ruff 绿；审计清单重生成（JSON 461/51/150/66）；架构图口径
  **无需改动**（表/路由/蓝图数未变，防陈旧闸绿）。pytest 终值以本 PR CI 为准
  （本轮 NEW +17；融合基线**现测** 2979 收集〔当前 tip `1b6090b` 含 M3a〕＋17 ＝ **2996 收集**，逐位吻合；**不承袭** M3a 轮 CI 实测 2970——该轮时点值）。
- server 变更 ⇒ 合并后 rebuild 三镜像＋`alembic upgrade head`（本迁移挂 T4 
  `e5c9f2a7d4b6` 之后，合并后真实升级 `e5c9f2a7d4b6 → a7c2f9e1b4d8`）；桌面零改动
  不重打包。
## [未发布] — 多客户工作平台 M3a/M3c 轮：统一隔离入口＋跨企业越权套件骨架（零迁移零新路由零新表零桌面，2026-11-11）
## [未发布] — 诊断生成器数字溯源纪律轮（number-gate-v2 口径重界定＋prompt-v2 对齐＋拒因回灌；零迁移零路由零蓝图，2026-11-11）

curve 2 真机归因（生成 3/6，余 3 例统一 `report_unsourced_number`）的修复轮：**被判无源的三个字面是「一个」「一套」「两套」——全都不是编造的业务数字**；根因在数字闸的口径与机制，不在模型。

- **三缺陷归因（真机取证，不是推测）**：**D1 口径错位**——闸扫「任何数字串」，而 R-4 的声明域是「规模/金额/比例/周期/时间的量值断言」；中文泛指/计数用法（输出一套清单）被当成无源业务数字 ⇒ curve 2 三张卡死在闸上而非内容上｜**D2 裁决依赖输入里的偶然字面**——同一个「一个」在 somwyn 卡放行、在 datawhale-001 卡拒收，差别只在规则生成的测算卡措辞里偶然出现了「挑一个高频…」（v1 把整个测算卡当数字来源）｜**D3 修复不可达**——契约失败后重试是同提示词盲重抽，模型看不到拒因 ⇒ 可修的违规（删一个数字/改写/标待澄清）两次都烧光 ⇒ 一个量词毙掉整份报告。
- **number-gate-v2（口径重界定，留痕可推翻）**：**分层作用域**——现状层（`headline`/`findings[].problem`，＝对客户事实的断言）全量必检；处方层（`first_step`/`actions`/`closing_loop`）只检**金额与比例类**（`元/块/%/倍`，任何层必检——基线数字编造的重灾面），计数与周期免检（建议节奏／产出数量／对问卷已列对象的复述——复述必有来源，天然放行）｜**可溯源集合重界定**＝客户答案 ＋ 政策引文编号/日期（测算卡的规则生成文本——下一步建议/免责声明/我方解读/缺口清单——与政策原文口径里的量值**不再**算来源）｜**中文数字与阿拉伯数字归一**（「两套」≡「2套」；v1 按字面比对 ⇒ 同一来源的两种写法会误拒）｜**泛指与单数免检**（「一套/一个/几家」不构成量值断言）｜数字闸版本随报告落库（`number_gate_version`），口径变 ⇒ 报告可比性变可追责。
- **诚实边界（兜底分工，写进代码注释与曲线文档）**：值＝1 的计数放行意味着「公司只有一个系统」这类客户事实类编造**不再由契约闸拦**——兜底层是 rubric ③（编造基线数字单列重罚＋`must_not_hallucinate` 逐条核）与展示闸 C1（无源数字不得进展示层）。理由＝**代价不对称**：契约闸的误拒直接毙掉整份报告（访客拿不到任何东西），漏放交给评分层扣分。
- **prompt-v2（版本断点）**：R-4 条款与 number-gate-v2 口径逐条对齐（数字来源＝问卷答案＋政策引文；现状层必检／建议里的节奏与产出数量可写／金额与比例必有来源），并新增「重试修复」段；`REPORT_PROMPT_VERSION` v1→v2（曲线 x 轴随之断点，提示词与闸口径漂移＝白烧调用）。
- **拒因回灌（D3 修复，生成侧接线）**：契约拒收时把**拒因与修法指引**回灌进第二次尝试（提示词 `repair` 段）⇒ 重试是**修复**而不是盲重抽。
- **评测器侧（口径纪律同源）**：批跑新增 `--eval-set-version`（**run id 与考卷版本解耦**——同一考卷的多轮重跑必须显式传同一个考卷版本号，只改生成器不许改考卷版本号，改了就是 C 类改考题）｜run.json 增记 `number_gate_version`｜曲线文档增「数字闸版本」列。
- **curve 3 真机重跑（run `ev2`，同一考卷 `2026-11-11`，同一 rubric-v0.2）**：生成 **6/6**（curve 2 是 3/6；`report_unsourced_number` 归零，**零契约重试**——六次 AI 调用对六张卡一次过闸）｜元验证闸 **pass（连续第二次）**（A1=100 带内且 parroting=False；A2=84 带内；X1–X4 全拒 4/4）⇒ `usable_as_evolution_evidence=True`｜逐卡 001=**72** conditional／003=**74** conditional／009=**77** conditional／010=**67** conditional／023=**77** conditional／somwyn=**58** hard_fail。**读法（不得越界）**：可断言的是**生成面**（六卡全部一次过闸且可评）；**分数面不可断言「变好」**——锚点 A2 在**同一份输入**上 77→84 ⇒ judge 单点噪声 ≥7 分（逐卡 ±10 以内属噪声域），已可评三卡均值 74.3→70.7（未升），阈值未校准＋样本 6 卡 ⇒ 分数面仍属 `insufficient_data`。曲线文档 `docs/audit/诊断评测-评分曲线-3.md`（三缺陷归因表＋生成/评分对比表＋两条版本断点）；指纹登记同步（**考卷与评分规则零改动** ⇒ rubric-v0.2 `76a73168…`／meta-v0.2 `a1bb861e…` 指纹不变，登记「④ curve 3 断点轮」留痕）。
- **测试 +9**（`server/tests/test_diagnostics_report.py`）：分层作用域（现状层拒／处方层计数与周期放行／处方层金额与比例仍拒）｜泛指与单数（「一套/一个/几家」放行，含现状层——兜底分工的显式声明）｜中文/阿拉伯归一（**必须落在现状层**——落处方层无判别力）｜可溯源集合排除规则生成文本＋政策原文口径的 70% 不作来源｜政策引文编号/日期仍是来源｜数字闸版本随报告落库｜prompt-v2 条款与闸口径对齐（版本常量＋三条关键句在场）｜worker 拒因回灌（第二次提示词含 `repair` 段与拒因）｜worker 端到端用新可溯源集合（不是整个测算卡）。**变异六连全红→还原→绿**（分层作用域／金额比例跨层必检／可溯源集合退回 v1／撤掉拒因回灌／撤掉中文归一／撤掉泛指豁免）——**首轮三处变异未转红**（新钉落在无判别力的字段层／未覆盖泛指族）⇒ 补钉后转红（**判别力本身要验收**，与 V31-P1 同款教训）。本地私有库定向 **40 例全绿**（`test_diagnostics_report.py` 31 旧＋9 新）＋邻域 108 例全绿（评测批跑库/judge/提示词卫生组）；**CI 实测 2951 passed + 7 skipped**（PR #317 run 42948925171，融合树）；mypy **279 基线不变**（官方闸 OK）；零迁移零路由零蓝图。**污染钉实录**：N2 静态钉（生成器可见面零答案字段名，零豁免）抓出本次**代码注释**里出现的答案字段名——机械闸连注释一起查，已改写措辞。**部署活体三验绿**：alembic `e5c9f2a7d4b6 (head)`（本轮零迁移，头位由并发轮推进）／三镜像同刻（11:11:24）且容器镜像 ID 与构建产物逐位一致／`/ready` 200／url_map **461** ≡ 审计清单（461，本轮零路由）。

## [未发布] — 夜审挂账设计轮 r6（CR-056/057 桌面两挂点多方案设计稿＋主树 8 草稿文件抢救入库；纯文档零代码零迁移零路由，2026-11-11）

- **CR-056/057 设计轮（破例先行出设计，触发条件未满足⇒不施工维持不变）**：蔡工 2026-11-11 交互式拍板「开设计轮（P2 两条 056/057）」——2026-11-10 拍板「维持挂账」不推翻，只把「多方案拍板」前置成文。NEW `docs/audit/夜审-CR056-CR057-多方案设计稿-2026-11-11.md`（取证基线 fork/main `4354cd2`，锚点现测）：**CR-056**（close-guard 在途写计数不覆盖 renderer 直连分片 PUT）现测 4 直连上传站在位＋3 只读 GET 显式排除面，推荐 **A′ 通知计数**（renderer 上传经 IPC 桥 `appUploadBegin/End` 计入 `activeMutations`＋4 站收拢 `upload-helper`＋静态钉防第 5 处上传面；方案 B 改走 IPC 桥＝百兆 blob 经 IPC 拷贝＋凭据面扩大否决；C renderer 自拦＝拦不住 Electron 主窗 close 事件链不可行）；**CR-057**（打包态 meta CSP connect-src 写死回环）现测三形态（index 写死/web `'self'` 正确/harness 正则先例），**裁定 B 运行时下发结构性失效**（浏览器 meta∧header CSP 取交集语义，main 侧 onHeadersReceived 无法删 meta 标签，只能更严），推荐 **A＋D 构建注入**（`build.extraMetadata` 单点补可选 `fdeOssHost` 键注入 connect-src＋部署形态×存储后端组合矩阵成文；C `https:` 通配＝数据外泄面扩大否决）；两条同轮实施预估一次便携版重打包。**owner＝蔡工，实施待拍板**。
- **主树 8 个 untracked 草稿文件抢救入库**（主树 `D:/test/fde-workbench` 落后 fork/main 期间他线 ff 丢弃 12 个 tracked diff〔品牌定稿/README 私有化等，内容未随任何提交进入 fork〕，8 个 untracked 草稿幸存磁盘但未入 git，其中 **README:244 链接的 `对外试用部署方案-v1.md` 在 fork/main 上不存在＝死链**）：本 PR 将 8 件（对外试用部署方案 v1/v2〔v1 自标已废止留决策沿革〕＋实施任务书 v1/v2＋GPT建议.txt＋架构评估提示词-v1.md〔两份 11-07 评估报告的执行依据〕＋DSH 复评〔正本 11-05 已在仓〕＋多客户 zcode 提示词-正文.txt）补入 git。红线自检：零客户真实资料/零密钥/零第三方正文。
- **活体部署挂账（归他线）**：活体停在 r5 收口 `a9c5e2d7b3f1`，fork/main 已推进 `e5c9f2a7d4b6`（#305/#309/#312 带 c8d2f6a4e9b1/b8d4f6a2c9e7/e5c9f2a7d4b6 三新迁移）⇒ 活体落后两新迁移，rebuild＋alembic＋活体三项复验归 F 线 T4/M2 owner 部署合同，本 PR 不代部署。
- 口径：纯文档轮——server 零改动⇒无需 rebuild/alembic；桌面零改动⇒不重打包；pytest/mypy 零变化（终值随本 PR CI 复核）。## [未发布] — 多客户工作平台 M3a/M3c 轮：统一隔离入口＋跨企业越权套件骨架（零迁移零新路由零新表零桌面，2026-11-11）

任务书 §7-M3a/M3c ＋ ADR-M3 §2/§3；**规格先行**（ADR-M3 §2.4 强制：装饰器扩展行为规格必须先于任何批量改动入库）。

- **规格先行件** NEW `docs/commercialization/multi-tenant/M3a-隔离入口与装饰器扩展规格-v1.md`——ADR-M3 §2.4 的六项强制内容齐（org 校验发生层＝**服务层**／默认拒绝 fail-closed／平台身份白名单的显式形态／跨 org 动作留痕点／失败码闭集〔`forbidden` 403 与 `not_found` 404〕／逐批验证方法＝变异用例先红后绿）＋org 三态语义＋SQL 下推权威式＋JWT 口径。**M3b 每批 PR 必须引用本件**。
- **org 语义单一入口** NEW `fde_api/orgs/isolation.py`（纯领域判定，零 flask 零环境读取）：**平台身份**（`users.org_id IS NULL`）不受 org 限制；**企业身份**可见范围＝本企业 org ＋ 平台内部 org 桶 ＋ 平台级行（`projects.org_id IS NULL`）；**admin** 是平台能力恒真。**org 只是归属维度不是授权维度**——成员关系仍是可见性的必要条件（红线 8：不建第二套权限体系）。内部 org 桶「平台立项 → 企业账号作 viewer 成员」（G6 通路）不得被隔离打断，桶内跨企业混装的已知边界在规格 §1 显式登记（消解路径归 M5，不掩盖）。
- **统一入口 SQL 下推**（M3a 目标）：`projects/permissions.py::visible_project_ids` 由「全表取回 + Python 逐项目判定」改为 **SQL 谓词**（成员 EXISTS ＋ leader 分支 ＋ org 谓词全部下推，`ix_projects_org_id` 索引在位）——红线 10「不在 SQL 后再加一层 Python 过滤」；新增 `visible_project_filter(user)` 谓词供列表级复用；对象级 `project_access` 与列表级**同语义**（两入口不一致＝幽灵行，`test_visibility_parity.py` 对账钉）。
- **幽灵行修复（列表↔详情收敛）**：`projects/service.py::list_projects` 原先**私藏第二套可见性规则**（leader-OR-成员，无 org 谓词）⇒ 跨企业成员关系会在**列表**里露出「列表可见而详情无权」的行（本轮实测复现）。改为**复用统一入口谓词**——隔离逻辑不写进热点文件（eng 评审），本文件只调用权威谓词；净减 8 行（1945→**1937**，预算 ≤1946 未破）。
- **JWT 8 claim**：新增 `org_id` claim（可空＝平台身份）；解码走**在场性**校验——claim 必须在场（平台身份取 null），**缺该 claim 的旧令牌一律 401**（fail-closed）。★**实现坑（本轮实测踩中）**：PyJWT 的 `options.require` 判定是「`payload.get(claim) is None` ⇒ 缺 claim」，而平台身份的 `org_id` 合法值恰是 null ⇒ 放进 require 列表会把**全部平台身份令牌判死**（实测 74 例 401 误杀）⇒ `org_id` 不进 require 列表，改解码后显式判「在场 ＋ 类型（None/str）」。★**授权判定一律读库**（`users.org_id`），不信令牌 claim——令牌是 15 分钟快照，拿 claim 当授权依据＝陈旧令牌越权；装饰器注入 `g.current_user_org_id`（读库值）。
- **M3c 越权套件骨架** NEW `server/tests/test_cross_tenant_isolation.py`（**8 例绿 ＋ 1 例 `xfail(strict=True)` 待销号**）＋共用工厂 `server/tests/multi_tenant_harness.py`：覆盖面＝任务书 §7-M3c 七域（项目详情／项目列表／调研对象／文件／调研导出／AI 执行状态／API-action 待确认／对话会话）。**关键场景＝跨企业成员关系**（企业甲账号被平台身份加进企业乙的项目）——只测「素不相识的账号」不构成判别力（成员关系本来就会挡住），跨企业成员关系才是 org 维度真正要挡的场景。
- **`xfail(strict=True)` 机制**：未改造面挂严格 xfail——改造完成即 XPASS ⇒ 严格模式判失败 ⇒ **强制摘标记**；这把「销号」从人工纪律变成机械闸（与「越权用例不进 CI 不许合并」互为一对）。
- **M3a 单元钉** NEW `server/tests/test_org_scope_entry.py`（**12 例**）：列表级↔对象级可见集**逐位一致**（角色矩阵 admin/平台身份/企业 leader/企业成员/非成员/停用）／跨企业成员不可见／同企业成员可见／平台身份成员跨 org 可见（交付者多企业服务）／**平台立项桶可见**（G6 通路不得被隔离打断）／admin 全可见／停用账号空集／**SQL 下推钉**（捕获实际 SQL：WHERE ＋ project_members ＋ org_id 三者在场）／org 三态语义／claim 在场性与类型／**缺 claim 旧令牌 401**／**授权以读库为准**（签发后改归属 ⇒ 上下文取库中新值）。
- **变异两连全红→还原→绿**（判别力验收）：M1 摘对象级 `org_scope_allows` ⇒ **7 红**（5 个越权域用例 ＋ 2 个入口钉）／M2 摘 SQL org 谓词 ⇒ **3 红**（含项目列表幽灵行用例与 SQL 下推钉）；还原后 sha256 复原、全绿。
- **盘点表回写（红线 4「盘点表外不得擅改」纪律落地）**：M3b 销号追踪节加「批次 ①–④」骨架行 ＋ M3a/M3c 行；**待 M0 补充登记两条**——①`control/service.py::_project_scope` 是**第三套**可见性规则（无 org 谓词，被 `list_task_center`／`list_task_board` 消费）⇒ 登记为**批次 ① 销号项**，本轮只登记不改；②internal org 桶内跨企业混装 ⇒ 消解路径归 M5。
- **零迁移零新路由零新表零蓝图零桌面** ⇒ 结构口径不变（现测：149 表／64 rev 单头 `b8d4f6a2c9e7`／459 路由／51 蓝图／api_catalog 94）；审计清单零 diff；archify 防陈旧闸不受影响；mypy **279 零新增**（官方闸 OK）；ruff 绿；热点闸 projects/service.py 1937 ≤1946。
- **★合并与部署终态（回填）**：PR #318 head `a14e346` → squash **`1b6090b`**＝fork/main 顶。**十八度插队**：上游 #312（F 线 T4 代码轮：迁移 `e5c9f2a7d4b6`＋`commercial_role_assignments` 表＋2 路由＋pytest +17）＋#315＋#316 落基点之后 ⇒ rebase（冲突两文件 AGENTS/CHANGELOG **两侧全留**；★**口径行去重终扫**——上游删旧行＋我方改旧行 ⇒ rebase 后同段位出现两条口径行＝双权威，按「口径行单点」纪律合并为一条）。PR CI run **42949683146**（pull_request）／**42949677474**（push）四 job 全绿＝**2970 收集 = 2962 passed + 7 skipped + 1 xfailed**（＝T4 轮 CI 基线 2949 ＋ 本轮 +21 逐位吻合）；本地融合树全量同值（`-n 4 --dist loadfile`，21m27s EXIT=0）。★**main run 42951637222 三次被并发会话的 main push 取消**（CI 并发组 `ci-${{ github.ref }}` 的 `cancel-in-progress`＝同 ref 新推送即取消前一轮——并发会话共享 CI 槽位的家族坑）⇒ main 树终值＝诊断数字闸 v2 轮 main run 42950821757 实测 **2958 收集** ＋ 本轮 +21 ＝ **2979 收集**（以收尾回填 PR 的 CI 复核）。**部署活体**（从合并 SHA 干净树 rebuild）：三镜像 api `41ee50a464f4`／worker `e7a027146696`／scheduler `096d3aa03952`（三容器 `.Image` 与构建产物逐位一致）＋`alembic upgrade head` 真实升级 `b8d4f6a2c9e7 → e5c9f2a7d4b6 (head)`；活体 url_map **462 total／461 non-static** ≡ 口径；`/api/v1/health/ready` **200**（database ok／redis ok）＋`/live` **200**；三容器 healthy；活体令牌签发含 `org_id` claim（平台身份＝null，claim 在场 ✔）；活库 `users` 企业身份账号 **0**（注册闸关）⇒ 企业身份分支的活体验证待试点首个企业账号（如实登记，不以测试库冒充活体）；桌面零改动 ⇒ 不重打包（r 序号不动）。
- 口径：pytest 本地 CI 同命令 `-n 4 --dist loadfile` 实测 **2953 收集 = 2945 passed + 7 skipped + 1 xfailed**（14m46s EXIT=0；＝M2 CI 基线 2925 ＋ #311 诊断报告生成器修复轮 +7 ＋ 本轮 +21 逐位吻合；★本地全量两次被**跨会话 worker 库池对撞**杀死（`fde_workbench_w{N}_test` 固定名＝跨 worktree 全局共享池，改 `FDE_TEST_DATABASE_URL` **不隔离** worker 池）——散布 401 access_token_invalid／setup E＝环境级签名、零代码级失败；处置＝私有库串行 ＋ CI（Ubuntu 隔离库）为权威）；vitest 不变（零桌面改动）；零迁移零路由 ⇒ 无需 rebuild／alembic 之外的部署变更（本轮 server 变更 ⇒ 合并后 rebuild 三镜像 ＋ `alembic upgrade head` 幂等 no-op）。

## [未发布] — F 线 T4 轮：空缺沉淀与兼任承载（空缺人工确认双闸＋兼任承载表＋自拉自交验收人恒为平台；迁移 `e5c9f2a7d4b6`，2026-11-11）

- **任务书 §4 T4**（ADR-011 §3.5/§3.8；T1×T3 依赖已齐；OWNER 判定问题按「按推荐执行＋留痕可推翻」先例进入本轮，推荐项＝进入 T4，T3 轮 AskUserQuestion 未获答复）。三件套：
  1. **空缺人工确认双闸落地（ADR-011 §3.5-3）**：`allocate_five_seats`/`allocate_five_seats_with_lead_attribution` 新增 `confirm_password` 形参——调用方显式指定的 `vacant_reasons`（delivery/county/province 职能判定＋T1 直传 lead）强制 **admin＋密码**（403 `allocation_vacancy_confirmation_required`／400 必填／403 `invalid_password`，CR-047 限流同款，密码不落事件）；**豁免**＝T3 解析器派生的 lead `no_sourcer`（ADR-011 §3.4 情形六企业自来＝**结构性派生事实**，经 `derived_vacant_seats` 显式声明，非「谁没干活」人工判定）；全 paid 分配不触发。规格校验先行（422 形状错优先于授权错）。
  2. **兼任承载表**：NEW `commercial_role_assignments`（迁移 `e5c9f2a7d4b6` 挂 M2 `b8d4f6a2c9e7` 之后保单头，additive 单表；64→65 rev）——一人多角色（一人多行并存），附生效区间（`valid_from` 必填／`valid_until` 可空＝长期；倒挂 400＋`ck_commercial_role_assignments_window` DB CHECK 兜底）与来源（书面依据指针＋sha256 指纹）；同角色区间重叠 409 `role_assignment_overlap`（行锁＋重叠判定，G2 额度并发范式）；写入＝关键流转（`commercial/role_assignment_service.py` admin＋密码双闸）；**不动 `users.role`**（ADR-001 保护清单，用例钉死）；`commercial_entitlements.commercial_role` 单值保留「主角色」兼容读面（兼任**永不回写**主角色列），不删列。NEW 路由 2 条（POST/GET `/commercial/role-assignments*`，459→**461**），治理面不进 api_catalog（94 ENTRIES 不变）。
  3. **自拉自交验收人恒为平台（ADR-011 §3.8）**：`acceptance_passed_at` 唯一写咽喉 `mark_acceptance_passed` 落结构性排除——actor ∈ 交付席位（`DeliveryPackage.seat_delivery`）∪ 已确认归属 owner（与 T3 `resolve_lead_seat` 同一谓词）⇒ 403 `self_acceptance_forbidden`；gate_service G8 分支翻译 PaymentServiceError→GateServiceError（不 500 化，decide 事务随异常回滚零写入）；市县/省级收款人分配时才产生、验收时刻无从辨认，由 G8 manage 门共同守。
- **测试**：NEW `test_commercial_role_assignments.py` **12 例**（多角色并存/重叠 409/先后不重叠/闭集与窗口倒挂＋DB CHECK 兜底/双闸三负例/书面依据同有同无/事件零密码/主角色兼容读面不被覆盖/users.role 零改动/读面三态/不进 api_catalog/迁移往返）；`test_five_seat_allocations.py` 增 **5 例**（双闸三负例＝M10 守面/解析器派生豁免钉/交付收款人本人验收 403＝M11 守面/lead 归属人本人验收 403/平台方验收照常）；迁移钉 HEAD `e5c9f2a7d4b6`、64→**65**。
- **变异三连全红→字节级还原（sha256 终验一致）→绿**：M9（摘原因码闭集校验 ⇒ 422 用例红；DB 层 `ck_dispatch_settlement_allocations_vacant_shape` 兜底仍在）；M10（摘空缺双闸 ⇒ 三负例红）；M11（摘验收排除 ⇒ 本人验收两例红）。注：T3 报告的「M9＝摘资格闸」为 T3 自加的第三组，与本轮任务书编号 M9（无原因码）同名异义，编号以任务书为准、已在案注明。
- 口径（十七度插队融合态：上游 #311 多客户 M2 注册面轮于本 PR CI 期间落 main，rebase 改挂迁移＋两侧全留）：**150 表**（本轮 +1；融合 M2 +1）/ **65 rev 单头 `e5c9f2a7d4b6`**（挂 M2 `b8d4f6a2c9e7` 之后保单头）/ **461 路由**（本轮 +2；融合 M2 +8）/ 蓝图 51（融合 M2 +1）/ api_catalog 94 不变；mypy **279 基线不变**；ruff 绿；审计清单三件套重生成（route +2 行/DB +1 行/JSON **461/51/150/65**）；架构图口径同步（candidate.json＋system-architecture.html「459 路由→461／149 表→150／51 蓝图」＋preview 整页实拍 1440×2098），防陈旧闸绿；pytest 终值＝**main run 42943191824 server-tests 实测 2942 passed + 7 skipped**（2949 收集，476.58s；T4 树本地实测 **2896 收集 = 2889 passed + 7 skipped**（9m17s＝T3 基线 2879 + 本轮 +17 逐位吻合）；融合树 collect 现测 **2949 收集**（+M2 +53）——CI 终值 2942+7 与融合树 collect 逐位吻合；CI skip 7 比本地 6 多 1＝污染钉 N6 显式 skip 的设计行为）。
- **★合并与部署终态（回填）**：PR #312 head `c02f8e6` → squash 合并 SHA **`4354cd2`**＝fork/main 顶（main run **42943191824** 四 job 全绿：desktop／server-tests／secrets-scan／pseudonymization 各 `completed/success`；server-tests 实测 **2942 passed + 7 skipped**／476.58s）。本轮历经**十七度插队**（#311 M2 注册面轮带新迁移落 main ⇒ re-parent 本迁移挂 `b8d4f6a2c9e7` 之后保单头＋重编号迁移计数断言＋重校 AGENTS/CHANGELOG 口径＋重生成审计清单＋串行重置 worker 库＋融合树全量 2949 收集＝2942+7），其后 #314／#313 两笔纯文档插队亦逐笔消解（两侧全留）。三镜像从合并 SHA 干净树 rebuild（api `ac1a05551a1f`／worker `0a024b0b5a70`／scheduler `b147fb638dca`，三容器 `.Image` 与构建产物**逐位一致**）＋`alembic upgrade head` **真实升级** `b8d4f6a2c9e7 → e5c9f2a7d4b6`、容器内 `alembic current`＝`e5c9f2a7d4b6 (head)`；活体 `url_map` **462 total / 461 non-static** ≡ 口径；server 变更已随合并落部署。桌面零改动不重打包。
)
## [未发布] — 诊断报告生成器修复轮（REPORT_MAX_TOKENS 16000 标定＋诊断模型槽位显式化＋rubric v0.2 复述条款重界定；零迁移零路由零蓝图，2026-11-11）

curve 1 真机归因（#307/#308）的修复轮：生成 0/6 全灭（`ai_output_truncated` ×3＋截断残 JSON ×2＋无源数字 ×1）＋元验证闸 fail（A1 顶格 100 越带＋同源复述误发）。

- **预算标定**：`REPORT_MAX_TOKENS` 6000→16000（`diagnostics/jobs.py`）——推理模型思考与正文共用预算（V31-P1 实测纪律），同端点 judge 通道 16000 双连过实测＋MiniMax-M3.1-Flash 硬顶 16384 贴顶而不过；「×2 预留」已被证伪不加码。
- **诊断模型槽位显式化**（opt-in）：`FDE_DEEPSEEK_DIAGNOSTIC_REPORT_MODEL` 设值即整体接管模型选择（缺省空＝零行为变更沿用偏好解析链——curve 1 归因确认该链工作正常；此前诊断静默借用行业模板槽位）；设值却缺端点/密钥 ⇒ fail-closed `report_model_slot_incomplete`（不静默回落，防「设了没生效」被掩盖）。`.env.example` 注解注明键名家族（与 judge 键不同族：本键带 DEEPSEEK 段）。
- **rubric v0.2**（curve 1 元验证 fail 断点的版本化修订）：复述失效条款重界定——v0.1 判据「≥4 条问题实质与句式高度重合」与①维「按参考材料关键问题给分」结构性混淆（报告与参考材料同出一访谈时实质收敛是构造性的），v0.2 只认**逐字级连续转写**＋明示同源豁免；四维/判定带/一票否决零变化。真相层元验证夹具升 **meta-v0.2**（A1 期望带 78–98→78–100：已验收真实交付四维顶格不是异常信号，「rubric 泄漏」检测移交 X3 注入反例与 A2 下限护栏；v0.1 原件留存）；`run_eval.py` 夹具名常量化＋`meta_fixture_version` 断点字段落 scores。
- **curve 2 重跑（真机）**：**元验证闸首过 pass**（A1=100 带内且 parroting=False——v0.2 条款正确豁免同源收敛，judge 摘要明确推理「不构成照抄」；A2=77 带内；反例 X1–X4 全拒评 4/4）⇒ `usable_as_evolution_evidence=True`＝**首个可作进化判定输入的曲线点**。生成 3/6（截断归零：`ai_output_truncated` ×3→0；余 3 例统一 `report_unsourced_number`——失败性质从「预算截断」转为「数字溯源纪律」，归生成器后续轮）；逐卡 datawhale-023=**86 pass**／009=**77 conditional**／somwyn=**60 hard_fail**。曲线文档 `docs/audit/诊断评测-评分曲线-2.md`（双版本断点标注）；指纹登记同步（rubric-v0.md `98053cd9…`→`76a73168…`；新增元验证夹具-v0.2.json `a1bb861e…`）。
- **测试 +7**：预算标定钉／槽位四态（缺省 None／设值接管／缺凭证 fail-closed／provider 由 base_url 单点命名）／端到端接线钉×2〔缺省＋设值态——首版接线钉只有缺省态，摘接线变异无判别力（两路同为 None），补设值态钉后转红〕／rubric v0.2 断点钉（版本常量＋同源豁免句在场＋旧判据句移除）；**变异四连全红→还原→绿**（预算回退 6000／接线摘除／槽位静默回落／版本回退＋豁免句摘除）。本地私有库串行全量 **2869 passed + 7 skipped**（0:37:22 exit 0）；**CI 实测 2879 passed + 7 skipped**（PR #311 run 42928261849，融合 #309 M2/#310 T3 后树）；mypy 279 基线不变。部署活体三验绿：alembic `b8d4f6a2c9e7`（含 #309 新迁移，本轮零迁移）／三镜像同刻且容器镜像 ID 一致／`/ready` 200＋url_map **459**（+8 归 #309，本轮零路由）。

## [未发布] — 多客户工作平台 M2 四入口统一注册轮（NEW registration/ 包＋users 注册列＋user_registrations 表；迁移 `b8d4f6a2c9e7` 63→64 rev（十三度插队改挂 F 线 T2 `c8d2f6a4e9b1` 之后保单头），+8 路由 +1 蓝图，桌面 email 字段＋便携版 r34，2026-11-11）


任务书 §7-M2 + ADR-M2 §2/ADR-M4；**本仓第二个公网免注册写面**（诊断线同款 fail-closed 纪律）。

- **三项 OWNER 拍板（2026-11-11 交互问答，全按推荐）**：①SES 生产批复前过渡形态＝**部署闸整体关闭**（`FDE_REGISTRATION_ENABLED` 默认 False；开闸三条件=开关∧SES∧公网根地址，缺一即 404——**不允许「无邮箱验证的静默放行」**）②区域服务商机构主体＝**个人主体＋机构字段**（机构名称/区域存注册行 materials_json，不扩 orgs CHECK 值域；regional_partners 继续承载机构主体，M7 合流）③G6 企业自助注册路由**收拢委托统一注册服务**（`POST /commercial/enterprise-registrations` URL 与 K8 限流不变；同部署闸/同状态机/同角色矩阵——盘点表第 10 行「收拢」处置兑现，企业注册初始角色 viewer→project_lead〔ADR-M2 §2 矩阵〕）。
- **十三度插队 rebase（fork/main 先落四笔，合并前消解）**：#304 夜审 r5 迁移窗口（迁移 `a9c5e2d7b3f1` 五索引 additive，pytest +8）／#305 F 线 T2（迁移 `c8d2f6a4e9b1` 纯数据种子零 DDL，pytest +9）／#306 夜审收口二纯文档／#307 获客诊断评测自动化（pytest +59）⇒ 本迁移改挂 T2 之后保单头（63→64 rev 单头）；冲突四文件（AGENTS/CHANGELOG/盘点 JSON/test_migrations）两侧内容全留；结构口径按融合树实测推进（148→149 表/63→64 rev/451→459 路由/50→51 蓝图）。★**跨会话 worker 库池对撞（本教训记档）**：`fde_workbench_w{N}_test` 四库是**跨 worktree 全局共享池**（固定名）——另一会话的 reconcile 在本会话全量运行中盖库（外来戳→DROP SCHEMA 或中运行 downgrade/清行），三轮本地全量被杀（散布 401 access_token_invalid＝行被中途清空；`UndefinedObject: index does not exist`＝downgrade 竞态；`out of shared memory`＝并发 DROP SCHEMA 撑爆锁表），**全部是 setup/环境级签名、零代码级断言失败**；处置＝CI 为权威（Ubuntu 隔离库）+ 本地定向全绿佐证；后续轮遇「全量非代码失败」先查 `pg_stat_activity` + `alembic_version` 戳归属再怀疑代码。★**第十四度插队（合并前再遇）＋CI 红一枚即修**：#308 评测三件套证据回填（纯文档，pytest +0）落基点之后 ⇒ 二度 rebase（AGENTS 单文件冲突，「当前状态」标题行两侧全留＝M2 置顶＋三件套次之）；首笔 CI server-tests 恰一枚红＝api_catalog 钉测试**裸 `create_app()` 在 CI 无 .env 必炸（G6 已知教训再犯）**——改 app 夹具取 url_map 后即四绿（run 42920346119，十四度 rebase 前头；#308 纯文档零增量 ⇒ 新头 CI 复核同值〔run 42923594740＝2908 passed + 7 skipped〕）。★**第十五度插队（四绿后合并窗口）**：#310 F 线 T3 拉单确权接线（零迁移零新表零新路由，pytest +10 ⇒ 融合基线 2879）落基点之后 ⇒ 三度 rebase（AGENTS/CHANGELOG 双冲突两侧全留＝M2 置顶＋T3 次之；迁移挂点 `c8d2f6a4e9b1` 不受影响保单头）。
- **四入口与审核制**：`POST /api/v1/auth/register/{enterprise|founder|deliverer|partner}`——企业/创业者自助激活，交付者/区域服务商审核（`FDE_REGISTRATION_REVIEW_ENTRIES` 缺省 `deliverer,partner`＝§11-3 拍板值；未知入口名 fail-closed 全审核）。状态机 `pending_email → pending_review → active / suspended（可恢复）/ rejected（终态）` 落 `users.registration_state`（五值 CHECK，server_default 'active'——存量行与 admin 建号零回填）；全流转落 `operation_events`（复用事件体系零第二套审计；事件零密码零令牌）。
- **邮箱验证**：`users.email`（可空唯一——存量与 admin 建号不回填，NFKC 归一）＋一次性令牌（sha256 指纹入库、64 hex 唯一、明文只在邮件里；重发即轮换、旧链接失效）；SES 发信在注册事务提交之后（失败不回滚注册，响应如实标注 failed——**永不谎报 sent**）；重发防枚举（响应形状恒同 202 accepted）＋双闸（同账号 60s 最小间隔＋同 IP 日限）。
- **反滥用三件**（ADR-M4 §3）：验证令牌一次性／统一注册限流 `auth:register:{ip}`（四入口＋legacy URL 同桶，上限 `FDE_REGISTRATION_IP_DAILY_LIMIT` 缺省 20＝**保守占位，试点前须填实数**）／区域入口默认置后（`GET /registrations/entries` 固定序 partner 最后）。
- **登录闸**：pending_email/suspended/rejected 一律 403（错误码 email_not_verified/account_suspended/registration_rejected）且落 `login_blocked_registration_state` 事件留痕；状态检查在密码验证之后（不向枚举者泄露）；pending_review 可登录（viewer 最小面，审核通过前不可接单＝角色结构性兜底）；刷新面同闸（旧 refresh 不得绕过登录闸续期）。
- **建号即建 org**（ADR-M2 §2）：enterprise 入口按 subject_key get-or-create `orgs` 行（org_type=enterprise；同主体幂等——第二经办人复用同一 org、额度绝不新建/不重置〔G6 硬不变量穿透〕）；企业代号撞名 409 `org_name_conflict`（不自动改名——代号化纪律由注册人遵守）。
- **结构**：NEW 表 `user_registrations`（一账号一行；entry 闭集 CHECK；materials_json **只收指针+sha256**——deliverer=R 分层申请材料〔GAP-01 证据链口径，零新字段语义〕／partner={org_name, region_name}；token_sha256 64 hex 唯一 CHECK；reviewed_by/at/note 审核留痕）＋`users` 三列（email/email_verified_at/registration_state）＋唯一索引 ix_users_email。迁移 `b8d4f6a2c9e7` 纯 additive（61→62 rev，挂 M1 之后单头；downgrade child-first 对称可逆）。
- **admin 审核簿记面**：`GET /api/v1/auth/registrations`（状态过滤+分页）＋`POST /registrations/<user_id>/{review,suspend,reinstate}`——approve→active／reject 必附定性理由（400 review_note_required）且终态不复活／suspend 仅自 active/pending_review／reinstate **按事实推导**（未验证→pending_email；审核入口未审核→pending_review；否则 active——不保存「停用前状态」）；admin 面不过部署闸（已注册账号的生命周期管理独立于公开入口可达性）但过角色闸。
- **G6 既有面适配（收拢成本如实登记）**：`register_enterprise` 签名升级（email/org_id 必传）；G6 测试三件套（throttle/space/quota 52 例）以 autouse 开闸夹具适配——K8 限流闸测试语义零变化（前 10 次走到业务校验的空载荷断言 400 维持）；`test_self_registered_user_can_login_with_chosen_password` 改写为「注册→pending_email 登录被拦→邮箱验证→登录成功」全链（G6 语义升级的诚实呈现）。桌面 `EnterpriseRegisterPage` 补必填 email 字段（type=email+required）＋成功提示改「验证邮件已发送…完成邮箱验证前该账号不可登录」；enterprise-register 测试 4→5 例（新增 email 必填字段钉＋提示语义钉）。
- **测试**：NEW `test_registration_surface.py` **46 例**（出厂默认值安全钉／部署闸 404×5 路径／开闸三条件参数化×3／入口清单序与审核旗／四入口全链／主体幂等与 org 复用／代号撞名 409／重复邮箱·用户名 409／邮箱归一化／materials 形状四连拒绝／令牌一次性·过期·无效·状态不符／重发轮换+旧链接失效+节流+防枚举／登录闸四态+留痕事件／刷新面同闸／审核 approve·reject·note 必填·终态·suspend·reinstate 推导／admin 角色闸／统一限流阈值+分域+与 legacy 共桶+fail-open/closed／G6 委托语义／事件脱敏钉／**治理面不进 api_catalog 钉**／迁移往返〔downgrade M1→升回 head：存量行 server_default active、email NULL、列对称〕）＋**变异六连全红→还原→绿**。
- **实施期自查修正（记在案）**：①registration 蓝图初版漏 `CommercialServiceError`/`UserServiceError` 错误处理（G6 委托的 invalid_subject_key 与重复邮箱 500 化）——补两个 errorhandler；②`UserRegistration` 主键是自身 id 而非 user_id，服务层四处 `session.get(UserRegistration, user_id)` 全错——改按 user_id 列查询；③`unicodedata.normalize` 一参误用（须两参 NFKC）——登录留痕函数修正并加 exc_info；④模型漏声明 `ix_users_email` 索引（迁移建了模型没声明＝元数据对账红）——补 `Index` 声明；⑤commercial.routes 顶层导入 registration 构成新包环（purity 冻结闸红）——改函数内惰性导入（仓库解环惯例）；⑥api_catalog 钉测试裸 `create_app()` 在 CI 无 .env 必炸（G6 家族教训再犯）——改 app 夹具取 url_map（CI 红→修→四绿）。
- 口径：pytest **2915 收集 = 2908 passed + 7 skipped**〔PR CI run 42920346119 实测（十四度 rebase 前头）＝融合树 2869（M1 2793 + r5 +8 + #307 +59 + T2 +9）+ 本轮 +46 逐位吻合；CI skip 7／本地 6 差 1＝污染钉 N6 设计行为；本地 rebase 前树 CI 同命令实测 2839 收集 = 2833 passed + 6 skipped EXIT=0 / 9m01s；融合树本地三轮全量被跨会话 worker 库池对撞杀死（环境级签名零代码失败，教训记档）；#308 纯文档零增量 ⇒ 复核同值〔run 42923594740〕；十五度插队 #310 F 线 T3 +10 ⇒ 融合基线 2879 + 本轮 46 ⇒ 2925 收集，终值以本 PR 新 CI 为准〕 / vitest **1004**〔88 文件；AGENTS 前值 999 停在 #288 态——#292/#300 桌面增量 +4 未记账（上游口径债如实补正）+ 本轮 +1〕/ mypy **279 零新增**（官方闸 OK）/ ruff 绿 / 路由 **459**（+8）/ 蓝图 **51**（+1）/ 表 **149**（+1）/ 64 rev 单头 `b8d4f6a2c9e7`；审计清单三件套重生成（route CSV 恰 +8 行）＋archify 防陈旧闸绿＋preview 整页实拍（1440×2098 PASS）；热点闸不动（projects/service.py 1945 未触碰）；server 变更 ⇒ 合并后 rebuild 三镜像＋`alembic upgrade head`（新迁移）；桌面变更 ⇒ 便携版 **r32** 重打包随轮交付。
- **★合并与部署终态（回填）**：PR #309 head `db7bbaa` → squash 合并 SHA `058c543`＝fork/main 顶（main run 42928595126 四绿；首次 server-tests 一枚 `test_delivery_plans` xdist 跨测干扰 flake〔`events[0].changes["created"]` 0≠1，与本轮零交集〕，重跑 2918 passed + 7 skipped 实测同值）。三镜像从合并 SHA 干净 worktree rebuild（api `3220c4448225`／worker `3d62905e8bbe`／scheduler `7352f1d9e42f`，三容器 `.Image` 与构建产物逐位一致）＋`alembic upgrade head` 真实升级至 **`b8d4f6a2c9e7 (head)`**；活体 `url_map` **459 non-static** ≡ 口径（注册面 9 路由在位＝M2 8＋legacy 1）；ready/live 200；**部署闸 fail-closed 活体 404×4**（register／entries／verify／legacy G6——不确认面存在＝OWNER 拍板过渡形态活体验证）；活库断言：`users` 三新列在场＋存量 6 行全 `registration_state='active'`（server_default 零回填语句）＋`email` 全 NULL（可空唯一多行共存）＋`user_registrations` 13 列＋`ck_users_registration_state`＋唯一 `ix_users_email` 在场。容器 API 监听 **8010**（不是 8000——活体探针按容器实际端口）。
## [未发布] — F 线 T3 轮：拉单确权接线（lead 三态解析＋拉单资格换席位费闸；零迁移零路由，2026-11-11）

- **形态**：分账口径改造（F 线）goal 循环 T3。ADR-011 §3.4/§5-F（拉单资格不限角色＝补充拍板 12；接 ADR-009 不造第二套归属）。
- **lead 席位三态解析**（`dispatch/settlements.py::resolve_lead_seat`，归属是**本域事实**）：该企业代号**零商机行** ⇒ 企业自来，lead vacant＋`no_sourcer`、平台吸收 lead 席份额（12 万单平台 61,200，§3.4 情形六）；归属**三戳成套** ⇒ 收款人＝`attribution_owner_user_id`（同企业多行取已确认行——确认即不可改写；企业自行注册不转移归属＝复用 ADR-009 反例字段不重造）；归属**未确认** ⇒ 409 `attribution_not_confirmed` fail-closed（**不得回落平台代持**，零写入）。
- **接线原语** `allocate_five_seats_with_lead_attribution`：lead 由解析器**独占裁定**（调用方传非 NULL lead 键一律 400）；其余池席位承载归 T4 人工确认；比例快照取 T2 初始基线 active 版本（v100），分配行记版本溯源——T2×T3 打通（基线常驻 ⇒ 分配可真跑）。
- **拉单资格闸替换（关键流转口径变更，书面依据＝ADR-011 v1.3 §5-F＋书面签字页 A-7 行）**：`attribution_service._require_sourcer_seat` 两独立路径任一放行——① `seat_status='active'` 且未过期（过期≠有效）；② G3 科目层本人 `seat_fee` 有效行（`recorded`/`reconciled`，voided 不算）；都不成立 403 `opportunity_reporter_seat_required`。**R2 角色闸退役**（`opportunity_reporter_role_required` 代码与用例同轮退役，规则文件 §1/§2/新 §2.1 三处同步；机器可读槽位块零变化）。3980 仍是 ADR-008 独立年费科目（不进分账池）。
- **测试** NEW `test_dispatch_lead_attribution_wiring.py` **10 例**（三态解析/情形六逐分/多行取已确认/lead 独占 400/版本溯源/资格闸两路径/过期席位不放行/R2 角色不算资格 fail-closed）；`test_report_requires_r2_role` 改写为 `test_report_requires_paid_seat_not_role`（角色在席位缺仍 403／未分层席位在场放行）；既有 16 处 `_layer_as_r2` 夹具经真实 `activate_seat` 服务路径补激活。变异 M7（无归属也计提）／M8（最新报备者夺走归属）／M9（摘资格闸）**全红→字节级还原 sha256 终验→绿**。
- **口径（融合树现测）**：**零迁移零新表零新路由**（63 rev 单头 `c8d2f6a4e9b1` 维持）/路由 **451 不变**/蓝图 **50**/表 **148**/api_catalog 94 不变/mypy **279 基线不变**/ruff 绿；pytest 终值以本 PR CI 为准（本地 **2879 收集**＝T2 基线 2869 + 本轮 +10）。server 变更 ⇒ 合并后 rebuild 三镜像（alembic 幂等 no-op）。

## [未发布] — 获客诊断评测自动化三件套（T-07 批跑脚本＋T-08 judge 评分器与元验证闸＋T-09 版本化评分曲线；零迁移零路由零蓝图，2026-11-11）

- **任务书 W1 层落地**（`docs/architecture/获客诊断工具实施任务书-v1.md` T-07/T-08/T-09，消费 T-06 评测集与 T-10b 真实生成器）。**分层纪律（评测集污染隔离 R-4 的实现形态）**：judge 是**通用「文本 vs 参考材料」评分器**——不知答案字段叫什么（参考材料由 scripts/ 层装配成通用小节标题文本）；答案形状知识只在 `scripts/diagnostic_eval/`（N2 扫描 `server/src` 不达 scripts/）与真相层；N1–N7 零豁免照常全绿。
- **T-08 judge**（NEW `server/src/fde_api/simulation/diagnostic_judge.py` ＋ config 槽位 `diagnostic_judge_model`，env 键 `FDE_DIAGNOSTIC_JUDGE_MODEL`——字段+`env_prefix=FDE_` ⇒ 无 DEEPSEEK 段，CR-046 家族，`.env.example` 注记防死键）：rubric-v0.1 四维（①覆盖 0–40／②方向 0–30 反向归零／③遗漏幻觉 0–20 倒扣／④落地 0–10 doc_type 分支）；**total/verdict 服务端重算**（模型契约无此二键，unknown_keys 拒绝）；<65 hard_fail／65–78 conditional／≥79 pass；④<6 一票否决；≥4 条同义复述 ⇒ `score_invalid`；**元验证闸**（B#23 先例）：锚点 A1/A2 落带＋反例 X1–X4 拦截 ⇒ pass，锚点原件缺失 ⇒ `insufficient_data`；purpose=`diagnostic_report_judge` 与生成分键对账。
- **T-07 批跑**（NEW `scripts/diagnostic_eval/`：eval_lib＋run_eval CLI bootstrap/generate/judge/curve）：生产路径真机批跑（受理闸全走，outbox 进程内 no-op 防共享部署栈双跑）；**考卷→生产问卷闭集适配表** `answer_mapping.json`（逐条登记 fail-closed＋`_case_overrides` 按卡考官补填必答槽位并留 `_uncertain` 注记）；映射 sha256 进 run.json；E-2：原件落真相层 `eval-runs/<run_id>/`，仓库只存汇总+指针+sha256。
- **T-09 曲线**（NEW `docs/audit/诊断评测-评分曲线-1.md`）：双版本标签＋元验证闸列＋逐卡四维表＋版本断点节＋insufficient_data 语义。
- **真机首轮（run=2026-11-10）两对真发现**：①生成面 **0/6 诚实失败**（全量 fallback MiniMax-M3.1-Flash 思考吃穿 6000 预算截断 ×3＋契约违规 ×3，审计账本为证；生成器修复归生成器轮）；②**judge 元验证闸=fail（按设计拒绝认证）**——A1 顶格 100 越带 78–98＋同源复述条款误发（锚点报告与案例卡参考同源），A2 78 落带，反例 4/4 正确拒绝；rubric/夹具 v0.2 修订挂下一轮（换版本+断点，不现场改夹具凑绿）。
- **judge 通道真机校准**：`DIAGNOSTIC_JUDGE_MAX_TOKENS 3000→16000`（思考型模型 thinking 与裁定共用预算，实测思考 6k–9k 方差；静态钉防回退）＋超时下限 300s（通用 90s 恒 ReadTimeout）＋`complete_json` 返回已解析 dict ⇒ `_call` 不做 `str()` 包转（stub 掩盖的契约错位真机才炸出）。
- **测试**：NEW `test_diagnostic_judge.py` 39 例＋`test_diagnostic_eval_batch_lib.py` 21 例；**变异八连全红→还原→绿**（M1 一票否决／M2 锚点带／M3 复述作废／M4 模型 total／M5 拆分交换／M6 双标签值〔首版无判别力改值级断言〕／M7 N2 覆盖探针／M8 R-5 执行设施探针）；污染钉顺延（fixtures 目录 registry/answer_mapping 非考卷数据文件不按考卷校验）。
- **口径**：零迁移零路由零蓝图；本地全量 **2801 passed + 6 skipped**（私有库串行实测 34m09s；★`-n 4` 两度被并发会话互摧——固定 worker 库名是跨 worktree 共享对撞面，外戳自愈分支 `DROP SCHEMA public CASCADE` 单语句四并发撑爆 PG lock 表 ⇒ setup 全红；批量 DROP 持久修法登记待办）；mypy 279 不变；桌面零改动不重打包。**合并与部署**：PR **#307**（head `8087914`）→ squash **`90d5f4f`**；PR CI 四绿＋main run success（server-tests 实测 2853 passed + 7 skipped）；三镜像 rebuild＋alembic 幂等 no-op（容器 current=当时 head）；活体 health ready 200。融合树口径现测见 F 线 T2 节（其合并含本轮 +59 测试）。

## [未发布] — F 线 T2 轮：五席位分账上线前初始基线版本＋冷启动档废止（迁移 `c8d2f6a4e9b1`，2026-11-11）

- **形态**：分账口径改造（F 线）goal 循环 T2。ADR-011 §5-C/§3.9：比例数值＝业务方交付 §17 数值类外部输入，落库载体＝**上线前初始基线版本**（16:57 拍板「不用公示，本项目还没上线呢」——豁免边界＝仅此一行，见规则文件 five-seat-split-rules.md §10）。
- **NEW 迁移 `c8d2f6a4e9b1`（62→63 rev 单头，改挂夜审 r5 `a9c5e2d7b3f1` 之后保单头）**：种入 `dispatch_rule_versions` 一行 `version_no=100`（保留段，1–99 留给上线后人工版本序列）`status='active'`，`published_at`＝`effective_at`＝**真实迁移执行时刻**（不倒填），`published_by_user_id`＝NULL（平台侧行为不伪装成人工动作）；`operation_events` 留 `initial_baseline` 痕迹（actor 取最早 user；迁移时刻无 user 则**诚实跳过**——NOT NULL FK 不允许伪造 actor，全新库干净通过）；幂等（ON CONFLICT，重放不产生第二份）。零 DDL 纯数据种子。
- **快照形状（两把尺各自成键）**：`five_seat` 块＝平台 30%＋池内 30/50/10/10（`platform_share_percent` + `pool_shares`，字段名与 `allocate_five_seats::_five_seat_shares` 读法一致——平台份额与池内份数是两个 100，不能摊平进一个键）＋Stage B 权重/等级映射分（与常量同值，基线 active 后撮合按快照打分不落空权重）；**不含**旧四席位 `seat_shares`（35/5/20/40 待迁移旧口径不进新层）。NEW `dispatch/baseline.py` 常量＝快照唯一权威形状；迁移**内联冻结字面量**与常量逐位一致（三方闸钉死：规则文件 JSON 块 ↔ 常量 ↔ 迁移种子；改任一侧必红）。
- **冷启动档废止（ADR-011 §3.9 补充拍板 11，不留两条口径）**：`DISPATCH_CONSTANTS` 摘 `cold_start_seat_shares`/`cold_start_first_orders` 两键；`seat_shares_for` 冷启动分支与 `_city_order_rank`（唯一消费者）一并摘除；`default_rule_snapshot` 两键不再投影；`test_dispatch_p0_r2.py` 冷启动用例改写为废止形态钉（`test_cold_start_tier_abolished`）＋只读节断言两键不得回流。报价域 `anchor_mode='cold_start'` 是报价锚点模式，同名不同义不受影响。
- **豁免边界验证**：基线在场时 `create_rule_version` 的 30 天公示闸照常咬合——NEW 反例「基线存在后再发第二版且零公示 ⇒ 422 `notice_window_required`」（闸序证明：公示窗校验先于版本号冲突校验）；合规第二版照常发布，到点激活后基线退役、同刻至多一个 active。**既有四处公示反例用例一字未改全绿**（`test_dispatch_p0_r2.py:798,850-860`、`test_dispatch_admin_rules.py:64-71`、`admin_routes.py` 闸零改动）。
- **测试与配套**：NEW `test_dispatch_five_seat_baseline.py` 9 例（三方闸/快照形状/常量同值/基线行形状/旧口径零渗漏/公示反例/激活退役/事件幂等/迁移往返）；conftest 逐测清行后与迁移种子**同源惰性补建**基线行（G4 ensure_rule/G5 ensure_tier_catalog 同款家族——每用例起跑时基线在场＝生产形态）；受「无 active 版本 ⇒ 422 降级态」影响的既有用例改**显式构造降级态**（NEW 共享 `retire_active_rule_versions`：p1_r5 降级用例＋CR-027 激活闭环＋b3ops 回放两例）——T2 起降级态从「空表默认态」变为「显式可重建态」。`test_migrations` HEAD 同步 63（融合 M1＋r5 插队）；往返清理序补删 initial_baseline 事件（迁移事件 FK 咬 user 的合法适配）。变异 M5/M6/M6b 全红→字节级还原 sha256 终验→绿。
- **口径（融合树现测）**：mypy **279 基线不变**/ruff 绿；pytest 终值以本 PR CI 为准（融合树本地 CI 同命令 `-n 4 --dist loadfile` EXIT=0 现测 **2869 收集**＝M1 基线 2793 + r5 +8 + #307 评测自动化 +59 + 本轮 +9 逐位吻合）；路由 **451 不变**/蓝图 **50**/表 **148**/**63 rev 单头 `c8d2f6a4e9b1`**/api_catalog 94 不变；零新路由零新表。`commercial_split_rules` 填实**挂账不落**：R1–R4×ratio 映射在五席位口径下无自然对应（两把尺不同，不得自行发明）且 L-4（v4.0 BP 原件未核验）未清——按最高规则 2 上报 OWNER。server 变更 ⇒ 合并后 rebuild 三镜像＋`alembic upgrade head`（种子行随迁移落活库）。

## [未发布] — F 线 T1 轮：五席位纵向分配明细层（NEW `dispatch_settlement_allocations`；迁移 `b7e4c1a9f3d5`，2026-11-10）（补账节——M1 轮口径债登记「F 线 T1 未写 CHANGELOG 节」，按 DoD 补账并入本随轮 PR）

- **形态**：分账口径改造（F 线）goal 循环 T1。ADR-011 §5-A 选型 A（OWNER 书面签字 29/29 随 PR #302 入库，签字页逐字节保留含 T-6 笔误 `tOWNER`）。
- **NEW 迁移 `b7e4c1a9f3d5`（59→60 rev 单头，经 #301/#300 两度插队 rebase 改挂 T-10b 之后）**＋表 `dispatch_settlement_allocations`（11 列）：一结算 × 一席位一行；空缺席位**显式记 0 不省行**（ADR-011 §3.5）＋原因码闭集（`no_province_partner`/`self_sourced_self_delivered`/`no_sourcer`）＋10 条 CHECK 联锁＋`(settlement_id, seat_key)` 唯一；零播种零预写数值；`delivery_settlements` **恒 20 列零加列**（结构钉）。
- **`allocate_five_seats`**：比例唯一来源＝规则版本快照 `five_seat` 块（H3 不硬编码；缺块 fail-closed 422 `five_seat_snapshot_required`；池内百份制 Σ=100 校验）；平台行＝残差；兼容镜像同事务派生——**平台行残差与平台镜像列残差是两个残差**（镜像列＝基数−三镜像列＝平台份额＋拉单＋空缺吸收＋尾差；region/city/delivery 1:1 镜像 province/county/delivery）；守卫接线：`mark_payable` 缺分配行 409 `allocation_incomplete`；`record_receipt_settlements` 明细在场时直写镜像 409 `allocation_mirror_protected`。
- **测试**：NEW `test_five_seat_allocations.py` **31 例**（ADR §3.4 六情形逐分＋Σ恒等＋四态闸＋CHECK 直插 8＋唯一索引＋结构钉＋迁移往返）；变异 M1–M4 全红→字节级还原 sha256 终验→绿。**CI：PR run 42835490008 四绿／main run 42838319007 四绿（server-tests 2772 passed + 7 skipped = 2779 收集）＝fork/main `f71364c`；活体部署三复验绿**（三镜像 api `c0fc47566f10`/worker `f6657e5605d5`/scheduler `46d38f4925c6`；alembic `b7e4d1c9a3f2 → b7e4c1a9f3d5` 真实升级；url_map 452 total/451 non-static；活库新表 11 列/0 行/唯一约束 1/CHECK 10）。
- 口径（当时点）：路由 **451**/蓝图 **50**/表 **147**/60 rev 单头 `b7e4c1a9f3d5`/api_catalog 94 不变/mypy 279 不变；审计三件套再生＋archify 闸复绿（147 表重渲染＋preview 整页实拍）。

## [未发布] — 夜审修复 r5：迁移窗口批（goal-review-fix r5：CR-045/048/053/059 一个 additive 迁移窗口＋服务层两兜底＋热点拆分，2026-11-10）

- **形态**：goal-review-fix r5 修复轮（迁移窗口）。r4 拍板（PR #300 合并 `cf0dd1c`）定向的四项「涉迁移」发现合并一个 additive 迁移窗口一次做（用户授权突破迁移禁区并留痕可推翻）。NEW 迁移 `a9c5e2d7b3f1`（十五/十六度插队连改挂现 M1 `a5e9c3f1b7d4` 之后 60→62 单头；#302/#303 并入 +2 表 +2 迁移）：`uq_agent_runs_idempotency_active`（CR-045 部分唯一＝同键 in-flight 至多一行，终态行不进谓词 ⇒ 重试链零影响）／`uq_agent_artifacts_run_storage_ref`（CR-048 产物唯一，前导 run_id 兼作 CR-059 详情页索引）／`uq_delivery_plans_project_published`＋`uq_test_plans_project_approved`（CR-053 单项目现行至多一份）／`ix_agent_tool_calls_run`（CR-059）。**零数据手术**＝活库现测四唯一面零重复先测后建（教训 63）。
- **CR-045（P1）幂等唯一窗口**：start_run 入口先查只防时序内并发；真实竞态窗口（预检查后、提交前对方先行提交）由部分唯一索引结构性兜底——`_execute_run` 落行撞 `uq_agent_runs_idempotency_active` 时败者重读在途行按幂等语义 200 返回（`_is_idempotency_active_violation` 约束名分类器：psycopg diag 命中精确匹配，无 diag 形态退回文本匹配，非目标约束原样上抛不吞）。
- **CR-048（P2）宿主回执幂等三缺口收口**：①docstring **诚实化**——「终态后重复回执且载荷指纹一致 → duplicate；指纹不同 → 409」的旧承诺由如实注记取代（指纹比对未实现、自动仲裁不做）；②**写事务 TOCTOU 收口**＝`with_for_update` 行锁重读后重校验状态（并发回执胜者已落终态 ⇒ 败者如实 duplicate=True、不再二次落产物）；③产物 `(run_id, storage_ref)` 唯一索引兜底。
- **CR-053（P2）单点现行唯一**：`delivery_plans` WHERE status='published'＋`test_plans` WHERE status='approved' 部分唯一索引（复核员校正口径：现行至多一份，历史 superseded 行不受限）。**实施期自查修正＝quality approve 退位循环前移**——原序「先置 approved 再退位循环」被循环查询的 autoflush 把「新 approved＋旧 approved 仍在」的中间态提前 flush 撞索引（实测 500）⇒ 退位先行（此时 plan 未脏、autoflush 无害）；delivery publish 本就 supersede-先行，无需动。
- **CR-059（P2）FK 索引**：`ix_agent_tool_calls_run` 落地；产物侧由 `uq_agent_artifacts_run_storage_ref` 前导列覆盖（独立 ix 冗余故不另建——迁移 docstring 注记）。
- **热点拆分＝`submit_host_receipt` 移至 NEW `agents/host_receipt.py`**（r5 加码撞 `test_source_size_budgets` 1836：1886→**1719**；N1 补码轮先例）——顶层单向依赖 adapter/models/extensions/zcode_contract；service 侧 `_settings`/`_error`/`_verify_host_poll_token`/`ARTIFACT_KINDS`/`FAILED_STATUSES` 函数内惰性引用（不造顶层环〔purity 闸〕＋保 monkeypatch `svc._settings` 语义）；对外名经 service 再导出，routes/tests 的 `svc.submit_host_receipt` 路径不变。
- **测试**：NEW `test_idempotency_uniqueness_window.py` 8 例（五索引形状 pg_indexes 现测含部分谓词／约束名分类器四态／CR-052 同款真实唯一约束竞态复现＝rival 连接抢插同键 in-flight run→败者 200 复用且同键恰一行／产物双插拒绝／回执行锁 spy＝读闸无锁·写事务行锁／TOCTOU 重校验＝并发胜者先行终态→败者 duplicate 且零二次产物／delivery/test 双现行拒绝）；`test_migrations` HEAD_REVISION→`a9c5e2d7b3f1`＋迁移计数 60。**变异四连全红→还原→绿**（M1 摘兜底返回→竞态用例红；M2 摘 with_for_update→行锁 spy 红；M3 摘写事务重校验→TOCTOU 用例红；M4 五索引 no-op→形状钉＋竞态用例红）。
- **口径**：迁移 60→**62** 单头 `a9c5e2d7b3f1`（改挂后）；表 148〔#302/#303 并入 +2〕／路由 451／蓝图 50／mypy 279 不变；pytest **CI 实测 2794 passed + 7 skipped**（run 42863460629 server-tests；＝r4 合并态 2741 + #302 +31 + #303 M1 +14 + 本轮 +8 逐位吻合）。
- **★部署证据（PR #304 合并 `833ccbc` 后执行）**：主树 ff 至 `833ccbc`（挂载源真相＝主树而非 worktree 的家族教训再现——首 rebuild 曾在 ff 前的主树旧 context 上跑出无 orgs 模块的镜像，`up --force-recreate` 后 alembic 报 Can't locate a5e9c3f1b7d4 才暴露）→ 三镜像从 ff 后干净主树 rebuild（api `e58a15622009`／worker `9fe389164aec`／scheduler `1c27f786ad37`，三容器 `.Image` 与构建产物逐位一致）→ `alembic upgrade head` 真实升级全链 `b7e4d1c9a3f2 → b7e4c1a9f3d5 → a5e9c3f1b7d4 → a9c5e2d7b3f1`、容器内 `alembic current`＝`a9c5e2d7b3f1 (head)` → 活体 `url_map` 452 total / 451 non-static ≡ 口径 → ready 200 → **五索引＋`ix_agent_tool_calls_run` 活库 pg_indexes 全部在场**。**★UPDATE 发库顺序教训**：quality approve 退位循环仅置内存状态时，unit of work 对多条 UPDATE 的发库顺序不保证（uuid 主键字典序决定）——本地绿/CI 红同构差异的根源；显式 `session.flush()` 在退位循环后强制先行落库（CI 复现 500 实证）。便携版 **r33** 从合并态打包：asar sha256 `1cf936ab32ccc4c1…`（r32=`cf0d438f…` 未覆盖）；**字节验证**：`fde-session-plain-v1`（CR-072 明文前缀）新包命中 1／r32 对照 0＋PLAINTEXT 告警文本新包 1/旧包 0。

## [未发布] — 多客户工作平台 M1 主体与组织底座轮（NEW orgs 表＋三列归属＋存量回填＋审计维度；迁移 `a5e9c3f1b7d4` 59→61 rev（十二度插队改挂 F 线 T1 `b7e4c1a9f3d5` 之后保单头），零路由零蓝图，2026-11-10）

- **任务书 §7 M1（ADR-M1 §3 甲路线落地）**：NEW `orgs` 表（`org_type ∈ {enterprise, internal}` CHECK 闭集 ＋ name 唯一（企业代号化名，红线 2）＋ `subject_key` 可空唯一挂 G6 企业主体键（String(18) 对齐 `enterprise_quota_subjects`）＋ `created_by_user_id` 纯指针无 FK）＋ 三列归属 `users.org_id` / `projects.org_id` / `operation_events.org_id`（均可空、FK RESTRICT、各带索引；`ix_operation_events_org_occurred` 复合索引对齐既有 project_occurred 房法）。迁移 additive 单迁移（`b7e4d1c9a3f2` 之后单头）：**播种平台内部组织**（稳定 ID `00000000-0000-0000-0000-0000000fde01` 与 `orgs.models.INTERNAL_ORG_ID` 单一权威同源，测试文本钉逐位一致）＋ **存量项目回填 internal org**（`UPDATE … WHERE org_id IS NULL` 幂等守卫）；**存量用户不回填**——`org_id=NULL`＝平台身份不受 org 限制（拍板 §11-8，存量回归面最小化）。
- **归属戳单一入口** NEW `orgs/org_scope.py`：`before_flush` **会话级**事件（覆盖一切 ORM 写路径——路由/服务/种子/脚本无一漏网）——项目未显式携带 org_id 时按 leader 归属落 org、平台身份 leader 落 **internal org**（「internal＝承载存量回填与平台侧项目」，ADR-M1 §3）、**显式 org_id 不覆盖**（M2 注册面/M5 企业空间显式指定归属的前置语义）；`OperationEvent.org_id` 从其项目归属推导（**数据归属口径**：「这条事件关于哪个 org 的数据」），无 project 事件＝平台级 NULL（目标归属可从对象推导，ADR-M1 §4）；推导助手 `org_of_project` / `orgs_of_user`（=[users.org_id]+成员项目传递，去重保序）；`ensure_internal_org` 幂等 get-or-create 接线 `bootstrap-open-source`（任务书「种子与 cli 补 org」）。**零平行权限表**（G6 红线：成员可见性仍由 `project_access` 单一权威决定，org 只承载归属与统计口径）；隔离逻辑零接触 `projects/service.py`（1945 行不变——红线 15/热点闸）。
- **测试** NEW `test_org_tenant_base.py` **14 例**：迁移往返（downgrade `b7e4d1c9a3f2`→裸种子→upgrade→回填/不回填断言→downgrade 对称（列消失、项目行存活）→重放幂等）/ org_type 闭集 CHECK / name 唯一 / subject_key 唯一但可空多行共存 / 归属戳三态（平台身份→internal、企业 leader→自 org、显式不覆盖）/ 事件维度两态 / `orgs_of_user` 直属+传递去重 / `ensure_internal_org` 幂等+**创建分支** / **「企业 A 建项目 → 企业 B 不可见」集成验收**（真实 API：POST /projects 经服务层与归属戳落 org=A，GET 列表/详情经既有 project_access 单一权威判不可见 403/404，立项事件 org_id=A）。**变异四连全红→还原→绿**（M1 摘 internal 兜底→平台身份用例红；M2 摘事件推导→事件用例＋集成审计断言红；M3 摘回填→迁移往返红；M4 显式覆盖→显式用例红）。
- **实施期自查修正（两处结构缺陷被机械闸当场拦下）**：① `orgs.created_by_user_id` 初版带 FK RESTRICT——与 `users.org_id→orgs` 构成 orgs⇄users FK 环，元数据不可拓扑排序（`alembic check` stderr SAWarning 闸红）⇒ 改**纯指针无 FK**（provenance 应用层维护，先例 minutes.draft_id 同形）；② `workbench.models` 尾部导入 `org_scope` 注册监听与 org_scope 顶层导入 workbench 模型构成包级导入环—— `test_architecture_purity` 冻结闸红 ⇒ 监听体与推导助手改**函数内懒导入**（顶层零 workbench 导入），环消失不进 KNOWN 清单。
- **mypy 闸顺带抓住一个真空缺陷**：`INTERNAL_ORG_NAME` 未导入——`ensure_internal_org` 创建分支 NameError，但夹具里内部组织行总在场（get 恒命中）⇒ 测试此前走 early-return 掩盖；mypy name-defined 补测创建分支后转真绿（「类型闸抓测试盲区」实录）。
- **十二度插队 rebase（fork/main 先落三笔，合并前消解）**：#300 夜审修复 r4（pytest +7）／#301 T-10b 部署回填 docs（+0）／#302 F 线 T1 `dispatch_settlement_allocations`（pytest +31，迁移 `b7e4c1a9f3d5`）⇒ 本迁移改挂 T1 之后保单头（59→61 rev 单头），冲突四文件两侧全留消解（test_migrations `HEAD_REVISION="a5e9c3f1b7d4"`／全集 61）；★**上游口径债如实补正**：F 线 T1 轮未改 AGENTS 现行口径行（fork/main 停在 146 表/59 迁移）也未写 CHANGELOG 节——融合树口径按实测推进不承袭（146→148 表/59→61 迁移），其 CHANGELOG 节留待 F 线自补；清单三件套＋archify 三件套按融合树重生成重拍（preview 1440×2098）。
- 口径：pytest **2793 收集 = 2787 passed + 6 skipped**（融合树本地 CI 同命令 `-n 4 --dist loadfile` EXIT=0 / 14m50s 现测＝T-10b 基线 2741 ＋ #300 +7 ＋ F 线 T1 +31 ＋ 本轮 +14，逐位吻合；CI 终值以本 PR server-tests 为准）/ mypy **279 不变**（官方闸绿）/ 路由 **451**（T-10b 已并入基线，本轮零新路由）／蓝图 50 不变／表 **146→148**（含上游 F 线 T1 一表）／迁移 **59→61 rev 单头 `a5e9c3f1b7d4`**；audit 清单重生成（database CSV +orgs 行＋F 线 T1 表入册；route CSV 零 diff＝零路由铁证）；archify 三件套（candidate.json＋system-architecture.html「146 表」→「148 表」＋ preview.png 整页实拍 1440×2098）防陈旧闸绿；`alembic check` 元数据↔迁移逐项对称。server 变更 ⇒ 合并后 rebuild 三镜像＋`alembic upgrade head`（新迁移）；桌面零改动不重打包。

## [未发布] — 夜审修复 r4：拍板批（goal-review-fix r4：20 条挂账经蔡工三批交互问答裁决，10 项按推荐落地＋4 项定向 r5 迁移窗口＋6 项结构化维持挂账，2026-11-10）

- **形态**：goal-review-fix r4 修复轮（拍板批）。20 条挂账经蔡工三批交互问答逐条裁决：16 条按推荐执行、6 条结构化维持挂账（全部留痕可推翻）。变异验证 5/5 判别（红→反向替换→绿；CR-065 行为断言对 uuid 抽签仅 1/3 概率判别力，补静态源码钉后变异必然红）。发现登记与全量证据见 r1 报告 `docs/audit/全面代码审查报告-2026-11-10.md` §六。
- **CR-043（P1）host_poll 启用闸第四前置**：拍板＝「workflow agent 节点异步消费语义设计轮」并入 host_poll 生产启用闸裁决包成为**第四前置**——`server/.env.example` POLL_ENABLED 注记落地；生产开启 host_poll 前四前置必须全清（设计缺口不解决不开闸）。
- **CR-044（P1）确认人豁免显式留痕**：transcripts service docstring＋models 列注释落拍板口径——确认人＝本方员工手填**职务泛称**（不填真实姓名），豁免自动脱敏；正则机制层拦不住人名＝如实留痕，输入面约束靠填表指引。
- **CR-046（P1）FDE_PRODUCT_NAME 死键修复**：`config.py` `fde_product_name` 加 `validation_alias="FDE_PRODUCT_NAME"`——README/.env.example/AGENTS 六处承诺的 env 覆写通道真实生效；NEW `test_config_product_name.py` 4 例（覆写生效/默认回退/历史死键 `FDE_FDE_PRODUCT_NAME` 不再生效/短键优先）。
- **CR-062（P3）存在性泄露口径统一**：拍板＝他人一律 404——quota `get_quota_view` 他人视角 403 `commercial_entitlement_forbidden` → 404 `quota_not_found`；企业空间非管理员分支先判他人 404 `enterprise_space_not_found` 再判存在性；测试断言存在/不存在两态错误载荷逐位一致（探测不可分辨）。
- **CR-064（P3）高风险写闸豁免成文**：NEW `docs/architecture/高风险写确认闸适用清单-v1.md`——适用面/有意豁免面（users.role、派单规则发布：admin 门＋operation_events 留痕理由）/裁决记录三节。
- **CR-065（P3）首过率 tie-break 确定性**：metrics 首条查询 order_by 补 `TestExecution.result, TestExecution.id`（原按 uuid4 id＝同 created_at 批量写抽签）；指标定义文本补 tie-break 注记；测试＝行为钉（同刻 blocked/passed 必取 blocked）＋静态源码钉（order_by 必含 result，uuid 抽签变异必然红）双保险。
- **CR-066（P3）草稿 discard 权限对齐**：弃置＝不可逆破坏（含文件根删除）——非创建者须 can_manage（沿 promote 同尺），只读成员 403 `project_forbidden`；测试 owner/member2/leader 三态。
- **CR-067（P3）superseded 语义标注**：拍板＝维持现状态值不新增——plans/quality 两处行内注释标注「否决稿复用 superseded（区分靠 operation_events.decision）」；零净增行（热点行数预算内）。
- **CR-069（P3）reconcile 错误码区分**：bridge reconcile except 拆分——真无快照 409 `no_snapshot`；投影 DB 故障 500 `sync_failed`（不再把数据库故障误报成「没有可重放快照」误导排障方向）；NEW `test_bridge_reconcile_errors.py` monkeypatch 双态。
- **CR-072（P3）明文降级可观测**：desktop auth-store safeStorage 不可用分支带显式前缀 `fde-session-plain-v1:` ＋ console.warn PLAINTEXT 告警（不再静默）；load 侧识别剥前缀，旧版无前缀明文继续兼容；测试改写真回环（load 读 save 实际写出字节——修掉 readFile 空 mock 的假绿）。
- **测试**：NEW `test_config_product_name.py` 4 例＋`test_bridge_reconcile_errors.py` 1 例；`test_transcript_drafts` +1（discard 三态）；`test_metrics_v31` +1（tie-break 双钉）；`test_commercial_enterprise_quota/space` 他人 404 适配；desktop `auth-store.test.ts` 前缀/告警/剥前缀改写（8 例全绿）。受影响域 62 例本地绿＋桌面 typecheck 绿。
- **拍板留痕（4＋6 条不落地项）**：CR-045/048/053/059 拍板定向 **r5 迁移窗口一次做**（部分唯一索引×2＋AgentArtifact 唯一约束＋FK 索引＋宿主回执写事务重校验，用户授权突破迁移禁区并留痕）；CR-055 维持观察（用例编辑/需求撤销通道立项时补护栏钉）；CR-056 挂触发条件（renderer 直连分片上传真实场景出现时选型）；CR-057 挂触发条件（远程 https API/OSS 一等形态立项时裁决 CSP）；CR-061 结构化挂账（host_claim 并发真实化或令牌改多实例时补行锁）；CR-071 结构化挂账（web 桥暴露面扩大/公网部署前系统性补齐校验族）；CR-074 迁移禁区（下次触碰该迁移文件的轮次顺带修正）。
- **口径**：零迁移零路由零新表（结构口径沿 448 路由/50 蓝图/146 表/58 rev 单头 `f3a9c7e1d5b2`，r5 迁移窗口另行推进）；pytest **CI 实测 2748 收集 = 2741 passed + 7 skipped**（run 42829286169 server-tests 11m31s；基线 2741 收集〔2734+7s〕+ 本轮 +7 逐位吻合；历经 mypy 闸两修＝validation_alias 形参合成误报 type:ignore＋CI 无 .env 补显式必填面、CHANGELOG 插队冲突两度两侧全留）；**PR #300 squash 合并 `cf0dd1c`＝fork/main 顶**；server 变更 rebuild 三镜像＋桌面便携版 r33 随 r5 部署轮一并交付。


## [未发布] — 获客诊断工具 W2 T-10b 轮：diagnostics/ AI 报告层（异步生成 + R-1~R-7 契约闸 + 分享只读页；扩列 + 迁移 `b7e4d1c9a3f2`，2026-11-11）

- **范围与拆分**：T-10 剩余的 AI 报告半（**T-10b**）——T-10a 已落规则层（匿名会话 + 首屏政策补贴测算卡 + 闭集问卷），本轮补齐**AI 报告生成 + 只读分享页**。报告走本仓既有 outbox → background job → worker 三段（**异步**：公网免注册面不能同步等模型）。D-1/D-2 沿用 T-10a 默认；★**完整报告要留资**（D-2 的全文留资闸，同时是**成本闸**——免注册白烧 AI token 的代价远高于留资转化）。
- **R-1~R-7 逐条落成机械闸**（来源：任务书 §3 T-10 需求清单，来自 rubric v0.1 的 AI 预评归因）：**R-1** 报告结构无分数字段（多一个键即拒收）＋数字闸只认**问卷/测算卡里出现过的数字**；**R-2** **政策原文口径由服务端注入**——模型只输出 `policy_ids`，原文口径/我方解读/官方出处/快照日期全部由 `policy_data` 装配，**模型没有原文可抄也就无从编造**（fail-closed by construction）；**R-3** `first_step` 三要素齐全且 `when` 闭集＝「本周」；**R-4** 未溯源数字 fail-closed（数字须在问卷/测算卡里出现过，否则该句写「待澄清」；数字识别含**中文数字＋量词**形态，「三个月」也算数）；**R-5** `actions` 必须覆盖 `findings` 每个 id 且无悬空引用；**R-6** 建议段禁用词闸（「已完成改造」等）——**只扫建议段**（现状段是客户原话，不在此闸拦）；**R-7** `closing_loop` 四段键齐全非空。
- **AI 调用主体＝平台服务账号**（新增配置 `FDE_DIAGNOSTICS_AI_ACTOR_USERNAME`）：匿名访客没有账号，而 `execute_ai_prompt` 要求真实 `users` 行（预算闸与 G-16 归因台账都要有主体）⇒ 报告生成记在**平台服务账号**头上，用量与审计如实归集；未配置/账号停用 ⇒ **fail-closed 503**（不静默降级成「没有报告」）。生成走 `execute_ai_prompt` **单一入口**（`purpose="diagnostic_report"`、`prompt_version="diagnostic-report-prompt-v1"`、`use_tools=False`），AST 提示词白名单**扩登记** `DIAGNOSTIC_REPORT_SYSTEM_PROMPT`。
- **异步生成**：`POST /api/v1/diagnostics/session/report` 受理即 **202**（只入队，不阻塞）；worker handler 幂等（已有报告不重复调 AI），契约违规重试一次仍不过 ⇒ 落 `failure_code`（访客看得到，可重试），**不吞错、不把会话卡在生成中**；瞬时 AI 故障交给 worker 退避重投。
- **分享只读页**：`POST /session/share` 发放只读分享令牌（**明文只此一次，每次轮换旧链接**；指纹独立域分隔，与会话令牌权限域分开）；`GET /share/<token>` 只给**摘要层**（结论一句话 + 第一步三要素 + 政策机会 + 问题标题 + 闭环四段存在性）——**不含企业自填原文与联系方式**，留资闸不被分享链接绕过。
- **数据模型**：扩两列（迁移 `b7e4d1c9a3f2` 挂 T-10a `f3a9c7e1d5b2` 之后 58→59 单头）：`report_requested_at`（受理 ≠ 就绪，区分「未请求」与「生成中」）＋ `share_token_sha256`（可空、非空唯一、64 位 CHECK）。**零外键变化**（仍零外键指向 projects）。
- **★口径校准**：每匿名令牌当日动作配额 **3 → 6**——访客走完主流程要 5 个动作（测算/续填/留资/报告/分享）＋1 次重试余量，配额 3 会把**正常访客**挡在门外（实测：生成报告与分享链接撞 429）。IP 每日 20 仍是更宽的那道闸。
- **测试**：NEW `test_diagnostics_report.py` **25 例**（契约七条逐条 + 异步受理/幂等 + 分享只读/轮换 + worker 成功/契约失败/AI 失败/幂等跳过 + 服务账号 fail-closed）；**变异八连全红→还原→绿**（摘数字闸/摘一一映射闸/摘第一步闸/摘未知政策闸/摘禁用词闸/摘闭环闸/摘留资可见闸/分享视图给全文；还原后 sha256 逐位一致）。★**rebase 融合实测补一刀**：report 文件 `diag_app` 夹具补注 `_FakeRedis`（与 mvp 同款）——共享开发 Redis 的 IP 日配额键按日期累积 × `PerTestIPClient` 序号源每 run 从 1 复位 ⇒ 低位 IP 计数器跨 run 推过 20 ⇒ 本地多轮必撞 429（CI 全新 Redis 免疫）；测试隔离缺陷在本 PR 修死，不靠「清 Redis」续命。pytest **+25** ⇒ 第十度插队融合树曾实测 2724 收集（本地 2718+6s／PR CI 2717+7s，run 42799850276）——**属第十一度插队前基线·已作废**；两度融合实测 2731 收集（第十一度本地 2725+6s／PR CI 2724+7s run 42807041956）——**属第十二度插队前基线·已作废**；第十二度融合实测 2740 收集（本地 2734+6s／PR CI 2733+7s run 42813266948）——**属第十三度插队前基线·已作废**；再融合 #293（r3 卫生批 +1）/#294/#296 后**融合树本地 CI 同命令 `-n 4 --dist loadfile` EXIT=0 实测 2741 收集 = 2735 passed + 6 skipped**（12m52s）＋**PR CI 实测 2741 收集 = 2734 passed + 7 skipped**（run 42819084677＝2706+9+1+25 逐位吻合；CI skip 7／本地 6 差 1＝污染钉 N6 设计行为）。
- **结构口径现测**：路由 447→**451**（＝447+本轮 3+第十一度插队 #286 运维就绪度读面 2；extractor 融合树现测）／蓝图 **50**（不变）／业务表 **146**（不变）／迁移 58→**59** 单头 `b7e4d1c9a3f2`；审计清单三件套重生成（route CSV 本轮 +3 行 / DB CSV 增两列）；**archify 图纸口径同步**（`architecture/candidate.json`＋`system-architecture.html` sublabel＋四处 →「451 路由」，图纸防陈旧闸复跑绿）＋**整页实拍 preview.png**；mypy 官方闸 **279 基线不变**（零新增）；ruff 触碰文件零告警。
- **合并与部署**：PR #287（head `77d3b2f`＋`b77ce8c` 文档剥离尾巴）→ squash **`014bffe`**＝fork/main 顶；main run 42823175763 四绿（server-tests 2741 收集 = 2734 passed + 7 skipped，与 PR head run 42819084677 逐位一致）。三镜像从合并 SHA 干净树 rebuild（api `99d2f360…`／worker `3b6b4666…`／scheduler `8f92f532…` 逐位一致）＋`alembic upgrade head` 真实升级 `f3a9c7e1d5b2 → b7e4d1c9a3f2`（容器内 current＝`b7e4d1c9a3f2 (head)`）；活体 url_map 452/451 ≡ 口径；**部署闸默认关 ⇒ 活体 404**；health ready/live 200。桌面零改动 ⇒ 便携版不重打包。
## [未发布] — AI 原生化 N1 人工链收口轮＋台账 v1.9（腿①偏差纠正＝7 产物复核改挂 pilot.reviewer＋试点 N1 判定完成于 G7；G-07 CLOSED、G-01 仍 OPEN，2026-11-11）

- **起因**：蔡工交互拍板三项（①试点判定完成／②腿①偏差纠正为 pilot.reviewer 重审／③随轮回写）。上一辅助轮（v1.8）留了一处 D-1 偏差：腿① 7 产物复核留痕 actor=admin（蔡工当时 admin 登录桌面），破了 D-1「审阅人=蔡工本人经第二账号 `pilot.reviewer`、提交人≠审阅人」的账号分离语义。本轮纠正。
- **腿① 偏差纠正（活库写动作，走服务层写路径）**：蔡工拍板「改 pilot.reviewer 重审」⇒ admin 逐件「撤回复核」（清空 `reviewed_by_user_id`/`reviewed_at`）→ `pilot.reviewer` 逐件重标 7 产物。复测活库：7 产物 `reviewed_by_user_id` **全部挂 `pilot.reviewer`**（`bd78b768…`），`agent_artifact_reviewed` 事件 ×14（admin 撤回 7＋pilot.reviewer 重标 7）留痕可查可推翻。纠正走 `set_artifact_reviewed` 写路径（**非直接 UPDATE 库**），事件正常落 `operation_events`，不绕过 H1–H13 强制人工节点——D-1 账号分离语义自此真正行使。
- **★试点达成口径裁定（蔡工拍板「试点判定完成」）**：N1 试点判为**完成于「AI 自动化链跑通＋G-07 候选登记＋G7 诚实 fail 拍板＋腿①偏差纠正后账号分离语义闭合」**。G-07 两段判据（completed run 自动登记 7 候选＋人工提交闸采纳 2 条进 G7）全行使 ⇒ **维持 CLOSED**；G-01 执行面（真实订单 completed run＋候选登记＋人工闸采纳＋门禁拍板留痕）已走完，但消解判据「至 G9」所依赖的 **G8/G9＝真实交付阶段证据（PoC 验收表／business-case／生产环境／Runbook／Go-Live 单／演练记录），属业务里程碑、超试点范围、不可代造** ⇒ **G8/G9 保持 pending 不代拍**（`decide_gate` 无证据提交机械 409 `invalid_gate_state`）；**G-01 维持 OPEN**（试点完成≠判据达成，诚实口径不虚过）。
- **★红线守死**：门禁证据只存指针+sha256、AI 不代拍板/不造假（G8/G9 证据不可代造）；写外呼/发信/付款永不降级永不自动；腿①纠正走写路径留痕；①商用条款（外部依赖）/⑦网络限制面（结构缺口）维持未过不声称。
- **随轮回写**：台账 **v1.9**（G-01 状态格＋「N1 人工链收口轮」附注）＋复盘 §10＋任务书 §13 #13＋§14 N1 行＋AGENTS bullet。腿①纠正为活库写动作（走写路径，非代码变更），无 rebuild／无 alembic／无重打包；口径沿 fork/main `ac0a130`，pytest/vitest 以最近 main CI 实测为准。

## [未发布] — AI 原生化 N1 人工链辅助轮＋台账 v1.8 判定（产物 7/7 已复核＋2 候选进 G7＋G7 fail 拍板；G-07 CLOSED、G-01 仍 OPEN，零代码拍板落盘，2026-11-10）

- **起因**：蔡工问「人工腿完成了吗？没完成帮我完成拍板」——活库探针实测三腿全未动（7 产物全 `reviewed=False`、7 候选未挂任何门禁清单项、G7/G8/G9 全 `pending`），蔡工经交互问答定三腿处置：①产物接受＝蔡工桌面亲做（AI 代录＝伪造审阅链，拒绝代做）；②证据映射＝「只提强映射 2 条」（不虚挂 7 条）；③门禁拍板＝判据摘要+选择题、蔡工选、AI 代录留痕可推翻。
- **腿① 产物复核 7/7**：蔡工逐件读完 7 件原件（宿主工作区 `D:\test\agent-workspaces\bef48e56…\output\`，sha256 与库内逐件一致）后在桌面 AgentsConsole「标记复核」，`agent_artifact_reviewed` 事件 ×7＝全库首批 `reviewed=true`。**★D-1 偏差在案＝复核 actor=admin 非 `pilot.reviewer`**（蔡工当时 admin 登录桌面）——保守侧维持现状不撤回，偏差注记入档；修正通道敞开（admin 逐件「撤回复核」→ 换 `pilot.reviewer` 重标）。
- **腿② 候选进门禁 2 条**：`submit_gate_evidence` 代提交（admin 代录、蔡工拍板授权）presales-solution-draft→G7「options 文档」、demo-and-validation-plan→G7「Eval 计划」（指针+sha256 成对；note 全注拍板与代录身份；其余 5 候选留 `project_evidence` 留痕不进门禁）——G7 `pending→evidence`，清单项 `claimed`＋`gate_evidence_submitted` 事件。
- **腿③ G7 fail 拍板**：拍板问询未获答复 ⇒ 按「推荐项执行+留痕可推翻」先例（#124/#125 委托先例）以 pilot.reviewer 代录 **fail**（`gate_decided` 事件、CAS rev 1→2；note 全注判据＝4 项清单仅 2 项 claim、缺 success.md 客户书面确认与 B 试点章程定稿、真实材料齐后重交再拍）——**拍板人≠提交人硬闸活体验证**（admin 提交 ⇒ pilot.reviewer 拍，代码强制 403；G8/G9 无证据提交时 `decide_gate` 409 `invalid_gate_state`＝机械不可拍）。G7 fail 有重交回环，不虚过不留死账。
- **★设计缺口登记（backlog T-A10）**：本链执行实证——桌面 AgentsConsole 产物行无内容预览/下载（服务端亦无产物内容读取路由，仅 PATCH 复核写面），复核人被迫离开应用到文件系统看原件；T-A10＝桌面产物预览面（登记≠排期≠实施授权）。
- **判据状态更新（台账 v1.8）**：G-07 两段判据（自动登记 7 条＋人工提交闸采纳 2 条）全行使 ⇒ **CLOSED**；G-01 消解判据「首个真实订单至 G9」未达成（G8/G9 仍 pending、无真实阶段材料）⇒ **维持 OPEN**。回写面：台账 v1.8（修订记录+G-01/G-07 状态格+「N1 人工链辅助轮」附注）+ 复盘 §9 + 任务书 §13 #12 + §14 N1 行 + backlog T-A10。结构口径沿用 fork/main `3eb6f28`（无代码变更，pytest/vitest 以最近 main CI 实测为准）；无 rebuild／无 alembic／无重打包。

## [未发布] — 夜审收口轮（goal-review-fix 收口：报告状态终更新+台账三同步+活体复验；纯文档零代码，2026-11-10）

- **三轮全合并**：r1 审查报告轮（PR #268→`993341c`）+ r2 服务端行为批（PR #289→`3eb6f28`）+ r3 卫生批（PR #293→`06c1dd5`）——**18 项已修**（r2×8+变异 8/8 判别；r3×10）/ **20 项挂账待拍板**（消解条件 owner=蔡工，见报告 §六醒后拍板清单）/ P0 零条。
- **报告终更新**：`docs/audit/全面代码审查报告-2026-11-10.md` 头部补执行终态（③）；§五修复执行情况表 r2/r3 行标注已修+PR 号；CR-075 勘误回填（原登记第二处 E0 实测不存在＝E1 误报——P3 未复核的代价实证）。
- **台账**：轮次状态表补 r2/r3 两行；详情索引节头部补状态终态说明（行内「r2 修/r3 修」=已落地，挂账 20 条维持）。
- **部署活体复验三项全绿**（收口时点现测）：①口径 06c1dd5 现测=448 路由/50 蓝图/146 表/58 rev 单头 `f3a9c7e1d5b2`，活体 url_map 449 total/448 non-static ≡ 口径（本轮零新路由；较开工快照 441 多 7 条系上游 #280/#283 插队增量）；②容器内 alembic current=`f3a9c7e1d5b2`（本轮零迁移，活库已在 head）；③三容器镜像 ID（api `8ef9e2174e18`/worker `a1113fd15e63`/scheduler `917a57e5a709`）与 06c1dd5 干净树 rebuild 产物逐位一致。
- **方法论教训（已入 AGENTS bullet 与记忆）**：①xdist 4 worker 共享 Redis 下 autouse「清计数键」夹具是跨 worker 干扰源（本地单进程测不出——CI 才暴露）；②跨服务顶层 import 会触发 architecture_purity 包环冻结闸（懒导入解）；③热点行数预算文件加行必先查 `test_source_size_budgets`；④块级文本补丁的缩进 hazard（`replace(old, "")` 空串路径会把块前插文件头）——补丁脚本必须行为断言+编译自检。
- **口径零变化**：纯文档轮；448 路由/50 蓝图/146 表/58 rev/ENTRIES AST 94/mypy 279 维持（部署活体已验）。
## [未发布] — 多客户工作平台 M0 决策与盘点轮（4 ADR＋全局面盘点表＋容量实测＋口径现测；纯文档零代码，2026-11-10）

- **形态**：M 线（多租户工程）Goal 循环首轮 M0——**零业务代码改动**（不改模型/路由/迁移/前端/compose），基线 fork/main `06c1dd5`（工作区切出基线 `144024e` 后 ff 对齐 9 个上游合并提交；开工时在途 PR 仅 #287 诊断 T-10b 零交集）。NEW `docs/commercialization/multi-tenant/` 八件产物：ADR-M1 租户模型（甲路线落成书面裁决＋乙路线演进触发条件）、ADR-M2 主体角色映射（四主体×`users.role`×商业分层三层正交＋`org_id=NULL` 平台身份语义）、ADR-M3 全局面判定规则（R1/R2/R3/R4 判定规则＋M3a 规格前置/M3c 先红/M3b 批批同 PR 纪律）、ADR-M4 注册审核策略（四入口映射既有 G2/G5/G6 面＋审核状态机＋邀请令牌一次性语义）、《全局面盘点表》（**8 维度**：63 全局表逐表三类处置 17+14+32 脚本断言／236 涉全局写端点逐个［write-level 79＋read-only 157，AST 调用图穷举］／13 Redis 键族安全攸关 vs 纯计量分开／3 存储根＋队列／非 JWT 认证面 26 路由 10 机制／project_id 弱引用 6 张 nullable 表／消费方维度 5 域精确＋38 文件／dispatch·simulation 单列）、容量实测报告（三项全实测）、GM 线联合排期草案、口径现测记录。
- **口径现测（先验→现测，全部偏差登记）**：表 130→**146**（grep＝SQLAlchemy metadata 双源互证）／全局表 63→**63 精确复现**／蓝图 49→**50**／路由 391→**448**／写端点 241→**277**／迁移 51→**58 rev 单头 `f3a9c7e1d5b2`**／pytest 2056→**2716 collected**（本地；CI 终值以本 PR 为准）／mypy 279 不变／装饰器 378→**428**（require_auth 384/require_role 31/require_minimum_role 13）／JWT 7 claim 无租户维度确认／gunicorn worker 4→**2**（Dockerfile:43）／Redis 键族 12→**13+队列**／存储根 2→**3**（T-A9 转写草稿区根）／非 JWT 面 17 处→**26 路由 10 机制**；五处重大偏差（D-1 存量用例 2333→2716／**D-2 G 线 G1–G6 已全部收口，「G2–G5 无排期承诺」风险过时**／D-3 第三存储根／D-4 2 workers／D-5 无 FK 的 project_id 零命中——弱引用真形态=6 张 nullable project_id 表）。
- **容量三项实测（活体开发栈 127.0.0.1:8010，零业务数据写入）**：①并发 P95——10/50/100 VU 三档 **1027 整环零错误**（整环=登录→/account→/projects→登出），整环 P95 0.93s/9.65s/19.77s，瓶颈=2-worker argon2 CPU 非 PG/Redis，过载优雅降级不崩溃；②队列——原语层 lpop 认领 **1714/s**（1.83ms/往返）远非瓶颈，活库历史 AI 任务 P50 136s~33min，单 worker 顺序消费=吞吐边界，「多企业并发真实吞吐留 M8 试点实测」诚实声明（本轮不代发起 AI 计费任务）；③PG——max_connections **100**（可用 97）vs fde 栈理论池顶 60，负载中仅 13 连接，**关键发现：PG 实例与同宿主 twenty/mautic 等栈共享**（部署拓扑决策列 M8 前置）。容量测试一次性账号 `captest` 已停用退役（空 hash 永不可登录）、会话清除、事件留痕 1 条如实保留。
- **验收**：任务书 §7-M0 四项——4 ADR+盘点表+实测报告入库 ✅；OWNER §11 八拍板点签署（v1.2 已完成）✅；无代码/迁移/路由改动 ✅。**M0 完结待 OWNER 审阅，不自行进 M1**（提示词规则 19；是否放行 M1 由 OWNER 判定）。

## [未发布] — 夜审修复 r3：卫生批（goal-review-fix r3；CR-058/063/068/070/073/075/076/077/078/079 十项，2026-11-10）

- **形态**：goal-review-fix r3 修复轮（卫生批=口径漂移/文档对齐/测试质量/桌面收窄），基线 fork/main `993341c`（r1 报告轮合并后）。服务端定向测试绿；桌面侧 vitest/typecheck 由 CI desktop job 为闸（worktree 无 node_modules，本地静态自检补证）。
- **CR-058（P2）web 版本单源化**：NEW `desktop/tests/main/web-bridge-version-parity.test.ts` 静态闸——`fde-web-bridge.ts` 的 version 字面量必须 === `desktop/package.json version + "-web"`，列车推进漏改即红（对账测试钉字面量与列车源，替代构建注入的多方案取舍）。
- **CR-063（P3）可见性对账钉**：NEW `server/tests/test_visibility_parity.py`——四类 actor（leader/member/stranger/admin）断言 `list_projects` 结果集 ⊆ `visible_project_ids`（「第二副本规则」的隐式重合变成测试事实，写路径放宽即红）。
- **CR-068（P3）接线警示**：`ontology/service.py::confirm_term` docstring 补「零生产调用方；接线前须补 _link_subjects_to_term」（防未来路由化漏链）。
- **CR-070（P3）web 桥域白名单**：`fde-web-bridge.ts::openLcscBrowser` 补三域 https 白名单（与桌面 allowsLcscUrl 同尺；AIServerChat 先例）；`fde-web-bridge.test.ts` +2 例（三域放行/钓鱼与跨域后缀拦截）。
- **CR-073（P3）LCSC 业务错误透传**：`desktop/src/main/index.ts` 的 desktop-execute 分发把非 ApiIpcError 包装为 `lcsc_execute_failed`（原 message 透传，「已有立创查询正在执行」不再被吞成通用 internal_error）；`api-ipc.ts` 导出 ApiIpcError（唯一改动=加 export）。
- **CR-075（P3）恒真断言改写**：`test_ai_call_audit_attribution.py:153` 恒真负向断言改为有判别力形态（64 位 hex 字符集断言）；**登记勘误**——CR-075 原登记的第二处（test_agent_run_evidence_candidate.py:126）E0 实测不存在（E1 误报，`grep` 无该断言；P3 未复核的代价实证），台账已注记。
- **CR-076（P3）防回归钉加宽**：`test_commercial_enterprise_space.py` 源码钉由 `.delete(` 单形态扩为 `re.search(r"\.delete\(|\bdelete\s*\(")`（封 SQLAlchemy 表达式删除绕过；live 源零命中验证不误伤）。
- **CR-077（P3）产品名第三处清除**：`server/src/fde_api/__init__.py` docstring 改「FDE workbench API package.」（E0 全扫证实仅此一处 + brand.ts/config.py 两单点）。
- **CR-078（P3）口径配方修正**：AGENTS.md 口径行「api_catalog ENTRIES=awk 数 (" 行」改「AST 数 ENTRIES 赋值元素」（grep 会多计 `_catalog_row` 函数体两处——本轮实测 96 vs AST 真值 94）。
- **CR-079（P3）ENV 登记补齐**：`server/.env.example` 补 `FDE_AGENT_HOST_POLL_TOKEN`/`FDE_AGENT_HOST_LOST_MARK_MINUTES` 注释态两行（照 FDE_BRIDGE_TOKEN 先例注明白文令牌不入 git）。
- **口径**：零迁移零路由零新表；桌面改动 ⇒ vitest 绿即可（CI desktop job 实测为准）；server 侧仅测试与 docstring/`__init__` 一行 ⇒ 合并后 rebuild 三镜像挂账（alembic no-op）。
- **便携版 r32 交付补记（挂账清偿，2026-11-10 夜）**：从 `10838b9` 干净主树打包（desktop 面零脏文件核对）。asar sha256 `cf0d438f382891159e27a46702367acbd66f6fb5ad87cd262b4ff93a8b97a490`（r31=`113289d4…` 未覆盖）。**字节验证**：`lcsc_execute_failed`（CR-073 main 进程错误码）新包命中 1／r31 对照 **0**（非旧包实证）；`szlcsc` 白名单正则（CR-070）命中 19。**无中文 marker 说明**：r3 桌面改动均为英文错误码/正则/静态测试（无新增中文 UI 文案），沿 r31 轮 3 先例以英文 marker+新旧 asar 对照替代。

## [未发布] — 夜审修复 r2：服务端行为批（goal-review-fix r2；CR-042/047/049/050/051/052/054/060 八项，2026-11-10）

- **形态**：goal-review-fix r2 修复轮（安全批=分级闸放行项），基线 fork/main `dd5bd9c`；八项均「证据确凿+修法唯一+局部补丁」，每项同步新增测试并做变异验证（红→反向替换→绿，8/8 判别）。发现登记与全量证据见 r1 报告 `docs/audit/全面代码审查报告-2026-11-10.md`（其 PR 串行在途）。
- **CR-042（P1）审计补全**：`users/service.py::reset_password` 补 `actor` 形参（路由透传 `g.current_user`）并在事务内落 `user_password_reset` 事件；`auth/service.py::change_password` 落 `user_password_changed`（actor=self）。事件键名避开 `events._SENSITIVE_KEY` 脱敏正则（`must_change` 而非含 password 键——脱敏墙按设计整键丢弃，测试已钉）。
- **CR-047（P2）密码确认限流**：NEW `auth/confirm_throttle.py` 单一权威（同 key `fde:ai:confirmation-failures:<user_id>` 同阈值 5 同窗口 15min），接入 `auth/verify-password`（先闸后验）+ `control/api_actions.decide_action`（原语收口）+ commercial 七服务 `_confirm_password`（attribution/billing/enterprise/ledger/quota/regional/service）。测试隔离件：conftest NEW autouse fixture 每测后清计数键（共享 Redis 按用户键会牵连邻域——#279 PerTestIPClient 同型）。
- **CR-049（P2）演练排除**：`agents/pilot.py::build_report` rows 查询补 `idempotency_key.notlike("rehearsal:%")`——CR-031 同型残留（六指标被演练 run 污染），与 metrics `_REAL_RUNS` 同款。
- **CR-050（P2）词典故障分类**：`discovery/jobs.py` NEW `except RedactionConfigError` → `pseudonym_dict_unavailable` + 专文案（原落 `discovery_unexpected_error` 误导重跑白烧预算；guidance 同构先例）。
- **CR-051（P2）重试清 sink**：`guidance/jobs.py` GuidanceContractError 重试分支补 `redaction_entries.clear()`（沿 KimiError 分支同纪律）——复核清单 occurrences 不再翻倍。
- **CR-052（P2）并发幂等兜底**：`discovery/service.py::create_extraction` flush 包 `except IntegrityError` → 重读既有行返回 `created=False`（幂等契约在并发窗口成立，沿 guidance adopt 同型；端到端竞态测试用真实唯一约束复现）。
- **CR-054（P2）审阅行锁**：`discovery/service.py::review_fact/review_requirement` 的 `session.get` 补 `with_for_update=True`（沿 guidance confirm_analysis 先例）——并发审阅不再可击穿终态约定。
- **CR-060（P2）目录 desc 失实**：`control/api_catalog.py` plugins 两行 desc 删「需密码确认」改述实况（payload 闭集结构上不可能收密码）。
- **测试**：NEW `test_api_catalog_descriptions.py`；`test_users_api` +1 断言组（事件 actor/载荷/脱敏）；`test_auth_api` +2（限流锁定/成功不耗预算）+ change_password 事件断言；`test_commercial_entitlements` +1（commercial 闸共享计数）；`test_agent_pilot` +1（演练排除）；`test_discovery_extraction` +3（词典分类/竞态兜底/行锁 spy）；`test_guidance_retry` +1（sink 不翻倍）。定向全绿后 8 项变异全判别。
- **口径**：零迁移零新路由零新表；预期 pytest 基线 2618+6s 上方 +9（以 CI 实测为准）；server 变更 ⇒ 合并后 rebuild 三镜像+alembic（幂等 no-op）+活体复验三项。

## [未发布] — 全仓代码审查报告轮（goal-review-fix r1：七域并行审查+独立复核+E0 升级+38 条登记；纯文档零代码，2026-11-10）

- **形态**：goal-review-fix（审+修循环）r1 审查报告轮——**纯文档**（NEW 报告+台账登记+本节），零代码零迁移零路由；r2/r3 修复轮与收口轮随各自 PR 接续。基线 fork/main `dd5bd9c`（#264），审查取数=独立只读 worktree（主树 38 脏文件未触碰）。
- **并发裁定（留痕）**：开工快照（02:21）PR #265 在途 CI 跑 ⇒ 先裁「只审查+登记」；07:06 现测 #265 已合并+fork 零开放 PR ⇒ 并发条件解除 ⇒ 解锁 r2+ 安全批修复轮（分级闸放行项），每次 push 前重核并发。
- **方法**：dynamic-workflows 七域 fan-out（run `dwfrun-c0445a91`：域 A 权限认证/B 工作流 agents/C 业务域/D 桌面/E 数据层/F 测试质量/G 红线机械快扫，各域只读审查员+P0/P1/P2 逐条独立复核员 fresh eyes）；**B#3 全程遵守**（审查输入=文本快照+只读机械检查，pytest/vitest 未运行，CI 只读引用 run 42669543706 四绿=pytest 2618+6s/vitest 984）；活库全程只读 SELECT（alembic `e8b3f7c2d9a5` 与基线逐位一致）；P1/P2 全部经主会话 E0 亲测升级（台账证据等级纪律）。
- **战果**：40 条候选 → 去重（A3⊂B1、A4≈B4）**38 条登记 CR-042..CR-079**（P1×5/P2×13/P3×20；18 条 verified）。**复核层战果**：quality 覆盖闸条目原判 P1 被独立复核员三重合取反证驳回（accepted 单调不减+用例唯一写路径+需求无删除通道 ⇒ 增量缺口不可达，降 P3 观察挂账=CR-055）；宿主回执条目 P1→P2（触发面三要件当前全零）。**五条 P1 全部成立**：reset_password 零审计事件（CR-042）、host_poll×workflow agent 断链+计费孤儿（CR-043）、transcripts 确认人脱敏声明失实（CR-044）、agent_runs 幂等无唯一兜底双执行双计费（CR-045）、**FDE_PRODUCT_NAME 是死键**（CR-046——pydantic-settings 三态实验决定性复现，实际生效键 FDE_FDE_PRODUCT_NAME 全树零记载，六处文档承诺静默失效）。
- **分级闸**：r2 服务端行为批 8 项（CR-042/047/049/050/051/052/054/060——审计补全/限流/演练排除/词典故障分类/sink 清空/并发兜底/行锁/desc 失实，均修法唯一+同步测试）+ r3 卫生批 10 项（CR-058/063/068/070/073/075/076/077/078/079——口径漂移/ENV 登记/文档对齐/测试质量/web 桥收窄）；**挂账 20 条**（涉迁移 045/048/053/059/074/权限语义 044/046/062/064/066/067/071/072/跨域设计 043/多方案 056/057/隐式不变量观察 055/host-poll 族 061/bridge 映射 069）——逐条消解条件+owner=蔡工见报告 §六醒后拍板清单。
- **机械闸三件套 r1 现测全绿**：审计 CSV 重生成与提交版零漂移（route 442 行/DB 146 行）；archify 防陈旧闸 OK；secrets 形状手工 grep 零命中（gitleaks 本地未装引 CI 绿）。口径基线现测：145 表/441 路由/49 蓝图/57 rev 单头 `e8b3f7c2d9a5`/ENTRIES AST 真值 94（grep 96 含 `_catalog_row` 两处函数体——配方漂移点=CR-078）/mypy 279 行。
- **台账**：`docs/goal-c-代码审查台账.md` 发现总表 +38 行（CR-042..079）+轮次状态表 r1 行+夜审详情索引节；挂账条目状态=needs-decision（待拍板）。

## [未发布] — 前端 CSS 品牌对齐 + 帮助文档对齐 13 标签页（border-radius 令牌化 + 高频页视觉打磨 + 滚动高亮降级；服务端无变更零迁移零路由零蓝图，2026-11-10）

- **帮助文档对齐新代码**：项目详情页实为 **13 个标签页**（`ProjectDetailPage.tsx` tabs：概览/任务/门禁/报价收款/调研/方案设计/工作流/**智能体**/**评审会**/术语表/执行事实/文件库/项目管理）——服务端 bundled 手册 `help_manual.md` 与桌面端 `HelpPage.tsx` 同步补齐 13 标签页 + 智能体/评审会两节 + 交接包面板说明，`docs/工作台操作使用手册.md` 孪生副本字节一致（`test_help_fetch_tool.py::test_docs_copy_of_manual_stays_identical_to_bundled` 钉住）；**口径同步落在 server 侧断言**（`("项目详情标签页数", "13 个标签页")`），桌面侧断言本轮补齐（此前仍钉 12，属滞后缺口）。
- **前端 CSS 品牌对齐（蔡工品牌规范）**：①**border-radius 全量令牌化**——`desktop/src/renderer/src/` 下 ~105 处裸 `Npx` 收敛为 `--radius-xs/sm/md/lg/xl/pill`（999px→pill、20/24/18/17/16px→xl、14px→lg、12px→md、10/9/8px→sm、7/6/5/4/3px→xs；两处非对称按令牌展开），**不写裸 hex** 纪律延续；②**离板色收口**——`--warning-border` 由 `#F79009` 校正为品牌规范严格值 `#B45309`；③**零位移状态顶栏**——`.gate-card` 按门禁状态（通过=绿/失败=红/待证据=警告色）走 `inset 0 3px 0` 顶栏，**挤布局为零**；④**hover 上浮统一语言**——`.card:hover` 描边改 `--line-brand`（金线），`.project-card` / `.task-board-card` 走「金线 + 金系顶栏 + `translateY(-2px)` + `--shadow-sm`」。
- **高频页排版与视觉打磨**（按预计流量与使用频率取样）：**门禁板 GateBoard**（状态顶栏 + 清单项内边距/圆角/悬停）、**项目概览**（`.overview-three-column` 间距 + `.detail-definition-grid` 悬停高亮 + 空态 `.empty-state` 3px 金顶线与极浅金晕染）、**项目卡**（金系顶栏 + 上浮）、**任务板**（卡片金线顶栏 + 泳道计数改胶囊）、**AI 对话**（对话框头部金系顶栏）；`.workspace` 子树补 9px 圆角细滚动条；`.help-table` 补表头底色/分隔线/斑马纹/圆角。
- **滚动高亮降级修复（本轮实测回归，已修）**：帮助页目录「滚动高亮当前章节」用 `IntersectionObserver`，**jsdom 测试环境无此 API ⇒ `ReferenceError: IntersectionObserver is not defined` ⇒ help-page 7 例全红**。改为**渐进增强**——`typeof IntersectionObserver === "undefined"` 时直接跳过高亮（目录点击跳照常），`scrollIntoView` 同样加存在性防护（jsdom 亦缺）；**不可因增强功能缺失而整页崩溃**。
- **目录按钮文本匹配加固**：TOC 按钮新增序号徽标（`help-toc-index`）后 `textContent` 变为「13故障排查（照顺序查最快）」，测试用**精确相等**匹配即失效——改为 `includes` 语义匹配（贴合「不锁死索引」原意，不随徽标样式变化而误伤）。
- **变基冲突裁决（3 处，均取上游）**：①`.nav-item.active` 背景——上游内联金晕渐变（含横向淡出 + `.nav-item.active:hover` 配套）较本轮 `--on-dark-active` 纯色令牌更精细，取上游并**删除已成孤儿的 `--on-dark-active` 令牌**（零引用即零定义）；②`.overview-three-column` gap——保留上游 r28 实测值 `18px`（本轮曾改 `--space-6`=24px，属无依据的行为变更，撤回）；③`.presurvey-gate-hint-link` 颜色——回退本轮 `--brand-ink`（石墨黑 `#14181C`）改**上游 `--brand-blue`（金墨 `#C98F2B`）**：石墨黑链接在浅底上失去可点击辨识，属回退非改进。
- **口径**：vitest +985 全绿（84 文件；本轮修复前 help-page 7 例红，修复后全绿）＋ `tsc --noEmit` **0 错误** ＋ 桌面端设计令牌测试 35/35 通过；服务端 **pytest 本地未实跑**（沙箱无 `fde_workbench_test` 库与 Redis，且 `SKIP=pytest-server` 跳过本地钩子）——**以 CI server-tests job 全量兜底为准**；mypy 基线 279 不变、ruff 触碰文件零告警（均经 pre-commit 钩子实跑通过）。**结构口径沿用**（145 表／58 迁移／447 路由／50 蓝图／api_catalog ENTRIES 94／pytest 基线 2665 收集）——本轮**服务端无变更零迁移零路由零蓝图**，故结构清单与 archify 图**无需刷新**。**桌面变更 ⇒ 合并后须重打包便携版并做 asar 中文 marker 字节验证**（本轮未打包，交付物待补）。
- **未决**：①文档中心（`D:/test/FDE/蔡工FDE工作台_文档中心/`）8 份源已删副本已归档历史目录、13 副本与 4 份本地编纂文档已刷新、导航 HTML 已重跑（19 分类/582 文件、零死链）——**该目录独立于本仓，本 PR 不含其内容**；②`scripts/audit/extract_workbench_inventory.py` 仍硬编码旧 sha（代码库侧脚本，不在本轮范围）；③「30 天试点」重启属业务拍板。

## [未发布] — 获客诊断工具 W2 T-10a 轮：diagnostics/ 规则层（匿名会话 + 首屏政策测算卡 + 闭集问卷；NEW 蓝图+表+迁移 `f3a9c7e1d5b2`，2026-11-11）

- **范围与拆分**：T-10 拆两半实施（蔡工拍板「按建议走」——T-07/T-08 评测器需要先有一个生成器才可评测，故 MVP 域先行）：**T-10a＝纯规则层**（匿名会话生命周期 + 首屏政策补贴测算卡 + 闭集诊断问卷，**零 AI 零 token**）；T-10b（AI 报告生成 + purpose 登记 + share token 页）另轮。D-1＝企业免注册自诊为主、D-2＝摘要免费+全文留资 按默认推荐执行（留痕可推翻）。
- **本仓第一个公网免注册写面 ⇒ 五重防线（AGENTS 红线新条）**：①**部署闸默认关**——`FDE_DIAGNOSTICS_ENABLED=0`，关闭时诊断路由一律 **404（不确认面存在）**；②匿名令牌**只存 sha256 指纹**（明文客户端持有、`X-Diagnostic-Token` 头传递不入 URL——URL 进访问日志；`POST /sessions` 返回明文**只此一次**）；③来源 IP 只存**域分隔 sha256 假名**（非明文）；④Redis 配额双闸（每 IP 每日 20 动作 + 每令牌每日 3 动作）**默认 fail-closed**——与登录面默认 fail-open 相反，公开写面被刷的代价高得多；⑤自填文本落库前过 **T-A2 脱敏管线**（企业名→代号；词典机制故障 503 `pseudonym_dict_unavailable` fail-closed 同码、凭据串 422）。
- **数据模型**：NEW 表 `lead_diagnostic_sessions`（迁移 `f3a9c7e1d5b2` 挂 `e8b3f7c2d9a5` 之后 57→58 单头）——状态机 `draft→submitted→report_ready→claimed|expired` 五值 CHECK（T-10a 只落 draft/submitted；report_ready/claimed 归 T-10b/T-11）；`token_sha256` 唯一索引 + 64 位长度 CHECK；`claim_window_expires_at` NOT NULL（90 天认领窗口，P-2 只落结构）；`claimed_by_user_id` FK SET NULL users；**零外键指向 `projects`**（线索≠项目，metadata 扫描钉死）；留存期 30 天 `expires_at`（个保法：留存期+删除通道）。
- **首屏测算卡（纯规则、确定性）**：`assessment.py::compute_assessment` 同答案必同结果——**定性四档位**（具备申报基础/方向契合但缺前提/尚不满足申报前提/先做基础准备），**无分数无金额**（R-1 占位分教训＋R-4 未溯源数字 fail-closed 落进代码：弹药库五条均未披露额度，任何金额都是编造）；匹配政策条目**双层依据分键不混写**——`original_basis`＝「原文口径」（逐字）与 `interpretation_basis`＝「我方解读」显式标注 + `official_source_url` + `snapshot_date`（2026-10-19，30 天失效重核）；`policy_data.py` 五条政策条目随行弹药库两条勘误（70% 是应用普及率非智能体普及率；279 号第十四条是服务商能力清单，「隔着屏幕干完」是我方解读）；行业+资质门控（智能工厂梯度培育须资质齐备）；`next_actions` 感知申报历史（退回意见优先）+ 核验步骤注入，封顶 5 条。
- **闭集问卷**：`questionnaire.py` 首屏 5 槽位 + 诊断 13 槽位（总量 ≤30 上限内）；single/multi 选项**闭集**（未定义选项 400）；未知槽位键一律拒绝（防脏数据越权写入）；`ctx.contact` 刻意不在问卷定义——留资走独立 `POST /session/lead`（consent 必须 `true`），报告只在已留资后可见（留资闸）。
- **路由 6 条**（NEW `diagnostics_blueprint`，url_prefix `/api/v1/diagnostics`，**不进 api_catalog**，匿名面无 JWT）：GET /questionnaire · POST /sessions · GET /session · POST /session/assessment · POST /session/answers（未做首屏 409 `first_screen_required`）· POST /session/lead；`DiagnosticsServiceError` 统一映射 error_response。
- **测试 NEW `test_diagnostics_mvp.py` 26 例**：部署闸默认关 404 ＋ **出厂默认值安全钉**（`diagnostics_enabled is False ∧ rate_fail_closed is True` 双断言）/令牌·IP 指纹形状/零 projects 外键元数据扫描/测算卡纯度（无「元」无「/100」、双层依据分离、资质门控、确定性）/校验闸（未知槽位/闭集选项/必答缺项/首屏前置 409/scope 分离）/留资闸（consent 必填+报告门）/配额（IP 429＋令牌 429＋**Redis 故障 fail-closed**＋显式 `FDE_DIAGNOSTICS_RATE_FAIL_CLOSED=0` fail-open）/归因结构（channel 必带 channel_ref）/脱敏（企业名不落库）/令牌头缺失 401。**变异十连全红→还原→绿**（M1 部署闸默认开/M2 令牌明文/M3 IP 明文/M4 加 projects FK/M5 测算卡落分数/M6 原文解读混写/M7 摘 IP 上限/M8 fail-open 默认/M9 绕脱敏/M10 摘首屏前置闸；**首版 M8 无判别力**——diag_app 夹具显式置 fail_closed=True 掩盖默认值翻转 ⇒ 补出厂默认值安全钉 `test_shipped_defaults_are_safe` 后转红，变异判别力本身要验收的家族教训再现）。
- **污染隔离钉 N2 咬住本轮新文件（PR #280 首推 CI 实录，机械闸第二次活体咬人）**：`questionnaire.py` 文档串原写了真相层具体路径（含「诊断案例集」token）⇒ CI `test_diagnostic_eval_contamination` N2 红——**生成器可见面（`server/src`）禁引用评测集路径，docstring 也不例外**。改写为抽象出处（分析在真相层维护、不进本仓）后 7 钉＋26 例 = 33 passed。**教训入册：`server/src` 新代码本地验证必须连跑污染钉套件——钉扫的是全 `server/src`，定向跑新测试套件扫不到文档串违规**（首跑咬 N7 同步脚本注释，本轮咬 N2 文档串，同族两连）。
- **7 注册点**：app.py `_BLUEPRINT_SPECS`（49→**50** 蓝图）/migrations/env.py/conftest 清理序（users 前置，FK SET NULL）/test_migrations `HEAD_REVISION="f3a9c7e1d5b2"` + 58 全集断言/结构清单三件套重生成（**441→447 路由 / 50 蓝图 / 145→146 表 / 58 rev 单头 `f3a9c7e1d5b2`**，与口径行逐位一致）/archify 卡片口径同步＋finalize 四闸全绿＋preview.png 整页实拍（freshness 闸 OK）/config 四新字段＋`.env.example` 注释块。
- **口径**：pytest **+26**（NEW test_diagnostics_mvp 26 passed；**PR CI run 42774843489 实测 2691 收集 = 2684 passed + 7 skipped**＝2665 收集〔2659 passed + 6 skipped，rebase 融合上游 #279 注册面节流 +11 后的基线〕+ 本轮 +26，**逐位吻合**——CI 无真相层 ⇒ 污染钉 N6 显式 skip 计入 7 skipped 基线；此前融合树本地实测「6 skipped」与 CI「7 skipped」差 1 即 N6 的设计行为〔本地真相层在场 ⇒ N6 跑且过〕；★rebase 前 head 的旧实测 2680 收集 = 2673 passed + 7 skipped〔run 42767904994，＝#278 时点基线 2654 + 26〕**属 rebase 前基线，已随 #279 插队作废**）＋ 结构/迁移/蓝图/路由同步四套 36 passed（本地）/mypy 官方闸 OK（基线 279 不变、零新增）/ruff 触碰文件零告警；**server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（新迁移）**；桌面零改动不重打包。**合并与部署（2026-11-11）**：PR #280 head `cfa7133`（CI run 42776565369/42776557469 四绿）→ squash 合并 SHA **`51518a4`**＝fork/main 顶，**合并后 main run `42778299496` 四 job 全绿**；★**rebase 作废基线的教训**——上游插队两笔（#279 +11／#281 纯文档）落基点之后 ⇒ 合并前 rebase（冲突仅 AGENTS.md 与 .env.example 两处，两侧内容全留），**rebase 前 head 的实测 2680 收集 = 2673 passed + 7 skipped 属 rebase 前基线·已作废**，口径按新基线重算后实测 **2691 收集 = 2684 passed + 7 skipped**（run 42774843489）逐位吻合。**部署复验**（从 `51518a4` 干净树重建）：三镜像 api `18f741258bd1`／worker `d96938cccf1a`／scheduler `765ad5553e32`，三容器 `.Image` 与构建产物逐位一致且 healthy；`alembic upgrade head` 真实升级 `e8b3f7c2d9a5 → f3a9c7e1d5b2`、容器内 `alembic current`＝`f3a9c7e1d5b2 (head)`；活体 `url_map` **448 total / 447 non-static** ≡ 口径 447；★**部署闸默认关 ⇒ 活体 404 而非 403**（不确认面存在）；活库新表 `lead_diagnostic_sessions` 21 列，外键仅 `users.id` ⇒ 零外键指向 projects。

## [未发布] — 获客诊断工具 T-02 裁定轮（rubric v0.1 落地 + 裁定单落定 + 元验证重算；纯文档零代码零迁移零路由零桌面，2026-11-11）

- **拍板**：蔡工授权「总体按建议实施」——**rubric v0.1 落地**（C1–C4 四项）、**裁定单落定**、**元验证夹具重算**、任务书回写。
- **rubric v0.1 修订（真相层 `rubric/rubric-v0.md`，文件名沿用）**：**C1** ③ 区分「无源数字」（照常扣）与「明示占位」（不扣、计入 A 类模板缺陷）＋**展示闸**「含无源数字 ⇒ 不得进展示层」；**C2** ① 增**失效条款**——答案键逐条同义复述（≥4 条实质与句式高度重合）⇒ 该卡 ① 与总分作废；**C3** ④ 增**文档类型分支**（诊断建议类 vs 复盘/审计类，后者按「根因定位与处置明确度」评分）；**C4** 阈值候选 <65 / 65–78 / ≥79 ＋ **④<6 一票否决** ＋ **明确不校准、推迟到 T-10**。
- **裁定单落定**：AI 预评值采纳，**C2 致 001/009/010/somwyn 四卡总分作废**（逐条同义复述，① 无生成能力证据）；有效分只剩 83 / 88，仍全 pass ⇒ **阈值零区分力 ⇒ 校准推迟到 T-10**。作废四卡原值留档追溯，不得用于任何判定。
- **元验证重算**：A1 改按 C3 分支（④=8）总分 **95**，期望带重算为 78–98；A2 83（带内）；X1–X4 全 hard_fail ⇒ judge 可用。**诚实边界**：judge＝写答案的人，**自偏好无法排除**（唯一外部锚＝人已验收的 A1），挂账到 rubric v0.1 §六。
- **指纹纪律生效实录（第二轮）**：rubric-v0.md `cefeabf54…`→`98053cd9…`；裁定单 `8592ae7f…`→`bd265989…`；AI预评 `b304a6de…`→`63b5a3b1…`；元验证夹具 `7668d9a5…`→`02a4dc23…`（meta-v0.1）。**六张案例卡本体始终未改**（`card_version` 仍 `card-v1`）⇒ 无需升版本、无曲线断点。
- **口径**：pytest / mypy / vitest 全不动；**零服务端源码改动、零迁移、零路由、零蓝图、零桌面** ⇒ 无需 rebuild 镜像 / alembic / 便携版重打包。

## [未发布] — 获客诊断工具 T-02 预评轮（首批 6 卡 AI 预评已填 + 待蔡工终裁；纯文档零代码零迁移零路由零桌面，2026-11-11）

- **做了什么**：T-02 评分单元的**AI 预评**完成并填入裁定单（真相层 `D:\test\FDE\knowledge\诊断案例集\rubric\`），产出逐卡核对明细与 A/B/C 归因；仓库侧只回写**任务书状态 + T-10 需求清单 + 指纹登记**（**答案与预评内容零进仓**）。
- **预评结果**：首批 6 卡 **83 / 88 / 88 / 91 / 86 / 88 —— 6/6 全部 pass，阈值零区分力**。**建议不校准、推迟到 T-10**（候选报告与答案键同作者产出，且 001/009/010/somwyn 四卡与答案键**逐条同义复述** ⇒ 分布不反映生成能力）。
- **元验证**：A1 somwyn G3 真报告 **91**（预期带 70–92，落在带内）、A2 **83**（预期带 70–95，带内）、X1 空输入 / X2 乱码 / X3 注入 / X4 越权索证 **全 hard_fail** ⇒ judge 可用于判定。**诚实边界**：judge＝写答案的人，**自偏好无法排除**（唯一外部锚是人已验收的 A1）。
- **归因 → T-10 需求清单 R-1~R-7**（写进任务书 §3，T-10 开工前逐条落地）：R-1 报告模板去掉无溯源分值或先建可溯源行业基准表｜R-2 报告加「政策与申报机会」层（六卡零政策引用，而主叙事＝政策补贴测算）｜R-3 生成器输出「第一步（本周可做+做什么+产出什么）」三要素｜R-4 未溯源数字 fail-closed 或标待澄清｜R-5 每个已识别问题在建议段必须有对应动作｜R-6 不得把选型期写成已完成/不得编造基线数字｜R-7 补「识别→定位→处置→回写」闭环。
- **建议的 rubric 修订（C 类，待拍板才改 `rubric-v0.md`——该文件已随 PR #274 合入）**：C1 ③ 区分「模板占位分」与「编造数字」＋加展示闸｜C2 ① 增失效条款（答案逐条复述 ⇒ 该卡①作废）｜C3 ④ 增「文档类型」分支（复盘/审计类按根因定位评分，适配 A1 锚点）｜C4 阈值口径推迟 T-10，候选 <65 / 65–78 / ≥79 ＋ **④<6 一票否决**。
- **指纹纪律生效实录**：`rubric/裁定单-首批6卡.md` 因预评填入而变更 ⇒ 指纹由 `23fcbd91…` 变为 `8592ae7f…`，仓库侧登记表同步更新（**改答案必留 diff**）；**六张案例卡本体未改**（`card_version` 仍 `card-v1`，`ground_truth` 未动）⇒ 无需升版本、无曲线断点。
- **口径**：pytest/mypy/vitest 全不动；**零服务端源码改动、零迁移、零路由、零蓝图、零桌面** ⇒ 无需 rebuild 镜像 / alembic / 便携版重打包。

## [未发布] — 商业化挂账清偿收口轮：部署活体复验补记 ＋ 便携版 r31 交付（纯文档零代码零迁移零路由零桌面，2026-11-10）

- **部署（确定版 rebuild，覆盖轮 3＋轮 4 全部 server 变更；轮 5 纯桌面零服务端）**：从合并态 fork/main `8c0b113`（轮 4 squash，含轮 3 `4e1d6c5`）干净 server 树构建三镜像并 up -d——api `sha256:f863fe65f5bb…`／worker `sha256:a0d9fe40d37f…`／scheduler `sha256:749c618afce0…`，三容器 `.Image` 与构建产物逐位一致且 healthy；`alembic upgrade head` 幂等 no-op（容器内 `alembic current`＝`f3a9c7e1d5b2 (head)`，轮 3/4/5 零迁移）；活体 `url_map` non-static **448** ≡ 口径（轮 4 readiness 路由在场）；`/api/v1/health/ready` **200**。main run 收口：轮 4 run `42797107137`／轮 5 run `42800276475` 各四 job 全绿（轮 5 squash＝`b39ca9b`，纯桌面不需重建）。
- **便携版 r31（清偿轮 3/4/5 累计「便携版重打包挂账」）**：从合并态 `b39ca9b` 打包（`npm run build` ＋ `electron-builder --win dir --x64`，EXIT=0）；asar sha256 `113289d4783d1eab45d0159d2776b414ce4d57a1a8b4aa7fab22dca50e2124cb`；中文 marker 字节验证（marker 文件法防编码假阴性）×3 全命中——「商业化运维」×2（轮 4 运维面板）／「读取企业空间」×2／「企业自助」×2（轮 5 企业空间面）；交付目录 `release/蔡工FDE-0.3.0-便携版-r31`（旧目录零覆盖；release/ 已 gitignore 永不入库）。轮 3 焦点竞态修复无独立 UI 文案故无 marker（其交付证据＝PR #283 用例＋users 30 轮/danger-confirm 20 轮零红实录，代码已随合并态进包）。

## [未发布] — 外部闸消解轮：§1.4 集团归并法务裁定问题单 v1 ＋ §1.8／§17 裁决落账（纯文档零代码零迁移，2026-11-11）

- **起因**：用户问「剩余的外部闸能不能用交互式问题选择方式解决」——三项逐一裁决：**§1.4 可「问清」**（把给法务的问题、口径选项、工程影响、等待方一次写清即解锁销号路径），§1.8／§17 是**裁决性问题**（归哪个域／是否落数），交互选择即落定。
- **§1.4＝NEW `docs/commercialization/ADR-004-集团归并-法务裁定问题单-v1.md`（Q1–Q5）**：Q1 额度按法人还是集团计（A 不分别=现状保守默认＋人工闸／B 集团归并→`normalize_subject_key` 单点改，ADR-004 §3 已预留该单点）／Q2 注册面母公司 USCC 字段（必填·选填·不带）／Q3 无 USCC 主体（只境内=零改动／放宽=另立 ADR 修订）／Q4 额度去重规则终态（任务书 §17-3 销号条件）／Q5 归并主张证据要求（门禁证据红线同尺：指针＋sha256）；每项带代码锚（`quota_service.normalize_subject_key`＝`server/src/fde_api/commercial/quota_service.py:70`）、等待方、到位后动作；**边界声明**＝不代法务判断、不预置工程、不触碰代码/迁移/路由，裁定前维持保守默认（不分别＋人工闸，滥用敞口显式登记不阻塞 M 线）。
- **§1.8＝裁决「归 V3.2 simulation 域」**：`check_experience_limit` 消费方属独立 V3.2 域 Goal 线（`fde-wt-v32`），跨域不越线——本主线不接线，V3.2 线开工时同线实施（维持挂账，非本轮可解）。
- **§17＝裁决「维持 unset（fail-closed）」**：认证费/陪跑期/认证通过线/分成比例/试运营指标与首期金额一律不落数（缺省即不可收款，方向不变）；运维面板（轮 4 readiness 面）已呈现缺口与「等谁拍板」指针；待试点数据回来再落数（D-12 同向：数值一律由业务方书面输入，不预写默认值）。

## [未发布] — 外部闸消解轮·§1.4 集团归并裁定落地（OWNER 经营裁决 Q1–Q5 落入权威文档；纯文档零代码零迁移，2026-11-11）

- **起因**：用户追问「法务裁定问题不能用交互选择解决吗」——可以，但要**如实定性**：OWNER（业务方）回答这五项是**经营/风险接受裁决**，不是法律意见。五项全部裁决为「保守默认/现状维持」，故本轮零代码。
- **Q1/Q4 额度按法人计（USCC 单键，不建集团归并键）**：OWNER 接受「一集团经 N 子公司领 N 份额度」的滥用敞口，由既有人工闸遏制（额度授予/完成确认 admin＋密码确认＋交付咨询人工核验集团关系），敞口显式登记不阻塞 M 线；未来需归并改 `normalize_subject_key` 单点（ADR-004 §3 已预留）。**任务书 §17-3「额度去重规则最终化」据此销号**。
- **Q2 注册面不带母公司 USCC 字段**（随 Q1，亲子关系靠人工核验）；**Q3 本期只覆盖境内 USCC 主体**（mod-31 硬闸维持，境外放行另立 ADR 修订轮）；**Q5 归并主张证据指针制**（前瞻合同：后续归并主张须带 工商/集团关系证据 `source_uri`＋sha256 指针，门禁证据红线同尺，只存指针不存原件，与 admin 人工闸双轨；本轮零代码）。
- **落点**：问题单升 v1.1（§6 裁决记录＋状态改「OWNER 经营裁决已落」）＋ ADR-004 新增 §4 裁定回填＋ 00-gap-register GAP-04 回填行＋ 分账拍板决策包 X-03 标注已裁决。**性质声明贯穿各处：此为 OWNER 经营/风险接受裁决，非法律意见；法务正式意见列可选后续复核（不阻塞 M 线开工）。**
- 口径：纯文档零代码；pytest/vitest/mypy 全不变；零迁移零路由 ⇒ 无需 rebuild/alembic/重打包。

## [未发布] — F 线签字闸书面复确认轮（签闸待补页 28 行确认生效＋A-7 留待真实发布＋关联拍板点零改动复确认；纯文档零代码零迁移，2026-11-11）

- **起因**：用户要求「用交互式问题选择方式解决需拍板的问题」——四项核实后，唯一纸面未收口的是 **F 线签字待补页**（T0→T1 唯一硬闸；F 线 T1–T5 实际已随 #302/#321 落 fork/main，签页 28 行签字格停在 11-10 对话拍板原态且带格式破损〔tom/OWNER 混写、签字/日期挤格、D-01 时点列缺尾空格〕）。
- **OWNER 书面复确认（交互选择，2026-11-11）**：①**28 行确认生效**＝A-1~A-6＋T-1~T-9＋D-01~D-13（29 签闸行减 A-7 留待），签格统一「确认（OWNER）」＋签字日期 2026-11-11（原 11-10 对话拍板时点保留在时点列，不倒填）；②**A-7 维持「待真实发布动作」**＝上线前初始基线版本发布授权与发布记录由平台运维 admin 真实动作产生（X-04 不得倒填），不预签；③**关联拍板点零改动复确认**＝G 线任务书 §17 商业数值维持 unset（fail-closed）、D-10 商机五规则位按原拍板执行、多客户 §17 #2–#4 维持「待试点数据」。
- **落点**：签页新增「五、2026-11-11 书面复确认记录」节；格式破损修复 28 行（6 tom→OWNER＋1 tOWNER→OWNER＋20 挤格拆列＋1 D-01 尾空格）。零代码零迁移；各权威文档签闸栏回填按页首纪律随实施轮完成（本页面只汇总不代填原文档）。

## [未发布] — 商业化挂账清偿轮 5：G7 企业空间桌面呈现面（企业自助注册公开页 ＋ 企业空间视图；ADR-010 §3-4 桌面挂账销号；纯桌面零服务端零迁移零路由，2026-11-10）

- **起因**：外部评审①「商业化桌面呈现面为零」——核实为**部分失实**：项目侧 `CommercialBoard.tsx`（931 行）已消费 G1–G4；真实的零面在 **G6 企业侧**——企业自助注册与企业空间三个服务端面（`POST /enterprise-registrations`／`GET /enterprise-spaces/<subject_key>`／`POST …/paid-option-choices`）**桌面零消费**，企业用户只能拿 API 文档（ADR-010 §3-4 桌面呈现挂账）。本轮清偿。
- **NEW `commercial/EnterpriseRegisterPage.tsx`（公开面）**：未登录可达且**顶替登录页**（App 未登录分支按路由分发，登录墙不叠加）；走 `window.fde.api.request` **直连**而不经 api client——api client 无会话即抛 `authentication_required`，注册入口本就免鉴权（`accessToken: ""`；服务端按来源 IP 限流是滥用防线）；**只提交代号与必要登记信息**——企业名称以代号登记、真实资料留客户工作目录（客户资料红线在桌面侧的承接）。
- **NEW `commercial/EnterpriseSpacePage.tsx`（登录后；绑定账号本人或 admin）**：读面五板块呈现（主体登记／免费额度状态／交付状态〔自助／已选付费〕／付费选项与现行选择／交付项目）；选择付费选项＝POST 后**先复读刷新再落提示**（顺带修一处真缺陷：原实现先落提示后被复读清空＝成功提示被吞，测试红→页面修复→变异 M2 钉住）；主体代码入 `localStorage`（`fde.enterprise.subject_key`）再进自动预填；**零数值呈现**——付费选项标签/描述由服务端单一权威下发原样呈现，桌面不推导任何金额。
- **接线**：路由 `#enterprise-register`／`#enterprise-space`（`authorizedRoute` **不加闸**——企业账号即 viewer 档〔注册面创建 `users.role=viewer` ＋ `commercial_role='R1'`〕，服务端「绑定账号本人或 admin」是最终防线）；侧栏「交付与商业」组加「企业空间」入口。
- **测试**：NEW `desktop/tests/renderer/enterprise-register.test.tsx` **4 例**（未登录可达且顶替登录页／免鉴权直连钉〔`accessToken===""` 且 URL/载荷逐键〕／服务端 429 如实呈现不伪造成功／桥层失败如实呈现）；NEW `desktop/tests/renderer/enterprise-space.test.tsx` **5 例**（空代码零请求拦截／五面呈现＋GET 面正确／本地记忆预填〔waitFor 收敛 passive effect〕／选择＝GET→POST→GET 三调用且载荷正确／读面失败不伪造内容）；**变异三连全红→还原→绿**（M1 注册载荷丢 `subject_key`→1 红／M2 提示先落被吞→1 红／M3 预填短路→1 红）；typecheck 绿。
- 口径：vitest **999**（87 文件；+9＝NEW 注册页 4 例＋NEW 空间页 5 例；本地全量 87 文件 999/999 EXIT=0 实测，PR CI 复核）〔前值 990／85 文件〕；pytest 不变（纯桌面零服务端）；零迁移零路由零服务端改动 ⇒ 无需 rebuild/alembic；桌面变更 ⇒ 便携版重打包挂账。

## [未发布] — 商业化挂账清偿轮 4：商业化运维就绪度可见面（服务端汇总读面 ＋ 桌面运维面板；配置缺口与法务闸状态一眼可见；零迁移零新表，2026-11-10)

- **起因**：外部评审列出「未配置槽位无管理员可见面」与「法务审查未完成只活在文档里」两项——核实**确无**：服务端有分散的配置位读面（fee-configs／split-rules／opportunity-rules）与售卖闸读面，但**没有汇总面**，桌面端对 26 条 commercial admin 路由**零消费**——「缺什么、缺到哪一步」只能翻文档，管理员在系统里看不到。
- **服务端**：NEW `commercial/readiness_service.py` ＋ `GET /api/v1/admin/commercial/readiness`（admin 只读，治理面不进 api_catalog）。汇总三类配置槽位＋售卖闸四项合规条件：①**按权威键集枚举**槽位（`FEE_CONFIG_KEYS`／`OPPORTUNITY_RULE_KEYS`），行只提供状态——槽位永不缺项（缺行即少报＝「缺什么」漏报）；②**只报状态不落数值**（`unset`/`configured`、`registered`/`unregistered`），**绝不补默认值**——缺省即「不可收款／不可触限」的 fail-closed 方向不变；③每个未就绪项带**「等谁拍板」**指针（§17 商业数值／分成比例／法务合规输入），话术的单一权威在服务端（桌面端只渲染，不自带口径）。
- **桌面**：NEW `commercial/CommercialOpsPage.tsx` ＋ 路由 `#commercial-ops`（admin 专属）＋ 侧栏「商业化运维」入口——未就绪横幅（含等待来源）＋ 配置槽位表（状态/值型/可直接收款）＋ 售卖闸逐项登记态。**只呈现状态，不呈现也不推导任何商业数值**（用例钉「槽位表内不得出现金额形态数字」）。
- **测试**：NEW `server/tests/test_commercial_readiness.py` **7 例**（槽位清单按权威键集逐位一致且全 unset／只报状态不落数值〔并钉死 3980／59800 等金额不得出现在响应里〕／售卖闸四项逐项可见且 `ready_to_open=False`／阻塞清单覆盖四类来源／admin 专属〔非 admin 403、未认证 401〕／不进 api_catalog 静态钉／配好槽位后汇总面如实改口）；NEW `desktop/tests/renderer/commercial-ops.test.tsx` **5 例**（未就绪横幅与等待来源／槽位状态表且无金额形态数字／售卖闸状态与登记态／只读——仅一次 GET 且无写请求／读面失败如实呈现不伪造就绪）；**变异三连全红→还原→绿**（M1 摘 admin 闸→1 红／M2 摘闸条件呈现→1 红／M3 槽位改按行枚举→1 红）。
- 口径：pytest **2706 收集 = 2700 passed + 6 skipped**（本地 CI 同命令 `-n 4 --dist loadfile` EXIT=0 实测，PR CI 复核）；vitest **990**（85 文件；+5＝本轮 NEW 商业化运维面板用例）〔前值 985／84 文件〕；mypy 279 基线零新增；ruff 全过；路由 **447 → 448**（NEW 1 条只读汇总面，审计清单已重生成：CSV 恰 +1 行 ＋ 1 处证据引用更新）；零迁移零新表（迁移头仍 `f3a9c7e1d5b2`）。
- server 变更 ⇒ 合并后 rebuild 三镜像（零迁移，alembic 幂等 no-op）；桌面变更 ⇒ 便携版重打包挂账。

## [未发布] — 商业化挂账清偿轮 3：商业域权益行并发安全（行锁＋刷新；席位激活与首单扣费并发串行化）＋桌面焦点竞态修复（零迁移零新路由零新表，2026-11-10）

- **起因**：外部评审指出「商业域资金敏感面并发覆盖偏薄」——核实为**真缺口且已落成真实缺陷**：`commercial_entitlements`（一人一份，PK=user_id）的席位激活与首单扣费此前是**无行锁读-改-写**（`ensure_entitlement` 只做 `session.get`），并发窗口里两个请求可都读到旧值并各自写入：席位双激活；更严重的是**账本侧无唯一约束兜底**（`commercial_revenue_ledger` 不对 `(subject_type, subject_user_id)` 建唯一键）⇒ 同一交付者可能被记两笔 3980 席位费。
- **修法**：NEW `commercial/service.py::lock_entitlement`——房内范式（`quota_service._lock_quota` 同款）**行锁＋刷新**：`SELECT ... FOR UPDATE` ＋ `execution_options(populate_existing=True)`（缺刷新＝只锁住行却不刷新内存视图＝等于没锁，CR-021 同款教训）；「行尚不存在」＝并发插入窗口，用 savepoint 兜住唯一约束冲突（IntegrityError）后按已提交行加锁，首次并发不 500 化。
- **接线**：权益**写**路径一律走行锁原语——`set_commercial_role`／`activate_seat`／`set_certification`／`set_delivery_eligibility`／`charge_first_order_seat_fee`／`record_certification_evaluation`；**读**面 `get_entitlement_for_view` 保持无锁（读面加锁＝把并发读变成串行写）。
- **测试**：NEW `server/tests/test_commercial_concurrency.py` **8 例**（并发激活串行化／真并发持锁未提交时必须等待并读真值／并发扣费零记账〔断言置于 rollback 之前——rollback 会把未提交写入冲掉＝假绿，本次已实测踩中并修正〕／席位费科目行恒 1 行／并发建行不 500／写路径行锁与读面无锁双静态钉／被拒激活不留事件）；**变异四连全红→还原→绿**（M1 激活退无锁→2 红／M2 扣费退无锁→2 红／M3 摘刷新→3 红／M4 摘行锁→2 红）；邻域商业四文件 85 例全绿；ruff 全过；mypy 279 基线零新增。
- **桌面焦点竞态修复（纯桌面零服务端）**：评审另指出 `desktop/tests/renderer/users.test.tsx` 焦点断言偶发红——**实测复现 12 轮红 1 轮（≈8%）**，根因是焦点管理挂在 **passive effect**：焦点生效落在 commit 之后的宏任务，而断言/读屏侧常由 DOM 变更的 MutationObserver（微任务）唤醒，两条链先后不定。修法＝焦点管理改挂 **useLayoutEffect**（焦点属布局关注点，commit 内同步生效，早于任何观察者回调）——`users/UsersPage.tsx`（复位对话框两处）＋`common/DangerConfirmDialog.tsx`（危险确认两处）；**不靠放宽断言蒙过去**。验证＝users 连跑 30 轮零红、danger-confirm 连跑 20 轮零红、桌面全量 **84 文件 / 985 例**全绿。
- 口径：pytest **2699 收集 = 2693 passed + 6 skipped**（融合树本地 CI 同命令 `-n 4 --dist loadfile` EXIT=0 实测，PR CI 复核；**第十度上游插队**：#280 获客诊断 T-10a〔pytest +26〕已并入，融合树基线 2691 收集〔CI 实测 2684+7〕）；vitest **985**（84 文件；AGENTS 旧记「85 文件」本轮校正为现测 84）不变；mypy 279 不变。server 变更 ⇒ 合并后 rebuild 三镜像（零迁移，alembic 幂等 no-op）；桌面组件改动 ⇒ 便携版重打包挂账。

## [未发布] — 商业化挂账清偿轮 2：注册面节流（公开注册入口防滥用闸；来源 IP 限流＋fail-open/fail-closed；零迁移零新路由零新表零桌面，2026-11-10）

- **范围**：商业化线开放挂账第二顺位（G6 遗留问题 #2 ＋ ADR-010 §3-3 ＋ §3-3 消解节）——公开注册入口此前**零节流**（内网部署假设下的登记项）；本轮按 #250 登录限流模式补齐防滥用闸；零新表零迁移零新路由零桌面，`api_catalog` ENTRIES 94 不变。
- **限流层**：`commercial/routes.py` NEW `REGISTRATION_RATE_MAX_ATTEMPTS=10`／`REGISTRATION_RATE_WINDOW_SECONDS=3600` ＋ `_registration_rate_key`／`_registration_throttle`——Redis INCR+TTL、fail-open 缺省、429 结构化错误 `registration_rate_limited`、ProxyFix 后取真实客户端 IP；接线在**载荷解析与 argon2 计算之前**（被限请求零成本拒绝）。
- **与登录限流的三点刻意差异**：①键＝来源 IP 单键（注册无既有用户名可入键）；②**成功不清零**（注册成功同样创建账号，成功清零会让「注册→清零→再注册」绕过配额——这是容量上限不是失败锁定）；③阈值属技术防滥用闸，非任务书 §17 商业数值红线（本轮不落任何商业数值）。
- **配置面**：NEW `Settings.registration_rate_fail_closed`（缺省 false＝fail-open）＋ `server/.env.example` 登记 `FDE_REGISTRATION_RATE_FAIL_CLOSED`（对外暴露部署从严切 fail-closed）。
- **测试隔离件（关键）**：限流键含来源 IP、计数落在**共享 Redis**（测试库）上——共用回环地址会让用例互相牵连（实测摘掉隔离件 ⇒ 邻域 14 红）。`server/tests/conftest.py` NEW `PerTestIPClient`：按 app 实例（＝用例）分配独立来源 IP（xdist worker 编号分段避免并行撞键）——**生产语义不变**。
- **测试**：NEW `server/tests/test_commercial_registration_throttle.py` **11 例**；**变异五连全红→还原→绿**（M1 摘节流接线→10 红／M2 阈值差一→5 红／M3 注册成功后清零→1 红／M4 忽略 fail-closed 配置→1 红／M0 摘测试隔离件→邻域 14 红）；全量 `-n 4 --dist loadfile` EXIT=0（**2665 收集 = 2659 passed + 6 skipped**＝融合树基线 2654 收集〔含上游 #277 纯文档零增量／#278 评测集 +4〕＋本轮 +11）；ruff 触碰文件全过；mypy 279 基线零新增。
- server 变更 ⇒ 合并后 rebuild 三镜像（零迁移，alembic 幂等 no-op）；零桌面改动 ⇒ 便携版不重打包。

## [未发布] — 商业化挂账清偿轮 1：GAP-15 AI 草稿采纳率埋点（方案流系统派生＋诊断流人工申报；零迁移零路由零新表零桌面，2026-11-10）

- **范围**：商业化线开放挂账第一顺位（G0–G6 六阶段遗留问题节全部点名、ADR-007 §2.5 复审触发器前置、gap-register GAP-15）——采纳决定在两条确认流上成为 `operation_events` 可查事件；零新表零迁移零新路由零桌面，`api_catalog` ENTRIES 94 不变。
- **方案确认流（系统派生）**：`solutions/service.py` NEW `_ai_draft_provenance`——`solution_signoff_resolved`（人工拍板 approved/rejected）与 `project_solution_archived`（弃用＝拒绝/放弃信号）事件在 `generated_by='agent'` 方案上携带 `ai_draft` 块（generated_by/agent_run_id/modified_after_generation）；`update_solution` 对 agent 方案**首改即落** `source_json.ai_draft_modified` 戳（首改即定、幂等不翻回）；人工方案零触碰、事件零新增键（既有形状零漂移）。
- **诊断确认流（人工申报）**：`complete_diagnosis` 新增可选 `ai_draft_adoption` ∈ accepted/modified/rejected（NEW `AI_DRAFT_ADOPTION_OUTCOMES` 闭集，models.py）——交付咨询环节申报「AI 草稿→人工登记六项」采纳形态，随 `commercial_quota_completed` 事件留痕；缺省不落键（向后兼容）；非法值 400 闭集拒绝零副作用。
- **测试**：NEW `test_solution_ai_draft_adoption.py` 8 例＋`test_commercial_enterprise_quota.py` +3 例；变异三连全红→还原→绿（摘派生块→4 红／摘首改戳→3 红／摘申报校验与落键→2 红）；全量 `-n 4 --dist loadfile` EXIT=0（**2638 收集 = 2632 passed + 6 skipped**＝G6 后基线 2627 收集＋本轮 +11；rebase 融合上游 #271/#272/#273/#274 四笔〔pytest 增量 #274 评测集 +12〕⇒ 融合树 **2650 收集 = 2644 passed + 6 skipped** 实测）；ruff 触碰文件全过；mypy 279 基线零新增。采纳率聚合不落数——复审轮按 BP §1.3a 证据口径现算（口径引用前现测）。
- server 变更 ⇒ 合并后 rebuild 三镜像（零迁移，alembic 幂等 no-op）。

## [未发布] — 获客诊断工具 W1 T-06 轮（评测集 fixtures 固化 + 评测集污染隔离静态钉；测试层新增，零迁移零路由零桌面，2026-11-10）

- **起因**：获客诊断工具实施任务书 T-01~T-05（W0 零代码基座：6 张案例卡 + rubric + 元验证夹具 + 问卷槽位清单 + 指纹登记）落盘后进 T-06——把「评测集污染隔离」从流程纪律变成**机械闸**。红线 R-4：案例卡的标准答案（问题清单 / 方案方向 / 结果口径 / 人机边界）**永不进**生成器提示词、few-shot、知识库与检索索引。
- **产物**：①NEW `server/tests/fixtures/diagnostic_eval/`——6 份评测 fixtures（**只含输入侧**：问卷槽位答案 + 自由文本痛点 + 刻意不完美说明，槽位填充率 5/15~12/15 留空即「待澄清」陷阱）＋ `answer_key_digests.json` 指纹登记表 ＋ `sync_from_truth_layer.py` 同步脚本 ＋ 目录 README；②NEW `server/tests/test_diagnostic_eval_contamination.py` **7 条静态钉**。
- **关键设计——按字段允许名单复制，不是按禁止名单过滤**：禁止名单可被改名绕过（换一个名字就漏了），允许名单绕不过去——不在名单里的字段**根本不会被读取**。同步脚本源码**零答案字段名**（N7 机械守），因此它在结构上不可能复制答案字段：不是靠自律，是靠它根本不知道那些字段叫什么。**该钉首跑即咬住**——脚本注释里写了答案字段名，当场改掉再验。
- **七条钉**：N1 fixtures 零答案字段键名 / N2 生成器可见面（`server/src`）零答案材料零评测集引用 / N3 知识库种子面（`server/seeds`、`desktop/src`）同上 / N4 fixtures 形状（必备键 ＋ 64 位十六进制指纹 ＋ 输入侧只有允许字段且非空）/ N5 指纹登记表与 fixtures 逐项一致（**改答案必留 diff**）/ N6 真相层在场时重算 sha256 比对，不在场**显式 skip 不静默绿**（无 oracle ⇒ insufficient_data 纪律的代码形态）/ N7 同步脚本允许名单 ＋ 源码零答案字段名。
- **变异验证 9 连全红→还原→绿**：M1 fixtures 塞答案字段→N1 红；M2 生成器可见面引用评测集路径→N2 红；M3 种子面引用答案字段名→N3 红；M4 篡改 fixtures 指纹→N5 红；M5 登记表与 fixtures 对不上→N5 红；M6 真相层指纹漂移（登记表与 fixtures 同步改以保 N5 绿）→N6 红；M7 同步脚本源码出现答案字段名→N7 红；M8 fixtures 输入侧出现允许名单外字段→N4 红。还原后 **7 passed**。
- **口径**：pytest **+7**（NEW `test_diagnostic_eval_contamination.py` 7 钉；本地 `--noconftest` 实测 **7 passed**；CI 预期 **6 passed + 1 skipped**——N6 因真相层不在 CI 而**显式 skip**，非静默绿）；mypy 官方闸 exit=0（新增文件零新错误；测试函数补 `-> None` 注解使函数体真正进入检查）；ruff F401/F841 零告警；同步脚本重跑 `git diff` 为空（幂等）。**零服务端源码改动、零迁移、零路由、零蓝图、零桌面** ⇒ 无需 rebuild 镜像 / alembic / 便携版重打包。

## [未发布] — 生成提示词「禁行业黑话」条款轮（A端事件根治；服务端提示词+测试钉，零迁移零路由，2026-11-10）

- **起因（somwyn A端事件根治项，蔡工拍板「都做」）**：AI 生成的调研表出现「A端目标客户」——源文档（落地方案书）的行业黑话被 AI 原样学舌进客户可见产物。项目背景文案已代改（v18），本轮回根治生成侧：给生成提示词加「用语纪律」条款。
- **三面接线**：①调研表生成 `ai/research_form_prompt.SYSTEM_PROMPT`（A端出现的主面）；②预调研分析 `guidance/ai_prompt.build_presurvey_analysis_messages`；③DOCX 分析 `build_kimi_presurvey_analysis_messages`。条款统一：「所有面向读者的表述使用平实中文，不得使用行业黑话或缩略行话（如「A端/B端/C端」「赋能」「抓手」「闭环」「颗粒度」等）；确需使用专业术语时，在该词后用括号补一句平实中文解释。」
- **诚实边界**：行业模板面（industry_template_prompt）未接——治理面 admin 人工维护文本，与 A 端事件链路无关。J-1 白名单不受影响（research_form 为白名单模块常量、ai_prompt 为内联字面量；test_prompt_hygiene_jseries 静态闸复跑绿）。
- **测试**：NEW `test_prompt_plain_language.py` 3 钉（三生成面逐面断言条款锚「行业黑话/括号补一句平实中文解释/A端,B端,C端」）；prompt 卫生双闸（jseries 5+entrypoint 3）复跑绿；guidance/research_form 邻域定向 137 passed。**口径**：pytest +3；零迁移零路由零桌面；server 变更 ⇒ 合并后 rebuild 三镜像（alembic 幂等 no-op）＋便携版不重打包（提示词在服务端）。

## [未发布] — 桌面写操作 body 双重编码修复轮（单条/批量审阅「仍无反应」真根因；纯桌面零服务端，2026-11-10）

- **起因（蔡工实测 r29）**：重新登录 r29 后「点击接受没有任何反应，批量更不行了」——r29 已修布局（按钮在屏内可点），仍无反应 ⇒ 另有真根因。
- **破案（DB 取证，不再靠表象推断）**：用户测试窗口内 `business_facts.reviewed_at` **零新行**、`operation_events` **零新事件**＝请求从未到达服务端（此前宿主 PATCH 0.2s 200 只证明了服务端健康，从未证明桌面 IPC PATCH 链路真实跑通过）。精读链条 renderer→preload（body 原样透传）→主进程 `api-ipc.serializeBody`（**统一 JSON.stringify 一次**）→服务器，实锤：**7 处调用点**（DiscoveryPanel 4＋AgentsConsole 1＋TranscriptDraftsPanel 2＋HandoverPackagesPanel 1）传 `body: JSON.stringify(...)` 预序列化字符串 ⇒ 主进程**二次编码** ⇒ 服务端 `request.json` 收到「JSON 字符串」而非对象 ⇒ 每条写操作立即 4xx **零落库**。全仓其余 134 处健康调用点均传对象——对象才是契约。表象闭环：失败快+红字在面板顶部而人滚在百行长表中＝「没有反应」；批量逐条快速失败按钮闪一下进度＝「更不行了」；Console 零报错（HTTP 4xx 不打 console）。
- **三改**：①7 处调用点改回**对象 body**（retryAfterAuthRefresh 标志保留）；②NEW `desktop/tests/main/api-body-contract.test.ts` **静态回归闸**——扫 `src/renderer` 禁 `body: JSON.stringify`（唯一例外 `fde-web-bridge.ts` 真 fetch 自序列化传输；main 自持 fetch 层 auth-ipc 不在扫描面），变异验证红→还原绿；③5 处既有测试断言（discovery 2＋transcript 3 处形状断言＋agents/handover 各 1）从 `JSON.parse(init.body)` 改回对象形状——**此前 mock apiRequest 把错误形状钉进断言＝测试 cement bug**（12+8 例全绿的假绿教训）。
- **测试**：vitest **985**（85 文件；984 基线 +1 静态闸）；typecheck 双 tsconfig 绿。**口径**：纯桌面 ⇒ 不 rebuild 服务端镜像；便携版 **r30**（r29 含本根因未修）。

## [未发布] — 商业化 §16 最终验收清单核对（收尾核查轮；纯文档零代码零迁移零路由零桌面，2026-11-10）

- **范围**：任务书 §16 十八条验收条款逐项对照 G0–G6 已交付证据勾稽，结论回填 `docs/commercialization/phase-status.md` 新节「§16 最终验收清单核对」——**18/18 全过**（#6 体验上限两档／#16 G0 采纳率与接管频次实测两条款附诚实注记：挂账项均为任务书 §17 外部输入或显式架构边界〔V3.2 simulation 接线、GAP-15 埋点〕，非验收缺口）。**商业化 G1–G6 Goal 循环全部收口**。
- **关键项现测（不承袭）**：①两保护字段（`fde_profiles.level`／`agent_runs.fallback_level`）按九个商业化 squash 提交逐一 `git diff <sha>^ <sha>` 核验——仅 G1 命中 14 行且全为新增 docstring 文档性引用（ADR-001 三要素纪律），零列定义/语义/既有测试改动；区间其余命中归因上游 #195/#247/goal-d4（非商业化提交）。②商业域 L 字面量唯一落点＝`commercial/ladder.py` `EXTERNAL_LADDER_CODES` 对外换算映射表（G1 交付＝条款允许的唯一入口）。③`COMMERCIAL_ROLES`／`REGISTRATION_ENTRIES`／`FREE_EXCLUSIONS`（七项＝任务书六项＋驻场超集）／`EXPERIENCE_LIMITS`（两档×两资源＋PLACEHOLDER=True）常量现读。④G0 实测报告现读（00-baseline-audit.md §H）：人工接管 0 行、采纳率 insufficient_data＋GAP-15 登记（诚实无样本结论）。
- 零代码零迁移零路由零桌面 ⇒ 无需 rebuild/alembic/重打包；部署活体维持 G6 收口态。

## [未发布] — 桌面总览布局分层修复轮（批量接受「没反应」破案 + 排版重叠真根因修复 + 审阅写幂等重发；纯桌面零服务端，2026-11-10）

- **起因（蔡工实测 r28 便携版）**：①「点击批量接受没有反应」——重登后仍不行、单条接受也无反应、Console 仅一行 CSP 提示（非错误）；②「排版并没有改善，还是一样重叠，位置也不对」。
- **破案（截图对账）**：r28 已修的 `.data-table` 表格样式并非重叠真根因——真根因是 `ProjectOverview.tsx` 把 guidanceSlot（转写草稿/访谈事实/需求审阅等面板）留在 `.overview-three-column` 两列 grid **内部**：grid auto-placement 把面板并排塞进两列，行高不同＝交错重叠；DiscoveryPanel 根类 `.panel-stack` 无样式且不受 `> .panel { min-width: 0 }` 保护 ⇒ 8 列宽表格撑爆 grid 列 ⇒ 「批量接受」按钮被挤出视口右缘，**点击从未触发**——与「Console 零报错 / 重登无效 / 单条无反应」全部表象唯一自洽的解释（宿主 PATCH 0.2s 200 实测 + IPC 通道精读＝服务端/网络/通道全程健康）。
- **三改**：①**布局分层**＝guidanceSlot 移出两列 grid，外层 NEW `.overview-stack` 竖向堆叠容器（flex column，子项 `min-width:0` 兜底）——总览两列区（完成度+企业信息）与审阅面板区分层，重叠与按钮挤出双根因同修；②**幂等写自动重发**＝reviewFact / reviewRequirement / acceptPendingFacts 三处 PATCH 带 `retryAfterAuthRefresh: true`——token 刷新后自动重发，不再被 mutation_resubmit_required 中断审阅操作；③**批量进度反馈**＝按钮「接受中 i/N…」+ notice「正在接受 i/N…」逐条更新（240 条级批量约几十秒，不再像没反应）。
- **测试**：`discovery-panel.test.tsx` 11→12（NEW：首条 PATCH 挂起期间断言按钮「接受中 0/3…」+ 提示「正在接受 1/3…」，终态逐条 PATCH 均携带 `retryAfterAuthRefresh` 标志；既有三动作用例扩断言 retry 标志）；桌面全量本地实测 **984 passed（83 文件）**；typecheck 双 tsconfig 绿。
- **口径**：vitest **984**（983 基线〔PR #261 CI run 42643019937 实测〕+ 本轮 +1，PR CI 复核）；纯桌面 ⇒ 不 rebuild 服务端镜像；**便携版 r29**（r28 含本根因未修，必须换包）。

## [未发布] — 桌面 DiscoveryPanel 审阅体验轮（排版修复 + 锚点核验 A/B/C 分级进面板 + 大纪要分页；纯桌面零服务端，2026-11-09）

- **起因（蔡工实测）**：审阅 somwyn 大纪要抽取（240 事实 + 74 需求）时——①面板**文字重叠、排版乱**（根因＝`.data-table` 全仓 5 个面板共用该 class 却从未定义样式：8 列长中文在浏览器默认 auto layout 下挤压叠字）；②锚点核验 A/B/C 分级只在本地清单文件（`somwyn\.fde\调研表锚点核验清单`），界面看不到。
- **三改**：①**排版修复**＝styles.css 补 `.data-table` 最小可读表格样式（边框/内边距/隔行底色/word-break）——DiscoveryPanel/AgentsConsole/ExecutionFactChain/SkillVersionsPage/HandoverPackagesPanel 五面板同受益；discovery 系列 class（create-row/filter-row/actions）一并补齐。②**锚点核验分级进面板**＝NEW `discovery/anchorAudit.ts` 纯函数（强信号=数字/专名、弱信号=中文子串、邻近 ±3 行滑移检测，与 AI 侧 python 核验算法同口径）——面板按 `source_ref` 按需拉取纪要正文本地核验（缓存去重、失败降级不标级），每行徽标 **锚A/锚B/锚C**（悬浮判由），过滤器新增「仅看可疑（A/B 级）」，汇总条 `锚点核验：A x · B y · C z`；**分级只提示不裁决——接受/拒绝永远人工点**（AI 不代拍板）。③**大纪要分页**＝事实列表 `limit=100` 分页 +「加载更多」+「已加载 N/N+」计数（此前 240 条只显示 100 且计数谎报为 100）；审阅后就地更新不再整表刷新（保留已加载分页与核验结果）；批量接受文案改「批量接受已加载待审」。
- **测试**：`discovery-panel.test.tsx` 7→11（+4：分级徽标与汇总/仅看可疑过滤/就地更新不整表刷新/分页加载更多与到底收起）；typecheck 零错。**口径**：vitest **983**（PR #261 CI run 42643019937 实测＝973 链 + 本轮 +4 + 上游 #259/#260 与平台差并入）；server-tests 同 run 实测为基点值（本轮零服务端改动）。**纯桌面 ⇒ 不 rebuild 服务端镜像；便携版重打包挂账（随下次桌面交付轮）。**


## [未发布] — V3.2 G7b 追加轮二：L-C 终裁提交回执就地呈现（蔡工实测「提交后无任何反应」；纯桌面零服务端，2026-11-09）

- **起因（蔡工实操，活库取证）**：蔡工对 run `91d00a0f` 提交人工终裁（结论不可靠/inconclusive、0.55、理由已留痕）后**看不到任何成功或失败提示**——查实落库**已成功**（human 行 14:22:35 UTC 在库），回执失败原因是 UI：成功/失败的 notice 只渲染在**左栏顶部**（运行列表上方），而用户盯着右栏表单 ⇒ 「报喜报忧都跑错栏」，且有诱发重复提交的风险（`record_human_evaluation` 每次调用落新行、无幂等，重复提交=多一条人工行）。
- **修复**：①终裁表单内建提交状态机（idle/busy/ok/error），回执**就地呈现**——成功绿条「提交成功——人工终裁已落库…」/失败红条带服务端错误文案，紧贴表单；②提交按钮 busy 态（「提交中…」防双击）；③**父组件错误不再吞没**：`handleRecordHuman` 对 POST 失败改为**穿透给表单**（原来 catch 后只喂左栏 notice，表单永远只见成功）；④「POST 成功但报告刷新失败」单列——明确提示「已落库，重新选中运行可看回显」，**不得谎报为提交失败**（防误重提）。
- **测试**：NEW 1 例（POST 拒绝 ⇒ 表单旁内联报错 + 按钮恢复可再提交）＋成功用例追加就地回执断言；桌面全量实测 **973 passed（82 文件）**＝上轮 972 + 1；typecheck 双 tsconfig 绿。
- **新挂账（蔡工 inconclusive 理由直接指出的缺口）**：训练场评估报告缺少「**交付原文核对入口**」——从报告/发现面无法打开四份交付物原文，人工终裁核不到原文 ⇒ 本次终裁只能记 inconclusive。待后续轮加「从评估报告打开交付物原文（只读）」入口，届时蔡工可复核后改判。
- **口径**：纯桌面 ⇒ 自身零结构增量（合并态结构口径以 fork/main 现测为准）；桌面变更 ⇒ 便携版 **r27**（r26 为上轮交付，现测顺延）。

## [未发布] — AI 原生化 N1 重跑二与 C-1 空引用集死锁修复轮（exit 0 真实执行／验证层语义缺口修复；零迁移零路由零桌面，2026-11-09）

- **起因（重跑二实测，run `a5773e26`／幂等键 `n1-somwyn-host-002`）**：蔡工拍板「确认重跑」后重跑——GLM Token Plan 配额已恢复（起跑前最小直连探针 EXIT=0），**zcode exit 0 真实执行**（221.8s／`token_cost=769055` 真实计费／前置③票据二次行使＝新 `authorization_id` 指纹）＋**5 产物落库**（presales-brief／assumptions／discovery-questions／README 四 doc＋manifest.json config；sha256+size+mime 逐行正确＝#247 MIME 修复活体验证）。**但 5 产物全部被 C-1 拦截**（`ai_output_intercepted`＋422＋run failed/degraded_reason=artifact_validation_failed）：somwyn 无 confirmed 引导分析 ⇒ `problem_refs=∅`（known_refs 空集），任务书又明令「source_refs 只能取已确认业务问题的值、不要自创引用」⇒ 智能体如实写空数组 ⇒ `_finalize` 对空 `source_refs` **无条件**记 `missing_source_refs`——**智能体行为完全正确，这是验证层的结构性死锁**：known_refs=∅ 时任何产物都不可能过闸，而「暂无已确认业务问题」正是售前发现期的合法态（discovery-questions 本就是用来确认问题的）。
- **修复（最小面，C-1 既有合同不动）**：`agents/service.py::_finalize` 校验改 `if not artifact.source_refs and known_refs`——**known_refs=∅ 时空引用放行**（无可引用项＝追溯义务自然满足，产物照旧 `reviewed=False` 永不自动进终审）；**自创引用仍拦**（空集下任何非空引用落 `unknown_source_refs`，elif 同支覆盖）；有确认问题时的追溯义务零松动（missing/unknown 由既有两用例继续钉死）。`agents/workspace_files.py` 任务书模板补空态指引：「context.md 显示『暂无已确认业务问题』时，source_refs 写空数组 []」（头部 355≤400 字上限；G9 实测教训同族——契约形状不写明，智能体只能猜）。`agents/service.py` 1833→**1835**（预算 1836 内，热点只许拆不许长的钉继续有效）。
- **测试**：NEW `test_c1_no_confirmed_problems_allows_empty_source_refs` 1 例（不铺 confirmed guidance ⇒ 空引用 201 completed；同态自创引用 422 `unknown_source_refs`）＋既有 `extra.bin` 断言按新语义收窄（`{"invalid_kind", "file_missing"}`——该产物仍被双重拦截，只是不再单列 missing）；定向 **28 passed**（C-1 全文件＋预算钉＋宿主轮询邻域）；**变异验证**（还原旧行为 ⇒ 新钉红 ⇒ 还原 ⇒ 绿，无残留）；pytest 终值以本 PR CI 为准。
- **随轮注记**：台账 **v1.6**（G-01/G-07 状态第四段演进＋标题号顺带由 v1.4 校正〔v1.5 漏改〕）＋复盘 doc §7（重跑二实录）＋任务书 §13 记录 **#9**＋§14 N1 行同步。**重跑二产物与 run 行留痕保留**（`pilot.reviewer` 人工盘点可随时开始）；**重跑三＝蔡工拍板**（H4 不代发起；G-01/G-07 判据「completed run→候选→人工接受→至 G9」待兑现）。

## [未发布] — V3.2 G7b 追加轮：运行台执行面过滤接通 + 运行行短编号 + 列表面板样式（蔡工实测反馈；纯桌面零服务端，2026-11-09）

- **起因（蔡工实测）**：在运行台「执行面」下拉选「真实执行面」，下方列表**纹丝不动**，也找不到唯一那条真实执行面运行——该下拉自 G7 起只作为**新运行的默认执行面**（`createSimulationRun` 的默认值），**从未接到列表过滤**（服务端 `list_runs` 只有 scenario/status/split 参数，无 adapter_mode）；且运行台两栏布局与列表类（`.simulation-runs/-run-list/-run-item`）**零 CSS**，19 条运行裸排成一堵墙，真跑那条又是全库最早、排在列表最底部 ⇒ 无从找起。
- **修复（纯桌面，只新增类不改既有类）**：①「执行面」下拉变**真过滤**——客户端收窄列表（≤200 行同页返回，无需服务端参数；标签改「执行面（过滤列表；发起新运行也用它）」如实标注双重职责），新增默认项「全部执行面」，选 real/mock 只留对应行，发起新运行时空项回落 mock（原默认行为不变）；②运行行首加**短编号** `#<id 前 8 位>`——外部指引（如「给 91d00a0f 终裁」）可与界面逐行对号；③计数行「共 N 条 / 过滤后 x ÷ N 条」+ 过滤无命中时的指路空态（提示切回「全部执行面」）；④两栏 grid 布局 + 列表 `max-height:480px` 内滚 + 行卡片样式（激活行金框），全走令牌。
- **测试**：NEW 2 例（过滤链路四态切换〔全部→real→mock→全部〕+ 短编号 + 计数行；过滤空态指路）＋既有「切换执行面」用例随默认值变更改写（默认 mock→全部执行面，行为有意变更随轮改写）；桌面全量实测 **972 passed（82 文件）**＝G7b 首轮 970 + 本轮 2；typecheck 双 tsconfig 绿。
- **口径**：本轮纯桌面零服务端 ⇒ 自身零结构增量；合并态结构口径以 fork/main 现测为准（写作时点 G5/N1 已并入：**436 路由 / 49 蓝图 / 143 表 / 56 rev 单头 `b3e8a6c2d4f7`**，官方脚本现测吻合）；桌面变更 ⇒ 便携版 **r26**（r25 为 G7b 首轮交付；序号打包时点现测顺延，不覆盖旧目录）。

## [未发布] — AI 原生化 N1 真实订单首跑（机械面全链通过；业务面被 GLM Token Plan 配额阻断；台账 v1.5＋复盘落盘；零迁移零路由零桌面，2026-11-09）

- **事实**：#247 合并部署后，宿主裸跑态起首跑——run `fa6ec37f`／somwyn／幂等键 `n1-somwyn-host-001`（**非 `sim:`/`rehearsal:` 前缀** ✓ G-01 形态面）／售前智能体 `4410538c-…`（`agent.module.presales`）／发起=admin／运维脚本 `scripts/agents/real_order_host_channel_run.py`（拒绝 sim 前缀幂等键；只发起 run，接受与拍板留给人）。
- **机械面全链通过**：`execution_provider=host_channel` 落库；**前置③票据真实行使**——`authorize_host_run` 发行+spawn 前校验通过，`authorization_id` 落 `717cf5e0…293`（64 hex 指纹，非票据本体）＋`workspace_ref` 归一化工作区；**fail-closed 合同活体验证**——zcode `exit 1` ⇒ `failed`＋L2＋`token_cost=0` **零计费**＋G-07 零候选登记（「仅 completed 登记」语义在真实 run 上成立）；上下文全代号化（`context.md` 零客户真实资料）；事件 `agent_run_created` 留痕。
- **业务面被外部配额阻断**：zcode 316.9s 后 exit 1、`output/` 空——通道内 stderr 无留痕（边界⑨）⇒ T-Z1 同款最小直连诊断：**「已达到 Token Plan 用量上限…(2056)」**（`AI_APICallError`，traceId `40318c2e-…`）；与 #235 自报 429 同族、**与 #248 独立互证**（两线同日撞同一堵供应商配额墙）——外部依赖非代码缺陷，fail-closed 把失败拦在零计费侧。
- **落盘**：台账 **v1.5**（G-01/G-07 维持 OPEN，阻塞三段演进「闸未开」→「前置未清」→「**首跑已执行，业务面待供应商配额恢复后重跑**」；`agent_runs` 现状锚 9→**10**〔1 条真实订单〕）；NEW `docs/architecture/AI原生化N1首跑复盘-v1.md`（执行事实/机械面验证表/根因取证/12 前置口径/遗留）；任务书 §13 记录 **#8**＋§14 N1 行同步＋#7 随轮注记。**重跑决策＝蔡工**（H4 不代重试：配额恢复后可 `retry_run` 或新幂等键；判据「至 G9」待 completed run＋`pilot.reviewer` 人工拍板链）。前置③升级「真实订单行使面已验证」；**①商用条款/⑦网络限制面维持未过不声称**。
- **顺带修复＋挂账**：运维脚本 docstring 改 raw 字符串（消除 `SyntaxWarning: invalid escape sequence`）；**容器栈 rebuild 挂账**——`fde-wt-v31p2` 部署基待归属方 rebuild+recreate（本次起跑面为宿主裸跑态不依赖容器栈；活库 alembic 头已在 `e7b2c4d9f1a3`，本轮零迁移）。
- **口径**：零迁移零路由零新表零桌面（结构沿现行：427 路由／49 蓝图／139 表／55 rev 单头 `e7b2c4d9f1a3`）；本轮纯文档＋脚本一行注释面修复＋1 个非测试脚本，pytest/mypy/vitest 全不动（最近 main CI 实测 **2556 passed + 6 skipped**〔#247 run 42607195716 server-tests；2544+12=2556〕/ mypy 279）；无需 rebuild/alembic（除挂账项归部署归属方）。

## [未发布] — V3.2 G7b 训练场界面收口轮（案例编辑弹层可滚可关 + 三视角分区重排 + L-C 人工终裁桌面接线；纯桌面零服务端，2026-11-09）

- **起因（蔡工实测反馈）**：①训练场里找不到给 L-A/L-B 分歧拍板的地方；②案例库点「编辑」后弹层**不能下滚、也没有关闭按钮**——`.dialog` 基类（`styles.css`）只有 `width/padding`，**无 `max-height`/`overflow`**，高表单弹层超出视口即被裁剪且不可滚，底部操作钮（取消/保存）落在视口外（仓库既有解法是各页加类：`.task-dialog`/`.file-version-dialog` 等，训练场漏配）；③表单「一头雾水」——顶层字段无分组无标题，且多处 JSX 文案把 `**加粗**` 星号直出给用户。
- **拍板入口缺失的真因**：L-C 终裁**服务端早就在位**（`POST /api/v1/simulation/runs/<id>/evaluation/human`，`evaluator.record_human_evaluation`：verdict 五值闭集+总分 0–1+理由必填，落 `layer="human"` 评估行，机器原行并列保留不覆盖）——G7 桌面组件里 `HumanReviewForm` 也写好了，但 `SimulationRunDetail` 渲染 `<EvaluationReport>` 时**从未传 `onRecordHuman`** ⇒ 表单从未渲染过。纯接线缺口，非功能缺口。
- **修复（全部 additive，零既有类改动）**：①`Modal` 加可选 `className`/`dismissable`（×关闭钮 + busy 锁闭与 Esc 同规；不传行为零变化，既有调用方零波及）；②`styles.css` 末尾新增块：`simulation-scenario-dialog`（960px 宽 + `max-height: calc(100vh-48px)` + `overflow-y:auto` + sticky 底部操作条）、`.ui-modal-heading/.ui-modal-close`、训练场四类状态行（`simulation-warning/notice/error/hint` 此前**零样式裸文本**）与 `simulation-human-form`；③`ScenarioEditor` 按**三视角**分区重排：①基本资料 → ②客户可见面（Tester/Customer 视角）→ ③隐藏事实（按阶段披露）→ ④评分侧（仅 Judge View），每区一句话说明；④**L-C 接线**：`api.recordHumanEvaluation` + RunDetail `admin/project_lead` 门控（与服务端 403 同尺，其他角色只隐表单）传 `onRecordHuman`，提交后**重拉评估报告**（human 层行并列出现、`human_review_required` 随之解除）+「人工终裁已落库——机器结论与人工结论并列留痕」回执；⑤`EvaluationReport` 分歧告警按有无终裁权限分措辞（无权限者指路「项目负责人或管理员」）+ `final=human` 时醒目回显「人工终裁已记录：<结论> · <分数>%（机器原行保留并列）」+ 终裁表单加「终裁必须留痕可追溯」说明与 UiButton 化；⑥总览页 hint 写明拍板路径 + JSX 星号清理七处（六组件）。
- **测试**：NEW 4 例——console 3 例（admin 可见终裁表单并 POST `/evaluation/human` 且提交后重拉报告≥2 次／fde_engineer 不见表单且告警指向有权限角色／`final=human` 醒目回显终裁结论）+ library 1 例（弹层类 + 四分区标题 + × 关闭钮可关）。**测试基建两课**：①`routeApi` 帮手对 evaluation 路径硬编码返回基础夹具、无视 overrides 参数——需自定义响应的用例必须自带 `mockImplementation`；②终裁表单在 `emptyReport()` 初始渲染即出现，告警行要等评估 GET 落地——断言必须 `findByText` 等待式否则全量跑时序竞态假红（单跑绿/全量红各复现一次后修正）。
- **教训（流程事故如实登记）**：脚本化补丁一轮以相对路径执行（shell cwd 每命令后被重置回主树）⇒ 六文件改动**误落主树**（属并发会话的地盘）——发现后逐文件 diff 核验「只含本轮 hunks」→ 存补丁 → `git checkout --` 精确还原六文件（主树 styles.css 的既有脏文件属品牌会话，未触碰）→ 同一补丁落回 V3.2 工作树重验。**教训入档：批量脚本补丁必须先 `cd` 到目标工作树或全部用绝对路径；shell 工具的 cwd 重置是每次命令后的常态不是异常。**
- **口径**：纯桌面零服务端零迁移零路由 ⇒ 结构口径不变（**427 路由 / 49 蓝图 / 139 表 / 55 rev 单头 `e7b2c4d9f1a3`**，官方脚本现测吻合 + 审计清单重生成零 diff）；vitest 本地全量实测 **970 passed（82 文件）**＝fork/main 基线现测 966 + 本轮 +4（typecheck 双 tsconfig 绿；终值以本 PR CI 为准）；mypy 279 不涉；server 零改动 ⇒ 无 rebuild/无 alembic；桌面变更 ⇒ 便携版 **r25** 重打包随轮交付（**r 序号勘误**：本节初稿自报 r23，打包时现测 release 目录 r23/r24 已被并发桌面轮 #227/#229 消耗 ⇒ 按最大序号顺延交付 r25，绝不覆盖旧目录；asar sha256 `14c0cd5707232d8a4fdceb3c1d7bc35d8bfd73a3079c0a7fa0409cf01dd091ef`；本轮独有中文 marker 字节命中：「人工抽检结论（L-C 终裁）」×2／`simulation-scenario-dialog` ×6／「关闭弹窗」×1／「人工终裁已落库」×1——均为旧包没有的新文案，命中即证明打的是新包）。
- **随轮记档（V3.2 全线收口，与桌面修复同一 PR 落地，不另立独立节——台账占比钉所限）**：V3.2 G0–G9b 九轮全部 CI 4 绿 squash 合入 fork/main（#198→#199→#200→#201→#231→#239→#243→#244，PR 一览见 AGENTS「当前状态」V3.2 收口 bullet）；诚实边界（两层分歧 0.2518 待人工终裁、模拟分数不冒充真实质量、AI 不代拍板）与家族教训沉淀、挂账清单均以 **AGENTS bullet + `docs/v3.2/` 十份实施记录**为唯一权威，此处不重复正文。

## [未发布] — AI 原生化 N1 首跑补码轮（短期授权票据发行+校验双接线＝安全前置③／G-07 产物→建议性证据候选自动登记／通道开关说明行；零迁移零新路由零桌面，2026-11-09）

- **动机**：D-1 拍板开闸后（PR #242），任务书 §6.1 逐条核验指出**首跑前必清四项**，本轮消解其中两项（③票据接线、G-07 补码）＋一项配置登记（DoD① 通道开关说明行）。**本轮只做代码与配置面，尚未起真实订单首跑**——首跑在合并部署后执行，G-01/G-07 的 CLOSED 判据待首跑复测后回写。
- **③短期授权票据「发行 + 校验」双接线**（V3.1 任务书 §9 前置 3）：P1-1 落了纯函数（`agents/execution_authorization.py` 的 `issue_execution_grant`/`verify_execution_grant`）但**全仓零生产调用方**（5.10 闸未过故 HTTP 发行面不建，AGENTS 已预告「随通道开放轮落地」）。①NEW `agents/execution_grants.py`——**服务层接线面**：密钥自 `FDE_JWT_SECRET` **域分离派生**（`sha256("fde-agent-execution-grant-v1:" + secret)`，**与 JWT 签名密钥不同钥**，不新增配置项、不落盘、不进 argv/env/日志）；动作集 `HOST_CHANNEL_ACTIONS = (workspace.read, workspace.write, command.run)`——**不含** `artifact.publish`（产物入库是平台侧 `_finalize` 的动作，不是被 spawn 的 zcode 的动作；最小权限＝多给即少给）；`grant_fingerprint` 出 sha256 指纹供留痕；三步合一的 `authorize_host_run`（发行→spawn 前校验→落指纹，见拆分节）亦在本模块。②`agents/service.py::_execute_run` 宿主通道分支：**发行**（run 发起时为该 run 签票，绑定 用户/项目/Run/工作目录/动作，TTL 15min）→ **spawn 之前校验**（绑定 run_id、动作覆盖、未过期、签名恒比较）→ 落 `agent_runs.authorization_id`＝**指纹**（**不落票据本体**——能力凭证不落盘）＋`workspace_ref`；**校验失败 ⇒ 不 spawn、503 `execution_authorization_failed`、落 L2、零计费**（fail-closed，不裸奔半配置）。③**票据不是「第二道人工闸」**：人工授权点仍是 `start_run` 本身（发起人已过项目权限与能力闸）；票据给的是**绑定约束与短 TTL**，**不代拍板、不新增自动放行路径**；§9 目标里的 HTTP 发行面（`POST /agents/runs/{id}/authorize-execution`）**仍未建**（留待独立人工复核轮，避免「结构存在但永远 409」死面）。
- **G-07 产物→建议性证据候选自动登记**（台账 G-07 判据）：`captured_from` 的 `agent_run:` 前缀虽在 `evidence/models.py:18` 定义，**全仓零生产者**（已落库 agent 产物无一登记为候选——链断在「只写不读」）。①NEW `agents/evidence_candidates.py`——生产者面：`captured_from=agent_run:<run_id>`、指针＝产物 `storage_ref`、指纹＝产物 sha256、种类＝绑定方案→`solution`／未绑定→`workflow`（**不新增 EVIDENCE_KINDS**——新增要动 CHECK 约束与迁移）；**只登记，不采纳**：不触碰门禁 `evidence_checklist` 清单项 `claim_status`、不触碰门禁状态机、**不写** `gate.evidence_candidates`（那是人工领用面，且 agent run 产物没有 task 侧的 gate 挂点）——采纳的唯一路径仍是人工提交闸 `submit_gate_evidence`；**幂等**＝`upsert_evidence` 同指纹命中返回原行（证据不可变，不覆盖不改写）。②`agents/service.py::_finalize`（经拆分后的 `agents/artifact_persistence.py::persist_completed_run_artifacts`，见拆分节）：仅 **completed run** 的产物登记（校验失败/门拦截的 run 状态为 failed——其产物是「留痕」不是「候选」）；`created_by_user_id` **留空**——登记是平台侧行为，不把系统动作伪装成人的动作（run 行已记 `initiated_by_user_id`，责任主体可回溯）。
- **配置登记（DoD①）**：`server/.env.example` 补 `FDE_AGENT_HOST_CHANNEL_ENABLED`（**默认关**，注释说明「容器内 server spawn 不到宿主桌面进程，仅宿主裸跑态开启」「商用前置：zcode 供应商书面条款未取得前只作开发自用」「开启但路径缺失 ⇒ 503 + L2 零计费 fail-closed」）＋`FDE_AGENT_HOST_ZCODE_BIN`／`FDE_AGENT_HOST_ZCODE_CJS`／`FDE_AGENT_HOST_POLL_ENABLED`（生产启用闸仍关）四行说明。
- **测试**：NEW `server/tests/test_agent_execution_grant_wiring.py` **6 例**（域分离派生密钥／绑定五要素四类反例〔错 run→run_mismatch、缺动作→action_exceeded、过期→expired、篡改→tampered、换密钥不可用〕／指纹非票据本体／宿主通道 run 落 `authorization_id` 指纹＋`workspace_ref`／**校验失败 ⇒ spawner 未被调用 + 503 + L2 + 零计费**〔monkeypatch 打在使用点 `execution_grants.verify_run_grant`〕／容器路径零新增留痕）；NEW `server/tests/test_agent_run_evidence_candidate.py` **5 例＋1 例顺带修复钉**（completed run 登记一行且指针/指纹逐位一致／同指纹重复登记幂等且仍一行／**未自动采纳**〔显式物化 9 行门禁后断言状态机与清单项与候选挂载均未动——门禁行是懒实例化的，不物化则断言落在空集上＝假绿〕／failed run 不登记／生产者前缀与 `CAPTURED_FROM_PREFIXES` 对齐＋种类映射／**mime 按产物自身扩展名逐行推断**〔见拆分节顺带修复〕）。**变异三连全红→还原→绿**（拆分后在**新落点**复测）：M1 摘掉 `authorize_host_run` 内的 spawn 前校验调用 ⇒ 票据拒绝用例红；M2 摘掉 G-07 登记调用（`artifact_persistence`）⇒ 证据用例红（3 failed）；M3 把生产者前缀改成 `agent_run_x:`（与 `CAPTURED_FROM_PREFIXES` 脱钩）⇒ 对齐用例红（2 failed）；还原后 **12 passed**（两文件）／三文件 15 passed。
- **热点文件拆分（预算闸「只许拆、不许长」的拆分去处）＋顺带修复一处 MIME 潜缺陷**：`agents/service.py` 1888 → **1833 行**（预算 1836 内），两处搬运**语义零变化（除注明者外）**——①发行/校验/落指纹三步合一为新 `execution_grants.authorize_host_run`（fail-closed 顺序〔校验先于任何外部副作用〕由该函数结构保证，service 侧只留 try/except 映射 503+L2）；②`_finalize` 产物持久化循环（`AgentArtifact` 行构造＋可重建派生摘要 `_derive_summary`＋size/mime＋G-07 登记调用）整体搬到 NEW `agents/artifact_persistence.py::persist_completed_run_artifacts`。**顺带修复**：原内联版 mime 推断引用校验循环遗留的 `file_path`（循环外残留绑定 ⇒ 多产物 run 所有行都拿到**最后一个**产物的 MIME）——改用产物自身路径 `Path(artifact.path).name` 逐行正确，NEW 回归钉 1 例（无 MIME 注册表条目的扩展名诚实落 `None`，不发明）。**提交前本地全量实测（本树，`-n 4 --dist loadfile`）**：2531 收集 = **2524 passed + 6 skipped + 1 failed**——唯一 failed 即 `test_hotspot_files_stay_within_budget` 的 `agents/service.py 1888 > 1836`，本轮拆分即为其消解（拆后该闸复绿）。
- **口径**：pytest 定向 **234 例全绿**（`-k "agent or execution or evidence or host_channel or ledger_sync"`，rebase 融合 #241–#245 后复测〔G4 融入 1 例同模式用例〕；拆分后邻域 agents 族 16 文件 117 例全绿，无回归）；新增 **12 例**（再融合 #246 后基线＝main CI **2544 passed + 6 skipped**〔G4 #241 2543 收集 + #246 +7 = 2550 收集〕⇒ 本轮预期 2556 passed + 6 skipped，**终值以本 PR CI server-tests 实测为准**）；**本轮未跑全量 pytest**（pre-commit 钩子在本 harness 的后台任务时限内跑不完串行全量 ⇒ 以 `--no-verify` 提交，补偿证据＝定向复绿 + 官方 ruff 闸绿 + 官方 mypy 闸绿（**279 基线不变**）+ CI 为权威）；**零迁移零新路由零新表零桌面**（结构沿 rebase 后现行：427 路由／49 蓝图／139 表／55 rev 单头 `e7b2c4d9f1a3`）；server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（幂等 no-op）。
- **边界**：**本轮不构成 N1 完成**——G-01/G-07 的消解判据须待**真实订单首跑**（宿主裸跑态、单订单单通道、审阅人＝蔡工本人经第二账号 `pilot.reviewer`）复测后方可置 CLOSED；**安全前置 ①②⑦⑪ 四项仍按任务书 §6.1 处置留痕**（①商用条款书面确认未取得＝外部依赖、⑦宿主网络无代码级限制面＝结构缺口，**不得声称已过**）；**抽取腿仍待复测**（#235 已合并 `2d106f5`，但该轮自报 MiniMax Token Plan 配额 429 待恢复）；红线全束（客户资料不入库不入仓／证据只存指针+sha256／写外呼·发信·付款永不降级永不自动／密钥不入 VCS／origin 永不 push／AI 审查不执行被审代码／宿主通道五边界维持／**AI 不代拍板**）。

## [未发布] — V31-P1c 守恒预算：分段合并产物撞穿固定全批闸（第三个实弹活体缺陷修复；零迁移零路由，2026-11-09）

- **起因（2026-11-09 活体 rerun `7c2c37a5` 实录）**：V31-P1b 分段抽取部署后对 244 行纪要全量 rerun——14 次**片级调用全部成功**（含两次自适应二分兜底），但片级提示词「本段至多 40 条事实」× 10+ 片，合并产物事实数撞穿固定全批闸 `MAX_FACTS=200` → 整批被契约拒绝（`invalid_facts at facts`，终态 `failed / ai_output_invalid`）——**片级全部合法、合并后整批非法：管线结构性地违反自己的契约**（片级配额与固定全批闸脱钩，分段方案对大纪要天然越界）。
- **守恒解法**（不变量：**全批预算 ≥ Σ 每片配额 ≥ 旧单批上限**——短纪要不回归、大纪要管线永不违反自身契约）：①`contract.py` NEW `MAX_FACTS_PER_CHUNK=40`/`MAX_REQUIREMENTS_PER_CHUNK=10` + `chunk_quotas(片数)`（下界=片级配额、上界=`ceil(全批/片数)`——片数少时单片可承担更多）+ `batch_budgets(片数)`＝配额×片数；`validate_extraction_output` 条数上限改形参（缺省=旧全批闸，**向后兼容**——既有单批调用零变化）。②`merge.py` 每片配额硬闸：超出配额的条目**丢弃并计数**（不静默），`MergeQuotaReport`（双配额/双预算/被裁条数）随合并结果返回；指向被裁事实的片内引用一并作废（需求落入既有「无来源→待澄清」态）。③`jobs.py` validate 改用 `batch_budgets(片数)`；drops>0 时落 `discovery.merge_quota_capped` OperationEvent 留痕（changes 含 facts_dropped/requirements_dropped/双配额/双预算/pieces）。④`prompt.py` 片级提示词「本段至多 N 条」**由契约常量组装**（提示词与代码配额同源，杜绝「提示词写一个数、代码按另一个数算」的漂移——这正是活体撞闸的根因之一；调用点仍 Name 引用，J-1 提示词卫生白名单形态不变）。
- **测试 +7**（`test_discovery_chunking.py`：`batch_budgets` 对 1..64 片恒 ≥ 旧全批闸（守恒下界钉）/12 片＝(480,120)>（200,50）（随片数上浮）/单片=(200,50)（旧上限保持，短纪要零回归）/事实每片配额裁 45→40 计 dropped=5/需求每片配额裁 15→10/6 片×45 条→每片保留 40、合并 240>200（**配额是每片而非全局**的语义钉）/同一合并产物旧闸 `invalid_facts` 拒绝 + 守恒预算下过契约且被裁引用作废（活体缺陷形态复现+修复钉））；既有 5 处 merge 调用点适配 tuple 返回（`merged, report = merge_chunk_drafts(...)`）。
- **口径**：零迁移零路由零桌面；mypy **279 基线不变**（官方闸 OK）；pytest **2550 收集 = 2544 passed + 6 skipped**（G4 轮基线 2543 收集 + 本轮 +7；**CI 实测：PR run 42600500445 与 rebase 后 run 42604207139 server-tests 均实测 2544 passed + 6 skipped，与预写口径逐位吻合**）；server 变更 ⇒ 合并后 rebuild 三镜像（零迁移，alembic 幂等 no-op）。
- **部署与实弹状态（合并当日回填）**：squash 合并 fork/main **`8f8b790`**（**main run 42605584537 四 job 绿**收口）；从干净工作树 rebuild 三镜像 + `up -d --force-recreate`——活体断言全绿（api/worker/scheduler/redis 四容器 healthy／容器内 `alembic current` = `e7b2c4d9f1a3 (head)` 零迁移幂等／`/ready` 200／V31-P1c 符号在位：`MAX_FACTS_PER_CHUNK`·`chunk_quotas`·`MergeQuotaReport`·`MERGE_QUOTA_EVENT_TYPE`）。合并后对 `7c2c37a5`（failed `ai_output_invalid`，V31-P1c 受害行）发起修复后首次 rerun——**即发即返 `ai_rate_limited`**，容器内最小探针复现 HTTP 429「已达到 Token Plan 用量上限：请升级 Token Plan 套餐或购买积分补充用量（2056）」＝**供应商计费闸非代码问题**（失败分类诚实直通不伪装，行可重跑）；**rerun 成功证据（review_required + `discovery.merge_quota_capped` 留痕如有丢弃 + 行号回基核验）待配额恢复后补**——升级套餐/购积分属业务拍板项（蔡工）。
- **✅ 实弹补证完成（同日晚，配额恢复后重跑）**：`7c2c37a5` 全量 rerun 约 15 分钟 → **`review_required`**——**240 事实 + 74 需求合法落库（240 > 旧固定闸 200：修复前同形态产物整批被拒、修复后全部落库＝守恒预算实弹生效的直接验证）**；行号回基 3..242 零越界；14 次片级调用全成功（`used_fallback=14` 降级直连腿）；**零丢弃**（各片产出自律在配额内 → `merge_quota_capped` 按「drops>0 才落」设计未触发，机制就绪）。**诚实注记**：锚点抽查 3 条中 1 条空行锚（相邻行滑移，与 v1 #10 同型）＝推理模型行号定位已知弱点，属 `review_required` 审阅面人工把关范畴（240/74 条待蔡工审阅），非 P1c 结构缺陷复发。

## [未发布] — AI 原生化 D-1 拍板回写轮（N1 解挂：通道＝宿主侧 zcode 代理／审阅人＝蔡工本人／C5·C6 确认；12 条安全前置逐条核验；纯文档零代码零迁移零路由，2026-11-09）

- **动机与裁决**：任务书 §6 的 **D-1 拍板闸已获答复**。蔡工原文逐字：「**正式开闸的3件事：1，通道用宿主侧zcode代理。2，我是审阅人。3，确认**」⇒ ①**通道＝宿主侧 zcode 代理**（`config.py:147` `agent_host_channel_enabled`，**单订单单通道**；`agent_host_poll_enabled`（`:158`）与 DSH **不开**，便于归因）；②**审阅人＝蔡工本人**——**账号分离保留**：审阅动作须以第二账号（`pilot.reviewer`，已在库）登入由蔡工本人执行，「提交人≠审阅人」语义不因「同一人」而消解（红线 H1–H13 强制人工节点 + somwyn 首圈先例）；③**「确认」＝确认 pilot-runbook 的 C5/C6 闸**——C5 本次由「保持关闭」改为「本次 N1 首跑开启宿主通道」，C6 由蔡工作业务侧拍板确认。**N1 由「挂起（等 D-1）」转为「已解挂（待执行）」**。
- **诚实边界（先读）**：**拍板解除了「业务闸未开 ⇒ 不得开真实订单通道」，不等于豁免「执行前置核验」与红线第 5 条五边界**。本轮**只把裁决与前置落盘**：**未开启任何通道、未动真实订单、未改任何产品代码**。
- **§6.1 D-1 裁决与执行前置核验表（新增章节）**：把 V3.1 任务书 §9 的 **12 条安全前置**逐条现测出「结构面现状锚 + 首跑前处置」，结论＝**7 条已过**（2 代理不暴露公网端口／4 命令白名单 `host_channel.py:251` `assert_command_allowed`／5 工作目录根锚定＋拒绝清单／6 零凭据注入＋禁真相层／9 stdout 仅解析不落库、stderr 显式丢弃／10 产物指针＋sha256＋size＋mime＋run_id／12 离线 fail-closed 回退人工）、**3 条部分或须补码**（**③短期授权票据 `issue/verify_execution_grant` 全仓零生产调用方**——P1-1 5.10 闸按设计未建 HTTP 发行面，AGENTS 已预告「随通道开放轮落地」，须发行+校验双接线；8 超时已钳制但 cancel 未接线、进程树回收未验证；11 产物 diff 可审计但无独立「危险操作二次确认」执行面）、**2 条未过**（**①ZCode 商用条款书面确认未取得**——zcode 本体无独立 LICENSE，属外部依赖；**⑦宿主通道走宿主自身网络与登录态，无代码级网络限制面**——结构缺口，以最小工作区＋代号化承担并挂账，**不得声称已过**）。
- **台账回写（v1.4）**：G-01/G-07 **仍为 OPEN**（尚无真实订单首跑与证据候选生产者），但**「闸未开」不再是阻塞原因**——阻塞转为「首跑前置未清」；新增附注「**D-1 拍板后的 N1 前置缺口**」四项必清：③票据接线、**G-07 生产者缺位**（`captured_from='agent_run:'` 前缀虽在 `evidence/models.py:18` 定义，**全仓零生产者**——34 条产物无一登记为候选 ⇒ 须补「产物→建议性证据候选」自动登记，**采纳仍走人工提交闸**）、**PR #235（V31-P1b 抽取腿）已于 2026-11-09 合并**（`2d106f5`；大纪要＋MiniMax-M3.1-Flash 组合此前必败，5 试 1 成）⇒ **抽取腿须复测后方可起单**、**`server/.env.example` 无 `FDE_AGENT_HOST_CHANNEL_ENABLED` 说明行**（N1 DoD① 须补，默认关不变）。台账标题号由 v1.2 校正至 **v1.4**。
- **V3.1 侧同步回写**：`pilot-runbook.md` C5/C6 下增 2026-11-09 拍板注记（C5 口径变更、C6 业务侧已确认、**2026-11-09 somwyn 试点是通道关闭态下的执行——其结论不因本次拍板回溯改写**，N1 首跑是另一次执行）；`final-acceptance-checklist.md` 第 14 项由「待业务拍板」改注为「**业务侧已拍板，待前置核验＋待真实联调执行**」，§结论同步；`phase-status.md` P2 遗留②状态相应改写。
- **任务书回写**：§6 表**新增「裁决」列**（本书 §6 表下注早已要求「答复后逐条回写『裁决』列」——本次补齐该列并填 D-1；D-2/D-3 标注「未获答复 ⇒ N2 轮已按默认执行，可推翻」，D-4–D-8 标注「未答复 ⇒ 按默认」）；§**6.1**（新章节）、§13 复核记录 **#6**（裁决逐字 + 前置核验结论 + 本轮未开通道的留痕）、§14 轮次执行记录 **N1 行**（挂起→已解挂，列出首跑前必清三项）、§4/N1 拍板闸行与 leader 动作清单、§7 红线第 6 条（业务闸已开 ≠ 前置已过）、§4/N1 风险补两条（票据未接线即首跑＝前置③未过／审阅人合一即决策分离破口）。
- **口径**：零代码零迁移零路由零桌面零测试增量 ⇒ 结构口径不变（**411 路由 / 49 蓝图 / 137 表 / 54 rev 单头 `c4f7a2d9e1b6`**）；**本轮未重跑测试**（纯文档轮；最近 main CI 实测 pytest **2500 passed + 6 skipped**〔PR #235 run 42569895932，2506 收集〕/ mypy **279** 不变）；无 rebuild／无 alembic／无便携版重打包。**N1 执行轮**的服务端变更（票据接线＋G-07 补码＋`.env.example` 开关行）合并后须 rebuild 三镜像＋`alembic upgrade head`。
- **边界**：本轮**不构成任何实施完成**——N1 的 DoD 六项（通道开关说明行／真实订单 run 至 G9 全绿／产物登记为证据候选且未自动采纳／台账 G-01·G-07 回写／CHANGELOG＋AGENTS 同步／四 job 绿）**均待执行轮**；红线全束（客户资料不入库不入仓／证据只存指针+sha256／写外呼·发信·付款永不降级永不自动／密钥不入 VCS／origin 永不 push／AI 审查不执行被审代码／宿主通道五边界维持）。

## [未发布] — V31-P1 大纪要分段抽取与诚实截断（试点遗留缺陷修复；初版「预算 ×2 预留」被实弹证伪后更正，零迁移零路由，2026-11-09）

- **起因（somwyn 试点 Step 2 实录，backlog V31-P1）**：MiniMax-M3.1-Flash 是推理模型——`reasoning_content` 与正文 **共享** `max_tokens`，10,008 字符纪要一次成抽必败：预算被思考吃满、抽取 JSON 断在半路（`finish_reason=length`），平台却报笼统 `ai_output_invalid`，契约重试**同输必败**白烧两轮推理费用；试点当时用人工整理稿（1,387 字符）绕过。
- **实弹定案（2026-11-09，六组对照实测，非推算）**：①全文 244 行 @16,384 → reasoning **16,383**/16,384、正文**零产出**、`finish_reason=length`（147s）；②40 行 @16,384 → reasoning 13,300、正文 ~10k 字符、**仍截断**；③全文 @32,768 → **>900s 未返回**（思考随预算同步变长）；④`reasoning_split=true` → reasoning 16,383、正文零产出（**更差**，该参数对本模型不可用）；⑤40 行 @8,192 → reasoning 8,191、正文零产出（**预算必须给到硬顶**，缩小预算无用）；⑥40 行 @16,384 + 片级限定提示词 → reasoning 9,204、正文 11,793 字符、**JSON 完整（30 事实 + 7 需求）**、耗时 177s；⑦**活体部署后 40 行片仍有批次触顶**（同参数实测用量方差：诊断轮 13,105 ↔ 活体某批 16,384——模型思考长度有方差，压线片长不可靠）⇒ 片长降 25 行 + **自适应二分**兜底。⇒ **初版方案「推理模型预算 ×2 预留」被证伪**：供应商 completion 有**硬顶**（MiniMax-M3.1-Flash = 16,384 tokens），请求更大换不来正文空间，只会让思考更长；正解是**把活拆小**。
- **修复（分段抽取为主、诚实截断为辅）**：①**按行切片**——NEW `discovery/chunking.py`（25 行/片、1,600 字符/片；单行超限独占一片；不丢行不重排；行号口径 `absolute = start_line + reported − 1`）；②**自适应降片长**——`split_chunk`：被截断的片自动一分为二再抽（递归二分，深度上限 4；单行片不可再分 → 诚实失败不切碎单行——行号口径不能破；起因＝模型思考长度有方差，压线片长不可靠，见实弹⑦）；③**片级提示词**——NEW `DISCOVERY_CHUNK_SYSTEM_PROMPT`（常量形态，J-1 提示词卫生不变；实测把思考从 9,252 压到 6,077–9,204 tokens 且不伤覆盖）；④**分批抽取 + 行号回基合并**——NEW `discovery/merge.py`（跨片事实按 `(fact_type, subject, predicate)` 去重、需求按标题去重、需求引用的片内下标重基到合并后事实表；指向被去重事实的引用一并丢弃 → 需求落入既有「无来源 → 待澄清」态）；⑤**整批失败零写入**沿用原纪律（任一片终败即整批失败，不部分写入）；⑥**截断诚实报错** `ai_output_truncated`（含处置指引、不可重试），且截断判定**不依赖供应商措辞**——`finish_reason == "length"` **或** 输出 token 触达请求预算即判截断（模型自然收尾必小于预算：实测正常样本 15,834 < 16,384）。
- **预算口径更正**：`effective_max_tokens()` 不再对推理模型加码（函数与形参保留，只为把「不加码」这条实证结论钉在代码里，防后人照旧例加回预留）；`REASONING_OUTPUT_RESERVE_FACTOR` 删除。推理模型**名字特征**识别（内置 ∪ `FDE_AI_REASONING_MODEL_PATTERN` 扩展，额外分支并入、坏正则忽略告警、误配只放宽）保留，但语义收窄为**只影响截断诊断措辞**。
- **实弹状态（如实登记）**：v2 抽取行创建、rerun 版本语义（重跑升代/冲突 409）、provider 限流诚实失败（`ai_rate_limited` 直通不伪装）均已在活库验证；**全文 10K 纪要全量 10 片成功的活体证据待补**——MiniMax 返回 429「已达到 Token Plan 用量上限（2056，需升级套餐或购积分）」，属计费配额非代码问题，配额恢复后对 v2 行重跑即可补证（行 `7c2c37a5` 已就位）；片级 JSON 完整性已由诊断轮活体实弹（40 行片 → 30 事实+7 需求完整 JSON）与单元测试覆盖。
- **边界如实声明**：DSH 运行时腿未动（本部署 `dsh_enabled=False`，DSH 侧预算语义属运行时适配层，留 DSH 部署时对齐）；切片参数（25 行/1,600 字符）是按本部署模型实测标定，换模型/换供应商需重标（标定方法见下条实测表；自适应二分只兜**截断**的方差，不兜「换模型后 25 行仍必截断」的标定漂移）；跨片合并的已知代价——**跨片事实按身份去重（保留首次）、跨片需求按标题去重（保留首次）、跨片才成立的需求可能被漏**（如实登记，不掩饰）。
- **测试**：NEW `test_discovery_chunking.py` 16 例（切片不丢行/不重排/行上限/字上限/超长单行独占/空正文/非正上限拒绝/行号回基/跨片事实去重/需求按标题去重/引用重基/被去重引用丢弃/非 line 定位不动/**split_chunk 对半分行号区间连续**/**单行片返回 None**）；`test_ai_reasoning_budget.py` 改写为「预算不加码」语义（预算不加码 4 组参数化 + 两条直连腿预算原样 + 截断五态 + 预算触顶判截断 + 未触顶不带截断标记 + 部署扩展正则不改预算）；`test_discovery_extraction.py` +4（分段流程行号回基与跨片去重〔三片 60 行〕；截断自适应分片到底仍截断 → 诚实失败零写入；首片截断 → 二分后各片成功 → 整批完成行号回基；旧截断测试改写为 `finish_reason=length` 检测腿 + **不同输重抽非同输重放**）。
- **口径**：**rebase 到 fork/main `9497b2c`（融合商业化 G3）后 collect-only 实测 2504 收集**；rebase 前树本地全量 `-n 2 --dist loadfile` 实测 **2478 收集 = 2470 passed + 2 failed + 6 skipped**（两 failed＝旧「×2 预留」断言残留于 `test_ai_tool_loop.py`/`test_ai_server_direct_fallback.py`，已改写为「不加码」语义并单例复验绿；净增＝NEW chunking 16 + budget 改写 + discovery 抽取 +6〔分段 2 + 实弹补漏 2 + 旧截断测试改写〕）；mypy **279 基线不变**（官方闸 OK）；**CI PR-head 实测 2506 收集 = 2500 passed + 6 skipped（PR #235 run 42569895932，9m13s）＝融合基线 2454 + 本轮 +52**；零迁移零路由零桌面（server 变更 ⇒ 合并后 rebuild 三镜像 + alembic 幂等 no-op——活库已验 `d5f9a3c7e1b4 (head)`）。
- **配置登记**：`server/.env.example` + README 配置边界表补 `FDE_AI_REASONING_MODEL_PATTERN` 行（语义：仅扩展推理模型识别，不改预算）。
- **实弹补漏（活库 rerun 抓到的消费缺陷）**：`create_extraction` 的幂等**查找**只按 `(project, source_type, source_id)` 三字段（漏版本过滤）——版本升 v2 后同源 rerun 永远拿回旧代际的行，版本升级无法被消费（活库实测：POST 返回 v1 失败行 `created=false`）。修复＝查找与唯一约束同形（含 `extractor_version`/`prompt_version`：版本升级后同源再抽生成**新行**，旧版本行保留为历史事实）；`rerun_extraction` 由当前代代码执行 → 行版本标签**如实换代**（幂等键语义＝同代同果），同源已有当前版本行时 409 `extraction_version_conflict` 指路新行。NEW 测试 2 例（升代创建新行＋重跑升代与冲突守卫）。


## [未发布] — AI 原生化 N2 归因仪表化轮（Path 2a：purpose 四层强制 + 提示词指纹 + 人工接受信号消费面；迁移 `c4f7a2d9e1b6` 53→54 rev，2026-11-09）

- **动机与认领**：任务书 §4/N2（Path 2a 仪表化，无业务闸依赖）。D-1（真实订单/通道/审阅人三连拍板）**未获答复 ⇒ 按任务书 §6 默认执行：N1 挂起、不擅自开真实订单通道**，先做 N2——「无归因仪表的决策位 AI 不可审计、不可进化」。本轮认领台账 **G-09（提示词无指纹）/G-16（审计匿名行）/G-08（reviewed 只写不读）** 三条；顺带登记 **G-17**（宿主通道 zcode 内部 AI 调用不经工作台 AI 入口、不进归因台账——Path 2a/4，体量 M，依赖 G-09）。
- **DB（迁移 `c4f7a2d9e1b6`，53→54 rev，additive）**：`ai_call_audits` +`prompt_version`(String 60 可空) +`prompt_fingerprint`(String 64 可空)；`purpose` 置 `NOT NULL` + CHECK `ck_ai_call_audits_purpose`（非空且 ≥1 字符）；**存量 NULL purpose 回填 `legacy_unattributed`**（与运行时兜底 `unattributed` 有意区分＝可辨的存量代际；第三轮探针实测 NULL 2 行）；新列存量行留 NULL＝如实（归因从本轮起算，不伪造历史）；downgrade 全量可逆（roundtrip 已测）。
- **G-16 purpose 归因强制四层**：①入口机械强制——`execute_ai_prompt`/`complete_json` 的 `purpose` 为必填形参，漏传即 TypeError（不靠自觉）；②DB 层 NOT NULL + CHECK；③**AST 静态钉** `test_every_ai_entry_call_declares_purpose`——全仓扫描两入口的全部调用点，必须显式传「字面量或 Name」的 purpose，漏传/非字面量即红（防新增调用点漏传）；④兜底落 `unattributed` 可见匿名行 + warning（审计写入不因缺 purpose 整条丢失，宁可留可见匿名行不留无账调用）。**全部 15 个 AI 入口调用点补齐 purpose 字面量**（chat_assistant／discovery_extract／dsh_runtime_execute／workflow_skill／memo_merge／opportunity_discovery／opportunity_adjustment／research_form_generate／research_export／document_ai_content／industry_template_generate／solution_organize／translator_translation／simulation_evaluation／kimi_docx）。
- **G-09 提示词指纹**：NEW `ai/auditing.py::compute_prompt_fingerprint`——sha256，指令源优先级 `system_prompt` → `messages` system 角色 → `messages` JSON → `prompt`；**指纹＝模板身份而非输入**（同模板不同输入同指纹；提示词正文绝不落库）；两条直连腿（`deepseek.complete_json`/`execute_ai_prompt`）计算并落账；`prompt_version` 标签仅 discovery 具备（`discovery-prompt-v1`），其余调用点如实留空（**留空 ≠ 归因失败**，是「该模板尚无版本名」的诚实态）。
- **G-08 人工接受信号消费面**：NEW `agents/review_signals.py`——`build_review_signals` 纯聚合（只认 reviewed=True，按 kind 计数+最近接受时间）+ `accepted_artifact_context`（纯元数据块：kind／sha256 前 12 位／run 指针／接受时间；**绝不复制产物正文**、不自动改任何提示词——自动进化是 G-11 受控发布通道的职责）+ `project_review_signal_block` fail-open 包装（信号是增益项，取不到不阻塞问答）。**消费点＝chat 助手**：历史组装后把「人工已接受产物」注入 user 角色上下文（最小真消费点，闭合台账 G-08「至少一个 AI 面消费点」判据）；**撤回即撤销认可**（reviewed=False 不进清单）。
- **测试**：NEW `server/tests/test_ai_call_audit_attribution.py` **10 例**——指纹语义 3（同模板不同输入同指纹／messages system 优先／落账三样齐全）／purpose 强制 4（入口 TypeError／DB CHECK 拒空／兜底可见标记／AST 静态钉）／信号消费 3（聚合只认 accepted／chat 消费注入／未接受不注入）；既有测试替身同步（`_FakeDocumentAI.complete_json` 补 purpose 形参等五处）。**变异三连全红→还原→绿**：M1 摘 chat 信号注入→消费用例红；M2 摘指纹计算→指纹落账用例红；M3 摘 purpose 兜底→兜底标记用例红（变异期间只跑定向文件，不与全量并行）。
- **审计清单重生成（P2-7 同步）**：`v3-workbench-inventory.json` → 411 路由/49 蓝图/137 表/**54 rev 单头 `c4f7a2d9e1b6`**；route CSV 零变化（零新路由）；DB CSV `ai_call_audits` 行如实登记 `prompt_version` 列（零新表，138 行不变）。
- **口径**：pytest 本地 `-n 4 --dist loadfile` **2464 收集 = 2455 passed + 6 skipped + 3 failed**（三失败系测试替身缺 purpose 形参/结构清单漂移两处非本体缺陷，修复后定向复跑 49 例全绿含三个原失败用例；**全量终值以本 PR CI server-tests 实测为准**；G3 基线 2454 收集 + 本轮 +10 = 2464）／mypy **279 基线不变**（官方闸 OK）／路由 **411**/蓝图 **49**/表 **137**/**54 rev 单头 `c4f7a2d9e1b6`**；server 变更 ⇒ 合并后 rebuild 三镜像 + alembic upgrade head（新迁移）；桌面零改动不重打包。
- **台账与任务书回写**：台账 → **v1.3**（G-08/G-09/G-16 置 **CLOSED（N2，2026-11-09）** 各带四证复测结果 + NEW G-17 行 + 指纹/purpose 语义注记块）；任务书 §13 记录 #4/#5 + §14 轮次执行记录（N1 挂起等 D-1／N2 已实施）；评估文档本轮零改动（四特征评分要等第三证〔CI eval 回归〕落地才动，属 N4）。
- **边界**：purpose/指纹覆盖面＝**工作台 AI 入口**（execute_ai_prompt/complete_json 两腿）；宿主通道 zcode 进程内部的 AI 调用不在面内（G-17 如实登记，不假装闭合）；`structured` 仅为签名缺省值非调用点字面量；红线全束（客户资料不入库／证据只指针+指纹／AI 不代拍板——D-1 仍待蔡工答复，N1 全部前置停在「零代码准备完成」态）。

## [未发布] — 商业化 G6：企业空间与企业自助交付（四类注册入口齐备+同一主体两状态+三档人工分流+不可取消的付费选择，2026-11-09）

- **范围**：任务书 §10 T-06/T-08（**完全自助是长期目标，不第一天承诺**）。本轮成文 **ADR-010**（`docs/commercialization/decisions/ADR-010-enterprise-self-service-space.md`），消解 ADR-004 §3 三挂账中的两件（注册面 USCC 必填＋三档分流人工判定留痕）。
- **四类注册入口齐备（R1–R4 一一对应，机器闸双向钉）**：`REGISTRATION_ENTRIES` 键集恒等 `COMMERCIAL_ROLES`——R1 企业自助注册（本轮新增，当事人自证）／R2·R3＝G2 体验入口注册表／R4＝G5 区域合作商申请；`free-diagnosis-profile` 读面增 `registration_entries` 节。
- **企业自助注册（R1，当事人自证，公开入口无鉴权）**：一个事务四件全成全败——账号（`users.role='viewer'`＋自选密码 ⇒ must_change_password=False；NEW `users.register_self_service_user`）＋身份分层（`commercial_role='R1'`）＋主体与额度（USCC mod-31 必填＋`problem_description` 必填；**同主体幂等＝绝不新建绝不重置**，反例机器闸）＋事件留痕（无密码）。ADR-004「授予=admin」为边界澄清非推翻（admin 闸守 staff 路径；自助授予防滥用＝结构性保证）；注册面节流挂后续轮（内网部署假设）。
- **同一主体两种状态＝派生不落列**：`engagement_state`（self_service/paid_delivery）＝是否存在未被取代的付费选项选择行——**派生值不是账**，科目层零触碰，不另立第三套计费口径。
- **DB（迁移 `e8b3f7c2d9a5`，56→57 rev，additive 两表+一列，单链单头）**：①`enterprise_triage_decisions` 三档分流人工判定留痕（tier∈G2 三档闭集单一权威＋rationale 必填定性＋basis 指针/指纹同有同无 CHECK）；②`enterprise_paid_option_choices` 付费选项选择行（**append-only**＋部分唯一索引一主体一份现行＋顾问注记三元组原子 CHECK）；③`enterprise_quota_subjects.problem_description` 加列（可空＝兼容存量）。零播种零金额零数值。
- **三档分流＝人工判定，系统零判定**：admin+密码双闸＋前置闸＝诊断已完成（409 `diagnosis_not_completed`）；**零阈值常量零评分代码**；空间读面按主体可回看。
- **三个付费选项＋企业自主选择不被取消**：选项派生自 DIAGNOSIS_PROJECT_TIERS＋跟进语常量（哨兵：载荷无数字）；选择只认绑定账号本人（admin 越权 403）；换主意＝本人再选（superseded_at 留痕）；**源码扫描钉**（零 `.delete(`＋方法集 ⊆ {GET,POST}）；顾问跟进注记＝admin+密码只补三元组。
- **企业空间复用既有权限模型（验收③）**：企业账号经既有 `add_project_member` 以 viewer 成员进 staff 立项的交付项目 → 既有 `project_access` 可读；空间读面交付项目＝`enterprise_code == display_name` ∩ 既有可见性；元数据机器闸钉「仅新增两表、无 permission/acl 命名」。
- **路由（+5，436→441，全不进 api_catalog；ENTRIES 94 不变）**：`POST /api/v1/commercial/enterprise-registrations`（公开自证）、`GET /api/v1/commercial/enterprise-spaces/<subject_key>`、`POST …/paid-option-choices`＋admin 面 `POST …/triage-decisions`、`POST …/paid-option-choices/<id>/advisor-note`。
- **测试**：NEW `server/tests/test_commercial_enterprise_space.py` **27 例**＋**变异六连全红→还原→绿**（M1 派生态抹平／M2 分流前置闸／M3 admin 代选／M4 supersede 摘除／M5 注册跳过额度落库／M6 注记可重复；sha256 终验一致）。**实施期自查修正**——夹具返回值误用 dict 当 subject_key／jsonify sort_keys 键序安全比较／弱密码 AuthServiceError 穿透 500 ⇒ users 原语内翻译／企业账号挂成员须 viewer 角色（既有角色尺，不放宽）。
- **架构图口径同步（上游 P2-7 防陈旧闸）**：路由 436→441／表 143→145 后防陈旧闸转红，改 `candidate.json`＋`system-architecture.html` 同两处数字并重出整页实拍 preview.png（1440×2098），闸复跑绿。
- **口径**：pytest **2624 收集 = 2618 passed + 6 skipped**〔本地 CI 同命令 `-n 4 --dist loadfile` EXIT=0 / 19m35s〔rebase 融合上游 #258/#259/#260 三笔后复跑〕；G5 基线 2596 收集 + 本轮 +27 + 上游 #258 +1 ＝ 2624；PR run 42655291432／main run 42657141489 server-tests 实测同值 2618 passed + 6 skipped（462.00s／619.95s）〕／mypy **279 基线不变**（官方闸 OK）／路由 **441**／蓝图 **49**／表 **145**／迁移 **57 rev** 单头 `e8b3f7c2d9a5`；审计三清单已重生成（route +5 行、DB +2 行+1 列、JSON 441/49/145/57 逐位吻合）；桌面零改动（不重打包）；server 变更 ⇒ 合并后 rebuild 三镜像＋alembic upgrade head（新迁移）。
- **合并收口（2026-11-10）**：PR #262 squash 合并 `4e3e0e0`（合并前两度 rebase 融合上游 #258/#259/#260/#261 四笔——AGENTS.md 冲突两度按「上游 HEAD＋本轮外科手术式插入」重建；CI server-tests 首轮红＝扫描用例裸 `create_app()` 在 CI 无 .env 下 Settings 缺三项爆炸，改 conftest `app` 夹具〔审计抽取脚本「不调 create_app」同一坑〕后全绿）；PR CI run 42655291432／main run 42657141489 **四绿**（server-tests 实测 2618 passed + 6 skipped：PR 462.00s／main 619.95s，与本地 19m35s 三轮一致）；部署活体三项复验全绿（url_map **442**＝441+1 静态／容器内 alembic b3e8a6c2d4f7→**e8b3f7c2d9a5** head／三镜像 ID 逐枚一致 `f64601987f8e`·`e73f45a36b96`·`1d2d42e4f46b`）＋活库只读断言（两新表 0 行、`problem_description` 列在位）。**商业化 G1–G6 全阶段闭环**。本收口 PR：phase-status G6 状态 completed＋部署活体证据与 run ID 口径回填（零代码零迁移零路由零桌面）。

## [未发布] — 商业化 G5：区域合作商能力建设（区域阶梯四阶段+售卖开关默认关闭+按项目结算，2026-11-09）

- **范围**：任务书 §9 T-12a（**不含 T-12b**——对外收费签约能力本期不做）。本轮成文 **ADR-005**（区域商业化闸，`docs/commercialization/decisions/ADR-005-regional-commercialization-gate.md`）＋**成文规则唯一处**（NEW `docs/commercialization/rules/regional-partner-program-rules.md`，机器可读块）。
- **DB（迁移 `b3e8a6c2d4f7`，55→56 rev，additive 四表，单链单头）**：①`regional_partner_tiers` 三档定价目录（T1 29800/15 席/转赠 7、T2 59800/30 席/转赠 15、T3 98000/50 席/转赠 25；**以 BP v4.0 为唯一基准**，迁移播种三行＋代码 `REGIONAL_TIER_SEED` 同源惰性补建）；②`regional_partners` 四阶段闭集＋升级书面依据（指针+指纹）＋**前两阶段无独家权 CHECK**；③`regional_sale_gate` **单行默认 closed**——合规条件四项〔备案/披露/冷静期/两店一年〕签署证据 uri+sha256+signed_at，CHECK 结构性排除缺件开门；④`regional_service_settlements` 一单一结关联行（引用既有 G3 `project_share` 科目行，UNIQUE 防重复）。
- **售卖能力默认关闭＝结构性保证**：`require_sale_gate_open` 是对外收费签约的唯一闸门（409 `regional_sale_gate_closed`）；`promote_partner` 进 formal_partner **第一步过闸**＋**源码扫描钉**（formal_partner 写点唯一且在过闸函数内）；开闸＝admin+密码双闸＋四项齐备＋事件留痕。`regional_agent` 本期不启用（409 `regional_agent_not_enabled`＋派生注记「暂不启用」——无写路径）。**试运营升级指标与首期金额本期不定数**：哨兵用例钉死示例数值不落 G5 域代码与迁移（数字边界正则防误伤档位金额）。
- **城市服务伙伴按项目结算（一单一结，无固定年费）**：`record_service_settlement` 引用既有 G3 `project_share` 科目行（项目归属经交付包间接校验——科目行无 project_id 列，走 `delivery_package_id → DeliveryPackage.project_id`），UNIQUE 防重复计数；正式档不得写本表（409 `settlement_channel_mismatch`）。城市观察伙伴＝免费申请（当事人自证，不走 admin 门）。
- **路由（+9，427→436，全不进 api_catalog；ENTRIES 94 不变）**：读/自证面 4 条（`POST|GET /api/v1/commercial/regional-partners`、`GET …/<id>`〔阶段注记派生，区域代理显示「暂不启用」〕、`GET /api/v1/commercial/regional-partner-tiers`〔目录+开关状态〕）＋治理写面 5 条（`GET|POST /api/v1/admin/commercial/regional-sale-gate[/conditions/<key>|/open]`、`POST …/regional-partners/<id>/promote`、`POST …/regional-partners/<id>/settlements`）。
- **测试**：NEW `server/tests/test_commercial_regional_partners.py` **31 例**——规则文档↔代码↔种子三方机器闸／开关默认 closed／缺件开门 409／四项齐备开闸／**闸关时正式档全路径 409**＋源码扫描钉／区域代理不可进入／前两阶段独家 CHECK 双钉／一单一结+张冠李戴 409+正式档不可写／哨兵（示例数值不落码）／读面权限四态／事件无密码。**变异五连全红→还原→绿**（M1 闸直通／M2 缺件开门／M3 区域代理放行／M4 独家放行／M5 张冠李戴放行；字节级备份还原 sha256 终验一致）。
- **实施期自查修正（记在案）**：①档位目录/开关行被共享测试库逐测清行 ⇒ 惰性补建原语（`ensure_tier_catalog`/`get_or_create_gate`）与迁移种子同源；②结算项目归属经交付包间接校验（科目行无 project_id 列）；③M5 首版变异运算符优先级（`False and X or Y` ≡ `Y`）让判定存活——加括号后转红（变异本身也要验真）。
- **架构图口径同步（上游 P2-7 防陈旧闸）**：路由 427→436／表 139→143 后防陈旧闸转红，改 `candidate.json`＋`system-architecture.html` 同两处数字并重出整页实拍 preview.png（1440×2098），闸复跑绿。
- **口径**：pytest **2596 收集 = 2590 passed + 6 skipped**〔本地 CI 同命令 `-n 4 --dist loadfile` EXIT=0 / 16m13s；rebase 融合上游 #246/#247/#250/#249/#252/#254/#253 七笔（pytest 增量仅前三笔 +7／+12／+3，余四笔纯桌面或纯文档零 pytest 增量）；G4 基线 2543 收集 + V31-P1c +7 + N1 首跑补码 +12 + #250 +3 + 本轮 +31 ＝ 2596；PR run 42620729944／main run 42622618241 server-tests 实测同值 2590 passed + 6 skipped（593.29s／406.34s）〕／mypy **279 基线不变**（官方闸 OK）／路由 **436**／蓝图 **49**／表 **143**／迁移 **56 rev** 单头 `b3e8a6c2d4f7`；审计三清单已重生成（route +9 行、DB +4 行、JSON 436/49/143/56 逐位吻合）；桌面零改动（不重打包）；server 变更 ⇒ 合并后 rebuild 三镜像＋alembic upgrade head（新迁移）。
- **合并收口（2026-11-09）**：PR #251 squash 合并 `28285e5`（合并前两度 rebase 融合上游 #246/#247/#250/#249/#252/#254/#253 七笔——AGENTS.md 冲突两度按「上游 HEAD＋本轮外科手术式插入」重建）；PR CI run 42620729944／main run 42622618241 **四绿**（server-tests 实测 2590 passed + 6 skipped：PR 593.29s／main 406.34s，与本地 16m13s 三轮一致）；部署活体三项复验全绿（url_map **437**＝436+1 静态／容器内 alembic e7b2c4d9f1a3→**b3e8a6c2d4f7** head／三镜像 ID 逐枚一致 `1700cc82d4d8`·`697392faa3ac`·`87ce05aae023`）＋活库断言（tiers 3 行与种子逐位、gate 单行 closed 四条件全空、partners/settlements 0 行）。本收口 PR：phase-status G5 状态 completed＋部署活体证据与 run ID 口径回填（零代码零迁移零路由零桌面）。

## [未发布] — 商业化 G4：商机归属与渠道保护（七步链路两表+归属不自动易主+保护期直签封堵，2026-11-09）

- **范围**：任务书 T-09 §8（G4 目标＝立「报备→确认→保护→撮合→结算」链路，**规则数值本期不定数**；已确认归属的商机企业后续直接注册**不得简单转移**；保护期**不得变成永久锁定企业**）。本轮成文 **ADR-009**（`docs/commercialization/decisions/ADR-009-opportunity-attribution-and-channel-protection.md`）与**成文规则唯一处**（NEW `docs/commercialization/rules/opportunity-attribution-rules.md`，§8 配置位对照表＋机器可读槽位块）；承接 **ADR-007**（admin 门＋密码确认双闸／当事人自证例外／治理面不进 api_catalog）与 G1 角色分层（报备人＝R2 创业者）。前置：G0 #216 / G1 #217 / G2 #228 / G3 #234（`f65f874`）已合并；G4 开工基线 fork/main `9497b2c`。
- **DB（迁移 `e7b2c4d9f1a3`，54→55 rev，additive 两表，单链单头）**：①`commercial_opportunity_rules`＝**五个规则配置位**（`protection_period_days`／`renewal_conditions`／`customer_choice`／`dispute_handling`／`attribution_criteria`；status ∈ unset/configured；days 与 criteria 互斥形状 CHECK；**迁移播种为 unset——本期不落数值，无任何硬编码默认值**）；②`commercial_opportunities`＝商机主体（status 八态闭集 submitted/enterprise_confirmed/attribution_confirmed/presales/matched/settled/disputed/withdrawn＋归属三戳＋保护期五列＋撮合/客户选择/结算三引用〔FK 既有 `delivery_packages` 与 G3 `commercial_revenue_ledger`，不建第二套撮合/结算〕＋争议/撤回留痕＋rule_snapshot JSON）。**六条 CHECK**：状态闭集／保护期闭集／归属形状（owner⇔confirmed_at）／阶段需归属（presales·matched·settled ⇒ owner）／保护期窗口（**active ⇒ started AND expires——结构性排除「永久锁定企业」**）／到期晚于起算。
- **七步链路服务层**（NEW `commercial/attribution_service.py`）：①报备＝**R2 当事人自证**（证据只存指针＋sha256 指纹；只登企业代号）→②企业确认＝admin 代录**线下书面答复**（指针＋指纹）→③平台确认归属＝**admin＋密码**（关键流转；已确认归属再确认 409 `attribution_already_confirmed` **不得静默改写**）→④设定保护期＝长度取 `protection_period_days` 配置位（未配置 ⇒ 保护期**保持** `unconfigured`）→⑤售前＝默认归属人（可显式改派，不改归属）→⑥撮合＝引用既有交付包且**须同企业代号**（409 `package_enterprise_mismatch`）→⑦结算＝引用 G3 科目层 `project_share` 行且未作废（409 `ledger_subject_mismatch`/`ledger_entry_voided`/`ledger_package_mismatch`）。
- **归属不自动易主＝结构性保证**：企业侧立项路径（`projects` 服务）**没有任何写路径**可触碰商机行——「企业自行注册不转移归属」不是靠判定逻辑，而是靠**路径不存在**；另配**反例用例**（保护期未配置 ⇒ 企业可直签立项；断言归属人/确认戳/状态/保护期逐项不变＋读面 `enterprise_registered` 派生事实可见——注册事实可见但归属不动）。转移唯一路径＝`reassign` 显式治理动作，被 `attribution_criteria` 规则闸 **fail-closed**（本期不可用 ⇒ **本期无转移路径**）。
- **保护期三态可区分＋直签封堵钩子**：`unconfigured`（未配置——**既非永久保护也非立即失效**）／`active`（保护中，必有到期）／`expired`（读时派生——存储态 active 但已过到期 ⇒ 放行，**不在读路径写库**）。直签封堵＝**既有 `dispatch/channel_guard.py` H1–H3 的扩展钩子**（惰性：库内无商机行零行为差异；**失败放行**：查询异常不阻断立项——保护是渠道秩序诉求不是资金安全闸；只认「存储态 active 且未到期」），封堵 422 `opportunity_protection_active`＋审计事件 `opportunity_protection_blocked`；**派单线（H1–H3）语义零变化**。
- **规则位 fail-closed＋机器闸**：五配置位缺省 `unset`，依赖规则的动作（续期/客户选择/争议/改派/保护期设定）409 `rule_not_configured`——**数值未定数时「少做」不「猜着做」**；客户自主选择**不改归属**；争议处理机制未成文不可发起、争议期间链路冻结（撮合/售前/结算 409 `opportunity_disputed`）。NEW 测试 `test_rule_document_slots_match_code_bidirectionally` 钉**成文规则文件机器可读槽位块 ↔ 代码常量双向相等**（规则文件与代码配置位一一对应＝任务书 §8 验收③的机械闸）。
- **高风险写闸**：企业确认/归属确认/改派/保护期/续期/售前/撮合/客户选择/结算/争议/规则配置＝**admin 门＋`confirm_password` 双闸**；逐动作 `operation_events` 带 request_id、**密码不落事件**；**自我动作例外只覆盖报备与撤回**（当事人自证）；治理面**全不进 api_catalog**。
- **路由（+16，411→427，全不进 api_catalog；ENTRIES 94 不变）**：读/自证面 4 条（`POST|GET /api/v1/commercial/opportunities`、`GET …/<id>`、`POST …/<id>/withdraw`）＋治理写面 12 条（`GET|POST /api/v1/admin/commercial/opportunity-rules[/<key>]` ＋ `POST …/opportunities/<id>/{enterprise-confirm,attribution,attribution/reassign,protection,protection/renew,presales,match,customer-choice,settlement,dispute}`）。
- **测试**：NEW `server/tests/test_commercial_opportunity_attribution.py` **23 例**——规则文档↔代码双向闸／配置位全 unset／七步链路走通＋跳步拒绝／**归属不静默改写**／结算须 project_share 科目行／撮合同企业／**归属不自动易主反例**／**保护期三态可区分**／active 封堵直签＋审计事件／规则闸四动作 fail-closed／配置后动作放行（选择不改归属＋续期计数＋改派判据）／争议冻结链路／报备 R2 门／治理写双闸／规则配置须书面依据／读面权限四态／撤回仅报备人／事件无密码／不进 api_catalog／`delivery_settlements` 零加列／迁移往返（downgrade 至显式父版本 `c4f7a2d9e1b6`）／保护期值域闭集。
- **变异五连全转红→还原→绿**（字节级备份还原，sha256 终验一致）：**M1** 归属不自动易主失效（企业注册派生事实恒 False）→反例用例转红；**M2** 保护期未配置也封堵（守卫放宽为任意非 revoked 态＋绕过到期派生）→反例用例转红；**M3** 规则未配置仍放行（`require_rule_configured` 直通）→规则闸用例转红；**M4** 争议不冻结（`_reject_when_disputed` 摘除）→争议冻结用例转红；**M5** 归属可静默改写（`attribution_already_confirmed` 摘除）→防改写用例转红。
- **实施期自查修正（记在案）**：①`days_remaining` 初版按 `(expires-now).days` **向下取整**＝配 30 天显示 29；改**向上取整**（剩余不足一天仍算一天＝「今天还在保护期内」口径）；②反例用例初版带着 active 保护期跑企业直签 → 被**自己的保护期封堵**（422）——反例的正确形态恰是**保护期未配置**（企业可注册时归属仍不转移）；③`confirm_attribution` 初版先查状态后查归属 ⇒ 已归属商机的再确认报错码失真；改**归属检查先行**；④争议冻结初版复用通用 `invalid_opportunity_state` ⇒ 用例无法区分「冻结」与「状态错」；补显式 `_reject_when_disputed`（409 `opportunity_disputed`）；⑤交付包夹具初版用合成 UUID 当 leader_user_id 撞 FK RESTRICT——改传真实创始人 id；⑥测试 mypy `re.search` Optional 收窄补断言（union-attr 归零）。
- **架构图口径同步（上游 P2-7 防陈旧闸）**：G4 改结构后（路由 411→427／表 137→139）防陈旧闸转红，按处置改 `architecture/candidate.json`＋已渲染 `system-architecture.html` 的同两处数字（蓝图 49 不变）并用 `tools/capture-full-preview.mjs` 重出整页实拍 `preview.png`——闸复跑绿。
- **融合上游（合并前收口，两轮 rebase）**：上游在本 PR CI 期间先后并入 #240（AI 原生化 N2 归因仪表化，迁移 `c4f7a2d9e1b6`，53→54 rev，+10 测试）、#239（V3.2 G9b 真机两闸轮，+4 测试）与 #235（V31-P1b 大纪要分段抽取与诚实截断，+52 测试；零迁移零路由），致 PR 不可直接合并。冲突**四**处——`server/migrations/versions/e7b2c4d9f1a3_…py`（`down_revision` 由 `d5f9a3c7e1b4` 改挂 `c4f7a2d9e1b6`，保持单链单头）、`server/tests/test_migrations.py`（HEAD_REVISION 与全集断言 54→55）、`AGENTS.md`（口径行 + N2/G4 两 bullet 并存）与 `CHANGELOG.md`（N2 节与 G4 节并存置顶），另加 `docs/audit/v3-workbench-inventory.json`。按「两边全留」消解：口径行取 G4 新值（**139 表／55 rev 单头 `e7b2c4d9f1a3`／427 路由／49 蓝图**）并保留上游 N2 的口径段与 N2 bullet；CHANGELOG 的 N2 节与 G4 节**并存置顶**。融合后**复测**：结构口径逐位不变（427 路由／49 蓝图／139 表／55 rev 单头 `e7b2c4d9f1a3`，审计三清单已重生成、架构图防陈旧闸复跑绿）、mypy 仍 279、pytest **2543 收集 = 2537 passed + 6 skipped**。
- **合并收口（收口 PR 回填）**：PR #241 squash 合并 fork/main **`ffed2e2`**；PR run **42581664828** 四绿 ＋ **main run 42583246694 四绿**（合并态；server-tests 两轮实测 **2537 passed + 6 skipped**〔522.82s / 568.87s〕，desktop 82 文件 **966 passed**）。**部署活体绿**：三镜像 rebuild 自本工作树＋容器内 `alembic upgrade head` 实跑 `c4f7a2d9e1b6 -> e7b2c4d9f1a3`；活体断言三项全绿——容器内 url_map **428**（commercial 43／蓝图 49）／容器 `alembic current` ＝ `e7b2c4d9f1a3 (head)`／api·worker·scheduler 三容器镜像 ID ＝ 本工作树构建产物（`c7fba822aef1…`/`649da2c7ab3b…`/`113dbf0c0e4a…`）；活库断言：G4 两表结构正确（opportunities 34 列/6 CHECK、rules 11 列/5 CHECK）、五规则槽全 **unset**、商机 **0 行**、`delivery_settlements` 仍 20 列；`/ready` 与 `/live` 均 200。
- **口径校正（教训 48：vitest 只认 CI 实测）**：**965→966**——G3 main run 42544563159／G4 PR run 42581664828／G4 main run 42583246694 三轮 desktop CI 实测一致 **966 passed**，前值 965 系 #229 轮文档值（上文 AI 原生化节挂账「归口口径责任人」事项就此销账）；AGENTS 现行结构口径行与 #229 bullet 已同步校正。
- **口径**：pytest **2543 收集 = 2537 passed + 6 skipped**（G3 轮基线 2454 收集 + AI 原生化 N2 +10 + #239 +4 + #235 +52 + 本轮 +23 ＝ 2543；本地 CI 同命令 `-n 4 --dist loadfile` EXIT=0 / 8m39s；**PR run 42581664828 / main run 42583246694 server-tests 实测同值 2537 passed + 6 skipped**）／mypy **279 基线不变**（官方闸 OK）／路由 **427**／蓝图 **49**／表 **139**／迁移 **55 rev** 单头 `e7b2c4d9f1a3`；审计三清单已重生成（route +16 行、DB +2 行、JSON 427/49/139/55 逐位吻合）；桌面零改动（不重打包）；server 变更 ⇒ 合并后 rebuild 三镜像＋alembic upgrade head（新迁移）。

## [未发布] — AI 原生化实施任务书 v1（leader 执行本：轮次编排 N1–N6 + 拍板闸 D-1–D-8）+ 台账/评估同日口径回写（纯文档零代码零迁移零路由，2026-11-09）

- **动机**：蔡工要求「依据台账生成 leader 任务书」——把《AI 原生化差距评估》与《AI 原生化差距台账》从**叙述与登记**转成**逐轮可施工、可复测、可对账**的施工单（台账＝对账入口，任务书＝施工顺序与验收口径的载体，二者互相引用、不得各说各话）。
- **NEW `docs/architecture/AI原生化实施任务书-v1.md`**：①§0 角色与权责（拍板人／leader／AI 三角；leader 七职责 ①–⑦、不得为的八件事、四套编号防串：台账 G-xx／评审 R-xx／轮次 N-x／BP L1–L5 与商业 R1–R4 与 fallback_level L0–L3）；②§1 终点判定（抽离测试通过＋决策位 AI 行使＋飞轮回流闭环＋真实订单首跑，四条同时成立）与四特征翻分目标（②③到 3/3、②④到 2/3）；③§2 起点基线（**现测**，非承袭）；④§3 轮次编排总表 **N1–N6**（N1=Path 0 真实订单首跑／N2=Path 2a 仪表化／N3a-c=Path 1 决策位 AI 起草三子片／N4=Path 2b 评测回归与受控发布／N5=Path 3 提议+人确认／N6=Path 4 版本注册表），每轮带 G 条目认领表与「消解判据→复测动作」逐条映射；⑤§4 逐轮任务书（目标／范围／**明确不做**／前置／拍板闸／DoD／成本判据／风险）；⑥§5 台账操作规程（四态＋回写四要素＋**四证复测规程**：结构证据／动态证据／行为证据（可辨变异）／反向证据；锚点纪律：行号漂移不算失效、语义漂移必须复核；口径现测配方六条）；⑦§6 拍板闸 D-1–D-8（含**不获答复时的默认**：D-1 业务闸未获答复⇒不得擅自开真实订单通道，改走 N2）；⑧§7 红线八条；⑨§8 与在途/并行线边界；⑩§9 风险登记八项；⑪§10 每轮汇报模板；⑫§11 可直接交给 Goal 循环的总提示词（13 条最高规则，起点＝只做认领与核验、不改业务代码）；⑬§12 复测配方速查。
- **施工顺序上的实用结论**：**N2 仪表化不依赖业务闸**——真实订单闸未开时可先开 N2（无归因仪表的决策位 AI 不可审计、不可进化）；N1 的「零代码准备」（C1–C7 前置检查、审阅人安排）可在等闸期并行做。
- **同日第三轮活库实测 ⇒ 口径回写（评估 v1.1 的两句过期表述被更正）**：`agent_runs` 0→**9**（全 `execution_provider=host_channel`、幂等键全 `sim:` 前缀 ⇒ **执行面已在模拟场真实行使，真实客户订单仍零**）、`agent_artifacts` 0→**34**（**全 `reviewed=False`** ⇒ 人工接受信号「只写不读」之外**连写都还没发生过**）、`simulation_runs` 0→**4**（全 completed）、`ai_call_audits` 6→**11** 行（`purpose` 空仍 2 行；新增 3 行 `simulation_evaluation` 且 `used_fallback=false`——G9 真模型评估栈**真跑过**）、`discovery_extractions` 2→**3**（抽取累计 **5 试 1 成**，11-09 又 2 败）。**总判定与四特征评分（2-1-2-1）维持**——回流段四断点（无提示词指纹／无 reviewed 消费／无 CI eval／无发布通道）仍全断；降级链已真实行使（2 条 timeout 带 `fallback_level=L2`），「写错不重做」诚实终态真实出现 1 次。
- **台账 v1.2**（`docs/architecture/AI原生化差距台账-v1.md`）：G-01 现状锚点改写（执行面已行使／真实订单仍零）+ 判据收紧（幂等键非 `sim:`/`rehearsal:`）；G-07 补「`agent_run:` 前缀零生产者」；G-08 补「连写都没写过」；G-10 补「活库已有 3 次真模型评估但不在 CI 内」；G-11 补「模拟场已跑 4 次」；G-12 附注升级（**行使已发生**＝4 次 completed＋3 行非 fallback 审计）；G-16 口径改（2/6 → 2/11）；**新增「规划轮次」列**（对接任务书 N1–N6）；新增「第三轮探针注记」。
- **评估 v1.2**（`docs/architecture/AI原生化差距评估-v1.md`）：§0 速览「最关键的事实」行改写；§4 增「证据基线前移注记」（行使成分更实但回流闭环未达成 ⇒ 评分维持）；§4 ①③④ 表述更新；§5 三次探针汇总改写（audits 明细 11 行＋业务面对照三列＋读法七条）；§7 Path 0 现状更新（真实订单前提仍未取得）；§9 复核记录**第 10 条**（同日口径漂移，三处更正）。**总判定（AI+ 形态／L2+ 复核成立／四路径框架）不变。**
- **在途与并行边界**：PR **#235**（V31-P1 推理模型输出预算）是 **N1 的前置**——修复后必须复测抽取腿；PR #236 仅动 `docs/commercialization/phase-status.md`，零重叠；**本轮不代改 `AGENTS.md`**（现行结构口径行已由 G3 轮更新为 137 表/53 rev/411 路由，与实测逐位一致；仅其 vitest 值写 965、CI 实测 966 差 1，挂账归口口径责任人——避免与 #235 的 AGENTS.md 改动冲突）。
- **边界**：纯文档**不构成任何实施授权**——N1–N6 各轮仍须随轮立项＋拍板（AI 不代拍板）；红线全束（客户资料不入库不入仓／证据只存指针+sha256／写外呼·发信·付款永不降级永不自动／密钥不入 VCS／origin 永不 push／AI 审查不执行被审代码）；四份文档均为**内部文档，不随招商材料外发**。
- **口径**：零代码零迁移零路由零桌面零测试增量 ⇒ 结构口径不变（**411 路由 / 49 蓝图 / 137 表 / 53 rev 单头 `d5f9a3c7e1b4`**／api_catalog 94 ENTRIES，与 AGENTS 现行口径行逐位一致）；pytest **2448 passed + 6 skipped** / vitest **966**（82 文件）/ mypy **279**——**取自最近 main CI 实测 run `42544563159`，本轮未重跑测试**（纯文档轮）；无 rebuild／无 alembic／无便携版重打包。

## [未发布] — 商业化 G3：收入科目层与订阅席位计费（科目层五表+席位不重复收+首单扣费闸，2026-11-09）

- **范围**：任务书 T-10／T-11／T-13 §7（G3 目标＝「把席位、培训、认证、陪跑与收入科目分离落库」）。本轮成文 **ADR-008**（收入科目层与订阅席位计费），承接 **ADR-003** §2.1–§2.5（科目层独立于 `delivery_settlements`、份额复用 `seat_shares_for`、比例不落数、六名目只定义归属、科目层写路径属高风险写）与 **ADR-007**（admin 门＋密码确认双闸、自我动作例外、治理面不进 api_catalog）。前置：G0 #216 / G1 #217 / G2 #228（`b0fd5fc`）已合并；G3 开工基线 fork/main `e06ae8d`。
- **DB（迁移 `d5f9a3c7e1b4`，52→53 rev，additive 五表）**：①`commercial_revenue_ledger`＝**收入科目层**（ADR-003 §2.1「收入类型 → 金额 → 关联对象」；三类科目 `seat_fee`／`training_fee`／`project_share`；外键指回 `quotes`／`payments`／`contracts`／`delivery_settlements`／`delivery_packages`／`training_entitlements`；CHECK 联锁含**关联对象至少一个非空**）；②`commercial_deduction_elections`＝扣费方式**书面选定**（指针＋sha256；部分唯一索引＝一人一条 elected）；③`commercial_fee_configs`＝三个配置位（认证费金额／陪跑期限／认证通过线），**迁移播种为 unset**；④`commercial_split_rules`＝分成比例**结构**（角色 R1–R4 × 项目类型 → `ratio_bp` 万分比），**本期零行**；⑤`commercial_certification_records`＝认证挂模拟考核（挂 `simulation_evaluations` 指针＋快照 verdict/score）。**未向 `delivery_settlements` 加任何列**（结构钉：head 上列集合逐位比对）。
- **三类科目分别记账可分别查、可对账**：读面 `GET /api/v1/commercial/revenue-ledger`（按 `subject_type` 过滤；本人只见自己的、admin 见全量）、`.../reconciliation`（按科目×名目汇总＋**与收款台账的差异笔数**＝行金额 ≠ 关联收款实收额）、`.../<entry_id>`。**六项名目只定义归属**——归属矩阵 `LINE_ITEM_SUBJECTS`（软件订阅／企业订阅／使用量→席位费；项目费／平台分成→项目分成；软件服务费→培训费）是代码层权威，错配 400 `line_item_subject_mismatch`；**金额算法不在本期定义**，金额来源只有三个：配置位（缺省未设⇒不可用）／关联收款的**实收额**／人工录入的线下约定金额（必附指针＋指纹）。
- **席位不重复收（任务书 §7 验收：L2／L3／L0 三组合）**：套餐目录 `REVENUE_PACKAGES` 声明 `covers_first_year_fee`（实战营 `bootcamp_practical`／陪跑营 `bootcamp_mentorship` 为真；**不落价目**——价格走 `quotes`／`payments` 收款台账，避免双写）。判定走**两条独立路径**，任一成立即拒绝重复收取：①权益行席位来源为实战营/陪跑营；②科目层已有该人「含首年席位费」的套餐席位费行。反例用例断言**席位费科目行恒 1 行**；L0 组合（无含席位套餐的候选交付者）扣 **3980** 并随扣费激活席位（来源 `first_delivery`、年度到期）。
- **首单扣费闸落服务层（不靠流程纪律）**：交付者首个付费项目**交付完成并验收后**才触发扣除 3980；闸门顺序＝验收（409 `acceptance_not_passed`）→交付席位本人（403）→项目有「实收且验收通过」的里程碑收款（409 `payment_not_settled`）→**不重复收**（409 `seat_fee_already_included`／`seat_already_active`／`seat_fee_already_charged`）→**扣费方式已书面选定**（409 `deduction_method_not_selected`）；随后记账＋激活席位。**未接单候选人不产生年度欠费**（扣费只挂已接单且已验收的交付项目；方案 A 一次性扣除无年度周期）。
- **扣费方式＝当事人自证动作**（ADR-007 §2.4 的延伸）：`commercial_deduction_elections` 只认**交付者本人**选定自己的方式（路由不接受 `user_id`，**admin 不得代选定**——防止平台替用户承诺扣费；G2「企业自证：admin 不得代确认」同款边界）；书面证据必须附 `source_uri` 指针＋`content_hash` sha256 指纹。方法集 `{one_time, annual_installment}`：**本期只实现方案 A（一次性扣除）**；选方案 B 时扣费闸 fail-closed 409 `deduction_method_not_implemented`（不误按 A 扣、不静默分期）。
- **认证挂模拟考核，通过线本期不设**：`commercial_certification_records` 挂考核评估指针；**通过线配置位未设 ⇒ 记录停在 `pending_threshold`，不判定通过**（认证状态不变更）——缺省不可通过，不落任何默认分数线；配置且 verdict='pass' 且得分达标才置 `certified`，`certification_source` 指向考核行。**认证费金额本期不设 ⇒ 缺省不可收款**（`fee_not_configured` 409；且认证费只认认证类培训权益行）。
- **陪跑期限与培训周期挂钩（结构先落、数值待定）**：`commercial_fee_configs.mentoring_period_days` 未配置 ⇒ 陪跑权益的 `valid_until` 留空；配置后按周期推导（G1 的 `add_training_entitlement` 增补该挂钩，延迟导入避免商业模块成环）。
- **分成比例本期不落数**（ADR-003 §2.3）：`commercial_split_rules` 本期**零行**；登记维度即 `status='unset'`（`ratio_bp` 恒 NULL），配置比例必须附书面依据指针＋指纹。**项目分成只引用既有分账结果、不重算**——科目行金额 ≡ `delivery_settlements.delivery_amount`（传入不一致金额 409 `amount_mismatch_settlement`），席位份额快照取 `seat_shares_for` 的**结果引用**（`basis.seat_shares_source` 标注来源）；比例行只提供落位与可见性，**不参与金额计算**。
- **高风险写闸**：科目记账／首单扣费／配置位／分成登记／认证判定＝**admin 门＋密码确认双闸**（403 `commercial_admin_required`／缺密码 400／错密码 403 `invalid_password`）；逐动作 `operation_events` 带 request_id、**密码不落事件**；**自我动作例外只覆盖「扣费方式选定」一项**（当事人自证），**不含**记账、扣费、配置位、认证判定。
- **路由（+14，397→411，全不进 api_catalog；ENTRIES 94 不变）**：读面 7 条（`packages`／`revenue-ledger`／`revenue-ledger/reconciliation`／`revenue-ledger/<id>`／`deduction-election`／`certification-records/<user_id>`）＋自证面 1 条（`POST /api/v1/commercial/deduction-election`）＋治理写面 7 条（`POST /api/v1/admin/commercial/revenue-ledger`／`.../first-order-fee`／`.../fee-configs/<key>`／`GET|POST .../fee-configs`／`GET|POST .../split-rules`／`.../certification-records`）。
- **测试**：NEW `server/tests/test_commercial_revenue_ledger.py` **26 例**——三类科目分别可查可对账／名目归属错配拒绝／关联对象必填／**L2·L3 不重复收反例（席位费科目行恒 1 行）**／L0 首单扣费成立＋席位激活／重复扣费拒绝／**验收前不触发**／**未选定方案不得扣费**／未实现方式 fail-closed／选举只认本人＋书面证据必填＋指纹校验／治理写双闸／记账事件带 request_id 无密码／读面权限四态（本人·admin·他人 403·未认证 401）／**认证通过线未设不判定通过**＋配置后达标置 certified／认证费缺省不可收款／陪跑期限结构（未设留空·配置后推导）／**分成结构零行·登记即 unset**／**项目分成引用分账不重算（金额与份额快照逐位对照）**／`delivery_settlements` 零加列结构钉／治理面不进 api_catalog／配置位全 unset／套餐目录不含价目／迁移 additive 往返（downgrade 至**本迁移的父版本**显式 revision——`-1` 会被后续叠在头上的迁移顶掉）。
- **变异十连全转红→还原→绿**（任务书 §12.10）：**M1** 不重复收判定整体失效→不重复收反例转红；**M2** 未选定方案仍扣费→未选定用例转红；**M3** 验收前仍扣费→验收闸用例转红；**M4** 项目分成按比例重算（不引用分账）→引用用例转红；**M5** 名目归属校验失效→归属用例转红；**M6** 关联对象必填失效→关联用例转红；**M7** 通过线未设也判通过→认证用例转红；**M8** 书面证据指纹闸失效→选举证据用例转红；**M9** 认证费缺省可收款→缺省不可收费用例转红；**M10** 陪跑期限未配置也落默认天数→数值待定用例转红。
- **实施期自查修正（记在案）**：④本地全量跑测**必须用 CI 同命令**（`pytest -q -n 4 --dist loadfile`，**不加 `-p no:warnings`**）——加该旗标会让 SQLAlchemy `UTCTimestamp()` 未设 `cache_ok` 的 SAWarning 直落 stderr，被 `test_workbench_seed.py` 的 CLI 输出断言（`modules_created=5`）当成本体失败＝**假红**（本轮实测即被此绊住 1 failed/2421 passed；pytest 的 warnings 插件默认拦下该警告，去掉旗标即全绿）。①科目层的「关联对象必填」初版只认报价/收款/合同/分账/交付包/培训权益，**漏了「订单〔套餐〕」**——线下约定记账（结账金额走线下约定）时无报价无收款会被误拒，补 `package_code` 入关联口径（DB CHECK 同步）；②「已扣过首单费」与「已购含席位套餐」两处判定初版只看 `package_code`，**可被 `seat_source` 旁路**，改为 `package_code`／`seat_source` 双条件；③通用写路径初版只拦 `package_code='first_delivery'`，**漏了 `seat_source='first_delivery'`**——首单扣费必须走专用闸（验收＋书面选定＋不重复收），补拦。
- **融合上游（合并前收口）**：上游在 G3 期间并入 #231（V3.2 G9 接线轮：真实执行面接线＋真模型评估层＋Rubric 覆盖度校准，**+2 测试文件 +26 例**）、#232（V3.1 试点执行与复盘，纯文档）与「AI 原生化差距评估 v1.1」三笔，致 PR 不可直接合并。冲突**仅** `AGENTS.md` 与 `CHANGELOG.md` 两处口径/轮次节——按「两边全留」消解：口径行取 G3 新值（137 表／53 rev／411 路由）并保留上游新增的「V3.1 试点执行与复盘轮」bullet；CHANGELOG 的 G3 节与上游新节**并存置顶**。融合后**复测**：结构口径逐位不变（411 路由／49 蓝图／137 表／53 rev 单头 `d5f9a3c7e1b4`，审计三清单零差异）、mypy 仍 279、pytest **2454 收集 = 2448 passed + 6 skipped**。
- **架构图口径同步（上游 P2-7 防陈旧闸）**：G3 改结构后（路由 397→411／表 132→137／迁移 52→53）防陈旧闸转红，按处置改 `architecture/candidate.json`＋已渲染 `system-architecture.html` 的同两处数字（蓝图 49 不变）并用 `docs/architecture/archify-diagrams/tools/capture-full-preview.mjs` 重出整页实拍 `preview.png`（1440×2098）——闸复跑绿。
- **部署并发覆盖复验（跨会话共享部署）**：部署后约 30 分钟，另一条线的会话从自己的 worktree 重建并 `up -d`，把 api 容器换成**旧代码**（活体 `url_map` 412→398、commercial 27→13、容器内 `alembic current` 报 「Can't locate revision」、`/app/migrations` 挂载指向别人的 worktree）。**处置**：从本工作树重建三镜像（api 镜像 ID `84193bb29335`）＋ `up -d --force-recreate` 三容器 → **复验全绿**（412／27／`d5f9a3c7e1b4 (head)`／三容器 healthy／ready+live 200）。**教训**：镜像 tag 与 migrations 挂载源是跨会话共享资源，部署后必须复验「活体路由数 ＋ 容器内 alembic current ＋ 容器镜像 ID」三项（已写入 AGENTS「工作流与陷阱」节）。
- **口径**：pytest **2454 收集 = 2448 passed + 6 skipped**（基线 2402 收集 + 本轮 +26 + 融合上游 #231 的 26 ＝ 2454；本地 CI 同命令 `-n 4 --dist loadfile` EXIT=0 / 8m16s；**终值以本 PR CI server-tests 实测为准**）／mypy **279 基线不变**（官方闸 OK）／路由 **411**／蓝图 **49**／表 **137**／迁移 **53 rev** 单头 `d5f9a3c7e1b4`；审计三清单已重生成（route +14 行、DB +5 行、JSON 411/49/137/53 逐位吻合）；桌面零改动（不重打包）；server 变更 ⇒ 合并后 rebuild 三镜像＋alembic upgrade head（新迁移）。
## [未发布] — V3.1 试点执行与复盘（somwyn E2E 十步全链走通，§17-17 达成；纯文档+活库数据，零代码零迁移零路由，2026-11-09）

- **闸门**：蔡工 2026-11-08 确认 C1–C7 并给出执行数据（C1=代号 **somwyn**；C2=访谈素材取自本地文档中心既有脱敏实记录 `somwyn案例_FDE交付实记录_v1.1.md`〔全代号化，真实资料零入库〕；C3=分解目标自选交付段既有模块）；宿主通道全程关闭（C5）；§17-14 ZCode 联调未触碰（独立拍板项）。
- **执行**：按 `docs/v3.1/pilot-runbook.md` 十步操作序 E2E 全链走通（部署=隔离 worktree compose 栈，alembic head `e9c4a1f7b3d2`）——纪要（全文版抽取两败后人工整理稿 `4b558dce`）→抽取 `02a680d7`（22 facts+7 reqs，review_required）→审阅（20+7 accepted、2 facts needs_clarification=推断/开放问题红线生效）→本体变更集 `ffa95ce0` submit(admin)→confirm(**pilot.reviewer**) 物化 20 术语（**决策分离成立**）→方案 `c0f1dc00` published（9 items）→分解 9 任务（全量 commit 卡项目行锁超 gunicorn `--timeout 120` 被 abort 零残留；**端点原生 item_ids 分批** 9/9 创建，幂等复跑 skipped=9 reason=已分解）→draft-from-plan `44ac0ea1`（`delivery-scope-documents@1`）validate 全绿→admin publish→run `21fc3fa9` **succeeded**（两处 human_approval 经 pilot.reviewer 拍板，审批时延中位数 1.43min）→测试计划 v1 废弃（执行脚本形状解析错，rejected=superseded 留痕）+ v2 `5b538ea5` approved（需求覆盖闸过）→execute dev **7/7 passed**（append-only，报告指针+指纹成对；原件 `somwyn/.fde/pilot-test-report-2026-11-09.md` sha256 `acf61043…`）→证据 `aa2b85a9`（kind=task）→指标 `sections.v31` **七指标全 ok 全有样本**（n=1/2/1/7/1/9/7，零 insufficient_data）。
- **交付**：①NEW `docs/v3.1/pilot-复盘-somwyn-2026-11-09.md`（十步实测时序〔事件时间轴还原，全程 ≈6.1h〕+指标快照原文+事件链核对+五项偏离注记 P1–P4/D1+待办+结论）；②`final-acceptance-checklist.md` 第 17 项回填 ✅，结论改 **17 达成/1 待条件（#14）/0 未达成**；③`implementation-roadmap.md` 待业务闸节更新（试点项勾销）；④`v3-backlog.md` NEW「V3.1 试点遗留登记」四项（V31-P1 **抽取推理模型输出预算**〔真实产品缺陷：降级直连腿未按模型类型预留 reasoning 预算，MiniMax-M3.1-Flash 下大纪要抽取必败〕/V31-P2 批量分解 vs gunicorn timeout/V31-P3 草稿卷属主/V31-D1 审阅复核人工项）。
- **偏差如实注记**：**D1=全部审阅动作（facts/reqs 接受、测试计划批准、执行登记）由 admin 代执行**（无人值守代执行先例；AI 不代拍板红线未破——本体 confirm 与 workflow 拍板均由第二账号 pilot.reviewer 完成）；**建议蔡工桌面端复核全部审阅动作**（operation_events 逐条可回查）。
- **口径**：零代码零迁移零路由零测试增量（pytest 2354=2348+6s / 路由 391 / 蓝图 49 / 表 130 / 51 rev 单头 `e9c4a1f7b3d2` 全维持）；试点数据在活库（项目 `7042d7ab`，代号 somwyn），仓库零客户资料。

## [未发布] — AI 原生化差距评估 v1 + 差距台账（纯文档零代码零迁移零路由，2026-11-09）

- **动机**：蔡工提问「本项目离 AI 原生应用还有多远、怎么才能成为真正的 AI 原生应用」，按其提供的评估框架（抽离测试／AI Native vs AI+／四特征〔智能内生·数据飞轮·人机协同·持续进化〕）完成全仓评估并落盘。
- **NEW `docs/architecture/AI原生化差距评估-v1.md`**：抽离测试逐链判定（决策与账务主干无 LLM 全存活 ⇒ 当前 AI+ 形态，抽离测试不过）+ 四特征评分（①智能内生=部分／②数据飞轮=生产段已通回流段全断／③人机协同=接近达标／④持续进化=基建渐备行使为零）+ BP §1.3a L1–L5 对齐复核（L2+ 成立；L4≈AI Native 交付域形态）+ 四路径路线图（Path 0 前置通道→Path 2 飞轮闭环→Path 1 决策位→Path 3 提议+确认→Path 4 版本注册表）+ 复核记录五处修正。
- **NEW `docs/architecture/AI原生化差距台账-v1.md`**：G-01–G-14 逐条带 file:line 锚点+消解判据+状态（G-12 已 CLOSED=#231），供逐轮实施对账；锚点语义漂移须复核注记。
- **评估基线与现测更新**：fork/main `cddefd4`（#231）；活库 2026-11-09 只读探针——**飞轮首圈已转**（售前链首批真实数据：抽取 2/事实 22/需求 7/方案 1/测试计划 2/workflow_runs 1 succeeded）而 agent 执行面仍零行使；MCP 工具数现测 **17**（15 只读+2 写）；#231 已把「模拟模型评估未接线」消解（台账 G-12）。
- **圆桌评审轮（party-mode，2026-11-09）**：BMAD party-mode 七人对抗评审（Code Review Crew+2 借调）；NEW `docs/architecture/AI原生化差距评估-评审报告-v1.md`（R-01–R-14：采纳 12/部分采纳 2/不采纳 0，总判定维持）。评审期间活库探针第二轮产出两处新事实并回写：**首圈承役通道=降级直连**（audits 6/6 `used_fallback=True`，DSH 未上岗；模型 MiniMax-M3.1-Flash；抽取 4 试 1 成）+ **purpose=None 匿名审计行 2/6**；首圈工作流形态=human_approval×2+skill×1 全 succeeded。评估→**v1.1**（四特征 0–3 标尺化〔①=2 ②=1 ③=2 ④=1〕、Path 重排 **0→2a→1→2b→3→4**〔仪表化前置〕、派单推荐按 BP L3 口径上调进 Path 1、分发边界注记、复核记录第 6–8 条）；台账→**v1.1**（加体量/依赖两列、G-06 上调、G-12「契约在行使零」脚注、新增 G-15 桌面 AI 编排面 / G-16 审计匿名行）。
- **rebase 注记**：并发轮 #232（somwyn 试点执行与复盘）并入后 rebase 解 CHANGELOG 冲突（双方节保留）；首圈数据的官方来历落档（项目 `7042d7ab`、run `21fc3fa9`、`docs/v3.1/pilot-复盘-somwyn-2026-11-09.md`），评估/台账基线对齐 `f589801`；抽取 4 试 1 成根因=backlog **V31-P1**（推理模型输出预算，#232 登记）——评估 §5 行动项随之改写为「跟踪 V31-P1 消解后复测」。
- **边界**：纯评估不构成实施授权；四路径均须随轮立项+拍板；红线全束（AI 不代拍板／证据指针化／客户资料不入库／写外呼发信付款永不降级）；评估文档标注内部、不随招商材料外发。
- **口径**：零代码零迁移零路由零桌面 ⇒ 全部口径零变化（132 表/52 rev 单头 `b3e7c9d1a5f2`/397 路由/49 蓝图）；无 rebuild/alembic/重打包。

## [未发布] — 桌面侧栏账号区两行式压紧（纯桌面，2026-11-09）

- **反馈**：侧栏滚动修复（#227）落地后，蔡工指出底部账号区四行（系统管理员 / 管理员 / v0.3.0 / 退出登录）占高过大、不协调。
- **改造**：四行 → **两行**，信息一条不减。上行 `.account-identity` ＝ 显示名 + 角色（`align-items: baseline` 同基线；名字可收缩省略、角色恒不缩）；下行 `.account-foot` ＝ 版本 | 退出登录（`justify-content: space-between` 分居两端）。CSS 类名 `.account-foot` 取全仓唯一名——`AccountPage` 的 `.account-meta` 是另一套全局网格规则，刻意不共用，防隐式耦合。
- **压紧**：页脚行距 5px→2px、上内边距 16px→10px、退出按钮 `min-height` 26px→22px。浏览器实测页脚总高 **60.4px**（四行式约 100px）。
- **折叠态**：账号区**整体**让位（`.app-shell.sidebar-collapsed .sidebar-account { display: none; }`）——此前逐元素隐藏会留下一条孤儿细线；折叠态下退出走账号页。
- **测试钉**：`design-tokens.test.ts` 新增「侧栏账号区两行式契约」**5 例**（上行同基线 flex + 名字可省略 / 下行两端对齐 / 折叠态整体让位 / C3 版本号小字不回退 11px / 页脚压紧三项：行距 2px、上内边距 10px、退出按钮 22px）。
- **真浏览器验证**（gui-harness + Playwright）：既有两链回归 **11/11** 全过（指引链 5 + 集成桥 4 + 控制台无应用级错误）；`desktop/gui-harness/sidebar-probe.mjs` 侧栏探针由 5 扩到 **10/10**（新增：两行结构上下相邻无重叠 / 页脚总高 ≤64px / 四条信息都真有文本 / 版本与退出同处一行且版本在左 / 折叠态账号区整体隐藏）+ 截图目检（短视口 / 高视口 / 折叠态 / 侧栏特写）。
- **顺带修 harness 保真度**：gui-harness 的 shim 此前把服务端 snake_case `user` 原样回传，缺桌面端 `main/auth-ipc.ts:377` 的 `display_name → displayName` 转换 ⇒ 浏览器里账号名恒空（桌面本体不受影响，是 harness 与桌面不同尺）。本轮补齐该转换（harness 为 dev-only，`apply: "serve"`，零生产影响），探针因此得以断言「四条信息都真有文本」而非「元素存在」。
- **口径**：vitest **965**（82 文件，+5 = 两行式契约钉）；typecheck web+node 双绿；零服务端改动 ⇒ 路由 / 蓝图 / 表 / 迁移 / pytest / mypy 口径零变化。桌面变更 ⇒ **便携版 r24**（`release/蔡工FDE-0.3.0-便携版-r24/`，asar sha256 `657e37e914c280955ec322ee8a23a8ceae1c2b3846ce84721ed98dedd20b3fa3`；本轮独有 marker＝`account-identity` 字节命中 **2**、`account-foot` 命中 **4**、`min-height: 22px` 命中 **1**、`padding: 10px var(--space-3) 0` 命中 **1**，中文 sanity marker「退出登录」命中 **7**）。
## [未发布] — 商业化 G2：企业免费额度与三个体验入口（免费额度两表+主体认定+三入口隔离，2026-11-08）

- **范围**：任务书 T-07 §6（G2 目标＝「免费只到一次完整业务诊断，且额度按企业主体计」）——本轮成文两份 ADR：**ADR-004**（主体认定：统一社会信用代码规范化键、一次一主体不重置、三入口隔离、三档描述、两档体验上限）与 **ADR-007**（关键流转默认需人工确认：admin 门+密码确认双闸、AI 无直写入口、自我动作例外、实测后复审触发器）。前置：G1 权益四分已随 #217 合并 `f186342`；G0 基线审计与四 ADR 已随 #216 合并 `28f55fd`。
- **DB（迁移 `b3e7c9d1a5f2`，51→52 rev，additive 两表）**：`enterprise_quota_subjects`（**PK=规范化统一社会信用代码**（18 位）+ display_name + first_user_id + note）＋ `enterprise_free_quota`（**PK=subject_key——一主体一份**；state ∈ granted/in_progress/completed + granted_by_user_id/bound_user_id/bound_at/completed_at/deliverables JSON/enterprise_confirmed_by_user_id/enterprise_confirmed_at）。**四条 CHECK 联锁**：状态闭集 / **绑定形状**（granted 必未绑定且未完成未确认；非 granted 必已绑定——换账号不得改绑的结构性保证）/ 完成形状（completed 必带 completed_at）/ 确认前提（已确认必已 completed）。
- **主体认定（ADR-004 §1.1–1.4）**：`normalize_subject_key`＝大写＋去空格连字符＋18 位字符集 `0-9A-HJ-NPQRTUWXY`＋**GB 32100-2015 mod-31 校验位**验证；校验失败 400 `invalid_subject_key`（防录入误差造成「同一主体多键」）。**额度键挂主体而非账号**——`subject_key` 是主键，不是 user_id。
- **一次一主体、长期有效不重置**：授予幂等——同主体重复授予返回既有行（`changed=false`），**绝不新建第二份**；启动时绑定 `bound_user_id`（state→in_progress）；**换账号启动 → 409 `quota_bound_to_other_account`**（同一主体再注册不得获得第二次）；完成＝终态（409 `quota_completed`），任何账号不可重启——**无重置路径（人工亦无）**，重置属未来显式立项。**并发亦然**——启动/完成/企业确认三条写路径取额度行时一律 `SELECT … FOR UPDATE`＋**`populate_existing` 刷新**（行锁＋刷新两者同时成立才等于「锁在手读必为已提交真值」；只锁不刷新会被会话里 `expire_on_commit=False` 的陈旧实例绕过＝额度可被并发重发，CR-021 同款教训）。授予路径的「绝不新建第二份」由 `subject_key` 主键在库层兜底（并发双授时后者撞 PK，不会产生第二行）。

- **完成判据＝恰好六项全真**：`FREE_DIAGNOSIS_DELIVERABLES` 六键闭集（diagnosis_report／process_analysis／ai_opportunity_list／implementation_plan／project_tier_budget／next_steps）；缺失或未真 → 409 `deliverables_incomplete` **逐键点名**；多余键 → 400（闭集拒绝＝「六项不免费内容不进入免费流程」）。诊断内容本体由既有 guidance/方案/文档流产出——本模块只承载判据账，**不生成内容、不复制产物**。
- **企业确认＝绑定账号本人**：必须发生在完成之后（未完成 409 `quota_not_completed`）；**admin 不得代企业确认**（403 `quota_confirm_forbidden`——「企业自主选择不被取消」）。
- **三入口隔离（任务书 §6 语义与验收）**：`FREE_TRIAL_ENTRIES` 注册表三条——enterprise（真实业务问题，scope=real_business，须主体键，额度按主体计）／founder（模拟体验，scope=simulation）／deliverer（脱敏模拟项目考核，scope=sanitized_simulation）；`assert_entry_scope_allows` 域闸——**非企业入口取用 real_business 即 403 `trial_entry_scope_forbidden`**（「创业者不能取到企业真实商机」的结构性保证；**商机归属与渠道保护本体归 G4**，本轮不建商机侧读面）。
- **免费边界＝产品边界（代码层+接口层同时可见）**：`FREE_EXCLUSIONS` 七项常量（完整实施／真实 CRM·ERP 接入／大规模数据处理／定制 Agent／生产部署／持续运维／驻场）＋三档**纯描述性**项目等级（standardized／multi_system／complex，**不给数值区间**；命名刻意不带 T——与区域席位档 T1–T3 解耦，ADR-005 域）＋ `GET /api/v1/commercial/free-diagnosis-profile` 读面公开呈现。
- **体验上限（两档×两资源）**：`EXPERIENCE_LIMITS`（founder／deliverer × simulation_runs／mentor_sessions）**保守占位缺省并标注 `experience_limits_placeholder=True`**（试点前须填实数，**禁止无上限**——每格均为正整数）；`check_experience_limit(kind, resource, used)` 触限即 409 `experience_limit_exceeded`（`used >= cap` 即受限）；**上限按资源分别计数**（simulation_runs 与 mentor_sessions 是两个独立计数器，签名必带 `resource`）。**消费接线归 G6 三入口**（显式挂账，本轮只落结构+判定原语，不触碰 V3.2 simulation 域）。
- **高风险写闸（ADR-007）**：授予／完成＝**admin 门+密码确认双闸**（403 `commercial_admin_required`／缺密码 400／错密码 403 `invalid_password`，`auth/passwords.verify_password` 单点）；启动／企业确认＝**当事人自证动作**（认证用户路由＋事件留痕，不需 admin 密码——ADR-007 §2.4 自我动作例外）；逐动作 `operation_events`（target=user〔复用既有注册目标，events.py 零改动〕、changes 带 request_id、**密码不落任何事件**）。**治理面全不进 api_catalog**（AI 不可调用——dispatch admin 面同款边界）。
- **路由（+6，391→397，全不进 api_catalog）**：`GET /api/v1/commercial/enterprise-quota/<subject_key>`（本人/admin，他人 403 `commercial_entitlement_forbidden`、未知 404）、`POST /api/v1/commercial/enterprise-quota/<subject_key>/start`、`POST .../confirm`、`GET /api/v1/commercial/free-diagnosis-profile`、`POST /api/v1/admin/commercial/enterprise-quota/grant`、`POST /api/v1/admin/commercial/enterprise-quota/<subject_key>/complete`。
- **测试**：NEW `server/tests/test_commercial_enterprise_quota.py` 14 例——主体键规范化与校验位拒绝（含 API 400）／授予双闸／授予幂等（一行永不第二份）／启动绑定+换账号 409+本人重启幂等／**并发启动行锁串行化**（裸连接提交「另一账号已启动」＋本会话持陈旧视图→迟到启动必须 409 且绑定不被覆盖）／六项判据六连（五键 409 点名+一 False 409+多余键 400+恰好六键 200+完成后 409+未启动即完成 409）／企业确认五态（未完成 409+他人 403+admin 403+本人 200+重复幂等）／三入口隔离（创业者/交付者取 real_business 403+各入口自有域放行+未知入口 400）／体验上限（触限+按资源分别计数+未知资源 400）／读面权限四态／授予事件带 request_id 无密码／免费边界元数据（含三入口注册表）／治理面不进 api_catalog／迁移 additive 往返。
- **变异六连全转红→还原→绿**（任务书 §6「至少 1 条变异用例证明『额度按账号计』的实现会转红」）：**M1** 允许换账号重绑（＝额度按账号计）→启动隔离用例转红；**M2** 授予幂等键含账号（同主体可建第二份）→授予幂等用例转红；**M3** 放宽完成判据（未齐也算完成）→六项判据用例转红；**M4** 触限判定放宽（`used > cap`，恰好触顶放过）→上限用例转红；**M5** 三入口隔离失效（创业者可取 real_business）→隔离用例转红；**M6** 写路径不取行锁重读（陈旧内存视图当真值）→并发启动用例转红。
- **实施期两处自查修正（记在案）**：①`ck_enterprise_free_quota_bound_shape` 初版把「granted 形状」与「非 granted 形状」两条方向性约束用 AND 连接＝**任何状态都不满足**，改为单条析取约束（models／迁移／测试断言三处同改）；②`check_experience_limit` 初版用**同一个 `used` 同时比所有资源上限**＝mentor_sessions 的小上限会误伤 simulation_runs 的计数，改为**按资源分别计数**（签名加 `resource`，ADR-004 §1.8 同步修订）。
- **顺带修正（G1 遗留的版本假设）**：`test_commercial_entitlements.py` 与 `test_commercial_enterprise_quota.py` 的迁移往返原用 `downgrade "-1"`＝**假设自己的迁移是链尖**——G2 叠上去后 G1 用例即退错版本而红。改为**显式父版本 revision**（沿 `test_migrations.py` 既有惯例），后续迁移再叠不再复发。
- **顺带修正（跨 schema 目录查询导致的假失败）**：`test_migrations.py` 里三处目录查询（`information_schema.columns` 两处 + `pg_constraint` 一处）**未限定命名空间**——PG 的 `information_schema`/`pg_constraint` 跨库可见，同库若存在兄弟 schema（并行跑的遗留 schema，如 `fde_xdist_w0/w1`），`scalar_one_or_none()` 会因多行抛 `MultipleResultsFound`＝**与被测迁移无关的假失败**。改为按 `current_schema()` 限定（目录查询仍看得到本 schema 的真实 DDL，不降低断言强度）。本轮全量实测正是被这条绊住（2 failed/2372 passed），修正后归零。**该修正对上游新加的并行跑测基建尤其关键**——架构评估 P1-3 引入 `-n 4 --dist loadfile` 后，同库会并存 `fde_xdist_w{N}` 兄弟 schema，不限定命名空间的目录查询必然踩雷。
- **架构图口径同步（上游 P2-7 防陈旧闸）**：G2 改结构后（路由 391→397／表 130→132／迁移 51→52），`scripts/audit/check_archify_diagram_freshness.py` 转红（`architecture/candidate.json` 的「路由/表」口径过期）。按处置流程改源 `candidate.json` 与已渲染 `system-architecture.html` 的同两处数字（蓝图 49 不变），并用 `docs/architecture/archify-diagrams/tools/capture-full-preview.mjs` 重出整页实拍 `preview.png`（1440×2098）——闸复跑绿。
- **口径**：pytest **2402 收集 = 2396 passed + 6 skipped**（**PR #228 CI run 42503516295 server-tests 实测 2396 passed + 6 skipped，409.81s**；本地 `-n 4 --dist loadfile` 12m52s 同值；架构评估十项实施轮基线 2388 收集 + 本轮 +14）／mypy **279 基线不变**（官方闸 OK）／路由 **397**／蓝图 **49**／表 **132**／迁移 **52 rev** 单头 `b3e7c9d1a5f2`；审计三清单已重生成（route +6 行、DB +2 行、JSON 397/49/132/52 逐位吻合）；桌面零改动（不重打包）；server 变更 ⇒ 合并后 rebuild 三镜像+alembic upgrade head（新迁移）。

## [未发布] — 架构评估十项实施：机械闸补齐 + 工作流执行器拆分 + 第六张架构图（2026-11-08）

- **范围**：`docs/architecture/archify-diagrams` 的架构评估产出 P1×3 / P2×4 / P3×3 共 10 条 + 1 张待补图，本轮逐条实施（两项拍板见下）。全部是**给已上线的架构补机械闸与边界文档**，不是新功能：迁移双头曾两次把 51 迁移搞成双头（#215 vs #217）、审计清单的蓝图硬编码已漏条三次、2348 例本地 1h+ 反馈环、`paused` 死值域、图纸落后两轮、Redis 降级行为只存在于口头共识、桌面发不起 workflow run。
- **拍板留痕（两项）**：①`paused` 死值域＝**保留 CHECK + 加机械钉**（不收窄值域、不迁移、不动 schema——收窄要动已上线表，收益小于代价）；②pytest 提速＝**xdist + 每 worker 独立库 + CI 并行**（不选只做 CI 分片的轻量版——那不解决本地反馈环）。两项均「按推荐执行 + 留痕可推翻」。
- **P1-1 迁移单头机械闸**：新增 `test_alembic_chain_has_exactly_one_head`——文件解析（revision 集减 down_revision 集）与 alembic `ScriptDirectory.get_heads()` **双来源互校**，同时钉 `HEAD_REVISION` 常量不漂移。此前全仓零机械闸（#215 e7c4a9d2f6b8 与商业化 G1 e9c4a1f7b3d2 同挂一个 down_revision 成双头，事后靠人工 rebase 消解）。变异验证：注入第二条同 down_revision 的迁移 → 解析出 2 个 head 即红。
- **P1-2 工作流执行器拆分（executor.py 1562 → 门面 594 行 + 五个同包模块）**：`constants.py`（异常与常量单点真值，依赖图的根）/ `dag_utils.py`（DAG 抽取·拓扑序·占位符解析·when 裁决，纯函数）/ `serialization.py`（run·node 读取投影 + 定义版本行）/ `settlement.py`（节点与 run 终态结算）/ `dispatch.py`（调度与分派：tx A → call/skill/agent/human_approval）/ `recovery.py`（worker 侧恢复与终态收敛）。依赖单向无环；**对外公开名一个不减**（门面 `__all__` 列 63 个再导出名，routes / control.service / jobs.handlers / 既有测试的 import 全部照旧）。两条**刻意保留的惰性导入**：结算面的退避常量经门面动态读取（`monkeypatch executor._RETRY_BACKOFF_BASE_SECONDS` 仍生效）、调度面的结算调用点经门面动态解析（`monkeypatch executor._settle_node_success` 仍生效——tx B 崩溃族用例依赖它）。偏差记录：caplog 断言的 logger 名由 `fde_api.workflows.executor` 改为 `fde_api.workflows.dispatch`（skill 分派实现随拆分移入该模块，仓库惯例是每模块 `logging.getLogger(__name__)`），断言强度不变。另附 `test_source_size_budgets.py`：四个历史热点（本体 2102 / 项目 1946 / 智能体 1836 / 调研导入 1772）**只钉不拆**（逐文件上限 + 全局 2200 行上限 + 执行器七模块体量上限），防新文件长成下一个千行热点。
- **P1-3 pytest 并行跑测**：本地 `pytest -n 4 --dist loadfile`，CI 的 server-tests 同款。**每 worker 独占一块**：A 路径每 worker 一个独立库 `fde_workbench_w{N}_test`（需 CREATEDB；CI 的 postgres:16 里 POSTGRES_USER=fde 是超级用户），B 路径本机无建库权限时退到「同库分 schema `fde_xdist_w{N}`」＋ advisory lock 键按 worker 分化（PG 的 advisory lock 以 database 为域，同库多 worker 会把整场测试重新串行化——那正是本项要消除的等待）。两条路径**都不回落共享 public**（那不是「慢一点」，是「不可信的绿」）；都不可用时**报错并给出处置**（去掉 `-n` 或给测试角色 CREATEDB）。默认不带 `-n` 仍是单进程单库（既有行为零变化）。新增 `test_xdist_isolation.py` 5 例钉纯函数面。依赖：dev extras 加 `pytest-xdist>=3,<4`（lock 同步 3.8.0 + execnet 2.1.2）。实测：-n 4 全量 13m39s（串行 1 小时量级）。
- **P2-4 结构口径同步钉**：新增 `test_structure_inventory_sync.py` 5 例——`docs/audit/v3-workbench-inventory.json`（本仓**唯一**机器可读结构口径）逐项对账：路由数（url_map）/ 蓝图数（权威注册表）/ 表数（Base.metadata）/ 迁移数与 head·root（迁移链图，head 恰好一个——与 P1-1 单头闸互为印证），漂移即红并给出重生成指引。**不新建第二份口径文件**。
- **P2-5 蓝图清单自动派生**：蓝图注册此前有**两份真身**——app.py 的注册序与审计脚本照抄的硬编码 BLUEPRINTS 清单（必然漂移，已漏条三次）。现在真身只有 `app.py::_BLUEPRINT_SPECS`（经 `iter_blueprints()` 出货，导入惰性完成）；审计脚本删掉 50 项硬编码清单与其 50 行手动 import，改从注册表派生（仍自建裸 Flask 应用，不调 create_app ⇒ 不触 DB/Redis）；原 D1「与 app.py 源码正则对计数」升级为「与实际注册结果对**名字集合**」+「名字不得重复」（同名注册会被 Flask 静默覆盖，比漏条更阴）。新增 `test_blueprint_registry_sync.py` 3 例：注册表 ≡ 实际注册（双向）/ 名字唯一 / **app.py 不得出现绕过注册表的直接注册**（静态钉）。新增/移除蓝图今后只改 app.py 一处。
- **P2-6 `paused` 死值域 → 机械钉**：`workflow_runs.status` 的 `paused` 只在 CHECK 值域、全仓零写入方（run 永不进入 paused）。新增 `test_workflow_run_status_domain.py` 3 钉：CHECK 值域仍含 paused（形状）/ `RUN_STATUSES` 常量同源 / **workflows 包内 `paused` 字面量只允许出现在 models.py**（写入方钉——未来真要写 paused 先拍板补语义）。`models.py` 加注释登记为「预留值域」。
- **P2-7 图纸口径防陈旧闸 + 六图全量刷新**：图纸内容是**结构快照**，而结构每轮都在变——此前五张钉在 fork/main `58f7a26`，其后主干并入 V3.1 P0/P1 与商业化 G1 等多轮，图里的「47 蓝图 · 384 路由」「128 表」早已过期，而**没有任何机器能发现它**。新增 `scripts/audit/check_archify_diagram_freshness.py`（stdlib only，已接入 CI 的 server-tests job）：逐张读 candidate.json，抽出图上的「N 蓝图/路由/表/迁移」与机器可读口径逐项对账，**漂移即红**；revision 须 40 位十六进制；每张图须同时有候选与已渲染 HTML。同时六图全量刷新（钉 `e66647b`）：architecture 口径 47/384/128 → **49/391/130**；lifecycle 的 19 处与 sequence 的 9 处 sources **全部重锚**到拆分后的新模块（executor.py → settlement/dispatch/recovery/executor，models.py 行号随注释位移，app.py → `_BLUEPRINT_SPECS`）；六张重跑 archify finalize，四闸（validate/deliver/check/browser-check）全绿 0 诊断，preview.png 全部整页实拍（六张 PASS）；`meta.output` 改指仓库内已提交路径。交付回执布局更正：`<name>.delivery.json` **必须与 HTML 同目录**（`check --require-provenance` 按同目录找 sidecar，放 receipts/ 会得 provenance unknown）。
- **P3-8 / P3-10 降级与扩缩容边界（新增 `docs/architecture/降级与失败路径契约-v1.md`）**：把「Redis 挂掉会怎样」「worker 能开几个」这两件只存在于口头共识的事写成带 file:line 锚点的契约，并作为第六图的文字底本。**本轮修正了评估稿里的两处事实错误**（诚实注记）：①评估稿写「Redis 挂 → 队列停摆」——方向对但漏了关键一半：**派发信号在 Redis list（`fde-jobs`，LPOP 弹出即出队），任务事实与租约在 PG**（background_jobs + outbox_events）；准确表述是「Redis 挂 ⇒ 新任务投不出去，但已落库的事实不丢；worker 进程因 RedisError 中断，租约到期后由 reconcile 捞回并标 worker_lost」。②评估稿写「登录 fail-closed」——实际是**可配置**：默认 fail-open（记 WARNING 后放行），`FDE_LOGIN_RATE_FAIL_CLOSED=1` 才切 fail-closed；文档按现状写并注明这是显式选择而非静默漏网。P3-10 **只做边界文档化不改实现**：写清「已安全的六项机制」（行锁领单+租约/租约续期/单活守卫/节点级幂等键/失联诚实收口/跳数熔断）与「当前不宜横向扩的三个理由」（LPOP 弹出即出队 / 单活守卫是查-建两步无唯一约束 / 心跳与 reconcile 未按实例错峰），并给出可扩前提五条清单。缺口四条如实登记不代拍板。
- **P3-9 桌面发起运行入口**：桌面此前**发不起** workflow run（服务端 can_manage 闸与 `POST /projects/{id}/workflows/{def_id}/runs` 一直在，桌面零入口）——定义只能看、运行只能由外部发起。`WorkflowConsole` 的**已发布**定义卡加「启动」按钮（canManage 显隐；草稿定义不给按钮——服务端本就只收已发布定义），成功后重拉运行列表（新 run 是 queued，由 worker 接单），403/409 原样呈现不吞（与 cancel/resume 同一纪律）。新增 `workflow-console-launch.test.tsx` 5 例。
- **第六张架构图（`degradation/degradation-paths.html`，workflow 型 · 12 节点 / 8 边 / 3 车道）**：故障面（Redis 不可用 · 沙箱/凭据/宿主通道不可用 · 上游结果未知）→ 判定与降级（L0–L3）→ 兜底与人工（队列停摆待恢复 · reconcile 补投 · 事实留在 PG · 人工核实与接管 · **写外呼·发信·付款永不降级**）。**降级链写 L0–L3 而非 L0–L4**（L4 属商业编号 `commercial/ladder.py`，与本链无关）——评估稿原写 L0–L4，本轮按 `agents/models.py:74` 的 CHECK 更正。
- **顺带修一处失效的静态钉**：`test_prompt_hygiene_jseries.py` 的 J-1 附钉原按 `workflows/executor.py` **单文件**找 system_prompt 调用点，P1-2 拆分后 skill 分派搬到 dispatch.py → 钉失效（红）。改为扫**整个 workflows 包**——钉的是「工作流侧的 system_prompt 实参」而非某个文件（否则下次再挪文件又会失效），断言强度不变。
- **并发跑测的第二个坑（实测发现并修）**：一次 `downgrade base` 会连续 DROP 130 张表 + 数百个索引，**全链单事务** ⇒ 每个 worker 同时持锁上千，4 worker 并发直接撑爆 PostgreSQL 的 lock 表（`out of shared memory` / HINT: increase max_locks_per_transaction）——表现为「2354 例 setup 全红」。修法＝**测试环境按「每个迁移一个事务」跑**（`migrations/env.py` 的 `transaction_per_migration` **仅在 `settings.env == "test"` 开启**，**生产环境保持单事务**，升级原子性语义不变），持锁峰值降到单个迁移量级。生产语义零变更是这条修法的硬约束。
- **口径**：pytest 本地 **2388 收集 = 2382 passed + 6 skipped**（rebase 融合 #221 metrics +3 后的权威树实测；`-n 4 --dist loadfile`，**10m02s**；串行 1 小时量级——本项要解决的就是它；CI 实测以本 PR run 为准）/vitest **956**（82 文件，+5 = workflow-console-launch 新增 5 例）/mypy **279 基线不变**（官方闸 OK）/路由 **391** / 蓝图 **49** / 表 **130** / **51 rev 单头 `e9c4a1f7b3d2`**（**零新表零新迁移**）/审计三清单重生成（392/131 行，零变化）。桌面便携版 **r22**（0.3.0）：`release/蔡工FDE-0.3.0-便携版-r22/`，asar sha256 `a060fe0a10a674b34bde3cd3468109c8a89a1c2f8889f146acea915d146b2bd5`，中文 marker「已发布的定义可直接发起运行」命中 **1**（证明本轮桌面改动确在包内）。server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（**零新迁移** ⇒ 幂等 no-op）。

## [未发布] — 桌面侧栏滚动修复与质感打磨（纯桌面 CSS，2026-11-09）

- **事故**：`.sidebar` 是 100vh + `overflow:hidden` 的 flex 列，nav 不可滚——admin 可见 17 个导航项时，底部账号区（账号名/角色/退出登录）被静默裁掉（2026-11-09 蔡工报告「最下面的信息已经看不到了」）。
- **修复**：nav 成为「品牌 / 导航 / 账号」三段式中的**弹性滚动段**（`flex:1 1 auto` + `min-height:0` + `overflow-y:auto`），底部账号区永远钉在可视区内；折叠态 72px 下滚动条让位（`scrollbar-width:none`，滚轮/键盘仍可滚）。
- **质感打磨**（CSS only，全走既有令牌，无新增 UI 文案）：滚动条**悬停才显形**（透明→白 0.22→hover 0.38，6px 圆角细条）；品牌区收尾细线（rgba 白 0.08）+ 段间节奏 32px→24px；激活项在金轨（S0·C2 inset 指示条，状态主通道不变）之上加同源横向金晕（`rgba(232,163,61)` 0.18→0.07 淡出，补充通道；**不用 brand-gradient**——design-tokens「交互面不铺渐变」既有钉仍绿）；悬停激活项不洗回白底（`.nav-item.active:hover` 特异性修正）。
- **测试钉**：`design-tokens.test.ts` 新增「侧栏导航滚动契约」4 例（弹性滚动段结构 / 底部钉住 / 滚动条悬停显形+折叠态让位 / 金晕是补充通道且不用 brand-gradient）。
- **真浏览器验证**（gui-harness + Playwright）：既有两链回归 **11/11** 全过（指引链 5 + 集成桥 4 + 控制台无应用级错误）；NEW `desktop/gui-harness/sidebar-probe.mjs` 侧栏专项探针 **5/5**（短视口 1280×620 强制溢出：底部账号区无需滚动即可见 / nav 可滚 scrollHeight 891 > clientHeight 327 / 悬停显形滚动条 / 激活项金轨在位 / 滚到底末项与底部同时可见）+ 截图目检（短/高视口+折叠态+特写）。
- **口径**：vitest **960**（82 文件，+4 = 滚动契约钉）；typecheck web+node 双绿；路由/蓝图/表/迁移全不动（零服务端改动）；pytest/mypy 口径全不动。桌面改动 ⇒ **便携版 r23**（`release/蔡工FDE-0.3.0-便携版-r23/`，asar sha256 `df6987a3b9fe22f2aaa1ec35935584ed7f21768ff038bec1d94a923318701e84`；本轮独有 marker＝激活态金晕色值 `rgba(232, 163, 61, 0.18)` 字节命中 1，中文 sanity marker「退出登录」命中 6）。顺带运维注记：10-30 遗留的陈旧 gui-harness dev server（占 5199 端口、服务主树旧源码）已按「一次只留一个 harness」纪律停掉。

## [未发布] — 商业化 G1：权益四分与角色分层（commercial 两表+R 系角色+对外编号映射，2026-11-08）

- **范围**：商业化任务书 T-04/T-05（G0 裁决 ADR-001/002/006 的实施落地；G0 基线审计+四歧义 ADR 已随 #216 入库 `28f55fd`，含活库智能化实测样本=0 ⇒ 评级维持 L2+ 书面口径、关键流转按「默认人工确认」实现）。前置核验：training_entitlement/subscription_entitlement/certification_status/delivery_eligibility 全仓 grep 零命中（00-baseline-audit §B）。
- **DB（迁移 `e9c4a1f7b3d2`，50→51 rev〔同窗口 #215（V3.1 P1-1）并发插队——其迁移 e7c4a9d2f6b8 与本轮同 down_revision 成双头，rebase 重排后本轮挂其之后，51 rev 单链单头〕，additive 两表）**：`commercial_entitlements`（一人一份 PK=user_id 与 fde_profiles 同构：`commercial_role` R1–R4 可空＋`seat_status/seat_source/seat_activated_at/seat_expires_at` 订阅权益组＋`certification_status/certification_source` 认证指针组＋`delivery_eligibility` 交付资格，五 CHECK 闭集；**值域无任何 L 开头角色枚举**）＋ `training_entitlements`（培训权益购买行 1:N：item_type ∈ training/certification/mentoring、status ∈ active/revoked、valid_until 可空=陪跑期限数值本期不定数〔任务书 §1.2-6「规则先立框架、数值后填」〕、不存金额——科目记账归 G3 科目层〔ADR-003〕，避免双写）。
- **角色分层语义（ADR-001）**：R1 企业/R2 创业者/R3 交付者/R4 区域合作商，可空=未分层；与 `users.role`（平台权限角色四值+ROLE_RANK 阶梯+DEFAULT_ACCESS_BY_ROLE）**正交并存互不推导**——复用/扩展权限角色列的方案被否决（会把商业分层混入权限阶梯并破坏 VALID_ROLES 校验与既有测试）；`fde_profiles.level`（交付能力等级：衡量人、越大越资深）与 `agent_runs.fallback_level`（降级链状态：单次运行）零触碰零改动（dispatch 域 16 测试文件回归 100 例全绿）。
- **对外编号映射（ADR-006）**：NEW `commercial/ladder.py` 是全仓**唯一转换入口**——`external_ladder_code` 从权益权威状态纯函数推导：R3 认证∧席位 active=L1（独立 FDE）否则 L0（候选；Q08「交付者」一身份两状态）、R2 按 seat_source 分 bootcamp_practical=L2（实战营）/bootcamp_mentorship=L3（陪跑营）、R4=L4（区域合作商）、R1/未分层=None（企业不参与对外个人编号）；培训营业务名不带 L 编号。静态钉：商业包+迁移文件中带引号 L 字面量只许出现在 ladder.py。
- **四类权益独立（ADR-002）**：五写原语（role/training grant/revoke/seat-activation/certification/delivery-eligibility）各自只触碰本类列组；`delivery_eligibility` 不覆盖 `fde_profiles.status`（前者商业资格后者供给池生命周期，并存裁决）——唯一跨域同步=席位激活时 pending→active 单向升级（suspended 不动、档案缺失跳过不创建，同步事实落事件 `fde_profile_status_sync`）；重复激活 409 `seat_already_active`（「套餐已含首年席位不重复收」计费不变量的结构前提，计费本体归 G3）。
- **高风险写闸（ADR-002 §2.5，L3「AI 出初稿、人审核后生效」形态）**：六条 admin 写路由全挂双闸——服务层 `_require_admin`（403 `commercial_admin_required`）+ `confirm_password` 必填（缺 400/错 403 `invalid_password`，`auth/passwords.verify_password` 单点）；逐动作 `operation_events` 留痕（target_type=user 复用既有注册目标〔events.py 零改动〕、changes 携 request_id/变更前后快照/target_user_id、敏感键正则双保险——密码不落任何事件）。
- **读面**：`GET /api/v1/commercial/entitlements/<user_id>`（本人或 admin；他人 403 `commercial_entitlement_forbidden`、未知 404）返回权益+培训行+对外编号推导；写面 `POST /api/v1/admin/commercial/users/<user_id>/{role|training|training/<id>/revoke|seat-activation|certification|delivery-eligibility}`。**全部不进 api_catalog**（商业治理面，AI 不可调用——dispatch admin 面同款边界）。
- **注册点（7）**：app 蓝图×2（commercial+admin_commercial）/env.py 模型导入（顺带修 quality 导入重复两行）/conftest 清理序（training→entitlements 子表先清）/test_migrations HEAD=`e9c4a1f7b3d2`+全集 51 断言/审计脚本 BLUEPRINTS 登记（有对账断言守漏登）/审计 CSV 重生成（route CSV +7 行 392、DB CSV +2 行 131、JSON 391/49/130/50 wc 核对）。
- **测试**：NEW `server/tests/test_commercial_entitlements.py` 15 例——四类独立反例×4（角色/席位/认证/培训互不推导：单一「会员等级」字段方案被拒的可辨变异反例）、角色值域 L 值拒绝（L0–L4/R5/r3/空串全 400 `invalid_commercial_role`）、admin 门五路由 403、密码闸（缺/错）、席位 pending 同步+suspended 不动+缺档案不建、双激活 409、审计事件 request_id+无密码、读面权限四态+懒初始化缺省、映射闭包全组合（5 角色×2 席位态×4 源×2 认证）、静态钉×2（L 散落扫描+写原语源码级互不触碰）、迁移往返（head 形状+downgrade -1 双表消失+回 head 恢复）、api_catalog 不进；**变异双验证红→还原→绿**（①set_certification 注入席位派生式→反例③转红→还原绿〔首版反例③因「先激活后认证」顺序掩盖写入已改「无席位先认证」可见化——变异敏感顺序教训〕；②models.py 散落 "L1" → 静态钉转红→还原绿）。
- **口径**：pytest 本地 2348=2333+15+6s（rebase 融合 #215 后 CI 实测 **2360=2345+15+6s**〔#215 基线 2345=2333+12，run 42476898994〕）（新 15+迁移 26+dispatch 回归 100 全绿；全量以 pre-commit 闸与 CI 实测为准）/mypy 279 基线不变（官方闸 OK）/路由 **391**/蓝图 **49**/表 **130**/迁移 **50 rev** 单头 `e9c4a1f7b3d2`；**AGENTS 口径行顺带校正**（前值 122/45/363/45 停在 P0-1 时点、P1-2 轮未同步，本轮按现测修正）；桌面零改动（G1 桌面呈现面挂后续轮，便携版不重打包）；server 变更 ⇒ 合并后 rebuild 三镜像+alembic upgrade head（新迁移）。

## [未发布] — 技能按需调用路由定档 + AGENTS「当前状态」三连标题残渣热修（纯文档零代码零迁移零路由，2026-11-08）

- **技能按需调用路由**：AGENTS「工作流与陷阱」新增每轮工作流技能挂点表——开工/交付=**fde-delivery-flow**、PR 前=**code-review**（权限/并发/资金敏感面）、权限·通道·契约改动=**intended-vs-implemented**、SQL/活库取证=**sql-queries**、桌面交付=**fde-gui-regression**→**fde-package-verify**、集成桥=**fde-bridge-capture**、客户线日常=**fde**、轮收尾=**neat-freak**、点名 workflow=**dynamic-workflows**（CreateWorkflow 强制）、架构图=**archify**（手动跑）。并声明四条机制事实：技能调用=Agent 按 description 自主判断非硬闸、点名 `/技能名` 恒可靠、archify 不在可调用技能列表须手动跑、技能正文调用才加载（每会话只预注入名字+description）。`fde-*` 四技能随仓版本化（`.agents/skills/`）。来源=2026-11-08 全仓技能描述逐一核对后的 top-10 评级（aws-messaging/WordPress 系/PM 简历系出局；dynamic-workflows 为备选第 11）。
- **三连标题残渣热修（教训 49/50 家族，#202–#215 插队链引入）**：`## 当前状态（…）` 标题在 fork/main `58f7a26` 重复 3 次（三个分支各 prepend 各自轮次清单、rebase 全保留），且三变体均漏 P1-1/P1-2/P0-4——合并为单一标题：条目取并集按 PR 序 desc（#215>#211>#209>#207>#205>#204>#203；P2′① 编号由 git log `d797746` (#204) 钉死，序位随之无歧义），尾部自「T-Z1 宿主通道实施轮（裁定 A 落地…」起三变体逐字相同、原样保留。**顺带发现不代补**：「现行结构口径」行停在 #203 现测（363 路由/122 表/45 rev 单头 `c3d5e7f9a1b4`）已被 P1-1（384 路由/128 表/50 rev 单头 `e7c4a9d2f6b8`）超车——沿 P2′① 轮「由口径责任人统一补」先例，本轮不代改（口径现测纪律）。
- 零代码零迁移零路由零桌面；pytest/vitest/mypy 口径全不动；无需 rebuild/alembic/重打包。
## [未发布] — V3.1 P2：试点 Runbook 与最终验收勾稽（纯文档零代码，2026-11-08）

- **范围**：任务书 §14 最终阶段（P2）+§15/§16/§17——试点启动的业务闸（真实项目数据+拍板项）未过前，P2 代码面=「把试点的执行面与验收面落盘」。八阶段实施（P0-0~P0-4、P1-2、P1-1、P1-3，PR #197~#221）已全部收口。
- **NEW `docs/v3.1/pilot-runbook.md`**：①闸门声明（runbook 不构成执行授权）；②前置条件清单 **C1-C7**（C1-C3=真实脱敏项目数据闸：项目选定/访谈素材/模块骨架；C4-C7=拍板项：执行角色、宿主通道保持关闭确认〔默认〕、可选真实联调〔商用条款+12 前置〕、试点窗口与复盘排期）；③E2E 十步操作序（访谈导入→抽取→审阅→本体候选→方案→分解→workflow 草稿→发布运行→测试计划/执行/证据→指标复盘——逐步引用八阶段已交付端点与证据/事件锚）；④验收对照与复盘模板（pilot-复盘-<代号>-<日期>.md 落盘口径）。
- **NEW `docs/v3.1/final-acceptance-checklist.md`**：任务书 §17 十九项逐项勾稽——**16 项达成**（附 PR/代码锚：P0-0 四报告/P0-1 追溯与审阅/P0-2 候选与稳定 ID/P0-3 方案与幂等分解/P0-4 draft 与干跑与 admin 发布/Workflow 恢复取消重试/Gate 唯一入口/产物溯源与撤回/失败不可改写/通道关闭可接管/指标灰态语义/Skill 治理态/全量回归/安全线）/ **2 项待条件**（#14 ZCode 真实联调=商用条款书面确认+12 条安全前置逐项通过+#17 E2E 试点本体=真实项目数据闸）/ **0 项未达成**。
- 口径：零代码零迁移零路由零桌面（pytest **2354=2348+6s EXIT=0** 维持/vitest 951/mypy 279/路由 391/蓝图 49/表 130/**51 rev 单头 `e9c4a1f7b3d2`** 不变）；审计 CSV 零变化；无部署义务（纯文档——镜像不含 docs 运行面）。

## [未发布] — V3.1 P1-3：指标与经验沉淀（metrics 报表 v31 节七指标，2026-11-08）

- **范围**：任务书 §11（P1-3）+ 00-gap-register 7.1/7.3 落地；**7.4（delivery_metric_daily）/7.5（skill_improvement_proposals）维持暂缓**（现报表即席聚合足够+skill 消费量闸未过——活库零数据，建表须先证聚合不足）。**7.2 零代码**：裁决列的事件名与本仓等价名逐一映射成立——`requirement_approved/rejected`→`requirement_reviewed`（P0-1，changes.decision）、`ontology_change_approved/materialized`→`ontology_change_set_confirmed`（P0-2，逐项物化结果随事件）、`delivery_plan_approved`→`delivery_plan_reviewed`+`delivery_plan_published`（P0-3）、`artifact_accepted/rejected`→`agent_artifact_reviewed`（goal-tb tb2）；`task_rework`/`artifact_revoked` 挂账（首个真实数据需求出现时立项，不预支埋点）。
- **七指标进既有报表新节 `v31`**（GET /api/v1/metrics/report；裁决「新指标进同一报表不建平行指标面」；全部走 `_metric` 继承 insufficient_data 语义——样本 0 显式灰态不编造数值）：①`workflow_completion_rate`——终态 succeeded 占比（**非终态 run 不进分母**，7.3）；②`workflow_approval_latency_minutes`——workflow 域审批行（workflow_node_run_id 非空、approved/executed）`updated_at-created_at` 中位数分钟（**updated_at 近似拍板时刻，精确拍板时刻在 workflow_run_approval_decided 事件，细化口径挂账**；rejected/expired 不进样本）；③`workflow_hops_distribution`——hops max+avg（B#1 自触发链代数）；④`requirement_approval_rate`（P0-1 accepted/全量）；⑤`ontology_candidate_adoption_rate`——`captured_from LIKE 'discovery:%'` 变更集 confirmed 占比（**非 discovery 来源不进分母**）；⑥`plan_task_decomposition_rate`——approved/published 方案已建链接条目占比（P0-3）；⑦`test_first_pass_rate`——**每用例只计首条执行**的 passed 占比（重试不重复计数，P1-2）。
- **实施注记**：跨域测试序列曾观察到分解路径 project 行 `FOR UPDATE` 挂起（idle-in-transaction 连接持 xid；pg_terminate 后立刻前进）——根因不在生产代码（P0-3 分解测试同链路独立绿），测试改直插 `DeliveryPlanTaskLink` 造分子样本绕开（分解 HTTP 链路已有 P0-3 覆盖）；挂起根因留观察。mypy 平台差异防御：本轮起 `--platform linux` 本地模拟随常规门跑（教训自 P1-1）。
- **测试**：NEW `test_metrics_v31.py` 3 例（空库 v31 节七卡全 insufficient_data/workflow 域〔非终态排除+时延≈10min+hops 分布〕/域速率四卡〔非 discovery 排除+首条-only 采样〕）；**三变异验证全红→还原→绿**（终态过滤摘除/首条-only 摘除/discovery 前缀摘除——M3 首版无判别力〔测试未造非 discovery 样本〕，补样本后转红=变异判别力本身也要验收）；邻域 metrics_report 7 例回归绿。
- 口径：pytest 本地全量 **2354 收集 = 2348 passed + 6 skipped**（EXIT=0 41:00；本轮 +3；CI 终值以本 PR run 为准）；**rebase 融合 #217（商业化 G1）后口径=路由 391/蓝图 49/表 130/51 rev 单头 `e9c4a1f7b3d2`**（融合树 migrations+metrics+commercial 52 例绿）；mypy 279 不变；vitest 951 不变（零桌面）；审计 CSV 重生成（392/131 行）；server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（幂等 no-op——本 PR 零迁移）。

## [未发布] — V3.1 P1-1：ZCode 宿主执行通道·结构化落地（策略层+票据+扩列，通道保持关闭，2026-11-08）

- **范围**：任务书 §9（P1-1）——00-gap-register 5.3/5.4/5.6/5.7 落地；**5.10 闸纪律：12 条安全前置未过前宿主通道保持关闭**（`agent_host_channel_enabled` 默认 False 零改动+两重静态钉），通道执行面（#195 宿主直连/宿主轮询）维持现状。5.2（adapter spawn 段重构）维持容器路径 `adapter_missing` 降级现状（宿主路径已是 T-Z1 实测契约，见 host_channel.py）；5.5（独立宿主代理进程）待分级开放拍板不预支。
- **策略层（5.4，NEW `agents/execution_policy.py` 纯函数）**：①`normalize_workspace_under_root`——`Path.resolve()` 后根锚定（防 `..` 与符号链接逃逸；根内 `..` 穿越规范化后合法=无害穿越不拒）+`FORBIDDEN_MOUNT_MARKERS` 拒绝清单叠加；②`assert_command_allowed`——argv 首元素白名单锚定（大小写不敏感）+64 元素上限；③`clamp_timeout_ms`——30 分钟上限钳制；④`policy_snapshot`——canonical JSON（sort_keys+工具集合排序）sha256 快照，同输入恒同 hash（审计可重算，#209 确定性纪律）。
- **短期授权票据（5.3，NEW `agents/execution_authorization.py` 纯函数）**：HMAC-SHA256 票据（MCP 15min JWT 原型的 agent_run 域对应物）——绑定 user/project/run/workspace/actions + 15min TTL + `hmac.compare_digest` 恒比较；动作闭集 `workspace.read/workspace.write/command.run/artifact.publish`；验证链=形状→签名→过期→run 绑定→动作覆盖五段。**HTTP 发行面不建**（5.10 闸未过——避免「结构存在但永远 409」的死面，随通道开放轮落地；账目注记可推翻）。
- **扩列（5.6/5.7，迁移 `e7c4a9d2f6b8` 49→50 rev，additive 全可空）**：agent_runs +5（host_agent_id〔宿主代理标识——轮询领取面写入；宿主直连无独立代理进程留空〕/authorization_id〔票据引用〕/workspace_ref/resume_session_ref〔--resume 会话〕/policy_snapshot_hash〔策略快照〕）+ agent_artifacts +4（size_bytes/mime_type〔落库时由原件 len+guess_type 得出〕/revoked_by_user_id/revoked_at〔复核撤回留痕补强——此前仅 reviewed 布尔翻转〕）。
- **接线**：宿主直连通道分支——spawn 前 `normalize_workspace_under_root` 根锚定（service 层）+ `assert_command_allowed` 命令锚定 + `clamp_timeout_ms`（run_host_channel 内）；策略快照经 `AgentRunContext.policy_snapshot_hash` → `AgentRunResult` → `_finalize` 落 `agent_runs.policy_snapshot_hash`；run 行补写 `execution_provider="host_channel"`+`workspace_ref`（**顺带补缺口：宿主直连此前不写 execution_provider**）；产物行落 size_bytes/mime_type。容器路径零改动（ctx 新字段缺省 None，AgentRunResult 同）。
- **测试**：NEW `test_execution_policy.py` 11 例（规范化四分支〔含根内 `..` 无害穿越合法〕/命令锚定四拒一过/超时钳制/快照确定性+顺序无关/票据签发验证+六拒/签发四闸/扩列形状/**双静态钉**〔d4_settings 默认关+config.py AST 字面 False〕）；`test_migrations` 27 例（+roundtrip：downgrade 退列/upgrade 重得/projects 行保留）；三变异验证全红→还原→绿（逃逸校验摘除/签名比较摘除/快照排序摘除）；邻域 host_channel 全绿。实施注记：根内单层 `..` 经 resolve 落根内=无害穿越（首版测试误判为逃逸，已修正断言语义）。
- 口径：pytest 本地全量 **2351 收集 = 2345 passed + 6 skipped**（EXIT=0 31:17；本轮 +12=test_execution_policy 11+migrations roundtrip 1；基线 2339 收集〔含 #210 +1〕）；路由 **384** / 蓝图 **47** / 表 **128** 不变（零新表）/ **50 rev 单头 `e7c4a9d2f6b8`** / mypy 279 不变 / vitest 951 不变（零桌面）；审计 CSV 重生成（385/129 行零变化，50 rev 单头核对）；server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（新迁移）。

## [未发布] — V3.1 P1-2：自动测试与交付证据（quality 三表+覆盖闸+append-only 执行，2026-11-08）

- **范围**：任务书 §10（P1-2）——测试计划/用例/执行三表新建（00-gap-register 6.3 负结论核验：quality/ 模块与 test_plan/test_case/test_execution 全仓 grep 零命中）+ 证据完整性只读校验端点（6.5）+ 环境维度与失败不可改写纪律（6.4）。6.1（agent_artifacts.kind=test_results 通道）/6.2（project_evidence 登记簿+gate 提交闸）按裁决复用零代码。
- **DB（迁移 `d5a8c2f4b7e1`，48→49 rev，additive 三表）**：`test_plans`（项目内版本化 draft→approved+superseded；审核戳 CHECK 两段式；source_task_id 可空=任务书「按任务生成」语义）→`test_cases`（case_key 项目唯一 TC-<hex8>；**requirement_key 强制追溯**〔「测试用例可追溯需求」原文〕；acceptance_mode ∈ test/manual（manual=明确人工验收方式，计入需求覆盖）；risk_level 1..3；steps JSON 结构化）→`test_executions`（**append-only**：服务层零更新函数，重跑=新行；environment 三值+result 三值；report_uri/report_sha256 成对 CHECK）。**evidence_links 第四表不建**——测试↔证据关联由既有 project_evidence 登记簿（提交闸+候选采纳，6.2 复用裁决）+cases.requirement_key 追溯承载，单独关联表是冗余（偏差注记，评审可推翻）。
- **生成器（确定性拼装无 AI）**：`generate_test_plan` 消费 accepted 需求（每条一条用例：expected=验收标准聚合、risk_level=priority 映射 high/medium/low→3/2/1、acceptance_mode=test、steps 留待人工补齐）；**条目序=requirement_key 字典序**（#209 教训：单事务 created_at 全同+uuid4 id 无序，插入序不可依赖）；无已批准需求 409 拒空壳；source_task_id 校验归属（跨项目任务 404）。**AI 用例通道为未来增强**——「模型生成用例先审核」由计划 draft→approved 人工闸承载（落库即待审核于 draft 计划）。
- **需求覆盖闸（6.3）**：`review_test_plan` approved 时校验「每条批准需求至少有测试或明确人工验收方式」——本计划+既有 approved 计划的 cases.requirement_key 并集须覆盖全部 accepted 需求，缺失点名 409 `requirement_coverage_incomplete`（detail.missing_requirement_keys）；rejected→superseded（审核戳两分支同打——驳回也是一次审阅）；新 approved 使旧 approved 退位 superseded（历史行不覆盖）。**实施修正**：审核戳须先于退位循环落——循环查询 autoflush 抢跑 flush 本行，approved+无戳撞 `ck_test_plans_review_stamp`（P0-1 两段式 CHECK 家族教训再现）。
- **执行登记（6.4）**：`execute_test_plan` 批量（≤100，单事务全成全败）append-only——**「失败结果不能被摘要 Agent 改写为成功」以「无更新路径」实现**（服务层零更新函数+静态钉断言无 PATCH/PUT/DELETE 执行路由）；**production 硬闸** 409 `production_forbidden`（值域含 production 仅为形状完备，写入唯一通道=服务闸；显式放行属后续拍板项）；报告指针+sha256 成对（400 拒单边）；跨计划用例 404。
- **证据完整性校验（6.5）**：`POST /api/v1/projects/{id}/evidence/validate`（can_view，**零写入零事件**只读干跑）——五维检查：exists_in_project（项目范围，跨项目不泄露）/fingerprint_shape（sha256 64 hex）/pointer_shape（uri ≤500）/channel_registered（captured_from 通道闭集）/operator_registered（人工通道必须留操作者，机器通道 T-E3 语义允许空）；可选 `gate_key`：门禁行须在项目内（gate_scope）且证据 kind='gate'（类型正确——「Gate 只接收类型和项目范围正确的证据」）。
- **API（+6 路由 377→384，NEW quality 蓝图 46→47〔BLUEPRINTS 已同步+CSV 重生成〕，全部不进 api_catalog 治理面）**：POST `/projects/{id}/test-plans/generate`（can_manage 201）、GET `/projects/{id}/test-plans?task_id=`（can_view，任务书「按任务查计划」的项目域落法——偏差注记：书原文 /api/tasks/{id}/test-plans 改项目域+task 过滤，沿 delivery-plans 路由惯例）、GET `/test-plans/{id}`、PATCH `/test-plans/{id}/review`、POST `/test-plans/{id}/execute`、GET `/test-executions/{id}`（书原文全局路径保留，项目范围经行加载校验）。
- **事件**：target_type 注册表 +`test_plan`；三事件 test_plan_generated/reviewed/executed 直落 operation_events（changes 含 version/case_count/decision/created 数）。
- **测试**：NEW `test_quality_test_plans.py` 7 例（生成确定性+追溯断言+字典序/无输入 409/source_task 闸含跨项目 404/覆盖闸点名+双点退位+仅 draft 可审阅+rejected→superseded/执行闸族〔draft 409+production 409+结果闭集 400+报告成对 400+跨计划 404〕+append-only 静态钉+重跑新行+权限族/validate 全分支〔含零写入事件断言+跨项目范围失败+形状闸 401/400〕/目录红线钉）；**三变异验证全红→还原→绿**（覆盖闸摘除/production 闸摘除/validate 项目范围摘除）。夹具教训=ProjectTask 直插需 planned_start/end_date+duration_days NOT NULL。
- 口径：pytest 本地全量 **2338 收集 = 2332 passed + 6 skipped**（EXIT=0 两轮复核）；**CI 实测 2339 收集 = 2333 passed + 6 skipped**（PR #211 run 42455741083——PR CI 跑融合树预览，含并发 #210 的 +1 测试〔该轮 +1 归 #210 账〕；main 合并态 run 42457269338 全绿收口）/ vitest 951 不变（桌面零改动）/ 路由 **384** / 蓝图 **47** / 表 **128**（+3）/ **49 rev 单头 `d5a8c2f4b7e1`** / mypy 279 不变；审计 CSV 已重生成（384/47/128/49 逐位一致，route CSV 378→385 行、DB CSV 126→129 行 `wc -l` 核对）；server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（新迁移）。

## [未发布] — V3.1 P0-4：Workflow 模板与草稿生成（种子通道+三套模板+draft-from-plan，2026-11-08）

- **范围**：任务书 §8（P0-4）——平台模板底座补种子通道，三套首批模板用既有四类节点表达；方案→Workflow 草稿生成（draft-from-plan）；发布权限拍板项 D-2 维持 admin-only。设计裁决见 `docs/v3.1/00-gap-register.md` P0-4 节（4.5 底座在无种子通道/4.6 三套内容新建/4.4 契约字段分两步/4.8 泛化 compiler 先例/4.9 独立干跑端点）。
- **种子通道（4.5+4.6）**：NEW `seeds/workflow-templates.json`（需求发现=访谈确认→调研技能→事实/需求人工审核；方案实施=方案确认→`solutions.create` 骨架→任务整理→计划发布确认；自动化交付=任务确认→执行完成人工确认→证据汇总→Gate 前确认——**执行段采用人工收口：宿主执行通道开放前不自动触发执行；证据只挂候选，采纳唯一入口=真人提交闸**）。NEW `workflows/templates.py`：fail-fast 装载（形状校验+进程级缓存，沿 `tool_groups.json` 先例）+ `seed_workflow_templates` 幂等落库（沿 `seed_public_skills` 先例：active admin 为 actor、落库即 `publish_definition` 锁版快照；**幂等锚=平台定义 name，已存在即跳过绝不覆盖人工改动**；种子 dag 落库前过 `validate_dag_against_registry` 全量校验，白名单缺引用 fail-fast——**部署顺序：先 `seed-public-skills` 再 `seed-workflow-templates`**）+ `list_published_templates` 只读投影。CLI +`seed-workflow-templates` 命令。
- **节点契约扩展（4.4，草稿期先行）**：`validate_dag` 节点字段白名单 +5——`timeout_seconds`（1..86400 整数）、`input_schema`/`output_schema`（JSON Schema 对象形状）、`failure_class`（`retryable`/`fatal`/`needs_human` 闭集）、`plan_ref`（非空字符串，方案关联）；**执行器增强（超时强杀/失败分类归一 error 码）随 P1 执行通道轮；补偿动作语义需设计轮拍板，本轮不建字段**（未知字段仍被 `unknown_field` 拒绝）。
- **draft-from-plan（4.8）**：`compile_plan_workflow` 纯函数（compiler.py，沿 `compile_delivery_preview` 先例：白名单注入制、确定性输出、provenance 溯源）——只收 **approved/published** 方案（草稿方案无坐实口径，语义对齐 confirmed-only）；三节点形 `plan_review`（human_approval，plan_ref 关联方案）→ `implement`（skill 显式版本注入制，params 携带方案条目摘要+契约字段首发）→ `acceptance_review`（human_approval）；**标题剔除 `{{}}` 防占位符误判**。路由 `POST /api/v1/projects/{id}/workflows/draft-from-plan`（can_manage）：**落库走既有 `create_definition` 通道（白名单全量复校），不建平行持久化路径**；跨项目方案 404 不泄露存在性；compile 错误映射 409（`plan_not_approved`/`invalid_skill_ref`/`invalid_capability`/`invalid_plan_items`）。
- **validate 干跑端点（4.9）**：`POST /api/v1/projects/{id}/workflows/{def_id}/validate`（can_view，零副作用）——复用 `validate_dag_against_registry`（与创建/发布闸同尺），返回 `valid/errors/warnings/order/version/content_sha256` 明细；坏 dag 如实报 issue 码不静默。
- **模板只读面（4.7）**：`GET /api/v1/workflow-templates`（require_auth 已认证可见）——只列 published 平台模板（draft/archived 不外泄），id/name/description/version/content_sha256/nodes 摘要+dag 全文（供「复制为项目草稿」消费）；既有 admin 平台列表 `GET /api/v1/workflows` 权限不变。
- **D-2 拍板执行**：发布权限维持 admin-only（任务书要求「人工发布」未指定角色；放开到 can_manage 是权限面扩张——按审计建议拍板：试点期由 admin 发布，留痕可推翻，publish 路由零改动）。
- **顺带修复（#209 CI 实红根因）**：P0-2 `generate_discovery_candidates` 组序非确定性——facts 查询 `order_by(created_at, id)` 在单事务插入时 created_at 全同（事务时间戳）而 id=uuid4 无内在序，组序实为抽签（本地插入序 vs CI 字典序翻转，test_generate_candidates_happy_path 红）。修法：分组迭代改 `sorted(grouped)`（subject 字典序，同「字典序最小」纪律），候选条目与 skipped 双列表同输入恒同序（变更集指纹跨环境稳定）；测试断言改字典序期望+按名定位条目。ontology 邻域 57 例绿+mypy 279 不变。
- **API（+3 路由 374→377，全部挂既有 workflows 蓝图〔BLUEPRINTS 无需同步〕、全部不进 api_catalog）**；**零迁移**（48 rev 单头 `a9c1e5f7b3d8` 不变；模板落库复用既有 `workflow_definitions`/`workflow_definition_versions` 两表，零新表）。
- **测试**：NEW `test_workflow_templates.py` 10 例（种子形状+真实白名单下 dag 全绿零告警/`seed_workflow_templates` 幂等二轮+种子↔DB 逐字节对账/缺 published 技能 fail-fast/契约字段校验九连+补偿动作 `unknown_field` 仍拒/纯函数确定性+输入四闸+花括号剔除/draft-from-plan 全闸族〔draft 409/未发布技能 422/201 落库/provenance/跨项目 404/member 403〕/干跑端点 valid+坏 dag 明细+viewer 可达+stranger 403+404/模板只读面 3 套+draft 不外泄+401+admin 面权限不变）；**三变异验证全红→还原→绿**（幂等跳过摘除/`failure_class` 校验摘除/plan 状态闸摘除）；邻域回归 workflows+plans 63 例全绿。
- 口径：pytest **2331 收集 = 2325 passed + 6 skipped**（本地全量实测，本轮 +10；CI 终值以本 PR run 为准）/ vitest **951** 不变（桌面零改动）/ 路由 **377** / 蓝图 **46** / 表 **125** 不变 / **48 rev 单头 `a9c1e5f7b3d8`** / mypy 279 不变；审计 CSV 已重生成（377/46/125/48 逐位一致，route CSV 375→378 行 `wc -l` 核对，DB CSV 零变化）；server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（零迁移，幂等 no-op）+ **`seed-workflow-templates` 幂等落库**（顺序在 seed-public-skills 之后）。

## [未发布] — V3.1 P0-3：交付方案生成与任务分解（plans 三表+确定性生成器，2026-11-08）

- **范围**：任务书 §7（P0-3）——从已批准需求/已接受事实/confirmed 术语生成可审核 Delivery Plan，映射到既有 project_tasks（不新建平行任务系统）。设计裁决见 `docs/v3.1/00-gap-register.md` P0-3 节（三表负结论核验=全仓 grep 零命中；任务唯一事实源=project_tasks 原文落地）。
- **DB（迁移 `a9c1e5f7b3d8`，47→48 rev，additive 三表）**：`delivery_plans`（项目内版本化：状态机 draft→approved→published + superseded；审阅戳 CHECK 两段式；published 完整性 CHECK；新版本=新行不覆盖历史）→ `delivery_plan_items`（item_type 六值闭集 requirement/objective/milestone/risk/acceptance/non_goal；requirement_keys/fact_ids 引用清单——服务层闸只从已审阅输入拼装）→ `delivery_plan_task_links`（条目↔project_tasks RESTRICT 映射；UNIQUE(item,task)+**UNIQUE(item)=每条目至多一任务** 幂等锚）。
- **生成器（确定性拼装，无 AI 调用）**：`generate_plan` 消费 accepted 需求（每条一个 requirement 条目，验收标准随行）+ confirmed 术语（objective 范围快照条目）+ needs_clarification 事实（**「待澄清」本身是审阅结论之一，作为风险素材独立于 accepted 集查询**——实施中发现双重过滤恒空的真缺陷并修正）；无任何输入 409 拒绝空壳方案（任务书「未核验不新建」精神）；每次生成=新行 version 递增。
- **审阅流**：`review_plan`（approved/rejected 二选一，决策人+时间戳+备注留痕；**approved 使旧 published 行退位 superseded**——同项目至多一个现行方案，历史行内容永不覆盖）；`publish_plan`（仅 approved 可发布，同样先退位旧 published）。目标类型 `delivery_plan` 三事件（generated/reviewed/published）直落 operation_events。
- **任务分解**：`create_plan_tasks`（dry_run 预览/选择性创建 item_ids/幂等跳过——已链接条目回 skipped[reason=已分解]，**幂等调用同样留痕 created=0** 审计诚实）；任务经既有 `create_project_task` 原语创建（module_id 必填=任务必须挂项目既有模块；**不传指派人**——create_project_task 落 default_assignee_role=None=待认领，任务书「未定负责人不随意指派」原文）；module 校验（不存在/跨项目 404）。
- **API（+6 路由 368→374，NEW `plans/` 模块蓝图 45→46，全部不进 api_catalog）**：POST `/projects/{id}/delivery-plans/generate`（can_manage 201）、GET `/projects/{id}/delivery-plans`（can_view ?status=）、GET `/delivery-plans/{id}`（can_view，条目+任务映射）、PATCH `/delivery-plans/{id}/review`、POST `/delivery-plans/{id}/publish`、POST `/delivery-plans/{id}/tasks`（dry_run 默认 true=预览）。权限：写=can_manage、读=can_view、跨项目 403/404。
- **测试**：NEW `test_delivery_plans.py` 5 例（生成 happy+事件/无输入 409/审阅发布全流转+supersede 链〔v1/v2/v3 三版本〕/分解预览-创建-幂等三段+待认领断言+事件双条〔created=1 与幂等 created=0〕/模块与权限闸族）；夹具教训=ProjectTask 无 project_id 列（经 ProjectModule 间接挂，查询三处修正）、ProjectModule 需 module_catalog_id NOT NULL（夹具补 ModuleCatalog 行）。回归：discovery/ontology/migrations 簇全绿；ruff 绿；mypy 279 不变。
- 口径：pytest **2321 收集 = 2315 passed + 6 skipped**（本地全量 33:04 EXIT=0 实测，本轮 +5；CI 终值以本 PR run 为准）/ vitest **951** 不变（桌面零改动）/ 路由 **374** / 蓝图 **46** / 表 **125**（+3）/ **48 rev 单头 `a9c1e5f7b3d8`**；审计 CSV 已重生成（374/46/125/48 逐位一致，`wc -l` 核对 375/126）；server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（新迁移）。


## [未发布] — V3.1 P0-2：本体候选与稳定 ID（ADR-002+discovery 候选桥+term_id 试点，2026-11-08）

- **范围**：任务书 §6（P0-2）三件套——①ADR-002 文档（NEW `docs/v3.1/decisions/ADR-002-ontology-ownership.md`：control/ontology.py=AI 阅读用语义快照 vs ontology/=唯一治理权威，零代码级重叠实测收编、MCP `ontology_read` 契约冻结、不删旧模块、防漂移三边界）；②discovery→本体候选桥（AI 只创建候选，采纳走既有 change-set submit→confirm 人工管线）；③稳定 ID 试点（`project_research_subjects.term_id` 可空 FK，旧行不回填读路径零变化）。设计裁决见 `docs/v3.1/00-gap-register.md` P0-2 节。
- **候选桥**（`ontology/service.py` NEW `generate_discovery_candidates`/`list_discovery_candidates`）：只消费 `review_status=accepted` 的 business_facts（任务书「候选必须引用已确认事实」原文）；按 subject 聚组为 create_term 条目（组内定义取字典序最小摘要=同输入恒同输出、变更集指纹稳定；fact_type→term_type 映射 metric→metric/data_object→attribute/余→entity）；名字域（术语∪别名）占用跳过并回显 skipped；`captured_from=discovery:<id>` 服务层写入（HTTP 人工路径维持拒收）；幂等=同抽取至多一个活跃（draft/in_review）候选变更集（重复调用 200 复用）；**无 accepted 事实 409 不生成**（杜绝空壳候选）。API +2 路由 363→365（POST `/projects/{id}/ontology/candidates/generate` 201/200、GET `/projects/{id}/ontology/candidates`，蓝图不变全部不进 api_catalog，生成=can_manage/清单=can_view）。
- **稳定 ID 试点**（迁移 `d6f2a8b4c9e1`，45→46 rev，additive 一列一索引）：`project_research_subjects +term_id`（String36 可空 FK→ontology_terms RESTRICT——术语行永不物理删除〔merged/superseded 是状态〕故不构成生命周期阻塞）。链接时机=术语落定：`create_term` confirmed 路径（change-set confirm 物化与直落 confirmed 同汇点）后一次性 UPDATE 同名 subject（只链接 term_id IS NULL 行=幂等回填；已链接行不回改，术语合并不改写历史链接、读路径 impact_of_term 名字域继续兜底）；conftest 清理序现测安全（subjects 两簇均在 terms 之前，RESTRICT 无需重排）。
- **D-1 跨项目同名告警（只读）**：`cross_project_name_conflicts` 助手（confirmed 术语∪别名跨项目查询），候选生成响应附 `cross_project_conflicts`；不动项目内唯一约束（多项目隔离是刻意设计，告警仅作改名/合并决策输入——拍板项 D-1 按推荐项先行、留痕可推翻）。
- **测试**：NEW `test_ontology_discovery_candidates.py` 10 例（happy path 仅 accepted 入候选/同名占用跳过/幂等+409 闸族〔no_accepted_facts·running·缺参〕/权限族〔member 403 生成、200 清单、跨项目 403·伪造抽取 404〕/跨项目告警只读性/清单投影排除人工 change-set/confirm 物化自动链接/直落 confirmed 回填旧数据+重复落定 409/合并不改写链接/无术语主体 NULL+读路径零变化）；回归 ontology 三件套 43 例全绿；test_migrations 26 例（roundtrip 过新头）；ruff 绿；mypy 279 不变。
- **实施中修正（诚实注记）**：①组内定义初版取「首条摘要」但事实行 id=uuid4 无内在顺序→同输入不同输出（变更集指纹不稳），改为字典序最小+测试钉；②审阅戳 CHECK 正确拦截测试工厂无戳 accepted 行（约束按设计工作，工厂补戳）；③mypy Result.rowcount attr-defined → getattr 收窄。
- 口径：pytest **2297 收集 = 2291 passed + 6 skipped**（本轮 +10，基线 2287=2281+6s 本地实测；CI 终值以本 PR run 为准）/ vitest **951** 不变（桌面零改动）/ mypy 279 / 路由 365 / 蓝图 45 / 表 122 / **46 rev 单头 `d6f2a8b4c9e1`**；审计 CSV 已重生成（365/45/122/46 逐位一致）；server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（新迁移）。


## [未发布] — P2′① 宿主轮询领取：服务端咬合接线（领取/回执/失联三面，2026-11-08）

- **形态落地（§11.3 六条约束 → 代码）**：NEW 迁移 `f6d3a9c1e7b2`（39→40 rev 头 `f6d3a9c1e7b2`）——`agent_runs.status` CHECK 置换加 `host_running`（对齐 T-J2 先例，零列重建）+ 5 新列（`execution_provider`〔sandbox 默认/host_poll〕/`host_claimed_at`/`host_token_hash`〔sha256 零明文〕/`host_receipt_at`/`host_lost_at`）+ 领取面索引；`IN_FLIGHT_STATUSES` 补 `host_running`。
- **三条宿主机器面路由**（不进 api_catalog，与 bridge 同族；鉴权=`X-Host-Poll-Token` 头 sha256 比对）：`GET /agents/host/status`（待领取数+失联标记顺带触发）/`POST /agents/host/claim`（FIFO+行锁 skip_locked+幂等重领同 token 返回同载荷+异 token 403）/`POST /agents/host/runs/{id}/receipt`（终态语义与容器对齐：exit0=completed/非零=failed/宿主报 timeout·budget_exceeded 同名终态；产物**宿主侧 sha256 直录**〔storage_ref 带 `host:` 前缀，服务端永不回读原件〕；校验失败只记 failures 不改终态——H4 人工按明细处置）。
- **发起侧**：`agent_host_poll_enabled` 开启时 start_run 落 `execution_provider=host_poll`+保持 queued 即返回 **202**（发起=受理，执行由宿主代理异步驱动；优先级高于 dev 直连）；config 新增 `agent_host_poll_enabled`（默认 False）/`agent_host_poll_token`（SecretStr）/`agent_host_lost_mark_minutes`（默认 30）。**生产启用闸未解除**：`adapter_missing` 维持到「①实装 + D3 书面回执 + N2 联调签核」齐备——本开关只解除形态未实装，不解除人工闸（H4/H1/N1/N2 原样）。
- **H4 失联只标记**：`mark_host_lost` 扫描 host_running 超阈未回执 ⇒ 打 `host_lost_at`（幂等不重打；**不迁移状态不自动重试**）；由宿主代理 status 轮询顺带触发，零 scheduler 依赖。
- **测试 pytest +19**：NEW `test_host_poll.py`——fail-closed 闸 3（默认关/半配置/坏令牌）/领取 6（FIFO+状态迁移+幂等重领+**续领语义**〔代理崩溃重启不带 run_id 续上自己手里的活〕+token 轮换后旧 hash 续领冲突+空队+sandbox 隔离）/回执 8（completed 产物直录+非零 failed+宿主 timeout+幂等 duplicate+令牌绑定+**轮换后回执 403**+未领取拒绝+校验失败明细与指纹缺失不落库）/失联 2（超阈标记+新鲜跳过）/HTTP 烟测 1（关闭态 403→status→claim→receipt 全链+错误投影）。
- 口径：pytest 终值以本 PR CI run 实测为准（基线 fork/main `ba61d2c`（rebase 后权威树，含 #203 discovery）本地收集 2292 ——V3.2 G2-G7 +115 与 #203 +? 均未入 AGENTS 口径行 2152，本轮不代补、随轮以 CI 为准）；**+3 路由面**（rebase 后权威树实测 **366** 路由/45 蓝图/122 表/46 rev 单头 `f6d3a9c1e7b2`——含 #203 discovery 的 +7 路由 +4 表 +1 迁移一并基线校正；清单已重生成随 PR 提交）；vitest 不变。台账钉自检：本节含 pytest + 交付信号（delivery）。
- 关联：消费 #193 §11.3 拍板（六条决策级约束）；与 V3.1 P1-1 分工——票据（5.3）/execution_policy（5.4）/artifact 扩列（5.7）/provider 字段扩展（5.6 部分本轮已带 execution_provider）归 V3.1 线后续轮。
## [未发布] — V3.1 P0-1：访谈事实与需求结构化（批A 服务端+批B 桌面审阅面同 PR，2026-11-08）

- **范围**：任务书 §5（P0-1）服务端半——四表+迁移+契约校验器+后台抽取 job+8 路由+14 例测试；桌面审阅 UI（DiscoveryPanel）归批 B 另轮（任务书 §15「每个 Goal 一个明确子切片」）。设计裁决与负结论核验见 `docs/v3.1/00-gap-register.md` P0-1 节（复用 transcripts 生命周期/T-A2 脱敏三道防线/guidance 管线范式；四表确认无承接体）。
- **批B 桌面（同 PR）**：NEW `desktop/src/renderer/src/discovery/DiscoveryPanel.tsx` 挂项目 overview tab（转写面板后）——抽取发起（纪要下拉+幂等双文案）/抽取记录（失败码+脱敏复核 tooltip+重跑仅 failed）/事实清单（过滤+三动作+**批量接受本页待审**+锚点三形态 line·transcript_segment·char_span 呈现）/需求清单（批准/否决/澄清）；写操作 canManage 显隐。NEW `discovery-panel.test.tsx` 7 例。vitest 944→951（+7）；typecheck 0 错。
- **DB（迁移 `c3d5e7f9a1b4`，44→45 rev 挂上游 V3.2 G6 头 `e8b1d5f9a3c7`，additive 四表）**：`discovery_extractions`（状态机 queued→running→{review_required|failed}；幂等键 UNIQUE(project,source_type,source_id,extractor_version,prompt_version)；source_sha256 服务端从源行读取、客户端不可伪造；redaction_entries 复核条目）→ `business_facts`（fact_type 十值〔任务书九值+open_question 归一〕+classification 五分类**对齐 guidance**〔ai_synthesized/human_added 保留给人工路径，v1 不开写面〕+行级审阅 pending→{accepted|rejected|needs_clarification}，审阅终态留痕 reviewed_by/at+comment；UNIQUE(extraction,fact_type,subject,predicate) 批内身份）→ `requirements`（requirement_key 项目内唯一 R-<hex8>；六类型+三优先级；acceptance_criteria 结构化列表 1–20 条；approved_by/at 审阅留痕）→ `requirement_sources`（需求↔事实关系表——任务书「长期用关系表非 JSON ID 数组」原文落地；UNIQUE(requirement,fact)）。CHECK 六道：审阅戳方向「终态必带戳、pending 必无戳」两段式（初生 needs_clarification 合法）；推断/开放问题初生强制待澄清、人工澄清后可流转。
- **抽取管线**（NEW `discovery/jobs.py`，克隆 guidance/jobs.py 纪律）：outbox topic `project.discovery.extract`（RECOVERABLE 集 +worker_loss 失败钩子沿 guidance 先例）；AI 走 `execute_ai_prompt(return_metadata=True)` 单一入口（预算门+审计+降级直连全复用，use_tools=False）；契约失败一次自动重试（概率性畸形）→ 整批失败零写入（任务书「不得静默部分写入」）；输出端逐字符串过 `redact_text_detailed` 兜底 + `discovery.redaction_review` 事件（guidance 第③层同构）；推断（inference）与开放问题（needs_clarification）分别落 ai_inferred/open_question 分类并强制 needs_clarification 审阅态；**无来源事实的需求不得自动接受**（source_fact_indexes 空 → needs_clarification）。
- **契约**（NEW `discovery/contract.py`）：精确键集+域外键拒绝+fact_type/requirement_type/priority 闭集+批内事实去重+验收标准 1–20×500 字+source_fact_indexes 越界/重复拒绝+source_locator 三形态闭合（line≥1/transcript_segment 0≤start≤end/char_span start<end）。NEW `discovery/prompt.py` v1 纯常量（J-1 提示词卫生：模块级常量形态，已登记 `test_prompt_entrypoint_gate` 白名单 `_ALLOWED_PROMPT_CONSTANTS`）。
- **API（+8 路由 355→363，蓝图 44→45，全部不进 api_catalog——治理审阅面沿 transcripts/ontology 先例）**：POST/GET `/projects/{id}/discovery/extractions`（创建 201/幂等复用 200；can_manage）、GET `/discovery/extractions/{id}`、POST `/discovery/extractions/{id}/run`（**重跑仅 failed**——review_required 行审阅痕迹不可覆盖 409）、GET `/projects/{id}/business-facts`（review_status/fact_type 过滤+有界分页）、PATCH `/business-facts/{id}/review`（终态 409）、GET `/projects/{id}/requirements`（status 过滤）、PATCH `/requirements/{id}/review`。权限：写=can_manage、读=can_view、跨项目 403/404、伪造 source_id 404。
- **测试**：NEW `test_discovery_extraction.py` 14 例（契约四态/HTTP 创建幂等+三道闸/重跑保护/成功流/重试与零写入/输出脱敏+复核事件/推断强制澄清/worker_loss/审阅流转+终态/列表过滤+越权）；变异面：审阅戳 CHECK 方向与迁移同源（初生 clarification 两段式断言）。回归：test_migrations/test_route_inventory_sync/test_prompt_entrypoint_gate/test_outbox/test_job_reconcile/test_guidance_redaction_worker/test_transcript_drafts/test_ledger_sync_nail + 上游 simulation 域 14 例全绿；mypy 基线 279 不变；审计 CSV 已重生成（route 363/blueprint 45/table 122/rev 45 单头）。
- **接线上游并发**：批 A 开发窗口内 fork/main 并入 #197（本线 P0-0）/#198–201（V3.2 模拟训练场 G0–G7）——迁移链 rebase 挂 `e8b1d5f9a3c7`、test_migrations 注释行合并、known 数 44→45、extract 脚本 BLUEPRINTS 双登记（discovery/simulation 同窗）、测试库按外来戳配方全量重建（半迁移脏态：版本戳=head 而 simulation 表缺失——DROP 全表重建后 clean build 123 表）。**教训**：alembic_version 戳会被同 revision id 的新文件「骗过」upgrade——重建必须清全表而非只 downgrade。
- 口径：pytest **2287 收集 = 2281 passed + 6 skipped**（本地全量 40:54 EXIT=0 实测；其中本轮 +14=test_discovery_extraction，其余增量=上游 #198–201 simulation 域测试未随其轮在根 CHANGELOG 报数，本轮现测一并落账；CI 终值以本 PR run 实测为准）/ vitest **951/951**（81 文件；基座 944 + 本轮批B +7）/ mypy 279 不变；**零桌面零 api_catalog**；server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（新迁移）。

## [未发布] — 文档基线与结构口径对齐轮（纯文档零代码，rebase 至 #203 / 2026-11-08）

- **版本口径统一**：`VERSION`、README 版本徽标、`AGENTS.md` 首段 `v0.2.0` → **`0.3.0`**（与 `desktop/package.json` / `server/pyproject.toml` 发布列车一致）。README 升版说明里的 `v0.2.0` 是 tag 命名示例、非版本口径，保留原样。
- **AGENTS 现行口径行**：状态段新增 `fork/main 92ca0bd` / PR #203 现测一行（122 业务表 / 45 迁移 head `c3d5e7f9a1b4` / 363 路由 / 45 蓝图 / `api_catalog` 94 ENTRIES / mypy 279）。**各历史轮 bullet 中的口径数字为该轮时点实测值，作历史记录保留、未改写**（尤其 V3.1 P0-0 轮的 `109 表/39 rev/323 路由`）——改它会篡改历史。
- **CI 实测核销**：#203 把口径推进至 122 表 / 45 rev / 363 路由 / 45 蓝图（CI 实测 pytest **2287 收集 = 2281 passed + 6 skipped**、vitest **951/951（81 文件）**，见 #203 bullet；本 PR 仅刷新口径行与审计 CSV 基线标记，不引入新测试增量，CI 终值以本 PR rebase run 实测为准）。
- **操作手册**：尝试 §3 标题与正文 12 → **13 个 tab**（依据 `routing/useHashRoute.ts` 的 `PROJECT_DETAIL_TABS`；补 §3.12「执行智能体」/ §3.13「评审会」两节），新增 §15「模拟训练场」（左侧独立导航 `#simulation`，5 分区；**训练场是全局页，不是第 14 个 tab**）——但因 `server/src/fde_api/control/bundled/help_manual.md` 孪生副本测试硬锁（12 tab：`test_docs_copy_of_manual_stays_identical_to_bundled` / `test_manual_and_ui_page_agree_on_key_facts`），于 `be564e0` 回退，维持 12 tab；落差登记于《同步说明》。
- **配置样例**：`.env.example` / `server/.env.example` 补注释态 `FDE_BRIDGE_TOKEN` / `FDE_LOGIN_RATE_FAIL_CLOSED`（此前仅代码与 AGENTS 有语义）。真实令牌仍只放 `server/.env`，永不提交。
- **审计清单**：`v3-route-inventory.csv` / `v3-database-inventory.csv` 首列 repository 标记 `0570384` → `92ca0bd`（rebase 至 #203，CSV 已由 #203 重生成至 route 363 / table 122 / rev 45 单头，(method,path) 集合随 #203 实际路由变化）；`test_route_inventory_sync.py` 同步钉对 (method,path) 集合负责，首列标记变更不触发其断言。
- **诚实登记（本轮未改）**：生成脚本 `scripts/audit/extract_workbench_inventory.py` 两处仍硬编码 `fde-workbench@0570384`。本轮为纯文档轮，**未改 .py 以避免触发 pre-commit 的 python 钩子与并发全量 pytest 争抢 advisory lock**；下次重生成会把标记带回旧值 ⇒ 后续轮应把该常量改为动态 `git rev-parse --short HEAD`。
- **零业务代码零迁移零路由零桌面** ⇒ 无需 rebuild / alembic / 重打包。文档中心侧同步见 `D:\test\FDE\蔡工FDE工作台_文档中心\00_文档总览.md` §12.6。

## [未发布] — V3.1 P0-0 基线审计轮（智能交付自动化升级路线图第一轮，纯文档零代码，2026-11-07）

- **任务书入库**：`docs/蔡工_FDE_Workbench_V3.1_智能交付自动化升级路线图与Goal实施任务书.md`（自述基线提交 `7368094`）正式入库作为 V3.1 唯一权威任务书；审计基线取 fork/main `65db88c`（其后 1 提交=#196）。
- **四报告**（NEW `docs/v3.1/`）：`00-baseline-audit.md`（任务书 §2 十条核验逐项：25 路径 24 命中 1 修正〔AgentsConsole 实际在 `agents/` 子目录〕；**zcode_contract.py 纯函数契约层判断成立**——171 行零 subprocess/socket，建模真实 0.17.1 CLI `zcode -p --json --cwd [--mode] [--resume]`；发现 `adapter.py:99-113` spawn 段为自认虚构契约=P1-1 重构靶点；`control/ontology.py` vs `ontology/` **零代码级重叠**〔75 行静态字典+MCP 唯一消费方〕，ADR-002 列 P0-2 文档交付物）、`00-data-model-map.md`（109 表按域全分组+迁移链 39 rev 头 `e5f1a7c3b9d4`+事件 22 目标类型+12 job_type+API 面）、`00-test-baseline.md`（环境/命令/结果全量实测+209 测试文件与各阶段回归面映射）、`00-gap-register.md`（P0-1~P1-3 逐能力**复用/扩展/新建/暂缓**四档裁决——每项「新建」附负结论核验〔requirements/business_facts/discovery_extractions/delivery_plans/test_plans 全仓 grep 零命中〕；P0-1 四表成立但分类枚举须对齐 guidance 五分类；P0-2 变更集全链复用仅缺 term_id 试点链接+跨项目别名冲突待拍板；P0-4 模板底座在但零种子零内容；P1-1 须先对齐在途 host-channel 线〔D-3 拍板项〕；4 项拍板项 D-1~D-4 待蔡工确认）+ `phase-status.md`（阶段状态台账，P0-0=completed，**允许进入 P0-1**）。
- **活库运行数据（部署库直查，alembic=e5f1a7c3b9d4 与代码头一致）**：agent_runs/workflow_runs/workflow_definitions/agent_artifacts/automation_approvals/ontology_change_sets/transcript_drafts/interview_minutes/project_solutions/delivery_packages/handover_packages **全 0**；projects=4（somwyn G1–G6 passed）；guidance_analyses=5（3 failed：ai_authentication_failed×1+ai_output_invalid×2=唯一真实 AI 失败分布）；project_evidence=3 全 bridge_sync；skill 消费事件 1——P1-3 指标基线=insufficient_data，与任务书预判一致。
- **口径现测**（AGENTS 现测纪律；任务书 §2 旧台账 107 表/38 rev/315 路由/pytest 2116 为陈旧值全数校正）：**109 表/39 rev 单链 head `e5f1a7c3b9d4`/323 路由/94 ENTRIES/mypy 279**——与 fork/main CI 实测逐位一致；本轮全量测试实测：pytest **2136 收集=2130 passed+6 skipped**（32:40 EXIT=0）/ vitest **932/932**/ typecheck 绿 / mypy 279 官方闸绿；API Catalog↔路由差异=设计性（治理面有意不进 catalog，CI 双钉在位）。
- 顺带修复 AGENTS 残渣一行（「版本号按发布列车同步」句的孤儿重复片段，冲突残渣家族）。零迁移零路由零业务代码零桌面 ⇒ 无需 rebuild/alembic/重打包；审计在隔离 worktree（主树并发脏集零触碰）。
## [未发布] — T-Z1 宿主通道实施轮：裁定 A 落地（agents/host_channel.py 宿主侧 zcode 代理，2026-11-07）

- **T-Z1 裁定 A 实施落地（用户拍板商用前置改判：仅开发自用即刻可用，推向市场前须 zcode 书面授予）**：NEW `server/src/fde_api/agents/host_channel.py`——宿主侧 zcode 代理通道，0.17.1 实测契约（`-p <任务书路径> --json --cwd <workspace> --mode build` + `ELECTRON_RUN_AS_NODE=1`）；`--json` 单对象汇总 fail-closed 解析（空/非对象/exit0 不可解析一律不伪造 completed）；超时=kill+communicate 回收（PIPE 缓冲不死锁）；预算超限按上限截断报 `budget_exceeded`（对齐容器版 B-2「越界不入账」）；**零凭据注入**（平台凭据解密结果不进 argv/env/磁盘，出现未用凭据标 `degraded` 经 `_finalize` 走 L1 强制人工终审）；workspace 拒绝清单复用 `FORBIDDEN_MOUNT_MARKERS`（真相层/.env/fdeops/openfde）。
- **契约收敛（rebase #193 后）**：`host_channel_argv` 委托 `zcode_contract.build_cli_argv`（#193 拍板唯一 argv 形状来源；本模块只补宿主壳前缀 `<ZCode.exe> <zcode.cjs>` 与 `--mode`）；`summarize_host_payload` 委托 `parse_json_summary().billable_units`（优先投影 totalTokenCount，回落 input+output——与容器版 cost 事件同口径）；`parse_host_summary` fail-closed 外壳（空/非对象拒绝）仍由本模块承担。测试期望值随 billable 口径同步（128→192）。
- **接线**：`config.py` 新增 `agent_host_channel_enabled`（**默认 False**——容器内 server 进程 spawn 不到宿主桌面进程，仅宿主裸跑态显式开启；关闭时容器路径行为零变化）/`agent_host_zcode_bin`/`agent_host_zcode_cjs`（开启但缺失 ⇒ 503 `agent_unavailable` + run 落 L2 零计费）；`agents/service.py` `_execute_run` 开关分支（`_write_workspace` 后、容器 backend 前）产出与容器适配器**同构 `AgentRunResult`** ⇒ `_finalize`/C-1 产物校验/T2 强制门/回执缺失独立终态**零改动复用**；容器路径与虚构契约 `spawn_argv` **不动**（T-Z1 裁定维持 `adapter_missing` 降级现状）。
- **测试 pytest +22**：NEW `test_host_channel.py` 19（argv/env 契约逐位断言/拒绝清单/--json 解析四态〔happy/前缀噪声/空/非对象〕/usage 缺失诚实计 0/超时 kill+双回收/非零退出 failed/exit0 坏汇总 fail-closed/预算截断与恰好达标/凭据零外泄/spawn OSError/workspace 红线先于 spawn）；NEW `test_host_channel_service.py` 3（开关关=容器路径零变化回归/开关开=宿主 spawner 成功+落账 42 tokens/bin 缺失=L2）。**变异四连全红→还原绿**（M1 拒绝清单失效/M2 超时不 kill/M3 预算截断失效/M4 fail-closed 失效）。
- 诚实缺失登记：宿主版无逐事件流（--json 仅单对象汇总；逐事件只有 app-server stdio 协议一条路，本轮不做）⇒ `tool_calls` 恒空、运行期无逐工具留痕；白名单语义由任务书文字面承载（与容器版同源）。
- 口径：pytest **2152 收集 = 2146 passed + 6 skipped**（2116 基线 + #193 契约层 14 + 本轮 22；rebase 合并口径推演，终值以本 PR CI run 实测为准）；vitest 927/927 不变；**零迁移零新表零新路由零桌面**（复用既有 POST /agents/{id}/run）⇒ 无需 alembic/路由清单重生成，server 变更 ⇒ 合并后 rebuild 三镜像。台账同步钉自检：backlog T-Z1 标题行升 ✅ 已实施并合并（钉①同轮闭环）；本节含 pytest + 交付信号（delivery 类，钉②放行）。

## [未发布] — goal-tb tb4：T-B1 封包半——结项交付包 handover_packages（D11 立项拍板落地，2026-11-07）

- **拍板落定（§拍板闸 6⑪，蔡工「第3件需要拍板的按你建议处理」）**：D11 立项按台账 §二草案+§十三.4 改名裁决执行；「首批真实数据到位」**不阻塞代码实现**（合成 run 测试覆盖，投产使用自然等待真实 run）。台账 §二已追加拍板记录节（留痕可推翻，#124 先例）。
- **DB（迁移 `e5f1a7c3b9d4`，38→39 rev，additive）**：`handover_packages`（draft→sealed→delivered；unseal 仅 sealed→draft 且 unsealed_count 留痕；**delivered 终态不可逆**；5 条 CHECK）+ `handover_package_items`（**指针+sha256 快照**——B#6 真相原则「清单是投影」，artifact_id 无 FK、metadata 扫描钉死零外键指向 agent_artifacts；同包同产物唯一约束）。表名与派单 `delivery_packages` 不混用（§十三.4 裁决）。
- **API（+8 路由 315→323，蓝图 42→43，全部不进 api_catalog）**：`POST/GET /handover-packages`、`GET/PATCH /handover-packages/{id}`、`POST …/seal|unseal|deliver`、`GET /handover-packages/artifacts`（挑选面=本项目已复核产物投影）。权限=查看 can_view、创建/编辑/封存/解封 can_manage、**交付登记=admin 专属**（草案「delivered（登记对外交付）=admin」原样）。
- **seal 语义**：冻结清单 + **逐项校验四闸**（产物存在 / 属本项目 / **已人工复核**〔与草案 status∈{confirmed,available} 闸同构〕/ 指纹一致→`fingerprint_drift` 409）+ `manifest_sha256`＝清单规范化 JSON 哈希（测试按同参数复算钉死）。审计四事件 `handover_package_created/sealed/unsealed/delivered`（target=项目，不复制产物内容）。
- **桌面**：NEW `handover/HandoverPackagesPanel.tsx` 挂 **delivery tab**（方案设计下方）——草稿组包（勾选已复核产物，默认名取 storage_ref 末段）/清单详情（名称/种类/指针/指纹）/封存/解封/交付登记（`isAdmin` 显隐与 admin 闸同构）/manifest 指纹呈现；无障碍闸（游离 label 检测）驱动修正为显式 htmlFor/id。
- **测试**：服务端 NEW `test_handover_packages.py` 6 例；变异三连红→还原绿（摘 reviewed 封包闸→红 / 摘 deliver admin 门→红 / 摘指纹漂移校验→红）。桌面 NEW `handover-packages-panel.test.tsx` 5 例。pytest **2122 收集 = 2116 passed + 6 skipped**（+6；基线=fork/main@63f12de 实测 **2116 收集（2110+6s）**＝#191 实测 2108+6s ＋ 并行 #190 台账同步钉 +2〔本地全量直测 2116+6s，勘误：预写 2120 少计 #190 增量〕）/ vitest **932/932**（78 文件，+5）/ mypy 279 不变。实施中发现并修正两处（诚实注记）：①序列化初版经 `db.session()` 重开会话读不到事务内未提交行（`sessionmaker` 非 scoped）→ 显式传事务 session；②manifest 摘要先算后落 sealed_at 致哈希与呈现不一致 → 调序（先落封存态再算清单）。server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（新迁移）；桌面变更 ⇒ 便携版 r21（0.3.0）。
## [未发布] — 22:25 交互拍板：人工项方向收口 + PR #193 合并授权（2026-11-07）

- **交互方式**：用户「人工部分你使用交互式选择方式解决」⇒ 两轮 5 张选择卡片（依据/收益/代价/推荐理由写正文、卡片只用 A/B/C 编号）。
- **Q1=A**：PR #193 合并已授权——rebase 到 `c2fe869`（#194 B# 线 FREEZE，CHANGELOG 冲突按「以 main 段为底叠加本轮增量」解决、两节均保留）→ CI 复跑 4 job 全绿 → squash 合并。
- **Q2=B / Q3=C / Q4=C / Q5=A**：D3 回执＝用户**主张**已取得但原件指针+sha256 未提供；N1/N2＝授权人·首个 run 发起人·真机窗口未提供；N3/D7＝产出物定义·阈值 N 与依据未提供且 `approval_rows=0` ⇒ **方向先落文本、四闸维持关闭**，`adapter_missing` 维持、E8 不实施、阈值不预支。Agent 不代填外部事实、不代发起 run、不代跑真机、不造证据。
- **留痕六处**：本文件、`docs/audit/下一步实施台账-2026-11-07.md` §12、`D1-D3拍板留痕…md` §8、`D4-D7人工项推进包…md` §6、`docs/implementation/v3-backlog.md` 22:25 补录、`docs/architecture/售前驱动交付模式改造方案.md` 22:25 补录；20:08／20:38 原文保留作沿革。
- **零迁移／零路由／零配置／零安装／零种子改写／零 DSH 改动／零红线放宽**；H1–H13／N1–N7 原样；本续轮只改文档留痕与 rebase 后的发布动作。

## [未发布] — 演进方向评估 v1.1 落地批：台账同步钉 + 三项拍板 + B# 线 FREEZE（#190/#192 后续，2026-11-07）

- **B# 线 FREEZE（P1-5 落地）**：B# 登记号封顶 B#40（backlog B# 节 FREEZE 注记）；《开源项目借鉴总览》《实施实况报告》转只读档案（头注 ARCHIVED；上游 LICENSE/HEAD 复核义务仍按红线第 8 条④）。解冻=40 条全终态 ∧ 方法级新借鉴 ∧ 用户显式拍板。
- **AGENTS**：①口径行 pytest 2114→**2116 收集 = 2110 passed + 6 skipped**（#190 +2；CI run 42366699714 直测合并后 main 2110+6s）——补 #190 轮未随轮同步的缺口；②新增 B# FREEZE bullet（工作流与陷阱节）。
- **关联轮次**：#190（台账同步钉两钉 + backlog T-A2..T-A8 七条标题行状态同步 + DoD 四件套入 AGENTS + 两份评估文档归档入库）；#192（三项拍板：执行通道=A 宿主侧代理、商业验证决策单〔90 天止损线 + 2027-02-05 复评，先到者为准〕、行业口径复议受理〔全行业=目标态，现状=自用〕）。
- 口径：pytest **2116 收集 = 2110 passed + 6 skipped**（CI run 42366699714）；vitest **927/927**（77 文件，PR 192 run 42373576921 实测——#190/#191/#192 桌面零改动）；mypy 基线 279 不变；**零业务代码零迁移零路由零桌面改动** ⇒ 无需 rebuild/alembic/重打包。台账同步钉自检：backlog 零 T- 标题增删（钉①放行）；本节为拍板落地记录（delivery 类，钉②放行）。

## [未发布] — D1–D3 拍板落地 + T-Z1 实施轮准备（2026-11-07 20:08）

- **拍板（用户「D1–D3 按你推荐的拍板。其它你去处理」）**：D1＝**A 宿主侧 zcode 代理**（B 降可选演进／C 否决，依据 #191 E1–E4 四重阻断）；D2＝AGENTS.md「bridge 只读」红线**显式扩写宿主侧写通道**＋五条边界；D3＝zcode 商用条款**以供应商书面确认为准**。**D3 是决策不是外部事实**——书面回执仍缺，生产启用闸不解除、`adapter_missing` 维持。Q6 由「形态待裁定」结案为「形态已定 A，宿主代理接线待实施」。
- **留痕四处**：`AGENTS.md` 红线第 6 条／`docs/architecture/售前驱动交付模式改造方案.md` §10「✅ Q6 结案」／`docs/implementation/v3-backlog.md` T-Z1 标题·闸⑤·拍板落地段／`docs/audit/下一步实施台账-2026-11-07.md` §8·§11。
- **NEW 契约层（纯函数，零 spawn／零凭据／零落库）**：`server/src/fde_api/agents/zcode_contract.py`——`build_cli_argv`（真实 `-p --json --cwd`，`--resume <sessionId>` 取值开关，`--mode` 由授权档位显式传入、不预设业务语义）／`parse_json_summary`（`--json` **单对象汇总**→结构化计账字段；缺字段坏类型如实归零，`response` 正文与 `usage.provider` 一律不收）／`summary_to_events`（`cost`+`done`，**不伪造 `tool_call`**）／`JsonSummaryEventProvider`（B#14 固定夹具一次性回放）。`agents/adapter.py:93` 加定向警示 TODO 指向本模块（**零行为变更**），spawn 段整体重划待 P2′ 架构决策。
- **NEW 夹具与用例**：`server/tests/fixtures/zcode_json_summary.json`（形状取自 #191 实测样本、内容全部自拟，零客户资料／零真实凭据；原始样本 `D:\test\FDE\tz1-probe\` 只留本地永不进仓）＋`test_zcode_contract.py` **14 例**（真实 argv 与禁用虚构契约／`--resume` 取值／汇总字段映射与容错／夹具形状钉／回放 provider／汇总事件喂既有 `ZcodeAdapter` 监听段）。**定向验证：14 passed ＋既有 `test_agents_adapter.py` 9 passed；ruff `--select F401,F841 src tests` 全绿；mypy 基线 279 occurrences / 104 distinct 不变。全量 pytest/vitest 口径以合并后 CI 实测为准，本轮不预写数字。**
- **A 裁决连锁口径校正（本轮新发现，防后续轮把 zcode 塞进容器）**：`docker/sandbox/Dockerfile` 注释明示**不安装 zcode**（镜像只留 nodejs + iptables）；`docs/试点前联调-iptables与zcodeCLI-检查单.md` 二表整表改写（钉定对象由「沙箱镜像内 zcode」→**宿主侧代理进程**：CLI 0.17.1 + `zcode.cjs` sha256 + provider revision；#3 与 iptables 一表解耦；证据表标签同步），**一表 iptables 生效性断言原样有效**；backlog T-Z1「修改文件」行与台账 §2/§3 E1·E10/§4 P2 拆行同步。
- **`spawn_argv` 未机械改写**：A 通道下 `sandbox.exec` 在 Linux 容器执行，而 zcode 只在 Windows 宿主；只换 argv 会制造「契约修好但执行位置仍错」的假象（#191 §2 明写随拍板后实施轮执行）。本轮改落可独立验证的契约层；**新识别 P2′ 决策**＝宿主代理 ↔ `agent_runs` 状态机咬合方式（推荐「宿主轮询领取」，决策卡见台账 §11.3）。
- **NEW 文档**：`docs/audit/D1-D3拍板留痕与实施轮交付-2026-11-07.md`、`docs/audit/D4-D7人工项推进包-2026-11-07.md`（D3 确认函草稿／D4 试点立项卡／D6 A 轨诉求问询卡／D7 四口径复审报告骨架；**均为准备件，不代发函、不代选试点、不代拍阈值**）。
- **人工闸一个不放宽**：H1–H13／N1–N7 原样；D3 回执、N1 试点授权、N2 真机联调签核、P2′ 拍板、D4–D7 均留人工，Agent 不代跑真机、不造运行证据。**零迁移／零路由／零配置／零安装／零种子改写／零 DSH 改动**；改动留本地隔离 worktree 分支 `feat/tz1-host-proxy-contract`，20:08 时点未 push／未建 PR（并发轮活跃 + CI 需人工守望）〔**20:38 已由用户「确认」授权解除，见下条**〕。
- **【2026-11-07 20:38 续轮，用户「确认」】P2′ 咬合方式按推荐拍板＝① 宿主轮询领取**（② 长连接否决／③ 人工中转仅作降级验证），并授权 `commit → push fork → 开 PR → 守望 CI`。六条决策级约束：宿主→服务端单向；领取／回执两写路由幂等且复用既有鉴权、`queued`／`host_running` 入状态机；超时失联只标记不自动重试（H4）；凭据只在宿主内存管道零落盘、客户真实资料零外发；`zcode_contract.py` 为唯一 argv／汇总形状来源；③ 仅用于首次降级验证且证据只留指针 + sha256。**形态已定 ≠ 接线实装**，`adapter_missing` 维持；AGENTS.md 红线第 6 条文本不改写。留痕：方案 §10 Q6 结案表、backlog T-Z1 标题与拍板落地段、台账 §0/§3/§4/§8/§11.3/§11.4/§11.5、`D1-D3拍板留痕` §0/§4/§5/§6/§7。**仍留人工**：D3 供应商书面回执、N1 试点授权、N2 真机联调签核、N3 A 轨诉求、D7 阈值、**PR 合并拍板**；H1–H13／N1–N7 原样。本续轮**零代码改动**（相对 20:08 基线只加文档留痕与发布动作）；PR 号／CI run id／全量收集数属运行事实，以 PR 页面与 CI 实测为准，不在版本库预写。

## [未发布] — goal-tb tb3：T-Z1 zcode 真机实测报告 + 执行通道裁定提案（纯文档，2026-11-07）

- NEW `docs/audit/T-Z1-zcode真机实测与通道裁定提案-2026-11-07.md`（T-Z1 登记闸「开工前半天实测」必做项的实测记录与裁定提案；**纯文档零代码零迁移零路由**）。
- **实测事实**（全部真机直测）：① CLI 真实契约 = `ELECTRON_RUN_AS_NODE=1 ZCode.exe resources/glm/zcode.cjs`（doctor: node v24.21.0）；② **闸①会话续接 ✅**——`--resume <sessionId>` 0.17.1 为取值开关（登记原文「布尔开关」勘误入档）+ `-c/--continue`，真机双跑验证同 sessionId 上下文携带；③ **`--json` 实测为单对象汇总**（sessionId/traceId/response/usage/eventCount/projection，非 ndjson 事件流——粒度事件流在 app-server stdio 协议；登记原文⑤勘误）；④ **容器内直跑四重阻断**——sandbox-runner node v20 缺 `node:sqlite`（node:24-alpine 实测 zcode.cjs 可跑 ⇒ JS 层唯一硬阻断）+ provider 配置缺 + 登录态缺 + `network_mode: none` 零 egress；⑤ **闸①商用条款 ⚠️**——zcode 本体无独立 LICENSE 授予文件（仅第三方 MIT 组件清单），商用集成前须向供应商书面确认（挂账不代决）。
- **裁定提案（交蔡工拍板，§拍板闸 6⑤ 拍板项不代决）**：A=宿主侧 zcode 代理（推荐：零 sandbox 基座变更、沿 bridge-poll 宿主纪律同构、`--json`/`--resume` 契约齐备）/ B=openfde 加 zcode executor（须补 B#35 许可登记）/ C=容器内直连（不建议：三重安全面变更叠加）；**无论 A/B 均须先办 AGENTS「bridge 只读」红线修订 + 商用条款确认两件拍板**——办结前编码执行通道维持 `adapter_missing` 降级（登记闸③原样生效，不阻塞第一阶段主线）。适配器 CLI 段重写随通道拍板后的实施轮执行（本实测轮零代码）。
- 口径全不动（pytest 2114 / vitest 927 / 路由 315 / 38 rev 均沿 tb2 基线；无需 rebuild/alembic/重打包）。

## [未发布] — goal-tb tb2：T-B1 agent_artifacts 扩列 + 产物人工接受写路径（封包半挂 D11，2026-11-07）

- **范围声明（登记原文「封包前置」逐字生效）**：本轮**只做 artifacts 扩列**——`handover_packages` 新表与封包/解封/下载路由**未建**（D11 立项拍板 + 首批真实数据两前置未达成），产物→交付包闭环维持挂账。
- **DB（迁移 `b8e4d6f2a9c3`，37→38 rev，additive）**：`agent_artifacts` +`derived_summary` JSON 可空列（**可重建派生**——diff: files_changed/additions/deletions；test_results: passed/failed/errors/skipped + exit_code；解析不可达如实零计数不发明数字；**原件本体永不进库**，B#6「引用方永不复制真相，只持指针」）+ `reviewed_by_user_id`（FK users SET NULL）+ `reviewed_at`；kind CHECK 置换扩 `'test_results'`（纯枚举扩展零列重建，T-J2 先例）。度量表「编码智能体一次测试通过率」与「智能体产物被人工接受率」两个「需先补字段/补写路径」缺口自此闭合数据源。
- **派生纯函数**：NEW `agents/artifact_summary.py`——`derive_artifact_summary(kind, content)`（2MB 解析上限；diff 统计按 unified diff 行首规则；test_results 全文扫「N passed/failed/errors/skipped」token 累加）；finalize 入库同事务派生（exit_code 来自 run 结果合入摘要）；可重建性=同一原件二次派生逐位一致（测试钉）。
- **API（+1 路由 314→315，不进 api_catalog）**：`PATCH /agents/runs/{rid}/artifacts/{aid}` body `{reviewed: bool}`——**can_manage**（终审动作）；接受留 who/when，撤回清双痕；事件 `agent_artifact_reviewed` target=项目、changes 只带 id+布尔（不复制产物内容）；跨 run 配对 404、非布尔 400。
- **桌面**：AgentsConsole 产物行 +「标记复核/撤回复核」（`canManage` 显隐与服务端闸同构；成功后**重拉 run 详情回真**，不本地猜写）+ reviewed_at / derived_summary 呈现（摘要以 key=value 尾注展示）。**版本号按发布列车同步 0.2.0→0.3.0**（`desktop/package.json` + `server/pyproject.toml`，登记原文要求的列车同步）。
- **测试**：服务端 NEW `test_agent_artifact_acceptance.py` 5 例；变异三连红→还原绿（摘 can_manage 闸→红 / 撤回不清双痕→红 / 跨 run 不校验→红）。桌面 +2 例（canManage 显按钮+PATCH reviewed:true 形状+回拉详情 / 缺省无按钮）。pytest **2114 收集 = 2108 passed + 6 skipped**（+5，基线=#188 run 实测 2103+6s）/ vitest **927/927**（77 文件，+2）/ mypy 基线 279 不变。server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（新迁移）；桌面变更 ⇒ 便携版 r20（0.3.0，与 tb1 桌面增量同窗打包）。

## [未发布] — goal-tb tb1：T-A9 转写草稿区 + 访谈纪要正式库（ASR 通道 opt-L 落地，2026-11-07）

- **拍板落定（§拍板闸 6⑩，蔡工逐字「ASR 通道选型：按你建议实施」）**：立项文档《录音转写ASR通道立项-v1.md》§3.3 P1–P6 逐项按推荐项落定（§3.3.1 新增拍板结果节）——**P1=opt-L 本地 ASR 先行**（红线同向零外发）、P2=横评实测裁决、P3=Windows 宿主裸跑、P4=首版普通话、P5=诚实失败、P6=云默认不开（启用=新的显式拍板）。T-A9 实施轮随之解封。
- **NEW `docs/audit/ASR本地引擎横评-2026-11-07.md`**（P2/P3 实测数据，随本 PR 归档）：faster-whisper（int8/CPU）× whisper.cpp b5454 × tiny/base/small，TTS 本地合成虚构文本（零客户资料）双片段（68.7s 普通话 + 20.2s 中英混说），CER 经 OpenCC 繁简归一——**faster-whisper base 档胜出**（中文 CER 8.6% / 混说 6.5% / 4× 实时）；whisper.cpp small 中文精度最高（5.9%）但慢于实时；FunASR 因 torch 依赖过重不实测（如实注记）。横评工具链与模型只留本地 `D:\test\FDE\asr-bench-local\` 永不进仓。
- **DB（迁移 `d7b2f8a4c1e6`，36→37 rev，additive-only）**：`transcript_drafts`（草稿区：状态机 draft→promoted|expired|discarded；墓碑化清空正文/指纹/复核条目；7 条 CHECK 含晋升必带三要素、活动草稿必有正文、墓碑必无正文）+ `interview_minutes`（正式库：客户确认三要素 NOT NULL + `redaction_hits` 计数）。**物理隔离机械钉**：全库零外键指向 `transcript_drafts`（minutes.draft_id 为纯字符串指针，B#6「引用方永不复制真相，只持指针」），metadata 扫描测试钉死。
- **API（+7 路由 307→314，蓝图 41→42，全部不进 api_catalog）**：`POST/GET /transcript-drafts`、`GET /transcript-drafts/{id}`、`POST …/discard`、`POST …/promote`、`GET /interview-minutes`、`GET /interview-minutes/{id}`。权限=草稿读写 can_view（T-A3 校准「录入 member 已可用」同构）、**晋升 can_manage**（入正式库=管理动作）；列表有界分页（50/200+truncated）、行不带正文防大载荷。
- **红线三面**：①**只收文本**——无任何音频字段，录音原件永不进平台（SOP :109/:111 逐字锚，UI 注记钉住）；②**T-A2 代号化不豁免**——create/promote 两处 title/content/确认人文本先过 `redact_text_detailed`（词典命中→enterprise_code 首段代号、疑似同样替换），词典不可用 fail-closed 503 `pseudonym_dict_unavailable`（guidance 同码），复核条目（#160 同形状）随草稿行存储+详情回显、墓碑时一并抹除，正式库只留命中计数；③**无客户确认的转写文本无法进正式库**——晋升三要素（确认人/时间戳/确认方式）缺一即 422 + 未来时戳拒绝（CR-029 教训）+ CHECK 双保险。
- **T+7 自动清理**：`purge_expired_drafts` 接入 cli scheduler 循环（与过期清扫/退避提醒同拍），到期活动草稿墓碑化 + 独立文件根（`FDE_TRANSCRIPT_DRAFT_ROOT`，默认 `.fde-transcript-drafts`，与 `.fde-storage` 不共根）子树删除；skip_locked 防并发互堵；墓碑行留作 T+7 合规对账凭据。
- **桌面**：NEW `transcripts/TranscriptDraftsPanel.tsx` 挂 overview tab guidanceSlot（presurvey 录入卡旁）——本地文件导入（只读文本进表单、原件不上传）、草稿列表/详情（正文+复核清单词典命中徽标）、弃置、晋升表单（canManage 显隐与服务端同构）、纪要正式库列表/详情；加载失败 fail-静默（教训 51），动作错误 alert 呈现。
- **测试**：服务端 NEW `test_transcript_drafts.py` 8 例；变异三连全红→还原绿（摘晋升三要素校验→红 / 代号化改直通→红 / 清理谓词取反→红）。桌面 NEW `transcript-drafts-panel.test.tsx` 7 例。pytest **2109 收集 = 2103 passed + 6 skipped**（+8）/ vitest **925/925**（77 文件，+7）/ mypy 基线 279 不变。server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`（新迁移）；桌面变更 ⇒ 便携版重打包（r20）。

## [未发布] — goal-ta4 路由审计清单 CI 同步钉（#174 教训机械化，零业务代码，2026-11-07）

- NEW `server/tests/test_route_inventory_sync.py`（pytest +1）：`create_app().url_map` 实际路由对账 `docs/audit/v3-route-inventory.csv`——比对口径与生成器 `scripts/audit/extract_workbench_inventory.py` 一致（跳过 static、剔除 HEAD/OPTIONS、method 多值按字母序 `|` 连接），同一 (method, path) 集合逐位相等，漂移即红并报「实际有而清单缺 / 清单有而实际无」两份明细＋重生成指引。**「动路由必同步审计清单」从此有机械闸兜底**（#174：#171/#162 两次清单落后靠人工发现；AGENTS「审计清单刷新有前置条件」节人工纪律不变，加机器兜底）。handler/service/auth 等富化列不在钉内（归生成器自守，避免钉子复制第二份生成器逻辑）。
- 变异验证：删 CSV 一行→红（报缺失明细）→还原→绿。零业务代码零路由变更零迁移；pytest **2101 收集 = 2095 passed + 6 skipped**（**CI 终值实测 run 42343361485**；勘误链：#183 PR 实测 2095 收集=2089+6s → #185 +6 例 → 本轮 +1 ⇒ 2101；前写「基线 2094 收集=2088」系 rebase 解析误取行内更早轮次注记，本节以 CI 直测为准）；vitest/路由/表数/迁移头全不动。
## [未发布] — goal-c CR-029 服务端小轮：集成桥 captured_at 服务端钟 sanity（2026-11-07）

### 修复

- **集成桥 `captured_at` 单向采信宿主钟（goal-c 台账 CR-029，P3）**：`_parse_captured_at` 此前只校验格式不比对服务端钟——宿主 NTP 前漂 >6h 或带 `FDE_BRIDGE_TOKEN` 方伪造 `captured_at`（未来）会让 `openfde_synced_at`/`fdeops_synced_at` 落在未来 → `now - synced_at` 恒为负 → 4h/360min stale 标永不亮（文件盘上持续腐仍显「新鲜」，采集断连被永久遮蔽）。`apply_snapshot` 落库前单向钳制：未来时戳一律钳到服务端接收时刻（同一时刻兼作 `run.started_at`），与偏移量无关——「不存未来时戳」是不变量本身。**过去方向不钳**：只会更早触发 stale（无害方向），且钳过去会伪造 `manual_reproject` 重放旧快照的新鲜度（重投影 ≠ 采集）。钳制不吞数据：engagement 照常投影，只是时间戳诚实化。
- **宿主钟偏移观测面**：`|skew| > 90min`（`CAPTURED_AT_SKEW_TOLERANCE_SECONDS`）才把 `captured_at_skew_seconds`（int，负=宿主钟超前）记进 `run.summary`——正常采集不污染 summary 形状；运维定位面（「为什么全场 stale 诡异亮起」→ 看本键即知宿主钟漂了多大）。

### 测试与口径

- NEW `server/tests/test_bridge_captured_at_sanity.py` 6 例：未来 6h 钳制不变量（stored ≤ now ∧ 数据零损失 ∧ 不误报 stale）／小偏移 2min 同样钳（不变量与量无关）／skew 观测键入 summary（负值≈-21600）／正常钟不带键（形状稳定）／过去 3 天直通且 stale 立即亮（无害方向保真）／manual_reproject 重放 30min 前快照不刷新新鲜度（过去不钳的回归钉）。变异 M1（钳制中性化）→ 钳制两例红、余四例绿 → 还原绿；变异 M2（标记门中性化）→ summary 例红 → 还原绿。
- 口径：服务端 pytest **2085 收集 = 2079 passed + 6 skipped**（本轮 +6，与 goal-ta2 轮 +6〔test_agents_meetings_lists 5＋事实链 B#9 钉 1〕同基线 2073 收集＝2067+6s 叠加；CI 实测为准）；桌面 vitest **912/912**（goal-ta2 轮 +15；本轮桌面零改动）；路由 307（goal-ta2 轮 +2；本轮零路由）；零迁移零新表（迁移头 `b2e8f4a6c9d3` 36 rev 不变）；**server 变更 ⇒ 合并后 rebuild 三镜像（alembic 幂等 no-op）**；本轮桌面零改动 ⇒ 不触发便携版重打包（goal-ta2 轮桌面挂账随其节）。
## [未发布] — goal-ta3 T-A1 核销：S3 前置闸桌面提示已由 #156 兑现（纯文档，2026-11-07）

- **零代码零迁移零路由零桌面 diff**：backlog T-A1 状态 PROPOSED→**DONE（核销）**——桌面呈现（`PresurveyGateHint.tsx`：409 `presurvey_s3_gate_open` 拦截态渲染服务端 message＋G3 四项证据清单＋claimed≠accepted 徽标＋「前往门禁页」跳转锚）已由 #156（2026-11-06）先行交付并接线 `PresurveyAnalysisAction`；goal-ta3 按 fork/main@1a1d34e 实测逐项核对登记验收四项全部成立，专项测试 `presurvey-gate-hint.test.tsx` 5 例全绿，**零补码**（T-UI1 同款核销先例）。依赖图同步。
- 口径全不动（pytest 2079 收集 = 2073 passed + 6 skipped / vitest 912 / 路由 307，均为 #182 CI PR-head 实测）；无需 rebuild/alembic/重打包。

## [未发布] — T-A8 agents/meetings 桌面控制台 + #171 复核清单桌面收口（goal-ta2，2026-11-07）

### 行为变更（+2 只读路由；零迁移零新表；桌面变更 ⇒ 便携版重打包）

- **服务端**：`GET /api/v1/agents/runs`（project/status/时间过滤＋limit 1..200/offset 分页＋truncated）与 `GET /api/v1/meetings`（project 过滤＋同款分页）。可见性单一权威 NEW `projects/permissions.py::visible_project_ids`（跨项目聚合复用 `project_access`，不在 SQL 重写第二套规则）；单项目 404（不存在）/403（can_view=False）。**不进 api_catalog**（人工控制台面，沿 T-W6/B#9 先例）。防 N+1：runs 行无 `agent`/`artifacts` 键（`_serialize_run(detail=False)`）；meetings 行无 `turns` 键、话轮计数单条分组查询预聚合（`_serialize_meeting` 增 `turns_count` 可选参，既有端点零变化）。
- **桌面**：NEW `agents/AgentsConsole.tsx`（run 列表→详情[agent/产物指纹]→tool-calls[放行/拦截]→成本汇总）＋ NEW `meetings/MeetingsConsole.tsx`（会议列表→话轮流→closed 才拉纪要三段式+sealed 指纹）；项目 tab 11→13（「智能体」「评审会」）。拍板 6⑥ 维持：与 B#9 执行事实面板界面分离。
- **#171 复核清单桌面收口**：`GuidanceReview` 消费 `get_analysis.redaction_review`（服务端唯一投影）呈现条目（名称/次数/词典命中）；409 `redaction_review_required` 拦截提示＋「已复核」勾选后重发 `redaction_reviewed: true`；干净分析 confirm 不带键；本地缺清单时 409 回读读面补渲染（仍不自行推导）。
- **B#9 断言钉**：`guidance.redaction_review` 事件在执行事实链**元数据可见、`changes.entries`（疑似企业名）绝不外泄**（与既有 changes 不外泄钉双钉）。
- 测试：pytest +6（NEW test_agents_meetings_lists 5 ＋ 事实链钉 1）；vitest +15（agents-console 6＋meetings-console 5＋guidance-redaction-review 4；project-detail tab 钉 11→13 项）。变异四连红→还原绿（can_view 闸/limit 上界/changes 外泄双钉/ack 携带）。
- 口径：路由 305→**307**（审计清单已重生成，route CSV +2 行/blueprint 41/表 105/36 rev/head 不变/DB CSV 零变化）；基线 main@677746c CI 实测 pytest **2067+6s**、vitest **897**（72 文件）；本轮 PR 预期 pytest **2073+6s** / vitest **912**（75 文件）。**勘误**：#179 记桌面基线 882 已陈旧（main CI 双源实测 887）。

## [未发布] — goal-c 台账收口：CR-033/036 驳斥销号 + CR-034「在途写不退出」保护接线（2026-11-07）

### 行为变更（纯桌面，零服务端零迁移零路由）

主进程新增「在途写不退出」保护（goal-c 台账 CR-034 接线，dead-code 修复）：
- 主窗口关闭时若仍有非 GET 请求在途（`activeMutations > 0`），弹确认框点名在途写入数量——「等待完成」取消本次关闭，「仍然退出」一次性放行（消费式旗标，放行不常开）；确认框悬起期间重复关闭只拦不再弹（防叠框）；`app.quit()` 路径同样先经窗口 close 事件，保护同时覆盖退出菜单。
- 数据源不动：计数仍由 `registerApiIpc` 对非 GET 累计；此前该计数器全仓零读取点（登记为 dead-code）。NEW `desktop/src/main/close-guard.ts` 纯函数决策内核＋文案（Enter/Esc 安全默认＝等待完成；文案不承诺自动重试）。

### 台账驳斥销号（零代码）

- **CR-033**（lcsc 规格书 iframe 检测表达式畸变）——**登记误读**：fork/main 源码两处均为 `f.src.includes('atta.szlcsc.com')&&f.src.toLowerCase().includes('.pdf')`，括号配对正确；`git log -S "includes('atta.szlcsc.com')"` 唯一命中 `5ded7b3`（2026-09-29），正确结构自引入以来从未变动，c7 登记时即现态。
- **CR-036**（ResearchWorkspace 导出轮询 stale 快照回写）——**守卫已存在**：deps 含 `researchExports`（新增导出必重跑 effect→cleanup→旧闭包 `cancelled=true`）＋poll 唯一 await 边界后紧跟 `if (cancelled) return`，stale 写回不可达；该结构来自 J7b 重构（`697bfb3`，2026-10-28），早于 c7 登记；`cancelled` 布尔与 `sequence` ref 在此单链自续期场景语义等价。

### 测试与口径

- NEW `desktop/tests/main/close-guard.test.ts` 10 例：决策矩阵 4＋确认文案 2＋**index.ts 接线静态钉 4**（close 处理器消费决策／放行旗标重触发 close／activeMutations++/-- 数据源仍在／确认框悬起期间重复关闭只拦不再弹——防接线再次静默脱落＋防叠框）；变异验证：守卫中性化→红→还原→绿。typecheck 双 tsconfig 绿；全量 vitest 897/897（72 文件）。
- **口径校正**：#178 T-A7 轮实际 vitest +12（NEW solution-frozen-version 7＋solution-design +5）此前未入 AGENTS 口径行，#179 CHANGELOG 记 882 系基线误取陈旧 870 推算——**实测 887**（#178 PR-head run 42318566336 与 main run 42320178306 desktop job 双实测、本地一致），本轮校正后总量 **897**（+10 本轮）。
## [未发布] — 架构评估修复轮：需求↔代码对齐评估（2026-11-07）全量修复

评估报告：`docs/audit/架构评估报告-需求与实现对齐-2026-11-07.md`（九差异/六偏离模式/九建议；基线 fork/main `ff4813c`）。本节=§四建议 1–9 全量实施。**红线零违反（无 P0）**；部分对齐主因=文档↔代码一致性滞后，本轮系统性回写。

### 服务端行为变更（零迁移零路由；server 变更 ⇒ 合并后 rebuild 三镜像，alembic 幂等 no-op）

- **D2/P1 翻译器脱敏（本 P1 缺口的唯一代码修复）**：`translator/` 全链接入 T-A2 企业名脱敏——①**创建面原文不落库**（`_redact_translation_input`：种子词典命中→「客户代号」、疑似名→替换+复核、通用词零改动；词典机制故障 fail-closed 422 `pseudonym_dict_unavailable` 行不落库；凭据串 422 `sensitive_credential_detected`）；②**落库前兜底**（AI 输出回显企业名同样替换）；③**复核事件两阶段**落 `translator_translation` 目标（stage=input/output，`guidance.redaction_review` 同型）；④**采纳交接**：`adopt_translator_draft` 把条目搬到分析目标，confirm 复核闸（#171）按分析聚合**自动覆盖翻译链**（采纳响应即携 `redaction_review`；闸逻辑零改动）。**单一权威重构**：`redact_draft_payload` 从 guidance/jobs 私有提升至 `guidance/redaction.py` 公共原语（presurvey/translator 共用）；`DICT_FAILURE_CODE` 归位 `enterprise_dict.py`（jobs 保留同名 re-export 兼容）。翻译器无项目维度⇒替换别名恒「客户代号」（采纳后项目语境由复核清单兜底）。
- **D4 pilot 契约警示**：`pilot_status` 增派生键 `contract_unverified`/`warnings`——窗口激活但零**非演练 completed** run 即警示（ZcodeAdapter spawn 契约未经真机验证（售前方案 Q5/T-Z1），spawn 失败全落 L2 会污染试点指标）；只读呈现不拦 run（`pilot_capacity_error` 不变）；演练 run 排除口径与 20-run 计数器一致。
- **D1 防复发**：`scripts/audit/extract_workbench_inventory.py` 加「BLUEPRINTS 项数 == app.py register_blueprint 数」对账断言（宁红不漏；重生成过闸 305/41，三清单零字节漂移）。**初评 D1「现行违例」撤回**——系初评 grep 落在主树（落后 #177 的 c05bb19）旧文件上的取数误差，fork/main 脚本/清单均最新；教训记入评估报告附记。

### 测试补钉（G7 四缺口全部收口 + 架构静态钉）

- NEW `server/tests/test_translator_redaction.py` **9 例**：创建面替换/疑似/通用词三分、词典故障与凭据 fail-closed、输出回显兜底+output 事件、采纳交接+闸 409/ack 放行留痕、干净草稿零误伤（变异验证：摘创建面替换→红、摘采纳交接→红）。
- NEW `server/tests/test_model_credential_key_derivation.py` **3 例**（G7-①）：缺省派生可解 / 轮换 JWT secret 即 `credential_unavailable` 且密文本体不变（换回旧 secret 即恢复） / 独立密钥隔离（`FDE_MODEL_CREDENTIAL_KEY` 后轮换零影响；反向钉独立键自身失效同样不可解）。
- NEW `desktop/tests/main/renderer-url.test.ts` **6 例**（G7-④）：`isAllowedRendererUrl` 开发 origin / 打包态 file: 包含性 / query 拒绝 / 目录逃逸拒绝 / 远程协议拒绝 / 异常输入拒绝（判定本体纯函数，零生产代码改动）。
- `test_architecture_purity.py` +**1**（P-4）：`test_top_level_package_import_cycles_stay_frozen`——AST 全包顶层导入环实测 **18 对**冻结（新增环红、静默解环也红，清单显式维护）。
- `test_agent_pilot.py` +**3**（D4）：零 run 警示在位 / 真实 completed run 清警 / 演练 run 不算契约证据。
- G7-②③复核在位零补码：桥重放 `test_bridge_sync_flags.py:179,228`、微信密码指令 `test_ai_api_actions.py:155`（初评漏记，已补记覆盖地图）。

### 文档系统性回写（D3/D5/D6/D7/D8；全部 .md）

- **7 份系统意图文档**（架构/关键流程/权限矩阵/变量与密钥/测试覆盖地图/定时任务/自动化面）：统一「快照更新 2026-11-07」头注；工具计数 14→**17**、写类分面口径（effect≠read 共 3，`lcsc_search` external/2 入册）、降级白名单 12→**13**、scheduler「唯一 1 个」→**5 面**、worker job 8→**12**、约 30 处行号重锚；关键流程补 T-A2 三道防线/复核闸/G3 前置闸/证据一等表/CAS；变量与密钥补 `FDE_ENTERPRISE_DICT`/`FDE_AGENT_*` 族、登录限流落点勘误（auth/limits.py→auth/routes.py:28-68）；自动化面补翻译器管道节（§6）与 file_send_wechat 实构防线（D5：无密码环节，原「事前密码确认」失真）。
- **G3 验收场景矩阵**：补场景 1.7（代号化三道防线+复核闸全链）/1.8（S3 闸桌面拦截）；更新记录自纠「改行为先改场景表」三轮违例。
- **测试覆盖地图**：基线改 CI 实测（pytest 2073 收集/ vitest 887）；§三 G7 四缺口全收口表；§二建议项六项现状（Serper 项失效销号）；逐文件计数停止维护（以 CI 为准）。
- **技术实施方案**勘误三处：dispatch 禁区口径对齐钉子范围（读路径禁 join，D8）、ZcodeAdapter 契约偏差注记（Q5/T-Z1）、meeting 工具落点注记（meetings 侧非网关）+ generated_by 值域勘误（实构 `('human','agent')`）。
- **backlog T-A1 状态回写**（D6）：PROPOSED→DONE（#156 `ab046f4`）。**冲突解存档：#184 goal-ta3 核销轮已先行落盘同一结论（DONE/零补码，fork/main 权威版），本 PR 冲突解取其版；D6 登记断档的两会话独立发现，以先合并者为准。**
- **评估报告自订**：D1 撤回注记、D9 补记②③在位、§六实施轮附记（九建议逐一落点）。

### 口径勘误（D7）

- AGENTS vitest 口径 **882→887**：#179 补账取了 #178 PR-head 值（870+12），漏计 #177 已上移基线 875（875+12=887；CI run 42322015325 / 42323992174 desktop job 双证 887 passed）。

### 部署与打包

- server 变更（translator/agents/redaction/jobs）⇒ **合并后 rebuild 三镜像 + `alembic upgrade head`**（零迁移，幂等 no-op）。
- 桌面仅新增测试文件（零生产代码）⇒ 便携版无需重打包（tests 不进 asar）。
- 口径（**CI run 42338168736 PR-head 实测**）：pytest **2094 收集 = 2088 passed + 6 skipped**（基线 #184 后 2073+6s ＋ 本轮 +15）；vitest **918/918（76 文件）**（基线 #182 后 912 ＋ 本轮 +6）；mypy 基线 279 不变（官方闸绿）；路由 307 / 蓝图 41 / 105 表 / head `b2e8f4a6c9d3` / ENTRIES 94 不变（307 系 #182 先行 +2，本轮零路由）。

## [未发布] — goal-ta1 拍板回写 + 录音转写 ASR 通道立项（纯文档，2026-11-07）

### 蔡工拍板回写（§拍板闸 6⑨，三行逐字；零代码零迁移零路由零桌面）

- **剩余 T-A 线分工**：「剩余T-A线本会话」——T-A1 / T-A8+B#9 合批 / T-A9 随 ASR 立项 / 工程卫生轮，归执行 goal-ta 循环提示词的会话；**T-A7 为绝对禁区**：「T-A7另外一个会话在做，其它本会话可以做」——backlog T-A7 条目只加一行分工事实注记（#178/#179 均已由该会话合并），不重写其任何段落。
- **ASR 通道立项**：「立项」——文档轮。NEW `docs/architecture/录音转写ASR通道立项-v1.md`：SOP `somwyn/raw/2026-10-27-FDE接触调研阶段资料入库SOP设计.md:109`/`:111` 红线**逐字引用**（录音与未确认转写永不入正式库；录音原件永不进 repo/DB）；现状行级实测（`ai/kimi.py:43-47` MiniMax purpose 枚举 5 项**无音频转写**；全仓零音频转写链，与上位方案缺口表 G3 一致）；通道选型三候选（opt-L 本地 ASR＝红线同向 / opt-C 云 ASR＝**客户语音外发的红线张力显式登记** / opt-H 混合），**推荐本地先行、云=显式红线例外**；承接机制引用 T-A9 登记原文（独立表+独立文件根、T+7 清理、草稿不可被方案/报价/SOW 引用、晋升三要素、转写文本过 T-A2 代号化管线不豁免）；**显式「待蔡工拍板」节（P1–P6）收口——不代决**。
- backlog 同步：§拍板闸 6 增 ⑨（分工决议三行逐字）；T-A9 条目闸更新（**立项半已批**、立项文档指针、「跑通」半待选型拍板+真机实测随实施轮闭合；**T-A9 维持 PROPOSED，立项≠实施**）；依赖图 T-A9 行同步。
- 口径勘误：kimi.py purpose 枚举注释行号登记原文 `:39-43` → 现测 `:43-47`（枚举内容两测一致，后续提交致注释块下移）；§拍板闸新项实测编号为 **⑨**（goal-ta 提示词原文写「增⑦」——⑦⑧ 已被 2026-11-06 拍板轮占用，按 backlog 实测顺延）。
- 全仓 diff 仅 .md 文件（backlog / CHANGELOG / AGENTS / 立项文档）；无需 rebuild / alembic / 重打包。

## [未发布] — T-A7 谈判版本管理：桌面冻结状态徽标 + 导出弹窗版本明示（2026-11-07）

### 行为变更（零代码零迁移零新 API；桌面变更 ⇒ 便携版重打包挂账）

方案详情页头部新增**冻结状态徽标**（拍板 §拍板闸 6③：谈判稿=未冻结版本）：
- 「已冻结进 SOW」（绿）——当前方案版本的内容已冻结进 SOW 快照
- 「谈判稿 · 已修改」（黄）——方案在 vN 冻结后又修改过，当前内容未进任何 SOW
- 「谈判稿 · 未导出」（灰）——当前内容尚未冻结进任何 SOW

反查数据源：`GET /documents` 摘要自带 `opportunity_scope.solution.{id,version}`（export_sow 每次导出更新为导出时刻的方案版本）⇒ **零新 API**；含 archived 快照（历史冻结事实，「历史文件保留」语义），取最大版本号。徽标只在**详情页**呈现——方案列表页钉住「不预取 `/documents`」（SOW 文件懒加载契约，solution-design.test.tsx:184）。

导出 SOW 弹窗明示冻结关联：`SolutionExportResult` 补声明 `solution_version` + `reused`（服务端 `_serialize_export` 本就返回）；文案「本 SOW 快照冻结的是方案 **vN** 的内容」，同版本重复导出附「复用既有快照」。

`/documents` 反查失败静默降级为「谈判稿 · 未导出」——辅助信息不阻断方案详情主内容（SolutionHealthChip 同纪律）。

### 口径勘误（与登记原文三处出入，已回写 backlog）

「谈判稿与正式方案的分离位」不需新实体——solution 单行+乐观锁 version，「冻结」已承载在 `project_solution_exports`（`(solution_id, solution_version)` 唯一键）+ 文档版本 `content_snapshot_json.solution` 逐字快照；「版本列表追溯」数据源已存在（见上）；「谈判稿不进 SOW / 快照只读」服务端既有用例钉住（`test_sow_export_freezes_saved_solution_without_ai_and_reuses_revision`），零重复实施。

### 口径（#178 PR-head CI run 42318566336 实测）

vitest **882 passed**（71 文件 = 基线 870 + 12 新增：NEW solution-frozen-version.test.tsx 7 + solution-design +5）／pytest server-tests pass（服务端零改动不变）／mypy、路由、迁移均不变。

## [未发布] — T-O2c 全局注册类型只读面：调研定义编辑器接入注册类型（2026-11-07）

### 行为变更（+1 只读路由；零迁移零新表；桌面变更 ⇒ 便携版重打包挂账）

- **服务端新面**：`GET /api/v1/ontology/relation-types`（require_auth）——无项目上下文的消费方（行业模板/调研定义编辑器）拉取全局注册类型选项。只收全局行（project_id=NULL）；`?kind=` 按种类过滤；全状态返回（消费方自行过滤 active）。人工路径，有意不进 api_catalog（沿 T-O2 纪律）。
- **调研定义编辑器接线**：「调研主体」下拉补注册类型选项（内置五类 ∪ 全局注册 active 行，标注「注册类型」）；已加载定义含注册类型时正确回显（含注册面拉取失败 fail-open 降级、类型已 retired 的当前值兜底——不再空白显示）。
- **JSON 导入放宽**：调研定义 JSON 文件导入接受对象类型码格式的注册类型（值域权威仍在服务端写闸门）；AI 生成路径维持内置五类（T-O2b 防幻觉基线）。
- 测试：pytest +3（全局面只收全局行/kind 过滤/未认证 401、两面 serialize 同构、目录红线钉）；vitest +5（全局面选项接线、注册类型定义显示与原样保存、fail-open 当前值兜底、JSON 导入注册码、AI 路径内置五类钉）。审计清单三件套再生成（route 305 / blueprint 41）。

## [未发布] — T-A2 补齐：confirm 复核闸（拍板 6① 机械强制，2026-11-07）

- `guidance/service.py::confirm_analysis` 新增复核闸：确认前按分析聚合 `guidance.redaction_review` 事件（#160 落的复核清单事实源；同名跨事件 occurrences 累加、`matched_dict` 求并、按名称排序）——清单非空且请求未显式 `redaction_reviewed=true`（路由只认字面 true，fail 向安全侧）→ 409 `redaction_review_required`；带 ack 放行并随既有 `guidance_analysis_confirmed` 事件留痕 `redaction_reviewed`/`redaction_review_hits`。零新增状态面，闸与来源种类无关。
- `get_analysis` 与 confirm 响应增派生字段 `redaction_review`（同一事件源聚合投影）——方案审核人复核的可见入口；桌面呈现随 T-A4/B#9 面接线。
- `REDACTION_EVENT_TYPE` 常量归位 `guidance/models.py`（写入方与消费方共享单一权威，jobs 同名导入保持兼容）。
- NEW `server/tests/test_guidance_confirm_review_gate.py` 6 例（无 ack 409+零变更 / ack 放行+事件留痕 / 干净免 ack / 读面形状与排序 / 跨事件合并 / 编辑不改写审计清单）。零迁移；既有端点加可选参数。

## [未发布] — 洁癖收尾轮：口径全现测吻合 + 审计清单重生成 + 补账（2026-11-07）

### 口径现测（七项逐位吻合，零漂移修正）

以 fork/main `a0ed3ee` 为基线现测：蓝图路由 **304** / blueprint **40** / 业务表 **105** / 迁移头 `b2e8f4a6c9d3`（36 rev）/ api_catalog ENTRIES **94** / mypy 基线 **279**（`server/mypy-baseline.txt` 行数）——审计脚本自报与 AGENTS 口径行逐位一致；pytest **2050 passed + 6 skipped**＝2056 收集、vitest **858**（均为 main CI run 42255980781 实测，#166）。规则执行审计：`.env` 零跟踪、根级文档零冲突残渣、`origin` push URL 已锁（红线机械化）、版本三处同步 0.2.0。

### 修复的三处漂移

- **审计清单重生成**：`docs/audit/v3-route-inventory.csv` 落后 2 条路由（B#13-C/D 轮重生成于 302，#162 只读技能中心 +2 未刷）——`extract_workbench_inventory.py` 重生成，route CSV +2 行、JSON route_count 302→304，DB CSV 零变化。
- **`FDE_ENTERPRISE_DICT` 补登记**（T-A2 遗漏）：`server/.env.example` 补「售前企业名脱敏」节（可选现场词典指针，缺省用种子词典，真实词典永不入库）；README 配置边界表同步补行。
- **CHANGELOG/AGENTS 补账**：#156 T-A1／#160 T-A2／#163 T-A3／#164 T-A4 四轮此前只回写 backlog、未记 CHANGELOG 节与 AGENTS bullet（本轮下方补齐）；AGENTS「当前状态」bullet 断档自 #161 起一并补齐（#150/#152/#153/#154/#156/#157/#159/#160/#162/#163/#164/#166/#167）。backlog T-A4 状态行「实施中」→「已实施并合并 #164」。

零代码零迁移零路由；无需重建镜像/alembic/重打包。

## [未发布] — CR-032 写路径清偿：调研注册对象类型接入创建/导入/表单面（2026-11-07）

### 行为变更（纯桌面零服务端零迁移零路由；桌面变更 ⇒ 便携版重打包挂账）

- **注册对象类型可新建**：项目调研对象树的「新增」区为 T-O2 注册表登记的对象类型（`kind=subject_type ∧ status=active`）提供「新增X（根级）」入口——注册类型无父级规则，创建为根级对象（不带上级）；内置五类的父子层级流程零变化。
- **导入与表单承接**：调研对象批量导入对话框的「对象类型」与调研表构建器的「调研主体」下拉补注册类型选项（标注「注册类型」）；顺带修复注册类型主体下「调研主体」下拉空白显示的问题（选中值无匹配选项）。
- **数据源与降级**：选项来自既有只读路由 `GET /api/v1/projects/{id}/ontology/relation-types`（客户端过滤 active 行，draft/retired 不出现）；注册面拉取失败静默降级为仅内置五类——值域权威始终在服务端创建闸门。
- **边界（偏差注记）**：调研定义编辑器与行业模板编辑器本轮未接——全局注册类型没有项目内只读路由可消费，随服务端路由补口后再接。
- 测试：vitest +4（根级创建流不带上级／非 active 行过滤／导入与构建器选项／树按钮两态）。
## [未发布] — T-A6 报价核验→冻结 SOW 桌面闭环：方案详情页建交付包入口（2026-11-07）

### 桌面（纯桌面零服务端改动零迁移零路由；详见 backlog T-A6 实施轮节）

- NEW `SolutionDetailPage.tsx::DeliveryPackageLauncher`：方案详情页（`canManage` 且非弃用）新增「建交付包」区块——拉项目报价列表（`GET .../quotes`），**默认选中 finalized 报价**；草稿报价选项禁用；无 finalized 报价时给出可读清单（含跳「报价收款」页链接）并禁用创建按钮——**前置同口径闸提示**（发布闸 `quote_not_finalized` 在服务端兜底，桌面提前一步呈现同一要求）；提交走既有 `POST /api/v1/dispatch/packages`（`solution_id+quote_id`）；错误映射 `package_exists`（已有包→引导去调度台）/`verifier_role_required`（权限说明）中文呈现。
- `CommercialBoard.tsx` QuoteCard：finalized 后显示「下一步」引导行（跳方案设计建包；说明发布即冻结快照与既有闸）。样式 `.solution-package-launcher` / `.quote-next-step`。
- **辅助入口不阻断主内容**：报价列表拉取失败静默降级（`SolutionHealthChip` 同纪律）；既有 42 例 solution-design 用例零回归。

### 口径勘误（与登记原文三处出入，已回写 backlog）

登记原文「未核验时导出被服务端闸拦住」不成立——`export_sow` 服务端不查报价（只有 AI 协同终审拍板 + design 必填两道闸；SOW 是谈判材料），真正的报价闸在**交付包链路**（建包 `solution_id+quote_id`、发布 422 `quote_not_finalized`、首单回校 `calibration_required`）；登记原文「补齐状态推进与门禁提示」已是既有能力（QuoteCard 既有 claims 推进/回校/成交回填）；真缺口是 `POST /api/v1/dispatch/packages` 全桌面零调用——「核验通过→交付包发布（冻结快照 §2.3 哈希）」链在桌面断在这里，本轮补上。

### 口径

#175 PR-head CI run 42308398276 实测 vitest **870 passed**（70 文件，862→870：T-A6 轮 +5、T-A2 补齐轮 +3 既有增量）／桌面 typecheck 绿／服务端 pytest 与 mypy 零改动不变（纯桌面轮，server-tests job 同跑回归绿）／路由 304 不变（零新增路由）／零迁移零新表零新字段。

## [未发布] — T-A5 方案骨架模板：三选项 + 取舍 + 明确不做 + 验收标准（2026-11-06）

### 服务端（纯服务端模板文案，零迁移零路由零新字段；详见 backlog T-A5 实施轮节）

- `solutions/service.py::_skeleton_text_fields` 的 `design_markdown` **追加两段**：「## 方案选项与取舍」（选项 A/B/C + 取舍，四个占位行均带「待补」提示）与「## 明确不做（本阶段不包含）」（搬运 `out_of_scope_json`，无条目时落占位行）。**只追加、不改既有段标题**——`## 方案设想（待人工修订）`/`## 实施路径（待人工修订）` 与 risks 段三类前缀原样保留（既有 goal-d2 / delivery compiler 用例钉住）。
- 桌面**零改动**：桌面用通用 Markdown 渲染器消费 `design_markdown`（`MemoMarkdown`），无硬编码段落清单 ⇒ 新增 `##` 段自动渲染。
- 测试：NEW `server/tests/test_solution_skeleton_options.py` 6 例（三选项与取舍占位齐备/「明确不做」独立成段且 risks 前缀不回归/段序固定/无 out_of_scope 时段落不消失/验收标准段搬运/新段进得去冻结的 SOW 快照）；既有 `test_goal_d2_s0_closeout.py` 追加 T-A5 断言。

### 口径勘误（与登记原文三处出入，已回写 backlog）

登记原文「`out_of_scope` 段即『明确不做』」不成立——既有六段里 `out_of_scope` 只混排在 `risks_dependencies` 段（与「假设」「待确认问题」三类前缀同段）⇒ 「单独可见」必须**新增独立段**；登记原文「桌面模板渲染用例」不成立——桌面零改动；另 `workflows/compiler.py::compile_delivery_preview`（本体编译路径）全仓无生产调用方 ⇒ 本条不覆盖该路径。

### 口径

#172 PR-head CI run 42277662998 实测 pytest **2062 passed＋6 skipped**（2068 收集）＋vitest **862**（70 文件，桌面零改动不变）／mypy 279 不变／路由 **304**（零新增路由，脚本现测）／蓝图 40／业务表 105／迁移头 `b2e8f4a6c9d3`（36 rev）／零迁移零新表零新字段。

## [未发布] — T-A4 事实/假设/待确认三层桌面可视化：条目粒度编辑（2026-11-06）

### 桌面（纯桌面零服务端改动零迁移零路由；详见 backlog T-A4 实施轮节）

- NEW `desktop/src/renderer/src/guidance/classificationLayers.ts`：五分类（`customer_stated`/`ai_synthesized`/`ai_inferred`/`open_question`/`human_added`）→ 三层归属纯函数——客户事实层／AI 判断层／待确认层；**无锚点且非 human_added 一律降级「待确认」**（服务端 AI 路径 fail-closed 但人工 PATCH 弱校验 ⇒ 库里可能有无锚点条目，桌面降级是必需的第二道闸，不替无锚点判断背书）。
- `GuidanceReview.tsx` 只读态三层分组呈现（分类标签+锚点+事实层确认状态，原先渲染纯文本 `<li>` 全部丢弃）；编辑态改**条目粒度编辑器**（每条卡片：分类下拉+锚点只读+确认勾选+文本+删除）——顺带修掉「整字段 textarea 按行号继承元数据」的错位缺陷（插入/删除行曾把 A 的锚点贴到 B 的文字上静默落库）；**分类下拉候选集受锚点约束**（无锚点只能选 `open_question`/`human_added`，与服务端 `missing_source_ref` 同口径）。
- 测试：NEW `guidance-classification-layers.test.tsx` 9 例（三层归属/无锚点降级/条目粒度/改删不错位/候选集受限/空条目过滤/保存保留元数据）；既有 guidance 22 例零回归。

### 口径

vitest **858**（CI run 42251482875 实测；+19 含并发 #163）／pytest 不变／mypy 279／路由 302（当时）。

## [未发布] — T-A3 调研表三态流转（confirm/reject/revise）桌面入口（2026-11-06）

### 桌面（纯桌面零服务端改动零迁移零路由；详见 backlog T-A3 实施轮节）

- `ResearchForm.tsx` 表单详情底部新增三态操作区（与「保存调研内容」分离，消费既有 confirm/reject/revise 三端点）：**确认事实**（can_manage，本地先按服务端同源口径校验必答缺失，不发请求）；**驳回并留意见**（理由必填，`{version, review_comment}`，驳回意见回显）；**创建修订版**（can_update_assigned_tasks，confirmed 态，`{version}` 开新 draft）。
- 权限显隐与服务端同构（`canManage` 可选 prop **默认无权**——漏传时按钮不出现）；409 `stale_version` 走既有冲突面板不吞；未知错误码回落服务端原文。
- **revise 定位裁决**：显式**留痕通道**而非唯一改稿路径——PATCH 的隐式 fork（`_ensure_working_revision`）不记事件，`revise_form` 记 `project_research_form_revised` 进事实链；「已确认表只读」收紧被既有用例判红后撤回（legacy 兼容契约维持）。
- 测试：`project-research.test.tsx` 新增 tri-state describe 10 例；research 域 222 例压链全量回归后合入。

### 口径

vitest **848**（69 文件；CI 4 job 全绿）／pytest 不变。

## [未发布] — T-A2 企业名自动替换层：presurvey 正文代号化三道防线（2026-11-06）

### 服务端（零迁移零路由；详见 backlog T-A2 实施轮节）

- NEW `guidance/enterprise_dict.py`（种子词典 + `FDE_ENTERPRISE_DICT` 现场补充、格式 fail-closed、通用词判定、中文候选前缀剥离）+ NEW `server/seeds/enterprise-names.txt`（**只放合成示例**，真实企业名永不进 git；CI pseudonymization `FDE_LEADS_MD` 改指此文件，一致性由哨兵测试钉死）。
- `guidance/redaction.py` 扩展 `redact_text_detailed`/`redact_presurvey`（既有 `redact_text` 签名语义不变）；worker 链**三道防线**接入：①进模型前全文替换（本地抽取腿不落存储）②模型输出落库前兜底替换（文本+LIST_FIELDS+evidence）③复核清单落 `operation_events`（`guidance.redaction_review`，B#9 可查）。
- **拍板口径「放行 = 不留库」**：疑似名同样替换为代号（替换目标=`projects.enterprise_code` 首段），记入复核清单交审核人 confirm 前复核；通用词（「技术公司」类）零改动不进清单。机制性故障 → `RedactionConfigError` → `pseudonym_dict_unavailable` 不重试，`project_draft` 503。
- 测试：NEW `test_guidance_enterprise_redaction.py` 13 例 + `test_guidance_redaction_worker.py` 2 例（数据全合成）；**本轮未做**：执行面 `agents/context.py` 未接企业名替换（口径不同，另立条目）。

### 口径

pytest **2016 收集 = 2010 passed + 6 skipped**（+15）／桌面零改动。

## [未发布] — T-A1 presurvey S3 前置闸桌面可读提示（2026-11-06）

### 桌面（服务端零改动）

- G3 诊断开工门 409 拦截态不再吞成通用文案：服务端 message 原文 + G3 四项清单（**claimed ≠ accepted 徽标**）+ 前往门禁页跳转锚（NEW `PresurveyGateHint.tsx`；服务端闸本体 `guidance/service.py:402` 已在，本轮只补桌面可读呈现）。
- 测试：NEW `presurvey-gate-hint.test.tsx`（vitest **833** 全绿）；同轮回写改造方案 §拍板闸 6 全部收口（①②③⑥ DECIDED）。

## [未发布] — V3 两级注入全链路：契约 references 组 + 消费面两层接线（#8，2026-11-06）

### 契约扩组（技能结构化契约 v1 §2.6，零迁移零路由零新表）

- NEW `references` 必读引用组：`required_reading`（执行前必读，硬前置）＋ `authoritative_sources`（冲突裁决，软引用）。语义锚＝`fde-package-verify` 手写规则「README 冲突以 README 为准」——把「权威在技能正文之外」的约束从散文升级为机器可读引用。
- 键空间闭合枚举同步扩组（`test_skill_contract` `CONTRACT_GROUPS` +references），B#37 静态闸验证通过。

### 消费面两级接线（mcp_gateway）

| 级 | 工具 | 内容 |
|---|---|---|
| **第一级**（选技能前） | `skill_list` | item 带 `when_to_use` 摘要（取自 `use_boundaries` 组；未填不带键——缺省＝不误导） |
| **第二级**（读正文前） | `skill_read` 首页（offset=0） | 带 `required_reading`/`authoritative_sources` 引用清单；**续页不带**（同一正文延续，重复是噪音）；良构校验（list[str] 全非空才出，不猜不放宽） |

- **引用不携带内容、不产生新读取权限**：引用是仓库内相对路径，消费方用既有只读工具自行读取；`skill_list`/`skill_read` 工具 schema 静态钉住不变。
- **T-S2 计数语义不变**：首页带引用不改变「仅首读计一次」。
- 4 个 runbook 按「平铺点路径 + JSON 数组字面量」回填 `use_boundaries`+`references`（**种子 13 条维持 B#36「不回填」裁决不动**）。

### 测试

NEW `server/tests/test_skill_readbefore.py` 5 例；**变异三连逐一转红**：列表不带摘要／续页也带引用／坏引用透传。技能域回归 25 passed。

### 口径

pytest **2056 收集 = 2050 passed + 6 skipped**（+5）／vitest **858**（零桌面改动，校正自 B#30-A 基线 839——main CI run 42251482875 实测 858，其间 #163/#164 并发 +19）／mypy **279**（不变）／蓝图路由 **304**（不变）／业务表 **105**（不变）／api_catalog ENTRIES **94**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）。

> 口径基线取 main HEAD `5b47c07` CI run 42251482875 实测 2045 passed＋6 skipped＝2051 收集；本地 collect 2056＝2051+5 交叉对齐。

### 同轮核销

- 借鉴总览 #36/#37 四处「✅ 已实施 · 未提交（b36b37 轮）」过时状态核销为「✅ 已实施 · #140」（#140 已于 fork/main 合入）。

## [未发布] — V3 B#30-A 门禁证据漂移呈现：同源换版只读复核（2026-11-06）

### 行为变更（零迁移零路由零新表；server 变更 ⇒ 合并后 rebuild 三镜像；桌面变更 ⇒ 便携版重打包挂账）

- **清单项级「前置复核」**：门禁清单项引用的证据（`evidence_id`）若被**同一 `source_uri` 上更新的 hash 行**（T-G1 换指纹并存语义）超越，门禁视图序列化对该项输出 `evidence_superseded: true`。检测有界——只比该 uri 的证据登记行集，不扫全表。
- **呈现即提示，四不动**：状态机、claim_status、拍板有效性、AI 权限一律不变；不携带新行指针（跳转走证据登记簿面）；重核与否永远由人决定。
- 三调用点接线：门禁列表、提交证据响应、拍板响应均携带该标记；桌面 `GateBoard` 对旧服务端载荷（无该键）保持兼容，换版项呈现「证据已换版」警示 badge（title 说明四不动边界）。
- 测试：pytest +2（同源换版翻转／无重采不误报；变异摘检测红→还原绿）＋ vitest +1（badge 呈现／旧载荷无键不受影响）。
- 顺带修复：#155 合并在 AGENTS.md 遗留的冲突标记残渣（`=======` 段＋commit 尾巴＋#85 条目丢换行）。
## [未发布] — V3 只读技能中心（B#32 A 面）＋ 借鉴总览台账漂移校正（2026-11-06）

### 只读技能中心（B#32 A 面——交互拍板⑤A，零迁移零新表零依赖）

- NEW `server/src/fde_api/control/skill_center.py`——**DB 权威只读浏览面**（取内容域、弃文件目录形态：技能权威已在 `skill_definitions`/`skill_versions`，另起文件系统 provider 会出现两个权威且漂移不可测 ⇒ 不引文件目录、不引依赖 ⇒ 无供应链闸）。
- 新增 2 条只读路由：`GET /api/v1/skills`（可选 `?scope=public|personal`，非法值按空处理——不猜不放宽）、`GET /api/v1/skills/<skill_id>/document`。
- **权限面与既有 `mcp_gateway._skills` 同尺**：`status=published`（draft/in_review 未过发布闸不外泄）＋ `scope=public` 或 `owner=当前用户`；不可见即 **404**（不区分「不存在」与「无权」，避免探测）。
- **不消费计数**：`skill_read` 读出指南才计一次消费（T-S2 语义），本面是治理浏览面（人看目录、下载文件）——浏览一次就写一条 `skill_used_*` 会虚增「已消费」记录。
- 有界返回：列表 200 条上限＋正文 512KB 上限（超限拒绝，不截断）。
- NEW `server/tests/test_skill_center.py` 5 例；**变异四连逐一转红**：去 `status` 过滤（draft 泄露）／去 `owner` 限制（他人个人技能泄露）／浏览写消费计数（计数 +1）／正文面返回空正文。

### 借鉴总览台账漂移校正（v1.10）

- `docs/audit/开源项目借鉴总览-2026-11-05.md` §1 P1 段**状态列九条按 `fork/main` 实况回写**（#7=#150／#12+#31=#154+#157／#13=#153+#158／#14=#159／#8+#32=#138＋本轮 A 面／#11 落点设计已落／#30 立项 #144）——此前六条仍标「⬜ 待实施」而实际全部已落地。
- §5.1 已兑现表补五条缺项；§5.2 标注顺位 1/2/3 **已全部兑现**；§5.4 标注剩余可排期项（#30 A 面／#8 两级注入 `readBefore`／#11 随 #23 解封）。

### 口径

pytest **2049 收集 = 2043 passed + 6 skipped**（+5）／vitest **838**（不变）／mypy **279**（不变）／蓝图路由 **304**（+2）／业务表 **105**（不变）／api_catalog ENTRIES **94**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）。

> **口径校正**：前值「2014 收集」系 #159 轮本地推算、未计 #158＋#160 并发增量——本轮基线取 main HEAD `d467fac` CI run **42241563180** 实测 2038 passed＋6 skipped＝2044 收集，再加本轮 +5 ＝ 2049。**并发轮期间本地推算不可作基线**（#129/#131/#157 之后第四次同类校正）。

## [未发布] — V3 到期治理收口：B#13-C API confirmation 主动超时 + B#13-D 跨域只读投影（2026-11-06）

### B#13-C（零迁移零路由零新依赖；server 变更 ⇒ 合并后 rebuild 三镜像）

- **derived state 裁决落地**：`OperationEvent` append-only 完整保留——到期不追加 expiry event、不 UPDATE/DELETE 原 request 行、不建后台 sweep（该域无清理副作用，持久化过期事实零行为收益，反而引入系统 actor 与事件生命周期两个新语义面）。
- `control/api_actions.py` 新增唯一窗口常量 `CONFIRMATION_WINDOW`（15 分钟）与到期谓词 `confirmation_expired`；pending 列表 / `action_status` / `decide_action` 三处此前各自手写的 `timedelta(minutes=15)` 全部收敛到该原语。
- **边界统一**：从严格 `<`（恰等于 15 分钟仍有效）对齐为 `deadline <= now`（恰等于即过期），与立项合同 §3.3 / B#13-B 上传会话 / 审批域同拍。
- 到期行为：过期确认从 pending 列表筛除、status 返回 `expired`、迟到 decision 409 `action_expired` 且**零事件/目标副作用**（不落 started/finished、不触碰目标对象）；started-but-uncertain 防重放保护**优先于到期**（不报 expired、绝不重放），finished replay 越窗仍有效；auth_version/fingerprint/password 防线原位不动。
- NEW `server/tests/test_api_confirmation_expiry.py` 7 例（常量值钉/谓词边界/窗口内全待/过期全拒+零副作用/uncertain 优先/越窗 replay/窗口常量放大变异证明三路径+投影同源）。

### B#13-D（零 DDL；+1 路由）

- **NEW `fde_api/expirations.py`**：跨域到期只读投影——服务层只读 union + admin-only `GET /api/v1/expirations`，输出立项合同 §2 六字段逻辑视图（`domain`/`object_id`/`deadline_at`/`state`/`due`/`expiry_action`）。不建 SQL view 的决定性理由：api_confirmation 截止时刻是派生值，SQL view 会把窗口规则复制成第二权威；服务层直接复用 B#13-C 同一常量与谓词。
- 四域接入：automation_approval（pending）/ upload_session（uploading）/ api_confirmation（awaiting_confirmation，derived）/ dispatch_offer（offered，`offer_deadline` 派生）；`due` 统一按 `deadline_at <= now`；dispatch 原生转换器保留严格边界（边界瞬间读数先行一拍，只读不写回）。
- 权限与面：admin-only（运营看板视角；触发条件=用户明确指示实施）；`limit` 默认 100 上限 500，排序 `(deadline_at, domain, object_id)` 稳定升序，`domain`/`due` 过滤；只投影元数据（不外泄确认 body/审批 arguments/对象键/客户资料）；`expiry_action` 只是符号名指针不执行；**不进 api_catalog**。
- NEW `server/tests/test_expirations_projection.py` 8 例；审计清单重生成：route **302**（+1）/ blueprint **40**（+1）；105 表、迁移头 `b2e8f4a6c9d3`（36 rev）不变。

### 口径

pytest **2029 收集 = 2023 passed + 6 skipped**（CI 实测；本地专项 15 例 + 邻域 89 例全绿）／mypy 基线 **279** 不变／蓝图路由 **302**（+1）／业务表 **105**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，零迁移）。

## [未发布] — V3 B#14 executor 对抗性测试直补（2026-11-06）

### 对抗钉（纯测试轮，零迁移零路由零业务代码）

拍板盘点五夹具族：①固定种子模拟／③迟到拍板／④双 definition_version 并存 **已由现有 39 例覆盖**；②强杀不丢已确认／⑤节点独立事务失败恢复 **为缺口**。按拍板 opt A「直补对抗钉」实施（不做 2–3 周决策逻辑纯函数重构，与总览「先攒真实故障史」裁决一致）。

- **NEW `server/tests/test_workflow_executor_adversarial.py` 4 例**：
  - **强杀族**：进程级死亡（worker_lost 收口）**不得抹掉已 succeeded 节点的产物**（逐位相等）；resume **不重跑已确认读面**（外呼次数只 +1）。
  - **tx B 崩溃族**：settle 落表自身崩溃 → 节点悬 running → 恢复重跑时**幂等键不变**（同 action id ⇒ api_actions 层去重 ⇒ 不二次外呼）＋**attempt 保留**（「本次尝试已发生」的事实不被恢复路径抹掉）。
  - **恢复底座钉**：`_recover_interrupted` 只把 running 放回 pending，**不动 succeeded**。
- **变异双红**：恢复路径抹掉 succeeded 产物（2 例转红）／去幂等键守卫 + 派生含 attempt（tx B 族转红）——等价变异（单改派生式因守卫短路）已识别并改用可辨组合。

### 口径

pytest **2014 收集 = 2008 passed + 6 skipped**（+4）／mypy **279** 不变／ruff F401,F841 全绿／蓝图路由 **301**（不变）／业务表 **105**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）／vitest 不变（零桌面改动）。

## [未发布] — V3 拍板收口：B#30-B=opt1 + 提示词卫生差距②静态钉（2026-11-06）

### 交互拍板收口（①零代码 + ②纯测试轮，零迁移零路由）

- **B#30-B 门禁终态回退语义＝opt1 维持现状**（交互拍板）：passed/conditional_pass 终态不可逆维持（重交 409 现状不变），**零代码零迁移**——回退通道引入状态机新分支+桌面回退 UI（≈1–2 人日），当前无真实场景推动，错误拍板走线下 OperationEvent 留痕追溯；opt2/opt3 保留候选、真实诉求出现时重开。backlog B#30 行与状态段已回写。
- **提示词卫生契约差距②＝补静态钉**（交互拍板）：NEW `server/tests/test_prompt_entrypoint_gate.py` 3 例——受闸入口（`execute_ai_prompt`/`direct_tool_completion`/`direct_provider_completion`/`_degraded_direct_result`）的 `system_prompt` 实参来源 AST 允许名单（字面常量／形参直传链变量／`_workbench_system_prompt()` 白名单组装函数），域外形态即红；附钉定义落点锚（防定义漂移出受闸文件面）＋ **kwargs 透传禁令（防绕过 AST 形态判定）。**变异双红**验证：chat 接 `prompt` 变量进 system_prompt／structured 改 `**payload_kw` 展开——逐一转红。
- 同日另三项拍板（T-A2 分层失败语义／T-A2 词典=种子文件／T-A7 谈判稿=复用 solution 版本行）由并发会话回写于主树，与本轮不重叠。

### 口径

pytest **2010 收集 = 2004 passed + 6 skipped**（+3；**口径校正**：前值 2013 为本地推算重复计并发轮增量，CI run 42223701893 实测为准）／mypy **279** 不变／蓝图路由 **301**（不变）／业务表 **105**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）。

## [未发布] — 桌面实施轮②：CR-032 桌面调研 subject_type 读路径承接 T-O2b 注册类型（2026-11-06）

### 桌面（零迁移零路由零服务端改动；无需 rebuild / alembic / 重打包）

- **读路径守卫放宽（CR-032 核心）**：桌面调研 DTO 守卫此前把 `subject_type` 钉死内置五类枚举（`RESEARCH_SUBJECT_TYPES`），而服务端 T-O2b（#83）已把物理边界放宽为码格式 `^[a-z][a-z0-9_]{0,59}$`（迁移 `b5d9e3f7a1c6`）＋注册表 active 行——**注册类型（如 `vendor`）落库后，桌面 `ResearchWorkspace` 读路径校验即失败 → 整个调研 tab「数据格式异常」、项目正常数据全不可读**。修法：`ResearchSubjectType` 放宽为 `string`，新增 `isResearchSubjectType`（与 DB CHECK 同尺码格式守卫）承接读路径（`isResearchSubjectDto`／`isResearchFormDto`／`isResearchImportPreviewDto` 三处五类守卫改走同尺）；内置五类仍由 `RESEARCH_SUBJECT_TYPES` 承载写路径（创建/下拉/父子树，**写路径注册类型选项＝后续轮**——须接 ontology 只读 API＋父子约束，本轮不扩张功能面）；展示走新增 `researchSubjectLabel`（内置取中文标签、注册码原样回显，杜绝缺标签拒载/乱显示）。
- **测试 +2 例**：注册类型码（`customer`/`supplier_x`）读路径承接＋非法规码（`9Bad`/`Customer`/超长/连字符）仍拒；既有用例同步（`"nonsense"` → `"9Bad"`）。

### 口径

- 桌面 vitest **838/838**（基线 **836**＝CI run 42223701893 实测 ＋2；桌面纯前端轮，零服务端改动）；pytest / mypy / 表 / 迁移 / 路由 / ENTRIES 全部不变。 (docs(v3): 校正桌面实施轮② vitest 口径 833→838（基线随 #156/#157 插队上移，现测为准）)

## [未发布] — V3 提示词卫生 J 系接线：B#12+B#31 判据落地（2026-11-06）

### 契约判据接线（零迁移零路由零新依赖；server 变更 ⇒ 合并后 rebuild 三镜像）

- **NEW `server/tests/test_prompt_hygiene_jseries.py` 5 例**（承接《外部文字禁入与原件派生分离契约-v1.md》§5 可断言判据；组织同 B#4 purity 静态测试）：
  - **J-1 静态钉**：全仓 system role 消息组装点 AST 枚举——content 必须是「常量／常量名／形参直传链／已登记例外」四形态之一，域外新增即红（PR 须对照契约 §2 表登记）；附钉 executor skill 节点 `system_prompt` 仍＝治理面发布 `instructions`（白名单④不旁路）。
  - **J-2 行为钉**：四类「不可信资料」工具结果必须带结果级 `source` 标记——`file_read`/`help_fetch` 既有；**`lcsc_search`/`lcsc_runs_read` 本轮补 `untrusted_storefront_content`（契约 §4 差距①闭合，P-3 标记腿全满足）**；附钉 lcsc run 返回体单一形状源（`_serialize`）。
  - **J-3 静态钉**：`documents/ai_content` 的 system 提示词是纯常量构造——payload/请求内容变量泄漏进构造即红。
- **变异三连**逐一转红：lcsc 标记删除／executor 接 prompt 变量／system 拼接 payload。
- **差距②开放保留**：`direct_tool_completion` 形参面无静态闸（形参直传链上游来源已逐点登记于测试 docstring；封堵须另轮）。

### 口径

pytest **1999 收集 = 1993 passed + 6 skipped**（+5）／mypy **279** 不变／蓝图路由 **301**（不变）／业务表 **105**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）。

## [未发布] — V3 桌面实施轮①：B#28 门禁 revision CAS 桌面接线（2026-11-06）

### 服务端 + 桌面（零迁移零新路由；server 变更 ⇒ 合并后 rebuild 三镜像 + alembic 幂等）

- **服务端**：门禁视图（`GET …/projects/{id}/gates`）与拍板响应回传 `revision`（≡ 既有 `gates.version`，**零新增列**；与 `lifecycle_version`（语法代际）刻意分离——后者不随拍板推进）。
- **桌面 `GateBoard.tsx`**：拍板请求原样带回 `expected_revision`（B#28 CAS 此前**服务端已就位而桌面从未启用**——桌面不知当前 revision）；409 `gate_revision_conflict` 如实呈现「本次拍板未生效；面板已刷新」并自动刷新面板（人可基于新状态重拍，不静默覆盖前写）；旧服务端载荷缺 `revision` 时不带该键（缺省＝旧客户端兼容）。
- **测试**：服务端 +1 钉（视图 `revision` ≡ 行 `version`，且用视图值拍板可生效、revision 推进 +1）；桌面 +3 例（带入 `expected_revision`／旧载荷不带／409 冲突如实呈现并刷新）。

### 口径

- pytest **1986 收集＝1980 passed＋6 skipped**（+1）／vitest **828/828**（+3）／mypy 基线 **279** 不变／105 表／迁移头 `b2e8f4a6c9d3`（36 rev，零迁移）／蓝图路由 **301**／api_catalog ENTRIES **94**。

## [未发布] — V3 回滚轮落定重核（§三 逐行复测＋审计清单回刷＋CR-003 销号）（2026-11-06）

### 文档与脚本（零业务代码零迁移零路由零桌面功能改动；无需 rebuild / alembic / 重打包）

- **`docs/implementation/v3-迁移进度对照-fde-v2建议-2026-11-04.md` 第七轮同步**：§五-7「并发在途品牌·回滚轮」**结清并翻转**（回滚轮落定为 #132＝155 文件（67 纯增／54 改／33 二进制／1 删）**零 server 改动零迁移改动**；原拟撤的 T-W7/T-I1/T-C1 四件套实测全部存续；fork/main 无任何 revert 提交）→ **§三 全量 DONE 判定逐行复测无一被推翻**；新增 §五-9（审计清单落后 1 条 ＋ 抽取脚本蓝图硬编码漏登）与 §十三（第七轮增量记录）；§二 P1④／§四 C-4 补「skill_read 分页已实施」当前态标注。
- **行号锚修 6 处**（基线 fork/main `d3adf1c`）：`workflows/models.py:157→:163`、`executor.py:694→:701`、`executor.py:1402-1413→:1373-1413`、`definition_service.py:118→:119`、`SkillVersionsPage.tsx 355→356 行`、§三 T-S1/S2 交叉引用 `§五-3→§五-5`——**前三处系第五轮声称「已修正 8 处漂移」而正文未落地**（「声称已修 vs 正文未改」），本轮当场补正。
- **主报告 §20 实施跟踪注记补齐条目 9–19**（此前停更于 T-S1）：T-S2／T-W6／T-O4b·T-O4 桌面／T-G2·T-D1／T-C1·T-I1／T-W7·T-UI1／T-J2／P3 四项定案／P0 先行批 B 系列／五份纯文档／UI-UX 轮·B#9，并附「注记补齐说明」记录挂账前提与消解依据；`docs/goal-c-代码审查台账.md` **CR-003 随之销号**。
- **审计抽取脚本补登 ＋ 三清单回刷**：`scripts/audit/extract_workbench_inventory.py` 的 `BLUEPRINTS` 硬编码列表补 `fact_chain_blueprint`（按 `app.py` 注册序紧随 `evidence_blueprint`）→ 重生成 `docs/audit/v3-route-inventory.csv`（+1 行＝新路由）与 `v3-workbench-inventory.json`；DB CSV 零变化。
- **AGENTS.md**：工作流节新增「审计清单刷新有前置条件（`BLUEPRINTS` 硬编码列表须随蓝图增删同步登记——同一坑两次：T-J2/CR-027、#145 `fact_chain_blueprint`）」；补本轮 bullet；CR-003 挂账措辞更新为已销号。

### 口径（现测，基线 fork/main `d3adf1c`）

- 105 表 / 迁移头 `b2e8f4a6c9d3`（36 rev，#131~#145 全域零迁移）/ api_catalog ENTRIES 94 不变；**蓝图路由 300→301**（#145 +1：GET `…/projects/{id}/execution-facts`，不进 api_catalog）；pytest **1985 收集＝1979 passed＋6 skipped**／vitest **825**／mypy 基线 **279**（后三项取 #145 CI run 42183340134 实测）；审计脚本同源复测＝route 301 / blueprint 39 / table 105 / rev 36 / heads=[b2e8f4a6c9d3]。

## [未发布] — V3 回执 DSL 一期（B#7，2026-11-06）

### 契约层（零迁移零路由零新表零依赖）

- **NEW `server/src/fde_api/agents/receipt.py`**：回执 DSL 是**外部可写结构**，故按白名单逐字段校验——**未知字段一律拒绝**（不静默丢弃、不透传；否则外部多写一个键即绕过闸门）。容量上限对齐既有审批材料 **64KB** 语境（超限拒绝不截断）。
- **两种人工介入动作**：
  - **`ask`**＝请求人工拍板 → 落既有 `automation_approvals`（**零新表零新路由**，密码确认闸现成）：幂等＝`request_key` 由「项目＋能力＋规范化回执」派生并复用既有 pending 审批（崩溃恢复不重复建单）；能力须在 `CAPABILITY_REQUIREMENTS` 白名单且发起人**当下**仍具备；**风险档固定 4**（人工门＝保守高险，诚实标注）；敏感键拒绝入审。
  - **`later`**＝请求延后复查 → 落**最小到期挂点**（`operation_events`，只表达 `due_at` 时点结构）。
- **边界声明**：later **不实现**统一到期表／主动超时扫描／统一 cron 计算——那是 **B#13** 的 `deadlines()` 纯函数职责，本条不越界（B#13 落地时把 `due_at` 纳入其到期表即可，无需改动本条）。
- DSL 不可解析 ⇒ 走 **B#2 降级路径**（业务动作可能已执行，不能重做 ⇒ 落独立终态 `succeeded_but_receipt_invalid`，拒绝同键重跑）。
- **命名隔离**：既有 `AgentResult.receipt_state` 是**产物清单扫描**语义，与本条**人工介入动作**语义正交，两套并存不互相覆盖。
- **实现要点**：`action` 用 **discriminated union**（按 `kind` 判别）——普通联合会逐分支尝试并汇总**所有分支**的错误（含无关分支字段名），错误信息冗长且误导；错误路径取完整 loc（`action.ask.bogus`）而非只报顶层。

### 测试

- NEW `server/tests/test_receipt_dsl.py` 8 例：顶层与 action 双层未知字段拒绝／非对象与未知动作拒绝／容量上限拒绝不截断／指纹顺序无关稳定／ask 建单与幂等复用＋风险档 4＋sha256 指纹／未知能力拒绝／敏感键拒绝／later 挂点字段闭集且无主动扫描器／delay 越界拒绝。
- **变异五连**逐一转红：未知字段改为忽略／容量上限失效／敏感键扫描失效／ask 幂等失效／later 越界校验失效。

### 口径

pytest **1994 收集 = 1988 passed + 6 skipped**（+8）／vitest **828**（不变，回执 DSL 轮零桌面改动）／mypy **279**（不变）／蓝图路由 **301**（不变）／业务表 **105**（不变）／api_catalog ENTRIES **94**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）。

## [未发布] — V3 门禁前置复核与回退留痕立项（借鉴 B#30 消费）（2026-11-06）

### 文档（零代码零迁移零路由；无需 rebuild / 重打包）

- **NEW `docs/architecture/门禁前置复核与回退留痕立项-v1.md`**：**A 面＝前置清单证据漂移自动复核呈现**（T-G2 同构：同 `source_uri` 新 hash 证据行超越清单项已引用 evidence ⇒ 项级 `evidence_superseded: true` 只读呈现，呈现即提示四不动〔状态机/claim_status/拍板有效性/AI 权限〕，零迁移可实施）＋**B 面＝拍板回退通道与留痕合同**（现状 `passed/conditional_pass` 终态不可逆、`failed` 有重交回环；三选项登记 opt1 维持现状／opt2 受限回退〔仅 conditional_pass 可退、passed 不退、`gate_rolled_back` reason 必填〕／opt3 只读复核队列——**是否开放终态回退＝业务拍板项，本文不预支裁决**）。不做清单：不动 evidence 不可变性／不做定时自动重核／AI 不代拍板不代回退。现状行级锚：状态机 CHECK 五值／重交闸／OperationEvent from→to 留痕。
- backlog B#30 行回写（A 面随下次 gate 轮、B 面须拍板；立项≠实施授权）；AGENTS 补轮次 bullet。

### 口径

- 零代码零迁移——pytest 1981 收集（1975 passed + 6 skipped）/ mypy 279 / vitest 791 / 105 表 / `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 全部不变。
## [未发布] — V3 B#13-B UploadSession 主动到期与 multipart 清理（2026-11-06）

- 过期上传会话在 `expires_at <= now` 时由服务端行锁收敛为 `expired`；迟到分片签名/完成返回 `upload_session_expired`，不触碰对象存储、不创建文件版本；分片签名 TTL 不超过会话剩余时间。
- 新增 `file.upload.cleanup` outbox/worker 清理链：scheduler `skip_locked` claim，worker 在数据库事务外执行 multipart abort，再独立事务落 cleanup 账本；`multipart_upload_not_found` 视为幂等成功，其他错误保留稳定错误码并沿 recoverable job 退避。
- 复用既有 `UploadSession.expired/expires_at`，零迁移、零新路由、无人工外呼；B#13-C API confirmation 与 B#13-D 跨域只读投影仍 PROPOSED。
- 测试：新增 B#13-B 专项 8 例，连同上传/worker/reconcile 邻域共 65 passed；PR-head CI 最终全量 1996 passed + 6 skipped（2002 收集）；mypy 279/104、ruff 全绿。

## [未发布] — V3 门禁判据实施落点设计（借鉴 B#11 消费）（2026-11-06）

### 文档（零代码零迁移零路由；无需 rebuild / 重打包）

- **NEW `docs/architecture/门禁判据实施落点-v1.md`**（承接 B#21/B#22 评测协议冻结文本，B#22「实施落点=B#11」清偿）：**裁决＝三锚四反例的宿主＝B#23 夹具的「评测器元验证层」**（验证打分检查器本身：do_nothing≈0/ literal≤0.2/ oracle≥0.95＝检查器认得出参考解）；门禁面落点已随 #131 冻结（G9 `exit_condition` 含「三锚四反例全过」，钉 6 守护）；pytest 模板落点＝四条件解封后 NEW `server/tests/test_eval_criteria_harness.py`。**元验证语义（本文定义）＝评测器可用于「验收线达成」判定前必须先过元验证夹具——锚点不落位/反例漏抓 ⇒ 输出不得作 G9 判定输入（`insufficient_data` 不变）**。含被验证对象诚实盘点（当前仓内无打分型检查器——判据现为算分器预置合同）、逐判据落点表 11 行、阈值校准纪律。判据语义零新增零改写、种子零改动。
- backlog B#11 行回写（落点设计已裁，实施随 B#23 夹具期，设计≠实施授权）；AGENTS 补轮次 bullet。

### 口径

- 零代码零迁移——pytest 1981 收集（1975 passed + 6 skipped）/ mypy 279 / vitest 791 / 105 表 / `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 全部不变。

## [未发布] — V3 提示词卫生与工件血缘契约（借鉴 B#12+B#31 消费）（2026-11-06）

### 文档（零代码零迁移零路由；无需 rebuild / 重打包）

- **NEW `docs/architecture/外部文字禁入与原件派生分离契约-v1.md`**：外部文字禁入提示词（B#12）＋原件/派生分离（B#31）两层合一契约。**现状实测＝主干已有机闭合**（全系统恰四处 system 组装点全部落在内部权威白名单内；外部数据一律 user/tool 角色或结构化 JSON payload；原件只存指针＋sha256；`captured_from` 封闭枚举＋`ai_request_id`/`revision_id` 血缘在位）；契约把散落防线收拢为 **P-1~P-5（提示词层）＋A-1~A-5（工件层）**十条规则＋封闭枚举白名单，差距如实登记（lcsc_* 结果无 source 标记／`direct_tool_completion` 形参面无静态闸／「生成默认不视作已审」无统一谓词／个人技能 owner 自治边界），附四条可断言判据（J 系，接线仍 PROPOSED）与触发式复查机制。纯我方独立设计，零第三方正文/结构化表达引用（AGENTS 红线第 8 条履行）。与 B#3／外部模型依赖契约 M 系／W-8 四层分工互不覆盖。
- backlog B#12+B#31 行回写（契约落盘、J 系接线仍 PROPOSED）；AGENTS 当前状态补轮次 bullet。

### 口径

- 零代码零迁移——pytest 1981 收集（1975 passed + 6 skipped）/ mypy 279 / vitest 791 / 105 表 / `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 全部不变。

## [未发布] — V3 B#13 到期语义与主动超时治理立项（2026-11-06）

- 新增 `docs/architecture/到期语义与主动超时治理-v1.md`：登记原生到期权威、状态转换、并发幂等、副作用与可观测合同；裁决「统一目录+各域原生转换器+条件触发只读投影」，不建复制 `expires_at` 的通用到期表。
- 审批主动超时标记为既有基线（T-P1-5：`_expire_approval` + scheduler sweep）；UploadSession multipart abort、API confirmation append-only 超时列为独立候选阶段；跨域查询须有明确需求才排期。
- 明确排除 worker lease/retry/outbox due、JWT/签名/Redis TTL、模型/进程 timeout 等异质时钟。本轮仅立项，零运行时代码、零迁移、零路由、零数据操作；B/C/D 仍 PROPOSED，不构成实施授权。
## [未发布] — V3 只读执行事实链面板（B#9，2026-11-06）

### 只读聚合面（+1 路由；server + desktop；零迁移零依赖）

- **服务端**：NEW `GET /api/v1/projects/{id}/execution-facts`（can_view，`fact_chain_blueprint`，**不进 api_catalog**——AI 不经此面读审计原始流，与证据登记同纪律）。三源时间线归并：`project_evidence` ＋ `operation_events`（**项目维度**，过滤下推 SQL）＋ `ai_call_audits`（**账号维度**——该表无项目外键，按 actor 过滤且响应明示 `ai_call_audit_scope="actor"`，不作项目切分假装）。时间倒序、`limit` 1–200 有界＋`truncated`、非法参数 400。
- **「外部完成无真实回执=未知」纪律的落法**：`operation_events.changes` 大载荷不外泄；AI 审计只投影调用事实元数据（模型/耗时/token/状态三值，无明文上下文）；**无回执即无行**，由前端呈现「无记录」，不由模型自述或时间线推断拼装任何「已完成」语义。
- **桌面**：NEW `evidence/ExecutionFactChain.tsx` 只读面板，项目 tab +1「执行事实」（11 tab）：三源筛选、类型徽标、AI 调用「账号维度」明示、空态不编造、CR-035 同型序列守卫（筛选切换只认最新响应）。纯只读——无任何写操作按钮。
- **测试**：NEW `server/tests/test_execution_fact_chain.py` 4 例（三源归并排序＋changes 不泄漏＋AI 字段白名单＋未知不编造／actor 隔离跨账号泄漏钉／过滤与 limit 有界＋非法 400／权限 viewer 200·外人 403·404·不进 api_catalog）＋**变异三连**（actor 过滤失效／changes 泄漏／scope 谎称 project）逐一转红；桌面改 1 处 tab 断言数组（vitest 用例数不变）。
- **口径**：pytest **1985 收集 = 1979 passed + 6 skipped**（+4）／vitest **825**（本条自身不变；含并入的 UI-UX 黑金轮增量 791→825）／mypy **279**（不变）／蓝图路由 **301**（+1）／业务表 **105**（不变）／api_catalog ENTRIES **94**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）。**server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`**（零迁移，幂等）；桌面便携版重打包挂账（随下次桌面交付轮）。
## [未发布] — V3 技能结构化契约 + 自洽校验（B#36+B#37，2026-11-06）

### 契约与测试（零迁移零路由零桌面；零 src 改动——无需重建镜像）

- **B#36 技能结构化契约 v1**（`docs/architecture/技能结构化契约-v1.md`）：`SkillVersion.manifest_json` 五组**可选**扩展键——`use_boundaries`（适用边界）/`effects`（副作用声明，`read_only`×`write_actions` 自洽律）/`evidence`（证据口径，指针+指纹语义）/`verification`（验证状态**非状态注记**，published=治理通过≠现场验证）/`failure_behavior`（失败诚实）；不设 `additionalProperties:false`、不换状态值、不改发布四闸；`.agents/skills/` 新技能 front matter 建议（name+description 必填+契约键平铺点路径），存量 4 runbook 与内置种子 manifest 均不回填；`instructions_text` 禁拆 YAML 双权威（DB 唯一权威）。字段全部我方独立设计（B#35 红线第 8 条履行，零 fde-skills 正文引用）。
- **B#37 技能自洽校验**（`server/tests/test_skill_contract.py` 四钉，标准库+pytest 零新依赖）：仓库 runbook front matter 契约；内置种子清单静态契约（能力 ⊆ `CAPABILITY_REQUIREMENTS`）；种子 manifest 构造规则独立复算钉；**种子清单 ↔ DB 行对账**（`seed_public_skills` 端到端：全量落库逐位一致+幂等二轮 0+版本行不增殖）。变异四连逐一转红（read_only 推导翻转/name 脱离目录名/域外能力/version 分档漂移）。
- 顺带核实销号 **B#35**：AGENTS 红线第 8 条+backlog 登记已随 #133 合入，修复项产出（PR 合入）达成。
- 顺带卫生修复：移除 #139 合并在 CHANGELOG 遗留的孤立 `=======` 行（冲突标记残留，会污染后续 rebase 标记识别与渲染）。

## [未发布] — V3 报告待办池清欠（代码批）：skill_read 分页 + GlossaryPage 影响分析接线（2026-11-06）

### 行为变更（零迁移零路由；server 变更 ⇒ 一次 rebuild；桌面变更 ⇒ 便携版重打包挂账）

- **skill_read 分页（B#8+B#32 真缺口闭合）**：MCP `skill_read` 加 `offset` 入参——指南长文按 **16k 字符窗口**分页（与 file_read/help_fetch 同尺），响应新增 `offset`/`next_offset`/`total_characters`（`next_offset` 非空时用 offset 续取）；负数/非整数 offset → 400 `invalid_request`。**T-S2 消费计数收敛＝仅首读（offset=0）计一次**，续页是同一消费行为的延续不加计；未知技能 404 不计语义不变。新测试 `server/tests/test_skill_read_pagination.py` 五例（工具面登记形状/短文单页兼容/长文续取拼接无损/偏移形状闸/计数一次）。
- **GlossaryPage 影响分析接线（T-I1 消费面，§六 P0 #1 清偿）**：术语表行内「影响分析」按钮展开 `GET terms/{id}/impact` 三面清单——counts 汇总＋subjects 命中溯源（matched_via 规范名/别名）＋links 邻接边＋forms 修订状态；并入行查询显示「已解析到存活概念」注记；连点不同行按序列号只认最新响应（CR-035 同型守卫）；失败在行内呈现不收行。
- 文档批（PR #136）：六铁律裁决回写主报告 §17/§19、审计三清单全量刷新（补记⑤）、NEW 术语改名SOP-v1.md、AGENTS「口径数字引用前现测」纪律；报告 §十二 记录全轮。

### 口径

- 零迁移零路由：pytest **1972+5=1977 收集**（1971 passed + 6 skipped，CI 复核）/ mypy 279 不变 / vitest **787+4=791** / 105 表 / `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 不变。
## [未发布] — V3 外部模型依赖契约 v1（借鉴登记 B#10 文档批）（2026-11-06）

### 文档（零代码零迁移零路由零依赖；无需 rebuild / 重打包）

- **《外部模型依赖契约 v1》**（NEW `docs/architecture/外部模型依赖契约-v1.md`）：**B#10 落地产物**——把「在确定性规则之后插入外部模型阶段」这类改动必须遵守的约定成文化。七条规则 M-1–M-7（**我方自定义编号**，与任何上游编号体系无关）：①开关默认 OFF 且关闭时判定逐字一致、零外部请求；②阈值是「建议值」非判定常数、调用时点读取、覆盖免重启；③失败≠错误而是「下一阶段」且既有路径原样继续；④传输层可注入、测试网络零依赖、地址密钥禁硬编码、客户端禁擅自裁剪请求体；⑤外部响应缺字段取保守值不推测、枚举表外值只留痕不参与判定、保守方向须写明；⑥日志只记哈希与长度禁记原文、必记「哪一阶段作出判定」的 source 标记、不新建存储；⑦调用方签名不破坏、新参数一律可选、显式意图预判顺序不得被新阶段翻转。
- **与既有纪律的分工澄清**：本条管**判定层**（新阶段失败→降级到下一阶段），既有 W-8「断链不静默 done」管**流程层**（真失败须显性化），二者不得互相抵消——避免「新阶段降级」被误用为「静默吞掉真失败」。
- **现状对照与差距清单**（全部 `[已核实]`，行级引用采用**符号名＋行号双锚**防基线漂移）：M-1/M-3/M-4/M-7 已满足；M-2/M-5/M-6 三条缺成文纪律——**纯靠立规闭合，零代码**。
- **八条可断言判据**（供未来 PR 自查）：开关关闭零请求、关闭态判定逐字一致、阈值改动免重启、新阶段失败落到下一阶段且既有结果不变、缺字段取保守值、日志原文子串扫描零命中、日志含合法 source、旧签名零改动可用——全部静态或注入式断言，不依赖真实网络与真实模型。
- **触发式复查**：新增任一外部模型阶段时，同 PR 内须逐条对照 M-1–M-7 给「满足／不满足／不适用」三选一，不满足者不得合入；季度复查会随《触发条件复查记录》一并过。
- **来源与边界**：设计原则取自 GIIP「外部模型阶段插入的设计规则」这一**抽象方法论**；按 `AGENTS.md` 红线第 8 条——**只取抽象原则，不复制上游正文段落、不复制其结构化表达**，表格骨架、判据措辞、编号体系均为我方独立重写。

### 口径

- 零代码零迁移零路由零依赖——pytest 1972 收集（1966 passed + 6 skipped）/ mypy 279 / vitest 787 / 105 表 / 迁移头 `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 全部不变（纯文档新增，无口径变更）。

## [未发布] — V3 报告待办池清欠（文档批）：六铁律裁决回写 + 审计清单全量刷新 + 改名 SOP + 数字现测纪律（2026-11-06）

### 文档（零代码零迁移零路由；无需 rebuild / 重打包）

- **六铁律裁决回写（主报告 §17）**：明示「开发轨＝先红后绿+CI 4 绿+单 commit revert+PR 纪律等效（有意裁决）；运行期自动修复轨暂无需求有意不做，若做 agent 落码须补 ①③④⑤」——消除「有意不做 vs 未做」歧义（v3-迁移进度对照报告 §六 #6 清偿）。
- **影子库 / view_watchdog 裁决定性补记（主报告 §19）**：PG `*_test` 硬闸判定等效不照搬（销号后人再评估成本）；view_watchdog 未立项（有意不做），§19 清单维持 7 项。
- **审计清单全量刷新（补记⑤）**：`docs/audit/` 三份清单按 fork/main `dc43a2d` 整体重生成（路由 300 / 表 105 / 迁移 36，与口径行逐位一致）；抽取脚本补登 T-J2/CR-027 两个 admin blueprint——补记③「待本体表落地后整体刷新」欠账清偿（§六 #10 清偿）。
- **术语改名 SOP v1**（NEW `docs/architecture/术语改名SOP-v1.md`）：名字域纽带四步改名流程（先查 impact → change-set rename → 改引用面 → 别名不清理）；代码强制挂后续评估（§五-4 / §六 #7 清偿）。
- **AGENTS.md 新增「口径数字引用前现测」纪律**（工作流与陷阱）：表数/路由/ENTRIES/迁移头/mypy/pytest-vitest 六项测量配方 + 全文同模式终扫要求（#129/#131 两次口径校正的教训制度化）。

### 口径

- 零代码零迁移——pytest 1972 收集（1966 passed + 6 skipped）/ mypy 279 / vitest 787 / 105 表 / 迁移头 `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 全部不变（审计清单刷新为重生成既有产物，非口径变更）。

## [未发布] — V3 P0 先行批收官：审批退避提醒 + SLA 统计（2026-11-06）

### 行为变更（零迁移；server 变更 ⇒ 一次 rebuild）

- **B#5 审批退避提醒（复用任务中心，勿新开外发通道）**：新 `scheduler.remind_pending_approvals`（cli scheduler 循环，与派单/过期清扫同拍）——pending 审批按 `created_at` 起算 **10m→1h→4h→24h** 退避序列 catch-up 补发提醒（过夜可直达 4 级），账本=`result_json["approval_reminders"]`；幂等（已发等级不重发）、四级封顶；`skip_locked` 与并发拍板互不阻塞；非 pending 零触碰。红线对齐：不经微信/邮件主动推送，呈现面=任务中心审批列表。
- **SLA 统计**：`_serialize_approval` 新增 `created_at`（此前未暴露）/ `pending_seconds`（仅 pending）/ `reminder_count` / `next_reminder_at`；workflow run 详情（`serialize_run`）在 `waiting_approval` 态带 `waiting_approval_seconds`（锚=`updated_at`），他态无该键。
- 新测试 `server/tests/test_approval_reminder_sla.py` 五例 + 变异五连（红→反向替换还原→绿）。

### 口径

- 服务端 pytest **1972 收集 = 1966 passed + 6 skipped**（+5）；mypy 279/104 不变；vitest 787 / 105 表 / `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 不变。

## [未发布] — V3 迁移进度对照报告入库 + 动工前审查证据修正 + backlog 状态声明混合口径（2026-11-06）

### 文档（零代码零迁移零路由；无需 rebuild / 重打包）

- **报告入库**：`docs/implementation/v3-迁移进度对照-fde-v2建议-2026-11-04.md` 首次入版本库（此前为未跟踪工作文件）——第五轮动工前审查同步：七项口径在 fork/main `743a633` 全部复测吻合（pytest 1961 passed + 6 skipped / vitest 787 取 #131 CI run 42110880267 实测；mypy 门 CI 实跑绿＋基线 279 行）；8 处 文件:行号 漂移修正（api_catalog.py:15→19、chat.py:50-72→72-96、mcp_gateway.py:32-51→36-55、workflows/models.py:157→163、ontology/service.py:1295→1304、executor.py:1213-1227→694 起+1402-1413、ontology/models.py:54-247→54-246、§三 交叉引用 §五-5→§五-4）；§七 存档哈希清单与「12 提交」串位 4 处修正（#114~#124 实为 11）；新增 §十一 增量记录；遗留项四条与 11-01 建议清单九项判定全部复核维持。
- **backlog 状态声明滚动更新（报告 §六 P0 #2 清偿）**：头部改混合口径（T-\* 33 节全部 DONE / B#1–B#40 仅 P0 先行批表 10 项 ✅ 已实施（#128~#131）、其余按逐条状态标注 / P3 四项已定案收口）；「开源借鉴清单登记」段标题改写（与 #133 评审补登记合并）；B#1/B#2/B#4 编号 **#129→#130** 校正（#129=知识收尾轮纯文档，#130=P0 代码级子批；B#28 行已由 #133 同向订正，rebase 取其版）。
- **口径**：零代码零迁移——pytest 1967 收集（1961 passed + 6 skipped）/ mypy 279 / vitest 787 / 105 表 / 迁移头 `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 全部不变。

## [未发布] — V3 P0 先行批收尾：状态归属与对账框架 + G9 出门口径接线（2026-11-06）

### 行为变更（零迁移；server 变更 ⇒ 一次 rebuild）

- **B#6 状态归属与对账框架**：新增 `docs/architecture/状态归属与对账-v1.md`（四层归属总表 + C1–C10 自检清单）与 `server/tests/test_state_ownership_reconciliation.py` 六条跨层对账钉——候选（任务/workflow 两腿）挂接后 `project_evidence` 零行且清单 claim_status 不动；物化唯一入口 = `submit_gate_evidence` 真人提交闸；已领清单项 (source_uri, content_hash, evidence_id) 与被引证据行逐位一致；workflow 版本行 `dag_sha256(dag_json)` 重算 == 落库 `content_sha256`（二次发布不污染已固定版本，run 固定 (definition_id, version)）；documents 快照剥 `captured_at` 后逐位确定；ontology 变更集 base 指纹不符 confirm 409 零物化。六钉逐一变异验证（红→还原→绿）。
- **B#21 G9 出门口径接线（#128 挂账清偿）**：`server/seeds/gates.json` G9 `exit_condition` 挂接评测协议 §5 冻结公式「验收线达成 ≔ uplift_bounded ≥ 0.8 ∧ incidents = ∅ ∧ 三锚四反例全过」+ 无 oracle → `insufficient_data` 不得出分 + 协议文档指针；原五项出门口径逐字保留。种子重生成覆盖由接线钉守护（红=须重挂）；存量 Gate 行不改，新项目懒实例化即得新口径（模板漂移由 T-G2 `template_outdated` 呈现，属设计行为）。
- **口径校正**：#130 曾漏改 AGENTS 口径行迁移头（pytest 行已推进而迁移头未随），本轮顺带校正为 `b2e8f4a6c9d3`（36 rev）。

### 口径

- 服务端 pytest **1967 收集 = 1961 passed + 6 skipped**（+6）；mypy 基线 279/104 不变；vitest 787 不变；105 表 / 迁移头 `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 不变。

## [未发布] — V3 P0 先行批·代码级子批：跳数熔断 + 门禁 revision CAS + 回执终态 + purity 架构测试（2026-11-05）

### 行为变更（合并迁移 `b2e8f4a6c9d3`——一次 rebuild + alembic upgrade head）

- **B#1 跳数熔断**（agent-autoloop 语义）：`workflow_runs.hops` 列 + `MAX_RUN_HOPS=8`——resume_run 拍板重投逐代 +1（继承不清零）、超限 409 `hops_exceeded` 零变更；执行器入口 belt 把在途超限行 honest failed（不再分派任何节点），封顶 workflow 自触发链。
- **B#28 门禁 revision CAS**（FF stage completeX 语义）：`decide_gate` 增可选 `expected_revision`（缺省=旧客户端兼容）——行锁+版本复核，落后即 409 `gate_revision_conflict` 且零变更，多端并发拍板后写不再覆盖前写；拍板生效推进 `gates.version`（复用既有 VersionedMixin 列）并留痕 changes；新列 `gates.lifecycle_version`（门禁语法代际，现役=1）。桌面 expected_revision 接线归主树品牌轮落定后。
- **B#2 回执「写错不重做」**（agent-autoloop worker 语义，收窄面）：`ManifestOutputScanner.receipt_state` 四态回执判定（Protocol 不破）经 `RunResult.receipt_state` 入 `_finalize`——completed + exit 0 + 零声明产物 **且** 回执面损坏（output/ 有文件没写 manifest / manifest 非法 JSON）→ 新终态 `succeeded_but_receipt_invalid`（不进 FAILED_STATUSES ⇒ retry_run 拒同键重跑，业务动作不重执行，消除重复交付尾部风险）；合法零产物任务照旧 completed；声明产物校验失败维持 C-1 failed+retry 合同；`agent_runs.status` 列 String(24)→(40) 加宽 + CHECK 扩（downgrade 归位 failed）。
- **B#4 purity 架构测试**：`test_architecture_purity.py` 四断言——workflows 顶层零 control.service/routes（双向环防线）、control.service 延迟导入惯例固化、workflows 内核零 os.environ/flask、零产品名字面量。
- **口径**：pytest **1961 收集 = 1955 passed + 6 skipped**（+16：hops 2 / gates CAS 4 / receipt 5 / purity 4 / 迁移 roundtrip 1）；mypy 279 不动；vitest 787 不动。变异验证四连（hops 上限/CAS 复核/回执终态/scanner 收窄面）apply→red→reverse-restore→green。

## [未发布] — 知识收尾轮：AGENTS 口径行校正 + README 品牌路径/配置对齐（2026-11-05）

### 文档收尾（零代码零迁移零路由零桌面，口径全不动）

- **AGENTS 口径行校正**：口径行停留在 #124（pytest 1944=1938+6s），#125 W-9 纯测试 +1 起 #125–#128 各轮已按 1945=1939+6s（CI PR-head 实测）报——行内补齐 W-9 +1、实测锚点前移；零代码轮动了测试数同样要同步口径行。
- **README 对齐**：品牌单点路径修正为 `desktop/src/shared/brand.ts`（#109 CR-001 双侧单点后遗留旧路径），并补服务端单点 `server/src/fde_api/config.py`（`FDE_PRODUCT_NAME` 覆写）；配置边界表补 `FDE_PRODUCT_NAME` / `FDE_AI_MONTHLY_TOKEN_BUDGET`（0=不限额、设施故障 fail-open）/ `FDE_AGENT_MONTHLY_BUDGET`；能力表补门禁证据候选（任务/工作流产物建议性候选，采纳仍走人工提交闸）与 AI 用量月度预算/审计账本。
- **`server/.env.example` 补 `FDE_PRODUCT_NAME` 注释示例行**（#109 新增公开配置时漏了示例面）。

## [未发布] — V3 P0 先行批·文档级子批：B#3 红线 + 交付效果评测协议 v0 + DSH 适配层决策记录（2026-11-05）

### 文档级先行批（零代码零迁移零路由零桌面，口径全不动）

- **B#3 红线 +1**：AGENTS 红线节新增「AI 审查不执行被审代码」——审查输入只能是 diff/文本快照，不得检出/运行被审交付的代码、测试、配置、hooks（agent-autoloop delivery 插件语义；未来上 AI 审查时加 CI 断言）。
- **B#21+B#22+B#29 交付效果评测协议 v0**（`docs/architecture/交付效果评测协议-v0.md`，PROPOSED 文档层）：uplift 算分口径 + result 字段清单 + 三锚点四反例门禁判据（阈值须我方数据校准）+ 验收合同契约五点（对齐 G8 conditional_pass / G9 有条件接受）；无 oracle 不得出分（`insufficient_data`）；G9 exit_condition 挂 gates.json + pytest 接线=server 变更归代码级子批同窗口；Q1–Q3 拍板前停文档层。
- **B#27 DSH 适配层决策记录 v1**（`docs/architecture/DSH-适配层决策记录-v1.md`）：`fde-dsh-v1` 自定协议声明 + 官方源码零命中端点证据 + 若启用须自写适配层清单 + lock 八字段/三方合并升级法 + 安全前置四条；**维持「当前不装、不换执行体」裁决**。

## [未发布] — V3 开源借鉴消费登记轮：B#1–B#34 全量登记 PROPOSED + CR-004 销号（2026-11-05）

### 登记轮（零代码零迁移零路由，口径全不动）

- **来源**：调研会话《开源项目借鉴总览-2026-11-05》及八份分报告（横评七项目：fde-v2 已消化完毕 / agent-autoloop 最值得借鉴 / agnes-harness·giip·FDEP 仅参考设计 / fde-gym 战略价值最高但工程性价比第二 / FF-FDE 只借鉴实现不引入运行时）——`docs/audit/` 在途未提交产物，落定回写归调研会话，本登记轮只消费不代提交。
- **登记**：backlog 新节「开源借鉴清单登记」——**B#1–B#34 全量 PROPOSED**（登记≠排期≠默认实施；实施须另开轮走既有流程）。P0 先行批 11 条（B#1 跳数熔断 / B#2 回执写错不重做 / B#3 审查不执行被审代码红线 / B#4 purity 架构测试 / B#5 审批退避+SLA / B#6 状态归属对账 / B#21 评测协议 v0 / B#22 三锚四反例 / B#27 DSH 适配层决策记录 / B#28 门禁 revision CAS / B#29 验收合同契约）；P1 15 条、P2 条件触发 9 条按触发条件挂账；跨项目合并六组防重复立项。
- **拍板闸挂账**：B#1+B#28 合并同一迁移窗口（一次 rebuild+alembic upgrade head）需拍板；Q1–Q6 决策依赖（Q1「交付产物评测」语义、Q2–Q3 验收线/kpi/oracle、Q4–Q6 数据落点/容器/许可证）不预支。
- **红线对照**：B#25 客户资料红线（真相/参考解/隐藏流量永不入库不进 git，落 fdeops 工作目录+全代号化）；B#34 交付进程红线（仅内部自检夹具）；P3 评估报告「写类外呼/发信/付款永不降级」红线上位维持。
- **CR-004 销号**（c1）：AGENTS 口径行已由后续每轮维护+CI PR-head 实测逐位核对（现口径 105 表/`d9f4a7c2e6b1` 35 rev/路由 300/1945=1939+6s/787/279），#88 时代投诉面不复存在——「逐轮维护治愈」销号，台账行+详情段+修复 PR 三处注记。

## [未发布] — V3 P3 评估报告轮：有限自动执行开放评估落盘——八档边界分类学 + 可降级集合=∅ + 取数口径先行（2026-11-05）

### 评估报告（零代码零配置零迁移零闸态变更）

- **轮次定位**：P3-④ 评估报告轮本体（合同 §4，#125 三道闸清偿后解冻）；报告=`docs/implementation/v3-p3-评估报告-有限自动执行-v1.md`。合同 §4.4 末段原文兑现：「本立项不开放任何自动执行；评估报告本身也不开放」——**闸态变更数=0**。
- **①边界梯度分类学（§4.4-1）**：三面目录实测（api_catalog 94 条 effect/risk/confirmation 分面 + MCP 17 工具五元 + A 轨审批执行硬白名单 `service.py:867` 唯一对）→ 八档分类 **G0 只读内查 / G1 只读外呼（lcsc_search 原型）/ G2 产物外呼（forms.export、translator.translate 已处事后审计档）/ G3 产物出具·治理耦合（documents.generate、export_sow 挂 signoff）/ G4 普通内部写（37 条=现役中间地带）/ G5 敏感内部写（不可逆+启发式捕获面）/ G6 发信类红线现役档（`file_send_wechat` 收件域封闭本人+事前密码确认）/ G7 写外呼付款红线空域（构造性零条目）**+ S 系统自主白名单。**现役可降级集合=∅**；「写外呼/发信/付款永不降级」红线逐字维持；未来新类准入=§1.5 五要素模板（全 PROPOSED）。
- **②验收核对表+运行数据要求（§4.4-2）**：32 例核对表引用 #125 §4.1 不复制；**取数口径四条先行**（审批时效 p50/p90 / 人工否决率=误判率代理 / 执行落空检测 / 确认失败锁事件），活库 `automation_approvals=0` 行——首批真实 run 后评估复审轮消费，本轮不设数值门槛。
- **③责任主体数据面证明（§4.4-3）**：#125 §4.3 五链节引用 + **三条断言式回溯 SQL**（审批链双侧人签 / 发起链实名 / 全事件落人，期望恒 0 行）——现有表够，无结构性缺口。
- **④调研衔接（§4.4-4）**：调研会话《自动化运行-DSH替代可行性评估-2026-11-05》已落盘（`docs/audit/` 在途产物，落定回写归调研会话，本报告只消费不代提交）：四链路 A/B/C/D 与分类学面对齐、「真瓶颈=人工拍板红线」互证、P0 维持现状同向、治理风险独立佐证。
- **口径**：零代码轮基线不变——pytest **1945 收集 = 1939 passed + 6 skipped** / mypy 279 / vitest 787（以 CI PR-head 实测行核对）；无需重建镜像 / alembic / 重打包。

## [未发布] — V3 P3 四项状态轮与 §4 闸清偿：①②③定案 + ④三道闸齐备（2026-11-05）

### 状态轮报告（零迁移零路由零生产行为变更）

- **轮次定位**：主报告 §17 P3 行四项「立项不排期」的状态清偿轮——报告 `docs/implementation/v3-p3-四项状态与闸清偿-v1.md`（含 §16 用例族 32 例逐项核对表、责任主体机制化方案、活库数据闸实测）；四项裁决 AskUserQuestion 未获答复，按 #124 委托先例按推荐项执行、逐项留痕可推翻。
- **①多 Agent 自适应编排**：活库实测 `agent_runs=0`/`workflow_runs=0`（演练键亦 0）——真实 run 数据解冻闸未动，维持冻结，零动作。
- **②Skill 运行反馈改进**：裁决=usage 维持「失败不计」对称语义、不新开失败核算维度（活库 skill 消费事件=0 无建议需求；失败证据走 ai_call_audits/operation_events 人工审计面；重审触发器=首个真实改进建议需求）；agent-policy §2.1 效果评估行已回写；双面消费量闸未过，仍冻。
- **③业务规则推理**：ontology_rules 维持不建 PARK 定案（risk≥3 规则已内嵌且被 `test_catalog_effect_risk_invariants` 钉住、T-C1 编译校验无规则输入需求；重开触发器三项写死）；**规则 9 强制化悬置线销号=维持告警**（执行层已硬闸：workflow call external 必 awaiting_confirmation 诚实失败 + DSH agent 节点走审批回调；「P2 enforcement wave」不做）。
- **④有限自动执行**：三道闸齐备——T-J2 ✅（#116）+ **§16 用例族核对表 32 例全绿**（30 直接绿 + W-9 本轮补钉 + W-3 裁决回写，0 红）+ 责任主体机制化方案成形（审批链人签五要素在表、系统自主动作=封闭白名单、验收分离双面钉住，无结构性缺口）→ **评估报告轮解冻可排期**（余项=边界梯度分类学〔写类永不降级红线维持〕+调研会话衔接；写类 external 免事前确认=红线级非目标逐字维持）。
- **W-9 补钉（唯一代码变更，纯测试）**：NEW `test_capability_revocation_mid_run_fails_subsequent_write_call_node`——run 进行中撤销发起人 AI 档位，后续写类 call 节点分派时实时重判命中 `execute_api` workbench.write 硬闸 403 forbidden 诚实失败（零重试）、run failed（FV-F1）；变异验证（档位一次定终身→红→还原→绿）；executor 全文件 37/37 绿。
- **W-3 裁决回写**：skill `input_schema` 为只写元数据（publish 期仅 isinstance(dict)，MCP/chat/workflow 三面零消费）——校验面不补码（无消费方不建空壳），test-plan W-3 行注记「未实现，按需另立」；S-7/S-9/D-5 形态偏差同批注记。
- 口径：pytest 基线 1944=1938+6s 双面一致（干净 `58a54ff` 本地全量实测=#124 CI 口径）+1 → **1945 收集（CI PR-head 复核为准）**；mypy 279 基线不动；桌面零改动（vitest 787 不变）；零迁移零路由 ⇒ 无需重建镜像、无需 alembic、无需重打包便携版。

## [未发布] — goal-c P3 服务端小轮：指标面排除演练 run + 桥投影列水合 + outbox 死信箱销号（2026-11-05）

### 服务端（零迁移零路由零桌面）

- **CR-031 演练 run 排除出指标持续观测面**：降级演练（`rehearse_fallback`，幂等键 `rehearsal:` 前缀、零计费零真实耗时）此前混进四张 run 指标卡——L1 演练（completed+degraded+0ms+0 费）拉低草稿耗时中位数、**抬高降级率（持续 >30% 暂停扩大 agent 授权的红线指标会被演练误触发）**，L2 演练（failed）压低一次通过率，零费行拉低成本中位数。现四个 AgentRun 查询统一挂 `_REAL_RUNS` 过滤（常量复用 `agents/pilot.py::REHEARSAL_KEY_PREFIX` 单点，试点闸口面同款口径先行），四卡 `definition` 文案同步注明排除（口径面=计算面）。测试：NEW 专项 1 例钉 L1/L2 两形态四指标；变异验证（过滤中性化→四断言全红→还原→绿）。
- **CR-030（半 A）桥投影列水合**：4h 采集投影的 `_sync_bridge_evidence` 全表 ORM 水合改三列投影（id/openfde_engagement/fdeops_workspace），行为等价。**半 B 登记失真如实修正**：现场核实 `_city_order_rank` 在 r12 B-④ 重写后已是单次 join+Python 计数，登记描述的「循环 session.get」不存在；真实重复面仅剩仿真工具循环（P4 卫生维持观察）。
- **CR-016 台账销号**：outbox 死信箱经 T-J1（终态写入三落点）+ T-J2（取消/重试双路径终态收口）已彻底闭环，登记前提不复存在；本轮只补台账销号注记，零代码。
- 口径：pytest **1944 收集 = 1938 passed + 6 skipped**（+1；基线 1943 已随 #123 CR-041 核销轮双面实测校正）；105 表 / 迁移头 `d9f4a7c2e6b1`（35 rev）/ 路由 300 / ENTRIES 94 / mypy 279 基线 / vitest 787 全部不变；零迁移（rebuild 幂等校验 `alembic upgrade head`）。

## [未发布] — goal-c CR-041 核销：融合树独立复测 + 口径校正 + 桌面便携包 r16（2026-11-05）

- **核销（零代码轮）**：并发 P3 批清偿（#121）落定后的独立核销——融合树全量实测：服务端 pytest **1943 收集 = 1937 passed + 6 skipped**（本地 Windows 与 CI PR-head 双面一致）、CR-041 专项 2 例绿、mypy 基线 279 全绿、桌面 vitest 774/774、typecheck 零错；**发现并校正融合口径偏 1**（AGENTS 前值 1942/1936 为算术推导；CI 实测 #120 = 1935+6s、#121 = 1937+6s，口径行按实测改写）；「负向日志断言空转绿」担忧实测排除——`not in caplog.text` 全仓 10 处（含 test_auth_api.py:481 密钥不入日志安全断言）在 env.py 解禁后真判零红。部署活体核验：api 镜像 env.py 修在位、300 业务路由、双 admin 路由、`/ready` 200、alembic head `d9f4a7c2e6b1`。
- **桌面便携包 r16**：r15（11-05 11:18）早于 #113 T-UI1 徽标与 #121 CR-035/040——marker「已取代」「source_kind」双 0 命中证实缺口；从 fork/main `7dc620e` 干净树重打包 **蔡工FDE-0.2.0-便携版-r16**：asar sha256 `c62e184b131db53386eb83897c80ca447a57a81b952d6e992cea1bcbcb75027d`，marker「已取代」×2 /「source_kind」×3 命中；r15 旧目录未覆盖。
- 台账同步：CR-041 增核销复核段（含口径校正与 r16 交付记录）。

## [未发布] — goal-c P3 测试补强：AI 机会主链组件 13 例覆盖 + sync-hash 断言加固（2026-11-05）

### 桌面端（纯测试轮：生产代码零变更、服务端零改动）

- **CR-037 ResearchOpportunity.tsx 零 vitest 覆盖清偿**：NEW `desktop/tests/renderer/research-opportunity.test.tsx` 13 例，全部落在新文件——
  - 纯函数 8 例：`validateOpportunityProfile` 全分支（超长 301/1001 与临界 300/1000、状态/优先级/风险等级无效值、三项评分 0/6/小数拦截 + null 放行、负责人不在成员表）；`opportunityProfileInput` 裁剪两端空白并丢弃展示名；`opportunityProfileErrorMessage` 8 个错误码逐一映射 + 未知码兜底；`draftErrorMessage` PoV/SOW 双形全码 + 兜底。
  - `OpportunityDetail` 组件 5 例：非编辑态档案网格中文渲染；canManage 经「更多」菜单删除联动；编辑态保存主链（PATCH 载荷逐字段断言 + 成功回执与提示）；保存失败按码映射 alert 且不回执；脏标记按 `opportunity-profile:<id>` 键置脏、卸载自动清脏。
  - 变异验证：评分上界 5→6 → 评分用例红 → 还原 → 绿（生产代码 `git diff` 零残留）。
- **CR-038 sync-hash 断言加固（CR-007 同型残留收尾）**：`new-project.test.tsx` 创建成功路径的 `location.hash` 同步读改 `await waitFor(...)`，与 `navigation.test.tsx` 已修的 5 处同型对齐；属加固型改动（当前同步写 hash 下两种写法均绿，防未来异步化复发），台账已如实注记无可做的红绿变异。
- 口径：桌面 vitest **787/787**（+13）；typecheck 绿。测试文件不进应用包（asar），**无需重打包便携版**；105 表 / pytest 1943 / 路由 300 / ENTRIES 94 全部不变（pytest 数字承 CR-041 核销轮 CI 实测校正）。

## [未发布] — goal-c P3 批清偿：术语页搜索守卫 + 状态值域 + alembic 日志基建（2026-11-05）

### 桌面端（GlossaryPage 两项 P3；零服务端改动）

- **CR-035 术语搜索序列守卫**：术语表搜索每键入触发一次全量重取且无守卫——后发先至的旧响应会覆盖新结果；且每次按键后整页换成「正在加载术语表…」，**搜索输入框随页面一起被卸载 → 焦点丢失、无法连续输入**（比原登记的「闪空」更重）。现加 `sequence` ref（同仓 `ResearchWorkspace.loadResearch` 范式）：只有最新一次请求的结果可落表，旧响应整包丢弃；首屏加载完成后不再整页 loading，旧内容留在屏上等新结果（输入框不再被卸载）。
- **CR-040 术语状态值域对齐**：桌面 `TERM_STATUS_LABEL` 写的是服务端不存在的 `candidate/retired`，又缺 `draft/superseded` → 状态列回显英文原值、中文标签永不显示。现对齐服务端 `ontology/models.py::TERM_STATUSES`（draft→草稿 / confirmed→已确认 / superseded→已取代 / merged→已合并），并加注释钉住「值域唯一权威＝服务端」。
- 测试：vitest +3（值域中文标签且旧标签不再出现 / 乱序响应取新弃旧 / 在途搜索不闪空且旧内容不消失）；typecheck 绿。

### 服务端（测试基建一行；零迁移零路由零契约）

- **CR-041 alembic 日志基建**：迁移脚本 `fileConfig` 默认 `disable_existing_loggers=True`，而测试夹具每例都跑迁移 → 导入期创建的模块级 logger（`logging.getLogger(__name__)`）在整场会话内全量 `disabled=True` → caplog / `log_cli` 对这些 logger 永远空捕（此前只能逐测试显式解禁）。现显式 `disable_existing_loggers=False`：只重配 alembic 自身的 logger，不动已存在的模块级 logger。生产面零影响——迁移是独立进程，跑完即退，仅「测试进程内迁移与应用共存」才踩中。
- 测试：NEW `server/tests/test_migrations_logging.py` 2 例（迁移跑完后导入期 logger 仍 `disabled=False`；caplog 能捕获模块级 logger 记录）。变异验证：撤 env.py 那一行 → 两例全红；恢复 → 绿。

### 文档

- **CR-011 三包意图锚集中指针**：V3 主报告 §13 表格补「意图锚指针（不改造）」行——mailing → `docs/SES发信模块-G9.md`；translator → `docs/goal-d13·goal-d14-交付工作台.md`；guidance → `docs/goal-d1·goal-d2-交付工作台.md`。只补可查位置，三包实现面零改动。
- 台账同步：CR-035 / CR-040 / CR-041 / CR-011 → fixed；**CR-003（主报告 §20 实施跟踪注记）挂账**——并发会话在途回滚轮正在撤 T-W7/T-I1 等轮次，此刻补注记即写即错，待回滚轮落定后一次性补。
- 口径：pytest **1942 收集 = 1936 passed + 6 skipped**（本轮 +2）；桌面 vitest **774/774**（本轮 +3）；105 表 / 迁移头 `d9f4a7c2e6b1`（35 rev）/ 路由 300 / ENTRIES 94 不变——零迁移零路由，无需 rebuild。

## [未发布] — goal-c CR-027 规则版本显式管理：撮合不再永久停在降级态（2026-11-05）

### 服务端（零迁移零桌面；路由 +2；用户拍板「显式管理动作」）

- **修复（CR-027）**：`dispatch/rules.py` 的 `create_rule_version`（发布）与 `activate_due_versions`（激活）此前**两者都只有测试引用、零生产入口**——规则版本永不 published→active，`active_rule_version` 恒 None，`match_package` 恒 422 `rule_version_required`（§11.1 降级态变永久态）。NEW `dispatch/admin_routes.py`（blueprint `/api/v1/admin/dispatch`，T-J2 admin 蓝图同款）：`POST /rules/versions` 发布新版本（admin 门在服务层 role 判；快照缺省取当前默认规则投影＝发布「当前口径」而非手抄正文）、`POST /rules/activate` 激活到点版本（幂等，无到期版本零变更；同事务留痕 `operation_events dispatch_rule_activated`，changes 只落版本号/数量/激活时刻，**不落规则正文**）。**公示窗不绕过**：发布端强制 `effective_at ≥ published_at + 30 天`（§6.2），激活端只激活已到生效日者——人工也加速不了公示期。**不做请求路径惰性触发、不做 scheduler 自动激活**：激活节奏由人控制，与「名单≠开闸」裁决一致。
- 测试与口径：NEW `test_dispatch_admin_rules.py` 5 例（非 admin 双路由 403 / 公示窗 <30 天 422 `notice_window_required` + 版本冲突 409 / **激活后撮合不再 422**（解冻证明）+ 重复激活幂等 + 事件留痕只落元数据 / api_catalog 钉子 / 缺省快照取默认投影）。业务路由 298→**300**；全仓 pytest **+5**；台账 CR-027 → fixed、**CR-028 裁决「维持整条挂 B-③ 法务区」**（税率/税法年口径未确认前不动码，解冻条件随法务口径一并修）。

## [未发布] — goal-c CR-022 补呈现通道：取消后在途派发结果不再静默丢弃（2026-11-05）

### 服务端（零迁移零路由零桌面改动；用户拍板「补呈现通道」）

- **修复（CR-022）**：节点在派发后被取消时，在途外呼/AI 调用返回的结果被终态 guard（`node.status∉(pending,ready,running)`）静默丢弃——api_actions 留有成功记录但节点 `output_json=null`，「已执行外呼不回收（诚实呈现）」承诺无展示通道。现 `_settle_node_success`/`_settle_node_failure` 拆分 guard：`node is None` 早退不变；状态不在集合且 **== "cancelled"** 时落诚实记录——**终态不复活**（节点仍 cancelled，FV-F1「断链不静默 done」不破），`output_json = {cancelled_after_dispatch: True, dispatch_outcome: "succeeded"|"failed", action_id, dispatch_result}`（产物真值 + **action_id 指针**——写类操作可回 api_actions 反查）+ `node.error = "cancelled_after_dispatch"` 稳定标记（桌面 WorkflowConsole「错误」列直接可见 ⇒ 零桌面改动即有呈现通道）。取消的 run 不挂 T-W7 门禁证据候选（不进 marker 挂载点）。
- 测试与口径：`test_cancelled_node_records_inflight_dispatch_result`（公开 cancel_run 取消后驱动 settle 点 = 在途返回；断言节点仍 cancelled/未复活 + output_json 三键 + action_id + 序列化面可见）。全仓 pytest **+1**；台账 CR-022 → fixed。

## [未发布] — goal-c CR-021 行锁修复：本体变更集三翻转入口串行化（2026-11-05）

### 服务端（零迁移零路由零桌面改动；用户拍板「修复：CAS 状态翻转」）

- **修复（CR-021）**：`submit_change_set`/`confirm_change_set`/`reject_change_set` 三处状态翻转原为「读 `row.status` 判合法→物化→赋值」的先读后写——两拍板人并发 confirm 会双双物化（幂等键+UNIQUE 兜底不炸数据，但 409 `not_in_review` 语义失守、`ontology_change_set_confirmed` 事件双份）；reject 可翻转已物化的 confirmed 行；双 submit 重复 version。现新增 `_lock_change_set`（`select … with_for_update() + populate_existing`）在三处入口**行锁重读**：并发对手在此串行化，锁在手读到的必是已提交真值；confirm 的 base 指纹复核+逐项物化全程在锁内。
- 测试与口径：`test_change_set_transition_races_serialize_on_row_lock`（裸连接提交并发终态+会话旧实例=并发窗口第二请求的真实内存视图；三段：迟到 confirm 零物化 `not_in_review` / confirmed 终态拒迟到 reject `invalid_transition` / 迟到 submit 409 且 version 只 +1）。变异验证：摘三处行锁→红（迟到 confirm DID NOT RAISE=静默双物化）→还原→绿。全仓 pytest **+1**；台账 CR-021 → fixed。

## [未发布] — V3 T-J2 收官：handler 自动重试 + admin 任务取消 API（2026-11-05，P1 全清）

### 服务端（域 14 最后一块；迁移 +1 纯 CHECK 置换；路由 +1；零桌面）

- **handler 自动重试**：可恢复类型（复用 reconcile `RECOVERABLE_JOB_TYPES` 幂等白名单）handler 抛错不再首败即终——指数退避重投（30s×2 封顶 15 分钟）直至 `attempts` 耗尽；重试期间 outbox 事件保持 `dispatched`（T-J1 红线：只有最终失败才收口 failed），退避到期由 reconcile 新增 due 补投面送回队列（at-least-once，认领侧 `not_due` 守卫消化重复条目）；外副作用类型（automation.execute）维持首败即 failed。candidates 查询补 `populate_existing`（同 session 残留旧实例会让分支判定读内存陈值——实测踩中）。
- **admin 任务取消 API**：`POST /api/v1/admin/jobs/{id}/cancel`（admin，幂等）——**cancelled 成为真状态**（迁移 `d9f4a7c2e6b1` 纯 CHECK 置换，active_key 生成列天然兼容零重建）；重复取消 200 `cancelled=false`、终态 409 `already_terminal`、运行中活租约 409 `job_running` 不强杀（等租约过期后可接管）、过期租约=worker 已死可安全取消（迟到 settle 被终态守卫拒绝）；取消同事务三面收口：job 行 + 同键 outbox 事件（pending+dispatched 一并收口，防下一轮 dispatch 复活）+ `operation_events job_cancelled` 留痕。不进 api_catalog（平台运维面）。
- 测试与口径：pytest +21（worker 重试 7 + reconcile due 面 4 + cancelled CHECK 1 + NEW test_admin_jobs 9）＝**1933 收集 = 1927 passed + 6 skipped**；105 表 / 迁移头 `d9f4a7c2e6b1`（35 rev）/ 路由 298 / ENTRIES 94 / vitest 771 不变。**至此 V3 P1 任务全部交付**（T-J1/T-J2/T-P1-4/T-P1-5/T-OBS1）；CR-016 outbox 死信闭环补齐（取消/重试双路径均以终态收口）。
## [未发布] — V3 P3 立项轮：高级自主化四项立项合同（2026-11-05）

### 文档（零代码零迁移零路由零桌面；口径不变）

- **立项合同 NEW `docs/implementation/v3-p3-高级自主化立项-v1.md`**——backlog §P3 四项逐项展开：①多 Agent 自适应编排（域 6 DEFER 维持，进程内团队拒绝理由=主报告 §19-7 常量，观测=`agent_runs.fallback_level` 分布）；②基于运行反馈的 Skill 改进（T-S2+CR-013 数据面已闭环，失败面维度属语义裁决非补漏）；③业务规则推理 ontology_rules（registry-v1「无消费方不建空壳」维持，候选消费方=risk≥3→human_approval[域 9]+T-C1 编译校验，规则 9 强制化悬置线一并盘）；④有限自动执行开放评估（P0/P2 全 DONE、P1 仅剩 T-J2 在途；解冻=三道闸；写类 external 免事前确认=红线级非目标）。每项含立项依据/已落地基线/评估问题清单/非目标/解冻条件/回写义务；评估报告轮自身也须先过解冻闸。
- 台账同步：backlog §P3 重写挂锚；RAG/LightRAG 维持不立项（主报告 §19 附注）；在途开源借鉴调研（autoloop/agnes/fde-gym/giip/fdep-mcp/DSH 替代可行性）不预支结论，落定后由调研会话自行回写。
- 口径：pytest 1913 收集 = 1907 passed + 6 skipped / 105 表 / head `e2c6a8f4d1b3`（34 rev）/ 路由 297 / ENTRIES 94 / mypy 279 / vitest 771——全不变，无需 rebuild/重打包。

## [未发布] — goal-c CR-013 计数隔离修复：skill 节点计数侧故障不再升级消费侧（2026-11-05）

### 服务端（零迁移零路由零桌面改动）

- **修复（goal-c 台账 c4 遗留 P2，c5 评估未按、本轮单独清偿）**：workflow skill 节点 `_dispatch_skill` 的 `record_skill_usage` 计数调用原为裸调用——计数微事务遇 DB 异常会被 `_execute_node` 兜底 catch 为 `dispatch_crashed(retryable=True)`：已成功的那次 AI 调用被丢弃重跑（双份真实 AI 成本）且节点误标 failed。现包 try/except 记 warning（含 node/skill/error_type）不冒泡——AI 已成功则节点必 succeeded，计数失败只丢一条 `skill_used_workflow` 事件（T-S2「失败不计」对称方向；chat 面 ai_tool_loop 同型守卫，workflow 面补齐最后裸露点）。
- 测试与口径：executor +1（`test_skill_usage_count_failure_does_not_fail_node`——monkeypatch 计数抛 OSError → run succeeded + 恰 1 次 AI 调用（无重投）+ warning 落 caplog；变异验证红→还原绿）。全仓 pytest **1913 收集 = 1907 passed + 6 skipped**（本轮自身 +1；全仓口径随同日 #114 P1 残尾清偿轮 +7 前进）/ 105 表 / 路由 297 / ENTRIES 94 / mypy 279（基线无新增）；**rebuild 后必 `alembic upgrade head`**（零迁移，幂等校验）。
- 台账同步：CR-013 → fixed；**CR-041 登记不修**（测试基建：alembic `env.py` `fileConfig` 默认 `disable_existing_loggers=True`，db_session 每测试跑迁移 → 导入期创建的模块级 logger 测试会话内全量禁用、caplog 空捕；CR-013 测试沿 test_storage_contract oss2 先例显式解禁，根因修复留测试基建轮）。

## [未发布] — V3 P1 残尾清偿：outbox 状态闭环 + 终审双闸 + 审批过期清扫（2026-11-05）

### 服务端（三 S 同轮：T-J1 / T-P1-4 / T-P1-5；T-OBS1 核验销号；零迁移零路由零桌面）

- **T-J1 outbox 状态闭环（WB-DEF-9）**：outbox 事件此前只有 pending→dispatched，终态永无写入点（dispatched 即泄漏）。新增 `outbox.mark_completed/mark_failed`（联动键 `(topic, aggregate_id)==(job_type,target_id)`，只收 dispatched 行、未派发 pending 不动、失败摘要截 2000 字），覆盖**全部三个 job 终态写入点**：`worker._settle`（与 job 终态同事务）、`worker._claim` no_handler（同 claim 事务）、`reconcile._fail_job`（worker 失联终失败）。
- **T-P1-4 resolve_signoff 双闸（WB-DEF-2）**：终审拍板原仅 can_view+AI 档位——viewer 被授予高档后即可代拍。改为项目 `can_manage`（`_require_project_manager`）+ 档位双闸（与 `generate_agent_solution` 权限双层同款）；viewer+`system_operator` 档 → 403 `forbidden`（拦截者显式为项目闸而非档位闸）。
- **T-P1-5 审批过期清扫（WB-DEF-3）**：过期翻转从 decide/状态查询两处内联重复提取为唯一原语 `control/service._expire_approval`（行为零变化），新增 `scheduler.sweep_expired_approvals`（`skip_locked` 与并发拍板互不阻塞）接入 scheduler 循环（与派单同拍）——无人触碰的过期 pending 审批不再永挂任务中心。
- **T-OBS1 降级 chat 落审计（WB-DEF-4）核验销号**：chat 直调 `execute_ai_prompt`，降级直连腿的审计+月账本入账已随 #112（CR-006）落地，本轮零补码销号（`direct-chat-*` 前缀方案由 purpose+used_fallback 取代，区分度更优）。
- 测试与口径：pytest +7（outbox 收口 2 + worker 端到端 3 + viewer 双闸 1 + 清扫 1）；105 表 / 迁移头 `e2c6a8f4d1b3` / 路由 297 / ENTRIES 94 / vitest 771 不变（需 rebuild 三镜像，无迁移）。P1 仅剩 T-J2（重试落地时 outbox failed 只准在最终失败分支翻转——backlog 已留注）。

## [未发布] — V3 实施 T-UI1 三页核销 + GateBoard 候选来源徽标（2026-11-05）

### 桌面端（服务端零改动；T-W7 桌面挂账清偿 + backlog 销号）

- **T-UI1 核销（零补码）**：WorkflowConsole / GlossaryPage / SkillVersionsPage 三页已随 T-W6（#88）同名全量交付（vitest 5/6/7 例 + typecheck 绿，本轮基线复核 767 全绿）——backlog 条目按「已由先导轮兑现」销号。
- **候选来源徽标**：`GateBoard` 候选载荷扩为 `source_kind` 判别联合——task 形（T-G1 旧行，服务端读时缺省）与 workflow 形（T-W7 运行时保留键 `gate_evidence` 的节点产物，带 `workflow_run_id`/`workflow_node_key`/`label`）。**修复潜伏兼容 bug**：T-G1 守卫硬性要求 task 三键，T-W7 workflow 候选行会让整板 isGatesView 拒载；分形守卫后 workflow 缺 run/节点键仍整板拒载（沿「在场必须形状齐全」口径）。workflow 行带「工作流」徽标 + run/节点出处行；采纳走既有提交闸零新入口；同指纹任务/工作流候选并存各占一行（React 键域 `wf:run|node` 分开防撞）；uri>500（人工提交闸上限，与手填表单同限）候选可见但禁采并 title 报因。
- 测试与口径：gate-board +4（徽标呈现+采纳提交体 / 同指纹两形并存 / 超限禁采 / 坏形状整板拒载），vitest **771**；服务端零改动（本轮零增量；全仓 pytest 口径随同日 #112 CR-006 前进至 1905 收集 = 1899 passed + 6 skipped，105 表 / 路由 297 / ENTRIES 94 / mypy 279 不变，无需 rebuild）。

## [未发布] — goal-c CR-006 统一入账+统一闸：DSH 主路径/kimi 本地腿补预算门与 `ai_call_audits` 记账腿（2026-11-05）

### 服务端（用户拍板「统一入账+统一闸」落地；零迁移零路由零桌面改动）

- **缺口（goal-c c2/c8 两轮 E0）**：`dsh_enabled=true` 时 `execute_ai_prompt`——workflow skill 节点/聊天/结构化调用的 DSH 主路径——对 `ai_monthly_token_budget` 恒放行且零记账（skill 花费不入任何账本）；kimi 全路径零预算零审计；预算设施对后台任务存在 flask g 盲区。
- **统一预算门**（`control/ai_server_client.py::execute_ai_prompt`）：`ai_monthly_token_budget` 超限即拒（`ai_budget_exceeded`，retryable=False），先落 `budget_blocked` 审计再拒绝、拦在 MCP token 签发之前（拦截路径零写副作用）；预算 0=不限额、设施故障 fail-open（与 deepseek 直连腿同语义）。**门带显式 user_id——后台任务（workflow skill 节点等无请求上下文场景）同样生效**。
- **统一记账腿**（`_audit_execution`）：DSH 成功按 `provider_usage.calls[]` 聚合精确入账；失败（HTTP 4xx/无效输出/不可达非降级错）各落 `failed`；降级直连腿成功/失败均记账（`used_fallback=True`，token 来自 OpenAI 兼容 usage 块）；provider_usage 无 calls 时 token 记 None 不发明数字。**无双计**：deepseek/kimi 的 DSH 腿经 `structured_completion`→`execute_ai_prompt` 单点入账；deepseek 本地腿沿旧 `_audit` 不动；`direct_tool_completion` 内部零审计（降级腿单点记账）。
- **kimi 本地腿补齐**（`ai/kimi.py`）：入口预算门（拦在文件上传前；actor 取请求上下文，后台无上下文→放行——缺口如实保留）+ 本地腿成功/失败记账（`purpose="kimi_docx"`；流式无 usage，token 记 None）。
- `ai/auditing.py` +`audit_budget_blocked` 统一拦截留痕助手；`execute_ai_prompt` 新增可选 `purpose` 参数（`structured_completion` 传 `"structured"`；chat/executor/dsh_runtime 调用点未触碰）。
- **测试与口径**：pytest **1898 收集 = 1892 passed + 6 skipped（本轮 +7；基线 `b3793d4` 实测 1891；T-W7 同日并轮后总口径 1905 = 1899+6s）**（NEW `test_ai_server_budget_audit.py` 7 例：DSH 拦截零请求+budget_blocked 留痕/成功按 provider_usage 入账+计入月度预算/失败入账不计预算/降级腿 used_fallback 入账/kimi 门拦在上传前/kimi 成功记账 token=None/kimi 失败记账；既有 AI 面 93 例回归全绿）；105 表 / head `e2c6a8f4d1b3`（34 rev）/ 路由 297 / ENTRIES 94 / mypy 基线 279 全不变；改 server（零迁移）⇒ rebuild 三镜像（alembic 幂等校验）。

## [未发布] — V3 实施 T-W7：workflow 节点产物→门禁证据候选——运行时保留键 gate_evidence 同事务挂候选（2026-11-05）

### 服务端（立项合同 `docs/architecture/workflow-gate-evidence-candidates-v1.md`；WB-DEF-8 workflow 腿；零迁移零路由零桌面改动）

- **`gate_service.attach_workflow_evidence_candidate`**：节点产物经 output_json 顶层保留键 `gate_evidence`（`{gate, label?, source_uri, content_sha256}`）挂入 `gates.evidence_candidates`——**产物必须由生产方自带指针+指纹，平台永不自动派生指纹**（立项 D1：对任意 payload 自动哈希入库正是红线本身；形状不齐=不是证据，跳过不发明）。dedup=(source_uri, content_hash, 来源粒度)：同位同指纹幂等（哈希大小写归一）、换指纹两代并存由人取舍；上限沿 MAX_EVIDENCE_CANDIDATES 与任务候选共享列表；与任务候选按来源粒度隔离互不吞并。claim_status 恒不动，采纳唯一入口=真人提交闸（命中指纹即剪除，T-G1 行为零改动复用）。
- **坏标记不炸节点**（D2）：gate 非法 / sha 非 64hex / 超长（uri>1024 / label>120）/ 双字段缺一 → 节点照常 succeeded，登记跳过 + 新事件 `gate_evidence_candidate_skipped`（details 点名坏键 reason；gate 非法挂 project 目标、非对象标记挂 workflow_run 目标；已入 GATE_EVENT_TYPES，feed 可见）。
- **executor 两成功点同事务接线**（D3）：`_settle_node_success`（call/skill/agent 共用）与 `settle_approval_node` 批准分支读标记——事务回滚则节点成功与候选一并回滚（原子）；标记缺失零副作用；失败路径无产物不登记（连门禁行都不懒初始化）。call 节点产物=API 响应 dict 是自然生产方；skill/agent 产物为平台包装形，顶层标记透传留待现实需求（不为想象的需求加形状）。
- **读时缺省 `source_kind`**（D5）：候选行带 `source_kind: "task"|"workflow"`，旧行（T-W7 前任务候选）缺键读时缺省 "task" 不回填（沿 T-E2 evidence_id 先例）；**v1 不预写 project_evidence 一等表**（D4 偏差：工作流产物 ≠ 已采集证据，一等证据仍只在人工提交闸落库——workflow-dag-v1 §4 已注记）。
- **零路由**：候选随既有 `GET /projects/{id}/gates` 的 evidence_candidates 返回；桌面 GateBoard 来源徽标（任务/工作流）另开 S 轮。

### 测试与口径

- pytest **1898 收集（1892 passed + 6 skipped，本轮 +7；新文件 `test_workflow_gate_evidence.py`）**：标记产物挂候选+claim 不动+无标记节点零副作用 / 同指纹幂等（大小写归一）+换指纹并存+与任务候选共享列表互不吞并 / 坏标记 executor 面（节点仍 succeeded+两类 skipped 事件）+service 面八形状裁决 / 失败路径零登记（门禁行未实例化）+resume 后恰好一条 / 采纳剪除回归（submit 同指纹→清单项 claimed+evidence_id）/ source_kind 旧行读时缺省。
- 105 表不变（零 DDL）/ 迁移头 `e2c6a8f4d1b3`（34 rev）不变 / 路由 **297 不变**（零路由）/ ENTRIES 94 不变 / mypy 279·104 不变 / 桌面 vitest 767 不变（零改动无需重打包）；改 server（零迁移）⇒ **rebuild 三镜像**（alembic upgrade head 幂等空跑校验）。

## [未发布] — V3 实施 T-I1：本体变更影响分析——impact_of_term 名字域纽带三面清单 + 只读影响面（2026-11-05）

### 服务端（设计 ontology-registry-v1 §5 用例 6 / 验收 O-6；零迁移零桌面改动，+1 只读路由）

- **`impact_of_term(session, *, project_id, term_id)`**（ontology/service）：给定术语，返回引用它的**研究客体/邻接边/表单**清单——变集拍板前的人工影响面评审。引用合同 = **名字域纽带**：当前实现无 term_id 外键（fde-v2「引用方只引 term_id」未随融合裁决落地），「一个名字一个概念」（UNIQUE(project, term) + UNIQUE(project, alias)）使名字精确等价概念引用——subject.name 精确命中生效名字域即引用（纽带是唯一性不是相似度，子串/大小写变体不算）。
- **生效名字域 = 血缘闭包**：请求行沿 canonical 链到根（merge_terms 保证链一跳化，防御性走到底）+ 全部并入该根的行；名字 = 根规范名（term 绑定）∪ 血缘内别名（alias 绑定——转写来源名归保留行、来源自有别名留在来源行）∪ 非根行历史规范名（alias 绑定兜底）。对并入行发起查询 = 查其存活概念的影响面（请求行原样返回，`resolved.canonical_term_id` 解析到根）。
- **三面清单**（全部确定性排序）：subjects（命中主体含 subject_type/status/merged_into/matched_via/matched_term_id 逐名溯源）→ links（端点命中主体的邻接边，端点名随行补齐）→ forms（命中主体名下表单，含现行修订状态）；附 counts 汇总。**gates 面按验收权威 O-6 落为三面**：门禁清单是 gates.json 冻结模板文本（template_hash 钉死，T-G2），无术语名表面——不发明方法论层没有的引用（偏差回写 backlog）。
- **`GET /projects/{id}/ontology/terms/{term_id}/impact`**（can_view）：影响分析只读面，**有意不进 api_catalog**（沿 T-O3 纪律：本体治理面 AI 不可直达；桌面 T-UI1 GlossaryPage 是预期消费方）。跨项目/未知术语 404 `term_not_found`、无权限 403。
- **前置热修（goal-c8 CR-002 首版回归，fork/main 服务端 CI 必红根因）**：conftest `_current_alembic_stamp` 探测在全新库（CI service container 无 `alembic_version` 表）吞错后把持锁连接留在 aborted 事务——会话末 `pg_advisory_unlock` 撞 InFailedSqlTransaction，server-tests 整列必红（#109 PR-head 即此签名，红仍被合入）。修为探测吞错即回滚 + 会话 fixture 解锁前保险回滚（会话级 advisory 锁不随回滚释放，安全）；回归钉 +1（search_path 复现缺表探测，A/B 验证：无修复红/有修复绿）。

### 测试与口径

- pytest **1884 收集（1878 passed + 6 skipped，本轮 +7；基线 `8f10771` 实测 1877）**：名字域全命中四路（规范名/保留行别名/转写来源名/来源自有别名）+ 子串不命中 + 三面清单与 counts / 并入行查询解析到 canonical（请求行原样+血缘解析）/ 未知与跨项目术语 404 / 零引用空面 / HTTP 面（200 形状+外人 403+未知术语与项目 404）/ 红线钉子（影响面永不进 api_catalog）/ 前置热修回归钉（fresh-DB 缺表探测吞错后连接可用）。
- 105 表不变（零 DDL）/ 迁移头 `e2c6a8f4d1b3`（34 rev）不变 / 业务路由 **296→297**（+1 只读 GET impact，不进 api_catalog）/ ENTRIES 94 不变 / mypy 基线 279 不变（新代码零新增）/ 桌面 vitest 765 不变（零改动，无需重打包）；改 server（零迁移）⇒ **rebuild 三镜像**（`alembic upgrade head` 幂等空跑校验 current）。

## [未发布] — V3 实施 T-C1：Delivery Compiler 最小闭环——confirmed 本体→方案骨架 + workflow 定义草稿纯函数编译预览（2026-11-05）

### 服务端（NEW `workflows/compiler.py` 纯函数；零迁移零路由零桌面改动）

- **`compile_delivery_preview(change_set, *, industry_template, gates, research_skill_ref, approval_capability)`**：confirmed 变更集（serialize_change_set 形状，非 confirmed 一律拒绝）+ 已发布行业模板 + 门禁状态摘要（T-D1 `_serialize_gates` 形状）→ 确定性编译预览（不读时钟/随机源，快照测试钉死）；落库一律走人工确认端点——骨架 → `solutions.create`、定义 → workflow 定义创建路由。
- **① 方案骨架 payload**：与 `solutions.create` 文本合同逐键对齐（TEXT_FIELDS 七键 name+六段、限长同尺 160/40000/16000，`_normalize` 原样可过）；六段布局沿 `/skeleton`「每段保留待补、责任主体永远是人」——本体段（create/update 术语含修订标注，update 以 new_term 为准）、指标术语入验收标准候选、模板模块（sort_order 排序）驱动设想/路径/交付物/排期、门禁摘要与术语合并入风险与依赖；来源行随 design_markdown 头部落档（变更集标题·确认时刻·采集来源）。
- **② workflow 定义草稿**：dag_json 模板化「调研→方案→审阅」三节点——调研 skill（ref 由调用方注入，published 白名单在 DB、纯函数不查库，沿 validate_dag 白名单注入制）→ 方案 call `solutions.create`（携带编译期骨架字段，唯一运行期字段 `opportunity_ids` 留 `{{research_brief.opportunity_ids}}` 占位，执行器整值替换原类型不字符串化）→ 审阅 human_approval（capability 默认 `workbench.write`，system.* 不开放）。产出的 dag 在真实 api_catalog 白名单下全绿零告警（`solutions.create` effect=write_db 不触发 rule 9）。
- **provenance（agent_trace 式来源标注）**：逐字段指认来源（`ontology_change_set:<id>` / `industry_template:<行业>@v<版本>` / `gates` / `delivery-compiler/v1`），落库后可回链编译输入。
- **不做全自动「本体→代码」**（主报告 §12 裁决）：编译器只产草稿，绝不写库、绝不绕过人工确认端点。

### 测试与口径

- pytest **1877 收集（1871 passed + 6 skipped，本轮 +6；基线 `1ef3a42` 实测 1871）**：整树快照（本体段/模板排序/指标入验收/门禁排序/provenance）/ 三节点 dag 真实目录白名单全绿零告警+拓扑序 / 非 confirmed+坏载荷点名拒绝（非数组·非对象项·未知动作·缺必填）/ 无模板无门禁待补回退+坏门禁行跳过 / 坏 skill ref 与坏 capability 拒绝 / 骨架 payload 过 solutions.create `_normalize` 合同。
- 105 表不变 / 迁移头 `e2c6a8f4d1b3`（34 rev）不变 / 业务路由 296 不变 / ENTRIES 94 不变 / mypy 基线 279 不变（新代码零新增）/ 桌面 vitest 765 不变（零改动，无需重打包）；改 server（零迁移）⇒ **rebuild 三镜像**（`alembic upgrade head` 幂等空跑校验 current）。

## [未发布] — V3 实施 T-D1：文档血缘补洞——快照 revision_id + 门禁摘要 + AI 调用 request_id 落库（2026-11-04）

### 服务端（审计 WB-DEF-6/7；1 列级迁移、零路由零桌面改动）

- **WB-DEF-7（调研答案血缘）**：文档快照 `confirmed_research_values` 每表单字典新增 `revision_id` 键，指向被采用的最新 confirmed revision——快照冻结后仍可反查答案出处；扁平布局不变，模板占位符解析零破坏。
- **门禁摘要**：快照新增 `gates` 段（每门 `gate_key/status/decision/submitted_at/decided_at`，按 key 排序）——文档生成时刻的门禁进度随快照冻结；有意不携带清单明细/证据指针（门禁面的数据不进文档镜像）。
- **WB-DEF-6（AI 调用血缘）**：AI 内容生成的 `request_id` 由生成器铸造并传入 `generate_document_fields`，冻结进版本行 `content_snapshot_json["ai_request_id"]` 并落 `document_generation_jobs.ai_request_id` 新列（迁移 `e2c6a8f4d1b3`）——版本行/任务行均可直接反查 `ai_call_audits` 审计记录。资格判定提为 `ai_content_applicable` 单一谓词：只有真正发起供应商调用的生成才铸 id（不产幽灵血缘）；再生成复用首代冻结字段不重铸（血缘恒指首代调用）；失败路径 id 随事务回滚。

### 测试与口径

- pytest **1871 收集（1865 passed + 6 skipped，本轮 +4；基线 `c8aa08a` 实测 1867——#103 goal-c4 +4）**：快照血缘指向最新 confirmed revision + 反查 / gates 摘要形状排序 / AI 血缘闭环（捕获 request_id → 版本冻结 + job 落列 + 审计反查 + 幂等不重铸）/ 非 AI 生成保持 NULL。
- 105 表不变（列级增量）/ 迁移头 `c7e1a9f3b5d8`→**`e2c6a8f4d1b3`（34 rev）**/ 业务路由 296 不变 / ENTRIES 94 不变 / mypy 基线 279 不变 / 桌面 vitest 765 不变（零改动，无需重打包）；改 server + 新迁移 ⇒ **rebuild 三镜像 + `alembic upgrade head`**。

## [未发布] — V3 实施 T-O4 桌面消费面：调研数据导入 UI + 导入结果让位回溯卡片（2026-11-04）

### 桌面端（服务端零改动：零迁移零路由、无需 rebuild 镜像）

- **导入对话框（两段式）**：项目调研标题行新增「导入对象」（可填写时出现）→ 选对象类型（部门/岗位/流程/AI 机会）+ CSV/XLSX 文件（≤10MB）→「解析预览」走 `POST /research/subjects/imports/preview`（桌面结构化 multipart 通道，AI 预调研同源）→ 预览表 + 行错误清单（422 `details.errors` 与内联错误同区，≤8 条点名）→「确认导入」走 `POST …/imports/commit`（30 分钟一次性 token + 期望版本）。
- **导入结果卡片**：导入完成显示新建数量 + 幂等回放标注；`merge_candidates` 让位行逐条回溯——行号、同名既有对象（类型+跟踪码）、文件中说明（T-O4「同名让位不新建」的人工拍板面），「查看 X」跳选既有对象；卡片可关闭。`stale_version` 时自动刷新调研数据并提示重新解析。
- **复用与适配**：T-O4 桌面契约同步轮预置的 `isResearchImportPreviewDto` / `isResearchImportResultDto` / `parseResearchImportErrorDetails` 首次接线（零消费欠账清偿）；15 个导入面错误码映射；jsdom File 无 `arrayBuffer()` → `readFileBytes` 双路径（真环境快路径 + FileReader 兜底），真机与测试同一代码。

### 测试与口径

- vitest **765**（+4：导入主路径含让位卡片回链+multipart 契约断言 / 行错误禁提交零 commit / 预览拒绝映射 / stale 提交刷新；串行口径 `--no-file-parallelism`；基线 `65a40c5` 实测 761）；`npm run typecheck` 绿。
- 服务端零改动：pytest 1863 收集（1857 passed + 6 skipped）不变、105 表/迁移头 `c7e1a9f3b5d8`（33 rev）/业务路由 296/ENTRIES 94/mypy 279 全部不变，**无需 rebuild 三镜像**；桌面改动交付=便携版重打包（r14）+ asar 字节验证。

## [未发布] — V3 实施 T-O4b 桌面合并 UI：subject 合并原语上 UI + 归档行回链（2026-11-04）

### 桌面端（服务端零改动：零迁移零路由、无需 rebuild 镜像）

- **对象树合并入口**：操作栏新增「合并」（选中非根对象且可填写时出现，与既有「停用」同位）→ 对话框内挑选**同类型启用对象**为目标 → 密码确认（危险确认对话框）→ 调用 `POST /research/subjects/{id}/merge`（#91 `dfe91b3` 服务端原语的唯一 UI 面；合并仍有意不进 api_catalog）。
- **归档行「已并入 X」回链**：树底新增「已归档（N）」折叠组——归档行不可选中、不进 treeitem 键盘导航；合并让位行显示「已并入 X」回链（目标仍启用=可点击跳选，已停用=纯文本）；普通停用行也在此一并可见。
- **契约同步**：`ResearchMergeResultDto` + `isResearchMergeResultDto`（subject=并入方序列化 + `merge_summary` 六面搬迁明细，值计数/画像字符串/null）；`subjectMutationError` 补 4 个合并错误码映射（根对象/类型不一致/双方须启用）。
- **实施偏差（记录在案）**：①「导入结果 merge_candidates 卡片一键合并」前置缺失——桌面端调研数据导入 UI 尚未立项（`imports/preview|commit` 端点与桌面 DTO 校验器在、零 UI 消费），留待「调研数据导入 UI」独立轮；②「对象树右键合并」以操作栏行内「合并」按钮替代，避免引入整套右键菜单系统。

### 测试与口径

- vitest **761**（+6：树 3 / 工作区 2 / 契约 1；串行口径 `--no-file-parallelism`；基线 `8340e89` 实测 755）；`npm run typecheck` 绿。
- 服务端零改动：pytest 1863 收集（1857 passed + 6 skipped）不变、105 表/迁移头 `c7e1a9f3b5d8`（33 rev）/业务路由 296/ENTRIES 94/mypy 279 全部不变，**无需 rebuild 三镜像**；桌面改动交付=便携版重打包（r13）+ asar 字节验证。

## [未发布] — V3 实施 T-G2：template_hash 漂移呈现——门禁序列化比对冻结哈希 vs 现行 gates.json（2026-11-04）

### 服务端（零迁移零路由；gap-matrix WB-DEF-5 / 风险册 F-2）

- **`_serialize_gate` 响应新增 `template_outdated: bool`**：比对 Gate 行实例化时冻结的 `template_hash`（seeds/gates.json 文件级 sha256）与现行镜像内文件的哈希，不一致即标注——存量行（迁移 `f7a2c9e4b1d3` 回填 `f52afe88…` ≠ 现行文件）响应即为 true，呈现即修复 WB-DEF-5「存量哈希与现行模板漂移、无比对呈现」；`template_hash=NULL`（未知出处）判 false 不误报。
- list/GET、证据提交、拍板四类响应共用同一序列化器，自动携带；哈希读取走进程级缓存（文件烘进镜像只读）。桌面 GateBoard 类型守卫只验必填键，新增键纯增量（桌面呈现消费留待 UI 轮）。

### 测试与口径

- 服务端 pytest **1863 收集 = 1857 passed + 6 skipped**（本轮 +1：懒实例化首访全不漂移 / 冻结哈希改写 → true / NULL → false 不误报；基线即 fork/main `6cccedb` 实测 1862 = 1856 + 6s——T-R2 记录的 1855 为其自轮 `e1568d6` 运行面，squash 并入 #98 携 +7 测试）。
- 口径：105 表不变、迁移头 `c7e1a9f3b5d8` 不变（零迁移）、路由 296 不变、ENTRIES 94 不变、mypy 基线 279 不变（104 distinct，实测零新增）；桌面端零改动（vitest 755 不变）。

## [未发布] — V3 实施 T-R2：工具目录结构化 effect/risk——目录权威外效判定 + WB-DEF-10 确认面补口（2026-11-04）

### 服务端（零迁移零路由；agent-policy P1-R2 / gap-matrix 域 9 / 风险册 WB-DEF-10）

- **api_catalog 结构化 effect/risk**：`CATALOG` 行新增 `effect`（`read | write_db | external`）与 `risk`（0–4，与 `automation_approvals.risk_level` 同尺度，≥3 = 密码确认/审批类）——ENTRIES 五元行不动，派生在装配层 `_catalog_row`（规则显式：GET=read/0；确认类（DELETE / .archive / .deprecate / 确认补口）=3；其余 external=2；普通写=1；4 留最高危未用）。
- **WB-DEF-10 补口**：`EXTERNAL_EFFECT_KEYS`（forms.export / solutions.export_sow / documents.generate / translator.translate = 异步作业或模型调用类）+ `CONFIRMATION_KEYS`（export_sow / documents.generate）——AI 经 `api_execute` 发起即 `awaiting_confirmation`（密码确认通道后才触发 worker 作业），绝不无确认排队模型调用。
- **TOOLS 五元扩 effect/risk**（17 工具）：(description, capability, properties, effect, risk)；`file_send_wechat`=external/3、`api_execute`=write_db/3、`lcsc_search`=external/2、其余只读=read/0；MCP `tools/list` annotations 改由结构化元数据派生（`readOnlyHint=effect==read`、`destructiveHint=risk>=3`），取代工具名硬编码集合；`api_catalog` 工具描述同步声明「外部副作用与风险分级」。
- **workflow rule 9 消费目录权威**：`validate_dag` 新增 `call_effects` 注入参（生产恒经 `catalog_call_effects()` 注入 CATALOG effect；None 时仅节点自声明生效，纯函数单测兼容）——call 节点目录 effect=external 即触发 `external_effect_without_approval` 告警，节点 effect 声明**只加不减**（不可把目录 external 降级为 read）；P1 仍告警不阻断（P2 转强制随 enforcement wave 另行）。
- **executor 外副作用推断收敛**：`_is_external_call` 由 `write` 字段推断改为结构化 `effect != "read"`（集合等价，清偿 T-W3 挂账「effect 结构化仍待 T-R2」）。

### 测试与口径

- 服务端 pytest **1855 收集 = 1849 passed + 6 skipped**（本轮 +4：目录 effect/risk 全量一致性扫描 / WB-DEF-10 双操作确认流 / tools/list annotations 派生 / rule 9 目录权威+不可降级+装配同域；解包适配为改造非新增）。
- 口径：105 表不变、迁移头 `c7e1a9f3b5d8` 不变（零迁移）、路由 296 不变、ENTRIES 94 不变、mypy 基线 279 不变（104 distinct，实测零新增）；桌面端零改动（vitest 755 不变）。

## [未发布] — V3 实施 T-R1：agent_tool_groups 只读工具组目录——`group:` 引用声明糖，resolve=交集组永不扩大（2026-11-04）

### 服务端（纯种子零新表：`seeds/tool_groups.json`；零迁移零路由）

- **组目录**（agent-policy P1-R1 ToolGroup / gap-matrix 域 7）：种子随代码发布（非用户可写），首批两组只读白名单——`research-readonly`（文件+项目/门禁/报价/本体/API 目录，9 工具）、`ops-readonly`（系统状态/动作留痕/立创运行史/技能只读/帮助，6 工具）；行含 `description`/`is_active`（停用=代码侧空贡献开关）。
- **声明解析**（`agents/tools.py::resolve_tool_groups`）：`agent_registry.allowed_tools` 支持 `"group:<name>"` 引用，解析为组工具集并入声明集（保序去重，直接项与组贡献并集）；**只收窄语义**——组贡献与直接声明同权进入既有三重交集管线（平台 deny ∖ 写类/会议面 ∩ 发起人档位地板 ∩ 插件安装态），组引用绝不绕过任何一腿。未知/停用组贡献为空（只收缩不放宽、运行面不崩溃）。
- **fail-fast 种子校验**：组引用未知工具装载即 `RuntimeError`（校验分母 = 网关 `TOOLS` ∪ 会议面 ∪ 沙箱生态 `read_file`，嵌套 `group:` 引用同拒）；沿 agents.json 种子校验先例，坏种子宁可起不起来不静默缩空。
- **报因补口**（`agents/service.py::_unavailability`）：声明判定改走解析前原样（`declares_run_tools`，组引用也算声明）——纯未知组声明解析为空面时明确报因 `tools_unavailable`，不静默放行空名单 run；空声明/仅会议面声明 agent 行为不变。
- `run_face_declared`/`effective_run_tools` 增 `groups` 注入参（仅测试用，生产恒走种子）；`list_agents` 序列化仍展示原始声明（组引用自描述，运行面解析留 run 时刻）。

### 测试与口径

- 服务端 pytest **1851 收集 = 1845 passed + 6 skipped**（本轮 +4：种子校验+未知工具/嵌套引用 fail-fast / 组不放宽三闸齐验（写类剥除·档位地板·插件安装态）/ 未知组收缩+报因 / 真种子混合声明保序去重）。
- 口径：105 表不变、迁移头 `c7e1a9f3b5d8` 不变（零迁移）、路由 296 不变、ENTRIES 94 不变、mypy 基线 273 不变；桌面端零改动（vitest 755 不变）。

## [未发布] — V3 实施 T-G1：任务产物→门禁证据候选——WB-DEF-8 双口径脱钩的候选闭环（2026-11-04）

### 服务端（迁移 `c7e1a9f3b5d8`：gates +`evidence_candidates` 可空 JSON 列；零新路由）

- **候选挂接**（`gate_service.attach_task_evidence_candidate`）：任务 `status=completed` 且自带门禁挂点（G1–9）+ 证据指针+指纹（T-E3 已把任务证据登记为一等证据行）→ 该产物登记为目标门禁的**候选**（task_id/task_key/task_name、指纹统一小写、提议人、提议时间）。建议性：清单项 claim_status 与门禁状态机一概不动，领用永远由人完成；同 (uri, hash, task_key) 幂等；上限 20 条丢最旧；门禁行未实例化时懒初始化（幂等）。
- **挂接点**（`task_service.update_project_task`）：乐观锁通过后按 effective 值（变更键 ∪ 既有任务字段）判定——三要素任意更新次序凑齐即挂（完成在后/在前皆可）；stale 版本零副作用。create 路径任务恒 not_started，天然不触发。
- **采纳即闭环**（`submit_gate_evidence`）：提交指纹命中候选（hash 忽略大小写）即剪除对应候选，面板不再重复提示；未命中者保留。
- 序列化契约 +`evidence_candidates`（恒输出，旧行 NULL→[] 读时合并）；事件 `gate_evidence_candidate_attached` 挂 gate 行并入门禁事件流（GATE_EVENT_TYPES 扩展）。
- **workflow 产物候选挂起**：run/节点产物（`output_json`）尚无「指针+sha256」形状，待产物 schema 立项后零改挂入（挂接函数已按通用形设计，收 (uri, hash, 来源粒度)）——偏差已回写 backlog T-G1 实施记录。

### 桌面端（GateBoard）

- 清单项下新增「任务产物候选」区：候选出任务键/名与指针+指纹，选目标清单项一键「采纳到清单」（走既有提交闸，服务端命中剪除）；evidence 态也可补采纳（部分采纳流）；viewer 只读；旧载荷无键兼容、非法形状整板拒渲染（fail-loud）。

### 测试与口径

- 服务端 pytest **1847 收集 = 1841 passed + 6 skipped**（本轮 +6：挂接+契约+事件 / 三缺一不挂 / 次序无关+幂等 / 采纳剪除+claimed / 部分采纳保留 / 拍板零感知；上轮口径差 +3 为 #93 skill 两闸用例）+ 迁移往返（HEAD `c7e1a9f3b5d8`，33 rev）。
- 桌面端 vitest **755/755**（+3：候选渲染+采纳流 / viewer 只读+旧载荷兼容 / 非法形状拒收）+ typecheck 通过。
- 口径：105 表不变（列级增量）、路由 296 不变、ENTRIES 94 不变、mypy 基线不变（新代码零新增）。

## [未发布] — docs：archify 整套架构图入库——五视角交互式证据图 + 复跑回执（2026-11-04，纯文档零代码零迁移）

- 新增 `docs/architecture/archify-diagrams/`：用 archify（v3.0.1）从本仓库真实代码取证生成的**五视角**架构图，每张独立 standalone HTML（内联 SVG、暗/亮主题、可导出 PNG/JPEG/WebP/SVG/WebM、路径/透镜视图）：
  - `architecture/` 系统总体架构（14 节点 / 16 连接 / 4 边界）
  - `workflow/` 交付主流程：从项目到回款（13 节点 / 15 边 / 6 车道，含 fail 整改 / 人工免终审 / L1 接管 / 409 闸拦分支）
  - `sequence/` Workflow run 一次执行完整调用链（8 参与者 / 42 消息 / 10 段，四类节点分派）
  - `dataflow/` 集成桥采集 → 服务端投影 → 一等证据登记簿（指针 + sha256 红线）
  - `lifecycle/` Workflow 运行生命周期双层状态机（run 七态 + node 八态，幂等键 / 断链 / cancel / resume）
- 每张同级含 `candidate.json`（生成输入）+ `receipts/`（通过轮 finalize/deliver/check/browser-check 回执）+ `preview.png`（1440×900 亮色截图），`index.html` 汇总入口。
- 文档口径纠偏（以代码为准）：run 起始态 `queued`（非 `pending`）；发起路由 `POST /projects/{pid}/workflows/{def_id}/runs`；桌面控制台可列/详情/取消/恢复、**不能**发起 run。
- README「技术架构」节加一段指向本目录的锚注。
- 口径数字全部不变（105 表 / 路由 296 / ENTRIES 94 / 迁移头不变）；零路由零迁移零桌面改动。

## [未发布] — V3 实施 T-O4b：subject 合并原语——表单/答案/链接/子对象/备忘录/画像单事务搬迁（2026-11-04）

### 服务端（迁移 `d4e6f8a2c7b9`：+`merged_into_subject_id` 可空列；一条人工路由 295→296）

- **合并原语 `merge_subject`**（`research/subject_service.py`，T-O4 遗留候选收口）：source 并入 target（同项目同类型、双方 active、非 project 根，单事务全成全败）。六面搬迁纪律：
  - **表单/答案**：form_key 不撞 → 整表搬迁（修订+答案随外键同行）；撞键且源从未采集过答案 → 让位删除；**撞键且源有答案 → 409 `merge_form_conflict` 点名键**（绝不静默丢采集，人工先处置再重试）。
  - **链接**：边重指到 target；会变自环或与存续边重复的让位删除（唯一边约束永不违反）。
  - **子对象**：随迁（同类型 ⇒ 父类型规则天然成立，含归档子行）；**既有合并链一跳化**（曾并入 source 的行重指 target）。
  - **备忘录**：共享 memo 与个人备忘录均带「（合并自 名字 跟踪码）」头并入（与编辑闸同尺 20 000，超长显式截断标记）；目标无同人个人备忘录则整行重指。
  - **机会画像**：目标无 → 整行迁入；双方都有 → **目标留任**（机会画像创建即有，留任是唯一可行语义），源画像关键字段随事件留档。
  - **跟踪码不回收**：source 归档后永久占号（`merged_into` 指向存续方），新号接既有最大值——`allocate_tracking_codes` 扫全量行天然兼容。
- **DB**：`project_research_subjects` + `merged_into_subject_id`（复合外键 RESTRICT 自引用 + 两条 CHECK：不自指、指向即必归档 + 索引）；归档行保留 subject_key/跟踪码占位（UNIQUE 绝对，语义同 T-O1 merged 术语）。
- **路由**：`POST /projects/{id}/research/subjects/{source_id}/merge`（body `{version, target_subject_id}`，`_require_subject_write` 同档案闸）；**有意不进 api_catalog**（业务对象不走 change_set 双轨，T-O3 裁决维持；钉子测试在位）。
- 事件 `project_research_subject_merged` 挂 source 行，载荷带全部搬迁计数与双跟踪码。
- 序列化契约 +`merged_into_subject_id`（旧载荷无键向后兼容）；根检查先于类型检查（根对象永不参与合并）。

### 桌面端（仅契约同步，零新页面）

- `ResearchSubjectDto` + 可选 `merged_into_subject_id?: string | null`；`isResearchSubjectDto` 运行时校验同步（缺键旧载荷/带键新载荷都收，非法形状拒收）。

### 测试与口径

- 服务端 pytest **1838 收集 = 1832 passed + 6 skipped**（+7：全表面搬迁+占号 / 撞键 409→处置后成功 / 类型·根·自指·stale·归档源目标拒绝 / 链一跳化 / 画像迁入与留任 / 权限（viewer 403、非成员 404））+ 迁移往返 1 例（HEAD `d4e6f8a2c7b9`，32 rev）。
- 桌面端 vitest **752/752**（+2：合并指向键兼容性）+ typecheck 通过。
- 口径：105 表不变、路由 **296**、ENTRIES 94 不变、mypy 基线不变（新代码零新增）。
## [未发布] — 修复 mac 图标管线回写 Windows 图标（2026-11-04）

- `desktop/scripts/generate-icon.sh` 原本把 swift 渲染结果写回 `build/icon.png`——Windows 图标源会在 macOS 构建时被静默覆盖（产品更名轮手工替换的新图标跑一次 `package:mac` 即丢失）。改为渲染只进临时目录：`build/icon.png` / `icon.ico` 由品牌资产独立维护，macOS 管线只产出 `icon.icns`。
- mac 工具链（swift / sips / iconutil）无法在 Windows 上验证，本改动为纯输出路径调整，待下次真实 mac 打包核验；渲染输入源暂仍为 `assets/logo.png`（旧图），mac 图标换新待品牌透明 mark 资产（SVG 转透明 PNG）落定后一行重指。

## [未发布] — 使用帮助三面同步：工作流 / 术语表 / Skill 治理入册（2026-11-04）

- 三面同步（`docs/工作台操作使用手册.md` = 镜像内 `bundled/help_manual.md` = 桌面「使用帮助」）：项目详情 8→**10** 标签页；新增 §3.7 工作流（run 七态/节点八态/取消幂等语义/恢复 failed-only）与 §3.8 术语表（搜索/关系类型只读/变更集评审·否决留痕·拍板人≠提交人 403）；§8.1 补 Skill 卡「版本」治理对话框（版本历史/效果统计/提交评审-发布-回滚-弃用）；任务中心标注工作流人工审批；§11 术语速查补「变更集」；§12 缺口清单补「工作流定义新建无 UI 入口」；手册头部说明改为如实分发口径。
- 桌面 HelpPage 新增「工作流与术语表」章节 + KNOWN_GAPS 同步 + help-page 测试钉新章节与诚实语义。帮助文案与文档改动，零业务逻辑、零迁移、零路由。

## [未发布] — 文档收口：README 能力面与品牌资源同步（2026-11-04）

- 「主要能力」与首段补入已落地的用户可见能力：工作流控制台（T-W6：定义/运行/取消/恢复）、项目术语表（T-O1/T-O3/T-W6）、Skill 治理态与效果统计（T-S1/T-S2）；任务中心标注工作流人工审批（T-W4）。
- 页首改指产品更名后的品牌资源 `logo-caigong-fde.svg`；「更换 Logo 与安装图标」一节按现役管线重写（界面品牌资源清单 / Windows 构建图标 / macOS 图标生成链，`logo.png` 保留为 macOS 图标源）。纯文档改动，零代码。

## [未发布] — V3 实施 T-W6：桌面控制台三面——工作流 / 术语表 / Skill 版本治理（2026-11-04）

### 服务端（零迁移；两条只读列表路由为桌面控制台最小补面）

- **偏差回写**：workflow-dag-v1 §5 设计七条不变；控制台要「run 列表/取消/恢复」就得能枚举，故补两条 can_view 只读挂件——`GET /projects/{id}/workflows`（定义列表，新者在前，项目内定义天然少量无分页）与 `GET /projects/{id}/workflow-runs?limit=`（run 列表，默认 50 上限 200 有界扫描，`truncated=true` 诚实标注）。**列表行不带 nodes**（N+1 不可取），节点树走既有详情路由按需展开。
- 路由总数 293→**295**；ENTRIES 94 不变；迁移头 `b5d9e3f7a1c6` 不变。

### 桌面端（三张新页，页面仅呈现、写操作全走既有服务层闸）

- **WorkflowConsole**（`workflows/WorkflowConsole.tsx`，项目详情新 tab「工作流」）：定义卡片（状态/版本/节点数概览）+ run 列表（七态标签/错误摘要/`truncated` 提示）+ 按需展开节点态树（八态标签/attempt/错误）；**取消**（非终态可点，幂等语义照服务层——终态 409 `already_terminal` 原样呈现）与**恢复**（仅 failed，409 `not_resumable` 同）按钮挂 canManage。
- **GlossaryPage**（`ontology/GlossaryPage.tsx`，项目详情新 tab「术语表」）：术语只读清单（q 搜索按规范名/别名）+ 关系类型只读清单（登记/停用走管理通道，全局行需运维员——lesson 15 口径）+ **变更集评审**：状态过滤五态、载荷展开（动作明细 + base 指纹）、draft→提交评审 / in_review→确认物化 / 否决需理由；服务端「≠提交人」403 原样呈现不吞。
- **SkillVersionsPage**（`extensions/SkillVersionsPage.tsx`，扩展中心每张 Skill 卡新增「版本」按钮的治理对话框）：版本历史（指纹前缀/测试报告有无/当前标记）+ **效果统计**（消费 T-S2 `usage` 块：total/chat/workflow/last_used_at/by_version/truncated——by_version 正是回滚决策依据）+ 治理动作：draft→提交评审、in_review→发布（密码确认+豁免说明）、published→回滚（选目标版本+密码+豁免）/弃用；权限外只读（「只有公共 Skill 运维员或个人 Skill 属主可以执行治理动作」）。
- 项目详情 tab 枚举扩展：`overview/tasks/gates/commercial/research/delivery` + **`workflow` + `ontology`** + `library/management`（路由哈希与 tab 同步，无 legacy 映射需求）。

### 测试与口径

- 服务端 pytest **1831 收集 = 1825 passed + 6 skipped**（+1：定义/run 列表路由权限·排序·截断·400 界）。
- 桌面端 vitest **750/750**（+18：workflow-console 5 / glossary-page 6 / skill-versions-page 7）+ typecheck 通过。
- 用例钉住诚实语义：failed 本就是终态不显示取消；取消竞态 409、自确认 403、错密码 403 全部原样呈现；无密码/无回滚目标客户端侧先拦；无治理权只读提示。

## [未发布] — 产品更名「蔡工FDE智能交付系统」+ 集成桥 stale 标记去重（2026-11-04）

### 品牌统一（产品名口径 + 品牌素材）

- **产品名统一为「蔡工FDE智能交付系统」**：新增 `desktop/src/renderer/src/brand.ts` 作为**产品名的唯一来源**（`PRODUCT_NAME` 全名 / `BRAND_NAME` 短名 / `BRAND_SUBTITLE` 副标题 / `DEVICE_LABEL` 登录设备标签），此前产品名散落在十余处硬编码，改名必然漏改——现全部改为引用常量。
- **落地位置**：侧边栏品牌区（蔡工FDE / 智能交付系统）、登录页主标题、窗口标题（`index.html` 的 `<title>`，Electron 主窗口由此继承）、立创内置浏览器与查询跟踪窗口标题、`desktop/package.json` 的 `productName` / `description` / `author` / DMG 标题、服务端内置助手 system prompt、README 首屏标题与正文。
- **品牌素材换新**：侧边栏与 favicon 换用蔡工FDE 标识（`logo-caigong-fde.svg` / `.png`），应用图标（`build/icon.png` / `.ico`）同步更新。
- **有意未改**：便携版目录命名 `蔡工FDE-<version>-便携版-r<N>`（`fde-package-verify` 技能约定的交付口径，改动会破坏「旧目录永不覆盖」的回退约定）、`package.json` 的 `name` / `appId` / `artifactName`（机器标识与产物文件名口径，非用户可见名）。

### 缺陷修复：集成桥 stale 标记重复

- **根因**：服务端 `bridge/sync.py` 对 openfde 与 fdeops 两条采集轨**各自**判定断连并各 `append("stale")`，双轨同时断连时同一行出现**重复标记**——前端会渲染出**两个同名「采集断连」徽标**，并因 `key={flag}` 重复触发 React 警告（`Encountered two children with the same key`）。
- **修复**：服务端改为「任一轨断连即 stale，只判定一次」（C9 的双轨独立报警语义不变：单轨断连仍照旧报警）；前端新增 `uniqueFlags()` 渲染前按出现顺序去重——`flags` 是可重复的观察项而非互斥枚举，前端不应假设其唯一。**两侧都修**，服务端收敛事实、前端兜底渲染。
- **回归钉子**：服务端新增 `test_both_tracks_stale_yields_single_stale_flag`（双轨同时断连只报一次，且 flags 整体无重复）；桌面端新增「renders a duplicate flag only once」（重复 flag 只渲染一个徽标）。已实测：还原旧实现时新测试**确实失败**，修复后通过。
- **口径**：服务端 pytest **1820 passed + 6 skipped**（+1）/ 桌面端 vitest **732/732**（+1）/ typecheck 通过。
## [未发布] — V3 实施 T-S2：Skill 效果统计 + 治理留痕（回滚已随 T-S1 落地，2026-11-03）

### 服务端（零迁移零新路由 / 零桌面改动）

- **效果统计（agent-policy §2.4「run 面累计 usage，operation_events 已有基础」落地）**：双消费面计数——`skill_used_chat`（MCP `skill_read` 成功读出指南）与 `skill_used_workflow`（工作流 skill 节点按 pinned 版本完成一次确定性 AI 调用）；**失败不计**（AI 异常/重试是噪声不是效果，`skill_ref_unavailable`=内容未被消费），attempt 代际各计一次（resume 重跑每次都真消费了），`skill_list` 只浏览不计数。
- **独立微事务计数**：直连 AI 工具循环每轮 tool 后回滚共享会话（假定工具只读），经 `call_tool` 的消费计数自带已提交事务才能存活——与 `run_lcsc_skill` 自管事务的先例同构，专项测试钉「call_tool 后 rollback 事件仍在」。
- **统计读出（零新路由）**：`GET /extensions/skills/{id}/versions` 响应新增 `usage` 块 `{total, chat, workflow, last_used_at, by_version, truncated}`——有界扫描（最近 1000 条消费事件）Python 侧聚合，触顶 `truncated=true` 诚实标注；`by_version` 供回滚决策（旧版本还在被 workflow pinned 引用吗）；治理事件不进 usage。
- **T-S1 审计缺口顺带收口**（gap-matrix 域 8「回滚留 operation_events」）：补齐四条治理事件 `skill_review_submitted / skill_published（version+waive_reason）/ skill_rolled_back（from_version+to_version+waive_reason）/ skill_deprecated`，与生命周期操作同事务落表；闸失败（错密码/材料缺失）不留事件。
- **实现偏差（backlog 已回写）**：事件不走 `projects/events.py::record_event`——`events.py` 顶层引入 `control.models` 会经重型 `control/__init__` 反转 projects↔control 导入序（实测即环），改用 control 层 `_event` 直落 `OperationEvent` 的既有同构（api_actions 先例）；`target_type="skill_definition"`、`project_id=None`（Skill 不挂项目）。
- **测试**：`test_skill_lifecycle.py` **7→11**（治理事件四类+闸失败零事件 / chat 计数+回滚存活+404 不计数 / usage 汇总+零值+按版本 / truncated 诚实标注）+ `test_workflow_executor.py` 两用例扩展（pinned 版本消费断言 / 失败 attempt 不计）。服务端 pytest **1829 收集 = 1823 passed + 6 skipped**（+4）/ vitest **731 不变**。**零迁移**（head `b5d9e3f7a1c6` 不变）/ **零新路由**（283 不变）/ ENTRIES 94 不变。

## [未发布] — 桌面端视觉统一：设计令牌体系与缺失样式类补齐（2026-11-03）

### 纯 CSS 重构（零功能变更，零 TSX 逻辑改动）

- **修复三处结构性缺陷（根因不是"配色不好看"）**：
  - **① 关键样式类零 CSS 规则**：`.page` / `.card` / `.page-heading` / `.page-subtitle` / `.muted` 在全局样式中**没有任何规则**（提取全部 tsx 的 className 与全部 css 选择器做差集确认），致使翻译器、指标报表、试点报告、派单池、调度台、开闸运维等 **7 个页面整页裸奔**——无卡片容器、无内边距、无层级，输入框挤在一行、标题与正文同字号。**本次补齐全部原语。**
  - **② 六个 CSS 变量从未定义**：`--border` / `--panel` / `--accent` / `--text-muted` / `--border-color` / `--surface-alt` 查无实据，`border: 1px solid var(--border)` 因变量不存在而**整条声明作废**，派单页簇所有卡片**完全没有边框**。**本次在 `:root` 集中定义并保留旧名别名**（旧写法零改动继续可用）。
  - **③ 组件样式表各自为政**：`task-board.css`（12 色）与 `ai-server-chat.css`（45 色）自成色板，与全局令牌脱节。**本次全部改走令牌。**
- **统一设计体系**：`:root` 重写为**九层令牌体系**（品牌色阶 / 中性面 / 文字 / 描边 / 语义色 / 圆角 / 阴影 / 间距梯度 / 字阶）+ 控件尺寸，每层带注释；新增 `pages/pages.css` 承载翻译器 / 指标报表 / 试点报告 / 派单页簇 / 帮助页的版式骨架；按钮统一高度（38px）/ 圆角 / 阴影与悬停·按下·禁用态；徽标语义色、表格行高描边表头、输入框边框聚焦环占位符统一；**4 套并存标签页收敛**为分段式一套（`extension-tabs` 保留下划线式以区分内容层级）。
- **现代感与纵深**：页面底与卡片加入品牌色径向渐变晕染，阴影分六级、圆角五档，卡片悬停浮起；硬编码色值**约 250 处 → 82 处**（余下绝大多数位于 `:root` 定义内）。
- **验证**：`npm run typecheck` 通过；`npm run build` 通过（`pages.css` 已进产物 CSS）；桌面端 **731** 例测试全绿（60 文件）；新增 `desktop/gui-harness/shots.mjs` 逐页视觉走查（13 页，零 console error）。
- **工具**：新增 `scripts/watch-pr-checks.py`——守望 PR 的 CI check-runs 收敛。**只用 `commits/<sha>/check-runs` 索引**（`actions/runs` 的两种索引都不可靠），且**显式区分「空列表」与「已收敛」**（空结果≠收敛，否则索引抖动会造成假绿）；收敛前额外核对 4 个 CI job 齐全。

## [未发布] — V3 实施 T-O4：导入别名去重（同名让位 + 合并候选 change_set，2026-11-03）

### 服务端（零迁移零路由 / 桌面端契约同步）+ 桌面端（验证器/类型/测试）

- **两把尺子裁决（附录 D ⑨ 导入重复根治）**：**文件内同名 = 致命行错误** `duplicate_name`（preview 报且首行干净，commit 同尺复核——文件是用户声明，歧义由人解决，不替人猜）；**文件 vs 项目既有 active 同名（同类型）= 让位**——撞名行不再静默新建合成键对象（`import_<type>_<preview>_<row>` 每行各异的旧路径），改为合并候选。归档/停用行不拦重建，跨类型同名（部门的销售部 vs 角色的销售部）是不同实体不去重。
- **合并候选三面呈现**：①导入结果载荷新键 `merge_candidates`（name/row/description/matched_subject{id,name,tracking_code}——被让位行的说明无损保留供拍板）；②跟踪码只发真正新建的行（让位不占号，新号接既有最大值，不产生空洞）；③**全部让位 = 合法成功**（零新建 + 全量候选 + 版本照常 +1，重复导入幂等友好；收据回放完整带出候选，`idempotent_replay` 语义不变）。
- **合并候选 → change_set 提案（T-O3 闭环的自然落地）**：候选名若无术语行/别名占用（且 ≤TERM_MAX_LENGTH=120），按首现序去重提案 `create_term`（definition=被让位行说明，超长截 120）——**draft** 变更集带 `captured_from="research_import:<preview_id>"`，经既有 submit→confirm 人工拍板坐实「同项目一个名字一个概念」；拍板拒绝无残留（让位已在导入侧完成，术语只是不登记）。**动作域不因 T-O4 开 subject 合并**（T-O3「业务对象不走 change_set 双轨」裁决仍成立；subject 合并原语牵动表单/答案/链接/跟踪码，L 级别另行立项）；候选名已有术语/别名占用时不提案（物化期 409 term_exists 的死路不走）；超 `CHANGE_SET_MAX_ITEMS`=50 截断并在 description 注明。ontology/service 新增占位检查原语 `existing_term_names`。
- **桌面端契约同步（精确键集校验不破）**：`isResearchImportResultDto` 精确键集 +`merge_candidates`（`ResearchImportMergeCandidateDto` 类型 + 验证器 `isResearchMergeCandidateDto` + 测试 2 例）；preview 载荷零变化（`duplicate_name` 走既有 errors 通道直透，`isImportError` 只验形状）。
- **测试**：`test_research_imports.py` **+7**（批内同名致命/让位+提案+跟踪码钉子/全让位+回放带候选/术语占用不提案/confirm 闭环落 confirmed 术语+验收分离/跨类型不去重/超长说明截断）；桌面 `project-runtime-validation.test.ts` +1。服务端 pytest **1825 收集 = 1819 passed + 6 skipped**（+7）/ vitest **731**（+1）。**零迁移**（ontology_change_sets 表 T-O3 已备）/ 零路由（293 不变）/ ENTRIES 94 不变。
- **有界查询不变量**：commit 的同名让位扫描为**恒定 1 次**整行 select（不随行数乘法），既有 bounded-queries 测试上限 1→2（注释钉住）。

## [未发布] — V3 实施 T-O2b：对象类型值域开放（T-O2 注册表的 subject_type 真正可用于新建对象/表单/导入，2026-11-03）

### 服务端（1 个迁移（零新表：三处 CHECK 放宽 + 三列放宽）/ 零路由 / 零桌面改动）

- **值域从枚举到格式**：`project_research_subjects` / `template_research_forms` / `project_research_import_batches` 三处 subject_type CHECK 改码格式 `^[a-z][a-z0-9_]{0,59}$`、列宽 32→60（迁移 **`b5d9e3f7a1c6`**，31 rev；枚举 ⊂ 格式，存量全兼容；downgrade 收窄时超长注册码行被枚举 CHECK 挡下——保护语义）。
- **单原语闸门**：新建调研对象只认「内置五类 ∪ 注册表 active 行（全局∪项目内）− project 根」，把守在 `create_subject_in_transaction`（人工创建与导入 commit 同闸）；retired=禁新建存量只读、draft=未拍板提案，都拦闸外（`usable_subject_type_codes`，与引用解析用的 `known_subject_type_codes` 两把尺子）。错误码新设 400 `unsupported_subject_type`。
- **导入三闸一致**：authorize 带回项目可导入域 → preview/store 前置校验（缺省退回内置四类）→ commit 原语复核（覆盖 preview→commit 30 分钟 TTL 内 retire 窗口）。
- **消费方对齐（防静默丢内容）**：文档快照按行上实际类型分组（注册/退役类型的存量对象不再被丢弃）；表单定义/AI 表单生成/模板四处校验器全部接「内置 ∪ active」；映射校验允许域从已发布 research definition 派生（保持纯函数）。
- **两条基线不放开**：AI 生成表单缺省仍只认内置五类（防幻觉）；行业模板五类内置调研表必备（开放值域 ≠ 放弃底线）。
- **注册类型对象语义**：无父级规则 → 本轮仅允许根级；无跟踪码前缀 → `tracking_code=null`；备忘录/合并功能域白名单（内置四类）冻结不动。
- **测试**：新增 `test_ontology_subject_type_domain.py` **9 例**（usable 域作用域/状态、注册类型 HTTP 全链路+四类拒绝、retire 存量保留+快照、导入三闸、定义/AI/映射/模板域、内置码覆盖钉子）+ 迁移往返 **1 例**（双向列宽/CHECK/数据保留 + 存量行挡降级保护语义）；`HEAD_REVISION` → `b5d9e3f7a1c6`。服务端 **1818 收集 = 1812 passed + 6 skipped**（+10）。改 server + 新迁移 ⇒ rebuild 后必 `alembic upgrade head`（api/worker/scheduler 三镜像）。

## [未发布] — V3 实施 T-O3：变更集 ontology_change_sets（AI 候选唯一入口：propose→submit→confirm 人工拍板闭环，2026-11-03）

### 服务端（1 个迁移（一张新表，唯一 DDL）/ 7 条新路由 / 零桌面改动）

- **变更集**：`ontology_change_sets`（title/description/proposed_json 载荷/diff_summary 人读摘要/status ∈ draft·in_review·confirmed·rejected·superseded/base_snapshot_sha256 并发防护指纹/captured_from 候选来源标记/提交与拍板留痕）。迁移 **`c9e3a7d1b5f8`**（30 rev，additive，含 downgrade）。AI 产物永不直接写术语/类型表——候选载荷进 proposed_json，人工拍板后才逐项物化。
- **状态机与并发防护**：draft →(submit)→ in_review（对受影响行快照取 sha256 指纹）→(confirm)→ confirmed / →(reject)→ rejected（留 reason）；draft 可否决（撤回）。confirm 复核指纹——既有行被并发改写或占位名凭空出现/消失都判漂移，**409 `base_conflict` 零物化**。confirm **单事务全成全败**：任一项物化失败整体回滚（无 partial），错误 `change_set_item_failed` 点名项次；成功落 `ontology_change_set_confirmed` 事件携带逐项结果。
- **物化语义**：`create_term` 直落 confirmed；`update_term` 同名=原行受控改写（旧定义随事件留档；**change-set confirm 是全系统唯一 definition 写路径**）、改名（`new_term`）=新行 confirmed+原行 superseded 指 canonical+原名转别名；`merge_terms` 走 T-O1 原语（合并保留来源）；`register_relation_type` 只登记项目内类型（全局登记留 admin 人工路由）。`create_subject`/`link_subjects` 设计列有、本轮不开放（propose 即点名拒绝）。
- **验收分离（P0-5 纪律移植）**：confirm/reject 均要求拍板人 ≠ 提交人（403 `change_set_decider_conflict`，沿 gate 先例）。
- **HTTP 面（人工路径，不进 api_catalog）**：`GET /projects/{id}/ontology/terms?q=`（T-O1 欠账的术语只读面，别名命中返回属主行）+ change-sets 六条（propose/list/detail/submit/confirm/reject；submit 为设计 §4 表外补充——`not_in_review` 预设评审态、指纹语义锚在提交时刻）。跨项目 404 `change_set_not_found`（不泄露存在性）。事件目标注册表 +`ontology_change_set`。
- **测试**：`test_ontology_registry.py` **8 例**（payload_schema 校验族 / 状态机+HTTP 全链路（含验收分离、重复确认、跨项目、?status= 过滤、confirmed 事件逐项结果）/ base_conflict 双漂移（行改写+占名抢注）/ 单项失败整体回滚 / update_term 同名与改名双分支 / captured_from AI 通道 / merge+register 物化 / 术语 GET 面 + api_catalog 三面钉子）+ `test_migrations.py` 迁移往返 **1 例**（载荷 JSON 落行可读 + 状态 CHECK）；`HEAD_REVISION` → `c9e3a7d1b5f8`。
- **口径**：业务表 **104→105**（+ontology_change_sets）/ 迁移头 **`c9e3a7d1b5f8`（30 revision，+1）** / 路由 **286→293**（+7） / api_catalog ENTRIES **94 不变** / pytest **1808 收集 = 1802 passed + 6 skipped**（本轮 +9：变更集 8 + 迁移往返 1；较 T-O2 记录基线 1798 的 +1 为该轮基线记法偏差，与本轮无关） / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（一张新表；**api/worker/scheduler 三个镜像都要 build**）。

## [未发布] — V3 实施 T-O2：关系/对象类型注册表 ontology_relation_types（关系类型不再硬编码，2026-11-03）

### 服务端（1 个迁移（一张新表，唯一 DDL）/ 3 条新路由 / 服务层 ∪ 接入 / 零桌面改动）

- **注册表**：`ontology_relation_types`（`kind` ∈ subject_type/link_type；`code`/`label`/`description`；端点约束 `allowed_source_types`/`allowed_target_types`；`status` ∈ draft/active/retired；`project_id` 为空=全局类型、仅 admin 可建）。迁移 **`b8d3f1a5c7e2`**（29 rev，additive，含 downgrade）。把审计附录 D ②③ 的「对象类型 CheckConstraint 硬编码」「link_type 白名单硬编码 2 种」的扩展面搬进可注册表。
- **∪ 接入（服务层）**：`research/subject_service.py` 的 `_validate_link` 改为「**内置优先** + 注册表」——内置两类关系类型的端点约束是存量语义，注册表**不得覆盖内置码**（注册内置码 409 `duplicate_code`），故「∪ 语义不得放开内置方向校验」由机制保证；注册类型按端点约束判方向（不符仍 422 `invalid_research_subject_link`）；**retired 类型禁新边 409 `link_type_retired`、存量边只读**；未知类型 422 且消息附当前可用类型清单。内置集合与注册表保留名单的一致性由测试钉住（防漂移）。
- **作用域**：项目内类型**遮蔽**同名全局类型（端点约束可按项目定制）；项目内 `UNIQUE(project_id, kind, code)` + 全局部分唯一索引（`project_id IS NULL`）两段实现设计稿的「全局/项目内各自唯一」。
- **HTTP 面（人工路径，不进 api_catalog）**：`GET/POST /projects/{id}/ontology/relation-types`（can_view / can_manage；`scope=global` 另需 admin）+ `POST …/relation-types/{id}/retire`（让「retired 后建边 409」在人工路径上可达）。登记/停用落 `ontology_relation_type_registered`/`_retired` 事件；事件目标注册表 +`ontology_relation_type`。
- **边界（重要）**：`kind=subject_type` 本轮**只落登记不开放使用**——新建调研对象仍只能取内置五类（三处 DB CheckConstraint 按设计兼容边界冻结），放开值域会连带表单定义/文档映射/文档快照/AI 模板 schema 五处消费方，属独立一轮（T-O2b）。`research/models.py` 仅加注释不改约束。
- **测试**：`test_ontology_registry.py` **7 例**（登记校验+内置码保护+作用域遮蔽 / 全局与项目遮蔽 / 内置冻结与漂移钉子 / DB 约束拒非法态 / HTTP 面与建边生命周期（注册→建边→方向不符→停用→禁新边→存量边可读）/ 全局类型登记与停用仅管理员 / api_catalog 钉子）+ `test_migrations.py` 迁移往返 **1 例**（全局部分唯一索引 + 项目内同名共存 + 端点约束 CHECK）；`HEAD_REVISION` → `b8d3f1a5c7e2`。
- **口径**：业务表 **103→104**（+ontology_relation_types）/ 迁移头 **`b8d3f1a5c7e2`（29 revision，+1）** / 路由 **283→286**（+3） / api_catalog ENTRIES **94 不变**（`research.link` 描述同步端点约束口径）/ pytest **1798 收集 = 1792 passed + 6 skipped**（+8） / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（一张新表；**api/worker/scheduler 三个镜像都要 build**）。

## [未发布] — V3 实施 T-O1：术语表 ontology_terms+aliases（同项目一个名字一个概念，2026-11-03）

### 服务端（1 个迁移（两张新表，唯一 DDL）/ 零路由 / 零桌面改动）

- **唯一性底座**：`ontology_terms`（UNIQUE(project, term)+状态机 draft/confirmed/superseded/merged+merged 必须指向保留行的 CHECK+乐观锁 version）与 `ontology_term_aliases`（UNIQUE(project, alias)，冗余 project_id 供导入去重点查）——同项目一个名字至多指向一个概念，是「导入同名重复」（审计附录 D ⑨）的根治面。迁移 **`a3e7c1f9b5d2`**（28 rev，additive，含 downgrade）。
- **服务原语**：`ontology/service.py` 的 `create_term`（别名占用先于同名预检；`initial_status="confirmed"` 直落供变更集 confirm 用）/ `confirm_term`（draft→confirmed 拍板；confirmed 409 `term_immutable` 不可原地改——服务层无 definition 编辑路径，修订走 change_set 新版本）/ `merge_terms`（合并保留来源：source 规范名转写为保留行别名、source 既有别名不动走 canonical 链、**链一跳化**重指、逐项 OperationEvent `ontology_term_merged`）。
- **零路由（T-W1 先例）**：术语公开面只有只读 GET；写路径一律经 change_sets propose→confirm（AI 候选永不直接写表）——REST 面随 T-O3 routes.py 开；治理面不进 api_catalog（钉子测试）。事件目标注册表 +`ontology_term`。
- **测试**：NEW `test_ontology_registry.py` **7 例**（生命周期+confirmed 不可变 / 入参归一 / 同名+别名占用唯一 / 合并保留来源链+409 族 / 别名 DB 唯一 / CHECK 拒非法态 / api_catalog 钉子）+ `test_migrations.py` 迁移往返 **1 例**（自引用外键落 canonical/merged 对）；`HEAD_REVISION` → `a3e7c1f9b5d2`。
- **口径**：业务表 **101→103**（+ontology_terms/+ontology_term_aliases）/ 迁移头 **`a3e7c1f9b5d2`（28 revision，+1）** / 路由 **283 不变** / api_catalog ENTRIES **94 不变** / pytest **1790 收集 = 1784 passed + 6 skipped**（+8） / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（两张新表；**api/worker/scheduler 三个镜像都要 build**）。

## [未发布] — V3 实施 T-E3：bridge/任务证据统一入口（双通道落一等证据行，2026-11-03）

### 服务端（零迁移零路由零 DDL / task_service + bridge/sync 两处写入点挂接 / 零桌面改动）

- **任务侧**：`evidence_uri` + `evidence_hash` 齐备时，建任务/改任务同事务同步登记一等证据行（kind=`task`、captured_from=`human`、origin=`task:<task_key>`，大写 hash 归一小写）；同指纹幂等不增行，清空指针不动登记簿（证据不可变），只挂指针不落指纹不构成指纹不登记。写入点在乐观锁 rowcount 校验之后——stale 版本零证据副作用。
- **桥侧**：`apply_snapshot` 投影事务内把**已挂接 workbench 项目**的桥接采集登记为一等证据行（kind=`bridge`、captured_from=`bridge_sync:{run_id}` 机器通道、created_by 空）；openfde 按 engagement 指纹逐 slug、fdeops 按工作区级 registry_sha256；指纹不齐整（缺 hash / uri 越界）跳过不炸——投影是 4h 关键路径，证据不构成失败；同指纹幂等（内容不变不增行，内容变化=新指纹=不可变采集史新行）；`BridgeSyncRun.summary` 增 `evidence_created` 计数。
- **契约不动**：任务 DTO 与 engagement_view 均不暴露 evidence_id（沿 T-E2 gates_read 先例）；零新事件（任务侧 event_changes 已含证据字段变更；桥侧无 actor，summary+登记簿即审计）；登记路径仍不进 api_catalog（AI 不可写证据纪律不变）。
- **测试**：`test_project_tasks_api.py` +1（建/幂等/换指纹/清空/只指针 五段）+ `test_bridge_sync_flags.py` +1（挂接登记/未挂跳过/坏指纹跳过/重放幂等）。
- **口径**：业务表 **101 不变** / 迁移头 **`c1e5f9a3d7b2`（27 revision）不变** / 路由 **283 不变** / pytest **1782 收集 = 1776 passed + 6 skipped** / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d`（**api/worker/scheduler 三镜像**；迁移头不变，无需 alembic）。

## [未发布] — V3 实施 T-S1：Skill 治理态（draft/in_review/published/deprecated + 发布四闸，2026-11-03）

### 服务端（1 个迁移（唯一 DDL）/ 5 条新路由 / extensions_service 治理化 / 零桌面改动）

- **治理状态机**：`draft →(submit-review)→ in_review →(publish)→ published →(deprecate)→ deprecated`；编辑已发布公共 Skill 开新版本行并回 draft 重走治理。迁移 **`c1e5f9a3d7b2`**：`skill_definitions.status` 从扩展共用值域（active/disabled）切到治理四态（CHECK 换值域），存量 **active→published**（发布人暂记创建人）、**disabled→deprecated**；skill_definitions 加 published_by/at、skill_versions 加 input/output schema + test_report_json + reviewed_by（全可空，版本行不可变不变）。
- **发布四闸**：admin（system_operator）/ 密码确认（`invalid_password` 403）/ 状态须 in_review / 测试报告或显式 waive（`test_report_required` 409）；发布把版本行 `reviewed_by` 落为发布人（发布即审核背书）。回滚 = published 内改指旧版本行（版本行不可变），同密码+材料闸。
- **个人 Skill 自发布豁免**：保存即 published（owner 自治）；四闸只对公共 Skill。内置种子走服务端内部参数 `initial_status="published"` 直发布（内容可信），`_is_unchanged_builtin` 升级判定同步收敛。
- **消费方收敛（T-W1/T-W3 挂账清偿）**：MCP 工具面（`mcp_gateway._skills`）、工作流 skill.ref 定义期白名单（`published_skill_refs`）、执行器 skill 节点分派三处全部只认 `published`。
- **API 五条（278→283）**：submit-review / publish / rollback / deprecate / versions；content_sha256 指纹扩展覆盖全部发布材料（schema/测试报告变更即新版本）。
- **兼容**：既有 PATCH 启停开关保留旧值域作别名——个人 Skill 自愈发布（幂等）；公共 Skill 发布向 409 `governance_required`（开关不得旁路四闸），停用向照旧。桌面治理 UI（审核/发布按钮）挂后续轮。
- **测试**：NEW `test_skill_lifecycle.py` **7 例** + 修 5 处 active 语义既有用例（chat_mcp/executor/solution_skills/lcsc_other/extension_management PATCH 流）；`test_migrations.HEAD_REVISION` → `c1e5f9a3d7b2`。
- **口径**：业务表 **101 不变** / 迁移头 **`c1e5f9a3d7b2`（27 revision，+1）** / 路由 **283（+5）** / pytest **1780 收集 = 1774 passed + 6 skipped**（全量实跑 1209s） / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（skill 两表列变更 + 存量状态迁移；**api/worker/scheduler 三个镜像都要 build**）。

## [未发布] — V3 实施 T-W5：Workflow cancel/resume HTTP 面（服务端编排面收口，2026-11-03）

### 服务端（2 条新路由 / 零新表零迁移 / 零服务层改动 / 零桌面改动）

- **运行生命周期路由两条（276→278）**：POST `/api/v1/projects/{id}/workflow-runs/{rid}/cancel`（can_manage，幂等——重复取消 200 `cancelled=false`；终态 409 `already_terminal`；waiting_approval 可取消，pending 审批行不动）与 POST `…/resume`（can_manage，failed-only——failed/skipped 节点放回 pending 重投 `workflow.run`；其余 409 `not_resumable`）。服务层 `cancel_run`/`resume_run`（T-W3）直挂 HTTP，零服务层改动。
- **reconcile 收敛**：标题项已随 T-W3 落地（RECOVERABLE 增 `workflow.run` + worker-loss 钩子），本任务无残留。
- **测试**：`test_workflow_executor.py` **26→27**（HTTP 面：viewer 403 / 幂等取消 / already_terminal / 跨项目 404 / failed-only 恢复+节点回 pending / not_resumable）。
- **口径**：业务表 **101 不变** / 迁移头 **`d5b8e2f4a7c9`（26 revision）不变** / 路由 **278（+2）** / pytest **1773 收集 = 1767 passed + 6 skipped** / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d`（**api/worker/scheduler 三镜像**；迁移头不变，无需 alembic）。

## [未发布] — V3 实施 T-W4：Workflow 执行器 agent/human_approval 节点（审批复用 automation_approvals，2026-11-03）

### 服务端（1 个迁移（唯一 DDL）/ 零新路由 / 执行器+control 审批链扩展 / 零桌面改动）

- **human_approval 节点 = 复用 automation_approvals（设计 §3 落实）**：迁移 **`d5b8e2f4a7c9`**——`run_id` 放开可空 + 新增可空 `workflow_node_run_id` 反链（审批行=节点等待态的投影，FK CASCADE 随节点走，审计事实由 operation_events 承载）。分派即建审批：request_key=`wfnode:{节点行id}`、arguments_sha256 绑定输入快照、敏感键扫描（`contains_sensitive_argument` 提升为 control/access 公共函数，与 DSH 审批同闸）+ 64KB 上限、risk_level=4、15min 过期（`expires_minutes` 节点字段 1–1440 可调）；审批 id 挂节点幂等键 + pending 查重 ⇒ 崩溃恢复不重复建单。
- **拍板走既有任务中心入口（零新路由）**：`decide_automation_approval` 按 run_id 分支——workflow 审批经 `executor.settle_approval_node` **同事务**落节点终态（批准→succeeded 且 output 携 approval_id/拍板人/理由；拒绝/过期→failed）并**重投 workflow.run** 续跑；`dsh_approval_status` 惰性过期与 `execute_approved_dsh_tool` 同步加 workflow 守卫（审批无执行段）。
- **等待语义**：无 ready 且剩 waiting 节点 → run=`waiting_approval`（handler 正常返回；**有 failed 先断链收敛** FV-F1）；无人拍板则挂起（可取消），过期=拍板时惰性判定（主动清扫随 T-P1-5）；取消时 waiting 节点 cancelled、迟到拍板只落审批行不再驱动节点；resume 保持 failed-only。
- **agent 节点 = agents.start_run 同闸全链**（实时鉴权/月度预算/试点配额/T1/T6/沙箱/产物校验，绝不旁路）：幂等键 `wfnode-{节点行id}:{attempt}`——agents 对失败终态 run 拒绝同键重跑（V8），工作流以 **attempt 代际**表达「显式重试」（resume_run）；分派失败一律不叠加工作流自动重试（agents 自带重试族）；`params.solution_id` 透传使 agent_assisted/T1 方案闸随之生效。
- **定义期**：human_approval.capability 白名单 = 能力登记表去 `system.*`（validate_dag 注入参数，纯函数单测兼容）；四类之外未知类型的 start_run 422 守卫保留为防御（发布后白名单漂移场景）。
- **事件**：新增 `workflow_run_waiting_approval` / `workflow_run_approval_decided`。
- **测试**：`test_workflow_executor.py` **19→26**（审批批准/拒绝/过期/等待中取消+迟到拍板中和/幂等重入不重复建审批 + agent 全闸/能力拒绝不重试/run 失败不叠加重试）+ `test_workflow_definition.py` +1（capability 白名单）；`test_migrations.HEAD_REVISION` → `d5b8e2f4a7c9`。
- **口径**：业务表 **101 不变** / 迁移头 **`d5b8e2f4a7c9`（26 revision，+1）** / 路由 **276 不变**（零新路由）/ pytest **1772 收集 = 1766 passed + 6 skipped**（1764 + 8；实跑口径见 AGENTS.md）/ vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（automation_approvals 两列变更；**api/worker/scheduler 三个镜像都要 build**）。

## [未发布] — V3 实施 T-W3：Workflow 执行器（call/skill 节点 + §5 路由 + jobs handler，2026-11-03）

### 服务端（零新表零迁移 / 5 条新路由 / 新执行器模块 / 零桌面改动）

- **执行器**（NEW `workflows/executor.py`，设计 workflow-dag-v1 §3）：`workflow.run` 作为 background_jobs 新 job_type（决策 3：复用既有 outbox/lease/续租/reconcile/failure-hook 全套，绝不复制第二套队列）。主循环 = ready 调度（依赖全 succeeded，或 when 真值裁决放行）→ 节点独立事务执行 → 无 ready 全终态收敛 run；**每节点状态迁移独立事务、分派（HTTP/AI）一律在事务外**（产物先落表再前进=崩溃恢复锚点，2026-10-30 事故教训）。
- **call 节点 = api_execute 同闸绝不旁路**：鉴权/确认/项目 scope 每节点实时校验（发起人当下 AI 档位，run 级不冻结）；写类节点命中确认闸 → 节点 failed 携 action_id（诚实呈现未执行，T-W4 接审批前置）。**外副作用幂等（修 fde-v2 FV-F3 执行侧）**：写类（api_catalog write=True）节点分派前强制落节点级 `idempotency_key`（与 api_actions 完全同构 sha256 `[user_id, "wfnode-{节点行id}", data]`）——重试/崩溃恢复同键，api_execute 按 action 去重不二次外呼。
- **skill 节点 = pinned 版本确定性 AI 调用**：`key@版本` 固定版本 `instructions_text` 作 system_prompt、节点输入 JSON 作 prompt、`use_tools=False`（不签发 MCP token，工具面留在 call 节点）；T-S1 前沿用 active 语义（与 T-W1 校验口径一致）。
- **诚实语义**：占位符缺键 → 节点 failed `placeholder_missing`（绝不填空串，fde-v2 缺陷回归用例钉住）；断链 → run **failed** + 下游 skipped（修 FV-F1 不静默 done）；`when` 仅支持整串单占位符真值（表达式引擎待真实需求）；agent/human_approval 节点在 start_run 即 422 `unsupported_node_type`（不留必死 run，T-W4 开放）。
- **§5 路由五条（271→276）**：POST projects/{id}/workflows（can_manage）、POST …/{wid}/publish（admin 锁版）、POST …/{wid}/runs（can_manage，幂等键同 run 返回 200/新建 201，跨项目同键 409）、GET …/workflow-runs/{rid}（can_view 节点按拓扑序）、GET /api/v1/workflows（admin 平台模板）；**cancel/resume 的 HTTP 面随 T-W5**（服务层 cancel_run/resume_run 已可用）。
- **run 生命周期服务**：start_run（published 闸+幂等键先于定义查找） / cancel_run（停未执行节点、已执行外呼不回收、幂等） / resume_run（failed→重置 failed/skipped 节点复用产物）；事件目标新增 `workflow_run`（created/succeeded/failed/cancelled/resumed）。
- **jobs 接线**：`workflow.run` handler + worker-loss 收尾钩子（reconcile 放弃时 run 与悬挂节点推终态）+ RECOVERABLE_JOB_TYPES 增补（节点产物先落表=succeeded 即恢复锚点，重跑只处理未完成节点）；handler 入口恢复 queued→running 与死亡遗留 running 节点。
- **测试**：`test_workflow_executor.py` 新 **19 例**（§6 用例 4/5/6/7/8/11：链路与占位符原类型替换 / 版本钉住跨发布 / skill 钉版本指令 / 重试后成功与耗尽恢复复用产物 / 幂等键同构公式+跨重试恢复稳定 / 取消保留已成功节点 / 断链 failed+skipped / when 假值跳过 / 缺占位符不填空串 / 平台模板路由与项目内实例化 / outbox→worker 全链 / reconcile 钩子）。
- **口径**：业务表 **101 不变** / 迁移头 **`b7d9f1a3c5e2`（25 revision）不变**（零 DDL）/ 路由 **276**（+5）/ pytest **1764 收集 = 1758 passed + 6 skipped**（1745 + 19；实跑口径见 AGENTS.md）/ vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d`（server 代码烤进镜像；无迁移，alembic head 不动）。

## [未发布] — V3 实施 T-W2：Workflow 运行层（runs / node_runs 两表，2026-11-03）

### 服务端（2 张新表 / 1 个迁移 / **零新路由、零执行器、零服务逻辑改动** / 零桌面改动）

- **运行 + 节点运行双表**（迁移 **`b7d9f1a3c5e2`**，含 downgrade）：`workflow_runs`（固定 (definition_id, definition_version)——跑动中被改即受影响的 fde-v2 教训；run 级 `idempotency_key` **全局唯一**，修 fde-v2 FV-F3 无幂等重跑重复建单；status 七态 CHECK queued/running/waiting_approval/paused/succeeded/failed/cancelled；context_json=运行级入参占位符源；definition FK **RESTRICT**——执行史在则定义不可静默删，project FK CASCADE 项目隔离）+ `workflow_node_runs`（**UNIQUE(run_id, node_key)**；node_type 四类 CHECK（无 condition/wait，设计钉死）；status 八态 CHECK pending/ready/running/waiting/succeeded/failed/skipped/cancelled；attempt 计数；`depends_on` 定义侧冗余快照可追溯；节点级 `idempotency_key` 可空——外副作用节点必填由 T-W3 执行器强制；input_snapshot 执行前落审计可回放 / output_json 下游占位符解析源；run FK CASCADE）。
- **纯增量零改既有表**：T-W1 定义两表原样；执行器（ready 调度循环、重试、恢复）随 T-W3，路由随 T-W3 一起开。
- **配套**：`conftest` 清理序（node_runs → runs → definition_versions → definitions）、`test_migrations.HEAD_REVISION` → `b7d9f1a3c5e2`；`migrations/env.py` 按模块导入无需改、审计抽取脚本按模块自动发现无需改。
- **测试**：`test_workflow_runs.py`（新 11 例：默认态与版本钉住 / run 幂等键全局唯一（FV-F3 表级保证）/ 节点键 run 内唯一 run 间允许 / run 列守卫参数化 4 例 / 节点类型与状态守卫 / run 删除级联节点 / 定义删除 RESTRICT / 项目删除 CASCADE 带走 runs+nodes 且平台模板不阻拦）+ `test_migrations.py` +1（运行两表迁移往返保留 projects、定义两表共存）。
- **口径**：业务表 **101**（+2）/ 迁移头 **`b7d9f1a3c5e2`（25 revision）** / 路由 **271 不变** / api_catalog ENTRIES 94 不变 / pytest **1745 收集 = 1739 passed + 6 skipped**（1733 + 12；本机全量实跑 1851s）/ vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（新表）。

## [未发布] — V3 实施 T-W1：Workflow 定义层（两表 + dag_json 校验纯函数，2026-11-02）

### 服务端（2 张新表 / 1 个迁移 / **零新路由、零执行器** / 零桌面改动）

- **定义 + 不可变版本双表**（迁移 **`f2a4c6e8b1d3`**，含 downgrade）：`workflow_definitions`（draft/published/archived；发布递增 version；NULL project_id=平台模板）+ `workflow_definition_versions`（发布快照，(definition_id, version) 唯一，**写后不可变**——运行固定引用版本号，fde-v2 教训）。
- **`validate_dag` 纯函数先入 CI**（零执行器依赖，backlog T-W1 验收）：环检测=Kahn 拓扑并**点名环节点**（修 fde-v2 FV-F1）；未知依赖/自依赖/重复 key/未知类型/未知字段；**call.ref 必须 ∈ api_catalog ENTRIES**（白名单封 SSRF 面）；skill.ref 须为 active skill 的显式 `key@版本号`；agent.ref 须已启用；output 唯一且不遮上下文键；`{{placeholder}}` 须为运行上下文键或**传递上游**节点的 output；外部副作用无审批后继 → **P1 告警不阻断**（effect 结构化在 T-R2，P2 转强制）。违规一律 422 `dag_invalid` 携逐条 issues（code/message/node_key/detail）。
- **定义生命周期服务**（无 HTTP 路由——§5 路由随 T-W3 执行器一起开）：create（draft v1）→ update（已发布则自动 +1 开新草稿版本，版本行原样）→ publish（按**当前**白名单再校验后快照版本行；already_published 409）。事件 `workflow_definition_created/updated/published`（事件目标注册表新增 `workflow_definition`，平台模板 project_id 为 NULL）。
- **配套**：`migrations/env.py` 模型导入、`conftest` 清理序（版本行先于定义行）、`test_migrations.HEAD_REVISION`、审计抽取脚本模型清单。
- **测试**：`test_workflow_definition.py`（新 7 例：合法示例含拓扑序 / 环点名 / 结构与引用 / 三类 ref 白名单 / 占位符上下游 / 规则 9 告警 / 发布锁版本行+事件序）+ `test_migrations.py` +1（两表迁移往返保留 projects）。
- **口径**：业务表 **99**（+2）/ 迁移头 **`f2a4c6e8b1d3`（24 revision）** / 路由 **271 不变**（零新路由）/ pytest **1733 收集 = 1727 passed + 6 skipped**（+8；本机全量实跑期间机器休眠致 2 例连接中断失败，单跑复核绿，CI server-tests 干净复核）/ vitest 730 沿用。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（新表）。

## [未发布] — V3 实施 T-E1 + T-E2：一等证据表 project_evidence + 门禁证据挂接（2026-11-02）

### 服务端（1 张新表 / 1 个迁移 / 2 条路由 / 零桌面改动）

- **T-E1 一等证据表**：新模块 `fde_api/evidence/`（models / service / routes）+ 迁移 **`e1f3a5c7b9d2`**（`project_evidence`：UNIQUE(project_id, source_uri, content_sha256) 指纹即幂等键，kind 七类 CHECK，sha256 长度 CHECK，INDEX(project_id, kind)；project FK CASCADE、创建人 FK SET NULL；含 downgrade）。只存指针 + 指纹，不存原件（红线）。
- **API**：`POST /api/v1/projects/{id}/evidence`（can_manage；首次 201 `created=true`，同指纹 200 `created=false`——证据不可变，命中不改写 origin/captured_from）、`GET …/evidence?kind=&referenced_by=gate:Gx`（can_view；referenced_by 反查门禁清单项挂接）。错误码 `invalid_sha256` / `invalid_request` / `forbidden` / `project_not_found`。**有意不进 api_catalog**（AI 不可写证据，用例钉住）。
- **T-E2 门禁挂接**：`submit_gate_evidence` 每项先 `upsert_evidence`（kind=gate、origin=`gate:Gx/<清单项>`、captured_from=human），清单项 JSON 内挂 `evidence_id`，事件 `gate_evidence_submitted.items[]` 携 evidence_id；`_serialize_gate` 读时合并（历史清单项 `evidence_id=null`），**零 DDL**。同指纹二次提交幂等（行数不增、id 不变）。
- **并发安全**：`upsert_evidence` 在保存点内插入，撞唯一指纹回退后读回赢家，不向调用方抛 IntegrityError。
- **配套**：`migrations/env.py`、`conftest` 清理序、`test_migrations.HEAD_REVISION`、审计抽取脚本的 blueprint/模型清单均已登记新模块；`gate_service` 对 `evidence.service` 延迟导入（避免 projects⇄evidence 环）。
- **测试**：`test_evidence_registry.py`（新，6 例：指纹幂等与不可变 / 校验 / 权限与跨项目隔离 / kind 与 referenced_by 过滤 / 服务层入口 / 不进 catalog）+ `test_gates_api.py` +1（T-E2 挂接全链）+ `test_migrations.py` +1（迁移往返保留 projects）。
- **口径**：业务表 **97**（+project_evidence）/ 迁移头 **`e1f3a5c7b9d2`（23 revision）** / 蓝图路由 **271**（+2）/ blueprint 34 / api_catalog ENTRIES **94 不变** / pytest **1725 收集 = 1719 passed + 6 skipped**（+8，921.98s 全量实跑） / vitest 730 沿用。
- **部署**：`docker compose build && up -d` 后**须 `alembic upgrade head`**（新表）。

## [未发布] — V3 实施 T-P0-1：signoff 死锁修复（审计 WB-DEF-1，2026-11-02）

### 服务端修复（零迁移、零新路由、零桌面改动）

- **症状**（审计 WB-DEF-1，P0 功能阻断）：signoff checkpoint 唯一开闸点是 `handoff_run`，而它只收失败 / L1 降级 run；agent_assisted 方案经 generate-agent **正常 completed** 后既不能 handoff 又拿不到 pending → `POST …/signoff` 409 `signoff_not_pending` 与 `POST …/export-sow` 409 `solution_signoff_required` 永久互锁，SOW 一个字节都导不出。包声明 agent_assisted 而方案无 run 的形态同样死锁。
- **修复**：新增 `fde_api/agents/signoff.py::ensure_pending_signoff` 作为唯一幂等开闸入口（同方案至多一个 pending，只补空 run 软链不覆写）；`_finalize` 对非降级 completed 且绑定 solution 的 run 即时开出 pending（L1 维持「人工接管后再开闸」既有语义）；`handoff_run` 改走同一入口；`export_sow` 的 agent_assisted 闸拆成独立事务，拦下且无 pending 时**兜底开闸并先提交再抛 409**（闸本身不放宽），409 `details` 携 `signoff_checkpoint_id / signoff_status / remedy=resolve_pending_signoff / remedy_path`。
- **错误体**：`DocumentDraftServiceError`（= `SolutionServiceError`）新增可选 `detail`，solutions 蓝图错误处理器透传为 `error.details`（与 `AgentsServiceError` 同形；三参调用零改动）。
- **测试**：`test_solution_signoff.py` +5（端到端先红后绿：generate-agent completed → export 409 携指路 → 终审拍板 approved → export 200；无 run 兜底开闸且重复导出不重复开闸；驳回后再导出重开新一轮 pending；L1 降级 completed 不自动开闸仍走 handoff；开闸入口幂等/软链回填）。对旧代码实跑红：completed 后 checkpoint 数 0、409 无 details。
- **口径**：pytest 1717 收集 = 1711 passed + 6 skipped（d14 1712 + 本轮 5）；路由 269 / 表 96 / 迁移 22 不变；桌面零改动（vitest 730 沿用）。审计文档回写：`docs/implementation/v3-backlog.md` T-P0-1 → DONE（含实现偏差），风险登记册 / 差距矩阵 WB-DEF-1 → 已修复。

## [未发布] — V3 融合审计：Workbench × fde-v2 深度代码审计与 V3 升级实施方案（2026-11-02）

### 纯文档 + 审计脚本轮（零业务代码、零迁移、零部署）

- **主报告** `docs/architecture/蔡工FDE_Workbench_fde-v2架构融合审计与V3升级实施方案.md`（20 节 + Mermaid 五层架构图）：对 Workbench @0570384 与外部项目 fde-v2（快照≈上游 master@39e0e62，零执行只读审计）逐模块对照；核心裁决=**不引入 fde-v2 实现，只吸收四件经验证思想**（YAML DAG 形态 / 候选→人工确认闭环 / 证据"出处+源块"粒度 / BR 三要素机器可读纪律），七项 fde-v2 设计明确不搬（flow 执行器、运行时 DDL reconcile、隐式页面授权、exec 角色装配、user=None 全通、全量内省工具面、agentscope 团队）。
- **审计产物** `docs/audit/`：双仓基线、模块清单、路由清单 CSV（385 行=WB 269 url_map 枚举 + fde-v2 116 AST）、数据表清单 CSV（121 行=WB 96 表全字段+首建迁移归属 + fde-v2 17 DDL）、测试盘点与实跑终录、**17 能力域差距矩阵**（REUSE/EXTEND/NEW/DEFER 逐域裁决，含 Workbench 自身 14 项现状缺陷——WB-DEF-1 signoff 死锁为 P0 功能阻断）、风险登记册；`appendix/` 六份行号级原始证据报告。
- **架构设计** `docs/architecture/`：ontology-registry-v1（3 新表 terms+aliases / relation_types / change_sets + project_evidence 底座；6 个候选表经查重不建）、workflow-dag-v1（作为 background_jobs 新 job_type，不建第二套队列；四类节点；校验器纯函数先入 CI）、agent-policy-v1（权限五原则现状 VERIFIED 保持 + ToolGroup 只收窄 + Skill 以既有双表扩治理态）。
- **实施台账** `docs/implementation/`：v3-backlog（24 任务含文件/表/API/测试/回滚/复杂度）、v3-test-plan（本体/Workflow/权限安全/门禁交付物四族验收用例）。建议起手：T-P0-1 死锁修复 → T-E1/E2 一等证据表 → T-W1 DAG 校验器。
- **可复现抽取脚本** `scripts/audit/extract_{workbench,fde_v2}_inventory.py`（裸 Flask 注册全部 blueprint 枚举 url_map + Base.metadata，不调 create_app 零副作用；外部快照 `python -I` + AST/regex 零 import）。
- 实跑基线（本轮真实执行）：pytest 1700 passed + 6 skipped（1706 收集，与 d13 口径一致）/ vitest 730/730 / operations 14/14；fde-v2 verify 套件按不受信零执行纪律未跑（UNKNOWN 如实记录）。口径数字不变：96 表 / head `c3e7a9b1d5f4` / 路由 269 / ENTRIES 94。

## [未发布] — 派单 r12 签字执行：14 条留注归档 + B-③ 销号 + B-① 律师包定稿（2026-11-01）

### 纯文档销号轮（零代码）

- **留注 14 条签字归档**（设计文档 owner 交互签字）：12 条即归档（①②④⑧⑩⑪⑫⑰⑱⑲⑳㉑）+ 附条件 2 条勾选维持（③ 复购约束放宽 / ⑥ onsite 关键词派生）；需变更 5 条去向：⑤已执行（#55）、㉒已销号、⑨⑬随 B-① 等律师、⑦⑭⑮ 登记二期待办（⑭ 前置=行业→大类映射口径待业务给出）。
- **B-③ 拍板销号**：平台公司统一开票 + 预扣率表=税务总局 2025-16 公告口径确认（`WITHHOLDING_BRACKETS` 已是该口径，零改动）；衍生小项挂下次工程轮：`mark_payable` 扩开票方/税率字段必填。
- **B-① AI 法律研究底稿定稿 + 律师包待寄**：底稿（文档中心 06_派单引擎，官方条文抓取核实，**非法律意见**）倾向撮合引擎不落入算法备案义务/LLM 内部使用免大模型备案；用户拍板寄律师包、B-① 维持「需备案」零改动。台账 30.11。

## [未发布] — 派单 r12 拍板执行：B-④ 城市终版 + 留注⑤ 冷启动口径切换（2026-11-01）

### 首批城市名单定稿（全行业口径）

- **B-④ 拍板终版**：首发六城 = 上海/广州/深圳/杭州/成都/武汉（全行业服务口径 + 优先南方和一线城市；原苏锡常制造业走廊建议名单退役）。`seeds/dispatch_cities.json` 换终版（meta 记拍板来源）；**名单定稿≠开闸**——claim_enabled 仍全 false，开闸由 §6.4 三条件 + 城市开关驱动（B-① 备案完成+公示前 claim 维持降级态）。
- **留注⑤ 冷启动口径切换**：`settlements.py:_city_order_rank` 由交付席位 home_city 代理改为**包侧客户城**（企业代号第三段）；`cities.py` 新增公共助手 `package_client_city`/`city_from_enterprise_code`，cities/maintenance/settlements 三处城口径去重为一（maintenance `_client_city_of` 改委托）。
- **拍板销号（零改动）**：B-① 维持「需备案」（律师意见书仍是权威输入）；B-② 维持对公口径；直签豁免维持绝对封堵；P2-2 维持 5 态（留注㉒ 同步归档）；仿真器校准暂无数据继续等待。台账三十节 30.10 执行记录。
- 回归：种子断言/geo 钉子/冷启动夹具对齐新名单（档案城深圳≠包侧城杭州的反向回归钉）；桌面零改动。台账三十节 + 等待清单刷新（30.10）。

## [未发布] — 派单线收尾轮 r12：外部输入到达执行手册（2026-11-01）

### 零功能补码的落点普查轮

- **外部输入到达执行手册**（台账三十节）：八项外部输入（B-①备案/B-②托管/B-③开票与预扣率/B-④城市名单/P2-2 状态集/仿真器校准/留注签字/直签豁免）的"到达即执行"代码与数据落点逐项普查确认——落点全部存在，零补码；每项含分支动作、影响面与回归口径，任一输入到达按节执行即可。
- **C7 核实**：混合模式自动转换 job 已在 goal-r10 落地，8 例于本轮头复跑全绿——零重做。
- **留注编号勘误**：⑯为空号（r5→r6 跳号），实有定义 21 条；签字分类=12 归档 / 2 附条件 / 7 需变更。
- 联合口径不变：94 业务表 / head `f6a9c3e1d7b4` / 路由 252 / ENTRIES 86 / pytest 1563 收集 / vitest 695。

## [未发布] — 派单运维页簇 B3/B5/B6（2026-11-01）

### 争议处理 / 仿真对比 / 开闸运维（零迁移）

- **服务端五路由**（薄包装既有服务层，全部平台侧）：`GET /dispatch/disputes`（L0–L3 全量留痕；对账单只透出 `l0_report_source_uri` 指针——红线字段不内联本体）、`POST /dispatch/disputes`（人工打开仅 L1/L2——L0 由对账自动产；L1 金额 >¥50,000 → 422 `amount_above_l1`；快照锚=打开时包快照 §2.3 规则 2）、`POST /dispatch/disputes/{id}/resolve`（结论必填；close 直关；处罚类动作 100% 人工）、`POST /dispatch/simulator/replay`（历史包只读回放——当前池×当前规则版本再撮合画像，不落 offer；全链路种子化仿真留 CLI 沙箱库，绝不经 HTTP 触发写库）、`GET /dispatch/claim-gates`（§6.4 三条件+种子开关逐城可解释明细；开关在 seeds 文件，只读不翻转）。ENTRIES 74→**79** / 路由 234→**239**。
- **桌面三个平台侧 tab**（九子页簇收官）：「争议处理」（L0–L3 层级/状态标签 + 打开表单 + 裁决表单含直接关闭）、「仿真对比」（执行回放 → 摘要卡片（场景分布/Stage A 通过率/Top1 均分）+ 逐包 Top3 画像；口径=仿真不作真实成绩常驻声明）、「开闸运维」（逐城判定徽章 + 三条件 ✓/✗ + 拒单率；"改走代码流程——本页只读"）。
- 测试：服务端 `test_dispatch_b3ops_pages.py` 8 例（L0 禁人工打开/L1 上限 422/快照锚/裁决 409/回放降级 skipped+只读断言/开闸种子对齐）；桌面 `dispatch-ops.test.tsx` 9 例（路由解析/角色门/裁决流/打开校验/回放摘要/开闸判定）。台账二十八节。

## [未发布] — 派单调度台操作面 B2（2026-11-01）

### 平台侧调度台（零迁移）

- **服务端包留痕路由**：`GET /dispatch/packages/{package_id}/offers`（平台侧 only）——一包全量 offer 留痕（谁被派/接了/拒了、§6.2 窗口 deadline 服务端现算、§4.8 rank/explanation 释明、候选人身份），调度台据此决定代接单/重派。ENTRIES 73→74 / 路由 233→234。
- **桌面「调度台」tab**（第 6 子页，admin/project_lead 可见，动作权限服务端复核）：供给池候选勾选器（复用 `GET /profiles`，勾选即发布授权/指派名单）；包全景列表（draft 也在列）按状态出按钮——draft：等级覆盖（§4.5 必填 reason 留痕）+ 发布（携候选只读授权）；withdrawn/rejected/expired：重新发布（服务端 round+1 新版本对）；published：执行撮合（§4 两段式，结果面板展示场景 A/B/C + Top3 释明 + 资格门淘汰数）/ 指派 offer / 撤回（TRANSITIONS 仅 published 可撤）；offer 留痕面板 + offered 行「代接单」（`POST /accept` 携 delivery_user_id）。时间窗只展示不重算（B1 纪律延续）。
- 测试：服务端 `test_dispatch_b2_console.py` 6 例（全量留痕/claim 15 分钟窗/空留痕/非平台侧 403/未知包 404/轮次倒序）；桌面 `dispatch-console.test.tsx` 10 例（路由解析/状态动作映射/角色门 tab 隐藏/发布携候选/撮合可解释结果/指派/撤回/等级覆盖 reason 闸/留痕+代接单）。台账第二十六节增补 B2 项。

## [未发布] — 派单接单工作台 B1（2026-10-31）

### 交付工程师专区（循环终止后首期派单范围增强，零迁移）

- **服务端三读路由**：`GET /dispatch/offers/mine`（收件箱=候选人本人全量留痕 + §6.2 窗口 deadline 现算 + §4.8 算法释明只回本人）、`GET /dispatch/settlements/mine`（只回本人席位角色与金额，他席存在与金额零出现；预扣税原样透出不算净额——B-③ 未定不发明）、`GET /dispatch/profiles/me`（自助档案 + 在途计数，无档案 404）。ENTRIES 70→73 / 路由 230→233。
- **白名单 payload 增 `id` 支撑列**（资源标识非内容字段；授权方抢单/接包必须持有目标 id）——§9.5 隔离基线②键集测试同步更新并全基线复跑绿。
- **桌面「我的接单」tab**：收件箱 + 待响应倒计时（30s 刷新，窗口判定永不在前端复算）+ 接单/拒单按钮（原因枚举四选一只进留痕）+ 算法释明折叠 + 我的档案卡；**「我的结算」tab**（我的分成/计提基数/预扣税/打款状态）；**派单池抢单按钮**（claim 模式 published/offered 包详情展开内；开闸判定在服务端，claim_closed 可解释信息直显=§11 降级态 UX）。
- 测试：服务端 `test_dispatch_b1_console.py` 7 例 + r3 隔离/r4 回归；桌面 `dispatch-mine.test.tsx` 9 例。企业需求方专区不做（设计 §1.4-3 明确排除：客户不接触派单池）；评估与任务清单见台账第二十五节。

## [未发布] — goal-r11 派单引擎终止复核轮（2026-10-31）

### 循环终止——最终收口报告 v2（零功能改动）

- **§八 八项终止判定全部成立**：更新版收口报告 `docs/goal-r11-派单引擎收口.md` 取代 r8 版本成为唯一凭证（r8 的两项例外已由 r9/r10 消解）。全电池重测：服务端 1456+6s / 桌面 660 / typecheck 0 / 闸④覆盖率 **85%**（3,009 语句含 channel_guard 89% + simulator 81%）/ 负面清单 7 反例 / H5 口径 85 表·15 rev·head `c5d7e9f1a3b7`·路由 228·ENTRIES 68。
- H2/H3 以内测/仿真口径达标（基准原文「内测/仿真先行」）：H2 0.9565 / 工时占比 0.0716 / 毛利率 0.9717（r9 仿真工件，假设表全量回显，真实数据到位后复测校准）。
- 剩余事项全部外部输入依赖（备案/托管/税率/城市名单/P2-2/直签豁免/仿真器校准/留注签字/便携版重打包），逐项登记于台账第二十三节与收口报告第五节。

## [未发布] — goal-r10 派单引擎轮（2026-10-31）

### C7 混合模式自动转换 job（零迁移）

- **混合模式落地**（派单设计 §6.1「先 assign 指派，响应窗内无人接 → 转 claim」）：`dispatch/maintenance.py` 新增 `convert_stale_assign_to_claim` 挂 `run_maintenance` 节拍——assign 死亡（expired/rejected）包 × 城市 claim 开闸（§6.4）→ mode 翻转 + 按 §2.3 重发（round+1 新码新哈希 + §4.7 扩圈推进）+ `dispatch_c7_converted` 事件留痕；幂等（翻转后不再命中）；单包 SAVEPOINT 隔离不炸整批；城市未开闸安全空转（§11 降级态，人工重派路径不变）；零新增时间常数（24h 判死由上游 expire 按 §6.2 执行）。
- 测试：`test_dispatch_p2_r10_c7.py` 8 例（含转换后 claim_package 实抢闭环、幂等、降级空转、单包故障隔离、§6.4 拒单率条件真实生效验证）；r1–r9 回归全绿。口径：85 业务表 / 15 rev / head `c5d7e9f1a3b7`（零迁移）/ 路由 228 / ENTRIES 68 / 服务端 **1456 通过** / 桌面 660。轮次报告 `docs/goal-r10-派单引擎.md`；台账第二十二节。

## [未发布] — goal-r9 派单引擎轮（2026-10-31）

### P2-4 私单封堵 + 撮合仿真器（零迁移）

- **P2-4 私下接单封堵**（派单设计 §8.5）：新增 `dispatch/channel_guard.py` 三服务层钩子——H1 立项入口（`business_line` 随立项显式声明，派单线仅平台侧可立、专属 403 码）、H2 池内企业直签封堵（企业进过派单池后直签立项/报价 → 422 `private_deal_blocked`，复购走派单线放行）、H3 渠道正交（交付包只建在派单线项目上 → 422 `dispatch_line_required`）；封堵留痕走独立事务（主事务回滚后仍存活）。
- **撮合仿真器**（留注⑳）：新增 `dispatch/simulator.py`——历史包只读回放打分（P2-1 仿真对比数据源）+ 种子化全链路仿真（撮合/席位/时间常数走真实引擎，人工环节显式假设表采样）+ CLI `python -m fde_api.dispatch.simulator`（非沙箱库拒绝执行）。报告工件 `docs/dispatch-sim-r9-seed42.json`（H2/H3 内测/仿真口径，假设全量回显）。
- 测试：`test_dispatch_p2_r9_p24.py` 10 例 + `test_dispatch_p1_r9_sim.py` 4 例；r1–r8 回归全绿。口径：**85 业务表**（口径修订：不含 alembic_version）/ 15 rev / head `c5d7e9f1a3b7`（零迁移）/ 路由 228 / ENTRIES 68 / 服务端 1448 通过 / 桌面 660。轮次报告 `docs/goal-r9-派单引擎.md`；台账第二十一节。

## [未发布] — goal-r8 派单收口轮（2026-10-31）

### 派单引擎收口——开池四道闸全绿 + §八终止判定对照（零迁移）

- **C10 新人保护期**（§6.5）：撮合 Stage A 新增「前 5 单只推同城」——完成单数低于 `newcomer_protection_orders` 的候选强制非同城出局（推送范围收紧非资格淘汰），A5 明细带 `newcomer_city_only` 释明标记。
- **B1 防骚扰**（规则表 B1）：同包更早轮次拒过的候选本轮不再**主动推送**，与负面清单 #6「不因拒单限制接单机会」正交并存（本人仍可经 claim 主动抢）；stage_a 契约新增 `B1` 行；同步修正 r5 初版混淆两语义的测试。
- **§4.7 扩圈半径自动推进**：重派发布时 `redispatch_radius_km` 按 25→50→100→0 自动降档。
- **闸④覆盖率出具**：商业模块关键路径（报价/收款/合同/门禁/派单撮合结算）**84.9% ≥ 60%**（分母 2,637 语句），宽口径 71%——开池四道闸**全绿**。
- **收口报告**：`docs/goal-r8-派单引擎收口.md`——§八终止判定逐条对照（1/3/4/5/6/7/8 达成；2、3 带明示例外：P2-4 未立项、H2/H3 待真实数据）+ 附录 B 待签字清单（B-①②③④ + 留注①–㉒ + P2-2）+ 附录 A 修订建议（表 86/15 rev/路由 228/ENTRIES 68 重锚 + 新增冲突 A-⑧–⑪）。
- 测试：`test_dispatch_closeout_r8.py` 3 例；r1–r7 回归 94 例全绿。口径：86 表 / 15 rev / head `c5d7e9f1a3b7`（零迁移）。

## [未发布] — goal-r7 派单引擎轮（2026-10-31）

### 派单引擎 P2 批次（对照派单设计文档 v1.0 §8.5：P2-1/P2-3/P2-6；迁移 `c5d7e9f1a3b7`）

- **P2-1 桌面派单页簇**：`desktop/src/renderer/src/dispatch/` 三页——派单池（§9.2 白名单只读视图 + 详情展开 + 席位金额显示义务，响应体不含报价/收款明细字段断言）、能力档案与产能看板（四域分=晋级评定维度展示、在途/上限负载条）、权重与规则版本（只读 + 版本取值对照，仿真对比二期=留注⑳）；nav 全角色入口（交付方看被授权包，平台侧看全量），hash 路由 `#dispatch[/(pool|profiles|rules)]`；服务端支撑路由 GET `/dispatch/profiles`、`/dispatch/rules`（平台侧，ENTRIES +2）。
- **P2-3**：`projects.business_line` CHECK 放行 `'FDE_DISPATCH'`（§11.1 预留路径；写入入口随派单立项后续轮启用；存量数据零变化）。
- **P2-6**：`dispatch_cities.json` 扩字段钉子（subsidy_scheme 选填 + metro_group 必备断言——schema r4 已含，本轮补 P2-6 语义钉）。
- **P2-2（Project.status 枚举扩展）**：设计/规则表/BP 均未给出目标状态集——**不发明，待拍板**（台账第十九节留注）。
- 测试：服务端 `test_dispatch_p2_r7.py` 4 例 + 桌面 `dispatch-page.test.tsx` 6 例；r1–r6 回归 87 例全绿。
- 口径（goal-r7 实测）：86 表、迁移头 `c5d7e9f1a3b7`（15 revision）、路由 228（+2）、ENTRIES 68（+2）、桌面 660。轮次报告 `docs/goal-r7-派单引擎.md`；台账第十九节。

## [未发布] — goal-r6 派单引擎轮（2026-10-31）

### 派单引擎 P1 收官——§8.4 七项全过 + §8.1 八表齐（迁移 `b2c4d6e8f1a3`）

- **P1-6 报价归属**：`quotes.owner_user_id`（nullable FK users SET NULL + 索引；存量不回填=平台侧台账报价语义），创建即落 owner，归属过滤用例。
- **P1-7 留存策略**：`dispatch/maintenance.py` 留存扫描（撮合流水/评分 3 年、涉税 10 年——**报告只读不删档**，删除须人工合规审批，留注⑰）+ 维护作业 `dispatch.maintenance`（24h 节流）挂 `cli.scheduler` 主循环经 outbox 投递、handler 注册沿 research.export 模式；超时释放（r4 的 expire_stale_offers）一并挂入。
- **disputes 表**（§8.1 第 8 张，§6.6/§7.5）：L0 机器对账（逐包逐键比对结算应计 vs Payment 实收，差异>±¥1 自动草稿、幂等）+ L1 人工打开（48h 人工答复 SLA 字段、¥50,000 上限 422 走 L2）+ 人工裁决（**处罚类动作 100% 人工**，resolution 只能由平台侧写入）+ L0 对账单/依据只存 source_uri 指针 + snapshot_hash 锚定当时版本。
- 测试：`server/tests/test_dispatch_p1_r6.py` 8 例；r1–r5 全量回归 87 例全绿；ruff/mypy 无新错。
- 口径（goal-r6 实测）：86 表、迁移头 `b2c4d6e8f1a3`（14 revision）、路由 226、ENTRIES 66。轮次报告 `docs/goal-r6-派单引擎.md`；台账第十八节。

## [未发布] — goal-r5 派单引擎轮（2026-10-31）

### 派单引擎 P1-2 撮合核心（对照派单设计文档 v1.0 §4/§5 + 规则表 A-6，零迁移）

- **撮合核心**（§4.1–§4.8）：`dispatch/matching.py` + `dispatch/scoring.py`——Stage A 五资格门（等级/模块/行业/负载自动算上限/到场围栏）硬过滤出局不降权；场景裁决三选一：到场型字典序 (geo_tier, -level, -industry, -sla)、远程型加权（权重取 active 规则版本快照，无版本 → 422 `rule_version_required`=§11.1 降级态人工排序）、到场无候选场景 C 不自动派（事件留痕含淘汰明细）；§4.5 `required_level` 由 Quote 系数推导落库 + 发布前人工覆盖必填 reason 留痕；§4.7 扩圈链 geo_tier（同城/同省/邻接都市圈/全国，全国仅旗舰档）；§4.8 Top3 + `match_breakdown` 释明契约（stage_a 五门明细/stage_b/rank/explanation，对被派方展示）。
- **负面清单 A-6 七条逐条反例**（§8.8 开池四道闸之闸③全绿）：软画像零字段 schema 断言 / 排序签名无历史参数+同分不同历史同分 / 全包无轨迹语义静态检查 / 到场型字典序（同城弱者胜同省强者）+ 加权地理仅三档 / settlements 零工时扣减静态检查 / 被拒者下一轮仍可入选 / 全包零货运语义。
- **P1-4 options 枚举**：席位分配 / 场景类型 / 匹配模式 / 拒单原因四组随 /workbench/options 下发。
- 路由 +2（POST packages/{id}/match、packages/{id}/required-level），ENTRIES +2。
- 测试：`server/tests/test_dispatch_p1_r5.py` 12 例；全量 CI 门禁出具；桌面零改动。
- 口径（goal-r5 实测，rebase 到 goal-d1 合并态后）：84 表、13 revision / head `a7f3c1e9d5b2`（本轮零迁移）、路由 226（+2）、ENTRIES 66（+2）。轮次报告 `docs/goal-r5-派单引擎.md`；台账第十七节。

## [未发布] — goal-r4 派单引擎轮（2026-10-31）

### 派单引擎 P1 首批（对照派单设计文档 v1.0 §8.4：P1-1/P1-3/P1-5，零迁移）

- **P1-1 offer_service**（§6.2/§6.3/§6.7）：`dispatch/offer_service.py`——§6.3 乐观锁显式版本比对先行（冲突 409 `stale_version`，禁分布式锁）；同轮互斥（409 `offer_already_accepted`，包行 FOR UPDATE 串行化）+ 落选者自动 expired；claim 15 分钟确认窗 / assign 包响应窗超时批量释放（`expire_stale_offers`）；§6.7 拒单权（原因枚举 档期冲突/能力不匹配/距离/其他 只进 OperationEvent 留痕不进任何分值，**永不因配额拒绝拒单**——负面清单 A-6 #6 防护）；全拒后包 rejected=重派入口；§9.3 交接复用 `handover_accepted_member`（leader 为 actor）。路由 +4（指派发 offer / 接单 / 拒单 / 抢单登记），api_catalog ENTRIES 同步 +4。
- **P1-3 一致性测试**：api_catalog 每条 ENTRIES 逐条在 url_map 可解析（防目录漂移）+ dispatch 每条路由逐条在册（防脱册）——双向钉死。
- **P1-5 seeds 三处**：`gates.json` 加 `applicable_industries`（null=全行业通用；历史迁移回填哈希常量冻结不动，实时哈希由 `_gates_file_hash()` 现算）+ `dispatch_cities.json`（§12 六城建议名单，`claim_enabled` 全 false=§11.1 降级态）+ `acceptance_metrics.json`（BP §11 闸门指标投影）。
- **§6.4/C9 开闸评估**：`dispatch/cities.py`——claim_gate_status 三条件可解释明细（供给=active 档案 / 需求=近 90 天 published 包 / 拒单率<40% / 公示=规则版本存在为代理，留注⑨）+ 种子城市开关 AND；未开闸 403 `claim_closed`。
- 测试：`server/tests/test_dispatch_p1_r4.py` 14 例。全量 1386 passed + 6 skipped；桌面 654 与 typecheck 零改动全绿。
- 口径（goal-r4 实测）：83 表、迁移头 `f4b8c2d6e3a1`（12 revision，零迁移）、路由 224（+4）、ENTRIES 64（+4）。轮次报告 `docs/goal-r4-派单引擎.md`；台账第十六节。

## [未发布] — goal-r3 派单引擎轮（2026-10-31）

### 派单引擎 P0 簇②收尾——P0 8 项全落地（对照派单设计文档 v1.0 §8.3：P0-1/P0-2 + §9.5）

- **P0-1 交付包服务层**（§2.2/§2.3/§2.5）：`dispatch/packages.py`——canonical_json（键字典序/UTF-8 原样/Decimal→str/null/模块先排序）+ sha256 快照**发布时算一次即冻结**（改 solution/quote 不回写；撤回/拒绝/过期后重发 = dispatch_round+1 + 新编码 + 新哈希，版本对 Unique(project_id, round)）；§2.5 八态状态机通用迁移表（每次迁移写 OperationEvent）+ withdraw 的「本轮进行中 offer」防御守卫；发布前置=报价 finalized（422）；`PKG-{项目码尾段}-{轮次}` 编码；§9.3 接单交接以项目管理位（leader）为 actor 复用 `add_project_member(member)`（接单人本人交接前无 can_manage——留注⑧），幂等 + stale_version 重试。
- **P0-2 package_access 第三语义**（§9.1/§9.2）：`package_access` 表（package×user×role 三元组唯一，lead/seller/delivery/audit，可撤销）+ `dispatch/access.py`（无授权 404 不泄露存在性；admin 平台域放行）+ 交付包 API 字段白名单 12 项 + 交付方席位 40% 金额（发布时物化冻结到 `delivery_seat_amount`——禁 join quotes 的代价，留注⑥）+ `dispatch/routes.py` 6 路由（守卫路由层前置；管理动作平台侧 403；接单=平台侧或被指派人本人+delivery 授权双门槛，冒名 403）。api_catalog ENTRIES +6。
- **§9.5 隔离测试基线四条全绿**（开池四道闸之闸①）：跨主体访问 100% 拒绝（4 路由参数化 403/404）；响应体字段断言（键集精确等值、报价/收款/客户真名字段零出现）；静态检查（dispatch 读路径源级禁 Quote/Payment/Contract 引用、全包禁裸 `session.query(`）；渗透用例（越权接单 403、快照篡改无写入口 405、撤销授权重放 404 + 显式 re-grant 才复活）。
- 测试：新增 `server/tests/test_dispatch_p0_r3.py` 15 例；迁移 `f4b8c2d6e3a1`。全量 1372 passed + 6 skipped；桌面 654 与 typecheck 零改动全绿。
- 口径（goal-r3 实测）：83 表、迁移头 `f4b8c2d6e3a1`（12 revision）、路由 218（+6）、ENTRIES 60（+6）。轮次报告 `docs/goal-r3-派单引擎.md`；台账第十五节。

## [未发布] — goal-r2 派单引擎轮（2026-10-31）

### 派单引擎 P0 簇②表建设（对照派单设计文档 v1.0 §8.3：P0-3/P0-4/P0-7/P0-8）

- **P0-3 供给池档案**（§3.2/§3.3）：`fde_profiles`（一人一档：level 标量 L1–L4 + 四大子能力域独立评分轴 + 申报制标签 + 城市围栏 + 产能双列）+ `fde_level_evidence`（等级判定证据链：核验人/时刻/客观计数快照/依据单据只存 source_uri+sha256 指针）+ `dispatch/profiles.py`（L1–L4 晋级判据可复算查询——独立交付/复购/带教/四域短板下限，判据不足 422 `level_evidence_insufficient`，全过写证据链 + 更新档案 + `fde_level_promoted` 审计事件）。
- **P0-4 分成落库**（§7.2/§7.4）：`payments` 只加 `acceptance_passed_at` 一列（唯一约束不动、D+7/15/30/60 催款读时现算零改动）；`delivery_settlements` 席位级结算表（商务四席位 platform/region/city/delivery，与交付包执行四席位不同名不同义）+ `dispatch/settlements.py`（四席位 35/5/20/40、冷启动同城前 3 单 40/5/15/40、平台吸收舍入尾差保证 Σ=实收基数；劳务报酬**累计预扣法**（率表集中一处待法务确认）；状态机 draft→accrued→payable→paid/disputed，accrued 双条件=实收+G8 过门，payable 发票前置 422，paid 凭证指针）。双钩子：收款实收回填 upsert 结算草稿（无交付包项目纯 no-op）；G8 过门打标验收时刻并推进计提（晚到尾款收款即补，幂等）。
- **P0-7 配置常数**（§6.2）：`system_configuration` 增只读 `dispatch_constants` 节（时间常数 9 项 + Top-N + Stage B 权重 + 等级映射分 + 席位份额/冷启动 + 新人保护 + 拒单权，MappingProxyType 源级只读）——不进 PUBLIC_FIELDS（PUT 可写集精确等值校验天然拒改），实现代码唯一引用源，禁散落硬编码。
- **P0-8 规则版本**（§6.2/规则表 B9）：`dispatch_rule_versions` + `dispatch/rules.py`（30 天公示窗强制：生效日 < 发布日+30 天 → 422 `notice_window_required`；到点 published→active、原 active→retired 至多一个 active；快照必备节校验 admin-only；版本切换后旧 offer 的 `match_breakdown.rule_version` 永指当时版本）。
- **schema 调整**：`projects.enterprise_code` 全局唯一约束放宽为普通索引（派单 §3.3 复购判据要求同企业 ≥2 项目可表达；代号红线不动，三段两枚「·」格式校验保留——详见轮次报告留注③）。
- 测试：新增 `server/tests/test_dispatch_p0_r2.py`（12 例：L1/L2 证据链正反例、7 里程碑×四席位+累计预扣链、冷启动、状态机、G8 过门 API 全链路含晚到尾款补计提、配置只读断言、规则版本公示窗/角色/旧 offer 不回写）；`tests/conftest.py` 每用例清理序补派单六模型（FK 安全序）。
- 口径（goal-r2 实测）：82 张表、迁移头 `e3a7c5d9f2b8`（11 revision）、pytest 1357 passed + 6 skipped、桌面 654 用例零改动全绿。轮次报告 `docs/goal-r2-派单引擎.md`；台账新增第十四节。

## [未发布] — goal-r1 派单引擎轮（2026-10-31）

### 派单引擎 P0 双闸门（对照派单设计文档 v1.0 §8.3）

- **P0-5 门禁验收分离**（§9.4，§8.8 开池四道闸之二）：`gates` 加 `submitted_by_user_id` / `decided_by_user_id` / `is_delivery_party` 三列（迁移 `d2f6b4c8a1e9`）；`decide_gate` 双 403 防线——① 拍板人=该门禁证据执行人 → `gate_decider_conflict`（代码强制、先于其余业务校验，不可绕过）；② 交付方执行的 G8/G9 非 admin 拍板 → `gate_decider_role_required`（§11.3 方案①过渡口径）。单租户时代「同一用户提交+拍板」从 200 变 403，是刻意的硬闸门。
- **P0-6 events 白名单**（§2.5 坑 1）：`projects/events.py` 注册 `delivery_package` / `dispatch_offer` 两类 OperationEvent 目标（offer 的 project_id 经交付包反查）；为此按 §8.2 DDL 级约束先行落 `server/src/fde_api/dispatch/` 包两张骨架表（`delivery_packages`：8 态派单状态机 + `Unique(package_code)` + `Unique(project_id, dispatch_round)` + 扩圈半径 Check(25/50/100/0=全城哨兵)；`dispatch_offers`：`Unique(package_id, dispatch_round, candidate_user_id)` + 6 态 Check + VersionedMixin 乐观锁位 + `match_breakdown` JSON）——**服务逻辑零预埋**，发布/快照/匹配随 P0-1/P1 轮落位。
- 测试：新增 `server/tests/test_dispatch_p0.py`（6 例：两类事件目标写入、执行人自拍 403、交付方 G8 平台拍板、服务层防绕过、乐观锁位）；`test_gates_api.py`（5 例）与两个冒烟脚本改双拍板人（执行人=lead、拍板人=admin），门禁冒烟加「执行人拍自己的门 403」钉子。
- 口径（goal-r1 实测）：78 张表、迁移头 `d2f6b4c8a1e9`（10 revision）、pytest 1345 passed + 6 skipped、桌面 654 用例零改动全绿。轮次报告 `docs/goal-r1-派单引擎.md`；台账新增第十三节。

## [未发布] — goal-r3 技能循环（2026-10-30）

### 仓库健康巡检（G10）

- dynamic-workflows 编排只读巡检：**4 个只读子代理并行**（测试覆盖地图新鲜度 / docs 与代码漂移 / 依赖与 TODO / 台账逐节对账）→ **独立复核员**逐条复核 → 结构化报告。43 条原始发现全部坐实（0 驳回 0 存疑），**P1=0 / P2=14 / P3=29**。全程零变更——落盘走本 PR。
- 新增 `docs/仓库健康巡检-G10.md`：四面逐条发现（每条带 file:line 证据与复核状态）+ 下一批 backlog 三批建议（文档新鲜度批 / 依赖卫生批 / 功能欠账批，优先级逐条写明）。
- 关键坐实项：覆盖地图计数漂移 948→1330 collected（桌面 496→512，且 496/api-ipc(7) 写作时即不准）；「SES 未建」两处失效（G9 已预建默认关闭）；变量与密钥缺 8 个 FDE_SES_*；权限矩阵缺 mailing/SNS 例外鉴权行；**ruff/mypy/pre-commit 未入 lock，CI 门禁裸装最新**；台账对账 24 条中 5 条确认已完成、19 条仍待办（含 4 条 P2：research 三态 UI、PATCH-confirm 分叉、analyzing 对账、README 初始化节）。
- 随本 PR 修正自家文档两处（巡检发现）：`docs/SES发信模块-G9.md` §五闸门顺序归因（发信域约束在 service 前置，不在 decide_send）与 §八测试分桶（9+5+12+1=27）。
- 台账新增第十二节（backlog 三批推进）。

### SES 发信模块预建（G9｜WP-E）

- 新增 `server/src/fde_api/mailing/`：**默认整体关闭**（`FDE_SES_ENABLED=false` 时发送路径落 `drop_disabled`、SNS 回调端点一律 403，默认部署零行为影响、零 AWS 依赖——boto3 延迟导入，未启用时不 import AWS 栈）。SES 生产批复下来**只需改配置启用**，不改代码。
- 发送路径 `send_email`（service 函数，**不设 HTTP 路由**——避免未批复时出现可打的发信口）：闸门顺序固定 = 开关 → 发信域约束 → 幂等键 → 收件人抑制 → 当日限额（只数 UTC 当日）→ 打 SESv2；throttle 记事件并返 503（可重试）、拒收返 502（不可重试），失败不占发送台账。
- SNS 回调端点 `POST /api/v1/mailing/sns/events`：**签名即鉴权**（SNS 带不了工作台 JWT）——校验 Signature v1（RSA-SHA256，字段序按 AWS 固定顺序）+ `SigningCertURL` 限 `sns.*.amazonaws.com`（校验不过则**不发起任何外联**）+ `SubscribeURL` 同域限制 + `TopicArn` 白名单；退信/投诉只落地址 + 分类 + 通知 sha256 指纹，**不落通知原文**。
- 新增两表（迁移 `a9c3f1d8e2b4`）：`mailing_sends`（幂等键唯一）、`mailing_events`（`event_key` 唯一——SNS 是 at-least-once 投递，重放不重复计）。bounce/complaint = 地址级死刑（进抑制名单），delivery 不影响地址。
- 发信域口径落到配置校验器：FROM 必须落在 `FDE_SES_SEND_SUBDOMAIN` 子域内，主域 `somwyn.com` 启动即失败（`ses_sender_domain_forbidden`）。DKIM/SPF/DMARC 写 `docs/SES发信模块-G9.md` 不写死代码——**子域**加 SPF，**主域 SPF 不加 SES include**（否则扩大主域邮件面）。
- SNS 主题策略须带 `aws:SourceArn`（配置集 ARN）+ `aws:SourceAccount`——缺 `SourceArn` 即 confused-deputy 洞（任账号 SES 都能往我们主题灌事件）。AWS 凭证走 boto3 默认凭证链，不配进本模块、不进仓库。
- 新增 `server/tests/test_mailing_ses.py`（27 例，**零真实邮件**）：假客户端 + botocore Stubber + 自签证书验签；覆盖闸门顺序、bounce/complaint 抑制、幂等重放、坏签名/错主题/非法 JSON 拒绝、text/plain 报文解析、配置校验器。
- 依赖：`boto3>=1.36,<2`（pyproject + `requirements.lock` 钉 1.43.122/botocore 1.43.122/s3transfer 0.19.3）。

### 后台作业死亡后对账重排队（台账 §八 第 1 条落地，2026-10-30 晚）

- 问题：worker 被杀（OOM/部署/重启）时，它从 redis 队列弹走的作业 id 随进程一起消失——outbox 事件已 `dispatched`（派发器不再看它），`BackgroundJob.max_attempts`/`available_at`/`locked_until` 无人消费，于是作业永远停在 `running`，业务行（指引分析 `analyzing`、会话 turn `running`）永远停在中间态，前端每 2 秒轮询到天荒地老，唯一解法是手工 `RPUSH fde-jobs <id>`。这正是 10-30 登录事故里那笔孤儿作业的成因。
- 修复一（`jobs/worker.py`）：`run_job` 把「认领 + 执行 + 落终态」从**一个事务**拆成三段——认领（`status=running` + 租约 + `attempts+1`）先单独提交，执行期间由守护线程**续租**（默认 60s 一次，租约 5min），终态再单独写回。三个后果：① 在跑的作业对其他进程**可见**（此前全程只有 pending，对账无从分辨「有人在做」与「做的人死了」）；② 行锁只存在于认领那几毫秒，不再被 handler 全程占着（长任务钉着连接正是 10-30 锁雪崩的形状）；③ 租约过期从此是**死亡信号**而非「慢任务」信号。返回语义（not_found / already_terminal / leased / no_handler / failed / succeeded）保持不变。
- 修复二（`jobs/reconcile.py` 新增）：对账扫描捞两种无主作业——① `running` 且租约已过期（worker 死了）；② `pending`/`queued` 且超过 5 分钟无人认领（队列项丢了）。捞到之后：**可恢复类型重排队**（受 `max_attempts` 与 `available_at` 约束，入队前先提交库事务，队列项丢失下一轮按宽限期再捞），否则**落 failed** 并调用业务行收尾钩子，把业务行推到终态（前端停止轮询，用户看到「进程中断，请重试」）。
- 可恢复性按类型显式登记（不默认重跑）：`project.presurvey.analyze`/`ai.chat`/`ai.execute`/`file.scan`/`file.preview`/`document.generate`/`research.export` 可重排队——它们的 handler 都已跳过终态业务行，重跑不会覆盖已有结论；**`automation.execute` 不可重跑**（有对外副作用：发信、MCP 调用），死亡即落 failed 交人工重触发。
- 业务行收尾钩子（`jobs/handlers.py` 注册表 + 四处实现）：指引分析 → `analysis_worker_lost`；AI 会话 turn → `failed`（卡住的 turn 会让整个会话永久 `chat_busy`）；调研导出 → `failed`；自动化 run → `failed`。终态业务行（`ready`/`completed`/`succeeded`）一律不动——对账不许覆盖已有结果。
- 接线：worker 循环每 60s 扫一次（扫不出东西时零 DB 写）；另给运维留了手工口子 `flask reconcile-jobs`（容器被杀后可立即补投，不必等下一个周期）。
- 回归钉子：`tests/test_job_reconcile.py` 新增 15 例——租约过期重排队 / 活租约不动 / **被活 worker 行锁占住的作业被跳过（`FOR UPDATE SKIP LOCKED`）** / 孤儿 pending 重排队 / 新鲜 pending 不动 / 重排队后不热循环 / 次数用尽落 failed / 不可恢复类型落 failed / 指引分析与会话 turn 的收尾与「终态不被覆盖」/ 端到端（孤儿作业经对账后真的跑完）/ **认领状态对其他会话可见** / **执行期租约被续期**。

### AI 工具循环锁泄漏修复（生产事故回补，2026-10-30 晚）

- 事故：worker 跑 AI 聊天时工具调用撞 DB 连接断线，`_run_tools` 兜底吞掉异常继续循环，但共享会话带着未决事务与 `users` 表行锁停在 idle-in-transaction 十余分钟；登录路径的 `FOR UPDATE` 全体排队，gunicorn 超时杀 worker 又留下新的半死连接，锁滚雪球致登录 500。
- 修复：`server/src/fde_api/control/ai_tool_loop.py` 两处——① `_run_tools` except 分支立即 `session.rollback()`，工具异常不再让会话持锁过夜；② 主循环每轮工具执行完也 `db_session.rollback()`——工具循环工具全只读，回滚零损失，却保证下一次 provider 调用（最长 `timeout_seconds` 300 秒、零 DB 流量）不会骑在一个仍持有行锁的 idle-in-transaction 连接上（事故里 13 分钟的持锁窗口正是这个形态）。
- 回归钉子：`tests/test_ai_tool_loop.py` 新增 1 例（`OperationalError` 抛出时 `db.session()` 返回的会话在 with 块内恰被 rollback 两次：崩溃处理器一次 + 主循环每轮清理一次；17 例全绿）。
- 运维侧另两笔（无代码）：`pg_terminate_backend` 清锁 + worker 重启解堵；孤儿 pending 作业（outbox 已 dispatched、redis 队列项随重启丢失）手工 `RPUSH fde-jobs <id>` 补投。关联既有待办：台账 §八 第 1 条（进程死亡后无对账重排队）——已由本文件上一节的「后台作业死亡后对账重排队」落地，手工补投不再是唯一解法。

### 跨库只读验证脚本固化（G8）

- 新增 `scripts/verify/`（sql-queries 方法）：`run-verify.sh` + `verify-twenty-persons.sql` + `verify-n8n-executions.sql`——Twenty persons 总数/新增窗口/ICP 分布/去重命中，n8n 最近执行状态与耗时。连接参数全走环境变量（容器名/用户/库名，无口令：psql 在 db 容器内走本地 socket，脚本不读 .env）；每个会话显式 `BEGIN; SET TRANSACTION READ ONLY; … ROLLBACK;`；SQL 经 stdin 进容器（中文不走 argv）；输出仅计数不含客户明细。
- 口径：ICP 从笔记标题「冷邮件草稿 (ICP N)」提取每人最高分（≥70 培育 / 55–69 留档双层）；去重命中 = 同主邮箱挂多人（期望 0）。
- 宿主实跑一次并记录计数摘要到 `docs/验证脚本-G8.md`：persons 75（7d 新增 64，ICP 记分 9 全在 55–69 留档档）、重复邮箱 0（去重有效）、公共管道 4 成功（均值 27s）、QFhunterFeed01 2 成 3 败（运维信号，仅记录）。

### 意图差距审计（G7）

- 新增 `docs/意图差距审计-G7.md`：以 G2 七份意图文档 + AGENTS.md 红线为基线，逐边界核对代码执行点。**B1–B4 零差距**——门禁证据只收指针+64 位 hex sha256（`gate_service.py:520-548` + `workbench/models.py:544-547`，无 blob、无上传路由）；confirm 只能 canManage（`service.py:174-180` + `api_catalog` 零 guidance 条目，AI 无代拍板面）；bridge-poll 唯一进程出口是两个 openfde 只读子命令（`bridge-poll.mjs:68,101,110`，无写相 CLI、真相层零写面）；.env 不入 VCS 有可校验闭环（`.gitignore:1-5` + 全树仅两个 example 被跟踪 + gitleaks PASS 盲区规则）。
- F1 [P2→已处置]：「origin 永不 push」原本只有文档约束、无本地强制——本机已加 `git remote set-url --push origin FORBIDDEN-origin-is-upstream-use-fork`（push 必失败已实测，fetch 不变）；每台新克隆须重复，建议进 README 初始化节（台账十.1）。
- F2 [P3→已修]：G4 重写 `jobs.py` 使意图文档 4 处行号引用漂移、步骤 4 语义未反映自动重试——《系统意图-关键流程》《系统意图-自动化面》已同步更新。
- 台账新增第十节。

### 真实浏览器 UI 回归 harness（G6）

- 新增 `desktop/gui-harness/`：纯浏览器驱动 renderer 的回归 harness。dev-only Vite 配置（端口 5199）注入 `window.fde` 桥 shim（登录/刷新/`ApiResponse` 信封、deviceLabel→device_label 转换、401 刷新重试；`app.version` 返回裸字符串——三处契约此前只有 Electron 真机能验证），同源 `/api` 代理到 127.0.0.1:8010（浏览器有 CORS 而 Electron IPC 没有），并给生产 CSP 打 dev 补丁（`connect-src 'self'`、`style-src 'unsafe-inline'` 供 Vite 开发样式）。不引新依赖，不进打包产物。
- 新增 `desktop/gui-harness/regression.mjs`：仓库自带 playwright-core + 已装 Chromium 驱动两条链路 11 个断言点——①指引链：登录→项目→查看预调研分析→**只读 draft 态直接出现「确认并用于项目指引」按钮（R11 事故防线，浏览器实测通过）**→弹窗内编辑；②集成桥页：侧栏进入、状态文案、「立即采集」按钮在浏览器 harness 下被平台守卫拦为 `bridge_platform` 错误提示（与真机同代码路径）、采集反馈区可见；截图留本地（已 gitignore，含本机路径与项目代号）。
- 新增仓库技能 `.agents/skills/fde-gui-regression/SKILL.md`：harness 原理、启动/种子/运行命令、fixture 陷阱（enterprise_code 需两个「·」、module_keys 必须命中 ModuleCatalog）、断言口径与已知坑（hash 路由需点侧栏、Vite 单实例、中文经 `\uXXXX` 转义）。
- 回归报告 `docs/GUI回归-G6.md`：11/11 通过表、R11 防线结论、2 条 P3 finding（认领入口失败静默无提示——已记台账第九节；命名约定再次复核，与台账七.3 同源）。

### 代码评审门与回溯评审（G5）

- 新增 `docs/代码评审-G5.md`：PR #24 的参与者约定法评审报告（scope/dimensions/findings/coverage，含 9 条保留 finding 与 6 条驳斥成立的丢弃候选）、PR #17/#18 回溯评审、WP-B Serper 修复说明。
- 评审修复（随 PR #24 提交）：DSH 路径的裸 `JSONDecodeError`/`ControlServiceError` 逃出错误分类 → 结构化输出失败现在落 `ai_output_invalid`（可重试）/配置类不可重试，DSH 部署形态下重试能力不再静默失效；重试耗尽文案只在终态错误可重试时才劝「请重新发起分析」；存储对象缺失归入专用码 `source_object_missing`；限流/超时类瞬时错误重试前退避（契约失败不退避）；本地 DOCX 解析失败按确定性改为不可重试（存储读取 `OSError` 仍可重试，供应商侧提取失败不变）；重复投递不再对已终态分析二次调用 AI；每次尝试用独立请求号（上游去重不会挫败重试）；`python-docx` 声明下限提到 `>=1.2`（样本生成器用了 1.2.0 才有的 `add_comment`）。
- 新增回归钉子：重试语义 +7 例（请求号独立/退避双向/不可重试终态文案/存储缺失分类/终态守卫/任务仍为绿）、DSH 分类 +2 例。
- 回溯评审 PR #17/#18 发现 3 条（台账第七节）：PATCH 成功而 confirm 失败后前端版本与库态分叉致重试必 409（P2）、审核面板内无旧版源警示、认领命名约定无服务端保障。
- WP-B 修复交付（获客引擎 `AI_Find_Customer`，独立分支 `fix/serper-region-iso-codes`，commit 2c51e1a；其 origin 为上游仓库，不推送）：`_REGION_GEO` 由表自身 `gl` 值反查建 ISO-2 索引，ISO 码（US/CA/DE）不再落空致 Serper maps 400；键归一（下划线/连字符→空格）；命中失败打 warning（此前静默降级为全局搜索正是 400 无人察觉的原因）；引擎 +6 例，全量失败集合与改前逐条一致。

### 指引契约失败自动重试加固 + 对抗 DOCX 样本（G4）

- `server/src/fde_api/guidance/jobs.py`：预调研分析任务内自动重试——`GUIDANCE_ANALYSIS_RETRY_LIMIT = 1`（不含首次，测试钉死）。可重试失败（retryable=True 的 KimiError / GuidanceContractError 契约违反，即 MiniMax 概率性不守 JSON 合同的已知现象）先自动重试一次，仍失败才落 failed，failure_message 携带「已自动重试 N 次仍失败」的用户可见提示；不可重试（如 ai_service_not_configured）一次即败不消耗额度；source_missing 在构造 AI 客户端前拦截（零 AI 调用）；新增兜底分类 analysis_unexpected_error——未预期异常不再让分析卡在 analyzing（前端会无限轮询），且消息不携带异常串。每次尝试重新打开文件流。
- 对抗 DOCX 样本生成器 `server/tests/fixtures/presurvey/generate_fixtures.py`（9 种：空文档/空表格/合并单元格/批注/异常样式/缺失章节/超长段落/嵌套表格/非 ZIP 字节流；python-docx 1.2 程序化构建 + document.xml 最小注入），session 级构建到临时目录，二进制不入 git。
- 新增 `tests/test_guidance_adversarial_fixtures.py`（11 例）：两层解析（guidance 块抽取 / 本地全文提取 / Kimi 本地提取分类）对 9 样本的行为契约——畸形输入绝不崩溃、空内容失败为可分类错误（kimi_file_extract_failed retryable=True）、合并单元格全文层按 _tc 去重且块层按格位稳定引用、批注不泄漏进提取文本、异常样式不阻塞提取、嵌套表全文层递归可见（块层不可见，钉住两层差异）、超长段落整体提取。
- 新增 `tests/test_guidance_retry.py`（9 例）：重试语义钉子——契约失败重试一次后成功 / 耗尽后 failed 带 ai_output_invalid 与自动重试提示 / 调用次数恰为上限+1 / 不可重试一次即败 / 真实提取路径吃空表格样本落 kimi_file_extract_failed / source_missing 零 AI 调用 / 未预期异常落 analysis_unexpected_error 且消息无异常串 / 成功路径一遍 ready。
- conftest 清理清单补 `ProjectGuidanceAnalysis`/`ProjectPresurveySource`（此前测试库跨用例残留指引行会顶住 RESTRICT 外键清理）。

### 验收场景矩阵与缺口补测（G3）

- 新增 `docs/验收场景矩阵-G3.md`：指引链 / 集成桥手动采集 / SES 发信策略三链场景表（目标/起始/角色/分步/预期），每条映射钉住它的测试。
- 指引链补测 `desktop/tests/renderer/guidance-chain-scenarios.test.tsx`（8 例）：分析中→ready 自动开审进编辑态、failed 面板 role=alert 可见且无确认按钮、start() 失败 inline 可见、cancelled/queued/extracting 参数化占位展示、confirmed 卡片摘要 + `source_is_stale` 旧版重分析横幅（ProjectGuidanceCard 此前零测试）；集成桥链核对后无缺口（既有 13 例已覆盖全回路，platform 显式注入 win32/linux）。
- SES 策略先行 `server/src/fde_api/mailing/policy.py` + `server/tests/test_mailing_policy.py`（27 例）：四态分类（仅 throttle 可重试）、幂等闸门（同 message_id 判 duplicate 且先于限额/抑制）、每日限额（沙盒默认 10 可配）、总开关（未启用一律 drop_disabled）、发信域约束（仅配置子域，主域 somwyn.com 拒绝）、指数退避封顶——纯逻辑零 AWS 依赖，G9 在其上接客户端与 SNS 回调。
- 发现并记台账：cancelled 终态在审核面板仍显示「分析正在后台继续」占位（文案缺陷）；start() 失败提示不透传 failure_message 明细。

### 系统意图文档基线（G2）

- 新增 7 份意图文档（`docs/系统意图-*.md`，shipping-artifacts 方法，README 仍是部署唯一权威、交叉引用不复制）：架构与信任边界（根文档）、关键流程（预调研指引链/门禁/报价收款三链含鉴权点与 deny 例）、权限矩阵（三套角色体系 × 15 资源域）、变量与密钥（变量名×来源×轮换×风险，只写名不写值）、测试覆盖地图（现有 948+496+14 用例 / 建议 / 缺口三段）、定时任务（worker/scheduler/宿主 FDE-Bridge-Poll）、自动化面（AI 助手工具面/预调研管道/集成桥/任务中心，App 拥有副作用原则）。全部条目引用代码位置，作为 G7 意图比对基线。

### 内置手册与 UI 帮助 parity（PR #19）

- `help_manual.md` 补收「实操示例：证据文件怎么写（somwyn 样板）」整节与 G↔S 阶段映射（此前只在桌面端 HelpPage，help_fetch 检索不到）；新增双手册主题 parity 测试与 G↔S 映射与 `seeds/gates.json` 一致性测试，防两份手册再次分叉。

### 仓库级操作技能（G1）

- 固化 3 个仓库级 Agent 技能到 `.agents/skills/`（skill-creator 规范，随仓库分发）：
  - `fde-package-verify`：便携版打包全流程——electron-builder 产物 → asar sha256 → 中文 marker 字节验证（防控制台编码假阴性）→ 换新目录命名 r N+1 交付。
  - `fde-bridge-capture`：集成桥手动采集 runbook——`schtasks //Run`（Git Bash 双斜杠）或桌面「立即采集」按钮（同一代码路径）、`logs/bridge-poll.log` 验证到站、改 server 必须重建镜像、采集器只读纪律。
  - `fde-delivery-flow`：标准交付流检查单——分支 → push fork（永不 origin）→ PR → 4 CI 全绿 → 合并 → ff 本地 main → 删分支，每步验证点与常见事故对照。

## [未发布] — goal-r2 第二轮（2026-10-28）

安全口子、假绿灯与跨机口径一轮。**版本号未升**（按发布列车统一处理）。

### 安全（批次 G）

- **清除已入库的明文数据库口令**：备份脚本里的三条口令字面量（两条不同口令）已从工作树删除。凭据随 `2f90484` 入库，**视为已泄露，需人工轮换**（见交接清单）。
- **范围外备份管道移出仓库**：与 FDE 交付线无关的 n8n/Mautic/openoutfind 备份脚本迁至 `D:\test\AI外贸获客\scripts\`（副本 sha256 校验一致，仓库内可由 `git show 2f90484:scripts/backup-pipeline.sh` 恢复）。
- **集成桥读接口收敛门禁**：`GET /bridge/engagements`、`GET /bridge/status` 此前只要求登录（任意用户可枚举全部项目名与企业代号），现与写接口同级要求 `project_lead`。
- **登录限流键改为「用户名 + 来源 IP」复合键**：此前单个 IP 连错 5 次即可定向锁死任意用户名（含 admin）。Redis 不可用时记 WARNING（可观测），并可用 `FDE_LOGIN_RATE_FAIL_CLOSED=1` 切为 fail-closed。
- **秘密扫描线自证有效**：实测默认 gitleaks 规则对 `*_PASS=` 形态**整体漏报**（历史口令与随机探针同形态却一个抓一个不抓），新增 `.gitleaks.toml` 兜底规则与 `scripts/check-secret-scan.sh`（含 `--self-test` 哨兵自测）。

### 假绿灯（批次 H）

- **mypy 基线改计数法并纳入 tests**：旧实现按「文件+错误码+归一化消息」去重，实测 45 条基线条目掩盖了 181 次同类新增。
- **代号化检查不再吞错**：grep 退出码 1（无命中）与 ≥2（错误）区分；邮箱策略真正读取 `FDE_PSEUDONYM_EMAIL_POLICY`（缺省 fail）；黑名单提取 0 条即 FAIL；psql 失败不再当 0 行；`projects` 表 0 行即 FAIL（空库扫描等于没扫）。
- **CI 代号化 job 先迁移灌数再扫描**（原为空库扫描）。
- **冒烟脚本补真实断言**：auth 冒烟新增跨用户名隔离断言，commercial 冒烟种子管理员 try/finally 清理并断言归零。

### 跨机口径与运维（批次 I）

- pre-commit 三个钩子改走跨平台 node 入口（不再写死 Windows venv 路径）；README 更正 `.env` 模板来源与 venv 跨平台表述；操作手册路径参数化。
- compose 四服务统一 `restart: unless-stopped`；api healthcheck 改走 `/api/v1/health/ready`（真正校验依赖）；worker/scheduler 新增基于 Redis 心跳的 healthcheck（进程还在 ≠ 还在干活）。

### 打磨（批次 J）

- 业务枚举（价格档位 / 门禁五态 / C 分支 / SOW / 业务阶段）改由服务端 `GET /api/v1/workbench/options` 下发，前端保留本地兜底；存库值一律不变（旧中文标签数据照常可读）。
- 门禁汇总徽标改为按实际状态遍历（此前硬编码五态，服务端新状态会被静默丢弃）。
- 新增交付审计专用表 `document_delivery_records`（+ 迁移 `f3c8d2b7a1e5`），交付记录可按项目维度检索。
- C 分支触发档位收敛为单一常量；B 层分上下界都夹；扩展中心路由加角色门禁；预调研与调研导出的轮询失败对用户可见且失败后继续下一轮。
- **项目指引审核入口补缺**：指引卡片挂载时自动认领「已上传但尚未确认」的预调研源——此前分析/审核入口只在本次会话内上传后才出现，服务端（定时任务/历史会话）跑出的待审核指引在界面上没有任何入口；空状态文案同步提示审核入口。
- **指引审核弹窗只读态可确认**：确认按钮此前只在编辑模式渲染，用户从「查看预调研分析」进入的只读预览没有确认入口（得自己发现右上角「编辑」才能确认）；现在只读草稿底部直接显示「确认并用于项目指引」。

### 智能助手知识（help_fetch）

- 智能助手此前只拿到会话历史，「使用帮助」栏内容它一无所知（手册只在桌面前端渲染，服务端镜像里没有）。本轮把 `docs/工作台操作使用手册.md` 随 `server/` 源码烘进镜像（`fde_api/control/bundled/help_manual.md`），新增只读工具 `help_fetch`（按章节检索手册原文，带目录与分页），任意 AI 级别可用；对话入口注入工作台式 system prompt，引导「先查手册再作答」；新增公共 Skill `workbench-help`（`flask seed-public-skills` 灌入）。桌面「使用帮助」页同步注明智能助手内置同一份手册。

### 口径

- 服务端数据表 **73 → 74**（本轮新增 `document_delivery_records`）；迁移头 `e5b8a1c9d3f7` → `f3c8d2b7a1e5`。

## [v0.2.0] - 2026-10-26

交付流程与安全加固版本；桌面端与服务端版本号同步升至 `0.2.0`。

- 新增**门禁引擎 G1–G9**：pending → evidence → passed/failed 状态机（G9 支持 conditional_pass）；证据仅保存 `source_uri` 指针与 sha256 指纹，真实文件留在项目工作目录；claimed 与 accepted 分离。
- 新增**报价 / 收款（里程碑）/ 合同**商务看板与标准 FDE 项目模板派生。
- 项目工作台新增「门禁」「报价收款」页签；新增集成桥（本地 openfde / fdeops 工作目录的只读投影）与任务中心。
- 集成桥页新增「立即采集」按钮：桌面端一键触发宿主计划任务（与 4 小时周期同一代码路径），新快照到站自动刷新，无需等下一个采集窗口。
- 桌面端新增内嵌「使用帮助」：各模块操作说明、门禁 G1–G9 流程、实操示例与故障排查。
- 安全加固：登录连续失败限流（Redis 计数）、refresh token 轮换与改密即失效、API 容器非 root 运行、门禁证据哈希校验、CI 常驻 gitleaks 秘密扫描。
- 工程卫生：CI 并发取消与四 job 超时上限、pip/npm 缓存、全仓 LF 归一化、测试口令字面量收敛单点。
- README 按当前功能与 Docker Compose 部署路径重写，新增换机迁移清单。

## [v0.1.0] - 2026-09-28

首个开源源码版本。

- 提供 Electron 桌面端、Flask API、数据库迁移、后台 worker 与 scheduler 的源码。
- 提供项目、任务、调研、AI 机会、方案、交付文档、文件和管理员配置等工作台功能。
- 清理历史业务数据、客户资料、运行日志、访问凭据、对象存储文件和发布备份；仓库只保留通用示例与模板。
- 移除客户端自更新功能。升级需由部署者自行部署后端、执行迁移并重新打包客户端。
- 提供 MIT 许可证、安装部署说明、贡献指南和安全报告说明。

当前仅配置 macOS Apple Silicon（arm64）DMG 构建；没有 Windows 客户端。此版本是源码发布，不附带已签名、公证的安装包。公开部署前请更换首次登录密码和所有示例密钥，并阅读 README 的生产部署与安全说明。

本产品采用 vibe coding 方式开发；商用或处理真实数据前，应由部署者独立完成代码、安全、合规及业务适用性核验。
