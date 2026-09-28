import type { UserRole } from "../../../shared/contracts"

/** DTOs deliberately retain the server's snake_case serialization. */
export interface PageDto<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

export interface WorkbenchUserDto {
  id: string
  username: string
  display_name: string
  role: UserRole
  is_active: boolean
  must_change_password: boolean
  created_at: string
  updated_at: string
}

export interface ProjectPersonDto {
  id: string
  display_name: string
  role: UserRole
}

export type ProjectStatus = "draft" | "active" | "paused" | "completed" | "cancelled"
export type ProjectModuleStatus = "active" | "cancelled"
export type ProjectTaskStatus = "not_started" | "in_progress" | "blocked" | "completed" | "cancelled"

export interface ProjectModuleDto {
  id: string
  module_key: string
  name: string
  description: string
  status: ProjectModuleStatus
  sort_order: number
  planned_start_date: string | null
  planned_end_date: string | null
}

export interface ProjectTaskDto {
  id: string
  project_module_id: string
  module_key: string
  task_key: string
  name: string
  description: string
  status: ProjectTaskStatus
  planned_start_date: string
  planned_end_date: string
  duration_days: number
  default_assignee_role: UserRole | null
  assignee_user_id: string | null
  pending_assignment: boolean
  progress: number
  blocked_reason: string
  completed_at: string | null
  sort_order: number
  collaborator_user_ids: string[]
  dependency_ids: string[]
  dependency_keys: string[]
  dependency_risk: boolean
  incomplete_dependency_ids: string[]
  version: number
}

export interface ProjectMemberDto {
  id: string
  user_id: string
  display_name: string
  system_role: UserRole
  role: "member" | "viewer"
}

/** `GET /projects/{id}/members` only. */
export interface ProjectMemberListDto {
  items: ProjectMemberDto[]
  project_version: number
}

/** `POST` and `PATCH /projects/{id}/members` only. */
export interface ProjectMemberMutationDto extends ProjectMemberDto {
  project_version: number
}

/** `DELETE /projects/{id}/members/{member}` returns HTTP 204 with no body. */
export type ProjectMemberRemovalResponse = void

export interface ProjectDefaultAssignmentItemDto {
  task_id: string
  assignee_user_id: string
}

/** `POST /projects/{id}/tasks/assign-defaults` only. */
export interface ProjectDefaultAssignmentDto {
  assigned_count: number
  assignments: ProjectDefaultAssignmentItemDto[]
  project_version: number
}

export interface ProjectBatchAssignmentDto {
  updated_count: number
  skipped_count: number
  tasks: ProjectTaskDto[]
}

/** Nested task shape returned by project-module append/cancel endpoints. */
export interface ProjectModuleMutationTaskDto {
  id: string
  project_module_id: string
  module_key: string
  task_key: string
  name: string
  description: string
  status: ProjectTaskStatus
  planned_start_date: string
  planned_end_date: string
  duration_days: number
  default_assignee_role: UserRole | null
  assignee_user_id: string | null
  pending_assignment: boolean
  progress: number
  blocked_reason: string
  completed_at: string | null
  sort_order: number
  dependency_ids: string[]
  dependency_risk: boolean
  incomplete_dependency_ids: string[]
  version: number
}

/** `POST /projects/{id}/modules` and `DELETE /projects/{id}/modules/{module}` only. */
export interface ProjectModuleMutationDto extends ProjectModuleDto {
  tasks: ProjectModuleMutationTaskDto[]
  project_version: number
}

export interface TemplateTaskDto {
  id: string
  task_key: string
  name: string
  description: string
  duration_days: number
  default_assignee_role: UserRole
  sort_order: number
  dependency_keys: string[]
}

export interface TemplateModuleDto {
  id: string
  module_catalog_id: string
  module_key: string
  name: string
  description: string
  sort_order: number
  tasks: TemplateTaskDto[]
}

export interface TemplateSnapshotDto {
  template_id: string | null
  template_name: string
  industry_name: string
  description: string
  version_id: string | null
  version_number?: number
  creation_source?: "template" | "presurvey" | "manual"
  modules: ProjectTemplateSnapshotModuleDto[]
}

export interface TemplateVersionDto extends TemplateSnapshotDto {
  template_id: string
  version_id: string
  version_number: number
  modules: TemplateModuleDto[]
  status: "draft" | "published" | "inactive"
  version: number
  published_by_user_id: string | null
  published_at: string | null
}

export interface ProjectTemplateSnapshotModuleDto {
  id: string | null
  module_catalog_id: string
  module_key: string
  name: string
  description: string
  sort_order: number
  tasks: ProjectTemplateSnapshotTaskDto[]
}

export interface ProjectTemplateSnapshotTaskDto {
  id: string | null
  task_key: string
  name: string
  description: string
  duration_days: number
  default_assignee_role: UserRole
  sort_order: number
  dependency_keys: string[]
}

export interface ProjectDto {
  id: string
  project_code: string
  name: string
  enterprise_name: string
  contact_name: string
  contact_phone: string
  address: string
  background: string
  notes: string
  status: ProjectStatus
  planned_start_date: string
  planned_end_date: string | null
  leader_user_id: string
  leader: ProjectPersonDto
  template_version_id: string | null
  industry: string
  completion: number
  version: number
  created_at: string
  updated_at: string
  modules: ProjectModuleDto[]
  tasks?: ProjectTaskDto[]
  members?: ProjectMemberDto[]
  template_snapshot?: TemplateSnapshotDto
}

export interface ModuleCatalogDto {
  id: string
  key: string
  name: string
  description: string
  sort_order: number
  is_active: boolean
  version: number
}

export interface GanttTaskDto {
  id: string
  task_key: string
  name: string
  planned_start_date: string
  planned_end_date: string
  assignee: ProjectPersonDto | null
  progress: number
  status: ProjectTaskStatus
  cancelled: boolean
  dependency_ids: string[]
  dependency_risk: boolean
  incomplete_dependency_ids: string[]
}

export interface ProjectGanttDto {
  project_id: string
  range: { start: string | null; end: string | null }
  groups: Array<{
    id: string
    module_key: string
    name: string
    status: ProjectModuleStatus
    cancelled: boolean
    tasks: GanttTaskDto[]
  }>
}
