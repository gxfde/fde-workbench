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

// ---------------------------------------------------------------------------
// 运行 / 评估 / 失败 / 提案 / 回归（G3–G6）
// ---------------------------------------------------------------------------

export type RunStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "completed"
  | "failed"
  | "failed_hard"
  | "timeout"
  | "cancelled"

export type EvaluationVerdict =
  | "pass"
  | "conditional"
  | "fail"
  | "hard_fail"
  | "inconclusive"
  | "unavailable"

export interface SimulationRunDto {
  id: string
  run_key: string
  scenario_id: string
  scenario_version: number
  split: "train" | "regression" | "blind"
  status: RunStatus
  adapter_mode: "real" | "mock"
  seed: number
  attempt: number
  actor_set: Record<string, { actor_id: string; display_name: string }>
  cost: Record<string, number>
  error: { code?: string; tools?: string[] } | null
  created_at: string | null
  started_at: string | null
  finished_at: string | null
}

export interface SimulationRunListDto {
  items: SimulationRunDto[]
  total: number
  truncated: boolean
}

export interface TraceItemDto {
  seq: number
  parent_seq: number | null
  actor_id: string | null
  phase: string
  event_type: string
  payload: Record<string, unknown>
  tool_call: Record<string, unknown> | null
  evidence: Record<string, unknown> | null
  cost: Record<string, number> | null
  created_at: string | null
}

export interface TraceListDto {
  items: TraceItemDto[]
  total: number
  truncated: boolean
  next_seq: number | null
}

export interface EvaluationLayerDto {
  id: string
  run_id: string
  layer: "deterministic" | "model" | "human"
  evaluator_id: string
  mode: string
  rubric_version: string
  total_score: number
  verdict: EvaluationVerdict
  unverified_ratio: number
  scores: {
    criteria?: Array<{
      key: string
      dimension: string
      title: string
      score: number
      verified: boolean
      evidence_refs?: Array<Record<string, unknown>>
    }>
    dimension_scores?: Record<string, number>
    dimensions?: Array<{ key: string; name: string; weight: number }>
  }
  hard_failures: Array<{ code: string; title: string; evidence_refs?: unknown[] }>
  note: string | null
  created_at: string | null
}

export interface EvaluationReportDto {
  run_id: string
  layers: EvaluationLayerDto[]
  deterministic: EvaluationLayerDto | null
  model: EvaluationLayerDto | null
  human: EvaluationLayerDto[]
  final: EvaluationLayerDto | null
  disagreement: number
  human_review_required: boolean
  meta: { rubric_version: string; adapter_mode: string; disclaimer: string }
}

export interface FindingDto {
  id: string
  run_id: string
  code: string
  title: string
  severity: "high" | "medium" | "low"
  dimension: string
  description: string
  evidence_refs: Array<Record<string, unknown>>
  root_causes: Array<{ code: string; confidence: string; analysis: string }>
  status: string
}

export interface ProposalDto {
  id: string
  proposal_key: string
  title: string
  problem: string
  finding_ids: string[]
  finding_codes: string[]
  target: { kind: string; ref: string }
  current_version: string
  proposed_version: string
  change_summary: string
  expected_effect: Record<string, unknown>
  impact_scope: string[]
  regression_plan: Record<string, unknown>
  override_json: Record<string, unknown>
  status: "draft" | "in_review" | "approved" | "rejected"
  decided_by_user_id: string | null
  decided_at: string | null
  note: string | null
  created_at: string | null
}

export interface RegressionSuiteDto {
  id: string
  name: string
  split: "train" | "regression" | "blind" | "mixed"
  scenario_ids: string[]
  baseline_config: Record<string, unknown>
  note: string | null
  created_at: string | null
}

export interface RegressionResultDto {
  id: string
  suite_id: string
  proposal_id: string | null
  before: { runs: number; mean_total: number; hard_failures?: string[] }
  after: { runs: number; mean_total: number; hard_failures?: string[] }
  deltas: {
    total_delta?: number
    dimension_deltas?: Record<string, number>
    regressed_dimensions?: string[]
    new_failure_codes?: string[]
    cost_delta?: Record<string, number>
    train_gain?: number
    blind_gain?: number
  }
  new_hard_failures: string[]
  resolved_hard_failures: string[]
  generalization_gap: number
  overfit_risk: boolean
  verdict: "improved" | "regressed" | "mixed" | "no_change" | "inconclusive"
  note: string | null
  created_at: string | null
}

export const RUN_STATUS_LABEL: Record<RunStatus, string> = {
  queued: "排队中",
  running: "执行中",
  awaiting_approval: "待人工确认",
  completed: "已完成",
  failed: "失败",
  failed_hard: "硬性失败",
  timeout: "超时",
  cancelled: "已取消",
}

export const VERDICT_LABEL: Record<EvaluationVerdict, string> = {
  pass: "通过",
  conditional: "有条件通过",
  fail: "未通过",
  hard_fail: "硬性失败",
  inconclusive: "结论不可靠",
  unavailable: "未评估",
}

export const LAYER_LABEL: Record<"deterministic" | "model" | "human", string> = {
  deterministic: "规则层",
  model: "模型层",
  human: "人工层",
}
