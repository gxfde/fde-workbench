from flask import Flask

from fde_api.auth.routes import auth_blueprint
from fde_api.ai.routes import ai_blueprint
from fde_api.cli import register_cli
from fde_api.config import Settings
from fde_api.control import control_blueprint
from fde_api.control.dsh_runtime import dsh_runtime
from fde_api.documents.template_routes import document_templates_blueprint
from fde_api.documents.project_routes import project_documents_blueprint
from fde_api.solutions.routes import solutions_blueprint
from fde_api.errors import register_error_handlers
from fde_api.extensions import db, object_storage, redis_client
from fde_api.files.routes import files_blueprint
from fde_api.health import health_blueprint
from fde_api.guidance.routes import guidance_blueprint
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
    app.register_blueprint(project_research_blueprint)
    app.register_blueprint(local_storage_blueprint)
    app.register_blueprint(files_blueprint)
    app.register_blueprint(document_templates_blueprint)
    app.register_blueprint(project_documents_blueprint)
    app.register_blueprint(solutions_blueprint)
    app.register_blueprint(guidance_blueprint)
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
