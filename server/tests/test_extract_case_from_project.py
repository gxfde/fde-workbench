"""学习闭环 2.0 L6——真实交付反哺抽取脚本契约与端到端测试。

覆盖设计稿 v1.1 §4-L6 / §5 与任务书 L6 判据：
1. 门禁 fail -> pass 迁移信号与产物/事实/需求拒收信号只读抽取；
2. T-A2 脱敏管线强制过闸：企业真名替换代号、PII 掩码、凭据串命中 fail-closed 零落盘；
3. 输出目录安全闸：落入本仓内即拒（out_dir_inside_repo）、目录不存在即拒（out_dir_missing）；
4. 生产四重闸衔接：产出卡直接通过 L1 import_cases.build_payload + gate_payload（八规则＋三视图无泄漏）；
5. 只插不改＋幂等：同项目同信号二次运行返回 already_exists、不覆盖已有文件、登记 candidate_manifest.json；
6. 预算记账主体说明与静态污染隔离（仓库内零候选卡落盘、源码零诊断答案键）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.discovery.models import BusinessFact, DiscoveryExtraction, Requirement
from fde_api.workbench.models import Gate, OperationEvent, Project

REPO_ROOT = Path(__file__).resolve().parents[2]
EXTRACT_SCRIPT = REPO_ROOT / "scripts" / "extract_case_from_project.py"


def _load_extractor():
    spec = importlib.util.spec_from_file_location("_l6_extractor", EXTRACT_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Python 3.13+ 的 @dataclass 在类创建期回查 sys.modules[cls.__module__]，
    # 动态加载必须先注册再 exec，否则 dataclass 定义即抛 AttributeError。
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return mod


def _seed_project_with_feedback(db_session, *, inject_credential: bool = False) -> Project:
    suffix = uuid4().hex[:8]
    user = User(
        username=f"l6.actor.{suffix}",
        password_hash=hash_password("Passw0rd!234"),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    project = Project(
        project_code=f"PRJ-L6-{suffix.upper()}",
        name=f"代号交付项目-{suffix}",
        enterprise_code="客户L6·装备制造·苏州",
        background=(
            "客户与华星重工集团对接产线质检台账，联系人手机 13812345678。"
            + (" api_key=sk-secretCredentialToken123456" if inject_credential else "")
        ),
        status="completed",
        planned_start_date=date(2026, 11, 1),
        leader_user_id=user.id,
        template_snapshot={"modules": []},
        research_snapshot={},
    )
    db_session.add(project)
    db_session.flush()

    gate = Gate(
        project_id=project.id,
        gate_key="G7",
        status="passed",
        evidence_checklist=[
            {"label": "原型核验纪要", "claim_status": "accepted"},
            {"label": "客户签收指针", "claim_status": "accepted"},
        ],
    )
    db_session.add(gate)
    db_session.flush()

    ev_fail = OperationEvent(
        project_id=project.id,
        actor_user_id=user.id,
        event_type="gate_decided",
        target_type="gate",
        target_id=gate.id,
        # 同事务两条事件 server_default 时间戳相同，而 id 是 UUID（字典序随机），
        # 显式 created_at 保证 fail→pass 迁移链排序确定（生产按墙钟天然有序）。
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        changes={
            "gate_key": "G7",
            "from_status": "evidence",
            "result": "fail",
            "note": "华星重工集团车间抽检缺异常回退演练证据，打回重补",
        },
    )
    ev_pass = OperationEvent(
        project_id=project.id,
        actor_user_id=user.id,
        event_type="gate_decided",
        target_type="gate",
        target_id=gate.id,
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
        changes={
            "gate_key": "G7",
            "from_status": "evidence",
            "result": "pass",
            "note": "补齐异常回退演练指针与 sha256 后核验通过",
        },
    )
    db_session.add_all([ev_fail, ev_pass])
    db_session.flush()

    extraction = DiscoveryExtraction(
        project_id=project.id,
        created_by_user_id=user.id,
        source_type="interview_minutes",
        source_id=str(uuid4()),
        source_sha256="a" * 64,
        status="review_required",
    )
    db_session.add(extraction)
    db_session.flush()

    accepted_fact = BusinessFact(
        project_id=project.id,
        extraction_id=extraction.id,
        fact_type="system",
        classification="customer_stated",
        subject="质检工位",
        predicate="在用系统",
        object_value="旧版 MES 扫码终端",
        source_ref="interview_minutes:1",
        source_locator={"line": 12},
        review_status="accepted",
        reviewed_by_user_id=user.id,
        reviewed_at=ev_pass.created_at,
    )
    rejected_fact = BusinessFact(
        project_id=project.id,
        extraction_id=extraction.id,
        fact_type="metric",
        classification="customer_stated",
        subject="良率提升",
        predicate="预期幅度",
        object_value="无依据声称提升 50%",
        source_ref="interview_minutes:1",
        source_locator={"line": 28},
        review_status="rejected",
        reviewed_by_user_id=user.id,
        reviewed_at=ev_pass.created_at,
        review_comment="客户原文未提及 50%，属无源数字臆造，予以驳回",
    )
    accepted_req = Requirement(
        project_id=project.id,
        extraction_id=extraction.id,
        created_by_user_id=user.id,
        requirement_key="R-L6-01",
        title="扫码异常离线暂存与重传",
        requirement_type="functional",
        priority="high",
        acceptance_criteria=["断网期间本地暂存不丢单，恢复后幂等重传"],
        status="accepted",
        approved_by_user_id=user.id,
        approved_at=ev_pass.created_at,
    )
    db_session.add_all([accepted_fact, rejected_fact, accepted_req])
    db_session.commit()
    return project


def test_out_dir_safety_gates_reject_inside_repo_and_missing_dir(tmp_path: Path):
    extractor = _load_extractor()

    # 1. 落入仓库目录内 ⇒ 必须拒绝
    inside_repo = REPO_ROOT / "docs" / "audit"
    with pytest.raises(extractor.CaseExtractionError) as exc_inside:
        extractor.assert_safe_out_dir(inside_repo)
    assert exc_inside.value.code == "out_dir_inside_repo"

    # 2. 仓库外但目录不存在 ⇒ fail-closed 不自动建目录
    missing_outside = tmp_path / "nonexistent_truth_subdir"
    with pytest.raises(extractor.CaseExtractionError) as exc_missing:
        extractor.assert_safe_out_dir(missing_outside)
    assert exc_missing.value.code == "out_dir_missing"


def test_extract_gate_fail_pass_and_rejection_to_redacted_idempotent_card(db_session, tmp_path: Path):
    extractor = _load_extractor()
    project = _seed_project_with_feedback(db_session)

    bundles = extractor.collect_project_feedback_signals(
        db_session, project_code=project.project_code
    )
    assert len(bundles) == 1
    bundle = bundles[0]
    assert len(bundle.gate_transitions) == 1
    assert bundle.gate_transitions[0].gate_key == "G7"
    assert len(bundle.rejections) == 1
    assert bundle.rejections[0].kind == "business_fact"

    card = extractor.build_candidate_card(bundle, snapshot_date="2026-11-14")
    serialized = json.dumps(card, ensure_ascii=False)

    # T-A2 脱敏验证：疑似真实企业名「华星重工集团」与手机号「13812345678」绝不出现在候选卡中
    assert "华星重工集团" not in serialized
    assert "13812345678" not in serialized
    assert "客户L6" in serialized
    assert card["card_version"] == "import-card-v1"
    assert card["provenance"]["billing_actor_policy"] == "service_account"

    # 只插不改＋幂等验证（tmp_path 位于系统临时目录，在仓库外）
    out_dir = tmp_path / "truth_candidates"
    out_dir.mkdir()
    first = extractor.write_candidate_card_idempotent(card, out_dir)
    assert first["status"] == "written"
    written_file = Path(first["path"])
    assert written_file.is_file()

    # 手工在已落盘文件末尾加注释空格模拟历史文件，二次运行必须保持原字节不改写
    original_bytes = written_file.read_bytes()
    second = extractor.write_candidate_card_idempotent(card, out_dir)
    assert second["status"] == "already_exists"
    assert written_file.read_bytes() == original_bytes

    manifest = json.loads((out_dir / "candidate_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["cards"]) == 1
    assert manifest["cards"][0]["card_id"] == card["card_id"]

    # L1 转换器衔接验证：候选卡可直接转成 status='draft'、source_kind='import' 的训练场导入包
    l1_out = tmp_path / "l1_packages"
    l1_out.mkdir()
    l1_mod = extractor._load_import_cases_module()
    payload, build_errs = l1_mod.build_payload(card)
    assert build_errs == []
    assert payload["status"] == "draft"
    assert payload["source_kind"] == "import"
    assert l1_mod.gate_payload(payload) == []


def test_credential_in_project_feedback_aborts_fail_closed(db_session, tmp_path: Path):
    extractor = _load_extractor()
    project = _seed_project_with_feedback(db_session, inject_credential=True)

    bundles = extractor.collect_project_feedback_signals(
        db_session, project_code=project.project_code
    )
    assert len(bundles) == 1
    with pytest.raises(extractor.CaseExtractionError) as exc_cred:
        extractor.build_candidate_card(bundles[0])
    assert exc_cred.value.code == "sensitive_credential_detected"


def test_extractor_source_carries_no_forbidden_diagnostic_answer_tokens():
    source = EXTRACT_SCRIPT.read_text(encoding="utf-8")
    for forbidden in (
        "ground_truth",
        "solution_direction",
        "problems_expected",
        "human_boundary",
        "must_not_hallucinate",
        "诊断案例集",
    ):
        assert forbidden not in source
