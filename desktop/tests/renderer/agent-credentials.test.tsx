// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

// 桌面第三批 ops3：智能体凭据面板（清单闭集 / 403 提示 / 闭集保存 body /
// 明文 await 前清空 / 两步删除确认）。
const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))

import { AgentCredentialsPanel } from "../../src/renderer/src/extensions/AgentCredentialsPanel"

function credentialRow(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    id: "c1",
    name: "default",
    credential_configured: true,
    created_by_user_id: "u1",
    created_at: "2026-11-13T08:00:00",
    ...overrides,
  }
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === "/api/v1/agents/credentials" && options?.method === "GET") {
      return Promise.resolve([credentialRow()])
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
})

afterEach(() => {
  cleanup()
})

it("清单直接渲染数组响应：名字 + 已配置态（不回显明文）", async () => {
  render(<AgentCredentialsPanel />)
  expect(await screen.findByText("default")).toBeInTheDocument()
  expect(screen.getByText(/已加密保存，不回显/)).toBeInTheDocument()
  expect(screen.queryByText(/secret/)).not.toBeInTheDocument()
})

it("403：提示仅平台操作者可管", async () => {
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === "/api/v1/agents/credentials" && options?.method === "GET") {
      return Promise.reject(new ApiClientError({ code: "forbidden", message: "当前账号无权配置智能体凭据。" }, 403))
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<AgentCredentialsPanel />)
  expect(await screen.findByRole("alert")).toHaveTextContent("仅平台操作者可管理智能体凭据。")
})

it("保存：body 闭集 {name, credential}，且 await 前明文 state 已清空", async () => {
  const user = userEvent.setup()
  let resolvePost: (() => void) | null = null
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === "/api/v1/agents/credentials" && options?.method === "GET") {
      return Promise.resolve([credentialRow()])
    }
    if (path === "/api/v1/agents/credentials" && options?.method === "POST") {
      expect(options.body).toEqual({ name: "default", credential: "secret-value" })
      return new Promise<void>((resolve) => { resolvePost = resolve })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<AgentCredentialsPanel />)
  await screen.findByText("default")
  await user.type(screen.getByLabelText("凭据名"), "default")
  await user.type(screen.getByLabelText("凭据明文"), "secret-value")
  await user.click(screen.getByRole("button", { name: "保存凭据" }))
  // POST 在途（未 resolve）时输入框必须已经清空：明文不驻留
  await waitFor(() => {
    expect(screen.getByLabelText("凭据名")).toHaveValue("")
    expect(screen.getByLabelText("凭据明文")).toHaveValue("")
  })
  resolvePost!()
  await waitFor(() => expect(screen.getByText(/已加密保存/)).toBeInTheDocument())
})

it("非法凭据名（含中文/连字符）客户端拦截，不发请求", async () => {
  const user = userEvent.setup()
  render(<AgentCredentialsPanel />)
  await screen.findByText("default")
  await user.type(screen.getByLabelText("凭据名"), "默认-槽")
  await user.type(screen.getByLabelText("凭据明文"), "x")
  await user.click(screen.getByRole("button", { name: "保存凭据" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("凭据名只允许字母、数字与下划线")
  const posts = mocks.apiRequest.mock.calls.filter((call) => call[1]?.method === "POST")
  expect(posts).toHaveLength(0)
})

it("明文超 8000 字符客户端拦截，不发请求", async () => {
  const user = userEvent.setup()
  render(<AgentCredentialsPanel />)
  await screen.findByText("default")
  await user.type(screen.getByLabelText("凭据名"), "big")
  // 8001 字符逐键太慢：直接改值（受控组件 onChange 同样触发）
  fireEvent.change(screen.getByLabelText("凭据明文"), { target: { value: "x".repeat(8001) } })
  await user.click(screen.getByRole("button", { name: "保存凭据" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("凭据明文过长")
  const posts = mocks.apiRequest.mock.calls.filter((call) => call[1]?.method === "POST")
  expect(posts).toHaveLength(0)
})

it("清空按钮立即清空明文输入", async () => {
  const user = userEvent.setup()
  render(<AgentCredentialsPanel />)
  await screen.findByText("default")
  await user.type(screen.getByLabelText("凭据名"), "tmp")
  await user.type(screen.getByLabelText("凭据明文"), "tmp-secret")
  await user.click(screen.getByRole("button", { name: "清空" }))
  expect(screen.getByLabelText("凭据名")).toHaveValue("")
  expect(screen.getByLabelText("凭据明文")).toHaveValue("")
})

it("删除走两步确认（DELETE /agents/credentials/<name>）", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === "/api/v1/agents/credentials" && options?.method === "GET") {
      return Promise.resolve([credentialRow()])
    }
    if (path === "/api/v1/agents/credentials/default" && options?.method === "DELETE") {
      return Promise.resolve({ deleted: "default" })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<AgentCredentialsPanel />)
  await screen.findByText("default")
  await user.click(screen.getByRole("button", { name: "删除" }))
  await user.click(screen.getByRole("button", { name: "确认删除" }))
  expect(await screen.findByText(/凭据「default」已删除/)).toBeInTheDocument()
})

it("删除 404 原样呈现", async () => {
  const user = userEvent.setup()
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === "/api/v1/agents/credentials" && options?.method === "GET") {
      return Promise.resolve([credentialRow()])
    }
    if (path === "/api/v1/agents/credentials/default" && options?.method === "DELETE") {
      return Promise.reject(new ApiClientError({ code: "credential_not_found", message: "凭据不存在。" }, 404))
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<AgentCredentialsPanel />)
  await screen.findByText("default")
  await user.click(screen.getByRole("button", { name: "删除" }))
  await user.click(screen.getByRole("button", { name: "确认删除" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("凭据不存在。")
})
