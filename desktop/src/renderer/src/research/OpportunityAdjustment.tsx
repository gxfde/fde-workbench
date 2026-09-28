import { useEffect, useRef, useState } from "react"
import { ApiClientError, type RendererApiRequestOptions } from "../api/client"
import type { ResearchSubjectDto } from "./types"

type Proposal = { name: string; description: string; target_audience: string; next_action: string }
type Result = { subject_id: string; version: number; proposal: Proposal }

export function OpportunityAdjustment({ projectId, opportunity, apiRequest, onSaved, onClose }: {
  projectId: string; opportunity: ResearchSubjectDto
  apiRequest<T>(path: string, options: RendererApiRequestOptions): Promise<T>
  onSaved(value: ResearchSubjectDto): void; onClose(): void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [instructions, setInstructions] = useState("")
  const [result, setResult] = useState<Result | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  useEffect(() => { dialog.current?.showModal(); return () => dialog.current?.close() }, [])
  async function generate() {
    setBusy(true); setError(""); setResult(null)
    try {
      setResult(await apiRequest<Result>("/api/v1/ai/project-ai-opportunities/adjust", { method: "POST", body: {
        project_id: projectId, subject_id: opportunity.id, version: opportunity.version, instructions: instructions.trim(),
      } }))
    } catch (err) { setError(err instanceof ApiClientError ? err.message : "调整失败，请重试。") }
    finally { setBusy(false) }
  }
  async function save() {
    if (!result) return
    setBusy(true); setError("")
    try {
      const updated = await apiRequest<ResearchSubjectDto>(`/api/v1/projects/${projectId}/research/subjects/${opportunity.id}`, {
        method: "PATCH", body: { version: result.version, name: result.proposal.name.trim(), description: result.proposal.description.trim(),
          opportunity_profile: { target_audience: result.proposal.target_audience.trim(), next_action: result.proposal.next_action.trim() } },
      })
      onSaved(updated); onClose()
    } catch (err) { setError(err instanceof ApiClientError ? (err.code === "stale_version" ? "机会已被更新，未覆盖任何内容。请关闭并刷新后重新调整。" : err.message) : "保存失败，请重试。") }
    finally { setBusy(false) }
  }
  const labels: Record<keyof Proposal, string> = { name: "机会名称", description: "说明", target_audience: "目标使用对象", next_action: "下一步行动" }
  const limits = { name: 160, description: 12000, target_audience: 300, next_action: 1000 }
  return <dialog ref={dialog} className="dialog opportunity-adjustment-dialog" aria-labelledby="opportunity-adjust-title" onCancel={(event) => { event.preventDefault(); if (!busy) onClose() }}>
    <h2 id="opportunity-adjust-title">AI 调整机会</h2>
    <p>调整「{opportunity.name}」的名称、说明、目标使用对象和下一步行动。已有调研表仅作参考，不改动编号、关联关系、负责人、状态及评分。</p>
    <label>调整要求<textarea autoFocus value={instructions} maxLength={4000} rows={4} disabled={busy} placeholder="例如：聚焦 BOM 审核，缩小首期范围，并明确下一步需要验证的内容。" onChange={(event) => { setInstructions(event.target.value); setResult(null) }} /></label>
    {result ? <section><h3>调整预览（可继续编辑）</h3>{(Object.keys(labels) as Array<keyof Proposal>).map((key) => <label key={key}>{labels[key]}<textarea rows={key === "description" ? 6 : 2} maxLength={limits[key]} disabled={busy} value={result.proposal[key]} onChange={(event) => setResult({ ...result, proposal: { ...result.proposal, [key]: event.target.value } })} /></label>)}</section> : null}
    {error ? <p role="alert" className="form-error">{error}</p> : null}
    <div className="opportunity-adjustment-actions"><button className="secondary-button" disabled={busy || !instructions.trim()} onClick={() => void generate()}>{busy ? "处理中…" : result ? "重新生成" : "生成调整建议"}</button><button className="secondary-button" disabled={busy} onClick={onClose}>取消</button><button className="primary-button" disabled={busy || !result?.proposal.name.trim()} onClick={() => void save()}>确认保存到原机会</button></div>
  </dialog>
}
