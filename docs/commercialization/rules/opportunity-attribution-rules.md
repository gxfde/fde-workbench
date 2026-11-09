# 商机归属与渠道保护：成文规则（v1，规则数值本期未定数）

- **适用范围**：商业化 G4（T-09）——创业者报备企业线索到平台按既定分成规则结算的全链路。
- **阶段**：G4 落地（ADR-009）。**本文件是「规则」的唯一成文处**；代码侧只提供**可配置结构**（配置位），**不预写任何业务数值**。
- **硬约束**：规则数值（保护期长度、续期条件、归属判定）**本期不定数**——配置位缺省 `unset`，成文前以「配置态留空」兜底，**不留硬编码默认值**（任务书 §1.2-6／§8）。
- **配套 ADR**：`docs/commercialization/decisions/ADR-009-opportunity-attribution-and-channel-protection.md`。
- **代码侧配置位**：`server/src/fde_api/commercial/models.py::OPPORTUNITY_RULE_KEYS` ＋ `OPPORTUNITY_RULE_VALUE_KINDS`；配置表 `commercial_opportunity_rules`。

---

## 1. 身份与术语

| 术语 | 含义 | 代码落点 |
|---|---|---|
| **商机** | 一个企业代号下的商业机会及其归属过程 | `commercial_opportunities` |
| **报备人** | 提交企业线索的创业者（R2） | `commercial_opportunities.reported_by_user_id` |
| **归属人** | 平台确认后负责该商机的创业者 | `commercial_opportunities.attribution_owner_user_id` |
| **企业代号** | 三段式代号（客户·行业·城市），**不是真实企业名** | `commercial_opportunities.enterprise_code`（与 `projects.enterprise_code` 同口径） |
| **保护期** | 归属确认后的**有界**时段，其间该企业的直签立项被封堵 | `commercial_opportunities.protection_*` ＋ 规则位 `protection_period_days` |

> **红线**：本域只存企业**代号**与指针＋sha256 指纹，**客户真实资料（姓名/扫描件/凭证）永不进库**（AGENTS 红线）。

## 2. 七步链路（成文规则）

| 步 | 名称 | 触发方 | 状态迁移 | 人工确认 | 落库 |
|---|---|---|---|---|---|
| 1 | **报备**（创业者提交企业线索） | 报备人本人（R2） | → `submitted` | 当事人自证（事件留痕） | `reported_by_user_id` |
| 2 | **企业确认有真实需求** | 平台代录企业书面答复 | `submitted` → `enterprise_confirmed` | **admin＋密码确认**，须附书面依据指针＋指纹 | `enterprise_confirmed_*` |
| 3 | **平台确认商机归属** | 平台 | `enterprise_confirmed` → `attribution_confirmed` | **admin＋密码确认**（关键流转，ADR-007），须附书面依据 | `attribution_owner_user_id` / `attribution_confirmed_at` |
| 4 | **设定保护期** | 平台 | 保护期状态 → `active`（**须规则位已配置**） | **admin＋密码确认** | `protection_started_at` / `protection_expires_at` |
| 5 | **创业者负责售前与客户关系** | 平台 | `attribution_confirmed` → `presales` | **admin＋密码确认** | `presales_owner_user_id`（默认＝归属人） |
| 6 | **平台撮合交付者** | 平台 | `presales` → `matched` | **admin＋密码确认** | `matched_delivery_package_id`（**引用既有 dispatch 交付包**，不建第二套撮合） |
| 7 | **按既定分成规则结算** | 平台 | `matched` → `settled` | **admin＋密码确认** | `settled_ledger_entry_id`（**引用 G3 科目层 project_share 行**） |

**辅助动作**：撤回（报备人自证，→ `withdrawn`）、争议（平台，规则位 `dispute_handling` 未配置则不可用，→ `disputed`）、客户自主选择（规则位 `customer_choice` 未配置则不可用）、归属改派（规则位 `attribution_criteria` 未配置则不可用）。

## 3. 保护期规则（成文，数值未设）

1. 保护期自「归属确认 + 设定保护期」起算，**长度取配置位 `protection_period_days`**。
2. **配置位未配置 ⇒ 保护期状态为 `unconfigured`**：既**不是**「永久保护」，也**不是**「立即失效」——三种状态（`unconfigured` / `active` / `expired`）在读面与接口错误码上**可区分**。
3. **保护期必有到期时刻**：`active` 态必须同时有 `protection_started_at` 与 `protection_expires_at`（库层 CHECK 约束）——**结构上不可能出现永久保护**。
4. 保护期内，该企业的**直签立项**被封堵（错误码 `opportunity_protection_active`，422），提示改走归属渠道；**派单线立项放行**（复购走池）。
5. 保护期结束（`expired`）后直签**立即恢复放行**——保护期**不得变成永久锁定企业**。

## 4. 续期条件（成文，条件未设）

1. 续期**须配置位 `renewal_conditions` 已配置**（成文的续期条件），否则续期动作 409 `rule_not_configured`。
2. 续期长度沿用 `protection_period_days`（未配置则不可续期——不落默认天数）。
3. 每次续期累加 `protection_renewal_count` 与 `protection_renewed_at`，并在事件中留痕；**续期不得延长到「无到期」**（到期时刻随续期同步后移）。

## 5. 客户自主选择权（成文，规则未设）

1. 配置位 `customer_choice` 未配置 ⇒ **不提供**客户自主选择入口（动作 409 `rule_not_configured`）。
2. 已配置时，客户可在平台撮合的候选中**自主指定交付包**，写入 `customer_choice_package_id`；该选择**不改变商机归属**（归属仍是归属人）。
3. 客户自主选择**不得**被用作绕过保护期的路径（选择动作不改保护期状态）。

## 6. 争议处理机制（成文，机制未设）

1. 配置位 `dispute_handling` 未配置 ⇒ **不可发起争议**（动作 409 `rule_not_configured`）——争议是**成文机制**下的动作，机制未定则不开放。
2. 已配置时，平台可把商机置 `disputed`；争议期间**不推进**后续链路步（撮合/结算拒绝，`disputed` 态下 409 `opportunity_disputed`）。
3. 争议记录只落**指针＋指纹**，争议材料本体不进库。

## 7. 归属判定（成文，判据未设）

1. 配置位 `attribution_criteria` 未配置 ⇒ **不可改派归属**（动作 409 `rule_not_configured`）——本期归属一旦确认即**稳定**，不存在任何自动或半自动的转移路径。
2. 归属确认**必须由人**（admin＋密码确认，ADR-007 关键流转默认人工确认）；系统不出「自动生效」的归属判定。
3. **企业后续自行注册（直签立项）不改变归属**：归属与保护期是本域的事实，企业侧的立项动作**无任何写路径**可触碰归属（结构性保证＋反例用例钉死）。
4. 改派（人工、显式、留痕、须判据规则已配置）**不是**企业注册的后果，二者不得混同。

## 8. 配置位对照（成文规则 ↔ 代码配置位，**一一对应**）

| 规则项 | 配置位 key | 值型 | 本期状态 | 缺省行为 |
|---|---|---|---|---|
| 保护期长度 | `protection_period_days` | `days` | **unset** | 保护期 `unconfigured`（非永久保护、非立即失效） |
| 续期条件 | `renewal_conditions` | `criteria` | **unset** | 续期不可用（409 `rule_not_configured`） |
| 客户自主选择权 | `customer_choice` | `criteria` | **unset** | 客户自主选择不可用（409 `rule_not_configured`） |
| 争议处理机制 | `dispute_handling` | `criteria` | **unset** | 争议不可发起（409 `rule_not_configured`） |
| 归属判定 | `attribution_criteria` | `criteria` | **unset** | 归属不可改派（409 `rule_not_configured`） |

<!-- rule-slots:begin -->
```json
{
  "slots": [
    {"key": "protection_period_days", "value_kind": "days", "label": "保护期长度", "default_status": "unset"},
    {"key": "renewal_conditions", "value_kind": "criteria", "label": "续期条件", "default_status": "unset"},
    {"key": "customer_choice", "value_kind": "criteria", "label": "客户自主选择权", "default_status": "unset"},
    {"key": "dispute_handling", "value_kind": "criteria", "label": "争议处理机制", "default_status": "unset"},
    {"key": "attribution_criteria", "value_kind": "criteria", "label": "归属判定", "default_status": "unset"}
  ]
}
```
<!-- rule-slots:end -->

> **机器闸**：`server/tests/test_commercial_opportunity_attribution.py` 解析上块 JSON，与代码常量 `OPPORTUNITY_RULE_KEYS`／`OPPORTUNITY_RULE_VALUE_KINDS` **逐项双向相等**，并核对配置表每行 `status='unset'`——**规则文件与代码配置位一一对应**（任务书 §8 验收）。
