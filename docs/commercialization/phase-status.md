# 商业化阶段状态（按 Goal 轮次累积）

- 权威基线：**fork/main**——G0 合并 `28f55fd`（#216）／G1 合并 `f186342`（#217）；G2 合并 `b0fd5fc`（#228）／G3 合并 `f65f874`（#234）／G4 合并 `ffed2e2`（#241）／**G5 在途（`feat/commercial-g5-regional-partners`，基线 `2538a02`）**
- 工作树：`D:\test\fde-wt-g1`
- 当前阶段：**G5 区域合作商能力建设（T-12a，任务书 §9）— 实施完成，PR→CI→合并→部署闭环进行中**
- 阶段纪律：**一个 Goal 只做一个阶段，不跳阶段**；每阶段按任务书 §14 总提示词逐项回报（SHA/分支/阶段、改动文件、迁移、API·权限·目录、前端、测试命令与通过·失败·跳过数、安全·兼容·回滚、验收证据、遗留、下一阶段是否可开）

---

## G5：区域合作商能力建设（T-12a，不含 T-12b）— 实施完成（闭环收口中）

- 分支：`feat/commercial-g5-regional-partners`（工作树 `D:\test\fde-wt-g1`）
- 基线 SHA：fork/main `2538a02`（G4 收口态）
- 状态：**implemented**（本节终值——PR 编号／CI run／部署活体断言——在合并收口 PR 回填）

### 目标

任务书 §9：建区域阶梯的**内部能力**，同时**不具备**对外收费签约能力（本期不做 T-12b）；四阶段可区分、前两阶段无独家权、城市服务伙伴按项目结算无固定年费、**售卖能力默认关闭**且开关绑定合规条件清单。

### 设计决策及理由（含 ADR 编号）

- **ADR-005**（`decisions/ADR-005-regional-commercialization-gate.md`，G5 成文）十项裁决：①四阶段闭集（city_observer/city_service/formal_partner/regional_agent），阶段注记读面派生；②**售卖开关单行默认 closed**，CHECK 结构性排除缺件开门；③「无任何代码路径可在开关未开启时对外收费签约」＝结构性保证（`require_sale_gate_open` 唯一闸门 + formal_partner 写点唯一源码扫描钉）；④合规条件四项**登记 ≠ 开启**（登记后仍 closed，开启须独立双闸动作）；⑤前两阶段不授予独家区域权（CHECK＋服务层双封）；⑥区域代理「暂不启用」＝**无写路径**（409 `regional_agent_not_enabled`），不是禁用状态列；⑦城市服务按项目结算引用既有 G3 `project_share` 科目行（不建第二套结算），正式档不得写按项目结算（两档收费形态互斥）；⑧试运营升级指标与首期金额**本期不定数**（哨兵钉死示例数值不落码）；⑨三档定价以 **BP v4.0 为唯一基准**（迁移播种＋代码 `REGIONAL_TIER_SEED` 同源）；⑩真实身份材料零入库（伙伴代号＋指针＋sha256）。
- 成文规则唯一处：`docs/commercialization/rules/regional-partner-program-rules.md`（§2 四阶段／§3 开关与合规清单／§4 三档定价＋机器可读块）；机器闸＝规则文件 JSON 块 ↔ 代码常量 ↔ 迁移种子**三方逐位一致**。

### 修改文件

```text
新增：
  docs/commercialization/rules/regional-partner-program-rules.md           （NEW：成文规则唯一处＋机器可读块）
  docs/commercialization/decisions/ADR-005-regional-commercialization-gate.md
  server/src/fde_api/commercial/regional_service.py                        （NEW：售卖闸＋四阶段＋按项目结算原语）
  server/migrations/versions/b3e8a6c2d4f7_commercial_g5_regional_partners.py
  server/tests/test_commercial_regional_partners.py                        （NEW：31 例）
修改：
  server/src/fde_api/commercial/models.py                                  （+4 表 + 常量）
  server/src/fde_api/commercial/routes.py                                  （+4 读/自证路由）
  server/src/fde_api/commercial/admin_routes.py                            （+5 治理写路由）
  server/tests/conftest.py                                                 （清理序：G5 四表先于 G4 两表）
  server/tests/test_migrations.py                                          （HEAD_REVISION b3e8a6c2d4f7 + 全集 56）
  docs/audit/v3-{route,database}-inventory.csv + v3-workbench-inventory.json（重生成：436/49/143/56）
  docs/architecture/archify-diagrams/architecture/{candidate.json,system-architecture.html,preview.png}
  AGENTS.md / CHANGELOG.md / docs/commercialization/phase-status.md（本节）
```

### 数据库迁移

迁移 `b3e8a6c2d4f7`（55→56 rev，additive 四表，单链单头）：`regional_partner_tiers`（三档定价目录，T1/T2/T3 CHECK＋金额>0＋席位形状 CHECK＋basis_reference 必填；**迁移播种三行**〔BP v4.0 基准〕）、`regional_partners`（伙伴主体：四阶段闭集＋申请自证戳＋升级书面依据三戳＋tier/exclusive；**五条 CHECK**：阶段闭集／前两阶段无独家权／观察档无升级留痕／服务档必有升级留痕／正式档须书面依据齐备；partner_code UNIQUE）、`regional_sale_gate`（**单行，播种 closed**：四条件各 uri+hash+signed_at＋开启人/时刻；三条 CHECK：状态闭集／条件原子性〔uri↔hash↔signed_at 同有同无〕／**opened ⇒ 四项齐备＋开启留痕非空**〔结构性排除缺件开门〕）、`regional_service_settlements`（一单一结关联行：FK 伙伴/项目/G3 科目行全 RESTRICT；ledger_entry_id UNIQUE 防重复计数）。**试运营数值零播种**（哨兵钉）。

### API / 权限 / API Catalog

- 读/自证面（4）：`POST /api/v1/commercial/regional-partners`（申请城市观察伙伴＝**当事人自证**，免费）、`GET /api/v1/commercial/regional-partners`（admin 全量／非 admin 只见本人）、`GET …/<id>`（含阶段注记派生——区域代理显示「暂不启用」；他人 404 不透 existence）、`GET /api/v1/commercial/regional-partner-tiers`（三档目录＋开关状态；**目录可见 ≠ 可签约**）。
- 治理写面（5，admin＋`confirm_password` 双闸）：`GET /api/v1/admin/commercial/regional-sale-gate`（开关读面：状态＋四条件登记态，只出指针）、`POST …/regional-sale-gate/conditions/<key>`（登记签署证据，**登记 ≠ 开启**）、`POST …/regional-sale-gate/open`（**关键流转**：四项齐备才可）、`POST …/regional-partners/<id>/promote`（阶段升级；**formal_partner 第一步过售卖闸**；regional_agent 显式拒绝）、`POST …/regional-partners/<id>/settlements`（按项目结算，引用 G3 科目行）。
- **全部不进 api_catalog**（商业治理面，AI 不可调用）——ENTRIES **94** 不变。

### 前端变化

无（纯服务端轮，桌面便携版不重打包；商业化桌面呈现面挂后续轮）。

### 测试命令与结果

- `pytest tests/test_commercial_regional_partners.py -q` → **31 passed**。
- 全量 `pytest -q -n 4 --dist loadfile`（**CI 同命令**）→ **2596 收集 = 2590 passed + 6 skipped，0 failed**（EXIT=0 / 16m13s；rebase 融合上游 #246/#247/#250/#249/#252/#254/#253 七笔（pytest 增量仅前三笔 +7／+12／+3，余四笔纯桌面或纯文档零 pytest 增量）；G4 基线 2543 收集 + V31-P1c +7 + N1 首跑补码 +12 + #250 +3 + 本轮 +31 ＝ 2596）。
- **PR CI server-tests 实测在途——合并后由收口 PR 回填（终值以本 PR CI server-tests 实测为准）**。
- `python scripts/check-python-types.py` → **OK：baseline 279 occurrences / 104 distinct，current 279**（本轮回退零新增；实施期两处 Optional 收窄当场归零）。
- `ruff check`（全部改动文件）→ All checks passed。
- **变异五连全转红→还原→绿**（字节级备份还原，sha256 终验一致）：M1 售卖闸直通（`require_sale_gate_open` 摘 closed 判定→正式档反例红）／M2 缺件开门（`open_sale_gate` 摘四项齐备校验→缺件用例红）／M3 区域代理放行（摘显式拒绝→不可进入用例红）／M4 前两阶段独家放行（摘 `exclusive_not_allowed`→独家拒绝用例红）／M5 结算张冠李戴放行（摘 `ledger_project_mismatch`→跨项目结算用例红；**首版变异 `False and X or Y` 运算符优先级让判定意外存活——加括号全判失效后转红**〔变异本身也要验真〕）。

### 安全检查

- 对外收费签约唯一闸门＝`require_sale_gate_open`（闸关 409 `regional_sale_gate_closed`，不回落不绕行）；源码扫描钉把「formal_partner 写点唯一且在过闸函数内」机械化（`test_no_signing_path_bypasses_gate_source_scan`）。
- 开闸/升级/条件登记/结算＝admin 门＋`confirm_password` 双闸（ADR-007 §2.1）；逐动作 `operation_events` 留痕（带 request_id，**密码不落事件**）。
- 申请城市观察伙伴＝当事人自证（免费，不走 admin 门）。
- 合规条件证据只存 `source_uri` 指针＋`content_hash` sha256 指纹＋签署时刻；伙伴真实身份材料零入库（只登伙伴代号＋区域名）。
- 「两店一年」是客观时间门槛，不可提前（其证据行即 qualification 条件；不预设「本模式是否构成特许经营」的法律结论——须律师意见）。
- 未读取无关密钥；`server/.env` 未入库；本轮零生产变更。

### 数据兼容与回滚

- additive 四表，**零既有表改列**（G4 两表/G3 科目层零触碰；opportunities 行零影响）。
- 回滚＝`alembic downgrade e7b2c4d9f1a3`（child-first：settlements → gate → partners → tiers）＋回滚镜像。
- 闸关闭态下区域模块读面/申请/升级（观察→服务）行为与既有商业面零交互；派单/项目/结算回归绿（ledger 26 例＋channel_guard 13 例＋G4 商机 23 例＋迁移全量 28 例）。

### 验收证据（任务书 §9 逐条）

| 验收项 | 证据 |
|---|---|
| 售卖能力默认关闭＋无代码路径可在开关未开启时对外收费签约（≥1 断言用例） | `test_gate_default_closed_lazy_seeded`＋`test_formal_partner_blocked_while_gate_closed`（409 `regional_sale_gate_closed`，含跳级路径）＋**源码扫描钉** `test_no_signing_path_bypasses_gate_source_scan`；变异 M1/M2 转红 |
| 四阶段与「暂不启用」标注正确落库 | `test_rule_document_slots_match_code_bidirectionally`（闭集双向闸＋agent.enabled=false＋note「暂不启用」）＋`test_regional_agent_is_not_enterable`（409）＋读面派生注记；变异 M3 转红 |
| 城市服务伙伴按项目结算，无固定年费 | `test_city_service_per_project_settlement`（一单一结＋重复 409）＋`test_tier_catalog_has_no_city_service_row`（目录只收 T1/T2/T3）＋`test_settlement_rejected_for_formal_stage`（两档互斥）＋`test_settlement_requires_matching_project`（张冠李戴 409）；变异 M5 转红 |
| 前两阶段不授予独家区域权 | `test_exclusive_territory_rejected_for_first_two_stages`（409）＋`test_db_check_first_two_stages_no_exclusive`（DB CHECK 在位）；变异 M4 转红 |
| 三档定价以 v4.0 为唯一基准 | `test_tier_seed_matches_rule_document`（文档块 ↔ `REGIONAL_TIER_SEED` ↔ 库行三方逐位）＋basis_reference 必填 CHECK |
| 试运营指标与首期金额本期不定数 | `test_trial_upgrade_metrics_unset`（规则槽显式 unset）＋`test_trial_example_numbers_absent_from_g5_code`（哨兵：示例数值不落 G5 域代码与迁移，数字边界正则防误伤档位金额） |
| 合规条件清单四项（备案/披露/冷静期/两店一年） | `test_opening_requires_all_four_conditions`（缺一 409 `gate_condition_missing`）＋`test_gate_opens_after_all_conditions`（齐备开闸＋重复开闸/开启后改条件 409）＋CHECK `ck_regional_sale_gate_opened_complete` |
| 高风险写双闸＋事件无密码 | `test_gate_condition_registration_requires_admin_and_password`＋`test_promotion_requires_evidence_and_admin_password`＋`test_gate_events_recorded_without_password`＋`test_promotion_event_carries_stage_transition` |
| 读面权限 | `test_partner_read_scopes`（本人/admin/他人 404/列表隔离）＋`test_partner_read_requires_auth`（401）＋`test_tier_catalog_visible_with_gate_status` |
| 治理面不进 api_catalog | `test_governance_face_not_in_api_catalog`＋路由审计 CSV（ENTRIES 94 不变） |
| 新增服务端逻辑有测试 | NEW `test_commercial_regional_partners.py` **31 例**＋变异五连全红→还原→绿 |

### 遗留问题

1. **T-12b（对外收费签约）本期不做**——闸关闭＋无签约服务原语；放行前置＝合规条件清单四项签署＋律师意见（「本模式是否构成特许经营」），留独立轮次。
2. 试运营升级指标与首期金额**待业务拍板**（任务书 §17 数值类）——配置槽显式 unset，成文后填实无需改结构。
3. 区域商业化桌面呈现面（伙伴列表/开关面板）挂后续桌面轮；GAP-15（AI 草稿采纳率埋点）与 ADR-004 §1.4 多子公司集团归并仍开放。

### 部署活体验证（合并后）

（收口 PR 回填：三镜像 rebuild 自本工作树＋alembic upgrade head → b3e8a6c2d4f7＋活体断言）

### 是否允许进入下一阶段

**允许进入 G6（企业空间与企业自助交付 T-06/T-08，任务书 §10）**——前置回填：PR 四绿＋合并态 main run 四绿＋部署活体绿。

---

## G4：商机归属与渠道保护（T-09）— 已完成

- 分支：`feat/commercial-g4-opportunity-attribution`（工作树 `D:\test\fde-wt-g1`）
- 基线 SHA：fork/main `9497b2c`（开工时）；合并前**两轮 rebase** 融合上游三笔——#240（AI 原生化 N2，迁移 `c4f7a2d9e1b6` 53→54 rev，+10 测试）、#239（V3.2 G9b 真机两闸轮，+4 测试）、#235（V31-P1b 大纪要分段抽取，+52 测试，零迁移零路由）⇒ 本轮迁移改挂 `c4f7a2d9e1b6` 之后，**55 rev 单链单头 `e7b2c4d9f1a3`**
- 状态：**completed**（PR #241 squash 合并 `ffed2e2`；PR run **42581664828** 四绿 ＋ **main run 42583246694 四绿**；**部署活体绿**——三镜像 rebuild 自本工作树 ＋ `alembic upgrade head` `c4f7a2d9e1b6`→`e7b2c4d9f1a3`，收口 PR：`feat/commercial-g4-closeout`）

### 目标

任务书 §8：立「报备→确认→保护→撮合→结算」七步链路，**规则数值本期不定数**（可配置结构＋缺省「未配置」，不留硬编码默认值）；已确认归属的商机企业后续直接注册**不得简单转移**；保护期**不得变成永久锁定企业**。

### 设计决策及理由（含 ADR 编号）

- **ADR-009**（`decisions/ADR-009-opportunity-attribution-and-channel-protection.md`，G4 成文）十项裁决：①七步状态机**引用既有** dispatch 交付包（⑥撮合）与 G3 科目层 `project_share` 行（⑦结算），不建第二套撮合/结算；②五个规则配置位（保护期长度／续期条件／客户自主选择权／争议处理机制／归属判定）迁移播种 **unset**＋机器闸（成文规则文件机器可读槽位块 ↔ 代码常量双向相等）；③保护期**三态可区分**（`unconfigured`/`active`/`expired`）且 `active` 必有到期时刻（CHECK 结构性排除永久锁定）；④保护期直签封堵＝**既有 `channel_guard` H1–H3 的扩展钩子**（惰性：无商机即 no-op／失败放行：查询异常不阻断立项／只认存储态 active 且未到期）；⑤归属不因企业自行注册而转移＝**结构性保证**（企业侧立项路径无商机行写路径）＋反例用例；⑥归属确认＝admin＋密码（关键流转），报备/撤回＝当事人自证（R2），企业确认＝admin＋线下书面依据（指针＋指纹）；⑦规则未配置 ⇒ **fail-closed**（409 `rule_not_configured`，不回落任何默认值）；⑧客户自主选择**不改归属**；⑨争议期间链路冻结（撮合/售前/结算 409 `opportunity_disputed`），争议处理机制未成文不可发起；⑩真实资料零入库（只登企业代号，材料只存指针＋sha256 指纹）。
- 成文规则唯一处：`docs/commercialization/rules/opportunity-attribution-rules.md`（§2 七步链路／§3 保护期三态／§8 配置位对照表＋机器可读槽位块）；承接 **ADR-007**（双闸与自证动作）与 G1 角色分层（报备人＝R2 创业者）。

### 修改文件

```text
新增：
  docs/commercialization/rules/opportunity-attribution-rules.md            （NEW：成文规则唯一处＋机器可读槽位块）
  docs/commercialization/decisions/ADR-009-opportunity-attribution-and-channel-protection.md
  server/src/fde_api/commercial/attribution_service.py                     （NEW：规则位＋七步链路写原语＋保护期读时派生）
  server/migrations/versions/e7b2c4d9f1a3_commercial_g4_opportunity_attribution.py
  server/tests/test_commercial_opportunity_attribution.py                  （NEW：23 例）
修改：
  server/src/fde_api/commercial/models.py                                  （+2 表 + 闭集常量）
  server/src/fde_api/commercial/routes.py                                  （+4 读/自证路由）
  server/src/fde_api/commercial/admin_routes.py                            （+12 治理写路由）
  server/src/fde_api/dispatch/channel_guard.py                             （+商机保护期直签封堵钩子，H1–H3 语义不变）
  server/tests/conftest.py                                                 （清理序：G4 两表先于 G3 五表/派单簇/users）
  server/tests/test_migrations.py                                          （HEAD_REVISION + 全集断言 54→55）
  docs/audit/v3-{route,database}-inventory.csv + v3-workbench-inventory.json（重生成）
  docs/architecture/archify-diagrams/architecture/*                        （口径数字同步 + preview 重出）
  AGENTS.md / CHANGELOG.md / docs/commercialization/phase-status.md（本节）
```

### 数据库迁移

迁移 `e7b2c4d9f1a3`（54→55 rev，additive 两表，单链单头）：`commercial_opportunity_rules`（五配置位：`protection_period_days`/`renewal_conditions`/`customer_choice`/`dispute_handling`/`attribution_criteria`；**迁移播种为 unset**，status ∈ unset/configured，days 与 criteria 互斥形状 CHECK）、`commercial_opportunities`（商机主体：status 八态闭集＋归属三戳（owner/by/at＋uri/hash）＋保护期五列（status/started/expires/renewal_count/renewed_at）＋撮合/客户选择/结算三引用（FK delivery_packages / commercial_revenue_ledger）＋争议/撤回留痕；**六条 CHECK**：状态闭集／保护期闭集／归属形状（owner⇔confirmed_at）／阶段需归属（presales·matched·settled ⇒ owner）／保护期窗口（active ⇒ started AND expires）／到期晚于起算）。rules 表先行（opportunities 的 rule 快照虽为 JSON 不引用，但 down 线 child-first 可逆）。

### API / 权限 / API Catalog

- 读/自证面（4）：`POST /api/v1/commercial/opportunities`（报备＝**R2 当事人自证**）、`GET /api/v1/commercial/opportunities`（admin 全量／本人只见报备·归属·售前相关）、`GET /api/v1/commercial/opportunities/<id>`（含保护期**派生态**与「企业是否已自助注册」**派生事实**）、`POST /api/v1/commercial/opportunities/<id>/withdraw`（报备人自证，settled 不可撤回）。
- 治理写面（12，admin＋`confirm_password` 双闸）：`GET/POST /api/v1/admin/commercial/opportunity-rules[/<key>]`（规则位读＋配置/清空，须书面依据）、`POST …/opportunities/<id>/enterprise-confirm`（企业确认，代录线下书面答复）、`/attribution`（归属确认）、`/attribution/reassign`（改派，**被 `attribution_criteria` 闸 fail-closed**）、`/protection`（设定保护期，长度取 `protection_period_days` 配置位）、`/protection/renew`（续期，被 `renewal_conditions` 闸）、`/presales`（售前，默认归属人）、`/match`（撮合，交付包须同企业代号）、`/customer-choice`（客户自主选择，被 `customer_choice` 闸、**不改归属**）、`/settlement`（结算，须引用 `project_share` 科目行且未作废）、`/dispute`（发起争议，被 `dispute_handling` 闸、争议中链路冻结）。
- **全部不进 api_catalog**（商业治理面，AI 不可调用）——ENTRIES **94** 不变。

### 前端变化

无（纯服务端轮，桌面便携版不重打包；商业化桌面呈现面挂后续轮）。

### 测试命令与结果

- `pytest tests/test_commercial_opportunity_attribution.py -q` → **23 passed**。
- 全量 `pytest -q -n 4 --dist loadfile`（**CI 同命令**）→ **2543 收集 = 2537 passed + 6 skipped，0 failed**（EXIT=0 / 8m39s；G3 轮基线 2454 收集 + AI 原生化 N2 +10 + #239 +4 + #235 +52 + 本轮 +23 ＝ 2543）。
- **PR CI server-tests 实测**（run 42581664828）：**2537 passed + 6 skipped**（522.82s）；**main run 收口**（合并态 `ffed2e2`，run 42583246694）：**2537 passed + 6 skipped**（568.87s）——与本地 CI 同命令实测逐位一致；desktop 82 文件 **966 passed**（见口径行 vitest 校正注记）。
- `python scripts/check-python-types.py` → **OK：baseline 279 occurrences / 104 distinct，current 279**（实施期补一处测试断言形状〔re.search Optional 收窄〕后归零，无新增）。
- `ruff check`（全部改动文件）→ All checks passed。
- **变异五连全转红→还原→绿**（字节级备份还原，sha256 终验一致）：M1 归属不自动易主失效（企业注册派生事实恒 False→反例用例红）／M2 保护期未配置也封堵（守卫放宽为任意非 revoked 态＋绕过到期派生→反例用例红）／M3 规则未配置仍放行（`require_rule_configured` 直通→规则闸用例红）／M4 争议不冻结（`_reject_when_disputed` 摘除→争议冻结用例红）／M5 归属可静默改写（`attribution_already_confirmed` 摘除→防改写用例红）。

### 安全检查

- 关键流转（企业确认/归属确认/改派/保护期/续期/售前/撮合/客户选择/结算/争议/规则配置）＝admin 门＋`confirm_password` 双闸（ADR-007 §2.1）；逐动作 `operation_events` 留痕（带 request_id，**密码不落事件**）。
- 报备/撤回＝当事人自证（ADR-007 §2.4；报备仅 R2）；撤回**不动归属事实**（审计可回查）。
- 证据只存 `source_uri` 指针＋`content_hash` sha256 指纹；真实企业名/联系人/凭证零入库（只登企业代号）。
- 归属改写无旁路：再确认 409 `attribution_already_confirmed`；转移唯一路径 `reassign` 且被 `attribution_criteria` 规则闸 fail-closed（本期不可用＝**本期无转移路径**）。
- 企业侧立项路径**无商机行写路径**（结构性保证）；保护期直签封堵**失败放行**（渠道秩序诉求，不是资金安全闸）；派单线（H1–H3）语义零变化。
- 未读取无关密钥；`server/.env` 未入库；本轮零生产变更。

### 数据兼容与回滚

- additive 两表，**零既有表改列**（`delivery_settlements` 列集合逐位比对，结构钉）。
- 回滚＝`alembic downgrade c4f7a2d9e1b6`（子表先行：opportunities → rules）＋回滚镜像。
- 保护期判定惰性（库内无商机行时行为逐位不变）；G1–G3 商业面与派单回归绿（commercial+dispatch+projects 组合 154 例通过）。

### 验收证据（任务书 §8 逐条）

| 验收项 | 证据 |
|---|---|
| 七步链路完整（§2 七步） | `test_seven_step_chain_completes`（报备→企业确认→归属→保护期→售前→撮合→结算全链 200）＋ `test_step_order_is_enforced`（跳步 409 `invalid_opportunity_state`） |
| 「归属确认后企业自行注册，商机不自动易主」反例 ≥1 | `test_attribution_not_transferred_when_enterprise_registers_directly`（保护期未配置 ⇒ 企业可直签立项；归属人/确认戳/状态/保护期逐项不变＋`enterprise_registered` 派生事实可见）；变异 M1/M2 转红 |
| 保护期为空＝「未配置」且三态可区分 | `test_protection_three_states_are_distinguishable`（unconfigured→直签放行／active→封堵／backdate 到期→读时派生 expired→放行）＋ `test_protection_status_values_are_closed` |
| 保护期 active 封堵直签立项（渠道保护落点） | `test_active_protection_blocks_direct_project_creation`（422 `opportunity_protection_active`＋审计事件 `opportunity_protection_blocked`）；直签封堵不得变永久锁定（CHECK active⇒expires） |
| 规则文件与代码配置位一一对应 | `test_rule_document_slots_match_code_bidirectionally`（机器可读槽位块 ↔ `OPPORTUNITY_RULE_KEYS`/`VALUE_KINDS` 双向相等＋库行全 unset）＋ `test_rule_slots_are_unset_by_default` |
| 规则数值不定数、无硬编码默认值 | 五配置位迁移播种 unset＋`test_actions_gated_by_unconfigured_rules`（续期/客户选择/争议/改派 409 `rule_not_configured`）；变异 M3 转红 |
| 规则配置须书面依据 | `test_rule_configuration_requires_evidence`（缺 URI/指纹 400；配置后动作放行见 `test_actions_enabled_after_rules_configured`） |
| 客户自主选择不改归属 | `test_actions_enabled_after_rules_configured`（选择生效且归属人不变；另证续期计数＋改派显式留痕） |
| 撮合不张冠李戴／结算引用既有分账 | `test_match_requires_same_enterprise_package`（409 `package_enterprise_mismatch`）＋ `test_settlement_requires_project_share_entry`（409 `ledger_subject_mismatch`） |
| 争议期间链路冻结 | `test_dispute_freezes_downstream_steps`（409 `opportunity_disputed`）；变异 M4 转红 |
| 归属人工确认、不得静默改写 | `test_attribution_cannot_be_silently_overwritten`（409 `attribution_already_confirmed`）；变异 M5 转红 |
| 报备＝R2；治理写双闸；事件无密码 | `test_report_requires_r2_role`＋`test_admin_actions_require_admin_and_password`＋`test_attribution_event_recorded_without_password` |
| 读面权限 | `test_read_scope_and_permissions`（本人／admin 全量／他人 403／未认证 401）＋ `test_withdraw_only_by_reporter` |
| 治理面不进 api_catalog | `test_governance_face_not_in_api_catalog`＋路由审计 CSV（ENTRIES 94 不变） |
| 新增服务端逻辑有测试 | NEW `test_commercial_opportunity_attribution.py` **23 例**＋变异五连全红→还原→绿 |

### 遗留问题

1. 五个规则位**数值仍待业务拍板**（任务书 §17 数值类）：保护期长度／续期条件／客户自主选择权／争议处理机制／归属判定——配置结构＋成文规则文件已就位，附书面依据配置即生效，无需改结构。
2. 商机保护期封堵提示文案与派单池内判定的先后语序，随数值拍板一并复核。
3. GAP-15（AI 草稿采纳率埋点）仍开放；ADR-004 §1.4 多子公司集团归并仍待法务。

### 部署活体验证（合并后）

- 三镜像 rebuild 自本工作树干净树＋`docker compose up -d --force-recreate`；容器内 `alembic upgrade head` 实跑 `c4f7a2d9e1b6 -> e7b2c4d9f1a3`，`alembic current` ＝ **`e7b2c4d9f1a3 (head)`**。
- **活体断言三项全绿**：①容器内 `create_app` url_map **428** 条（commercial **43**／admin commercial **27**／opportunity 14＋12，蓝图 **49**）与本轮口径一致；②容器 `alembic current` ＝ 本轮 head `e7b2c4d9f1a3`；③api/worker/scheduler 三容器镜像 ID ＝ 本工作树构建产物（`c7fba822aef1…`／`649da2c7ab3b…`／`113dbf0c0e4a…`，container==image）。
- 活库断言：G4 两表结构正确（opportunities 34 列/6 CHECK；rules 11 列/5 CHECK），五规则槽全 **unset**，`commercial_opportunities` **0 行**，`delivery_settlements` 仍 20 列（零既有表改列）；`/api/v1/health/ready` 200 ＋ `/live` 200，四容器 healthy。

### 是否允许进入下一阶段

**允许进入 G5（区域合作商能力建设 T-12a，**不含 T-12b**，任务书 §9）**——前置已全部满足：PR #241 四绿（run 42581664828）＋合并态 main run 四绿（run 42583246694）＋部署活体绿（见上节）。
T-12b（对外收费签约）本期不做：售卖能力默认关闭、开关绑定合规条件清单（《商业特许经营管理条例》七/八/十二/二十一条＋披露办法第四条四项）；「两直营店经营满 1 年」为客观时间门槛不可提前。

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
- **并发覆盖复验（跨会话共享部署）**：部署后约 30 分钟，另一条线的会话从自己的 worktree 重建并 `up -d`，把 api 容器换成了**旧代码**（活体 `url_map` 掉回 398、commercial 掉回 13 条、容器内 `alembic current` 报 「Can't locate revision」、`/app/migrations` 挂载指向别人的 worktree）。**处置**：从本工作树重建三镜像 （api 镜像 ID `84193bb29335`）＋ `up -d --force-recreate` 三容器 → **复验全绿**（`url_map` 412／commercial 27／`alembic current` ＝ `d5f9a3c7e1b4 (head)`／容器 working_dir 与 migrations 挂载均回本工作树／三容器 healthy／ready+live 200）。**教训**：镜像 tag 与 migrations 挂载源是跨会话共享资源，部署后必须复验「活体路由数 ＋ 容器内 alembic current ＋ 容器镜像 ID」三项（已写入 AGENTS「工作流与陷阱」节）。

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
