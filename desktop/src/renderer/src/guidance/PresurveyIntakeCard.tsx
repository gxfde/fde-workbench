import { useEffect, useState } from "react"
import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { INTERVIEW_MODES, INTERVIEW_MODE_LABELS, emptyIntake, isPresurveyIntake } from "./types"
import type { InterviewMode, PresurveyIntakeDto } from "./types"
import { Loading } from "../components/ui"

const TEXT_LIMITS: Record<"industry" | "scale" | "region", number> = { industry: 80, scale: 80, region: 80 }
const PARAGRAPH_LIMITS = { customer_vision: 2000, phase_objective: 2000, notes: 2000 }
const ROLES_LIMIT = { count: 20, length: 80 }

// goal-d2：售前轻量录入卡的桌面入口（d1 已交付 GET/PUT API，台账登记的 UI 缺口）。
// S1–S2 阶段即可填写（PRD D16：无敏感字段、无门禁要求），供方案骨架的行业匹配
// 与会议准备使用。
export function PresurveyIntakeCard({ projectId, onClose }: { projectId: string; onClose(): void }) {
  const { apiRequest } = useAuth()
  const [intake, setIntake] = useState<PresurveyIntakeDto>(() => emptyIntake(projectId))
  const [rolesText, setRolesText] = useState("")
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  useEffect(() => {
    let active = true
    void apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/presurvey-intake`, { method: "GET" })
      .then((value) => {
        if (!active) return
        if (!isPresurveyIntake(value)) throw new Error("invalid intake")
        setIntake(value)
        setRolesText(value.interviewee_roles.join("\n"))
        setError("")
      })
      .catch((caught) => {
        if (active) setError(caught instanceof ApiClientError || caught instanceof Error ? caught.message : "录入卡读取失败，请稍后重试。")
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [apiRequest, projectId])
  function update<K extends keyof PresurveyIntakeDto>(key: K, value: PresurveyIntakeDto[K]) {
    setIntake((previous) => ({ ...previous, [key]: value }))
  }
  async function save() {
    setSaving(true); setError(""); setNotice("")
    try {
      const roles = rolesText.split("\n").map((role) => role.trim()).filter(Boolean)
      if (roles.length > ROLES_LIMIT.count) throw new Error(`访谈对象最多 ${ROLES_LIMIT.count} 个。`)
      if (roles.some((role) => role.length > ROLES_LIMIT.length)) throw new Error(`单个访谈对象不超过 ${ROLES_LIMIT.length} 字。`)
      const saved = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/presurvey-intake`, {
        method: "PUT",
        body: {
          industry: intake.industry, scale: intake.scale, region: intake.region,
          interview_mode: intake.interview_mode, interviewee_roles: roles,
          customer_vision: intake.customer_vision, phase_objective: intake.phase_objective, notes: intake.notes,
        },
      })
      if (!isPresurveyIntake(saved)) throw new Error("invalid intake")
      setIntake(saved); setRolesText(saved.interviewee_roles.join("\n")); setNotice("已保存")
    } catch (caught) {
      setError(caught instanceof Error && caught.message && caught.message !== "invalid intake" ? caught.message : "录入卡保存失败，请稍后重试。")
    } finally { setSaving(false) }
  }
  return <div className="dialog-backdrop"><section className="dialog guidance-review-dialog" role="dialog" aria-modal="true" aria-label="售前录入卡">
    <div className="dialog-heading"><div><h3>售前录入卡</h3><p className="field-hint">轻量结构化信息：售前阶段即可填写，用于行业模板匹配与访谈准备。</p></div><div className="row-actions"><button className="secondary-button compact" type="button" onClick={onClose}>关闭</button></div></div>
    <div className="guidance-review-body">
      {loading ? <Loading label="读取中…" /> : <div className="guidance-form">
        <label className="field"><span>行业（≤{TEXT_LIMITS.industry} 字）</span><input value={intake.industry} maxLength={TEXT_LIMITS.industry} onChange={(event) => update("industry", event.target.value)} placeholder="如：零售连锁" /></label>
        <label className="field"><span>企业规模（≤{TEXT_LIMITS.scale} 字）</span><input value={intake.scale} maxLength={TEXT_LIMITS.scale} onChange={(event) => update("scale", event.target.value)} placeholder="如：门店 150 家，总部 200 人" /></label>
        <label className="field"><span>地域（≤{TEXT_LIMITS.region} 字）</span><input value={intake.region} maxLength={TEXT_LIMITS.region} onChange={(event) => update("region", event.target.value)} placeholder="如：华东（苏州）" /></label>
        <label className="field"><span>访谈方式</span><select value={intake.interview_mode} onChange={(event) => update("interview_mode", event.target.value as InterviewMode)}>
          {INTERVIEW_MODES.map((mode) => <option key={mode} value={mode}>{INTERVIEW_MODE_LABELS[mode]}</option>)}
        </select></label>
        <label className="field"><span>访谈对象角色（每行一个，≤{ROLES_LIMIT.count} 个）</span><textarea rows={3} value={rolesText} onChange={(event) => setRolesText(event.target.value)} placeholder={"运营负责人\nIT 负责人"} /></label>
        <label className="field"><span>客户愿景（≤{PARAGRAPH_LIMITS.customer_vision} 字）</span><textarea rows={3} value={intake.customer_vision} maxLength={PARAGRAPH_LIMITS.customer_vision} onChange={(event) => update("customer_vision", event.target.value)} /></label>
        <label className="field"><span>本阶段目标（≤{PARAGRAPH_LIMITS.phase_objective} 字）</span><textarea rows={3} value={intake.phase_objective} maxLength={PARAGRAPH_LIMITS.phase_objective} onChange={(event) => update("phase_objective", event.target.value)} /></label>
        <label className="field"><span>备注（≤{PARAGRAPH_LIMITS.notes} 字）</span><textarea rows={3} value={intake.notes} maxLength={PARAGRAPH_LIMITS.notes} onChange={(event) => update("notes", event.target.value)} /></label>
      </div>}
      {notice ? <p className="field-hint" role="status">{notice}</p> : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {!loading ? <div className="row-actions guidance-review-actions"><button className="secondary-button" type="button" onClick={onClose}>关闭</button><button className="primary-button" type="button" disabled={saving} onClick={() => void save()}>{saving ? "保存中…" : "保存录入卡"}</button></div> : null}
    </div>
  </section></div>
}
