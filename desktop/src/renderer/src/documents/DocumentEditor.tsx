import { useCallback, useEffect, useState, type MouseEvent } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { isDocumentDetail, isDocumentDraft } from "./runtimeValidation"
import type { DocumentDetailDto } from "./types"
import { DOCUMENT_TYPE_LABELS } from "./types"

interface DocumentEditorProps {
  projectId: string
  documentId: string
  onClose(): void
  onUpdated(): void
}

export function DocumentEditor({ projectId, documentId, onClose, onUpdated }: DocumentEditorProps) {
  const { apiRequest } = useAuth()
  const [detail, setDetail] = useState<DocumentDetailDto | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [fieldOverrides, setFieldOverrides] = useState<Record<string, string>>({})
  const [richText, setRichText] = useState("")
  const [draftVersion, setDraftVersion] = useState(1)
  const [documentVersion, setDocumentVersion] = useState(1)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState("")
  const [saved, setSaved] = useState(false)
  const [staleConflict, setStaleConflict] = useState(false)

  const loadDetail = useCallback(async (): Promise<void> => {
    setLoading(true)
    setError("")
    try {
      const next = await apiRequest<unknown>(detailPath(projectId, documentId), { method: "GET" })
      if (!isDocumentDetail(next)) throw new Error("invalid document detail")
      setDetail(next)
      setDocumentVersion(next.version)
      const draft = next.draft
      if (draft) {
        setDraftVersion(draft.version)
        setFieldOverrides(recordToStrings(draft.field_overrides))
        setRichText(richTextToPlain(draft.rich_text))
      }
    } catch (caught) {
      setError(detailError(caught))
    } finally {
      setLoading(false)
    }
  }, [apiRequest, projectId, documentId])

  useEffect(() => {
    void loadDetail()
  }, [loadDetail])

  async function handleSave(): Promise<void> {
    setSaving(true)
    setSaveError("")
    setSaved(false)
    setStaleConflict(false)
    try {
      const patched = await apiRequest<unknown>(draftPath(projectId, documentId), {
        method: "PATCH",
        body: {
          version: draftVersion,
          field_overrides: fieldOverrides,
          rich_text: plainToRichText(richText),
          list_selections: detail?.draft?.list_selections ?? {},
        },
      })
      if (!isDocumentDraft(patched)) throw new Error("invalid draft patch")
      setDraftVersion(patched.version)
      // Generate against the document's own version counter (unchanged by the patch).
      await apiRequest<unknown>(generatePath(projectId, documentId), { method: "POST", body: { version: documentVersion } })
      setDocumentVersion((current) => current + 1)
      setSaved(true)
      onUpdated()
    } catch (caught) {
      if (caught instanceof ApiClientError && caught.code === "stale_version") {
        setStaleConflict(true)
      } else {
        setSaveError(saveErrorText(caught))
      }
    } finally {
      setSaving(false)
    }
  }

  async function handleRefresh(): Promise<void> {
    setStaleConflict(false)
    setSaveError("")
    // Reload the optimistic-lock base but keep the user's local edits visible.
    try {
      const next = await apiRequest<unknown>(detailPath(projectId, documentId), { method: "GET" })
      if (!isDocumentDetail(next)) throw new Error("invalid document detail")
      setDetail(next)
      setDocumentVersion(next.version)
      if (next.draft) setDraftVersion(next.draft.version)
    } catch (caught) {
      setSaveError(saveErrorText(caught))
    }
  }

  const handleBackdrop = (event: MouseEvent<HTMLDivElement>): void => {
    if (event.target === event.currentTarget) onClose()
  }

  return (
    <div className="dialog-backdrop" role="presentation" onClick={handleBackdrop}>
      <div className="dialog document-editor-dialog" role="dialog" aria-modal="true" aria-label={`编辑：${detail?.business_code ?? documentId}`} onClick={(event) => event.stopPropagation()}>
        <div className="dialog-heading">
          <h3>{detail ? `编辑文档：${detail.business_code}` : "编辑文档"}</h3>
          <button className="secondary-button compact" type="button" onClick={onClose}>关闭</button>
        </div>
        {loading ? <p role="status">正在加载文档草稿…</p> : error ? <p className="form-error" role="alert">{error}</p> : detail ? (
          <div className="document-editor-body">
            {detail.draft === null ? (
              <p className="field-hint">该文档没有可编辑的草稿内容。</p>
            ) : (
              <>
                <p className="document-editor-meta">类型：{DOCUMENT_TYPE_LABELS[detail.document_type]} · 文档版本：{documentVersion}</p>
                {staleConflict ? (
                  <div className="notice document-editor-conflict" role="alert">
                    <p>该文档草稿已在别处更新，请刷新或合并后重试。</p>
                    <button className="secondary-button compact" type="button" onClick={() => void handleRefresh()}>刷新草稿</button>
                  </div>
                ) : null}
                {saved ? <p className="notice">保存成功，已提交重新生成。</p> : null}
                {saveError ? <p className="form-error banner" role="alert">{saveError}</p> : null}
                {Object.keys(fieldOverrides).length > 0 ? (
                  <fieldset className="document-editor-fields">
                    <legend>结构化字段</legend>
                    {Object.entries(fieldOverrides).map(([key, value]) => (
                      <label key={key} className="field">
                        <span>{key}</span>
                        <input
                          value={value}
                          onChange={(event) => setFieldOverrides((current) => ({ ...current, [key]: event.target.value }))}
                          aria-label={`字段：${key}`}
                        />
                      </label>
                    ))}
                  </fieldset>
                ) : (
                  <p className="field-hint">该文档暂无结构化字段。</p>
                )}
                <label className="field">
                  <span>正文（富文本）</span>
                  <textarea
                    className="document-rich-text"
                    value={richText}
                    onChange={(event) => setRichText(event.target.value)}
                    aria-label="富文本正文"
                  />
                </label>
                <div className="dialog-actions">
                  <button className="secondary-button" type="button" onClick={onClose}>取消</button>
                  <button className="primary-button" type="button" disabled={saving} onClick={() => void handleSave()}>
                    {saving ? "保存中…" : "保存并重新生成"}
                  </button>
                </div>
              </>
            )}
          </div>
        ) : null}
      </div>
    </div>
  )
}

function recordToStrings(record: Record<string, unknown>): Record<string, string> {
  const result: Record<string, string> = {}
  for (const [key, value] of Object.entries(record)) {
    result[key] = typeof value === "string" ? value : value === null ? "" : JSON.stringify(value)
  }
  return result
}

/** Extract a plain-text preview from a `{type:"doc",content:[{type:"paragraph",text}]}` doc. */
function richTextToPlain(value: unknown): string {
  if (typeof value === "string") return value
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    const content = (value as Record<string, unknown>).content
    if (Array.isArray(content)) {
      return content
        .filter((item) => typeof item === "object" && item !== null && typeof (item as Record<string, unknown>).text === "string")
        .map((item) => (item as Record<string, unknown>).text as string)
        .join("\n")
    }
  }
  return ""
}

/** Rebuild the canonical rich-text doc JSON from plain lines. */
function plainToRichText(text: string): unknown {
  const content = text.split("\n").map((line) => ({ type: "paragraph", text: line }))
  return { type: "doc", content }
}

function detailPath(projectId: string, documentId: string): string {
  return `${documentsPath(projectId)}/${encodeURIComponent(documentId)}`
}

function draftPath(projectId: string, documentId: string): string {
  return `${detailPath(projectId, documentId)}/draft`
}

function generatePath(projectId: string, documentId: string): string {
  return `${detailPath(projectId, documentId)}/generate`
}

function documentsPath(projectId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/documents`
}

function detailError(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "forbidden") return "你没有权限编辑该文档。"
  if (error instanceof ApiClientError && error.code === "document_not_found") return "该文档不存在或已被删除。"
  return "文档草稿加载失败，请稍后重试。"
}

function saveErrorText(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "invalid_rich_text") return "正文内容格式无效。"
  if (error instanceof ApiClientError && error.code === "invalid_document_state") return "该文档当前状态不允许生成。"
  if (error instanceof ApiClientError && error.code === "forbidden") return "你没有权限编辑该文档。"
  return "保存失败，请稍后重试。"
}
