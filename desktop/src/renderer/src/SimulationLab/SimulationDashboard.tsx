// V3.2 G2 模拟训练场 · 总览。
//
// 只呈现案例库盘点（案例数 × 客户行为 × 数据集 × 状态）。运行/评估/回归面在
// G3–G6 落地后再挂（不在本轮虚构数据）。

import { useCallback, useEffect, useRef, useState, type ReactElement } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { EmptyState, Loading } from "../components/ui"
import { listScenarios } from "./api"
import {
  SPLIT_LABEL,
  VARIANT_LABEL,
  type ScenarioDto,
  type ScenarioSplit,
  type ScenarioVariant,
} from "./types"

interface Bucket {
  key: string
  label: string
  count: number
}

function countBy(items: ScenarioDto[], pick: (item: ScenarioDto) => string): Bucket[] {
  const counts = new Map<string, number>()
  for (const item of items) {
    const key = pick(item)
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([key, count]) => ({ key, label: key, count }))
    .sort((left, right) => left.key.localeCompare(right.key))
}

export function SimulationDashboard(): ReactElement {
  const { apiRequest } = useAuth()
  const [items, setItems] = useState<ScenarioDto[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const sequence = useRef(0)

  const load = useCallback(async () => {
    const requestSequence = ++sequence.current
    try {
      const payload = await listScenarios(apiRequest, { includeHistory: true, limit: 200 })
      if (requestSequence !== sequence.current) return
      setItems(payload.items)
      setError("")
    } catch (caught) {
      if (requestSequence !== sequence.current) return
      setError(
        caught instanceof ApiClientError || caught instanceof Error
          ? caught.message
          : "加载失败，请稍后重试。",
      )
    } finally {
      if (requestSequence === sequence.current) setLoading(false)
    }
  }, [apiRequest])

  useEffect(() => {
    let active = true
    void load().then(() => {
      if (!active) return
      setLoading(false)
    })
    return () => {
      active = false
      sequence.current += 1
    }
  }, [load])

  const variantBuckets = countBy(items, (item) => VARIANT_LABEL[item.variant])
  const splitBuckets = countBy(items, (item) => SPLIT_LABEL[item.split as ScenarioSplit])
  const caseBuckets = countBy(items, (item) => item.scenario_key)
  const variantTotals: Record<ScenarioVariant, number> = {
    normal: 0,
    vague: 0,
    complex: 0,
  }
  for (const item of items) variantTotals[item.variant] += 1

  return (
    <section className="simulation-dashboard" aria-label="模拟训练场总览">
      <header>
        <h2>模拟训练场</h2>
        <p className="simulation-hint">
          FDE 交付模拟训练场：让既有 FDE Agent 与 Workflow 在隔离的虚拟环境里完成一次模拟交付，
          再由独立评估与失败分析给出可追溯的改进方向。评估与人工终裁入口在「运行台」：
          选中一次运行 → 「评估该运行」→ 在评估报告底部的「人工抽检结论（L-C 终裁）」提交终裁。
        </p>
      </header>

      {error ? (
        <p className="simulation-error" role="alert">
          {error}
        </p>
      ) : null}
      {loading ? <Loading label="正在加载训练场盘点…" /> : null}

      {!loading && items.length === 0 ? (
        <EmptyState
          title="训练场尚无案例"
          description="先在「案例库」中创建或导入案例，再发起模拟运行。"
        />
      ) : null}

      {items.length > 0 ? (
        <>
          <div className="simulation-kpi-row">
            <article className="simulation-kpi">
              <h3>案例分支</h3>
              <p className="simulation-kpi-value">{items.length}</p>
            </article>
            <article className="simulation-kpi">
              <h3>案例数</h3>
              <p className="simulation-kpi-value">{caseBuckets.length}</p>
            </article>
            <article className="simulation-kpi">
              <h3>正常客户</h3>
              <p className="simulation-kpi-value">{variantTotals.normal}</p>
            </article>
            <article className="simulation-kpi">
              <h3>模糊客户</h3>
              <p className="simulation-kpi-value">{variantTotals.vague}</p>
            </article>
            <article className="simulation-kpi">
              <h3>复杂客户</h3>
              <p className="simulation-kpi-value">{variantTotals.complex}</p>
            </article>
          </div>

          <div className="simulation-bucket-grid">
            <section aria-label="按客户行为分布">
              <h3>按客户行为</h3>
              <ul>
                {variantBuckets.map((bucket) => (
                  <li key={bucket.key}>
                    <span>{bucket.label}</span>
                    <strong>{bucket.count}</strong>
                  </li>
                ))}
              </ul>
            </section>
            <section aria-label="按数据集分布">
              <h3>按数据集</h3>
              <ul>
                {splitBuckets.map((bucket) => (
                  <li key={bucket.key}>
                    <span>{bucket.label}</span>
                    <strong>{bucket.count}</strong>
                  </li>
                ))}
              </ul>
            </section>
            <section aria-label="案例清单">
              <h3>案例</h3>
              <ul>
                {caseBuckets.map((bucket) => (
                  <li key={bucket.key}>
                    <span>{bucket.key}</span>
                    <strong>{bucket.count}</strong>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </>
      ) : null}
    </section>
  )
}
