import { useEffect, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { aiAccessLabels, aiCapabilityLabels } from "../ai/accessLabels"
import "./account-weixin.css"

interface AccountSummary {
  user: { id: string; username: string; display_name: string; role: string; is_active: boolean }
  ai_access: { level: string; source: string; capabilities: string[]; system_operations_explicit_only: boolean }
  wechat_clawbot: WechatBinding
}

interface WechatBinding {
  id?: string
  status: string
  channel: string
  display_name?: string
  commands_enabled: boolean
  notifications_enabled: boolean
  binding_expires_at?: string | null
  last_seen_at?: string | null
  binding_code?: string
  login_status?: string
  login_id?: string
  qr_image?: string
  enabled?: boolean
  connected?: boolean
  last_error_code?: string
}

const roleLabels: Record<string, string> = {
  admin: "管理员",
  project_lead: "项目负责人",
  fde_engineer: "FDE 工程师",
  viewer: "查看者",
}

export function AccountPage() {
  const { apiRequest, changePassword, updateDisplayName } = useAuth()
  const [account, setAccount] = useState<AccountSummary | null>(null)
  const [displayName, setDisplayName] = useState("")
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [qrImage, setQrImage] = useState("")
  const [loginId, setLoginId] = useState("")
  const [verifyCode, setVerifyCode] = useState("")
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState("")
  const [error, setError] = useState("")

  async function load(): Promise<void> {
    try {
      const data = await apiRequest<AccountSummary>("/api/v1/account", { method: "GET" })
      setAccount(data)
      setDisplayName(data.user.display_name)
      const binding = await apiRequest<WechatBinding>("/api/v1/account/wechat-clawbot/qr", { method: "GET" })
      setAccount((current) => current ? { ...current, wechat_clawbot: binding } : current)
    } catch (caught) {
      setError(messageOf(caught))
    }
  }

  useEffect(() => { void load() }, [])

  const loginStatus = account?.wechat_clawbot.login_status
  useEffect(() => {
    if (!loginId || !["wait", "scaned", "scaned_but_redirect"].includes(loginStatus ?? "")) return
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    async function poll(): Promise<void> {
      try {
        const data = await apiRequest<WechatBinding>("/api/v1/account/wechat-clawbot/qr/poll", { method: "POST", body: { login_id: loginId } })
        if (disposed) return
        setAccount((current) => current ? { ...current, wechat_clawbot: data } : current)
        if (data.login_status === "confirmed") { setQrImage(""); setLoginId(""); setNotice("微信已绑定，可以向 ClawBot 发送文字指令了。"); return }
        if (["wait", "scaned", "scaned_but_redirect"].includes(data.login_status ?? "")) timer = setTimeout(() => void poll(), 1500)
      } catch (caught) { if (!disposed) { setError(messageOf(caught)); setLoginId("") } }
    }
    timer = setTimeout(() => void poll(), 1000)
    return () => { disposed = true; clearTimeout(timer) }
  }, [apiRequest, loginId, loginStatus])

  async function saveProfile(): Promise<void> {
    setBusy(true); setError(""); setNotice("")
    try {
      const data = await apiRequest<AccountSummary["user"]>("/api/v1/account/profile", { method: "PATCH", body: { display_name: displayName } })
      updateDisplayName(data.display_name)
      setAccount((current) => current ? { ...current, user: data } : current)
      setNotice("个人资料已保存。")
    } catch (caught) { setError(messageOf(caught)) } finally { setBusy(false) }
  }

  async function savePassword(): Promise<void> {
    if (newPassword !== confirmPassword) { setError("两次输入的新密码不一致。"); return }
    setBusy(true); setError(""); setNotice("")
    try {
      await changePassword(currentPassword, newPassword)
      setCurrentPassword(""); setNewPassword(""); setConfirmPassword("")
      setNotice("密码已修改。")
    } catch (caught) { setError(messageOf(caught)) } finally { setBusy(false) }
  }

  async function beginBinding(): Promise<void> {
    setBusy(true); setError(""); setNotice("")
    try {
      const data = await apiRequest<WechatBinding>("/api/v1/account/wechat-clawbot/qr", { method: "POST", body: {} })
      setQrImage(data.qr_image ?? "")
      setLoginId(data.login_id ?? "")
      setVerifyCode("")
      setAccount((current) => current ? { ...current, wechat_clawbot: data } : current)
      setNotice("请用手机微信扫描二维码，并在手机上确认连接。二维码 5 分钟内有效。")
    } catch (caught) { setError(messageOf(caught)) } finally { setBusy(false) }
  }

  async function submitVerification(): Promise<void> {
    setBusy(true); setError("")
    try {
      const data = await apiRequest<WechatBinding>("/api/v1/account/wechat-clawbot/qr/poll", { method: "POST", body: { login_id: loginId, verify_code: verifyCode } })
      setAccount((current) => current ? { ...current, wechat_clawbot: data } : current)
      setVerifyCode("")
      if (data.login_status === "confirmed") { setQrImage(""); setLoginId(""); setNotice("微信已绑定，可以向 ClawBot 发送文字指令了。") }
      else if (data.login_status === "need_verifycode") setError("数字不匹配，请重新输入手机微信显示的验证码。")
    } catch (caught) { setError(messageOf(caught)) } finally { setBusy(false) }
  }

  async function removeBinding(): Promise<void> {
    setBusy(true); setError("")
    try {
      const data = await apiRequest<WechatBinding>("/api/v1/account/wechat-clawbot/qr/unbind", { method: "POST", body: {} })
      setAccount((current) => current ? { ...current, wechat_clawbot: data } : current)
      setQrImage(""); setLoginId(""); setNotice("已解除工作台微信连接，服务器已清除登录凭据。")
    } catch (caught) { setError(messageOf(caught)) } finally { setBusy(false) }
  }

  if (!account && !error) return <section className="page account-page"><p role="status">正在加载个人与安全中心…</p></section>

  return <section className="page account-page">
    <header className="page-heading"><div><p className="eyebrow">账户设置</p><h1>个人与安全中心</h1><p>管理个人资料、密码、AI Server 权限和微信 ClawBot 绑定。</p></div></header>
    {notice ? <p className="notice" role="status">{notice}</p> : null}
    {error ? <p className="form-error banner" role="alert">{error}</p> : null}
    {account ? <div className="account-grid">
      <section className="panel account-card"><h2>个人资料</h2><div className="account-meta"><span>登录名</span><strong>{account.user.username}</strong><span>系统角色</span><strong>{roleLabels[account.user.role] ?? account.user.role}</strong></div><label className="field"><span>显示名称</span><input value={displayName} maxLength={120} onChange={(event) => setDisplayName(event.target.value)} /></label><div className="dialog-actions"><button className="primary-button" type="button" disabled={busy || !displayName.trim()} onClick={() => void saveProfile()}>保存个人资料</button></div></section>
      <section className="panel account-card"><h2>密码与登录安全</h2><label className="field"><span>当前密码</span><input type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} /></label><label className="field"><span>新密码</span><input type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /></label><label className="field"><span>确认新密码</span><input type="password" autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} /></label><div className="dialog-actions"><button className="secondary-button" type="button" disabled={busy || !currentPassword || !newPassword || !confirmPassword} onClick={() => void savePassword()}>修改密码</button></div></section>
      <section className="panel account-card"><div className="account-card-heading"><div><h2>AI Server 权限</h2><p>权限会同时约束桌面端、微信和定时任务。</p></div><span className="permission-badge">{aiAccessLabels[account.ai_access.level] ?? "未开通"}</span></div><p className="security-callout">{account.user.role === "admin" ? "管理员拥有完整管理权限；发布、迁移等高风险操作仍需确认。" : "管理员可以为每个账户分配 AI 权限，项目数据仍按项目成员权限隔离。"}</p><ul className="capability-list">{account.ai_access.capabilities.map((item) => <li key={item}>{aiCapabilityLabels[item] ?? "其他已授权能力"}</li>)}</ul></section>
      <section className="panel account-card">
        <div className="account-card-heading"><div><h2>微信 ClawBot</h2><p>用手机微信扫码连接，随时向 AI Server 下达工作台指令。</p></div><span className={`channel-status ${account.wechat_clawbot.status}`}>{bindingStatus(account.wechat_clawbot.status)}</span></div>
        {qrImage && !["expired", "verify_code_blocked"].includes(loginStatus ?? "") ? <div className="weixin-qr"><img src={qrImage} alt="微信 ClawBot 官方登录二维码" width="220" height="220" /><strong>{loginStatus === "scaned" ? "已扫码，请在手机微信上确认" : "请使用手机微信扫一扫"}</strong><small>二维码由微信官方服务签发，仅用于绑定当前工作台账户。</small></div> : null}
        {loginStatus === "need_verifycode" ? <div className="weixin-verify"><label className="field"><span>手机微信显示的数字验证码</span><input inputMode="numeric" autoComplete="one-time-code" maxLength={12} value={verifyCode} onChange={(event) => setVerifyCode(event.target.value.replace(/\D/g, ""))} /></label><button className="primary-button" disabled={busy || verifyCode.length < 4} onClick={() => void submitVerification()}>确认验证码</button></div> : null}
        {loginStatus === "expired" || loginStatus === "verify_code_blocked" ? <p className="security-callout" role="status">{loginStatus === "expired" ? "二维码已过期，请重新获取后扫码。" : "验证码错误次数过多，请重新获取二维码。"}</p> : null}
        {!account.wechat_clawbot.enabled ? <p className="security-callout">微信扫码服务暂未启用。启用后会显示微信官方二维码，不再使用一次性绑定码。</p> : null}
        {account.wechat_clawbot.last_error_code === "weixin_session_expired" ? <p className="form-error">微信登录已失效，请重新扫码。</p> : null}
        {account.wechat_clawbot.connected ? <p className="security-callout">已绑定当前账户。仅接受扫码者本人的文字指令，使用当前账户的 AI 与项目权限。</p> : null}
        <div className="dialog-actions">{account.wechat_clawbot.connected ? <button className="secondary-button" type="button" disabled={busy} onClick={() => void removeBinding()}>解除绑定</button> : null}<button className="primary-button" type="button" disabled={busy || account.wechat_clawbot.enabled === false} onClick={() => void beginBinding()}>{qrImage ? "重新获取二维码" : account.wechat_clawbot.connected ? "重新扫码绑定" : "微信扫码绑定"}</button></div>
      </section>
    </div> : null}
  </section>
}

function bindingStatus(status: string): string { return ({ unbound: "未绑定", pending: "等待扫码", active: "已绑定", paused: "已暂停", revoked: "已解除" } as Record<string, string>)[status] ?? "未绑定" }
function messageOf(error: unknown): string { return error instanceof ApiClientError || error instanceof Error ? error.message : "操作失败，请稍后重试。" }
