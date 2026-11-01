import { useCallback, useEffect, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"

/** P2-1（派单设计 §3.2/§6.5）：能力档案 + 产能看板——四域分只用于等级晋级
 *  评定（短板决定），不进排序；同时接单上限=产能÷单均自动算（不可手工设）。 */

export interface CapabilityProfileView {
  user_id: string
  username: string
  display_name: string
  level: string | null
  status: string
  scores: {
    biz_cognition: number
    scenario_eng: number
    ai_tech: number
    delivery_assure: number
  }
  industry_tags: string[]
  module_tags: string[]
  home_city: string | null
  geo_fence_km: number
  monthly_capacity_hours: number | null
  avg_delivery_hours: number | null
  in_hand: number
  capacity_cap: number
}

const LEVEL_LABELS: Record<string, string> = {
  L1: "L1 助理场景工程师",
  L2: "L2 场景工程师",
  L3: "L3 高级场景工程师",
  L4: "L4 首席场景工程师",
}

export function isProfileView(value: unknown): value is CapabilityProfileView {
  if (typeof value !== "object" || value === null) return false
  const row = value as Record<string, unknown>
  return typeof row.user_id === "string" && typeof row.username === "string"
}

export function loadLevel(profile: CapabilityProfileView): number {
  // 负载率 = 在途 ÷ 上限（§6.5 容量过滤口径；只做硬过滤展示，不进排序）
  if (profile.capacity_cap <= 0) return 1
  return Math.min(profile.in_hand / profile.capacity_cap, 1)
}

export function CapabilityProfilesPage() {
  const { apiRequest } = useAuth()
  const [profiles, setProfiles] = useState<CapabilityProfileView[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const requestSequence = useRef(0)

  const load = useCallback(() => {
    const sequence = ++requestSequence.current
    setLoading(true)
    setError("")
    void apiRequest<unknown>("/api/v1/dispatch/profiles", { method: "GET" })
      .then((payload) => {
        if (sequence !== requestSequence.current) return
        // goal-d9 fix: apiRequest already unwraps the {data,error} envelope (latent bug family)
        setProfiles(Array.isArray(payload) ? payload.filter(isProfileView) : [])
      })
      .catch((caught: unknown) => {
        if (sequence !== requestSequence.current) return
        setError(
          caught instanceof ApiClientError ? caught.message : "能力档案加载失败，请稍后重试。"
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
    <section className="page" aria-label="能力档案与产能看板">
      <header className="page-header">
        <div>
          <h1>能力档案与产能看板</h1>
          <p className="page-subtitle">
            四域分是等级晋级评定维度（短板决定），不进派单排序；负载=在途÷上限，仅作容量硬过滤。
            等级核验证据链（goal-d11 M10）支持引用工作台评审会纪要：source_uri 填
            <code>workbench-minutes:&lt;meeting_id&gt;</code>，sha256 必须等于该纪要 sealed_sha256。
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
      {!loading && !error && profiles.length === 0 ? (
        <p className="muted">供给池暂无档案。</p>
      ) : null}
      <table className="dispatch-profile-table">
        <thead>
          <tr>
            <th>交付方</th>
            <th>等级</th>
            <th>四域（认知/场景/AI/保障）</th>
            <th>常驻城市</th>
            <th>行业标签</th>
            <th>在途/上限</th>
            <th>负载</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {profiles.map((row) => (
            <tr key={row.user_id}>
              <td>{row.display_name || row.username}</td>
              <td>{row.level ? LEVEL_LABELS[row.level] || row.level : "未定级"}</td>
              <td>
                {row.scores.biz_cognition}/{row.scores.scenario_eng}/
                {row.scores.ai_tech}/{row.scores.delivery_assure}
              </td>
              <td>{row.home_city || "—"}</td>
              <td>{row.industry_tags.length ? row.industry_tags.join("、") : "—"}</td>
              <td>
                {row.in_hand}/{row.capacity_cap}
              </td>
              <td>
                <span
                  className={`load-bar${loadLevel(row) >= 1 ? " load-full" : ""}`}
                  role="img"
                  aria-label={`负载 ${Math.round(loadLevel(row) * 100)}%`}
                >
                  {Math.round(loadLevel(row) * 100)}%
                </span>
              </td>
              <td>{row.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
