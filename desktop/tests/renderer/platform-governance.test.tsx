// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

// 桌面第三批 ops3：运行治理卡（到期投影闭集过滤 / 队列计量 / 两步取消 /
// 失败不阻保存 / SystemConfigurationPage <form> 外下方接线）。
const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))

import { PlatformGovernancePanel } from "../../src/renderer/src/system/PlatformGovernancePanel"
import { SystemConfigurationPage } from "../../src/renderer/src/system/SystemConfigurationPage"

function expirationItem(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    domain: "automation_approval",
    object_id: "obj-1",
    deadline_at: "2026-11-13T08:00:00+00:00",
    state: "pending",
    due: true,
    expiry_action: "fde_api.control.service._expire_approval",
    ...overrides,
  }
}

function meteringPayload(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    groups: [
      { org_id: null, active: 2, terminal: 5 },
      { org_id: "org-1", active: 1, terminal: 0 },
    ],
    queue_depth: 3,
    active_statuses: ["pending", "queued", "running"],
    ...overrides,
  }
}

function baseMock(): void {
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === "/api/v1/expirations?due=true") {
      return Promise.resolve({
        items: [expirationItem(), expirationItem({ domain: "upload_session", object_id: "up-9", expiry_action: "fde_api.files.expiration.expire_upload_session" })],
        total: 2,
      })
    }
    if (path === "/api/v1/admin/jobs/metering") {
      return Promise.resolve(meteringPayload())
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
  baseMock()
})

afterEach(() => {
  cleanup()
})

it("到期表只呈现闭集四域（未知域防御性过滤），截止时间与到期动作可见", async () => {
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === "/api/v1/expirations?due=true") {
      return Promise.resolve({
        items: [expirationItem(), expirationItem({ domain: "mystery_domain", object_id: "x-1" })],
        total: 2,
      })
    }
    if (path === "/api/v1/admin/jobs/metering") return Promise.resolve(meteringPayload())
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<PlatformGovernancePanel />)
  const region = await screen.findByRole("region", { name: "到期事项监控" })
  const table = within(region).getByRole("table")
  expect(within(table).getByText("自动化审批")).toBeInTheDocument()
  expect(within(table).getByText("obj-1")).toBeInTheDocument()
  // 未知域整行不呈现（防御性过滤），连带其对象列
  expect(screen.queryByText("x-1")).not.toBeInTheDocument()
  expect(within(table).queryByText("mystery_domain")).not.toBeInTheDocument()
})

it("队列计量：queue_depth 与分组（org 缺省呈现为平台级）", async () => {
  render(<PlatformGovernancePanel />)
  expect(await screen.findByText("平台级")).toBeInTheDocument()
  expect(screen.getByText("org-1")).toBeInTheDocument()
  expect(screen.getByText(/队列深度/)).toHaveTextContent("3")
  const region = screen.getByRole("region", { name: "队列监控" })
  expect(region).toHaveTextContent("2")
  expect(region).toHaveTextContent("5")
})

it("取消任务两步确认 → POST /admin/jobs/{id}/cancel → 刷新计量", async () => {
  let meterLoads = 0
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === "/api/v1/expirations?due=true") return Promise.resolve({ items: [], total: 0 })
    if (path === "/api/v1/admin/jobs/metering") {
      meterLoads += 1
      return Promise.resolve(meteringPayload())
    }
    if (path === "/api/v1/admin/jobs/job-1/cancel" && options?.method === "POST") {
      return Promise.resolve({ job_id: "job-1", job_type: "outbox_dispatch", status: "cancelled", cancelled: true })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<PlatformGovernancePanel />)
  await screen.findByText("平台级")
  const input = screen.getByLabelText("任务 ID")
  const cancelButton = screen.getByRole("button", { name: "取消任务" })
  expect(cancelButton).toBeDisabled()
  await userEvent.setup().type(input, "job-1")
  await userEvent.setup().click(screen.getByRole("button", { name: "取消任务" }))
  // 第一步只是确认态，还没发 POST
  expect(screen.getByRole("button", { name: /确认取消 job-1/ })).toBeInTheDocument()
  expect(mocks.apiRequest.mock.calls.filter((call) => String(call[0]).endsWith("/cancel"))).toHaveLength(0)
  await userEvent.setup().click(screen.getByRole("button", { name: /确认取消 job-1/ }))
  expect(await screen.findByText(/任务 job-1 已取消/)).toBeInTheDocument()
  await waitFor(() => expect(meterLoads).toBeGreaterThanOrEqual(2))
})

it("终态任务 409（already_terminal）原样呈现", async () => {
  const user = userEvent.setup()
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === "/api/v1/expirations?due=true") return Promise.resolve({ items: [], total: 0 })
    if (path === "/api/v1/admin/jobs/metering") return Promise.resolve(meteringPayload())
    if (path === "/api/v1/admin/jobs/job-2/cancel" && options?.method === "POST") {
      return Promise.reject(new ApiClientError({ code: "already_terminal", message: "后台任务已到达成功/失败终态，不能取消。" }, 409))
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<PlatformGovernancePanel />)
  await screen.findByText("平台级")
  await user.type(screen.getByLabelText("任务 ID"), "job-2")
  await user.click(screen.getByRole("button", { name: "取消任务" }))
  await user.click(screen.getByRole("button", { name: /确认取消 job-2/ }))
  expect(await screen.findByRole("alert")).toHaveTextContent("已到达成功/失败终态")
})

it("一路失败不阻另一路：到期投影 403 时计量照常渲染", async () => {
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === "/api/v1/expirations?due=true") {
      return Promise.reject(new ApiClientError({ code: "forbidden", message: "跨域到期投影仅平台管理员可读。" }, 403))
    }
    if (path === "/api/v1/admin/jobs/metering") return Promise.resolve(meteringPayload())
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<PlatformGovernancePanel />)
  expect(await screen.findByRole("alert")).toHaveTextContent("仅平台管理员可读")
  expect(await screen.findByText("平台级")).toBeInTheDocument()
  expect(screen.getByText(/队列深度/)).toHaveTextContent("3")
})

it("SystemConfigurationPage：治理卡在 <form> 外下方渲染，配置保存按钮不受影响", async () => {
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === "/api/v1/system/configuration" && options?.method === "GET") {
      return Promise.resolve({ values: {}, secrets_configured: {}, version: 7, bootstrap_fields: [] })
    }
    if (path === "/api/v1/expirations?due=true") return Promise.resolve({ items: [], total: 0 })
    if (path === "/api/v1/admin/jobs/metering") return Promise.resolve(meteringPayload())
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<SystemConfigurationPage />)
  expect(await screen.findByRole("button", { name: "保存系统配置" })).toBeInTheDocument()
  expect(await screen.findByRole("region", { name: "到期事项监控" })).toBeInTheDocument()
  expect(await screen.findByRole("region", { name: "队列监控" })).toBeInTheDocument()
  // 治理卡两区不得处于保存表单内部（<form> 外下方的结构约定）
  expect(screen.getByRole("region", { name: "到期事项监控" }).closest("form")).toBeNull()
  expect(screen.getByRole("region", { name: "队列监控" }).closest("form")).toBeNull()
})
