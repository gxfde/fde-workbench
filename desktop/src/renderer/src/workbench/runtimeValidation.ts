import { isUserRole } from "../../../shared/contracts"
import type {
  ModuleCatalogDto,
  ProjectDto,
  ProjectModuleDto,
  ProjectPersonDto,
  ProjectStatus,
  TemplateModuleDto,
  TemplateTaskDto,
  TemplateVersionDto,
  WorkbenchUserDto,
} from "./types"

const PROJECT_STATUSES: readonly ProjectStatus[] = ["draft", "active", "paused", "completed", "cancelled"]

export function isWorkbenchUserDto(value: unknown): value is WorkbenchUserDto {
  return isRecord(value)
    && hasStrings(value, ["id", "username", "display_name", "created_at", "updated_at"])
    && isUserRole(value.role)
    && typeof value.is_active === "boolean"
    && typeof value.must_change_password === "boolean"
}

export function isTemplateVersionDto(value: unknown): value is TemplateVersionDto {
  return isRecord(value)
    && hasStrings(value, ["template_id", "template_name", "industry_name", "description", "version_id"])
    && isPositiveInteger(value.version_number)
    && (value.status === "draft" || value.status === "published" || value.status === "inactive")
    && isPositiveInteger(value.version)
    && isNullableString(value.published_by_user_id)
    && isNullableString(value.published_at)
    && Array.isArray(value.modules)
    && value.modules.every(isTemplateModuleDto)
}

export function isModuleCatalogDto(value: unknown): value is ModuleCatalogDto {
  return isRecord(value)
    && hasStrings(value, ["id", "key", "name", "description"])
    && isInteger(value.sort_order)
    && typeof value.is_active === "boolean"
    && isPositiveInteger(value.version)
}

export function isProjectDto(value: unknown): value is ProjectDto {
  return isRecord(value)
    && hasStrings(value, [
      "id", "project_code", "name", "enterprise_name", "contact_name", "contact_phone", "address",
      "background", "notes", "planned_start_date", "leader_user_id", "industry",
      "created_at", "updated_at",
    ])
    && isProjectStatus(value.status)
    && isNullableString(value.template_version_id)
    && isNullableString(value.planned_end_date)
    && isProjectPersonDto(value.leader)
    && isPercentage(value.completion)
    && isPositiveInteger(value.version)
    && Array.isArray(value.modules)
    && value.modules.every(isProjectModuleDto)
}

function isProjectPersonDto(value: unknown): value is ProjectPersonDto {
  return isRecord(value)
    && hasStrings(value, ["id", "display_name"])
    && isUserRole(value.role)
}

function isProjectModuleDto(value: unknown): value is ProjectModuleDto {
  return isRecord(value)
    && hasStrings(value, ["id", "module_key", "name", "description"])
    && (value.status === "active" || value.status === "cancelled")
    && isInteger(value.sort_order)
    && isNullableString(value.planned_start_date)
    && isNullableString(value.planned_end_date)
}

export function isTemplateModuleDto(value: unknown): value is TemplateModuleDto {
  return isRecord(value)
    && hasStrings(value, ["id", "module_catalog_id", "module_key", "name", "description"])
    && isInteger(value.sort_order)
    && Array.isArray(value.tasks)
    && value.tasks.every(isTemplateTaskDto)
}

function isTemplateTaskDto(value: unknown): value is TemplateTaskDto {
  return isRecord(value)
    && hasStrings(value, ["id", "task_key", "name", "description"])
    && isPositiveInteger(value.duration_days)
    && isUserRole(value.default_assignee_role)
    && isInteger(value.sort_order)
    && Array.isArray(value.dependency_keys)
    && value.dependency_keys.every((key) => typeof key === "string")
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function hasStrings(value: Record<string, unknown>, keys: string[]): boolean {
  return keys.every((key) => typeof value[key] === "string")
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string"
}

function isProjectStatus(value: unknown): value is ProjectStatus {
  return typeof value === "string" && PROJECT_STATUSES.some((status) => status === value)
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0
}

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value)
}

function isPercentage(value: unknown): value is number {
  return isInteger(value) && value >= 0 && value <= 100
}
