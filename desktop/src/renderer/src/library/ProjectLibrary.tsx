import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { BUSINESS_CATEGORIES, BUSINESS_CATEGORY_LABELS, BUSINESS_CATEGORY_UNCATEGORIZED_LABEL } from "../businessCategory"
import { useDangerConfirm } from "../common/DangerConfirmProvider"
import { DocumentPreview } from "../documents/DocumentPreview"
import { DocumentVersionTimeline, versionCanDownload, versionCanPreview } from "../documents/DocumentVersionTimeline"
import { isDocumentListDto } from "../documents/runtimeValidation"
import { DOCUMENT_SOURCE_LABELS, DOCUMENT_TYPE_LABELS, type DocumentSummaryDto } from "../documents/types"
import { FilePreview } from "../files/FilePreview"
import { FileVersionTimeline } from "../files/FileVersionTimeline"
import { versionCanBePreviewed } from "../files/fileCapabilities"
import { ProjectFiles } from "../files/ProjectFiles"
import { isFileUrlDto, isProjectFileListDto } from "../files/runtimeValidation"
import type { ProjectFileDto } from "../files/types"
import type { LibraryRow } from "./types"

type PreviewTarget = { kind: "file"; file: ProjectFileDto } | { kind: "document"; document: DocumentSummaryDto }

export function ProjectLibrary({ projectId, canManage, documentType }: { projectId: string; canManage: boolean; documentType?: "sow" }) {
  const { apiRequest, user } = useAuth()
  const dangerConfirm = useDangerConfirm()
  const titleId = useId()
  const libraryTitle = documentType === "sow" ? "SOW 文件" : "文件库"
  const [files, setFiles] = useState<ProjectFileDto[]>([])
  const [documents, setDocuments] = useState<DocumentSummaryDto[]>([])
  const [loading, setLoading] = useState(true)
  const [fileError, setFileError] = useState("")
  const [documentError, setDocumentError] = useState("")
  const [actionError, setActionError] = useState("")
  const [businessCategory, setBusinessCategory] = useState("")
  const [kind, setKind] = useState<"all" | "file" | "document">("all")
  const [status, setStatus] = useState<"all" | "normal" | "deprecated">("normal")
  const [uploadOpen, setUploadOpen] = useState(false)
  const [preview, setPreview] = useState<PreviewTarget | null>(null)
  const [timeline, setTimeline] = useState<PreviewTarget | null>(null)
  const [renameTarget, setRenameTarget] = useState<LibraryRow | null>(null)
  const [renameValue, setRenameValue] = useState("")
  const [renameBusy, setRenameBusy] = useState(false)
  const [renameError, setRenameError] = useState("")
  const sequenceRef = useRef(0)

  const load = useCallback(async (silent = false) => {
    const sequence = ++sequenceRef.current
    if (!silent) setLoading(true)
    const [fileResult, documentResult] = await Promise.allSettled([
      documentType ? Promise.resolve({ items: [] }) : apiRequest<unknown>(libraryPath(projectId, "files", businessCategory), { method: "GET" }),
      apiRequest<unknown>(libraryPath(projectId, "documents", businessCategory), { method: "GET" }),
    ])
    if (sequence !== sequenceRef.current) return
    if (fileResult.status === "fulfilled" && isProjectFileListDto(fileResult.value)) {
      setFiles(fileResult.value.items); setFileError("")
    } else {
      setFiles([]); setFileError(libraryLoadError("file", fileResult.status === "rejected" ? fileResult.reason : null))
    }
    if (documentResult.status === "fulfilled" && isDocumentListDto(documentResult.value)) {
      setDocuments(documentResult.value.items.filter((item) => !documentType || item.document_type === documentType)); setDocumentError("")
    } else {
      const error = documentResult.status === "rejected" ? documentResult.reason : null
      setDocuments([]); setDocumentError(documentType ? (error instanceof ApiClientError && error.code === "forbidden" ? "你没有权限查看 SOW 文件。" : "SOW 文件加载失败，请稍后重试。") : libraryLoadError("document", error))
    }
    if (!silent) setLoading(false)
  }, [apiRequest, businessCategory, documentType, projectId])

  useEffect(() => { void load(); return () => { sequenceRef.current += 1 } }, [load, user?.id])

  useEffect(() => {
    if (!files.some((file) => file.generation_status === "queued" || file.generation_status === "generating")
      && !documents.some((document) => documentGenerating(document))) return
    const timer = window.setTimeout(() => { void load(true) }, 1500)
    return () => window.clearTimeout(timer)
  }, [documents, files, load])

  const rows = useMemo(() => normalizeRows(documentType ? [] : files, documents)
    .filter((row) => documentType ? row.kind === "document" && row.source.document_type === documentType : kind === "all" || row.kind === kind)
    .filter((row) => status === "all" || (status === "deprecated" ? rowDeprecated(row) : !rowDeprecated(row)))
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt)), [documents, documentType, files, kind, status])

  async function download(row: LibraryRow) {
    setActionError("")
    const versionId = cardVersion(row)?.id
    if (!versionId) return
    const resource = row.kind === "file" ? "files" : "documents"
    try {
      const result = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/${resource}/${encodeURIComponent(versionId)}/download-url`, { method: "GET" })
      if (!isFileUrlDto(result)) throw new Error("invalid download url")
      const anchor = document.createElement("a")
      anchor.href = result.url
      anchor.download = row.kind === "file" ? (row.source.current_version?.original_filename || row.source.display_name) : `${row.title}.docx`
      document.body.appendChild(anchor); anchor.click(); anchor.remove()
    } catch (caught) {
      setActionError(caught instanceof ApiClientError && caught.code === "file_not_available" ? "该版本尚不可下载。" : "下载失败，请稍后重试。")
    }
  }

  async function restore(row: LibraryRow) {
    setActionError("")
    try {
      if (row.kind === "file") {
        await apiRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/files/items/${encodeURIComponent(row.id)}/restore`, { method: "POST" })
      } else {
        await apiRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/documents/items/${encodeURIComponent(row.id)}/restore`, { method: "POST", body: { version: row.source.version } })
      }
      await load()
    } catch (caught) {
      setActionError(restorationError(caught))
    }
  }

  async function deprecate(row: LibraryRow) {
    const confirmed = await dangerConfirm({ title: "标记文件为弃用", description: `确定将“${row.title}”的所有启用版本标记为弃用吗？历史版本仍会保留，可在“弃用”筛选中恢复最新版本。`, confirmLabel: "标记为弃用" })
    if (!confirmed) return
    setActionError("")
    try {
      if (row.kind === "file") {
        await apiRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/files/items/${encodeURIComponent(row.id)}/deprecate`, { method: "POST", body: { reason: "人工弃用" } })
      } else {
        await apiRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/documents/items/${encodeURIComponent(row.id)}/archive`, { method: "POST", body: { version: row.source.version } })
      }
      await load()
    } catch (caught) {
      setActionError(deprecationError(caught))
    }
  }

  async function retryGeneration(file: ProjectFileDto) {
    if (!file.generation_form_id) return
    if (!window.confirm(`确定重新生成“${file.display_name}”吗？\n\n确认后系统会在后台生成，期间可继续使用其他功能。`)) return
    setActionError("")
    try {
      await apiRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/research/forms/${encodeURIComponent(file.generation_form_id)}/export`, { method: "POST", body: {} })
      await load(true)
    } catch (caught) {
      setActionError(caught instanceof ApiClientError ? `重新生成失败：${caught.message}` : "重新生成失败，请稍后重试。")
    }
  }

  function beginRename(row: LibraryRow) {
    setRenameTarget(row); setRenameValue(row.title); setRenameError("")
  }

  async function submitRename() {
    if (!renameTarget) return
    const name = renameValue.trim()
    if (!name) { setRenameError("请填写文档名称。"); return }
    setRenameBusy(true); setRenameError("")
    try {
      if (renameTarget.kind === "document") {
        await apiRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(renameTarget.id)}`, {
          method: "PATCH",
          body: { version: renameTarget.source.version, name },
        })
      } else {
        await apiRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/files/items/${encodeURIComponent(renameTarget.id)}`, {
          method: "PATCH",
          body: { name },
        })
      }
      setRenameTarget(null)
      await load(true)
    } catch (caught) {
      setRenameError(renameFailureMessage(caught))
    } finally {
      setRenameBusy(false)
    }
  }

  if (timeline?.kind === "file") return <FileVersionTimeline mode="page" projectId={projectId} file={timeline.file} canManage={canManage} onChanged={() => void load()} onClose={() => setTimeline(null)} />
  if (timeline?.kind === "document") return <DocumentVersionTimeline mode="page" projectId={projectId} documentId={timeline.document.id} title={timeline.document.business_code} onClose={() => setTimeline(null)} />

  return <section className="panel table-panel project-library" aria-labelledby={titleId}>
    <div className="panel-heading library-heading"><div><h2 id={titleId}>{libraryTitle}</h2><p className="supporting-copy compact-copy">{documentType ? "与项目文件库同步，仅展示 SOW 工作说明书；历史版本保留，可预览、下载和管理。" : "项目文件用于人工归档；调研结果、PoV 和 SOW 等业务文档生成后会自动进入这里。"}</p></div><span>{rows.length} 个文件</span></div>
    <div className="project-list-toolbar library-toolbar" role="toolbar" aria-label={`${libraryTitle}工具栏`}>
      {canManage && !documentType ? <button className="primary-button" type="button" onClick={() => setUploadOpen(true)}>上传项目文件</button> : null}
      {!documentType ? <label className="field library-filter library-kind-filter"><span>类型</span><select aria-label="筛选文件类型" value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}><option value="all">全部</option><option value="file">项目文件</option><option value="document">业务文档</option></select></label> : null}
      <label className="field library-filter business-category-filter"><span>业务阶段</span><select aria-label="筛选业务阶段" value={businessCategory} onChange={(event) => setBusinessCategory(event.target.value)}><option value="">全部</option><option value={BUSINESS_CATEGORY_UNCATEGORIZED_LABEL}>{BUSINESS_CATEGORY_UNCATEGORIZED_LABEL}</option>{BUSINESS_CATEGORIES.map((category) => <option key={category} value={category}>{BUSINESS_CATEGORY_LABELS[category]}</option>)}</select></label>
      <label className="field library-filter library-status-filter"><span>状态</span><select aria-label="筛选文件状态" value={status} onChange={(event) => setStatus(event.target.value as typeof status)}><option value="all">全部</option><option value="normal">正常</option><option value="deprecated">弃用</option></select></label>
    </div>
    {!canManage ? <p className="field-hint">{documentType ? "你可以查看、预览和下载 SOW 文件，但当前角色不能修改或弃用文件。" : "你可以查看、预览和下载文件库内容，但当前角色不能上传或弃用文件。"}</p> : null}
    {fileError ? <p className="form-error banner" role="alert">{fileError}</p> : null}
    {documentError ? <p className="form-error banner" role="alert">{documentError}</p> : null}
    {actionError ? <p className="form-error banner" role="alert">{actionError}</p> : null}
    {loading ? <p role="status">正在加载{libraryTitle}…</p> : rows.length === 0 ? <p className="empty-state">{documentType ? "暂无符合筛选条件的 SOW 文件。保存方案并导出 SOW 后会自动出现在这里。" : "暂无文件。可上传项目文件，业务文档会在调研或 AI 机会中生成后自动出现。"}</p> : <div className="library-card-grid" role="list" aria-label={libraryTitle}>
      {rows.map((row) => <article className="library-file-card" role="listitem" key={`${row.kind}:${row.id}`}>
        <header className="library-card-header">
          <div className="library-card-title"><div className="library-card-name"><h3>{row.title}</h3>{canManage ? <button className="library-rename-button" type="button" aria-label={`重命名：${row.title}`} title="重命名" onClick={() => beginRename(row)}><RenameIcon /></button> : null}</div>{row.kind === "file" && row.source.current_version?.original_filename ? <p>{row.source.current_version.original_filename}</p> : row.kind === "document" ? <p>{DOCUMENT_TYPE_LABELS[row.source.document_type]}</p> : null}</div>
          <span className={`badge ${row.kind === "file" ? "muted" : "business-category"}`}>{row.kind === "file" ? "项目文件" : "业务文档"}</span>
        </header>
        {rowGenerating(row) ? <div className="library-card-generation" role="status"><span className="ai-spinner" aria-hidden="true" /><div><strong>正在后台生成</strong><p>生成完成后会自动更新为可预览、可下载的文件版本。</p></div></div> : rowGenerationFailed(row) ? <div className="library-card-generation failed" role="alert"><div><strong>生成失败</strong><p>{generationFailureMessage(row.source.generation_message)}</p></div></div> : <dl className="library-card-meta">
          <div><dt>业务阶段</dt><dd>{row.category || BUSINESS_CATEGORY_UNCATEGORIZED_LABEL}</dd></div>
          <div><dt>当前版本</dt><dd>{cardVersion(row) ? `v${cardVersion(row)?.version_number}` : ""}</dd></div>
          <div><dt>上传者</dt><dd>{row.actor}</dd></div>
          <div className="library-card-time"><dt>上传时间</dt><dd>{formatTime(row.updatedAt)}</dd></div>
        </dl>}
        <footer className="library-card-actions"><div className="row-actions">
          {rowDownloadable(row) ? <button className="secondary-button compact" type="button" onClick={() => void download(row)}>下载</button> : null}
          {rowPreviewable(row) ? <button className="secondary-button compact" type="button" onClick={() => setPreview(row.kind === "file" ? { kind: "file", file: fileAtCardVersion(row.source) } : { kind: "document", document: row.source })}>预览</button> : null}
          {cardVersion(row) ? <button className="secondary-button compact" type="button" onClick={() => setTimeline(row.kind === "file" ? { kind: "file", file: row.source } : { kind: "document", document: row.source })}>版本</button> : null}
          {canManage && rowDeprecatable(row) ? <button className="danger-button compact" type="button" onClick={() => void deprecate(row)}>标记为弃用</button> : null}
          {canManage && rowDeprecated(row) ? <button className="secondary-button compact" type="button" onClick={() => void restore(row)}>恢复</button> : null}
          {canManage && row.kind === "file" && row.source.generation_status === "failed" && row.source.generation_form_id ? <button className="secondary-button compact" type="button" onClick={() => void retryGeneration(row.source)}>重新生成</button> : null}
        </div></footer>
      </article>)}
    </div>}
    {uploadOpen && !documentType ? <div className="dialog-backdrop library-manager-backdrop"><section className="dialog library-manager-dialog" role="dialog" aria-modal="true" aria-label="上传项目文件"><div className="dialog-heading"><div><h3>上传项目文件</h3><p className="supporting-copy compact-copy">上传时填写文件名称；同一文件后续可继续上传新版本。</p></div><button className="secondary-button compact" type="button" onClick={() => { setUploadOpen(false); void load() }}>关闭</button></div><ProjectFiles projectId={projectId} canManage={canManage} uploadOnly /></section></div> : null}
    {renameTarget ? <div className="dialog-backdrop" role="presentation"><section className="dialog library-rename-dialog" role="dialog" aria-modal="true" aria-labelledby="library-rename-title"><div className="dialog-heading"><div><h3 id="library-rename-title">修改文档名称</h3><p className="supporting-copy compact-copy">仅修改文件库中显示和后续下载使用的名称，不会新建文档版本。</p></div></div><label className="field" htmlFor="library-rename-input"><span>文档名称</span><input id="library-rename-input" autoFocus maxLength={renameTarget.kind === "document" ? 80 : 255} value={renameValue} disabled={renameBusy} onChange={(event) => setRenameValue(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void submitRename() } }} /></label>{renameError ? <p className="form-error" role="alert">{renameError}</p> : null}<div className="dialog-actions"><button className="secondary-button" type="button" disabled={renameBusy} onClick={() => setRenameTarget(null)}>取消</button><button className="primary-button" type="button" disabled={renameBusy || !renameValue.trim()} onClick={() => void submitRename()}>{renameBusy ? "正在保存…" : "保存"}</button></div></section></div> : null}
    {preview?.kind === "file" ? <FilePreview projectId={projectId} file={preview.file} canRegenerate={canManage} onClose={() => setPreview(null)} /> : null}
    {preview?.kind === "document" && preview.document.current_version ? <DocumentPreview projectId={projectId} title={preview.document.business_code} versionId={preview.document.current_version.id} onClose={() => setPreview(null)} /> : null}
  </section>
}

function normalizeRows(files: ProjectFileDto[], documents: DocumentSummaryDto[]): LibraryRow[] {
  const documentFileIds = new Set(documents.map((item) => item.library_file_id).filter((id): id is string => Boolean(id)))
  return [
    ...files.filter((file) => !documentFileIds.has(file.id)).map((file): LibraryRow => ({ id: file.id, kind: "file", title: file.display_name, category: file.business_category ? BUSINESS_CATEGORY_LABELS[file.business_category] : "", actor: (file.latest_version ?? file.current_version)?.uploaded_by ?? file.created_by ?? "", updatedAt: (file.latest_version ?? file.current_version)?.uploaded_at ?? file.generation_updated_at ?? "", source: file })),
    ...documents.map((document): LibraryRow => ({ id: document.id, kind: "document", title: document.display_name || document.business_code, category: document.business_category ? BUSINESS_CATEGORY_LABELS[document.business_category] : "", actor: document.current_version ? DOCUMENT_SOURCE_LABELS[document.current_version.source] : "", updatedAt: document.current_version?.created_at ?? document.updated_at ?? document.created_at, source: document })),
  ]
}

function cardVersion(row: LibraryRow) { return row.kind === "file" ? (row.source.current_version ?? row.source.latest_version) : row.source.current_version }
function fileAtCardVersion(file: ProjectFileDto): ProjectFileDto { const active = file.current_version ?? file.latest_version; return { ...file, current_version: active ?? null, current_version_id: active?.id ?? null } }
function documentGenerating(document: DocumentSummaryDto): boolean { return document.generation_status === "queued" || document.generation_status === "running" }
function rowGenerating(row: LibraryRow): boolean { return row.kind === "file" ? row.source.generation_status === "queued" || row.source.generation_status === "generating" : documentGenerating(row.source) }
function rowGenerationFailed(row: LibraryRow): boolean { return row.kind === "file" ? row.source.generation_status === "failed" && !cardVersion(row) : row.source.generation_status === "failed" }
function rowDeprecated(row: LibraryRow): boolean { return row.kind === "file" ? !row.source.current_version && Boolean(row.source.latest_version) : Boolean(row.source.current_version && row.source.current_version.status === "archived") }
function rowDownloadable(row: LibraryRow): boolean {
  if (row.kind === "file") return (row.source.current_version ?? row.source.latest_version)?.status === "available"
  return Boolean(row.source.current_version && versionCanDownload(row.source.current_version))
}
function rowPreviewable(row: LibraryRow): boolean {
  if (row.kind === "file") return versionCanBePreviewed(row.source.current_version ?? row.source.latest_version, row.source.display_name)
  return Boolean(row.source.current_version && versionCanPreview(row.source.current_version))
}
function rowDeprecatable(row: LibraryRow): boolean { return row.kind === "file" ? row.source.current_version?.status === "available" : Boolean(row.source.current_version && row.source.current_version.status !== "archived") }
function libraryPath(projectId: string, resource: "files" | "documents", category: string) { const base = `/api/v1/projects/${encodeURIComponent(projectId)}/${resource}`; return category ? `${base}?business_category=${encodeURIComponent(category)}` : base }
function formatTime(value: string) { if (!value) return ""; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false }) }
function generationFailureMessage(message?: string | null): string {
  if (!message) return "文档生成失败，请重新生成。"
  if (message.includes("template_placeholder_remaining")) return "模板仍有未生成的占位内容，系统已补齐兼容处理，请重新生成。"
  if (message.includes("template_docx_unavailable")) return "未找到可用的 DOCX 模板，请先在文档模板中发布对应模板。"
  return message.startsWith("生成") || /[\u4e00-\u9fff]/.test(message) ? message : "文档生成失败，请稍后重试。"
}
function libraryLoadError(kind: "file" | "document", error: unknown): string { const label = kind === "file" ? "项目文件" : "业务文档"; if (error instanceof ApiClientError && error.code === "forbidden") return `你没有权限查看${label}。`; return `${label}加载失败，另一类内容仍可继续使用。` }
function deprecationError(error: unknown): string {
  if (!(error instanceof ApiClientError)) return "标记弃用失败，请检查本地服务是否正在运行。"
  const messages: Record<string, string> = {
    stale_version: "内容已被其他人更新，请刷新后重试。",
    forbidden: "当前账号没有标记弃用的权限。",
    file_version_not_available: "该文件版本当前不可用，只有可下载的版本可以标记为弃用。",
    invalid_document_state: "该业务文档的当前状态不允许标记为弃用。",
    file_version_not_found: "文件版本不存在或已经发生变化，请刷新后重试。",
    version_not_found: "业务文档版本不存在或已经发生变化，请刷新后重试。",
    document_not_found: "业务文档不存在或已经被删除。",
    mutation_resubmit_required: "登录状态刚刚刷新，请重新点击标记为弃用。",
  }
  return messages[error.code] ?? "标记弃用失败，请刷新文件库后重试。"
}
function restorationError(error: unknown): string {
  if (!(error instanceof ApiClientError)) return "恢复失败，请检查本地服务是否正在运行。"
  const messages: Record<string, string> = {
    stale_version: "内容已被其他人更新，请刷新后重试。",
    forbidden: "当前账号没有恢复文件的权限。",
    file_version_not_restorable: "该文件版本当前不能恢复。",
    invalid_document_state: "该业务文档版本当前不能恢复。",
    file_version_not_found: "文件版本不存在或已经发生变化，请刷新后重试。",
    version_not_found: "业务文档版本不存在或已经发生变化，请刷新后重试。",
  }
  return messages[error.code] ?? "恢复失败，请刷新文件库后重试。"
}

function renameFailureMessage(error: unknown): string {
  if (!(error instanceof ApiClientError)) return "重命名失败，请稍后重试。"
  const messages: Record<string, string> = {
    document_name_invalid: error.message,
    file_display_name_invalid: error.message,
    document_name_conflict: "项目中已存在同名文档。",
    file_name_conflict: "项目中已存在同名文件。",
    stale_version: "文档已被其他人更新，请刷新后重试。",
    forbidden: "当前账号没有重命名权限。",
  }
  return messages[error.code] ?? error.message
}

function RenameIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4l10.6-10.6a1.8 1.8 0 0 0 0-2.5l-1.5-1.5a1.8 1.8 0 0 0-2.5 0L4 16v4Z" /><path d="m13.5 6.5 4 4" /></svg>
}
