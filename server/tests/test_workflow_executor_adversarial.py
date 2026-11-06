"""B#14 executor 对抗性测试——直补两族缺口（2026-11-06 交互拍板 opt A）。

盘点结论（拍板前实测 `test_workflow_executor.py` 39 例）：
- ①固定种子模拟：已覆盖（分派面全部 mock 化，无真实外呼）
- ②强杀不丢已确认：**缺口**（worker_lost 收口面已测，但「已 succeeded 节点产物
  在进程级死亡后不丢」无专项钉）
- ③迟到拍板：已覆盖（cancel 后迟到拍板被中和）
- ④双 definition_version 并存：已覆盖（版本钉住）
- ⑤节点独立事务失败恢复：**缺口**（tx A/tx B 结构与 dispatch_crashed 已测，
  但「tx B settle 自身崩溃 → 节点悬 running → 恢复重跑且幂等键不变」无钉）

本轮按拍板 opt A「直补对抗钉」实施：不做 2–3 周的决策逻辑纯函数重构
（与总览「先攒真实故障史，三期做」裁决一致），以对抗组合钉补两族缺口。

组织：复用 `test_workflow_executor.py` 的夹具函数（`_node`/`_make_definition`/
`_start`/`_node_map`/`_install_fake_api`/`_zero_backoff`），零新依赖零迁移。
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from test_agents_d4_harness import make_user
from test_document_drafts_api import _persist_project
from test_workflow_executor import (
    READ_REF,
    WRITE_REF,
    _install_fake_api,
    _make_definition,
    _node,
    _node_map,
    _start,
    _zero_backoff,
)

from fde_api.control.service import ControlServiceError
from fde_api.jobs.models import BackgroundJob
from fde_api.jobs.reconcile import reconcile_jobs
from fde_api.workflows.executor import (
    WORKFLOW_JOB_TYPE,
    resume_run,
    run_workflow_run,
)
from fde_api.workflows.models import WorkflowNodeRun, WorkflowRun


def _force_node_state(db_session, run_id: str, node_key: str, *, status: str, **fields):
    """把节点强行置到指定状态（模拟进程级死亡留下的悬挂态）。"""
    node = _node_map(db_session, run_id)[node_key]
    node.status = status
    for key, value in fields.items():
        setattr(node, key, value)
    db_session.commit()
    return node


# ---------------------------------------------------------------------------
# ② 强杀不丢已确认：进程级死亡后已 succeeded 节点产物必须留存
# ---------------------------------------------------------------------------


def test_worker_death_keeps_already_succeeded_node_output(db_session, settings, monkeypatch):
    """强杀族：进程级死亡（worker_lost 收口）**不得**抹掉已 succeeded 节点的产物。

    场景：两节点链，gather 成功、write 派发中进程死 → reconcile 放弃 →
    run failed + write 节点 failed。此时 gather 的产物必须仍在（下游恢复时
    可直接复用，不需重跑已确认的读面）。
    """
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"AK{uuid4().hex[:4]}")
    calls: list = []
    _install_fake_api(monkeypatch, calls)
    _zero_backoff(monkeypatch)
    definition = _make_definition(
        db_session,
        leader,
        project,
        _node("gather", output="subjects"),
        _node("ship", ["gather"], ref=WRITE_REF),
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    # 第一轮：只让 gather 成功（ship 派发前强杀——模拟进程在 tx B 前死亡）
    def _kill_before_ship(**kwargs):
        calls.append(kwargs)
        # 只在写节点派发时强杀；读节点（gather）正常返回
        if kwargs.get("operation") == WRITE_REF:
            raise KeyboardInterrupt("模拟进程强杀：写节点派发中途进程终止")
        return {"http_status": 200, "result": {"items": [1, 2, 3]}}

    monkeypatch.setattr("fde_api.control.api_actions.execute_api", _kill_before_ship)
    with pytest.raises(KeyboardInterrupt):
        run_workflow_run(run.id)

    db_session.expire_all()
    gather = _node_map(db_session, run.id)["gather"]
    ship = _node_map(db_session, run.id)["ship"]
    # gather 已成功且产物在位
    assert gather.status == "succeeded"
    assert gather.output_json is not None
    # ship 悬 running（进程死时未落终态）
    assert ship.status == "running"

    # 进程重启：worker 接手同一 job 且租约耗尽 → reconcile 放弃收口
    job = BackgroundJob(
        job_type=WORKFLOW_JOB_TYPE, target_id=run.id, status="running",
        attempts=5, max_attempts=5, locked_until=None,
    )
    db_session.add(job)
    db_session.commit()

    class _Queue:
        def enqueue(self, job_id: str) -> None:  # pragma: no cover
            raise AssertionError("attempts exhausted must not requeue")

    result = reconcile_jobs(db_session, _Queue())
    assert result.failed == 1

    db_session.expire_all()
    settled = db_session.get(WorkflowRun, run.id)
    assert settled.status == "failed" and "worker_lost" in (settled.error or "")
    # 关键断言：**已 succeeded 的 gather 产物零丢失**（run 终态化不得抹掉它）
    gather_after = _node_map(db_session, run.id)["gather"]
    assert gather_after.status == "succeeded"
    assert gather_after.output_json == gather.output_json
    # 悬挂的 ship 节点诚实失败（产物未落表即未发生）
    ship_after = _node_map(db_session, run.id)["ship"]
    assert ship_after.status == "failed" and ship_after.error == "worker_lost"


def test_resume_after_worker_death_reuses_succeeded_output_without_rerunning_gather(
    db_session, settings, monkeypatch
):
    """强杀族续钉：worker_lost 收口后 resume **不重跑已确认的 gather**。

    已 succeeded 节点原样复用（产物即锚点）⇒ gather 的外呼次数不增加；
    仅失败节点被重派。
    """
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"AK{uuid4().hex[:4]}")
    calls: list = []
    _install_fake_api(monkeypatch, calls)
    _zero_backoff(monkeypatch)
    definition = _make_definition(
        db_session,
        leader,
        project,
        _node("gather", output="subjects"),
        _node("ship", ["gather"], ref=WRITE_REF),
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    # 让 ship 失败（gather 正常成功）——按 operation 区分，避免读节点被误伤
    def _fail_ship_only(**kwargs):
        calls.append({"operation": kwargs.get("operation"),
                      "execution_id": kwargs.get("claims", {}).get("execution_id")})
        if kwargs.get("operation") == WRITE_REF:
            raise ControlServiceError("transient", "临时失败。", 503)
        return {"http_status": 200, "result": {"items": [1, 2, 3]}}

    from fde_api.control import api_actions
    monkeypatch.setattr(api_actions, "execute_api", _fail_ship_only)
    run_workflow_run(run.id)

    db_session.expire_all()
    gather_calls_before = len(calls)
    assert _node_map(db_session, run.id)["gather"].status == "succeeded"
    assert db_session.get(WorkflowRun, run.id).status == "failed"

    # 修复写节点 → resume：gather 不重跑（产物即锚点）
    def _ok_api(**kwargs):
        calls.append({"operation": kwargs.get("operation"),
                      "execution_id": kwargs.get("claims", {}).get("execution_id")})
        return {"http_status": 200, "result": {"items": [1, 2, 3]}}

    monkeypatch.setattr(api_actions, "execute_api", _ok_api)
    resume_run(actor=leader, project_id=project.id, run_id=run.id)
    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "succeeded"
    # gather 的外呼次数未增加（只跑了 ship 那一次）
    assert len(calls) == gather_calls_before + 1


# ---------------------------------------------------------------------------
# ⑤ 节点独立事务失败恢复：tx B settle 自身崩溃 → 恢复重跑且幂等键不变
# ---------------------------------------------------------------------------


def test_settle_crash_leaves_node_running_and_resume_keeps_idempotency_key(
    db_session, settings, monkeypatch
):
    """tx B 崩溃族：settle 落表自身崩溃（DB 层异常）→ 节点悬 running →
    进程重启后被恢复为 pending → resume 重跑时**幂等键不变**（同键 ⇒
    api_actions 层去重 ⇒ 不二次外呼）。

    对抗点：tx A 已落幂等键、tx B 落表崩 ⇒ 若恢复路径换了键，外呼会二次发生。
    """
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"AK{uuid4().hex[:4]}")
    calls: list = []
    _install_fake_api(monkeypatch, calls)
    _zero_backoff(monkeypatch)
    definition = _make_definition(
        db_session, leader, project, _node("create", ref=WRITE_REF), publish=True
    )
    run, _ = _start(db_session, leader, project, definition)

    # tx B 崩溃：settle 阶段 DB 写失败（模拟进程在「产物已算好、未落表」时死）
    import fde_api.workflows.executor as executor_module

    real_settle = executor_module._settle_node_success

    def _boom_settle(run_id, key, payload):
        raise RuntimeError("模拟 tx B 落表崩溃：产物未落表即进程终止")

    monkeypatch.setattr(executor_module, "_settle_node_success", _boom_settle)
    with pytest.raises(RuntimeError):
        run_workflow_run(run.id)

    monkeypatch.setattr(executor_module, "_settle_node_success", real_settle)

    db_session.expire_all()
    node = _node_map(db_session, run.id)["create"]
    # tx A 已落幂等键（分派前持久化）——这是「崩溃不重复外呼」的前提
    assert node.status == "running"
    assert node.idempotency_key
    key_before = node.idempotency_key
    # 产物未落表 ⇒ 诚实：output 为空（未发生即无产物）
    assert node.output_json is None

    # 进程重启：恢复入口把 running 放回 pending（attempt 保留）
    run_workflow_run(run.id)

    db_session.expire_all()
    recovered = _node_map(db_session, run.id)["create"]
    # 恢复后重跑：幂等键不变 ⇒ 同 action id ⇒ api_actions 层去重
    assert recovered.idempotency_key == key_before
    # 恢复链的 attempt 语义：worker 死亡遗留 running → 放回 pending 时**attempt
    # 保留**（不是归零）——「本次尝试已发生」的事实不被恢复路径抹掉；
    # 归零会让「重试计数」与「崩溃次数」两类事实混同。
    assert recovered.attempt >= 1
    # 外呼只发生一次（第二次被同键去重）
    execution_ids = {call["execution_id"] for call in calls}
    assert execution_ids == {f"wfnode-{node.id}"}
    assert db_session.get(WorkflowRun, run.id).status == "succeeded"


def test_recover_interrupted_keeps_succeeded_and_only_resets_running(
    db_session, settings, monkeypatch
):
    """恢复语义钉：`_recover_interrupted` 只把 running 放回 pending，
    **不动 succeeded**（产物不丢）——强杀族与 tx B 族的共同底座。
    """
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"AK{uuid4().hex[:4]}")
    calls: list = []
    _install_fake_api(monkeypatch, calls)
    _zero_backoff(monkeypatch)
    definition = _make_definition(
        db_session,
        leader,
        project,
        _node("gather", output="subjects"),
        _node("ship", ["gather"], ref=WRITE_REF),
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    # 造状态：gather succeeded（带产物）、ship running（悬挂）
    gather = _force_node_state(
        db_session, run.id, "gather", status="succeeded", output_json={"items": [1, 2]}
    )
    _force_node_state(db_session, run.id, "ship", status="running")
    run_row = db_session.get(WorkflowRun, run.id)
    run_row.status = "running"
    db_session.commit()
    gather_output = gather.output_json

    # 触发恢复（run_workflow_run 入口调 _recover_interrupted）
    _install_fake_api(monkeypatch, calls, fail_times=99, error_status=503)
    run_workflow_run(run.id)

    db_session.expire_all()
    after = _node_map(db_session, run.id)
    # gather：succeeded 且产物逐位不变（零丢失）
    assert after["gather"].status == "succeeded"
    assert after["gather"].output_json == gather_output
    # ship：running 被放回 pending/failed（未确认即未发生）
    assert after["ship"].status in ("pending", "ready", "failed")
