# V3.1 最终验收清单勾稽（任务书 §17 十九项，2026-11-08 P2 轮核验）

> 核验基线：fork/main `2d14d85`（P1-3 合并态；八阶段 PR #197/#203/#205/#207/#209/#211/#213/#215/#221 全部 CI 绿+main run 收口+部署活体）。
> 三态：**✅ 达成**（附锚）/ **⬜ 待条件**（试点数据闸或拍板项，如实标注依赖）/ ⚠️ 部分。
> 本文件随试点执行更新：第 17/14 项完成后回填证据。

| # | 验收项 | 状态 | 证据锚 |
| --- | --- | --- | --- |
| 1 | 基线审计、数据模型图和测试基线归档 | ✅ | P0-0 四报告入库（PR #197 `14d2b62`）：00-baseline-audit / 00-data-model-map / 00-test-baseline / 00-gap-register |
| 2 | 访谈事实/需求可追溯到原始来源 | ✅ | P0-1 `requirement_sources` 关系表 + facts.source_ref/source_locator 三形态（PR #203 `92ca0bd`） |
| 3 | 事实/需求支持接受、拒绝、澄清和审计 | ✅ | P0-1 行级审阅终态留痕 + 两段式审核戳 CHECK + approved 戳（#203） |
| 4 | 本体候选不能绕过 Change Set 审批 | ✅ | P0-2 候选桥只产候选，采纳唯一入口=既有 submit→confirm 人工管线（PR #205 `858e090`） |
| 5 | 至少一个试点领域对象使用稳定 ID，旧数据兼容 | ✅ | P0-2 `project_research_subjects.term_id` 可空 FK + confirmed 落定自动回填 + 读路径名字域兜底（#205） |
| 6 | 交付方案引用已批准需求并有版本 | ✅ | P0-3 `delivery_plans`（draft→approved→published+superseded，requirement_keys 引用清单）（PR #207 `889f964`） |
| 7 | 方案条目幂等映射到现有项目任务 | ✅ | P0-3 `delivery_plan_task_links` UNIQUE(item) 幂等锚 + skipped 留痕（#207） |
| 8 | Workflow Draft 可生成、校验、人工发布 | ✅ | P0-4 draft-from-plan + validate 干跑端点 + admin-only 发布（D-2 拍板维持）（PR #209 `b196074`） |
| 9 | Workflow 可恢复、取消、重试且幂等 | ✅ | V3 T-W5 cancel/resume + B#14 对抗钉（强杀族/tx B 崩溃族/恢复底座，早于 V3.1 已收口） |
| 10 | Gate Service 是唯一门禁状态决策入口 | ✅ | 既有 `gate_service`；workflow 产物只能经 `gate_evidence` 挂候选、采纳唯一入口=真人提交闸（T-W7） |
| 11 | Agent 产物有来源、hash、审核和撤回信息 | ✅ | 既有 agent_artifacts（storage_ref+sha256+reviewed 戳）+ P1-1 revoked 留痕补强（revoked_by/at，PR #215 `58f7a26`） |
| 12 | 测试失败不能被 Agent 摘要改写为成功 | ✅ | P1-2 执行 append-only（服务层零更新函数+无 PATCH/PUT/DELETE 执行路由静态钉）（PR #211 `9b5e030`） |
| 13 | ZCode 未通过安全审批时保持关闭并可人工接管 | ✅ | P1-1 `agent_host_channel_enabled` 默认 False + 双静态钉（d4_settings+config AST）；人工接管=L1 链路既有语义（#215） |
| 14 | 如接通 ZCode：授权、沙箱、超时、取消、脱敏、产物校验和真实联调全部通过 | ⬜ 待条件 | **依赖：商用条款书面确认 + 12 条安全前置逐项通过（业务拍板）+ 试点联调执行**；结构面已就绪（zcode_contract 实测契约/host_channel 策略层/票据纯函数）；T-Z1 真机实测基础在案（#191-193）。**2026-11-08 已随 #17 一并提请蔡工（独立拍板项，不与试点捆绑）——待线下拍板** |
| 15 | 指标口径统一，样本不足不误导 | ✅ | 既有 metrics 十指标 `_metric` insufficient_data + P1-3 v31 节七指标同语义（PR #221 `2d14d85`） |
| 16 | Skill 改进经草稿、审核和版本化发布 | ✅ | V3 T-S1 Skill 治理态 draft→in_review→published→deprecated + 版本行（早于 V3.1 已收口；skill_improvement_proposals 表按 7.5 裁决暂缓——首个真实改进需求出现时立项） |
| 17 | 至少一个脱敏端到端试点完成并复盘 | ⬜ 待条件 | **P2 试点本体**：执行面与前置条件已落盘 `docs/v3.1/pilot-runbook.md`（C1-C7 前置清单+10 步操作序+就绪预检 18/18 端点在位）；待真实项目数据闸（C1-C3）+ 拍板（C4-C7）后执行。**2026-11-08 已向蔡工提请 C1-C7 确认（goal 循环交互问答未获答复=无人值守态）——待线下拍板；试点启动不适用「按推荐项代执行」先例（依赖真实客户数据，AI 不得伪造试点）** |
| 18 | 全量回归通过，或已知基线失败有批准说明 | ✅ | 各阶段本地全量 EXIT=0 + CI 4 job 绿 + main run 收口（最新：P1-3 轮 2354=2348+6s EXIT=0；融合树 CI 绿） |
| 19 | 无未解决高危安全问题 | ✅ | 安全线全程在案：CI secrets-scan/pseudonymization 双闸绿；安全前置未过通道保持关闭；客户资料红线零触碰 |

## 结论

- **16 项达成、2 项待条件（#14 ZCode 真实联调、#17 E2E 试点本体）、0 项未达成**。
- 待条件两项的依赖均为**业务闸**（真实项目数据 + 蔡工拍板），非代码缺口：
  - #17：按 `pilot-runbook.md` §2 前置清单（C1-C7）逐项确认后即可执行；
  - #14：按任务书 §9 十二条安全前置逐项通过后，按既有通道开关（默认关）+ 试点联调执行。
- 全部八阶段实施代码已合并且部署活体验证；P2 轮自身零代码零迁移零路由（纯文档 runbook+勾稽）。
