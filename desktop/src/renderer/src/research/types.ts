export const RESEARCH_SUBJECT_TYPES = [
  "project",
  "department",
  "role",
  "process",
  "opportunity",
] as const

export type ResearchSubjectType = typeof RESEARCH_SUBJECT_TYPES[number]

export const RESEARCH_SUBJECT_LABELS: Record<ResearchSubjectType, string> = {
  project: "企业",
  department: "部门",
  role: "岗位",
  process: "流程",
  opportunity: "AI 机会",
}

// Allowed child subject types for each subject type (used by both the tree's
// "新增" controls and the AI-opportunity panel).
export const CHILD_TYPES_BY_PARENT: Record<ResearchSubjectType, readonly CreatableResearchSubjectType[]> = {
  project: ["department", "process", "opportunity"],
  department: ["role", "process", "opportunity"],
  role: ["process", "opportunity"],
  process: ["opportunity"],
  opportunity: [],
}

export type CreatableResearchSubjectType = Exclude<ResearchSubjectType, "project">

export const RESEARCH_FIELD_TYPES = [
  "short_text",
  "long_text",
  "rich_text",
  "integer",
  "decimal",
  "date",
  "single_choice",
  "multi_choice",
  "table",
  "file_reference",
] as const

export type ResearchFieldType = typeof RESEARCH_FIELD_TYPES[number]
export type ResearchTableColumnType = Exclude<ResearchFieldType, "table" | "file_reference">
export type ResearchConditionLeafOperator = "equals" | "not_equals" | "contains"
export type ResearchConditionGroupOperator = "all" | "any"

export type ResearchJsonValue =
  | string
  | number
  | boolean
  | null
  | ResearchJsonValue[]
  | { [key: string]: ResearchJsonValue }

export type ResearchConditionDto =
  | {
      field_key: string
      operator: ResearchConditionLeafOperator
      value: ResearchJsonValue
    }
  | {
      field_key: string
      operator: "is_empty"
    }
  | { operator: "all"; conditions: ResearchConditionDto[] }
  | { operator: "any"; conditions: ResearchConditionDto[] }

export interface ResearchTextOptionsDto {
  placeholder?: string
  default_value?: string
  min_length?: number
  max_length?: number
}

export interface ResearchRichTextOptionsDto {
  placeholder?: string
  default_value?: string
}

export interface ResearchIntegerOptionsDto {
  minimum?: number
  maximum?: number
  default_value?: number
}

export interface ResearchDecimalOptionsDto {
  minimum?: number
  maximum?: number
  default_value?: number
}

export interface ResearchDateOptionsDto {
  minimum?: string
  maximum?: string
  default_value?: string
}

export interface ResearchSingleChoiceOptionsDto {
  choices: string[]
  default_value?: string
}

export interface ResearchMultiChoiceOptionsDto {
  choices: string[]
  default_value?: string[]
}

export interface ResearchTableColumnDto {
  key: string
  name: string
  type?: ResearchTableColumnType
  options?: ResearchTableColumnOptionsDto
}

export type ResearchTableColumnOptionsDto =
  | ResearchTextOptionsDto
  | ResearchRichTextOptionsDto
  | ResearchIntegerOptionsDto
  | ResearchDecimalOptionsDto
  | ResearchDateOptionsDto
  | ResearchSingleChoiceOptionsDto
  | ResearchMultiChoiceOptionsDto

export interface ResearchTableOptionsDto {
  columns?: ResearchTableColumnDto[]
}

export interface ResearchFileReferenceOptionsDto {
  max_files: number
}

export type ResearchFieldOptionsDto =
  | ResearchTextOptionsDto
  | ResearchRichTextOptionsDto
  | ResearchIntegerOptionsDto
  | ResearchDecimalOptionsDto
  | ResearchDateOptionsDto
  | ResearchSingleChoiceOptionsDto
  | ResearchMultiChoiceOptionsDto
  | ResearchTableOptionsDto
  | ResearchFileReferenceOptionsDto

export interface ResearchFieldDto {
  id: string
  field_key: string
  name: string
  help_text: string
  type: ResearchFieldType
  is_required: boolean
  options: ResearchFieldOptionsDto
  sort_order: number
  condition?: ResearchConditionDto
}

export interface ResearchSectionDto {
  id: string
  section_key: string
  name: string
  description: string
  sort_order: number
  fields: ResearchFieldDto[]
}

export interface ResearchFormDto {
  id: string
  form_key: string
  name: string
  description: string
  subject_type: ResearchSubjectType
  module_key: string | null
  sort_order: number
  sections: ResearchSectionDto[]
}

export interface ResearchDefinitionDto {
  version: number
  forms: ResearchFormDto[]
}

export interface ResearchDefinitionIssueDto {
  code: string
  path: string
}

export interface ResearchRichTextDto {
  type: "doc"
  content: Array<{
    type: "paragraph"
    content: Array<{ type: "text"; text: string }>
  }>
}

export type ResearchScalarAnswer = string | number | string[] | ResearchRichTextDto
export type ResearchTableRowAnswer = Record<string, ResearchScalarAnswer>
export type ResearchAnswerValue = ResearchScalarAnswer | ResearchTableRowAnswer[]
export type ResearchEditableTableRow = Record<string, ResearchScalarAnswer | null>
export type ResearchEditableAnswerValue = ResearchAnswerValue | ResearchEditableTableRow[] | null

export interface ResearchSubjectLinkDto {
  id: string
  project_id: string
  source_subject_id: string
  target_subject_id: string
  link_type: string
}

export interface ResearchSubjectDto {
  id: string
  project_id: string
  parent_subject_id: string | null
  subject_type: ResearchSubjectType
  subject_key: string
  name: string
  description: string
  sort_order: number
  status: "active" | "archived"
  tracking_code: string | null
  version: number
  links: ResearchSubjectLinkDto[]
  opportunity_profile?: AIOpportunityProfileDto | null
}

export type OpportunityStatus = "discovered" | "assessing" | "ready" | "converted" | "paused"
export type OpportunityLevel = "high" | "medium" | "low"

export interface AIOpportunityProfileDto {
  target_audience: string
  owner_user_id: string | null
  owner_display_name: string | null
  opportunity_status: OpportunityStatus
  priority: OpportunityLevel | null
  business_value_score: number | null
  feasibility_score: number | null
  data_readiness_score: number | null
  risk_level: OpportunityLevel | null
  next_action: string
  evidence?: AIOpportunityEvidenceDto[]
  ai_generated?: boolean
}

export interface AIOpportunityEvidenceDto {
  form_id: string
  form_name: string
  field_key: string
  question: string
  answer_excerpt: string
  reason: string
}

export interface ResearchAnswerDto {
  field_key: string
  value: ResearchAnswerValue
}

export interface ResearchFormRevisionDto {
  id: string
  revision_number: number
  parent_revision_id: string | null
  status: "draft" | "confirmed"
  version: number
  returned_by_user_id: string | null
  returned_at: string | null
  return_comment: string | null
  answers: ResearchAnswerDto[]
}

export interface ResearchCompletionDto {
  visible_total: number
  answered_visible: number
  required_total: number
  required_answered: number
  missing_required_count: number
  completion_rate: number
  visible_required_field_keys: string[]
  missing_required_field_keys: string[]
  answered_visible_field_count: number
}

export interface ProjectResearchFormDto {
  id: string
  project_id: string
  subject_id: string
  form_key: string
  name: string
  description: string
  version: number
  current_revision: ResearchFormRevisionDto | null
  completion: ResearchCompletionDto
  definition_snapshot: ResearchFormDto
}

export interface ResearchImportRowDto {
  row: number
  name: unknown
  description: unknown
  parent_name: unknown
}

export interface ResearchImportErrorDto {
  row: number
  column: string
  code: string
  message: string
}

export interface ResearchImportPreviewDto {
  preview_token: string
  subject_type: Exclude<ResearchSubjectType, "project">
  row_count: number
  rows: ResearchImportRowDto[]
  errors: ResearchImportErrorDto[]
  expires_in_seconds: number
}

export interface ResearchImportResultDto {
  subjects: ResearchSubjectDto[]
  imported_count: number
  project_version: number
  idempotent_replay: boolean
}
