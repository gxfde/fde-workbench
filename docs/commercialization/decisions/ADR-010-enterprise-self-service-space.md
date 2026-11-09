# ADR-010：企业空间与企业自助交付——自助注册、同一主体两状态、三档人工分流与不可取消的付费选择

- **状态：** Accepted（G6 裁决，2026-11-09；主体认定口径沿 ADR-004 待法务最终确认——任务书 §17-3，裁决可推翻）
- **消解：** 任务书 §10 G6（对应 T-06、T-08）；ADR-004 §3 挂账三件（注册面收集 USCC 必填／体验上限消费接线〔本轮裁定见 §3-3〕／三档分流人工判定留痕）
- **基线：** fork/main `212b5fb`（G5 收口态）

## 1. 裁决

1. **四类注册入口＝R1–R4 一一对应，齐备性由机器闸钉住**：`REGISTRATION_ENTRIES` 注册表键集恒等于 `COMMERCIAL_ROLES`（R1 企业／R2 创业者／R3 交付者／R4 区域合作商）——R1 企业自助注册＝本轮新增（`POST /api/v1/commercial/enterprise-registrations`，当事人自证）；R2/R3＝G2 `FREE_TRIAL_ENTRIES`（founder／deliverer）；R4＝G5 区域合作商申请（当事人自证）。读面：`GET /api/v1/commercial/free-diagnosis-profile` 增 `registration_entries` 节；测试双向钉（键集↔注册表↔体验入口注册表）。

2. **企业自助注册＝当事人自证形态**（G5 城市观察伙伴申请同款）：一个事务四件事要么全成要么全败——①账号（`users.role='viewer'` 最低平台权限档；密码当事人自选 ⇒ `must_change_password=False`；`register_self_service_user` 原语，无 admin actor）＋②身份分层（`CommercialEntitlement.commercial_role='R1'`，G1 结构复用，正交于平台权限角色）＋③主体与免费额度（`normalize_subject_key` USCC mod-31 必填校验；`problem_description` 业务问题描述注册必填 ≤2000 字）＋④事件留痕（actor＝当事人本人，无密码落事件）。**同主体幂等**：主体已存在 ⇒ 新账号照常可建（企业其他经办人），额度**绝不新建、绝不重置**（ADR-004 §1.2 硬不变量穿透自助路径；首次登记的 `problem_description` 不被后来者覆盖）。

3. **ADR-004 §1.2「授予=admin+密码」的边界澄清（非推翻）**：该 admin 闸守的是 **staff 发起的授予动作**；自助注册的授予是当事人自证动作，其防滥用不靠 admin 门，靠**结构性保证**——USCC 一主体一份额度（库层主键兜底）＋免费边界七项不免费硬编码＋G3 完成判据六项全真+企业确认。admin 授予路由原样保留（招商先行录入场景）。**自助注册面公开无鉴权**是任务书验收（「企业可独立注册……无需经招商人员」）的直接要求；对外暴露部署的注册面节流（复用 #250 登录限流模式加 fail-open/fail-closed 开关）挂后续轮，本期以内网部署假设交付（ADR-007 高风险写口径不变：升级/开闸/结算类仍双闸）。

4. **「企业客户」与「企业自助用户」＝同一主体（USCC subject_key）两种状态，派生不落列**：企业空间读面输出 `engagement_state`——`self_service`（默认）／`paid_delivery`（存在未被取代的付费选项选择行）。**派生值不是账**：科目层 `commercial_revenue_ledger` 零触碰、不新增任何计费名目或金额结构——「不另立第三套计费口径」的结构性表达；两状态共享同一企业空间（同一 subject_key 的读面），不存在第二套主体模型。

5. **三档分流＝人工判定留痕，系统零判定**：`enterprise_triage_decisions` 表——`tier` ∈ G2 `DIAGNOSIS_PROJECT_TIERS` 键闭集（**单一权威，零另立枚举**）、`decided_by/at`、`rationale` 必填（定性判断的人写依据 ≤2000 字）、可选书面依据（指针＋sha256，同有同无 CHECK；原件永不入库）。写路径＝admin+密码双闸（交付咨询环节＝平台顾问，当前由 admin 承载——ADR-007 形态）；**前置闸＝诊断已完成**（`diagnosis_not_completed` 409——分流发生在免费诊断之后，任务书 §10 语序）。**系统不做任何硬规则判定**：本域零阈值常量、零评分代码，判定＝人的输入不是计算输出——「无量化阈值硬编码」验收由哨兵（选项载荷无数字）＋闭集复用（G2 权威）＋模块审查共同钉住。可回看＝企业空间读面按主体列出全部判定行（谁在何时判了哪一档、依据是什么）。

6. **三个付费选项由系统呈现**：派生自 `DIAGNOSIS_PROJECT_TIERS`（标签/描述零复制——直接引用同一权威字典）＋固定跟进语常量（「由平台顾问跟进；企业自主选择，平台不代选、不取消、不改选」）。**零金额零数值**（本期不落数值红线）：哨兵用例断言选项载荷无任何数字。

7. **企业自主选择不被取消＝append-only 结构**：`enterprise_paid_option_choices` 表只增不删——①**选择动作只认绑定账号本人**（`quota.bound_user_id == actor.id`，admin 越权 403 `enterprise_choice_forbidden`；平台不代选）；②换主意＝企业本人再选（新行写旧行 `superseded_at` 留痕；部分唯一索引保证一主体至多一份现行选择）；③全仓**无删除/取消路径**（源码扫描钉：模块零 `.delete(`、企业域路由方法集 ⊆ {GET, POST}）；④平台侧唯一写面＝顾问跟进注记（admin+密码；CHECK 原子三元组 advisor_note/user/at；**只补注记、不能动 option_key/chosen_***；一选择行至多一条注记）。前置闸同分流＝诊断完成后可选。

8. **企业空间复用既有权限模型（验收③）**：①自助诊断阶段的边界＝注册/描述问题/启动绑定/确认完成/三档回看/付费选择（全部经商业自助读面，按绑定账号鉴权）；诊断内容生产仍走既有 L3 形态（AI 出草稿 → admin 登记六项 → 企业确认——ADR-004 §1.5 维持；**完全自助是长期目标，不第一天承诺**）。②付费交付项目由 staff 立项后经**既有 `add_project_member`** 把企业账号加为 `viewer` 成员（`_validate_project_member_target` 的既有角色尺：viewer 系统角色 ↔ viewer 项目成员），企业账号即经既有 `project_access` 获得项目可读——**零平行权限表**（元数据机器闸：G6 仅新增 triage/choices 两表，无 permission/acl 命名）。③企业空间读面的交付项目清单＝`projects.enterprise_code == subject.display_name`（企业代号＝项目域连接键；USCC＝额度主体键——两键并存各有用途）∩ 既有可见性。

## 2. 理由

- 当事人自证形态（G5 先例）是「无需招商人员」验收的唯一自洽落点：免费诊断的防滥用已由 ADR-004 的主体键结构承担，admin 门在自助路径上只会把验收变假。
- 分流判定与付费选择落表而非事件日志：验收要求「可留痕、可回看」的**业务对象**（企业空间读面按主体聚合回看），operation_events 是审计账不是回看面——两者并用（写路径同步落事件）。
- 付费交付态派生自选择行而非状态列：状态列会引入第二套状态机与「谁有权翻转」的新治理面；派生让「付费交付态」永远有据可查（指向哪一行选择）。
- viewer 成员＋既有角色尺：把企业账号提为 `member` 需要放宽 `_validate_project_member_target` 的角色尺（牵动所有项目成员面），本期不做——viewer 成员已满足「企业可读交付项目」的验收语义。

## 3. 后果与挂账

1. `problem_description` 列可空（兼容 G2 admin 授予的存量行）；自助注册必填——admin 授予路径不强制，存量补录走后续轮。
2. 体验上限（ADR-004 §1.8）的消费接线**本轮不落地**：founder/deliverer 体验的真实消费方在 V3.2 simulation 域（ADR-004 §1.9 已裁「不触碰」），判定原语 `check_experience_limit` 已在位；接线随 simulation 消费面立项（保持显式挂账，不假装接线）。
3. 注册面节流（#250 登录限流模式复用）挂后续轮；本期注册面仅内网部署假设。
4. 企业空间桌面呈现面（自助注册页/空间视图）挂后续桌面轮；本轮为纯服务端。
5. 多子公司集团归并（母公司 USCC 字段）仍按 ADR-004 §1.4 挂法务。
