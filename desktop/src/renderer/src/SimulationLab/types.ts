// V3.2 G2 模拟训练场 · 桌面契约类型。
//
// 与服务端 `fde_api.simulation.schemas` / `models.py` 同口径；前端只做**读面**
// 契约校验（形状不对即视为数据格式异常），不做业务判定——服务端是唯一权威。

export type ScenarioVariant = "normal" | "vague" | "complex"
export type ScenarioSplit = "train" | "regression" | "blind"
export type ScenarioStatus = "draft" | "active" | "archived"
export type ScenarioDifficulty = "basic" | "standard" | "hard"

export const SCENARIO_VARIANTS: ScenarioVariant[] = ["normal", "vague", "complex"]
export const SCENARIO_SPLITS: ScenarioSplit[] = ["train", "regression", "blind"]
export const SCENARIO_STATUSES: ScenarioStatus[] = ["draft", "active", "archived"]

export const VARIANT_LABEL: Record<ScenarioVariant, string> = {
  normal: "正常客户",
  vague: "模糊客户",
  complex: "复杂客户",
}

export const SPLIT_LABEL: Record<ScenarioSplit, string> = {
  train: "训练集",
  regression: "回归集",
  blind: "盲测集",
}

export const STATUS_LABEL: Record<ScenarioStatus, string> = {
  draft: "草稿",
  active: "启用",
  archived: "已归档",
}

export interface HiddenFactDto {
  fact_id: string
  text: string
  category?: string
  disclosure_stage: string
  probe_keywords?: string[]
  condition?: string
}

export interface ScenarioContentDto {
  case_code?: string
  customer_profile?: {
    company_type?: string
    stakeholders?: string[]
    maturity?: string
    [key: string]: unknown
  }
  visible?: {
    initial_brief?: string[]
    known_systems?: string[]
    constraints?: {
      budget?: string
      timeline?: string
      tech?: string[]
      compliance?: string[]
      extra?: string[]
      [key: string]: unknown
    }
    [key: string]: unknown
  }
  hidden?: { facts?: HiddenFactDto[]; [key: string]: unknown }
  misleading_request?: string
  [key: string]: unknown
}

export interface ScenarioRubricDto {
  must_identify?: string[]
  must_avoid?: string[]
  must_produce?: string[]
}

export interface ScenarioReferenceDto {
  expected_outcomes?: string[]
  acceptance_criteria?: string[]
  rubric?: ScenarioRubricDto
  [key: string]: unknown
}

export interface ScenarioDto {
  id: string
  scenario_key: string
  name: string
  industry: string
  variant: ScenarioVariant
  difficulty: ScenarioDifficulty
  split: ScenarioSplit
  status: ScenarioStatus
  tags: string[]
  version: number
  rubric_version: string
  source_kind: string
  source_ref: string | null
  note: string | null
  created_at: string | null
  updated_at: string | null
  content?: ScenarioContentDto
  reference?: ScenarioReferenceDto | null
}

export interface ScenarioListDto {
  items: ScenarioDto[]
  total: number
  truncated: boolean
}

export interface ScenarioImportResultDto {
  created: ScenarioDto[]
  created_count: number
  failures: Array<{
    index: number
    code: string
    message: string
    detail?: { errors?: string[] }
  }>
}

export interface ScenarioExportDto {
  items: Array<{
    scenario_key: string
    name: string
    industry: string
    variant: ScenarioVariant
    split: ScenarioSplit
    status: ScenarioStatus
    tags: string[]
    rubric_version: string
    content: ScenarioContentDto
    reference?: ScenarioReferenceDto | null
  }>
  total: number
}

/** 服务端返回的字段级契约校验：只认已知形状，不猜、不放宽。 */
export function isScenarioDto(value: unknown): value is ScenarioDto {
  if (!value || typeof value !== "object") return false
  const row = value as Record<string, unknown>
  return (
    typeof row.id === "string" &&
    typeof row.scenario_key === "string" &&
    typeof row.name === "string" &&
    typeof row.industry === "string" &&
    SCENARIO_VARIANTS.includes(row.variant as ScenarioVariant) &&
    SCENARIO_SPLITS.includes(row.split as ScenarioSplit) &&
    SCENARIO_STATUSES.includes(row.status as ScenarioStatus) &&
    Array.isArray(row.tags) &&
    typeof row.version === "number"
  )
}

export function isScenarioListDto(value: unknown): value is ScenarioListDto {
  if (!value || typeof value !== "object") return false
  const payload = value as Record<string, unknown>
  return (
    Array.isArray(payload.items) &&
    payload.items.every(isScenarioDto) &&
    typeof payload.total === "number" &&
    typeof payload.truncated === "boolean"
  )
}
