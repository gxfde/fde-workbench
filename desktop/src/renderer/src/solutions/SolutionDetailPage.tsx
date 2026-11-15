import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { ApiClientError } from '../api/client'
import { subjectAncestors } from '../documents/ProjectDocuments'
import { MemoMarkdown } from '../research/MemoMarkdown'
import type { ResearchSubjectDto } from '../research/types'
import { allowNextHashNavigation } from '../routing/navigationGuard'
import { routeHash } from '../routing/useHashRoute'
import { frozenSolutionVersion, solutionVersionBadge } from './frozenVersion'
import type { DocumentScopeRef } from './frozenVersion'
import { SignoffConsole } from './SignoffConsole'
import { SolutionEditor } from './SolutionEditor'
import { SolutionExport } from './SolutionExport'
import type { SolutionExportResult } from './SolutionExport'
import { solutionError } from './solutionErrors'
import { QuotaMeter } from './QuotaMeter'
import { isSolution, SOLUTION_DETAIL_FIELDS } from './types'
import type { SolutionDto } from './types'

export function solutionHref(projectId: string, solutionId?: string, mode?: 'edit', opportunityId?: string): string {
  return routeHash({ kind: 'project', projectId, tab: 'delivery', ...(solutionId ? { solution: solutionId } : {}), ...(mode ? { mode } : {}), ...(opportunityId && /^[a-zA-Z0-9_-]+$/.test(opportunityId) ? { opportunity: opportunityId } : {}) })
}

interface Props { projectId: string; canManage: boolean; solutionId: string; mode?: 'edit'; opportunityId?: string }

export function SolutionDetailPage({ projectId, canManage, solutionId, mode, opportunityId }: Props) {
  const { apiRequest } = useAuth()
  const [solution, setSolution] = useState<SolutionDto | null>(null)
  const [subjects, setSubjects] = useState<ResearchSubjectDto[]>([])
  // T-A7：SOW 冻结反查数据源（拉取失败静默降级——辅助信息不阻断主内容）
  const [frozenDocs, setFrozenDocs] = useState<DocumentScopeRef[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [exporting, setExporting] = useState(false)
  const [exported, setExported] = useState<SolutionExportResult | null>(null)
  const [exportRevision, setExportRevision] = useState(0)
  const sequence = useRef(0)
  const creating = solutionId === 'new'
  const listHref = solutionHref(projectId, undefined, undefined, opportunityId)
  const detailHref = solutionHref(projectId, solutionId, undefined, opportunityId)
  const load = useCallback(async () => {
    const request = ++sequence.current
    setLoading(true); setError(''); setSolution(null); setSubjects([])
    try {
      const [next, research, documents] = await Promise.all([
        creating ? Promise.resolve(null) : apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/solutions/${encodeURIComponent(solutionId)}`, { method: 'GET' }),
        apiRequest<{ items: ResearchSubjectDto[] }>(`/api/v1/projects/${encodeURIComponent(projectId)}/research/subjects`, { method: 'GET' }),
        // T-A7：冻结反查（辅助数据源，失败静默降级）
        apiRequest<{ items: DocumentScopeRef[] }>(`/api/v1/projects/${encodeURIComponent(projectId)}/documents`, { method: 'GET' }).catch(() => ({ items: [] as DocumentScopeRef[] })),
      ])
      if (request !== sequence.current) return
      if ((!creating && (!isSolution(next) || next.id !== solutionId || next.project_id !== projectId)) || !Array.isArray(research.items)) throw new Error('invalid solution detail')
      setSolution(next as SolutionDto | null); setSubjects(research.items); setFrozenDocs(Array.isArray(documents.items) ? documents.items : [])
    } catch (caught) { if (request === sequence.current) setError(solutionError(caught)) }
    finally { if (request === sequence.current) setLoading(false) }
  }, [apiRequest, projectId, solutionId, creating])
  useEffect(() => { void load(); return () => { sequence.current += 1 } }, [load])
  async function exportSow() {
    if (!solution || exporting || !canManage || solution.status === 'archived') return
    const request = sequence.current
    setExporting(true); setError('')
    try {
      const result = await apiRequest<SolutionExportResult>(`/api/v1/projects/${encodeURIComponent(projectId)}/solutions/${encodeURIComponent(solution.id)}/export-sow`, { method: 'POST', body: { version: solution.version } })
      if (request !== sequence.current) return
      if (!result.document_id || !result.document_version_id || !result.document) throw new Error('invalid solution export')
      setExported(result); setExportRevision(current => current + 1)
    } catch (caught) { if (request === sequence.current) setError(solutionError(caught)) }
    finally { if (request === sequence.current) setExporting(false) }
  }

  const navigation = <a className="secondary-button button-link compact" href={listHref}>返回方案列表</a>
  if (loading) return <section className="panel solution-panel"><div className="solution-page-heading"><h2>方案详情</h2>{navigation}</div><p role="status">正在加载方案…</p></section>
  if ((creating || mode === 'edit') && !canManage) return <section className="panel solution-panel"><div className="solution-page-heading"><h2>方案详情</h2>{navigation}</div><p role="alert">当前账号没有创建或编辑方案的权限。</p>{solution ? <a href={detailHref}>查看方案</a> : null}</section>
  if (!creating && !solution || creating && error) return <section className="panel solution-panel"><div className="solution-page-heading"><h2>方案详情</h2>{navigation}</div><p className="form-error" role="alert">{error || '方案不存在或不可访问。'}</p><button className="secondary-button" onClick={() => void load()}>重试加载</button></section>
  if ((creating || mode === 'edit') && solution?.status !== 'archived') return <SolutionEditor key={`${projectId}:${solutionId}`} projectId={projectId} solution={solution} subjects={subjects} backHref={listHref}
    onClose={() => { const target = creating ? listHref : detailHref; allowNextHashNavigation(target); window.location.hash = target }}
    onSaved={saved => { const target = solutionHref(projectId, saved.id, undefined, opportunityId); allowNextHashNavigation(target); window.location.hash = target }} />
  if (!solution) return null

  const groups = new Map<string, { name: string; path: string; items: SolutionDto['opportunities'] }>()
  for (const item of solution.opportunities) {
    const ancestors = subjectAncestors(subjects, item.id).slice(0, -1)
    const parent = ancestors.at(-1) ?? subjects.find(subject => subject.id === item.parent_id)
    const key = parent?.id ?? item.parent_id ?? 'unassigned'
    if (!groups.has(key)) groups.set(key, { name: parent?.name ?? '未关联对象', path: ancestors.slice(0, -1).map(subject => subject.name).join(' › '), items: [] })
    groups.get(key)!.items.push(item)
  }

  return <section className="panel solution-panel solution-viewer" role="region" aria-label={`查看方案：${solution.name}`}>
    <header className="solution-page-heading"><div><p className="eyebrow">方案设计 · 版本 {solution.version} · {solution.status === 'archived' ? '弃用' : '正常'}{(() => { const badge = solutionVersionBadge(solution.version, frozenSolutionVersion(frozenDocs, solution.id)); return <span className={`badge ${badge.className} solution-freeze-badge`} title={badge.title}>{badge.label}</span> })()}<SolutionProvenanceBadge solution={solution} /><QuotaMeter /><SolutionHealthChip projectId={projectId} solutionId={solution.id} /></p><h2>{solution.name}</h2></div><div className="row-actions">{canManage && solution.status !== 'archived' ? <><a className="secondary-button button-link compact" href={solutionHref(projectId, solution.id, 'edit', opportunityId)}>编辑方案</a><button type="button" className="primary-button compact" disabled={exporting} onClick={() => void exportSow()}>{exporting ? '处理中…' : '导出 SOW'}</button></> : null}{navigation}</div></header>
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    {mode === 'edit' && solution.status === 'archived' ? <p className="notice warning" role="alert">此方案已弃用，仅可查看内容。</p> : null}
    {solution.source?.kind === 'legacy_opportunity_delivery' ? <p className="solution-legacy-notice">{solution.source.reviewed ? '历史交付说明：已保留来源，内容经过编辑整理，不代表客户审核或验收。' : '历史交付说明 · 待整理：保留了原机会中的交付内容，请核对完善方案后再导出 SOW。'}</p> : null}
    {canManage && solution.status !== 'archived' ? <SolutionAgentGenerator projectId={projectId} solution={solution} onWired={setSolution} /> : null}
    <section className="solution-view-associated">
      <h3>关联 AI 机会 <span>{solution.opportunities.length} 个机会 · {groups.size} 个对象</span></h3>
      <div className="solution-opportunity-groups">{Array.from(groups, ([key, group]) => <section className="solution-opportunity-group" key={key}>
        <header><h4>{group.name}<span>{group.items.length}</span></h4>{group.path ? <p title={group.path}>{group.path}</p> : null}</header>
        <ul>{group.items.map(item => <li key={item.id}>{item.tracking_code ? <a className="solution-opportunity-code" href={routeHash({ kind: 'project', projectId, tab: 'research', opportunity: item.id })} title={`查看 ${item.name}`}>{item.tracking_code}</a> : null}<span title={item.name}>{item.name}</span></li>)}</ul>
      </section>)}</div>
    </section>
    <section className="solution-view-section"><h3>方案设计</h3><div className="solution-markdown"><MemoMarkdown>{solution.design_markdown || '待补充'}</MemoMarkdown></div></section>
    <div className="solution-delivery-grid" role="group" aria-label="交付信息">
      {SOLUTION_DETAIL_FIELDS.map(field => <section className={`solution-delivery-card${field.key === 'risks_dependencies' ? ' solution-delivery-card-full' : ''}`} key={field.key} aria-labelledby={`solution-delivery-${field.key}`}><h3 id={`solution-delivery-${field.key}`}>{field.label}</h3><div className="solution-markdown"><MemoMarkdown>{solution[field.key] || '待确认'}</MemoMarkdown></div></section>)}
    </div>
    {exported ? <SolutionExport key={exportRevision} projectId={projectId} result={exported} name={solution.name} requestError={error} retrying={exporting} onRetry={() => void exportSow()} onClose={() => setExported(null)} /> : null}
    {canManage && solution.status !== 'archived' ? <DeliveryPackageLauncher projectId={projectId} solution={solution} /> : null}
    <SignoffConsole projectId={projectId} solutionId={solution.id} canManage={canManage && solution.status !== 'archived'} />
  </section>
}

// 溯源徽标（goal-d6 V11 UI 半边）：AI 生成常显；降级生成以 warning 档强化——
// 「不允许看起来一样但质量不同」（自动交付 §3.3 纪律）
export function SolutionProvenanceBadge({ solution }: { solution: SolutionDto }) {
  if (solution.generated_by !== 'agent' || !solution.agent_run_id) return null
  if (solution.agent_degraded) {
    return <span className="badge warning solution-provenance" title={`降级生成（${solution.agent_fallback_level ?? 'L1'}）：产物须经人工终审后使用`}>智能体生成 · 已降级</span>
  }
  return <span className="badge muted solution-provenance" title="本方案由智能体生成，溯源见 agent 溯源链">智能体生成</span>
}

// 桌面第三批 ops3：方案 AI 生成入口（POST /solutions/{id}/generate-agent）。
// 服务端复用 agents.start_run 全链（权限双层/T2 门/幂等/预算），响应二态：
// wired=true → solution 已接线（溯源徽标经 onWired 刷新）；wired=false →
// run 在途/失败，呈现 run.status 并放行跳转智能体控制台（导航守卫放行）。
const SOLUTION_AGENT_TIER = 'agent.module.solution'

interface AgentListItem {
  id: string
  name: string
  enabled: boolean
  capability_tier: string
  available: boolean
  unavailable_reason: string | null
}

interface GenerateAgentResponse {
  solution_id: string
  wired: boolean
  wired_now?: boolean
  agent_run_id?: string
  solution?: SolutionDto
  run?: { status: string }
}

export function SolutionAgentGenerator({ projectId, solution, onWired }: {
  projectId: string
  solution: SolutionDto
  onWired(next: SolutionDto): void
}) {
  const { apiRequest } = useAuth()
  const [agents, setAgents] = useState<AgentListItem[] | null>(null)
  const [selected, setSelected] = useState('')
  const [idempotencyKey, setIdempotencyKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [pendingRun, setPendingRun] = useState<{ status: string } | null>(null)
  const agentsHref = routeHash({ kind: 'project', projectId, tab: 'agents' })

  useEffect(() => {
    let active = true
    // 清单拉取失败静默降级（辅助入口不阻断方案详情主内容——同 SolutionHealthChip 纪律）
    void apiRequest<{ items: AgentListItem[] }>('/api/v1/agents', { method: 'GET' })
      .then((data) => {
        if (!active || !Array.isArray(data.items)) return
        setAgents(data.items)
        const preferred = data.items.find((item) => item.available && item.capability_tier === SOLUTION_AGENT_TIER)
        if (preferred) setSelected(preferred.id)
      })
      .catch(() => { if (active) setAgents([]) })
    return () => { active = false }
  }, [apiRequest])

  async function generate() {
    if (!selected || busy) return
    const key = idempotencyKey.trim()
    if (key.length > 160) {
      setError('幂等键最长 160 字符。')
      return
    }
    setBusy(true); setError(''); setNotice(''); setPendingRun(null)
    // body 闭集 {agent_id, idempotency_key?}：键留空不传，无多余键
    const body: { agent_id: string; idempotency_key?: string } = { agent_id: selected }
    if (key) body.idempotency_key = key
    try {
      const result = await apiRequest<GenerateAgentResponse>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/solutions/${encodeURIComponent(solution.id)}/generate-agent`,
        { method: 'POST', body },
      )
      if (result.wired && result.solution) {
        onWired(result.solution)
        setNotice(result.wired_now === false ? '方案已关联既有智能体产物（同 run 幂等复用）。' : '智能体生成产物已接线到本方案——溯源徽标已更新。')
      } else {
        setPendingRun(result.run ?? { status: 'unknown' })
      }
    } catch (caught) {
      setError(solutionError(caught))
    } finally {
      setBusy(false)
    }
  }

  return <section className="panel solution-panel solution-agent-generator" role="region" aria-label="AI 生成方案">
    <h3>AI 生成 <span>智能体起草方案，产物经人工终审后生效</span></h3>
    {notice ? <p className="notice" role="status">{notice}</p> : null}
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    {agents === null ? <p className="field-hint" role="status">正在读取智能体清单…</p> : null}
    {agents !== null && agents.length === 0 ? <p className="field-hint">智能体清单暂不可用——请稍后重试。</p> : null}
    {agents !== null && agents.length > 0 ? <>
      <div className="field"><label htmlFor="solution-agent-select"><span>智能体</span></label>
        <select id="solution-agent-select" value={selected} onChange={event => setSelected(event.target.value)}>
          <option value="">— 选择智能体 —</option>
          {agents.map(item => <option key={item.id} value={item.id} disabled={!item.available}>
            {item.name} · {item.capability_tier}{item.available ? '' : `（不可用：${item.unavailable_reason ?? '未知原因'}）`}
          </option>)}
        </select>
      </div>
      <div className="field"><label htmlFor="solution-agent-idempotency"><span>幂等键（可选）</span></label>
        <input id="solution-agent-idempotency" value={idempotencyKey} placeholder="留空则不启用幂等复用" onChange={event => setIdempotencyKey(event.target.value)} />
      </div>
      <button type="button" className="primary-button compact" disabled={!selected || busy} onClick={() => void generate()}>{busy ? '生成中…' : '发起 AI 生成'}</button>
    </> : null}
    {pendingRun ? <p className="field-hint" role="status">智能体 run 未完成接线（状态：{pendingRun.status}）——<a href={agentsHref} onClick={() => allowNextHashNavigation(agentsHref)}>前往智能体运行查看</a></p> : null}
  </section>
}

interface SolutionHealth {
  score: number
  max_score: number
  issues: string[]
}

// goal-d2 S0-4 健康分 v0 的只读展示：加载失败静默隐藏（健康分是辅助信息，
// 不得阻断方案详情主内容）。
function SolutionHealthChip({ projectId, solutionId }: { projectId: string; solutionId: string }) {
  const { apiRequest } = useAuth()
  const [health, setHealth] = useState<SolutionHealth | null>(null)
  useEffect(() => {
    let active = true
    void apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/solutions/${encodeURIComponent(solutionId)}/health`, { method: 'GET' })
      .then((value) => {
        if (!active || !value || typeof value !== 'object') return
        const item = value as Record<string, unknown>
        if (typeof item.score !== 'number' || typeof item.max_score !== 'number' || !Array.isArray(item.issues)) return
        setHealth({ score: item.score, max_score: item.max_score, issues: item.issues.filter((issue): issue is string => typeof issue === 'string') })
      })
      .catch(() => {})
    return () => { active = false }
  }, [apiRequest, projectId, solutionId])
  if (!health) return null
  return <span className="badge business-category" title={health.issues.length ? health.issues.join('\n') : '各项齐备'}>健康度 {health.score}/{health.max_score}</span>
}

// T-A6（报价核验 → 冻结 SOW 闭环）：方案详情页的「建交付包」入口。
// 实测口径（登记三处勘误的落点）：
// 1. 服务端 export_sow 不查报价（SOW 是谈判材料）——真正的报价闸在交付包：
//    建包要求 solution_id+quote_id，publish 要求 quote finalized（422
//    quote_not_finalized）。桌面在「创建入口」前置同口径提示，而不是等 publish 报错。
// 2. 「冻结」语义 = publish 时的快照哈希（§2.3 逐字段清单一次冻结）。
// 3. 服务端零改动零新 API——建包走既有 POST /api/v1/dispatch/packages。
interface QuoteSummary { id: string; quote_key: string; status: string; tier_label: string; claims_summary: { accepted: number; total: number } }

function isQuoteSummary(value: unknown): value is QuoteSummary {
  if (!value || typeof value !== 'object') return false
  const item = value as Record<string, unknown>
  return typeof item.id === 'string' && typeof item.quote_key === 'string'
    && typeof item.status === 'string' && typeof item.tier_label === 'string'
    && !!item.claims_summary && typeof (item.claims_summary as Record<string, unknown>).accepted === 'number'
    && typeof (item.claims_summary as Record<string, unknown>).total === 'number'
}

function DeliveryPackageLauncher({ projectId, solution }: { projectId: string; solution: SolutionDto }) {
  const { apiRequest } = useAuth()
  const [quotes, setQuotes] = useState<QuoteSummary[] | null>(null)
  const [selectedQuote, setSelectedQuote] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const enc = encodeURIComponent(projectId)

  useEffect(() => {
    let active = true
    // 报价拉取失败静默降级（与 SolutionHealthChip 同纪律：辅助入口不得阻断方案详情主内容）
    void apiRequest<unknown>(`/api/v1/projects/${enc}/quotes`, { method: 'GET' })
      .then((payload) => {
        if (!active || !payload || typeof payload !== 'object') return
        const items = (payload as Record<string, unknown>).quotes
        if (!Array.isArray(items)) return
        const rows = items.filter(isQuoteSummary)
        setQuotes(rows)
        const finalized = rows.find(row => row.status === 'finalized')
        if (finalized) setSelectedQuote(finalized.id)
      })
      .catch(() => { if (active) setQuotes([]) })
    return () => { active = false }
  }, [apiRequest, enc])

  const finalizedQuotes = (quotes ?? []).filter(row => row.status === 'finalized')
  const draftQuotes = (quotes ?? []).filter(row => row.status !== 'finalized')
  const canCreate = Boolean(selectedQuote) && !busy

  async function createPackage() {
    if (!selectedQuote || busy) return
    setBusy(true); setError(''); setNotice('')
    try {
      await apiRequest('/api/v1/dispatch/packages', {
        method: 'POST',
        body: { solution_id: solution.id, quote_id: selectedQuote },
      })
      setNotice(`交付包已创建（草稿）。发布后报价与方案要素即冻结为快照——在调度台完成发布。`)
    } catch (caught) {
      if (caught instanceof ApiClientError) {
        if (caught.code === 'package_exists') setError('该方案已有交付包（撤回/拒绝后重发走同一行），请到调度台操作。')
        else if (caught.code === 'verifier_role_required') setError('只有平台侧（管理员/项目负责人）可建交付包。')
        else setError(caught.message)
      } else setError('创建交付包失败，请稍后重试。')
    } finally {
      setBusy(false)
    }
  }

  return <section className="panel solution-panel solution-package-launcher" role="region" aria-label={`建交付包：${solution.name}`}>
    <h3>建交付包 <span>方案 + 已核验报价 → 调度台</span></h3>
    {notice ? <p className="notice" role="status">{notice}</p> : null}
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    {quotes === null ? <p className="field-hint" role="status">正在读取项目报价…</p> : null}
    {quotes !== null && quotes.length === 0 ? <p className="field-hint">项目尚无报价——先到 <a href={routeHash({ kind: 'project', projectId, tab: 'commercial' })}>报价收款</a> 创建报价并完成数字核验（claims 全 accepted），再回此建交付包。</p> : null}
    {quotes !== null && quotes.length > 0 ? <>
      <div className="field"><label htmlFor="package-quote-select"><span>选择报价</span></label>
        <select id="package-quote-select" value={selectedQuote} onChange={event => setSelectedQuote(event.target.value)}>
          <option value="">— 选择报价 —</option>
          {finalizedQuotes.map(row => <option key={row.id} value={row.id}>{row.quote_key} · {row.tier_label} · 已成交回填（claims {row.claims_summary.accepted}/{row.claims_summary.total}）</option>)}
          {draftQuotes.map(row => <option key={row.id} value={row.id} disabled>{row.quote_key} · {row.tier_label} · 草稿（发布交付包前须成交回填）</option>)}
        </select>
      </div>
      {selectedQuote && !finalizedQuotes.some(row => row.id === selectedQuote) ? <p className="field-hint" role="status">交付包发布前报价必须成交回填（服务端闸 quote_not_finalized）——请先到 <a href={routeHash({ kind: 'project', projectId, tab: 'commercial' })}>报价收款</a> 完成成交回填。</p> : null}
      {finalizedQuotes.length === 0 && quotes.length > 0 ? <p className="field-hint">全部报价仍是草稿——数字核验（claims 逐项推进到 accepted）与成交回填都在 <a href={routeHash({ kind: 'project', projectId, tab: 'commercial' })}>报价收款</a> 完成。</p> : null}
      <button type="button" className="primary-button compact" disabled={!canCreate} onClick={() => void createPackage()}>{busy ? '创建中…' : '创建交付包（草稿）'}</button>
      <p className="field-hint">发布时方案与报价要素将冻结为快照（含哈希）；发布前报价必须已成交回填。</p>
    </> : null}
  </section>
}
