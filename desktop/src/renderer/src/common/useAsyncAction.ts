import { useCallback, useRef, useState } from "react"

/** 方案 §3.5 F1：idle → pending → success/error 的局部操作状态机。 */
export type AsyncActionState = "idle" | "pending" | "success" | "error"

export interface AsyncAction {
  state: AsyncActionState
  /** 正在执行的操作 key；null 表示空闲。 */
  busyKey: string | null
  isBusy: boolean
  run<T>(key: string, task: () => Promise<T>): Promise<T | undefined>
}

/**
 * 高危写操作的「禁用 / 处理中文案 / 防重复提交」护栏。
 *
 * - `running` 用 ref 而非 state：state 更新是异步的，单靠 state 挡不住同一帧内的第二次点击。
 * - 只包住调用点，**不吞异常**：task 抛出的错误照常向上传播，避免改变各页原有的错误提示行为。
 * - 不接管结果回执（统一 ToastHost 属 S2），也不改任何 API 契约、门禁语义或审批链。
 */
export function useAsyncAction(): AsyncAction {
  const [state, setState] = useState<AsyncActionState>("idle")
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const running = useRef(false)

  const run = useCallback(async <T,>(key: string, task: () => Promise<T>): Promise<T | undefined> => {
    if (running.current) return undefined
    running.current = true
    setState("pending")
    setBusyKey(key)
    try {
      const result = await task()
      setState("success")
      return result
    } catch (error) {
      setState("error")
      throw error
    } finally {
      running.current = false
      setBusyKey(null)
    }
  }, [])

  return { state, busyKey, isBusy: busyKey !== null, run }
}
