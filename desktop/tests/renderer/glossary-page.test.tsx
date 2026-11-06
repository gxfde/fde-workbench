// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
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

it("renders the server term status domain with Chinese labels (CR-040)", async () => {
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `${base}/terms` || path.startsWith(`${base}/terms?`)) {
      return Promise.resolve({
        items: [
          term({ id: "term-draft", term: "草稿术语", status: "draft" }),
          term({ id: "term-superseded", term: "旧口径术语", status: "superseded" }),
          term({ id: "term-merged", term: "并入术语", status: "merged" }),
        ],
      })
    }
    if (path === `${base}/relation-types`) return Promise.resolve({ items: [] })
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) {
      return Promise.resolve({ items: [] })
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<GlossaryPage projectId={projectId} canManage={false} />)
  const table = within(await screen.findByRole("table"))
  expect(table.getByText("草稿")).toBeInTheDocument()
  expect(table.getByText("已取代")).toBeInTheDocument()
  expect(table.getByText("已合并")).toBeInTheDocument()
  // 服务端值域无 candidate/retired → 旧标签不得再出现
  expect(table.queryByText("候选")).not.toBeInTheDocument()
  expect(table.queryByText("已退役")).not.toBeInTheDocument()
})

it("keeps the newest search result when an older response arrives later (CR-035)", async () => {
  const user = userEvent.setup()
  const pending: Array<(value: { items: Array<Record<string, unknown>> }) => void> = []
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `${base}/terms`) return Promise.resolve({ items: [term({ term: "初始术语" })] })
    if (path.startsWith(`${base}/terms?`)) {
      return new Promise((resolve) => {
        pending.push(resolve as (value: { items: Array<Record<string, unknown>> }) => void)
      })
    }
    if (path === `${base}/relation-types`) return Promise.resolve({ items: [] })
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) {
      return Promise.resolve({ items: [] })
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<GlossaryPage projectId={projectId} canManage={false} />)
  await screen.findByText("初始术语")
  const input = screen.getByLabelText("搜索术语")
  await user.type(input, "验")
  await user.type(input, "收")
  await waitFor(() => expect(pending.length).toBe(2))
  await act(async () => {
    pending[1]!({ items: [term({ term: "新结果" })] })
  })
  expect(await screen.findByText("新结果")).toBeInTheDocument()
  // 旧请求后到：不得覆盖新结果（序列守卫）
  await act(async () => {
    pending[0]!({ items: [term({ term: "旧结果" })] })
  })
  expect(screen.getByText("新结果")).toBeInTheDocument()
  expect(screen.queryByText("旧结果")).not.toBeInTheDocument()
})

it("keeps the current list visible while a new search is in flight (CR-035)", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `${base}/terms`) return Promise.resolve({ items: [term({ term: "初始术语" })] })
    if (path.startsWith(`${base}/terms?`)) return new Promise(() => {})
    if (path === `${base}/relation-types`) return Promise.resolve({ items: [] })
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) {
      return Promise.resolve({ items: [] })
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<GlossaryPage projectId={projectId} canManage={false} />)
  await screen.findByText("初始术语")
  await user.type(screen.getByLabelText("搜索术语"), "验")
  // 搜索在途：旧内容仍在（不闪空），整页 loading 文案不出现
  expect(screen.getByText("初始术语")).toBeInTheDocument()
  expect(screen.queryByText("正在加载术语表…")).not.toBeInTheDocument()
})

function impact(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    term: term(),
    resolved: { canonical_term_id: "term-1", lineage_term_ids: ["term-1"] },
    subjects: [
      {
        id: "subj-1",
        subject_key: "S-001",
        name: "交付物",
        subject_type: "artifact",
        status: "active",
        merged_into_subject_id: null,
        matched_via: "term",
        matched_term_id: "term-1",
      },
    ],
    links: [
      {
        id: "link-1",
        link_type: "belongs_to",
        source_subject_id: "subj-1",
        source_subject_name: "交付物",
        target_subject_id: "subj-2",
        target_subject_name: "里程碑",
      },
    ],
    forms: [
      {
        id: "form-1",
        form_key: "delivery-brief",
        name: "交付简报",
        subject_id: "subj-1",
        subject_name: "交付物",
        current_revision_status: "confirmed",
      },
    ],
    counts: { subjects: 1, links: 1, forms: 1 },
    ...overrides,
  }
}

function withImpactMock(payload: unknown): void {
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `${base}/terms` || path.startsWith(`${base}/terms?`)) {
      return Promise.resolve({ items: [term()] })
    }
    if (path === `${base}/relation-types`) return Promise.resolve({ items: [] })
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) {
      return Promise.resolve({ items: [] })
    }
    if (path === `${base}/terms/term-1/impact`) return Promise.resolve(payload)
    throw new Error(`unexpected api call: ${path}`)
  })
}

it("expands the per-term impact panel with the three-face list (T-I1 接线)", async () => {
  const user = userEvent.setup()
  withImpactMock(impact())
  render(<GlossaryPage projectId={projectId} canManage={false} />)
  await user.click(await screen.findByRole("button", { name: "影响分析" }))
  // 计数行 + subjects 命中溯源 + 邻接边 + 表单
  expect(await screen.findByText(/调研对象 1 · 关联边 1 · 表单 1/)).toBeInTheDocument()
  expect(screen.getByText(/S-001/)).toBeInTheDocument()
  expect(screen.getByText(/命中经 规范名/)).toBeInTheDocument()
  expect(screen.getByText(/belongs_to/)).toBeInTheDocument()
  expect(screen.getByText(/交付简报/)).toBeInTheDocument()
})

it("notes lineage resolution when querying a merged term", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `${base}/terms` || path.startsWith(`${base}/terms?`)) {
      return Promise.resolve({ items: [term({ id: "term-old", term: "旧名", canonical_term_id: "term-1", status: "merged" })] })
    }
    if (path === `${base}/relation-types`) return Promise.resolve({ items: [] })
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) {
      return Promise.resolve({ items: [] })
    }
    if (path === `${base}/terms/term-old/impact`) {
      return Promise.resolve(
        impact({
          term: term({ id: "term-old", term: "旧名", canonical_term_id: "term-1", status: "merged" }),
          resolved: { canonical_term_id: "term-1", lineage_term_ids: ["term-1", "term-old"] },
        }),
      )
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<GlossaryPage projectId={projectId} canManage={false} />)
  await user.click(await screen.findByRole("button", { name: "影响分析" }))
  expect(await screen.findByText(/并入行：已解析到存活概念/)).toBeInTheDocument()
  expect(screen.getByText(/血缘 2 行/)).toBeInTheDocument()
})

it("surfaces impact fetch failure inside the panel", async () => {
  const user = userEvent.setup()
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `${base}/terms` || path.startsWith(`${base}/terms?`)) {
      return Promise.resolve({ items: [term()] })
    }
    if (path === `${base}/relation-types`) return Promise.resolve({ items: [] })
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) {
      return Promise.resolve({ items: [] })
    }
    if (path === `${base}/terms/term-1/impact`) {
      return Promise.reject(new ApiClientError({ code: "term_not_found", message: "术语不存在。" }, 404))
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<GlossaryPage projectId={projectId} canManage={false} />)
  await user.click(await screen.findByRole("button", { name: "影响分析" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("术语不存在。")
})

it("keeps only the newest impact response when switching rows (序列守卫)", async () => {
  const user = userEvent.setup()
  const pending: Array<(value: Record<string, unknown>) => void> = []
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `${base}/terms` || path.startsWith(`${base}/terms?`)) {
      return Promise.resolve({
        items: [term({ term: "术语甲" }), term({ id: "term-2", term: "术语乙" })],
      })
    }
    if (path === `${base}/relation-types`) return Promise.resolve({ items: [] })
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) {
      return Promise.resolve({ items: [] })
    }
    if (path === `${base}/terms/term-1/impact` || path === `${base}/terms/term-2/impact`) {
      return new Promise((resolve) => {
        pending.push(resolve as (value: Record<string, unknown>) => void)
      })
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<GlossaryPage projectId={projectId} canManage={false} />)
  const buttons = await screen.findAllByRole("button", { name: "影响分析" })
  expect(buttons).toHaveLength(2)
  await user.click(buttons[0]!) // 术语甲：在途
  await user.click(buttons[1]!) // 术语乙：在途（甲的面板被顶替）
  await waitFor(() => expect(pending.length).toBe(2))
  await act(async () => {
    pending[1]!({ ...impact(), term: term({ id: "term-2", term: "术语乙" }) })
  })
  expect(await screen.findByText(/调研对象 1 · 关联边 1 · 表单 1/)).toBeInTheDocument()
  // 甲的旧响应后到：不得顶掉乙的面板（序列守卫）
  await act(async () => {
    pending[0]!({ ...impact(), term: term({ term: "术语甲" }) })
  })
  await waitFor(() => {
    expect(screen.getAllByText(/调研对象 1 · 关联边 1 · 表单 1/).length).toBe(1)
  })
})
