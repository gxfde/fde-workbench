"""CR-029：集成桥 captured_at 单向采信宿主钟——未来时戳遮「采集断连」。

_parse_captured_at 只校验格式不比对服务端钟；宿主 NTP 前漂或带
FDE_BRIDGE_TOKEN 方伪造 captured_at（未来）→ synced_at 落在未来 →
now - synced_at 恒为负 → 4h/360min stale 标永不亮（文件盘上持续腐仍显
「新鲜」）。

修法（登记建议的单向收窄实施）：apply_snapshot 内钳制——快照不可能比
服务端收到它更「新」，未来时戳一律钳到服务端接收时刻（stale 数学恢复
「距上次采集接收多久」的本义，与偏移量无关）；过去方向不钳（只会更早
触发 stale，无害方向，且钳过去会伪造 manual_reproject 重放旧快照的
新鲜度）；宿主钟偏移超 CAPTURED_AT_SKEW_TOLERANCE_SECONDS 记
run.summary["captured_at_skew_seconds"]（负值=宿主钟超前）供运维定位。
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from fde_api.bridge.sync import (
    CAPTURED_AT_SKEW_TOLERANCE_SECONDS,
    STALE_AFTER_MINUTES,
    apply_snapshot,
    engagement_view,
    reproject_last,
)
from fde_api.extensions import db
from fde_api.workbench.models import BridgeEngagement


def _payload(captured_at: datetime, slug: str) -> dict:
    return {
        "captured_at": captured_at.isoformat(),
        "openfde": {
            "engagements": [
                {"slug": slug, "ok": True, "status": {"entities": 1}, "source_uri": "cli://openfde/x"}
            ]
        },
        "fdeops": {
            "registry_sha256": "b" * 64,
            "source_uri": "file://fdeops",
            "dirs": [{"slug": slug, "exists": True, "fde_initialized": True}],
        },
    }


def _stored(slug: str) -> tuple[datetime | None, datetime | None]:
    """读回投影行的双轨 synced_at（服务级直读，绕开视图的 ISO 字符串化）。

    调用方须持 app 上下文（与 test_bridge_sync_flags 的直读纪律同构）。"""
    session = db.session()
    try:
        row = session.scalar(select(BridgeEngagement).where(BridgeEngagement.slug == slug))
        assert row is not None, f"projection row missing for {slug}"
        return row.openfde_synced_at, row.fdeops_synced_at
    finally:
        session.close()


def test_future_captured_at_clamped_never_stored_future(db_session, app):
    """未来时戳（NTP 前漂/伪造 >6h）落库前钳到服务端接收时刻。

    不变量：stored synced_at 永不晚于服务端当下 ⇒ now - synced_at ≥ 0，
    stale 数学恢复本义——采集停止后 360min 内必亮，断连无法被永久遮蔽。
    """
    slug = "c29-clamp-future"
    poisoned = datetime.now(UTC) + timedelta(hours=6)
    apply_snapshot(_payload(poisoned, slug), trigger="poller")
    with app.app_context():
        openfde_at, fdeops_at = _stored(slug)
    now = datetime.now(UTC)
    assert openfde_at is not None and openfde_at.tzinfo is not None
    assert openfde_at <= now + timedelta(seconds=2), f"openfde_synced_at 落在未来: {openfde_at}"
    assert fdeops_at is not None and fdeops_at <= now + timedelta(seconds=2)
    # 钳制不吞数据：engagement 仍正常投影（数据面零损失，只是时间戳诚实化）
    view = engagement_view()
    row = next(item for item in view["engagements"] if item["slug"] == slug)
    assert "stale" not in row["flags"], row["flags"]


def test_small_future_skew_also_clamped(db_session, app):
    """钳制与偏移量无关——「不存未来时戳」是不变量本身，不受容差门控。

    容差（90min）只管观测标记是否入 summary，不是钳制的闸门。
    """
    slug = "c29-clamp-small-future"
    poisoned = datetime.now(UTC) + timedelta(minutes=2)
    apply_snapshot(_payload(poisoned, slug), trigger="poller")
    with app.app_context():
        openfde_at, _ = _stored(slug)
    assert openfde_at is not None
    assert openfde_at <= datetime.now(UTC) + timedelta(seconds=2), f"落在未来: {openfde_at}"


def test_future_skew_recorded_in_run_summary(db_session, app):
    """宿主钟超前超容差 → run.summary 带负值 captured_at_skew_seconds。

    这是运维定位面：全场 stale 诡异亮起时，看本键即知宿主钟漂了多大。
    """
    slug = "c29-skew-future-summary"
    poisoned = datetime.now(UTC) + timedelta(hours=6)
    result = apply_snapshot(_payload(poisoned, slug), trigger="poller")
    skew = result["summary"]["captured_at_skew_seconds"]
    assert skew < -CAPTURED_AT_SKEW_TOLERANCE_SECONDS, skew
    assert skew >= -(6 * 3600 + 60), skew  # ≈ -21600，只容忍测试执行的钟差


def test_normal_skew_omits_summary_key(db_session, app):
    """正常钟（|skew| < 90min）→ summary 不带 captured_at_skew_seconds。

    观测键超容差才出现——正常采集不污染 summary 形状（桌面宽松消费，
    但形状稳定性仍是契约面）。
    """
    slug = "c29-skew-normal"
    result = apply_snapshot(_payload(datetime.now(UTC), slug), trigger="poller")
    assert "captured_at_skew_seconds" not in result["summary"], result["summary"]


def test_past_captured_at_passes_through_and_stale_lights(db_session, app):
    """过去方向不钳——快照声称 3 天前采的就是 3 天前（诚实保留），stale
    立即亮起（只会更早触发 = 无害方向，且这是 manual_reproject 重放旧
    快照必须保真的语义）。"""
    slug = "c29-past-passthrough"
    ancient = datetime.now(UTC) - timedelta(days=3)
    apply_snapshot(_payload(ancient, slug), trigger="poller")
    with app.app_context():
        openfde_at, fdeops_at = _stored(slug)
    assert openfde_at is not None
    assert abs((openfde_at - ancient).total_seconds()) < 5, f"过去值被改写: {openfde_at}"
    assert fdeops_at is not None and abs((fdeops_at - ancient).total_seconds()) < 5
    view = engagement_view()
    row = next(item for item in view["engagements"] if item["slug"] == slug)
    assert "stale" in row["flags"], row["flags"]


def test_manual_reproject_does_not_refresh_freshness(db_session, app):
    """manual_reproject 重放旧快照不刷新新鲜度——stored 仍是原始采集时刻
    （过去方向不钳的推论：重投影 ≠ 采集，不得把 stale 钟清零）。

    回归钉：若钳制误写成「统一钳到接收时刻」，重放 30 分钟前的快照会把
    synced_at 抬到重放当下，stale 检测被手动操作重置——本例转红。
    """
    slug = "c29-reproject-honest"
    collected = datetime.now(UTC) - timedelta(minutes=30)
    apply_snapshot(_payload(collected, slug), trigger="poller")
    reproject_last()
    with app.app_context():
        openfde_at, _ = _stored(slug)
    assert openfde_at is not None
    assert abs((openfde_at - collected).total_seconds()) < 5, (
        f"重投影刷新了新鲜度（应为原始采集时刻）: {openfde_at}"
    )
    # 距原始采集 30min < 360min：未 stale；若被刷新则更不会 stale——
    # 本例的断言力在上一行的时刻等值，不在 stale 翻转。
    assert STALE_AFTER_MINUTES == 360  # 口径锚：本文件所有时长断言的基准
