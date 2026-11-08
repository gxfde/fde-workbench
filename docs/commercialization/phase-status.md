# 商业化阶段状态（按 Goal 轮次累积）

- 权威基线：**fork/main**——G0 合并 `28f55fd`（#216）／G1 合并 `f186342`（#217）；G2 开工基线 `7c32736`
- 工作树：`D:\test\fde-wt-g1`
- 当前阶段：**G2 免费额度与三个体验入口（T-07，任务书 §6）**
- 阶段纪律：**一个 Goal 只做一个阶段，不跳阶段**；每阶段按任务书 §14 总提示词逐项回报（SHA/分支/阶段、改动文件、迁移、API·权限·目录、前端、测试命令与通过·失败·跳过数、安全·兼容·回滚、验收证据、遗留、下一阶段是否可开）

---

## G2：免费额度与三个体验入口（T-07）— 当前阶段

- 分支：`feat/commercial-g2-free-quota`（工作树 `D:\test\fde-wt-g1`）
- 基线 SHA：fork/main `7c32736`
- 状态：**进行中**（实现与测试已就位，待 CI 实测回填 pytest 口径后收口）

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

### 遗留问题

1. 主体认定口径待法务最终确认（ADR-004 状态行已注）。
2. 体验上限消费接线、三档分流人工判定留痕、注册面收 USCC → 归 G6。
3. 商机归属与渠道保护本体 → 归 G4。
4. GAP-15（AI 草稿采纳率埋点）仍开放——ADR-007 §2.5 的复审触发器依赖它。

### 是否允许进入下一阶段

**G2 收口（CI 四绿＋合并＋main run 收口＋部署活体绿）后允许进入 G3（订阅、培训与科目结算，T-10/T-11/T-13）**——ADR-005（区域商业化闸）仍归 G5，不预支。

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
