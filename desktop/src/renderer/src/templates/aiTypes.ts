export interface AIChatMessage {
  role: "user" | "assistant"
  content: string
}

export interface AIChatDecision {
  status: "need_more_information" | "ready_to_generate"
  message: string
  known_information: Record<string, unknown>
  missing_fields: string[]
  questions: string[]
}
