# goal-crv-fix2 进度台账（剩余修复批次总循环）

- **工作树**：`D:/test/fde-wt-crv2`
- **任务书**：`docs/goal-crv-fix2-剩余批次总循环-任务书.md`
- **基线参照**：`docs/audit/全面代码审查报告-2026-11-13.md`（v1.0，基点 `35ffbea`）＋`docs/goal-crv-BLOCKED.md` §5 拍板

| 轮次 | 批次 | 覆盖范围 | 状态 | PR / SHA | 变异红→绿记录 |
|---|---|---|---|---|---|
| r1 | 批 A | `QR-001` / `QR-002` / `QR-003` / `QR-004` + `QR-018` | 已合并 | `#444` / `a8a2c25c` | 7 组全红→字节级还原核 sha256→25 passed |
| r2 | 批 C | `QR-041` / `QR-042` / `QR-043` / `QR-044` | 已合并 | `#451` / `f4cb5e9f` | 7 组全红→字节级还原核 sha256→4 passed + 168 邻域绿 |
| r3 | 批 D | `QR-055` / `QR-056`+`059` / `QR-057` / `QR-067` + 单步迁移 `d4b8e1f6a9c3` | 已合并 | `#456` / `b11b8b3f` | 5 组全红→字节级还原核 sha256→4 passed + 300 邻域绿 |
| r4 | 批 E | `QR-071` / `QR-072` + `QR-073`/宿主通道核销 | 已验待合并 | `#462` / `1df421bd`（rebase `d8a98ed0`） | 3 组全红→字节级还原核 sha256→5 passed + 213 邻域绿 |
| r5 | 批 G | `QR-133` / `QR-134` | 已合并 | `#463` / `3fc7ddb6` | 3 组全红→字节级还原核 sha256→10 passed + 97 邻域绿 |
| r6 | 批 R7 | `QR-109` / `QR-110` / `QR-111` / `QR-112` / `QR-113` + 便携版 r49 | 已合并 | `#466` / `b65f9167` | 3 组全红→字节级还原核 sha256→54 passed（3 文件）+1217 全量绿 |
| r7 | 收口与部署 | 总报告销号节 + `BLOCKED`/`PROGRESS` + `AGENTS` bullet + 活体部署三验 | 已验待合并 | 待填 | 活体三验见 r7 节 |

---

## r1 批 A（权限·身份·项目闸，零迁移零新路由）

- **合并记录**：PR `#444` → squash `a8a2c25c`（4 个必需 CI job 全绿）。
- **修复明细**：
  1. `QR-001`（`server/src/fde_api/auth/routes.py::_login_fail_key`）：登录失败计数与清零键改调 `normalize_username(username)`（NFKC + strip + lower），大小写/全角/首尾空白变体共享同一限流桶。
  2. `QR-002`（`server/src/fde_api/auth/service.py::change_password` + `registration/service.py`）：`change_password` 在旧密验证后补 `_registration_state_gate(current_user)`，拦截 `suspended` / `rejected` / `pending_email` 改密换发新令牌对；`suspend_registration` 与 `review_registration(decision="reject")` 递增 `user.auth_version += 1` 使存量 15min JWT 立即 401 失效，同时保留 `/auth/refresh` 返回 `403 account_suspended` / `registration_rejected` 契约。
  3. `QR-003`（`server/src/fde_api/control/api_actions.py::_authorized`）：新增 `_target_project_id` 兼容 `agents.run_start` 的 `body.project_id`，将 `_require_run_start_scope_binding` 并入 `_authorized` 单点（propose 与 confirm 双侧必经），消除路径无 `{project_id}` 致先 403 死代码。
  4. `QR-004` + `QR-018`（`server/src/fde_api/projects/service.py::update_project` + `projects/quote_service.py::create_quote`）：PATCH `enterprise_code` 发生实质变更时复跑 `ensure_enterprise_channel`（H2 池内企业 / G4 商机保护期均拦 422）；`create_quote` 改为先 `for_update=True` 锁定并 `populate_existing` 重读 `Project` 后再跑 `ensure_enterprise_channel`；`projects/service.py` 1943 行 ≤ 1946 热点上限。
- **测试与变异证据**：NEW `server/tests/test_crv_batch_a.py`（9 例）+ `test_ai_run_proposal.py`（16 例）；7 组变异全红→还原 `sha256` 全绿。

---

## r2 批 C（公网写面与个保法留存期，零迁移零新路由）

- **合并记录**：PR `#451` → squash `f4cb5e9f`（4 个必需 CI job 全绿）。
- **修复明细**：
  1. `QR-041`（#1A，`server/src/fde_api/guidance/redaction.py::redact_text_detailed` + `diagnostics/service.py::capture_lead` + `diagnostics/claim_service.py::reveal_claimed_lead_contact`）：新增 `mask_pii: bool = True` 开关（默认仍掩码手机号/邮箱/固话），仅留资 `contact` 传 `mask_pii=False` 保留联系方式明文（企业名代号化与凭据 422 拦截恒在位）；受控读函数仅允许 `admin` 或已接受认领单本人读取并写 `diagnostic_lead_contact_revealed` 审计事件（事件 `changes` 零明文联系方式）。
  2. `QR-042`（#2A，`server/src/fde_api/diagnostics/service.py::_enforce_retention` + `claim_service.py` + `diagnostics/jobs.py`）：30 天 `expires_at` 读写懒检查——未认领且 `expires_at <= now` 的会话立即转 `expired` 并匿名化清空 `answers`/`assessment`/`report`/`lead_contact`/`subject_fingerprint`/`region_name`/`share_token_sha256`；续写返 `409 session_closed`、分享返 `404`、线索池排除、认领与裁定返 `409 lead_expired`、worker 跳过 AI 调用；已 `claimed` 会话保全。
  3. `QR-043`（`server/src/fde_api/registration/routes.py` + `commercial/routes.py`）：四入口注册、重发验证邮件与 legacy 企业注册三处将 `_ensure_surface_open` 移至限流器前，部署闸关闭时即使超限或 Redis 故障也恒返 **404 `not_found`**。
  4. `QR-044`（`server/src/fde_api/diagnostics/claim_service.py::get_claim` + `lead_routes.py`）：补 `ensure_enabled()` 与 `admin` / `claimant_user_id == actor.id` 归属校验，越权一律返 **404 `claim_not_found`**。
- **测试与变异证据**：NEW `server/tests/test_crv_batch_c.py`（4 组）+ 既有 168 例绿；7 组变异全红→还原 `sha256` 全绿。

---

## r3 批 D（资金商业面＋单步 Alembic 迁移 `d4b8e1f6a9c3`）

- **修复明细**：
  1. `QR-055`（`server/src/fde_api/commercial/models.py` + `commercial/service.py::activate_seat`）：`CommercialEntitlement` 增加 `CheckConstraint("seat_status <> 'active' OR seat_expires_at IS NOT NULL", name="ck_commercial_entitlements_active_requires_expiry")`，`activate_seat` 服务层必填 `expires_at`（缺失返 `400 invalid_request`）；换代 9 份商业/多租户测试夹具补显式 `expires_at`。
  2. `QR-056` + `QR-059`（`server/src/fde_api/commercial/attribution_service.py::record_settlement` + `commercial/models.py`）：对 `CommercialRevenueLedger` 加 `with_for_update()` 锁；`entry.delivery_package_id` 或 `row.matched_delivery_package_id` 缺失或不等一律返 `409 ledger_package_mismatch`（对齐 `regional_service.py`）；同一笔 `project_share` 科目行不可被多条商机重复引用结算（服务层返 `409 ledger_already_settled` + DB 部分唯一索引 `uq_commercial_opportunities_settled_ledger` 兜底）。
  3. `QR-057`（`server/src/fde_api/commercial/models.py` + `conftest.py`）：`CommercialRoleAssignment.source_uri` 由 `String(255)` 扩为 `String(500)`（对齐服务层 `_URI_MAX = 500`），并在 `conftest.py` `cleanup_models` 补列 `CommercialRoleAssignment` 防止 RESTRICT 清理冲突。
  4. `QR-067`（#3A，`server/src/fde_api/commercial/admin_routes.py`）：`/fee-configs`、`/split-rules`、`/opportunity-rules`、`/regional-sale-gate` 四个 GET 治理读面接入 `is_platform_operator` 门禁（非平台管理操作者返 `403 commercial_admin_required`）。
  5. **单步迁移与口径同步**：新增唯一迁移 `server/migrations/versions/d4b8e1f6a9c3_commercial_batch_d_hardening.py`（接 `c8e2a6f0b9d4`，`74→75` 单头），同步 `server/tests/test_migrations.py::HEAD_REVISION` 与 `len(known) == 75`、`docs/audit/v3-workbench-inventory.json`（`check_archify_diagram_freshness.py` PASS）。
- **测试与变异证据**：
  - NEW `server/tests/test_crv_batch_d.py`（4 组）+ `test_migrations.py`（28 例）+ 商业/多租户 17 套件（272 例）= **304 passed** 全绿。
  - 变异五连（`try/finally` 字节还原核对 `sha256`）：
    - `M1_QR055_service_expires_at_required`：red=True → 还原 `sha256=bab938618d97b9d4`
    - `M2_QR056_packageless_ledger_check`：red=True → 还原 `sha256=864bf3fbbd2a820b`
    - `M3_QR059_duplicate_ledger_settlement_check`：red=True → 还原 `sha256=864bf3fbbd2a820b`
    - `M4_QR057_migration_column_width_revert`：red=True → 还原 `sha256=41ad63b871bc363a`
    - `M5_QR067_platform_operator_read_gate`：red=True → 还原 `sha256=9eb8dffe7cf0ca70`
    - 还原终验：`4 passed`；`ruff` 0 告警；`check-python-types.py` `277 occurrences / 102 distinct` 零新增。
  - **合并记录**：PR `#456` → squash `b11b8b3f`（4 个必需 CI job 全绿，run 43471375645）。

---

## r4 批 E（编排执行域，零迁移零新路由）

- **修复明细**：
  1. `QR-071`（续 CR-028，`server/src/fde_api/dispatch/packages.py::transition_package` + `dispatch/settlements.py`）：published 态 `seat_delivery=None` 生成的 draft 结算行在四条路径同步回填 `seat_delivery_user_id`——①接单（accept 分支扫 draft 行回填）；②`allocate_five_seats`（分配即落 `seat_payees["delivery"]`，空缺席位恒 None）；③`record_receipt_settlements` 刷新（行空且包已在位时回填）；④`accrue_settlements_for_project` 兜底（行空时经 `DispatchSettlementAllocation` paid 明细解析 → `package.seat_delivery` → `accepted_user_id` 逐级回退并持久化）。保证当期预扣税非零且同自然年后续里程碑把已计提行计入 `past_rows` 累计预扣递进基数。
  2. `QR-072`（`workflows/compiler.py` + `seeds/workflow-templates.json` + `workflows/definition_service.py` + `workflows/dispatch.py`）：①`compile_delivery_preview` 与种子模板 `plan_execution` 的 `solutions.create` 节点补 `params.project_id="{{project_id}}"` 并把骨架字段包进 `params.body`（对齐 api_catalog 路由契约）；②`validate_dag` 新增 `call_contracts` 注入（`catalog_call_contracts()` 由 CATALOG 派生 `{method, path_params}`），定义期拦截缺路径必填参数（`call_missing_path_param`）、`body` 非对象（`call_invalid_body`）、写操作字段散落顶层（`call_unwrapped_body_params`）——三类均 422 `dag_invalid`；③`_dispatch_skill` 把 skill JSON 输出的字典字段（剔除 `text`）透出节点上下文，下游 `{{research_brief.opportunity_ids}}` 引用可达；`test_delivery_compiler.py` 期望结构同步换代。
  3. `QR-073` 及宿主通道核销：`is_unsafe_artifact_path` 三形态钉（POSIX 绝对／`..` 穿越／Windows 盘符·反斜杠根·UNC）+ `#422`（`QR-088/089`：`claim_host_run` `with_for_update`＋`frozen_tools`）与 `#433`（`QR-092` env 白名单继承＋密钥拒绝清单；`QR-094` done 终态 break；`QR-095` exit_code fail-closed）在位核验，写核销记录不重复造例。
  4. **附带真缺陷收口**（QR-095 家族延展）：`host_receipt.py` exit_code 原判 `isinstance(raw_exit, int)` 未排 `bool`——Python 中 `isinstance(False, int) is True` 且 `False == 0`，宿主回执传 `"exit_code": false` 会误判成功。补 `not isinstance(raw_exit, bool)` 排除（fail-closed 语义补全）。
- **测试与变异证据**：
  - NEW `server/tests/test_crv_batch_e.py`（5 例：QR-071 主链同月跨档累计预扣递进／QR-071 辅链五席位分配＋accrue 兜底回填／QR-072 定义期契约闸三码＋种子模板全集过闸／QR-072 端到端 compile→definition→publish→run 真实落库 `ProjectSolution` 停于 `waiting_approval`／QR-073 三形态＋吸收项核销）；`test_delivery_compiler.py` 期望结构换代。
  - 邻域回归 14 套件 **213 passed**（workflows 全家＋dispatch P0-R2/P1-R5＋five_seat＋T6 票税＋host_poll＋host_agent＋architecture_purity＋source_size_budgets）。
  - 变异三连（`try/finally` 字节还原核对 `sha256`）：
    - `M1_QR071_accept_backfill`：red=True → 还原 `sha256=a21bd969090cda0e…` MATCH
    - `M2_QR072_definition_gate`：red=True → 还原 `sha256=3601e0db6dc904ff…` MATCH
    - `M3_QR072_compiler_contract`：red=True → 还原 `sha256=4eee24050b9082bb…` MATCH
    - 还原终验：`5 passed`；`ruff` 0 告警；`check-python-types.py` `277 occurrences / 102 distinct` 零新增。

---

## r5 批 G（脱敏事件账指纹化＋编辑复扫，零迁移零新路由）

- **修复明细**：
  1. `QR-133`（#6A 拍板 A 指纹化复核清单，`guidance/redaction.py` 单一真身 + 4 锚写入侧 + 读侧）：`redaction_review` 事件账零真名——NEW `redaction_name_hash`（域分隔 `fde-redaction-v1:{name}` sha256）与 `fingerprint_review_entries`（确证命中→`{"name_hash","occurrences","matched_dict":True}`；疑似→不入条目账只留聚合计数 `suspect_count`）；写入侧四锚接线（`guidance/jobs.py::_write_redaction_event`、`translator/service.py::create_translation` input 阶段、`translator/jobs.py` output 阶段、采纳流 `_merge_carried_changes` 指纹形状原样搬运）；读侧 NEW `resolve_redaction_display`（词典反解：命中显示词目原文、未命中 `name=None` 软失败不 500）＋ `_review_projection`（条目按 name_hash 排序＋疑似计数项殿后）；`_split_review_events` 兼容历史 name 形状事件（现算指纹归一、matched=False 折算计数——投影语义统一零真名）；confirm 复核闸与 `redaction_review_hits` 口径同步换代。
  2. `QR-134`（#7A 拍板 A 豁免登记＋编辑复扫，`guidance/service.py::update_analysis`）：保存时输出端复扫三文本字段＋LIST_FIELDS 列表 str 值——词典确证命中 422 `redaction_name_detected` fail-closed（错误消息不回显命中原文）；疑似名替换为代号放行＋`manual_edit` 复核事件（仅聚合计数）；`RedactionConfigError` 422 `pseudonym_dict_unavailable` 同码、`SensitiveCredentialDetected` 422 同闸；presurvey 录入卡维持零脱敏豁免（用户自填自述≠AI 加工面），豁免与指纹化语义一并登记 `AGENTS.md` 独立 bullet。
- **测试与变异证据**：
  - NEW `server/tests/test_crv_batch_g.py`（10 例：指纹形状单一真身／反解命中与未命中软失败／worker 全链事件账 JSON 序列化零真名＋指纹在场＋suspect_count 在场／投影聚合（指纹条目+计数项）／历史 name 形状兼容归一／update_analysis 词典命中 422 不回显原文／列表字段命中即拒／疑似替换放行＋manual_edit 计数事件零真名／干净编辑零事件／凭据串 422 同闸）；旧钉换代 4 文件（`test_guidance_redaction_worker.py` 事件账零真名断言、`test_translator_redaction.py` 3 处事件断言＋投影断言、`test_guidance_confirm_review_gate.py` 4 处投影断言、`test_guidance_retry.py` CR-051 防翻倍断言指纹化）。
  - 邻域回归 12 套件 **97 passed**（guidance/translator 全家）；`test_guidance_retry.py::test_unexpected_failure_keeps_the_background_job_green` 1 例红经 **stash 基线验证为既有失败**（#455 合并后 no_handler，非批 G 改动面，不越界修）。
  - 变异三连（`try/finally` 字节还原核对 `sha256`）：
    - `M1_QR133_fingerprint_bypass`：red=True → 还原 `sha256=c5344296bf926715…` MATCH
    - `M2_QR134_dict_hit_reject`：red=True → 还原 `sha256=e7e6dbb4431d42a2…` MATCH
    - `M3_QR133_suspect_count`：red=True → 还原 `sha256=0989639f4b32d5d7…` MATCH
    - 还原终验：`10 passed`；`ruff` 0 告警；`check-python-types.py` `277 occurrences / 102 distinct` 零新增。

---

## r6 批 R7（桌面五项＋便携版 r49，零服务端改动零迁移零路由）

- **修复明细**：
  1. `QR-109`（`desktop/src/main/index.ts`）：主窗口 `hardenWebContents` 补 `will-redirect` 同尺守卫（30x 重定向不走 will-navigate；此前特权更高的主窗口只有半边，lcsc 分支成对注册）。
  2. `QR-110`（同文件）：`desktop-execute` 桥拦截分支在 `executeDesktopLcsc` 前调 `requireLcscEnabled()`——`lcscIpcEnabled`「默认关」闸此前只护 3/4 个 LCSC 面（flag=false 经 API 桥仍拉起自动化执行＝意图↔实现缺口）；声明提升至 `registerApiIpc` 之前（TDZ 安全），4 处 LCSC 面共用同一单点。
  3. `QR-111`（`lcsc-browser-ui.ts` + `lcsc-runner.ts`）：denied 名单提单一真身 `DENIED_ACTION_SOURCE`（观察面 `OBSERVE_BROWSER` 与点击前复验共用同一字面内插）；runner 点击分支执行前对目标元素当前 innerText/aria-label/title 复验同尺正则＋`closest('form')` 拦截（TOCTOU 窗口 DOM 变化或 AI 误点敏感控件即停；执行窗与手动内置浏览器共享 partition，登录态共享放大误点后果）。
  4. `QR-112`（`shared/api-safety.ts` + `main/api-ipc.ts` + `renderer/src/fde-web-bridge.ts`）：响应面四条不变量（ok∧error 拒／!ok∧¬error 拒／!ok data 置空／错误体形态校验）提双桥共用纯函数 `parseApiEnvelope`；脱敏族（`redactSensitiveString`/`sanitizeEnvelopeDetails`/`collectEnvelopeSensitiveValues`/`isSensitiveKey`）同点提升（实现逐字迁移、调用点 import 别名零改动）；web 桥四处不等价缺口全封；等价性静态钉扩响应面——NEW `tests/shared/api-envelope-samples.ts`（17 信封样本＋5 脱敏样本）双侧消费（`api-envelope-equivalence.test.ts` 桌面侧真 handler 逐样本＋`fde-web-bridge-equivalence.test.ts` web 侧镜像）。
  5. `QR-113`（`AgentsConsole.tsx`）：去顶层 `if (error) return` 整页坍缩（单件复核 PATCH 409/下载失败此前全页阻断无恢复路径），改页内错误条＋「重试」按钮（load 可重入），与 detailError/queueError 就地呈现语义一致。
  6. **便携版 r49**：RELEASE-COUNTER 对齐已声明最大轮次（45→48，r46-r48 在各自打包树 bump 未回写 fork/main）后 bump→**r49** 注入 `0.3.0-r49`；`electron-builder --win dir --x64` 产出归档主树 `release/蔡工FDE-0.3.0-便携版-r49`；**asar 正反向字节双证 ALL PASS**（六特征串——`DENIED_ACTION_SOURCE`／点击复验文案／`parseApiEnvelope`／主窗口 will-redirect 分支／desktop-execute 闸逗号表达式／`not_ok_without_error`——新 asar 全命中＋旧 r47 asar（`0ab9b017…`）全 0 命中＋版本 marker 在场）；新 asar sha256 `275313739f5dc4eb2269dfc2490df7a3f49c01e3690ac115124187a7186b76a7`。
- **测试与变异证据**：
  - NEW `tests/main/api-envelope-equivalence.test.ts`（17+6）＋`tests/main/crv-batch-r7-nails.test.ts`（8 源码锚钉：will-redirect 成对／闸调用先于 execute／TDZ 顺序／requireLcscEnabled 4 处单点／DENIED 真身双处内插／runner 复验锚／无顶层早返回／错误条+重试）＋`tests/shared/api-envelope-samples.ts`；`fde-web-bridge-equivalence.test.ts` 扩 web 镜像 17 例；旧钉换代 1 处（`fde-web-bridge.test.ts` 错误信封 stub 200→409——旧断言恰钉住缺口①旧行为「200+error 放行」，换代注记留痕）。
  - `npm run typecheck` 零错＋vitest 全量 **104 文件 1217 passed**。
  - 变异三连（`try/finally` 字节还原核对 `sha256`）：
    - `M1_QR110_gate_bypass`：red=True → 还原 `sha256=c1c455f2fdfbbf3f…` MATCH
    - `M2_QR111_recheck_bypass`：red=True → 还原 `sha256=d1e61b85fbcc5e19…` MATCH
    - `M3_QR112_ok_with_error`：red=True → 还原 `sha256=6f07a8382a88d0cd…` MATCH
    - 还原终验：3 文件 54 passed。

---

## r7 收口与部署（总报告销号节＋台账终态＋AGENTS bullet＋统一活体部署三验）

- **文档四件**：总报告 §修复销号节（v1.0 正文零改动）＋`goal-crv-BLOCKED.md` §6 拍板销号终态＋`goal-crv-PROGRESS.md` 终态行＋`AGENTS.md` 独立 bullet（轮次逆序区，未触碰超长链行）。
- **统一活体部署（2026-11-14，`takeover_check --tree fde-wt-crv2 --live` PASS 后执行）**：`compose -p fde-workbench build api worker scheduler`＋`up -d --force-recreate`＋容器内 `alembic upgrade head`（幂等 no-op——#455 部署时已升 76）。**三验实测**：①活体 `url_map` non-static **491** ≡ `v3-workbench-inventory.json` `route_count=491`；②容器内 `alembic current`＝`d4b7e2f9a6c1 (head)` ≡ inventory 单头（76 rev；批 D `d4b8e1f6a9c3` 被 #455 续接）；③三镜像 ID ≡ 本树构建（api `4e3daf1f9f09`／worker `6b5f05014f7a`／scheduler `b8013143bfea` 全 MATCH，含批 D/E/G 四处源码标记容器内实测在位）＋四容器 healthy＋`:8010/api/v1/health/{live,ready}` 200。migrations 挂载源回归本树（`/mnt/d/test/fde-wt-crv2/server/migrations`，接管前 uilib 僵尸挂载经 takeover_check 拦截后原样携带部署态 `server/.env` 修复）。
- **CHANGELOG**：delivery 节随本 PR（收口轮自身零代码零迁移）。
