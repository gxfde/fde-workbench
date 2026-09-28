import { useEffect, useRef, useState } from "react"
import { ApiClientError } from "../api/client"
import { useAIExecution } from "../ai/AIExecutionProvider"
import { useAuth } from "../auth/AuthProvider"
import { GuidanceReview } from "./GuidanceReview"
import { isGuidanceAnalysis } from "./runtimeValidation"
import type { GuidanceAnalysisDto } from "./types"

export function PresurveyAnalysisAction({ projectId, fileVersionId, canManage, autoStart = false, onConfirmed }: { projectId: string; fileVersionId: string; canManage: boolean; autoStart?: boolean; onConfirmed?(value: GuidanceAnalysisDto): void }) {
  const { apiRequest } = useAuth(); const [analysis, setAnalysis] = useState<GuidanceAnalysisDto | null>(null); const [error, setError] = useState(""); const [busy, setBusy] = useState(false); const [open, setOpen] = useState(false); const [editOnOpen, setEditOnOpen] = useState(false)
  const { runTask } = useAIExecution()
  const started = useRef(false)
  useEffect(() => {
    if (!analysis || !["queued", "extracting", "analyzing"].includes(analysis.analysis_state)) return
    const timer = window.setInterval(async () => { try { const next = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/guidance-analyses/${encodeURIComponent(analysis.id)}`, { method: "GET" }); if (isGuidanceAnalysis(next)) { setAnalysis(next); if (!["queued", "extracting", "analyzing"].includes(next.analysis_state)) { setEditOnOpen(next.analysis_state === "ready" && next.status === "draft"); setOpen(true) } } } catch {} }, 2000)
    return () => window.clearInterval(timer)
  }, [analysis, apiRequest, projectId])
  useEffect(() => {
    if (!canManage || autoStart) return
    let cancelled = false
    void apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/guidance-analyses`, { method: "GET" })
      .then((value) => {
        if (cancelled || !value || typeof value !== "object") return
        const items = (value as { items?: unknown }).items
        if (!Array.isArray(items)) return
        const latest = items.find((item) => isGuidanceAnalysis(item) && item.source_file_version_id === fileVersionId)
        if (latest && isGuidanceAnalysis(latest)) setAnalysis(latest)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [apiRequest, autoStart, canManage, fileVersionId, projectId])
  async function start() {
    setBusy(true); setError("")
    try {
      const next = await runTask<GuidanceAnalysisDto>({ title: "AI 正在分析预调研表", stages: ["正在读取文件库版本", "AI 正在提取文档内容", "正在归纳目标、问题与约束", "正在形成可审核项目指引"], task: async () => {
        const created = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/guidance-analyses`, { method: "POST", body: { source_file_version_id: fileVersionId } })
        if (!isGuidanceAnalysis(created)) throw new Error("invalid guidance")
        let current = created
        while (["queued", "extracting", "analyzing"].includes(current.analysis_state)) {
          await new Promise((resolve) => window.setTimeout(resolve, 1500))
          const value = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/guidance-analyses/${encodeURIComponent(current.id)}`, { method: "GET" })
          if (!isGuidanceAnalysis(value)) throw new Error("invalid guidance")
          current = value
        }
        if (current.analysis_state === "failed") throw new Error(current.failure_message || "AI 分析失败")
        return current
      } })
      setAnalysis(next); setEditOnOpen(next.status === "draft" && next.analysis_state === "ready"); setOpen(true)
    } catch (caught) { setError(caught instanceof ApiClientError ? caught.message : "无法开始 AI 分析，请稍后重试。") } finally { setBusy(false) }
  }
  async function view() {
    if (!analysis) return start()
    setBusy(true); setError("")
    try {
      const next = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/guidance-analyses/${encodeURIComponent(analysis.id)}`, { method: "GET" })
      if (!isGuidanceAnalysis(next)) throw new Error("invalid guidance")
      setAnalysis(next); setEditOnOpen(false); setOpen(true)
    } catch (caught) { setError(caught instanceof ApiClientError ? caught.message : "无法读取预调研分析，请稍后重试。") } finally { setBusy(false) }
  }
  useEffect(() => { if (autoStart && canManage && !started.current) { started.current = true; void start() } }, [autoStart, canManage, fileVersionId])
  if (!canManage) return null
  return <><button className="secondary-button compact" type="button" disabled={busy} onClick={() => void view()}>{busy ? (analysis ? "加载中…" : "启动中…") : analysis ? "查看预调研分析" : "AI 分析预调研表"}</button>{error ? <span className="inline-error" title={error}>分析失败</span> : null}{analysis && open ? <GuidanceReview projectId={projectId} initial={analysis} canManage={canManage} initialEditing={editOnOpen} onClose={() => { setOpen(false); setEditOnOpen(false) }} onSaved={(value) => { setAnalysis(value); if (value.status === "confirmed") onConfirmed?.(value) }} /> : null}</>
}
