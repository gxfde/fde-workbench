from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# 红线① 产品名单一来源（服务端侧单点）：界面文案（chat 系统提示词等）从此常量/
# Settings 取值，不再硬编码。桌面端对应 desktop/src/shared/brand.ts 的 PRODUCT_NAME，
# 两处口径需同步；`server/.env` 可经 FDE_PRODUCT_NAME 覆写（换名只改这两处）。
DEFAULT_PRODUCT_NAME = "蔡工FDE智能交付系统"


class Settings(BaseSettings):
    env: Literal["development", "test", "production"] = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8010
    database_url: str
    redis_url: str
    jwt_secret: str = Field(min_length=32)
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    # 红线① 产品名单一来源（服务端侧单点）：默认值=desktop/src/shared/brand.ts 的
    # PRODUCT_NAME；改动需双侧同步（桌面 brand.ts + 此处/env 覆写 FDE_PRODUCT_NAME）。
    # 界面文案（chat 系统提示词等）从此处取值，不再硬编码。
    # CR-046：env 覆写键=FDE_PRODUCT_NAME（validation_alias 单点钉死）——
    # 无别名时 env_prefix 会拼出 FDE_FDE_PRODUCT_NAME 死键（六处文档承诺失效）。
    fde_product_name: str = Field(
        default=DEFAULT_PRODUCT_NAME,
        validation_alias="FDE_PRODUCT_NAME",
    )
    storage_backend: Literal["local", "oss"] = "local"
    # 存储布局五步状态机（M4 批次 D；出厂默认 legacy＝现状零回归）：
    # legacy → dual_write → read_new → readonly → retired（storage/layout.py 单一权威）。
    storage_layout: Literal[
        "legacy", "dual_write", "read_new", "readonly", "retired"
    ] = "legacy"
    local_storage_root: Path = Path(".fde-storage")
    oss_endpoint: str | None = None
    oss_bucket: str | None = None
    oss_access_key_id: SecretStr | None = Field(default=None, repr=False)
    oss_access_key_secret: SecretStr | None = Field(default=None, repr=False)
    clamav_host: str = "127.0.0.1"
    clamav_port: int = 3310
    clamav_timeout_seconds: int = 10
    clamav_socket_timeout_seconds: int = 5
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: SecretStr | None = Field(default=None, repr=False)
    deepseek_industry_template_model: str = "deepseek-v4-pro"
    deepseek_project_presurvey_model: str = "deepseek-v4-pro"
    deepseek_ai_opportunity_model: str = "deepseek-v4-pro"
    deepseek_research_export_model: str = "deepseek-v4-pro"
    deepseek_document_generation_model: str = "deepseek-v4-pro"
    # V3.2 G9：模拟训练场的**独立模型评估层**槽位（按用途独立，不与生产管道
    # 换档互牵连）。缺 API Key 时该层返回 unavailable（不产生分数）。
    deepseek_simulation_evaluation_model: str = "deepseek-v4-pro"
    # 学习闭环 2.0 L4：训练场 workbench 执行面（API 内真模型跑题）槽位——
    # 空 = 回落评估槽位；缺端点/密钥 ⇒ 运行诚实失败（不静默退回 mock）。
    deepseek_simulation_workbench_model: str = ""
    # 诊断报告科目评分模型（T-08）：空 = 沿用训练场评估模型槽位；评分模型
    # 与生成模型分档是常态，独立槽位便于单独校准。
    diagnostic_judge_model: str = ""
    # 诊断报告**生成**模型的显式槽位（curve 1 修复轮）：空 = 不接管，沿用
    # execute_ai_prompt 既有解析链（服务账号偏好行 → system-default〔借行业
    # 模板槽位〕——curve 1 真机归因确认该链工作正常）。设值即整体接管：
    # 单模型端点必须填端点实际在售的模型名（默认族值 deepseek-v4-pro 在不售
    # 它的端点上会 400）。
    deepseek_diagnostic_report_model: str = ""
    # N6/G-13 按评测质量路由模型（fail-safe 薄缝，ai/model_routing.py）：出厂闸
    # 默认关＝永不切换（任务书 N6「不在无评测数据时自动切模型」）；摘要指针空/
    # 文件不可读/无该 purpose 行/分数低于下限，四道闸任一不满足都沿用既有解析链。
    ai_quality_route_enabled: bool = False
    # N4 CI eval 产出的按 purpose 模型质量摘要（本地 JSON 指针，原件不入仓）。
    ai_quality_route_summary_uri: str = ""
    # 质量分下限（缺省 0.8＝交付效果评测协议 v0 PASS 截断口径）。
    ai_quality_route_min_score: float = 0.8
    # N4/G-14 指标越限→提示词复审工单（metrics/review_tickets.py）：出厂闸默认
    # 关＝永不自动建单；规则 JSON 空＝无规则。工单是 draft 提案（零生产写），
    # 人工复核后才走既有审批/发布链——动作是「工单」，不是自动改提示词。
    ai_review_ticket_enabled: bool = False
    # 复审规则 JSON 数组文本：[{"metric":"<v31 指标 id>","op":"<|<=|>|>=",
    #   "threshold":<数值>,"prompt_ref":"<prompt_registry 注册键>"}]
    # 未知指标/未知注册键/非法 op 在评估时 422 fail-closed（不静默跳过）。
    ai_review_ticket_rules: str = ""
    # goal-d9：翻译器管道（文本 JSON 提炼）。goal-d13 拍板：provider 切 kimi
    # 槽位（kimi-k3，Moonshot OpenAI 兼容端点），客户端仍走通用文本 JSON 栈。
    # T6 高成本 run 前评审（goal-d11，总纲 §2.2 T6）：拟用 agent 的
    # max_cost_units 超过该阈值（或为 0=单 run 不限额，即最高成本档）时，
    # start_run 前置 T6 评审闸；0 = 全局关闭（试点期默认）。项目级关闭见
    # projects.t6_review_disabled。
    t6_review_cost_threshold: int = 0
    # E5 降级链：主模型瞬时故障（超时/限流/5xx）时切换的备用模型；
    # 留空表示不降级（行为与旧版一致）。主备都失败 → ai_manual_handoff 转人工。
    deepseek_fallback_model: str = "deepseek-v4"
    deepseek_timeout_seconds: int = Field(default=90, ge=5, le=300)
    # E7 月度 token 预算（按用户、自然月，审计表汇总核算）。0 = 不限额——
    # 默认配置不锁死现有用户；设置正数后超限调用被拒且不发起供应商请求。
    ai_monthly_token_budget: int = Field(default=0, ge=0)
    # V31-P1（somwyn 试点偏离）：推理模型先产出 reasoning_content 再产出
    # content，两者共享 max_tokens——不预留时 content 被 reasoning 挤到截断
    # （实测 MiniMax-M3.1-Flash：16,384 预算被 reasoning 吃掉 15,223，正文
    # JSON 截断 finish_reason=length）。直连腿对命中推理特征的模型把输出
    # 预算 ×2（多出份额供 reasoning 消耗，content 份额不缩水）。留空=只用
    # 内置特征识别；配置 Python 正则会作为**额外**分支并入（不替换内置，
    # 误配只放宽不收窄）。
    ai_reasoning_model_pattern: str = ""
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_project_presurvey_api_key: SecretStr | None = Field(default=None, repr=False)
    kimi_project_presurvey_model: str = "kimi-k3"
    # goal-d13 拍板：翻译管道独立 kimi 槽位（key/base_url/model 与预调研分开配，
    # 换档不互相牵连）。base_url 也独立的原因：部署 env 可能把共享 kimi_base_url
    # 指向另一家 OpenAI 兼容供应商（如 minimaxi），若翻译共用该地址，就会拿
    # kimi-k3 去打没有该模型的端点。默认与 kimi-k3 自洽（Moonshot）。
    # goal-d14 拍板：这三件降级为**可选 env 覆盖**——配齐才强制走 kimi-k3；
    # 不配则翻译与 AI 聊天同源解析模型（模型偏好表 → 系统默认槽位），
    # 运维零新增配置即可用。
    kimi_translator_api_key: SecretStr | None = Field(default=None, repr=False)
    kimi_translator_base_url: str = "https://api.moonshot.cn/v1"
    kimi_translator_model: str = "kimi-k3"
    kimi_timeout_seconds: int = Field(default=180, ge=10, le=600)
    # Kimi 槽位切到非 Moonshot 供应商（如 MiniMax）时的两个协议开关：
    # - kimi_local_docx_extract=True：供应商不提供 file-extract 文件接口，
    #   改为服务端本地解析 DOCX 取文本后送模型（文件不出本机）
    # - kimi_openai_compatible=True：按通用 OpenAI 兼容端点发请求
    #   （用 max_tokens 而非 max_completion_tokens，不发 reasoning_effort）
    kimi_local_docx_extract: bool = True
    kimi_openai_compatible: bool = False
    dsh_enabled: bool = False
    dsh_base_url: str = "http://127.0.0.1:8020"
    dsh_service_token: SecretStr | None = Field(default=None, repr=False)
    dsh_runtime_version: str = "unconfigured"
    dsh_protocol_version: str = "fde-dsh-v1"
    dsh_timeout_seconds: int = Field(default=300, ge=10, le=1800)
    ai_internal_api_url: str = "http://127.0.0.1:8010"
    weixin_enabled: bool = False
    weixin_credential_key: SecretStr | None = Field(default=None, repr=False)
    dsh_market_enabled: bool = False
    dsh_market_registry_url: str = "https://example.com/plugins.json"
    dsh_market_timeout_seconds: int = Field(default=15, ge=3, le=60)
    dsh_market_max_catalog_bytes: int = Field(default=25_000_000, ge=100_000, le=100_000_000)
    clawbot_enabled: bool = False
    clawbot_gateway_token: SecretStr | None = Field(default=None, repr=False)
    # P2 集成桥：宿主采集器（scripts/bridge-poll.mjs）推快照用的静态令牌；
    # 未配置时 POST /api/v1/bridge/snapshots 返回 503（桥关闭）
    bridge_token: SecretStr | None = Field(default=None, repr=False)
    # G7 登录限流：Redis 不可用时的策略。默认 fail-open（本机回环部署，Redis 挂了
    # 不挡业务登录，记 WARNING 可观测）；对外暴露部署设 true 切 fail-closed（一律 429）。
    login_rate_fail_closed: bool = False
    # G6 注册面节流：Redis 不可用时的策略，语义同登录限流。默认 fail-open
    # （内网部署假设，Redis 挂了不挡注册，记 WARNING 可观测）；对外暴露部署
    # 设 true 切 fail-closed（注册一律 429）。
    registration_rate_fail_closed: bool = False
    # 多客户 M2 四入口注册面（ADR-M4）：**部署闸默认关**——关闭时注册面一律 404
    # （不确认面存在，诊断线同款 fail-closed）。开闸前提 = 本开关与 SES 发信同时
    # 启用且公网根地址已配置：**不允许「无邮箱验证的静默放行」**（OWNER 拍板
    # 2026-11-11，SES 生产批复前注册面整体关闭）。
    registration_enabled: bool = False
    # 验证链接的公网根地址（SES 批复前的过渡形态=部署闸整体关闭，OWNER 拍板）；
    # 未配置时注册面视为关闭（fail-closed，不 crash）。
    public_base_url: str = ""
    # 注册面同 IP 每日上限（四入口统一限流，键族 auth:register:{ip}）。**保守占位
    # 缺省，试点前须填实数**（ADR-M4 §3-2；不定数纪律，禁止无上限）。
    registration_ip_daily_limit: int = Field(default=20, ge=1)
    # 邮箱验证令牌有效期（小时）；令牌一次性，明文只出现在邮件里，库中只有
    # sha256 指纹（诊断匿名令牌同形态）。
    registration_token_hours: int = Field(default=72, ge=1)
    # 同账号重发验证的最小间隔（秒）；叠加同 IP 每日上限构成重发双闸。
    registration_resend_min_seconds: int = Field(default=60, ge=1)
    # 审核制开关（任务书 §11-3 拍板值）：逗号分隔的需要人工审核的注册入口集。
    # 缺省 = 拍板值「交付者与区域审核、企业与创业者自助激活」；改此值即切换
    # 审核制（验收「审核制开关生效」）。
    registration_review_entries: str = "deliverer,partner"
    # WP-E SES 发信（goal-r3 G9 预建）：默认整体关闭、零行为影响；SES 生产批复
    # 下来只需改配置启用。发信域约束按项目口径：主域（somwyn.com）不发信，
    # 只允许配置的子域（如 mail.somwyn.com）。DKIM/SPF 的 DNS 记录不写死在代码，
    # 见 docs/系统意图-自动化面.md SES 节。
    ses_enabled: bool = False
    ses_region: str = "us-east-1"
    ses_send_subdomain: str = ""
    ses_from_address: str = ""
    ses_reply_to_address: str = ""
    ses_topic_arn: str = ""
    ses_daily_limit: int = Field(default=10, ge=1)
    ses_configuration_set: str = ""
    # goal-d3 沙箱基座（技术实施方案 §4 / 决议 D4）：默认参数面向 docker CLI
    # 可注入后端；镜像与容器名口径见 agents/sandbox.py。断网/资源上限/
    # 一次性 workspace 是基线事实，不随配置开放（egress allowlist 已随 d4
    # 落地，白名单本身仍需显式配置）。
    sandbox_docker_bin: str = "docker"
    sandbox_image: str = "fde-sandbox-runner:latest"
    sandbox_memory: str = "512m"
    sandbox_cpus: str = "1.0"
    sandbox_pids_limit: int = Field(default=128, ge=1)
    sandbox_tmpfs_size: str = "512m"
    sandbox_timeout_seconds: int = Field(default=300, ge=5, le=3600)
    # goal-d4 run 生命周期（技术实施方案 §5/§8）：FDE_AGENT_* 配置族。
    agent_monthly_budget: int = Field(default=0, ge=0)  # 平台月度预算（0=不限额，沿 E7 心智）
    # 单 run 超时毫秒（D6 默认 300000；agent_registry.max_duration_ms 优先）
    agent_max_duration_ms: int = Field(default=300000, ge=1000)
    # 重试指数退避基长（秒）：第 n 次重试需等待 base*2^(n-1)；0 = 测试口径
    agent_retry_backoff_base_seconds: int = Field(default=30, ge=0)
    # egress allowlist：逗号分隔 IPv4 CIDR；空 = allowlist 档不可用（deny 基线不变）
    agent_allowed_egress: str = ""
    # 上下文脱敏禁区词（逗号分隔，真实客户名等）：命中即拒绝发起 run（fail-closed）
    agent_forbidden_terms: str = ""
    # L 线 L3：agent 上下文知识片段（server/seeds/lessons.json 静态经验条目层）
    # ——能力腿＋项目行业过滤，条数与单条字符上限防上下文膨胀（agents/lessons.py）。
    agent_lessons_enabled: bool = True
    agent_lessons_top_k: int = Field(default=3, ge=0)
    agent_lessons_max_chars: int = Field(default=400, ge=1)
    # ⑦ 宿主通道出站限制面（任务书 §9 方案 A，2026-11-11 拍板实施）：开启后
    # 宿主 spawn zcode 前起本地正向代理（仅监听 127.0.0.1 临时端口），把
    # HTTP(S)_PROXY/NO_PROXY 注入进程 env；白名单外 CONNECT 一律 403 拒绝，
    # 出站审计落 agent_egress_audit 事件（只记域名不记内容）。白名单=逗号
    # 分隔域名后缀（如 api.z.ai,open.bigmodel.cn）；**空 + 开启 = fail-closed**
    # （run 拒绝发起转 L2 不计费——既不无限制放行也不静默全拒绝）。
    agent_host_egress_gate_enabled: bool = False
    agent_host_egress_allowlist: str = ""
    # run workspace 根目录（相对路径相对服务端工作目录）
    agent_workspace_root: str = "agent-workspaces"
    # 沙箱内 agent CLI 命令（zcode 适配器 spawn 段）
    agent_cli_command: str = "zcode"
    # 宿主侧 zcode 代理通道（T-Z1 裁定 A 方案实施轮，2026-11-07；仅开发
    # 自用，商用前须 zcode 供应商书面授予——见 backlog T-Z1 挂账）。默认
    # False：容器内 server 进程无法 spawn 宿主桌面进程（zcode 登录态在
    # Windows 宿主），只有宿主裸跑态（scripts/run-server-tests.mjs 同款
    # 直跑形态）显式开启后才走本通道；关闭时 run 走既有容器沙箱路径，
    # kind=zcode 无 docker 时沿 SandboxError→L2 链降级，行为零变化。
    agent_host_channel_enabled: bool = False
    # ZCode.exe 全路径（Electron 壳；宿主通道 spawn 段）
    agent_host_zcode_bin: str = ""
    # zcode.cjs 全路径（相对安装根 resources/glm/zcode.cjs；宿主通道 spawn 段）
    agent_host_zcode_cjs: str = ""
    # zcode CLI 配置文件路径（N2 事实② defaultModelSelection 键校验用；
    # 空 = 缺省 ~/.zcode/cli/config.json——goal-sprint r2，2026-11-13）
    agent_host_zcode_cli_config: str = ""
    # P2′① 宿主轮询领取（§11.3 六条约束，迁移 f6d3a9c1e7b2；2026-11-08）：
    # 开启后 kind=zcode 的 run 发起时落 queued + execution_provider=host_poll
    # 即返回（HTTP 不阻塞），由宿主代理轮询领取（POST /agents/host/claim）→
    # 本地 spawn zcode → 回执（POST /agents/host/runs/{id}/receipt）。
    # **生产启用闸仍关**：adapter_missing 维持到「①实装 + D3 书面回执 +
    # N2 联调签核」齐备——本开关只解除「形态未实装」，不解除人工闸。
    agent_host_poll_enabled: bool = False
    # 宿主代理轮询令牌（SHA-256 后入库比对；零明文落库——§11.3 约束 4）。
    # 空 = 轮询路由 403 host_poll_disabled（fail-closed）。
    agent_host_poll_token: SecretStr | None = Field(default=None, repr=False)
    # 失联标记阈值（分钟）：host_running 超此时长未回执 ⇒ 标 host_lost_at
    # （H4 只标记不自动重试；不迁移状态——接管/重试仍由人）。
    agent_host_lost_mark_minutes: int = Field(default=30, ge=1)
    # goal-d6 试点开关族（PRD §10 / 技术文档 S1-7 / 总纲 UM-1）：30 天 / 10 run
    # 先到为准；窗口内超限 409 pilot_run_limit_exceeded，窗口走完不再拦（试点
    # 结束由报告定升级）。started_at 留空 = 以最早 agent_run.created_at 推导
    # （首个 run 即试点启动）；演练 run（rehearsal: 前缀幂等键）不计数。
    # ★max_runs 默认 10＝文档拍板值对齐（2026-11-13 OWNER 拍板「保守值优先」，
    #   收口 backlog「代码 20 vs 文档 10」口径差；此前默认 20 属实现自由裁量）。
    agent_pilot_enabled: bool = False
    agent_pilot_window_days: int = Field(default=30, ge=1)
    agent_pilot_max_runs: int = Field(default=10, ge=1)
    agent_pilot_started_at: str = ""
    # run 卡死恢复新鲜窗口（分钟）：窗口内不许恢复（防误恢复在途 run）；
    # 0 = 立即可恢复（测试口径）
    agent_recover_stale_minutes: int = Field(default=15, ge=0)
    # goal-d7 O-3 额度族（自动交付 §6）：¥3,980/年含 100 次「工作台动作」/月，
    # seat 归集；0 = 不限额。超额**只标注不拦截**（over_quota=true + 加油包
    # 入口）——「交付中途绝不静默断供」，只限速不限质。
    seat_action_quota_monthly: int = Field(default=100, ge=0)
    # 加油包计价（透明计价，价格前置公示）：¥0.5–2/次量级，此处为公示价签
    seat_action_pack_price_yuan: float = Field(default=1.0, ge=0)
    seat_action_pack_note: str = "加油包按次计价（¥0.5–2/次量级，价格前置公示），只限速不限质；用尽次月自动恢复。"
    # 30 天重校钩子（自动交付 §6 重校条款）：窗口起点留空 = 以最早
    # seat_action_ledger.created_at 推导；到期后配额响应标 review_due（回写人工）
    seat_quota_review_days: int = Field(default=30, ge=1)
    seat_quota_started_at: str = ""
    # goal-d7 PM-2 内容层（PartyMode §4.2）：角色卡处方话术禁令（逗号分隔
    # denylist；persona 发言命中即 422 persona_prescription_blocked，质量守卫
    # 抽查的系统级落点）
    persona_forbidden_patterns: str = "你应该签,你不该签,必须签,建议签署,不应该签"
    # goal-d7 M7 中断恢复：live/paused 会议超时自动收场阈值（小时，懒收场——
    # 会议访问点触发 reap）；恢复窗口同此值（≤24h）
    meeting_stale_close_hours: int = Field(default=24, ge=1)
    # T-A9 转写草稿区（goal-tb tb1）：独立文件根（物理隔离，与 .fde-storage
    # 上传存储不共根）+ T+7 自动清理保留天数。只收文本——录音原件永不进本根
    # （SOP :109/:111 红线）；引擎不进平台依赖，engine 字段纯来源标注。
    transcript_draft_root: Path = Path(".fde-transcript-drafts")
    transcript_draft_retention_days: int = Field(default=7, ge=1)
    # ── 获客诊断工具（T-10a）：匿名免注册诊断面 ─────────────────────────
    # 本仓第一个公网免注册写面 ⇒ **默认关闭**：主部署不暴露匿名写面。
    # D-3 独立轻部署：诊断面单独 compose / 单独库 / 单独域名，与工作台真相层
    # 物理隔离；关闭时路由一律 404（不确认面存在）。
    diagnostics_enabled: bool = False
    # 公开写面的限流故障策略：**默认 fail-closed**（与登录面默认 fail-open 相反
    # ——匿名面被刷的代价高得多；Redis 挂了宁可拒绝新会话，不可放开）。
    diagnostics_rate_fail_closed: bool = True
    # 每 IP 每日动作上限（创建会话 / 测算 / 答题 / 留资 共用一个计数）
    diagnostics_daily_ip_limit: int = Field(default=20, ge=1)
    # 每匿名令牌的当日动作配额。
    # ★T-10b 校准：访客走完主流程要 5 个动作（首屏测算 / 续填 / 留资 / 报告受理
    # / 生成分享链接）＋1 次重试余量 ⇒ 配额 3 会把**正常访客**挡在门外（实测：
    # 生成报告与分享链接撞 429）。IP 每日上限仍是更宽的那道闸。
    diagnostics_session_quota: int = Field(default=6, ge=1)
    # ── 获客诊断工具（T-10b）：AI 报告的服务账号 ───────────────────────
    # 匿名访客没有账号，而 execute_ai_prompt 要求真实 users 行（预算闸与归因
    # 台账都要有主体）⇒ 报告生成走**平台服务账号**：此处填一个既有用户名，
    # AI 用量与审计如实记在它头上。**留空 = 报告功能不可用**（受理时 503
    # fail-closed，不静默降级成「没有报告」）。
    diagnostics_ai_actor_username: str = ""
    # ── 模拟域 L-B 模型评估：AI 记账服务账号（billing_actor_policy 机制化） ──
    # 模拟域真模型评估（学习闭环 2.0 L6 条款④）的政策是**以平台服务账号
    # 记账**（候选卡 provenance.billing_actor_policy=service_account 声明），
    # 本键把声明落成机制：配置后，模拟模型评估的预算闸与 ai_call_audits
    # 归因落到该既有用户名头上（与诊断域键隔离，防跨域串账）。
    # **留空＝机制关（opt-in）**：行为与现状完全一致——请求腿记调用者、
    # 无主背景腿 fail-open（零回归）；配置了账号不存在/已停用 ⇒ fail-closed
    # 503（仿 diagnostics_ai_actor_username 先例），不静默降级。
    simulation_ai_actor_username: str = ""
    # ── 获客诊断工具（T-16 价格轮）：转化费比例（**配置面**） ───────────
    # 三档归因的转化费为**比例制**（蔡工 2026-11-12 拍板④，按推荐执行＋留痕
    # 可推翻）：A 渠道报备缺省 20%、B 认领转化缺省 10%（C 平台留存零转化费，
    # 不走比例）。比例数值**只在配置面**——模型列零比例零金额字段（静态钉
    # 不变），认领单投影不携带比例数字（dispatch 域「报价/收款明细不出响应」
    # 同款纪律）。取值 0~1 的小数；越界启动即炸——商业口径错配宁可起不来，
    # 不可带错跑（也挡住「填 20 想表达 20%」的经典笔误）。
    diagnostics_fee_ratio_tier_a: Decimal = Field(default=Decimal("0.20"), ge=0, le=1)
    diagnostics_fee_ratio_tier_b: Decimal = Field(default=Decimal("0.10"), ge=0, le=1)

    model_config = SettingsConfigDict(
        env_prefix="FDE_",
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    @model_validator(mode="after")
    def validate_storage_environment(self) -> "Settings":
        if self.storage_backend == "local":
            return self

        if not all(
            (
                self.oss_endpoint,
                self.oss_bucket,
                self.oss_access_key_id,
                self.oss_access_key_secret,
            )
        ):
            raise ValueError("missing_oss_configuration")

        return self

    @model_validator(mode="after")
    def validate_dsh_configuration(self) -> "Settings":
        if self.dsh_enabled and self.dsh_service_token is None:
            raise ValueError("missing_dsh_service_token")
        if self.dsh_enabled and not self.dsh_runtime_version.strip():
            raise ValueError("missing_dsh_runtime_version")
        return self

    @model_validator(mode="after")
    def validate_dsh_market_configuration(self) -> "Settings":
        parsed = urlparse(self.dsh_market_registry_url)
        if self.dsh_market_enabled and (
            parsed.scheme not in ({"https"} if self.env == "production" else {"http", "https"})
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("invalid_dsh_market_registry_url")
        return self

    @model_validator(mode="after")
    def validate_clawbot_configuration(self) -> "Settings":
        if self.clawbot_enabled and self.clawbot_gateway_token is None:
            raise ValueError("missing_clawbot_gateway_token")
        return self

    @model_validator(mode="after")
    def validate_ses_configuration(self) -> "Settings":
        if not self.ses_enabled:
            return self
        if not self.ses_send_subdomain.strip() or not self.ses_from_address.strip():
            raise ValueError("missing_ses_sender_configuration")
        if not self.ses_topic_arn.strip():
            raise ValueError("missing_ses_topic_arn")
        # 发信域约束在启动时就校验：FROM 地址必须落在允许子域内（主域不发信）。
        domain = self.ses_from_address.rsplit("@", 1)[-1]
        from fde_api.mailing.policy import is_allowed_sender_domain

        if not is_allowed_sender_domain(domain, self.ses_send_subdomain):
            raise ValueError("ses_sender_domain_forbidden")
        return self
