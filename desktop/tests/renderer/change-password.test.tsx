// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { App } from "../../src/renderer/src/App"
import {
  authResult,
  bridge,
  engineerUser,
  installBridge,
  ok,
  renderApp,
} from "./test-utils"

afterEach(() => cleanup())

function forcedUser() {
  return { ...engineerUser, mustChangePassword: true }
}

describe("forced password change", () => {
  it("shows visible password policy and focuses the first invalid field", async () => {
    installBridge(
      bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(forcedUser()))) }),
    )
    const user = userEvent.setup()
    renderApp(<App />)

    await screen.findByRole("heading", { name: "修改初始密码" })
    expect(screen.getByText("新密码需至少 6 位。")).toBeVisible()
    await user.click(screen.getByRole("button", { name: "保存新密码" }))
    expect(screen.getByText("请输入当前密码。")).toBeVisible()
    expect(screen.getByLabelText("当前密码")).toHaveFocus()
  })

  it("changes password through main IPC and enters the shell without retaining secrets", async () => {
    const changedUser = { ...engineerUser, mustChangePassword: false }
    const changePassword = vi
      .fn()
      .mockResolvedValue(ok(authResult(changedUser, "changed-access")))
    installBridge(
      bridge({
        refresh: vi.fn().mockResolvedValue(ok(authResult(forcedUser()))),
        changePassword,
      }),
    )
    const user = userEvent.setup()
    renderApp(<App />)
    await screen.findByRole("heading", { name: "修改初始密码" })

    await user.type(screen.getByLabelText("当前密码"), "TempPass!2345")
    await user.type(screen.getByLabelText("新密码"), "123456")
    await user.type(screen.getByLabelText("确认新密码"), "123456")
    await user.click(screen.getByRole("button", { name: "保存新密码" }))

    expect(changePassword).toHaveBeenCalledWith(
      "access-token",
      "TempPass!2345",
      "123456",
    )
    expect(
      await screen.findByRole("heading", { name: "项目工作台" }),
    ).toBeVisible()
    expect(document.body).not.toHaveTextContent("TempPass!2345")
    expect(document.body).not.toHaveTextContent("123456")
  })

  it("explains the six-character minimum when the new password is too short", async () => {
    const changePassword = vi.fn()
    installBridge(
      bridge({
        refresh: vi.fn().mockResolvedValue(ok(authResult(forcedUser()))),
        changePassword,
      }),
    )
    const user = userEvent.setup()
    renderApp(<App />)
    await screen.findByRole("heading", { name: "修改初始密码" })

    await user.type(screen.getByLabelText("当前密码"), "TempPass!2345")
    await user.type(screen.getByLabelText("新密码"), "12345")
    await user.type(screen.getByLabelText("确认新密码"), "12345")
    await user.click(screen.getByRole("button", { name: "保存新密码" }))

    expect(screen.getByRole("alert")).toHaveTextContent("新密码至少需要 6 位。")
    expect(changePassword).not.toHaveBeenCalled()
  })

  it("keeps the forced-change boundary when the current password is rejected", async () => {
    installBridge(
      bridge({
        refresh: vi.fn().mockResolvedValue(ok(authResult(forcedUser()))),
        changePassword: vi.fn().mockResolvedValue({
          ok: false,
          error: { code: "invalid_credentials", message: "wrong" },
        }),
      }),
    )
    const user = userEvent.setup()
    renderApp(<App />)
    await screen.findByRole("heading", { name: "修改初始密码" })

    await user.type(screen.getByLabelText("当前密码"), "WrongPass!234")
    await user.type(screen.getByLabelText("新密码"), "ChangedPass!9012")
    await user.type(screen.getByLabelText("确认新密码"), "ChangedPass!9012")
    await user.click(screen.getByRole("button", { name: "保存新密码" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("当前密码错误")
    expect(screen.getByRole("heading", { name: "修改初始密码" })).toBeVisible()
    expect(
      screen.queryByRole("heading", { name: "项目工作台" }),
    ).not.toBeInTheDocument()
  })
})
