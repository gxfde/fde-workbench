import { type ButtonHTMLAttributes, type ReactElement } from "react"

import { useAsyncAction } from "../../common/useAsyncAction"

export type ButtonVariant = "primary" | "secondary" | "danger"

export interface UiButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  compact?: boolean
  busy?: boolean
  busyLabel?: string
}

function variantClass(variant: ButtonVariant): string {
  if (variant === "primary") return "primary-button"
  if (variant === "danger") return "danger-button"
  return "secondary-button"
}

/**
 * S2 展示层按钮原语。沿用 S0 已收敛的按钮族 class，不新增 CSS 契约、
 * 不引入 UI 库；`busy` 统一负责 disabled / aria-busy / 「处理中…」文案。
 */
export function UiButton({
  variant = "secondary",
  compact = false,
  busy = false,
  busyLabel = "处理中…",
  className = "",
  children,
  disabled,
  ...rest
}: UiButtonProps): ReactElement {
  const classes = [variantClass(variant), compact ? "compact" : "", className]
    .filter(Boolean)
    .join(" ")
  return (
    <button
      {...rest}
      className={classes}
      type={rest.type ?? "button"}
      disabled={Boolean(disabled) || busy}
      aria-busy={busy || undefined}
    >
      {busy ? busyLabel : children}
    </button>
  )
}

export interface AsyncButtonProps extends Omit<UiButtonProps, "onClick" | "busy"> {
  /** 区分同一页面里的多个动作，供 aria-busy 精确指向。 */
  actionKey: string
  /** 必须自行收敛异常并把错误展示出来（与 S1 的 15 个调用点同口径）。 */
  onRun(): Promise<unknown>
}

/** 把 `useAsyncAction` 状态机收进按钮内部，供 S2 逐页替换时使用。 */
export function AsyncButton({
  actionKey,
  onRun,
  ...buttonProps
}: AsyncButtonProps): ReactElement {
  const action = useAsyncAction()
  return (
    <UiButton
      {...buttonProps}
      busy={action.isBusy}
      onClick={() => {
        // onRun 内部负责展示错误；此处只兜住未处理 rejection，不改变业务语义。
        void action.run(actionKey, onRun).catch(() => undefined)
      }}
    />
  )
}
