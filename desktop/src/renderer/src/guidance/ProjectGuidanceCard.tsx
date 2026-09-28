import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { useAuth } from "../auth/AuthProvider"
import { isGuidanceAnalysis } from "./runtimeValidation"
import type { GuidanceAnalysisDto } from "./types"
import { GuidanceReview } from "./GuidanceReview"
import { PresurveyUploadAction } from "./PresurveyUploadAction"

export function ProjectGuidanceCard({ projectId, canManage }: { projectId: string; canManage: boolean }) {
  const { apiRequest } = useAuth(); const [guidance, setGuidance] = useState<GuidanceAnalysisDto | null>(null); const [open, setOpen] = useState(false); const cardRef = useRef<HTMLElement>(null)
  const summaries = useMemo(() => guidance ? guidanceSummaries(guidance) : [], [guidance])
  const minimumCount = Math.min(3, summaries.length)
  const [visibleCount, setVisibleCount] = useState(minimumCount)
  const [fitLimit, setFitLimit] = useState(summaries.length)
  useEffect(() => { let active = true; void apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/guidance`, { method: "GET" }).then((value) => { if (active && isGuidanceAnalysis(value)) setGuidance(value) }).catch(() => {}); return () => { active = false } }, [apiRequest, projectId])
  useEffect(() => { setVisibleCount(minimumCount); setFitLimit(summaries.length) }, [minimumCount, summaries.length])
  useEffect(() => {
    const card = cardRef.current
    const enterprise = card?.previousElementSibling
    if (!(enterprise instanceof HTMLElement)) return
    const recalculate = () => {
      if (window.innerWidth <= 1050) { setVisibleCount(summaries.length); setFitLimit(summaries.length); return }
      setVisibleCount(minimumCount); setFitLimit(summaries.length)
    }
    recalculate()
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(recalculate)
    observer?.observe(enterprise)
    window.addEventListener("resize", recalculate)
    return () => { observer?.disconnect(); window.removeEventListener("resize", recalculate) }
  }, [minimumCount, summaries.length])
  useLayoutEffect(() => {
    const card = cardRef.current
    const enterprise = card?.previousElementSibling
    if (!(card instanceof HTMLElement) || !(enterprise instanceof HTMLElement) || window.innerWidth <= 1050) return
    const targetHeight = enterprise.getBoundingClientRect().height
    if (targetHeight <= 0) return
    if (card.scrollHeight > targetHeight + 1 && visibleCount > minimumCount) {
      const next = visibleCount - 1
      setFitLimit(next); setVisibleCount(next)
    } else if (visibleCount < fitLimit) setVisibleCount(visibleCount + 1)
  }, [fitLimit, minimumCount, visibleCount])
  return <section ref={cardRef} className="panel project-guidance-card" aria-labelledby="project-guidance-title"><div className="panel-heading guidance-card-heading"><h2 id="project-guidance-title">客户目标与项目指引</h2><div className="guidance-heading-actions">{canManage ? <PresurveyUploadAction projectId={projectId} hasGuidance={Boolean(guidance)} onConfirmed={setGuidance} /> : null}{guidance ? <button className="secondary-button compact" onClick={() => setOpen(true)}>查看详情</button> : null}</div></div>
    {!guidance ? <p className="empty-state">暂无已确认的项目指引。上传预调研 DOCX 后，系统会自动分析并生成待审核内容。</p> : <>
      {guidance.source_is_stale ? <p className="form-error banner">当前指引基于旧版预调研表，最新启用版本尚未重新分析。</p> : null}
      <div className="guidance-compact-summary">{summaries.slice(0, Math.max(visibleCount, minimumCount)).map((summary) => <div key={summary.label}><span>{summary.label}</span>{summary.items ? <ul>{summary.items.slice(0, 3).map((item, index) => <li key={index}>{item}</li>)}</ul> : <strong>{summary.text}</strong>}</div>)}</div>
    </>}
    {guidance && open ? <GuidanceReview projectId={projectId} initial={guidance} canManage={canManage} onClose={() => setOpen(false)} onSaved={setGuidance} /> : null}
  </section>
}

interface GuidanceSummary { label: string; text?: string; items?: string[] }

function guidanceSummaries(guidance: GuidanceAnalysisDto): GuidanceSummary[] {
  const itemSummary = (label: string, items: GuidanceAnalysisDto["key_business_problems"]): GuidanceSummary | null => items.length ? { label, items: items.map((item) => item.text) } : null
  return [
    { label: "客户长期愿景", text: guidance.customer_vision },
    { label: "当前阶段目标", text: guidance.current_phase_objective },
    itemSummary("优先关注", guidance.key_business_problems),
    itemSummary("优先部门", guidance.priority_departments),
    itemSummary("优先岗位", guidance.priority_roles),
    itemSummary("优先流程", guidance.priority_processes),
    itemSummary("成功标准", guidance.success_criteria),
    itemSummary("下一步行动", guidance.next_actions),
  ].filter((summary): summary is GuidanceSummary => summary !== null && Boolean(summary.text || summary.items?.length))
}
