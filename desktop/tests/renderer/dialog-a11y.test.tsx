// @vitest-environment jsdom
// S1 / §3.7：弹窗统一键盘契约的行为守卫。
// 覆盖：打开焦点移入、Esc 关闭、关闭后焦点归还触发元素、Tab 双向循环，
// 以及叠加危险确认弹窗时底层 hook 必须让位（不能抢 Esc、不能困住 Tab）。
import "@testing-library/jest-dom/vitest"

import { useState, type ReactElement } from "react"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"

import { useDialogA11y } from "../../src/renderer/src/common/useDialogA11y"

interface DialogProps {
  onClose: () => void
  label?: string
}

function Dialog({ onClose, label = "预览" }: DialogProps): ReactElement {
  const ref = useDialogA11y<HTMLDivElement>(onClose)
  return (
    <div ref={ref} role="dialog" aria-modal="true" aria-label={label}>
      <button type="button">关闭</button>
      <input aria-label="备注" />
      <button type="button">确定</button>
    </div>
  )
}

function Host(): ReactElement {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        打开
      </button>
      {open ? <Dialog onClose={() => setOpen(false)} /> : null}
    </>
  )
}

afterEach(cleanup)

it("打开时焦点移入弹窗，Esc 关闭后焦点归还触发元素", () => {
  render(<Host />)
  const trigger = screen.getByRole("button", { name: "打开" })
  trigger.focus()
  fireEvent.click(trigger)

  const dialog = screen.getByRole("dialog")
  expect(dialog.querySelector("button")).toHaveFocus()

  fireEvent.keyDown(document.activeElement as Element, { key: "Escape" })
  expect(screen.queryByRole("dialog")).toBeNull()
  expect(trigger).toHaveFocus()
})

it("Tab / Shift+Tab 在弹窗内循环，不会跑到背景页面", () => {
  render(<Host />)
  fireEvent.click(screen.getByRole("button", { name: "打开" }))
  const dialog = screen.getByRole("dialog")
  const focusable = dialog.querySelectorAll<HTMLElement>("button, input")
  const first = focusable[0]
  const last = focusable[focusable.length - 1]

  last.focus()
  fireEvent.keyDown(last, { key: "Tab" })
  expect(first).toHaveFocus()

  fireEvent.keyDown(first, { key: "Tab", shiftKey: true })
  expect(last).toHaveFocus()
})

it("叠加危险确认弹窗时，底层弹窗让位：Esc 由上层处理，底层不被关闭", () => {
  const onClose = vi.fn()
  const upperEscape = vi.fn()

  function Stacked(): ReactElement {
    return (
      <>
        <Dialog onClose={onClose} label="底层预览" />
        <div
          role="dialog"
          aria-modal="true"
          aria-label="危险确认"
          onKeyDown={(event) => {
            if (event.key === "Escape") upperEscape()
          }}
        >
          <button type="button">取消</button>
        </div>
      </>
    )
  }

  render(<Stacked />)
  const cancel = screen.getByRole("button", { name: "取消" })
  cancel.focus()

  fireEvent.keyDown(cancel, { key: "Escape" })
  expect(upperEscape).toHaveBeenCalledTimes(1)
  expect(onClose).not.toHaveBeenCalled()
  expect(screen.getAllByRole("dialog")).toHaveLength(2)
})
