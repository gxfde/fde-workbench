# AGENTS.md — fde-workbench

FDE（前端部署工程师）交付工作台：Flask + SQLAlchemy API（`server/`）+ Electron·Vite·React 桌面端（`desktop/`），当前 v0.2.0。部署、命令全集、迁移与换机迁移清单以 **README.md** 为唯一权威，本文件只放 Agent 不看就会犯错的边界。

## 红线（违反即事故）

- 客户真实资料永不进 git 历史与远端：仓库和数据库只存代号（如 somwyn）；真实姓名、扫描件、回款凭证只留在本地 fdeops/openfde 工作目录（`D:\test\FDE\…`）。
- 密钥不入 VCS：`.env`、`server/.env`（承载 FDE_DB_PASSWORD / FDE_JWT_SECRET / FDE_BRIDGE_TOKEN）永不提交，仓库只有 `*.env.example`；FDE_JWT_SECRET 是本地密钥加密根，换机迁移必须原样携带。
- 门禁证据只存 `source_uri` 指针 + sha256 指纹；证据原件永远留在项目工作目录，不进仓库、不进数据库。
- `scripts/bridge-poll.mjs` 只读纪律：只调 openfde 只读 CLI + 读文件，绝不写真相层；采集只能在 Windows 宿主跑，Docker 容器内跑不了。
- 远端分工：`origin` 是上游（gxfde），**永不 push**；工作远端是 `fork`（caishide/fde-workbench），tag 也只打在 fork。

## 常用命令

- 桌面端：`npm run typecheck`、`npm run test:desktop`（620+ 用例）；服务端：`npm run test:server`。
- 服务端代码烤进镜像：改 `server/` 后必须 `docker compose build && docker compose up -d`，再执行 `alembic upgrade head`（只跑 up -d 无效）。
- 集成桥手动采集：`schtasks //Run //TN "FDE-Bridge-Poll"`（Git Bash 下双斜杠），或桌面端集成桥页「立即采集」按钮（同一代码路径）。
- 桌面改动交付：重打包便携版并做 asar 字节验证（README「打包桌面端」节）。

## 工作流与陷阱

- 变更走 feature 分支 → push fork → PR → 4 个 CI job 全绿（desktop / server-tests / gitleaks / pseudonymization）→ 合并 → ff 本地 main → 删分支。
- CI 跑 Ubuntu：Windows-only 代码路径（schtasks、wsl、盘符）必须做成可注入/可 mock，测试显式传 platform。
- 本机 Windows/Git Bash；docker 经 `wsl -d Ubuntu-24.04 -- docker …`（配 `MSYS_NO_PATHCONV=1`）。
- 代码检索优先用 CodeGraph：本仓库已索引（`.codegraph/` 是本地 SQLite，已 gitignore，勿提交）；`codegraph explore "<问题或符号>"`，大规模改码后 `codegraph sync` 重建增量。

## 当前状态（2026-11-01，goal-d9 后）

- v0.2.0：门禁 G1–G9、报价/收款/合同、集成桥（宿主 4h 采集 + 手动采集按钮）、内嵌使用帮助；本地 main == fork/main。
- 版本号按发布列车同步 `desktop/package.json` 与 `server/pyproject.toml`，tag 打在 fork。
- 待办台账：`docs/后续需求台账-F5与D11.md`；历史审计存档：`docs/goal-audit-2026-10-26.md`；派单引擎 goal 循环报告：`docs/goal-r<N>-派单引擎.md`。
- 口径数字（实测 2026-11-01，goal-d9 P3 翻译器全量轮 / d8-d7 联合口径）：服务端 **96 张业务表**（不含 alembic_version；d9 **+1 迁移**：translator_translations 表 + solution_review_checkpoints.handoff_run_id 列）、迁移头 `c5e9b3d7a1f5`（**20 个 revision**，链条 …→ a7b4d9e2c6f1 → b8c2d6f0a4e7 → c5e9b3d7a1f5）、蓝图路由 **268**（d9 +4：translator 3 + solutions signoff）、api_catalog ENTRIES **93**（d9 +2：translator.translate 写 + translator.translations 只读；**signoff 拍板路径有意不收编**）、服务端 pytest **1666 收集 = 1660 passed + 6 skipped**（d9 +23）、桌面端 vitest **721/721**（d9 +8，串行口径 --no-file-parallelism）。goal-d9：**P3 翻译器全量**（POST /api/v1/translator/translations 引导式表单→AI 翻译管道→guidance 全契约草稿落库 confirmed 一律 False；provider=DeepSeek 文本栈 settings 单点可换，决议①）+ **终审台拍板收口**（POST /solutions/{id}/signoff approved/rejected：pending 闸/权限档闸/attempt 计数；review-trail 扩 artifacts+signoff，handoff 路产物经 handoff_run_id 并入家族；**人工拍板不进 api_catalog**）+ **指标埋点三件转实**（SOW 一次拍板率=首拍板事件口径/资深介入时长=接管→拍板 run 配对/拦截率=C-1 422 事件；空库仍 insufficient）+ **agent_assisted 桌面化**（派单池/控制台难度徽标+协同声明按钮双通道；白名单 +accepted_user_id）+ **潜伏 bug 家族全修**（派单桌面页簇 12 处对已解包 apiRequest 再取 .data→B1/B2 列表线上恒空、单测 mock 信封假绿——全修+mock 适配）——详见 `docs/goal-d9-交付工作台.md`。goal-d8（压缩）：**D2 合成裁决落地（PRD §6 四条规则全测）**——`agent_assisted` 交付包级协同声明（接单人显式声明才启用评审门与溯源联动：accepted+未声明 start_run 409 `agent_assisted_required` 纯人工交付；声明 8 态机零改动只落列+事件留痕；溯源=包↔方案同键+白名单两键+artifact 既有链）+ **O-4 订单难度三档**（delivery_packages.difficulty low/medium/high 发布时定档；start_run low→standard/medium→high 自动带入 run.difficulty **T4 免手报**，手报冲突 400 `difficulty_order_conflict`；high 声明侧禁入+start_run 兜底双保险）+ **P0/P1 指标报表**（`GET /metrics/report` 只读聚合：确认率/耗时中位数/lite 占比/一次通过率/降级率/成本中位数/当月动作；缺埋点三类显式 insufficient_data 不编造）+ **翻译器门户骨架**（`#/translator` 引导式表单+实时只读预览，纯前端 preview.ts 对齐 guidance 契约不落库）+ 桌面 `#/metrics`（admin/project_lead）——详见 `docs/goal-d8-交付工作台.md`。goal-d7（压缩）：**S1–S6 场景模板全量**（PartyMode 班底 + D10 蒸馏源标注）+ **T1/T4/T5 三强制门**（T1=start_run 带 solution 前置闸；T4=difficulty 高难度升 full 档加座；T5=家族含 L1 门只认 T5 补审）+ **角色卡 persona**（种子懒装载；不可执行 409）+ **编排中枢到场表鉴权**（persona 只经 `persona:<key>` 入场）+ **PM-2 三层防火墙系统级封存**（徽标注入/处方 denylist 422/结论位禁入+待办强制前缀进 sealed_sha256）+ **Killjoy 自动收敛**（auto 纪要永不作门证据）+ M5 memlog + M7 中断恢复 + M8 checklist 降级 + M9 会议成本 + **O-3 额度**（seat_action_ledger 三类动作 seat 归集；超额只标注不拦截绝不断供）+ 桌面 QuotaMeter——详见 `docs/goal-d7-交付工作台.md`。goal-d6（压缩）：**降级链全链**（L1=降级 completed 强制人工终审 / B 类失败去向 L2）+ V4 演练端点（rehearsal: 零计费）+ V3 名字空间三重交集 + V12 插件联动 + generate-agent 接线 + review-trail + 试点开关 + U3/U4/U9 + run 卡死恢复——详见 `docs/goal-d6-交付工作台.md`。
- goal-d8 口径存档（2026-11-01）：95 表 / head `b8c2d6f0a4e7`（19 revision）/ 路由 264 / ENTRIES 91 / pytest 1649 收集（1643 passed + 6 skipped）/ vitest 713。
- goal-d7 口径存档（2026-11-01）：95 表 / head `a7b4d9e2c6f1`（18 revision）/ 路由 262 / ENTRIES 89 / pytest 1627 收集（1621 passed + 6 skipped）/ vitest 704。
- goal-d6 口径存档（2026-11-01）：94 表 / head `f6a9c3e1d7b4`（17 revision）/ 路由 258 / ENTRIES 87 / pytest 1592 收集（1586 passed + 6 skipped）/ vitest 699。
- goal-d5 口径存档（2026-11-01）：94 表 / head `f6a9c3e1d7b4`（17 revision）/ 路由 252 / ENTRIES 86 / pytest 1563 收集（1557 passed + 6 skipped）/ vitest 695。
- goal-d4/B1/B2/B3ops 口径存档（2026-11-01）：91 表 / head `d9c3e7f1a5b8`（16 revision）/ 路由 246 / ENTRIES 83 / pytest 1541 收集（1521 passed + 6 skipped 实跑）/ vitest 695。
- 派单线收尾轮 r12 口径存档（2026-11-01，零功能补码）：口径数字与 d5 行一致（94 表 / `f6a9c3e1d7b4` / 252 / 86 / 1563 / 695）；C7 经核实 r10 已交付（8 例复跑绿）；《外部输入到达执行手册》=台账三十节（八项落点全存在、零补码；留注⑯空号、实有 21 条=12 归档/2 附条件/7 需变更）。
- 派单首轮拍板执行存档（2026-11-01，r12 续）：**B-④ 城市终版=上海/广州/深圳/杭州/成都/武汉**（全行业+南方一线口径，苏锡常制造业口径退役；claim 仍全关=名单≠开闸）+ **留注⑤ 冷启动切换落地**（settlements 包侧客户城=企业代号第三段，cities.package_client_city 三处口径归一）+ 拍板销号 B-①（维持需备案，律师意见书仍待）/B-②（对公）/直签（封堵）/P2-2（5 态）——台账 30.10；B-③ 开票税率、留注签字、仿真器数据仍外部等待。
- 派单签字轮存档（2026-11-01，r12 续，纯文档）：**留注 14 条签字归档**（owner=用户本人：12 条即归档 + ③⑥ 附条件维持；剩 ⑦⑭⑮ 二期待办【⑭ 前置=行业→大类映射口径】+ ⑨⑬ 随 B-①）+ **B-③ 拍板销号**（平台统一开票 + 2025-16 预扣口径确认；mark_payable 字段扩展挂下次工程轮）+ **B-① AI 研究底稿定稿**（倾向无需备案、非法律意见；用户拍板寄律师包、维持需备案零改动）——台账 30.11；等待=B-① 意见书/仿真器数据。
- goal-d3/B1 口径存档（2026-10-31）：91 表 / head `d9c3e7f1a5b8`（16 revision）/ 路由 233 / ENTRIES 73 / pytest 1493 收集 / vitest 676。
- goal-d2 口径存档（2026-10-31）：85 表 / head `c5d7e9f1a3b7`（15 revision）/ 路由 230 / ENTRIES 70 / pytest 1448 收集 / vitest 667；S0 全收口——详见 `docs/goal-d2-交付工作台.md`。
- 派单引擎施工准绳：`D:\test\FDE\蔡工FDE工作台_文档中心\06_派单引擎\蔡工FDE工作台_派单撮合引擎产品与技术设计_v1.0.md`（2026-10-31 补齐版，冲突裁决顺序=代码实测 > 设计文档 > 规则表 > BP）。
