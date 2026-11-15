import { useCallback, useEffect, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"

// V3 T-W6 工作流控制台（workflow-dag-v1 §5 消费面）：定义列表 + run 列表/详情树
// + 取消/恢复按钮。页面仅呈现；写操作走既有 require_auth + 服务层闸（cancel 幂等、
// resume failed-only），服务端 403/409 原样呈现不吞。
// 第二批桌面 AI 辅助闭环·任务 3：顶部新增「从方案生成草稿」区——编译草稿
// （draft-from-plan，落库为 draft 定义）与 AI 起草草稿（generate-ai-draft，返件式
// 零落库）并列双来源；AI 返件就地预览（节点表＋validate 明细＋dag_sha256），
// 「采纳为定义」走既有 POST /workflows 通道；draft 卡片加干跑校验，admin 加发布。

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

interface PlanOptionDto {
  id: string
  title: string
  status: string
  version: number
}

interface SkillOptionDto {
  key: string
  name: string
  status: string
  current_version: number
}

interface WorkflowIssueDto {
  code?: string
  message?: string
  node?: string
}

interface WorkflowValidateDto {
  valid: boolean
  errors: WorkflowIssueDto[]
  warnings: WorkflowIssueDto[]
  order: string[]
  version?: number
  content_sha256?: string
}

interface AiWorkflowDraftDto {
  dag_json: { nodes?: unknown[] }
  validate: WorkflowValidateDto
  dag_sha256: string
  plan_ref: string
  implementation_skill_ref: string
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
  if (caught instanceof ApiClientError) {
    return caught.code ? `[${caught.code}] ${caught.message}` : caught.message
  }
  if (caught instanceof Error) return caught.message
  return "操作失败，请重试。"
}

function issueText(issue: WorkflowIssueDto): string {
  const parts = [issue.node, issue.code, issue.message].filter(Boolean).map(String)
  return parts.length ? parts.join(" · ") : JSON.stringify(issue)
}

function asNodeRows(dag: { nodes?: unknown[] } | null): Array<Record<string, unknown>> {
  if (dag && Array.isArray(dag.nodes)) {
    return dag.nodes.filter((n): n is Record<string, unknown> => typeof n === "object" && n !== null)
  }
  return []
}

interface WorkflowConsoleProps {
  projectId: string
  canManage: boolean
  isAdmin?: boolean
}

export function WorkflowConsole({ projectId, canManage, isAdmin = false }: WorkflowConsoleProps) {
  const { apiRequest } = useAuth()
  const [definitions, setDefinitions] = useState<WorkflowDefinitionDto[]>([])
  const [runs, setRuns] = useState<WorkflowRunDto[]>([])
  const [truncated, setTruncated] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [actionError, setActionError] = useState("")
  const [notice, setNotice] = useState("")
  const [busy, setBusy] = useState(false)
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // —— 从方案生成草稿（双来源）——
  const [planOptions, setPlanOptions] = useState<PlanOptionDto[]>([])
  const [skillOptions, setSkillOptions] = useState<SkillOptionDto[]>([])
  const [selectedPlanId, setSelectedPlanId] = useState("")
  const [selectedSkillRef, setSelectedSkillRef] = useState("")
  const [approvalCapability, setApprovalCapability] = useState("workbench.write")
  const [aiDraft, setAiDraft] = useState<AiWorkflowDraftDto | null>(null)
  const [adoptName, setAdoptName] = useState("")
  const [adoptDescription, setAdoptDescription] = useState("")
  const [validateResults, setValidateResults] = useState<Record<string, WorkflowValidateDto>>({})

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

  // 草稿来源（approved/published 方案 + published 技能）：加载失败静默降级为
  // 空下拉（沿面板族 fail-静默纪律），生成动作仍受服务端闸约束。
  const loadDraftSources = useCallback(async (): Promise<void> => {
    if (!canManage) return
    try {
      const [planData, extData] = await Promise.all([
        apiRequest<{ items: PlanOptionDto[] }>(
          `/api/v1/projects/${encodeURIComponent(projectId)}/delivery-plans`,
          { method: "GET" },
        ),
        apiRequest<{ skills: SkillOptionDto[] }>("/api/v1/extensions", { method: "GET" }),
      ])
      setPlanOptions((planData.items ?? []).filter((p) => p.status === "approved" || p.status === "published"))
      setSkillOptions((extData.skills ?? []).filter((s) => s.status === "published"))
    } catch {
      // 静默降级：下拉为空时用户无法生成草稿（选择闸在 UI，闸码在服务端）
    }
  }, [apiRequest, projectId, canManage])

  useEffect(() => {
    void loadDraftSources()
  }, [loadDraftSources])

  const draftBody = useCallback(():
    { plan_id: string; implementation_skill_ref: string; approval_capability: string } | null => {
    if (!selectedPlanId || !selectedSkillRef) {
      setActionError("请先选择交付方案与实施技能。")
      return null
    }
    const capability = approvalCapability.trim() || "workbench.write"
    return { plan_id: selectedPlanId, implementation_skill_ref: selectedSkillRef, approval_capability: capability }
  }, [selectedPlanId, selectedSkillRef, approvalCapability])

  async function compileFromPlan(): Promise<void> {
    if (busy || !canManage) return
    const body = draftBody()
    if (!body) return
    setActionError("")
    setNotice("")
    setBusy(true)
    try {
      await apiRequest<unknown>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/workflows/draft-from-plan`,
        { method: "POST", body },
      )
      setNotice("已从方案编译生成工作流草稿定义（draft，发布需管理员）。")
      await load()
    } catch (caught) {
      setActionError(actionMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  async function aiDraftFromPlan(): Promise<void> {
    if (busy || !canManage) return
    const body = draftBody()
    if (!body) return
    setActionError("")
    setNotice("")
    setBusy(true)
    try {
      const data = await apiRequest<{ draft: AiWorkflowDraftDto; model: string | null; prompt_version: string }>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/workflows/generate-ai-draft`,
        { method: "POST", body },
      )
      setAiDraft(data.draft)
      const plan = planOptions.find((p) => p.id === selectedPlanId)
      setAdoptName(plan ? `${plan.title} 工作流` : "")
      setNotice(`AI 已起草 DAG 草稿（返件式零落库，采纳后才成为定义）。模型：${data.model ?? "未知"}`)
    } catch (caught) {
      setActionError(actionMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  async function adoptDraft(): Promise<void> {
    if (busy || !aiDraft) return
    const name = adoptName.trim()
    if (!name) {
      setActionError("请填写定义名称后再采纳。")
      return
    }
    setActionError("")
    setNotice("")
    setBusy(true)
    try {
      // 采纳恰含 name/dag（description 非空才携带）；validate 明细等 AI 契约外字段不进 body
      const body: { name: string; dag: unknown; description?: string } = { name, dag: aiDraft.dag_json }
      const description = adoptDescription.trim()
      if (description) body.description = description
      await apiRequest<unknown>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/workflows`,
        { method: "POST", body },
      )
      setAiDraft(null)
      setAdoptName("")
      setAdoptDescription("")
      setNotice("AI 草稿已采纳为工作流定义（draft；发布需管理员）。")
      await load()
    } catch (caught) {
      setActionError(actionMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  async function dryRunDefinition(definition: WorkflowDefinitionDto): Promise<void> {
    if (busy) return
    setActionError("")
    setNotice("")
    setBusy(true)
    try {
      const data = await apiRequest<WorkflowValidateDto>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(definition.id)}/validate`,
        { method: "POST", body: {} },
      )
      setValidateResults((current) => ({ ...current, [definition.id]: data }))
    } catch (caught) {
      setActionError(actionMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  async function publishDefinition(definition: WorkflowDefinitionDto): Promise<void> {
    if (busy || !isAdmin) return
    setActionError("")
    setNotice("")
    setBusy(true)
    try {
      const data = await apiRequest<{ definition: WorkflowDefinitionDto; version: number; content_sha256: string }>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(definition.id)}/publish`,
        { method: "POST", body: {} },
      )
      setNotice(`工作流定义已发布为 v${data.version}（dag 快照不可变）。`)
      await load()
    } catch (caught) {
      setActionError(actionMessage(caught))
    } finally {
      setBusy(false)
    }
  }

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

  // 发起运行（can_manage，服务端闸已存在）：只有已发布定义可发起。成功后重拉
  // 运行列表（新 run 是 queued，由 worker 接单）。403/409 原样呈现不吞——
  // 与 cancel/resume 同一纪律。
  async function launch(definition: WorkflowDefinitionDto): Promise<void> {
    setActionError("")
    setBusy(true)
    try {
      await apiRequest<{ run: WorkflowRunDto; created: boolean }>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(definition.id)}/runs`,
        { method: "POST", body: {} },
      )
      await load()
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
      {actionError ? <p role="alert" className="empty-copy">{actionError}</p> : null}
      {notice ? <p role="status" className="empty-copy">{notice}</p> : null}

      {canManage ? (
        <section className="panel" aria-label="从方案生成草稿">
          <div className="panel-heading">
            <div>
              <h2>从方案生成草稿</h2>
              <p>编译草稿直接落库为 draft 定义；AI 起草为返件式零落库，就地预览并人工采纳后才是定义。</p>
            </div>
          </div>
          <div className="page-stack">
            <label>
              交付方案（approved/published）
              <select
                aria-label="交付方案"
                value={selectedPlanId}
                onChange={(e) => setSelectedPlanId(e.target.value)}
              >
                <option value="">请选择交付方案</option>
                {planOptions.map((plan) => (
                  <option key={plan.id} value={plan.id}>
                    {plan.title}（v{plan.version} · {statusLabel(DEFINITION_STATUS_LABEL, plan.status)}）
                  </option>
                ))}
              </select>
            </label>
            <label>
              实施技能（published，key@版本）
              <select
                aria-label="实施技能"
                value={selectedSkillRef}
                onChange={(e) => setSelectedSkillRef(e.target.value)}
              >
                <option value="">请选择实施技能</option>
                {skillOptions.map((skill) => {
                  const ref = `${skill.key}@${skill.current_version}`
                  return (
                    <option key={ref} value={ref}>
                      {skill.name}（{ref}）
                    </option>
                  )
                })}
              </select>
            </label>
            <label>
              审批能力
              <input
                type="text"
                aria-label="审批能力"
                value={approvalCapability}
                onChange={(e) => setApprovalCapability(e.target.value)}
                placeholder="workbench.write"
              />
            </label>
            <div className="plugin-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={busy}
                onClick={() => void compileFromPlan()}
              >
                编译草稿
              </button>
              <button
                type="button"
                className="primary-button"
                disabled={busy}
                onClick={() => void aiDraftFromPlan()}
              >
                AI 起草草稿
              </button>
            </div>
          </div>

          {aiDraft ? (
            <div className="panel" aria-label="AI 起草预览">
              <p><strong>AI 起草预览（未落库）</strong>　<code>{aiDraft.dag_sha256.slice(0, 16)}…</code></p>
              <p>
                干跑校验：{aiDraft.validate.valid ? "通过" : "未通过"}
                {aiDraft.validate.errors.length ? `（${aiDraft.validate.errors.length} 个错误）` : ""}
                {aiDraft.validate.warnings.length ? `（${aiDraft.validate.warnings.length} 个告警）` : ""}
              </p>
              {aiDraft.validate.errors.length ? (
                <ul>
                  {aiDraft.validate.errors.map((issue, index) => (
                    <li key={index}>{issueText(issue)}</li>
                  ))}
                </ul>
              ) : null}
              {aiDraft.validate.warnings.length ? (
                <ul>
                  {aiDraft.validate.warnings.map((issue, index) => (
                    <li key={index}>告警：{issueText(issue)}</li>
                  ))}
                </ul>
              ) : null}
              {aiDraft.validate.order.length ? (
                <p><small>执行序：{aiDraft.validate.order.join(" → ")}</small></p>
              ) : null}
              {asNodeRows(aiDraft.dag_json).length ? (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th scope="col">节点</th>
                      <th scope="col">类型</th>
                      <th scope="col">依赖</th>
                    </tr>
                  </thead>
                  <tbody>
                    {asNodeRows(aiDraft.dag_json).map((node, index) => (
                      <tr key={index}>
                        <td><code>{String(node.key ?? "")}</code></td>
                        <td>{String(node.type ?? "")}</td>
                        <td>{Array.isArray(node.depends_on) ? node.depends_on.map(String).join(", ") : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : null}
              <label>
                定义名称
                <input
                  type="text"
                  aria-label="定义名称"
                  value={adoptName}
                  onChange={(e) => setAdoptName(e.target.value)}
                />
              </label>
              <label>
                定义描述（可选）
                <input
                  type="text"
                  aria-label="定义描述"
                  value={adoptDescription}
                  onChange={(e) => setAdoptDescription(e.target.value)}
                />
              </label>
              <div className="plugin-actions">
                <button
                  type="button"
                  className="primary-button"
                  disabled={busy || !adoptName.trim()}
                  onClick={() => void adoptDraft()}
                >
                  采纳为定义
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={busy}
                  onClick={() => setAiDraft(null)}
                >
                  放弃草稿
                </button>
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>工作流定义</h2>
            <p>项目内流程定义（草稿与已发布）；已发布的定义可直接发起运行（需管理权限）。</p>
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
                {canManage && definition.status === "published" ? (
                  <div className="plugin-actions">
                    <button className="secondary-button" disabled={busy} onClick={() => void launch(definition)}>
                      启动
                    </button>
                  </div>
                ) : null}
                {canManage && definition.status === "draft" ? (
                  <div className="plugin-actions">
                    <button className="secondary-button" disabled={busy} onClick={() => void dryRunDefinition(definition)}>
                      干跑校验
                    </button>
                    {isAdmin ? (
                      <button className="primary-button" disabled={busy} onClick={() => void publishDefinition(definition)}>
                        发布
                      </button>
                    ) : null}
                  </div>
                ) : null}
                {validateResults[definition.id] ? (
                  <div role="region" aria-label={`干跑校验结果 ${definition.name}`}>
                    <p>
                      干跑校验：{validateResults[definition.id].valid ? "通过（无错误）" : "未通过"}
                      {validateResults[definition.id].warnings.length
                        ? ` · ${validateResults[definition.id].warnings.length} 个告警`
                        : ""}
                    </p>
                    {validateResults[definition.id].errors.length ? (
                      <ul>
                        {validateResults[definition.id].errors.map((issue, index) => (
                          <li key={index}>{issueText(issue)}</li>
                        ))}
                      </ul>
                    ) : null}
                    {validateResults[definition.id].warnings.length ? (
                      <ul>
                        {validateResults[definition.id].warnings.map((issue, index) => (
                          <li key={index}>告警：{issueText(issue)}</li>
                        ))}
                      </ul>
                    ) : null}
                    {validateResults[definition.id].order.length ? (
                      <p><small>执行序：{validateResults[definition.id].order.join(" → ")}</small></p>
                    ) : null}
                  </div>
                ) : null}
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
