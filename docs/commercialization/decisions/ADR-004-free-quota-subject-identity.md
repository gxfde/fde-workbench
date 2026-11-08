# ADR-004：企业免费额度主体认定——统一社会信用代码规范化键，一次一主体不重置

- **状态：** Accepted（G2 裁决，2026-11-08；**主体认定口径待法务最终确认**——任务书 §17-3，裁决可推翻）
- **消解：** 任务书 §6「企业主体判定：一次一主体、长期有效不重置。主体认定键（工商口径）须先出 ADR 并提示法务确认；多子公司是否分别体验须显式规则（本期先给保守默认：不分别）」
- **基线：** fork/main `7c32736`

## 1. 裁决

1. **主体认定键 = 统一社会信用代码（USCC）规范化**：大写、去除空格与连字符，18 位，字符集 `0-9A-HJ-NPQRTUWXY`，**校验位按 GB 32100-2015（mod-31）验证**——校验失败即 400 `invalid_subject_key`（防手误造成的同主体多键）。`subject_key` 为额度主键，**非用户 ID**。
2. **一次一主体、长期有效不重置**：额度行按 `subject_key` 唯一；`grant` 幂等——同主体重复授予返回既有行（`changed=false`），**绝不新建第二份**。
3. **换账号不重置**：诊断启动时绑定 `bound_user_id`（state→`in_progress`）；同主体其他账号尝试启动 → 409 `quota_bound_to_other_account`；完成（六项齐+企业确认）为终态，任何账号不可重启（无重置路径，人工亦无——重置属未来显式立项）。**并发口径同此**：启动/完成/企业确认三条写路径取额度行一律 `SELECT … FOR UPDATE` **且** `populate_existing` 刷新会话内存视图——行锁与刷新两者同时成立才等于「锁在手读必为已提交真值」；只锁不刷新会被 `expire_on_commit=False` 下会话里陈旧的实例绕过（并发下额度被重发，CR-021 同款教训）。授予路径的「绝不新建第二份」由 `subject_key` 主键在库层兜底。
4. **多子公司保守默认 = 不分别体验**：本期不建母子公司图谱；同 `subject_key` 即同主体。子公司持各自 USCC 在形式上是不同法人——保守默认的落地靠**人工闸**：额度授予/完成确认均走 admin+密码确认（高风险写），交付咨询环节人工核验集团关系（ADR-007 的「AI 出建议、人判定」形态）；法务口径到位后可在 G6 注册面加母公司 USCC 字段做结构化归并（本期不做，显式挂账）。
5. **完成判据 = 六项交付物齐备 + 企业确认**：六键闭集（diagnosis_report / process_analysis / ai_opportunity_list / implementation_plan / project_tier_budget / next_steps），服务层要求**恰好六键全真**方可标记完成，缺失点名 409 `deliverables_incomplete`；企业确认由绑定账号执行且必须发生在完成之后（DB CHECK 双保险）。诊断内容本体由既有 guidance/方案/文档流产出，本模块只承载判据账，不生成内容、不复制产物。
6. **免费边界即产品边界（代码层+文档层同时可见）**：`FREE_EXCLUSIONS` 七项常量（完整实施／真实 CRM/ERP 接入／大规模数据处理／定制 Agent／生产部署／持续运维／驻场）+ `GET /api/v1/commercial/free-diagnosis-profile` 读面公开呈现；文档层=本 ADR + 使用帮助（后续轮同步）。
7. **三档描述与解耦**：免费诊断交付物「预计项目等级与预算区间」采用三档**纯描述性**表述（standardized／multi_system／complex，对应「标准化高风险低→AI 自助候选／多业务系统→AI 辅助+企业审核／复杂流程与集成→转专业 FDE」），**不给数值区间**，命名刻意不带 T（与区域席位档 T1–T3 解耦，ADR-005 域）。
8. **两档体验上限**：创业者／交付者档各两数值（模拟运行数／人工指导次数），落 `EXPERIENCE_LIMITS` 可配置结构 + 保守缺省值并**标注「试点前须填实数」**（占位缺省非业务拍板数，`EXPERIENCE_LIMITS_PLACEHOLDER=True`）；`check_experience_limit(kind, resource, used)` 触限即 409 `experience_limit_exceeded`（`used >= cap` 即受限）。**上限按资源分别计数**——`simulation_runs` 与 `mentor_sessions` 是两个独立计数器，签名必须带 `resource`，不得用同一 `used` 同时比所有资源上限（否则一档的上限会误伤另一档的计数）；消费接线随 G6 三入口（显式挂账，本模块先落结构+判定原语）。
9. **三入口隔离＝入口注册表 + 域闸（结构性声明）**：`FREE_TRIAL_ENTRIES` 三条——`enterprise`（真实业务问题，`scope=real_business`，须主体键，额度按主体计）／`founder`（模拟体验，`scope=simulation`）／`deliverer`（脱敏模拟项目考核，`scope=sanitized_simulation`）；`assert_entry_scope_allows(entry, scope)` 是域闸——**非企业入口取用 `real_business` 即 403 `trial_entry_scope_forbidden`**（任务书 §6 验收「创业者不能取到企业真实商机」的结构性保证；注册表与域闸同在读面 `GET /api/v1/commercial/free-diagnosis-profile` 可见）。**边界**：本 ADR 只保证「三入口的数据域隔离声明与闸」，**商机归属、渠道保护与真实商机可见性的实现本体归 G4**（T-09）；本轮不建商机侧读面。


## 2. 理由

- USCC 是工商口径唯一稳定键（企业名可改、可重名）；mod-31 校验位是公开国家标准，本地可验证，杜绝「同一主体多键」的主要来源（录入误差）。
- 额度键挂主体而非账号，是「换账号不重置」的结构性保证——按账号计的实现会在本 ADR 的反例用例上转红（G2 测试含该变异用例，任务书 §6 验收）。
- 人工闸（授予/完成 admin+密码确认）承接**交付智能化等级**（平台，越大越自动化，BP §1.3a）的 **L3** 形态：系统可出建议与草稿，分级与豁免的判定权在人（任务书 §0.5 三条硬约束之一）。

## 3. 后果与挂账

- G6 注册面落地时收集 USCC 成为必填（本期服务原语已按必填校验）；法务确认后如口径变化（如需集团归并键），改 `normalize_subject_key` 单点即可。
- 体验上限的消费接线、三档分流的人工判定留痕均归 G6（本模块只落结构、常量与判定原语，不触碰 V3.2 simulation 域）。
- 校验位算法若法务口径要求放宽（如境外主体无 USCC），另立裁决修订本 ADR。
