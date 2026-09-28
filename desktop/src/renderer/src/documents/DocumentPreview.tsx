import { useEffect, useState, type MouseEvent } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { isDocumentUrl } from "./runtimeValidation"
import type { DocumentUrlDto } from "./types"

interface DocumentPreviewProps {
  projectId: string
  title: string
  versionId: string
  onClose(): void
}

export function DocumentPreview({ projectId, title, versionId, onClose }: DocumentPreviewProps) {
  const { apiRequest } = useAuth()
  const [url, setUrl] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [downloading, setDownloading] = useState(false)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError("")
    if (!versionId) {
      if (active) { setError("该文档版本没有可预览的内容。"); setLoading(false) }
      return
    }
    setUrl("")
    void apiRequest<unknown>(previewUrlPath(projectId, versionId), { method: "GET" })
      .then(async (next) => {
        if (!active) return
        if (!isDocumentUrl(next)) throw new Error("invalid preview url")
        const response = await fetch(next.url)
        if (!response.ok) throw new Error("preview download failed")
        const blob = await response.blob()
        if (active) setUrl(URL.createObjectURL(blob))
      })
      .catch((caught) => {
        if (active) setError(previewError(caught))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [apiRequest, projectId, versionId])

  useEffect(() => () => {
    if (url.startsWith("blob:")) URL.revokeObjectURL(url)
  }, [url])

  const handleBackdrop = (event: MouseEvent<HTMLDivElement>): void => {
    if (event.target === event.currentTarget) onClose()
  }

  async function download(): Promise<void> {
    if (downloading) return
    setDownloading(true)
    try {
      const next = await apiRequest<unknown>(downloadUrlPath(projectId, versionId), { method: "GET" })
      if (!isDocumentUrl(next)) throw new Error("invalid download url")
      const anchor = document.createElement("a")
      anchor.href = next.url
      anchor.download = `${title}.docx`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
    } catch (caught) {
      setError(previewError(caught))
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation" onClick={handleBackdrop}>
      <div className="dialog file-preview-dialog" role="dialog" aria-modal="true" aria-label={`预览：${title}`} onClick={(event) => event.stopPropagation()}>
        <div className="dialog-heading">
          <h3>预览：{title}</h3>
          <div className="row-actions">
            <button className="secondary-button compact" type="button" disabled={downloading || !versionId} onClick={() => void download()}>{downloading ? "下载中…" : "下载"}</button>
            <button className="secondary-button compact" type="button" onClick={onClose}>关闭</button>
          </div>
        </div>
        {loading ? <p role="status">正在加载预览…</p> : error ? <p className="form-error" role="alert">{error}</p> : url ? (
          <iframe className="file-preview-frame" title={`预览：${title}`} src={url} />
        ) : null}
      </div>
    </div>
  )
}

function previewUrlPath(projectId: string, versionId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(versionId)}/preview-url`
}

function downloadUrlPath(projectId: string, versionId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(versionId)}/download-url`
}

function previewError(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "forbidden") return "你没有权限预览该文档。"
  if (error instanceof ApiClientError && error.code === "document_not_found") return "该文档不存在或已被删除。"
  if (error instanceof ApiClientError && error.code === "preview_not_available") return "该版本的预览尚未就绪。"
  return "预览地址获取失败，请稍后重试。"
}
