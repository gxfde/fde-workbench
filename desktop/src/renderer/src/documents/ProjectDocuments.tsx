import { useCallback, useEffect, useRef, useState, type ChangeEvent, type MouseEvent, type ReactNode } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { useDangerConfirm } from "../common/DangerConfirmProvider"
import { BUSINESS_CATEGORIES, BUSINESS_CATEGORY_LABELS, BUSINESS_CATEGORY_UNCATEGORIZED_LABEL } from "../businessCategory"
import type { BusinessCategory } from "../businessCategory"
import { isDocumentListDto } from "./runtimeValidation"
import type { DocumentSummaryDto, DocumentTypeKey, DocumentVersionSummary } from "./types"
import { DOCUMENT_TYPE_KEYS, DOCUMENT_TYPE_LABELS } from "./types"
import { DocumentEditor } from "./DocumentEditor"
import type { ResearchSubjectDto } from "../research/types"
import { OpportunityFilter } from './OpportunityFilter'
import { DocumentPreview } from "./DocumentPreview"
import { DocumentVersionTimeline, versionCanDownload, versionCanPreview } from "./DocumentVersionTimeline"

interface ProjectDocumentsProps {
  projectId: string
  canManage: boolean
  deliveryMode?: boolean
  historyMode?: boolean
}

/** Fallback published-template id sent when the admin template catalog is unavailable. */
const FALLBACK_TEMPLATE_VERSION_ID = "published"

export function ProjectDocuments({ projectId, canManage, deliveryMode = false, historyMode = false }: ProjectDocumentsProps) {
  const { apiRequest } = useAuth()
  const dangerConfirm = useDangerConfirm()
  const [documents, setDocuments] = useState<DocumentSummaryDto[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const [createOpen, setCreateOpen] = useState(false)
  const [newDocumentType, setNewDocumentType] = useState<DocumentTypeKey>("sow")
  const [createBusinessCategory, setCreateBusinessCategory] = useState<BusinessCategory | null>(null)
  const [filterCategory, setFilterCategory] = useState<string>("")
  const [createTemplateVersionId, setCreateTemplateVersionId] = useState("")
  const [publishedByType, setPublishedByType] = useState<Record<string, string>>({})
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState("")
  const [subjects, setSubjects] = useState<ResearchSubjectDto[]>([])
  const opportunities = subjects.filter(item => item.subject_type === 'opportunity')
  const groups = opportunityGroups(subjects)
  const [statusFilter, setStatusFilter] = useState('normal')
  const objectIds = new Set(groups.flatMap(group => subjectAncestors(subjects, group.id).map(item => item.id)))
  const filterOptions = [{ value: '', label: '全部机会' }, ...subjects.filter(item => objectIds.has(item.id)).flatMap(item => [
    { value: `object:${item.id}`, label: subjectAncestors(subjects, item.id).map(parent => parent.name).join(' › ') },
    ...(groups.find(group => group.id === item.id)?.items ?? []).map(opportunity => ({ value: opportunity.id, label: `${opportunity.tracking_code ?? ''} ${opportunity.name}`.trim(), level: 1 })),
  ]), ...groups.filter(group => !subjects.some(item => item.id === group.id)).flatMap(group => group.items.map(item => ({ value: item.id, label: item.name, level: 1 })))]
  const [selectedOpportunities, setSelectedOpportunities] = useState<string[]>([])
  const [generationScope, setGenerationScope] = useState("")
  const [opportunityFilter, setOpportunityFilter] = useState(() => new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('opportunity') ?? '')
  useEffect(() => {
    const sync = () => setOpportunityFilter(new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('opportunity') ?? '')
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])
  const selectedIds = opportunityFilter.startsWith('object:') ? opportunities.filter(item => subjectAncestors(subjects, item.id).some(parent => parent.id === opportunityFilter.slice(7))).map(item => item.id) : [opportunityFilter]
  const visibleDocuments = documents.filter(document => (!deliveryMode || statusFilter === 'all' || (statusFilter === 'archived' ? document.status === 'archived' : document.status !== 'archived')) && (!opportunityFilter || selectedIds.includes(document.source_opportunity_id ?? '') || document.opportunity_scope?.opportunities.some(item => selectedIds.includes(item.source_opportunity_id))))
  useEffect(() => {
    if (!deliveryMode) return
    let active = true
    void apiRequest<{ items: ResearchSubjectDto[] }>(`/api/v1/projects/${projectId}/research/subjects`, { method: 'GET' }).then(value => {
      if (active) setSubjects(value.items)
    }).catch(() => { if (active) setError('无法加载 AI 机会，请重新进入交付文档。') })
    return () => { active = false }
  }, [apiRequest, projectId, deliveryMode])

  const [preview, setPreview] = useState<{ title: string; versionId: string } | null>(null)
  const [timeline, setTimeline] = useState<DocumentSummaryDto | null>(null)
  const [editor, setEditor] = useState<DocumentSummaryDto | null>(null)
  const [actionError, setActionError] = useState("")

  const sequenceRef = useRef(0)
  const uploadInputRef = useRef<HTMLInputElement>(null)
  const uploadTargetRef = useRef<DocumentSummaryDto | null>(null)

  const loadDocuments = useCallback(async (options?: { quiet?: boolean }): Promise<void> => {
    const sequence = ++sequenceRef.current
    if (!options?.quiet) setLoading(true)
    try {
      const next = await apiRequest<unknown>(documentsPath(projectId, filterCategory), { method: "GET" })
      if (sequence !== sequenceRef.current) return
      if (!isDocumentListDto(next)) throw new Error("invalid document list")
      setDocuments(deliveryMode ? next.items.filter(item => ['pov_plan', 'sow'].includes(item.document_type)) : next.items)
      setError("")
    } catch (caught) {
      if (sequence === sequenceRef.current) setError(documentError(caught))
    } finally {
      if (sequence === sequenceRef.current && !options?.quiet) setLoading(false)
    }
  }, [apiRequest, projectId, filterCategory, deliveryMode])

  useEffect(() => {
    void loadDocuments()
    return () => { sequenceRef.current += 1 }
  }, [loadDocuments])

  const shouldPoll = documents.some(documentNeedsPolling)
  useEffect(() => {
    if (!shouldPoll) return
    const timer = window.setInterval(() => { void loadDocuments({ quiet: true }) }, 2_000)
    return () => window.clearInterval(timer)
  }, [loadDocuments, shouldPoll])

  async function openCreate(): Promise<void> {
    setCreateOpen(true)
    setCreateError("")
    setSelectedOpportunities([]); setGenerationScope("")
    setNewDocumentType("sow")
    setCreateBusinessCategory(null)
    setCreateTemplateVersionId("")
    await loadCreateTemplateOptions("sow")
  }

  async function loadCreateTemplateOptions(type: DocumentTypeKey): Promise<void> {
    try {
      const next = await apiRequest<unknown>("/api/v1/document-templates", { method: "GET" })
      const versions = publishedVersionByType(next)
      setPublishedByType(versions)
      setCreateTemplateVersionId(versions[type] ?? "")
    } catch {
      // Admin-only catalog; fall back to a default template version id on submit.
      setPublishedByType({})
      setCreateTemplateVersionId("")
    }
  }

  function handleCreateTypeChange(type: DocumentTypeKey): void {
    setNewDocumentType(type)
    setCreateTemplateVersionId(publishedByType[type] ?? "")
  }

  async function submitCreate(): Promise<void> {
    if (deliveryMode && !selectedOpportunities.length) { setCreateError('请至少选择一个 AI 机会。'); return }
    setCreating(true)
    setCreateError("")
    try {
      const templateVersionId = createTemplateVersionId || FALLBACK_TEMPLATE_VERSION_ID
      const project = await apiRequest<unknown>(projectPath(projectId), { method: "GET" })
      const expectedVersion = isRecord(project) && typeof project.version === "number" && project.version >= 1 ? project.version : 1
      const created = await apiRequest<{ id: string; version: number }>(documentsPath(projectId), {
        method: "POST",
        body: {
          document_type: newDocumentType,
          ...(deliveryMode && !createTemplateVersionId ? {} : { template_version_id: templateVersionId }),
          expected_version: expectedVersion,
          business_category: createBusinessCategory ?? null,
          ...(deliveryMode ? { source_opportunity_ids: selectedOpportunities, generation_scope: generationScope.trim() } : {}),
        },
      })
      setCreateOpen(false)
      if (deliveryMode) {
        try { await apiRequest(`${detailPath(projectId, created.id)}/generate`, { method: 'POST', body: { version: created.version } }) }
        catch (caught) { setActionError(`草稿已创建，生成未成功，可在列表重试：${documentError(caught)}`) }
      }
      await loadDocuments({ quiet: true })
    } catch (caught) {
      setCreateError(createErrorText(caught))
    } finally {
      setCreating(false)
    }
  }

  async function generateDocument(document: DocumentSummaryDto): Promise<void> {
    setActionError("")
    try {
      await apiRequest<unknown>(`${detailPath(projectId, document.id)}/generate`, { method: "POST", body: { version: document.version } })
      await loadDocuments({ quiet: true })
    } catch (caught) {
      setActionError(documentError(caught))
    }
  }

  async function reviseDocument(document: DocumentSummaryDto): Promise<void> {
    setActionError("")
    try {
      await apiRequest<unknown>(`${detailPath(projectId, document.id)}/revise`, { method: "POST", body: { version: document.version, draft_changes: {} } })
      await loadDocuments({ quiet: true })
    } catch (caught) {
      setActionError(documentError(caught))
    }
  }

  async function confirmVersion(document: DocumentSummaryDto): Promise<void> {
    const versionId = document.current_version_id ?? document.current_version?.id
    if (!versionId) return
    setActionError("")
    try {
      await apiRequest<unknown>(`${documentsPath(projectId)}/${encodeURIComponent(versionId)}/confirm`, { method: "POST", body: { version: document.version } })
      await loadDocuments({ quiet: true })
    } catch (caught) {
      setActionError(documentError(caught))
    }
  }

  async function archiveVersion(document: DocumentSummaryDto): Promise<void> {
    const versionId = document.current_version_id ?? document.current_version?.id
    if (!versionId) return
    const confirmed = await dangerConfirm({
      title: "标记文档为弃用",
      description: `确定将文档“${document.business_code}”标记为弃用吗？弃用后该版本将在当前列表中隐藏，仍可在版本记录中查看。`,
      confirmLabel: "标记为弃用",
    })
    if (!confirmed) return
    setActionError("")
    try {
      await apiRequest<unknown>(`${documentsPath(projectId)}/${encodeURIComponent(versionId)}/archive`, { method: "POST", body: { version: document.version } })
      await loadDocuments({ quiet: true })
    } catch (caught) {
      setActionError(documentError(caught))
    }
  }

  async function downloadDocument(documentRecord: DocumentSummaryDto): Promise<void> {
    const versionId = documentRecord.current_version_id ?? documentRecord.current_version?.id
    if (!versionId) return
    setActionError("")
    try {
      const next = await apiRequest<unknown>(`${documentsPath(projectId)}/${encodeURIComponent(versionId)}/download-url`, { method: "GET" })
      if (!isRecord(next) || typeof next.url !== "string") throw new Error("invalid download url")
      const anchor = document.createElement("a")
      anchor.href = next.url
      anchor.download = `${documentRecord.business_code}.docx`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
    } catch (caught) {
      setActionError(documentError(caught))
    }
  }

  function requestManualUpload(document: DocumentSummaryDto): void {
    uploadTargetRef.current = document
    uploadInputRef.current?.click()
  }

  async function handleManualUpload(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = Array.from(event.target.files ?? [])[0]
    const target = uploadTargetRef.current
    event.target.value = ""
    if (!target || !file) return
    setActionError("")
    try {
      const base64 = await fileToBase64(file)
      await apiRequest<unknown>(`${detailPath(projectId, target.id)}/revisions/manual`, {
        method: "POST",
        body: { version: target.version, note: "", file_base64: base64 },
      })
      await loadDocuments({ quiet: true })
    } catch (caught) {
      setActionError(documentError(caught))
    }
  }

  return (
    <section className="panel table-panel" aria-labelledby="project-documents-title">
      <div className="panel-heading">
        <h2 id="project-documents-title">{historyMode ? '历史文档' : deliveryMode ? '交付文档' : '项目文档'}</h2>
        <span>{visibleDocuments.length} 个</span>
      </div>
      {deliveryMode && !historyMode ? <p>以项目交付或共同验证目标为主体，勾选多个 AI 机会生成草稿，审核后确认。机会快照不会随原资料自动更新。</p> : null}
      <div className="project-list-toolbar document-toolbar" role="toolbar" aria-label="文档工具栏">
        {canManage && !historyMode ? <button className="primary-button" type="button" onClick={() => void openCreate()}>新建文档</button> : null}
        {deliveryMode ? <OpportunityFilter value={opportunityFilter} options={filterOptions} onChange={setOpportunityFilter} /> : null}
        <label className="field business-category-filter" style={{ marginLeft: deliveryMode ? undefined : "auto" }}>
          <span>业务阶段</span>
          <select aria-label="筛选业务阶段" value={filterCategory} onChange={(event) => setFilterCategory(event.target.value)}>
            <option value="">全部</option>
            <option value={BUSINESS_CATEGORY_UNCATEGORIZED_LABEL}>{BUSINESS_CATEGORY_UNCATEGORIZED_LABEL}</option>
            {BUSINESS_CATEGORIES.map((category) => <option key={category} value={category}>{BUSINESS_CATEGORY_LABELS[category]}</option>)}
          </select>
        </label>
      {deliveryMode ? <label className="field business-category-filter delivery-status-filter"><span>状态</span><select aria-label="筛选文档状态" value={statusFilter} onChange={event => setStatusFilter(event.target.value)}><option value="all">全部</option><option value="normal">正常</option><option value="archived">弃用</option></select></label> : null}
      </div>
      {!canManage ? <p className="field-hint">你可以查看并下载可用的文档，但当前角色无法创建或编辑。</p> : null}
      {error ? <p className="form-error banner" role="alert">{error}</p> : null}
      {actionError ? <p className="form-error banner" role="alert">{actionError}</p> : null}
      {loading ? <p role="status">正在加载文档…</p> : visibleDocuments.length === 0 ? <p className="empty-state">{documents.length ? '暂无符合筛选条件的文档。' : '暂无项目文档。'}</p> : (
        <div className="table-scroll"><table aria-label="项目文档"><thead><tr><th>文档</th><th>状态</th><th>操作</th></tr></thead><tbody>
          {visibleDocuments.map((document) => (
            <tr key={document.id}>
              <td>
                <strong>{document.business_code}</strong>
                {document.opportunity_scope ? <div className="delivery-snapshot"><small>关联机会：{document.opportunity_scope.opportunities.map(item => `${item.opportunity_tracking_code} ${item.opportunity_name}`).join('、')}</small>{document.opportunity_scope.solution ? <p>来源方案：{document.opportunity_scope.solution.name} · 版本 {document.opportunity_scope.solution.version}</p> : <p>本次范围：{document.opportunity_scope.instructions || '按所选机会整理，未明确事项待确认'}</p>}{!document.opportunity_scope.solution && document.opportunity_scope.opportunities.some(snapshot => opportunities.some(item => item.id === snapshot.source_opportunity_id && item.version !== snapshot.version)) ? <p className="field-hint">来源机会已更新；本文档保留原快照。如需纳入变化，请保存新的方案后导出 SOW。</p> : null}</div> : document.source_opportunity_id ? <small>关联机会：{opportunities.find(item => item.id === document.source_opportunity_id)?.name ?? document.source_opportunity_id}（历史文档）</small> : null}
                <small className="table-subline">{DOCUMENT_TYPE_LABELS[document.document_type]}</small>
                {document.business_category ? <span className="badge business-category table-subline-chip">{document.business_category}</span> : null}
              </td>
              <td>
                <span className={`badge ${docStatusClass(document.status)}`}>{docStatusLabel(document.status)}</span>
                {document.current_version ? (
                  <small className="table-subline">{versionSummaryLabel(document.current_version)}</small>
                ) : null}
              </td>
              <td>{renderActions(document)}</td>
            </tr>
          ))}
        </tbody></table></div>
      )}
      {canManage ? <input ref={uploadInputRef} className="file-input-hidden" type="file" accept=".docx" aria-label="选择 DOCX 文件" onChange={(event) => void handleManualUpload(event)} /> : null}
      {preview ? <DocumentPreview projectId={projectId} title={preview.title} versionId={preview.versionId} onClose={() => setPreview(null)} /> : null}
      {timeline ? <DocumentVersionTimeline projectId={projectId} documentId={timeline.id} title={timeline.business_code} onClose={() => setTimeline(null)} /> : null}
      {editor ? <DocumentEditor projectId={projectId} documentId={editor.id} onClose={() => setEditor(null)} onUpdated={() => void loadDocuments({ quiet: true })} /> : null}
      {createOpen ? renderCreateDialog() : null}
    </section>
  )

  function renderActions(document: DocumentSummaryDto) {
    const version = document.current_version
    const versionId = document.current_version_id ?? version?.id
    // Automated exports come from the saved solution; manual document revisions remain available.
    const isDraft = document.status === "draft"
    const isSolutionExport = Boolean(document.opportunity_scope?.solution)
    const buttons: ReactNode[] = []
    if (canManage && isDraft && !isSolutionExport) {
      buttons.push(<button key="edit" className="secondary-button compact" type="button" aria-label={`编辑：${document.business_code}`} onClick={() => setEditor(document)}>编辑</button>)
    }
    if (version) {
      buttons.push(<button key="versions" className="secondary-button compact" type="button" aria-label={`版本：${document.business_code}`} onClick={() => setTimeline(document)}>版本</button>)
    }
    if (version && versionCanDownload(version)) {
      buttons.push(<button key="download" className="secondary-button compact" type="button" aria-label={`下载：${document.business_code}`} onClick={() => void downloadDocument(document)}>下载</button>)
    }
    if (version && versionCanPreview(version)) {
      buttons.push(<button key="preview" className="secondary-button compact" type="button" aria-label={`预览：${document.business_code}`} onClick={() => { if (versionId) setPreview({ title: document.business_code, versionId }) }}>预览</button>)
    }
    if (canManage && isDraft) {
      if (!isSolutionExport) buttons.push(<button key="generate" className="secondary-button compact" type="button" aria-label={`生成：${document.business_code}`} onClick={() => void generateDocument(document)}>生成</button>)
      if (version) {
        buttons.push(<button key="revise" className="secondary-button compact" type="button" aria-label={`在线修订：${document.business_code}`} onClick={() => void reviseDocument(document)}>在线修订</button>)
      }
      buttons.push(<button key="upload" className="secondary-button compact" type="button" aria-label={`人工上传：${document.business_code}`} onClick={() => requestManualUpload(document)}>人工上传</button>)
      if (version && version.status === "draft") {
        buttons.push(<button key="confirm" className="secondary-button compact" type="button" aria-label={`确认：${document.business_code}`} onClick={() => void confirmVersion(document)}>确认</button>)
        buttons.push(<button key="archive" className="secondary-button compact" type="button" aria-label={`标记为弃用：${document.business_code}`} onClick={() => void archiveVersion(document)}>标记为弃用</button>)
      }
    }
    return buttons.length > 0 ? <div className="row-actions">{buttons}</div> : null
  }

  function renderCreateDialog() {
    return (
      <div className="dialog-backdrop" role="presentation" onClick={(event: MouseEvent<HTMLDivElement>) => { if (!creating && event.target === event.currentTarget) setCreateOpen(false) }}>
        <div className="dialog document-create-dialog" role="dialog" aria-modal="true" aria-label="新建文档" onClick={(event) => event.stopPropagation()}>
          <div className="dialog-heading">
            <h3>新建文档</h3>
            <button className="secondary-button compact" type="button" disabled={creating} onClick={() => setCreateOpen(false)}>关闭</button>
          </div>
          <div className="document-create-fields">
            <label className="field">
              <span>文档类型</span>
              <select value={newDocumentType} onChange={(event) => handleCreateTypeChange(event.target.value as DocumentTypeKey)} aria-label="文档类型">
                {DOCUMENT_TYPE_KEYS.filter(key => !deliveryMode || ['pov_plan', 'sow'].includes(key)).map((key) => <option key={key} value={key}>{DOCUMENT_TYPE_LABELS[key]}</option>)}
              </select>
            </label>
            <label className="field">
              <span>业务阶段</span>
              <select
                value={createBusinessCategory ?? BUSINESS_CATEGORY_UNCATEGORIZED_LABEL}
                aria-label="新建文档业务阶段"
                onChange={(event) => {
                  const value = event.target.value
                  setCreateBusinessCategory(value === BUSINESS_CATEGORY_UNCATEGORIZED_LABEL ? null : value as BusinessCategory)
                }}
              >
                <option value={BUSINESS_CATEGORY_UNCATEGORIZED_LABEL}>{BUSINESS_CATEGORY_UNCATEGORIZED_LABEL}</option>
                {BUSINESS_CATEGORIES.map((category) => <option key={category} value={category}>{BUSINESS_CATEGORY_LABELS[category]}</option>)}
              </select>
            </label>
          </div>
          <p className="field-hint">将使用该文档类型已发布的模板版本创建草稿。</p>
          {deliveryMode ? <><fieldset className="delivery-opportunity-picker"><legend>选择 AI 机会（可多选）</legend>{groups.map(group => <section key={group.id} className="delivery-opportunity-group"><h4>{group.path}</h4>{group.items.filter(item => item.status === 'active').map(item => <label key={item.id}><input type="checkbox" checked={selectedOpportunities.includes(item.id)} onChange={event => setSelectedOpportunities(current => event.target.checked ? [...current, item.id] : current.filter(id => id !== item.id))} /><span><strong>{item.tracking_code} {item.name}</strong><small>{item.description}</small></span></label>)}</section>)}{!opportunities.some(item => item.status === 'active') ? <p>暂无可选机会，请先到调研中整理 AI 机会。</p> : null}</fieldset><label className="field">本次{newDocumentType === 'sow' ? '交付范围、责任边界' : '共同验证目标、通过标准'}及补充要求<textarea rows={4} maxLength={4000} value={generationScope} onChange={event => setGenerationScope(event.target.value)} /></label></> : null}
          {createError ? <p className="form-error" role="alert">{createError}</p> : null}
          <div className="dialog-actions">
            <button className="secondary-button" type="button" disabled={creating} onClick={() => setCreateOpen(false)}>取消</button>
            <button className="primary-button" type="button" disabled={creating} onClick={() => void submitCreate()}>
              {creating ? "创建中…" : deliveryMode ? "生成草稿" : "创建"}
            </button>
          </div>
        </div>
      </div>
    )
  }
}

export function subjectAncestors(subjects: ResearchSubjectDto[], id: string): ResearchSubjectDto[] {
  const path: ResearchSubjectDto[] = []
  let item = subjects.find(subject => subject.id === id)
  const visited = new Set<string>()
  while (item && !visited.has(item.id)) {
    visited.add(item.id); path.unshift(item)
    item = subjects.find(subject => subject.id === item?.parent_subject_id)
  }
  return path
}

export function opportunityGroups(subjects: ResearchSubjectDto[]) {
  const groups = new Map<string, { id: string; path: string; items: ResearchSubjectDto[] }>()
  for (const item of subjects.filter(subject => subject.subject_type === 'opportunity' && subject.status === 'active')) {
    const id = item.parent_subject_id ?? 'project'
    if (!groups.has(id)) groups.set(id, { id, path: subjectAncestors(subjects, id).map(parent => parent.name).join(' › ') || '项目直属机会', items: [] })
    groups.get(id)!.items.push(item)
  }
  return [...groups.values()].sort((a, b) => a.path.localeCompare(b.path, 'zh-CN'))
}

function versionSummaryLabel(version: DocumentVersionSummary): string {
  const sourceLabel = version.source === "generated" ? "系统生成" : version.source === "online_revised" ? "在线修订" : "人工上传"
  return `版本 ${version.version_number} · ${sourceLabel}`
}

function docStatusLabel(status: DocumentSummaryDto["status"]): string {
  return { draft: "草稿", confirmed: "已确认", archived: "已弃用" }[status]
}

function docStatusClass(status: DocumentSummaryDto["status"]): string {
  if (status === "confirmed") return "success"
  if (status === "draft") return "warning"
  return "muted"
}

function documentNeedsPolling(document: DocumentSummaryDto): boolean {
  if (document.status === "draft") return true
  const version = document.current_version
  return Boolean(version && (version.status === "draft" || version.preview_status === "pending"))
}

function publishedVersionByType(value: unknown): Record<string, string> {
  const result: Record<string, string> = {}
  if (!isRecord(value) || !Array.isArray(value.items)) return result
  for (const item of value.items) {
    if (!isRecord(item) || typeof item.document_type !== "string" || !Array.isArray(item.versions)) continue
    const published = (item.versions as unknown[]).find((version) => isRecord(version) && version.status === "published" && typeof version.id === "string")
    if (published) result[item.document_type] = (published as Record<string, unknown>).id as string
  }
  return result
}

async function fileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ""
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary)
}

function documentsPath(projectId: string, filterCategory?: string): string {
  const base = `/api/v1/projects/${encodeURIComponent(projectId)}/documents`
  return filterCategory ? `${base}?business_category=${encodeURIComponent(filterCategory)}` : base
}

function detailPath(projectId: string, documentId: string): string {
  return `${documentsPath(projectId)}/${encodeURIComponent(documentId)}`
}

function projectPath(projectId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function documentError(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "project_not_found") return "项目不存在或已被删除。"
  if (error instanceof ApiClientError && error.code === "forbidden") return "你没有权限操作该项目的文档。"
  if (error instanceof ApiClientError && error.code === "file_not_available") return "该文档版本尚不可下载。"
  if (error instanceof ApiClientError && error.code === "preview_not_available") return "该文档版本的预览尚未就绪。"
  return "文档操作失败，请稍后重试。"
}

function createErrorText(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "template_version_not_published") return "该文档类型的模板尚未发布。"
  if (error instanceof ApiClientError && error.code === "unknown_document_type") return "该文档类型不受支持。"
  if (error instanceof ApiClientError && error.code === "stale_version") return "项目已更新，请刷新后重试。"
  if (error instanceof ApiClientError && error.code === "forbidden") return "你没有权限创建文档。"
  return "创建文档失败，请稍后重试。"
}
