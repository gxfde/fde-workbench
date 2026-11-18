"""AF2-WP1 第一批：资料只读画像与采样（03 §77 / 15 号 §3 WP1 行）。

画像器是**纯函数**：输入 = 上传文件字节（CSV/XLSX），输出 = 画像报告
（表结构/类型推断/空值/唯一性/关系候选）+ 脱敏样本。四纪律钉：

- 画像产物只存统计 + 掩码样本 + 来源指纹（04 §3.2：原始敏感行留在授权
  域，工程日志只存引用、统计和错误类别）；``input_sha256`` 可复验快照；
- 关系候选只登记（status 恒 ``candidate``，模型与 API 均无翻产通道）——
  未知关联不能自动变成生产 Join（03 §77 验收行）；
- 解析失败行如实计数（``error_rows``），行数守恒不被静默丢行美化
  （05 §3 分母完整性同源纪律）；
- 只读：解析全在内存，不触碰 files 域状态、不写任何源数据（AF2 源数据
  零覆盖红线的前置面）。

路由面：项目域上传→画像（member 级 can_view = 项目授权内预览档，04 §4）；
非项目成员 404（S-01 不泄露存在性）。
"""
from __future__ import annotations

import uuid
from datetime import date
from hashlib import sha256
from io import BytesIO

import pytest
from sqlalchemy import select

from conftest import INITIAL_PASSWORD as PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.data_engineering.masking import mask_value
from fde_api.data_engineering.models import DataProfile
from fde_api.data_engineering.profiling import (
    MAX_PROFILE_BYTES,
    ProfileError,
    profile_bytes,
)
from fde_api.workbench.models import Project, ProjectMember

CSV_BASIC = (
    "样品编号,批次号,检测日期,合格,结论备注\n"
    "SP-001,LOT-1,2026-01-02,true,ok\n"
    "SP-002,LOT-1,2026-01-03,false,复检\n"
    "SP-003,LOT-2,2026-01-04,true,ok\n"
    ",LOT-2,2026-01-05,true,缺编号\n"
).encode("utf-8")


def _xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet_a = workbook.active
    sheet_a.title = "样品表"
    sheet_a.append(["样品编号", "结论"])
    sheet_a.append(["SP-001", "ok"])
    sheet_a.append(["SP-002", "复检"])
    sheet_b = workbook.create_sheet("批次表")
    sheet_b.append(["批次号", "样品编号"])
    sheet_b.append(["LOT-1", "SP-001"])
    sheet_b.append(["LOT-2", "SP-003"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# ---- 纯函数层：表结构 / 类型 / 空值 / 唯一性 ---------------------------------


def test_profile_csv_reports_structure_types_nulls_uniqueness() -> None:
    report = profile_bytes(filename="samples.csv", data=CSV_BASIC)

    assert report["source_name"] == "samples.csv"
    assert report["input_sha256"] == sha256(CSV_BASIC).hexdigest()
    assert report["truncated"] is False
    table = report["tables"][0]
    assert table["name"] == "samples"
    assert table["row_count"] == 4 and table["error_rows"] == 0  # 行数守恒
    columns = {column["name"]: column for column in table["columns"]}
    assert set(columns) == {"样品编号", "批次号", "检测日期", "合格", "结论备注"}
    assert columns["样品编号"]["inferred_type"] == "string"
    assert columns["批次号"]["inferred_type"] == "string"
    assert columns["检测日期"]["inferred_type"] == "date"
    assert columns["合格"]["inferred_type"] == "boolean"
    assert columns["样品编号"]["null_count"] == 1
    assert columns["样品编号"]["unique_count"] == 3  # 缺编号行不计入非空唯一值
    assert columns["批次号"]["unique_count"] == 2


# ---- 纯函数层：关系候选（只登记，不翻产） ------------------------------------


def test_profile_xlsx_multi_sheet_registers_relation_candidates() -> None:
    report = profile_bytes(filename="workbook.xlsx", data=_xlsx_bytes())

    tables = {table["name"]: table for table in report["tables"]}
    assert set(tables) == {"样品表", "批次表"}
    candidates = report["relation_candidates"]
    pairs = {
        (item["left_table"], item["right_table"], item["left_column"], item["right_column"])
        for item in candidates
    }
    # 同名列 + 类型兼容 → 双向候选都登记（方向留给人工/WP2 受限 Join 裁决）
    assert ("样品表", "批次表", "样品编号", "样品编号") in pairs
    assert ("批次表", "样品表", "样品编号", "样品编号") in pairs
    for item in candidates:
        assert item["status"] == "candidate"
        assert item["basis"]  # 候选依据（same_name_type_compatible 等）必须留痕


def test_relation_candidates_have_no_production_state() -> None:
    """钉死「不自动变生产 Join」：候选序列化键空间里不存在任何生产态——
    模型与 API 均不提供 candidate → production 翻转通道（WP2 受限 Join
    走显式审批面时另立契约，不在画像产物上开口子）。"""
    report = profile_bytes(filename="workbook.xlsx", data=_xlsx_bytes())
    for item in report["relation_candidates"]:
        assert set(item) <= {
            "left_table", "right_table", "left_column", "right_column",
            "basis", "status", "overlap_ratio",
        }
        assert item["status"] == "candidate"


# ---- 纯函数层：脱敏样本 ------------------------------------------------------


def test_samples_mask_pii_by_name_and_value_patterns() -> None:
    csv_pii = (
        "姓名,联系电话,邮箱,样品编号,检测日期\n"
        "张三,13812345678,zhang@example.com,SP-001,2026-01-02\n"
        "李四,13987654321,li@example.com,SP-002,2026-01-03\n"
    ).encode("utf-8")

    report = profile_bytes(filename="pii.csv", data=csv_pii)
    table = report["tables"][0]
    assert table["row_count"] == 2
    for row in report["samples"]["pii"]:
        assert row["姓名"] not in {"张三", "李四"}                     # 列名敏感 → 掩码
        assert "13812345678" not in str(row["联系电话"])              # 值正则兜底
        assert str(row["邮箱"]).startswith("z***") or str(row["邮箱"]).startswith("l***")
        assert "zhang@example.com" not in str(row["邮箱"])            # 原文不出现
        assert row["样品编号"] in {"SP-001", "SP-002"}                # 非敏感列原值保留
        assert row["检测日期"] in {"2026-01-02", "2026-01-03"}


def test_mask_value_by_kind() -> None:
    assert mask_value("13812345678", "phone").startswith("138")
    assert mask_value("13812345678", "phone").endswith("78")
    assert "***" in mask_value("13812345678", "phone")
    assert set(mask_value("110101199003078615", "idcard")) == {"*"}  # 证件全掩
    assert mask_value("zhang@example.com", "email").count("@") == 1
    assert "***" in mask_value("zhang@example.com", "email")
    assert mask_value("普通值", "generic") != "普通值"


# ---- 纯函数层：失败行如实计数 + 截断如实标注 --------------------------------


def test_parse_error_rows_counted_not_silently_dropped() -> None:
    malformed = (
        "a,b\n1,2\n\"未闭合,3\n4,5\n"
    ).encode("utf-8")

    report = profile_bytes(filename="broken.csv", data=malformed)
    table = report["tables"][0]
    # 行数守恒：成功行 + 失败行 = 全部数据行（不许静默丢行美化统计）
    assert table["row_count"] + table["error_rows"] == 2


def test_truncation_flag_over_row_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    import fde_api.data_engineering.profiling as profiling

    monkeypatch.setattr(profiling, "MAX_ROWS", 3)
    many_rows = b"a\n" + b"".join(f"{i}\n".encode() for i in range(10))

    report = profile_bytes(filename="big.csv", data=many_rows)
    assert report["truncated"] is True
    assert report["tables"][0]["row_count"] == 3


def test_rejects_oversize_bytes() -> None:
    with pytest.raises(ProfileError) as error:
        profile_bytes(filename="huge.csv", data=b"a,b\n" + b"x" * (MAX_PROFILE_BYTES + 1))
    assert "too_large" in str(error.value)


# ---- 路由层：项目域 + 权限 + 快照可复验 ---------------------------------------


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
    project = Project(
        project_code=f"DE-{uuid.uuid4().hex[:8]}",
        name="Data engineering project",
        enterprise_code="Example·行业·城市",
        planned_start_date=date(2026, 9, 1),
        leader_user_id=leader.id,
        status="active",
        template_snapshot={},
    )
    db_session.add(project)
    db_session.commit()
    return project


def _headers(user: User, settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


def test_create_and_get_profile_scoped_to_project(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    outsider = _make_user(db_session, "fde_engineer")
    member = _make_user(db_session, "viewer")
    db_session.add(ProjectMember(project_id=project.id, user_id=member.id, role="member"))
    db_session.commit()

    # 非项目成员 → 404（S-01 不泄露存在性）
    response = client.post(
        f"/api/v1/projects/{project.id}/data-profiles",
        data={"file": (BytesIO(CSV_BASIC), "samples.csv")},
        headers=_headers(outsider, settings),
        content_type="multipart/form-data",
    )
    assert response.status_code == 404

    # 项目成员（viewer 全局角色 + member）→ 201：画像=项目授权内预览档（04 §4）
    response = client.post(
        f"/api/v1/projects/{project.id}/data-profiles",
        data={"file": (BytesIO(CSV_BASIC), "samples.csv")},
        headers=_headers(member, settings),
        content_type="multipart/form-data",
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    body = response.get_json()
    profile = body["data"]
    assert profile["input_sha256"] == sha256(CSV_BASIC).hexdigest()
    assert profile["created_by_user_id"] == member.id
    assert profile["tables"][0]["row_count"] == 4

    # 详情：成员可读、外人 404；快照哈希逐位一致（可复验）
    detail = client.get(
        f"/api/v1/projects/{project.id}/data-profiles/{profile['id']}",
        headers=_headers(member, settings),
    )
    assert detail.status_code == 200
    assert detail.get_json()["data"]["input_sha256"] == sha256(CSV_BASIC).hexdigest()
    outsider_detail = client.get(
        f"/api/v1/projects/{project.id}/data-profiles/{profile['id']}",
        headers=_headers(outsider, settings),
    )
    assert outsider_detail.status_code == 404

    listing = client.get(
        f"/api/v1/projects/{project.id}/data-profiles",
        headers=_headers(member, settings),
    )
    assert listing.status_code == 200
    ids = [item["id"] for item in listing.get_json()["data"]]
    assert profile["id"] in ids


def test_rejects_unsupported_extension(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)

    response = client.post(
        f"/api/v1/projects/{project.id}/data-profiles",
        data={"file": (BytesIO(b"MZ fake"), "evil.exe")},
        headers=_headers(leader, settings),
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "unsupported_file_type"


def test_profile_row_persisted_and_readable_via_model(client, db_session, settings) -> None:
    """落库面钉：画像行挂 project_id（租户隔离）；落库产物是统计+掩码样本，
    不是文件副本——敏感列原文（手机号）不得出现在任何落库 JSON 里（04 §3.2
    引用/统计纪律；非敏感列原值允许留在授权域内产物中）。"""
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    csv_pii = (
        "姓名,联系电话,样品编号\n"
        "张三,13812345678,SP-001\n"
    ).encode("utf-8")

    response = client.post(
        f"/api/v1/projects/{project.id}/data-profiles",
        data={"file": (BytesIO(csv_pii), "pii.csv")},
        headers=_headers(leader, settings),
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    profile_id = response.get_json()["data"]["id"]

    row = db_session.scalar(select(DataProfile).where(DataProfile.id == profile_id))
    assert row is not None
    assert row.project_id == project.id
    serialized = str(row.tables_json) + str(row.samples_json)
    assert "13812345678" not in serialized, "敏感列原文不得落库"
    assert "SP-001" in serialized, "非敏感列原值保留（授权域内产物）"
