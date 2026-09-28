import { useEffect, useState } from "react"
import { useAuth } from "../auth/AuthProvider"
import type { ModelPreference } from "./ExtensionsPage"

const empty = { name: "", provider: "deepseek", base_url: "https://api.deepseek.com", model: "deepseek-v4-pro", api_key: "", is_default: true, supports_tools: true }

export function ModelPreferencesPanel({ items, canManage, credentialsReady, onSaved }: { items: ModelPreference[]; canManage: boolean; credentialsReady: boolean; onSaved(): Promise<void> }) {
  const { apiRequest } = useAuth()
  const [deleting, setDeleting] = useState<ModelPreference | null>(null)
  const [password, setPassword] = useState("")
  const [editing, setEditing] = useState(false)
  const [original, setOriginal] = useState<ModelPreference | null>(null)
  const [scope, setScope] = useState<"personal" | "public">("personal")
  const [draft, setDraft] = useState(empty)
  const [lockedJev, setLockedJev] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const isJev = draft.provider.trim().toLowerCase() === "typesafe"
  function close(): void { if (!busy) { setEditing(false); setDeleting(null); setPassword(""); setDraft(empty); setLockedJev(false) } }
  useEffect(() => {
    const handler = (event: KeyboardEvent) => { if (event.key === "Escape") close() }
    if (editing || deleting) window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [editing, deleting, busy])
  function open(item?: ModelPreference): void {
    setOriginal(item || null); setScope(item?.scope || "personal")
    setLockedJev(item?.provider === "typesafe")
    setDraft(item ? { name: item.name, provider: item.provider, base_url: item.base_url, model: item.model, api_key: "", is_default: item.is_default, supports_tools: item.supports_tools } : empty)
    setEditing(true); setError("")
  }
  function openJev(): void {
    setOriginal(null); setScope("personal")
    setLockedJev(true)
    setDraft({ name: "Jev 立创查询", provider: "typesafe", base_url: "https://api.typesafe.ai/v1", model: "jev-1.13.0", api_key: "", is_default: false, supports_tools: false })
    setEditing(true); setError("")
  }
  async function save(): Promise<void> {
    if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await apiRequest("/api/v1/extensions/model-preferences", { method: "POST", body: { ...draft,
        ...(isJev ? { provider: "typesafe", model: "jev-1.13.0", base_url: "https://api.typesafe.ai/v1", is_default: false, supports_tools: false } : {}),
        scope, ...(original ? { id: original.id, version: original.version } : {}) } })
      setDraft(empty); setEditing(false); setNotice("模型已保存，API Key 在服务端加密存储，不会回显。")
      await onSaved()
    } catch (caught) { setError(caught instanceof Error ? caught.message : "模型保存失败。") } finally { setBusy(false) }
  }
  async function remove(item: ModelPreference): Promise<void> {
    if (busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      await apiRequest(`/api/v1/extensions/model-preferences/${item.id}`, { method: "DELETE", body: { password } })
      setDeleting(null); setPassword("")
      setNotice("模型配置已删除，已保存的项目资料不受影响。")
      await onSaved()
    } catch (caught) { setError(caught instanceof Error ? caught.message : "删除失败。") } finally { setBusy(false) }
  }
  return <>
    <div className="panel-heading"><div><h2>模型与 API Key</h2><p>每个人可以配置自己的模型；Jev 凭据仅用于立创 Skill 判断，不会替换对话默认模型。</p></div><div className="extension-heading-actions"><button className="secondary-button" onClick={openJev}>添加 Jev 凭据</button><button className="primary-button" onClick={() => open()}>添加模型</button></div></div>
    {!credentialsReady ? <p className="market-warning">服务器尚未完成密钥加密配置，暂不能保存 API Key。</p> : null}
    {error && !editing ? <p className="form-error" role="alert">{error}</p> : null}{notice ? <p className="notice" role="status">{notice}</p> : null}
    <div className="extension-card-grid model-card-grid">{items.map((item) => <article className="extension-item" key={item.id}><div><strong>{item.name}</strong><span className="extension-scope">{item.scope === "public" ? "公共" : "个人"}</span>{item.is_default ? <span className="verified-badge">默认</span> : null}</div><p>{item.provider} · {item.model}</p><small>{item.base_url}</small><p className="model-key-state">API Key：{item.credential_configured ? "已加密保存，不回显" : "未配置"}</p>{item.can_edit ? <div className="plugin-actions"><button className="secondary-button" disabled={busy} onClick={() => open(item)}>编辑</button><button className="secondary-button" disabled={busy} onClick={() => { setDeleting(item); setPassword(""); setError("") }}>删除配置</button></div> : null}</article>)}</div>
    {!items.length ? <p className="empty-copy">尚未添加模型。可以使用服务端已配置的默认模型，或添加自己的模型和 API Key。</p> : null}
    {editing ? <div className="dialog-backdrop"><section className="dialog extension-dialog model-editor-dialog" role="dialog" aria-modal="true" aria-labelledby="model-editor-title"><h2 id="model-editor-title">{isJev ? original ? "编辑 Jev 凭据" : "添加 Jev 凭据" : original ? "编辑模型" : "添加模型"}</h2><form onSubmit={(event) => { event.preventDefault(); void save() }}><div className="skill-editor">
      <label className="field"><span>显示名称</span><input aria-label="模型名称" autoFocus required value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
      <label className="field"><span>使用范围</span><select aria-label="模型使用范围" disabled={!!original} value={scope} onChange={(event) => setScope(event.target.value as "personal" | "public")}><option value="personal">个人模型（仅自己）</option>{canManage ? <option value="public">公共模型（所有账号）</option> : null}</select></label>
      <label className="field"><span>供应商</span><input aria-label="模型供应商" list="model-provider-options" required readOnly={lockedJev} value={draft.provider} onChange={(event) => { const provider = event.target.value; setDraft(provider.trim().toLowerCase() === "typesafe" ? { ...draft, provider: "typesafe", model: "jev-1.13.0", base_url: "https://api.typesafe.ai/v1", is_default: false, supports_tools: false } : { ...draft, provider }) }} /></label>
      <label className="field"><span>模型标识</span><input aria-label="模型标识" list="model-id-options" required readOnly={isJev} value={draft.model} onChange={(event) => setDraft({ ...draft, model: event.target.value })} /></label>
      <label className="field full"><span>API 地址</span><input aria-label="模型 API 地址" required type="url" readOnly={isJev} value={draft.base_url} onChange={(event) => setDraft({ ...draft, base_url: event.target.value })} /></label>
      <label className="field full"><span>API Key</span><input aria-label="API Key" type="password" autoComplete="new-password" required={!original} placeholder={original ? "留空保留现有密钥" : "输入模型供应商提供的 API Key"} value={draft.api_key} onChange={(event) => setDraft({ ...draft, api_key: event.target.value })} /><small>传输后在服务端加密保存，之后不会回显原始密钥。</small></label>
      {isJev ? <p className="jev-config-hint">Jev 仅供立创 Skill 判断，不是对话模型；以下两项已固定关闭。</p> : null}
      <label className="research-check"><input type="checkbox" disabled={isJev} checked={isJev ? false : draft.is_default} onChange={(event) => setDraft({ ...draft, is_default: event.target.checked })} />设为该范围的默认模型</label>
      <label className="research-check"><input type="checkbox" disabled={isJev} checked={isJev ? false : draft.supports_tools} onChange={(event) => setDraft({ ...draft, supports_tools: event.target.checked })} />支持工具调用</label>
      <datalist id="model-provider-options"><option value="deepseek">DeepSeek</option><option value="openai-compatible">Kimi / OpenAI 兼容接口</option><option value="typesafe">TypeSafe Jev</option></datalist>
      <datalist id="model-id-options">{Array.from(new Set([...items.map(item => item.model), "deepseek-v4-pro", "deepseek-v4-flash", "kimi-k3", "jev-1.13.0"])).map(model => <option key={model} value={model} />)}</datalist>
    </div>{error ? <p className="form-error" role="alert">{error}</p> : null}<div className="dialog-actions"><button className="secondary-button" type="button" disabled={busy} onClick={close}>取消</button><button className="primary-button" type="submit" disabled={busy || !credentialsReady}>保存模型</button></div></form></section></div> : null}
    {deleting ? <div className="dialog-backdrop"><section className="dialog extension-dialog" role="dialog" aria-modal="true" aria-label="确认删除模型"><h2>删除模型配置</h2><p>将删除“{deleting.name}”及其保存的 API Key，已有项目资料不受影响。请输入当前登录账号的密码确认。</p><form onSubmit={event => { event.preventDefault(); void remove(deleting) }}><label className="field"><span>当前账号密码</span><input autoFocus required type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} /></label>{error ? <p role="alert" className="form-error">{error}</p> : null}<div className="dialog-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => { setDeleting(null); setPassword(""); setError("") }}>取消</button><button type="submit" className="danger-button" disabled={busy || !password}>确认删除</button></div></form></section></div> : null}
  </>
}
