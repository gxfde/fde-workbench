# V3.1 阶段状态

- 基线 SHA：P0-0 审计=`65db88c`；P0-1 批A 开发基线=fork/main `9aaa4ef`（含 #197 本线 P0-0 与 #198–201 V3.2 模拟训练场并发并入）
- 当前分支：`feat/v31-p0-1-discovery`（隔离 worktree `D:/test/fde-wt-v31p0`）
- 当前阶段：P0-1 访谈事实与需求结构化——**批A（服务端）completed 待合并；批B（桌面审阅 UI）pending**
- 状态：in_progress（批A 已交付）
- 开始/完成时间：P0-0=2026-11-07 完成（PR #197 已合并 fork/main `14d2b62`）；P0-1 批A=2026-11-08 完成

## P0-0（completed，已合并）

四报告+任务书入库+复用/扩展/新建裁决（详见 `00-baseline-audit.md` 等），PR #197 squash 合并为 `14d2b62`，CI 4 job 全绿。遗留：拍板项 D-1~D-4 待蔡工确认（不阻塞 P0-1 批A——批A 不踩跨项目别名/发布权限/锚点粒度三议题；D-3 宿主通道对齐已由 #195 落地自动消解大半）。

## P0-1 批A（服务端，completed）

- **交付**：NEW `discovery/` 五文件（models/contract/prompt/jobs/routes）+ 迁移 `c3d5e7f9a1b4`（挂上游 V3.2 G6 头 `e8b1d5f9a3c7`）+ 8 路由 + 14 例测试；7 处注册点（app 蓝图/jobs handler+失败钩子/reconcile RECOVERABLE/env.py/conftest 清理序/test_migrations HEAD/extract 脚本 BLUEPRINTS）+ 提示词卫生闸登记（`_ALLOWED_PROMPT_CONSTANTS`）。
- **设计裁决**（00-gap-register P0-1 全部落地）：七组示例收敛 facts[].fact_type 十值+requirements 独立组；classification 对齐 guidance 五分类；抽取行 status 四值（accepted/rejected=派生态不物化，B#13-C 先例）；requirements 结构化 acceptance_criteria 列表；requirement_sources 关系表（任务书原文）。
- **红线对齐**：整批失败零写入；推断/开放问题强制待澄清；无来源需求不得自动接受；输出端 T-A2 兜底脱敏+复核事件；重跑仅 failed（审阅痕迹不可覆盖）；全部路由不进 api_catalog。
- **测试**：14 例全绿+回归簇 46 passed+邻域 37+上游 simulation 14；mypy 279 不变；测试库外来戳重建（教训：版本戳骗过 upgrade——重建必须清全表）。

## P0-1 批B（桌面，completed 随批A PR 同窗交付）

- NEW `desktop/src/renderer/src/discovery/DiscoveryPanel.tsx`（挂项目 overview tab、转写面板之后——访谈区聚合）：抽取发起（纪要下拉+幂等 created 双文案）/抽取记录表（状态徽标+失败码+脱敏复核条目 tooltip+重跑仅 failed）/事实清单（审阅状态过滤+三动作接受/拒绝/澄清+**批量接受本页待审**〔逐条 PATCH、失败计数如实汇报〕+锚点三形态呈现 line/transcript_segment/char_span）/需求清单（批准/否决/澄清+验收条数+来源计数）。写操作 canManage 显隐。
- NEW `desktop/tests/renderer/discovery-panel.test.tsx` 7 例（三列表加载+复核呈现/锚点三形态/POST 形状+幂等提示/重跑显隐/PATCH 形状/批量只打 pending/viewer 全隐）。
- 口径：vitest 944→951（+7）；typecheck 0 错；零服务端改动。

## 遗留问题

1. 拍板项 D-1（跨项目别名冲突）/D-2（发布权限）待蔡工确认——分别阻塞 P0-2 部分/不阻塞。
2. D-4（锚点粒度）已在批A 以三形态闭合枚举（line/transcript_segment/char_span）落地，契约层收敛，批B UI 按此呈现。
3. 任务书 §16 其余文档（architecture/api-contracts/data-model/security-review/pilot-runbook）随对应阶段交付。

## 是否允许进入下一阶段

P0-1 批B（桌面）→ 批B 合并后 P0-1 整阶段收口 → **P0-2 本体候选与稳定 ID**（先落 ADR-002 文档+D-1 拍板确认）。

## 本阶段目标

按任务书 §2「P0-0 必须先完成的代码核验」十条，只做基线审计不改业务代码；产出四份审计报告并给出复用/扩展/新建/暂缓裁决。

## 真实代码定位

四域并行深查（transcripts/guidance/meetings、agents/zcode/control 执行面、workflows/jobs/metrics、ontology/gate/tasks/solutions/evidence/handover），全部结论带 `file:line` 锚，汇总于：

- `00-baseline-audit.md`（十条核验逐项结论+口径现测+活库运行数据）
- `00-data-model-map.md`（109 表按域分组、迁移链、事件/异步底座、API 面）
- `00-test-baseline.md`（环境/命令/结果/209 测试文件/回归面映射）
- `00-gap-register.md`（P0-1~P1-3 逐能力裁决+横切纪律+4 项拍板项）

任务书 §2 表格 25 项路径核验：24 项原路径命中、1 项修正（AgentsConsole 实际在 `agents/` 子目录）。

## 设计决策及理由

1. 审计在隔离 worktree @ fork/main 执行（主树落后 23 提交且有并发会话脏集），不触碰用户未提交修改。
2. 历史台账口径（107 表/38 rev/315 路由/pytest 2116）确认为旧值，全部以本轮现测替代（109/39/e5f1a7c3b9d4/323/pytest 见 test-baseline）。
3. `zcode_contract.py` 纯函数契约层判断成立；发现 `adapter.py` spawn 段为自认虚构契约（与真实 0.17.1 CLI 相悖）——登记为 P1-1 重构靶点而非本轮修复。
4. `control/ontology.py` vs `ontology/` 零代码级重叠（静态字典 vs 治理层），ADR-002 列为 P0-2 文档交付物。
5. 每项「新建」裁决均附负结论核验（grep/表全集证据），满足任务书 §1.3「核验现有能力前不新增」纪律。

## 修改文件

仅文档（零业务代码/零迁移/零路由/零桌面）：

- NEW `docs/v3.1/00-baseline-audit.md`
- NEW `docs/v3.1/00-data-model-map.md`
- NEW `docs/v3.1/00-test-baseline.md`
- NEW `docs/v3.1/00-gap-register.md`
- NEW `docs/v3.1/phase-status.md`（本文件）
- ADD `docs/蔡工_FDE_Workbench_V3.1_智能交付自动化升级路线图与Goal实施任务书.md`（用户提供的任务书原稿，从主树未跟踪状态正式入库，作为 V3.1 唯一权威任务书）
- NEW `docs/v3.1/decisions/`（空目录预留 ADR；git 不跟踪空目录，实际由 P0-2 的 ADR-002 首个文件建立）

## 数据库迁移

无。

## API / 权限 / API Catalog

无变化（审计含 API Catalog↔路由差异核验：323 全路由 vs 94 ENTRIES 为设计性差异，CI 双钉在位）。

## 前端变化

无。

## 测试命令与结果

见 `00-test-baseline.md` §2（pytest 全量/vitest 932/typecheck/mypy 279 基线全绿；零新增测试——纯文档轮）。

## 安全检查

- 未运行被审代码；未执行生产变更；未读取客户资料。
- 活库查询为只读 SELECT（经 api 容器内引擎）。
- 发现类安全注记：P1-1 的 12 条安全前置未过前宿主通道保持关闭（任务书红线原文遵守）；在途会话 `feat/host-zcode-channel` 线需先对齐（gap-register D-3）。

## 数据兼容与回滚

纯文档，无需回滚；合并后如需撤销直接 revert 本 PR 即可。

## 验收证据

- 四报告齐全且十条核验逐项有锚（本文件+00-baseline-audit.md §1-§10 对照表）。
- 复用/扩展/新建/暂缓四档裁决覆盖 P0-1~P1-3 全部条目（00-gap-register.md）。
- 口径现测与 fork/main CI 实测逐位一致（test-baseline §4）。
- CI 4 job 绿（PR 链接见合并记录）。

## 遗留问题

1. 4 项拍板项（gap-register D-1~D-4）待蔡工确认后进入对应阶段。
2. 任务书 §16 建议目录中的 architecture.md / api-contracts.md / data-model.md / security-review.md / pilot-runbook.md 属后续阶段交付物，P0-0 不预支。

## 是否允许进入下一阶段

**允许进入 P0-1（访谈事实与需求结构化）**——前置基线已闭合：transcripts/guidance 域真实代码定位、四表新建论证、脱敏/任务/校验三范式复用清单齐备。P0-1 方案设计须先按任务书 §5 约束出最小改动清单（新表+job_type+契约校验器+审阅 UI），其中锚点粒度（D-4）建议随方案一并呈批。
