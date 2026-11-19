"""AF2-WP4：执行产物呈现面（预览/差异/血缘/质量反馈四读面）。

四读面全部为 **run 落库件的只读派生视图**（零落库、零状态变更、零迁移），
项目域鉴权沿 WP3 惯例（非成员/跨项目 run＝404）。纪律锚（15 号 WP4 行 /
04 §3.2 原文）：

- **样本预览用于早期检查**；完整数据断言必须基于全量统计件（守恒/账本/
  质量报告）——预览面 note 显式声明样本性质（「不能只用样本预览代替」
  的呈现化落实）；
- **所有输入记录去向可解释**：diff 面按弱守恒口径呈现产出/拒绝（按
  reason 分组）/溢出三类去向，质量条目（quality_* ＝保留行违规记录，
  非拒绝）单列 ``quality_flags``，不与拒绝混淆；
- **反馈面零行值原文**：quality-feedback 只含断言统计与定位类别
  （04 §3.2「工程日志只存引用、统计和错误类别」；17 号 §3.3 账本纪律
  在呈现面的延续）；
- 两级血缘拼装（17 号 §3.5）：计划静态 DAG（validation_json）+ 执行级
  per-step 统计（lineage_json）对齐呈现，步序不一致＝如实标 false 不静默。
"""
from __future__ import annotations

import hashlib
import io
import uuid

import pytest
from conftest import INITIAL_PASSWORD as PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.data_engineering.models import DataProfile, TransformPlan, TransformRun
from fde_api.data_engineering.transform_plan import PLAN_VERSION, validate_plan
from fde_api.files.models import ProjectFile, ProjectFileVersion
from fde_api.workbench.models import Project

# ---- 工厂（与 WP3 测试同构） -------------------------------------------------

OUTPUT_COLUMNS = [
    {"name": "eq_id", "type": "string"},
    {"name": "defect_pct", "type": "number"},
]


def _plan(profile_id: str | None = None) -> dict:
    body = {
        "plan_version": PLAN_VERSION,
        "source": {"profile_id": profile_id or str(uuid.uuid4()), "table": "equipment"},
        "input": {
            "columns": [
                {"name": "eq_id", "type": "string"},
                {"name": "defect_pct", "type": "number"},
            ]
        },
        "policies": {
            "null_handling": "reject",
            "reject_record": "collect",
            "duplicate_key": "keep_first",
        },
        "relations": [],
        "steps": [
            {"id": "s1", "op": "select", "params": {"columns": ["eq_id", "defect_pct"]}},
        ],
        "output": {"columns": [dict(c) for c in OUTPUT_COLUMNS]},
    }
    return body


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
    from datetime import date

    project = Project(
        project_code=f"TE-{uuid.uuid4().hex[:8]}",
        name="Run views project",
        enterprise_code="Example·行业·城市",
        planned_start_date=date(2026, 9, 1),
        leader_user_id=leader.id,
        status="active",
        template_snapshot={},
    )
    db_session.add(project)
    db_session.commit()
    return project


def _persist_plan(db_session, actor: User, project: Project, plan: dict | None = None) -> TransformPlan:
    body = plan or _plan()
    row = TransformPlan(
        project_id=project.id,
        plan_version=PLAN_VERSION,
        status="validated",
        source_profile_id=str(body["source"]["profile_id"]),
        source_table=str(body["source"]["table"]),
        plan_json=body,
        validation_json=validate_plan(body),
        created_by_user_id=actor.id,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _insert_run(
    db_session,
    project: Project,
    actor: User,
    plan_row: TransformPlan,
    *,
    status: str = "succeeded",
    failure_reason: str | None = None,
    output_rows: list[dict] | None = None,
    output_row_count: int | None = None,
    reject_ledger: list[dict] | None = None,
    rejected_row_count: int = 0,
    overflow_count: int = 0,
    quality_report: dict | None = None,
    lineage: list[dict] | None = None,
    conservation: dict | None = None,
    legacy: bool = False,
) -> TransformRun:
    """run 直插工厂（append-only 记录；呈现面只读，无需走执行链）。"""
    rows = output_rows or []
    ledger = reject_ledger or []
    row = TransformRun(
        project_id=project.id,
        plan_id=plan_row.id,
        plan_version=plan_row.plan_version,
        idempotency_key="view-" + uuid.uuid4().hex,
        status=status,
        failure_reason=failure_reason,
        input_anchor_json={"kind": "synthetic"},
        output_rows_json=rows,
        output_row_count=output_row_count if output_row_count is not None else len(rows),
        output_columns_json=[dict(c) for c in OUTPUT_COLUMNS],
        reject_ledger_json=ledger,
        rejected_row_count=rejected_row_count,
        overflow_count=overflow_count,
        quality_report_json=quality_report or {},
        lineage_json=lineage or [],
        conservation_json={
            **({} if legacy else {"input_integrity": {"parse_error_rows": 0, "truncated": False}}),
            **(conservation or {}),
        },
        created_by_user_id=actor.id,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _seed_csv_version(db_session, project: Project, actor: User, csv_text: str):
    return _seed_file_version(db_session, project, actor, "equipment.csv", csv_text.encode("utf-8"), "text/csv")


def _seed_file_version(db_session, project: Project, actor: User, filename: str, data: bytes, mime_type: str):
    from fde_api.files.names import attachment_key, extension_of, safe_filename
    from fde_api.extensions import object_storage

    file_id, version_id = uuid.uuid4().hex, uuid.uuid4().hex
    project_file = ProjectFile(
        id=file_id,
        project=project,
        category="attachment",
        display_name=filename,
        description="",
        created_by_user_id=actor.id,
    )
    db_session.add(project_file)
    db_session.flush()
    safe = safe_filename(filename)
    storage_key = attachment_key(project.id, file_id, "v1", safe)
    version = ProjectFileVersion(
        id=version_id,
        project_file=project_file,
        version_number=1,
        source="upload",
        original_filename=filename,
        safe_filename=safe,
        extension=extension_of(filename),
        mime_type=mime_type,
        bucket="local",
        storage_key=storage_key,
        size_bytes=len(data),
        etag="",
        sha256=hashlib.sha256(data).hexdigest(),
        uploaded_by_user_id=actor.id,
        status="available",
        scan_status="clean",
        preview_status="none",
    )
    db_session.add(version)
    db_session.flush()
    project_file.current_version_id = version.id
    db_session.commit()
    object_storage.current.put_stream(storage_key, io.BytesIO(data), mime_type, {})
    return version


def _seed_profile(db_session, project: Project, actor: User, sha: str) -> DataProfile:
    row = DataProfile(
        project_id=project.id,
        source_name="equipment.csv",
        input_sha256=sha,
        source_kind="file",
        tables_json=[],
        relation_candidates_json=[],
        samples_json={},
        created_by_user_id=actor.id,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _headers(user: User, settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


def _submit_run(client, project: Project, leader: User, plan_row: TransformPlan, version, settings) -> dict:
    response = client.post(
        f"/api/v1/projects/{project.id}/transform-plans/{plan_row.id}/runs",
        json={"input": {"kind": "file_version", "file_version_id": version.id}},
        headers={**_headers(leader, settings), "Idempotency-Key": "run-" + uuid.uuid4().hex},
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["data"]


# ---- preview ----------------------------------------------------------------


def test_preview_masks_sensitive_input_after_rename_and_keeps_full_counts(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    csv_text = (
        "eq_id,contact_name,reference,unprojected\n"
        "EQ-1,PRIVATE-ALPHA,ordinary,omit-this\n"
        "EQ-2,PRIVATE-BETA,13800138000,omit-that\n"
    )
    version = _seed_csv_version(db_session, project, leader, csv_text)
    profile = _seed_profile(db_session, project, leader, version.sha256 or "")
    plan = _plan(profile.id)
    plan["input"]["columns"] = [
        dict(name=name, type="string") for name in ("eq_id", "contact_name", "reference", "unprojected")
    ]
    plan["steps"] = [{"id": "rename", "op": "rename", "params": {"mapping": {"contact_name": "operator"}}}]
    plan["output"]["columns"] = [dict(name=name, type="string") for name in ("eq_id", "operator", "reference")]
    plan_row = _persist_plan(db_session, leader, project, plan)
    run = _submit_run(client, project, leader, plan_row, version, settings)

    base = f"/api/v1/projects/{project.id}/transform-runs"
    headers = _headers(leader, settings)
    response = client.get(f"{base}/{run['id']}/preview?limit=1", headers=headers)
    assert response.status_code == 200
    preview = response.get_json()["data"]
    assert preview["rows"] == [{"eq_id": "EQ-1", "operator": "***", "reference": "***"}]
    assert preview["output_columns"] == plan["output"]["columns"]
    assert preview["total_row_count"] == 2
    assert run["output_rows"] == []
    assert client.get(f"{base}/{run['id']}", headers=headers).get_json()["data"]["output_rows"] == []
    assert client.get(base, headers=headers).get_json()["data"][0]["output_rows"] == []
    persisted = db_session.get(TransformRun, run["id"])
    assert persisted is not None
    assert persisted.output_rows_json == [
        {"eq_id": "EQ-1", "operator": "***", "reference": "***"},
        {"eq_id": "EQ-2", "operator": "***", "reference": "***"},
    ]


def test_preview_withholds_historical_unverified_rows(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    plan_row = _persist_plan(db_session, leader, project)
    run = _insert_run(db_session, project, leader, plan_row, output_rows=[{"eq_id": "HISTORICAL-PRIVATE"}])
    headers = _headers(leader, settings)
    base = f"/api/v1/projects/{project.id}/transform-runs/{run.id}"
    response = client.get(f"{base}/preview", headers=headers)
    assert response.status_code == 200
    preview = response.get_json()["data"]
    assert preview["rows"] == []
    assert preview["total_row_count"] == 1
    assert preview["sample_available"] is False
    assert client.get(base, headers=headers).get_json()["data"]["output_rows"] == []
    replay = client.post(
        f"/api/v1/projects/{project.id}/transform-plans/{plan_row.id}/runs",
        json={"input": {"kind": "file_version", "file_version_id": "historical-version"}},
        headers={**headers, "Idempotency-Key": run.idempotency_key},
    )
    assert replay.status_code == 201
    assert replay.get_json()["data"]["id"] == run.id
    assert replay.get_json()["data"]["output_rows"] == []
    listed = client.get(f"/api/v1/projects/{project.id}/transform-runs", headers=headers).get_json()["data"]
    assert [(item["id"], item["output_rows"]) for item in listed] == [(run.id, [])]

def test_preview_sample_window_with_cap_and_note(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    version = _seed_csv_version(db_session, project, leader, "eq_id,defect_pct\nEQ-1,0.5\nEQ-2,1.5\n")
    profile = _seed_profile(db_session, project, leader, version.sha256 or "")
    plan_row = _persist_plan(db_session, leader, project, _plan(profile.id))
    run = _submit_run(client, project, leader, plan_row, version, settings)

    response = client.get(
        f"/api/v1/projects/{project.id}/transform-runs/{run['id']}/preview?limit=1",
        headers=_headers(leader, settings),
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()["data"]
    assert payload["run_id"] == run["id"]
    assert payload["status"] == "succeeded"
    assert payload["total_row_count"] == 2
    assert payload["sample_row_count"] == 1
    assert payload["truncated"] is True
    assert payload["rows"][0]["eq_id"] == "EQ-1"
    assert payload["output_columns"] == OUTPUT_COLUMNS
    # 样本性质显式声明：预览≠完整断言（15 号纪律锚呈现化）
    assert "样本预览" in payload["note"]
    assert "断言" in payload["note"]


def test_preview_limit_validation_and_cap(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    csv_text = "eq_id,defect_pct\n" + "".join(f"EQ-{i},0.5\n" for i in range(101))
    version = _seed_csv_version(db_session, project, leader, csv_text)
    profile = _seed_profile(db_session, project, leader, version.sha256 or "")
    plan_row = _persist_plan(db_session, leader, project, _plan(profile.id))
    run = _submit_run(client, project, leader, plan_row, version, settings)

    base = f"/api/v1/projects/{project.id}/transform-runs/{run['id']}/preview"
    for bad in ("abc", "0", "-1"):
        assert client.get(f"{base}?limit={bad}", headers=_headers(leader, settings)).status_code == 400
    capped = client.get(f"{base}?limit=500", headers=_headers(leader, settings))
    assert capped.status_code == 200
    payload = capped.get_json()["data"]
    assert payload["sample_row_count"] == 100
    assert payload["total_row_count"] == 101
    assert payload["truncated"] is True
    default = client.get(base, headers=_headers(leader, settings))
    assert default.status_code == 200
    assert default.get_json()["data"]["sample_row_count"] == 20


def test_preview_requires_membership(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    outsider = _make_user(db_session, "viewer")
    project = _make_project(db_session, leader)
    plan_row = _persist_plan(db_session, leader, project)
    run = _insert_run(db_session, project, leader, plan_row)
    response = client.get(
        f"/api/v1/projects/{project.id}/transform-runs/{run.id}/preview",
        headers=_headers(outsider, settings),
    )
    assert response.status_code == 404


def test_preview_cross_project_run_not_found(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project_a = _make_project(db_session, leader)
    project_b = _make_project(db_session, leader)
    plan_row = _persist_plan(db_session, leader, project_a)
    run = _insert_run(db_session, project_a, leader, plan_row)
    response = client.get(
        f"/api/v1/projects/{project_b.id}/transform-runs/{run.id}/preview",
        headers=_headers(leader, settings),
    )
    assert response.status_code == 404


def test_preview_failed_run_zero_sample(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    plan_row = _persist_plan(db_session, leader, project)
    run = _insert_run(
        db_session,
        project,
        leader,
        plan_row,
        status="failed",
        failure_reason="duplicate_key",
        output_rows=[],
        output_row_count=0,
    )
    response = client.get(
        f"/api/v1/projects/{project.id}/transform-runs/{run.id}/preview",
        headers=_headers(leader, settings),
    )
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["status"] == "failed"
    assert payload["total_row_count"] == 0
    assert payload["rows"] == []


# ---- diff -------------------------------------------------------------------


def test_full_snapshot_matches_numeric_time_join_and_row_accounting(client, db_session, settings) -> None:
    from openpyxl import Workbook

    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    workbook = Workbook()
    left = workbook.active
    assert left is not None
    left.title = "equipment"
    left.append(["eq_id", "defect_pct", "measured_at"])
    for record in (
        ["EQ-1", "3.145", "2026-01-02T08:00:00+00:00"],
        ["EQ-X", "0.5", "2026-01-03T08:00:00"],
        ["EQ-3", "bad-number", "2026-01-04T08:00:00"],
        ["EQ-4", "2.0", "bad-date"],
    ):
        left.append(record)
    right = workbook.create_sheet("lookup")
    right.append(["eq_id", "category", "contact_name"])
    right.append(["EQ-1", "A", "PRIVATE-ONE"])
    right.append(["EQ-1", "B", "PRIVATE-TWO"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    version = _seed_file_version(
        db_session, project, leader, "equipment.xlsx", buffer.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    profile = _seed_profile(db_session, project, leader, version.sha256 or "")
    plan = _plan(profile.id)
    plan["input"]["columns"].append({"name": "measured_at", "type": "datetime"})
    plan["policies"]["null_handling"] = "keep_null"
    plan["relations"] = [{
        "left_table": "equipment", "right_table": "lookup", "left_column": "eq_id", "right_column": "eq_id",
        "basis": "declared_by_plan",
    }]
    plan["steps"] = [
        {"id": "cast", "op": "cast", "params": {"column": "defect_pct", "to_type": "decimal", "scale": 2, "rounding": "half_up"}},
        {"id": "time", "op": "normalize_datetime", "depends_on": ["cast"], "params": {"column": "measured_at", "to_tz": "Asia/Shanghai"}},
        {"id": "join", "op": "join", "depends_on": ["time"], "params": {
            "left_key": "eq_id", "right_table": "lookup", "right_key": "eq_id", "cardinality": "many_to_one",
            "basis": "declared_by_plan", "right_columns": ["category", "contact_name"],
        }},
        {"id": "rename", "op": "rename", "depends_on": ["join"], "params": {"mapping": {"contact_name": "operator"}}},
        {"id": "quality", "op": "assert_quality", "depends_on": ["rename"], "params": {"kind": "unique", "column": "eq_id"}},
    ]
    plan["output"]["columns"] = [
        dict(name=name, type=kind) for name, kind in (
            ("eq_id", "string"), ("defect_pct", "decimal"), ("measured_at", "datetime"),
            ("category", "string"), ("operator", "string"),
        )
    ]
    plan_row = _persist_plan(db_session, leader, project, plan)
    run = _submit_run(client, project, leader, plan_row, version, settings)
    assert run["status"] == "succeeded"
    assert run["conservation"] == {
        "input_rows": 4, "output_rows": 3, "rejected_rows": 2, "overflow_count": 0, "ok": True,
        "input_integrity": {"parse_error_rows": 0, "truncated": False},
    }
    persisted = db_session.get(TransformRun, run["id"])
    assert persisted is not None
    assert persisted.output_rows_json == [
        {"eq_id": "EQ-1", "defect_pct": "3.15", "measured_at": "2026-01-02T16:00:00+08:00", "category": "A", "operator": "***"},
        {"eq_id": "EQ-1", "defect_pct": "3.15", "measured_at": "2026-01-02T16:00:00+08:00", "category": "B", "operator": "***"},
        {"eq_id": "EQ-X", "defect_pct": "0.50", "measured_at": "2026-01-03T08:00:00+08:00", "category": None, "operator": None},
    ]
    base = f"/api/v1/projects/{project.id}/transform-runs/{run['id']}"
    headers = _headers(leader, settings)
    diff = client.get(f"{base}/diff", headers=headers).get_json()["data"]
    assert diff["ledger_sample"] == [
        {"row_index": 2, "reason": "cast_failed", "column": "defect_pct"},
        {"row_index": 3, "reason": "datetime_failed", "column": "measured_at"},
        {"row_index": 0, "reason": "quality_unique", "column": "eq_id"},
    ]
    assert diff["destinations"] == {
        "output": 3, "rejected_by_reason": {"cast_failed": 1, "datetime_failed": 1},
        "quality_flags": {"quality_unique": 1}, "overflow": 0,
    }
    feedback = client.get(f"{base}/quality-feedback", headers=headers).get_json()["data"]
    assert feedback["assertions"] == [
        {"step_id": "quality", "kind": "unique", "column": "eq_id", "evaluated_rows": 3,
         "rejected_before": 2, "violations": 1, "verdict": "fail"},
    ]
    lineage = client.get(f"{base}/lineage", headers=headers).get_json()["data"]
    assert lineage["steps_alignment"] is True
    assert lineage["plan_dag"]["edges"] == [["cast", "time"], ["time", "join"], ["join", "rename"], ["rename", "quality"]]
    assert [(step["step_id"], step["input_rows"], step["output_rows"], step["rejected_rows"])
            for step in lineage["execution_steps"]] == [
        ("cast", 4, 3, 1), ("time", 3, 2, 1), ("join", 2, 3, 0), ("rename", 3, 3, 0), ("quality", 3, 3, 0),
    ]
    preview = client.get(f"{base}/preview?limit=1", headers=headers).get_json()["data"]
    assert preview["sample_row_count"] == 1 and preview["total_row_count"] == 3

    from fde_api.extensions import object_storage

    with object_storage.current.open_stream(version.storage_key) as source:
        assert source.read() == buffer.getvalue()


def test_malformed_snapshot_reports_parse_errors_without_asserting_partial_data(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    version = _seed_csv_version(db_session, project, leader, "eq_id,defect_pct\nEQ-1,0.50\nMALFORMED-ROW\n")
    profile = _seed_profile(db_session, project, leader, version.sha256 or "")
    plan = _plan(profile.id)
    plan["steps"].append({"id": "quality", "op": "assert_quality", "params": {"kind": "unique", "column": "eq_id"}})
    plan_row = _persist_plan(db_session, leader, project, plan)
    run = _submit_run(client, project, leader, plan_row, version, settings)

    assert run["status"] == "failed"
    assert run["failure_reason"] == "input_parse_errors"
    assert run["output_row_count"] == 0
    assert run["conservation"]["ok"] is None
    base = f"/api/v1/projects/{project.id}/transform-runs/{run['id']}"
    headers = _headers(leader, settings)
    diff = client.get(f"{base}/diff", headers=headers).get_json()["data"]
    assert diff["input_rows"] == 2
    assert diff["input_integrity"] == {"parse_error_rows": 1, "truncated": False}
    assert diff["conservation_ok"] is None
    feedback = client.get(f"{base}/quality-feedback", headers=headers)
    assert "MALFORMED-ROW" not in feedback.get_data(as_text=True)
    body = feedback.get_json()["data"]
    assert body["complete"] is False
    assert body["assertions"] == []


def test_invalid_csv_encoding_and_quoting_stop_execution(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    for data in (
        b"eq_id,defect_pct\n\xff,0.50\n",
        b'eq_id,defect_pct\n"EQ-1,0.50\n',
        b"eq_id,defect_pct,eq_id\nEQ-1,0.50,EQ-2\n",
    ):
        project = _make_project(db_session, leader)
        version = _seed_file_version(db_session, project, leader, "equipment.csv", data, "text/csv")
        profile = _seed_profile(db_session, project, leader, version.sha256 or "")
        plan_row = _persist_plan(db_session, leader, project, _plan(profile.id))
        run = _submit_run(client, project, leader, plan_row, version, settings)
        assert run["status"] == "failed"
        assert run["failure_reason"] == "input_parse_errors"
        assert run["conservation"]["input_rows"] is None
        assert run["conservation"]["ok"] is None


def test_truncated_snapshot_never_reports_quality_pass(client, db_session, settings, monkeypatch) -> None:
    from fde_api.data_engineering import profiling

    monkeypatch.setattr(profiling, "MAX_ROWS", 1)
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    version = _seed_csv_version(db_session, project, leader, "eq_id,defect_pct\nEQ-1,0.50\nEQ-1,1.50\n")
    profile = _seed_profile(db_session, project, leader, version.sha256 or "")
    plan = _plan(profile.id)
    plan["steps"].append({"id": "quality", "op": "assert_quality", "params": {"kind": "unique", "column": "eq_id"}})
    plan_row = _persist_plan(db_session, leader, project, plan)
    run = _submit_run(client, project, leader, plan_row, version, settings)

    assert run["status"] == "budget_exhausted"
    assert run["conservation"]["ok"] is None
    base = f"/api/v1/projects/{project.id}/transform-runs/{run['id']}"
    headers = _headers(leader, settings)
    diff = client.get(f"{base}/diff", headers=headers).get_json()["data"]
    assert diff["input_rows"] is None
    assert diff["input_integrity"] == {"parse_error_rows": 0, "truncated": True}
    assert diff["conservation_ok"] is None
    feedback = client.get(f"{base}/quality-feedback", headers=headers).get_json()["data"]
    assert feedback["complete"] is False
    assert feedback["assertions"] == []


def test_diff_destinations_grouped_by_reason(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    plan_row = _persist_plan(db_session, leader, project)
    run = _insert_run(
        db_session,
        project,
        leader,
        plan_row,
        output_rows=[{"eq_id": "E1"}, {"eq_id": "E2"}],
        reject_ledger=[
            {"row_index": 1, "reason": "cast_failed", "column": "defect_pct"},
            {"row_index": 3, "reason": "cast_failed", "column": "defect_pct"},
            {"row_index": 4, "reason": "enum_unmapped", "column": "eq_id"},
        ],
        rejected_row_count=4,
        overflow_count=1,
        conservation={"input_rows": 6, "output_rows": 2, "rejected_rows": 4, "overflow_count": 1, "ok": True},
    )
    response = client.get(
        f"/api/v1/projects/{project.id}/transform-runs/{run.id}/diff",
        headers=_headers(leader, settings),
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()["data"]
    assert payload["destinations"]["output"] == 2
    assert payload["destinations"]["rejected_by_reason"] == {"cast_failed": 2, "enum_unmapped": 1}
    assert payload["destinations"]["overflow"] == payload["overflow_count"] == 1
    assert sum(payload["destinations"]["rejected_by_reason"].values()) + payload["overflow_count"] == payload["rejected_rows"]
    assert payload["input_rows"] == 6
    assert payload["conservation_ok"] is True
    assert len(payload["ledger_sample"]) == 3


def test_diff_quality_flags_separate_from_rejections(client, db_session, settings) -> None:
    """质量条目＝保留行违规记录（非拒绝）：diff 面单列 quality_flags，
    不计入 rejected 去向（17 号 §3.3 账本两类条目在呈现面的区分）。"""
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    plan_row = _persist_plan(db_session, leader, project)
    run = _insert_run(
        db_session,
        project,
        leader,
        plan_row,
        output_rows=[{"eq_id": "E1"}, {"eq_id": "E2"}],
        reject_ledger=[
            {"row_index": 2, "reason": "cast_failed", "column": "defect_pct"},
        ],
        rejected_row_count=1,
        quality_report={"q1": {"kind": "not_null", "column": "eq_id", "violations": 1}},
        conservation={"input_rows": 3, "output_rows": 2, "rejected_rows": 1, "overflow_count": 0, "ok": True},
    )
    response = client.get(
        f"/api/v1/projects/{project.id}/transform-runs/{run.id}/diff",
        headers=_headers(leader, settings),
    )
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["destinations"]["rejected_by_reason"] == {"cast_failed": 1}
    assert payload["destinations"]["quality_flags"] == {"quality_not_null": 1}
    assert payload["destinations"]["output"] == 2


def test_diff_expansion_note_many_to_one(client, db_session, settings) -> None:
    """join many_to_one 合法展开（1 输入行→N 产出）：弱守恒口径呈现，
    note 说明展开（17 号 §3.4 round2 修订的呈现化）。"""
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    plan_row = _persist_plan(db_session, leader, project)
    run = _insert_run(
        db_session,
        project,
        leader,
        plan_row,
        output_rows=[{"eq_id": f"E{i}"} for i in range(5)],
        output_row_count=5,
        reject_ledger=[{"row_index": 2, "reason": "cast_failed", "column": "defect_pct"}],
        rejected_row_count=1,
        conservation={"input_rows": 3, "output_rows": 5, "rejected_rows": 1, "overflow_count": 0, "ok": True},
    )
    response = client.get(
        f"/api/v1/projects/{project.id}/transform-runs/{run.id}/diff",
        headers=_headers(leader, settings),
    )
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["output_rows"] == 5
    assert payload["input_rows"] == 3
    assert payload["conservation_ok"] is True
    assert "展开" in payload["note"]


def test_diff_on_failed_run(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    plan_row = _persist_plan(db_session, leader, project)
    run = _insert_run(
        db_session,
        project,
        leader,
        plan_row,
        status="failed",
        failure_reason="duplicate_key",
        output_rows=[],
        output_row_count=0,
        conservation={"input_rows": 4, "output_rows": 0, "rejected_rows": 0, "overflow_count": 0, "ok": True},
    )
    response = client.get(
        f"/api/v1/projects/{project.id}/transform-runs/{run.id}/diff",
        headers=_headers(leader, settings),
    )
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["status"] == "failed"
    assert payload["failure_reason"] == "duplicate_key"
    assert payload["destinations"]["output"] == 0
    assert payload["conservation_ok"] is None
    lineage = client.get(
        f"/api/v1/projects/{project.id}/transform-runs/{run.id}/lineage",
        headers=_headers(leader, settings),
    )
    assert lineage.status_code == 200
    assert lineage.get_json()["data"]["final"]["conservation_ok"] is None


# ---- lineage ----------------------------------------------------------------

def test_lineage_two_level_alignment_end_to_end(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    version = _seed_csv_version(db_session, project, leader, "eq_id,defect_pct\nEQ-1,0.5\nEQ-2,1.5\n")
    profile = _seed_profile(db_session, project, leader, version.sha256 or "")
    plan_row = _persist_plan(db_session, leader, project, _plan(profile.id))
    run = _submit_run(client, project, leader, plan_row, version, settings)

    response = client.get(
        f"/api/v1/projects/{project.id}/transform-runs/{run['id']}/lineage",
        headers=_headers(leader, settings),
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()["data"]
    assert payload["plan_id"] == plan_row.id
    assert payload["plan_dag"]["nodes"] == ["s1"]
    assert payload["plan_dag"]["topological_order"] == ["s1"]
    assert payload["execution_steps"] == [
        {"step_id": "s1", "op": "select", "input_rows": 2, "output_rows": 2, "rejected_rows": 0}
    ]
    assert payload["steps_alignment"] is True
    assert payload["final"]["output_row_count"] == 2
    assert payload["final"]["conservation_ok"] is True


def test_lineage_alignment_false_reported_honestly(client, db_session, settings) -> None:
    """执行统计步序与计划 DAG 拓扑序不一致＝如实标 false（不静默）。"""
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    plan_row = _persist_plan(db_session, leader, project)
    run = _insert_run(
        db_session,
        project,
        leader,
        plan_row,
        lineage=[
            {"step_id": "sx", "op": "select", "input_rows": 2, "output_rows": 2, "rejected_rows": 0},
        ],
        conservation={"input_rows": 2, "output_rows": 2, "rejected_rows": 0, "overflow_count": 0, "ok": True},
    )
    response = client.get(
        f"/api/v1/projects/{project.id}/transform-runs/{run.id}/lineage",
        headers=_headers(leader, settings),
    )
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["steps_alignment"] is False


# ---- quality-feedback ---------------------------------------------------------

def test_quality_feedback_fail_without_row_values(client, db_session, settings) -> None:
    """反馈面：verdict fail + 违反计数；**全件零行值原文**——种子产物行里放
    哨兵值，反馈响应文本不得出现（账本纪律 04 §3.2 在反馈面的机检）。"""
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    plan = _plan()
    plan["steps"] = [{"id": "q1", "op": "assert_quality", "params": {"kind": "not_null", "column": "eq_id"}}]
    plan_row = _persist_plan(db_session, leader, project, plan)
    run = _insert_run(
        db_session,
        project,
        leader,
        plan_row,
        output_rows=[{"eq_id": "SECRET-OP-7", "defect_pct": 0.1}, {"eq_id": "E2", "defect_pct": 0.2}],
        lineage=[{"step_id": "q1", "op": "assert_quality", "input_rows": 2, "output_rows": 2, "rejected_rows": 0}],
        quality_report={"q1": {"kind": "not_null", "column": "eq_id", "violations": 1}},
        reject_ledger=[{"row_index": 0, "reason": "quality_not_null", "column": "eq_id"}],
        conservation={"input_rows": 2, "output_rows": 2, "rejected_rows": 0, "overflow_count": 0, "ok": True},
    )
    response = client.get(
        f"/api/v1/projects/{project.id}/transform-runs/{run.id}/quality-feedback",
        headers=_headers(leader, settings),
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_data(as_text=True)
    assert "SECRET-OP-7" not in body, "反馈面泄漏行值原文"
    payload = response.get_json()["data"]
    assert payload["overall"]["assertions_run"] == 1
    assert payload["overall"]["assertions_failed"] == 1
    assert payload["overall"]["total_violations"] == 1
    assert payload["assertions"][0]["verdict"] == "fail"
    assert payload["assertions"][0]["column"] == "eq_id"


@pytest.mark.parametrize(("survivors", "verdict"), [(0, "not_evaluated"), (1, "incomplete")])
def test_quality_feedback_uses_validated_order_and_observed_rows(client, db_session, settings, survivors, verdict) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    version = _seed_csv_version(
        db_session, project, leader, "eq_id,defect_pct\nEQ-1,bad\n" + "EQ-2,0.50\n" * survivors,
    )
    profile = _seed_profile(db_session, project, leader, version.sha256 or "")
    plan = _plan(profile.id)
    plan["steps"] = [
        {"id": "quality", "op": "assert_quality", "depends_on": ["cast"],
         "params": {"kind": "unique", "column": "eq_id"}},
        {"id": "cast", "op": "cast", "params": {"column": "defect_pct", "to_type": "number"}},
    ]
    plan_row = _persist_plan(db_session, leader, project, plan)
    run = _submit_run(client, project, leader, plan_row, version, settings)
    assert run["status"] == "succeeded"
    assert run["output_row_count"] == survivors
    assert run["rejected_row_count"] == 1
    base = f"/api/v1/projects/{project.id}/transform-runs/{run['id']}"
    headers = _headers(leader, settings)
    lineage = client.get(f"{base}/lineage", headers=headers).get_json()["data"]
    assert lineage["steps_alignment"] is True
    assert [step["step_id"] for step in lineage["execution_steps"]] == ["cast", "quality"]
    feedback = client.get(f"{base}/quality-feedback", headers=headers).get_json()["data"]
    assert feedback["input_row_count"] == 1 + survivors
    assert feedback["assertions"][0]["evaluated_rows"] == survivors
    assert feedback["assertions"][0]["rejected_before"] == 1
    assert feedback["assertions"][0]["verdict"] == verdict


def test_quality_feedback_pass_when_clean(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    plan = _plan()
    plan["steps"] = [{"id": "q1", "op": "assert_quality", "params": {"kind": "unique", "column": "eq_id"}}]
    plan_row = _persist_plan(db_session, leader, project, plan)
    run = _insert_run(
        db_session,
        project,
        leader,
        plan_row,
        lineage=[{"step_id": "q1", "op": "assert_quality", "input_rows": 2, "output_rows": 2, "rejected_rows": 0}],
        quality_report={"q1": {"kind": "unique", "column": "eq_id", "violations": 0}},
        conservation={"input_rows": 2, "output_rows": 2, "rejected_rows": 0, "overflow_count": 0, "ok": True},
    )
    response = client.get(
        f"/api/v1/projects/{project.id}/transform-runs/{run.id}/quality-feedback",
        headers=_headers(leader, settings),
    )
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["overall"] == {"assertions_run": 1, "assertions_failed": 0, "total_violations": 0}
    assert payload["assertions"][0]["verdict"] == "pass"


def test_legacy_success_without_input_integrity_has_no_full_verdict(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    plan = _plan()
    plan["steps"] = [{"id": "q1", "op": "assert_quality", "params": {"kind": "unique", "column": "eq_id"}}]
    plan_row = _persist_plan(db_session, leader, project, plan)
    run = _insert_run(
        db_session, project, leader, plan_row, legacy=True,
        lineage=[{"step_id": "q1", "op": "assert_quality", "input_rows": 1, "output_rows": 1, "rejected_rows": 0}],
        quality_report={"q1": {"kind": "unique", "column": "eq_id", "violations": 0}},
        conservation={"input_rows": 1, "ok": True},
    )
    base = f"/api/v1/projects/{project.id}/transform-runs/{run.id}"
    headers = _headers(leader, settings)
    assert client.get(base, headers=headers).get_json()["data"]["conservation"]["ok"] is None
    assert client.get(f"{base}/diff", headers=headers).get_json()["data"]["conservation_ok"] is None
    feedback = client.get(f"{base}/quality-feedback", headers=headers).get_json()["data"]
    assert feedback["input_row_count"] is None
    assert feedback["complete"] is False
    assert feedback["overall"]["assertions_failed"] is None
    assert feedback["assertions"][0]["verdict"] == "incomplete"


def test_quality_feedback_no_assertions(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    plan_row = _persist_plan(db_session, leader, project)
    run = _insert_run(
        db_session, project, leader, plan_row,
        lineage=[{"step_id": "s1", "op": "select", "input_rows": 0, "output_rows": 0, "rejected_rows": 0}],
    )
    response = client.get(
        f"/api/v1/projects/{project.id}/transform-runs/{run.id}/quality-feedback",
        headers=_headers(leader, settings),
    )
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["overall"] == {"assertions_run": 0, "assertions_failed": 0, "total_violations": 0}
    assert payload["assertions"] == []


# ---- 只读纪律 -----------------------------------------------------------------

def test_views_are_read_only_no_new_runs(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    plan_row = _persist_plan(db_session, leader, project)
    run = _insert_run(db_session, project, leader, plan_row)
    headers = _headers(leader, settings)
    base = f"/api/v1/projects/{project.id}/transform-runs/{run.id}"
    before = len(client.get(f"/api/v1/projects/{project.id}/transform-runs", headers=headers).get_json()["data"])
    for path in ("/preview", "/diff", "/lineage", "/quality-feedback"):
        assert client.get(f"{base}{path}", headers=headers).status_code == 200
    after = len(client.get(f"/api/v1/projects/{project.id}/transform-runs", headers=headers).get_json()["data"])
    assert before == after
