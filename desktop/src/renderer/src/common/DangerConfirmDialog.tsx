import { useEffect, useRef, useState, type FormEvent } from "react"

import { PASSWORD_MAX_LENGTH } from "../../../shared/contracts"
import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { Modal, UiButton } from "../components/ui"

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
 *
 * S2：呈现层已吸收到统一 Modal 原语（ARIA 契约、Esc、焦点陷阱、焦点归还），
 * 但**人工确认 + 密码二次校验的强度不变**——密码仍由本组件自行校验，
 * 确认按钮在验证通过前不会触发 onConfirm。
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

  return (
    <Modal
      title={title}
      description={description}
      tone="danger"
      busy={busy || verifying}
      onClose={onCancel}
    >
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
          <UiButton disabled={locked} onClick={onCancel}>
            取消
          </UiButton>
          <UiButton variant="danger" type="submit" disabled={locked}>
            {verifying ? "正在验证" : confirmLabel}
          </UiButton>
        </div>
      </form>
    </Modal>
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
