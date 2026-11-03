"""C9：集成桥 stale 判定双轨独立——fdeops 轨单独断连也要报警。

openfde 与 fdeops 是两条独立采集链；只看 openfde_synced_at 时，fdeops 文件
探针停摆（目录移走、.registry 锁死）不会黄标，投影悄然过期还显示「正常」。

V3 T-E3 另覆盖：投影把已挂接 workbench 项目的桥接采集同步登记为一等证据行
（kind=bridge，captured_from=bridge_sync:{run_id}），同指纹幂等。
"""
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, text

from fde_api.auth.models import User
from fde_api.bridge.sync import STALE_AFTER_MINUTES, apply_snapshot, engagement_view
from fde_api.evidence.models import ProjectEvidence
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, Project


def _seed_linked_project(db_session, *, openfde: str, fdeops: str) -> Project:
    leader = User(
        username=f"bridge.evidence.{uuid4().hex}",
        display_name="桥接证据负责人",
        role="project_lead",
        password_hash="x",
        must_change_password=False,
        is_active=True,
    )
    template = IndustryTemplate(name="桥接证据模板", industry_name="制造")
    template_version = IndustryTemplateVersion(
        template=template,
        name=template.name,
        industry_name="制造",
        description="",
        version_number=1,
        status="published",
        published_by=leader,
    )
    project = Project(
        project_code=f"FDE-BRIDGE-EVID-{uuid4().hex[:8]}",
        name="桥接证据项目",
        enterprise_code="星河制造·制造·苏州",
        leader=leader,
        source_template_version=template_version,
        template_snapshot={},
        planned_start_date=date(2026, 11, 2),
        openfde_engagement=openfde,
        fdeops_workspace=fdeops,
    )
    db_session.add_all([leader, template, template_version, project])
    db_session.commit()
    return project


def _payload(slug: str) -> dict:
    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "openfde": {
            "engagements": [
                {"slug": slug, "ok": True, "status": {"entities": 1}, "source_uri": "cli://openfde/x"}
            ]
        },
        "fdeops": {
            "registry_sha256": "a" * 64,
            "source_uri": "file://fdeops",
            "dirs": [{"slug": slug, "exists": True, "fde_initialized": True}],
        },
    }


def _age_fdeops_track(app, slug: str, hours: float) -> None:
    """把 fdeops 轨的 synced_at 拨回过去（模拟该轨探针停摆）。"""
    from fde_api.extensions import db

    with app.app_context():
        session = db.session()
        try:
            session.execute(
                text(
                    "UPDATE bridge_engagements SET fdeops_synced_at = :ts "
                    "WHERE slug = :slug"
                ),
                {
                    "ts": datetime.now(UTC) - timedelta(hours=hours),
                    "slug": slug,
                },
            )
            session.commit()
        finally:
            session.close()


def test_fdeops_track_disconnection_flags_stale(db_session, app, settings):
    slug = "c9-stale-check"
    apply_snapshot(_payload(slug), trigger="poller")
    _age_fdeops_track(app, slug, hours=STALE_AFTER_MINUTES + 2)

    view = engagement_view()
    row = next(item for item in view["engagements"] if item["slug"] == slug)
    assert "stale" in row["flags"], row["flags"]


def test_both_tracks_stale_yields_single_stale_flag(db_session, app, settings):
    """双轨同时断连只报一次 stale——「采集断连」是一个状态，不是两条事实。

    回归钉子：此前两条轨各自 append("stale")，同一行出现重复标记，
    前端会渲染出两个同名「采集断连」徽标，并因 key 重复触发 React 警告。
    """
    slug = "c9-both-stale"
    apply_snapshot(_payload(slug), trigger="poller")
    _age_fdeops_track(app, slug, hours=STALE_AFTER_MINUTES + 2)

    from fde_api.extensions import db

    with app.app_context():
        session = db.session()
        try:
            session.execute(
                text(
                    "UPDATE bridge_engagements SET openfde_synced_at = :ts "
                    "WHERE slug = :slug"
                ),
                {
                    "ts": datetime.now(UTC) - timedelta(minutes=STALE_AFTER_MINUTES + 2),
                    "slug": slug,
                },
            )
            session.commit()
        finally:
            session.close()

    view = engagement_view()
    row = next(item for item in view["engagements"] if item["slug"] == slug)
    assert "stale" in row["flags"], row["flags"]
    assert row["flags"].count("stale") == 1, row["flags"]
    assert len(row["flags"]) == len(set(row["flags"])), row["flags"]


def test_both_tracks_fresh_has_no_stale_flag(db_session, app, settings):
    slug = "c9-fresh-check"
    apply_snapshot(_payload(slug), trigger="poller")

    view = engagement_view()
    row = next(item for item in view["engagements"] if item["slug"] == slug)
    assert "stale" not in row["flags"], row["flags"]


def test_openfde_only_staleness_still_flags(db_session, app, settings):
    """原行为回归：openfde 轨断连照旧报警（C9 不许把旧语义修没）。"""
    slug = "c9-openfde-stale"
    apply_snapshot(_payload(slug), trigger="poller")
    from fde_api.extensions import db

    with app.app_context():
        session = db.session()
        try:
            session.execute(
                text(
                    "UPDATE bridge_engagements SET openfde_synced_at = :ts "
                    "WHERE slug = :slug"
                ),
                {
                    "ts": datetime.now(UTC) - timedelta(minutes=STALE_AFTER_MINUTES + 2),
                    "slug": slug,
                },
            )
            session.commit()
        finally:
            session.close()

    view = engagement_view()
    row = next(item for item in view["engagements"] if item["slug"] == slug)
    assert "stale" in row["flags"], row["flags"]


def test_bridge_snapshot_syncs_evidence_for_linked_projects(db_session, app, settings):
    """V3 T-E3：快照投影把已挂接项目的桥接采集登记为一等证据行
    （kind=bridge / captured_from=bridge_sync:{run_id} / created_by 空=机器通道）；
    未挂接的 slug 与指纹不齐整（hash 非法）的采集跳过且不炸；同快照重放幂等不增行。"""
    linked = _seed_linked_project(db_session, openfde="ev-linked", fdeops="ev-linked")

    payload = {
        "captured_at": datetime.now(UTC).isoformat(),
        "openfde": {
            "engagements": [
                {
                    "slug": "ev-linked",
                    "ok": True,
                    "status": {"entities": 1},
                    "source_uri": "cli://openfde/status?engagement=ev-linked",
                    "stdout_sha256": "C" * 64,
                },
                # 未挂接项目 → 不登记
                {"slug": "ev-unlinked", "ok": True, "status": {}, "stdout_sha256": "d" * 64},
                # 指纹不齐整（hash 非 64 位十六进制）→ 跳过不炸
                {"slug": "ev-linked", "ok": True, "status": {}, "stdout_sha256": "short"},
            ]
        },
        "fdeops": {
            "registry_sha256": "e" * 64,
            "source_uri": "file://fdeops",
            "dirs": [{"slug": "ev-linked", "exists": True}],
        },
    }
    result = apply_snapshot(payload, trigger="poller")

    db_session.rollback()
    rows = list(
        db_session.scalars(
            select(ProjectEvidence).order_by(ProjectEvidence.created_at, ProjectEvidence.id)
        )
    )
    # openfde 1 行（挂接 slug）+ fdeops 1 行（工作区级注册表同挂该项目）
    assert len(rows) == 2, [(r.source_uri, r.origin) for r in rows]
    by_uri = {row.source_uri: row for row in rows}
    openfde_row = by_uri["cli://openfde/status?engagement=ev-linked"]
    assert openfde_row.project_id == linked.id
    assert openfde_row.kind == "bridge"
    assert openfde_row.content_sha256 == "c" * 64
    assert openfde_row.captured_from.startswith("bridge_sync:")
    assert openfde_row.origin == "bridge:openfde/ev-linked"
    assert openfde_row.created_by_user_id is None
    fdeops_row = by_uri["file://fdeops"]
    assert fdeops_row.origin == "bridge:fdeops/ev-linked"
    assert fdeops_row.content_sha256 == "e" * 64
    assert result["summary"]["evidence_created"] == 2

    # 同快照重放（手动重投影语义）→ 同指纹幂等，不增行
    again = apply_snapshot(payload, trigger="manual_reproject")
    assert again["summary"]["evidence_created"] == 0
    db_session.rollback()
    assert len(list(db_session.scalars(select(ProjectEvidence)))) == 2
