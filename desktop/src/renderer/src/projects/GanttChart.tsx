import { useEffect, useMemo, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import type { GanttTaskDto, ProjectGanttDto } from "../workbench/types"
import { isProjectGanttDto } from "./projectRuntimeValidation"
import { GanttDependencyLayer } from "./GanttDependencyLayer"

export function ProjectGantt({ projectId }: { projectId: string }) {
  const { apiRequest, user } = useAuth()
  const [data, setData] = useState<ProjectGanttDto | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const sequenceRef = useRef(0)

  useEffect(() => {
    let active = true
    const sequence = ++sequenceRef.current
    setLoading(true)
    setError("")
    void apiRequest<ProjectGanttDto>(`/api/v1/projects/${encodeURIComponent(projectId)}/gantt`, { method: "GET" })
      .then((next) => {
        if (!active || sequence !== sequenceRef.current) return
        if (!isProjectGanttDto(next) || next.project_id !== projectId) throw new Error("invalid gantt")
        setData(next)
      })
      .catch((caught) => {
        if (!active || sequence !== sequenceRef.current) return
        setError(detailError(caught, "甘特图加载失败，请稍后重试。"))
      })
      .finally(() => {
        if (active && sequence === sequenceRef.current) setLoading(false)
      })
    return () => { active = false; sequenceRef.current += 1 }
  }, [apiRequest, projectId, user?.id])

  if (loading) return <p role="status">正在加载甘特图…</p>
  if (error) return <p className="form-error" role="alert">{error}</p>
  return data ? <GanttChart data={data} /> : null
}

export function GanttChart({ data }: { data: ProjectGanttDto }) {
  const chartRef = useRef<HTMLElement>(null)
  const cancelledTasks = data.groups.flatMap((group) => group.tasks
    .filter((task) => task.cancelled)
    .map((task) => ({ group, task })))
  const weekdays = data.range.start && data.range.end ? weekdayRange(data.range.start, data.range.end) : []
  const hasActiveRange = weekdays.length > 0
  const activeTasks = useMemo(() => data.groups.flatMap((group) => group.tasks.filter((task) => !task.cancelled)), [data.groups])
  const taskNames = useMemo(() => new Map(activeTasks.map((task) => [task.id, task.name])), [activeTasks])
  if (!hasActiveRange && cancelledTasks.length === 0) return <p className="empty-state">暂无可排期的任务。</p>
  return (
    <section className="gantt-chart" aria-label="工作日甘特图" ref={chartRef}>
      <GanttDependencyLayer tasks={activeTasks} containerRef={chartRef} />
      {hasActiveRange ? <div className="gantt-header gantt-grid" style={gridStyle(weekdays.length)}>
          {weekdays.map((day) => <span key={day}>{day.slice(5)}</span>)}
        </div> : <p className="empty-state">暂无活动排期。</p>}
      {data.groups.map((group) => (
        <section className={`gantt-group${group.cancelled ? " cancelled" : ""}`} key={group.id} aria-labelledby={`gantt-group-${group.id}`}>
          <h3 id={`gantt-group-${group.id}`}>{group.name}{group.cancelled ? "（已取消）" : ""}</h3>
          {group.tasks.length === 0 ? <p className="compact-copy">暂无任务</p> : group.tasks.filter((task) => !task.cancelled).map((task) => (
            <div className="gantt-row" key={task.id}>
              <div className="gantt-task-label">
                <strong>{task.name}</strong>
                <small>{task.assignee?.display_name ?? "待分配"}</small>
              </div>
              <div className="gantt-grid gantt-track" style={gridStyle(weekdays.length)}>
                <GanttBar task={task} weekdays={weekdays} dependencyNames={task.dependency_ids.map((id) => taskNames.get(id)).filter((name): name is string => Boolean(name))} />
              </div>
            </div>
          ))}
        </section>
      ))}
      {cancelledTasks.length > 0 ? <section className="cancelled-task-summary" role="region" aria-label="已取消任务（不在活动时间轴）">
        <h3>已取消任务（不在活动时间轴）</h3>
        <ul>{cancelledTasks.map(({ group, task }) => <li key={task.id}>{task.name} · {group.name} · {task.planned_start_date} 至 {task.planned_end_date}</li>)}</ul>
      </section> : null}
    </section>
  )
}

function GanttBar({ task, weekdays, dependencyNames }: { task: GanttTaskDto; weekdays: string[]; dependencyNames: string[] }) {
  const start = weekdays.findIndex((day) => day >= task.planned_start_date)
  const end = weekdays.findLastIndex((day) => day <= task.planned_end_date)
  if (start < 0 || end < start) return <p className="compact-copy">排期超出当前时间轴：{task.planned_start_date} 至 {task.planned_end_date}</p>
  const column = start + 1
  const span = end - start + 1
  const classes = ["gantt-bar", task.dependency_risk ? "dependency-risk" : ""]
    .filter(Boolean)
    .join(" ")
  return (
    <div
      className={classes}
      role="img"
      aria-label={`${task.name}，${task.planned_start_date} 至 ${task.planned_end_date}，进度 ${task.progress}%${dependencyNames.length ? `，前置任务：${dependencyNames.join("、")}` : ""}${task.dependency_risk ? "，依赖风险" : ""}`}
      data-gantt-task-id={task.id}
      style={{ gridColumn: `${column} / span ${span}` }}
    >
      <span style={{ width: `${task.progress}%` }} />
      <em>{task.progress}%</em>
    </div>
  )
}

function weekdayRange(start: string, end: string): string[] {
  const current = parseDate(start)
  const last = parseDate(end)
  if (!current || !last || current > last) return []
  const result: string[] = []
  while (current <= last) {
    const weekday = current.getUTCDay()
    if (weekday !== 0 && weekday !== 6) result.push(formatDate(current))
    current.setUTCDate(current.getUTCDate() + 1)
  }
  return result
}

function parseDate(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const result = new Date(`${value}T00:00:00Z`)
  return Number.isNaN(result.getTime()) ? null : result
}

function formatDate(date: Date): string {
  return date.toISOString().slice(0, 10)
}

function gridStyle(columns: number) {
  return { gridTemplateColumns: `repeat(${columns}, minmax(54px, 1fr))` }
}

function detailError(error: unknown, fallback: string): string {
  if (error instanceof ApiClientError && error.code === "stale_session_response") return "登录会话已更改，请重新加载项目。"
  return fallback
}
