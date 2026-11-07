// V3.2 G2 模拟训练场 · 桌面 API 客户端。
//
// 只调既有 `apiRequest` 通道（`auth/AuthProvider`），不新建传输层。
// 读面契约校验在 types.ts；本层只负责路径与查询参数。

import type { ApiMethod } from "../../../shared/contracts"
import type {
  ScenarioDto,
  ScenarioExportDto,
  ScenarioImportResultDto,
  ScenarioListDto,
} from "./types"
import { isScenarioDto, isScenarioListDto } from "./types"

export interface SimulationApiRequest {
  <T>(path: string, options: { method: ApiMethod; body?: unknown }): Promise<T>
}

export interface ScenarioListQuery {
  split?: string
  industry?: string
  variant?: string
  status?: string
  q?: string
  includeHistory?: boolean
  limit?: number
}

function buildQuery(query: ScenarioListQuery): string {
  const parts: string[] = []
  if (query.split) parts.push(`split=${encodeURIComponent(query.split)}`)
  if (query.industry) parts.push(`industry=${encodeURIComponent(query.industry)}`)
  if (query.variant) parts.push(`variant=${encodeURIComponent(query.variant)}`)
  if (query.status) parts.push(`status=${encodeURIComponent(query.status)}`)
  if (query.q) parts.push(`q=${encodeURIComponent(query.q)}`)
  if (query.includeHistory) parts.push("include_history=true")
  if (query.limit) parts.push(`limit=${encodeURIComponent(String(query.limit))}`)
  return parts.length ? `?${parts.join("&")}` : ""
}

const BASE = "/api/v1/simulation"

export async function listScenarios(
  apiRequest: SimulationApiRequest,
  query: ScenarioListQuery = {},
): Promise<ScenarioListDto> {
  const payload = await apiRequest(`${BASE}/scenarios${buildQuery(query)}`, { method: "GET" })
  if (!isScenarioListDto(payload)) throw new Error("模拟场景列表数据格式异常")
  return payload
}

export async function getScenario(
  apiRequest: SimulationApiRequest,
  scenarioId: string,
): Promise<ScenarioDto> {
  const payload = await apiRequest(`${BASE}/scenarios/${encodeURIComponent(scenarioId)}`, {
    method: "GET",
  })
  if (!isScenarioDto(payload)) throw new Error("模拟场景数据格式异常")
  return payload
}

export interface ScenarioWritePayload {
  scenario_key?: string
  name?: string
  industry?: string
  variant?: string
  split?: string
  difficulty?: string
  status?: string
  tags?: string[]
  content?: unknown
  reference?: unknown
  note?: string
}

export async function createScenario(
  apiRequest: SimulationApiRequest,
  payload: ScenarioWritePayload,
): Promise<ScenarioDto> {
  const data = await apiRequest(`${BASE}/scenarios`, { method: "POST", body: payload })
  if (!isScenarioDto(data)) throw new Error("模拟场景数据格式异常")
  return data
}

export async function updateScenario(
  apiRequest: SimulationApiRequest,
  scenarioId: string,
  payload: ScenarioWritePayload,
): Promise<ScenarioDto> {
  const data = await apiRequest(`${BASE}/scenarios/${encodeURIComponent(scenarioId)}`, {
    method: "PATCH",
    body: payload,
  })
  if (!isScenarioDto(data)) throw new Error("模拟场景数据格式异常")
  return data
}

export async function duplicateScenario(
  apiRequest: SimulationApiRequest,
  scenarioId: string,
  scenarioKey: string,
): Promise<ScenarioDto> {
  const data = await apiRequest(
    `${BASE}/scenarios/${encodeURIComponent(scenarioId)}/duplicate`,
    { method: "POST", body: { scenario_key: scenarioKey } },
  )
  if (!isScenarioDto(data)) throw new Error("模拟场景数据格式异常")
  return data
}

export async function archiveScenario(
  apiRequest: SimulationApiRequest,
  scenarioId: string,
): Promise<ScenarioDto> {
  const data = await apiRequest(`${BASE}/scenarios/${encodeURIComponent(scenarioId)}/archive`, {
    method: "POST",
  })
  if (!isScenarioDto(data)) throw new Error("模拟场景数据格式异常")
  return data
}

export async function importScenarios(
  apiRequest: SimulationApiRequest,
  scenarios: unknown[],
): Promise<ScenarioImportResultDto> {
  const data = await apiRequest(`${BASE}/scenarios/import`, {
    method: "POST",
    body: { scenarios },
  })
  if (!data || typeof data !== "object") throw new Error("模拟场景导入结果格式异常")
  return data as ScenarioImportResultDto
}

export async function exportScenarios(
  apiRequest: SimulationApiRequest,
  query: { split?: string; variant?: string } = {},
): Promise<ScenarioExportDto> {
  const parts: string[] = []
  if (query.split) parts.push(`split=${encodeURIComponent(query.split)}`)
  if (query.variant) parts.push(`variant=${encodeURIComponent(query.variant)}`)
  const suffix = parts.length ? `?${parts.join("&")}` : ""
  const data = await apiRequest(`${BASE}/scenarios/export${suffix}`, { method: "GET" })
  if (!data || typeof data !== "object") throw new Error("模拟场景导出结果格式异常")
  return data as ScenarioExportDto
}

// ---------------------------------------------------------------------------
// 运行 / 评估 / 失败 / 提案 / 回归（G3–G6）
// ---------------------------------------------------------------------------

export async function listSimulationRuns(
  apiRequest: SimulationApiRequest,
  query: { scenarioId?: string; status?: string; split?: string } = {},
): Promise<import("./types").SimulationRunListDto> {
  const parts: string[] = []
  if (query.scenarioId) parts.push(`scenario_id=${encodeURIComponent(query.scenarioId)}`)
  if (query.status) parts.push(`status=${encodeURIComponent(query.status)}`)
  if (query.split) parts.push(`split=${encodeURIComponent(query.split)}`)
  const suffix = parts.length ? `?${parts.join("&")}` : ""
  const data = await apiRequest(`${BASE}/runs${suffix}`, { method: "GET" })
  if (!data || typeof data !== "object") throw new Error("模拟运行列表数据格式异常")
  return data as import("./types").SimulationRunListDto
}

export async function createSimulationRun(
  apiRequest: SimulationApiRequest,
  payload: {
    scenario_id: string
    adapter_mode?: string
    execute?: boolean
    config?: Record<string, unknown>
    seed?: number
  },
): Promise<import("./types").SimulationRunDto> {
  const data = await apiRequest(`${BASE}/runs`, { method: "POST", body: payload })
  if (!data || typeof data !== "object") throw new Error("模拟运行数据格式异常")
  return data as import("./types").SimulationRunDto
}

export async function cancelSimulationRun(
  apiRequest: SimulationApiRequest,
  runId: string,
): Promise<import("./types").SimulationRunDto> {
  const data = await apiRequest(`${BASE}/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
  })
  if (!data || typeof data !== "object") throw new Error("模拟运行数据格式异常")
  return data as import("./types").SimulationRunDto
}

export async function listRunTraces(
  apiRequest: SimulationApiRequest,
  runId: string,
  query: { phase?: string; afterSeq?: number } = {},
): Promise<import("./types").TraceListDto> {
  const parts: string[] = []
  if (query.phase) parts.push(`phase=${encodeURIComponent(query.phase)}`)
  if (query.afterSeq !== undefined) parts.push(`after_seq=${encodeURIComponent(String(query.afterSeq))}`)
  const suffix = parts.length ? `?${parts.join("&")}` : ""
  const data = await apiRequest(`${BASE}/runs/${encodeURIComponent(runId)}/trace${suffix}`, {
    method: "GET",
  })
  if (!data || typeof data !== "object") throw new Error("模拟 Trace 数据格式异常")
  return data as import("./types").TraceListDto
}

export async function evaluateRun(
  apiRequest: SimulationApiRequest,
  runId: string,
): Promise<import("./types").EvaluationReportDto> {
  const data = await apiRequest(`${BASE}/runs/${encodeURIComponent(runId)}/evaluate`, {
    method: "POST",
  })
  if (!data || typeof data !== "object") throw new Error("评估结果数据格式异常")
  return data as import("./types").EvaluationReportDto
}

export async function getEvaluationReport(
  apiRequest: SimulationApiRequest,
  runId: string,
): Promise<import("./types").EvaluationReportDto> {
  const data = await apiRequest(`${BASE}/runs/${encodeURIComponent(runId)}/evaluation`, {
    method: "GET",
  })
  if (!data || typeof data !== "object") throw new Error("评估报告数据格式异常")
  return data as import("./types").EvaluationReportDto
}

export async function listFindings(
  apiRequest: SimulationApiRequest,
  runId?: string,
): Promise<{ items: import("./types").FindingDto[]; total: number }> {
  const suffix = runId ? `?run_id=${encodeURIComponent(runId)}` : ""
  const data = await apiRequest(`${BASE}/findings${suffix}`, { method: "GET" })
  if (!data || typeof data !== "object") throw new Error("失败发现数据格式异常")
  return data as { items: import("./types").FindingDto[]; total: number }
}

export async function analyzeRun(
  apiRequest: SimulationApiRequest,
  runId: string,
): Promise<{ run_id: string; created: number; items: import("./types").FindingDto[] }> {
  const data = await apiRequest(`${BASE}/runs/${encodeURIComponent(runId)}/analyze`, {
    method: "POST",
  })
  if (!data || typeof data !== "object") throw new Error("失败分析数据格式异常")
  return data as { run_id: string; created: number; items: import("./types").FindingDto[] }
}

export async function listProposals(
  apiRequest: SimulationApiRequest,
  query: { status?: string } = {},
): Promise<{ items: import("./types").ProposalDto[]; total: number }> {
  const suffix = query.status ? `?status=${encodeURIComponent(query.status)}` : ""
  const data = await apiRequest(`${BASE}/proposals${suffix}`, { method: "GET" })
  if (!data || typeof data !== "object") throw new Error("改进提案数据格式异常")
  return data as { items: import("./types").ProposalDto[]; total: number }
}

export async function createProposal(
  apiRequest: SimulationApiRequest,
  payload: {
    finding_ids: string[]
    target: { kind: string; ref: string }
    change_summary: string
    current_version?: string
    proposed_version?: string
    override_json?: Record<string, unknown>
  },
): Promise<import("./types").ProposalDto> {
  const data = await apiRequest(`${BASE}/proposals`, { method: "POST", body: payload })
  if (!data || typeof data !== "object") throw new Error("改进提案数据格式异常")
  return data as import("./types").ProposalDto
}

export async function decideProposal(
  apiRequest: SimulationApiRequest,
  proposalId: string,
  payload: { approve: boolean; password: string; note: string },
): Promise<import("./types").ProposalDto> {
  const data = await apiRequest(`${BASE}/proposals/${encodeURIComponent(proposalId)}/decide`, {
    method: "POST",
    body: payload,
  })
  if (!data || typeof data !== "object") throw new Error("改进提案数据格式异常")
  return data as import("./types").ProposalDto
}

export async function listRegressionSuites(
  apiRequest: SimulationApiRequest,
): Promise<{ items: import("./types").RegressionSuiteDto[]; total: number }> {
  const data = await apiRequest(`${BASE}/regression/suites`, { method: "GET" })
  if (!data || typeof data !== "object") throw new Error("回归套件数据格式异常")
  return data as { items: import("./types").RegressionSuiteDto[]; total: number }
}

export async function createRegressionSuite(
  apiRequest: SimulationApiRequest,
  payload: { name: string; split?: string; scenario_ids?: string[]; baseline_config?: Record<string, unknown> },
): Promise<import("./types").RegressionSuiteDto> {
  const data = await apiRequest(`${BASE}/regression/suites`, { method: "POST", body: payload })
  if (!data || typeof data !== "object") throw new Error("回归套件数据格式异常")
  return data as import("./types").RegressionSuiteDto
}

export async function runRegression(
  apiRequest: SimulationApiRequest,
  suiteId: string,
  proposalId?: string,
): Promise<import("./types").RegressionResultDto> {
  const data = await apiRequest(
    `${BASE}/regression/suites/${encodeURIComponent(suiteId)}/run`,
    { method: "POST", body: proposalId ? { proposal_id: proposalId } : {} },
  )
  if (!data || typeof data !== "object") throw new Error("回归结果数据格式异常")
  return data as import("./types").RegressionResultDto
}

export async function listRegressionResults(
  apiRequest: SimulationApiRequest,
  suiteId?: string,
): Promise<{ items: import("./types").RegressionResultDto[]; total: number }> {
  const suffix = suiteId ? `?suite_id=${encodeURIComponent(suiteId)}` : ""
  const data = await apiRequest(`${BASE}/regression/results${suffix}`, { method: "GET" })
  if (!data || typeof data !== "object") throw new Error("回归结果数据格式异常")
  return data as { items: import("./types").RegressionResultDto[]; total: number }
}
