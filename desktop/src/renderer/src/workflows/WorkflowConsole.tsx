import { useCallback, useEffect, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"

// V3 T-W6 工作流控制台（workflow-dag-v1 §5 消费面）：定义列表 + run 列表/详情树
// + 取消/恢复按钮。页面仅呈现；写操作走既有 require_auth + 服务层闸（cancel 幂等、
// resume failed-only），服务端 403/409 原样呈现不吞。

interface WorkflowDefinitionDto {
  id: string
  name: string
  description: string | null
  status: string
  version: number
  published_at: string | null
  dag_json: { nodes?: unknown[] } | null
}

interface WorkflowRunDto {
  id: string
  definition_id: string
  definition_version: number
  status: string
  error: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  nodes?: WorkflowNodeDto[]
}

interface WorkflowNodeDto {
  node_key: string
  node_type: string
  status: string
  attempt: number
  error: string | null
}

interface RunListDto {
  items: WorkflowRunDto[]
  truncated: boolean
}

const DEFINITION_STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  published: "已发布",
  archived: "已归档",
}

const RUN_STATUS_LABEL: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  waiting_approval: "等待审批",
  paused: "已暂停",
  succeeded: "成功",
  failed: "失败",
  cancelled: "已取消",
}

const NODE_STATUS_LABEL: Record<string, string> = {
  pending: "待执行",
  ready: "就绪",
  running: "运行中",
  waiting: "等待审批",
  succeeded: "成功",
  failed: "失败",
  skipped: "已跳过",
  cancelled: "已取消",
}

const TERMINAL_RUN_STATUSES = new Set(["succeeded", "failed", "cancelled"])

function statusLabel(map: Record<string, string>, value: string): string {
  return map[value] ?? value
}

function shortId(value: string): string {
  return value.length > 8 ? value.slice(0, 8) : value
}

function nodeCount(dag: WorkflowDefinitionDto["dag_json"]): string {
  if (dag && typeof dag === "object" && Array.isArray(dag.nodes)) return `${dag.nodes.length} 个节点`
  return "节点数未知"
}

function actionMessage(caught: unknown): string {
  if (caught instanceof ApiClientError) return caught.message
  if (caught instanceof Error) return caught.message
  return "操作失败，请重试。"
}

interface WorkflowConsoleProps {
  projectId: string
  canManage: boolean
}

export function WorkflowConsole({ projectId, canManage }: WorkflowConsoleProps) {
  const { apiRequest } = useAuth()
  const [definitions, setDefinitions] = useState<WorkflowDefinitionDto[]>([])
  const [runs, setRuns] = useState<WorkflowRunDto[]>([])
  const [truncated, setTruncated] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [actionError, setActionError] = useState("")
  const [busy, setBusy] = useState(false)
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const load = useCallback(async (): Promise<void> => {
    setError("")
    try {
      const [definitionData, runData] = await Promise.all([
        apiRequest<{ items: WorkflowDefinitionDto[] }>(
          `/api/v1/projects/${encodeURIComponent(projectId)}/workflows`,
          { method: "GET" },
        ),
        apiRequest<RunListDto>(
          `/api/v1/projects/${encodeURIComponent(projectId)}/workflow-runs`,
          { method: "GET" },
        ),
      ])
      setDefinitions(definitionData.items)
      setRuns(runData.items)
      setTruncated(runData.truncated)
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

  async function toggleRunDetail(run: WorkflowRunDto): Promise<void> {
    if (expandedRunId === run.id) {
      setExpandedRunId(null)
      return
    }
    setActionError("")
    setExpandedRunId(run.id)
    if (Array.isArray(run.nodes)) return // cancel/resume 返回体自带节点树，免重复取
    setDetailLoading(true)
    try {
      const data = await apiRequest<{ run: WorkflowRunDto }>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/workflow-runs/${encodeURIComponent(run.id)}`,
        { method: "GET" },
      )
      setRuns((current) => current.map((row) => (row.id === run.id ? data.run : row)))
    } catch (caught) {
      setActionError(actionMessage(caught))
      setExpandedRunId(null)
    } finally {
      setDetailLoading(false)
    }
  }

  async function act(run: WorkflowRunDto, action: "cancel" | "resume"): Promise<void> {
    setActionError("")
    setBusy(true)
    try {
      const data = await apiRequest<{ run: WorkflowRunDto; cancelled?: boolean; reset_nodes?: number }>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/workflow-runs/${encodeURIComponent(run.id)}/${action}`,
        { method: "POST", body: {} },
      )
      setRuns((current) => current.map((row) => (row.id === run.id ? data.run : row)))
    } catch (caught) {
      setActionError(actionMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <p className="empty-copy" role="status">正在加载工作流…</p>
  if (error) return <p className="empty-copy" role="alert">{error}</p>

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>工作流定义</h2>
            <p>项目内流程定义（草稿与已发布）；发布走管理通道，控制台只读呈现。</p>
          </div>
        </div>
        {definitions.length ? (
          <div className="extension-card-grid">
            {definitions.map((definition) => (
              <article key={definition.id} className="extension-item">
                <div>
                  <span className={`extension-scope ${definition.status === "published" ? "public" : ""}`}>
                    {statusLabel(DEFINITION_STATUS_LABEL, definition.status)}
                  </span>
                  <strong>{definition.name}</strong>
                  {definition.version > 0 ? <small> v{definition.version}</small> : null}
                </div>
                <p>{definition.description || "暂无说明"}</p>
                <small>{nodeCount(definition.dag_json)}{definition.published_at ? ` · 发布于 ${definition.published_at.slice(0, 10)}` : ""}</small>
              </article>
            ))}
          </div>
        ) : (
          <p className="empty-copy">还没有工作流定义。</p>
        )}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>运行记录</h2>
            <p>取消幂等（终态拒绝）；恢复仅限失败运行，失败/跳过节点放回重跑。</p>
          </div>
        </div>
        {actionError ? <p role="alert" className="empty-copy">{actionError}</p> : null}
        {runs.length ? (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">运行</th>
                <th scope="col">状态</th>
                <th scope="col">定义</th>
                <th scope="col">开始时间</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td>
                    <code>{shortId(run.id)}</code>
                    {run.error ? <div><small>{run.error}</small></div> : null}
                  </td>
                  <td>{statusLabel(RUN_STATUS_LABEL, run.status)}</td>
                  <td><code>{shortId(run.definition_id)}</code> v{run.definition_version}</td>
                  <td>{run.started_at ? run.started_at.slice(0, 19).replace("T", " ") : "—"}</td>
                  <td>
                    <div className="plugin-actions">
                      <button
                        className="secondary-button"
                        disabled={busy || (detailLoading && expandedRunId === run.id)}
                        onClick={() => void toggleRunDetail(run)}
                      >
                        {expandedRunId === run.id ? "收起" : "详情"}
                      </button>
                      {canManage && !TERMINAL_RUN_STATUSES.has(run.status) ? (
                        <button className="secondary-button" disabled={busy} onClick={() => void act(run, "cancel")}>
                          取消
                        </button>
                      ) : null}
                      {canManage && run.status === "failed" ? (
                        <button className="secondary-button" disabled={busy} onClick={() => void act(run, "resume")}>
                          恢复
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="empty-copy">还没有运行记录。</p>
        )}
        {truncated ? (
          <p className="empty-copy">已显示最近的运行，更早的记录未列出。</p>
        ) : null}
        {expandedRunId && expandedRunId === runs.find((row) => row.id === expandedRunId)?.id ? (
          <RunNodes run={runs.find((row) => row.id === expandedRunId)!} loading={detailLoading} />
        ) : null}
      </section>
    </div>
  )
}

function RunNodes({ run, loading }: { run: WorkflowRunDto; loading: boolean }) {
  if (!Array.isArray(run.nodes) || !run.nodes.length) {
    return <p className="empty-copy">{loading ? "正在加载节点…" : "该运行暂无节点记录。"}</p>
  }
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th scope="col">节点</th>
          <th scope="col">类型</th>
          <th scope="col">状态</th>
          <th scope="col">尝试</th>
          <th scope="col">错误</th>
        </tr>
      </thead>
      <tbody>
        {run.nodes.map((node) => (
          <tr key={node.node_key}>
            <td><code>{node.node_key}</code></td>
            <td>{node.node_type}</td>
            <td>{statusLabel(NODE_STATUS_LABEL, node.status)}</td>
            <td>{node.attempt}</td>
            <td>{node.error ? <small>{node.error}</small> : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
