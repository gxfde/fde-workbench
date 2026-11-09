"""N1 真实订单首跑·运维脚本（宿主裸跑态）：真订单走宿主侧 zcode 代理通道。

**这是裸跑态（宿主 Windows 直跑服务端进程）的运维工具**——容器内 server
spawn 不到宿主 zcode（T-Z1 裁定 A 的前提），因此真机执行面只在宿主裸跑态可用
（形态同 ``scripts/simulation/sandbox_real_e2e.py``）。

跑法（宿主 Windows，server venv）：

```bash
cd server
PYTHONPATH=src python ../scripts/agents/real_order_host_channel_run.py \
  --project-code FDE-20261025-9BF8E4AE \
  --agent-id 4410538c-17a1-499d-817e-cb8060a90795 \
  --idempotency-key n1-somwyn-host-001
```

前置环境变量（本脚本不代设，跑前自行导出）：

```bash
export FDE_AGENT_HOST_CHANNEL_ENABLED=1
export FDE_AGENT_HOST_ZCODE_BIN='D:\software\zcode\ZCode.exe'
export FDE_AGENT_HOST_ZCODE_CJS='D:\software\zcode\resources\glm\zcode.cjs'
export FDE_AGENT_WORKSPACE_ROOT='D:\test\agent-workspaces'   # 须在仓库与真相层之外
export FDE_AGENT_MAX_DURATION_MS=900000
export FDE_DATABASE_URL='postgresql+psycopg://fde:<pw>@127.0.0.1:15432/fde_workbench'
```

**边界（脚本不越权）**：

1. 本脚本**只发起 run**（机械执行）——**产物接受（``reviewed=True``）与门禁
   拍板（G7/G8/G9）仍由人执行**（红线：AI 不代拍板；H1–H13 强制人工节点）；
2. 幂等键**不得**以 ``sim:`` / ``rehearsal:`` 开头——台账 G-01 判据要求真实
   订单的 run 幂等键**非** sim/演练前缀；
3. 工作区根须落在拒绝清单之外（真相层 / ``.env`` / fdeops / openfde /
   ``d:\\test\\fde`` 前缀），否则策略层 ``normalize_workspace_under_root`` 拒绝。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER_ROOT / "src"))

_SIM_PREFIXES = ("sim:", "rehearsal:")


def _require_env() -> None:
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
    if str(os.environ.get("FDE_AGENT_HOST_CHANNEL_ENABLED") or "").strip() not in (
        "1",
        "true",
        "True",
    ):
        raise SystemExit("FDE_AGENT_HOST_CHANNEL_ENABLED 必须显式为 1（本脚本只走宿主通道）。")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="N1 真实订单首跑（宿主侧 zcode 代理通道）")
    parser.add_argument("--project-code", required=True, help="项目代号（如 FDE-20261025-XXXX）")
    parser.add_argument("--agent-id", required=True, help="kind=zcode 智能体 id")
    parser.add_argument("--idempotency-key", required=True, help="幂等键；不得以 sim:/rehearsal: 开头")
    parser.add_argument(
        "--initiator",
        default="admin",
        help="发起人账号用户名（默认 admin）——审阅动作请用第二账号另登",
    )
    parser.add_argument("--difficulty", default="standard", choices=("standard", "high"))
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    _require_env()
    if args.idempotency_key.startswith(_SIM_PREFIXES):
        raise SystemExit(
            f"幂等键不得以 {args.idempotency_key[:5]}… 开头——台账 G-01 判据要求真实订单的 "
            "run 幂等键非 sim/演练前缀。"
        )

    from sqlalchemy import select

    from fde_api.agents import service as agents_service
    from fde_api.agents.models import AgentRegistry
    from fde_api.auth.models import User
    from fde_api.config import Settings
    from fde_api.evidence.models import ProjectEvidence
    from fde_api.extensions import db
    from fde_api.workbench.models import Project

    app_settings = Settings()
    if not app_settings.agent_host_channel_enabled:
        raise SystemExit("Settings().agent_host_channel_enabled 为 False——宿主通道未开启。")

    from fde_api.app import create_app

    app = create_app(app_settings)
    with app.app_context():
        with db.session() as session:
            project = session.scalar(
                select(Project).where(Project.project_code == args.project_code)
            )
            if project is None:
                raise SystemExit(f"项目不存在：{args.project_code}")
            agent = session.get(AgentRegistry, args.agent_id)
            if agent is None:
                raise SystemExit(f"智能体不存在：{args.agent_id}")
            if agent.kind != "zcode":
                raise SystemExit(f"智能体不是 zcode 类型：{agent.kind}")
            actor = session.scalar(select(User).where(User.username == args.initiator))
            if actor is None:
                raise SystemExit(f"发起人账号不存在：{args.initiator}")
            project_id = project.id
            project_code = project.project_code
            agent_id = agent.id
            agent_name = agent.name
            capability = agent.capability_tier
            session.commit()

        print(f"project={project_code} agent={agent_name}({capability}) initiator={args.initiator}")
        print(f"workspace_root={os.environ['FDE_AGENT_WORKSPACE_ROOT']}")

        run, status = agents_service.start_run(
            actor=actor,
            agent_id=agent_id,
            payload={
                "project_id": project_id,
                "idempotency_key": args.idempotency_key,
                "difficulty": args.difficulty,
            },
        )
        print(f"http_status={status} run_id={run.get('id')} status={run.get('status')}")
        print(f"execution_provider={run.get('execution_provider')} degraded={run.get('degraded')}")
        print(f"token_cost={run.get('token_cost')} duration_ms={run.get('duration_ms')}")
        for artifact in run.get("artifacts") or []:
            print(
                f"artifact kind={artifact.get('kind')} sha256={artifact.get('sha256')} "
                f"reviewed={artifact.get('reviewed')} storage_ref={artifact.get('storage_ref')}"
            )

        with db.session() as session:
            candidates = session.scalars(
                select(ProjectEvidence).where(
                    ProjectEvidence.captured_from == f"agent_run:{run.get('id')}"
                )
            ).all()
            print(f"evidence_candidates={len(candidates)}")
            for row in candidates:
                print(
                    f"candidate id={row.id} kind={row.kind} source_uri={row.source_uri} "
                    f"sha256={row.content_sha256} captured_from={row.captured_from}"
                )

        print(
            "\n下一步（**人工动作，AI 不代做**）：\n"
            "  1. 产物人工接受/撤回：PATCH /api/v1/agents/runs/{rid}/artifacts/{aid}"
            "（审阅账号请用第二账号，提交人≠审阅人）\n"
            "  2. 门禁拍板：把候选证据提交到对应门禁清单项后由人决定 G7/G8/G9\n"
            "     （采纳唯一路径＝人工提交闸 submit_gate_evidence，AI 不代拍板）"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
