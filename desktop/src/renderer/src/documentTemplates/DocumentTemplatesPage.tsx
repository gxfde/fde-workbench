import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { useDangerConfirm } from "../common/DangerConfirmProvider"

type TemplateType = "research_result" | "project_plan_progress" | "pov_plan" | "sow"
type VersionStatus = "draft" | "published" | "inactive"

interface TemplateVersionDto {
  id: string
  version_number: number
  status: VersionStatus
  created_at: string | null
  docx_original_filename: string | null
}

interface DocumentTemplateDto {
  document_type: string
  latest_published_version_number: number | null
  versions: TemplateVersionDto[]
}

const TEMPLATE_TYPES: Array<{ type: TemplateType; name: string; description: string; hint: string }> = [
  { type: "research_result", name: "调研结果", description: "把单份调研表答案与 AI 总结生成 DOCX。", hint: "动态内容位置请保留：【待插入：调研内容】" },
  { type: "project_plan_progress", name: "项目计划及进度", description: "汇总项目资料、项目指引、任务甘特图和任务清单。", hint: "请保留四个【待插入：…】动态内容标记。" },
  { type: "pov_plan", name: "PoV 验证方案", description: "从 AI 机会生成 PoV 文档并进入项目文件库。", hint: "可使用【待填写：现状描述】等占位符。" },
  { type: "sow", name: "SOW 工作说明书", description: "从 AI 机会生成 SOW 文档并进入项目文件库。", hint: "可使用【待填写：项目名称】等占位符。" },
]

export function DocumentTemplatesPage() {
  const { apiRequest } = useAuth()
  const dangerConfirm = useDangerConfirm()
  const inputRef = useRef<HTMLInputElement>(null)
  const uploadTypeRef = useRef<TemplateType | null>(null)
  const [templates, setTemplates] = useState<DocumentTemplateDto[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState("")
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await apiRequest<unknown>("/api/v1/document-templates", { method: "GET" })
      if (!isTemplateList(result)) throw new Error("invalid document template list")
      setTemplates(result.items)
      setError("")
    } catch (caught) {
      setError(actionError(caught))
    } finally {
      setLoading(false)
    }
  }, [apiRequest])

  useEffect(() => { void load() }, [load])

  function chooseFile(type: TemplateType): void {
    uploadTypeRef.current = type
    inputRef.current?.click()
  }

  async function upload(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = event.target.files?.[0]
    const type = uploadTypeRef.current
    event.target.value = ""
    if (!file || !type) return
    if (!file.name.toLowerCase().endsWith(".docx")) { setError("模板只支持 DOCX 文件。"); return }
    if (file.size > 10 * 1024 * 1024) { setError("模板文件不能超过 10MB。"); return }
    setBusy(`upload:${type}`); setError(""); setNotice("")
    try {
      const bytes = new Uint8Array(await file.arrayBuffer())
      await apiRequest(`/api/v1/document-templates/${type}/versions`, {
        method: "POST",
        body: { kind: "multipart_file", fields: {}, file: { field_name: "file", name: file.name, type: file.type || "application/vnd.openxmlformats-officedocument.wordprocessingml.document", bytes } },
      })
      setNotice(`${templateName(type)}已上传为新草稿，请测试后发布。`)
      await load()
    } catch (caught) { setError(actionError(caught)) } finally { setBusy("") }
  }

  async function runAction(version: TemplateVersionDto, action: "test" | "publish"): Promise<void> {
    setBusy(`${action}:${version.id}`); setError(""); setNotice("")
    try {
      await apiRequest(`/api/v1/document-templates/${version.id}/${action}`, { method: "POST", body: {}, retryAfterAuthRefresh: true })
      setNotice(action === "test" ? `v${version.version_number} 测试通过，可以发布。` : `v${version.version_number} 已发布，后续生成将使用该版本。`)
      await load()
    } catch (caught) { setError(actionError(caught)) } finally { setBusy("") }
  }

  async function deactivate(version: TemplateVersionDto): Promise<void> {
    const confirmed = await dangerConfirm({ title: "停用模板版本", description: `确定停用 v${version.version_number} 吗？历史版本仍会保留。`, confirmLabel: "停用" })
    if (!confirmed) return
    setBusy(`deactivate:${version.id}`); setError("")
    try {
      await apiRequest(`/api/v1/document-templates/${version.id}/deactivate`, { method: "POST", body: {}, retryAfterAuthRefresh: true })
      setNotice(`v${version.version_number} 已停用。`); await load()
    } catch (caught) { setError(actionError(caught)) } finally { setBusy("") }
  }

  async function download(version: TemplateVersionDto): Promise<void> {
    setBusy(`download:${version.id}`); setError("")
    try {
      const result = await apiRequest<unknown>(`/api/v1/document-templates/${version.id}/download-url`, { method: "GET" })
      if (!isDownloadUrl(result)) throw new Error("invalid download url")
      const response = await fetch(result.url)
      if (!response.ok || /json|text\/html/i.test(response.headers.get('content-type') || '')) {
        setError('模板下载失败，请稍后重试或联系管理员检查模板文件。未保存错误文件。')
        return
      }
      const blob = await response.blob()
      const signature = new Uint8Array(await blob.slice(0, 4).arrayBuffer())
      if (signature.length !== 4 || signature[0] !== 0x50 || signature[1] !== 0x4b || signature[2] !== 3 || signature[3] !== 4) {
        setError('模板文件格式异常，无法作为 DOCX 下载。请联系管理员检查模板。')
        return
      }
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = version.docx_original_filename || `document-template-v${version.version_number}.docx`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (caught) { setError(actionError(caught)) } finally { setBusy("") }
  }

  return (
    <div className="page-stack document-template-page">
      <header className="page-header"><div><p className="eyebrow">系统管理</p><h1>文档模板</h1><p className="supporting-copy">集中管理调研结果、项目计划及进度、PoV 和 SOW 的全局 DOCX 模板。上传新版本不会覆盖历史版本，发布后才用于后续生成。</p></div></header>
      <input ref={inputRef} className="file-input-hidden" type="file" accept=".docx" onChange={(event) => { void upload(event) }} />
      {notice ? <p className="notice" role="status">{notice}</p> : null}
      {error ? <p className="form-error banner" role="alert">{error}</p> : null}
      {loading ? <p className="empty-state">正在加载文档模板…</p> : <div className="document-template-grid">
        {TEMPLATE_TYPES.map((definition) => {
          const template = templates.find((item) => item.document_type === definition.type)
          const versions = template?.versions ?? []
          return <section className="panel document-template-card" key={definition.type}>
            <div className="panel-heading"><div><h2>{definition.name}</h2><p>{definition.description}</p></div><button className="primary-button compact" type="button" disabled={Boolean(busy)} onClick={() => chooseFile(definition.type)}>{busy === `upload:${definition.type}` ? "上传中…" : versions.length ? "上传新版本" : "上传模板"}</button></div>
            <p className="template-placeholder-hint">{definition.hint}</p>
            <div className="document-template-version-list">
              {versions.length === 0 ? <p className="empty-state">尚未上传模板。上传后将保存为草稿。</p> : versions.map((version) => <article className="document-template-version" key={version.id}>
                <div><strong>v{version.version_number}</strong><span className={`badge ${statusClass(version.status)}`}>{statusLabel(version.status)}</span>{template?.latest_published_version_number === version.version_number && version.status === "published" ? <span className="badge success">当前使用</span> : null}<small>{formatTime(version.created_at)}</small></div>
                <div className="row-actions">
                  <button className="secondary-button compact" type="button" disabled={Boolean(busy)} onClick={() => { void download(version) }}>{busy === `download:${version.id}` ? "下载中…" : "下载"}</button>
                  {version.status === "draft" ? <><button className="secondary-button compact" type="button" disabled={Boolean(busy)} onClick={() => { void runAction(version, "test") }}>{busy === `test:${version.id}` ? "测试中…" : "测试生成"}</button><button className="primary-button compact" type="button" disabled={Boolean(busy)} onClick={() => { void runAction(version, "publish") }}>{busy === `publish:${version.id}` ? "发布中…" : "发布"}</button></> : null}
                  {version.status !== "inactive" ? <button className="danger-button compact" type="button" disabled={Boolean(busy)} onClick={() => { void deactivate(version) }}>停用</button> : null}
                </div>
              </article>)}
            </div>
          </section>
        })}
      </div>}
    </div>
  )
}

function isTemplateList(value: unknown): value is { items: DocumentTemplateDto[] } {
  if (!value || typeof value !== "object" || !Array.isArray((value as { items?: unknown }).items)) return false
  return (value as { items: unknown[] }).items.every((item) => Boolean(item) && typeof item === "object" && typeof (item as DocumentTemplateDto).document_type === "string" && Array.isArray((item as DocumentTemplateDto).versions))
}
function isDownloadUrl(value: unknown): value is { url: string } { return Boolean(value) && typeof value === "object" && typeof (value as { url?: unknown }).url === "string" }
function statusLabel(status: VersionStatus): string { return { draft: "草稿", published: "已发布", inactive: "已停用" }[status] }
function statusClass(status: VersionStatus): string { return status === "published" ? "success" : status === "draft" ? "warning" : "muted" }
function templateName(type: TemplateType): string { return TEMPLATE_TYPES.find((item) => item.type === type)?.name ?? "文档模板" }
function formatTime(value: string | null): string { if (!value) return ""; const date = new Date(value); return Number.isNaN(date.getTime()) ? "" : date.toLocaleString("zh-CN", { hour12: false }) }
function actionError(error: unknown): string {
  if (error instanceof ApiClientError) {
    const messages: Record<string, string> = { invalid_template_file: "模板文件无效，请选择内容完整的 DOCX 文件。", unsafe_template_expression: "模板包含不安全的占位符，请修改后重新上传。", unknown_document_type: "该模板类型暂不受支持。", invalid_version_state: "当前版本状态不允许执行此操作，请刷新后重试。", template_generation_failed: "模板测试未通过，请检查未闭合或无法识别的占位符。", template_docx_unavailable: "模板文件暂不可用，请重新上传。", request_timeout: "服务响应超时，请稍后重试。", forbidden: "只有管理员可以管理文档模板。" }
    return messages[error.code] ?? error.message ?? "文档模板操作失败，请稍后重试。"
  }
  return "文档模板操作失败，请稍后重试。"
}
