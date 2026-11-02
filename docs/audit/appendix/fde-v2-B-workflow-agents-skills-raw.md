# 附录 B（原始证据）：fde-v2 Workflow / 多 Agent / Skill / MCP 代码审计

> 生成方式：独立审计子代理对 `D:\test\FDE\knowledge\fde-v2`（v2.3.0b0 快照）全程只读、零执行。以下为子代理报告原文。审计日期：2026-11-02。

## 一、实际读取文件清单（路径 + 行数）

**全文精读**：`fde_platform/flow.py`(657)、`agent_service.py`(605)、`agent_roles.py`(357)、`agentscope_bridge.py`(595)、`builtin_tools.py`(278)、`agent_tool_filter.py`(91)、`agent_surface.py`(73)、`agent_common.py`(61)、`agent_admin.py`(237)、`platform_mcp_tools.py`(186)、`mcp_server.py`(294)、`mcp_http.py`(245)、`skills.py`(409)、`llm.py`(558)、`llm_admin.py`(92)、`_verify_agent2.py`(72)、`_verify_agent_service.py`(109)、`scripts/verify_agent_quality.py`(1161)、`verify_agent_rail.py`(211)、`verify_agent_tools.py`(329)、`verify_mcp_http.py`(214)、`patch_agentscope.py`(135)、`app/psc/_agent_tools.py`(125)、`_roles.py`(15)、`design-plus/流程编排方案.md`(193)、`多智能体方案.md`(252)、`智能体角色声明.md`(102)、`scripts/agent_quality/cases.jsonl`(19 条场景)、`app/psc/_flow_forecast_to_plan.yaml`、`_flow_alert_heal.yaml`。

**关键段落精读（交叉验证）**：`users.py`（is_effectively_granted/effective_service_names/has_app_access/ctx_for_user/MCP token，L465-530、L650-760）、`web.py`（agent2 反代与 SSE L670-700、HITL confirm L1225-1290、flow API L1507-1575）、`auth.py`（gate L109-155）、`scheduler.py`（run_job_now/_resolve_ctx L340-380）、`run_gates.py`（门禁分层 L60-230）、`config_paths.py`(40)。

## 二、逐条结论

**1. 流程定义格式与存储** | YAML 声明文件 `app/<组>/_flow_<key>.yaml`，平台扫描装配（`flow.py:169-196 _load_flows`，yaml.safe_load）；`save_flow/delete_flow` 直接写盘/删文件（L224-247）。运行进度存 SQLite：`config/flow_runs.db`，DDL 在 `flow.py:68-90`（`flow_runs` 只留最近一条 + `flow_run_history` 裁剪至 50 行）。 | **VERIFIED**

**2. DAG 解析/验证/执行/持久化** | `_normalize_nodes`(L323-343) 把 steps/nodes 归一；静态验证 `flow_problems`(L127-166) 查三条：id 重复、depends_on 指向不存在节点、input 引用无 output 声明——**无环检测**（循环依赖靠执行期 `ready` 为空 break 兜底，L632-635，且 break 后仍上报 `done` 而非 error，L655）；执行 `run_flow`(L611-657)：拓扑分层 + 同层 `ThreadPoolExecutor` 并行（`_run_ready` L590-608）；持久化仅 `_report_progress`(L252-282) 写两表，**无节点级状态持久化**。 | **VERIFIED（环检测缺失）**

**3. 节点类型** | 三种（`flow.py:19-26`、`_execute_node` L552-587）：`agent`（默认，`_run_node` L471-508 轻量 ReAct：llm.chat + bridge.execute，上限 10 轮）；`call`（`_execute_call_node` L519-537 确定性直调 `app.service`→`group__app__service` 工具名）；`skill`（`_execute_skill_node` L540-549 调 `skills.run_skill`）。控制流：`when` 条件跳过、`until`+`max_loop` 循环、`depends_on` 汇聚。**无 human/wait 类型**。 | **VERIFIED**

**4. 依赖检查/重试/恢复/取消/幂等** | 依赖检查：有（flow_problems + `_preflight` L446-468 开跑前对无 when 的 agent 节点预检工具面）。重试：**未找到**节点级重试（仅 until/max_loop 重执行语义）。恢复：**未找到**（无断点续跑，进程死即丢）。取消：**未找到**（无 cancel API）。幂等：**未找到**（重跑 flow 全量重执行；verify_agent_quality.py L22-24 自述 `demand_pool` 无去重、重复调用重复建单）。 | **VERIFIED（缺失项属实）**

**5. 节点 IO 验证与上下文传递** | 无 JSON schema 验证；静态只有 output 声明引用检查。上下文经共享 `state` dict：`output` 键写入、`{key}` 占位符由 `_fill/_fill_args`(L346-350, 511-516) 替换；上游被 when 跳过 ⇒ 缴 input 键 ⇒ 下游也跳过（L566-568）；skill 节点对未填充占位符 `{{key}}` 显式报错（skills.py:356-361），flow 的 call 节点**无**此检查（`_fill` 缺键填空串）。 | **VERIFIED**

**6. 工作流绕权限？** | 不能绕服务授权，但**绕 HITL**。权限校验点：agent 节点工具面 = 角色收窄 ∩ 用户有效授权（`_node_tools` L406-443，经 `agent_surface.app_surface`），收窄到空抛 `FlowAbort`；call/skill 节点每次经 `bridge.execute`（agentscope_bridge.py:541-595）做 fail-closed 授权（`users.is_effectively_granted` / 内置文件工具 `has_app_access`）。但 `bridge.execute` **无 dangerous 判定**——`_is_dangerous` 只在 agent_service 聊天路径的 `FunctionTool.check_permissions` 生效（agent_service.py:449），flow/scheduler 路径对 publish/delete/calc_net 等危险服务零确认直调，这是文档明示的刻意取舍（多智能体方案.md §6.2 L196-204）。注意：call 节点越权失败被 `_run_ready` 捕成"（节点执行失败）"文本写入 state **继续跑**（L606-607），不中止流程（preflight 不覆盖 call 节点）。 | **VERIFIED**

**7. 角色定义与工具过滤** | 业务角色下沉 `app/<组>/_roles.py`（`ROLES=[{type,label,apps}]`，`agent_roles.py:43-75 _load_group_roles` 用 exec 装配，psc 4 角色：sales/planning/inventory/delivery）；平台运维角色 integration/scheduler 代码定义（L19-29）。`allowed_tools_for_role`(L312-329)：业务角色按 `_meta.app`∈ROLE_APPS 匹配，平台角色按工具名匹配。工具过滤两层（agent_tool_filter.py）：`RoleToolFilterMiddleware.on_model_call` 软隔离（越界 FDE 工具从 LLM schema 剔除）+ `on_check_permission` 硬兜底 DENY（L37-63）；leader 用 `LeaderToolFilterMiddleware` 剥平台配置工具 + scheduled 会话禁 ScheduleCreate（L66-91）。角色识别靠 system_prompt 首行机器标记 `<!--FDE_ROLE:xxx-->`（agent_roles.py:303-309）。 | **VERIFIED**

**8. 服务端权限检查 / 读写区分 / HITL** | 每次工具调用都过 `bridge.execute`：业务服务判 `users.is_effectively_granted`（显式 ∪ 角色 ∪ 页面派生，users.py:465-490），内置文件工具判 `has_app_access`（agentscope_bridge.py:574-579）；`args.pop("context")` 拒客户端伪造身份（L548）。租户隔离：agent_service 按 X-User-ID（web.py:686 注入登录用户名），auth.gate 改写 session_id 为 `用户名:原值`（auth.py:150-153）。读写区分：无静态读写标注，靠 ①角色 prompt 注入 `AGENT_DISCIPLINE`"分析题只查询不动手"清单（agent_roles.py:209-222）②HITL 显式清单 `_HITL_SERVICES`（agent_service.py:76-89，9 个服务名：publish/approve/reject/delete/disable/rollback/cancel/calc_net/freeze）+ 平台工具 `_meta.dangerous`（`_is_dangerous` L92-101）→ `PermissionBehavior.ASK`，经 REQUIRE_USER_CONFIRM → `/api/agent2/confirm`（web.py:1225-1290）转发 USER_CONFIRM_RESULT 续跑——human-in-the-loop 代码真实存在，但**仅聊天路径**（见第 6 条）。 | **VERIFIED**

**9. Agent 间任务/上下文传递** | 用 AgentScope 2.0.6 app 框架内置团队工具：leader 调 TeamCreate/AgentCreate（subagent_type 取自 `custom_subagent_templates=agent_roles.AGENT_ROLES`，agent_service.py:589-597）/TeamSay 派活与回报；消息走 `InMemoryMessageBus`，会话/Agent 记录存 `AsyncSQLAlchemyStorage(sqlite+aiosqlite:///config/agent_service.db)`（L525），工作区 `config/agent_workspaces`。worker 模板 prompt 尾部写明"用 TeamSay 向 leader 回报"（agent_roles.py:264）。真实用例：`_verify_agent_service.py:68-77`（建 integration+scheduler 团队）、`_flow_forecast_to_plan.yaml`（5 节点跨 sales/inventory/planning/delivery 的产销协同链）。 | **VERIFIED**

**10. agentscope_bridge 封装与补丁** | bridge 封装两接口：`tool_schemas(platform,user)`（服务→OpenAI function 定义，按 visible_service_names 过滤 + 平台工具）与 `execute`（工具名→(app,service) 反查 →授权→`platform.call`/内置工具），AgentScope 侧不感知 FDE 内部（agentscope_bridge.py:1-11）。`patch_agentscope.py` 打两个源码补丁（Docker 构建期）：①`_toolkit.py get_toolkit` 支持 extra_factory 返回 `(tools, tool_groups)` 元组；②`_schedule_create.py` timezone 缺省从 UTC 改本地时区（tzlocal）。另有进程内 monkeypatch：`ToolOffloadMiddleware` 超时 10s→180s（agent_service.py:577-586）。 | **VERIFIED**

**11. LLM 调用** | 配置来源：`config/llm.db` 的 `llm_profiles` 表按 role（operator/vision）一行，密钥 Fernet 加密（主密钥 env `LLM_MASTER_KEY` 或 `config/llm_master.key`）；库内未配置回落 `LLM_BASE_URL/LLM_API_KEY/LLM_MODEL`，再回落 `NotConfiguredProvider` 优雅降级（llm.py:480-496）。重试：`FDE_LLM_RETRIES=3` 次线性退避（8s*n，L228-229、257-277）；超时：profile 的 timeout_s；中断钩子 `set_interrupt_check`（L63-69）。**成本/token 记录：未找到**；**审计日志：未找到**（仅 public_view 只读视图与 admin 页展示）。 | **VERIFIED（含缺失项）**

**12. Skill 定义/存储/版本/状态** | 定义 = `{name(唯一), description, trigger, steps:[{tool,args,output?,note?}]}`；存储 `config/skills.db` 单表 `skill`（DDL skills.py:30-48）；`version INTEGER` 字段存在（同名再提议 version+1）；状态机 `draft→approved→deprecated`（`STATUSES` L28），`reject` 直接删草稿（L211-215）。模块隔离：`module` 列 + `_module_filter`"本组 ∪ 平台级"（L112-119）。 | **VERIFIED**

**13. Skill 治理逐项** | 版本不可变：**无**——单行 UPDATE 原地改写（propose L176-183），无历史快照表，version 只是计数器。发布前测试：**无**——approve 仅改 status（L199-208），无 dry-run（仅 `_validate_steps` 形状校验 L135-161）。输入输出契约：**部分**——args 占位符 `{{key}}` 执行期填充、未填充报错（run_skill L356-361）、output 写 state，但无 schema。失败恢复/回滚：**无**——步骤失败抛 FdeError 即止（L367-368），不补偿不回滚。运行时版本固定：**无**——执行读当前行，跑动中被改即受影响。执行效果记录：**部分**——`usage_count`/`score` 累计（rate L231-250、note_usage 子序列匹配 L268-279），无 per-run 日志。人工审批闸真实有效：`run_skill` 强制 `status=='approved'`（L346-347），prompt 注入也只取 approved（`published_prompt_block` L387-409）。 | **VERIFIED**

**14. 三个 verify 脚本** | `verify_agent_tools.py`：纯静态代码断言（8 组：平台工具登记完整性、leader 白/黑名单、剪枝声明有效性+AST 重复键、工具面预算 ≤25/组 ≤15、HITL 清单命中与 `_meta.dangerous` 真被消费、HOWTOUSE 齐全、权限打标口径与 `flow._node_tool_usable` 零漂移、flow YAML 自洽）——**已入 CI**：`run_gates.py` static 层第 7 项（L102）。`verify_agent_quality.py`：**需活环境**（平台+agent_service+LLM+演示数据），不在 run_gates；判据混合——L1 工具轨迹/L2 事实数值/L3 结论正则均为**代码断言**（ground truth 只读现算，`fingerprint` 数据指纹防脏），仅 L4（B 类 4 条 rubric 场景）用 **LLM 裁判**（裁判失效→SKIP 不判 FAIL，L637-695）；退出码 0/1/2 区分失败与前置未就绪。`verify_agent_rail.py`：Playwright UI 长回合验收（sending 锁定、idle 解禁、SSE 对账），需活环境+LLM，自述"不在 run_gates"（L29）。 | **VERIFIED**

**15. MCP 暴露/鉴权/与 builtin_tools 关系** | 工具 = `platform.all_mcp_tools()`（每应用服务 `组__应用__服务` + 每应用 3 个内置文件工具）+ `platform_mcp_tools.tools()` 的 13 个 `platform__*` 管理工具。鉴权：stdio 用 `--user`/`FDE_MCP_USER`（启动校验，mcp_server.py:86-97）；HTTP 单端点 `POST /mcp` Bearer 令牌（sha256 哈希查表 `users.verify_mcp_token`，mcp_http.py:114-120），401+WWW-Authenticate、Accept 双类型 406、会话不可跨令牌接管、吊销即 401（verify_mcp_http.py 全覆盖）。`tools/list` 与 `tools/call` 都按 `is_effectively_granted`/`has_app_access` 过滤非 admin（mcp_server.py:143-151、193-204）——与 bridge.execute 同口径。`platform__*` 需 admin（L176-180）。MCP 的文件工具直接复用 `builtin_tools.call_builtin`（L207-211），Agent/MCP/Web 三面共用同一执行器与路径穿越防护（`_resolve` builtin_tools.py:57-70）。 | **VERIFIED**

## 三、关键调用链

- **聊天工具调用**：浏览器 → Flask `/api/agent2/chat/stream`（web.py:961，注入 X-User-ID）→ AgentScope create_app(:4100) → `_fde_tool_factory`（每次组装按授权即时重算工具面）→ FunctionTool(`_mk_ft`.check_permissions=ASK/ALLOW) → `bridge.execute(_platform, user, name, args)` → 授权判定 → `platform.call(app,service,ctx,**args)` / `builtin_tools.call_builtin` → 应用 SQLite。
- **HITL**：dangerous 工具 → PermissionBehavior.ASK → REQUIRE_USER_CONFIRM 事件 → 前端停车 → `/api/agent2/confirm` → USER_CONFIRM_RESULT 回注 agent_service 续跑。
- **flow**：`platform_run_flow`（聊天）或前端 → `flow.run_flow` → `_preflight`（agent 节点工具面预检）→ 拓扑分层并行 `_run_ready` → agent: `_run_node`(llm.chat+bridge.execute) / call: `bridge.execute` / skill: `skills.run_skill` → state 传递 → `_report_progress` → flow_runs.db。
- **MCP**：客户端 → nginx → Flask `/mcp`（Bearer→user）→ `McpServer.handle_as` → tools/list 授权过滤 / tools/call 授权判定 → `platform.call`（ctx=令牌用户）。

## 四、工具清单表（平台级；业务工具=每应用公共服务约 180 个）

| 名称 | 读/写/外部副作用 | 权限检查点 | 定义文件 |
|---|---|---|---|
| platform_propose_skill / raise_alert | 写（skill 草稿/告警） | 无用户级检查（全员，module 归组隔离） | agentscope_bridge.py:67-125 |
| platform_list_flows / run_flow / flow_progress | 读 / 执行(内部可写) / 读 | 全员；run_flow 内部按发起用户授权 | 同上 L127-162 |
| platform_read_app_doc / query_knowledge | 读 | **无应用授权过滤**（全员可读任意应用文档） | 同上 L164-209 |
| platform_save_flow / delete_flow | 写（文件系统） | execute 处 admin-only（bridge L422-424）；但 leader 白名单含它 | 同上 L287-302 |
| platform_{save,delete,test}_integration、{create,update,delete,set_job_enabled,run_job_now} | 写 / 外部 HTTP | admin-only + dangerous=True→HITL | 同上 L216-285 |
| platform_{create,delete,reset_password,set_user_role,set_user_grants,create_role,…} | 写（权限面） | admin-only + HITL | 同上 L303-352 |
| `<app>__platform_read_file` | 读（应用 resource 目录） | has_app_access（应用级） | builtin_tools.py:214-278 |
| `<app>__platform_write_file` | 写（仅 export-file） | has_app_access | 同上 |
| platform__user_create/user_reset_pwd/user_delete/llm_save/integration_save | 写 | MCP 路径 admin-only | platform_mcp_tools.py:22-86 |
| platform__user_list/role_list/llm_list/integration_list/scheduler_list/read_app_doc | 读 | MCP 路径 admin-only | 同上 |
| platform__integration_test | 外部 HTTP 请求 | admin-only | 同上 |

## 五、数据存储清单

| 存储 | 内容 | DDL 位置 |
|---|---|---|
| `app/<组>/_flow_*.yaml` | 流程定义（文件） | 格式正本 design-plus/流程编排方案.md |
| `config/flow_runs.db` | flow_runs + flow_run_history | flow.py:68-90 |
| `config/skills.db` | skill 表（含 module 迁移） | skills.py:30-55 |
| `config/llm.db` | llm_profiles | llm.py:75-90 |
| `config/llm_master.key` / `.env` | 加密根 | llm.py:160-177 |
| `config/auth.db`（users.py get_conn） | roles/users/service_grants/role_grants/role_page_grants/user_prefs/mcp_tokens | users.py:77-150 |
| `config/agent_service.db` + `agent_workspaces/` | AgentScope 会话/团队/凭证 | agent_service.py:54-59、525（schema 由 agentscope 库管理） |
| `config/scheduler.db`、`integration.db`、`agent_alerts.db` | 定时任务/集成/告警 | 各自模块 |
| `app/<组>/_roles.py`、`_agent_tools.py` | 角色/剪枝声明（exec 装配） | agent_roles.py:40-121 |

## 六、风险与差距（均有代码证据）

1. **stdio MCP 缺省 = 无授权全通**：`McpServer` 不带 `--user` 时 `self.user=None`，仅 stderr 告警即以平台默认身份运行（mcp_server.py:96-97），tools/call 全部放行（`user and not is_admin` 才拦）。
2. **flow/scheduler 路径绕过 HITL**：`bridge.execute` 无 dangerous 判定（对照 agent_service.py:449 只在聊天路径生效），publish/delete/calc_net 等经 flow 的 call 节点或定时任务零人工确认执行——文档承认为刻意设计（多智能体方案.md §6.2），但配合第 4 条（无幂等）放大不可逆风险。
3. **platform_read_app_doc 无应用授权过滤**：`agent_common.read_app_doc`（agent_common.py:43-61）不查 grants，非 admin 聊天用户可读**未授权应用**的 README/详设；且 agent_service.py:535 注释自称"按授权过滤"与实现不符。MCP 侧同名工具反而 admin-only——两个入口口径不一致。
4. **流程环/断链静默"done"**：flow_problems 无环检测；执行期 `ready` 为空 break 后仍报 `done`（flow.py:633-655）。
5. **save_flow 白名单与执行闸冲突**：`_LEADER_PLATFORM_TOOLS` 给（非 admin 的）leader 发 save_flow/delete_flow（agent_service.py:212-219 注释明说"让大模型创建工作流就靠它"），但 `_call_platform_tool` 的 admin 闸（bridge L422-424）会让非 admin 调用必然报"无权"——非 admin 场景"看得到、调不动"。
6. **无鉴权模式全通蔓延**：`user is None` 在 `_is_admin`（agent_admin/llm_admin/scheduler/auth）与 bridge/mcp 各处一致解释为"全通"，一旦部署关闭鉴权，聊天、MCP、flow 全部无门槛。
7. **提示注入面**：skill steps、HOWTOUSE、应用文档、上传文件内容（read_file 返回直接进模型上下文）均无内容消毒；防线是 execute 层授权 + AGENT_DISCIPLINE 纪律注入，属缓解而非阻断。verify_agent_quality.py L48-53 自认"权限边界只管服务面、不管文件面"（Glob/Read 泄漏事故已用 `_NO_CODE_TOOLS` 封堵，agent_service.py:528-538）。
8. **LLM 无成本/审计记录**：llm.py 无 token 用量、无调用留痕。

## 七、无法验证的项

- AgentScope 2.0.6 库内部实现（TeamCreate/AgentCreate/ResetTools/permission_mode DONT_ASK 下 ASK→DENY 的确切行为、agent_service.db 表结构）——本仓不含其源码。
- `platform.all_mcp_tools()`/`introspect.to_mcp_tool` 的逐字段生成逻辑（runtime.py/introspect.py 未列入必读清单，仅经 bridge 消费侧确认行为）。
- Docker 镜像内 patch 是否实际生效、`宣传/` 目录下 demo 与评测脚本（不在任务范围）。
- 各 verify 脚本"当前是否全绿"——按纪律未执行任何脚本，仅静态审读判据。
