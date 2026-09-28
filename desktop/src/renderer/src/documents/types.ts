/**
 * Project document DTOs (Task 7 desktop document center).
 *
 * DTOs deliberately retain the server's snake_case serialization so the
 * renderer can pass them straight back to the document API endpoints. Field
 * shapes mirror `fde_api.documents.draft_service` / `version_service`.
 */

export const DOCUMENT_TYPE_KEYS = [
  "research_result",
  "project_plan_progress",
  "prediagnosis",
  "job_description",
  "job_questionnaire",
  "shadowing_record",
  "process_system_map",
  "ai_opportunity_score",
  "scenario_decision",
  "pov_plan",
  "pov_report",
  "sow",
  "weekly_issue",
  "change_request",
  "acceptance",
  "training_handover",
  "contract",
] as const

export type DocumentTypeKey = (typeof DOCUMENT_TYPE_KEYS)[number]

import type { BusinessCategory } from "../businessCategory"

export type { BusinessCategory }

/** `ProjectDocument.status`. */
export type DocumentStatus = "draft" | "confirmed" | "archived"

/** `ProjectDocumentVersion.source`. */
export type DocumentVersionSource = "generated" | "online_revised" | "manual_upload"

/** `ProjectDocumentVersion.status`. */
export type DocumentVersionStatus = "draft" | "confirmed" | "archived"

/** `ProjectFileVersion.preview_status` for a document version. */
export type DocumentPreviewStatus = "none" | "pending" | "ready" | "failed"

/** A slim user reference, e.g. `owner` / `confirmed_by`. */
export interface DocumentUserDto {
  id: string
  display_name: string
}

/**
 * The compact `current_version` shape returned inside a list summary.
 *
 * The Task 7 summary DTO describes `preview_status` here; the Task 6 list
 * serializer emits it for version reports. Both are accepted so the renderer is
 * robust to the server's exact column set.
 */
export interface DocumentVersionSummary {
  id: string
  version_number: number
  source: DocumentVersionSource
  status: DocumentVersionStatus
  docx_file_version_id?: string | null
  preview_file_version_id?: string | null
  preview_status?: DocumentPreviewStatus
  parent_version_id?: string | null
  created_at?: string
}

/** A single item from `GET /api/v1/projects/{projectId}/documents` `data.items`. */
export interface DocumentSummaryDto {
  opportunity_scope?: { instructions?: string; solution?: { id: string; name: string; version: number }; opportunities: Array<{ source_opportunity_id: string; opportunity_name: string; opportunity_tracking_code: string; version: number }> } | null
  id: string
  project_id: string
  document_type: DocumentTypeKey
  business_code: string
  display_name?: string
  /** Optional business stage; `null`/absent means uncategorized. */
  business_category?: BusinessCategory | null
  source_opportunity_id?: string | null
  library_file_id?: string | null
  status: DocumentStatus
  /** The document's own optimistic-lock version counter. */
  version: number
  current_version_id: string | null
  current_version: DocumentVersionSummary | null
  generation_status?: "queued" | "running" | "succeeded" | "failed" | "cancelled" | null
  generation_message?: string
  created_at: string
  updated_at?: string
}

/** `GET /api/v1/projects/{projectId}/documents` response `data`. */
export interface DocumentListDto {
  items: DocumentSummaryDto[]
}

/** Document version as returned by the version-history / generate / revise endpoints. */
export interface DocumentVersionDto {
  id: string
  document_id: string
  version_number: number
  source: DocumentVersionSource
  status: DocumentVersionStatus
  parent_version_id?: string | null
  docx_file_version_id?: string | null
  preview_file_version_id?: string | null
  preview_status?: DocumentPreviewStatus
  sha256?: string
  confirmed_by?: DocumentUserDto | null
  confirmed_at?: string | null
  created_at: string
  updated_at?: string
}

/** The structured, editor-authored draft. */
export interface DocumentDraftDto {
  id: string
  document_id: string
  version: number
  field_overrides: Record<string, unknown>
  rich_text: unknown
  list_selections: Record<string, unknown>
  created_at: string
  updated_at: string
}

/** `GET /api/v1/projects/{projectId}/documents/{documentId}` response `data`. */
export interface DocumentDetailDto {
  id: string
  project_id: string
  document_type: DocumentTypeKey
  business_code: string
  display_name?: string
  /** Optional business stage; `null`/absent means uncategorized. */
  business_category?: BusinessCategory | null
  source_opportunity_id?: string | null
  library_file_id?: string | null
  status: DocumentStatus
  version: number
  source_template_version_id?: string
  current_version_id: string | null
  current_version: DocumentVersionDto | null
  draft: DocumentDraftDto | null
  history: DocumentVersionSummary[]
  owner?: DocumentUserDto | null
  created_at: string
  updated_at?: string
}

/** `GET /api/v1/projects/{projectId}/documents/{versionId}/download-url` / `preview-url` response `data`. */
export interface DocumentUrlDto {
  url: string
  expires_seconds: number
}

/** `POST /api/v1/projects/{projectId}/documents` request body. */
export interface NewDocumentInput {
  document_type: DocumentTypeKey
  template_version_id: string
  /** The project's optimistic-lock version counter (server field: `expected_version`). */
  expected_version: number
  /** Optional business stage; omitted/`null` means uncategorized. */
  business_category?: BusinessCategory | null
}

/** Human-readable Chinese labels for the canonical document types. */
export const DOCUMENT_TYPE_LABELS: Record<DocumentTypeKey, string> = {
  research_result: "调研结果",
  project_plan_progress: "项目计划及进度",
  prediagnosis: "预调研表",
  job_description: "岗位说明书",
  job_questionnaire: "岗位问卷",
  shadowing_record: "现场访谈与跟岗记录",
  process_system_map: "流程与系统数据地图",
  ai_opportunity_score: "AI机会清单与评分表",
  scenario_decision: "场景决策记录",
  pov_plan: "PoV验证方案",
  pov_report: "PoV验证结果报告",
  sow: "SOW工作说明书",
  weekly_issue: "项目周报与问题清单",
  change_request: "需求变更单",
  acceptance: "上线验收单",
  training_handover: "培训与运营移交清单",
  contract: "标准合同",
}

/** Chinese labels for version sources. */
export const DOCUMENT_SOURCE_LABELS: Record<DocumentVersionSource, string> = {
  generated: "系统生成",
  online_revised: "在线修订",
  manual_upload: "人工上传",
}

/** Chinese labels for document / version statuses. */
export const DOCUMENT_STATUS_LABELS: Record<DocumentStatus | DocumentVersionStatus, string> = {
  draft: "草稿",
  confirmed: "已确认",
  archived: "已归档",
}
