// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  user: { id: "leader-1", role: "project_lead" },
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))

import { MeetingsConsole } from "../../src/renderer/src/meetings/MeetingsConsole"

const projectId = "proj-ta8"

function meetingRow(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    id: "meeting-abcdef1234567890",
    project_id: projectId,
    template_id: "T2-lite",
    status: "live",
    gate_tier: "lite",
    trigger: "mandatory",
    topic_refs: {},
    turn_budget: 2,
    hosted_by_user_id: "user-1",
    triggered_by_run_id: null,
    convened_by_agent_id: null,
    min_difficulty: null,
    degraded: false,
    created_at: "2026-11-07T08:00:00",
    turns_count: 2,
    ...overrides,
  }
}

function minutesFixture(): Record<string, unknown> {
  return {
    id: "minutes-1",
    meeting_id: "meeting-abcdef1234567890",
    consensus: [{ text: "产物结构与引用闭合，通过", source_refs: [] }],
    disputes: [{ text: "交付边界仍需客户确认", source_refs: [] }],
    todos: [],
    sealed_sha256: "b".repeat(64),
    created_at: "2026-11-07T09:00:00",
  }
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it("渲染会议列表（状态/门档/话轮计数预聚合）", async () => {
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `/api/v1/meetings?project_id=${projectId}`) {
      return Promise.resolve({ items: [meetingRow()], truncated: false })
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<MeetingsConsole projectId={projectId} />)
  expect(await screen.findByText("进行中")).toBeInTheDocument()
  expect(screen.getByText("轻量门")).toBeInTheDocument()
  expect(screen.getByText("强制门")).toBeInTheDocument()
  expect(screen.getByText("2")).toBeInTheDocument() // 话轮计数（列表行预聚合，不发额外请求）
  expect(mocks.apiRequest.mock.calls.length).toBe(1)
})

it("详情展开呈现话轮流；live 会议不拉纪要", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `/api/v1/meetings?project_id=${projectId}`) {
      return Promise.resolve({ items: [meetingRow()], truncated: false })
    }
    if (path === "/api/v1/meetings/meeting-abcdef1234567890" && options?.method === "GET") {
      return Promise.resolve(meetingRow({
        turns: [
          { seq: 1, speaker_agent_id: "agent-1", speaker_user_id: null, content: { text: "产物引用闭合" } },
          { seq: 2, speaker_agent_id: null, speaker_user_id: "user-1", content: { text: "确认通过" } },
        ],
      }))
    }
    if ((path as string).endsWith("/minutes")) {
      throw new Error("live 会议不应拉取纪要")
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<MeetingsConsole projectId={projectId} />)
  await user.click(await screen.findByRole("button", { name: "详情" }))
  expect(await screen.findByText("产物引用闭合")).toBeInTheDocument()
  expect(screen.getByText("确认通过")).toBeInTheDocument()
  expect(screen.getByText(/会议收敛后生成纪要/)).toBeInTheDocument()
})

it("closed 会议详情呈现纪要三段式与封存指纹", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `/api/v1/meetings?project_id=${projectId}`) {
      return Promise.resolve({ items: [meetingRow({ status: "closed" })], truncated: false })
    }
    if (path === "/api/v1/meetings/meeting-abcdef1234567890" && options?.method === "GET") {
      return Promise.resolve(meetingRow({ status: "closed", turns: [{ seq: 1, speaker_agent_id: "agent-1", speaker_user_id: null, content: { text: "评审完成" } }] }))
    }
    if (path === "/api/v1/meetings/meeting-abcdef1234567890/minutes" && options?.method === "GET") {
      return Promise.resolve(minutesFixture())
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<MeetingsConsole projectId={projectId} />)
  await user.click(await screen.findByRole("button", { name: "详情" }))
  expect(await screen.findByText("纪要（已封存）")).toBeInTheDocument()
  expect(screen.getByText("产物结构与引用闭合，通过")).toBeInTheDocument()
  expect(screen.getByText("交付边界仍需客户确认")).toBeInTheDocument()
  expect(screen.getByText(/bbbbbbbbbbbbbbbb…/)).toBeInTheDocument()
})

it("truncated 与空态", async () => {
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `/api/v1/meetings?project_id=${projectId}`) {
      return Promise.resolve({ items: [], truncated: true })
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<MeetingsConsole projectId={projectId} />)
  expect(await screen.findByText("本项目还没有评审会议。")).toBeInTheDocument()
  expect(screen.getByText("已显示最近的会议，更早的记录未列出。")).toBeInTheDocument()
})

it("服务端错误原样呈现", async () => {
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `/api/v1/meetings?project_id=${projectId}`) {
      return Promise.reject(new ApiClientError({ code: "project_forbidden", message: "无权访问该项目。" }, 403))
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<MeetingsConsole projectId={projectId} />)
  expect(await screen.findByRole("alert")).toHaveTextContent("无权访问该项目。")
})
