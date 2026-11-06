import { useId, type ReactElement, type ReactNode } from "react"

import { useDialogA11y } from "../../common/useDialogA11y"

export type ModalTone = "default" | "danger" | "warning"

export interface ModalProps {
  title: string
  description?: string
  tone?: ModalTone
  /** 提交/校验进行中时锁住 Esc，避免用户误以为已取消。 */
  busy?: boolean
  onClose(): void
  children?: ReactNode
  footer?: ReactNode
}

/**
 * S2 统一弹窗原语：把 §3.3 的 ARIA 契约收敛到一个组件里。
 *
 * - `role="dialog" aria-modal="true"` + `aria-labelledby` / `aria-describedby`
 * - Esc 关闭、Tab 焦点陷阱、打开焦点移入、关闭焦点归还，全部由 `useDialogA11y` 承担
 * - 叠加更上层 aria-modal 时自动让位（hook 内已有焦点归属守卫）
 * - 只负责呈现层：密码二次校验、人工确认强度、G1–G9 均由调用方保留
 */
export function Modal({
  title,
  description,
  tone = "default",
  busy = false,
  onClose,
  children,
  footer,
}: ModalProps): ReactElement {
  const dialogRef = useDialogA11y<HTMLDivElement>(() => {
    if (!busy) onClose()
  })
  const titleId = useId()
  const descriptionId = useId()
  const toneClass = tone === "default" ? "" : ` ui-modal-${tone}`

  return (
    <div className="dialog-backdrop">
      <div
        ref={dialogRef}
        className={`dialog ui-modal${toneClass}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
      >
        <h2 id={titleId}>{title}</h2>
        {description ? (
          <p id={descriptionId} className="supporting-copy">{description}</p>
        ) : null}
        {children}
        {footer ? <div className="dialog-actions">{footer}</div> : null}
      </div>
    </div>
  )
}
