"""AE1-WP5 评分器与落盘记录：口径钉（分母纪律 / Wilson 区间 / 报告分列）。

钉的纪律（05 号）：
- **分母不许改**（05:54）：失败、基础设施失败、超时一律保留在总表；
- **唯一任务数与运行次数分列**（05:47）；
- **二项比例给 95% Wilson 区间**（05:66），小样本显式标注不确定性；
- **评分器只消费落盘记录，不改断言**（05:41）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ae_eval.records import RunRecord, load_records, write_records
from ae_eval.scorer import Z_95, wilson_interval, score_records

TASKSET = Path(__file__).resolve().parents[1] / "tests" / "ae_eval" / "taskset_v1.json"


def _attempt(
    *,
    status: str = "succeeded",
    execution_id: str = "exec-1",
    replayed_from: str | None = None,
    output: dict[str, Any] | None = None,
    audit: dict[str, Any] | None = None,
    estimated_usd: float = 0.0,
) -> dict[str, Any]:
    return {
        "execution_id": execution_id,
        "idempotency_key": "test-idem-t4-001-a",
        "status": status,
        "output": output if output is not None else {"count": 2},
        "error": None,
        "audit": audit
        if audit is not None
        else {
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
        "cost": {"tool_calls": 1, "duration_ms": 1000, "estimated_usd": estimated_usd},
        "rollback": {"supported": False, "execution_id": execution_id},
        "replayed_from_execution_id": replayed_from,
    }


def _record(task_id: str, run_index: int, **kwargs: Any) -> RunRecord:
    return RunRecord(task_id=task_id, run_index=run_index, **kwargs)


# ---- Wilson 区间 -------------------------------------------------------------


class TestWilsonInterval:
    def test_known_value(self) -> None:
        """经典检验：10/10 ⇒ 下界 ≈ 0.722467（正态近似会给出 0.76..1.0 的错误下界）。

        解析交叉验证：p̂=1 时 margin 项 z·√(p̂(1−p̂)/n + z²/4n²) = z²/2n，
        与 center 分子里的 z²/2n 相消 ⇒ low = 1/(1+z²/n) = 1/1.384146 ≈ 0.722467。
        """
        low, high = wilson_interval(10, 10)
        assert low == pytest.approx(0.722467, abs=1e-5)
        assert low == pytest.approx(1.0 / (1.0 + Z_95**2 / 10.0), abs=1e-12)
        assert high == pytest.approx(1.0, abs=1e-9)

    def test_zero_successes(self) -> None:
        low, high = wilson_interval(0, 10)
        assert low == 0.0
        assert 0.0 < high < 0.35

    def test_half(self) -> None:
        low, high = wilson_interval(5, 10)
        assert low == pytest.approx(0.236593, abs=1e-5)
        assert high == pytest.approx(0.763407, abs=1e-5)

    def test_zero_denominator(self) -> None:
        assert wilson_interval(0, 0) == (0.0, 0.0)

    def test_interval_contains_point_estimate(self) -> None:
        for successes, total in ((0, 5), (1, 5), (3, 5), (5, 5), (14, 15)):
            low, high = wilson_interval(successes, total)
            assert low <= successes / total <= high


# ---- 落盘记录 ----------------------------------------------------------------


class TestRunRecord:
    def test_total_cost_is_derived_from_attempts(self) -> None:
        record = _record(
            "T4-001",
            1,
            attempts={
                "first": _attempt(estimated_usd=0.02),
                "replay2": _attempt(status="replayed", estimated_usd=0.02),
            },
        )
        assert record.total_cost_usd == pytest.approx(0.04)

    def test_envelope_shape_matches_task_set_spec(self) -> None:
        record = _record("T4-001", 1, attempts={"first": _attempt()}, external_state={"x": True})
        envelope = record.envelope()
        assert set(envelope) == {"attempts", "task"}
        assert set(envelope["task"]) == {"total_cost_usd", "external_state"}
        assert envelope["task"]["external_state"] == {"x": True}

    def test_json_roundtrip(self, tmp_path: Path) -> None:
        record = _record("T4-001", 2, attempts={"first": _attempt()}, external_state={"x": 1})
        target = write_records([record], tmp_path / "records.jsonl")
        loaded = load_records(target)
        assert len(loaded) == 1
        assert loaded[0].task_id == "T4-001"
        assert loaded[0].run_index == 2
        assert loaded[0].attempts == record.attempts
        assert loaded[0].external_state == {"x": 1}

    def test_records_file_is_jsonl_one_per_line(self, tmp_path: Path) -> None:
        write_records([_record("T4-001", 1), _record("T4-001", 2)], tmp_path / "r.jsonl")
        lines = (tmp_path / "r.jsonl").read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            json.loads(line)


# ---- 评分口径 ----------------------------------------------------------------


def _passing_task_record(task_id: str, run_index: int) -> RunRecord:
    """构造一条「与冻结断言全合」的记录（按各任务断言的实际绑定逐条满足）。"""
    external: dict[str, Any]  # 显式注解（首分支 {bool} 会把推断收窄成 dict[str, bool]）
    if task_id == "T4-001":
        attempts = {
            "first": _attempt(
                output={
                    "ontologies": [
                        {"ontology_id": "o1", "name": "Equipment", "org_id": "test-org-001"},
                    ],
                    "count": 1,
                },
                audit={
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
            )
        }
        external = {"ontology_terms_unchanged": True}
    elif task_id == "T4-003":
        mail_audit = {
            "connector_id": "mock.email",
            "method": "send",
            "params_sha256": "b" * 64,
            "actor_user_id": "test-user-001",
            "org_id": "test-org-001",
            "approval_id": "approval-1",
            "started_at": "2026-11-20T00:00:00+00:00",
            "finished_at": "2026-11-20T00:00:01+00:00",
            "duration_ms": 1000,
        }
        attempts = {
            "first": _attempt(
                output={"message_id": "msg-1", "delivered_count": 1},
                audit=mail_audit,
                execution_id="exec-3",
            ),
            "replay2": _attempt(
                status="replayed",
                output={"message_id": "msg-1", "delivered_count": 1},
                audit=mail_audit,
                execution_id="exec-3",
                replayed_from="exec-3",
            ),
            "replay3": _attempt(
                status="replayed",
                output={"message_id": "msg-1", "delivered_count": 1},
                audit=mail_audit,
                execution_id="exec-3",
                replayed_from="exec-3",
            ),
        }
        external = {"mailbox_count": 1, "mailbox_first_subject": "test-subject-t4-003"}
    else:
        attempts = {"first": _attempt()}
        external = {}
    return RunRecord(task_id=task_id, run_index=run_index, attempts=attempts, external_state=external)


class TestScoring:
    def test_passing_record_scores_all_assertions_true(self) -> None:
        result = score_records([_passing_task_record("T4-001", 1)], TASKSET)
        assert result["task_scores"][0]["passed"] is True
        assert result["task_scores"][0]["failed_expressions"] == []

    def test_success_rate_denominator_keeps_failures(self) -> None:
        """分母不许改：失败运行保留在总表（05:54）。"""
        passing = _passing_task_record("T4-001", 1)
        failing = _passing_task_record("T4-001", 2)
        failing.attempts["first"]["output"] = {"count": 999}  # 破坏 count==len
        result = score_records([passing, failing], TASKSET)
        metrics = {metric["name"]: metric for metric in result["metrics"]}
        assert metrics["task_success_rate"]["denominator"] == 2
        assert metrics["task_success_rate"]["numerator"] == 1
        assert metrics["task_success_rate"]["rate"] == pytest.approx(0.5)

    def test_counts_separate_unique_tasks_and_runs(self) -> None:
        """唯一任务数与运行次数分列（05:47）。"""
        records = [
            _passing_task_record("T4-001", 1),
            _passing_task_record("T4-001", 2),
            _passing_task_record("T4-001", 3),
        ]
        result = score_records(records, TASKSET)
        assert result["counts"]["unique_task_count"] == 1
        assert result["counts"]["run_count"] == 3

    def test_idempotency_metric_uses_replay_attempts(self) -> None:
        result = score_records([_passing_task_record("T4-003", 1)], TASKSET)
        metrics = {metric["name"]: metric for metric in result["metrics"]}
        assert metrics["idempotency_rate"]["denominator"] == 2
        assert metrics["idempotency_rate"]["numerator"] == 2
        assert metrics["idempotency_rate"]["rate"] == 1.0

    def test_audit_completeness_metric_counts_nine_fields(self) -> None:
        result = score_records([_passing_task_record("T4-001", 1)], TASKSET)
        metrics = {metric["name"]: metric for metric in result["metrics"]}
        assert metrics["audit_completeness_rate"]["denominator"] == 1
        assert metrics["audit_completeness_rate"]["numerator"] == 1

    def test_audit_incomplete_fails_completeness(self) -> None:
        """审计缺九必填之一 ⇒ 完备率腿判 0（51:46 三腿单独统计）。

        冻结 84 条断言不绑 audit.duration_ms（逐字不可改）——任务成功率只判
        断言绑定的字段，故该运行任务面仍通过；九必填完备率是**独立指标腿**，
        正是它兜住「断言不绑定的必填字段缺失」，两腿都进报告不互相藏分。
        """
        record = _passing_task_record("T4-001", 1)
        del record.attempts["first"]["audit"]["duration_ms"]
        result = score_records([record], TASKSET)
        metrics = {metric["name"]: metric for metric in result["metrics"]}
        assert metrics["audit_completeness_rate"]["numerator"] == 0
        assert metrics["task_success_rate"]["numerator"] == 1

    def test_metrics_carry_wilson_intervals(self) -> None:
        result = score_records([_passing_task_record("T4-001", 1)], TASKSET)
        for metric in result["metrics"]:
            low, high = metric["wilson_95"]
            assert 0.0 <= low <= high <= 1.0

    def test_scorer_does_not_modify_task_set(self) -> None:
        """评分器只消费不改断言（05:41）——任务集文件 sha256 不变。"""
        import hashlib

        before = hashlib.sha256(TASKSET.read_bytes()).hexdigest()
        score_records([_passing_task_record("T4-001", 1)], TASKSET)
        after = hashlib.sha256(TASKSET.read_bytes()).hexdigest()
        assert before == after

    def test_unknown_task_id_scores_zero_assertions(self) -> None:
        """任务集外的记录不静默通过——断言数 0 ⇒ 通过判定按「无断言不通过」处理。"""
        result = score_records([_record("T4-999", 1, attempts={"first": _attempt()})], TASKSET)
        score = result["task_scores"][0]
        assert score["assertions"] == []
        assert score["passed"] is False
