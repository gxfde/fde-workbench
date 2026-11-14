"""Gate 评估回执与验收契约（V3.3 M5-WP2③；D29 不可变回执 + 结构化验收契约）。

独立新模块——``ontology/service.py`` 2102 行封顶只减不增，本模块零依赖它。

D29（不可变 GateEvaluationReceipt）：Gate 拍板生效瞬间固化「输入快照 +
快照哈希 + 当时本体降级态 + D31 处置闭环判定 + 拍板结论绑定」——历史重放
只验回执，免疫实时网络抖动。不可变性由 ORM before_update/before_delete
守卫强制（沿 workflows/models.py §9.3 快照守卫先例扩展到全行），Agent 与
ontology-service 均无写通道（S-16 只读、无任何回执改写 API 面）。

验收契约（acceptance_contracts）：结构化验收契约项——输入清单、量化规则
引用、acceptor 按**角色**判定（project_lead 等平台角色，换人不失效）、争议
响应 SLA 小时数。独立实体可换版（status: draft/active/superseded）；
回执只固化签约快照。

审计映射默认假设（工作令所称 audit_events）：本仓唯一审计事件表
operation_events（projects.events.record_event）——降级审批留痕由
gate_ontology.set_gate_dependency 落，本模块只管回执与契约的固化域。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    event,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.workbench.models import Base, TimestampMixin, new_uuid

# 降级态闭集（S-16 表现层：online=本体可用原规则；degraded=降级放行+标注；
# skipped=per_gate none 档跳过；disabled=D12 门控关闭零出站）
DEGRADATION_TIERS = ("online", "degraded", "skipped", "disabled")

# 参与 receipt_sha256 的内容列（防「只改结论列」的第二级篡改；不含
# input_snapshot_json 本身——其完整性由第一级 input_snapshot_sha256 把守，
# 两级互补：改快照破第一级，改结论破第二级）
_RECEIPT_CONTENT_COLUMNS = (
    "gate_id",
    "gate_key",
    "revision",
    "result",
    "decision",
    "input_snapshot_sha256",
    "ontology_degradation",
    "decided_by_user_id",
    "decided_at",
)

# 不可变守卫的盯防列 = 内容列 + input_snapshot_json 本身。守卫与验真是两道
# 独立的闸：哈希验真靠比对发现「被改过」，守卫靠 ORM 事件让改写在 flush 前
# 响亮失败——快照列若不进守卫，改写快照虽会破坏第一级哈希，却不会在 flush
# 时即时暴露（D29 语义 = 任何内容列改动都不许静默通过）。
_RECEIPT_IMMUTABLE_COLUMNS = _RECEIPT_CONTENT_COLUMNS + ("input_snapshot_json",)


def canonical_json(value: Any) -> str:
    """稳定序列化（键序/分隔符确定）——哈希口径全仓唯一。"""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def snapshot_sha256(snapshot: dict[str, Any] | None) -> str:
    return hashlib.sha256(canonical_json(snapshot or {}).encode("utf-8")).hexdigest()


class AcceptanceContract(Base, TimestampMixin):
    """结构化验收契约（D29 配套；工作令 WP2③「gate_service 集成 AcceptanceContract」）。

    一行 = 一个门禁的一份契约（同 gate 换版走 superseded 交接，不删行）。
    acceptor_role 用**平台角色**（auth User.role 闭集）而非具体人——项目
    交接/换人不失效；拍板时由 gate_ontology.assert_acceptance_contract
    对照 actor.role 强制。
    """

    __tablename__ = "acceptance_contracts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'superseded')",
            name="ck_acceptance_contracts_status",
        ),
        CheckConstraint("sla_hours > 0", name="ck_acceptance_contracts_sla_positive"),
        Index(
            "ix_acceptance_contracts_project_gate_status",
            "project_id", "gate_key", "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    gate_key: Mapped[str] = mapped_column(String(10), nullable=False)
    # 验收输入清单（证据项 label 列表/结构化条目）；规则引用（量化规则键）
    items_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    rule_refs_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    acceptor_role: Mapped[str] = mapped_column(String(40), nullable=False)
    sla_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=72)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class GateEvaluationReceipt(Base, TimestampMixin):
    """Gate 评估回执（D29）：拍板生效瞬间固化，写后全行不可变。

    一行 = 一次拍板的本体辅助校验结论（含不可用/降级场景——校验缺席本身
    也要留痕，degradation 闭集四值）。历史重放只验回执两级哈希。
    """

    __tablename__ = "gate_evaluation_receipts"
    __table_args__ = (
        CheckConstraint(
            "ontology_degradation IN ('online', 'degraded', 'skipped', 'disabled')",
            name="ck_gate_evaluation_receipts_degradation",
        ),
        CheckConstraint(
            "char_length(input_snapshot_sha256) = 64 AND char_length(receipt_sha256) = 64",
            name="ck_gate_evaluation_receipts_sha256_len",
        ),
        Index(
            "ix_gate_evaluation_receipts_project_gate",
            "project_id", "gate_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    gate_id: Mapped[str] = mapped_column(
        ForeignKey("gates.id", ondelete="CASCADE"), nullable=False
    )
    gate_key: Mapped[str] = mapped_column(String(10), nullable=False)
    # B#28 revision（≡ gates.version 拍板时点值）——与门禁 CAS 语义同源
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    # G8 三态拍板（proceed/pivot/stop）；非 G8 恒 NULL
    decision: Mapped[str | None] = mapped_column(String(10))
    input_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ontology_checks_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    ontology_degradation: Mapped[str] = mapped_column(String(16), nullable=False)
    # ---- 合流回植（源=并行评审 b2e8d4c6a9f1 版本，append-only e9c4b7a1d5f8）----
    # 高频审计查询字段从 checks_json 提升为物理列（决策单步④）；双指纹诚实
    # 可空（disabled/skipped 档无指纹），gate_ready/disposition_closed 与并行
    # 版查询形态兼容（NOT NULL + server_default）。不进两级哈希口径（观测值列，
    # 结论完整性由既有 _RECEIPT_CONTENT_COLUMNS 守卫）。
    domain_schema_sha256: Mapped[str | None] = mapped_column(String(64))
    site_binding_sha256: Mapped[str | None] = mapped_column(String(64))
    gate_ready: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    disposition_closed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    decided_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


@event.listens_for(GateEvaluationReceipt, "before_update")
def _gate_receipt_immutable_update(mapper: Any, connection: Any, target: Any) -> None:
    """D29 全行不可变：已落库回执任一内容列（含快照列）再变更即在 flush 前响亮失败。"""
    from sqlalchemy import inspect as sa_inspect

    state = sa_inspect(target)
    for attr in _RECEIPT_IMMUTABLE_COLUMNS:
        history = state.attrs[attr].history
        if history.has_changes() and history.deleted:
            raise RuntimeError(
                "gate_evaluation_receipts is immutable after insert "
                f"(D29; column={attr})"
            )


@event.listens_for(GateEvaluationReceipt, "before_delete")
def _gate_receipt_immutable_delete(mapper: Any, connection: Any, target: Any) -> None:
    """D29：回执不可删除（审计记录；项目级 CASCADE 除外——库级外键语义）。"""
    raise RuntimeError(
        "gate_evaluation_receipts is immutable, delete forbidden (D29)"
    )


def receipt_sha256(receipt: GateEvaluationReceipt) -> str:
    """第二级防篡改摘要（内容列集合口径，见 _RECEIPT_CONTENT_COLUMNS）。

    datetime 统一规范化 UTC 后序列化——DB 往返（timestamptz 会话时区差异）
    不得改变哈希口径，否则历史回执重放验真会假阴性。
    """
    payload = {}
    for attr in _RECEIPT_CONTENT_COLUMNS:
        value = getattr(receipt, attr)
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            value = value.astimezone(timezone.utc)
            payload[attr] = value.isoformat()
        else:
            payload[attr] = value
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def verify_receipt(receipt: GateEvaluationReceipt) -> bool:
    """两级哈希验真：快照级 + 内容列级。任一失配即 False（重放/审计入口）。"""
    if receipt.input_snapshot_sha256 != snapshot_sha256(receipt.input_snapshot_json):
        return False
    return receipt.receipt_sha256 == receipt_sha256(receipt)


def freeze_gate_receipt(
    session: Any,
    *,
    project_id: str,
    gate: Any,
    actor: Any,
    result: str,
    decision: str | None,
    ontology_eval: dict[str, Any],
    contract_snapshot: dict[str, Any] | None,
) -> GateEvaluationReceipt:
    """拍板生效瞬间固化回执（decide_gate 成功路径唯一入口；调用方事务内）。

    ontology_eval = gate_ontology.evaluate_gate_ontology 的返回（degradation
    + checks）；contract_snapshot = assert_acceptance_contract 的返回（无
    契约 None）。快照只含拍板判定所需元数据，不含证据原文（证据永远只在
    project_evidence 留指纹指针）。
    """
    input_snapshot: dict[str, Any] = {
        "gate_key": gate.gate_key,
        "revision": gate.version,
        "actor_user_id": actor.id,
        "actor_role": actor.role,
        "submitted_by_user_id": gate.submitted_by_user_id,
        "acceptance_contract": contract_snapshot,
    }
    receipt = GateEvaluationReceipt(
        project_id=project_id,
        gate_id=gate.id,
        gate_key=gate.gate_key,
        revision=gate.version,
        result=result,
        decision=decision,
        input_snapshot_json=input_snapshot,
        input_snapshot_sha256=snapshot_sha256(input_snapshot),
        ontology_checks_json=dict(ontology_eval.get("checks") or {}),
        ontology_degradation=ontology_eval["degradation"],
        domain_schema_sha256=ontology_eval.get("checks", {}).get("domain_schema_sha256"),
        site_binding_sha256=ontology_eval.get("checks", {}).get("site_binding_sha256"),
        gate_ready=bool(ontology_eval.get("checks", {}).get("gate_ready")),
        disposition_closed=bool(
            (ontology_eval.get("checks", {}).get("candidate_disposition") or {}).get(
                "all_disposed", True
            )
        ),
        decided_by_user_id=actor.id,
        decided_at=datetime.now(timezone.utc),
    )
    receipt.receipt_sha256 = receipt_sha256(receipt)
    session.add(receipt)
    return receipt
