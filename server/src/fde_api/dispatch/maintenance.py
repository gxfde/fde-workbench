"""dispatch 维护任务（P1-7 留存策略 + 超时释放调度，goal-r6）。

- 超时释放（§2.5/§6.2）：expire_stale_offers（r4 已实现）挂进调度。
- 留存扫描（规则表 B11 / §6.2）：撮合流水与评分留痕 3 年、涉税资料 10 年
  ——本任务只**报告**超期对象（OperationEvent 留痕，含 bounded 样本清单），
  实际删档/转冷存储是运营人工动作（留存是「至少保留」下限，删除另有合规
  审批；goal-r6 留注⑰）。
- 混合模式转换（§6.1 / C7）：assign 指派死亡（expired/rejected，响应窗
  24h 内无人接）→ 城市 claim 开闸（§6.4，前置=同 claim）则就地转 claim
  按 §2.3 重发；未开闸安全空转跳过（§11 降级态，人工重派路径不变）。
- 调度：cli.scheduler 主循环每轮调用 `maintenance_due()`（24h 节流，经
  BackgroundJob 天然去重）→ 到期 enqueue `dispatch.maintenance` → worker
  跑 handler（jobs/handlers 注册，模式同 research.export）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.dispatch.cities import claim_gate_status, package_client_city
from fde_api.dispatch.disputes import run_l0_reconciliation
from fde_api.dispatch.models import DeliveryPackage, DeliverySettlement, Dispute, DispatchOffer
from fde_api.dispatch.offer_service import actor_system, expire_stale_offers
from fde_api.dispatch.packages import publish_package
from fde_api.projects.events import record_event
from fde_api.workbench.models import Payment

RETENTION_MATCHING_YEARS = 3   # 撮合流水与评分留痕（§6.2 / 规则表 B11）
RETENTION_TAX_YEARS = 10       # 涉税资料（§7.4 / B11）
_MAINTENANCE_JOB_TYPE = "dispatch.maintenance"
_SAMPLE_LIMIT = 50


def retention_scan(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """超期对象盘点（只读 + 事件留痕，不删数据——留注⑰）。"""
    now = now or datetime.now(timezone.utc)
    matching_cutoff = now - timedelta(days=365 * RETENTION_MATCHING_YEARS)
    tax_cutoff = now - timedelta(days=365 * RETENTION_TAX_YEARS)

    stale_offers = session.scalars(
        select(DispatchOffer.id).where(DispatchOffer.created_at < matching_cutoff).limit(_SAMPLE_LIMIT)
    ).all()
    stale_settlements = session.scalars(
        select(DeliverySettlement.id).where(DeliverySettlement.created_at < tax_cutoff).limit(_SAMPLE_LIMIT)
    ).all()
    stale_payments = session.scalars(
        select(Payment.id).where(Payment.created_at < tax_cutoff).limit(_SAMPLE_LIMIT)
    ).all()
    resolved_disputes = session.scalars(
        select(Dispute.id).where(
            Dispute.status.in_(("resolved", "closed")),
            Dispute.resolved_at.is_not(None),
            Dispute.resolved_at < matching_cutoff,
        ).limit(_SAMPLE_LIMIT)
    ).all()

    report = {
        "matching_over_3y_sample": stale_offers,
        "tax_over_10y_settlements_sample": stale_settlements,
        "tax_over_10y_payments_sample": stale_payments,
        "disputes_past_3y_sample": resolved_disputes,
        "note": "report-only：删档/转冷存储须人工合规审批（留注⑰）",
    }
    admin = session.scalar(select_admin())
    target = session_get_any_package(session)
    if admin is not None and target is not None:
        record_event(
            session,
            admin,
            "dispatch_retention_scanned",
            target,
            report,
        )
    return report


def select_admin():
    from fde_api.auth.models import User

    from sqlalchemy import select as _select

    return _select(User).where(User.role == "admin").limit(1)


def session_get_any_package(session: Session):
    from sqlalchemy import select as _select

    from fde_api.dispatch.models import DeliveryPackage

    return session.scalar(_select(DeliveryPackage).limit(1))


def _client_city_of(session: Session, package: DeliveryPackage) -> str | None:
    """客户城归属（企业代号三段两枚「·」的第三段）——统一走 cities 公共助手
    （r12 B-④ 去重：与 claim 冷启动/开闸同口径，home_city 代理已退役）。"""
    return package_client_city(session, package)


def convert_stale_assign_to_claim(
    session: Session, *, now: datetime | None = None
) -> dict[str, Any]:
    """C7 混合模式自动转换（§6.1：先 assign 指派，响应窗内无人接 → 转 claim）。

    扫描**指派死亡**（expired=响应超时 / rejected=全拒——均属「无人接」）的
    assign 包：该城 claim 开闸（§6.4 三条件+城市开关，前置=同 claim）→
    mode 翻转 claim + publish_package 按 §2.3 重发（round+1 新 package_code
    + 新 snapshot_hash + §4.7 扩圈半径推进）；未开闸/无城市归属/前置要素
    缺失 → 安全空转跳过（§11 降级态：包保持原状，人工重派路径不变；
    跳过明细随作业结果上报，不逐条刷事件）。

    幂等：mode 翻转后不再命中扫描（天然只转一次）。24h 响应窗由上游
    expire_stale_offers 按 response_window_hours（§6.2 唯一权威表）执行——
    本函数不引入新的时间常数。单包失败不阻断整批（逐包 try，失败计 skipped）。
    """
    now = now or datetime.now(timezone.utc)
    dead = session.scalars(
        select(DeliveryPackage).where(
            DeliveryPackage.dispatch_mode == "assign",
            DeliveryPackage.dispatch_status.in_(("expired", "rejected")),
        )
    ).all()
    converted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for package in dead:
        city = _client_city_of(session, package)
        if not city:
            skipped.append(
                {"package_code": package.package_code, "reason": "city_unknown"}
            )
            continue
        gate = claim_gate_status(session, city, now=now)
        if not gate["claim_open"]:
            skipped.append(
                {
                    "package_code": package.package_code,
                    "city": city,
                    "reason": "claim_gate_closed",
                }
            )
            continue
        try:
            # SAVEPOINT：单包失败只回滚到转换前，不炸整批维护事务
            with session.begin_nested():
                actor = actor_system(session)
                package.dispatch_mode = "claim"
                publish_package(
                    session, actor=actor, package_id=package.id, candidate_user_ids=()
                )
        except Exception as error:  # noqa: BLE001 - 单包失败不阻断整批
            session.expire(package)  # 回读库内权威态，防内存残留误提交
            skipped.append(
                {
                    "package_code": package.package_code,
                    "city": city,
                    "reason": f"convert_failed:{getattr(error, 'code', type(error).__name__)}",
                }
            )
            continue
        record_event(
            session,
            actor,
            "dispatch_c7_converted",
            package,
            {
                "city": city,
                "dispatch_round": package.dispatch_round,
                "package_code": package.package_code,
                "from_status": "expired_or_rejected",
                "rule": "§6.1 混合模式：响应窗内无人接 → 转 claim",
            },
        )
        converted.append(
            {
                "package_code": package.package_code,
                "city": city,
                "dispatch_round": package.dispatch_round,
            }
        )
    return {"converted": converted, "skipped": skipped}


def run_maintenance(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """维护任务体（worker handler 调用）：超时释放 + C7 混合转换 + 留存扫描
    + T+30 对账。转换排在释放之后——同一节拍内「响应窗判死 → 开闸转 claim」。"""
    expired = expire_stale_offers(session, now=now)
    c7 = convert_stale_assign_to_claim(session, now=now)
    retention = retention_scan(session, now=now)
    reconciliation = run_l0_reconciliation(session, now=now)
    return {
        "expired_offers": expired,
        "c7_conversion": c7,
        "retention": retention,
        "t30_reconciliation": reconciliation,
    }


def maintenance_due(session: Session, *, now: datetime | None = None) -> bool:
    """24h 节流：还有 pending/queued/running 维护作业 → 不到期；最近一次成功
    完成距今 ≥24h 才再投（DB 侧 max(updated_at)，不受 ORM server_default
    回填时点影响）。"""
    from sqlalchemy import func

    from fde_api.jobs.models import BackgroundJob

    now = now or datetime.now(timezone.utc)
    running = session.scalar(
        select(BackgroundJob.id).where(
            BackgroundJob.job_type == _MAINTENANCE_JOB_TYPE,
            BackgroundJob.status.in_(("pending", "queued", "running")),
        )
    )
    if running is not None:
        return False
    last_finished_at = session.scalar(
        select(func.max(BackgroundJob.updated_at)).where(
            BackgroundJob.job_type == _MAINTENANCE_JOB_TYPE,
            # T-J2：cancelled 也是「已完结」终态——被取消的维护 job 不把
            # 24h 节拍门挂死在旧的 succeeded 时间戳上。
            BackgroundJob.status.in_(("succeeded", "failed", "cancelled")),
        )
    )
    if last_finished_at is None:
        return True
    return now - last_finished_at >= timedelta(hours=24)


def register_dispatch_maintenance_handler() -> None:
    from fde_api.jobs.handlers import register_handler

    register_handler(_MAINTENANCE_JOB_TYPE, _run_maintenance_job)


def _run_maintenance_job(job) -> None:
    """worker handler：单事务跑超时释放 + 留存扫描 + T+30 对账。"""
    from fde_api.extensions import db

    session = db.session()
    try:
        with session.begin():
            run_maintenance(session)
    finally:
        session.close()
