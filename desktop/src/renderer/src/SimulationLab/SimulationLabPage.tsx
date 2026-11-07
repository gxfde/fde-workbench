// V3.2 G7 · 模拟训练场 · 页面外壳。
//
// 六块：总览（盘点）／案例库（管理）／运行台（Trace·评估·失败）／
// 改进提案／回归与盲测。运行、评估、失败三块共处「运行台」页（选中运行后分栏呈现）。

import { useState, type ReactElement } from "react"

import { ImprovementProposals } from "./ImprovementProposals"
import { RegressionDashboard } from "./RegressionDashboard"
import { ScenarioLibrary } from "./ScenarioLibrary"
import { SimulationDashboard } from "./SimulationDashboard"
import { SimulationRunDetail } from "./SimulationRunDetail"

type Tab = "overview" | "library" | "runs" | "proposals" | "regression"

const TABS: Array<{ key: Tab; label: string }> = [
  { key: "overview", label: "总览" },
  { key: "library", label: "案例库" },
  { key: "runs", label: "运行台" },
  { key: "proposals", label: "改进提案" },
  { key: "regression", label: "回归与盲测" },
]

export function SimulationLabPage(): ReactElement {
  const [tab, setTab] = useState<Tab>("overview")

  return (
    <main className="simulation-lab">
      <nav className="simulation-tabs" aria-label="模拟训练场分区">
        {TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`simulation-tab${tab === item.key ? " active" : ""}`}
            aria-current={tab === item.key ? "page" : undefined}
            onClick={() => setTab(item.key)}
          >
            {item.label}
          </button>
        ))}
      </nav>
      {tab === "overview" ? <SimulationDashboard /> : null}
      {tab === "library" ? <ScenarioLibrary /> : null}
      {tab === "runs" ? <SimulationRunDetail /> : null}
      {tab === "proposals" ? <ImprovementProposals /> : null}
      {tab === "regression" ? <RegressionDashboard /> : null}
    </main>
  )
}
