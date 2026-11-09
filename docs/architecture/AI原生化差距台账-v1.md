# AI 原生化差距台账 v1.1

配套 [AI原生化差距评估-v1.md](./AI原生化差距评估-v1.md) 的逐条对账台账。

- **修订记录**：**v1**（2026-11-09 首版，G-01–G-14）→ **v1.1**（2026-11-09，圆桌评审后：加「体量/依赖」两列〔R-08〕、G-06 上调 Path 1〔R-05〕、G-12 附注升级〔R-10〕、新增 **G-15**〔R-12〕/ **G-16**〔R-02〕、首圈注记按探针第二轮改写〔R-01/R-09〕）。
- **评估基线**：fork/main `f589801`（含 #232 试点复盘；锚点复核基线 `cddefd4`=#231——#232 纯文档零代码，锚点不受影响）；活库探针 2026-11-09（两轮）。
- **用途**：每轮实施前认领条目 → 实施后按「消解判据」复测 → 回写状态与实施轮号（PR 号）。锚点是行号级快照——**上游合并后行号漂移不算失效**，按符号重 grep 即可；**语义漂移**（锚点所指行为变了）须复核并在本行注记。
- **列语义**：体量 S=小轮（≤1 天）/ M=常规轮 / L=需设计轮先行；依赖=「消解前须先闭合的条目」。
- **状态语义**：`OPEN`（未实施）／`IN_PROGRESS`（在途 PR）／`CLOSED`（消解判据复测通过，注记 PR 号）／`WONTFIX`（有意不消解，注记理由）。

| 编号 | 差距 | 归属特征 | 现状锚点（2026-11-09） | 消解路径 | 消解判据 | 体量 | 依赖 | 状态 | 实施轮 |
|---|---|---|---|---|---|---|---|---|---|
| G-01 | 三条 AI 执行通道源码默认全关；agent 执行面活库零行使（首圈由降级直连承役，DSH 未上岗） | ①④ | `server/src/fde_api/config.py:83`（dsh）、`:147`（宿主通道）、`:158`（轮询）；agent_runs=0 | Path 0 | 受控试点内至少一条通道开启，且首个含 agent run 的真实订单至 G9 | M | — | OPEN | — |
| G-02 | AI 不能发起 run：MCP 17 工具无 initiate 类；发起路由全部面向人 | ①③ | `server/src/fde_api/control/mcp_gateway.py:36`（17 键全列见评估 §2） | Path 3 | MCP/api_actions 新增受 15min 确认窗的 run 发起动作，含取消语义/幂等键/授权绑定三样安全清单（R-03），端到端审计留痕 | M | G-16 | OPEN | — |
| G-03 | DAG 规划无 AI：节点类型四值闭集；图来源=人工模板或确定性编译器 | ① | `server/src/fde_api/workflows/constants.py:50`；`workflows/compiler.py:326`；`server/seeds/workflow-templates.json` | Path 1 | 存在 AI 起草 DAG 草稿→validate 干跑→人工 create_definition 发布的完整链 | L | G-09 | OPEN | — |
| G-04 | 交付方案生成器确定性拼装，零 AI | ① | `server/src/fde_api/plans/service.py:64,75` | Path 1 | 方案条目支持 AI 起草且仅经 approved 闸发布（版本化不覆盖历史） | M | G-09 | OPEN | — |
| G-05 | 测试用例生成器确定性拼装，零 AI（**建议决策位 AI 试点首发**——两段式审核戳现成，R-11） | ① | `server/src/fde_api/quality/service.py:4,72` | Path 1 | test_cases 支持 AI 起草通道，审核语义仍由计划 draft→approved 闸承载 | M | G-09 | OPEN | — |
| G-06 | 派单无 AI 推荐（BP §1.3a L3 定义含「AI 参与派单推荐」，R-05 上调为 Path 1 组成；仍建议入口+人工终审，责任主体永远是人的 PRD 拍板不放松） | ① | `server/src/fde_api/dispatch/scoring.py:3,7` | Path 1 | 派单推荐由 AI 起草、人工终审采纳，责任主体语义不变 | M | G-09 | OPEN | — |
| G-07 | 门禁 AI 起草证据候选链未接：captured_from 单一 human 源；agent_run:/workflow_node: 前缀全仓零生产者 | ①② | `server/src/fde_api/projects/gate_service.py:275`；`evidence/models.py:18`；`evidence/service.py:84-98` | Path 1/2 | 首个 agent run 产物自动登记为建议性证据候选（采纳仍走人工提交闸） | M | Path 0 首跑 | OPEN | — |
| G-08 | 人工接受信号只写不读：reviewed 无任何 AI 面消费点 | ② | `server/src/fde_api/agents/service.py:1445,1468`（写）；`:363`（仅 API 呈现） | Path 2a | 至少一个 AI 面消费点读取 reviewed（如审查优先级/提示词复审信号） | S | — | OPEN | — |
| G-09 | ai_call_audits 无提示词指纹/版本列，输出无法按提示词版本归因 | ②④ | `server/src/fde_api/workbench/models.py:920` 起（列集：request_id/actor/purpose/model/tokens/status/error_code） | Path 2a | 新列落地（迁移），新调用全量回填指纹，历史行容忍空值 | M | — | OPEN | — |
| G-10 | golden set 不连真实模型；CI 无 AI 评测 job | ②④ | `server/tests/fixtures/ai/opportunity_golden_set.json`（23 例）；`server/tests/test_ai_eval/test_ai_eval_opportunity.py:19`（直调后处理）；`.github/workflows/ci.yml`（四 job 无 eval） | Path 2b | CI eval job 按交付效果评测协议 v0 跑真实模型并出 uplift 报告（insufficient_data 语义保留） | M | G-09 | OPEN | — |
| G-11 | 模拟实验室改进链止于 approved，「只提案不落地」无发布通道 | ②④ | `server/src/fde_api/simulation/improvement_service.py` 头注（P8 四条）；`server/tests/test_simulation_improvement.py:403`（静态钉） | Path 2b | 受控发布通道（发布闸+审计+可回滚），静态钉改为「只许经发布通道写」语义而非删除 | L | G-09 | OPEN | — |
| G-12 | ~~模拟模型评估 server 模式未接线~~ | ④ | 已消解：`server/src/fde_api/simulation/model_evaluation.py:168`（ServerModelEvaluation→ai/deepseek complete_json purpose="simulation_evaluation"）+ `evaluation_prompt.py:17` + `evaluation_schema.py` 契约 | — | 真模型评估栈在仓；活库行使归 Path 0/2b | — | — | **CLOSED（#231，2026-11-09）** | #231 |
| G-13 | 提示词版本化 1/5：仅 discovery 带版本戳；模拟评估 Rubric 有版本、提示词本体无 | ④ | `server/src/fde_api/discovery/models.py:44,93`；`ai/research_form_prompt.py:9`；`ai/industry_template_prompt.py:10,21`；`simulation/evaluation_prompt.py:17` | Path 4 | 全部 SYSTEM_PROMPT 常量进版本注册表并回填审计归因 | S | G-09 | OPEN | — |
| G-14 | 指标面只读无回流：metrics v31 七指标无任何自动消费方 | ② | `server/src/fde_api/metrics/service.py:341`（v31 节） | Path 2b | 指标触发至少一个自动改进动作（如阈值越限生成提示词复审工单） | M | G-09 | OPEN | — |
| G-15 | 桌面缺 AI 运行编排/多 run 管理面（现有 DiscoveryPanel/AgentsConsole/GuidanceReview 均为单点审阅面；「人管理 Agent」的呈现缺口，R-12） | ③ | `desktop/src/renderer/src/`（agents/guidance/discovery 各控制台单点） | Path 1/3 | 桌面存在跨 run 的编排/管理视图（列表→批量操作→终审队列任一形态） | M | Path 0 | OPEN | — |
| G-16 | ai_call_audits 存在 purpose=None 匿名行（2/6，11-06 与 11-08 各一）——存在不带用途标识的调用方，审计归因不闭合（R-02） | ② | 活库探针 2026-11-09（audits 明细见评估 §5）；`control/ai_server_client.py:186`（purpose 为可选参） | Path 2a | 全量 AI 调用强制 purpose 非空（或白名单豁免登记并注记调用方），存量行排查注记 | S | — | OPEN | — |

## 附注

- **G-12 附注（R-10 升级）**：CLOSED 指**契约在仓**（#231 G9 接线）；**行使为零**（simulation_runs=0），且「模型层缺席（unavailable）时三层机制裁决」仅 stub 模式端到端测过——首次真实跑场前不得引用为「模型评估能力已验证」。另 `simulation/model_evaluation.py:10-11` 模块头 docstring 仍写「本轮未接线」（G1 陈旧注记；类级 docstring `:168` 为权威），留给下一 V3.2 轮顺带清理。
- **红线约束适用于全部条目**：AI 不代拍板；门禁证据只存指针+sha256；客户资料不入库；写外呼/发信/付款永不降级不自动。任何条目的实施轮不得以「消解差距」为由放宽上述边界。
- **首圈注记（2026-11-09，R-01/R-09 改写；#232 复盘落档后更新）**：售前链首批真实数据（discovery 2 / facts 22 / requirements 7 / delivery_plans 1 / test_plans 2 / workflow_runs 1 succeeded〔human_approval×2+skill×1〕）。承役通道=**降级直连**（audits 6/6 `used_fallback=True`），DSH 未上岗；模型 MiniMax-M3.1-Flash；**抽取 4 试 1 成**（3 failed `ai_output_invalid`）。**官方复盘已落档（#232）**：`docs/v3.1/pilot-复盘-somwyn-2026-11-09.md`（项目 `7042d7ab`、run `21fc3fa9`、指标 v31 七指标全有样本）；抽取失败根因=backlog **V31-P1**（降级直连腿未按推理模型预留输出预算，大纪要必败；成功例输入为人工整理稿）——原「失败归因复盘」行动项转为「跟踪 V31-P1 消解后复测」。样本量=1，只证明链路通。
- **首圈零代码复盘不属于本台账条目**（是行动不是差距）——其产出（提示词 v2 假设）在 G-09/G-13 落地后才有归因位。
