# ADR-002：权益四分独立建模——四字段并存，不覆盖 `fde_profiles.status`，认证与等级证据链并存

- **状态：** Accepted（G0 裁决，2026-11-08）
- **消解歧义：** 任务书 §0.2（Q04 四权益字段在代码中零命中；与 `fde_profiles.status` / `fde_level_evidence` 的边界）
- **基线：** `eee317c`

## 1. 背景（实测）

- `training_entitlement` / `subscription_entitlement` / `certification_status` / `delivery_eligibility` 四者在 `server/src` + `desktop/src` 全库**零命中**（G0 grep 复核确认）。
- 「派单资格」的既有承担者是 `fde_profiles.status`（pending/active/suspended，`ck_fde_profiles_status`）+ `is_active`——语义是**供给池生命周期**（是否进撮合池）。
- 「能力等级评定」的既有承担者是 `fde_profiles.level` + `fde_level_evidence`（`dispatch/models.py:315` 证据链）——语义是**派单内能力爬级**。
- Q04 拍板「权益须分四类字段管理，不得只用一个会员等级字段代表所有权益」。

## 2. 裁决

1. **四类权益必须新增、独立建模**（表或字段组由 G1 实施轮按本 ADR 的方向落），四类语义分别固定为：
   - **培训权益**（training_entitlement）：购买与有效期——培训费、认证费、陪跑；
   - **订阅权益**（subscription_entitlement）：年度席位（3980）激活状态、激活来源、到期；
   - **认证状态**（certification_status）：未认证/已认证，**挂模拟考核结果**（消费 V3.2 `simulation_evaluations`，只读引用）；
   - **交付资格**（delivery_eligibility）：是否具备接单并激活年度席位的资格。
2. **任一类不得由其他类推导替代；禁止单一「会员等级」字段代表全部**。验收时须有 ≥3 条反例用例证明「单一会员等级字段」方案被拒（不得放宽断言蒙混）。
3. **`delivery_eligibility` 不得覆盖或替换 `fde_profiles.status`**。二者并存且同步关系固定为：
   - `fde_profiles.status` = 供给池生命周期（pending 不占名额 → active 参与匹配 → suspended）；
   - `delivery_eligibility` = 商业资格（是否有资格接单并激活年度席位）；
   - 同步规则示例（G1 实施时落为可测不变量）：激活年度席位 → `fde_profiles.status` 由 pending 转 active；suspended 时 `delivery_eligibility` 的生效性由 G1 细化，但**两个状态字段各自保留、各自有写入路径与审计事件**。
4. **`certification_status` 与 `fde_level_evidence` 等级核验链并存**：认证=培训出口（是否已获认证），等级证据链=能力评定（交付爬级）；互不替代、互不写入对方。
5. **权益变更、额度扣减、席位激活属高风险写：默认需人工确认**，AI 只出草稿/建议；人工接管路径留审计事件（沿 `operation_events` 单一体系 + 既有 handoff 模式，不建第二套）——依据：交付智能化等级 L2+（平台，越大越自动化）下「AI 出初稿、人审核后交付」的固有形态（§0.5；活库实测自动化水平样本=0，见 00-baseline-audit §H）。
6. 权益变更留审计事件：Actor、对象、前后状态、时间、来源、请求 ID（沿 `operation_events` 既有载荷惯例）。

## 3. 理由

- 四类权益的生命周期、变更主体、到期规则完全不同（培训跟购买走、订阅跟年度走、认证跟考核走、资格跟派单走），单字段表达必然在某一类上语义失真。
- 与 `fde_profiles.status` 的并存裁决避免了「激活席位=进撮合池」的隐式捆绑——供给池准入是派单引擎治理态（含名额），商业资格是售卖侧事实，混同会让派单引擎被商业动作意外驱动。
- 与既有测试的关系：`fde_profiles.status`/`level` 值域零改动（ADR-001 §3.3 影响面）。

## 4. 后果

- G1 需要新表（或字段组）+ 迁移（自 `d5a8c2f4b7e1` 顺延，开工前 fetch 对齐）；「套餐已含首年席位则不重复收取」落为可测不变量（实战营 9800 与陪跑营 19800 均含首年 3980）。
- 桌面呈现（权益视图）随 G1 桌面轮，本期挂账不交付。
- 具体表名/列名在 G1 实施轮落 DDL 时定，本 ADR 只钉语义边界与不变量。

## 5. 与任务书裁决要求的对照

| 任务书 §0.2/§5 要求 | 本 ADR |
|---|---|
| 四字段必须新增（Q04 拍板） | §2.1 ✅ |
| `delivery_eligibility` 不得覆盖 `fde_profiles.status`，写明判据与同步关系 | §2.3 ✅ |
| `certification_status` 与等级核验链并存不互代 | §2.4 ✅ |
| 四类互不推导、禁单一会员等级字段（≥3 反例） | §2.2 ✅ |
| 高风险写默认人工确认 + 审计事件 | §2.5/§2.6 ✅ |
| 「套餐已含席位不重复收」可测不变量 | §4 ✅（G1 落地） |
