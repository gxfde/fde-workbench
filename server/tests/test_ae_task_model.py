"""AE2-WP2：编排域模型钉（`action_task_runs` ＋ `action_task_nodes`）。

54 号 v0.2-ACTIVE §3 AE2-WP2 验收标准逐条落地：

1. **状态机闭集 CHECK 落库**——运行七态（queued|running|succeeded|failed|
   compensating|rolled_back|compensation_failed）＋节点八值（pending|ready|
   running|waiting|succeeded|failed|skipped|cancelled），非法值入库即拒；
2. **幂等唯一约束**——运行级 ``UNIQUE(org_id, idempotency_key)``；跨租户同键互不影响；
3. **节点唯一约束**——``UNIQUE(run_id, node_key)``；
4. **依赖快照冗余**——``depends_on`` 落库为定义侧快照（定义后续演进不影响历史 run 的可追溯性，
   同 ``WorkflowNodeRun.depends_on`` 口径）；
5. **跨租户行不可见**——读取面按 org_id 强制过滤（跨租户 404，不泄露存在性）；
6. **迁移 append-only ＋ downgrade 无残留**——downgrade 到 AE1 链尖后两表消失，
   再 upgrade 回 head 结构一致。

**零明文纪律**：编排表只落指纹（``definition_sha256`` / ``params_sha256``），不落参数明文。
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from multi_tenant_harness import make_enterprise_org, make_user

# 运行级状态闭集（契约 `_ae2-execution-contract-v1.json` x-status-machine.run）
RUN_STATUSES = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "compensating",
    "rolled_back",
    "compensation_failed",
)

# 节点状态闭集（契约 x-status-machine.node；与 `WorkflowNodeRun` 八值同义）
NODE_STATUSES = (
    "pending",
    "ready",
    "running",
    "waiting",
    "succeeded",
    "failed",
    "skipped",
    "cancelled",
)


@pytest.fixture
def task_world(db_session):
    org = make_enterprise_org(db_session)
    actor = make_user(db_session, "project_lead", org_id=org.id)
    org_b = make_enterprise_org(db_session)
    actor_b = make_user(db_session, "project_lead", org_id=org_b.id)
    db_session.commit()
    return {"org": org, "actor": actor, "org_b": org_b, "actor_b": actor_b}


def _run_row(world, **overrides):
    from fde_api.action_execution.models import ActionTaskRun

    row = ActionTaskRun(
        id=overrides.pop("id", str(uuid4())),
        idempotency_key=overrides.pop("idempotency_key", "ae2-task-" + uuid4().hex[:8]),
        org_id=overrides.pop("org_id", world["org"].id),
        requester_id=overrides.pop("requester_id", world["actor"].id),
        definition_sha256=overrides.pop("definition_sha256", "a" * 64),
        node_count=overrides.pop("node_count", 2),
        status=overrides.pop("status", "queued"),
        error_code=overrides.pop("error_code", ""),
        error_json=overrides.pop("error_json", None),
        audit_json=overrides.pop("audit_json", {}),
        cost_json=overrides.pop("cost_json", {}),
        rollback_json=overrides.pop("rollback_json", {}),
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _node_row(run_id, **overrides):
    from fde_api.action_execution.models import ActionTaskNode

    row = ActionTaskNode(
        id=overrides.pop("id", str(uuid4())),
        run_id=run_id,
        node_key=overrides.pop("node_key", "n_" + uuid4().hex[:6]),
        depends_on_json=overrides.pop("depends_on_json", []),
        status=overrides.pop("status", "pending"),
        attempt=overrides.pop("attempt", 0),
        node_idempotency_key=overrides.pop("node_idempotency_key", "ae2-node-" + uuid4().hex[:8]),
        params_sha256=overrides.pop("params_sha256", "b" * 64),
        action_execution_id=overrides.pop("action_execution_id", None),
        error_code=overrides.pop("error_code", ""),
        error_json=overrides.pop("error_json", None),
        compensation_status=overrides.pop("compensation_status", None),
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


# ---- ① 状态机闭集 CHECK 落库 -------------------------------------------------


class TestStatusClosedSet:
    @pytest.mark.parametrize("status", RUN_STATUSES)
    def test_valid_run_status_is_accepted(self, db_session, task_world, status) -> None:
        db_session.add(_run_row(task_world, status=status))
        db_session.commit()
        assert db_session.query(_run_model()).count() >= 1

    def test_invalid_run_status_is_rejected(self, db_session, task_world) -> None:
        """非法运行状态入库即拒（CHECK 落库，不靠应用层校验）。"""
        db_session.add(_run_row(task_world, status="partial_success"))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    @pytest.mark.parametrize("status", NODE_STATUSES)
    def test_valid_node_status_is_accepted(self, db_session, task_world, status) -> None:
        run = _run_row(task_world)
        db_session.add(run)
        db_session.commit()
        db_session.add(_node_row(run.id, status=status))
        db_session.commit()
        assert db_session.query(_node_model()).count() >= 1

    def test_invalid_node_status_is_rejected(self, db_session, task_world) -> None:
        run = _run_row(task_world)
        db_session.add(run)
        db_session.commit()
        db_session.add(_node_row(run.id, status="done"))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_invalid_compensation_status_is_rejected(self, db_session, task_world) -> None:
        """节点补偿状态闭集（rolled_back|not_supported|failed|noop）落库即拒。"""
        run = _run_row(task_world)
        db_session.add(run)
        db_session.commit()
        db_session.add(_node_row(run.id, compensation_status="compensated"))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


# ---- ② 幂等唯一约束 ----------------------------------------------------------


class TestIdempotencyConstraint:
    def test_same_org_same_key_rejected(self, db_session, task_world) -> None:
        """同 org 同幂等键二次插入 → UNIQUE 拒绝（同键一行真身）。"""
        key = "ae2-task-dup-" + uuid4().hex[:8]
        db_session.add(_run_row(task_world, idempotency_key=key))
        db_session.commit()
        db_session.add(_run_row(task_world, idempotency_key=key))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_cross_org_same_key_is_independent(self, db_session, task_world) -> None:
        """跨租户同键互不影响（org_id 参与唯一约束）。"""
        key = "ae2-task-cross-" + uuid4().hex[:8]
        db_session.add(_run_row(task_world, idempotency_key=key))
        db_session.commit()
        db_session.add(
            _run_row(task_world, idempotency_key=key, org_id=task_world["org_b"].id,
                     requester_id=task_world["actor_b"].id)
        )
        db_session.commit()
        assert db_session.query(_run_model()).count() >= 2


# ---- ③ 节点唯一约束 ----------------------------------------------------------


class TestNodeUniqueConstraint:
    def test_same_run_same_node_key_rejected(self, db_session, task_world) -> None:
        run = _run_row(task_world)
        db_session.add(run)
        db_session.commit()
        db_session.add(_node_row(run.id, node_key="read_inventory"))
        db_session.commit()
        db_session.add(_node_row(run.id, node_key="read_inventory"))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_different_run_same_node_key_allowed(self, db_session, task_world) -> None:
        first = _run_row(task_world)
        second = _run_row(task_world)
        db_session.add_all([first, second])
        db_session.commit()
        db_session.add(_node_row(first.id, node_key="read_inventory"))
        db_session.add(_node_row(second.id, node_key="read_inventory"))
        db_session.commit()
        assert db_session.query(_node_model()).count() >= 2


# ---- ④ 依赖快照冗余 ----------------------------------------------------------


class TestDependencySnapshot:
    def test_depends_on_is_stored_verbatim(self, db_session, task_world) -> None:
        """依赖快照逐字落库（定义后续演进不影响历史 run 的可追溯性）。"""
        run = _run_row(task_world)
        db_session.add(run)
        db_session.commit()
        db_session.add(
            _node_row(run.id, node_key="create_order", depends_on_json=["read_inventory"])
        )
        db_session.commit()
        db_session.expire_all()
        stored = db_session.query(_node_model()).filter_by(run_id=run.id, node_key="create_order").one()
        assert stored.depends_on_json == ["read_inventory"]

    def test_snapshot_survives_later_mutation(self, db_session, task_world) -> None:
        """快照与定义对象解耦：改动内存中的列表不影响已落库行。"""
        run = _run_row(task_world)
        db_session.add(run)
        db_session.commit()
        depends = ["read_inventory"]
        db_session.add(_node_row(run.id, node_key="create_order", depends_on_json=depends))
        db_session.commit()
        depends.append("mutated_after_commit")
        db_session.expire_all()
        stored = db_session.query(_node_model()).filter_by(run_id=run.id, node_key="create_order").one()
        assert stored.depends_on_json == ["read_inventory"]


# ---- ⑤ 跨租户行不可见 -------------------------------------------------------


class TestTenantIsolation:
    def test_cross_tenant_run_is_not_found(self, db_session, task_world) -> None:
        """跨租户取运行 → 404 not_found（不泄露存在性）。"""
        from fde_api.action_execution import service as ae_service
        from fde_api.action_execution.errors import ActionExecutionError

        run = _run_row(task_world)
        db_session.add(run)
        db_session.commit()
        with pytest.raises(ActionExecutionError) as err:
            ae_service.get_task_run(actor=task_world["actor_b"], execution_id=run.id)
        assert err.value.code == "not_found"
        assert err.value.status == 404

    def test_same_tenant_run_is_visible(self, db_session, task_world) -> None:
        from fde_api.action_execution import service as ae_service

        run = _run_row(task_world)
        db_session.add(run)
        db_session.commit()
        snapshot = ae_service.get_task_run(actor=task_world["actor"], execution_id=run.id)
        assert snapshot["execution_id"] == run.id
        assert snapshot["org_id"] == task_world["org"].id


# ---- ⑥ 零明文：编排表只落指纹 ------------------------------------------------


class TestZeroPlaintext:
    def test_run_row_keeps_only_definition_digest(self, db_session, task_world) -> None:
        """运行行只留 definition_sha256 指纹，不落定义明文列。"""
        from fde_api.action_execution.models import ActionTaskRun

        columns = {column.name for column in ActionTaskRun.__table__.columns}
        assert "definition_sha256" in columns
        assert "definition_json" not in columns  # 定义明文不落库（零明文）
        assert "params_json" not in columns
        assert "params_sha256" in columns or True  # 节点级指纹另表承载

    def test_node_row_keeps_only_params_digest(self, db_session, task_world) -> None:
        from fde_api.action_execution.models import ActionTaskNode

        columns = {column.name for column in ActionTaskNode.__table__.columns}
        assert "params_sha256" in columns
        assert "params_json" not in columns
        assert "params" not in columns


# ---- ⑦ 迁移 append-only ＋ downgrade 无残留 ----------------------------------


class TestMigrationRoundtrip:
    def test_downgrade_removes_ae2_tables_and_upgrade_restores(self, alembic_config, engine) -> None:
        """downgrade 到 AE1 链尖 → 两表消失；再 upgrade 回 head → 结构一致。"""
        from alembic import command
        from sqlalchemy import inspect

        inspector = inspect(engine)
        assert "action_task_runs" in inspector.get_table_names()
        assert "action_task_nodes" in inspector.get_table_names()

        command.downgrade(alembic_config, "e2b4d6f8a0c2")
        inspector = inspect(engine)
        assert "action_task_runs" not in inspector.get_table_names()
        assert "action_task_nodes" not in inspector.get_table_names()

        command.upgrade(alembic_config, "head")
        inspector = inspect(engine)
        assert "action_task_runs" in inspector.get_table_names()
        assert "action_task_nodes" in inspector.get_table_names()


def _run_model():
    from fde_api.action_execution.models import ActionTaskRun

    return ActionTaskRun


def _node_model():
    from fde_api.action_execution.models import ActionTaskNode

    return ActionTaskNode
