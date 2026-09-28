import { useEffect, useRef, useState, type FormEvent } from "react"

import { PASSWORD_MAX_LENGTH, USERNAME_MAX_LENGTH } from "../../../shared/contracts"
import { AuthUiError, useAuth } from "./AuthProvider"

const LAST_USERNAME_KEY = "fde:last-username:v1"

export function LoginPage() {
  const { login } = useAuth()
  const [username, setUsername] = useState(readLastUsername)
  const [password, setPassword] = useState("")
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
        deviceLabel: "FDE Workbench Desktop",
      })
      rememberUsername(normalizedUsername)
    } catch (caught) {
      setPassword("")
      setError(loginErrorMessage(caught))
      passwordFocusPending.current = true
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="login-title">
        <p className="eyebrow">企业 AI 落地工作台</p>
        <h1 id="login-title">FDE 工作台</h1>
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
            <input
              ref={passwordRef}
              id="login-password"
              name="password"
              type="password"
              autoComplete="current-password"
              maxLength={PASSWORD_MAX_LENGTH}
              value={password}
              disabled={submitting}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <button className="primary-button full-width" type="submit" disabled={submitting}>
            {submitting ? "正在登录" : "登录"}
          </button>
        </form>
      </section>
    </main>
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
