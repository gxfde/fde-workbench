// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"
import React from "react"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn(), changePassword: vi.fn(), updateDisplayName: vi.fn() }))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))
import { AccountPage } from "../../src/renderer/src/account/AccountPage"

const unbound = { status: "unbound", channel: "wechat_clawbot", commands_enabled: false, notifications_enabled: false, enabled: true, connected: false, login_status: "idle" }
const summary = { user: { id: "sample_user", username: "sample_user", display_name: "示例用户", role: "admin", is_active: true }, ai_access: { level: "system_operator", source: "role", capabilities: ["project.read", "system.health"], system_operations_explicit_only: false }, wechat_clawbot: unbound }

beforeEach(() => {
  mocks.apiRequest.mockReset()
  mocks.apiRequest.mockImplementation(async (path: string) => path === "/api/v1/account" ? summary : unbound)
})
afterEach(cleanup)

describe("微信官方扫码绑定", () => {
  it("shows Chinese permissions and Tencent QR image instead of a binding code", async () => {
    const user = userEvent.setup()
    mocks.apiRequest.mockImplementation(async (path: string, options: {method: string}) => {
      if (path === "/api/v1/account") return summary
      if (path.endsWith("/qr") && options.method === "POST") return { ...unbound, status: "pending", login_status: "wait", login_id: "provider-login-session-123456", qr_image: "data:image/svg+xml;base64,PHN2Zy8+" }
      return unbound
    })
    render(<AccountPage />)
    expect(await screen.findByRole("heading", { name: "AI Server 权限" })).toBeVisible()
    expect(screen.queryByText("project.read")).not.toBeInTheDocument()
    expect(screen.getByText(/管理员拥有完整管理权限/)).toBeVisible()
    await user.click(await screen.findByRole("button", { name: "微信扫码绑定" }))
    expect(await screen.findByRole("img", { name: "微信 ClawBot 官方登录二维码" })).toHaveAttribute("src", "data:image/svg+xml;base64,PHN2Zy8+")
    expect(screen.queryByText("一次性绑定码")).not.toBeInTheDocument()
    expect(mocks.apiRequest).toHaveBeenCalledWith("/api/v1/account/wechat-clawbot/qr", { method: "POST", body: {} })
  })

  it("polls confirmation and supports clearing the binding", async () => {
    const user = userEvent.setup()
    mocks.apiRequest.mockImplementation(async (path: string, options: {method: string}) => {
      if (path === "/api/v1/account") return summary
      if (path.endsWith("/poll")) return { ...unbound, status: "active", connected: true, login_status: "confirmed" }
      if (path.endsWith("/qr") && options.method === "POST") return { ...unbound, status: "pending", login_status: "wait", login_id: "provider-login-session-123456", qr_image: "data:image/svg+xml;base64,PHN2Zy8+" }
      return unbound
    })
    render(<AccountPage />)
    await user.click(await screen.findByRole("button", { name: "微信扫码绑定" }))
    await waitFor(() => expect(screen.getByRole("button", { name: "解除绑定" })).toBeVisible(), { timeout: 3000 })
    expect(screen.queryByRole("img")).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "解除绑定" }))
    expect(await screen.findByText(/服务器已清除登录凭据/)).toBeVisible()
  })

  it("requests phone verification when required by Tencent", async () => {
    const user = userEvent.setup()
    mocks.apiRequest.mockImplementation(async (path: string, options: {method: string;body?: {verify_code?: string}}) => {
      if (path === "/api/v1/account") return summary
      if (path.endsWith("/poll")) return { ...unbound, status: "pending", login_status: options.body?.verify_code ? "confirmed" : "need_verifycode", connected: Boolean(options.body?.verify_code) }
      if (path.endsWith("/qr") && options.method === "POST") return { ...unbound, status: "pending", login_status: "wait", login_id: "provider-login-session-123456", qr_image: "data:image/svg+xml;base64,PHN2Zy8+" }
      return unbound
    })
    render(<AccountPage />)
    await user.click(await screen.findByRole("button", { name: "微信扫码绑定" }))
    const codeInput = await screen.findByLabelText("手机微信显示的数字验证码", {}, { timeout: 3000 })
    await user.type(codeInput, "123456")
    await user.click(screen.getByRole("button", { name: "确认验证码" }))
    expect(mocks.apiRequest).toHaveBeenCalledWith("/api/v1/account/wechat-clawbot/qr/poll", { method: "POST", body: { login_id: "provider-login-session-123456", verify_code: "123456" } })
  })
})
