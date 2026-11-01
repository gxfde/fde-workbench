import { useCallback, useEffect, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"

/** P2-1（派单设计 §8.5）：派单池页——交付包白名单字段只读视图（§9.2 十二项
 *  + 交付方席位金额）。跨主体语义=「只看我被授权的包」，金额只有
 *  delivery_seat_amount 一个（显示义务），报价/收款明细永不出现在响应里。 */

export interface DispatchPackageView {
  id: string
  package_code: string
  scope_summary: string | null
  deliverables_json: string | null
  acceptance_criteria: string | null
  data_systems: string | null
  schedule_text: string | null
  risks_dependencies: string | null
  business_category: string | null
  client_code: string
  client_city: string | null
  onsite_required: boolean
  onsite_visits: number | null
  deadline: string | null
  delivery_seat_amount: number | null
  dispatch_status: string
  dispatch_round: number
  dispatch_mode: string
  response_window_hours: number
  published_at: string | null
  agent_assisted: boolean
  difficulty: string | null
  accepted_user_id: string | null
}

export const DIFFICULTY_LABELS: Record<string, string> = {
  low: "low（agent 独立出草稿 + 人工终审）",
  medium: "medium（agent 草稿 + 强制终审）",
  high: "high（不派发给智能体）",
}

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  published: "已发布",
  offered: "已发 offer",
  assigned: "已指派",
  accepted: "已接单",
  rejected: "已拒绝",
  expired: "已超时",
  withdrawn: "已撤回",
}

export const MODE_LABELS: Record<string, string> = {
  assign: "指派制",
  claim: "抢单制",
}

export function isPackageView(value: unknown): value is DispatchPackageView {
  if (typeof value !== "object" || value === null) return false
  const row = value as Record<string, unknown>
  return typeof row.package_code === "string" && typeof row.client_code === "string"
}

export function formatSeatAmount(amount: number | null): string {
  if (amount === null) return "—"
  return `¥${amount.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`
}

export function DispatchPoolPage() {
  const { apiRequest, user } = useAuth()
  const [packages, setPackages] = useState<DispatchPackageView[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [expanded, setExpanded] = useState<string | null>(null)
  const [claimingId, setClaimingId] = useState<string | null>(null)
  const [claimError, setClaimError] = useState("")
  const [declaringId, setDeclaringId] = useState<string | null>(null)
  const [declareError, setDeclareError] = useState("")
  const requestSequence = useRef(0)

  const load = useCallback(() => {
    const sequence = ++requestSequence.current
    setLoading(true)
    setError("")
    void apiRequest<unknown>("/api/v1/dispatch/packages", { method: "GET" })
      .then((payload) => {
        if (sequence !== requestSequence.current) return
        // goal-d9 修正：apiRequest 客户端已解包 {data,error} 信封（潜伏 bug——
        // 旧代码对已解包值再取 .data 恒 undefined，派单池永远渲染为空）
        setPackages(Array.isArray(payload) ? payload.filter(isPackageView) : [])
      })
      .catch((caught: unknown) => {
        if (sequence !== requestSequence.current) return
        setError(
          caught instanceof ApiClientError ? caught.message : "派单池加载失败，请稍后重试。"
        )
      })
      .finally(() => {
        if (sequence === requestSequence.current) setLoading(false)
      })
  }, [apiRequest])

  useEffect(() => {
    load()
  }, [load])

  /** B1：抢单（§6.4）。开闸判定在服务端（claim_gate_status），前端直接
   *  试错并把可解释的 403 claim_closed 信息展示出来（§11 降级态 UX）。 */
  const claim = useCallback(
    (row: DispatchPackageView) => {
      setClaimingId(row.id)
      setClaimError("")
      void apiRequest<unknown>(`/api/v1/dispatch/packages/${row.id}/claim`, {
        method: "POST",
      })
        .then(() => {
          setExpanded(null)
          load()
        })
        .catch((caught: unknown) => {
          setClaimError(
            caught instanceof ApiClientError ? caught.message : "抢单失败，请稍后重试。"
          )
        })
        .finally(() => setClaimingId(null))
    },
    [apiRequest, load]
  )

  /** goal-d9 桌面化（D2 裁决三）：接单人对 accepted 包显式声明/撤销智能体
   *  协同。准入判定在服务端（声明权=接单人或 admin；high/未定档 409），
   *  前端试错并透出可解释错误（§11 降级态 UX 同款纪律）。 */
  const toggleAgentAssisted = useCallback(
    (row: DispatchPackageView) => {
      setDeclaringId(row.id)
      setDeclareError("")
      void apiRequest<unknown>(`/api/v1/dispatch/packages/${row.id}/agent-assisted`, {
        method: "POST",
        body: { enabled: !row.agent_assisted },
      })
        .then(() => load())
        .catch((caught: unknown) => {
          setDeclareError(
            caught instanceof ApiClientError ? caught.message : "协同声明失败，请稍后重试。"
          )
        })
        .finally(() => setDeclaringId(null))
    },
    [apiRequest, load]
  )

  return (
    <section className="page" aria-label="派单池">
      <header className="page-header">
        <div>
          <h1>派单池</h1>
          <p className="page-subtitle">
            只显示被授权查看的交付包；字段为脱敏白名单，金额仅为交付方席位份额（显示义务）。
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
      {!loading && !error && packages.length === 0 ? (
        <p className="muted">暂无被授权的交付包。</p>
      ) : null}
      <ul className="dispatch-package-list">
        {packages.map((row) => (
          <li key={row.package_code} className="dispatch-package-card">
            <button
              type="button"
              className="dispatch-package-summary"
              aria-expanded={expanded === row.package_code}
              onClick={() =>
                setExpanded(expanded === row.package_code ? null : row.package_code)
              }
            >
              <strong>{row.package_code}</strong>
              <span>{row.scope_summary || "（无范围摘要）"}</span>
              <span className="muted">
                {STATUS_LABELS[row.dispatch_status] || row.dispatch_status} ·{" "}
                {MODE_LABELS[row.dispatch_mode] || row.dispatch_mode} · 第 {row.dispatch_round} 轮
              </span>
              <span className="dispatch-seat-amount">
                交付方席位 {formatSeatAmount(row.delivery_seat_amount)}
              </span>
            </button>
            {expanded === row.package_code ? (
              <dl className="dispatch-package-detail">
                <dt>客户代号</dt>
                <dd>{row.client_code}</dd>
                <dt>客户城市</dt>
                <dd>{row.client_city || "—"}</dd>
                <dt>验收口径</dt>
                <dd>{row.acceptance_criteria || "—"}</dd>
                <dt>数据系统</dt>
                <dd>{row.data_systems || "—"}</dd>
                <dt>排期</dt>
                <dd>{row.schedule_text || "—"}</dd>
                <dt>风险依赖</dt>
                <dd>{row.risks_dependencies || "—"}</dd>
                <dt>业务类目</dt>
                <dd>{row.business_category || "—"}</dd>
                <dt>是否到场</dt>
                <dd>
                  {row.onsite_required
                    ? `是（${row.onsite_visits ?? 0} 次）`
                    : "否（远程）"}
                </dd>
                <dt>截止</dt>
                <dd>{row.deadline || "—"}</dd>
                <dt>响应窗</dt>
                <dd>{row.response_window_hours} 小时</dd>
                <dt>发布时刻</dt>
                <dd>{row.published_at || "—"}</dd>
                <dt>难度档位</dt>
                <dd>
                  {row.difficulty
                    ? DIFFICULTY_LABELS[row.difficulty] || row.difficulty
                    : "未定档"}
                </dd>
                <dt>智能体协同</dt>
                <dd>{row.agent_assisted ? "已声明（启用评审门与溯源联动）" : "未声明（纯人工交付）"}</dd>
              </dl>
            ) : null}
            {expanded === row.package_code &&
            row.dispatch_status === "accepted" &&
            row.accepted_user_id !== null &&
            row.accepted_user_id === user?.id ? (
              <div className="dispatch-offer-actions">
                <button
                  type="button"
                  className="secondary-button"
                  disabled={declaringId !== null}
                  onClick={() => toggleAgentAssisted(row)}
                >
                  {declaringId === row.id
                    ? "处理中…"
                    : row.agent_assisted
                      ? "撤销协同声明"
                      : "声明智能体协同"}
                </button>
                <span className="muted">
                  声明后启用 T1–T6 评审强制门与溯源联动；难度 high 或未定档不可声明。
                </span>
              </div>
            ) : null}
            {expanded === row.package_code &&
            row.dispatch_mode === "claim" &&
            (row.dispatch_status === "published" || row.dispatch_status === "offered") ? (
              <div className="dispatch-offer-actions">
                <button
                  type="button"
                  className="primary-button"
                  disabled={claimingId !== null}
                  onClick={() => claim(row)}
                >
                  {claimingId === row.id ? "抢单中…" : "抢单"}
                </button>
                <span className="muted">开闸判定在服务端（§6.4 三条件 + 城市开关）。</span>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
      {claimError ? (
        <p className="error-text" role="alert">
          {claimError}
        </p>
      ) : null}
      {declareError ? (
        <p className="error-text" role="alert">
          {declareError}
        </p>
      ) : null}
    </section>
  )
}
