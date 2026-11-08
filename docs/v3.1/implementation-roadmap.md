# V3.1 实施 Roadmap 与收口终态

> 本文件是 V3.1 实施路线图与九阶段收口的**单页导航**。权威输入：《蔡工_FDE_Workbench_V3.1_智能交付自动化升级路线图与Goal实施任务书》（仓库根 docs/，§14 严格阶段顺序 P0-0→P0-1→P0-2→P0-3→P0-4→P1-2→P1-1→P1-3→P2）；逐阶段状态=同目录 `phase-status.md`；试点执行面=`pilot-runbook.md`；验收勾稽=`final-acceptance-checklist.md`。

## 收口终态（2026-11-09，fork/main `acceb50`）

| 阶段 | PR | 交付要点 |
| --- | --- | --- |
| P0-0 基线审计 | #197 `14d2b62` | 四报告（baseline-audit/data-model-map/test-baseline/gap-register）+任务书入库；复用/扩展/新建/暂缓四档裁决+拍板项 D-1~D-4 登记 |
| P0-1 访谈事实/需求 | #203 `92ca0bd` | discovery 四表+8 路由+抽取 job（T-A2 脱敏/契约重试/整批失败零写入）+桌面 DiscoveryPanel（批 B） |
| P0-2 本体候选/稳定 ID | #205 `858e090` | ADR-002+候选桥（accepted 事实→change-set 管线）+subjects.term_id 试点+D-1 只读告警 |
| P0-3 交付方案/任务分解 | #207 `889f964` | plans 三表+确定性生成器+审阅发布双点退位+幂等分解（dry_run/待认领） |
| P0-4 Workflow 模板/草稿 | #209 `b196074` | 种子通道三套模板+validate_dag 契约字段扩展+draft-from-plan+validate 干跑+模板只读面；D-2=admin-only 发布 |
| P1-2 自动测试/证据 | #211 `9b5e030`（+#213 口径回填） | quality 三表（requirement_key 追溯/append-only 执行/production 硬闸）+需求覆盖闸+evidence/validate 五维只读校验 |
| P1-1 宿主执行通道 | #215 `58f7a26` | execution_policy（根锚定/命令锚定/超时钳制/快照）+HMAC 短期票据+agent_runs/artifacts 扩列；**通道保持关闭**（默认 False+双静态钉） |
| P1-3 指标/经验沉淀 | #221 `2d14d85` | metrics 报表 v31 节七指标（workflow 三+域速率四，insufficient_data 语义）；7.2 事件映射注记；7.4/7.5 暂缓 |
| P2 试点 Runbook/验收勾稽 | #222+#223+#225 `acceb50` | pilot-runbook（前置 C1-C7+E2E 十步+复盘模板+就绪预检 18/18）+§17 十九项勾稽（试点后 **17 达成/1 待业务闸/0 未达成**；试点执行复盘=`pilot-复盘-somwyn-2026-11-09.md`） |

## 终态口径（实测）

pytest **2354 收集 = 2348 passed + 6 skipped**（EXIT=0）/ vitest **951** / mypy 基线 **279** / 路由 **391** / 蓝图 **49** / 业务表 **130** / **51 rev 单头 `e9c4a1f7b3d2`**；各阶段均 CI 4 job 绿 + main run 收口 + 部署活体验证；四层账目（AGENTS 口径/CHANGELOG 节/AGENTS bullet/审计 CSV）齐备。

## 待业务闸（2026-11-09 更新：试点已完成，仅余一项）

1. ~~**§17-17 E2E 试点**~~ ✅ **已完成（2026-11-09）**：蔡工确认 C1-C7 后按 `pilot-runbook.md` 十步操作序执行 somwyn 试点全链并复盘——`pilot-复盘-somwyn-2026-11-09.md`；checklist 第 17 项已回填 ✅（**偏差注记：审阅动作 admin 代执行，建议蔡工桌面端复核**）；
2. **§17-14 ZCode 真实联调**：待商用条款书面确认 + 12 条安全前置逐项通过——独立拍板；通道保持关闭（默认 False）直至该闸通过。

## 文档地图

- 阶段状态：`phase-status.md`（逐轮交付/口径/实施修正/遗留）
- 裁决依据：`00-gap-register.md`（P0-1~P1-3 逐能力四档裁决+横切纪律）
- 试点执行：`pilot-runbook.md`；验收勾稽：`final-acceptance-checklist.md`
- 架构决策：`decisions/ADR-002-ontology-ownership.md`
- 任务书（权威输入）：`docs/蔡工_FDE_Workbench_V3.1_智能交付自动化升级路线图与Goal实施任务书.md`
