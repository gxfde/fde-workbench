import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { subjectAncestors } from '../documents/ProjectDocuments'
import { MemoMarkdown } from '../research/MemoMarkdown'
import type { ResearchSubjectDto } from '../research/types'
import { allowNextHashNavigation } from '../routing/navigationGuard'
import { routeHash } from '../routing/useHashRoute'
import { SolutionEditor } from './SolutionEditor'
import { SolutionExport } from './SolutionExport'
import type { SolutionExportResult } from './SolutionExport'
import { solutionError } from './solutionErrors'
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
      const [next, research] = await Promise.all([
        creating ? Promise.resolve(null) : apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/solutions/${encodeURIComponent(solutionId)}`, { method: 'GET' }),
        apiRequest<{ items: ResearchSubjectDto[] }>(`/api/v1/projects/${encodeURIComponent(projectId)}/research/subjects`, { method: 'GET' }),
      ])
      if (request !== sequence.current) return
      if ((!creating && (!isSolution(next) || next.id !== solutionId || next.project_id !== projectId)) || !Array.isArray(research.items)) throw new Error('invalid solution detail')
      setSolution(next as SolutionDto | null); setSubjects(research.items)
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
    <header className="solution-page-heading"><div><p className="eyebrow">方案设计 · 版本 {solution.version} · {solution.status === 'archived' ? '弃用' : '正常'}</p><h2>{solution.name}</h2></div><div className="row-actions">{canManage && solution.status !== 'archived' ? <><a className="secondary-button button-link compact" href={solutionHref(projectId, solution.id, 'edit', opportunityId)}>编辑方案</a><button type="button" className="primary-button compact" disabled={exporting} onClick={() => void exportSow()}>{exporting ? '处理中…' : '导出 SOW'}</button></> : null}{navigation}</div></header>
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    {mode === 'edit' && solution.status === 'archived' ? <p className="notice">此方案已弃用，仅可查看内容。</p> : null}
    {solution.source?.kind === 'legacy_opportunity_delivery' ? <p className="solution-legacy-notice">{solution.source.reviewed ? '历史交付说明：已保留来源，内容经过编辑整理，不代表客户审核或验收。' : '历史交付说明 · 待整理：保留了原机会中的交付内容，请核对完善方案后再导出 SOW。'}</p> : null}
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
  </section>
}
