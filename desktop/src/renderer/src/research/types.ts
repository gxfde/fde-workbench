export const RESEARCH_SUBJECT_TYPES = [
  "project",
  "department",
  "role",
  "process",
  "opportunity",
] as const

// V3 T-O2b（CR-032 清偿）：subject_type 物理边界已从「内置五类枚举」放宽为码格式
// （迁移 b5d9e3f7a1c6 把三处 CHECK 换成 `^[a-z][a-z0-9_]{0,59}$`）。注册类型落库后
// 桌面读路径必须原样承接——否则一条注册类型数据即令整个调研 tab 报「数据格式异常」。
// 故 `ResearchSubjectType` 放宽为 string（任意合法对象类型码）：读路径校验走
// `isResearchSubjectType`（与 DB CHECK 同尺）、展示走 `researchSubjectLabel`
// （内置取中文标签、注册码原样显示）；内置五类仍由 `RESEARCH_SUBJECT_TYPES`
// 承载写路径（创建/下拉/父子树）。
export type ResearchSubjectType = string

// T-O2b 对象类型码格式（与 server `subject_type ~ '^[a-z][a-z0-9_]{0,59}$'` CHECK 同尺）
const RESEARCH_SUBJECT_TYPE_CODE = /^[a-z][a-z0-9_]{0,59}$/

/** 读路径守卫：subject_type 是否为合法对象类型码（内置五类 ∪ 注册表 active 行皆可）。 */
export function isResearchSubjectType(value: unknown): value is string {
  return typeof value === "string" && RESEARCH_SUBJECT_TYPE_CODE.test(value)
}

export const RESEARCH_SUBJECT_LABELS: Record<string, string> = {
  project: "企业",
  department: "部门",
  role: "岗位",
  process: "流程",
  opportunity: "AI 机会",
}

/**
 * 对象类型 → 显示标签。内置五类取中文标签；注册类型（T-O2b 开放域）无预置
 * 标签，原样回显码本身（CR-032：数据合法、不可因缺标签而拒载或乱显示）。
 */
export function researchSubjectLabel(type: string): string {
  return RESEARCH_SUBJECT_LABELS[type] ?? type
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
  // V3 T-O4b：非空 ⇔ 本行因合并让位（指向同项目存续方）；旧载荷无此键。
  merged_into_subject_id?: string | null
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

export interface ResearchImportMergeCandidateDto {
  name: string
  row: number
  description: string
  matched_subject: {
    id: string
    name: string
    tracking_code: string | null
  }
}

export interface ResearchImportResultDto {
  subjects: ResearchSubjectDto[]
  imported_count: number
  project_version: number
  idempotent_replay: boolean
  merge_candidates: ResearchImportMergeCandidateDto[]
}

// V3 T-O4b 桌面面：subject 合并响应——subject=并入方（target）的最新序列化；
// merge_summary=六面搬迁明细（键名以服务端为权威，值多为计数，画像分支为字符串/null）。
export interface ResearchMergeResultDto {
  subject: ResearchSubjectDto
  merge_summary: Record<string, number | string | null>
}
