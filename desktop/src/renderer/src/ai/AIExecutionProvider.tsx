import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"

type ExecutionStatus = "running" | "completed" | "failed"
type AIEventType = "stage_changed" | "reasoning_delta" | "content_delta" | "completed" | "failed"

interface AIExecutionEvent { type: AIEventType; text: string; at: string }
export interface AIExecutionDto {
  id: string; operation: string; status: ExecutionStatus; stage: string
  result: unknown; error: { code: string; message: string; status?: number } | null
  events: AIExecutionEvent[]; next_offset: number; created_at: string; updated_at: string
}

interface RunAIOptions { operation: string; title: string; payload: Record<string, unknown>; autoCloseMs?: number }
interface RunTaskOptions<T> { title: string; stages: string[]; task(): Promise<T> }
interface AIExecutionContextValue { runAI<T>(options: RunAIOptions): Promise<T>; runTask<T>(options: RunTaskOptions<T>): Promise<T> }

const AIExecutionContext = createContext<AIExecutionContextValue | null>(null)

export function AIExecutionProvider({ children }: { children: ReactNode }) {
  const { apiRequest } = useAuth()
  const [execution, setExecution] = useState<AIExecutionDto | null>(null)
  const [title, setTitle] = useState("AI 正在处理")
  const [visible, setVisible] = useState(false)
  const runSequence = useRef(0)
  useEffect(() => {
    document.documentElement.dataset.aiBusy = String(visible && (!execution || execution.status === 'running'))
    return () => { delete document.documentElement.dataset.aiBusy }
  }, [visible, execution])

  const runAI = useCallback(async <T,>({ operation, title: nextTitle, payload, autoCloseMs = 900 }: RunAIOptions): Promise<T> => {
    const sequence = ++runSequence.current
    setTitle(nextTitle); setVisible(true); setExecution(null)
    const started = await apiRequest<unknown>("/api/v1/ai/executions", {
      method: "POST", body: { operation, payload },
    })
    if (!isExecution(started)) throw invalidExecution()
    setExecution(started)
    let current = started
    let offset = 0
    while (current.status === "running") {
      await wait(350)
      const next = await apiRequest<unknown>(`/api/v1/ai/executions/${encodeURIComponent(current.id)}?after=${offset}`, { method: "GET" })
      if (!isExecution(next)) throw invalidExecution()
      offset = next.next_offset
      current = { ...next, events: [...current.events, ...next.events] }
      if (sequence === runSequence.current) setExecution(current)
    }
    if (current.status === "failed") {
      const error = current.error ?? { code: "ai_execution_failed", message: "AI 处理失败，请稍后重试。" }
      throw new ApiClientError(error, error.status)
    }
    if (sequence === runSequence.current) {
      window.setTimeout(() => {
        if (sequence === runSequence.current) setVisible(false)
      }, autoCloseMs)
    }
    return current.result as T
  }, [apiRequest])

  const runTask = useCallback(async <T,>({ title: nextTitle, stages, task }: RunTaskOptions<T>): Promise<T> => {
    const sequence = ++runSequence.current
    const now = new Date().toISOString()
    const id = crypto.randomUUID()
    let current: AIExecutionDto = { id, operation: "background_ai", status: "running", stage: stages[0] ?? "正在准备", result: null, error: null, events: [], next_offset: 0, created_at: now, updated_at: now }
    setTitle(nextTitle); setVisible(true); setExecution(current)
    const timers = stages.slice(1).map((stage, index) => window.setTimeout(() => {
      if (sequence !== runSequence.current) return
      const event = { type: "stage_changed" as const, text: stage, at: new Date().toISOString() }
      current = { ...current, stage, updated_at: event.at, events: [...current.events, event] }
      setExecution(current)
    }, 900 * (index + 1)))
    try {
      const result = await task()
      current = { ...current, status: "completed", stage: "正在校验并整理结果", result, updated_at: new Date().toISOString() }
      if (sequence === runSequence.current) { setExecution(current); window.setTimeout(() => sequence === runSequence.current && setVisible(false), 900) }
      return result
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "AI 处理失败，请稍后重试。"
      current = { ...current, status: "failed", stage: "处理失败", error: { code: "ai_task_failed", message }, updated_at: new Date().toISOString() }
      if (sequence === runSequence.current) setExecution(current)
      throw caught
    } finally { timers.forEach((timer) => window.clearTimeout(timer)) }
  }, [])

  const value = useMemo(() => ({ runAI, runTask }), [runAI, runTask])
  return <AIExecutionContext.Provider value={value}>
    {children}
    {visible ? <AIExecutionPanel title={title} execution={execution} onClose={() => execution?.status === "failed" && setVisible(false)} /> : null}
  </AIExecutionContext.Provider>
}

export function useAIExecution(): AIExecutionContextValue {
  const value = useContext(AIExecutionContext)
  const { apiRequest } = useAuth()
  return useMemo(() => value ?? {
    runAI: async <T,>({ operation, payload }: RunAIOptions): Promise<T> => apiRequest<T>(legacyOperationPath(operation), { method: "POST", body: payload }),
    runTask: async <T,>({ task }: RunTaskOptions<T>): Promise<T> => task(),
  }, [apiRequest, value])
}

export function AIExecutionPanel({ title, execution, onClose }: {
  title: string; execution: AIExecutionDto | null
  onClose(): void
}) {
  const [clock, setClock] = useState(() => Date.now())
  const reasoning = joinEvents(execution?.events, "reasoning_delta")
  const output = joinEvents(execution?.events, "content_delta")
  const reasoningScroll = useAutoFollow(reasoning, execution?.id)
  const outputScroll = useAutoFollow(output, execution?.id)
  useEffect(() => {
    setClock(Date.now())
    if (execution?.status !== "running") return
    const timer = window.setInterval(() => setClock(Date.now()), 1_000)
    return () => window.clearInterval(timer)
  }, [execution?.id, execution?.status])
  const failed = execution?.status === "failed"
  return <div className="ai-execution-backdrop" role="presentation">
    <section className="ai-execution-panel" role="dialog" aria-modal="true" aria-labelledby="ai-execution-title">
      <header className="ai-execution-heading">
        <div><p className="eyebrow">AI 执行中心</p><h3 id="ai-execution-title">{title}</h3></div>
        <div className="ai-execution-actions">{failed ? <button className="secondary-button compact" type="button" onClick={onClose}>关闭</button> : null}</div>
      </header>
      <div className={`ai-execution-status ${failed ? "failed" : execution?.status === "completed" ? "completed" : ""}`} role="status">
        <span className="ai-orbit" aria-hidden="true"><i /><i /><i /></span>
        <div><strong>{execution?.stage ?? "正在启动 AI"}</strong><p>{failed ? execution?.error?.message : execution?.status === "completed" ? "结果已通过校验，即将返回原页面。" : "正在执行，请稍候。"}</p></div>
      </div>
      <div className="ai-execution-stream" aria-live="polite">
        <section><h4>分析过程</h4><pre ref={reasoningScroll.ref} onScroll={reasoningScroll.onScroll}>{reasoning || stageTranscript(execution?.events) || "正在建立安全连接并准备上下文…"}</pre></section>
        <section><h4>实时输出</h4><pre ref={outputScroll.ref} onScroll={outputScroll.onScroll}>{output || "等待 AI 返回内容…"}</pre></section>
      </div>
      {execution ? <footer className="ai-execution-footer"><span>执行编号 {execution.id.slice(0, 8)}</span><span>{elapsed(execution.created_at, execution.status === "running" ? clock : execution.updated_at)}</span></footer> : null}
    </section>
  </div>
}

function useAutoFollow(content: string, resetKey: string | undefined) {
  const ref = useRef<HTMLPreElement>(null)
  const following = useRef(true)

  useEffect(() => {
    following.current = true
    const frame = window.requestAnimationFrame(() => {
      const element = ref.current
      if (element) element.scrollTop = element.scrollHeight
    })
    return () => window.cancelAnimationFrame(frame)
  }, [resetKey])

  useEffect(() => {
    if (!following.current) return
    const element = ref.current
    if (element) element.scrollTop = element.scrollHeight
  }, [content])

  return {
    ref,
    onScroll: () => {
      const element = ref.current
      if (!element) return
      following.current = element.scrollHeight - element.scrollTop - element.clientHeight <= 24
    },
  }
}

function joinEvents(events: AIExecutionEvent[] | undefined, type: AIEventType): string {
  return (events ?? []).filter((event) => event.type === type).map((event) => event.text).join("").slice(-12_000)
}
function stageTranscript(events: AIExecutionEvent[] | undefined): string {
  return (events ?? []).filter((event) => event.type === "stage_changed").map((event) => `• ${event.text}`).join("\n")
}
function elapsed(start: string, end: string | number): string {
  const endTime = typeof end === "number" ? end : Date.parse(end)
  const seconds = Math.max(0, Math.floor((endTime - Date.parse(start)) / 1000))
  return `已执行 ${seconds} 秒`
}
function wait(ms: number): Promise<void> { return new Promise((resolve) => window.setTimeout(resolve, ms)) }
function invalidExecution(): ApiClientError { return new ApiClientError({ code: "invalid_ai_execution", message: "AI 执行状态格式不正确。" }) }
function legacyOperationPath(operation: string): string {
  const paths: Record<string, string> = {
    industry_template_chat: "/api/v1/ai/industry-template/chat",
    project_draft_chat: "/api/v1/ai/industry-template/chat",
    industry_template_generate: "/api/v1/ai/industry-template/generate",
    project_draft_generate: "/api/v1/ai/industry-template/generate",
    industry_research_form_generate: "/api/v1/ai/industry-template/research-form/generate",
    project_research_form_generate: "/api/v1/ai/project-research-form/generate",
    project_ai_opportunities_discover: "/api/v1/ai/project-ai-opportunities/discover",
  }
  const path = paths[operation]
  if (!path) throw new Error(`Unsupported AI operation: ${operation}`)
  return path
}
function isExecution(value: unknown): value is AIExecutionDto {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false
  const item = value as Record<string, unknown>
  return typeof item.id === "string" && ["running", "completed", "failed"].includes(String(item.status)) && typeof item.stage === "string" && Array.isArray(item.events) && typeof item.next_offset === "number"
}
