"""Flask 应用装配（蓝图注册的**唯一权威**）。

蓝图注册序写在 ``_BLUEPRINT_SPECS`` 一张表里，应用装配与审计清单生成共用同一个
来源。此前审计脚本另抄了一份硬编码列表，已漏条三次（T-J2/CR-027 的两个 admin
面板、#145 的 fact_chain_blueprint、#177 前审计）——那类漏条是**流程纪律**挡不住
的（人记得住一次，记不住十次），因此本轮把它变成机器可校验的单一来源：
``iter_blueprints()`` 出货一次，``server/tests/test_blueprint_registry_sync.py``
双向比对「本表 vs 实际注册」。

导入一律惰性（``import_module`` 在函数内完成）：部分蓝图模块与 control/agents
存在模块级互相引用，顶层 import 会把导入序变成地雷——仓库既有惯例就是函数内
惰性导入（``control.service`` → workflows 同款）。
"""
from __future__ import annotations

from collections.abc import Iterator
from importlib import import_module

from flask import Blueprint, Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from fde_api.config import Settings
from fde_api.errors import register_error_handlers
from fde_api.extensions import db, object_storage, redis_client
from fde_api.system_configuration import apply_persisted_configuration

# 蓝图注册序（唯一权威）：形如 (模块路径, 蓝图属性名)。
# 顺序即注册顺序——审计清单的 route CSV 顺序与桌面控制台呈现顺序都依赖它。
_BLUEPRINT_SPECS: tuple[tuple[str, str], ...] = (
    ("fde_api.health", "health_blueprint"),
    ("fde_api.auth.routes", "auth_blueprint"),
    ("fde_api.ai.routes", "ai_blueprint"),
    ("fde_api.users", "users_blueprint"),
    ("fde_api.system_configuration", "blueprint"),
    ("fde_api.modules", "modules_blueprint"),
    ("fde_api.templates", "templates_blueprint"),
    ("fde_api.research.template_routes", "template_research_blueprint"),
    ("fde_api.projects", "projects_blueprint"),
    ("fde_api.workbench.routes", "workbench_blueprint"),
    ("fde_api.bridge", "bridge_blueprint"),
    ("fde_api.research.project_routes", "project_research_blueprint"),
    ("fde_api.storage.local_routes", "local_storage_blueprint"),
    ("fde_api.files.routes", "files_blueprint"),
    ("fde_api.documents.template_routes", "document_templates_blueprint"),
    ("fde_api.documents.project_routes", "project_documents_blueprint"),
    ("fde_api.solutions.routes", "solutions_blueprint"),
    ("fde_api.evidence.routes", "evidence_blueprint"),
    ("fde_api.evidence.routes", "fact_chain_blueprint"),
    ("fde_api.ontology.routes", "ontology_blueprint"),
    ("fde_api.ontology.routes", "global_ontology_blueprint"),
    ("fde_api.expirations", "blueprint"),
    ("fde_api.workflows.routes", "workflows_blueprint"),
    ("fde_api.dispatch.routes", "blueprint"),
    ("fde_api.guidance.routes", "guidance_blueprint"),
    ("fde_api.agents.routes", "agents_blueprint"),
    ("fde_api.jobs.admin_routes", "admin_jobs_blueprint"),
    ("fde_api.dispatch.admin_routes", "admin_dispatch_blueprint"),
    ("fde_api.meetings.routes", "meetings_blueprint"),
    ("fde_api.transcripts.routes", "transcripts_blueprint"),
    ("fde_api.handover.routes", "handover_blueprint"),
    ("fde_api.discovery.routes", "discovery_blueprint"),
    ("fde_api.plans.routes", "plans_blueprint"),
    ("fde_api.quality.routes", "quality_blueprint"),
    ("fde_api.metrics.routes", "metrics_blueprint"),
    ("fde_api.translator.routes", "translator_blueprint"),
    ("fde_api.mailing.routes", "mailing_blueprint"),
    ("fde_api.control", "control_blueprint"),
    ("fde_api.control.task_board", "task_board_blueprint"),
    ("fde_api.control.extension_management_routes", "management_blueprint"),
    ("fde_api.control.clawbot_weixin", "weixin_blueprint"),
    ("fde_api.control.mcp_gateway", "mcp_blueprint"),
    ("fde_api.control.chat", "chat_blueprint"),
    ("fde_api.control.lcsc_skills", "lcsc_blueprint"),
    ("fde_api.control.lcsc_desktop", "desktop_lcsc_blueprint"),
    ("fde_api.control.api_actions", "actions_blueprint"),
    ("fde_api.simulation.routes", "simulation_blueprint"),
    ("fde_api.commercial.routes", "commercial_blueprint"),
    ("fde_api.commercial.admin_routes", "admin_commercial_blueprint"),
)


def iter_blueprints() -> Iterator[Blueprint]:
    """按注册序产出全部蓝图（唯一权威序）。

    审计清单生成脚本（``scripts/audit/extract_workbench_inventory.py``）直接用
    本函数派生蓝图列表——不再照抄一份硬编码清单，也不再调 ``create_app``
    （那会牵出 DB/Redis 初始化）。
    """
    for module_path, attribute in _BLUEPRINT_SPECS:
        module = import_module(module_path)
        blueprint = getattr(module, attribute)
        if not isinstance(blueprint, Blueprint):
            raise RuntimeError(
                f"{module_path}.{attribute} 不是 Flask Blueprint"
                "——蓝图注册表登记有误（新增/改名蓝图时必须同步 _BLUEPRINT_SPECS）"
            )
        yield blueprint


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or Settings()
    app = Flask(__name__)
    app.config["SETTINGS"] = settings

    db.init_app(app, settings)
    redis_client.init_app(app, settings)
    object_storage.init_app(app, settings)
    from fde_api.control.dsh_runtime import dsh_runtime

    dsh_runtime.init_app(app, settings)
    apply_persisted_configuration(app)
    register_error_handlers(app)
    for blueprint in iter_blueprints():
        app.register_blueprint(blueprint)

    from fde_api.control.ai_server_client import apply_runtime_plugin
    from fde_api.control.chat import weixin_message_handler

    app.extensions["fde_weixin_message_handler"] = weixin_message_handler
    app.extensions["fde_plugin_executor"] = apply_runtime_plugin
    from fde_api.cli import register_cli

    register_cli(app)

    # 反向代理拓扑：外部客户端 -> Nginx(宿主) -> 127.0.0.1:8010 -> Gunicorn。
    # 8010 只绑回环且公网不可达，X-Forwarded-For 只能由本机 Nginx 覆盖写入
    # （客户端自带值已被丢弃），因此只信任一跳是安全的。ProxyFix 改写
    # REMOTE_ADDR 后，auth 的「用户名 + 来源 IP」限流键能取到真实客户端 IP；
    # 宿主回环直连的请求无 XFF，仍按 Docker 网桥网关计数，运维接口不受影响。
    # 只开 x_for，不动 scheme/host/port，缩小对 URL 生成与其它中间件的影响面。
    # Flask 的类型存根把 wsgi_app 声明为方法，赋值必然触发 method-assign；
    # 这是存局限定，不是运行时错误，故只在该行豁免，不扩进 mypy 基线。
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)  # type: ignore[method-assign]

    return app
