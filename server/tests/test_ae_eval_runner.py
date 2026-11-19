"""AE1-WP5-B：公开集全量评测 runner 钉（5 任务 × 3 独立运行 → 报告门禁）。

门槛纪律（53 号 §2.3）：报告信封门槛位标注**「未冻结（附录草案口径）」**——
本钉只按 51 号 §4.2 草案下限断言（T4 成功率 ≥90%），不声称已达成 05 号
AE1 门禁；唯一任务数与运行次数分列（05:47），分母不许改（05:54）。

评分链（05:41「评分器只消费落盘记录」）：runner 产记录 → JSONL 落盘 →
``load_records`` 回读 → ``score_records`` 判定——跑与判同形态，零内存直通。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import _ae_mock_stack as mock_stack_module
from ae_eval.records import load_records, write_records
from ae_eval.runner import (
    RUNS,
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

    def test_report_gate_annotated_unfrozen(self) -> None:
        """报告信封门槛位＝「未冻结（附录草案口径）」（53 号 §2.3 逐字）。"""
        report = build_report(score_records([], TASKSET))
        assert report["gate"]["status"] == "未冻结（附录草案口径）"
        assert "≥90%" in report["gate"]["reference"]
        assert report["counts"]["run_count"] == 0


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
        result = score_records(load_records(records_path), TASKSET)

        assert result["counts"]["unique_task_count"] == 5
        assert result["counts"]["run_count"] == 15
        assert result["counts"]["assertion_evaluations"] == 252  # 84 冻结断言 × 3 运行

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

        # 门槛下限（未冻结·附录草案口径——51 号 §4.2）
        assert metrics["task_success_rate"]["rate"] >= 0.9
        assert metrics["idempotency_rate"]["rate"] == 1.0
        assert metrics["audit_completeness_rate"]["rate"] == 1.0

        report = build_report(result)
        assert report["gate"]["status"] == "未冻结（附录草案口径）"

        # 交付证据出口（WP5-C：AE1_EVAL_OUT 指定目录时落报告＋记录副本）
        out_dir = os.environ.get("AE1_EVAL_OUT")
        if out_dir:
            root = Path(out_dir)
            write_report(report, root / "ae1-eval-report.json")
            write_records(load_records(records_path), root / "ae1-records.jsonl")
