// @vitest-environment node
/**
 * CR-034「在途写不退出」保护接线（goal-c 台账）：
 * - close-guard 纯函数决策矩阵与确认文案；
 * - index.ts 接线静态钉——计数器曾只有 ++/-- 全仓零读取点（dead-code），
 *   本钉防止接线再次静默脱落。
 */
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"

import { describe, expect, it } from "vitest"

import { buildCloseGuardDialogSpec, shouldDeferWindowClose } from "../../src/main/close-guard"

const INDEX_SOURCE = readFileSync(
  join(fileURLToPath(new URL("../..", import.meta.url)), "src", "main", "index.ts"),
  "utf-8",
)

describe("CR-034 在途写不退出保护决策内核", () => {
  it("无在途写入时不拦截关闭", () => {
    expect(shouldDeferWindowClose(0, false)).toBe(false)
  })

  it("有在途写入且未放行时拦截关闭", () => {
    expect(shouldDeferWindowClose(1, false)).toBe(true)
    expect(shouldDeferWindowClose(5, false)).toBe(true)
  })

  it("一次性放行后不拦截关闭", () => {
    expect(shouldDeferWindowClose(3, true)).toBe(false)
  })

  it("负计数视为零在途（防御）", () => {
    expect(shouldDeferWindowClose(-1, false)).toBe(false)
  })
})

describe("CR-034 拦截确认对话框文案", () => {
  it("点名在途写入数量并给出两键选择，安全默认为等待", () => {
    const spec = buildCloseGuardDialogSpec(2)
    expect(spec.type).toBe("warning")
    expect(spec.message).toContain("2")
    expect(spec.buttons).toEqual(["等待完成", "仍然退出"])
    expect(spec.defaultId).toBe(0)
    expect(spec.cancelId).toBe(0)
  })

  it("detail 说明退出风险，不在文案里承诺自动重试", () => {
    const spec = buildCloseGuardDialogSpec(1)
    expect(spec.detail).toContain("重复提交")
    expect(spec.buttons.join()).not.toContain("自动")
  })
})

describe("CR-034 index.ts 接线静态钉（防再次静默脱线）", () => {
  it("主窗口 close 处理器消费 shouldDeferWindowClose 并可拦下事件", () => {
    expect(INDEX_SOURCE).toMatch(/window\.on\("close"/)
    expect(INDEX_SOURCE).toMatch(/shouldDeferWindowClose\(/)
    expect(INDEX_SOURCE).toMatch(/event\.preventDefault\(\)/)
  })

  it("对话框确认「仍然退出」后一次性放行并重触发关闭", () => {
    expect(INDEX_SOURCE).toMatch(/allowMainWindowCloseOnce = true/)
    expect(INDEX_SOURCE).toMatch(/window\.close\(\)/)
  })

  it("确认框悬起期间重复关闭只拦不再弹（防叠框）", () => {
    expect(INDEX_SOURCE).toMatch(/closeGuardDialogPending = true/)
    expect(INDEX_SOURCE).toMatch(/if \(closeGuardDialogPending\) return/)
    expect(INDEX_SOURCE).toMatch(/closeGuardDialogPending = false/)
  })

  it("activeMutations 既有累计/递减点仍存在（保护数据源不被移除）", () => {
    expect(INDEX_SOURCE).toMatch(/activeMutations\+\+/)
    expect(INDEX_SOURCE).toMatch(/activeMutations--/)
  })
})
