from flask import Flask

from fde_api.auth.routes import auth_blueprint
from fde_api.ai.routes import ai_blueprint
from fde_api.cli import register_cli
from fde_api.config import Settings
from fde_api.control import control_blueprint
from fde_api.control.dsh_runtime import dsh_runtime
from fde_api.documents.template_routes import document_templates_blueprint
from fde_api.documents.project_routes import project_documents_blueprint
from fde_api.dispatch.routes import blueprint as dispatch_blueprint
from fde_api.evidence.routes import evidence_blueprint
from fde_api.ontology.routes import ontology_blueprint  # V3 T-O2
from fde_api.workflows.routes import workflows_blueprint  # V3 T-W3
from fde_api.solutions.routes import solutions_blueprint
from fde_api.errors import register_error_handlers
from fde_api.extensions import db, object_storage, redis_client
from fde_api.files.routes import files_blueprint
from fde_api.health import health_blueprint
from fde_api.guidance.routes import guidance_blueprint
from fde_api.mailing.routes import mailing_blueprint
from fde_api.modules import modules_blueprint
from fde_api.projects import projects_blueprint
from fde_api.storage.local_routes import local_storage_blueprint
from fde_api.research.template_routes import template_research_blueprint
from fde_api.research.project_routes import project_research_blueprint
from fde_api.templates import templates_blueprint
from fde_api.users import users_blueprint
from fde_api.system_configuration import blueprint as system_configuration_blueprint, apply_persisted_configuration


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or Settings()
    app = Flask(__name__)
    app.config["SETTINGS"] = settings

    db.init_app(app, settings)
    redis_client.init_app(app, settings)
    object_storage.init_app(app, settings)
    dsh_runtime.init_app(app, settings)
    apply_persisted_configuration(app)
    register_error_handlers(app)
    app.register_blueprint(health_blueprint)
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(ai_blueprint)
    app.register_blueprint(users_blueprint)
    app.register_blueprint(system_configuration_blueprint)
    app.register_blueprint(modules_blueprint)
    app.register_blueprint(templates_blueprint)
    app.register_blueprint(template_research_blueprint)
    app.register_blueprint(projects_blueprint)
    # WP29/J1：业务枚举选项表下发（前端保留本地兜底）
    from fde_api.workbench.routes import workbench_blueprint
    app.register_blueprint(workbench_blueprint)
    # P2 集成桥：真相层（openfde/fdeops）→ PG 单向投影
    from fde_api.bridge import bridge_blueprint
    app.register_blueprint(bridge_blueprint)
    app.register_blueprint(project_research_blueprint)
    app.register_blueprint(local_storage_blueprint)
    app.register_blueprint(files_blueprint)
    app.register_blueprint(document_templates_blueprint)
    app.register_blueprint(project_documents_blueprint)
    app.register_blueprint(solutions_blueprint)
    # V3 T-E1：一等证据登记簿（只存指针+指纹；人工写路径有意不进 api_catalog）
    app.register_blueprint(evidence_blueprint)
    # V3 T-O2：本体注册表路由（关系类型登记；术语面随 T-O3 开；人工路径不进 api_catalog）
    app.register_blueprint(ontology_blueprint)
    # V3 T-W3：Workflow 定义/运行路由（§5 五条；cancel/resume 随 T-W5 开）
    app.register_blueprint(workflows_blueprint)
    app.register_blueprint(dispatch_blueprint)
    app.register_blueprint(guidance_blueprint)
    # S1 编程工作台（goal-d4）：agent 注册表 + run 生命周期（适配器/溯源/成本）
    from fde_api.agents.routes import agents_blueprint
    app.register_blueprint(agents_blueprint)
    # V3 T-J2（域 14）：admin 后台任务取消面（幂等/不强杀/留痕，不进 api_catalog）
    from fde_api.jobs.admin_routes import admin_jobs_blueprint
    app.register_blueprint(admin_jobs_blueprint)
    # S1 评审会最小闭环（goal-d5）：T2 强制门 + 纪要封存（技术文档 §6）
    from fde_api.meetings.routes import meetings_blueprint
    app.register_blueprint(meetings_blueprint)
    # P0/P1 指标报表（goal-d8）：PRD §10 只读聚合
    from fde_api.metrics.routes import metrics_blueprint
    app.register_blueprint(metrics_blueprint)
    # P3 翻译器门户（goal-d9）：引导式翻译 + AI 草稿落库
    from fde_api.translator.routes import translator_blueprint
    app.register_blueprint(translator_blueprint)
    # WP-E SES：SNS 退信/投诉回调端点（默认随模块关闭，端点校验失败一律 403）
    app.register_blueprint(mailing_blueprint)
    app.register_blueprint(control_blueprint)
    from fde_api.control.task_board import task_board_blueprint
    from fde_api.control.extension_management_routes import management_blueprint
    from fde_api.control.clawbot_weixin import weixin_blueprint
    from fde_api.control.mcp_gateway import mcp_blueprint
    from fde_api.control.chat import chat_blueprint, weixin_message_handler
    from fde_api.control.lcsc_skills import lcsc_blueprint
    app.register_blueprint(task_board_blueprint)
    app.register_blueprint(management_blueprint)
    app.register_blueprint(weixin_blueprint)
    app.register_blueprint(mcp_blueprint)
    app.register_blueprint(chat_blueprint)
    app.register_blueprint(lcsc_blueprint)
    from fde_api.control.lcsc_desktop import desktop_lcsc_blueprint
    app.register_blueprint(desktop_lcsc_blueprint)
    from fde_api.control.api_actions import actions_blueprint
    app.register_blueprint(actions_blueprint)
    app.extensions["fde_weixin_message_handler"] = weixin_message_handler
    from fde_api.control.ai_server_client import apply_runtime_plugin
    app.extensions["fde_plugin_executor"] = apply_runtime_plugin
    register_cli(app)

    return app
