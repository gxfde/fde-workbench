import { useEffect, useRef, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { useAuth } from "../auth/AuthProvider"
import type { AppRoute } from "../routing/useHashRoute"
import "./ai-server-chat.css"
import { AIActionConfirmation } from "./AIActionConfirmation"

type Conversation = { id: string; title: string; source: string }
type Turn = { id: string; conversation_id: string; prompt: string; response: string; status: string; error_message: string; metrics?: {model?: {name?: string}; provider_usage?: {complete?: boolean; calls?: Array<{input_tokens: number; output_tokens: number; cache_read_tokens?: number; cache_write_tokens?: number}>}; cost?: {cny_estimate?: string | null; note?: string}} }
type Model = { id: string; name: string; scope: string; provider?: string }
type Progress = {text: string; steps: string[]; phase: string}

export function AIServerChat({ route }: { route: AppRoute }) {
  const { apiRequest, user } = useAuth()
  const [open, setOpen] = useState(false)
  const [historyCollapsed, setHistoryCollapsed] = useState(false)
  const [maximized, setMaximized] = useState(false)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [conversationId, setConversationId] = useState("")
  const [turns, setTurns] = useState<Turn[]>([])
  const [models, setModels] = useState<Model[]>([])
  const [modelId, setModelId] = useState("")
  const [deepThinking, setDeepThinking] = useState(false)
  const [progress, setProgress] = useState<Record<string, Progress>>({})
  const [draft, setDraft] = useState("")
  const [sending, setSending] = useState(false)
  const [error, setError] = useState("")
  const input = useRef<HTMLTextAreaElement>(null)
  const launcher = useRef<HTMLButtonElement>(null)
  const transcript = useRef<HTMLDivElement>(null)
  const followLatest = useRef(true)
  const pendingId = useRef<string | null>(null)
  const sendLock = useRef(false)
  const accountGeneration = useRef(0)
  const busy = sending || turns.some((turn) => ["queued", "running"].includes(turn.status))
  useEffect(() => {
    document.documentElement.dataset.chatBusy = String(busy)
    return () => { delete document.documentElement.dataset.chatBusy }
  }, [busy])

  useEffect(() => {
    accountGeneration.current += 1; sendLock.current = false; setSending(false)
    setDeepThinking(false); setProgress({}); setModels([]); setError(""); setOpen(false); setTurns([]); setConversations([]); setConversationId(""); setDraft(""); setModelId(""); pendingId.current = null
  }, [user?.id])

  useEffect(() => {
    if (!open) return
    let active = true
    void apiRequest<{ items: Conversation[] }>("/api/v1/ai/chat/conversations", { method: "GET" })
      .then((data) => { if (active) setConversations(data.items) })
      .catch((caught) => { if (active) setError(messageOf(caught)) })
    void apiRequest<{ items: Model[] }>("/api/v1/extensions/model-preferences", { method: "GET" })
      .then((data) => { if (active) setModels(data.items.filter(model => model.provider !== "typesafe")) })
      .catch(() => { /* Server-configured default remains available. */ })
    input.current?.focus()
    return () => { active = false }
  }, [open, apiRequest])

  useEffect(() => {
    if (!open || !conversationId) return
    let active = true
    let timer: ReturnType<typeof setTimeout> | undefined
    async function poll() {
      try {
        const data = await apiRequest<{ items: Turn[] }>(`/api/v1/ai/chat/conversations/${conversationId}`, { method: "GET" })
        if (!active) return
        setTurns(data.items)
        const pending = data.items.find(turn => ["queued", "running"].includes(turn.status))
        if (pending) {
          try { const value = await apiRequest<Progress>(`/api/v1/ai/chat/messages/${pending.id}/progress`, {method: "GET"}); if (active) setProgress(current => ({...current, [pending.id]: value})) } catch { /* A temporary progress failure must not discard the saved conversation. */ }
        }
        if (active && data.items.some((t) => ["queued", "running"].includes(t.status))) timer = setTimeout(() => void poll(), 500)
      } catch (caught) { if (active) setError(messageOf(caught)) }
    }
    void poll()
    return () => { active = false; if (timer) clearTimeout(timer) }
  }, [open, conversationId, sending, apiRequest])

  useEffect(() => { followLatest.current = true }, [conversationId, open, user?.id])
  useEffect(() => {
    const element = transcript.current
    if (element && followLatest.current) element.scrollTop = element.scrollHeight
  }, [turns, progress, open])

  async function send() {
    if (!draft.trim() || busy || sendLock.current) return
    const generation = accountGeneration.current
    sendLock.current = true; setSending(true); setError("")
    pendingId.current ??= crypto.randomUUID()
    try {
      const turn = await apiRequest<Turn>("/api/v1/ai/chat/messages", { method: "POST", body: {
        message_id: pendingId.current, conversation_id: conversationId || null, message: draft.trim(),
        project_id: !conversationId && route.kind === "project" ? route.projectId : null,
        model_preference_id: modelId || null, deep_thinking: deepThinking,
      } })
      if (generation !== accountGeneration.current) return
      setConversationId(turn.conversation_id)
      setTurns((current) => [...current.filter((item) => item.id !== turn.id), turn])
      setConversations((current) => current.some((c) => c.id === turn.conversation_id) ? current : [{ id: turn.conversation_id, title: draft.trim().slice(0, 50), source: "desktop" }, ...current])
      setDraft(""); pendingId.current = null
    } catch (caught) { if (generation === accountGeneration.current) setError(messageOf(caught)) }
    finally { if (generation === accountGeneration.current) { setSending(false); sendLock.current = false } }
  }

  function close() { setOpen(false); launcher.current?.focus() }
  return <>
    {open ? <AIActionConfirmation key={user?.id || "signed-out"} /> : null}
    <button ref={launcher} className={`ai-server-launcher${open ? " is-open" : ""}`} type="button" aria-label={open ? "关闭 AI Server 对话" : "打开 AI Server 对话"} aria-expanded={open} aria-controls="ai-server-dialog" onClick={() => open ? close() : setOpen(true)}>
      <svg aria-hidden="true" width="23" height="23" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M20 11.5a8 8 0 0 1-8 8H5l-3 2v-10a9 9 0 1 1 18 0Z" /><path d="M7 11h.01M12 11h.01M17 11h.01" strokeWidth="3" strokeLinecap="round" /></svg>
    </button>
    {open ? <section id="ai-server-dialog" className={`ai-server-dialog${maximized ? ' is-maximized' : ''}`} role="dialog" aria-label="AI Server 对话" onKeyDown={(event) => { if (event.key === "Escape") close() }}>
      <header><div className="ai-chat-heading"><button className="ai-chat-icon-button" type="button" title={historyCollapsed?'展开历史记录':'折叠历史记录'} aria-label={historyCollapsed?'展开历史记录':'折叠历史记录'} aria-expanded={!historyCollapsed} aria-controls="ai-chat-history" onClick={()=>setHistoryCollapsed(!historyCollapsed)}><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/><path d={historyCollapsed?'m13 9 3 3-3 3':'m16 9-3 3 3 3'}/></svg></button><div><strong>AI Server</strong><small>你的工作台智能助手</small></div></div><div className="ai-chat-window-actions"><button className="ai-chat-icon-button" type="button" title={maximized?'还原对话窗口':'放大对话窗口'} aria-label={maximized?'还原对话窗口':'放大对话窗口'} aria-pressed={maximized} onClick={()=>setMaximized(!maximized)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d={maximized?'M9 3v6H3m18 0h-6V3M3 15h6v6m6 0v-6h6':'M9 3H3v6m12-6h6v6M3 15v6h6m6 0h6v-6'}/></svg></button><button className="ai-chat-icon-button" type="button" aria-label="关闭对话" title="关闭对话" onClick={close}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button></div></header>
      <div className="ai-chat-layout"><aside id="ai-chat-history" className="ai-chat-sidebar" hidden={historyCollapsed} aria-label="我的对话"><button className="secondary-button" type="button" disabled={sending} onClick={() => { setConversationId(""); setTurns([]); setError(""); pendingId.current = null }}>＋ 新对话</button><p>仅当前账号可见</p><nav aria-label="对话列表">{conversations.map(c => <button key={c.id} title={c.title} type="button" aria-current={conversationId === c.id ? "page" : undefined} disabled={sending} onClick={() => {setConversationId(c.id);setTurns([]);setError("");pendingId.current=null}}>{c.source === "wechat" ? "微信 · " : ""}{c.title}</button>)}</nav></aside><div className="ai-chat-main">
      <div className="ai-chat-transcript" ref={transcript} aria-live="polite" onScroll={() => {
        const element = transcript.current
        if (element) followLatest.current = element.scrollHeight - element.scrollTop - element.clientHeight <= 24
      }}>
        {!turns.length ? <div className="ai-chat-welcome"><h3>有什么需要帮你？</h3><p>我可以查询项目资料、文件库和任务进度。查询范围与当前账号权限一致。</p>{route.kind === "project" && !conversationId ? <small>新对话将关联当前项目</small> : null}<div>{["我有哪些项目？", "帮我查找项目文件", "系统运行正常吗？", "用普通版立创 Skill 搜索 STM32F103C8T6", "用 Jev 版立创 Skill 搜索 STM32F103C8T6"].map((text) => <button type="button" key={text} onClick={() => { setDraft(text); input.current?.focus() }}>{text}</button>)}</div></div> : turns.map((turn) => <article key={turn.id} className="ai-chat-turn"><div className="ai-chat-user">{turn.prompt}</div><div className="ai-chat-answer"><small>AI Server</small>{progress[turn.id] ? <details className="ai-chat-process" open={["queued","running"].includes(turn.status)}><summary>执行过程 · {turn.status === "completed" ? "已完成" : turn.status === "failed" ? "执行失败" : progress[turn.id].phase}</summary><ol>{progress[turn.id].steps?.map((step,index) => <li key={index}>{step}</li>)}</ol><small>展示实际执行进度，不包含模型内部推理原文。</small></details> : null}{turn.response || progress[turn.id]?.text ? <ReactMarkdown remarkPlugins={[remarkGfm]} components={{a: ({href, children}) => {
          if (href && /^https:\/\/(www|so|item)\.szlcsc\.com\//.test(href)) return <a href={href} onClick={(event) => { event.preventDefault(); void window.fde.app.openLcscBrowser?.(href) }}>{children}</a>
          return <a href={href} target="_blank" rel="noreferrer">{children}</a>
        }}}>{turn.response || progress[turn.id]?.text || ""}</ReactMarkdown> : turn.status === "failed" ? <p role="alert">{turn.error_message || "处理失败，请重新发送。"}</p> : <p className="ai-chat-thinking">{turn.status === "queued" ? "正在排队…" : "正在查询与思考…"}</p>}{turn.status === "completed" && turn.metrics?.model?.name ? <ChatMetrics metrics={turn.metrics} /> : null}</div></article>)}
      </div>
      {error ? <p className="ai-chat-error" role="alert">{error}</p> : null}
      <form className="ai-chat-composer" onSubmit={(event) => { event.preventDefault(); void send() }}><textarea ref={input} aria-label="发给 AI Server 的消息" value={draft} maxLength={16000} placeholder="询问项目、文件或工作台情况…" onChange={(event) => { setDraft(event.target.value); pendingId.current = null }} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send() } }} /><small className="ai-chat-input-hint">Enter 发送 · Shift+Enter 换行</small><div className="ai-chat-send-controls"><select aria-label="对话模型" value={modelId} disabled={busy} onChange={event => {setModelId(event.target.value); setDeepThinking(false); pendingId.current = null}}><option value="">使用我的默认模型</option>{models.map(model => <option key={model.id} value={model.id}>{model.name}</option>)}</select><label className="ai-chat-depth toggle-control"><input type="checkbox" role="switch" checked={deepThinking} disabled={busy || (!!modelId && models.find(model => model.id === modelId)?.provider !== "deepseek")} onChange={event => {setDeepThinking(event.target.checked); pendingId.current = null}} /><span className="toggle-track" aria-hidden="true" />深度思考</label><button type="submit" className="primary-button" disabled={busy || !draft.trim()}>{busy ? "处理中" : "发送"}</button></div></form>
      </div></div>
    </section> : null}
  </>
}

function messageOf(error: unknown): string { return error instanceof Error ? error.message.replaceAll("DSH", "AI Server") : "AI Server 暂时无法连接，请稍后重试。" }

function ChatMetrics({ metrics }: { metrics: NonNullable<Turn["metrics"]> }) {
  const calls = metrics.provider_usage?.calls || []
  const input = calls.reduce((total, call) => total + call.input_tokens + (call.cache_read_tokens || 0) + (call.cache_write_tokens || 0), 0)
  const output = calls.reduce((total, call) => total + call.output_tokens, 0)
  return <details className="ai-chat-process"><summary>对话模型用量 · {metrics.model?.name}</summary>
    {metrics.provider_usage?.complete ? <p>输入 {input} Token · 输出 {output} Token · 人民币估算 {metrics.cost?.cny_estimate == null ? "不可核算" : `¥${metrics.cost.cny_estimate}`}</p> : <p>本次模型调用未返回完整 Token 统计。</p>}
    <small>{metrics.cost?.note || "费用以供应商实际账单为准。"}</small>
  </details>
}
