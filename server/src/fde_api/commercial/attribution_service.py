"""商业化 G4 服务层：商机归属与渠道保护（任务书 §8；ADR-009）。

七步链路（成文规则 §2）：

    ①报备 → ②企业确认 → ③平台确认归属 → ④设定保护期 → ⑤售前与客户关系
    → ⑥平台撮合交付者 → ⑦按既定分成规则结算

语义钉（实施不得越界）：

- **规则数值本期不定数**：五个规则位（保护期长度／续期条件／客户自主选择权／
  争议处理机制／归属判定）缺省 ``unset``；未配置的相关动作一律 fail-closed
  （409 ``rule_not_configured``），**不回落到任何硬编码默认值**。
- **保护期三态可区分**（``unconfigured`` / ``active`` / ``expired``）：未配置
  **既不是**「永久保护」也**不是**「立即失效」；``active`` 必有到期时刻——
  **结构上不可能出现永久锁定企业**（任务书 §8）。
- **归属不因企业自行注册而转移**：归属与保护期是本域事实，企业侧立项路径**没有
  任何写路径**可触碰商机行（结构性保证＋反例用例）。
- **复用优先**：第 ⑥ 步引用既有 ``delivery_packages``（不建第二套撮合），第 ⑦ 步
  引用 G3 科目层的 ``project_share`` 行（不建第二套结算）。
- **高风险写默认人工确认**（ADR-007 §2.1）：②③④⑤⑥⑦及规则配置＝admin 门＋密码
  确认双闸，逐动作 ``operation_events`` 留痕（带 request_id，**密码不落事件**）；
  ①报备与撤回是**当事人自证动作**（认证用户＋事件留痕）。
- **只登企业代号**：真实企业名/联系人/凭证一律不入库；线索、答复、判据、争议
  材料**只存指针 + sha256 指纹**（AGENTS 红线）。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.auth.models import ROLE_ADMIN, User
from fde_api.auth.confirm_throttle import confirm_attempts_blocked, record_confirm_failure
from fde_api.auth.passwords import verify_password
from fde_api.commercial.models import (
    OPPORTUNITY_PROTECTION_STATUSES,
    OPPORTUNITY_RULE_KEYS,
    OPPORTUNITY_RULE_STATUSES,
    OPPORTUNITY_RULE_VALUE_KINDS,
    OPPORTUNITY_STATUSES,
    CommercialEntitlement,
    CommercialOpportunity,
    CommercialOpportunityRule,
    CommercialRevenueLedger,
    RegionalPartner,
)
from fde_api.commercial.org_read_scope import visible_user_ids_query
from fde_api.commercial.service import CommercialServiceError
from fde_api.dispatch.models import DeliveryPackage
from fde_api.projects.events import record_event
from fde_api.workbench.models import Project

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _error(code: str, message: str, status: int = 400) -> CommercialServiceError:
    return CommercialServiceError(code, message, status)


def _require_admin(actor: User) -> None:
    if actor.role != ROLE_ADMIN:
        raise _error("commercial_admin_required", "商机归属治理仅系统运维员可用。", 403)


def _confirm_password(session: Session, actor: User, password: object) -> None:
    """单次显式授权：admin 写原语须携带当前账号密码（高风险写人工确认）。"""
    if not isinstance(password, str) or not password:
        raise _error("invalid_request", "confirm_password 必填（高风险写人工确认）。")
    # CR-047：密码确认尝试限流——与 auth verify-password / ai 确认闸同 key 同阈值同窗口。
    if confirm_attempts_blocked(actor.id):
        raise _error("too_many_attempts", "密码错误次数过多，请 15 分钟后重试。", 429)
    current = session.get(User, actor.id)
    if current is None or not verify_password(current.password_hash, password):
        record_confirm_failure(actor.id)
        raise _error("invalid_password", "当前账号密码不正确。", 403)


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.match(value.strip().lower()):
        raise _error("invalid_request", f"{field} 必须是 64 位 sha256 十六进制指纹。")
    return value.strip().lower()


def _require_uri(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 500:
        raise _error("invalid_request", f"{field} 必须是 ≤500 字符指针字符串。")
    return value.strip()


def _optional_uri(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 500:
        raise _error("invalid_request", f"{field} 必须是 ≤500 字符指针字符串或 null。")
    return value.strip()


def _require_user(session: Session, user_id: object, field: str = "user_id") -> User:
    if not isinstance(user_id, str) or not user_id:
        raise _error("invalid_request", f"{field} 必填。")
    user = session.get(User, user_id)
    if user is None:
        raise _error("user_not_found", "用户不存在。", 404)
    return user


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ══════════════════════════════════════════════════════════════════════════
# 规则位（成文规则 ↔ 代码配置位一一对应；本期全部 unset）
# ══════════════════════════════════════════════════════════════════════════


def ensure_rule(session: Session, key: str) -> CommercialOpportunityRule:
    """确保规则位存在（**缺省 unset**）——槽位是结构，缺失即补建。

    补建出来的行恒为 ``unset``，**不落任何业务数值**（规则数值本期不定数）。
    """
    value_kind = OPPORTUNITY_RULE_VALUE_KINDS.get(key)
    if value_kind is None:
        raise _error("rule_slot_not_found", f"规则位 {key} 不存在。", 404)
    row = session.get(CommercialOpportunityRule, key)
    if row is None:
        row = CommercialOpportunityRule(
            key=key, value_kind=value_kind, status="unset"
        )
        session.add(row)
        session.flush()
    return row


def list_rules(session: Session) -> list[CommercialOpportunityRule]:
    for key in OPPORTUNITY_RULE_KEYS:
        ensure_rule(session, key)
    return list(
        session.scalars(
            select(CommercialOpportunityRule).order_by(CommercialOpportunityRule.key)
        )
    )


def rule_status_snapshot(session: Session) -> dict[str, str]:
    """规则位状态快照（各键 → unset/configured）——随规则相关流转留痕。"""
    snapshot: dict[str, str] = {}
    for key in OPPORTUNITY_RULE_KEYS:
        row = session.get(CommercialOpportunityRule, key)
        snapshot[key] = row.status if row is not None else "unset"
    return snapshot


def require_rule_configured(session: Session, key: str) -> CommercialOpportunityRule:
    """规则位未配置 ⇒ 相关动作 fail-closed（409 ``rule_not_configured``）。

    **不回落到默认值**——数值未定数时「少做」比「猜着做」安全。
    """
    row = ensure_rule(session, key)
    if row.status != "configured":
        raise _error(
            "rule_not_configured",
            f"规则位 {key} 尚未成文配置，本期不可据此执行（规则数值待拍板）。",
            409,
        )
    return row


def configure_rule(
    session: Session,
    *,
    actor: User,
    key: object,
    value: object = None,
    source_uri: object = None,
    content_hash: object = None,
    confirm_password: object,
) -> dict[str, Any]:
    """配置/清空规则位（admin + 密码确认；书面依据指针 + sha256 指纹）。

    ``value=None`` ⇒ 退回 ``unset``（数值待定态）——**清空同样要留依据**。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    if not isinstance(key, str) or key not in OPPORTUNITY_RULE_KEYS:
        raise _error("invalid_rule_slot", f"key 必须是 {'/'.join(OPPORTUNITY_RULE_KEYS)} 之一。")
    row = ensure_rule(session, key)
    uri = _require_uri(source_uri, "source_uri")
    digest = _require_sha256(content_hash, "content_hash")

    if value is None:
        row.status = "unset"
        row.days = None
        row.criteria = None
    elif row.value_kind == "days":
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise _error("invalid_rule_value", "保护期长度必须是正整数天数。")
        row.days = int(value)
        row.criteria = None
        row.status = "configured"
    else:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 500:
            raise _error("invalid_rule_value", "规则正文必须是 ≤500 字符非空字符串。")
        row.criteria = value.strip()
        row.days = None
        row.status = "configured"
    row.source_uri = uri
    row.content_hash = digest
    row.configured_by_user_id = actor.id
    row.configured_at = _now()
    session.flush()
    record_event(
        session,
        actor,
        "commercial_opportunity_rule_changed",
        actor,
        {
            "request_id": str(uuid4()),
            "key": key,
            "status": row.status,
            "value_kind": row.value_kind,
        },
    )
    return {"rule": serialize_rule(row), "changed": True}


def serialize_rule(row: CommercialOpportunityRule) -> dict[str, Any]:
    return {
        "key": row.key,
        "value_kind": row.value_kind,
        "status": row.status,
        "configured": row.status == "configured",
        "days": row.days,
        "criteria": row.criteria,
        "source_uri": row.source_uri,
        "content_hash": row.content_hash,
        "configured_by_user_id": row.configured_by_user_id,
        "configured_at": row.configured_at.isoformat() if row.configured_at else None,
    }


# ══════════════════════════════════════════════════════════════════════════
# 商机主体：加载 / 读面 / 保护期派生
# ══════════════════════════════════════════════════════════════════════════


def _load(session: Session, opportunity_id: object) -> CommercialOpportunity:
    if not isinstance(opportunity_id, str) or not opportunity_id:
        raise _error("invalid_request", "opportunity_id 必填。")
    row = session.get(CommercialOpportunity, opportunity_id)
    if row is None:
        raise _error("opportunity_not_found", "商机不存在。", 404)
    return row


def protection_effective_status(row: CommercialOpportunity, now: datetime | None = None) -> str:
    """保护期**派生态**：存储态为 active 但已过到期时刻 ⇒ 派生为 expired。

    「到期即失效」是**读时派生**（不在读路径写库）：到期后直签立即恢复放行，
    保护期**不得变成永久锁定企业**。
    """
    moment = now or _now()
    if row.protection_status != "active":
        return row.protection_status
    if row.protection_expires_at is not None and row.protection_expires_at <= moment:
        return "expired"
    return "active"


def active_protection_for_enterprise(
    session: Session, enterprise_code: str, now: datetime | None = None
) -> CommercialOpportunity | None:
    """该企业是否存在**生效中**的保护期商机（直签封堵钩子用）。

    只认「存储态 active 且未到期」——未配置（unconfigured）与已到期（expired）
    都**不封堵**（未配置不是永久保护，过期即放行）。
    """
    if not enterprise_code:
        return None
    moment = now or _now()
    rows = session.scalars(
        select(CommercialOpportunity).where(
            CommercialOpportunity.enterprise_code == enterprise_code,
            CommercialOpportunity.protection_status == "active",
        )
    ).all()
    for row in rows:
        if protection_effective_status(row, moment) == "active":
            return row
    return None


def _enterprise_project_count(session: Session, enterprise_code: str) -> int:
    """该企业代号下的项目数（派生事实：企业是否已自助注册）。

    用于让「企业自行注册不自动易主」的反例**非空洞**——读面能看见企业后来
    注册了，但归属逐项未动。
    """
    if not enterprise_code:
        return 0
    return int(
        session.scalar(
            select(Project.id).where(Project.enterprise_code == enterprise_code).limit(1)
        )
        is not None
    )


# ══════════════════════════════════════════════════════════════════════════
# M7：商机数据归属权与导出权硬约束（ADR-M7）
#
# 语义（任务书 §7 M7；sec 评审硬条件「归属权与导出权须在 M7 写死」）：
#
#   **平台托管** → **企业确认前区域服务商不可导出客户名单** → **双方按授权可见**
#
# 实现口径（**零新表、零新列、零新路由**——裁决 1：主体归属走 ``user.org_id``
# 间接归属，不新增 org_id 列、不新增迁移、不改表结构）：
#
# - 「客户识别字段」＝**企业代号**与**企业是否已注册**派生事实——本域唯一
#   客户名单可枚举面（见 ``OPPORTUNITY_CUSTOMER_IDENTITY_FIELDS``）；
# - 「托管方」＝**平台 admin**（平台侧，全量可见，本轮不变——与 M3b
#   「admin 跨 org 代操作留痕不阻断」一致）；
# - 「区域服务商」＝任一 ``regional_partners`` 行的申请账号（G5 外部角色；
#   四阶段皆属外部伙伴；区域代理本期无进入路径）——经既有 ``applicant_user_id``
#   列判定，**不新增任何授权表**；
# - 「企业确认」＝既有 ``commercial_opportunities.enterprise_confirmed_at`` 列
#   （第②步平台代录企业书面答复时落值）——**企业确认前企业代号只是未经核验的
#   报备声明**，属平台托管事实。
# ══════════════════════════════════════════════════════════════════════════

# 客户识别字段集合（本域「客户名单」的唯一可枚举面定义）
OPPORTUNITY_CUSTOMER_IDENTITY_FIELDS = ("enterprise_code", "enterprise_registered")


def is_opportunity_custodian(actor: User) -> bool:
    """托管方判定——**平台 admin** 是商机数据的托管方（ADR-M7 §2）。

    托管方全量可见（**含未企业确认商机**）：admin 是平台方，本轮口径不变。
    本判定**只看 role 不看 org_id**——存量平台身份账号（``org_id IS NULL``）
    不因此获得客户名单能力（客户名单能力属外部角色专属的受限面）。
    """
    return actor.role == ROLE_ADMIN


def is_regional_partner(session: Session, actor: User) -> bool:
    """区域服务商身份判定（G5 外部角色；**零新表**——既有 ``regional_partners``）。

    「区域服务商」＝任一 ``regional_partners`` 行的申请账号
    （``applicant_user_id``）——四阶段（``city_observer``／``city_service``／
    ``formal_partner``）皆属外部伙伴；``regional_agent`` 本期无进入路径
    （服务层显式拒绝），对本判定无影响。

    区域伙伴的组织归属经 ``applicant_user_id`` → ``users.org_id`` 推导
    （OWNER 2026-11-12 拍板：**不新增 org_id 列**）。
    """
    if is_opportunity_custodian(actor):
        return False
    return (
        session.scalar(
            select(RegionalPartner.id)
            .where(RegionalPartner.applicant_user_id == actor.id)
            .limit(1)
        )
        is not None
    )


def customer_identity_visible(
    row: CommercialOpportunity,
    *,
    actor: User,
    external_partner: bool,
    enforce_ownership: bool = True,
) -> bool:
    """客户识别字段对该 actor 是否可见（**授权模型**；零新表零新列零新路由）。

    判定式（ADR-M7 §2）：

    1. **托管方**（admin）⇒ 恒可见（平台托管方全量可见，本轮不变）；
    2. **写面回显**（``enforce_ownership=False``）⇒ 可见——回显是**自证回执**
       （本人刚提交的报备／刚确认的流转），遮蔽它不产生任何信息安全收益；
    3. **非区域服务商身份** ⇒ 既有可见性语义**逐位不变**（本轮硬约束的作用
       对象是**外部角色**，不越界改写既有读面口径——与 M6 的 org 隔离接线
       分工正交）；
    4. **区域服务商**（外部角色）⇒ 客户识别字段**以企业确认为闸**：
       - 已企业确认 ⇒ 可见（**双方按授权可见**）；
       - 企业确认前 ⇒ **不可见**（平台托管的客户识别事实不得外发给区域
         服务商——**含其本人刚报备的行**：企业代号此时是**未经核验的报备
         声明**，客户名单的主体是平台而非报备人）。

    **范围声明**：本轮硬约束的作用对象＝**区域服务商这一外部角色**
    （任务书 §7 M7 明文）——非区域服务商账号的账号级客户名单遮蔽属可能的
    扩展，须 OWNER 裁决后再落，本轮不越界改写既有语义。
    """
    if is_opportunity_custodian(actor):
        return True
    if not enforce_ownership:
        return True
    if not external_partner:
        return True
    return row.enterprise_confirmed_at is not None


def require_enterprise_confirmed_for_customer_list(
    session: Session,
    *,
    actor: User,
    enterprise_code: str,
    scoped_ids: set[str],
) -> None:
    """**企业确认前的客户名单保护闸**（fail-closed；ADR-M7 §3）。

    语义：企业确认前，企业代号是**未经平台核验的报备声明**——属平台托管的
    客户识别事实；**区域服务商**不得据此**枚举**客户名单。

    不通过 ⇒ 403 ``opportunity_customer_list_not_confirmed``。

    **为什么是 403 而不是 409**：这是**读面授权**判定，不是状态机冲突——
    409（``rule_not_configured`` 那种）会让调用方误读为「稍后重试即可」；
    403 与既有读面越权码（``opportunity_forbidden``）同族，语义是「该身份
    此刻无权取得该客户识别数据」。409 留给**状态机**冲突（链路步序、
    规则位未配置等）。

    **判定口径（精确到「是否会泄信息」）**：只有当该 ``enterprise_code``
    **在平台全域存在未企业确认的行、且该行不在 actor 的可见域内**时，
    探针才会泄露新信息（「这个企业代号在平台存在」）。故：

    - 命中行全在 actor 可见域内 ⇒ 放行（actor 本就能看见，无新信息）；
    - 命中行全已企业确认 ⇒ 放行（已确认的客户识别事实属「双方按授权可见」）；
    - 存在「域外 ＋ 未企业确认」的行 ⇒ 403（**存在性旁路**被关闭）。
    """
    if is_opportunity_custodian(actor):
        return
    if not is_regional_partner(session, actor):
        return
    leaking = list(
        session.scalars(
            select(CommercialOpportunity.id).where(
                CommercialOpportunity.enterprise_code == enterprise_code,
                CommercialOpportunity.enterprise_confirmed_at.is_(None),
            )
        )
    )
    if not leaking:
        return
    if all(row_id in scoped_ids for row_id in leaking):
        # 命中行全在 actor 可见域内 ⇒ 无新信息泄露
        return
    raise _error(
        "opportunity_customer_list_not_confirmed",
        "企业确认前，客户识别数据由平台托管：区域服务商不得取得客户名单"
        "（企业确认后双方按授权可见）。",
        403,
    )


def _opportunity_scope_filter(actor: User):
    """列表可见域谓词（**M6 org 隔离 × M7 客户名单硬约束的单一权威**）。

    - **平台身份／admin** ⇒ ``None`` 分支：既有语义**逐位不变**（只见本人
      报备/归属/售前三列）——M1 拍板「存量用户不回填」⇒ 存量回归面零变化；
    - **企业身份** ⇒ 可见集合收敛为「本 org（＋平台内部桶）成员」的商机
      （M5 已落模式；行归属经 ``reported_by_user_id``／
      ``attribution_owner_user_id``／``presales_owner_user_id`` →
      ``users.org_id`` 推导，**零迁移零新列**）；别家企业商机不外泄。

    ★ ``list_opportunities`` 的列表语句与枚举闸基准 ``scoped_ids`` **共用本
    谓词** ⇒ M7 的 ``require_enterprise_confirmed_for_customer_list`` 判定
    基准自动跟随 M6 的 org 可见域，两层约束不各说各话。判定权威仍是既有
    ``fde_api.orgs.isolation``（经 ``org_read_scope.visible_user_ids_query``）。
    """
    visible_ids = visible_user_ids_query(actor)
    if visible_ids is None:
        return (
            (CommercialOpportunity.reported_by_user_id == actor.id)
            | (CommercialOpportunity.attribution_owner_user_id == actor.id)
            | (CommercialOpportunity.presales_owner_user_id == actor.id)
        )
    return (
        CommercialOpportunity.reported_by_user_id.in_(visible_ids)
        | CommercialOpportunity.attribution_owner_user_id.in_(visible_ids)
        | CommercialOpportunity.presales_owner_user_id.in_(visible_ids)
    )


def serialize_opportunity(
    session: Session,
    row: CommercialOpportunity,
    *,
    actor: User,
    external_partner: bool | None = None,
    enforce_ownership: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """商机序列化（**按授权裁剪客户识别字段**；ADR-M7 §2）。

    裁剪规则：``customer_identity_visible`` 为假 ⇒ ``enterprise_code`` 与
    ``enterprise_registered`` 输出 ``None``（**遮蔽**，不是删除——字段形状
    稳定，前端与测试可据 ``customer_identity_visible`` 判别），并置
    ``customer_identity_visible=False`` 显式透出判定结果。

    ``enforce_ownership=False`` 用于**写面回显**（自证回执：本人刚提交／
    刚确认的流转）——回显不适用导出权硬约束（见 ``customer_identity_visible``
    判定式第 2 条）。
    """
    moment = now or _now()
    if external_partner is None:
        external_partner = is_regional_partner(session, actor)
    visible = customer_identity_visible(
        row,
        actor=actor,
        external_partner=external_partner,
        enforce_ownership=enforce_ownership,
    )
    effective = protection_effective_status(row, moment)
    days_remaining = None
    if effective == "active" and row.protection_expires_at is not None:
        # **向上取整**——配了 30 天，读面就显示「还剩 30 天」（不是 29）：
        # 剩余不足一天仍算一天（用户口径：今天还在保护期内）。
        remaining = (row.protection_expires_at - moment).total_seconds()
        days_remaining = max(0, int(-(-remaining // 86400)))
    return {
        "id": row.id,
        "enterprise_code": row.enterprise_code if visible else None,
        "title": row.title,
        "note": row.note,
        "status": row.status,
        "reported_by_user_id": row.reported_by_user_id,
        "reported_at": row.reported_at.isoformat() if row.reported_at else None,
        "source_uri": row.source_uri,
        "content_hash": row.content_hash,
        "enterprise_confirmation": {
            "confirmed_at": (
                row.enterprise_confirmed_at.isoformat()
                if row.enterprise_confirmed_at
                else None
            ),
            "confirmed_by_user_id": row.enterprise_confirmed_by_user_id,
            "source_uri": row.enterprise_confirmation_uri,
            "content_hash": row.enterprise_confirmation_hash,
        },
        "attribution": {
            "owner_user_id": row.attribution_owner_user_id,
            "confirmed_at": (
                row.attribution_confirmed_at.isoformat()
                if row.attribution_confirmed_at
                else None
            ),
            "confirmed_by_user_id": row.attribution_confirmed_by_user_id,
            "source_uri": row.attribution_uri,
            "content_hash": row.attribution_hash,
        },
        "protection": {
            "status": row.protection_status,
            "effective_status": effective,
            "started_at": (
                row.protection_started_at.isoformat()
                if row.protection_started_at
                else None
            ),
            "expires_at": (
                row.protection_expires_at.isoformat()
                if row.protection_expires_at
                else None
            ),
            "renewal_count": row.protection_renewal_count,
            "renewed_at": (
                row.protection_renewed_at.isoformat()
                if row.protection_renewed_at
                else None
            ),
            "days_remaining": days_remaining,
        },
        "presales_owner_user_id": row.presales_owner_user_id,
        "matched_delivery_package_id": row.matched_delivery_package_id,
        "customer_choice_package_id": row.customer_choice_package_id,
        "settled_ledger_entry_id": row.settled_ledger_entry_id,
        "rule_snapshot": row.rule_snapshot,
        "withdrawn_at": row.withdrawn_at.isoformat() if row.withdrawn_at else None,
        "disputed_at": row.disputed_at.isoformat() if row.disputed_at else None,
        # 派生事实：企业是否已自助注册（**注册不改变归属**——结构性保证的可见证据）
        "enterprise_registered": (
            _enterprise_project_count(session, row.enterprise_code) > 0
            if visible
            else None
        ),
        # M7：客户识别字段对该读者的可见性判定结果（显式透出，避免「静默遮蔽」）
        "customer_identity_visible": visible,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_opportunities(
    session: Session,
    *,
    actor: User,
    status: object = None,
    enterprise_code: object = None,
) -> dict[str, Any]:
    """商机列表（admin 全量；非 admin 只见自己报备或归属的）。

    **M7 客户名单硬约束**（ADR-M7 §3）：本读面**本身就是客户名单导出面**
    （admin 全量含企业代号＋「企业是否已注册」派生事实，且支持
    ``?enterprise_code=`` 枚举）——故硬约束**落在本函数与序列化层**，
    不是另开一个 export 端点：

    - **按企业代号枚举**（``?enterprise_code=``）＝客户名单导出尝试⇒对
      **区域服务商**且**命中的商机尚未企业确认** ⇒ 403
      ``opportunity_customer_list_not_confirmed``（fail-closed）；
    - 列表内每行按 ``customer_identity_visible`` **遮蔽**客户识别字段
      （企业确认前对区域服务商遮蔽）。

    **M6 org 隔离接线**（落点在 ``_opportunity_scope_filter``）：企业身份下
    可见集合收敛为「本 org（＋平台内部桶）成员报备/归属/售前的商机」——本企业
    成员互相可见，**别家企业商机不外泄**（行归属经三个用户 FK →
    ``users.org_id`` 推导，零迁移零新列）。列表语句与 ``scoped_ids`` 共用同一
    谓词 ⇒ 枚举闸基准自动跟随 org 可见域，两层约束不各说各话。
    """
    # **可见域谓词**（可见域语义单一权威）——M6 的 org 维度接线落点即此
    # 谓词（见 ``_opportunity_scope_filter`` docstring）。
    scope_filter = (
        None if actor.role == ROLE_ADMIN else _opportunity_scope_filter(actor)
    )
    statement = select(CommercialOpportunity)
    if scope_filter is not None:
        statement = statement.where(scope_filter)
    # **可见域 id 集合**（枚举闸用）——只含**可见域谓词**（不含 status 过滤、
    # 不含 enterprise_code 过滤）：它回答「actor 本来能看见哪些行」，是
    # 枚举探针是否泄露新信息的唯一判据基准。
    scoped_ids = set(
        session.scalars(
            select(CommercialOpportunity.id).where(scope_filter)
            if scope_filter is not None
            else select(CommercialOpportunity.id)
        )
    )
    if status is not None:
        if status not in OPPORTUNITY_STATUSES:
            raise _error("invalid_status", f"status 必须是 {'/'.join(OPPORTUNITY_STATUSES)} 之一。")
        statement = statement.where(CommercialOpportunity.status == status)
    if enterprise_code is not None:
        if not isinstance(enterprise_code, str) or not enterprise_code.strip():
            raise _error("invalid_request", "enterprise_code 必须是 ≤80 字符非空字符串。")
        statement = statement.where(
            CommercialOpportunity.enterprise_code == enterprise_code.strip()
        )
    rows = list(
        session.scalars(
            statement.order_by(
                CommercialOpportunity.created_at.desc(), CommercialOpportunity.id
            )
        )
    )
    external_partner = is_regional_partner(session, actor)
    if enterprise_code is not None:
        # 枚举闸：按客户代号取数＝客户名单导出尝试（存在性旁路被关闭）
        require_enterprise_confirmed_for_customer_list(
            session,
            actor=actor,
            enterprise_code=enterprise_code.strip(),
            scoped_ids=scoped_ids,
        )
    return {
        "opportunities": [
            serialize_opportunity(
                session, row, actor=actor, external_partner=external_partner
            )
            for row in rows
        ],
        "count": len(rows),
        "scope": "platform" if actor.role == ROLE_ADMIN else "self",
    }


def get_opportunity(
    session: Session, *, actor: User, opportunity_id: str
) -> dict[str, Any]:
    """商机详情（**按授权裁剪客户识别字段**；ADR-M7 §2）。"""
    row = _load(session, opportunity_id)
    if actor.role != ROLE_ADMIN and actor.id not in (
        row.reported_by_user_id,
        row.attribution_owner_user_id,
        row.presales_owner_user_id,
    ):
        raise _error("opportunity_forbidden", "只能查看本人相关商机。", 403)
    return {
        "opportunity": serialize_opportunity(session, row, actor=actor),
    }


def _require_sourcer_seat(session: Session, actor: User) -> None:
    """拉单资格闸（**关键流转口径变更**：ADR-011 §5-F 补充拍板 12）。

    原 G4 闸＝「角色分层必须 R2 创业者」；ADR-011 v1.3 §5-F（2026-11-10
    15:30 拍板，OWNER 书面签字页 A-7 行随 PR #302 入库）改为**缴 3980 席位
    订阅费即可、资格不限角色**。两条独立路径任一成立即放行（对应规则文件
    「存在有效席位费科目行／席位 active」）：

    - ① ``commercial_entitlements``：``seat_status='active'`` 且未过期
      （``seat_expires_at`` 为 NULL 视为未设到期，不算过期）；
    - ② G3 科目层：存在本人义务人的 ``seat_fee`` 有效行
      （``status IN ('recorded','reconciled')``，voided 不算）。

    都不成立 ⇒ 403 ``opportunity_reporter_seat_required``（fail-closed，
    不得静默放宽）。
    """
    entitlement = session.get(CommercialEntitlement, actor.id)
    if (
        entitlement is not None
        and entitlement.seat_status == "active"
        and (
            entitlement.seat_expires_at is None
            or entitlement.seat_expires_at >= datetime.now(timezone.utc)
        )
    ):
        return
    ledger_row = session.scalar(
        select(CommercialRevenueLedger.id).where(
            CommercialRevenueLedger.subject_type == "seat_fee",
            CommercialRevenueLedger.subject_user_id == actor.id,
            CommercialRevenueLedger.status.in_(("recorded", "reconciled")),
        )
    )
    if ledger_row is not None:
        return
    raise _error(
        "opportunity_reporter_seat_required",
        "报备企业线索须缴 3980 席位订阅费（席位 active 或科目层存在有效 seat_fee "
        "行）；拉单资格不限角色（ADR-011 §5-F）。",
        403,
    )


# ══════════════════════════════════════════════════════════════════════════
# 七步链路写原语
# ══════════════════════════════════════════════════════════════════════════


def submit_opportunity(
    session: Session,
    *,
    actor: User,
    enterprise_code: object,
    title: object,
    note: object = None,
    source_uri: object,
    content_hash: object,
) -> dict[str, Any]:
    """① 报备（**当事人自证动作**：提交自己的企业线索）。

    拉单资格**不限角色**，缴 3980 席位订阅费即可（ADR-011 §5-F 补充拍板 12，
    2026-11-10 15:30 拍板；书面依据＝ADR-011 v1.3 §5-F＋书面签字页 A-7 行——
    角色闸替换是关键流转口径变更，见 ``_require_sourcer_seat``）。证据只存
    指针 + sha256 指纹。
    """
    _require_sourcer_seat(session, actor)
    if not isinstance(enterprise_code, str) or not enterprise_code.strip():
        raise _error("invalid_request", "enterprise_code 必填（企业代号，非真实企业名）。")
    if len(enterprise_code.strip()) > 80:
        raise _error("invalid_request", "enterprise_code 必须是 ≤80 字符字符串。")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 160:
        raise _error("invalid_request", "title 必须是 ≤160 字符非空字符串。")
    if note is not None and (not isinstance(note, str) or len(note) > 500):
        raise _error("invalid_request", "note 必须是 ≤500 字符字符串或 null。")
    uri = _require_uri(source_uri, "source_uri")
    digest = _require_sha256(content_hash, "content_hash")

    row = CommercialOpportunity(
        enterprise_code=enterprise_code.strip(),
        title=title.strip(),
        note=note.strip() if isinstance(note, str) else None,
        status="submitted",
        reported_by_user_id=actor.id,
        reported_at=_now(),
        source_uri=uri,
        content_hash=digest,
        protection_status="unconfigured",
        protection_renewal_count=0,
        rule_snapshot=rule_status_snapshot(session),
    )
    session.add(row)
    session.flush()
    record_event(
        session,
        actor,
        "commercial_opportunity_reported",
        actor,
        {
            "request_id": str(uuid4()),
            "opportunity_id": row.id,
            "enterprise_code": row.enterprise_code,
        },
    )
    return {"opportunity": serialize_opportunity(
                session, row, actor=actor, enforce_ownership=False
            ),
            "changed": True,}


def confirm_enterprise_demand(
    session: Session,
    *,
    actor: User,
    opportunity_id: object,
    confirmation_uri: object,
    confirmation_hash: object,
    confirm_password: object,
) -> dict[str, Any]:
    """② 企业确认有真实需求（平台代录企业书面答复：admin + 密码确认）。

    企业尚未成为账号主体时，企业确认只能以**线下书面依据**由平台代录——依据
    只存指针 + sha256 指纹（原件留在 fdeops/openfde 工作目录）。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    row = _load(session, opportunity_id)
    if row.status != "submitted":
        raise _error(
            "invalid_opportunity_state",
            f"只有已报备的商机可确认企业需求（当前状态 {row.status}）。",
            409,
        )
    uri = _require_uri(confirmation_uri, "confirmation_uri")
    digest = _require_sha256(confirmation_hash, "confirmation_hash")
    row.enterprise_confirmed_by_user_id = actor.id
    row.enterprise_confirmed_at = _now()
    row.enterprise_confirmation_uri = uri
    row.enterprise_confirmation_hash = digest
    row.status = "enterprise_confirmed"
    row.rule_snapshot = rule_status_snapshot(session)
    session.flush()
    record_event(
        session,
        actor,
        "commercial_opportunity_enterprise_confirmed",
        actor,
        {
            "request_id": str(uuid4()),
            "opportunity_id": row.id,
            "enterprise_code": row.enterprise_code,
        },
    )
    return {"opportunity": serialize_opportunity(
                session, row, actor=actor, enforce_ownership=False
            ),
            "changed": True,}


def confirm_attribution(
    session: Session,
    *,
    actor: User,
    opportunity_id: object,
    owner_user_id: object,
    attribution_uri: object,
    attribution_hash: object,
    confirm_password: object,
) -> dict[str, Any]:
    """③ 平台确认商机归属（**关键流转**：admin + 密码确认，ADR-007 §2.1）。

    归属**只能由人确认**（系统不出「自动生效」的归属判定）。已确认归属的商机
    再次确认 ⇒ 409 ``attribution_already_confirmed``（**不得静默改写归属**）。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    row = _load(session, opportunity_id)
    if row.attribution_owner_user_id is not None:
        raise _error(
            "attribution_already_confirmed",
            "该商机归属已确认，不得静默改写（改派须走显式动作且判据规则须成文）。",
            409,
        )
    if row.status != "enterprise_confirmed":
        raise _error(
            "invalid_opportunity_state",
            f"只有企业已确认的商机可确认归属（当前状态 {row.status}）。",
            409,
        )
    owner = _require_user(session, owner_user_id, "owner_user_id")
    uri = _require_uri(attribution_uri, "attribution_uri")
    digest = _require_sha256(attribution_hash, "attribution_hash")
    row.attribution_owner_user_id = owner.id
    row.attribution_confirmed_by_user_id = actor.id
    row.attribution_confirmed_at = _now()
    row.attribution_uri = uri
    row.attribution_hash = digest
    row.status = "attribution_confirmed"
    row.rule_snapshot = rule_status_snapshot(session)
    session.flush()
    record_event(
        session,
        actor,
        "commercial_opportunity_attribution_confirmed",
        actor,
        {
            "request_id": str(uuid4()),
            "opportunity_id": row.id,
            "owner_user_id": owner.id,
            "enterprise_code": row.enterprise_code,
        },
    )
    return {"opportunity": serialize_opportunity(
                session, row, actor=actor, enforce_ownership=False
            ),
            "changed": True,}


def reassign_attribution(
    session: Session,
    *,
    actor: User,
    opportunity_id: object,
    owner_user_id: object,
    reason_uri: object,
    reason_hash: object,
    confirm_password: object,
) -> dict[str, Any]:
    """改派归属（**判据规则未成文 ⇒ 不可用**，409 ``rule_not_configured``）。

    「已确认归属的商机不得**简单**转移」的最强可执行形态：**本期没有转移路径**，
    直到归属判定规则成文并配置。改派是人工、显式、带依据的治理动作，**不是**
    企业注册的后果。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    require_rule_configured(session, "attribution_criteria")
    row = _load(session, opportunity_id)
    if row.attribution_owner_user_id is None:
        raise _error(
            "attribution_not_confirmed", "该商机尚未确认归属，无可改派对象。", 409
        )
    owner = _require_user(session, owner_user_id, "owner_user_id")
    uri = _require_uri(reason_uri, "reason_uri")
    digest = _require_sha256(reason_hash, "reason_hash")
    previous_owner = row.attribution_owner_user_id
    row.attribution_owner_user_id = owner.id
    row.attribution_confirmed_by_user_id = actor.id
    row.attribution_confirmed_at = _now()
    row.attribution_uri = uri
    row.attribution_hash = digest
    row.rule_snapshot = rule_status_snapshot(session)
    session.flush()
    record_event(
        session,
        actor,
        "commercial_opportunity_attribution_reassigned",
        actor,
        {
            "request_id": str(uuid4()),
            "opportunity_id": row.id,
            "previous_owner_user_id": previous_owner,
            "owner_user_id": owner.id,
        },
    )
    return {"opportunity": serialize_opportunity(
                session, row, actor=actor, enforce_ownership=False
            ),
            "changed": True,}


def set_protection(
    session: Session,
    *,
    actor: User,
    opportunity_id: object,
    confirm_password: object,
) -> dict[str, Any]:
    """④ 设定保护期（admin + 密码确认）。

    **保护期长度取配置位** ``protection_period_days``；未配置 ⇒ 409
    ``rule_not_configured``，保护期**保持** ``unconfigured``（既非永久保护，
    也非立即失效）。配置后方可设定，起止时刻必落（库层 CHECK 兜底）。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    rule = require_rule_configured(session, "protection_period_days")
    row = _load(session, opportunity_id)
    if row.attribution_owner_user_id is None:
        raise _error(
            "attribution_not_confirmed", "未确认归属的商机不可设定保护期。", 409
        )
    days = int(rule.days or 0)
    if days <= 0:
        raise _error("rule_not_configured", "保护期长度未配置有效天数。", 409)
    started = _now()
    row.protection_status = "active"
    row.protection_started_at = started
    row.protection_expires_at = started + timedelta(days=days)
    row.rule_snapshot = rule_status_snapshot(session)
    session.flush()
    record_event(
        session,
        actor,
        "commercial_opportunity_protection_set",
        actor,
        {
            "request_id": str(uuid4()),
            "opportunity_id": row.id,
            "days": days,
            "expires_at": row.protection_expires_at.isoformat()
            if row.protection_expires_at
            else None,
        },
    )
    return {"opportunity": serialize_opportunity(
                session, row, actor=actor, enforce_ownership=False
            ),
            "changed": True,}


def renew_protection(
    session: Session,
    *,
    actor: User,
    opportunity_id: object,
    confirm_password: object,
) -> dict[str, Any]:
    """续期保护期（**续期条件规则未成文 ⇒ 不可用**，409 ``rule_not_configured``）。

    续期长度沿用保护期长度配置位（**不落默认天数**）；每次续期累加计数并留痕。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    require_rule_configured(session, "renewal_conditions")
    period = require_rule_configured(session, "protection_period_days")
    row = _load(session, opportunity_id)
    if row.protection_status not in ("active", "expired"):
        raise _error(
            "invalid_protection_state",
            f"只有保护中或已到期的商机可续期（当前 {row.protection_status}）。",
            409,
        )
    days = int(period.days or 0)
    if days <= 0:
        raise _error("rule_not_configured", "保护期长度未配置有效天数。", 409)
    now = _now()
    base = row.protection_expires_at or row.protection_started_at or now
    if base <= now:
        base = now
    row.protection_status = "active"
    row.protection_started_at = row.protection_started_at or now
    row.protection_expires_at = base + timedelta(days=days)
    row.protection_renewal_count = int(row.protection_renewal_count) + 1
    row.protection_renewed_at = now
    row.rule_snapshot = rule_status_snapshot(session)
    session.flush()
    record_event(
        session,
        actor,
        "commercial_opportunity_protection_renewed",
        actor,
        {
            "request_id": str(uuid4()),
            "opportunity_id": row.id,
            "days": days,
            "renewal_count": row.protection_renewal_count,
        },
    )
    return {"opportunity": serialize_opportunity(
                session, row, actor=actor, enforce_ownership=False
            ),
            "changed": True,}


def assign_presales(
    session: Session,
    *,
    actor: User,
    opportunity_id: object,
    owner_user_id: object = None,
    confirm_password: object,
) -> dict[str, Any]:
    """⑤ 创业者负责售前与客户关系（admin + 密码确认）。

    负责人默认＝归属人；可显式改派并留痕（**不改归属**）。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    row = _load(session, opportunity_id)
    _reject_when_disputed(row)
    if row.status != "attribution_confirmed":
        raise _error(
            "invalid_opportunity_state",
            f"只有已确认归属的商机可进入售前（当前状态 {row.status}）。",
            409,
        )
    owner = (
        _require_user(session, owner_user_id, "owner_user_id")
        if owner_user_id is not None
        else session.get(User, row.attribution_owner_user_id or "")
    )
    if owner is None:
        raise _error("user_not_found", "归属人账号不存在。", 404)
    row.presales_owner_user_id = owner.id
    row.status = "presales"
    row.rule_snapshot = rule_status_snapshot(session)
    session.flush()
    record_event(
        session,
        actor,
        "commercial_opportunity_presales_assigned",
        actor,
        {
            "request_id": str(uuid4()),
            "opportunity_id": row.id,
            "presales_owner_user_id": owner.id,
        },
    )
    return {"opportunity": serialize_opportunity(
                session, row, actor=actor, enforce_ownership=False
            ),
            "changed": True,}


def record_match(
    session: Session,
    *,
    actor: User,
    opportunity_id: object,
    delivery_package_id: object,
    confirm_password: object,
) -> dict[str, Any]:
    """⑥ 平台撮合交付者（admin + 密码确认；**引用既有 dispatch 交付包**）。

    交付包必须挂在**同一企业代号**的项目上（否则 409
    ``package_enterprise_mismatch``）——撮合不得张冠李戴。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    row = _load(session, opportunity_id)
    _reject_when_disputed(row)
    if row.status != "presales":
        raise _error(
            "invalid_opportunity_state",
            f"只有进入售前的商机可撮合交付者（当前状态 {row.status}）。",
            409,
        )
    package = _require_package(session, delivery_package_id)
    package_enterprise = _package_enterprise_code(session, package)
    if package_enterprise != row.enterprise_code:
        raise _error(
            "package_enterprise_mismatch",
            "交付包所属企业与商机企业代号不一致，不得撮合。",
            409,
        )
    row.matched_delivery_package_id = package.id
    row.status = "matched"
    row.rule_snapshot = rule_status_snapshot(session)
    session.flush()
    record_event(
        session,
        actor,
        "commercial_opportunity_matched",
        actor,
        {
            "request_id": str(uuid4()),
            "opportunity_id": row.id,
            "delivery_package_id": package.id,
        },
    )
    return {"opportunity": serialize_opportunity(
                session, row, actor=actor, enforce_ownership=False
            ),
            "changed": True,}


def record_customer_choice(
    session: Session,
    *,
    actor: User,
    opportunity_id: object,
    delivery_package_id: object,
    confirm_password: object,
) -> dict[str, Any]:
    """客户自主选择交付包（**客户自主选择权规则未成文 ⇒ 不可用**）。

    选择**不改变归属**（归属仍是归属人）——选择权是渠道内的选择，不是归属转移。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    require_rule_configured(session, "customer_choice")
    row = _load(session, opportunity_id)
    if row.status not in ("presales", "matched"):
        raise _error(
            "invalid_opportunity_state",
            f"只有进入售前或已撮合的商机可由客户自主选择（当前状态 {row.status}）。",
            409,
        )
    package = _require_package(session, delivery_package_id)
    row.customer_choice_package_id = package.id
    row.rule_snapshot = rule_status_snapshot(session)
    session.flush()
    record_event(
        session,
        actor,
        "commercial_opportunity_customer_choice",
        actor,
        {
            "request_id": str(uuid4()),
            "opportunity_id": row.id,
            "delivery_package_id": package.id,
        },
    )
    return {"opportunity": serialize_opportunity(
                session, row, actor=actor, enforce_ownership=False
            ),
            "changed": True,}


def record_settlement(
    session: Session,
    *,
    actor: User,
    opportunity_id: object,
    ledger_entry_id: object,
    confirm_password: object,
) -> dict[str, Any]:
    """⑦ 按既定分成规则结算（admin + 密码确认；**引用 G3 科目层的 project_share 行**）。

    结算行必须是**项目分成科目**且未作废；若该行挂了交付包，须与撮合的交付包
    一致（409 ``ledger_package_mismatch``）——结算不得张冠李戴。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    row = _load(session, opportunity_id)
    _reject_when_disputed(row)
    if row.status != "matched":
        raise _error(
            "invalid_opportunity_state",
            f"只有已撮合的商机可结算（当前状态 {row.status}）。",
            409,
        )
    if not isinstance(ledger_entry_id, str) or not ledger_entry_id:
        raise _error("invalid_request", "ledger_entry_id 必填。")
    entry = session.scalars(
        select(CommercialRevenueLedger)
        .where(CommercialRevenueLedger.id == ledger_entry_id)
        .with_for_update()
    ).first()
    if entry is None:
        raise _error("ledger_entry_not_found", "科目行不存在。", 404)
    if entry.subject_type != "project_share":
        raise _error(
            "ledger_subject_mismatch", "结算必须引用项目分成科目行（project_share）。", 409
        )
    if entry.status == "voided":
        raise _error("ledger_entry_voided", "结算科目行已作废，不可结算。", 409)
    # QR-056：对齐 regional_service.py:470-479，无包或包不一致一律 409，封堵无包行跨企业结算洞
    if (
        entry.delivery_package_id is None
        or row.matched_delivery_package_id is None
        or entry.delivery_package_id != row.matched_delivery_package_id
    ):
        raise _error(
            "ledger_package_mismatch", "结算科目行的交付包缺失或与撮合结果不一致。", 409
        )
    # QR-059：同一笔 project_share 科目行不可被多条商机重复引用结算
    existing_settled = session.scalars(
        select(CommercialOpportunity).where(
            CommercialOpportunity.settled_ledger_entry_id == entry.id,
            CommercialOpportunity.id != row.id,
        )
    ).first()
    if existing_settled is not None:
        raise _error(
            "ledger_already_settled", "该结算科目行已被其他商机结算引用，不可重复结算。", 409
        )
    row.settled_ledger_entry_id = entry.id
    row.status = "settled"
    row.rule_snapshot = rule_status_snapshot(session)
    session.flush()
    record_event(
        session,
        actor,
        "commercial_opportunity_settled",
        actor,
        {
            "request_id": str(uuid4()),
            "opportunity_id": row.id,
            "ledger_entry_id": entry.id,
            "amount": float(entry.amount),
        },
    )
    return {"opportunity": serialize_opportunity(
                session, row, actor=actor, enforce_ownership=False
            ),
            "changed": True,}


def mark_disputed(
    session: Session,
    *,
    actor: User,
    opportunity_id: object,
    dispute_uri: object,
    dispute_hash: object,
    confirm_password: object,
) -> dict[str, Any]:
    """发起争议（**争议处理机制未成文 ⇒ 不可用**，409 ``rule_not_configured``）。

    争议期间链路冻结（撮合/结算 409 ``opportunity_disputed``）。争议材料只落
    指针 + 指纹。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    require_rule_configured(session, "dispute_handling")
    row = _load(session, opportunity_id)
    if row.status in ("withdrawn", "settled"):
        raise _error(
            "invalid_opportunity_state",
            f"当前状态 {row.status} 不可发起争议。",
            409,
        )
    uri = _require_uri(dispute_uri, "dispute_uri")
    digest = _require_sha256(dispute_hash, "dispute_hash")
    row.disputed_at = _now()
    row.dispute_uri = uri
    row.dispute_hash = digest
    row.status = "disputed"
    row.rule_snapshot = rule_status_snapshot(session)
    session.flush()
    record_event(
        session,
        actor,
        "commercial_opportunity_disputed",
        actor,
        {
            "request_id": str(uuid4()),
            "opportunity_id": row.id,
        },
    )
    return {"opportunity": serialize_opportunity(
                session, row, actor=actor, enforce_ownership=False
            ),
            "changed": True,}


def withdraw_opportunity(
    session: Session, *, actor: User, opportunity_id: object
) -> dict[str, Any]:
    """撤回商机（**报备人自证动作**；他人 403）。

    撤回**不动归属**（已确认归属的商机撤回后归属事实仍在库内，便于审计）。
    """
    row = _load(session, opportunity_id)
    if actor.role != ROLE_ADMIN and row.reported_by_user_id != actor.id:
        raise _error("opportunity_forbidden", "只有报备人本人可撤回商机。", 403)
    if row.status == "withdrawn":
        return {
            "opportunity": serialize_opportunity(
                session, row, actor=actor, enforce_ownership=False
            ),
            "changed": False,
        }
    if row.status == "settled":
        raise _error("invalid_opportunity_state", "已结算的商机不可撤回。", 409)
    row.withdrawn_at = _now()
    row.status = "withdrawn"
    session.flush()
    record_event(
        session,
        actor,
        "commercial_opportunity_withdrawn",
        actor,
        {
            "request_id": str(uuid4()),
            "opportunity_id": row.id,
        },
    )
    return {"opportunity": serialize_opportunity(
                session, row, actor=actor, enforce_ownership=False
            ),
            "changed": True,}


def _reject_when_disputed(row: CommercialOpportunity) -> None:
    """争议期间链路冻结（成文规则 §6-2）：撮合/售前/结算一律拒绝。"""
    if row.status == "disputed":
        raise _error(
            "opportunity_disputed",
            "该商机处于争议中，链路冻结（争议处理按成文规则执行）。",
            409,
        )


def _require_package(session: Session, package_id: object) -> DeliveryPackage:
    if not isinstance(package_id, str) or not package_id:
        raise _error("invalid_request", "delivery_package_id 必填。")
    package = session.get(DeliveryPackage, package_id)
    if package is None:
        raise _error("package_not_found", "交付包不存在。", 404)
    return package


def _package_enterprise_code(session: Session, package: DeliveryPackage) -> str | None:
    project = session.get(Project, package.project_id)
    return project.enterprise_code if project is not None else None


__all__ = [
    "CommercialServiceError",
    "OPPORTUNITY_CUSTOMER_IDENTITY_FIELDS",
    "OPPORTUNITY_PROTECTION_STATUSES",
    "OPPORTUNITY_RULE_STATUSES",
    "active_protection_for_enterprise",
    "assign_presales",
    "configure_rule",
    "confirm_attribution",
    "confirm_enterprise_demand",
    "customer_identity_visible",
    "ensure_rule",
    "get_opportunity",
    "is_opportunity_custodian",
    "is_regional_partner",
    "list_opportunities",
    "list_rules",
    "mark_disputed",
    "protection_effective_status",
    "record_customer_choice",
    "record_match",
    "record_settlement",
    "reassign_attribution",
    "renew_protection",
    "require_enterprise_confirmed_for_customer_list",
    "require_rule_configured",
    "rule_status_snapshot",
    "serialize_opportunity",
    "serialize_rule",
    "set_protection",
    "submit_opportunity",
    "withdraw_opportunity",
]
