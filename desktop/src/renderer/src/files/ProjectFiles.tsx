import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { BUSINESS_CATEGORIES, BUSINESS_CATEGORY_LABELS, BUSINESS_CATEGORY_UNCATEGORIZED_LABEL } from "../businessCategory"
import type { BusinessCategory } from "../businessCategory"
import { FileUploader } from "./FileUploader"
import { fileTooLarge, versionCanBePreviewed } from "./fileCapabilities"
import { FilePreview } from "./FilePreview"
import { FileVersionTimeline, versionStatusClass, versionStatusLabel } from "./FileVersionTimeline"
import {
  isFileUrlDto,
  isProjectFileListDto,
  isUploadCompleteDto,
  isUploadedPartDto,
  isUploadSessionDto,
} from "./runtimeValidation"
import type {
  ProjectFileDto,
  UploadItem,
  UploadSessionDto,
} from "./types"

interface ProjectFilesProps {
  projectId: string
  canManage: boolean
  uploadOnly?: boolean
}

interface PendingNamedFile {
  id: string
  file: File
  displayName: string
}

export function ProjectFiles({ projectId, canManage, uploadOnly = false }: ProjectFilesProps) {
  const { apiRequest } = useAuth()
  const [files, setFiles] = useState<ProjectFileDto[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [uploads, setUploads] = useState<UploadItem[]>([])
  const [previewFile, setPreviewFile] = useState<ProjectFileDto | null>(null)
  const [timelineFile, setTimelineFile] = useState<ProjectFileDto | null>(null)
  const [filterCategory, setFilterCategory] = useState<string>("")
  const [pendingNamedFiles, setPendingNamedFiles] = useState<PendingNamedFile[]>([])
  const [namingError, setNamingError] = useState("")

  const sequenceRef = useRef(0)
  const uploadsRef = useRef<UploadItem[]>([])
  const fileRefs = useRef(new Map<string, File>())
  const replaceInputRef = useRef<HTMLInputElement>(null)
  const replaceTargetRef = useRef<ProjectFileDto | null>(null)
  const startedRef = useRef(new Set<string>())
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  const loadFiles = useCallback(async (options?: { quiet?: boolean }): Promise<void> => {
    const sequence = ++sequenceRef.current
    if (!options?.quiet) setLoading(true)
    try {
      const next = await apiRequest<unknown>(filesPath(projectId, filterCategory), { method: "GET" })
      if (sequence !== sequenceRef.current) return
      if (!isProjectFileListDto(next)) throw new Error("invalid file list")
      setFiles(next.items)
      setError("")
    } catch (caught) {
      if (sequence === sequenceRef.current) setError(fileError(caught))
    } finally {
      if (sequence === sequenceRef.current && !options?.quiet) setLoading(false)
    }
  }, [apiRequest, projectId, filterCategory])

  useEffect(() => {
    void loadFiles()
    return () => { sequenceRef.current += 1 }
  }, [loadFiles])

  const shouldPoll = files.some(fileNeedsPolling)
  useEffect(() => {
    if (!shouldPoll) return
    const timer = window.setInterval(() => { void loadFiles({ quiet: true }) }, 2_000)
    return () => window.clearInterval(timer)
  }, [loadFiles, shouldPoll])

  function updateUploads(updater: (prev: UploadItem[]) => UploadItem[]): void {
    const next = updater(uploadsRef.current)
    uploadsRef.current = next
    if (mountedRef.current) setUploads(next)
  }

  function patchUpload(id: string, patch: Partial<UploadItem>): void {
    updateUploads((prev) => prev.map((item) => item.id === id ? { ...item, ...patch } : item))
  }

  function addUploads(selected: File[]): void {
    const oversized = selected.find(fileTooLarge)
    if (oversized) {
      setError(`文件“${oversized.name}”超过 100MB，无法上传。`)
      return
    }
    setError("")
    setPendingNamedFiles(selected.map((file) => ({
      id: crypto.randomUUID(),
      file,
      displayName: file.name.replace(/\.[^.]+$/, ""),
    })))
    setNamingError("")
  }

  function confirmNamedUploads(): void {
    const normalized = pendingNamedFiles.map((item) => ({ ...item, displayName: item.displayName.trim() }))
    if (normalized.length === 0) return
    if (normalized.some((item) => !item.displayName)) {
      setNamingError("请为每个文件填写文件名称。")
      return
    }
    if (normalized.some((item) => item.displayName.length > 255)) {
      setNamingError("文件名称不能超过 255 个字符。")
      return
    }
    const businessCategory = categoryFromFilter(filterCategory)
    const newItems: UploadItem[] = normalized.map((selected): UploadItem => {
      fileRefs.current.set(selected.id, selected.file)
      return {
        id: selected.id,
        name: selected.file.name,
        displayName: selected.displayName,
        sizeBytes: selected.file.size,
        mimeType: selected.file.type,
        status: "pending",
        progress: 0,
        idempotencyKey: crypto.randomUUID(),
        businessCategory,
      }
    })
    updateUploads((prev) => [...prev, ...newItems])
    setPendingNamedFiles([])
    setNamingError("")
    for (const item of newItems) void runUpload(item.id)
  }

  async function runUpload(id: string): Promise<void> {
    if (startedRef.current.has(id)) return
    const item = uploadsRef.current.find((candidate) => candidate.id === id)
    if (!item || item.status === "completed" || item.status === "cancelled" || item.status === "uploading") return
    const file = fileRefs.current.get(id)
    if (!file) { patchUpload(id, { status: "failed", error: "文件对象不可用。" }); return }
    startedRef.current.add(id)
    try {
      patchUpload(id, { status: "uploading", error: undefined })
      const session = await apiRequest<unknown>(filesPath(projectId), {
        method: "POST",
        body: {
          name: file.name,
          display_name: item.displayName,
          file_id: item.fileId,
          size_bytes: file.size,
          mime_type: file.type,
          category: "attachment",
          business_category: item.businessCategory ?? null,
          idempotency_key: item.idempotencyKey,
        },
      })
      if (isCancelled(id)) return
      if (!isUploadSessionDto(session)) throw new Error("invalid upload session")
      patchUpload(id, { sessionId: session.id, partSize: session.part_size })
      const parts = await uploadParts(id, file, session)
      if (isCancelled(id)) return
      const complete = await apiRequest<unknown>(`${filesPath(projectId)}/${encodeURIComponent(session.id)}/complete`, {
        method: "POST",
        body: { parts },
      })
      if (isCancelled(id)) return
      if (!isUploadCompleteDto(complete)) throw new Error("invalid upload completion")
      patchUpload(id, { status: "completed", progress: 100 })
      await loadFiles({ quiet: true })
    } catch (caught) {
      if (isCancelled(id)) return
      patchUpload(id, { status: "failed", error: uploadError(caught) })
    } finally {
      startedRef.current.delete(id)
    }
  }

  function requestNewVersion(file: ProjectFileDto): void {
    replaceTargetRef.current = file
    replaceInputRef.current?.click()
  }

  function addNewVersion(event: ChangeEvent<HTMLInputElement>): void {
    const selected = Array.from(event.target.files ?? [])
    event.target.value = ""
    const target = replaceTargetRef.current
    if (!target || selected.length === 0) return
    const file = selected[0]
    if (fileTooLarge(file)) {
      setError(`文件“${file.name}”超过 100MB，无法上传。`)
      return
    }
    setError("")
    const id = crypto.randomUUID()
    fileRefs.current.set(id, file)
    const item: UploadItem = {
      id, name: file.name, displayName: target.display_name, fileId: target.id,
      sizeBytes: file.size, mimeType: file.type, status: "pending", progress: 0,
      idempotencyKey: crypto.randomUUID(), businessCategory: target.business_category ?? null,
    }
    updateUploads((prev) => [...prev, item])
    void runUpload(id)
  }

  async function uploadParts(id: string, file: File, session: UploadSessionDto): Promise<Array<{ part_number: number; etag: string }>> {
    const partSize = session.part_size
    const total = Math.max(1, Math.ceil(file.size / partSize))
    const parts: Array<{ part_number: number; etag: string }> = []
    let uploadedBytes = 0
    for (let partNumber = 1; partNumber <= total; partNumber += 1) {
      if (isCancelled(id)) return parts
      const signed = await apiRequest<unknown>(`${filesPath(projectId)}/${encodeURIComponent(session.id)}/parts`, {
        method: "POST",
        body: { part_number: partNumber },
      })
      if (isCancelled(id)) return parts
      if (!isUploadedPartDto(signed)) throw new Error("invalid signed part")
      const start = (partNumber - 1) * partSize
      const end = Math.min(file.size, start + partSize)
      const response = await fetch(signed.url, { method: "PUT", body: file.slice(start, end) })
      if (!response.ok) throw new Error(`storage_upload_failed:${response.status}`)
      const etag = stripQuote(response.headers.get("etag") ?? "")
      parts.push({ part_number: partNumber, etag })
      uploadedBytes += end - start
      patchUpload(id, { progress: Math.min(100, Math.round((uploadedBytes / Math.max(1, file.size)) * 100)) })
    }
    return parts
  }

  function cancelUpload(id: string): void {
    const item = uploadsRef.current.find((candidate) => candidate.id === id)
    if (!item) return
    if (item.status === "uploading" && item.sessionId) {
      void apiRequest<void>(`${filesPath(projectId)}/${encodeURIComponent(item.sessionId)}/abort`, { method: "POST" }).catch(() => {})
    }
    updateUploads((prev) => prev.map((candidate) => candidate.id === id ? { ...candidate, status: "cancelled" } : candidate))
  }

  function retryUpload(id: string): void {
    const item = uploadsRef.current.find((candidate) => candidate.id === id)
    if (!item) return
    updateUploads((prev) => prev.map((candidate) => candidate.id === id ? { ...candidate, status: "pending", progress: 0, error: undefined, sessionId: undefined, partSize: undefined } : candidate))
    void runUpload(id)
  }

  function isCancelled(id: string): boolean {
    return uploadsRef.current.find((candidate) => candidate.id === id)?.status === "cancelled"
  }

  async function downloadFile(file: ProjectFileDto): Promise<void> {
    const versionId = file.current_version_id ?? file.current_version?.id
    if (!versionId) return
    try {
      const next = await apiRequest<unknown>(`${filesPath(projectId)}/${encodeURIComponent(versionId)}/download-url`, { method: "GET" })
      if (!isFileUrlDto(next)) throw new Error("invalid download url")
      const anchor = document.createElement("a")
      anchor.href = next.url
      anchor.download = file.display_name
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
    } catch (caught) {
      setError(fileError(caught))
    }
  }

  const fileStatusLabel = (file: ProjectFileDto): string => {
    const status = file.current_version?.status
    return status ? versionStatusLabel(status) : "无版本"
  }
  const fileStatusClass = (file: ProjectFileDto): string => {
    const status = file.current_version?.status
    return status ? versionStatusClass(status) : "muted"
  }
  const categoryFilter = (
    <label className="field business-category-filter">
      <span>业务阶段</span>
      <select aria-label={uploadOnly ? "业务阶段" : "筛选业务阶段"} value={filterCategory} onChange={(event) => setFilterCategory(event.target.value)}>
        <option value="">全部</option>
        <option value={BUSINESS_CATEGORY_UNCATEGORIZED_LABEL}>{BUSINESS_CATEGORY_UNCATEGORIZED_LABEL}</option>
        {BUSINESS_CATEGORIES.map((category) => <option key={category} value={category}>{BUSINESS_CATEGORY_LABELS[category]}</option>)}
      </select>
    </label>
  )

  return (
    <section className={`panel table-panel${uploadOnly ? " project-files-upload-only" : ""}`} aria-labelledby={uploadOnly ? undefined : "project-files-title"} aria-label={uploadOnly ? "上传项目文件" : undefined}>
      {!uploadOnly ? <div className="panel-heading">
        <h2 id="project-files-title">项目文件</h2>
        <span>{files.length} 个</span>
      </div> : null}
      {canManage ? (
        <FileUploader canUpload onFilesSelected={addUploads} items={uploads} onCancel={cancelUpload} onRetry={retryUpload} toolbarExtra={categoryFilter} toolbarExtraPosition={uploadOnly ? "before" : "after"} />
      ) : <><div className="project-list-toolbar" role="toolbar" aria-label="文件工具栏">{categoryFilter}</div><p className="field-hint">你可以查看并下载可用的文件，但当前角色无法上传。</p></>}
      {error ? <p className="form-error banner" role="alert">{error}</p> : null}
      {!uploadOnly && (loading ? <p role="status">正在加载文件…</p> : files.length === 0 ? <p className="empty-state">暂无项目文件。</p> : (
        <div className="table-scroll"><table aria-label="项目文件"><thead><tr><th>文件</th><th>状态</th><th>上传者</th><th>操作</th></tr></thead><tbody>
          {files.map((file) => {
            const status = file.current_version?.status
            const available = status === "available"
            const hasVersion = Boolean(file.current_version)
            return <tr key={file.id}>
              <td>
                <strong>{file.display_name}</strong>
                <small className="table-subline">{categoryLabel(file.category)}{file.current_version ? ` · v${file.current_version.version_number}` : ""}</small>
                {file.business_category ? <span className="badge business-category table-subline-chip">{businessCategoryLabel(file.business_category)}</span> : null}
              </td>
              <td>
                <span className={`badge ${fileStatusClass(file)}`}>{fileStatusLabel(file)}</span>
              </td>
              <td>{file.created_by ?? "—"}</td>
              <td>
                {available ? (
                  <div className="row-actions">
                    <button className="secondary-button compact" type="button" aria-label={`下载：${file.display_name}`} onClick={() => void downloadFile(file)}>下载</button>
                    {versionCanBePreviewed(file.current_version, file.display_name) ? <button className="secondary-button compact" type="button" aria-label={`预览：${file.display_name}`} onClick={() => setPreviewFile(file)}>预览</button> : null}
                    {hasVersion ? <button className="secondary-button compact" type="button" aria-label={`版本：${file.display_name}`} onClick={() => setTimelineFile(file)}>版本</button> : null}
                    {canManage ? <button className="secondary-button compact" type="button" aria-label={`上传新版本：${file.display_name}`} onClick={() => requestNewVersion(file)}>上传新版本</button> : null}
                  </div>
                ) : null}
              </td>
            </tr>
          })}
        </tbody></table></div>
      ))}
      {!uploadOnly && previewFile ? <FilePreview projectId={projectId} file={previewFile} canRegenerate={canManage} onClose={() => setPreviewFile(null)} /> : null}
      <input ref={replaceInputRef} className="file-input-hidden" type="file" aria-label="选择新版本文件" onChange={addNewVersion} />
      {!uploadOnly && timelineFile ? <FileVersionTimeline projectId={projectId} file={timelineFile} canManage={canManage} onChanged={() => void loadFiles({ quiet: true })} onClose={() => setTimelineFile(null)} /> : null}
      {pendingNamedFiles.length > 0 ? (
        <div className="dialog-backdrop" role="presentation">
          <section className="dialog file-naming-dialog" role="dialog" aria-modal="true" aria-labelledby="file-naming-title">
            <div className="dialog-heading">
              <div><h3 id="file-naming-title">填写文件名称</h3><p className="supporting-copy compact-copy">文件名称用于文件库归档，原始文件名会保留在版本记录中。</p></div>
              <button className="secondary-button compact" type="button" onClick={() => { setPendingNamedFiles([]); setNamingError("") }}>取消</button>
            </div>
            <div className="file-naming-list">
              {pendingNamedFiles.map((item, index) => (
                <label className="field" key={item.id}>
                  <span>文件名称</span>
                  <input
                    aria-label={`文件名称：${item.file.name}`}
                    value={item.displayName}
                    maxLength={255}
                    autoFocus={index === 0}
                    onChange={(event) => setPendingNamedFiles((current) => current.map((candidate) => candidate.id === item.id ? { ...candidate, displayName: event.target.value } : candidate))}
                  />
                  <small className="field-hint">原始文件：{item.file.name}</small>
                </label>
              ))}
            </div>
            {namingError ? <p className="form-error" role="alert">{namingError}</p> : null}
            <div className="dialog-actions">
              <button className="secondary-button" type="button" onClick={() => { setPendingNamedFiles([]); setNamingError("") }}>取消</button>
              <button className="primary-button" type="button" onClick={confirmNamedUploads}>开始上传</button>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  )
}

function filesPath(projectId: string, filterCategory?: string): string {
  const base = `/api/v1/projects/${encodeURIComponent(projectId)}/files`
  return filterCategory ? `${base}?business_category=${encodeURIComponent(filterCategory)}` : base
}

function fileNeedsPolling(file: ProjectFileDto): boolean {
  const version = file.current_version
  if (!version) return false
  if (version.status === "uploading" || version.status === "quarantined") return true
  return version.scan_status === "pending" || version.scan_status === "scanning"
}

function categoryLabel(category: ProjectFileDto["category"]): string {
  return { attachment: "附件", document: "文档" }[category]
}

function businessCategoryLabel(category: BusinessCategory): string {
  return BUSINESS_CATEGORY_LABELS[category]
}

function stripQuote(value: string): string {
  return value.startsWith('"') && value.endsWith('"') ? value.slice(1, -1) : value
}

/** The upload inherits the single 业务阶段 filter (未分类/全部 map to uncategorized). */
function categoryFromFilter(filter: string): BusinessCategory | null {
  if (!filter || filter === BUSINESS_CATEGORY_UNCATEGORIZED_LABEL) return null
  return BUSINESS_CATEGORIES.includes(filter as BusinessCategory) ? filter as BusinessCategory : null
}

function fileError(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "project_not_found") return "项目不存在或已被删除。"
  if (error instanceof ApiClientError && error.code === "forbidden") return "你没有权限查看该项目的文件。"
  return "文件列表加载失败，请稍后重试。"
}

function uploadError(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (error.code === "file_type_not_allowed") return "文件类型不受支持。"
    if (error.code === "file_too_large") return "单个文件不能超过 100MB。"
    if (error.code === "file_name_invalid") return "文件名不合法。"
    if (error.code === "invalid_parts") return "分片数据无效。"
    if (error.code === "forbidden") return "当前账号没有上传项目文件的权限。"
    if (error.code === "request_timeout") return "文件服务响应超时，请稍后重试。"
    if (error.code === "network_error") return "无法连接本地文件服务，请确认服务已启动。"
  }
  if (error instanceof TypeError) return "无法连接本地文件存储服务，请完全退出并重新打开最新版后重试。"
  if (error instanceof Error && error.message.startsWith("storage_upload_failed:")) {
    const status = error.message.split(":")[1]
    return `文件存储服务拒绝了上传（HTTP ${status}），请重试。`
  }
  if (error instanceof Error && error.message === "invalid upload session") return "创建上传任务后返回的数据不完整，请重试。"
  if (error instanceof Error && error.message === "invalid signed part") return "获取文件分片上传地址失败，请重试。"
  if (error instanceof Error && error.message === "invalid upload completion") return "文件已上传，但服务器确认结果异常，请刷新文件库查看。"
  return "上传失败，未能识别具体原因，请重新选择文件后再试。"
}
