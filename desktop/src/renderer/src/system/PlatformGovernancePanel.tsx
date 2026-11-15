import { useEffect, useState } from "react"

import { useAuth } from "../auth/AuthProvider"

// 运行治理卡（桌面第三批 ops3）：系统配置页 <form> 外下方的只读监控＋受控取消。
// 失败不阻保存——两路数据各自独立加载、各自呈现错误，绝不抛进页面级 error。
// ① 跨域到期投影（GET /api/v1/expirations?due=true，admin 只读）：域值域闭集
//    ＝服务端 expirations.EXPIRY_ACTIONS 四键；客户端按闭集防御性过滤。
// ② 队列计量（GET /api/v1/admin/jobs/metering，admin 只读）：queue_depth＋按
//    org_id 分组的 active/terminal 计数（org_id null＝平台级）。
// ③ 取消后台任务（POST /api/v1/admin/jobs/{id}/cancel）：两步确认；幂等
//    cancelled=false 不是错误，404/409（终态/运行中）原样呈现。
const EXPIRATION_DOMAIN_LABEL: Record<string, string> = {
  automation_approval: "自动化审批",
  api_confirmation: "AI 确认窗口",
  dispatch_offer: "派单报价窗口",
  upload_session: "上传会话",
}

interface ExpirationItem {
  domain: string
  object_id: string
  deadline_at: string
  state: string
  due: boolean
  expiry_action: string
}

interface ExpirationList {
  items: ExpirationItem[]
  total: number
}

interface JobGroup {
  org_id: string | null
  active: number
  terminal: number
}

interface JobMetering {
  groups: JobGroup[]
  queue_depth: number | null
}

interface CancelJobResult {
  job_id: string
  job_type: string
  status: string
  cancelled: boolean
}

function formatDeadline(iso: string): string {
  return iso.replace("T", " ").slice(0, 19)
}

export function PlatformGovernancePanel() {
  const { apiRequest } = useAuth()
  const [expirations, setExpirations] = useState<ExpirationList | null>(null)
  const [expirationError, setExpirationError] = useState("")
  const [metering, setMetering] = useState<JobMetering | null>(null)
  const [meteringError, setMeteringError] = useState("")
  const [jobId, setJobId] = useState("")
  const [confirming, setConfirming] = useState(false)
  const [cancelBusy, setCancelBusy] = useState(false)
  const [cancelError, setCancelError] = useState("")
  const [cancelNotice, setCancelNotice] = useState("")

  async function loadExpirations(): Promise<void> {
    setExpirationError("")
    try {
      const data = await apiRequest<ExpirationList>("/api/v1/expirations?due=true", { method: "GET" })
      setExpirations({
        items: (Array.isArray(data.items) ? data.items : []).filter((row) => row.domain in EXPIRATION_DOMAIN_LABEL),
        total: typeof data.total === "number" ? data.total : 0,
      })
    } catch (caught) {
      setExpirations(null)
      setExpirationError(caught instanceof Error ? caught.message : "到期事项加载失败，请稍后重试。")
    }
  }

  async function loadMetering(): Promise<void> {
    setMeteringError("")
    try {
      const data = await apiRequest<JobMetering>("/api/v1/admin/jobs/metering", { method: "GET" })
      setMetering({ groups: Array.isArray(data.groups) ? data.groups : [], queue_depth: typeof data.queue_depth === "number" ? data.queue_depth : null })
    } catch (caught) {
      setMetering(null)
      setMeteringError(caught instanceof Error ? caught.message : "队列计量加载失败，请稍后重试。")
    }
  }

  useEffect(() => {
    void loadExpirations()
    void loadMetering()
  }, [])

  async function cancelJob(): Promise<void> {
    const target = jobId.trim()
    if (!target || cancelBusy) return
    setCancelBusy(true); setCancelError(""); setCancelNotice("")
    try {
      const result = await apiRequest<CancelJobResult>(`/api/v1/admin/jobs/${encodeURIComponent(target)}/cancel`, { method: "POST" })
      setCancelNotice(result.cancelled ? `任务 ${target} 已取消。` : `任务 ${target} 已是取消态（幂等，未重复处理）。`)
      setJobId(""); setConfirming(false)
      await loadMetering()
    } catch (caught) {
      setCancelError(caught instanceof Error ? caught.message : "取消失败，请稍后重试。")
    } finally {
      setCancelBusy(false)
    }
  }

  return <>
    <section className="panel" role="region" aria-label="到期事项监控">
      <div className="panel-heading"><div><h2>到期事项</h2><p>跨域到期投影（仅已到期）：自动化审批 / AI 确认窗口 / 派单报价窗口 / 上传会话。只读监控，到期动作由服务端定时收口。</p></div></div>
      {expirationError ? <p className="form-error" role="alert">{expirationError}</p> : null}
      {expirations === null && !expirationError ? <p role="status">正在读取到期事项…</p> : null}
      {expirations !== null ? (expirations.items.length ? (
        <table className="data-table">
          <thead><tr><th scope="col">域</th><th scope="col">对象</th><th scope="col">截止时间</th><th scope="col">状态</th><th scope="col">到期动作</th></tr></thead>
          <tbody>
            {expirations.items.map((item) => (
              <tr key={`${item.domain}:${item.object_id}`}>
                <td>{EXPIRATION_DOMAIN_LABEL[item.domain] ?? item.domain}</td>
                <td><code>{item.object_id}</code></td>
                <td>{formatDeadline(item.deadline_at)}</td>
                <td>{item.state}{item.due ? " · 已到期" : ""}</td>
                <td><code>{item.expiry_action}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="empty-copy">没有已到期的事项。</p>) : null}
    </section>
    <section className="panel" role="region" aria-label="队列监控">
      <div className="panel-heading"><div><h2>队列监控</h2><p>后台任务按主体（组织/平台级）分组计量与取消：active＝pending/queued/running，terminal＝终态。取消是留痕操作；运行中（租约未过期）不强杀。</p></div></div>
      {meteringError ? <p className="form-error" role="alert">{meteringError}</p> : null}
      {metering === null && !meteringError ? <p role="status">正在读取队列计量…</p> : null}
      {metering !== null ? <>
        <p className="field-hint">Redis 队列深度：<strong>{metering.queue_depth ?? "—"}</strong>{metering.queue_depth === null ? "（未接入 Redis 或不可读）" : ""}</p>
        {metering.groups.length ? (
          <table className="data-table">
            <thead><tr><th scope="col">主体</th><th scope="col">进行中</th><th scope="col">终态</th></tr></thead>
            <tbody>
              {metering.groups.map((group) => (
                <tr key={group.org_id ?? "__platform__"}>
                  <td>{group.org_id ?? "平台级"}</td>
                  <td>{group.active}</td>
                  <td>{group.terminal}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="empty-copy">暂无后台任务。</p>}
      </> : null}
      {cancelError ? <p className="form-error" role="alert">{cancelError}</p> : null}
      {cancelNotice ? <p className="notice" role="status">{cancelNotice}</p> : null}
      <form className="page-stack" onSubmit={(event) => { event.preventDefault(); if (confirming) void cancelJob() }}>
        <div className="plugin-actions">
          <label className="field"><span>任务 ID</span>
            <input aria-label="任务 ID" placeholder="job_id" value={jobId} onChange={(event) => { setJobId(event.target.value); setConfirming(false) }} />
          </label>
          {confirming ? <>
            <button type="button" className="danger-button" disabled={cancelBusy || !jobId.trim()} onClick={() => void cancelJob()}>确认取消 {jobId.trim()}</button>
            <button type="button" className="secondary-button" disabled={cancelBusy} onClick={() => setConfirming(false)}>再想想</button>
          </> : <button type="button" className="secondary-button" disabled={!jobId.trim() || cancelBusy} onClick={() => setConfirming(true)}>取消任务</button>}
        </div>
        <p className="field-hint">先填任务 ID 再两步确认；终态任务（已成功/已失败）与执行中的任务会被服务端 409 拒绝。</p>
      </form>
    </section>
  </>
}
