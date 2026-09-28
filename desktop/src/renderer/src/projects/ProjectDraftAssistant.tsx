import { useState } from "react"

import { useAIExecution } from "../ai/AIExecutionProvider"
import { useAuth } from "../auth/AuthProvider"
import { isAIChatDecision } from "../templates/aiRuntimeValidation"
import type { AIChatMessage } from "../templates/aiTypes"

export interface ProjectConfigurationDraft {
  industry_name: string
  description: string
  modules: Array<Record<string, unknown>>
  known_information?: Record<string, unknown>
}

export function ProjectDraftAssistant({ onApply, onClose }: { onApply(draft: ProjectConfigurationDraft): void; onClose(): void }) {
  const { user } = useAuth()
  const { runAI } = useAIExecution()
  const [messages, setMessages] = useState<AIChatMessage[]>([])
  const [known, setKnown] = useState<Record<string, unknown>>({})
  const [input, setInput] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  async function send() {
    const content = input.trim()
    if (!content || busy) return
    const next = [...messages, { role: "user", content } satisfies AIChatMessage]
    setMessages(next); setInput(""); setBusy(true); setError("")
    try {
      const decision = await runAI<unknown>({ operation: "project_draft_chat", title: "AI 正在理解项目需求", payload: { messages: next } })
      if (!isAIChatDecision(decision)) throw new Error("invalid decision")
      const history = [...next, { role: "assistant", content: decision.message } satisfies AIChatMessage]
      setMessages(history); setKnown(decision.known_information)
      if (decision.status === "ready_to_generate") await generate(history, decision.known_information)
    } catch { setError("AI 未能生成有效项目草稿，请调整描述后重试。") }
    finally { setBusy(false) }
  }

  async function generate(history = messages, information = known) {
    setBusy(true); setError("")
    try {
      const value = await runAI<unknown>({ operation: "project_draft_generate", title: "AI 正在生成项目配置草稿", payload: { generation_id: crypto.randomUUID(), messages: history, known_information: information } })
      if (!isDraft(value)) throw new Error("invalid draft")
      onApply({ industry_name: value.industry_name, description: value.description, modules: value.modules, known_information: information })
    } catch { setError("AI 返回的项目配置不完整，请重试。") }
    finally { setBusy(false) }
  }

  return <div className="dialog-backdrop"><section className="dialog ai-template-dialog" role="dialog" aria-modal="true" aria-labelledby="project-draft-ai-title">
    <div className="dialog-heading"><div><h3 id="project-draft-ai-title">AI 辅助填写项目</h3><p className="supporting-copy compact-copy">通过多轮对话整理基础资料、模块和任务，生成后仍可手动调整。</p></div><button className="secondary-button compact" type="button" disabled={busy} onClick={onClose}>关闭</button></div>
    <div className="ai-chat-log content-sized">{messages.length ? messages.map((message, index) => <div className={`ai-chat-message ${message.role}`} key={index}><strong>{message.role === "user" ? user?.username : "AI"}</strong><p>{message.content}</p></div>) : <p className="empty-state">描述企业、已有资料、目标和希望启用的模块即可。</p>}</div>
    {error ? <p className="form-error banner">{error}</p> : null}
    <label className="field"><span>告诉 AI 你的项目需求</span><textarea rows={4} value={input} disabled={busy} onChange={(event) => setInput(event.target.value)} /></label>
    <div className="dialog-actions">{messages.length ? <button className="secondary-button" disabled={busy} onClick={() => void generate()}>按现有信息生成</button> : null}<button className="primary-button" disabled={busy || !input.trim()} onClick={() => void send()}>发送</button></div>
  </section></div>
}

function isDraft(value: unknown): value is { industry_name: string; description: string; modules: Array<Record<string, unknown>> } {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false
  const draft = value as Record<string, unknown>
  return typeof draft.industry_name === "string" && typeof draft.description === "string" && Array.isArray(draft.modules) && draft.modules.length > 0
}
