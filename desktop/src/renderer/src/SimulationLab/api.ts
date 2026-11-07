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
