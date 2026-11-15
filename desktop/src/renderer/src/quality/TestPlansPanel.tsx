import { useCallback, useEffect, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import type { ProjectTaskDto } from "../workbench/types"

// 第二批桌面 AI 辅助闭环·任务 2：测试计划面板（quality 蓝图消费面）。
// 确定性生成（generate）与 AI 起草（generate-ai）并列双来源，可带 source_task_id
// （任务下拉选中即透传）；产物恒为 draft 计划，审阅闸（覆盖闸在服务端
// 409 requirement_coverage_incomplete）与执行登记闸（仅 approved；production
// 恒 409 不出 UI 选项；报告指针与 sha256 成对，缺一前端拦截）不代拍。

export interface TestCaseDto {
  id: string
  case_key: string
  title: string
  preconditions: string | null
  steps: string[]
  expected: string | null
  risk_level: number
  automated: boolean
  acceptance_mode: string
  requirement_key: string
  sort_order: number
}

export interface TestPlanDto {
  id: string
  project_id: string
  source_task_id: string | null
  title: string
  version: number
  status: string
  created_by_user_id: string
  reviewed_by_user_id: string | null
  reviewed_at: string | null
  review_comment: string | null
  cases: TestCaseDto[]
  case_count: number
}

type ExecutionResult = "passed" | "failed" | "blocked"

const PLAN_STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  approved: "已批准",
  superseded: "已取代",
}

const ACCEPTANCE_MODE_LABEL: Record<string, string> = {
  test: "测试",
  manual: "人工验收",
}

const RESULT_LABEL: Record<ExecutionResult, string> = {
  passed: "通过",
  failed: "失败",
  blocked: "阻塞",
}

function labelOf(map: Record<string, string>, value: string): string {
  return map[value] ?? value
}

function riskLabel(level: number): string {
  return ({ 3: "高", 2: "中", 1: "低" })[level] ?? String(level)
}

function formatError(caught: unknown): string {
  if (caught instanceof ApiClientError) {
    const base = caught.code ? `[${caught.code}] ${caught.message}` : caught.message
    const details = caught.details
    const missing =
      details && typeof details === "object" && Array.isArray((details as { missing_requirement_keys?: unknown }).missing_requirement_keys)
        ? ` 缺失需求：${((details as { missing_requirement_keys: unknown[] }).missing_requirement_keys).join(", ")}`
        : ""
    return `${base}${missing}`
  }
  if (caught instanceof Error) return caught.message
  return "操作失败，请重试。"
}

interface ExecutionDraft {
  result: "" | ExecutionResult
  reportUri: string
  reportSha256: string
}

interface TestPlansPanelProps {
  projectId: string
  canManage: boolean
  tasks: ProjectTaskDto[]
}

export function TestPlansPanel({ projectId, canManage, tasks }: TestPlansPanelProps) {
  const { apiRequest } = useAuth()
  const usableTasks = tasks.filter((task) => task.status !== "cancelled")
  const [plans, setPlans] = useState<TestPlanDto[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [sourceTaskId, setSourceTaskId] = useState("")
  const [reviewComments, setReviewComments] = useState<Record<string, string>>({})
  const [executingPlanId, setExecutingPlanId] = useState<string | null>(null)
  const [executionEnvironment, setExecutionEnvironment] = useState<"dev" | "staging">("dev")
  const [executionDrafts, setExecutionDrafts] = useState<Record<string, ExecutionDraft>>({})

  const reload = useCallback(async () => {
    try {
      const data = await apiRequest<{ items: TestPlanDto[] }>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/test-plans`,
        { method: "GET" },
      )
      setPlans(Array.isArray(data?.items) ? data.items : [])
    } catch {
      // 初始/刷新列表静默降级（沿面板族 fail-静默纪律；写动作失败走 alert 原样呈现）
    } finally {
      setLoading(false)
    }
  }, [apiRequest, projectId])

  useEffect(() => {
    setLoading(true)
    void reload()
  }, [reload])

  const generate = async (mode: "deterministic" | "ai") => {
    if (busy || !canManage) return
    setBusy(true)
    setError("")
    setNotice("")
    const endpoint =
      mode === "ai"
        ? `/api/v1/projects/${encodeURIComponent(projectId)}/test-plans/generate-ai`
        : `/api/v1/projects/${encodeURIComponent(projectId)}/test-plans/generate`
    const body: { source_task_id?: string } = {}
    if (sourceTaskId) body.source_task_id = sourceTaskId
    try {
      await apiRequest<unknown>(endpoint, { method: "POST", body })
      setNotice(mode === "ai" ? "AI 已起草测试计划草稿（待人工审阅）。" : "已确定性生成测试计划草稿（待人工审阅）。")
      await reload()
    } catch (caught) {
      setError(formatError(caught))
    } finally {
      setBusy(false)
    }
  }

  const review = async (plan: TestPlanDto, decision: "approved" | "rejected") => {
    if (busy || !canManage) return
    const rawComment = reviewComments[plan.id] ?? ""
    if (rawComment.length > 500) {
      setError("审阅备注必须是 ≤500 字的文本。")
      return
    }
    setBusy(true)
    setError("")
    setNotice("")
    try {
      const body: { decision: "approved" | "rejected"; comment?: string } = { decision }
      if (rawComment.trim()) body.comment = rawComment.trim()
      await apiRequest<{ plan: TestPlanDto }>(
        `/api/v1/test-plans/${encodeURIComponent(plan.id)}/review`,
        { method: "PATCH", body },
      )
      setNotice(decision === "approved" ? `测试计划 v${plan.version} 已批准。` : `测试计划 v${plan.version} 已驳回。`)
      await reload()
    } catch (caught) {
      setError(formatError(caught))
    } finally {
      setBusy(false)
    }
  }

  const toggleExecute = (plan: TestPlanDto) => {
    if (executingPlanId === plan.id) {
      setExecutingPlanId(null)
      return
    }
    setExecutingPlanId(plan.id)
    setError("")
    setNotice("")
    setExecutionEnvironment("dev")
    const defaults: Record<string, ExecutionDraft> = {}
    for (const testCase of plan.cases) {
      defaults[testCase.id] = { result: "", reportUri: "", reportSha256: "" }
    }
    setExecutionDrafts(defaults)
  }

  const updateDraft = (caseId: string, patch: Partial<ExecutionDraft>) => {
    setExecutionDrafts((current) => ({
      ...current,
      [caseId]: { ...current[caseId], ...patch },
    }))
  }

  const submitExecutions = async (plan: TestPlanDto) => {
    if (busy || !canManage) return
    const chosen = plan.cases.filter((testCase) => executionDrafts[testCase.id]?.result)
    if (!chosen.length) {
      setError("请至少为一条用例选择执行结果。")
      return
    }
    for (const testCase of chosen) {
      const draft = executionDrafts[testCase.id]
      if (Boolean(draft.reportUri.trim()) !== Boolean(draft.reportSha256.trim())) {
        setError(`用例 ${testCase.case_key}：报告指针与报告 sha256 须成对提供（请同时填写或同时留空）。`)
        return
      }
    }
    setBusy(true)
    setError("")
    setNotice("")
    try {
      const executions = chosen.map((testCase) => {
        const draft = executionDrafts[testCase.id]
        const row: {
          case_id: string
          result: ExecutionResult
          report_uri?: string
          report_sha256?: string
        } = { case_id: testCase.id, result: draft.result as ExecutionResult }
        if (draft.reportUri.trim()) row.report_uri = draft.reportUri.trim()
        if (draft.reportSha256.trim()) row.report_sha256 = draft.reportSha256.trim()
        return row
      })
      await apiRequest<unknown>(
        `/api/v1/test-plans/${encodeURIComponent(plan.id)}/execute`,
        { method: "POST", body: { environment: executionEnvironment, executions } },
      )
      setNotice(`已登记 ${executions.length} 条执行记录（append-only，重跑即新行）。`)
      setExecutingPlanId(null)
      await reload()
    } catch (caught) {
      setError(formatError(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel" aria-label="测试计划">
      <div className="panel-heading">
        <div>
          <h2>测试计划</h2>
          <p>从已批准需求生成测试计划草稿（确定性拼装或 AI 起草并列）；审阅通过后方可登记执行（append-only）。</p>
        </div>
        {canManage ? (
          <div className="plugin-actions">
            <label>
              来源任务
              <select
                aria-label="来源任务"
                value={sourceTaskId}
                onChange={(e) => setSourceTaskId(e.target.value)}
              >
                <option value="">不指定（按项目全部已批准需求）</option>
                {usableTasks.map((task) => (
                  <option key={task.id} value={task.id}>
                    {task.name}（{task.task_key}）
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="secondary-button"
              disabled={busy}
              onClick={() => void generate("deterministic")}
            >
              确定性生成
            </button>
            <button
              type="button"
              className="primary-button"
              disabled={busy}
              onClick={() => void generate("ai")}
            >
              AI 起草
            </button>
          </div>
        ) : null}
      </div>

      {error ? <p className="form-error banner" role="alert">{error}</p> : null}
      {notice ? <p className="notice" role="status">{notice}</p> : null}

      {loading ? (
        <p className="empty-copy">正在加载测试计划…</p>
      ) : plans.length === 0 ? (
        <p className="empty-copy">暂无测试计划草稿或已批准版本。</p>
      ) : (
        <div className="page-stack">
          {plans.map((plan) => {
            const isDraft = plan.status === "draft"
            const isApproved = plan.status === "approved"
            const executing = executingPlanId === plan.id
            return (
              <article key={plan.id} className="extension-item" data-testid={`test-plan-${plan.id}`}>
                <div>
                  <span className={`extension-scope ${plan.status === "approved" ? "public" : ""}`}>
                    {labelOf(PLAN_STATUS_LABEL, plan.status)}
                  </span>
                  <strong>{plan.title}</strong>
                  <small> v{plan.version} · {plan.case_count} 用例</small>
                </div>
                {plan.review_comment ? <p><small>审阅备注：{plan.review_comment}</small></p> : null}

                {plan.cases.length > 0 ? (
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th scope="col">用例号</th>
                        <th scope="col">标题</th>
                        <th scope="col">风险</th>
                        <th scope="col">验收方式</th>
                        <th scope="col">需求追溯</th>
                      </tr>
                    </thead>
                    <tbody>
                      {plan.cases.map((testCase) => (
                        <tr key={testCase.id}>
                          <td><code>{testCase.case_key}</code></td>
                          <td>{testCase.title}</td>
                          <td>{riskLabel(testCase.risk_level)}</td>
                          <td>{labelOf(ACCEPTANCE_MODE_LABEL, testCase.acceptance_mode)}</td>
                          <td><code>{testCase.requirement_key}</code></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : null}

                {canManage && isDraft ? (
                  <div className="page-stack">
                    <label>
                      审阅备注（可选，≤500 字）
                      <input
                        type="text"
                        maxLength={500}
                        aria-label={`审阅备注 v${plan.version}`}
                        value={reviewComments[plan.id] ?? ""}
                        onChange={(e) =>
                          setReviewComments((curr) => ({ ...curr, [plan.id]: e.target.value }))
                        }
                        placeholder="输入审阅意见（可选）"
                      />
                    </label>
                    <div className="plugin-actions">
                      <button
                        type="button"
                        className="primary-button"
                        disabled={busy}
                        onClick={() => void review(plan, "approved")}
                      >
                        批准
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={busy}
                        onClick={() => void review(plan, "rejected")}
                      >
                        驳回
                      </button>
                    </div>
                  </div>
                ) : null}

                {canManage && isApproved ? (
                  <div className="plugin-actions">
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={busy}
                      onClick={() => toggleExecute(plan)}
                    >
                      {executing ? "收起执行登记" : "登记执行"}
                    </button>
                  </div>
                ) : null}

                {canManage && isApproved && executing ? (
                  <div className="panel" aria-label={`执行登记面板 v${plan.version}`}>
                    <label>
                      执行环境
                      <select
                        aria-label="执行环境"
                        value={executionEnvironment}
                        onChange={(e) => setExecutionEnvironment(e.target.value === "staging" ? "staging" : "dev")}
                      >
                        {/* production 恒 409（服务层硬闸）——UI 不提供该选项 */}
                        <option value="dev">dev（开发环境）</option>
                        <option value="staging">staging（预发环境）</option>
                      </select>
                    </label>
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th scope="col">用例</th>
                          <th scope="col">结果</th>
                          <th scope="col">报告指针（与指纹成对）</th>
                          <th scope="col">报告 sha256</th>
                        </tr>
                      </thead>
                      <tbody>
                        {plan.cases.map((testCase) => {
                          const draft = executionDrafts[testCase.id]
                          return (
                            <tr key={testCase.id}>
                              <td><code>{testCase.case_key}</code></td>
                              <td>
                                <select
                                  aria-label={`执行结果 ${testCase.case_key}`}
                                  value={draft?.result ?? ""}
                                  onChange={(e) =>
                                    updateDraft(testCase.id, {
                                      result: e.target.value as ExecutionDraft["result"],
                                    })
                                  }
                                >
                                  <option value="">未登记</option>
                                  <option value="passed">通过</option>
                                  <option value="failed">失败</option>
                                  <option value="blocked">阻塞</option>
                                </select>
                              </td>
                              <td>
                                <input
                                  type="text"
                                  aria-label={`报告指针 ${testCase.case_key}`}
                                  value={draft?.reportUri ?? ""}
                                  onChange={(e) => updateDraft(testCase.id, { reportUri: e.target.value })}
                                  placeholder="如 file:///D:/reports/r1.html（可选）"
                                />
                              </td>
                              <td>
                                <input
                                  type="text"
                                  aria-label={`报告 sha256 ${testCase.case_key}`}
                                  value={draft?.reportSha256 ?? ""}
                                  onChange={(e) => updateDraft(testCase.id, { reportSha256: e.target.value })}
                                  placeholder="64 位十六进制（可选）"
                                />
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                    <div className="plugin-actions">
                      <button
                        type="button"
                        className="primary-button"
                        disabled={busy}
                        onClick={() => void submitExecutions(plan)}
                      >
                        提交执行记录
                      </button>
                    </div>
                  </div>
                ) : null}
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}
