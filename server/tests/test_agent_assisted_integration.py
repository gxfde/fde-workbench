"""goal-d8：D2 合成裁决（PRD §6）四条规则逐条测试 + agent_assisted 两态集成。

- 规则① 接单主体必须是人：声明权只在接单人（admin 管理通道除外）；声明
  绝不触碰 dispatch_status / TRANSITIONS（8 态机零改动）。
- 规则② 降级天然兼容：协同包上 L1 降级家族照常触发 T5 门语义（锚点复用
  d7 T5 判定，本文件只证协同列不旁路降级链）。
- 规则③ 协同显式声明：未声明（accepted 包）→ start_run 409
  agent_assisted_required（纯人工交付，v0.2.0 行为）；声明后才启用。
- 规则④ O-4 三档：difficulty=high 禁声明；low→standard / medium→high
  映射自动带入 run.difficulty（T4 免手报）；显式手报冲突 400。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from test_agents_d4_harness import (
    ArtifactFile,
    FakeScanner,
    api_client,
    prime_run,
    seed_agent,
)
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _persist_project

from fde_api.agents.models import AgentArtifact, AgentRun
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.dispatch.models import DeliveryPackage, PackageAccess
from fde_api.meetings.service import t2_gate_satisfied
from fde_api.projects.events import record_event  # noqa: F401  (口径引用)
from fde_api.solutions.models import ProjectSolution
from fde_api.workbench.models import OperationEvent, Project

from conftest import INITIAL_PASSWORD

_MINUTES_OK = {
    "consensus": [{"text": "评审通过", "source_refs": []}],
    "disputes": [],
    "todos": [],
}


def _user(username: str, role: str = "admin") -> User:
    return User(
        username=f"{username}.{uuid4().hex[:8]}",
        display_name=username,
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )


def _authorized(client, settings, user: User):
    from test_dispatch_p0_r2 import AuthorizedClient  # noqa: PLC0415  (测试互引，沿 r2 先例)

    return AuthorizedClient(client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"})


def _setup(db_session, d4_client, d4_settings):
    """leader(project_lead) + 接单人(fde_engineer) + 项目 + 方案 + agent。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    acceptor = _authorized(d4_client, d4_settings, _user("d8.acceptee", role="fde_engineer"))
    db_session.add(acceptor.user)
    db_session.commit()
    project = _persist_project(db_session, leader.user, code=f"D8A{uuid4().hex[:6]}")
    solution = ProjectSolution(project_id=project.id, name="交付方案", owner_user_id=leader.user.id)
    db_session.add(solution)
    db_session.commit()
    agent = seed_agent(db_session, d4_settings, capability="agent.code.write")
    return leader, acceptor, project, solution, agent


def _package(
    db_session,
    project: Project,
    solution: ProjectSolution,
    *,
    seat_user_id: str,
    accepted: bool = True,
    difficulty: str | None = None,
    agent_assisted: bool = False,
) -> DeliveryPackage:
    package = DeliveryPackage(
        id=solution.id,
        solution_id=solution.id,
        project_id=project.id,
        package_code=f"PKG-{uuid4().hex[:10].upper()}",
        dispatch_status="accepted" if accepted else "draft",
        accepted_at=datetime.now(timezone.utc) if accepted else None,
        accepted_user_id=seat_user_id if accepted else None,
        seat_delivery=seat_user_id if accepted else None,
        difficulty=difficulty,
        agent_assisted=agent_assisted,
    )
    db_session.add(package)
    if accepted:
        # 接单交接的测试等价物：接单人持 delivery 只读授权行（§9.2③——
        # 无授权行对包一律 404，声明后 GET 白名单断言依赖此行）
        db_session.add(
            PackageAccess(
                package_id=package.id,
                user_id=seat_user_id,
                role="delivery",
                granted_at=datetime.now(timezone.utc),
            )
        )
    db_session.commit()
    return package


def _declare(acceptor, package, *, enabled: bool = True):
    return acceptor.post(
        f"/api/v1/dispatch/packages/{package.id}/agent-assisted",
        json={"enabled": enabled},
    )


def _confirmed_ref(db_session, project, leader) -> None:
    from test_goal_d2_s0_closeout import _confirmed_guidance  # noqa: PLC0415

    _confirmed_guidance(
        db_session,
        project,
        leader.user,
        problems=[{"text": "库存数据割裂", "classification": "数据", "source_refs": ["src-1"], "confirmed": True}],
    )


def _seed_t1(leader, project, solution) -> None:
    convened = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": "T1-lite", "solution_id": solution.id},
    )
    assert convened.status_code == 201, convened.json
    sealed = leader.post(f"/api/v1/meetings/{convened.json['data']['id']}/close", json=_MINUTES_OK)
    assert sealed.status_code == 200, sealed.json


def _seed_t2(leader, project, solution) -> None:
    convened = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": "T2-lite", "solution_id": solution.id},
    )
    assert convened.status_code == 201, convened.json
    sealed = leader.post(f"/api/v1/meetings/{convened.json['data']['id']}/close", json=_MINUTES_OK)
    assert sealed.status_code == 200, sealed.json


def _refs_writer(path: str, refs: tuple[str, ...]):
    def factory(run_id, workspace):
        output = Path(workspace) / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / path).write_text("产物正文", encoding="utf-8")
        return FakeScanner([ArtifactFile(path=path, kind="doc", source_refs=refs)])

    return factory


def _start(leader, agent, project, solution, *, difficulty: str | None = None):
    payload: dict[str, Any] = {
        "project_id": project.id,
        "solution_id": solution.id,
        "idempotency_key": f"d8a:{uuid4().hex}",
    }
    if difficulty is not None:
        payload["difficulty"] = difficulty
    return leader.post(f"/api/v1/agents/{agent.id}/run", json=payload)


# ---------------------------------------------------------------------------
# 规则③：未声明态（纯人工交付）
# ---------------------------------------------------------------------------


def test_undeclared_accepted_package_blocks_run(db_session, d4_client, d4_settings) -> None:
    """已接单未声明 → start_run 409 agent_assisted_required（准入闸先于 T1）。"""
    leader, acceptor, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    package = _package(db_session, project, solution, seat_user_id=acceptor.user.id)
    assert package.agent_assisted is False
    _confirmed_ref(db_session, project, leader)
    _seed_t1(leader, project, solution)  # T1 已放行也会被协同准入拦住
    body = _start(leader, agent, project, solution)
    assert body.status_code == 409, body.json
    error = body.json["error"]
    assert error["code"] == "agent_assisted_required"
    assert error["details"]["package_id"] == package.id
    runs = list(db_session.scalars(select(AgentRun).where(AgentRun.project_id == project.id)))
    assert runs == []  # 准入闸在发起前：零 run 落库


def test_undeclared_pre_accept_package_not_blocked(db_session, d4_client, d4_settings, d4_app) -> None:
    """未接单（draft 包）不受协同准入影响——售前段 run 自由（d4–d7 零回归）。"""
    leader, acceptor, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    _package(db_session, project, solution, seat_user_id=acceptor.user.id, accepted=False)
    _confirmed_ref(db_session, project, leader)
    _seed_t1(leader, project, solution)
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    body = _start(leader, agent, project, solution)
    assert body.status_code != 409 or body.json["error"]["code"] != "agent_assisted_required"
    assert body.status_code == 409 and body.json["error"]["code"] == "review_gate_open"


def test_no_package_not_blocked(db_session, d4_client, d4_settings, d4_app) -> None:
    """无交付包（纯售前项目）零感知——T1/T2 门照常（行为与 v0.2.0+ 增量一致）。"""
    leader, _acceptor, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    _confirmed_ref(db_session, project, leader)
    _seed_t1(leader, project, solution)
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    body = _start(leader, agent, project, solution)
    assert body.status_code == 409 and body.json["error"]["code"] == "review_gate_open"


# ---------------------------------------------------------------------------
# 规则③：声明态（显式声明后启用）
# ---------------------------------------------------------------------------


def test_declare_requires_acceptee_role(db_session, d4_client, d4_settings) -> None:
    """规则①：非接单人声明 403 declarer_required（声明权在人）。"""
    leader, acceptor, project, solution, _agent = _setup(db_session, d4_client, d4_settings)
    package = _package(db_session, project, solution, seat_user_id=acceptor.user.id, difficulty="low")
    outsider = _authorized(d4_client, d4_settings, _user("d8.outsider", role="fde_engineer"))
    db_session.add(outsider.user)
    db_session.commit()
    body = _declare(outsider, package)
    assert body.status_code == 403, body.json
    assert body.json["error"]["code"] == "declarer_required"
    # 接单人本人可以声明（对照）
    ok = _declare(acceptor, package)
    assert ok.status_code == 200, ok.json
    assert ok.json["data"]["agent_assisted"] is True


def test_declare_requires_accepted_status(db_session, d4_client, d4_settings) -> None:
    """未接单（draft）包禁止声明 409 package_not_accepted——draft 无接单人，
    非接单人先撞 403 declarer_required（规则①），admin 管理通道才到状态闸。"""
    leader, acceptor, project, solution, _agent = _setup(db_session, d4_client, d4_settings)
    package = _package(db_session, project, solution, seat_user_id=acceptor.user.id, accepted=False, difficulty="low")
    body = _declare(acceptor, package)
    assert body.status_code == 403, body.json  # draft 无接单人：权限闸先拦
    assert body.json["error"]["code"] == "declarer_required"
    admin = _authorized(d4_client, d4_settings, _user("d8.admin2", role="admin"))
    db_session.add(admin.user)
    db_session.commit()
    via_admin = _declare(admin, package)
    assert via_admin.status_code == 409, via_admin.json
    assert via_admin.json["error"]["code"] == "package_not_accepted"
    assert package.dispatch_status == "draft"  # 8 态机零改动


def test_declare_requires_difficulty_defined(db_session, d4_client, d4_settings) -> None:
    """难度未定档禁止声明 409 difficulty_undefined（带入链需要 difficulty）。"""
    leader, acceptor, project, solution, _agent = _setup(db_session, d4_client, d4_settings)
    package = _package(db_session, project, solution, seat_user_id=acceptor.user.id, difficulty=None)
    body = _declare(acceptor, package)
    assert body.status_code == 409, body.json
    assert body.json["error"]["code"] == "difficulty_undefined"


def test_declare_rejects_high_difficulty(db_session, d4_client, d4_settings) -> None:
    """规则④：difficulty=high 禁止协同声明 409 difficulty_excludes_agents
    （O-4 三档处理：难度高=不派发给智能体）。"""
    leader, acceptor, project, solution, _agent = _setup(db_session, d4_client, d4_settings)
    package = _package(db_session, project, solution, seat_user_id=acceptor.user.id, difficulty="high")
    body = _declare(acceptor, package)
    assert body.status_code == 409, body.json
    assert body.json["error"]["code"] == "difficulty_excludes_agents"
    assert package.agent_assisted is False


def test_declare_success_event_idempotent_and_whitelist(db_session, d4_client, d4_settings) -> None:
    """声明成功：列翻转 + OperationEvent 留痕 + 幂等（重复声明只留一条事件）
    + 白名单透出 agent_assisted/difficulty 两键。"""
    leader, acceptor, project, solution, _agent = _setup(db_session, d4_client, d4_settings)
    package = _package(db_session, project, solution, seat_user_id=acceptor.user.id, difficulty="medium")
    first = _declare(acceptor, package)
    assert first.status_code == 200, first.json
    data = first.json["data"]
    assert data["agent_assisted"] is True
    assert data["difficulty"] == "medium"
    assert data["dispatch_status"] == "accepted"  # 8 态机零改动
    second = _declare(acceptor, package)
    assert second.status_code == 200 and second.json["data"]["agent_assisted"] is True
    events = db_session.scalars(
        select(OperationEvent.event_type).where(OperationEvent.target_id == package.id)
    ).all()
    assert events.count("agent_assisted_declared") == 1  # 幂等：不重复留痕
    # 读回白名单（GET）同样透出两键
    read = acceptor.get(f"/api/v1/dispatch/packages/{package.id}")
    assert read.status_code == 200
    assert read.json["data"]["agent_assisted"] is True
    assert read.json["data"]["difficulty"] == "medium"


def test_revoke_declaration_reblocks_runs(db_session, d4_client, d4_settings) -> None:
    """撤销声明：agent_assisted=False + revoked 事件；后续 run 重新被准入闸拦
    （既有 run 不回溯——报告 §二 口径）。"""
    leader, acceptor, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    package = _package(
        db_session, project, solution, seat_user_id=acceptor.user.id, difficulty="low", agent_assisted=True
    )
    body = _declare(acceptor, package, enabled=False)
    assert body.status_code == 200 and body.json["data"]["agent_assisted"] is False
    events = db_session.scalars(
        select(OperationEvent.event_type).where(OperationEvent.target_id == package.id)
    ).all()
    assert "agent_assisted_revoked" in events
    _confirmed_ref(db_session, project, leader)
    _seed_t1(leader, project, solution)
    blocked = _start(leader, agent, project, solution)
    assert blocked.status_code == 409 and blocked.json["error"]["code"] == "agent_assisted_required"


# ---------------------------------------------------------------------------
# 规则④：订单难度自动带入 run.difficulty（T4 免手报）
# ---------------------------------------------------------------------------


def test_difficulty_low_maps_to_standard(db_session, d4_client, d4_settings, d4_app) -> None:
    """声明 low 包：不传 difficulty → run.difficulty=standard（lite 纪要放行，
    全链 201）。"""
    leader, acceptor, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    _package(db_session, project, solution, seat_user_id=acceptor.user.id, difficulty="low", agent_assisted=True)
    _confirmed_ref(db_session, project, leader)
    _seed_t1(leader, project, solution)
    _seed_t2(leader, project, solution)
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    body = _start(leader, agent, project, solution)
    assert body.status_code == 201, body.json
    run = db_session.get(AgentRun, body.json["data"]["id"])
    assert run is not None and run.difficulty == "standard"


def test_difficulty_medium_maps_to_high_and_t4_full(db_session, d4_client, d4_settings, d4_app) -> None:
    """声明 medium 包：不传 difficulty → run.difficulty=high（T4 生效——lite
    纪要拦截，升档 full 后 retry 放行且 run.difficulty=high）。"""
    leader, acceptor, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    _package(db_session, project, solution, seat_user_id=acceptor.user.id, difficulty="medium", agent_assisted=True)
    _confirmed_ref(db_session, project, leader)
    _seed_t1(leader, project, solution)
    _seed_t2(leader, project, solution)  # 侧链 lite 纪要
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    blocked = _start(leader, agent, project, solution)
    assert blocked.status_code == 409 and blocked.json["error"]["code"] == "review_gate_open"
    run_id = blocked.json["error"]["details"]["run_id"]
    first_run = db_session.get(AgentRun, run_id)
    assert first_run is not None and first_run.difficulty == "high"  # 自动带入，无需手报
    # 对该 run 召集 T2-lite（T4 升 full）→ retry 放行
    convened = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": "T2-lite", "triggered_by_run_id": run_id},
    )
    assert convened.status_code == 201
    sealed = leader.post(f"/api/v1/meetings/{convened.json['data']['id']}/close", json=_MINUTES_OK)
    assert sealed.status_code == 200
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    retried = leader.post(f"/api/v1/agents/runs/{run_id}/retry", json={})
    assert retried.status_code == 201, retried.json
    retried_run = db_session.get(AgentRun, retried.json["data"]["id"])
    assert retried_run is not None and retried_run.difficulty == "high"


def test_difficulty_hand_report_conflict_rejected(db_session, d4_client, d4_settings, d4_app) -> None:
    """声明 low 包但显式手报 high → 400 difficulty_order_conflict（透明化，
    不静默覆盖）。"""
    leader, acceptor, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    _package(db_session, project, solution, seat_user_id=acceptor.user.id, difficulty="low", agent_assisted=True)
    _confirmed_ref(db_session, project, leader)
    _seed_t1(leader, project, solution)
    _seed_t2(leader, project, solution)
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    body = _start(leader, agent, project, solution, difficulty="high")
    assert body.status_code == 400, body.json
    error = body.json["error"]
    assert error["code"] == "difficulty_order_conflict"
    assert error["details"]["order_difficulty"] == "low"
    assert error["details"]["run_difficulty"] == "standard"


def test_difficulty_hand_report_match_passes(db_session, d4_client, d4_settings, d4_app) -> None:
    """显式手报与订单映射一致（low+standard）→ 正常放行（免手报≠禁手报）。"""
    leader, acceptor, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    _package(db_session, project, solution, seat_user_id=acceptor.user.id, difficulty="low", agent_assisted=True)
    _confirmed_ref(db_session, project, leader)
    _seed_t1(leader, project, solution)
    _seed_t2(leader, project, solution)
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    body = _start(leader, agent, project, solution, difficulty="standard")
    assert body.status_code == 201, body.json
    run = db_session.get(AgentRun, body.json["data"]["id"])
    assert run is not None and run.difficulty == "standard"


# ---------------------------------------------------------------------------
# 规则①：8 态机零改动 + 规则②：降级兼容 + 溯源联动
# ---------------------------------------------------------------------------


def test_declare_never_touches_transitions(db_session, d4_client, d4_settings) -> None:
    """规则①：声明/撤销前后 dispatch_status、TRANSITIONS 表零改动（同包
    状态守恒）。"""
    from fde_api.dispatch.packages import TRANSITIONS

    leader, acceptor, project, solution, _agent = _setup(db_session, d4_client, d4_settings)
    package = _package(db_session, project, solution, seat_user_id=acceptor.user.id, difficulty="low")
    before = package.dispatch_status
    _declare(acceptor, package, enabled=True)
    _declare(acceptor, package, enabled=False)
    _declare(acceptor, package, enabled=True)
    assert package.dispatch_status == before == "accepted"
    # TRANSITIONS 是模块级表——声明动作纯列翻转，不注册新迁移路径
    assert TRANSITIONS["publish"]["draft"] == "published"


def test_rule2_degraded_family_still_gated_on_assisted_package(db_session, d4_client, d4_settings) -> None:
    """规则②：协同包上 L1 降级 run 家族照常触发 T5 门语义（协同列绝不旁路
    降级链——降级产物不自动放行）。"""
    leader, acceptor, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    _package(db_session, project, solution, seat_user_id=acceptor.user.id, difficulty="low", agent_assisted=True)
    l1_run = AgentRun(
        project_id=project.id,
        agent_id=agent.id,
        initiated_by_user_id=leader.user.id,
        capability_used=agent.capability_tier,
        status="completed",
        degraded=True,
        degraded_reason="tool_denied",
        fallback_level="L1",
        context_ref="agent-workspaces/x/context.md",
        idempotency_key=f"d8l1:{uuid4().hex}",
    )
    db_session.add(l1_run)
    db_session.commit()
    # 无 T5 补审纪要 → 门不开（协同包上语义与 d7 完全一致）
    assert t2_gate_satisfied(db_session, run_id=l1_run.id, solution_id=solution.id) is False


def test_traceability_package_solution_artifact_chain(db_session, d4_client, d4_settings, d4_app) -> None:
    """溯源联动三点成链：包 id == solution.id；start_run 带 solution 产物
    artifact.linked_solution_id 直达包（零新表）。"""
    leader, acceptor, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    package = _package(
        db_session, project, solution, seat_user_id=acceptor.user.id, difficulty="low", agent_assisted=True
    )
    assert package.id == solution.id  # 包↔方案同键（r3 结构事实）
    _confirmed_ref(db_session, project, leader)
    _seed_t1(leader, project, solution)
    _seed_t2(leader, project, solution)
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    body = _start(leader, agent, project, solution)
    assert body.status_code == 201, body.json
    artifact = db_session.scalar(
        select(AgentArtifact).where(AgentArtifact.run_id == body.json["data"]["id"])
    )
    assert artifact is not None
    assert artifact.linked_solution_id == package.id  # run→artifact→solution→package


# ---------------------------------------------------------------------------
# 发布定档（difficulty 随发布冻结进白名单）
# ---------------------------------------------------------------------------


def test_publish_sets_difficulty_and_validates(db_session, d4_client, d4_settings) -> None:
    """发布时平台侧定档：difficulty=low 落列透白名单；非法档位 400（draft 态
    路由层校验，不触状态机）。"""
    from test_dispatch_p0_r2 import _quote  # noqa: PLC0415


    leader, acceptor, project, solution, _agent = _setup(db_session, d4_client, d4_settings)
    quote = _quote(db_session, project)
    admin = _authorized(d4_client, d4_settings, _user("d8.admin", role="admin"))
    db_session.add(admin.user)
    db_session.commit()
    # ORM 直建 draft 包（create_package 的派单线渠道守卫属 r7 语义，不在本验收）
    package = DeliveryPackage(
        id=solution.id,
        solution_id=solution.id,
        project_id=project.id,
        package_code=f"PKG-{uuid4().hex[:10].upper()}",
        quote_id=quote.id,
        dispatch_status="draft",
    )
    db_session.add(package)
    db_session.commit()
    bad = admin.post(
        f"/api/v1/dispatch/packages/{package.id}/publish",
        json={"difficulty": "extreme"},
    )
    assert bad.status_code == 400 and bad.json["error"]["code"] == "invalid_request"
    assert package.difficulty is None
    published = admin.post(
        f"/api/v1/dispatch/packages/{package.id}/publish",
        json={"difficulty": "low"},
    )
    assert published.status_code == 200, published.json
    assert published.json["data"]["difficulty"] == "low"
    assert published.json["data"]["dispatch_status"] == "published"
