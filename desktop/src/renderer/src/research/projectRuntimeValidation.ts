import { isResearchFormDto } from "./runtimeValidation"
import { isCanonicalDecimalValue, normalizeAsciiEdgeWhitespace, normalizeDecimalValue } from "./conditionValueContract"
import { RESEARCH_SUBJECT_TYPES, type ProjectResearchFormDto, type ResearchAnswerValue, type ResearchFieldDto, type ResearchFormDto, type ResearchFormRevisionDto, type ResearchImportErrorDto, type ResearchImportPreviewDto, type ResearchImportResultDto, type ResearchSubjectDto, type ResearchTableColumnDto } from "./types"

const FILE_REFERENCE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/
const SCRIPT_MARKUP = /<\s*\/?\s*script\b/i

export function isResearchSubjectListDto(value: unknown): value is { items: ResearchSubjectDto[] } {
  return isRecord(value) && exact(value, ["items"]) && Array.isArray(value.items) && value.items.every(isResearchSubjectDto)
}

export function isResearchSubjectDto(value: unknown): value is ResearchSubjectDto {
  return isRecord(value)
    && exact(value, ["id", "project_id", "parent_subject_id", "subject_type", "subject_key", "name", "description", "sort_order", "status", "tracking_code", "version", "links"], ["project_version", "opportunity_profile"])
    && strings(value, ["id", "project_id", "subject_key", "name", "description"])
    && nullableString(value.parent_subject_id)
    && RESEARCH_SUBJECT_TYPES.some((item) => item === value.subject_type)
    && Number.isInteger(value.sort_order)
    && (value.status === "active" || value.status === "archived")
    && nullableString(value.tracking_code)
    && positiveInteger(value.version)
    && (value.project_version === undefined || positiveInteger(value.project_version))
    && Array.isArray(value.links)
    && value.links.every(isSubjectLink)
    && (value.opportunity_profile === undefined || value.opportunity_profile === null || isOpportunityProfile(value.opportunity_profile))
}

function isOpportunityProfile(value: unknown): boolean {
  if (!isRecord(value) || !exact(value, ["target_audience", "owner_user_id", "owner_display_name", "opportunity_status", "priority", "business_value_score", "feasibility_score", "data_readiness_score", "risk_level", "next_action"], ["evidence", "ai_generated"])) return false
  const level = (item: unknown) => item === null || item === "high" || item === "medium" || item === "low"
  const score = (item: unknown) => item === null || (Number.isInteger(item) && Number(item) >= 1 && Number(item) <= 5)
  return typeof value.target_audience === "string"
    && nullableString(value.owner_user_id)
    && nullableString(value.owner_display_name)
    && ["discovered", "assessing", "ready", "converted", "paused"].includes(String(value.opportunity_status))
    && level(value.priority)
    && score(value.business_value_score)
    && score(value.feasibility_score)
    && score(value.data_readiness_score)
    && level(value.risk_level)
    && typeof value.next_action === "string"
    && (value.evidence === undefined || (Array.isArray(value.evidence) && value.evidence.every(isRecord)))
    && (value.ai_generated === undefined || typeof value.ai_generated === "boolean")
}

export function isProjectResearchFormListDto(value: unknown): value is { items: ProjectResearchFormDto[] } {
  return isRecord(value) && exact(value, ["items"]) && Array.isArray(value.items) && value.items.every(isProjectResearchFormDto)
}

export function isProjectResearchFormDto(value: unknown): value is ProjectResearchFormDto {
  if (!(isRecord(value)
    && exact(value, ["id", "project_id", "subject_id", "form_key", "name", "description", "version", "current_revision", "completion", "definition_snapshot"])
    && strings(value, ["id", "project_id", "subject_id", "form_key", "name", "description"])
    && positiveInteger(value.version)
    && (value.current_revision === null || isRevision(value.current_revision))
    && isCompletion(value.completion)
    && isResearchFormDto(value.definition_snapshot))) return false
  return value.current_revision === null || answersMatchDefinition(value.current_revision, value.definition_snapshot)
}

export function isResearchImportPreviewDto(value: unknown): value is ResearchImportPreviewDto {
  return isRecord(value)
    && exact(value, ["preview_token", "subject_type", "row_count", "rows", "errors", "expires_in_seconds"])
    && typeof value.preview_token === "string" && value.preview_token.length > 0
    && RESEARCH_SUBJECT_TYPES.some((item) => item === value.subject_type) && value.subject_type !== "project"
    && nonNegativeInteger(value.row_count)
    && positiveInteger(value.expires_in_seconds)
    && Array.isArray(value.rows) && value.rows.every(isImportRow)
    && Array.isArray(value.errors) && value.errors.every(isImportError)
    && value.row_count === value.rows.length
}

export function isResearchImportResultDto(value: unknown): value is ResearchImportResultDto {
  return isRecord(value)
    && exact(value, ["subjects", "imported_count", "project_version", "idempotent_replay"])
    && Array.isArray(value.subjects) && value.subjects.every(isResearchSubjectDto)
    && nonNegativeInteger(value.imported_count)
    && value.imported_count === value.subjects.length
    && positiveInteger(value.project_version)
    && typeof value.idempotent_replay === "boolean"
}

export function parseResearchImportErrorDetails(value: unknown): ResearchImportErrorDto[] | null {
  if (!isRecord(value) || !exact(value, ["errors"]) || !Array.isArray(value.errors) || !value.errors.every(isImportError)) return null
  return value.errors as ResearchImportErrorDto[]
}

function isRevision(value: unknown): value is ResearchFormRevisionDto {
  return isRecord(value)
    && exact(value, ["id", "revision_number", "parent_revision_id", "status", "version", "returned_by_user_id", "returned_at", "return_comment", "answers"])
    && typeof value.id === "string" && value.id.length > 0
    && positiveInteger(value.revision_number)
    && nullableString(value.parent_revision_id)
    && (value.status === "draft" || value.status === "confirmed")
    && positiveInteger(value.version)
    && nullableString(value.returned_by_user_id)
    && nullableString(value.returned_at)
    && nullableString(value.return_comment)
    && Array.isArray(value.answers)
    && value.answers.every((answer) => isRecord(answer)
      && exact(answer, ["field_key", "value"])
      && typeof answer.field_key === "string"
      && isResearchAnswerValue(answer.value))
}

function answersMatchDefinition(revision: ResearchFormRevisionDto, definition: ResearchFormDto): boolean {
  const fields = definition.sections.flatMap((section) => section.fields)
  const fieldsByKey = new Map(fields.map((field) => [field.field_key, field]))
  if (fieldsByKey.size !== fields.length) return false
  const answeredKeys = new Set<string>()
  for (const answer of revision.answers) {
    const field = fieldsByKey.get(answer.field_key)
    if (!field || answeredKeys.has(answer.field_key) || !answerMatchesField(answer.value, field)) return false
    answeredKeys.add(answer.field_key)
  }
  return true
}

function answerMatchesField(value: unknown, field: ResearchFieldDto): boolean {
  const options = field.options as Record<string, unknown>
  switch (field.type) {
    case "short_text":
    case "long_text":
      return typeof value === "string"
        && normalizeAsciiEdgeWhitespace(value) === value
        && optionalLengthBound(value, options.min_length, options.max_length)
    case "rich_text":
      return isRichText(value)
    case "integer":
      return typeof value === "number" && Number.isSafeInteger(value) && withinNumberBounds(value, options)
    case "decimal":
      return isCanonicalDecimalValue(value) && withinDecimalBounds(value, options)
    case "date":
      return isCanonicalDate(value)
        && (typeof options.minimum !== "string" || value >= options.minimum)
        && (typeof options.maximum !== "string" || value <= options.maximum)
    case "single_choice":
      return typeof value === "string" && Array.isArray(options.choices) && options.choices.includes(value)
    case "multi_choice":
      return Array.isArray(value)
        && value.every((item) => typeof item === "string" && Array.isArray(options.choices) && options.choices.includes(item))
        && new Set(value).size === value.length
    case "table":
      return Array.isArray(value) && Array.isArray(options.columns) && value.every((row) => tableRowMatches(row, options.columns as ResearchTableColumnDto[]))
    case "file_reference":
      return Array.isArray(value)
        && value.every((item) => typeof item === "string" && FILE_REFERENCE.test(item) && item.trim() === item)
        && new Set(value).size === value.length
        && typeof options.max_files === "number" && value.length <= options.max_files
  }
}

function tableRowMatches(value: unknown, columns: ResearchTableColumnDto[]): boolean {
  if (!isRecord(value)) return false
  const byKey = new Map(columns.map((column) => [column.key, column]))
  if (byKey.size !== columns.length || Object.keys(value).length !== columns.length) return false
  return Object.entries(value).every(([key, answer]) => {
    const column = byKey.get(key)
    if (!column) return false
    return answerMatchesField(answer, {
      id: key,
      field_key: key,
      name: column.name,
      help_text: "",
      type: column.type ?? "short_text",
      is_required: true,
      options: column.options ?? {},
      sort_order: 0,
    })
  })
}

function isRichText(value: unknown): boolean {
  return isRecord(value)
    && exact(value, ["type", "content"])
    && value.type === "doc"
    && Array.isArray(value.content)
    && value.content.every((paragraph) => isRecord(paragraph)
      && exact(paragraph, ["type", "content"])
      && paragraph.type === "paragraph"
      && Array.isArray(paragraph.content)
      && paragraph.content.every((node) => isRecord(node)
        && exact(node, ["type", "text"])
        && node.type === "text"
        && typeof node.text === "string"
        && !SCRIPT_MARKUP.test(node.text)))
}

function optionalLengthBound(value: string, minimum: unknown, maximum: unknown): boolean {
  const length = Array.from(value).length
  return (typeof minimum !== "number" || length >= minimum)
    && (typeof maximum !== "number" || length <= maximum)
}

function withinNumberBounds(value: number, options: Record<string, unknown>): boolean {
  return (typeof options.minimum !== "number" || value >= options.minimum)
    && (typeof options.maximum !== "number" || value <= options.maximum)
}

function withinDecimalBounds(value: string, options: Record<string, unknown>): boolean {
  for (const [key, direction] of [["minimum", 1], ["maximum", -1]] as const) {
    const raw = options[key]
    if (raw === undefined) continue
    const limit = normalizeDecimalValue(String(raw))
    if (limit === null || compareDecimals(value, limit) * direction < 0) return false
  }
  return true
}

function compareDecimals(left: string, right: string): number {
  const scale = Math.max(decimalScale(left), decimalScale(right))
  const leftInteger = decimalInteger(left, scale)
  const rightInteger = decimalInteger(right, scale)
  return leftInteger < rightInteger ? -1 : leftInteger > rightInteger ? 1 : 0
}

function decimalScale(value: string): number {
  return value.includes(".") ? value.length - value.indexOf(".") - 1 : 0
}

function decimalInteger(value: string, scale: number): bigint {
  const ownScale = decimalScale(value)
  return BigInt(value.replace(".", "")) * (10n ** BigInt(scale - ownScale))
}

function isCanonicalDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000-")) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

function isCompletion(value: unknown): boolean {
  if (!isRecord(value) || !exact(value, ["visible_total", "answered_visible", "required_total", "required_answered", "missing_required_count", "completion_rate", "visible_required_field_keys", "missing_required_field_keys", "answered_visible_field_count"])) return false
  return ["visible_total", "answered_visible", "required_total", "required_answered", "missing_required_count", "answered_visible_field_count"].every((key) => nonNegativeInteger(value[key]))
    && nonNegativeInteger(value.completion_rate) && value.completion_rate <= 100
    && stringArray(value.visible_required_field_keys)
    && stringArray(value.missing_required_field_keys)
}

function isResearchAnswerValue(value: unknown): value is ResearchAnswerValue {
  if (typeof value === "string" || (typeof value === "number" && Number.isInteger(value))) return true
  if (Array.isArray(value)) return value.every((item) => typeof item === "string" || (isRecord(item) && Object.values(item).every(isResearchAnswerValue)))
  return isRecord(value)
    && exact(value, ["type", "content"])
    && value.type === "doc"
    && Array.isArray(value.content)
    && value.content.every((paragraph) => isRecord(paragraph)
      && exact(paragraph, ["type", "content"])
      && paragraph.type === "paragraph"
      && Array.isArray(paragraph.content)
      && paragraph.content.every((node) => isRecord(node) && exact(node, ["type", "text"]) && node.type === "text" && typeof node.text === "string"))
}

function isSubjectLink(value: unknown): boolean {
  return isRecord(value)
    && exact(value, ["id", "project_id", "source_subject_id", "target_subject_id", "link_type"])
    && strings(value, ["id", "project_id", "source_subject_id", "target_subject_id", "link_type"])
}

function isImportRow(value: unknown): boolean {
  return isRecord(value) && exact(value, ["row", "name", "description", "parent_name"]) && positiveInteger(value.row)
}

function isImportError(value: unknown): boolean {
  return isRecord(value) && exact(value, ["row", "column", "code", "message"]) && positiveInteger(value.row) && strings(value, ["column", "code", "message"])
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function exact(value: Record<string, unknown>, required: string[], optional: string[] = []): boolean {
  const allowed = new Set([...required, ...optional])
  return required.every((key) => Object.hasOwn(value, key)) && Object.keys(value).every((key) => allowed.has(key))
}

function strings(value: Record<string, unknown>, keys: string[]): boolean {
  return keys.every((key) => typeof value[key] === "string")
}

function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string"
}

function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0
}

function nonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
}
