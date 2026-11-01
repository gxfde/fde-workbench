import { useCallback, useEffect, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"

/** 城市开闸运维页（B6 运维页簇；§6.4 抢单开闸 + §11.1 降级态）。
 *  逐城可解释明细：白名单 + 种子开关 + 三条件（供给>需求/拒单率<40%/规则
 *  已公示）→ claim_open 终判。种子开关在 seeds/dispatch_cities.json（文件
 *  权威）——本页只读展示，改开关走代码流程，不提供 HTTP 翻转。 */

export interface ClaimGateView {
  city: string
  whitelisted: boolean
  city_switch: boolean
  supply: number
  demand: number
  offered: number
  declined: number
  reject_rate: number
  conditions: {
    supply_gt_demand: boolean
    reject_rate_ok: boolean
    rule_publicized: boolean
  }
  claim_open: boolean
}

export function isClaimGateView(value: unknown): value is ClaimGateView {
  if (typeof value !== "object" || value === null) return false
  const row = value as Record<string, unknown>
  return (
    typeof row.city === "string" &&
    typeof row.claim_open === "boolean" &&
    typeof row.conditions === "object" &&
    row.conditions !== null
  )
}

export function gateVerdict(gate: ClaimGateView): string {
  if (!gate.whitelisted) return "非白名单"
  if (!gate.city_switch) return "开关关闭（备案未完成，§11.1 降级态）"
  if (gate.claim_open) return "已开闸"
  return "条件未满足"
}

export function ClaimGatesPage() {
  const { apiRequest } = useAuth()
  const [gates, setGates] = useState<ClaimGateView[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const requestSequence = useRef(0)

  const load = useCallback(() => {
    const sequence = ++requestSequence.current
    setLoading(true)
    setError("")
    void apiRequest<unknown>("/api/v1/dispatch/claim-gates", { method: "GET" })
      .then((payload) => {
        if (sequence !== requestSequence.current) return
        // goal-d9 fix: apiRequest already unwraps the {data,error} envelope (latent bug family)
        setGates(Array.isArray(payload) ? payload.filter(isClaimGateView) : [])
      })
      .catch((caught: unknown) => {
        if (sequence !== requestSequence.current) return
        setError(
          caught instanceof ApiClientError ? caught.message : "开闸看板加载失败，请稍后重试。"
        )
      })
      .finally(() => {
        if (sequence === requestSequence.current) setLoading(false)
      })
  }, [apiRequest])

  useEffect(() => {
    load()
  }, [load])

  return (
    <section className="page" aria-label="开闸运维">
      <header className="page-header">
        <div>
          <h1>开闸运维</h1>
          <p className="page-subtitle">
            抢单开闸逐城判定（§6.4：白名单 + 种子开关 + 三条件）；开关在
            seeds/dispatch_cities.json，改走代码流程——本页只读。
          </p>
        </div>
        <button className="secondary-button" type="button" onClick={load}>
          刷新
        </button>
      </header>
      {loading ? <p className="muted">加载中…</p> : null}
      {error ? (
        <p className="error-text" role="alert">
          {error}
        </p>
      ) : null}
      {!loading && !error && gates.length === 0 ? (
        <p className="muted">城市白名单为空。</p>
      ) : null}
      <ul className="dispatch-package-list">
        {gates.map((gate) => (
          <li key={gate.city} className="dispatch-package-card">
            <div className="dispatch-offer-summary">
              <strong>{gate.city}</strong>
              <span
                className={gate.claim_open ? "dispatch-seat-amount" : "muted"}
                role="status"
              >
                {gateVerdict(gate)}
              </span>
              <span className="muted">
                供给 {gate.supply} · 需求 {gate.demand} · 90 天 offer {gate.offered}
                / 拒 {gate.declined}（拒单率{" "}
                {(gate.reject_rate * 100).toFixed(1)}%）
              </span>
            </div>
            <dl className="dispatch-package-detail">
              <dt>白名单</dt>
              <dd>{gate.whitelisted ? "是" : "否"}</dd>
              <dt>种子开关</dt>
              <dd>{gate.city_switch ? "开" : "关"}</dd>
              <dt>供给&gt;需求</dt>
              <dd>{gate.conditions.supply_gt_demand ? "✓" : "✗"}</dd>
              <dt>拒单率&lt;40%</dt>
              <dd>{gate.conditions.reject_rate_ok ? "✓" : "✗"}</dd>
              <dt>规则已公示</dt>
              <dd>{gate.conditions.rule_publicized ? "✓" : "✗"}</dd>
            </dl>
          </li>
        ))}
      </ul>
    </section>
  )
}
