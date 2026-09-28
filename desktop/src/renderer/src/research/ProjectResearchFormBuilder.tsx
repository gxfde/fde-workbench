import { useEffect, useId, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import type { RendererApiRequestOptions } from "../api/client"
import { isProjectResearchFormDto } from "./projectRuntimeValidation"
import { RESEARCH_FIELD_TYPES, RESEARCH_SUBJECT_TYPES, RESEARCH_SUBJECT_LABELS, type ProjectResearchFormDto, type ResearchConditionDto, type ResearchFieldOptionsDto, type ResearchFieldType, type ResearchSubjectDto, type ResearchSubjectType } from "./types"

interface BuilderField {
  clientId: string
  lockedKey: boolean
  fieldKey: string
  name: string
  helpText: string
  type: ResearchFieldType
  options: ResearchFieldOptionsDto
  condition?: ResearchConditionDto
}

interface BuilderSection {
  clientId: string
  lockedKey: boolean
  sectionKey: string
  name: string
  description: string
  fields: BuilderField[]
}

export interface ProjectResearchFormDraft {
  form_key: string
  name: string
  description: string
  subject_type: ResearchSubjectType
  module_key: string | null
  sections: Array<{
    section_key: string
    name: string
    description: string
    fields: Array<{
      field_key: string
      name: string
      help_text: string
      type: ResearchFieldType
      is_required: boolean
      options: ResearchFieldOptionsDto
      condition?: ResearchConditionDto
    }>
  }>
}

interface ProjectResearchFormBuilderProps {
  projectId: string
  subject: ResearchSubjectDto
  initialForm?: ProjectResearchFormDraft | null
  editingForm?: ProjectResearchFormDto | null
  apiRequest<T>(path: string, options: RendererApiRequestOptions): Promise<T>
  onAIGenerate?(): void
  onCreated(form: ProjectResearchFormDto): void
  onCancel(): void
  onDirtyChange?(dirty: boolean): void
}

let builderSequence = 0

function nextBuilderId(prefix: string): string {
  builderSequence += 1
  return `${prefix}-local-${builderSequence}`
}

function defaultOptions(type: ResearchFieldType): ResearchFieldOptionsDto {
  if (type === "single_choice" || type === "multi_choice") return { choices: ["选项 1"] }
  if (type === "file_reference") return { max_files: 1 }
  if (type === "table") return { columns: [] }
  return {}
}

function fieldTypeLabel(type: ResearchFieldType): string {
  return {
    short_text: "短文本",
    long_text: "长文本",
    rich_text: "富文本",
    integer: "整数",
    decimal: "小数",
    date: "日期",
    single_choice: "单选",
    multi_choice: "多选",
    table: "表格",
    file_reference: "文件引用",
  }[type]
}

export function ProjectResearchFormBuilder({ projectId, subject, initialForm, editingForm, apiRequest, onAIGenerate, onCreated, onCancel, onDirtyChange }: ProjectResearchFormBuilderProps) {
  const [name, setName] = useState(initialForm?.name ?? "")
  const [formKey, setFormKey] = useState(initialForm?.form_key ?? "")
  const [description, setDescription] = useState(initialForm?.description ?? "")
  const [subjectType, setSubjectType] = useState<ResearchSubjectType>(initialForm?.subject_type ?? subject.subject_type)
  const [sections, setSections] = useState<BuilderSection[]>(() => initialForm?.sections.map((section) => ({
    clientId: nextBuilderId("section"),
    lockedKey: true,
    sectionKey: section.section_key,
    name: section.name,
    description: section.description,
    fields: section.fields.map((field) => ({
      clientId: nextBuilderId("field"),
      lockedKey: true,
      fieldKey: field.field_key,
      name: field.name,
      helpText: field.help_text,
      type: field.type,
      options: field.options,
      condition: field.condition,
    })),
  })) ?? [])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const nameId = useId()
  const keyId = useId()
  const subjectId = useId()
  const descriptionId = useId()
  const draftSnapshot = JSON.stringify({ name, formKey, description, subjectType, sections })
  const initialSnapshot = useRef(draftSnapshot)
  const dirty = draftSnapshot !== initialSnapshot.current || Boolean(initialForm && !editingForm)
  const dirtyChange = useRef(onDirtyChange)
  dirtyChange.current = onDirtyChange
  useEffect(() => { dirtyChange.current?.(dirty) }, [dirty])
  useEffect(() => () => dirtyChange.current?.(false), [])

  function addSection(): void {
    setSections((current) => [...current, { clientId: nextBuilderId("section"), lockedKey: false, sectionKey: "", name: "", description: "", fields: [] }])
  }

  function removeSection(clientId: string): void {
    setSections((current) => current.filter((section) => section.clientId !== clientId))
  }

  function updateSection(clientId: string, changes: Partial<BuilderSection>): void {
    setSections((current) => current.map((section) => section.clientId === clientId ? { ...section, ...changes } : section))
  }

  function addField(sectionId: string): void {
    setSections((current) => current.map((section) => section.clientId !== sectionId ? section : {
      ...section,
      fields: [...section.fields, { clientId: nextBuilderId("field"), lockedKey: false, fieldKey: "", name: "", helpText: "", type: "short_text", options: {} }],
    }))
  }

  function removeField(sectionId: string, fieldId: string): void {
    setSections((current) => current.map((section) => section.clientId !== sectionId ? section : {
      ...section,
      fields: section.fields.filter((field) => field.clientId !== fieldId),
    }))
  }

  function updateField(sectionId: string, fieldId: string, changes: Partial<BuilderField>): void {
    setSections((current) => current.map((section) => section.clientId !== sectionId ? section : {
      ...section,
      fields: section.fields.map((field) => field.clientId === fieldId ? { ...field, ...changes } : field),
    }))
  }

  function validationMessage(): string {
    if (!name.trim()) return "请填写调研表名称。"
    if (!/^[a-z][a-z0-9_]*$/.test(formKey.trim())) return "稳定标识只能使用小写英文、数字或下划线。"
    if (subjectType !== subject.subject_type) return `调研主体必须与当前对象类型（${RESEARCH_SUBJECT_LABELS[subject.subject_type]}）一致。`
    if (!sections.length) return "请至少添加一个章节。"
    const fieldKeys = new Set<string>()
    for (const [index, section] of sections.entries()) {
      if (!section.name.trim() || !/^[a-z][a-z0-9_]*$/.test(section.sectionKey.trim())) return `第 ${index + 1} 个章节：章节名称和稳定标识不能为空。`
      for (const field of section.fields) {
        if (!field.name.trim() || !/^[a-z][a-z0-9_]*$/.test(field.fieldKey.trim())) return `第 ${index + 1} 个章节：字段名称和稳定标识不能为空。`
        if (fieldKeys.has(field.fieldKey.trim())) return `第 ${index + 1} 个章节：字段稳定标识必须唯一。`
        fieldKeys.add(field.fieldKey.trim())
      }
    }
    return ""
  }

  async function save(): Promise<void> {
    const validation = validationMessage()
    if (validation) { setError(validation); return }
    setBusy(true)
    setError("")
    setNotice("")
    try {
      const value = await apiRequest<unknown>(editingForm
        ? `/api/v1/projects/${encodeURIComponent(projectId)}/research/forms/${encodeURIComponent(editingForm.id)}/definition`
        : `/api/v1/projects/${encodeURIComponent(projectId)}/research/forms`, {
        method: editingForm ? "PATCH" : "POST",
        body: {
          ...(editingForm ? { version: editingForm.current_revision?.version } : { subject_id: subject.id }),
          form_key: formKey.trim(),
          name: name.trim(),
          description: description.trim(),
          subject_type: subjectType,
          module_key: null,
          sort_order: 0,
          sections: sections.map((section, sectionIndex) => ({
            section_key: section.sectionKey.trim(),
            name: section.name.trim(),
            description: section.description.trim(),
            sort_order: (sectionIndex + 1) * 10,
            fields: section.fields.map((field, fieldIndex) => ({
              field_key: field.fieldKey.trim(),
              name: field.name.trim(),
              help_text: field.helpText.trim(),
              type: field.type,
              is_required: false,
              options: field.options,
              sort_order: (fieldIndex + 1) * 10,
              ...(field.condition ? { condition: field.condition } : {}),
            })),
          })),
        },
      })
      if (!isProjectResearchFormDto(value)) throw new Error("invalid project research form")
      setNotice(editingForm ? "调研表结构已更新。" : "调研表已创建。")
      onCreated(value)
    } catch (caught) {
      setError(builderError(caught))
    } finally {
      setBusy(false)
    }
  }

  return <section className="panel research-definition-editor" aria-labelledby="builder-title" data-research-dirty={dirty ? "true" : undefined}>
    <div className="panel-heading"><div><h2 id="builder-title">{editingForm ? "修改调研表结构" : "新增调研表"}</h2><p className="supporting-copy">{editingForm ? "可随时增加章节、问题或选项；稳定标识不变的已填内容会保留。" : "为当前对象新增一份调研表，并配置章节与字段。"}</p></div>{!editingForm && onAIGenerate ? <button className="primary-button compact ai-assist-button" type="button" disabled={busy} onClick={onAIGenerate}>AI 辅助生成</button> : null}</div>
    {error ? <p className="form-error banner" role="alert">{error}</p> : null}
    {notice ? <p className="notice" role="status">{notice}</p> : null}
    <fieldset className="research-form-card" disabled={busy}>
      <div className="research-form-grid">
        <div className="field"><label htmlFor={nameId}>调研表名称</label><input id={nameId} value={name} onChange={(event) => setName(event.target.value)} /></div>
        <div className="field"><label htmlFor={keyId}>稳定标识</label><input id={keyId} value={formKey} disabled={Boolean(editingForm)} onChange={(event) => setFormKey(event.target.value)} /></div>
        <div className="field"><label htmlFor={subjectId}>调研主体</label><select id={subjectId} value={subjectType} disabled={Boolean(editingForm)} onChange={(event) => setSubjectType(event.target.value as ResearchSubjectType)}>{RESEARCH_SUBJECT_TYPES.map((subject) => <option value={subject} key={subject}>{RESEARCH_SUBJECT_LABELS[subject]}</option>)}</select></div>
        <div className="field"><label htmlFor={descriptionId}>说明</label><textarea id={descriptionId} rows={2} value={description} onChange={(event) => setDescription(event.target.value)} /></div>
      </div>
      <div className="research-section-list">
        {sections.map((section, sectionIndex) => {
          const sectionPrefix = `章节 ${sectionIndex + 1}`
          return <fieldset className="research-section-card" key={section.clientId} disabled={busy}>
            <div className="research-card-head">
              <div className="research-card-title"><span className="sequence-label">{sectionPrefix}</span><h4 className="research-card-name">{section.name || "未命名章节"}</h4></div>
              <button className="danger-button compact" type="button" onClick={() => removeSection(section.clientId)}>移除{sectionPrefix}</button>
            </div>
            <div className="research-form-grid">
              <label className="field"><span>章节标题</span><input value={section.name} onChange={(event) => updateSection(section.clientId, { name: event.target.value })} /></label>
              <label className="field"><span>章节稳定标识</span><input value={section.sectionKey} disabled={Boolean(editingForm && section.lockedKey)} onChange={(event) => updateSection(section.clientId, { sectionKey: event.target.value })} /></label>
              <label className="field"><span>章节说明</span><textarea rows={2} value={section.description} onChange={(event) => updateSection(section.clientId, { description: event.target.value })} /></label>
            </div>
            <div className="research-field-list">
              {section.fields.map((field, fieldIndex) => {
                const fieldPrefix = `${sectionPrefix} 字段 ${fieldIndex + 1}`
                return <fieldset className="research-field-card" key={field.clientId} disabled={busy}>
                  <div className="research-card-head">
                    <div className="research-card-title"><span className="sequence-label">{fieldPrefix}</span><span className="research-card-name">{field.name || "未命名字段"}</span></div>
                    <button className="danger-button compact" type="button" onClick={() => removeField(section.clientId, field.clientId)}>移除{fieldPrefix}</button>
                  </div>
                  <div className="research-field-grid">
                    <label className="field"><span>字段标签</span><input value={field.name} onChange={(event) => updateField(section.clientId, field.clientId, { name: event.target.value })} /></label>
                    <label className="field"><span>字段稳定标识</span><input value={field.fieldKey} disabled={Boolean(editingForm && field.lockedKey)} onChange={(event) => updateField(section.clientId, field.clientId, { fieldKey: event.target.value })} /></label>
                    <label className="field"><span>字段类型</span><select value={field.type} onChange={(event) => { const type = event.target.value as ResearchFieldType; updateField(section.clientId, field.clientId, { type, options: defaultOptions(type) }) }}>{RESEARCH_FIELD_TYPES.map((type) => <option value={type} key={type}>{fieldTypeLabel(type)}</option>)}</select></label>
                    <label className="field"><span>帮助文字</span><textarea rows={2} value={field.helpText} onChange={(event) => updateField(section.clientId, field.clientId, { helpText: event.target.value })} /></label>
                  </div>
                  {field.type === "single_choice" || field.type === "multi_choice" ? <ChoiceOptionsEditor prefix={fieldPrefix} type={field.type} options={field.options} onChange={(options) => updateField(section.clientId, field.clientId, { options })} /> : null}
                </fieldset>
              })}
            </div>
            <button className="research-add-button" type="button" onClick={() => addField(section.clientId)}><svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M8 2v12M2 8h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>在{sectionPrefix} 中新增字段</button>
          </fieldset>
        })}
      </div>
      <button className="research-add-button" type="button" onClick={addSection}><svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M8 2v12M2 8h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>新增章节</button>
      <div className="research-editor-actions">
        <button className="secondary-button" type="button" disabled={busy} onClick={onCancel}>取消</button>
        <button className="primary-button" type="button" disabled={busy} onClick={() => void save()}>{busy ? "正在保存" : editingForm ? "保存结构" : "创建调研表"}</button>
      </div>
    </fieldset>
  </section>
}

function ChoiceOptionsEditor({ prefix, type, options, onChange }: {
  prefix: string
  type: "single_choice" | "multi_choice"
  options: ResearchFieldOptionsDto
  onChange(options: ResearchFieldOptionsDto): void
}) {
  const choices = ("choices" in options && Array.isArray(options.choices) ? options.choices.filter((item): item is string => typeof item === "string") : [])
  const [defaultValue, setDefaultValue] = useState<string>(() => {
    const value = ("default_value" in options ? options.default_value : undefined)
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string").join("\n") : typeof value === "string" ? value : ""
  })
  return <div className="research-options-grid">
    <div className="field"><label>{prefix} 选项（每行一个）</label><textarea rows={3} value={choices.join("\n")} onChange={(event) => onChange({ ...options, choices: event.target.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean) })} /></div>
    <div className="field"><label>{prefix} 默认选项（每行一个）</label><textarea rows={3} value={defaultValue} onChange={(event) => {
      setDefaultValue(event.target.value)
      onChange(type === "multi_choice"
        ? { choices, default_value: event.target.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean) }
        : { choices, default_value: event.target.value })
    }} /></div>
  </div>
}

function builderError(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (error.code === "invalid_research_definition") return "调研表定义不符合要求，请检查名称、稳定标识、章节与字段配置。"
    if (error.code === "research_form_subject_type_mismatch") return "调研主体必须与当前对象类型一致。"
    if (error.code === "research_form_conflict") return "该对象已存在相同稳定标识的调研表。"
    if (error.code === "forbidden") return "你没有权限为该对象新增调研表。"
  }
  return "调研表操作失败，请稍后重试。"
}
