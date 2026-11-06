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
  /** 三态流转里的 confirm/reject 权限（服务端 `_require_confirm` = can_manage）。
   *  可选且默认「无权」——安全默认：漏传时三态按钮不出现，而非误开放。 */
  canManage?: boolean
  apiRequest<T>(path: string, options: RendererApiRequestOptions): Promise<T>
  onUpdate(form: ProjectResearchFormDto): void
  onDirtyChange(dirty: boolean): void
  onSaved?(form: ProjectResearchFormDto): void
  onCancel?(): void
}

export function ResearchForm({ projectId, form, canFill, canManage = false, apiRequest, onUpdate, onDirtyChange, onSaved, onCancel }: ResearchFormProps) {
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
  // 三态流转（confirm / reject / revise）——台账 T-A3。
  const [triState, setTriState] = useState<"" | "confirm" | "reject" | "revise">("")
  const [rejectPanelOpen, setRejectPanelOpen] = useState(false)
  const [rejectReason, setRejectReason] = useState("")

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
    setRejectPanelOpen(false)
    setRejectReason("")
    setTriState("")
    onDirtyChange(false)
  }, [form.id, revision?.id, revision?.version])

  const sections = useMemo(() => identificationSections(form), [form.definition_snapshot])
  const fields = useMemo(() => sections
    .flatMap((section) => section.fields)
    .sort((left, right) => left.sort_order - right.sort_order), [sections])
  const visibleKeys = useMemo(() => visibleResearchFieldKeys(fields, values), [fields, values])
  const invalidVisibleFields = fields.filter((field) => visibleKeys.has(field.field_key) && invalidFields.has(field.field_key))
  const completion = localCompletion(fields, values, visibleKeys)
  // 已确认的修订仍是可编辑的——既有契约（project-research 用例钉住）：
  // 在已确认表上直接保存，服务端 `_ensure_working_revision` 会自动 fork 出
  // 新 draft 修订并保留原修订不变（legacy confirmed 表的迁移兼容路径）。
  // 桌面的 revise 入口是**并行的显式留痕通道**：它让「谁在何时基于已确认
  // 版本发起了修订」落进 operation_events，而隐式 fork 不记事件。
  const isConfirmed = revision?.status === "confirmed"
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

  // ── 三态流转（confirm / reject / revise）——台账 T-A3 ──
  // 权限口径与服务端同构：confirm/reject 走 `_require_confirm`（can_manage），
  // revise 走 `_require_fill`（can_manage 或 can_update_assigned_tasks）。
  async function runTriState(action: "confirm" | "reject" | "revise", body: Record<string, unknown>): Promise<void> {
    if (!revision) return
    setTriState(action)
    setError("")
    setMessage("")
    try {
      const next = await guardedFormRequest(
        apiRequest,
        `/api/v1/projects/${encodeURIComponent(projectId)}/research/forms/${encodeURIComponent(form.id)}/${action}`,
        { method: "POST", body: { version: revision.version, ...body } },
      )
      adopt(next)
      setRejectPanelOpen(false)
      setRejectReason("")
      setMessage(
        action === "confirm"
          ? "调研事实已确认。后续修改请直接保存或创建修订版——两者都会生成新修订，已确认版本不变。"
          : action === "reject"
            ? "已驳回并记录修改意见，草稿保持可编辑。"
            : "已基于已确认版本创建修订版，可继续编辑。",
      )
    } catch (caught) {
      if (caught instanceof ApiClientError && (caught.code === "stale_version" || caught.code === "research_form_conflict")) {
        setConflict("stale")
        setError("其他同事已更新该表单。本地输入已保留，请刷新远端版本后重试。")
      } else {
        setError(triStateError(caught, action))
      }
    } finally {
      setTriState("")
    }
  }

  async function confirmForm(): Promise<void> {
    if (!revision || !canManage || isConfirmed) return
    // 必填校验与服务端 confirm 同源（visible + is_required + 非空），
    // 用服务端下发的 completion 口径，不在桌面另算一套。
    const missing = form.completion?.missing_required_field_keys ?? []
    if (missing.length) {
      const labels = researchFieldLabels(form)
      setError(`必填项尚未完成：${missing.map((key) => labels.get(key) ?? key).join("、")}。补齐并保存后再确认。`)
      return
    }
    await runTriState("confirm", {})
  }

  async function submitReject(): Promise<void> {
    if (!revision || !canManage || isConfirmed) return
    const comment = rejectReason.trim()
    if (!comment) {
      setError("驳回必须填写理由，供填写人对照修改。")
      return
    }
    await runTriState("reject", { review_comment: comment })
  }

  async function reviseForm(): Promise<void> {
    if (!revision || !canFill) return
    if (!isConfirmed) {
      setError("仅已确认的调研表可创建修订版。")
      return
    }
    await runTriState("revise", {})
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
    {revision ? <section className="research-form-tri-state" aria-label="调研表事实流转">
      <div className="research-form-tri-state-heading"><h3>事实流转</h3><span className="badge muted">{isConfirmed ? "已确认" : "草稿"}</span></div>
      {revision.return_comment ? <p className="research-form-return-comment">驳回意见：{revision.return_comment}</p> : null}
      {isConfirmed ? <p className="field-hint">本表事实已确认。直接保存会在已确认版本之上创建新修订（原版本不变）；点「创建修订版」是显式发起修订，会在事实链留痕。</p> : null}
      {dirty ? <p className="field-hint" role="status">有未保存修改——请先保存调研内容再进行流转操作。</p> : null}
      <div className="research-form-actions">
        {canManage && !isConfirmed ? <button type="button" className="primary-button" disabled={busy || dirty || triState !== ""} onClick={() => void confirmForm()}>{triState === "confirm" ? "正在确认" : "确认事实"}</button> : null}
        {canManage && !isConfirmed ? <button type="button" className="secondary-button" disabled={busy || dirty || triState !== ""} onClick={() => { setRejectPanelOpen((open) => !open); setRejectReason(""); setError("") }}>驳回并留意见</button> : null}
        {canFill && isConfirmed ? <button type="button" className="secondary-button" disabled={busy || triState !== ""} onClick={() => void reviseForm()}>{triState === "revise" ? "正在创建修订版" : "创建修订版"}</button> : null}
      </div>
      {rejectPanelOpen && canManage && !isConfirmed ? <div className="research-form-reject-panel">
        <label htmlFor={`research-reject-${form.id}`}>驳回理由（必填）</label>
        <textarea id={`research-reject-${form.id}`} rows={3} maxLength={2000} value={rejectReason} disabled={triState !== ""} placeholder="说明需要修改的事实与依据，填写人会看到这段意见。" onChange={(event) => setRejectReason(event.target.value)} />
        <div className="research-form-actions"><button type="button" className="secondary-button" disabled={triState !== ""} onClick={() => setRejectPanelOpen(false)}>取消</button><button type="button" className="danger-button" disabled={triState !== "" || dirty} onClick={() => void submitReject()}>{triState === "reject" ? "正在驳回" : "提交驳回"}</button></div>
      </div> : null}
    </section> : null}
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

function researchFieldLabels(form: ProjectResearchFormDto): Map<string, string> {
  const labels = new Map<string, string>()
  for (const section of form.definition_snapshot.sections) {
    for (const field of section.fields) labels.set(field.field_key, field.name)
  }
  return labels
}

// 三态失败语义：已知错误码给中文可执行提示；未知错误码回落到服务端原文
// （不吞错误——台账 T-A3 验收：403/409 原样呈现）。
function triStateError(error: unknown, action: "confirm" | "reject" | "revise"): string {
  if (error instanceof ApiClientError) {
    if (error.code === "forbidden") return "你没有权限执行该操作。"
    if (error.code === "research_required_fields_missing") return "必填项尚未完成，无法确认——请补齐并保存后重试。"
    if (error.code === "research_form_not_draft") return "当前版本不是草稿，无法执行该操作——请刷新后重试。"
    if (error.code === "research_form_not_confirmed") return "仅已确认的调研表可创建修订版。"
    if (error.code === "invalid_request") return "请求参数不合法，请刷新后重试。"
    return error.message
  }
  if (action === "confirm") return "确认失败，请稍后重试。"
  if (action === "reject") return "驳回失败，请稍后重试。"
  return "创建修订版失败，请稍后重试。"
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
