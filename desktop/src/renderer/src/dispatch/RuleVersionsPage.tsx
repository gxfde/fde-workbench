import { useCallback, useEffect, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"

/** P2-1（派单设计 §6.2/规则表 B9）：权重与规则版本——只读视图（改规则 =
 *  新版本 + ≥30 天公示，服务端强制；仿真对比二期，留注⑳：本页做版本取值
 *  对照）。常数节来自 system_configuration 只读 dispatch_constants。 */

export interface RuleVersionView {
  id: string
  version_no: number
  status: string
  rule_snapshot: Record<string, unknown>
  published_at: string | null
  effective_at: string | null
  retired_at: string | null
}

export interface RulesPayload {
  versions: RuleVersionView[]
  constants: Record<string, unknown>
}

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  published: "已公示",
  active: "生效中",
  retired: "已退役",
}

export function isRulesPayload(value: unknown): value is RulesPayload {
  if (typeof value !== "object" || value === null) return false
  const row = value as Record<string, unknown>
  return Array.isArray(row.versions) && typeof row.constants === "object"
}

export function snapshotValue(
  snapshot: Record<string, unknown> | undefined,
  key: string
): string {
  const value = snapshot?.[key]
  if (value === undefined || value === null) return "—"
  return JSON.stringify(value)
}

export function RuleVersionsPage() {
  const { apiRequest } = useAuth()
  const [payload, setPayload] = useState<RulesPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const requestSequence = useRef(0)

  const load = useCallback(() => {
    const sequence = ++requestSequence.current
    setLoading(true)
    setError("")
    void apiRequest<unknown>("/api/v1/dispatch/rules", { method: "GET" })
      .then((data) => {
        if (sequence !== requestSequence.current) return
        // goal-d9 fix: apiRequest already unwraps the {data,error} envelope (latent bug family)
        if (!isRulesPayload(data)) {
          setError("规则版本数据格式异常")
          return
        }
        setPayload(data)
      })
      .catch((caught: unknown) => {
        if (sequence !== requestSequence.current) return
        setError(
          caught instanceof ApiClientError ? caught.message : "规则版本加载失败，请稍后重试。"
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
    <section className="page" aria-label="权重与规则版本">
      <header className="page-header">
        <div>
          <h1>权重与规则版本</h1>
          <p className="page-subtitle">
            改规则 = 新版本 + 公示 ≥30 天（服务端强制 422）；此处只读。仿真对比二期。
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
      {payload ? (
        <>
          <h2>版本快照</h2>
          <table className="dispatch-rules-table">
            <thead>
              <tr>
                <th>版本</th>
                <th>状态</th>
                <th>Stage B 权重</th>
                <th>等级映射分</th>
                <th>席位份额</th>
                <th>公示日</th>
                <th>生效日</th>
              </tr>
            </thead>
            <tbody>
              {payload.versions.map((row) => (
                <tr key={row.id}>
                  <td>v{row.version_no}</td>
                  <td>{STATUS_LABELS[row.status] || row.status}</td>
                  <td>{snapshotValue(row.rule_snapshot, "stage_b_weights")}</td>
                  <td>{snapshotValue(row.rule_snapshot, "level_score_map")}</td>
                  <td>{snapshotValue(row.rule_snapshot, "seat_shares")}</td>
                  <td>{row.published_at || "—"}</td>
                  <td>{row.effective_at || "—"}</td>
                </tr>
              ))}
              {payload.versions.length === 0 ? (
                <tr>
                  <td colSpan={7}>尚无规则版本（撮合将回落只读常数口径，且 422 降级态生效）。</td>
                </tr>
              ) : null}
            </tbody>
          </table>
          <h2>只读常数（§6.2 唯一权威表）</h2>
          <pre className="dispatch-constants">{JSON.stringify(payload.constants, null, 2)}</pre>
        </>
      ) : null}
    </section>
  )
}
