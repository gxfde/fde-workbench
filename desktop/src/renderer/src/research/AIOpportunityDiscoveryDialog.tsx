import { useState } from "react"
import { ApiClientError, type RendererApiRequestOptions } from "../api/client"
import { useAIExecution } from "../ai/AIExecutionProvider"
import type { AIOpportunityEvidenceDto, OpportunityLevel, ProjectResearchFormDto, ResearchSubjectDto } from "./types"

const OPPORTUNITY_RESEARCH_ANSWER_KEYS = [
  "current_state", "pain_points", "business_value", "target_scenario", "owner_role", "technical_prereqs",
] as const

type OpportunityResearchAnswers = Record<(typeof OPPORTUNITY_RESEARCH_ANSWER_KEYS)[number], string>

export interface AIOpportunityCandidate {
  id: string; name: string; description: string; target_audience: string
  priority: OpportunityLevel; business_value_score: number; feasibility_score: number
  data_readiness_score: number; risk_level: OpportunityLevel; next_action: string
  research_answers: OpportunityResearchAnswers
  evidence: AIOpportunityEvidenceDto[]
}

interface Props {
  projectId: string; subject: ResearchSubjectDto
  apiRequest<T>(path: string, options: RendererApiRequestOptions): Promise<T>
  onClose(): void
  onCreated(): Promise<void> | void
}

export function AIOpportunityDiscoveryDialog({ projectId, subject, apiRequest, onClose, onCreated }: Props) {
  const { runAI } = useAIExecution()
  const [candidates, setCandidates] = useState<AIOpportunityCandidate[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [includedForms, setIncludedForms] = useState(0)
  const [includedMemos, setIncludedMemos] = useState(0)
  const [references, setReferences] = useState(["personal_memos", "shared_memos", "research_forms", "guidance"])
  const [expand, setExpand] = useState(true)
  const [guidance, setGuidance] = useState("")
  const [analyzing, setAnalyzing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")

  function invalidate() { setCandidates([]); setSelected(new Set()); setError("") }

  async function analyze() {
    if (!references.length) { setError("请至少勾选一类参考内容。"); return }
    invalidate(); setAnalyzing(true); setError("")
    try {
      const value = await runAI<unknown>({
        operation: "project_ai_opportunities_discover",
        title: `AI 正在分析“${subject.name}”的机会`,
        payload: { project_id: projectId, subject_id: subject.id, guidance: references.includes("guidance") ? guidance.trim() : "", references, expand },
      })
      if (!isDiscovery(value)) throw new Error("invalid discovery")
      if (!value.candidates.length) {
        setCandidates([]); setIncludedForms(value.included_form_count); setIncludedMemos(value.included_memo_count ?? 0); setSelected(new Set())
        setError(`已分析 ${evidenceSummary(value.included_form_count, value.included_memo_count ?? 0)}，本次未发现有足够调研依据的 AI 机会。可补充调研表或备忘录后重新分析。`)
        return
      }
      setCandidates(value.candidates); setIncludedForms(value.included_form_count); setIncludedMemos(value.included_memo_count ?? 0)
      setSelected(new Set(value.candidates.map((item) => item.id)))
    } catch (caught) { setError(discoveryError(caught)) }
    finally { setAnalyzing(false) }
  }

  async function createSelected() {
    const chosen = candidates.filter((item) => selected.has(item.id))
    if (!chosen.length) { setError("请至少选择一个 AI 机会候选。") ; return }
    if (chosen.some(item => !item.name.trim())) { setError("请填写所选机会的名称。"); return }
    setSaving(true); setError("")
    try {
      const project = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}`, { method: "GET" })
      let version = isRecord(project) && typeof project.version === "number" ? project.version : 1
      const createdCandidates: Array<{ subjectId: string; candidate: AIOpportunityCandidate }> = []
      for (const [index, item] of chosen.entries()) {
        const created = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/research/subjects`, { method: "POST", body: {
          version, subject_type: "opportunity", subject_key: `ai_opp_${Date.now().toString(36)}_${index}`,
          name: item.name.slice(0, 160), description: item.description, sort_order: index, parent_subject_id: subject.id,
        } })
        if (!isRecord(created) || typeof created.id !== "string" || typeof created.version !== "number") throw new Error("invalid opportunity")
        if (typeof created.project_version === "number") version = created.project_version
        await apiRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/research/subjects/${encodeURIComponent(created.id)}`, { method: "PATCH", body: {
          version: created.version, opportunity_profile: {
            target_audience: item.target_audience, opportunity_status: "discovered", priority: item.priority,
            business_value_score: item.business_value_score, feasibility_score: item.feasibility_score,
            data_readiness_score: item.data_readiness_score, risk_level: item.risk_level,
            next_action: item.next_action, evidence: item.evidence, ai_generated: true,
          },
        } })
        createdCandidates.push({ subjectId: created.id, candidate: item })
      }
      const formCollection = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/research/forms`, { method: "GET" })
      const forms = researchForms(formCollection)
      for (const { subjectId, candidate } of createdCandidates) {
        for (const form of forms.filter((item) => item.subject_id === subjectId && item.current_revision)) {
          const acceptedKeys = opportunityResearchFieldKeys(form)
          const answers = Object.fromEntries(
            Object.entries(candidate.research_answers).filter(([key, value]) => acceptedKeys.has(key) && value.trim()),
          )
          if (!Object.keys(answers).length || !form.current_revision) continue
          await apiRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/research/forms/${encodeURIComponent(form.id)}`, {
            method: "PATCH",
            body: { version: form.current_revision.version, answers },
          })
        }
      }
      await onCreated(); onClose()
    } catch (caught) { setError(caught instanceof ApiClientError ? `保存候选失败：${caught.message}` : "保存 AI 机会候选失败，请稍后重试。") }
    finally { setSaving(false) }
  }

  return <div className="dialog-backdrop" role="presentation"><section className="dialog ai-opportunity-discovery-dialog" role="dialog" aria-modal="true" aria-labelledby="ai-opportunity-discovery-title">
    <div className="dialog-heading"><div><h3 id="ai-opportunity-discovery-title">AI 辅助发现机会</h3><p className="supporting-copy compact-copy">分析“{subject.name}”及其下级对象的已填调研表和备忘录，并给出可追溯证据。</p></div><button className="secondary-button compact" disabled={analyzing || saving} onClick={onClose}>关闭</button></div>
    <fieldset className="ai-reference-options"><legend>参考内容（可多选）</legend>{[["personal_memos","个人备注"],["shared_memos","公共备注"],["research_forms","调研表"],["guidance","补充想法"]].map(([key,label]) => <label key={key}><input type="checkbox" checked={references.includes(key)} disabled={analyzing || saving} onChange={event => {invalidate(); setReferences(current => event.target.checked ? [...current,key] : current.filter(value => value !== key))}} />{label}</label>)}</fieldset>
    <label className="toggle-control"><input type="checkbox" role="switch" checked={expand} disabled={analyzing || saving} onChange={event => {invalidate(); setExpand(event.target.checked)}} /><span className="toggle-track" aria-hidden="true" />开启拓展（根据资料补充场景与验证建议）</label>
    <p className="field-hint">{expand ? "只参考已勾选的内容，拓展建议仍需审核。" : "仅格式整理：不拓展新场景、不额外推演；未提供的内容留空，整理结果可编辑后填入机会表单。评分为默认值，待人工评估。"}</p>
    <label className="field ai-opportunity-guidance" htmlFor="ai-opportunity-guidance">
      <span>补充想法</span>
      <textarea
        id="ai-opportunity-guidance"
        aria-label="补充想法"
        rows={4}
        maxLength={4000}
        value={guidance}
        disabled={analyzing || saving || !references.includes("guidance")}
        placeholder="例如：我想重点看看销售订单预测与生产排程能否结合 AI，优先考虑两个月内可验证的方案。"
        onChange={(event) => {invalidate(); setGuidance(event.target.value)}}
      />
      <small className="field-hint">AI 会将这段话作为分析方向，再结合已填调研资料判断和补全，不会把想法直接当作事实。</small>
      <small className="ai-opportunity-guidance-count">{guidance.length}/4000</small>
    </label>
    {!candidates.length && !analyzing ? <div className="empty-state"><p>AI 不会直接创建正式机会。分析完成后，你可以审核、选择并批量保存候选。</p><button className="primary-button" onClick={() => void analyze()}>开始分析</button></div> : null}
    {candidates.length ? <><p className="field-hint">已分析 {evidenceSummary(includedForms, includedMemos)}，发现 {candidates.length} 个候选。保存时会同步预填“AI 机会调研”，之后仍可手动编辑。</p><div className="ai-opportunity-candidate-list">{candidates.map((item) => <div className="ai-opportunity-candidate" key={item.id}><input type="checkbox" checked={selected.has(item.id)} onChange={(event) => setSelected((current) => { const next = new Set(current); event.target.checked ? next.add(item.id) : next.delete(item.id); return next })} /><div><strong>{item.name}</strong><input aria-label="候选机会名称" value={item.name} onChange={event => setCandidates(current => current.map(candidate => candidate.id === item.id ? { ...candidate, name: event.target.value } : candidate))} /><textarea aria-label="候选机会描述" value={item.description} onChange={event => setCandidates(current => current.map(candidate => candidate.id === item.id ? { ...candidate, description: event.target.value } : candidate))} /><div className="opportunity-list-meta"><span>价值 {item.business_value_score}/5</span><span>可行性 {item.feasibility_score}/5</span><span>数据 {item.data_readiness_score}/5</span><span>{item.evidence.length} 条依据</span></div><details><summary>编辑预填表单</summary>{OPPORTUNITY_RESEARCH_ANSWER_KEYS.map((key, index) => <label className="field" key={key}><span>{["当前现状","痛点问题","业务价值","目标场景","负责人角色","技术前提"][index]}</span><textarea value={item.research_answers?.[key] ?? ""} onChange={event => setCandidates(current => current.map(candidate => candidate.id === item.id ? {...candidate, research_answers: {...candidate.research_answers, [key]: event.target.value}} : candidate))} /></label>)}</details><details><summary>查看调研依据</summary><ul>{item.evidence.map((entry, index) => <li key={index}><strong>{entry.form_name} · {entry.question}</strong><p>{entry.answer_excerpt}</p><small>{entry.reason}</small></li>)}</ul></details></div></div>)}</div></> : null}
    {error ? <p className="form-error banner" role="alert">{error}</p> : null}
    {candidates.length ? <div className="dialog-actions"><button className="secondary-button" disabled={saving} onClick={() => void analyze()}>重新分析</button><button className="primary-button" disabled={saving || !selected.size} onClick={() => void createSelected()}>{saving ? "正在保存…" : `保存所选机会（${selected.size}）`}</button></div> : null}
  </section></div>
}

function isDiscovery(value: unknown): value is { included_form_count: number; included_memo_count?: number; candidates: AIOpportunityCandidate[] } { return isRecord(value) && typeof value.included_form_count === "number" && (value.included_memo_count === undefined || typeof value.included_memo_count === "number") && Array.isArray(value.candidates) }
function evidenceSummary(formCount: number, memoCount: number): string { return `${formCount} 张调研表、${memoCount} 份备忘录` }
function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value) }
function researchForms(value: unknown): ProjectResearchFormDto[] { return isRecord(value) && Array.isArray(value.items) ? value.items.filter(isResearchForm) : [] }
function isResearchForm(value: unknown): value is ProjectResearchFormDto { return isRecord(value) && typeof value.id === "string" && typeof value.subject_id === "string" && isRecord(value.definition_snapshot) && (value.current_revision === null || (isRecord(value.current_revision) && typeof value.current_revision.version === "number")) }
function opportunityResearchFieldKeys(form: ProjectResearchFormDto): Set<string> { return new Set(form.definition_snapshot.sections.flatMap((section) => section.fields).filter((field) => field.type === "short_text" || field.type === "long_text").map((field) => field.field_key).filter((key) => OPPORTUNITY_RESEARCH_ANSWER_KEYS.includes(key as (typeof OPPORTUNITY_RESEARCH_ANSWER_KEYS)[number]))) }
function discoveryError(error: unknown): string { if (!(error instanceof ApiClientError)) return "AI 机会分析失败，请稍后重试。"; const map: Record<string, string> = { research_answers_required: "当前对象及下级对象还没有可用于分析的调研表或备忘录。", ai_service_not_configured: "AI 服务尚未配置，请联系管理员。", ai_timeout: "AI 分析超时，请稍后重试。", request_timeout: "AI 响应时间较长，请稍后重试。", ai_output_invalid: "AI 返回的机会缺少有效调研依据，请重试。", ai_service_unavailable: "暂时无法连接 AI 服务，请稍后重试。" }; return map[error.code] ?? error.message }
