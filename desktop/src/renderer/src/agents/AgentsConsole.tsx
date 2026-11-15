import { Fragment, useCallback, useEffect, useState } from "react"

import { MemoMarkdown } from "../research/MemoMarkdown"
import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { allowNextHashNavigation } from "../routing/navigationGuard"

// T-A8 智能体控制台（台账「售前主线登记」节）：run 列表 → 详情 → 工具调用 →
// 项目成本汇总。页面仅呈现（拍板 6⑥：与 B#9 执行事实面板界面分离——本页是
// 智能体运行态，证据/审计事实链在「执行事实」tab）；写操作（handoff/retry）
// 不在本页，服务端 403/409 原样呈现不吞。
// N3c（2026-11-12 拍板）：G-15 跨 run 编排面＝run 列表多选 ＋ 未复核产物
// 「终审队列」＋批量标记复核——批量＝逐件调用既有单件 PATCH（写语义零新增，
// 终审不可绕过天然成立；零服务端新写路径）；T-A10 产物就地 [预览][下载]——
// content 路由逐字节 sha256 自证，宿主裸跑态全量可用、容器态显式 404
// （错误原样呈现不静默）。

interface AgentArtifactDto {
  id: string
  kind: string
  storage_ref: string
  sha256: string
  reviewed: boolean
  linked_solution_id: string | null
  reviewed_by_user_id?: string | null
  reviewed_at?: string | null
  derived_summary?: Record<string, number> | null
}

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
  artifacts: AgentArtifactDto[] | null
  // 宿主通道溯源面（PR #435 起 detail 面透出；列表面不透出）。
  execution_provider?: string | null
  host_claimed_at?: string | null
  host_receipt_at?: string | null
}

interface AgentToolCallDto {
  id: string
  tool_name: string
  decision: string
  capability: string
  reason: string | null
  duration_ms: number
}

interface ArtifactContentDto {
  run_id: string
  artifact_id: string
  kind: string
  storage_ref: string
  sha256: string
  size: number
  mime: string
  reviewed: boolean
  content_base64: string
}

interface ArtifactAdoptionResultDto {
  solution_id: string
  run_id: string
  artifact_id: string
  adopted: boolean
  duplicate: boolean
  solution?: { id: string; name?: string } | null
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

// G-15 终审队列行：run × 未复核产物
interface ReviewQueueItem {
  runId: string
  artifact: AgentArtifactDto
}

interface ArtifactPreviewState {
  status: "loading" | "ready" | "error"
  text?: string
  mime?: string
  error?: string
}

const RUN_STATUS_LABEL: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  host_running: "宿主执行中",
  completed: "已完成",
  succeeded_but_receipt_invalid: "成功但回执无效",
  failed: "失败",
  timeout: "超时",
  budget_exceeded: "预算超限",
}

// 采纳闸的成功终态集合（仅 completed / succeeded_but_receipt_invalid 允许采纳为方案；
// queued/running/host_running/failed/timeout/budget_exceeded 一律不可）。
const RUN_ADOPTABLE_STATUSES = new Set([
  "completed",
  "succeeded_but_receipt_invalid",
])

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

function decodeBase64(value: string): Uint8Array {
  const binary = atob(value)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  return bytes
}

function fileNameOf(storageRef: string): string {
  const parts = storageRef.split("/")
  return parts[parts.length - 1] || "artifact"
}

function PreviewBlock({ state, kind }: { state: ArtifactPreviewState; kind: string }) {
  if (state.status === "loading") return <p className="empty-copy" role="status">正在加载产物内容…</p>
  if (state.status === "error") return <p className="empty-copy" role="alert">{state.error}</p>
  if (kind === "doc") return <div className="artifact-preview artifact-preview-doc"><MemoMarkdown>{state.text ?? ""}</MemoMarkdown></div>
  return <pre className="artifact-preview">{state.text ?? ""}</pre>
}

interface AgentsConsoleProps {
  projectId: string
  canManage?: boolean
}

export function AgentsConsole({ projectId, canManage = false }: AgentsConsoleProps) {
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
  const [artifactBusyId, setArtifactBusyId] = useState<string | null>(null)
  const [artifactNotice, setArtifactNotice] = useState("")
  // —— G-15：跨 run 编排面状态 ——
  const [selectedRunIds, setSelectedRunIds] = useState<Set<string>>(new Set())
  const [queue, setQueue] = useState<ReviewQueueItem[]>([])
  const [queueLoading, setQueueLoading] = useState(false)
  const [queueBusy, setQueueBusy] = useState(false)
  const [queueNotice, setQueueNotice] = useState("")
  const [queueError, setQueueError] = useState("")
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set())
  // —— T-A10：预览/下载状态（内容缓存按 artifact id；预览开合单独记录）——
  const [previews, setPreviews] = useState<Record<string, ArtifactPreviewState>>({})
  const [openPreviews, setOpenPreviews] = useState<Set<string>>(new Set())
  const [downloadBusyId, setDownloadBusyId] = useState<string | null>(null)
  // —— 采纳为方案（PR #435 人工采纳入口；canManage + completed/succeeded_but_receipt_invalid + 未采纳才可点）——
  const [adoptBusyId, setAdoptBusyId] = useState<string | null>(null)

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

  // T-B1（goal-tb tb2）：产物人工接受/撤回（can_manage 面；服务端 PATCH 同名动作）。
  // 成功后重拉 run 详情让 reviewed 状态回真（不本地猜写）。
  async function toggleArtifactReview(runId: string, artifactId: string, reviewed: boolean): Promise<void> {
    setArtifactBusyId(artifactId)
    setArtifactNotice("")
    setError("")
    try {
      await apiRequest(
        `/api/v1/agents/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`,
        // body 契约＝对象：主进程 serializeBody 统一 stringify（预 stringify 会二次编码 → 服务端 4xx）。
        { method: "PATCH", body: { reviewed } },
      )
      setArtifactNotice(reviewed ? "已标记复核。" : "已撤回复核。")
      const refreshed = await apiRequest<AgentRunDetailDto>(
        `/api/v1/agents/runs/${encodeURIComponent(runId)}`,
        { method: "GET" },
      )
      setDetail(refreshed)
    } catch (caught) {
      setError(actionMessage(caught))
    } finally {
      setArtifactBusyId(null)
    }
  }

  // —— G-15：跨 run 终审队列（未复核产物汇总；批量＝逐件既有 PATCH）——

  async function loadReviewQueue(selection: Set<string>): Promise<void> {
    if (!selection.size) {
      setQueue([])
      setCheckedIds(new Set())
      return
    }
    setQueueLoading(true)
    setQueueError("")
    try {
      const details = await Promise.all(
        [...selection].map((runId) =>
          apiRequest<AgentRunDetailDto>(
            `/api/v1/agents/runs/${encodeURIComponent(runId)}`,
            { method: "GET" },
          ),
        ),
      )
      const items: ReviewQueueItem[] = []
      details.forEach((entry) => {
        ;(entry.artifacts ?? [])
          .filter((artifact) => !artifact.reviewed)
          .forEach((artifact) => items.push({ runId: entry.id, artifact }))
      })
      setQueue(items)
      setCheckedIds(new Set(items.map((item) => item.artifact.id)))
    } catch (caught) {
      setQueueError(actionMessage(caught))
    } finally {
      setQueueLoading(false)
    }
  }

  function toggleRunSelect(runId: string): void {
    setSelectedRunIds((prev) => {
      const next = new Set(prev)
      if (next.has(runId)) next.delete(runId)
      else next.add(runId)
      void loadReviewQueue(next)
      return next
    })
  }

  function toggleAllRuns(): void {
    setSelectedRunIds((prev) => {
      const next = prev.size === runs.length ? new Set<string>() : new Set(runs.map((run) => run.id))
      void loadReviewQueue(next)
      return next
    })
  }

  function toggleArtifactCheck(artifactId: string): void {
    setCheckedIds((prev) => {
      const next = new Set(prev)
      if (next.has(artifactId)) next.delete(artifactId)
      else next.add(artifactId)
      return next
    })
  }

  async function batchReview(): Promise<void> {
    const ids = [...checkedIds].filter((id) => queue.some((item) => item.artifact.id === id))
    if (!ids.length) {
      setQueueNotice("请先勾选要复核的产物。")
      return
    }
    setQueueBusy(true)
    setQueueNotice("")
    setError("")
    let succeeded = 0
    let failed = 0
    for (const artifactId of ids) {
      const item = queue.find((entry) => entry.artifact.id === artifactId)
      if (!item) continue
      try {
        await apiRequest(
          `/api/v1/agents/runs/${encodeURIComponent(item.runId)}/artifacts/${encodeURIComponent(artifactId)}`,
          { method: "PATCH", body: { reviewed: true } },
        )
        succeeded += 1
      } catch {
        failed += 1
      }
    }
    setQueueNotice(`批量复核完成：成功 ${succeeded}${failed ? `，失败 ${failed}` : ""}。`)
    setQueueBusy(false)
    await loadReviewQueue(selectedRunIds)
    if (expandedRunId) {
      try {
        const refreshed = await apiRequest<AgentRunDetailDto>(
          `/api/v1/agents/runs/${encodeURIComponent(expandedRunId)}`,
          { method: "GET" },
        )
        setDetail(refreshed)
      } catch (caught) {
        setDetailError(actionMessage(caught))
      }
    }
  }

  // —— T-A10：产物就地预览/下载（content 路由 sha256 自证；错误原样呈现）——

  async function togglePreview(runId: string, artifact: AgentArtifactDto): Promise<void> {
    if (openPreviews.has(artifact.id)) {
      setOpenPreviews((prev) => {
        const next = new Set(prev)
        next.delete(artifact.id)
        return next
      })
      return
    }
    setOpenPreviews((prev) => new Set(prev).add(artifact.id))
    if (previews[artifact.id]?.status === "ready") return
    setPreviews((prev) => ({ ...prev, [artifact.id]: { status: "loading" } }))
    try {
      const data = await apiRequest<ArtifactContentDto>(
        `/api/v1/agents/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifact.id)}/content`,
        { method: "GET" },
      )
      const text = new TextDecoder("utf-8").decode(decodeBase64(data.content_base64))
      setPreviews((prev) => ({ ...prev, [artifact.id]: { status: "ready", text, mime: data.mime } }))
    } catch (caught) {
      setPreviews((prev) => ({ ...prev, [artifact.id]: { status: "error", error: actionMessage(caught) } }))
    }
  }

  async function downloadArtifact(runId: string, artifact: AgentArtifactDto): Promise<void> {
    setDownloadBusyId(artifact.id)
    setError("")
    try {
      const data = await apiRequest<ArtifactContentDto>(
        `/api/v1/agents/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifact.id)}/content`,
        { method: "GET" },
      )
      const blob = new Blob([decodeBase64(data.content_base64).buffer as ArrayBuffer], { type: data.mime })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = fileNameOf(data.storage_ref)
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (caught) {
      setError(actionMessage(caught))
    } finally {
      setDownloadBusyId(null)
    }
  }

  function jumpToSolution(solutionId: string): void {
    const nextHash = `#projects/${encodeURIComponent(projectId)}?tab=delivery&solution=${encodeURIComponent(solutionId)}`
    allowNextHashNavigation(nextHash)
    window.location.hash = nextHash
  }

  async function adoptArtifactAsSolution(runId: string, artifact: AgentArtifactDto): Promise<void> {
    setAdoptBusyId(artifact.id)
    setArtifactNotice("")
    setDetailError("")
    try {
      const result = await apiRequest<ArtifactAdoptionResultDto>(
        `/api/v1/agents/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifact.id)}/adopt-solution`,
        { method: "POST", body: {} },
      )
      const runDetail = await apiRequest<AgentRunDetailDto>(
        `/api/v1/agents/runs/${encodeURIComponent(runId)}`,
        { method: "GET" },
      )
      setDetail(runDetail)
      setArtifactNotice(
        result.duplicate
          ? "该产物已关联交付方案（幂等回执），点击「查看方案」即可前往。"
          : "已将该产物采纳为交付方案，点击「查看方案」即可前往编辑。",
      )
    } catch (caught) {
      setDetailError(actionMessage(caught))
    } finally {
      setAdoptBusyId(null)
    }
  }

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
  // QR-113（goal-crv r7）：顶层 error 不再整页早返回——单件复核 PATCH 409/
  // 下载失败此前把整个控制台坍缩为一行且无恢复路径。改为页内错误条＋重试
  //（load 可重入），与 detailError/queueError 就地呈现语义一致。
  const previewActions = (runId: string, artifact: AgentArtifactDto) => (
    <>
      <button
        className="secondary-button"
        onClick={() => { void togglePreview(runId, artifact) }}
      >
        {openPreviews.has(artifact.id) ? "收起预览" : "预览"}
      </button>{" "}
      <button
        className="secondary-button"
        disabled={downloadBusyId === artifact.id}
        onClick={() => { void downloadArtifact(runId, artifact) }}
      >
        {downloadBusyId === artifact.id ? "正在下载…" : "下载"}
      </button>
    </>
  )

  return (
    <div className="page-stack">
      {error && (
        <p className="empty-copy" role="alert">
          {error}{" "}
          <button className="secondary-button" onClick={() => { void load() }}>
            重试
          </button>
        </p>
      )}
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>智能体运行</h2>
            <p>本项目的智能体 run 列表（运行态）；勾选多个 run 可在其下汇总未复核产物做批量终审；产物/工具调用/成本在详情按需展开。</p>
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
                {canManage ? (
                  <th scope="col">
                    <input
                      type="checkbox"
                      aria-label="全选运行"
                      checked={runs.length > 0 && selectedRunIds.size === runs.length}
                      onChange={toggleAllRuns}
                    />
                  </th>
                ) : null}
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
                  {canManage ? (
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`选择运行 ${shortId(run.id)}`}
                        checked={selectedRunIds.has(run.id)}
                        onChange={() => toggleRunSelect(run.id)}
                      />
                    </td>
                  ) : null}
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

      {canManage && runs.length ? (
        <section className="panel" aria-label="跨 run 终审队列">
          <div className="panel-heading">
            <div>
              <h2>终审队列（跨 run）</h2>
              <p>勾选运行后此处汇总其未复核产物；批量复核＝逐件调用既有单件复核写面，写语义零新增，终审不可绕过。</p>
            </div>
          </div>
          {queueError ? <p role="alert" className="empty-copy">{queueError}</p> : null}
          {queueNotice ? <p role="status" className="notice">{queueNotice}</p> : null}
          {selectedRunIds.size ? (
            queueLoading ? (
              <p className="empty-copy" role="status">正在汇总已选运行的未复核产物…</p>
            ) : (
              <div className="page-stack">
                {queue.length ? (
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th scope="col">选择</th>
                        <th scope="col">运行</th>
                        <th scope="col">产物</th>
                        <th scope="col">类型</th>
                        <th scope="col">指纹 (sha256)</th>
                        <th scope="col">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {queue.map(({ runId, artifact }) => (
                        <Fragment key={artifact.id}>
                          <tr>
                            <td>
                              <input
                                type="checkbox"
                                aria-label={`选择产物 ${artifact.storage_ref}`}
                                checked={checkedIds.has(artifact.id)}
                                onChange={() => toggleArtifactCheck(artifact.id)}
                              />
                            </td>
                            <td><code>{shortId(runId)}</code></td>
                            <td><code>{artifact.storage_ref}</code></td>
                            <td>{artifact.kind}</td>
                            <td><code>{artifact.sha256.slice(0, 12)}…</code></td>
                            <td>{previewActions(runId, artifact)}</td>
                          </tr>
                          {openPreviews.has(artifact.id) ? (
                            <tr>
                              <td colSpan={6}>
                                <PreviewBlock state={previews[artifact.id] ?? { status: "loading" }} kind={artifact.kind} />
                              </td>
                            </tr>
                          ) : null}
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="empty-copy">已选运行没有未复核产物。</p>
                )}
                <div>
                  <button
                    className="primary-button"
                    disabled={queueBusy || checkedIds.size === 0}
                    onClick={() => { void batchReview() }}
                  >
                    {queueBusy ? "正在批量复核…" : `批量标记复核（${checkedIds.size}）`}
                  </button>
                </div>
              </div>
            )
          ) : (
            <p className="empty-copy">勾选上方运行行，将其未复核产物汇总到本队列。</p>
          )}
        </section>
      ) : null}

      {expandedRunId ? (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>运行详情</h2>
              <p>
                {detail?.agent ? `${detail.agent.name}（${detail.agent.kind}）` : <code>{shortId(expandedRunId)}</code>}
                {detail?.fallback_level ? ` · 降级链 ${detail.fallback_level}` : ""}
                {detail?.degraded_reason ? ` · ${detail.degraded_reason}` : ""}
                {detail?.execution_provider ? ` · 通道 ${detail.execution_provider}` : ""}
                {detail?.host_claimed_at ? ` · 宿主领取 ${detail.host_claimed_at.slice(0, 19).replace("T", " ")}` : ""}
                {detail?.host_receipt_at ? ` · 宿主回执 ${detail.host_receipt_at.slice(0, 19).replace("T", " ")}` : ""}
              </p>
            </div>
          </div>
          {detailError ? <p role="alert" className="empty-copy">{detailError}</p> : null}
          {artifactNotice ? <p role="status" className="notice">{artifactNotice}</p> : null}
          {detailLoading ? <p className="empty-copy" role="status">正在加载详情…</p> : null}
          {detail && !detailLoading ? (
            <div className="page-stack">
              {(() => {
                const isTerminalAdoptable = RUN_ADOPTABLE_STATUSES.has(detail.status)
                const showActionColumn = Boolean(
                  canManage || detail.artifacts?.some((item) => Boolean(item.linked_solution_id)),
                )
                const colCount = showActionColumn ? 6 : 5
                return (
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">产物</th>
                    <th scope="col">类型</th>
                    <th scope="col">指纹 (sha256)</th>
                    <th scope="col">复核</th>
                    <th scope="col">方案</th>
                    {showActionColumn ? <th scope="col">操作</th> : null}
                  </tr>
                </thead>
                <tbody>
                  {detail.artifacts?.length ? (
                    detail.artifacts.map((artifact) => (
                      <Fragment key={artifact.id}>
                        <tr>
                          <td><code>{artifact.storage_ref}</code></td>
                          <td>{artifact.kind}</td>
                          <td><code>{artifact.sha256.slice(0, 12)}…</code></td>
                          <td>
                            {artifact.reviewed ? "已复核" : "未复核"}
                            {artifact.reviewed_at ? <small> · {artifact.reviewed_at.slice(0, 19).replace("T", " ")}</small> : null}
                            {artifact.derived_summary ? (
                              <small> · {Object.entries(artifact.derived_summary).map(([key, value]) => `${key}=${value}`).join(" / ")}</small>
                            ) : null}
                          </td>
                          <td>
                            {artifact.linked_solution_id ? (
                              <small>已采纳 <code>{artifact.linked_solution_id.slice(0, 8)}…</code></small>
                            ) : (
                              <small>—</small>
                            )}
                          </td>
                          {showActionColumn ? (
                            <td>
                              {canManage ? (
                                <>
                                  <button
                                    className="secondary-button"
                                    disabled={artifactBusyId === artifact.id}
                                    onClick={() => { void toggleArtifactReview(expandedRunId ?? "", artifact.id, !artifact.reviewed) }}
                                  >
                                    {artifactBusyId === artifact.id ? "正在提交…" : artifact.reviewed ? "撤回复核" : "标记复核"}
                                  </button>{" "}
                                  {previewActions(expandedRunId ?? "", artifact)}
                                </>
                              ) : null}
                              {artifact.linked_solution_id ? (
                                <>
                                  {canManage ? " " : null}
                                  <button
                                    className="secondary-button"
                                    onClick={() => jumpToSolution(artifact.linked_solution_id ?? "")}
                                  >
                                    查看方案
                                  </button>
                                </>
                              ) : canManage && isTerminalAdoptable ? (
                                <>
                                  {" "}
                                  <button
                                    className="primary-button"
                                    disabled={adoptBusyId === artifact.id}
                                    onClick={() => { void adoptArtifactAsSolution(expandedRunId ?? "", artifact) }}
                                  >
                                    {adoptBusyId === artifact.id ? "正在采纳…" : "采纳为方案"}
                                  </button>
                                </>
                              ) : null}
                            </td>
                          ) : null}
                        </tr>
                        {canManage && openPreviews.has(artifact.id) ? (
                          <tr>
                            <td colSpan={colCount}>
                              <PreviewBlock state={previews[artifact.id] ?? { status: "loading" }} kind={artifact.kind} />
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    ))
                  ) : (
                    <tr><td colSpan={colCount}>该运行暂无产物。</td></tr>
                  )}
                </tbody>
              </table>
                )
              })()}
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
