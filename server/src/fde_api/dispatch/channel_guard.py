"""私单封堵（设计 §8.5 P2-4 / 规则表 P2-4「禁止私下接单的技术执行」）。

派单池外成交的技术封堵，三条服务层校验钩子：

  H1 立项入口：business_line='FDE_DISPATCH' 只能由平台侧（admin/project_lead）
     立项。交付包不另立项目（accept_package 复用包上 project_id），派单线项目
     是池内成交的唯一载体。
  H2 池内企业直签封堵：企业已进过派单池（任一交付包挂在同企业项目上）后，
     再以 'FDE' 直签线为其立项/报价 → 422 private_deal_blocked。复购走池
     （§3.3 复购判据按同企业项目数计），直签即池外成交。
  H3 渠道正交：交付包只能建在 'FDE_DISPATCH' 项目上。直签项目不得入池
     （不得借池洗渠道），派单项目天然承载池内成交。

封堵是绝对的技术动作，不留运行时开关；若业务要给池内客户开直签，属设计
变更拍板项（轮次报告留注），不是配置项。封堵发生时写 OperationEvent 留痕
（target=actor/project）；留痕走独立事务——被封堵的主事务必然回滚，留痕
必须独立存活。留痕失败只降级（不阻断封堵本身）。

**G4 附加判定（商业化 ADR-009 §2.4）**：商机报备保护期内，该企业**直签
立项**亦被封堵（``opportunity_protection_active``，422）。该判定**惰性**
（无商机即 no-op，既有三条钩子语义不变）且**失败放行**（查询异常不阻断
立项）——保护是渠道秩序诉求，不是资金安全闸。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.dispatch.models import DeliveryPackage
from fde_api.extensions import db
from fde_api.workbench.models import Project

DISPATCH_LINE = "FDE_DISPATCH"
DIRECT_LINE = "FDE"
BUSINESS_LINES = (DIRECT_LINE, DISPATCH_LINE)
PLATFORM_ROLES = ("admin", "project_lead")


class ChannelGuardError(Exception):
    """封堵钩子错误；调用方（project/quote/package 服务）转译为各自错误类型。"""

    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def normalize_business_line(value: Any) -> str:
    """立项输入的 business_line 归一：缺省直签线，越界即非法请求。"""
    line = value if isinstance(value, str) and value else DIRECT_LINE
    if line not in BUSINESS_LINES:
        raise ChannelGuardError(
            "invalid_business_line",
            "business_line 必须是 FDE/FDE_DISPATCH。",
            400,
        )
    return line


def enterprise_in_pool(session: Session, enterprise_code: str) -> bool:
    """该企业是否已进过派单池（任一交付包挂在同企业项目上，不限包状态）。"""
    if not enterprise_code:
        return False
    row = session.scalar(
        select(Project.id)
        .join(DeliveryPackage, DeliveryPackage.project_id == Project.id)
        .where(Project.enterprise_code == enterprise_code)
        .limit(1)
    )
    return row is not None


def _audit_block(
    actor_id: str,
    *,
    event_type: str,
    target: User | Project | None,
    payload: dict[str, Any],
) -> None:
    """封堵留痕（独立事务）：主事务回滚后留痕仍存活；失败只降级。

    record_event 延迟导入——fde_api.projects.__init__ 会急切拉起
    routes/service，而 service 又反向依赖本模块（避免环）。"""
    from fde_api.projects.events import record_event  # noqa: PLC0415

    audit = db.session()
    try:
        with audit.begin():
            fresh_actor = audit.get(User, actor_id)
            if fresh_actor is None:
                return
            audit_target: User | Project = fresh_actor
            if isinstance(target, Project):
                fresh_project = audit.get(Project, target.id)
                if fresh_project is not None:
                    audit_target = fresh_project
            record_event(audit, fresh_actor, event_type, audit_target, payload)
    except Exception:  # noqa: BLE001 - 留痕失败不阻断封堵（轮次报告留注）
        audit.rollback()
    finally:
        audit.close()


def ensure_dispatch_entry(actor: User) -> None:
    """H1 立项入口：派单线项目只能平台侧立项（fde_engineer/viewer → 403）。"""
    if actor.role in PLATFORM_ROLES:
        return
    _audit_block(
        actor.id,
        event_type="dispatch_project_entry_blocked",
        target=None,
        payload={"business_line": DISPATCH_LINE, "actor_role": actor.role},
    )
    raise ChannelGuardError(
        "dispatch_project_platform_only",
        "派单线（FDE_DISPATCH）项目只能由平台侧（admin/project_lead）立项。",
        403,
    )


def _opportunity_protection_guard(
    session: Session, enterprise_code: str
) -> ChannelGuardError | None:
    """G4 商机保护期附加判定（商业化 ADR-009 §2.4）。

    报备保护期内，该企业的**直签立项**被封堵（提示走归属渠道）——这是商机保护
    的商业含义落点；**派单线放行**。

    - **惰性**：无商机即 no-op——既有三条钩子语义不变（无商机时行为逐位相同）；
    - **失败放行**：查询异常不阻断立项（保护是**渠道秩序**诉求，不是资金安全
      闸，不得因查询故障挡住客户立项）；
    - **只认「存储态 active 且未到期」**：未配置（unconfigured）与已到期
      （expired）都**不封堵**——「未配置」不是永久保护，过期即放行。
    """
    if not enterprise_code:
        return None
    try:
        from fde_api.commercial.attribution_service import (  # noqa: PLC0415
            active_protection_for_enterprise,
        )

        row = active_protection_for_enterprise(session, enterprise_code)
    except Exception:  # noqa: BLE001 - 失败放行（docstring 已述取舍）
        return None
    if row is None:
        return None
    expires = row.protection_expires_at.isoformat() if row.protection_expires_at else ""
    return ChannelGuardError(
        "opportunity_protection_active",
        "该企业的商机处于报备保护期内（至 {}）：直签立项已封堵，"
        "请走归属渠道或等待保护期结束。".format(expires),
        422,
    )


def ensure_enterprise_channel(
    session: Session,
    *,
    actor: User,
    business_line: str,
    enterprise_code: str,
) -> None:
    """H2 池内企业直签封堵：直签线 × 池内企业 → 422（复购走池）。

    派单线放行——同企业复购走池正是判据口径（§3.3）。

    另附 G4 商机保护期判定（报备保护期内直签封堵，ADR-009 §2.4）——该判定
    **先于**池内判定：它在**成交前**的报备窗口生效，池内判定在成交后生效，
    两者互补不重叠。
    """
    if business_line != DIRECT_LINE:
        return
    protection = _opportunity_protection_guard(session, enterprise_code)
    if protection is not None:
        _audit_block(
            actor.id,
            event_type="opportunity_protection_blocked",
            target=None,
            payload={
                "business_line": business_line,
                "enterprise_code": enterprise_code,
                "hook": "G4_opportunity_protection",
            },
        )
        raise protection
    if not enterprise_in_pool(session, enterprise_code):
        return
    _audit_block(
        actor.id,
        event_type="private_deal_blocked",
        target=None,
        payload={
            "business_line": business_line,
            "enterprise_code": enterprise_code,
            "hook": "H2_enterprise_channel",
        },
    )
    raise ChannelGuardError(
        "private_deal_blocked",
        "该企业已进派单池：直签封堵生效，成交须走派单池（新建 FDE_DISPATCH 项目入池）。",
        422,
    )


def ensure_package_channel(project: Project) -> None:
    """H3 渠道正交：交付包只能建在派单线项目上（直签项目不得入池）。"""
    if project.business_line == DISPATCH_LINE:
        return
    raise ChannelGuardError(
        "dispatch_line_required",
        "只有派单线（FDE_DISPATCH）项目可建交付包；直签项目不得入池。",
        422,
    )
