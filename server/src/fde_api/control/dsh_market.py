from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Any
from urllib.parse import urlparse

import requests
from flask import current_app
from sqlalchemy import func, or_, select

from fde_api.auth.models import ROLE_ADMIN, User
from fde_api.control.access import effective_ai_access
from fde_api.control.models import PluginCatalogSync, PluginPackage, UserAIAccessGrant
from fde_api.control.service import ControlServiceError
from fde_api.extensions import db


SOURCE = "dsh-market"
_PACKAGE = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")


def sync_dsh_market(*, user: User, http: requests.Session | None = None) -> dict[str, Any]:
    level, _ = effective_ai_access(user)
    if level != "system_operator":
        raise ControlServiceError("forbidden", "只有系统运维员可以同步插件目录。", 403)
    return _sync_dsh_market(actor=user, http=http)


def _sync_dsh_market(*, actor: User, http: requests.Session | None = None) -> dict[str, Any]:
    settings = current_app.config["SETTINGS"]
    if not settings.dsh_market_enabled:
        raise ControlServiceError("marketplace_disabled", "dsh-market 尚未启用。", 409)

    try:
        raw, document, entries = _fetch_catalog(http=http)
    except ControlServiceError as error:
        _record_sync_failure(registry_url=settings.dsh_market_registry_url, message=error.message)
        raise

    digest = sha256(raw).hexdigest()
    session = db.session()
    try:
        with session.begin():
            existing = {
                item.plugin_key: item
                for item in session.scalars(select(PluginPackage).where(PluginPackage.source == SOURCE).with_for_update())
            }
            active_keys: set[str] = set()
            for entry in entries:
                plugin_key = _plugin_key(entry["url"])
                active_keys.add(plugin_key)
                item = existing.get(plugin_key)
                values = _package_values(entry)
                if item is None:
                    item = PluginPackage(
                        plugin_key=plugin_key,
                        created_by_user_id=actor.id,
                        package_sha256="",
                        verified=False,
                        **values,
                    )
                    session.add(item)
                else:
                    changed = any(getattr(item, key) != value for key, value in values.items())
                    for key, value in values.items():
                        setattr(item, key, value)
                    if changed:
                        item.version += 1
            for key, item in existing.items():
                if key not in active_keys and item.status != "disabled":
                    item.status = "disabled"
                    item.version += 1
            state = session.scalar(select(PluginCatalogSync).where(PluginCatalogSync.source == SOURCE).with_for_update())
            if state is None:
                state = PluginCatalogSync(source=SOURCE, registry_url=settings.dsh_market_registry_url)
                session.add(state)
            state.registry_url = settings.dsh_market_registry_url
            state.registry_updated = str(document.get("updated", ""))[:80]
            state.plugin_count = len(entries)
            state.content_sha256 = digest
            state.status = "ready"
            state.error_message = ""
            registry_updated = state.registry_updated
        return {"source": SOURCE, "status": "ready", "plugin_count": len(entries), "registry_updated": registry_updated}
    finally:
        session.close()


def sync_dsh_market_scheduled(*, http: requests.Session | None = None) -> dict[str, Any]:
    """Run the same guarded sync under an explicitly granted system operator."""
    session = db.session()
    try:
        actor = session.scalar(
            select(User)
            .join(UserAIAccessGrant, UserAIAccessGrant.user_id == User.id)
            .where(User.is_active.is_(True), UserAIAccessGrant.access_level == "system_operator")
            .order_by(UserAIAccessGrant.created_at, User.id)
            .limit(1)
        )
    finally:
        session.close()
    if actor is None:
        session = db.session()
        try:
            actor = session.scalar(
                select(User).where(User.is_active.is_(True), User.role == ROLE_ADMIN).order_by(User.created_at, User.id).limit(1)
            )
        finally:
            session.close()
    if actor is None:
        raise ControlServiceError("marketplace_operator_missing", "没有可记录自动同步操作的活动管理员。", 409)
    return _sync_dsh_market(actor=actor, http=http)


def search_dsh_market(*, query: str, category: str, page: int, page_size: int) -> dict[str, Any]:
    if page < 1 or page_size < 1 or page_size > 100 or len(query) > 160 or len(category) > 120:
        raise ControlServiceError("invalid_marketplace_query", "插件市场查询参数无效。", 400)
    session = db.session()
    try:
        filters = [PluginPackage.source == SOURCE, PluginPackage.status == "active"]
        if query.strip():
            term = f"%{query.strip()}%"
            filters.append(or_(PluginPackage.name.like(term), PluginPackage.description.like(term), PluginPackage.publisher.like(term)))
        if category.strip():
            filters.append(PluginPackage.category == category.strip())
        total = session.scalar(select(func.count()).select_from(PluginPackage).where(*filters)) or 0
        items = list(session.scalars(select(PluginPackage).where(*filters).order_by(PluginPackage.name, PluginPackage.id).offset((page - 1) * page_size).limit(page_size)))
        categories = [
            {"key": key, "count": count}
            for key, count in session.execute(
                select(PluginPackage.category, func.count()).where(PluginPackage.source == SOURCE, PluginPackage.status == "active").group_by(PluginPackage.category).order_by(PluginPackage.category)
            )
            if key
        ]
        return {"items": [_serialize_market_item(item) for item in items], "total": total, "page": page, "page_size": page_size, "categories": categories}
    finally:
        session.close()


def marketplace_status(*, enabled: bool, registry_url: str) -> dict[str, Any]:
    session = db.session()
    try:
        state = session.scalar(select(PluginCatalogSync).where(PluginCatalogSync.source == SOURCE))
        return {
            "connected": bool(enabled and state and state.plugin_count > 0),
            "enabled": enabled,
            "status": state.status if state else ("not_synced" if enabled else "disabled"),
            "source": SOURCE,
            "registry_url": registry_url,
            "plugin_count": state.plugin_count if state else 0,
            "registry_updated": state.registry_updated if state else "",
            "last_error": state.error_message if state else "",
        }
    finally:
        session.close()


def _validate_catalog(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, dict) or not isinstance(document.get("plugins"), list):
        raise ValueError("invalid root")
    plugins = document["plugins"]
    if len(plugins) > 10_000:
        raise ValueError("too many plugins")
    result = []
    for entry in plugins:
        if not isinstance(entry, dict):
            raise ValueError("invalid entry")
        name, owner, url = entry.get("name"), entry.get("owner"), entry.get("url")
        if not all(isinstance(value, str) and value.strip() for value in (name, owner, url)):
            raise ValueError("missing identity")
        if len(name) > 160 or len(owner) > 160 or not _safe_github_url(url):
            raise ValueError("unsafe identity")
        npm = entry.get("npm")
        tarball = entry.get("tarball")
        if npm is not None and (not isinstance(npm, str) or not _PACKAGE.fullmatch(npm)):
            raise ValueError("unsafe npm package")
        if tarball is not None and (not isinstance(tarball, str) or not _safe_https_url(tarball)):
            raise ValueError("unsafe tarball")
        result.append(entry)
    return result


def _fetch_catalog(*, http: requests.Session | None) -> tuple[bytes, dict[str, Any], list[dict[str, Any]]]:
    settings = current_app.config["SETTINGS"]
    client = http or requests.Session()
    try:
        response = client.get(
            settings.dsh_market_registry_url,
            timeout=settings.dsh_market_timeout_seconds,
            allow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": "FDE-Workbench/dsh-market-v1"},
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise ControlServiceError("marketplace_unavailable", "dsh-market 目录暂时不可用。", 502) from error
    raw = response.content
    if len(raw) > settings.dsh_market_max_catalog_bytes:
        raise ControlServiceError("marketplace_invalid", "dsh-market 目录文件超过安全上限。", 502)
    try:
        document = json.loads(raw.decode("utf-8"))
        entries = _validate_catalog(document)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ControlServiceError("marketplace_invalid", "dsh-market 目录格式不正确。", 502) from error
    return raw, document, entries


def _record_sync_failure(*, registry_url: str, message: str) -> None:
    session = db.session()
    try:
        with session.begin():
            state = session.scalar(select(PluginCatalogSync).where(PluginCatalogSync.source == SOURCE).with_for_update())
            if state is None:
                state = PluginCatalogSync(source=SOURCE, registry_url=registry_url)
                session.add(state)
            state.registry_url = registry_url
            state.status = "degraded"
            state.error_message = message[:500]
    finally:
        session.close()


def _package_values(entry: dict[str, Any]) -> dict[str, Any]:
    description = entry.get("description", {})
    description_text = (description.get("zh") or description.get("en") or "") if isinstance(description, dict) else ""
    safe_manifest = {key: entry.get(key) for key in ("npm", "tarball", "stars", "downloads", "added") if entry.get(key) is not None}
    canonical = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    page = entry.get("page", "")
    return {
        "name": entry["name"].strip(), "description": str(description_text)[:10_000], "publisher": entry["owner"].strip(),
        "current_version": "catalog", "manifest_json": safe_manifest, "status": "active", "source": SOURCE,
        "source_url": entry["url"], "page_url": page if _safe_https_url(page, allow_empty=True) else "",
        "category": str(entry.get("category", ""))[:120], "install_spec": entry.get("npm") or entry.get("tarball") or entry["url"],
        "catalog_entry_sha256": sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _plugin_key(url: str) -> str:
    return f"dsh-market:{sha256(url.rstrip('/').lower().encode('utf-8')).hexdigest()[:32]}"


def _safe_github_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and parsed.hostname == "github.com" and parsed.username is None


def _safe_https_url(value: Any, *, allow_empty: bool = False) -> bool:
    if allow_empty and value == "":
        return True
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.hostname) and parsed.username is None


def _serialize_market_item(item: PluginPackage) -> dict[str, Any]:
    return {
        "id": item.id, "key": item.plugin_key, "name": item.name, "description": item.description,
        "publisher": item.publisher, "category": item.category, "source_url": item.source_url, "page_url": item.page_url,
        "stars": item.manifest_json.get("stars"), "downloads": item.manifest_json.get("downloads"),
        "verified": item.verified, "install_available": False,
    }
