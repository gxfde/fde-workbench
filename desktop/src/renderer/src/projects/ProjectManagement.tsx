import type { ProjectDto } from "../workbench/types"
import { ProjectMembers } from "./ProjectMembers"
import { ProjectModules } from "./ProjectModules"

export function ProjectManagement({
  project,
  canManage,
  onProjectChange,
  onRefresh,
}: {
  project: ProjectDto
  canManage: boolean
  onProjectChange(project: ProjectDto): void
  onRefresh(): Promise<ProjectDto | null>
}) {
  return (
    <div className="page-stack project-management-page">
      <ProjectMembers project={project} canManage={canManage} onProjectChange={onProjectChange} />
      <ProjectModules
        project={project}
        canManage={canManage}
        onProjectChange={onProjectChange}
        onRefresh={onRefresh}
      />
    </div>
  )
}
