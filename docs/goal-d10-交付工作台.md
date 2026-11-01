# goal-d10 · 交付工作台升级轮次报告（2026-11-01）

## 〇、只读预检

- fork/main = `1e9b059`（goal-d9 squash 合并点），本地 main 停留 `755e429`（ff 顺延，主树并发会话 6 M + ?? 未提交改动原样未碰）。
- 隔离 worktree：`D:\test\fde-workbench-d10`（feat/goal-d10 @ 1e9b059，unset-upstream，junction node_modules/server/.venv，.env/server/.env 已拷）。
- 预调研在 worktree 真实基线完成（主树文件系统停在 r3 时代，不可作依据）。

## 一、能力项差距（P3 收口 + M10 联动 + 试点前准备）

| # | 差距 | 现状 | 验收判据 |
|---|---|---|---|
| A | **翻译草稿「采纳流」**：ready 草稿升格为项目 guidance 版本 | d9 草稿是只读个人席位资产，与项目维度零关联 | `POST /translator/translations/{id}/adopt`（body: project_id）全闸矩阵（401/403/404/409 非 ready/409 重复/400）+ 新 guidance 版本逐字段=原草稿 + api_catalog 收编 |
| B | **O-3 翻译器额度计量随路落**（d9 决议④挂账） | 翻译时无项目维度（seat_action_ledger.project_id NOT NULL），零计量 | 采纳动作落 `action_type='translation'` 台账行（ref_id=translation_id，seat=采纳发起人，over_quota 只标注不拦截）；`GET /agents/quota` 消耗数含翻译采纳 |
| C | **草稿人工编辑/逐条确认落点**（台账节三十四 #2） | ready 草稿在 `#/translator` 只读；确认动作无落点 | 采纳后编辑/逐条确认/确认走项目侧 GuidanceReview 既有 PATCH+confirm（零新建）；门户 ready 卡新增「采纳到项目」入口 + 项目下拉 + 采纳成功跳转提示 |
| D | **M10 评审会产出作为 Stage A/B 闸门证据引用**（PartyMode §8 M10 / 台账节三十二 #2） | promote_user 的 source_uri 只验非空——纪要无法作为等级证据被可信引用 | source_uri 支持 `workbench-minutes:<meeting_id>`：服务端校验纪要存在（存在即已封存）+ source_sha256 必须等于 sealed_sha256（指纹一致，不可伪造）；等级是 Stage A A1 门数据源——证据链收编纪要即联动达成 |
| E | **试点前人工联调钉定准备**（台账节三十三 #8） | 真实 iptables 生效性 + 沙箱镜像 zcode CLI 钉定从未演练 | 交付《试点前联调检查单》（iptables 断言步骤 + zcode CLI 冒烟 + 通过判据），真实执行仍人工（显式交接） |

### 不做边界（本轮显式不做）

- 门户侧草稿独立编辑器（编辑/确认统一收敛在项目侧 GuidanceReview——一份指引一处编辑权）。
- 跨项目采纳限制（草稿是个人席位资产，可采纳到多个项目；同项目数据库级防重复）。
- artifacts reviewed 在拍板 approved 时的翻转（台账 #5 待拍板）；provider kimi 化（#3 待拍板）；export-sow×signoff 强制关系（#4 待拍板）。
- 真实 iptables/zcode CLI 执行（人工项，本轮只出检查单）。

## 二、设计决议

1. **采纳 = 升格 ProjectGuidanceAnalysis 新版本**（非并入既有版本、非另立表）：version_number 取 max+1，`source_kind='translator_draft'`（新列，CheckConstraint 双值）+ `translation_id` 软链（新列，(project_id, translation_id) 唯一约束——数据库级防双击）；source_file_id/source_file_version_id 放宽 nullable（迁移；翻译器无源文件）；source_filename 存 `translator:<translation_id>`（NOT NULL 不放宽，可读可追溯）；analysis_state='ready'、status='draft'（确认仍走人工）。同一草稿可采纳多项目（个人资产语义），同项目唯一。
2. **O-3 额度随采纳落账**：`action_type='translation'` 新枚举（模型 CheckConstraint + quota.ACTION_TYPES 同步放宽）；计 1 unit、ref_id=translation_id、seat=采纳发起人。翻译 worker 就绪时无项目维度不计——采纳时刻项目上下文齐备，随路落。over_quota 只标注不拦截红线保持。
3. **confirm_analysis 的翻译器来源隔离**：source_kind='translator_draft' 的版本确认时**跳过 ProjectPresurveySource 指针回写与旧源 deprecate**（预调研源指针绝不被翻译器假源污染——否则确认动作会把项目预调研源指向不存在的文件击穿 NOT NULL）；serialize 对 translator 来源 `source_is_stale=False`（无源文件概念无从过期）+ 透出 source_kind/translation_id。
4. **M10 = 等级证据链收编工作台纪要**：`workbench-minutes:<meeting_id>` 形态经服务端校验（ReviewMeetingMinutes by meeting_id 存在——模型层 sealed NOT NULL + char_length=64 check 钉死「存在即已封存」；source_sha256 必须 == sealed_sha256）。非该前缀的 source_uri 行为零变化。

## 三、验证判据

| 判据 | 门 |
|---|---|
| adopt 全闸 + 内容展开 + 事件 + 额度落账 | pytest 定向 |
| confirm translator 版本不动 presurvey source | 钉子用例 |
| M10 三态（成功/指纹不合 422/纪要不存在 422）+ 普通 uri 回归 | pytest 定向 |
| 迁移双跑干净（约束放宽+新列新约束）+ 96 表不变 | test_migrations |
| api_catalog 94（translator.adopt 收编） | catalog 断言 |
| pytest 全量 / vitest 串行全量 / ruff / mypy 基线无新增 | 全量门 |
| 变异 ≥8×8 红绿（统一循环，共用快照字节级核对） | 变异门 |

**反假绿灯四条**：变异不红先怀疑测试空洞；mock 必须按 apiRequest 解包后载荷喂；全量跑串行口径；容器验证核对镜像时间戳。

## 三·五、实施变更清单（实测）

- **迁移 1**：`a1d3f5b7c9e2`（21 revision，down_revision=c5e9b3d7a1f5）——project_guidance_analyses +source_kind（CheckConstraint 双值）+translation_id（(project_id,translation_id) 唯一）+source_file 双列放宽 nullable；seat_action_ledger.action_type CheckConstraint 放宽 +'translation'。**96 业务表不变**（零新表）。
- **服务端**：guidance/service.py +adopt_translator_draft（闸序=翻译记录 owner/admin→项目 can_manage→ready→唯一；O-3 record_action 随路落；事件 translator_draft_adopted）+confirm_analysis 翻译器来源隔离（决议③守卫兼 mypy 收窄）+serialize_analysis 透出 source_kind/translation_id/source_is_stale；translator/routes.py +POST /translations/{id}/adopt（+GuidanceServiceError errorhandler）；agents/quota.py ACTION_TYPES +translation；dispatch/profiles.py promote_user +workbench-minutes:<meeting_id> 证据形态（存在性+sealed_sha256 指纹一致，事件 evidence_form/minutes_id）；control/api_catalog.py +translator.adopt（**93→94**）。
- **桌面**：TranslatorPortalPage.tsx +AdoptionSection（项目下拉/采纳按钮/成功提示跳项目/错误码中文映射）+ **extractTranslationId 潜伏解包 bug 修复**（决议⑤家族漏网：apiRequest 已解包再取 .data → 线上提交后轮询永不发起、AI 草稿卡不出现；单测 mock 喂信封假绿——本轮修复+mock 适配解包后载荷）。
- **文档件**：docs/试点前联调-iptables与zcodeCLI-检查单.md（人工项显式交接，证据红线口径）。
- 行为变更：guidance 序列化新增三键（source_kind/translation_id/source_is_stale 语义对 translator 来源翻转）；confirm 事件 +source_kind 键；promote 事件 +evidence_form/minutes_id 键。既有测试零适配（纯增量）。

## 三·六、验证（全部本包实测）

| 项 | 结果 |
|---|---|
| pytest | **1684 收集 = 1678 passed / 6 skipped / 0 failed**（fork/main 实测基线 1672 收集；+12=adopt 9+M10 3；全量正规口径） |
| vitest / typecheck | **722/722 全绿**（60 文件，`npm test` 串行；+1 adopt 用例 + 2 处信封→解包适配）；typecheck 零错误 |
| ruff / mypy | src+tests All checks passed（CI 口径 F401/F841）；基线门 OK（baseline 289 / current 279 无新增；nullable 收窄守卫顺带修复 mypy 真新增 2 条） |
| 迁移 | head `a1d3f5b7c9e2` 真库 down→up→down→up 双跑干净；96 表不变 |
| 变异闭环 | **8×8 红绿**（ready 翻转/owner 闸 or 翻转/ledger 类型/决议③分支翻转/纪要存在闸/指纹闸/adopt 请求体/解包回退钉子）；统一循环 apply→red→restore→verify，每步 restore 字节级 IDENTICAL；首轮红判定解析误报修正后全循环重跑（变异本体无一 NOT-RED） |

## 四、遗留与下轮建议

### 挂账（新登记，台账节三十五）

| # | 事项 | 时点 |
|---|---|---|
| 1 | 采纳后草稿在 `#/translator` 门户的「已采纳到项目」状态透出（当前靠 guidance 侧 translation_id 反查；门户列表无采纳标注） | P3 下一增量 |
| 2 | 试点联调检查单真实执行（iptables 生效性 6 步 + zcode CLI 钉定 4 步）——**人工项**，检查单已交付 | 试点前（蔡工） |
| 3 | 评审会纪要证据的桌面透出：CapabilityProfilesPage 晋级表单对 `workbench-minutes:<id>` 形态的提示与纪要选择器（当前纯 API 能力，桌面无入口提示） | 终审流细化 |
| 4 | presurvey_docx 来源缺源文件的 409 guidance_source_missing 无 UI 文案映射（异常路径，桌面显示通用错误） | 低优 |

### 下轮建议（goal-d11）

- **P4 起**：SOW 导出与终审拍板联动（待蔡工拍板 export-sow×signoff 关系后落地）；artifacts reviewed 翻转语义（同待拍板）。
- **试点包**：T6 + checkpoint 桌面页 + pilot-report 桌面页 + 插件能力登记种子（承前挂账）——试点数据回流的前置。
- **「创业者独立闭环 ≥90%」指标**：adopt 流已通，数据开始积累；试点后复盘 O-8 阈值。
- D10 待拍板项顺延：S 编号映射/九卡原句/报价卡数值禁区/G3 会闸关系/审定流程 + provider kimi 化 + export-sow×signoff + reviewed 翻转。
