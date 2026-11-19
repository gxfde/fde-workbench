"""action_execution 服务面：真门装配 + 执行记录落库（AE1-WP1）。

门装配（WP1 生产默认）：
- **幂等门**＝查 ``action_executions``（UNIQUE(org_id, idempotency_key)）——
  同键异体 409 ``idempotency_mismatch``；同体在途（awaiting_approval 行在场）
  409 ``idempotency_in_flight``；同体终态复放（不落新行，零副作用）；
- **白名单门**＝fail-closed（无注册连接器一律 403 ``tool_not_allowed``；
  只读加载器与三元组匹配归 AE1-WP3，禁改清单第 7 项：缺失/损坏不得回退
  「任意 URL 可调」）；
- **审批门**＝复用 ``AutomationApproval``（``run_id=None`` 直发形态）+ 指纹
  复算沿 ``control/service.py`` 先例；拍板面 ``decide_automation_approval``
  本体零改动（禁改清单第 1 项）；
- **派发**＝未接线 fail-closed（403 + ``details.connector_adapter_not_wired``，
  Q8 闭集外映射口径）；连接器适配归 AE1-WP3。
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from fde_api.action_execution.executor import ActionExecutor, replay_payload_from_row, request_fingerprint
from fde_api.action_execution.errors import ActionExecutionError
from fde_api.action_execution.models import ActionCompensation, ActionExecution, ActionExecutionLog
from fde_api.action_execution.schemas import build_error, build_rollback_result
from fde_api.auth.models import User
from fde_api.control.access import authorize_ai_capability
from fde_api.control.models import AutomationApproval
from fde_api.errors import NOT_FOUND_MESSAGE
from fde_api.extensions import db
from fde_api.workbench.models import new_uuid

AE_CAPABILITY = "action_execution.invoke"  # CAPABILITY_REQUIREMENTS：project_operator（AE1-WP1 注册）

logger = logging.getLogger(__name__)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


@contextmanager
def _ae_session() -> Iterator[Any]:
    """``db.session()`` 用后即还连接（WP5-B 登记）。

    ``extensions.Database`` 每次调用返回**全新 Session**（非 scoped），连接在
    ``close`` 前不归还池——本面全部位点经此上下文包裹，评测 runner 高频连续
    提交（单测试 27 次）曾把池（size 5 + overflow 10）抽干成 30s 假等待。
    事务口径不变：commit/rollback 由调用方负责，此处只负责归还连接；
    ``expire_on_commit=False``（extensions.py:24）——close 后已加载属性可读。
    """
    session = db.session()
    try:
        yield session
    finally:
        session.close()


class _DbIdempotencyGate:
    """L2 门：``action_executions`` 表上的幂等裁决。"""

    def lookup(self, idempotency_key: str, org_id: str, fingerprint: str) -> dict | None:
        with _ae_session() as session:
            row = session.scalar(
                select(ActionExecution).where(
                    ActionExecution.idempotency_key == idempotency_key,
                    ActionExecution.org_id == org_id,
                )
            )
            if row is None:
                return None
            if row.request_fingerprint != fingerprint:
                raise ActionExecutionError("idempotency_mismatch", "同键请求体不一致（幂等指纹不符）。")
            if row.status == "awaiting_approval":
                raise ActionExecutionError("idempotency_in_flight", "同键执行在途，请退避后重试。")
            if row.status == "succeeded":
                return replay_payload_from_row(row)
            # failed/cancelled 终态行：复放原失败态（WP1 执行段不产此类行；腿留 WP2+）
            return {
                "execution_id": row.id,
                "output": row.output_json or {},
                "audit": row.audit_json,
                "cost": row.cost_json,
                "rollback": row.rollback_json,
            }


class _FailClosedWhitelist:
    """L3 门（WP1 默认）：无白名单装配＝全拒（fail-closed 默认关，Q7/禁改 7）。"""

    def check(self, connector_id: str, method: str) -> None:
        raise ActionExecutionError("tool_not_allowed", "连接器未在白名单注册（fail-closed）。")


class _UnwiredDispatch:
    """执行段（WP1 默认）：连接器适配未接线 → fail-closed 拒绝（Q8 映射+details）。"""

    def call(self, request: dict) -> dict:
        raise ActionExecutionError(
            "tool_not_allowed",
            "连接器适配未接线（AE1-WP3 落位前拒绝一切外呼）。",
            details={"reason": "connector_adapter_not_wired"},
        )


class _DbApprovalGate:
    """L4 门：写型 risk≥3 校验 ``AutomationApproval``（复用拍板面的登记面）。"""

    def __init__(self, actor: User) -> None:
        self._actor = actor

    def verify(self, request: dict) -> dict | None:
        if request["dry_run"] or request["risk_level"] < 3:
            return None  # 干跑/低风险直通（审批闸只管写型高风险）
        approval_id = request.get("approval_id")
        if not isinstance(approval_id, str) or not approval_id.strip():
            raise ActionExecutionError("approval_required", "写型高风险动作缺 approval_id。")
        with _ae_session() as session:
            approval = session.scalar(
                select(AutomationApproval)
                .options(joinedload(AutomationApproval.project))
                .where(AutomationApproval.id == approval_id)
            )
            if approval is None:
                raise ActionExecutionError("approval_not_found", "审批请求不存在。", status=404)
            # 归属面：审批单租户链（project.org_id）与请求 org 不符 → 404 不泄露；
            # 审批单请求人与执行 requester 不符 → 404 同口径（跨主体不泄露）。
            project = approval.project
            if project is None or project.org_id != request["org_id"]:
                raise ActionExecutionError("approval_not_found", "审批请求不存在。", status=404)
            if approval.requested_by_user_id != request["requester_id"]:
                raise ActionExecutionError("approval_not_found", "审批请求不存在。", status=404)
            now = datetime.now(UTC)
            if approval.status == "expired" or (approval.status == "pending" and approval.expires_at <= now):
                raise ActionExecutionError("approval_expired", "操作审批已过期。")
            if approval.status != "approved":
                raise ActionExecutionError("approval_not_approved", "该操作尚未获批。")
            # 指纹复算（U1 x-approval.integrity；沿 control/service.py:864-871 先例）：
            # 请求 params 的 canonical sha256 须与审批登记面一致。
            if sha256(_canonical(request["params"]).encode("utf-8")).hexdigest() != approval.arguments_sha256:
                raise ActionExecutionError("approval_integrity_failed", "审批参数完整性校验失败。")
            # 执行前权限重验（U1 x-approval.revocation）
            decision = authorize_ai_capability(user=self._actor, capability=AE_CAPABILITY, project=project)
            if not decision.allowed:
                raise ActionExecutionError("permission_revoked", "任务发起人已不具备该操作权限。")
            return {"approval_id": approval.id}


FAIL_CLOSED_WHITELIST = _FailClosedWhitelist()
UNWIRED_DISPATCH = _UnwiredDispatch()


def submit_action(
    *,
    actor: User,
    payload: Any,
    whitelist_gate=_FailClosedWhitelist(),
    dispatch=_UnwiredDispatch(),
    rollback_supported: bool = False,
) -> dict[str, Any]:
    """提交单步动作执行（租户绑定 → 五层编排 → 在途锁 → 落库 → 契约结果）。

    返回契约 ``ActionExecutionResult`` 形态 dict；复放不落新行。拒绝路径以
    ``ActionExecutionError`` 冒泡（routes 转 ``{data:null,error:{...}}`` 信封）。

    WP2 在途锁（U1 ``x-idempotency.in_flight`` / U2 S-AE-02 A9）：L5 通过后、
    dispatch 前落 ``awaiting_approval`` 锁行占用 ``UNIQUE(org_id, idempotency_key)``
    ——并发败者在**零副作用窗口**（dispatch 未发生）即被 409 挡下；锁行与终态
    是同一行的状态机推进（``awaiting_approval → succeeded/failed``，语义＝
    「尚未执行；零外部副作用」，终态翻转后锁随唯一约束自然释放为复放通道）。
    """
    if not isinstance(payload, dict):
        raise ActionExecutionError("validation_failed", "请求体须为 JSON 对象。")
    # 租户绑定（U1 x-tenant-isolation.server_side_binding：不盲信调用方 org_id；
    # 与上下文不一致按 404——Q15 口径，不泄露「存在但无权」与「不存在」的差别）
    request_org = payload.get("org_id")
    if not isinstance(request_org, str) or request_org != actor.org_id:
        raise ActionExecutionError("not_found", NOT_FOUND_MESSAGE)

    executor = ActionExecutor(
        idempotency_gate=_DbIdempotencyGate(),
        whitelist_gate=whitelist_gate,
        approval_gate=_DbApprovalGate(actor),
        dispatch=dispatch,
        in_flight_lock=_make_in_flight_lock(payload),
    )
    try:
        result = executor.execute(payload)
    except ActionExecutionError as exc:
        # 锁行翻 failed 诚实终态（拒绝路径发生在锁前——锁行不存在则跳过，保持
        # WP1「白名单/审批拒绝零落库」行为；dispatch 失败的锁行翻 failed 留痕）
        _finalize_in_flight(payload, result=None, error=exc)
        raise
    if result["status"] == "replayed":
        return result  # 复放零新行（同键一行真身；锁行未被本请求触碰）
    _finalize_in_flight(payload, result=result, error=None, rollback_supported=rollback_supported)
    return result


def _in_flight_row(payload: dict) -> ActionExecution | None:
    # 缺键防御：422 路径（validation_failed 先于锁）无键可查——finalize 无行可翻，
    # 零落库跳过（与 WP1「拒绝路径不落库」口径一致）。
    key = payload.get("idempotency_key")
    org = payload.get("org_id")
    if not isinstance(key, str) or not isinstance(org, str):
        return None
    with _ae_session() as session:
        return session.scalar(
            select(ActionExecution).where(
                ActionExecution.idempotency_key == key,
                ActionExecution.org_id == org,
            )
        )


def _make_in_flight_lock(payload: dict):
    """构造在途锁闭包（executor L5 后调用，入参 execution_id）。

    落 ``awaiting_approval`` 锁行；``IntegrityError``（并发败者撞
    ``uq_action_executions_org_idem``）→ 重读既有行按指纹裁决：异体 409
    ``mismatch``／同键 409 ``in_flight``（U2 A9：败者未到 dispatch，副作用恒 1）。
    先例：``agents/service.py:649-664`` 败者重读在途行。
    """
    fingerprint = request_fingerprint(payload)

    def lock(execution_id: str) -> None:
        # SQLAlchemy 2.0 autobegin：同 session 上幂等门已查询过（事务已隐式开启），
        # 不得再 ``with session.begin()``——直接 add + commit，异常 rollback（项目先例口径）。
        with _ae_session() as session:
            try:
                session.add(
                    ActionExecution(
                        id=execution_id,
                        idempotency_key=payload["idempotency_key"],
                        org_id=payload["org_id"],
                        requester_id=payload["requester_id"],
                        action_id=payload["action_id"],
                        action_type=payload.get("action_type"),
                        connector_id=payload["connector_id"],
                        method=payload["method"],
                        params_sha256=sha256(_canonical(payload["params"]).encode("utf-8")).hexdigest(),
                        request_fingerprint=fingerprint,
                        dry_run=bool(payload["dry_run"]),
                        risk_level=int(payload["risk_level"]),
                        approval_id=payload.get("approval_id"),
                        status="awaiting_approval",  # 在途锁位（契约语义：尚未执行；零外部副作用）
                        audit_json={},
                        cost_json={},
                        rollback_json={"supported": False, "execution_id": execution_id},
                    )
                )
                session.commit()
            except IntegrityError:
                session.rollback()
                row = _in_flight_row(payload)
                if row is not None and row.request_fingerprint != fingerprint:
                    raise ActionExecutionError("idempotency_mismatch", "同键请求体不一致（幂等指纹不符）。") from None
                raise ActionExecutionError("idempotency_in_flight", "同键执行在途，请退避后重试。") from None

    return lock


class _NoCompensator:
    """fail-closed 默认补偿器：返回 ``skipped`` 条目——回滚判定据此转
    ``not_supported``（诚实：无补偿器注册即无回滚能力，不谎报 ``rolled_back``）。
    真实补偿器随 WP3 连接器适配按 kind 注册。"""

    def compensate(self, record: dict) -> dict[str, Any]:
        return {
            "compensation_id": f"no-comp-{str(record.get('execution_id', ''))[:8]}",
            "kind": record["kind"],
            "target": record["target"],
            "status": "skipped",
            "detail": {"reason": "no_compensator_registered"},
        }


NO_COMPENSATOR = _NoCompensator()


def _write_audit_log(session: Any, execution_id: str, result: dict[str, Any]) -> None:
    """审计落行（AE1-WP4，U1 ``$defs/AuditObject`` 9 必填＋``$defs/CostObject`` 3 字段）。

    纪律：
    - **一行一执行**：``execution_id`` UNIQUE——重复 finalize（防御路径）不追加；
    - **零明文**：审计行只落 ``params_sha256``；应用日志同口径——只落指纹
      与计数，绝不落 params/响应体（C-08）；
    - **append-only**：只在终态 succeeded 写入；失败路径不落审计行（无真实
      起止时间即不伪造），失败留痕在 ``action_executions.error_json``。
    """
    audit = result["audit"]
    cost = result["cost"]
    existing = session.scalar(select(ActionExecutionLog).where(ActionExecutionLog.execution_id == execution_id))
    if existing is not None:
        return
    session.add(
        ActionExecutionLog(
            id=new_uuid(),
            execution_id=execution_id,
            org_id=audit["org_id"],
            connector_id=audit["connector_id"],
            method=audit["method"],
            params_sha256=audit["params_sha256"],
            actor_user_id=audit["actor_user_id"],
            approval_id=audit["approval_id"],
            started_at=datetime.fromisoformat(audit["started_at"]),
            finished_at=datetime.fromisoformat(audit["finished_at"]),
            duration_ms=int(audit["duration_ms"]),
            tool_calls=int(cost["tool_calls"]),
            estimated_usd=cost["estimated_usd"],
        )
    )
    # 应用日志腿：结构化一行，只含指纹/计数锚——零 params、零响应体。
    logger.info(
        "ae_execution_audited execution_id=%s connector=%s method=%s params_sha256=%s duration_ms=%s tool_calls=%s",
        execution_id,
        audit["connector_id"],
        audit["method"],
        audit["params_sha256"],
        audit["duration_ms"],
        cost["tool_calls"],
    )


def _finalize_in_flight(
    payload: dict,
    *,
    result: dict[str, Any] | None,
    error: ActionExecutionError | None,
    rollback_supported: bool = False,
) -> None:
    """锁行 → 终态（同一行状态机推进；行不存在＝拒绝发生在锁前，零落库跳过）。

    ``db.session()`` 每次调用返回**全新 Session**（extensions.Database 非
    scoped）——查询与属性赋值必须用**同一 session 变量**（跨 session 的
    ORM 对象赋值不被 track，commit 无事发生＝静默丢写）。"""
    with _ae_session() as session:
        # 缺键防御：422 路径（validation_failed 先于锁）无键可查——finalize 无行
        # 可翻，零落库跳过（与 WP1「拒绝路径不落库」口径一致）。
        key = payload.get("idempotency_key")
        org = payload.get("org_id")
        if not isinstance(key, str) or not isinstance(org, str):
            return
        row = session.scalar(
            select(ActionExecution).where(
                ActionExecution.idempotency_key == key,
                ActionExecution.org_id == org,
            )
        )
        if row is None:
            return
        # autobegin 口径同 lock：属性赋值 + commit，异常 rollback（不得 with session.begin()）
        try:
            if result is not None:
                row.status = result["status"]
                row.output_json = result["output"]
                row.error_code = (result["error"] or {}).get("code", "")
                row.error_json = result["error"]
                row.replayed_from_execution_id = result["replayed_from_execution_id"]
                row.approval_id = result["audit"]["approval_id"]
                row.audit_json = result["audit"]
                row.cost_json = result["cost"]
                row.rollback_json = result["rollback"]
                # WP4 审计落行（与终态同事务——审计与执行记录原子一致）
                _write_audit_log(session, row.id, result)
            else:
                assert error is not None
                row.status = "failed"
                row.error_code = error.code
                row.error_json = build_error(error.code, error.message, retryable=False, details=error.details)
            session.commit()
        except Exception:
            session.rollback()
            raise


def rollback_action(
    *,
    actor: User,
    execution_id: str,
    reason: str | None = None,
    idempotency_key: str | None = None,
    compensator: Any = None,
) -> dict[str, Any]:
    """回滚服务（U1 ``x-rollback``；U2 S-AE-03）：逐条补偿＋幂等＋四态诚实失败。

    - 幂等（A3）：``execution_id`` 唯一批次——重复调用短路复用既有批次，
      补偿副作用计数不增（先例 ``agents/sandbox.py:319-327`` destroyed 短路）；
    - 入态（U1 ``rollback_entry_states``）：cancelled/awaiting_approval/replayed
      → ``noop``；succeeded/failed → 可回滚；
    - ``supported=false`` → ``not_supported``（不谎报 ``rolled_back``）；
    - 部分补偿失败 → ``failed``＋``compensation_failed``＋
      ``details.compensation_ids``（不得报 ``rolled_back``）；
    - 跨租户/不存在 → 404 ``not_found``（不泄露存在性）；
    - **审批读法**（U1 ``x-rollback.exceptions.approval_required``）：AE1 单步
      补偿＝撤销既有被审批副作用（非新副作用），被原执行 ``approval_id`` 覆盖；
      risk≥3 真执行行 approval_id 缺失属 L4 不变量破缺 → 防御 403。
    """
    if compensator is None:
        compensator = NO_COMPENSATOR
    with _ae_session() as session:
        row = session.scalar(select(ActionExecution).where(ActionExecution.id == execution_id))
        if row is None or row.org_id != actor.org_id:
            raise ActionExecutionError("not_found", NOT_FOUND_MESSAGE)

        batch = session.scalar(select(ActionCompensation).where(ActionCompensation.execution_id == execution_id))
        if batch is not None:
            # 幂等短路：既有批次复用（A3——条目数与各条 status 不变，零新补偿副作用）
            return {
                "execution_id": execution_id,
                "status": batch.status,
                "compensations": batch.compensations_json,
                "output": None,
                "error": batch.error_json,
            }

        result = _compute_rollback(row, compensator)
        _persist_compensation_batch(
            row, result, actor=actor, reason=reason, idempotency_key=idempotency_key
        )
        return result


def _compute_rollback(row: ActionExecution, compensator: Any) -> dict[str, Any]:
    """四态判定（纯逻辑；批次落库由调用方负责）。"""
    # 入态判定（U1 rollback_entry_states）：零副作用可补偿态 → noop
    if row.status in ("cancelled", "awaiting_approval") or row.replayed_from_execution_id:
        return build_rollback_result(execution_id=row.id, status="noop", compensations=[], error=None)
    if row.dry_run:
        # S-AE-03 A6：干跑执行零副作用 → noop
        return build_rollback_result(execution_id=row.id, status="noop", compensations=[], error=None)
    # 防御分支（模块头审批读法）：risk≥3 真执行行必须有审批覆盖
    if row.risk_level >= 3 and not row.approval_id:
        raise ActionExecutionError("approval_required", "补偿不得绕过审批（原执行审批面缺失）。")
    if not (row.rollback_json or {}).get("supported"):
        # S-AE-03 A5/A8：supported=false → 诚实 not_supported（HTTP 200 + error 对象）
        return build_rollback_result(
            execution_id=row.id,
            status="not_supported",
            compensations=[],
            error=build_error("rollback_not_supported", "该动作不支持自动回滚。", retryable=False),
        )
    # 逐条补偿（单步 T4 ⇒ 一条主补偿任务；target 零明文＝connector/method＋指纹前缀锚）
    record = {
        "kind": f"rollback_{row.method}",
        "target": f"{row.connector_id}/{row.method}#{(row.params_sha256 or '')[:12]}",
        "execution_id": row.id,
    }
    try:
        comp_record = compensator.compensate(record)
    except Exception as exc:  # 补偿器异常＝该条补偿失败（诚实 failed，不冒泡裸异常）
        comp_record = {
            "compensation_id": f"comp-{str(row.id)[:8]}",
            "kind": record["kind"],
            "target": record["target"],
            "status": "failed",
            "detail": {"reason": type(exc).__name__},
        }
    compensations = [comp_record]
    if all(c["status"] == "skipped" for c in compensations):
        # 无补偿器注册（NO_COMPENSATOR fail-closed）→ 诚实 not_supported
        return build_rollback_result(
            execution_id=row.id,
            status="not_supported",
            compensations=compensations,
            error=build_error("rollback_not_supported", "无可用补偿器（连接器适配未声明回滚能力）。", retryable=False),
        )
    failed_ids = [c["compensation_id"] for c in compensations if c["status"] == "failed"]
    if failed_ids:
        # S-AE-03 A4：部分失败诚实上报，不得报 rolled_back
        return build_rollback_result(
            execution_id=row.id,
            status="failed",
            compensations=compensations,
            error=build_error(
                "compensation_failed",
                "部分补偿失败。",
                retryable=False,
                details={"compensation_ids": failed_ids},
            ),
        )
    return build_rollback_result(execution_id=row.id, status="rolled_back", compensations=compensations, error=None)


def _persist_compensation_batch(
    row: ActionExecution, result: dict[str, Any], *, actor: User, reason: str | None, idempotency_key: str | None
) -> None:
    with _ae_session() as session:
        try:
            # autobegin 口径同 lock：rollback_action 已在此 session 上查询过，不得
            # ``with session.begin()``——add + commit，IntegrityError rollback 复用既有批次。
            session.add(
                ActionCompensation(
                    id=new_uuid(),
                    execution_id=row.id,
                    org_id=row.org_id,
                    requester_id=actor.id,
                    rollback_key=idempotency_key,
                    status=result["status"],
                    compensations_json=result["compensations"],
                    error_json=result["error"],
                    reason=reason,
                )
            )
            session.commit()
        except IntegrityError:
            # 并发双回滚：批次已被并发方登记 → 复用既有批次（幂等，A3 同源）
            session.rollback()


def get_rollback_batch(execution_id: str) -> dict[str, Any] | None:
    """回滚批次检视（内部辅助/测试）：按 execution_id 取批次快照。"""
    with _ae_session() as session:
        batch = session.scalar(select(ActionCompensation).where(ActionCompensation.execution_id == execution_id))
        if batch is None:
            return None
        return batch.snapshot()


def get_execution(*, actor, execution_id: str) -> dict[str, Any]:
    """执行详情（本人/同租户；跨租户 404 复用关闭面文案不泄露存在性）。"""
    with _ae_session() as session:
        row = session.scalar(select(ActionExecution).where(ActionExecution.id == execution_id))
        if row is None or row.org_id != actor.org_id:
            raise ActionExecutionError("not_found", NOT_FOUND_MESSAGE)
        return row.snapshot()


def get_execution_row(execution_id: str) -> ActionExecution | None:
    """内部辅助（测试/运维检视）：按 id 取原始行，无租户过滤。"""
    with _ae_session() as session:
        return session.scalar(select(ActionExecution).where(ActionExecution.id == execution_id))
