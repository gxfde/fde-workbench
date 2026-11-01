"""package_access 跨主体只读授权（设计 §9.1/§9.2，P0-2）。

第三语义：独立于 project_access（项目内协作）与 admin（平台全局）。
派单池只解决「谁能接/谁能看交付包」，不解决「接了之后能干什么」——
后者由 §9.3 接单交接复用 add_project_member 落回项目内鉴权。

§9.2 三条实现纪律的落点：
① dispatch 包 SQL 禁 join quotes/payments/contracts —— 序列化所需金额来自
   delivery_packages.delivery_seat_amount（发布时物化冻结），本模块零 join；
② 响应体走显式白名单 schema（serialize_package_whitelist），禁止直出 ORM 对象；
③ 路由层强制前置 require_package_access，任何 dispatch API 入口不可绕过。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.dispatch.errors import DispatchServiceError
from fde_api.dispatch.models import DeliveryPackage, PackageAccess
from fde_api.solutions.models import ProjectSolution
from fde_api.workbench.models import Project

ACCESS_ROLES = ("lead", "seller", "delivery", "audit")


def grant_package_access(
    session: Session,
    *,
    package_id: str,
    user_id: str,
    role: str,
    granted_by_user_id: str | None = None,
) -> PackageAccess:
    """授只读授权（幂等：同三元组已存在且未撤销 → 复用并清撤销标记）。"""
    if role not in ACCESS_ROLES:
        raise DispatchServiceError(
            "invalid_request", f"role 必须是 {'/'.join(ACCESS_ROLES)}。"
        )
    row = session.scalar(
        select(PackageAccess).where(
            PackageAccess.package_id == package_id,
            PackageAccess.user_id == user_id,
            PackageAccess.role == role,
        )
    )
    now = datetime.now(timezone.utc)
    if row is None:
        row = PackageAccess(
            package_id=package_id,
            user_id=user_id,
            role=role,
            granted_at=now,
            granted_by_user_id=granted_by_user_id,
        )
        session.add(row)
    else:
        # 重放已撤销授权 = 重新授予须走本函数显式操作，禁止静默复活
        row.revoked_at = None
        row.granted_at = now
    session.flush()
    return row


def revoke_package_access(
    session: Session, *, package_id: str, user_id: str, role: str
) -> int:
    """撤销授权（未撤销的行打 revoked_at；已撤销不动，返回本次撤销数）。"""
    rows = session.scalars(
        select(PackageAccess).where(
            PackageAccess.package_id == package_id,
            PackageAccess.user_id == user_id,
            PackageAccess.role == role,
            PackageAccess.revoked_at.is_(None),
        )
    ).all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.revoked_at = now
    return len(rows)


def has_package_access(
    session: Session, *, user: User, package_id: str, roles: tuple[str, ...] = ()
) -> bool:
    """判可见性：admin 平台全局语义放行；其余只认未撤销的授权行（§9.2③）。"""
    if user.role == "admin":
        return True
    statement = select(PackageAccess.id).where(
        PackageAccess.package_id == package_id,
        PackageAccess.user_id == user.id,
        PackageAccess.revoked_at.is_(None),
    )
    if roles:
        statement = statement.where(PackageAccess.role.in_(roles))
    return session.scalar(statement.limit(1)) is not None


def require_package_access(
    session: Session, *, user: User, package_id: str, roles: tuple[str, ...] = ()
) -> DeliveryPackage:
    """路由层前置守卫（§9.2 纪律③）：无授权 → 404（不泄露包存在性）。"""
    package = session.get(DeliveryPackage, package_id)
    if package is None or not has_package_access(
        session, user=user, package_id=package_id, roles=roles
    ):
        raise DispatchServiceError("package_not_found", "交付包不存在或无权访问。", 404)
    return package


def list_accessible_package_ids(session: Session, *, user: User) -> list[str]:
    """派单池列表口径：admin 全量；其余 = 未撤销授权去重。"""
    if user.role == "admin":
        return list(
            session.scalars(select(DeliveryPackage.id).order_by(DeliveryPackage.created_at))
        )
    return list(
        session.scalars(
            select(PackageAccess.package_id)
            .where(
                PackageAccess.user_id == user.id,
                PackageAccess.revoked_at.is_(None),
            )
            .distinct()
            .order_by(PackageAccess.package_id)
        )
    )


def _decimal_or_none(value: Decimal | int | None) -> float | None:
    return float(value) if value is not None else None


def serialize_package_whitelist(
    package: DeliveryPackage,
    *,
    solution: ProjectSolution,
    project: Project,
) -> dict[str, Any]:
    """§9.2 字段白名单 12 项 + 交付方席位金额（显示义务）+ 资源 id（支撑列）。

    显式 schema 直出：新增 ORM 字段**不会**自动进响应（纪律②）。
    客户标识只有代号（client_code=enterprise_code）与城市段（client_city=
    代号第三段），客户真名永不出现（红线）。金额字段只允许 delivery_seat_amount。
    id 是资源标识非内容字段（B1 接单工作台：授权方对包行动——抢单/接包——
    必须持有目标 id；不含任何业务内容，不扩白名单语义）。
    """
    segments = (project.enterprise_code or "").split("·")
    return {
        # ---- 资源标识（非内容字段；授权方行动所需） ----
        "id": package.id,
        # ---- 12 项白名单 ----
        "package_code": package.package_code,
        "scope_summary": solution.name,
        "deliverables_json": solution.deliverables,
        "acceptance_criteria": solution.acceptance_criteria,
        "data_systems": solution.data_systems,
        "schedule_text": solution.schedule,
        "risks_dependencies": solution.risks_dependencies,
        "business_category": solution.business_category,
        "client_code": project.enterprise_code,
        "client_city": segments[2] if len(segments) == 3 else None,
        "onsite_required": package.onsite_required,
        "onsite_visits": package.onsite_visits,
        "deadline": project.planned_end_date.isoformat()
        if project.planned_end_date
        else None,
        # ---- 显示义务（§7.1）：交付方席位 40% 对应金额（发布时物化冻结）----
        "delivery_seat_amount": _decimal_or_none(package.delivery_seat_amount),
        # 状态面（非敏感，派单池可见性必需）
        "dispatch_status": package.dispatch_status,
        "dispatch_round": package.dispatch_round,
        "dispatch_mode": package.dispatch_mode,
        "response_window_hours": package.response_window_hours,
        "published_at": package.published_at.isoformat()
        if package.published_at
        else None,
        # goal-d8（D2 裁决三/O-4）：协同声明态 + 订单难度三档——接单人据此
        # 知道「是否已声明协同 / 难度映射后的 run 档位」，透明化口径
        "agent_assisted": package.agent_assisted,
        "difficulty": package.difficulty,
        # goal-d9（桌面化）：接单人资源 id（声明按钮门控=本人或 admin；
        # 沿「id 是资源标识非内容字段」先例，不含业务内容）
        "accepted_user_id": package.accepted_user_id,
    }
