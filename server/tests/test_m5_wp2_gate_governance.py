"""V3.3 M5-WP2②③④：S-13 证据引用强验 + GateEvaluationReceipt + S-16/S-12 + 验收契约（TDD）。

契约依据 = Fde-Ontology ``docs/v3.3/m5/00-m5-work-order.md`` WP2 行 + D29 决策 + 集成契约 §9.2：
- ② 唯一 DDL 迁移：project_evidence S-13 五列（org/绑定强验、唯一键不互踩）、
  gate_evaluation_receipts 快照回执（不可变）、acceptance_contracts 契约实体、
  ontology_terms.promoted_readonly/promoted_at 晋升锚点；
- ③ gate_service 集成 AcceptanceContract 与本体辅助校验（只卡 D31 处置闭环；
  Agent 禁改 Gate 状态——回执 decided_by + ORM 守卫）；
- ④ S-16 双层枚举（strong|weak|per_gate → required|optional|none）+ S-12 防降级旁路锁
  （Owner 异人审批 + 熔断窗口禁下调 + operation_events 留痕）。

审计映射默认假设：工作令所称 ``audit_events`` 落本仓唯一审计事件表
``operation_events``（record_event）；「项目 Owner」= ``Project.leader_user_id``
（admin 平台位同权）；「异人」= 操作人 ≠ 依赖等级基线建档人。
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import UniqueConstraint, select

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.evidence.models import ProjectEvidence
from fde_api.integrations.models import ProjectOntologyBinding
from fde_api.integrations.ontology_mock import (
    M5_SEED_VERSION_ID,
    MockOntologyAdapter,
    SEED_ONTOLOGY_ID,
)
from fde_api.ontology.models import OntologyTerm
from fde_api.projects.gate_receipt import (
    AcceptanceContract,
    GateEvaluationReceipt,
    verify_receipt,
)
from fde_api.workbench.models import Gate, OperationEvent, Project
from fde_api.workbench.seed import GENERIC_TEMPLATE_KEY, seed_workbench

from conftest import INITIAL_PASSWORD
from test_gates_api import AuthorizedClient  # noqa: F401  (pytest fixture 供给方)
from test_gates_api import admin_client, gate_project  # noqa: F401  (pytest fixture)

M5_INDUSTRY_ONT = "ont-m5-mfg-quality"


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def m5_env(gate_project, client, db_session, settings):
    """(project, gates_url, leader_client) + admin 执行人客户端 + 活跃本体绑定。"""
    from test_gates_api import AuthorizedClient

    project, gates_url, leader_client = gate_project
    admin = db_session.scalar(select(User).where(User.username == "gate.admin"))
    assert admin is not None
    admin_client = AuthorizedClient(
        client, admin, {"Authorization": f"Bearer {issue_access_token(admin, settings)}"}
    )
    # 响应 dict 不投影 org_id——org 归属从 DB 行取（projects.org_id，D10 段 2）
    project_row = db_session.get(Project, project["id"])
    assert project_row is not None
    binding = ProjectOntologyBinding(
        org_id=project_row.org_id,
        project_id=project["id"],
        ontology_id=SEED_ONTOLOGY_ID,
        pinned_version_id=M5_SEED_VERSION_ID,
        pinned_version="1.1.0",
        binding_role="primary",
        status="active",
        active_marker="active",
        bound_by_user_id=admin.id,
    )
    db_session.add(binding)
    db_session.commit()
    return {
        "project": project,
        "org_id": project_row.org_id,
        "gates_url": gates_url,
        "leader": leader_client,
        "admin": admin_client,
        "binding": binding,
        "mock": MockOntologyAdapter(),
    }


def _mock_client_factory(mock: MockOntologyAdapter):
    return lambda: mock


def _submit_gate_evidence(env, gate_key: str) -> None:
    """admin 执行人全量提交门禁证据（claimed），拍板留给 leader（P0-5 异人）。"""
    _submit_evidence_as(env, gate_key, env["admin"])


def _submit_evidence_as(env, gate_key: str, who) -> None:
    """指定执行人客户端全量提交门禁证据（claimed），拍板留给异人（P0-5）。"""
    gates = who.get(env["gates_url"]).json["data"]["gates"]
    gate = next(g for g in gates if g["gate_key"] == gate_key)
    response = who.post(
        f"{env['gates_url']}/{gate_key}/evidence",
        json={
            "items": [
                {
                    "label": item["label"],
                    "source_uri": f"fdeops://p3/{gate_key}",
                    "content_hash": hashlib.sha256(item["label"].encode()).hexdigest(),
                }
                for item in gate["checklist"]
            ]
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)


def _decide(env, gate_key: str, payload: dict[str, Any]):
    return env["leader"].post(f"{env['gates_url']}/{gate_key}/decision", json=payload)


# ---------------------------------------------------------------- ② 迁移与 ORM


def test_wp2_migration_columns_exist(db_session) -> None:
    """唯一迁移 DDL 落库：S-13 五列 / Gate 两列 / 回执表 / 契约表 / 晋升锚点。"""
    ev = ProjectEvidence(
        project_id="p-x", kind="gate", source_uri="u", content_sha256="a" * 64
    )
    assert ev.ontology_id is None
    assert ev.pinned_version_id is None
    assert ev.object_ref_id is None
    assert ev.action_request_id is None
    assert ev.logic_eval_digest is None

    gate_cols = {c.name for c in Gate.__table__.columns}
    assert {"ontology_dependency", "ontology_dependency_baseline_by_user_id"} <= gate_cols

    receipt_cols = {c.name for c in GateEvaluationReceipt.__table__.columns}
    assert {
        "id", "project_id", "gate_id", "gate_key", "revision", "result", "decision",
        "input_snapshot_json", "input_snapshot_sha256", "ontology_checks_json",
        "ontology_degradation", "decided_by_user_id", "decided_at", "receipt_sha256",
    } <= receipt_cols

    # 契约独立实体（吸收并行评审亮点：可独立建档/换版，acceptor 按**角色**判定，
    # 换人不失效；回执只固化快照）
    contract_cols = {c.name for c in AcceptanceContract.__table__.columns}
    assert {
        "id", "project_id", "gate_key", "items_json", "rule_refs_json",
        "acceptor_role", "sla_hours", "status", "created_by_user_id",
    } <= contract_cols

    term_cols = {c.name for c in OntologyTerm.__table__.columns}
    assert {"promoted_readonly", "promoted_at"} <= term_cols
    assert OntologyTerm.__table__.c.promoted_readonly.default.arg is False


def test_evidence_unique_fingerprint_not_polluted_by_ref(db_session) -> None:
    """工作令防互踩：S-13 引用列不进 (project_id, source_uri, content_sha256) 唯一键。"""
    uq = next(
        c for c in ProjectEvidence.__table__.constraints  # type: ignore[attr-defined]
        if isinstance(c, UniqueConstraint)
    )
    assert set(uq.columns.keys()) == {"project_id", "source_uri", "content_sha256"}


# ---------------------------------------------------------------- ② S-13 证据引用强验


def test_evidence_ontology_ref_pinned_to_active_binding(m5_env) -> None:
    """引用钉住活跃绑定版本 → 五列落库；引用未钉版本 → 400 防跨租户注入。"""
    env = m5_env
    pid = env["project"]["id"]
    ok = env["admin"].post(
        f"/api/v1/projects/{pid}/evidence",
        json={
            "kind": "gate",
            "source_uri": "fdeops://m5/ref-ok",
            "content_sha256": "b" * 64,
            "ontology_ref": {
                "ontology_id": SEED_ONTOLOGY_ID,
                "pinned_version_id": M5_SEED_VERSION_ID,
                "object_ref_id": "ref-obj-1",
            },
        },
    )
    assert ok.status_code == 201, ok.get_data(as_text=True)
    body = ok.json["data"]["evidence"]
    assert body["ontology_id"] == SEED_ONTOLOGY_ID
    assert body["pinned_version_id"] == M5_SEED_VERSION_ID
    assert body["object_ref_id"] == "ref-obj-1"
    assert body["action_request_id"] is None

    bad = env["admin"].post(
        f"/api/v1/projects/{pid}/evidence",
        json={
            "kind": "gate",
            "source_uri": "fdeops://m5/ref-bad",
            "content_sha256": "c" * 64,
            "ontology_ref": {
                "ontology_id": "ont-other-tenant",
                "pinned_version_id": "ver-other",
            },
        },
    )
    assert bad.status_code == 400
    assert bad.json["error"]["code"] == "ontology_ref_not_pinned"


def test_evidence_ref_idempotent_fingerprint_keeps_first_ref(m5_env, db_session) -> None:
    """同指纹重复登记幂等（created=false）且首建引用不被改写（证据不可变纪律）。"""
    env = m5_env
    pid = env["project"]["id"]
    payload = {
        "kind": "gate",
        "source_uri": "fdeops://m5/idem",
        "content_sha256": "d" * 64,
        "ontology_ref": {
            "ontology_id": SEED_ONTOLOGY_ID,
            "pinned_version_id": M5_SEED_VERSION_ID,
        },
    }
    first = env["admin"].post(f"/api/v1/projects/{pid}/evidence", json=payload)
    assert first.status_code == 201
    second = env["admin"].post(f"/api/v1/projects/{pid}/evidence", json=payload)
    assert second.status_code == 200
    assert second.json["data"]["created"] is False
    row = db_session.scalar(
        select(ProjectEvidence).where(ProjectEvidence.source_uri == "fdeops://m5/idem")
    )
    assert row.ontology_id == SEED_ONTOLOGY_ID


# ---------------------------------------------------------------- ③ GateEvaluationReceipt


def test_receipt_frozen_on_decide_and_immutable(m5_env, db_session, monkeypatch) -> None:
    """拍板生效即固化回执（快照哈希 + 降级态）；改写/删除在 flush 前响亮失败。"""
    env = m5_env
    _settings_with(env, ontology_gate_dependency="per_gate")
    monkeypatch.setattr(
        "fde_api.projects.gate_ontology.client_from_settings",
        _mock_client_factory(env["mock"]),
    )
    _submit_gate_evidence(env, "G5")
    resp = _decide(env, "G5", {"result": "pass"})
    assert resp.status_code == 200, resp.get_data(as_text=True)

    receipts = list(
        db_session.scalars(
            select(GateEvaluationReceipt).where(
                GateEvaluationReceipt.project_id == env["project"]["id"]
            )
        )
    )
    assert len(receipts) == 1
    rec = receipts[0]
    assert rec.gate_key == "G5"
    assert rec.result == "pass"
    assert rec.ontology_degradation in ("online", "degraded", "skipped", "disabled")
    # 快照哈希可重放验真
    assert verify_receipt(rec) is True
    # 篡改快照 → 验真失败
    rec.input_snapshot_json = dict(rec.input_snapshot_json, tampered=True)
    assert verify_receipt(rec) is False

    # ORM 不可变守卫：改写/删除在 flush 前响亮失败（db_session 自动 flush 于查询前，
    # 此处显式 flush 触发守卫）
    with pytest.raises(RuntimeError, match="immutable"):
        db_session.flush()


def _settings_with(env, **overrides: Any):
    """返回当前测试 app 的 Settings 对象并就地覆盖（function 级 fixture 同对象）。"""
    from fde_api.extensions import db  # noqa: F401  (确保 app 上下文已建立)

    settings = env["leader"].client.application.config["SETTINGS"]
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


# ---------------------------------------------------------------- ④ S-16 三档降级


@pytest.mark.parametrize(
    ("global_dep", "gate_dep", "fault", "expect_status", "expect_degradation"),
    [
        # strong：runtime 不可用 → 门禁暂停（409），不产回执
        ("strong", None, "unavailable", 409, None),
        # weak：不可用 → 原规则运行 + degraded 标注（S-16 表：原规则+标注未校验）
        ("weak", None, "unavailable", 200, "degraded"),
        # per_gate + 单门禁 required：同 strong 暂停
        ("per_gate", "required", "unavailable", 409, None),
        # per_gate + optional：降级放行
        ("per_gate", "optional", "unavailable", 200, "degraded"),
        # per_gate + none：跳过本体校验（零出站调用）
        ("per_gate", "none", None, 200, "skipped"),
    ],
)
def test_s16_dependency_tiers(
    m5_env, db_session, monkeypatch, global_dep, gate_dep, fault, expect_status, expect_degradation
) -> None:
    env = m5_env
    _settings_with(env, ontology_gate_dependency=global_dep, ontology_enabled=True)
    if gate_dep is not None:
        gate_row = db_gate(env, "G5", db_session)
        gate_row.ontology_dependency = gate_dep
        db_session.commit()
    mock = env["mock"]
    mock.inject_fault(fault)
    monkeypatch.setattr(
        "fde_api.projects.gate_ontology.client_from_settings", _mock_client_factory(mock)
    )
    _submit_gate_evidence(env, "G5")
    resp = _decide(env, "G5", {"result": "pass"})
    assert resp.status_code == expect_status, resp.get_data(as_text=True)
    if expect_status == 409:
        assert resp.json["error"]["code"] == "gate_ontology_unavailable"
        return
    # 放行路径：回执降级态透明标注
    rec = latest_receipt(env)
    assert rec.ontology_degradation == expect_degradation


def test_s16_disabled_flag_skips_all_checks(m5_env, monkeypatch) -> None:
    """ontology_enabled=False（D12 门控）→ degradation=disabled，零出站零阻断。"""
    env = m5_env
    _settings_with(env, ontology_gate_dependency="strong", ontology_enabled=False)

    def _boom() -> MockOntologyAdapter:
        raise AssertionError("disabled 时不得出站调用 runtime")

    monkeypatch.setattr(
        "fde_api.projects.gate_ontology.client_from_settings", _boom
    )
    _submit_gate_evidence(env, "G5")
    resp = _decide(env, "G5", {"result": "pass"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert latest_receipt(env).ontology_degradation == "disabled"


def test_s16_config_validator_rejects_unknown_tier() -> None:
    """S-16 全局枚举启动闸：非 strong|weak|per_gate 一律启动即炸（沿商业口径先例）。"""
    from fde_api.config import Settings

    # Settings 必填字段（env/database/redis/jwt）——沿 test_ontology_config 惯例
    base = {
        "env": "test",
        "database_url": "postgresql+psycopg://u:p@127.0.0.1:5432/x",
        "redis_url": "redis://127.0.0.1:6379/2",
        "jwt_secret": "test-secret-with-at-least-thirty-two-characters",
    }
    # **kwargs 展开进 pydantic-settings 无法被类型桩精确建模（惯例同 test_ontology_config）
    with pytest.raises(ValueError):
        Settings(ontology_gate_dependency="bogus", **base)  # type: ignore[arg-type]
    ok = Settings(ontology_gate_dependency="per_gate", **base)  # type: ignore[arg-type]
    assert ok.ontology_gate_dependency == "per_gate"


# ---------------------------------------------------------------- ④ S-12 防降级旁路锁


def test_s12_downgrade_requires_owner_and_other_person(m5_env, db_session, monkeypatch) -> None:
    """下调三闸：Owner（leader/admin）+ 异于基线建档人 + 熔断窗口禁生效；收紧自由。"""
    from fde_api.projects.gate_ontology import GateOntologyError, set_gate_dependency

    env = m5_env
    project = env["project"]
    leader = env["leader"].user
    gate = db_gate(env, "G5", db_session)

    # 建档：首次显式设置自由（任何 manage 位），基线建档人 = admin
    admin = env["admin"].user
    set_gate_dependency(
        db_session, actor=admin, project_id=project["id"], gate=gate, new_level="required"
    )
    assert gate.ontology_dependency == "required"
    assert gate.ontology_dependency_baseline_by_user_id == admin.id

    # 同人下调 → 403 same_person_forbidden（异人闸）
    with pytest.raises(GateOntologyError) as same:
        set_gate_dependency(
            db_session, actor=admin, project_id=project["id"], gate=gate, new_level="optional"
        )
    assert same.value.code == "same_person_forbidden"

    # 非 Owner（fde_engineer）下调 → 403 owner_required（即便异人）
    engineer = _make_user(db_session, role="fde_engineer")
    with pytest.raises(GateOntologyError) as not_owner:
        set_gate_dependency(
            db_session, actor=engineer, project_id=project["id"], gate=gate, new_level="optional"
        )
    assert not_owner.value.code == "owner_required"

    # Owner 异人下调 + 熔断窗口 → 409 circuit_open_no_downgrade
    with pytest.raises(GateOntologyError) as circuit:
        set_gate_dependency(
            db_session,
            actor=leader,
            project_id=project["id"],
            gate=gate,
            new_level="optional",
            breaker_open=True,
        )
    assert circuit.value.code == "circuit_open_no_downgrade"

    # Owner 异人下调（无熔断）→ 通过 + operation_events 留痕
    event_count_before = _dep_event_count(db_session, project["id"])
    out = set_gate_dependency(
        db_session, actor=leader, project_id=project["id"], gate=gate, new_level="optional"
    )
    assert out["from_level"] == "required" and out["to_level"] == "optional"
    assert _dep_event_count(db_session, project["id"]) == event_count_before + 1
    # id 是随机 UUID 字符串——id.desc() 不是时间序，建档/下调事件同名，
    # 必须按 changes.action 过滤做确定性断言（不依赖任何排序）
    dep_events = list(
        db_session.scalars(
            select(OperationEvent).where(
                OperationEvent.project_id == project["id"],
                OperationEvent.event_type == "gate_ontology_dependency_changed",
            )
        )
    )
    downgrades = [e for e in dep_events if e.changes.get("action") == "downgrade"]
    assert len(downgrades) == 1
    assert downgrades[0].changes["from_level"] == "required"
    assert downgrades[0].changes["to_level"] == "optional"

    # 收紧（升级）自由：fde_engineer 也可 optional → required
    out2 = set_gate_dependency(
        db_session, actor=engineer, project_id=project["id"], gate=gate, new_level="required"
    )
    assert out2["to_level"] == "required"
    # 基线建档人不因收紧改变
    assert gate.ontology_dependency_baseline_by_user_id == admin.id


def test_s12_invalid_level_rejected(m5_env, db_session) -> None:
    from fde_api.projects.gate_ontology import GateOntologyError, set_gate_dependency

    env = m5_env
    with pytest.raises(GateOntologyError) as bad:
        set_gate_dependency(
            db_session,
            actor=env["admin"].user,
            project_id=env["project"]["id"],
            gate=db_gate(env, "G5", db_session),
            new_level="bogus",
        )
    assert bad.value.code == "invalid_request"


# ---------------------------------------------------------------- ③ AcceptanceContract


def test_acceptance_contract_role_and_items_enforced(m5_env, db_session, monkeypatch) -> None:
    """契约闸：过门须 acceptor 角色拍板；契约快照固化进回执。

    闸序（decide_gate）：权限(manage) → P0-5 异人 → 本体契约角色闸。能过 manage
    闸的只有 admin 与 leader 位——故 G5 用 leader 提交 + admin 拍板（异人过
    P0-5，platform role=admin ≠ acceptor_role → 契约闸 403）；G6 用 admin 提交
    + leader（project_lead）拍板走正向，契约快照进回执。
    """
    env = m5_env
    _settings_with(env, ontology_gate_dependency="per_gate")
    monkeypatch.setattr(
        "fde_api.projects.gate_ontology.client_from_settings",
        _mock_client_factory(env["mock"]),
    )
    for gate_key in ("G5", "G6"):
        gate = db_gate(env, gate_key, db_session)
        labels = [item["label"] for item in gate.evidence_checklist]
        db_session.add(
            AcceptanceContract(
                project_id=env["project"]["id"],
                gate_key=gate_key,
                items_json=labels,
                rule_refs_json=[f"{gate_key}.quantified"],
                acceptor_role="project_lead",
                sla_hours=72,
                status="active",
                created_by_user_id=env["admin"].user.id,
            )
        )
    db_session.commit()

    # G5：leader 提交（执行人=leader），admin 拍板——P0-5 过（异人），
    # 契约闸拦 platform role=admin ≠ acceptor_role=project_lead → 403
    _submit_evidence_as(env, "G5", env["leader"])
    blocked = env["admin"].post(f"{env['gates_url']}/G5/decision", json={"result": "pass"})
    assert blocked.status_code == 403, blocked.get_data(as_text=True)
    assert blocked.json["error"]["code"] == "gate_acceptor_role_required"

    # G6：admin 提交（执行人=admin），project_lead（契约 acceptor 角色）拍板
    # → 过门，契约快照进回执输入快照
    _submit_evidence_as(env, "G6", env["admin"])
    resp2 = _decide(env, "G6", {"result": "pass"})
    assert resp2.status_code == 200, resp2.get_data(as_text=True)
    rec = latest_receipt(env)
    snap = rec.input_snapshot_json
    assert snap["acceptance_contract"]["acceptor_role"] == "project_lead"
    # 快照键与契约列名同形（sla_hours）；争议 SLA 语义不变
    assert snap["acceptance_contract"]["sla_hours"] == 72
    assert snap["acceptance_contract"]["gate_key"] == "G6"


# ---------------------------------------------------------------- ③ D31 处置闸


def test_d31_disposition_gate_blocks_required_when_undisposed(
    m5_env, db_session, monkeypatch
) -> None:
    """D31 古德哈特护栏：required 门禁只卡「<0.8/冲突候选 100% 人工处置」；
    处置闭环后绿灯——免改/精修/驳回均不算阻断项。"""
    env = m5_env
    # D31 是本体可用（online）路径的处置闸——必须显式开启本体面（D12 门控，
    # 缺省 False 会整段走 disabled 短路、闸不触发）
    _settings_with(env, ontology_gate_dependency="per_gate", ontology_enabled=True)
    mock = env["mock"]
    # 让种子候选归属测试项目 org（Mock 按 org 过滤）
    for cs in mock._change_sets.values():
        cs["org_id"] = env["org_id"]
    monkeypatch.setattr(
        "fde_api.projects.gate_ontology.client_from_settings", _mock_client_factory(mock)
    )
    gate_row = db_gate(env, "G5", db_session)
    gate_row.ontology_dependency = "required"
    db_session.commit()

    _submit_gate_evidence(env, "G5")
    blocked = _decide(env, "G5", {"result": "pass"})
    assert blocked.status_code == 409
    assert blocked.json["error"]["code"] == "gate_ontology_disposition_open"

    # 处置闭环（draft 候选完成人工处置）→ 绿灯
    mock._change_sets["cs-m5-draft"]["status"] = "approved"
    resp = _decide(env, "G5", {"result": "pass"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    rec = latest_receipt(env)
    assert rec.ontology_checks_json["candidate_disposition"]["all_disposed"] is True


# ---------------------------------------------------------------- helpers


def db_gate(env, gate_key: str, session) -> Gate:
    """取门禁行（必须传 fixture 的 ``db_session``——测试体内 ``db.session()``
    的作用域随 app context 变化，与 fixture session 不同，改动不会落库）。"""
    row = session.scalar(
        select(Gate).where(
            Gate.project_id == env["project"]["id"], Gate.gate_key == gate_key
        )
    )
    if row is None:
        # gates 懒实例化（list 入口首次建 9 门）——先触发再取行
        env["leader"].get(env["gates_url"])
        session.expire_all()
        row = session.scalar(
            select(Gate).where(
                Gate.project_id == env["project"]["id"], Gate.gate_key == gate_key
            )
        )
    assert row is not None
    return row


def latest_receipt(env) -> GateEvaluationReceipt:
    from fde_api.extensions import db

    session = db.session()
    row = session.scalar(
        select(GateEvaluationReceipt)
        .where(GateEvaluationReceipt.project_id == env["project"]["id"])
        .order_by(GateEvaluationReceipt.created_at.desc(), GateEvaluationReceipt.id.desc())
    )
    assert row is not None
    return row


def _make_user(db_session, *, role: str) -> User:
    user = User(
        username=f"m5.{role}.{uuid4().hex[:8]}",
        display_name=f"M5 {role}",
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _dep_event_count(db_session, project_id: str) -> int:
    return len(
        list(
            db_session.scalars(
                select(OperationEvent).where(
                    OperationEvent.project_id == project_id,
                    OperationEvent.event_type == "gate_ontology_dependency_changed",
                )
            )
        )
    )
