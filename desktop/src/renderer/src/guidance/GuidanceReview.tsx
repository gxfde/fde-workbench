import { useEffect, useMemo, useRef, useState } from "react"
import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import type { GuidanceAnalysisDto, GuidanceItemDto } from "./types"
import { isGuidanceAnalysis } from "./runtimeValidation"

const sections: Array<[keyof GuidanceAnalysisDto, string]> = [
  ["key_business_problems", "关键业务问题"], ["priority_departments", "优先部门"], ["priority_roles", "优先岗位"],
  ["priority_processes", "优先流程"], ["success_criteria", "成功标准"], ["out_of_scope", "本阶段不包含"],
  ["data_security_redlines", "数据与安全红线"], ["systems_and_deployment_constraints", "系统与部署约束"],
  ["assumptions", "假设"], ["open_questions", "待确认问题"], ["next_actions", "下一步行动"],
]

export function GuidanceReview({ projectId, initial, canManage, initialEditing = false, onClose, onSaved }: { projectId: string; initial: GuidanceAnalysisDto; canManage: boolean; initialEditing?: boolean; onClose(): void; onSaved(value: GuidanceAnalysisDto): void }) {
  const { apiRequest } = useAuth()
  const [draft, setDraft] = useState(initial)
  const [baseline, setBaseline] = useState(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const published = useRef<GuidanceAnalysisDto | null>(null)
  const [editing, setEditing] = useState(initialEditing && initial.status === "draft" && initial.analysis_state === "ready")
  useEffect(() => {
    // A locally published revision is echoed back by the parent. Do not turn
    // off editing immediately after the user explicitly requested that revision.
    if (initial === published.current) return
    setDraft(initial); setBaseline(initial); setEditing(initialEditing && initial.status === "draft" && initial.analysis_state === "ready")
  }, [initial, initialEditing])
  const canEdit = canManage && draft.analysis_state === "ready"
  const payload = useMemo(() => Object.fromEntries(sections.map(([key]) => [key, draft[key]])), [draft])
  async function save(confirm = false) {
    setSaving(true); setError("")
    try {
      let next = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/guidance-analyses/${encodeURIComponent(draft.id)}`, { method: "PATCH", body: { version: draft.version, customer_vision: draft.customer_vision, current_phase_objective: draft.current_phase_objective, executive_summary: draft.executive_summary, ...payload } })
      if (!isGuidanceAnalysis(next)) throw new Error("invalid guidance")
      if (confirm) {
        next = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/guidance-analyses/${encodeURIComponent(next.id)}/confirm`, { method: "POST", body: { version: next.version } })
        if (!isGuidanceAnalysis(next)) throw new Error("invalid guidance")
      }
      setDraft(next); setBaseline(next); published.current = next; onSaved(next)
      if (confirm) onClose()
      else setEditing(false)
    } catch (caught) {
      setError(caught instanceof ApiClientError ? caught.message : "项目指引保存失败，请稍后重试。")
    } finally { setSaving(false) }
  }
  async function beginEditing() {
    if (draft.status === "draft") { setEditing(true); return }
    setSaving(true); setError("")
    try {
      const next = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/guidance-analyses/${encodeURIComponent(draft.id)}/revisions`, { method: "POST", body: { version: draft.version } })
      if (!isGuidanceAnalysis(next)) throw new Error("invalid guidance")
      setDraft(next); setBaseline(next); published.current = next; onSaved(next); setEditing(true)
    } catch (caught) {
      setError(caught instanceof ApiClientError ? caught.message : "项目指引修订版创建失败，请稍后重试。")
    } finally { setSaving(false) }
  }
  function changeItems(key: keyof GuidanceAnalysisDto, text: string) {
    const previous = draft[key] as GuidanceItemDto[]
    const next = text.split("\n").map((value) => value.trim()).filter(Boolean).map((value, index) => ({ text: value, classification: previous[index]?.classification ?? "human_added" as const, source_refs: previous[index]?.source_refs ?? [], confirmed: previous[index]?.confirmed ?? true }))
    setDraft({ ...draft, [key]: next })
  }
  function cancelEditing() { setDraft(baseline); setError(""); setEditing(false) }
  return <div className="dialog-backdrop"><section className="dialog guidance-review-dialog" role="dialog" aria-modal="true" aria-label="审核客户目标与项目指引">
    <div className="dialog-heading"><div><h3>客户目标与项目指引 · v{draft.version_number}</h3><p className="field-hint">来源：{draft.source_filename}</p></div><div className="row-actions">{canEdit ? <button className="secondary-button compact" type="button" disabled={saving} onClick={() => editing ? cancelEditing() : void beginEditing()}>{saving && !editing ? "创建修订中…" : editing ? "取消编辑" : "编辑"}</button> : null}<button className="secondary-button compact" type="button" onClick={onClose}>关闭</button></div></div>
    <div className="guidance-review-body">
      {draft.analysis_state !== "ready" ? draft.analysis_state === "failed" ? <p className="form-error" role="alert">{draft.failure_message}</p> : <div className="guidance-analysis-progress" role="status"><strong>预调研分析正在后台继续</strong><p>可以先关闭本页处理其他工作；进入分析时会显示 AI 执行中心，完成后这里会自动更新为审核内容。</p></div> : editing ? <div className="guidance-form">
        <label className="field"><span>客户长期愿景</span><textarea rows={3} value={draft.customer_vision} onChange={(event) => setDraft({ ...draft, customer_vision: event.target.value })} /></label>
        <label className="field"><span>当前阶段目标</span><textarea rows={3} value={draft.current_phase_objective} onChange={(event) => setDraft({ ...draft, current_phase_objective: event.target.value })} /></label>
        {sections.map(([key, label]) => <label className="field" key={key}><span>{label}</span><textarea rows={4} value={(draft[key] as GuidanceItemDto[]).map((item) => item.text).join("\n")} onChange={(event) => changeItems(key, event.target.value)} /></label>)}
        <label className="field"><span>执行摘要</span><textarea rows={4} value={draft.executive_summary} onChange={(event) => setDraft({ ...draft, executive_summary: event.target.value })} /></label>
      </div> : <div className="guidance-detail-grid">
        <GuidanceText title="客户长期愿景" text={draft.customer_vision} wide />
        <GuidanceText title="当前阶段目标" text={draft.current_phase_objective} wide />
        {sections.map(([key, label]) => <GuidanceItems key={key} title={label} items={draft[key] as GuidanceItemDto[]} />)}
        <GuidanceText title="执行摘要" text={draft.executive_summary} wide />
      </div>}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {editing && canEdit ? <div className="row-actions guidance-review-actions"><button className="secondary-button" type="button" disabled={saving} onClick={cancelEditing}>取消</button><button className="secondary-button" disabled={saving} onClick={() => void save(false)}>{saving ? "保存中…" : "保存修改"}</button><button className="primary-button" disabled={saving} onClick={() => void save(true)}>确认并用于项目指引</button></div> : null}
    </div>
  </section></div>
}

function GuidanceText({ title, text, wide = false }: { title: string; text: string; wide?: boolean }) {
  return <article className={`guidance-detail-section${wide ? " wide" : ""}`}><h4>{title}</h4><p>{text}</p></article>
}

function GuidanceItems({ title, items }: { title: string; items: GuidanceItemDto[] }) {
  return <article className="guidance-detail-section"><h4>{title}</h4>{items.length ? <ul>{items.map((item, index) => <li key={index}>{item.text}</li>)}</ul> : <p className="guidance-empty-copy">暂无内容</p>}</article>
}
