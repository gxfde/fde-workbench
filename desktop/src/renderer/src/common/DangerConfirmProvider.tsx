import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"

import { DangerConfirmDialog } from "./DangerConfirmDialog"

export interface DangerConfirmOptions {
  title: string
  description: string
  confirmLabel: string
}

type DangerConfirmFn = (options: DangerConfirmOptions) => Promise<boolean>

interface DangerConfirmContextValue {
  confirm: DangerConfirmFn
}

type ResolveFn = (value: boolean) => void

const DangerConfirmContext = createContext<DangerConfirmContextValue | null>(
  null,
)

/**
 * Provides a single shared `confirm(...)` that opens a password-verified
 * danger dialog anywhere in the app. It resolves `true` only after the current
 * account password is verified, `false` on cancel/escape.
 */
export function DangerConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<DangerConfirmOptions | null>(null)
  const resolveRef = useRef<ResolveFn | null>(null)

  const confirm = useCallback<DangerConfirmFn>(
    (options) =>
      new Promise<boolean>((resolve) => {
        resolveRef.current = resolve
        setPending({ ...options })
      }),
    [],
  )

  const settle = useCallback((value: boolean) => {
    resolveRef.current?.(value)
    resolveRef.current = null
    setPending(null)
  }, [])

  const handleConfirm = useCallback(() => settle(true), [settle])
  const handleCancel = useCallback(() => settle(false), [settle])

  const value = useMemo<DangerConfirmContextValue>(
    () => ({ confirm }),
    [confirm],
  )

  return (
    <DangerConfirmContext.Provider value={value}>
      {children}
      {pending ? (
        <DangerConfirmDialog
          title={pending.title}
          description={pending.description}
          confirmLabel={pending.confirmLabel}
          onConfirm={handleConfirm}
          onCancel={handleCancel}
        />
      ) : null}
    </DangerConfirmContext.Provider>
  )
}

export function useDangerConfirm(): DangerConfirmFn {
  const context = useContext(DangerConfirmContext)
  if (!context) {
    throw new Error("DangerConfirmProvider is required to use useDangerConfirm.")
  }
  return context.confirm
}
