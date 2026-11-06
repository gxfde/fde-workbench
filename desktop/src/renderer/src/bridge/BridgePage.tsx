import { useCallback, useEffect, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { commonErrorMessage } from "../common/errorMessages"

/** P2 集成桥：真相层（openfde 知识轨 / fdeops 流程轨）→ workbench 的只读投影。
 *  A1 铁律：文件永远赢——vanished 只清投影，绝不动真相文件。 */

interface BridgeLinkedProject {
  project_id: string
  project_name: string
}

interface BridgeEngagement {
  slug: string
  openfde_status: {
    episodes?: number | null
    pending?: number | null
    entities?: number | null
    active_facts?: number | null
    expired_facts?: number | null
    open_tasks?: number | null
    capture_error?: string
  } | null
  openfde_synced_at: string | null
  fdeops_state: { fde_initialized?: boolean; bound_path?: string | null; capture_error?: string } | null
  fdeops_synced_at: string | null
  linked_projects: BridgeLinkedProject[]
  flags: string[]
}

interface BridgeProjectAudit {
  project_id: string
  project_name: string
  enterprise_code: string
  openfde_engagement: string | null
  fdeops_workspace: string | null
  flags: string[]
}

interface BridgeRun {
  id: string
  trigger: string
  ok: boolean
  started_at: string
  finished_at: string | null
  engagements_seen: number
  error: string | null
}

interface BridgeView {
  captured_at: string | null
  stale_after_minutes?: number
  engagements: BridgeEngagement[]
  projects: BridgeProjectAudit[]
}

const FLAG_LABELS: Record<string, { label: string; tone: "warning" | "muted" }> = {
  vanished: { label: "文件已删", tone: "muted" },
  unlinked: { label: "未绑定项目", tone: "muted" },
  stale: { label: "采集断连", tone: "warning" },
  orphan_openfde: { label: "openfde 指针悬空", tone: "warning" },
  orphan_fdeops: { label: "fdeops 指针悬空", tone: "warning" },
  missing_openfde_pointer: { label: "缺 openfde 指位", tone: "warning" },
}

/**
 * 标记去重：服务端 flags 是「可重复出现的观察项」而非互斥枚举——同一行可能
 * 带重复的 flag（如双轨各自断连各报一次 stale）。直接 map 渲染会出现两个
 * 同名徽标，并因 key 重复触发 React 警告。故渲染前先按出现顺序去重。
 */
function uniqueFlags(flags: string[]): string[] {
  return flags.filter((flag, index) => flags.indexOf(flag) === index)
}

function isBridgeView(value: unknown): value is BridgeView {
  if (typeof value !== "object" || value === null) return false
  const record = value as Record<string, unknown>
  return Array.isArray(record.engagements) && Array.isArray(record.projects)
}

function formatTime(iso: string | null): string {
  if (!iso) return "—"
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString("zh-CN", { hour12: false })
}

function errorMessage(caught: unknown): string {
  // S2 / F4：公共错误码走统一表；未收录时保留服务端原文（已是面向用户的中文）。
  if (caught instanceof ApiClientError) {
    return commonErrorMessage(caught, "") || caught.message || "请求失败"
  }
  return caught instanceof Error ? caught.message : "请求失败"
}

export function BridgePage() {
  const { apiRequest, user } = useAuth()
  const canManage = user?.role === "admin" || user?.role === "project_lead"
  const [view, setView] = useState<BridgeView | null>(null)
  const [runs, setRuns] = useState<BridgeRun[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState("")
  const requestSequence = useRef(0)
  const captureTimer = useRef<number | null>(null)

  useEffect(
    () => () => {
      if (captureTimer.current !== null) window.clearInterval(captureTimer.current)
    },
    [],
  )

  const load = useCallback(() => {
    const sequence = ++requestSequence.current
    setLoading(true)
    setError("")
    void Promise.all([
      apiRequest<unknown>("/api/v1/bridge/engagements", { method: "GET" }),
      apiRequest<unknown>("/api/v1/bridge/status", { method: "GET" }),
    ])
      .then(([nextView, statusData]) => {
        if (sequence !== requestSequence.current) return
        if (!isBridgeView(nextView)) {
          setError("集成桥数据格式异常")
          return
        }
        setView(nextView)
        const nextRuns = (statusData as { runs?: unknown } | null)?.runs
        setRuns(Array.isArray(nextRuns) ? (nextRuns as BridgeRun[]).slice(0, 5) : [])
      })
      .catch((caught) => {
        if (sequence !== requestSequence.current) return
        setError(errorMessage(caught))
      })
      .finally(() => {
        if (sequence === requestSequence.current) setLoading(false)
      })
  }, [apiRequest])

  useEffect(() => { load() }, [load])

  function reconcile(): void {
    setBusy("reconcile")
    void apiRequest<unknown>("/api/v1/bridge/reconcile", { method: "POST" })
      .then(() => load())
      .catch((caught) => setError(errorMessage(caught)))
      .finally(() => setBusy(""))
  }

  /** 手动采集：触发宿主计划任务，轮询到新 poller 快照后自动刷新本页。 */
  function captureNow(): void {
    setBusy("capture")
    setError("")
    const startedAt = Date.now() - 5_000
    const stopPolling = (): void => {
      if (captureTimer.current !== null) {
        window.clearInterval(captureTimer.current)
        captureTimer.current = null
      }
    }
    void window.fde.bridge.capture().then((result) => {
      if (!result.ok) {
        setError(result.error?.message || "触发宿主采集失败")
        setBusy("")
        return
      }
      const deadline = Date.now() + 180_000
      const checkForFreshRun = (): void => {
        void apiRequest<unknown>("/api/v1/bridge/status", { method: "GET" })
          .then((statusData) => {
            const runs = (statusData as { runs?: unknown } | null)?.runs
            const fresh = Array.isArray(runs)
              ? (runs as BridgeRun[]).some(
                  (run) =>
                    run.trigger === "poller" &&
                    Number.isFinite(Date.parse(run.started_at)) &&
                    Date.parse(run.started_at) > startedAt,
                )
              : false
            if (!fresh) return
            stopPolling()
            load()
            setBusy("")
          })
          .catch(() => { /* 单次轮询失败不中断等待 */ })
      }
      checkForFreshRun()
      captureTimer.current = window.setInterval(() => {
        if (Date.now() > deadline) {
          stopPolling()
          setError("已触发宿主采集，但 3 分钟内未见新快照——请检查宿主 logs/bridge-poll.log 与计划任务状态。")
          setBusy("")
          return
        }
        checkForFreshRun()
      }, 4_000)
    })
  }

  function clearProjection(slug: string): void {
    setBusy(`clear:${slug}`)
    void apiRequest<unknown>(`/api/v1/bridge/engagements/${encodeURIComponent(slug)}`, { method: "DELETE" })
      .then(() => load())
      .catch((caught) => setError(errorMessage(caught)))
      .finally(() => setBusy(""))
  }

  const anyStale = view?.engagements.some((item) => item.flags.includes("stale")) ?? false
  const orphanProjects = view?.projects.filter((item) => item.flags.length > 0) ?? []

  return (
    <div id="bridge-page" className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">集成桥（P2）</p>
          <h1>双轨状态</h1>
          <p className="supporting-copy">
            openfde 知识轨 + fdeops 流程轨 → 本页为只读投影；真相在文件，文件永远赢。
            采集节奏：宿主计划任务每 4 小时（bridge-poll.mjs），中途更新了真相文件可点「立即采集」。
            {view?.captured_at ? ` 最近采集：${formatTime(view.captured_at)}` : " 尚无采集记录"}
          </p>
        </div>
        <div className="page-header-actions">
          {canManage ? (
            <button
              className="secondary-button"
              type="button"
              disabled={loading || busy !== ""}
              title="触发宿主计划任务 FDE-Bridge-Poll 立即采集（新快照到站后本页自动刷新）"
              onClick={captureNow}
            >
              {busy === "capture" ? "采集中…" : "立即采集"}
            </button>
          ) : null}
          <button className="secondary-button" type="button" disabled={loading || busy !== ""} onClick={load}>刷新</button>
          {canManage ? (
            <button
              className="secondary-button"
              type="button"
              disabled={loading || busy !== "" || !view?.captured_at}
              title="用最近一次采集的快照重新投影（不触发宿主采集）"
              onClick={reconcile}
            >
              {busy === "reconcile" ? "重投影中…" : "重新投影"}
            </button>
          ) : null}
        </div>
      </header>

      {anyStale ? (
        <p className="empty-state">
          ⚠ 采集断连：超过 {view ? Math.round((view.stale_after_minutes ?? 360) / 60) : 6} 小时没有新快照
          （宿主计划任务或 WSL 服务可能停了），下表数据可能过期。
        </p>
      ) : null}
      {error ? <p className="empty-state" role="alert">{error}</p> : null}

      <section>
        <h2>Engagement 投影</h2>
        {loading && !view ? <p className="supporting-copy">加载中…</p> : null}
        {view && view.engagements.length === 0 ? (
          <p className="empty-state">还没有 engagement 投影——等宿主采集器跑一轮，或确认 FDE-Bridge-Poll 计划任务在位。</p>
        ) : null}
        {view && view.engagements.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>slug</th>
                <th>openfde 知识轨</th>
                <th>fdeops 流程轨</th>
                <th>关联项目</th>
                <th>标记</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {view.engagements.map((item) => (
                <tr key={item.slug} className={item.flags.includes("vanished") ? "bridge-vanished" : undefined}>
                  <td><strong>{item.slug}</strong></td>
                  <td>
                    {item.openfde_synced_at ? (
                      <>
                        {item.openfde_status?.entities ?? "—"} 实体 / {item.openfde_status?.active_facts ?? "—"} 活事实 / {item.openfde_status?.open_tasks ?? "—"} 开放任务
                        <br />
                        <span className="supporting-copy">采集 {formatTime(item.openfde_synced_at)}</span>
                      </>
                    ) : item.openfde_status?.capture_error ? (
                      <span className="supporting-copy">采集失败：{item.openfde_status.capture_error}</span>
                    ) : "—"}
                  </td>
                  <td>
                    {item.fdeops_synced_at ? (
                      <>
                        {item.fdeops_state?.fde_initialized ? ".fde 已初始化" : ".fde 未初始化"}
                        {item.fdeops_state?.bound_path ? <br /> : null}
                        {item.fdeops_state?.bound_path ? <span className="supporting-copy">{item.fdeops_state.bound_path}</span> : null}
                      </>
                    ) : "—"}
                  </td>
                  <td>
                    {item.linked_projects.length > 0
                      ? item.linked_projects.map((linked) => linked.project_name).join("、")
                      : "—"}
                  </td>
                  <td>
                    {uniqueFlags(item.flags).length > 0
                      ? uniqueFlags(item.flags).map((flag) => (
                          <span key={flag} className={`badge ${FLAG_LABELS[flag]?.tone ?? "muted"}`} style={{ marginRight: 4 }}>
                            {FLAG_LABELS[flag]?.label ?? flag}
                          </span>
                        ))
                      : <span className="badge success">正常</span>}
                  </td>
                  <td>
                    {canManage && item.flags.includes("vanished") ? (
                      <button
                        className="danger-button compact"
                        type="button"
                        disabled={busy !== ""}
                        onClick={() => clearProjection(item.slug)}
                      >
                        {busy === `clear:${item.slug}` ? "清理中…" : "清投影"}
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </section>

      <section>
        <h2>项目指位审计（§1 铁律 3：缺一指位即孤儿）</h2>
        {view && orphanProjects.length === 0 ? (
          <p className="empty-state">所有项目的 openfde / fdeops 指位均有效。</p>
        ) : null}
        {view && orphanProjects.length > 0 ? (
          <table>
            <thead>
              <tr><th>项目</th><th>客户代号</th><th>openfde 指针</th><th>fdeops 指针</th><th>标记</th></tr>
            </thead>
            <tbody>
              {orphanProjects.map((item) => (
                <tr key={item.project_id}>
                  <td><strong>{item.project_name}</strong></td>
                  <td>{item.enterprise_code}</td>
                  <td>{item.openfde_engagement ?? "（缺）"}</td>
                  <td>{item.fdeops_workspace ?? "（缺）"}</td>
                  <td>
                    {uniqueFlags(item.flags).map((flag) => (
                      <span key={flag} className={`badge ${FLAG_LABELS[flag]?.tone ?? "warning"}`} style={{ marginRight: 4 }}>
                        {FLAG_LABELS[flag]?.label ?? flag}
                      </span>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </section>

      <section>
        <h2>最近同步</h2>
        {runs.length === 0 ? <p className="supporting-copy">暂无运行记录。</p> : null}
        {runs.length > 0 ? (
          <table>
            <thead>
              <tr><th>时间</th><th>触发</th><th>结果</th><th>engagement</th><th>错误</th></tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td>{formatTime(run.started_at)}</td>
                  <td>{run.trigger === "poller" ? "宿主采集" : "手动重投影"}</td>
                  <td>{run.ok ? <span className="badge success">成功</span> : <span className="badge warning">失败</span>}</td>
                  <td>{run.ok ? run.engagements_seen : "—"}</td>
                  <td className="supporting-copy">{run.error ? run.error.slice(0, 120) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </section>
    </div>
  )
}
