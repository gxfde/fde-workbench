// V3.2 G2 模拟训练场 · 页面外壳。
//
// 两块：总览（盘点）与案例库（管理）。运行/评估/失败分析/改进提案/回归盲测
// 五块在 G3–G6 落地后依次挂入——不在本轮放占位假数据。

import { useState, type ReactElement } from "react"

import { ScenarioLibrary } from "./ScenarioLibrary"
import { SimulationDashboard } from "./SimulationDashboard"

type Tab = "overview" | "library"

export function SimulationLabPage(): ReactElement {
  const [tab, setTab] = useState<Tab>("overview")

  return (
    <main className="simulation-lab">
      <nav className="simulation-tabs" aria-label="模拟训练场分区">
        <button
          type="button"
          className={`simulation-tab${tab === "overview" ? " active" : ""}`}
          aria-current={tab === "overview" ? "page" : undefined}
          onClick={() => setTab("overview")}
        >
          总览
        </button>
        <button
          type="button"
          className={`simulation-tab${tab === "library" ? " active" : ""}`}
          aria-current={tab === "library" ? "page" : undefined}
          onClick={() => setTab("library")}
        >
          案例库
        </button>
      </nav>
      {tab === "overview" ? <SimulationDashboard /> : <ScenarioLibrary />}
    </main>
  )
}
