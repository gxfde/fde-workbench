from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.control.access import authorize_ai_capability
from fde_api.control.dsh_runtime import DSHExecutionResult
from fde_api.control.scheduler import dispatch_due_automations, next_schedule_time
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
    PluginPackage,
    SkillDefinition,
    SkillVersion,
    UserAIAccessGrant,
)
from fde_api.jobs.models import BackgroundJob, OutboxEvent
from fde_api.jobs.outbox import dispatch_pending
from fde_api.jobs.worker import run_job
from fde_api.workbench.models import ModuleCatalog, Project, ProjectMember, ProjectModule, ProjectTask


PASSWORD = "InitialPass!234"


@dataclass(frozen=True)
class AuthorizedClient:
    client: object
    user: User
    headers: dict[str, str]

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)

    def patch(self, *args, **kwargs):
        return self.client.patch(*args, headers=self.headers, **kwargs)


@pytest.fixture
def authorized_client_factory(client, db_session, settings):
    def create(role: str) -> AuthorizedClient:
        user = User(
            username=f"{role}.{uuid4().hex}",
            display_name=role,
            role=role,
            password_hash=hash_password(PASSWORD),
            must_change_password=False,
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        return AuthorizedClient(client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"})

    return create


def create_project_with_task(db_session, leader: User):
    catalog = ModuleCatalog(module_key=f"module-{uuid4().hex}", name=f"Module {uuid4().hex}", description="")
    project = Project(
        project_code=f"CONTROL-{uuid4().hex[:8]}",
        name="Control plane project",
        enterprise_name="Example",
        planned_start_date=date(2026, 9, 1),
        leader_user_id=leader.id,
        status="active",
        template_snapshot={},
    )
    db_session.add_all([catalog, project])
    db_session.flush()
    module = ProjectModule(
        project_id=project.id,
        module_catalog_id=catalog.id,
        name="Research",
        description="",
        status="active",
    )
    db_session.add(module)
    db_session.flush()
    task = ProjectTask(
        project_module_id=module.id,
        task_key=f"task-{uuid4().hex}",
        name="Interview roles",
        description="",
        status="not_started",
        planned_start_date=date(2026, 9, 1),
        planned_end_date=date(2026, 9, 2),
        duration_days=2,
        progress=0,
    )
    db_session.add(task)
    db_session.commit()
    return project, task


def test_account_exposes_safe_role_default_and_updates_own_display_name(authorized_client_factory):
    viewer = authorized_client_factory("viewer")

    response = viewer.get("/api/v1/account")

    assert response.status_code == 200
    assert response.json["data"]["ai_access"]["level"] == "assistant_read"
    assert "system.release" not in response.json["data"]["ai_access"]["capabilities"]

    updated = viewer.patch("/api/v1/account/profile", json={"display_name": "新名称"})
    assert updated.status_code == 200
    assert updated.json["data"]["display_name"] == "新名称"


def test_personal_skills_are_private_and_create_immutable_versions(
    authorized_client_factory, db_session
):
    engineer = authorized_client_factory("fde_engineer")
    other = authorized_client_factory("fde_engineer")
    payload = {
        "key": "meeting-summary",
        "name": "会议纪要整理",
        "description": "整理个人访谈记录",
        "instructions": "# 会议纪要整理\n仅总结有证据的内容。",
        "manifest": {"entrypoint": "SKILL.md"},
        "required_capabilities": ["project.read"],
    }

    created = engineer.post("/api/v1/extensions/skills/personal", json=payload)
    assert created.status_code == 201, created.get_data(as_text=True)
    assert created.json["data"]["scope"] == "personal"
    assert created.json["data"]["current_version"] == 1

    repeated = engineer.post("/api/v1/extensions/skills/personal", json=payload)
    assert repeated.status_code == 201
    assert repeated.json["data"]["current_version"] == 1

    updated = engineer.post(
        "/api/v1/extensions/skills/personal",
        json={**payload, "instructions": payload["instructions"] + "\n输出待办事项。"},
    )
    assert updated.status_code == 201
    assert updated.json["data"]["current_version"] == 2

    own = engineer.get("/api/v1/extensions")
    others = other.get("/api/v1/extensions")
    assert [item["key"] for item in own.json["data"]["skills"]] == ["meeting-summary"]
    assert others.json["data"]["skills"] == []
    db_session.rollback()
    skill = db_session.scalar(select(SkillDefinition).where(SkillDefinition.skill_key == "meeting-summary"))
    assert db_session.query(SkillVersion).filter_by(skill_id=skill.id).count() == 2

    overreaching = engineer.post(
        "/api/v1/extensions/skills/personal",
        json={**payload, "key": "release-helper", "required_capabilities": ["system.release"]},
    )
    assert overreaching.status_code == 400
    assert overreaching.json["error"]["code"] == "invalid_skill"


def test_extension_center_never_returns_provider_credential_reference(
    authorized_client_factory, db_session
):
    operator = authorized_client_factory("admin")
    viewer = authorized_client_factory("viewer")
    db_session.add(
        UserAIAccessGrant(
            user_id=operator.user.id,
            granted_by_user_id=operator.user.id,
            access_level="system_operator",
            reason="extension test",
        )
    )
    provider = AIProviderConfig(
        provider_key="deepseek",
        display_name="DeepSeek",
        base_url="https://api.deepseek.com",
        credential_ref="kms:alias/fde/deepseek",
        credential_hint="sk-***abcd",
        status="active",
        created_by_user_id=operator.user.id,
    )
    db_session.add(provider)
    db_session.flush()
    db_session.add(
        AIModelConfig(
            provider_id=provider.id,
            model_key="deepseek-chat",
            display_name="DeepSeek Chat",
            context_window=128000,
            supports_tools=True,
            supports_json=True,
            status="active",
        )
    )
    db_session.add(
        PluginPackage(
            plugin_key="official.example",
            name="示例插件",
            description="",
            publisher="FDE",
            current_version="1.0.0",
            manifest_json={"capabilities": ["project.read"]},
            package_sha256="a" * 64,
            verified=True,
            status="active",
            created_by_user_id=operator.user.id,
        )
    )
    db_session.commit()

    operator_response = operator.get("/api/v1/extensions")
    viewer_response = viewer.get("/api/v1/extensions")
    assert operator_response.status_code == viewer_response.status_code == 200
    assert operator_response.json["data"]["providers"][0]["credential_configured"] is True
    assert "credential_ref" not in operator_response.get_data(as_text=True)
    assert "kms:alias/fde/deepseek" not in operator_response.get_data(as_text=True)
    assert viewer_response.json["data"]["providers"] == []
    assert viewer_response.json["data"]["models"][0]["key"] == "deepseek-chat"
    assert viewer_response.json["data"]["plugins"][0]["installation_status"] == "not_installed"


def test_plugin_changes_require_operator_approval_and_keep_rollback_history(
    authorized_client_factory, db_session, app
):
    app.extensions["fde_plugin_executor"] = lambda *, action, plugin: {"status": "installed", "version": plugin["version"], "runtime_version": "test-runtime"}
    operator = authorized_client_factory("admin")
    viewer = authorized_client_factory("viewer")
    db_session.add(UserAIAccessGrant(user_id=operator.user.id, granted_by_user_id=operator.user.id, access_level="system_operator", reason="plugin approvals"))
    plugin = PluginPackage(
        plugin_key=f"official.plugin.{uuid4().hex}", name="受控插件", description="", publisher="FDE",
        current_version="2.0.0", manifest_json={"capabilities": ["project.read"]},
        package_sha256="b" * 64, verified=True, status="active", created_by_user_id=operator.user.id,
    )
    db_session.add(plugin)
    db_session.commit()

    requested = viewer.post(
        f"/api/v1/extensions/plugins/{plugin.id}/requests",
        json={"action": "install", "target_version": "", "reason": "项目使用"},
    )
    assert requested.status_code == 202, requested.get_data(as_text=True)
    request_id = requested.json["data"]["id"]
    assert requested.json["data"]["status"] == "pending"
    assert viewer.post(
        f"/api/v1/extensions/plugin-requests/{request_id}/decision",
        json={"decision": "approve", "reason": "越权"},
    ).status_code == 403

    approved = operator.post(
        f"/api/v1/extensions/plugin-requests/{request_id}/decision",
        json={"decision": "approve", "reason": "权限范围已核对"},
    )
    assert approved.status_code == 200, approved.get_data(as_text=True)
    assert approved.json["data"]["status"] == "executed"
    db_session.rollback()
    installation = db_session.scalar(select(PluginInstallation).where(PluginInstallation.plugin_id == plugin.id, PluginInstallation.user_id == viewer.user.id))
    assert installation.installed_version == "2.0.0"
    assert db_session.query(PluginInstallationRevision).filter_by(installation_id=installation.id).count() == 1

    plugin = db_session.get(PluginPackage, plugin.id)
    plugin.current_version = "3.0.0"
    db_session.commit()
    upgrade = viewer.post(
        f"/api/v1/extensions/plugins/{plugin.id}/requests",
        json={"action": "upgrade", "target_version": "", "reason": "升级"},
    )
    assert upgrade.status_code == 202
    assert operator.post(
        f"/api/v1/extensions/plugin-requests/{upgrade.json['data']['id']}/decision",
        json={"decision": "approve", "reason": "通过"},
    ).status_code == 200
    rollback = viewer.post(
        f"/api/v1/extensions/plugins/{plugin.id}/requests",
        json={"action": "rollback", "target_version": "2.0.0", "reason": "兼容性回退"},
    )
    assert rollback.status_code == 202, rollback.get_data(as_text=True)
    assert operator.post(
        f"/api/v1/extensions/plugin-requests/{rollback.json['data']['id']}/decision",
        json={"decision": "approve", "reason": "回退已核对"},
    ).status_code == 200
    db_session.rollback()
    installation = db_session.scalar(select(PluginInstallation).where(PluginInstallation.plugin_id == plugin.id, PluginInstallation.user_id == viewer.user.id))
    assert installation.installed_version == "2.0.0"
    assert db_session.query(PluginInstallationRevision).filter_by(installation_id=installation.id).count() == 3
    assert db_session.query(PluginChangeRequest).filter_by(plugin_id=plugin.id, status="executed").count() == 3


def test_system_operator_can_publish_public_skill_and_configure_provider_and_model(
    authorized_client_factory, db_session
):
    operator = authorized_client_factory("admin")
    viewer = authorized_client_factory("viewer")
    db_session.add(UserAIAccessGrant(user_id=operator.user.id, granted_by_user_id=operator.user.id, access_level="system_operator", reason="extensions"))
    db_session.commit()
    skill = {
        "key": "project-summary",
        "name": "项目摘要",
        "description": "生成项目摘要",
        "instructions": "只根据项目资料生成摘要。",
        "manifest": {"entrypoint": "SKILL.md"},
        "required_capabilities": ["project.read"],
    }

    denied = viewer.post("/api/v1/extensions/skills/public", json=skill)
    published = operator.post("/api/v1/extensions/skills/public", json=skill)
    provider = operator.post("/api/v1/extensions/providers", json={
        "key": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com",
        "credential_ref": "kms:alias/fde/deepseek", "credential_hint": "已绑定", "status": "active",
    })
    model = operator.post("/api/v1/extensions/models", json={
        "provider_key": "deepseek", "key": "deepseek-chat", "name": "DeepSeek Chat",
        "context_window": 128000, "supports_tools": True, "supports_json": True, "status": "active",
    })

    assert denied.status_code == 403
    assert published.status_code == provider.status_code == model.status_code == 201
    assert published.json["data"]["scope"] == "public"
    assert provider.json["data"]["credential_configured"] is True
    assert model.json["data"]["provider"]["key"] == "deepseek"
    visible = viewer.get("/api/v1/extensions")
    assert visible.json["data"]["skills"][0]["key"] == "project-summary"
    assert visible.json["data"]["models"][0]["key"] == "deepseek-chat"
    assert visible.json["data"]["providers"] == []


def test_provider_configuration_rejects_raw_api_keys(authorized_client_factory, db_session):
    operator = authorized_client_factory("admin")
    db_session.add(UserAIAccessGrant(user_id=operator.user.id, granted_by_user_id=operator.user.id, access_level="system_operator", reason="extensions"))
    db_session.commit()

    response = operator.post("/api/v1/extensions/providers", json={
        "key": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com",
        "credential_ref": "test-credential-must-never-be-stored", "credential_hint": "", "status": "active",
    })

    assert response.status_code == 400
    assert "test-credential-must-never-be-stored" not in response.get_data(as_text=True)


def test_admin_has_full_access_even_with_historical_lower_grant(authorized_client_factory, db_session):
    admin = authorized_client_factory("admin")

    allowed = authorize_ai_capability(user=admin.user, capability="system.release")

    assert allowed.allowed is True
    assert allowed.access_level == "system_operator"

    db_session.add(UserAIAccessGrant(user_id=admin.user.id, granted_by_user_id=admin.user.id, access_level="project_manager", reason="historical role default"))
    db_session.commit()

    allowed = authorize_ai_capability(user=admin.user, capability="system.release")
    assert allowed.allowed is True
    assert allowed.source == "administrator"


def test_wechat_binding_code_is_returned_once_but_only_digest_is_persisted(authorized_client_factory, db_session):
    engineer = authorized_client_factory("fde_engineer")

    response = engineer.post("/api/v1/account/wechat-clawbot/binding", json={})

    assert response.status_code == 201
    code = response.json["data"]["binding_code"]
    assert len(code) == 8
    db_session.rollback()
    binding = db_session.scalar(select(ChannelBinding).where(ChannelBinding.user_id == engineer.user.id))
    assert binding is not None
    assert binding.binding_code_digest == sha256(code.encode("utf-8")).hexdigest()
    assert code not in binding.binding_code_digest


def test_clawbot_completes_binding_and_queues_each_event_exactly_once(
    authorized_client_factory, db_session, app
):
    viewer = authorized_client_factory("viewer")
    leader = authorized_client_factory("project_lead")
    project, project_task = create_project_with_task(db_session, leader.user)
    db_session.add(ProjectMember(project_id=project.id, user_id=viewer.user.id, role="viewer"))
    db_session.commit()
    started = viewer.post("/api/v1/account/wechat-clawbot/binding", json={})
    code = started.json["data"]["binding_code"]

    settings = app.config["SETTINGS"]
    settings.clawbot_enabled = True
    settings.clawbot_gateway_token = SecretStr("clawbot-gateway-secret")
    gateway_headers = {"Authorization": "Bearer clawbot-gateway-secret"}

    denied = viewer.client.post(
        "/api/v1/internal/clawbot/bindings/complete",
        headers={"Authorization": "Bearer wrong"},
        json={"binding_code": code, "external_subject": "wx-open-id-1", "display_name": "微信用户"},
    )
    assert denied.status_code == 401

    completed = viewer.client.post(
        "/api/v1/internal/clawbot/bindings/complete",
        headers=gateway_headers,
        json={"binding_code": code, "external_subject": "wx-open-id-1", "display_name": "微信用户"},
    )
    assert completed.status_code == 200
    assert completed.json["data"]["status"] == "active"

    event = {
        "event_id": "wechat-event-001",
        "external_subject": "wx-open-id-1",
        "project_id": project.id,
        "text": "总结这个项目今天的进展",
    }
    first = viewer.client.post("/api/v1/internal/clawbot/events", headers=gateway_headers, json=event)
    second = viewer.client.post("/api/v1/internal/clawbot/events", headers=gateway_headers, json=event)

    assert first.status_code == second.status_code == 202
    assert first.json["data"]["duplicate"] is False
    assert second.json["data"]["duplicate"] is True
    assert first.json["data"]["task"]["id"] == second.json["data"]["task"]["id"]
    db_session.rollback()
    event_digest = sha256(b"wx-open-id-1\x00wechat-event-001").hexdigest()
    event_key = f"wechat:sha256:{event_digest}"
    assert db_session.query(AutomationTask).filter_by(source_event_id=event_key).count() == 1
    assert db_session.query(AutomationTaskRun).filter_by(idempotency_key=event_key).count() == 1
    assert db_session.query(OutboxEvent).filter_by(topic="automation.execute").count() == 1


def test_task_center_unifies_project_and_wechat_automation_tasks(authorized_client_factory, db_session):
    leader = authorized_client_factory("project_lead")
    viewer = authorized_client_factory("viewer")
    project, project_task = create_project_with_task(db_session, leader.user)
    db_session.add(ProjectMember(project_id=project.id, user_id=viewer.user.id, role="viewer"))
    db_session.commit()

    created = leader.post(
        "/api/v1/task-center/automations",
        json={
            "title": "每日检查项目进度",
            "project_id": project.id,
            "source": "wechat",
            "schedule_kind": "calendar",
            "schedule_expression": "0 9 * * 1-5",
            "timezone": "Asia/Shanghai",
            "prompt": "检查逾期任务，有异常时通知我。",
            "risk_level": 0,
        },
    )
    assert created.status_code == 201, created.get_data(as_text=True)
    assert created.json["data"]["source"] == "wechat"

    listed = leader.get("/api/v1/task-center")
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json["data"]["items"]}
    assert {project_task.id, created.json["data"]["id"]} <= ids
    assert listed.json["data"]["counts"] == {"project": 1, "automation": 1}

    forbidden = viewer.post(
        "/api/v1/task-center/automations",
        json={
            "title": "Should fail",
            "project_id": project.id,
            "schedule_kind": "once",
            "schedule_expression": "2026-09-05T09:00:00+08:00",
            "timezone": "Asia/Shanghai",
            "prompt": "Do something",
        },
    )
    assert forbidden.status_code == 403
    assert forbidden.json["error"]["code"] == "forbidden"


def test_scheduler_dispatches_due_task_once_and_advances_interval(authorized_client_factory, db_session, app):
    leader = authorized_client_factory("project_lead")
    project, _ = create_project_with_task(db_session, leader.user)
    created = leader.post("/api/v1/task-center/automations", json={
        "title": "每小时检查", "project_id": project.id, "schedule_kind": "interval",
        "schedule_expression": "1h", "timezone": "Asia/Shanghai", "prompt": "检查项目进度。",
    })
    assert created.status_code == 201
    db_session.rollback()
    task = db_session.get(AutomationTask, created.json["data"]["id"])
    due = task.next_run_at

    with app.app_context():
        first = dispatch_due_automations(now=due + timedelta(seconds=1))
        second = dispatch_due_automations(now=due + timedelta(seconds=1))

    assert first == 1
    assert second == 0
    db_session.rollback()
    assert db_session.query(AutomationTaskRun).count() == 1
    assert db_session.query(OutboxEvent).filter_by(topic="automation.execute").count() == 1
    db_session.refresh(task)
    assert task.next_run_at == due + timedelta(hours=1)


def test_calendar_schedule_uses_task_timezone_and_rejects_invalid_expression():
    after = datetime(2026, 9, 4, 23, 30, tzinfo=UTC)  # Saturday 07:30 in Shanghai.
    result = next_schedule_time(kind="calendar", expression="0 9 * * 1-5", timezone="Asia/Shanghai", after=after)
    assert result == datetime(2026, 9, 7, 1, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        next_schedule_time(kind="calendar", expression="not cron", timezone="Asia/Shanghai", after=after)


def test_manual_automation_run_is_idempotent_and_dsh_callback_is_authenticated(
    authorized_client_factory, db_session, app
):
    leader = authorized_client_factory("project_lead")
    project, _ = create_project_with_task(db_session, leader.user)
    created = leader.post(
        "/api/v1/task-center/automations",
        json={
            "title": "检查项目进度",
            "project_id": project.id,
            "source": "desktop",
            "schedule_kind": "once",
            "schedule_expression": "2026-09-05T09:00:00+08:00",
            "timezone": "Asia/Shanghai",
            "prompt": "检查逾期任务。",
            "requested_capabilities": ["project.read", "project.summarize"],
        },
    )
    task_id = created.json["data"]["id"]
    headers = {**leader.headers, "Idempotency-Key": "manual-run-1"}

    first = leader.client.post(f"/api/v1/task-center/automations/{task_id}/runs", headers=headers)
    second = leader.client.post(f"/api/v1/task-center/automations/{task_id}/runs", headers=headers)

    assert first.status_code == second.status_code == 202
    assert first.json["data"]["id"] == second.json["data"]["id"]
    db_session.rollback()
    assert db_session.query(AutomationTaskRun).count() == 1
    assert db_session.query(OutboxEvent).filter_by(topic="automation.execute").count() == 1

    run_id = first.json["data"]["id"]
    denied = leader.client.post(
        f"/api/v1/internal/dsh/executions/{run_id}/events",
        headers={"Authorization": "Bearer wrong"},
        json={"status": "succeeded", "output": {}},
    )
    assert denied.status_code == 401

    runtime = app.extensions["fde_api_dsh_runtime"]
    runtime.enabled = True
    runtime.service_token = "dsh-callback-secret"
    completed = leader.client.post(
        f"/api/v1/internal/dsh/executions/{run_id}/events",
        headers={"Authorization": "Bearer dsh-callback-secret"},
        json={
            "status": "succeeded",
            "execution_id": "dsh-execution-1",
            "runtime_version": "1.4.2",
            "summary": "检查完成",
            "output": {"overdue": 0},
        },
    )
    assert completed.status_code == 200
    assert completed.json["data"]["status"] == "succeeded"
    assert completed.json["data"]["runtime_version"] == "1.4.2"


def test_worker_dispatches_only_the_persisted_permission_scope_to_dsh(
    authorized_client_factory, db_session, app
):
    leader = authorized_client_factory("project_lead")
    project, _ = create_project_with_task(db_session, leader.user)
    created = leader.post(
        "/api/v1/task-center/automations",
        json={
            "title": "只读项目摘要",
            "project_id": project.id,
            "source": "desktop",
            "schedule_kind": "once",
            "schedule_expression": "2026-09-05T09:00:00+08:00",
            "timezone": "Asia/Shanghai",
            "prompt": "总结项目进度。",
            "requested_capabilities": ["project.read", "project.summarize"],
        },
    )
    task_id = created.json["data"]["id"]
    queued = leader.client.post(
        f"/api/v1/task-center/automations/{task_id}/runs",
        headers={**leader.headers, "Idempotency-Key": "dispatch-run-1"},
    )
    run_id = queued.json["data"]["id"]
    db_session.rollback()

    class Queue:
        job_ids = []

        def enqueue(self, job_id):
            self.job_ids.append(job_id)

    queue = Queue()
    dispatch_pending(db_session, queue)

    class Runtime:
        runtime_version = "1.4.2"
        calls = []

        def execute(self, **kwargs):
            self.calls.append(kwargs)
            return DSHExecutionResult("external-1", "succeeded", "完成", {"ok": True}, "1.4.2")

        def verify_service_token(self, candidate):
            return candidate == "runtime-secret"

    runtime = Runtime()
    app.extensions["fde_api_dsh_runtime"] = runtime
    assert run_job(queue.job_ids[0]) == "succeeded"

    db_session.expire_all()
    run = db_session.get(AutomationTaskRun, run_id)
    job = db_session.get(BackgroundJob, queue.job_ids[0])
    assert run.status == "succeeded"
    assert run.dsh_runtime_version == "1.4.2"
    assert runtime.calls[0]["allowed_tools"] == ["project.read", "project.summarize"]
    assert runtime.calls[0]["project_id"] == project.id
    assert runtime.calls[0]["context_refs"][0]["kind"] == "knowledge_snapshot"
    assert job.status == "succeeded"
    snapshot = db_session.get(KnowledgeSnapshot, run.knowledge_snapshot_id)
    assert snapshot.payload_json["project"]["id"] == project.id
    assert snapshot.payload_json["tasks"][0]["name"] == "Interview roles"

    knowledge = leader.client.get(
        f"/api/v1/internal/dsh/executions/{run_id}/knowledge",
        headers={"Authorization": "Bearer runtime-secret"},
    )
    assert knowledge.status_code == 200
    assert knowledge.json["data"]["content_sha256"] == snapshot.content_sha256


def test_high_risk_dsh_operation_requires_project_permission_and_current_password(
    authorized_client_factory, db_session, app
):
    leader = authorized_client_factory("project_lead")
    viewer = authorized_client_factory("viewer")
    engineer = authorized_client_factory("fde_engineer")
    project, project_task = create_project_with_task(db_session, leader.user)
    db_session.add_all(
        [
            ProjectMember(project_id=project.id, user_id=viewer.user.id, role="viewer"),
            ProjectMember(project_id=project.id, user_id=engineer.user.id, role="member"),
        ]
    )
    db_session.commit()
    created = leader.post(
        "/api/v1/task-center/automations",
        json={
            "title": "批量分配待处理任务",
            "project_id": project.id,
            "source": "desktop",
            "schedule_kind": "once",
            "schedule_expression": "2026-09-05T09:00:00+08:00",
            "timezone": "Asia/Shanghai",
            "prompt": "将选定任务分配给项目成员。",
            "requested_capabilities": ["project.read", "task.batch_assign"],
        },
    )
    queued = leader.client.post(
        f"/api/v1/task-center/automations/{created.json['data']['id']}/runs",
        headers={**leader.headers, "Idempotency-Key": "approval-run-1"},
    )
    run_id = queued.json["data"]["id"]
    db_session.rollback()
    run = db_session.get(AutomationTaskRun, run_id)
    run.status = "running"
    db_session.commit()

    class ApprovalRuntime:
        def verify_service_token(self, candidate):
            return candidate == "runtime-approval-secret"

    app.extensions["fde_api_dsh_runtime"] = ApprovalRuntime()
    proposed = leader.client.post(
        f"/api/v1/internal/dsh/executions/{run_id}/approvals",
        headers={"Authorization": "Bearer runtime-approval-secret"},
        json={
            "request_id": "tool-call-1",
            "capability": "task.batch_assign",
            "tool_name": "project_tasks.batch_assign",
            "arguments": {
                "member_user_id": engineer.user.id,
                "mode": "assignee",
                "assignments": [{"task_id": project_task.id, "version": project_task.version}],
            },
            "risk_level": 3,
        },
    )
    assert proposed.status_code == 202, proposed.get_data(as_text=True)
    approval_id = proposed.json["data"]["id"]
    db_session.expire_all()
    assert db_session.get(AutomationTaskRun, run_id).status == "waiting_approval"

    viewer_list = viewer.get("/api/v1/task-center/approvals")
    assert viewer_list.status_code == 200
    assert viewer_list.json["data"]["items"][0]["can_review"] is False
    forbidden = viewer.post(
        f"/api/v1/task-center/approvals/{approval_id}/decision",
        json={"decision": "approve", "password": PASSWORD, "reason": ""},
    )
    assert forbidden.status_code == 403

    premature_execution = leader.client.post(
        f"/api/v1/internal/dsh/approvals/{approval_id}/execute",
        headers={"Authorization": "Bearer runtime-approval-secret"},
    )
    assert premature_execution.status_code == 409
    assert premature_execution.json["error"]["code"] == "approval_not_approved"

    wrong_password = leader.post(
        f"/api/v1/task-center/approvals/{approval_id}/decision",
        json={"decision": "approve", "password": "wrong-password", "reason": ""},
    )
    assert wrong_password.status_code == 400
    assert wrong_password.json["error"]["code"] == "invalid_password"

    approved = leader.post(
        f"/api/v1/task-center/approvals/{approval_id}/decision",
        json={"decision": "approve", "password": PASSWORD, "reason": "已核对任务范围"},
    )
    assert approved.status_code == 200
    assert approved.json["data"]["status"] == "approved"
    db_session.rollback()
    approval = db_session.get(AutomationApproval, approval_id)
    assert approval.reviewed_by_user_id == leader.user.id
    assert approval.decision_reason == "已核对任务范围"
    assert db_session.get(AutomationTaskRun, run_id).status == "running"

    polled = leader.client.get(
        f"/api/v1/internal/dsh/approvals/{approval_id}",
        headers={"Authorization": "Bearer runtime-approval-secret"},
    )
    assert polled.status_code == 200
    assert polled.json["data"]["status"] == "approved"
    assert "arguments" not in polled.json["data"]

    first_execution = leader.client.post(
        f"/api/v1/internal/dsh/approvals/{approval_id}/execute",
        headers={"Authorization": "Bearer runtime-approval-secret"},
    )
    repeated_execution = leader.client.post(
        f"/api/v1/internal/dsh/approvals/{approval_id}/execute",
        headers={"Authorization": "Bearer runtime-approval-secret"},
    )
    assert first_execution.status_code == 200, first_execution.get_data(as_text=True)
    assert repeated_execution.status_code == 200, repeated_execution.get_data(as_text=True)
    assert first_execution.json["data"]["status"] == "executed"
    assert first_execution.json["data"]["result"]["updated_count"] == 1
    assert repeated_execution.json["data"]["result"] == first_execution.json["data"]["result"]
    db_session.rollback()
    assert db_session.get(ProjectTask, project_task.id).assignee_user_id == engineer.user.id
    assert db_session.get(AutomationApproval, approval_id).executed_at is not None


def test_dsh_approval_rejects_secrets_in_tool_arguments(
    authorized_client_factory, db_session, app
):
    leader = authorized_client_factory("project_lead")
    project, _ = create_project_with_task(db_session, leader.user)
    created = leader.post(
        "/api/v1/task-center/automations",
        json={
            "title": "安全审批测试",
            "project_id": project.id,
            "source": "desktop",
            "schedule_kind": "once",
            "schedule_expression": "2026-09-05T09:00:00+08:00",
            "timezone": "Asia/Shanghai",
            "prompt": "测试审批参数。",
            "requested_capabilities": ["project.read", "task.batch_assign"],
        },
    )
    queued = leader.client.post(
        f"/api/v1/task-center/automations/{created.json['data']['id']}/runs",
        headers={**leader.headers, "Idempotency-Key": "approval-secret-run"},
    )
    run_id = queued.json["data"]["id"]
    db_session.rollback()
    db_session.get(AutomationTaskRun, run_id).status = "running"
    db_session.commit()

    class ApprovalRuntime:
        def verify_service_token(self, candidate):
            return candidate == "runtime-approval-secret"

    app.extensions["fde_api_dsh_runtime"] = ApprovalRuntime()
    response = leader.client.post(
        f"/api/v1/internal/dsh/executions/{run_id}/approvals",
        headers={"Authorization": "Bearer runtime-approval-secret"},
        json={
            "request_id": "tool-call-secret",
            "capability": "task.batch_assign",
            "tool_name": "project_tasks.batch_assign",
            "arguments": {"nested": {"access_token": "must-not-persist"}},
            "risk_level": 3,
        },
    )
    assert response.status_code == 400
    assert db_session.query(AutomationApproval).count() == 0


def test_expired_approval_is_persisted_when_reviewer_arrives_too_late(
    authorized_client_factory, db_session, app
):
    leader = authorized_client_factory("project_lead")
    project, _ = create_project_with_task(db_session, leader.user)
    created = leader.post(
        "/api/v1/task-center/automations",
        json={
            "title": "过期审批测试",
            "project_id": project.id,
            "source": "desktop",
            "schedule_kind": "once",
            "schedule_expression": "2026-09-05T09:00:00+08:00",
            "timezone": "Asia/Shanghai",
            "prompt": "测试审批过期。",
            "requested_capabilities": ["project.read", "task.batch_assign"],
        },
    )
    queued = leader.client.post(
        f"/api/v1/task-center/automations/{created.json['data']['id']}/runs",
        headers={**leader.headers, "Idempotency-Key": "expired-approval-run"},
    )
    run_id = queued.json["data"]["id"]
    db_session.rollback()
    db_session.get(AutomationTaskRun, run_id).status = "running"
    db_session.commit()

    class ApprovalRuntime:
        def verify_service_token(self, candidate):
            return candidate == "runtime-approval-secret"

    app.extensions["fde_api_dsh_runtime"] = ApprovalRuntime()
    proposed = leader.client.post(
        f"/api/v1/internal/dsh/executions/{run_id}/approvals",
        headers={"Authorization": "Bearer runtime-approval-secret"},
        json={
            "request_id": "expired-tool-call",
            "capability": "task.batch_assign",
            "tool_name": "project_tasks.batch_assign",
            "arguments": {"task_ids": ["task-1"], "assignee_user_id": leader.user.id},
            "risk_level": 3,
        },
    )
    approval_id = proposed.json["data"]["id"]
    db_session.rollback()
    approval = db_session.get(AutomationApproval, approval_id)
    approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    response = leader.post(
        f"/api/v1/task-center/approvals/{approval_id}/decision",
        json={"decision": "approve", "password": PASSWORD, "reason": "too late"},
    )
    assert response.status_code == 409
    assert response.json["error"]["code"] == "approval_expired"
    db_session.expire_all()
    assert db_session.get(AutomationApproval, approval_id).status == "expired"
    run = db_session.get(AutomationTaskRun, run_id)
    assert run.status == "failed"
    assert run.error_code == "approval_expired"
