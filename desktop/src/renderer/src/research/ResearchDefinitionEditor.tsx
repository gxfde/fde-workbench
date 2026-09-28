import {
  forwardRef,
  useEffect,
  useId,
  useImperativeHandle,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from "react"

import { ApiClientError } from "../api/client"
import { useAIExecution } from "../ai/AIExecutionProvider"
import { useAuth } from "../auth/AuthProvider"
import { isResearchConditionDto, isResearchDefinitionDto } from "./runtimeValidation"
import {
  hasConditionalDependencyCycle,
  isCanonicalConditionText,
  isCanonicalDecimalValue,
  normalizeAsciiEdgeWhitespace,
  normalizeDecimalValue,
} from "./conditionValueContract"
import {
  RESEARCH_FIELD_TYPES,
  RESEARCH_SUBJECT_TYPES,
  type ResearchConditionDto,
  type ResearchDefinitionDto,
  type ResearchFieldDto,
  type ResearchFieldOptionsDto,
  type ResearchFieldType,
  type ResearchFormDto,
  type ResearchSectionDto,
  type ResearchSubjectType,
  type ResearchTableColumnDto,
  type ResearchTableColumnOptionsDto,
  type ResearchTableColumnType,
} from "./types"

export interface ResearchDefinitionEditorHandle {
  isReady(): boolean
  preflight(): ResearchDefinitionPreflight
  adoptAggregateVersion(expectedVersion: number, newVersion: number): void
  save(expectedVersion?: number, prepared?: ResearchDefinitionPreflight): Promise<ResearchDefinitionDto>
}

export interface ResearchDefinitionPreflight {
  forms: ResearchFormInput[]
  dirty: boolean
}

type ResearchFieldInput = Omit<ResearchFieldDto, "id"> & { id?: string }
type ResearchSectionInput = Omit<ResearchSectionDto, "id" | "fields"> & { id?: string; fields: ResearchFieldInput[] }
type ResearchFormInput = Omit<ResearchFormDto, "id" | "sections"> & { id?: string; sections: ResearchSectionInput[] }

interface EditableField {
  clientId: string
  serverId?: string
  fieldKey: string
  name: string
  helpText: string
  type: ResearchFieldType
  required: boolean
  options: ResearchFieldOptionsDto
  condition?: ResearchConditionDto
}

interface EditableSection {
  clientId: string
  serverId?: string
  sectionKey: string
  name: string
  description: string
  fields: EditableField[]
}

interface EditableForm {
  clientId: string
  serverId?: string
  formKey: string
  name: string
  description: string
  subjectType: ResearchSubjectType
  moduleKey: string | null
  sections: EditableSection[]
}

interface ConditionField {
  key: string
  type: ResearchFieldType
  options: ResearchFieldOptionsDto
}

interface EditorProps {
  templateId: string
  versionId: string
  version: number
  moduleKeys: string[]
  disabled?: boolean
  onLoadedVersion?(version: number): void
  onVersionChange(version: number): void
  onStale?(): void
  onPublish?(): void
}

let researchEditorSequence = 0

export const ResearchDefinitionEditor = forwardRef<ResearchDefinitionEditorHandle, EditorProps>(
  function ResearchDefinitionEditor({
    templateId,
    versionId,
    version,
    moduleKeys,
    disabled = false,
    onLoadedVersion,
    onVersionChange,
    onStale,
    onPublish,
  }, ref) {
    const { apiRequest, status } = useAuth()
    const { runAI } = useAIExecution()
    const [forms, setForms] = useState<EditableForm[]>([])
    const [loading, setLoading] = useState(true)
    const [ready, setReady] = useState(false)
    const [loadedVersion, setLoadedVersion] = useState<number | null>(null)
    const [saving, setSaving] = useState(false)
    const [notice, setNotice] = useState("")
    const [error, setError] = useState("")
    const [aiOpen, setAIOpen] = useState(false)
    const [aiRequirement, setAIRequirement] = useState("")
    const [aiBusy, setAIBusy] = useState(false)
    const [aiError, setAIError] = useState("")
    const versionRef = useRef(version)
    const onVersionChangeRef = useRef(onVersionChange)
    const onLoadedVersionRef = useRef(onLoadedVersion)
    const onStaleRef = useRef(onStale)
    const baselineSignatureRef = useRef<string | null>(null)
    const importJsonInputRef = useRef<HTMLInputElement>(null)

    useEffect(() => {
      versionRef.current = version
    }, [version])

    useEffect(() => {
      onVersionChangeRef.current = onVersionChange
    }, [onVersionChange])

    useEffect(() => {
      onLoadedVersionRef.current = onLoadedVersion
    }, [onLoadedVersion])

    useEffect(() => {
      onStaleRef.current = onStale
    }, [onStale])

    useEffect(() => {
      if (status !== "authenticated") return
      let active = true
      setLoading(true)
      setReady(false)
      setError("")
      const requestedVersion = versionRef.current
      void apiRequest<unknown>(researchPath(templateId, versionId), { method: "GET" })
        .then((value) => {
          if (!active) return
          if (!isResearchDefinitionDto(value)) {
            setError("服务器返回的调研模板数据格式无效。")
            return
          }
          if (requestedVersion < versionRef.current && value.version < versionRef.current) return
          versionRef.current = value.version
          setLoadedVersion(value.version)
          const loadedForms = value.forms.map(formFromDto)
          baselineSignatureRef.current = serializedFormsSignature(loadedForms)
          setForms(loadedForms)
          setReady(true)
          onLoadedVersionRef.current?.(value.version)
        })
        .catch((caught) => {
          if (active) setError(researchDefinitionErrorMessage(caught))
        })
        .finally(() => {
          if (active) setLoading(false)
        })
      return () => {
        active = false
      }
    }, [apiRequest, status, templateId, versionId])

    function preflightDefinition(): ResearchDefinitionPreflight {
      if (!ready || loadedVersion !== version) throw new InvalidResearchResponseError()
      const validationMessage = researchClientValidationMessage(forms, moduleKeys)
      if (validationMessage) throw new ResearchEditorValidationError(validationMessage)
      const serializedForms = forms.map((form, formIndex) => serializeForm(form, formIndex))
      return {
        forms: serializedForms,
        dirty: JSON.stringify(serializedForms) !== baselineSignatureRef.current,
      }
    }

    async function saveDefinition(
      expectedVersion = versionRef.current,
      prepared = preflightDefinition(),
    ): Promise<ResearchDefinitionDto> {
      const explicitlyCoordinated = expectedVersion !== versionRef.current
      if (!ready || (!explicitlyCoordinated && loadedVersion !== version)) throw new InvalidResearchResponseError()
      if (!prepared.dirty) {
        setNotice("调研模板没有未保存修改")
        const unchanged = { version: loadedVersion ?? versionRef.current, forms: prepared.forms }
        if (!isResearchDefinitionDto(unchanged)) throw new InvalidResearchResponseError()
        return unchanged
      }
      setSaving(true)
      setNotice("")
      setError("")
      try {
        const value = await apiRequest<unknown>(researchPath(templateId, versionId), {
          method: "PUT",
          body: {
            version: expectedVersion,
            forms: prepared.forms,
          },
        })
        if (!isResearchDefinitionDto(value)) {
          throw new InvalidResearchResponseError()
        }
        versionRef.current = value.version
        setLoadedVersion(value.version)
        const savedForms = value.forms.map(formFromDto)
        baselineSignatureRef.current = serializedFormsSignature(savedForms)
        setForms(savedForms)
        onVersionChangeRef.current(value.version)
        setNotice("调研模板已保存")
        return value
      } catch (caught) {
        if (caught instanceof ApiClientError && caught.code === "stale_version") onStaleRef.current?.()
        setError(researchDefinitionErrorMessage(caught))
        throw caught
      } finally {
        setSaving(false)
      }
    }

    function adoptAggregateVersion(expectedVersion: number, newVersion: number): void {
      const currentSignature = serializedFormsSignature(forms)
      if (!ready
        || loadedVersion !== expectedVersion
        || newVersion < expectedVersion
        || currentSignature !== baselineSignatureRef.current) {
        throw new InvalidResearchResponseError()
      }
      versionRef.current = newVersion
      setLoadedVersion(newVersion)
    }

    useImperativeHandle(ref, () => ({
      isReady: () => ready && loadedVersion === version,
      preflight: preflightDefinition,
      adoptAggregateVersion,
      save: saveDefinition,
    }))

    function updateForm(clientId: string, changes: Partial<EditableForm>): void {
      setForms((current) => current.map((form) => form.clientId === clientId ? { ...form, ...changes } : form))
    }

    function addForm(): void {
      setForms((current) => [...current, {
        clientId: nextResearchId("form"),
        formKey: "",
        name: "",
        description: "",
        subjectType: "project",
        moduleKey: null,
        sections: [],
      }])
    }

    async function generateFormWithAI(): Promise<void> {
      if (aiBusy) return
      setAIBusy(true)
      setAIError("")
      try {
        const value = await runAI<unknown>({ operation: "industry_research_form_generate", title: "AI 正在生成模板调研表", payload: {
            template_id: templateId,
            version_id: versionId,
            requirement: aiRequirement.trim(),
            existing_forms: forms.map((form) => ({
              form_key: form.formKey.trim(),
              name: form.name.trim(),
              subject_type: form.subjectType,
            })),
          } })
        const generated = importableForm(value)
        if (!generated) throw new Error("invalid_ai_research_form")
        setForms((current) => [...current, generated])
        setAIOpen(false)
        setAIRequirement("")
        setNotice("AI 已生成调研表，请检查修改后保存。")
        setError("")
      } catch (caught) {
        setAIError(aiResearchFormErrorMessage(caught))
      } finally {
        setAIBusy(false)
      }
    }

    function addSection(formId: string): void {
      setForms((current) => current.map((form) => form.clientId !== formId ? form : {
        ...form,
        sections: [...form.sections, {
          clientId: nextResearchId("section"),
          sectionKey: "",
          name: "",
          description: "",
          fields: [],
        }],
      }))
    }

    function updateSection(formId: string, sectionId: string, changes: Partial<EditableSection>): void {
      setForms((current) => current.map((form) => form.clientId !== formId ? form : {
        ...form,
        sections: form.sections.map((section) => section.clientId === sectionId ? { ...section, ...changes } : section),
      }))
    }

    function addField(formId: string, sectionId: string): void {
      setForms((current) => current.map((form) => form.clientId !== formId ? form : {
        ...form,
        sections: form.sections.map((section) => section.clientId !== sectionId ? section : {
          ...section,
          fields: [...section.fields, {
            clientId: nextResearchId("field"),
            fieldKey: "",
            name: "",
            helpText: "",
            type: "short_text",
            required: false,
            options: {},
          }],
        }),
      }))
    }

    function updateField(formId: string, sectionId: string, fieldId: string, changes: Partial<EditableField>): void {
      setForms((current) => current.map((form) => form.clientId !== formId ? form : {
        ...form,
        sections: form.sections.map((section) => section.clientId !== sectionId ? section : {
          ...section,
          fields: section.fields.map((field) => field.clientId === fieldId ? { ...field, ...changes } : field),
        }),
      }))
    }

    function moveForm(index: number, direction: -1 | 1): void {
      setForms((current) => moved(current, index, direction))
    }

    function moveSection(formId: string, index: number, direction: -1 | 1): void {
      setForms((current) => current.map((form) => form.clientId !== formId ? form : {
        ...form,
        sections: moved(form.sections, index, direction),
      }))
    }

    function moveField(formId: string, sectionId: string, index: number, direction: -1 | 1): void {
      setForms((current) => current.map((form) => form.clientId !== formId ? form : {
        ...form,
        sections: form.sections.map((section) => section.clientId !== sectionId ? section : {
          ...section,
          fields: moved(section.fields, index, direction),
        }),
      }))
    }

    function exportJson(): void {
      const payload = { forms: forms.map(serializeEditableForm) }
      const json = JSON.stringify(payload, null, 2)
      const blob = new Blob([json], { type: "application/json" })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = `${researchExportFileName(forms)}.json`
      anchor.rel = "noopener"
      document.body.appendChild(anchor)
      anchor.click()
      document.body.removeChild(anchor)
      setTimeout(() => URL.revokeObjectURL(url), 0)
    }

    function handleImportFile(event: ChangeEvent<HTMLInputElement>): void {
      const input = event.target
      const file = input.files?.[0]
      if (!file) return
      const reader = new FileReader()
      reader.onerror = () => setError("读取导入文件失败，请重试。")
      reader.onload = () => {
        if (typeof reader.result !== "string") {
          setError("读取导入文件失败，请重试。")
          return
        }
        let parsed: unknown
        try {
          parsed = JSON.parse(reader.result)
        } catch {
          setError("导入的 JSON 文件格式无效：无法解析 JSON。")
          return
        }
        const imported = parseEditableDefinition(parsed)
        if (!imported) {
          setError("导入的 JSON 不是有效的调研定义：需要包含 forms/sections/fields 结构。")
          return
        }
        if (!window.confirm("导入 JSON 将替换当前调研定义，未保存修改会丢失。是否继续？")) return
        setForms(imported)
        setError("")
        setNotice("已导入调研定义，请核对后再保存。")
      }
      reader.readAsText(file)
      input.value = ""
    }

    const busy = disabled || loading || saving || aiBusy || !ready || loadedVersion !== version
    const clientValidationMessage = researchClientValidationMessage(forms, moduleKeys)

    return (
      <section className="research-definition-editor" aria-labelledby="research-definition-title">
        <div className="panel-heading research-definition-heading">
          <div>
            <h2 id="research-definition-title">调研表</h2>
            <p className="supporting-copy compact-copy">调研表会随当前模板版本发布；稳定标识在保存后不应更改。</p>
          </div>
          <div className="research-definition-toolbar">
            <button id="research-export-json" className="secondary-button" type="button" disabled={busy} onClick={exportJson}>导出 JSON</button>
            <button id="research-import-json" className="secondary-button" type="button" disabled={busy} onClick={() => importJsonInputRef.current?.click()}>导入 JSON</button>
            <button id="research-ai-generate-form" className="primary-button ai-assist-button" type="button" disabled={busy} onClick={() => { setAIError(""); setAIOpen(true) }}>AI 辅助生成</button>
            <button id="research-add-form" className="primary-button" type="button" disabled={busy} onClick={addForm}>新增调研表</button>
            <input ref={importJsonInputRef} className="file-input-hidden" type="file" accept="application/json,.json" aria-label="导入调研定义 JSON 文件" onChange={handleImportFile} />
          </div>
        </div>

        {loading ? <p role="status">正在加载调研模板…</p> : null}
        {notice ? <p className="notice" role="status">{notice}</p> : null}
        {error || clientValidationMessage ? <p className="form-error banner" role="alert">{error || clientValidationMessage}</p> : null}
        {!loading && forms.length === 0 ? <p className="empty-state">暂无调研表</p> : null}

        <div className="research-form-list">
          {forms.map((form, formIndex) => {
            const formPrefix = `表单 ${formIndex + 1}`
            const availableFields = form.sections.flatMap((section) => section.fields.map((field): ConditionField => ({
              key: field.fieldKey,
              type: field.type,
              options: field.options,
            }))).filter((field) => Boolean(field.key))
            return (
              <fieldset className="research-form-card" key={form.clientId} disabled={busy}>
                <div className="research-card-head">
                  <div className="research-card-title">
                    <span className="sequence-label">{formPrefix}</span>
                    <h3 className="research-card-name">{form.name || "未命名调研表"}</h3>
                    <code className="research-card-key">{form.formKey || "待填写稳定标识"}</code>
                    <span className="research-card-count">{form.sections.length} 个章节</span>
                  </div>
                  <OrderActions
                    label={formPrefix}
                    index={formIndex}
                    length={forms.length}
                    removeId={removeControlId("form", form.clientId)}
                    focusAfterRemoveId={forms[formIndex + 1]
                      ? removeControlId("form", forms[formIndex + 1].clientId)
                      : forms[formIndex - 1]
                        ? removeControlId("form", forms[formIndex - 1].clientId)
                        : "research-add-form"}
                    onMove={(direction) => moveForm(formIndex, direction)}
                    onRemove={() => setForms((current) => current.filter((item) => item.clientId !== form.clientId))}
                  />
                </div>
                <div className="research-form-grid">
                  <Field label={`${formPrefix} 名称`} id={`research-form-name-${form.clientId}`}>
                    <input id={`research-form-name-${form.clientId}`} value={form.name} onChange={(event) => updateForm(form.clientId, { name: event.target.value })} />
                  </Field>
                  <Field label={`${formPrefix} 稳定标识`} id={`research-form-key-${form.clientId}`}>
                    <input id={`research-form-key-${form.clientId}`} value={form.formKey} disabled={Boolean(form.serverId)} onChange={(event) => updateForm(form.clientId, { formKey: event.target.value })} />
                  </Field>
                  <Field label={`${formPrefix} 调研主体`} id={`research-form-subject-${form.clientId}`}>
                    <select id={`research-form-subject-${form.clientId}`} value={form.subjectType} onChange={(event) => updateForm(form.clientId, { subjectType: event.target.value as ResearchSubjectType })}>
                      {RESEARCH_SUBJECT_TYPES.map((subject) => <option value={subject} key={subject}>{subjectLabel(subject)}</option>)}
                    </select>
                  </Field>
                  <Field label={`${formPrefix} 所属模块`} id={`research-form-module-${form.clientId}`}>
                    <select id={`research-form-module-${form.clientId}`} value={form.moduleKey ?? ""} onChange={(event) => updateForm(form.clientId, { moduleKey: event.target.value || null })}>
                      <option value="">不限定模块</option>
                      {moduleKeys.map((key) => <option value={key} key={key}>{key}</option>)}
                    </select>
                  </Field>
                  <Field label={`${formPrefix} 说明`} id={`research-form-description-${form.clientId}`}>
                    <textarea id={`research-form-description-${form.clientId}`} rows={2} value={form.description} onChange={(event) => updateForm(form.clientId, { description: event.target.value })} />
                  </Field>
                </div>
                <div className="research-section-list">
                  {form.sections.map((section, sectionIndex) => {
                    const sectionPrefix = `${formPrefix} 章节 ${sectionIndex + 1}`
                    return (
                      <fieldset className="research-section-card" key={section.clientId}>
                        <div className="research-card-head research-section-head">
                          <div className="research-card-title">
                            <span className="sequence-label">{sectionPrefix}</span>
                            <h4 className="research-card-name">{section.name || "未命名章节"}</h4>
                            <code className="research-card-key">{section.sectionKey || "待填写稳定标识"}</code>
                          </div>
                          <OrderActions
                            label={sectionPrefix}
                            index={sectionIndex}
                            length={form.sections.length}
                            removeId={removeControlId("section", section.clientId)}
                            focusAfterRemoveId={form.sections[sectionIndex + 1]
                              ? removeControlId("section", form.sections[sectionIndex + 1].clientId)
                              : form.sections[sectionIndex - 1]
                                ? removeControlId("section", form.sections[sectionIndex - 1].clientId)
                                : addControlId("section", form.clientId)}
                            onMove={(direction) => moveSection(form.clientId, sectionIndex, direction)}
                            onRemove={() => updateForm(form.clientId, { sections: form.sections.filter((item) => item.clientId !== section.clientId) })}
                          />
                        </div>
                        <div className="research-form-grid">
                          <Field label={`${sectionPrefix} 标题`} id={`research-section-name-${section.clientId}`}>
                            <input id={`research-section-name-${section.clientId}`} value={section.name} onChange={(event) => updateSection(form.clientId, section.clientId, { name: event.target.value })} />
                          </Field>
                          <Field label={`${sectionPrefix} 稳定标识`} id={`research-section-key-${section.clientId}`}>
                            <input id={`research-section-key-${section.clientId}`} value={section.sectionKey} disabled={Boolean(section.serverId)} onChange={(event) => updateSection(form.clientId, section.clientId, { sectionKey: event.target.value })} />
                          </Field>
                          <Field label={`${sectionPrefix} 说明`} id={`research-section-description-${section.clientId}`}>
                            <textarea id={`research-section-description-${section.clientId}`} rows={2} value={section.description} onChange={(event) => updateSection(form.clientId, section.clientId, { description: event.target.value })} />
                          </Field>
                        </div>
                        <div className="research-field-list">
                          {section.fields.map((field, fieldIndex) => {
                            const fieldPrefix = `${sectionPrefix} 字段 ${fieldIndex + 1}`
                            return (
                              <fieldset className="research-field-card" key={field.clientId}>
                                <div className="research-card-head research-field-head">
                                  <div className="research-card-title">
                                    <span className="sequence-label">{fieldPrefix}</span>
                                    <span className="research-card-name">{field.name || "未命名字段"}</span>
                                    <code className="research-card-key">{field.fieldKey || "待填写稳定标识"}</code>
                                  </div>
                                  <OrderActions
                                    label={fieldPrefix}
                                    index={fieldIndex}
                                    length={section.fields.length}
                                    removeId={removeControlId("field", field.clientId)}
                                    focusAfterRemoveId={section.fields[fieldIndex + 1]
                                      ? removeControlId("field", section.fields[fieldIndex + 1].clientId)
                                      : section.fields[fieldIndex - 1]
                                        ? removeControlId("field", section.fields[fieldIndex - 1].clientId)
                                        : addControlId("field", section.clientId)}
                                    onMove={(direction) => moveField(form.clientId, section.clientId, fieldIndex, direction)}
                                    onRemove={() => updateSection(form.clientId, section.clientId, { fields: section.fields.filter((item) => item.clientId !== field.clientId) })}
                                  />
                                </div>
                                <div className="research-field-grid">
                                  <Field label={`${fieldPrefix} 标签`} id={`research-field-name-${field.clientId}`}>
                                    <input id={`research-field-name-${field.clientId}`} value={field.name} onChange={(event) => updateField(form.clientId, section.clientId, field.clientId, { name: event.target.value })} />
                                  </Field>
                                  <Field label={`${fieldPrefix} 稳定标识`} id={`research-field-key-${field.clientId}`}>
                                    <input id={`research-field-key-${field.clientId}`} value={field.fieldKey} disabled={Boolean(field.serverId)} onChange={(event) => updateField(form.clientId, section.clientId, field.clientId, { fieldKey: event.target.value })} />
                                  </Field>
                                  <Field label={`${fieldPrefix} 类型`} id={`research-field-type-${field.clientId}`}>
                                    <select id={`research-field-type-${field.clientId}`} value={field.type} onChange={(event) => {
                                      const type = event.target.value as ResearchFieldType
                                      updateField(form.clientId, section.clientId, field.clientId, { type, options: defaultOptions(type) })
                                    }}>
                                      {RESEARCH_FIELD_TYPES.map((type) => <option value={type} key={type}>{fieldTypeLabel(type)}</option>)}
                                    </select>
                                  </Field>
                                  <Field label={`${fieldPrefix} 帮助文字`} id={`research-field-help-${field.clientId}`}>
                                    <textarea id={`research-field-help-${field.clientId}`} rows={2} value={field.helpText} onChange={(event) => updateField(form.clientId, section.clientId, field.clientId, { helpText: event.target.value })} />
                                  </Field>
                                </div>
                                <TypeOptionsEditor
                                  prefix={fieldPrefix}
                                  type={field.type}
                                  options={field.options}
                                  onChange={(options) => updateField(form.clientId, section.clientId, field.clientId, { options })}
                                />
                                <label className="research-check"><input type="checkbox" aria-label={`${fieldPrefix} 启用显示条件`} checked={field.condition !== undefined} onChange={(event) => updateField(form.clientId, section.clientId, field.clientId, { condition: event.target.checked ? defaultCondition() : undefined })} />{fieldPrefix} 启用显示条件</label>
                                {field.condition ? <ConditionEditor prefix={fieldPrefix} condition={field.condition} fields={availableFields} onChange={(condition) => updateField(form.clientId, section.clientId, field.clientId, { condition })} /> : null}
                              </fieldset>
                            )
                          })}
                        </div>
                        <button id={addControlId("field", section.clientId)} className="research-add-button" type="button" onClick={() => addField(form.clientId, section.clientId)}><svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M8 2v12M2 8h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>在{sectionPrefix} 中新增字段</button>
                      </fieldset>
                    )
                  })}
                </div>
                <button id={addControlId("section", form.clientId)} className="research-add-button" type="button" onClick={() => addSection(form.clientId)}><svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M8 2v12M2 8h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>在{formPrefix} 中新增章节</button>
              </fieldset>
            )
          })}
        </div>
        <div className="research-editor-actions">
          <button className="secondary-button" type="button" disabled={busy} onClick={() => void saveDefinition().catch(() => undefined)}>{saving ? "正在保存" : "保存调研模板"}</button>
          {onPublish ? <button className="primary-button" type="button" disabled={busy} onClick={onPublish}>保存并发布调研模板</button> : null}
        </div>
        {aiOpen ? <div className="dialog-backdrop">
          <section className="dialog ai-research-form-dialog" role="dialog" aria-modal="true" aria-labelledby="ai-research-form-title">
            <div className="dialog-heading">
              <div>
                <h3 id="ai-research-form-title">AI 辅助生成调研表</h3>
                <p className="supporting-copy compact-copy">可直接生成，也可说明想调研的对象、目标或业务范围。</p>
              </div>
              <button className="secondary-button compact" type="button" disabled={aiBusy} onClick={() => setAIOpen(false)}>关闭</button>
            </div>
            <div className="field">
              <label htmlFor="ai-research-form-requirement">生成要求（可选）</label>
              <textarea
                id="ai-research-form-requirement"
                rows={5}
                maxLength={4000}
                value={aiRequirement}
                disabled={aiBusy}
                placeholder="例如：生成一份访谈生产部门负责人的调研表，重点了解计划排产、质量异常和数据现状。"
                onChange={(event) => setAIRequirement(event.target.value)}
              />
            </div>
            {aiError ? <p className="form-error banner" role="alert">{aiError}</p> : null}
            <div className="dialog-actions">
              <button className="secondary-button" type="button" disabled={aiBusy} onClick={() => setAIOpen(false)}>取消</button>
              <button className="primary-button" type="button" disabled={aiBusy} onClick={() => void generateFormWithAI()}>{aiBusy ? "正在生成调研表" : "生成调研表"}</button>
            </div>
          </section>
        </div> : null}
      </section>
    )
  },
)

function TypeOptionsEditor({ prefix, type, options, onChange }: {
  prefix: string
  type: ResearchFieldType
  options: ResearchFieldOptionsDto
  onChange(options: ResearchFieldOptionsDto): void
}) {
  const values = options as Record<string, unknown>
  const update = (key: string, value: unknown) => onChange({ ...values, [key]: value } as ResearchFieldOptionsDto)
  if (type === "short_text" || type === "long_text") {
    return <div className="research-options-grid">
      <OptionField label={`${prefix} 占位提示`} value={stringValue(values.placeholder)} onChange={(value) => update("placeholder", value)} />
      <OptionField label={`${prefix} 默认值`} value={stringValue(values.default_value)} onChange={(value) => update("default_value", value)} />
      <NumberOptionField label={`${prefix} 最小长度`} value={numberText(values.min_length)} integer onChange={(value) => update("min_length", value)} />
      <NumberOptionField label={`${prefix} 最大长度`} value={numberText(values.max_length)} integer onChange={(value) => update("max_length", value)} />
    </div>
  }
  if (type === "rich_text") {
    return <div className="research-options-grid">
      <OptionField label={`${prefix} 占位提示`} value={stringValue(values.placeholder)} onChange={(value) => update("placeholder", value)} />
      <OptionField label={`${prefix} 默认值`} value={stringValue(values.default_value)} onChange={(value) => update("default_value", value)} />
    </div>
  }
  if (type === "integer" || type === "decimal") {
    return <div className="research-options-grid">
      <NumberOptionField label={`${prefix} 最小值`} value={numberText(values.minimum)} integer={type === "integer"} onChange={(value) => update("minimum", value)} />
      <NumberOptionField label={`${prefix} 最大值`} value={numberText(values.maximum)} integer={type === "integer"} onChange={(value) => update("maximum", value)} />
      <NumberOptionField label={`${prefix} 默认值`} value={numberText(values.default_value)} integer={type === "integer"} onChange={(value) => update("default_value", value)} />
    </div>
  }
  if (type === "date") {
    return <div className="research-options-grid">
      <OptionField label={`${prefix} 最早日期`} type="date" value={stringValue(values.minimum)} onChange={(value) => update("minimum", value)} />
      <OptionField label={`${prefix} 最晚日期`} type="date" value={stringValue(values.maximum)} onChange={(value) => update("maximum", value)} />
      <OptionField label={`${prefix} 默认日期`} type="date" value={stringValue(values.default_value)} onChange={(value) => update("default_value", value)} />
    </div>
  }
  if (type === "single_choice" || type === "multi_choice") {
    const choices = Array.isArray(values.choices) ? values.choices.filter((value): value is string => typeof value === "string") : []
    const defaultValue = type === "multi_choice" && Array.isArray(values.default_value)
      ? values.default_value.filter((value): value is string => typeof value === "string").join("\n")
      : stringValue(values.default_value)
    return <div className="research-options-grid">
      <TextAreaOption label={`${prefix} 选项（每行一个）`} value={choices.join("\n")} onChange={(value) => update("choices", lines(value))} />
      <TextAreaOption label={`${prefix} 默认选项（每行一个）`} value={defaultValue} onChange={(value) => update("default_value", type === "multi_choice" ? lines(value) : value)} />
    </div>
  }
  if (type === "table") {
    const columns = Array.isArray(values.columns) ? values.columns as ResearchTableColumnDto[] : []
    return <div className="research-table-options">
      {columns.map((column, index) => {
        const columnPrefix = `${prefix} 表格列 ${index + 1}`
        const focusIndex = index < columns.length - 1 ? index : index - 1
        const focusTarget = focusIndex >= 0
          ? columnRemoveControlId(prefix, focusIndex)
          : columnAddControlId(prefix)
        return <fieldset key={index} className="research-column-card">
          <legend>{columnPrefix}</legend>
          <div className="research-options-grid">
            <OptionField label={`${columnPrefix} 标题`} value={column.name} onChange={(value) => updateColumn(columns, index, { name: value }, onChange)} />
            <OptionField label={`${columnPrefix} 稳定标识`} value={column.key} onChange={(value) => updateColumn(columns, index, { key: value }, onChange)} />
            <div className="field"><label htmlFor={`column-type-${safeDomId(prefix)}-${index}`}>{columnPrefix} 类型</label><select id={`column-type-${safeDomId(prefix)}-${index}`} value={column.type ?? "short_text"} onChange={(event) => updateColumn(columns, index, { type: event.target.value as ResearchTableColumnType, options: defaultOptions(event.target.value as ResearchTableColumnType) }, onChange)}>{RESEARCH_FIELD_TYPES.filter((item) => item !== "table" && item !== "file_reference").map((item) => <option value={item} key={item}>{fieldTypeLabel(item)}</option>)}</select></div>
          </div>
          {(column.type === "single_choice" || column.type === "multi_choice") ? <TextAreaOption label={`${columnPrefix} 选项（每行一个）`} value={columnChoices(column).join("\n")} onChange={(value) => updateColumn(columns, index, { options: { choices: lines(value) } }, onChange)} /> : null}
          <button id={columnRemoveControlId(prefix, index)} className="danger-button compact" type="button" onClick={() => {
            onChange({ columns: columns.filter((_item, columnIndex) => columnIndex !== index) })
            focusSoon(focusTarget)
          }}>移除{columnPrefix}</button>
        </fieldset>
      })}
      <button id={columnAddControlId(prefix)} className="secondary-button compact" type="button" onClick={() => onChange({ columns: [...columns, { key: "", name: "", type: "short_text", options: {} }] })}>在{prefix} 中新增表格列</button>
    </div>
  }
  return <NumberOptionField label={`${prefix} 最多文件数`} value={numberText(values.max_files)} integer onChange={(value) => update("max_files", value ?? 1)} />
}

function ConditionEditor({ prefix, condition, fields, onChange }: {
  prefix: string
  condition: ResearchConditionDto
  fields: ConditionField[]
  onChange(condition: ResearchConditionDto): void
}) {
  const group = condition.operator === "all" || condition.operator === "any"
  const operatorId = conditionControlId("operator", prefix)
  const fieldId = conditionControlId("field", prefix)
  const referenced = !group ? fields.find((field) => field.key === condition.field_key) : undefined
  return <fieldset className="research-condition-card">
    <legend>{prefix} 显示条件</legend>
    <div className="research-options-grid">
      <div className="field"><label htmlFor={operatorId}>{conditionLabel(prefix, "运算符")}</label><select id={operatorId} value={condition.operator} onChange={(event) => onChange(conditionForOperator(event.target.value))}>{conditionOperators().map(([value, text]) => <option value={value} key={value}>{text}</option>)}</select></div>
      {!group ? <div className="field"><label htmlFor={fieldId}>{conditionLabel(prefix, "引用字段")}</label><select id={fieldId} value={condition.field_key} onChange={(event) => {
        const field = fields.find((item) => item.key === event.target.value)
        onChange(conditionForField(field, condition.operator))
      }}><option value="">请选择</option>{fields.map((field) => <option value={field.key} key={field.key}>{field.key}</option>)}</select></div> : null}
      {!group && condition.operator !== "is_empty" && referenced ? <ConditionValueEditor prefix={prefix} condition={condition} field={referenced} onChange={onChange} /> : null}
    </div>
    {group ? <div className="research-condition-children">
      {condition.conditions.map((child, index) => {
        const childPrefix = `${prefix} 第 ${index + 1} 个子条件`
        const focusIndex = index < condition.conditions.length - 1 ? index : index - 1
        const focusTarget = focusIndex >= 0
          ? conditionControlId("operator", `${prefix} 第 ${focusIndex + 1} 个子条件`)
          : conditionControlId("add", prefix)
        return <div className="research-condition-child" key={index}>
          <ConditionEditor prefix={childPrefix} condition={child} fields={fields} onChange={(changed) => onChange({ ...condition, conditions: condition.conditions.map((item, childIndex) => childIndex === index ? changed : item) })} />
          <button className="danger-button compact" type="button" aria-label={`移除第 ${index + 1} 个子条件`} onClick={() => {
            onChange({ ...condition, conditions: condition.conditions.filter((_item, childIndex) => childIndex !== index) })
            focusSoon(focusTarget)
          }}>移除子条件</button>
        </div>
      })}
      <button id={conditionControlId("add", prefix)} className="secondary-button compact" type="button" onClick={() => onChange({ ...condition, conditions: [...condition.conditions, defaultCondition()] })}>新增子条件</button>
    </div> : null}
  </fieldset>
}

function ConditionValueEditor({ prefix, condition, field, onChange }: {
  prefix: string
  condition: Extract<ResearchConditionDto, { value: unknown }>
  field: ConditionField
  onChange(condition: ResearchConditionDto): void
}) {
  const id = conditionControlId("value", prefix)
  const label = conditionLabel(prefix, "值")
  if (field.type === "integer") {
    return <div className="field"><label htmlFor={id}>{label}</label><input id={id} type="number" step="1" value={numberText(condition.value)} onChange={(event) => onChange({ ...condition, value: typedIntegerValue(event.target.value) })} /></div>
  }
  if (field.type === "decimal") {
    return <div className="field"><label htmlFor={id}>{label}</label><input id={id} type="text" inputMode="decimal" value={stringValue(condition.value)} onChange={(event) => onChange({ ...condition, value: event.target.value })} onBlur={(event) => onChange({ ...condition, value: normalizeDecimalValue(event.target.value) ?? event.target.value })} /></div>
  }
  if (field.type === "date") {
    return <div className="field"><label htmlFor={id}>{label}</label><input id={id} type="date" value={stringValue(condition.value)} onChange={(event) => onChange({ ...condition, value: event.target.value })} /></div>
  }
  if (field.type === "single_choice" || field.type === "multi_choice") {
    const choices = optionChoices(field.options)
    return <div className="field"><label htmlFor={id}>{label}</label><select id={id} value={stringValue(condition.value)} onChange={(event) => onChange({ ...condition, value: event.target.value })}><option value="">请选择</option>{choices.map((choice) => <option value={choice} key={choice}>{choice}</option>)}</select></div>
  }
  return <div className="field"><label htmlFor={id}>{label}</label><input id={id} value={stringValue(condition.value)} onChange={(event) => onChange({ ...condition, value: event.target.value })} onBlur={(event) => onChange({ ...condition, value: normalizeAsciiEdgeWhitespace(event.target.value) })} /></div>
}

function OrderActions({ label, index, length, removeId, focusAfterRemoveId, onMove, onRemove }: {
  label: string
  index: number
  length: number
  removeId: string
  focusAfterRemoveId: string
  onMove(direction: -1 | 1): void
  onRemove(): void
}) {
  return <div className="research-order-actions">
    <button className="secondary-button compact" type="button" disabled={index === 0} aria-label={`向上移动${label}`} onClick={() => onMove(-1)}>上移</button>
    <button className="secondary-button compact" type="button" disabled={index === length - 1} aria-label={`向下移动${label}`} onClick={() => onMove(1)}>下移</button>
    <button id={removeId} className="danger-button compact" type="button" aria-label={`移除${label}`} onClick={() => {
      onRemove()
      focusSoon(focusAfterRemoveId)
    }}>移除</button>
  </div>
}

function Field({ label, id, children }: { label: string; id: string; children: ReactNode }) {
  return <div className="field"><label htmlFor={id}>{label}</label>{children}</div>
}

function OptionField({ label, value, onChange, type = "text" }: { label: string; value: string; onChange(value: string): void; type?: string }) {
  const id = useId()
  return <div className="field"><label htmlFor={id}>{label}</label><input id={id} type={type} value={value} onChange={(event) => onChange(event.target.value)} /></div>
}

function TextAreaOption({ label, value, onChange }: { label: string; value: string; onChange(value: string): void }) {
  const id = useId()
  return <div className="field"><label htmlFor={id}>{label}</label><textarea id={id} rows={3} value={value} onChange={(event) => onChange(event.target.value)} /></div>
}

function NumberOptionField({ label, value, integer, onChange }: { label: string; value: string; integer: boolean; onChange(value: number | undefined): void }) {
  const id = useId()
  return <div className="field"><label htmlFor={id}>{label}</label><input id={id} type="number" step={integer ? "1" : "any"} value={value} onChange={(event) => onChange(numberValue(event.target.value, integer))} /></div>
}

function formFromDto(form: ResearchFormDto): EditableForm {
  return {
    clientId: `form-${form.id}`,
    serverId: form.id,
    formKey: form.form_key,
    name: form.name,
    description: form.description,
    subjectType: form.subject_type,
    moduleKey: form.module_key,
    sections: form.sections.map(sectionFromDto),
  }
}

function sectionFromDto(section: ResearchSectionDto): EditableSection {
  return {
    clientId: `section-${section.id}`,
    serverId: section.id,
    sectionKey: section.section_key,
    name: section.name,
    description: section.description,
    fields: section.fields.map(fieldFromDto),
  }
}

function fieldFromDto(field: ResearchFieldDto): EditableField {
  return {
    clientId: `field-${field.id}`,
    serverId: field.id,
    fieldKey: field.field_key,
    name: field.name,
    helpText: field.help_text,
    type: field.type,
    required: field.is_required,
    options: field.options,
    condition: field.condition,
  }
}

function serializeForm(form: EditableForm, formIndex: number): ResearchFormInput {
  return withServerId(form.serverId, {
    form_key: form.formKey.trim(),
    name: form.name.trim(),
    description: form.description.trim(),
    subject_type: form.subjectType,
    module_key: form.moduleKey,
    sort_order: (formIndex + 1) * 10,
    sections: form.sections.map((section, sectionIndex) => withServerId(section.serverId, {
      section_key: section.sectionKey.trim(),
      name: section.name.trim(),
      description: section.description.trim(),
      sort_order: (sectionIndex + 1) * 10,
      fields: section.fields.map((field, fieldIndex) => withServerId(field.serverId, {
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
  })
}

function withServerId<T extends object>(serverId: string | undefined, value: T): T & { id?: string } {
  return serverId ? { id: serverId, ...value } : value
}

function serializeEditableForm(form: EditableForm): Record<string, unknown> {
  return {
    form_key: form.formKey,
    name: form.name,
    description: form.description,
    subject_type: form.subjectType,
    module_key: form.moduleKey,
    sections: form.sections.map((section) => ({
      section_key: section.sectionKey,
      name: section.name,
      description: section.description,
      fields: section.fields.map((field) => ({
        field_key: field.fieldKey,
        name: field.name,
        help_text: field.helpText,
        type: field.type,
        is_required: false,
        options: field.options,
        ...(field.condition ? { condition: field.condition } : {}),
      })),
    })),
  }
}

function researchExportFileName(forms: EditableForm[]): string {
  const firstKey = forms.find((form) => Boolean(form.formKey.trim()))?.formKey.trim()
  return firstKey || "research"
}

function aiResearchFormErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError) {
    const messages: Record<string, string> = {
      ai_service_not_configured: "AI 服务尚未配置，请联系管理员。",
      ai_authentication_failed: "AI 服务认证失败，请检查服务端配置。",
      ai_rate_limited: "AI 请求过于频繁，请稍后重试。",
      ai_timeout: "AI 生成超时，请稍后重试。",
      request_timeout: "AI 响应时间较长，请稍后重试。",
      ai_service_unavailable: "暂时无法连接 AI 服务，请稍后重试。",
      ai_output_invalid: "AI 生成的调研表结构不符合要求，请调整描述后重试。",
      template_version_not_found: "当前行业模板版本不存在。",
      template_version_not_editable: "只能为草稿版本生成调研表。",
      network_error: "无法连接本地服务，请确认服务已启动。",
    }
    return messages[error.code] ?? error.message
  }
  return "AI 生成的调研表格式无效，请重试。"
}

function parseEditableDefinition(value: unknown): EditableForm[] | null {
  const rawForms = Array.isArray(value)
    ? value
    : isRecord(value) && Array.isArray(value.forms)
      ? value.forms
      : null
  if (!rawForms) return null
  const forms: EditableForm[] = []
  for (const raw of rawForms) {
    const form = importableForm(raw)
    if (!form) return null
    forms.push(form)
  }
  return forms
}

function importableForm(value: unknown): EditableForm | null {
  if (!isRecord(value)) return null
  const { form_key, name, description, subject_type, module_key, sections } = value
  if (typeof form_key !== "string" || typeof name !== "string" || typeof description !== "string") return null
  if (!importableSubjectType(subject_type)) return null
  if (module_key !== null && module_key !== undefined && typeof module_key !== "string") return null
  if (!Array.isArray(sections)) return null
  const importedSections = sections.map(importableSection)
  if (importedSections.some((section) => section === null)) return null
  return {
    clientId: nextResearchId("form"),
    formKey: form_key,
    name,
    description,
    subjectType: subject_type as ResearchSubjectType,
    moduleKey: typeof module_key === "string" ? module_key : null,
    sections: importedSections as EditableSection[],
  }
}

function importableSection(value: unknown): EditableSection | null {
  if (!isRecord(value)) return null
  const { section_key, name, description, fields } = value
  if (typeof section_key !== "string" || typeof name !== "string" || typeof description !== "string") return null
  if (!Array.isArray(fields)) return null
  const importedFields = fields.map(importableField)
  if (importedFields.some((field) => field === null)) return null
  return {
    clientId: nextResearchId("section"),
    sectionKey: section_key,
    name,
    description,
    fields: importedFields as EditableField[],
  }
}

function importableField(value: unknown): EditableField | null {
  if (!isRecord(value)) return null
  const { field_key, name, help_text, type, is_required, options, condition } = value
  if (typeof field_key !== "string" || typeof name !== "string" || typeof help_text !== "string") return null
  if (!importableFieldType(type)) return null
  if (typeof is_required !== "boolean") return null
  let safeCondition: ResearchConditionDto | undefined
  if (condition !== undefined) {
    if (!isResearchConditionDto(condition)) return null
    safeCondition = condition
  }
  return {
    clientId: nextResearchId("field"),
    fieldKey: field_key,
    name,
    helpText: help_text,
    type: type as ResearchFieldType,
    required: is_required,
    options: isRecord(options) ? options as ResearchFieldOptionsDto : {},
    condition: safeCondition,
  }
}

function importableSubjectType(value: unknown): value is ResearchSubjectType {
  return typeof value === "string" && RESEARCH_SUBJECT_TYPES.some((subject) => subject === value)
}

function importableFieldType(value: unknown): value is ResearchFieldType {
  return typeof value === "string" && RESEARCH_FIELD_TYPES.some((kind) => kind === value)
}

function defaultOptions(type: ResearchTableColumnType): ResearchTableColumnOptionsDto
function defaultOptions(type: ResearchFieldType): ResearchFieldOptionsDto
function defaultOptions(type: ResearchFieldType): ResearchFieldOptionsDto {
  if (type === "single_choice" || type === "multi_choice") return { choices: ["选项 1"] }
  if (type === "table") return { columns: [] }
  if (type === "file_reference") return { max_files: 1 }
  return {}
}

function defaultCondition(): ResearchConditionDto {
  return { field_key: "", operator: "equals", value: "" }
}

function conditionForOperator(operator: string): ResearchConditionDto {
  if (operator === "all" || operator === "any") return { operator, conditions: [defaultCondition()] }
  if (operator === "is_empty") return { field_key: "", operator }
  return { field_key: "", operator: operator as "equals" | "not_equals" | "contains", value: "" }
}

function conditionForField(field: ConditionField | undefined, currentOperator: ResearchConditionDto["operator"]): ResearchConditionDto {
  if (!field) return defaultCondition()
  const allowed = conditionLeafOperators(field.type)
  const operator = allowed.includes(currentOperator as "equals" | "not_equals" | "contains" | "is_empty")
    ? currentOperator as "equals" | "not_equals" | "contains" | "is_empty"
    : allowed[0]
  if (operator === "is_empty") return { field_key: field.key, operator }
  return { field_key: field.key, operator, value: defaultConditionValue(field) }
}

function conditionLeafOperators(type: ResearchFieldType): Array<"equals" | "not_equals" | "contains" | "is_empty"> {
  if (type === "short_text" || type === "long_text") return ["equals", "not_equals", "contains", "is_empty"]
  if (type === "integer" || type === "decimal" || type === "date" || type === "single_choice") return ["equals", "not_equals", "is_empty"]
  if (type === "multi_choice") return ["contains", "is_empty"]
  return ["is_empty"]
}

function defaultConditionValue(field: ConditionField): string | number {
  if (field.type === "integer") return 0
  if (field.type === "decimal") return "0"
  if (field.type === "single_choice" || field.type === "multi_choice") return optionChoices(field.options)[0] ?? ""
  return ""
}

function conditionOperators(): Array<[ResearchConditionDto["operator"], string]> {
  return [["equals", "等于"], ["not_equals", "不等于"], ["contains", "包含"], ["is_empty", "为空"], ["all", "全部满足"], ["any", "任一满足"]]
}

function researchClientValidationMessage(forms: EditableForm[], moduleKeys: string[]): string {
  const formKeys = new Set<string>()
  for (const [formIndex, form] of forms.entries()) {
    if (!form.name.trim() || !validStableKey(form.formKey)) return `第 ${formIndex + 1} 个表单：表单名称和稳定标识不能为空，稳定标识只能使用小写英文、数字或下划线。`
    if (form.name.length > 160 || form.formKey.length > 100) return `第 ${formIndex + 1} 个表单：表单名称或稳定标识过长。`
    if (formKeys.has(form.formKey)) return `第 ${formIndex + 1} 个表单：表单稳定标识必须唯一。`
    formKeys.add(form.formKey)
    if (form.moduleKey !== null && !moduleKeys.includes(form.moduleKey)) return `第 ${formIndex + 1} 个表单：所属模块不存在，请重新选择。`
    const fields = form.sections.flatMap((section) => section.fields)
    const fieldsByKey = new Map(fields.filter((field) => field.fieldKey).map((field) => [field.fieldKey, field]))
    const sectionKeys = new Set<string>()
    const fieldKeys = new Set<string>()
    for (const [sectionIndex, section] of form.sections.entries()) {
      if (!section.name.trim() || !validStableKey(section.sectionKey)) return `第 ${formIndex + 1} 个表单 > 第 ${sectionIndex + 1} 个章节：章节名称和稳定标识不能为空。`
      if (section.name.length > 160 || section.sectionKey.length > 100) return `第 ${formIndex + 1} 个表单 > 第 ${sectionIndex + 1} 个章节：章节名称或稳定标识过长。`
      if (sectionKeys.has(section.sectionKey)) return `第 ${formIndex + 1} 个表单：章节稳定标识必须唯一。`
      sectionKeys.add(section.sectionKey)
      for (const [fieldIndex, field] of section.fields.entries()) {
        if (!field.name.trim() || !validStableKey(field.fieldKey)) return `第 ${formIndex + 1} 个表单 > 第 ${sectionIndex + 1} 个章节 > 第 ${fieldIndex + 1} 个字段：字段名称和稳定标识不能为空。`
        if (field.name.length > 160 || field.fieldKey.length > 100) return `第 ${formIndex + 1} 个表单 > 第 ${sectionIndex + 1} 个章节 > 第 ${fieldIndex + 1} 个字段：字段名称或稳定标识过长。`
        if (fieldKeys.has(field.fieldKey)) return `第 ${formIndex + 1} 个表单：字段稳定标识必须唯一。`
        fieldKeys.add(field.fieldKey)
        const optionIssue = scalarOptionsValidationMessage(field.type, field.options)
        if (optionIssue) return `第 ${formIndex + 1} 个表单 > 第 ${sectionIndex + 1} 个章节 > 第 ${fieldIndex + 1} 个字段：${optionIssue}`
        if (field.type === "single_choice" || field.type === "multi_choice") {
          const choices = optionChoices(field.options)
          if (choices.length === 0 || choices.some((choice) => !choice.trim()) || new Set(choices).size !== choices.length) return `第 ${formIndex + 1} 个表单 > 第 ${sectionIndex + 1} 个章节 > 第 ${fieldIndex + 1} 个字段：选项必须非空且唯一。`
          const defaultValue = (field.options as { default_value?: unknown }).default_value
          const invalidDefault = field.type === "single_choice"
            ? defaultValue !== undefined && (typeof defaultValue !== "string" || !choices.includes(defaultValue))
            : defaultValue !== undefined && (!Array.isArray(defaultValue) || defaultValue.some((item) => typeof item !== "string" || !choices.includes(item)))
          if (invalidDefault) return `第 ${formIndex + 1} 个表单 > 第 ${sectionIndex + 1} 个章节 > 第 ${fieldIndex + 1} 个字段：默认选项必须来自已声明选项。`
        }
        if (field.type === "table") {
          const columns = Array.isArray((field.options as { columns?: unknown }).columns)
            ? (field.options as { columns: ResearchTableColumnDto[] }).columns
            : []
          const seen = new Set<string>()
          for (const [columnIndex, column] of columns.entries()) {
            if (!/^[a-z][a-z0-9_]*$/.test(column.key)) return `第 ${formIndex + 1} 个表单 > 第 ${sectionIndex + 1} 个章节 > 第 ${fieldIndex + 1} 个字段 > 第 ${columnIndex + 1} 个表格列：稳定标识不能为空，且只能使用小写英文、数字或下划线。`
            if (column.key.length > 100) return `第 ${formIndex + 1} 个表单 > 第 ${sectionIndex + 1} 个章节 > 第 ${fieldIndex + 1} 个字段 > 第 ${columnIndex + 1} 个表格列：稳定标识过长。`
            if (!column.name.trim()) return `第 ${formIndex + 1} 个表单 > 第 ${sectionIndex + 1} 个章节 > 第 ${fieldIndex + 1} 个字段 > 第 ${columnIndex + 1} 个表格列：标题不能为空。`
            if (seen.has(column.key)) return `第 ${formIndex + 1} 个表单 > 第 ${sectionIndex + 1} 个章节 > 第 ${fieldIndex + 1} 个字段：表格列稳定标识必须唯一。`
            seen.add(column.key)
            const columnOptionIssue = scalarOptionsValidationMessage(column.type ?? "short_text", column.options ?? {})
            if (columnOptionIssue) return `第 ${formIndex + 1} 个表单 > 第 ${sectionIndex + 1} 个章节 > 第 ${fieldIndex + 1} 个字段 > 第 ${columnIndex + 1} 个表格列：${columnOptionIssue}`
            if (column.type === "single_choice" || column.type === "multi_choice") {
              const choices = columnChoices(column)
              if (choices.length === 0 || choices.some((choice) => !choice.trim()) || new Set(choices).size !== choices.length) return `第 ${formIndex + 1} 个表单 > 第 ${sectionIndex + 1} 个章节 > 第 ${fieldIndex + 1} 个字段 > 第 ${columnIndex + 1} 个表格列：选项必须非空且唯一。`
            }
          }
        }
        if (field.type === "file_reference") {
          const maxFiles = (field.options as { max_files?: unknown }).max_files
          if (typeof maxFiles !== "number" || !Number.isInteger(maxFiles) || maxFiles < 1) return `第 ${formIndex + 1} 个表单 > 第 ${sectionIndex + 1} 个章节 > 第 ${fieldIndex + 1} 个字段：最多文件数必须是正整数。`
        }
        const conditionIssue = conditionValidationMessage(field.condition, fieldsByKey)
        if (conditionIssue) return `第 ${formIndex + 1} 个表单 > 第 ${sectionIndex + 1} 个章节 > 第 ${fieldIndex + 1} 个字段：${conditionIssue}`
      }
    }
    if (hasConditionalDependencyCycle(fields.map((field) => ({
      fieldKey: field.fieldKey,
      condition: field.condition,
    })))) return `第 ${formIndex + 1} 个表单：显示条件不能形成循环依赖。`
  }
  return ""
}

function validStableKey(value: string): boolean {
  return /^[a-z][a-z0-9_]*$/.test(value)
}

function scalarOptionsValidationMessage(
  type: ResearchFieldType | ResearchTableColumnType,
  options: ResearchFieldOptionsDto | ResearchTableColumnDto["options"],
): string {
  const values = (options ?? {}) as Record<string, unknown>
  const allowedKeys: Record<ResearchFieldType, string[]> = {
    short_text: ["placeholder", "default_value", "min_length", "max_length"],
    long_text: ["placeholder", "default_value", "min_length", "max_length"],
    rich_text: ["placeholder", "default_value"],
    integer: ["minimum", "maximum", "default_value"],
    decimal: ["minimum", "maximum", "default_value"],
    date: ["minimum", "maximum", "default_value"],
    single_choice: ["choices", "default_value"],
    multi_choice: ["choices", "default_value"],
    table: ["columns"],
    file_reference: ["max_files"],
  }
  if (Object.keys(values).some((key) => !allowedKeys[type].includes(key))) return "字段配置包含不支持的属性。"
  if (type === "short_text" || type === "long_text") {
    if (["placeholder", "default_value"].some((key) => values[key] !== undefined && typeof values[key] !== "string")) return "文本配置必须是文本。"
    const minimum = values.min_length
    const maximum = values.max_length
    if (![minimum, maximum].every((value) => value === undefined || (typeof value === "number" && Number.isInteger(value) && value >= 0))) return "长度限制必须是非负整数。"
    if (typeof minimum === "number" && typeof maximum === "number" && minimum > maximum) return "最小长度不能大于最大长度。"
  } else if (type === "rich_text") {
    if (["placeholder", "default_value"].some((key) => values[key] !== undefined && typeof values[key] !== "string")) return "富文本配置必须是文本。"
  } else if (type === "integer") {
    const configured = [values.minimum, values.maximum, values.default_value]
    if (!configured.every((value) => value === undefined || (typeof value === "number" && Number.isInteger(value)))) return "整数字段范围和默认值必须是整数。"
    if (typeof values.minimum === "number" && typeof values.maximum === "number" && values.minimum > values.maximum) return "最小值不能大于最大值。"
  } else if (type === "decimal") {
    const configured = [values.minimum, values.maximum, values.default_value]
    if (!configured.every((value) => value === undefined || (typeof value === "number" && Number.isFinite(value)))) return "小数字段范围和默认值必须是有限数字。"
    if (typeof values.minimum === "number" && typeof values.maximum === "number" && values.minimum > values.maximum) return "最小值不能大于最大值。"
  } else if (type === "date") {
    if (["minimum", "maximum", "default_value"].some((key) => values[key] !== undefined && typeof values[key] !== "string")) return "日期范围和默认值必须是日期文本。"
  }
  return ""
}

function conditionValidationMessage(condition: ResearchConditionDto | undefined, fieldsByKey: Map<string, EditableField>): string {
  if (!condition) return ""
  if (condition.operator === "all" || condition.operator === "any") {
    if (condition.conditions.length === 0) return "条件组至少需要一个子条件。"
    for (const child of condition.conditions) {
      const issue = conditionValidationMessage(child, fieldsByKey)
      if (issue) return issue
    }
    return ""
  }
  const referenced = fieldsByKey.get(condition.field_key)
  if (!referenced) return "条件引用字段不存在，请重新选择。"
  if (!conditionLeafOperators(referenced.type).includes(condition.operator)) return "该字段类型不支持条件比较，请选择“为空”或更换引用字段。"
  if (condition.operator === "is_empty") return ""
  if ((referenced.type === "short_text" || referenced.type === "long_text") && !isCanonicalConditionText(condition.value)) return "文本条件值必须去除首尾 ASCII 空白且不能为空。"
  if (referenced.type === "integer" && (typeof condition.value !== "number" || !Number.isInteger(condition.value))) return "整数条件值必须是整数。"
  if (referenced.type === "decimal" && !isCanonicalDecimalValue(condition.value)) return "小数条件值超出支持范围或不是规范有限数字。"
  if (referenced.type === "date" && !isCanonicalDate(condition.value)) return "日期条件值必须使用 YYYY-MM-DD。"
  if ((referenced.type === "single_choice" || referenced.type === "multi_choice") && (typeof condition.value !== "string" || !optionChoices(referenced.options).includes(condition.value))) return "条件值必须来自引用字段的选项。"
  return ""
}

function moved<T>(items: T[], index: number, direction: -1 | 1): T[] {
  const target = index + direction
  if (target < 0 || target >= items.length) return items
  const result = [...items]
  ;[result[index], result[target]] = [result[target], result[index]]
  return result
}

function serializedFormsSignature(forms: EditableForm[]): string {
  return JSON.stringify(forms.map((form, formIndex) => serializeForm(form, formIndex)))
}

function updateColumn(columns: ResearchTableColumnDto[], index: number, changes: Partial<ResearchTableColumnDto>, onChange: (options: ResearchFieldOptionsDto) => void): void {
  onChange({ columns: columns.map((column, columnIndex) => columnIndex === index ? { ...column, ...changes } : column) })
}

function columnChoices(column: ResearchTableColumnDto): string[] {
  if (!column.options || !("choices" in column.options) || !Array.isArray(column.options.choices)) return []
  return column.options.choices
}

function researchPath(templateId: string, versionId: string): string {
  return `/api/v1/templates/${templateId}/versions/${versionId}/research-forms`
}

function nextResearchId(prefix: string): string {
  researchEditorSequence += 1
  return `${prefix}-local-${researchEditorSequence}`
}

function safeDomId(value: string): string {
  return value.replace(/[^\p{L}\p{N}_-]+/gu, "-")
}

function conditionControlId(kind: "operator" | "field" | "value" | "add", prefix: string): string {
  return `research-condition-${kind}-${safeDomId(prefix)}`
}

function conditionLabel(prefix: string, suffix: string): string {
  return prefix.endsWith("子条件") ? `${prefix}${suffix}` : `${prefix} 条件${suffix}`
}

function removeControlId(kind: "form" | "section" | "field", clientId: string): string {
  return `research-remove-${kind}-${safeDomId(clientId)}`
}

function addControlId(kind: "section" | "field", parentId: string): string {
  return `research-add-${kind}-${safeDomId(parentId)}`
}

function columnRemoveControlId(prefix: string, index: number): string {
  return `research-remove-column-${safeDomId(prefix)}-${index}`
}

function columnAddControlId(prefix: string): string {
  return `research-add-column-${safeDomId(prefix)}`
}

function focusSoon(id: string): void {
  setTimeout(() => document.getElementById(id)?.focus(), 0)
}

function lines(value: string): string[] {
  return value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
}

function numberText(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : ""
}

function numberValue(value: string, integer: boolean): number | undefined {
  if (!value.trim()) return undefined
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || (integer && !Number.isInteger(parsed))) return undefined
  return parsed
}

function typedIntegerValue(value: string): number | string {
  if (value === "") return ""
  const parsed = Number(value)
  return Number.isInteger(parsed) ? parsed : value
}

function isCanonicalDate(value: unknown): boolean {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000-")) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function optionChoices(options: ResearchFieldOptionsDto): string[] {
  const value = options as { choices?: unknown }
  return Array.isArray(value.choices) ? value.choices.filter((item): item is string => typeof item === "string") : []
}

function subjectLabel(type: ResearchSubjectType): string {
  return { project: "项目", department: "部门", role: "岗位", process: "流程", opportunity: "AI 机会" }[type]
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

export function researchDefinitionErrorMessage(error: unknown): string {
  if (error instanceof ResearchEditorValidationError) return error.message
  if (error instanceof InvalidResearchResponseError) return "服务器返回的调研模板数据格式无效。"
  if (!(error instanceof ApiClientError)) return "调研模板操作失败，请稍后重试。"
  if (error.code === "invalid_research_definition") {
    const paths = issuePaths(error.details)
    return paths.length > 0 ? `调研模板校验未通过：${paths.join("；")}` : "调研模板校验未通过，请检查字段配置。"
  }
  const safeMessages: Record<string, string> = {
    stale_version: "调研模板已被其他操作更新；已保留当前页面的本地内容，请刷新后核对。",
    forbidden: "当前账号无权修改调研模板。",
    network_error: "网络连接异常，当前本地内容已保留，请稍后重试。",
    template_version_immutable: "当前模板版本已发布，不能再修改调研定义。",
    stable_key_immutable: "已保存的稳定标识不能修改。",
    authentication_refreshed_resubmit: "登录状态已刷新，请重新提交本次操作。",
  }
  return safeMessages[error.code] ?? "调研模板操作失败，请稍后重试。"
}

function issuePaths(details: unknown): string[] {
  if (!isRecord(details) || !Array.isArray(details.issues)) return []
  return details.issues.flatMap((issue) => isRecord(issue) && typeof issue.path === "string" ? [chineseResearchPath(issue.path)] : [])
}

export function chineseResearchPath(path: string): string {
  if (!path) return "调研定义"
  const tokens = path.match(/(?:forms|sections|fields|columns|conditions)\[\d+]|[^.]+/g) ?? []
  const mapped = tokens.map((token, index): string | null => {
    const indexed = /^(forms|sections|fields|columns|conditions)\[(\d+)]$/.exec(token)
    if (indexed) {
      const noun = { forms: "表单", sections: "章节", fields: "字段", columns: "表格列", conditions: "子条件" }[indexed[1]]
      return `第 ${Number(indexed[2]) + 1} 个${noun}`
    }
    if (token === "field_key") {
      return tokens.slice(0, index).some((item) => item === "condition" || item.startsWith("conditions[")) ? "引用字段" : "字段稳定标识"
    }
    return ({
      condition: "显示条件",
      operator: "运算符",
      value: "条件值",
      options: "字段配置",
      choices: "选项",
      module_key: "所属模块",
      form_key: "表单稳定标识",
      section_key: "章节稳定标识",
      type: "类型",
      name: "名称",
    } as Record<string, string>)[token] ?? null
  })
  return mapped.some((token) => token === null) ? "调研定义中的某项配置" : mapped.join(" > ")
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

class InvalidResearchResponseError extends Error {}
export class ResearchEditorValidationError extends Error {}
