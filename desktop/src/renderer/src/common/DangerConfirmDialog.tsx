import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react"

import { PASSWORD_MAX_LENGTH } from "../../../shared/contracts"
import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"

export interface DangerConfirmDialogProps {
  title: string
  description: string
  confirmLabel: string
  /** Set when the underlying damage action is already running. */
  busy?: boolean
  onConfirm(): void
  onCancel(): void
}

/**
 * A reusable confirmation dialog that asks for the CURRENT account password
 * before the caller is allowed to run a destructive action. The password is
 * verified against the backend endpoint; only on a successful match does it
 * invoke `onConfirm`. A wrong password keeps the dialog open with an inline
 * error and never reaches the destructive action.
 */
export function DangerConfirmDialog({
  title,
  description,
  confirmLabel,
  busy = false,
  onConfirm,
  onCancel,
}: DangerConfirmDialogProps) {
  const { apiRequest } = useAuth()
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [verifying, setVerifying] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const locked = busy || verifying

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  useEffect(() => {
    if (error && !verifying) inputRef.current?.focus()
  }, [error, verifying])

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (locked) return
    setError("")
    if (!password) {
      setError("请输入当前账号密码。")
      return
    }
    setVerifying(true)
    try {
      await apiRequest<{ valid: boolean }>("/api/v1/auth/verify-password", {
        method: "POST",
        body: { password },
      })
      setPassword("")
      onConfirm()
    } catch (caught) {
      setPassword("")
      setError(verifyErrorMessage(caught))
    } finally {
      setVerifying(false)
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLElement>): void {
    if (event.key === "Escape") {
      event.preventDefault()
      if (!locked) onCancel()
    }
  }

  return (
    <div className="dialog-backdrop">
      <section
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="danger-confirm-title"
        aria-describedby="danger-confirm-description"
        onKeyDown={handleKeyDown}
      >
        <h2 id="danger-confirm-title">{title}</h2>
        <p id="danger-confirm-description" className="supporting-copy">
          {description}
        </p>
        <form onSubmit={(event) => void submit(event)} noValidate>
          <div className="field">
            <label htmlFor="danger-confirm-password">当前账号密码</label>
            <input
              ref={inputRef}
              id="danger-confirm-password"
              type="password"
              autoComplete="current-password"
              maxLength={PASSWORD_MAX_LENGTH}
              value={password}
              disabled={locked}
              autoFocus
              aria-invalid={Boolean(error)}
              aria-describedby={error ? "danger-confirm-error" : undefined}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
          {error ? (
            <p id="danger-confirm-error" className="form-error" role="alert">
              {error}
            </p>
          ) : null}
          <div className="dialog-actions">
            <button
              className="secondary-button"
              type="button"
              disabled={locked}
              onClick={onCancel}
            >
              取消
            </button>
            <button
              className="primary-button"
              type="submit"
              disabled={locked}
            >
              {verifying ? "正在验证" : confirmLabel}
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}

function verifyErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "invalid_password") {
    return "当前账号密码错误，请输入正确密码。"
  }
  if (
    error instanceof ApiClientError &&
    (error.code === "authentication_required" ||
      error.code === "authentication_refreshed_resubmit")
  ) {
    return "登录状态已更新，请重新输入密码验证。"
  }
  return "暂时无法验证密码，请稍后重试。"
}
