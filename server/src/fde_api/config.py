from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    env: Literal["development", "test", "production"] = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8010
    database_url: str
    redis_url: str
    jwt_secret: str = Field(min_length=32)
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    storage_backend: Literal["local", "oss"] = "local"
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
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_project_presurvey_api_key: SecretStr | None = Field(default=None, repr=False)
    kimi_project_presurvey_model: str = "kimi-k3"
    # goal-d13 拍板：翻译管道独立 kimi 槽位（key/base_url/model 与预调研分开配，
    # 换档不互相牵连）。base_url 也独立的原因：部署 env 可能把共享 kimi_base_url
    # 指向另一家 OpenAI 兼容供应商（如 minimaxi），若翻译共用该地址，就会拿
    # kimi-k3 去打没有该模型的端点。独立后默认与 kimi-k3 自洽（Moonshot）。
    kimi_translator_api_key: SecretStr | None = Field(default=None, repr=False)
    kimi_translator_base_url: str = "https://api.moonshot.cn/v1"
    kimi_translator_model: str = "kimi-k3"
    kimi_timeout_seconds: int = Field(default=180, ge=10, le=600)
    # Kimi 槽位切到非 Moonshot 供应商（如 MiniMax）时的两个协议开关：
    # - kimi_local_docx_extract=True：供应商不提供 file-extract 文件接口，
    #   改为服务端本地解析 DOCX 取文本后送模型（文件不出本机）
    # - kimi_openai_compatible=True：按通用 OpenAI 兼容端点发请求
    #   （用 max_tokens 而非 max_completion_tokens，不发 reasoning_effort）
    kimi_local_docx_extract: bool = False
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
    # run workspace 根目录（相对路径相对服务端工作目录）
    agent_workspace_root: str = "agent-workspaces"
    # 沙箱内 agent CLI 命令（zcode 适配器 spawn 段）
    agent_cli_command: str = "zcode"
    # goal-d6 试点开关族（PRD §10 / 技术文档 S1-7 / 总纲 UM-1）：30 天 / 20 run
    # 先到为准；窗口内超限 409 pilot_run_limit_exceeded，窗口走完不再拦（试点
    # 结束由报告定升级）。started_at 留空 = 以最早 agent_run.created_at 推导
    # （首个 run 即试点启动）；演练 run（rehearsal: 前缀幂等键）不计数。
    agent_pilot_enabled: bool = False
    agent_pilot_window_days: int = Field(default=30, ge=1)
    agent_pilot_max_runs: int = Field(default=20, ge=1)
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
