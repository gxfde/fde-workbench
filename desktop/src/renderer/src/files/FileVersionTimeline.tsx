import { useEffect, useRef, useState, type ChangeEvent } from "react"
import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { useDangerConfirm } from "../common/DangerConfirmProvider"
import { FilePreview } from "./FilePreview"
import { fileTooLarge, versionCanBePreviewed } from "./fileCapabilities"
import { isFileUrlDto, isUploadCompleteDto, isUploadedPartDto, isUploadSessionDto } from "./runtimeValidation"
import type { ProjectFileDto, ProjectFileVersionDto, UploadSessionDto } from "./types"

interface FileVersionTimelineProps {
  projectId: string
  file: ProjectFileDto
  canManage?: boolean
  mode?: "dialog" | "page"
  onClose(): void
  onChanged?(): void
}

/** Version history and per-version actions for one project file. */
export function FileVersionTimeline({ projectId, file, canManage = false, mode = "dialog", onClose, onChanged }: FileVersionTimelineProps) {
  const { apiRequest } = useAuth()
  const dangerConfirm = useDangerConfirm()
  const [entries, setEntries] = useState<ProjectFileVersionDto[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [previewVersion, setPreviewVersion] = useState<ProjectFileVersionDto | null>(null)
  const [uploading, setUploading] = useState(false)
  const uploadInputRef = useRef<HTMLInputElement>(null)

  async function load() {
    setLoading(true)
    try {
      const value = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/files/items/${encodeURIComponent(file.id)}/versions`, { method: "GET" })
      if (!isVersionList(value)) throw new Error("invalid versions")
      setEntries(value.items); setError("")
    } catch { setError("版本历史加载失败，请稍后重试。") }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [file.id, projectId])

  async function deprecate(version: ProjectFileVersionDto) {
    const confirmed = await dangerConfirm({
      title: "弃用文件版本",
      description: `确定弃用“${file.display_name}”v${version.version_number} 吗？该版本将不再作为当前版本，但会保留在历史记录中。`,
      confirmLabel: "弃用",
    })
    if (!confirmed) return
    try {
      await apiRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/files/versions/${encodeURIComponent(version.id)}/deprecate`, { method: "POST", body: { reason: "人工弃用" } })
      await load(); onChanged?.()
    } catch { setError("版本弃用失败，请稍后重试。") }
  }

  async function restore(version: ProjectFileVersionDto) {
    try {
      await apiRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/files/versions/${encodeURIComponent(version.id)}/restore`, { method: "POST" })
      await load(); onChanged?.()
    } catch { setError("版本恢复失败，请稍后重试。") }
  }

  async function download(version: ProjectFileVersionDto) {
    try {
      const result = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(version.id)}/download-url`, { method: "GET" })
      if (!isFileUrlDto(result)) throw new Error("invalid download url")
      const anchor = document.createElement("a")
      anchor.href = result.url
      anchor.download = version.original_filename || file.display_name
      document.body.appendChild(anchor); anchor.click(); anchor.remove()
    } catch (caught) {
      setError(caught instanceof ApiClientError && caught.code === "file_not_available" ? "该版本当前不可下载。" : "版本下载失败，请稍后重试。")
    }
  }

  async function uploadNewVersion(event: ChangeEvent<HTMLInputElement>) {
    const selectedFile = event.target.files?.[0]
    event.target.value = ""
    if (!selectedFile) return
    if (fileTooLarge(selectedFile)) {
      setError(`文件“${selectedFile.name}”超过 100MB，无法上传。`)
      return
    }
    setUploading(true); setError("")
    try {
      const base = `/api/v1/projects/${encodeURIComponent(projectId)}/files`
      const session = await apiRequest<unknown>(base, {
        method: "POST",
        body: {
          name: selectedFile.name,
          display_name: file.display_name,
          file_id: file.id,
          size_bytes: selectedFile.size,
          mime_type: selectedFile.type,
          category: file.category,
          business_category: file.business_category ?? null,
          idempotency_key: crypto.randomUUID(),
        },
      })
      if (!isUploadSessionDto(session)) throw new Error("invalid upload session")
      const parts = await uploadSelectedFile(base, selectedFile, session)
      const completed = await apiRequest<unknown>(`${base}/${encodeURIComponent(session.id)}/complete`, {
        method: "POST", body: { parts },
      })
      if (!isUploadCompleteDto(completed)) throw new Error("invalid upload completion")
      await load(); onChanged?.()
    } catch (caught) {
      setError(caught instanceof ApiClientError ? `新版本上传失败：${caught.message}` : "新版本上传失败，请稍后重试。")
    } finally {
      setUploading(false)
    }
  }

  async function uploadSelectedFile(base: string, selectedFile: File, session: UploadSessionDto) {
    const total = Math.max(1, Math.ceil(selectedFile.size / session.part_size))
    const parts: Array<{ part_number: number; etag: string }> = []
    for (let partNumber = 1; partNumber <= total; partNumber += 1) {
      const signed = await apiRequest<unknown>(`${base}/${encodeURIComponent(session.id)}/parts`, {
        method: "POST", body: { part_number: partNumber },
      })
      if (!isUploadedPartDto(signed)) throw new Error("invalid signed part")
      const start = (partNumber - 1) * session.part_size
      const response = await fetch(signed.url, {
        method: "PUT", body: selectedFile.slice(start, Math.min(selectedFile.size, start + session.part_size)),
      })
      if (!response.ok) throw new Error(`storage_upload_failed:${response.status}`)
      parts.push({ part_number: partNumber, etag: (response.headers.get("etag") ?? "").replace(/^"|"$/g, "") })
    }
    return parts
  }

  const content = (
    <section className={mode === "page" ? "panel file-version-page" : "dialog file-version-dialog"} role={mode === "dialog" ? "dialog" : undefined} aria-modal={mode === "dialog" ? "true" : undefined} aria-label={`版本历史：${file.display_name}`} onClick={mode === "dialog" ? (event) => event.stopPropagation() : undefined}>
      <div className="dialog-heading">
        <div><p className="eyebrow">文件库 / 版本历史</p><h3>版本历史：{file.display_name}</h3></div>
        <div className="row-actions">
          {canManage ? <><input ref={uploadInputRef} className="file-input-hidden" type="file" aria-label="选择新版本文件" disabled={uploading} onChange={(event) => void uploadNewVersion(event)} /><button className="secondary-button compact" type="button" disabled={uploading} onClick={() => uploadInputRef.current?.click()}>{uploading ? "上传中…" : "上传新版本"}</button></> : null}
          <button className="secondary-button compact" type="button" onClick={onClose}>{mode === "page" ? "返回文件库" : "关闭"}</button>
        </div>
      </div>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {loading ? <p role="status">正在加载版本…</p> : entries.length === 0 ? (
        <p className="empty-state">该文件暂无版本。</p>
      ) : (
        <div className="table-scroll version-history-table">
          <table aria-label={`${file.display_name}版本历史`}>
            <thead><tr><th>版本</th><th>状态</th><th>上传者</th><th>上传时间</th><th>原文件</th><th>操作</th></tr></thead>
            <tbody>{entries.map((version) => (
              <tr key={version.id}>
                <td><strong>v{version.version_number}</strong></td>
                <td><span className={`badge ${versionStatusClass(version.status)}`}>{versionStatusLabel(version.status)}</span></td>
                <td>{version.uploaded_by ?? ""}</td>
                <td>{version.uploaded_at ? formatTime(version.uploaded_at) : ""}</td>
                <td className="wrap-cell">{version.original_filename ?? ""}</td>
                <td><div className="row-actions version-history-actions">
                  {versionCanBePreviewed(version, file.display_name) ? <button className="secondary-button compact" type="button" onClick={() => setPreviewVersion(version)}>预览</button> : null}
                  {downloadableStatus(version.status) ? <button className="secondary-button compact" type="button" onClick={() => void download(version)}>下载</button> : null}
                  {canManage && version.status === "available" ? <button className="danger-button compact" type="button" onClick={() => void deprecate(version)}>标记为弃用</button> : null}
                  {canManage && version.status === "deprecated" ? <button className="secondary-button compact" type="button" onClick={() => void restore(version)}>恢复</button> : null}
                </div></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </section>
  )

  return (
    <>
      {mode === "page" ? content : <div className="dialog-backdrop" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) onClose() }}>{content}</div>}
      {previewVersion ? <FilePreview projectId={projectId} file={{ ...file, current_version: previewVersion, current_version_id: previewVersion.id }} canRegenerate={canManage} onClose={() => setPreviewVersion(null)} /> : null}
    </>
  )
}

function downloadableStatus(status: ProjectFileVersionDto["status"]): boolean { return status === "available" || status === "deprecated" }

export function versionStatusLabel(status: ProjectFileVersionDto["status"]): string {
  return { uploading: "上传中", quarantined: "处理中", available: "可下载", deprecated: "已弃用", rejected: "已拒绝", failed: "上传失败" }[status]
}

function isVersionList(value: unknown): value is { items: ProjectFileVersionDto[] } {
  return Boolean(value && typeof value === "object" && Array.isArray((value as { items?: unknown }).items))
}
function formatTime(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false }) }

export function versionStatusClass(status: ProjectFileVersionDto["status"]): string {
  if (status === "available") return "success"
  if (status === "quarantined" || status === "uploading") return "warning"
  return "muted"
}
