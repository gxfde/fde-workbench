import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { auditFacts, summarizeAnchorAudit, type AnchorGrade } from "./anchorAudit"

// V3.1 P0-1 批B：访谈事实与需求审阅面板（discovery 消费面）。
// AI 抽取只是草稿生成器——逐条接受/拒绝/澄清永远是人工决策（任务书 §12
// 权限矩阵：Agent 可生成草稿，不得批准正式事实/需求）。来源定位三形态
// （line/transcript_segment/char_span）只读呈现，跳转锚交由纪要正文对照。
// 试点轮追加：line 定位条目按 source_ref 拉取纪要正文做本地锚点核验
// （A/B/C 分级只提示不裁决），列表分页加载缓解大纪要抽取的百级条目。

// 复核账条目（盲审追批零真名换代）：指纹条目（name 词典反解可空）＋疑似聚合
// 哨兵 {suspect_count}；旧形状（name 原文）宽容兼容。
interface RedactionEntryDto {
  name?: string | null
  name_hash?: string
  occurrences?: number
  matched_dict?: boolean
  suspect_count?: number
}

function redactionEntryLabel(entry: RedactionEntryDto): string {
  if (entry.suspect_count !== undefined) return "疑似企业名（未收录词典）"
  if (typeof entry.name === "string" && entry.name) return entry.name
  if (entry.name_hash) return `${entry.name_hash.slice(0, 8)}…`
  return "未知条目"
}

function redactionEntryCount(entry: RedactionEntryDto): number {
  return entry.suspect_count ?? entry.occurrences ?? 0
}

interface ExtractionDto {
  id: string
  source_type: string
  source_id: string
  source_sha256: string
  status: string
  extractor_version: string
  prompt_version: string
  ai_model: string | null
  completed_at: string | null
  failure_code: string | null
  failure_message: string | null
  redaction_entries: RedactionEntryDto[] | null
}

interface FactDto {
  id: string
  fact_type: string
  classification: string
  subject: string
  predicate: string
  object_value: unknown
  confidence: number | null
  source_ref: string
  source_locator: { type: string; line?: number; start_ms?: number; end_ms?: number; start?: number; end?: number }
  review_status: string
  review_comment: string | null
  reviewed_at: string | null
}

interface RequirementDto {
  id: string
  requirement_key: string
  title: string
  description: string | null
  requirement_type: string
  priority: string
  acceptance_criteria: string[]
  status: string
  approved_at: string | null
  review_comment: string | null
  source_fact_ids: string[]
  source_count: number
}

interface ExtractionListDto {
  items: ExtractionDto[]
}

interface FactListDto {
  items: FactDto[]
}

interface RequirementListDto {
  items: RequirementDto[]
}

interface MinutesRowDto {
  id: string
  title: string
}

const EXTRACTION_STATUS_LABEL: Record<string, string> = {
  queued: "排队中",
  running: "抽取中",
  review_required: "待审阅",
  failed: "失败",
}

const FACT_TYPE_LABEL: Record<string, string> = {
  process: "流程",
  role: "角色",
  system: "系统",
  rule: "规则",
  data_object: "数据对象",
  metric: "指标",
  constraint: "约束",
  pain_point: "痛点",
  decision: "决策",
  open_question: "开放问题",
}

const REVIEW_STATUS_LABEL: Record<string, string> = {
  pending: "待审",
  accepted: "已接受",
  rejected: "已拒绝",
  needs_clarification: "待澄清",
}

const CLASSIFICATION_LABEL: Record<string, string> = {
  customer_stated: "客户原话",
  ai_synthesized: "AI 归纳",
  ai_inferred: "AI 推断",
  open_question: "开放问题",
  human_added: "人工补充",
}

const REQUIREMENT_TYPE_LABEL: Record<string, string> = {
  functional: "功能",
  non_functional: "非功能",
  data: "数据",
  integration: "集成",
  security: "安全",
  operational: "运维",
}

const PRIORITY_LABEL: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
}

const FACT_PAGE_SIZE = 100

function label(map: Record<string, string>, value: string): string {
  return map[value] ?? value
}

function errorMessage(caught: unknown): string {
  if (caught instanceof ApiClientError) return caught.message
  if (caught instanceof Error) return caught.message
  return "操作失败，请重试。"
}

function formatDateTime(value: string | null): string {
  return value ? value.slice(0, 19).replace("T", " ") : "—"
}

function locatorText(locator: FactDto["source_locator"]): string {
  if (locator.type === "line") return `第 ${locator.line ?? "?"} 行`
  if (locator.type === "transcript_segment") return `${locator.start_ms ?? 0}–${locator.end_ms ?? 0} ms`
  if (locator.type === "char_span") return `字符 ${locator.start ?? "?"}–${locator.end ?? "?"}`
  return locator.type
}

function objectValueText(value: unknown): string {
  if (typeof value === "string") return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function minutesIdFromRef(sourceRef: string): string | null {
  const prefix = "interview_minutes:"
  return sourceRef.startsWith(prefix) ? sourceRef.slice(prefix.length) : null
}

interface DiscoveryPanelProps {
  projectId: string
  canManage: boolean
}

export function DiscoveryPanel({ projectId, canManage }: DiscoveryPanelProps) {
  const { apiRequest } = useAuth()
  const [minutes, setMinutes] = useState<MinutesRowDto[]>([])
  const [selectedMinutesId, setSelectedMinutesId] = useState("")
  const [extractions, setExtractions] = useState<ExtractionDto[]>([])
  const [facts, setFacts] = useState<FactDto[]>([])
  const [requirements, setRequirements] = useState<RequirementDto[]>([])
  const [factFilter, setFactFilter] = useState("")
  const [anchorFilter, setAnchorFilter] = useState<"all" | "suspect">("all")
  const [factsExhausted, setFactsExhausted] = useState(true)
  const [requirementsExhausted, setRequirementsExhausted] = useState(true)
  const [anchorAudit, setAnchorAudit] = useState<Map<string, AnchorGrade>>(new Map())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  // 批量接受进度（按钮级呈现——面板顶部的 notice 可能随长表滚出视口）。
  const [batchProgress, setBatchProgress] = useState<{ done: number; total: number } | null>(null)
  const [selectedFacts, setSelectedFacts] = useState<string[]>([])
  const [batchPreview, setBatchPreview] = useState<FactDto[]>([])
  const [batchReceipts, setBatchReceipts] = useState<Array<{ id: string; label: string; message: string }>>([])
  const [needsFactReload, setNeedsFactReload] = useState<string[]>([])
  const [loaded, setLoaded] = useState(false)
  const minutesContentRef = useRef<Map<string, string>>(new Map())
  const factsRef = useRef<FactDto[]>([])
  const loadGeneration = useRef(0)

  const loadFacts = useCallback(async (offset: number, replace: boolean, generation: number) => {
    const params = new URLSearchParams({ limit: String(FACT_PAGE_SIZE), offset: String(offset) })
    if (factFilter) params.set("review_status", factFilter)
    const factData = await apiRequest<FactListDto>(`/api/v1/projects/${projectId}/business-facts?${params.toString()}`, { method: "GET" })
    if (generation !== loadGeneration.current) return
    const page = factData.items
    setFacts((prev) => {
      const next = replace ? page : [...prev, ...page.filter((item) => !prev.some((p) => p.id === item.id))]
      factsRef.current = next
      return next
    })
    setFactsExhausted(page.length < FACT_PAGE_SIZE)
  }, [apiRequest, projectId, factFilter])

  const loadAll = useCallback(async () => {
    const generation = ++loadGeneration.current
    setLoaded(false)
    setError("")
    try {
      const [minutesData, extractionData, requirementData] = await Promise.all([
        apiRequest<{ items: MinutesRowDto[] }>(`/api/v1/interview-minutes?project_id=${projectId}&limit=50`, { method: "GET" }),
        apiRequest<ExtractionListDto>(`/api/v1/projects/${projectId}/discovery/extractions?limit=20`, { method: "GET" }),
        apiRequest<RequirementListDto>(`/api/v1/projects/${projectId}/requirements?limit=100`, { method: "GET" }),
      ])
      if (generation !== loadGeneration.current) return
      setMinutes(minutesData.items)
      setExtractions(extractionData.items)
      setRequirements(requirementData.items)
      setRequirementsExhausted(requirementData.items.length < 100)
      await loadFacts(0, true, generation)
      if (generation === loadGeneration.current) setLoaded(true)
    } catch (caught) {
      if (generation === loadGeneration.current) setError(errorMessage(caught))
    }
  }, [apiRequest, projectId, loadFacts])

  useEffect(() => {
    void loadAll()
    return () => { loadGeneration.current += 1 }
  }, [loadAll])

  // 锚点核验：需要正文的纪要按需拉取（缓存去重），缺失时该条不标级（不炸面板）。
  useEffect(() => {
    const needed = new Set<string>()
    for (const fact of facts) {
      if (fact.source_locator.type !== "line") continue
      const minutesId = minutesIdFromRef(fact.source_ref)
      if (minutesId && !minutesContentRef.current.has(minutesId)) needed.add(minutesId)
    }
    if (!needed.size) {
      setAnchorAudit(auditFacts(factsRef.current, minutesContentRef.current))
      return
    }
    let cancelled = false
    void (async () => {
      await Promise.all([...needed].map(async (minutesId) => {
        try {
          const detail = await apiRequest<{ content: string }>(`/api/v1/interview-minutes/${minutesId}`, { method: "GET" })
          minutesContentRef.current.set(minutesId, detail.content ?? "")
        } catch {
          minutesContentRef.current.set(minutesId, "")
        }
      }))
      if (!cancelled) setAnchorAudit(auditFacts(factsRef.current, minutesContentRef.current))
    })()
    return () => { cancelled = true }
  }, [facts, apiRequest])

  const anchorSummary = useMemo(() => summarizeAnchorAudit(anchorAudit), [anchorAudit])
  const visibleFacts = useMemo(() => {
    if (anchorFilter === "suspect") {
      return facts.filter((fact) => {
        const grade = anchorAudit.get(fact.id)
        return grade ? grade.grade !== "C" : false
      })
    }
    return facts
  }, [facts, anchorAudit, anchorFilter])

  const createExtraction = async () => {
    if (!selectedMinutesId) return
    setBusy(true); setError(""); setNotice("")
    try {
      const data = await apiRequest<ExtractionDto & { created: boolean }>(
        `/api/v1/projects/${projectId}/discovery/extractions`,
        // body 契约＝对象：主进程 serializeBody 统一 stringify 一次（预 stringify 会被二次编码 → 服务端收到字符串 → 4xx 零落库）。
        { method: "POST", body: { source_type: "interview_minutes", source_id: selectedMinutesId } },
      )
      setNotice(data.created ? "抽取任务已入队，完成后回到「待审阅」状态。" : "该来源已有抽取记录（同源同版本幂等），未重复创建。")
      await loadAll()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const rerunExtraction = async (extractionId: string) => {
    setBusy(true); setError("")
    try {
      await apiRequest(`/api/v1/discovery/extractions/${extractionId}/run`, { method: "POST" })
      setNotice("已重新入队。")
      await loadAll()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  // 审阅后就地更新该条状态（不整表刷新——保留已加载分页与锚点核验结果）。
  const reviewFact = async (factId: string, reviewStatus: string) => {
    setBusy(true); setError("")
    try {
      await apiRequest(`/api/v1/business-facts/${factId}/review`, {
        method: "PATCH",
        // 幂等审阅写：token 刷新后允许自动重发（否则 mutation_resubmit_required 中断操作）。
        retryAfterAuthRefresh: true,
        body: { review_status: reviewStatus },
      })
      setFacts((prev) => prev.map((fact) => (fact.id === factId ? { ...fact, review_status: reviewStatus } : fact)))
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const reviewRequirement = async (requirementId: string, status: string) => {
    setBusy(true); setError("")
    try {
      await apiRequest(`/api/v1/requirements/${requirementId}/review`, {
        method: "PATCH",
        // 幂等审阅写：token 刷新后允许自动重发。
        retryAfterAuthRefresh: true,
        body: { status },
      })
      setRequirements((prev) => prev.map((req) => (req.id === requirementId ? { ...req, status } : req)))
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const eligibleFacts = loaded && (!factFilter || factFilter === "pending")
    ? visibleFacts.filter((fact) => fact.review_status === "pending" && !needsFactReload.includes(fact.id))
    : []
  const selectedPending = eligibleFacts.filter((fact) => selectedFacts.includes(fact.id))

  const readBatchResults = async (ids: string[]) => {
    const found = new Map<string, FactDto>()
    const wanted = new Set(ids)
    // Omit the status filter: a settled fact may have left the active 待审 filter.
    const limit = Math.max(FACT_PAGE_SIZE, facts.length)
    for (let offset = 0; offset < limit && found.size < wanted.size; offset += FACT_PAGE_SIZE) {
      const data = await apiRequest<FactListDto>(
        `/api/v1/projects/${projectId}/business-facts?limit=${FACT_PAGE_SIZE}&offset=${offset}`, { method: "GET" },
      )
      for (const fact of data.items) if (wanted.has(fact.id)) found.set(fact.id, fact)
      if (data.items.length < FACT_PAGE_SIZE) break
    }
    setFacts((prev) => prev.map((fact) => found.get(fact.id) ?? fact))
    setNeedsFactReload((prev) => prev.filter((id) => !found.has(id)))
    setBatchReceipts((prev) => prev.map((row) => {
      const current = found.get(row.id)
      if (current) return { ...row, message: `${row.message}；回读状态：${label(REVIEW_STATUS_LABEL, current.review_status)}` }
      if (ids.includes(row.id)) return { ...row, message: "未在本次回读范围内找到，结果仍未确认。" }
      return row
    }))
  }

  const acceptPendingFacts = async () => {
    if (!canManage || busy || !batchPreview.length) return
    const pending = batchPreview
    setBatchPreview([])
    setSelectedFacts([])
    setBatchReceipts([])
    setBusy(true); setError("")
    const accepted: string[] = []
    const uncertain: string[] = []
    let done = 0
    for (const fact of pending) {
      setBatchProgress({ done, total: pending.length })
      setNotice(`正在接受 ${done + 1}/${pending.length}…`)
      let message: string
      try {
        await apiRequest(`/api/v1/business-facts/${fact.id}/review`, {
          method: "PATCH",
          body: { review_status: "accepted", expected_review_status: "pending" },
        })
        accepted.push(fact.id)
        message = "已接受"
      } catch (caught) {
        const status = caught instanceof ApiClientError ? caught.status : undefined
        if (status === 409) {
          message = "已不再待审，未写入"
          uncertain.push(fact.id)
        } else if (status && status >= 400 && status < 500 && status !== 408) {
          message = "请求被拒绝，未写入"
        } else {
          message = "写入结果未知"
          uncertain.push(fact.id)
        }
      }
      done += 1
      setBatchReceipts((prev) => [...prev, { id: fact.id, label: `${fact.subject} · ${fact.predicate}`, message }])
    }
    setFacts((prev) => prev.map((fact) => accepted.includes(fact.id) ? { ...fact, review_status: "accepted" } : fact))
    setNeedsFactReload((prev) => [...new Set([...prev, ...uncertain])])
    if (uncertain.length) {
      try { await readBatchResults(uncertain) } catch { setError("无法回读事实状态，未重试写入。") }
    }
    setBatchProgress(null)
    setNotice(accepted.length === pending.length ? `已批量接受 ${accepted.length} 条待审事实。` : `已接受 ${accepted.length}/${pending.length} 条，请查看逐项回执。`)
    setBusy(false)
  }

  const loadMoreFacts = async () => {
    setBusy(true); setError("")
    try {
      await loadFacts(facts.length, false, loadGeneration.current)
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const loadMoreRequirements = async () => {
    setBusy(true); setError("")
    try {
      const data = await apiRequest<RequirementListDto>(`/api/v1/projects/${projectId}/requirements?limit=100&offset=${requirements.length}`, { method: "GET" })
      setRequirements((prev) => [...prev, ...data.items.filter((item) => !prev.some((p) => p.id === item.id))])
      setRequirementsExhausted(data.items.length < 100)
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const anchorBadge = (fact: FactDto): AnchorGrade | null => anchorAudit.get(fact.id) ?? null

  return (
    <section id="discovery-panel" className="panel-stack" aria-label="访谈事实与需求">
      <h3>访谈事实与需求（AI 抽取草稿 · 人工审阅定案）</h3>
      {/* aria-live 容器不用 alert/status 角色：project-detail 等既有测试的
          角色查询以页面唯一 alert 为前提（教训 51：新挂载点请求失败呈现不得
          挤占既有角色域）。 */}
      {error ? <p aria-live="assertive" className="error-text">{error}</p> : null}
      {notice ? <p aria-live="polite" className="notice-text">{notice}</p> : null}

      {canManage ? (
        <div className="discovery-create-row">
          <label htmlFor="discovery-source-select">抽取来源（访谈纪要）</label>
          <select
            id="discovery-source-select"
            value={selectedMinutesId}
            onChange={(event) => { setSelectedMinutesId(event.target.value) }}
          >
            <option value="">— 选择纪要 —</option>
            {minutes.map((minute) => (
              <option key={minute.id} value={minute.id}>{minute.title}</option>
            ))}
          </select>
          <button type="button" disabled={busy || !selectedMinutesId} onClick={() => { void createExtraction() }}>
            发起 AI 抽取
          </button>
          {!minutes.length ? <span className="hint-text">尚无访谈纪要：先在转写草稿区晋升纪要。</span> : null}
        </div>
      ) : null}

      <h4>抽取记录</h4>
      {!loaded ? <p>正在加载…</p> : extractions.length === 0 ? <p>暂无抽取记录。</p> : (
        <table className="data-table">
          <thead>
            <tr><th>状态</th><th>来源</th><th>指纹</th><th>模型</th><th>完成时间</th><th>复核/失败</th><th>{canManage ? "操作" : ""}</th></tr>
          </thead>
          <tbody>
            {extractions.map((extraction) => (
              <tr key={extraction.id}>
                <td>{label(EXTRACTION_STATUS_LABEL, extraction.status)}</td>
                <td>{extraction.source_type === "interview_minutes" ? "纪要" : "草稿"}</td>
                <td title={extraction.source_sha256}>{extraction.source_sha256.slice(0, 12)}</td>
                <td>{extraction.ai_model ?? "—"}</td>
                <td>{formatDateTime(extraction.completed_at)}</td>
                <td>
                  {extraction.failure_code
                    ? <span title={extraction.failure_message ?? ""}>{extraction.failure_code}</span>
                    : extraction.redaction_entries && extraction.redaction_entries.length
                      ? <span title={extraction.redaction_entries.map((entry) => `${redactionEntryLabel(entry)}×${redactionEntryCount(entry)}`).join("；")}>脱敏复核 {extraction.redaction_entries.length} 项</span>
                      : "—"}
                </td>
                <td>
                  {canManage && extraction.status === "failed"
                    ? <button type="button" disabled={busy} onClick={() => { void rerunExtraction(extraction.id) }}>重跑</button>
                    : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h4>业务事实（已加载 {facts.length}{factsExhausted ? "" : "+"}）</h4>
      <div className="discovery-filter-row">
        <label htmlFor="discovery-fact-filter">审阅状态</label>
        <select id="discovery-fact-filter" value={factFilter} disabled={busy} onChange={(event) => {
          loadGeneration.current += 1
          setSelectedFacts([]); setBatchPreview([]); setFacts([]); setLoaded(false); setFactFilter(event.target.value)
        }}>
          <option value="">全部</option>
          <option value="pending">待审</option>
          <option value="needs_clarification">待澄清</option>
          <option value="accepted">已接受</option>
          <option value="rejected">已拒绝</option>
        </select>
        <label htmlFor="discovery-anchor-filter">锚点核验</label>
        <select id="discovery-anchor-filter" value={anchorFilter} disabled={busy} onChange={(event) => {
          setSelectedFacts([]); setBatchPreview([])
          setAnchorFilter(event.target.value === "suspect" ? "suspect" : "all")
        }}>
          <option value="all">全部</option>
          <option value="suspect">仅看可疑（A/B 级）</option>
        </select>
        <span className="hint-text" title="锚点核验＝行号定位对纪要原文的程序化比对（A=高危/空行或全不命中，B=疑似相邻行滑移，C=命中）。分级仅提示，接受/拒绝仍由人工判断。">
          锚点核验：A {anchorSummary.a} · B {anchorSummary.b} · C {anchorSummary.c}
        </span>
        {canManage ? <button type="button" disabled={busy || !selectedPending.length} onClick={() => setBatchPreview(selectedPending)}>
          {batchProgress ? `接受中 ${batchProgress.done}/${batchProgress.total}…` : `预览批量接受（已选 ${selectedPending.length} 条）`}
        </button> : null}
        {!factsExhausted
          ? <button type="button" disabled={busy} onClick={() => { void loadMoreFacts() }}>加载更多事实</button>
          : null}
      </div>
      {canManage && batchPreview.length > 0 ? <fieldset>
        <legend>确认批量接受</legend>
        <p>当前筛选 · 已加载 · 已选 {batchPreview.length} 条</p>
        <ul>{batchPreview.map((fact) => <li key={fact.id}>{fact.subject} · {fact.predicate}</li>)}</ul>
        <button type="button" autoFocus onClick={() => setBatchPreview([])}>取消批量接受</button>
        <button type="button" disabled={busy || batchPreview.some((fact) => !eligibleFacts.some((item) => item.id === fact.id))} onClick={() => void acceptPendingFacts()}>确认接受</button>
      </fieldset> : null}
      {batchReceipts.length > 0 ? <ul aria-label="批量审阅回执">{batchReceipts.map((row) => <li key={row.id}>{row.label}：{row.message}</li>)}</ul> : null}
      {needsFactReload.length > 0 ? <button type="button" disabled={busy} onClick={async () => {
        setBusy(true); setError("")
        try { await readBatchResults(needsFactReload) } catch { setError("无法回读事实状态，未重试写入。") }
        finally { setBusy(false) }
      }}>回读事实状态</button> : null}
      {!loaded ? <p>正在加载…</p> : visibleFacts.length === 0 ? <p>暂无事实（发起抽取后生成草稿）。</p> : (
        <table className="data-table">
          <thead>
            <tr><th>类型</th><th>事实</th><th>取值</th><th>分类</th><th>来源定位 / 锚点核验</th><th>置信</th><th>审阅</th><th>{canManage ? "操作" : ""}</th></tr>
          </thead>
          <tbody>
            {visibleFacts.map((fact) => {
              const grade = anchorBadge(fact)
              return (
                <tr key={fact.id}>
                  <td>{label(FACT_TYPE_LABEL, fact.fact_type)}</td>
                  <td>{fact.subject} · {fact.predicate}</td>
                  <td title={objectValueText(fact.object_value)}>{objectValueText(fact.object_value).slice(0, 60)}</td>
                  <td>{label(CLASSIFICATION_LABEL, fact.classification)}</td>
                  <td title={`${fact.source_ref}${grade ? ` | 锚点核验：${grade.reason}` : ""}`}>
                    <span className={`anchor-badge anchor-${grade ? grade.grade.toLowerCase() : "none"}`}>{locatorText(fact.source_locator)}</span>
                    {grade
                      ? <span className={`anchor-badge anchor-${grade.grade.toLowerCase()}`} title={grade.reason}>{` 锚${grade.grade}`}</span>
                      : null}
                  </td>
                  <td>{fact.confidence ?? "—"}</td>
                  <td>{label(REVIEW_STATUS_LABEL, fact.review_status)}</td>
                  <td>
                    {canManage && fact.review_status === "pending" ? <input
                      type="checkbox"
                      aria-label={`选择事实：${fact.subject} · ${fact.predicate}`}
                      checked={selectedFacts.includes(fact.id)}
                      disabled={busy || batchPreview.length > 0 || needsFactReload.includes(fact.id)}
                      onChange={(event) => {
                        const checked = event.target.checked
                        setSelectedFacts((prev) => checked ? [...prev, fact.id] : prev.filter((id) => id !== fact.id))
                      }}
                    /> : null}
                    {canManage && fact.review_status !== "accepted" && fact.review_status !== "rejected"
                      ? (
                        <span className="discovery-actions">
                          <button type="button" disabled={busy} onClick={() => { void reviewFact(fact.id, "accepted") }}>接受</button>
                          <button type="button" disabled={busy} onClick={() => { void reviewFact(fact.id, "rejected") }}>拒绝</button>
                          <button type="button" disabled={busy} onClick={() => { void reviewFact(fact.id, "needs_clarification") }}>澄清</button>
                        </span>
                      )
                      : null}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      <h4>需求（已加载 {requirements.length}{requirementsExhausted ? "" : "+"}）</h4>
      {!loaded ? <p>正在加载…</p> : requirements.length === 0 ? <p>暂无需求。</p> : (
        <table className="data-table">
          <thead>
            <tr><th>键</th><th>标题</th><th>类型</th><th>优先级</th><th>验收标准</th><th>来源</th><th>状态</th><th>{canManage ? "操作" : ""}</th></tr>
          </thead>
          <tbody>
            {requirements.map((requirement) => (
              <tr key={requirement.id}>
                <td>{requirement.requirement_key}</td>
                <td title={requirement.description ?? ""}>{requirement.title}</td>
                <td>{label(REQUIREMENT_TYPE_LABEL, requirement.requirement_type)}</td>
                <td>{label(PRIORITY_LABEL, requirement.priority)}</td>
                <td title={requirement.acceptance_criteria.join("；")}>{requirement.acceptance_criteria.length} 条</td>
                <td>{requirement.source_count} 处</td>
                <td>{label(REVIEW_STATUS_LABEL, requirement.status)}</td>
                <td>
                  {canManage && requirement.status !== "accepted" && requirement.status !== "rejected"
                    ? (
                      <span className="discovery-actions">
                        <button type="button" disabled={busy} onClick={() => { void reviewRequirement(requirement.id, "accepted") }}>批准</button>
                        <button type="button" disabled={busy} onClick={() => { void reviewRequirement(requirement.id, "rejected") }}>否决</button>
                        <button type="button" disabled={busy} onClick={() => { void reviewRequirement(requirement.id, "needs_clarification") }}>澄清</button>
                      </span>
                    )
                    : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!requirementsExhausted
        ? <button type="button" disabled={busy} onClick={() => { void loadMoreRequirements() }}>加载更多需求</button>
        : null}
    </section>
  )
}
