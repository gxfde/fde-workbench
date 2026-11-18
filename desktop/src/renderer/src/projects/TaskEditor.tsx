import { useEffect, useRef, useState, type FormEvent } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import type { ProjectMemberDto, ProjectTaskDto, ProjectTaskStatus } from "../workbench/types"
import { isProjectTaskDto } from "./projectRuntimeValidation"
import { TaskDependencyPicker } from "./TaskDependencyPicker"

interface TaskEditorProps {
  projectId: string
  task: ProjectTaskDto
  tasks: ProjectTaskDto[]
  members: ProjectMemberDto[]
  canManage: boolean
  onSaved(task: ProjectTaskDto): void
  onClose(): void
}

interface TaskDraft {
  status: ProjectTaskStatus
  progress: string
  blockedReason: string
  plannedStartDate: string
  plannedEndDate: string
  durationDays: string
  assigneeUserId: string
  collaboratorUserIds: string[]
  dependencyIds: string[]
  description: string
}

type DraftField = keyof TaskDraft

const DRAFT_GROUPS = [
  { label: "状态、进度与阻塞原因", fields: ["status", "progress", "blockedReason"] },
  { label: "计划开始、结束日期与工期", fields: ["plannedStartDate", "plannedEndDate", "durationDays"], manage: true },
  { label: "负责人和协作人", fields: ["assigneeUserId", "collaboratorUserIds"], manage: true },
  { label: "前置任务", fields: ["dependencyIds"], manage: true },
  { label: "任务说明", fields: ["description"] },
] satisfies Array<{ label: string; fields: DraftField[]; manage?: boolean }>

type DraftGroup = (typeof DRAFT_GROUPS)[number]
interface DraftConflict {
  group: DraftGroup
  opened: TaskDraft
  latest: TaskDraft
  local: TaskDraft
}

function sameGroup(a: TaskDraft, b: TaskDraft, group: DraftGroup): boolean {
  return group.fields.every((field) => {
    const x = a[field]
    const y = b[field]
    return Array.isArray(x) && Array.isArray(y)
      ? x.length === y.length && x.every((id) => y.includes(id))
      : x === y
  })
}

function copyGroup(target: TaskDraft, source: TaskDraft, group: DraftGroup): TaskDraft {
  return { ...target, ...Object.fromEntries(group.fields.map((field) => [field, source[field]])) }
}

export function TaskEditor({ projectId, task, tasks, members, canManage, onSaved, onClose }: TaskEditorProps) {
  const { apiRequest } = useAuth()
  const [draft, setDraft] = useState<TaskDraft>(() => taskDraft(task))
  const [baseline, setBaseline] = useState(() => ({ draft: taskDraft(task), version: task.version }))
  const [conflicts, setConflicts] = useState<DraftConflict[]>([])
  const version = baseline.version
  const [saving, setSaving] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [stale, setStale] = useState(false)
  const generationRef = useRef(0)
  const [denied, setDenied] = useState(false)
  const managementLost = !canManage && DRAFT_GROUPS.some((group) => group.manage && !sameGroup(draft, baseline.draft, group))

  useEffect(() => {
    setDraft(taskDraft(task))
    setBaseline({ draft: taskDraft(task), version: task.version })
    setConflicts([])
    setDenied(false)
    setError("")
    setNotice("")
    setStale(false)
    return () => { generationRef.current += 1 }
  }, [task.id])

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (saving || stale || refreshing || conflicts.length || managementLost || denied) return
    const [execution, schedule, people, dependencies] = DRAFT_GROUPS
    const changed = (group: DraftGroup) => !sameGroup(draft, baseline.draft, group)
    const executionChanged = changed(execution)
    const scheduleChanged = canManage && changed(schedule)
    const progress = Number(draft.progress)
    if (executionChanged && (!Number.isInteger(progress) || progress < 0 || progress > 100)) {
      setError("进度必须是 0 到 100 的整数。")
      return
    }
    const duration = Number(draft.durationDays)
    if (scheduleChanged && (!Number.isInteger(duration) || duration < 1)) {
      setError("工期必须是大于 0 的整数。")
      return
    }
    if (scheduleChanged && workdayDuration(draft.plannedStartDate, draft.plannedEndDate) !== duration) {
      setError("计划开始日期、结束日期与工期不一致，请调整后重试。")
      return
    }
    if (executionChanged && draft.status === "blocked" && !draft.blockedReason.trim()) {
      setError("阻塞状态必须填写阻塞原因。")
      return
    }
    // 服务端四态分支会拒绝或强改进度；先在本地说明，避免提交后拿到无指向的失败。
    if (executionChanged) {
      const problem = progressConflict(draft.status, progress, Number(baseline.draft.progress))
      if (problem) {
        setError(problem)
        return
      }
    }
    const body: Record<string, unknown> = { version }
    if (executionChanged) {
      Object.assign(body, { status: draft.status, progress })
      if (draft.status === "blocked") body.blocked_reason = draft.blockedReason.trim()
    }
    if (canManage && draft.description.trim() !== baseline.draft.description.trim()) body.description = draft.description.trim()
    if (scheduleChanged) Object.assign(body, {
      planned_start_date: draft.plannedStartDate,
      planned_end_date: draft.plannedEndDate,
      duration_days: duration,
    })
    if (canManage && changed(people)) Object.assign(body, {
      assignee_user_id: draft.assigneeUserId || null,
      collaborator_user_ids: draft.collaboratorUserIds,
    })
    if (canManage && changed(dependencies)) body.dependency_ids = draft.dependencyIds
    if (Object.keys(body).length === 1) {
      setError("")
      setNotice("任务没有需要保存的修改。")
      return
    }
    const generation = ++generationRef.current
    setSaving(true)
    setError("")
    setNotice("")
    setStale(false)
    try {
      const saved = await apiRequest<ProjectTaskDto>(taskPath(projectId, task.id), { method: "PATCH", body })
      if (generation !== generationRef.current) return
      if (!isProjectTaskDto(saved) || saved.id !== task.id) throw new Error("invalid task")
      onSaved(saved)
    } catch (caught) {
      if (generation !== generationRef.current) return
      if (caught instanceof ApiClientError && caught.code === "stale_version") {
        setStale(true)
        setError("内容已被其他人更新，请刷新后重试")
      } else if (caught instanceof ApiClientError && caught.status === 404) {
        // 任务已不存在或已不可见：继续提交只会重复失败，锁住本窗口。
        setDenied(true)
        setError("任务已不可编辑，未保存。")
      } else if (caught instanceof ApiClientError && caught.status === 403) {
        // 字段级越权不应连坐同窗口内合法的进度/阻塞原因编辑。
        setError("本次修改包含你无权变更的内容，未保存。请只改状态、进度或阻塞原因后重试。")
      } else setError(taskError(caught))
    } finally {
      if (generation === generationRef.current) setSaving(false)
    }
  }

  async function refreshVersion(): Promise<void> {
    if (refreshing) return
    const generation = ++generationRef.current
    setRefreshing(true)
    setNotice("")
    try {
      const current = await apiRequest<ProjectTaskDto>(taskPath(projectId, task.id), { method: "GET" })
      if (generation !== generationRef.current) return
      if (!isProjectTaskDto(current) || current.id !== task.id) throw new Error("invalid task")
      const latest = taskDraft(current)
      const nextConflicts: DraftConflict[] = []
      let merged = latest
      for (const group of DRAFT_GROUPS) {
        if (sameGroup(draft, baseline.draft, group)) continue
        if (!sameGroup(latest, baseline.draft, group) && !sameGroup(latest, draft, group)) {
          nextConflicts.push({ group, opened: baseline.draft, latest, local: draft })
        }
        merged = copyGroup(merged, draft, group)
      }
      setBaseline({ draft: latest, version: current.version })
      setDraft(merged)
      setConflicts(nextConflicts)
      setStale(false)
      setError("")
      setNotice(nextConflicts.length ? "同组内容已变更，请选择保留哪一组值。" : "已合并最新任务与未保存的修改。")
    } catch (caught) {
      if (generation === generationRef.current) setError(taskError(caught))
    } finally {
      if (generation === generationRef.current) setRefreshing(false)
    }
  }

  return (
    <div className="dialog-backdrop">
      <section className="dialog task-dialog" role="dialog" aria-modal="true" aria-labelledby="task-editor-title">
        <div className="panel-heading"><h2 id="task-editor-title">更新任务：{task.name}</h2><span>v{version}</span></div>
        <form onSubmit={submit}>
          <div className="task-dialog-grid" inert={saving || refreshing || conflicts.length > 0 || denied}>
            <Field label="状态" id="task-edit-status">
              <select id="task-edit-status" value={draft.status} onChange={(event) => {
                const status = event.target.value as ProjectTaskStatus
                setDraft({
                  ...draft,
                  status,
                  progress: progressForStatus(status, draft.progress),
                  blockedReason: status === "blocked" ? draft.blockedReason : "",
                })
              }}>
                <option value="not_started">未开始</option><option value="in_progress">进行中</option><option value="blocked">阻塞</option><option value="completed">已完成</option>{canManage ? <option value="cancelled">已取消</option> : null}
              </select>
            </Field>
            <Field label="进度" id="task-edit-progress">
              <input id="task-edit-progress" type="number" min="0" max="100" step="1" value={draft.progress} onChange={(event) => setDraft({ ...draft, progress: event.target.value })} />
            </Field>
            <Field label="阻塞原因" id="task-edit-blocked" wide>
              <textarea id="task-edit-blocked" rows={2} disabled={draft.status !== "blocked"} value={draft.blockedReason} onChange={(event) => setDraft({ ...draft, blockedReason: event.target.value })} />
              {draft.status !== "blocked" ? <small className="field-hint">非阻塞状态不会提交阻塞原因。</small> : null}
            </Field>
            <Field label="任务说明" id="task-edit-description" wide>
              <textarea id="task-edit-description" rows={2} value={draft.description} disabled={!canManage} onChange={(event) => setDraft({ ...draft, description: event.target.value })} />
              {!canManage ? <small className="field-hint">任务说明由项目负责人维护。</small> : null}
            </Field>
            {canManage ? <>
              <Field label="计划开始日期" id="task-edit-start"><input id="task-edit-start" type="date" value={draft.plannedStartDate} onChange={(event) => setDraft(updatePlannedDate(draft, "start", event.target.value))} /></Field>
              <Field label="计划结束日期" id="task-edit-end"><input id="task-edit-end" type="date" value={draft.plannedEndDate} onChange={(event) => setDraft(updatePlannedDate(draft, "end", event.target.value))} /></Field>
              <Field label="工期（工作日）" id="task-edit-duration"><input id="task-edit-duration" type="number" min="1" step="1" value={draft.durationDays} onChange={(event) => setDraft(updateDuration(draft, event.target.value))} /></Field>
              <Field label="负责人" id="task-edit-assignee"><select id="task-edit-assignee" value={draft.assigneeUserId} onChange={(event) => setDraft({ ...draft, assigneeUserId: event.target.value })}><option value="">待分配</option>{workingMembers(members).map(memberOption)}</select></Field>
              <Field label="协作人" id="task-edit-collaborators" wide>
                <div className="task-collaborator-list" role="group" aria-label="协作人">
                  {workingMembers(members).map((member) => <label className="task-collaborator-option" key={member.user_id}><input type="checkbox" checked={draft.collaboratorUserIds.includes(member.user_id)} disabled={draft.assigneeUserId === member.user_id} onChange={(event) => setDraft({ ...draft, collaboratorUserIds: event.target.checked ? [...draft.collaboratorUserIds, member.user_id] : draft.collaboratorUserIds.filter((id) => id !== member.user_id) })} />{member.display_name}</label>)}
                </div>
                <small className="field-hint">可多选项目成员；负责人不能同时作为协作人。</small>
              </Field>
              <TaskDependencyPicker currentTaskId={task.id} tasks={tasks} value={draft.dependencyIds} disabled={saving} onChange={(dependencyIds) => setDraft({ ...draft, dependencyIds })} />
            </> : null}
          </div>
          {conflicts.map(({ group, opened, latest, local }) => (
            <fieldset key={group.label}>
              <legend>{group.label}</legend>
              <dl>
                <dt>打开时</dt><dd>{groupText(opened, group)}</dd>
                <dt>最新值</dt><dd>{groupText(latest, group)}</dd>
                <dt>我的草稿</dt><dd>{groupText(local, group)}</dd>
              </dl>
              <button type="button" className="secondary-button" onClick={() => {
                setDraft((previous) => copyGroup(previous, latest, group))
                setConflicts((previous) => previous.filter((conflict) => conflict.group !== group))
              }}>使用最新值</button>
              <button type="button" className="secondary-button" onClick={() => {
                setConflicts((previous) => previous.filter((conflict) => conflict.group !== group))
              }}>保留我的草稿</button>
            </fieldset>
          ))}
          {managementLost ? <p className="form-error" role="alert">管理权限已变更，无法保存此草稿。</p> : null}
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          {notice ? <p className="notice" role="status">{notice}</p> : null}
          <div className="dialog-actions">
            {stale ? <button className="secondary-button" type="button" disabled={refreshing} onClick={() => void refreshVersion()}>{refreshing ? "刷新中…" : "刷新任务"}</button> : null}
            <button className="secondary-button" type="button" onClick={onClose}>取消</button>
            <button className="primary-button" type="submit" disabled={saving || refreshing || stale || conflicts.length > 0 || managementLost || denied}>{saving ? "保存中…" : "保存任务"}</button>
          </div>
        </form>
      </section>
    </div>
  )
}

function groupText(draft: TaskDraft, group: DraftGroup): string {
  return group.fields.map((field) => {
    const value = draft[field]
    return (Array.isArray(value) ? value.join("、") : value) || "—"
  }).join(" / ")
}

function Field({ label, id, wide = false, children }: { label: string; id: string; wide?: boolean; children: React.ReactNode }) {
  return <div className={`field${wide ? " wide-field" : ""}`}><label htmlFor={id}>{label}</label>{children}</div>
}

function taskDraft(task: ProjectTaskDto): TaskDraft {
  return {
    status: task.status,
    progress: String(task.progress),
    blockedReason: task.blocked_reason,
    plannedStartDate: task.planned_start_date,
    plannedEndDate: task.planned_end_date,
    durationDays: String(task.duration_days),
    assigneeUserId: task.assignee_user_id ?? "",
    collaboratorUserIds: task.collaborator_user_ids,
    dependencyIds: task.dependency_ids,
    description: task.description,
  }
}

function taskPath(projectId: string, taskId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}`
}

function progressConflict(status: ProjectTaskStatus, progress: number, opened: number): string {
  if (status === "not_started" && progress !== 0) return "未开始任务的进度必须是 0。"
  if (status === "in_progress" && (progress < 1 || progress > 99)) {
    return "进行中任务的进度必须在 1 到 99 之间；请改用其他状态。"
  }
  if (status === "blocked" && progress !== opened) return "阻塞状态不能同时改进度，请先解除阻塞再更新进度。"
  if (status === "completed" && progress !== 100) return "已完成任务的进度将记为 100%。"
  return ""
}

function progressForStatus(status: ProjectTaskStatus, current: string): string {
  if (status === "not_started") return "0"
  if (status === "completed") return "100"
  if (status !== "in_progress") return current
  const progress = Number(current)
  if (!Number.isFinite(progress) || progress < 1) return "1"
  if (progress > 99) return "99"
  return String(progress)
}

function updatePlannedDate(draft: TaskDraft, field: "start" | "end", value: string): TaskDraft {
  const normalized = normalizeWorkdayInput(value)
  const next = {
    ...draft,
    plannedStartDate: field === "start" ? normalized : draft.plannedStartDate,
    plannedEndDate: field === "end" ? normalized : draft.plannedEndDate,
  }
  const duration = workdayDuration(next.plannedStartDate, next.plannedEndDate)
  if (duration !== null) return { ...next, durationDays: String(duration) }
  if (field === "start") {
    const calculatedEnd = workdayEnd(normalized, Number(draft.durationDays))
    if (calculatedEnd) return { ...next, plannedEndDate: calculatedEnd }
  }
  return next
}

function updateDuration(draft: TaskDraft, value: string): TaskDraft {
  const calculatedEnd = workdayEnd(draft.plannedStartDate, Number(value))
  return {
    ...draft,
    durationDays: value,
    plannedEndDate: calculatedEnd ?? draft.plannedEndDate,
  }
}

function workdayDuration(startValue: string, endValue: string): number | null {
  const start = parseDate(startValue)
  const end = parseDate(endValue)
  if (!start || !end || end < start || !isWorkday(start) || !isWorkday(end)) return null
  let duration = 0
  for (const day = new Date(start); day <= end; day.setUTCDate(day.getUTCDate() + 1)) {
    if (isWorkday(day)) duration += 1
  }
  return duration || null
}

function workdayEnd(startValue: string, duration: number): string | null {
  const start = parseDate(startValue)
  if (!start || !Number.isInteger(duration) || duration < 1) return null
  while (!isWorkday(start)) start.setUTCDate(start.getUTCDate() + 1)
  let remaining = duration - 1
  while (remaining > 0) {
    start.setUTCDate(start.getUTCDate() + 1)
    if (isWorkday(start)) remaining -= 1
  }
  return formatDate(start)
}

function normalizeWorkdayInput(value: string): string {
  const date = parseDate(value)
  if (!date) return value
  while (!isWorkday(date)) date.setUTCDate(date.getUTCDate() + 1)
  return formatDate(date)
}

function parseDate(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return null
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])))
  return Number.isNaN(date.getTime()) ? null : date
}

function formatDate(value: Date): string {
  return value.toISOString().slice(0, 10)
}

function isWorkday(value: Date): boolean {
  const day = value.getUTCDay()
  return day !== 0 && day !== 6
}

function workingMembers(members: ProjectMemberDto[]): ProjectMemberDto[] {
  return members.filter((member) => member.role === "member")
}

function memberOption(member: ProjectMemberDto) {
  return <option key={member.user_id} value={member.user_id}>{member.display_name}</option>
}

function taskError(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (error.code === "authentication_refreshed_resubmit") return error.message
    if (error.code === "cyclic_dependency") return "依赖关系存在循环，无法保存。"
    if (error.code === "invalid_task_dependency") return "前置任务必须来自同一项目且有效。"
    if (error.code === "invalid_task_member") return "负责人和协作人必须是有效的项目成员。"
    if (error.code === "invalid_task_assignment") return "负责人不能同时作为协作人。"
    if (error.code === "invalid_task_state") return "状态与进度的组合不被接受，请按提示调整后重试。"
    if (error.code === "forbidden") return "本次修改包含你无权变更的内容，未保存。"
  }
  return "任务更新失败，请检查内容后重试。"
}
