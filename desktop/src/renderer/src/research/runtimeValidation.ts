import {
  RESEARCH_FIELD_TYPES,
  RESEARCH_SUBJECT_TYPES,
  type ResearchConditionDto,
  type ResearchDefinitionDto,
  type ResearchFieldDto,
  type ResearchFieldType,
  type ResearchFormDto,
  type ResearchSectionDto,
  type ResearchTableColumnDto,
  type ResearchTableColumnType,
} from "./types"
import {
  hasConditionalDependencyCycle,
  isCanonicalConditionText,
  isCanonicalDecimalValue,
} from "./conditionValueContract"

const TABLE_COLUMN_TYPES: readonly ResearchTableColumnType[] = [
  "short_text",
  "long_text",
  "rich_text",
  "integer",
  "decimal",
  "date",
  "single_choice",
  "multi_choice",
]

export function isResearchDefinitionDto(value: unknown): value is ResearchDefinitionDto {
  if (!(isRecord(value)
    && hasExactKeys(value, ["version", "forms"])
    && isPositiveInteger(value.version)
    && Array.isArray(value.forms)
    && value.forms.every(isResearchFormDto))) return false
  return value.forms.every(hasValidConditionSemantics)
}

export function isResearchFormDto(value: unknown): value is ResearchFormDto {
  return isRecord(value)
    && hasExactKeys(value, [
      "id", "form_key", "name", "description", "subject_type", "module_key", "sort_order", "sections",
    ])
    && hasStrings(value, ["id", "form_key", "name", "description"])
    && isNonEmptyString(value.id)
    && isStableKey(value.form_key)
    && isNonEmptyString(value.name)
    && isOneOf(value.subject_type, RESEARCH_SUBJECT_TYPES)
    && (value.module_key === null || isStableKey(value.module_key))
    && isInteger(value.sort_order)
    && Array.isArray(value.sections)
    && value.sections.every(isResearchSectionDto)
}

export function isResearchSectionDto(value: unknown): value is ResearchSectionDto {
  return isRecord(value)
    && hasExactKeys(value, ["id", "section_key", "name", "description", "sort_order", "fields"])
    && hasStrings(value, ["id", "section_key", "name", "description"])
    && isNonEmptyString(value.id)
    && isStableKey(value.section_key)
    && isNonEmptyString(value.name)
    && isInteger(value.sort_order)
    && Array.isArray(value.fields)
    && value.fields.every(isResearchFieldDto)
}

export function isResearchFieldDto(value: unknown): value is ResearchFieldDto {
  if (!isRecord(value)
    || !hasExactKeys(
      value,
      ["id", "field_key", "name", "help_text", "type", "is_required", "options", "sort_order"],
      ["condition"],
    )
    || !hasStrings(value, ["id", "field_key", "name", "help_text"])
    || !isNonEmptyString(value.id)
    || !isStableKey(value.field_key)
    || !isNonEmptyString(value.name)
    || !isOneOf(value.type, RESEARCH_FIELD_TYPES)
    || typeof value.is_required !== "boolean"
    || !isInteger(value.sort_order)
    || !isOptionsForType(value.type, value.options)) {
    return false
  }
  return !("condition" in value) || isResearchConditionDto(value.condition)
}

export function isResearchConditionDto(value: unknown): value is ResearchConditionDto {
  if (!isRecord(value) || typeof value.operator !== "string") return false
  if (value.operator === "all" || value.operator === "any") {
    return hasExactKeys(value, ["operator", "conditions"])
      && Array.isArray(value.conditions)
      && value.conditions.length > 0
      && value.conditions.every(isResearchConditionDto)
  }
  if (value.operator === "is_empty") {
    return hasExactKeys(value, ["field_key", "operator"])
      && isStableKey(value.field_key)
  }
  return (value.operator === "equals" || value.operator === "not_equals" || value.operator === "contains")
    && hasExactKeys(value, ["field_key", "operator", "value"])
    && isStableKey(value.field_key)
    && isJsonValue(value.value)
}

export function isResearchTableColumnDto(value: unknown): value is ResearchTableColumnDto {
  if (!isRecord(value)
    || !hasExactKeys(value, ["key", "name"], ["type", "options"])
    || !isStableKey(value.key)
    || !isNonEmptyString(value.name)) {
    return false
  }
  const type = value.type === undefined ? "short_text" : value.type
  if (!isOneOf(type, TABLE_COLUMN_TYPES)) return false
  return value.options === undefined || isOptionsForType(type, value.options)
}

function isOptionsForType(type: ResearchFieldType | ResearchTableColumnType, value: unknown): boolean {
  if (!isRecord(value)) return false
  switch (type) {
    case "short_text":
    case "long_text":
      return hasExactKeys(value, [], ["placeholder", "default_value", "min_length", "max_length"])
        && optionalString(value.placeholder)
        && optionalString(value.default_value)
        && optionalNonNegativeInteger(value.min_length)
        && optionalNonNegativeInteger(value.max_length)
        && orderedOptionalNumbers(value.min_length, value.max_length)
    case "rich_text":
      return hasExactKeys(value, [], ["placeholder", "default_value"])
        && optionalString(value.placeholder)
        && optionalString(value.default_value)
    case "integer":
      return hasExactKeys(value, [], ["minimum", "maximum", "default_value"])
        && optionalSafeInteger(value.minimum)
        && optionalSafeInteger(value.maximum)
        && optionalSafeInteger(value.default_value)
        && orderedOptionalNumbers(value.minimum, value.maximum)
    case "decimal":
      return hasExactKeys(value, [], ["minimum", "maximum", "default_value"])
        && optionalFiniteNumber(value.minimum)
        && optionalFiniteNumber(value.maximum)
        && optionalFiniteNumber(value.default_value)
        && orderedOptionalNumbers(value.minimum, value.maximum)
    case "date":
      return hasExactKeys(value, [], ["minimum", "maximum", "default_value"])
        && optionalString(value.minimum)
        && optionalString(value.maximum)
        && optionalString(value.default_value)
    case "single_choice": {
      const choices = value.choices
      return hasExactKeys(value, ["choices"], ["default_value"])
        && isValidChoices(choices)
        && (value.default_value === undefined || (typeof value.default_value === "string" && choices.includes(value.default_value)))
    }
    case "multi_choice": {
      const choices = value.choices
      return hasExactKeys(value, ["choices"], ["default_value"])
        && isValidChoices(choices)
        && (value.default_value === undefined || isStringArray(value.default_value))
        && (value.default_value === undefined || value.default_value.every((item) => choices.includes(item)))
    }
    case "table":
      return hasExactKeys(value, [], ["columns"])
        && (value.columns === undefined || (
          Array.isArray(value.columns)
          && value.columns.every(isResearchTableColumnDto)
          && uniqueColumnKeys(value.columns)
        ))
    case "file_reference":
      return hasExactKeys(value, ["max_files"])
        && isPositiveInteger(value.max_files)
  }
}

function uniqueColumnKeys(columns: ResearchTableColumnDto[]): boolean {
  return new Set(columns.map((column) => column.key)).size === columns.length
}

function hasValidConditionSemantics(form: ResearchFormDto): boolean {
  const fields = form.sections.flatMap((section) => section.fields)
  const byKey = new Map(fields.map((field) => [field.field_key, field]))
  return fields.every((field) => field.condition === undefined || conditionMatchesFieldContract(field.condition, byKey))
    && !hasConditionalDependencyCycle(fields.map((field) => ({ fieldKey: field.field_key, condition: field.condition })))
}

function conditionMatchesFieldContract(
  condition: ResearchConditionDto,
  fields: Map<string, ResearchFieldDto>,
): boolean {
  if (condition.operator === "all" || condition.operator === "any") {
    return condition.conditions.every((child) => conditionMatchesFieldContract(child, fields))
  }
  const referenced = fields.get(condition.field_key)
  if (!referenced) return false
  const allowed = conditionOperatorsForType(referenced.type)
  if (!allowed.includes(condition.operator)) return false
  if (condition.operator === "is_empty") return true
  const value = condition.value
  if (referenced.type === "short_text" || referenced.type === "long_text") {
    return isCanonicalConditionText(value)
  }
  if (referenced.type === "integer") return typeof value === "number" && Number.isSafeInteger(value)
  if (referenced.type === "decimal") return isCanonicalDecimalValue(value)
  if (referenced.type === "date") return isCanonicalDateString(value)
  if (referenced.type === "single_choice" || referenced.type === "multi_choice") {
    return typeof value === "string"
      && "choices" in referenced.options
      && Array.isArray(referenced.options.choices)
      && referenced.options.choices.includes(value)
  }
  return false
}

function conditionOperatorsForType(type: ResearchFieldType): string[] {
  if (type === "short_text" || type === "long_text") return ["equals", "not_equals", "contains", "is_empty"]
  if (type === "integer" || type === "decimal" || type === "date" || type === "single_choice") return ["equals", "not_equals", "is_empty"]
  if (type === "multi_choice") return ["contains", "is_empty"]
  return ["is_empty"]
}

function isCanonicalDateString(value: unknown): boolean {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000-")) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

function isJsonValue(value: unknown): boolean {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true
  if (typeof value === "number") return Number.isFinite(value)
  if (Array.isArray(value)) return value.every(isJsonValue)
  return isRecord(value) && Object.values(value).every(isJsonValue)
}

function hasExactKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[] = [],
): boolean {
  const allowed = new Set([...required, ...optional])
  return required.every((key) => Object.hasOwn(value, key))
    && Object.keys(value).every((key) => allowed.has(key))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function hasStrings(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return keys.every((key) => typeof value[key] === "string")
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0
}

function isStableKey(value: unknown): value is string {
  return typeof value === "string" && /^[a-z][a-z0-9_]*$/.test(value)
}

function isOneOf<T extends string>(value: unknown, allowed: readonly T[]): value is T {
  return typeof value === "string" && allowed.some((item) => item === value)
}

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value)
}

function isPositiveInteger(value: unknown): value is number {
  return isInteger(value) && value > 0
}

function optionalSafeInteger(value: unknown): boolean {
  return value === undefined || (typeof value === "number" && Number.isSafeInteger(value))
}

function optionalNonNegativeInteger(value: unknown): boolean {
  return value === undefined || (isInteger(value) && value >= 0)
}

function optionalFiniteNumber(value: unknown): boolean {
  return value === undefined || (typeof value === "number" && Number.isFinite(value))
}

function optionalString(value: unknown): boolean {
  return value === undefined || typeof value === "string"
}

function orderedOptionalNumbers(minimum: unknown, maximum: unknown): boolean {
  return minimum === undefined || maximum === undefined
    || (typeof minimum === "number" && typeof maximum === "number" && minimum <= maximum)
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
}

function isValidChoices(value: unknown): value is string[] {
  return isStringArray(value)
    && value.length > 0
    && value.every((item) => item.trim().length > 0)
    && new Set(value).size === value.length
}
