import { useEffect, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { isDocumentVersion } from "./runtimeValidation"
import { DocumentPreview } from "./DocumentPreview"
import type { DocumentVersionDto } from "./types"
import { DOCUMENT_SOURCE_LABELS, DOCUMENT_STATUS_LABELS } from "./types"

interface DocumentVersionTimelineProps {
  projectId: string
  documentId: string
  title: string
  mode?: "dialog" | "page"
  onClose(): void
}

export function DocumentVersionTimeline({ projectId, documentId, title, mode = "dialog", onClose }: DocumentVersionTimelineProps) {
  const { apiRequest } = useAuth()
  const [versions, setVersions] = useState<DocumentVersionDto[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [previewVersion, setPreviewVersion] = useState<DocumentVersionDto | null>(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError("")
    void apiRequest<unknown>(versionsPath(projectId, documentId), { method: "GET" })
      .then((next) => {
        if (!active) return
        if (!isRecord(next) || !Array.isArray(next.items) || !next.items.every(isDocumentVersion)) throw new Error("invalid versions")
        setVersions(next.items)
      })
      .catch((caught) => {
        if (active) setError(versionError(caught))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [apiRequest, projectId, documentId])

  async function download(version: DocumentVersionDto): Promise<void> {
    try {
      const next = await apiRequest<unknown>(`${documentsPath(projectId)}/${encodeURIComponent(version.id)}/download-url`, { method: "GET" })
      if (!isRecord(next) || typeof next.url !== "string") throw new Error("invalid download url")
      const anchor = document.createElement("a")
      anchor.href = next.url
      anchor.download = `${title}-v${version.version_number}.docx`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
    } catch (caught) {
      setError(versionError(caught))
    }
  }

  const content = (
    <section className={mode === "page" ? "panel file-version-page" : "dialog file-version-dialog"} role={mode === "dialog" ? "dialog" : undefined} aria-modal={mode === "dialog" ? "true" : undefined} aria-label={`版本历史：${title}`} onClick={mode === "dialog" ? (event) => event.stopPropagation() : undefined}>
      <div className="dialog-heading">
        <div><p className="eyebrow">文件库 / 版本历史</p><h3>版本历史：{title}</h3></div>
        <button className="secondary-button compact" type="button" onClick={onClose}>{mode === "page" ? "返回文件库" : "关闭"}</button>
      </div>
      {loading ? <p role="status">正在加载版本历史…</p> : error ? <p className="form-error" role="alert">{error}</p> : versions.length === 0 ? (
        <p className="empty-state">该文档暂无版本。</p>
      ) : (
        <div className="table-scroll version-history-table">
          <table aria-label={`${title}版本历史`}>
            <thead><tr><th>版本</th><th>状态</th><th>来源</th><th>确认人</th><th>确认时间</th><th>校验值</th><th>操作</th></tr></thead>
            <tbody>{versions.map((version) => (
              <tr key={version.id}>
                <td><strong>v{version.version_number}</strong></td>
                <td><span className={`badge ${statusClass(version.status)}`}>{DOCUMENT_STATUS_LABELS[version.status]}</span></td>
                <td>{DOCUMENT_SOURCE_LABELS[version.source]}</td>
                <td>{version.confirmed_by?.display_name ?? ""}</td>
                <td>{version.confirmed_at ? formatTime(version.confirmed_at) : ""}</td>
                <td>{shortSha256(version.sha256)}</td>
                <td><div className="row-actions version-history-actions">
                  {versionCanPreview(version) ? <button className="secondary-button compact" type="button" aria-label={`预览：${title} v${version.version_number}`} onClick={() => setPreviewVersion(version)}>预览</button> : null}
                  {versionCanDownload(version) ? <button className="secondary-button compact" type="button" aria-label={`下载：${title} v${version.version_number}`} onClick={() => void download(version)}>下载</button> : null}
                </div></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      <p className="field-hint">版本列表按时间倒序，最新版本展示在最前。</p>
    </section>
  )

  return (
    <>
      {mode === "page" ? content : <div className="dialog-backdrop" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) onClose() }}>{content}</div>}
      {previewVersion ? <DocumentPreview projectId={projectId} title={`${title} v${previewVersion.version_number}`} versionId={previewVersion.id} onClose={() => setPreviewVersion(null)} /> : null}
    </>
  )
}

export function versionCanDownload(version: { status: DocumentVersionDto["status"]; docx_file_version_id?: string | null }): boolean {
  return Boolean(version.docx_file_version_id) || version.status === "confirmed" || version.status === "archived"
}

export function versionCanPreview(version: { status: DocumentVersionDto["status"]; preview_status?: DocumentVersionDto["preview_status"] }): boolean {
  return version.preview_status === "ready"
}

export function statusClass(status: DocumentVersionDto["status"]): string {
  if (status === "confirmed") return "success"
  if (status === "draft") return "warning"
  return "muted"
}

function shortSha256(sha256?: string): string {
  if (!sha256) return "—"
  return sha256.length > 12 ? `${sha256.slice(0, 12)}…` : sha256
}

function formatTime(value: string): string {
  try {
    return new Date(value).toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
  } catch {
    return value
  }
}

function versionsPath(projectId: string, documentId: string): string {
  return `${documentsPath(projectId)}/${encodeURIComponent(documentId)}/versions`
}

function documentsPath(projectId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/documents`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function versionError(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "forbidden") return "你没有权限查看该文档的版本。"
  if (error instanceof ApiClientError && error.code === "document_not_found") return "该文档不存在或已被删除。"
  return "版本历史加载失败，请稍后重试。"
}
