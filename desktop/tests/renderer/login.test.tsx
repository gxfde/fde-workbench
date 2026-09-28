// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { App } from "../../src/renderer/src/App"
import {
  authResult,
  bridge,
  deferred,
  engineerUser,
  installBridge,
  ok,
  renderApp,
} from "./test-utils"

beforeEach(() => {
  const values = new Map<string, string>()
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      clear: () => values.clear(),
      getItem: (key: string) => values.get(key) ?? null,
      key: (index: number) => [...values.keys()][index] ?? null,
      get length() { return values.size },
      removeItem: (key: string) => values.delete(key),
      setItem: (key: string, value: string) => values.set(key, String(value)),
    } satisfies Storage,
  })
})

afterEach(() => {
  cleanup()
  window.localStorage.clear()
})

describe("desktop authentication experience", () => {
  it("refreshes once at startup while showing a neutral loading state", async () => {
    const pending = deferred<ReturnType<typeof ok<null>>>()
    const fde = bridge({ refresh: vi.fn().mockReturnValue(pending.promise) })
    installBridge(fde)

    renderApp(<App />)

    expect(screen.getByRole("status")).toHaveTextContent("正在加载工作台")
    expect(fde.auth.refresh).toHaveBeenCalledOnce()
    pending.resolve(ok(null))
    expect(await screen.findByRole("heading", { name: "FDE 工作台" })).toBeVisible()
    expect(fde.auth.refresh).toHaveBeenCalledOnce()
  })

  it("shows validation and places focus on the first invalid login field", async () => {
    installBridge(bridge())
    const user = userEvent.setup()
    renderApp(<App />)

    await screen.findByRole("heading", { name: "FDE 工作台" })
    await user.click(screen.getByRole("button", { name: "登录" }))

    expect(screen.getByText("请输入用户名。")).toBeVisible()
    expect(screen.getByLabelText("用户名")).toHaveFocus()
  })

  it("prefills the last successful username and focuses the password field", async () => {
    window.localStorage.setItem("fde:last-username:v1", "engineer.li")
    installBridge(bridge())
    renderApp(<App />)

    await screen.findByRole("heading", { name: "FDE 工作台" })

    expect(screen.getByLabelText("用户名")).toHaveValue("engineer.li")
    expect(screen.getByLabelText("密码")).toHaveFocus()
  })

  it("remembers the trimmed username only after a successful login", async () => {
    installBridge(bridge())
    const user = userEvent.setup()
    renderApp(<App />)
    await screen.findByRole("heading", { name: "FDE 工作台" })

    await user.type(screen.getByLabelText("用户名"), "  engineer.li  ")
    await user.type(screen.getByLabelText("密码"), "TempPass!2345")
    await user.click(screen.getByRole("button", { name: "登录" }))

    await screen.findByRole("heading", { name: "项目工作台" })
    expect(window.localStorage.getItem("fde:last-username:v1")).toBe("engineer.li")
  })

  it("supports keyboard navigation through the login controls", async () => {
    installBridge(bridge())
    const user = userEvent.setup()
    renderApp(<App />)

    await screen.findByRole("heading", { name: "FDE 工作台" })
    await user.tab()
    expect(screen.getByLabelText("用户名")).toHaveFocus()
    await user.tab()
    expect(screen.getByLabelText("密码")).toHaveFocus()
    await user.tab()
    expect(screen.getByRole("button", { name: "登录" })).toHaveFocus()
  })

  it("uses clear invalid-credentials copy and clears the submitted password", async () => {
    const fde = bridge({
      login: vi.fn().mockResolvedValue({
        ok: false,
        error: { code: "invalid_credentials", message: "backend copy" },
      }),
    })
    installBridge(fde)
    const user = userEvent.setup()
    renderApp(<App />)
    await screen.findByRole("heading", { name: "FDE 工作台" })

    await user.type(screen.getByLabelText("用户名"), "engineer.li")
    await user.type(screen.getByLabelText("密码"), "WrongPass!234")
    await user.click(screen.getByRole("button", { name: "登录" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("用户名或密码错误")
    expect(screen.getByLabelText("密码")).toHaveValue("")
    expect(screen.getByLabelText("密码")).toHaveFocus()
  })

  it("explains when the local API service cannot be reached", async () => {
    installBridge(bridge({
      login: vi.fn().mockResolvedValue({
        ok: false,
        error: { code: "network_error", message: "safe backend copy" },
      }),
    }))
    const user = userEvent.setup()
    renderApp(<App />)
    await screen.findByRole("heading", { name: "FDE 工作台" })

    await user.type(screen.getByLabelText("用户名"), "engineer.li")
    await user.type(screen.getByLabelText("密码"), "TempPass!2345")
    await user.click(screen.getByRole("button", { name: "登录" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("无法连接本地服务，请确认 FDE API 已启动")
  })

  it("locks login controls while authentication is pending", async () => {
    const pending = deferred<ReturnType<typeof ok<ReturnType<typeof authResult>>>>()
    installBridge(bridge({ login: vi.fn().mockReturnValue(pending.promise) }))
    const user = userEvent.setup()
    renderApp(<App />)
    await screen.findByRole("heading", { name: "FDE 工作台" })

    await user.type(screen.getByLabelText("用户名"), "engineer.li")
    await user.type(screen.getByLabelText("密码"), "TempPass!2345")
    await user.click(screen.getByRole("button", { name: "登录" }))

    expect(screen.getByRole("button", { name: "正在登录" })).toBeDisabled()
    expect(screen.getByLabelText("用户名")).toBeDisabled()
    expect(screen.getByLabelText("密码")).toBeDisabled()
    pending.resolve(ok(authResult(engineerUser)))
    expect(
      await screen.findByRole("heading", { name: "项目工作台" }),
    ).toBeVisible()
  })

  it("forces password change before showing the shell", async () => {
    const forcedUser = { ...engineerUser, mustChangePassword: true }
    installBridge(
      bridge({ login: vi.fn().mockResolvedValue(ok(authResult(forcedUser))) }),
    )
    const user = userEvent.setup()
    renderApp(<App />)
    await screen.findByRole("heading", { name: "FDE 工作台" })

    await user.type(screen.getByLabelText("用户名"), "engineer.li")
    await user.type(screen.getByLabelText("密码"), "TempPass!2345")
    await user.click(screen.getByRole("button", { name: "登录" }))

    expect(await screen.findByRole("heading", { name: "修改初始密码" })).toBeVisible()
    expect(
      screen.queryByRole("heading", { name: "项目工作台" }),
    ).not.toBeInTheDocument()
  })

  it("hides user management from engineers and clears session even if logout fails", async () => {
    const fde = bridge({
      refresh: vi.fn().mockResolvedValue(ok(authResult(engineerUser))),
      logout: vi.fn().mockResolvedValue({
        ok: false,
        error: { code: "network_error", message: "offline" },
      }),
    })
    installBridge(fde)
    vi.spyOn(window, "confirm").mockReturnValue(true)
    const user = userEvent.setup()
    renderApp(<App />)

    expect(
      await screen.findByRole("heading", { name: "项目工作台" }),
    ).toBeVisible()
    expect(screen.queryByRole("link", { name: "用户管理" })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "退出登录" }))
    expect(await screen.findByRole("heading", { name: "FDE 工作台" })).toBeVisible()
  })
})
