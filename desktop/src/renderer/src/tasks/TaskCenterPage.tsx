import { useEffect, useMemo, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { aiCapabilityLabels } from "../ai/accessLabels"
import { useAuth } from "../auth/AuthProvider"
import "./task-board.css"
import { TaskEditor } from "../projects/TaskEditor"
import type { ProjectDto, ProjectTaskDto } from "../workbench/types"

interface TaskCenterItem {
  id: string
  kind: "project" | "automation"
  source: "workbench" | "desktop" | "wechat" | "system"
  title: string
  description: string
  status: string
  project_id: string | null
  project_name: string
  assignee_name: string
  schedule: { kind: string; expression: string; timezone?: string }
  next_run_at: string | null
  updated_at: string
  can_run?: boolean
  can_edit?: boolean
  version?: number
  progress?: number
  blocked_reason?: string
}

interface AutomationRun { id: string; task_id: string; status: string }
interface ApprovalItem {
  id: string
  run_id: string
  project_id: string
  project_name: string
  requested_by_name: string
  capability: string
  tool_name: string
  arguments: Record<string, unknown>
  risk_level: number
  status: string
  expires_at: string
  can_review: boolean
}

interface TaskCenterResult { items: TaskCenterItem[]; total: number; counts: { project: number; automation: number } }
interface ApprovalResult { items: ApprovalItem[]; total: number }

const sourceLabels: Record<string, string> = { workbench: "工作台", desktop: "桌面端", wechat: "微信", system: "系统" }
const statusLabels: Record<string, string> = { not_started: "未开始", in_progress: "进行中", blocked: "已阻塞", completed: "已完成", cancelled: "已取消", active: "已启用", paused: "已暂停", archived: "已归档" }
const projectStatuses = ["not_started", "in_progress", "blocked", "completed", "cancelled"]
const automationStatuses = ["active", "paused", "archived"]
const approvalToolLabels: Record<string, string> = { "project_tasks.batch_assign": "批量分配项目任务" }

export function TaskCenterPage() {
  const { apiRequest, user } = useAuth()
  const [editor, setEditor] = useState<{ project: ProjectDto; task: ProjectTaskDto } | null>(null)
  const [openingEditor, setOpeningEditor] = useState("")
  async function editTask(item: TaskCenterItem) {
    if (!item.project_id || openingEditor) return
    setOpeningEditor(item.id); setError("")
    try {
      const project = await apiRequest<ProjectDto>(`/api/v1/projects/${item.project_id}`, { method: "GET" })
      const task = project.tasks?.find(task => task.id === item.id)
      if (!task) throw new Error("任务不存在或已被更新。")
      setEditor({project, task})
    } catch (caught) { setError(caught instanceof Error ? caught.message : "无法打开任务。") }
    finally { setOpeningEditor("") }
  }
  const [data, setData] = useState<TaskCenterResult | null>(null)
  const [approvals, setApprovals] = useState<ApprovalResult>({ items: [], total: 0 })
  const [filter, setFilter] = useState<"all" | "project" | "automation">("all")
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [runningTaskId, setRunningTaskId] = useState("")
  const [reviewingApprovalId, setReviewingApprovalId] = useState("")
  const [approvalPassword, setApprovalPassword] = useState("")
  const [approvalReason, setApprovalReason] = useState("")
  const [savingKeys, setSavingKeys] = useState<string[]>([])
  const [draggingKey, setDraggingKey] = useState("")
  const [dropLane, setDropLane] = useState("")
  const [statusConfirmation, setStatusConfirmation] = useState<{ task: TaskCenterItem; status: string } | null>(null)
  const [blockedReason, setBlockedReason] = useState("")
  const savingRef = useRef(new Set<string>())
  const loadSequence = useRef(0)
  const mounted = useRef(true)
  const dialogRef = useRef<HTMLDivElement>(null)

  async function load(quiet = false): Promise<void> {
    if (savingRef.current.size) return
    const sequence = ++loadSequence.current
    if (!quiet) setError("")
    try {
      const [tasks, pendingApprovals] = await Promise.all([
        apiRequest<TaskCenterResult>("/api/v1/task-center/board", { method: "GET" }),
        apiRequest<ApprovalResult>("/api/v1/task-center/approvals", { method: "GET" }),
      ])
      if (mounted.current && sequence === loadSequence.current) {
        setData(tasks)
        setApprovals(pendingApprovals)
      }
    }
    catch (caught) { if (mounted.current && sequence === loadSequence.current) setError(caught instanceof Error ? caught.message : "任务加载失败，系统会自动重试。") }
  }

  useEffect(() => {
    mounted.current = true
    void load()
    const reload = () => { if (document.visibilityState !== "hidden") void load(true) }
    const timer = window.setInterval(reload, 30_000)
    window.addEventListener("focus", reload)
    return () => { mounted.current = false; ++loadSequence.current; window.clearInterval(timer); window.removeEventListener("focus", reload) }
  }, [])
  useEffect(() => {
    if (statusConfirmation) dialogRef.current?.querySelector<HTMLElement>("textarea, button")?.focus()
  }, [statusConfirmation])
  const items = useMemo(() => data?.items.filter((item) => filter === "all" || item.kind === filter) ?? [], [data, filter])

  async function saveStatus(task: TaskCenterItem, status: string, reason?: string): Promise<void> {
    const key = taskKey(task)
    if (!task.can_edit || !task.version || savingRef.current.has(key) || task.status === status) return
    savingRef.current.add(key)
    ++loadSequence.current // Ignore an older background read while this edit is in flight.
    setSavingKeys([...savingRef.current]); setError(""); setNotice("")
    setData((current) => current ? { ...current, items: current.items.map((item) => taskKey(item) === key ? { ...item, status } : item) } : current)
    let conflicted = false
    try {
      const updated = await apiRequest<Partial<TaskCenterItem>>(`/api/v1/task-center/board/${task.kind}/${task.id}/status`, {
        method: "PATCH", body: { status, version: task.version, ...(reason !== undefined ? { blocked_reason: reason } : {}) },
      })
      if (!mounted.current) return
      setData((current) => current ? { ...current, items: current.items.map((item) => taskKey(item) === key ? { ...item, ...updated } : item) } : current)
      setNotice(`“${task.title}”已移至${statusLabels[status]}。`)
    } catch (caught) {
      if (!mounted.current) return
      setData((current) => current ? { ...current, items: current.items.map((item) => taskKey(item) === key ? task : item) } : current)
      conflicted = caught instanceof ApiClientError && caught.code === "stale_version"
      setError(conflicted ? "任务已被其他人更新，已重新读取最新状态，请确认后再操作。" : caught instanceof Error ? caught.message : "状态保存失败，已恢复原状态。")
    } finally {
      savingRef.current.delete(key)
      if (mounted.current) {
        setSavingKeys([...savingRef.current])
        if (conflicted) void load(true)
      }
    }
  }

  function changeStatus(task: TaskCenterItem, status: string): void {
    if (!task.can_edit || savingRef.current.has(taskKey(task)) || status === task.status) return
    if (task.kind === "project" && (status === "blocked" || status === "cancelled")) {
      setStatusConfirmation({ task, status }); setBlockedReason(task.blocked_reason ?? "")
    } else void saveStatus(task, status)
  }

  function renderBoard(kind: "project" | "automation") {
    const groupItems = items.filter((item) => item.kind === kind)
    if (filter !== "all" && filter !== kind || filter === "all" && groupItems.length === 0) return null
    const statuses = kind === "project" ? projectStatuses : automationStatuses
    const title = kind === "project" ? "项目任务" : "自动与定时任务"
    const dragging = items.find((item) => taskKey(item) === draggingKey)
    return <section className="task-board-group" aria-label={`${title}看板`}>
      <div className="task-board-heading"><h2>{title}<span>{groupItems.length}</span></h2><p>{kind === "project" ? "拖动卡片调整状态，也可使用卡片中的状态选择框。" : "按调度状态管理；暂停或归档不会中止已开始的执行，也不会更改执行结果。"}</p></div>
      <div className={`task-board-lanes ${kind}`}>
        {statuses.map((status) => {
          const laneKey = `${kind}:${status}`
          const laneItems = groupItems.filter((item) => item.status === status)
          const canDrop = dragging?.kind === kind && dragging.can_edit && dragging.status !== status
          return <section key={status} role="region" aria-label={`${title}：${statusLabels[status]}`} className={`task-board-lane ${status}${dropLane === laneKey ? " drag-over" : ""}`}
            onDragOver={(event) => { if (canDrop) { event.preventDefault(); event.dataTransfer.dropEffect = "move"; setDropLane(laneKey) } }}
            onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropLane("") }}
            onDrop={(event) => { event.preventDefault(); setDropLane(""); setDraggingKey(""); if (canDrop && dragging) changeStatus(dragging, status) }}>
            <header className="task-board-lane-heading"><h3><span className={`task-board-dot ${status}`} />{statusLabels[status]}</h3><span>{laneItems.length}</span></header>
            <div className="task-board-cards">{laneItems.length === 0 ? <p className="task-board-empty">暂无任务</p> : laneItems.map((item) => {
              const key = taskKey(item)
              const saving = savingKeys.includes(key)
              const editable = !!item.can_edit && !!item.version && !saving
              return <article key={key} aria-label={item.title} aria-busy={saving} className={`task-board-card${draggingKey === key ? " dragging" : ""}${saving ? " saving" : ""}`}
                draggable={editable}
                onDragStart={(event) => { if (!editable) { event.preventDefault(); return }; event.dataTransfer.setData("application/x-fde-task", key); event.dataTransfer.effectAllowed = "move"; setDraggingKey(key) }}
                onDragEnd={() => { setDraggingKey(""); setDropLane("") }}>
                <div className="task-board-card-top"><span className={`task-source ${item.source}`}>{sourceLabels[item.source] ?? "工作台"}</span>{editable ? <span className="task-board-drag-handle" aria-hidden="true">⠿</span> : null}</div>
                <h4>{item.title}</h4>
                {item.description ? <p className="task-board-description">{item.description}</p> : null}
                <dl className="task-board-meta"><div><dt>项目</dt><dd>{item.project_name || "未关联项目"}</dd></div><div><dt>执行者</dt><dd>{item.assignee_name || "未分配"}</dd></div><div><dt>计划</dt><dd>{scheduleLabel(item)}</dd></div></dl>
                {item.next_run_at ? <p className="task-board-next-run">下次：{formatTime(item.next_run_at)}</p> : null}
                {item.kind === "project" && item.status !== "cancelled" ? <div className="task-board-progress" aria-label={`进度 ${item.progress ?? 0}%`}><span><i style={{ width: `${item.progress ?? 0}%` }} /></span><small>{item.progress ?? 0}%</small></div> : null}
                {item.status === "blocked" && item.blocked_reason ? <p className="task-board-blocked-reason">阻塞原因：{item.blocked_reason}</p> : null}
                <div className="task-board-card-actions">{item.can_edit && item.version ? <label className="task-board-status-select"><span className="task-board-sr-only">{item.title}的状态</span><select value={item.status} disabled={saving} onChange={(event) => changeStatus(item, event.target.value)}>{statuses.map((value) => <option key={value} value={value}>{statusLabels[value]}</option>)}</select></label> : <span className="task-board-readonly">{item.status === "cancelled" ? "已取消 · 不可修改" : "仅可查看"}</span>}
                  {item.kind === "project" && item.can_edit ? <button type="button" className="task-card-edit" aria-label={`编辑任务：${item.title}`} title="编辑任务" disabled={saving || !!openingEditor} onClick={() => void editTask(item)}><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m16 3 5 5-12 12-6 1 1-6Z"/><path d="m14 5 5 5"/></svg></button> : null}
                  {saving ? <span className="task-board-saving" role="status">保存中…</span> : null}
                  {item.kind === "automation" && item.can_run ? <button className="secondary-button compact-button" type="button" disabled={saving || runningTaskId === item.id} onClick={() => void runAutomation(item)}>{runningTaskId === item.id ? "启动中…" : "立即执行"}</button> : null}
                </div>
              </article>
            })}</div>
          </section>
        })}
      </div>
    </section>
  }

  async function runAutomation(task: TaskCenterItem): Promise<void> {
    setRunningTaskId(task.id); setError(""); setNotice("")
    try {
      const run = await apiRequest<AutomationRun>(`/api/v1/task-center/automations/${task.id}/runs`, { method: "POST", body: {} })
      setNotice(`任务已加入执行队列（${run.id.slice(0, 8)}）。`)
      await load()
    } catch (caught) {
      setError(caught instanceof ApiClientError || caught instanceof Error ? caught.message : "任务启动失败。")
    } finally { setRunningTaskId("") }
  }

  async function decideApproval(approval: ApprovalItem, decision: "approve" | "reject"): Promise<void> {
    setError(""); setNotice("")
    if (decision === "approve" && !approvalPassword) { setError("批准高风险操作前请输入当前密码。"); return }
    try {
      await apiRequest(`/api/v1/task-center/approvals/${approval.id}/decision`, {
        method: "POST",
        body: { decision, password: decision === "approve" ? approvalPassword : "", reason: approvalReason },
      })
      setNotice(decision === "approve" ? "操作已批准，AI Server 可以继续执行。" : "操作已拒绝。")
      setReviewingApprovalId(""); setApprovalPassword(""); setApprovalReason("")
      await load()
    } catch (caught) { setError(caught instanceof ApiClientError || caught instanceof Error ? caught.message : "审批处理失败。") }
  }

  return <section className="page task-center-page">
    <header className="page-heading"><div><p className="eyebrow">统一调度</p><h1>任务中心</h1><p>项目任务按进展归列，AI Server 与定时任务按调度状态管理。列表自动更新。</p></div></header>
    {error ? <p className="form-error banner" role="alert">{error}</p> : null}
    {notice ? <p className="notice" role="status">{notice}</p> : null}
    {approvals.total > 0 ? <section className="panel approval-panel"><div className="approval-panel-heading"><div><p className="eyebrow">需要人工确认</p><h2>待审批操作</h2></div><strong>{approvals.total}</strong></div><div className="approval-list">{approvals.items.map((approval) => <article className="approval-card" key={approval.id}><div className="approval-card-main"><div><span className="risk-badge">L{approval.risk_level}</span><strong>{approvalToolLabels[approval.tool_name] ?? "AI 操作"}</strong></div><p>{approval.project_name || "未关联项目"} · 发起人：{approval.requested_by_name || "AI Server"}</p><small>权限：{aiCapabilityLabels[approval.capability] ?? "专项操作权限"}　有效期至 {formatTime(approval.expires_at)}</small><details><summary>查看操作参数</summary><pre>{JSON.stringify(approval.arguments, null, 2)}</pre></details></div>{approval.can_review ? <div className="approval-actions">{reviewingApprovalId === approval.id ? <div className="approval-confirm"><label className="field"><span>当前密码</span><input aria-label="审批当前密码" type="password" autoComplete="current-password" value={approvalPassword} onChange={(event) => setApprovalPassword(event.target.value)} /></label><label className="field"><span>审批说明（选填）</span><input aria-label="审批说明" value={approvalReason} maxLength={500} onChange={(event) => setApprovalReason(event.target.value)} /></label><div><button className="secondary-button" type="button" onClick={() => { setReviewingApprovalId(""); setApprovalPassword("") }}>取消</button><button className="primary-button" type="button" onClick={() => void decideApproval(approval, "approve")}>确认批准</button></div></div> : <><button className="danger-button" type="button" onClick={() => void decideApproval(approval, "reject")}>拒绝</button><button className="primary-button" type="button" onClick={() => { setReviewingApprovalId(approval.id); setApprovalPassword(""); setApprovalReason("") }}>审核并批准</button></>}</div> : <span className="approval-readonly">仅可查看</span>}</article>)}</div></section> : null}
    <div className="task-center-summary">
      <button className={filter === "all" ? "active" : ""} type="button" onClick={() => setFilter("all")}><span>全部任务</span><strong>{data?.total ?? 0}</strong></button>
      <button className={filter === "project" ? "active" : ""} type="button" onClick={() => setFilter("project")}><span>项目任务</span><strong>{data?.counts.project ?? 0}</strong></button>
      <button className={filter === "automation" ? "active" : ""} type="button" onClick={() => setFilter("automation")}><span>自动与定时任务</span><strong>{data?.counts.automation ?? 0}</strong></button>
    </div>
    {!data ? <p role="status">{error ? "任务暂未加载，系统会自动重试。" : "正在加载任务…"}</p> : items.length === 0 ? <div className="panel empty-state">当前筛选下暂无任务。</div> : <>{renderBoard("project")}{renderBoard("automation")}</>}
    {editor ? <TaskEditor projectId={editor.project.id} task={editor.task} tasks={editor.project.tasks || []} members={editor.project.members || []} canManage={!!user && (user.role === "admin" || (user.role === "project_lead" && editor.project.leader_user_id === user.id))} onClose={() => setEditor(null)} onSaved={() => { setEditor(null); void load(true) }} /> : null}
    {statusConfirmation ? <div className="task-board-dialog-backdrop"><div className="task-board-dialog panel" role="dialog" aria-modal="true" aria-labelledby="task-board-dialog-title" ref={dialogRef}
      onKeyDown={(event) => {
        if (event.key === "Escape") setStatusConfirmation(null)
        if (event.key === "Tab") {
          const controls = dialogRef.current?.querySelectorAll<HTMLElement>("textarea, button:not(:disabled)")
          if (!controls?.length) return
          const first = controls[0]; const last = controls[controls.length - 1]
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
          else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
        }
      }}>
      <h2 id="task-board-dialog-title">{statusConfirmation.status === "blocked" ? "填写阻塞原因" : "确认取消任务"}</h2><p>{statusConfirmation.task.title}</p>
      {statusConfirmation.status === "blocked" ? <label className="field"><span>阻塞原因</span><textarea value={blockedReason} maxLength={2000} rows={3} onChange={(event) => setBlockedReason(event.target.value)} /></label> : <p>取消后任务将保留在看板中，但无法再次修改状态。</p>}
      <div className="task-board-dialog-actions"><button className="secondary-button" type="button" onClick={() => setStatusConfirmation(null)}>返回</button><button className={statusConfirmation.status === "cancelled" ? "danger-button" : "primary-button"} type="button" disabled={statusConfirmation.status === "blocked" && !blockedReason.trim()} onClick={() => { void saveStatus(statusConfirmation.task, statusConfirmation.status, statusConfirmation.status === "blocked" ? blockedReason.trim() : undefined); setStatusConfirmation(null) }}>确认{statusConfirmation.status === "blocked" ? "阻塞" : "取消任务"}</button></div>
    </div></div> : null}
  </section>
}

function scheduleLabel(item: TaskCenterItem): string { return item.schedule.kind === "project_dates" ? item.schedule.expression : item.schedule.expression || "—" }
function formatTime(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false }) }
function taskKey(item: TaskCenterItem): string { return `${item.kind}:${item.id}` }
