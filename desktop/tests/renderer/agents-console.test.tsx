// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  user: { id: "leader-1", role: "project_lead" },
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))

import { AgentsConsole } from "../../src/renderer/src/agents/AgentsConsole"

const projectId = "proj-ta8"

function runRow(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    id: "run-abcdef1234567890",
    project_id: projectId,
    agent_id: "agent-1234567890",
    status: "completed",
    capability_used: "agent.code.write",
    initiated_by_user_id: "user-1",
    context_ref: "agent-workspaces/x/context.md",
    token_cost: 1200,
    duration_ms: 4300,
    exit_code: 0,
    degraded: false,
    degraded_reason: null,
    fallback_level: null,
    retry_of: null,
    idempotency_key: "k1",
    cost_owner_type: "project",
    cost_owner_id: null,
    handoff_user_id: null,
    difficulty: "standard",
    created_at: "2026-11-07T08:00:00",
    updated_at: "2026-11-07T08:01:00",
    ...overrides,
  }
}

function costSummary(): Record<string, unknown> {
  return { scope: "project", project_id: projectId, items: [], total_token_cost: 3200, monthly: { "2026-11": 3200 } }
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it("渲染 run 列表与项目成本汇总（列表→成本两面板）", async () => {
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.resolve({ items: [runRow()], truncated: false })
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<AgentsConsole projectId={projectId} />)
  expect(await screen.findByText("已完成")).toBeInTheDocument()
  expect(screen.getByText("agent.code.write")).toBeInTheDocument()
  expect(screen.getByText("3200")).toBeInTheDocument() // 成本汇总
  expect(screen.getByText(/2026-11=3200/)).toBeInTheDocument()
})

it("详情展开拉 run 详情与工具调用（详情+工具调用面板）", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.resolve({ items: [runRow({ status: "succeeded_but_receipt_invalid" })], truncated: false })
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    if (path === "/api/v1/agents/runs/run-abcdef1234567890" && options?.method === "GET") {
      return Promise.resolve(runRow({
        agent: { name: "ZCode 沙箱智能体", kind: "zcode" },
        artifacts: [{ id: "art-1", kind: "doc", storage_ref: "output/plan.md", sha256: "a".repeat(64), reviewed: false, linked_solution_id: null }],
      }))
    }
    if (path === "/api/v1/agents/runs/run-abcdef1234567890/tool-calls" && options?.method === "GET") {
      return Promise.resolve({
        items: [{ id: "call-1", tool_name: "read_file", decision: "allowed", capability: "fs.read", reason: null, duration_ms: 12 }],
        denied_count: 0,
      })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<AgentsConsole projectId={projectId} />)
  expect(await screen.findByText("成功但回执无效")).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "详情" }))
  expect(await screen.findByText("ZCode 沙箱智能体（zcode）")).toBeInTheDocument()
  expect(screen.getByText("output/plan.md")).toBeInTheDocument()
  expect(screen.getByText(/aaaaaaaaaaaa…/)).toBeInTheDocument()
  expect(screen.getByText("read_file")).toBeInTheDocument()
  expect(screen.getByText("放行")).toBeInTheDocument()
})

it("详情收起后再次展开重新拉取；收起不重复请求", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.resolve({ items: [runRow()], truncated: false })
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    if (path === "/api/v1/agents/runs/run-abcdef1234567890" && options?.method === "GET") {
      return Promise.resolve(runRow({ agent: { name: "ZCode 沙箱智能体", kind: "zcode" }, artifacts: [] }))
    }
    if (path === "/api/v1/agents/runs/run-abcdef1234567890/tool-calls" && options?.method === "GET") {
      return Promise.resolve({ items: [], denied_count: 0 })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<AgentsConsole projectId={projectId} />)
  await user.click(await screen.findByRole("button", { name: "详情" }))
  await screen.findByText("运行详情")
  await user.click(screen.getByRole("button", { name: "收起" }))
  await waitFor(() => expect(screen.queryByText("运行详情")).not.toBeInTheDocument())
  const detailCalls = mocks.apiRequest.mock.calls.filter((call) => String(call[0]) === "/api/v1/agents/runs/run-abcdef1234567890").length
  expect(detailCalls).toBe(1)
})

it("truncated 标记呈现「更早的记录未列出」", async () => {
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.resolve({ items: [runRow()], truncated: true })
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<AgentsConsole projectId={projectId} />)
  expect(await screen.findByText("已显示最近的运行，更早的记录未列出。")).toBeInTheDocument()
})

it("服务端错误（403 等）原样呈现", async () => {
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.reject(new ApiClientError({ code: "project_forbidden", message: "无权访问该项目。" }, 403))
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<AgentsConsole projectId={projectId} />)
  expect(await screen.findByRole("alert")).toHaveTextContent("无权访问该项目。")
})

it("空列表呈现空态文案", async () => {
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.resolve({ items: [], truncated: false })
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<AgentsConsole projectId={projectId} />)
  expect(await screen.findByText("本项目还没有智能体运行记录。")).toBeInTheDocument()
})

// —— T-B1（goal-tb tb2）：产物人工接受面 ——

it("canManage 时产物行可标记复核并回拉详情（PATCH reviewed:true）", async () => {
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: string }) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.resolve({ items: [runRow()], truncated: false })
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    if (path === "/api/v1/agents/runs/run-abcdef1234567890" && options?.method === "GET") {
      return Promise.resolve(runRow({
        agent: { name: "ZCode 沙箱智能体", kind: "zcode" },
        artifacts: [{ id: "art-1", kind: "doc", storage_ref: "output/plan.md", sha256: "a".repeat(64), reviewed: false, linked_solution_id: null }],
      }))
    }
    if (path === "/api/v1/agents/runs/run-abcdef1234567890/artifacts/art-1" && options?.method === "PATCH") {
      expect(options.body).toEqual({ reviewed: true })
      return Promise.resolve({ reviewed: true })
    }
    if (path === "/api/v1/agents/runs/run-abcdef1234567890/tool-calls" && options?.method === "GET") {
      return Promise.resolve({ items: [], denied_count: 0 })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<AgentsConsole projectId={projectId} canManage />)
  fireEvent.click(await screen.findByText("详情"))
  const button = await screen.findByText("标记复核")
  fireEvent.click(button)
  expect(await screen.findByText("已标记复核。")).toBeInTheDocument()
  expect(mocks.apiRequest.mock.calls.some((call) => call[0] === "/api/v1/agents/runs/run-abcdef1234567890/artifacts/art-1")).toBe(true)
})

it("canManage 缺省 false：产物行无复核操作按钮（写闸在服务端，呈现同构显隐）", async () => {
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.resolve({ items: [runRow()], truncated: false })
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    if (path === "/api/v1/agents/runs/run-abcdef1234567890" && options?.method === "GET") {
      return Promise.resolve(runRow({
        agent: { name: "ZCode 沙箱智能体", kind: "zcode" },
        artifacts: [{ id: "art-1", kind: "doc", storage_ref: "output/plan.md", sha256: "a".repeat(64), reviewed: false, linked_solution_id: null }],
      }))
    }
    if (path === "/api/v1/agents/runs/run-abcdef1234567890/tool-calls" && options?.method === "GET") {
      return Promise.resolve({ items: [], denied_count: 0 })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<AgentsConsole projectId={projectId} />)
  fireEvent.click(await screen.findByText("详情"))
  await screen.findByText("未复核")
  expect(screen.queryByText("标记复核")).toBeNull()
})
