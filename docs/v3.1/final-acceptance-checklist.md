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
| 14 | 如接通 ZCode：授权、沙箱、超时、取消、脱敏、产物校验和真实联调全部通过 | ⬜ 待条件 | **依赖：商用条款书面确认（外部）+ 12 条安全前置逐项通过（现测 8 过／2 部分〔⑧⑪〕／2 未过〔①⑦〕；③票据已接线且在首跑/重跑二两度真实行使）+ 试点联调执行**；结构面已就绪（zcode_contract 实测契约/host_channel 策略层/票据纯函数）；T-Z1 真机实测基础在案（#191-193）。**2026-11-08 已随 #17 一并提请蔡工（独立拍板项，不与试点捆绑）——业务侧已于 2026-11-09 拍板确认（D-1：通道＝宿主侧 zcode 代理／审阅人＝蔡工本人／确认 C5·C6）**，但**「拍板已得」≠「前置已过」**：12 条安全前置现测＝7 过／3 部分或须补码／2 未过（逐条锚点见 AI 原生化任务书 §6.1），且**③短期授权票据零生产调用方须先接线**⇒ 本项仍为「待条件」，待 N1 首跑复测后勾稽 |
| 15 | 指标口径统一，样本不足不误导 | ✅ | 既有 metrics 十指标 `_metric` insufficient_data + P1-3 v31 节七指标同语义（PR #221 `2d14d85`） |
| 16 | Skill 改进经草稿、审核和版本化发布 | ✅ | V3 T-S1 Skill 治理态 draft→in_review→published→deprecated + 版本行（早于 V3.1 已收口；skill_improvement_proposals 表按 7.5 裁决暂缓——首个真实改进需求出现时立项） |
| 17 | 至少一个脱敏端到端试点完成并复盘 | ✅ | **2026-11-09 试点执行完成**：蔡工确认 C1-C7（C1=代号 somwyn；C2=本地文档中心既有脱敏实记录；C3=交付段既有模块）后按 `pilot-runbook.md` 十步操作序 E2E 全链走通——纪要（整理稿 `4b558dce`）→抽取 `02a680d7`（22 facts+7 reqs）→审阅（20+7 accepted、2 needs_clarification）→本体 `ffa95ce0` confirm（决策分离经 pilot.reviewer，物化 20 术语）→方案 `c0f1dc00` published（9 items）→分解 9 任务（幂等复跑 skipped=9）→草稿 `44ac0ea1` validate 全绿→run `21fc3fa9` succeeded（两处 human_approval 拍板）→测试计划 `5b538ea5` approved→execute dev 7/7 passed→证据 `aa2b85a9`（指针+指纹）→指标七项全 ok。复盘报告：`docs/v3.1/pilot-复盘-somwyn-2026-11-09.md`（含五项偏离注记与 backlog 待办；**偏差 D1=审阅动作 admin 代执行，建议蔡工桌面端复核**） |
| 18 | 全量回归通过，或已知基线失败有批准说明 | ✅ | 各阶段本地全量 EXIT=0 + CI 4 job 绿 + main run 收口（最新：P1-3 轮 2354=2348+6s EXIT=0；融合树 CI 绿） |
| 19 | 无未解决高危安全问题 | ✅ | 安全线全程在案：CI secrets-scan/pseudonymization 双闸绿；安全前置未过通道保持关闭；客户资料红线零触碰 |

## 结论

- **17 项达成、1 项待条件（#14 ZCode 真实联调）、0 项未达成**（2026-11-09 somwyn 试点完成后）。
- #17 已达成（试点执行+复盘落盘，2026-11-09）；唯余待条件一项依赖**业务闸**：
  - #14：**业务侧拍板已于 2026-11-09 落定**（D-1：通道＝宿主侧 zcode 代理、审阅人＝蔡工本人经第二账号、确认 C5·C6）⇒ 本项从「待业务拍板」转为「**待前置核验 + 待真实联调执行**」：按任务书 §9 十二条安全前置逐项通过（现测 **8 过／2 部分〔⑧⑪〕／2 未过〔①⑦〕**；③票据已接线且两度真实行使；**抽取腿复测已由 V31-P1c 全量 rerun 消解**——任务书 §13 记录 #10）＋ 商用条款书面确认（外部依赖未取得）＋ N1 真实订单首跑复测后，按既有通道开关（默认关）执行并回写。
- 全部八阶段实施代码已合并且部署活体验证；试点轮自身零代码零迁移零路由（数据在活库、复盘为纯文档；偏离与待办见复盘报告 §4/§5）。
