import { useEffect, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"

// 智能体凭据管理面（E11 消费面，桌面第三批 ops3）：platform operator 专管。
// 服务端只存 Fernet 密文、绝不回显——任何序列化路径只出 credential_configured
// 布尔。凭据名会进沙箱 env（FDE_AGENT_<NAME>），与服务端同尺：^[A-Za-z0-9_]{1,120}$。
interface AgentCredentialDto {
  id: string
  name: string
  credential_configured: boolean
  created_by_user_id: string | null
  created_at: string
}

const CREDENTIAL_NAME_PATTERN = /^[A-Za-z0-9_]{1,120}$/
const PLAINTEXT_MAX_CHARS = 8000

function errorMessage(caught: unknown, fallback: string): string {
  if (caught instanceof ApiClientError) {
    if (caught.code === "forbidden") return "仅平台操作者可管理智能体凭据。"
    return caught.message
  }
  return caught instanceof Error ? caught.message : fallback
}

export function AgentCredentialsPanel() {
  const { apiRequest } = useAuth()
  const [items, setItems] = useState<AgentCredentialDto[] | null>(null)
  const [name, setName] = useState("")
  const [credential, setCredential] = useState("")
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")

  async function load(): Promise<void> {
    try {
      const rows = await apiRequest<AgentCredentialDto[]>("/api/v1/agents/credentials", { method: "GET" })
      setItems(Array.isArray(rows) ? rows : [])
    } catch (caught) {
      setItems([])
      setError(errorMessage(caught, "凭据清单加载失败，请稍后重试。"))
    }
  }
  useEffect(() => { void load() }, [])

  // 明文零驻留：提交入口 await 前与取消/收起时即清空明文 state——
  // 明文只在本次请求的内存 body 里出现一次。
  function clearPlaintext(): void {
    setName("")
    setCredential("")
  }

  async function save(): Promise<void> {
    if (busy) return
    setError(""); setNotice("")
    const trimmed = name.trim()
    if (!CREDENTIAL_NAME_PATTERN.test(trimmed)) {
      setError("凭据名只允许字母、数字与下划线，长度 1–120（例如 default）。")
      return
    }
    if (!credential) {
      setError("凭据明文不能为空。")
      return
    }
    if (credential.length > PLAINTEXT_MAX_CHARS) {
      setError(`凭据明文过长（上限 ${PLAINTEXT_MAX_CHARS} 字符）。`)
      return
    }
    setBusy(true)
    const payload = { name: trimmed, credential }
    clearPlaintext()
    try {
      await apiRequest<AgentCredentialDto>("/api/v1/agents/credentials", { method: "POST", body: payload })
      setNotice(`凭据「${trimmed}」已加密保存，不会回显。`)
      await load()
    } catch (caught) {
      setError(errorMessage(caught, "凭据保存失败，请稍后重试。"))
    } finally {
      setBusy(false)
    }
  }

  async function remove(target: string): Promise<void> {
    if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await apiRequest<{ deleted: string }>(`/api/v1/agents/credentials/${encodeURIComponent(target)}`, { method: "DELETE" })
      setNotice(`凭据「${target}」已删除。`)
      setConfirmDelete(null)
      await load()
    } catch (caught) {
      setError(errorMessage(caught, "凭据删除失败，请稍后重试。"))
    } finally {
      setBusy(false)
    }
  }

  return <>
    <div className="panel-heading"><div><h2>智能体凭据</h2><p>为智能体 run 注入的凭据槽（如 default）；服务端只存密文，绝不回显。凭据名会进入沙箱环境变量（FDE_AGENT_&lt;NAME&gt;）。</p></div></div>
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    {notice ? <p className="notice" role="status">{notice}</p> : null}
    <form className="page-stack" onSubmit={(event) => { event.preventDefault(); void save() }}>
      <div className="plugin-actions">
        <label className="field"><span>凭据名</span>
          <input aria-label="凭据名" placeholder="default" value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="field"><span>凭据明文</span>
          <input aria-label="凭据明文" type="password" autoComplete="new-password" value={credential} onChange={(event) => setCredential(event.target.value)} />
        </label>
      </div>
      <p className="field-hint">凭据名只允许字母、数字与下划线（1–120 位，例如 default）；明文非空且 ≤{PLAINTEXT_MAX_CHARS} 字符，提交前即从输入框清除。</p>
      <div className="plugin-actions">
        <button className="primary-button" type="submit" disabled={busy}>保存凭据</button>
        <button className="secondary-button" type="button" disabled={busy} onClick={() => { clearPlaintext(); setError(""); setNotice("") }}>清空</button>
      </div>
    </form>
    {items === null ? <p className="empty-copy" role="status">正在加载凭据清单…</p> : items.length ? (
      <div className="extension-card-grid">
        {items.map((item) => <article className="extension-item" key={item.id}>
          <div><strong>{item.name}</strong>{item.name === "default" ? <span className="extension-scope">默认槽</span> : null}</div>
          <small>凭据：{item.credential_configured ? "已加密保存，不回显" : "未配置"}{item.created_at ? ` · ${item.created_at.slice(0, 10)}` : ""}</small>
          <div className="plugin-actions">
            {confirmDelete === item.name ? <>
              <button className="danger-button" disabled={busy} onClick={() => void remove(item.name)}>确认删除</button>
              <button className="secondary-button" disabled={busy} onClick={() => setConfirmDelete(null)}>取消</button>
            </> : <button className="secondary-button" disabled={busy} onClick={() => { setConfirmDelete(item.name); setError(""); setNotice("") }}>删除</button>}
          </div>
        </article>)}
      </div>
    ) : <p className="empty-copy">还没有凭据。智能体发起 run 需要凭据槽（种子智能体引用 default）。</p>}
  </>
}
