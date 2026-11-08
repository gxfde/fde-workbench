# 商业化线 G0 基线审计（00-baseline-audit）

- **日期：** 2026-11-08
- **执行分支：** `feat/commercial-g0-audit`（基于 fork/main）
- **基线提交：** `eee317c`（PR #214，商业化任务书 L 编号四套标注修订，2026-11-08 16:10 合并，main CI run 42461768715 四 job 全绿）
- **任务书基线差异说明：** 任务书自述基线为 `858e090`（V3.1 P0-2）。其后的合并且本轮必须感知的有：#206 任务书入库 → #207 P0-3 交付方案（plans 三表）→ #209 P0-4 Workflow 模板 → #210 本体候选组序修复 → #211 P1-2 质量三表 → #213 P1-2 口径回填 → #212/#214 任务书 L 编号修正。**本审计全部以 `eee317c` 现测为准**，不承袭任务书内数字。
- **性质：** 纯审计，零业务代码改动；活库查询全部为只读 SELECT。

---

## §A 仓库状态核对（G0 必做项 1）

- 工作树：`D:\test\fde-wt-g1`（既有工作树，前会话任务书修订已随 #214 squash 合并，本地分支树 hash 与 fork/main 一致，接管安全）。
- 分支：`feat/commercial-g0-audit`，自 `fork/main = eee317c` 新建。
- fork/main 无在途商业 PR（`gh pr list` 为空），无并发认领。
- 主树 `D:\test\fde-workbench` 上有他人未提交的 `brand/` 修改，本线零触碰。

## §B 任务书 §2 表格逐项核验（G0 必做项 2）

逐行实测（锚点为 `eee317c` 上的行号）：

| 任务书断言 | 实测结果 | 锚点 |
|---|---|---|
| `dispatch/models.py` `fde_profiles`，level CheckConstraint L1–L4、NULL 未定级 | ✅ 存在 | `dispatch/models.py:237`，`ck_fde_profiles_level` = `level IS NULL OR level IN ('L1','L2','L3','L4')` |
| `fde_profiles.status` = pending/active/suspended | ✅ 存在 | `ck_fde_profiles_status`（models.py:264 附近） |
| `fde_level_evidence` 证据链 | ✅ 存在 | `dispatch/models.py:315` |
| `dispatch/profiles.py` `LEVELS`、`_DELIVERY_COUNTS = {L1:1, L2:3, L3:8, L4:15}` | ✅ 存在 | `profiles.py:33` / `:44` |
| 晋级判据=交付能力事实（单数/复购/带教/收款） | ✅ 结构在位 | `profiles.py` 晋级校验 `_DELIVERY_COUNTS[to_level]`（:187） |
| `dispatch/matching.py:59` level 值域检查 | ✅ 精确命中 | `matching.py:59` `if level not in ("L1","L2","L3","L4")` |
| `scoring.py:18 LEVEL_RANKS` | ✅ 精确命中 | `scoring.py:18` `{"L1":1,"L2":2,"L3":3,"L4":4}` |
| `delivery_packages.required_level` | ✅ 存在 | `dispatch/models.py:40`（DeliveryPackage） |
| `system_configuration.py level_score_map` L1–L4→40/60/80/100 | ✅ 存在 | `system_configuration.py:79`；快照键登记 `dispatch/rules.py:25 REQUIRED_SNAPSHOT_KEYS` |
| `agents/models.py AgentRun.fallback_level` L0–L3 | ✅ 存在 | `agents/models.py:65`（agent_runs）；CHECK 四值 |
| `agents/service.py:1111` 用 `fallback_level == "L1"` 判 handoff 准入 | ✅ 存在（行号微漂 1113） | `handoff_run` 定义于 `service.py:1102`；`l1_completed = run.status == "completed" and run.fallback_level == "L1"`（:1113） |
| `meetings/service.py:1326` 同理 | ✅ 精确命中 | `meetings/service.py:1326` |
| `dispatch/settlements.py::seat_shares_for` 四席位实算 | ✅ 存在 | `settlements.py:59` |
| `delivery_settlements` 表（r2 建） | ✅ 存在 | `dispatch/models.py:388` |
| `dispatch_rule_versions`（权重唯一来源=版本表） | ✅ 存在 | `dispatch/models.py:353`；`disputes` = `:449` |
| `delivery_packages` / `dispatch_offers` / `package_access` | ✅ 存在 | `dispatch/models.py:40` / `:158` / `:202` |
| 权益四字段 `training_entitlement` / `subscription_entitlement` / `certification_status` / `delivery_eligibility` 零命中 | ✅ 零命中确认 | `server/src` + `desktop/src` 全库 grep 无结果 |

**结论：任务书 §2 表格全部属实，无幽灵条目。**

## §C `level`（交付能力等级）依赖全集与测试影响面（G0 必做项 3a）

### C.1 交付能力等级族（衡量**人**、越大越资深——ADR-001 保护对象）

| 文件 | 依赖内容 |
|---|---|
| `dispatch/models.py` | `FdeProfile.level` 列 + CHECK；`delivery_packages.required_level` |
| `dispatch/profiles.py` | `LEVELS`、`_DELIVERY_COUNTS`、晋级校验 |
| `dispatch/scoring.py` | `LEVEL_RANKS` 撮合打分 |
| `dispatch/matching.py` | `derive_required_level` / `override_required_level`（值域闸 ：59） |
| `dispatch/packages.py` / `dispatch/routes.py` | 包准入与路由序列化 |
| `dispatch/rules.py` | `REQUIRED_SNAPSHOT_KEYS` 含 `level_score_map`（规则快照） |
| `dispatch/simulator.py` | 撮合模拟器投影 `level_score_map` |
| `system_configuration.py` | `level_score_map` 常量（:79） |

### C.2 同名异义「level 家族」补充登记（任务书 §0.4 四套之外，ADR-001 一并区分）

| 名称 | 载体 | 主语 | 语义 |
|---|---|---|---|
| **AI 访问档位** `required_level` / `access_level` / `AI_ACCESS_LEVELS` | `control/models.py:13`、`agents/models.py:248/262`、`agents/signoff.py:56`、`solutions/service.py`（checkpoint 双闸） | 用户/检查点 | disabled→assistant_read→project_operator→project_manager→system_operator 五档权限阶梯 |
| **催款级别** `DUNNING_LEVELS` | `projects/payment_service.py:46` | 收款台账 | D+7/15/30/60 催款升级刻度 |

这两者均**不用 L 前缀枚举值**，与四套 L 无冲突，但同名 `level`，R 系命名落地时在注释/文档中一并避开。

### C.3 测试影响面

- `server/tests` 中含 L1–L4 字面量的文件：**19 个**（`grep -rlE '"L[1-4]"' server/tests`）。
- dispatch 域测试文件 **16 个**（test_dispatch_p0…p2_r10 全系）。
- `level_score_map` 快照钉：`test_dispatch_admin_rules.py`、`test_dispatch_p2_r7.py`、`test_dispatch_p2_r10_c7.py`。
- 等级推导/人工覆盖：`test_dispatch_p0_r2.py`（derive/override_required_level）、`test_dispatch_p1_r5.py`。
- 桌面引用 L 等级的组件：`dispatch/ConsolePage.tsx`、`dispatch/DisputesPage.tsx`、`solutions/SignoffConsole.tsx`。

## §D `fallback_level`（降级链状态）使用点全集（G0 必做项 3b）

- 服务端（5 文件）：`agents/models.py`（列+CHECK）、`agents/service.py`（`_mark_l2` :414 写入；handoff 准入 :1113 判定；`handoff_run` :1102）、`meetings/service.py`（:1326 判定）、`solutions/service.py`（:152/:627 序列化进方案）、`workflows/executor.py`（:1187 透传）。
- 桌面（3 组件 + 2 测试文件）：`AgentsConsole.tsx`、`solutions/types.ts`、`SolutionDetailPage.tsx`；`agents-console.test.tsx`、`solution-provenance.test.tsx`。
- 测试引用：server/tests **26 处 / 10 文件**（与任务书 §0.4 断言逐位吻合）。
- **裁决输入：不可删、不可改语义**（驱动 handoff 准入 + 前端「降级链 Lx」展示 + 方案 provenance）。

## §E users / projects 权限模型与复用点（G0 必做项 4、5）

### E.1 `users` 表与角色现状

- `auth/models.py:80` `class User`，`__tablename__ = "users"`（:81）。
- **`users.role` 已存在**（String(32) not null），值域 `VALID_ROLES = frozenset({admin, project_lead, fde_engineer, viewer})`（auth/models.py:13–18），赋值校验 :129，越域抛 `InvalidRoleError`。
- 消费面：`auth/permissions.py:1 ROLE_RANK`（权限阶梯比较）、`control/access.py:43 DEFAULT_ACCESS_BY_ROLE`（AI 档位默认映射）、JWT `tokens.py:16` 携带 role。
- **关键判断：`users.role` 是平台权限角色，与商业角色分层 R1–R4 正交**——复用/扩展该列会把商业分层混入权限阶梯（ROLE_RANK/DEFAULT_ACCESS_BY_ROLE 全链受污染），详见 ADR-001。

### E.2 注册面现状（G2/G6 关键缺口）

- **无自助注册端点**：`auth/routes.py` 无 register；建号唯一入口 `POST /api/v1/users`（`users/routes.py:50`）挂 `@require_role("admin")`。
- 活库 users 仅 3 行，全 admin。
- ⇒ 四类注册入口（企业/创业者/交付者/区域）目前**全部不存在**，G2/G6 需新增带主体判定的注册流。

### E.3 projects 权限模型（复用点）

- `ProjectMember`：`workbench/models.py:326`，`role` String(20) default `"member"`。
- 复用入口：`projects/service.py:481 add_project_member` + `projects/routes.py:434` 路由。
- 活库：projects 4 行、project_members 4 行（全 member）。
- ⇒ G6 企业空间可按任务书 §3 优先复用此模型；本线不新建平行权限体系。

## §F 既有商业化能力盘点（G0 必做项 2 扩展——任务书未列但存在）

| 能力 | 位置 | 活库行数 | 对本线的意义 |
|---|---|---|---|
| P4 报价/收款/合同 | `workbench/models.py:643 quotes` / `:753 payments` / `:801 contracts`；桌面 `CommercialBoard.tsx` + `commercial-board.test.tsx` + `scripts/commercial-smoke.py` | quotes=1 / payments=3 / contracts=0 | G3 科目层的外键指回对象（报价/合同锚点已存在） |
| 结项交付包 | `handover/models.py` handover_packages / handover_package_items | 0 | G1 交付者「首个付费项目交付完成并验收」的结项态锚点 |
| 交付模拟训练场（V3.2） | `simulation/models.py`：scenarios / runs / actors / traces / evaluations / findings / improvement_proposals / regression_suites / regression_results | runs=0 | G1「认证挂模拟考核」与 G2 创业者模拟体验的既有底座（**红线：模拟表无 project_id，本线消费时遵守 V3.2 边界**） |
| 交付方案/任务分解（V3.1 P0-3） | `plans/models.py` delivery_plans / plan_items / task_links | 0 | 免费诊断六项交付物中「建议实施方案」的生成底座 |
| 质量三表（V3.1 P1-2） | `quality/models.py` test_plans / test_cases / test_executions | — | 与本线无直接交叠 |
| 访谈→事实→需求（V3.1 P0-1） | `discovery/models.py` extraction / business_facts / requirements / requirement_sources | 0 | 企业诊断事实链底座 |
| 前置调研/免费诊断 | `guidance/`（presurvey、G3 前置闸 `_require_s3_gate` 两处调用 `guidance/service.py:42`/`:64`——任务书所记 `:402` 系旧基线锚点，已随 T-A2 脱敏代码插入漂移） | gates 18 行 | G2「六项交付物完成判据」的判定落点 |
| 派单全家桶 | `dispatch/` 8 表 + 撮合/评分/结算/争议 | **全 0**（packages/offers/settlements/disputes=0） | 结构完备但从未真实使用——G1 席位激活、G3 科目结算的复用对象 |

**结论：本线所有「新增」判定均有据**——training/quota/lead/partner/subscription/entitlement/enterprise 七类概念全库无模块（`server/src/fde_api/` 现有 41 包逐一核对），复用面如上表。

## §G 口径七项现测（G0 必做项 6；口径=引用前现测）

| 项 | 现测值 | 测量方法 |
|---|---|---|
| 业务表 | **128** | `grep -rh "__tablename__" server/src/fde_api --include=*.py` 去重计数 |
| 迁移 | **49 个 revision，head `d5a8c2f4b7e1`** | revision 集 − down_revision 集（双格式兼容提取） |
| 蓝图路由 | **384** | 装饰器计数 `@x.(get|post|put|patch|delete)(`（蓝图定义 grep 计 47，含非注册定义，仅作参考） |
| api_catalog ENTRIES | **94** | `control/api_catalog.py` 中 `    ("` 行计数 |
| mypy 基线 | **279 行** | `wc -l server/mypy-baseline.txt`（权威闸=scripts/check-python-types.py） |
| 服务端 pytest | **2333 passed + 6 skipped（=2339 collected）** | CI main run **42461768715**（#214，2026-11-08）server-tests job log 实测 |
| 桌面 vitest | **951 passed（81 文件）** | 同 run desktop job log 实测 |

> 教训 48 履行：pytest/vitest 只认 CI 实测，不预写本地推算值。

## §H 智能化现状实测（G0 必做项 7；§0.5 要求用实测数据替代口述）

活库只读查询（api 容器内经应用自身配置连接，全部 SELECT；2026-11-08）：

| 指标 | 实测 | 结论 |
|---|---|---|
| `agent_runs` 总数 / 按 status×fallback_level 分布 | **0 行** | 降级链分布：无样本 |
| `handoff_user_id` 非空（人工接管频次） | **0 行**；`agent_run_handoff` 事件 0 条 | 人工接管：无样本 |
| AI 草稿采纳率（接受/修改/拒绝） | **无承载事件**：solutions=0、content/document 类 operation_events=0、signoff 事件=0 | `insufficient_data`（采纳率埋点本身也是缺口，见 gap-register） |
| Gate 人工审核 | gates 18 行：6 passed / 12 pending；decision 数组空 | 唯一非零治理数据；通过率 6/18 但含种子/示例行，不作效率结论 |
| `ai_call_audits` | 1 行（purpose=NULL） | AI 调用近乎零 |
| workflow_runs / simulation_runs / fde_profiles / discovery / plans | 全 0 | 派单与执行域从未真实使用 |
| users / projects / members | 3 admin / 4 projects / 4 member | 无付费角色样本 |

**G0 判定：**
1. 业务方口述「约 L3」**无实测支撑**——按任务书 §0.5，**书面评级维持 L2+（强 L2，向 L3 演进中，BP v4.0 §1.3a 口径）**；「交付智能化等级」衡量**平台**、越大越自动化。
2. 自动化水平实测数据 `insufficient_data`（样本=0）⇒ **G1–G6 所有关键流转（权益变更、额度扣减、席位激活、商机归属确认、区域升级）按「默认需人工确认」实现**（ADR-007 方向，§0.5 三条硬约束直接生效）；人工接管路径沿 `handoff_run` 的 `handoff_user_id` + signoff checkpoint + 事件模式，不建第二套。
3. AI 草稿采纳率**缺埋点**：当前无「接受/修改/拒绝」事件承载——列入 gap-register（G2 诊断完成判据需要它，首批真实 run 后在评估复审轮补测）。
4. `fallback_level` 分布无样本——仅作降级链现状字段保留，**不得**据其推断智能化等级。

## §I 与 V3.1 并行线交叠核对（任务书 §3）

| 交叠点 | 现测结论 |
|---|---|
| 迁移编号 | 本线开工 head `d5a8c2f4b7e1`（49 rev）；后续 G1+ 新迁移自其顺延，开工前必须 fetch 对齐 |
| `fde_profiles.level` | 本线零触碰（ADR-001 保护）；V3.1 若涉等级语义以 ADR-001 为准 |
| 企业侧数据 | 复用 `projects` 权限模型（`add_project_member` :481）；V3.1 P0-1 discovery 表按项目组织，不冲突 |
| 权限与审计 | 写操作审计沿 `operation_events` 单一事件体系（workbench/models.py:892），不新建 |
| 前端 | 本线页面优先改已有页面；桌面改动按 AGENTS.md 重打包挂账，本期不交付 |
| V3.2 模拟场 | `simulation/` 表**无 project_id** 是 V3.2 红线；本线消费模拟考核结果时只读引用，不改其结构 |

## §J G0 未做与移交后续 Goal 的事项

- ADR-004（免费额度主体认定）、ADR-005（区域商业化闸）、ADR-007（人工确认默认）分别归 G2 / G5 / G1 阶段在其设计轮内成文——G0 只出四个歧义 ADR（ADR-001/002/003/006），不预支后续阶段裁决。
- 任务书 §17 外部输入清单（法务/业务数值）维持待外部状态，本审计不代填。
