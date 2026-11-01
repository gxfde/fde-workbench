import { useCallback, useEffect, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import {
  formatSeatAmount,
  isPackageView,
  MODE_LABELS,
  type DispatchPackageView,
} from "./DispatchPoolPage"

/** B1 接单工作台：我的 offer 收件箱 + 我的档案卡。

 *  数据源 GET /dispatch/offers/mine（候选人=当前用户全量留痕，§6.3）；
 *  deadline 是服务端按 §6.2 窗口现算（claim 15 分钟 / assign 24h），
 *  前端只做倒计时展示不做窗口判定（时间常数唯一权威在 DISPATCH_CONSTANTS）。
 *  接单/拒单走既有乐观锁 API（version 必填；拒单原因四选一只进留痕，§6.7）。
 *  match_breakdown（§4.8）只回本人的算法释明，默认折叠。 */

export interface MyOfferView {
  offer_id: string
  status: string
  version: number
  dispatch_round: number
  mode: string
  offered_at: string | null
  responded_at: string | null
  deadline: string | null
  match_breakdown: Record<string, unknown> | null
  package: DispatchPackageView
}

export interface MyProfileView {
  level: string | null
  status: string
  scores: {
    biz_cognition: number | null
    scenario_eng: number | null
    ai_tech: number | null
    delivery_assure: number | null
  }
  industry_tags: string[]
  module_tags: string[]
  home_city: string | null
  monthly_capacity_hours: number | null
  avg_delivery_hours: number | null
  in_hand: number
  capacity_cap: number
}

export const DECLINE_REASONS = ["档期冲突", "能力不匹配", "距离", "其他"] as const

export const OFFER_STATUS_LABELS: Record<string, string> = {
  offered: "待响应",
  accepted: "已接单",
  rejected: "已中签（他方）",
  declined: "已拒单",
  transferred: "已转单",
  expired: "已超时",
}

export function isMyOfferView(value: unknown): value is MyOfferView {
  if (typeof value !== "object" || value === null) return false
  const row = value as Record<string, unknown>
  return (
    typeof row.offer_id === "string" &&
    typeof row.status === "string" &&
    typeof row.version === "number" &&
    isPackageView(row.package)
  )
}

export function isMyProfileView(value: unknown): value is MyProfileView {
  if (typeof value !== "object" || value === null) return false
  const row = value as Record<string, unknown>
  return typeof row.status === "string" && typeof row.in_hand === "number"
}

/** 倒计时纯函数：距 deadline 的可读剩余时长；过期/无期限返回固定文案。 */
export function formatCountdown(deadline: string | null, now: Date): string {
  if (!deadline) return "—"
  const target = new Date(deadline)
  if (Number.isNaN(target.getTime())) return "—"
  const diffMs = target.getTime() - now.getTime()
  if (diffMs <= 0) return "已过期"
  const minutes = Math.floor(diffMs / 60000)
  const hours = Math.floor(minutes / 60)
  if (hours >= 1) return `剩 ${hours} 小时 ${minutes % 60} 分`
  return `剩 ${minutes} 分钟`
}

function ProfileCard() {
  const { apiRequest } = useAuth()
  const [profile, setProfile] = useState<MyProfileView | null>(null)
  const [missing, setMissing] = useState(false)

  useEffect(() => {
    let cancelled = false
    void apiRequest<unknown>("/api/v1/dispatch/profiles/me", { method: "GET" })
      .then((payload) => {
        if (cancelled) return
        // goal-d9 fix: apiRequest already unwraps the {data,error} envelope (latent bug family)
        setProfile(isMyProfileView(payload) ? payload : null)
      })
      .catch((caught: unknown) => {
        if (cancelled) return
        setMissing(
          caught instanceof ApiClientError && caught.status === 404
        )
      })
    return () => {
      cancelled = true
    }
  }, [apiRequest])

  if (missing) {
    return (
      <p className="muted" aria-label="档案缺失提示">
        尚无能力档案（由平台创建/晋级流程建立）。
      </p>
    )
  }
  if (!profile) return null
  return (
    <section className="dispatch-profile-card" aria-label="我的能力档案">
      <strong>
        我的档案：{profile.level ? `L${profile.level.slice(1)}` : "未定级"} ·{" "}
        {profile.home_city || "城市未填"}
      </strong>
      <span className="muted">
        在途 {profile.in_hand} / 上限 {profile.capacity_cap} 单 · 月产能{" "}
        {profile.monthly_capacity_hours ?? 0} 小时
      </span>
      <span className="muted">
        四域分：业务 {profile.scores.biz_cognition ?? "—"} · 场景{" "}
        {profile.scores.scenario_eng ?? "—"} · AI {profile.scores.ai_tech ?? "—"} ·{" "}
        交付 {profile.scores.delivery_assure ?? "—"}
      </span>
    </section>
  )
}

function OfferRow({ offer, onChanged }: { offer: MyOfferView; onChanged: () => void }) {
  const { apiRequest } = useAuth()
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState("")
  const [declineOpen, setDeclineOpen] = useState(false)
  const [reason, setReason] = useState<string>(DECLINE_REASONS[0])
  const [now, setNow] = useState(() => new Date())
  const [breakdownOpen, setBreakdownOpen] = useState(false)

  useEffect(() => {
    if (offer.status !== "offered") return
    const timer = window.setInterval(() => setNow(new Date()), 30_000)
    return () => window.clearInterval(timer)
  }, [offer.status])

  const act = useCallback(
    async (path: string, body: Record<string, unknown>) => {
      setBusy(true)
      setActionError("")
      try {
        await apiRequest<unknown>(path, { method: "POST", body })
        onChanged()
      } catch (caught: unknown) {
        setActionError(
          caught instanceof ApiClientError ? caught.message : "操作失败，请稍后重试。"
        )
      } finally {
        setBusy(false)
      }
    },
    [apiRequest, onChanged]
  )

  const pkg = offer.package
  return (
    <li className="dispatch-package-card">
      <div className="dispatch-package-summary dispatch-offer-summary">
        <strong>{pkg.package_code}</strong>
        <span>{pkg.scope_summary || "（无范围摘要）"}</span>
        <span className="muted">
          {OFFER_STATUS_LABELS[offer.status] || offer.status} ·{" "}
          {MODE_LABELS[offer.mode] || offer.mode} · 第 {offer.dispatch_round} 轮
        </span>
        <span className="muted">
          {offer.status === "offered"
            ? `响应截止：${formatCountdown(offer.deadline, now)}`
            : offer.responded_at
              ? `响应于 ${offer.responded_at}`
              : ""}
        </span>
        <span className="dispatch-seat-amount">
          交付方席位 {formatSeatAmount(pkg.delivery_seat_amount)}
        </span>
      </div>
      <dl className="dispatch-package-detail">
        <dt>客户代号</dt>
        <dd>{pkg.client_code}</dd>
        <dt>客户城市</dt>
        <dd>{pkg.client_city || "—"}</dd>
        <dt>是否到场</dt>
        <dd>
          {pkg.onsite_required ? `是（${pkg.onsite_visits ?? 0} 次）` : "否（远程）"}
        </dd>
        <dt>截止</dt>
        <dd>{pkg.deadline || "—"}</dd>
      </dl>
      {offer.match_breakdown ? (
        <>
          <button
            type="button"
            className="secondary-button"
            onClick={() => setBreakdownOpen((open) => !open)}
          >
            {breakdownOpen ? "收起算法释明" : "查看算法释明（§4.8）"}
          </button>
          {breakdownOpen ? (
            <pre className="dispatch-breakdown">
              {JSON.stringify(offer.match_breakdown, null, 2)}
            </pre>
          ) : null}
        </>
      ) : null}
      {offer.status === "offered" ? (
        <div className="dispatch-offer-actions">
          <button
            type="button"
            className="primary-button"
            disabled={busy}
            onClick={() =>
              void act(`/api/v1/dispatch/offers/${offer.offer_id}/accept`, {
                version: offer.version,
              })
            }
          >
            接单
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={busy}
            onClick={() => setDeclineOpen((open) => !open)}
          >
            拒单
          </button>
          {declineOpen ? (
            <span className="dispatch-decline-row">
              <select
                aria-label="拒单原因"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              >
                {DECLINE_REASONS.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="secondary-button"
                disabled={busy}
                onClick={() =>
                  void act(`/api/v1/dispatch/offers/${offer.offer_id}/decline`, {
                    version: offer.version,
                    reason,
                  })
                }
              >
                确认拒单
              </button>
            </span>
          ) : null}
        </div>
      ) : null}
      {actionError ? (
        <p className="error-text" role="alert">
          {actionError}
        </p>
      ) : null}
    </li>
  )
}

export function MyOffersPage() {
  const { apiRequest } = useAuth()
  const [offers, setOffers] = useState<MyOfferView[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const requestSequence = useRef(0)

  const load = useCallback(() => {
    const sequence = ++requestSequence.current
    setLoading(true)
    setError("")
    void apiRequest<unknown>("/api/v1/dispatch/offers/mine", { method: "GET" })
      .then((payload) => {
        if (sequence !== requestSequence.current) return
        // goal-d9 fix: apiRequest already unwraps the {data,error} envelope (latent bug family)
        setOffers(Array.isArray(payload) ? payload.filter(isMyOfferView) : [])
      })
      .catch((caught: unknown) => {
        if (sequence !== requestSequence.current) return
        setError(
          caught instanceof ApiClientError ? caught.message : "收件箱加载失败，请稍后重试。"
        )
      })
      .finally(() => {
        if (sequence === requestSequence.current) setLoading(false)
      })
  }, [apiRequest])

  useEffect(() => {
    load()
  }, [load])

  const pending = offers.filter((offer) => offer.status === "offered").length

  return (
    <section className="page" aria-label="我的接单">
      <header className="page-header">
        <div>
          <h1>我的接单</h1>
          <p className="page-subtitle">
            收到与历史 offer 全量留痕；待响应条目按 §6.2 窗口倒计时，超时自动释放。
          </p>
        </div>
        <button className="secondary-button" type="button" onClick={load}>
          刷新
        </button>
      </header>
      <ProfileCard />
      {loading ? <p className="muted">加载中…</p> : null}
      {error ? (
        <p className="error-text" role="alert">
          {error}
        </p>
      ) : null}
      {!loading && !error && offers.length === 0 ? (
        <p className="muted">暂无 offer 记录；被指派/中签后会出现在这里。</p>
      ) : null}
      {!loading && offers.length > 0 ? (
        <p className="muted" aria-label="待响应计数">
          待响应 {pending} 条 / 共 {offers.length} 条
        </p>
      ) : null}
      <ul className="dispatch-package-list">
        {offers.map((offer) => (
          <OfferRow key={offer.offer_id} offer={offer} onChanged={load} />
        ))}
      </ul>
    </section>
  )
}
