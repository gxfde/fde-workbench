# ADR-001：角色分层与交付能力等级正交——`fde_profiles.level` 零改动保护与 R 系字段另立

- **状态：** Accepted（G0 裁决，2026-11-08）
- **消解歧义：** 任务书 §0.1（现有 `level` 字段 L1–L4 与角色分层同名不同义）＋ §0.4 裁决要求第 1/2/6 条
- **基线：** `eee317c`

## 1. 背景（实测）

商业口径把人的商业层级分为「L0 候选交付者 / L1 独立 FDE / L2 实战营 / L3 陪跑营 / L4 区域合作商」（BP §7.10 五层角色），而代码中 `fde_profiles.level` 的 L1–L4 是**交付能力等级**（衡量**人**、越大越资深，判据=独立交付单数 1/3/8/15、客户复购、带教、全额收款），已被撮合、评分、席位、规则快照全链依赖。两者**主语不同**（交付能力等级衡量人能不能交付；角色分层衡量人在组织中的商业层级），值域刻度也不同构（角色分层含 L0 候选态，能力等级从 L1 起）。共用一个字段必然互相覆盖语义。

## 2. 裁决

1. **`fde_profiles.level` 保持交付能力等级语义，不改名、不改值域、不加迁移**。其 CHECK（`level IS NULL OR level IN ('L1','L2','L3','L4')`）、`LEVELS`/`_DELIVERY_COUNTS`（profiles.py:33/:44）、`LEVEL_RANKS`（scoring.py:18）、`level_score_map`（system_configuration.py:79）全部原样。
2. **角色分层另立承载，不复用 `level`，不落 L 编号**：值域 **R1 企业 / R2 创业者 / R3 交付者 / R4 区域合作商**，可空（未分层）。具体落点（`users` 加新列 vs 商业身份表）在 G1 实施轮按「权益四分」的表结构一并定（ADR-002 关联），本 ADR 只钉死语义与命名边界。
3. **拒绝复用/扩展 `users.role`**：该列是平台权限角色（`VALID_ROLES = {admin, project_lead, fde_engineer, viewer}`，auth/models.py:13–18），消费面为 `ROLE_RANK` 权限阶梯（auth/permissions.py:1）与 `DEFAULT_ACCESS_BY_ROLE` AI 档位映射（control/access.py:43）——商业分层混入会改变权限阶梯行为并破坏既有校验（`InvalidRoleError`）与测试。R 系字段与权限角色**并存**，互不推导。
4. **对外 L0–L4 商业编号仅存于映射表**，从「角色 + 订阅/认证状态」推导；映射表是唯一转换入口，代码与迁移中**不得散落 L 编号换算**、不得新增以 L 开头的角色枚举值（细则见 ADR-006）。
5. **凡引用 L 编号必须写明「哪一套 + 主语 + 方向」三要素**（细则见 ADR-006 §三要素纪律）。

## 3. `level`（交付能力等级）依赖全集（裁决要求第 6 条）

### 3.1 交付能力等级族（零改动保护清单）

| 代码位置 | 依赖内容 |
|---|---|
| `server/src/fde_api/dispatch/models.py:237` | `FdeProfile.level` 列 + `ck_fde_profiles_level` CHECK |
| `server/src/fde_api/dispatch/models.py:40` | `delivery_packages.required_level` |
| `server/src/fde_api/dispatch/profiles.py:33,44` | `LEVELS`、`_DELIVERY_COUNTS = {L1:1, L2:3, L3:8, L4:15}`；晋级校验 :187 |
| `server/src/fde_api/dispatch/scoring.py:18` | `LEVEL_RANKS` |
| `server/src/fde_api/dispatch/matching.py:41,52,59` | `derive_required_level` / `override_required_level` / 值域闸 |
| `server/src/fde_api/dispatch/packages.py`、`dispatch/routes.py` | 包准入、序列化与路由 |
| `server/src/fde_api/dispatch/rules.py:25` | `REQUIRED_SNAPSHOT_KEYS` 含 `level_score_map`（规则快照契约） |
| `server/src/fde_api/dispatch/simulator.py:295` | 撮合模拟器投影 |
| `server/src/fde_api/system_configuration.py:79` | `level_score_map = {L1:40, L2:60, L3:80, L4:100}` |

### 3.2 同名异义「level 家族」（一并区分，防止未来误撞）

| 名称 | 载体（实测锚点） | 主语 | 方向 | 与角色分层关系 |
|---|---|---|---|---|
| 交付智能化等级 L1–L5 | BP v4.0 §1.3a 文档口径，**无代码字段**；当前评级 L2+ | **平台**（全系统一个值） | 越大越自动化 | 无关（平台演进轴） |
| 交付能力等级 L1–L4 | `fde_profiles.level`（§3.1 清单） | **人** | 越大越资深 | 正交；R3 交付者的商业层级 ≠ 其能力等级，两者可任意组合 |
| 降级链状态 L0–L3 | `agent_runs.fallback_level`（agents/models.py:65）；handoff 准入 `agents/service.py:1113`、`meetings/service.py:1326`；前端 `AgentsConsole.tsx`/`SolutionDetailPage.tsx` | **单次运行** | 越大越不自动化 | 无关；**不可删**（驱动 handoff 决策 + 界面证据），server/tests 26 处引用 |
| AI 访问档位 `required_level`/`access_level` | `control/models.py:13 AI_ACCESS_LEVELS`、`agents/models.py:248,262`、`agents/signoff.py:56`、`solutions/service.py` checkpoint 双闸 | 用户/检查点 | 权限阶梯 | 无关；同名 level，R 系落地时避开 |
| 催款级别 `DUNNING_LEVELS` | `projects/payment_service.py:46` | 收款台账 | D+7/15/30/60 | 无关 |

### 3.3 既有测试影响面（「零改动通过」的验证口径）

- `server/tests` 含 L1–L4 字面量：**19 个文件**；dispatch 域测试 16 个文件。
- 关键钉子：`test_dispatch_p0_r2.py`（derive/override_required_level）、`test_dispatch_p1_r5.py`（等级推导）、`test_dispatch_admin_rules.py` / `test_dispatch_p2_r7.py` / `test_dispatch_p2_r10_c7.py`（`level_score_map` 快照）、`test_dispatch_p1_r9_sim.py`（模拟器）。
- 桌面：`dispatch/ConsolePage.tsx`、`dispatch/DisputesPage.tsx`、`solutions/SignoffConsole.tsx` 消费等级展示。
- **G1 验收基线：上述测试零改动通过**（本线不触碰 dispatch 域与上述消费面）。

## 4. 理由

- 撮合/评分/席位/规则快照全链依赖 `level` 值域，改名/改值域是全仓级风险且零商业收益（§0.1 裁决前置结论）。
- BP 自己的两套 L 并用（「一个 L3 职级的创业者使用 L2+ 智能化程度的系统」）证明概念上必须分离承载；R 系命名让「商业层级」在代码中零歧义。
- 映射表收敛对外编号，避免第二套权威值域滋生（§0.4 裁决 3 的目的：以后改商业口径只动映射表一行）。

## 5. 后果

- 正面：G1+ 全部商业逻辑以 R 系表达；dispatch 域零回归风险；对外口径可调。
- 代价：多一张映射表/一个字段；文档引用 L 编号的纪律靠 ADR-006 三要素约束（评审把关）。
- 中性：`fde_profiles.level` 与 R 系字段在同一用户上可同时有值（例：R3 交付者 + 交付能力等级 L2），语义互不覆盖。

## 6. 与任务书裁决要求的对照

| 任务书 §0.1/§0.4 裁决要求 | 本 ADR |
|---|---|
| 0.1-1 `level` 保持原语义不改 | §2.1 ✅ |
| 0.1-2 角色分层另立字段 R1–R4，不复用 `level`，不落 L 编号 | §2.2 ✅ |
| 0.1-3 对外 L 编号仅映射表推导，唯一转换入口 | §2.4 ✅（细则 ADR-006） |
| 0.1-4 裁决文档列出全部 level 依赖与测试影响面 | §3 ✅ |
| 0.4-2 三套既有 L 全不改（含 fallback_level 不可删） | §3.2 ✅ |
| 0.4-5 凡引用 L 必须三要素 | §2.5 ✅（细则 ADR-006） |
| 0.4-6 区分降级链状态与智能化等级 | §3.2 表 ✅ |
