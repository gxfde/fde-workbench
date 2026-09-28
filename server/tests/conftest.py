from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import Session

from fde_api.app import create_app
from fde_api.config import Settings
from fde_api.extensions import db


SERVER_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def test_settings(tmp_path_factory):
    return Settings(
        env="test",
        database_url="mysql+pymysql://fde_local:change%5Fme@127.0.0.1:3306/fde_workbench_test",
        redis_url="redis://127.0.0.1:6379/2",
        jwt_secret="test-secret-with-at-least-thirty-two-characters",
        local_storage_root=tmp_path_factory.mktemp("fde-object-storage"),
    )


@pytest.fixture
def settings(test_settings, tmp_path):
    return test_settings.model_copy(
        update={"local_storage_root": tmp_path / "object-storage"}
    )


@pytest.fixture
def alembic_config(test_settings):
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["settings"] = test_settings
    return config


@pytest.fixture
def engine(test_settings):
    database_engine = create_engine(test_settings.database_url)
    try:
        yield database_engine
    finally:
        database_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_test_schema(test_settings):
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["settings"] = test_settings
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield


@pytest.fixture
def app(settings):
    app = create_app(settings)
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app) -> Session:
    from fde_api.auth.models import RefreshSession, User
    from fde_api.documents.models import (
        DocumentGenerationJob,
        DocumentTemplate,
        DocumentTemplateVersion,
        ProjectDocument,
        ProjectDocumentDraft,
        ProjectDocumentVersion,
    )
    from fde_api.files.models import ProjectFile, ProjectFileVersion, UploadSession
    from fde_api.jobs.models import BackgroundJob, OutboxEvent
    from fde_api.control.models import (
        AIModelConfig,
        AIProviderConfig,
        AutomationApproval,
        AutomationTask,
        AutomationTaskRun,
        ChannelBinding,
        KnowledgeSnapshot,
        PluginChangeRequest,
        PluginInstallation,
        PluginInstallationRevision,
        PluginCatalogSync,
        PluginPackage,
        SkillDefinition,
        SkillVersion,
        UserAIAccessGrant,
    )
    from fde_api.guidance.models import ProjectGuidanceAnalysis, ProjectPresurveySource
    from fde_api.research.models import (
        ProjectAIOpportunityProfile,
        ProjectResearchPersonalMemo,
        ProjectResearchAnswer,
        ProjectResearchForm,
        ProjectResearchExport,
        ProjectResearchFormRevision,
        ProjectResearchImportBatch,
        ProjectResearchSubject,
        ProjectResearchSubjectLink,
        TemplateResearchField,
        TemplateResearchForm,
        TemplateResearchSection,
    )
    from fde_api.workbench.models import (
        IndustryTemplate,
        IndustryTemplateVersion,
        ModuleCatalog,
        OperationEvent,
        Project,
        ProjectMember,
        ProjectModule,
        ProjectTask,
        ProjectTaskCollaborator,
        ProjectTaskDependency,
        TemplateModule,
        TemplateTask,
        TemplateTaskDependency,
    )

    cleanup_models = (
        __import__("fde_api.system_configuration", fromlist=["SystemConfiguration"]).SystemConfiguration,
        __import__("fde_api.solutions.models", fromlist=["ProjectSolutionExport"]).ProjectSolutionExport,
        __import__("fde_api.solutions.models", fromlist=["ProjectSolutionOpportunity"]).ProjectSolutionOpportunity,
        __import__("fde_api.solutions.models", fromlist=["ProjectSolution"]).ProjectSolution,
        __import__("fde_api.control.chat", fromlist=["AIChatTurn"]).AIChatTurn,
        __import__("fde_api.control.chat", fromlist=["AIConversation"]).AIConversation,
        __import__("fde_api.control.lcsc_skills", fromlist=["LcscSkillRun"]).LcscSkillRun,
        __import__("fde_api.control.weixin_models", fromlist=["WeixinInbox"]).WeixinInbox,
        __import__("fde_api.control.weixin_models", fromlist=["WeixinAccount"]).WeixinAccount,
        __import__("fde_api.control.model_preferences", fromlist=["ModelPreference"]).ModelPreference,
        AIModelConfig,
        AIProviderConfig,
        PluginChangeRequest,
        PluginInstallationRevision,
        PluginInstallation,
        PluginCatalogSync,
        PluginPackage,
        SkillVersion,
        SkillDefinition,
        AutomationApproval,
        AutomationTaskRun,
        KnowledgeSnapshot,
        AutomationTask,
        ChannelBinding,
        UserAIAccessGrant,
        ProjectResearchExport,
        DocumentGenerationJob,
        ProjectDocumentVersion,
        ProjectDocumentDraft,
        ProjectDocument,
        DocumentTemplateVersion,
        DocumentTemplate,
        ProjectFileVersion,
        UploadSession,
        ProjectFile,
        OutboxEvent,
        BackgroundJob,
        ProjectResearchAnswer,
        ProjectResearchImportBatch,
        ProjectResearchFormRevision,
        ProjectResearchForm,
        ProjectResearchSubjectLink,
        ProjectResearchPersonalMemo,
        ProjectAIOpportunityProfile,
        ProjectResearchSubject,
        TemplateResearchField,
        TemplateResearchSection,
        TemplateResearchForm,
        OperationEvent,
        ProjectTaskDependency,
        ProjectTaskCollaborator,
        ProjectTask,
        ProjectModule,
        ProjectMember,
        Project,
        TemplateTaskDependency,
        TemplateTask,
        TemplateModule,
        IndustryTemplateVersion,
        IndustryTemplate,
        ModuleCatalog,
        RefreshSession,
        User,
    )

    def _clear_tables(engine) -> None:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE project_research_forms SET current_revision_id = NULL")
            )
            connection.execute(
                text("UPDATE project_research_form_revisions SET parent_revision_id = NULL")
            )
            connection.execute(
                text("UPDATE project_research_subjects SET parent_subject_id = NULL")
            )
            connection.execute(
                text("UPDATE project_files SET current_version_id = NULL")
            )
            connection.execute(
                text("UPDATE project_file_versions SET parent_version_id = NULL")
            )
            connection.execute(
                text("UPDATE project_file_versions SET preview_version_id = NULL")
            )
            connection.execute(
                text("UPDATE project_documents SET current_version_id = NULL")
            )
            connection.execute(
                text("UPDATE project_document_versions SET parent_version_id = NULL")
            )
            for model in cleanup_models:
                connection.execute(delete(model))

    with app.app_context():
        engine = db.engine
        _clear_tables(engine)
        session = db.session()
        try:
            yield session
        finally:
            session.rollback()
            session.close()
            _clear_tables(engine)
