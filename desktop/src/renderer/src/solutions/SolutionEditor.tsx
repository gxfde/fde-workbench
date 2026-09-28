import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { BUSINESS_CATEGORIES } from '../businessCategory'
import type { BusinessCategory } from '../businessCategory'
import { opportunityGroups } from '../documents/ProjectDocuments'
import { MemoMarkdown } from '../research/MemoMarkdown'
import type { ResearchSubjectDto } from '../research/types'
import { emptySolution, isSolution, SOLUTION_DETAIL_FIELDS, solutionFields } from './types'
import type { SolutionDto, SolutionFields } from './types'
import { solutionError } from './solutionErrors'
import { allowNextHashNavigation, registerHashNavigationGuard } from '../routing/navigationGuard'

interface Props {
  projectId: string
  solution: SolutionDto | null
  subjects: ResearchSubjectDto[]
  backHref: string
  onClose(): void
  onSaved(solution: SolutionDto): void
}

export function SolutionEditor({ projectId, solution, subjects, backHref, onClose, onSaved }: Props) {
  const { apiRequest } = useAuth()
  const [fields, setFields] = useState<SolutionFields>(() => solution ? solutionFields(solution) : emptySolution())
  const [reference, setReference] = useState('')
  const [preview, setPreview] = useState(false)
  const [busy, setBusy] = useState<'save' | 'ai' | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [discard, setDiscard] = useState(false)
  const initial = useRef(JSON.stringify(fields))
  const nameInput = useRef<HTMLInputElement>(null)
  const active = useRef(true)
  const saved = useRef(false)
  const groups = opportunityGroups(subjects)
  const isDirty = JSON.stringify(fields) !== initial.current || Boolean(reference)
  useEffect(() => { nameInput.current?.focus() }, [])
  useEffect(() => {
    active.current = true
    return () => { active.current = false }
  }, [])
  useEffect(() => {
    if (!isDirty && !busy) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    const confirmLeave = () => {
      if (saved.current) return true
      if (busy === 'save') { window.alert('方案正在保存，请等待保存完成后再离开。'); return false }
      const accepted = window.confirm(busy === 'ai' ? 'AI 正在整理，离开将放弃本页尚未保存的内容，确定离开吗？' : '当前方案有未保存修改，确定离开吗？')
      if (!accepted) nameInput.current?.focus()
      return accepted
    }
    const unregister = registerHashNavigationGuard(confirmLeave)
    const click = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>('a[href^="#"]') : null
      const nextHash = target?.getAttribute('href')
      if (!nextHash || nextHash === window.location.hash) return
      if (!confirmLeave()) { event.preventDefault(); event.stopImmediatePropagation() }
      else allowNextHashNavigation(nextHash)
    }
    window.addEventListener('beforeunload', warn)
    document.addEventListener('click', click, true)
    return () => { unregister(); window.removeEventListener('beforeunload', warn); document.removeEventListener('click', click, true) }
  }, [isDirty, busy])

  function close() {
    if (busy) return
    if (isDirty) setDiscard(true)
    else onClose()
  }
  function update<K extends keyof SolutionFields>(key: K, value: SolutionFields[K]) {
    setFields(current => ({ ...current, [key]: value }))
    setNotice('')
  }
  async function organize() {
    if (!fields.opportunity_ids.length) { setError('请先选择至少一个 AI 机会。'); return }
    if (!reference.trim()) { setError('请先填写一段方案参考，再使用 AI 整理。'); return }
    setBusy('ai'); setError(''); setNotice('')
    try {
      const next = await apiRequest<{ fields: Partial<SolutionFields> }>(`/api/v1/projects/${encodeURIComponent(projectId)}/solutions/ai-organize`, { method: 'POST', body: { ...fields, reference: reference.trim() } })
      if (!active.current) return
      if (!next.fields || typeof next.fields !== 'object') throw new Error('invalid suggestions')
      // AI may suggest text, but cannot change selected opportunities or the business stage.
      const textKeys = ['name', 'design_markdown', ...SOLUTION_DETAIL_FIELDS.map(field => field.key)] as const
      setFields(current => ({ ...current, ...Object.fromEntries(textKeys.filter(key => typeof next.fields[key] === 'string').map(key => [key, next.fields[key]])) }))
      setPreview(true)
      setNotice('AI 已预填充方案，请检查并完善后保存；尚未写入正式方案。')
    } catch (caught) { if (active.current) setError(solutionError(caught)) }
    finally { if (active.current) setBusy(null) }
  }
  async function save() {
    if (!fields.opportunity_ids.length) { setError('请至少选择一个 AI 机会。'); return }
    if (!fields.name.trim()) { setError('请填写方案名称。'); nameInput.current?.focus(); return }
    if (!fields.design_markdown.trim()) { setError('请填写方案设计，或通过 AI 整理后再保存。'); setPreview(false); return }
    setBusy('save'); setError('')
    try {
      const next = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/solutions${solution ? `/${encodeURIComponent(solution.id)}` : ''}`, {
        method: solution ? 'PATCH' : 'POST',
        body: { ...fields, name: fields.name.trim(), ...(solution ? { version: solution.version } : {}) },
      })
      if (!active.current) return
      if (!isSolution(next) || next.project_id !== projectId || (solution && next.id !== solution.id)) throw new Error('invalid saved solution')
      saved.current = true
      onSaved(next)
    } catch (caught) { if (active.current) setError(solutionError(caught)) }
    finally { if (active.current) setBusy(null) }
  }

  return <section className="panel solution-editor" role="region" aria-label={solution ? '编辑方案' : '新建方案'}>
      <header className="solution-page-heading solution-editor-header"><div><h2>{solution ? '编辑方案' : '新建方案'}</h2><p className="field-hint">关联 AI 机会 → 设计交付方案 → 保存后导出 SOW</p></div><a className="secondary-button button-link compact" href={backHref}>返回方案列表</a></header>
      <div className="solution-editor-layout">
        <aside className="solution-opportunity-sidebar"><fieldset className="delivery-opportunity-picker"><legend>关联 AI 机会（可多选）</legend>
          {groups.map(group => <section className="delivery-opportunity-group" key={group.id}><h4 title={group.path}>{group.path}</h4>{group.items.map(item => <label key={item.id} title={`${item.tracking_code ?? ''} ${item.name}`}><input type="checkbox" disabled={Boolean(busy)} checked={fields.opportunity_ids.includes(item.id)} onChange={event => update('opportunity_ids', event.target.checked ? [...fields.opportunity_ids, item.id] : fields.opportunity_ids.filter(id => id !== item.id))} /><span><strong>{item.tracking_code} {item.name}</strong></span></label>)}</section>)}
          {!groups.length ? <p className="field-hint">暂无可选机会，请先到调研中识别 AI 机会。</p> : null}
          {solution?.opportunities.filter(item => !subjects.some(subject => subject.id === item.id && subject.status === 'active')).map(item => <label key={item.id}><input type="checkbox" checked={fields.opportunity_ids.includes(item.id)} disabled={Boolean(busy)} onChange={event => update('opportunity_ids', event.target.checked ? [...fields.opportunity_ids, item.id] : fields.opportunity_ids.filter(id => id !== item.id))} /><span>{item.tracking_code} {item.name}<small>历史关联机会</small></span></label>)}
        </fieldset><p className="field-hint">已选择 {fields.opportunity_ids.length} 个机会。这里只建立关联，不改变机会本身。</p></aside>
        <div className="solution-editor-main">
          <div className="solution-form-grid"><label className="field"><span>方案名称</span><input ref={nameInput} value={fields.name} maxLength={160} disabled={Boolean(busy)} onChange={event => update('name', event.target.value)} /></label><label className="field"><span>业务阶段</span><select value={fields.business_category ?? ''} disabled={Boolean(busy)} onChange={event => update('business_category', event.target.value as BusinessCategory || null)}><option value="">未分类</option>{BUSINESS_CATEGORIES.map(category => <option key={category} value={category}>{category}</option>)}</select></label></div>
          <section className="solution-assist"><label className="field"><span>方案参考</span><textarea rows={3} maxLength={12000} value={reference} disabled={Boolean(busy)} placeholder="写下你的方案思路、实施边界或约束；AI 会结合所选机会整理，未明确事项保留待确认。" onChange={event => setReference(event.target.value)} /></label><div className="solution-assist-footer"><small>也可以跳过 AI，直接填写下面的方案。</small><button className="secondary-button" type="button" disabled={Boolean(busy)} onClick={() => void organize()}>{busy === 'ai' ? 'AI 整理中…' : 'AI 整理'}</button></div></section>
          {notice ? <p className="notice" role="status">{notice}</p> : null}
          <section className="solution-design-field"><div className="solution-field-heading"><label htmlFor="solution-design-input">方案设计</label><div role="group" aria-label="方案设计显示方式" className="solution-view-toggle"><button type="button" aria-pressed={!preview} onClick={() => setPreview(false)}>编辑</button><button type="button" aria-pressed={preview} onClick={() => setPreview(true)}>Markdown 预览</button></div></div>
            {preview ? <div className="solution-markdown solution-design-preview">{fields.design_markdown ? <MemoMarkdown>{fields.design_markdown}</MemoMarkdown> : <p className="field-hint">填写方案设计后可在这里预览。</p>}</div> : <textarea id="solution-design-input" aria-label="方案设计" rows={10} maxLength={40000} value={fields.design_markdown} disabled={Boolean(busy)} placeholder="支持 Markdown：方案目标、整体设计、业务流程、模块能力、实施边界等。" onChange={event => update('design_markdown', event.target.value)} />}
          </section>
          <div className="solution-form-grid solution-delivery-fields">{SOLUTION_DETAIL_FIELDS.map(field => <label key={field.key} className={`field${field.key === 'risks_dependencies' ? ' solution-field-full' : ''}`}><span>{field.label}</span><textarea rows={4} maxLength={16000} value={fields[field.key]} disabled={Boolean(busy)} placeholder={field.placeholder} onChange={event => update(field.key, event.target.value)} /></label>)}</div>
        </div>
      </div>
      <footer className="solution-editor-footer">{error ? <p className="form-error" role="alert">{error}</p> : null}{discard ? <div className="solution-discard" role="alert"><span>当前修改尚未保存，确定放弃吗？</span><button className="secondary-button" type="button" onClick={() => setDiscard(false)}>继续编辑</button><button className="danger-button" type="button" onClick={() => { saved.current = true; onClose() }}>放弃修改</button></div> : <div className="dialog-actions"><button className="secondary-button" type="button" disabled={Boolean(busy)} onClick={close}>取消</button><button className="primary-button" type="button" disabled={Boolean(busy)} onClick={() => void save()}>{busy === 'save' ? '保存中…' : '保存方案'}</button></div>}</footer>
    </section>
}
