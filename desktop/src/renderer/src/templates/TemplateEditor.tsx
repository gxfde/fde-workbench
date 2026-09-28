import { useMemo, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react"

import { USER_ROLES, isUserRole, type UserRole } from "../../../shared/contracts"
import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { useDangerConfirm } from "../common/DangerConfirmProvider"
import {
  ResearchDefinitionEditor,
  ResearchEditorValidationError,
  researchDefinitionErrorMessage,
  type ResearchDefinitionPreflight,
  type ResearchDefinitionEditorHandle,
} from "../research/ResearchDefinitionEditor"
import { isResearchDefinitionDto } from "../research/runtimeValidation"
import type { ResearchDefinitionDto } from "../research/types"
import type {
  ModuleCatalogDto,
  TemplateVersionDto,
} from "../workbench/types"
import {
  DependencyEditor,
  documentHasCycle,
  type DependencyTask,
} from "./DependencyEditor"

interface EditorTask {
  clientId: string
  taskKey: string
  name: string
  description: string
  durationDays: string
  defaultAssigneeRole: UserRole
  sortOrder: string
  dependencyKeys: string[]
}

interface EditorModule {
  clientId: string
  moduleKey: string
  name: string
  description: string
  sortOrder: string
  tasks: EditorTask[]
}

interface TemplateDocumentInput {
  name: string
  industry_name: string
  description: string
  modules: Array<{
    module_key: string
    name: string
    description: string
    sort_order: number
    tasks: Array<{
      task_key: string
      name: string
      description: string
      duration_days: number
      default_assignee_role: UserRole
      sort_order: number
      dependency_keys: string[]
    }>
  }>
}

let editorSequence = 0

export function TemplateEditor({
  draft,
  catalog,
  onSaved,
  onPublished,
  onDeleted,
  onCancel,
  onAIRequested,
  initialNotice = "",
}: {
  draft: TemplateVersionDto | null
  catalog: ModuleCatalogDto[]
  onSaved(version: TemplateVersionDto): void
  onPublished(version: TemplateVersionDto): void
  onDeleted(versionId: string, versionNumber: number): void
  onCancel(): void
  onAIRequested?(): void
  initialNotice?: string
}) {
  const { apiRequest } = useAuth()
  const dangerConfirm = useDangerConfirm()
  const [persisted, setPersisted] = useState(draft)
  const persistedRef = useRef(draft)
  const [name, setName] = useState(draft?.template_name ?? "")
  const [industryName, setIndustryName] = useState(draft?.industry_name ?? "")
  const [description, setDescription] = useState(draft?.description ?? "")
  const [modules, setModules] = useState<EditorModule[]>(() => fromDto(draft))
  const [selectedModuleKey, setSelectedModuleKey] = useState("")
  const [saving, setSaving] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [notice, setNotice] = useState(initialNotice)
  const [error, setError] = useState("")
  const [publishError, setPublishError] = useState("")
  const [staleVersion, setStaleVersion] = useState(false)
  const [versionConflict, setVersionConflict] = useState(false)
  const [activeEditorTab, setActiveEditorTab] = useState<"workflow" | "research">("workflow")
  const [researchMounted, setResearchMounted] = useState(false)
  const [researchReloadKey, setResearchReloadKey] = useState(0)
  const researchEditorRef = useRef<ResearchDefinitionEditorHandle>(null)
  const workflowTabRef = useRef<HTMLButtonElement>(null)
  const researchTabRef = useRef<HTMLButtonElement>(null)
  const allTasks = useMemo(() => modules.flatMap((module) => module.tasks), [modules])
  const availableCatalog = catalog.filter(
    (item) => item.is_active && !modules.some((module) => module.moduleKey === item.key),
  )
  const versionNumber = persisted?.version_number ?? 1

  function adoptPersisted(next: TemplateVersionDto): void {
    persistedRef.current = next
    setPersisted(next)
  }

  function adoptResearchVersion(version: number): void {
    const current = persistedRef.current
    if (!current || version <= current.version) return
    const updated = { ...current, version }
    adoptPersisted(updated)
    onSaved(updated)
  }

  function observeResearchVersion(version: number): void {
    const current = persistedRef.current
    if (!current) return
    if (version !== current.version) {
      setVersionConflict(true)
      setStaleVersion(true)
      setError("服务器完整草稿已更新；本地修改仍保留。重新加载完整草稿后才能保存或发布。")
    }
  }

  function activateEditorTab(tab: "workflow" | "research"): void {
    if (tab === "research") setResearchMounted(true)
    setActiveEditorTab(tab)
  }

  function handleTabKey(event: KeyboardEvent<HTMLDivElement>): void {
    if (!persisted || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return
    event.preventDefault()
    const next = event.key === "ArrowRight" || event.key === "End" ? "research" : "workflow"
    activateEditorTab(next)
    ;(next === "research" ? researchTabRef : workflowTabRef).current?.focus()
  }

  function addModule(): void {
    const selected = catalog.find((item) => item.key === selectedModuleKey && item.is_active)
    if (!selected || modules.some((module) => module.moduleKey === selected.key)) return
    setModules((current) => [...current, {
      clientId: nextEditorId("module"),
      moduleKey: selected.key,
      name: selected.name,
      description: selected.description,
      sortOrder: String(selected.sort_order),
      tasks: [],
    }])
    setSelectedModuleKey("")
    setError("")
  }

  function updateModule(clientId: string, changes: Partial<EditorModule>): void {
    setModules((current) => current.map((module) => module.clientId === clientId ? { ...module, ...changes } : module))
  }

  function removeModule(clientId: string): void {
    const removedKeys = new Set(
      modules.find((module) => module.clientId === clientId)?.tasks.map((task) => task.taskKey) ?? [],
    )
    setModules((current) => current
      .filter((module) => module.clientId !== clientId)
      .map((module) => ({
        ...module,
        tasks: module.tasks.map((task) => ({
          ...task,
          dependencyKeys: task.dependencyKeys.filter((key) => !removedKeys.has(key)),
        })),
      })))
  }

  function addTask(moduleId: string): void {
    setModules((current) => current.map((module) => {
      if (module.clientId !== moduleId) return module
      return {
        ...module,
        tasks: [...module.tasks, {
          clientId: nextEditorId("task"),
          taskKey: "",
          name: "",
          description: "",
          durationDays: "1",
          defaultAssigneeRole: "fde_engineer",
          sortOrder: String((module.tasks.length + 1) * 10),
          dependencyKeys: [],
        }],
      }
    }))
  }

  function updateTask(clientId: string, changes: Partial<EditorTask>): void {
    setModules((current) => {
      const previous = current.flatMap((module) => module.tasks).find((task) => task.clientId === clientId)
      const previousKey = previous?.taskKey
      const nextKey = changes.taskKey
      return current.map((module) => ({
        ...module,
        tasks: module.tasks.map((task) => {
          const updated = task.clientId === clientId ? { ...task, ...changes } : task
          if (previousKey !== undefined && nextKey !== undefined && previousKey !== nextKey) {
            return {
              ...updated,
              dependencyKeys: updated.dependencyKeys.map((key) => key === previousKey ? nextKey : key),
            }
          }
          return updated
        }),
      }))
    })
  }

  function removeTask(clientId: string): void {
    const removedKey = allTasks.find((task) => task.clientId === clientId)?.taskKey
    setModules((current) => current.map((module) => ({
      ...module,
      tasks: module.tasks
        .filter((task) => task.clientId !== clientId)
        .map((task) => ({
          ...task,
          dependencyKeys: task.dependencyKeys.filter((key) => key !== removedKey),
        })),
    })))
  }

  async function save(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (versionConflict) {
      setError("服务器完整草稿已更新；请先使用下方解决动作。")
      return
    }
    setError("")
    setPublishError("")
    setNotice("")
    setStaleVersion(false)
    setSaving(true)
    try {
      const saved = await persistDocumentAndResearch()
      setNotice("草稿已保存")
      onSaved(saved)
    } catch (caught) {
      markStaleVersion(caught)
      setError(templateErrorMessage(caught))
    } finally {
      setSaving(false)
    }
  }

  async function publish(): Promise<void> {
    if (versionConflict) {
      setPublishError("服务器完整草稿已更新；请先使用下方解决动作。")
      return
    }
    setError("")
    setPublishError("")
    setNotice("")
    setStaleVersion(false)
    setPublishing(true)
    try {
      const saved = await persistDocumentAndResearch()
      onSaved(saved)
      const published = await apiRequest<TemplateVersionDto>(
        `/api/v1/industry-templates/versions/${saved.version_id}/publish`,
        { method: "POST", body: { version: saved.version } },
      )
      onPublished(published)
    } catch (caught) {
      markStaleVersion(caught)
      setPublishError(templateErrorMessage(caught))
    } finally {
      setPublishing(false)
    }
  }

  async function persistDocument(): Promise<TemplateVersionDto> {
    const input = buildDocumentInput(name, industryName, description, modules)
    const current = persistedRef.current
    const saved = current
      ? await apiRequest<TemplateVersionDto>(
          `/api/v1/industry-templates/versions/${current.version_id}`,
          { method: "PATCH", body: { version: current.version, ...input } },
        )
      : await apiRequest<TemplateVersionDto>("/api/v1/industry-templates", {
          method: "POST",
          body: input,
        })
    adoptPersisted(saved)
    return saved
  }

  async function persistDocumentAndResearch(): Promise<TemplateVersionDto> {
    if (versionConflict) throw new EditorValidationError("服务器完整草稿已更新；请先重新加载完整草稿。")
    const beforeSave = persistedRef.current
    const mountedEditor = researchEditorRef.current
    let preparedResearch: ResearchDefinitionPreflight | null = null
    if (beforeSave && !mountedEditor) {
      const value = await apiRequest<unknown>(researchPath(beforeSave), { method: "GET" })
      if (!isResearchDefinitionDto(value)) throw new EditorValidationError("服务器返回的调研模板数据格式无效。")
      if (value.version !== beforeSave.version) {
        observeResearchVersion(value.version)
        throw new EditorValidationError("服务器完整草稿已更新；请先重新加载完整草稿。")
      }
    } else if (mountedEditor && !mountedEditor.isReady()) {
      throw new EditorValidationError("调研模板仍在加载、加载失败或版本不一致，请处理后重试。")
    } else if (mountedEditor) {
      preparedResearch = mountedEditor.preflight()
    }

    const savedBase = await persistDocument()
    const savedResearch = mountedEditor && preparedResearch?.dirty
      ? await mountedEditor.save(savedBase.version, preparedResearch)
      : !beforeSave
        ? await replaceUnopenedResearch(savedBase, [])
        : null
    if (mountedEditor && preparedResearch && !preparedResearch.dirty && beforeSave) {
      mountedEditor.adoptAggregateVersion(beforeSave.version, savedBase.version)
    }
    const saved = savedResearch ? { ...savedBase, version: savedResearch.version } : savedBase
    adoptPersisted(saved)
    return saved
  }

  async function replaceUnopenedResearch(
    template: TemplateVersionDto,
    forms: ResearchDefinitionDto["forms"],
  ): Promise<ResearchDefinitionDto> {
    const value = await apiRequest<unknown>(researchPath(template), {
      method: "PUT",
      body: { version: template.version, forms },
    })
    if (!isResearchDefinitionDto(value)) throw new EditorValidationError("服务器返回的调研模板数据格式无效。")
    return value
  }

  function markStaleVersion(error: unknown): void {
    if (error instanceof ApiClientError && error.code === "stale_version" && persistedRef.current) {
      setStaleVersion(true)
      setVersionConflict(true)
    }
  }

  async function refreshStaleVersion(): Promise<void> {
    const previous = persistedRef.current
    if (!previous) return
    setSaving(true)
    try {
      const current = await apiRequest<TemplateVersionDto>(
        `/api/v1/industry-templates/versions/${previous.version_id}`,
        { method: "GET" },
      )
      adoptPersisted(current)
      replaceEditorDocument(current, setName, setIndustryName, setDescription, setModules)
      onSaved(current)
      setVersionConflict(false)
      setStaleVersion(false)
      if (researchMounted) setResearchReloadKey((value) => value + 1)
      setError("")
      setPublishError("")
      setNotice("已重新加载服务器完整草稿；此前本地修改已舍弃。")
    } catch (caught) {
      setError(templateErrorMessage(caught))
    } finally {
      setSaving(false)
    }
  }

  async function deleteDraft(): Promise<void> {
    if (!persisted) return
    const confirmed = await dangerConfirm({
      title: "删除草稿",
      description: `确定删除 v${persisted.version_number} 草稿吗？该版本将被永久删除。`,
      confirmLabel: "删除",
    })
    if (!confirmed) return
    setError("")
    setPublishError("")
    setNotice("")
    setStaleVersion(false)
    setDeleting(true)
    try {
      await apiRequest<void>(
        `/api/v1/industry-templates/versions/${persisted.version_id}`,
        { method: "DELETE", body: { version: persisted.version } },
      )
      onDeleted(persisted.version_id, persisted.version_number)
    } catch (caught) {
      markStaleVersion(caught)
      setError(templateErrorMessage(caught))
    } finally {
      setDeleting(false)
    }
  }

  const busy = saving || publishing || deleting
  return (
    <section className="page-stack template-editor" aria-labelledby="template-editor-title">
      <header className="page-header">
        <div>
          <p className="eyebrow">行业模板</p>
          <h1 id="template-editor-title">{persisted ? `编辑 v${versionNumber} ${persisted.status === "draft" ? "草稿" : "版本"}` : "新建 v1 草稿"}</h1>
          <p className="supporting-copy">草稿保存为完整版本文档；已发布版本仍可继续编辑。</p>
        </div>
        <div className="page-header-actions">
          {!persisted && onAIRequested ? <button className="primary-button ai-assist-button" type="button" disabled={busy} onClick={onAIRequested}>AI 辅助创建</button> : null}
          <button className="secondary-button" type="button" disabled={busy} onClick={onCancel}>返回列表</button>
        </div>
      </header>

      {notice ? <p className="notice" role="status">{notice}</p> : null}
      {error ? <p className="form-error banner" role="alert">{error}</p> : null}
      {staleVersion ? <button className="secondary-button" type="button" disabled={busy} onClick={() => void refreshStaleVersion()}>重新加载服务器完整草稿（舍弃本地修改）</button> : null}

      <form className="page-stack" onSubmit={(event) => void save(event)} noValidate>
        <section className="panel" aria-labelledby="template-metadata-title">
          <h2 id="template-metadata-title">版本信息</h2>
          <div className="template-metadata-grid">
            <Field label="模板名称" id="template-name"><input id="template-name" value={name} disabled={busy} onChange={(event) => setName(event.target.value)} /></Field>
            <Field label="行业名称" id="template-industry"><input id="template-industry" value={industryName} disabled={busy} onChange={(event) => setIndustryName(event.target.value)} /></Field>
            <Field label="模板说明" id="template-description"><textarea id="template-description" rows={3} value={description} disabled={busy} onChange={(event) => setDescription(event.target.value)} /></Field>
          </div>
        </section>

        <div className="template-editor-tabs" role="tablist" aria-label="模板编辑内容" onKeyDown={handleTabKey}>
          <button ref={workflowTabRef} id="template-workflow-tab" role="tab" tabIndex={activeEditorTab === "workflow" ? 0 : -1} aria-selected={activeEditorTab === "workflow"} aria-controls="template-workflow-panel" className={activeEditorTab === "workflow" ? "active" : ""} type="button" disabled={busy} onClick={() => activateEditorTab("workflow")}>模块与任务</button>
          <button ref={researchTabRef} id="template-research-tab" role="tab" tabIndex={activeEditorTab === "research" ? 0 : -1} aria-selected={activeEditorTab === "research"} aria-controls="template-research-panel" className={activeEditorTab === "research" ? "active" : ""} type="button" disabled={busy || !persisted} onClick={() => activateEditorTab("research")}>调研表</button>
        </div>

        <section id="template-workflow-panel" role="tabpanel" aria-labelledby="template-workflow-tab" className="panel" hidden={activeEditorTab !== "workflow"}>
          <div className="panel-heading"><div><h2 id="template-modules-title">模块与任务</h2><p className="supporting-copy compact-copy">任务标识用于跨模块依赖，请使用稳定的小写英文标识。</p></div><span>{modules.length} 个模块 · {allTasks.length} 个任务</span></div>
          <div className="add-module-row">
            <div className="field"><label htmlFor="catalog-module">选择模块</label><select id="catalog-module" value={selectedModuleKey} disabled={busy || availableCatalog.length === 0} onChange={(event) => setSelectedModuleKey(event.target.value)}><option value="">请选择</option>{availableCatalog.map((module) => <option key={module.id} value={module.key}>{module.name}（{module.key}）</option>)}</select></div>
            <button className="secondary-button" type="button" disabled={busy || !selectedModuleKey} onClick={addModule}>添加模块</button>
          </div>
          {modules.length === 0 ? <p className="empty-state">暂未添加模块。草稿可以为空，发布前每个模块至少需要一个任务。</p> : null}
          <div className="module-editor-list">{modules.map((module, moduleIndex) => (
            <article className="module-editor-card" key={module.clientId}>
              <div className="card-heading"><div><span className="sequence-label">模块 {moduleIndex + 1}</span><h3>{module.name || module.moduleKey}</h3><code>{module.moduleKey}</code></div><button className="danger-button compact" type="button" disabled={busy} onClick={() => removeModule(module.clientId)}>移除模块</button></div>
              <div className="template-module-grid">
                <Field label={`${module.moduleKey} 模块名称`} id={`module-name-${module.clientId}`}><input id={`module-name-${module.clientId}`} value={module.name} disabled={busy} onChange={(event) => updateModule(module.clientId, { name: event.target.value })} /></Field>
                <Field label={`${module.moduleKey} 模块排序`} id={`module-sort-${module.clientId}`}><input id={`module-sort-${module.clientId}`} type="number" step="1" value={module.sortOrder} disabled={busy} onChange={(event) => updateModule(module.clientId, { sortOrder: event.target.value })} /></Field>
                <Field label={`${module.moduleKey} 模块说明`} id={`module-description-${module.clientId}`}><textarea id={`module-description-${module.clientId}`} rows={2} value={module.description} disabled={busy} onChange={(event) => updateModule(module.clientId, { description: event.target.value })} /></Field>
              </div>
              <div className="task-heading"><h4>任务定义</h4><button className="secondary-button compact" type="button" disabled={busy} aria-label={`在 ${module.name}中新增任务`} onClick={() => addTask(module.clientId)}>新增任务</button></div>
              <div className="task-editor-list">{module.tasks.map((task, taskIndex) => {
                const taskLabel = task.name.trim() || `任务 ${taskIndex + 1}`
                return <article className="task-editor-card" key={task.clientId}>
                  <div className="card-heading"><div><span className="sequence-label">任务 {taskIndex + 1}</span><strong>{task.name || "未命名任务"}</strong><code>{task.taskKey || "待填写稳定标识"}</code></div><button className="danger-button compact" type="button" disabled={busy} onClick={() => removeTask(task.clientId)}>移除任务</button></div>
                  <div className="task-fields-grid">
                    <Field label={`${taskLabel} 任务名称`} id={`task-name-${task.clientId}`}><input id={`task-name-${task.clientId}`} value={task.name} disabled={busy} onChange={(event) => updateTask(task.clientId, { name: event.target.value })} /></Field>
                    <Field label={`${taskLabel} 稳定任务标识`} id={`task-key-${task.clientId}`}><input id={`task-key-${task.clientId}`} placeholder="prepare_data" value={task.taskKey} disabled={busy} onChange={(event) => updateTask(task.clientId, { taskKey: event.target.value })} /></Field>
                    <Field label={`${taskLabel} 时长（工作日）`} id={`task-duration-${task.clientId}`}><input id={`task-duration-${task.clientId}`} type="number" min="1" step="1" value={task.durationDays} disabled={busy} onChange={(event) => updateTask(task.clientId, { durationDays: event.target.value })} /></Field>
                    <Field label={`${taskLabel} 默认负责角色`} id={`task-role-${task.clientId}`}><select id={`task-role-${task.clientId}`} value={task.defaultAssigneeRole} disabled={busy} onChange={(event) => { if (isUserRole(event.target.value)) updateTask(task.clientId, { defaultAssigneeRole: event.target.value }) }}>{USER_ROLES.map((role) => <option value={role} key={role}>{roleLabel(role)}</option>)}</select></Field>
                    <Field label={`${taskLabel} 任务排序`} id={`task-sort-${task.clientId}`}><input id={`task-sort-${task.clientId}`} type="number" step="1" value={task.sortOrder} disabled={busy} onChange={(event) => updateTask(task.clientId, { sortOrder: event.target.value })} /></Field>
                    <Field label={`${taskLabel} 任务说明`} id={`task-description-${task.clientId}`}><textarea id={`task-description-${task.clientId}`} rows={2} value={task.description} disabled={busy} onChange={(event) => updateTask(task.clientId, { description: event.target.value })} /></Field>
                    <DependencyEditor task={dependencyTask(task)} tasks={allTasks.map(dependencyTask)} disabled={busy} onChange={(dependencyKeys) => updateTask(task.clientId, { dependencyKeys })} />
                  </div>
                </article>
              })}</div>
            </article>
          ))}</div>
        </section>

        {researchMounted && persisted ? <section id="template-research-panel" role="tabpanel" aria-labelledby="template-research-tab" className="panel" hidden={activeEditorTab !== "research"}>
          <ResearchDefinitionEditor
            key={researchReloadKey}
            ref={researchEditorRef}
            templateId={persisted.template_id}
            versionId={persisted.version_id}
            version={persisted.version}
            moduleKeys={modules.map((module) => module.moduleKey)}
            disabled={busy}
            onLoadedVersion={observeResearchVersion}
            onVersionChange={adoptResearchVersion}
            onStale={() => {
              setStaleVersion(true)
              setVersionConflict(true)
            }}
            onPublish={() => void publish()}
          />
        </section> : null}

        <footer className="editor-actions">
          <button className="secondary-button" type="button" disabled={busy} onClick={onCancel}>取消</button>
          {persisted && persisted.status === "draft" ? <button className="danger-text-button" type="button" disabled={busy} onClick={() => void deleteDraft()}>{deleting ? "正在删除" : "删除草稿"}</button> : null}
          <button className="secondary-button" type="submit" disabled={busy}>{saving ? "正在保存" : "保存草稿"}</button>
          {persisted === null || persisted.status === "draft" ? (
            <div className="publish-actions" data-testid="publish-actions">
              <button className="primary-button" type="button" disabled={busy} onClick={() => void publish()}>{publishing ? "正在发布" : `发布 v${versionNumber}`}</button>
              {publishError ? <p className="form-error" role="alert">{publishError}</p> : null}
            </div>
          ) : null}
        </footer>
      </form>
    </section>
  )
}

function Field({ label, id, children }: { label: string; id: string; children: ReactNode }) {
  return <div className="field"><label htmlFor={id}>{label}</label>{children}</div>
}

function fromDto(draft: TemplateVersionDto | null): EditorModule[] {
  return draft?.modules.map((module) => ({
    clientId: module.id,
    moduleKey: module.module_key,
    name: module.name,
    description: module.description,
    sortOrder: String(module.sort_order),
    tasks: module.tasks.map((task) => ({
      clientId: task.id,
      taskKey: task.task_key,
      name: task.name,
      description: task.description,
      durationDays: String(task.duration_days),
      defaultAssigneeRole: task.default_assignee_role,
      sortOrder: String(task.sort_order),
      dependencyKeys: task.dependency_keys,
    })),
  })) ?? []
}

function replaceEditorDocument(
  current: TemplateVersionDto,
  setName: (value: string) => void,
  setIndustryName: (value: string) => void,
  setDescription: (value: string) => void,
  setModules: (value: EditorModule[]) => void,
): void {
  setName(current.template_name)
  setIndustryName(current.industry_name)
  setDescription(current.description)
  setModules(fromDto(current))
}

function researchPath(template: Pick<TemplateVersionDto, "template_id" | "version_id">): string {
  return `/api/v1/templates/${template.template_id}/versions/${template.version_id}/research-forms`
}

function buildDocumentInput(
  rawName: string,
  rawIndustryName: string,
  rawDescription: string,
  modules: EditorModule[],
): TemplateDocumentInput {
  const name = rawName.trim()
  const industryName = rawIndustryName.trim()
  if (!name || !industryName) throw new EditorValidationError("请填写模板名称和行业名称。")
  const taskKeys = modules.flatMap((module) => module.tasks.map((task) => task.taskKey.trim()))
  if (taskKeys.some((key) => !stableKey(key))) throw new EditorValidationError("稳定任务标识需使用小写英文、数字或下划线，且以英文开头。")
  if (new Set(taskKeys).size !== taskKeys.length) throw new EditorValidationError("稳定任务标识在模板中必须唯一。")
  if (documentHasCycle(modules.flatMap((module) => module.tasks).map(dependencyTask))) throw new EditorValidationError("任务依赖存在循环，请先调整。")
  return {
    name,
    industry_name: industryName,
    description: rawDescription.trim(),
    modules: modules.map((module) => {
      const sortOrder = wholeNumber(module.sortOrder)
      if (!module.name.trim() || sortOrder === null) throw new EditorValidationError("请完整填写模块名称和排序。")
      return {
        module_key: module.moduleKey,
        name: module.name.trim(),
        description: module.description.trim(),
        sort_order: sortOrder,
        tasks: module.tasks.map((task) => {
          const durationDays = positiveNumber(task.durationDays)
          const taskSortOrder = wholeNumber(task.sortOrder)
          if (!task.name.trim() || durationDays === null || taskSortOrder === null) throw new EditorValidationError("请完整填写任务名称、时长和排序。")
          return {
            task_key: task.taskKey.trim(),
            name: task.name.trim(),
            description: task.description.trim(),
            duration_days: durationDays,
            default_assignee_role: task.defaultAssigneeRole,
            sort_order: taskSortOrder,
            dependency_keys: task.dependencyKeys,
          }
        }),
      }
    }),
  }
}

class EditorValidationError extends Error {}

function nextEditorId(prefix: string): string {
  editorSequence += 1
  return `${prefix}-${editorSequence}`
}

function dependencyTask(task: EditorTask): DependencyTask {
  return {
    clientId: task.clientId,
    taskKey: task.taskKey.trim(),
    name: task.name,
    dependencyKeys: task.dependencyKeys,
  }
}

function stableKey(value: string): boolean {
  return /^[a-z][a-z0-9_]*$/.test(value)
}

function wholeNumber(value: string): number | null {
  if (!/^-?\d+$/.test(value.trim())) return null
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) ? parsed : null
}

function positiveNumber(value: string): number | null {
  const parsed = wholeNumber(value)
  return parsed !== null && parsed >= 1 ? parsed : null
}

function roleLabel(role: UserRole): string {
  return { admin: "管理员", project_lead: "项目负责人", fde_engineer: "FDE 工程师", viewer: "查看者" }[role]
}

function templateErrorMessage(error: unknown): string {
  if (error instanceof EditorValidationError) return error.message
  if (error instanceof ResearchEditorValidationError) return researchDefinitionErrorMessage(error)
  if (error instanceof ApiClientError) {
    if (error.code === "invalid_research_definition") return researchDefinitionErrorMessage(error)
    const messages: Record<string, string> = {
      stale_version: "草稿已被其他操作更新；已保留当前页面的本地值，请核对后重试。",
      cyclic_dependency: "任务依赖存在循环，请调整后再发布。",
      missing_dependency: "任务依赖指向了不存在的稳定标识。",
      inactive_module: "草稿使用了已停用模块，请调整后再发布。",
      template_empty: "发布前至少需要一个模块，且每个模块至少有一个任务。",
      invalid_task_key: "草稿包含无效的稳定任务标识。",
      duplicate_task_key: "稳定任务标识在模板中必须唯一。",
      template_draft_exists: "该模板已有可编辑草稿。",
      authentication_refreshed_resubmit: "登录状态已刷新，请重新提交本次操作。",
    }
    return messages[error.code] ?? "模板操作失败，请稍后重试。"
  }
  return "模板操作失败，请稍后重试。"
}
