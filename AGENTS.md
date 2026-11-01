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
- 口径数字（实测 2026-11-01，goal-d5 评审会轮 / d4·B3ops·B2·B1 联合口径）：服务端 **94 张业务表**（不含 alembic_version；d5 +3：review_meetings/review_meeting_turns/review_meeting_minutes）、迁移头 `f6a9c3e1d7b4`（**17 个 revision**，d5）、蓝图路由 **252**（d5 +6：meetings 召集/状态/话轮/收敛/纪要/模板）、api_catalog ENTRIES **86**（d5 +3 只读：meetings.templates/get/minutes——召集/发言/收敛属人工收敛写路径不收）、服务端 pytest **1563 收集 = 1557 passed / 6 skipped**（d5 +22）、桌面端 vitest **695 用例**（d5 零改动）。goal-d5：评审会三表（gate_tier 三档门 + triggered_by_run_id D7 回链软引用 + trigger + min_difficulty 预留）+ T2-lite 模板注册表（守卫+1 模块智能体、2 话轮）+ 工具面 `dispatch_agent_tool`（三重白名单 enabled/allowed_tools 显式声明/capability 实时鉴权；meeting_convene 计费 +2 落触发 run + 每 run ≤2 次；meeting_get_minutes 只读仅限自己触发；面外工具 denied——**denied 留痕与 degraded 标注走独立事务，拒绝回滚不丢痕**）+ 纪要三段式 sealed_sha256 封存（守卫复核引用闭合，失败拒封存标 degraded；二次 close 409 不可变；分歧条目必须 ≥2 方论点+冲突标注）+ **T2 强制钩子**（`agents/_finalize`：solution 绑定的 completed run 无已封存强制纪要 → run failed + `review_gate_open` 409 + 产物留痕不进终审；封存纪要对幂等键家族生效，同键 retry 放行；探索性 run 门不适用 d4 零回归）——详见 `docs/goal-d5-交付工作台.md`。goal-d4：zcode 适配器三段 + run 生命周期（幂等/重试/handoff L3/月度闸）+ 上下文脱敏渲染器 + egress allowlist + C-1 产物校验——详见 `docs/goal-d4-交付工作台.md`。B2 调度台操作面：平台侧第 6 子页（供给池候选勾选器 + 包全景生命周期按钮 + 包侧 offer 留痕面板）——台账二十七节。B1 接单工作台：交付工程师专区（我的 offer/接单拒单/我的结算/我的档案/抢单按钮）——台账二十六节。B3/B5/B6 运维页簇：争议处理/仿真对比/开闸运维三个平台侧 tab（对账单只透出 source_uri 指针红线；仿真不作真实成绩）——台账二十八节。goal-d3：agent 五表 + solution_review_checkpoints + `agent.*` 四能力 + 沙箱基座（V2 四断言）——详见 `docs/goal-d3-交付工作台.md`。goal-d2：S0-3/4/5/6（确认流修复+方案骨架+健康分+SOW 串联+行业模板种子）——详见 `docs/goal-d2-交付工作台.md`。派单 goal-r9/r10/r11：**派单 goal 循环已终止（§八八项全成立）**，唯一凭证=`docs/goal-r11-派单引擎收口.md`。
- goal-d4/B1/B2/B3ops 口径存档（2026-11-01）：91 表 / head `d9c3e7f1a5b8`（16 revision）/ 路由 246 / ENTRIES 83 / pytest 1541 收集（1521 passed + 6 skipped 实跑）/ vitest 695。
- goal-d3/B1 口径存档（2026-10-31）：91 表 / head `d9c3e7f1a5b8`（16 revision）/ 路由 233 / ENTRIES 73 / pytest 1493 收集 / vitest 676。
- goal-d2 口径存档（2026-10-31）：85 表 / head `c5d7e9f1a3b7`（15 revision）/ 路由 230 / ENTRIES 70 / pytest 1448 收集 / vitest 667；S0 全收口——详见 `docs/goal-d2-交付工作台.md`。
- 派单引擎施工准绳：`D:\test\FDE\蔡工FDE工作台_文档中心\06_派单引擎\蔡工FDE工作台_派单撮合引擎产品与技术设计_v1.0.md`（2026-10-31 补齐版，冲突裁决顺序=代码实测 > 设计文档 > 规则表 > BP）。
