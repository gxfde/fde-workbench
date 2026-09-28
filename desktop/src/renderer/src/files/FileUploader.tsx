import { useRef, type ChangeEvent, type ReactNode } from "react"

import type { UploadItem, UploadItemStatus } from "./types"

interface FileUploaderProps {
  /** Whether the current user may start uploads. */
  canUpload: boolean
  /** The user picked one or more files from the local disk. The upload category
   * comes from the project file filter, so no separate selector is rendered here. */
  onFilesSelected(files: File[]): void
  /** In-flight / queued upload items shown with per-file progress. */
  items: UploadItem[]
  /** Abort an in-progress upload (or drop a queued one). */
  onCancel(id: string): void
  /** Retry a failed upload, reusing its idempotency key. */
  onRetry(id: string): void
  /** Controls that belong on the same toolbar as the upload action. */
  toolbarExtra?: ReactNode
  /** Whether the extra controls appear before or after the upload action. */
  toolbarExtraPosition?: "before" | "after"
}

export function FileUploader({ canUpload, onFilesSelected, items, onCancel, onRetry, toolbarExtra, toolbarExtraPosition = "after" }: FileUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  function handleChange(event: ChangeEvent<HTMLInputElement>): void {
    const files = Array.from(event.target.files ?? [])
    if (files.length === 0) return
    onFilesSelected(files)
    // Reset the input so re-selecting the same file still fires onChange.
    event.target.value = ""
  }

  return (
    <div className="file-uploader">
      <div className="file-uploader-toolbar" role="toolbar" aria-label="文件工具栏">
        <input
          ref={inputRef}
          className="file-input-hidden"
          type="file"
          multiple
          aria-label="选择文件"
          disabled={!canUpload}
          onChange={handleChange}
        />
        {toolbarExtraPosition === "before" ? toolbarExtra : null}
        <button
          className="primary-button"
          type="button"
          disabled={!canUpload}
          onClick={() => inputRef.current?.click()}
        >
          上传文件
        </button>
        <span className="file-uploader-hint">{items.length > 0 ? `${items.length} 个待处理` : "支持选择多个文件"}</span>
        {toolbarExtraPosition === "after" ? toolbarExtra : null}
      </div>
      {items.length > 0 ? <ul className="upload-item-list" aria-label="上传队列">{items.map((item) => (
        <li key={item.id} className={`upload-item ${item.status}`}>
          <div className="upload-item-main">
            <strong className="upload-item-name">{item.name}</strong>
            <span className="upload-item-meta">{uploadStatusLabel(item.status)}{item.sizeBytes > 0 ? ` · ${formatBytes(item.sizeBytes)}` : ""}</span>
            {item.status === "uploading" || item.status === "pending" || item.status === "failed" ? (
              <progress className="upload-progress" value={item.progress} max={100} aria-label={`${item.name} 上传进度`}>{item.progress}%</progress>
            ) : null}
            {item.error ? <small className="form-error upload-item-error" role="alert">{item.error}</small> : null}
          </div>
          <div className="upload-item-actions">
            {item.status === "pending" || item.status === "uploading" ? (
              <button className="secondary-button compact" type="button" onClick={() => onCancel(item.id)}>取消</button>
            ) : null}
            {item.status === "failed" ? (
              <button className="secondary-button compact" type="button" onClick={() => onRetry(item.id)}>重试</button>
            ) : null}
            {item.status === "completed" ? <span className="badge success">已完成</span> : null}
            {item.status === "cancelled" ? <span className="badge muted">已取消</span> : null}
          </div>
        </li>
      ))}</ul> : null}
    </div>
  )
}

export function uploadStatusLabel(status: UploadItemStatus): string {
  return { pending: "等待中", uploading: "上传中", completed: "已完成", failed: "上传失败", cancelled: "已取消" }[status]
}

function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}
