import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { useAuth } from "../auth/AuthProvider"
import { useAsyncAction } from "../common/useAsyncAction"
import {
  FALLBACK_OPTIONS,
  mergeOptions,
  type WorkbenchOptions,
} from "../workbench/options"

// P4 报价/收款/合同（设计 §6，报价计算卡 v1.1 程序化）。
// 报价：系数输入 → 公式价 → 锚点三分支；claims 四值 accepted 之外黄标（§5.3）；
// 首单结项必须先回校缓冲 ×2.0 再成交回填（结项 checklist 固定一步）。
// 收款：B 50/50 / C 40/40/20 计划 + D+7/15/30/60 催款现算；G8 stop 按合同结算打标。
// 合同：只存指针（PDF 在 fdeops），四类 SOW 补位视图。

interface QuoteDto {
  id: string
  quote_key: string
  tier: string
  tier_label: string
  status: string
  preset: string | null
  inputs: {
    ideal_hours: number
    integration_factor: number
    data_factor: number
    compliance_factor: number
    buffer_factor: number
    hourly_rate: number
    cash_cost: number
    b_layer_score: number
    anchor_mode: string
  }
  computed: {
    realistic_hours: number
    total_cost: number
    formula_price: number
    b_layer_factor: number
    b_reference_price: number | null
    anchor_low: number
    anchor_high: number
    branch: string
    quote_low: number | null
    quote_high: number | null
    c_handling: string | null
    c_handling_label: string | null
  }
  ledger: {
    final_amount: number | null
    final_deviation_pct: number | null
    allowance_cap: number | null
    allowance_paid: number
    ticket_deal: boolean
    ticket_note: string
  }
  calibration: {
    actual_hours: number | null
    deviation_pct: number | null
    deviation_reason: string
    calibrated_buffer_factor: number | null
  }
  field_claims: Record<string, string>
  claims_summary: { accepted: number; total: number }
}

interface PaymentDto {
  id: string
  milestone_key: string
  sow_label: string
  collects: string
  timing: string
  ratio: number | null
  amount: number
  received_amount: number | null
  due_date: string | null
  received_at: string | null
  invoice_no: string | null
  status: string
  status_label: string
  settlement_reason: string | null
  note: string
  dunning_level: string | null
  dunning_label: string
  overdue?: boolean
}

interface PaymentBoardDto {
  payments: PaymentDto[]
  summary: {
    receivable: number
    received: number
    outstanding: number
    overdue: number
    dunning_counts: Record<string, number>
  }
}

interface ContractDto {
  id?: string
  sow_type: string
  sow_label: string
  recorded?: boolean
  signed_at?: string | null
  payment_terms?: string
  acceptance_window_days?: number
  termination_terms?: string
  source_uri?: string | null
  content_hash?: string | null
}

interface CommercialBoardProps {
  projectId: string
  canManage: boolean
}

// J4：档内偏离「×1.40 档内升级」是唯一触发 C 分支的档位——收敛为单一常量，
// 改一处漏两处会静默漏传 c_handling（服务端 400）。
const C_BRANCH_INTEGRATION_FACTOR = 1.4
// J5：B 层分的上下界（冷启动 ≤5，稳态 ≤10）。HTML max 拦不住键盘输入，
// 因此输入时必须上下界都夹。
const B_SCORE_COLD_START_MAX = 5
const B_SCORE_STEADY_MAX = 10
const B_SCORE_MIN = 0

const CLAIM_ORDER = ["estimated", "claimed", "measured", "accepted"] as const

const CLAIM_LABEL: Record<string, string> = {
  estimated: "初始假设",
  claimed: "已声明",
  measured: "已实测",
  accepted: "已核验",
}

const CLAIM_FIELD_LABEL: Record<string, string> = {
  ideal_hours: "基线工时",
  integration_factor: "档内偏离",
  data_factor: "数据成熟度",
  compliance_factor: "合规系数",
  buffer_factor: "缓冲 ×2.0",
  hourly_rate: "时薪",
  cash_cost: "现金成本",
  b_layer_score: "B 层分",
  formula_price: "公式价",
  final_amount: "成交价",
  actual_hours: "实际工时",
}

const fmt = (value: number | null | undefined): string =>
  value === null || value === undefined ? "—" : `¥${value.toLocaleString("zh-CN")}`

/** J5：B 层分夹上下界——HTML min/max 拦不住键盘输入，负数/越界都须在提交前夹住。 */
export function clampBScore(value: number, anchorMode: string): number {
  if (!Number.isFinite(value)) return B_SCORE_MIN
  const max =
    anchorMode === "cold_start" ? B_SCORE_COLD_START_MAX : B_SCORE_STEADY_MAX
  return Math.min(Math.max(value, B_SCORE_MIN), max)
}

// 表单数字入参统一走这里（NaN/负数/0 前端就拦，错误消息进 actionError 展示）
function parsePositive(raw: string, label: string): number {
  const value = Number(raw)
  if (!Number.isFinite(value) || value <= 0) throw new Error(`${label} 必须是正数`)
  return value
}

function parsePositiveInt(raw: string, label: string): number {
  const value = Number(raw)
  if (!Number.isInteger(value) || value < 1) throw new Error(`${label} 必须是 ≥1 的整数`)
  return value
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function errorText(caught: unknown): string {
  if (isRecord(caught) && typeof caught.message === "string") return caught.message
  return String(caught)
}

export function CommercialBoard({ projectId, canManage }: CommercialBoardProps) {
  const { apiRequest } = useAuth()
  const [quotes, setQuotes] = useState<QuoteDto[]>([])
  const [board, setBoard] = useState<PaymentBoardDto | null>(null)
  const [contracts, setContracts] = useState<ContractDto[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [actionError, setActionError] = useState("")
  const [draftHtml, setDraftHtml] = useState<{ key: string; html: string } | null>(null)
  const [options, setOptions] = useState<WorkbenchOptions>(FALLBACK_OPTIONS)
  const sequenceRef = useRef(0)
  const enc = encodeURIComponent(projectId)

  // J1：业务枚举（价格档位 / C 分支 / SOW）由服务端下发；取不到用本地兜底。
  useEffect(() => {
    let cancelled = false
    void apiRequest<unknown>("/api/v1/workbench/options", { method: "GET" })
      .then((payload) => {
        if (!cancelled) setOptions(mergeOptions(payload))
      })
      .catch(() => {
        if (!cancelled) setOptions(FALLBACK_OPTIONS)
      })
    return () => {
      cancelled = true
    }
  }, [apiRequest])

  const load = useCallback(async (): Promise<void> => {
    const sequence = ++sequenceRef.current
    try {
      const [quotesView, boardView, contractsView] = await Promise.all([
        apiRequest<unknown>(`/api/v1/projects/${enc}/quotes`, { method: "GET" }),
        apiRequest<unknown>(`/api/v1/projects/${enc}/payments`, { method: "GET" }),
        apiRequest<unknown>(`/api/v1/projects/${enc}/contracts`, { method: "GET" }),
      ])
      if (sequence !== sequenceRef.current) return
      if (!isRecord(quotesView) || !Array.isArray(quotesView.quotes)) throw new Error("invalid quotes view")
      if (!isRecord(boardView) || !Array.isArray(boardView.payments)) throw new Error("invalid payments view")
      if (!isRecord(contractsView) || !Array.isArray(contractsView.contracts)) throw new Error("invalid contracts view")
      setQuotes(quotesView.quotes as QuoteDto[])
      setBoard(boardView as unknown as PaymentBoardDto)
      setContracts(contractsView.contracts as ContractDto[])
      setError("")
    } catch (caught) {
      if (sequence !== sequenceRef.current) return
      setError(errorText(caught))
    } finally {
      if (sequence === sequenceRef.current) setLoading(false)
    }
  }, [apiRequest, enc])

  useEffect(() => {
    setLoading(true)
    setDraftHtml(null)
    void load()
  }, [load])

  const mutate = useCallback(
    async (run: () => Promise<unknown>): Promise<void> => {
      setActionError("")
      try {
        await run()
        await load()
      } catch (caught) {
        setActionError(errorText(caught))
      }
    },
    [load],
  )

  const post = useCallback(
    (path: string, body: unknown): Promise<unknown> =>
      apiRequest<unknown>(`/api/v1/projects/${enc}${path}`, {
        method: "POST",
        body,
        retryAfterAuthRefresh: true,
      }),
    [apiRequest, enc],
  )

  const loadDraft = useCallback(
    async (quoteKey: string): Promise<string> => {
      const data = await apiRequest<unknown>(
        `/api/v1/projects/${enc}/quotes/${encodeURIComponent(quoteKey)}/draft`,
        { method: "GET" },
      )
      if (!isRecord(data) || typeof data.html !== "string") throw new Error("invalid draft")
      return data.html
    },
    [apiRequest, enc],
  )

  const summary = useMemo(() => {
    if (!board) return null
    const dunning = board.summary.dunning_counts
    const levels = (["d7", "d15", "d30", "d60"] as const).filter((k) => dunning[k] > 0)
    return { ...board.summary, levels }
  }, [board])

  if (loading) return <div className="panel">加载报价 / 收款 / 合同……</div>
  if (error)
    return (
      <div className="panel">
        <p className="form-error banner" role="alert">{error}</p>
      </div>
    )

  return (
    <div className="commercial-board">
      {actionError ? <div className="panel gate-fail-exit">{actionError}</div> : null}

      <section className="panel">
        <h3>报价台账（报价卡 v1.1）</h3>
        {canManage ? <QuoteCreateForm post={post} mutate={mutate} options={options} /> : null}
        {quotes.length === 0 ? (
          <p className="supporting-copy">暂无报价。首单用「首单默认参数」一键取值（卡 §5.4）。</p>
        ) : (
          <div className="quote-list">
            {quotes.map((quote) => (
              <QuoteCard
                key={quote.id}
                quote={quote}
                canManage={canManage}
                post={post}
                mutate={mutate}
                loadDraft={loadDraft}
                draftHtml={draftHtml}
                setDraftHtml={setDraftHtml}
              />
            ))}
          </div>
        )}
      </section>

      <section className="panel">
        <h3>收款看板（D+7/15/30/60 四级催款）</h3>
        {canManage ? <PlanForm post={post} mutate={mutate} options={options} /> : null}
        {summary ? (
          <div className="payment-summary">
            <span>应收 {fmt(summary.receivable)}</span>
            <span>已收 {fmt(summary.received)}</span>
            <span>未收 {fmt(summary.outstanding)}</span>
            <span className={summary.overdue > 0 ? "badge danger" : "badge muted"}>
              逾期 {fmt(summary.overdue)}
            </span>
            {summary.levels.length > 0 ? (
              <span className="badge warning">
                催款 {summary.levels.map((l) => `${l.toUpperCase()}×${summary.dunning_counts[l]}`).join(" ")}
              </span>
            ) : null}
          </div>
        ) : null}
        <table className="payment-table">
          <thead>
            <tr>
              <th>里程碑</th>
              <th>款项</th>
              <th>金额</th>
              <th>状态</th>
              <th>到期 / 到账</th>
              <th>催款级</th>
              {canManage ? <th>操作</th> : null}
            </tr>
          </thead>
          <tbody>
            {(board?.payments ?? []).map((payment) => (
              <PaymentRow key={payment.id} payment={payment} canManage={canManage} post={post} mutate={mutate} />
            ))}
            {(board?.payments ?? []).length === 0 ? (
              <tr>
                <td colSpan={canManage ? 7 : 6} className="supporting-copy">
                  暂无收款计划。B 试点按 50/50 生成两行（G4 预付 / G8 尾款）。
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <h3>合同台账（只存指针，PDF 在 fdeops）</h3>
        <div className="contract-grid">
          {contracts.map((contract) => (
            <ContractCard key={contract.sow_type} contract={contract} canManage={canManage} post={post} mutate={mutate} />
          ))}
        </div>
      </section>
    </div>
  )
}

type Post = (path: string, body: unknown) => Promise<unknown>
type Mutate = (run: () => Promise<unknown>) => Promise<void>

function QuoteCreateForm({
  post,
  mutate,
  options,
}: {
  post: Post
  mutate: Mutate
  /** J1：价格档位 / C 分支选项由服务端选项表下发（含本地兜底） */
  options: WorkbenchOptions
}) {
  const [busy, setBusy] = useState(false)
  const [tier, setTier] = useState("light")
  const [anchorMode, setAnchorMode] = useState("cold_start")
  const [hourly, setHourly] = useState(150)
  const [dataFactor, setDataFactor] = useState(1.0)
  const [compliance, setCompliance] = useState(1.0)
  const [integration, setIntegration] = useState(1.0)
  const [bScore, setBScore] = useState(3)
  const [cHandling, setCHandling] = useState("scope_cut")

  // 防重入：建报价无服务端幂等键，双击会产出删不掉的重复台账行
  const run = (action: () => Promise<void>): void => {
    if (busy) return
    setBusy(true)
    void action().finally(() => setBusy(false))
  }

  const submitPreset = (): Promise<void> =>
    mutate(() => post("/quotes", { preset: "first_order_defaults" }))

  const submitCustom = (): Promise<void> =>
    mutate(() =>
      post("/quotes", {
        tier,
        anchor_mode: anchorMode,
        hourly_rate: hourly,
        data_factor: dataFactor,
        compliance_factor: compliance,
        integration_factor: integration,
        b_layer_score: bScore,
        // 与上方渲染条件同判：任意档位出现 C 分支都必须带上四选一
        ...(integration === C_BRANCH_INTEGRATION_FACTOR ? { c_handling: cHandling } : {}),
      }),
    )

  return (
    <div className="quote-create">
      <button type="button" className="primary-button compact" disabled={busy} onClick={() => run(submitPreset)}>
        首单默认参数（轻量 / ¥150/h / ×1.0 / 冷启动锚点）
      </button>
      <details className="quote-advanced">
        <summary>自定义系数</summary>
        <div className="gate-form-row">
          <label>
            档位
            <select value={tier} onChange={(e) => setTier(e.target.value)}>
              {options.price_tiers.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </label>
          <label>
            锚点
            <select
              value={anchorMode}
              onChange={(e) => {
                const mode = e.target.value
                setAnchorMode(mode)
                // 冷启动上限 5 分：切回冷启动时把越界的分数夹回来（HTML max 拦不住键盘输入）
                setBScore((score) => clampBScore(score, mode))
              }}
            >
              <option value="cold_start">冷启动（前 3 单）</option>
              <option value="steady">稳态（第 4 单起）</option>
            </select>
          </label>
          <label>
            时薪
            <select value={hourly} onChange={(e) => setHourly(Number(e.target.value))}>
              <option value={150}>¥150（首单）</option>
              <option value={180}>¥180（第 2-3 单）</option>
              <option value={400}>¥400（稳态）</option>
            </select>
          </label>
          <label>
            数据成熟度
            <select value={dataFactor} onChange={(e) => setDataFactor(Number(e.target.value))}>
              <option value={0.8}>×0.8 A 干净</option>
              <option value={1.0}>×1.0 B 一般</option>
              <option value={1.3}>×1.3 C 脏</option>
              <option value={1.6}>×1.6 D 极脏（治理段须单列）</option>
            </select>
          </label>
          <label>
            合规
            <select value={compliance} onChange={(e) => setCompliance(Number(e.target.value))}>
              <option value={1.0}>×1.0 无</option>
              <option value={1.2}>×1.2 等保/私有化</option>
              <option value={1.35}>×1.35 跨国审计</option>
            </select>
          </label>
          <label>
            档内偏离
            <select value={integration} onChange={(e) => setIntegration(Number(e.target.value))}>
              <option value={0.75}>×0.75 档内降级</option>
              <option value={1.0}>×1.00 默认</option>
              <option value={C_BRANCH_INTEGRATION_FACTOR}>×1.40 档内升级（优先改上一档）</option>
            </select>
          </label>
          <label>
            B 层分（冷启动 ≤5）
            <input
              type="number"
              min={B_SCORE_MIN}
              max={anchorMode === "cold_start" ? B_SCORE_COLD_START_MAX : B_SCORE_STEADY_MAX}
              value={bScore}
              onChange={(e) => setBScore(clampBScore(Number(e.target.value), anchorMode))}
            />
          </label>
          {integration === C_BRANCH_INTEGRATION_FACTOR ? (
            <label>
              C 分支处理
              <select value={cHandling} onChange={(e) => setCHandling(e.target.value)}>
                {options.c_handling_options.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
        <button type="button" className="secondary-button compact" disabled={busy} onClick={() => run(submitCustom)}>
          按上述系数建报价
        </button>
      </details>
    </div>
  )
}

function QuoteCard({
  quote,
  canManage,
  post,
  mutate,
  loadDraft,
  draftHtml,
  setDraftHtml,
}: {
  quote: QuoteDto
  canManage: boolean
  post: Post
  mutate: Mutate
  loadDraft: (quoteKey: string) => Promise<string>
  draftHtml: { key: string; html: string } | null
  setDraftHtml: (value: { key: string; html: string } | null) => void
}) {
  const [calActual, setCalActual] = useState("")
  const [calReason, setCalReason] = useState("")
  const [finalAmount, setFinalAmount] = useState("")
  const [firstYear, setFirstYear] = useState("")
  const [approvalCap, setApprovalCap] = useState("")
  const [ticketDeal, setTicketDeal] = useState(false)
  const [ticketNote, setTicketNote] = useState("")
  const [draftError, setDraftError] = useState("")
  const allAccepted = quote.claims_summary.accepted === quote.claims_summary.total
  const needsCalibration = quote.preset === "first_order_defaults" && quote.calibration.actual_hours === null

  const showDraft = async (): Promise<void> => {
    if (draftHtml?.key === quote.quote_key) {
      setDraftHtml(null)
      return
    }
    setDraftError("")
    setDraftHtml({ key: quote.quote_key, html: "" })
    try {
      const html = await loadDraft(quote.quote_key)
      setDraftHtml({ key: quote.quote_key, html })
    } catch (caught) {
      setDraftHtml(null)
      setDraftError(errorText(caught))
    }
  }

  return (
    <article className={`quote-card status-${quote.status === "finalized" ? "passed" : "evidence"}`}>
      <header className="quote-card-head">
        <strong>
          {quote.quote_key} · {quote.tier_label}
          {quote.preset === "first_order_defaults" ? "（首单默认参数）" : ""}
        </strong>
        <span className={`badge ${allAccepted ? "success" : "warning"}`}>
          {allAccepted ? "数字全核验" : `claims ${quote.claims_summary.accepted}/${quote.claims_summary.total} 核验`}
        </span>
        <span className={`badge ${quote.status === "finalized" ? "success" : "muted"}`}>
          {quote.status === "finalized" ? "已成交回填" : "草稿"}
        </span>
      </header>
      <div className="quote-metrics">
        <span>realistic {quote.computed.realistic_hours} h</span>
        <span>成本 {fmt(quote.computed.total_cost)}</span>
        <span className="quote-formula">公式价 {fmt(quote.computed.formula_price)}</span>
        <span>
          锚点 {fmt(quote.computed.anchor_low)}–{fmt(quote.computed.anchor_high)}
        </span>
        <span className={`badge ${quote.computed.branch === "C" ? "danger" : "muted"}`}>
          {quote.computed.branch} 分支
          {quote.computed.c_handling_label ? ` · ${quote.computed.c_handling_label}` : ""}
        </span>
        {quote.computed.quote_low !== null ? (
          <span>
            建议报价 {fmt(quote.computed.quote_low)} – {fmt(quote.computed.quote_high)}
            {quote.computed.branch === "B" && quote.computed.b_reference_price !== null
              ? `（B 层建议点 ${fmt(quote.computed.b_reference_price)}）`
              : ""}
          </span>
        ) : (
          <span className="supporting-copy">超锚点不许硬报（缩范围/拆分期/协作/门票单）</span>
        )}
      </div>
      <div className="quote-claims">
        {Object.entries(quote.field_claims).map(([field, status]) => {
          const index = CLAIM_ORDER.indexOf(status as (typeof CLAIM_ORDER)[number])
          // 未知状态不提供前进按钮（服务端只写四个合法值，防御）
          const next = index >= 0 ? CLAIM_ORDER[Math.min(index + 1, 3)] : null
          const canAdvance = canManage && next !== null && next !== status
          return (
            <button
              key={field}
              type="button"
              className={`claim-chip ${status === "accepted" ? "accepted" : "yellow"}`}
              disabled={!canAdvance}
              title={canAdvance && next ? `前进到 ${CLAIM_LABEL[next]}` : CLAIM_LABEL[status] ?? status}
              onClick={() =>
                void mutate(() =>
                  post(`/quotes/${encodeURIComponent(quote.quote_key)}/claims`, {
                    field,
                    claim_status: next,
                  }),
                )
              }
            >
              {CLAIM_FIELD_LABEL[field] ?? field}·{CLAIM_LABEL[status] ?? status}
            </button>
          )
        })}
      </div>
      {quote.calibration.actual_hours !== null ? (
        <p className="quote-calibration">
          回校：实际 {quote.calibration.actual_hours} h（偏差 {((quote.calibration.deviation_pct ?? 0) * 100).toFixed(1)}%，
          建议缓冲 ×{quote.calibration.calibrated_buffer_factor}）——{quote.calibration.deviation_reason}
        </p>
      ) : needsCalibration ? (
        <p className="quote-calibration pending">首单结项必回校缓冲 ×2.0（结项 checklist 固定一步）</p>
      ) : null}
      {quote.ledger.final_amount !== null ? (
        <p className="quote-ledger">
          成交 {fmt(quote.ledger.final_amount)}（较锚点下沿 {((quote.ledger.final_deviation_pct ?? 0) * 100).toFixed(1)}%）·
          可让利 {fmt(quote.ledger.allowance_cap)} · 已让 {fmt(quote.ledger.allowance_paid)}
          {quote.ledger.ticket_deal ? " · 门票单" : ""}
        </p>
      ) : null}
      {canManage ? (
        <div className="quote-actions">
          {quote.calibration.actual_hours === null ? (
            <div className="gate-form-row">
              <input placeholder="实际工时 h" value={calActual} onChange={(e) => setCalActual(e.target.value)} />
              <input placeholder="回校结论（deviation_reason 必填）" value={calReason} onChange={(e) => setCalReason(e.target.value)} />
              <button
                type="button"
                className="secondary-button compact"
                disabled={!calActual || !calReason}
                onClick={() =>
                  void mutate(async () =>
                    post(`/quotes/${encodeURIComponent(quote.quote_key)}/calibrate`, {
                      actual_hours: parsePositive(calActual, "实际工时"),
                      deviation_reason: calReason,
                    }),
                  )
                }
              >
                回校缓冲
              </button>
            </div>
          ) : null}
          {quote.status === "draft" ? (
            <div className="gate-form-row">
              <input placeholder="成交价" value={finalAmount} onChange={(e) => setFinalAmount(e.target.value)} />
              <input placeholder="首年可回收价值（选填）" value={firstYear} onChange={(e) => setFirstYear(e.target.value)} />
              <input placeholder="客户单笔审批上限（选填）" value={approvalCap} onChange={(e) => setApprovalCap(e.target.value)} />
              <label className="inline-check">
                <input type="checkbox" checked={ticketDeal} onChange={(e) => setTicketDeal(e.target.checked)} /> 门票单
              </label>
              {ticketDeal ? (
                <input placeholder="亏损额与补回路径（门票单必填）" value={ticketNote} onChange={(e) => setTicketNote(e.target.value)} />
              ) : null}
              <button
                type="button"
                className="primary-button compact"
                disabled={!finalAmount || (ticketDeal && !ticketNote)}
                onClick={() =>
                  void mutate(async () =>
                    post(`/quotes/${encodeURIComponent(quote.quote_key)}/finalize`, {
                      final_amount: parsePositive(finalAmount, "成交价"),
                      ...(firstYear ? { first_year_recoverable_value: parsePositive(firstYear, "首年可回收价值") } : {}),
                      ...(approvalCap ? { approval_cap: parsePositive(approvalCap, "审批上限") } : {}),
                      ...(ticketDeal ? { ticket_deal: true, ticket_note: ticketNote } : {}),
                    }),
                  )
                }
              >
                成交回填
              </button>
            </div>
          ) : null}
          <button type="button" className="secondary-button compact" onClick={() => void showDraft()}>
            {draftHtml?.key === quote.quote_key ? "收起草稿" : "预览报价单草稿"}
          </button>
        </div>
      ) : null}
      {draftError ? <p className="form-error banner" role="alert">{draftError}</p> : null}
      {draftHtml?.key === quote.quote_key ? (
        draftHtml.html ? (
          <iframe title="报价单草稿" sandbox="" srcDoc={draftHtml.html} className="quote-draft-frame" />
        ) : (
          <p className="supporting-copy">加载草稿……</p>
        )
      ) : null}
    </article>
  )
}

function PlanForm({
  post,
  mutate,
  options,
}: {
  post: Post
  mutate: Mutate
  /** J1：SOW 类型选项由服务端选项表下发（含本地兜底） */
  options: WorkbenchOptions
}) {
  const [sow, setSow] = useState("b")
  const [base, setBase] = useState("")
  const [replace, setReplace] = useState(false)
  return (
    <div className="gate-form-row">
      <select value={sow} onChange={(e) => setSow(e.target.value)}>
        {options.sow_options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
      <input placeholder="合同基数金额 ¥" value={base} onChange={(e) => setBase(e.target.value)} />
      <label className="inline-check">
        <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} /> 重建已有计划
      </label>
      <button
        type="button"
        className="primary-button compact"
        disabled={!base}
        onClick={() =>
          void mutate(async () => post("/payments/plan", { sow_type: sow, base_amount: parsePositive(base, "合同基数金额"), replace }))
        }
      >
        生成收款计划
      </button>
    </div>
  )
}

function PaymentRow({
  payment,
  canManage,
  post,
  mutate,
}: {
  payment: PaymentDto
  canManage: boolean
  post: Post
  mutate: Mutate
}) {
  const [dueDate, setDueDate] = useState(payment.due_date ?? "")
  const [received, setReceived] = useState("")
  const [invoiceNo, setInvoiceNo] = useState(payment.invoice_no ?? "")
  // S1/F1：设到期是本地写操作，护栏挂在实际渲染按钮的子组件作用域内。
  const action = useAsyncAction()
  const dunningClass =
    payment.dunning_level === "d60" || payment.dunning_level === "d30"
      ? "badge danger"
      : payment.dunning_level
        ? "badge warning"
        : "badge muted"
  return (
    <tr>
      <td>
        <strong>{payment.milestone_key}</strong>
        <div className="supporting-copy">{payment.sow_label}</div>
      </td>
      <td>
        {payment.collects}
        <div className="supporting-copy">{payment.timing}</div>
        {payment.settlement_reason === "g8_stop" ? (
          <span className="badge danger">G8 stop · 按合同结算</span>
        ) : null}
      </td>
      <td>
        {fmt(payment.amount)}
        {payment.ratio !== null ? <div className="supporting-copy">{payment.ratio * 100}%</div> : null}
      </td>
      <td>
        <span className={payment.status === "received" ? "badge success" : "badge muted"}>{payment.status_label}</span>
        {payment.received_amount !== null ? (
          <div className="supporting-copy">实收 {fmt(payment.received_amount)}</div>
        ) : null}
      </td>
      <td className="supporting-copy">
        {payment.due_date ? `到期 ${payment.due_date}` : "未设到期日"}
        {payment.received_at ? ` / 到账 ${payment.received_at}` : ""}
      </td>
      <td>
        <span className={dunningClass}>{payment.dunning_label}</span>
        {payment.overdue && !payment.dunning_level ? (
          <div className="badge warning">已逾期（未到 D+7 催款级）</div>
        ) : null}
      </td>
      {canManage ? (
        <td className="payment-ops">
          {payment.received_at === null ? (
            <>
              <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
              <button
                type="button"
                className="secondary-button compact"
                disabled={!dueDate || action.isBusy}
                aria-busy={action.busyKey === `due:${payment.milestone_key}`}
                onClick={() => void action.run(`due:${payment.milestone_key}`, () => mutate(() => post(`/payments/${encodeURIComponent(payment.milestone_key)}`, { due_date: dueDate })))}
              >
                {action.busyKey === `due:${payment.milestone_key}` ? "处理中…" : "设到期"}
              </button>
              <input placeholder="实收金额" value={received} onChange={(e) => setReceived(e.target.value)} />
              <input placeholder="发票号" value={invoiceNo} onChange={(e) => setInvoiceNo(e.target.value)} />
              <button
                type="button"
                className="primary-button compact"
                disabled={!received && !invoiceNo}
                onClick={() =>
                  void mutate(async () =>
                    post(`/payments/${encodeURIComponent(payment.milestone_key)}`, {
                      ...(received ? { received_amount: parsePositive(received, "实收金额") } : {}),
                      ...(invoiceNo ? { invoice_no: invoiceNo } : {}),
                    }),
                  )
                }
              >
                回填
              </button>
            </>
          ) : (
            <span className="supporting-copy">{payment.invoice_no ?? "已到账"}</span>
          )}
        </td>
      ) : null}
    </tr>
  )
}

function ContractCard({
  contract,
  canManage,
  post,
  mutate,
}: {
  contract: ContractDto
  canManage: boolean
  post: Post
  mutate: Mutate
}) {
  const [signedAt, setSignedAt] = useState(contract.signed_at ?? "")
  const [terms, setTerms] = useState(contract.payment_terms ?? "")
  const [window, setWindow] = useState(String(contract.acceptance_window_days ?? 15))
  const [termination, setTermination] = useState(contract.termination_terms ?? "")
  const [sourceUri, setSourceUri] = useState(contract.source_uri ?? "")
  const recorded = contract.recorded === true
  return (
    <div className={`contract-card ${recorded ? "" : "empty"}`}>
      <header>
        <strong>{contract.sow_label}</strong>
        {recorded ? <span className="badge success">已建档</span> : <span className="badge muted">未建档</span>}
      </header>
      {recorded ? (
        <dl className="contract-meta">
          <dt>签约日</dt>
          <dd>{contract.signed_at ?? "—"}</dd>
          <dt>验收窗口</dt>
          <dd>{contract.acceptance_window_days} 天</dd>
          <dt>账期</dt>
          <dd>{contract.payment_terms || "—"}</dd>
          <dt>终止条款</dt>
          <dd>{contract.termination_terms || "—"}</dd>
          <dt>指针</dt>
          <dd className="mono">{contract.source_uri ?? "—"}</dd>
        </dl>
      ) : null}
      {canManage ? (
        <div className="gate-form">
          <div className="gate-form-row">
            <input type="date" value={signedAt} onChange={(e) => setSignedAt(e.target.value)} />
            <input
              type="number"
              min={1}
              value={window}
              onChange={(e) => setWindow(e.target.value)}
              title="验收窗口天数"
            />
          </div>
          <input placeholder="账期（如 B 50/50）" value={terms} onChange={(e) => setTerms(e.target.value)} />
          <input placeholder="终止条款摘要" value={termination} onChange={(e) => setTermination(e.target.value)} />
          <input
            placeholder="fdeops:// 指针（PDF 在 fdeops 文件系统）"
            value={sourceUri}
            onChange={(e) => setSourceUri(e.target.value)}
          />
          <button
            type="button"
            className="secondary-button compact"
            disabled={!sourceUri}
            onClick={() =>
              void mutate(async () =>
                post("/contracts", {
                  sow_type: contract.sow_type,
                  ...(signedAt ? { signed_at: signedAt } : {}),
                  acceptance_window_days: window.trim() === "" ? 15 : parsePositiveInt(window, "验收窗口"),
                  ...(terms ? { payment_terms: terms } : {}),
                  ...(termination ? { termination_terms: termination } : {}),
                  source_uri: sourceUri,
                }),
              )
            }
          >
            {recorded ? "更新" : "登记"}
          </button>
        </div>
      ) : null}
    </div>
  )
}
