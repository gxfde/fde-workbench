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

## 当前状态（2026-11-01，goal-d11 后）

- v0.2.0：门禁 G1–G9、报价/收款/合同、集成桥（宿主 4h 采集 + 手动采集按钮）、内嵌使用帮助；本地 main 允许落后——**权威=fork/main**（开新轮先 fetch 对齐）。
- 版本号按发布列车同步 `desktop/package.json` 与 `server/pyproject.toml`，tag 打在 fork。
- 待办台账：`docs/后续需求台账-F5与D11.md`；历史审计存档：`docs/goal-audit-2026-10-26.md`；派单引擎 goal 循环报告：`docs/goal-r<N>-派单引擎.md`。
- 口径数字（实测 2026-11-01，goal-d11 T6+试点包轮 / d10 口径顺延）：服务端 **96 张业务表**（不含 alembic_version；d11 **+1 迁移零新表**：projects.t6_review_disabled 列）、迁移头 `c3e7a9b1d5f4`（**22 个 revision**，链条 …→ c5e9b3d7a1f5 → a1d3f5b7c9e2 → c3e7a9b1d5f4）、蓝图路由 **269**（d11 零新增）、api_catalog ENTRIES **94**（d11 零新增）、服务端 pytest **1698 收集 = 1692 passed + 6 skipped**（d11 +14）、桌面端 vitest **725/725**（d11 +3，串行口径）。goal-d11：**T6 高成本 run 前评审**（总纲 §2.2 T6：settings.t6_review_cost_threshold 全局阈值（0=关默认零回归）+agent.max_cost_units 档判据（0=不限额=最高档必触发）+项目级 t6_review_disabled 关闭+T6-lite 模板+t6_gate_satisfied（project_id 侧链+auto 排除）+start_run 闸链 协同声明→T1→T6）+ **试点包三件收尾**（#/pilot 桌面页六指标 None 灰态；插件种子 lcsc-browser-baseline/jev 懒装载幂等；checkpoint 拍板桌面页=SignoffConsole 销号）+ **d10 挂账清尾**（门户 adopted_into 徽标/workbench-minutes 档案页提示/source_missing 验证销号）——详见 `docs/goal-d11-交付工作台.md`。goal-d10（压缩）：P3 收口采纳流（POST /translator/translations/{id}/adopt 升格项目指引 draft+O-3 额度随路落 action_type='translation'+决议③ confirm 不回写预调研源）+M10 纪要证据联动（promote_user workbench-minutes:<id>+sealed 指纹一致）+桌面采纳 UI+extractTranslationId 潜伏解包 bug 修复——详见 `docs/goal-d10-交付工作台.md`。服务端 **96 张业务表**（不含 alembic_version；d10 **+1 迁移零新表**：project_guidance_analyses +source_kind/translation_id 列+source_file 双列放宽 nullable + seat_action_ledger.action_type 放宽 +'translation'）、迁移头 `a1d3f5b7c9e2`（**21 个 revision**，链条 …→ b8c2d6f0a4e7 → c5e9b3d7a1f5 → a1d3f5b7c9e2）、蓝图路由 **269**（d10 +1：translator adopt）、api_catalog ENTRIES **94**（d10 +1：translator.adopt 创作类写先例；signoff 拍板路径仍不收编）、服务端 pytest **1684 收集 = 1678 passed + 6 skipped**（fork/main 实测基线 1672 收集，d10 +12）、桌面端 vitest **722/722**（d10 +1，串行口径 --no-file-parallelism）。goal-d10：**P3 收口采纳流**（POST /translator/translations/{id}/adopt：ready 草稿升格项目指引新版本 status=draft 确认仍人工；决议③ confirm 不回写预调研源指针；O-3 额度 action_type='translation' 随路落 over_quota 只标注不拦截）+ **M10 纪要证据联动**（promote_user 收编 workbench-minutes:<meeting_id>：纪要存在+sealed_sha256 指纹一致，等级证据链→Stage A A1 门）+ **桌面采纳 UI**（#/translator ready 卡采纳下拉/提示；编辑/逐条确认复用项目侧 GuidanceReview）+ **决议⑤家族漏网修复**（extractTranslationId 再取 .data→提交后轮询永不发起，mock 信封假绿）+ **试点联调检查单**（iptables+zcode CLI 人工项）——详见 `docs/goal-d10-交付工作台.md`。goal-d9（压缩）：P3 翻译器全量（POST /api/v1/translator/translations 引导式表单→AI 翻译管道→guidance 全契约草稿落库 confirmed 一律 False；provider=DeepSeek 文本栈 settings 单点）+ 终审台拍板收口（POST /solutions/{id}/signoff；review-trail 扩 artifacts+signoff；人工拍板不进 api_catalog）+ 指标埋点三件转实 + agent_assisted 桌面化 + 潜伏 bug 家族 12 处全修——详见 `docs/goal-d9-交付工作台.md`。
- goal-d10 口径存档（2026-11-01）：96 表 / head `a1d3f5b7c9e2`（21 revision 零新表）/ 路由 269 / ENTRIES 94 / pytest 1684 收集（1678 passed + 6 skipped）/ vitest 722。
- goal-d9 口径存档（2026-11-01）：96 表 / head `c5e9b3d7a1f5`（20 revision）/ 路由 268 / ENTRIES 93 / pytest 1666 收集（1660 passed + 6 skipped）/ vitest 721。
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
