import { useEffect, useRef, useState, type FormEvent } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { useDangerConfirm } from "../common/DangerConfirmProvider"
import { fetchAllPages } from "../workbench/fetchAllPages"
import { isWorkbenchUserDto } from "../workbench/runtimeValidation"
import type {
  ProjectBatchAssignmentDto,
  ProjectDefaultAssignmentDto,
  ProjectDto,
  ProjectMemberDto,
  ProjectMemberListDto,
  ProjectMemberMutationDto,
  ProjectTaskDto,
  WorkbenchUserDto,
} from "../workbench/types"
import {
  isProjectBatchAssignmentDto,
  isProjectDefaultAssignmentDto,
  isProjectMemberListDto,
  isProjectMemberMutationDto,
  isTaskListDto,
} from "./projectRuntimeValidation"

interface ProjectMembersProps {
  project: ProjectDto
  canManage: boolean
  onProjectChange(project: ProjectDto): void
}

export function ProjectMembers({ project, canManage, onProjectChange }: ProjectMembersProps) {
  const { apiRequest, user } = useAuth()
  const dangerConfirm = useDangerConfirm()
  const [members, setMembers] = useState(project.members ?? [])
  const [projectVersion, setProjectVersion] = useState(project.version)
  const [users, setUsers] = useState<WorkbenchUserDto[]>([])
  const [userId, setUserId] = useState("")
  const [role, setRole] = useState<ProjectMemberDto["role"]>("member")
  const [loading, setLoading] = useState(true)
  const [ready, setReady] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [stale, setStale] = useState(false)
  const [batchMember, setBatchMember] = useState<ProjectMemberDto | null>(null)
  const [batchMode, setBatchMode] = useState<"assignee" | "collaborator">("assignee")
  const [selectedTaskIds, setSelectedTaskIds] = useState<string[]>([])
  const [taskSearch, setTaskSearch] = useState("")
  const generationRef = useRef(0)

  async function loadMembers(preserveDraft = false): Promise<void> {
    const generation = ++generationRef.current
    setLoading(true)
    setReady(false)
    try {
      const next = await apiRequest<ProjectMemberListDto>(memberPath(project.id), { method: "GET" })
      if (generation !== generationRef.current) return
      if (!isProjectMemberListDto(next)) throw new Error("invalid member list")
      setMembers(next.items)
      setProjectVersion(next.project_version)
      setReady(true)
      setStale(false)
      setError("")
      if (!preserveDraft) setNotice("")
      onProjectChange({ ...project, members: next.items, version: next.project_version })
    } catch (caught) {
      if (generation === generationRef.current) setError(memberError(caught))
    } finally {
      if (generation === generationRef.current) setLoading(false)
    }
  }

  useEffect(() => {
    void loadMembers()
    return () => { generationRef.current += 1 }
  }, [apiRequest, project.id, user?.id])

  useEffect(() => {
    if (!canManage || user?.role !== "admin") return
    const controller = new AbortController()
    void fetchAllPages({
      apiRequest,
      pathForPage: (page, pageSize) => `/api/v1/users?active=true&page=${page}&page_size=${pageSize}`,
      itemKey: (item: WorkbenchUserDto) => item.id,
      validateItem: isWorkbenchUserDto,
      signal: controller.signal,
      pageSize: 100,
    }).then(setUsers).catch((caught) => {
      if (!controller.signal.aborted) setError(memberError(caught))
    })
    return () => controller.abort()
  }, [apiRequest, canManage, user?.id, user?.role])

  async function addMember(event: FormEvent): Promise<void> {
    event.preventDefault()
    const targetId = userId.trim()
    if (!targetId || !ready || loading || submitting) return
    setSubmitting(true)
    clearMessages()
    const operation = ++generationRef.current
    try {
      const saved = await apiRequest<ProjectMemberMutationDto>(memberPath(project.id), {
        method: "POST",
        body: { user_id: targetId, role, version: projectVersion },
      })
      if (operation !== generationRef.current) return
      if (!isProjectMemberMutationDto(saved)) throw new Error("invalid member")
      const nextMembers = [...members, withoutProjectVersion(saved)]
      updateLocal(nextMembers, saved.project_version)
      setUserId("")
      setNotice("成员已添加。")
    } catch (caught) { if (operation === generationRef.current) handleError(caught) } finally { if (operation === generationRef.current) setSubmitting(false) }
  }

  async function updateMember(member: ProjectMemberDto, nextRole: ProjectMemberDto["role"]): Promise<void> {
    if (!ready || loading || submitting || nextRole === member.role) return
    setSubmitting(true)
    clearMessages()
    const operation = ++generationRef.current
    try {
      const saved = await apiRequest<ProjectMemberMutationDto>(`${memberPath(project.id)}/${encodeURIComponent(member.id)}`, {
        method: "PATCH",
        body: { role: nextRole, version: projectVersion },
      })
      if (operation !== generationRef.current) return
      if (!isProjectMemberMutationDto(saved)) throw new Error("invalid member")
      updateLocal(members.map((item) => item.id === saved.id ? withoutProjectVersion(saved) : item), saved.project_version)
      setNotice("成员权限已更新。")
    } catch (caught) { if (operation === generationRef.current) handleError(caught) } finally { if (operation === generationRef.current) setSubmitting(false) }
  }

  async function removeMember(member: ProjectMemberDto): Promise<void> {
    if (!ready || loading || submitting || member.user_id === project.leader_user_id) return
    const confirmed = await dangerConfirm({
      title: "移除成员",
      description: `确定移除成员“${member.display_name}”吗？该成员将失去当前项目的访问权限。`,
      confirmLabel: "移除",
    })
    if (!confirmed) return
    setSubmitting(true)
    clearMessages()
    const operation = ++generationRef.current
    try {
      await apiRequest<void>(`${memberPath(project.id)}/${encodeURIComponent(member.id)}`, {
        method: "DELETE",
        body: { version: projectVersion },
      })
      if (operation !== generationRef.current) return
      updateLocal(members.filter((item) => item.id !== member.id), projectVersion + 1)
      setNotice("成员已移除。")
    } catch (caught) { if (operation === generationRef.current) handleError(caught) } finally { if (operation === generationRef.current) setSubmitting(false) }
  }

  async function assignDefaults(): Promise<void> {
    if (!ready || loading || submitting) return
    setSubmitting(true)
    clearMessages()
    const operation = ++generationRef.current
    try {
      const assigned = await apiRequest<ProjectDefaultAssignmentDto>(`/api/v1/projects/${encodeURIComponent(project.id)}/tasks/assign-defaults`, {
        method: "POST",
        body: { version: projectVersion },
      })
      if (operation !== generationRef.current) return
      if (!isProjectDefaultAssignmentDto(assigned)) throw new Error("invalid assignments")
      setProjectVersion(assigned.project_version)
      onProjectChange({ ...project, members, version: assigned.project_version })
      const taskList = await apiRequest<{ items: ProjectTaskDto[] }>(`/api/v1/projects/${encodeURIComponent(project.id)}/tasks`, { method: "GET" })
      if (operation !== generationRef.current) return
      if (!isTaskListDto(taskList)) throw new Error("invalid task list")
      onProjectChange({ ...project, members, tasks: taskList.items, version: assigned.project_version })
      setNotice(`已分派 ${assigned.assigned_count} 项任务。`)
    } catch (caught) { if (operation === generationRef.current) handleError(caught) } finally { if (operation === generationRef.current) setSubmitting(false) }
  }

  function openBatchAssignment(member: ProjectMemberDto): void {
    setBatchMember(member)
    setBatchMode("assignee")
    setSelectedTaskIds([])
    setTaskSearch("")
    clearMessages()
  }

  function closeBatchAssignment(): void {
    if (submitting) return
    setBatchMember(null)
    setSelectedTaskIds([])
  }

  async function saveBatchAssignment(): Promise<void> {
    if (!batchMember || selectedTaskIds.length === 0 || submitting) return
    const selectedTasks = (project.tasks ?? []).filter((task) => selectedTaskIds.includes(task.id))
    if (selectedTasks.length !== selectedTaskIds.length) {
      setError("部分任务已发生变化，请关闭窗口后重试。")
      return
    }
    setSubmitting(true)
    clearMessages()
    try {
      const result = await apiRequest<ProjectBatchAssignmentDto>(`/api/v1/projects/${encodeURIComponent(project.id)}/tasks/batch-assignments`, {
        method: "POST",
        body: {
          member_user_id: batchMember.user_id,
          mode: batchMode,
          tasks: selectedTasks.map((task) => ({ task_id: task.id, version: task.version })),
        },
      })
      if (!isProjectBatchAssignmentDto(result)) throw new Error("invalid batch assignments")
      const updates = new Map(result.tasks.map((task) => [task.id, task]))
      onProjectChange({
        ...project,
        members,
        tasks: (project.tasks ?? []).map((task) => updates.get(task.id) ?? task),
      })
      setBatchMember(null)
      setSelectedTaskIds([])
      setNotice(batchMode === "assignee" ? `已将 ${result.updated_count} 项任务分配给 ${batchMember.display_name}。` : `已将 ${batchMember.display_name} 添加到 ${result.updated_count} 项任务。`)
    } catch (caught) {
      handleError(caught)
    } finally {
      setSubmitting(false)
    }
  }

  function updateLocal(nextMembers: ProjectMemberDto[], version: number): void {
    setMembers(nextMembers)
    setProjectVersion(version)
    onProjectChange({ ...project, members: nextMembers, version })
  }

  function clearMessages(): void { setError(""); setNotice(""); setStale(false) }
  function handleError(caught: unknown): void {
    if (caught instanceof ApiClientError && caught.code === "stale_version") {
      setStale(true)
      setError("内容已被其他人更新，请刷新后重试")
    } else setError(memberError(caught))
  }

  return (
    <section className="panel table-panel" aria-labelledby="project-members-title">
      <div className="panel-heading"><h2 id="project-members-title">项目成员</h2><span>{members.length} 人</span></div>
      {canManage ? <>
        <form className="member-add-form" onSubmit={addMember}>
          <div className="field">
            <label htmlFor="project-member-user">{user?.role === "admin" ? "用户" : "用户 ID"}</label>
            {user?.role === "admin" ? <select id="project-member-user" value={userId} onChange={(event) => setUserId(event.target.value)}><option value="">请选择活跃用户</option>{users.filter((item) => !members.some((member) => member.user_id === item.id)).map((item) => <option value={item.id} key={item.id}>{item.display_name} ({item.username})</option>)}</select> : <input id="project-member-user" value={userId} onChange={(event) => setUserId(event.target.value)} placeholder="输入已建立的活跃用户 ID" />}
          </div>
          <div className="field"><label htmlFor="project-member-role">项目访问权限</label><select id="project-member-role" value={role} onChange={(event) => setRole(event.target.value as ProjectMemberDto["role"])}><option value="member">工作成员</option><option value="viewer">只读成员</option></select></div>
          <button className="primary-button" type="submit" disabled={!ready || loading || submitting || !userId.trim()}>添加成员</button>
          <button className="secondary-button" type="button" disabled={!ready || loading || submitting} onClick={() => void assignDefaults()}>按默认角色分派待分配任务</button>
        </form>
        {user?.role !== "admin" ? <p className="field-hint">项目负责人无权读取全公司用户目录；请输入明确用户 ID。</p> : null}
      </> : null}
      {error ? <p className="form-error banner" role="alert">{error}</p> : null}
      {notice ? <p className="notice" role="status">{notice}</p> : null}
      {stale ? <button className="secondary-button" type="button" disabled={loading || submitting} onClick={() => void loadMembers(true)}>刷新成员</button> : null}
      {loading ? <p role="status">正在加载成员…</p> : members.length === 0 ? <p className="empty-state">暂无项目成员。</p> : <div className="table-scroll"><table aria-label="项目成员"><thead><tr><th>成员</th><th>系统角色</th><th>项目权限</th><th>操作</th></tr></thead><tbody>{members.map((member) => <tr key={member.id}>
        <td>{member.display_name}{member.user_id === project.leader_user_id ? <span className="badge success member-owner-badge">当前负责人</span> : null}</td><td>{systemRoleLabel(member.system_role)}</td>
        <td>{canManage ? <select className="table-select" aria-label={`更新${member.display_name}的项目权限`} value={member.role} disabled={!ready || loading || submitting || member.user_id === project.leader_user_id} onChange={(event) => void updateMember(member, event.target.value as ProjectMemberDto["role"])}><option value="member">工作成员</option><option value="viewer">只读成员</option></select> : member.role === "member" ? "工作成员" : "只读成员"}</td>
        <td>{canManage ? <div className="row-actions member-row-actions">
          {member.role === "member" ? <button className="secondary-button compact-button" type="button" disabled={!ready || loading || submitting} onClick={() => openBatchAssignment(member)} aria-label={`批量分配任务给：${member.display_name}`}>批量分配</button> : null}
          {member.user_id !== project.leader_user_id ? <button className="danger-button compact" type="button" disabled={!ready || loading || submitting} onClick={() => void removeMember(member)} aria-label={`移除成员：${member.display_name}`}>移除</button> : null}
        </div> : null}</td>
      </tr>)}</tbody></table></div>}
      {batchMember ? <BatchAssignmentDialog
        member={batchMember}
        mode={batchMode}
        tasks={project.tasks ?? []}
        modules={project.modules ?? []}
        selectedTaskIds={selectedTaskIds}
        search={taskSearch}
        submitting={submitting}
        error={error}
        onModeChange={(nextMode) => { setBatchMode(nextMode); setSelectedTaskIds([]) }}
        onSearchChange={setTaskSearch}
        onSelectedTaskIdsChange={setSelectedTaskIds}
        onClose={closeBatchAssignment}
        onSubmit={() => void saveBatchAssignment()}
      /> : null}
    </section>
  )
}

function BatchAssignmentDialog({
  member,
  mode,
  tasks,
  modules,
  selectedTaskIds,
  search,
  submitting,
  error,
  onModeChange,
  onSearchChange,
  onSelectedTaskIdsChange,
  onClose,
  onSubmit,
}: {
  member: ProjectMemberDto
  mode: "assignee" | "collaborator"
  tasks: ProjectTaskDto[]
  modules: ProjectDto["modules"]
  selectedTaskIds: string[]
  search: string
  submitting: boolean
  error: string
  onModeChange(mode: "assignee" | "collaborator"): void
  onSearchChange(value: string): void
  onSelectedTaskIdsChange(ids: string[]): void
  onClose(): void
  onSubmit(): void
}) {
  const normalizedSearch = search.trim().toLocaleLowerCase()
  const moduleNames = new Map(modules.map((module) => [module.module_key, module.name]))
  const visibleTasks = tasks.filter((task) => task.status !== "cancelled" && (
    !normalizedSearch
    || task.name.toLocaleLowerCase().includes(normalizedSearch)
    || (moduleNames.get(task.module_key) ?? task.module_key).toLocaleLowerCase().includes(normalizedSearch)
  ))
  const selectableTasks = visibleTasks.filter((task) => !assignmentState(task, member.user_id, mode).disabled)
  const selected = new Set(selectedTaskIds)
  const allSelected = selectableTasks.length > 0 && selectableTasks.every((task) => selected.has(task.id))

  function toggleTask(taskId: string): void {
    onSelectedTaskIdsChange(selected.has(taskId) ? selectedTaskIds.filter((id) => id !== taskId) : [...selectedTaskIds, taskId])
  }

  function toggleAll(): void {
    const visibleIds = new Set(selectableTasks.map((task) => task.id))
    onSelectedTaskIdsChange(allSelected
      ? selectedTaskIds.filter((id) => !visibleIds.has(id))
      : [...new Set([...selectedTaskIds, ...visibleIds])])
  }

  return <div className="dialog-backdrop" role="presentation">
    <section className="dialog batch-assignment-dialog" role="dialog" aria-modal="true" aria-labelledby="batch-assignment-title">
      <div className="dialog-heading">
        <div><h3 id="batch-assignment-title">批量分配任务：{member.display_name}</h3><p className="supporting-copy">选择处理方式和任务，一次完成分配。</p></div>
        <button className="secondary-button" type="button" disabled={submitting} onClick={onClose}>关闭</button>
      </div>
      <div className="batch-assignment-toolbar">
        <div className="field"><label htmlFor="batch-assignment-mode">分配方式</label><select id="batch-assignment-mode" value={mode} disabled={submitting} onChange={(event) => onModeChange(event.target.value as "assignee" | "collaborator")}><option value="assignee">设为负责人</option><option value="collaborator">添加为协作人</option></select></div>
        <div className="field"><label htmlFor="batch-assignment-search">搜索任务</label><input id="batch-assignment-search" value={search} disabled={submitting} onChange={(event) => onSearchChange(event.target.value)} placeholder="任务名称或模块" /></div>
      </div>
      {error ? <p className="form-error banner" role="alert">{error}</p> : null}
      <div className="batch-task-picker">
        <label className="batch-task-select-all"><input type="checkbox" checked={allSelected} disabled={selectableTasks.length === 0 || submitting} onChange={toggleAll} />全选当前可处理任务 <span>{selectedTaskIds.length} 项已选</span></label>
        <div className="batch-task-list" role="group" aria-label="可批量分配的任务">
          {visibleTasks.length === 0 ? <p className="empty-state">没有符合条件的任务。</p> : visibleTasks.map((task) => {
            const state = assignmentState(task, member.user_id, mode)
            return <label className={`batch-task-option${state.disabled ? " disabled" : ""}`} key={task.id}>
              <input type="checkbox" checked={selected.has(task.id)} disabled={state.disabled || submitting} onChange={() => toggleTask(task.id)} />
              <span><strong>{task.name}</strong><small>{moduleNames.get(task.module_key) ?? task.module_key} · {taskStatusLabel(task.status)}</small></span>
              {state.label ? <em>{state.label}</em> : null}
            </label>
          })}
        </div>
      </div>
      <div className="dialog-actions"><button className="secondary-button" type="button" disabled={submitting} onClick={onClose}>取消</button><button className="primary-button" type="button" disabled={submitting || selectedTaskIds.length === 0} onClick={onSubmit}>{submitting ? "正在分配…" : `确认分配（${selectedTaskIds.length}）`}</button></div>
    </section>
  </div>
}

function assignmentState(task: ProjectTaskDto, userId: string, mode: "assignee" | "collaborator"): { disabled: boolean; label: string } {
  if (mode === "assignee" && task.assignee_user_id === userId) return { disabled: true, label: "已是负责人" }
  if (mode === "collaborator" && task.assignee_user_id === userId) return { disabled: true, label: "已是负责人" }
  if (mode === "collaborator" && task.collaborator_user_ids.includes(userId)) return { disabled: true, label: "已是协作人" }
  return { disabled: false, label: "" }
}

function taskStatusLabel(status: ProjectTaskDto["status"]): string { return { not_started: "未开始", in_progress: "进行中", blocked: "阻塞", completed: "已完成", cancelled: "已取消" }[status] }

function memberPath(projectId: string): string { return `/api/v1/projects/${encodeURIComponent(projectId)}/members` }
function withoutProjectVersion(member: ProjectMemberMutationDto): ProjectMemberDto { const { project_version: _, ...result } = member; return result }
function systemRoleLabel(role: string): string { return { admin: "管理员", project_lead: "项目负责人", fde_engineer: "工程师", viewer: "查看者" }[role] ?? role }
function memberError(error: unknown): string { return error instanceof ApiClientError && error.message ? error.message : "成员操作失败，请稍后重试。" }
