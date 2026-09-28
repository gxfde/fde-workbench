import { useEffect, useMemo, useRef, useState, type FormEvent } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import type { ProjectMemberDto, ProjectModuleDto, ProjectTaskDto, ProjectTaskStatus } from "../workbench/types"
import { isProjectTaskDto, isTaskListDto } from "./projectRuntimeValidation"
import { TaskEditor } from "./TaskEditor"
import { TaskDependencyPicker } from "./TaskDependencyPicker"

interface TaskTableProps {
  projectId: string
  initialTasks: ProjectTaskDto[]
  modules: ProjectModuleDto[]
  members: ProjectMemberDto[]
  canManage: boolean
  onTasksChange(tasks: ProjectTaskDto[]): void
}

interface TaskListDto { items: ProjectTaskDto[] }

export function TaskTable({ projectId, initialTasks, modules, members, canManage, onTasksChange }: TaskTableProps) {
  const { apiRequest, user } = useAuth()
  const [tasks, setTasks] = useState(initialTasks)
  const [status, setStatus] = useState("")
  const [moduleKey, setModuleKey] = useState("")
  const [assigneeId, setAssigneeId] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [refreshWarning, setRefreshWarning] = useState("")
  const [editingId, setEditingId] = useState<string | null>(null)
  const [addingTask, setAddingTask] = useState(false)
  const sequenceRef = useRef(0)
  const allTasksRef = useRef(initialTasks)
  const path = useMemo(() => taskListPath(projectId, status, moduleKey, assigneeId), [assigneeId, moduleKey, projectId, status])

  useEffect(() => {
    let active = true
    const sequence = ++sequenceRef.current
    setLoading(true)
    setError("")
    setRefreshWarning("")
    void apiRequest<TaskListDto>(path, { method: "GET" })
      .then((next) => {
        if (!active || sequence !== sequenceRef.current) return
        if (!isTaskListDto(next)) throw new Error("invalid task list")
        setTasks(next.items)
        if (!status && !moduleKey && !assigneeId) {
          allTasksRef.current = next.items
          onTasksChange(next.items)
        }
      })
      .catch((caught) => {
        if (!active || sequence !== sequenceRef.current) return
        setError(listError(caught))
      })
      .finally(() => {
        if (active && sequence === sequenceRef.current) setLoading(false)
      })
    return () => { active = false; sequenceRef.current += 1 }
  }, [apiRequest, onTasksChange, path, user?.id])

  const editing = tasks.find((item) => item.id === editingId) ?? null
  function replaceTask(saved: ProjectTaskDto): void {
    const optimistic = replaceTaskInList(allTasksRef.current, saved)
    allTasksRef.current = optimistic
    onTasksChange(optimistic)
    setTasks(filterTasks(optimistic, status, moduleKey, assigneeId))
    setRefreshWarning("")
    setEditingId(null)
    void refreshAfterMutation()
  }

  function addTask(saved: ProjectTaskDto): void {
    replaceTask(saved)
    setAddingTask(false)
  }

  async function refreshAfterMutation(): Promise<void> {
    const sequence = ++sequenceRef.current
    setLoading(true)
    setError("")
    setRefreshWarning("")
    try {
      const unfilteredPath = taskListPath(projectId, "", "", "")
      const refreshPath = canManage ? unfilteredPath : path
      const next = await apiRequest<TaskListDto>(refreshPath, { method: "GET" })
      if (sequence !== sequenceRef.current) return
      if (!isTaskListDto(next)) throw new Error("invalid task list")
      if (canManage) {
        allTasksRef.current = next.items
        onTasksChange(next.items)
        setTasks(filterTasks(next.items, status, moduleKey, assigneeId))
      } else {
        setTasks(next.items)
        if (refreshPath === unfilteredPath) {
          allTasksRef.current = next.items
          onTasksChange(next.items)
        }
      }
    } catch {
      if (sequence === sequenceRef.current) setRefreshWarning("任务已保存，列表刷新失败")
    } finally {
      if (sequence === sequenceRef.current) setLoading(false)
    }
  }

  return (
    <section className="panel table-panel" aria-labelledby="project-task-list-title">
      <div className="panel-heading"><h2 id="project-task-list-title">项目任务</h2><span className="list-heading-actions" style={{ gap: 12 }}>{canManage ? <button className="secondary-button compact" type="button" onClick={() => setAddingTask(true)}>新增任务</button> : null}<span>{tasks.length} 项</span></span></div>
      <div className="task-filter-grid">
        <div className="field"><label htmlFor="task-filter-status">按状态筛选</label><select id="task-filter-status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部状态</option>{taskStatuses.map((item) => <option key={item} value={item}>{taskStatusLabel(item)}</option>)}</select></div>
        <div className="field"><label htmlFor="task-filter-module">按模块筛选</label><select id="task-filter-module" value={moduleKey} onChange={(event) => setModuleKey(event.target.value)}><option value="">全部模块</option>{modules.map((module) => <option value={module.module_key} key={module.id}>{module.name}</option>)}</select></div>
        <div className="field"><label htmlFor="task-filter-assignee">按负责人筛选</label><select id="task-filter-assignee" value={assigneeId} onChange={(event) => setAssigneeId(event.target.value)}><option value="">全部负责人</option>{members.map((member) => <option value={member.user_id} key={member.id}>{member.display_name}</option>)}</select></div>
      </div>
      {refreshWarning ? <p className="form-error" role="alert">{refreshWarning}</p> : null}
      {loading ? <p role="status">正在加载任务…</p> : error ? <p className="form-error" role="alert">{error}</p> : tasks.length === 0 ? <p className="empty-state">暂无符合条件的任务。</p> : (
        <div className="task-card-grid" role="list" aria-label="项目任务">
          {tasks.map((task) => {
            const member = members.find((item) => item.user_id === task.assignee_user_id)
            const hasWorkingMembership = Boolean(user && members.some((item) => item.user_id === user.id && item.role === "member"))
            const editable = canManage || Boolean(user && roleAtLeastEngineer(user.role) && hasWorkingMembership && (task.assignee_user_id === user.id || task.collaborator_user_ids.includes(user.id)))
            const moduleName = modules.find((item) => item.module_key === task.module_key)?.name ?? task.module_key
            const dependencies = dependencyNames(task, allTasksRef.current)
            return <article className="task-summary-card" role="listitem" key={task.id} aria-labelledby={`task-card-${task.id}`}>
              <header className="task-card-heading">
                <div className="task-card-title-row">
                  <h3 id={`task-card-${task.id}`}>{task.name}</h3>
                  <div className="task-card-badges">
                    <span className="badge muted">{moduleName}</span>
                    <span className={`badge ${taskStatusClass(task.status)}`}>{taskStatusLabel(task.status)}</span>
                    {editable && task.status !== "cancelled" ? <button className="secondary-button compact task-card-update-button" type="button" aria-label={`更新任务：${task.name}`} onClick={() => setEditingId(task.id)}>更新</button> : null}
                  </div>
                </div>
                <p className="task-card-description">{task.description || task.task_key}</p>
              </header>
              {task.status === "blocked" && task.blocked_reason ? <p className="task-blocked-reason">阻塞原因：{task.blocked_reason}</p> : null}
              <div className="task-card-progress" aria-label={`任务进度 ${task.progress}%`}>
                <span>进度</span><progress value={task.progress} max="100" /><strong>{task.progress}%</strong>
              </div>
              <dl className="task-card-meta">
                <div><dt>负责人</dt><dd>{task.pending_assignment ? <span className="badge warning">待分配</span> : member?.display_name ?? task.assignee_user_id}</dd></div>
                <div><dt>计划</dt><dd>{task.planned_start_date} 至 {task.planned_end_date}</dd></div>
                {dependencies || task.dependency_risk ? <div className="task-card-dependency"><dt>前置任务</dt><dd>{task.dependency_risk ? <span className="badge warning">依赖风险</span> : null}<span>{dependencies}</span></dd></div> : null}
              </dl>
            </article>
          })}
        </div>
      )}
      {editing ? <TaskEditor projectId={projectId} task={editing} tasks={allTasksRef.current} members={members} canManage={canManage} onSaved={replaceTask} onClose={() => setEditingId(null)} /> : null}
      {addingTask && canManage ? <NewTaskDialog projectId={projectId} modules={modules} tasks={allTasksRef.current} members={members} onSaved={addTask} onClose={() => setAddingTask(false)} /> : null}
    </section>
  )
}

const taskStatuses: ProjectTaskStatus[] = ["not_started", "in_progress", "blocked", "completed", "cancelled"]

function taskListPath(projectId: string, status: string, moduleKey: string, assigneeId: string): string {
  const params = new URLSearchParams()
  if (status) params.set("status", status)
  if (moduleKey) params.set("module_key", moduleKey)
  if (assigneeId) params.set("assignee_user_id", assigneeId)
  const query = params.toString()
  return `/api/v1/projects/${encodeURIComponent(projectId)}/tasks${query ? `?${query}` : ""}`
}

function taskStatusLabel(status: ProjectTaskStatus): string {
  return { not_started: "未开始", in_progress: "进行中", blocked: "阻塞", completed: "已完成", cancelled: "已取消" }[status]
}

function taskStatusClass(status: ProjectTaskStatus): string {
  if (status === "completed") return "success"
  if (status === "blocked") return "warning"
  return "muted"
}

function replaceTaskInList(tasks: ProjectTaskDto[], saved: ProjectTaskDto): ProjectTaskDto[] {
  return tasks.some((task) => task.id === saved.id)
    ? tasks.map((task) => task.id === saved.id ? saved : task)
    : [...tasks, saved]
}

function filterTasks(tasks: ProjectTaskDto[], status: string, moduleKey: string, assigneeId: string): ProjectTaskDto[] {
  return tasks.filter((task) => (!status || task.status === status)
    && (!moduleKey || task.module_key === moduleKey)
    && (!assigneeId || task.assignee_user_id === assigneeId))
}

function listError(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "stale_session_response") return "登录会话已更改，请重新加载任务。"
  return "任务加载失败，请稍后重试。"
}

function roleAtLeastEngineer(role: string): boolean {
  return role === "fde_engineer" || role === "project_lead" || role === "admin"
}

interface NewTaskDialogProps {
  projectId: string
  modules: ProjectModuleDto[]
  tasks: ProjectTaskDto[]
  members: ProjectMemberDto[]
  onSaved(task: ProjectTaskDto): void
  onClose(): void
}

function NewTaskDialog({ projectId, modules, tasks, members, onSaved, onClose }: NewTaskDialogProps) {
  const { apiRequest } = useAuth()
  const [moduleKey, setModuleKey] = useState(modules[0]?.module_key ?? "")
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [durationDays, setDurationDays] = useState("1")
  const [assigneeUserId, setAssigneeUserId] = useState("")
  const [collaboratorUserIds, setCollaboratorUserIds] = useState<string[]>([])
  const [dependencyIds, setDependencyIds] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (busy) return
    if (!name.trim()) { setError("请填写任务名称。"); return }
    const duration = Number(durationDays)
    if (!Number.isInteger(duration) || duration < 1) { setError("工期必须是大于 0 的整数。"); return }
    if (!moduleKey) { setError("请选择所属模块。"); return }
    setBusy(true)
    setError("")
    try {
      const saved = await apiRequest<unknown>(taskCreatePath(projectId, moduleKey), {
        method: "POST",
        body: {
          name: name.trim(),
          description: description.trim(),
          duration_days: duration,
          assignee_user_id: assigneeUserId || null,
          collaborator_user_ids: collaboratorUserIds,
          dependency_ids: dependencyIds,
        },
      })
      if (!isProjectTaskDto(saved)) throw new Error("invalid task")
      onSaved(saved)
    } catch (caught) {
      setError(newTaskError(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dialog-backdrop">
      <section className="dialog task-dialog" role="dialog" aria-modal="true" aria-labelledby="new-task-title">
        <div className="panel-heading"><h2 id="new-task-title">新增任务</h2></div>
        <form onSubmit={(event) => void submit(event)}>
          <div className="task-dialog-grid">
            <Field label="所属模块" id="new-task-module">
              <select id="new-task-module" value={moduleKey} onChange={(event) => setModuleKey(event.target.value)} disabled={busy}>
                {modules.map((module) => <option value={module.module_key} key={module.id}>{module.name}</option>)}
              </select>
            </Field>
            <Field label="任务名称" id="new-task-name"><input id="new-task-name" value={name} onChange={(event) => setName(event.target.value)} disabled={busy} /></Field>
            <Field label="任务说明" id="new-task-description" wide><textarea id="new-task-description" rows={2} value={description} onChange={(event) => setDescription(event.target.value)} disabled={busy} /></Field>
            <Field label="工期（工作日）" id="new-task-duration"><input id="new-task-duration" type="number" min="1" step="1" value={durationDays} onChange={(event) => setDurationDays(event.target.value)} disabled={busy} /></Field>
            <Field label="负责人" id="new-task-assignee"><select id="new-task-assignee" value={assigneeUserId} onChange={(event) => setAssigneeUserId(event.target.value)} disabled={busy}><option value="">待分配</option>{workingMembers(members).map(memberOption)}</select></Field>
            <Field label="协作人" id="new-task-collaborators" wide>
              <div className="task-collaborator-list" role="group" aria-label="协作人">
                {workingMembers(members).map((member) => <label className="task-collaborator-option" key={member.user_id}><input type="checkbox" checked={collaboratorUserIds.includes(member.user_id)} disabled={busy || assigneeUserId === member.user_id} onChange={(event) => setCollaboratorUserIds(event.target.checked ? [...collaboratorUserIds, member.user_id] : collaboratorUserIds.filter((id) => id !== member.user_id))} />{member.display_name}</label>)}
              </div>
            </Field>
            <TaskDependencyPicker currentTaskId={null} tasks={tasks} value={dependencyIds} disabled={busy} onChange={setDependencyIds} />
          </div>
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <div className="dialog-actions">
            <button className="secondary-button" type="button" disabled={busy} onClick={onClose}>取消</button>
            <button className="primary-button" type="submit" disabled={busy}>{busy ? "正在创建" : "创建任务"}</button>
          </div>
        </form>
      </section>
    </div>
  )
}

function Field({ label, id, wide = false, children }: { label: string; id: string; wide?: boolean; children: React.ReactNode }) {
  return <div className={`field${wide ? " wide-field" : ""}`}><label htmlFor={id}>{label}</label>{children}</div>
}

function taskCreatePath(projectId: string, moduleKey: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/modules/${encodeURIComponent(moduleKey)}/tasks`
}

function workingMembers(members: ProjectMemberDto[]): ProjectMemberDto[] {
  return members.filter((member) => member.role === "member")
}

function memberOption(member: ProjectMemberDto) {
  return <option key={member.user_id} value={member.user_id}>{member.display_name}</option>
}

function dependencyNames(task: ProjectTaskDto, tasks: ProjectTaskDto[]): string {
  return task.dependency_ids
    .map((id) => tasks.find((candidate) => candidate.id === id)?.name)
    .filter((name): name is string => Boolean(name))
    .join("、")
}

function newTaskError(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (error.code === "invalid_task_member") return "负责人和协作人必须是有效的项目成员。"
    if (error.code === "invalid_task_assignment") return "负责人不能同时作为协作人。"
    if (error.code === "cyclic_dependency") return "依赖关系存在循环，无法保存。"
    if (error.code === "invalid_request") return "任务内容不合法，请检查名称、工期与负责人。"
    if (error.code === "forbidden") return "你没有权限在该项目中新建任务。"
  }
  return "任务创建失败，请检查内容后重试。"
}
