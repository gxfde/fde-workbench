import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { ApiClientError } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import {
  buildTranslationPreview,
  type TranslatorFormState,
} from './preview'

// 翻译器门户（goal-d9，PRD §3.2 P3 全量）：引导式表单 + 实时本地预览 +
// AI 翻译管道（POST /api/v1/translator/translations → job 轮询 → guidance
// 全契约草稿）。AI 只出草稿（服务端契约 confirmed 一律 False）：结果卡
// 常显「AI 草稿 · 待人工确认」徽标；失败码透出（§11 降级态 UX）。
const INTERVIEW_MODES: { value: TranslatorFormState['interview_mode']; label: string }[] = [
  { value: 'onsite', label: '现场' },
  { value: 'remote', label: '远程' },
  { value: 'hybrid', label: '混合' },
]

const EMPTY_FORM: TranslatorFormState = {
  industry: '',
  scale: '',
  region: '',
  interview_mode: 'onsite',
  customer_vision: '',
  phase_objective: '',
}

const POLL_INTERVAL_MS = 800
const POLL_MAX_MS = 90_000

interface TranslationDto {
  id: string
  status: 'pending' | 'running' | 'ready' | 'failed'
  adopted_into?: { project_id: string; analysis_id: string }[]
  customer_vision?: string | null
  created_at?: string | null
  result: {
    customer_vision?: string
    current_phase_objective?: string
    executive_summary?: string
    key_business_problems?: { text: string; severity?: string; module?: string; classification: string }[]
    open_questions?: { text: string }[]
  } | null
  failure_code: string | null
  failure_message: string | null
  ai_model: string | null
}

function isTranslationDto(value: unknown): value is TranslationDto {
  if (typeof value !== 'object' || value === null) return false
  const row = value as Record<string, unknown>
  return typeof row.id === 'string' && typeof row.status === 'string'
}

const CLASSIFICATION_LABELS: Record<string, string> = {
  customer_stated: '客户原话',
  ai_synthesized: 'AI 综合',
  ai_inferred: 'AI 推断',
  open_question: '待确认',
}

export function TranslatorPortalPage() {
  const { apiRequest } = useAuth()
  const [form, setForm] = useState<TranslatorFormState>(EMPTY_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')
  const [translation, setTranslation] = useState<TranslationDto | null>(null)
  const [history, setHistory] = useState<TranslationDto[]>([])
  const [historyError, setHistoryError] = useState(false)
  const pollTimer = useRef<number | null>(null)
  const preview = useMemoPreview(form)

  // 历史一览（goal-d12）：GET /translations 列表（服务端：本人最近 20 条，
  // 带 adopted_into）。加载失败静默降级为 muted 行——不阻塞表单主流程
  //（沿 AdoptionSection 项目列表拉取失败的同一先例）。
  const loadHistory = useCallback(() => {
    void apiRequest<unknown>('/api/v1/translator/translations', { method: 'GET' })
      .then((value) => {
        const rows = Array.isArray(value) ? value : []
        setHistory(rows.filter(isTranslationDto))
        setHistoryError(false)
      })
      .catch(() => { setHistoryError(true) })
  }, [apiRequest])

  useEffect(() => { loadHistory() }, [loadHistory])

  const stopPolling = useCallback(() => {
    if (pollTimer.current !== null) {
      window.clearTimeout(pollTimer.current)
      pollTimer.current = null
    }
  }, [])
  useEffect(() => stopPolling, [stopPolling])

  const poll = useCallback((id: string) => {
    stopPolling()
    const startedAt = Date.now()
    const tick = () => {
      void apiRequest<unknown>(`/api/v1/translator/translations/${encodeURIComponent(id)}`, { method: 'GET' })
        .then((value) => {
          if (!isTranslationDto(value)) throw new Error('invalid translation')
          setTranslation(value)
          if (value.status === 'pending' || value.status === 'running') {
            if (Date.now() - startedAt > POLL_MAX_MS) {
              setSubmitError('翻译耗时过长，请稍后在列表查看结果。')
              return
            }
            pollTimer.current = window.setTimeout(tick, POLL_INTERVAL_MS)
          } else {
            loadHistory() // 终态（ready/failed）刷新历史一览
          }
        })
        .catch(() => {
          if (Date.now() - startedAt > POLL_MAX_MS) {
            setSubmitError('翻译状态查询失败，请稍后重试。')
            return
          }
          pollTimer.current = window.setTimeout(tick, POLL_INTERVAL_MS)
        })
    }
    pollTimer.current = window.setTimeout(tick, POLL_INTERVAL_MS)
  }, [apiRequest, stopPolling, loadHistory])

  function update<K extends keyof TranslatorFormState>(key: K, value: TranslatorFormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const canSubmit =
    !submitting && form.customer_vision.trim().length > 0

  async function submit() {
    if (!canSubmit) return
    setSubmitting(true); setSubmitError(''); setTranslation(null)
    try {
      const created = await apiRequest<unknown>('/api/v1/translator/translations', {
        method: 'POST',
        body: {
          industry: form.industry.trim(),
          scale: form.scale.trim(),
          region: form.region.trim(),
          interview_mode: form.interview_mode,
          customer_vision: form.customer_vision.trim(),
          phase_objective: form.phase_objective.trim(),
        },
      })
      const id = extractTranslationId(created)
      if (!id) throw new Error('invalid translation response')
      poll(id)
    } catch (caught) {
      setSubmitError(caught instanceof ApiClientError ? caught.message : '提交失败，请稍后重试。')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="page" aria-label="翻译器门户">
      <header className="page-header">
        <div>
          <p className="eyebrow">翻译器门户</p>
          <h1>客户诉求翻译</h1>
          <p>
            把客户的模糊诉求引导式录入：左侧实时预览（本地启发式），提交后由 AI
            翻译管道生成结构化项目指引草稿（AI 只出草稿，人工确认）。
          </p>
        </div>
      </header>
      <div className="page-stack">
        <div className="card translator-form">
          <div className="card-heading">
            <div>
              <h3>第一步 · 客户背景</h3>
            </div>
          </div>
          <label>
            行业
            <input
              value={form.industry}
              onChange={(event) => update('industry', event.target.value)}
              placeholder="如：装备制造"
            />
          </label>
          <label>
            规模
            <input
              value={form.scale}
              onChange={(event) => update('scale', event.target.value)}
              placeholder="如：200 人 / 年产值 3 亿"
            />
          </label>
          <label>
            区域
            <input
              value={form.region}
              onChange={(event) => update('region', event.target.value)}
              placeholder="如：苏州"
            />
          </label>
          <label>
            访谈方式
            <select
              value={form.interview_mode}
              onChange={(event) => update('interview_mode', event.target.value as TranslatorFormState['interview_mode'])}
            >
              {INTERVIEW_MODES.map((mode) => (
                <option key={mode.value} value={mode.value}>{mode.label}</option>
              ))}
            </select>
          </label>
          <div className="card-heading">
            <div>
              <h3>第二步 · 客户诉求与阶段目标</h3>
            </div>
          </div>
          <label>
            客户诉求原话（AI 将逐句翻译为结构化问题清单）
            <textarea
              value={form.customer_vision}
              onChange={(event) => update('customer_vision', event.target.value)}
              rows={5}
              placeholder="例：仓库出入库必须过系统留痕；管理层看不到实时良率；明年要过客户审计……"
            />
          </label>
          <label>
            阶段目标
            <textarea
              value={form.phase_objective}
              onChange={(event) => update('phase_objective', event.target.value)}
              rows={2}
              placeholder="本期要达成什么（建议补齐，便于 AI 对齐本期范围）"
            />
          </label>
          <div className="row-actions">
            <button type="button" className="primary-button" disabled={!canSubmit} onClick={() => void submit()}>
              {submitting ? '提交中…' : translation && (translation.status === 'pending' || translation.status === 'running') ? 'AI 翻译中…' : '提交 AI 翻译'}
            </button>
            <span className="muted">AI 只出草稿：结果经人工确认前不进入任何下游流程。</span>
          </div>
          {submitError ? <p className="form-error" role="alert">{submitError}</p> : null}
        </div>
        <div className="card translator-preview" aria-live="polite">
          <div className="card-heading">
            <div>
              <h3>实时预览（本地，未提交）</h3>
            </div>
          </div>
          <p className="muted">
            客户画像：{preview.profile.industry || '—'} / {preview.profile.scale || '—'} / {preview.profile.region || '—'} / {preview.profile.interview_mode}
          </p>
          {preview.draft_problems.length === 0 ? (
            <p className="muted">暂无拟问题清单。</p>
          ) : (
            <ol className="translator-problems">
              {preview.draft_problems.map((problem, index) => (
                <li key={`${index}-${problem.text}`}>
                  {problem.text}
                  <span className={`badge ${problem.severity === 'high' ? 'warning' : 'muted'} translator-severity`}>
                    {problem.severity === 'high' ? 'severity=high（预标）' : 'severity=待确认'}
                  </span>
                  <span className="badge muted translator-module">module=待认领</span>
                </li>
              ))}
            </ol>
          )}
          {preview.hints.map((hint) => (
            <p key={hint} className="muted translator-hint">{hint}</p>
          ))}
        </div>
        {translation ? <TranslationResultCard translation={translation} /> : null}
        <HistorySection
          items={history}
          error={historyError}
          activeId={translation?.id ?? null}
          onReload={loadHistory}
          onOpen={(row) => setTranslation(row)}
        />
      </div>
    </section>
  )
}

function TranslationResultCard({ translation }: { translation: TranslationDto }) {
  if (translation.status === 'pending' || translation.status === 'running') {
    return <div className="card translator-result" aria-live="polite">
      <div className="card-heading"><div><h3>AI 翻译草稿</h3></div></div>
      <p role="status">AI 翻译管道处理中…</p>
    </div>
  }
  if (translation.status === 'failed') {
    return <div className="card translator-result" aria-live="polite">
      <div className="card-heading"><div><h3>AI 翻译草稿</h3></div></div>
      <p className="form-error" role="alert">
        翻译失败（{translation.failure_code || 'unknown'}）：{translation.failure_message || '请重新发起翻译。'}
      </p>
    </div>
  }
  const problems = translation.result?.key_business_problems ?? []
  const openQuestions = translation.result?.open_questions ?? []
  const adopted = translation.adopted_into ?? []
  return <div className="card translator-result" aria-live="polite">
    <div className="card-heading">
      <div>
        <h3>AI 翻译草稿</h3>
        <p className="muted">
          <span className="badge warning">AI 草稿 · 待人工确认</span>
          {' '}模型 {translation.ai_model || '—'} · 问题 {problems.length} 条 · 待确认 {openQuestions.length} 条
        </p>
        {adopted.length > 0 ? (
          <p className="muted translator-adopted">
            {adopted.map((item) => (
              <span key={item.project_id} className="badge ok">
                已采纳 <a href={`#/projects/${item.project_id}`}>项目</a>
              </span>
            ))}
          </p>
        ) : null}
      </div>
    </div>
    {translation.result?.executive_summary ? <p>{translation.result.executive_summary}</p> : null}
    {problems.length === 0 ? (
      <p className="muted">AI 未能从原话中提炼问题清单，建议补充诉求描述后重试。</p>
    ) : (
      <ol className="translator-problems">
        {problems.map((problem, index) => (
          <li key={`${index}-${problem.text}`}>
            {problem.text}
            <span className={`badge ${problem.severity === 'high' ? 'warning' : 'muted'} translator-severity`}>
              severity={problem.severity || '待确认'}
            </span>
            <span className="badge muted translator-module">
              module={problem.module || '待认领'} · {CLASSIFICATION_LABELS[problem.classification] || problem.classification}
            </span>
          </li>
        ))}
      </ol>
    )}
    {openQuestions.length > 0 ? <p className="muted translator-hint">待确认问题将在人工确认环节逐条消化。</p> : null}
    <AdoptionSection translationId={translation.id} />
  </div>
}

const STATUS_BADGES: Record<TranslationDto['status'], { label: string; tone: string }> = {
  pending: { label: '排队中', tone: 'muted' },
  running: { label: '翻译中', tone: 'muted' },
  ready: { label: '就绪', tone: 'ok' },
  failed: { label: '失败', tone: 'warning' },
}

// 历史一览（goal-d12）：本人最近 20 条草稿。ready/failed 行可点「查看」载入
// 结果卡——ready 草稿可再次采纳到其他项目（同一草稿可采多项目=个人资产，
// goal-d10 决议①）；已采纳行透出计数徽标。
function HistorySection({ items, error, activeId, onReload, onOpen }: {
  items: TranslationDto[]
  error: boolean
  activeId: string | null
  onReload: () => void
  onOpen: (row: TranslationDto) => void
}) {
  return <div className="card translator-history">
    <div className="card-heading">
      <div><h3>最近翻译</h3></div>
      <button type="button" className="text-button" onClick={onReload}>重新加载</button>
    </div>
    {error ? <p className="muted">翻译记录加载失败。</p> : null}
    {!error && items.length === 0 ? <p className="muted">暂无翻译记录。</p> : null}
    {items.length > 0 ? (
      <ul className="translator-history-list">
        {items.map((row) => {
          const badge = STATUS_BADGES[row.status] ?? { label: row.status, tone: 'muted' }
          const adoptedCount = row.adopted_into?.length ?? 0
          const vision = (row.customer_vision ?? '').trim()
          const viewable = row.status === 'ready' || row.status === 'failed'
          return (
            <li key={row.id} className={row.id === activeId ? 'translator-history-item active' : 'translator-history-item'}>
              <span className={`badge ${badge.tone}`}>{badge.label}</span>
              <span className="translator-history-vision">
                {vision ? (vision.length > 40 ? `${vision.slice(0, 40)}…` : vision) : '（无原话）'}
              </span>
              {adoptedCount > 0 ? <span className="badge ok">已采纳 {adoptedCount} 项目</span> : null}
              {viewable ? (
                <button type="button" className="text-button" onClick={() => onOpen(row)}>
                  {row.id === activeId ? '查看中' : '查看'}
                </button>
              ) : null}
            </li>
          )
        })}
      </ul>
    ) : null}
  </div>
}

const ADOPT_ERROR_LABELS: Record<string, string> = {
  already_adopted: '该草稿已采纳到本项目，请到项目指引页编辑确认。',
  translation_not_ready: '草稿尚未就绪，暂不能采纳。',
  translation_not_found: '翻译记录不存在。',
  forbidden: '只有项目负责人或管理员可以采纳到该项目。',
  project_not_found: '项目不存在或无权访问。',
}

// 采纳流（goal-d10）：ready 草稿升格为项目指引新版本（status=draft 待人工
// 确认）；编辑与逐条确认统一在项目指引页（GuidanceReview）完成——一份指引
// 一处编辑权。O-3 额度由服务端随采纳落账。
function AdoptionSection({ translationId }: { translationId: string }) {
  const { apiRequest } = useAuth()
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([])
  const [projectId, setProjectId] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    void apiRequest<unknown>('/api/v1/projects?page=1&page_size=50', { method: 'GET' })
      .then((value) => {
        if (!active) return
        const items = Array.isArray((value as { items?: unknown })?.items)
          ? (value as { items: unknown[] }).items
          : []
        setProjects(items.flatMap((item) => {
          const row = item as { id?: unknown; name?: unknown }
          return typeof row.id === 'string' && typeof row.name === 'string'
            ? [{ id: row.id, name: row.name }]
            : []
        }))
      })
      .catch(() => { /* 项目列表拉取失败不阻塞草稿展示。 */ })
    return () => { active = false }
  }, [apiRequest])
  async function adopt() {
    if (!projectId || busy) return
    setBusy(true); setError(''); setNotice('')
    try {
      await apiRequest<unknown>(
        `/api/v1/translator/translations/${encodeURIComponent(translationId)}/adopt`,
        { method: 'POST', body: { project_id: projectId } },
      )
      const name = projects.find((item) => item.id === projectId)?.name ?? projectId
      setNotice(`已采纳到项目「${name}」，请到项目指引页编辑并逐条确认后正式生效。`)
    } catch (caught) {
      setError(caught instanceof ApiClientError
        ? (ADOPT_ERROR_LABELS[caught.code] ?? caught.message)
        : '采纳失败，请稍后重试。')
    } finally { setBusy(false) }
  }
  return <div className="translator-adopt">
    <h4>采纳到项目</h4>
    <p className="muted">采纳后草稿成为项目指引新版本（待确认），编辑与逐条确认在项目指引页完成。</p>
    {notice ? <p role="status" className="notice">{notice} <a href={`#/projects/${projectId}`}>打开项目</a></p> : null}
    {error ? <p role="alert" className="form-error">{error}</p> : null}
    <label>
      项目
      <select aria-label="采纳到项目" value={projectId} onChange={(event) => setProjectId(event.target.value)}>
        <option value="">选择项目…</option>
        {projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select>
    </label>
    <button type="button" className="primary-button" disabled={!projectId || busy} onClick={() => void adopt()}>
      {busy ? '采纳中…' : '采纳到项目'}
    </button>
  </div>
}

function extractTranslationId(value: unknown): string | null {
  // goal-d10 fix: apiRequest already unwraps the {data,error} envelope, so the
  // created payload is the translation DTO itself (same latent bug family as
  // the dispatch pages fixed in goal-d9; tests used to feed the envelope).
  if (typeof value !== 'object' || value === null) return null
  const id = (value as Record<string, unknown>).id
  return typeof id === 'string' ? id : null
}

// 本地启发式预览（骨架版能力保留——打字期间的即时反馈）
function useMemoPreview(form: TranslatorFormState) {
  return useMemo(() => buildTranslationPreview(form), [form])
}
