import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from fde_api.app import create_app
from fde_api.config import Settings
from fde_api.extensions import db


SERVER_ROOT = Path(__file__).resolve().parents[1]

_ALLOWED_TEST_DATABASE_NAMES = {"fde_workbench_test"}

# 测试初始口令单点：曾散落在 14 个测试文件里重复定义同一字面量，持续制造
# secret 扫描噪声（评审会跟进清单 P3-7）。合成值，改口令只改这里。
INITIAL_PASSWORD = "InitialPass!234"
_FORBIDDEN_DATABASE_NAMES = {
    "fde_workbench",
    "twenty",
    "postgres",
    "template0",
    "template1",
}


def _read_local_db_password() -> str:
    env_path = SERVER_ROOT.parent / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "FDE_DB_PASSWORD":
            return value.strip()
    return ""


def resolve_test_database_url() -> str:
    """Resolve the dedicated PostgreSQL test database URL.

    Safety contract (goal prompt §0.6): tests must never fall back to the
    development/production FDE_DATABASE_URL, and the resolved database name
    must be an allowed test database before any migration (downgrade) runs.
    """
    url = os.environ.get("FDE_TEST_DATABASE_URL", "").strip()
    if not url:
        password = _read_local_db_password()
        if password:
            url = (
                "postgresql+psycopg://fde:"
                + quote_plus(password)
                + "@127.0.0.1:15432/fde_workbench_test"
            )
    if not url:
        raise RuntimeError(
            "FDE_TEST_DATABASE_URL is required: point it at a dedicated "
            "PostgreSQL test database, e.g. "
            "postgresql+psycopg://fde:<password>@127.0.0.1:15432/fde_workbench_test"
        )
    parsed = make_url(url)
    if parsed.drivername != "postgresql+psycopg":
        raise RuntimeError(
            "Refusing to run tests with driver "
            f"{parsed.drivername!r}: only postgresql+psycopg is supported"
        )
    database_name = parsed.database or ""
    if (
        database_name in _FORBIDDEN_DATABASE_NAMES
        or database_name not in _ALLOWED_TEST_DATABASE_NAMES
        and not database_name.endswith("_test")
    ):
        raise RuntimeError(
            "Refusing to run tests against database "
            f"{database_name!r}: a dedicated *_test database is required"
        )
    # 安全契约的另一半：远端机器上的 *_test 同样可能承载真实数据，而测试
    # 会迁移/清表/降级——只允许指向本机回环地址。
    host = (parsed.host or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError(
            "Refusing to run tests against host "
            f"{host!r}: only loopback test databases are allowed"
        )
    return url


@pytest.fixture(scope="session")
def test_settings(tmp_path_factory):
    return Settings(
        env="test",
        database_url=resolve_test_database_url(),
        redis_url=os.environ.get("FDE_TEST_REDIS_URL", "redis://127.0.0.1:16379/2"),
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


_SESSION_LOCK_KEY = "fde_workbench_test_session"


@pytest.fixture(scope="session", autouse=True)
def migrated_test_schema(test_settings):
    assert test_settings.env == "test"
    assert make_url(test_settings.database_url).database.endswith("_test")
    # 会话级 PG advisory lock：本机/CI 上若有两个 pytest 进程同时指向同一
    # 测试库（运行器重复派发、并行任务），迁移 downgrade/upgrade 与每用例
    # 清理会互相踩踏（死锁/表消失的假失败）。持锁串行化整个测试会话。
    lock_engine = create_engine(test_settings.database_url)
    lock_conn = lock_engine.connect()
    try:
        lock_conn.execute(text(f"SELECT pg_advisory_lock(hashtext('{_SESSION_LOCK_KEY}'))"))
    except Exception:
        lock_conn.close()
        lock_engine.dispose()
        raise
    try:
        config = Config(str(SERVER_ROOT / "alembic.ini"))
        config.attributes["settings"] = test_settings
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        # 项目建行的 projects.sop_phase 外键指向 sop_nodes.node_key，生产环境由
        # load_seeds.py 灌入 SOP 快照；测试库迁移后同样灌入，保证同一行为。
        seed_reference_data(test_settings.database_url)
        yield
    finally:
        lock_conn.execute(text(f"SELECT pg_advisory_unlock(hashtext('{_SESSION_LOCK_KEY}'))"))
        lock_conn.close()
        lock_engine.dispose()


def seed_reference_data(database_url: str) -> None:
    """迁移到 head 后灌 sop_nodes / module_catalog 引用种子（A1：种子是投影）。

    独立成函数：test_migrations 的 roundtrip 用例 downgrade→upgrade(head)
    会把这两张表重建为空，每个 roundtrip 回到 head 后都必须重灌，否则
    后续所有建项目的测试撞 fk_projects_sop_phase_sop_nodes。
    """
    if str(SERVER_ROOT) not in sys.path:
        sys.path.insert(0, str(SERVER_ROOT))
    from load_seeds import _upsert_module_catalog, _upsert_sop_nodes

    engine = create_engine(database_url)
    try:
        with Session(engine) as session, session.begin():
            _upsert_sop_nodes(session)
            _upsert_module_catalog(session)
    finally:
        engine.dispose()


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
    from fde_api.guidance.models import PresurveyIntake, ProjectGuidanceAnalysis, ProjectPresurveySource
    from fde_api.jobs.models import BackgroundJob, OutboxEvent
    from fde_api.mailing.models import MailingEvent, MailingSend
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
    # goal-d3：agent 表簇（artifacts/tool_calls 引用 runs，runs 被
    # project_solutions.agent_run_id 引用——清理序见 cleanup_models 注释）。
    from fde_api.agents.models import (
        AgentArtifact,
        AgentCredential,
        AgentRegistry,
        AgentRun,
        AgentToolCall,
        SolutionReviewCheckpoint,
    )

    cleanup_models = (
        __import__("fde_api.system_configuration", fromlist=["SystemConfiguration"]).SystemConfiguration,
        # 派单簇（goal-r2 起）：结算/offer 先于包（FK RESTRICT），包先于
        # project_solutions/projects/quotes；证据链与档案先于 users。
        # goal-r3：package_access 先于包（FK RESTRICT）。
        __import__("fde_api.dispatch.models", fromlist=["PackageAccess"]).PackageAccess,
        # goal-r6：disputes 引用包（FK RESTRICT），先于包清理。
        __import__("fde_api.dispatch.models", fromlist=["Dispute"]).Dispute,
        __import__("fde_api.dispatch.models", fromlist=["DeliverySettlement"]).DeliverySettlement,
        __import__("fde_api.dispatch.models", fromlist=["DispatchOffer"]).DispatchOffer,
        __import__("fde_api.dispatch.models", fromlist=["DeliveryPackage"]).DeliveryPackage,
        __import__("fde_api.dispatch.models", fromlist=["DispatchRuleVersion"]).DispatchRuleVersion,
        __import__("fde_api.dispatch.models", fromlist=["FdeLevelEvidence"]).FdeLevelEvidence,
        __import__("fde_api.dispatch.models", fromlist=["FdeProfile"]).FdeProfile,
        # goal-d5：纪要/话轮/会议（minutes→turns→meetings 子表先清；话轮
        # 引用 agent_registry RESTRICT，会议引用 projects/users RESTRICT）。
        __import__("fde_api.meetings.models", fromlist=["ReviewMeetingMinutes"]).ReviewMeetingMinutes,
        __import__("fde_api.meetings.models", fromlist=["ReviewMeetingTurn"]).ReviewMeetingTurn,
        __import__("fde_api.meetings.models", fromlist=["ReviewMeeting"]).ReviewMeeting,
        # goal-d7：O-3 额度台账（ref_id 为软引用，只挂 projects/users RESTRICT）
        __import__("fde_api.agents.models", fromlist=["SeatActionLedger"]).SeatActionLedger,
        # goal-d9：翻译器草稿（created_by 挂 users RESTRICT，先于 users 清）
        __import__("fde_api.translator.models", fromlist=["TranslatorTranslation"]).TranslatorTranslation,
        # goal-d3：审核节点与产物引用 project_solutions（RESTRICT），先于方案；
        # tool_calls/artifacts 引用 runs，同样先清。
        __import__("fde_api.agents.models", fromlist=["SolutionReviewCheckpoint"]).SolutionReviewCheckpoint,
        __import__("fde_api.agents.models", fromlist=["AgentToolCall"]).AgentToolCall,
        __import__("fde_api.agents.models", fromlist=["AgentArtifact"]).AgentArtifact,
        __import__("fde_api.solutions.models", fromlist=["ProjectSolutionExport"]).ProjectSolutionExport,
        __import__("fde_api.solutions.models", fromlist=["ProjectSolutionOpportunity"]).ProjectSolutionOpportunity,
        __import__("fde_api.solutions.models", fromlist=["ProjectSolution"]).ProjectSolution,
        # goal-d3：runs 被 project_solutions.agent_run_id 引用（RESTRICT），先于
        # runs 清方案；registry 被 runs 引用，先清 runs。
        __import__("fde_api.agents.models", fromlist=["AgentRun"]).AgentRun,
        __import__("fde_api.agents.models", fromlist=["AgentCredential"]).AgentCredential,
        __import__("fde_api.agents.models", fromlist=["AgentRegistry"]).AgentRegistry,
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
        ProjectGuidanceAnalysis,
        ProjectPresurveySource,
        # goal-d1：录入卡引用 projects/users（RESTRICT），先于两表清理。
        PresurveyIntake,
        ProjectFileVersion,
        UploadSession,
        ProjectFile,
        OutboxEvent,
        BackgroundJob,
        MailingSend,
        MailingEvent,
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
        # V3 T-E1：一等证据引用 projects（CASCADE）/users（SET NULL），显式先清
        __import__("fde_api.evidence.models", fromlist=["ProjectEvidence"]).ProjectEvidence,
        # V3 T-O1：别名引用 terms（CASCADE），terms 引用 projects/users + 自引用
        # canonical（SET NULL），均先于 projects/users 清理
        __import__("fde_api.ontology.models", fromlist=["OntologyTermAlias"]).OntologyTermAlias,
        __import__("fde_api.ontology.models", fromlist=["OntologyTerm"]).OntologyTerm,
        # V3 T-O2：类型注册表引用 projects（CASCADE）/users（SET NULL），先于两表清理
        __import__(
            "fde_api.ontology.models", fromlist=["OntologyRelationType"]
        ).OntologyRelationType,
        # V3 T-O3：变更集引用 projects（CASCADE）/users（SET NULL），先于两表清理
        __import__(
            "fde_api.ontology.models", fromlist=["OntologyChangeSet"]
        ).OntologyChangeSet,
        # V3 T-W2：node_runs 引用 runs（CASCADE），runs 引用 definitions（RESTRICT，
        # 故必须先于 definitions 清理）与 projects/users
        __import__("fde_api.workflows.models", fromlist=["WorkflowNodeRun"]).WorkflowNodeRun,
        __import__("fde_api.workflows.models", fromlist=["WorkflowRun"]).WorkflowRun,
        # V3 T-W1：workflow 版本行引用 definitions（CASCADE），definitions 引用
        # projects/users（RESTRICT/SET NULL），均先于两表清理
        __import__("fde_api.workflows.models", fromlist=["WorkflowDefinitionVersion"]).WorkflowDefinitionVersion,
        __import__("fde_api.workflows.models", fromlist=["WorkflowDefinition"]).WorkflowDefinition,
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
            # V3 T-O4b：合并指向是同表自引用外键（RESTRICT），清理先解除再删行。
            connection.execute(
                text("UPDATE project_research_subjects SET merged_into_subject_id = NULL")
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
