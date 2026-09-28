import { useEffect, useMemo, useRef, useState, type FormEvent } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { useDangerConfirm } from "../common/DangerConfirmProvider"
import type { ProjectDto, ProjectModuleDto, ProjectModuleMutationDto, ProjectModuleMutationTaskDto, ProjectTaskDto } from "../workbench/types"
import { isProjectModuleMutationDto, isTaskListDto } from "./projectRuntimeValidation"

interface ProjectModulesProps { project: ProjectDto; canManage: boolean; onProjectChange(project: ProjectDto): void; onRefresh(): Promise<ProjectDto | null> }

export function ProjectModules({ project, canManage, onProjectChange, onRefresh }: ProjectModulesProps) {
  const { apiRequest } = useAuth()
  const dangerConfirm = useDangerConfirm()
  const [moduleKey, setModuleKey] = useState("")
  const [plannedStart, setPlannedStart] = useState(project.planned_start_date)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [stale, setStale] = useState(false)
  const [taskRefreshFailed, setTaskRefreshFailed] = useState(false)
  const operationRef = useRef(0)
  const latestProjectRef = useRef(project)
  const remaining = useMemo(() => (project.template_snapshot?.modules ?? []).filter((snapshot) => !project.modules.some((module) => module.module_key === snapshot.module_key)), [project.modules, project.template_snapshot])
  useEffect(() => () => { operationRef.current += 1 }, [])
  useEffect(() => { latestProjectRef.current = project }, [project])

  async function appendModule(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (!moduleKey || !plannedStart || submitting) return
    setSubmitting(true); clearMessages()
    setTaskRefreshFailed(false)
    const operation = ++operationRef.current
    try {
      const current = latestProjectRef.current
      const saved = await apiRequest<ProjectModuleMutationDto>(`/api/v1/projects/${encodeURIComponent(current.id)}/modules`, { method: "POST", body: { module_key: moduleKey, planned_start_date: plannedStart, version: current.version } })
      if (operation !== operationRef.current) return
      if (!isProjectModuleMutationDto(saved)) throw new Error("invalid module")
      const next = mergeModule(latestProjectRef.current, saved)
      latestProjectRef.current = next
      onProjectChange(next)
      setModuleKey("")
      setNotice("模块已追加。")
      try {
        const taskList = await fetchTasks(next.id)
        if (operation !== operationRef.current) return
        const refreshed = mergeTasks(latestProjectRef.current, taskList)
        latestProjectRef.current = refreshed
        onProjectChange(refreshed)
      } catch {
        if (operation !== operationRef.current) return
        setNotice("")
        setTaskRefreshFailed(true)
        setError("模块已追加，任务刷新失败，请刷新")
      }
    } catch (caught) { if (operation === operationRef.current) handleError(caught) } finally { if (operation === operationRef.current) setSubmitting(false) }
  }

  async function retryTaskRefresh(): Promise<void> {
    if (submitting) return
    const operation = ++operationRef.current
    setSubmitting(true)
    setError("")
    try {
      const tasks = await fetchTasks(latestProjectRef.current.id)
      if (operation !== operationRef.current) return
      const refreshed = mergeTasks(latestProjectRef.current, tasks)
      latestProjectRef.current = refreshed
      onProjectChange(refreshed)
      setTaskRefreshFailed(false)
      setNotice("任务列表已刷新。")
    } catch {
      if (operation === operationRef.current) {
        setTaskRefreshFailed(true)
        setError("模块已追加，任务刷新失败，请刷新")
      }
    } finally {
      if (operation === operationRef.current) setSubmitting(false)
    }
  }

  async function fetchTasks(projectId: string): Promise<ProjectTaskDto[]> {
    const response = await apiRequest<{ items: ProjectTaskDto[] }>(`/api/v1/projects/${encodeURIComponent(projectId)}/tasks`, { method: "GET" })
    if (!isTaskListDto(response)) throw new Error("invalid task list")
    return response.items
  }

  async function cancelModule(module: ProjectModuleDto): Promise<void> {
    if (submitting) return
    const confirmed = await dangerConfirm({
      title: "取消模块",
      description: `确定取消模块“${module.name}”吗？其中未取消的任务也将被取消。`,
      confirmLabel: "确认取消",
    })
    if (!confirmed) return
    setSubmitting(true); clearMessages()
    const operation = ++operationRef.current
    try {
      const current = latestProjectRef.current
      const saved = await apiRequest<ProjectModuleMutationDto>(`/api/v1/projects/${encodeURIComponent(current.id)}/modules/${encodeURIComponent(module.id)}`, { method: "DELETE", body: { version: current.version } })
      if (operation !== operationRef.current) return
      if (!isProjectModuleMutationDto(saved)) throw new Error("invalid module")
      const next = mergeModule(latestProjectRef.current, saved)
      latestProjectRef.current = next
      onProjectChange(next)
      setNotice("模块已取消。")
    } catch (caught) { if (operation === operationRef.current) handleError(caught) } finally { if (operation === operationRef.current) setSubmitting(false) }
  }

  function clearMessages(): void { setError(""); setNotice(""); setStale(false) }
  function handleError(caught: unknown): void {
    if (caught instanceof ApiClientError && caught.code === "stale_version") { setStale(true); setError("内容已被其他人更新，请刷新后重试") }
    else setError(caught instanceof ApiClientError && caught.message ? caught.message : "模块操作失败，请稍后重试。")
  }

  async function refreshProject(): Promise<void> {
    const operation = ++operationRef.current
    const next = await onRefresh()
    if (operation === operationRef.current && next) { latestProjectRef.current = next; setStale(false); setError(""); setNotice("已刷新项目版本，未提交选择仍已保留。") }
  }

  return <section className="panel table-panel" aria-labelledby="project-modules-title">
    <div className="panel-heading"><h2 id="project-modules-title">项目模块</h2><span>{project.modules.length} 个</span></div>
    {canManage && remaining.length > 0 ? <form className="module-append-form" onSubmit={appendModule}>
      <div className="field"><label htmlFor="append-module-key">待追加模块</label><select id="append-module-key" value={moduleKey} onChange={(event) => setModuleKey(event.target.value)}><option value="">请选择可追加模块</option>{remaining.map((module) => <option key={module.id} value={module.module_key}>{module.name}</option>)}</select></div>
      <div className="field"><label htmlFor="append-module-start">计划开始日期</label><input id="append-module-start" type="date" value={plannedStart} onChange={(event) => setPlannedStart(event.target.value)} /></div>
      <button className="primary-button module-append-submit" type="submit" disabled={submitting || !moduleKey || !plannedStart}>追加模块</button>
    </form> : canManage ? <p className="supporting-copy">当前没有可追加模块；已取消模块不可重新追加。</p> : null}
    {error ? <p className="form-error banner" role="alert">{error}</p> : null}{notice ? <p className="notice" role="status">{notice}</p> : null}
    {taskRefreshFailed ? <button className="secondary-button" type="button" disabled={submitting} onClick={() => void retryTaskRefresh()}>刷新任务</button> : null}
    {stale ? <button className="secondary-button" type="button" onClick={() => void refreshProject()}>刷新项目</button> : null}
    {project.modules.length === 0 ? <p className="empty-state">暂无项目模块。</p> : <div className="module-card-grid">{project.modules.map((module) => <article className={`module-summary-card${module.status === "cancelled" ? " cancelled" : ""}`} key={module.id}><div className="module-card-head"><h3>{module.name}</h3><div className="module-card-actions"><span className={`badge ${module.status === "active" ? "success" : "muted"}`}>{module.status === "active" ? "进行中" : "已取消"}</span>{canManage && module.status === "active" ? <button className="danger-button compact" type="button" aria-label={`取消模块：${module.name}`} disabled={submitting} onClick={() => void cancelModule(module)}>取消模块</button> : null}</div></div><p>{module.description || "无说明"}</p><small>{module.planned_start_date ?? "待排期"} 至 {module.planned_end_date ?? "待排期"}</small></article>)}</div>}
  </section>
}

function mergeModule(project: ProjectDto, saved: ProjectModuleMutationDto): ProjectDto {
  const module: ProjectModuleDto = { id: saved.id, module_key: saved.module_key, name: saved.name, description: saved.description, status: saved.status, sort_order: saved.sort_order, planned_start_date: saved.planned_start_date, planned_end_date: saved.planned_end_date }
  const modules = project.modules.some((item) => item.id === saved.id) ? project.modules.map((item) => item.id === saved.id ? module : item) : [...project.modules, module].sort((a, b) => a.sort_order - b.sort_order)
  const existingTasks = project.tasks ?? []
  const incoming = saved.tasks.map((task) => enrichTask(task, existingTasks.find((item) => item.id === task.id)))
  const incomingIds = new Set(incoming.map((task) => task.id))
  const tasks = [...existingTasks.filter((task) => !incomingIds.has(task.id)), ...incoming]
  return { ...project, modules, tasks, completion: completionFrom(tasks), version: saved.project_version }
}
function enrichTask(task: ProjectModuleMutationTaskDto, existing?: ProjectTaskDto): ProjectTaskDto { return { ...task, collaborator_user_ids: existing?.collaborator_user_ids ?? [], dependency_keys: existing?.dependency_keys ?? [] } }
function mergeTasks(project: ProjectDto, tasks: ProjectTaskDto[]): ProjectDto { return { ...project, tasks, completion: completionFrom(tasks) } }
function completionFrom(tasks: ProjectTaskDto[]): number { const active = tasks.filter((task) => task.status !== "cancelled"); return active.length === 0 ? 0 : Math.round(active.reduce((sum, task) => sum + task.progress, 0) / active.length) }
