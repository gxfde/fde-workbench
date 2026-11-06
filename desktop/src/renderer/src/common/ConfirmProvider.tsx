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

import { Modal, UiButton } from "../components/ui"
import type { ModalTone } from "../components/ui"

export interface ConfirmOptions {
  title: string
  description?: string
  confirmLabel?: string
  cancelLabel?: string
  tone?: ModalTone
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>
type ResolveFn = (value: boolean) => void

const ConfirmContext = createContext<ConfirmFn | null>(null)

// 模块级便捷入口：S2 归一时，部分遗留调用点位于深层 async 回调里，
// 插入 hook 会牵动组件签名；由当前挂载的 Provider 注册/注销，卸载即失效。
// 新代码请优先使用 useConfirm()。
let activeConfirm: ConfirmFn | null = null

export function confirmAsync(options: ConfirmOptions): Promise<boolean> {
  return activeConfirm?.(options) ?? Promise.resolve(false)
}

/**
 * S2 / F6：普通确认的唯一异步通道，替代散落的原生同步 confirm。
 *
 * 与 `DangerConfirmProvider` 分工明确：
 * - 本 Provider 只负责「用户是否确认」这一呈现层，**不做密码校验**；
 * - 涉及危险操作、需要当前账号密码二次校验的，仍必须走
 *   `useDangerConfirm()`，G1–G9 与人工确认强度不变。
 *
 * ⚠️ 同步导航守卫（`registerHashNavigationGuard` 的 guard 回调必须同步返回
 * boolean）不能改用本通道，详见实施记录。
 */
export function ConfirmProvider({ children }: { children: ReactNode }): ReactElement {
  const [pending, setPending] = useState<ConfirmOptions | null>(null)
  const resolveRef = useRef<ResolveFn | null>(null)

  const confirm = useCallback<ConfirmFn>(
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

  useEffect(() => {
    activeConfirm = confirm
    return () => { if (activeConfirm === confirm) activeConfirm = null }
  }, [confirm])

  const tone = pending?.tone ?? "default"
  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending ? (
        <Modal
          title={pending.title}
          description={pending.description}
          tone={tone}
          onClose={() => settle(false)}
          footer={
            <>
              <UiButton onClick={() => settle(false)}>
                {pending.cancelLabel ?? "取消"}
              </UiButton>
              <UiButton
                variant={tone === "danger" ? "danger" : "primary"}
                onClick={() => settle(true)}
              >
                {pending.confirmLabel ?? "确定"}
              </UiButton>
            </>
          }
        />
      ) : null}
    </ConfirmContext.Provider>
  )
}

export function useConfirm(): ConfirmFn {
  const context = useContext(ConfirmContext)
  if (!context) throw new Error("ConfirmProvider is required to use useConfirm().")
  return context
}
