import { useEffect, useRef, useState } from "react"
import { ApiClientError } from "../api/client"
import { useAIExecution } from "../ai/AIExecutionProvider"
import { useAuth } from "../auth/AuthProvider"
import { GuidanceReview } from "./GuidanceReview"
import { PresurveyGateHint, S3_GATE_BLOCKED_CODE } from "./PresurveyGateHint"
import { isGuidanceAnalysis } from "./runtimeValidation"
import type { GuidanceAnalysisDto } from "./types"

export function PresurveyAnalysisAction({ projectId, fileVersionId, canManage, autoStart = false, onConfirmed }: { projectId: string; fileVersionId: string; canManage: boolean; autoStart?: boolean; onConfirmed?(value: GuidanceAnalysisDto): void }) {
  const { apiRequest } = useAuth(); const [analysis, setAnalysis] = useState<GuidanceAnalysisDto | null>(null); const [error, setError] = useState(""); const [pollError, setPollError] = useState(""); const [busy, setBusy] = useState(false); const [open, setOpen] = useState(false); const [editOnOpen, setEditOnOpen] = useState(false); const [gateBlocked, setGateBlocked] = useState("")
  const { runTask } = useAIExecution()
  const started = useRef(false)
  useEffect(() => {
    if (!analysis || !["queued", "extracting", "analyzing"].includes(analysis.analysis_state)) return
    // J7：轮询失败必须让用户看见——网络持续失败时界面原本永远停在「分析中」。
    // 这里只提示「暂时读不到进度」（任务仍在服务端跑），不清空 analysis，
    // 下一轮轮询继续尝试。
    const timer = window.setInterval(async () => { try { const next = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/guidance-analyses/${encodeURIComponent(analysis.id)}`, { method: "GET" }); if (isGuidanceAnalysis(next)) { setAnalysis(next); setPollError(""); if (!["queued", "extracting", "analyzing"].includes(next.analysis_state)) { setEditOnOpen(next.analysis_state === "ready" && next.status === "draft"); setOpen(true) } } } catch { setPollError("暂时读不到分析进度，正在重试…") } }, 2000)
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
    setBusy(true); setError(""); setGateBlocked("")
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
    } catch (caught) {
      // 台账五.2（goal-d2 S0-3）：任务内 poll 到 failed 抛的正是 failure_message
      // （runTask 原样 rethrow），不能再吞成通用文案；「invalid guidance」是
      // 内部哨兵，仍然回落通用提示。
      // T-A1：G3 诊断开工门 409（presurvey_s3_gate_open）走可读拦截态——
      // 显示服务端原文 + G3 四项清单 + 前往门禁页跳转，不再吞成通用文案。
      if (caught instanceof ApiClientError && caught.code === S3_GATE_BLOCKED_CODE) {
        setGateBlocked(caught.message)
      } else {
        const message = caught instanceof Error ? caught.message : ""
        setError(message && message !== "invalid guidance" ? message : "无法开始 AI 分析，请稍后重试。")
      }
    } finally { setBusy(false) }
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
  return <><button className="secondary-button compact" type="button" disabled={busy} onClick={() => void view()}>{busy ? (analysis ? "加载中…" : "启动中…") : analysis ? "查看预调研分析" : "AI 分析预调研表"}</button>{gateBlocked ? <PresurveyGateHint projectId={projectId} serverMessage={gateBlocked} /> : null}{error ? <span className="inline-error" title={error}>分析失败</span> : null}{pollError ? <span className="inline-error" role="status" title={pollError}>{pollError}</span> : null}{analysis && open ? <GuidanceReview projectId={projectId} initial={analysis} canManage={canManage} initialEditing={editOnOpen} onClose={() => { setOpen(false); setEditOnOpen(false) }} onSaved={(value) => { setAnalysis(value); if (value.status === "confirmed") onConfirmed?.(value) }} /> : null}</>
}
