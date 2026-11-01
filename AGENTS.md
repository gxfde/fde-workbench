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

## 当前状态（2026-10-31）

- v0.2.0：门禁 G1–G9、报价/收款/合同、集成桥（宿主 4h 采集 + 手动采集按钮）、内嵌使用帮助；本地 main == fork/main。
- 版本号按发布列车同步 `desktop/package.json` 与 `server/pyproject.toml`，tag 打在 fork。
- 待办台账：`docs/后续需求台账-F5与D11.md`；历史审计存档：`docs/goal-audit-2026-10-26.md`；派单引擎 goal 循环报告：`docs/goal-r<N>-派单引擎.md`。
- 口径数字（实测 2026-11-01，goal-d6 降级链+试点轮 / d5 联合口径）：服务端 **94 张业务表**（不含 alembic_version；d6 **零迁移**）、迁移头 `f6a9c3e1d7b4`（**17 个 revision**，不变）、蓝图路由 **258**（d6 +6：agents 演练/恢复/试点报告 + solutions generate-agent/review-trail + meetings checklist）、api_catalog ENTRIES **87**（d6 +1 只读：solutions.review_trail）、服务端 pytest **1592 收集 = 1586 passed / 6 skipped**（d6 +29）、桌面端 vitest **699/699 全绿**（d6 +4：V11 徽标）。goal-d6：**降级链全链**（L1=降级 completed 强制人工终审产物不自动挂 solution + handoff 接受 L1 保留降级事实 / B 类失败去向 L2 / L2 A-1、L3 handoff d4 既有）+ **V4 手动触发面**（admin 演练端点 rehearsal: 键零计费，试点计数排除）+ **V3 三重交集名字空间裁决**（`agents/tools.effective_run_tools`：写类+会议面恒剥；网关名字空间按能力腿实时判定，等级地板恒生效插件安装不放宽；沙箱生态名由声明+adapter 承载）+ **V12 插件联动**（安装 disable → 新 run 白名单收紧；全失效 → `tools_unavailable` 明确报因）+ `solutions.generate-agent`（completed 才接线 `agent_run_id`+`generated_by='agent'`，gate_open 409 透传）+ review-trail（U5 家族∪侧链纪要回链）+ SOW `agent_trace` 导出行段（V9 闭环+V11 导出标注）+ **试点开关**（30 天/20 run 先到为准，`pilot_run_limit_exceeded`；pilot-report 六指标=拦截率/一次通过率/单会成本/降级率/熔断率/成本中位数，只出数不判阈 D15）+ U3 T3-adhoc（reason 必填入 topic_refs 计入纪要回链；adhoc 纪要不作门证据）+ U4 修订回路（家族纪要未决分歧 → retry 409 `revision_disputes_open` 升级人工）+ U9 checklist（模板人工执行单端点）+ run 卡死恢复（新鲜窗口闸 `stuck_recovered`）+ 桌面溯源徽标——详见 `docs/goal-d6-交付工作台.md`。goal-d5（压缩）：评审会三表 + T2-lite 模板 + 工具面 dispatch_agent_tool（三重白名单；召集计费 +2/≤2 次；**denied 留痕与 degraded 标注走独立事务拒绝回滚不丢痕**）+ 纪要三段式 sealed_sha256 封存 + **T2 强制钩子**（无封存强制纪要 → `review_gate_open` 409 产物不进终审；对幂等键家族生效）——详见 `docs/goal-d5-交付工作台.md`。goal-d4：zcode 适配器三段 + run 生命周期（幂等/重试/handoff L3/月度闸）+ 脱敏渲染器 + egress allowlist——详见 `docs/goal-d4-交付工作台.md`。B2 调度台操作面——台账二十七节；B1 接单工作台——台账二十六节；B3/B5/B6 运维页簇——台账二十八节。goal-d3：agent 五表 + `agent.*` 四能力 + 沙箱基座——详见 `docs/goal-d3-交付工作台.md`。goal-d2：S0 全收口——详见 `docs/goal-d2-交付工作台.md`。派单 goal-r9/r10/r11：**派单 goal 循环已终止（§八八项全成立）**，唯一凭证=`docs/goal-r11-派单引擎收口.md`。
- goal-d5 口径存档（2026-11-01）：94 表 / head `f6a9c3e1d7b4`（17 revision）/ 路由 252 / ENTRIES 86 / pytest 1563 收集（1557 passed + 6 skipped）/ vitest 695。
- goal-d4/B1/B2/B3ops 口径存档（2026-11-01）：91 表 / head `d9c3e7f1a5b8`（16 revision）/ 路由 246 / ENTRIES 83 / pytest 1541 收集（1521 passed + 6 skipped 实跑）/ vitest 695。
- 派单线收尾轮 r12 口径存档（2026-11-01，零功能补码）：口径数字与 d5 行一致（94 表 / `f6a9c3e1d7b4` / 252 / 86 / 1563 / 695）；C7 经核实 r10 已交付（8 例复跑绿）；《外部输入到达执行手册》=台账三十节（八项落点全存在、零补码；留注⑯空号、实有 21 条=12 归档/2 附条件/7 需变更）。
- 派单首轮拍板执行存档（2026-11-01，r12 续）：**B-④ 城市终版=上海/广州/深圳/杭州/成都/武汉**（全行业+南方一线口径，苏锡常制造业口径退役；claim 仍全关=名单≠开闸）+ **留注⑤ 冷启动切换落地**（settlements 包侧客户城=企业代号第三段，cities.package_client_city 三处口径归一）+ 拍板销号 B-①（维持需备案，律师意见书仍待）/B-②（对公）/直签（封堵）/P2-2（5 态）——台账 30.10；B-③ 开票税率、留注签字、仿真器数据仍外部等待。
- 派单签字轮存档（2026-11-01，r12 续，纯文档）：**留注 14 条签字归档**（owner=用户本人：12 条即归档 + ③⑥ 附条件维持；剩 ⑦⑭⑮ 二期待办【⑭ 前置=行业→大类映射口径】+ ⑨⑬ 随 B-①）+ **B-③ 拍板销号**（平台统一开票 + 2025-16 预扣口径确认；mark_payable 字段扩展挂下次工程轮）+ **B-① AI 研究底稿定稿**（倾向无需备案、非法律意见；用户拍板寄律师包、维持需备案零改动）——台账 30.11；等待=B-① 意见书/仿真器数据。
- goal-d3/B1 口径存档（2026-10-31）：91 表 / head `d9c3e7f1a5b8`（16 revision）/ 路由 233 / ENTRIES 73 / pytest 1493 收集 / vitest 676。
- goal-d2 口径存档（2026-10-31）：85 表 / head `c5d7e9f1a3b7`（15 revision）/ 路由 230 / ENTRIES 70 / pytest 1448 收集 / vitest 667；S0 全收口——详见 `docs/goal-d2-交付工作台.md`。
- 派单引擎施工准绳：`D:\test\FDE\蔡工FDE工作台_文档中心\06_派单引擎\蔡工FDE工作台_派单撮合引擎产品与技术设计_v1.0.md`（2026-10-31 补齐版，冲突裁决顺序=代码实测 > 设计文档 > 规则表 > BP）。
