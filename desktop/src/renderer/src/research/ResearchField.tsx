import { useEffect, useId, useRef, useState } from "react"

import type { RendererApiRequestOptions } from "../api/client"
import { isProjectFileListDto } from "../files/runtimeValidation"
import type { ProjectFileDto } from "../files/types"
import { normalizeDecimalValue } from "./conditionValueContract"
import type {
  ResearchAnswerValue,
  ResearchEditableAnswerValue,
  ResearchEditableTableRow,
  ResearchFieldDto,
  ResearchRichTextDto,
  ResearchScalarAnswer,
  ResearchTableColumnDto,
} from "./types"

interface ResearchFieldProps {
  definition: ResearchFieldDto
  value: ResearchEditableAnswerValue | undefined
  onChange(value: ResearchEditableAnswerValue): void
  onValidityChange?(valid: boolean): void
  disabled: boolean
  resetKey?: string
  projectId?: string
  apiRequest?<T>(path: string, options: RendererApiRequestOptions): Promise<T>
}

export function ResearchField({ definition, value, onChange, onValidityChange, disabled, resetKey, projectId, apiRequest }: ResearchFieldProps) {
  const id = useId()
  const hintId = `${id}-hint`
  const describedBy = definition.help_text ? hintId : undefined
  const label = <><span>{definition.name}{definition.is_required ? <span className="required-marker" aria-hidden="true"> *</span> : null}</span>{definition.help_text ? <small id={hintId} className="field-hint">{definition.help_text}</small> : null}</>

  if (definition.type === "long_text") {
    return <label className="field" htmlFor={id}>{label}<textarea id={id} aria-label={definition.name} aria-describedby={describedBy} rows={5} disabled={disabled} value={stringValue(value)} placeholder={textOption(definition, "placeholder")} onChange={(event) => onChange(event.target.value)} /></label>
  }
  if (definition.type === "rich_text") {
    return <RichTextField id={id} label={label} ariaLabel={definition.name} describedBy={describedBy} value={value} disabled={disabled} placeholder={textOption(definition, "placeholder")} onChange={onChange} />
  }
  if (definition.type === "integer" || definition.type === "decimal") {
    return <CanonicalNumberField id={id} label={label} ariaLabel={definition.name} describedBy={describedBy} type={definition.type} value={value} disabled={disabled} emptyIsValid resetKey={resetKey} onChange={onChange} onValidityChange={onValidityChange} />
  }
  if (definition.type === "date") {
    return <label className="field" htmlFor={id}>{label}<input id={id} aria-label={definition.name} aria-describedby={describedBy} type="date" disabled={disabled} value={stringValue(value)} min={textOption(definition, "minimum")} max={textOption(definition, "maximum")} onChange={(event) => onChange(event.target.value || null)} /></label>
  }
  if (definition.type === "single_choice") {
    return <label className="field" htmlFor={id}>{label}<select id={id} aria-label={definition.name} aria-describedby={describedBy} disabled={disabled} value={stringValue(value)} onChange={(event) => onChange(event.target.value || null)}><option value="">请选择</option>{choices(definition).map((choice) => <option key={choice} value={choice}>{choice}</option>)}</select></label>
  }
  if (definition.type === "multi_choice") {
    const selected = stringArray(value)
    return <fieldset className="research-answer-group" disabled={disabled} aria-describedby={describedBy}><legend>{definition.name}{definition.is_required ? <span className="required-marker" aria-hidden="true"> *</span> : null}</legend>{definition.help_text ? <small id={hintId} className="field-hint">{definition.help_text}</small> : null}<div className="research-choice-list">{choices(definition).map((choice) => <label key={choice}><input type="checkbox" checked={selected.includes(choice)} onChange={(event) => onChange(event.target.checked ? [...selected, choice] : selected.filter((item) => item !== choice))} />{choice}</label>)}</div></fieldset>
  }
  if (definition.type === "table") {
    return <ResearchTableField definition={definition} value={value} onChange={onChange} onValidityChange={onValidityChange} disabled={disabled} resetKey={resetKey} />
  }
  if (definition.type === "file_reference") {
    return <FileReferenceField definition={definition} value={value} onChange={onChange} disabled={disabled} projectId={projectId} apiRequest={apiRequest} />
  }
  return <label className="field" htmlFor={id}>{label}<input id={id} aria-label={definition.name} aria-describedby={describedBy} type="text" disabled={disabled} value={stringValue(value)} placeholder={textOption(definition, "placeholder")} onChange={(event) => onChange(event.target.value)} /></label>
}

function RichTextField({ id, label, ariaLabel, describedBy, value, disabled, placeholder, onChange }: {
  id: string
  label: React.ReactNode
  ariaLabel: string
  describedBy?: string
  value: ResearchEditableAnswerValue | undefined
  disabled: boolean
  placeholder?: string
  onChange(value: ResearchAnswerValue): void
}) {
  const [text, setText] = useState(() => richTextString(value))
  useEffect(() => setText(richTextString(value)), [value])
  return <label className="field" htmlFor={id}>{label}<textarea id={id} aria-label={ariaLabel} aria-describedby={describedBy} rows={7} disabled={disabled} value={text} placeholder={placeholder} onChange={(event) => {
    const next = event.target.value
    setText(next)
    onChange(richTextDocument(next))
  }} /><small className="field-hint">仅保存纯文本段落，不解析 HTML。</small></label>
}

function CanonicalNumberField({ id, label, ariaLabel, describedBy, type, value, disabled, emptyIsValid, resetKey, onChange, onValidityChange }: {
  id: string
  label: React.ReactNode
  ariaLabel: string
  describedBy?: string
  type: "integer" | "decimal"
  value: ResearchEditableAnswerValue | undefined
  disabled: boolean
  emptyIsValid: boolean
  resetKey?: string
  onChange(value: ResearchEditableAnswerValue): void
  onValidityChange?(valid: boolean): void
}) {
  const [raw, setRaw] = useState(() => scalarString(value))
  useEffect(() => setRaw(scalarString(value)), [value, resetKey])
  return <label className="field" htmlFor={id}>{label}<input id={id} aria-label={ariaLabel} aria-describedby={describedBy} type="text" inputMode={type === "integer" ? "numeric" : "decimal"} disabled={disabled} value={raw} onChange={(event) => {
    const next = event.target.value
    setRaw(next)
    if (next === "") {
      onValidityChange?.(emptyIsValid)
      onChange(null)
      return
    }
    if (type === "integer" && /^[+-]?\d+$/.test(next)) {
      const parsed = Number(next)
      if (Number.isSafeInteger(parsed)) {
        onValidityChange?.(true)
        onChange(parsed)
        return
      }
    }
    if (type === "decimal") {
      const normalized = normalizeDecimalValue(next)
      if (normalized !== null) {
        onValidityChange?.(true)
        onChange(normalized)
        return
      }
    }
    onValidityChange?.(false)
  }} /></label>
}

function ResearchTableField({ definition, value, onChange, onValidityChange, disabled, resetKey }: ResearchFieldProps) {
  const columns = tableColumns(definition)
  const rows = tableRows(value)
  const tableId = useId()
  const nextRowId = useRef(0)
  const allocateRowId = () => `${tableId}-row-${nextRowId.current++}`
  const [rowIds, setRowIds] = useState<string[]>(() => rows.map(allocateRowId))
  const [invalidCells, setInvalidCells] = useState<Set<string>>(new Set())
  const invalidCellsRef = useRef(invalidCells)
  useEffect(() => {
    const nextIds = rows.map(allocateRowId)
    setRowIds(nextIds)
    invalidCellsRef.current = new Set()
    setInvalidCells(new Set())
    onValidityChange?.(true)
  }, [resetKey])
  const updateRows = (next: ResearchEditableTableRow[]) => onChange(next)
  function updateCellValidity(cell: string, valid: boolean): void {
    const next = new Set(invalidCellsRef.current)
    if (valid) next.delete(cell)
    else next.add(cell)
    invalidCellsRef.current = next
    setInvalidCells(next)
    onValidityChange?.(next.size === 0)
  }
  function deleteRow(rowIndex: number): void {
    const removedId = rowIds[rowIndex]
    const nextInvalid = new Set([...invalidCellsRef.current].filter((cell) => !cell.startsWith(`${removedId}:`)))
    invalidCellsRef.current = nextInvalid
    setInvalidCells(nextInvalid)
    setRowIds((current) => current.filter((_, index) => index !== rowIndex))
    onValidityChange?.(nextInvalid.size === 0)
    updateRows(rows.filter((_, index) => index !== rowIndex))
  }
  function addRow(): void {
    const rowId = allocateRowId()
    const nextInvalid = new Set(invalidCellsRef.current)
    for (const column of columns) if (cellRequiresNonEmptyValue(column)) nextInvalid.add(`${rowId}:${column.key}`)
    invalidCellsRef.current = nextInvalid
    setInvalidCells(nextInvalid)
    setRowIds((current) => [...current, rowId])
    onValidityChange?.(nextInvalid.size === 0)
    updateRows([...rows, Object.fromEntries(columns.map((column) => [column.key, defaultColumnValue(column)]))])
  }
  return <fieldset className="research-answer-group research-table-field" disabled={disabled}><legend>{definition.name}{definition.is_required ? <span className="required-marker" aria-hidden="true"> *</span> : null}</legend>{definition.help_text ? <small className="field-hint">{definition.help_text}</small> : null}<div className="table-scroll"><table aria-label={definition.name}><thead><tr>{columns.map((column) => <th key={column.key} scope="col">{column.name}</th>)}{disabled ? null : <th scope="col">操作</th>}</tr></thead><tbody>{rows.map((row, rowIndex) => { const rowId = rowIds[rowIndex] ?? `${tableId}-pending-${rowIndex}`; return <tr key={rowId}>{columns.map((column) => <td key={column.key}><TableCell column={column} rowId={rowId} rowIndex={rowIndex} resetKey={resetKey} value={row[column.key]} disabled={disabled} onValidityChange={(valid) => updateCellValidity(`${rowId}:${column.key}`, valid)} onChange={(next) => updateRows(rows.map((item, index) => index === rowIndex ? { ...item, [column.key]: next } : item))} /></td>)}{disabled ? null : <td><button type="button" className="danger-text-button" aria-label={`删除第 ${rowIndex + 1} 行`} onClick={() => deleteRow(rowIndex)}>删除</button></td>}</tr> })}</tbody></table></div>{disabled ? null : <button type="button" className="secondary-button compact" aria-label={`为${definition.name}新增一行`} onClick={addRow}>新增一行</button>}</fieldset>
}

function TableCell({ column, rowId, rowIndex, resetKey, value, disabled, onChange, onValidityChange }: { column: ResearchTableColumnDto; rowId: string; rowIndex: number; resetKey?: string; value: ResearchScalarAnswer | null | undefined; disabled: boolean; onChange(value: ResearchScalarAnswer | null): void; onValidityChange(valid: boolean): void }) {
  const label = `第 ${rowIndex + 1} 行 ${column.name}`
  const type = column.type ?? "short_text"
  if (type === "integer" || type === "decimal") {
    return <CanonicalNumberField id={`${rowId}-${column.key}`} label={label} ariaLabel={label} type={type} value={value} disabled={disabled} emptyIsValid={false} resetKey={resetKey} onValidityChange={onValidityChange} onChange={(next) => onChange(next as ResearchScalarAnswer | null)} />
  }
  if (type === "single_choice") return <select aria-label={label} disabled={disabled} value={stringValue(value)} onChange={(event) => { const next = event.target.value; onValidityChange(next !== ""); onChange(next || null) }}><option value="">请选择</option>{columnChoices(column).map((choice) => <option key={choice}>{choice}</option>)}</select>
  if (type === "multi_choice") return <fieldset className="table-choice-cell"><legend>{label}</legend>{columnChoices(column).map((choice) => <label key={choice}><input type="checkbox" disabled={disabled} checked={stringArray(value).includes(choice)} onChange={(event) => onChange(event.target.checked ? [...stringArray(value), choice] : stringArray(value).filter((item) => item !== choice))} />{choice}</label>)}</fieldset>
  if (type === "date") return <input aria-label={label} type="date" disabled={disabled} value={stringValue(value)} onChange={(event) => { const next = event.target.value; onValidityChange(next !== ""); onChange(next || null) }} />
  if (type === "long_text" || type === "rich_text") return <textarea aria-label={label} disabled={disabled} value={type === "rich_text" ? richTextString(value) : stringValue(value)} onChange={(event) => onChange(type === "rich_text" ? richTextDocument(event.target.value) : event.target.value)} />
  return <input aria-label={label} type="text" disabled={disabled} value={stringValue(value)} onChange={(event) => onChange(event.target.value)} />
}

function FileReferenceField({ definition, value, onChange, disabled, projectId, apiRequest }: ResearchFieldProps) {
  const references = stringArray(value)
  const maximum = typeof (definition.options as { max_files?: unknown }).max_files === "number" ? (definition.options as { max_files: number }).max_files : 1
  const [pickerOpen, setPickerOpen] = useState(false)
  const [files, setFiles] = useState<ProjectFileDto[]>([])
  const [pending, setPending] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState("")
  const fileNames = new Map(files.map((file) => [file.id, file.display_name]))

  async function openPicker(): Promise<void> {
    if (!projectId || !apiRequest) {
      setLoadError("文件库选择器暂不可用，请刷新页面后重试。")
      setPickerOpen(true)
      return
    }
    setPickerOpen(true)
    setPending(references)
    setLoading(true)
    setLoadError("")
    try {
      const result = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/files`, { method: "GET" })
      if (!isProjectFileListDto(result)) throw new Error("invalid project file list")
      setFiles(result.items.filter((file) => file.category === "attachment" && file.status === "active" && file.current_version?.status === "available"))
    } catch {
      setLoadError("文件库加载失败，请稍后重试。")
    } finally {
      setLoading(false)
    }
  }

  function toggleReference(fileId: string): void {
    setPending((current) => current.includes(fileId)
      ? current.filter((item) => item !== fileId)
      : current.length < maximum ? [...current, fileId] : current)
  }

  return <fieldset className="research-answer-group" disabled={disabled}>
    <legend>{definition.name}{definition.is_required ? <span className="required-marker" aria-hidden="true"> *</span> : null}</legend>
    {definition.help_text ? <small className="field-hint">{definition.help_text}</small> : null}
    <p className="field-hint">从项目文件库选择已上传的文件，此处不会上传新文件。</p>
    <div className="research-reference-entry">
      <label className="field">
        <span>{definition.name}（可关联文件库文件）</span>
        <input aria-label={`${definition.name}（可关联文件库文件）`} readOnly value={references.length ? `已关联 ${references.length} 个文件` : ""} placeholder="请从文件库选择" disabled={disabled} onClick={() => void openPicker()} />
      </label>
      <button type="button" className="secondary-button" disabled={disabled} onClick={() => void openPicker()}>添加附件引用</button>
    </div>
    {references.length ? <ul className="research-reference-list">{references.map((reference) => <li key={reference}><span><strong>{fileNames.get(reference) ?? "已关联文件"}</strong><code>{reference}</code></span>{disabled ? null : <button type="button" className="danger-text-button" aria-label={`移除附件引用 ${reference}`} onClick={() => onChange(references.filter((item) => item !== reference))}>移除</button>}</li>)}</ul> : <p className="field-hint">尚未选择附件。</p>}
    {pickerOpen ? <div className="dialog-backdrop" role="presentation">
      <section className="dialog research-file-picker-dialog" role="dialog" aria-modal="true" aria-labelledby="research-file-picker-title">
        <div className="dialog-heading"><div><h3 id="research-file-picker-title">选择文件库文件</h3><p className="supporting-copy compact-copy">最多关联 {maximum} 个文件。</p></div><button type="button" className="secondary-button compact" onClick={() => setPickerOpen(false)}>关闭</button></div>
        {loadError ? <p className="form-error banner" role="alert">{loadError}</p> : loading ? <p role="status">正在加载文件库…</p> : files.length ? <ul className="research-file-picker-list">{files.map((file) => {
          const checked = pending.includes(file.id)
          return <li key={file.id}><label><input type="checkbox" checked={checked} disabled={!checked && pending.length >= maximum} onChange={() => toggleReference(file.id)} /><span><strong>{file.display_name}</strong><small>{file.current_version?.original_filename || "项目文件"}</small></span></label></li>
        })}</ul> : <p className="empty-state">文件库中暂无可关联的项目文件。</p>}
        <div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => setPickerOpen(false)}>取消</button><button type="button" className="primary-button" disabled={loading || Boolean(loadError)} onClick={() => { onChange(pending); setPickerOpen(false) }}>确认关联（{pending.length}）</button></div>
      </section>
    </div> : null}
  </fieldset>
}

function textOption(definition: ResearchFieldDto, key: string): string | undefined {
  const value = (definition.options as Record<string, unknown>)[key]
  return typeof value === "string" ? value : undefined
}

function choices(definition: ResearchFieldDto): string[] {
  const value = (definition.options as { choices?: unknown }).choices
  return Array.isArray(value) && value.every((item) => typeof item === "string") ? value : []
}

function columnChoices(column: ResearchTableColumnDto): string[] {
  const value = (column.options as { choices?: unknown } | undefined)?.choices
  return Array.isArray(value) && value.every((item) => typeof item === "string") ? value : []
}

function tableColumns(definition: ResearchFieldDto): ResearchTableColumnDto[] {
  const value = (definition.options as { columns?: unknown }).columns
  return Array.isArray(value) ? value as ResearchTableColumnDto[] : []
}

function tableRows(value: ResearchEditableAnswerValue | undefined): ResearchEditableTableRow[] {
  return Array.isArray(value) && value.every((item) => typeof item === "object" && item !== null && !Array.isArray(item)) ? value as ResearchEditableTableRow[] : []
}

function stringArray(value: ResearchEditableAnswerValue | ResearchScalarAnswer | undefined): string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string") ? value : []
}

function stringValue(value: ResearchEditableAnswerValue | ResearchScalarAnswer | undefined): string {
  return typeof value === "string" ? value : ""
}

function scalarString(value: ResearchEditableAnswerValue | ResearchScalarAnswer | undefined): string {
  return typeof value === "number" || typeof value === "string" ? String(value) : ""
}

function richTextString(value: ResearchEditableAnswerValue | ResearchScalarAnswer | undefined): string {
  if (!value || typeof value !== "object" || Array.isArray(value) || value.type !== "doc") return ""
  return value.content.map((paragraph) => paragraph.content.map((node) => node.text).join("")).join("\n")
}

function richTextDocument(value: string): ResearchRichTextDto {
  return {
    type: "doc",
    content: value.split("\n").map((line) => ({
      type: "paragraph",
      content: line ? [{ type: "text", text: line }] : [],
    })),
  }
}

function defaultColumnValue(column: ResearchTableColumnDto): ResearchScalarAnswer {
  const type = column.type ?? "short_text"
  if (type === "integer") return 0
  if (type === "decimal") return "0"
  if (type === "multi_choice") return []
  if (type === "rich_text") return richTextDocument("")
  return ""
}

function cellRequiresNonEmptyValue(column: ResearchTableColumnDto): boolean {
  const type = column.type ?? "short_text"
  return type === "date" || type === "single_choice"
}
