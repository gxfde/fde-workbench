"""Admin 后台任务取消面（V3 T-J2，域 14）：POST /api/v1/admin/jobs/{id}/cancel。

验收口径钉四件事：幂等（已取消再取消 200 cancelled=false / 终态 409）、
不强杀（running+活租约 409 job_running；过期租约=worker 已死可接管）、
留痕（operation_events job_cancelled 只落元数据）、不复活（outbox
pending+dispatched 一并收口，reconcile 不再重排）。
"""

from dataclasses import dataclass
from uuid import uuid4

import pytest

from conftest import INITIAL_PASSWORD as PASSWORD

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.jobs.models import BackgroundJob, OutboxEvent
from fde_api.jobs.outbox import dispatch_pending, enqueue_outbox
from fde_api.jobs.reconcile import reconcile_jobs
from fde_api.workbench.models import OperationEvent


@dataclass(frozen=True)
class AuthorizedClient:
    client: object
    user: User
    headers: dict[str, str]

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)


@pytest.fixture
def authorized_client_factory(client, db_session, settings):
    def create(role: str) -> AuthorizedClient:
        user = User(
            username=f"{role}.{uuid4().hex}",
            display_name=role,
            role=role,
            password_hash=hash_password(PASSWORD),
            must_change_password=False,
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        return AuthorizedClient(
            client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
        )

    return create


class _Queue:
    def enqueue(self, job_id: str) -> None:
        pass


def _job_with_outbox(db_session, *, status: str = "queued", **kwargs):
    """造 job + 同键两条 outbox 事件（一条 dispatched 一条 pending）。"""
    topic = kwargs.pop("job_type", "file.scan")
    target = kwargs.pop("target_id", f"t-{uuid4().hex[:8]}")
    enqueue_outbox(db_session, topic, target, {"n": 1})
    db_session.commit()
    dispatch_pending(db_session, _Queue())  # 事件1→dispatched，job 落 pending
    enqueue_outbox(db_session, topic, target, {"n": 2})
    db_session.commit()  # 事件2 留 pending
    job = db_session.query(BackgroundJob).filter_by(job_type=topic, target_id=target).one()
    job.status = status
    for key, value in kwargs.items():
        setattr(job, key, value)
    db_session.commit()
    return job


def _cancel(admin: AuthorizedClient, job_id: str):
    return admin.post(f"/api/v1/admin/jobs/{job_id}/cancel")


def test_admin_cancels_queued_job_with_outbox_and_audit(db_session, authorized_client_factory):
    """主路径：取消落终态 + outbox pending/dispatched 双收口 + operation_event 留痕。"""
    admin = authorized_client_factory("admin")
    job = _job_with_outbox(db_session, status="queued")

    response = _cancel(admin, job.id)

    assert response.status_code == 200
    payload = response.json["data"]
    assert payload["cancelled"] is True
    assert payload["status"] == "cancelled"
    db_session.refresh(job)
    assert job.status == "cancelled"
    assert job.last_error == "cancelled_by_admin"
    assert job.locked_until is None and job.locked_by is None
    events = db_session.query(OutboxEvent).all()
    assert {event.status for event in events} == {"failed"}
    assert all(event.last_error == "cancelled_by_admin" for event in events)
    audit = db_session.query(OperationEvent).filter_by(target_id=job.id).one()
    assert audit.event_type == "job_cancelled"
    assert audit.actor_user_id == admin.user.id
    assert audit.changes["previous_status"] == "queued"
    assert audit.changes["job_type"] == "file.scan"
    # 域 14 验收：取消后 reconcile 不再重排
    result = reconcile_jobs(db_session, _Queue())
    assert result.scanned == 0
    assert result.requeued == 0


def test_cancel_is_idempotent_for_already_cancelled_job(db_session, authorized_client_factory):
    admin = authorized_client_factory("admin")
    job = _job_with_outbox(db_session, status="queued")
    _cancel(admin, job.id)

    second = _cancel(admin, job.id)

    assert second.status_code == 200
    assert second.json["data"]["cancelled"] is False
    assert second.json["data"]["status"] == "cancelled"
    audits = db_session.query(OperationEvent).filter_by(target_id=job.id).all()
    assert len(audits) == 1  # 幂等重放不追加留痕


@pytest.mark.parametrize("status", ["succeeded", "failed"])
def test_cancel_refuses_terminal_jobs(db_session, authorized_client_factory, status):
    admin = authorized_client_factory("admin")
    job = _job_with_outbox(db_session, status=status)

    response = _cancel(admin, job.id)

    assert response.status_code == 409
    assert response.json["error"]["code"] == "already_terminal"


def test_cancel_refuses_running_job_with_live_lease(db_session, authorized_client_factory):
    """不强杀：租约未过期 = worker 可能活着，强行终止只会丢结果烧外呼。"""
    from datetime import UTC, datetime, timedelta

    admin = authorized_client_factory("admin")
    job = _job_with_outbox(
        db_session,
        status="running",
        locked_until=datetime.now(UTC) + timedelta(minutes=5),
        locked_by="worker-123-abc",
    )

    response = _cancel(admin, job.id)

    assert response.status_code == 409
    assert response.json["error"]["code"] == "job_running"
    db_session.refresh(job)
    assert job.status == "running"


def test_cancel_takes_over_running_job_with_expired_lease(db_session, authorized_client_factory):
    """租约已过期 = worker 已死：取消是安全接管，迟到 settle 被终态守卫拒绝。"""
    from datetime import UTC, datetime, timedelta

    admin = authorized_client_factory("admin")
    job = _job_with_outbox(
        db_session,
        status="running",
        locked_until=datetime.now(UTC) - timedelta(minutes=1),
        locked_by="worker-dead-abc",
    )

    response = _cancel(admin, job.id)

    assert response.status_code == 200
    assert response.json["data"]["cancelled"] is True
    db_session.refresh(job)
    assert job.status == "cancelled"


def test_admin_can_cancel_pending_job(db_session, authorized_client_factory):
    admin = authorized_client_factory("admin")
    job = _job_with_outbox(db_session, status="pending")

    response = _cancel(admin, job.id)

    assert response.status_code == 200
    assert response.json["data"]["cancelled"] is True
    db_session.refresh(job)
    assert job.status == "cancelled"


def test_cancel_requires_admin_role(db_session, authorized_client_factory):
    lead = authorized_client_factory("project_lead")
    job = _job_with_outbox(db_session, status="queued")

    response = _cancel(lead, job.id)

    assert response.status_code == 403
    assert response.json["error"]["code"] == "job_cancel_forbidden"
    db_session.refresh(job)
    assert job.status == "queued"  # 未被取消


def test_cancel_unknown_job_returns_404(db_session, authorized_client_factory):
    admin = authorized_client_factory("admin")

    response = _cancel(admin, "does-not-exist")

    assert response.status_code == 404
    assert response.json["error"]["code"] == "job_not_found"
