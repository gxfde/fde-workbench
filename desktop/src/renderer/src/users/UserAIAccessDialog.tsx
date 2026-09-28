import { useEffect, useState } from "react"
import { aiAccessLabels, aiCapabilityLabels } from "../ai/accessLabels"
import { useAuth } from "../auth/AuthProvider"

interface Access { level: string; capabilities: string[]; locked: boolean }
export function UserAIAccessDialog({ userId, name, onClose }: { userId: string; name: string; onClose(): void }) {
  const { apiRequest } = useAuth()
  const [access, setAccess] = useState<Access | null>(null)
  const [level, setLevel] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let active = true
    void apiRequest<Access>(`/api/v1/users/${userId}/ai-access`, { method: "GET" }).then((value) => { if (active) { setAccess(value); setLevel(value.level) } }).catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : "权限加载失败。") })
    return () => { active = false }
  }, [userId])
  async function save(): Promise<void> {
    if (busy || !access) return
    setBusy(true); setError("")
    try { await apiRequest(`/api/v1/users/${userId}/ai-access`, { method: "PATCH", body: { level } }); onClose() }
    catch (caught) { setError(caught instanceof Error ? caught.message : "权限保存失败。") }
    finally { setBusy(false) }
  }
  const summaries: Record<string, string> = {
    disabled: "不能发起 AI 对话或 AI 自动任务。",
    assistant_read: "可查看、检索和总结自己有权访问的项目资料。",
    project_operator: "在只读能力上，可生成调研和机会草稿、编辑个人笔记、更新自己的任务。",
    project_manager: "在项目操作能力上，可管理自己有管理权限的项目排期、成员、共享纪要与任务分配。",
    system_operator: "具备全部 AI 能力，包括公共扩展、系统运行情况与运维管理；高风险工具执行仍遵守确认规则。",
  }
  return <div className="dialog-backdrop"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="user-ai-access-title" onKeyDown={(event) => { if (event.key === "Escape" && !busy) onClose() }}><h2 id="user-ai-access-title">{name} 的 AI 权限</h2>{error ? <p className="form-error" role="alert">{error}</p> : null}{access ? <form onSubmit={(event) => { event.preventDefault(); void save() }}><label className="field"><span>AI 权限级别</span><select autoFocus aria-label="AI 权限级别" value={level} disabled={access.locked || busy} onChange={(event) => setLevel(event.target.value)}>{Object.entries(aiAccessLabels).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label><p className="supporting-copy">{summaries[level]}</p>{access.locked ? <p>管理员始终拥有完全权限。若需限制，请先调整账号角色。</p> : null}<details><summary>当前已生效能力</summary><ul>{access.capabilities.map((capability) => <li key={capability}>{aiCapabilityLabels[capability] || "扩展能力"}</li>)}</ul></details><div className="dialog-actions"><button className="secondary-button" disabled={busy} type="button" onClick={onClose}>关闭</button>{!access.locked ? <button className="primary-button" disabled={busy} type="submit">保存 AI 权限</button> : null}</div></form> : <><p role="status">正在加载 AI 权限…</p><button className="secondary-button" onClick={onClose}>关闭</button></>}</section></div>
}
