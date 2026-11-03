// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  user: { id: "leader-1", role: "project_lead" },
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))

import { WorkflowConsole } from "../../src/renderer/src/workflows/WorkflowConsole"

const projectId = "proj-1"

function definition(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    id: "def-1",
    name: "周报汇总",
    description: "汇总门禁结果",
    status: "published",
    version: 2,
    published_at: "2026-11-04T08:00:00",
    dag_json: { nodes: [{ key: "gather" }, { key: "deliver" }] },
    ...overrides,
  }
}

function run(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    id: "run-abcdef1234567890",
    definition_id: "def-1",
    definition_version: 2,
    status: "running",
    error: null,
    started_at: "2026-11-04T09:00:00",
    finished_at: null,
    created_at: "2026-11-04T09:00:00",
    ...overrides,
  }
}

function mockApi(): void {
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === `/api/v1/projects/${projectId}/workflows`) {
      return Promise.resolve({ items: [definition()] })
    }
    if (path === `/api/v1/projects/${projectId}/workflow-runs` && options?.method === "GET") {
      return Promise.resolve({ items: [run()], truncated: false })
    }
    if (path === `/api/v1/projects/${projectId}/workflow-runs/run-abcdef1234567890` && options?.method === "GET") {
      return Promise.resolve({
        run: run({ nodes: [{ node_key: "gather", node_type: "call", status: "succeeded", attempt: 1, error: null }] }),
      })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
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
  mockApi()
})

afterEach(() => {
  cleanup()
})

it("renders definitions and runs with status labels and node overview", async () => {
  render(<WorkflowConsole projectId={projectId} canManage={false} />)
  expect(await screen.findByText("周报汇总")).toBeInTheDocument()
  expect(screen.getByText("已发布")).toBeInTheDocument()
  expect(screen.getByText(/2 个节点/)).toBeInTheDocument()
  expect(screen.getByText("运行中")).toBeInTheDocument()
  expect(screen.getByText("run-abcd")).toBeInTheDocument()
  // 运行中：不可恢复（resume 仅 failed），不可取消（无 canManage）
  expect(screen.queryByRole("button", { name: "取消" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "恢复" })).not.toBeInTheDocument()
})

it("shows cancel and resume buttons for canManage and posts cancel", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `/api/v1/projects/${projectId}/workflows`) return Promise.resolve({ items: [] })
    if (path === `/api/v1/projects/${projectId}/workflow-runs` && options?.method === "GET") {
      return Promise.resolve({
        items: [run({ status: "failed", error: "transient:临时失败。" }), run({ id: "run-live00000000000001", status: "queued" })],
        truncated: false,
      })
    }
    if (path?.endsWith("/cancel")) return Promise.resolve({ run: run({ status: "cancelled", finished_at: "2026-11-04T09:30:00" }), cancelled: true })
    if (path?.endsWith("/resume")) return Promise.resolve({ run: run({ status: "running" }), reset_nodes: 1 })
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<WorkflowConsole projectId={projectId} canManage />)
  expect(await screen.findByText("失败")).toBeInTheDocument()
  // failed 已是终态：仅恢复（resume）；queued 非终态：可取消
  expect(screen.getAllByRole("button", { name: "取消" }).length).toBe(1)
  expect(screen.getByRole("button", { name: "恢复" })).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "恢复" }))
  await waitFor(() => expect(callCount(`/api/v1/projects/${projectId}/workflow-runs/run-abcdef1234567890/resume`, "POST")).toBe(1))
  await waitFor(() => expect(screen.getByText("运行中")).toBeInTheDocument())
})

it("surfaces server 409 messages instead of swallowing them", async () => {
  const user = userEvent.setup()
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `/api/v1/projects/${projectId}/workflows`) return Promise.resolve({ items: [] })
    if (path === `/api/v1/projects/${projectId}/workflow-runs` && options?.method === "GET") {
      return Promise.resolve({ items: [run({ status: "running" })], truncated: false })
    }
    // 竞态：行还是 running 时别人已取消 → 服务端 409；控制台原样呈现
    if (path?.endsWith("/cancel")) {
      return Promise.reject(new ApiClientError({ code: "already_terminal", message: "运行已终态（cancelled），不能取消。" }, 409))
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<WorkflowConsole projectId={projectId} canManage />)
  await user.click(await screen.findByRole("button", { name: "取消" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("运行已终态（cancelled），不能取消。")
})

it("expands run detail and fetches the node tree on demand", async () => {
  const user = userEvent.setup()
  render(<WorkflowConsole projectId={projectId} canManage={false} />)
  await user.click(await screen.findByRole("button", { name: "详情" }))
  await waitFor(() =>
    expect(callCount(`/api/v1/projects/${projectId}/workflow-runs/run-abcdef1234567890`, "GET")).toBe(1),
  )
  expect(await screen.findByText("gather")).toBeInTheDocument()
  expect(screen.getByText("成功")).toBeInTheDocument()
})

it("notes truncated run lists honestly", async () => {
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `/api/v1/projects/${projectId}/workflows`) return Promise.resolve({ items: [] })
    if (path === `/api/v1/projects/${projectId}/workflow-runs`) {
      return Promise.resolve({ items: [run()], truncated: true })
    }
    throw new Error(`unexpected api call: GET ${path}`)
  })
  render(<WorkflowConsole projectId={projectId} canManage={false} />)
  expect(await screen.findByText("已显示最近的运行，更早的记录未列出。")).toBeInTheDocument()
})
