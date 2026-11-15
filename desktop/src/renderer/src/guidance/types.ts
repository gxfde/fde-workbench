export type GuidanceClassification = "customer_stated" | "ai_synthesized" | "ai_inferred" | "open_question" | "human_added"
export type GuidanceSeverity = "high" | "medium" | "low"
// goal-d1 S0-2：key_business_problems 条目可附可签约优先级与交付模块映射（服务端契约可选键）。
export interface GuidanceItemDto {
  text: string; classification: GuidanceClassification; source_refs: string[]; confirmed: boolean
  severity?: GuidanceSeverity; module?: string
}
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
  // T-A2 复核读面（#171 派生投影，服务端唯一权威；旧服务端载荷无此键——可选）。
  redaction_review?: GuidanceRedactionReviewItem[]
}
// 复核清单条目（盲审追批换代）：服务端投影含两类项——
// ① 指纹条目（#463 确证命中）：name_hash 必在；name 为词典反解结果（可
//    null/缺省＝词典故障或词目已删，UI 显示指纹前 8 位占位）；
// ② 疑似聚合哨兵 {suspect_count}（拍板 #6A 零真名：疑似名不逐条入账，
//    聚合计数殿后一条）。
// 旧形状（#160 name/occurrences/matched_dict）仍宽容接受（历史载荷）。
// 守卫整组语义不变：任一项形状非法 ⇒ 整组丢弃（fail 向保守）。
export interface GuidanceRedactionReviewEntry {
  name_hash: string
  name?: string | null
  occurrences: number
  matched_dict: true
}
export interface GuidanceRedactionSuspectAggregate {
  suspect_count: number
}
export type GuidanceRedactionReviewItem =
  | GuidanceRedactionReviewEntry
  | GuidanceRedactionSuspectAggregate
  | LegacyRedactionReviewEntry
export interface LegacyRedactionReviewEntry {
  name: string
  occurrences: number
  matched_dict: boolean
}
function isRedactionReviewItem(value: unknown): boolean {
  if (!value || typeof value !== "object") return false
  const entry = value as Record<string, unknown>
  const finiteCount = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v)
  // 疑似聚合哨兵：仅 suspect_count 一个数据键。
  if (finiteCount(entry.suspect_count) && entry.suspect_count > 0
    && entry.name === undefined && entry.name_hash === undefined
    && entry.occurrences === undefined && entry.matched_dict === undefined) return true
  // 指纹条目（#463 新形状）。
  if (typeof entry.name_hash === "string" && entry.name_hash.length > 0
    && finiteCount(entry.occurrences) && entry.matched_dict === true
    && (entry.name === undefined || entry.name === null || typeof entry.name === "string")) return true
  // 旧形状条目（#160，历史载荷宽容）。
  if (typeof entry.name === "string" && entry.name.length > 0
    && finiteCount(entry.occurrences) && typeof entry.matched_dict === "boolean") return true
  return false
}
export function isRedactionReviewEntries(value: unknown): value is GuidanceRedactionReviewItem[] {
  return Array.isArray(value) && value.length > 0 && value.every(isRedactionReviewItem)
}
// goal-d2：售前轻量录入卡（S0-1 API 的桌面入口；S1–S2 阶段即可填写，无门禁要求）。
export type InterviewMode = "onsite" | "remote" | "hybrid"
export const INTERVIEW_MODES: InterviewMode[] = ["onsite", "remote", "hybrid"]
export const INTERVIEW_MODE_LABELS: Record<InterviewMode, string> = {
  onsite: "现场访谈", remote: "远程访谈", hybrid: "混合",
}
export interface PresurveyIntakeDto {
  project_id: string
  industry: string; scale: string; region: string
  interview_mode: InterviewMode
  interviewee_roles: string[]
  customer_vision: string; phase_objective: string; notes: string
  updated_at?: string | null
}
export function emptyIntake(projectId: string): PresurveyIntakeDto {
  return { project_id: projectId, industry: "", scale: "", region: "", interview_mode: "onsite", interviewee_roles: [], customer_vision: "", phase_objective: "", notes: "" }
}
export function isPresurveyIntake(value: unknown): value is PresurveyIntakeDto {
  if (!value || typeof value !== "object") return false
  const item = value as Record<string, unknown>
  return typeof item.project_id === "string"
    && ["industry", "scale", "region", "customer_vision", "phase_objective", "notes"].every((key) => typeof item[key] === "string")
    && typeof item.interview_mode === "string" && INTERVIEW_MODES.includes(item.interview_mode as InterviewMode)
    && Array.isArray(item.interviewee_roles) && item.interviewee_roles.every((role) => typeof role === "string")
}
