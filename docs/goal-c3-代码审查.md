# goal-c3-代码审查（交付主链：projects, solutions, documents, guidance, templates, evidence, files, storage, mailing, translator）

> 循环：goal-c ｜ 轮性质：审查+修复（P1 当轮修）｜ 日期：2026-11-04 ｜ 基于树：`edb013d`（fork/main，#94）

## 1 结论一句话 + 口径数字变化

**交付主链 86 条路由隔离矩阵全绿（写面 100% can_manage/can_manage∪can_update/AI 档位收口，三类越权形态零命中）；承诺语义核对揪出 signoff 并发开闸双插缺口（CR-008，P1，当轮修）+ 报价数值防御 500 而非 400 两处不自洽（CR-010，P1，当轮修）+ G8-stop 结算联动零测试载体（CR-009，P2，当轮补测试）；T-E1/E2 证据挂接与 T-P0-1 单事务语义 12 条承诺逐条 ✓，红线 4「证据只存指针+指纹」在 evidence/mailings/documents 三处均成立。口径数字：服务端测试 +7（signoff 并发 2 + 报价守门 3 + G8-stop 2），零迁移零路由。**

## 2 审查方法与覆盖面（隔离矩阵 + 承诺核对表落报告）

### 2.1 方法

- 双引擎：`code-review`（候选缺陷 12 条走驳斥关）+ `intended-vs-implemented`（11 条意图锚逐条对照）；3 个子代理并行分包（闸/证据/signoff 深审、隔离矩阵 86 路由、意图对照），主会话逐条 E0 升级（子代理结论按 E1 入账前全部重读源码验证——含纠正子代理对 `deviation_pct` 列上界的误读：`Numeric(7,4)` 整数位 3 = 999.9999 而非 9999.9999）。
- 实际覆盖：`projects/`（routes 全文 31 路由 + gate/quote/payment/contract/task 服务层）、`solutions/`（12 路由 + signoff/export 全链）、`documents/`（17 路由 + 版本/下载/预览）、`guidance/`（10 路由）、`evidence/`（2 路由 + 幂等/不可变/反查）、`files/`（16 路由 + 分片/版本/预览）、`mailing/`、`storage/`、`templates/`、`translator/`；`agents/signoff.py` 全文 + `agents/service.py` _finalize/handoff 段 + `solutions/service.py` export 兜底段。
- **没看 & 为什么**：dispatch 三隔离与 8 态机（c6 冻结区正事，本轮只确认 G8-stop 联动调用点不越 dispatch 写路径）；documents 生成器字节路径 internals（子代理已核 `generator.py:1000` put_stream 口径，未逐行）；mailing SES 凭证管理（`docs/SES发信模块-G9.md` 独立意图文档已核，包体只存 payload_sha256 不落原文 ✓）。

### 2.2 隔离矩阵（86 路由，三类越权形态全部零命中，E0）

权限权威实现 `projects/permissions.py:20-41 project_access`（admin 全通 / leader / 成员 viewer|member）；服务层统一语义：**项目不存在=404、存在但无权限=403**（全服务一致，存在性可见=设计口径非缺陷）。

| 面 | 路由数 | 判定 | 要点 |
|---|---|---|---|
| projects（gates/quotes/payments/contracts/members/tasks/modules/gantt） | 31 | ✓ | 写面全 can_manage（成员写仅 `can_update_assigned_tasks` 本人执行字段=permissions.py:12 第三闸，设计内） |
| solutions | 12 | ✓ | 对象双重过滤（solution_id AND project_id）；signoff 闸=can_view 进门 + checkpoint.required_level 档位拍板（默认 project_manager，AI 治理档位制，设计内） |
| documents（draft/versions/download/preview/delivery-records） | 17 | ✓ | version_id 全局解析但下游按 path project_id 二次过滤（`version_service.py:1039`），残余=UUID 存在性提示≈0 |
| guidance | 10 | ✓ | 读 can_view / 写 can_manage + G3 前置闸 |
| evidence | 2 | ✓ | POST can_manage 指纹幂等 / GET can_view；不进 api_catalog 承诺 ✓ |
| files（分片/完整/版本/预览） | 16 | ✓ | 全部 can_manage 写 / can_view 读，对象均按 path project 过滤 |
| mailing / storage | 3 | ✓（平台级） | SNS 回调=签名代鉴权（TopicArn 白名单）；分片/下载=短时效签名 URL——**无 require_auth 属设计内**，不参与项目隔离 |
| templates / translator | 8 | ✓ | 行业模板=admin/project_lead 平台门；translator 草稿=个人席位资产（created_by 归集），adopt 走项目 can_manage |

三类越权形态专项：(a) 写面只 can_view——**零命中**；(b) 路径 project_id 与查询过滤不一致——**零命中**（唯一 version_id 全局解析面已被下游过滤收口）；(c) 列表按 user 而非项目——GET /projects 非 admin 强制 leader∪member 过滤（正面实现）。

### 2.3 承诺语义核对表（T-P0-1 / T-E1 / T-E2，子代理报告 + 主会话 E0 复核）

**T-P0-1（signoff 死锁修复）**：唯一开闸入口 ✓（全仓 grep 仅 `signoff.py` 一处构造）；单事务内幂等 ✓；「先提交再 409」两段事务 ✓；remedy/checkpoint_id ✓；SolutionServiceError detail ✓；**并发跨事务幂等 ✗ → CR-008（当轮修）**。

**T-E1/E2（一等证据）**：指纹幂等+不可变 ✓（`evidence/service.py:126-147` + 唯一约束）；只存指针+sha256 无内容列 ✓；清单项挂 evidence_id 零 DDL 旧行读时合并 ✓；POST can_manage/GET can_view ✓；`referenced_by=gate:Gx` 反查 ✓（task/bridge origin 无反查面=已知边界，非缺陷）；不进 api_catalog ✓（测试钉住）。

**金额精度**（全链路 Decimal + Numeric 列，序列化转 float 仅展示层）：payment_service 汇总先 Decimal 域求和 ✓；contract_service 无金额字段（纯指针）N/A；quote_service **cash_cost 无上限 + deviation 先落库后 400 检查 → CR-010（当轮修）**；公式/系数封闭集（INTEGRATION/DATA/COMPLIANCE/MARGIN/DEFAULT_BUFFER）与 docstring 声称完全一致（红线区 ✓，仅 L81 注释「两档」与 3 取值措辞矛盾=cosmetic 不入账）。

## 3 发现清单（台账增删摘要）

| 编号 | 级别 | 状态 | 摘要 |
|---|---|---|---|
| CR-008 | P1 | **fixed（当轮修，随本轮 PR）** | signoff「同方案至多一个 pending」无并发防线：SELECT-then-INSERT 无行锁无 UNIQUE，双 run 并发 _finalize 可双插 pending → 加事务级 advisory lock（fde_quote_first_order 先例同构） |
| CR-009 | P2 | **fixed（当轮补测试）** | G8-stop 结算联动 `flag_g8_stop_settlement` 零测试载体（tests 全仓 grep 命中 0）→ 补 2 用例 |
| CR-010 | P1 | **fixed（当轮修）** | quote 数值防御不自洽：calibrate deviation 先 flush 后 400（Numeric(7,4)=999.9999 可被 10⁵ 倍偏差击穿→500）、create 侧 cash_cost 无 MAX → 双前置 400 闸 + 3 用例 |
| CR-011 | P3 | open（登记不修） | mailing/translator/guidance 三包意图锚分散 4 份文档，V3 主报告无集中裁决行 |

**驳回 6 项**（台账「驳回/观察记录」）：signoff L1 经 export 兜底软链偏离「handoff 后开闸」（语义偏离不破坏安全边界，闸本身未放宽）；已 accepted 清单项重提交重置 claimed（failed 重提=事实变了，pass 仍强制全 accepted）；并发证据登记输家无事件（幂等语义可接受）；rejected 后「曾 approved」永久放行（审计留痕设计，T-P0-1 拍板原文）；update_payment 只传 received_at 金额沿用计划额（docstring 自注「沿用计划额」=文档化行为）；handoff 档 can_view（goal-d9 既有语义，开闸≠拍板）。

## 4 修复记录

**CR-008 + CR-010 + CR-009 → 单 PR**（fix/goal-c3-signoff-and-quote-guards → fork/main，squash）：

- **CR-008**：`agents/signoff.py::ensure_pending_signoff` 入口加 `SELECT pg_advisory_xact_lock(hashtext('fde_signoff:' || :solution_id))`（零 DDL；同仓 `quote_service.py:592` fde_quote_first_order 与 `bridge/sync.py` fde_bridge_apply 先例同构；锁随事务提交/回滚释放）。三处调用点（_finalize/handoff/export 兜底）全在显式事务内，自动获益。
- **CR-010**：`quote_service` 双前置 400 闸——create 侧 `cash_cost > MAX_INPUT_MONEY` 拒（同 final_amount 口径）；calibrate 侧 `abs(deviation) > 999.9999` 在 flush 前拒（对齐既有 99.99 calibrated 闸语义）。零迁移零路由。
- **CR-009**：`test_gates_api.py` +2（G8 stop 有尾款行打 `settlement_reason='g8_stop'`+事件+note 追加；无尾款行只留事件 flagged=false）。
- 测试 +7：`test_signoff_concurrency.py`（双线程真实 PG 并发开闸恒单行 + 串行软链幂等钉）/ `test_quote_numerical_guards.py`（cash_cost 上限 400 + 边界内放行 / deviation 超限 400 + 上界内回校对照 / 两闸消息面钉住防既有 99.99 闸冒充）。
- **变异验证**：① 删 advisory lock → 并发用例红（双插两不同 checkpoint.id）→ 还原 → 绿；② 删双 400 闸 → 2 守门用例红 → 还原 → 16/16 绿零残留。
- 本地前置门：ruff 绿；`scripts/check-python-types.py` 基线不变（279）；signoff/solution/gates/quote 五文件簇 66/66 绿。

## 5 未修与移交

- **CR-011（P3）**：三包意图锚分散——文档轮顺手（V3 主报告 §13/§20 补指针行，同 CR-003 类）。
- **CR-006 遗留**（c2）：DSH 记账面 c8 取证，不动。
- **观察级（不占编号）**：① 文档 version_id 全局解析的 UUID 存在性提示≈0（维持现状）；② delivery-records 双重门角色/成员码型不对称（docstring 明载意图，只收紧不放宽）；③ HOURLY_RATES 注释「两档」三取值措辞矛盾（cosmetic，不入账）；④ task/bridge 证据无 referenced_by 反查面（service docstring 自述边界）。
- **BLOCKED-EXTERNAL**：无。

## 6 教训（同步沉淀执行者记忆）

1. **「承诺的并发安全」要拿真实 PG 并发验**：signoff docstring 的「同方案至多一个 pending」在单事务内成立，跨事务靠的是……什么都没靠（无锁无 UNIQUE）——并发承诺的验证载体必须是双连接 barrier 同步（test_quote_first_order_concurrency 的既有模式），读代码读不出来。advisory lock 是零 DDL 的并发串行化惯用件：先例 `fde_quote_first_order`/`fde_bridge_apply`，新并发闸直接 `hashtext('<域>:' || 资源键)` 同构。
2. **「先落库后检查」的顺序错=500 而非 400**：Numeric 列上界是 DB 约束，业务 400 守卫必须在 flush 之前跑；审查金额代码时专盯「赋值语句与校验语句的相对顺序」——calibrated 的 99.99 闸在 deviation 赋值之后，对 deviation 无效。
3. **测试写「id 断言」要 flush 后读**：Python 侧 `default=` 生成的 UUID 在 flush 前是 None——并发用例里「两线程取回同一 id」断言必须先 flush 再读，否则把测试写法缺陷误判为产品缺陷。
4. **子代理报的列上界要重算**：`Numeric(7,4)` 可存 999.9999（整数位 3）而非 9999.9999——子代理 E0 引文也要按 DDL 语义复核一遍再定触发数字。

## 7 门禁四件套（本轮收口）

（全量 server 套件后台运行中，结果回填此处：`npm run typecheck` / `npm run test:server` / `npm run test:desktop` / `python scripts/check-python-types.py`）
