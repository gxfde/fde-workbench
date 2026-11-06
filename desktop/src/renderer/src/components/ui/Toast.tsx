import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from "react"

export type ToastTone = "success" | "info" | "warning" | "error"

interface ToastItem {
  id: number
  message: string
  tone: ToastTone
}

export interface ToastApi {
  push(message: string, tone?: ToastTone): void
  success(message: string): void
  info(message: string): void
  warning(message: string): void
  error(message: string): void
}

const ToastContext = createContext<ToastApi | null>(null)
const TOAST_TTL_MS = 5000

// 模块级便捷入口，供 S2 归一遗留调用点；卸载即失效。新代码优先 useToast()。
let activePush: ((message: string, tone: ToastTone) => void) | null = null

export function showToast(message: string, tone: ToastTone = "info"): void {
  activePush?.(message, tone)
}

/**
 * S2 / F2 单一 ToastHost。success/info 用 `role="status"`（polite），
 * error/warning 用 `role="alert"`（assertive），读屏用户不再错过结果。
 * 只新增回执通道，不接管各页已有的行内错误展示。
 */
export function ToastProvider({ children }: { children: ReactNode }): ReactElement {
  const [items, setItems] = useState<ToastItem[]>([])
  const nextId = useRef(0)
  const timers = useRef<number[]>([])

  useEffect(() => () => {
    timers.current.forEach((id) => window.clearTimeout(id))
  }, [])

  const push = useCallback((message: string, tone: ToastTone = "info") => {
    const id = ++nextId.current
    setItems((current) => [...current, { id, message, tone }])
    const timer = window.setTimeout(() => {
      setItems((current) => current.filter((item) => item.id !== id))
    }, TOAST_TTL_MS)
    timers.current.push(timer)
  }, [])

  useEffect(() => {
    activePush = push
    return () => { if (activePush === push) activePush = null }
  }, [push])

  const api: ToastApi = {
    push,
    success: (message) => push(message, "success"),
    info: (message) => push(message, "info"),
    warning: (message) => push(message, "warning"),
    error: (message) => push(message, "error"),
  }

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toast-host" aria-live="polite" aria-atomic="false">
        {items.map((item) => (
          <div
            key={item.id}
            className={`toast toast-${item.tone}`}
            role={item.tone === "error" || item.tone === "warning" ? "alert" : "status"}
          >
            {item.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext)
  if (!context) throw new Error("ToastProvider is required to use useToast().")
  return context
}
