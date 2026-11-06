import { useEffect, useRef } from "react"

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * 方案 §3.3 / §3.7：弹窗的统一键盘契约——
 * Esc 关闭、Tab 在弹窗内循环、打开时焦点移入、关闭后焦点归还触发元素。
 *
 * 只补交互层，不改弹窗业务语义：危险确认的密码二次校验与 autoFocus 仍在
 * DangerConfirmDialog 内，本 hook 不介入该组件。
 *
 * 用法：把返回的 ref 挂到带 `role="dialog" aria-modal="true"` 的容器上。
 * `onClose` 用 ref 保存最新值，避免内联回调导致每次渲染都重做焦点初始化。
 */
export function useDialogA11y<T extends HTMLElement = HTMLDivElement>(onClose: () => void) {
  const dialogRef = useRef<T | null>(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null
    const dialog = dialogRef.current
    const initial = dialog?.querySelector<HTMLElement>(FOCUSABLE)
    initial?.focus()

    const handleKeyDown = (event: KeyboardEvent): void => {
      if (!dialog) return
      // 叠加弹窗让位：DangerConfirmDialog 等自带 onKeyDown 的确认框会抢走焦点。
      // 焦点在别的 aria-modal 里时，本 hook 既不抢 Esc 也不做 Tab 循环，
      // 否则捕获阶段的 stopPropagation 会让上层确认框的 Esc 失效、却关掉底层弹窗。
      const active = document.activeElement as HTMLElement | null
      const activeDialog = active?.closest('[role="dialog"][aria-modal="true"]') ?? null
      if (activeDialog && activeDialog !== dialog) return

      if (event.key === "Escape") {
        event.preventDefault()
        event.stopPropagation()
        closeRef.current()
        return
      }
      if (event.key !== "Tab") return
      const items = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE))
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener("keydown", handleKeyDown, true)
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true)
      previouslyFocused?.focus?.()
    }
  }, [])

  return dialogRef
}
