"""V3.1 P0-1：访谈事实与需求结构化（discovery 四表 + 抽取管线 + 审阅面）。

验收面（任务书 §5 + docs/v3.1/00-gap-register P0-1）：
- 契约整批失败零写入；来源定位闭合（line/transcript_segment/char_span）；
- 抽取幂等（同源同版本复用既有行）；重跑仅 failed（审阅痕迹不可覆盖）；
- 输出端脱敏兜底 + 复核事件（guidance 第③层同构）；
- 推断/开放问题强制待澄清；无来源事实的需求不得自动接受；
- 审阅终态不可逆（accepted/rejected），needs_clarification 可流转；
- 越权（viewer 创建/审阅 403；跨项目 404/403）。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from test_agents_d4_harness import ApiClient, api_client, issue_access_token, make_user
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _persist_project  # 项目工厂复用（enterprise_code 唯一）

from fde_api.discovery import jobs as discovery_jobs
from fde_api.discovery.contract import DiscoveryContractError, validate_extraction_output
from fde_api.discovery.models import (
    BusinessFact,
    DiscoveryExtraction,
    Requirement,
    RequirementSource,
)
from fde_api.jobs.models import OutboxEvent
from fde_api.transcripts.models import InterviewMinutes
from fde_api.workbench.models import OperationEvent, ProjectMember

_DICT_NAME = "合成测试集团"  # seeds/enterprise-names.txt 合成条目（零真实资料）


# ---------------------------------------------------------------------------
# 工厂


def _new_project(db_session, leader_user, tag: str):
    return _persist_project(db_session, leader_user, code=f"{tag}{uuid4().hex[:4]}·制造业·苏州")


def _member_client(db_session, d4_client, d4_settings, project) -> tuple[ApiClient, object]:
    user = make_user(db_session, "fde_engineer")
    db_session.add(ProjectMember(project_id=project.id, user_id=user.id, role="member"))
    db_session.commit()
    return ApiClient(d4_client, user, {"Authorization": f"Bearer {issue_access_token(user, d4_settings)}"}), user


def _viewer_client(db_session, d4_client, d4_settings, project) -> tuple[ApiClient, object]:
    user = make_user(db_session, "fde_engineer")
    db_session.add(ProjectMember(project_id=project.id, user_id=user.id, role="viewer"))
    db_session.commit()
    return ApiClient(d4_client, user, {"Authorization": f"Bearer {issue_access_token(user, d4_settings)}"}), user


def _minutes(db_session, project, leader_user, *, content: str = "第1行：询盘目前靠销售人工分配。\n第2行：排程用 Excel。") -> InterviewMinutes:
    import hashlib

    row = InterviewMinutes(
        project_id=project.id,
        created_by_user_id=leader_user.id,
        draft_id=None,
        title="初诊纪要",
        content=content,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        redaction_hits=0,
        client_confirmed_by="客户A-王总",
        client_confirmed_at=datetime.now(UTC) - timedelta(hours=2),
        client_confirmation_method="verbal",
    )
    db_session.add(row)
    db_session.commit()
    return row


def _valid_ai_payload() -> dict:
    return {
        "facts": [
            {
                "fact_type": "process",
                "subject": "询盘处理",
                "predicate": "当前步骤",
                "object_value": {"step": "销售人工分配"},
                "source_locator": {"type": "line", "line": 1},
                "confidence": 0.9,
            },
            {
                "fact_type": "pain_point",
                "subject": "生产排程",
                "predicate": "现状",
                "object_value": "排程用 Excel，改版频繁出错",
                "source_locator": {"type": "line", "line": 2},
            },
        ],
        "requirements": [
            {
                "title": "询奖自动分配",
                "requirement_type": "functional",
                "priority": "high",
                "acceptance_criteria": ["新建询盘 5 分钟内按规则分配到人"],
                "source_fact_indexes": [0],
            }
        ],
    }


# ---------------------------------------------------------------------------
# 契约校验器（纯函数）


def test_contract_happy_path() -> None:
    draft = validate_extraction_output(_valid_ai_payload())
    assert len(draft["facts"]) == 2 and draft["facts"][0]["confidence"] == 0.9
    assert draft["requirements"][0]["source_fact_indexes"] == [0]


def test_contract_rejects_bad_shapes() -> None:
    # 键集不完整
    with _raises("invalid_extraction"):
        validate_extraction_output({"facts": []})
    # fact_type 域外
    bad = _valid_ai_payload()
    bad["facts"][0]["fact_type"] = "gossip"
    with _raises("invalid_fact_type"):
        validate_extraction_output(bad)
    # 未知键拒绝
    bad = _valid_ai_payload()
    bad["facts"][0]["surprise"] = 1
    with _raises("invalid_fact"):
        validate_extraction_output(bad)
    # 批内重复事实
    bad = _valid_ai_payload()
    bad["facts"].append(dict(bad["facts"][0]))
    with _raises("duplicate_fact"):
        validate_extraction_output(bad)


def test_contract_locator_closure() -> None:
    for locator, ok in [
        ({"type": "line", "line": 1}, True),
        ({"type": "line", "line": 0}, False),
        ({"type": "transcript_segment", "start_ms": 0, "end_ms": 1500}, True),
        ({"type": "transcript_segment", "start_ms": 2000, "end_ms": 1500}, False),
        ({"type": "char_span", "start": 3, "end": 9}, True),
        ({"type": "char_span", "start": 9, "end": 9}, False),
        ({"type": "paragraph", "index": 1}, False),
    ]:
        payload = _valid_ai_payload()
        payload["facts"][0]["source_locator"] = locator
        if ok:
            validate_extraction_output(payload)
        else:
            with _raises("invalid_locator"):
                validate_extraction_output(payload)


def test_contract_confidence_and_requirement_rules() -> None:
    bad = _valid_ai_payload()
    bad["facts"][0]["confidence"] = 1.5
    with _raises("invalid_confidence"):
        validate_extraction_output(bad)
    bad = _valid_ai_payload()
    bad["requirements"][0]["requirement_type"] = "magical"
    with _raises("invalid_requirement_type"):
        validate_extraction_output(bad)
    bad = _valid_ai_payload()
    bad["requirements"][0]["acceptance_criteria"] = []
    with _raises("invalid_acceptance"):
        validate_extraction_output(bad)
    bad = _valid_ai_payload()
    bad["requirements"][0]["source_fact_indexes"] = [7]
    with _raises("unknown_source_fact"):
        validate_extraction_output(bad)
    bad = _valid_ai_payload()
    bad["requirements"][0]["source_fact_indexes"] = [0, 0]
    with _raises("duplicate_source_fact"):
        validate_extraction_output(bad)


class _raises:
    def __init__(self, code: str):
        self.code = code

    def __enter__(self):
        import pytest

        return pytest.raises(DiscoveryContractError)

    def __exit__(self, exc_type, exc, tb):
        assert exc is not None and exc.code == self.code, f"期望 {self.code}，实际 {exc}"
        return True


# ---------------------------------------------------------------------------
# HTTP 面：创建/幂等/越权/重跑


def test_create_extraction_and_idempotency(db_session, d4_client, d4_settings) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户A")
    minutes = _minutes(db_session, project, leader.user)

    response = leader.post(
        "/api/v1/projects/{}/discovery/extractions".format(project.id),
        json={"source_type": "interview_minutes", "source_id": minutes.id},
    )
    assert response.status_code == 201, response.get_json()
    data = response.get_json()["data"]
    assert data["status"] == "queued" and data["created"] is True
    assert len(data["source_sha256"]) == 64

    # 幂等：同源同版本重复创建返回既有行
    again = leader.post(
        "/api/v1/projects/{}/discovery/extractions".format(project.id),
        json={"source_type": "interview_minutes", "source_id": minutes.id},
    )
    assert again.status_code == 200
    assert again.get_json()["data"]["id"] == data["id"] and again.get_json()["data"]["created"] is False

    # outbox 事件恰好一条（第二次幂等创建不再入队）
    outbox = db_session.query(OutboxEvent).filter_by(topic="project.discovery.extract", aggregate_id=data["id"]).count()
    assert outbox == 1
    events = db_session.query(OperationEvent).filter_by(
        target_type="discovery_extraction", target_id=data["id"], event_type="discovery_extraction_created"
    ).count()
    assert events == 1


def test_create_extraction_access_and_source_gates(db_session, d4_client, d4_settings) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户B")
    minutes = _minutes(db_session, project, leader.user)
    viewer, _ = _viewer_client(db_session, d4_client, d4_settings, project)

    # viewer 无管理权 → 403
    denied = viewer.post(
        "/api/v1/projects/{}/discovery/extractions".format(project.id),
        json={"source_type": "interview_minutes", "source_id": minutes.id},
    )
    assert denied.status_code == 403

    # 跨项目源 → 404（伪造 source_ref 防线：源必须属本项目）
    other_leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    other_project = _new_project(db_session, other_leader.user, "客户C")
    forged = other_leader.post(
        "/api/v1/projects/{}/discovery/extractions".format(other_project.id),
        json={"source_type": "interview_minutes", "source_id": minutes.id},
    )
    assert forged.status_code == 404

    # 不存在的源 → 404；非法 source_type → 400
    assert leader.post(
        "/api/v1/projects/{}/discovery/extractions".format(project.id),
        json={"source_type": "interview_minutes", "source_id": str(uuid4())},
    ).status_code == 404
    assert leader.post(
        "/api/v1/projects/{}/discovery/extractions".format(project.id),
        json={"source_type": "memo", "source_id": minutes.id},
    ).status_code == 400


def test_rerun_only_failed(db_session, d4_client, d4_settings) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户D")
    minutes = _minutes(db_session, project, leader.user)
    extraction = DiscoveryExtraction(
        project_id=project.id,
        created_by_user_id=leader.user.id,
        source_type="interview_minutes",
        source_id=minutes.id,
        source_sha256=minutes.content_sha256,
        status="review_required",
    )
    db_session.add(extraction)
    db_session.commit()

    response = leader.post(f"/api/v1/discovery/extractions/{extraction.id}/run")
    assert response.status_code == 409 and response.get_json()["error"]["code"] == "extraction_not_failed"

    extraction.status = "failed"
    extraction.failure_code = "ai_output_invalid"
    extraction.failure_message = "格式错误"
    db_session.commit()
    response = leader.post(f"/api/v1/discovery/extractions/{extraction.id}/run")
    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "queued"


def test_create_extraction_version_bump_creates_new_row(db_session, d4_client, d4_settings) -> None:
    """幂等键含版本（V31-P1b 实弹抓到的缺陷：查找漏版本过滤 → rerun 永远
    拿回旧代际的行）：旧版本失败行保留为历史，同源再抽生成当前版本**新行**。"""
    from fde_api.discovery.models import EXTRACTOR_VERSION, PROMPT_VERSION

    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户L")
    minutes = _minutes(db_session, project, leader.user)
    legacy = DiscoveryExtraction(
        project_id=project.id,
        created_by_user_id=leader.user.id,
        source_type="interview_minutes",
        source_id=minutes.id,
        source_sha256=minutes.content_sha256,
        status="failed",
        failure_code="ai_output_invalid",
        failure_message="v1 整篇成抽必截断",
        extractor_version="discovery-extractor-v1",
        prompt_version="discovery-prompt-v1",
    )
    db_session.add(legacy)
    db_session.commit()

    response = leader.post(
        "/api/v1/projects/{}/discovery/extractions".format(project.id),
        json={"source_type": "interview_minutes", "source_id": minutes.id},
    )
    assert response.status_code == 201, response.get_json()
    data = response.get_json()["data"]
    assert data["created"] is True
    assert data["id"] != legacy.id
    assert data["extractor_version"] == EXTRACTOR_VERSION == "discovery-extractor-v2"
    assert data["prompt_version"] == PROMPT_VERSION == "discovery-prompt-v2"

    # 同版本再 POST → 幂等返回当前版本行；旧 v1 行原样保留
    again = leader.post(
        "/api/v1/projects/{}/discovery/extractions".format(project.id),
        json={"source_type": "interview_minutes", "source_id": minutes.id},
    )
    assert again.status_code == 200
    assert again.get_json()["data"]["id"] == data["id"] and again.get_json()["data"]["created"] is False
    db_session.expire_all()
    assert db_session.get(DiscoveryExtraction, legacy.id).extractor_version == "discovery-extractor-v1"


def test_rerun_failed_extraction_bumps_versions_with_conflict_guard(db_session, d4_client, d4_settings) -> None:
    """重跑由当前代代码执行 → 行版本标签如实换代；同源已有当前版本行时 409
    指路新行（唯一约束会撞），旧失败行保留为历史。"""
    from fde_api.discovery.models import EXTRACTOR_VERSION, PROMPT_VERSION

    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户M")
    minutes = _minutes(db_session, project, leader.user)
    legacy = DiscoveryExtraction(
        project_id=project.id,
        created_by_user_id=leader.user.id,
        source_type="interview_minutes",
        source_id=minutes.id,
        source_sha256=minutes.content_sha256,
        status="failed",
        failure_code="ai_output_truncated",
        failure_message="截断",
        extractor_version="discovery-extractor-v1",
        prompt_version="discovery-prompt-v1",
    )
    db_session.add(legacy)
    db_session.commit()

    response = leader.post(f"/api/v1/discovery/extractions/{legacy.id}/run")
    assert response.status_code == 200, response.get_json()
    db_session.expire_all()
    row = db_session.get(DiscoveryExtraction, legacy.id)
    assert row.status == "queued"
    assert row.extractor_version == EXTRACTOR_VERSION and row.prompt_version == PROMPT_VERSION

    # 同源已存在另一条当前版本行（如已完成的 v2）→ 重跑旧失败行 409 指路
    other = _minutes(db_session, project, leader.user, content="另一篇")
    stale = DiscoveryExtraction(
        project_id=project.id,
        created_by_user_id=leader.user.id,
        source_type="interview_minutes",
        source_id=other.id,
        source_sha256=other.content_sha256,
        status="failed",
        failure_code="ai_output_invalid",
        failure_message="旧失败",
        extractor_version="discovery-extractor-v1",
        prompt_version="discovery-prompt-v1",
    )
    current = DiscoveryExtraction(
        project_id=project.id,
        created_by_user_id=leader.user.id,
        source_type="interview_minutes",
        source_id=other.id,
        source_sha256=other.content_sha256,
        status="review_required",
    )
    db_session.add_all([stale, current])
    db_session.commit()
    response = leader.post(f"/api/v1/discovery/extractions/{stale.id}/run")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "extraction_version_conflict"


# ---------------------------------------------------------------------------
# 抽取管线（handler 直调）


def _run_handler(app, db_session, extraction, ai_outputs):
    """直调 handler；ai_outputs 逐次弹出（模拟重试序列）。"""

    def _fake_execute(**kwargs):
        item = ai_outputs.pop(0)
        if isinstance(item, Exception):
            raise item
        return {"text": item, "model": {"provider": "test", "name": "test-model"}, "provider_usage": {}}

    import fde_api.discovery.jobs as jobs_module

    original = jobs_module.execute_ai_prompt
    jobs_module.execute_ai_prompt = _fake_execute
    job = SimpleNamespace(target_id=extraction.id)
    try:
        with app.app_context():
            jobs_module.handle_discovery_extraction(job)
    finally:
        jobs_module.execute_ai_prompt = original
    db_session.expire_all()
    return db_session.get(DiscoveryExtraction, extraction.id)


def test_extraction_job_success_flow(app, db_session, d4_client, d4_settings) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户E")
    minutes = _minutes(db_session, project, leader.user)
    extraction = DiscoveryExtraction(
        project_id=project.id,
        created_by_user_id=leader.user.id,
        source_type="interview_minutes",
        source_id=minutes.id,
        source_sha256=minutes.content_sha256,
        status="queued",
    )
    db_session.add(extraction)
    db_session.commit()

    import json as _json

    row = _run_handler(app, db_session, extraction, [_json.dumps(_valid_ai_payload(), ensure_ascii=False)])
    assert row.status == "review_required"
    assert row.ai_model == "test-model" and row.failure_code is None

    facts = db_session.query(BusinessFact).filter_by(extraction_id=row.id).all()
    assert len(facts) == 2
    by_subject = {f.subject: f for f in facts}
    first = by_subject["询盘处理"]
    assert first.classification == "customer_stated" and first.review_status == "pending"
    assert first.source_ref == f"interview_minutes:{minutes.id}"
    assert first.source_locator == {"type": "line", "line": 1}

    requirement = db_session.query(Requirement).filter_by(extraction_id=row.id).one()
    assert requirement.status == "pending" and requirement.requirement_key.startswith("R-")
    sources = db_session.query(RequirementSource).filter_by(requirement_id=requirement.id).all()
    assert len(sources) == 1 and sources[0].fact_id in {f.id for f in facts}


def test_extraction_job_retry_and_failure_zero_write(app, db_session, d4_client, d4_settings) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户F")
    minutes = _minutes(db_session, project, leader.user)
    extraction = DiscoveryExtraction(
        project_id=project.id, created_by_user_id=leader.user.id,
        source_type="interview_minutes", source_id=minutes.id,
        source_sha256=minutes.content_sha256, status="queued",
    )
    db_session.add(extraction)
    db_session.commit()

    # 第一次畸形、第二次合法 → 自动重试成功
    row = _run_handler(app, db_session, extraction, ["{not json", _valid_ai_payload()])
    assert row.status == "review_required"
    assert db_session.query(BusinessFact).filter_by(extraction_id=row.id).count() == 2

    # 重置后两次全畸形 → failed 且零业务写入（子表先清：sources→requirements→facts）
    db_session.query(RequirementSource).filter(
        RequirementSource.requirement_id.in_(
            db_session.query(Requirement.id).filter_by(extraction_id=row.id)
        )
    ).delete(synchronize_session=False)
    db_session.query(Requirement).filter_by(extraction_id=row.id).delete(synchronize_session=False)
    db_session.query(BusinessFact).filter_by(extraction_id=row.id).delete(synchronize_session=False)
    row.status = "failed"
    row.failure_code = "ai_output_invalid"
    row.failure_message = "x"
    db_session.commit()
    row = _run_handler(app, db_session, extraction, ["{bad", "{also-bad"])
    assert row.status == "failed" and row.failure_code == "ai_output_invalid"
    assert db_session.query(BusinessFact).filter_by(extraction_id=row.id).count() == 0
    assert db_session.query(Requirement).filter_by(extraction_id=row.id).count() == 0


def test_extraction_output_redaction_and_review_event(app, db_session, d4_client, d4_settings) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户G")
    minutes = _minutes(db_session, project, leader.user, content=f"与{_DICT_NAME}聊排程。")
    extraction = DiscoveryExtraction(
        project_id=project.id, created_by_user_id=leader.user.id,
        source_type="interview_minutes", source_id=minutes.id,
        source_sha256=minutes.content_sha256, status="queued",
    )
    db_session.add(extraction)
    db_session.commit()

    payload = _valid_ai_payload()
    payload["facts"][0]["subject"] = f"{_DICT_NAME}的询盘流"
    row = _run_handler(app, db_session, extraction, [payload])
    assert row.status == "review_required"
    fact = db_session.query(BusinessFact).filter_by(extraction_id=row.id).first()
    assert _DICT_NAME not in fact.subject, "输出端兜底脱敏必须替换词典命中名"
    assert row.redaction_entries and any(e["name"] == _DICT_NAME for e in row.redaction_entries)
    events = db_session.query(OperationEvent).filter_by(
        target_type="discovery_extraction", target_id=row.id, event_type="discovery.redaction_review"
    ).count()
    assert events == 1


def test_inference_and_open_question_forced_clarification(app, db_session, d4_client, d4_settings) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户H")
    minutes = _minutes(db_session, project, leader.user)
    extraction = DiscoveryExtraction(
        project_id=project.id, created_by_user_id=leader.user.id,
        source_type="interview_minutes", source_id=minutes.id,
        source_sha256=minutes.content_sha256, status="queued",
    )
    db_session.add(extraction)
    db_session.commit()

    payload = _valid_ai_payload()
    payload["facts"][0]["inference"] = True
    payload["facts"][1]["needs_clarification"] = True
    payload["requirements"][0]["source_fact_indexes"] = []
    row = _run_handler(app, db_session, extraction, [payload])
    facts = db_session.query(BusinessFact).filter_by(extraction_id=row.id).all()
    by_subject = {f.subject: f for f in facts}
    assert by_subject["询盘处理"].classification == "ai_inferred"
    assert by_subject["询盘处理"].review_status == "needs_clarification"
    assert by_subject["生产排程"].classification == "open_question"
    # 无来源事实的需求 → needs_clarification（无来源不得自动接受）
    requirement = db_session.query(Requirement).filter_by(extraction_id=row.id).one()
    assert requirement.status == "needs_clarification"
    assert db_session.query(RequirementSource).filter_by(requirement_id=requirement.id).count() == 0


def test_worker_loss_failure_handler(db_session, d4_client, d4_settings) -> None:
    from fde_api.discovery.jobs import fail_extraction_on_worker_loss

    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户K")
    extraction = DiscoveryExtraction(
        project_id=project.id, created_by_user_id=leader.user.id,
        source_type="interview_minutes", source_id=str(uuid4()),
        source_sha256="a" * 64, status="running",
    )
    db_session.add(extraction)
    db_session.commit()
    job = SimpleNamespace(target_id=extraction.id)
    fail_extraction_on_worker_loss(db_session, job)
    db_session.flush()  # 失败钩子由 reconcile 调用方提交（guidance 同约）；测试内显式落
    db_session.expire_all()
    row = db_session.get(DiscoveryExtraction, extraction.id)
    assert row.status == "failed" and row.failure_code == "discovery_worker_lost"
    # 终态行再触发零动作
    fail_extraction_on_worker_loss(db_session, job)
    db_session.expire_all()
    assert db_session.get(DiscoveryExtraction, extraction.id).failure_code == "discovery_worker_lost"


# ---------------------------------------------------------------------------
# 审阅面


def test_review_fact_and_requirement_flow(db_session, d4_client, d4_settings) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户I")
    minutes = _minutes(db_session, project, leader.user)
    extraction = DiscoveryExtraction(
        project_id=project.id, created_by_user_id=leader.user.id,
        source_type="interview_minutes", source_id=minutes.id,
        source_sha256=minutes.content_sha256, status="review_required",
    )
    db_session.add(extraction)
    db_session.flush()
    fact = BusinessFact(
        project_id=project.id, extraction_id=extraction.id,
        fact_type="process", classification="customer_stated",
        subject="询盘处理", predicate="当前步骤", object_value={"step": "人工"},
        source_ref=f"interview_minutes:{minutes.id}",
        source_locator={"type": "line", "line": 1}, review_status="pending",
    )
    requirement = Requirement(
        project_id=project.id, extraction_id=extraction.id, created_by_user_id=leader.user.id,
        requirement_key="R-abc12345", title="自动分配", requirement_type="functional",
        priority="high", acceptance_criteria=["5 分钟内分配"], status="pending",
    )
    db_session.add_all([fact, requirement])
    db_session.commit()

    # viewer 审阅 → 403
    viewer, _ = _viewer_client(db_session, d4_client, d4_settings, project)
    assert viewer.patch(f"/api/v1/business-facts/{fact.id}/review", json={"review_status": "accepted"}).status_code == 403

    # leader 审阅事实 → accepted + 留痕
    response = leader.patch(
        f"/api/v1/business-facts/{fact.id}/review",
        json={"review_status": "accepted", "comment": "已与纪要对齐"},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["review_status"] == "accepted" and data["reviewed_by_user_id"] == leader.user.id

    # 终态再流转 → 409
    assert leader.patch(
        f"/api/v1/business-facts/{fact.id}/review", json={"review_status": "rejected"}
    ).status_code == 409

    # needs_clarification → accepted 可流转（非终态）
    fact2 = BusinessFact(
        project_id=project.id, extraction_id=extraction.id,
        fact_type="open_question", classification="open_question",
        subject="预算", predicate="待确认", object_value="?",
        source_ref=f"interview_minutes:{minutes.id}",
        source_locator={"type": "line", "line": 2}, review_status="needs_clarification",
    )
    db_session.add(fact2)
    db_session.commit()
    assert leader.patch(
        f"/api/v1/business-facts/{fact2.id}/review", json={"review_status": "accepted"}
    ).status_code == 200

    # 需求审阅 → rejected + 事件
    response = leader.patch(
        f"/api/v1/requirements/{requirement.id}/review",
        json={"status": "rejected", "comment": "客户暂不做"},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "rejected"
    assert db_session.query(OperationEvent).filter_by(
        target_type="requirement", target_id=requirement.id, event_type="requirement_reviewed"
    ).count() == 1


def test_list_endpoints_filters_and_cross_project(db_session, d4_client, d4_settings) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户J")
    minutes = _minutes(db_session, project, leader.user)
    extraction = DiscoveryExtraction(
        project_id=project.id, created_by_user_id=leader.user.id,
        source_type="interview_minutes", source_id=minutes.id,
        source_sha256=minutes.content_sha256, status="review_required",
    )
    db_session.add(extraction)
    db_session.flush()
    db_session.add(BusinessFact(
        project_id=project.id, extraction_id=extraction.id,
        fact_type="role", classification="customer_stated",
        subject="车间主任", predicate="职责", object_value="排产",
        source_ref=f"interview_minutes:{minutes.id}",
        source_locator={"type": "line", "line": 1}, review_status="accepted",
        reviewed_by_user_id=leader.user.id, reviewed_at=datetime.now(UTC),
    ))
    db_session.commit()

    listing = leader.get(f"/api/v1/projects/{project.id}/business-facts?review_status=accepted")
    assert listing.status_code == 200
    items = listing.get_json()["data"]["items"]
    assert len(items) == 1 and items[0]["fact_type"] == "role"

    assert leader.get(f"/api/v1/projects/{project.id}/business-facts?fact_type=process").get_json()["data"]["items"] == []
    assert leader.get(f"/api/v1/projects/{project.id}/business-facts?limit=0").status_code == 400

    # 跨项目：另一 lead（非成员）→ 403
    stranger = api_client(d4_client, db_session, d4_settings, "project_lead")
    assert stranger.get(f"/api/v1/projects/{project.id}/business-facts").status_code == 403
    assert stranger.get(f"/api/v1/discovery/extractions/{extraction.id}").status_code == 403


def test_extraction_output_truncated_fail_fast_no_retry(app, db_session, d4_client, d4_settings) -> None:
    """V31-P1→P1b：截断检测第二腿（``finish_reason=length``）→
    可分的片自适应降片长再抽（**不同输**，非同输必败重放）；
    两行片二分后首个单行半片不可再分 → 整批诚实失败零写入。"""
    import fde_api.discovery.jobs as jobs_module

    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户H")
    minutes = _minutes(db_session, project, leader.user)
    extraction = DiscoveryExtraction(
        project_id=project.id, created_by_user_id=leader.user.id,
        source_type="interview_minutes", source_id=minutes.id,
        source_sha256=minutes.content_sha256, status="queued",
    )
    db_session.add(extraction)
    db_session.commit()

    calls: list[str] = []
    truncated_usage = {
        "complete": True,
        "calls": [{"finish_reason": "length", "reasoning_tokens": 16383, "truncated": True}],
    }

    def _fake_execute(**kwargs):
        calls.append(str(kwargs.get("execution_id")))
        return {
            "text": '{"facts": [{"sub',
            "model": {"provider": "test", "name": "MiniMax-M3.1-Flash"},
            "provider_usage": truncated_usage,
        }

    original = jobs_module.execute_ai_prompt
    jobs_module.execute_ai_prompt = _fake_execute
    job = SimpleNamespace(target_id=extraction.id)
    try:
        with app.app_context():
            jobs_module.handle_discovery_extraction(job)
    finally:
        jobs_module.execute_ai_prompt = original
    db_session.expire_all()

    row = db_session.get(DiscoveryExtraction, extraction.id)
    assert row.status == "failed" and row.failure_code == "ai_output_truncated"
    assert "截断" in (row.failure_message or "")
    # 2 次调用：原片（2 行）+ 二分后的半片（1 行，execution_id 不同=不同输重抽）；
    # 半片不可再分 → 诚实失败。绝不第二次重放同一输入。
    assert len(calls) == 2
    assert calls[0] != calls[1]
    assert db_session.query(BusinessFact).filter_by(extraction_id=row.id).count() == 0
    assert db_session.query(Requirement).filter_by(extraction_id=row.id).count() == 0


# ---------------------------------------------------------------------------
# V31-P1b：分段抽取（长纪要按行切片 → 分批抽取 → 行号回基合并）


def test_extraction_chunked_flow_rebases_and_merges(app, db_session, d4_client, d4_settings) -> None:
    """长纪要切成多片分批抽取：片内行号回基成全文绝对行号，跨片事实去重。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户I")
    content = "\n".join(f"第{i}行内容" for i in range(1, 61))
    minutes = _minutes(db_session, project, leader.user, content=content)
    extraction = DiscoveryExtraction(
        project_id=project.id, created_by_user_id=leader.user.id,
        source_type="interview_minutes", source_id=minutes.id,
        source_sha256=minutes.content_sha256, status="queued",
    )
    db_session.add(extraction)
    db_session.commit()

    import json as _json

    def _payload(subject: str, line: int) -> dict:
        return {
            "facts": [{
                "fact_type": "process",
                "subject": subject,
                "predicate": "当前步骤",
                "object_value": {"步骤": subject},
                "source_locator": {"type": "line", "line": line},
                "confidence": 0.9,
            }],
            "requirements": [{
                "title": "统一入口",
                "requirement_type": "functional",
                "priority": "high",
                "acceptance_criteria": ["单一入口可查"],
                "source_fact_indexes": [0],
            }],
        }

    # 三片（60 行 → 25/25/10）：片 2、片 3 重复片 1 的事实身份 → 应被去重
    outputs = [
        _json.dumps(_payload("片一事实", 1), ensure_ascii=False),
        _json.dumps(_payload("片一事实", 2), ensure_ascii=False),
        _json.dumps(_payload("片一事实", 3), ensure_ascii=False),
    ]
    prompts: list[str] = []

    def _fake_execute(**kwargs):
        prompts.append(str(kwargs.get("prompt") or ""))
        item = outputs.pop(0)
        return {"text": item, "model": {"provider": "test", "name": "test-model"}, "provider_usage": {}}

    import fde_api.discovery.jobs as jobs_module

    original = jobs_module.execute_ai_prompt
    jobs_module.execute_ai_prompt = _fake_execute
    job = SimpleNamespace(target_id=extraction.id)
    try:
        with app.app_context():
            jobs_module.handle_discovery_extraction(job)
    finally:
        jobs_module.execute_ai_prompt = original
    db_session.expire_all()

    row = db_session.get(DiscoveryExtraction, extraction.id)
    assert row.status == "review_required", row.failure_message
    assert len(prompts) == 3  # 60 行 → 25 行/片 → 3 片
    # 每片拿到的是本片正文（不是全文）
    assert all("第61行内容" not in p for p in prompts)

    facts = db_session.query(BusinessFact).filter_by(extraction_id=row.id).all()
    assert len(facts) == 1  # 跨片重复身份被去重
    locators = {f.subject: f.source_locator["line"] for f in facts}
    assert locators["片一事实"] == 1          # 首次出现（片 1 第 1 行）
    # 需求：两片标题重复 → 只留一条，引用指向合并后的事实表
    requirements = db_session.query(Requirement).filter_by(extraction_id=row.id).all()
    assert len(requirements) == 1
    sources = db_session.query(RequirementSource).filter_by(
        requirement_id=requirements[0].id).all()
    assert len(sources) == 1


def test_extraction_chunk_truncation_splits_and_retries(app, db_session, d4_client, d4_settings) -> None:
    """V31-P1b：被截断的片**自适应一分为二再抽**（模型思考长度有方差，
    固定片长无法保证不触顶）；单行片仍截断 → 整批诚实失败（不部分写入）。"""
    import json as _json

    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户J")
    content = "\n".join(f"第{i}行内容" for i in range(1, 4))
    minutes = _minutes(db_session, project, leader.user, content=content)
    extraction = DiscoveryExtraction(
        project_id=project.id, created_by_user_id=leader.user.id,
        source_type="interview_minutes", source_id=minutes.id,
        source_sha256=minutes.content_sha256, status="queued",
    )
    db_session.add(extraction)
    db_session.commit()

    prompts: list[str] = []
    truncated = {"count": 0}

    def _fake_execute(**kwargs):
        prompts.append(str(kwargs.get("prompt") or ""))
        # 前 3 次（3 行的片 + 二分后的两片）都截断，验证会继续往下分
        truncated["count"] += 1
        return {
            "text": '{"facts": [{"sub',
            "model": {"provider": "test", "name": "MiniMax-M3.1-Flash"},
            "provider_usage": {"complete": True, "calls": [{"truncated": True}]},
        }

    import fde_api.discovery.jobs as jobs_module

    original = jobs_module.execute_ai_prompt
    jobs_module.execute_ai_prompt = _fake_execute
    job = SimpleNamespace(target_id=extraction.id)
    try:
        with app.app_context():
            jobs_module.handle_discovery_extraction(job)
    finally:
        jobs_module.execute_ai_prompt = original
    db_session.expire_all()

    row = db_session.get(DiscoveryExtraction, extraction.id)
    assert row.status == "failed" and row.failure_code == "ai_output_truncated"
    # 3 行片 → 二分（2+1）→ 2 行片再二分（1+1）→ 单行片仍截断 → 诚实失败
    assert len(prompts) > 1, "被截断的片必须自适应降片长再抽"
    assert db_session.query(BusinessFact).filter_by(extraction_id=row.id).count() == 0
    assert db_session.query(Requirement).filter_by(extraction_id=row.id).count() == 0


def test_extraction_chunk_truncation_splits_then_succeeds(app, db_session, d4_client, d4_settings) -> None:
    """被截断的片二分后再抽成功 → 整批照常完成（行号按二分后的片回基）。"""
    import json as _json

    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户K")
    content = "\n".join(f"第{i}行内容" for i in range(1, 4))
    minutes = _minutes(db_session, project, leader.user, content=content)
    extraction = DiscoveryExtraction(
        project_id=project.id, created_by_user_id=leader.user.id,
        source_type="interview_minutes", source_id=minutes.id,
        source_sha256=minutes.content_sha256, status="queued",
    )
    db_session.add(extraction)
    db_session.commit()

    calls = {"n": 0}
    prompts: list[str] = []

    def _fake_execute(**kwargs):
        calls["n"] += 1
        prompts.append(str(kwargs.get("prompt") or ""))
        if calls["n"] == 1:
            # 首片（3 行）被截断
            return {
                "text": '{"facts": [{"sub',
                "model": {"provider": "test", "name": "MiniMax-M3.1-Flash"},
                "provider_usage": {"complete": True, "calls": [{"truncated": True}]},
            }
        payload = {
            "facts": [{
                "fact_type": "process",
                "subject": f"事实{calls['n']}",
                "predicate": "当前步骤",
                "object_value": {"步骤": "x"},
                "source_locator": {"type": "line", "line": 1},
                "confidence": 0.9,
            }],
            "requirements": [],
        }
        return {
            "text": _json.dumps(payload, ensure_ascii=False),
            "model": {"provider": "test", "name": "test-model"},
            "provider_usage": {},
        }

    import fde_api.discovery.jobs as jobs_module

    original = jobs_module.execute_ai_prompt
    jobs_module.execute_ai_prompt = _fake_execute
    job = SimpleNamespace(target_id=extraction.id)
    try:
        with app.app_context():
            jobs_module.handle_discovery_extraction(job)
    finally:
        jobs_module.execute_ai_prompt = original
    db_session.expire_all()

    row = db_session.get(DiscoveryExtraction, extraction.id)
    assert row.status == "review_required", row.failure_message
    facts = db_session.query(BusinessFact).filter_by(extraction_id=row.id).all()
    assert len(facts) == 2  # 二分后的两片各一条
    # 行号按二分后的片回基：左片首行=1，右片首行=2
    assert sorted(f.source_locator["line"] for f in facts) == [1, 2]
