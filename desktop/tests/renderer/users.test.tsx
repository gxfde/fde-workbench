// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { App } from "../../src/renderer/src/App"
import type { ApiResponse, BridgeResult } from "../../src/shared/contracts"
import {
  adminUser,
  authResult,
  bridge,
  deferred,
  engineerUser,
  installBridge,
  ok,
  renderApp,
} from "./test-utils"

beforeEach(() => {
  location.hash = "#users"
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  location.hash = ""
})

const listedUser = {
  id: "2c8b61c9-60a6-4be6-a2b1-c83e1b97d456",
  username: "engineer.li",
  display_name: "李工程师",
  role: "fde_engineer",
  is_active: true,
  must_change_password: true,
  created_at: "2026-08-19T12:00:00+00:00",
  updated_at: "2026-08-19T12:00:00+00:00",
}

function apiOk<T>(data: T, status = 200): BridgeResult<ApiResponse<T>> {
  return ok({ status, data, error: null })
}

function listResponse() {
  return apiOk({ items: [listedUser], page: 1, page_size: 20, total: 1 })
}

describe("administrator user management", () => {
  it("manages AI permissions with Chinese labels", async () => {
    const apiRequest = vi.fn((path: string, options: { method: string }) => {
      if (path === `/api/v1/users/${listedUser.id}/ai-access` && options.method === "GET") return Promise.resolve(apiOk({ level: "project_operator", capabilities: ["project.read", "task.assigned.update"], locked: false }))
      if (path === `/api/v1/users/${listedUser.id}/ai-access` && options.method === "PATCH") return Promise.resolve(apiOk({ level: "assistant_read" }))
      return Promise.resolve(listResponse())
    })
    installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
    renderApp(<App />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "管理 engineer.li 的 AI 权限" }))
    const select = await screen.findByLabelText("AI 权限级别")
    expect(screen.getByRole("option", { name: "AI 系统管理员（完全权限）" })).toBeInTheDocument()
    await user.selectOptions(select, "assistant_read")
    await user.click(screen.getByRole("button", { name: "保存 AI 权限" }))
    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith(`/api/v1/users/${listedUser.id}/ai-access`, expect.objectContaining({ method: "PATCH", body: { level: "assistant_read" } })))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  })

  it("shows the admin-only link and complete user state table", async () => {
    installBridge(
      bridge({
        refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
        apiRequest: vi.fn().mockResolvedValue(listResponse()),
      }),
    )
    renderApp(<App />)

    expect(await screen.findByRole("link", { name: "用户管理" })).toBeVisible()
    const row = await screen.findByRole("row", { name: /李工程师/ })
    expect(within(row).getByText("engineer.li")).toBeVisible()
    expect(within(row).getByText("工程师")).toBeVisible()
    expect(within(row).getByText("启用")).toBeVisible()
    expect(within(row).getByText("待修改")).toBeVisible()
    expect(within(row).getByText(/2026/)).toBeVisible()
  })

  it("creates a user and clears the temporary password immediately", async () => {
    const storageWrite = vi.spyOn(Storage.prototype, "setItem")
    const apiRequest = vi
      .fn()
      .mockResolvedValueOnce(listResponse())
      .mockResolvedValueOnce(apiOk(listedUser, 201))
      .mockResolvedValueOnce(listResponse())
    installBridge(
      bridge({
        refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
        apiRequest,
      }),
    )
    const user = userEvent.setup()
    renderApp(<App />)
    await screen.findByRole("heading", { name: "用户管理" })

    await user.type(screen.getByLabelText("用户名"), "engineer.new")
    await user.type(screen.getByLabelText("显示名称"), "新工程师")
    await user.selectOptions(screen.getByLabelText("角色"), "fde_engineer")
    await user.type(screen.getByLabelText("临时密码"), "TempPass!2345")
    await user.click(screen.getByRole("button", { name: "创建账号" }))

    expect(await screen.findByText("账号已创建")).toBeVisible()
    expect(screen.getByLabelText("临时密码")).toHaveValue("")
    expect(storageWrite).not.toHaveBeenCalled()
    expect(apiRequest).toHaveBeenNthCalledWith(
      2,
      "/api/v1/users",
      expect.objectContaining({
        method: "POST",
        body: expect.objectContaining({ temporary_password: "TempPass!2345" }),
      }),
    )
  })

  it("requires the current password before disabling an account", async () => {
    const apiRequest = vi
      .fn()
      .mockResolvedValueOnce(listResponse())
      .mockResolvedValueOnce(apiOk({ valid: true }))
      .mockResolvedValueOnce(apiOk({ ...listedUser, is_active: false }))
      .mockResolvedValueOnce(listResponse())
    installBridge(
      bridge({
        refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
        apiRequest,
      }),
    )
    const user = userEvent.setup()
    renderApp(<App />)
    const disable = await screen.findByRole("button", { name: "停用 engineer.li" })

    await user.click(disable)
    const dialog = await screen.findByRole("dialog", { name: "停用账号" })
    await user.type(within(dialog).getByLabelText("当前账号密码"), "AdminPass!123")
    await user.click(within(dialog).getByRole("button", { name: "停用" }))

    await waitFor(() => expect(apiRequest).toHaveBeenCalledTimes(4))
    expect(
      apiRequest,
    ).toHaveBeenNthCalledWith(
      2,
      "/api/v1/auth/verify-password",
      expect.objectContaining({ method: "POST", body: { password: "AdminPass!123" } }),
    )
    expect(apiRequest).toHaveBeenNthCalledWith(
      3,
      `/api/v1/users/${listedUser.id}`,
      expect.objectContaining({ method: "PATCH", body: { is_active: false } }),
    )
  })

  it("does not call the destructive action when the dialog is cancelled", async () => {
    const apiRequest = vi
      .fn()
      .mockResolvedValueOnce(listResponse())
      .mockResolvedValueOnce(listResponse())
    installBridge(
      bridge({
        refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
        apiRequest,
      }),
    )
    const user = userEvent.setup()
    renderApp(<App />)
    await user.click(await screen.findByRole("button", { name: "停用 engineer.li" }))
    const dialog = await screen.findByRole("dialog", { name: "停用账号" })
    await user.click(within(dialog).getByRole("button", { name: "取消" }))

    expect(await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    })).toBeUndefined()
    const destructiveCalls = apiRequest.mock.calls.filter(
      (call) => call[1]?.method === "PATCH",
    )
    expect(destructiveCalls).toHaveLength(0)
  })

  it("clears a reset temporary password after submission", async () => {
    const apiRequest = vi
      .fn()
      .mockResolvedValueOnce(listResponse())
      .mockResolvedValueOnce(apiOk(listedUser))
      .mockResolvedValueOnce(listResponse())
    installBridge(
      bridge({
        refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
        apiRequest,
      }),
    )
    const user = userEvent.setup()
    renderApp(<App />)
    await user.click(await screen.findByRole("button", { name: "重置 engineer.li 的密码" }))
    const resetField = screen.getByLabelText("新临时密码")
    await user.type(resetField, "ResetPass!9012")
    await user.click(screen.getByRole("button", { name: "确认重置" }))

    expect(await screen.findByText("密码已重置")).toBeVisible()
    expect(screen.queryByLabelText("新临时密码")).not.toBeInTheDocument()
    expect(document.body).not.toHaveTextContent("ResetPass!9012")
  })

  it("validates a required reset password inside the semantic dialog", async () => {
    const apiRequest = vi.fn().mockResolvedValueOnce(listResponse())
    installBridge(
      bridge({
        refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
        apiRequest,
      }),
    )
    const user = userEvent.setup()
    renderApp(<App />)
    await user.click(await screen.findByRole("button", { name: "重置 engineer.li 的密码" }))

    const dialog = screen.getByRole("dialog", { name: "重置 engineer.li 的密码" })
    expect(dialog).toHaveAttribute("aria-modal", "true")
    await user.click(within(dialog).getByRole("button", { name: "确认重置" }))

    expect(within(dialog).getByRole("alert")).toHaveTextContent("请输入新临时密码。")
    expect(within(dialog).getByLabelText("新临时密码")).toHaveFocus()
    expect(apiRequest).toHaveBeenCalledOnce()
  })

  it("traps focus, closes on Escape, and restores focus to the reset trigger", async () => {
    const apiRequest = vi.fn().mockResolvedValueOnce(listResponse())
    installBridge(
      bridge({
        refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
        apiRequest,
      }),
    )
    const user = userEvent.setup()
    renderApp(<App />)
    const trigger = await screen.findByRole("button", { name: "重置 engineer.li 的密码" })
    await user.click(trigger)
    const dialog = screen.getByRole("dialog")
    const input = within(dialog).getByLabelText("新临时密码")
    const cancel = within(dialog).getByRole("button", { name: "取消" })
    const confirm = within(dialog).getByRole("button", { name: "确认重置" })

    expect(input).toHaveFocus()
    await user.tab()
    expect(cancel).toHaveFocus()
    await user.tab()
    expect(confirm).toHaveFocus()
    await user.tab()
    expect(input).toHaveFocus()
    await user.tab({ shift: true })
    expect(confirm).toHaveFocus()
    await user.keyboard("{Escape}")

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it("locks reset submission, ignores Escape while pending, and shows failure inside the dialog", async () => {
    const pending = deferred<BridgeResult<ApiResponse<typeof listedUser>>>()
    const apiRequest = vi
      .fn()
      .mockResolvedValueOnce(listResponse())
      .mockReturnValueOnce(pending.promise)
    installBridge(
      bridge({
        refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
        apiRequest,
      }),
    )
    const user = userEvent.setup()
    renderApp(<App />)
    await user.click(await screen.findByRole("button", { name: "重置 engineer.li 的密码" }))
    const dialog = screen.getByRole("dialog")
    const input = within(dialog).getByLabelText("新临时密码")
    await user.type(input, "ResetPass!9012")
    await user.click(within(dialog).getByRole("button", { name: "确认重置" }))

    expect(within(dialog).getByRole("button", { name: "正在重置" })).toBeDisabled()
    expect(input).toBeDisabled()
    expect(within(dialog).getByRole("button", { name: "取消" })).toBeDisabled()
    await user.keyboard("{Escape}")
    expect(screen.getByRole("dialog")).toBeVisible()
    expect(apiRequest).toHaveBeenCalledTimes(2)

    pending.resolve(
      ok({
        status: 400,
        data: null,
        error: { code: "invalid_request", message: "invalid" },
      }),
    )
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("操作失败，请稍后重试。")
    expect(screen.getByRole("dialog")).toBeVisible()
    expect(input).toHaveValue("")
    expect(input).toHaveFocus()
    expect(within(dialog).getByRole("button", { name: "确认重置" })).toBeEnabled()
    expect(apiRequest).toHaveBeenCalledTimes(2)
  })

  it("refreshes once and retries the original request once after API 401", async () => {
    const apiRequest = vi
      .fn()
      .mockResolvedValueOnce(
        ok({
          status: 401,
          data: null,
          error: { code: "access_token_expired", message: "expired" },
        }),
      )
      .mockResolvedValueOnce(listResponse())
    const refresh = vi
      .fn()
      .mockResolvedValueOnce(ok(authResult(adminUser, "startup-access")))
      .mockResolvedValueOnce(ok(authResult(adminUser, "fresh-access")))
    installBridge(bridge({ refresh, apiRequest }))
    renderApp(<App />)

    expect(await screen.findByRole("heading", { name: "用户管理" })).toBeVisible()
    expect(refresh).toHaveBeenCalledTimes(2)
    expect(apiRequest).toHaveBeenCalledTimes(2)
    expect(apiRequest).toHaveBeenNthCalledWith(
      2,
      "/api/v1/users?page=1&page_size=20",
      expect.objectContaining({ accessToken: "fresh-access" }),
    )
  })

  it("returns to login when API refresh fails", async () => {
    const apiRequest = vi.fn().mockResolvedValue(
      ok({
        status: 401,
        data: null,
        error: { code: "access_token_expired", message: "expired" },
      }),
    )
    const refresh = vi
      .fn()
      .mockResolvedValueOnce(ok(authResult(adminUser, "startup-access")))
      .mockResolvedValueOnce({
        ok: false,
        error: { code: "refresh_token_invalid", message: "expired" },
      })
    installBridge(bridge({ refresh, apiRequest }))
    renderApp(<App />)

    expect(await screen.findByRole("heading", { name: "FDE 工作台" })).toBeVisible()
    expect(apiRequest).toHaveBeenCalledOnce()
  })

  it("does not let an old in-flight refresh overwrite a logout/login switch", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true)
    const oldRefresh = deferred<BridgeResult<ReturnType<typeof authResult> | null>>()
    const apiRequest = vi.fn().mockResolvedValueOnce(
      ok({
        status: 401,
        data: null,
        error: { code: "access_token_expired", message: "expired" },
      }),
    )
    const refresh = vi
      .fn()
      .mockResolvedValueOnce(ok(authResult(adminUser, "old-admin-access")))
      .mockReturnValueOnce(oldRefresh.promise)
    installBridge(
      bridge({
        refresh,
        login: vi.fn().mockResolvedValue(ok(authResult(engineerUser, "engineer-access"))),
        apiRequest,
      }),
    )
    const user = userEvent.setup()
    renderApp(<App />)
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledTimes(2))

    await user.click(screen.getByRole("button", { name: "退出登录" }))
    await screen.findByRole("heading", { name: "FDE 工作台" })
    await user.type(screen.getByLabelText("用户名"), "engineer.li")
    await user.type(screen.getByLabelText("密码"), "EngineerPass!234")
    await user.click(screen.getByRole("button", { name: "登录" }))
    expect(
      await screen.findByRole("heading", { name: "项目工作台" }),
    ).toBeVisible()

    oldRefresh.resolve(ok(authResult(adminUser, "stale-admin-access")))
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "项目工作台" })).toBeVisible(),
    )
    expect(screen.queryByRole("link", { name: "用户管理" })).not.toBeInTheDocument()
    expect(refresh).toHaveBeenCalledTimes(2)
    expect(apiRequest).toHaveBeenCalledTimes(3)
    expect(apiRequest.mock.calls.slice(1)).toEqual(
      expect.arrayContaining([
        [
          "/api/v1/projects?page=1&page_size=20",
          expect.objectContaining({ accessToken: "engineer-access" }),
        ],
        [
          "/api/v1/projects?page=1&page_size=100",
          expect.objectContaining({ accessToken: "engineer-access" }),
        ],
      ]),
    )
  })

  it("refreshes after mutation 401 but requires explicit resubmission", async () => {
    const apiRequest = vi
      .fn()
      .mockResolvedValueOnce(listResponse())
      .mockResolvedValueOnce(
        ok({
          status: 401,
          data: null,
          error: { code: "access_token_expired", message: "expired" },
        }),
      )
    const refresh = vi
      .fn()
      .mockResolvedValueOnce(ok(authResult(adminUser, "startup-access")))
      .mockResolvedValueOnce(ok(authResult(adminUser, "fresh-access")))
    installBridge(bridge({ refresh, apiRequest }))
    const user = userEvent.setup()
    renderApp(<App />)
    await screen.findByRole("heading", { name: "用户管理" })

    await user.type(screen.getByLabelText("用户名"), "engineer.new")
    await user.type(screen.getByLabelText("显示名称"), "新工程师")
    await user.selectOptions(screen.getByLabelText("角色"), "fde_engineer")
    await user.type(screen.getByLabelText("临时密码"), "TempPass!2345")
    await user.click(screen.getByRole("button", { name: "创建账号" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "登录状态已刷新，请重新提交本次操作。",
    )
    const createCalls = apiRequest.mock.calls.filter((call) => call[1]?.method === "POST")
    expect(createCalls).toHaveLength(1)
    expect(refresh).toHaveBeenCalledTimes(2)
  })
})
