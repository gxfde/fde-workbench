"""学习闭环 2.0 L6——宿主侧只读真实交付反哺抽取脚本。

依据 ``docs/architecture/AI原生化学习闭环2.0-设计稿-v1.md`` §2.6 / §4-L6 与
``docs/goal-l2.0-AI原生化学习闭环2.0-任务书.md`` L6 条款：

- **宿主通道五边界先例裁定**：沿 ``scripts/lead_ledger_append.py`` 先例
  （Windows 宿主侧人工显式发起＋数据库只读查询＋真相层只插不改＋幂等＋
  缺登记目录 fail-closed），服务端容器绝不直连宿主 CLI；
- **反哺信号双源**：
  1. 门禁 ``fail -> pass / conditional_pass`` 迁移（``operation_events``
     中同一门禁先被拍 ``fail`` 后重交过门的真实驳回修正链）；
  2. 交付产物/事实/需求/审核节点拒收（``business_facts.review_status='rejected'``、
     ``requirements.status='rejected'``、``agent_artifacts.revoked_by_user_id IS NOT NULL``、
     ``solution_review_checkpoints.status='rejected'``）；
- **脱敏与隔离红线**：
  - 全部自由文本字段强制经 T-A2 ``redact_text_detailed``（企业名→代号、
    PII 掩码；词典故障或凭据串命中即 fail-closed 中止，零落盘）；
  - 输出目录必须在仓库目录之外且预先存在（落本仓内或目录不存在均 fail-closed）；
  - 写出前强制过 L1 ``import_cases.build_payload`` ＋ ``gate_payload``
    （卡 schema 允许名单 + ``validate_scenario`` 八规则 + ``load_view``
    三视图泄漏自检）；
  - 只插不改、确定性 ``card_id`` 幂等（同名候选卡已存在则跳过不覆盖）；
  - 复用 L1 管线草稿态约定（后续人工跑 ``import_cases.py`` 写死
    ``source_kind='import'`` / ``status='draft'``，桌面核对后人工启用）。

**预算记账主体说明**（设计稿 §4-L6 / §5）：
本脚本纯确定性 SQL 只读抽取与本地规则装配，**零 AI 调用、零 token 消耗**；
候选卡经人工导入训练场后，后续模拟域 workbench 单跑/跑批与异步回归的 AI
调用统一以发起该运行/回归的平台服务账号（或操作员账号）入 ``ai_call_audits``
与月度预算门记账，不伪造匿名主体。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_SRC = REPO_ROOT / "server" / "src"
if str(SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(SERVER_SRC))

from sqlalchemy import select, text as sa_text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from fde_api.agents.models import AgentArtifact, AgentRun, SolutionReviewCheckpoint  # noqa: E402
from fde_api.discovery.models import BusinessFact, Requirement  # noqa: E402
from fde_api.guidance.enterprise_dict import RedactionConfigError  # noqa: E402
from fde_api.guidance.redaction import SensitiveCredentialDetected, redact_text_detailed  # noqa: E402
from fde_api.solutions.models import ProjectSolution  # noqa: E402
from fde_api.workbench.models import Gate, OperationEvent, Project  # noqa: E402

CARD_VERSION = "import-card-v1"
MANIFEST_FILENAME = "candidate_manifest.json"


class CaseExtractionError(RuntimeError):
    """抽取/脱敏/闸门任一环节未过即 fail-closed 抛错，零落盘。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.detail = message


@dataclass(frozen=True)
class GateFailPassSignal:
    gate_key: str
    fail_event_id: str
    pass_event_id: str
    fail_note: str
    pass_note: str
    accepted_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeliverableRejectionSignal:
    kind: str  # business_fact | requirement | agent_artifact | review_checkpoint
    source_id: str
    summary: str
    reason: str


@dataclass
class ProjectFeedbackBundle:
    project_id: str
    project_code: str
    enterprise_code: str
    industry: str
    background: str
    gate_transitions: list[GateFailPassSignal] = field(default_factory=list)
    rejections: list[DeliverableRejectionSignal] = field(default_factory=list)
    accepted_facts: list[tuple[str, str, str]] = field(default_factory=list)
    accepted_requirements: list[tuple[str, str, list[str]]] = field(default_factory=list)

    @property
    def has_signals(self) -> bool:
        return bool(self.gate_transitions or self.rejections)


def _load_import_cases_module() -> Any:
    script_path = REPO_ROOT / "scripts" / "simulation" / "import_cases.py"
    spec = importlib.util.spec_from_file_location("_l1_import_cases", script_path)
    if spec is None or spec.loader is None:
        raise CaseExtractionError("import_cases_unavailable", f"找不到 L1 转换器：{script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_safe_out_dir(out_dir: Path, *, repo_root: Path = REPO_ROOT) -> Path:
    """校验输出目录：①不得落入仓库内；②目录必须预先存在（缺登记面 fail-closed）。"""
    resolved_out = out_dir.resolve()
    resolved_repo = repo_root.resolve()
    if resolved_out == resolved_repo or resolved_repo in resolved_out.parents:
        raise CaseExtractionError(
            "out_dir_inside_repo",
            f"候选卡含判卷基准，禁止写入仓库目录内：{resolved_out}",
        )
    if not resolved_out.exists() or not resolved_out.is_dir():
        raise CaseExtractionError(
            "out_dir_missing",
            f"目标真相层目录不存在（fail-closed 不自动建目录）：{resolved_out}",
        )
    return resolved_out


def _parse_industry(enterprise_code: str) -> str:
    parts = [seg.strip() for seg in (enterprise_code or "").split("·") if seg.strip()]
    if len(parts) >= 2:
        return parts[1]
    return "general"


def _redact(value: str, *, enterprise_code: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    try:
        return redact_text_detailed(
            cleaned,
            project_code=enterprise_code,
            mask_pii=True,
        ).text
    except SensitiveCredentialDetected as exc:
        raise CaseExtractionError("sensitive_credential_detected", str(exc)) from exc
    except RedactionConfigError as exc:
        raise CaseExtractionError("pseudonym_dict_unavailable", str(exc)) from exc


def collect_project_feedback_signals(
    session: Session,
    *,
    project_id: str | None = None,
    project_code: str | None = None,
) -> list[ProjectFeedbackBundle]:
    """只读扫描指定项目（或全库项目）的门禁 fail→pass 与产物拒收信号。"""
    stmt = select(Project).order_by(Project.created_at.asc(), Project.id.asc())
    if project_id:
        stmt = stmt.where(Project.id == project_id)
    if project_code:
        stmt = stmt.where(Project.project_code == project_code)
    projects = list(session.scalars(stmt))
    if (project_id or project_code) and not projects:
        raise CaseExtractionError(
            "project_not_found",
            f"未找到目标项目（project_id={project_id!r}, project_code={project_code!r}）",
        )

    bundles: list[ProjectFeedbackBundle] = []
    for project in projects:
        bundle = ProjectFeedbackBundle(
            project_id=project.id,
            project_code=project.project_code,
            enterprise_code=project.enterprise_code,
            industry=_parse_industry(project.enterprise_code),
            background=project.background or "",
        )

        # 1. 门禁 fail -> pass / conditional_pass 迁移链
        # 排序三键：created_at 打平（如同秒/同事务批量代录）时由 occurred_at
        # 破平局；生产双拍板为独立事务、occurred_at 微秒可分——id（UUID，
        # 字典序随机）只作最后兜底，禁止在打平时被实际消费。
        gate_events = list(
            session.scalars(
                select(OperationEvent)
                .where(
                    OperationEvent.project_id == project.id,
                    OperationEvent.event_type == "gate_decided",
                )
                .order_by(
                    OperationEvent.created_at.asc(),
                    OperationEvent.occurred_at.asc(),
                    OperationEvent.id.asc(),
                )
            )
        )
        gates_by_key: dict[str, Gate] = {
            g.gate_key: g
            for g in session.scalars(select(Gate).where(Gate.project_id == project.id))
        }
        last_fail_by_gate: dict[str, OperationEvent] = {}
        for ev in gate_events:
            changes = ev.changes if isinstance(ev.changes, dict) else {}
            gate_key = str(changes.get("gate_key") or "").strip()
            result = str(changes.get("result") or "").strip()
            if not gate_key:
                continue
            if result == "fail":
                last_fail_by_gate[gate_key] = ev
            elif result in ("pass", "conditional_pass") and gate_key in last_fail_by_gate:
                fail_ev = last_fail_by_gate.pop(gate_key)
                fail_changes = fail_ev.changes if isinstance(fail_ev.changes, dict) else {}
                gate_row = gates_by_key.get(gate_key)
                checklist_labels: list[str] = []
                if gate_row and isinstance(gate_row.evidence_checklist, list):
                    checklist_labels = [
                        str(item.get("label") or "").strip()
                        for item in gate_row.evidence_checklist
                        if isinstance(item, dict) and str(item.get("label") or "").strip()
                    ]
                bundle.gate_transitions.append(
                    GateFailPassSignal(
                        gate_key=gate_key,
                        fail_event_id=fail_ev.id,
                        pass_event_id=ev.id,
                        fail_note=str(
                            fail_changes.get("note")
                            or fail_changes.get("fail_exit")
                            or f"{gate_key} 首次核验未通过"
                        ),
                        pass_note=str(changes.get("note") or f"{gate_key} 补齐证据后核验通过"),
                        accepted_labels=tuple(checklist_labels),
                    )
                )

        # 2A. 被拒收的业务事实
        for fact in session.scalars(
            select(BusinessFact)
            .where(
                BusinessFact.project_id == project.id,
                BusinessFact.review_status == "rejected",
            )
            .order_by(BusinessFact.created_at.asc(), BusinessFact.id.asc())
        ):
            bundle.rejections.append(
                DeliverableRejectionSignal(
                    kind="business_fact",
                    source_id=fact.id,
                    summary=f"{fact.subject} · {fact.predicate}",
                    reason=str(fact.review_comment or "事实缺乏客户原文锚点被审阅人驳回"),
                )
            )

        # 2B. 被拒收的需求条目
        for req in session.scalars(
            select(Requirement)
            .where(
                Requirement.project_id == project.id,
                Requirement.status == "rejected",
            )
            .order_by(Requirement.created_at.asc(), Requirement.id.asc())
        ):
            bundle.rejections.append(
                DeliverableRejectionSignal(
                    kind="requirement",
                    source_id=req.id,
                    summary=f"{req.requirement_key} {req.title}",
                    reason=str(req.review_comment or "需求未获客户确认或越出本期边界被驳回"),
                )
            )

        # 2C. 被撤回的智能体交付产物（revoked_by_user_id IS NOT NULL）
        for artifact in session.scalars(
            select(AgentArtifact)
            .join(AgentRun, AgentArtifact.run_id == AgentRun.id)
            .where(
                AgentRun.project_id == project.id,
                AgentArtifact.revoked_by_user_id.is_not(None),
            )
            .order_by(AgentArtifact.created_at.asc(), AgentArtifact.id.asc())
        ):
            bundle.rejections.append(
                DeliverableRejectionSignal(
                    kind="agent_artifact",
                    source_id=artifact.id,
                    summary=f"智能体产物 {artifact.kind}（sha256:{artifact.sha256[:12]}）",
                    reason="人工复核撤回（产物未满足交付门禁核验口径）",
                )
            )

        # 2D. 被驳回的方案审核节点
        for cp in session.scalars(
            select(SolutionReviewCheckpoint)
            .join(ProjectSolution, SolutionReviewCheckpoint.solution_id == ProjectSolution.id)
            .where(
                ProjectSolution.project_id == project.id,
                SolutionReviewCheckpoint.status == "rejected",
            )
            .order_by(SolutionReviewCheckpoint.created_at.asc(), SolutionReviewCheckpoint.id.asc())
        ):
            bundle.rejections.append(
                DeliverableRejectionSignal(
                    kind="review_checkpoint",
                    source_id=cp.id,
                    summary=f"方案审核关口 {cp.checkpoint_type}",
                    reason="方案审核节点人工拍板驳回",
                )
            )

        if not bundle.has_signals:
            continue

        # 3. 读取已接受事实与需求作为场景骨架（只读代号化结构）
        for fact in session.scalars(
            select(BusinessFact)
            .where(
                BusinessFact.project_id == project.id,
                BusinessFact.review_status == "accepted",
            )
            .order_by(BusinessFact.created_at.asc(), BusinessFact.id.asc())
            .limit(12)
        ):
            obj_text = (
                json.dumps(fact.object_value, ensure_ascii=False)
                if not isinstance(fact.object_value, str)
                else fact.object_value
            )
            bundle.accepted_facts.append((fact.fact_type, f"{fact.subject}{fact.predicate}：{obj_text}", fact.id))

        for req in session.scalars(
            select(Requirement)
            .where(
                Requirement.project_id == project.id,
                Requirement.status == "accepted",
            )
            .order_by(Requirement.created_at.asc(), Requirement.id.asc())
            .limit(8)
        ):
            criteria = [str(c) for c in (req.acceptance_criteria or []) if str(c).strip()]
            bundle.accepted_requirements.append((req.requirement_key, req.title, criteria))

        bundles.append(bundle)

    return bundles


def _clean_code_token(project_code: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "-", (project_code or "PRJ").upper()).strip("-")
    return (token[:16] or "PRJ").rstrip("-")


def build_candidate_card(
    bundle: ProjectFeedbackBundle,
    *,
    snapshot_date: str | None = None,
) -> dict[str, Any]:
    """将单个项目的反哺信号包脱敏装配为 ``import_card_v1`` 候选卡并过生产四重闸。"""
    if not bundle.has_signals:
        raise CaseExtractionError("no_feedback_signals", f"项目 {bundle.project_code} 无门禁驳回或产物拒收信号")

    enterprise_code = bundle.enterprise_code
    snap = snapshot_date or date.today().isoformat()

    signal_tokens = sorted(
        [f"gate:{s.gate_key}:{s.fail_event_id}->{s.pass_event_id}" for s in bundle.gate_transitions]
        + [f"rej:{r.kind}:{r.source_id}" for r in bundle.rejections]
    )
    signal_digest = hashlib.sha256("|".join(signal_tokens).encode("utf-8")).hexdigest()
    card_id = f"IMP-PRJ-{_clean_code_token(bundle.project_code)}-{signal_digest[:6].upper()}"

    alias_label = _redact(enterprise_code.split("·")[0] if enterprise_code else "目标客户", enterprise_code=enterprise_code) or "客户代号"
    industry_clean = _redact(bundle.industry, enterprise_code=enterprise_code) or "general"
    bg_clean = _redact(bundle.background, enterprise_code=enterprise_code)

    initial_brief: list[str] = [
        bg_clean or f"{alias_label}（{industry_clean}）推进数字化交付项目，需完成调研、方案与门禁核验。"
    ]
    known_systems: list[str] = []
    hidden_facts: list[dict[str, Any]] = []
    must_identify: list[str] = []
    must_avoid: list[str] = []
    must_produce: list[str] = []

    for f_type, f_text, _fid in bundle.accepted_facts:
        redacted_fact = _redact(f_text, enterprise_code=enterprise_code)
        if not redacted_fact:
            continue
        if f_type == "system" and len(known_systems) < 5:
            known_systems.append(redacted_fact[:120])
        elif len(hidden_facts) < 6:
            hf_id = f"HF-FACT-{len(hidden_facts) + 1:02d}"
            hidden_facts.append(
                {
                    "fact_id": hf_id,
                    "text": redacted_fact[:240],
                    "disclosure_stage": "interview",
                    "probe_keywords": ["现状", "流程", "系统", "边界"],
                }
            )
            must_identify.append(f"识别关键业务事实：{redacted_fact[:120]}")

    for idx, gate_sig in enumerate(bundle.gate_transitions, start=1):
        fail_note = _redact(gate_sig.fail_note, enterprise_code=enterprise_code)
        pass_note = _redact(gate_sig.pass_note, enterprise_code=enterprise_code)
        hf_id = f"HF-GATE-{idx:02d}"
        hidden_facts.append(
            {
                "fact_id": hf_id,
                "text": f"门禁 {gate_sig.gate_key} 核验易漏项：{fail_note}；合规过门条件：{pass_note}"[:240],
                "disclosure_stage": "analysis",
                "probe_keywords": [gate_sig.gate_key, "门禁", "证据", "验收"],
            }
        )
        must_identify.append(f"在 {gate_sig.gate_key} 提交前核清过门条件：{pass_note[:120]}")
        must_avoid.append(f"避免复现 {gate_sig.gate_key} 曾被驳回缺陷：{fail_note[:120]}")
        for label in gate_sig.accepted_labels[:3]:
            clean_label = _redact(label, enterprise_code=enterprise_code)
            if clean_label:
                must_produce.append(f"{gate_sig.gate_key} 核验清单项：{clean_label[:100]}")

    for idx, rej in enumerate(bundle.rejections, start=1):
        rej_summary = _redact(rej.summary, enterprise_code=enterprise_code)
        rej_reason = _redact(rej.reason, enterprise_code=enterprise_code)
        hf_id = f"HF-REJ-{idx:02d}"
        hidden_facts.append(
            {
                "fact_id": hf_id,
                "text": f"交付物审阅高风险拒收点（{rej.kind}）：{rej_summary}——拒收原因：{rej_reason}"[:240],
                "disclosure_stage": "design",
                "probe_keywords": ["验收", "范围", "依据", "边界"],
            }
        )
        must_avoid.append(f"禁止提交缺乏依据的条目（{rej_summary[:60]}）：{rej_reason[:100]}")

    acceptance_criteria: list[str] = []
    for req_key, req_title, req_criteria in bundle.accepted_requirements:
        clean_title = _redact(f"{req_key} {req_title}", enterprise_code=enterprise_code)
        if clean_title:
            must_produce.append(f"覆盖已批准需求：{clean_title[:120]}")
        for crit in req_criteria[:2]:
            clean_crit = _redact(crit, enterprise_code=enterprise_code)
            if clean_crit:
                acceptance_criteria.append(clean_crit[:200])

    if not must_identify:
        must_identify.append("通过结构化追问核清真实交付约束与验收口径，不依赖未经证实的假设。")
    if not must_produce:
        must_produce.append("产出带客户原文证据锚点的需求分析、交付方案与门禁核验清单。")
    if not acceptance_criteria:
        acceptance_criteria.append("全部隐藏风险点在访谈/分析阶段被识别，且方案不触发历史驳回缺陷。")

    first_trap = must_avoid[0] if must_avoid else "直接按表面诉求给出一刀切方案，跳过边界核验"
    misleading_request = (
        f"客户希望尽快跳过前置核验直接定稿上线（历史易错诱导：{first_trap[:100]}）。"
    )

    card: dict[str, Any] = {
        "card_id": card_id,
        "card_version": CARD_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "attribution": {
            "source_type": "internal_project_feedback_redacted",
            "source_pointer": f"project:{bundle.project_code}#signals:{signal_digest[:12]}",
            "license": "Proprietary-Internal-Pseudonymized",
            "snapshot_date": snap,
            "rewritten": True,
            "rewrite_declaration": (
                "由本仓宿主侧只读脚本 scripts/extract_case_from_project.py 自代号化交付项目"
                "门禁 fail→pass 与审阅拒收记录确定性脱敏合成，零第三方材料、零客户实名与原件。"
            ),
        },
        "scenario": {
            "name": f"{alias_label}·真实交付反哺场景（{bundle.project_code}）"[:120],
            "industry": industry_clean[:60],
            "tags": ["l6-feedback", "real-rejection", industry_clean[:24]],
            "difficulty": "standard",
            "split": "train",
            "rubric_version": "rubric-v1",
            "note": f"L6 反哺候选卡（门禁迁移 {len(bundle.gate_transitions)} 处 / 拒收 {len(bundle.rejections)} 处），待人工审阅激活。",
        },
        "content": {
            "case_code": card_id,
            "customer_profile": {
                "alias": alias_label,
                "industry": industry_clean,
                "persona": "注重交付证据链与边界落地的业务负责人",
            },
            "visible": {
                "initial_brief": initial_brief,
                "known_systems": known_systems,
                "constraints": {
                    "evidence_discipline": "门禁与需求条目必须具备可核验出处，禁止无源断言",
                },
            },
            "hidden": {
                "facts": hidden_facts,
            },
            "misleading_request": misleading_request,
        },
        "reference": {
            "expected_outcomes": must_produce[:6],
            "acceptance_criteria": acceptance_criteria[:8],
            "rubric": {
                "must_identify": must_identify[:8],
                "must_avoid": must_avoid[:8],
                "must_produce": must_produce[:8],
            },
        },
        "provenance": {
            "extractor": "scripts/extract_case_from_project.py",
            "project_code": bundle.project_code,
            "signal_fingerprint": signal_digest,
            "gate_transition_count": len(bundle.gate_transitions),
            "rejection_count": len(bundle.rejections),
            "billing_actor_policy": "service_account",
        },
    }

    # 生产四重闸自检（卡允许名单 + validate_scenario 八规则 + load_view 三视图泄漏自检）
    import_cases = _load_import_cases_module()
    payload, card_errors = import_cases.build_payload(card)
    if card_errors:
        raise CaseExtractionError("card_schema_failed", ",".join(card_errors))
    gate_errors = import_cases.gate_payload(payload)
    if gate_errors:
        raise CaseExtractionError("scenario_gate_failed", ";".join(gate_errors))

    return card


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def write_candidate_card_idempotent(
    card: dict[str, Any],
    out_dir: Path,
    *,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """只插不改＋原子写落盘真相层候选卡并追加登记 ``candidate_manifest.json``。"""
    safe_dir = assert_safe_out_dir(out_dir, repo_root=repo_root)

    import_cases = _load_import_cases_module()
    payload, card_errors = import_cases.build_payload(card)
    if card_errors:
        raise CaseExtractionError("card_schema_failed", ",".join(card_errors))
    gate_errors = import_cases.gate_payload(payload)
    if gate_errors:
        raise CaseExtractionError("scenario_gate_failed", ";".join(gate_errors))

    card_id = str(card["card_id"])
    target_path = safe_dir / f"{card_id}.json"
    if target_path.exists():
        existing_sha = _sha256_bytes(target_path.read_bytes())
        return {
            "card_id": card_id,
            "status": "already_exists",
            "path": str(target_path),
            "sha256": existing_sha,
        }

    encoded = (json.dumps(card, ensure_ascii=False, indent=2, sort_keys=False) + "\n").encode("utf-8")
    digest = _sha256_bytes(encoded)
    _atomic_write_bytes(target_path, encoded)

    manifest_path = safe_dir / MANIFEST_FILENAME
    manifest_entries: list[dict[str, Any]] = []
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("cards"), list):
                manifest_entries = list(loaded["cards"])
        except ValueError as exc:
            raise CaseExtractionError("manifest_corrupted", f"候选清单 JSON 损坏：{manifest_path}") from exc

    if not any(isinstance(item, dict) and item.get("card_id") == card_id for item in manifest_entries):
        manifest_entries.append(
            {
                "card_id": card_id,
                "file": target_path.name,
                "sha256": digest,
                "project_code": card.get("provenance", {}).get("project_code", ""),
                "recorded_at": datetime.now(UTC).isoformat(),
            }
        )
        manifest_doc = {
            "schema": "l6-candidate-manifest-v1",
            "note": "真相层候选卡登记簿（只插不改；激活须人工跑 import_cases.py 并经桌面启用）",
            "cards": manifest_entries,
        }
        _atomic_write_bytes(
            manifest_path,
            (json.dumps(manifest_doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )

    return {
        "card_id": card_id,
        "status": "written",
        "path": str(target_path),
        "sha256": digest,
    }


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="L6 宿主侧只读抽取真实交付门禁驳回/产物拒收信号为真相层 import_card_v1 候选卡。",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--project-code", help="按项目代号（如 PRJ-...）精确抽取")
    target.add_argument("--project-id", help="按项目 UUID 精确抽取")
    target.add_argument("--all-projects", action="store_true", help="扫描全库所有含驳回/拒收信号的项目")
    parser.add_argument(
        "--out-dir",
        required=True,
        type=Path,
        help="真相层候选卡输出目录（必须位于仓库外且预先存在）",
    )
    parser.add_argument("--dry-run", action="store_true", help="仅只读抽取与闸门自检，不写磁盘")
    args = parser.parse_args(argv)

    if not args.dry_run:
        assert_safe_out_dir(args.out_dir)

    from fde_api.app import create_app
    from fde_api.extensions import db

    app = create_app()
    results: list[dict[str, Any]] = []
    with app.app_context():
        session = db.session()
        try:
            session.execute(sa_text("SET TRANSACTION READ ONLY"))
            bundles = collect_project_feedback_signals(
                session,
                project_id=args.project_id,
                project_code=args.project_code,
            )
            for bundle in bundles:
                card = build_candidate_card(bundle)
                if args.dry_run:
                    results.append(
                        {
                            "card_id": card["card_id"],
                            "project_code": bundle.project_code,
                            "status": "dry_run_ok",
                        }
                    )
                else:
                    receipt = write_candidate_card_idempotent(card, args.out_dir)
                    results.append(receipt)
            session.rollback()
        finally:
            session.close()

    print(json.dumps({"count": len(results), "items": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run_cli())
    except CaseExtractionError as exc:
        print(json.dumps({"error": exc.code, "message": exc.detail}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc
