# 区域合作商计划规则（G5 成文规则唯一处）

- **状态：** Accepted（G5 成文，2026-11-09）
- **消解：** 任务书 §9（T-12a，**不含 T-12b**）的落地规则；配套 **ADR-005**（`decisions/ADR-005-regional-commercialization-gate.md`）
- **基准：** 正式区域合作商三档定价**以 BP v4.0 为唯一基准**（v4.0 终版，经蔡工拍板；投资人版附录 C）

## 1. 身份与术语

- **区域伙伴**：以伙伴代号（企业代号三段式口径，**非真实企业名**）登记的区域合作主体；身份材料一律指针 + sha256 指纹，原件留在本地工作目录（AGENTS 红线）。
- **区域阶梯**：城市观察伙伴 → 城市服务伙伴 → 正式区域合作商 → 区域代理（**本期不启用**）。
- **售卖开关**：`regional_sale_gate` 单行全局闸，**默认 closed**；开启的必要条件是合规条件清单四项签署证据齐备。

## 2. 四阶段（成文规则）

| 阶段 | stage 值 | 收费形态 | 独家区域权 | 本期状态 |
|---|---|---|---|---|
| 城市观察伙伴 | `city_observer` | **免费申请**（参与活动、体验系统、了解市场） | **不授予** | 可申请（当事人自证） |
| 城市服务伙伴 | `city_service` | **按项目结算，一单一结，不设固定年费** | **不授予** | 可升级（书面依据） |
| 正式区域合作商 | `formal_partner` | 三档年费（T1/T2/T3，见 §4） | 可声明（仅正式档） | **须先开售卖闸** |
| 区域代理 | `regional_agent` | —— | —— | **暂不启用**（无任何进入路径；省级方案待试点后另定） |

- **前两阶段不授予独家区域权、不提前承诺正式代理权益**——CHECK 结构性联锁（`ck_regional_partners_first_two_stages_no_exclusive`）＋服务层显式拒绝。
- **区域代理「暂不启用」**：`regional_agent` 在阶段闭集里保留位置，读面派生注记「暂不启用」；服务层对任何进入该阶段的动作显式 409 `regional_agent_not_enabled`。

## 3. 售卖开关与合规条件清单（成文规则；本期只登记不实现收费路径）

开关开启的**必要条件**（四项，全部须先登记签署证据：指针 + sha256 指纹 + 签署时刻）：

1. **备案**：首次订立特许经营合同后 15 日内向商务主管部门备案；
2. **披露**：订立合同之日前至少 30 日书面披露经营资源、费用构成与合同文本；
3. **冷静期**：合同含被特许人单方解除冷静期条款并明确费用返还方式；
4. **主体资格**：「至少 2 个直营店且经营满 1 年」——**客观时间门槛，不可提前**；直营店形态仅限分公司／子公司（持股超 50%）／母公司／控股股东的个体工商户或个人独资企业，电子商务形式网上店铺不算直营店。

> 以上为公开规范原文摘录（事实引用）。**「本模式是否被认定为特许经营」是法律判断，须律师出具意见——本期不预设结论。**

- 开启动作＝**关键流转**（admin 门 + `confirm_password` 双闸 + `operation_events` 留痕，密码不落事件）；CHECK 结构性排除缺件开门（`ck_regional_sale_gate_opened_complete`）。
- **进入正式区域合作商（即对外收费签约的开始）必须先过闸**：闸关 ⇒ 409 `regional_sale_gate_closed`——这是「无任何代码路径可在开关未开启时对外收费签约」的结构性保证。
- **试运营升级指标与首期金额本期不定数**：原文示例（首期 9800／90 天／补 20000）**不得作为合同条款或既定指标**——本仓任何代码、迁移、种子、规则槽位均不落这些数值。

## 4. 正式区域合作商三档定价（成文规则 ↔ 档位目录，**一一对应**）

以 **BP v4.0 为唯一基准**（v4.0 终版，经蔡工拍板）：

| 档位 | tier_code | 年费（元） | 含席位 | 转赠配额（席） |
|---|---|---|---|---|
| T1（核心区） | `T1` | 29800 | 15 | 7 |
| T2 | `T2` | 59800 | 30 | 15 |
| T3 | `T3` | 98000 | 50 | 25 |

- 目录由迁移播种进 `regional_partner_tiers`（`basis_reference` 记基准指针）；**目录存在 ≠ 可以售卖**（售卖闸关闭期间无任何签约路径）。
- **城市服务伙伴没有档位行**——「按项目结算、不设固定年费」是其结构性属性。

<!-- regional-rule-slots:begin -->
```json
{
  "stages": [
    {"stage": "city_observer", "label": "城市观察伙伴", "fee_model": "free_application", "exclusive": false, "enabled": true},
    {"stage": "city_service", "label": "城市服务伙伴", "fee_model": "per_project_settlement", "exclusive": false, "enabled": true},
    {"stage": "formal_partner", "label": "正式区域合作商", "fee_model": "annual_tier", "exclusive": true, "enabled": true},
    {"stage": "regional_agent", "label": "区域代理", "fee_model": null, "exclusive": null, "enabled": false, "note": "暂不启用"}
  ],
  "gate_conditions": [
    {"key": "filing", "label": "15 日内商务主管部门备案", "evidence": "uri+sha256+signed_at"},
    {"key": "disclosure", "label": "订约前至少 30 日书面披露", "evidence": "uri+sha256+signed_at"},
    {"key": "cooling_off", "label": "单方解除冷静期条款与费用返还方式", "evidence": "uri+sha256+signed_at"},
    {"key": "qualification", "label": "至少 2 个直营店且经营满 1 年", "evidence": "uri+sha256+signed_at"}
  ],
  "tiers": [
    {"tier_code": "T1", "annual_fee_amount": 29800.00, "included_seats": 15, "transfer_quota_seats": 7},
    {"tier_code": "T2", "annual_fee_amount": 59800.00, "included_seats": 30, "transfer_quota_seats": 15},
    {"tier_code": "T3", "annual_fee_amount": 98000.00, "included_seats": 50, "transfer_quota_seats": 25}
  ],
  "trial_upgrade_metrics": {"status": "unset", "note": "试运营升级指标与首期金额本期不定数；原文示例不得作为合同条款或既定指标"}
}
```
<!-- regional-rule-slots:end -->

> **机器闸**：`server/tests/test_commercial_regional_partners.py` 解析上块 JSON，与代码常量（`REGIONAL_PARTNER_STAGES`／`REGIONAL_GATE_CONDITION_KEYS`／`REGIONAL_TIER_CODES`）**逐项双向相等**，并核对档位目录三行与迁移种子逐位一致、开关行 `status='closed'`、试运营指标槽 `unset`（任务书 §9 验收）。

## 5. 城市服务伙伴按项目结算（成文规则）

- **一单一结**：每次结算关联一条既有 G3 科目层 `commercial_revenue_ledger` 的 `project_share` 行（项目服务费／组织服务费落该科目族，ADR-003「只定义归属不定义计算」）；一个科目行至多关联一次（UNIQUE 防重复计数）；科目行归属必须与结算项目一致。
- **不设固定年费**：本表结构上没有城市服务伙伴的年费字段；正式档年费只在 `regional_partner_tiers`。
- 正式区域合作商**不得**写按项目结算关联（服务层 409 `settlement_channel_mismatch`）——两档收费形态互斥。
