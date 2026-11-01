# goal-d8 · 交付工作台升级轮次报告（2026-11-01）

> 输入：goal-d7 报告 + PRD v1.0 定稿 §3.2/§6/§10 + 《需求与设计总纲》+ goal 循环提示词 v1.0（goal-d8 节）+ 代码实测（fork/main `6857055` 基线）。
> 本轮定位：**S2 dispatch×agents 合成（D2 裁决落地）+ P3 预备**。派单 8 态机零改动、TRANSITIONS 表零改动、`fde_profiles`/`package_access`/`match_breakdown` 零改动。

## 〇、预检（2026-11-01）

- fork/main = `6857055`（goal-d7 squash 合并后基线）；本地 main 仍 `755e429`（并发会话 6 M 文件未提交改动，按红线全程不碰，ff 继续顺延）。
- 隔离 worktree：`D:\test\fde-workbench-d8`（feat/goal-d8 ← fork/main，`--unset-upstream` 已执行；node_modules / server/.venv junction 指主树绝对目标；.env / server/.env 已拷贝）。
- 主树 dispatch 文件（models/packages/routes/api_catalog/gates.json）存在并发会话未提交改动——本轮全部在 worktree 基于 6857055 干净基线实施，与其零交集。

## 一、差距清单（本轮覆盖项）

| # | 能力项 | 目标（出处） | 现状（代码证据） | 定级 | 行动 |
|---|---|---|---|---|---|
| 1 | `agent_assisted` 协同标记（交付包级） | 接单人显式声明后才启用评审门与溯源联动；不声明=纯人工交付，行为与 v0.2.0 一致（PRD §6.3，D2 裁决） | `delivery_packages` 无该列；start_run 对已接单包零感知（agents/service.py start_run 只查 solution/T1 闸） | P2 必须 | 迁移 +2 列；声明端点；start_run 准入闸 |
| 2 | 派单订单难度自动带入 run.difficulty | T4 免手报；O-4 三档处理（PRD §6.4） | d7 落 `agent_runs.difficulty`（standard/high，发起人手报）；`delivery_packages` 无难度列 | P2 必须 | `delivery_packages.difficulty`（low/medium/high）；发布时定档；start_run 映射带入（low→standard/medium→high/high→协同禁入） |
| 3 | 声明/未声明两态集成测试 | PRD §6 逐条验收 | 无 | P2 必须 | test_agent_assisted_integration.py 新建 |
| 4 | PRD §6 四条合成规则逐条测试 | 循环提示词 goal-d8 验收 | 仅裁决文档，无测试锚点 | P2 必须 | 同上文件四条规则各一组用例 |
| 5 | P0/P1 指标报表 | P0 四指标 + P1 试点观测 + 持续观测（PRD §10） | 无任何指标聚合端点/页面 | P3 预备 | 服务端 `GET /metrics/report`（只读聚合）+ 桌面 `#/metrics` 报表页（admin/project_lead） |
| 6 | 翻译器门户骨架 | 引导式翻译 + 实时预览（PRD §3.2 P3） | 无 | P3 预备（骨架） | 桌面 `#/translator` 引导式表单 + 实时只读预览（纯前端，不落库不调 AI） |

### 不做边界（本轮明确不做）

1. 撮合核心不派发 high 难度订单给智能体（P1-2 职责，goal-e 并行轨）——本轮只做声明侧防线（difficulty=high 禁声明）。
2. M10 派单 Stage A/B 证据引用联动（挂账，见 §四）。
3. U6 全量成本归集（话轮/收敛计费）。
4. std-full 档独立门模板（试点升级后）。
5. 翻译器 P3 全量：AI 翻译管道、落库、终审台「产物+纪要」合并视图——本轮仅骨架只读预览。
6. 指标页数据导出/权限细分——本轮登录可见聚合（脱敏聚合无客户数据），admin/project_lead 路由级限制。
7. 撤销声明的追溯处理（撤销后既有 run 不回溯，文档声明）。
8. D10 五项待蔡工拍板（S 编号映射/九卡原句/报价卡数值禁区/G3 会闸关系/审定流程）。

## 二、行动说明

分支 `feat/goal-d8`（← fork/main `6857055`）；零新表（95 业务表不变），1 迁移 `b8c2d6f0a4e7`（19 revision：`delivery_packages` +`agent_assisted` Boolean server_default false + `difficulty` String(8) Check low/medium/high nullable）；蓝图路由 262→**264**（+dispatch agent-assisted / +metrics report）；api_catalog ENTRIES 89→**91**（+1 写 dispatch.agent_assisted_declare——沿 packages_publish 配置类写路径先例（协同声明=接单人显式行为，非代拍板）；+1 只读 metrics.report）。改动 10 文件 + 10 新文件。

### d8 四条设计决议

1. **协同准入闸的精确语义（规则③）**：准入条件 = `delivery_packages` 存在（包 id=solution.id，r3 结构事实）且 `dispatch_status=="accepted"` 且未声明——此时 start_run 409 `agent_assisted_required`（纯人工交付，v0.2.0 行为；准入先于 T1 流程门，零 run 落库）。draft/published 等未接单态与无包项目不受任何影响（售前段 d4–d7 语义零回归）。**评审门启用不引入新门**——d7 已把 T1/T4/T5 落为状态机级强制门，声明的增量 = 解锁准入（不声明时智能体根本进不来），溯源联动 = 包↔方案同键 + 白名单 `agent_assisted`/`difficulty` 两键 + 产物 `artifact.linked_solution_id` 既有链三点成链（零新表）。
2. **订单难度三档与 run 两档映射（规则④）**：`difficulty` ∈ low/medium/high 对齐 O-4 三档处理口径；发布交付包时平台侧定档（`publish_package` +difficulty 参数，可选），start_run 按 `low→standard / medium→high` 映射自动带入 `agent_runs.difficulty`（T4 免手报）；显式手报与订单映射冲突 → 400 `difficulty_order_conflict`（透明化，不静默覆盖）；`high` 在声明侧前置禁入（409 `difficulty_excludes_agents`）+ start_run 防御兜底双保险。medium 带入 high 后 T4 全链自动生效（lite 纪要拦截 → 升档 full 加座）——实测用例证明。
3. **声明权与撤销口径（规则①）**：声明/撤销端点 `POST /dispatch/packages/<id>/agent-assisted {enabled}`——权限 = 接单人（accepted_user_id/seat_delivery）或 admin 管理通道；draft 包无接单人 → 非接单人先撞 403 `declarer_required`（规则①：声明权在人）。声明不是状态迁移：8 态机零改动、TRANSITIONS 零改动，动作只落列 + OperationEvent（`agent_assisted_declared`/`agent_assisted_revoked`）留痕；幂等（同值重复声明不重复留痕）。撤销只影响后续 run，既有 run 不回溯。
4. **指标报表的诚实口径（§10 落地）**：可计算子集实测（确认率按 project 去重 / 草稿耗时中位数 / lite 占比 / 一次通过率 / 降级率 / 成本中位数 / 当月动作+超额行）；**缺埋点三类显式 `insufficient_data`**（SOW 一次拍板率、资深工程师介入时长、输出拦截率——拍板/计时/422 拦截事件无埋点，挂账台账），不编造数值；「一次通过率」当前口径 = 终态 completed 占比（retry 幂等链未折算，挂账）；「草稿耗时」当前口径 = agent 路 duration_ms 中位数（人工路无计时，基线对比挂账）。报表脱敏聚合（计数/占比/中位数，无客户数据）→ require_auth 登录即可读，桌面路由 admin/project_lead。

### 其他改动

- 白名单 +2 键（`agent_assisted`/`difficulty`，§9.2 纪律②显式 schema 直出，有意扩白名单——接单人据此知道协同态与难度档位）。
- 桌面：`#/translator`（全角色，引导式表单三步 + 实时只读预览，纯前端启发式映射 `preview.ts` 不调 AI 不落库，提交入口 disabled 标注 P3 开放）；`#/metrics`（admin/project_lead，三分区指标卡，insufficient 灰态「数据未积累」）；AppShell 导航两项。
- 桌面 target 渲染 bug 由测试抓出并修复（`card.target !== null` 对 undefined 失效 → `!= null`，避免 `≥NaN%` 徽标）。

## 三、验收判据

| 项 | 结果 |
|---|---|
| PRD §6 规则①（接单主体是人） | 非接单人声明 403 declarer_required；声明前后 dispatch_status 守恒 + TRANSITIONS 零改动断言（publish: draft→published 行为不变） |
| PRD §6 规则②（降级天然兼容） | 协同包上 L1 降级 run 家族 t2_gate_satisfied=False（T5 门语义不因协同列旁路）；fallback 链测试 d7 全绿零改动 |
| PRD §6 规则③（协同显式声明） | 未声明 accepted 包 start_run 409 agent_assisted_required 零 run 落库；draft/无包/未接单态零感知（review_gate_open 到位）；声明后 201 全链；声明幂等事件唯一；撤销后复闸 |
| PRD §6 规则④（O-4 三档） | difficulty=high 禁声明 409 + start_run 防御兜底；low→standard / medium→high 自动带入（免手报实测，medium 带入后 T4 lite 拦截→full 升档→retry 放行全链）；手报冲突 400 difficulty_order_conflict；一致手报放行 |
| 两态集成 | 声明/未声明两态 17 用例 + 发布定档 400/200 白名单透出 |
| 指标报表 | 空库三类 insufficient 显式灰态；造数据后确认率（project 去重）/lite 占比/一次通过率 0.6/降级率 1/3/中位数/当月动作+超额行逐指标核对；401 未登录 |
| 翻译器骨架 | 预览映射 4 例（切分/预标/截断/空态）+ 页面 2 例（骨架徽标/提交禁用） |
| 迁移/口径 | head `b8c2d6f0a4e7` 双跑（down→up→down→up）干净；95 业务表不变；路由 264 / ENTRIES 91 |
| pytest | **1649 收集 = 1643 passed / 6 skipped / 0 failed**（+22 新用例，全量 21:38；首轮 2 失败=2 盘点断言合法适配——白名单键数（+agent_assisted/difficulty）与 HEAD_REVISION 常量，处置后复跑绿） |
| vitest / typecheck | **713/713 全绿**（59 文件，串行 275s）；typecheck 零错误 |
| ruff / mypy | All checks passed；新文件零 mypy 错误，总错误 274 ≤ d7 基线 279（无新增） |
| 变异闭环 | **7 处各红→还原→绿**（准入闸反转/映射反转/high 禁声明摘除/声明幂等摘除/insufficient 伪造/确认率恒真/灰态摘除）；两过程事故如实登记（见下） |

### 过程事故（如实登记）

1. **变异驱动脚本中途崩溃致 WEB⑦ 变异残留工作区**：首次跑变异脚本在 MET⑥（值碰撞未红）后于 WEB⑦ 处崩溃（对 vitest 输出的 red 判断解析脆弱），变异体残留在 MetricsReportPage.tsx 未还原。处置：从唯一变异前快照回写还原 + diff 字节级核对（`cmp -s` 在 Git Bash 对 `C:\...` 反斜杠路径静默误报 DRIFT——以 `diff`/`git diff` 为准，d7 filecmd 教训同源）+ WEB⑦ 手动重做红→绿→BYTE_IDENTICAL 三重确认。零残留实证：4 快照 × diff 全一致。
2. **MET⑥ 变异值碰撞**：`== "confirmed"` → `!= "confirmed"` 在 2 confirmed + 1 draft 的用例数据下确认率恰仍 0.5（集合对称）→ 变异后不红。非测试失效，是变异设计缺陷；改恒真变异（confirmed_projects=全部项目 → rate=1.0）后红→绿。

## 四、遗留与下轮建议

### 挂账（新登记，台账节三十三）

| # | 事项 | 时点 |
|---|---|---|
| 1 | M10：派单 Stage A/B 证据引用联动（纪要作证据） | 试点前 |
| 2 | U6：全量成本归集（话轮/收敛计费入 meetings cost） | 试点后 |
| 3 | std-full 档独立门模板（lite→std 升级后拆分模板族） | 试点升级后 |
| 4 | 指标埋点三类：SOW 拍板事件 / 资深介入计时 / 422 拦截事件——补埋点后报表三类 insufficient 转 ok | P3 前 |
| 5 | 「一次通过率」retry 幂等链折算口径（当前=终态 completed 占比） | 数据积累后 |
| 6 | 翻译器 P3 全量：AI 翻译管道 + 落库 + 终审台「产物+纪要」合并视图 | P3 |
| 7 | 撤销声明的既有 run 处理策略（当前=不回溯，口径已声明） | 拍板 |
| 8 | 试点前人工联调：真实 iptables + zcode CLI 钉定 | 试点前 |
| 9 | D10 五项待蔡工拍板（S 编号映射/九卡原句/报价卡数值禁区/G3 会闸关系/审定流程） | 审定交接 |

### 下轮建议（goal-d9）

- **P3 翻译器全量启动**：`preview.ts` 输出形状已对齐 guidance 契约（severity/module 两键），接 AI 翻译管道（kimi）+ `POST /translator/translate` 落库到 guidance 草稿 + 终审台合并视图（D7 纪要回链）。
- 指标埋点三件（挂账#4）与报表三 insufficient 转实——优先 SOW 拍板事件（solution 拍板动作已有 UI 入口，埋点成本低）。
- agent_assisted 桌面化：派单详情页协同声明按钮 + 难度档位显示（服务端白名单两键已透出，桌面零阻塞）。
