import { useEffect, useRef, useState } from "react"
import { useAuth } from "../auth/AuthProvider"

type Action = { id: string; description: string; operation: string; parameters: Record<string, string>; body: Record<string, unknown> }

export function AIActionConfirmation() {
  const { apiRequest, user } = useAuth()
  const [actions, setActions] = useState<Action[]>([])
  const [password, setPassword] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const mounted = useRef(true)
  const current = actions[0]
  useEffect(() => {
    mounted.current = true
    let active = true
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      try {
        const data = await apiRequest<{ items: Action[] }>("/api/v1/ai/actions", { method: "GET" })
        if (active && Array.isArray(data.items)) setActions(data.items.filter(item => typeof item.id === "string" && typeof item.description === "string"))
      } catch { /* Do not interrupt the app when no confirmation can be loaded. */ }
      if (active) timer = setTimeout(() => { void poll() }, 2500)
    }
    if (user) void poll()
    return () => { active = false; mounted.current = false; clearTimeout(timer) }
  }, [apiRequest, user?.id])
  useEffect(() => { setPassword(""); setError("") }, [current?.id])
  async function decide(approve: boolean) {
    if (!current || busy) return
    setBusy(true); setError("")
    const identifier = current.id
    try {
      const result = await apiRequest<{ status: string }>(`/api/v1/ai/actions/${identifier}/decision`, { method: "POST", body: { approve, ...(approve ? { password } : {}) } })
      if (!mounted.current) return
      setPassword("")
      setActions(items => items.filter(item => item.id !== identifier))
      if (result.status === "failed" || result.status === "uncertain") window.alert("操作未确认完成，请查询目标的最新状态，避免重复执行。")
    } catch (caught) {
      if (mounted.current) { setPassword(""); setError(caught instanceof Error ? caught.message : "确认失败，请重试。") }
    } finally { if (mounted.current) setBusy(false) }
  }
  if (!current || !user) return null
  return <div className="dialog-backdrop" style={{ zIndex: 1600 }}>
    <section className="dialog extension-dialog" role="dialog" aria-modal="true" aria-labelledby="ai-action-confirm-title" onKeyDown={event => {
      if (event.key !== "Tab") return
      const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("input,button")).filter(item => !item.hasAttribute("disabled"))
      if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1)?.focus() }
      else if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0]?.focus() }
    }}>
      <h2 id="ai-action-confirm-title">确认 AI 敏感操作</h2><p>{current.description}</p>
      <p>操作尚未执行。请核对目标和内容，密码只用于服务端验证，不会发送给 AI。</p>
      <details><summary>查看操作目标与内容</summary><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 220, overflow: "auto" }}>{JSON.stringify({ 目标: current.parameters, 内容: current.body }, null, 2)}</pre></details>
      <form onSubmit={event => { event.preventDefault(); void decide(true) }}>
        <label className="field"><span>当前账号密码</span><input key={current.id} autoFocus type="password" autoComplete="current-password" required value={password} disabled={busy} onChange={event => setPassword(event.target.value)} /></label>
        {error ? <p role="alert" className="form-error">{error}</p> : null}
        <div className="dialog-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => { void decide(false) }}>取消操作</button><button className="danger-button" type="submit" disabled={busy || !password}>{busy ? "正在验证…" : "验证并执行"}</button></div>
      </form>
    </section>
  </div>
}
