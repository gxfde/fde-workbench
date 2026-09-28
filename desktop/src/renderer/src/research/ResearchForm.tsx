import { useEffect, useMemo, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import type { RendererApiRequestOptions } from "../api/client"
import { normalizeAsciiEdgeWhitespace } from "./conditionValueContract"
import { isProjectResearchFormDto } from "./projectRuntimeValidation"
import { ResearchField } from "./ResearchField"
import type { ProjectResearchFormDto, ResearchAnswerValue, ResearchConditionDto, ResearchEditableAnswerValue, ResearchFieldDto } from "./types"

interface ResearchFormProps {
  projectId: string
  form: ProjectResearchFormDto
  canFill: boolean
  apiRequest<T>(path: string, options: RendererApiRequestOptions): Promise<T>
  onUpdate(form: ProjectResearchFormDto): void
  onDirtyChange(dirty: boolean): void
  onSaved?(form: ProjectResearchFormDto): void
  onCancel?(): void
}

export function ResearchForm({ projectId, form, canFill, apiRequest, onUpdate, onDirtyChange, onSaved, onCancel }: ResearchFormProps) {
  const revision = form.current_revision
  const [values, setValues] = useState<Record<string, ResearchEditableAnswerValue>>(() => answerMap(form))
  const [invalidFields, setInvalidFields] = useState<Set<string>>(new Set())
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")
  const [error, setError] = useState("")
  const [conflict, setConflict] = useState<"stale" | "immutable" | null>(null)
  const [remote, setRemote] = useState<ProjectResearchFormDto | null>(null)
  const [showDiff, setShowDiff] = useState(false)
  const [fieldResetGeneration, setFieldResetGeneration] = useState(0)
  const selfAdoptedForm = useRef<ProjectResearchFormDto | null>(null)

  useEffect(() => {
    if (selfAdoptedForm.current === form) {
      selfAdoptedForm.current = null
      return
    }
    selfAdoptedForm.current = null
    setValues(answerMap(form))
    setDirty(false)
    setInvalidFields(new Set())
    setMessage("")
    setError("")
    setConflict(null)
    setRemote(null)
    setShowDiff(false)
    setFieldResetGeneration((current) => current + 1)
    onDirtyChange(false)
  }, [form.id, revision?.id, revision?.version])

  const sections = useMemo(() => identificationSections(form), [form.definition_snapshot])
  const fields = useMemo(() => sections
    .flatMap((section) => section.fields)
    .sort((left, right) => left.sort_order - right.sort_order), [sections])
  const visibleKeys = useMemo(() => visibleResearchFieldKeys(fields, values), [fields, values])
  const invalidVisibleFields = fields.filter((field) => visibleKeys.has(field.field_key) && invalidFields.has(field.field_key))
  const completion = localCompletion(fields, values, visibleKeys)
  const editable = canFill && revision !== null

  function updateValue(fieldKey: string, value: ResearchEditableAnswerValue): void {
    setValues((current) => ({ ...current, [fieldKey]: value }))
    setDirty(true)
    setMessage("")
    setError("")
    setConflict(null)
    onDirtyChange(true)
  }

  function updateValidity(fieldKey: string, valid: boolean): void {
    setInvalidFields((current) => {
      const next = new Set(current)
      if (valid) next.delete(fieldKey)
      else next.add(fieldKey)
      return next
    })
    if (!valid) {
      setDirty(true)
      onDirtyChange(true)
    }
  }

  async function save(): Promise<void> {
    if (!revision || !editable) return
    if (invalidVisibleFields.length) {
      setError(`${invalidVisibleFields.map((field) => field.name).join("、")}格式无效，请修正后再保存。`)
      return
    }
    setBusy(true)
    setError("")
    setMessage("")
    try {
      const saved = await guardedFormRequest(
        apiRequest,
        `/api/v1/projects/${encodeURIComponent(projectId)}/research/forms/${encodeURIComponent(form.id)}`,
        { method: "PATCH", body: { version: revision.version, answers: submittedAnswers(values, visibleKeys) } },
      )
      adopt(saved)
      if (onSaved) onSaved(saved)
      else setMessage("调研内容已保存。")
    } catch (caught) {
      if (caught instanceof ApiClientError && (caught.code === "stale_version" || caught.code === "research_form_conflict")) {
        setConflict("stale")
        setError("其他同事已更新该表单。本地输入已保留，请刷新远端版本后比较。")
      } else {
        setError(formError(caught))
      }
    } finally {
      setBusy(false)
    }
  }

  function adopt(next: ProjectResearchFormDto): void {
    selfAdoptedForm.current = next
    setValues(answerMap(next))
    setFieldResetGeneration((current) => current + 1)
    setDirty(false)
    setInvalidFields(new Set())
    onDirtyChange(false)
    onUpdate(next)
  }

  async function refreshRemote(): Promise<ProjectResearchFormDto | null> {
    setBusy(true)
    setError("")
    try {
      const next = await guardedFormRequest(apiRequest, `/api/v1/projects/${encodeURIComponent(projectId)}/research/forms/${encodeURIComponent(form.id)}`, { method: "GET" })
      setRemote(next)
      setMessage("已读取远端版本，本地输入仍保留。")
      return next
    } catch (caught) {
      setError(formError(caught))
      return null
    } finally {
      setBusy(false)
    }
  }

  async function compare(): Promise<void> {
    const next = remote ?? await refreshRemote()
    if (next) setShowDiff(true)
  }

  async function discardLocal(): Promise<void> {
    const next = remote ?? await refreshRemote()
    if (!next) return
    setValues(answerMap(next))
    setFieldResetGeneration((current) => current + 1)
    setDirty(false)
    setConflict(null)
    setShowDiff(false)
    onDirtyChange(false)
    onUpdate(next)
    setMessage("已放弃本地修改并采用远端版本。")
  }

  return <article className="panel research-form-card-runtime" aria-labelledby={`research-form-${form.id}`} data-research-dirty={dirty ? "true" : undefined}>
    <header className="panel-heading"><div><h2 id={`research-form-${form.id}`}>{form.name}</h2><p className="supporting-copy">{form.definition_snapshot.subject_type === "opportunity" ? "记录 AI 机会的现状、痛点与业务价值。交付内容请在方案设计中维护。" : form.description}</p></div></header>
    <div className="research-completion" aria-label="表单完成度"><span>完成度 {completion.rate}%</span><progress max="100" value={completion.rate}>{completion.rate}%</progress><small>已填写 {completion.answered}/{completion.total}</small></div>
    {error ? <p className="form-error banner" role="alert">{error}</p> : null}
    {message ? <p className="notice" role="status">{message}</p> : null}
    {conflict ? <div className="research-conflict-actions" aria-label="版本冲突操作"><button type="button" className="secondary-button" disabled={busy} onClick={() => void refreshRemote()}>刷新远端版本</button><button type="button" className="secondary-button" disabled={busy} onClick={() => void compare()}>比较差异</button><button type="button" className="secondary-button" disabled={busy} onClick={() => void discardLocal()}>放弃本地修改</button></div> : null}
    {showDiff && remote ? <Comparison fields={fields} local={values} remote={answerMap(remote)} /> : null}
    <form onSubmit={(event) => { event.preventDefault(); void save() }}>
      <div className="research-runtime-section-list">{[...sections].sort((left, right) => left.sort_order - right.sort_order).map((section) => <fieldset className="research-runtime-section" key={section.section_key}><legend>{section.name}</legend>{section.description ? <p className="field-hint">{section.description}</p> : null}<div className="research-runtime-fields">{[...section.fields].sort((left, right) => left.sort_order - right.sort_order).filter((field) => visibleKeys.has(field.field_key)).map((field) => <ResearchField key={field.field_key} definition={{ ...field, is_required: false }} value={values[field.field_key]} resetKey={`${revision?.id ?? "none"}:${revision?.version ?? 0}:${fieldResetGeneration}`} disabled={!editable || busy} projectId={projectId} apiRequest={apiRequest} onChange={(value) => updateValue(field.field_key, value)} onValidityChange={(valid) => updateValidity(field.field_key, valid)} />)}</div></fieldset>)}</div>
      {editable ? <div className="research-form-actions">{onCancel ? <button type="button" className="secondary-button" disabled={busy} onClick={onCancel}>取消</button> : null}<button type="submit" className="primary-button" disabled={busy}>{busy ? "正在保存" : "保存调研内容"}</button></div> : null}
    </form>
    {dirty ? <p className="field-hint" role="status">有未保存修改</p> : null}
  </article>
}

const LEGACY_DELIVERY_FIELDS = new Set(["delivery_scope", "deliverables", "acceptance_criteria", "data_systems", "schedule", "risks_dependencies"])

function identificationSections(form: ProjectResearchFormDto) {
  const sections = form.definition_snapshot.sections
  if (form.definition_snapshot.subject_type !== "opportunity") return sections
  // Filter the view of legacy snapshots too. Saving only submits visible keys,
  // so the server can retain their historical delivery answers for migration.
  return sections
    .filter((section) => section.section_key !== "delivery" && section.name !== "交付说明")
    .map((section) => ({ ...section, fields: section.fields.filter((field) => !LEGACY_DELIVERY_FIELDS.has(field.field_key)) }))
    .filter((section) => section.fields.length > 0)
}

export function visibleResearchFieldKeys(fields: ResearchFieldDto[], answers: Record<string, ResearchEditableAnswerValue>): Set<string> {
  const byKey = new Map(fields.map((field) => [field.field_key, field]))
  const cache = new Map<string, boolean>()
  const visiting = new Set<string>()
  function visible(key: string): boolean {
    if (cache.has(key)) return cache.get(key)!
    if (visiting.has(key)) return false
    const field = byKey.get(key)
    if (!field) return false
    visiting.add(key)
    const result = matches(field.condition)
    visiting.delete(key)
    cache.set(key, result)
    return result
  }
  function matches(condition: ResearchConditionDto | undefined): boolean {
    if (!condition) return true
    if (condition.operator === "all") return condition.conditions.every(matches)
    if (condition.operator === "any") return condition.conditions.some(matches)
    if (!visible(condition.field_key)) return false
    const controller = byKey.get(condition.field_key)
    const rawAnswer = answers[condition.field_key]
    const answer = controller && (controller.type === "short_text" || controller.type === "long_text") && typeof rawAnswer === "string"
      ? normalizeAsciiEdgeWhitespace(rawAnswer)
      : rawAnswer
    if (condition.operator === "is_empty") return answerIsEmpty(answer)
    if (condition.operator === "contains") return typeof answer === "string"
      ? answer.includes(String(condition.value))
      : Array.isArray(answer) && answer.includes(condition.value as never)
    if (condition.operator === "equals") return answer === condition.value
    return answer !== condition.value
  }
  return new Set(fields.filter((field) => visible(field.field_key)).map((field) => field.field_key))
}

function answerMap(form: ProjectResearchFormDto): Record<string, ResearchAnswerValue> {
  return Object.fromEntries((form.current_revision?.answers ?? []).map((answer) => [answer.field_key, answer.value]))
}

function submittedAnswers(values: Record<string, ResearchEditableAnswerValue>, visible: Set<string>): Record<string, ResearchEditableAnswerValue> {
  return Object.fromEntries(Object.entries(values).filter(([key]) => visible.has(key)))
}

function localCompletion(fields: ResearchFieldDto[], values: Record<string, ResearchEditableAnswerValue>, visible: Set<string>) {
  const answered = fields.filter((field) => visible.has(field.field_key) && !answerIsEmpty(values[field.field_key])).length
  return {
    rate: visible.size === 0 ? 100 : Math.round(100 * answered / visible.size),
    answered,
    total: visible.size,
  }
}

function answerIsEmpty(value: ResearchEditableAnswerValue | undefined): boolean {
  if (value === undefined || value === null) return true
  if (typeof value === "string") return normalizeAsciiEdgeWhitespace(value) === ""
  if (Array.isArray(value)) return value.length === 0
  if (typeof value === "object" && value.type === "doc") return value.content.every((paragraph) => paragraph.content.every((node) => normalizeAsciiEdgeWhitespace(node.text) === ""))
  return false
}

async function guardedFormRequest(
  apiRequest: ResearchFormProps["apiRequest"], path: string, options: RendererApiRequestOptions,
): Promise<ProjectResearchFormDto> {
  const value = await apiRequest<unknown>(path, options)
  if (!isProjectResearchFormDto(value)) throw new Error("invalid research form")
  return value
}

function formError(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (error.code === "forbidden") return "你没有权限执行该操作。"
    if (error.code === "invalid_research_answer") return "字段值不符合调研表定义，请检查后重试。"
  }
  return "调研表操作失败，请稍后重试。"
}

function Comparison({ fields, local, remote }: { fields: ResearchFieldDto[]; local: Record<string, ResearchEditableAnswerValue>; remote: Record<string, ResearchEditableAnswerValue> }) {
  const changed = fields.filter((field) => JSON.stringify(local[field.field_key]) !== JSON.stringify(remote[field.field_key]))
  return <section className="research-comparison" aria-label="本地与远端差异"><h3>差异比较</h3>{changed.length ? <ul>{changed.map((field) => <li key={field.field_key}><strong>{field.name}</strong><span>本地：{displayValue(local[field.field_key])}</span><span>远端：{displayValue(remote[field.field_key])}</span></li>)}</ul> : <p>本地与远端值相同。</p>}</section>
}

function displayValue(value: ResearchEditableAnswerValue | undefined): string {
  if (value === undefined || value === null) return "（空）"
  if (typeof value === "object" && !Array.isArray(value) && value.type === "doc") return value.content.map((paragraph) => paragraph.content.map((node) => node.text).join("")).join(" / ") || "（空）"
  return typeof value === "string" ? value || "（空）" : JSON.stringify(value)
}
