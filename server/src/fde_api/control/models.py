from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fde_api.auth.models import Base, User, UTCDateTime
from fde_api.workbench.models import Project, TimestampMixin, VersionedMixin, new_uuid


AI_ACCESS_LEVELS = ("disabled", "assistant_read", "project_operator", "project_manager", "system_operator")
CHANNEL_STATUSES = ("pending", "active", "paused", "revoked")
AUTOMATION_TASK_STATUSES = ("active", "paused", "archived")
AUTOMATION_TASK_SOURCES = ("desktop", "wechat", "system")
AUTOMATION_TASK_TYPES = ("ai", "system")
SCHEDULE_KINDS = ("once", "calendar", "interval", "event")
AUTOMATION_RUN_STATUSES = ("queued", "running", "waiting_approval", "succeeded", "failed", "cancelled", "skipped")
AUTOMATION_APPROVAL_STATUSES = ("pending", "approved", "rejected", "expired", "executed")
SKILL_SCOPES = ("public", "personal")
EXTENSION_STATUSES = ("active", "disabled")
PLUGIN_INSTALLATION_STATUSES = ("installed", "disabled", "removed")
PLUGIN_CHANGE_ACTIONS = ("install", "upgrade", "rollback", "disable", "remove")
PLUGIN_CHANGE_STATUSES = ("pending", "approved", "rejected", "executed", "failed")


class UserAIAccessGrant(Base, TimestampMixin):
    __tablename__ = "user_ai_access_grants"
    __table_args__ = (
        CheckConstraint(f"access_level IN {AI_ACCESS_LEVELS!r}", name="ck_user_ai_access_level"),
        UniqueConstraint("user_id", name="uq_user_ai_access_grants_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    access_level: Mapped[str] = mapped_column(String(32), nullable=False)
    granted_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    granted_by: Mapped[User] = relationship(foreign_keys=[granted_by_user_id])


class ChannelBinding(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "channel_bindings"
    __table_args__ = (
        CheckConstraint("channel IN ('wechat_clawbot')", name="ck_channel_bindings_channel"),
        CheckConstraint(f"status IN {CHANNEL_STATUSES!r}", name="ck_channel_bindings_status"),
        UniqueConstraint("user_id", "channel", name="uq_channel_bindings_user_channel"),
        UniqueConstraint("channel", "external_subject_hash", name="uq_channel_bindings_external_subject"),
        Index("ix_channel_bindings_status", "channel", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="wechat_clawbot")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    external_subject_hash: Mapped[str | None] = mapped_column(String(64))
    channel_display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    default_project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    commands_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    binding_code_digest: Mapped[str | None] = mapped_column(String(64))
    binding_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    default_project: Mapped[Project | None] = relationship(foreign_keys=[default_project_id])


class AutomationTask(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "automation_tasks"
    __table_args__ = (
        CheckConstraint(f"source IN {AUTOMATION_TASK_SOURCES!r}", name="ck_automation_tasks_source"),
        CheckConstraint(f"task_type IN {AUTOMATION_TASK_TYPES!r}", name="ck_automation_tasks_type"),
        CheckConstraint(f"status IN {AUTOMATION_TASK_STATUSES!r}", name="ck_automation_tasks_status"),
        CheckConstraint(f"schedule_kind IN {SCHEDULE_KINDS!r}", name="ck_automation_tasks_schedule_kind"),
        CheckConstraint("risk_level >= 0 AND risk_level <= 4", name="ck_automation_tasks_risk"),
        UniqueConstraint("source_event_id", name="uq_automation_tasks_source_event_id"),
        Index("ix_automation_tasks_owner_status", "created_by_user_id", "status"),
        Index("ix_automation_tasks_project_status", "project_id", "status"),
        Index("ix_automation_tasks_next_run", "status", "next_run_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="desktop")
    task_type: Mapped[str] = mapped_column(String(20), nullable=False, default="ai")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    schedule_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    schedule_expression: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    source_event_id: Mapped[str | None] = mapped_column(String(160))
    requested_capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    dsh_profile: Mapped[str] = mapped_column(String(120), nullable=False, default="fde-operator")
    risk_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    notification_policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    project: Mapped[Project | None] = relationship(foreign_keys=[project_id])
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_user_id])


class KnowledgeSnapshot(Base, TimestampMixin):
    __tablename__ = "knowledge_snapshots"
    __table_args__ = (
        UniqueConstraint("project_id", "content_sha256", name="uq_knowledge_snapshots_project_sha256"),
        Index("ix_knowledge_snapshots_project_created", "project_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False, default="fde-ontology-v1")
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    project: Mapped[Project] = relationship(foreign_keys=[project_id])
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_user_id])


class AutomationTaskRun(Base, TimestampMixin):
    __tablename__ = "automation_task_runs"
    __table_args__ = (
        CheckConstraint(f"status IN {AUTOMATION_RUN_STATUSES!r}", name="ck_automation_task_runs_status"),
        CheckConstraint("attempt >= 0", name="ck_automation_task_runs_attempt"),
        UniqueConstraint("idempotency_key", name="uq_automation_task_runs_idempotency"),
        Index("ix_automation_task_runs_task_scheduled", "task_id", "scheduled_for"),
        Index("ix_automation_task_runs_status", "status", "scheduled_for"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("automation_tasks.id", ondelete="RESTRICT"), nullable=False)
    requested_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    dsh_runtime_version: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    agent_profile_version: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    knowledge_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_snapshots.id", ondelete="RESTRICT"))
    result_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    external_execution_id: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")

    task: Mapped[AutomationTask] = relationship(foreign_keys=[task_id])
    requested_by: Mapped[User] = relationship(foreign_keys=[requested_by_user_id])
    knowledge_snapshot: Mapped[KnowledgeSnapshot | None] = relationship(foreign_keys=[knowledge_snapshot_id])


class AutomationApproval(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "automation_approvals"
    __table_args__ = (
        CheckConstraint(
            f"status IN {AUTOMATION_APPROVAL_STATUSES!r}",
            name="ck_automation_approvals_status",
        ),
        CheckConstraint("risk_level >= 3 AND risk_level <= 4", name="ck_automation_approvals_risk"),
        UniqueConstraint("run_id", "request_key", name="uq_automation_approvals_run_request"),
        Index("ix_automation_approvals_project_status", "project_id", "status"),
        Index("ix_automation_approvals_expires", "status", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("automation_task_runs.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    requested_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    request_key: Mapped[str] = mapped_column(String(160), nullable=False)
    capability: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    arguments_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    arguments_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    decision_reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    run: Mapped[AutomationTaskRun] = relationship(foreign_keys=[run_id])
    project: Mapped[Project] = relationship(foreign_keys=[project_id])
    requested_by: Mapped[User] = relationship(foreign_keys=[requested_by_user_id])
    reviewed_by: Mapped[User | None] = relationship(foreign_keys=[reviewed_by_user_id])


class SkillDefinition(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "skill_definitions"
    __table_args__ = (
        CheckConstraint(f"scope IN {SKILL_SCOPES!r}", name="ck_skill_definitions_scope"),
        CheckConstraint(f"status IN {EXTENSION_STATUSES!r}", name="ck_skill_definitions_status"),
        UniqueConstraint("namespace_key", "skill_key", name="uq_skill_definitions_namespace_key"),
        Index("ix_skill_definitions_scope_status", "scope", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    namespace_key: Mapped[str] = mapped_column(String(80), nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    skill_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    owner: Mapped[User | None] = relationship(foreign_keys=[owner_user_id])
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_user_id])


class SkillVersion(Base, TimestampMixin):
    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "version_number", name="uq_skill_versions_number"),
        UniqueConstraint("skill_id", "content_sha256", name="uq_skill_versions_content"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skill_definitions.id", ondelete="RESTRICT"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    instructions_text: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    required_capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    skill: Mapped[SkillDefinition] = relationship(foreign_keys=[skill_id])
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_user_id])


class PluginPackage(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "plugin_packages"
    __table_args__ = (
        CheckConstraint(f"status IN {EXTENSION_STATUSES!r}", name="ck_plugin_packages_status"),
        UniqueConstraint("plugin_key", name="uq_plugin_packages_key"),
        Index("ix_plugin_packages_source_category", "source", "category"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plugin_key: Mapped[str] = mapped_column(String(140), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    publisher: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    current_version: Mapped[str] = mapped_column(String(80), nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    package_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="internal")
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    page_url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    install_spec: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    catalog_entry_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    created_by: Mapped[User] = relationship(foreign_keys=[created_by_user_id])


class PluginCatalogSync(Base, TimestampMixin):
    __tablename__ = "plugin_catalog_syncs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    registry_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    registry_updated: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    plugin_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")
    error_message: Mapped[str] = mapped_column(String(500), nullable=False, default="")


class PluginInstallation(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "plugin_installations"
    __table_args__ = (
        CheckConstraint(
            f"status IN {PLUGIN_INSTALLATION_STATUSES!r}",
            name="ck_plugin_installations_status",
        ),
        UniqueConstraint("plugin_id", "user_id", name="uq_plugin_installations_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plugin_id: Mapped[str] = mapped_column(ForeignKey("plugin_packages.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    installed_version: Mapped[str] = mapped_column(String(80), nullable=False)
    granted_capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="installed")

    plugin: Mapped[PluginPackage] = relationship(foreign_keys=[plugin_id])
    user: Mapped[User] = relationship(foreign_keys=[user_id])


class PluginInstallationRevision(Base, TimestampMixin):
    __tablename__ = "plugin_installation_revisions"
    __table_args__ = (
        UniqueConstraint("installation_id", "revision_number", name="uq_plugin_installation_revisions_number"),
        Index("ix_plugin_installation_revisions_version", "installation_id", "installed_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    installation_id: Mapped[str] = mapped_column(ForeignKey("plugin_installations.id", ondelete="RESTRICT"), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    installed_version: Mapped[str] = mapped_column(String(80), nullable=False)
    granted_capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    installation: Mapped[PluginInstallation] = relationship(foreign_keys=[installation_id])
    changed_by: Mapped[User] = relationship(foreign_keys=[changed_by_user_id])


class PluginChangeRequest(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "plugin_change_requests"
    __table_args__ = (
        CheckConstraint(f"action IN {PLUGIN_CHANGE_ACTIONS!r}", name="ck_plugin_change_requests_action"),
        CheckConstraint(f"status IN {PLUGIN_CHANGE_STATUSES!r}", name="ck_plugin_change_requests_status"),
        Index("ix_plugin_change_requests_status", "status", "created_at"),
        Index("ix_plugin_change_requests_target", "target_user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plugin_id: Mapped[str] = mapped_column(ForeignKey("plugin_packages.id", ondelete="RESTRICT"), nullable=False)
    target_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    requested_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    from_version: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    target_version: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    requested_capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    request_reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    decision_reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    plugin: Mapped[PluginPackage] = relationship(foreign_keys=[plugin_id])
    target_user: Mapped[User] = relationship(foreign_keys=[target_user_id])
    requested_by: Mapped[User] = relationship(foreign_keys=[requested_by_user_id])
    reviewed_by: Mapped[User | None] = relationship(foreign_keys=[reviewed_by_user_id])


class AIProviderConfig(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "ai_provider_configs"
    __table_args__ = (
        CheckConstraint(f"status IN {EXTENSION_STATUSES!r}", name="ck_ai_provider_configs_status"),
        UniqueConstraint("provider_key", name="uq_ai_provider_configs_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    provider_key: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    credential_ref: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    credential_hint: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    created_by: Mapped[User] = relationship(foreign_keys=[created_by_user_id])


class AIModelConfig(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "ai_model_configs"
    __table_args__ = (
        CheckConstraint(f"status IN {EXTENSION_STATUSES!r}", name="ck_ai_model_configs_status"),
        UniqueConstraint("provider_id", "model_key", name="uq_ai_model_configs_provider_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    provider_id: Mapped[str] = mapped_column(ForeignKey("ai_provider_configs.id", ondelete="RESTRICT"), nullable=False)
    model_key: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    context_window: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    supports_tools: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_json: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    provider: Mapped[AIProviderConfig] = relationship(foreign_keys=[provider_id])
