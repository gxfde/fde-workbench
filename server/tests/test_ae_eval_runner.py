"""AE1-WP5-B：公开集全量评测 runner 钉（5 任务 × 3 独立运行 → 报告门禁）。

门槛纪律（05 号 §5 AE1 行，2026-11-20 P1 出口轮转正——评审补强 G3-10/B-1）：
报告信封门槛位标注**「已冻结（05 §5 AE1 行）」**（出口时点草案口径已停用）；
唯一任务数与运行次数分列（05:47），分母不许改（05:54），预登记分母锚不符
时显著标注（B-2）；合成 failed 记录按契约形态（B-3：error 三键／execution_id
占位／零越界键）。

评分链（05:41「评分器只消费落盘记录」）：runner 产记录 → JSONL 落盘 →
``load_records`` 回读 → ``score_records`` 判定——跑与判同形态，零内存直通。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

import _ae_mock_stack as mock_stack_module
from ae_eval.records import RunRecord, load_records, write_records
from ae_eval.runner import (
    RUNS,
    _infra_reasons,
    _submit_attempt,
    build_report,
    load_public_tasks,
    provision_pinned_world,
    run_public_eval,
    write_report,
)
from ae_eval.scorer import score_records

TASKSET = Path(__file__).resolve().parents[1] / "tests" / "ae_eval" / "taskset_v1.json"


@pytest.fixture(scope="module")
def mock_stack():
    """ephemeral 桩端口（跨 worker 与固定端口桩文件共存——WP5-B 装置面）。"""
    stack = mock_stack_module.MockStack(erp_port=0, email_port=0)
    stack.start()
    yield stack
    stack.stop()


@pytest.fixture(scope="module")
def wb_service(test_settings):
    svc = mock_stack_module.WorkbenchService(test_settings)
    svc.start()
    yield svc
    svc.stop()


@pytest.fixture(scope="module")
def wb_port(wb_service):
    return wb_service.port


class TestRunnerAssembly:
    def test_public_tasks_loaded_verbatim(self) -> None:
        """runner 装配：公开集 5 任务清单＋冻结输入逐字（不改写不脱敏改形）。"""
        tasks = load_public_tasks()
        assert [task["id"] for task in tasks] == ["T4-001", "T4-002", "T4-003", "T4-004", "T4-005"]
        assert tasks[0]["input"]["idempotency_key"] == "test-idem-t4-001-a"
        assert tasks[2]["input"]["params"]["subject"] == "test-subject-t4-003"
        assert tasks[3]["input"]["dry_run"] is True

    def test_report_gate_annotated_frozen_per_05(self) -> None:
        """报告信封门槛位＝「已冻结（05 §5 AE1 行）」（评审补强 G3-10/B-1：转正口径）。"""
        report = build_report(score_records([], TASKSET))
        assert report["gate"]["status"] == "已冻结（05 §5 AE1 行，2026-11-20 转正）"
        assert "≥90%" in report["gate"]["reference"]
        assert "05-evaluation-and-gates.md" in report["gate"]["reference"]
        assert report["counts"]["run_count"] == 0


class TestSyntheticFailureShape:
    """评审补强 G3-12/B-3：合成 failed 记录须为契约形态（error 三键／
    execution_id 非空占位／零越界键；audit={}＝审计纪律不伪造）。"""

    def _payload(self, ae_world: dict[str, Any]) -> dict[str, Any]:
        return {
            "action_id": "mock.email.send",
            "action_type": "send_email",
            "connector_id": "mock.email",
            "method": "send",
            "params": {"to": "ops@example.test", "subject": "s-shape", "body": "b-shape"},
            "idempotency_key": "idem-shape-" + __import__("uuid").uuid4().hex[:8],
            "org_id": ae_world["org"].id,
            "requester_id": ae_world["user"].id,
            "dry_run": False,
            "risk_level": 0,
            "timeout_seconds": 30,
        }

    class _AllowAllGate:
        """放行桩：L3 直通（本组钉只看执行段折叠形态）。"""

        def check(self, connector_id: str, method: str) -> None:
            return None

    class _DomainErrorDispatch:
        """域错误 dispatch（模拟执行段域内失败）。"""

        def call(self, request: dict) -> dict:
            from fde_api.action_execution.errors import ActionExecutionError

            raise ActionExecutionError("tool_not_allowed", "连接器上游调用失败（模拟）。")

    class _InfraErrorDispatch:
        """非域异常 dispatch（基础设施失败归因面——经 service 兜底 P6 映射）。"""

        def call(self, request: dict) -> dict:
            raise RuntimeError("boom-infra")

    def test_domain_error_shape_is_contract_form(self, ae_world_runner) -> None:
        record = _submit_attempt(ae_world_runner["user"], self._payload(ae_world_runner), self._AllowAllGate(), self._DomainErrorDispatch())
        assert record["status"] == "failed"
        assert isinstance(record["execution_id"], str) and record["execution_id"].startswith("not-issued-")
        error = record["error"]
        assert error["code"] == "tool_not_allowed"  # 闭集码
        assert error["retryable"] is False  # 域错误不可重试
        assert 1 <= len(error["message"]) <= 500
        assert "_infra_exception" not in record  # 越界键已移除

    def test_infra_error_shape_is_contract_form(self, ae_world_runner) -> None:
        record = _submit_attempt(ae_world_runner["user"], self._payload(ae_world_runner), self._AllowAllGate(), self._InfraErrorDispatch())
        assert record["status"] == "failed"
        assert isinstance(record["execution_id"], str) and record["execution_id"].startswith("not-issued-")
        error = record["error"]
        assert error["code"] == "tool_not_allowed"  # 闭集映射（Q8 口径）
        assert error["retryable"] is True  # 基础设施失败可重试
        assert error["details"]["reason"] == "RuntimeError"  # 归因在 details
        assert "_infra_exception" not in record  # 越界键已移除

    def test_infra_reasons_reads_error_details_not_out_of_band_key(self) -> None:
        """note 归因改读闭集 error.details.reason（越界键通道已拆）。"""
        domain_failed = {"error": {"code": "tool_not_allowed", "retryable": False, "details": {"reason": "x"}}}
        infra_failed = {"error": {"code": "tool_not_allowed", "retryable": True, "details": {"reason": "RuntimeError"}}}
        ok = {"error": None}
        assert _infra_reasons({"first": infra_failed, "replay2": domain_failed, "replay3": ok}) == ["RuntimeError"]
        assert _infra_reasons({"first": ok}) == []


@pytest.fixture
def ae_world_runner(db_session):
    """字面 ID 评测世界（org/user/project 占位主键真身）。"""
    return provision_pinned_world(db_session)


class TestPublicEval:
    def test_public_taskset_three_runs_full_report(
        self, db_session, test_settings, mock_stack, wb_service, wb_port, tmp_path
    ) -> None:
        """5 任务 × 3 独立运行 → 15 运行逐断言判定（评分链只消费落盘记录）。

        期望形态（计数锚）：唯一任务 5 / 运行 15 / 断言判定 252（84×3）/
        幂等复放检查 12（T4-003、T4-005 × replay2/replay3 × 3 轮）/ 审计完备
        尝试 27（每轮 1+1+3+1+3 个 attempt）。
        """
        world = provision_pinned_world(db_session)
        records = run_public_eval(
            db_session=db_session,
            actor=world["user"],
            test_settings=test_settings,
            stack=mock_stack,
            wb_port=wb_port,
            runs=RUNS,
        )
        records_path = write_records(records, tmp_path / "ae1-records.jsonl")
        result = score_records(load_records(records_path), TASKSET, expected_runs=RUNS * 5)

        assert result["counts"]["unique_task_count"] == 5
        assert result["counts"]["run_count"] == 15
        assert result["counts"]["assertion_evaluations"] == 252  # 84 冻结断言 × 3 运行
        assert "denominator_mismatch" not in result  # 分母锚一致（B-2）

        metrics = {metric["name"]: metric for metric in result["metrics"]}
        assert metrics["task_success_rate"]["numerator"] == 15
        assert metrics["idempotency_rate"]["numerator"] == 12
        assert metrics["audit_completeness_rate"]["numerator"] == 27

        # 失败诊断面：任一运行未过全断言 → 断言体逐条列出（不许静默）
        failed = [score for score in result["task_scores"] if not score["passed"]]
        assert not failed, json.dumps(
            [
                {
                    "task": score["task_id"],
                    "run": score["run_index"],
                    "note": score["note"],
                    "failed": score["failed_expressions"],
                }
                for score in failed
            ],
            ensure_ascii=False,
            indent=1,
        )

        # 门槛（已冻结·05 §5 AE1 行——G3-10/B-1 转正口径）
        assert metrics["task_success_rate"]["rate"] >= 0.9
        assert metrics["idempotency_rate"]["rate"] == 1.0
        assert metrics["audit_completeness_rate"]["rate"] == 1.0

        report = build_report(result)
        assert report["gate"]["status"] == "已冻结（05 §5 AE1 行，2026-11-20 转正）"

        # 交付证据出口（WP5-C：AE1_EVAL_OUT 指定目录时落报告＋记录副本）
        out_dir = os.environ.get("AE1_EVAL_OUT")
        if out_dir:
            root = Path(out_dir)
            write_report(report, root / "ae1-eval-report.json")
            write_records(load_records(records_path), root / "ae1-records.jsonl")


def _run_record(task_id: str, run_index: int) -> RunRecord:
    return RunRecord(task_id=task_id, run_index=run_index, attempts={}, external_state={})
