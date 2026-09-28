import type { AIChatDecision } from "./aiTypes"

export function isAIChatDecision(value: unknown): value is AIChatDecision {
  if (!isRecord(value)) return false
  return (value.status === "need_more_information" || value.status === "ready_to_generate")
    && typeof value.message === "string"
    && isRecord(value.known_information)
    && isStringArray(value.missing_fields)
    && isStringArray(value.questions)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
}
