import type { GuidanceAnalysisDto, GuidanceItemDto } from "./types"

const states = new Set(["queued", "extracting", "analyzing", "ready", "failed", "cancelled"])
const statuses = new Set(["draft", "confirmed", "superseded"])
const classifications = new Set(["customer_stated", "ai_synthesized", "ai_inferred", "open_question", "human_added"])
const listFields = ["key_business_problems", "priority_departments", "priority_roles", "priority_processes", "success_criteria", "out_of_scope", "data_security_redlines", "systems_and_deployment_constraints", "assumptions", "open_questions", "next_actions"] as const
export function isGuidanceItem(value: unknown): value is GuidanceItemDto {
  return isRecord(value) && typeof value.text === "string" && classifications.has(String(value.classification)) && Array.isArray(value.source_refs) && value.source_refs.every((item) => typeof item === "string") && typeof value.confirmed === "boolean"
}
export function isGuidanceAnalysis(value: unknown): value is GuidanceAnalysisDto {
  return isRecord(value) && ["id", "project_id", "source_filename", "customer_vision", "current_phase_objective", "executive_summary", "failure_code", "failure_message"].every((key) => typeof value[key] === "string")
    && statuses.has(String(value.status)) && states.has(String(value.analysis_state)) && typeof value.version === "number"
    && typeof value.source_is_stale === "boolean" && listFields.every((field) => Array.isArray(value[field]) && value[field].every(isGuidanceItem))
}
function isRecord(value: unknown): value is Record<string, any> { return typeof value === "object" && value !== null && !Array.isArray(value) }
