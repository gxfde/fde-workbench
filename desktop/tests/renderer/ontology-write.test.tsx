// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

// 桌面第三批 ops3：本体写面（候选生成 / 手工变更集闭集键 / 禁自审 / 关系类型新停）。
const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  user: { id: "leader-1", role: "project_lead" },
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))

import { GlossaryPage } from "../../src/renderer/src/ontology/GlossaryPage"

const projectId = "proj-1"
const base = `/api/v1/projects/${projectId}/ontology`
const extractionsPath = `/api/v1/projects/${projectId}/discovery/extractions?limit=50`

function relationType(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    id: "rt-1",
    scope: "project",
    kind: "subject_type",
    code: "delivery_role",
    label: "交付角色",
    description: null,
    allowed_source_types: [],
    allowed_target_types: [],
    status: "active",
    ...overrides,
  }
}

function baseMock(): void {
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `${base}/terms` || path.startsWith(`${base}/terms?`)) return Promise.resolve({ items: [] })
    if (path === `${base}/relation-types`) return Promise.resolve({ items: [] })
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) return Promise.resolve({ items: [] })
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
}

function postedCalls(): unknown[][] {
  return mocks.apiRequest.mock.calls.filter((call) => call[1]?.method === "POST")
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
  mocks.user = { id: "leader-1", role: "project_lead" }
  baseMock()
})

afterEach(() => {
  cleanup()
})

it("生成候选：只列 review_required 抽取，POST 闭集键并刷新变更集", async () => {
  const user = userEvent.setup()
  let csLoads = 0
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === `${base}/terms` || path.startsWith(`${base}/terms?`)) return Promise.resolve({ items: [] })
    if (path === `${base}/relation-types`) return Promise.resolve({ items: [] })
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) {
      csLoads += 1
      return Promise.resolve({ items: [] })
    }
    if (path === extractionsPath) {
      return Promise.resolve({
        items: [
          { id: "ext-1", source_type: "interview", status: "review_required", completed_at: "2026-11-13T08:00:00" },
          { id: "ext-2", source_type: "interview", status: "completed", completed_at: "2026-11-13T07:00:00" },
        ],
      })
    }
    if (path === `${base}/candidates/generate` && options?.method === "POST") {
      expect(options.body).toEqual({ extraction_id: "ext-1" })
      return Promise.resolve({
        change_set: {
          id: "cs-9", title: "抽取候选", description: null, proposed_json: [],
          diff_summary: "拟新建 2 个术语", status: "draft", base_snapshot_sha256: null,
          captured_from: "discovery:ext-1", rejected_reason: null,
          created_by_user_id: "leader-1", created_at: "2026-11-13T08:00:00",
        },
        created: true,
        skipped: [{ term: "已存在", reason: "同名术语或别名已存在" }],
        cross_project_conflicts: [{ term: "交付物", project_ids: ["proj-2"] }],
      })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<GlossaryPage projectId={projectId} canManage />)
  await user.click(await screen.findByRole("button", { name: "展开候选来源" }))
  expect(await screen.findByText("ext-1")).toBeInTheDocument()
  expect(screen.queryByText("ext-2")).not.toBeInTheDocument()
  await user.click(screen.getAllByRole("button", { name: "生成候选" })[0]!)
  expect(await screen.findByText("已创建候选变更集")).toBeInTheDocument()
  expect(screen.getByText(/跳过 1 项/)).toBeInTheDocument()
  expect(screen.getByText(/跨项目同名告警/)).toBeInTheDocument()
  await waitFor(() => expect(csLoads).toBeGreaterThanOrEqual(2))
})

it("手工变更集：body 闭集（description 缺省不传、无 captured_from）", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === `${base}/terms` || path.startsWith(`${base}/terms?`)) return Promise.resolve({ items: [] })
    if (path === `${base}/relation-types`) return Promise.resolve({ items: [] })
    // POST 分支必须先于 GET 清单分支（path 相同，靠 method 区分）
    if (path === `${base}/change-sets` && options?.method === "POST") {
      expect(options.body).toEqual({
        title: "术语口径修订",
        proposed_json: [
          { action: "create_term", term: "验收标准", definition: "可验证的完成口径", term_type: "metric" },
        ],
      })
      return Promise.resolve({ change_set: { id: "cs-8", title: "术语口径修订", status: "draft" } })
    }
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) return Promise.resolve({ items: [] })
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<GlossaryPage projectId={projectId} canManage />)
  await user.click(await screen.findByRole("button", { name: "手工提变更集" }))
  await user.type(screen.getByLabelText("变更集标题"), "术语口径修订")
  await user.selectOptions(screen.getByLabelText("条目 1 术语类型"), "metric")
  await user.type(screen.getByLabelText("条目 1 术语名"), "验收标准")
  await user.type(screen.getByLabelText("条目 1 定义"), "可验证的完成口径")
  await user.click(screen.getByRole("button", { name: "创建变更集（草稿）" }))
  await waitFor(() => expect(screen.getByText(/变更集已创建/)).toBeInTheDocument())
})

it("同名合并在前端被拦下，不发请求", async () => {
  const user = userEvent.setup()
  render(<GlossaryPage projectId={projectId} canManage />)
  await user.click(await screen.findByRole("button", { name: "手工提变更集" }))
  await user.type(screen.getByLabelText("变更集标题"), "合并修订")
  await user.selectOptions(screen.getByLabelText("条目 1 动作"), "merge_terms")
  await user.type(screen.getByLabelText("条目 1 来源术语"), "同名")
  await user.type(screen.getByLabelText("条目 1 目标术语"), "同名")
  await user.click(screen.getByRole("button", { name: "创建变更集（草稿）" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("不能把术语合并到它自己")
  expect(postedCalls()).toHaveLength(0)
})

it("自审闸：自己提交的 in_review 行禁确认/否决并提示另一管理员", async () => {
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `${base}/terms` || path.startsWith(`${base}/terms?`)) return Promise.resolve({ items: [] })
    if (path === `${base}/relation-types`) return Promise.resolve({ items: [] })
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) {
      return Promise.resolve({
        items: [{
          id: "cs-1", title: "我提的候选", description: null, proposed_json: [],
          diff_summary: "拟新建 1 个术语", status: "in_review", base_snapshot_sha256: "abc",
          captured_from: null, rejected_reason: null, created_by_user_id: "leader-1",
          created_at: "2026-11-13T08:00:00",
        }],
      })
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<GlossaryPage projectId={projectId} canManage />)
  expect(await screen.findByText("我提的候选")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "确认物化" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "否决" })).not.toBeInTheDocument()
  expect(screen.getByText(/另一管理员审阅/)).toBeInTheDocument()
})

it("他人提交的 in_review 行确认按钮照常可用", async () => {
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `${base}/terms` || path.startsWith(`${base}/terms?`)) return Promise.resolve({ items: [] })
    if (path === `${base}/relation-types`) return Promise.resolve({ items: [] })
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) {
      return Promise.resolve({
        items: [{
          id: "cs-2", title: "别人提的候选", description: null, proposed_json: [],
          diff_summary: null, status: "in_review", base_snapshot_sha256: null,
          captured_from: null, rejected_reason: null, created_by_user_id: "admin-2",
          created_at: "2026-11-13T08:00:00",
        }],
      })
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<GlossaryPage projectId={projectId} canManage />)
  expect(await screen.findByText("别人提的候选")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "确认物化" })).toBeEnabled()
})

it("登记 link_type：闭集键 + 端点约束两键（服务端必填的前端同尺）", async () => {
  const user = userEvent.setup()
  mocks.user = { id: "leader-1", role: "admin" }
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === `${base}/terms` || path.startsWith(`${base}/terms?`)) return Promise.resolve({ items: [] })
    if (path === `${base}/relation-types` && options?.method === "GET") {
      return Promise.resolve({ items: [relationType()] })
    }
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) return Promise.resolve({ items: [] })
    if (path === `${base}/relation-types` && options?.method === "POST") {
      expect(options.body).toEqual({
        kind: "link_type",
        code: "escalates_to",
        scope: "project",
        allowed_source_types: ["project", "department"],
        allowed_target_types: ["role"],
      })
      return Promise.resolve({ relation_type: relationType({ kind: "link_type", code: "escalates_to" }), created: true })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<GlossaryPage projectId={projectId} canManage />)
  await user.click(await screen.findByRole("button", { name: "登记类型" }))
  await user.selectOptions(screen.getByLabelText("类型种类"), "link_type")
  await user.type(screen.getByLabelText("类型 code"), "escalates_to")
  await user.type(screen.getByLabelText("源对象类型"), "project, department")
  await user.type(screen.getByLabelText("目标对象类型"), "role")
  await user.click(screen.getByRole("button", { name: "确认登记" }))
  await waitFor(() => expect(screen.getByText("项目类型已登记。")).toBeInTheDocument())
})

it("code 不合法在前端被拦下，不发请求", async () => {
  const user = userEvent.setup()
  render(<GlossaryPage projectId={projectId} canManage />)
  await user.click(await screen.findByRole("button", { name: "登记类型" }))
  await user.type(screen.getByLabelText("类型 code"), "Bad-Code")
  await user.click(screen.getByRole("button", { name: "确认登记" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("code 需小写字母开头")
  expect(postedCalls()).toHaveLength(0)
})

it("非管理员看不到全局范围选项，也停用不了全局行", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `${base}/terms` || path.startsWith(`${base}/terms?`)) return Promise.resolve({ items: [] })
    if (path === `${base}/relation-types`) {
      return Promise.resolve({ items: [relationType({ id: "rt-global", scope: "global", code: "platform_role", label: "平台角色" })] })
    }
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) return Promise.resolve({ items: [] })
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<GlossaryPage projectId={projectId} canManage />)
  await user.click(await screen.findByRole("button", { name: "登记类型" }))
  const scopeSelect = screen.getByLabelText("类型范围")
  const options = Array.from((scopeSelect as HTMLSelectElement).options).map((option) => option.value)
  expect(options).toEqual(["project"])
  expect(screen.queryByRole("button", { name: "停用" })).not.toBeInTheDocument()
  expect(screen.getByText(/全局类型仅系统运维员可停用/)).toBeInTheDocument()
})

it("项目行两步确认后停用（POST 无 body），全局行对管理员可停", async () => {
  const user = userEvent.setup()
  mocks.user = { id: "leader-1", role: "admin" }
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `${base}/terms` || path.startsWith(`${base}/terms?`)) return Promise.resolve({ items: [] })
    if (path === `${base}/relation-types`) {
      return Promise.resolve({ items: [relationType()] })
    }
    if (path === `${base}/change-sets` || path.startsWith(`${base}/change-sets?`)) return Promise.resolve({ items: [] })
    if (path === `${base}/relation-types/rt-1/retire` && options?.method === "POST") {
      return Promise.resolve({ relation_type: relationType({ status: "retired" }) })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<GlossaryPage projectId={projectId} canManage />)
  await user.click(await screen.findByRole("button", { name: "停用" }))
  await user.click(screen.getByRole("button", { name: "确认停用" }))
  await waitFor(() => expect(screen.getByText(/已停用：禁新边/)).toBeInTheDocument())
  const retireCall = mocks.apiRequest.mock.calls.find((call) => String(call[0]).endsWith("/retire"))
  expect(retireCall).toBeTruthy()
  expect((retireCall![1] as { method?: string }).method).toBe("POST")
  expect((retireCall![1] as { body?: unknown }).body).toBeUndefined()
})
