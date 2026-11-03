// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  user: { id: "leader-1", role: "admin" },
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))

import { SkillVersionsPage } from "../../src/renderer/src/extensions/SkillVersionsPage"

const versionsPath = "/api/v1/extensions/skills/skill-1/versions"

function versionsPayload(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    skill: {
      id: "skill-1",
      scope: "public",
      key: "weekly-report",
      name: "周报润色",
      status: "published",
      current_version: 2,
      can_edit: true,
    },
    versions: [
      { version: 1, content_sha256: "aaaaaaaaaaaaaaaaaaaa", created_at: "2026-11-01T08:00:00", has_test_report: true, is_current: false },
      { version: 2, content_sha256: "bbbbbbbbbbbbbbbbbbbb", created_at: "2026-11-03T08:00:00", has_test_report: false, is_current: true },
    ],
    usage: {
      total: 3,
      chat: 2,
      workflow: 1,
      last_used_at: "2026-11-04T10:00:00",
      by_version: { "1": 2, "2": 1 },
      truncated: false,
    },
    ...overrides,
  }
}

function publishResponse(): Record<string, unknown> {
  return { skill: { status: "published" }, version: 2, content_sha256: "b" }
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === versionsPath) return Promise.resolve(versionsPayload())
    throw new Error(`unexpected api call: GET ${path}`)
  })
})

afterEach(() => {
  cleanup()
})

function changedSpy(): () => Promise<void> {
  return vi.fn(async () => {})
}

it("renders usage stats and version history with current marker", async () => {
  render(<SkillVersionsPage skill={{ id: "skill-1", name: "周报润色" }} onClose={vi.fn()} onChanged={changedSpy()} />)
  expect(await screen.findByText(/周报润色/)).toBeInTheDocument()
  // usage 块：总数/双消费面/按版本分布
  expect(screen.getByText(/累计消费/)).toBeInTheDocument()
  expect(screen.getByText(/聊天 2 · 工作流 1/)).toBeInTheDocument()
  expect(screen.getByText(/v1 ×2，v2 ×1/)).toBeInTheDocument()
  // 版本表：当前标记（td 内 v2 + strong 分裂渲染）+ 指纹前缀 + 测试报告有无
  expect(screen.getByText("（当前）")).toBeInTheDocument()
  expect(screen.getByText("aaaaaaaaaaaa")).toBeInTheDocument()
  expect(screen.getByText("有")).toBeInTheDocument()
})

it("notes truncated usage honestly", async () => {
  mocks.apiRequest.mockImplementation((path: string) =>
    Promise.resolve(path === versionsPath ? versionsPayload({ usage: { total: 1000, chat: 900, workflow: 100, last_used_at: null, by_version: {}, truncated: true } }) : Promise.reject(new Error(`unexpected ${path}`))),
  )
  render(<SkillVersionsPage skill={{ id: "skill-1", name: "周报润色" }} onClose={vi.fn()} onChanged={changedSpy()} />)
  expect(await screen.findByText(/统计仅覆盖最近 1000 条消费事件/)).toBeInTheDocument()
})

it("publish flow requires password and posts it with waive reason", async () => {
  const user = userEvent.setup()
  const onChanged = changedSpy()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === versionsPath) {
      return Promise.resolve(
        versionsPayload({
          skill: { id: "skill-1", scope: "public", key: "weekly-report", name: "周报润色", status: "in_review", current_version: 2, can_edit: true },
        }),
      )
    }
    if (path === "/api/v1/extensions/skills/skill-1/publish" && options?.method === "POST") {
      expect((options.body as Record<string, unknown>).password).toBe("hunter2")
      expect((options.body as Record<string, unknown>).waive_reason).toBe("治理测试豁免")
      return Promise.resolve(publishResponse())
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<SkillVersionsPage skill={{ id: "skill-1", name: "周报润色" }} onClose={vi.fn()} onChanged={onChanged} />)
  const publish = await screen.findByRole("button", { name: "发布" })
  await user.click(publish)
  await user.type(screen.getByLabelText("密码确认"), "hunter2")
  await user.type(screen.getByLabelText("豁免说明"), "治理测试豁免")
  await user.click(screen.getByRole("button", { name: "确认发布" }))
  await waitFor(() => expect(onChanged).toHaveBeenCalled())
})

it("publish without password is blocked client-side with an honest message", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === versionsPath) {
      return Promise.resolve(
        versionsPayload({
          skill: { id: "skill-1", scope: "public", key: "weekly-report", name: "周报润色", status: "in_review", current_version: 2, can_edit: true },
        }),
      )
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<SkillVersionsPage skill={{ id: "skill-1", name: "周报润色" }} onClose={vi.fn()} onChanged={changedSpy()} />)
  await user.click(await screen.findByRole("button", { name: "发布" }))
  await user.click(screen.getByRole("button", { name: "确认发布" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("密码确认必填。")
  expect(mocks.apiRequest.mock.calls.filter((call) => String(call[0]).endsWith("/publish")).length).toBe(0)
})

it("rollback requires a target version and posts it", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === versionsPath && options?.method === "POST") throw new Error("no lifecycle calls expected here")
    if (path === "/api/v1/extensions/skills/skill-1/rollback" && options?.method === "POST") {
      expect((options.body as Record<string, unknown>).version).toBe(1)
      expect(typeof (options.body as Record<string, unknown>).password).toBe("string")
      return Promise.resolve({ skill: { current_version: 1 }, version: 1 })
    }
    if (path === versionsPath) return Promise.resolve(versionsPayload())
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<SkillVersionsPage skill={{ id: "skill-1", name: "周报润色" }} onClose={vi.fn()} onChanged={changedSpy()} />)
  await user.click(await screen.findByRole("button", { name: "回滚" }))
  await user.type(screen.getByLabelText("密码确认"), "hunter2")
  // 未选版本先拦
  await user.click(screen.getByRole("button", { name: "确认回滚" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("请选择回滚目标版本。")
  await user.selectOptions(screen.getByLabelText("回滚目标版本"), "1")
  await user.click(screen.getByRole("button", { name: "确认回滚" }))
  await waitFor(() => {
    const calls = mocks.apiRequest.mock.calls.filter((call) => String(call[0]).endsWith("/rollback"))
    expect(calls.length).toBe(1)
  })
})

it("surfaces server lifecycle errors (wrong password 403) honestly", async () => {
  const user = userEvent.setup()
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === versionsPath) {
      return Promise.resolve(
        versionsPayload({
          skill: { id: "skill-1", scope: "public", key: "weekly-report", name: "周报润色", status: "in_review", current_version: 2, can_edit: true },
        }),
      )
    }
    if (path === "/api/v1/extensions/skills/skill-1/publish") {
      return Promise.reject(new ApiClientError({ code: "invalid_password", message: "密码确认不匹配。" }, 403))
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<SkillVersionsPage skill={{ id: "skill-1", name: "周报润色" }} onClose={vi.fn()} onChanged={changedSpy()} />)
  await user.click(await screen.findByRole("button", { name: "发布" }))
  await user.type(screen.getByLabelText("密码确认"), "wrong")
  await user.click(screen.getByRole("button", { name: "确认发布" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("密码确认不匹配。")
})

it("shows read-only notice for skills without governance rights", async () => {
  mocks.apiRequest.mockImplementation((path: string) =>
    Promise.resolve(
      path === versionsPath
        ? versionsPayload({ skill: { id: "skill-1", scope: "public", key: "weekly-report", name: "周报润色", status: "published", current_version: 2, can_edit: false } })
        : Promise.reject(new Error(`unexpected ${path}`)),
    ),
  )
  render(<SkillVersionsPage skill={{ id: "skill-1", name: "周报润色" }} onClose={vi.fn()} onChanged={changedSpy()} />)
  expect(await screen.findByText(/只有公共 Skill 运维员或个人 Skill 属主可以执行治理动作/)).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "弃用" })).not.toBeInTheDocument()
})
