"""goal-r1 P0 双闸门回归（派单设计 §8.3 / §9.4 / §9.5）。

- P0-6（§8.3）：record_event 支持 delivery_package / dispatch_offer 两类目标
  ——不注册则 events.py `_TARGET_TYPES` 查不到直接 TypeError（设计 §2.5 坑 1）。
- P0-5（§9.4，§8.8 开池四道闸之二）：门禁验收分离——
  ① 拍板人 ≠ 该门禁执行人（gate_decider_conflict → 403，代码强制不可绕过）；
  ② 交付方执行的 G8/G9 须平台侧（admin）拍板（gate_decider_role_required → 403）。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.dispatch.models import DeliveryPackage, DispatchOffer
from fde_api.projects.events import record_event
from fde_api.projects.gate_service import GateServiceError, decide_gate
from fde_api.solutions.models import ProjectSolution
from fde_api.workbench.models import (
    Gate,
    IndustryTemplate,
    IndustryTemplateVersion,
    OperationEvent,
    Project,
)
from fde_api.workbench.seed import GENERIC_TEMPLATE_KEY, seed_workbench

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


# ---------------------------------------------------------------------------
# P0-6：events 白名单两类派单目标
# ---------------------------------------------------------------------------


def _dispatch_context(db_session):
    """直插 actor/project/solution/package/offer（服务逻辑未建，走模型层）。"""
    actor = _user("dispatch.actor")
    template = IndustryTemplate(
        template_key=f"dispatch-tpl-{uuid4().hex[:8]}",
        name="派单模板",
        industry_name="制造业",
    )
    version = IndustryTemplateVersion(
        template=template,
        name="派单模板 v1",
        industry_name="制造业",
        version_number=1,
        status="published",
    )
    project = Project(
        project_code=f"DP-{uuid4().hex[:6].upper()}",
        name="派单事件项目",
        enterprise_code=f"星河派单·制造·{uuid4().hex[:6]}",
        planned_start_date=date(2026, 10, 31),
        leader_user_id=actor.id,
        source_template_version=version,
        template_snapshot={"industry_name": "制造业", "modules": []},
    )
    db_session.add_all([actor, project])
    db_session.flush()
    solution = ProjectSolution(
        project_id=project.id,
        name="派单方案",
        owner_user_id=actor.id,
    )
    db_session.add(solution)
    db_session.flush()
    package = DeliveryPackage(
        id=solution.id,  # §2.2：package_id 直接引用 ProjectSolution.id
        solution_id=solution.id,
        project_id=project.id,
        package_code=f"PKG-{uuid4().hex[:10].upper()}",
    )
    offer = DispatchOffer(
        package_id=solution.id,
        dispatch_round=1,
        candidate_user_id=actor.id,
        match_breakdown={"rule_version": "v1", "score": 90},
    )
    db_session.add_all([package, offer])
    db_session.flush()
    return actor, project, package, offer


def test_record_event_supports_delivery_package_target(db_session):
    """P0-6 判据：交付包状态迁移可写 OperationEvent（target_type=delivery_package）。"""
    actor, project, package, _offer = _dispatch_context(db_session)

    event = record_event(
        db_session,
        actor,
        "delivery_package_published",
        package,
        {"dispatch_status": {"from": "draft", "to": "published"}},
    )
    db_session.flush()

    stored = db_session.get(OperationEvent, event.id)
    assert stored is not None
    assert stored.target_type == "delivery_package"
    assert stored.target_id == package.id
    assert stored.project_id == project.id
    assert stored.actor_user_id == actor.id
    assert stored.changes["dispatch_status"]["to"] == "published"


def test_record_event_supports_dispatch_offer_target(db_session):
    """P0-6 判据：offer 留痕可写 OperationEvent（target_type=dispatch_offer，project 经包反查）。"""
    actor, project, _package, offer = _dispatch_context(db_session)

    event = record_event(
        db_session,
        actor,
        "dispatch_offer_created",
        offer,
        {"status": "offered", "candidate_user_id": offer.candidate_user_id},
    )
    db_session.flush()

    stored = db_session.get(OperationEvent, event.id)
    assert stored is not None
    assert stored.target_type == "dispatch_offer"
    assert stored.target_id == offer.id
    assert stored.project_id == project.id


def test_dispatch_offer_optimistic_lock_column_present(db_session):
    """§8.2：dispatch_offers 挂 VersionedMixin 乐观锁位（§6.3 禁分布式锁）。

    本仓乐观锁惯例：服务层先比对 expected_version 再显式递增（无 ORM 自动 +1），
    offer_service（P1-1）沿用同一模式。
    """
    _actor, _project, _package, offer = _dispatch_context(db_session)
    assert offer.version == 1
    offer.version += 1
    db_session.flush()
    assert offer.version == 2


# ---------------------------------------------------------------------------
# P0-5：门禁验收分离（§9.4）
# ---------------------------------------------------------------------------


@pytest.fixture
def separation_context(client, db_session, settings):
    """admin（平台侧）+ leader（项目管理位）+ 已激活项目，返回四件套。"""
    seed_workbench(db_session)
    db_session.commit()
    template = db_session.scalar(
        select(IndustryTemplateVersion)
        .join(IndustryTemplate)
        .where(
            IndustryTemplateVersion.status == "published",
            IndustryTemplate.template_key == GENERIC_TEMPLATE_KEY,
        )
    )
    admin = _user("sep.admin", role="admin")
    leader = _user("sep.lead", role="project_lead")
    db_session.add_all([admin, leader])
    db_session.commit()

    admin_client = _authorized(client, settings, admin)
    response = admin_client.post(
        "/api/v1/projects",
        json={
            "name": "验收分离项目",
            "enterprise_code": f"验收分离·回归·{uuid4().hex[:8]}",
            "template_version_id": template.id,
            "leader_user_id": leader.id,
            "planned_start_date": "2026-08-21",
            "module_keys": ["pre_diagnosis"],
        },
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    project = response.json["data"]
    activated = admin_client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"version": project["version"], "status": "active"},
    )
    assert activated.status_code == 200, activated.get_data(as_text=True)
    leader_client = _authorized(client, settings, leader)
    gates_url = f"/api/v1/projects/{project['id']}/gates"
    # 懒实例化 9 门
    assert admin_client.get(gates_url).status_code == 200
    return admin, leader, admin_client, leader_client, project["id"], gates_url


def _submit_all_evidence(authorized: AuthorizedClient, gates_url: str, gate_key: str):
    gates = authorized.get(gates_url).json["data"]["gates"]
    gate = next(g for g in gates if g["gate_key"] == gate_key)
    response = authorized.post(
        f"{gates_url}/{gate_key}/evidence",
        json={
            "expected_revision": gate["revision"],
            "items": [
                {
                    "label": item["label"],
                    "source_uri": f"fdeops://goal-r1/{gate_key}",
                    "content_hash": hashlib.sha256(item["label"].encode()).hexdigest(),
                }
                for item in gate["checklist"]
            ]
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.json["data"]["revision"]


def test_executor_cannot_decide_own_gate(separation_context, db_session):
    """P0-5 判据：执行方拍自己的门 → 403 gate_decider_conflict，状态不被改动。"""
    admin, leader, admin_client, leader_client, project_id, gates_url = (
        separation_context
    )
    revision = _submit_all_evidence(admin_client, gates_url, "G1")

    conflict = admin_client.post(f"{gates_url}/G1/decision", json={"expected_revision": revision, "result": "pass"})
    assert conflict.status_code == 403
    assert conflict.json["error"]["code"] == "gate_decider_conflict"

    gate_row = db_session.scalar(
        select(Gate).where(Gate.project_id == project_id, Gate.gate_key == "G1")
    )
    assert gate_row.status == "evidence"
    assert gate_row.submitted_by_user_id == admin.id
    assert gate_row.is_delivery_party is False

    decided = leader_client.post(f"{gates_url}/G1/decision", json={"expected_revision": revision, "result": "pass"})
    assert decided.status_code == 200, decided.get_data(as_text=True)
    assert decided.json["data"]["status"] == "passed"
    assert decided.json["data"]["decided_by_user_id"] == leader.id
    assert decided.json["data"]["submitted_by_user_id"] == admin.id


def test_delivery_party_gate_g8_requires_platform_decider(
    separation_context, db_session
):
    """P0-5/§11.3 方案①：交付方执行的 G8 须平台侧拍板——leader 403，admin 放行。

    is_delivery_party 的 API 写入路径随派单池接单（§9.3）落位，此处按列语义
    直改行状态构造场景（member 执行 + 已全部 claimed）。
    """
    admin, leader, admin_client, leader_client, project_id, gates_url = (
        separation_context
    )
    revision = _submit_all_evidence(admin_client, gates_url, "G8")
    delivery_member = _user("sep.delivery.member", role="fde_engineer")
    db_session.add(delivery_member)
    db_session.commit()

    g8 = db_session.scalar(
        select(Gate).where(Gate.project_id == project_id, Gate.gate_key == "G8")
    )
    checklist = [dict(item, claim_status="claimed") for item in g8.evidence_checklist]
    db_session.execute(
        update(Gate)
        .where(Gate.id == g8.id)
        .values(
            evidence_checklist=checklist,
            is_delivery_party=True,
            submitted_by_user_id=delivery_member.id,
        )
    )
    db_session.commit()

    denied = leader_client.post(
        f"{gates_url}/G8/decision", json={"expected_revision": revision, "result": "pass", "decision": "proceed"}
    )
    assert denied.status_code == 403
    assert denied.json["error"]["code"] == "gate_decider_role_required"

    approved = admin_client.post(
        f"{gates_url}/G8/decision", json={"expected_revision": revision, "result": "pass", "decision": "proceed"}
    )
    assert approved.status_code == 200, approved.get_data(as_text=True)
    assert approved.json["data"]["status"] == "passed"
    assert approved.json["data"]["decided_by_user_id"] == admin.id
    assert approved.json["data"]["is_delivery_party"] is True


def test_decide_gate_service_level_conflict_guard(separation_context):
    """服务层直调同样被拦（防绕过 API 层的兜底断言）。"""
    _admin, _leader, admin_client, _leader_client, _project_id, gates_url = (
        separation_context
    )
    revision = _submit_all_evidence(admin_client, gates_url, "G2")

    with pytest.raises(GateServiceError) as excinfo:
        decide_gate(
            actor=_admin,
            project_id=_project_id,
            gate_key="G2",
            payload={"expected_revision": revision, "result": "pass"},
        )
    assert excinfo.value.code == "gate_decider_conflict"
    assert excinfo.value.status == 403
