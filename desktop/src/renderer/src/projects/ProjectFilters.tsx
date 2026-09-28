import type { FormEvent } from "react"

import type { ProjectDto, ProjectStatus } from "../workbench/types"

export interface ProjectFilterValues {
  search: string
  status: "" | ProjectStatus
  leaderUserId: string
  industry: string
  moduleKey: string
}

export const emptyProjectFilters: ProjectFilterValues = {
  search: "",
  status: "",
  leaderUserId: "",
  industry: "",
  moduleKey: "",
}

export interface ProjectFilterOptions {
  leaders: ProjectDto["leader"][]
  industries: string[]
  modules: Array<{ key: string; name: string }>
}

export function ProjectFilters({
  value,
  options,
  disabled,
  onChange,
  onApply,
}: {
  value: ProjectFilterValues
  options: ProjectFilterOptions
  disabled: boolean
  onChange(value: ProjectFilterValues): void
  onApply(): void
}) {
  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault()
    onApply()
  }

  return (
    <form className="panel project-filter-grid" onSubmit={submit}>
      <div className="field">
        <label htmlFor="project-search">搜索项目或企业</label>
        <input
          id="project-search"
          value={value.search}
          onChange={(event) => onChange({ ...value, search: event.target.value })}
        />
      </div>
      <div className="field">
        <label htmlFor="project-status">项目状态</label>
        <select
          id="project-status"
          value={value.status}
          onChange={(event) => onChange({
            ...value,
            status: projectStatusFilter(event.target.value),
          })}
        >
          <option value="">全部状态</option>
          <option value="draft">草稿</option>
          <option value="active">进行中</option>
          <option value="paused">已暂停</option>
          <option value="completed">已完成</option>
          <option value="cancelled">已取消</option>
        </select>
      </div>
      <div className="field">
        <label htmlFor="project-leader">项目负责人</label>
        <select
          id="project-leader"
          value={value.leaderUserId}
          onChange={(event) => onChange({ ...value, leaderUserId: event.target.value })}
        >
          <option value="">全部负责人</option>
          {options.leaders.map((leader) => (
            <option key={leader.id} value={leader.id}>{leader.display_name}</option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="project-industry">行业</label>
        <select
          id="project-industry"
          value={value.industry}
          onChange={(event) => onChange({ ...value, industry: event.target.value })}
        >
          <option value="">全部行业</option>
          {options.industries.map((industry) => (
            <option key={industry} value={industry}>{industry}</option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="project-module">模块</label>
        <select
          id="project-module"
          value={value.moduleKey}
          onChange={(event) => onChange({ ...value, moduleKey: event.target.value })}
        >
          <option value="">全部模块</option>
          {options.modules.map((module) => (
            <option key={module.key} value={module.key}>{module.name}</option>
          ))}
        </select>
      </div>
      <div className="filter-actions">
        <button className="primary-button" type="submit" disabled={disabled}>筛选</button>
      </div>
    </form>
  )
}

function projectStatusFilter(value: string): ProjectFilterValues["status"] {
  if (value === "draft" || value === "active" || value === "paused" || value === "completed" || value === "cancelled") return value
  return ""
}
