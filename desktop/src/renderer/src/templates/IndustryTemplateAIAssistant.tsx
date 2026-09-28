import { useState } from "react"

import { ApiClientError } from "../api/client"
import { useAIExecution } from "../ai/AIExecutionProvider"
import { useAuth } from "../auth/AuthProvider"
import { isTemplateVersionDto } from "../workbench/runtimeValidation"
import type { ModuleCatalogDto, TemplateVersionDto } from "../workbench/types"
import { isAIChatDecision } from "./aiRuntimeValidation"
import type { AIChatMessage } from "./aiTypes"


export function IndustryTemplateAIAssistant({
  catalog,
  onGenerated,
  onClose,
}: {
  catalog: ModuleCatalogDto[]
  onGenerated(version: TemplateVersionDto): void
  onClose(): void
}) {
  const { apiRequest, user } = useAuth()
  const { runAI } = useAIExecution()
  const [messages, setMessages] = useState<AIChatMessage[]>([])
  const [questions, setQuestions] = useState<string[]>([])
  const [knownInformation, setKnownInformation] = useState<Record<string, unknown>>({})
  const [input, setInput] = useState("")
  const [busy, setBusy] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [generationId, setGenerationId] = useState<string | null>(null)
  const [error, setError] = useState("")

  async function send(): Promise<void> {
    const content = input.trim()
    if (!content || busy || generating) return
    const nextMessages: AIChatMessage[] = [...messages, { role: "user", content }]
    setMessages(nextMessages)
    setInput("")
    setQuestions([])
    setError("")
    setBusy(true)
    try {
      const value = await runAI<unknown>({ operation: "industry_template_chat", title: "AI 正在理解模板需求", payload: { messages: nextMessages } })
      if (!isAIChatDecision(value)) throw new Error("invalid_ai_response")
      const withAssistant: AIChatMessage[] = [
        ...nextMessages,
        { role: "assistant", content: value.message },
      ]
      setMessages(withAssistant)
      setQuestions(value.questions)
      setKnownInformation(value.known_information)
      if (value.status === "ready_to_generate") {
        await generate(withAssistant, value.known_information)
      }
    } catch (caught) {
      setError(aiErrorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  async function generate(
    currentMessages: AIChatMessage[],
    knownInformation: Record<string, unknown>,
  ): Promise<void> {
    const id = createGenerationId()
    setGenerationId(id)
    setGenerating(true)
    try {
      const value = await runAI<unknown>({ operation: "industry_template_generate", title: "AI 正在生成行业模板草稿", payload: {
          generation_id: id,
          messages: currentMessages,
          known_information: knownInformation,
      } })
      if (!isTemplateVersionDto(value)) throw new Error("invalid_template_response")
      onGenerated(value)
    } catch (caught) {
      setError(aiErrorMessage(caught))
      setGenerating(false)
    }
  }

  async function cancel(): Promise<void> {
    if (generationId) {
      try {
        await apiRequest(`/api/v1/ai/industry-template/generations/${generationId}`, {
          method: "DELETE",
        })
      } catch {
        // Closing locally is still safe; the server checks cancellation before persistence.
      }
    }
    onClose()
  }

  function requestClose(): void {
    if (messages.length > 0 && !window.confirm("当前 AI 对话尚未完成，确定关闭吗？")) return
    onClose()
  }

  return (
    <div className="dialog-backdrop">
      <section className="dialog ai-template-dialog" role="dialog" aria-modal="true" aria-labelledby="ai-template-title">
        <div className="dialog-heading">
          <div>
            <h3 id="ai-template-title">AI 辅助创建行业模板</h3>
            <p className="supporting-copy compact-copy">通过多轮对话生成草稿，仍需人工审核后发布。</p>
          </div>
          <button className="secondary-button compact" type="button" disabled={generating} onClick={requestClose}>关闭</button>
        </div>

        <div className="ai-chat-log content-sized" aria-live="polite">
          {messages.length === 0 ? <p className="empty-state">输入企业名称、行业名称或一句需求，AI 会直接生成可修改的草稿。</p> : null}
          {messages.map((message, index) => (
            <div key={`${message.role}-${index}`} className={`ai-chat-message ${message.role}`}>
              <strong>{message.role === "user" ? (user?.username || "用户") : "AI"}</strong>
              <p>{message.content}</p>
            </div>
          ))}
          {questions.length ? <ul className="ai-question-list">{questions.map((question) => <li key={question}>{question}</li>)}</ul> : null}
        </div>

        {error ? <p className="form-error banner" role="alert">{error}</p> : null}
        <div className="field">
          <label htmlFor="industry-template-ai-input">告诉 AI 你的需求</label>
          <textarea
            id="industry-template-ai-input"
            rows={4}
            maxLength={4000}
            value={input}
            disabled={busy || generating}
            onChange={(event) => setInput(event.target.value)}
          />
        </div>
        <div className="dialog-actions">
          {generating ? <button className="secondary-button" type="button" onClick={() => void cancel()}>取消生成</button> : null}
          {!generating && !busy && questions.length > 0 ? (
            <button className="secondary-button" type="button" onClick={() => void generate(messages, knownInformation)}>按现有信息生成草稿</button>
          ) : null}
          <button className="primary-button" type="button" disabled={busy || generating || !input.trim() || catalog.length === 0} onClick={() => void send()}>
            {busy ? "正在发送" : "发送"}
          </button>
        </div>
      </section>
    </div>
  )
}

function createGenerationId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `00000000-0000-4000-8000-${Date.now().toString().padStart(12, "0").slice(-12)}`
}

function aiErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError) {
    const messages: Record<string, string> = {
      ai_service_not_configured: "AI 服务尚未配置，请联系管理员。",
      ai_authentication_failed: "AI 服务认证失败，请检查服务端配置。",
      ai_rate_limited: "请求过于频繁，请稍后重试。",
      ai_timeout: "生成超时，可保留当前对话后重试。",
      request_timeout: "AI 响应时间较长，请稍后重试；当前对话已保留。",
      network_error: "无法连接本地服务，请确认服务已启动。",
      ai_empty_response: "AI 未返回有效内容，可重试。",
      ai_output_invalid: error.message || "AI 生成内容不符合模板要求，请重试。",
      generation_cancelled: "生成已取消，未创建草稿。",
      template_conflict: "模板创建发生冲突，请修改名称或重试。",
      not_found: "AI 接口不可用，请重启本地服务或联系管理员检查版本。",
      internal_error: "系统发生异常，请稍后重试。",
    }
    return messages[error.code] ?? error.message
  }
  return "AI 返回内容格式无效，请重试。"
}
