import { useCallback, useEffect, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import type { ProjectDetailTab } from "../routing/useHashRoute"
import { isProjectDto } from "../workbench/runtimeValidation"
import type { ProjectDto, ProjectTaskDto } from "../workbench/types"
import { ProjectGantt } from "./GanttChart"
import { ProjectManagement } from "./ProjectManagement"
import { ProjectOverview } from "./ProjectOverview"
import { isProjectMemberDto, isProjectTaskDto } from "./projectRuntimeValidation"
import { TaskTable } from "./TaskTable"
import { ProjectLibrary } from "../library/ProjectLibrary"
import { ResearchWorkspace } from "../research/ResearchWorkspace"
import { SolutionDesign } from "../solutions/SolutionDesign"
import { allowNextHashNavigation, registerHashNavigationGuard } from "../routing/navigationGuard"
import { ProjectGuidanceCard } from "../guidance/ProjectGuidanceCard"
import { isDocumentDetail, isDocumentVersion } from "../documents/runtimeValidation"

interface ProjectDetailPageProps { projectId: string; tab: ProjectDetailTab; solutionId?: string; solutionMode?: 'edit'; opportunityId?: string }

const tabs: Array<{ id: ProjectDetailTab; label: string }> = [
  { id: "overview", label: "概览" },
  { id: "tasks", label: "任务" },
  { id: "research", label: "调研" },
  { id: "delivery", label: "方案设计" },
  { id: "library", label: "文件库" },
  { id: "management", label: "项目管理" },
]

export function ProjectDetailPage({ projectId, tab, solutionId, solutionMode, opportunityId }: ProjectDetailPageProps) {
  const { apiRequest, user } = useAuth()
  const [project, setProject] = useState<ProjectDto | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [researchDirty, setResearchDirty] = useState(false)
  const [exportingPlan, setExportingPlan] = useState(false)
  const [exportNotice, setExportNotice] = useState("")
  const [exportError, setExportError] = useState("")
  const sequenceRef = useRef(0)

  const loadProject = useCallback(async (): Promise<ProjectDto | null> => {
    const sequence = ++sequenceRef.current
    setError("")
    try {
      const next = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}`, { method: "GET" })
      if (sequence !== sequenceRef.current) return null
      if (!isProjectDetail(next) || next.id !== projectId) throw new Error("invalid project detail")
      setProject(next)
      return next
    } catch (caught) {
      if (sequence !== sequenceRef.current) return null
      setError(projectError(caught))
      return null
    }
  }, [apiRequest, projectId])

  useEffect(() => {
    let active = true
    setProject(null)
    setLoading(true)
    void loadProject().finally(() => { if (active) setLoading(false) })
    return () => { active = false; sequenceRef.current += 1 }
  }, [loadProject, user?.id])

  const canManage = Boolean(user && project && (user.role === "admin" || (user.id === project.leader_user_id && user.role === "project_lead")))
  const projectMembership = project?.members?.find((member) => member.user_id === user?.id)
  const canFillResearch = Boolean(user && project && (
    user.role === "admin"
    || (user.id === project.leader_user_id && user.role === "project_lead")
    || (projectMembership?.role === "member" && (user.role === "fde_engineer" || user.role === "project_lead"))
  ))
  const hrefFor = (next: ProjectDetailTab) => `#projects/${encodeURIComponent(projectId)}${next === "overview" ? "" : `?tab=${next}`}`
  const handleTasksChange = useCallback((tasks: ProjectTaskDto[]) => {
    setProject((current) => current ? { ...current, tasks, completion: completionFrom(tasks) } : current)
  }, [])
  const handleProjectChange = useCallback((next: ProjectDto) => setProject(next), [])

  async function exportProjectPlan(): Promise<void> {
    if (!project || !canManage || exportingPlan) return
    setExportingPlan(true)
    setExportNotice("")
    setExportError("")
    try {
      const latestProject = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(project.id)}`, { method: "GET" })
      if (!isProjectDetail(latestProject) || latestProject.id !== project.id) throw new Error("invalid project plan project response")
      setProject(latestProject)
      const created = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(project.id)}/documents`, {
        method: "POST",
        body: { document_type: "project_plan_progress", expected_version: latestProject.version },
      })
      if (!isDocumentDetail(created)) throw new Error("invalid project plan document")
      const generated = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(project.id)}/documents/${encodeURIComponent(created.id)}/generate`, {
        method: "POST",
        body: { version: created.version },
      })
      if (!isDocumentVersion(generated)) throw new Error("invalid project plan generation")
      const projectVersion = typeof (created as unknown as Record<string, unknown>).project_version === "number"
        ? Number((created as unknown as Record<string, unknown>).project_version)
        : latestProject.version
      setProject((current) => current ? { ...current, version: projectVersion } : current)
      setExportNotice("项目计划及进度已提交生成，完成后会自动进入文件库并保留为新版本。")
    } catch (caught) {
      setExportError(projectPlanExportError(caught))
    } finally {
      setExportingPlan(false)
    }
  }

  useEffect(() => {
    if (!researchDirty || tab !== 'research') return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = "" }
    const focusDirty = () => window.setTimeout(() => {
      document.querySelector<HTMLElement>('[data-research-dirty="true"] input:not([disabled]), [data-research-dirty="true"] textarea:not([disabled]), [data-research-dirty="true"] select:not([disabled])')?.focus()
    }, 0)
    const confirmNavigation = () => {
      const accepted = window.confirm("当前表单有未保存修改，确定离开吗？")
      if (!accepted) focusDirty()
      return accepted
    }
    const unregister = registerHashNavigationGuard(confirmNavigation)
    const click = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>('a[href^="#"]') : null
      const nextHash = target?.getAttribute("href")
      if (!nextHash || nextHash === window.location.hash) return
      if (!window.confirm("当前表单有未保存修改，确定离开吗？")) {
        event.preventDefault()
        event.stopImmediatePropagation()
        focusDirty()
        return
      }
      allowNextHashNavigation(nextHash)
    }
    window.addEventListener("beforeunload", warn)
    document.addEventListener("click", click, true)
    return () => {
      unregister()
      window.removeEventListener("beforeunload", warn)
      document.removeEventListener("click", click, true)
    }
  }, [researchDirty, tab])

  return (
    <div id="project-detail" className={`page-stack${tab === 'delivery' && solutionId ? ' project-secondary-page' : ''}`}>
      <header className="page-header">
        <div><p className="eyebrow">项目管理</p><h1>项目详情</h1>{project ? <p className="supporting-copy">{project.name} · {project.enterprise_name}</p> : null}</div>
        <div className="page-header-actions">
          {project && canManage ? <button className="secondary-button" type="button" disabled={exportingPlan} onClick={() => { void exportProjectPlan() }}>{exportingPlan ? "正在提交…" : "导出项目计划及进度"}</button> : null}
        </div>
      </header>
      {exportNotice ? <p className="notice" role="status">{exportNotice}</p> : null}
      {exportError ? <p className="form-error banner" role="alert">{exportError}</p> : null}
      <div className="project-sticky-navigation">
      <nav className="detail-tabs" role="tablist" aria-label="项目详情导航">
        {tabs.map((item, index) => <a key={item.id} id={`project-tab-${item.id}`} href={hrefFor(item.id)} role="tab" aria-controls="project-detail-tabpanel" aria-selected={tab === item.id} tabIndex={tab === item.id ? 0 : -1} className={tab === item.id ? "active" : ""} onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return
          event.preventDefault()
          const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : event.key === "ArrowLeft" ? (index - 1 + tabs.length) % tabs.length : (index + 1) % tabs.length
          const target = event.currentTarget.parentElement?.querySelectorAll<HTMLAnchorElement>('[role="tab"]')[next]
          target?.focus()
          target?.click()
        }}>{item.label}</a>)}
      </nav>
      <a className="secondary-button button-link compact" href="#projects">返回项目列表</a>
      </div>
      {loading ? <p role="status">正在加载项目详情…</p> : error ? <p className="form-error banner" role="alert">{error}</p> : project ? (
        <div id="project-detail-tabpanel" role="tabpanel" aria-labelledby={`project-tab-${tab}`}>
          {tab === "overview" ? <div className="page-stack"><ProjectOverview project={project} canManage={canManage} onProjectChange={handleProjectChange} onRefresh={loadProject} guidanceSlot={<ProjectGuidanceCard projectId={project.id} canManage={canManage} />} /><ProjectGantt projectId={project.id} /></div> : null}
          {tab === "tasks" ? <TaskTable projectId={project.id} initialTasks={project.tasks ?? []} modules={project.modules} members={project.members ?? []} canManage={canManage} onTasksChange={handleTasksChange} /> : null}
          {tab === "management" ? <ProjectManagement project={project} canManage={canManage} onProjectChange={handleProjectChange} onRefresh={loadProject} /> : null}
          {tab === "library" ? <ProjectLibrary projectId={project.id} canManage={canManage} /> : null}
          {tab === "research" ? <ResearchWorkspace project={project} canFill={canFillResearch} canManage={canManage} onDirtyChange={setResearchDirty} initialOpportunityId={opportunityId} /> : null}
          {tab === "delivery" ? <SolutionDesign projectId={project.id} canManage={canManage} solutionId={solutionId} mode={solutionMode} opportunityId={opportunityId} /> : null}
        </div>
      ) : null}
    </div>
  )
}

function isProjectDetail(value: unknown): value is ProjectDto {
  if (!isProjectDto(value)) return false
  const detail = value as ProjectDto
  return Array.isArray(detail.tasks)
    && detail.tasks.every(isProjectTaskDto)
    && Array.isArray(detail.members)
    && detail.members.every(isProjectMemberDto)
    && isTemplateSnapshot(detail.template_snapshot)
}

function isTemplateSnapshot(value: unknown): boolean {
  if (!isRecord(value) || !Array.isArray(value.modules)) return false
  if (!["template_name", "industry_name", "description"].every((key) => typeof value[key] === "string")) return false
  if (![value.template_id, value.version_id].every((item) => item === null || typeof item === "string")) return false
  if (value.version_number !== undefined && (!Number.isInteger(value.version_number) || Number(value.version_number) <= 0)) return false
  if (value.creation_source !== undefined && !["template", "presurvey", "manual"].includes(String(value.creation_source))) return false
  return value.modules.every(isProjectTemplateSnapshotModule)
}

function isProjectTemplateSnapshotModule(value: unknown): boolean {
  return isRecord(value)
    && (value.id === null || typeof value.id === "string")
    && ["module_catalog_id", "module_key", "name", "description"].every((key) => typeof value[key] === "string")
    && Number.isInteger(value.sort_order)
    && Array.isArray(value.tasks)
    && value.tasks.every(isProjectTemplateSnapshotTask)
}

function isProjectTemplateSnapshotTask(value: unknown): boolean {
  return isRecord(value)
    && (value.id === null || typeof value.id === "string")
    && ["task_key", "name", "description"].every((key) => typeof value[key] === "string")
    && Number.isInteger(value.duration_days)
    && Number(value.duration_days) > 0
    && typeof value.default_assignee_role === "string"
    && Number.isInteger(value.sort_order)
    && Array.isArray(value.dependency_keys)
    && value.dependency_keys.every((key) => typeof key === "string")
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function projectError(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "project_not_found") return "项目不存在或已被删除。"
  if (error instanceof ApiClientError && error.code === "forbidden") return "你没有权限查看该项目。"
  return "项目详情加载失败，请稍后重试。"
}

function projectPlanExportError(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (["document_template_not_published", "template_version_not_published", "document_template_not_found"].includes(error.code)) {
      return "尚未发布“项目计划及进度”模板。请前往“文档模板”上传模板，并将该版本发布后再导出。"
    }
    if (error.code === "unknown_document_type") {
      return "当前线上服务尚未支持“项目计划及进度”导出。请先更新服务端；更新后还需在“文档模板”中上传并发布对应模板。"
    }
    if (error.code === "template_document_type_mismatch") return "当前发布的模板类型不是“项目计划及进度”，请重新上传到正确的模板卡片并发布。"
    if (["template_version_not_found", "document_not_found"].includes(error.code)) return "导出所需的模板或文档草稿已失效，请刷新页面后重新导出。"
    if (["invalid_definition", "invalid_request", "document_generation_failed"].includes(error.code)) return `项目计划及进度生成失败：${error.message}`
    if (error.code === "network_error") return "无法连接服务端，请检查网络后重试。"
    if (error.code === "stale_version") return "项目刚刚发生变化，请刷新后重新导出。"
    if (error.code === "forbidden") return "只有项目负责人或管理员可以导出项目计划及进度。"
    return `项目计划及进度导出失败：${error.message}`
  }
  if (error instanceof Error && error.message.startsWith("invalid project plan")) {
    return "服务端返回的项目计划数据格式不兼容，请更新服务端后重试。"
  }
  return "项目计划及进度导出失败，请稍后重试。"
}

function completionFrom(tasks: ProjectTaskDto[]): number {
  const active = tasks.filter((task) => task.status !== "cancelled")
  return active.length === 0 ? 0 : Math.round(active.reduce((total, task) => total + task.progress, 0) / active.length)
}
