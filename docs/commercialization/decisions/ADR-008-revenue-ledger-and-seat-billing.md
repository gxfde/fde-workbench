# ADR-008：收入科目层与订阅席位计费——三类科目独立记账、套餐含席位不重复收、首单扣费须事先书面选定

- **状态：** Accepted（G3 成文，2026-11-09）
- **消解：** 任务书 §7（T-10 订阅席位 / T-11 培训与认证 / T-13 分账结算）的落地歧义；承接 ADR-003 §2.1–§2.5
- **基线：** fork/main `e06ae8d`（G2 收口态）

## 1. 背景（实测）

- G1 已落 `commercial_entitlements`（四权益：角色分层 R1–R4 / 订阅席位 / 认证状态 / 交付资格）与 `training_entitlements`（培训权益购买行）；`service.py::activate_seat` 是席位激活原语（admin + 密码确认 + `operation_events` 留痕），席位来源闭集 `SEAT_SOURCES = (first_delivery, bootcamp_practical, bootcamp_mentorship)`——其中 `first_delivery` 的注释已预埋「G3 首单扣费闸」。
- G2 已落 `enterprise_quota_subjects` / `enterprise_free_quota`（ADR-004 主体认定）与 ADR-007（关键流转默认人工确认：admin 门 + 密码确认双闸；自我动作例外；治理面不进 api_catalog）。
- 派单域已有 `dispatch/settlements.py::seat_shares_for`（四席位份额 %，active 规则版本快照优先、回退 `DISPATCH_CONSTANTS`）、`delivery_settlements`（平台↔FDE 分账，状态机 draft→accrued→payable→paid/disputed）、`DeliveryPackage`（派单态，含 `seat_delivery`/`dispatch_status`/`accepted_at`）；收款域有 `quotes` / `payments`（含 `received_amount` / `acceptance_passed_at`）/ `contracts`。
- 任务书 §7 的语义里有 **七个未定数**（首年席位费金额口径、扣费方式方案集、认证费金额、认证通过线、陪跑期限、分成比例、套餐价目），且「本期不落具体数值」是硬约束——只建结构、不得预写业务默认值。

## 2. 裁决

1. **收入科目层独立新建**（ADR-003 §2.1）：`commercial_revenue_ledger`（收入类型 → 金额 → 关联对象）。**未向 `delivery_settlements` 加任何列**（结构钉：head 上该表列集合逐位比对）。
2. **三类科目分别记账可分别核对**：`seat_fee`（席位费）/ `training_fee`（培训费）/ `project_share`（项目分成）。对账面按科目×名目汇总，并给出与收款台账的**差异笔数**（行金额 ≠ 关联收款实收额）。
3. **六项名目只定义归属，不定义计算方式**（ADR-003 §2.4）：归属矩阵 `LINE_ITEM_SUBJECTS`（软件订阅／企业订阅／使用量 → 席位费；项目费／平台分成 → 项目分成；软件服务费 → 培训费）是代码层权威，写路径校验配对，错配 400 `line_item_subject_mismatch`。**金额算法不实现**——结账金额本期走线下约定。
4. **金额来源只有三个**：① 配置位（缺省未设 ⇒ 不可用）；② 关联收款的**实收额**（`payments.received_amount`）；③ 人工录入的线下约定金额（必附 `source_uri` 指针 + `content_hash` sha256 指纹）。
5. **项目分成只引用既有分账结果，不重算**（ADR-003 §2.2）：科目行的金额 ≡ `delivery_settlements.delivery_amount`（传入不一致金额一律 409 `amount_mismatch_settlement`）；席位份额快照取 `seat_shares_for` 的**结果引用**（`seat_shares` JSON + `basis.seat_shares_source` 标注来源）。
6. **分成比例只落结构，本期不落数**（ADR-003 §2.3）：`commercial_split_rules`（角色 R1–R4 × 项目类型 → `ratio_bp` 万分比），本期**零行**；登记维度即 `status='unset'`（`ratio_bp` 恒 NULL），配置比例必须附书面依据指针 + 指纹。该表**不参与金额计算**——比例行只提供落位与可见性（`basis.split_ratio_status`）。
7. **首单扣费闸**（任务书 §7）：交付者首个付费项目**交付完成并验收后**才触发扣除 **3980**（本期唯一落数金额）。闸门在**服务层**（不靠人工纪律）：交付未验收 ⇒ 409 `acceptance_not_passed`；非交付席位本人 ⇒ 403；项目无「实收且验收通过」的里程碑收款 ⇒ 409 `payment_not_settled`；已购含席位套餐／席位已激活／已扣过 ⇒ 409（不重复收）；**扣费方式未书面选定 ⇒ 409 `deduction_method_not_selected`**。
8. **扣费方式书面选定＝当事人自证动作**（ADR-007 §2.4 的延伸）：`commercial_deduction_elections` 记选定人与书面依据（指针 + sha256）；**只有交付者本人能选定自己的**（路由不接受 `user_id`，admin 不得代选定——防止平台替用户承诺扣费）。方法集 `{one_time, annual_installment}`：**本期只实现方案 A（一次性扣除）**；选方案 B 时扣费闸 fail-closed 409 `deduction_method_not_implemented`（不误按 A 扣、不静默分期）。「未接单候选人不产生年度欠费」由结构保证——扣费只挂在已接单且已验收的交付项目上，且方案 A 无年度周期。
9. **席位不重复收**（任务书 §7）：「含首年席位费」的套餐目录（实战营 `bootcamp_practical` / 陪跑营 `bootcamp_mentorship`）在 `REVENUE_PACKAGES` 常量里声明 `covers_first_year_fee=True`（**不落价目**——价格走 `quotes`/`payments` 收款台账，避免双写）。判定走**两条独立路径**，任一成立即拒绝重复收取：① 权益行席位来源为实战营/陪跑营；② 科目层已有该人的「含首年席位费」套餐席位费行。**反例用例覆盖 L2／L3／L0 三种组合**（含席位套餐者恒 1 行席位费科目；无套餐的候选交付者扣 3980 且席位随扣费激活，来源 `first_delivery`、年度到期）。
10. **认证挂模拟考核，通过线本期不设**（任务书 §7）：`commercial_certification_records` 挂 `simulation_evaluations` 指针并快照当次 verdict/score；**通过线配置位未设 ⇒ 停在 `pending_threshold`，不判定通过**（认证状态不变更）——缺省不可通过，不落任何默认分数线。配置且达标（verdict='pass' 且得分 ≥ 阈值）才置 `certified`，`certification_source` 指向考核行。
11. **陪跑期限与培训周期挂钩，数值待定**（任务书 §7）：`commercial_fee_configs.mentoring_period_days` 未配置 ⇒ 陪跑权益的 `valid_until` 留空（结构先落）；配置后按周期推导。G1 的 `add_training_entitlement` 增补该挂钩（延迟导入避免商业模块成环）。
12. **认证费金额本期不设 ⇒ 缺省不可收款**：`commercial_fee_configs.certification_fee` 未配置时，按该配置位记账一律 409 `fee_not_configured`。
13. **高风险写默认人工确认**（ADR-003 §2.5 / ADR-007 §2.1）：科目层与计费闸的全部治理写：admin 门 + `confirm_password` 双闸，逐动作落 `operation_events`（带 request_id，**密码不落事件**）。**自我动作例外**只覆盖「扣费方式选定」一项（当事人自证），**不含**记账、扣费、配置位、认证判定。
14. **配置位缺省不可用，且不预写业务数值**：`commercial_fee_configs` 三个槽位（认证费金额／陪跑期限／认证通过线）迁移播种为 **unset**；服务层另提供 `ensure_fee_config` 自愈补建（槽位是结构，缺失即补建为 unset），**任何路径都不得预写数值**。

## 3. 理由

- **科目层独立于分账层**（ADR-003 §3）：分账表按「项目×席位」读，科目账按「科目×期间」读；塞同一张表会让任何一方查询都要过滤另一半的行。而 `delivery_settlements` 已被派单 r 系 16 个测试文件与规则快照钉住，加列会引发快照与序列化连锁改动。
- **金额不重算**：项目分成金额取既有分账的 `delivery_amount`，是「引用」而非「第二套算法」——既满足 ADR-003 §2.2，又让本期**不需要**先拍板分成比例（比例未定时金额仍有唯一权威来源）。
- **闸门放服务层而非流程**：验收判定、书面选定判定、不重复收判定若只落在流程文档里，回归时无从证伪；放进服务层后，「验收前不触发」「未选定不得扣费」都能用反例用例钉死。
- **自我动作例外只开一项**：让交付者自己写明「我选一次性扣除」，是把扣费同意权还给当事人；平台侧只做**记录与校验**，不得替当事人选择（G2「企业自证：admin 不得代确认」同款边界）。
- **缺省不可用优于缺省可用**：认证费、通过线、陪跑周期、分成比例在业务未拍板前一律「未配置」，写路径 fail-closed——宁可少收不可错收。

## 4. 后果

- 新增五表（`commercial_split_rules` / `commercial_fee_configs` / `commercial_deduction_elections` / `commercial_certification_records` / `commercial_revenue_ledger`）＋ 迁移 `d5f9a3c7e1b4`（additive，单链单头）。
- 商业治理路由 **+14**（读面 7 ＋ admin 写面 7），**全部不进 api_catalog**（AI 不可调用）。
- 陪跑期限与认证判定的数值**仍待外部输入**（任务书 §17 数值类）：本期配置位为空位，后续轮填实数即可，无需改结构。
- 「认证挂模拟考核」只落**证据挂接与判定闸**；模拟考核产物的生成与消费仍归 V3.2 模拟域，本轮零改动。

## 5. 与任务书 §7 / ADR-003 的逐条对照

| 任务书 §7 要求 | 本 ADR |
|---|---|
| 首单激活＝交付完成并验收后扣 3980 | §2.7 ✅（服务层闸 + 唯一落数金额） |
| 扣费方式方案 A 为默认、须事先书面选定 | §2.8 ✅（选定表 + 本人自证 + 未选定 409） |
| 未接单候选人不产生年度欠费 | §2.8 ✅（扣费只挂已验收交付项目；方案 A 无周期） |
| 席位不重复收（L2 9800／L3 19800 含首年 3980；L0 首单） | §2.9 ✅（套餐目录标记 + 双路径判定 + 三组合反例） |
| 认证独立收费项、金额本期不设（缺省不可收款） | §2.12 ✅（配置位 unset + `fee_not_configured`） |
| 认证挂模拟考核、通过线本期不设 | §2.10 ✅（挂评估指针 + `pending_threshold` 不判通过） |
| 陪跑期限与培训周期挂钩（结构先落，数值待定） | §2.11 ✅（配置位 + G1 挂钩推导） |
| 科目层：三类科目分别记账可分别核对 | §2.1–§2.4 ✅（独立表 + 按科目查询 + 对账面） |
| 六名目只定义归属不定义计算方式 | §2.3 ✅（归属矩阵 + 金额三来源） |
| 分成比例本期不定数，只落「按角色与项目类型配置」的结构 | §2.6 ✅（结构表零行、登记即 unset） |
| 约束：席位份额复用 `seat_shares_for` | §2.5 ✅（引用结果快照，不另起算法） |
| 约束：不得在 `delivery_settlements` 加列 | §2.1 ✅（结构钉：列集合逐位比对） |
| ADR-003 §2.5 科目层写路径属高风险写 | §2.13 ✅（admin + 密码确认 + 审计事件） |
