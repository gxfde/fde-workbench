# 附录 C（原始证据）：Workbench「Agent / Skill / 工具目录 / MCP Gateway / 权限审批 / AI 调用环 / 自动化异步」代码审计

> 生成方式：独立审计子代理对 `D:\test\fde-workbench`（分支 fde-v2，HEAD `0570384`）只读审计。以下为子代理报告原文。审计日期：2026-11-02。

## 一、实际读取文件清单

**control/（全读）**：`access.py`(117)、`ai_tool_loop.py`(304)、`mcp_gateway.py`(289)、`api_catalog.py`(127)、`api_actions.py`(277)、`models.py`(391)、`scheduler.py`(119)、`automation_jobs.py`(164)、`builtin_skills.py`(174)、`plugin_seeds.py`(69)；**选读**：`extensions_service.py`(L130–540)、`chat.py`(L1–230)、`ai_server_client.py`(L1–200)、`service.py`(L555–943)、`routes.py`(L189–303)、`extension_management_routes.py`(L30–110)、`file_delivery.py`(grep 段)。
**agents/（全读）**：`models.py`(246)、`service.py`(1198)、`tools.py`(110)、`adapter.py`(228)、`context.py`(194)、`pilot.py`(208)、`quota.py`(135)、`sandbox.py`(345)、`seeds.py`(82)、`routes.py`(124)。
**jobs/（全读）**：`worker.py`(194)、`outbox.py`(92)、`models.py`(102)、`handlers.py`(111)、`queue.py`(74)、`reconcile.py`(205)；另 `health/heartbeat.py`(103)、`cli.py`(worker/scheduler 循环段)。
**auth/**：`decorators.py`(139)、`permissions.py`(15)。**ai/**：`auditing.py`(110)、`deepseek.py`(L1–120)、`executions.py`(L1–90)、`routes.py`(grep)。
**workbench/models.py**：L875–939（OperationEvent、AICallAudit）。
**迁移**：`d9c3e7f1a5b8_s1_agent_tables.py`(276)、`b8c2d6f0a4e7_o8_agent_assisted.py`(52)、`a7b4d9e2c6f1_o3_seat_quota.py`(94)、`e5b8a1c9d3f7_ai_call_audits.py`(59)、`c3e7a9b1d5f4_t6_review_project_toggle.py`(31)、`ebb003a5c3a8_baseline_pg.py`(表名清单提取)。**种子**：`server/seeds/agents.json`。
**测试**（测试名+关键断言）：test_ai_tool_loop、test_permissions、test_control_plane_api、test_agent_idempotency、test_agent_traceability、test_agent_budget、test_agent_context_sanitization、test_agent_pilot、test_agent_gates_d7、test_agents_fallback_chain、test_ai_api_actions、test_ai_server_chat_mcp、test_ai_execution_reliability、test_outbox、test_worker、test_scheduling、test_job_reconcile、test_service_heartbeat、test_extension_management、test_sandbox_isolation、test_lcsc_skills、test_lcsc_capability_gate、test_solution_skills、test_seat_quota、test_audit_mutations、test_operation_events（共 26 个）。

## 二、逐条结论

**1. 工具目录注册（三层）** | ① `mcp_gateway.py:32-51` `TOOLS: dict[str, tuple[描述, capability|None, 参数schema]]`，共 **17 个**工具条目，元数据=中文描述+所需 capability+JSON 参数属性；**无**独立 risk 数值、无 read/write 布尔（写属性由 `tools/list` 的 annotations 动态推导，`mcp_gateway.py:271`：`readOnlyHint = name not in {"api_execute","file_send_wechat"}`）。② `api_catalog.py:15-126` `ENTRIES` **94 条**（GET 48 / POST 35 / PATCH 9 / DELETE 2），每条=(id, method, path, description, body_hints)，派生 `write = method != "GET"`、`confirmation = DELETE 或 .archive/.deprecate 后缀`（L123-126）。③ `builtin_skills.py` `SKILLS` 共 14 条（LEGACY 11 + workbench-help + lcsc-browser-baseline/jev），经 `seed_public_skill()` 落库。 | **VERIFIED**

**2. 读写区分与外部副作用标注** | MCP 面：仅 `api_execute`、`file_send_wechat` 为写（readOnlyHint=False，api_execute 另标 destructiveHint）。`api_catalog` 中 `api_execute` 执行前按 `write` 布尔过滤目录（`mcp_gateway.py:143`：无 workbench.write 时 write 条目不可见）。外部副作用标注是**隐式**的：`file_send_wechat`（微信投递，`file_delivery.py:23-38`）、`automation.execute`（DSH 外呼邮件/MCP，`reconcile.py:35-37` 注释明确 "has external side effects (mail, MCP calls)" 故不可恢复重跑）；api_catalog 条目文字注明"平台侧/需密码确认"，**无结构化 external_side_effect 字段**。 | **VERIFIED**（标注部分为注释级）

**3. 每次工具调用都过服务端鉴权；用户权限∩token 声明；project_id 双重校验** | 调用链：`mcp_endpoint`(mcp_gateway.py:251) → `_identity`(L66-81)：15 分钟 HS256 JWT（iss=fde-ai-tools/aud=fde-mcp）解码后**重新加载 User**，校验 is_active / must_change_password / auth_version，`allowed = capabilities_for_level(实时等级) ∩ claims.capabilities`（**只衰减不提升**）→ `call_tool`(L100-105)：注册表外工具 400、未知参数键 400、capability 不在 allowed 403 → `_project`(L84-90)：`claims.project_id` 匹配 + `project_access(user, project).can_view`（404 掩护）。直连环 `ai_tool_loop.direct_tool_completion`(L202-205) 用同一 `capabilities_for_level` + `call_tool`，注释明言 "a direct call can never reach more data than the MCP route would allow"。测试锁定：test_ai_server_chat_mcp.py:166/173/183/197（撤销 AI 授权即时失效、token 只衰减、项目范围与成员移除即时生效）。 | **VERIFIED**

**4. 无 "ToolGroup" 表；双层权限：角色 rank + AI 档位；agent 不能扩大用户授权** | HTTP 层角色：`auth/permissions.py` ROLE_RANK（viewer/fde_engineer/project_lead/admin）+ `require_role/require_minimum_role`（decorators.py:52-89）。AI 层：`access.py:14-26` ACCESS_RANK 五档 + DEFAULT_ACCESS_BY_ROLE + `UserAIAccessGrant` 显式覆盖（admin 恒 system_operator，L79）；`CAPABILITY_REQUIREMENTS`(L27-65) 定义约 30 个 capability 的最低档位。agent 侧"角色"= `agent_registry.capability_tier`（指向上述 capability 名）+ `allowed_tools` 声明白名单；run 发起时三重交集（`agents/tools.py:84-106`）：声明集 ∖ 平台 deny 集（`RUN_FACE_DENIED_TOOLS` 恒剥 `api_execute/file_send_wechat/会议二工具`）∩ 发起人实时等级 capability ∩ 插件安装实时态（V12：disable 即新 run 收紧）；等级地板恒生效——"插件安装绝不放宽门槛"。测试 test_agents_fallback_chain.py:209/218/248 锁定。 | **VERIFIED**

**5. automation_approvals：绑定 run+request_key、15 分钟、一次性、执行前复查权限** | 表 `control/models.py:161-195`：`(run_id, request_key)` 唯一；字段 capability/tool_name/arguments_json/**arguments_sha256**/risk_level(仅 3-4，CheckConstraint)/expires_at/status(pending/approved/rejected/expired/executed)。创建：`service.py:561-645`（DSH service token 入口 `/internal/dsh/executions/{run}/approvals`；校验 capability ∈ task.requested_capabilities + `authorize_ai_capability(requested_by)` 不过则 403 permission_revoked；密钥参数拒绝；run→waiting_approval）。审批：`decide_automation_approval`(L683-754)：项目范围可见性 + 审批人 `authorize_ai_capability` + **approve 必须验当前密码**；过期懒翻转。执行：`execute_approved_dsh_tool`(L781-843)：status=approved 才行、sha256 完整性复核、**再次 `authorize_ai_capability(requested_by)`**（撤销后执行被 403 拦截）、**硬编码工具白名单仅 `task.batch_assign/project_tasks.batch_assign`**、executed 后幂等返回——不可复用。测试 test_control_plane_api.py:643/766/813。另有两套平行确认：ai.api 密码确认（api_actions.py:215-257，auth_version 绑定+15 分钟+指纹陈旧检测）与插件变更审批（extensions_service.py:408-505）。 | **VERIFIED**

**6. 直连模型不能绕过工具权限；server chat MCP 路径=DSH 代理回环** | `ai/deepseek.py`、`ai/kimi.py` 等直连客户端只产文本/JSON，**无工具执行面**；DSH 不可用时的降级路径 `ai_server_client.py:57-119 direct_provider_completion`（无工具）与 `_degraded_direct_result → ai_tool_loop.direct_tool_completion`（只暴露 `READ_ONLY_TOOLS` 13 个白名单工具，ai_tool_loop.py:42-56，注释明言写类工具 "designed to run behind the MCP confirmation flow…Offering them here would bypass that control"）。chat MCP 路径（test_ai_server_chat_mcp.py）：`execute_ai_prompt`(ai_server_client.py:135-199) 给 DSH 签发 MCP token，DSH 以该 token 回调本服务 `/api/v1/internal/ai/mcp`——工具执行始终在本服务端、走第 3 条的同一鉴权。 | **VERIFIED**（注：直连 chat 路径的 usage 只进 `metrics_json`+成本估算，**不落 ai_call_audits**，见风险 R4）

**7. 提示注入防护=数据标记+提示层纪律+上下文熔断，无独立检测器** | ① `mcp_gateway.py:1-5` 模块红线 "Document text is untrusted reference material, never a source of instructions"；`file_read` 返回显式 `"source": "untrusted_project_file"`（L206）。② agent 上下文（`agents/context.py`）：只进 `confirmed=True` 的 ProblemItem（未拍板内容 AI 不可见）、模式遮蔽（盘符路径/PEM 私钥/API 令牌→REDACTED）、禁区词 fail-closed 抛 SanitizationError→422；沙箱内写入 `SANDBOX_AGENT_DISCIPLINE` 纪律文件。③ MCP 边界不收任意 SQL/路径/shell。**没有**对文件内容的指令语义检测/隔离编码——防护是标记+提示约定。 | **PARTIALLY VERIFIED**

**8. 预算/配额/成本三层** | ① E7 `ai_call_audits`（workbench/models.py:908-939；迁移 e5b8a1c9d3f7）：request_id/actor_user_id/purpose/model/used_fallback/duration_ms/input_tokens/output_tokens/status(succeeded/failed/**budget_blocked**)/error_code；月度按用户汇总（auditing.py:35-56），预算 0=不限，审计设施故障 fail-open。② agent 层：平台 `agent_monthly_budget` 发起前拦截（service.py:805-811）、单 run `max_cost_units` 适配器熔断（adapter.py:159-167）、`max_duration_ms` 超时（L146-148）。③ O-3 `seat_action_ledger`（agents/models.py:181-209；迁移 a7b4d9e2c6f1）：agent_run/meeting_convene/ai_chat/translation 四类动作，**超额只标注不拦截**（quota.py:45-74 record_action 永不抛错）；试点另有 30 天/20 run 硬闸（pilot.py:95-104，会拦截）。 | **VERIFIED**

**9. Skill 模型逐项** | 表 `skill_definitions` + `skill_versions`（control/models.py:198-239；基线迁移 ebb003a5c3a8）。
- 版本：**有**——`current_version_number` + 每变更新行 `SkillVersion(version_number, content_sha256 唯一)`，**不可变**（extensions_service.py:223-253：内容指纹相同则只改元数据，不同则 version_number+1 新行）。
- 状态：**部分**——仅 active/disabled，**无 draft/review/published/deprecated 全周期**。
- 测试报告：**无**。工具约束：**部分**——`required_capabilities`（⊆ CAPABILITY_REQUIREMENTS 且创建者档位内，防能力提升）；manifest_json 为任意 JSON，**无 I/O schema 校验**。
- 运行时选版本：**有**——`mcp_gateway._skills`(L93-97) join current_version_number，`skill_read` 只回当前版指令文本（指令型 Skill，无代码执行）。
- 回滚：**无**（版本留存但无切回接口）；弃用：**有**（status=disabled 后 `_skills` 过滤）。
- builtin 注册：`seed_public_skills`(builtin_skills.py:124-148)——admin 落库、指纹匹配（`_is_unchanged_builtin`）才升级，**管理员编辑永不覆写**（test_solution_skills.py:23 锁定）。 | **VERIFIED**

**10. extension/plugin/sandbox 机制及与 Skill 的关系** | extension=聚合中心（`extensions_center`：Skills+模型目录+插件+marketplace）。plugin：`PluginPackage`（marketplace 目录，verified/package_sha256/install_spec）→ `PluginChangeRequest`（install/upgrade/rollback/disable/remove，用户申请）→ system_operator `decide_plugin_change`（密码确认在 api_actions 敏感清单；能力不得超目标用户档位；install/upgrade 须版本+能力清单与包一致）→ AI Server `/v1/plugins/apply` 执行并**验证返回**才落 `PluginInstallation`(per-user granted_capabilities) + `PluginInstallationRevision`（rollback 只允许回到已验证历史版本，L518-528）。种子 `plugin_seeds.py` 幂等登记 lcsc.browse 等插件。与 Skill 的关系：**能力命名空间互通**——插件 manifest capabilities 进入 `agents/tools._plugin_capabilities/_actor_plugin_caps`，构成 run 面工具第三重闸。sandbox（agents/sandbox.py）：per-run docker 容器、恰好一个 bind mount（FORBIDDEN_MOUNT_MARKERS 拒挂 .env/真相层目录）、默认 `--network none`、allowlist 档 per-run iptables 网络、tmpfs、凭据仅经 env 内存管道（argv/磁盘零明文）、kill 逆序回收——这是 **agent CLI 执行沙箱**，Skill 本身无沙箱（纯指令文本）。测试 test_extension_management.py:110/128、test_sandbox_isolation.py 九条 V2 契约。 | **VERIFIED**

**11. background_jobs/outbox_events 与 worker 模型** | 表（jobs/models.py；基线迁移）：`outbox_events`(topic/aggregate_id/payload_json/status pending-dispatched-completed-failed/attempts/available_at/last_error)、`background_jobs`(job_type/target_id/status pending-queued-running-succeeded-failed/attempts/**max_attempts=5**/locked_until/locked_by/**active_key 生成列唯一**=单活跃 per (job_type,target_id))。worker（worker.py）：**lease 模型**——claim(running+locked_until+token) 先于 handler 独立事务提交；60 秒续租线程、租约 5 分钟；`_settle` token 守防陈旧覆写。队列：Redis list（queue.py，无 FOR UPDATE——outbox 用条件 UPDATE rowcount 抢占，dispatch 前强制新鲜快照读规避 REPEATABLE READ）。reconcile（reconcile.py）：expired-lease running 与孤儿 pending(>300s) 两形态，`RECOVERABLE_JOB_TYPES` 显式白名单（8 类；**automation.execute 故意不在内**——外副作用不自动重投），不可恢复/次数耗尽 → failed + 注册的 failure handler 把业务行推终态。心跳（health/heartbeat.py）：worker/scheduler 各写 Redis TTL 键。失败分类：last_error + `worker_lost:{reason}` 前缀；幂等键：chat turn id、`schedule:{task_id}:{ts}`、execution_id、action sha256。取消：无通用 BackgroundJob 取消 API（chat 会话删除、automation 走 DSH cancelled 回调）。 | **VERIFIED**

**12. automation_tasks / automation_task_runs / automation_approvals：存在** | control/models.py:72-195（基线迁移建）。结构：task（schedule_kind once/calendar/interval/event + cron 表达式 + timezone + prompt + requested_capabilities + risk_level 0-4 + dsh_profile）；run（状态机 queued/running/waiting_approval/succeeded/failed/cancelled/skipped、attempt、**idempotency_key 唯一**、knowledge_snapshot_id 外链、external_execution_id）。调度：`control/scheduler.py:62-94` `dispatch_due_automations`——`FOR UPDATE SKIP LOCKED` 锁到期 active 任务、幂等键查重、建 run + enqueue_outbox("automation.execute")。执行器：`automation_jobs.execute_automation_run`——FOR UPDATE 锁 run、终态跳过、task 非 active→skipped、**每个 requested_capability 逐一 `authorize_ai_capability` 复查**、构建 knowledge snapshot、携持久化 scope 派发 DSH（Idempotency-Key）。审批绑定如第 5 条。DSH 回调（events/knowledge/approvals）经 `verify_service_token` 服务令牌认证（routes.py:257-320）。测试 test_control_plane_api.py:482/515/572/643。 | **VERIFIED**

**13. 距 DAG Workflow 的差距与可复用扩展点** | 差距：① 无节点图——job 是 (job_type, target_id) 单原子，payload 不透明、**无 I/O 契约**；② 重试粒度=整 job（max_attempts 5）/agent 家族（≤2 指数退避），**无节点级重试/断点恢复**；③ 无工作流级取消/部分完成语义；④ `active_key` 唯一约束反而限制同 target 并行子任务。可复用（不必建第二套队列）：`jobs/handlers.register_handler/register_job_failure_handler` 的 job_type 注册机制、`enqueue_outbox(topic, aggregate_id, payload)` + `ensure_background_job` 的单活跃守卫、BackgroundJob 状态机+lease+reconcile 白名单（新 DAG 类型加进 RECOVERABLE 需逐节点幂等依据）、payload_json 携带节点 DAG 与各节点幂等键（可复用 api_actions 的 sha256 action_id 模式做副作用幂等）。最小侵入路线：**一个编排 handler 消费一个 workflow job，节点循环内复用 lease 续租与 failure hook**，节点产物落表供恢复。 | **VERIFIED**

**14. agent_runs / O-8 agent_assisted / traceability / pilot** | `agent_runs`（agents/models.py:60-121；迁移 d9c3e7f1a5b8）：状态机 queued→running→completed/failed/timeout/budget_exceeded + degraded/fallback_level(L0-L3)/retry_of/idempotency_key(索引不唯一，服务层家族收敛)/cost_owner/handoff_user_id/difficulty。溯源：`context_ref` 指脱敏 context.md；产物 `agent_artifacts`（storage_ref+sha256 成对、reviewed=False 起点、source_refs 必须 ⊆ 已确认 problem_refs 否则 C-1 拒绝）；`agent_tool_calls`（allowed/denied+capability+reason）；`project_solutions.generated_by/agent_run_id/template_id/confidence`。T1（计划评审）/T2（产物终审）/T6（高成本）门=已封存纪要侧链校验（service.py:751-784）。O-8（迁移 b8c2d6f0a4e7）：`delivery_packages.agent_assisted`+`difficulty`——已接单未声明→409 agent_assisted_required；high 档双保险禁入。pilot 开关：settings `agent_pilot_enabled/started_at/window_days/max_runs`（pilot.py）。 | **VERIFIED**

## 三、关键调用链（8 条）

1. **MCP 工具鉴权链**：chat/结构化 AI → `ai_server_client.execute_ai_prompt:159` `issue_mcp_token`（15min、能力=实时档位∩请求，只衰减）→ DSH → `POST /api/v1/internal/ai/mcp` `mcp_gateway.mcp_endpoint:251` → `_identity:66`（JWT+重载用户+active/auth_version+∩）→ `call_tool:100`（注册表+参数键+capability）→ `_project:84`（claims 范围+project_access）→ 具体 handler → commit。
2. **直连工具环（降级）**：`chat.create_turn:87`（排队+outbox）→ worker `run_job` → `execute_chat_turn:144` → `execute_ai_prompt`（DSH 不可用）→ `ai_tool_loop.direct_tool_completion:176`（capabilities_for_level→READ_ONLY_TOOLS∩capability）→ 供应商 /chat/completions → `_run_tools:96`→`call_tool`（同一鉴权）→ 最终答案 → metrics+成本估算。
3. **审批链**：DSH → `POST /internal/dsh/executions/{run}/approvals`（service token）→ `create_dsh_approval_request:561` → run=waiting_approval → 桌面 `GET /task-center/approvals` → `POST .../decision` `decide_automation_approval:683`（审批人能力+密码）→ approved → DSH → `POST /internal/dsh/approvals/{id}/execute` `execute_approved_dsh_tool:781`（approved 态+sha256+发起人权限复查+硬白名单单工具）→ executed 一次。
4. **job 执行链**：业务事务内 `enqueue_outbox:29`（flush 不 commit）→ worker `dispatch_pending:50`（新鲜快照+条件 UPDATE 抢占+单活跃+rpush）→ `dequeue` lpop → `run_job:56`→`_claim:93`（FOR UPDATE+lease+token 先提交）→ `_renew_lease` 线程 → handler → `_settle:131`（token 守终态）→ 死者由 `reconcile_jobs:110`（skip_locked 扫描+白名单+failure hook）收尾 + `beat()` 心跳。
5. **automation 调度链**：scheduler 循环 → `dispatch_due_automations:62`（SKIP LOCKED+幂等键）→ `AutomationTaskRun(queued)` + outbox("automation.execute") → worker → `execute_automation_run:19`（终态跳过/逐 capability 复查）→ `dsh_runtime.execute`（Idempotency-Key）→ 回调 events（service token）→ 终态。
6. **agent run 链**：`POST /api/v1/agents/{id}/run`（require_auth）→ `start_run:654`（persona 拒→`authorize_ai_capability`→工具三重交集→agent_assisted/difficulty/T1/T6 门→幂等→月预算→pilot→凭据 Fernet 解密）→ `_render_context:330`（只进 confirmed+遮蔽+禁区词 422）→ `_execute_run:485`（run 落库+SeatActionLedger+事件→workspace→`SandboxHandle.create` docker→`adapter.run` 判定/熔断/kill→`_finalize` 落 tool_calls+产物指纹+T2 门+L1/L2 标注）。
7. **skill 执行链**：`skill_list/skill_read` → `mcp_gateway._skills:93`（status=active ∧ (public∨owner) ∧ required_capabilities⊆allowed）→ 返回 current_version 的 instructions_text——**指令文本供模型阅读，无执行语义**。
8. **api_execute 写路径**：`call_tool:api_execute` → `execute_api:110`（目录+参数校验+密钥递归拒绝+60KB 上限）→ workbench.write 双重闸 → `_authorized:96` → OperationEvent(requested+指纹) → 敏感→awaiting_confirmation（15min，`/ai/actions/{id}/decision` 密码+auth_version+指纹陈旧检测）或 `_run`（内部 test_client 以新签 access token 转发同一 API）→ finished 事件。

## 四、相关表清单

| 表名 | 模型类 | 文件 | 关键字段 | 迁移 |
|---|---|---|---|---|
| user_ai_access_grants | UserAIAccessGrant | control/models.py:28 | user_id, access_level, granted_by | ebb003a5c3a8 |
| automation_tasks | AutomationTask | control/models.py:72 | schedule_kind/expression, prompt, requested_capabilities, risk_level, next_run_at | ebb003a5c3a8 |
| automation_task_runs | AutomationTaskRun | control/models.py:128 | status(7 态), idempotency_key(唯一), knowledge_snapshot_id, external_execution_id | ebb003a5c3a8 |
| automation_approvals | AutomationApproval | control/models.py:161 | run_id+request_key(唯一), capability, tool_name, arguments_sha256, risk 3-4, expires_at, status(5 态) | ebb003a5c3a8 |
| skill_definitions / skill_versions | SkillDefinition / SkillVersion | control/models.py:198/222 | scope, status, current_version_number / version_number, content_sha256, required_capabilities | ebb003a5c3a8 |
| plugin_packages / plugin_installations / plugin_installation_revisions / plugin_change_requests | … | control/models.py:242-352 | granted_capabilities, verified, package_sha256 / action, from/target_version, status | ebb003a5c3a8 |
| ai_provider_configs / ai_model_configs | … | control/models.py:355-390 | credential_ref(kms/env/vault 前缀), supports_tools | ebb003a5c3a8 |
| outbox_events | OutboxEvent | jobs/models.py:37 | topic, aggregate_id, status, attempts, available_at | ebb003a5c3a8 |
| background_jobs | BackgroundJob | jobs/models.py:66 | job_type, target_id, status, locked_until/by, max_attempts, active_key(生成列唯一) | ebb003a5c3a8 |
| ai_conversations / ai_chat_turns | … | control/chat.py:24/33 | status(queued/running/completed/failed), metrics_json | ebb003a5c3a8 |
| operation_events | OperationEvent | workbench/models.py:879 | actor, target_type/id, event_type, changes | ebb003a5c3a8 |
| agent_registry | AgentRegistry | agents/models.py:32 | kind(5 种), capability_tier, allowed_tools, sandbox_profile, credential_ref | d9c3e7f1a5b8 |
| agent_runs | AgentRun | agents/models.py:60 | status(6 态), fallback_level, retry_of, idempotency_key(索引), cost_owner, difficulty | d9c3e7f1a5b8+a7b4d9e2c6f1 |
| agent_artifacts / agent_tool_calls / agent_credentials / solution_review_checkpoints | … | agents/models.py:124/146/165/212 | sha256(64hex), reviewed, linked_solution_id / decision(allowed/denied) / Fernet 密文 / checkpoint_type+required_level | d9c3e7f1a5b8 |
| seat_action_ledger | SeatActionLedger | agents/models.py:181 | action_type(4), units, over_quota | a7b4d9e2c6f1 |
| ai_call_audits | AICallAudit | workbench/models.py:908 | model, used_fallback, tokens, status(含 budget_blocked) | e5b8a1c9d3f7 |
| delivery_packages(增量) | — | dispatch/models | agent_assisted, difficulty(low/medium/high) | b8c2d6f0a4e7 |
| projects(增量) | Project | workbench/models.py:281 | t6_review_disabled | c3e7a9b1d5f4 |

## 五、工具目录摘要

- **MCP TOOLS 17 个**：无 capability 门槛 7（action_status、api_catalog、api_execute、ontology_read、help_fetch、skill_list、skill_read）；读类带门槛 8（project_list/project_read/quote_list/gates_read→project.read；file_search/file_read→file.search；system_status→system.health；lcsc_search/lcsc_runs_read→lcsc.browse→system_operator）；**写类 2**（api_execute、file_send_wechat）。
- **api_catalog 94 条**：读 48 / 写 46；confirmation 强制 11 条级（DELETE 2 + .archive/.deprecate 后缀 + 敏感字段动态判定）。
- **builtin skills 14 条**（种子升级制）。示例条目：`gates_read`（读，project.read）、`api_execute`（写+destructiveHint）、`file_send_wechat`（外部副作用）、`solutions.export_sow`（写+导出闸）、`plugins.decide`（写+管理员密码确认）。

## 六、风险与差距

- **R1（低）skill 无 I/O schema 与测试报告**：manifest_json 任意 JSON、无结构校验（extensions_service.py:177 只查 isinstance dict）。
- **R2（低）提示注入为约定级防护**：untrusted 标记+提示纪律+确认流三道闸存在，但文件/网页正文进入模型上下文后无指令隔离编码，理论上可诱导模型调用其有权工具（权限闸仍在，危害=授权内误操作）。
- **R3（低）审批过期是懒翻转**：无人问津的 pending 审批无后台清扫，但 run 已停等且 execute 会拒——无实际越权窗口。
- **R4（低）直连 chat 路径不落 ai_call_audits**：DSH 缺席的降级对话用量只进 metrics_json，月度 token 预算核算对该路径失真。
- **R5（信息）automation_approvals 执行面极窄**：硬编码仅 task.batch_assign 一工具可用——保守设计而非漏洞。
- **R6（信息）agent run 权限冻结窗口**：allowed_tools 发起时刻冻结、运行中不重算；但 run 内工具均为只读且沙箱断网。
- **R7（信息）预算闸 fail-open**：E7 预算设施故障放行——可用性优先的显式取舍。

## 七、无法验证的项

1. **iptables egress 白名单的真实生效性**：sandbox.py 自述"argv 事实层经可注入后端在 CI 断言；真实 iptables 生效性归 d6 试点联调（人工项）"。
2. **DSH（AI Server）侧内部实现**：不在本仓库。
3. **生产 Docker 部署形态**：docker/ 目录全量未逐项核对。
4. **桌面端集成桥采集路径**（bridge-poll.mjs）：宿主侧脚本，不在服务端审计范围。
5. **kimi.py / minimax 完整实现**：仅确认其为独立槽位的 OpenAI 兼容客户端。

**总体判断**：该实现在「每次调用实时鉴权、token 只衰减、审批一次性且执行前复查权限、agent 权限天花板=发起人、外部副作用显式保守（automation 不可自动重投、写工具不进直连面）」五个关键安全属性上均有代码级证据与测试锁定；主要成熟度缺口在 Skill 治理（无 schema/测试报告/回滚）与 DAG 编排能力（单原子 job、无节点级恢复），以及注入防护停留在约定层。
