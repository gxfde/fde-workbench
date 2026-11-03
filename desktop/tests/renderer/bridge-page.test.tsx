// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  user: { id: "actor-1", role: "project_lead" },
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))

import { BridgePage } from "../../src/renderer/src/bridge/BridgePage"
import { bridge, installBridge, ok } from "./test-utils"

function bridgeView(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    captured_at: "2026-10-26T08:00:00+00:00",
    engagements: [
      {
        slug: "demo-engagement",
        openfde_synced_at: "2026-10-26T08:00:00+00:00",
        openfde_status: { entities: 12, active_facts: 30, open_tasks: 2 },
        fdeops_synced_at: "2026-10-26T07:00:00+00:00",
        fdeops_state: { fde_initialized: true, bound_path: "D:/fdeops/demo" },
        linked_projects: [{ project_id: "p-1", project_name: "星河试点" }],
        flags: [],
      },
    ],
    projects: [],
    ...overrides,
  }
}

function callCount(path: string, method?: string): number {
  return mocks.apiRequest.mock.calls.filter(
    (call) =>
      String(call[0]) === path &&
      (method === undefined || (call[1] as { method?: string } | undefined)?.method === method),
  ).length
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
  mocks.user = { id: "actor-1", role: "project_lead" }
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path) === "/api/v1/bridge/engagements") return bridgeView()
    if (String(path) === "/api/v1/bridge/status") return { runs: [] }
    return {}
  })
  installBridge(bridge())
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it("shows the failure banner when the engagement projection cannot load", async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path) === "/api/v1/bridge/engagements") throw new Error("集成桥投影不可用")
    return { runs: [] }
  })
  render(<BridgePage />)

  const alert = await screen.findByRole("alert")
  expect(alert).toHaveTextContent("集成桥投影不可用")
  expect(screen.queryByText("demo-engagement")).not.toBeInTheDocument()
})

it("renders engagement projections with track status and flags", async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path) === "/api/v1/bridge/engagements") {
      return bridgeView({
        engagements: [
          {
            slug: "stale-one",
            openfde_synced_at: "2026-10-26T08:00:00+00:00",
            openfde_status: { entities: 3, active_facts: 5, open_tasks: 0 },
            fdeops_synced_at: null,
            fdeops_state: {},
            linked_projects: [],
            flags: ["stale"],
          },
        ],
      })
    }
    if (String(path) === "/api/v1/bridge/status") return { runs: [] }
    return {}
  })
  render(<BridgePage />)

  expect(await screen.findByText("stale-one")).toBeVisible()
  expect(screen.getByText("采集断连")).toBeVisible()
  expect(screen.getByText(/⚠ 采集断连/)).toBeVisible()
  const trackCell = await screen.findByText(
    (_, element) =>
      element?.tagName === "TD" &&
      (element.textContent ?? "").includes("3 实体 / 5 活事实 / 0 开放任务"),
  )
  expect(trackCell).toBeVisible()
})

it("manager can reproject and the board reloads afterwards", async () => {
  const user = userEvent.setup()
  render(<BridgePage />)

  await screen.findByText("demo-engagement")
  expect(callCount("/api/v1/bridge/reconcile", "POST")).toBe(0)

  await user.click(screen.getByRole("button", { name: "重新投影" }))

  await waitFor(() => expect(callCount("/api/v1/bridge/reconcile", "POST")).toBe(1))
  // 重投影成功后回读投影
  await waitFor(() => expect(callCount("/api/v1/bridge/engagements", "GET")).toBeGreaterThanOrEqual(2))
})

it("viewer neither sees reproject nor clear controls", async () => {
  mocks.user = { id: "viewer-1", role: "viewer" }
  render(<BridgePage />)

  await screen.findByText("demo-engagement")
  expect(screen.queryByRole("button", { name: "重新投影" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "清投影" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "立即采集" })).not.toBeInTheDocument()
})

it("manual capture triggers the host task and reloads once a fresh poller run lands", async () => {
  const user = userEvent.setup()
  const capture = vi.fn().mockResolvedValue(ok({ triggered: true, task: "FDE-Bridge-Poll" }))
  installBridge(bridge({ capture }))
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path) === "/api/v1/bridge/engagements") return bridgeView()
    if (String(path) === "/api/v1/bridge/status") {
      // 采集触发后的首次状态轮询即看到新的宿主采集运行
      return {
        runs: [
          {
            id: "run-fresh",
            trigger: "poller",
            ok: true,
            started_at: new Date().toISOString(),
            finished_at: null,
            engagements_seen: 1,
            error: null,
          },
        ],
      }
    }
    return {}
  })
  render(<BridgePage />)

  await user.click(await screen.findByRole("button", { name: "立即采集" }))

  await waitFor(() => expect(capture).toHaveBeenCalledOnce())
  await waitFor(() => expect(callCount("/api/v1/bridge/status", "GET")).toBeGreaterThanOrEqual(2))
  await waitFor(() => expect(callCount("/api/v1/bridge/engagements", "GET")).toBeGreaterThanOrEqual(2))
  // 到站刷新完成后按钮恢复可用
  await waitFor(() => expect(screen.getByRole("button", { name: "立即采集" })).toBeEnabled())
})

it("surfaces capture trigger failures without reloading the projection", async () => {
  const user = userEvent.setup()
  const capture = vi.fn().mockResolvedValue({
    ok: false,
    error: { code: "task_missing", message: "未找到计划任务 FDE-Bridge-Poll，请先安装宿主采集任务。" },
  })
  installBridge(bridge({ capture }))
  render(<BridgePage />)

  await user.click(await screen.findByRole("button", { name: "立即采集" }))

  const alert = await screen.findByRole("alert")
  expect(alert).toHaveTextContent("未找到计划任务 FDE-Bridge-Poll")
  await waitFor(() => expect(capture).toHaveBeenCalledOnce())
  expect(callCount("/api/v1/bridge/engagements", "GET")).toBe(1)
})

it("clears a vanished projection via DELETE and reloads", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation(async (path: string, options?: { method?: string }) => {
    if (String(path) === "/api/v1/bridge/engagements" && options?.method !== "DELETE") {
      return bridgeView({
        engagements: [
          {
            slug: "gone-engagement",
            openfde_synced_at: null,
            openfde_status: {},
            fdeops_synced_at: null,
            fdeops_state: {},
            linked_projects: [],
            flags: ["vanished"],
          },
        ],
      })
    }
    if (String(path) === "/api/v1/bridge/status") return { runs: [] }
    return {}
  })
  render(<BridgePage />)

  await user.click(await screen.findByRole("button", { name: "清投影" }))

  await waitFor(() =>
    expect(callCount("/api/v1/bridge/engagements/gone-engagement", "DELETE")).toBe(1),
  )
  await waitFor(() => expect(callCount("/api/v1/bridge/engagements", "GET")).toBeGreaterThanOrEqual(2))
})

it("surfaces clear failures without wiping the table", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation(async (path: string, options?: { method?: string }) => {
    if (String(path).includes("/bridge/engagements/gone-engagement")) {
      throw new Error("清投影失败：文件仍存活")
    }
    if (String(path) === "/api/v1/bridge/engagements") {
      return bridgeView({
        engagements: [
          {
            slug: "gone-engagement",
            openfde_synced_at: null,
            openfde_status: {},
            fdeops_synced_at: null,
            fdeops_state: {},
            linked_projects: [],
            flags: ["vanished"],
          },
        ],
      })
    }
    if (String(path) === "/api/v1/bridge/status") return { runs: [] }
    return {}
  })
  render(<BridgePage />)

  await user.click(await screen.findByRole("button", { name: "清投影" }))

  const alert = await screen.findByRole("alert")
  expect(alert).toHaveTextContent("清投影失败：文件仍存活")
  expect(screen.getByText("gone-engagement")).toBeVisible()
})

it("renders a duplicate flag only once", async () => {
  // 服务端 flags 允许重复（双轨各自断连各报一次 stale）。前端渲染前必须去重，
  // 否则会出现两个同名徽标，并因 key 重复触发 React 警告。
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path) === "/api/v1/bridge/engagements") {
      return bridgeView({
        engagements: [
          {
            slug: "dup-flag-engagement",
            openfde_synced_at: "2026-10-26T08:00:00+00:00",
            openfde_status: {},
            fdeops_synced_at: "2026-10-26T07:00:00+00:00",
            fdeops_state: {},
            linked_projects: [],
            flags: ["stale", "stale", "unlinked"],
          },
        ],
      })
    }
    if (String(path) === "/api/v1/bridge/status") return { runs: [] }
    return {}
  })
  render(<BridgePage />)

  await screen.findByText("dup-flag-engagement")
  expect(screen.getAllByText("采集断连")).toHaveLength(1)
  expect(screen.getAllByText("未绑定项目")).toHaveLength(1)
})
