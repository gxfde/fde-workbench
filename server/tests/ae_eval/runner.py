"""AE1-WP5-B 评测 runner：冻结任务集公开 5 任务 × 3 次独立运行 → 落盘 → 评分。

纪律对齐（53 号 §2.3 / 05 号）：
- **3 次独立运行**（05:45/05:47）：运行间重置执行台账（action_executions/
  compensations/logs 三表，FK RESTRICT 子先父后）＋Mock 桩（收件箱/计数器），
  同一冻结输入逐字重放——运行独立性＝**状态隔离**，不是复放链（复放链是
  任务内 replay2/replay3，两者在报告分列）。运行间清台账是评测隔离装置，
  不触生产 append-only 语义（后者由 WP4 业务面钉守护）；
- **分母不许改**（05:54）：runs 次运行全部入记录入报告——提交异常折叠为
  诚实 failed 记录形态（error.code / 基础设施失败入 note 归因）；
- **字面 ID 世界**：84 条冻结断言把 ``audit.org_id == "test-org-001"``、
  ``audit.actor_user_id == "test-user-001"`` 逐字钉死（逐字不可改）——评测
  世界以占位串为**真实主键**落行（Org/User/Project PK 均 String(36)），
  而非「跑真 ID 再改记录」；
- **评分器只消费落盘记录**（05:41）：runner 只产记录；判定一律由调用方
  落盘后经 ``scorer.score_records`` 消费；
- **门槛口径**（51 号 §4.2）：「AE1 门禁：T4 成功率 ≥90% AND S-AE 全通过」
  ——报告信封标注 **「未冻结（附录草案口径）」**（53 号 §2.3：不得声称
  「已达成 05 号 AE1 门禁」）；
- **桩端口注入面**：runner 桩绑 **ephemeral 端口**（跨 worker 与固定端口桩
  文件共存），实际端口注入白名单快照 base_url——装置级快照构造（非运行时
  篡改），与 WP3 ``_live_gates(wb_port)`` 先例同一语义。

KD-01 同构登记：``mock.erp`` query_inventory 上游 ``{items:[…]}`` → items[0]
展开 ``{sku,quantity,available}``（适配层 ``connectors.normalize_output``；
available 取桩侧事实源零派生）——T4-002/005 冻结断言可判定所需，登记入
53 号 WP5 docs 条目，不触白名单/任务集/契约三冻结件。
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select, text

import _ae_mock_stack as _mock_stack_module
from ae_eval.records import RunRecord
from conftest import INITIAL_PASSWORD
from fde_api.action_execution import connectors
from fde_api.action_execution import service as ae_service
from fde_api.action_execution.errors import ActionExecutionError
from fde_api.action_execution.models import ActionCompensation, ActionExecution, ActionExecutionLog
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.control.models import AutomationApproval
from fde_api.ontology.models import OntologyTerm
from fde_api.orgs.models import ORG_TYPE_ENTERPRISE, Org
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, Project

__all__ = [
    "ORG_ID",
    "PROJECT_ID",
    "RUNS",
    "USER_ID",
    "build_report",
    "load_public_tasks",
    "provision_pinned_world",
    "run_public_eval",
    "write_report",
]

SERVER_ROOT = Path(__file__).resolve().parents[2]
TASKSET_PATH = Path(__file__).resolve().parent / "taskset_v1.json"
SNAPSHOT_PATH = SERVER_ROOT / "src" / "fde_api" / "action_execution" / "whitelist.json"

#: 字面 ID 世界（冻结断言逐字钉死的占位串＝真实主键）。
ORG_ID = "test-org-001"
USER_ID = "test-user-001"
PROJECT_ID = "test-project-001"

#: 3 次独立运行（05:45；唯一任务数与运行次数在报告分列——05:47）。
RUNS = 3

#: T4-002/T4-005 库存观测的 sku（取任务集 input.params 事实源）。
_TASK_SKU = {"T4-002": "test-sku-001", "T4-005": "test-sku-002"}


def load_public_tasks() -> list[dict[str, Any]]:
    """公开集 5 任务（冻结任务集 byte 一致副本；input 逐字即场景输入）。"""
    payload = json.loads(TASKSET_PATH.read_text(encoding="utf-8"))
    tasks = [task for task in payload["tasks"] if str(task["id"]).startswith("T4-0")]
    if [str(task["id"]) for task in tasks] != ["T4-001", "T4-002", "T4-003", "T4-004", "T4-005"]:
        raise ValueError("公开集任务清单漂移（冻结件 v1 应恰为 T4-001..T4-005）")
    return tasks


# ---- 生产等价装配 --------------------------------------------------------------


def _live_gates(
    token: str | None,
    *,
    wb_port: int | None = None,
    erp_port: int | None = None,
    email_port: int | None = None,
) -> tuple[Any, Any]:
    """白名单门＋真 HTTP dispatch（装置级快照构造——同 WP3
    ``test_ae_connector_allowlist._live_gates(wb_port)`` 先例语义：生产门仍用
    冻结快照原文，此处仅把本进程桩的实际端口注入快照 base_url）。"""
    snapshot = connectors.load_whitelist(str(SNAPSHOT_PATH))
    for conn in snapshot["connectors"]:
        cid = conn.get("id")
        if wb_port is not None and cid in {"workbench.ontology", "workbench.workflow"}:
            conn["base_url"] = f"http://127.0.0.1:{wb_port}"
        if erp_port is not None and cid == "mock.erp":
            conn["base_url"] = f"http://127.0.0.1:{erp_port}"
        if email_port is not None and cid == "mock.email":
            conn["base_url"] = f"http://127.0.0.1:{email_port}"
    gate = connectors.ConnectorWhitelist(snapshot)
    dispatch = connectors.HttpDispatch(
        whitelist=gate, token=token, timeout_seconds=5.0, whitelist_snapshot=snapshot
    )
    return gate, dispatch


def provision_pinned_world(db_session: Any) -> dict[str, Any]:
    """字面 ID 世界：org/user/project 三行 PK 逐字钉任务集占位串＋两条本体术语。"""
    # 字面键残留防清（同会话重跑防护；FK 子先父后）
    db_session.execute(text("DELETE FROM ontology_terms WHERE project_id = :p"), {"p": PROJECT_ID})
    db_session.execute(text("DELETE FROM projects WHERE id = :p"), {"p": PROJECT_ID})
    db_session.execute(text("DELETE FROM users WHERE id = :u"), {"u": USER_ID})
    db_session.execute(text("DELETE FROM orgs WHERE id = :o"), {"o": ORG_ID})
    db_session.commit()

    org = Org(id=ORG_ID, org_type=ORG_TYPE_ENTERPRISE, name="AE1 评测隔离企业（test- 占位）")
    user = User(
        id=USER_ID,
        username=USER_ID,
        display_name="AE1 评测发起人（test- 占位）",
        role="project_lead",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
        org_id=ORG_ID,
    )
    template = IndustryTemplate(name="AE1 评测模板", industry_name="制造")
    template_version = IndustryTemplateVersion(
        template=template,
        name=template.name,
        industry_name=template.industry_name,
        description="",
        version_number=1,
        status="published",
        published_by=user,
    )
    project = Project(
        id=PROJECT_ID,
        project_code="test-project-001",
        name="AE1 评测项目（test- 占位）",
        enterprise_code="AE1 评测企业·制造·test-project-001",
        leader=user,
        source_template_version=template_version,
        template_snapshot={},
        research_snapshot={},
        planned_start_date=date(2026, 8, 22),
        org_id=ORG_ID,
    )
    # 分阶段 flush（org→user→project 无 ORM relationship，unit of work 不保证
    # 插入序——字符串外键须按依赖次序显式落，WP2「同一 session 变量」教训同源）
    db_session.add(org)
    db_session.flush()
    db_session.add(user)
    db_session.flush()
    db_session.add_all([template, template_version, project])
    db_session.flush()
    db_session.add_all(
        [
            OntologyTerm(
                project_id=PROJECT_ID,
                term="Equipment",
                definition="设备类本体",
                term_type="entity",
                status="confirmed",
            ),
            OntologyTerm(
                project_id=PROJECT_ID,
                term="Sensor",
                definition="传感类本体",
                term_type="entity",
                status="confirmed",
            ),
        ]
    )
    db_session.commit()
    return {"org": org, "user": user, "project": project}


REVIEWER_ID = "test-reviewer-001"  # 评审 P15：四眼闸第二人（复核人≠发起人）


def _ensure_reviewer(db_session: Any) -> str:
    """字面 ID 世界的复核人行（不存在即建；org 同 test-org-001）。"""
    from fde_api.auth.models import User as _User

    if db_session.get(_User, REVIEWER_ID) is None:
        db_session.add(
            _User(
                id=REVIEWER_ID,
                username=REVIEWER_ID,
                display_name="AE1 评测复核人（test- 占位）",
                role="admin",
                password_hash=hash_password(INITIAL_PASSWORD),
                must_change_password=False,
                is_active=True,
                org_id=ORG_ID,
            )
        )
        db_session.commit()
    return REVIEWER_ID


def _make_email_approval(db_session: Any, params: dict, risk_level: int) -> str:
    """T4-003 审批单直插（WP3 先例同构；指纹＝params canonical sha256）。

    每轮运行独立签发（审批面不属运行隔离清理范围；expires 1 小时内有效）。"""
    canonical = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    row = AutomationApproval(
        id=str(uuid.uuid4()),
        run_id=None,
        workflow_node_run_id=None,
        project_id=PROJECT_ID,
        requested_by_user_id=USER_ID,
        reviewed_by_user_id=_ensure_reviewer(db_session),  # 评审 P15：四眼闸形式（复核人≠发起人）
        request_key=f"ae1-eval-t4-003-{uuid.uuid4().hex[:12]}",
        capability="action_execution.invoke",
        tool_name="action_execution.execute",
        risk_level=risk_level,
        status="approved",
        arguments_json=params,
        arguments_sha256=sha256(canonical.encode("utf-8")).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(row)
    db_session.commit()
    return row.id


def reset_execution_ledger(db_session: Any) -> None:
    """运行隔离：清执行三表（FK RESTRICT 子先父后）——同幂等键可重新首跑。"""
    db_session.execute(delete(ActionExecutionLog))
    db_session.execute(delete(ActionCompensation))
    db_session.execute(delete(ActionExecution))
    db_session.commit()


# ---- 外部系统状态观测（白名单 idempotency_assertion 的观测面） -------------------


def _http_get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=5.0) as response:
        return json.loads(response.read().decode("utf-8"))


def _ontology_terms_count(db_session: Any) -> int:
    return int(
        db_session.scalar(
            select(func.count()).select_from(OntologyTerm).where(OntologyTerm.project_id == PROJECT_ID)
        )
    )


def _workflow_definitions_count(db_session: Any) -> int:
    return int(
        db_session.scalar(
            text("SELECT count(*) FROM workflow_definitions WHERE project_id = :p"), {"p": PROJECT_ID}
        )
    )


def _inventory_url(stack: _mock_stack_module.MockStack, sku: str) -> str:
    return f"http://127.0.0.1:{stack.erp_port}/mock-erp/inventory?{urllib.parse.urlencode({'sku': sku})}"


def _mailbox_url(stack: _mock_stack_module.MockStack) -> str:
    return f"http://127.0.0.1:{stack.email_port}/mock-email/inbox"


def _snapshot_state(task_id: str, db_session: Any, stack: _mock_stack_module.MockStack) -> dict[str, Any]:
    """运行前外部状态快照（T4-003 只看运行后收件箱——写副作用锚在 after）。"""
    if task_id == "T4-001":
        return {"terms_count": _ontology_terms_count(db_session)}
    if task_id in _TASK_SKU:
        return {"inventory": _http_get_json(_inventory_url(stack, _TASK_SKU[task_id]))}
    if task_id == "T4-004":
        return {"wf_count": _workflow_definitions_count(db_session)}
    return {}


def _external_state(
    task_id: str, *, before: dict[str, Any], after: dict[str, Any], stack: _mock_stack_module.MockStack
) -> dict[str, Any]:
    """harness 对外部系统状态的只读观测（任务集 §4 ``task.external_state.*``）。"""
    if task_id == "T4-001":
        return {"ontology_terms_unchanged": before["terms_count"] == after["terms_count"]}
    if task_id in _TASK_SKU:
        return {"inventory_unchanged": before["inventory"] == after["inventory"]}
    if task_id == "T4-003":
        items = _http_get_json(_mailbox_url(stack)).get("items") or []
        return {
            "mailbox_count": len(items),
            "mailbox_first_subject": items[0].get("subject") if items else None,
        }
    if task_id == "T4-004":
        return {"workflow_definitions_unchanged": before["wf_count"] == after["wf_count"]}
    raise ValueError(f"公开集外任务无观测面：{task_id}")


# ---- 执行链 --------------------------------------------------------------------


def _submit_attempt(actor: Any, payload: dict[str, Any], gate: Any, dispatch: Any) -> dict[str, Any]:
    """单次提交——失败按 05:54 保留总表：异常折叠为诚实 failed 记录形态
    （闭集码＋message 入 error；基础设施失败标 ``_infra_exception`` 由
    runner 转写进 RunRecord.note）。audit 置空对象＝审计完备率腿诚实扣减。"""
    try:
        return ae_service.submit_action(
            actor=actor, payload=payload, whitelist_gate=gate, dispatch=dispatch
        )
    except ActionExecutionError as exc:
        return {
            "execution_id": None,
            "idempotency_key": str(payload.get("idempotency_key")),
            "status": "failed",
            "output": None,
            "error": {"code": exc.code, "message": exc.message},
            "audit": {},
            "cost": {"tool_calls": 0, "duration_ms": 0, "estimated_usd": 0.0},
            "rollback": {"supported": False, "execution_id": None},
        }
    except Exception as exc:  # 基础设施失败归因面（诚实保留总表，见上）
        return {
            "execution_id": None,
            "idempotency_key": str(payload.get("idempotency_key")),
            "status": "failed",
            "output": None,
            "error": None,
            "audit": {},
            "cost": {"tool_calls": 0, "duration_ms": 0, "estimated_usd": 0.0},
            "rollback": {"supported": False, "execution_id": None},
            "_infra_exception": type(exc).__name__,
        }


def _run_task_once(
    db_session: Any,
    actor: Any,
    gate: Any,
    dispatch: Any,
    stack: _mock_stack_module.MockStack,
    task: dict[str, Any],
    run_index: int,
) -> RunRecord:
    task_id = str(task["id"])
    payload = dict(task["input"])  # 冻结输入逐字（T4-003 仅 approval_id 运行时绑定）
    if task_id == "T4-003":
        payload["approval_id"] = _make_email_approval(
            db_session, payload["params"], int(payload["risk_level"])
        )
    needs_replay = "replay_expectation" in (task.get("expected_output") or {})
    before = _snapshot_state(task_id, db_session, stack)
    attempts: dict[str, dict[str, Any]] = {"first": _submit_attempt(actor, payload, gate, dispatch)}
    if needs_replay:
        for slot in ("replay2", "replay3"):
            attempts[slot] = _submit_attempt(actor, payload, gate, dispatch)
    after = _snapshot_state(task_id, db_session, stack)
    infra = sorted(
        {
            attempt["_infra_exception"]
            for attempt in attempts.values()
            if attempt.get("_infra_exception") is not None
        }
    )
    return RunRecord(
        task_id=task_id,
        run_index=run_index,
        attempts=attempts,
        external_state=_external_state(task_id, before=before, after=after, stack=stack),
        note=f"infrastructure_error: {','.join(infra)}" if infra else "",
    )


def run_public_eval(
    *,
    db_session: Any,
    actor: Any,
    test_settings: Any,
    stack: _mock_stack_module.MockStack,
    wb_port: int,
    runs: int = RUNS,
) -> list[RunRecord]:
    """公开集 5 任务 × runs 次独立运行 → RunRecord 列表（调用方落盘后交 scorer）。

    每轮运行前：清执行台账（同幂等键才能重新首跑）＋重置 Mock 桩（收件箱
    清零——T4-003 的 ``mailbox_count == 1`` 锚按轮独立成立）。
    """
    tasks = load_public_tasks()
    token = issue_access_token(actor, test_settings)
    gate, dispatch = _live_gates(
        token,
        wb_port=wb_port,
        erp_port=stack.erp_port,
        email_port=stack.email_port,
    )
    records: list[RunRecord] = []
    for run_index in range(1, runs + 1):
        reset_execution_ledger(db_session)
        stack.reset()
        for task in tasks:
            records.append(_run_task_once(db_session, actor, gate, dispatch, stack, task, run_index))
    return records


# ---- 报告信封 ------------------------------------------------------------------


def build_report(result: dict[str, Any]) -> dict[str, Any]:
    """评测报告信封：门槛按 53 号 §2.3 标注**未冻结（附录草案口径）**。"""
    return {
        "taskset": result["taskset"],
        "counts": result["counts"],
        "metrics": result["metrics"],
        "task_scores": result["task_scores"],
        "gate": {
            "reference": "51-ae-evaluation.md §4.2：AE1 门禁＝T4 成功率 ≥90% AND S-AE 全通过",
            "status": "未冻结（附录草案口径）",
            "note": "53 号 §2.3：出口报告按草案口径标注，不声称「已达成 05 号 AE1 门禁」；05:54 分母不许改",
        },
    }


def write_report(report: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return target
