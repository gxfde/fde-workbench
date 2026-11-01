import { useCallback, useEffect, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"

/** 争议处理页（B3 运维页簇；§6.6 四层仲裁 + §7.5 T+30 对账）。
 *  L0 机器对账草稿只读（禁人工打开）；L1/L2 可人工打开与裁决——处罚类
 *  动作 100% 人工，页面只是人工操作的载体。l0_report_source_uri 是指针
 *  红线字段：只展示指针，永不内联对账单本体。 */

export interface DisputeView {
  dispute_id: string
  package_id: string
  package_code: string
  settlement_key: string | null
  layer: string
  status: string
  amount: number | null
  reason: string
  resolution: string
  l0_report_source_uri: string | null
  snapshot_hash: string | null
  opened_by: string | null
  handled_by: string | null
  resolved_at: string | null
  created_at: string | null
}

export function isDisputeView(value: unknown): value is DisputeView {
  if (typeof value !== "object" || value === null) return false
  const row = value as Record<string, unknown>
  return typeof row.dispute_id === "string" && typeof row.package_id === "string"
}

export const DISPUTE_LAYER_LABELS: Record<string, string> = {
  L0: "L0 机器对账",
  L1: "L1 平台运营",
  L2: "L2 双人复核",
  L3: "L3 外部仲裁",
}

export const DISPUTE_STATUS_LABELS: Record<string, string> = {
  draft: "对账草稿",
  open: "待处理",
  reviewing: "复核中",
  resolved: "已裁决",
  closed: "已关闭",
}

export function formatDisputeAmount(amount: number | null): string {
  if (amount === null) return "—"
  return `¥${amount.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`
}

export function canResolve(status: string): boolean {
  return status === "open" || status === "reviewing"
}

export function DisputesPage() {
  const { apiRequest } = useAuth()
  const [disputes, setDisputes] = useState<DisputeView[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [actionError, setActionError] = useState("")
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [openForm, setOpenForm] = useState(false)
  const [draft, setDraft] = useState({
    package_id: "",
    layer: "L1",
    reason: "",
    amount: "",
    settlement_key: "",
  })
  const [resolveDraft, setResolveDraft] = useState<{
    disputeId: string
    resolution: string
    close: boolean
  } | null>(null)
  const requestSequence = useRef(0)

  const load = useCallback(() => {
    const sequence = ++requestSequence.current
    setLoading(true)
    setError("")
    void apiRequest<unknown>("/api/v1/dispatch/disputes", { method: "GET" })
      .then((payload) => {
        if (sequence !== requestSequence.current) return
        // goal-d9 fix: apiRequest already unwraps the {data,error} envelope (latent bug family)
        setDisputes(Array.isArray(payload) ? payload.filter(isDisputeView) : [])
      })
      .catch((caught: unknown) => {
        if (sequence !== requestSequence.current) return
        setError(
          caught instanceof ApiClientError ? caught.message : "争议单加载失败，请稍后重试。"
        )
      })
      .finally(() => {
        if (sequence === requestSequence.current) setLoading(false)
      })
  }, [apiRequest])

  useEffect(() => {
    load()
  }, [load])

  const submitOpen = () => {
    if (!draft.package_id.trim() || !draft.reason.trim()) {
      setActionError("package_id 与非空 reason 必填（L0 由对账自动产，仅 L1/L2）。")
      return
    }
    setBusyKey("open")
    setActionError("")
    void apiRequest<unknown>("/api/v1/dispatch/disputes", {
      method: "POST",
      body: {
        package_id: draft.package_id.trim(),
        layer: draft.layer,
        reason: draft.reason,
        ...(draft.amount ? { amount: Number(draft.amount) } : {}),
        ...(draft.settlement_key ? { settlement_key: draft.settlement_key } : {}),
      },
    })
      .then(() => {
        setOpenForm(false)
        setDraft({ package_id: "", layer: "L1", reason: "", amount: "", settlement_key: "" })
        load()
      })
      .catch((caught: unknown) => {
        setActionError(
          caught instanceof ApiClientError ? caught.message : "打开争议失败，请稍后重试。"
        )
      })
      .finally(() => setBusyKey(null))
  }

  const submitResolve = (disputeId: string) => {
    if (!resolveDraft || !resolveDraft.resolution.trim()) {
      setActionError("裁决结论必填（处罚类动作 100% 人工，留痕担责）。")
      return
    }
    setBusyKey(`resolve:${disputeId}`)
    setActionError("")
    void apiRequest<unknown>(`/api/v1/dispatch/disputes/${disputeId}/resolve`, {
      method: "POST",
      body: { resolution: resolveDraft.resolution, close: resolveDraft.close },
    })
      .then(() => {
        setResolveDraft(null)
        load()
      })
      .catch((caught: unknown) => {
        setActionError(
          caught instanceof ApiClientError ? caught.message : "裁决失败，请稍后重试。"
        )
      })
      .finally(() => setBusyKey(null))
  }

  return (
    <section className="page" aria-label="争议处理">
      <header className="page-header">
        <div>
          <h1>争议处理</h1>
          <p className="page-subtitle">
            L0 机器对账草稿只读；L1/L2 人工打开与裁决（§6.6，处罚类动作 100% 人工）。
          </p>
        </div>
        <div className="row-actions">
          <button
            className="secondary-button"
            type="button"
            onClick={() => setOpenForm((prev) => !prev)}
          >
            {openForm ? "收起" : "打开争议"}
          </button>
          <button className="secondary-button" type="button" onClick={load}>
            刷新
          </button>
        </div>
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

      {openForm ? (
        <div className="dispatch-console-pool" aria-label="打开争议表单">
          <div className="dispatch-offer-actions">
            <select
              aria-label="争议层"
              value={draft.layer}
              onChange={(event) => setDraft({ ...draft, layer: event.target.value })}
            >
              <option value="L1">L1 平台运营（≤¥50,000）</option>
              <option value="L2">L2 双人复核</option>
            </select>
            <input
              aria-label="交付包 ID"
              placeholder="交付包 ID（从调度台复制）"
              value={draft.package_id}
              onChange={(event) => setDraft({ ...draft, package_id: event.target.value })}
            />
            <input
              aria-label="争议原因"
              placeholder="争议原因（必填）"
              value={draft.reason}
              onChange={(event) => setDraft({ ...draft, reason: event.target.value })}
            />
            <input
              aria-label="争议金额"
              placeholder="金额（选填）"
              inputMode="decimal"
              value={draft.amount}
              onChange={(event) => setDraft({ ...draft, amount: event.target.value })}
            />
            <input
              aria-label="结算键"
              placeholder="结算键（选填）"
              value={draft.settlement_key}
              onChange={(event) =>
                setDraft({ ...draft, settlement_key: event.target.value })
              }
            />
            <button
              type="button"
              className="primary-button"
              disabled={busyKey !== null}
              onClick={submitOpen}
            >
              {busyKey === "open" ? "提交中…" : "提交"}
            </button>
          </div>
        </div>
      ) : null}

      {!loading && !error && disputes.length === 0 ? (
        <p className="muted">暂无争议单。</p>
      ) : null}
      <ul className="dispatch-package-list">
        {disputes.map((row) => (
          <li key={row.dispute_id} className="dispatch-package-card">
            <div className="dispatch-offer-summary">
              <strong>
                {DISPUTE_LAYER_LABELS[row.layer] || row.layer} ·{" "}
                {DISPUTE_STATUS_LABELS[row.status] || row.status}
              </strong>
              <span>{row.package_code}</span>
              <span className="muted">金额 {formatDisputeAmount(row.amount)}</span>
              {row.settlement_key ? (
                <span className="muted">结算键 {row.settlement_key}</span>
              ) : null}
            </div>
            <dl className="dispatch-package-detail">
              <dt>原因</dt>
              <dd>{row.reason}</dd>
              {row.resolution ? (
                <>
                  <dt>裁决</dt>
                  <dd>{row.resolution}</dd>
                </>
              ) : null}
              {row.l0_report_source_uri ? (
                <>
                  <dt>对账单指针</dt>
                  <dd>
                    <code>{row.l0_report_source_uri}</code>
                  </dd>
                </>
              ) : null}
              <dt>快照锚</dt>
              <dd>
                <code>{row.snapshot_hash ? row.snapshot_hash.slice(0, 12) : "—"}</code>
              </dd>
              <dt>经手</dt>
              <dd>
                {row.opened_by ? `打开 ${row.opened_by}` : "对账自动产"}
                {row.handled_by ? ` · 裁决 ${row.handled_by}` : ""}
              </dd>
            </dl>
            {canResolve(row.status) ? (
              resolveDraft && resolveDraft.disputeId === row.dispute_id ? (
                <div className="dispatch-offer-actions">
                  <input
                    aria-label="裁决结论"
                    placeholder="裁决结论（必填留痕）"
                    value={resolveDraft.resolution}
                    onChange={(event) =>
                      setResolveDraft({ ...resolveDraft, resolution: event.target.value })
                    }
                  />
                  <label className="dispatch-console-candidate">
                    <input
                      type="checkbox"
                      checked={resolveDraft.close}
                      onChange={(event) =>
                        setResolveDraft({ ...resolveDraft, close: event.target.checked })
                      }
                    />
                    直接关闭
                  </label>
                  <button
                    type="button"
                    className="primary-button"
                    disabled={busyKey !== null}
                    onClick={() => submitResolve(row.dispute_id)}
                  >
                    {busyKey === `resolve:${row.dispute_id}` ? "提交中…" : "提交裁决"}
                  </button>
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => setResolveDraft(null)}
                  >
                    取消
                  </button>
                </div>
              ) : (
                <div className="dispatch-offer-actions">
                  <button
                    type="button"
                    className="primary-button"
                    onClick={() =>
                      setResolveDraft({
                        disputeId: row.dispute_id,
                        resolution: "",
                        close: false,
                      })
                    }
                  >
                    裁决
                  </button>
                </div>
              )
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  )
}
