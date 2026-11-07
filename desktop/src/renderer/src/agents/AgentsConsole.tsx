import { useCallback, useEffect, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"

// T-A8 智能体控制台（台账「售前主线登记」节）：run 列表 → 详情 → 工具调用 →
// 项目成本汇总。页面仅呈现（拍板 6⑥：与 B#9 执行事实面板界面分离——本页是
// 智能体运行态，证据/审计事实链在「执行事实」tab）；写操作（handoff/retry）
// 不在本页，服务端 403/409 原样呈现不吞。

interface AgentRunRowDto {
  id: string
  project_id: string
  agent_id: string
  status: string
  capability_used: string
  initiated_by_user_id: string
  token_cost: number
  duration_ms: number
  degraded: boolean
  degraded_reason: string | null
  fallback_level: string | null
  created_at: string | null
  updated_at: string | null
}

interface AgentRunDetailDto extends AgentRunRowDto {
  agent: { name: string; kind: string } | null
  artifacts: Array<{
    id: string
    kind: string
    storage_ref: string
    sha256: string
    reviewed: boolean
    linked_solution_id: string | null
  }> | null
}

interface AgentToolCallDto {
  id: string
  tool_name: string
  decision: string
  capability: string
  reason: string | null
  duration_ms: number
}

interface RunListDto {
  items: AgentRunRowDto[]
  truncated: boolean
}

interface ToolCallListDto {
  items: AgentToolCallDto[]
  denied_count: number
}

interface ProjectCostDto {
  scope: string
  project_id: string
  total_token_cost: number
  monthly: Record<string, number>
}

const RUN_STATUS_LABEL: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  succeeded_but_receipt_invalid: "成功但回执无效",
  failed: "失败",
  timeout: "超时",
  budget_exceeded: "预算超限",
}

const DECISION_LABEL: Record<string, string> = {
  allowed: "放行",
  denied: "拦截",
}

function statusLabel(map: Record<string, string>, value: string): string {
  return map[value] ?? value
}

function shortId(value: string): string {
  return value.length > 8 ? value.slice(0, 8) : value
}

function actionMessage(caught: unknown): string {
  if (caught instanceof ApiClientError) return caught.message
  if (caught instanceof Error) return caught.message
  return "操作失败，请重试。"
}

function formatDuration(ms: number): string {
  if (!ms) return "—"
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

interface AgentsConsoleProps {
  projectId: string
}

export function AgentsConsole({ projectId }: AgentsConsoleProps) {
  const { apiRequest } = useAuth()
  const [runs, setRuns] = useState<AgentRunRowDto[]>([])
  const [truncated, setTruncated] = useState(false)
  const [cost, setCost] = useState<ProjectCostDto | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [detailError, setDetailError] = useState("")
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)
  const [detail, setDetail] = useState<AgentRunDetailDto | null>(null)
  const [toolCalls, setToolCalls] = useState<AgentToolCallDto[] | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const load = useCallback(async (): Promise<void> => {
    setError("")
    try {
      const [runData, costData] = await Promise.all([
        apiRequest<RunListDto>(
          `/api/v1/agents/runs?project_id=${encodeURIComponent(projectId)}`,
          { method: "GET" },
        ),
        apiRequest<ProjectCostDto>(
          `/api/v1/agents/cost?scope=project&project_id=${encodeURIComponent(projectId)}`,
          { method: "GET" },
        ),
      ])
      setRuns(runData.items)
      setTruncated(runData.truncated)
      setCost(costData)
    } catch (caught) {
      setError(actionMessage(caught))
    }
  }, [apiRequest, projectId])

  useEffect(() => {
    let active = true
    setLoading(true)
    void load().finally(() => {
      if (active) setLoading(false)
    })
    return () => {
      active = false
    }
  }, [load])

  async function toggleRunDetail(run: AgentRunRowDto): Promise<void> {
    if (expandedRunId === run.id) {
      setExpandedRunId(null)
      setDetail(null)
      setToolCalls(null)
      return
    }
    setDetailError("")
    setExpandedRunId(run.id)
    setDetail(null)
    setToolCalls(null)
    setDetailLoading(true)
    try {
      const [runDetail, calls] = await Promise.all([
        apiRequest<AgentRunDetailDto>(
          `/api/v1/agents/runs/${encodeURIComponent(run.id)}`,
          { method: "GET" },
        ),
        apiRequest<ToolCallListDto>(
          `/api/v1/agents/runs/${encodeURIComponent(run.id)}/tool-calls`,
          { method: "GET" },
        ),
      ])
      setDetail(runDetail)
      setToolCalls(calls.items)
    } catch (caught) {
      setDetailError(actionMessage(caught))
      setExpandedRunId(null)
    } finally {
      setDetailLoading(false)
    }
  }

  if (loading) return <p className="empty-copy" role="status">正在加载智能体运行…</p>
  if (error) return <p className="empty-copy" role="alert">{error}</p>

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>智能体运行</h2>
            <p>本项目的智能体 run 列表（运行态）；产物/工具调用/成本在详情按需展开。</p>
          </div>
          {cost ? (
            <div>
              <strong>{cost.total_token_cost}</strong>
              <small> token 累计 · 近月 {Object.entries(cost.monthly).map(([month, value]) => `${month}=${value}`).join(" / ") || "—"}</small>
            </div>
          ) : null}
        </div>
        {runs.length ? (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">运行</th>
                <th scope="col">状态</th>
                <th scope="col">能力</th>
                <th scope="col">降级</th>
                <th scope="col">成本 (token)</th>
                <th scope="col">耗时</th>
                <th scope="col">发起时间</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td><code>{shortId(run.id)}</code></td>
                  <td>{statusLabel(RUN_STATUS_LABEL, run.status)}</td>
                  <td><code>{run.capability_used}</code></td>
                  <td>{run.degraded ? <span title={run.degraded_reason ?? ""}>{run.fallback_level ?? "降级"}</span> : "—"}</td>
                  <td>{run.token_cost}</td>
                  <td>{formatDuration(run.duration_ms)}</td>
                  <td>{run.created_at ? run.created_at.slice(0, 19).replace("T", " ") : "—"}</td>
                  <td>
                    <button
                      className="secondary-button"
                      disabled={detailLoading && expandedRunId === run.id}
                      onClick={() => void toggleRunDetail(run)}
                    >
                      {expandedRunId === run.id ? "收起" : "详情"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="empty-copy">本项目还没有智能体运行记录。</p>
        )}
        {truncated ? <p className="empty-copy">已显示最近的运行，更早的记录未列出。</p> : null}
      </section>

      {expandedRunId ? (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>运行详情</h2>
              <p>
                {detail?.agent ? `${detail.agent.name}（${detail.agent.kind}）` : <code>{shortId(expandedRunId)}</code>}
                {detail?.fallback_level ? ` · 降级链 ${detail.fallback_level}` : ""}
                {detail?.degraded_reason ? ` · ${detail.degraded_reason}` : ""}
              </p>
            </div>
          </div>
          {detailError ? <p role="alert" className="empty-copy">{detailError}</p> : null}
          {detailLoading ? <p className="empty-copy" role="status">正在加载详情…</p> : null}
          {detail && !detailLoading ? (
            <div className="page-stack">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">产物</th>
                    <th scope="col">类型</th>
                    <th scope="col">指纹 (sha256)</th>
                    <th scope="col">复核</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.artifacts?.length ? (
                    detail.artifacts.map((artifact) => (
                      <tr key={artifact.id}>
                        <td><code>{artifact.storage_ref}</code></td>
                        <td>{artifact.kind}</td>
                        <td><code>{artifact.sha256.slice(0, 12)}…</code></td>
                        <td>{artifact.reviewed ? "已复核" : "未复核"}</td>
                      </tr>
                    ))
                  ) : (
                    <tr><td colSpan={4}>该运行暂无产物。</td></tr>
                  )}
                </tbody>
              </table>
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">工具</th>
                    <th scope="col">判定</th>
                    <th scope="col">能力</th>
                    <th scope="col">原因</th>
                    <th scope="col">耗时</th>
                  </tr>
                </thead>
                <tbody>
                  {toolCalls && toolCalls.length ? (
                    toolCalls.map((call) => (
                      <tr key={call.id}>
                        <td><code>{call.tool_name}</code></td>
                        <td>{statusLabel(DECISION_LABEL, call.decision)}</td>
                        <td><code>{call.capability}</code></td>
                        <td>{call.reason ? <small>{call.reason}</small> : "—"}</td>
                        <td>{formatDuration(call.duration_ms)}</td>
                      </tr>
                    ))
                  ) : (
                    <tr><td colSpan={5}>该运行暂无工具调用记录。</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  )
}
