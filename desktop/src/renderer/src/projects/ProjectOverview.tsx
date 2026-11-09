import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { useDangerConfirm } from "../common/DangerConfirmProvider"
import { isProjectDto } from "../workbench/runtimeValidation"
import type { ProjectDto, ProjectStatus } from "../workbench/types"

interface ProjectOverviewProps {
  project: ProjectDto
  canManage: boolean
  onProjectChange(project: ProjectDto): void
  onRefresh(): Promise<ProjectDto | null>
  guidanceSlot: ReactNode
}

const transitions: Record<ProjectStatus, ProjectStatus[]> = {
  draft: ["active", "cancelled"],
  active: ["paused", "completed", "cancelled"],
  paused: ["active", "cancelled"],
  completed: [],
  cancelled: [],
}

interface OverviewDraft {
  name: string
  enterprise_code: string
  openfdeEngagement: string
  fdeopsWorkspace: string
  sopPhase: string
  background: string
  notes: string
  plannedStartDate: string
  plannedEndDate: string
}

export function ProjectOverview({ project, canManage, onProjectChange, onRefresh, guidanceSlot }: ProjectOverviewProps) {
  const { apiRequest } = useAuth()
  const dangerConfirm = useDangerConfirm()
  const [status, setStatus] = useState(project.status)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [stale, setStale] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<OverviewDraft>(() => overviewDraft(project))
  const [editSaving, setEditSaving] = useState(false)
  const [editError, setEditError] = useState("")
  const [editStale, setEditStale] = useState(false)
  const generationRef = useRef(0)

  useEffect(() => {
    setStatus(project.status)
    setStale(false)
    setError("")
    setEditing(false)
    setEditStale(false)
    setEditError("")
    setDraft(overviewDraft(project))
    return () => { generationRef.current += 1 }
  }, [project.id])

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (saving || status === project.status) return
    if (status === "cancelled") {
      const confirmed = await dangerConfirm({
        title: "取消项目",
        description: `确定取消项目“${project.name}”吗？取消后项目将无法再恢复为进行中状态。`,
        confirmLabel: "确认取消",
      })
      if (!confirmed) return
    }
    setSaving(true)
    setError("")
    setStale(false)
    const generation = ++generationRef.current
    try {
      const saved = await apiRequest<ProjectDto>(`/api/v1/projects/${encodeURIComponent(project.id)}`, {
        method: "PATCH",
        body: { status, version: project.version },
      })
      if (generation !== generationRef.current) return
      if (!isProjectDto(saved) || saved.id !== project.id) throw new Error("invalid project")
      onProjectChange(saved)
    } catch (caught) {
      if (generation !== generationRef.current) return
      if (caught instanceof ApiClientError && caught.code === "stale_version") {
        setStale(true)
        setError("内容已被其他人更新，请刷新后重试")
      } else setError("项目状态更新失败，请稍后重试。")
    } finally {
      if (generation === generationRef.current) setSaving(false)
    }
  }

  async function saveEdit(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (editSaving) return
    if (!draft.name.trim()) {
      setEditError("项目名称不能为空。")
      return
    }
    const changed = changedFields(project, draft)
    if (Object.keys(changed).length === 0) {
      setEditing(false)
      setEditError("")
      return
    }
    setEditError("")
    setEditStale(false)
    setEditSaving(true)
    const generation = ++generationRef.current
    try {
      const saved = await apiRequest<ProjectDto>(`/api/v1/projects/${encodeURIComponent(project.id)}`, {
        method: "PATCH",
        body: { ...changed, version: project.version },
      })
      if (generation !== generationRef.current) return
      if (!isProjectDto(saved) || saved.id !== project.id) throw new Error("invalid project")
      onProjectChange(saved)
      setEditing(false)
    } catch (caught) {
      if (generation !== generationRef.current) return
      if (caught instanceof ApiClientError && caught.code === "stale_version") {
        setEditStale(true)
        setEditError("内容已被其他人更新，请刷新后重试")
      } else setEditError("项目信息更新失败，请稍后重试。")
    } finally {
      if (generation === generationRef.current) setEditSaving(false)
    }
  }

  async function refresh(): Promise<void> {
    const selected = status
    const generation = ++generationRef.current
    const next = await onRefresh()
    if (generation === generationRef.current && next) {
      setStatus(selected)
      setStale(false)
      setError("")
      setEditing(false)
      setDraft(overviewDraft(next))
      setEditStale(false)
      setEditError("")
    }
  }

  function startEditing(): void {
    setDraft(overviewDraft(project))
    setEditError("")
    setEditStale(false)
    setEditing(true)
  }

  function cancelEditing(): void {
    setDraft(overviewDraft(project))
    setEditError("")
    setEditStale(false)
    setEditing(false)
  }

  const allowed = transitions[project.status]
  return (
    <div className="overview-stack">
    <div className="overview-three-column">
      <section className="panel progress-panel" aria-labelledby="project-progress-title">
        <div className="progress-summary">
          <h2 id="project-progress-title">整体完成度</h2>
          <strong className="project-completion">{project.completion}%</strong>
          <progress max="100" value={project.completion} aria-label={`项目完成度 ${project.completion}%`} />
          <p className="supporting-copy">{project.planned_start_date} 至 {project.planned_end_date ?? "待排期"}</p>
        </div>
        {canManage ? (
          <form onSubmit={submit} className="status-transition-form">
            <div className="field">
              <select id="project-detail-status" aria-label="项目状态" value={status} disabled={saving || allowed.length === 0} onChange={(event) => setStatus(event.target.value as ProjectStatus)}>
                <option value={project.status}>{statusLabel(project.status)}</option>
                {allowed.map((item) => <option value={item} key={item}>{statusLabel(item)}</option>)}
              </select>
            </div>
            {error ? <p className="form-error" role="alert">{error}</p> : null}
            <div className="row-actions">
              <button className="primary-button" type="submit" disabled={saving || status === project.status}>{saving ? "更新中…" : "更新项目状态"}</button>
              {stale ? <button className="secondary-button" type="button" onClick={() => void refresh()}>刷新项目</button> : null}
            </div>
          </form>
        ) : <p className="supporting-copy progress-current-status">当前状态：{statusLabel(project.status)}</p>}
      </section>
      <section className="panel enterprise-overview-panel" aria-labelledby="enterprise-details-title">
        <div className="panel-heading">
          <h2 id="enterprise-details-title">企业与项目信息</h2>
          <div className="row-actions">
            <span>{project.project_code || "未设置编号"}</span>
            {canManage && !editing ? <button className="secondary-button compact" type="button" onClick={startEditing}>编辑</button> : null}
          </div>
        </div>
        {editing ? (
          <form onSubmit={saveEdit} className="overview-edit-form" data-testid="project-overview-edit-form">
            <div className="overview-edit-grid">
              <Field label="项目名称" id="overview-edit-name">
                <input id="overview-edit-name" type="text" value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
              </Field>
              <Field label="客户代号" id="overview-edit-enterprise">
                <input id="overview-edit-enterprise" type="text" maxLength={80} placeholder="客户A·行业·城市" value={draft.enterprise_code} onChange={(event) => setDraft({ ...draft, enterprise_code: event.target.value })} />
              </Field>
              <Field label="SOP 节点" id="overview-edit-sop-phase">
                <input id="overview-edit-sop-phase" type="text" maxLength={20} placeholder="S3–S13（留空不改）" value={draft.sopPhase} onChange={(event) => setDraft({ ...draft, sopPhase: event.target.value })} />
              </Field>
              <Field label="openfde engagement" id="overview-edit-openfde">
                <input id="overview-edit-openfde" type="text" maxLength={100} value={draft.openfdeEngagement} onChange={(event) => setDraft({ ...draft, openfdeEngagement: event.target.value })} />
              </Field>
              <Field label="fdeops 工作区" id="overview-edit-fdeops">
                <input id="overview-edit-fdeops" type="text" maxLength={160} value={draft.fdeopsWorkspace} onChange={(event) => setDraft({ ...draft, fdeopsWorkspace: event.target.value })} />
              </Field>
              <Field label="计划开始日期" id="overview-edit-start">
                <input id="overview-edit-start" type="date" value={draft.plannedStartDate} onChange={(event) => setDraft({ ...draft, plannedStartDate: event.target.value })} />
              </Field>
              <Field label="计划结束日期" id="overview-edit-end">
                <input id="overview-edit-end" type="date" value={draft.plannedEndDate} onChange={(event) => setDraft({ ...draft, plannedEndDate: event.target.value })} />
                <small className="field-hint">留空表示暂未排期。</small>
              </Field>
              <Field label="项目背景" id="overview-edit-background" wide>
                <textarea id="overview-edit-background" rows={3} value={draft.background} onChange={(event) => setDraft({ ...draft, background: event.target.value })} />
              </Field>
              <Field label="备注" id="overview-edit-notes" wide>
                <textarea id="overview-edit-notes" rows={2} value={draft.notes} onChange={(event) => setDraft({ ...draft, notes: event.target.value })} />
              </Field>
            </div>
            {editError ? <p className="form-error" role="alert">{editError}</p> : null}
            <div className="row-actions">
              <button className="secondary-button" type="button" onClick={cancelEditing}>取消</button>
              <button className="primary-button" type="submit" disabled={editSaving}>{editSaving ? "保存中…" : "保存"}</button>
              {editStale ? <button className="secondary-button" type="button" onClick={() => void refresh()}>刷新项目</button> : null}
            </div>
          </form>
        ) : (
          <dl className="detail-definition-grid">
            <div><dt>客户代号</dt><dd>{project.enterprise_code || "—"}</dd></div>
            <div><dt>行业</dt><dd>{project.industry || "—"}</dd></div>
            <div><dt>SOP 节点</dt><dd>{project.sop_phase || "—"}</dd></div>
            <div><dt>openfde</dt><dd>{project.openfde_engagement || "—"}</dd></div>
            <div><dt>fdeops</dt><dd>{project.fdeops_workspace || "—"}</dd></div>
            <div><dt>负责人</dt><dd>{project.leader.display_name}</dd></div>
            <div className="wide-detail"><dt>项目背景</dt><dd>{project.background}</dd></div>
            <div className="wide-detail"><dt>备注</dt><dd>{project.notes}</dd></div>
          </dl>
        )}
      </section>
    </div>
      {guidanceSlot}
    </div>
  )
}

function Field({ label, id, wide = false, children }: { label: string; id: string; wide?: boolean; children: React.ReactNode }) {
  return <div className={`field${wide ? " wide-field" : ""}`}><label htmlFor={id}>{label}</label>{children}</div>
}

function overviewDraft(project: ProjectDto): OverviewDraft {
  return {
    name: project.name,
    enterprise_code: project.enterprise_code,
    openfdeEngagement: project.openfde_engagement ?? "",
    fdeopsWorkspace: project.fdeops_workspace ?? "",
    sopPhase: project.sop_phase ?? "",
    background: project.background,
    notes: project.notes,
    plannedStartDate: project.planned_start_date,
    plannedEndDate: project.planned_end_date ?? "",
  }
}

function changedFields(project: ProjectDto, draft: OverviewDraft): Record<string, unknown> {
  const changed: Record<string, unknown> = {}
  if (draft.name !== project.name) changed.name = draft.name
  if (draft.enterprise_code !== project.enterprise_code) changed.enterprise_code = draft.enterprise_code
  if (draft.openfdeEngagement !== (project.openfde_engagement ?? "")) changed.openfde_engagement = draft.openfdeEngagement
  if (draft.fdeopsWorkspace !== (project.fdeops_workspace ?? "")) changed.fdeops_workspace = draft.fdeopsWorkspace
  // sop_phase 留空表示不改（PATCH null 会被路由拒，空串又过不了节点键校验）
  if (draft.sopPhase.trim() && draft.sopPhase !== project.sop_phase) changed.sop_phase = draft.sopPhase.trim()
  if (draft.background !== project.background) changed.background = draft.background
  if (draft.notes !== project.notes) changed.notes = draft.notes
  if (draft.plannedStartDate !== project.planned_start_date) changed.planned_start_date = draft.plannedStartDate
  if (draft.plannedEndDate !== (project.planned_end_date ?? "")) changed.planned_end_date = draft.plannedEndDate || null
  return changed
}

function statusLabel(status: ProjectStatus): string {
  return { draft: "草稿", active: "进行中", paused: "已暂停", completed: "已完成", cancelled: "已取消" }[status]
}
