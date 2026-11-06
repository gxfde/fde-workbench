"""gate_service：P3 门禁引擎（设计 §5，Gate 状态机驱动）。

口径铁律（照搬 SOP v2.4.6 + 映射表 v1.3；工程层不得发明方法论层没有的东西）：
- 状态机：pending →(提交证据) evidence →(人工核验) passed | conditional_pass | failed。
  conditional_pass 仅 G9（SOP 原文「有条件通过」）；G8 passed 必带 decision ∈
  {proceed, pivot, stop}（三者都算过门，stop 的结算由 P4 Payment 承接）；
  v0.2 已删无出处的 waived，此处不存在。
- claimed ≠ accepted（SOP 铁律，设计 §5.3）：清单每项 claim_status，
  提交出处 = claimed（UI 黄标），人工核验接受 = accepted。
  pass 要求全部项 accepted，conditional_pass 要求全部项至少 claimed——门禁不能是
  「点鼠标过场」。
- 证据只存出处指针（A4）：项级 source_uri + content_hash，内容本体在
  fdeops .fde/ 或 openfde assets/。
- failed 允许重新提交证据（G4 fail_exit「可随时重启」有出处）；
  passed / conditional_pass 为终态（SOP 无「撤销过门」语义）。
- 失败出口可触发（§5 验收）：decide fail 的响应与事件均带模板 fail_exit 原文，
  出口动作本身在 SOP 里由人执行，引擎只负责显式呈现与留痕。
- 模板：seeds/gates.json（烘进镜像）按项目幂等实例化 9 行（首次访问时懒初始化，
  兼容 P1/P2 期已激活的存量项目）；evidence_checklist 即模板快照（P1 口径，
  模板定义不另建 DB 表）。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access
from fde_api.workbench.models import Gate, OperationEvent, Project, ProjectMember, SopNode

GATE_STATUSES = ("pending", "evidence", "passed", "conditional_pass", "failed")
GATE_RESULTS = ("pass", "conditional_pass", "fail")
G8_DECISIONS = ("proceed", "pivot", "stop")
# 模板 checklist 项的合法 claim_status；null = 未提交（§5.3：accepted 之外一律黄标）
CLAIM_STATUSES = ("claimed", "accepted")

_GATE_KEY_PATTERN = re.compile(r"G[1-9]")
_HEX64_PATTERN = re.compile(r"[0-9a-fA-F]{64}")

_SEEDS_DIR = Path(__file__).resolve().parents[3] / "seeds"


class GateServiceError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@lru_cache(maxsize=1)
def _gate_templates() -> tuple[dict[str, Any], ...]:
    """读取 gates.json 模板（镜像内只读，进程级缓存足够）。"""
    path = _SEEDS_DIR / "gates.json"
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as error:
        raise RuntimeError("gates.json template unavailable") from error
    rows = payload.get("gates") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("gates.json template empty")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("gate_key"), str):
            raise RuntimeError("gates.json template row invalid")
    return tuple(rows)


def _template_index() -> dict[str, dict[str, Any]]:
    return {row["gate_key"]: row for row in _gate_templates()}


@lru_cache(maxsize=1)
def _gates_file_hash() -> str:
    """gates.json 文件级 sha256（Gate 行实例化时冻结，审计清单版本漂移）。"""
    import hashlib

    return hashlib.sha256((_SEEDS_DIR / "gates.json").read_bytes()).hexdigest()


def ensure_project_gates(session: Session, project: Project) -> int:
    """按模板幂等实例化 9 行 Gate（已存在则不动），返回新建行数。

    先锁项目行再计数：两个并发首访不会双份 9 行（撞唯一约束 500）。
    """
    session.execute(
        select(Project.id).where(Project.id == project.id).with_for_update()
    )
    existing = session.scalar(
        select(func.count()).select_from(Gate).where(Gate.project_id == project.id)
    )
    if existing:
        return 0
    for template in _gate_templates():
        session.add(
            Gate(
                project_id=project.id,
                gate_key=template["gate_key"],
                status="pending",
                evidence_checklist=[
                    {
                        "label": label,
                        "claim_status": None,
                        "source_uri": None,
                        "content_hash": None,
                    }
                    for label in template.get("evidence_checklist") or []
                ],
                signer_role=template.get("signer_role"),
                template_hash=_gates_file_hash(),
            )
        )
    return len(_gate_templates())


def _ensure_gates_logged(session: Session, actor: User, project: Project) -> None:
    """懒初始化（docstring 承诺「首次访问」）：list/submit/decide 入口统一走这里。"""
    created = ensure_project_gates(session, project)
    if created:
        record_event(
            session,
            actor,
            "gates_instantiated",
            project,
            {"gate_count": created, "source": "seeds/gates.json"},
        )


def list_project_gates(*, actor: User, project_id: str) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_gates(session, actor, project_id, manage=False)
            _ensure_gates_logged(session, actor, project)
            gates = list(
                session.scalars(select(Gate).where(Gate.project_id == project.id))
            )
            templates = _template_index()
            sop_nodes = _sop_nodes_for_templates(session, templates)
            order = {row["gate_key"]: index for index, row in enumerate(_gate_templates())}
            gates.sort(key=lambda gate: order.get(gate.gate_key, 99))
            items = [
                _serialize_gate(gate, templates.get(gate.gate_key), sop_nodes)
                for gate in gates
            ]
            events = _recent_gate_events(session, project.id)
        return {
            "project_id": project.id,
            "sop_phase": project.sop_phase,
            "gates": items,
            "events": events,
        }
    except GateServiceError:
        raise
    except RuntimeError as error:
        if str(error).startswith("gates.json"):
            raise GateServiceError(
                "gate_template_unavailable",
                "门禁模板不可用，请检查服务端 seeds/gates.json。",
                500,
            ) from None
        raise
    finally:
        session.close()


def summarize_project_gates(*, actor: User, project_id: str) -> dict[str, Any]:
    """AI 只读门禁摘要（gates_read 工具消费）：状态/拍板/清单 claim 进度 + 最近事件。

    刻意瘦身：不带模板长文、source_uri/content_hash——摘要只回答「到哪一步、
    还缺什么」；写路径（提交证据/人工拍板）刻意不对 AI 开放。
    """
    payload = list_project_gates(actor=actor, project_id=project_id)
    gates = []
    for gate in payload["gates"]:
        checklist = gate["checklist"]
        gates.append(
            {
                "gate_key": gate["gate_key"],
                "gate_name": gate["gate_name"],
                "node_key": gate["node_key"],
                "status": gate["status"],
                "decision": gate["decision"],
                "signer_role": gate["signer_role"],
                "submitted_at": gate["submitted_at"],
                "decided_at": gate["decided_at"],
                "checklist": [
                    {"label": item["label"], "claim_status": item["claim_status"]}
                    for item in checklist
                ],
                "accepted": sum(
                    1 for item in checklist if item["claim_status"] == "accepted"
                ),
                "total": len(checklist),
            }
        )
    return {
        "project_id": payload["project_id"],
        "sop_phase": payload["sop_phase"],
        "gates": gates,
        "recent_events": [
            {
                key: event[key]
                for key in ("event_type", "occurred_at", "actor_display_name")
            }
            for event in payload["events"][:5]
        ],
        "note": "门禁只读视图：提交证据与人工核验拍板需在桌面端项目详情页由人执行，AI 不代执行。",
    }


def submit_gate_evidence(
    *,
    actor: User,
    project_id: str,
    gate_key: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    items = _normalize_submission_items(payload)
    note = _optional_note(payload)
    # 延迟导入：evidence.service 依赖 projects.events/permissions，模块级互导会成
    # projects⇄evidence 环（沿 solutions.generate_agent_solution → agents 的先例）
    from fde_api.evidence.service import upsert_evidence

    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_gates(session, actor, project_id, manage=True)
            _ensure_gates_logged(session, actor, project)
            gate = _load_gate(session, project.id, gate_key)
            if gate.status in ("passed", "conditional_pass"):
                raise GateServiceError(
                    "gate_already_decided", "该门禁已过门，不能再提交证据。", 409
                )
            checklist = {
                item["label"]: dict(item) for item in gate.evidence_checklist
            }
            unknown = [item["label"] for item in items if item["label"] not in checklist]
            if unknown:
                raise GateServiceError(
                    "invalid_gate_evidence",
                    f"清单项不存在：{'、'.join(unknown)}。",
                    400,
                )
            for item in items:
                # V3 T-E2：证据先登记为一等实体（同指纹幂等，见 evidence/service.py），
                # 清单项只持 evidence_id；origin 记「门禁/清单项」出处粒度。旧行无
                # evidence_id，读时合并为 null（_serialize_gate），零迁移。
                evidence, _created = upsert_evidence(
                    session,
                    project_id=project.id,
                    kind="gate",
                    source_uri=item["source_uri"],
                    content_sha256=item["content_hash"],
                    origin=f"gate:{gate.gate_key}/{item['label']}",
                    captured_from="human",
                    created_by_user_id=actor.id,
                )
                item["evidence_id"] = evidence.id
                checklist[item["label"]].update(
                    claim_status="claimed",
                    source_uri=item["source_uri"],
                    content_hash=item["content_hash"],
                    evidence_id=evidence.id,
                )
            previous_status = gate.status
            gate.evidence_checklist = list(checklist.values())
            gate.status = "evidence"
            gate.submitted_at = datetime.now(timezone.utc)
            gate.evidence_uri = items[0]["source_uri"]
            gate.evidence_hash = items[0]["content_hash"]
            # V3 T-G1：采纳即闭环——提交指纹命中候选（uri 相等且 hash 忽略大小
            # 写相等）则剪除对应候选，面板不再重复提示；未命中的候选原样保留。
            submitted_uris = {item["source_uri"] for item in items}
            submitted_hashes = {item["content_hash"].lower() for item in items}
            candidates = [
                row
                for row in (gate.evidence_candidates or [])
                if not (
                    row.get("source_uri") in submitted_uris
                    and str(row.get("content_hash") or "").lower() in submitted_hashes
                )
            ]
            gate.evidence_candidates = candidates if candidates else None
            # P0-5 门禁验收分离（设计 §9.4）：提交人即执行人，落库供 decide_gate
            # 校验「拍板人 ≠ 执行人」。is_delivery_party 标记证据由交付方（外部
            # FDE，§9.3 接单后以 ProjectMember(role='member') 入场）执行；管理位
            # （admin/项目 leader）提交视为平台侧执行——派单池上线前恒 False。
            member = session.scalar(
                select(ProjectMember).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == actor.id,
                )
            )
            gate.is_delivery_party = member is not None and member.role == "member"
            gate.submitted_by_user_id = actor.id
            record_event(
                session,
                actor,
                "gate_evidence_submitted",
                gate,
                {
                    "gate_key": gate.gate_key,
                    "from_status": previous_status,
                    "to_status": gate.status,
                    "items": [
                        {
                            "label": item["label"],
                            "source_uri": item["source_uri"],
                            "content_hash": item["content_hash"],
                            "evidence_id": item["evidence_id"],
                        }
                        for item in items
                    ],
                    "note": note,
                },
            )
            session.flush()
            templates = _template_index()
            sop_nodes = _sop_nodes_for_templates(session, templates)
            return _serialize_gate(gate, templates.get(gate.gate_key), sop_nodes)
    except GateServiceError:
        raise
    except RuntimeError as error:
        if str(error).startswith("gates.json"):
            raise GateServiceError(
                "gate_template_unavailable",
                "门禁模板不可用，请检查服务端 seeds/gates.json。",
                500,
            ) from None
        raise
    finally:
        session.close()


def decide_gate(
    *,
    actor: User,
    project_id: str,
    gate_key: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    result = payload.get("result")
    if result not in GATE_RESULTS:
        raise GateServiceError(
            "invalid_request", "result 必须是 pass / conditional_pass / fail。", 400
        )
    decision = payload.get("decision")
    if decision is not None and decision not in G8_DECISIONS:
        raise GateServiceError(
            "invalid_request", "decision 必须是 proceed / pivot / stop。", 400
        )
    accepted_labels_raw = payload.get("accepted_labels")
    if accepted_labels_raw is not None and (
        not isinstance(accepted_labels_raw, list)
        or not all(isinstance(label, str) for label in accepted_labels_raw)
    ):
        raise GateServiceError(
            "invalid_request", "accepted_labels 必须是字符串数组。", 400
        )
    note = _optional_note(payload)
    # B#28 门禁 revision CAS（FF stage completeX 语义）：expected_revision 提供
    # 时必须与当前 version 相等，否则 409 且零变更——多端并发拍板后写不再覆盖
    # 前写。行锁（_load_gate with_for_update）+ 版本复核 = 原子 CAS；缺省时维持
    # 既有行为（旧客户端兼容），version 照常推进。
    expected_revision = payload.get("expected_revision")
    if expected_revision is not None and (
        isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
        or expected_revision < 1
    ):
        raise GateServiceError(
            "invalid_request", "expected_revision 必须是正整数。", 400
        )

    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_gates(session, actor, project_id, manage=True)
            _ensure_gates_logged(session, actor, project)
            gate = _load_gate(session, project.id, gate_key)
            if gate.status != "evidence":
                raise GateServiceError(
                    "invalid_gate_state", "该门禁尚无待核验证据，先提交证据再核验。", 409
                )
            # B#28 CAS 复核：版本已被推进（并发拍板先到者胜）→ 拒绝且零变更。
            if expected_revision is not None and gate.version != expected_revision:
                raise GateServiceError(
                    "gate_revision_conflict",
                    f"门禁状态已被推进（当前 revision={gate.version}），请刷新后重试；本次拍板未生效。",
                    409,
                )
            # P0-5 硬闸门（设计 §9.4，§8.8 开池四道闸之二）：拍板人 ≠ 该门禁执行人，
            # 代码强制、先于其余业务校验，不可绕过。
            if (
                gate.submitted_by_user_id is not None
                and gate.submitted_by_user_id == actor.id
            ):
                raise GateServiceError(
                    "gate_decider_conflict",
                    "门禁验收分离：拍板人不能是该门禁的证据执行人。",
                    403,
                )
            # 交付方执行的 G8/G9 须由平台侧（交付总监 = admin）拍板
            # （§9.4 方案②正解 + §11.3 方案①过渡口径）。
            if (
                gate.is_delivery_party
                and gate.gate_key in ("G8", "G9")
                and actor.role != "admin"
            ):
                raise GateServiceError(
                    "gate_decider_role_required",
                    "交付方执行的 G8/G9 须由平台侧（交付总监）拍板。",
                    403,
                )
            templates = _template_index()
            template = templates.get(gate.gate_key)
            if template is None:
                raise GateServiceError(
                    "gate_template_unavailable",
                    f"门禁 {gate.gate_key} 的模板定义缺失，请检查服务端 seeds/gates.json。",
                    500,
                )
            # conditional_pass 仅限 G9 的校验必须对 G8 同样生效（A1）：
            # 此前该检查关在非 G8 分支内，G8 + conditional_pass 可绕过
            # 试点毕业门的书面三态拍板控制。
            if result == "conditional_pass" and gate.gate_key != "G9":
                raise GateServiceError(
                    "gate_result_not_allowed",
                    "conditional_pass（有条件通过）仅限 G9 上线门。",
                    400,
                )
            if gate.gate_key == "G8":
                if result != "pass" and decision is not None:
                    raise GateServiceError(
                        "gate_decision_not_allowed",
                        "decision 只随 G8 过门（pass）提交。",
                        400,
                    )
                if result == "pass" and decision is None:
                    raise GateServiceError(
                        "gate_decision_required",
                        "G8 过门必须书面拍板：proceed / pivot / stop 三选一。",
                        400,
                    )
            else:
                if decision is not None:
                    raise GateServiceError(
                        "gate_decision_not_allowed",
                        "decision 三态拍板仅限 G8 试点毕业门。",
                        400,
                    )

            checklist = [dict(item) for item in gate.evidence_checklist]
            previous_status = gate.status
            changes: dict[str, Any] = {
                "gate_key": gate.gate_key,
                "from_status": previous_status,
                "result": result,
            }
            if result == "pass":
                # claimed ≠ accepted（SOP 铁律）：核验只能「接受已提交证据的项」，
                # 不许把从未提交的清单项直接追认 accepted 空证据过门。
                claimed = {
                    item["label"]
                    for item in checklist
                    if item["claim_status"] == "claimed"
                }
                accepted = (
                    set(accepted_labels_raw)
                    if accepted_labels_raw is not None
                    else claimed
                )
                not_claimed = sorted(accepted - claimed)
                if not_claimed:
                    raise GateServiceError(
                        "accepted_labels_not_claimed",
                        "accepted_labels 只能核验已提交证据的清单项："
                        f"{'、'.join(not_claimed)} 尚未提交。",
                        400,
                    )
                for item in checklist:
                    if item["label"] in accepted:
                        item["claim_status"] = "accepted"
                gate.evidence_checklist = checklist
                incomplete = [
                    item["label"]
                    for item in checklist
                    if item["claim_status"] != "accepted"
                ]
                if incomplete:
                    raise GateServiceError(
                        "gate_evidence_incomplete",
                        f"仍有清单项未接受核验，不能过门：{'、'.join(incomplete)}。",
                        400,
                    )
                gate.status = "passed"
                if decision is not None:
                    gate.decision = decision
                    changes["decision"] = decision
            elif result == "conditional_pass":
                unclaimed = [
                    item["label"]
                    for item in checklist
                    if item["claim_status"] not in CLAIM_STATUSES
                ]
                if unclaimed:
                    raise GateServiceError(
                        "gate_evidence_incomplete",
                        f"有条件通过也要求全部证据先提交：{'、'.join(unclaimed)}。",
                        400,
                    )
                gate.evidence_checklist = checklist
                gate.status = "conditional_pass"
            else:
                gate.evidence_checklist = checklist
                gate.status = "failed"
                changes["fail_exit"] = template.get("fail_exit") or ""
            gate.decided_at = datetime.now(timezone.utc)
            gate.decided_by_user_id = actor.id
            changes["decided_by_user_id"] = actor.id
            # B#28：拍板生效即推进 revision（VersionedMixin.version），留痕进
            # changes 供 operation_events 审计；lifecycle_version 不动（语法代际
            # 只随模板 grammar 换代推进，拍板不触碰）。
            gate.version += 1
            changes["revision"] = gate.version
            if note:
                changes["note"] = note
            # P4 承接（设计 §6）：G8 stop 也按合同结算（SOP §S8 三态）——
            # 联动给 G8 尾款收款行打 settlement_reason，B 尾款照收。
            settlement: dict[str, Any] | None = None
            if gate.gate_key == "G8" and result == "pass" and decision == "stop":
                from fde_api.projects.payment_service import flag_g8_stop_settlement

                settlement = flag_g8_stop_settlement(session, actor, project.id)
                changes["g8_stop_settlement"] = settlement
            # P0-4（派单设计 §7.2）：G8 过门 = 验收通过——联动打标
            # payments.acceptance_passed_at 并推进 delivery_settlements 计提
            # （draft → accrued 双条件之二；无交付包项目零感知）。
            acceptance: dict[str, Any] | None = None
            if gate.gate_key == "G8" and result == "pass":
                from fde_api.projects.payment_service import mark_acceptance_passed

                acceptance = mark_acceptance_passed(session, actor, project.id)
                changes["acceptance_marked"] = acceptance
            record_event(session, actor, "gate_decided", gate, changes)
            session.flush()
            sop_nodes = _sop_nodes_for_templates(session, templates)
            result_payload = _serialize_gate(gate, template, sop_nodes)
            if settlement is not None:
                result_payload["g8_stop_settlement"] = settlement
            if acceptance is not None:
                result_payload["acceptance_marked"] = acceptance
            return result_payload
    except GateServiceError:
        raise
    except RuntimeError as error:
        if str(error).startswith("gates.json"):
            raise GateServiceError(
                "gate_template_unavailable",
                "门禁模板不可用，请检查服务端 seeds/gates.json。",
                500,
            ) from None
        raise
    finally:
        session.close()


def _load_project_for_gates(
    session: Session, actor: User, project_id: str, *, manage: bool
) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise GateServiceError("project_not_found", "项目不存在或已被删除。", 404)
    access = project_access(actor, project)
    if not (access.can_manage if manage else access.can_view):
        raise GateServiceError("forbidden", "你没有该项目门禁的操作权限。", 403)
    return project


def _load_gate(session: Session, project_id: str, gate_key: str) -> Gate:
    if not isinstance(gate_key, str) or not _GATE_KEY_PATTERN.fullmatch(gate_key):
        raise GateServiceError("invalid_request", "门禁编号格式不正确。", 400)
    gate = session.scalar(
        select(Gate)
        .where(Gate.project_id == project_id, Gate.gate_key == gate_key)
        .with_for_update()
    )
    if gate is None:
        raise GateServiceError("gate_not_found", "该门禁不存在。", 404)
    return gate


def _sop_nodes_for_templates(
    session: Session, templates: Mapping[str, dict[str, Any]]
) -> dict[str, SopNode]:
    """只取模板引用到的节点（避免每次请求全表扫 SopNode）。"""
    node_keys = {
        template.get("node_key")
        for template in templates.values()
        if template.get("node_key")
    }
    if not node_keys:
        return {}
    return {
        node.node_key: node
        for node in session.scalars(
            select(SopNode).where(SopNode.node_key.in_(node_keys))
        )
    }


def _normalize_submission_items(
    payload: Mapping[str, Any]
) -> list[dict[str, str]]:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise GateServiceError(
            "invalid_request", "items 必须是非空数组（label + source_uri + content_hash）。", 400
        )
    normalized: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            raise GateServiceError("invalid_request", "items 元素必须是对象。", 400)
        label = item.get("label")
        source_uri = item.get("source_uri")
        content_hash = item.get("content_hash")
        if not isinstance(label, str) or not label.strip():
            raise GateServiceError("invalid_request", "label 不能为空。", 400)
        if not isinstance(source_uri, str) or not 0 < len(source_uri.strip()) <= 500:
            raise GateServiceError(
                "invalid_request", "source_uri 必须是 1–500 字符的出处指针。", 400
            )
        if not isinstance(content_hash, str) or not _HEX64_PATTERN.fullmatch(
            content_hash
        ):
            raise GateServiceError(
                "invalid_request", "content_hash 必须是 64 位十六进制 sha256。", 400
            )
        normalized.append(
            {
                "label": label.strip(),
                "source_uri": source_uri.strip(),
                "content_hash": content_hash.strip().lower(),
            }
        )
    return normalized


def _optional_note(payload: Mapping[str, Any]) -> str | None:
    note = payload.get("note")
    if note is None:
        return None
    if not isinstance(note, str) or not note.strip() or len(note) > 500:
        raise GateServiceError(
            "invalid_request", "note 必须是 1–500 字符的说明。", 400
        )
    return note.strip()


def _serialize_gate(
    gate: Gate,
    template: dict[str, Any] | None,
    sop_nodes: Mapping[str, SopNode],
) -> dict[str, Any]:
    node = sop_nodes.get(template.get("node_key")) if template else None
    return {
        "gate_key": gate.gate_key,
        "status": gate.status,
        "decision": gate.decision,
        "submitted_at": gate.submitted_at.isoformat() if gate.submitted_at else None,
        "decided_at": gate.decided_at.isoformat() if gate.decided_at else None,
        # P0-5 验收分离字段（设计 §9.4）：执行人/拍板人/是否交付方执行
        "submitted_by_user_id": gate.submitted_by_user_id,
        "decided_by_user_id": gate.decided_by_user_id,
        "is_delivery_party": gate.is_delivery_party,
        "evidence_uri": gate.evidence_uri,
        "evidence_hash": gate.evidence_hash,
        "checklist": [
            {
                "label": item.get("label"),
                "claim_status": item.get("claim_status"),
                "source_uri": item.get("source_uri"),
                "content_hash": item.get("content_hash"),
                # V3 T-E2：一等证据引用；T-E2 之前提交的清单项无此键 → null（读时合并）
                "evidence_id": item.get("evidence_id"),
            }
            for item in gate.evidence_checklist
        ],
        # V3 T-G1：任务产物候选（建议性）；旧行 NULL → []（读时合并，恒输出）
        # V3 T-W7：候选行 source_kind 读时缺省 "task"（workflow 行显式带键）；
        # 任务侧行（含历史行）不回填，沿 T-E2 evidence_id 读时合并先例。
        "evidence_candidates": [
            dict(row, source_kind="task")
            if isinstance(row, dict) and not row.get("source_kind")
            else row
            for row in (gate.evidence_candidates or [])
        ],
        # 模板快照（gates.json，A4 出处指针在模板 source_uri/source_sha256）
        "gate_name": template.get("gate_name") if template else None,
        "node_key": template.get("node_key") if template else None,
        "exit_condition": template.get("exit_condition") if template else None,
        "evidence_location": template.get("evidence_location") if template else None,
        "contract_payment": template.get("contract_payment") if template else None,
        "signer_role": template.get("signer_role") if template else gate.signer_role,
        "fail_exit": template.get("fail_exit") if template else None,
        "decision_semantics": template.get("decision_semantics") if template else None,
        "template_source_uri": template.get("source_uri") if template else None,
        "template_hash": gate.template_hash,
        # B#28 门禁 revision CAS 的「当前值」回传：桌面拍板时随 expected_revision
        # 带回，服务端据此做版本复核（并发拍板先到者胜）。≡ VersionedMixin.version
        # ——与 lifecycle_version（语法代际）刻意分离：后者不随拍板推进。
        "revision": gate.version,
        # V3 T-G2（WB-DEF-5）：冻结哈希 vs 现行 gates.json 比对呈现；NULL=未知出处不误报
        "template_outdated": bool(gate.template_hash)
        and gate.template_hash != _gates_file_hash(),
        "next_node_keys": node.next_node_keys if node else [],
    }


GATE_EVENT_TYPES = (
    "gates_instantiated",
    "gate_evidence_submitted",
    "gate_decided",
    # V3 T-G1：候选挂接事件（挂 gate 行目标），随事件留痕入 feed
    "gate_evidence_candidate_attached",
    # V3 T-W7：workflow 产物坏标记跳过事件（挂 project 目标——gate 非法时无行可挂）
    "gate_evidence_candidate_skipped",
)

# 候选上限：任务证据指纹去重后仍可能被反复改动刷出长尾，超过即丢最旧候选
# （建议性数据，最旧的参考价值最低）。
MAX_EVIDENCE_CANDIDATES = 20


def attach_task_evidence_candidate(
    session: Session,
    *,
    actor: User,
    project: Project,
    task_id: str,
    task_key: str,
    task_name: str,
    gate_key: str,
    source_uri: str,
    content_hash: str,
) -> bool:
    """V3 T-G1（WB-DEF-8）：任务产物→门禁证据候选（建议性，claim_status 不动）。

    任务完成且自带门禁挂点 + 证据指针+指纹时由 task_service 调用；候选只提示
    「这份产物可能可作为本门禁清单项证据」，领用永远经既有提交闸由人完成
    （submit_gate_evidence 命中指纹即剪除候选）。同 (uri, hash, task_key) 幂等
    不重复挂；门禁行尚未实例化时懒初始化（ensure_project_gates，幂等）。

    Returns: True = 新挂了一条候选；False = 去重跳过或门禁行不存在。
    """
    ensure_project_gates(session, project)
    gate = session.scalar(
        select(Gate).where(Gate.project_id == project.id, Gate.gate_key == gate_key)
    )
    if gate is None:
        return False
    fingerprint_hash = content_hash.lower()
    candidates = list(gate.evidence_candidates or [])
    for row in candidates:
        if (
            row.get("source_uri") == source_uri
            and str(row.get("content_hash") or "").lower() == fingerprint_hash
            and row.get("task_key") == task_key
        ):
            return False
    candidates.append(
        {
            "source_uri": source_uri,
            "content_hash": fingerprint_hash,
            "task_id": task_id,
            "task_key": task_key,
            "task_name": task_name,
            "proposed_by_user_id": actor.id,
            "proposed_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    if len(candidates) > MAX_EVIDENCE_CANDIDATES:
        candidates = candidates[-MAX_EVIDENCE_CANDIDATES:]
    gate.evidence_candidates = candidates
    record_event(
        session,
        actor,
        "gate_evidence_candidate_attached",
        gate,
        {
            "gate_key": gate.gate_key,
            "task_key": task_key,
            "task_name": task_name,
            "source_uri": source_uri,
            "content_hash": fingerprint_hash,
            "candidates_count": len(candidates),
        },
    )
    return True


# V3 T-W7 标记合同（workflow-gate-evidence-candidates-v1 §2）：source_uri 仅指针
# ≤1024、label 可选 ≤120（缺省用节点 key）、content_sha256 64 位 hex 归一小写。
_WF_MARKER_URI_MAX = 1024
_WF_MARKER_LABEL_MAX = 120


def attach_workflow_evidence_candidate(
    session: Session,
    *,
    actor: User,
    project: Project,
    run_id: str,
    node_key: str,
    gate_key: Any,
    source_uri: Any,
    content_hash: Any,
    label: Any = None,
) -> bool:
    """V3 T-W7（WB-DEF-8 workflow 腿）：workflow 节点产物→门禁证据候选。

    executor 在节点 succeeded 的同一事务内调用（事务回滚则节点成功与候选一并
    回滚）；标记是 output_json 顶层保留键 ``gate_evidence``，生产方（API 响应）
    自带指针+指纹——平台永不自动派生指纹，形状不齐=不是证据，跳过不发明。
    坏标记不炸节点：gate 非法 / sha 非 64hex / 超长 / 双字段缺一 → 节点照常
    succeeded，登记跳过 + ``gate_evidence_candidate_skipped`` 事件（details 点名
    坏键）。dedup = (source_uri, content_hash, wf:{run_id}:{node_key})：重试产出
    同指纹幂等跳过，换指纹新候选并存；上限沿 MAX_EVIDENCE_CANDIDATES 与任务候选
    共享同一列表与裁剪。claim_status 恒不动，采纳唯一入口 = submit_gate_evidence
    真人提交闸（命中指纹即剪除候选）。字段收 Any：坏形状由本校验裁决，绝不抛出。

    Returns: True = 新挂了一条候选；False = 坏标记跳过 / 幂等去重 / 门禁行不存在。
    """
    if not isinstance(gate_key, str) or not _GATE_KEY_PATTERN.fullmatch(gate_key):
        reason = "gate"
    elif not isinstance(source_uri, str) or not 0 < len(source_uri) <= _WF_MARKER_URI_MAX:
        reason = "source_uri"
    elif not isinstance(content_hash, str) or not _HEX64_PATTERN.fullmatch(content_hash):
        reason = "content_sha256"
    elif label is not None and (
        not isinstance(label, str) or len(label) > _WF_MARKER_LABEL_MAX
    ):
        reason = "label"
    else:
        reason = None
    if reason is not None:
        record_event(
            session,
            actor,
            "gate_evidence_candidate_skipped",
            project,
            {
                "gate_key": gate_key if isinstance(gate_key, str) else None,
                "workflow_run_id": run_id,
                "workflow_node_key": node_key,
                "reason": reason,
            },
        )
        return False
    ensure_project_gates(session, project)
    gate = session.scalar(
        select(Gate).where(Gate.project_id == project.id, Gate.gate_key == gate_key)
    )
    if gate is None:
        return False
    fingerprint_hash = content_hash.lower()
    candidates = list(gate.evidence_candidates or [])
    for row in candidates:
        if (
            row.get("source_uri") == source_uri
            and str(row.get("content_hash") or "").lower() == fingerprint_hash
            and row.get("source_kind") == "workflow"
            and row.get("workflow_run_id") == run_id
            and row.get("workflow_node_key") == node_key
        ):
            return False
    candidates.append(
        {
            "source_uri": source_uri,
            "content_hash": fingerprint_hash,
            "source_kind": "workflow",
            "workflow_run_id": run_id,
            "workflow_node_key": node_key,
            "label": label or node_key,
            "proposed_by_user_id": actor.id,
            "proposed_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    if len(candidates) > MAX_EVIDENCE_CANDIDATES:
        candidates = candidates[-MAX_EVIDENCE_CANDIDATES:]
    gate.evidence_candidates = candidates
    record_event(
        session,
        actor,
        "gate_evidence_candidate_attached",
        gate,
        {
            "gate_key": gate.gate_key,
            "workflow_run_id": run_id,
            "workflow_node_key": node_key,
            "label": label or node_key,
            "source_uri": source_uri,
            "content_hash": fingerprint_hash,
            "candidates_count": len(candidates),
        },
    )
    return True


def _recent_gate_events(session: Session, project_id: str) -> list[dict[str, Any]]:
    # gates_instantiated 挂在 project 目标上，其余三类挂在 gate 行上——按事件类型过滤
    events = list(
        session.scalars(
            select(OperationEvent)
            .options(joinedload(OperationEvent.actor))
            .where(
                OperationEvent.project_id == project_id,
                OperationEvent.event_type.in_(GATE_EVENT_TYPES),
            )
            .order_by(OperationEvent.occurred_at.desc())
            .limit(30)
        )
    )
    return [
        {
            "event_type": event.event_type,
            "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
            "actor_display_name": event.actor.display_name if event.actor else None,
            "changes": event.changes,
        }
        for event in events
    ]
