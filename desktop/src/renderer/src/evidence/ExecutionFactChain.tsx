import { Fragment, useCallback, useEffect, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"

// 借鉴登记 #9：只读执行事实链面板（execution-fact-chain 消费面）。
// 数据源 = GET /projects/{id}/execution-facts（can_view，服务端三源归并）：
// - evidence（项目维度）：证据指针 + sha256 指纹；原件永远留在本地工作目录（红线），
//   面板只呈现指纹摘要，不取原件内容。
// - operation_event（项目维度）：操作事件元数据；服务端不回传 changes 载荷。
// - ai_call_audit（**账号维度** scope=actor）：AI 调用事实（模型/耗时/token/状态）；
//   该表无项目外键——面板明示「账号维度」，不假装项目维度。
// 「外部完成无真实回执=未知」纪律：无记录即显示「无记录」，前端不拼装任何
// 「已完成」推断。本面板纯只读：无任何写操作按钮。

interface FactItem {
  fact_type: "evidence" | "operation_event" | "ai_call_audit"
  id: string
  // evidence
  kind?: string
  source_uri?: string
  content_sha256?: string
  origin?: string | null
  captured_from?: string | null
  created_at?: string | null
  updated_at?: string | null
  // operation_event
  actor_user_id?: string
  target_type?: string
  target_id?: string
  event_type?: string
  occurred_at?: string | null
  // ai_call_audit
  request_id?: string
  purpose?: string | null
  model?: string
  used_fallback?: boolean
  status?: string
  error_code?: string | null
  duration_ms?: number
  input_tokens?: number | null
  output_tokens?: number | null
}

interface FactsDto {
  project_id: string
  ai_call_audit_scope: "actor"
  counts: { evidence: number; operation_event: number; ai_call_audit: number }
  items: FactItem[]
  truncated: boolean
  limit: number
}

type FactFilter = "" | FactItem["fact_type"]

const FACT_TYPE_LABEL: Record<FactItem["fact_type"], string> = {
  evidence: "证据",
  operation_event: "操作",
  ai_call_audit: "AI 调用",
}

const FACT_TYPE_BADGE: Record<FactItem["fact_type"], string> = {
  evidence: "badge success",
  operation_event: "badge info",
  ai_call_audit: "badge warning",
}

const AI_STATUS_LABEL: Record<string, string> = {
  succeeded: "成功",
  failed: "失败",
  budget_blocked: "预算拦截",
}

const EVIDENCE_KIND_LABEL: Record<string, string> = {
  gate: "门禁",
  task: "任务",
  guidance: "指引",
  research: "调研",
  bridge: "集成桥",
  workflow: "工作流",
  solution: "方案",
}

function errorMessage(caught: unknown): string {
  if (caught instanceof ApiClientError) return caught.message
  if (caught instanceof Error) return caught.message
  return "加载失败，请重试。"
}

function timeOf(item: FactItem): string {
  return item.occurred_at ?? item.created_at ?? ""
}

function formatTime(value: string): string {
  if (!value) return "—"
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function shortHash(value: string | undefined): string {
  return value ? `${value.slice(0, 12)}…` : "—"
}

function factLine(item: FactItem): { title: string; meta: string } {
  if (item.fact_type === "evidence") {
    const parts = [
      EVIDENCE_KIND_LABEL[item.kind ?? ""] ?? item.kind ?? "—",
      item.source_uri ?? "—",
      `sha256 ${shortHash(item.content_sha256)}`,
    ]
    if (item.captured_from) parts.push(`来源 ${item.captured_from}`)
    if (item.origin) parts.push(item.origin)
    return { title: parts[0], meta: parts.slice(1).join(" · ") }
  }
  if (item.fact_type === "operation_event") {
    return {
      title: item.event_type ?? "—",
      meta: `${item.target_type ?? "—"}/${item.target_id ?? "—"}`,
    }
  }
  const parts = [item.purpose ?? "—", `${item.duration_ms ?? 0}ms`]
  if (item.input_tokens != null || item.output_tokens != null) {
    parts.push(`tokens ${item.input_tokens ?? "?"}/${item.output_tokens ?? "?"}`)
  }
  if (item.error_code) parts.push(item.error_code)
  if (item.used_fallback) parts.push("降级腿")
  return {
    title: item.model ?? "—",
    meta: `${AI_STATUS_LABEL[item.status ?? ""] ?? item.status ?? "—"} · ${parts.join(" · ")}`,
  }
}

export function ExecutionFactChain({ projectId }: { projectId: string }) {
  const { apiRequest } = useAuth()
  const [facts, setFacts] = useState<FactsDto | null>(null)
  const [filter, setFilter] = useState<FactFilter>("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  // CR-035 同款序列号守卫：筛选切换的并发响应只认最新一次。
  const sequence = useRef(0)
  const loadedOnce = useRef(false)

  const load = useCallback(async () => {
    const requestSequence = ++sequence.current
    setError("")
    try {
      const query = filter ? `?fact_type=${encodeURIComponent(filter)}` : ""
      const data = await apiRequest<FactsDto>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/execution-facts${query}`,
        { method: "GET" },
      )
      if (requestSequence !== sequence.current) return
      setFacts(data)
    } catch (caught) {
      if (requestSequence !== sequence.current) return
      setError(errorMessage(caught))
    } finally {
      if (requestSequence === sequence.current) {
        setLoading(false)
        loadedOnce.current = true
      }
    }
  }, [apiRequest, projectId, filter])

  useEffect(() => {
    void load()
    return () => {
      sequence.current += 1
    }
  }, [load])

  const filters: Array<{ key: FactFilter; label: string }> = [
    { key: "", label: "全部" },
    { key: "evidence", label: "证据" },
    { key: "operation_event", label: "操作" },
    { key: "ai_call_audit", label: "AI 调用" },
  ]

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>执行事实链</h2>
            <p>
              三源只读时间线（证据 / 操作 / AI 调用）；外部完成但无真实回执的事项呈现为
              「无记录」，模型自述不作完成证据。AI 调用流为账号维度（该账本无项目外键）。
            </p>
          </div>
          <div className="row-actions">
            {filters.map((entry) => (
              <button
                key={entry.key || "all"}
                type="button"
                className={filter === entry.key ? "primary-button" : "secondary-button"}
                onClick={() => setFilter(entry.key)}
              >
                {entry.label}
              </button>
            ))}
          </div>
        </div>
        {loading && !loadedOnce.current ? (
          <p className="empty-copy" role="status">正在加载执行事实…</p>
        ) : null}
        {error ? (
          <p className="empty-copy" role="alert">{error}</p>
        ) : null}
        {!error && facts ? (
          <>
            <p className="muted">
              共 {facts.counts.evidence} 条证据 · {facts.counts.operation_event} 条操作 ·{" "}
              {facts.counts.ai_call_audit} 条 AI 调用
              {facts.truncated ? `（已截断，显示最新 ${facts.limit} 条）` : ""}
            </p>
            {facts.items.length === 0 ? (
              <p className="empty-state">
                无记录——外部完成但无真实回执的事项不会在此编造展示
              </p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">类型</th>
                    <th scope="col">内容</th>
                    <th scope="col">时间</th>
                  </tr>
                </thead>
                <tbody>
                  {facts.items.map((item) => {
                    const line = factLine(item)
                    return (
                      <Fragment key={`${item.fact_type}-${item.id}`}>
                        <tr>
                          <td>
                            <span className={FACT_TYPE_BADGE[item.fact_type]}>
                              {FACT_TYPE_LABEL[item.fact_type]}
                            </span>
                            {item.fact_type === "ai_call_audit" ? (
                              <span className="badge muted">账号维度</span>
                            ) : null}
                          </td>
                          <td>
                            <strong>{line.title}</strong>
                            {line.meta ? (
                              <>
                                <br />
                                <span className="muted">{line.meta}</span>
                              </>
                            ) : null}
                          </td>
                          <td>{formatTime(timeOf(item))}</td>
                        </tr>
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            )}
          </>
        ) : null}
      </section>
    </div>
  )
}
