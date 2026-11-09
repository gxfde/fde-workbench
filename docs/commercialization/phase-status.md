# 商业化阶段状态（按 Goal 轮次累积）

- 权威基线：**fork/main**——G0 合并 `28f55fd`（#216）／G1 合并 `f186342`（#217）；G2 合并 `b0fd5fc`（#228）／**G3 合并 `f65f874`（#234）**
- 工作树：`D:\test\fde-wt-g1`
- 当前阶段：**G3 订阅、培训与科目结算（T-10/T-11/T-13，任务书 §7）— 已完成**
- 阶段纪律：**一个 Goal 只做一个阶段，不跳阶段**；每阶段按任务书 §14 总提示词逐项回报（SHA/分支/阶段、改动文件、迁移、API·权限·目录、前端、测试命令与通过·失败·跳过数、安全·兼容·回滚、验收证据、遗留、下一阶段是否可开）

---

## G3：订阅、培训与科目结算（T-10 / T-11 / T-13）— 已完成

- 分支：`feat/commercial-g3-revenue-ledger`（工作树 `D:\test\fde-wt-g1`）
- 基线 SHA：fork/main `e06ae8d`（开工时）；合并前融合上游 #231／#232／AI 原生化差距评估 v1.1（冲突仅 AGENTS.md 与 CHANGELOG.md，两边全留；融合后结构口径逐位不变）
- 状态：**completed**（PR #234 squash 合并 `f65f874`；PR run 42543224303 四绿 + **main run 42544563159 四绿**；**部署活体绿**——三镜像 rebuild 自本工作树 + `alembic upgrade head` `b3e7c9d1a5f2`→`d5f9a3c7e1b4`）

### 目标

任务书 §7：把席位、培训、认证、陪跑与收入科目分离落库。

### 设计决策及理由（含 ADR 编号）

- **ADR-008**（`decisions/ADR-008-revenue-ledger-and-seat-billing.md`，G3 成文）：收入科目层独立新建（不向 `delivery_settlements` 加列）；三类科目分别记账可分别核对；六名目只定义归属；分成比例只落结构不落数；席位份额复用 `seat_shares_for`；首单扣费闸落**服务层**（验收前不触发／未书面选定不得扣费）；扣费方式＝当事人自证（他人/admin 不得代选定）；认证挂模拟考核且通过线未设即不判定通过；陪跑期限结构先落数值待定；缺省不可用（认证费未配即不可收款）。
- 承接 **ADR-003** §2.1–§2.5（科目层独立、份额复用、比例不落数、六名目只定义归属、科目层写路径属高风险写）与 **ADR-007**（admin 门＋密码确认双闸、自我动作例外、治理面不进 api_catalog）。

### 修改文件

```text
新增：
  docs/commercialization/decisions/ADR-008-revenue-ledger-and-seat-billing.md
  server/src/fde_api/commercial/ledger_service.py        （NEW：科目层＋费用配置位＋分成结构）
  server/src/fde_api/commercial/billing_service.py        （NEW：首单扣费闸＋扣费选定＋认证挂考核）
  server/migrations/versions/d5f9a3c7e1b4_commercial_g3_revenue_ledger.py
  server/tests/test_commercial_revenue_ledger.py         （NEW：26 例）
修改：
  server/src/fde_api/commercial/models.py                （+5 表 + 闭集常量）
  server/src/fde_api/commercial/routes.py                （+7 读/自证路由）
  server/src/fde_api/commercial/admin_routes.py          （+7 治理写路由）
  server/src/fde_api/commercial/service.py               （陪跑期限挂钩 G3 配置位）
  server/tests/conftest.py                               （清理序：G3 五表先于派单簇与 users）
  server/tests/test_migrations.py                        （HEAD_REVISION + 全集断言 52→53）
  docs/audit/v3-{route,database}-inventory.csv + v3-workbench-inventory.json（重生成）
  docs/architecture/archify-diagrams/architecture/*      （口径数字同步 + preview 重出）
  AGENTS.md / CHANGELOG.md（本节）
```

### 数据库迁移

迁移 `d5f9a3c7e1b4`（52→53 rev，additive 五表）：`commercial_split_rules`（分成比例结构：角色 R1–R4 × 项目类型 → `ratio_bp`，**本期零行**）、`commercial_fee_configs`（认证费金额／陪跑期限／认证通过线三个配置位，**迁移播种为 unset**）、`commercial_deduction_elections`（扣费方式书面选定；部分唯一索引＝一人一条 elected）、`commercial_certification_records`（认证挂模拟考核）、`commercial_revenue_ledger`（**收入科目层**）。单链单头，无双头。

### API / 权限 / API Catalog

- 读面（7）：`GET /api/v1/commercial/packages`、`GET /api/v1/commercial/revenue-ledger`、`GET /api/v1/commercial/revenue-ledger/reconciliation`、`GET /api/v1/commercial/revenue-ledger/<entry_id>`、`GET /api/v1/commercial/deduction-election`、`GET /api/v1/commercial/certification-records/<user_id>`。
- 自证面（1）：`POST /api/v1/commercial/deduction-election`（**只认 actor 本人**，payload 里的 `user_id` 无效——杜绝代选定）。
- 治理写面（7，admin＋密码确认双闸）：`POST /api/v1/admin/commercial/revenue-ledger`、`POST /api/v1/admin/commercial/first-order-fee`、`POST /api/v1/admin/commercial/fee-configs/<key>`、`GET /api/v1/admin/commercial/fee-configs`、`GET /api/v1/admin/commercial/split-rules`、`POST /api/v1/admin/commercial/split-rules`、`POST /api/v1/admin/commercial/certification-records`。
- **全部不进 api_catalog**（商业治理面，AI 不可调用）——`api_catalog` ENTRIES **94** 不变。

### 前端变化

无（纯服务端轮，桌面便携版不重打包；商业化桌面呈现面挂后续轮）。

### 测试命令与结果

- `PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_commercial_revenue_ledger.py -q` → **26 passed**。
- 全量 `pytest -q -n 4 --dist loadfile`（**CI 同命令**）→ **2454 收集 = 2448 passed + 6 skipped，0 failed**（EXIT=0，8m16s；G2 轮基线 2402 收集 + 本轮 +26 + 融合上游 #231 的 26 ＝ 2454）。
- **PR #234 CI run 42543224303 server-tests 实测 2448 passed + 6 skipped**（569.95s）——与本地同值。
- **合并态 main run 42544563159 四绿**（合并态权威）：server-tests 实测 **2448 passed + 6 skipped**（359.40s）／desktop 2m10s／secrets-scan 12s／pseudonymization 53s。
- `python scripts/check-python-types.py` → **OK：baseline 279 occurrences / 104 distinct，current 279**（无新增）。
- `ruff check`（改动文件）→ All checks passed。
- **变异十连全转红→还原→绿**（任务书 §12.10）：M1 不重复收判定整体失效／M2 未选定方案仍扣费／M3 验收前仍扣费／M4 项目分成按比例重算（不引用分账）／M5 名目归属校验失效／M6 关联对象必填失效／M7 通过线未设也判通过／M8 书面证据指纹闸失效／M9 认证费缺省可收款／M10 陪跑期限未配置也落默认天数。

### 安全检查

- 高风险写（记账／首单扣费／配置位／分成登记／认证判定）＝admin 门＋`confirm_password` 双闸；逐动作 `operation_events` 留痕（带 request_id，**密码不落事件**）。
- 书面证据只存 `source_uri` 指针 + `content_hash` sha256 指纹；证据原件不进仓、不进库。
- 扣费方式选定＝当事人自证（ADR-007 §2.4），**admin 不得代选定**；证据缺指针或指纹非 sha256 一律 400。
- 未读取无关密钥；`server/.env` 未入库；客户资料零触碰；本轮零生产变更。

### 数据兼容与回滚

- additive 五表，**零既有表改列**（`delivery_settlements` 列集合逐位比对，结构钉）。
- 回滚＝`alembic downgrade b3e7c9d1a5f2`（子表先行：ledger → certification_records → deduction_elections → fee_configs → split_rules）+ 回滚镜像。
- 科目层与既有收款台账不双写：金额来源为配置位／关联收款实收额／线下约定金额三者之一。

### 验收证据（任务书 §7 逐条）

| 验收项 | 证据 |
|---|---|
| 「套餐含席位不重复收」反例用例（含 L2／L3／L0 三种组合） | `test_package_included_seat_is_not_charged_again[bootcamp_practical/bootcamp_mentorship]`（409 `seat_fee_already_included` ＋ **席位费科目行恒 1 行**）＋ `test_first_order_fee_applies_for_candidate_without_package`（无含席位套餐者扣 3980 且席位激活） |
| 首单扣费在验收前不触发 | `test_first_order_fee_blocked_before_acceptance`（409 `acceptance_not_passed`，零行）；变异 M3 转红 |
| 未选定方案时不得扣费 | `test_first_order_fee_blocked_without_election`（409 `deduction_method_not_selected`，零行）；变异 M2 转红 |
| 三类科目分别可查、可对账 | `test_three_subject_types_separately_queryable_and_reconcilable`（按 `subject_type` 各查各的＋对账分桶金额逐位吻合） |
| 新增服务端逻辑有测试 | NEW `test_commercial_revenue_ledger.py` 26 例；变异十连全转红→还原转绿 |
| 新增路由有权限测试 | `test_ledger_read_scope_and_permissions`（本人／admin／他人 403／未认证 401）＋ `test_governance_writes_require_admin_and_password`（非 admin 403／缺密码 400／错密码 403） |
| 席位份额复用 `seat_shares_for` | `test_project_share_references_settlement_without_recompute`（快照 ≡ `seat_shares_for`；金额 ≡ 分账 `delivery_amount`；不一致金额 409）；变异 M4 转红 |
| 不在 `delivery_settlements` 加列 | `test_delivery_settlements_keeps_its_original_columns`（列集合逐位比对） |
| 认证费金额本期不设→缺省不可收款 | `test_certification_fee_cannot_be_charged_before_configured`（409 `fee_not_configured`）；变异 M9 转红 |
| 认证挂模拟考核、通过线本期不设 | `test_certification_without_threshold_stays_pending`（`pending_threshold`、认证状态不变）＋ `test_certification_after_threshold_configured`；变异 M7 转红 |
| 陪跑期限结构先落、数值待定 | `test_mentoring_period_structure_is_pending_by_default`；变异 M10 转红 |

### 遗留问题

1. 认证费金额、陪跑周期、认证通过线、分成比例**仍待业务拍板**（任务书 §17 数值类）——配置位与结构已就位，填实数即可，无需改结构。
2. 方案 B（年度分期）的周期与算式未实现（fail-closed 拒绝），随数值拍板一并落地。
3. 商机归属与渠道保护本体 → 归 G4。
4. GAP-15（AI 草稿采纳率埋点）仍开放——ADR-007 §2.5 的复审触发器依赖它。

### 部署活体验证（合并后）

- 三镜像（api/worker/scheduler）自本工作树 `D:/test/fde-wt-g1` 重建；构建树与 `fork/main` `f65f874` **逐位一致**（`git diff fork/main <branch>` 为空）⇒ 部署的就是合并态代码。
- `docker compose -p fde-workbench up -d` 后三容器 **healthy**（api/worker/scheduler）。
- `alembic upgrade head`：`b3e7c9d1a5f2` → **`d5f9a3c7e1b4` (head)**；`alembic current` ＝ `d5f9a3c7e1b4 (head)`。
- 活体断言：`url_map` **412** 条（审计口径 411，+1 恒定差）；**commercial 27 条**（G1 七 ＋ G2 六 ＋ G3 十四，含 G3 新增的 `packages`／`revenue-ledger`×3／`deduction-election`×2／`certification-records`×2／`fee-configs`×2／`split-rules`×2／`first-order-fee`）。
- G3 五表齐备：`commercial_revenue_ledger` 28 列／`commercial_split_rules` 11 列／`commercial_fee_configs` 12 列／`commercial_deduction_elections` 10 列／`commercial_certification_records` 13 列；**CHECK 全在**（科目层 9 条、配置位 5 条、分成结构 4 条、选定 2 条、认证记录 2 条）。
- **五表零行**（`commercial_fee_configs` 3 行为迁移播种的 **unset** 配置位；其余四表 0 行——无客户数据）；`commercial_split_rules` **零行**（本期比例不定数）。
- **结构钉活体复核**：`delivery_settlements` 列集合仍为原 **20 列**（`acceptance_passed_at`／`base_amount`／`city_amount`／`created_at`／`delivery_amount`／`id`／`package_id`／`paid_at`／`paid_proof_source_uri`／`platform_amount`／`region_amount`／`seat_*`×4／`settlement_key`／`snapshot_hash`／`status`／`updated_at`／`withholding_tax`）——**零加列**。
- `/api/v1/health/ready` 与 `/api/v1/health/live` 均 **200**。

### 是否允许进入下一阶段

**允许进入 G4（商机归属与渠道保护，T-09，任务书 §8）**——前置已全部满足：PR 四绿 ＋ 合并态 main run 四绿 ＋ 部署活体绿。
ADR-005（区域商业化闸）仍归 G5，不预支；GAP-15（AI 草稿采纳率埋点）仍开放——ADR-007 §2.5 的复审触发器依赖它。

---

## G2：免费额度与三个体验入口（T-07）— 已完成

- 分支：`feat/commercial-g2-free-quota`（工作树 `D:\test\fde-wt-g1`）
- 基线 SHA：fork/main `7c32736`（开工时）→ 合并后 fork/main `b0fd5fc`
- 状态：**completed**（PR #228 squash 合并 `b0fd5fc`；PR run 42505691928 四绿 + **main run 42506701371 四绿**；**部署活体绿**——三镜像 rebuild 自本工作树 + `alembic upgrade head` `e9c4a1f7b3d2`→`b3e7c9d1a5f2`）

### 目标

任务书 §6：免费只到一次完整业务诊断，且额度按企业主体计。

### 设计决策及理由（含 ADR 编号）

- **ADR-004**（`decisions/ADR-004-free-quota-subject-identity.md`）：主体认定键＝统一社会信用代码规范化（mod-31 校验位）；一次一主体、长期有效不重置；换账号不重置；多子公司保守默认＝不分别（法务待确认）；完成判据＝六项齐备＋企业确认；免费边界七项；三档纯描述；两档体验上限；三入口隔离注册表＋域闸。
- **ADR-007**（`decisions/ADR-007-human-confirmation-default.md`）：关键流转默认人工确认——admin 门＋密码确认双闸；AI 无直写入口（治理面不进 api_catalog）；人工接管沿 `handoff_run` 既有模式；自我动作例外（企业自证）；实测后复审触发器。

### 修改文件

```text
新增：
  docs/commercialization/decisions/ADR-004-free-quota-subject-identity.md
  docs/commercialization/decisions/ADR-007-human-confirmation-default.md
  server/src/fde_api/commercial/quota_service.py        （NEW：额度服务层）
  server/migrations/versions/b3e7c9d1a5f2_commercial_g2_free_quota.py
  server/tests/test_commercial_enterprise_quota.py       （NEW：13 例）
修改：
  server/src/fde_api/commercial/models.py                （+两表+常量）
  server/src/fde_api/commercial/routes.py                （+4 读/当事人路由）
  server/src/fde_api/commercial/admin_routes.py          （+2 治理写路由）
  server/tests/conftest.py                               （清理序）
  server/tests/test_migrations.py                        （HEAD+全集断言）
  server/tests/test_commercial_entitlements.py           （downgrade 改显式父版本）
  docs/audit/v3-{route,database}-inventory.csv + v3-workbench-inventory.json（重生成）
  AGENTS.md / CHANGELOG.md（本节）
```

### 数据库迁移

迁移 `b3e7c9d1a5f2`（51→52 rev，additive 两表）：`enterprise_quota_subjects`（PK=subject_key 18 位）＋ `enterprise_free_quota`（PK=subject_key 一主体一份，四条 CHECK 联锁）。单链单头，无双头。

### API / 权限 / API Catalog

- 读面：`GET /api/v1/commercial/enterprise-quota/<subject_key>`（本人/admin，他人 403，未知 404）、`POST .../start`、`POST .../confirm`、`GET /api/v1/commercial/free-diagnosis-profile`。
- 治理写面（admin＋密码确认双闸）：`POST /api/v1/admin/commercial/enterprise-quota/grant`、`POST /api/v1/admin/commercial/enterprise-quota/<subject_key>/complete`。
- **全部不进 api_catalog**（商业治理面，AI 不可调用）——`api_catalog` ENTRIES **94** 不变。

### 前端变化

无（纯服务端轮，桌面便携版不重打包；商业化桌面呈现面挂后续轮）。

### 测试命令与结果

- `PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_commercial_enterprise_quota.py -q` → **14 passed**。
- 全量 `pytest -q -n 4 --dist loadfile` → **2402 收集 = 2396 passed + 6 skipped，0 failed**（EXIT=0，12m52s）；**PR #228 CI run 42503516295 server-tests 实测 2396 passed + 6 skipped（409.81s）——与本地同值**（架构评估十项实施轮基线 2388 收集 + 本轮 +14）。
- `python scripts/check-python-types.py` → **OK：baseline 279 occurrences / 104 distinct，current 279**（无新增）。
- `ruff check`（改动文件）→ All checks passed。
- **变异六连全转红→还原→绿**（任务书 §6「至少 1 条变异用例证明『额度按账号计』的实现会转红」）：M1 换账号可重绑／M2 授予幂等键含账号／M3 放宽完成判据／M4 触限判定放宽／M5 三入口隔离失效／M6 写路径不取行锁重读（并发额度可被重发）。

### 安全检查

- 高风险写＝admin 门＋`confirm_password` 双闸；逐动作 `operation_events` 留痕（带 request_id，**密码不落事件**）。
- 企业确认只认绑定账号本人，admin 不得代确认。
- 主体键校验位本地可验证；不存客户真实业务内容（只存判据账与主体代号键）。
- 未读取无关密钥；`server/.env` 未入库；客户资料零触碰。

### 数据兼容与回滚

- additive 两表，零既有表改列；`downgrade` 子表先行（free_quota → subjects）可逆。
- 回滚＝`alembic downgrade e9c4a1f7b3d2` + 回滚镜像；既有商业化数据不与既有域混写，无双写风险。

### 验收证据（任务书 §6 逐条）

| 验收项 | 证据 |
|---|---|
| 换账号不重置额度（同一主体再注册不得获得第二次） | `test_start_binds_account_blocks_other_accounts_and_restart`（换账号 409 `quota_bound_to_other_account`）＋`test_grant_idempotent_per_subject_never_second_row`（行数恒 1）＋`test_start_race_serializes_on_row_lock`（并发启动被行锁串行化）；变异 M1/M2/M6 转红 |
| 六项交付物未齐备不算完成 | `test_completion_requires_exactly_six_true`（五键 409 点名／一 False 409／多余键 400）；变异 M3 转红 |
| 六项不免费内容不进入免费流程 | `FREE_EXCLUSIONS` 七项常量＋闭集拒绝（多余键 400）；`test_free_diagnosis_profile_meta` |
| 创业者不能取到企业真实商机 | `test_three_trial_entries_isolated`（非企业入口取 real_business 403）；变异 M5 转红（商机归属本体归 G4） |
| 交付者触及上限即受限 | `test_experience_limit_exceeded_at_cap`（used≥cap 409）；变异 M4 转红 |
| 至少 1 条变异用例证明「额度按账号计」会转红 | M1／M2 双条，均转红→还原转绿 |

### 部署活体验证（合并后）

- 三镜像（api/worker/scheduler）自本工作树 `D:/test/fde-wt-g1` 重建；`docker compose -p fde-workbench up -d` 后三容器 healthy。
- `alembic upgrade head`：`e9c4a1f7b3d2` → **`b3e7c9d1a5f2`**（G2 additive 两表）。
- 活体断言：`alembic current` = `b3e7c9d1a5f2`；`url_map` **398** 条（审计口径 397，+1 恒定差）；**commercial 13 条**（G1 七条 + G2 六条）；`enterprise_quota_subjects` 6 列 / `enterprise_free_quota` 12 列；四条 CHECK 齐备（`state`／`bound_shape`／`completed_shape`／`confirm_requires_completed`）；两表**零行**（无客户数据）。
- `/api/v1/health/ready` 与 `/api/v1/health/live` 均 **200**。

### 遗留问题

1. 主体认定口径待法务最终确认（ADR-004 状态行已注）。
2. 体验上限消费接线、三档分流人工判定留痕、注册面收 USCC → 归 G6。
3. 商机归属与渠道保护本体 → 归 G4。
4. GAP-15（AI 草稿采纳率埋点）仍开放——ADR-007 §2.5 的复审触发器依赖它。

### 是否允许进入下一阶段

**允许进入 G3（订阅、培训与科目结算，T-10/T-11/T-13）**——前置已全部满足：PR 四绿 ＋ 合并态 main run 四绿 ＋ 部署活体绿。
ADR-005（区域商业化闸）仍归 G5，不预支；GAP-15（采纳率埋点）仍开放。

---

## G1：权益四分与角色分层（T-04、T-05）— 已完成

- 分支：`feat/commercial-g1-entitlements`；合并：**fork/main `f186342`**（PR #217）
- 目标：任务书 §5。四权益独立建模；角色分层 R1–R4；对外 L 编号唯一换算入口；席位激活与 `fde_profiles.status` 的单向同步。
- 裁决落地：**ADR-001**（角色分层 vs 交付能力等级正交、`fde_profiles.level` 零改动保护清单）、**ADR-002**（四权益独立、不覆盖 `fde_profiles.status`、高风险写双闸）、**ADR-006**（R1–R4 命名与六套 level 同名家族区分）。
- 改动：`commercial_entitlements`＋`training_entitlements` 两表；迁移 `e9c4a1f7b3d2`（50→51 rev）；+7 路由（384→391）、+2 蓝图（47→49）——全不进 api_catalog（ENTRIES 94 不变）。
- 测试：NEW `test_commercial_entitlements.py` 15 例；变异双验证红→还原→绿。
- 口径：CI 实测 **pytest 2360 = 2345 + 15 + 6 skipped**；mypy 279；路由 391／蓝图 49／表 130／51 rev 单头 `e9c4a1f7b3d2`。
- 部署：合并后 rebuild 三镜像＋`alembic upgrade head`（`e9c4a1f7b3d2`），`/health/ready` 与 `/live` 200，三容器 healthy。

---

## G0：基线审计 + 四个歧义 ADR — 已完成

- 分支：`feat/commercial-g0-audit`；合并：**fork/main `28f55fd`**（PR #216）
- 基线 SHA：`eee317c`（fork/main，PR #214 合并态；任务书自述基线 `858e090` 已被其后 8 个合并超越，本轮以现测为准）
- 开始/完成时间：2026-11-08 16:35 开工 / 2026-11-08 同日收口（以 PR 合并时间为准）

### 本阶段目标

按任务书 §14 总提示词第 3 条：「第一个 Goal 只做 G0 基线审计 + 四个歧义 ADR，不改业务代码。」覆盖任务书 §2 G0 必做项 1–8。

### 真实代码定位

见 `00-baseline-audit.md` §B–§F（逐行锚点实测）。要点：任务书 §2 表格全部属实；权益四字段全库零命中；派单/席位/结算/降级链结构完备但活库零使用。

### 设计决策及理由（含 ADR 编号）

- **ADR-001**（`decisions/ADR-001-role-vs-delivery-level.md`）：角色分层与交付能力等级正交；`fde_profiles.level` 零改动保护；R1–R4 不落 L 编号；含 level 依赖全集与测试影响面。
- **ADR-002**（`decisions/ADR-002-entitlement-model.md`）：四权益独立建模方向；不覆盖 `fde_profiles.status`；`certification_status` 与 `fde_level_evidence` 并存。
- **ADR-003**（`decisions/ADR-003-revenue-ledger-vs-dispatch-settlement.md`）：收入科目层独立于 `delivery_settlements`；份额算法复用 `seat_shares_for`；比例不落数。
- **ADR-006**（`decisions/ADR-006-naming-convention-r1r4.md`）：R1–R4 命名规范；六套「level 同名家族」区分；凡引用 L 编号必须写三要素。
- ADR-004 / ADR-005 / ADR-007 分别归 G2 / G5 / G1 设计轮成文（**ADR-004/007 已于 G2 成文**；ADR-005 仍归 G5）。

### 修改文件

全部为新增文档（零业务代码、零迁移、零路由）：

```text
docs/commercialization/
  00-baseline-audit.md      （基线审计：§B 逐项核验、口径七项现测、活库智能化实测）
  00-gap-register.md        （15 条缺口登记 + Goal 矩阵）
  phase-status.md           （本文件）
  decisions/
    ADR-001-role-vs-delivery-level.md
    ADR-002-entitlement-model.md
    ADR-003-revenue-ledger-vs-dispatch-settlement.md
    ADR-006-naming-convention-r1r4.md
```

### 数据库迁移

零迁移（基线维持 49 rev，head `d5a8c2f4b7e1`）。

### API / 权限 / API Catalog

零改动（路由 384、api_catalog ENTRIES 94 不变）。

### 前端变化

无（桌面便携版重打包挂账不适用于本轮）。

### 测试命令与结果

- 本轮纯文档，未跑新测试；基线口径引用 CI main run **42461768715**（#214，2026-11-08）job log 实测：
  - server-tests：**2333 passed + 6 skipped**（11m28s，job 128672384334）
  - desktop：**951 passed / 81 文件**（vitest，job 128672384201）
  - secrets-scan / pseudonymization 均绿。
- mypy 基线 279 行未动（`wc -l server/mypy-baseline.txt` 现测）。

### 安全检查

- 活库查询全部只读 SELECT（经 api 容器应用自身配置连接），零写入、零生产变更。
- 未读取无关密钥；`server/.env` 未打开；客户资料零触碰。
- 遵守红线：本审计不含任何客户真实姓名/扫描件/凭证。

### 数据兼容与回滚

- 无 schema/数据变更，无需回滚方案；文档可随时 revert。

### 验收证据

- 任务书 §2 G0 必做项 1–8 对照：1=§A、2=§B、3=§C/§D、4=§E.1、5=§E.3、6=§G、7=§H、8=两份 00- 文档已产出。
- 智能化评级判定：实测样本=0 ⇒ 维持书面口径 **L2+（交付智能化等级：平台，越大越自动化）**，不因口述升格（§0.5 硬约束）；G1–G6 关键流转按「默认人工确认」实现。
- 四个歧义裁决全部落盘且与任务书 §0 的裁决要求逐条对照（见各 ADR 尾节）。

### 遗留问题

1. ADR-005 待 G5 成文。
2. GAP-15（AI 草稿采纳率埋点）待落地（**仍开放**——ADR-007 §2.5 的复审触发器依赖它）。
3. 任务书 §17 外部输入 8 项维持待外部状态（法务意见、数值类、v4.0 原件核验等）。
4. 任务书基线 SHA（858e090）与当前权威基线（eee317c）的漂移已在本文档头部说明，后续 Goal 以「开工前现测」纪律处置。

### 是否允许进入下一阶段

**G0 已允许 G1 开工**（G1 已完成，见上）。
