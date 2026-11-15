// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

// 桌面第三批 ops3：方案 AI 生成（generate-agent 闭集键 / wired 双态 / 溯源联动）。
const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))

import { SolutionAgentGenerator } from "../../src/renderer/src/solutions/SolutionDetailPage"
import { emptySolution } from "../../src/renderer/src/solutions/types"
import type { SolutionDto } from "../../src/renderer/src/solutions/types"

function solution(overrides: Partial<SolutionDto> = {}): SolutionDto {
  return {
    ...emptySolution(),
    id: "s1",
    project_id: "p1",
    name: "方案甲",
    opportunity_ids: [],
    opportunities: [],
    version: 1,
    status: "active",
    updated_at: "2026-11-13T08:00:00Z",
    ...overrides,
  }
}

function agentsPayload(): { items: Array<Record<string, unknown>> } {
  return {
    items: [
      { id: "agent-sol", kind: "module", name: "方案智能体", enabled: true, capability_tier: "agent.module.solution", sandbox_profile: "sandbox", max_cost_units: 10, max_duration_ms: 1000, allowed_tools: [], available: true, unavailable_reason: null },
      { id: "agent-off", kind: "module", name: "缺凭据智能体", enabled: true, capability_tier: "agent.module.solution", sandbox_profile: "sandbox", max_cost_units: 10, max_duration_ms: 1000, allowed_tools: [], available: false, unavailable_reason: "credential_missing" },
      { id: "agent-other", kind: "module", name: "验收智能体", enabled: true, capability_tier: "agent.module.acceptance", sandbox_profile: "sandbox", max_cost_units: 10, max_duration_ms: 1000, allowed_tools: [], available: true, unavailable_reason: null },
    ],
  }
}

function wiredResponse(next: SolutionDto): Record<string, unknown> {
  return { solution_id: next.id, wired: true, wired_now: true, agent_run_id: "run-1", solution: next }
}

function baseMock(): void {
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === "/api/v1/agents" && options?.method === "GET") return Promise.resolve(agentsPayload())
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

it("默认选中可用的方案档智能体，不可用项禁选并展示原因", async () => {
  render(<SolutionAgentGenerator projectId="p1" solution={solution()} onWired={() => {}} />)
  const select = (await screen.findByLabelText("智能体")) as HTMLSelectElement
  await waitFor(() => expect(select.value).toBe("agent-sol"))
  const options = Array.from(select.options)
  expect(options.find((option) => option.value === "agent-off")!.disabled).toBe(true)
  expect(options.find((option) => option.value === "agent-off")!.textContent).toContain("credential_missing")
  expect(options.find((option) => option.value === "agent-sol")!.disabled).toBe(false)
})

it("闭集 body：无幂等键只发 {agent_id}，wired=true 刷新 solution（溯源联动）", async () => {
  const user = userEvent.setup()
  const onWired = vi.fn()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === "/api/v1/agents" && options?.method === "GET") return Promise.resolve(agentsPayload())
    if (path === "/api/v1/projects/p1/solutions/s1/generate-agent" && options?.method === "POST") {
      expect(options.body).toEqual({ agent_id: "agent-sol" })
      return Promise.resolve(wiredResponse(solution({ generated_by: "agent", agent_run_id: "run-1" })))
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<SolutionAgentGenerator projectId="p1" solution={solution()} onWired={onWired} />)
  await user.click(await screen.findByRole("button", { name: "发起 AI 生成" }))
  await waitFor(() => expect(onWired).toHaveBeenCalledTimes(1))
  expect(onWired).toHaveBeenCalledWith(solution({ generated_by: "agent", agent_run_id: "run-1" }))
  expect(await screen.findByText(/溯源徽标已更新/)).toBeInTheDocument()
})

it("填幂等键时 body 为双键闭集；超 160 字客户端拦截不发请求", async () => {
  const user = userEvent.setup()
  let postCount = 0
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === "/api/v1/agents" && options?.method === "GET") return Promise.resolve(agentsPayload())
    if (path === "/api/v1/projects/p1/solutions/s1/generate-agent" && options?.method === "POST") {
      postCount += 1
      expect(options.body).toEqual({ agent_id: "agent-sol", idempotency_key: "k1" })
      return Promise.resolve({ solution_id: "s1", wired: false, run: { status: "queued" } })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<SolutionAgentGenerator projectId="p1" solution={solution()} onWired={() => {}} />)
  await user.type(await screen.findByLabelText("幂等键（可选）"), "k1")
  await user.click(screen.getByRole("button", { name: "发起 AI 生成" }))
  await waitFor(() => expect(postCount).toBe(1))
  await user.clear(screen.getByLabelText("幂等键（可选）"))
  await user.type(screen.getByLabelText("幂等键（可选）"), "x".repeat(161))
  await user.click(screen.getByRole("button", { name: "发起 AI 生成" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("幂等键最长 160 字符")
  expect(postCount).toBe(1)
})

it("wired=false：呈现 run.status 并放行跳转智能体控制台", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === "/api/v1/agents" && options?.method === "GET") return Promise.resolve(agentsPayload())
    if (path === "/api/v1/projects/p1/solutions/s1/generate-agent" && options?.method === "POST") {
      return Promise.resolve({ solution_id: "s1", wired: false, run: { status: "queued" } })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<SolutionAgentGenerator projectId="p1" solution={solution()} onWired={() => {}} />)
  await user.click(await screen.findByRole("button", { name: "发起 AI 生成" }))
  const link = await screen.findByRole("link", { name: "前往智能体运行查看" })
  expect(link).toHaveAttribute("href", "#projects/p1?tab=agents")
  expect(screen.getByText(/状态：queued/)).toBeInTheDocument()
})

it("服务端闸（409 solution_archived）原样呈现", async () => {
  const user = userEvent.setup()
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === "/api/v1/agents" && options?.method === "GET") return Promise.resolve(agentsPayload())
    if (path === "/api/v1/projects/p1/solutions/s1/generate-agent" && options?.method === "POST") {
      return Promise.reject(new ApiClientError({ code: "solution_archived", message: "该方案已弃用，不能发起生成。" }, 409))
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<SolutionAgentGenerator projectId="p1" solution={solution()} onWired={() => {}} />)
  await user.click(await screen.findByRole("button", { name: "发起 AI 生成" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("弃用")
})
