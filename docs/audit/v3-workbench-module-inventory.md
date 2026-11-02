# V3 模块清单：蔡工 FDE Workbench（@0570384，分支 fde-v2）

> 自动抽取：`scripts/audit/extract_workbench_inventory.py`（url_map + Base.metadata + alembic AST）；人工核查：审计子代理（附录 C/D/F）。路由逐条见 `v3-route-inventory.csv`（repository=fde-workbench@0570384，269 行）；表逐张见 `v3-database-inventory.csv`（96 行）。

## 1. 服务端模块（server/src/fde_api，216 个 py）

| 模块 | 路由数 | 表（__tablename__） | 职责与关键符号（VERIFIED） |
|---|---|---|---|
| auth | 6 | users, roles | JWT 会话（access/refresh）、ROLE_RANK 四角色（viewer/fde_engineer/project_lead/admin）、`require_auth/require_role/require_minimum_role/require_bridge_token` 装饰器（decorators.py:52-89） |
| users | 4 | — | 用户管理 API（复用 auth 模型） |
| projects | 31 | projects, project_members, project_modules, project_tasks, sop_nodes, gates, quotes…（workbench/models.py 21 表中大部） | 项目生命周期、SOP 节点、**门禁 G1–G9**（gate_service.py：submit_gate_evidence L222 / decide_gate L313 五道闸）、任务板；权限 `project_access()`（permissions.py） |
| workbench | 1 | workbench 21 表（projects/gates/sop_nodes/module_catalog/industry_templates(+versions)/operation_events/ai_call_audits/bridge_engagements…） | 模型大本营 + 业务枚举选项下发（WP29/J1） |
| research | 23+4 | project_research_subjects / _links / _forms / _form_revisions / _answers / _personal_memos / _import_batches / _exports / project_ai_opportunity_profiles / template_research_forms/sections/fields（12 表） | 调研域五类对象、机会档案、问卷修订链（draft→confirmed/archived）、导入幂等回执；`subject_service.py`(911 行)、`form_service.py`(1130 行)、`imports.py`(1552 行) |
| guidance | 10 | project_guidance_analyses, presurvey_intakes, project_presurvey_sources | 预勘录入（S1-S2 即可填）、DOCX 分析（G3 闸 `_require_s3_gate`）、翻译草稿采纳 `adopt_translator_draft`（service.py:248）、draft→confirmed→superseded 状态机、redaction（密钥拒绝+PII 脱敏） |
| templates | 9 | （复用 workbench 模板表） | 行业模板 CRUD、AI draft（`create_ai_template_draft` 原子落库）、publish 锁版（service.py:326-330 immutable） |
| documents | 17+6 | project_documents / _versions / _drafts / document_generation_jobs / document_delivery_records / document_templates / document_template_versions（7 表） | 文档四表（身份/不可变版本链/可变草稿/生成任务）、worker 异步渲染（generator.py）、`build_document_snapshot` 冻结输入、交付记录（delivery_key 幂等） |
| solutions | 12 | project_solutions, project_solution_exports, solution_review_checkpoints(agents) | 方案（就地可变 version+=1）、AI organize（只返建议）、generate-agent（沙箱 run）、**signoff**（resolve_signoff L319：AI 档位闸+artifact 翻转）、export-sow（agent_assisted 409 闸） |
| agents | 11 | agent_registry, agent_runs, agent_artifacts, agent_tool_calls, agent_credentials, seat_action_ledger, solution_review_checkpoints（7 表） | S1 编程工作台：run 状态机（queued→…→budget_exceeded）、fallback L0-L3、`start_run` L654（预算/pilot/T1/T6/agent_assisted 全闸）、docker 沙箱（sandbox.py 345 行）、工具三重交集（tools.py:84-106） |
| ai | 10 | — | DeepSeek/Kimi 客户端、SSE 执行态（Redis）、行业模板/问卷/机会 AI 服务（**均不落库，建议制**）、ai_call_audits 写入（auditing.py） |
| control | 26+ | user_ai_access_grants, automation_tasks/_runs/_approvals, skill_definitions/versions, plugin_*(4 表), ai_provider/model_configs, ai_conversations/_chat_turns, knowledge_snapshots, weixin 2 表, model_preferences, lcsc_skills（15+ 表） | 控制平面：access 五档 CAPABILITY_REQUIREMENTS、mcp_gateway TOOLS 17、api_catalog 94、api_actions 密码确认、ai_tool_loop 降级直连（READ_ONLY 13）、automation 调度/审批、extensions/plugins、chat、scheduler、task_board、lcsc、weixin |
| jobs | — | outbox_events, background_jobs | outbox→Redis list→worker（lease 5min/续租 60s/token 守卫/reconcile 白名单 8 类）、`flask worker`/`flask scheduler` CLI |
| bridge | 5 | bridge_engagements, bridge_sync_runs | openfde ledger.db / fdeops .registry 单向投影（文件永远赢）；宿主 4h 采集（schtasks） |
| dispatch | 24 | 8 表（profiles/rules/settlements/offers/packages/cities…） | 派单撮合引擎（r1–r12）、城市终版 6 城、G8/G9 派单侧校验 |
| meetings | 10 | review_meetings, review_meeting_minutes, meeting_orchestrations | 评审会+纪要封存（T2 强制门）、t6_gate_satisfied |
| metrics | 1 | — | 只读聚合报表 |
| translator | 4 | translator_translations | 翻译门户（kimi-k3）、adopt → guidance |
| mailing | 1 | mailing_events, sns 2 表 | SES 退信/投诉回调（模块默认关闭） |
| files | 14 | project_files, file_versions, file_previews | 项目文件+版本+预览 |
| modules / storage / health / system_configuration | 3+2+2+2 | system_configuration | 模块目录、本地/对象存储、心跳、系统配置 |
| lcsc（control 内） | 4+4 | lcsc_skills | 立创商城浏览器插件（capability lcsc.browse→system_operator） |

## 2. 桌面端（desktop/src，136 ts/tsx）

- `main/`（Electron 主进程：api-ipc、集成桥调度桥接）、`preload/`、`shared/contracts`（类型契约）、`renderer/src/`：
  - `api/client.ts`：createApiClient（会话快照→transport.request→401 刷新重试一次）。
  - 页面：`projects/GateBoard.tsx`(492 行，门禁板)、`solutions/SignoffConsole.tsx`、projects/solutions/documents/research/guidance/agents/task-center/extensions/dispatch/translator/help 等（vitest 730 用例覆盖）。
- 桌面端不直连 DB；全部经 API；MCP 工具面给外部 DSH agent 用，桌面端走普通 REST。

## 3. 关键横切机制（VERIFIED，证据见附录）

| 机制 | 位置 | 语义 |
|---|---|---|
| 权限 | auth/decorators + control/access + services `project_access` | HTTP 层角色 rank；AI 层五档 capability；agent 工具=声明∩发起人∩插件；MCP token 只衰减 |
| 审计 | operation_events + ai_call_audits | 业务变更留痕（actor/changes JSON）；AI 调用审计（tokens/status/budget_blocked） |
| 异步 | outbox_events→Redis→background_jobs | 单活跃守卫（active_key 唯一生成列）、lease/token、reconcile 白名单（automation.execute 不可恢复重投） |
| 门禁 | gate_service.py | 唯一写路径；拍板人≠执行人；G8/G9 admin；evidence→终态 |
| 证据 | source_uri+sha256 指针 | 不进库不进仓（红线） |

## 4. 种子与配置

- `server/seeds/gates.json`（G1–G9 定义，239 行，sha256=180c4809…）、`seeds/agents.json`、`plugin_seeds.py`、`builtin_skills.py`。
- 版本：`desktop/package.json` 与 `server/pyproject.toml` 同步 v0.2.0（发布列车）。
