"""goal-r3 P0 簇②收尾回归（派单设计 §8.3 P0-1/P0-2 + §9.5 隔离基线）。

- P0-1：§2.3 canonical_json 快照冻结（发布后改 solution/quote 不回写）+
  §2.5 八态状态机全迁移 + 发布前置（报价 finalized）。
- P0-2：package_access 第三语义 + §9.5 四条隔离基线——
  ① 跨主体访问 100% 拒绝（参数化）；② 响应体字段白名单断言；
  ③ 静态检查（dispatch 读路径无三表 join、无裸 session.query）；
  ④ 渗透用例（越权接单 / 快照篡改回写 / 重放已撤销授权）。
- §9.3：接单交接复用 add_project_member（零新增项目内鉴权路径）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.dispatch.access import (
    grant_package_access,
    revoke_package_access,
)
from fde_api.dispatch.errors import DispatchServiceError
from fde_api.dispatch.models import DeliveryPackage, PackageAccess
from fde_api.dispatch.packages import (
    canonical_json,
    compute_snapshot_hash,
    create_package,
    publish_package,
    transition_package,
)
from fde_api.solutions.models import ProjectSolution
from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    OperationEvent,
    Project,
    ProjectMember,
    Quote,
)

from conftest import INITIAL_PASSWORD


@dataclass(frozen=True)
class AuthorizedClient:
    client: object
    user: User
    headers: dict[str, str]

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)

    def patch(self, *args, **kwargs):
        return self.client.patch(*args, headers=self.headers, **kwargs)


def _user(username: str, role: str = "admin") -> User:
    return User(
        username=f"{username}.{uuid4().hex[:8]}",
        display_name=username,
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )


def _authorized(client, settings, user: User) -> AuthorizedClient:
    return AuthorizedClient(
        client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    )


def _context(db_session, *, schedule: str = "远程交付", final_amount: str = "20000"):
    """方案 + finalized 报价 + 交付包 draft 三件套。"""
    admin = _user("r3.admin")
    fde = _user("r3.fde", role="fde_engineer")
    template = IndustryTemplate(
        template_key=f"r3-tpl-{uuid4().hex[:8]}",
        name="r3 模板",
        industry_name="制造业",
    )
    version = IndustryTemplateVersion(
        template=template,
        name="r3 模板 v1",
        industry_name="制造业",
        version_number=1,
        status="published",
    )
    project = Project(
        project_code=f"R3-{uuid4().hex[:6].upper()}",
        name="r3 派单项目",
        enterprise_code=f"r3 企业·制造·{uuid4().hex[:4]}",
        business_line="FDE_DISPATCH",  # P2-4 H3：交付包只建在派单线项目
        planned_start_date=date(2026, 10, 31),
        planned_end_date=date(2026, 12, 31),
        leader_user_id=admin.id,
        source_template_version=version,
        template_snapshot={"industry_name": "制造业", "modules": []},
    )
    db_session.add_all([admin, fde, project])
    db_session.flush()
    solution = ProjectSolution(
        project_id=project.id,
        name="r3 交付方案",
        design_markdown="# 设计",
        deliverables="交付物 A/B",
        acceptance_criteria="验收口径",
        data_systems="ERP",
        schedule=schedule,
        risks_dependencies="无",
        owner_user_id=admin.id,
    )
    db_session.add(solution)
    db_session.flush()
    quote = Quote(
        project_id=project.id,
        quote_key=f"Q-{uuid4().hex[:8]}",
        status="finalized",
        tier="standard",
        ideal_hours=Decimal("100"),
        realistic_hours=Decimal("100"),
        integration_factor=Decimal("1.00"),
        data_factor=Decimal("1.00"),
        compliance_factor=Decimal("1.00"),
        buffer_factor=Decimal("1.00"),
        hourly_rate=150,
        cash_cost=100000,
        margin_factor=Decimal("1.40"),
        b_layer_score=5,
        b_layer_factor=Decimal("1.00"),
        anchor_mode="steady",
        labor_cost=Decimal("100000"),
        total_cost=Decimal("100000"),
        formula_price=Decimal("200000"),
        anchor_low=200000,
        anchor_high=300000,
        branch="A",
        final_amount=Decimal(final_amount),
        field_claims={"final_amount": "measured"},
    )
    db_session.add(quote)
    db_session.flush()
    package = create_package(
        db_session, actor=admin, solution_id=solution.id, quote_id=quote.id
    )
    db_session.flush()
    return admin, fde, project, solution, quote, package


# ---------------------------------------------------------------------------
# P0-1：canonical_json + 快照冻结
# ---------------------------------------------------------------------------


def test_canonical_json_rules():
    """§2.3：键字典序、Decimal→str、None→null、ensure_ascii=False、紧凑分隔符。"""
    payload = {
        "b_layer_score": 5,
        "quote_low": Decimal("123.40"),
        "required_modules": ["m2", "m1"],  # 调用方先排序（publish 已排）
        "seat_lead": None,
        "name": "中文·方案",
    }
    assert canonical_json(payload) == (
        '{"b_layer_score":5,"name":"中文·方案","quote_low":"123.40",'
        '"required_modules":["m2","m1"],"seat_lead":null}'
    )
    assert len(compute_snapshot_hash(payload)) == 64


def test_snapshot_frozen_after_publish(db_session):
    """P0-1 判据：发布后改 solution/quote 不回写快照（哈希与席位金额双冻结）。"""
    admin, _fde, project, solution, quote, package = _context(db_session)
    publish_package(db_session, actor=admin, package_id=package.id)
    frozen_hash = package.snapshot_hash
    frozen_amount = package.delivery_seat_amount
    assert frozen_hash is not None
    assert frozen_amount == Decimal("8000.00")  # 20000 × 40%

    # 发布后改真相层（直接 ORM 模拟方案/报价演进）
    solution.design_markdown = "# 改过的设计"
    solution.deliverables = "改过的交付物"
    quote.final_amount = Decimal("99999")
    db_session.flush()
    db_session.refresh(package)
    assert package.snapshot_hash == frozen_hash
    assert package.delivery_seat_amount == frozen_amount

    # 用「现在的数据」重算快照必然不同 → 冻结语义可证伪
    from fde_api.dispatch.packages import _snapshot_payload
    from datetime import datetime, timezone

    payload = _snapshot_payload(
        package, solution, project, quote, published_at=datetime.now(timezone.utc)
    )
    assert compute_snapshot_hash(payload) != frozen_hash


def test_publish_requires_finalized_quote(db_session):
    admin, _fde, _p, _s, quote, package = _context(db_session)
    quote.status = "draft"
    db_session.flush()
    with pytest.raises(DispatchServiceError) as excinfo:
        publish_package(db_session, actor=admin, package_id=package.id)
    assert excinfo.value.code == "quote_not_finalized"
    assert excinfo.value.status == 422
    db_session.refresh(package)
    assert package.dispatch_status == "draft"


def test_publish_grants_candidate_read_access(db_session):
    admin, fde, _p, _s, _q, package = _context(db_session)
    publish_package(
        db_session, actor=admin, package_id=package.id, candidate_user_ids=(fde.id,)
    )
    row = db_session.scalar(
        select(PackageAccess).where(
            PackageAccess.package_id == package.id, PackageAccess.user_id == fde.id
        )
    )
    assert row is not None and row.role == "delivery" and row.revoked_at is None


# ---------------------------------------------------------------------------
# P0-1：§2.5 八态状态机
# ---------------------------------------------------------------------------


def _events_of(db_session, package_id: str) -> set[str]:
    return set(
        db_session.scalars(
            select(OperationEvent.event_type).where(
                OperationEvent.target_id == package_id,
                OperationEvent.target_type == "delivery_package",
            )
        )
    )


def test_eight_state_machine_full_walk(db_session):
    """§2.5：主路径 + 拒绝重派 + 超时 + 撤回重发，非法迁移 409。"""
    admin, _fde, _p, _s, _q, package = _context(db_session)
    # 主路径：draft→published→offered→assigned→accepted
    publish_package(db_session, actor=admin, package_id=package.id)
    for action in ("offer", "assign", "accept"):
        transition_package(
            db_session,
            actor=admin,
            package_id=package.id,
            action=action,
            seat_delivery_user_id=_fde.id if action == "accept" else None,
        )
    assert package.dispatch_status == "accepted"
    assert package.accepted_user_id == _fde.id
    assert package.seat_delivery == _fde.id
    events = _events_of(db_session, package.id)
    assert {
        "delivery_package_created",
        "delivery_package_published",
        "delivery_package_offer",
        "delivery_package_assign",
        "delivery_package_accept",
    } <= events
    # 已接单不可撤回（状态机拒绝）
    with pytest.raises(DispatchServiceError) as excinfo:
        transition_package(db_session, actor=admin, package_id=package.id, action="withdraw")
    assert excinfo.value.code == "invalid_dispatch_state"

    # 路径二：拒绝 → 重发（round+1 新哈希新编码）
    _, _, _, _, _, pkg2 = _context(db_session)
    publish_package(db_session, actor=admin, package_id=pkg2.id)
    hash_round1 = pkg2.snapshot_hash
    transition_package(db_session, actor=admin, package_id=pkg2.id, action="offer")
    transition_package(db_session, actor=admin, package_id=pkg2.id, action="reject")
    assert pkg2.dispatch_status == "rejected"
    first_code = pkg2.package_code
    publish_package(db_session, actor=admin, package_id=pkg2.id)
    assert pkg2.dispatch_status == "published"
    assert pkg2.dispatch_round == 2
    assert pkg2.package_code != first_code
    assert pkg2.snapshot_hash is not None and pkg2.snapshot_hash != hash_round1

    # 路径三：offered→expired（响应超时）
    _, _, _, _, _, pkg3 = _context(db_session)
    publish_package(db_session, actor=admin, package_id=pkg3.id)
    transition_package(db_session, actor=admin, package_id=pkg3.id, action="offer")
    transition_package(db_session, actor=admin, package_id=pkg3.id, action="expire")
    assert pkg3.dispatch_status == "expired"
    # expired 人工介入 = 允许重发
    publish_package(db_session, actor=admin, package_id=pkg3.id)
    assert pkg3.dispatch_status == "published" and pkg3.dispatch_round == 2

    # 路径四：published→withdrawn（无 offer）→ 重发
    _, _, _, _, _, pkg4 = _context(db_session)
    publish_package(db_session, actor=admin, package_id=pkg4.id)
    transition_package(db_session, actor=admin, package_id=pkg4.id, action="withdraw")
    assert pkg4.dispatch_status == "withdrawn"
    publish_package(db_session, actor=admin, package_id=pkg4.id)
    assert pkg4.dispatch_status == "published" and pkg4.dispatch_round == 2


def test_withdraw_blocked_while_offer_in_flight(db_session):
    """防御守卫：published 态但本轮仍有进行中 offer（P1-1 重派流程的防御位）——
    正常序 offered 态先被状态机拦（invalid_dispatch_state）。"""
    admin, _fde, _p, _s, _q, package = _context(db_session)
    from fde_api.dispatch.models import DispatchOffer

    publish_package(db_session, actor=admin, package_id=package.id)
    transition_package(db_session, actor=admin, package_id=package.id, action="offer")
    transition_package(db_session, actor=admin, package_id=package.id, action="reject")
    publish_package(db_session, actor=admin, package_id=package.id)  # round 2 published
    # 构造本轮进行中 offer（模拟 offer_service 异常序），withdraw 应被拦
    db_session.add(
        DispatchOffer(
            package_id=package.id,
            dispatch_round=package.dispatch_round,
            candidate_user_id=_fde.id,
            status="accepted",
        )
    )
    db_session.flush()
    with pytest.raises(DispatchServiceError) as excinfo:
        transition_package(db_session, actor=admin, package_id=package.id, action="withdraw")
    assert excinfo.value.code == "offer_in_flight"


# ---------------------------------------------------------------------------
# §9.3：接单交接
# ---------------------------------------------------------------------------


def test_accept_handover_adds_project_member(db_session, client, settings):
    """§9.3：accept 后交付方成为 ProjectMember(role=member)，既有鉴权自动生效。"""
    admin, fde, project, _s, _q, package = _context(db_session)
    publish_package(
        db_session, actor=admin, package_id=package.id, candidate_user_ids=(fde.id,)
    )
    transition_package(db_session, actor=admin, package_id=package.id, action="offer")
    db_session.commit()

    from fde_api.dispatch.packages import accept_package

    result = accept_package(
        actor=admin, package_id=package.id, delivery_user_id=fde.id
    )
    assert result["dispatch_status"] == "accepted"
    assert result["handover"]["added"] is True
    db_session.expire_all()
    member = db_session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id == fde.id
        )
    )
    assert member is not None and member.role == "member"


# ---------------------------------------------------------------------------
# §9.5 基线①②③④：隔离
# ---------------------------------------------------------------------------


@pytest.fixture
def api_context(client, db_session, settings):
    admin, fde, project, solution, quote, package = _context(db_session)
    stranger = _user("r3.stranger", role="fde_engineer")
    db_session.add(stranger)
    db_session.commit()
    publish_package(
        db_session, actor=admin, package_id=package.id, candidate_user_ids=(fde.id,)
    )
    db_session.commit()
    return {
        "admin": admin,
        "fde": fde,
        "stranger": stranger,
        "project": project,
        "solution": solution,
        "quote": quote,
        "package": package,
        "admin_client": _authorized(client, settings, admin),
        "fde_client": _authorized(client, settings, fde),
        "stranger_client": _authorized(client, settings, stranger),
    }


DISPATCH_ROUTES = (
    ("GET", "/api/v1/dispatch/packages/{pid}"),
    ("POST", "/api/v1/dispatch/packages/{pid}/publish"),
    ("POST", "/api/v1/dispatch/packages/{pid}/withdraw"),
    ("POST", "/api/v1/dispatch/packages/{pid}/accept"),
)


@pytest.mark.parametrize("method,path_template", DISPATCH_ROUTES)
def test_cross_principal_access_denied(api_context, method, path_template):
    """§9.5 基线①：无授权用户对 dispatch 全部 API 读/写 100% 拒绝。"""
    stranger_client = api_context["stranger_client"]
    path = path_template.format(pid=api_context["package"].id)
    body = {"delivery_user_id": api_context["stranger"].id}
    response = getattr(stranger_client, method.lower())(
        path, json=body if method == "POST" else None
    )
    assert response.status_code in (403, 404), (method, path, response.status_code)
    assert response.json["error"]["code"] in (
        "package_not_found",
        "verifier_role_required",
        "forbidden",
    )
    # 列表口径：陌生人看不到别人的包
    listing = stranger_client.get("/api/v1/dispatch/packages")
    assert listing.status_code == 200
    assert listing.json["data"] == []


def test_package_response_field_whitelist(api_context):
    """§9.5 基线②：白名单 12 项 + 席位金额 + id 支撑列；无报价明细、无客户真名字段。"""
    detail = api_context["fde_client"].get(
        f"/api/v1/dispatch/packages/{api_context['package'].id}"
    )
    assert detail.status_code == 200
    payload = detail.json["data"]
    assert set(payload) == {
        "id",
        "package_code",
        "scope_summary",
        "deliverables_json",
        "acceptance_criteria",
        "data_systems",
        "schedule_text",
        "risks_dependencies",
        "business_category",
        "client_code",
        "client_city",
        "onsite_required",
        "onsite_visits",
        "deadline",
        "delivery_seat_amount",
        "dispatch_status",
        "dispatch_round",
        "dispatch_mode",
        "response_window_hours",
        "published_at",
        # goal-d8（D2 裁决三/O-4）：协同声明态 + 订单难度三档入白名单
        "agent_assisted",
        "difficulty",
    }
    # 金额字段只允许 delivery_seat_amount（=final_amount×40%，发布物化）
    assert payload["delivery_seat_amount"] == 8000.0
    forbidden_fragments = ("final_amount", "quote_low", "quote_high", "b_layer_score",
                           "labor_cost", "total_cost", "formula_price", "received",
                           "invoice", "enterprise_name", "contact", "phone")
    serialized = str(payload).lower()
    assert not any(fragment in serialized for fragment in forbidden_fragments)
    # 客户标识只有代号与城市段
    assert payload["client_code"] == api_context["project"].enterprise_code
    assert payload["client_city"] == api_context["project"].enterprise_code.split("·")[2]


def test_static_isolation_rules():
    """§9.5 基线③：dispatch 读路径禁三表引用、全包禁裸 session.query()。"""
    dispatch_dir = Path(__file__).resolve().parents[1] / "src" / "fde_api" / "dispatch"
    forbidden_join_imports = ("Quote", "Payment", "Contract")
    for name in ("access.py", "routes.py"):  # 读/序列化路径（packages.py 是写路径）
        source = (dispatch_dir / name).read_text(encoding="utf-8")
        for symbol in forbidden_join_imports:
            assert not re.search(rf"\b{symbol}\b", source), (name, symbol)
    for path in dispatch_dir.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "session.query(" not in source, path.name


def test_penetration_cases(api_context, db_session):
    """§9.5 基线④：越权接单 / 快照篡改无入口 / 重放已撤销授权。"""
    fde = api_context["fde"]
    stranger = api_context["stranger"]
    package = api_context["package"]

    # ① 越权：被授权的 fde 冒名接别人的单（delivery_user_id ≠ 本人）
    hijack = api_context["fde_client"].post(
        f"/api/v1/dispatch/packages/{package.id}/accept",
        json={"delivery_user_id": stranger.id},
    )
    assert hijack.status_code == 403
    assert hijack.json["error"]["code"] == "forbidden"

    # ② 快照篡改回写：交付包无任何 PUT/PATCH 入口（405）
    tamper = api_context["fde_client"].patch(
        f"/api/v1/dispatch/packages/{package.id}",
        json={"snapshot_hash": "0" * 64, "delivery_seat_amount": 1},
    )
    assert tamper.status_code == 405

    # ③ 重放已撤销授权：撤销 → 详情 404；重新授予走显式 grant 才复活
    revoke_package_access(
        db_session, package_id=package.id, user_id=fde.id, role="delivery"
    )
    db_session.commit()
    denied = api_context["fde_client"].get(f"/api/v1/dispatch/packages/{package.id}")
    assert denied.status_code == 404
    grant_package_access(
        db_session,
        package_id=package.id,
        user_id=fde.id,
        role="delivery",
        granted_by_user_id=api_context["admin"].id,
    )
    db_session.commit()
    revived = api_context["fde_client"].get(f"/api/v1/dispatch/packages/{package.id}")
    assert revived.status_code == 200


def test_platform_user_can_publish_and_candidate_accepts(api_context, db_session):
    """指派制正路径：admin 发布+发派 → 候选人本人接单（持 delivery 授权）。"""
    package = api_context["package"]
    fde_client = api_context["fde_client"]
    transition = api_context["admin_client"].post(
        f"/api/v1/dispatch/packages/{package.id}/publish", json={}
    )
    # 已是 published（fixture 发布过）→ 状态机 409，换 offer 动作走正路径
    assert transition.status_code == 409
    from fde_api.dispatch.packages import transition_package as move

    move(db_session, actor=api_context["admin"], package_id=package.id, action="offer")
    db_session.commit()
    accepted = fde_client.post(
        f"/api/v1/dispatch/packages/{package.id}/accept",
        json={"delivery_user_id": api_context["fde"].id},
    )
    assert accepted.status_code == 200, accepted.get_data(as_text=True)
    assert accepted.json["data"]["dispatch_status"] == "accepted"
    assert accepted.json["data"]["handover"]["added"] is True
