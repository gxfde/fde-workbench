# Agent Autoloop 借鉴意见 · 多专家深度评审报告（party mode）

- **评审日期**：2026-11-04
- **评审方式**：5 位角色专家（架构师 / 工程效能 / 代码质量 / 产品需求匹配 / 风险合规）独立评审 → 汇总裁决
- **证据基础**：全部结论基于本地一手证据包（`D:\test\fde-workbench\.workbuddy\review-agent-autoloop\`，32 份仓库原文 + 我方源码实测），未采信任何二手转述。证据不足处显式标注。
- **过程说明**：原计划 5 个并行子代理独立评审，均因 Token Plan 用量上限（429）失败；改由主会话逐一以五视角完成。各视角的评审纪律（只依据证据、引文件行号、独立结论）保持不变。
- **上游评审对象**：`KKKKhazix/agent-autoloop`（MIT，v1.0.0，2026-11-03）

---

## 0. 整体结论（先看这里）

1. **九条借鉴意见中，5 条采纳/有条件采纳后即可进入实施**：A3（跳数熔断）、A7（回执写错不重做）、A2 剩余部分（审批退避提醒 + SLA 统计）、A8（purity 架构测试）、A9（审查不执行被审代码立规）。
2. **A1（回执 DSL）有条件采纳、分三期**：一期只上 `ask` + `later`（天然落在我方任务中心，闸门现成）；`notice` 二期；`resolve` / `events` 三期且必须先过风险闸（见风险专家意见）。
3. **两条被降级为「暂缓/不做」**：A5 的「事项聚合层」（无业务承载）、A6 的「单 timer 零轮询」（Flask 多 worker 架构下是伪需求——只搬「统一到期计算」思想）。
4. **五视角一致认定**：autoloop 的价值在**协议语义、状态机不变量、测试组织方式**，不在代码本身。照抄代码被四位专家明确反对（中文口语注释、自造术语、单人 bus factor、单日 5 commits 的演进速度）。
5. **我方存量优势盘点（勿被「借鉴」误导成退步）**：沙箱四硬边界 + egress deny/allowlist、审批密码确认 + 敏感键扫描 + 64KB 上限、证据指纹不可变表、OperationEvent 脱敏审计、api_actions sha256 幂等、gitleaks + pseudonymization CI、项目级 RBAC——**这七项 autoloop 一个都没有**（其 SECURITY.md 自认「要隔离密钥，用单独的系统账号或容器」）。

---

## 1. 专家一：系统架构师

### 总体判断
autoloop 的架构价值集中在三处：内核纯度约束（purity.test.ts）、hops 熔断语义、回执协议。事件溯源存储模型不可搬——我方是 SQL 权威库 + 31 个 Alembic 迁移，「从日志重放重建」与我方迁移体系正面冲突。我方「内核↔能力面」的依赖方向问题（`workflows/definition_service.py:26-32` 顶层 import `control.*`，`control/service.py:663` 靠函数内延迟导入规避环）恰好是 A8 需要治的病，有实证。

### 逐条评审

| 意见 | 结论 | 核心依据 |
|---|---|---|
| A1 回执 DSL | **有条件采纳** | `protocol/validate.ts` 的 `only()` 字段白名单 + 容量上限是协议稳定性的关键；`kernel_decide.ts:351-370 applyReceipt` 是消费端。前置：动作落点必须映射到我方既有闸（ask→任务中心审批行），`events` 动作必须同构 `emits` 白名单（`kernel_decide.ts:337-340`：规则没写就不能发，否则 rejected） |
| A2 挂起零消耗 | **有条件采纳（语义已达成 80%）** | 我方 `waiting_approval` 非终态、handler 正常返回（job 释放）、拍板重投 = 零消耗已实现。真正缺口：①审批提醒退避序列（`kernel_decide.ts:26` RESEND_AT）②跨 run 会话续接——**不采纳**，我方 Agent 是沙箱一次性 CLI 调用，无跨 run 会话概念，强做需 CLI 原生支持（证据不足：zcode 是否支持续接未核实） |
| A3 跳数熔断 | **采纳** | `kernel_decide.ts:30 MAX_HOPS=8`、`:172-181` tooDeep 分支（记录+不派发+once 通知）、`:336` 回执事件 hops+1、`:391-392` 卡片回答事件**继承 hops 不清零**、`:446` timer.due 同样继承。语义完整可直接译为我方 `workflow_runs.hops` |
| A4 指令数据分离 | **有条件采纳** | 实现手段比想象简单：`parseEvent` 的 FIELDS 白名单**隐式拒绝**未知字段（含 cwd/agent/access），subject 限标识符字符集、link 限 ASCII。我方 `_write_workspace` 已有文件通道，缺的是渲染层强制 + evidence 登记 |
| A5 状态可追 | **有条件采纳（砍半）** | 「规则版本快照」我方**已有**——`workflow_runs` 固定 `(definition_id, definition_version)` 即 autoloop 的 `runs.rules_version`（`kernel_schema.sql` runs 表）。缺的只是 trace 聚合视图。「事项」聚合层：缺失属实，但事件溯源模型下事项=lane 归组是内核概念，搬到 SQL 权威库需新表+新状态机，**暂缓** |
| A6 单一到期调度 | **有条件采纳（只搬思想）** | `kernel_due.ts` 单函数算全部到期 + 外壳单 timer 是**单进程 SQLite 的产物**；我方 Flask 多 worker + background_jobs 队列下「单 timer」不成立。可搬：「统一到期计算函数」+ 审批过期从惰性改主动扫 |
| A7 回执写错不重做 | **采纳** | `kernel_decide.ts:344-348 finish()` 幂等设计精妙：同 token + 同结果 hash → duplicate 返回同 rejected；不同 hash → Conflict。`worker_contract.ts:71-73 repairPrompt`（"你做过的事不要重做……只把最后一条消息按格式重写一遍"）+ `worker_worker.ts:36 REPAIRS=2` + `discardReceipt`（保留原结论+notice）三层兜底 |
| A8 插件边界 | **采纳（纪律层）** | `tests_purity.test.ts` 六条测试全是正则静态断言，直接可译为 pytest。我方实证：`definition_service` 顶层 import control 三模块 + `control/service.py:663` 延迟导入规避环——需要 purity 测试锁方向的证据 |
| A9 审查不执行被审代码 | **采纳** | `plugins_delivery_delivery.ts:110`（只处理本仓库分支→main）、`:119-121`（main 前进→重新同步审查）、`:151`（合并响应丢失→读回确认）、SECURITY.md「PR 只下载 Git 对象，生成文字差异，不检出、不运行 PR 的代码」——完整的事故清单，先立规成本≈0 |

### 架构师裁决建议（优先级排序）
**A3 > A7 > A9 > A8 > A1（一期）> A4 > A2 剩余 > A6 > A5**。
架构上根本不成立的两条：①事件溯源存储替换（与 31 个迁移的权威库正面冲突）；②「单 timer 零轮询」（多 worker 架构伪需求）。

---

## 2. 专家二：工程效能负责人

### 总体判断
逐项核对后，**A2 的核心收益我方已经拿到**（waiting_approval 释放 job），不要重复建设。autoloop delivery 插件多出来的三件事（Ship+健康版本核对、合并响应读回、等待期新标签阻止合并）我方暂无自动部署面对象，登记不动。最有性价比的是 A3（1 迁移+1 判断+1 测试）和 purity 架构测试（pytest 单文件）。

### 逐条评审

| 意见 | 结论 | 核心依据 |
|---|---|---|
| A1 | **有条件采纳** | DX 成本：所有 Skill/提示词加 JSON 输出约束，首轮成功率可能降（推测，无数据）；autoloop 靠 repair 循环兜底（REPAIRS=2），我方引入必须同步引入 repair/降级路径，否则「回执失败」直接变「业务失败」。一期只做 ask/later 可复用任务中心，增量最小 |
| A2 | **采纳剩余部分** | 核对结论：`executor.py` 剩余节点全 waiting → run=waiting_approval，handler 正常返回，background_jobs 释放——**零消耗已达成**。增量=退避提醒（RESEND_AT 模式）+ 挂起时长 SLA 统计。会话续接不做 |
| A3 | **采纳** | 成本量级：1 列 + 执行器入口 1 处判断 + 1 个 pytest 用例。最便宜的结构性保障 |
| A4 | **采纳** | 我方已有 `_write_workspace`（文件通道）+ `evidence`（指纹登记）+ `_redact_changes`（脱敏）；缺的是 `_render_context` 渲染层断言与登记自动化。成本中 |
| A5 | **部分采纳** | trace 聚合视图：我方数据已齐（definition_version + workflow_node_runs + automation_approvals + operation_events + evidence），一次 API 聚合即可，成本中。规则版本快照已有。事项层暂缓 |
| A6 | **部分采纳** | 统一到期函数：把我方分散的 cron（scheduler.py）/ 重试 not_before / worker 租约（adapter 超时）/ 审批过期（惰性）收口为一个计算函数 + 审批超时主动扫。成本中。「单 timer」不搬 |
| A7 | **采纳语义** | 落点：agents 输出解析处（非 workflow 层）。repair 循环按 CLI 能力降级——autoloop 自己也是这么做的（`worker_worker.ts:319`：`adapter.link` 不支持就 discardReceipt 保留原结论）。我方 zcode CLI 会话能力证据不足，降级路径反而是主路径 |
| A8 | **采纳** | purity 架构测试：pytest 单文件（遍历 workflows/ 源码正则断言「不 import control.service/routes」），成本极低。Agent 接入成本：我方 adapter 抽象已达标，无增量工作 |
| A9 | **采纳** | 当前我方无 AI 审查执行面，立规（AGENTS.md 一条红线 + 未来 CI 断言）成本≈0，收益是防未来 |

### 专项发现
1. **交付流水线对比**：我方 CI（4 job + 分支保护）已覆盖 delivery 插件的审查/检查/合并主体；多出来的「健康版本核实」思想值得登记，用于未来桌面端自动更新通道。
2. **测试效能差距**：sim 三件套（20 万步种子模拟/强杀 1000/变异检查）对我方有价值但**前置条件是先把 executor 决策逻辑抽纯函数**（现在耦合 SQLAlchemy session），估计 2-3 周重构 + 框架搭建——三期再做。`ci-scope.sh` 按改动分流思想可低成本抄（GitHub Actions paths filter）。
3. **成本治理**：挂起零消耗在我方已达成，无需估算 Token 节省；真正可量化的是「审批挂起时长分布」——建议随退避提醒一起做。

---

## 3. 专家三：代码质量专家

### 总体判断
`kernel_decide.ts`（541 行）质量高于平均：Draft + `view.fork()` 的「视图+待提交改动」写法干净，常量集中（RESEND_AT/MAX_HOPS/RESEND_WINDOW 都在文件头部），`HANDLERS` 派发可扩展。但要破除「1651 行内核」的神话：`worker_worker.ts` 的 repairs/triedFresh/cancel 多状态交错可读性一般，`worker_contract.ts` 边界处理堆叠。投影查询是 O(n) 扫描靠索引弥补（110 万条事实重建 43.1s 是明码标价的上限）。**抄机制与测试思想，不抄代码。**

### 逐条评审

| 意见 | 结论 | 核心依据 |
|---|---|---|
| A1 | **有条件采纳** | 双重校验（schema.json 20KB + validate.ts 手工）在我方**只选一层**：Pydantic/marshal + 「未知字段拒绝」（`only()` 等价）。容量上限数值不照抄，对齐我方既有 64KB 审批上限（`executor.py:80 _APPROVAL_PAYLOAD_LIMIT_BYTES`）。落点：新建 `agents/receipt.py`，**别塞进已 1188 行的 service.py** |
| A2 | **采纳剩余**（同效能意见） | `waiting_approval 不盖 finished_at`（executor.py:778）的诚实语义已经是好代码，保持 |
| A3 | **采纳** | 硬编码 MAX_HOPS=8 先硬后配置化是对的；必须配测试（autoloop 有 tests/hops.test.ts——证据包未含，**证据不足**，我方自己写） |
| A4 | **有条件采纳** | 白名单隐式拒绝（`protocol_validate.ts:52-54`：`for name of Object.keys(given) if (!FIELDS.includes(name)) throw`）比显式黑名单优雅，我方入站清洗照此模式 |
| A5 | **部分采纳** | 「测试即规格」实践可低成本搬：每个测试文件头写「防的失败方式」（purity.test.ts 每个 test 上方都有注释）——采纳为我方 pytest 约定。独立重放 oracle（`sim_invariants.ts replay()` 不用生产写路径）前提是事件溯源，我方替代方案=状态机不变量断言（对 run+node 状态组合断言），不必改存储模型 |
| A6 | **部分采纳** | `deadlines()` 纯函数计算是好范式；我方 `_cron_values` 自研解析已有测试，统一入口是重构非新增 |
| A7 | **采纳** | `discardReceipt` 的「保留原结论 + 通知回执未生效」比「失败重跑」诚实——建议作为设计原则写进我方 AGENTS.md。`finish()` 的 token+hash 幂等与我方 api_actions sha256 同构，迁移路径清晰 |
| A8 | **采纳** | purity 测试是「架构即测试」的最佳实践样本；注意我方「内核」边界要自己定义（建议：workflows/ 不 import control 的 service/routes 层，models 层单议），不能照搬「零 import」 |
| A9 | **采纳** | AGENTS.md 的「必须保住的事故逻辑」清单（main 设置、分支改动才审、冲突保留、草稿不放行、main 变化不合并、合并响应读回、Ship+健康同验、交付不倒退）值得整段翻译进我方交付规范 |

### 专项发现
1. **我方 executor.py 现状**：1390 行约 40 函数，`_dispatch_call/skill/agent/human_approval` 已按节点类型分离（结构良好）。A3 入口检查不改结构；A1 解析层独立模块化即可。总体判断：引入采纳项会让代码**更清晰**（语义显式化），不会更混乱。
2. **腐化风险**：上游单日 5 commits、单人维护、中文口语注释与自造术语（「中台」「批奏折」）、约定大量是「禁止型」表述——照抄代码风格的长期维护代价为负。界线：协议语义/不变量/测试组织方式可抄；代码、常量数值、目录结构不抄。
3. **质量警戒**：A1 的 DSL 必须「未知字段拒绝」，否则一年后字段漂移无人能清——这是 autoloop 用 `only()` 守住的第一道线。

---

## 4. 专家四：产品负责人

### 总体判断
autoloop 的 7 个场景模板全是**个人效率型**（早报/GitHub Issue/告警排查/反馈处理/网站巡检/飞书周报/PR 交付）；我方是 **B2B 客户交付型**（门禁 G1-G9、报价收款合同、集成桥、派单引擎、试点报告）。直接对得上的只有：告警排查≈集成桥采集异常处理；网站巡检≈h2-home.com 独立站（工作台之外）；PR 交付≈未来交付包自动验证（当前无对象）。**价值判断优先于技术优雅度。**

### 逐条评审（按减人力排序）

| 意见 | 结论 | 产品理由 |
|---|---|---|
| A2 剩余 | **采纳（最高产品价值）** | 「客户交付卡在等拍板→忘了拍板」是真实高频痛点；退避提醒 + SLA 统计直接减少人工跟进 |
| A3 | **采纳** | 一次额度失控事故的损失 > 开发成本；且熔断是可解释失败，客诉时可答清 |
| A7 | **采纳** | 重复发信/重复部署对客户是事故级；「业务成功+结论无效」语义是防事故保险 |
| A1 | **有条件采纳（基建性质）** | 人工介入场景扩展的基建，前期只有 ask/later 有用户；notice/resolve/events 等有真实场景再上 |
| A4 | **采纳（防御性）** | 客户资料合规是红线，出一次事故就没有下一次 |
| A5 trace | **有条件采纳** | 客诉/复盘时快速定位，低频高价值；事项层暂缓——**我方当前交付是「一次 run 出一个交付物」，无持续巡检业务，做了没用户** |
| A6 | **部分采纳** | 审批超时主动暴露有感知价值；统一到期函数是内部质量，用户无感 |
| A8/A9 | **采纳（纪律）** | 无直接人力节省，但防未来事故 |

### 反面意见（暂缓/不做清单）
1. **「事项」聚合层暂缓**——无业务承载，等「持续巡检」类需求出现。
2. **跨 run 会话续接不做**——客户交付不需要 Agent 跨天续聊。
3. **sim 三件套暂缓**——当前 pytest + 4 CI 已挡回归；没有真实故障史之前投入产出不成立。
4. **单 timer 零轮询不做**——多 worker 架构下的伪需求。

### 路线裁决
- 只能做一条：**A3**（成本最低、防真事故）。
- 只能做两条：**+A7**。
- 需补充的业务信息：每月交付 run 数量、审批平均等待时长、是否发生过重复交付/额度失控事故、客户交付时效 SLA 承诺。

---

## 5. 专家五：风险与合规专家

### 总体判断
autoloop 的注入防御是**诚实但有边界的**：SECURITY.md 明说「这挡不住所有提示注入：Agent 还是会读到别人写的话。所以默认权限是 edit，给 full 之前想清楚」。我方有七项它没有的控制（见 §0.5），借鉴的正确姿势是**把它的好语义装进我方更强的控制面**，而不是引入它的弱控制。A1 的 `resolve`/`events` 两个动作是真实攻击面，必须带闸上线。

### 逐条评审

| 意见 | 结论 | 风险依据 |
|---|---|---|
| A1 | **有条件采纳（resolve/events 必须带闸）** | 攻击面逐条：(a) resolve≤50 批量关审批行可抹待办痕迹→我方映射必须 can_manage 校验 + OperationEvent 留痕 + 限单回执数量；(b) events 伪造触发绕审批→autoloop 用 emits 白名单（`kernel_decide.ts:337-340`），我方必须同构：事件→新 run 走 capability 闸（definition 期白名单 + `executor.py:1044` 实时校验已具备）+ hops 继承；(c) later 无限链→hops 不清零 + MAX_HOPS 兜住，我方 later 落地必须继承 hops；(d) notice 外发→autoloop「通道接收人属于整个中台，规则不能单独挑收件人」，我方收件人必须由 RBAC（项目成员）决定，回执不得指定收件人 |
| A2 | **部分采纳（卡片链接通道不采纳）** | 已核实撤回「token 明文」疑虑：查找走 `card_hash` 哈希索引（`host_runtime.ts:41,68,181`），token 由 master.key HMAC 派生，SECURITY.md「只保存 token 的哈希」准确。但「持有即授权 7 天」在我方不可接受——我方审批=任务中心+密码确认（`TaskCenterPage.tsx:212-220` decideApproval 强制 password），权限模型更强。**人工介入落点保持任务中心** |
| A3 | **采纳（须配可解释性）** | 熔断是成本控制非安全控制；必须落 OperationEvent（event_type=`workflow_hops_exceeded`）+ 通知项目负责人——证据链我方已有表，零新表 |
| A4 | **采纳（须钉死文件落点）** | 我方能做得更强：sandbox egress deny + 工具白名单 deny-降级 + `_redact_changes` 脱敏都是现成加固位。红线约束：外部文字文件必须落项目工作目录或 sandbox workspace，**不落仓库**；登记必须走 evidence 指纹（指针+sha256），不落内容 |
| A5 | **部分采纳（须 project-scoped）** | trace 视图必须 can_view + 不跨项目。若实现为「上下文快照入库」→ **触犯我方「证据原件不进数据库」红线**，实现必须是指针+指纹 |
| A6 | **采纳** | 无新风险；审批超时主动扫反而消除「过期卡片静默悬挂」 |
| A7 | **采纳** | 「保留原结论+人工通知」的降级路径比我方现状（整轮失败可重跑→重复交付风险）更安全 |
| A8 | **有条件采纳** | purity 测试无风险；但**不要引入**「git 地址即装」的插件通道进服务端——`SECURITY.md` 明文「加载入口就会执行它」，企业环境是供应链面；我方 extensions_service 已有此面（既有风险，非新增，不扩大） |
| A9 | **采纳** | 「审查不执行被审代码」直接堵死「AI 审查执行了客户提供的脚本」的攻击面；我方 CI 在 Ubuntu 跑、gitleaks 在线，立规成本≈0 |

### 我方优势盘点（≥5，防退步清单）
1. 沙箱四硬边界 + egress deny 默认/allowlist 档（`agents/sandbox.py`，测试逐条锁定）——autoloop 无沙箱。
2. 审批密码确认 + 敏感键扫描（`contains_sensitive_argument`）+ 64KB 上限 + risk_level（`executor.py:1094-1100`）。
3. 证据指纹不可变表（`ProjectEvidence` 唯一约束 (project, source_uri, sha256)）。
4. OperationEvent 脱敏审计（`projects/events.py:100-103` redact authorization/bearer/sessionkey/accesskey）。
5. api_actions sha256 幂等键。
6. gitleaks + pseudonymization 双 CI 闸。
7. 项目级 RBAC（can_manage/can_view）。
（autoloop 对应项：全部没有，其权限模型是 read/edit/full 三档 + 系统账号隔离建议。）

### 风险严重度排序
**高**：A1 的 resolve/events 动作未带闸不得上线。
**中**：A4 文件落点纪律（不落仓库）；A3 熔断事件必须留痕。
**低**：A6；A8 的 purity 测试本身。

---

## 6. 汇总：一致意见与分歧裁决

### 一致意见（4/5 或 5/5）
| 项 | 一致结论 |
|---|---|
| A3 | 采纳（5/5）。1 迁移 + 1 判断 + 1 测试 + 熔断留痕 |
| A7 语义 | 采纳（5/5）。「业务成功+回执无效」独立终态 + 保留原结论降级路径 |
| A9 | 采纳（5/5）。立规成本≈0 |
| A8 purity 测试 | 采纳（5/5）。pytest 单文件；「git 即装」通道不引入（风险专家加码） |
| A2 核心语义 | 已达成（5/5 确认），剩余=退避提醒+SLA |
| 照抄代码 | 反对（4/5 明确）。只抄机制/不变量/测试组织 |

### 分歧点与裁决
| # | 分歧 | 各方立场 | 裁决 | 理由 |
|---|---|---|---|---|
| 1 | A1 上线范围 | 架构/效能/质量=有条件采纳；产品=基建性质前期用不上；风险=resolve/events 必须带闸 | **分三期**：一期 ask+later（落任务中心，闸现成）；二期 notice；三期 resolve+events（先过风险闸：can_manage + 留痕 + emits 同构白名单） | 闸成本决定节奏；任务中心+密码确认是现成最强闸 |
| 2 | A2 会话续接 | 架构=不采纳；产品=暂缓；效能=证据不足 | **不做** | 我方 Agent 是沙箱一次性调用；强做依赖 CLI 会话能力（zcode 未核实），收益场景不存在 |
| 3 | A5 事项层 | 架构=缺失属实；产品=暂缓（无业务） | **暂缓，登记台账** | 无用户场景；等「持续巡检」需求出现 |
| 4 | A6 单 timer | 效能=不适用多 worker；架构=思想可搬 | **只搬统一到期计算 + 审批主动超时** | 「单 timer」是单进程 SQLite 产物，Flask 多 worker 下伪需求 |
| 5 | A7 repair 循环 | 质量/风险=采纳；效能=zcode 会话能力证据不足 | **采纳语义，repair 按 CLI 能力降级** | autoloop 自身的降级路径（discardReceipt）本来就是主路径备选；我方直接以「保留原结论+通知」为默认，repair 为增强 |

### 逐条评审总表

| 意见项 | 评审意见 | 优先级 | 影响范围 | 建议动作 |
|---|---|---|---|---|
| A3 跳数熔断 | **采纳** | **高** | `workflows/models.py`（hops 列）+ `executor.py`（入口检查）+ 1 迁移 + 1 测试 | 一期先行。事件驱动入口 hops+1（拍板重投/定时复查继承不清零）；>8 → failed(`hops_exceeded`) + OperationEvent + 项目通知 |
| A7 回执写错不重做 | **采纳** | **高** | `agents/service.py` 输出解析处 + AGENTS.md 设计原则 | 「业务成功+结论解析失败」独立终态；默认降级=保留原结论+通知；repair 为增强（CLI 支持时） |
| A2 剩余（退避+SLA） | **采纳** | **高** | 审批提醒任务 + 桌面任务中心徽标 | RESEND_AT 式退避（如 0/10/30/120/480 分钟）；挂起时长统计进 run 详情 |
| A8 purity 架构测试 | **采纳** | **高** | 新 pytest 文件 + （可选）CI job | 断言：workflows/ 不 import control 的 service/routes 层；kernel 类模块不读 os.environ/flask；不出现产品硬编码（对照 brand.ts 红线） |
| A9 审查不执行被审代码 | **采纳** | **高** | AGENTS.md 红线一条（未来 CI 断言） | 「AI 审查输入必须是 diff/文本快照，不得在审查机执行被审分支的代码/hooks/配置」 |
| A1 回执 DSL | **有条件采纳** | **中**（一期） | 新 `agents/receipt.py` + Skill 编写口径 | 一期 ask+later；Pydantic + 未知字段拒绝；容量对齐 64KB 语境；失败走 A7 降级路径；resolve/events 三期带闸评估 |
| A4 指令数据分离 | **有条件采纳** | **中** | `agents/context.py` 渲染层 + evidence 登记 | 外部来源文字只入文件（落项目工作目录/sandbox workspace）；提示词只放受控引用（路径+sha256）；渲染断言「资料非指令」；登记走 evidence |
| A5 trace 视图 | **部分采纳** | **中** | 新只读路由 + 桌面 WorkflowConsole 一块面板 | 一次 API 聚合：触发事件→definition_version→节点树→审批记录→evidence 指针→操作事件；project-scoped（can_view）；不落快照只落指针 |
| A6 统一到期+审批超时 | **部分采纳** | **中** | `control/scheduler.py` 重构 + 审批到期扫 | 统一到期计算函数；审批过期从惰性改主动扫+提醒；「单 timer」不搬 |
| A5 事项聚合层 | **暂缓** | 低 | （无） | 登记后续需求台账，等持续巡检类需求 |
| sim 三件套 | **暂缓** | 低 | （前置：executor 决策逻辑抽纯函数） | 三期；先攒真实故障史 |
| ci-scope 分流 | **可选** | 低 | GitHub Actions paths filter | 顺手项，非独立工程 |

---

## 7. 待澄清问题清单（含假设声明）

| # | 问题 | 影响哪条 | 当前假设 |
|---|---|---|---|
| 1 | zcode CLI 是否支持会话续接（resume/session）？ | A7 repair 增强、A2 会话续接 | 假设不支持 → 以「保留原结论+通知」为默认 |
| 2 | 近一个月真实交付 run 数量与审批平均等待时长？ | A2 退避参数、A6 优先级 | 无数据 → 退避序列先用 autoloop 量级（分钟级 5 档） |
| 3 | 是否发生过重复交付/额度失控事故？ | A3/A7 的优先级佐证 | 假设未发生 → 按「防事故保险」定位而非「救火」 |
| 4 | `workflow_runs.hops` 迁移本轮是否允许？（触发 rebuild + `alembic upgrade head` 流程；另：迁移文件实测 31 个，AGENTS.md 台账记 27 rev，口径差待核销） | A3 | 待拍板 |
| 5 | A1 一期是否允许改动 Agent Skill 编写口径（新增 JSON 输出约定）？ | A1 | 待拍板；不改口径则 A1 一期顺延 |
| 6 | 「持续巡检」类需求是否有真实客户在问？ | A5 事项层 | 假设没有 → 暂缓 |
| 7 | autoloop 的 tests/hops.test.ts 未在证据包内，其测试细节未核实 | A3 测试设计 | 我方自写测试，不依赖其样例 |
| 8 | 上游活跃度数据仅基于 2026-11-03 单日 5 commits 的提交历史可见部分 | 腐化风险评估 | 按「单人快迭代」对待，只抄机制不锁接口 |

## 8. 分阶段改进计划

### 先行批（本周可启动，合计 ≈2-4 人日）
| 序 | 动作 | 依赖 | 风险提示 |
|---|---|---|---|
| 1 | A9 立规：AGENTS.md 红线 +1（审查不执行被审代码） | 无 | 无 |
| 2 | A8 purity 架构测试：pytest 单文件锁 workflows/→control 依赖方向 | 无 | 「内核」边界需先在 AGENTS.md 定义一句，避免测试口径争论 |
| 3 | A7 语义落地：agents 输出解析失败 → `succeeded_but_receipt_invalid` 独立终态 + 保留原结论 + OperationEvent | 无 | 与 V8「失败终态拒同键重跑」的交互需写清（业务成功不触发重跑闸） |
| 4 | A2 剩余：审批退避提醒（复用任务中心徽标/通知）+ 挂起时长统计 | 无 | 提醒通道只在桌面端，注意勿引入新的外发通道 |

### 第二批（1-2 周，合计 ≈1 周）
| 序 | 动作 | 依赖 | 风险提示 |
|---|---|---|---|
| 5 | A3：`workflow_runs.hops` 列 + 迁移 + 执行器入口检查 + 熔断留痕 + pytest（含「拍板重投继承不清零」用例） | 先行批#2 定义的边界；迁移流程（rebuild + upgrade head） | 迁移窗口需停写；熔断阈值先硬编码 8 |
| 6 | A1 一期：`agents/receipt.py`（ask/later）+ Pydantic 校验 + 未知字段拒绝 + 失败走 #3 降级 | 先行批#3；用户拍板「改 Skill 编写口径」 | 首轮成功率可能降——必须同步上线降级路径 |
| 7 | A6：统一到期计算 + 审批超时主动扫 + 提醒 | #4 | scheduler 重构回归面大，先补 cron/interval 既有测试再动 |

### 第三批（1-2 月）
| 序 | 动作 | 依赖 | 风险提示 |
|---|---|---|---|
| 8 | A4：渲染层「资料非指令」断言 + evidence 自动登记 | evidence 表（已有） | 文件落点纪律必须先进 AGENTS.md（不落仓库） |
| 9 | A5 trace：只读聚合路由 + WorkflowConsole 面板 | 无硬依赖 | project-scoped 闸必须走 can_view；不落快照 |
| 10 | A1 二期 notice / 三期 resolve+events | #6 + 风险闸设计（can_manage + 留痕 + emits 同构） | resolve/events 未过风险评审不得上线 |
| 11 | （登记不排期）事项聚合层、sim 三件套、健康版本核实 | 真实需求/故障史 | — |

### 时间与风险总提示
- 全部迁移类改动走既有纪律：feature 分支 → PR → 4 CI job 全绿 → 合并；改 server 必 rebuild + `alembic upgrade head`。
- A1 是唯一「改写作口径」的项，建议先在 1 个内部 Skill 试点再推广。
- 上游接口不锁定：我们只吸收语义，任何常量数值（8 跳、5 档退避）都按我方场景重定，不追上游变更。

---

## 附：本报告证据包索引
`D:\test\fde-workbench\.workbuddy\review-agent-autoloop\`：`00-评审简报.md`（评审输入与纪律）+ `README.md` + `ev/` 32 份仓库一手文件（含 kernel_decide.ts / kernel_due.ts / kernel_schema.sql / kernel_credentials.ts / kernel_card-page.ts / kernel_http.ts / host_runtime.ts / protocol_validate.ts / protocol_schema.json / worker_worker.ts / worker_contract.ts / plugins_delivery_*.ts / tests_purity.test.ts / sim_invariants.ts / SECURITY.md / AGENTS.md / INSTALL.md / docs_protocol.md / docs_plugins.md）。

我方对照（本轮实测）：`server/src/fde_api/workflows/{executor,models,definition_service}.py`、`control/{service,scheduler,ai_tool_loop,access,api_actions}.py`、`agents/{service,adapter,sandbox,signoff}.py`、`evidence/models.py`、`projects/events.py`、`desktop/src/renderer/src/tasks/TaskCenterPage.tsx`、`server/migrations/versions/`（31 文件）。
