from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from urllib.parse import urlparse

from flask import current_app
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from fde_api.auth.models import User
from fde_api.auth.passwords import verify_password
from fde_api.control.access import ACCESS_RANK, CAPABILITY_REQUIREMENTS, capabilities_for_level, effective_ai_access
from fde_api.control.models import (
    AIModelConfig,
    AIProviderConfig,
    PluginChangeRequest,
    PluginInstallation,
    PluginInstallationRevision,
    PluginPackage,
    SKILL_STATUSES,
    SkillDefinition,
    SkillVersion,
)
from fde_api.control.service import ControlServiceError
from fde_api.control.dsh_market import marketplace_status
from fde_api.extensions import db


_SKILL_KEY = re.compile(r"^[a-z][a-z0-9-]{1,99}$")
_PROVIDER_KEY = re.compile(r"^[a-z][a-z0-9_-]{1,79}$")
_MODEL_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")


def extensions_center(*, user: User) -> dict[str, Any]:
    level, _ = effective_ai_access(user)
    session = db.session()
    try:
        # 插件能力登记表种子（goal-d11，d6 挂账⑥）：懒装载幂等——首次进入
        # 扩展中心时装载已知插件（存在即跳过，不覆写现场）。
        from fde_api.control.plugin_seeds import ensure_plugin_seeds

        ensure_plugin_seeds(session, user)
        session.commit()
        skills = list(
            session.scalars(
                select(SkillDefinition)
                .where(
                    or_(
                        SkillDefinition.scope == "public",
                        SkillDefinition.owner_user_id == user.id,
                    )
                )
                .order_by(SkillDefinition.scope, SkillDefinition.name, SkillDefinition.id)
            )
        )
        installations = {
            item.plugin_id: item
            for item in session.scalars(
                select(PluginInstallation).where(PluginInstallation.user_id == user.id)
            )
        }
        installation_ids = [item.id for item in installations.values()]
        revisions = list(session.scalars(
            select(PluginInstallationRevision).where(
                PluginInstallationRevision.installation_id.in_(installation_ids)
            )
        )) if installation_ids else []
        rollback_versions: dict[str, list[str]] = {}
        for revision in revisions:
            rollback_versions.setdefault(revision.installation_id, []).append(revision.installed_version)
        plugins = list(
            session.scalars(
                select(PluginPackage)
                .where(PluginPackage.status == "active", or_(PluginPackage.source != "dsh-market", PluginPackage.id.in_(list(installations))))
                .order_by(PluginPackage.name, PluginPackage.id)
            )
        )
        models = list(
            session.scalars(
                select(AIModelConfig)
                .join(AIProviderConfig)
                .options(joinedload(AIModelConfig.provider))
                .where(
                    AIModelConfig.status == "active",
                    AIProviderConfig.status == "active",
                )
                .order_by(AIProviderConfig.display_name, AIModelConfig.display_name)
            )
        )
        providers = list(session.scalars(select(AIProviderConfig).order_by(AIProviderConfig.display_name)))
        can_manage_system = level == "system_operator"
        request_scope = True if can_manage_system else PluginChangeRequest.target_user_id == user.id
        plugin_requests = list(
            session.scalars(
                select(PluginChangeRequest)
                .options(joinedload(PluginChangeRequest.plugin), joinedload(PluginChangeRequest.target_user))
                .where(request_scope)
                .order_by(PluginChangeRequest.created_at.desc(), PluginChangeRequest.id)
                .limit(100)
            )
        )
        from fde_api.control.model_preferences import credentials_ready, list_model_preferences
        from fde_api.control.mcp_gateway import TOOLS
        allowed_tools = set(capabilities_for_level(level))
        return {
            "skills": [_serialize_skill(item, user) for item in skills],
            "tools": [{"key": key, "description": definition[0], "capability": definition[1]}
                      for key, definition in TOOLS.items() if definition[1] is None or definition[1] in allowed_tools],
            "plugins": [
                _serialize_plugin(
                    item,
                    installations.get(item.id),
                    rollback_versions.get(installations[item.id].id, []) if item.id in installations else [],
                )
                for item in plugins
            ],
            "models": [_serialize_model(item) for item in models],
            "providers": [
                _serialize_provider(item, include_hint=can_manage_system)
                for item in providers
            ] if can_manage_system else [],
            "plugin_requests": [_serialize_plugin_request(item) for item in plugin_requests],
            "permissions": {
                "can_manage_personal_skills": level != "disabled",
                "can_manage_system": can_manage_system,
            },
            "marketplace": marketplace_status(
                enabled=current_app.config["SETTINGS"].dsh_market_enabled,
                registry_url=current_app.config["SETTINGS"].dsh_market_registry_url,
            ),
            "credential_storage": "encrypted_server_storage",
            "model_preferences": list_model_preferences(user=user),
            "model_credentials_ready": credentials_ready(),
        }
    finally:
        session.close()


def save_personal_skill(*, user: User, payload: dict[str, Any]) -> dict[str, Any]:
    level, _ = effective_ai_access(user)
    if level == "disabled":
        raise ControlServiceError("forbidden", "当前账户未开通个人 Skill。", 403)
    return _save_skill(user=user, payload=payload, scope="personal")


def save_public_skill(
    *, user: User, payload: dict[str, Any], initial_status: str | None = None
) -> dict[str, Any]:
    """公共 Skill 保存（system_operator）。

    initial_status 仅限服务端种子路径（builtin 内容可信，直接 published）；
    HTTP 面不传 → 公共 Skill 一律落 draft 走治理工作流（T-S1）。
    """
    level, _ = effective_ai_access(user)
    if level != "system_operator":
        raise ControlServiceError("forbidden", "只有管理员可以发布公共 Skill。", 403)
    if initial_status is not None and initial_status not in SKILL_STATUSES:
        raise ControlServiceError("invalid_skill", "Skill 参数无效。", 400)
    return _save_skill(user=user, payload=payload, scope="public", initial_status=initial_status)


def _save_skill(
    *, user: User, payload: dict[str, Any], scope: str, initial_status: str | None = None
) -> dict[str, Any]:
    level, _ = effective_ai_access(user)
    required = {"key", "name", "description", "instructions", "manifest", "required_capabilities"}
    optional = {"input_schema", "output_schema", "test_report"}
    if not required <= set(payload) <= required | optional:
        raise ControlServiceError("invalid_skill", "Skill 参数无效。", 400)
    key = payload["key"]
    name = payload["name"]
    description = payload["description"]
    instructions = payload["instructions"]
    manifest = payload["manifest"]
    capabilities = payload["required_capabilities"]
    input_schema = payload.get("input_schema")
    output_schema = payload.get("output_schema")
    test_report = payload.get("test_report")
    if (
        not isinstance(key, str)
        or not _SKILL_KEY.fullmatch(key)
        or not isinstance(name, str)
        or not name.strip()
        or len(name) > 160
        or not isinstance(description, str)
        or len(description) > 4_000
        or not isinstance(instructions, str)
        or not instructions.strip()
        or len(instructions.encode("utf-8")) > 128_000
        or not isinstance(manifest, dict)
        or not isinstance(capabilities, list)
        or any(not isinstance(item, str) or item not in CAPABILITY_REQUIREMENTS for item in capabilities)
        or len(set(capabilities)) != len(capabilities)
        or any(
            ACCESS_RANK[level] < ACCESS_RANK[CAPABILITY_REQUIREMENTS[item]]
            for item in capabilities
        )
        or any(value is not None and not isinstance(value, dict) for value in (input_schema, output_schema, test_report))
    ):
        raise ControlServiceError("invalid_skill", "Skill 参数无效。", 400)
    # 指纹覆盖全部发布材料（instructions/manifest/capabilities + 契约 schema + 测试报告）：
    # 任一材料变化都开新版本——版本行不可变的语义以「整份发布材料」为单位。
    canonical = json.dumps(
        {
            "instructions": instructions,
            "manifest": manifest,
            "required_capabilities": capabilities,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "test_report": test_report,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    digest = sha256(canonical.encode("utf-8")).hexdigest()
    namespace_key = user.id if scope == "personal" else "public"
    owner_user_id = user.id if scope == "personal" else None
    # 治理态（T-S1）：个人 Skill 自发布（owner 自治，四闸只对公共 Skill）；
    # 公共 Skill 落 draft 走 draft→in_review→published→deprecated（initial_status 仅种子路径）。
    if scope == "personal" or initial_status == "published":
        status_value = "published"
        published_by, published_at = user.id, datetime.now(UTC)
    else:
        status_value, published_by, published_at = "draft", None, None
    session = db.session()
    try:
        with session.begin():
            skill = session.scalar(
                select(SkillDefinition)
                .where(
                    SkillDefinition.namespace_key == namespace_key,
                    SkillDefinition.skill_key == key,
                )
                .with_for_update()
            )
            if skill is None:
                skill = SkillDefinition(
                    scope=scope,
                    namespace_key=namespace_key,
                    owner_user_id=owner_user_id,
                    skill_key=key,
                    name=name.strip(),
                    description=description.strip(),
                    status=status_value,
                    current_version_number=1,
                    created_by_user_id=user.id,
                    published_by_user_id=published_by,
                    published_at=published_at,
                )
                session.add(skill)
                session.flush()
                version_number = 1
            else:
                current = session.scalar(
                    select(SkillVersion).where(
                        SkillVersion.skill_id == skill.id,
                        SkillVersion.version_number == skill.current_version_number,
                    )
                )
                if current is not None and current.content_sha256 == digest:
                    # 同内容重存：只同步名称/描述；个人 Skill 自愈回 published，
                    # 公共 Skill 的治理态不被重存改写（deprecated 不因重存复活）。
                    if scope == "personal":
                        skill.status = "published"
                        skill.published_by_user_id = published_by
                        skill.published_at = published_at
                    if skill.name != name.strip() or skill.description != description.strip():
                        skill.name = name.strip()
                        skill.description = description.strip()
                        skill.version += 1
                    return _serialize_skill(skill, user)
                version_number = skill.current_version_number + 1
                skill.current_version_number = version_number
                skill.name = name.strip()
                skill.description = description.strip()
                skill.status = status_value
                skill.published_by_user_id = published_by
                skill.published_at = published_at
                skill.version += 1
            session.add(
                SkillVersion(
                    skill_id=skill.id,
                    version_number=version_number,
                    instructions_text=instructions,
                    manifest_json=manifest,
                    required_capabilities=capabilities,
                    content_sha256=digest,
                    created_by_user_id=user.id,
                    input_schema_json=input_schema,
                    output_schema_json=output_schema,
                    test_report_json=test_report,
                )
            )
            session.flush()
            return _serialize_skill(skill, user)
    finally:
        session.close()


def submit_skill_review(*, user: User, skill_id: str) -> dict[str, Any]:
    """提交审核（draft→in_review；公共 Skill；system_operator）。"""
    _require_system_operator(user, "只有管理员可以提交公共 Skill 审核。")
    with db.session() as session, session.begin():
        skill = _load_governed_skill(session, skill_id)
        if skill.status != "draft":
            raise ControlServiceError(
                "not_submittable", "只有草稿（draft）状态的 Skill 可以提交审核。", 409
            )
        skill.status = "in_review"
        skill.version += 1
        session.flush()
        return _serialize_skill(skill, user)


def publish_skill(*, user: User, skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """发布（in_review→published）。四条闸：admin / 密码确认 / in_review / 测试报告或显式 waive。

    版本行不可变：发布只置定义态与发布人戳，并把版本行 reviewed_by 落为发布人
    （发布即审核背书）；无测试报告时必须给 waive_reason（≤500 字），诚实留痕。
    """
    _require_system_operator(user, "只有管理员可以发布公共 Skill。")
    password, waive_reason = _lifecycle_payload(payload, optional={"waive_reason"})
    with db.session() as session, session.begin():
        skill = _load_governed_skill(session, skill_id)
        if skill.status != "in_review":
            raise ControlServiceError(
                "not_in_review", "只有待审核（in_review）的 Skill 可以发布；请先提交审核。", 409
            )
        version = session.scalar(
            select(SkillVersion).where(
                SkillVersion.skill_id == skill.id,
                SkillVersion.version_number == skill.current_version_number,
            )
        )
        if version is None:
            raise ControlServiceError("version_not_found", "Skill 版本不存在。", 404)
        if not verify_password(user.password_hash, password):
            raise ControlServiceError("invalid_password", "当前账号密码不正确。", 403)
        if version.test_report_json is None and not waive_reason:
            raise ControlServiceError(
                "test_report_required",
                "该版本没有测试报告；如确需跳过请携带 waive_reason 说明理由。",
                409,
            )
        skill.status = "published"
        skill.published_by_user_id = user.id
        skill.published_at = datetime.now(UTC)
        version.reviewed_by_user_id = user.id
        skill.version += 1
        session.flush()
        return _serialize_skill(skill, user)


def rollback_skill(*, user: User, skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """回滚（published 内把当前版本指回旧版本行；同密码+材料闸）。

    版本行不可变 ⇒ 回滚=改指 current_version_number，历史版本原样保留；
    目标版本同样要有测试报告或 waive（旧版本当年怎么过的闸，今天就怎么复核）。
    """
    _require_system_operator(user, "只有管理员可以回滚公共 Skill。")
    password, waive_reason = _lifecycle_payload(payload, optional={"waive_reason"}, require_version=True)
    target_number = payload["version"]
    with db.session() as session, session.begin():
        skill = _load_governed_skill(session, skill_id)
        if skill.status != "published":
            raise ControlServiceError(
                "not_rollbackable", "只有已发布（published）的 Skill 可以回滚。", 409
            )
        if not isinstance(target_number, int) or target_number < 1:
            raise ControlServiceError("invalid_request", "version 必须是正整数。", 400)
        if target_number == skill.current_version_number:
            raise ControlServiceError(
                "already_current", f"版本 {target_number} 已是当前版本。", 409
            )
        version = session.scalar(
            select(SkillVersion).where(
                SkillVersion.skill_id == skill.id,
                SkillVersion.version_number == target_number,
            )
        )
        if version is None:
            raise ControlServiceError("version_not_found", "Skill 版本不存在。", 404)
        if not verify_password(user.password_hash, password):
            raise ControlServiceError("invalid_password", "当前账号密码不正确。", 403)
        if version.test_report_json is None and not waive_reason:
            raise ControlServiceError(
                "test_report_required",
                "目标版本没有测试报告；如确需跳过请携带 waive_reason 说明理由。",
                409,
            )
        skill.current_version_number = target_number
        skill.published_by_user_id = user.id
        skill.published_at = datetime.now(UTC)
        version.reviewed_by_user_id = user.id
        skill.version += 1
        session.flush()
        return _serialize_skill(skill, user)


def deprecate_skill(*, user: User, skill_id: str) -> dict[str, Any]:
    """弃用（published→deprecated；从 MCP 工具面与工作流白名单退出）。

    弃用保留 published_by/at 作历史；复活路径=重新编辑（新版本回 draft 走治理）。
    """
    _require_system_operator(user, "只有管理员可以弃用公共 Skill。")
    with db.session() as session, session.begin():
        skill = _load_governed_skill(session, skill_id)
        if skill.status != "published":
            raise ControlServiceError(
                "not_deprecatable", "只有已发布（published）的 Skill 可以弃用。", 409
            )
        skill.status = "deprecated"
        skill.version += 1
        session.flush()
        return _serialize_skill(skill, user)


def list_skill_versions(*, user: User, skill_id: str) -> dict[str, Any]:
    """版本治理视图（公共 Skill 任何登录用户可读，与扩展中心可见性同口径；个人仅 owner）。"""
    with db.session() as session:
        skill = session.get(SkillDefinition, skill_id)
        if skill is None or (
            skill.scope == "personal" and skill.owner_user_id != user.id
        ):
            raise ControlServiceError("skill_not_found", "Skill 不存在。", 404)
        rows = list(
            session.scalars(
                select(SkillVersion)
                .where(SkillVersion.skill_id == skill.id)
                .order_by(SkillVersion.version_number)
            )
        )
        versions = [
            {
                "version": row.version_number,
                "content_sha256": row.content_sha256,
                "created_by_user_id": row.created_by_user_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "reviewed_by_user_id": row.reviewed_by_user_id,
                "has_test_report": row.test_report_json is not None,
                "input_schema": row.input_schema_json,
                "output_schema": row.output_schema_json,
                "is_current": row.version_number == skill.current_version_number,
            }
            for row in rows
        ]
        return {"skill": _serialize_skill(skill, user), "versions": versions}


def _load_governed_skill(session: Any, skill_id: str) -> SkillDefinition:
    """治理操作只落公共 Skill（个人 Skill 自发布，无治理态可操作）。"""
    skill = session.get(SkillDefinition, skill_id)
    if skill is None or skill.scope != "public":
        raise ControlServiceError("skill_not_found", "Skill 不存在。", 404)
    return skill


def _lifecycle_payload(
    payload: dict[str, Any], *, optional: set[str], require_version: bool = False
) -> tuple[str, str]:
    """生命周期请求体校验：password 必带（1–1024 字符）；waive_reason 可选（≤500）。"""
    required = {"password", "version"} if require_version else {"password"}
    if not required <= set(payload) <= required | optional:
        raise ControlServiceError("invalid_request", "请求参数无效。", 400)
    password = payload["password"]
    if not isinstance(password, str) or not 1 <= len(password) <= 1024:
        raise ControlServiceError("invalid_request", "请求参数无效。", 400)
    waive = payload.get("waive_reason")
    if waive is not None and (not isinstance(waive, str) or len(waive.strip()) > 500):
        raise ControlServiceError("invalid_request", "请求参数无效。", 400)
    return password, (waive.strip() if isinstance(waive, str) else "")


def save_ai_provider(*, user: User, payload: dict[str, Any]) -> dict[str, Any]:
    _require_system_operator(user, "只有系统运维员可以管理模型供应商。")
    required = {"key", "name", "base_url", "credential_ref", "credential_hint", "status"}
    if set(payload) != required:
        raise ControlServiceError("invalid_provider", "模型供应商参数无效。", 400)
    key, name, base_url = payload["key"], payload["name"], payload["base_url"]
    credential_ref, credential_hint, status = payload["credential_ref"], payload["credential_hint"], payload["status"]
    parsed = urlparse(base_url) if isinstance(base_url, str) else None
    if (
        not isinstance(key, str) or not _PROVIDER_KEY.fullmatch(key)
        or not isinstance(name, str) or not name.strip() or len(name) > 160
        or parsed is None or parsed.scheme != "https" or not parsed.netloc or parsed.username is not None
        or not isinstance(credential_ref, str) or len(credential_ref) > 500
        or (credential_ref and not credential_ref.startswith(("kms:", "env:", "vault:")))
        or not isinstance(credential_hint, str) or len(credential_hint) > 40
        or status not in {"active", "disabled"}
    ):
        raise ControlServiceError("invalid_provider", "模型供应商参数无效；密钥只能填写 KMS、Vault 或环境变量引用。", 400)
    session = db.session()
    try:
        with session.begin():
            provider = session.scalar(select(AIProviderConfig).where(AIProviderConfig.provider_key == key).with_for_update())
            if provider is None:
                provider = AIProviderConfig(provider_key=key, display_name=name.strip(), base_url=base_url.rstrip("/"), credential_ref=credential_ref, credential_hint=credential_hint, status=status, created_by_user_id=user.id)
                session.add(provider)
            else:
                provider.display_name = name.strip()
                provider.base_url = base_url.rstrip("/")
                provider.credential_ref = credential_ref
                provider.credential_hint = credential_hint
                provider.status = status
                provider.version += 1
            session.flush()
            return _serialize_provider(provider, include_hint=True)
    finally:
        session.close()


def save_ai_model(*, user: User, payload: dict[str, Any]) -> dict[str, Any]:
    _require_system_operator(user, "只有系统运维员可以管理模型。")
    required = {"provider_key", "key", "name", "context_window", "supports_tools", "supports_json", "status"}
    if set(payload) != required:
        raise ControlServiceError("invalid_model", "模型参数无效。", 400)
    provider_key, key, name = payload["provider_key"], payload["key"], payload["name"]
    context_window = payload["context_window"]
    if (
        not isinstance(provider_key, str) or not _PROVIDER_KEY.fullmatch(provider_key)
        or not isinstance(key, str) or not _MODEL_KEY.fullmatch(key)
        or not isinstance(name, str) or not name.strip() or len(name) > 160
        or not isinstance(context_window, int) or isinstance(context_window, bool) or context_window < 0 or context_window > 10_000_000
        or not isinstance(payload["supports_tools"], bool) or not isinstance(payload["supports_json"], bool)
        or payload["status"] not in {"active", "disabled"}
    ):
        raise ControlServiceError("invalid_model", "模型参数无效。", 400)
    session = db.session()
    try:
        with session.begin():
            provider = session.scalar(select(AIProviderConfig).where(AIProviderConfig.provider_key == provider_key, AIProviderConfig.status == "active"))
            if provider is None:
                raise ControlServiceError("provider_not_found", "请先创建并启用模型供应商。", 404)
            model = session.scalar(select(AIModelConfig).where(AIModelConfig.provider_id == provider.id, AIModelConfig.model_key == key).with_for_update())
            if model is None:
                model = AIModelConfig(provider_id=provider.id, model_key=key, display_name=name.strip(), context_window=context_window, supports_tools=payload["supports_tools"], supports_json=payload["supports_json"], status=payload["status"])
                session.add(model)
            else:
                model.display_name = name.strip()
                model.context_window = context_window
                model.supports_tools = payload["supports_tools"]
                model.supports_json = payload["supports_json"]
                model.status = payload["status"]
                model.version += 1
            session.flush()
            model.provider = provider
            return _serialize_model(model)
    finally:
        session.close()


def request_plugin_change(*, user: User, plugin_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    level, _ = effective_ai_access(user)
    if level == "disabled":
        raise ControlServiceError("forbidden", "当前账户未开通插件能力。", 403)
    if set(payload) != {"action", "target_version", "reason"}:
        raise ControlServiceError("invalid_plugin_change", "插件变更参数无效。", 400)
    action = payload["action"]
    target_version = payload["target_version"]
    reason = payload["reason"]
    if (
        action not in {"install", "upgrade", "rollback", "disable", "remove"}
        or not isinstance(target_version, str) or len(target_version) > 80
        or not isinstance(reason, str) or len(reason) > 500
    ):
        raise ControlServiceError("invalid_plugin_change", "插件变更参数无效。", 400)

    session = db.session()
    try:
        with session.begin():
            plugin = session.get(PluginPackage, plugin_id)
            if plugin is None or plugin.status != "active":
                raise ControlServiceError("plugin_not_found", "插件不存在或已停用。", 404)
            installation = session.scalar(
                select(PluginInstallation).where(
                    PluginInstallation.plugin_id == plugin.id,
                    PluginInstallation.user_id == user.id,
                )
            )
            _validate_plugin_action(session, plugin, installation, action, target_version)
            capabilities = _plugin_capabilities(plugin)
            if action == "rollback" and installation is not None:
                historical = session.scalar(
                    select(PluginInstallationRevision).where(
                        PluginInstallationRevision.installation_id == installation.id,
                        PluginInstallationRevision.installed_version == target_version,
                    ).order_by(PluginInstallationRevision.revision_number.desc()).limit(1)
                )
                capabilities = list(historical.granted_capabilities) if historical is not None else capabilities
            for capability in capabilities:
                if capability not in CAPABILITY_REQUIREMENTS or ACCESS_RANK[level] < ACCESS_RANK[CAPABILITY_REQUIREMENTS[capability]]:
                    raise ControlServiceError("plugin_capability_forbidden", "插件申请了当前账户无权使用的能力。", 403)
            pending = session.scalar(
                select(PluginChangeRequest).where(
                    PluginChangeRequest.plugin_id == plugin.id,
                    PluginChangeRequest.target_user_id == user.id,
                    PluginChangeRequest.status == "pending",
                )
            )
            if pending is not None:
                raise ControlServiceError("plugin_change_pending", "该插件已有待审批变更。", 409)
            change = PluginChangeRequest(
                plugin_id=plugin.id,
                target_user_id=user.id,
                requested_by_user_id=user.id,
                action=action,
                from_version=installation.installed_version if installation else "",
                target_version=(target_version.strip() if action == "rollback" else plugin.current_version),
                requested_capabilities=capabilities,
                status="pending",
                request_reason=reason.strip(),
            )
            session.add(change)
            session.flush()
            change.plugin = plugin
            change.target_user = user
            return _serialize_plugin_request(change)
    finally:
        session.close()


def decide_plugin_change(*, user: User, request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _require_system_operator(user, "只有系统运维员可以审批插件变更。")
    if set(payload) != {"decision", "reason"} or payload.get("decision") not in {"approve", "reject"} or not isinstance(payload.get("reason"), str) or len(payload["reason"]) > 500:
        raise ControlServiceError("invalid_plugin_decision", "插件审批参数无效。", 400)
    session = db.session()
    try:
        with session.begin():
            change = session.scalar(
                select(PluginChangeRequest)
                .options(joinedload(PluginChangeRequest.plugin), joinedload(PluginChangeRequest.target_user))
                .where(PluginChangeRequest.id == request_id)
                # PG 拒绝对外连接的可空侧 FOR UPDATE；只锁主行（并发审批互斥
                # 的本体），关联行由 ORM 正常读取。
                .with_for_update(of=PluginChangeRequest)
            )
            if change is None:
                raise ControlServiceError("plugin_change_not_found", "插件变更申请不存在。", 404)
            if change.status != "pending":
                raise ControlServiceError("plugin_change_already_decided", "插件变更申请已经处理。", 409)
            now = datetime.now(UTC)
            change.reviewed_by_user_id = user.id
            change.reviewed_at = now
            change.decision_reason = payload["reason"].strip()
            change.version += 1
            if payload["decision"] == "reject":
                change.status = "rejected"
                return _serialize_plugin_request(change)

            if not change.target_user.is_active:
                raise ControlServiceError("plugin_target_inactive", "目标账户已停用。", 409)
            target_level, _ = effective_ai_access(change.target_user)
            for capability in change.requested_capabilities:
                if capability not in CAPABILITY_REQUIREMENTS or ACCESS_RANK[target_level] < ACCESS_RANK[CAPABILITY_REQUIREMENTS[capability]]:
                    raise ControlServiceError("plugin_capability_forbidden", "目标账户当前无权使用插件申请的能力。", 403)
            if change.action in {"install", "upgrade"} and (
                change.target_version != change.plugin.current_version
                or change.requested_capabilities != _plugin_capabilities(change.plugin)
            ):
                raise ControlServiceError("plugin_package_changed", "插件包或权限清单已变化，请重新提交申请。", 409)
            installation = session.scalar(
                select(PluginInstallation)
                .where(PluginInstallation.plugin_id == change.plugin_id, PluginInstallation.user_id == change.target_user_id)
                .with_for_update()
            )
            _validate_plugin_action(session, change.plugin, installation, change.action, change.target_version)
            executor = current_app.extensions.get("fde_plugin_executor")
            if not callable(executor):
                raise ControlServiceError("plugin_runtime_unavailable", "AI Server 插件运行环境未连接，未执行安装或卸载。", 503)
            try:
                result = executor(action=change.action, plugin={
                    "id": change.plugin.id, "key": change.plugin.plugin_key,
                    "version": change.target_version, "source": change.plugin.source,
                    "source_url": change.plugin.source_url, "install_spec": change.plugin.install_spec,
                    "manifest": change.plugin.manifest_json, "package_sha256": change.plugin.package_sha256,
                    "user_id": change.target_user_id, "request_id": change.id,
                })
            except ControlServiceError:
                raise
            except ControlServiceError:
                # AI Server emits controlled Chinese compatibility/verification
                # errors; keep these actionable instead of hiding them as 502.
                raise
            except Exception as error:
                raise ControlServiceError("plugin_execution_failed", "AI Server 插件变更执行失败，未登记成功；请检查服务运行情况后重试。", 502) from error
            expected = "uninstalled" if change.action == "remove" else "disabled" if change.action == "disable" else "installed"
            if not isinstance(result, dict) or result.get("status") != expected or not isinstance(result.get("version"), str) or not result["version"] or result["version"] == "catalog":
                raise ControlServiceError("plugin_execution_unverified", "AI Server 未返回可验证的插件版本和状态，未登记成功。", 502)
            actual_version = result["version"]
            if installation is None:
                installation = PluginInstallation(
                    plugin_id=change.plugin_id,
                    user_id=change.target_user_id,
                    installed_version=actual_version,
                    granted_capabilities=change.requested_capabilities,
                    status="installed",
                )
                session.add(installation)
                session.flush()
                revision_number = 1
            else:
                revision_number = installation.version + 1
                installation.installed_version = actual_version
                installation.granted_capabilities = change.requested_capabilities
                installation.status = "disabled" if change.action == "disable" else "removed" if change.action == "remove" else "installed"
                installation.version += 1
            session.add(PluginInstallationRevision(
                installation_id=installation.id,
                revision_number=revision_number,
                installed_version=installation.installed_version,
                granted_capabilities=installation.granted_capabilities,
                status=installation.status,
                action=change.action,
                changed_by_user_id=user.id,
            ))
            change.status = "executed"
            change.target_version = actual_version
            change.executed_at = now
            return _serialize_plugin_request(change)
    finally:
        session.close()


def _validate_plugin_action(session: Any, plugin: PluginPackage, installation: PluginInstallation | None, action: str, target_version: str) -> None:
    active = installation is not None and installation.status in {"installed", "disabled"}
    if action == "install" and active:
        raise ControlServiceError("plugin_already_installed", "插件已经安装。", 409)
    if action in {"upgrade", "disable", "remove", "rollback"} and not active:
        raise ControlServiceError("plugin_not_installed", "插件尚未安装。", 409)
    if action == "upgrade" and installation is not None and installation.installed_version == plugin.current_version:
        raise ControlServiceError("plugin_already_current", "插件已经是最新版本。", 409)
    if action == "rollback":
        if not target_version.strip() or installation is None or target_version == installation.installed_version:
            raise ControlServiceError("invalid_rollback_version", "请选择一个历史安装版本。", 400)
        known = session.scalar(
            select(PluginInstallationRevision.id).where(
                PluginInstallationRevision.installation_id == installation.id,
                PluginInstallationRevision.installed_version == target_version,
            ).limit(1)
        )
        if known is None:
            raise ControlServiceError("rollback_version_not_found", "目标版本不在已验证的安装历史中。", 409)


def _plugin_capabilities(plugin: PluginPackage) -> list[str]:
    capabilities = plugin.manifest_json.get("capabilities", []) if isinstance(plugin.manifest_json, dict) else []
    if not isinstance(capabilities, list) or any(not isinstance(item, str) for item in capabilities):
        raise ControlServiceError("plugin_manifest_invalid", "插件权限清单格式无效。", 409)
    return list(dict.fromkeys(capabilities))


def _require_system_operator(user: User, message: str) -> None:
    level, _ = effective_ai_access(user)
    if level != "system_operator":
        raise ControlServiceError("forbidden", message, 403)


def _serialize_skill(skill: SkillDefinition, user: User) -> dict[str, Any]:
    return {
        "id": skill.id,
        "scope": skill.scope,
        "key": skill.skill_key,
        "name": skill.name,
        "description": skill.description,
        "status": skill.status,
        "current_version": skill.current_version_number,
        "published_at": skill.published_at.isoformat() if skill.published_at else None,
        "can_edit": (skill.scope == "personal" and skill.owner_user_id == user.id) or (skill.scope == "public" and effective_ai_access(user)[0] == "system_operator"),
    }


def _serialize_plugin(plugin: PluginPackage, installation: PluginInstallation | None, history: list[str] | None = None) -> dict[str, Any]:
    previous_versions = list(dict.fromkeys(history or []))
    if installation is not None:
        previous_versions = [item for item in previous_versions if item != installation.installed_version]
    return {
        "id": plugin.id,
        "key": plugin.plugin_key,
        "name": plugin.name,
        "description": plugin.description,
        "publisher": plugin.publisher,
        "version": plugin.current_version,
        "verified": plugin.verified,
        "installation_status": installation.status if installation else "not_installed",
        "installed_version": installation.installed_version if installation else "",
        "granted_capabilities": installation.granted_capabilities if installation else [],
        "rollback_versions": previous_versions,
    }


def _serialize_plugin_request(change: PluginChangeRequest) -> dict[str, Any]:
    return {
        "id": change.id,
        "plugin": {"id": change.plugin.id, "key": change.plugin.plugin_key, "name": change.plugin.name},
        "target_user": {"id": change.target_user.id, "name": change.target_user.display_name},
        "action": change.action,
        "from_version": change.from_version,
        "target_version": change.target_version,
        "requested_capabilities": change.requested_capabilities,
        "status": change.status,
        "request_reason": change.request_reason,
        "decision_reason": change.decision_reason,
        "created_at": change.created_at.isoformat() if change.created_at else "",
    }


def _serialize_model(model: AIModelConfig) -> dict[str, Any]:
    return {
        "id": model.id,
        "provider": {"key": model.provider.provider_key, "name": model.provider.display_name},
        "key": model.model_key,
        "name": model.display_name,
        "context_window": model.context_window,
        "supports_tools": model.supports_tools,
        "supports_json": model.supports_json,
    }


def _serialize_provider(provider: AIProviderConfig, *, include_hint: bool) -> dict[str, Any]:
    return {
        "id": provider.id,
        "key": provider.provider_key,
        "name": provider.display_name,
        "base_url": provider.base_url,
        "status": provider.status,
        "credential_configured": bool(provider.credential_ref),
        "credential_hint": provider.credential_hint if include_hint else "",
    }


def get_skill_detail(*, user: User, skill_id: str) -> dict[str, Any]:
    with db.session() as session:
        item = session.get(SkillDefinition, skill_id)
        if item is None or (item.scope == "personal" and item.owner_user_id != user.id):
            raise ControlServiceError("skill_not_found", "Skill 不存在或无权访问。", 404)
        version = session.scalar(select(SkillVersion).where(SkillVersion.skill_id == item.id, SkillVersion.version_number == item.current_version_number))
        return {**_serialize_skill(item, user), "instructions": version.instructions_text if version else "", "manifest": version.manifest_json if version else {}, "required_capabilities": version.required_capabilities if version else []}


def update_skill_status(*, user: User, skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """既有启用/停用开关（PATCH）与治理态的调和（T-S1）。

    旧值域 active/disabled 继续接受（桌面端零改动兼容），并等价映射到治理态：
    - published（旧 active）：个人 Skill=owner 自愈发布（幂等）；公共 Skill 拒绝——
      发布必须走 submit-review/publish 四闸，开关不得旁路（409 governance_required）。
    - deprecated（旧 disabled）：published → deprecated 下架（两 scope 皆可）；
      已 deprecated 幂等 no-op；草稿/待审核先回退语义不成立 → 409。
    """
    aliases = {"active": "published", "disabled": "deprecated"}
    raw = payload.get("status")
    if set(payload) != {"status"} or (raw not in aliases and raw not in SKILL_STATUSES):
        raise ControlServiceError("invalid_skill", "Skill 状态无效。", 400)
    target = aliases.get(raw, raw)
    with db.session() as session, session.begin():
        item = session.scalar(select(SkillDefinition).where(SkillDefinition.id == skill_id).with_for_update())
        if item is None:
            raise ControlServiceError("skill_not_found", "Skill 不存在。", 404)
        if not _serialize_skill(item, user)["can_edit"]:
            raise ControlServiceError("forbidden", "无权管理此 Skill。", 403)
        if target == "published":
            if item.scope != "personal":
                raise ControlServiceError(
                    "governance_required",
                    "公共 Skill 已启用治理流程：发布请走 submit-review/publish（四闸），开关不能旁路。",
                    409,
                )
            if item.status != "published":
                item.status = "published"
                item.published_by_user_id = user.id
                item.published_at = datetime.now(UTC)
                item.version += 1
            return _serialize_skill(item, user)
        # target == "deprecated"
        if item.status == "deprecated":
            return _serialize_skill(item, user)
        if item.status != "published":
            raise ControlServiceError(
                "not_deprecatable", "只有已发布（published）的 Skill 可以停用。", 409
            )
        item.status = "deprecated"
        item.version += 1
        return _serialize_skill(item, user)


def get_plugin_detail(*, user: User, plugin_id: str) -> dict[str, Any]:
    with db.session() as session:
        plugin = session.get(PluginPackage, plugin_id)
        if plugin is None or plugin.status != "active":
            raise ControlServiceError("plugin_not_found", "插件不存在或已下架。", 404)
        installation = session.scalar(select(PluginInstallation).where(PluginInstallation.plugin_id == plugin.id, PluginInstallation.user_id == user.id))
        return {**_serialize_plugin(plugin, installation), "source_url": plugin.source_url,
                "page_url": plugin.page_url, "category": plugin.category,
                "capabilities": _plugin_capabilities(plugin), "source": plugin.source,
                "install_available": callable(current_app.extensions.get("fde_plugin_executor")),
                "install_spec": plugin.install_spec}
