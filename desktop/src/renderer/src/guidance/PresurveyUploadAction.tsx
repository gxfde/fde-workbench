import { useRef, useState, type ChangeEvent } from "react"
import { useAuth } from "../auth/AuthProvider"
import { isProjectFileListDto, isUploadCompleteDto, isUploadedPartDto, isUploadSessionDto } from "../files/runtimeValidation"
import type { UploadSessionDto } from "../files/types"
import { PresurveyAnalysisAction } from "./PresurveyAnalysisAction"
import type { GuidanceAnalysisDto } from "./types"

export function PresurveyUploadAction({ projectId, hasGuidance, onConfirmed }: { projectId: string; hasGuidance: boolean; onConfirmed(value: GuidanceAnalysisDto): void }) {
  const { apiRequest } = useAuth(); const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [versionId, setVersionId] = useState<string | null>(null)
  async function selected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]; event.target.value = ""
    if (!file) return
    if (!file.name.toLowerCase().endsWith(".docx")) { setError("预调研表必须是 DOCX 文件。"); return }
    setBusy(true); setError(""); setVersionId(null)
    try {
      const existing = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/files?business_category=${encodeURIComponent("预调研")}`, { method: "GET" })
      const existingFileId = isProjectFileListDto(existing)
        ? existing.items.find((item) => item.display_name === "预调研表")?.id
        : undefined
      const session = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/files`, { method: "POST", body: { name: file.name, display_name: "预调研表", file_id: existingFileId, size_bytes: file.size, mime_type: file.type, category: "document", business_category: "预调研", idempotency_key: crypto.randomUUID() } })
      if (!isUploadSessionDto(session)) throw new Error("invalid upload")
      const parts = await uploadParts(file, session)
      const complete = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(session.id)}/complete`, { method: "POST", body: { parts } })
      if (!isUploadCompleteDto(complete)) throw new Error("invalid complete")
      const availableVersion = await waitUntilAvailable(complete.file_id)
      setVersionId(availableVersion)
    } catch { setError("预调研表上传或安全检查失败，请稍后重试。") }
    finally { setBusy(false) }
  }
  async function uploadParts(file: File, session: UploadSessionDto) {
    const total = Math.max(1, Math.ceil(file.size / session.part_size)); const parts: Array<{ part_number: number; etag: string }> = []
    for (let number = 1; number <= total; number += 1) {
      const signed = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(session.id)}/parts`, { method: "POST", body: { part_number: number } })
      if (!isUploadedPartDto(signed)) throw new Error("invalid part")
      const start = (number - 1) * session.part_size; const response = await fetch(signed.url, { method: "PUT", body: file.slice(start, Math.min(file.size, start + session.part_size)) })
      if (!response.ok) throw new Error("upload failed")
      const raw = response.headers.get("etag") ?? ""; parts.push({ part_number: number, etag: raw.startsWith('"') ? raw.slice(1, -1) : raw })
    }
    return parts
  }
  async function waitUntilAvailable(fileId: string | null): Promise<string> {
    for (let attempt = 0; attempt < 30; attempt += 1) {
      const value = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/files?business_category=${encodeURIComponent("预调研")}`, { method: "GET" })
      if (isProjectFileListDto(value)) {
        const file = value.items.find((item) => item.id === fileId)
        if (file?.current_version?.status === "available") return file.current_version.id
        if (file?.current_version?.status === "failed" || file?.current_version?.status === "rejected") throw new Error("scan failed")
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1000))
    }
    throw new Error("scan timeout")
  }
  return <div className="guidance-upload-actions"><input ref={inputRef} className="file-input-hidden" type="file" accept=".docx" aria-label="选择预调研表" onChange={(event) => void selected(event)} /><button className="secondary-button compact" type="button" disabled={busy} onClick={() => inputRef.current?.click()}>{busy ? "正在上传并检查…" : hasGuidance ? "上传新版本" : "上传预调研表"}</button>{versionId ? <PresurveyAnalysisAction projectId={projectId} fileVersionId={versionId} canManage autoStart onConfirmed={onConfirmed} /> : null}{error ? <span className="inline-error">{error}</span> : null}</div>
}
