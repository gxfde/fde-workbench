"""sync：单向投影器 + orphan 判定（设计 §4.3，A1「文件永远赢」）。

apply_snapshot 幂等 upsert bridge_engagements（按 slug），并把原始快照存进
bridge_sync_runs.payload——手动「重新投影」用它重放，不触发宿主采集。
orphan 语义：
  - vanished：bridge 行的 slug 在最近一次成功采集的存活集里消失（文件已删）→ 清投影候选
  - unlinked：engagement 存活但无 workbench 项目引用 → 可立项/绑定（不是垃圾）
  - orphan_openfde / orphan_fdeops：项目指针指向不存在的 engagement/目录
  - stale：任一轨 synced_at 距今超过 STALE_AFTER_MINUTES（采集链路断连，如 WSL 停机）；
    openfde 与 fdeops 双轨独立判定（C9：单看 openfde 会漏报 fdeops 探针停摆）
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, text

from fde_api.extensions import db
from fde_api.workbench.models import BridgeEngagement, BridgeSyncRun, Project

from fde_api.bridge.adapters import normalize_fdeops_dir, normalize_openfde_status

# 采集节奏每 4 小时（计划任务，2026-10-25 用户裁决放宽），一个周期加余量 = 断连
STALE_AFTER_MINUTES = 360

# CR-029：宿主钟偏移观测容差——|captured_at - 服务端钟| 超过该值才把偏移记进
# run.summary["captured_at_skew_seconds"]（正常钟不污染 summary 形状）。
CAPTURED_AT_SKEW_TOLERANCE_SECONDS = 90 * 60


class BridgeSyncError(Exception):
    """同步失败（对外 500 / 404 / 409 由 routes 翻译）。"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_captured_at(payload: dict[str, Any]) -> datetime:
    raw = payload.get("captured_at")
    if not isinstance(raw, str) or not raw:
        raise BridgeSyncError("captured_at missing")
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise BridgeSyncError(f"captured_at not ISO format: {raw!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _live_sets(payload: dict[str, Any]) -> tuple[set[str], set[str]]:
    """从快照推存活集：openfde=engagement list 成员（含 status 报错的）；fdeops=目录存在。"""
    openfde = payload.get("openfde") or {}
    engagements = openfde.get("engagements") or []
    openfde_live = {
        entry["slug"] for entry in engagements if isinstance(entry, dict) and isinstance(entry.get("slug"), str)
    }
    fdeops = payload.get("fdeops") or {}
    dirs = fdeops.get("dirs") or []
    fdeops_live = {
        entry["slug"]
        for entry in dirs
        if isinstance(entry, dict) and entry.get("slug") and entry.get("exists") is True
    }
    return openfde_live, fdeops_live


def _last_successful_payload(session) -> tuple[str | None, dict[str, Any] | None]:
    run = session.scalar(
        select(BridgeSyncRun)
        .where(BridgeSyncRun.ok.is_(True), BridgeSyncRun.payload.is_not(None))
        .order_by(BridgeSyncRun.started_at.desc())
        .limit(1)
    )
    if run is None:
        return None, None
    return run.id, run.payload


_HEX64_PATTERN = re.compile(r"[0-9a-fA-F]{64}")


def _valid_fingerprint(uri: object, sha: object) -> tuple[str, str] | None:
    """一等证据表的指纹门槛（uri 1–500 + sha256 64 位十六进制）；不齐整跳过。"""
    if not isinstance(uri, str) or not 0 < len(uri.strip()) <= 500:
        return None
    if not isinstance(sha, str) or not _HEX64_PATTERN.fullmatch(sha):
        return None
    return uri.strip(), sha.lower()


def _sync_bridge_evidence(session, *, run: BridgeSyncRun, payload: dict[str, Any]) -> int:
    """V3 T-E3：桥接投影可选落一等证据行（kind=bridge，captured_from=bridge_sync:{run_id}）。

    只对已挂接 workbench 项目的 slug 写（openfde 按 openfde_engagement、fdeops 按
    fdeops_workspace 反查）；指纹不齐整（缺 sha256 / uri 越界）跳过——投影是 4h
    关键路径，证据永远是锦上添花，不构成失败。同指纹幂等（内容不变不增行）；
    内容变化 = 新指纹 = 新行（不可变采集史）。DB 级故障不上吞：随投影一起落
    failed run（与既有 all-or-nothing 一致）。返回本次新建行数（进 run.summary）。"""
    # 延迟导入：与 gate_service/task_service 同纪律，避免模块级互导成环
    from fde_api.evidence.service import upsert_evidence

    openfde = payload.get("openfde") or {}
    fdeops = payload.get("fdeops") or {}
    openfde_links: dict[str, list[str]] = {}
    fdeops_links: dict[str, list[str]] = {}
    # CR-030：4h 投影热路径只吃三列——列投影替代整表 ORM 水合（docstring 自称
    # 「关键路径」，别让数百项目量级的全列构造拖在每拍前面）。
    for project_id, openfde_engagement, fdeops_workspace in session.execute(
        select(Project.id, Project.openfde_engagement, Project.fdeops_workspace)
    ).all():
        if openfde_engagement:
            openfde_links.setdefault(openfde_engagement, []).append(project_id)
        if fdeops_workspace:
            fdeops_links.setdefault(fdeops_workspace, []).append(project_id)

    # 候选 = (project_id, source_uri, sha256, origin)
    candidates: list[tuple[str, str, str, str]] = []
    for entry in openfde.get("engagements") or []:
        if not isinstance(entry, dict) or entry.get("ok") is not True:
            continue
        slug = entry.get("slug")
        targets = openfde_links.get(slug) if isinstance(slug, str) else None
        if not targets:
            continue
        fingerprint = _valid_fingerprint(
            entry.get("source_uri") or f"cli://openfde/status?engagement={slug}",
            entry.get("stdout_sha256"),
        )
        if fingerprint is None:
            continue
        uri, sha = fingerprint
        candidates.extend(
            (project_id, uri, sha, f"bridge:openfde/{slug}") for project_id in targets
        )

    # fdeops 轨是工作区级注册表：一个 registry_sha256 对全部存活目录
    registry_fingerprint = _valid_fingerprint(
        fdeops.get("source_uri") or "file://fdeops", fdeops.get("registry_sha256")
    )
    if registry_fingerprint is not None:
        uri, sha = registry_fingerprint
        for slug, targets in fdeops_links.items():
            candidates.extend(
                (project_id, uri, sha, f"bridge:fdeops/{slug}") for project_id in targets
            )

    created = 0
    for project_id, uri, sha, origin in candidates:
        _, was_created = upsert_evidence(
            session,
            project_id=project_id,
            kind="bridge",
            source_uri=uri,
            content_sha256=sha,
            origin=origin,
            captured_from=f"bridge_sync:{run.id}",
            created_by_user_id=None,
        )
        created += int(was_created)
    return created


def apply_snapshot(payload: dict[str, Any], trigger: str) -> dict[str, Any]:
    """快照落库。注意 db.session() 是 sessionmaker 语义（每次新开），
    摘要必须等投影提交后再取视图——分三段：①upsert+提交 ②标记 run ok+提交
    ③取视图算 flags 回写 summary。②③失败只缺摘要，不影响投影本身。

    CR-029：captured_at 只过格式校验，落库前单向钳制——快照不可能比服务端
    收到它更「新」，未来时戳（宿主 NTP 前漂/带桥令牌伪造）一律钳到接收时刻，
    否则 now - synced_at 恒为负、4h/360min stale 标永不亮（断连被永久遮蔽）。
    过去方向不钳（只会更早触发 stale，无害方向，且钳过去会伪造 manual_reproject
    重放旧快照的新鲜度）。宿主钟偏移超容差记入 summary 供运维定位。"""
    captured = _parse_captured_at(payload)
    session = db.session()
    # 串行化投影：gunicorn 2 workers 下 4h 采集与手动「重新投影」并发时，
    # check-then-insert 会双双 INSERT 撞 uq_bridge_engagements_slug（500）。
    # 事务级 advisory lock 让同 slug 集的投影完全串行，也顺带关掉
    # 「reproject 读到旧 payload 覆盖新投影」的两段式窗口。
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext('fde_bridge_apply'))"))
    received_at = _utcnow()
    # CR-029：原始偏移先记（钳制不改写观测值）——负值=宿主钟超前（未来时戳
    # 方向，落库前已钳到 received_at），正值=宿主钟滞后（stale 只会更早触发）。
    captured_at_skew_seconds = (received_at - captured).total_seconds()
    if captured > received_at:
        captured = received_at
    run = BridgeSyncRun(trigger=trigger, payload=payload, started_at=received_at)
    session.add(run)
    try:
        openfde = payload.get("openfde") or {}
        fdeops = payload.get("fdeops") or {}
        seen_slugs: set[str] = set()

        for entry in openfde.get("engagements") or []:
            slug = entry.get("slug")
            if not isinstance(slug, str) or not slug:
                continue
            seen_slugs.add(slug)
            row = session.scalar(select(BridgeEngagement).where(BridgeEngagement.slug == slug))
            if row is None:
                row = BridgeEngagement(slug=slug)
                session.add(row)
            if entry.get("ok") is True:
                row.openfde_status = normalize_openfde_status(entry.get("status"))
                row.openfde_synced_at = captured
                row.openfde_source_uri = entry.get("source_uri") or f"cli://openfde/status?engagement={slug}"
                row.openfde_content_hash = entry.get("stdout_sha256")
            else:
                # CLI 对该 slug 报错：保留旧投影，只记错误（A1——采集失败不等于文件没了）
                merged = dict(row.openfde_status or {})
                merged["capture_error"] = (entry.get("error") or "capture failed")[:500]
                row.openfde_status = merged

        fdeops_hash = fdeops.get("registry_sha256")
        fdeops_uri = fdeops.get("source_uri")
        for entry in fdeops.get("dirs") or []:
            slug = entry.get("slug")
            if not isinstance(slug, str) or not slug:
                continue
            seen_slugs.add(slug)
            row = session.scalar(select(BridgeEngagement).where(BridgeEngagement.slug == slug))
            if row is None:
                row = BridgeEngagement(slug=slug)
                session.add(row)
            if entry.get("exists") is True:
                row.fdeops_state = normalize_fdeops_dir(entry)
                row.fdeops_synced_at = captured
                row.fdeops_source_uri = fdeops_uri or f"file://fdeops/{slug}"
                row.fdeops_content_hash = fdeops_hash
            else:
                merged = dict(row.fdeops_state or {})
                merged["capture_error"] = "directory missing"
                row.fdeops_state = merged

        run.engagements_seen = len(seen_slugs)
        # V3 T-E3：投影事务内顺带把已挂接项目的桥接采集登记为一等证据行（幂等）
        evidence_created = _sync_bridge_evidence(session, run=run, payload=payload)
        session.commit()
    except BridgeSyncError as exc:
        session.rollback()
        raise exc
    except Exception as exc:  # noqa: BLE001 —— 失败也要落一行日志再上抛
        session.rollback()
        failed = db.session()
        failed.add(BridgeSyncRun(trigger=trigger, ok=False, error=str(exc)[:2000], started_at=_utcnow()))
        failed.commit()
        raise BridgeSyncError(f"snapshot apply failed: {exc}") from exc

    # ② 标记成功（视图算 vanished/orphan 依赖「最近一次成功 run」，必须先落 ok）
    run_id = run.id
    mark = db.session()
    mark.get(BridgeSyncRun, run_id).ok = True
    mark.get(BridgeSyncRun, run_id).finished_at = _utcnow()
    mark.commit()

    # ③ 提交后取视图算摘要并回写
    view = engagement_view()
    summary = {
        "engagements_seen": len(seen_slugs),
        "openfde_slugs": sorted(_live_sets(payload)[0]),
        "fdeops_slugs": sorted(_live_sets(payload)[1]),
        "vanished": sum("vanished" in e["flags"] for e in view["engagements"]),
        "unlinked": sum("unlinked" in e["flags"] for e in view["engagements"]),
        "orphan_projects": sum(1 for p in view["projects"] if p["flags"]),
        "evidence_created": evidence_created,
    }
    # CR-029：宿主钟偏移观测——|skew| 超容差才带键（正常钟不污染 summary 形状）；
    # 这是运维定位面：「为什么全场 stale」→ 看本键即知是宿主钟漂了多大。
    if abs(captured_at_skew_seconds) > CAPTURED_AT_SKEW_TOLERANCE_SECONDS:
        summary["captured_at_skew_seconds"] = int(captured_at_skew_seconds)
    finish = db.session()
    finish.get(BridgeSyncRun, run_id).summary = summary
    # 采集每 4h 存全量 payload（50 文件名 × 200 目录），只留最近 200 行防膨胀
    keep_ids = list(
        finish.scalars(
            select(BridgeSyncRun.id).order_by(BridgeSyncRun.started_at.desc()).limit(200)
        )
    )
    if keep_ids:
        finish.execute(delete(BridgeSyncRun).where(BridgeSyncRun.id.not_in(keep_ids)))
    finish.commit()
    return {"run_id": run_id, "engagements_seen": len(seen_slugs), "summary": summary}


def reproject_last() -> dict[str, Any]:
    """手动重投影：重放最近一次成功采集的原始快照（不触发宿主采集）。"""
    session = db.session()
    run_id, payload = _last_successful_payload(session)
    if payload is None:
        raise BridgeSyncError("no successful snapshot to reproject")
    return apply_snapshot(payload, trigger="manual_reproject")


def engagement_view() -> dict[str, Any]:
    """双轨状态一屏看的后端视图：bridge 行 + 项目指针审计 + flags。"""
    session = db.session()
    rows = session.scalars(select(BridgeEngagement).order_by(BridgeEngagement.slug)).all()
    _, last_payload = _last_successful_payload(session)
    openfde_live: set[str] = set()
    fdeops_live: set[str] = set()
    if last_payload is not None:
        openfde_live, fdeops_live = _live_sets(last_payload)

    projects = session.scalars(select(Project).order_by(Project.created_at.desc())).all()
    openfde_links: dict[str, list[dict[str, str]]] = {}
    fdeops_links: dict[str, list[dict[str, str]]] = {}
    for project in projects:
        if project.openfde_engagement:
            openfde_links.setdefault(project.openfde_engagement, []).append(
                {"project_id": project.id, "project_name": project.name}
            )
        if project.fdeops_workspace:
            fdeops_links.setdefault(project.fdeops_workspace, []).append(
                {"project_id": project.id, "project_name": project.name}
            )

    now = _utcnow()
    engagements = []
    for row in rows:
        flags: list[str] = []
        has_data = row.openfde_synced_at is not None or row.fdeops_synced_at is not None
        if last_payload is not None and has_data and row.slug not in openfde_live and row.slug not in fdeops_live:
            flags.append("vanished")
        # C9：fdeops 轨单独断连也要报警——双轨独立采集，只看 openfde 时
        # fdeops 文件探针停摆（如目录移走）不会黄标，投影悄然过期。
        # 两条轨都可能判定 stale，但「采集断连」是一个状态而非两条事实：
        # 重复 append 会让前端渲染出两个同名徽标（并触发 React 重复 key 警告），
        # 故此处只判定一次——任一轨断连即 stale。
        openfde_stale = (
            row.openfde_synced_at is not None
            and row.slug in openfde_live
            and (now - row.openfde_synced_at).total_seconds() > STALE_AFTER_MINUTES * 60
        )
        fdeops_stale = (
            row.fdeops_synced_at is not None
            and row.slug in fdeops_live
            and (now - row.fdeops_synced_at).total_seconds() > STALE_AFTER_MINUTES * 60
        )
        if openfde_stale or fdeops_stale:
            flags.append("stale")
        linked = openfde_links.get(row.slug, []) + [
            item for item in fdeops_links.get(row.slug, [])
            if item not in openfde_links.get(row.slug, [])
        ]
        if not linked:
            flags.append("unlinked")
        engagements.append({
            "slug": row.slug,
            "openfde_status": row.openfde_status,
            "openfde_synced_at": row.openfde_synced_at.isoformat() if row.openfde_synced_at else None,
            "openfde_source_uri": row.openfde_source_uri,
            "openfde_content_hash": row.openfde_content_hash,
            "fdeops_state": row.fdeops_state,
            "fdeops_synced_at": row.fdeops_synced_at.isoformat() if row.fdeops_synced_at else None,
            "fdeops_source_uri": row.fdeops_source_uri,
            "fdeops_content_hash": row.fdeops_content_hash,
            "linked_projects": linked,
            "flags": flags,
        })

    project_flags = []
    for project in projects:
        flags: list[str] = []
        if last_payload is not None:
            if project.openfde_engagement:
                if project.openfde_engagement not in openfde_live:
                    flags.append("orphan_openfde")
            else:
                flags.append("missing_openfde_pointer")
            if project.fdeops_workspace and project.fdeops_workspace not in fdeops_live:
                flags.append("orphan_fdeops")
        project_flags.append({
            "project_id": project.id,
            "project_name": project.name,
            "enterprise_code": project.enterprise_code,
            "openfde_engagement": project.openfde_engagement,
            "fdeops_workspace": project.fdeops_workspace,
            "flags": flags,
        })

    return {
        "captured_at": (
            _parse_captured_at(last_payload).isoformat() if last_payload is not None else None
        ),
        "stale_after_minutes": STALE_AFTER_MINUTES,
        "engagements": engagements,
        "projects": project_flags,
    }


def delete_projection(slug: str) -> None:
    """清投影：只删 bridge 行，绝不动真相文件。文件仍存活的拒绝删（下一轮采集会复活）。"""
    session = db.session()
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext('fde_bridge_apply'))"))
    row = session.scalar(select(BridgeEngagement).where(BridgeEngagement.slug == slug))
    if row is None:
        raise BridgeSyncError("projection not found")
    _, last_payload = _last_successful_payload(session)
    if last_payload is not None:
        openfde_live, fdeops_live = _live_sets(last_payload)
        if slug in openfde_live or slug in fdeops_live:
            raise BridgeSyncError("engagement still live in files; projection cannot be removed")
    session.delete(row)
    session.commit()


def recent_runs(limit: int = 5) -> list[dict[str, Any]]:
    session = db.session()
    runs = session.scalars(
        select(BridgeSyncRun).order_by(BridgeSyncRun.started_at.desc()).limit(limit)
    ).all()
    return [
        {
            "id": run.id,
            "trigger": run.trigger,
            "ok": run.ok,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "engagements_seen": run.engagements_seen,
            "summary": run.summary,
            "error": run.error,
        }
        for run in runs
    ]
