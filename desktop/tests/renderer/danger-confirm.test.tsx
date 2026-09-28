// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React, { useState } from "react"
import { cleanup, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AuthProvider } from "../../src/renderer/src/auth/AuthProvider"
import { DangerConfirmProvider, useDangerConfirm } from "../../src/renderer/src/common/DangerConfirmProvider"
import type { ApiResponse, BridgeResult } from "../../src/shared/contracts"
import { adminUser, authResult, bridge, installBridge, ok, renderApp } from "./test-utils"

const CORRECT_PASSWORD = "AdminPass!123"
const WRONG_PASSWORD = "WrongPass!999"

function apiOk<T>(data: T, status = 200): BridgeResult<ApiResponse<T>> {
  return ok({ status, data, error: null })
}

function apiError(code: string, status: number): BridgeResult<ApiResponse<never>> {
  return ok({ status, data: null, error: { code, message: code } })
}

function Harness() {
  const confirm = useDangerConfirm()
  const [ran, setRan] = useState(false)
  return (
    <div>
      <button
        type="button"
        onClick={() => {
          void confirm({
            title: "删除草稿",
            description: "确定删除该草稿吗？删除后不可恢复。",
            confirmLabel: "删除",
          }).then((confirmed) => {
            if (confirmed) setRan(true)
          })
        }}
      >
        触发危险操作
      </button>
      <output aria-label="执行状态">{ran ? "已执行" : "未执行"}</output>
    </div>
  )
}

function verifyRequest(apiRequest: ReturnType<typeof vi.fn>): (password: string) => void {
  return (password: string) => {
    const calls = apiRequest.mock.calls
    const verifyCalls = calls.filter(
      ([path, options]) =>
        (path as string) === "/api/v1/auth/verify-password" &&
        (options as { method: string }).method === "POST",
    )
    expect(verifyCalls).toHaveLength(1)
    const body = (verifyCalls[0][1] as { body: unknown }).body as {
      password: string
    }
    expect(body.password).toBe(password)
  }
}

function renderHarness(apiRequest: ReturnType<typeof vi.fn>) {
  installBridge(
    bridge({
      refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
      apiRequest,
    }),
  )
  renderApp(
    <AuthProvider>
      <DangerConfirmProvider>
        <Harness />
      </DangerConfirmProvider>
    </AuthProvider>,
  )
}

describe("DangerConfirmDialog", () => {
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it("requires the current account password before confirming", async () => {
    const apiRequest = vi.fn().mockResolvedValue(apiOk({ valid: true }))
    renderHarness(apiRequest)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "触发危险操作" }))
    const dialog = await screen.findByRole("dialog", { name: "删除草稿" })
    expect(within(dialog).getByLabelText("当前账号密码")).toHaveFocus()

    await user.click(within(dialog).getByRole("button", { name: "删除" }))
    expect(within(dialog).getByRole("alert")).toHaveTextContent("请输入当前账号密码。")
    expect(apiRequest).not.toHaveBeenCalled()
    expect(screen.getByRole("status", { name: "执行状态" })).toHaveTextContent("未执行")
  })

  it("runs onConfirm only after a valid password is verified", async () => {
    const apiRequest = vi.fn().mockResolvedValue(apiOk({ valid: true }))
    renderHarness(apiRequest)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "触发危险操作" }))
    const dialog = await screen.findByRole("dialog", { name: "删除草稿" })
    await user.type(within(dialog).getByLabelText("当前账号密码"), CORRECT_PASSWORD)
    await user.click(within(dialog).getByRole("button", { name: "删除" }))

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    })
    verifyRequest(apiRequest)(CORRECT_PASSWORD)
    expect(screen.getByRole("status", { name: "执行状态" })).toHaveTextContent("已执行")
  })

  it("keeps the dialog open and blocks the action on an invalid password", async () => {
    const apiRequest = vi.fn().mockImplementation((path: string, options: { method: string }) => {
      if (path === "/api/v1/auth/verify-password" && options.method === "POST") {
        return Promise.resolve(apiError("invalid_password", 400))
      }
      return Promise.resolve(apiError("unexpected_request", 500))
    })
    renderHarness(apiRequest)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "触发危险操作" }))
    const dialog = await screen.findByRole("dialog", { name: "删除草稿" })
    await user.type(within(dialog).getByLabelText("当前账号密码"), WRONG_PASSWORD)
    await user.click(within(dialog).getByRole("button", { name: "删除" }))

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("当前账号密码错误")
    expect(within(dialog).getByLabelText("当前账号密码")).toHaveValue("")
    expect(within(dialog).getByLabelText("当前账号密码")).toHaveFocus()
    expect(screen.getByRole("dialog")).toBeVisible()
    expect(screen.getByRole("status", { name: "执行状态" })).toHaveTextContent("未执行")
  })

  it("dismisses without running the action when cancelled", async () => {
    const apiRequest = vi.fn().mockResolvedValue(apiOk({ valid: true }))
    renderHarness(apiRequest)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "触发危险操作" }))
    const dialog = await screen.findByRole("dialog", { name: "删除草稿" })
    await user.click(within(dialog).getByRole("button", { name: "取消" }))

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    })
    expect(apiRequest).not.toHaveBeenCalled()
    expect(screen.getByRole("status", { name: "执行状态" })).toHaveTextContent("未执行")
  })
})
