import { useEffect, useRef, useState, type FormEvent } from "react"

import { PASSWORD_MAX_LENGTH, USERNAME_MAX_LENGTH } from "../../../shared/contracts"
import { DEVICE_LABEL, PRODUCT_NAME } from "../../../shared/brand"
import { AuthUiError, useAuth } from "./AuthProvider"
import logoMark from "../assets/logo-caigong-fde-light.svg"

const LAST_USERNAME_KEY = "fde:last-username:v1"

export function LoginPage() {
  const { login } = useAuth()
  const [username, setUsername] = useState(readLastUsername)
  const [password, setPassword] = useState("")
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const usernameRef = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)
  const passwordFocusPending = useRef(false)

  useEffect(() => {
    if (username) passwordRef.current?.focus()
  }, [])

  // After a failed submit, focus the password field once the controls re-enable.
  // This never steals focus while the user is typing the username.
  useEffect(() => {
    if (passwordFocusPending.current && !submitting) {
      passwordFocusPending.current = false
      passwordRef.current?.focus()
    }
  }, [error, submitting])

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault()
    setError("")
    if (!username.trim()) {
      setError("请输入用户名。")
      usernameRef.current?.focus()
      return
    }
    if (!password) {
      setError("请输入密码。")
      passwordRef.current?.focus()
      return
    }

    setSubmitting(true)
    try {
      const normalizedUsername = username.trim()
      await login({
        username: normalizedUsername,
        password,
        deviceLabel: DEVICE_LABEL,
      })
      rememberUsername(normalizedUsername)
    } catch (caught) {
      setPassword("")
      setShowPassword(false)
      setError(loginErrorMessage(caught))
      passwordFocusPending.current = true
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="login-title">
        <div className="auth-brand">
          <img className="auth-brand-mark" src={logoMark} alt="" aria-hidden="true" />
          <div className="auth-brand-text">
            <h1 id="login-title">{PRODUCT_NAME}</h1>
            <p className="auth-brand-slogan">交付有据，一步到位</p>
          </div>
        </div>
        <p className="supporting-copy">使用管理员分配的企业账号登录。</p>
        <form onSubmit={(event) => void submit(event)} noValidate>
          <div className="field">
            <label htmlFor="login-username">用户名</label>
            <input
              ref={usernameRef}
              id="login-username"
              name="username"
              autoComplete="username"
              maxLength={USERNAME_MAX_LENGTH}
              value={username}
              disabled={submitting}
              onChange={(event) => setUsername(event.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="login-password">密码</label>
            <div className="password-field">
              <input
                ref={passwordRef}
                id="login-password"
                name="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                maxLength={PASSWORD_MAX_LENGTH}
                value={password}
                disabled={submitting}
                onChange={(event) => setPassword(event.target.value)}
              />
              <button
                type="button"
                className="password-toggle"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? "隐藏密码" : "显示密码"}
                disabled={submitting}
              >
                <EyeIcon open={showPassword} />
              </button>
            </div>
          </div>
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <button className="primary-button full-width" type="submit" disabled={submitting}>
            {submitting ? "正在登录" : "登录"}
          </button>
        </form>
        {/*
          自助注册是**公开面**（未登录可达；服务端按来源 IP 限流）。注册制试用
          开闸 R3：登录页给出可见入口——此前只有 #enterprise-register 路由挂载
          （App.tsx），无导航入口 ⇒ 试用者拿不到入口。
        */}
        <p className="supporting-copy auth-register-entry">
          还没有账号？<a className="button-link" href="#enterprise-register">企业自助注册</a>
        </p>
      </section>
    </main>
  )
}

function EyeIcon({ open }: { open: boolean }) {
  const iconProps = {
    width: 18,
    height: 18,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  }
  return (
    <svg {...iconProps}>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
      {open ? <path d="m3 3 18 18" /> : null}
    </svg>
  )
}

function readLastUsername(): string {
  try {
    return window.localStorage?.getItem(LAST_USERNAME_KEY) ?? ""
  } catch {
    return ""
  }
}

function rememberUsername(username: string): void {
  try {
    window.localStorage?.setItem(LAST_USERNAME_KEY, username)
  } catch {
    // A disabled local storage must not block authentication.
  }
}

function loginErrorMessage(error: unknown): string {
  if (error instanceof AuthUiError && error.code === "invalid_credentials") {
    return "用户名或密码错误。"
  }
  if (error instanceof AuthUiError && error.code === "account_inactive") {
    return "该账号已停用，请联系管理员。"
  }
  if (error instanceof AuthUiError && error.code === "network_error") {
    return "无法连接本地服务，请确认 FDE API 已启动。"
  }
  if (error instanceof AuthUiError && error.code === "request_timeout") {
    return "本地服务响应超时，请稍后重试。"
  }
  return "暂时无法登录，请稍后重试。"
}
