import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { BUSINESS_CATEGORIES, BUSINESS_CATEGORY_UNCATEGORIZED_LABEL } from '../businessCategory'
import { OpportunityFilter } from '../documents/OpportunityFilter'
import { opportunityGroups, subjectAncestors } from '../documents/ProjectDocuments'
import { ProjectLibrary } from '../library/ProjectLibrary'
import type { ResearchSubjectDto } from '../research/types'
import { isSolution } from './types'
import type { SolutionDto } from './types'
import { SolutionDetailPage, solutionHref } from './SolutionDetailPage'
import { SolutionExport } from './SolutionExport'
import type { SolutionExportResult } from './SolutionExport'
import { solutionError } from './solutionErrors'
import './solutions.css'

interface Props { projectId: string; canManage: boolean; solutionId?: string; mode?: 'edit'; opportunityId?: string }

export function SolutionDesign(props: Props) {
  return props.solutionId
    ? <SolutionDetailPage key={`${props.projectId}:${props.solutionId}:${props.mode ?? 'view'}`} {...props} solutionId={props.solutionId} />
    : <SolutionList key={props.projectId} projectId={props.projectId} canManage={props.canManage} />
}

function SolutionList({ projectId, canManage }: { projectId: string; canManage: boolean }) {
  const { apiRequest } = useAuth()
  const [solutions, setSolutions] = useState<SolutionDto[]>([])
  const [subjects, setSubjects] = useState<ResearchSubjectDto[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [category, setCategory] = useState('')
  const [status, setStatus] = useState('normal')
  const [opportunity, setOpportunity] = useState(() => hashOpportunity())
  const [archiving, setArchiving] = useState<SolutionDto | null>(null)
  const [exported, setExported] = useState<{ result: SolutionExportResult; solution: SolutionDto } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyRevision, setHistoryRevision] = useState(0)
  const sequence = useRef(0)
  const load = useCallback(async () => {
    const current = ++sequence.current
    try {
      const [next, research] = await Promise.all([
        apiRequest<{ items: unknown[] }>(`/api/v1/projects/${encodeURIComponent(projectId)}/solutions`, { method: 'GET' }),
        apiRequest<{ items: ResearchSubjectDto[] }>(`/api/v1/projects/${encodeURIComponent(projectId)}/research/subjects`, { method: 'GET' }),
      ])
      if (current !== sequence.current) return
      if (!Array.isArray(next.items) || !next.items.every(isSolution) || !Array.isArray(research.items)) throw new Error('invalid solutions')
      setSolutions(next.items); setSubjects(research.items); setError('')
    } catch (caught) { if (current === sequence.current) setError(solutionError(caught)) }
    finally { if (current === sequence.current) setLoading(false) }
  }, [apiRequest, projectId])
  useEffect(() => {
    setLoading(true); setSolutions([]); setSubjects([])
    setArchiving(null); setExported(null)
    void load()
    return () => { sequence.current += 1 }
  }, [load])
  useEffect(() => {
    const sync = () => setOpportunity(hashOpportunity())
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])
  const opportunities = subjects.filter(subject => subject.subject_type === 'opportunity')
  const groups = opportunityGroups(subjects)
  const objectIds = new Set(groups.flatMap(group => subjectAncestors(subjects, group.id).map(parent => parent.id)))
  const filterOptions = [{ value: '', label: '全部机会' }, ...subjects.filter(subject => objectIds.has(subject.id)).flatMap(subject => [
    { value: `object:${subject.id}`, label: subjectAncestors(subjects, subject.id).map(parent => parent.name).join(' › ') },
    ...(groups.find(group => group.id === subject.id)?.items ?? []).map(item => ({ value: item.id, label: `${item.tracking_code ?? ''} ${item.name}`.trim(), level: 1 })),
  ]), ...groups.filter(group => !subjects.some(subject => subject.id === group.id)).flatMap(group => group.items.map(item => ({ value: item.id, label: `${item.tracking_code ?? ''} ${item.name}`.trim(), level: 1 })))]
  // A linked historical opportunity can still filter its saved plans even after deprecation.
  if (opportunity && !opportunity.startsWith('object:') && !filterOptions.some(option => option.value === opportunity)) {
    const historical = opportunities.find(item => item.id === opportunity) ?? solutions.flatMap(item => item.opportunities).find(item => item.id === opportunity)
    if (historical) filterOptions.push({ value: opportunity, label: `${historical.tracking_code ?? ''} ${historical.name}`.trim() })
  }
  const selectedIds = opportunity.startsWith('object:') ? opportunities.filter(item => subjectAncestors(subjects, item.id).some(parent => parent.id === opportunity.slice(7))).map(item => item.id) : [opportunity]
  const visible = solutions.filter(solution => (status === 'all' || (status === 'archived' ? solution.status === 'archived' : solution.status !== 'archived'))
    && (!category || (category === BUSINESS_CATEGORY_UNCATEGORIZED_LABEL ? !solution.business_category : solution.business_category === category))
    && (!opportunity || solution.opportunity_ids.some(id => selectedIds.includes(id))))

  function openSolution(solution: SolutionDto, edit: boolean) {
    window.location.hash = solutionHref(projectId, solution.id, edit ? 'edit' : undefined, hashOpportunity())
  }
  async function exportSow(solution: SolutionDto) {
    const request = sequence.current
    setBusy(solution.id); setError(''); setNotice('')
    try {
      const result = await apiRequest<SolutionExportResult>(`/api/v1/projects/${encodeURIComponent(projectId)}/solutions/${encodeURIComponent(solution.id)}/export-sow`, { method: 'POST', body: { version: solution.version } })
      if (request !== sequence.current) return
      if (!result.document_id || !result.document_version_id || !result.document) throw new Error('invalid export')
      setExported({ result, solution }); setHistoryRevision(current => current + 1)
    } catch (caught) { if (request === sequence.current) setError(solutionError(caught)) }
    finally { if (request === sequence.current) setBusy(null) }
  }

  return <div className="page-stack solution-design-page">
    <section className="panel solution-panel" aria-labelledby="solution-design-title">
      <div className="panel-heading"><h2 id="solution-design-title">方案设计</h2><span>{visible.length} 个</span></div>
      <p className="supporting-copy">围绕关联的 AI 机会设计交付方案，保存后导出 SOW。机会用于识别需求，方案负责设计交付。</p>
      <div className="project-list-toolbar document-toolbar solution-toolbar" role="toolbar" aria-label="方案工具栏">
        {canManage ? <button type="button" className="primary-button" disabled={loading || Boolean(busy)} onClick={() => { window.location.hash = solutionHref(projectId, 'new', undefined, hashOpportunity()) }}>新建方案</button> : null}
        <OpportunityFilter value={opportunity} options={filterOptions} onChange={setOpportunity} />
        <label className="field business-category-filter"><span>业务阶段</span><select aria-label="筛选业务阶段" value={category} onChange={event => setCategory(event.target.value)}><option value="">全部</option><option value={BUSINESS_CATEGORY_UNCATEGORIZED_LABEL}>未分类</option>{BUSINESS_CATEGORIES.map(item => <option key={item} value={item}>{item}</option>)}</select></label>
        <label className="field business-category-filter delivery-status-filter"><span>状态</span><select aria-label="筛选方案状态" value={status} onChange={event => setStatus(event.target.value)}><option value="all">全部</option><option value="normal">正常</option><option value="archived">弃用</option></select></label>
      </div>
      {!canManage ? <p className="field-hint">你可以查看方案；创建、编辑、导出和弃用由项目负责人或管理员操作。</p> : null}
      {error ? <p className="form-error banner" role="alert">{error}</p> : null}
      {notice ? <p className="notice" role="status">{notice}</p> : null}
      {loading ? <p role="status">正在加载方案…</p> : !visible.length ? <p className="empty-state">{solutions.length ? '暂无符合筛选条件的方案。' : '暂无方案。先选择 AI 机会，再设计交付方案。'}</p> : <div className="solution-card-grid">{visible.map(solution => <article className="solution-card" key={solution.id} aria-label={`方案：${solution.name}`}>
        <div className="solution-card-meta"><span className={`badge ${solution.status === 'archived' ? 'muted' : 'success'}`}>{solution.status === 'archived' ? '弃用' : '正常'}</span>{solution.business_category ? <span className="badge business-category">{solution.business_category}</span> : null}<small>版本 {solution.version}</small></div>
        {solution.source?.kind === 'legacy_opportunity_delivery' ? <p className="solution-legacy-notice">{solution.source.reviewed ? '历史交付说明' : '历史交付说明 · 待整理'}</p> : null}
        <h3><button type="button" title={solution.name} disabled={Boolean(busy)} onClick={() => void openSolution(solution, false)}>{solution.name}</button></h3>
        <p className="solution-card-summary">{plainSummary(solution.design_markdown) || '暂未填写方案设计'}</p>
        <div className="solution-card-opportunities"><span>关联 AI 机会 · {solution.opportunities.length}</span>{solution.opportunities.slice(0, 3).map(item => <p key={item.id} title={`${item.tracking_code ?? ''} ${item.name}`}><code>{item.tracking_code}</code> {item.name}</p>)}{solution.opportunities.length > 3 ? <small>另有 {solution.opportunities.length - 3} 个机会，查看方案了解全部</small> : null}</div>
        <footer className="solution-card-actions"><button type="button" className="secondary-button compact" disabled={Boolean(busy)} onClick={() => void openSolution(solution, false)}>查看</button>{canManage && solution.status !== 'archived' ? <><button type="button" className="secondary-button compact" aria-label={`编辑方案：${solution.name}`} disabled={Boolean(busy)} onClick={() => void openSolution(solution, true)}>编辑</button><button type="button" className="primary-button compact" aria-label={`导出 SOW：${solution.name}`} disabled={Boolean(busy)} onClick={() => void exportSow(solution)}>{busy === solution.id ? '处理中…' : '导出 SOW'}</button><button type="button" className="danger-button compact solution-archive-button" aria-label={`弃用方案：${solution.name}`} disabled={Boolean(busy)} onClick={() => setArchiving(solution)}>弃用</button></> : null}</footer>
      </article>)}</div>}
    </section>
    <details className="solution-history" open={historyOpen} onToggle={event => setHistoryOpen(event.currentTarget.open)}><summary>SOW 文件</summary><p className="field-hint">与文件库使用同一份文件和版本记录，这里仅展示 SOW。</p>{historyOpen ? <ProjectLibrary key={historyRevision} projectId={projectId} canManage={canManage} documentType="sow" /> : null}</details>
    {archiving ? <ArchiveSolution projectId={projectId} solution={archiving} onClose={() => setArchiving(null)} onArchived={() => { setArchiving(null); setNotice('方案已标记为弃用。方案记录、关联机会和历史 SOW 均保留。'); void load() }} /> : null}
    {exported ? <SolutionExport key={historyRevision} projectId={projectId} result={exported.result} name={exported.solution.name} requestError={error} retrying={busy === exported.solution.id} onRetry={() => void exportSow(exported.solution)} onClose={() => setExported(null)} /> : null}
  </div>
}

function ArchiveSolution({ projectId, solution, onClose, onArchived }: { projectId: string; solution: SolutionDto; onClose(): void; onArchived(): void }) {
  const { apiRequest } = useAuth()
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function archive() {
    if (!password) { setError('请输入当前账号密码。'); return }
    setBusy(true); setError('')
    try {
      await apiRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/solutions/${encodeURIComponent(solution.id)}/archive`, { method: 'POST', body: { version: solution.version, password } })
      setPassword(''); onArchived()
    } catch (caught) { setPassword(''); setError(solutionError(caught)) }
    finally { setBusy(false) }
  }
  return <div className="dialog-backdrop"><section className="dialog" role="dialog" aria-modal="true" aria-label="弃用方案"><h2>弃用方案</h2><p>将“{solution.name}”标记为弃用。关联机会和已导出的 SOW 不受影响，方案仍可在弃用筛选中查看。</p><form onSubmit={event => { event.preventDefault(); void archive() }}><label className="field"><span>当前账号密码</span><input type="password" autoComplete="current-password" autoFocus maxLength={1024} value={password} disabled={busy} onChange={event => setPassword(event.target.value)} /></label>{error ? <p className="form-error" role="alert">{error}</p> : null}<div className="dialog-actions"><button type="button" className="secondary-button" disabled={busy} onClick={onClose}>取消</button><button type="submit" className="danger-button" disabled={busy}>{busy ? '验证并弃用…' : '确认弃用'}</button></div></form></section></div>
}

function hashOpportunity(): string { return new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('opportunity') ?? '' }
function plainSummary(value: string): string { return value.replace(/```[\s\S]*?```/g, '').replace(/[#*_>`~|]/g, '').replace(/\s+/g, ' ').trim() }
