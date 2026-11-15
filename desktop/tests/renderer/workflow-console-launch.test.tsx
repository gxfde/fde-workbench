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
const launchPath = `/api/v1/projects/${projectId}/workflows/def-1/runs`

function definition(overrides: Record<string, unknown> = {}): Record<string, unknown> {
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

function run(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "run-abcdef1234567890",
    definition_id: "def-1",
    definition_version: 2,
    status: "queued",
    error: null,
    started_at: null,
    finished_at: null,
    created_at: "2026-11-04T09:00:00",
    ...overrides,
  }
}

function mockApi(definitions: Record<string, unknown>[] = [definition()]): void {
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === `/api/v1/projects/${projectId}/workflows` && (!options || options.method === "GET")) {
      return Promise.resolve({ items: definitions })
    }
    if (path === `/api/v1/projects/${projectId}/workflow-runs` && options?.method === "GET") {
      return Promise.resolve({ items: [run()], truncated: false })
    }
    if (path === launchPath && options?.method === "POST") {
      return Promise.resolve({ run: run(), created: true })
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

it("offers a launch button for published definitions when the user can manage", async () => {
  render(<WorkflowConsole projectId={projectId} canManage />)
  expect(await screen.findByRole("button", { name: "启动" })).toBeInTheDocument()
})

it("hides the launch button without manage permission", async () => {
  render(<WorkflowConsole projectId={projectId} canManage={false} />)
  expect(await screen.findByText("周报汇总")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "启动" })).not.toBeInTheDocument()
})

it("hides the launch button for draft definitions (only published can run)", async () => {
  mockApi([definition({ status: "draft" })])
  render(<WorkflowConsole projectId={projectId} canManage />)
  expect(await screen.findByText("草稿")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "启动" })).not.toBeInTheDocument()
})

it("posts a run launch and reloads the run list", async () => {
  const user = userEvent.setup()
  render(<WorkflowConsole projectId={projectId} canManage />)
  await user.click(await screen.findByRole("button", { name: "启动" }))
  await waitFor(() => expect(callCount(launchPath, "POST")).toBe(1))
  // 成功后重拉运行列表（新 run 由 worker 接单）
  await waitFor(() => expect(callCount(`/api/v1/projects/${projectId}/workflow-runs`, "GET")).toBe(2))
})

it("surfaces server 409 messages instead of swallowing them", async () => {
  const user = userEvent.setup()
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `/api/v1/projects/${projectId}/workflows`) return Promise.resolve({ items: [definition()] })
    if (path === `/api/v1/projects/${projectId}/workflow-runs` && options?.method === "GET") {
      return Promise.resolve({ items: [], truncated: false })
    }
    if (path === launchPath && options?.method === "POST") {
      return Promise.reject(
        new ApiClientError({ code: "definition_not_published", message: "只有已发布的定义可以发起运行。" }, 409),
      )
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<WorkflowConsole projectId={projectId} canManage />)
  await user.click(await screen.findByRole("button", { name: "启动" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("只有已发布的定义可以发起运行。")
})

// ── 第二批桌面 AI 辅助闭环·任务 3：新「从方案生成草稿」区在场时，启动行为零回归 ──

it("keeps launch behavior unchanged while the draft-generation section is present", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `/api/v1/projects/${projectId}/workflows` && options?.method === "GET") {
      return Promise.resolve({ items: [definition()] })
    }
    if (path === `/api/v1/projects/${projectId}/workflow-runs` && options?.method === "GET") {
      return Promise.resolve({ items: [], truncated: false })
    }
    if (path === `/api/v1/projects/${projectId}/delivery-plans` && options?.method === "GET") {
      return Promise.resolve({ items: [{ id: "plan-ap-1", title: "交付方案 v1", status: "approved", version: 1 }] })
    }
    if (path === "/api/v1/extensions" && options?.method === "GET") {
      return Promise.resolve({ skills: [{ key: "sop-deploy", name: "部署 SOP", status: "published", current_version: 3 }] })
    }
    if (path === launchPath && options?.method === "POST") {
      return Promise.resolve({ run: run(), created: true })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<WorkflowConsole projectId={projectId} canManage isAdmin />)

  // 新功能区在场（默认审批能力 workbench.write）
  expect(await screen.findByLabelText("从方案生成草稿")).toBeInTheDocument()
  expect(screen.getByLabelText("审批能力")).toHaveValue("workbench.write")
  // 既有启动行为零回归：POST runs → 重拉运行列表
  await user.click(screen.getByRole("button", { name: "启动" }))
  await waitFor(() => expect(callCount(launchPath, "POST")).toBe(1))
  await waitFor(() => expect(callCount(`/api/v1/projects/${projectId}/workflow-runs`, "GET")).toBe(2))
})
