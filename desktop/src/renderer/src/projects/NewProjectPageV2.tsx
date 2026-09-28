import { useEffect, useMemo, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAIExecution } from "../ai/AIExecutionProvider"
import { useAuth } from "../auth/AuthProvider"
import { fetchAllPages } from "../workbench/fetchAllPages"
import { isModuleCatalogDto, isProjectDto } from "../workbench/runtimeValidation"
import type { ModuleCatalogDto, TemplateVersionDto, WorkbenchUserDto } from "../workbench/types"
import { isUploadCompleteDto, isUploadedPartDto, isUploadSessionDto } from "../files/runtimeValidation"
import type { UploadSessionDto } from "../files/types"
import { emptyProjectBasics, ProjectBasicsStep, type ProjectBasics } from "./ProjectBasicsStep"
import { ProjectDraftAssistant, type ProjectConfigurationDraft } from "./ProjectDraftAssistant"
import { ProjectModulesStep } from "./ProjectModulesStep"
import { ProjectReviewStep } from "./ProjectReviewStep"
import { dependencyClosure, listEligibleLeaders, NewProjectPage, orderedModuleKeys } from "./NewProjectPage"

type CreationMode = "template" | "presurvey" | "manual"
type WizardStep = 1 | 2 | 3 | 4

export function NewProjectPageV2() {
  const { apiRequest, user } = useAuth()
  const { runTask } = useAIExecution()
  const [mode, setMode] = useState<CreationMode | null>(null)
  const [step, setStep] = useState<WizardStep>(1)
  const [basics, setBasics] = useState<ProjectBasics>(emptyProjectBasics)
  const [catalog, setCatalog] = useState<ModuleCatalogDto[]>([])
  const [leaders, setLeaders] = useState<WorkbenchUserDto[]>([])
  const [leaderId, setLeaderId] = useState("")
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])
  const [draft, setDraft] = useState<ProjectConfigurationDraft | null>(null)
  const [sourceFile, setSourceFile] = useState<File | null>(null)
  const [aiOpen, setAIOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [resourceError, setResourceError] = useState("")
  const [dependencyNotice, setDependencyNotice] = useState("")
  const submitting = useRef(false)
  const generation = useRef(0)

  useEffect(() => {
    const current = ++generation.current
    submitting.current = false
    return () => { if (generation.current === current) generation.current += 1 }
  }, [mode, user?.id])

  useEffect(() => {
    if (!user || !mode || mode === "template") return
    const controller = new AbortController()
    let active = true
    setLoading(true)
    setResourceError("")
    void Promise.all([
      fetchAllPages({ apiRequest, pathForPage: (page, pageSize) => `/api/v1/modules?active=true&page=${page}&page_size=${pageSize}`, itemKey: (item: ModuleCatalogDto) => item.id, validateItem: isModuleCatalogDto, signal: controller.signal }),
      listEligibleLeaders(apiRequest, user, controller.signal),
    ]).then(([modules, eligible]) => {
      if (!active) return
      setCatalog(modules.filter((item) => item.is_active).sort((a, b) => a.sort_order - b.sort_order))
      setLeaders(eligible); setLeaderId(eligible.some((item) => item.id === user.id) ? user.id : eligible[0]?.id ?? "")
    }).catch(() => { if (active) setResourceError("创建项目所需数据加载失败，请稍后重试。") })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false; controller.abort() }
  }, [apiRequest, mode, user?.id, user?.role])

  const configuration = useMemo(() => syntheticTemplate(draft, catalog), [catalog, draft])
  const leader = leaders.find((item) => item.id === leaderId) ?? null

  function chooseMode(next: CreationMode) {
    setMode(next); setStep(1); setError(""); setResourceError(""); setDraft(null); setSourceFile(null)
    setSelectedKeys([]); setDependencyNotice(""); setBusy(false)
  }

  function applyAIDraft(next: ProjectConfigurationDraft) {
    setDraft(next)
    setSelectedKeys(next.modules.map((item) => String(item.module_key ?? "")).filter(Boolean))
    const known = next.known_information ?? {}
    setBasics((current) => ({ ...current,
      enterpriseName: text(known.enterprise) || current.enterpriseName,
      name: text(known.project_name) || current.name,
      background: next.description || text(known.requirement) || current.background,
    }))
    setAIOpen(false)
  }

  async function analyzePresurvey(file: File) {
    if (file.size > 100 * 1024 * 1024) { setError("预调研文件不能超过 100MB。"); return }
    if (!file.name.toLowerCase().endsWith(".docx")) { setError("预调研解析目前请上传 DOCX 文件。"); return }
    const startedGeneration = generation.current
    setBusy(true); setError("")
    try {
      const bytes = new Uint8Array(await file.arrayBuffer())
      const value = await runTask<unknown>({ title: "AI 正在解析预调研表", stages: ["正在上传预调研文件", "AI 正在读取文档", "正在提取企业与项目资料", "正在生成项目配置草稿"], task: () => apiRequest<unknown>("/api/v1/ai/project-draft/presurvey", { method: "POST", body: { kind: "multipart_file", fields: {}, file: { field_name: "file", name: file.name, type: file.type || "application/vnd.openxmlformats-officedocument.wordprocessingml.document", bytes } } }) })
      if (startedGeneration !== generation.current) return
      if (!isPresurveyDraft(value)) throw new Error("invalid draft")
      setSourceFile(file)
      applyAIDraft({ industry_name: value.project.industry_name, description: value.project.background, modules: value.modules })
      setBasics((current) => ({ ...current,
        name: value.project.name || current.name, enterpriseName: value.project.enterprise_name || current.enterpriseName,
        contactName: value.project.contact_name || current.contactName, contactPhone: value.project.contact_phone || current.contactPhone,
        address: value.project.address || current.address, background: value.project.background || current.background, notes: value.project.notes || current.notes,
      }))
    } catch (caught) { if (startedGeneration === generation.current) setError(caught instanceof ApiClientError ? caught.message : "预调研表解析失败，请检查文件后重试。") }
    finally { if (startedGeneration === generation.current) setBusy(false) }
  }

  function next() {
    setError("")
    if (!mode) return
    if (step === 1 && (!basics.name.trim() || !basics.enterpriseName.trim() || !basics.plannedStartDate)) { setError("请填写项目名称、企业名称和计划开始日期。"); return }
    if (step === 1 && basics.plannedEndDate && basics.plannedEndDate < basics.plannedStartDate) { setError("计划结束日期不能早于开始日期。"); return }
    if (step === 2 && (loading || resourceError || !leader)) { setError("请选择有效的项目负责人，并等待数据加载完成。"); return }
    if (step === 3 && !selectedKeys.length) { setError("请至少选择一个首期模块。"); return }
    setStep((current) => Math.min(4, current + 1) as WizardStep)
  }

  async function create() {
    if (submitting.current || !mode || !leader || !configuration || !selectedKeys.length) return
    submitting.current = true
    const startedGeneration = generation.current
    setBusy(true); setError("")
    try {
      const body: Record<string, unknown> = {
        name: basics.name.trim(), enterprise_name: basics.enterpriseName.trim(), contact_name: basics.contactName.trim(), contact_phone: basics.contactPhone.trim(), address: basics.address.trim(), background: basics.background.trim(), notes: basics.notes.trim(), project_code: basics.projectCode.trim(), planned_start_date: basics.plannedStartDate, planned_end_date: basics.plannedEndDate || null,
        leader_user_id: leader.id, module_keys: selectedKeys, creation_source: mode,
        template_version_id: null,
        project_snapshot: snapshotPayload(configuration, selectedKeys),
      }
      const created = await apiRequest<unknown>("/api/v1/projects", { method: "POST", body })
      if (startedGeneration !== generation.current) return
      if (!isProjectDto(created)) throw new Error("invalid project")
      if (mode === "manual" && window.confirm("项目已创建。是否把本次项目配置另存为新的行业模板草稿？")) {
        const name = window.prompt("请输入新模板名称", `${basics.enterpriseName || basics.name}项目模板`)?.trim()
        if (name) {
          try {
            await apiRequest("/api/v1/industry-templates", { method: "POST", body: { name, industry_name: configuration.industry_name || "通用", description: configuration.description || basics.background, modules: snapshotPayload(configuration, selectedKeys).modules } })
          } catch {
            window.alert("项目已创建，但行业模板草稿保存失败。你可以稍后在行业模板中重新创建。")
          }
        }
      }
      if (sourceFile) {
        try {
          await uploadPresurveySource(apiRequest, created.id, sourceFile)
        } catch {
          window.alert("项目已创建，但原始预调研表上传失败。请进入项目文件库后重新上传。")
        }
      }
      if (startedGeneration === generation.current) window.location.hash = `#projects/${encodeURIComponent(created.id)}`
    } catch (caught) { if (startedGeneration === generation.current) setError(caught instanceof ApiClientError ? caught.message : "项目创建失败，当前输入已保留。") }
    finally { if (startedGeneration === generation.current) { submitting.current = false; setBusy(false) } }
  }

  function toggleModule(key: string, checked: boolean) {
    const initial = new Set(checked ? [...selectedKeys, key] : selectedKeys.filter((item) => item !== key))
    const closed = dependencyClosure(configuration, initial)
    if (!checked && closed.has(key)) { setDependencyNotice("该模块是已选模块的前置，不能移除。"); return }
    const added = configuration.modules.filter((item) => closed.has(item.module_key) && !initial.has(item.module_key))
    setSelectedKeys(orderedModuleKeys(configuration, closed))
    setDependencyNotice(added.length ? `已自动选择前置模块：${added.map((item) => item.name).join("、")}。` : "")
  }

  if (!mode) return <div id="new-project" className="page-stack"><PageHeader /><section className="panel creation-method-panel"><h2>选择新建方式</h2><p className="supporting-copy">三种方式最终都会进入可人工调整的项目草稿，不会直接发布或覆盖模板。</p><div className="creation-method-grid"><Method icon="template" title="从模板新建" description="选择已发布行业模板，沿用现有模块、任务和调研结构。" onClick={() => chooseMode("template")} /><Method icon="presurvey" title="上传预调研表新建" description="上传 DOCX，由 AI 解析后生成可调整项目草稿。" onClick={() => chooseMode("presurvey")} /><Method icon="manual" title="手动新建" description="从空白项目开始，也可以通过多轮对话让 AI 辅助填写。" onClick={() => chooseMode("manual")} /></div></section></div>

  // The template entry keeps the established validated creation workflow.
  if (mode === "template") return <div className="page-stack"><div className="creation-source-bar"><button className="secondary-button compact" onClick={() => setMode(null)}>更换新建方式</button><span>当前方式：从模板新建</span></div><NewProjectPage /></div>

  return <div id="new-project" className="page-stack"><PageHeader />
    <div className="creation-source-bar"><button className="secondary-button compact" onClick={() => setMode(null)}>更换新建方式</button><span>当前方式：{modeLabel(mode)}</span>{mode === "manual" ? <button className="primary-button compact ai-assist-button" onClick={() => setAIOpen(true)}>AI 辅助填写</button> : null}{mode === "presurvey" ? <label className={`primary-button compact file-button${busy ? " disabled" : ""}`}>{busy ? "正在解析…" : sourceFile ? "重新上传预调研表" : "上传预调研表"}<input className="file-input-hidden" type="file" accept=".docx" aria-label="选择预调研表 DOCX" disabled={busy} onChange={(event) => { const file = event.target.files?.[0]; if (file) void analyzePresurvey(file); event.currentTarget.value = "" }} /></label> : null}</div>
    <ol className="wizard-progress">{["基础信息", "负责人", "首期模块", "确认创建"].map((label, index) => <li key={label} className={step === index + 1 ? "active" : step > index + 1 ? "done" : ""}><span>{index + 1}</span>{label}</li>)}</ol>
    {step === 1 ? <ProjectBasicsStep value={basics} onChange={setBasics} /> : null}
    {step === 2 ? <section className="panel wizard-panel"><h2>2. 项目负责人</h2><label className="field"><span>负责人</span><select value={leaderId} disabled={user?.role === "project_lead"} onChange={(event) => setLeaderId(event.target.value)}>{leaders.map((item) => <option value={item.id} key={item.id}>{item.display_name}</option>)}</select></label></section> : null}
    {step === 3 && configuration ? <ProjectModulesStep template={configuration} selectedModuleKeys={selectedKeys} dependencyNotice={dependencyNotice} onToggle={toggleModule} /> : null}
    {step === 4 && configuration && leader ? <ProjectReviewStep basics={basics} template={configuration} leader={leader} selectedModuleKeys={selectedKeys} /> : null}
    {error || resourceError ? <p className="form-error banner" role="alert">{error || resourceError}</p> : null}
    <div className="wizard-actions">{step > 1 ? <button className="secondary-button" disabled={busy} onClick={() => setStep((step - 1) as WizardStep)}>上一步</button> : <span />}{step < 4 ? <button className="primary-button" disabled={busy || loading} onClick={next}>下一步</button> : <button className="primary-button" disabled={busy} onClick={() => void create()}>{busy ? "正在创建…" : "创建项目"}</button>}</div>
    {aiOpen ? <ProjectDraftAssistant onApply={applyAIDraft} onClose={() => setAIOpen(false)} /> : null}
  </div>
}

function PageHeader() { return <header className="page-header"><div><p className="eyebrow">项目管理</p><h1>新建项目</h1><p className="supporting-copy">选择信息来源，形成草稿，人工调整后再创建项目。</p></div><a className="secondary-button button-link" href="#projects">返回项目列表</a></header> }
function Method({ icon, title, description, onClick }: { icon: CreationMode; title: string; description: string; onClick(): void }) { return <button className="creation-method-card" type="button" onClick={onClick}><span className={`creation-method-icon ${icon}`} aria-hidden="true"><CreationMethodIcon kind={icon} /></span><strong>{title}</strong><p>{description}</p><em>开始</em></button> }

function CreationMethodIcon({ kind }: { kind: CreationMode }) {
  const common = { viewBox: "0 0 24 24", width: 24, height: 24, fill: "none", stroke: "currentColor", strokeWidth: 1.9, strokeLinecap: "round" as const, strokeLinejoin: "round" as const }
  if (kind === "template") return <svg {...common}><path d="M5 5.5A2.5 2.5 0 0 1 7.5 3H19v15H7.5A2.5 2.5 0 0 0 5 20.5z"/><path d="M5 5.5v15M9 7h6M9 11h7"/></svg>
  if (kind === "presurvey") return <svg {...common}><path d="M12 16V5M8 9l4-4 4 4"/><path d="M5 14v5h14v-5"/></svg>
  return <svg {...common}><path d="m4 20 4.2-1 10.4-10.4a2.1 2.1 0 0 0-3-3L5.2 16z"/><path d="m14.5 6.5 3 3M4 20h6"/></svg>
}
function modeLabel(mode: CreationMode) { return mode === "template" ? "从模板新建" : mode === "presurvey" ? "上传预调研表新建" : "手动新建" }
function text(value: unknown): string { return typeof value === "string" ? value : "" }

function syntheticTemplate(draft: ProjectConfigurationDraft | null, catalog: ModuleCatalogDto[]): TemplateVersionDto {
  const moduleDrafts: Array<Record<string, unknown>> = draft?.modules.length ? draft.modules : catalog.map((item) => ({ module_key: item.key, name: item.name, description: item.description, tasks: [{ task_key: `${item.key}_planning`, name: `${item.name}实施规划`, description: `梳理${item.name}的范围、输入、责任人与验收条件。`, duration_days: 1, default_assignee_role: "project_lead", dependency_keys: [], sort_order: 0 }] }))
  const modules = moduleDrafts.map((item, index) => ({
    id: `draft-module-${index}`, module_catalog_id: catalog.find((entry) => entry.key === item.module_key)?.id ?? "", module_key: String(item.module_key ?? ""), name: String(item.name ?? item.module_key ?? "未命名模块"), description: String(item.description ?? ""), sort_order: Number(item.sort_order ?? index),
    tasks: (Array.isArray(item.tasks) ? item.tasks : []).map((task, taskIndex) => { const value = task as Record<string, unknown>; return { id: `draft-task-${index}-${taskIndex}`, task_key: String(value.task_key ?? `${item.module_key}_task_${taskIndex + 1}`), name: String(value.name ?? "实施任务"), description: String(value.description ?? ""), duration_days: Number(value.duration_days ?? 1), default_assignee_role: (value.default_assignee_role === "fde_engineer" ? "fde_engineer" : "project_lead") as "project_lead" | "fde_engineer", sort_order: Number(value.sort_order ?? taskIndex), dependency_keys: Array.isArray(value.dependency_keys) ? value.dependency_keys.map(String) : [] } }),
  }))
  return { template_id: "", template_name: "项目自定义配置", industry_name: draft?.industry_name || "通用", description: draft?.description || "", version_id: "", version_number: 1, status: "draft", version: 1, published_by_user_id: null, published_at: null, modules }
}

function snapshotPayload(template: TemplateVersionDto, selected: string[]) { return { industry_name: template.industry_name, description: template.description, modules: template.modules.filter((item) => selected.includes(item.module_key)).map((item) => ({ module_key: item.module_key, name: item.name, description: item.description, sort_order: item.sort_order, tasks: item.tasks.map((task) => ({ task_key: task.task_key, name: task.name, description: task.description, duration_days: task.duration_days, default_assignee_role: task.default_assignee_role, dependency_keys: task.dependency_keys, sort_order: task.sort_order })) })) } }
function isPresurveyDraft(value: unknown): value is { project: Record<string, string>; modules: Array<Record<string, unknown>> } { return Boolean(value && typeof value === "object" && !Array.isArray(value) && typeof (value as Record<string, unknown>).project === "object" && Array.isArray((value as Record<string, unknown>).modules)) }

async function uploadPresurveySource(apiRequest: ReturnType<typeof useAuth>["apiRequest"], projectId: string, file: File): Promise<void> {
  const base = `/api/v1/projects/${encodeURIComponent(projectId)}/files`
  const created = await apiRequest<unknown>(base, { method: "POST", body: { name: file.name, display_name: file.name.replace(/\.docx$/i, ""), size_bytes: file.size, mime_type: file.type || "application/vnd.openxmlformats-officedocument.wordprocessingml.document", category: "attachment", business_category: "预调研", idempotency_key: crypto.randomUUID() } })
  if (!isUploadSessionDto(created)) throw new Error("invalid upload session")
  const parts = await uploadFileParts(apiRequest, base, created, file)
  const complete = await apiRequest<unknown>(`${base}/${encodeURIComponent(created.id)}/complete`, { method: "POST", body: { parts } })
  if (!isUploadCompleteDto(complete)) throw new Error("invalid upload completion")
}

async function uploadFileParts(apiRequest: ReturnType<typeof useAuth>["apiRequest"], base: string, session: UploadSessionDto, file: File) {
  const parts: Array<{ part_number: number; etag: string }> = []
  const total = Math.max(1, Math.ceil(file.size / session.part_size))
  for (let partNumber = 1; partNumber <= total; partNumber += 1) {
    const signed = await apiRequest<unknown>(`${base}/${encodeURIComponent(session.id)}/parts`, { method: "POST", body: { part_number: partNumber } })
    if (!isUploadedPartDto(signed)) throw new Error("invalid upload part")
    const start = (partNumber - 1) * session.part_size
    const response = await fetch(signed.url, { method: "PUT", body: file.slice(start, Math.min(file.size, start + session.part_size)) })
    if (!response.ok) throw new Error("storage upload failed")
    parts.push({ part_number: partNumber, etag: (response.headers.get("etag") ?? "").replace(/^"|"$/g, "") })
  }
  return parts
}
