import { useRef, useState, type FormEvent } from "react"

import { PASSWORD_MAX_LENGTH } from "../../../shared/contracts"
import { AuthUiError, useAuth } from "./AuthProvider"

export function ChangePasswordPage() {
  const { changePassword, user } = useAuth()
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmation, setConfirmation] = useState("")
  const [error, setError] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const currentRef = useRef<HTMLInputElement>(null)
  const nextRef = useRef<HTMLInputElement>(null)
  const confirmationRef = useRef<HTMLInputElement>(null)

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault()
    setError("")
    if (!currentPassword) {
      setError("请输入当前密码。")
      currentRef.current?.focus()
      return
    }
    if (!isValidPassword(newPassword)) {
      setError("新密码至少需要 6 位。")
      nextRef.current?.focus()
      return
    }
    if (newPassword !== confirmation) {
      setError("两次输入的新密码不一致。")
      confirmationRef.current?.focus()
      return
    }
    setSubmitting(true)
    try {
      await changePassword(currentPassword, newPassword)
      setCurrentPassword("")
      setNewPassword("")
      setConfirmation("")
    } catch (caught) {
      setCurrentPassword("")
      setNewPassword("")
      setConfirmation("")
      setError(passwordErrorMessage(caught))
      requestAnimationFrame(() => currentRef.current?.focus())
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card wide" aria-labelledby="change-password-title">
        <p className="eyebrow">首次登录安全步骤</p>
        <h1 id="change-password-title">修改初始密码</h1>
        <p className="supporting-copy">
          {user?.displayName}，设置新密码后才能进入工作台。
        </p>
        <div className="policy-box" aria-label="密码要求">
          新密码需至少 6 位。
        </div>
        <form onSubmit={(event) => void submit(event)} noValidate>
          <PasswordField
            id="current-password"
            label="当前密码"
            value={currentPassword}
            inputRef={currentRef}
            autoComplete="current-password"
            disabled={submitting}
            onChange={setCurrentPassword}
          />
          <PasswordField
            id="new-password"
            label="新密码"
            value={newPassword}
            inputRef={nextRef}
            autoComplete="new-password"
            disabled={submitting}
            onChange={setNewPassword}
          />
          <PasswordField
            id="confirm-password"
            label="确认新密码"
            value={confirmation}
            inputRef={confirmationRef}
            autoComplete="new-password"
            disabled={submitting}
            onChange={setConfirmation}
          />
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <button className="primary-button full-width" type="submit" disabled={submitting}>
            {submitting ? "正在保存" : "保存新密码"}
          </button>
        </form>
      </section>
    </main>
  )
}

function PasswordField(props: {
  id: string
  label: string
  value: string
  inputRef: React.RefObject<HTMLInputElement | null>
  autoComplete: string
  disabled: boolean
  onChange(value: string): void
}) {
  return (
    <div className="field">
      <label htmlFor={props.id}>{props.label}</label>
      <input
        ref={props.inputRef}
        id={props.id}
        type="password"
        autoComplete={props.autoComplete}
        maxLength={PASSWORD_MAX_LENGTH}
        value={props.value}
        disabled={props.disabled}
        onChange={(event) => props.onChange(event.target.value)}
      />
    </div>
  )
}

function isValidPassword(value: string): boolean {
  return value.length >= 6 && value.length <= PASSWORD_MAX_LENGTH
}

function passwordErrorMessage(error: unknown): string {
  if (error instanceof AuthUiError && error.code === "invalid_credentials") {
    return "当前密码错误，请重新输入。"
  }
  if (error instanceof AuthUiError && error.code === "password_too_weak") {
    return "新密码至少需要 6 位。"
  }
  return "暂时无法修改密码，请稍后重试。"
}
