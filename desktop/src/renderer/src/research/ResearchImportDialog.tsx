import { useState } from "react"
import { ApiClientError, type RendererApiRequestOptions } from "../api/client"
import { isResearchImportPreviewDto, isResearchImportResultDto, parseResearchImportErrorDetails } from "./projectRuntimeValidation"
import { researchSubjectLabel, type CreatableResearchSubjectType, type ResearchImportErrorDto, type ResearchImportPreviewDto, type ResearchImportResultDto } from "./types"

// V3 T-O4 桌面面：调研对象批量导入——CSV/XLSX 先解析预览（服务端签发 30 分钟
// 一次性 token），确认后提交；与既有启用对象同名的行服务端会让位不新建，事后
// 以导入结果卡片的 merge_candidates 供人逐条回溯。行错误来自 422 的
// details.errors，与预览内联错误共用同一展示区。
const MAX_IMPORT_BYTES = 10 * 1024 * 1024
const IMPORTABLE_SUBJECT_TYPES: CreatableResearchSubjectType[] = ["department", "role", "process", "opportunity"]
const VISIBLE_ROW_ERROR_LIMIT = 8

interface Props {
  projectId: string
  projectVersion: number
  apiRequest<T>(path: string, options: RendererApiRequestOptions): Promise<T>
  /** CR-032 写路径：注册对象类型（T-O2 注册表 active 行）——导入对象类型附加选项。 */
  registeredTypes?: string[]
  onClose(): void
  onStale(): void
  onImported(result: ResearchImportResultDto): Promise<void> | void
}

export function ResearchImportDialog({ projectId, projectVersion, apiRequest, registeredTypes, onClose, onStale, onImported }: Props) {
  const [subjectType, setSubjectType] = useState<CreatableResearchSubjectType>("department")
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ResearchImportPreviewDto | null>(null)
  const [rowErrors, setRowErrors] = useState<ResearchImportErrorDto[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  function resetPreview() {
    setPreview(null)
    setRowErrors([])
    setError("")
  }

  async function submitPreview(): Promise<void> {
    if (!file) { setError("请先选择要导入的 CSV 或 XLSX 文件。"); return }
    if (file.size > MAX_IMPORT_BYTES) { setError("导入文件超过 10MB 上限，请拆分后再导入。"); return }
    setBusy(true)
    try {
      const bytes = await readFileBytes(file)
      const value = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/research/subjects/imports/preview`, {
        method: "POST",
        body: { kind: "multipart_file", fields: { subject_type: subjectType }, file: { field_name: "file", name: file.name, type: file.type || "application/octet-stream", bytes } },
      })
      if (!isResearchImportPreviewDto(value)) throw new Error("invalid import preview")
      setPreview(value)
      setRowErrors(value.errors)
      setError(value.errors.length ? "导入文件存在校验错误，请修正后重新上传。" : "")
    } catch (caught) {
      setRowErrors(importErrorRows(caught))
      setError(importErrorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  async function submitCommit(): Promise<void> {
    if (!preview) return
    setBusy(true)
    try {
      const value = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/research/subjects/imports/commit`, {
        method: "POST",
        body: { preview_token: preview.preview_token, version: projectVersion },
      })
      if (!isResearchImportResultDto(value)) throw new Error("invalid import result")
      await onImported(value)
      onClose()
    } catch (caught) {
      if (caught instanceof ApiClientError && caught.code === "stale_version") onStale()
      setRowErrors(importErrorRows(caught))
      setError(importErrorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return <div className="dialog-backdrop" role="presentation"><section className="dialog research-import-dialog" role="dialog" aria-modal="true" aria-labelledby="research-import-title">
    <div className="dialog-heading"><div><h3 id="research-import-title">导入调研对象</h3><p className="supporting-copy compact-copy">上传 CSV 或 XLSX 批量创建调研对象，列名：名称（必填）、说明、父级（可选）。与既有启用对象同名的行会让位不新建，导入后在结果卡片中逐条回溯。</p></div><button className="secondary-button compact" type="button" disabled={busy} onClick={onClose}>关闭</button></div>
    {preview ? <>
      <div className="research-import-summary">
        <span className="badge muted">{researchSubjectLabel(preview.subject_type)}</span>
        <span>共 {preview.row_count} 行</span>
        {preview.errors.length ? <span className="research-import-error-count">{preview.errors.length} 行有校验错误</span> : null}
        <span className="field-hint">预览 30 分钟内有效，提交一次后自动关闭。</span>
      </div>
      <div className="research-import-rows">
        <table>
          <thead><tr><th scope="col">行</th><th scope="col">名称</th><th scope="col">说明</th><th scope="col">父级</th></tr></thead>
          <tbody>{preview.rows.map((row) => <tr key={row.row}><td>{row.row}</td><td>{cellText(row.name)}</td><td>{cellText(row.description)}</td><td>{cellText(row.parent_name)}</td></tr>)}</tbody>
        </table>
      </div>
      {preview.errors.length ? <div className="research-import-errors"><p>存在校验错误的文件不会被导入，请修正后重新上传。</p><ul>{preview.errors.slice(0, VISIBLE_ROW_ERROR_LIMIT).map((item, index) => <li key={`${item.row}:${index}`}>第 {item.row} 行 · {item.column}：{item.message}</li>)}{preview.errors.length > VISIBLE_ROW_ERROR_LIMIT ? <li>…还有 {preview.errors.length - VISIBLE_ROW_ERROR_LIMIT} 个错误</li> : null}</ul></div> : null}
      {error ? <p className="form-error banner" role="alert">{error}</p> : null}
      <div className="dialog-actions"><button type="button" className="secondary-button" disabled={busy} onClick={resetPreview}>重新选择</button><button type="button" className="primary-button" disabled={busy || !preview.row_count || preview.errors.length > 0} onClick={() => void submitCommit()}>{busy ? "正在导入" : "确认导入"}</button></div>
    </> : <>
      <label className="field"><span>对象类型</span><select value={subjectType} disabled={busy} onChange={(event) => { setSubjectType(event.target.value as CreatableResearchSubjectType); resetPreview() }}>{IMPORTABLE_SUBJECT_TYPES.map((type) => <option value={type} key={type}>{researchSubjectLabel(type)}</option>)}{(registeredTypes ?? []).map((type) => <option value={type} key={`registered:${type}`}>{researchSubjectLabel(type)}（注册类型）</option>)}</select></label>
      <label className="field"><span>导入文件（CSV 或 XLSX，≤10MB）</span><input aria-label="导入文件" type="file" accept=".csv,.xlsx" disabled={busy} onChange={(event) => { setFile(event.target.files?.[0] ?? null); resetPreview() }} /></label>
      {file ? <p className="field-hint">已选择：{file.name}</p> : null}
      {error ? <p className="form-error banner" role="alert">{error}</p> : null}
      {rowErrors.length ? <div className="research-import-errors"><ul>{rowErrors.slice(0, VISIBLE_ROW_ERROR_LIMIT).map((item, index) => <li key={`${item.row}:${index}`}>第 {item.row} 行 · {item.column}：{item.message}</li>)}{rowErrors.length > VISIBLE_ROW_ERROR_LIMIT ? <li>…还有 {rowErrors.length - VISIBLE_ROW_ERROR_LIMIT} 个错误</li> : null}</ul></div> : null}
      <div className="dialog-actions"><button type="button" className="secondary-button" disabled={busy} onClick={onClose}>取消</button><button type="button" className="primary-button" disabled={busy || !file} onClick={() => void submitPreview()}>{busy ? "正在解析" : "解析预览"}</button></div>
    </>}
  </section></div>
}

function cellText(value: unknown): string {
  return typeof value === "string" ? value : ""
}

// jsdom 的 File 至今没有 arrayBuffer()（Electron 真环境有）——测试环境走
// FileReader 兜底，两条路径产出同一份字节。
function readFileBytes(file: File): Promise<Uint8Array> {
  if (typeof file.arrayBuffer === "function") {
    return file.arrayBuffer().then((buffer) => new Uint8Array(buffer))
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer))
    reader.onerror = () => reject(reader.error ?? new Error("导入文件读取失败。"))
    reader.readAsArrayBuffer(file)
  })
}

function importErrorRows(error: unknown): ResearchImportErrorDto[] {
  if (error instanceof ApiClientError && error.code === "invalid_research_import") {
    return parseResearchImportErrorDetails(error.details) ?? []
  }
  return []
}

function importErrorMessage(error: unknown): string {
  if (!(error instanceof ApiClientError)) return "导入操作失败，请稍后重试。"
  if (error.code === "invalid_research_import") return "导入文件存在校验错误，请修正后重新上传。"
  const map: Record<string, string> = {
    unsupported_subject_type: "该项目不支持导入此类型的调研对象，请刷新后重试。",
    unsupported_import_format: "仅支持 CSV 或 XLSX 文件。",
    research_import_too_large: "导入文件超过 10MB 上限，请拆分后再导入。",
    unsupported_csv_encoding: "CSV 文件需使用 UTF-8 或 GB18030 编码。",
    research_import_workbook_too_complex: "XLSX 工作簿结构过于复杂，无法安全处理。",
    invalid_research_import_file: "导入文件内容无效或已损坏。",
    research_import_preview_not_found: "导入预览已失效，请重新解析文件。",
    research_import_preview_expired: "导入预览已过期，请重新解析文件。",
    research_import_commit_in_progress: "该导入正在提交中，请稍后刷新调研数据查看结果。",
    research_import_storage_unavailable: "导入预览服务暂时不可用，请稍后重试。",
    research_import_failed: "导入失败，请稍后重试。",
    stale_version: "调研数据已被其他操作更新，已刷新调研数据；请重新解析文件后再提交。",
    forbidden: "当前账号无权导入调研对象。",
    project_not_found: "项目不存在或无权访问。",
    network_error: "无法连接本地服务，请确认服务已启动。",
  }
  return map[error.code] ?? error.message
}
