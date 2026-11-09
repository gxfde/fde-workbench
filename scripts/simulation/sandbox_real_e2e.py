"""V3.2 G9b · 宿主真机通道运维脚本（bootstrap / smoke / single / e2e）。

**这是裸跑态（宿主 Windows 直跑服务端进程）的运维工具**——容器内 server
spawn 不到宿主 zcode（T-Z1 裁定 A 的前提），因此真机执行面只在宿主裸跑态可用。

跑法（宿主 Windows，server venv）：

```bash
cd server
PYTHONPATH=src python ../scripts/simulation/sandbox_real_e2e.py bootstrap   # 一次性闸引导（幂等）
PYTHONPATH=src python ../scripts/simulation/sandbox_real_e2e.py smoke       # zcode CLI 冒烟（约 1 分钟）
PYTHONPATH=src python ../scripts/simulation/sandbox_real_e2e.py single      # 单相位真跑（约 8 分钟）
PYTHONPATH=src python ../scripts/simulation/sandbox_real_e2e.py e2e         # 全链 + 真模型评估（约 30 分钟）
```

前置环境变量（本脚本不代设，跑前自行导出）：

```bash
export FDE_AGENT_HOST_CHANNEL_ENABLED=1
export FDE_AGENT_HOST_ZCODE_BIN=<ZCode.exe 绝对路径>
export FDE_AGENT_HOST_ZCODE_CJS=<zcode.cjs 绝对路径>
export FDE_AGENT_WORKSPACE_ROOT=<宿主可写目录，须在仓库与真相层之外>
export FDE_AGENT_MAX_DURATION_MS=900000          # 真实相位常用 5–10 分钟
export FDE_DEEPSEEK_SIMULATION_EVALUATION_MODEL=<provider 实际型号>
export FDE_DATABASE_URL=<宿主可达的活库 URL>
```

**边界**：合成场景内容，无任何真实客户资料；T1/T2 纪要为如实记录
（沙箱平台资产 + 蔡工授权原文），不伪造人工决定；工作区锚定
``FDE_AGENT_WORKSPACE_ROOT``（拒绝清单校验照常生效）。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER_ROOT / "src"))

CREDENTIAL_SLOT = "sim-host-zcode-slot"
CAPABILITIES = (
    "agent.module.presales",
    "agent.module.solution",
    "agent.module.deployment",
    "agent.module.acceptance",
)
SCENARIO_KEY = "CASE-A-QUALITY-TRACE"


def _require_channel_env() -> None:
    missing = [
        name
        for name in (
            "FDE_AGENT_HOST_CHANNEL_ENABLED",
            "FDE_AGENT_HOST_ZCODE_BIN",
            "FDE_AGENT_HOST_ZCODE_CJS",
            "FDE_AGENT_WORKSPACE_ROOT",
        )
        if not str(os.environ.get(name) or "").strip()
    ]
    if missing:
        raise SystemExit(f"缺少宿主通道环境变量：{', '.join(missing)}（见文件头 runbook）")


def bootstrap() -> int:
    """一次性闸引导（幂等）：注册表种子 + 凭据槽位 + 沙箱 T1/T2 正规封存。"""
    from sqlalchemy import select

    from fde_api.agents.models import AgentCredential, AgentRegistry
    from fde_api.agents.seeds import ensure_agent_seeds
    from fde_api.auth.models import User
    from fde_api.extensions import db
    from fde_api.simulation import sandbox
    from fde_api.simulation.seeds import seed_scenarios

    with db.session() as session:
        created = ensure_agent_seeds(session)
        session.commit()
        print(f"registry_seed_created={created}")
        actor = session.scalar(select(User).where(User.role == "admin").limit(1))
        if actor is None:
            raise SystemExit("活库无 admin 用户。")
        project = sandbox.ensure_sandbox_project(actor=actor, session=session)
        print(f"sandbox_project={project.project_code}")

        slot = session.scalar(
            select(AgentCredential).where(AgentCredential.name == CREDENTIAL_SLOT)
        )
        if slot is None:
            from base64 import urlsafe_b64encode
            from hashlib import sha256

            from cryptography.fernet import Fernet

            from fde_api.config import Settings

            secret = str(os.environ.get("FDE_MODEL_CREDENTIAL_KEY") or "")
            key = secret or urlsafe_b64encode(
                sha256(Settings().jwt_secret.encode()).digest()
            )
            cipher = Fernet(
                key if isinstance(key, bytes) else str(key).encode()
            ).encrypt(b"host-channel-slot-unused-by-real-adapter").decode()
            session.add(AgentCredential(name=CREDENTIAL_SLOT, credential_ciphertext=cipher))
            print("credential_slot_created=1")
        for tier in CAPABILITIES:
            agent = session.scalar(
                select(AgentRegistry).where(
                    AgentRegistry.kind == "zcode",
                    AgentRegistry.capability_tier == tier,
                )
            )
            if agent is not None and not agent.credential_ref:
                agent.credential_ref = CREDENTIAL_SLOT
                print(f"credential_ref_set={tier}")
        session.commit()

        seed_scenarios(session)
        session.commit()

    from fde_api.meetings.service import (
        close_meeting,
        create_meeting,
        t1_gate_satisfied,
        t2_gate_satisfied,
    )
    from fde_api.simulation.scenarios.loader import load_view

    with db.session() as session:
        scenario = _scenario_row()
        content = dict(scenario.content_json or {})
        customer_view = load_view(content, None, "customer")
        disclosed = [
            dict(fact)
            for fact in ((customer_view.get("hidden") or {}).get("facts") or [])
        ]
        actor = session.scalar(select(User).where(User.role == "admin").limit(1))
        project = sandbox_project_row(session)
        projection = sandbox.project_scenario(
            session=session,
            project=project,
            scenario_key=scenario.scenario_key,
            variant=scenario.variant,
            split=scenario.split,
            brief=tuple(load_view(content, None, "tester").get("brief") or []),
            disclosed=disclosed,
            actor=actor,
        )
        solution_id = str(projection["solution_id"])

        if t1_gate_satisfied(session, solution_id=solution_id):
            print("t1_gate=already_satisfied")
        else:
            meeting = create_meeting(
                actor=actor,
                payload={
                    "project_id": project.id,
                    "template_id": "T1-lite",
                    "solution_id": solution_id,
                },
            )
            minutes = close_meeting(
                actor=actor,
                meeting_id=meeting["id"],
                payload={
                    "consensus": [
                        {
                            "text": _T1_MINUTES_TEXT,
                            "source_refs": [solution_id],
                        }
                    ],
                    "disputes": [],
                    "todos": [],
                },
            )
            print(f"t1_sealed sha={str(minutes.get('sealed_sha256'))[:12]}")
        if t2_gate_satisfied(session, run_id="none", solution_id=solution_id):
            print("t2_gate=already_satisfied")
        else:
            meeting = create_meeting(
                actor=actor,
                payload={
                    "project_id": project.id,
                    "template_id": "T2-lite",
                    "solution_id": solution_id,
                },
            )
            minutes = close_meeting(
                actor=actor,
                meeting_id=meeting["id"],
                payload={
                    "consensus": [
                        {
                            "text": _T2_MINUTES_TEXT,
                            "source_refs": [solution_id],
                        }
                    ],
                    "disputes": [],
                    "todos": [],
                },
            )
            print(f"t2_sealed sha={str(minutes.get('sealed_sha256'))[:12]}")
    print("bootstrap done")
    return 0


_T1_MINUTES_TEXT = (
    "模拟训练场沙箱方案（SIM-V32-LAB）计划评审放行：本方案为 V3.2 交付模拟训练场"
    "平台资产，仅承载合成场景投影（无真实客户资料）；真机执行经宿主 zcode 通道，"
    "2026-11-09 由蔡工在 V3.2 会话内明示授权实施（原话：剩余两闸带着我去实施落地）。"
    "产物一律为模拟域摘录+指针，不进真相层。"
)
_T2_MINUTES_TEXT = (
    "模拟训练场沙箱产物评审放行：沙箱产物为合成场景的草稿交付物（draft，"
    "requires_human_confirmation），只作模拟域摘录回读用于评估训练，"
    "不进真实交付、不触发任何对外动作；2026-11-09 蔡工授权随"
    "「两闸实施落地」一并放行（含宿主 zcode 通道真机产物）。"
)


def smoke() -> int:
    """zcode CLI 冒烟：生产 ``run_host_channel`` 契约直跑临时工作区。"""
    import time as _time

    from fde_api.agents.adapter import AgentRunContext
    from fde_api.agents.execution_policy import policy_snapshot
    from fde_api.agents.host_channel import HostChannelSettings, run_host_channel
    from fde_api.agents.service import ManifestOutputScanner

    root = Path(str(os.environ["FDE_AGENT_WORKSPACE_ROOT"]))
    stamp = _time.strftime("%Y%m%d-%H%M%S")
    ws = root / f"smoke-{stamp}"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "task.md").write_text(
        "# 冒烟任务（合成内容，无任何真实客户资料）\n\n"
        "请在当前工作区完成以下两件事，除此之外不做任何其他动作：\n\n"
        "1. 创建 `output/result.md`，内容恰好一行：`OK`\n"
        "2. 创建 `output/manifest.json`，内容为一个 JSON 数组："
        '`[{"path": "result.md", "kind": "doc"}]`\n',
        encoding="utf-8",
    )
    timeout_ms = 300_000
    ctx = AgentRunContext(
        run_id=f"smoke-{stamp}",
        project_code="SIM-SMOKE",
        capability="smoke",
        workspace_host=str(ws),
        allowed_tools=frozenset({"read_file"}),
        credentials={},
        timeout_ms=timeout_ms,
        max_cost_units=0,
        policy_snapshot_hash=policy_snapshot(
            provider="host_channel",
            workspace_ref=str(ws),
            allowed_tools=["read_file"],
            timeout_ms=timeout_ms,
            max_cost_units=0,
        ),
    )
    settings = HostChannelSettings(
        zcode_bin=str(os.environ["FDE_AGENT_HOST_ZCODE_BIN"]),
        cjs_path=str(os.environ["FDE_AGENT_HOST_ZCODE_CJS"]),
    )
    scanner = ManifestOutputScanner(ws / "output")
    print(f"workspace: {ws}")
    result = run_host_channel(ctx, settings, output_scanner=scanner)
    print(
        f"status={result.status} exit={result.exit_code} "
        f"dur={result.duration_ms}ms receipt={scanner.receipt_state} "
        f"artifacts={[a.path for a in result.artifacts]}"
    )
    return 0 if result.status == "completed" else 1


def _scenario_row():
    from sqlalchemy import select

    from fde_api.extensions import db
    from fde_api.simulation.models import SimulationScenario

    row = db.session().scalar(
        select(SimulationScenario).where(
            SimulationScenario.scenario_key == SCENARIO_KEY,
            SimulationScenario.variant == "normal",
        )
    )
    if row is None:
        raise SystemExit(f"场景未物化：{SCENARIO_KEY} normal（先跑 bootstrap）")
    return row


def sandbox_project_row(session):
    from sqlalchemy import select

    from fde_api.simulation.sandbox import SANDBOX_PROJECT_CODE
    from fde_api.workbench.models import Project

    row = session.scalar(select(Project).where(Project.project_code == SANDBOX_PROJECT_CODE))
    if row is None:
        raise SystemExit("沙箱项目不存在（先跑 bootstrap）")
    return row


def _adapter_ctx(run_id: str):
    from fde_api.simulation.adapters.base import AdapterContext
    from fde_api.simulation.scenarios.loader import load_view

    scenario = _scenario_row()
    content = dict(scenario.content_json or {})
    customer_view = load_view(content, None, "customer")
    disclosed = [
        dict(fact)
        for fact in ((customer_view.get("hidden") or {}).get("facts") or [])
    ]
    return AdapterContext(
        run_id=run_id,
        scenario_key=scenario.scenario_key,
        variant=scenario.variant,
        split=scenario.split,
        seed=42,
        brief=tuple(load_view(content, None, "tester").get("brief") or []),
        disclosed=tuple(disclosed),
    )


def single() -> int:
    """单相位真跑（analysis）：隔离验证真实执行面。"""
    from uuid import uuid4

    from fde_api.simulation.adapters.real import RealAgentAdapter

    run_id = f"sim-real-{uuid4().hex[:8]}"
    adapter = RealAgentAdapter()
    started = time.monotonic()
    outcome = adapter.analyze(_adapter_ctx(run_id))
    print(f"analyze done in {time.monotonic() - started:.0f}s")
    print("integration_status:", outcome.get("integration_status"))
    print("agent_status:", outcome.get("agent_status"))
    print("artifacts:", [a.get("name") for a in (outcome.get("artifacts") or [])])
    return 0 if outcome.get("integration_status") == "exercised" else 1


def e2e() -> int:
    """全链真机 E2E：adapter_mode=real 七相位 + 真模型评估（L-B server）。"""
    import json

    from sqlalchemy import select

    from fde_api.auth.models import User
    from fde_api.extensions import db
    from fde_api.simulation import evaluator, run_service
    from fde_api.simulation.improvement_service import analyze_run
    from fde_api.simulation.models import SimulationEvaluation
    from fde_api.simulation.seeds import seed_scenarios

    with db.session() as session:
        seed_scenarios(session)
        session.commit()
        actor = session.scalar(select(User).where(User.role == "admin").limit(1))
        scenario = _scenario_row()
    print(f"scenario={scenario.id} starting real run...", flush=True)
    run = run_service.create_run(
        actor=actor,
        payload={
            "scenario_id": scenario.id,
            "adapter_mode": "real",
            "execute": True,
            "config": {"max_rounds": 5},
        },
    )
    print("run_status:", run.get("status"), flush=True)
    if run.get("error"):
        print("run_error:", json.dumps(run["error"], ensure_ascii=False), flush=True)

    report = evaluator.evaluate_run(actor=actor, run_id=run["id"], model_mode="server")
    findings = analyze_run(actor=actor, run_id=run["id"])
    with db.session() as session:
        rows = session.scalars(
            select(SimulationEvaluation).where(SimulationEvaluation.run_id == run["id"])
        ).all()
        for row in rows:
            print(
                f"eval_layer={row.layer} evaluator={row.evaluator_id} mode={row.mode} "
                f"score={row.total_score} verdict={row.verdict} note={str(row.note)[:160]}",
                flush=True,
            )
    summary = {
        "run_id": run["id"],
        "status": run.get("status"),
        "score": report.get("total_score"),
        "verdict": report.get("verdict"),
        "hard_failures": [item.get("code") for item in (report.get("hard_failures") or [])],
        "findings": len(findings.get("items") or []),
    }
    print("E2E_SUMMARY:", json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if run.get("status") == "completed" else 1


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in {"bootstrap", "smoke", "single", "e2e"}:
        raise SystemExit("用法：sandbox_real_e2e.py {bootstrap|smoke|single|e2e}")
    _require_channel_env()
    from fde_api.app import create_app
    from fde_api.config import Settings

    app = create_app(Settings())
    with app.app_context():
        return {"bootstrap": bootstrap, "smoke": smoke, "single": single, "e2e": e2e}[mode]()


if __name__ == "__main__":
    raise SystemExit(main())
