"""agents 服务层：run 生命周期 + 溯源 + 成本（goal-d4，技术实施方案 §3.1/§5）。

生命周期（自动交付 §5.1 / §7.1 判据锚）：

- 幂等（V8/I-1）：``idempotency_key`` 服务层去重——completed 复用、在途复用、
  终态失败要求显式 retry（d3 迁移注释的语义落地点）。
- 重试（≤2 次指数退避）：retry 链共享同一幂等键，家族大小 = 尝试次数；
  退避 ``base * 2^(已重试-1)`` 秒，未到点 409 ``retry_backoff_not_elapsed``。
- 熔断（V5/B-1/B-2）：单 run ``max_duration_ms``（默认 300000，D6）与
  ``max_cost_units`` 在适配器监听段强制；平台月度 ``agent_monthly_budget``
  （0 = 不限额，沿 E7 ``ai_monthly_token_budget`` 心智）在发起前拦截。
- 降级链全链（goal-d6，自动交付 §3.3 / 判定 V4）：

  - L0 正常态：沙箱 run，产物按门与校验规则进出终审。
  - L1：降级 completed（D 类 ``tool_denied`` 后 run 继续）→
    ``fallback_level=L1`` + 产物 ``linked_solution_id=None``
    （**强制人工终审，不可自动放行**——决议①：同步栈下 L1 = 降级产物
    形态，生成动作由降级 run 既有产物承载）；handoff 接受 L1 completed
    转人工终审（signoff checkpoint 收口）。
  - L2：沙箱不可用（A-1，d4）与一切非 completed 终态（timeout/
    budget_exceeded/failed，B 类——无产物可降级审，走模板填空；决议②）。
  - L3：``ai_manual_handoff`` 转人工（V7/E-2，d4），接管后挂 pending
    signoff 终审检查点。
  - V4 手动触发面：L0=start_run；L1/L2=``rehearse_fallback``（admin 演练，
    与真实故障同一标注路径，零计费）；L3=handoff（本就是人工触发面）。
- 责任主体：发起人即责任人（``initiated_by_user_id``），每次 run 实时鉴权。

产物红线：storage_ref 指针 + sha256 指纹；C-1 校验失败（缺/未知
source_refs）→ run failed + 产物 ``reviewed=False`` 永不进终审。
"""

from __future__ import annotations

import json
import os
import re
from base64 import urlsafe_b64encode
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from sqlalchemy import func, select

from fde_api.agents.adapter import (
    ADAPTER_KINDS,
    AgentRunContext,
    ArtifactFile,
    OutputScanner,
    RunEventProvider,
    ZcodeAdapter,
)
from fde_api.agents.context import (
    SANDBOX_AGENT_DISCIPLINE,
    SanitizationError,
    render_masked_context,
)
from fde_api.agents.models import (
    AgentArtifact,
    AgentCredential,
    AgentRegistry,
    AgentRun,
    AgentToolCall,
)
from fde_api.agents.sandbox import (
    DockerBackend,
    SandboxBackend,
    SandboxError,
    SandboxHandle,
    SandboxProfile,
)
from fde_api.agents.signoff import ensure_pending_signoff
from fde_api.agents import pilot, quota as seat_quota
from fde_api.agents.tools import declares_run_tools, effective_run_tools
from fde_api.auth.models import User
from fde_api.control.access import authorize_ai_capability
from fde_api.extensions import db
from fde_api.guidance.models import ProjectGuidanceAnalysis
from fde_api.meetings.service import (
    latest_sealed_mandatory_minutes,
    t1_gate_satisfied,
    t2_gate_satisfied,
    t6_gate_satisfied,
)
from fde_api.dispatch.agent_assisted import ORDER_DIFFICULTY_RUN_MAP
from fde_api.dispatch.models import DeliveryPackage
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access, visible_project_ids
from fde_api.solutions.models import ProjectSolution
from fde_api.workbench.models import Project, new_uuid

ARTIFACT_KINDS = frozenset({"code", "doc", "diff", "config"})
FAILED_STATUSES = frozenset({"failed", "timeout", "budget_exceeded"})
IN_FLIGHT_STATUSES = frozenset({"queued", "running"})
AGENT_MAX_RETRIES = 2  # 循环提示词硬性：重试上限 2 次（家族 = 3 个 run）

_CONTEXT_FILE = "context.md"
_TASK_FILE = "task.md"
_DISCIPLINE_FILE = "AGENTS.md"
_OUTPUT_DIR = "output"
_EVENTS_FILE = "events.ndjson"
_MANIFEST_FILE = "manifest.json"
_RUN_HEADER_LIMIT = 200  # 任务书正文上限（上下文本体在 context.md）


class AgentsServiceError(Exception):
    def __init__(self, code: str, message: str, status: int, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.detail = detail or {}


# ---------------------------------------------------------------------------
# 生产事件源 / 产物扫描器（容器内文件协议；测试注入假实现）
# ---------------------------------------------------------------------------


class NdjsonEventProvider:
    """监听段事件源：tail output/events.ndjson（NDJSON，逐行偏移量推进）。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._offset = 0

    def poll(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        events: list[dict[str, Any]] = []
        with self._path.open("r", encoding="utf-8") as handle:
            handle.seek(self._offset)
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    events.append(value)
            self._offset = handle.tell()
        return events


class ManifestOutputScanner:
    """回收段产物扫描：output/manifest.json → ArtifactFile 清单。

    B#2 回执状态面：scan() 返回类型不变（OutputScanner Protocol 兼容），
    回执判定落 ``receipt_state`` 属性——``ok``（manifest 可解析）/
    ``no_output``（无 output 目录或零文件=合法零产物任务）/
    ``files_without_manifest``（output/ 有文件但没写 manifest=回执缺失）/
    ``manifest_invalid``（manifest 不是合法 JSON 数组=回执写坏）。
    """

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir
        self.receipt_state = "ok"

    def _classify_missing_manifest(self) -> str:
        if not self._output_dir.exists():
            return "no_output"
        has_files = any(p.is_file() for p in self._output_dir.rglob("*"))
        return "files_without_manifest" if has_files else "no_output"

    def scan(self) -> list[ArtifactFile]:
        manifest = self._output_dir / _MANIFEST_FILE
        if not manifest.exists():
            self.receipt_state = self._classify_missing_manifest()
            return []
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self.receipt_state = "manifest_invalid"
            return []
        if not isinstance(value, list):
            self.receipt_state = "manifest_invalid"
            return []
        self.receipt_state = "ok"
        items: list[ArtifactFile] = []
        for entry in value:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            kind = entry.get("kind")
            if not isinstance(path, str) or not isinstance(kind, str):
                continue
            raw_refs = entry.get("source_refs")
            refs = tuple(ref for ref in raw_refs if isinstance(ref, str)) if isinstance(raw_refs, list) else ()
            items.append(ArtifactFile(path=path, kind=kind, source_refs=refs))
        return items


# ---------------------------------------------------------------------------
# 注册表可见性（V1 / P-1 静态不可用原因）
# ---------------------------------------------------------------------------


def _unavailability(session: Any, agent: AgentRegistry, actor: User) -> str | None:
    if not agent.enabled:
        return "disabled"
    if agent.kind != "zcode" or agent.kind not in ADAPTER_KINDS:
        # d4 只实装 zcode 适配器；其余注册项明确报因（技术文档 §5 首个 = zcode）
        return "adapter_missing"
    if not agent.credential_ref:
        return "credential_missing"
    credential = session.scalar(select(AgentCredential).where(AgentCredential.name == agent.credential_ref))
    if credential is None:
        return "credential_missing"
    # V12（自动交付 §2.4）：run 面声明工具经三重交集收紧后全部失效 → agent
    # 明确报因不可用，而不是让新 run 拿着空白名单静默失败
    # （仅会议面声明的 agent 不受影响——会议面由 meetings 工具面判定）
    # T-R1：声明判定走解析前原样（group: 引用也算声明）——纯未知/停用组
    # 声明解析为空面时同样报因，不静默放行空名单 run
    if declares_run_tools(list(agent.allowed_tools or [])) and not effective_run_tools(
        session, allowed_tools=list(agent.allowed_tools), actor=actor
    ):
        return "tools_unavailable"
    return None


def list_agents(*, actor: User) -> dict[str, Any]:
    with db.session() as session:
        # S2 编排种子懒初始化（goal-d7，沿 gates.json 首访装载先例）：
        # 守卫 + 六模块智能体 + 三角色卡幂等落库
        from fde_api.agents.seeds import ensure_agent_seeds

        ensure_agent_seeds(session)
        session.commit()
        items = []
        for agent in session.scalars(select(AgentRegistry).order_by(AgentRegistry.created_at, AgentRegistry.id)):
            reason = _unavailability(session, agent, actor)
            items.append(
                {
                    "id": agent.id,
                    "kind": agent.kind,
                    "name": agent.name,
                    "enabled": agent.enabled,
                    "capability_tier": agent.capability_tier,
                    "sandbox_profile": agent.sandbox_profile,
                    "max_cost_units": agent.max_cost_units,
                    "max_duration_ms": agent.max_duration_ms,
                    "allowed_tools": list(agent.allowed_tools),
                    "available": reason is None,
                    "unavailable_reason": reason,
                }
            )
        return {"items": items}


# ---------------------------------------------------------------------------
# 发起 run（含幂等/预算/鉴权/脱敏/沙箱/执行/落账全链）
# ---------------------------------------------------------------------------


def _settings():
    return current_app.config["SETTINGS"]


def _error(code: str, message: str, status: int = 400, detail: dict[str, Any] | None = None) -> AgentsServiceError:
    return AgentsServiceError(code, message, status, detail)


def _decrypt_credential(ciphertext: str) -> str:
    """Fernet 解密（ModelPreference 同款派生先例）；只发生在注入时刻。"""
    key = current_app.config.get("MODEL_CREDENTIAL_KEY") or os.environ.get("FDE_MODEL_CREDENTIAL_KEY", "")
    if not key:
        key = urlsafe_b64encode(sha256(_settings().jwt_secret.encode()).digest())
    cipher = Fernet(key.encode() if isinstance(key, str) else key)
    try:
        return cipher.decrypt(ciphertext.encode()).decode("utf-8")
    except InvalidToken as error:
        raise _error("credential_decrypt_failed", "智能体凭据无法解密，请联系系统运维员。", 503) from error


def _credential_env_name(ref: str) -> str:
    return "FDE_AGENT_" + re.sub(r"[^A-Za-z0-9]", "_", ref).upper()


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _platform_month_spent(session: Any) -> int:
    return int(
        session.scalar(
            select(func.coalesce(func.sum(AgentRun.token_cost), 0)).where(AgentRun.created_at >= _month_start())
        )
    )


def _derived_idempotency_key(agent_id: str, project_id: str, solution_id: str | None) -> str:
    raw = f"{agent_id}:{project_id}" + (f":{solution_id}" if solution_id else "")
    return raw[:160]


def _require_run_access(session: Any, actor: User, run_id: str) -> tuple[AgentRun, Project]:
    run = session.get(AgentRun, run_id)
    if run is None:
        raise _error("agent_run_not_found", "agent run 不存在。", 404)
    project = session.get(Project, run.project_id)
    access = project_access(actor, project) if project else None
    if project is None or access is None or not access.can_view:
        raise _error("project_forbidden", "无权访问该 run 所属项目。", 403)
    return run, project


def _serialize_run(session: Any, run: AgentRun, *, detail: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": run.id,
        "project_id": run.project_id,
        "agent_id": run.agent_id,
        "status": run.status,
        "capability_used": run.capability_used,
        "initiated_by_user_id": run.initiated_by_user_id,
        "context_ref": run.context_ref,
        "token_cost": run.token_cost,
        "duration_ms": run.duration_ms,
        "exit_code": run.exit_code,
        "degraded": run.degraded,
        "degraded_reason": run.degraded_reason,
        "fallback_level": run.fallback_level,
        "retry_of": run.retry_of,
        "idempotency_key": run.idempotency_key,
        "cost_owner_type": run.cost_owner_type,
        "cost_owner_id": run.cost_owner_id,
        "handoff_user_id": run.handoff_user_id,
        "difficulty": run.difficulty,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }
    if detail:
        agent = session.get(AgentRegistry, run.agent_id)
        data["agent"] = {"name": agent.name, "kind": agent.kind} if agent else None
        data["artifacts"] = [
            {
                "id": artifact.id,
                "kind": artifact.kind,
                "storage_ref": artifact.storage_ref,
                "sha256": artifact.sha256,
                "reviewed": artifact.reviewed,
                "linked_solution_id": artifact.linked_solution_id,
            }
            for artifact in session.scalars(
                select(AgentArtifact).where(AgentArtifact.run_id == run.id).order_by(AgentArtifact.created_at)
            )
        ]
    return data


def _render_context(
    session: Any, *, project: Project, agent: AgentRegistry, solution: ProjectSolution | None
) -> tuple[str, tuple[str, ...]]:
    """脱敏渲染（红线段）：确认问题 + 骨架 + 知识片段；SanitizationError → 422。"""
    settings = _settings()
    analysis = session.scalar(
        select(ProjectGuidanceAnalysis)
        .where(ProjectGuidanceAnalysis.project_id == project.id, ProjectGuidanceAnalysis.status == "confirmed")
        .order_by(ProjectGuidanceAnalysis.version_number.desc())
    )
    items: list[dict[str, Any]] = list(analysis.key_business_problems_json or []) if analysis else []
    forbidden_terms = [term for term in (settings.agent_forbidden_terms or "").split(",") if term.strip()]
    skeleton = ""
    if solution is not None and isinstance(solution.design_markdown, str):
        skeleton = solution.design_markdown[:4000]
    try:
        rendered = render_masked_context(
            project_code=project.project_code,
            agent_name=agent.name,
            capability=agent.capability_tier,
            confirmed_items=items,
            template_skeleton=skeleton,
            knowledge_snippets=(),
            forbidden_terms=forbidden_terms,
        )
    except SanitizationError as error:
        # fail-closed：禁区词/非法条目拦截在落盘与发起之前（绝不 500 裸抛）
        raise _error(error.code, error.message, 422) from error
    return rendered.text, rendered.problem_refs


def _write_workspace(workspace: Path, *, context_text: str, project_code: str, capability: str) -> None:
    """渲染产物落 workspace（挂进沙箱的唯一目录；红线段三文件）。"""
    (workspace / _OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    (workspace / _CONTEXT_FILE).write_text(context_text, encoding="utf-8")
    header = "\n".join(("# 任务书", "", f"- 项目代号: {project_code}", f"- 能力: {capability}", "请阅读 context.md 与 AGENTS.md 后执行；产物写入 output/ 并附 manifest.json。", ""))
    (workspace / _TASK_FILE).write_text(header[:_RUN_HEADER_LIMIT], encoding="utf-8")
    (workspace / _DISCIPLINE_FILE).write_text(SANDBOX_AGENT_DISCIPLINE, encoding="utf-8")


def _mark_l2(session: Any, run_id: str, reason: str) -> None:
    """A-1：沙箱不可用 → run 落 L2，零计费（token_cost 保持 0）。"""
    with db.session() as write_session, write_session.begin():
        run = write_session.get(AgentRun, run_id)
        if run is None:
            return
        run.status = "failed"
        run.degraded = True
        run.degraded_reason = reason[:32]
        run.fallback_level = "L2"


def _finalize(
    session_factory: Any,
    *,
    run_id: str,
    result,
    known_refs: set[str],
    workspace: Path,
    solution_id: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    """执行终态落账：状态/成本 + 工具留痕 + 产物校验（C-1）+ T2 强制门（U2）。

    校验失败 ≠ 丢证据：能取指纹的产物一律留痕（reviewed=False 永不进终审）；
    文件缺失的产物无指纹（红线：storage_ref + sha256 必须成对完整）只记失败。
    T2 门（goal-d5）：solution 绑定的 completed run =「artifact 提交终审」
    迁移点——无已封存强制评审纪要则迁移被拒：run failed +
    ``review_gate_open``，产物留痕但 linked_solution_id=None（不进终审通道）。
    降级链层级（goal-d6）：降级 completed（D 类）= L1，产物即使过门也
    ``linked_solution_id=None``——强制人工终审不可自动放行，T2 门对 L1 不
    适用（终审通道入口本就是人工）；非 completed 终态 = L2。
    """
    validation_failures: list[dict[str, Any]] = []
    prepared: list[tuple[ArtifactFile, str]] = []
    if result.status == "completed":
        for artifact in result.artifacts:
            problems: list[str] = []
            if artifact.kind not in ARTIFACT_KINDS:
                problems.append("invalid_kind")
            if not artifact.source_refs:
                problems.append("missing_source_refs")
            elif not set(artifact.source_refs) <= known_refs:
                problems.append("unknown_source_refs")
            relative = artifact.path
            if relative.startswith("/") or ".." in Path(relative).parts:
                problems.append("unsafe_path")
            file_path = workspace / _OUTPUT_DIR / relative
            if file_path.exists():
                digest = sha256(file_path.read_bytes()).hexdigest()
                prepared.append((artifact, digest))
            else:
                problems.append("file_missing")
            if problems:
                validation_failures.append({"path": relative, "reasons": problems})

    failed_validation = bool(validation_failures) and result.status == "completed"
    # B#2 回执「写错不重做」（收窄面）：任务书要求 output/ 附 manifest.json——
    # completed + exit 0 + 零声明产物 = 回执缺失/写坏（业务动作已执行、产出
    # 未被清单追踪），独立终态不进 FAILED_STATUSES ⇒ retry_run 拒同键重跑；
    # 声明了产物但校验失败（invalid_kind/缺 source_refs/文件丢失）仍走 C-1
    # 既有合同 failed + retry 恢复（可重试族本就排除外副作用类型）。
    receipt_missing = (
        result.status == "completed"
        and (result.exit_code or 0) == 0
        and not result.artifacts
        and getattr(result, "receipt_state", "ok")
        in ("files_without_manifest", "manifest_invalid")
    )
    gate_open = False
    l1_path = result.status == "completed" and result.degraded  # 决议①：降级 completed = L1
    with session_factory() as session, session.begin():
        run = session.get(AgentRun, run_id)
        gate_open = (
            solution_id is not None
            and result.status == "completed"
            and not result.degraded  # L1 产物本就不自动进终审（强制人工终审），门不适用
            and not failed_validation
            and not t2_gate_satisfied(session, run_id=run_id, solution_id=solution_id)
        )
        if receipt_missing:
            # B#2 回执缺失：业务成功但回执没写——独立终态，拒绝同键重跑（业务
            # 动作不重执行）；人工盘点 output/ 后修复回执或另起任务。
            run.status = "succeeded_but_receipt_invalid"
        elif gate_open:
            # T2 评审门（review_gate_open）：业务面未获放行，维持 failed 终态。
            run.status = "failed"
        elif failed_validation:
            # C-1 既有合同：声明产物校验失败 → failed（retry 族排除外副作用
            # 类型，重试恢复路径由 test_c1_* 钉住）。
            run.status = "failed"
        else:
            run.status = result.status
        run.token_cost = result.token_cost
        run.duration_ms = result.duration_ms
        run.exit_code = result.exit_code
        if result.degraded or failed_validation or gate_open:
            run.degraded = True
        if l1_path:
            run.fallback_level = "L1"
        elif result.status != "completed":
            # 决议②：B 类无产物 → 降级去向 L2 模板填空（自动交付 §3.2「L1 或 L2」取 L2）
            run.fallback_level = "L2"
        if receipt_missing:
            run.degraded_reason = "receipt_missing"
            run.degraded = True
        if failed_validation:
            run.degraded_reason = "artifact_validation_failed"
        elif gate_open:
            run.degraded_reason = "review_gate_open"
        elif result.degraded_reason:
            run.degraded_reason = result.degraded_reason
        for record in result.tool_calls:
            session.add(
                AgentToolCall(
                    run_id=run.id,
                    tool_name=record.tool_name[:120],
                    decision=record.decision,
                    capability=record.capability[:64],
                    reason=record.reason[:120] if record.reason else None,
                    duration_ms=record.duration_ms,
                )
            )
        # 超时/熔断产物不入库（B-1）；completed 的产物含校验失败者一律留痕
        # reviewed=False（C-1：拒绝进终审但不丢证据）；T2 门开着时产物同样
        # 留痕但不挂 solution（不进终审通道，review_gate_open 收口后重试）；
        # L1 降级产物恒不挂 solution（强制人工终审，handoff 后人工收口）
        if result.status == "completed":
            for artifact, digest in prepared:
                session.add(
                    AgentArtifact(
                        run_id=run.id,
                        kind=artifact.kind,
                        storage_ref=f"{run.id}/output/{artifact.path}"[:255],
                        sha256=digest,
                        reviewed=False,
                        linked_solution_id=None if (gate_open or l1_path) else solution_id,
                    )
                )
        # V3 T-P0-1（WB-DEF-1 signoff 死锁）：非降级 completed 且绑定 solution 的
        # run = 产物进入终审通道，pending signoff 在此即时开出（幂等，见
        # agents/signoff.py）。此前唯一开闸点是 handoff_run，而它只收失败 / L1
        # run：正常 completed 的 agent_assisted 方案既不能 handoff 又拿不到
        # pending，export-sow 永久 409。L1（降级 completed）维持「人工接管后再
        # 开闸」的既有语义；失败 / 门拦截（run.status=failed）走 handoff。
        if solution_id is not None and run.status == "completed" and not l1_path:
            ensure_pending_signoff(session, solution_id=solution_id, run_id=run.id)
        session.flush()
        return _serialize_run(session, run, detail=True), validation_failures, gate_open


def _execute_run(
    *,
    actor: User,
    agent: AgentRegistry,
    project: Project,
    solution: ProjectSolution | None,
    idempotency_key: str,
    retry_of: str | None,
    credentials_plaintext: str | None,
    context_text: str,
    problem_refs: tuple[str, ...],
    effective_tools: frozenset[str],
    difficulty: str = "standard",
) -> tuple[dict[str, Any], int]:
    """run 执行主干（start/retry 共用）：落 queued → 沙箱 → 适配器 → 落账。

    ``effective_tools`` 由调用方在发起时刻求三重交集（V3/V12，agents/tools）；
    在跑 run 不中断（§2.4）——允许名单随 run 冻结，运行中不重算。
    """
    settings = _settings()
    run_id = new_uuid()
    workspace_root = Path(settings.agent_workspace_root)
    workspace = workspace_root / run_id
    context_ref = f"{workspace_root.as_posix().strip('/')}/{run_id}/{_CONTEXT_FILE}"

    with db.session() as session, session.begin():
        run = AgentRun(
            id=run_id,
            project_id=project.id,
            agent_id=agent.id,
            initiated_by_user_id=actor.id,
            capability_used=agent.capability_tier,
            status="queued",
            context_ref=context_ref[:255],
            idempotency_key=idempotency_key,
            cost_owner_type="project",
            cost_owner_id=project.id,
            retry_of=retry_of,
            difficulty=difficulty,
        )
        session.add(run)
        # O-3（goal-d7）：一次方案生成 run = 一次「工作台动作」，发起时刻
        # 计（seat 归集 = 发起人；超额只标注不拦截——绝不断供；演练 run
        # 不经本函数，天然零计量）
        seat_quota.record_action(
            session,
            project_id=project.id,
            user_id=actor.id,
            action_type="agent_run",
            ref_id=run_id,
            quota_monthly=int(settings.seat_action_quota_monthly or 0),
        )
        record_event(
            session,
            actor,
            "agent_run_created",
            project,
            {"run_id": run_id, "agent_id": agent.id, "capability": agent.capability_tier, "retry_of": retry_of},
        )

    _write_workspace(workspace, context_text=context_text, project_code=project.project_code, capability=agent.capability_tier)

    backend: SandboxBackend | None = current_app.extensions.get("fde_agent_sandbox_backend")
    if backend is None:
        backend = DockerBackend(settings.sandbox_docker_bin)
    profile = SandboxProfile(
        memory=settings.sandbox_memory,
        cpus=settings.sandbox_cpus,
        pids_limit=settings.sandbox_pids_limit,
        tmpfs_size=settings.sandbox_tmpfs_size,
        egress="allowlist" if agent.sandbox_profile == "egress_allowlist" else "deny",
    )
    allowlist = [item for item in (settings.agent_allowed_egress or "").split(",") if item.strip()]
    try:
        handle = SandboxHandle.create(
            run_id=run_id,
            profile=profile,
            workspace_host=str(workspace),
            image=settings.sandbox_image,
            backend=backend,
            egress_allowlist=allowlist,
        )
    except SandboxError as error:
        _mark_l2(db.session(), run_id, str(error))
        raise _error(
            "agent_unavailable",
            "智能体未就绪（沙箱不可用），已转 L2 模板填空，本次不计费。",
            503,
            detail={"run_id": run_id, "fallback_level": "L2", "reason": str(error)},
        ) from error

    with db.session() as session, session.begin():
        run_row = session.get(AgentRun, run_id)
        if run_row is not None:
            run_row.status = "running"

    adapter = current_app.extensions.get("fde_agent_adapter") or ZcodeAdapter(cli_command=settings.agent_cli_command)
    provider_factory = current_app.extensions.get("fde_agent_event_provider_factory")
    scanner_factory = current_app.extensions.get("fde_agent_output_scanner_factory")
    event_provider: RunEventProvider = (
        provider_factory(run_id, workspace) if provider_factory else NdjsonEventProvider(workspace / _OUTPUT_DIR / _EVENTS_FILE)
    )
    output_scanner: OutputScanner = (
        scanner_factory(run_id, workspace) if scanner_factory else ManifestOutputScanner(workspace / _OUTPUT_DIR)
    )
    credentials = {_credential_env_name(agent.credential_ref or ""): credentials_plaintext} if credentials_plaintext else {}
    ctx = AgentRunContext(
        run_id=run_id,
        project_code=project.project_code,
        capability=agent.capability_tier,
        workspace_host=str(workspace),
        allowed_tools=effective_tools,
        credentials=credentials,
        timeout_ms=agent.max_duration_ms or settings.agent_max_duration_ms,
        max_cost_units=agent.max_cost_units,
    )
    try:
        run_kwargs: dict[str, Any] = {}
        injected_clock = current_app.extensions.get("fde_agent_clock")
        injected_sleeper = current_app.extensions.get("fde_agent_sleeper")
        if injected_clock is not None:
            run_kwargs["clock"] = injected_clock
        if injected_sleeper is not None:
            run_kwargs["sleeper"] = injected_sleeper
        result = adapter.run(ctx, handle, event_provider=event_provider, output_scanner=output_scanner, **run_kwargs)
    except SandboxError as error:
        _mark_l2(db.session(), run_id, str(error))
        raise _error(
            "agent_unavailable",
            "智能体未就绪（沙箱注入失败），已转 L2 模板填空，本次不计费。",
            503,
            detail={"run_id": run_id, "fallback_level": "L2", "reason": str(error)},
        ) from error

    data, failures, gate_open = _finalize(
        db.session,
        run_id=run_id,
        result=result,
        known_refs=set(problem_refs),
        workspace=workspace,
        solution_id=solution.id if solution is not None else None,
    )
    if failures:
        # C-1：先落账（产物 reviewed=False 永不进终审）再抛 422，失败码可见
        # goal-d9 埋点（指标三件）：422 输出扫描拦截事件留痕——产物行承载
        # 「哪份产物被拒」，事件承载「发生了拦截」这一可聚合事实（拦截率）。
        with db.session() as session, session.begin():
            record_event(session, actor, "ai_output_intercepted", project, {
                "run_id": run_id,
                "intercepted_count": len(failures),
                "reasons": sorted({reason for item in failures for reason in item.get("reasons", [])})[:10],
            })
        raise _error(
            "artifact_validation_failed",
            "产物校验未通过，已拒绝进入终审；请回退补录后重试。",
            422,
            detail={"run_id": run_id, "failures": failures},
        )
    if gate_open:
        # U2：T2 强制门——无已封存强制评审纪要，产物提交终审被状态机拒绝
        raise _error(
            "review_gate_open",
            "T2 评审门未放行：请先召开产物评审会并封存纪要，再重试提交。",
            409,
            detail={"run_id": run_id, "gate": "T2", "required": "sealed_mandatory_minutes"},
        )
    return data, 201


def start_run(*, actor: User, agent_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    settings = _settings()
    if set(payload) - {"project_id", "solution_id", "idempotency_key", "difficulty"}:
        raise _error("invalid_request", "请求字段无效。")
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise _error("invalid_request", "project_id 必填。")
    solution_id = payload.get("solution_id")
    if solution_id is not None and (not isinstance(solution_id, str) or not solution_id):
        raise _error("invalid_request", "solution_id 无效。")
    client_key = payload.get("idempotency_key")
    if client_key is not None and (not isinstance(client_key, str) or not client_key or len(client_key) > 160):
        raise _error("invalid_request", "idempotency_key 必须为 ≤160 字符的字符串。")
    difficulty = payload.get("difficulty") or "standard"
    if difficulty not in ("standard", "high"):
        raise _error("invalid_request", "difficulty 仅支持 standard/high。")

    with db.session() as session:
        agent = session.get(AgentRegistry, agent_id)
        if agent is None:
            raise _error("agent_not_found", "智能体不存在。", 404)
        if agent.kind == "persona":
            # 角色卡不是可执行智能体（PartyMode §4.2：静态 persona 配置）——
            # 只在评审会发言（编排中枢到场表），无沙箱 run 通道
            raise _error(
                "persona_not_executable",
                "角色卡（persona）不能发起 run：它只在评审会中提供模拟视角。",
                409,
                detail={"agent_id": agent.id, "kind": agent.kind},
            )
        project = session.get(Project, project_id)
        if project is None:
            raise _error("project_not_found", "项目不存在或无权访问。", 404)
        decision = authorize_ai_capability(user=actor, capability=agent.capability_tier, project=project)
        if not decision.allowed:
            raise _error(decision.reason, "当前账号无权发起该智能体能力。", 403)
        reason = _unavailability(session, agent, actor)
        if reason is not None:
            raise _error("agent_unavailable", "智能体当前不可用。", 409, detail={"reason": reason})
        effective_tools = effective_run_tools(session, allowed_tools=list(agent.allowed_tools or []), actor=actor)
        solution = None
        if solution_id is not None:
            solution = session.get(ProjectSolution, solution_id)
            if solution is None or solution.project_id != project.id:
                raise _error("solution_not_found", "方案不存在或不属于该项目。", 404)
            # D2 合成裁决三（goal-d8，PRD §6.3）：交付包与方案一对一（包 id =
            # solution.id）——已接单且未声明「智能体协同」= 纯人工交付，智能体
            # 不得在该包上发起 run（准入闸，先于 T1 流程门）。未建包（售前段）
            # 与非 accepted 态不受影响（v0.2.0 行为）。
            package = session.get(DeliveryPackage, solution.id)
            if (
                package is not None
                and package.dispatch_status == "accepted"
                and not package.agent_assisted
            ):
                raise _error(
                    "agent_assisted_required",
                    "该方案已有已接单交付包且未声明智能体协同（纯人工交付）："
                    "接单人经 POST /api/v1/dispatch/packages/{id}/agent-assisted "
                    "显式声明后方可启用评审门与溯源联动。",
                    409,
                    detail={"package_id": package.id, "required": "agent_assisted_declaration"},
                )
            if package is not None and package.agent_assisted:
                # O-4 防御兜底：high 档订单不进智能体栈（声明侧已禁，双保险）
                if package.difficulty == "high":
                    raise _error(
                        "difficulty_excludes_agents",
                        "订单难度为 high：按 O-4 三档处理不派发给智能体。",
                        409,
                    )
                # T4 免手报：订单难度映射自动带入 run.difficulty（low→standard /
                # medium→high）；显式手报与订单档位冲突 400（透明化，不静默覆盖）
                order_run_difficulty = (
                    ORDER_DIFFICULTY_RUN_MAP.get(package.difficulty)
                    if package.difficulty is not None
                    else None
                )
                if order_run_difficulty is not None:
                    if (
                        payload.get("difficulty") is not None
                        and payload["difficulty"] != order_run_difficulty
                    ):
                        raise _error(
                            "difficulty_order_conflict",
                            f"订单难度为 {package.difficulty}，run 档位自动带入 "
                            f"{order_run_difficulty}，请勿手报冲突档位（T4 免手报）。",
                            400,
                            detail={
                                "order_difficulty": package.difficulty,
                                "run_difficulty": order_run_difficulty,
                            },
                        )
                    difficulty = order_run_difficulty
            # T1 计划评审强制门（总纲 §2.2 T1，U2 同族状态机级）：带
            # solution 的 run = 进入产物生成——无已封存 T1 纪要侧链该
            # solution 则不放行（retry 不复闸：家族首 run 已被闸）
            if not t1_gate_satisfied(session, solution_id=solution.id):
                raise _error(
                    "t1_gate_open",
                    "T1 计划评审门未放行：请先召开计划评审会（T1 模板）并封存纪要，再发起产物生成。",
                    409,
                    detail={"gate": "T1", "solution_id": solution.id, "required": "sealed_t1_minutes"},
                )

        # T6 高成本 run 前评审（总纲 §2.2 T6，goal-d11）：拟用 agent 的授权
        # 成本档超全局阈值（max_cost_units=0 = 单 run 不限额，即最高成本档，
        # 必触发）且项目未显式关闭时，须先有已封存 T6 纪要侧链该项目——
        # 闸序在协同声明与计划评审之后（先过准入与计划门，再谈性价比）。
        threshold = int(getattr(settings, "t6_review_cost_threshold", 0) or 0)
        agent_cost_tier = int(agent.max_cost_units or 0)
        if (
            threshold > 0
            and (agent_cost_tier == 0 or agent_cost_tier > threshold)
            and not project.t6_review_disabled
            and not t6_gate_satisfied(session, project_id=project.id)
        ):
            raise _error(
                "t6_gate_open",
                "T6 高成本评审门未放行：该 agent 授权成本档超过阈值"
                f"（max_cost_units={'不限额' if agent_cost_tier == 0 else agent_cost_tier} > {threshold}），"
                "请先召开 T6 评审会（性价比评审）并封存纪要，或由项目负责人在项目设置中关闭 T6 评审。",
                409,
                detail={
                    "gate": "T6",
                    "project_id": project.id,
                    "agent_max_cost_units": agent.max_cost_units,
                    "threshold": threshold,
                    "required": "sealed_t6_minutes",
                },
            )

        idempotency_key = client_key or _derived_idempotency_key(agent.id, project.id, solution_id)
        existing = session.scalar(
            select(AgentRun)
            .where(AgentRun.idempotency_key == idempotency_key)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        )
        if existing is not None:
            if existing.status == "completed":
                return _serialize_run(session, existing, detail=True), 200
            if existing.status in IN_FLIGHT_STATUSES:
                return _serialize_run(session, existing, detail=True), 200
            # 终态失败：重试必须走显式 retry（退避/上限语义），start 不悄悄重跑
            raise _error(
                "agent_run_retry_required",
                "该幂等键的上次 run 已失败，请通过 retry 接口显式重试。",
                409,
                detail={"run_id": existing.id, "status": existing.status},
            )

        budget = int(settings.agent_monthly_budget or 0)
        if budget > 0 and _platform_month_spent(session) >= budget:
            raise _error(
                "agent_budget_exhausted",
                "本月智能体用量已达平台预算上限，请联系管理员或下月再试。",
                409,
            )
        pilot_error = pilot.pilot_capacity_error(session, settings)
        if pilot_error is not None:
            code, message, detail = pilot_error
            raise _error(code, message, 409, detail=detail)
        credentials_plaintext = None
        if agent.credential_ref:
            credential = session.scalar(select(AgentCredential).where(AgentCredential.name == agent.credential_ref))
            if credential is None:  # 可用性已闸过；此处兜底防御（mypy 收窄）
                raise _error("agent_unavailable", "智能体凭据缺失。", 409, detail={"reason": "credential_missing"})
            credentials_plaintext = _decrypt_credential(credential.credential_ciphertext)
        context_text, problem_refs = _render_context(session, project=project, agent=agent, solution=solution)

    return _execute_run(
        actor=actor,
        agent=agent,
        project=project,
        solution=solution,
        idempotency_key=idempotency_key,
        retry_of=None,
        credentials_plaintext=credentials_plaintext,
        context_text=context_text,
        problem_refs=problem_refs,
        effective_tools=effective_tools,
        difficulty=difficulty,
    )


# ---------------------------------------------------------------------------
# 溯源 / 工具留痕 / handoff / retry / 成本
# ---------------------------------------------------------------------------


def get_run_detail(*, actor: User, run_id: str) -> dict[str, Any]:
    with db.session() as session:
        run, _project = _require_run_access(session, actor, run_id)
        return _serialize_run(session, run, detail=True)


def list_runs(
    *,
    actor: User,
    project_id: str | None,
    status: str | None,
    created_from: datetime | None,
    created_to: datetime | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Run 列表（T-A8 桌面控制台数据源，只读）。

    - project_id 给定：can_view 闸（局外人 403）；未给定：跨「actor 可见项目」
      聚合——可见性单一权威是 `projects.permissions.visible_project_ids`，
      不在 SQL 里重写第二套规则。
    - 列表行 = `_serialize_run(detail=False)`（纯列读，零关系查询——列表行
      不带详情/产物，防 N+1；详情与工具调用走既有单 run 端点按需取）。
    - 有界分页：取 limit+1 行判定 truncated（诚实标记可能还有更多）。
    """
    with db.session() as session:
        if project_id is not None:
            project = session.get(Project, project_id)
            access = project_access(actor, project) if project else None
            if project is None or access is None:
                raise _error("project_not_found", "项目不存在或无权访问。", 404)
            if not access.can_view:
                raise _error("project_forbidden", "无权访问该项目。", 403)
            scope = AgentRun.project_id == project.id
        else:
            scope = AgentRun.project_id.in_(visible_project_ids(session, actor))
        query = select(AgentRun).where(scope)
        if status:
            query = query.where(AgentRun.status == status)
        if created_from is not None:
            query = query.where(AgentRun.created_at >= created_from)
        if created_to is not None:
            query = query.where(AgentRun.created_at <= created_to)
        rows = list(
            session.scalars(
                query.order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
                .offset(offset)
                .limit(limit + 1)
            )
        )
        truncated = len(rows) > limit
        return {
            "items": [_serialize_run(session, row) for row in rows[:limit]],
            "truncated": truncated,
        }


def list_tool_calls(*, actor: User, run_id: str, decision: str | None) -> dict[str, Any]:
    if decision is not None and decision not in {"allowed", "denied"}:
        raise _error("invalid_request", "decision 仅支持 allowed/denied。")
    with db.session() as session:
        run, _project = _require_run_access(session, actor, run_id)
        query = select(AgentToolCall).where(AgentToolCall.run_id == run.id).order_by(AgentToolCall.created_at)
        if decision is not None:
            query = query.where(AgentToolCall.decision == decision)
        items = [
            {
                "id": row.id,
                "tool_name": row.tool_name,
                "decision": row.decision,
                "capability": row.capability,
                "reason": row.reason,
                "duration_ms": row.duration_ms,
            }
            for row in session.scalars(query)
        ]
        return {"items": items, "denied_count": sum(1 for item in items if item["decision"] == "denied")}


def handoff_run(*, actor: User, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) - {"solution_id"}:
        raise _error("invalid_request", "请求字段无效。")
    solution_id = payload.get("solution_id")
    if solution_id is not None and (not isinstance(solution_id, str) or not solution_id):
        raise _error("invalid_request", "solution_id 无效。")
    with db.session() as session, session.begin():
        run, project = _require_run_access(session, actor, run_id)
        # goal-d6（L1 强制人工终审）：降级 completed（L1）的产物也可转人工收口
        l1_completed = run.status == "completed" and run.fallback_level == "L1"
        if run.status not in FAILED_STATUSES and not l1_completed:
            raise _error("agent_handoff_not_allowed", "只有失败/超时/超预算或 L1 降级完成的 run 才能转人工。", 409)
        if run.handoff_user_id is not None:
            raise _error("agent_handoff_exists", "该 run 已完成人工接管。", 409)
        run.handoff_user_id = actor.id
        run.degraded = True
        if not l1_completed:
            # L1 产物的降级事实保留（自动交付 §3.5「接管后产物仍标 degraded」）：
            # fallback_level=L1 与原 degraded_reason 不被 L3 覆写，接管事实由
            # handoff_user_id + signoff checkpoint + 事件承载
            run.degraded_reason = "ai_manual_handoff"
            run.fallback_level = "L3"
        checkpoint = None
        if solution_id is not None:
            solution = session.get(ProjectSolution, solution_id)
            if solution is None or solution.project_id != project.id:
                raise _error("solution_not_found", "方案不存在或不属于该项目。", 404)
            # goal-d9 触发 run 软链 + 同方案不重复挂检查点：统一走 agents/signoff.py
            # （T-P0-1 后 _finalize / export_sow 兜底与此处共用同一幂等入口）
            checkpoint = ensure_pending_signoff(session, solution_id=solution.id, run_id=run.id)
        record_event(session, actor, "agent_run_handoff", project, {"run_id": run.id, "fallback_level": "L3"})
        session.flush()
        data = _serialize_run(session, run, detail=True)
        data["signoff_checkpoint_id"] = checkpoint.id if checkpoint is not None else None
        return data


def _retry_family(session: Any, key: str) -> list[AgentRun]:
    return list(
        session.scalars(
            select(AgentRun).where(AgentRun.idempotency_key == key).order_by(AgentRun.created_at.asc(), AgentRun.id.asc())
        )
    )


def retry_run(*, actor: User, run_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    if payload:
        raise _error("invalid_request", "retry 不接受请求体。")
    settings = _settings()
    with db.session() as session:
        original, project = _require_run_access(session, actor, run_id)
        if original.status not in FAILED_STATUSES:
            raise _error("agent_retry_not_allowed", "只有失败/超时/超预算的 run 才能重试。", 409)
        agent = session.get(AgentRegistry, original.agent_id)
        if agent is None:
            raise _error("agent_not_found", "智能体不存在。", 404)
        decision = authorize_ai_capability(user=actor, capability=original.capability_used, project=project)
        if not decision.allowed:
            raise _error(decision.reason, "当前账号无权重试该智能体能力。", 403)
        family = _retry_family(session, original.idempotency_key)
        retries_used = len(family) - 1
        if retries_used >= AGENT_MAX_RETRIES:
            raise _error(
                "agent_retry_limit_exceeded",
                "重试次数已达上限（2 次），请转人工处理。",
                409,
                detail={"attempts": len(family)},
            )
        # 平台月度预算闸在 retry 通道同样生效（goal-c CR-012）：start 的月度封顶
        # 若只对新建 run 生效，跨月失败 run 的 retry 会绕过「下月再试」语义
        # （V8 家族重试是原 start 的延续，预算口径不豁免）。
        budget = int(settings.agent_monthly_budget or 0)
        if budget > 0 and _platform_month_spent(session) >= budget:
            raise _error(
                "agent_budget_exhausted",
                "本月智能体用量已达平台预算上限，请联系管理员或下月再试。",
                409,
            )
        # U4 修订回路（技术文档 §6 第 4 条）：门拦截后的会外修订以纪要为准——
        # 家族最新已封存强制纪要存在未决分歧（disputes 非空）时不再自动修订，
        # 升级人工（ai_manual_handoff）
        if original.degraded_reason == "review_gate_open":
            minutes = latest_sealed_mandatory_minutes(
                session, run_id=original.id, idempotency_key=original.idempotency_key
            )
            if minutes is not None and minutes.disputes:
                raise _error(
                    "revision_disputes_open",
                    "评审纪要存在未决分歧，修订回路收口：请转人工处理。",
                    409,
                    detail={"run_id": original.id, "minutes_id": minutes.id},
                )
        backoff_base = int(settings.agent_retry_backoff_base_seconds)
        # 即将创建的是第 retries_used+1 次尝试 → 等待 base*2^retries_used 秒
        # （第 1 次重试等 base，第 2 次等 2*base；上限由家族大小另行拦截）
        required_seconds = backoff_base * (2**retries_used) if backoff_base > 0 else 0
        latest = max(family, key=lambda item: (item.created_at, item.id))
        if required_seconds > 0 and latest.created_at is not None:
            elapsed = (datetime.now(timezone.utc) - latest.created_at).total_seconds()
            if elapsed < required_seconds:
                raise _error(
                    "retry_backoff_not_elapsed",
                    "重试退避未到：指数退避窗口内不能再次发起。",
                    409,
                    detail={"retry_after_ms": int((required_seconds - elapsed) * 1000)},
                )
        # retry 不隐式携带 solution：产物关联只由发起时的显式 solution_id 决定
        solution = None
        credentials_plaintext = None
        if agent.credential_ref:
            credential = session.scalar(select(AgentCredential).where(AgentCredential.name == agent.credential_ref))
            if credential is None:  # 可用性已闸过；此处兜底防御（mypy 收窄）
                raise _error("agent_unavailable", "智能体凭据缺失。", 409, detail={"reason": "credential_missing"})
            credentials_plaintext = _decrypt_credential(credential.credential_ciphertext)
        context_text, problem_refs = _render_context(session, project=project, agent=agent, solution=solution)
        effective_tools = effective_run_tools(session, allowed_tools=list(agent.allowed_tools or []), actor=actor)
        pilot_error = pilot.pilot_capacity_error(session, settings)
        if pilot_error is not None:
            code, message, detail = pilot_error
            raise _error(code, message, 409, detail=detail)

    return _execute_run(
        actor=actor,
        agent=agent,
        project=project,
        solution=solution,
        idempotency_key=original.idempotency_key,
        retry_of=original.id,
        credentials_plaintext=credentials_plaintext,
        context_text=context_text,
        problem_refs=problem_refs,
        effective_tools=effective_tools,
        difficulty=original.difficulty,
    )


# ---------------------------------------------------------------------------
# V4 手动触发面 / run 卡死恢复 / 试点报告（goal-d6）
# ---------------------------------------------------------------------------


def rehearse_fallback(*, actor: User, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """降级链演练（V4「每级可手动触发」）：不跑沙箱不调用模型，创建与真实
    故障同一标注形态的演练 run。零计费；幂等键 ``rehearsal:`` 前缀使试点
    计数与报告可排除。L0=start_run、L3=handoff 既有手动面，此处只补 L1/L2。
    """
    if actor.role != "admin":
        raise _error("rehearsal_forbidden", "降级演练仅系统运维员可执行。", 403)
    if set(payload) - {"level", "project_id"}:
        raise _error("invalid_request", "请求字段无效。")
    level = payload.get("level")
    project_id = payload.get("project_id")
    if level not in {"L1", "L2"}:
        raise _error("invalid_request", "level 仅支持 L1/L2（L0=正常发起、L3=handoff）。")
    if not isinstance(project_id, str) or not project_id:
        raise _error("invalid_request", "project_id 必填。")
    with db.session() as session, session.begin():
        agent = session.get(AgentRegistry, agent_id)
        if agent is None:
            raise _error("agent_not_found", "智能体不存在。", 404)
        project = session.get(Project, project_id)
        if project is None:
            raise _error("project_not_found", "项目不存在。", 404)
        run_id = new_uuid()
        # 形态与真实故障一致：L1=降级 completed（D 类收口形态）；L2=failed（A-1 形态）
        run = AgentRun(
            id=run_id,
            project_id=project.id,
            agent_id=agent.id,
            initiated_by_user_id=actor.id,
            capability_used=agent.capability_tier,
            status="completed" if level == "L1" else "failed",
            context_ref=f"rehearsal://{run_id}",
            token_cost=0,  # 演练零计费
            duration_ms=0,
            exit_code=0 if level == "L1" else None,
            degraded=True,
            degraded_reason="fallback_rehearsal",
            fallback_level=level,
            idempotency_key=(pilot.REHEARSAL_KEY_PREFIX + run_id)[:160],
            cost_owner_type="project",
            cost_owner_id=project.id,
        )
        session.add(run)
        record_event(
            session,
            actor,
            "agent_fallback_rehearsed",
            project,
            {"run_id": run_id, "agent_id": agent.id, "fallback_level": level},
        )
        session.flush()
        return _serialize_run(session, run, detail=True)


def recover_run(*, actor: User, run_id: str) -> dict[str, Any]:
    """run 卡死恢复（d5 挂账）：同步栈 crash 留 queued/running 态 → 发起人或
    管理员显式恢复为 failed（``stuck_recovered``），恢复后 retry/handoff 两路
    既有语义即可走。新鲜窗口闸（``agent_recover_stale_minutes``）防止恢复
    仍在正常执行的 run。
    """
    with db.session() as session, session.begin():
        run, project = _require_run_access(session, actor, run_id)
        if run.status not in IN_FLIGHT_STATUSES:
            raise _error("agent_recover_not_allowed", "只有排队中/执行中的 run 才能恢复。", 409)
        if actor.role != "admin" and run.initiated_by_user_id != actor.id:
            raise _error("agent_recover_forbidden", "只有发起人或系统运维员可以恢复卡死的 run。", 403)
        stale_minutes = int(_settings().agent_recover_stale_minutes or 0)
        if run.updated_at is not None and stale_minutes > 0:
            elapsed = (datetime.now(timezone.utc) - run.updated_at).total_seconds()
            if elapsed < stale_minutes * 60:
                raise _error(
                    "agent_recover_not_stale",
                    "run 仍在新鲜窗口内，不能恢复；请等待超过阈值后再试。",
                    409,
                    detail={"age_seconds": int(elapsed), "stale_minutes": stale_minutes},
                )
        run.status = "failed"
        run.degraded = True
        run.degraded_reason = "stuck_recovered"
        record_event(
            session,
            actor,
            "agent_run_recovered",
            project,
            {"run_id": run.id, "stale_minutes": stale_minutes},
        )
        session.flush()
        return _serialize_run(session, run, detail=True)


def get_pilot_report(*, actor: User) -> dict[str, Any]:
    """试点报告（UM-1）：状态 + 六指标；只出数，O-8/UM-5 阈值人工评（D15）。"""
    if actor.role != "admin":
        raise _error("pilot_report_forbidden", "试点报告仅系统运维员可查。", 403)
    with db.session() as session:
        return pilot.build_report(session, _settings())


def get_seat_quota(*, actor: User, user_id: str | None) -> dict[str, Any]:
    """O-3 配额快照（goal-d7）：本席默认（self），他席 admin-only。透明只读
    ——消耗显示/≤20% 提醒/超额标注/加油包计价入口/30 天重校窗口。"""
    target = actor.id
    if user_id and user_id != actor.id:
        if actor.role != "admin":
            raise _error("quota_scope_forbidden", "他席配额仅系统运维员可查。", 403)
        target = user_id
    with db.session() as session:
        return seat_quota.quota_snapshot(session, _settings(), user_id=target)


def get_cost(*, actor: User, scope: str | None, project_id: str | None) -> dict[str, Any]:
    user = actor
    if scope not in {"project", "seat", "platform"}:
        raise _error("invalid_request", "scope 仅支持 project/seat/platform。")
    if scope in {"seat", "platform"} and user.role != "admin":
        raise _error("cost_scope_forbidden", "席位/平台成本口径仅系统运维员可查。", 403)

    def _monthly(rows: list[AgentRun]) -> dict[str, int]:
        rollup: dict[str, int] = {}
        for row in rows:
            if row.created_at is None:
                continue
            bucket = row.created_at.astimezone(timezone.utc).strftime("%Y-%m")
            rollup[bucket] = rollup.get(bucket, 0) + row.token_cost
        return dict(sorted(rollup.items()))

    with db.session() as session:
        if scope == "project":
            if not project_id:
                raise _error("invalid_request", "scope=project 需要 project_id。")
            project = session.get(Project, project_id)
            access = project_access(user, project) if project else None
            if project is None or access is None or not access.can_view:
                raise _error("project_not_found", "项目不存在或无权访问。", 404)
            rows = list(
                session.scalars(
                    select(AgentRun).where(AgentRun.project_id == project.id).order_by(AgentRun.created_at)
                )
            )
            items = [
                {
                    "run_id": row.id,
                    "agent_id": row.agent_id,
                    "status": row.status,
                    "token_cost": row.token_cost,
                    "duration_ms": row.duration_ms,
                    "initiated_by_user_id": row.initiated_by_user_id,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]
            return {
                "scope": "project",
                "project_id": project.id,
                "items": items,
                "total_token_cost": sum(row.token_cost for row in rows),
                "monthly": _monthly(rows),
            }

        rows = list(session.scalars(select(AgentRun).order_by(AgentRun.created_at)))
        if scope == "seat":
            by_user: dict[str, dict[str, Any]] = {}
            for row in rows:
                bucket = by_user.setdefault(row.initiated_by_user_id, {"user_id": row.initiated_by_user_id, "runs": 0, "token_cost": 0})
                bucket["runs"] += 1
                bucket["token_cost"] += row.token_cost
            return {
                "scope": "seat",
                "items": sorted(by_user.values(), key=lambda item: item["user_id"]),
                "total_token_cost": sum(row.token_cost for row in rows),
                "monthly": _monthly(rows),
            }
        return {
            "scope": "platform",
            "total_runs": len(rows),
            "total_token_cost": sum(row.token_cost for row in rows),
            "monthly": _monthly(rows),
        }
