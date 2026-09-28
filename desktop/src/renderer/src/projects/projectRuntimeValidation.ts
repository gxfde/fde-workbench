import { isUserRole } from "../../../shared/contracts"
import type {
  GanttTaskDto,
  ProjectDefaultAssignmentDto,
  ProjectBatchAssignmentDto,
  ProjectGanttDto,
  ProjectMemberDto,
  ProjectMemberListDto,
  ProjectMemberMutationDto,
  ProjectModuleMutationDto,
  ProjectModuleMutationTaskDto,
  ProjectTaskDto,
  ProjectTaskStatus,
} from "../workbench/types"

const TASK_STATUSES: readonly ProjectTaskStatus[] = ["not_started", "in_progress", "blocked", "completed", "cancelled"]

export function isProjectTaskDto(value: unknown): value is ProjectTaskDto {
  return isTaskBase(value)
    && "collaborator_user_ids" in value
    && Array.isArray(value.collaborator_user_ids)
    && value.collaborator_user_ids.every(isString)
    && "dependency_keys" in value
    && Array.isArray(value.dependency_keys)
    && value.dependency_keys.every(isString)
}

export function isProjectModuleMutationTaskDto(value: unknown): value is ProjectModuleMutationTaskDto {
  return isTaskBase(value)
}

export function isProjectMemberDto(value: unknown): value is ProjectMemberDto {
  return isRecord(value)
    && hasStrings(value, ["id", "user_id", "display_name"])
    && isUserRole(value.system_role)
    && (value.role === "member" || value.role === "viewer")
}

export function isProjectMemberListDto(value: unknown): value is ProjectMemberListDto {
  return isRecord(value)
    && Array.isArray(value.items)
    && value.items.every(isProjectMemberDto)
    && isPositiveInteger(value.project_version)
}

export function isProjectMemberMutationDto(value: unknown): value is ProjectMemberMutationDto {
  return isProjectMemberDto(value) && "project_version" in value && isPositiveInteger(value.project_version)
}

export function isProjectDefaultAssignmentDto(value: unknown): value is ProjectDefaultAssignmentDto {
  return isRecord(value)
    && isNonNegativeInteger(value.assigned_count)
    && isPositiveInteger(value.project_version)
    && Array.isArray(value.assignments)
    && value.assignments.every((item) => isRecord(item) && hasStrings(item, ["task_id", "assignee_user_id"]))
    && value.assigned_count === value.assignments.length
}

export function isProjectBatchAssignmentDto(value: unknown): value is ProjectBatchAssignmentDto {
  return isRecord(value)
    && isNonNegativeInteger(value.updated_count)
    && isNonNegativeInteger(value.skipped_count)
    && Array.isArray(value.tasks)
    && value.tasks.every(isProjectTaskDto)
    && value.updated_count === value.tasks.length
}

export function isProjectModuleMutationDto(value: unknown): value is ProjectModuleMutationDto {
  return isRecord(value)
    && hasStrings(value, ["id", "module_key", "name", "description"])
    && (value.status === "active" || value.status === "cancelled")
    && isInteger(value.sort_order)
    && isNullableString(value.planned_start_date)
    && isNullableString(value.planned_end_date)
    && isPositiveInteger(value.project_version)
    && Array.isArray(value.tasks)
    && value.tasks.every(isProjectModuleMutationTaskDto)
}

export function isProjectGanttDto(value: unknown): value is ProjectGanttDto {
  return isRecord(value)
    && typeof value.project_id === "string"
    && isRecord(value.range)
    && isNullableString(value.range.start)
    && isNullableString(value.range.end)
    && ((value.range.start === null) === (value.range.end === null))
    && Array.isArray(value.groups)
    && value.groups.every((group) => isRecord(group)
      && hasStrings(group, ["id", "module_key", "name"])
      && (group.status === "active" || group.status === "cancelled")
      && typeof group.cancelled === "boolean"
      && Array.isArray(group.tasks)
      && group.tasks.every(isGanttTaskDto))
}

export function isTaskListDto(value: unknown): value is { items: ProjectTaskDto[] } {
  return isRecord(value) && Array.isArray(value.items) && value.items.every(isProjectTaskDto)
}

function isTaskBase(value: unknown): value is ProjectTaskDto | ProjectModuleMutationTaskDto {
  return isRecord(value)
    && hasStrings(value, [
      "id", "project_module_id", "module_key", "task_key", "name", "description",
      "planned_start_date", "planned_end_date", "blocked_reason",
    ])
    && isTaskStatus(value.status)
    && isPositiveInteger(value.duration_days)
    && (value.default_assignee_role === null || isUserRole(value.default_assignee_role))
    && isNullableString(value.assignee_user_id)
    && typeof value.pending_assignment === "boolean"
    && isProgress(value.progress)
    && isNullableString(value.completed_at)
    && isInteger(value.sort_order)
    && Array.isArray(value.dependency_ids)
    && value.dependency_ids.every(isString)
    && typeof value.dependency_risk === "boolean"
    && Array.isArray(value.incomplete_dependency_ids)
    && value.incomplete_dependency_ids.every(isString)
    && isPositiveInteger(value.version)
}

function isGanttTaskDto(value: unknown): value is GanttTaskDto {
  return isRecord(value)
    && hasStrings(value, ["id", "task_key", "name", "planned_start_date", "planned_end_date"])
    && isTaskStatus(value.status)
    && isProgress(value.progress)
    && typeof value.cancelled === "boolean"
    && Array.isArray(value.dependency_ids)
    && value.dependency_ids.every(isString)
    && typeof value.dependency_risk === "boolean"
    && Array.isArray(value.incomplete_dependency_ids)
    && value.incomplete_dependency_ids.every(isString)
    && (value.assignee === null || (isRecord(value.assignee)
      && hasStrings(value.assignee, ["id", "display_name"])
      && isUserRole(value.assignee.role)))
}

function isTaskStatus(value: unknown): value is ProjectTaskStatus {
  return typeof value === "string" && TASK_STATUSES.some((status) => status === value)
}

function isProgress(value: unknown): value is number {
  return isInteger(value) && value >= 0 && value <= 100
}

function isPositiveInteger(value: unknown): value is number {
  return isInteger(value) && value > 0
}

function isNonNegativeInteger(value: unknown): value is number {
  return isInteger(value) && value >= 0
}

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value)
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string"
}

function isString(value: unknown): value is string {
  return typeof value === "string"
}

function hasStrings(value: Record<string, unknown>, keys: string[]): boolean {
  return keys.every((key) => typeof value[key] === "string")
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}
