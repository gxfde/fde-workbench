"""V3.3 M5-WP3①：对客「冻结证据评审包」（D30，独立新模块 evidence_pack）。

四条验收语义（工作令 §3 WP3 条 1 / D30 / 决议 03 §6-3 / 改进单 M5-OPT-2）：
- **白名单物理阻断**：显式只读 DTO 字段白名单投影——``connection_ref``（S-07）、
  ``unresolved_questions``（S-20）、``internal_only``、内部人锚列不进白名单即
  出不了包（黑名单废除，测试注入恶意字段钉死投影面）；
- **离线 HTML 安全**：全值 ``html.escape`` + 零脚本静态
  ``CSP: default-src 'none'; style-src 'unsafe-inline'; img-src data:``；
- **服务端 HMAC 防伪**：独立密钥对 ``(org_id, package_id, pinned_version_id,
  pack_sha256)`` 签名；密钥缺省 fail-closed（503）；篡改任一分量即失配；
- **I7 异人签收回执**：``kind=ontology_annotation`` +
  ``captured_from=ontology_review:<package_id>``；导出人与 ``acceptor`` 同人
  硬拦（SoD）；无导出留痕的包不可签收（fail-closed）。

纯函数（投影/包 ID/HMAC/渲染）100% 确定性生成并支持离线重放验证（工作令
§1 条 6）；导出/签收全程 OperationEvent 留痕。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.auth.tokens import issue_access_token
from fde_api.evidence.models import ProjectEvidence
from fde_api.integrations.models import ProjectOntologyBinding
from fde_api.integrations.ontology_mock import (
    M5_SEED_VERSION_ID,
    SEED_ONTOLOGY_ID,
    MockOntologyAdapter,
)
from fde_api.ontology.evidence_pack import (
    EvidencePackError,
    build_pack_payload,
    compute_package_id,
    render_pack_html,
    sign_pack,
    verify_pack_signature,
)
from fde_api.workbench.models import OperationEvent
from fde_api.workbench.models import Project

from test_gates_api import AuthorizedClient
from test_gates_api import admin_client, gate_project  # noqa: F401  (fixture 供给方)

PACK_HMAC_KEY = "pack-hmac-secret"


# ---------------------------------------------------------------- fixtures


def _pack_settings(settings, monkeypatch, *, enabled: bool = True) -> None:
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "ontology_enabled", enabled, raising=False)
    monkeypatch.setattr(
        settings, "ontology_evidence_pack_hmac_key", SecretStr(PACK_HMAC_KEY), raising=False
    )


def _pack_env(gate_project, client, db_session, settings, monkeypatch, *, enabled=True):
    """(project, admin 导出客户端, lead 异人客户端) + 活跃绑定 + 两条证据行。

    证据行 1 混入**内部字段**（模拟未来列漂移/脏数据）：白名单投影必须把它们
    物理挡在包外——这是 D30「废除黑名单」的投影面钉子。
    """
    _pack_settings(settings, monkeypatch, enabled=enabled)
    project, _gates_url, leader = gate_project
    project_row = db_session.get(Project, project["id"])
    binding = ProjectOntologyBinding(
        org_id=project_row.org_id,
        project_id=project["id"],
        ontology_id=SEED_ONTOLOGY_ID,
        pinned_version_id=M5_SEED_VERSION_ID,
        pinned_version="1.1.0",
        binding_role="primary",
        status="active",
        active_marker="active",
        bound_by_user_id=leader.user.id,
    )
    db_session.add(binding)
    internal = ProjectEvidence(
        project_id=project["id"],
        kind="gate",
        source_uri="fdeops://m5/pack-internal",
        content_sha256="a" * 64,
        origin="gate:G5/探针",
        captured_from="human",
    )
    clean = ProjectEvidence(
        project_id=project["id"],
        kind="ontology_annotation",
        source_uri="fdeops://m5/pack-clean",
        content_sha256="b" * 64,
        origin="客户批注",
        captured_from="human",
    )
    db_session.add_all([internal, clean])
    db_session.commit()
    admin_row = db_session.scalar(select(User).where(User.username == "gate.admin"))
    assert admin_row is not None
    admin = AuthorizedClient(
        client,
        admin_row,
        {"Authorization": f"Bearer {issue_access_token(admin_row, settings)}"},
    )
    # gate_project 第三返回值即 leader_client（AuthorizedClient）
    env: dict[str, Any] = {
        "project": project,
        "project_row": project_row,
        "admin": admin,
        "lead": leader,
        "admin_user": admin_row,
        "lead_user": leader.user,
        "binding": binding,
    }
    return env


def _export_payload(
    *,
    org_id: str,
    pinned_version_id: str = M5_SEED_VERSION_ID,
    pack_sha256: str = "c" * 64,
    package_id: str = "",
    key: str = PACK_HMAC_KEY,
) -> str:
    package_id = package_id or "d" * 64
    return sign_pack(
        org_id=org_id,
        package_id=package_id,
        pinned_version_id=pinned_version_id,
        pack_sha256=pack_sha256,
        hmac_key=key,
    )


# ---------------------------------------------------------------- 纯函数层


def _sample_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "evidence_id": "ev-1",
        "kind": "gate",
        "source_uri": "fdeops://x/1",
        "content_sha256": "a" * 64,
        "origin": "gate:G5/客户成功案例",
        "captured_from": "human",
        "ontology_id": SEED_ONTOLOGY_ID,
        "pinned_version_id": M5_SEED_VERSION_ID,
        "object_ref_id": "ref-obj-1",
        # 恶意/内部字段：白名单外的脏数据必须被物理挡住
        "connection_ref": "env://secret-handle",
        "internal_only": True,
        "unresolved_questions": ["未决问题"],
        "created_by_user_id": "u-internal",
        "action_request_id": "ar-internal",
        "logic_eval_digest": "e" * 64,
    }
    row.update(overrides)
    return row


def test_pack_payload_whitelist_blocks_internal_fields() -> None:
    """白名单物理阻断：S-07/S-20/internal_only/内部人锚列不进投影。"""
    payload = build_pack_payload(
        project_code="PROJ-CODE-1",
        ontology_id=SEED_ONTOLOGY_ID,
        pinned_version="1.1.0",
        pinned_version_id=M5_SEED_VERSION_ID,
        governance={"included": False},
        gates_view=[{"gate_key": "G5", "status": "evidence", "decision": None}],
        evidence_rows=[_sample_row()],
    )
    text = json.dumps(payload, ensure_ascii=False)
    assert "connection_ref" not in text
    assert "env://secret-handle" not in text
    assert "internal_only" not in text
    assert "unresolved_questions" not in text
    assert "created_by_user_id" not in text
    assert "action_request_id" not in text
    assert "logic_eval_digest" not in text
    # 白名单内字段逐位保留
    ev = payload["evidence"][0]
    assert ev["source_uri"] == "fdeops://x/1"
    assert ev["object_ref_id"] == "ref-obj-1"


def test_pack_html_escapes_and_zero_script_csp() -> None:
    """HTML 全值转义 + 零脚本 CSP + 水印 + 包 ID。"""
    payload = build_pack_payload(
        project_code="PROJ-CODE-1",
        ontology_id=SEED_ONTOLOGY_ID,
        pinned_version="1.1.0",
        pinned_version_id=M5_SEED_VERSION_ID,
        governance={"included": False},
        gates_view=[],
        evidence_rows=[_sample_row(origin="<script>alert(1)</script>裸注入")],
    )
    package_id = compute_package_id(payload)
    html = render_pack_html(payload, package_id=package_id, signature="sig")
    assert "<script" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "default-src 'none'" in html and "style-src 'unsafe-inline'" in html
    assert "img-src data:" in html
    assert package_id in html and "PROJ-CODE-1" in html  # 包 ID + 水印


def test_pack_id_and_signature_deterministic_and_tamper_evident() -> None:
    """内容寻址包 ID + HMAC 四元组签名：确定性、离线重放、篡改即失配。"""
    payload_a = build_pack_payload(
        project_code="P",
        ontology_id="ont-1",
        pinned_version="1.0.0",
        pinned_version_id="ver-1",
        governance={"included": False},
        gates_view=[],
        evidence_rows=[_sample_row()],
    )
    payload_b = build_pack_payload(
        project_code="P",
        ontology_id="ont-1",
        pinned_version="1.0.0",
        pinned_version_id="ver-1",
        governance={"included": False},
        gates_view=[],
        evidence_rows=[_sample_row()],
    )
    assert compute_package_id(payload_a) == compute_package_id(payload_b)
    sha = compute_package_id(payload_a)
    sig = sign_pack(
        org_id="org-1", package_id=sha, pinned_version_id="ver-1",
        pack_sha256=sha, hmac_key=PACK_HMAC_KEY,
    )
    # 离线重放（不起 app）同签名
    assert sig == sign_pack(
        org_id="org-1", package_id=sha, pinned_version_id="ver-1",
        pack_sha256=sha, hmac_key=PACK_HMAC_KEY,
    )
    assert verify_pack_signature(
        org_id="org-1", package_id=sha, pinned_version_id="ver-1",
        pack_sha256=sha, signature=sig, hmac_key=PACK_HMAC_KEY,
    )
    # 篡改任一分量即失配
    for tweak in (
        {"org_id": "org-evil"},
        {"package_id": "0" * 64},
        {"pinned_version_id": "ver-evil"},
        {"pack_sha256": "0" * 64},
    ):
        assert not verify_pack_signature(
            hmac_key=PACK_HMAC_KEY, signature=sig,
            **{
                "org_id": "org-1",
                "package_id": sha,
                "pinned_version_id": "ver-1",
                "pack_sha256": sha,
                **tweak,
            },
        )
    assert not verify_pack_signature(
        org_id="org-1", package_id=sha, pinned_version_id="ver-1",
        pack_sha256=sha, signature=sig, hmac_key="wrong-key",
    )


# ---------------------------------------------------------------- 服务层


def test_export_requires_hmac_key_fail_closed(
    gate_project, client, db_session, settings, monkeypatch
):
    """密钥缺省 fail-closed：宁可拒绝不可裸包出闸（D30 防伪前提）。"""
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "ontology_evidence_pack_hmac_key", None, raising=False)
    from fde_api.ontology.evidence_pack import export_evidence_pack

    project, _url, leader = gate_project
    with pytest.raises(EvidencePackError) as excinfo:
        export_evidence_pack(
            db_session, actor=leader, project_id=project["id"], settings=settings
        )
    assert excinfo.value.code == "evidence_pack_not_configured"


def test_export_builds_signed_html_and_audits(
    gate_project, client, db_session, settings, monkeypatch
):
    """导出：包 ID/签名/HTML 齐备 + 导出事件留痕（回执异人验真的导出人锚）。"""
    env = _pack_env(gate_project, client, db_session, settings, monkeypatch)
    from fde_api.ontology.evidence_pack import export_evidence_pack

    result = export_evidence_pack(
        db_session,
        actor=env["admin_user"],
        project_id=env["project"]["id"],
        settings=settings,
        client=MockOntologyAdapter(),
    )
    assert result["evidence_count"] == 2
    assert len(result["pack_sha256"]) == 64 and len(result["package_id"]) == 64
    assert "<script" not in result["html"]
    # 导出留痕（changes.package_id 是签收异人验真的比对锚）
    event = db_session.scalar(
        select(OperationEvent).where(
            OperationEvent.project_id == env["project"]["id"],
            OperationEvent.event_type == "ontology_evidence_pack_exported",
        )
    )
    assert event is not None
    assert event.changes["package_id"] == result["package_id"]
    assert event.actor_user_id == env["admin_user"].id
    # 治理段在线（mock 种子有未处置候选 → gate_ready=False 透传）
    assert result["governance"]["included"] is True
    db_session.commit()


def test_export_governance_degraded_annotation(
    gate_project, client, db_session, settings, monkeypatch
):
    """runtime 不可达 → 降级段透明标注，包仍可出（证据包核心是证据清单）。"""
    env = _pack_env(gate_project, client, db_session, settings, monkeypatch)
    from fde_api.ontology.evidence_pack import export_evidence_pack

    adapter = MockOntologyAdapter()
    adapter.inject_fault("unavailable")
    result = export_evidence_pack(
        db_session,
        actor=env["admin_user"],
        project_id=env["project"]["id"],
        settings=settings,
        client=adapter,
    )
    assert result["governance"]["degraded"] is True
    db_session.commit()


def test_export_disabled_flag_honest_default(
    gate_project, client, db_session, settings, monkeypatch
):
    """ontology_enabled=False（存量默认）→ 治理段 included=false 诚实缺省。"""
    env = _pack_env(gate_project, client, db_session, settings, monkeypatch, enabled=False)
    from fde_api.ontology.evidence_pack import export_evidence_pack

    result = export_evidence_pack(
        db_session,
        actor=env["admin_user"],
        project_id=env["project"]["id"],
        settings=settings,
        client=MockOntologyAdapter(),
    )
    assert result["governance"]["included"] is False
    db_session.commit()


def test_receipt_rejects_tampered_pack(
    gate_project, client, db_session, settings, monkeypatch
):
    """篡改包（pack_sha256 与签名不配）→ 400 拒收。"""
    env = _pack_env(gate_project, client, db_session, settings, monkeypatch)
    from fde_api.ontology.evidence_pack import export_evidence_pack, import_annotation_receipt

    exported = export_evidence_pack(
        db_session,
        actor=env["admin_user"],
        project_id=env["project"]["id"],
        settings=settings,
        client=MockOntologyAdapter(),
    )
    payload = {
        "review_package_id": exported["package_id"],
        "pack_sha256": "f" * 64,  # 篡改
        "pinned_version_id": exported["pinned_version_id"],
        "signature": exported["signature"],
        "annotations": [
            {"source_uri": "fdeops://m5/note-1", "content_sha256": "1" * 64}
        ],
    }
    with pytest.raises(EvidencePackError) as excinfo:
        import_annotation_receipt(
            db_session, actor=env["lead_user"], project_id=env["project"]["id"],
            payload=payload, settings=settings,
        )
    assert excinfo.value.code == "pack_signature_invalid"
    db_session.commit()


def test_receipt_rejects_same_person_self_acceptance(
    gate_project, client, db_session, settings, monkeypatch
):
    """SoD 硬拦：导出人与 acceptor 同人 → 403（D30 内部自签洗白漏洞封堵）。"""
    env = _pack_env(gate_project, client, db_session, settings, monkeypatch)
    from fde_api.ontology.evidence_pack import export_evidence_pack, import_annotation_receipt

    exported = export_evidence_pack(
        db_session,
        actor=env["admin_user"],
        project_id=env["project"]["id"],
        settings=settings,
        client=MockOntologyAdapter(),
    )
    payload = {
        "review_package_id": exported["package_id"],
        "pack_sha256": exported["pack_sha256"],
        "pinned_version_id": exported["pinned_version_id"],
        "signature": exported["signature"],
        "annotations": [
            {"source_uri": "fdeops://m5/self-1", "content_sha256": "2" * 64}
        ],
    }
    with pytest.raises(EvidencePackError) as excinfo:
        import_annotation_receipt(
            db_session, actor=env["admin_user"], project_id=env["project"]["id"],
            payload=payload, settings=settings,
        )
    assert excinfo.value.code == "self_acceptance_forbidden"
    db_session.commit()


def test_receipt_without_export_record_fails_closed(
    gate_project, client, db_session, settings, monkeypatch
):
    """无导出留痕的包不可签收（fail-closed：签名对但流程不合法）。"""
    env = _pack_env(gate_project, client, db_session, settings, monkeypatch)
    from fde_api.ontology.evidence_pack import import_annotation_receipt

    org_id = env["project_row"].org_id
    payload = {
        "review_package_id": "d" * 64,
        "pack_sha256": "c" * 64,
        "pinned_version_id": M5_SEED_VERSION_ID,
        "signature": _export_payload(org_id=org_id),
        "annotations": [
            {"source_uri": "fdeops://m5/ghost", "content_sha256": "3" * 64}
        ],
    }
    with pytest.raises(EvidencePackError) as excinfo:
        import_annotation_receipt(
            db_session, actor=env["lead_user"], project_id=env["project"]["id"],
            payload=payload, settings=settings,
        )
    assert excinfo.value.code == "export_record_missing"
    db_session.commit()


def test_receipt_accepts_other_person_and_lands_evidence(
    gate_project, client, db_session, settings, monkeypatch
):
    """异人签收：HMAC 复核通过 → 逐条落 ontology_annotation 证据 + 幂等重放。"""
    env = _pack_env(gate_project, client, db_session, settings, monkeypatch)
    from fde_api.ontology.evidence_pack import export_evidence_pack, import_annotation_receipt

    exported = export_evidence_pack(
        db_session,
        actor=env["admin_user"],
        project_id=env["project"]["id"],
        settings=settings,
        client=MockOntologyAdapter(),
    )
    annotation = {
        "source_uri": f"fdeops://m5/receipt-{exported['package_id'][:8]}",
        "content_sha256": "4" * 64,
        "origin": "客户批注：指标口径确认",
    }
    payload = {
        "review_package_id": exported["package_id"],
        "pack_sha256": exported["pack_sha256"],
        "pinned_version_id": exported["pinned_version_id"],
        "signature": exported["signature"],
        "annotations": [annotation],
    }
    first = import_annotation_receipt(
        db_session, actor=env["lead_user"], project_id=env["project"]["id"],
        payload=payload, settings=settings,
    )
    assert first["accepted"] == 1 and first["duplicated"] == 0
    row = db_session.scalar(
        select(ProjectEvidence).where(
            ProjectEvidence.source_uri == f"ontology_review:{exported['package_id']}|{annotation['source_uri']}"
        )
    )
    assert row is not None
    assert row.kind == "ontology_annotation"
    assert row.captured_from == f"ontology_review:{exported['package_id']}"
    # 幂等重放：同指纹复用既有行（证据不可变，created=false 语义）
    second = import_annotation_receipt(
        db_session, actor=env["lead_user"], project_id=env["project"]["id"],
        payload=payload, settings=settings,
    )
    assert second["accepted"] == 0 and second["duplicated"] == 1
    # 签收留痕
    event = db_session.scalar(
        select(OperationEvent).where(
            OperationEvent.project_id == env["project"]["id"],
            OperationEvent.event_type == "ontology_annotation_receipt_imported",
        )
    )
    assert event is not None
    db_session.commit()


def test_receipt_validates_annotation_shape(
    gate_project, client, db_session, settings, monkeypatch
):
    """回执条目形状校验：sha256 非 64hex / source_uri 缺失 → 400。"""
    env = _pack_env(gate_project, client, db_session, settings, monkeypatch)
    from fde_api.ontology.evidence_pack import export_evidence_pack, import_annotation_receipt

    exported = export_evidence_pack(
        db_session,
        actor=env["admin_user"],
        project_id=env["project"]["id"],
        settings=settings,
        client=MockOntologyAdapter(),
    )
    payload = {
        "review_package_id": exported["package_id"],
        "pack_sha256": exported["pack_sha256"],
        "pinned_version_id": exported["pinned_version_id"],
        "signature": exported["signature"],
        "annotations": [{"source_uri": "fdeops://m5/bad", "content_sha256": "nothex"}],
    }
    with pytest.raises(EvidencePackError) as excinfo:
        import_annotation_receipt(
            db_session, actor=env["lead_user"], project_id=env["project"]["id"],
            payload=payload, settings=settings,
        )
    assert excinfo.value.code == "invalid_request"
    db_session.commit()


# ------------------------------------------------- party 六席评审缺陷修复钉
# （P1 2026-11-15 批准入线前批：①三闸顺序 ③annotations 无界 ⑤acceptor 资格闸
#   ⑥降级态进对客包——party 评审纪要见工作令 §6.1）


def test_receipt_gate_order_signature_before_export_record(
    gate_project, client, db_session, settings, monkeypatch
):
    """① 三闸「顺序即防线」：无效签名 + 无导出留痕 → 必须先落签名闸 400。

    签名闸在前挡的是包 ID 存在性 oracle——若留痕闸先行，攻击者可用
    409-vs-400 逐包探测导出记录存在性（Amelia 席 P2-1）。
    """
    env = _pack_env(gate_project, client, db_session, settings, monkeypatch)
    from fde_api.ontology.evidence_pack import import_annotation_receipt

    org_id = env["project_row"].org_id
    payload = {
        "review_package_id": "d" * 64,  # 幽灵包：无导出留痕
        "pack_sha256": "c" * 64,
        "pinned_version_id": M5_SEED_VERSION_ID,
        "signature": "0" * 64,  # 且签名无效
        "annotations": [
            {"source_uri": "fdeops://m5/ghost-bad-sig", "content_sha256": "6" * 64}
        ],
    }
    assert payload["signature"] != _export_payload(org_id=org_id)  # 确为坏签名
    with pytest.raises(EvidencePackError) as excinfo:
        import_annotation_receipt(
            db_session, actor=env["lead_user"], project_id=env["project"]["id"],
            payload=payload, settings=settings,
        )
    assert excinfo.value.code == "pack_signature_invalid"  # 不得是 export_record_missing
    assert excinfo.value.status == 400
    db_session.commit()


def test_receipt_rejects_viewer_acceptor(
    gate_project, client, db_session, settings, monkeypatch
):
    """⑤ acceptor 资格闸：签收是写路径（落证据行+事件），viewer 不可为 → 404。

    S-01 统一不泄露存在性（Vex 席 P1：view-only 成员不得经签收写入证据）。
    """
    from fde_api.auth.models import User
    from fde_api.workbench.models import ProjectMember

    env = _pack_env(gate_project, client, db_session, settings, monkeypatch)
    from fde_api.ontology.evidence_pack import export_evidence_pack, import_annotation_receipt

    viewer = User(
        username="wp3-pack-viewer",
        role="viewer",
        org_id=env["project_row"].org_id,
        password_hash="x",
        must_change_password=False,
        is_active=True,
    )
    db_session.add(viewer)
    db_session.flush()
    db_session.add(
        ProjectMember(project_id=env["project"]["id"], user_id=viewer.id, role="viewer")
    )
    exported = export_evidence_pack(
        db_session,
        actor=env["admin_user"],
        project_id=env["project"]["id"],
        settings=settings,
        client=MockOntologyAdapter(),
    )
    payload = {
        "review_package_id": exported["package_id"],
        "pack_sha256": exported["pack_sha256"],
        "pinned_version_id": exported["pinned_version_id"],
        "signature": exported["signature"],
        "annotations": [
            {"source_uri": "fdeops://m5/viewer-sig", "content_sha256": "7" * 64}
        ],
    }
    with pytest.raises(EvidencePackError) as excinfo:
        import_annotation_receipt(
            db_session, actor=viewer, project_id=env["project"]["id"],
            payload=payload, settings=settings,
        )
    assert excinfo.value.status == 404  # S-01：与不可见同形
    db_session.rollback()
    db_session.commit()


def test_receipt_rejects_annotation_flood(
    gate_project, client, db_session, settings, monkeypatch
):
    """③ 回执容量硬限：annotations ≤200 条、origin ≤200 字符（Vex 席 P2-1）。"""
    env = _pack_env(gate_project, client, db_session, settings, monkeypatch)
    from fde_api.ontology.evidence_pack import export_evidence_pack, import_annotation_receipt

    exported = export_evidence_pack(
        db_session,
        actor=env["admin_user"],
        project_id=env["project"]["id"],
        settings=settings,
        client=MockOntologyAdapter(),
    )
    base = {
        "review_package_id": exported["package_id"],
        "pack_sha256": exported["pack_sha256"],
        "pinned_version_id": exported["pinned_version_id"],
        "signature": exported["signature"],
    }
    flood = [
        {"source_uri": f"fdeops://m5/flood-{i}", "content_sha256": "8" * 64}
        for i in range(201)
    ]
    with pytest.raises(EvidencePackError) as excinfo:
        import_annotation_receipt(
            db_session, actor=env["lead_user"], project_id=env["project"]["id"],
            payload={**base, "annotations": flood}, settings=settings,
        )
    assert "200" in str(excinfo.value)
    long_origin = [
        {
            "source_uri": "fdeops://m5/long-origin",
            "content_sha256": "9" * 64,
            "origin": "x" * 201,
        }
    ]
    with pytest.raises(EvidencePackError):
        import_annotation_receipt(
            db_session, actor=env["lead_user"], project_id=env["project"]["id"],
            payload={**base, "annotations": long_origin}, settings=settings,
        )
    db_session.rollback()
    db_session.commit()


def test_export_degraded_pack_carries_visible_annotation(
    gate_project, client, db_session, settings, monkeypatch
):
    """⑥ 降级态透明标注出对客包：degraded 进白名单投影 + HTML 显式标注。

    工作令 §1 条 4「对客证据包透明标注本体校验在线/降级态」（Grumbal 席
    P2-C：投影丢键 = HTML 零标注 = 承诺落空）。
    """
    env = _pack_env(gate_project, client, db_session, settings, monkeypatch)
    from fde_api.ontology.evidence_pack import export_evidence_pack

    adapter = MockOntologyAdapter()
    adapter.inject_fault("unavailable")
    result = export_evidence_pack(
        db_session,
        actor=env["admin_user"],
        project_id=env["project"]["id"],
        settings=settings,
        client=adapter,
    )
    # 投影面：degraded 键进白名单（出得了闸）
    projected = build_pack_payload(
        project_code="P",
        ontology_id=SEED_ONTOLOGY_ID,
        pinned_version="1.1.0",
        pinned_version_id=M5_SEED_VERSION_ID,
        governance=result["governance"],
        gates_view=[],
        evidence_rows=[_sample_row()],
    )
    assert projected["ontology"]["degraded"] is True
    # 渲染面：HTML 显式降级标注（客户离线打开即可见）
    assert "本体校验降级" in result["html"]
    db_session.commit()


# ------------------------------------------------- 回植前置评审 patch/dedentry


def test_receipt_cross_package_same_file_not_folded(
    gate_project, client, db_session, settings, monkeypatch
):
    """D1 跨包互踩：同 uri+sha 批注在两个不同包中签收 → 各自成行。

    工作令 §1 条 1 明令规避 (project_id, source_uri, content_sha256) 唯一键
    互踩——批注落库时 source_uri 编码包 ID 前缀，captured_from 与 source_uri
    双锚各自指向其来源包（P1 拍板：零 DDL 方案）。
    """
    env = _pack_env(gate_project, client, db_session, settings, monkeypatch)
    from fde_api.ontology.evidence_pack import export_evidence_pack, import_annotation_receipt

    # 第一包：当前两条证据行
    first_pack = export_evidence_pack(
        db_session,
        actor=env["admin_user"],
        project_id=env["project"]["id"],
        settings=settings,
        client=MockOntologyAdapter(),
    )
    annotation = {"source_uri": "fdeops://m5/cross-file", "content_sha256": "a" * 64}
    first_receipt = import_annotation_receipt(
        db_session, actor=env["lead_user"], project_id=env["project"]["id"],
        payload={
            "review_package_id": first_pack["package_id"],
            "pack_sha256": first_pack["pack_sha256"],
            "pinned_version_id": first_pack["pinned_version_id"],
            "signature": first_pack["signature"],
            "annotations": [annotation],
        },
        settings=settings,
    )
    assert first_receipt["accepted"] == 1

    # 第二包：新增一条证据行 → 包内容变化 → 不同 package_id
    db_session.add(
        ProjectEvidence(
            project_id=env["project"]["id"],
            kind="gate",
            source_uri="fdeops://m5/second-pack-ev",
            content_sha256="d" * 64,
            captured_from="human",
        )
    )
    db_session.commit()
    second_pack = export_evidence_pack(
        db_session,
        actor=env["admin_user"],
        project_id=env["project"]["id"],
        settings=settings,
        client=MockOntologyAdapter(),
    )
    assert second_pack["package_id"] != first_pack["package_id"]

    second_receipt = import_annotation_receipt(
        db_session, actor=env["lead_user"], project_id=env["project"]["id"],
        payload={
            "review_package_id": second_pack["package_id"],
            "pack_sha256": second_pack["pack_sha256"],
            "pinned_version_id": second_pack["pinned_version_id"],
            "signature": second_pack["signature"],
            "annotations": [annotation],  # 同 uri + 同 sha
        },
        settings=settings,
    )
    # 互踩修复后：第二包是独立签收（非折叠 duplicated）
    assert second_receipt["accepted"] == 1, second_receipt
    assert second_receipt["duplicated"] == 0
    rows = db_session.scalars(
        select(ProjectEvidence).where(
            ProjectEvidence.source_uri.like("ontology_review:%|fdeops://m5/cross-file")
        )
    ).all()
    assert len(rows) == 2  # 两包各自成行
    assert {r.captured_from for r in rows} == {
        f"ontology_review:{first_pack['package_id']}",
        f"ontology_review:{second_pack['package_id']}",
    }
    db_session.commit()


def test_pack_excludes_internal_compiler_telemetry(
    gate_project, client, db_session, settings, monkeypatch
):
    """D2 古德哈特护栏：内部编译器遥测不出对客包（payload + HTML 双断言）。"""
    env = _pack_env(gate_project, client, db_session, settings, monkeypatch)
    from fde_api.ontology.evidence_pack import export_evidence_pack

    result = export_evidence_pack(
        db_session,
        actor=env["admin_user"],
        project_id=env["project"]["id"],
        settings=settings,
        client=MockOntologyAdapter(),
    )
    assert "compiler_telemetry" not in result["html"]
    assert "unmodified_accept_rate" not in result["html"]
    db_session.commit()


def test_export_and_receipt_cross_tenant_are_404(
    gate_project, client, db_session, settings, monkeypatch
):
    """P2 两 POST 防伪面跨租户隔离：外企业用户 → 404（S-01 同形）。"""
    from fde_api.auth.models import User
    from fde_api.ontology.evidence_pack import export_evidence_pack, import_annotation_receipt
    from fde_api.orgs.models import ORG_TYPE_ENTERPRISE, Org

    env = _pack_env(gate_project, client, db_session, settings, monkeypatch)
    db_session.add(Org(id="org-outsider", org_type=ORG_TYPE_ENTERPRISE, name="外企业-证据包隔离"))
    db_session.flush()
    outsider = User(
        username="wp3-pack-outsider",
        role="project_lead",
        org_id="org-outsider",
        password_hash="x",
        must_change_password=False,
        is_active=True,
    )
    db_session.add(outsider)
    db_session.commit()
    pid = env["project"]["id"]
    with pytest.raises(EvidencePackError) as excinfo:
        export_evidence_pack(db_session, actor=outsider, project_id=pid, settings=settings)
    assert excinfo.value.status == 404
    with pytest.raises(EvidencePackError) as excinfo:
        import_annotation_receipt(
            db_session,
            actor=outsider,
            project_id=pid,
            payload={"review_package_id": "d" * 64, "pack_sha256": "c" * 64,
                     "pinned_version_id": "v", "signature": "s",
                     "annotations": [{"source_uri": "u", "content_sha256": "1" * 64}]},
            settings=settings,
        )
    assert excinfo.value.status == 404
    db_session.rollback()


def test_sod_anchors_first_export_not_latest(
    gate_project, client, db_session, settings, monkeypatch
):
    """P3 SoD 锚定首次导出：重导出同一内容不换锚，首经办人仍被拦。

    内容寻址使同包可被第二人幂等重导出——若锚取最新事件，首经办人 A 即可
    经 B 重导出完成自签收（评审 P3：换锚洗 SoD）。
    """
    env = _pack_env(gate_project, client, db_session, settings, monkeypatch)
    from fde_api.ontology.evidence_pack import export_evidence_pack, import_annotation_receipt

    first = export_evidence_pack(
        db_session,
        actor=env["admin_user"],
        project_id=env["project"]["id"],
        settings=settings,
        client=MockOntologyAdapter(),
    )
    second = export_evidence_pack(
        db_session,
        actor=env["lead_user"],  # 异人重导出同一内容 → 同 package_id
        project_id=env["project"]["id"],
        settings=settings,
        client=MockOntologyAdapter(),
    )
    assert second["package_id"] == first["package_id"]
    payload = {
        "review_package_id": first["package_id"],
        "pack_sha256": first["pack_sha256"],
        "pinned_version_id": first["pinned_version_id"],
        "signature": first["signature"],
        "annotations": [
            {"source_uri": "fdeops://m5/rewash", "content_sha256": "b" * 64}
        ],
    }
    with pytest.raises(EvidencePackError) as excinfo:
        import_annotation_receipt(
            db_session, actor=env["admin_user"], project_id=env["project"]["id"],
            payload=payload, settings=settings,
        )
    assert excinfo.value.code == "self_acceptance_forbidden"
    db_session.rollback()
    db_session.commit()


# ---------------------------------------------------------------- 路由烟测


def test_routes_export_and_receipt_http(
    gate_project, admin_client, client, db_session, settings, monkeypatch
):
    """HTTP 面：导出 → 异人签收全链（route → service 接线烟测）。"""
    env = _pack_env(gate_project, client, db_session, settings, monkeypatch)
    pid = env["project"]["id"]
    # HTTP 面走真实 client_from_settings：补 S-02 凭据占位（连接失败 → 治理段
    # 降级标注，证据包核心是本地证据清单，不因 runtime 不可达拒绝导出）
    from pydantic import SecretStr

    monkeypatch.setattr(
        settings, "ontology_api_key", SecretStr("route-test-key"), raising=False
    )
    monkeypatch.setattr(
        settings, "ontology_signing_key", SecretStr("route-test-signing"), raising=False
    )
    export = env["admin"].post(f"/api/v1/projects/{pid}/ontology/evidence-packs/export", json={})
    assert export.status_code == 200, export.get_data(as_text=True)
    body = export.json["data"]
    assert body["package_id"] and body["signature"]
    # 异人签收经 HTTP
    receipt = env["lead"].post(
        f"/api/v1/projects/{pid}/ontology/evidence-packs/receipt",
        json={
            "review_package_id": body["package_id"],
            "pack_sha256": body["pack_sha256"],
            "pinned_version_id": body["pinned_version_id"],
            "signature": body["signature"],
            "annotations": [
                {
                    "source_uri": "fdeops://m5/http-receipt",
                    "content_sha256": "5" * 64,
                }
            ],
        },
    )
    assert receipt.status_code == 200, receipt.get_data(as_text=True)
    assert receipt.json["data"]["accepted"] == 1
    db_session.commit()
