"""AE1-WP5-A：断言文法解析与求值（任务集 `_ae-tasks-v1.md` §5 断言表达式文法）。

评分器纪律（05:41「评分器只消费落盘记录，不改断言」）：本文件实现**冻结文法**
的解析与求值，**逐字消费**任务集里的 84 条断言文本——不改写、不放宽、不跳过；
任何解析不了的表达式一律**判 FAIL 并登记**，绝不静默通过。

文法（`_ae-tasks-v1.md` §5 逐字）::

    expr    := clause ((" and " | " or " ) clause)*
    clause  := operand op operand
             | "len(" path ")" op operand
             | "not " operand
    operand := path | literal | "len(" path ")"
    path    := ident ( "." ident | "[" int "]" )*
    op      := "==" | "!=" | ">=" | "<=" | ">" | "<"
    literal := string | number | true | false | null
    ident   := [A-Za-z_][A-Za-z0-9_]*

根作用域（`_ae-tasks-v1.md` §4 观测包络）：``attempts.<first|replay2|replay3>``
（契约字段）、``task.total_cost_usd``（评分器派生）、``task.external_state.<key>``
（harness 观测）。

缺失路径口径：**证据缺失即不通过**（缺失哨兵参与任何比较恒为 False，
``not <缺失>`` 亦为 False）——不得把「查不到」当「通过」。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from ae_eval.assertions import (
    AssertionSyntaxError,
    evaluate_all,
    evaluate_assertion,
    parse_assertion,
)

# ---- 合成观测包络（不引用任何真实运行记录） --------------------------------


def _envelope(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "attempts": {
            "first": {
                "execution_id": "exec-1",
                "idempotency_key": "test-idem-t4-001-a",
                "status": "succeeded",
                "output": {
                    "ontologies": [
                        {"ontology_id": "o-1", "name": "Equipment", "org_id": "test-org-001"},
                        {"ontology_id": "o-2", "name": "Sensor", "org_id": "test-org-001"},
                    ],
                    "count": 2,
                    "simulated": False,
                },
                "error": None,
                "audit": {
                    "connector_id": "workbench.ontology",
                    "method": "read",
                    "params_sha256": "a" * 64,
                    "actor_user_id": "test-user-001",
                    "org_id": "test-org-001",
                    "approval_id": None,
                    "started_at": "2026-11-20T00:00:00+00:00",
                    "finished_at": "2026-11-20T00:00:01+00:00",
                    "duration_ms": 1000,
                },
                "cost": {"tool_calls": 1, "duration_ms": 1000, "estimated_usd": 0.0},
                "rollback": {"supported": False, "execution_id": "exec-1"},
                "replayed_from_execution_id": None,
            },
            "replay2": {
                "execution_id": "exec-1",
                "idempotency_key": "test-idem-t4-001-a",
                "status": "replayed",
                "output": {"count": 2},
                "error": None,
                "audit": {
                    "connector_id": "workbench.ontology",
                    "method": "read",
                    "params_sha256": "a" * 64,
                    "actor_user_id": "test-user-001",
                    "org_id": "test-org-001",
                    "approval_id": None,
                    "started_at": "2026-11-20T00:00:00+00:00",
                    "finished_at": "2026-11-20T00:00:01+00:00",
                    "duration_ms": 1000,
                },
                "cost": {"tool_calls": 1, "duration_ms": 1000, "estimated_usd": 0.0},
                "rollback": {"supported": False, "execution_id": "exec-1"},
                "replayed_from_execution_id": "exec-1",
            },
        },
        "task": {
            "total_cost_usd": 0.0,
            "external_state": {
                "ontology_terms_unchanged": True,
                "mailbox_count": 1,
                "mailbox_first_subject": "test-subject-t4-003",
            },
        },
    }
    base.update(overrides)
    return base


# ---- 文法解析 ----------------------------------------------------------------


class TestGrammar:
    @pytest.mark.parametrize(
        "expression",
        [
            'attempts.first.status == "succeeded"',
            "len(attempts.first.output.ontologies) >= 1",
            "attempts.first.output.count == len(attempts.first.output.ontologies)",
            "attempts.first.cost.tool_calls == 1",
            "task.total_cost_usd <= 0.10",
            "attempts.first.audit.approval_id == null",
            "attempts.first.audit.approval_id != null",
            "attempts.first.output != null",
            "task.external_state.mailbox_count == 1",
            'task.external_state.mailbox_first_subject == "test-subject-t4-003"',
            "not attempts.first.output.simulated",
            'attempts.first.status == "succeeded" and attempts.first.cost.tool_calls == 1',
            'attempts.first.status == "succeeded" or attempts.first.status == "failed"',
            "attempts.first.items[0].sku == \"SKU-001\"",
        ],
    )
    def test_expression_parses(self, expression: str) -> None:
        """文法覆盖：逐字对齐 `_ae-tasks-v1.md` §5。"""
        assert parse_assertion(expression) is not None

    @pytest.mark.parametrize(
        "expression",
        [
            "attempts.first.status ==",
            "== \"succeeded\"",
            "attempts.first.status == ",
            "attempts.first..status == \"x\"",
            "attempts.first.status == \"unterminated",
            "attempts.first.status == \"x\" and",
            "len(attempts.first.output >= 1",
        ],
    )
    def test_malformed_expression_raises(self, expression: str) -> None:
        """文法不合的表达式一律抛错——评分器据此判 FAIL（不得静默跳过）。"""
        with pytest.raises(AssertionSyntaxError):
            parse_assertion(expression)

    def test_parser_does_not_mutate_expression_text(self) -> None:
        """解析器不改写断言原文（05:41 纪律）。"""
        text = 'attempts.first.status == "succeeded"'
        parse_assertion(text)
        assert text == 'attempts.first.status == "succeeded"'


# ---- 求值 --------------------------------------------------------------------


class TestEvaluation:
    def test_path_equals_string_literal(self) -> None:
        assert evaluate_assertion('attempts.first.status == "succeeded"', _envelope()) is True

    def test_path_equals_wrong_string_literal(self) -> None:
        assert evaluate_assertion('attempts.first.status == "failed"', _envelope()) is False

    def test_len_of_list(self) -> None:
        assert evaluate_assertion("len(attempts.first.output.ontologies) >= 1", _envelope()) is True
        assert evaluate_assertion("len(attempts.first.output.ontologies) >= 3", _envelope()) is False

    def test_len_of_string(self) -> None:
        assert evaluate_assertion("len(attempts.first.output.ontologies[0].name) >= 1", _envelope()) is True

    def test_path_equals_len_of_other_path(self) -> None:
        assert (
            evaluate_assertion(
                "attempts.first.output.count == len(attempts.first.output.ontologies)", _envelope()
            )
            is True
        )

    def test_numeric_comparisons(self) -> None:
        assert evaluate_assertion("attempts.first.cost.duration_ms >= 0", _envelope()) is True
        assert evaluate_assertion("attempts.first.cost.duration_ms > 1000", _envelope()) is False
        assert evaluate_assertion("attempts.first.cost.duration_ms <= 1000", _envelope()) is True
        assert evaluate_assertion("attempts.first.cost.duration_ms < 1000", _envelope()) is False

    def test_float_budget_comparison(self) -> None:
        assert evaluate_assertion("task.total_cost_usd <= 0.10", _envelope()) is True
        env = _envelope(task={"total_cost_usd": 0.11, "external_state": {}})
        assert evaluate_assertion("task.total_cost_usd <= 0.10", env) is False

    def test_null_literal_comparisons(self) -> None:
        assert evaluate_assertion("attempts.first.audit.approval_id == null", _envelope()) is True
        assert evaluate_assertion("attempts.first.audit.approval_id != null", _envelope()) is False
        assert evaluate_assertion("attempts.first.output != null", _envelope()) is True

    def test_boolean_literal(self) -> None:
        assert evaluate_assertion("task.external_state.ontology_terms_unchanged == true", _envelope()) is True
        assert evaluate_assertion("task.external_state.ontology_terms_unchanged == false", _envelope()) is False

    def test_and_or_operators(self) -> None:
        assert (
            evaluate_assertion(
                'attempts.first.status == "succeeded" and attempts.first.cost.tool_calls == 1', _envelope()
            )
            is True
        )
        assert (
            evaluate_assertion(
                'attempts.first.status == "failed" or attempts.first.cost.tool_calls == 1', _envelope()
            )
            is True
        )

    def test_not_operator(self) -> None:
        assert evaluate_assertion("not attempts.first.output.simulated", _envelope()) is True
        env = _envelope()
        env["attempts"]["first"]["output"]["simulated"] = True
        assert evaluate_assertion("not attempts.first.output.simulated", env) is False

    def test_path_to_path_equality(self) -> None:
        assert (
            evaluate_assertion(
                "attempts.replay2.replayed_from_execution_id == attempts.first.execution_id", _envelope()
            )
            is True
        )

    def test_indexed_path(self) -> None:
        assert evaluate_assertion('attempts.first.output.ontologies[0].name == "Equipment"', _envelope()) is True

    def test_missing_path_is_false_not_error(self) -> None:
        """证据缺失即不通过（不得把「查不到」当「通过」）。"""
        assert evaluate_assertion('attempts.first.output.missing_key == "x"', _envelope()) is False
        assert evaluate_assertion("len(attempts.first.output.missing_key) >= 0", _envelope()) is False
        assert evaluate_assertion("not attempts.first.output.missing_key", _envelope()) is False

    def test_missing_attempt_slot_is_false(self) -> None:
        """replay3 不存在时按缺失判 FALSE（不得跳过）。"""
        assert evaluate_assertion('attempts.replay3.status == "replayed"', _envelope()) is False

    def test_type_mismatch_is_false(self) -> None:
        """类型不可比的比较恒为 False（不抛错、不当通过）。"""
        assert evaluate_assertion('attempts.first.status == 1', _envelope()) is False
        assert evaluate_assertion('attempts.first.cost.duration_ms == "1000"', _envelope()) is False

    def test_evaluate_all_returns_per_assertion_booleans(self) -> None:
        results = evaluate_all(
            [
                'attempts.first.status == "succeeded"',
                'attempts.first.status == "failed"',
                "attempts.first.cost.tool_calls == 1",
            ],
            _envelope(),
        )
        assert results == [True, False, True]

    def test_evaluate_all_is_all_or_nothing_at_call_site(self) -> None:
        """评分器口径：全部断言同时为真＝该次运行通过（_ae-tasks-v1.md §5）。"""
        results = evaluate_all(
            ['attempts.first.status == "succeeded"', 'attempts.first.status == "failed"'], _envelope()
        )
        assert all(results) is False

    def test_evaluate_all_registers_malformed_as_failed(self) -> None:
        """解析不了的断言不得静默跳过——登记为 FAIL。"""
        results = evaluate_all(['attempts.first.status == "succeeded"', "attempts.first.status =="], _envelope())
        assert results == [True, False]


# ---- 冻结任务集 84 条断言逐字可解析（只消费不改写） ---------------------------


class TestFrozenTaskSetAssertions:
    """钉：冻结任务集里的每一条断言都能被本解析器接受（`_ae-tasks-v1.md` §5
    「84 条断言全部符合该文法」的口径在实现侧复核）。"""

    TASKSET = Path(__file__).resolve().parents[1] / "tests" / "ae_eval" / "taskset_v1.json"

    def test_taskset_copy_is_byte_identical_to_frozen_source(self) -> None:
        """仓内副本＝docs 冻结件 `_ae-tasks-v1.json` 的 **byte 一致副本**
        （sha256 锚；白名单同款「仓内副本＋锚钉」先例——改副本即改冻结件）。"""
        digest = hashlib.sha256(self.TASKSET.read_bytes()).hexdigest()
        assert digest == "bbf20c9ed6977434cebb0523b69e594553e9ab1f8f7df688f120d20da4b2d8d7"
        assert self.TASKSET.stat().st_size == 40542

    def _assertions(self) -> list[str]:
        payload = json.loads(self.TASKSET.read_text(encoding="utf-8"))
        collected: list[str] = []
        for task in payload["tasks"]:
            collected.extend(task["assertions"])
        return collected

    def test_frozen_task_set_has_84_assertions(self) -> None:
        assert len(self._assertions()) == 84

    def test_frozen_task_set_is_public_five_only(self) -> None:
        """仓内副本只含**公开集 5 任务**；隐藏 3 槽在密封件里（明文不入仓——
        09 §3.4 隔离纪律）。"""
        payload = json.loads(self.TASKSET.read_text(encoding="utf-8"))
        assert [task["id"] for task in payload["tasks"]] == [
            "T4-001",
            "T4-002",
            "T4-003",
            "T4-004",
            "T4-005",
        ]

    def test_every_frozen_assertion_parses(self) -> None:
        failures: list[str] = []
        for expression in self._assertions():
            try:
                parse_assertion(expression)
            except AssertionSyntaxError as exc:  # pragma: no cover - 失败即钉红
                failures.append(f"{expression!r}: {exc}")
        assert not failures, failures

    def test_evaluate_all_over_frozen_assertions_returns_84_booleans(self) -> None:
        results = evaluate_all(self._assertions(), _envelope())
        assert len(results) == 84
