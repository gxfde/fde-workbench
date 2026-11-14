"""Gate 本体治理（V3.3 M5-WP2③④）：S-16 双层降级 + S-12 防降级旁路锁
+ D31 处置闸 + 验收契约闸 + 拍板前本体辅助校验。

独立新模块——``ontology/service.py`` 2102 行封顶只减不增，本模块零依赖它；
判定纯逻辑不出仓，出站只读 governance-summary（无任何本体写通道）。

S-16（集成契约 §0/§3，冻结契约 v1.3.0-m5）双层降级枚举：
- 全局环境闸 ``FDE_ONTOLOGY_GATE_DEPENDENCY = strong | weak | per_gate``
  （config.py 启动校验，缺省 ``per_gate``）；
- ``strong``：本体不可用一律挂起门禁（409 gate_ontology_unavailable）；
- ``weak``：原规则运行 + 回执标注 degraded（未校验留痕）；
- **仅 ``per_gate``** 读单门禁 ``gates.ontology_dependency =
  required | optional | none``，行值缺省 ``optional``（本体辅助语义：
  可用则校验标注、不可用降级放行，不阻断业务拍板）；
- 非法全局值 fail-closed 取 strong（宁严勿松）。

S-12（任务书红线 12 / 工作令 §1 条 4）防降级旁路锁：门禁依赖基线建档后，
任何**下调**（严格序 required > optional > none）须同时满足——①异人：
操作人 ≠ 基线建档人（gate.ontology_dependency_baseline_by_user_id）；
②Owner：操作人 = 项目 leader_user_id（admin 平台位同权）；③非熔断窗口：
本体熔断（breaker ≠ closed）期严禁下调生效。收紧（升级）自由，任何
manage 位可做。每次落值记 operation_events（工作令所称 audit_events 的
本仓实现）。

审计映射默认假设：「项目 Owner」= ``Project.leader_user_id``（admin 同权）；
「异人」= 操作人 ≠ 基线建档人。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.projects.gate_receipt import AcceptanceContract

# S-16 外层全局闸 / 内层单门禁等级
GLOBAL_TIERS = ("strong", "weak", "per_gate")
GATE_LEVELS = ("required", "optional", "none")
# 严格序：数值越大越严格；下调 = 放松 = 严格度变小（S-12 审批锁触发条件）
_LEVEL_STRICTNESS: dict[str, int] = {"none": 0, "optional": 1, "required": 2}
# 全局 strong/weak 直接映射为生效档（内层值不可达，防旁路）
_DIRECT_TIERS = {"strong": "strong", "weak": "weak"}
# per_gate 行值缺省档：optional（本体辅助语义；对方评审稿曾用 required，
# 本仓按集成契约「per_gate 缺省=辅助校验」口径取 optional——不可用降级放行）
_PER_GATE_DEFAULT = "optional"

# 硬卡处置闸的生效档：把本体当必需品的档位才硬卡 D31（optional/weak 只
# 透明标注不阻断——optional 的语义就是「本体不可用也可放行」）
_DISPOSITION_HARD_TIERS = ("required", "strong")

# S-12 降级审批留痕事件（audit_events ≡ operation_events，record_event 单口）
ONTOLOGY_EVENT_TYPE = "gate_ontology_dependency_changed"


class GateOntologyError(Exception):
    """本体治理域业务错（code 供 API 面映射；status 即 HTTP 状态码）。"""

    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def client_from_settings() -> Any:
    """唯一出站工厂（测试 monkeypatch 点；与 integrations.service 同名同构）。

    只在 ontology_enabled=True 时会被触达（evaluate 先做 D12 disabled 短路）；
    返回 OntologyClient（熔断/重试/签名同 M4 契约）。
    """
    from fde_api.integrations.service import client_from_settings as _factory

    return _factory()


def resolve_effective_dependency(global_tier: str | None, gate_row_value: str | None) -> str:
    """解析生效本体依赖档（S-16 双层；返回 ∈ strong|weak|required|optional|none）。"""
    gate = (global_tier or "").strip() or "per_gate"
    if gate not in GLOBAL_TIERS:
        return "strong"  # 非法全局值 fail-closed（config 校验是第一道，此为运行时兜底）
    if gate in _DIRECT_TIERS:
        return _DIRECT_TIERS[gate]
    row = (gate_row_value or "").strip()
    return row if row in GATE_LEVELS else _PER_GATE_DEFAULT


def is_dependency_downgrade(current: str, proposed: str) -> bool:
    """判定是否下调（放松方向）；任一端非法视为无效变更（非下调，调用方 400）。"""
    old = _LEVEL_STRICTNESS.get((current or "").strip())
    new = _LEVEL_STRICTNESS.get((proposed or "").strip())
    if old is None or new is None:
        return False
    return new < old


def _ambient_breaker_open() -> bool:
    """缺省熔断观察（breaker_open 未显式提供时）：请求上下文内读 client 内存
    态（零出站）；上下文外（内部直调/脚本）无法观察 → 视为非熔断窗口
    （False）；enabled 但 client 构建/读态异常 → fail-closed True（宁严勿松，
    熔断窗口宁可拒下调）。真实调用点应显式传入 breaker_open 快照。"""
    try:
        from flask import current_app

        settings = current_app.config["SETTINGS"]
    except RuntimeError:
        return False
    if not getattr(settings, "ontology_enabled", False):
        return False  # D12 disabled：零出站，无熔断窗口概念
    try:
        return client_from_settings().breaker_state != "closed"
    except Exception:
        return True


def _load_active_binding(session: Session, project: Any) -> Any | None:
    """项目活跃本体绑定（primary 优先；同项目同本体单活跃由唯一键保证）。

    ProjectOntologyBinding 函数内导入：包级顶层导入环冻结
    （test_architecture_purity）——integrations→projects 既有边不可反向成环。
    """
    from fde_api.integrations.models import ProjectOntologyBinding

    return session.scalar(
        select(ProjectOntologyBinding)
        .where(
            ProjectOntologyBinding.project_id == project.id,
            ProjectOntologyBinding.status == "active",
        )
        .order_by(ProjectOntologyBinding.binding_role.desc(), ProjectOntologyBinding.id.asc())
        .limit(1)
    )


def evaluate_gate_ontology(
    session: Session, *, project: Any, gate: Any, actor: Any
) -> dict[str, Any]:
    """拍板前本体辅助校验（decide_gate 唯一接线点；只读，零落库）。

    返回 ``{"degradation", "checks"}``——degradation ∈ online|degraded|
    skipped|disabled（回执固化用）；checks 透明记录判定依据（生效档/绑定/
    D31 处置闭环）。

    卡点（仅此两个，工作令「只卡 100% 人工处置」；免改率等一律不卡）：
    - required/strong 且本体不可用 → 409 gate_ontology_unavailable（挂起）；
    - required/strong 且本体可用但有未处置候选（<0.8/冲突候选未 100% 人工
      处置，D31 古德哈特护栏）→ 409 gate_ontology_disposition_open。
    optional/weak 两场景一律降级放行（degraded 标注），处置状态只进 checks。
    """
    from flask import current_app

    settings = current_app.config["SETTINGS"]
    if not getattr(settings, "ontology_enabled", False):
        return {"degradation": "disabled", "checks": {"reason": "ontology_disabled"}}
    tier = resolve_effective_dependency(
        settings.ontology_gate_dependency, gate.ontology_dependency
    )
    checks: dict[str, Any] = {"effective_dependency": tier}
    if tier == "none":
        # per_gate none 档：跳过本体校验，零出站（回执照固留痕 skipped）
        return {"degradation": "skipped", "checks": checks}

    binding = _load_active_binding(session, project)
    if binding is None:
        checks["binding_found"] = False
        if tier in _DISPOSITION_HARD_TIERS:
            raise GateOntologyError(
                "gate_ontology_unavailable",
                "门禁本体依赖为 required，但项目无活跃本体绑定，暂不能拍板。",
                409,
            )
        checks["unavailable_reason"] = "no_active_binding"
        return {"degradation": "degraded", "checks": checks}

    checks["binding_found"] = True
    checks["ontology_id"] = binding.ontology_id
    checks["pinned_version_id"] = binding.pinned_version_id
    try:
        client = client_from_settings()
        summary = client.get_version_governance_summary(
            actor_id=actor.id,
            org_id=project.org_id,
            project_id=project.id,
            ontology_id=binding.ontology_id,
            version_id=binding.pinned_version_id,
        )
        if summary.get("_status") != 200:
            raise RuntimeError(f"governance-summary _status={summary.get('_status')}")
    except Exception as exc:  # 熔断/超时/5xx/绑定版本失联 → 统一按不可用
        checks["unavailable_reason"] = type(exc).__name__
        if tier in _DISPOSITION_HARD_TIERS:
            raise GateOntologyError(
                "gate_ontology_unavailable",
                "本体运行时不可用（strong/required 档挂起门禁，回执不产、稍后重拍）。",
                409,
            ) from exc
        return {"degradation": "degraded", "checks": checks}

    disposition = summary.get("candidate_disposition")
    if isinstance(disposition, dict):
        checks["candidate_disposition"] = disposition
    checks["gate_ready"] = bool(summary.get("gate_ready"))
    # D31 古德哈特护栏：required/strong 只卡「<0.8/冲突候选 100% 人工处置」；
    # 免改/精修/驳回均算已处置（summary all_disposed 口径），不算阻断项。
    if (
        tier in _DISPOSITION_HARD_TIERS
        and isinstance(disposition, dict)
        and disposition.get("all_disposed") is False
    ):
        raise GateOntologyError(
            "gate_ontology_disposition_open",
            "存在低置信度/冲突候选未完成 100% 人工处置（免改/精修/驳回均算处置），"
            "required 门禁暂不能拍板。",
            409,
        )
    return {"degradation": "online", "checks": checks}


def contract_snapshot(contract: Any) -> dict[str, Any]:
    """契约签约快照（回执固化用；换版后旧回执仍可对账历史契约形态）。"""
    return {
        "contract_id": contract.id,
        "gate_key": contract.gate_key,
        "items": list(contract.items_json or []),
        "rule_refs": list(contract.rule_refs_json or []),
        "acceptor_role": contract.acceptor_role,
        "sla_hours": contract.sla_hours,
        "status": contract.status,
    }


def assert_acceptance_contract(
    session: Session, *, project_id: str, gate: Any, actor: Any
) -> dict[str, Any] | None:
    """验收契约闸：active 契约存在时，拍板人 platform role 须匹配 acceptor_role。

    无契约 → 返回 None（向后兼容：未签约门禁不拦）；role 不符 → 403
    gate_acceptor_role_required（闸序在 P0-5 异人闸之后——先验人再验角色）。
    返回契约快照（调用方固化进回执输入快照）。
    """
    contract = session.scalar(
        select(AcceptanceContract)
        .where(
            AcceptanceContract.project_id == project_id,
            AcceptanceContract.gate_key == gate.gate_key,
            AcceptanceContract.status == "active",
        )
        .order_by(AcceptanceContract.created_at.desc(), AcceptanceContract.id.desc())
        .limit(1)
    )
    if contract is None:
        return None
    if (actor.role or "") != contract.acceptor_role:
        raise GateOntologyError(
            "gate_acceptor_role_required",
            f"该门禁验收契约要求 {contract.acceptor_role} 角色拍板。",
            403,
        )
    return contract_snapshot(contract)


def set_gate_dependency(
    session: Session,
    *,
    actor: Any,
    project_id: str,
    gate: Any,
    new_level: str,
    breaker_open: bool | None = None,
) -> dict[str, Any]:
    """设置/变更门禁本体依赖档（S-16 内层；S-12 三闸收口；调用方事务内）。

    - 建档（行值 None → 初次落值）：自由，任何 manage 位可做；基线建档人
      = 操作人（S-12 异人判定锚点）；
    - 收紧/平调（严格度不降）：自由；基线建档人不变；
    - 下调（放松）：三闸——异人（≠基线建档人）→ Owner（leader/admin）→
      非熔断窗口；任一不满足即 GateOntologyError，零落值；
    - 全部落值记 operation_events（audit_events ≡ operation_events 映射）。
    """
    from fde_api.projects.events import record_event
    from fde_api.workbench.models import Project

    if new_level not in GATE_LEVELS:
        raise GateOntologyError(
            "invalid_request", f"ontology_dependency 仅可为 {'/'.join(GATE_LEVELS)}。", 400
        )
    current = gate.ontology_dependency
    effective_breaker = _ambient_breaker_open() if breaker_open is None else breaker_open
    out: dict[str, Any] = {
        "from_level": current,
        "to_level": new_level,
        "breaker_open": effective_breaker,
    }
    if current == new_level:
        out.update(changed=False, action="noop")
        return out

    if current is None:
        action = "establish"
        gate.ontology_dependency = new_level
        gate.ontology_dependency_baseline_by_user_id = actor.id
    elif not is_dependency_downgrade(current, new_level):
        action = "tighten"  # 收紧/平调自由；基线建档人不因收紧改变（S-12 锚点稳定）
        gate.ontology_dependency = new_level
    else:
        action = "downgrade"
        if gate.ontology_dependency_baseline_by_user_id == actor.id:
            raise GateOntologyError(
                "same_person_forbidden",
                "下调本体依赖须异人审批：操作人不得是基线建档人（S-12）。",
                403,
            )
        project = session.get(Project, project_id)
        is_owner = project is not None and (
            project.leader_user_id == actor.id or actor.role == "admin"
        )
        if not is_owner:
            raise GateOntologyError(
                "owner_required",
                "下调本体依赖须项目 Owner（leader/admin）审批（S-12）。",
                403,
            )
        if effective_breaker:
            raise GateOntologyError(
                "circuit_open_no_downgrade",
                "本体熔断窗口内严禁下调依赖等级（S-12：宁可挂起，不带病降级）。",
                409,
            )
        gate.ontology_dependency = new_level

    out.update(changed=True, action=action)
    record_event(session, actor, ONTOLOGY_EVENT_TYPE, gate, dict(out))
    return out
