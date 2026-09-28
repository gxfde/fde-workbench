// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"
import React from "react"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"
const mocks = vi.hoisted(() => ({ apiRequest: vi.fn(), user: { id: "actor" } }))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))
import { AIActionConfirmation } from "../../src/renderer/src/ai/AIActionConfirmation"
afterEach(() => { cleanup(); vi.resetAllMocks() })
const action = { id: "a".repeat(64), description: "弃用文件：测试文件", operation: "files.deprecate", parameters: { file_id: "file" }, body: { reason: "测试" } }

it("sends password only to the dedicated confirmation API", async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => path.endsWith("/decision") ? { status: "completed" } : { items: [action] })
  render(<AIActionConfirmation />)
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText("当前账号密码"), "private-confirmation-password")
  await user.click(screen.getByRole("button", { name: "验证并执行" }))
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  expect(mocks.apiRequest).toHaveBeenCalledWith(`/api/v1/ai/actions/${action.id}/decision`, { method: "POST", body: { approve: true, password: "private-confirmation-password" } })
  expect(mocks.apiRequest.mock.calls.some(([path]) => path.includes("/chat/"))).toBe(false)
})

it("allows cancelling without entering a password", async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => path.endsWith("/decision") ? { status: "cancelled" } : { items: [action] })
  render(<AIActionConfirmation />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole("button", { name: "取消操作" }))
  expect(mocks.apiRequest).toHaveBeenCalledWith(`/api/v1/ai/actions/${action.id}/decision`, { method: "POST", body: { approve: false } })
})
