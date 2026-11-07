// CR-034：「在途写不退出」保护的决策内核。
// activeMutations 计数器在 index.ts 的 API 桥接线累计（非 GET 视为写入，
// 见 registerApiIpc）；本模块只承载「要不要拦窗口关闭」的判定与确认文案，
// 保持纯函数可测——此前计数器只有 ++/-- 全仓零读取点，保护从未接线
// （goal-c 台账 CR-034，登记为 dead-code）。

export function shouldDeferWindowClose(activeMutations: number, allowCloseOnce: boolean): boolean {
  return !allowCloseOnce && activeMutations > 0
}

export interface CloseGuardDialogSpec {
  type: "warning"
  message: string
  detail: string
  buttons: string[]
  defaultId: number
  cancelId: number
  noLink: true
}

export function buildCloseGuardDialogSpec(activeMutations: number): CloseGuardDialogSpec {
  return {
    type: "warning",
    message: `有 ${activeMutations} 个写入操作仍在进行中`,
    detail: "立即关闭可能丢失操作结果或造成重复提交。可选择等写入完成后再退出，或仍然退出。",
    buttons: ["等待完成", "仍然退出"],
    defaultId: 0,
    cancelId: 0,
    noLink: true,
  }
}
