import { useEffect, useMemo, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { fetchAllPages, requirePage } from "../workbench/fetchAllPages"
import { isProjectDto } from "../workbench/runtimeValidation"
import type { PageDto, ProjectDto, ProjectStatus } from "../workbench/types"
import {
  emptyProjectFilters,
  ProjectFilters,
  type ProjectFilterOptions,
  type ProjectFilterValues,
} from "./ProjectFilters"

const PAGE_SIZE = 20
const FACET_PAGE_SIZE = 100
const emptyFilterOptions: ProjectFilterOptions = { leaders: [], industries: [], modules: [] }

export function ProjectsPage() {
  const { apiRequest, user } = useAuth()
  const [draftFilters, setDraftFilters] = useState<ProjectFilterValues>(emptyProjectFilters)
  const [appliedFilters, setAppliedFilters] = useState<ProjectFilterValues>(emptyProjectFilters)
  const [page, setPage] = useState(1)
  const [result, setResult] = useState<PageDto<ProjectDto> | null>(null)
  const [options, setOptions] = useState<ProjectFilterOptions>(emptyFilterOptions)
  const [loading, setLoading] = useState(true)
  const [facetsLoading, setFacetsLoading] = useState(true)
  const [error, setError] = useState("")
  const [facetError, setFacetError] = useState("")
  const requestSequence = useRef(0)
  const facetSequence = useRef(0)
  const path = useMemo(() => projectListPath(appliedFilters, page), [appliedFilters, page])

  useEffect(() => {
    let active = true
    const sequence = ++requestSequence.current
    setLoading(true)
    setError("")
    void apiRequest<unknown>(path, { method: "GET" })
      .then((next) => {
        if (!active || sequence !== requestSequence.current) return
        setResult(requirePage(next, page, PAGE_SIZE, isProjectDto))
      })
      .catch((caught) => {
        if (!active || sequence !== requestSequence.current) return
        setError(projectListError(caught))
      })
      .finally(() => {
        if (active && sequence === requestSequence.current) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [apiRequest, path, user?.id])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    const sequence = ++facetSequence.current
    setFacetsLoading(true)
    setFacetError("")
    setOptions(emptyFilterOptions)
    void fetchAllPages({
      apiRequest,
      pathForPage: (facetPage, pageSize) => `/api/v1/projects?page=${facetPage}&page_size=${pageSize}`,
      itemKey: (project: ProjectDto) => project.id,
      validateItem: isProjectDto,
      signal: controller.signal,
      pageSize: FACET_PAGE_SIZE,
    })
      .then((projects) => {
        if (!active || sequence !== facetSequence.current) return
        setOptions(filterOptionsFrom(projects))
      })
      .catch((caught) => {
        if (!active || sequence !== facetSequence.current || isAbortError(caught)) return
        setOptions(emptyFilterOptions)
        setFacetError(facetLoadError(caught))
      })
      .finally(() => {
        if (active && sequence === facetSequence.current) setFacetsLoading(false)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [apiRequest, user?.id])

  const pageCount = Math.max(1, Math.ceil((result?.total ?? 0) / PAGE_SIZE))
  const canCreate = user?.role === "admin" || user?.role === "project_lead"

  function applyFilters(): void {
    setPage(1)
    setAppliedFilters(normalizeFilters(draftFilters))
  }

  return (
    <div id="projects" className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">项目管理</p>
          <h1 aria-label="项目工作台">项目工作台</h1>
          <p className="supporting-copy">查看进展与交付范围，按负责人、行业和模块定位项目。</p>
        </div>
        {canCreate ? <a className="primary-button button-link" href="#projects/new">新建项目</a> : null}
      </header>

      <ProjectFilters
        value={draftFilters}
        options={options}
        disabled={loading || facetsLoading}
        onChange={setDraftFilters}
        onApply={applyFilters}
      />

      {facetError ? <p className="form-error banner" role="alert">{facetError}</p> : null}

      <section className="panel table-panel" aria-labelledby="project-list-title">
        <div className="panel-heading">
          <h2 id="project-list-title">项目列表</h2>
          <span>{result?.total ?? 0} 个项目</span>
        </div>
        {loading ? <p role="status">正在加载项目…</p> : error ? (
          <p className="form-error" role="alert">{error}</p>
        ) : !result || result.items.length === 0 ? (
          <p className="empty-state">暂无符合条件的项目。</p>
        ) : (
          <div className="project-list-grid">
            {result.items.map((project) => (
              <article className="project-card" aria-labelledby={`project-card-${project.id}`} key={project.id}>
                <div className="project-card-title">
                  <h3 id={`project-card-${project.id}`}>{project.name}</h3>
                  <span className="project-card-code">{project.project_code}</span>
                </div>
                <div className="project-card-meta">
                  <div><span className="project-card-label">企业 / 行业</span><span>{project.enterprise_name} · {project.industry}</span></div>
                  <div><span className="project-card-label">状态</span><span className={`badge ${projectStatusClass(project.status)}`}>{projectStatusLabel(project.status)}</span></div>
                  <div><span className="project-card-label">负责人</span><span>{project.leader.display_name}</span></div>
                </div>
                <div className="project-card-modules">
                  {project.modules.length === 0 ? <span className="project-card-label">—</span> : project.modules.map((module) => (
                    <span className="chip" key={module.id}>{module.name}</span>
                  ))}
                </div>
                <div className="project-card-progress">
                  <div className="completion-row"><span className="project-card-label">完成度</span><span className="completion-value">{project.completion}%</span></div>
                  <progress className="completion-meter" max="100" value={project.completion} aria-label={`${project.name} 完成度 ${project.completion}%`} />
                </div>
                <div className="project-card-footer">
                  <span className="project-card-date">{project.planned_start_date} 至 {project.planned_end_date ?? "待排期"}</span>
                  <a className="secondary-button compact button-link" aria-label={`进入项目：${project.name}`} href={`#projects/${encodeURIComponent(project.id)}`}>进入项目</a>
                </div>
              </article>
            ))}
          </div>
        )}
        {!loading && !error && result ? (
          <div className="pagination" aria-label="项目分页">
            <button className="secondary-button compact" type="button" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>上一页</button>
            <span>第 {page} / {pageCount} 页</span>
            <button className="secondary-button compact" type="button" disabled={page >= pageCount} onClick={() => setPage((current) => current + 1)}>下一页</button>
          </div>
        ) : null}
      </section>
    </div>
  )
}

function projectListPath(filters: ProjectFilterValues, page: number): string {
  const params = new URLSearchParams()
  if (filters.search) params.append("search", filters.search)
  if (filters.status) params.append("status", filters.status)
  if (filters.leaderUserId) params.append("leader_user_id", filters.leaderUserId)
  if (filters.industry) params.append("industry", filters.industry)
  if (filters.moduleKey) params.append("module_key", filters.moduleKey)
  params.append("page", String(page))
  params.append("page_size", String(PAGE_SIZE))
  return `/api/v1/projects?${params.toString()}`
}

function normalizeFilters(filters: ProjectFilterValues): ProjectFilterValues {
  return {
    ...filters,
    search: filters.search.trim(),
    industry: filters.industry.trim(),
    moduleKey: filters.moduleKey.trim(),
  }
}

function filterOptionsFrom(projects: ProjectDto[]): ProjectFilterOptions {
  const leaders = new Map<string, ProjectDto["leader"]>()
  const industries = new Set<string>()
  const modules = new Map<string, { key: string; name: string }>()
  for (const project of projects) {
    leaders.set(project.leader.id, project.leader)
    industries.add(project.industry)
    for (const module of project.modules) modules.set(module.module_key, { key: module.module_key, name: module.name })
  }
  return {
    leaders: [...leaders.values()].sort((left, right) => left.display_name.localeCompare(right.display_name, "zh-CN")),
    industries: [...industries].sort((left, right) => left.localeCompare(right, "zh-CN")),
    modules: [...modules.values()].sort((left, right) => left.name.localeCompare(right.name, "zh-CN")),
  }
}

function projectStatusLabel(status: ProjectStatus): string {
  return {
    draft: "草稿",
    active: "进行中",
    paused: "已暂停",
    completed: "已完成",
    cancelled: "已取消",
  }[status]
}

function projectStatusClass(status: ProjectStatus): string {
  if (status === "active" || status === "completed") return "success"
  if (status === "paused") return "warning"
  return "muted"
}

function projectListError(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "stale_session_response") return "登录会话已更改，请重新加载项目。"
  return "项目加载失败，请稍后重试。"
}

function facetLoadError(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "stale_session_response") return "登录会话已更改，请重新加载筛选项。"
  return "筛选项加载失败，请稍后重试。"
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError"
}
