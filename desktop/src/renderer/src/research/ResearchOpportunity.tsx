import { useEffect, useRef, useState } from "react"

import { ApiClientError, type RendererApiRequestOptions } from "../api/client"
import { RESEARCH_SUBJECT_LABELS, type AIOpportunityProfileDto, type OpportunityLevel, type OpportunityStatus, type ProjectResearchFormDto, type ResearchSubjectDto } from "./types"
import { ResearchForm } from "./ResearchForm"
import { OpportunityAdjustment } from "./OpportunityAdjustment"

const STATUS_LABELS: Record<OpportunityStatus, string> = { discovered: "已发现", assessing: "评估中", ready: "可推进", converted: "已转交付", paused: "已暂停" }
const LEVEL_LABELS: Record<OpportunityLevel, string> = { high: "高", medium: "中", low: "低" }
export function createEmptyOpportunityProfile(): AIOpportunityProfileDto {
  return { target_audience: "", owner_user_id: null, owner_display_name: null, opportunity_status: "discovered", priority: null, business_value_score: null, feasibility_score: null, data_readiness_score: null, risk_level: null, next_action: "" }
}

const EMPTY_PROFILE = createEmptyOpportunityProfile()

interface OpportunityListPanelProps { opportunities: ResearchSubjectDto[]; canCreateOpportunity: boolean; onCreate(): void; onAIGenerate(): void; onView(opportunity: ResearchSubjectDto): void }

export function OpportunityListPanel({ opportunities, canCreateOpportunity, onCreate, onAIGenerate, onView }: OpportunityListPanelProps) {
  return <section className="panel research-opportunity-panel" aria-labelledby="research-opportunity-list-title">
    <div className="panel-heading"><h2 id="research-opportunity-list-title">AI 机会列表</h2><span>{opportunities.length} 个</span></div>
    {canCreateOpportunity ? <div className="research-opportunity-actions"><button type="button" className="primary-button compact ai-assist-button" onClick={onAIGenerate}>AI 辅助生成</button><button type="button" className="secondary-button compact" onClick={onCreate}>新增 AI 机会</button></div> : null}
    {opportunities.length ? <ul className="research-opportunity-list" aria-label="AI 机会列表">{opportunities.map((opportunity) => {
      const profile = opportunity.opportunity_profile ?? EMPTY_PROFILE
      return <li className="research-opportunity-row" key={opportunity.id}><div><strong>{opportunity.name}</strong>{opportunity.tracking_code ? <code>{opportunity.tracking_code}</code> : null}<div className="opportunity-list-meta"><span>{STATUS_LABELS[profile.opportunity_status]}</span>{profile.priority ? <span>优先级 {LEVEL_LABELS[profile.priority]}</span> : null}{profile.business_value_score ? <span>价值 {profile.business_value_score}</span> : null}{profile.feasibility_score ? <span>可行性 {profile.feasibility_score}</span> : null}</div></div><button type="button" className="secondary-button compact" onClick={() => onView(opportunity)}>查看</button></li>
    })}</ul> : <p className="empty-state">当前选定范围内暂无 AI 机会，可切换上级对象查看。</p>}
  </section>
}

interface OpportunityDetailProps {
  projectId: string; opportunity: ResearchSubjectDto; forms: ProjectResearchFormDto[]
  ownerOptions: Array<{ id: string; display_name: string }>; canManage: boolean; canFill: boolean; editing: boolean
  apiRequest<T>(path: string, options: RendererApiRequestOptions): Promise<T>
  onOpportunityUpdated(opportunity: ResearchSubjectDto): void; onUpdate(form: ProjectResearchFormDto): void
  onDirtyChange(formId: string, dirty: boolean): void; onEdit(): void; onDelete(): void; onBack(): void
}

export function OpportunityDetail({ projectId, opportunity, forms, ownerOptions, canManage, canFill, editing, apiRequest, onOpportunityUpdated, onUpdate, onDirtyChange, onEdit, onDelete, onBack }: OpportunityDetailProps) {
  const [profile, setProfile] = useState<AIOpportunityProfileDto>(opportunity.opportunity_profile ?? EMPTY_PROFILE)
  const [description, setDescription] = useState(opportunity.description)
  const [saving, setSaving] = useState(false)
  const [adjusting, setAdjusting] = useState(false)
  const moreActions = useRef<HTMLDetailsElement>(null)
  useEffect(() => {
    const closeOutside = (event: PointerEvent) => { if (event.target instanceof Node && !moreActions.current?.contains(event.target) && moreActions.current) moreActions.current.open = false }
    const closeEscape = (event: KeyboardEvent) => { if (event.key === "Escape" && moreActions.current?.open) { moreActions.current.open = false; moreActions.current.querySelector("summary")?.focus() } }
    document.addEventListener("pointerdown", closeOutside)
    document.addEventListener("keydown", closeEscape)
    return () => { document.removeEventListener("pointerdown", closeOutside); document.removeEventListener("keydown", closeEscape) }
  }, [])
  const [notice, setNotice] = useState("")
  const [error, setError] = useState("")
  const dirtyChange = useRef(onDirtyChange)
  dirtyChange.current = onDirtyChange
  const profileKey = `opportunity-profile:${opportunity.id}`
  const profileDirty = description !== opportunity.description
    || JSON.stringify(profile) !== JSON.stringify(opportunity.opportunity_profile ?? EMPTY_PROFILE)
  useEffect(() => {
    dirtyChange.current(profileKey, profileDirty)
  }, [profileKey, profileDirty])
  useEffect(() => () => dirtyChange.current(profileKey, false), [profileKey])
  useEffect(() => {
    setProfile(opportunity.opportunity_profile ?? EMPTY_PROFILE)
    setDescription(opportunity.description)
  }, [opportunity])

  async function saveProfile(): Promise<void> {
    const validationError = validateOpportunityProfile(profile, ownerOptions)
    if (validationError) { setError(validationError); return }
    setSaving(true); setError(""); setNotice("")
    try {
      const updated = await apiRequest<ResearchSubjectDto>(`/api/v1/projects/${encodeURIComponent(projectId)}/research/subjects/${encodeURIComponent(opportunity.id)}`, { method: "PATCH", body: { version: opportunity.version, description: description.trim(), opportunity_profile: opportunityProfileInput(profile) } })
      onOpportunityUpdated(updated); setNotice("机会档案已保存。")
    } catch (caught) {
      setError(opportunityProfileErrorMessage(caught))
    } finally { setSaving(false) }
  }

  return <section className="panel research-opportunity-detail" aria-labelledby="opportunity-detail-heading">
    {adjusting ? <OpportunityAdjustment key={opportunity.id} projectId={projectId} opportunity={opportunity} apiRequest={apiRequest} onSaved={onOpportunityUpdated} onClose={() => setAdjusting(false)} /> : null}
    <header className="research-selection-heading"><div><span className="badge muted">{RESEARCH_SUBJECT_LABELS[opportunity.subject_type]}</span><h2 id="opportunity-detail-heading">{opportunity.name}</h2>{opportunity.tracking_code ? <code>{opportunity.tracking_code}</code> : null}</div><div className="research-opportunity-actions">
      {canFill || canManage ? <details className="opportunity-more-actions" ref={moreActions}>
        <summary className="secondary-button">更多 <svg className="opportunity-more-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg></summary>
        <div className="opportunity-more-dropdown" onClick={(event) => { if (event.target instanceof HTMLButtonElement && !event.target.disabled && moreActions.current) moreActions.current.open = false }}>
          {canFill ? <button type="button" disabled={editing || saving} title={editing ? "请先保存并退出编辑，再使用 AI 调整" : "按要求调整当前机会"} onClick={() => setAdjusting(true)}>AI 调整</button> : null}
          <a className="opportunity-documents-link" href={`#projects/${encodeURIComponent(projectId)}?tab=delivery&opportunity=${encodeURIComponent(opportunity.id)}`}>查看关联方案</a>
          {canManage ? <>
            <button type="button" className="opportunity-more-delete" onClick={onDelete}>删除</button>
          </> : null}
        </div>
      </details> : null}
      {canFill && !editing ? <button type="button" className="primary-button" onClick={onEdit}>编辑</button> : null}<button type="button" className="secondary-button" onClick={onBack}>返回</button>
    </div></header>
    {notice ? <p className="notice" role="status">{notice}</p> : null}{error ? <p className="form-error" role="alert">{error}</p> : null}
    <section className="opportunity-profile-card" aria-labelledby="opportunity-profile-heading" data-research-dirty={profileDirty ? "true" : undefined}><h3 id="opportunity-profile-heading">机会档案</h3>
      {editing ? <div className="opportunity-profile-form">
        <OpportunityProfileFields description={description} profile={profile} ownerOptions={ownerOptions} onDescriptionChange={setDescription} onProfileChange={setProfile} />
        <div className="wide"><button type="button" className="primary-button" disabled={saving} onClick={() => void saveProfile()}>{saving ? "保存中…" : "保存机会档案"}</button></div>
      </div> : <div className="opportunity-profile-grid">
        <ProfileItem label="说明" value={description} wide /><ProfileItem label="目标使用对象" value={profile.target_audience} wide /><ProfileItem label="负责人" value={profile.owner_display_name ?? ""} /><ProfileItem label="状态" value={STATUS_LABELS[profile.opportunity_status]} /><ProfileItem label="优先级" value={profile.priority ? LEVEL_LABELS[profile.priority] : ""} /><ProfileItem label="业务价值" value={scoreLabel("业务价值", profile.business_value_score)} /><ProfileItem label="实施可行性" value={scoreLabel("实施可行性", profile.feasibility_score)} /><ProfileItem label="数据准备度" value={scoreLabel("数据准备度", profile.data_readiness_score)} /><ProfileItem label="风险等级" value={profile.risk_level ? LEVEL_LABELS[profile.risk_level] : ""} /><ProfileItem label="下一步行动" value={profile.next_action} wide />
      </div>}
    </section>
    {forms.length ? forms.map((form) => <ResearchForm key={form.id} projectId={projectId} form={form} canFill={canFill && editing} apiRequest={apiRequest} onUpdate={onUpdate} onDirtyChange={(dirty) => onDirtyChange(form.id, dirty)} onCancel={onBack} />) : <p className="empty-state">该 AI 机会暂无调研表，请先补充调研表。</p>}
  </section>
}

export function OpportunityProfileFields({ description, profile, ownerOptions, disabled = false, onDescriptionChange, onProfileChange }: {
  description: string
  profile: AIOpportunityProfileDto
  ownerOptions: Array<{ id: string; display_name: string }>
  disabled?: boolean
  onDescriptionChange(value: string): void
  onProfileChange(value: AIOpportunityProfileDto): void
}) {
  return <>
    <label className="field wide"><span>说明</span><textarea rows={3} value={description} disabled={disabled} onChange={(event) => onDescriptionChange(event.target.value)} /></label>
    <label className="field wide"><span>目标使用对象</span><input value={profile.target_audience} disabled={disabled} maxLength={300} onChange={(event) => onProfileChange({ ...profile, target_audience: event.target.value })} /></label>
    <SelectField label="负责人" value={profile.owner_user_id ?? ""} disabled={disabled} onChange={(value) => { const owner = ownerOptions.find((item) => item.id === value); onProfileChange({ ...profile, owner_user_id: value || null, owner_display_name: owner?.display_name ?? null }) }} options={ownerOptions.map((item) => ({ value: item.id, label: item.display_name }))} empty="未指定" />
    <SelectField label="状态" value={profile.opportunity_status} disabled={disabled} onChange={(value) => onProfileChange({ ...profile, opportunity_status: value as OpportunityStatus })} options={Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }))} />
    <LevelField label="优先级" value={profile.priority} disabled={disabled} onChange={(value) => onProfileChange({ ...profile, priority: value })} />
    <ScoreField label="业务价值" value={profile.business_value_score} disabled={disabled} onChange={(value) => onProfileChange({ ...profile, business_value_score: value })} />
    <ScoreField label="实施可行性" value={profile.feasibility_score} disabled={disabled} onChange={(value) => onProfileChange({ ...profile, feasibility_score: value })} />
    <ScoreField label="数据准备度" value={profile.data_readiness_score} disabled={disabled} onChange={(value) => onProfileChange({ ...profile, data_readiness_score: value })} />
    <LevelField label="风险等级" value={profile.risk_level} disabled={disabled} onChange={(value) => onProfileChange({ ...profile, risk_level: value })} />
    <label className="field wide"><span>下一步行动</span><textarea rows={3} disabled={disabled} maxLength={1000} value={profile.next_action} onChange={(event) => onProfileChange({ ...profile, next_action: event.target.value })} /></label>
  </>
}

export function opportunityProfileInput(profile: AIOpportunityProfileDto) {
  return {
    target_audience: profile.target_audience.trim(),
    owner_user_id: profile.owner_user_id,
    opportunity_status: profile.opportunity_status,
    priority: profile.priority,
    business_value_score: profile.business_value_score,
    feasibility_score: profile.feasibility_score,
    data_readiness_score: profile.data_readiness_score,
    risk_level: profile.risk_level,
    next_action: profile.next_action.trim(),
  }
}

export function validateOpportunityProfile(profile: AIOpportunityProfileDto, ownerOptions: Array<{ id: string }>): string {
  if (profile.target_audience.trim().length > 300) return "目标使用对象不能超过 300 个字符。"
  if (profile.next_action.trim().length > 1000) return "下一步行动不能超过 1000 个字符。"
  if (!Object.hasOwn(STATUS_LABELS, profile.opportunity_status)) return "状态选项无效，请重新选择。"
  const validLevel = (value: OpportunityLevel | null) => value === null || Object.hasOwn(LEVEL_LABELS, value)
  if (!validLevel(profile.priority)) return "优先级选项无效，请重新选择。"
  if (!validLevel(profile.risk_level)) return "风险等级选项无效，请重新选择。"
  const invalidScore = (value: number | null) => value !== null && (!Number.isInteger(value) || value < 1 || value > 5)
  if (invalidScore(profile.business_value_score)) return "业务价值评分必须是 1 到 5 的整数。"
  if (invalidScore(profile.feasibility_score)) return "实施可行性评分必须是 1 到 5 的整数。"
  if (invalidScore(profile.data_readiness_score)) return "数据准备度评分必须是 1 到 5 的整数。"
  if (profile.owner_user_id && !ownerOptions.some((owner) => owner.id === profile.owner_user_id)) return "负责人已不在当前项目成员中，请重新选择。"
  return ""
}

function ProfileItem({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) { return <div className={`opportunity-profile-item${wide ? " wide" : ""}`}><span>{label}</span><strong>{value}</strong></div> }
function scoreLabel(label: string, value: number | null): string { return value ? `${label} ${value}/5` : "" }
function ScoreField({ label, value, disabled = false, onChange }: { label: string; value: number | null; disabled?: boolean; onChange(value: number | null): void }) { return <label className="field"><span>{label}</span><select aria-label={label} value={value ?? ""} disabled={disabled} onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}><option value="">未评分</option>{[1, 2, 3, 4, 5].map((score) => <option key={score} value={score}>{score} / 5</option>)}</select></label> }
function LevelField({ label, value, disabled = false, onChange }: { label: string; value: OpportunityLevel | null; disabled?: boolean; onChange(value: OpportunityLevel | null): void }) { return <SelectField label={label} value={value ?? ""} disabled={disabled} onChange={(next) => onChange((next || null) as OpportunityLevel | null)} empty="未设置" options={Object.entries(LEVEL_LABELS).map(([option, text]) => ({ value: option, label: text }))} /> }
function SelectField({ label, value, options, empty, disabled = false, onChange }: { label: string; value: string; options: Array<{ value: string; label: string }>; empty?: string; disabled?: boolean; onChange(value: string): void }) { return <label className="field"><span>{label}</span><select aria-label={label} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>{empty ? <option value="">{empty}</option> : null}{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label> }
function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value) }

export function opportunityProfileErrorMessage(error: unknown): string {
  if (!(error instanceof ApiClientError)) return "机会档案保存失败，未知错误。"
  const messages: Record<string, string> = {
    stale_version: "AI 机会已被其他人更新，请刷新后重试。",
    forbidden: "当前账号没有编辑该 AI 机会的权限。",
    invalid_opportunity_profile: "服务端判定机会档案字段不合法，请刷新页面后重新选择评分、状态和负责人。",
    invalid_opportunity_owner: "负责人必须是当前项目中的有效成员。",
    research_subject_not_found: "该 AI 机会不存在或已被删除。",
    research_subject_archived: "该 AI 机会已停用，无法保存。",
    invalid_request: "当前服务版本不兼容 AI 机会档案，请重启本地服务后重试。",
    network_error: "无法连接本地服务，请检查服务是否已启动。",
  }
  return messages[error.code] ?? `机会档案保存失败：${error.message}`
}

export function draftErrorMessage(error: unknown, documentType: "pov_plan" | "sow"): string {
  const name = documentType === "pov_plan" ? "PoV" : "SOW"
  if (!(error instanceof ApiClientError)) return `${name} 文档生成任务提交失败：未知错误。`
  const messages: Record<string, string> = {
    forbidden: `当前账号没有生成 ${name} 文档的权限。`,
    invalid_source_opportunity: `该 AI 机会已失效或不属于当前项目，无法生成 ${name} 文档。`,
    document_template_not_published: `尚未发布 ${name} 文档模板，请先在文档模板中发布后重试。`,
    template_version_not_published: `${name} 文档模板尚未发布，请发布后重试。`,
    template_document_type_mismatch: `已选模板与 ${name} 文档类型不匹配。`,
    stale_version: "项目已被其他人更新，请刷新后重试。",
    invalid_request: `当前服务版本不兼容从 AI 机会创建 ${name} 草稿，请重启本地服务后重试。`,
    network_error: "无法连接本地服务，请检查服务是否已启动。",
  }
  return messages[error.code] ?? `${name} 文档生成任务提交失败：${error.message}`
}
