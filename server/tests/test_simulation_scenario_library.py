"""模拟场景库纯函数层（V3.2 G2）。

钉住四组纪律（全部为**可变异**断言——改动任一条即应转红）：

1. **装载视图隔离**：Tester View 只有客户初始简报/已知系统/既定约束；
   Customer View 含隐藏事实但**不含**参考答案与 Rubric；Judge View 才全量。
2. **装载器自检**：视图里出现不该可见的键 ⇒ 直接拒绝装载（不静默放行）。
3. **变体物化**：6 案例 × 3 变体 = 18 行；物化后 `variant_overrides` 移除、
   覆盖项按语义合并（追加约束/覆盖预算/抑制事实）。
4. **内置案例自洽**：6 个种子文件全部通过校验器（案例质量回归闸）。

本文件**不碰数据库**（纯函数层）。
"""
from __future__ import annotations

import copy
import re

import pytest

from fde_api.simulation.scenarios.loader import (
    ScenarioLeakError,
    list_case_files,
    load_case_file,
    load_view,
    materialize_variant,
)
from fde_api.simulation.scenarios.validator import validate_scenario
from fde_api.simulation.scenarios.versioning import derive_next_row, next_version
from fde_api.simulation.seeds import VARIANTS, build_seed_rows
from fde_api.simulation.schemas import ANSWER_SIDE_KEYS, contains_forbidden_keys


def _base_case() -> dict:
    return load_case_file(list_case_files()[0])


# ---------------------------------------------------------------------------
# 1. 装载视图隔离
# ---------------------------------------------------------------------------


def test_tester_view_exposes_only_initial_brief_known_systems_and_constraints():
    base = _base_case()
    content = base["content"]
    view = load_view(content, base["reference"], "tester")

    assert set(view) == {"brief", "known_systems", "constraints"}
    assert view["brief"] == content["visible"]["initial_brief"]
    # 隐藏事实、参考答案、Rubric 一律不可见
    assert contains_forbidden_keys(view) == []


def test_tester_view_never_exposes_hidden_facts_or_reference():
    base = _base_case()
    content = base["content"]
    reference = base["reference"]

    view = load_view(content, reference, "tester")

    hidden_fact_text = content["hidden"]["facts"][0]["text"]
    assert hidden_fact_text not in str(view)
    assert reference["rubric"]["must_identify"][0] not in str(view)


def test_customer_view_holds_hidden_facts_but_not_the_answer():
    base = _base_case()
    content = base["content"]
    reference = base["reference"]

    view = load_view(content, reference, "customer")

    assert view["hidden"]["facts"]
    assert view["customer_profile"]["stakeholders"]
    # 客户模拟器不得看到评分侧答案（客户侧键对它可见，故只查答案侧键）
    assert contains_forbidden_keys(view, ANSWER_SIDE_KEYS) == []
    assert reference["rubric"]["must_avoid"][0] not in str(view)


def test_judge_view_is_the_only_full_view():
    base = _base_case()
    view = load_view(base["content"], base["reference"], "judge")

    assert view["reference"]["rubric"]["must_identify"]
    assert view["hidden"]["facts"]


# ---------------------------------------------------------------------------
# 2. 装载器自检（拒绝而非放行）
# ---------------------------------------------------------------------------


def test_loader_refuses_to_hand_out_an_answer_side_key():
    """把 Rubric 塞进 content ⇒ 客户视图装载必须失败（不是「顺手带上」）。"""
    base = _base_case()
    content = copy.deepcopy(base["content"])
    content["rubric"] = {"must_identify": ["答案"], "must_avoid": [], "must_produce": []}

    with pytest.raises(ScenarioLeakError) as excinfo:
        load_view(content, base["reference"], "customer")

    assert excinfo.value.code == "reference_leak"
    assert "rubric" in str(excinfo.value.detail)


def test_loader_rejects_unknown_view():
    base = _base_case()
    with pytest.raises(ScenarioLeakError) as excinfo:
        load_view(base["content"], base["reference"], "everyone")
    assert excinfo.value.code == "invalid_view"


def test_leak_detector_finds_nested_paths():
    payload = {"a": {"b": [{"rubric": {}}]}}
    hits = contains_forbidden_keys(payload)
    assert len(hits) == 1
    assert hits[0].startswith("a.b")


# ---------------------------------------------------------------------------
# 3. 变体物化
# ---------------------------------------------------------------------------


def test_materialized_variant_drops_variant_overrides_itself():
    base = _base_case()
    content = base["content"]
    for variant in VARIANTS:
        materialized = materialize_variant(content, variant)
        assert "variant_overrides" not in materialized
        # 物化结果是自包含的独立场景
        assert materialized["case_code"] == content["case_code"]


def test_complex_variant_merges_budget_conflicts_and_change_events():
    base = _base_case()
    content = base["content"]
    assert "complex" in content["variant_overrides"], "基线案例应提供 complex 覆盖"

    materialized = materialize_variant(content, "complex")

    override = content["variant_overrides"]["complex"]
    if "budget" in override:
        assert materialized["visible"]["constraints"]["budget"] == override["budget"]
    if "conflicts" in override:
        assert materialized["conflicts"]
    if "change_events" in override:
        assert materialized["change_events"]
    # 变体额外约束是追加，不覆盖原约束
    assert "extra" in materialized["visible"]["constraints"]


def test_suppress_facts_removes_the_named_fact_only():
    base = _base_case()
    content = copy.deepcopy(base["content"])
    facts = content["hidden"]["facts"]
    target = facts[0]["fact_id"]
    content["variant_overrides"] = {
        "vague": {"suppress_facts": [target]},
        "complex": {},
    }

    materialized = materialize_variant(content, "vague")

    remaining = {fact["fact_id"] for fact in materialized["hidden"]["facts"]}
    assert target not in remaining
    assert len(remaining) == len(facts) - 1


def test_normal_variant_is_the_baseline_without_overrides():
    base = _base_case()
    content = base["content"]
    materialized = materialize_variant(content, "normal")
    assert materialized["hidden"]["facts"] == content["hidden"]["facts"]
    assert "probe_tolerance" not in materialized


# ---------------------------------------------------------------------------
# 4. 校验器
# ---------------------------------------------------------------------------


def test_all_builtin_cases_pass_validation():
    for path in list_case_files():
        base = load_case_file(path)
        errors = validate_scenario(
            base["content"],
            base["reference"],
            scenario_key=base["case_code"],
            variant="normal",
            split=base.get("split", "train"),
        )
        assert errors == [], f"{path.name} 校验未通过：{errors}"


def test_seeds_materialize_eighteen_rows_six_cases_three_variants():
    rows = build_seed_rows()
    assert len(rows) == 18
    assert len({row["scenario_key"] for row in rows}) == 6
    assert {row["variant"] for row in rows} == {"normal", "vague", "complex"}
    for row in rows:
        assert row["version"] == 1
        assert row["source_kind"] == "seed"


def test_missing_required_key_is_rejected():
    base = _base_case()
    content = copy.deepcopy(base["content"])
    del content["misleading_request"]
    errors = validate_scenario(content, base["reference"], scenario_key=base["case_code"])
    assert "scenario_empty" in errors


def test_illegal_disclosure_stage_is_rejected():
    base = _base_case()
    content = copy.deepcopy(base["content"])
    content["hidden"]["facts"][0]["disclosure_stage"] = "whenever"
    errors = validate_scenario(content, base["reference"], scenario_key=base["case_code"])
    assert "invalid_disclosure_stage" in errors


def test_incomplete_rubric_is_rejected():
    base = _base_case()
    reference = copy.deepcopy(base["reference"])
    reference["rubric"]["must_avoid"] = []
    errors = validate_scenario(base["content"], reference, scenario_key=base["case_code"])
    assert "rubric_incomplete" in errors


def test_case_code_must_match_scenario_key():
    base = _base_case()
    errors = validate_scenario(
        base["content"], base["reference"], scenario_key="CASE-OTHER-KEY"
    )
    assert "scenario_key_mismatch" in errors


def test_blind_split_requires_reference():
    base = _base_case()
    errors = validate_scenario(
        base["content"], None, scenario_key=base["case_code"], split="blind"
    )
    assert "missing_reference" in errors


def test_unknown_variant_override_key_is_rejected():
    base = _base_case()
    content = copy.deepcopy(base["content"])
    content["variant_overrides"] = {"vague": {"not_a_real_key": 1}}
    errors = validate_scenario(content, base["reference"], scenario_key=base["case_code"])
    assert "invalid_variant_override" in errors


# ---------------------------------------------------------------------------
# 5. 版本化
# ---------------------------------------------------------------------------


def test_seed_files_contain_no_pseudonymization_sensitive_shapes():
    """仿真种子**不得**含任何会被代号化扫描判为个人数据的形状。

    扫描正则与 ``scripts/check-pseudonymization.sh`` **逐字同尺**（邮箱 / 手机号 /
    18 位身份证）：CI 的 pseudonymization job 会把整库 dump 后扫这些形状——仿真
    地址一旦落库就会让该 job 变红。故种子里的占位邮箱刻意不带 TLD 圆点。
    """
    email_pattern = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    phone_pattern = re.compile(r"(?<![0-9A-Fa-f-])1[3-9][0-9]{9}(?![0-9A-Fa-f-])")
    idcard_pattern = re.compile(r"(?<![0-9A-Fa-fXx])[0-9]{17}[0-9Xx](?![0-9A-Fa-fXx])")

    for path in list_case_files():
        raw = path.read_text(encoding="utf-8")
        assert not email_pattern.findall(raw), f"{path.name} 含 email 形状串"
        assert not phone_pattern.findall(raw), f"{path.name} 含手机号形状串"
        assert not idcard_pattern.findall(raw), f"{path.name} 含身份证形状串"


def test_next_version_is_max_plus_one():
    assert next_version([]) == 1
    assert next_version([1, 2, 3]) == 4
    assert next_version([1, 2, 3, 9]) == 10


def test_derive_next_row_bumps_version_and_ignores_identity_fields():
    existing = {
        "scenario_key": "CASE-A",
        "name": "案例 A",
        "industry": "automotive_parts",
        "variant": "normal",
        "difficulty": "standard",
        "split": "train",
        "status": "active",
        "tags": ["质量"],
        "content_json": {"case_code": "CASE-A"},
        "reference_json": None,
        "rubric_version": "rubric-v1",
        "source_kind": "seed",
        "source_ref": "CASE-A.json",
        "note": None,
    }
    derived = derive_next_row(
        existing,
        {"name": "案例 A（改）", "id": "HACK", "scenario_key": "HACK"},
        next_version_number=2,
    )
    assert derived["version"] == 2
    assert derived["name"] == "案例 A（改）"
    # 身份字段不可透传
    assert derived["scenario_key"] == "CASE-A"
    assert "id" not in derived
