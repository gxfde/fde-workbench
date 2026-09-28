export type GuidanceClassification = "customer_stated" | "ai_synthesized" | "ai_inferred" | "open_question" | "human_added"
export interface GuidanceItemDto { text: string; classification: GuidanceClassification; source_refs: string[]; confirmed: boolean }
export interface GuidanceAnalysisDto {
  id: string; project_id: string; version_number: number; source_file_id: string; source_file_version_id: string
  source_filename: string; status: "draft" | "confirmed" | "superseded"
  analysis_state: "queued" | "extracting" | "analyzing" | "ready" | "failed" | "cancelled"
  customer_vision: string; current_phase_objective: string; executive_summary: string
  key_business_problems: GuidanceItemDto[]; priority_departments: GuidanceItemDto[]; priority_roles: GuidanceItemDto[]
  priority_processes: GuidanceItemDto[]; success_criteria: GuidanceItemDto[]; out_of_scope: GuidanceItemDto[]
  data_security_redlines: GuidanceItemDto[]; systems_and_deployment_constraints: GuidanceItemDto[]
  assumptions: GuidanceItemDto[]; open_questions: GuidanceItemDto[]; next_actions: GuidanceItemDto[]
  failure_code: string; failure_message: string; source_is_stale: boolean; version: number
}
