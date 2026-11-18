"""AF2-WP2：类型化 TransformPlan 与算子白名单（15 号 §3 WP2 行 / 03 §5）。

计划面（WP2）只产出**声明**：类型化 Schema + 算子白名单闭集 + 结构静态
校验 + op 级依赖 DAG。编译面（算子 step → logic_engine AST 求值）归 WP3
design-first 门，不在本批（15 号 §2 D2 分阶段落地口径）。

核心纪律钉：

- **算子白名单闭集**：九算子（选择/重命名/类型/日期时区/单位换算/枚举映射/
  去重/受限 Join/质量断言），白名单外一律拒；
- **参数键集精确匹配**：每算子的参数键集闭集且逐算子不同，**多余键即拒**
  —— 这就是 03 §5「不接受嵌入 SQL/脚本/表达式逃逸」的结构化落实：
  计划里没有任何自由文本表达式槽可逃逸（``expr``/``sql``/``script`` 等键
  一律被多余键检查拦下）；
- **值域枚举化**：时区走 IANA tzdata、单位走受控量纲换算表、枚举映射与
  质量断言走闭集 kind；
- **04 §3.2「日期时区、Decimal、舍入、空值、重复主键、Join 基数、
  丢弃/拒绝记录策略必须显式定义」逐项 fail-closed**：缺声明即校验失败；
- **依赖图无环** + 拓扑序（op 级 DAG，兼作血缘骨架）；
- **未知关联不自动变生产 Join**（03 §77）：Join 步骤只是声明，证据键对
  （``basis=fk_catalog``）须在关系候选段可查；``declared_by_plan`` 仅表示
  人工声明，仍无翻产通道（本批无任何生产态字段）。
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from conftest import INITIAL_PASSWORD as PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.data_engineering.models import TransformPlan
from fde_api.data_engineering.transform_plan import (
    PLAN_VERSION,
    validate_plan,
)
from fde_api.workbench.models import Project, ProjectMember

# ---- 计划骨架 ----------------------------------------------------------------

INPUT_COLUMNS = [
    {"name": "eq_id", "type": "string"},
    {"name": "eq_name", "type": "string"},
    {"name": "defect_pct", "type": "number"},
    {"name": "measured_at", "type": "datetime"},
    {"name": "length_mm", "type": "number"},
    {"name": "operator_id", "type": "string"},
]


def _plan(**overrides):
    plan = {
        "plan_version": PLAN_VERSION,
        "source": {"profile_id": str(uuid.uuid4()), "table": "equipment"},
        "input": {"columns": list(INPUT_COLUMNS)},
        "policies": {
            "null_handling": "reject",
            "reject_record": "collect",
            "duplicate_key": "error",
        },
        "relations": [
            {
                "left_table": "work_order",
                "right_table": "equipment",
                "left_column": "eq_id",
                "right_column": "eq_id",
                "basis": "fk_catalog",
            }
        ],
        "steps": [
            {"id": "s1", "op": "select", "params": {"columns": ["eq_id", "eq_name"]}},
        ],
        "output": {"columns": [{"name": "eq_id", "type": "string"}]},
    }
    plan.update(overrides)
    return plan


def _codes(report) -> set[str]:
    return {error["code"] for error in report["errors"]}


# ---- 版本与骨架 ---------------------------------------------------------------


def test_valid_plan_reports_valid_and_dependency_graph() -> None:
    report = validate_plan(_plan())

    assert report["valid"] is True
    assert report["errors"] == []
    graph = report["dependency_graph"]
    assert graph["nodes"] == ["s1"]
    assert graph["edges"] == []
    assert graph["topological_order"] == ["s1"]
    assert report["output_columns"] == [{"name": "eq_id", "type": "string"}]


def test_unsupported_plan_version_rejected() -> None:
    report = validate_plan(_plan(plan_version="af2-wp2-v999"))

    assert report["valid"] is False
    assert "unsupported_plan_version" in _codes(report)


def test_missing_policies_block_rejected() -> None:
    """04 §3.2：空值/丢弃拒绝/重复主键策略必须显式定义——缺一即拒。"""
    for missing in ("null_handling", "reject_record", "duplicate_key"):
        policies = {
            "null_handling": "reject",
            "reject_record": "collect",
            "duplicate_key": "error",
        }
        policies.pop(missing)
        report = validate_plan(_plan(policies=policies))

        assert report["valid"] is False, missing
        assert "invalid_parameter_value" in _codes(report), missing


def test_policy_values_restricted_to_closed_set() -> None:
    report = validate_plan(
        _plan(policies={"null_handling": "drop_rows", "reject_record": "collect", "duplicate_key": "error"})
    )

    assert report["valid"] is False
    assert "invalid_parameter_value" in _codes(report)


# ---- 算子白名单闭集 -----------------------------------------------------------


def test_operator_outside_whitelist_rejected() -> None:
    plan = _plan(
        steps=[{"id": "s1", "op": "python_eval", "params": {"code": "1+1"}}]
    )
    report = validate_plan(plan)

    assert report["valid"] is False
    assert "unknown_operator" in _codes(report)


def test_whitelist_contains_the_nine_declared_operators() -> None:
    """白名单闭集＝九算子（03 §5 WP2 行原文六类拆到可执行粒度）。

    九算子串成一条链（每步依赖上一步）——依赖图给出单 sink，最终 schema
    即 sink 产出（类型沿链演进）。
    """
    plan = _plan(
        steps=[
            {"id": "s1", "op": "select", "params": {"columns": ["eq_id", "eq_name", "defect_pct", "measured_at", "length_mm", "operator_id"]}},
            {"id": "s2", "op": "rename", "params": {"mapping": {"eq_id": "equipment_id"}}, "depends_on": ["s1"]},
            {"id": "s3", "op": "cast", "params": {"column": "defect_pct", "to_type": "decimal", "scale": 4, "rounding": "half_up"}, "depends_on": ["s2"]},
            {"id": "s4", "op": "normalize_datetime", "params": {"column": "measured_at", "to_tz": "Asia/Shanghai"}, "depends_on": ["s3"]},
            {"id": "s5", "op": "convert_unit", "params": {"column": "length_mm", "from_unit": "mm", "to_unit": "m"}, "depends_on": ["s4"]},
            {"id": "s6", "op": "map_enum", "params": {"column": "operator_id", "mapping": {"A": "alpha"}, "unmapped": "error"}, "depends_on": ["s5"]},
            {"id": "s7", "op": "dedup", "params": {"keys": ["equipment_id"]}, "depends_on": ["s6"]},
            {"id": "s8", "op": "join", "params": {"left_key": "equipment_id", "right_table": "equipment", "right_key": "eq_id", "cardinality": "one_to_one", "basis": "fk_catalog"}, "depends_on": ["s7"]},
            {"id": "s9", "op": "assert_quality", "params": {"kind": "not_null", "column": "equipment_id"}, "depends_on": ["s8"]},
        ],
        output={"columns": [{"name": "equipment_id", "type": "string"}]},
    )
    report = validate_plan(plan)

    assert report["valid"] is True, report["errors"]
    assert len(report["dependency_graph"]["nodes"]) == 9
    assert report["dependency_graph"]["topological_order"][0] == "s1"
    assert report["dependency_graph"]["topological_order"][-1] == "s9"


# ---- 参数键集精确匹配＝无逃逸槽 -----------------------------------------------


@pytest.mark.parametrize(
    "operator,params",
    [
        ("select", {"columns": ["eq_id"], "expr": "upper(eq_id)"}),
        ("cast", {"column": "defect_pct", "to_type": "number", "sql": "select 1"}),
        ("dedup", {"keys": ["eq_id"], "script": "rm -rf /"}),
        ("join", {"left_key": "eq_id", "right_table": "equipment", "right_key": "eq_id", "cardinality": "one_to_one", "basis": "fk_catalog", "template": "{{x}}"}),
    ],
)
def test_extra_parameter_keys_rejected(operator: str, params: dict) -> None:
    """多余键即拒——计划里没有自由文本槽可逃逸（03 §5）。"""
    report = validate_plan(_plan(steps=[{"id": "s1", "op": operator, "params": params}]))

    assert report["valid"] is False
    assert "unexpected_parameter" in _codes(report)


def test_missing_required_parameter_rejected() -> None:
    report = validate_plan(_plan(steps=[{"id": "s1", "op": "cast", "params": {"column": "defect_pct"}}]))

    assert report["valid"] is False
    assert "missing_parameter" in _codes(report)


# ---- 值域枚举化 ---------------------------------------------------------------


def test_unknown_timezone_rejected() -> None:
    report = validate_plan(
        _plan(steps=[{"id": "s1", "op": "normalize_datetime", "params": {"column": "measured_at", "to_tz": "Mars/Olympus_Mons"}}])
    )

    assert report["valid"] is False
    assert "invalid_parameter_value" in _codes(report)


def test_incompatible_unit_conversion_rejected() -> None:
    report = validate_plan(
        _plan(steps=[{"id": "s1", "op": "convert_unit", "params": {"column": "length_mm", "from_unit": "mm", "to_unit": "kg"}}])
    )

    assert report["valid"] is False
    assert "invalid_parameter_value" in _codes(report)


def test_valid_unit_conversion_accepted() -> None:
    report = validate_plan(
        _plan(steps=[{"id": "s1", "op": "convert_unit", "params": {"column": "length_mm", "from_unit": "mm", "to_unit": "m"}}])
    )

    assert report["valid"] is True, report["errors"]


def test_cast_to_decimal_requires_scale_and_rounding() -> None:
    """04 §3.2：Decimal 与舍入必须显式定义——缺 scale/rounding 即拒。"""
    plan = _plan(
        steps=[{"id": "s1", "op": "cast", "params": {"column": "defect_pct", "to_type": "decimal"}}]
    )
    report = validate_plan(plan)

    assert report["valid"] is False
    assert "missing_parameter" in _codes(report)


def test_cast_to_decimal_with_scale_and_rounding_accepted() -> None:
    plan = _plan(
        steps=[{"id": "s1", "op": "cast", "params": {"column": "defect_pct", "to_type": "decimal", "scale": 4, "rounding": "half_up"}}]
    )
    report = validate_plan(plan)

    assert report["valid"] is True, report["errors"]


def test_incompatible_cast_rejected() -> None:
    report = validate_plan(
        _plan(steps=[{"id": "s1", "op": "cast", "params": {"column": "eq_id", "to_type": "datetime"}}])
    )

    assert report["valid"] is False
    assert "type_incompatible" in _codes(report)


def test_assert_quality_kind_closed_set() -> None:
    report = validate_plan(
        _plan(steps=[{"id": "s1", "op": "assert_quality", "params": {"kind": "looks_odd", "column": "eq_id"}}])
    )

    assert report["valid"] is False
    assert "invalid_parameter_value" in _codes(report)


# ---- 列引用与输出声明 ---------------------------------------------------------


def test_unknown_column_reference_rejected() -> None:
    report = validate_plan(
        _plan(steps=[{"id": "s1", "op": "cast", "params": {"column": "no_such_column", "to_type": "string"}}])
    )

    assert report["valid"] is False
    assert "unknown_column" in _codes(report)


def test_output_column_not_in_produced_set_rejected() -> None:
    report = validate_plan(
        _plan(output={"columns": [{"name": "defect_pct", "type": "number"}]})
    )

    assert report["valid"] is False
    assert "output_mismatch" in _codes(report)


def test_output_type_mismatch_rejected() -> None:
    report = validate_plan(
        _plan(output={"columns": [{"name": "eq_id", "type": "number"}]})
    )

    assert report["valid"] is False
    assert "output_mismatch" in _codes(report)


def test_rename_conflicting_with_existing_column_rejected() -> None:
    report = validate_plan(
        _plan(
            steps=[
                {"id": "s1", "op": "select", "params": {"columns": ["eq_id", "eq_name"]}},
                {"id": "s2", "op": "rename", "params": {"mapping": {"eq_id": "eq_name"}}},
            ]
        )
    )

    assert report["valid"] is False
    assert "duplicate_column" in _codes(report)


# ---- 依赖图：无环 + 拓扑序 ----------------------------------------------------


def test_dependency_cycle_rejected() -> None:
    plan = _plan(
        steps=[
            {"id": "s1", "op": "select", "params": {"columns": ["eq_id"]}, "depends_on": ["s2"]},
            {"id": "s2", "op": "dedup", "params": {"keys": ["eq_id"]}, "depends_on": ["s1"]},
        ]
    )
    report = validate_plan(plan)

    assert report["valid"] is False
    assert "dependency_cycle" in _codes(report)


def test_unknown_step_reference_rejected() -> None:
    plan = _plan(
        steps=[
            {"id": "s1", "op": "select", "params": {"columns": ["eq_id"]}, "depends_on": ["s9"]},
        ]
    )
    report = validate_plan(plan)

    assert report["valid"] is False
    assert "unknown_step_reference" in _codes(report)


def test_dependency_graph_topological_order_and_edges() -> None:
    plan = _plan(
        steps=[
            {"id": "s1", "op": "select", "params": {"columns": ["eq_id", "eq_name", "defect_pct"]}},
            {"id": "s2", "op": "cast", "params": {"column": "defect_pct", "to_type": "number"}, "depends_on": ["s1"]},
            {"id": "s3", "op": "dedup", "params": {"keys": ["eq_id"]}, "depends_on": ["s1", "s2"]},
        ],
        output={"columns": [{"name": "eq_id", "type": "string"}]},
    )
    report = validate_plan(plan)

    assert report["valid"] is True, report["errors"]
    graph = report["dependency_graph"]
    assert graph["nodes"] == ["s1", "s2", "s3"]
    assert sorted(graph["edges"]) == [["s1", "s2"], ["s1", "s3"], ["s2", "s3"]]
    assert graph["topological_order"].index("s1") < graph["topological_order"].index("s2")
    assert graph["topological_order"].index("s2") < graph["topological_order"].index("s3")


def test_duplicate_step_id_rejected() -> None:
    plan = _plan(
        steps=[
            {"id": "s1", "op": "select", "params": {"columns": ["eq_id"]}},
            {"id": "s1", "op": "dedup", "params": {"keys": ["eq_id"]}},
        ]
    )
    report = validate_plan(plan)

    assert report["valid"] is False
    assert "duplicate_step_id" in _codes(report)


# ---- Join 证据（03 §77 未知关联不自动变生产 Join）------------------------------


def test_join_with_fk_evidence_accepted() -> None:
    plan = _plan(
        steps=[
            {"id": "s1", "op": "select", "params": {"columns": ["eq_id"]}},
            {"id": "s2", "op": "join", "params": {"left_key": "eq_id", "right_table": "equipment", "right_key": "eq_id", "cardinality": "one_to_one", "basis": "fk_catalog"}, "depends_on": ["s1"]},
        ]
    )
    report = validate_plan(plan)

    assert report["valid"] is True, report["errors"]


def test_join_without_evidence_rejected() -> None:
    """basis=fk_catalog 但关系候选段查无此键对 → 拒（不得凭空宣称硬证据）。"""
    plan = _plan(
        steps=[
            {"id": "s1", "op": "select", "params": {"columns": ["eq_id"]}},
            {"id": "s2", "op": "join", "params": {"left_key": "eq_id", "right_table": "nowhere", "right_key": "eq_id", "cardinality": "one_to_one", "basis": "fk_catalog"}, "depends_on": ["s1"]},
        ]
    )
    report = validate_plan(plan)

    assert report["valid"] is False
    assert "join_evidence_missing" in _codes(report)


def test_join_cardinality_must_be_declared() -> None:
    """04 §3.2：Join 基数必须显式定义。"""
    plan = _plan(
        steps=[
            {"id": "s1", "op": "select", "params": {"columns": ["eq_id"]}},
            {"id": "s2", "op": "join", "params": {"left_key": "eq_id", "right_table": "equipment", "right_key": "eq_id", "basis": "fk_catalog"}, "depends_on": ["s1"]},
        ]
    )
    report = validate_plan(plan)

    assert report["valid"] is False
    assert "missing_parameter" in _codes(report)


def test_relation_basis_has_no_production_state() -> None:
    """关系候选段无生产态字段——只有 basis，无 status/promoted（03 §77）。"""
    plan = _plan(
        relations=[
            {
                "left_table": "work_order",
                "right_table": "equipment",
                "left_column": "eq_id",
                "right_column": "eq_id",
                "basis": "fk_catalog",
                "status": "promoted",
            }
        ]
    )
    report = validate_plan(plan)

    assert report["valid"] is False
    assert "unexpected_parameter" in _codes(report)


# ---- 落库面 -------------------------------------------------------------------


def _make_user(db_session, role: str) -> User:
    user = User(
        username=f"{role}.{uuid.uuid4().hex}",
        display_name=role,
        role=role,
        password_hash=hash_password(PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _make_project(db_session, leader: User) -> Project:
    project = Project(
        project_code=f"TP-{uuid.uuid4().hex[:8]}",
        name="Transform plan project",
        enterprise_code="Example·行业·城市",
        planned_start_date=date(2026, 9, 1),
        leader_user_id=leader.id,
        status="active",
        template_snapshot={},
    )
    db_session.add(project)
    db_session.commit()
    return project


def _headers(user: User, settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


def test_create_plan_persists_validated_artifact(client, db_session, settings) -> None:
    """落库钉：只落**已通过静态校验**的计划（计划面产物=校验报告+DAG+输出声明）；
    append-only、无 PATCH/DELETE（关系候选与计划均无翻产通道）。"""
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    member = _make_user(db_session, "viewer")
    db_session.add(ProjectMember(project_id=project.id, user_id=member.id, role="member"))
    db_session.commit()

    body = _plan()
    response = client.post(
        f"/api/v1/projects/{project.id}/transform-plans",
        json={"plan": body},
        headers=_headers(member, settings),
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    payload = response.get_json()["data"]
    assert payload["plan_version"] == PLAN_VERSION
    assert payload["status"] == "validated"  # 键空间封闭：无生产态
    assert payload["validation"]["valid"] is True
    assert payload["dependency_graph"]["nodes"] == ["s1"]
    assert payload["output_columns"] == [{"name": "eq_id", "type": "string"}]
    assert payload["source_profile_id"] == body["source"]["profile_id"]
    assert payload["source_table"] == "equipment"

    row = db_session.get(TransformPlan, payload["id"])
    assert row is not None
    assert row.project_id == project.id
    assert row.created_by_user_id == member.id

    # 清单 + 详情：项目成员可读、外人 404（S-01）
    detail = client.get(
        f"/api/v1/projects/{project.id}/transform-plans/{payload['id']}",
        headers=_headers(member, settings),
    )
    assert detail.status_code == 200
    outsider = _make_user(db_session, "fde_engineer")
    outsider_detail = client.get(
        f"/api/v1/projects/{project.id}/transform-plans/{payload['id']}",
        headers=_headers(outsider, settings),
    )
    assert outsider_detail.status_code == 404
    listing = client.get(
        f"/api/v1/projects/{project.id}/transform-plans",
        headers=_headers(member, settings),
    )
    assert listing.status_code == 200
    assert payload["id"] in [item["id"] for item in listing.get_json()["data"]]


def test_create_plan_rejects_invalid_plan_without_persisting(client, db_session, settings) -> None:
    """校验失败 ⇒ 400 且**零落库**（不落非法计划）。"""
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)

    response = client.post(
        f"/api/v1/projects/{project.id}/transform-plans",
        json={"plan": _plan(steps=[{"id": "s1", "op": "python_eval", "params": {"code": "1"}}])},
        headers=_headers(leader, settings),
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_transform_plan"
    assert db_session.query(TransformPlan).count() == 0


def test_create_plan_requires_membership(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    outsider = _make_user(db_session, "fde_engineer")

    response = client.post(
        f"/api/v1/projects/{project.id}/transform-plans",
        json={"plan": _plan()},
        headers=_headers(outsider, settings),
    )
    assert response.status_code == 404  # S-01 不泄露存在性
