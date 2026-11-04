# goal-c6-代码审查（派单/桥/工作台/指标/模块：dispatch, bridge, workbench, metrics, modules）

> 循环：goal-c ｜ 轮性质：**纯登记轮**（P0/P1 当轮修=0；冻结区审不改）｜ 日期：2026-11-05 ｜ 基于树：`2dcc61b`（fork/main，#106）｜ 施工面：隔离 worktree `D:/test/fde-wt-c67`（分支 fix/goal-c6-c7-register）

## 1 结论一句话 + 口径数字变化

**冻结区（8 态机 TRANSITIONS / package_access 白名单 schema / match_breakdown schema / 三隔离基线 / api_catalog 94 ENTRIES）全域零命中——8 态机 6 动作 × 状态全表写点仅 `_assert_transition` 单点、三隔离 grep 空、quote/payment 只读复算面走白名单序列化不泄漏；冻结区外揪出 2 P2 + 5 P3 登记不修（撮合规则版本激活零生产调用方 → 自动撮合永久降级态 CR-027；累计预扣 UTC 年+调用时月双实算误差 CR-028；桥 captured_at 单向采信宿主钟 CR-029；4h 热路径全表水合+N+1 CR-030；演练 run 未排除出指标面 CR-031；L0 对账草稿无指针/自引用助手并入观察项；meeting 工具面 initiator 纵深缺口并入驳回记录）；convene-billing「覆写」候选经 E0 逐路径核实**驳回**（同事务内递增、工具面不入 adapter 循环）。零代码改动（纯登记），口径数字不变。**

## 2 审查方法与覆盖面

### 2.1 方法

- 双引擎：`code-review`（冻结区单点写面 + 派单/桥/指标三子代理分审）+ `intended-vs-implemented`（§11.1 降级态前置 / 累计预扣 docstring / 桥「4h+360min 断连可见」不变量逐条对照）。
- 主会话对子代理 E1 结论逐条 E0 升级：grep 生产调用方（`activate_due_versions` 零命中）、读 settlements 138/145 行、读 metrics 四个 AgentRun 查询——**并纠正 1 处子代理夸大**（C6-01 初报为「claim 闸也死」，实读 cities.py:139 认 published 即可，仅撮合面死、claim 面活，降为 P2 登记）。
- **冻结区纪律**：dispatch 8 态机 / package_access / match_breakdown / 三隔离 / api_catalog 内容=只审（确认无违规写入）不改、不报缺陷。
- 实际覆盖：`dispatch/`（rules/settlements/matching/packages/maintenance/disputes/cities/profiles/offer_service）、`bridge/`（sync/runner/routes/evidence 挂接）、`metrics/service.py`（AgentRun 指标面）、`modules/`（catalog 同步）、`meetings/`（convene 计费三路径+工具面）。
- **没看 & 为什么**：桌面桥页立即采集按钮（c7 桌面轮）；dispatch 派单引擎 goal-r 线（施工准绳=外部设计文档，非 c6 代码审计面）。

### 2.2 冻结区审计（零命中，E0）

| 冻结项 | 审计面 | 判定 |
|---|---|---|
| 8 态机 TRANSITIONS（packages.py:39-52） | 全 dispatch 写 `dispatch_status` 点 | 仅 `_assert_transition`（:152-160）单点；withdraw 有 live-offer 守卫（:358-365）✓ |
| package_access 白名单 schema（models.py:202-234） | 序列化面 | routes 走 `serialize_package_whitelist`（routes.py:58-61）不透字段 ✓ |
| match_breakdown JSON（:194-196） | 写点 | matching.py:349-357 / offer_service.py:115,188 同构写 ✓ |
| 三隔离（不 join quotes/payments/contracts 裸 session.query / 不 __dict__） | grep 全 dispatch/ | `session.query` 零命中、`__dict__` 零命中；profiles.py:80-135 join Quote/Payment **只读复算判据**（§3.3 证据核验面，非序列化泄漏）✓ |
| api_catalog 94 ENTRIES | meetings 面 | `meetings.create` 有意缺席（solutions/service.py:322 人工拍板面不编目）=有意设计 ✓ |

## 3 发现清单（台账增删摘要）

| 编号 | 级别 | 状态 | 摘要 |
|---|---|---|---|
| CR-027 | P2 | open（登记） | 规则版本激活 `activate_due_versions` 零生产调用方 → 自动撮合永久 422 降级态（claim 闸认 published 未死） |
| CR-028 | P2 | open（登记，B-③ 口径区） | 累计预扣 UTC 年 + 调用时月（G8 回填多算一档减除少扣税） |
| CR-029 | P3 | open（登记） | 桥 `captured_at` 单向采信宿主钟（NTP 前漂/伪造遮「断连」） |
| CR-030 | P3 | open（登记） | 4h 热路径全表 `select(Project)` + `_city_order_rank` N+1（性能卫生） |
| CR-031 | P3 | open（登记） | 演练 run 未排除出指标中位数/降级率/一次通过率（与 pilot 闸面口径不齐） |
| （观察） | — | 驳回 | C6-06 convene-billing「覆写」候选 dismissed（同事务递增+工具面不入 adapter 循环） |
| （观察） | P3 | 驳回记录 | C6-07 `meeting_get_minutes` initiator 纵深缺口（工具面零生产路由，不可达） |
| （观察） | P3 | 驳回记录 | C6-08 L0 对账草稿无 `l0_report_source_uri` 指针（草稿=人裁决，source_uri 可空） |

## 4 修复记录

**纯登记轮，零代码改动**（冻结区审不改 + P2/P3 登记不修纪律）。

## 5 未修与移交

- **CR-027（P2）**：激活接线=备案开闸轮（B-① 名单≠开闸同源），归备案/月度 job 轮。
- **CR-028（P2）**：税率口径=B-③ 法务区，口径拍板时一并修（年过滤改自然年、月份集用行 `accepted_at.month`）。
- **CR-029~031（P3）**：桥钟 sanity / 热路径 3 列 select / 指标面加 `notlike("rehearsal:%")`，各归后续工程轮。
- **BLOCKED-EXTERNAL**：CR-028 待 2025-16 公告口径 + 律师意见（B-①/B-③）。

## 6 教训（同步沉淀执行者记忆）

1. **冻结区先划再审**：本轮 8 态机/白名单/三隔离/api_catalog 五条先逐条列「单点写面/序列化面/grep 面」再放行，子代理才没把「合规的只读复算 join」（profiles 判据面）误报成泄漏——冻结区审计的价值=**证明清白**不是找茬。
2. **「降级态前置」要数它有没有人激活**：§11.1 声明「自动撮合要求 published/active 规则版本」，但 `published→active` 唯一写点 `activate_due_versions` 全仓生产零调用方——**声明了状态机没接电**的功能面=永久降级态，不是「备案未定」的临时态；审计意图锚时追问「谁把状态推过去」。

## 7 门禁四件套（本轮收口）

- `npm run typecheck` / `test:server` / `test:desktop` / `check-python-types.py`：本轮**零代码改动**（纯台账+报告），四 job 以 CI 兜底（c5 轮全量 1868 为基线，c6 无增量用例）。

**注**：c6 施工面=登记轮，只动 `docs/`（台账+本报告），无 server/desktop 代码路径。

## 8 后记（c8 轮回填）

CR-028 待 B-③ 口径；CR-027 待备案开闸；CR-029~031 挂后续工程轮；C6-06/07/08 驳回/观察不入编号。
