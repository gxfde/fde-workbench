import { useCallback, useEffect, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { isProfileView, type CapabilityProfileView } from "./CapabilityProfilesPage"
import {
  formatSeatAmount,
  isPackageView,
  MODE_LABELS,
  DIFFICULTY_LABELS,
  type DispatchPackageView,
} from "./DispatchPoolPage"
import { OFFER_STATUS_LABELS } from "./MyOffersPage"

/** 平台侧调度台操作面（B2）：发布 / 撮合 / 指派 / 撤回 / 等级覆盖 + 包侧
 *  offer 留痕。动作权限在服务端（admin/project_lead）；前端按状态出按钮：
 *  - draft：等级覆盖（§4.5，必填 reason）+ 发布（可携候选只读授权）
 *  - withdrawn/rejected/expired：重新发布（服务端自动 round+1 新版本对）
 *  - published：执行撮合（§4 两段式，无公示规则版本时 422 降级人工排序）/
 *    指派 offer / 撤回（TRANSITIONS 仅 published 可撤）
 *  确认窗 deadline 由服务端现算，前端只展示不重算（B1 时间窗纪律）。 */

export interface OfferTrailView {
  offer_id: string
  candidate_user_id: string
  candidate_username: string
  candidate_display_name: string
  dispatch_round: number
  mode: string
  status: string
  version: number
  rank: number | null
  explanation: string | null
  offered_at: string | null
  responded_at: string | null
  deadline: string | null
}

export function isOfferTrailView(value: unknown): value is OfferTrailView {
  if (typeof value !== "object" || value === null) return false
  const row = value as Record<string, unknown>
  return (
    typeof row.offer_id === "string" && typeof row.candidate_user_id === "string"
  )
}

export interface MatchResultView {
  scenario: string
  offers: {
    offer_id: string
    candidate_user_id: string
    rank: number
    explanation: string | null
  }[]
  rejected: string[]
  rule_version: string | null
}

export function isMatchResultView(value: unknown): value is MatchResultView {
  if (typeof value !== "object" || value === null) return false
  const row = value as Record<string, unknown>
  return typeof row.scenario === "string" && Array.isArray(row.offers)
}

export interface AiSuggestionRow {
  candidate_user_id: string
  rank: number
  rationale: string
}

export interface AiMatchResultView {
  scenario: string
  ai_suggestions: AiSuggestionRow[]
  recommendation_sha256: string
  ai_called: boolean
  model: string | null
  prompt_version: string
  truncated: boolean
}

export function isAiMatchResultView(value: unknown): value is AiMatchResultView {
  if (typeof value !== "object" || value === null) return false
  const row = value as Record<string, unknown>
  return (
    typeof row.scenario === "string" &&
    Array.isArray(row.ai_suggestions) &&
    typeof row.recommendation_sha256 === "string" &&
    typeof row.ai_called === "boolean"
  )
}

export const PACKAGE_STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  published: "已发布",
  offered: "已发 offer",
  assigned: "已指派",
  accepted: "已接单",
  rejected: "已拒绝",
  expired: "已超时",
  withdrawn: "已撤回",
}

const SCENARIO_LABELS: Record<string, string> = {
  A: "场景 A（到场·地理分层）",
  B: "场景 B（远程·加权排序）",
  C: "场景 C（资格门全拒·人工兜底）",
}

const LEVELS = ["L1", "L2", "L3", "L4"] as const

export function statusActionLabel(status: string): string | null {
  // 状态 → 主操作提示（按钮文案由动作自身决定；null = 该状态无平台动作）
  if (status === "draft") return "发布"
  if (status === "withdrawn" || status === "rejected" || status === "expired")
    return "重新发布"
  if (status === "published") return "撮合/指派"
  return null
}

export function ConsolePage() {
  const { apiRequest, user } = useAuth()
  const [packages, setPackages] = useState<DispatchPackageView[]>([])
  const [profiles, setProfiles] = useState<CapabilityProfileView[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [actionError, setActionError] = useState("")
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [trail, setTrail] = useState<Record<string, OfferTrailView[]>>({})
  const [matchResults, setMatchResults] = useState<Record<string, MatchResultView>>({})
  const [aiMatchResults, setAiMatchResults] = useState<Record<string, AiMatchResultView>>({})
  const [aiDecisionState, setAiDecisionState] = useState<
    Record<string, { decision: "adopted" | "rejected"; recommendation_sha256: string }>
  >({})
  const [overrideDraft, setOverrideDraft] = useState<{
    packageId: string
    level: string
    reason: string
  } | null>(null)
  const requestSequence = useRef(0)

  const load = useCallback(() => {
    const sequence = ++requestSequence.current
    setLoading(true)
    setError("")
    Promise.all([
      apiRequest<unknown>("/api/v1/dispatch/packages", { method: "GET" }),
      apiRequest<unknown>("/api/v1/dispatch/profiles", { method: "GET" }),
    ])
      .then(([pkgPayload, profilePayload]) => {
        if (sequence !== requestSequence.current) return
        // goal-d9 修正：apiRequest 已解包信封（同 DispatchPoolPage 潜伏 bug）
        const pkgRows = pkgPayload
        const profileRows = profilePayload
        setPackages(Array.isArray(pkgRows) ? pkgRows.filter(isPackageView) : [])
        setProfiles(
          Array.isArray(profileRows) ? profileRows.filter(isProfileView) : []
        )
      })
      .catch((caught: unknown) => {
        if (sequence !== requestSequence.current) return
        setError(
          caught instanceof ApiClientError ? caught.message : "调度台加载失败，请稍后重试。"
        )
      })
      .finally(() => {
        if (sequence === requestSequence.current) setLoading(false)
      })
  }, [apiRequest])

  useEffect(() => {
    load()
  }, [load])

  const loadTrail = useCallback(
    (packageId: string) => {
      void apiRequest<unknown>(`/api/v1/dispatch/packages/${packageId}/offers`, {
        method: "GET",
      })
        .then((payload) => {
          // goal-d9 fix: apiRequest already unwraps the {data,error} envelope (latent bug family)
          setTrail((prev) => ({
            ...prev,
            [packageId]: Array.isArray(payload) ? payload.filter(isOfferTrailView) : [],
          }))
        })
        .catch((caught: unknown) => {
          setActionError(
            caught instanceof ApiClientError ? caught.message : "offer 留痕加载失败。"
          )
        })
    },
    [apiRequest]
  )

  const runAction = useCallback(
    (key: string, run: () => Promise<void>) => {
      setBusyKey(key)
      setActionError("")
      void run()
        .then(() => {
          load()
          if (expanded) loadTrail(expanded)
        })
        .catch((caught: unknown) => {
          setActionError(
            caught instanceof ApiClientError ? caught.message : "操作失败，请稍后重试。"
          )
        })
        .finally(() => setBusyKey(null))
    },
    [expanded, load, loadTrail]
  )

  const selectedIds = [...selected]

  const publish = (row: DispatchPackageView) =>
    runAction(`publish:${row.id}`, async () => {
      await apiRequest(`/api/v1/dispatch/packages/${row.id}/publish`, {
        method: "POST",
        body: { candidate_user_ids: selectedIds },
      })
    })

  const withdraw = (row: DispatchPackageView) =>
    runAction(`withdraw:${row.id}`, async () => {
      await apiRequest(`/api/v1/dispatch/packages/${row.id}/withdraw`, {
        method: "POST",
      })
    })

  // goal-d9 桌面化（D2 裁决三）：admin 管理通道声明/撤销协同；声明权校验在
  // 服务端（接单人或 admin；high/未定档 409），前端试错透出
  const toggleAgentAssisted = (row: DispatchPackageView) =>
    runAction(`assist:${row.id}`, async () => {
      await apiRequest(`/api/v1/dispatch/packages/${row.id}/agent-assisted`, {
        method: "POST",
        body: { enabled: !row.agent_assisted },
      })
    })

  const runMatch = (row: DispatchPackageView) =>
    runAction(`match:${row.id}`, async () => {
      const payload = await apiRequest<unknown>(
        `/api/v1/dispatch/packages/${row.id}/match`,
        { method: "POST" }
      )
      // goal-d9 fix: apiRequest already unwraps the {data,error} envelope (latent bug family)
      if (isMatchResultView(payload)) {
        setMatchResults((prev) => ({ ...prev, [row.id]: payload }))
      }
    })

  const runAiMatch = (row: DispatchPackageView) =>
    runAction(`match-ai:${row.id}`, async () => {
      const payload = await apiRequest<unknown>(
        `/api/v1/dispatch/packages/${row.id}/match-ai`,
        { method: "POST", body: {} }
      )
      if (isAiMatchResultView(payload)) {
        setAiMatchResults((prev) => ({ ...prev, [row.id]: payload }))
        setAiDecisionState((prev) => {
          const next = { ...prev }
          delete next[row.id]
          return next
        })
      }
    })

  const submitAiDecision = (
    row: DispatchPackageView,
    decision: "adopted" | "rejected",
  ) => {
    const aiResult = aiMatchResults[row.id]
    if (!aiResult) return
    const suggestedIds = Array.from(
      new Set(
        aiResult.ai_suggestions
          .map((item) => item.candidate_user_id)
          .filter((id) => Boolean(id)),
      ),
    )
    const adoptedIds = decision === "adopted" ? suggestedIds : []
    runAction(`match-ai-decision:${row.id}`, async () => {
      await apiRequest(`/api/v1/dispatch/packages/${row.id}/match-ai/decision`, {
        method: "POST",
        body: {
          decision,
          recommendation_sha256: aiResult.recommendation_sha256,
          adopted_candidate_ids: adoptedIds,
        },
      })
      if (decision === "adopted") {
        setSelected((prev) => {
          const next = new Set(prev)
          for (const candidateId of adoptedIds) {
            next.add(candidateId)
          }
          return next
        })
      }
      setAiDecisionState((prev) => ({
        ...prev,
        [row.id]: {
          decision,
          recommendation_sha256: aiResult.recommendation_sha256,
        },
      }))
    })
  }

  const assignOffers = (row: DispatchPackageView) =>
    runAction(`assign:${row.id}`, async () => {
      await apiRequest(`/api/v1/dispatch/packages/${row.id}/offers`, {
        method: "POST",
        body: { candidate_user_ids: selectedIds },
      })
    })

  const overrideLevel = (row: DispatchPackageView) => {
    if (!overrideDraft || !overrideDraft.reason.trim()) {
      setActionError("等级覆盖必须写明 reason（§4.5 留痕）。")
      return
    }
    runAction(`level:${row.id}`, async () => {
      await apiRequest(`/api/v1/dispatch/packages/${row.id}/required-level`, {
        method: "POST",
        body: { level: overrideDraft.level, reason: overrideDraft.reason },
      })
      setOverrideDraft(null)
    })
  }

  const acceptOnBehalf = (row: DispatchPackageView, candidateUserId: string) =>
    runAction(`accept:${row.id}:${candidateUserId}`, async () => {
      await apiRequest(`/api/v1/dispatch/packages/${row.id}/accept`, {
        method: "POST",
        body: { delivery_user_id: candidateUserId },
      })
    })

  function toggleCandidate(userId: string): void {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(userId)) next.delete(userId)
      else next.add(userId)
      return next
    })
  }

  function toggleExpand(row: DispatchPackageView): void {
    if (expanded === row.id) {
      setExpanded(null)
      return
    }
    setExpanded(row.id)
    setOverrideDraft(null)
    loadTrail(row.id)
  }

  return (
    <section className="page" aria-label="调度台">
      <header className="page-header">
        <div>
          <h1>调度台</h1>
          <p className="page-subtitle">
            平台侧派单操作面：发布 / 撮合 / 指派 / 撤回；权限在服务端复核，按钮按包状态出。
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
      {actionError ? (
        <p className="error-text" role="alert">
          {actionError}
        </p>
      ) : null}

      <div className="dispatch-console-pool">
        <h2>供给池候选（勾选后用于发布授权 / 指派 offer）</h2>
        {profiles.length === 0 && !loading ? (
          <p className="muted">供给池暂无档案。</p>
        ) : null}
        <ul className="dispatch-console-candidates">
          {profiles.map((profile) => (
            <li key={profile.user_id}>
              <label className="dispatch-console-candidate">
                <input
                  type="checkbox"
                  checked={selected.has(profile.user_id)}
                  onChange={() => toggleCandidate(profile.user_id)}
                />
                <strong>{profile.display_name}</strong>
                <span className="muted">
                  {profile.level || "未定级"} · {profile.status} · 在途{" "}
                  {profile.in_hand}/{profile.capacity_cap}
                </span>
              </label>
            </li>
          ))}
        </ul>
      </div>

      {!loading && !error && packages.length === 0 ? (
        <p className="muted">暂无交付包（draft 也在列）。</p>
      ) : null}
      <ul className="dispatch-package-list">
        {packages.map((row) => (
          <li key={row.id} className="dispatch-package-card">
            <button
              type="button"
              className="dispatch-package-summary"
              aria-expanded={expanded === row.id}
              onClick={() => toggleExpand(row)}
            >
              <strong>{row.package_code}</strong>
              <span>{row.scope_summary || "（无范围摘要）"}</span>
              <span className="muted">
                {PACKAGE_STATUS_LABELS[row.dispatch_status] || row.dispatch_status} ·{" "}
                {MODE_LABELS[row.dispatch_mode] || row.dispatch_mode} · 第{" "}
                {row.dispatch_round} 轮
              </span>
              <span className="dispatch-seat-amount">
                交付方席位 {formatSeatAmount(row.delivery_seat_amount)}
              </span>
            </button>

            {expanded === row.id ? (
              <>
                <dl className="dispatch-package-detail">
                  <dt>客户代号</dt>
                  <dd>{row.client_code}</dd>
                  <dt>客户城市</dt>
                  <dd>{row.client_city || "—"}</dd>
                  <dt>发布时刻</dt>
                  <dd>{row.published_at || "—"}</dd>
                  <dt>响应窗</dt>
                  <dd>{row.response_window_hours} 小时</dd>
                  <dt>难度档位</dt>
                  <dd>
                    {row.difficulty
                      ? DIFFICULTY_LABELS[row.difficulty] || row.difficulty
                      : "未定档"}
                  </dd>
                  <dt>智能体协同</dt>
                  <dd>{row.agent_assisted ? "已声明（启用评审门与溯源联动）" : "未声明（纯人工交付）"}</dd>
                </dl>

                {row.dispatch_status === "accepted" && user?.role === "admin" ? (
                  <div className="dispatch-offer-actions">
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={busyKey !== null}
                      onClick={() => void toggleAgentAssisted(row)}
                    >
                      {busyKey === `assist:${row.id}`
                        ? "处理中…"
                        : row.agent_assisted
                          ? "撤销协同声明"
                          : "代为声明协同（管理通道）"}
                    </button>
                    <span className="muted">管理通道：声明权=接单人或 admin（D2 裁决三）。</span>
                  </div>
                ) : null}

                <div className="dispatch-offer-actions">
                  {row.dispatch_status === "draft" ? (
                    <>
                      {overrideDraft && overrideDraft.packageId === row.id ? (
                        <span className="dispatch-decline-row">
                          <select
                            aria-label="覆盖等级"
                            value={overrideDraft.level}
                            onChange={(event) =>
                              setOverrideDraft({
                                packageId: row.id,
                                level: event.target.value,
                                reason: overrideDraft.reason,
                              })
                            }
                          >
                            {LEVELS.map((level) => (
                              <option key={level} value={level}>
                                {level}
                              </option>
                            ))}
                          </select>
                          <input
                            aria-label="覆盖原因"
                            placeholder="覆盖原因（必填留痕）"
                            value={overrideDraft.reason}
                            onChange={(event) =>
                              setOverrideDraft({
                                packageId: row.id,
                                level: overrideDraft.level,
                                reason: event.target.value,
                              })
                            }
                          />
                          <button
                            type="button"
                            className="primary-button"
                            disabled={busyKey !== null}
                            onClick={() => overrideLevel(row)}
                          >
                            {busyKey === `level:${row.id}` ? "提交中…" : "提交覆盖"}
                          </button>
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={() => setOverrideDraft(null)}
                          >
                            取消
                          </button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() =>
                            setOverrideDraft({
                              packageId: row.id,
                              level: "L2",
                              reason: "",
                            })
                          }
                        >
                          等级覆盖
                        </button>
                      )}
                      <button
                        type="button"
                        className="primary-button"
                        disabled={busyKey !== null}
                        onClick={() => publish(row)}
                      >
                        {busyKey === `publish:${row.id}`
                          ? "发布中…"
                          : `发布（已选 ${selectedIds.length} 候选）`}
                      </button>
                    </>
                  ) : null}

                  {row.dispatch_status === "withdrawn" ||
                  row.dispatch_status === "rejected" ||
                  row.dispatch_status === "expired" ? (
                    <button
                      type="button"
                      className="primary-button"
                      disabled={busyKey !== null}
                      onClick={() => publish(row)}
                    >
                      {busyKey === `publish:${row.id}`
                        ? "发布中…"
                        : `重新发布（第 ${row.dispatch_round + 1} 轮，已选 ${selectedIds.length} 候选）`}
                    </button>
                  ) : null}

                  {row.dispatch_status === "published" ? (
                    <>
                      <button
                        type="button"
                        className="primary-button"
                        disabled={busyKey !== null}
                        onClick={() => runMatch(row)}
                      >
                        {busyKey === `match:${row.id}` ? "撮合中…" : "执行撮合"}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={busyKey !== null}
                        onClick={() => runAiMatch(row)}
                      >
                        {busyKey === `match-ai:${row.id}` ? "AI 撮合中…" : "AI 撮合建议"}
                      </button>
                      <button
                        type="button"
                        className="primary-button"
                        disabled={busyKey !== null || selectedIds.length === 0}
                        onClick={() => assignOffers(row)}
                      >
                        {busyKey === `assign:${row.id}`
                          ? "指派中…"
                          : `指派 offer（已选 ${selectedIds.length} 候选）`}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={busyKey !== null}
                        onClick={() => withdraw(row)}
                      >
                        {busyKey === `withdraw:${row.id}` ? "撤回中…" : "撤回"}
                      </button>
                    </>
                  ) : null}
                </div>

                {aiMatchResults[row.id] ? (
                  <div className="dispatch-breakdown" aria-label="AI 撮合建议结果">
                    <strong>
                      AI 撮合建议 ·{" "}
                      {SCENARIO_LABELS[aiMatchResults[row.id].scenario] ||
                        `场景 ${aiMatchResults[row.id].scenario}`}
                      {aiMatchResults[row.id].model
                        ? ` · 模型 ${aiMatchResults[row.id].model}`
                        : ""}
                      {aiMatchResults[row.id].prompt_version
                        ? ` · 提示词 ${aiMatchResults[row.id].prompt_version}`
                        : ""}
                    </strong>
                    {!aiMatchResults[row.id].ai_called ? (
                      <p className="muted">
                        未调用 AI 模型（资格门无候选过闸，零模型消耗，请走人工兜底）。
                      </p>
                    ) : null}
                    {aiMatchResults[row.id].ai_suggestions.length > 0 ? (
                      <ul>
                        {aiMatchResults[row.id].ai_suggestions.map((suggestion) => {
                          const matchedProfile = profiles.find(
                            (p) => p.user_id === suggestion.candidate_user_id,
                          )
                          return (
                            <li key={`${suggestion.rank}-${suggestion.candidate_user_id}`}>
                              Top{suggestion.rank} · 候选 {suggestion.candidate_user_id}
                              {matchedProfile ? `（${matchedProfile.display_name}）` : ""}
                              {suggestion.rationale ? ` · 理由：${suggestion.rationale}` : ""}
                            </li>
                          )
                        })}
                      </ul>
                    ) : aiMatchResults[row.id].ai_called ? (
                      <p className="muted">AI 未返回候选建议。</p>
                    ) : null}
                    <div className="dispatch-offer-actions">
                      <button
                        type="button"
                        className="primary-button"
                        disabled={
                          busyKey !== null ||
                          aiMatchResults[row.id].ai_suggestions.length === 0
                        }
                        onClick={() => submitAiDecision(row, "adopted")}
                      >
                        {busyKey === `match-ai-decision:${row.id}` ? "记录中…" : "采纳建议"}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={busyKey !== null}
                        onClick={() => submitAiDecision(row, "rejected")}
                      >
                        {busyKey === `match-ai-decision:${row.id}` ? "记录中…" : "驳回建议"}
                      </button>
                      {aiDecisionState[row.id] ? (
                        <span className="muted">
                          {aiDecisionState[row.id].decision === "adopted"
                            ? "已记录采纳并勾选推荐候选人，请点击「指派 offer」人工派单。"
                            : "已记录驳回建议。"}
                        </span>
                      ) : null}
                    </div>
                  </div>
                ) : null}

                {matchResults[row.id] ? (
                  <div className="dispatch-breakdown" aria-label="撮合结果">
                    <strong>
                      {SCENARIO_LABELS[matchResults[row.id].scenario] ||
                        `场景 ${matchResults[row.id].scenario}`}
                      {matchResults[row.id].rule_version
                        ? ` · 规则版本 v${matchResults[row.id].rule_version}`
                        : ""}
                    </strong>
                    <ul>
                      {matchResults[row.id].offers.map((offer) => (
                        <li key={offer.offer_id}>
                          Top{offer.rank} · 候选 {offer.candidate_user_id}
                          {offer.explanation ? ` · ${offer.explanation}` : ""}
                        </li>
                      ))}
                      {matchResults[row.id].offers.length === 0 ? (
                        <li>本轮无自动派单（人工兜底）。</li>
                      ) : null}
                    </ul>
                    {matchResults[row.id].rejected.length > 0 ? (
                      <p className="muted">
                        资格门淘汰 {matchResults[row.id].rejected.length} 人。
                      </p>
                    ) : null}
                  </div>
                ) : null}

                <h3 className="dispatch-console-trail-title">offer 留痕</h3>
                {(trail[row.id] ?? []).length === 0 ? (
                  <p className="muted">本包暂无 offer。</p>
                ) : null}
                <ul className="dispatch-console-trail">
                  {(trail[row.id] ?? []).map((offer) => (
                    <li key={offer.offer_id} className="dispatch-console-trail-row">
                      <strong>{offer.candidate_display_name}</strong>
                      <span className="muted">
                        {OFFER_STATUS_LABELS[offer.status] || offer.status} · 第{" "}
                        {offer.dispatch_round} 轮 ·{" "}
                        {offer.rank ? `Top${offer.rank}` : "指派"}
                      </span>
                      <span className="muted">
                        确认截止 {offer.deadline || "—"}
                      </span>
                      {(offer.status === "offered" || offer.status === "assigned") &&
                      row.dispatch_status !== "accepted" ? (
                        <button
                          type="button"
                          className="secondary-button"
                          disabled={busyKey !== null}
                          onClick={() => acceptOnBehalf(row, offer.candidate_user_id)}
                        >
                          {busyKey === `accept:${row.id}:${offer.candidate_user_id}`
                            ? "确认中…"
                            : "代接单"}
                        </button>
                      ) : null}
                      {offer.explanation ? (
                        <details>
                          <summary className="muted">释明</summary>
                          <p>{offer.explanation}</p>
                        </details>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  )
}
