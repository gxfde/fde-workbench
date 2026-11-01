"""Reviewed atomic API capabilities. No business workflow lives here.

Each entry maps to an existing authenticated endpoint. No arbitrary paths,
credential APIs, storage URLs, shell commands, or external recipients.
"""
P = "/api/v1/projects/{project_id}"
R = P + "/research"
D = P + "/documents"
F = P + "/files"
E = "/api/v1/extensions"
S = P + "/solutions"
A = "/api/v1/agents"

# ID, method, path, semantic description, body field hints.
ENTRIES = [
    ("modules.catalog", "GET", "/api/v1/modules", "读取模块目录，取得创建项目所需的 module_keys", ""),
    ("templates.catalog", "GET", "/api/v1/industry-templates", "读取行业模板目录", ""),
    ("documents.templates", "GET", "/api/v1/document-templates", "读取可用业务文档模板和类型，禁止猜测不存在的 document_type", ""),
    ("projects.members", "GET", P + "/members", "读取项目成员及分配任务所需的账号 ID", ""),
    ("research.link", "POST", R + "/subjects/{subject_id}/links", "将 AI 机会关联同项目岗位或流程", "version=来源机会对象当前版本,target_subject_id,link_type=opportunity_role 或 opportunity_process"),
    ("models.list", "GET", E + "/model-preferences", "查看公共和个人模型配置，不含密钥", ""),
    ("models.save", "POST", E + "/model-preferences", "创建或编辑模型配置；AI 不接收密钥，新模型保存为非默认草稿，由用户在模型管理填写 Key", "scope,name,provider,base_url,model,is_default=false,supports_tools；编辑时 id,version；禁止 api_key"),
    ("models.delete", "DELETE", E + "/model-preferences/{preference_id}", "删除模型配置，需当前账号密码确认", ""),
    ("plugins.read", "GET", E + "/plugins/{plugin_id}", "读取插件详情", ""),
    ("plugins.request", "POST", E + "/plugins/{plugin_id}/requests", "提交插件变更请求；卸载需密码确认", "action,target_version 等以 API 为准"),
    ("plugins.decide", "POST", E + "/plugin-requests/{request_id}/decision", "管理员审批并执行插件变更，需密码确认", "decision,reason 等以 API 为准"),
    ("projects.list", "GET", "/api/v1/projects", "查询可访问项目", ""),
    ("projects.read", "GET", P, "读取项目和当前版本", ""),
    ("projects.create", "POST", "/api/v1/projects", "创建项目", "name,enterprise_code,planned_start_date,leader_user_id,module_keys；可选 openfde_engagement,fdeops_workspace,background,notes,planned_end_date"),
    ("projects.update", "PATCH", P, "编辑项目", "version；可选 name,enterprise_code,openfde_engagement,fdeops_workspace,sop_phase,background,notes,planned_start_date,planned_end_date,status"),
    ("tasks.list", "GET", P + "/tasks", "读取项目任务", ""),
    ("tasks.read", "GET", P + "/tasks/{task_id}", "读取任务和当前版本", ""),
    ("tasks.create", "POST", P + "/modules/{module_identifier}/tasks", "在模块中新增任务", "必填 name,duration_days；可选 description,planned_start_date,assignee_user_id,collaborator_user_ids,dependency_ids"),
    ("tasks.update", "PATCH", P + "/tasks/{task_id}", "编辑任务状态、进度及计划", "version；status,progress,blocked_reason,description,planned_start_date,planned_end_date,duration_days,assignee_user_id,collaborator_user_ids,dependency_ids"),
    ("research.list", "GET", R + "/subjects", "读取调研对象及 AI 机会", ""),
    ("research.create", "POST", R + "/subjects", "创建调研对象或 AI 机会", "必填 version=最新项目版本,subject_type=department/role/process/opportunity,subject_key=小写字母开头且仅小写字母数字下划线,name；可选 description,sort_order,parent_subject_id"),
    ("research.update", "PATCH", R + "/subjects/{subject_id}", "编辑调研对象或 AI 机会", "version；name,description,sort_order,parent_subject_id,opportunity_profile；备注使用独立 memo 操作"),
    ("research.delete", "DELETE", R + "/subjects/{subject_id}", "删除调研对象，需密码确认", "version"),
    ("memos.read", "GET", R + "/subjects/{subject_id}/memo", "读取公共备注", ""),
    ("memos.update", "PATCH", R + "/subjects/{subject_id}/memo", "编辑公共备注", "version,memo"),
    ("memos.personal_list", "GET", R + "/subjects/{subject_id}/personal-memos", "读取项目成员个人备注", ""),
    ("memos.personal_update", "PATCH", R + "/subjects/{subject_id}/personal-memo", "只修改当前账号个人备注", "version,memo"),
    ("forms.list", "GET", R + "/forms", "读取调研表目录", ""),
    ("forms.read", "GET", R + "/forms/{form_id}", "读取调研表", ""),
    ("forms.update", "PATCH", R + "/forms/{form_id}", "填写调研表", "version,answers；字段结构以读取结果及 API 校验为准"),
    ("forms.export", "POST", R + "/forms/{form_id}/export", "提交调研表导出", ""),
    ("forms.export_status", "GET", R + "/exports/{export_id}", "读取导出状态与文件引用", ""),
    ("documents.list", "GET", D, "读取项目文档", ""),
    ("documents.read", "GET", D + "/{document_id}", "读取文档草稿及版本", ""),
    ("solutions.list", "GET", S, "查询方案设计；方案和机会识别是不同实体", ""),
    ("solutions.read", "GET", S + "/{solution_id}", "读取方案、关联机会及当前版本", ""),
    ("solutions.create", "POST", S, "保存关联多个机会的交付方案，不直接生成文件", "name,opportunity_ids,design_markdown；可选 deliverables,acceptance_criteria,data_systems,schedule,risks_dependencies,business_category"),
    ("solutions.update", "PATCH", S + "/{solution_id}", "编辑方案，不改动已有 SOW 文件", "version；可选 name,opportunity_ids,design_markdown,deliverables,acceptance_criteria,data_systems,schedule,risks_dependencies,business_category"),
    ("solutions.organize", "POST", S + "/ai-organize", "按所选机会与参考内容返回方案建议，不保存方案", "opportunity_ids,reference；可选方案字段。返回 fields，审阅后才能调用保存"),
    ("solutions.skeleton", "POST", S + "/skeleton", "按已确认项目指引与行业模板生成方案骨架草稿并保存（AI 不参与内容生成，人工修订后才能导出 SOW）", "可选 name,opportunity_ids,business_category"),
    ("solutions.health", "GET", S + "/{solution_id}/health", "读取方案健康度评分（模板覆盖率/引用完整性/报价合法）", ""),
    ("solutions.export_sow", "POST", S + "/{solution_id}/export-sow", "将已保存方案版本导出 SOW，内容保持原样，不重新 AI 推演", "version；返回文档及异步生成引用，完成后在文件库查看"),
    ("solutions.archive", "POST", S + "/{solution_id}/archive", "弃用方案，需当前账号密码二次确认；保留已有文件", "version；密码由专用确认通道输入，禁止传给模型"),
    ("documents.create", "POST", D, "创建其他业务文档身份，不等于生成文件；新 SOW 使用 solutions.export_sow", "document_type,expected_version；可选 template_version_id,business_category。历史 source_opportunity_ids/generation_scope 与 source_opportunity_id 接口仅兼容旧流程。项目计划类型为 project_plan_progress"),
    ("documents.draft", "PATCH", D + "/{document_id}/draft", "编辑文档草稿", "version；field_overrides,rich_text,list_selections"),
    ("documents.generate", "POST", D + "/{document_id}/generate", "提交生成；异步产物自动归档文件库", "version"),
    ("documents.versions", "GET", D + "/{document_id}/versions", "检查文档生成状态及具体文件版本引用", ""),
    ("documents.archive", "POST", D + "/items/{document_id}/archive", "归档文档，需密码确认", "version"),
    ("files.list", "GET", F, "查询文件库", ""),
    ("files.versions", "GET", F + "/items/{file_id}/versions", "查询稳定文件下的内容版本", ""),
    ("files.rename", "PATCH", F + "/items/{file_id}", "重命名文件", "name"),
    ("files.deprecate", "POST", F + "/items/{file_id}/deprecate", "弃用文件，需密码确认", "reason"),
    ("extensions.read", "GET", E, "读取可见 Skills、插件和模型目录，不含密钥", ""),
    ("skills.personal_save", "POST", E + "/skills/personal", "维护个人技能", "key,name,description,instructions,manifest,required_capabilities"),
    ("skills.public_save", "POST", E + "/skills/public", "管理员维护公共技能", "key,name,description,instructions,manifest,required_capabilities"),
    ("plugins.search", "GET", E + "/marketplace/search", "搜索插件；query 参数以 API 为准", ""),
    # 派单引擎（goal-r3 P0-1/P0-2）：交付包读走 package_access 第三语义白名单
    ("dispatch.packages_list", "GET", "/api/v1/dispatch/packages", "查询自己被授权的交付包（跨主体只读白名单，不含报价明细）", ""),
    ("dispatch.packages_read", "GET", "/api/v1/dispatch/packages/{package_id}", "读取交付包白名单字段（12 项 + 交付方席位金额）", ""),
    ("dispatch.packages_create", "POST", "/api/v1/dispatch/packages", "从方案+报价建交付包 draft（平台侧）", "solution_id,quote_id；可选 dispatch_mode=assign/claim,onsite_visits"),
    ("dispatch.packages_publish", "POST", "/api/v1/dispatch/packages/{package_id}/publish", "发布交付包：冻结快照哈希并对候选授只读（平台侧）", "可选 candidate_user_ids"),
    ("dispatch.packages_withdraw", "POST", "/api/v1/dispatch/packages/{package_id}/withdraw", "撤回交付包（无进行中 offer 才允许；平台侧）", ""),
    ("dispatch.packages_accept", "POST", "/api/v1/dispatch/packages/{package_id}/accept", "接单并交接项目成员身份（§9.3）", "delivery_user_id"),
    ("dispatch.offers_create", "POST", "/api/v1/dispatch/packages/{package_id}/offers", "对候选发指派 offer（平台侧；包 published→offered）", "candidate_user_ids"),
    ("dispatch.offers_accept", "POST", "/api/v1/dispatch/offers/{offer_id}/accept", "接单/中签确认（乐观锁 version；§9.3 交接随行）", "version"),
    ("dispatch.offers_decline", "POST", "/api/v1/dispatch/offers/{offer_id}/decline", "拒单（§6.7 拒单权；原因枚举选填、只进留痕）", "version；可选 reason=档期冲突/能力不匹配/距离/其他"),
    ("dispatch.offers_mine", "GET", "/api/v1/dispatch/offers/mine", "我的 offer 收件箱（候选人=当前用户全量留痕；§6.2 窗口 deadline 现算；§4.8 释明只回本人）", ""),
    ("dispatch.package_offers_list", "GET", "/api/v1/dispatch/packages/{package_id}/offers", "包侧 offer 留痕（调度台运营视图：本轮谁被派/接了/拒了、确认窗 deadline 现算、rank 释明；平台侧）", ""),
    ("dispatch.settlements_mine", "GET", "/api/v1/dispatch/settlements/mine", "我的席位结算（只含自己席位的角色与金额；他席存在与金额不出现；预扣税原样透出）", ""),
    ("dispatch.packages_claim", "POST", "/api/v1/dispatch/packages/{package_id}/claim", "抢单登记（§6.4 城市开闸三条件 + 种子开关全过才允许）", ""),
    ("dispatch.packages_match", "POST", "/api/v1/dispatch/packages/{package_id}/match", "两段式撮合 Top3（Stage A 资格门 + 场景裁决 + Stage B；§4）", ""),
    ("dispatch.packages_level_override", "POST", "/api/v1/dispatch/packages/{package_id}/required-level", "发布前人工覆盖等级门槛（必填 reason 留痕；§4.5）", "level,reason"),
    ("dispatch.profiles_list", "GET", "/api/v1/dispatch/profiles", "供给池能力档案与产能看板（含在途/上限；平台侧）", ""),
    ("dispatch.profiles_me", "GET", "/api/v1/dispatch/profiles/me", "我的能力档案与产能（自助只读；无档案 404）", ""),
    ("dispatch.rules_list", "GET", "/api/v1/dispatch/rules", "规则版本快照与只读常数（P2-1 权重配置页；平台侧）", ""),
    ("dispatch.disputes_list", "GET", "/api/v1/dispatch/disputes", "争议单列表（L0–L3 全量；L0 对账单只透出 source_uri 指针；平台侧）", ""),
    ("dispatch.disputes_open", "POST", "/api/v1/dispatch/disputes", "人工打开争议（仅 L1/L2——L0 由对账自动产；L1 金额 ≤¥50,000 超限 422；平台侧）", "package_id,layer,reason；可选 amount,settlement_key,l0_report_source_uri"),
    ("dispatch.disputes_resolve", "POST", "/api/v1/dispatch/disputes/{dispute_id}/resolve", "人工裁决（结论必填；处罚类动作 100% 人工；可选 close=true 直关；平台侧）", "resolution；可选 close"),
    ("dispatch.simulator_replay", "POST", "/api/v1/dispatch/simulator/replay", "历史包回放打分（当前池×当前规则版本再撮合画像；只读；全链路仿真留 CLI 沙箱库；平台侧）", ""),
    ("dispatch.claim_gates_list", "GET", "/api/v1/dispatch/claim-gates", "城市开闸看板（§6.4 三条件+种子开关逐城可解释明细；只读不翻转开关；平台侧）", ""),
    # 编程工作台（goal-d4）：agents 只读四条；发起 run/接管/重试属人工授权
    # 写路径，继续不收（沿门禁三路由先例）
    ("agents.list", "GET", "/api/v1/agents", "读取智能体注册表与可用状态（含不可用原因：disabled/adapter_missing/credential_missing）", ""),
    ("agents.run_get", "GET", A + "/runs/{run_id}", "查询 agent run 溯源（状态/成本/降级链/产物 sha256 指纹）", ""),
    ("agents.tool_calls", "GET", A + "/runs/{run_id}/tool-calls", "查询 run 工具调用留痕（denied 明细可过滤）", "decision=allowed|denied 可选"),
    ("agents.cost", "GET", A + "/cost", "查询 agent 成本明细与月度汇总（project 需 project_id；seat/platform 仅系统运维员）", "scope=project|seat|platform，scope=project 时必带 project_id"),
    # 评审会（goal-d5）：只读三条；召集/发言/收敛属人工收敛写路径不收——
    # 评审结论永远经人工收敛封存，AI 不代拍板（沿门禁与 agents 先例）
    ("meetings.templates", "GET", "/api/v1/meeting-templates", "评审会模板列表（三档门 lite/std/full；T2-lite=守卫+1 模块智能体、2 话轮）", ""),
    ("meetings.get", "GET", "/api/v1/meetings/{meeting_id}", "查询评审会状态与话轮流（只读）", ""),
    ("meetings.minutes", "GET", "/api/v1/meetings/{meeting_id}/minutes", "查询会议纪要三段式（共识/分歧/待办 + sealed_sha256 封存指纹 + triggered_by_run_id 溯源回链）", ""),
]

CATALOG = {key: {"id": key, "method": method, "path": path, "description": description,
    "body_hints": hints, "write": method != "GET",
    "confirmation": method == "DELETE" or key.endswith((".archive", ".deprecate")),
} for key, method, path, description, hints in ENTRIES}
