# V3.1 阶段状态

- 基线 SHA：`65db88c53dab1bcdea24dd9d9ad4e212acd0fc24`（fork/main）
- 当前分支：`feat/v31-p0-0-baseline-audit`（隔离 worktree `D:/test/fde-wt-v31p0`）
- 当前阶段：P0-0 基线审计
- 状态：completed
- 开始/完成时间：2026-11-07 / 2026-11-07

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
