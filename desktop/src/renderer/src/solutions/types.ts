import type { BusinessCategory } from '../businessCategory'

export interface SolutionFields {
  name: string
  opportunity_ids: string[]
  design_markdown: string
  deliverables: string
  acceptance_criteria: string
  data_systems: string
  schedule: string
  risks_dependencies: string
  business_category: BusinessCategory | null
}

export interface SolutionDto extends SolutionFields {
  id: string
  project_id: string
  version: number
  status: 'active' | 'archived'
  opportunities: Array<{ id: string; name: string; tracking_code?: string | null; parent_id?: string | null }>
  updated_at: string
  source?: { kind?: string; reviewed?: boolean } | null
}

export const SOLUTION_DETAIL_FIELDS = [
  { key: 'deliverables', label: '交付物', placeholder: '交付的系统、模块、文件和培训等' },
  { key: 'acceptance_criteria', label: '预期指标/验收标准', placeholder: '每项交付物如何验证，通过标准是什么' },
  { key: 'data_systems', label: '所需数据/系统', placeholder: '使用的数据、需对接的系统及授权要求' },
  { key: 'schedule', label: '计划排期', placeholder: '实施阶段、里程碑与责任分工' },
  { key: 'risks_dependencies', label: '风险与依赖', placeholder: '前置条件、责任边界、排除项和待确认事项' },
] as const

export function emptySolution(): SolutionFields {
  return { name: '', opportunity_ids: [], design_markdown: '', deliverables: '', acceptance_criteria: '', data_systems: '', schedule: '', risks_dependencies: '', business_category: null }
}

export function solutionFields(solution: SolutionDto): SolutionFields {
  return Object.fromEntries(Object.keys(emptySolution()).map(key => [key, solution[key as keyof SolutionFields]])) as unknown as SolutionFields
}

export function isSolution(value: unknown): value is SolutionDto {
  if (!value || typeof value !== 'object') return false
  const item = value as Record<string, unknown>
  return typeof item.id === 'string' && typeof item.name === 'string'
    && typeof item.version === 'number' && item.version >= 1
    && ['active', 'archived'].includes(String(item.status))
    && Array.isArray(item.opportunity_ids) && item.opportunity_ids.every(id => typeof id === 'string')
    && Array.isArray(item.opportunities) && item.opportunities.every(opportunity => opportunity && typeof opportunity.id === 'string' && typeof opportunity.name === 'string')
    && ['design_markdown', 'deliverables', 'acceptance_criteria', 'data_systems', 'schedule', 'risks_dependencies'].every(key => typeof item[key] === 'string')
}
