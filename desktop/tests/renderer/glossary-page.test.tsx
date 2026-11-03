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

import { GlossaryPage } from "../../src/renderer/src/ontology/GlossaryPage"

const projectId = "proj-1"
const base = `/api/v1/projects/${projectId}/ontology`

function term(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    id: "term-1",
    term: "交付物",
    term_type: "artifact",
    definition: "项目产出的可交付成果",
    status: "confirmed",
    version: 1,
    canonical_term_id: null,
    updated_at: "2026-11-04T08:00:00",
    ...overrides,
  }
}

function changeSet(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    id: "cs-1",
    title: "导入合并候选",
    description: null,
    proposed_json: [{ action: "create_term", term: "验收标准", kind: "artifact" }],
    diff_summary: "拟新建 1 个术语",
    status: "in_review",
    base_snapshot_sha256: "abc123",
    captured_from: "research_import:prev-1",
    rejected_reason: null,
    created_at: "2026-11-04T08:00:00",
    ...overrides,
  }
}

function mockApi(): void {
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `${base}/terms` || path.startsWith(`${base}/terms?`)) {
      return Promise.resolve({ items: [term()] })
    }
    if (path === `${base}/relation-types`) {
      return Promise.resolve({
        items: [
          {
            id: "rt-1",
            scope: "project",
            kind: "hierarchical",
            code: "belongs_to",
            label: "属于",
            description: null,
            allowed_source_types: ["artifact"],
            allowed_target_types: ["milestone"],
            status: "active",
          },
        ],
      })
    }
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) {
      return Promise.resolve({ items: [changeSet()] })
    }
    if (path === `${base}/change-sets/cs-1` && options?.method === "GET") {
      return Promise.resolve({ change_set: changeSet() })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
  mockApi()
})

afterEach(() => {
  cleanup()
})

it("renders terms, relation types and change sets read-only", async () => {
  render(<GlossaryPage projectId={projectId} canManage={false} />)
  expect(await screen.findByText("交付物")).toBeInTheDocument()
  expect(screen.getByText("属于")).toBeInTheDocument()
  expect(screen.getByText("导入合并候选")).toBeInTheDocument()
  // 徽标与状态过滤 option 同文——断言至少出现在徽标里
  expect((await screen.findAllByText("评审中")).length).toBeGreaterThan(0)
  // 无 canManage：生命周期按钮不出现
  expect(screen.queryByRole("button", { name: "提交评审" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "确认物化" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "否决" })).not.toBeInTheDocument()
})

it("search forwards q parameter to the terms endpoint", async () => {
  const user = userEvent.setup()
  render(<GlossaryPage projectId={projectId} canManage={false} />)
  await user.type(await screen.findByLabelText("搜索术语"), "验收{enter}")
  await waitFor(() => {
    const calls = mocks.apiRequest.mock.calls.filter((call) => String(call[0]).startsWith(`${base}/terms?`))
    expect(calls.length).toBeGreaterThan(0)
    expect(String(calls[calls.length - 1]![0])).toContain("q=")
  })
})

it("expands change-set payload with base fingerprint and actions", async () => {
  const user = userEvent.setup()
  render(<GlossaryPage projectId={projectId} canManage />)
  await user.click(await screen.findByRole("button", { name: "评审载荷" }))
  expect(await screen.findByText("create_term · 验收标准 · artifact")).toBeInTheDocument()
  expect(screen.getByText(/abc123/)).toBeInTheDocument()
})

it("confirm posts and replaces the row with the confirmed state", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `${base}/terms` || path.startsWith(`${base}/terms?`)) return Promise.resolve({ items: [] })
    if (path === `${base}/relation-types`) return Promise.resolve({ items: [] })
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) {
      return Promise.resolve({ items: [changeSet()] })
    }
    if (path === `${base}/change-sets/cs-1/confirm` && options?.method === "POST") {
      return Promise.resolve({ change_set: changeSet({ status: "confirmed" }) })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<GlossaryPage projectId={projectId} canManage />)
  await user.click(await screen.findByRole("button", { name: "确认物化" }))
  await waitFor(() => expect(screen.getAllByText("已确认").length).toBeGreaterThan(1)) // 徽标翻转为已确认（option 恒占其一）
})

it("surfaces server rejection (self-confirm 403) honestly", async () => {
  const user = userEvent.setup()
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `${base}/terms` || path.startsWith(`${base}/terms?`)) return Promise.resolve({ items: [] })
    if (path === `${base}/relation-types`) return Promise.resolve({ items: [] })
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) {
      return Promise.resolve({ items: [changeSet()] })
    }
    if (path === `${base}/change-sets/cs-1/confirm`) {
      return Promise.reject(new ApiClientError({ code: "forbidden", message: "提交人不能确认自己的变更集。" }, 403))
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<GlossaryPage projectId={projectId} canManage />)
  await user.click(await screen.findByRole("button", { name: "确认物化" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("提交人不能确认自己的变更集。")
})

it("reject stays disabled without a reason and posts it once filled", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === `${base}/terms` || path.startsWith(`${base}/terms?`)) return Promise.resolve({ items: [] })
    if (path === `${base}/relation-types`) return Promise.resolve({ items: [] })
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) {
      return Promise.resolve({ items: [changeSet()] })
    }
    if (path === `${base}/change-sets/cs-1/reject`) {
      expect((options?.body as { reason?: string }).reason).toBe("术语口径不对")
      return Promise.resolve({ change_set: changeSet({ status: "rejected", rejected_reason: "术语口径不对" }) })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<GlossaryPage projectId={projectId} canManage />)
  const reject = await screen.findByRole("button", { name: "否决" })
  expect(reject).toBeDisabled()
  await user.type(screen.getByLabelText("否决理由"), "术语口径不对")
  await user.click(screen.getByRole("button", { name: "否决" }))
  await waitFor(() => expect(screen.getByText("已否决")).toBeInTheDocument())
})
