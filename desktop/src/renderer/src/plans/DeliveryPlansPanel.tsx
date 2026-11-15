import { useCallback, useEffect, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import type { ProjectModuleDto } from "../workbench/types"

// 第二批桌面 AI 辅助闭环·任务 1：交付方案面板（plans 蓝图消费面）。
// 确定性生成（generate）与 AI 起草（generate-ai）并列双来源，产出恒为 draft 方案；
// 审阅闸（draft→approved/superseded）与发布闸（approved→published）在服务端，桌面端不代拍。
// 任务分解仅限 approved/published 方案：先 dry_run:true 预览，再 dry_run:false 落任务。

export interface DeliveryPlanItemDto {
  id: string
  item_type: string
  title: string
  detail: string | null
  priority: string
  requirement_keys: string[]
  fact_ids: string[]
  sort_order: number
  task_id: string | null
}

export interface DeliveryPlanDto {
  id: string
  project_id: string
  title: string
  summary: string | null
  status: string
  version: number
  source_extraction_id: string | null
  created_by_user_id: string
  reviewed_by_user_id: string | null
  reviewed_at: string | null
  review_comment: string | null
  published_by_user_id: string | null
  published_at: string | null
  items: DeliveryPlanItemDto[]
  task_link_count: number
}

interface PlanListDto {
  items: DeliveryPlanDto[]
  limit?: number
}

interface TaskPreviewItemDto {
  item_id: string
  item_type: string
  name: string
  description: string
  duration_days: number
}

interface CreatePlanTasksResponseDto {
  dry_run: boolean
  created: Array<{ item_id: string; task_id: string }>
  skipped: Array<{ item_id: string; task_id: string; reason: string }>
  preview: TaskPreviewItemDto[]
}

const PLAN_STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  approved: "已批准",
  published: "已发布",
  superseded: "已取代",
}

const ITEM_TYPE_LABEL: Record<string, string> = {
  requirement: "需求",
  fact: "事实",
  risk: "风险",
  open_question: "待确认问题",
  task: "任务",
  milestone: "里程碑",
}

const PRIORITY_LABEL: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
}

function labelOf(map: Record<string, string>, value: string): string {
  return map[value] ?? value
}

function formatError(caught: unknown): string {
  if (caught instanceof ApiClientError) {
    return caught.code ? `[${caught.code}] ${caught.message}` : caught.message
  }
  if (caught instanceof Error) return caught.message
  return "操作失败，请重试。"
}

interface DeliveryPlansPanelProps {
  projectId: string
  canManage: boolean
  modules: ProjectModuleDto[]
  onTasksCreated?: () => void
}

export function DeliveryPlansPanel({
  projectId,
  canManage,
  modules,
  onTasksCreated,
}: DeliveryPlansPanelProps) {
  const { apiRequest } = useAuth()
  const activeModules = modules.filter((m) => m.status !== "cancelled")
  const [plans, setPlans] = useState<DeliveryPlanDto[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [reviewComments, setReviewComments] = useState<Record<string, string>>({})
  const [decomposePlanId, setDecomposePlanId] = useState<string | null>(null)
  const [selectedModuleId, setSelectedModuleId] = useState<string>(activeModules[0]?.id ?? "")
  const [selectedItemIds, setSelectedItemIds] = useState<Record<string, boolean>>({})
  const [previewResult, setPreviewResult] = useState<CreatePlanTasksResponseDto | null>(null)

  useEffect(() => {
    if (!selectedModuleId && activeModules[0]?.id) {
      setSelectedModuleId(activeModules[0].id)
    } else if (selectedModuleId && !activeModules.some((m) => m.id === selectedModuleId)) {
      setSelectedModuleId(activeModules[0]?.id ?? "")
    }
  }, [activeModules, selectedModuleId])

  const reload = useCallback(async () => {
    try {
      const data = await apiRequest<PlanListDto>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/delivery-plans`,
        { method: "GET" },
      )
      setPlans(Array.isArray(data?.items) ? data.items : [])
    } catch {
      // 初始/刷新列表静默降级（沿 HandoverPackagesPanel/TranscriptDraftsPanel 同款纪律，
      // 不抢页面级 role="alert"；所有写动作失败均原样走 alert 呈现）
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
        ? `/api/v1/projects/${encodeURIComponent(projectId)}/delivery-plans/generate-ai`
        : `/api/v1/projects/${encodeURIComponent(projectId)}/delivery-plans/generate`
    try {
      await apiRequest<unknown>(endpoint, { method: "POST", body: {} })
      setNotice(mode === "ai" ? "AI 已起草交付方案草稿（待人工审阅）。" : "已确定性生成交付方案草稿（待人工审阅）。")
      await reload()
    } catch (caught) {
      setError(formatError(caught))
    } finally {
      setBusy(false)
    }
  }

  const review = async (plan: DeliveryPlanDto, decision: "approved" | "rejected") => {
    if (busy || !canManage) return
    const rawComment = reviewComments[plan.id] ?? ""
    if (rawComment.length > 500) {
      setError("[invalid_comment] 审阅备注必须是 ≤500 字的文本。")
      return
    }
    setBusy(true)
    setError("")
    setNotice("")
    try {
      const body: { decision: "approved" | "rejected"; comment?: string } = { decision }
      if (rawComment.trim()) body.comment = rawComment.trim()
      await apiRequest<DeliveryPlanDto>(
        `/api/v1/delivery-plans/${encodeURIComponent(plan.id)}/review`,
        { method: "PATCH", body },
      )
      setNotice(decision === "approved" ? `方案 v${plan.version} 已批准。` : `方案 v${plan.version} 已驳回。`)
      await reload()
    } catch (caught) {
      setError(formatError(caught))
    } finally {
      setBusy(false)
    }
  }

  const publish = async (plan: DeliveryPlanDto) => {
    if (busy || !canManage) return
    setBusy(true)
    setError("")
    setNotice("")
    try {
      await apiRequest<DeliveryPlanDto>(
        `/api/v1/delivery-plans/${encodeURIComponent(plan.id)}/publish`,
        { method: "POST", body: {} },
      )
      setNotice(`方案 v${plan.version} 已发布。`)
      await reload()
    } catch (caught) {
      setError(formatError(caught))
    } finally {
      setBusy(false)
    }
  }

  const openDecompose = (plan: DeliveryPlanDto) => {
    if (decomposePlanId === plan.id) {
      setDecomposePlanId(null)
      setPreviewResult(null)
      return
    }
    setDecomposePlanId(plan.id)
    setPreviewResult(null)
    setError("")
    setNotice("")
    if (!selectedModuleId && activeModules[0]?.id) {
      setSelectedModuleId(activeModules[0].id)
    }
    const defaults: Record<string, boolean> = {}
    for (const item of plan.items) {
      if (!item.task_id) defaults[item.id] = true
    }
    setSelectedItemIds(defaults)
  }

  const buildTaskPayload = (plan: DeliveryPlanDto, dryRun: boolean) => {
    const unlinkedIds = plan.items.filter((i) => !i.task_id).map((i) => i.id)
    const chosen = plan.items.filter((i) => selectedItemIds[i.id]).map((i) => i.id)
    const body: { module_id: string; dry_run: boolean; item_ids?: string[] } = {
      module_id: selectedModuleId,
      dry_run: dryRun,
    }
    if (chosen.length > 0 && chosen.length < unlinkedIds.length) {
      body.item_ids = chosen
    } else if (chosen.length > 0 && unlinkedIds.length !== plan.items.length) {
      body.item_ids = chosen
    }
    return body
  }

  const runDecompose = async (plan: DeliveryPlanDto, dryRun: boolean) => {
    if (busy || !canManage) return
    if (!selectedModuleId) {
      setError("请先选择目标模块。")
      return
    }
    setBusy(true)
    setError("")
    setNotice("")
    try {
      const result = await apiRequest<CreatePlanTasksResponseDto>(
        `/api/v1/delivery-plans/${encodeURIComponent(plan.id)}/tasks`,
        { method: "POST", body: buildTaskPayload(plan, dryRun) },
      )
      if (dryRun) {
        setPreviewResult(result)
      } else {
        setPreviewResult(null)
        setDecomposePlanId(null)
        setNotice(`已分解创建 ${result.created.length} 条任务（跳过 ${result.skipped.length} 条）。`)
        await reload()
        onTasksCreated?.()
      }
    } catch (caught) {
      setError(formatError(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel" aria-label="交付方案">
      <div className="panel-heading">
        <div>
          <h2>交付方案</h2>
          <p>从已批准需求与已接受事实生成方案草稿（确定性拼装或 AI 起草并列，产物恒为草稿，经人工审阅与发布后生效）。</p>
        </div>
        {canManage ? (
          <div className="plugin-actions">
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
        <p className="empty-copy">正在加载交付方案…</p>
      ) : plans.length === 0 ? (
        <p className="empty-copy">暂无交付方案草稿或已发布版本。</p>
      ) : (
        <div className="page-stack">
          {plans.map((plan) => {
            const isDraft = plan.status === "draft"
            const isApproved = plan.status === "approved"
            const canDecompose = plan.status === "approved" || plan.status === "published"
            const decomposing = decomposePlanId === plan.id
            return (
              <article key={plan.id} className="extension-item" data-testid={`delivery-plan-${plan.id}`}>
                <div>
                  <span className={`extension-scope ${plan.status === "published" ? "public" : ""}`}>
                    {labelOf(PLAN_STATUS_LABEL, plan.status)}
                  </span>
                  <strong>{plan.title}</strong>
                  <small> v{plan.version} · {plan.items.length} 条目 · 已关联任务 {plan.task_link_count}</small>
                </div>
                {plan.summary ? <p>{plan.summary}</p> : null}
                {plan.review_comment ? <p><small>审阅备注：{plan.review_comment}</small></p> : null}

                {plan.items.length > 0 ? (
                  <ul className="compact-list">
                    {plan.items.map((item) => (
                      <li key={item.id}>
                        <span>[{labelOf(ITEM_TYPE_LABEL, item.item_type)} · 优先级{labelOf(PRIORITY_LABEL, item.priority)}]</span>{" "}
                        <strong>{item.title}</strong>
                        {item.requirement_keys.length > 0 ? (
                          <small>（需求：{item.requirement_keys.join(", ")}）</small>
                        ) : null}
                        {item.task_id ? <small> · 已落任务 {item.task_id.slice(0, 8)}</small> : null}
                      </li>
                    ))}
                  </ul>
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

                {canManage && (isApproved || canDecompose) ? (
                  <div className="plugin-actions">
                    {isApproved ? (
                      <button
                        type="button"
                        className="primary-button"
                        disabled={busy}
                        onClick={() => void publish(plan)}
                      >
                        发布
                      </button>
                    ) : null}
                    {canDecompose ? (
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={busy || activeModules.length === 0}
                        title={activeModules.length === 0 ? "当前项目暂无可用模块，请先添加模块后再分解任务" : undefined}
                        onClick={() => openDecompose(plan)}
                      >
                        {decomposing ? "收起分解" : "分解任务"}
                      </button>
                    ) : null}
                    {canDecompose && activeModules.length === 0 ? (
                      <small>暂无可用项目模块，无法分解任务。</small>
                    ) : null}
                  </div>
                ) : null}

                {canManage && canDecompose && decomposing && activeModules.length > 0 ? (
                  <div className="panel" aria-label={`分解任务面板 v${plan.version}`}>
                    <label>
                      目标模块
                      <select
                        aria-label="目标模块"
                        value={selectedModuleId}
                        onChange={(e) => {
                          setSelectedModuleId(e.target.value)
                          setPreviewResult(null)
                        }}
                      >
                        {activeModules.map((mod) => (
                          <option key={mod.id} value={mod.id}>
                            {mod.name} ({mod.module_key})
                          </option>
                        ))}
                      </select>
                    </label>

                    {plan.items.length > 0 ? (
                      <div>
                        <small>选择要分解的条目（已分解条目自动跳过）：</small>
                        <ul>
                          {plan.items.map((item) => (
                            <li key={item.id}>
                              <label>
                                <input
                                  type="checkbox"
                                  disabled={Boolean(item.task_id) || busy}
                                  checked={Boolean(selectedItemIds[item.id]) && !item.task_id}
                                  onChange={(e) => {
                                    setSelectedItemIds((curr) => ({
                                      ...curr,
                                      [item.id]: e.target.checked,
                                    }))
                                    setPreviewResult(null)
                                  }}
                                />
                                {item.title}
                                {item.task_id ? "（已分解）" : ""}
                              </label>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}

                    <div className="plugin-actions">
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={busy || !selectedModuleId}
                        onClick={() => void runDecompose(plan, true)}
                      >
                        预览分解
                      </button>
                      {previewResult ? (
                        <button
                          type="button"
                          className="primary-button"
                          disabled={busy || !selectedModuleId}
                          onClick={() => void runDecompose(plan, false)}
                        >
                          确认创建任务
                        </button>
                      ) : null}
                    </div>

                    {previewResult ? (
                      <div role="region" aria-label="分解预览结果">
                        <p>
                          预览：将创建 {previewResult.preview.length} 条任务，跳过 {previewResult.skipped.length} 条已分解条目。
                        </p>
                        {previewResult.preview.length > 0 ? (
                          <ul>
                            {previewResult.preview.map((draft) => (
                              <li key={draft.item_id}>
                                {draft.name}（预计 {draft.duration_days} 天）
                              </li>
                            ))}
                          </ul>
                        ) : null}
                      </div>
                    ) : null}
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
