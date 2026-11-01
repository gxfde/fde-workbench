# 试点执行手册（runbook）— UM-1 智能交付试点 · 30 天 / 20 run

> goal-d12 交付（2026-11-02）。本文只收录**仓库内已实现**的行为与开关；
> 待拍板项一律标注「待蔡工拍板」，不预设结论。操作前提见
> `docs/试点前联调-iptables与zcodeCLI-检查单.md`（人工联调项，执行后在本手册 §8 登记勾选）。

## 1. 试点定位与边界（为什么是"试点"）

- 试点 = **带观测窗口的受限放开**：30 天 / 20 run 先到为准（`config.py` goal-d6 试点开关族）；窗口内超限发起 run 返回 409 `pilot_run_limit_exceeded`，窗口走完不再拦（试点结束由报告定升级）。
- AI 只出草稿：翻译草稿、run 产物、项目指引版本一律 `confirmed=False`，**人工确认是唯一转正通道**；pilot 页六指标只出数，O-8/UM-5 阈值由人工评审（D15）。
- 演练 run（rehearsal 幂等键前缀）不计入 20 run 额度。

## 2. 试点开关清单（server/.env，改后需重建镜像生效）

| 配置键 | 默认 | 说明 |
|---|---|---|
| `agent_pilot_enabled` | `false` | 试点总开关；false 时 pilot 页显示「未启用」 |
| `agent_pilot_started_at` | 空 | 窗口起点（ISO）；**留空 = 以最早 agent_run.created_at 推导**（首个 run 即启动） |
| `agent_pilot_window_days` | `30` | 观测窗口天数 |
| `agent_pilot_max_runs` | `20` | 窗口内 run 额度 |
| `t6_review_cost_threshold` | `0`（全局关） | T6 高成本 run 前评审阈值；**0 = 关闭，行为与 v0.2.0 一致**；>0 时启用（见 §4） |

改动方式：编辑 `server/.env` → `docker compose build api worker scheduler && docker compose up -d`（服务端代码/配置烤进镜像，只 `up -d` 无效）→ 容器内无需迁移（本轮开关均无 schema 变更）。

## 3. 试点启动顺序（建议）

1. 完成 `docs/试点前联调-iptables与zcodeCLI-检查单.md` 全部人工项（iptables 生效性 + 沙箱内 zcode CLI 钉定）。
2. `server/.env` 打开 `agent_pilot_enabled=true`；如需固定窗口起点，同时写 `agent_pilot_started_at`。
3. 重建镜像并重启（§2 方式）；桌面端「试点报告」页（admin）确认状态卡「进行中」。
4. T6 阈值此时**保持 0**（关）；待首批 run 成本数据积累后由蔡工拍板定值再开（§4）。

## 4. T6 高成本 run 前评审（总纲 §2.2 T6，goal-d11 落地）

- 触发判据：run 拟用 agent 的 `max_cost_units` **成本档**——`0`（单 run 不限额）或 `> threshold` 即「高成本档」，启动前拦截 409 `t6_gate_open`（detail 带 gate/agent_max_cost_units/threshold）。启动前唯一可判定事实是 agent 授权成本档，不是 run 实际成本。
- 闸链顺序：协同声明 → T1 → **T6**（项目级门，不带 solution 的 run 同受闸）。
- 放行方式（二选一）：
  1. **纪要侧链**：召集 `T6-lite` 评审会（mandatory、守卫+模块智能体+finance persona）→ 会议纪要**封存** → `t6_gate_satisfied` 按 `topic_refs.project_id` 侧链该项目，后续高成本 run 直接放行（评审对象是项目内高成本 run 的性价比结论，一次评审放行后续 run）。**auto 纪要不算数**。
  2. **项目级关闭**：`PATCH /api/v1/projects/<id>` 置 `t6_review_disabled=true`（严格布尔）。适用于已在会下人工评审过的项目。
- ⚠️ `t6_review_cost_threshold` 定值与 `T6-lite` 模板内容审定 = **待蔡工拍板**（D10 五项同族），本手册不预设数值。

## 5. 翻译器门户操作流（goal-d9/d10/d12）

1. 登录 → 「翻译器」页：引导式表单录入客户诉求 → 提交 → AI 翻译管道 → 轮询就绪。
2. 结果卡核读（**AI 草稿 · 待人工确认** 徽标常显）：问题清单带 severity/module/分类标签。
3. 采纳：结果卡「采纳到项目」选目标项目 → 草稿升格为该项目指引**新版本**（draft 待确认）→ 到项目指引页编辑并逐条确认后正式生效。
4. 同一草稿可采纳到**多个项目**（个人资产语义）；同一项目对同一草稿只许采纳一次（409 `already_adopted`）。
5. 「最近翻译」列表（goal-d12）：本人最近 20 条，状态徽标 + 已采纳计数 + 「查看」载入结果卡再采纳。
6. O-3 额度在**采纳时刻**随路落账（`action_type=translation`，seat=采纳发起人；超额只标注不拦截）。

## 6. pilot 页读数口径（UM-1，admin 专属）

六指标全部只出数；`None` = 「数据未积累」（灰态，不编造）：

| 指标 | 口径 | 人工评审关注 |
|---|---|---|
| 强制门拦截率 | 门拦截 ÷（拦截+过门产物） | 持续为 0 或过高都触发复盘 |
| 评审后一次通过率 | 过门产物 run 中首次尝试占比 | retry 折算口径待数据积累后细化（挂账） |
| 单会成本（units） | 召集计费总额 ÷ 会议总数 | 当前口径=召集计费；U6 全量归集承前挂账 |
| 降级率 | L1+ 占比 | 持续 >30% = 基座不成熟红线 |
| 超时/预算熔断率 | 熔断 run 占比 | — |
| run 成本中位数（units） | 窗口内全部 run | T6 阈值定值的主要输入 |

状态卡：窗口起止 / run 额度（used/limit/余量）/ 剩余天数 / 滞留中 run（stuck_inflight，配合 run 卡死恢复功能处置）。

**O-8/UM-5 评审**：试点窗口结束或额度耗尽后，以六指标 + 台账做人工评审，决定转正/续试点/收敛——**人工拍板，系统不判阈值**。

## 7. 证据与红线（试点期间持续有效）

- 客户真实资料不进 git/数据库：仓库与库内只存代号（如 somwyn）；原件留本地工作目录。
- 门禁证据只存 `source_uri` 指针 + sha256；`scripts/bridge-poll.mjs` 只读。
- T6/纪要侧链依赖**封存**纪要（sealed_sha256）；伪造/改稿指纹即不一致。
- M10 等级证据可用 `workbench-minutes:<meeting_id>` + 指纹双校验引用 Stage A 证据（goal-d10）。

## 8. 执行登记（人工勾选）

- [ ] §3-1 联调检查单人工项全部完成（iptables 生效性 / zcode CLI 钉定）
- [ ] §3-2 `agent_pilot_enabled=true` + 窗口起点写入 `server/.env`
- [ ] §3-3 镜像重建 + 状态卡「进行中」确认（执行日期：________）
- [ ] T6 阈值定值与模板审定拍板（试点数据回流后；拍板结果：________）
- [ ] 窗口结束 O-8/UM-5 人工评审（结论：________）
