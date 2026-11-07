"""模拟场景库 API（V3.2 G2）。

钉住：
1. **CRUD + 版本语义**：创建 → 列表/详情；编辑**追加新版本**（既有版本不可变）；
   复制 → 新业务键；归档 → 追加 archived 新版本。
2. **导入导出**：批量导入逐条校验（非法条目不阻断其余条目，错误逐条回显）；
   导出返回有效版本。
3. **权限**：读与写都要求 project_operator 档（fde_engineer 及以上）；
   viewer（assistant_read 档）403。
4. **校验失败即 422**：错误码稳定可断言（scenario_key_mismatch / rubric_incomplete …）。
5. **隔离**：场景数据不落 projects 表（本模块零项目写入）。
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from conftest import INITIAL_PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.simulation.models import SimulationScenario
from fde_api.workbench.models import OperationEvent


@dataclass(frozen=True)
class _Client:
    client: object
    user: User
    headers: dict[str, str]

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)

    def patch(self, *args, **kwargs):
        return self.client.patch(*args, headers=self.headers, **kwargs)


def _make_client(client, db_session, settings, *, role: str) -> _Client:
    user = User(
        username=f"sim.{role}.{uuid4().hex[:8]}",
        display_name="Simulation user",
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return _Client(client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"})


@pytest.fixture
def operator(client, db_session, settings):
    return _make_client(client, db_session, settings, role="fde_engineer")


@pytest.fixture
def viewer(client, db_session, settings):
    return _make_client(client, db_session, settings, role="viewer")


@pytest.fixture(autouse=True)
def _clean_scenarios(db_session):
    """场景表不在 conftest 的公共清理清单里（避免改共享文件）⇒ 本模块自清理。"""
    yield
    db_session.rollback()
    db_session.execute(delete(SimulationScenario))
    db_session.commit()


def _case_payload(case_code: str = "CASE-TEST-001", **overrides):
    payload = {
        "name": "测试案例",
        "industry": "general_manufacturing",
        "variant": "normal",
        "split": "train",
        "content": {
            "case_code": case_code,
            "customer_profile": {
                "company_type": "测试用制造企业",
                "stakeholders": ["生产经理"],
                "maturity": "基础台账",
            },
            "visible": {
                "initial_brief": ["设备经常坏，找不到原因"],
                "known_systems": ["ERP"],
                "constraints": {"budget": "10 万", "timeline": "1 个月"},
            },
            "hidden": {
                "facts": [
                    {
                        "fact_id": "T-F1",
                        "text": "维修记录是纸质的",
                        "category": "knowledge",
                        "disclosure_stage": "interview",
                        "probe_keywords": ["记录", "维修"],
                    }
                ]
            },
            "misleading_request": "上 AI 预测性维护",
        },
        "reference": {
            "expected_outcomes": ["识别真问题是知识缺失而非算法缺失"],
            "acceptance_criteria": ["验收标准可度量"],
            "rubric": {
                "must_identify": ["知识采集前置"],
                "must_avoid": ["以模型精度为核心承诺"],
                "must_produce": ["知识采集方案"],
            },
        },
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CRUD + 版本
# ---------------------------------------------------------------------------


def test_create_scenario_returns_version_one(operator):
    response = operator.post("/api/v1/simulation/scenarios", json=_case_payload())
    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["version"] == 1
    assert data["variant"] == "normal"
    assert data["scenario_key"] == "CASE-TEST-001"
    assert data["content"]["hidden"]["facts"]


def test_list_scenarios_returns_created_case(operator):
    operator.post("/api/v1/simulation/scenarios", json=_case_payload())
    response = operator.get("/api/v1/simulation/scenarios")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["total"] >= 1
    assert any(item["scenario_key"] == "CASE-TEST-001" for item in data["items"])


def test_update_appends_a_new_version_and_keeps_the_old_one(operator):
    created = operator.post(
        "/api/v1/simulation/scenarios", json=_case_payload()
    ).get_json()["data"]
    scenario_id = created["id"]

    payload = {"name": "测试案例（改）"}
    response = operator.patch(f"/api/v1/simulation/scenarios/{scenario_id}", json=payload)
    assert response.status_code == 201
    updated = response.get_json()["data"]
    assert updated["version"] == 2
    assert updated["name"] == "测试案例（改）"

    # 既有版本仍可读（不可变）
    original = operator.get(f"/api/v1/simulation/scenarios/{scenario_id}").get_json()["data"]
    assert original["version"] == 1
    assert original["name"] == "测试案例"


def test_duplicate_creates_a_new_scenario_key(operator):
    created = operator.post(
        "/api/v1/simulation/scenarios", json=_case_payload()
    ).get_json()["data"]
    response = operator.post(
        f"/api/v1/simulation/scenarios/{created['id']}/duplicate",
        json={"scenario_key": "CASE-TEST-001-COPY"},
    )
    assert response.status_code == 201
    copy_data = response.get_json()["data"]
    assert copy_data["scenario_key"] == "CASE-TEST-001-COPY"
    assert copy_data["version"] == 1
    assert copy_data["status"] == "draft"
    assert copy_data["content"]["case_code"] == "CASE-TEST-001-COPY"


def test_archive_appends_archived_version(operator):
    created = operator.post(
        "/api/v1/simulation/scenarios", json=_case_payload()
    ).get_json()["data"]
    response = operator.post(f"/api/v1/simulation/scenarios/{created['id']}/archive")
    assert response.status_code == 200
    archived = response.get_json()["data"]
    assert archived["status"] == "archived"
    assert archived["version"] == 2


def test_versions_endpoint_lists_history(operator):
    created = operator.post(
        "/api/v1/simulation/scenarios", json=_case_payload()
    ).get_json()["data"]
    operator.patch(f"/api/v1/simulation/scenarios/{created['id']}", json={"name": "改"})
    response = operator.get(f"/api/v1/simulation/scenarios/{created['id']}/versions")
    assert response.status_code == 200
    versions = response.get_json()["data"]["items"]
    assert [item["version"] for item in versions] == [1, 2]


# ---------------------------------------------------------------------------
# 导入导出
# ---------------------------------------------------------------------------


def test_import_reports_failures_without_blocking_valid_rows(operator):
    good = _case_payload("CASE-IMPORT-OK")
    bad = _case_payload("CASE-IMPORT-BAD")
    bad["reference"]["rubric"]["must_identify"] = []
    response = operator.post(
        "/api/v1/simulation/scenarios/import",
        json={"scenarios": [good, bad]},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["created_count"] == 1
    assert len(data["failures"]) == 1
    assert data["failures"][0]["index"] == 1
    assert "rubric_incomplete" in data["failures"][0]["detail"]["errors"]


def test_export_returns_effective_versions(operator):
    operator.post("/api/v1/simulation/scenarios", json=_case_payload())
    response = operator.get("/api/v1/simulation/scenarios/export")
    assert response.status_code == 200
    items = response.get_json()["data"]["items"]
    assert any(item["scenario_key"] == "CASE-TEST-001" for item in items)
    exported = next(i for i in items if i["scenario_key"] == "CASE-TEST-001")
    assert exported["reference"]["rubric"]["must_identify"]


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------


def test_viewer_cannot_read_the_scenario_library(viewer):
    response = viewer.get("/api/v1/simulation/scenarios")
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "forbidden"


def test_viewer_cannot_create_a_scenario(viewer):
    response = viewer.post("/api/v1/simulation/scenarios", json=_case_payload())
    assert response.status_code == 403


def test_unauthenticated_request_is_rejected(client):
    response = client.get("/api/v1/simulation/scenarios")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------


def test_invalid_scenario_is_rejected_with_stable_error_codes(operator):
    payload = _case_payload("CASE-MISMATCH")
    payload["scenario_key"] = "CASE-SOMETHING-ELSE"
    response = operator.post("/api/v1/simulation/scenarios", json=payload)
    assert response.status_code == 422
    error = response.get_json()["error"]
    assert error["code"] == "invalid_scenario"
    assert "scenario_key_mismatch" in error["details"]["errors"]


def test_duplicate_scenario_key_is_rejected_with_conflict(operator):
    operator.post("/api/v1/simulation/scenarios", json=_case_payload())
    response = operator.post("/api/v1/simulation/scenarios", json=_case_payload())
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "conflict"


def test_missing_scenario_returns_404(operator):
    response = operator.get("/api/v1/simulation/scenarios/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_invalid_query_filter_is_rejected(operator):
    response = operator.get("/api/v1/simulation/scenarios?variant=unknown")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_request"


# ---------------------------------------------------------------------------
# 隔离与留痕
# ---------------------------------------------------------------------------


def test_scenario_write_leaves_no_project_rows(operator, db_session):
    from fde_api.workbench.models import Project

    operator.post("/api/v1/simulation/scenarios", json=_case_payload())
    db_session.rollback()
    assert db_session.scalar(select(Project.id).limit(1)) is None


def test_scenario_write_is_audited_as_operation_event(operator, db_session):
    created = operator.post(
        "/api/v1/simulation/scenarios", json=_case_payload()
    ).get_json()["data"]
    db_session.rollback()
    events = list(
        db_session.scalars(
            select(OperationEvent).where(
                OperationEvent.target_type == "simulation_scenario",
                OperationEvent.target_id == created["id"],
            )
        )
    )
    assert events
    assert events[0].event_type == "simulation_scenario_created"
    # 模拟对象不属于任何真实项目
    assert events[0].project_id is None
