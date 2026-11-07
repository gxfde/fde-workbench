"""V3.2 G8 · 端到端验收实测脚本（产出统计，不改任何生产数据）。

跑法（在服务端环境里）：

```bash
cd server
PYTHONPATH=src python ../scripts/simulation/acceptance_sweep.py
```

产出：标准输出的 JSON（可直接重定向为 `docs/v3.2/v3.2-acceptance-report.json`）。

**边界**：本脚本只读内置案例种子、只写**模拟域**四表（run/actor/trace/evaluation）；
不碰真实项目、不发邮件、不调任何外部服务。执行面固定为 **mock**——统计的是
「训练场机制是否按预期跑通」，**不是**真实 Agent 的交付质量。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SERVER_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER_ROOT / "src"))

from fde_api.extensions import db  # noqa: E402
from fde_api.simulation import evaluator, run_service  # noqa: E402
from fde_api.simulation.improvement_service import analyze_run  # noqa: E402
from fde_api.simulation.models import SimulationScenario  # noqa: E402
from fde_api.simulation.seeds import CASE_SPLIT, VARIANTS, seed_scenarios  # noqa: E402
from sqlalchemy import select  # noqa: E402


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def main() -> int:
    from fde_api.auth.models import User
    from fde_api.auth.passwords import hash_password
    from fde_api.auth.tokens import issue_access_token

    with db.session() as session:
        seed_outcome = seed_scenarios(session)
        session.commit()

    with db.session() as session:
        actor = session.scalar(select(User).where(User.role == "admin").limit(1))
        if actor is None:
            # 验收脚本自建一个一次性 admin（随机口令、不用于登录）。
            from uuid import uuid4

            actor = User(
                username=f"sim.acceptance.{uuid4().hex[:8]}",
                display_name="Simulation acceptance sweep",
                role="admin",
                password_hash=hash_password(uuid4().hex),
                must_change_password=False,
                is_active=True,
            )
            session.add(actor)
            session.commit()

    rows: list[dict[str, Any]] = []
    with db.session() as session:
        scenarios = list(
            session.scalars(
                select(SimulationScenario).order_by(
                    SimulationScenario.scenario_key, SimulationScenario.variant
                )
            )
        )

    for scenario in scenarios:
        run = run_service.create_run(
            actor=actor,
            payload={
                "scenario_id": scenario.id,
                "adapter_mode": "mock",
                "execute": True,
                "config": {"max_rounds": 5, "probe_quality": 1.0},
            },
        )
        report = evaluator.evaluate_run(actor=actor, run_id=run["id"])
        findings = analyze_run(actor=actor, run_id=run["id"])
        rows.append(
            {
                "case": scenario.scenario_key,
                "variant": scenario.variant,
                "split": scenario.split,
                "status": run["status"],
                "score": report["total_score"],
                "verdict": report["verdict"],
                "hard_failures": [item["code"] for item in report["hard_failures"]],
                "rounds": run["cost"].get("rounds"),
                "tool_calls": run["cost"].get("tool_calls"),
                "tool_failures": run["cost"].get("tool_failures"),
                "findings": len(findings["items"]),
                "findings_new": findings["created"],
            }
        )

    scores = [float(row["score"]) for row in rows]
    by_split: dict[str, list[float]] = {}
    for row in rows:
        by_split.setdefault(str(row["split"]), []).append(float(row["score"]))
    verdicts: dict[str, int] = {}
    for row in rows:
        key = str(row["verdict"])
        verdicts[key] = verdicts.get(key, 0) + 1

    summary = {
        "meta": {
            "adapter_mode": "mock",
            "disclaimer": "本统计为模拟环境的合成结果（假设 × 引擎），不冒充真实项目交付质量。",
            "case_splits": dict(CASE_SPLIT),
            "variants": list(VARIANTS),
        },
        "seed": seed_outcome,
        "totals": {
            "runs": len(rows),
            "mean_score": _mean(scores),
            "min_score": round(min(scores), 4) if scores else 0.0,
            "max_score": round(max(scores), 4) if scores else 0.0,
            "total_tool_calls": sum(int(row["tool_calls"] or 0) for row in rows),
            "total_rounds": sum(int(row["rounds"] or 0) for row in rows),
            "total_findings": sum(int(row["findings"] or 0) for row in rows),
        },
        "verdicts": verdicts,
        "by_split": {
            split: {"runs": len(values), "mean_score": _mean(values)}
            for split, values in sorted(by_split.items())
        },
        "runs": rows,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _run() -> int:
    """在应用上下文里跑（db.session() 需要 current_app）。"""
    from fde_api.app import create_app
    from fde_api.config import Settings

    app = create_app(Settings())
    with app.app_context():
        return main()


if __name__ == "__main__":
    raise SystemExit(_run())
