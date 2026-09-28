import { useEffect, useRef, useState, type MouseEvent } from "react"
import { renderAsync } from "docx-preview"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { decodeTextPreview, filePreviewKind } from "./fileCapabilities"
import { isFileUrlDto } from "./runtimeValidation"
import type { FileUrlDto, ProjectFileDto } from "./types"

interface FilePreviewProps {
  projectId: string
  file: ProjectFileDto
  canRegenerate?: boolean
  onClose(): void
}

export function FilePreview({ projectId, file, canRegenerate = false, onClose }: FilePreviewProps) {
  const { apiRequest } = useAuth()
  const [url, setUrl] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [notReady, setNotReady] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [regenerating, setRegenerating] = useState(false)
  const [regenerationQueued, setRegenerationQueued] = useState(false)
  const [docxData, setDocxData] = useState<ArrayBuffer | null>(null)
  const [textContent, setTextContent] = useState("")
  const docxContainerRef = useRef<HTMLDivElement | null>(null)
  const versionId = file.current_version_id ?? file.current_version?.id ?? ""
  const versionFilename = file.current_version?.original_filename || file.display_name
  const previewKind = filePreviewKind(versionFilename)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError("")
    setNotReady(false)
    setUrl("")
    setDocxData(null)
    setTextContent("")
    if (!versionId) {
      if (active) { setError("该文件没有可预览的版本。"); setLoading(false) }
      return
    }
    const usesConvertedPreview = previewKind === "converted-pdf"
    void apiRequest<FileUrlDto>(usesConvertedPreview ? previewUrlPath(projectId, versionId) : downloadUrlPath(projectId, versionId), { method: "GET" })
      .then(async (next) => {
        if (!active) return
        if (!isFileUrlDto(next)) throw new Error("invalid preview url")
        const response = await fetch(next.url)
        if (!response.ok) throw new Error("preview download failed")
        if (previewKind === "docx") {
          const data = await response.arrayBuffer()
          if (active) setDocxData(data)
        } else if (previewKind === "text") {
          const data = await response.arrayBuffer()
          if (active) setTextContent(decodeTextPreview(data, versionFilename))
        } else {
          const blob = await response.blob()
          if (active) setUrl(URL.createObjectURL(blob))
        }
      })
      .catch((caught) => {
        if (active && caught instanceof ApiClientError && caught.code === "preview_not_available") setNotReady(true)
        if (active) setError(previewError(caught))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [apiRequest, previewKind, projectId, versionFilename, versionId])

  useEffect(() => () => {
    if (url.startsWith("blob:")) URL.revokeObjectURL(url)
  }, [url])

  useEffect(() => {
    const container = docxContainerRef.current
    if (!docxData || !container) return
    container.replaceChildren()
    void renderAsync(docxData, container, undefined, {
      breakPages: true,
      ignoreHeight: false,
      ignoreWidth: false,
      renderHeaders: true,
      renderFooters: true,
      useBase64URL: true,
    }).catch(() => setError("DOCX 预览解析失败，请下载原文件查看。"))
  }, [docxData, loading])

  async function downloadOriginal(): Promise<void> {
    if (!versionId || downloading) return
    setDownloading(true)
    try {
      const next = await apiRequest<FileUrlDto>(downloadUrlPath(projectId, versionId), { method: "GET" })
      if (!isFileUrlDto(next)) throw new Error("invalid download url")
      const anchor = document.createElement("a")
      anchor.href = next.url
      anchor.download = versionFilename
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
    } catch (caught) {
      setError(previewError(caught))
    } finally {
      setDownloading(false)
    }
  }

  async function regeneratePreview(): Promise<void> {
    if (!versionId || regenerating) return
    setRegenerating(true)
    setRegenerationQueued(false)
    try {
      await apiRequest(previewRegenerationPath(projectId, versionId), { method: "POST" })
      setError("")
      setRegenerationQueued(true)
    } catch (caught) {
      setError(regenerationError(caught))
    } finally {
      setRegenerating(false)
    }
  }

  const handleBackdrop = (event: MouseEvent<HTMLDivElement>): void => {
    if (event.target === event.currentTarget) onClose()
  }

  return (
    <div className="dialog-backdrop" role="presentation" onClick={handleBackdrop}>
      <div className="dialog file-preview-dialog" role="dialog" aria-modal="true" aria-label={`预览：${file.display_name}`} onClick={(event) => event.stopPropagation()}>
        <div className="dialog-heading">
          <h3>预览：{file.display_name}</h3>
          <div className="row-actions">
            <button className="secondary-button compact" type="button" disabled={downloading || !versionId} onClick={() => void downloadOriginal()}>{downloading ? "下载中…" : "下载"}</button>
            <button className="secondary-button compact" type="button" onClick={onClose}>关闭</button>
          </div>
        </div>
        {loading ? <p role="status">正在加载预览…</p> : notReady ? (
          <div className="preview-unavailable" data-testid="preview-unavailable">
            <p className="form-error" role="alert">预览生成失败，原文件可下载。</p>
            {regenerationQueued ? <p className="notice" role="status">已提交重新生成。稍后关闭并重新打开预览即可查看结果。</p> : null}
            <div className="row-actions">
              <button className="secondary-button" type="button" disabled={downloading} onClick={() => void downloadOriginal()}>{downloading ? "下载中…" : `下载 ${downloadExtension(file.display_name)}`}</button>
              {canRegenerate ? <button className="primary-button" type="button" disabled={regenerating || regenerationQueued} onClick={() => void regeneratePreview()}>{regenerating ? "正在提交…" : regenerationQueued ? "已提交" : "重新生成预览"}</button> : null}
            </div>
          </div>
        ) : error ? <p className="form-error" role="alert">{error}</p> : previewKind === "docx" && docxData ? (
          <div className="docx-preview-host" ref={docxContainerRef} aria-label={`DOCX 预览：${file.display_name}`} />
        ) : previewKind === "text" ? (
          <pre className="text-file-preview" aria-label={`文本预览：${file.display_name}`}>{textContent}</pre>
        ) : previewKind === "image" && url ? (
          <div className="image-file-preview"><img src={url} alt={`${file.display_name} 预览`} /></div>
        ) : url ? (
          <iframe className="file-preview-frame" title={`预览：${file.display_name}`} src={url} />
        ) : null}
      </div>
    </div>
  )
}

function previewUrlPath(projectId: string, versionId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(versionId)}/preview-url`
}

function downloadUrlPath(projectId: string, versionId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(versionId)}/download-url`
}

function previewRegenerationPath(projectId: string, versionId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(versionId)}/preview`
}

function downloadExtension(displayName: string): string {
  const extension = displayName.split(".").pop()
  return extension && extension !== displayName ? extension.toUpperCase() : "原文件"
}

function previewError(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "forbidden") return "你没有权限预览该文件。"
  if (error instanceof ApiClientError && error.code === "file_not_found") return "该文件不存在或已被删除。"
  if (error instanceof ApiClientError && error.code === "preview_not_available") return "预览尚未就绪，原文件可下载。"
  return "预览地址获取失败，请稍后重试。"
}


function regenerationError(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "forbidden") return "你没有权限重新生成该文件的预览。"
  if (error instanceof ApiClientError && error.code === "file_not_previewable") return "该版本当前不能生成预览，请确认文件已启用并通过安全检查。"
  if (error instanceof ApiClientError && error.code === "file_type_not_previewable") return "该文件类型暂不支持生成预览。"
  return "重新生成预览提交失败，请稍后重试。"
}
