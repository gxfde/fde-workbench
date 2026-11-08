# V3.1 P2 真实项目试点 Runbook（试点条件与执行面）

> **闸门声明（先读）**：本 runbook 只提供试点条件清单与 E2E 执行面，**不构成执行授权**。
> 试点启动需满足 §2 全部前置（真实脱敏项目数据闸 + 蔡工拍板项逐项确认）。
> 红线不变：客户真实资料永不进 git/数据库（只存代号）；宿主通道在 12 条安全前置
> 通过前保持关闭（`agent_host_channel_enabled=False`）；AI 产出一律草稿+人工审阅。

阶段归属：任务书 §14 P2（最终阶段）；前置八阶段（P0-0~P0-4、P1-2、P1-1、P1-3）
已全部收口（PR #197/#203/#205/#207/#209/#211/#213/#215/#221）。

## 1. 试点目标（任务书 §13.5 + §17-17）

**至少一个脱敏端到端试点完成并复盘**：从访谈导入出发，走通
「事实/需求结构化 → 本体候选 → 交付方案 → 任务分解 → Workflow 模板 →
测试计划/执行 → 证据登记 → 指标复盘」全链，链上每个环节均落
operation_events 与审计留痕，产出复盘报告。

## 2. 试点前置条件清单（逐项确认后才可启动）

| # | 条件 | 类型 | 现状锚 |
| --- | --- | --- | --- |
| C1 | 真实脱敏项目选定（代号制；真实名称/扫描件/凭证只留本地工作目录） | 数据闸 | AGENTS 红线；fdeops 工作目录先例（somwyn） |
| C2 | 项目访谈素材可用（纪要/转写稿，已脱敏或 T-A2 企业名替换层兜底） | 数据闸 | T-A2 三道防线（#160） |
| C3 | 项目模块/任务骨架就绪（分解目标 module 存在） | 数据闸 | P0-3 分解必填 module_id |
| C4 | 试点执行角色到位（project_lead 执行 + admin 审阅发布） | 拍板项 | D-2 裁决=发布维持 admin-only |
| C5 | 宿主通道保持关闭确认（试点默认全人工执行 Agent 段；不开真实 zcode） | 拍板项（默认关闭） | P1-1 5.10 闸；12 条安全前置未过 |
| C6 | （可选）若试点要真实联调 ZCode：商用条款书面确认+12 条前置逐项通过 | 拍板项（独立） | 任务书 §9 前置 1-12；§17-14 |
| C7 | 试点时间窗与复盘会排期 | 拍板项 | — |

## 3. E2E 执行面（操作序；全部 API 已随八阶段交付）

> 每步标注产出与可验证证据。`{pid}`=试点项目 id；全部走 `/api/v1`。

| 步 | 操作 | 端点 / 入口 | 产出与证据 | 实施锚 |
| --- | --- | --- | --- | --- |
| 1 | 建项目+访谈纪要导入 | 项目创建 + 访谈纪要面（interview_minutes） | 纪要行 content_sha256 | T-A9（#188） |
| 2 | 发起事实/需求抽取 | POST `/projects/{pid}/discovery/extractions`（review 后自动跑 AI 抽取 job） | discovery_extractions 行 + business_facts/requirements 草稿 | P0-1（#203） |
| 3 | 事实/需求人工审阅 | facts/requirements 三动作 PATCH（接受/拒绝/澄清）+ 批量接受 | accepted 戳 + `requirement_reviewed` 事件 | P0-1；红线=推断/开放问题强制待澄清 |
| 4 | 本体候选生成→审阅→确认 | POST `/projects/{pid}/ontology/candidates/generate` → 既有 change-set submit→confirm | confirmed 术语 + subjects.term_id 回填链接 | P0-2（#205）；AI 不绕过审批 |
| 5 | 交付方案生成→审阅→发布 | POST `/projects/{pid}/delivery-plans/generate` → PATCH review → POST publish | approved/published 方案（旧行退位 superseded） | P0-3（#207） |
| 6 | 方案条目分解到任务 | POST `/delivery-plans/{id}/tasks`（dry_run 预览 → 选择性创建） | project_tasks（待认领）+ links 幂等锚 | P0-3 |
| 7 | Workflow 草稿：模板复制或 draft-from-plan | POST `/projects/{pid}/workflows/draft-from-plan` 或人工按 `GET /api/v1/workflow-templates` 模板手建 → POST validate | draft 定义（validate 干跑全绿） | P0-4（#209） |
| 8 | Workflow 人工发布（admin）+ 发起运行 | POST publish（admin-only，D-2）→ POST runs（幂等键） | 锁版版本行 + run/节点留痕；human_approval 节点走任务中心 | T-W1~W5（V3 前收口） |
| 9 | 测试计划→执行→证据 | quality：POST generate → PATCH review（覆盖闸）→ POST execute（dev/staging；production 硬闸）→ 证据 POST `/evidence`（指针+sha256） | test_plans/cases/executions + project_evidence；失败不可改写 | P1-2（#211） |
| 10 | 指标复盘 | GET `/api/v1/metrics/report`（v31 节） | 七指标（workflow 三+域速率四）+ insufficient_data 灰态核对 | P1-3（#221） |

每步之后：核对 `operation_events` 对应事件（discovery.redaction_review /
requirement_reviewed / ontology_change_set_confirmed / delivery_plan_* /
workflow_definition_* / test_plan_* / evidence_registered …）。

## 4. 验收对照（§17-17）

试点完成后按 `docs/v3.1/final-acceptance-checklist.md` 第 17 项勾稽：
「至少一个脱敏端到端试点完成并复盘」——复盘报告落 `docs/v3.1/`（命名
`pilot-复盘-<代号>-<日期>.md`），内容含：链路各步实际耗时、指标快照、
偏离 runbook 之处、待办清单。

## 5. 复盘模板（最小集）

```markdown
# V3.1 试点复盘：<代号> <日期>
- 试点窗口 / 角色（执行者 / 审阅者 / admin）
- 链路步时序（10 步各实际耗时与卡点）
- 指标快照（report v31 节原文 + 解读）
- 偏离与原因（runbook 哪步不成立 / 需要补能力）
- 待办（进 backlog 台账，逐条带锚）
- 结论：试点是否达成 §13.5 验收；未达成项的补齐路径
```
