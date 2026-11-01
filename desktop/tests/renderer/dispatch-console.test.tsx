// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  user: { id: "admin-1", role: "admin" } as { id: string; role: string },
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))

import { ConsolePage, statusActionLabel } from "../../src/renderer/src/dispatch/ConsolePage"
import { DispatchPage } from "../../src/renderer/src/dispatch/DispatchPage"
import { parseHashRoute } from "../../src/renderer/src/routing/useHashRoute"

function packageRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "pkg-1",
    package_code: "PKG-B2CON-01",
    scope_summary: "交付物 A/B",
    deliverables_json: "交付物 A/B",
    acceptance_criteria: "口径条款逐项可判",
    data_systems: "ERP",
    schedule_text: "远程交付",
    risks_dependencies: "无",
    business_category: "PoV验证",
    client_code: "b2 企业·制造·苏州",
    client_city: "苏州",
    onsite_required: false,
    onsite_visits: null,
    deadline: "2026-12-31",
    delivery_seat_amount: 8000,
    dispatch_status: "published",
    dispatch_round: 1,
    dispatch_mode: "assign",
    response_window_hours: 24,
    published_at: "2026-10-31T12:00:00+00:00",
    ...overrides,
  }
}

function profileRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    user_id: "fde-1",
    username: "zhang.san",
    display_name: "张三",
    level: "L2",
    status: "active",
    scores: {
      biz_cognition: 3,
      scenario_eng: 3,
      ai_tech: 4,
      delivery_assure: 3,
    },
    industry_tags: ["制造业"],
    module_tags: ["ERP"],
    home_city: "苏州",
    geo_fence_km: 50,
    monthly_capacity_hours: 160,
    avg_delivery_hours: 40,
    in_hand: 1,
    capacity_cap: 4,
    ...overrides,
  }
}

function offerTrailRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    offer_id: "offer-1",
    candidate_user_id: "fde-1",
    candidate_username: "zhang.san",
    candidate_display_name: "张三",
    dispatch_round: 1,
    mode: "assign",
    status: "offered",
    version: 3,
    rank: 1,
    explanation: "L2 · 行业匹配 · 地理 T1",
    offered_at: "2026-10-31T12:00:00+00:00",
    responded_at: null,
    deadline: "2026-11-01T12:00:00+00:00",
    ...overrides,
  }
}

/** 按 (method, path) 路由的 apiRequest 桩：GET 回固定夹具，POST 记录调用。 */
function stubApi(options: {
  packages?: unknown[]
  profiles?: unknown[]
  offers?: Record<string, unknown[]>
  matchResult?: unknown
}) {
  const posts: { path: string; body: unknown }[] = []
  mocks.apiRequest.mockImplementation(
    (path: string, init?: { method?: string; body?: unknown }) => {
      const method = init?.method ?? "GET"
      if (method !== "GET") {
        posts.push({ path, body: init?.body })
        if (path.endsWith("/match") && options.matchResult !== undefined) {
          return Promise.resolve(options.matchResult)
        }
        return Promise.resolve(null)
      }
      if (path === "/api/v1/dispatch/packages") {
        return Promise.resolve(options.packages ?? [])
      }
      if (path === "/api/v1/dispatch/profiles") {
        return Promise.resolve(options.profiles ?? [])
      }
      const trail = path.match(/\/api\/v1\/dispatch\/packages\/([^/]+)\/offers$/)
      if (trail) {
        return Promise.resolve(options.offers?.[trail[1]] ?? [])
      }
      return Promise.reject(new Error(`unexpected GET ${path}`))
    }
  )
  return posts
}

beforeEach(() => {
  mocks.user = { id: "admin-1", role: "admin" }
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// 纯函数与路由
// ---------------------------------------------------------------------------

it("parseHashRoute recognizes #dispatch/console", () => {
  expect(parseHashRoute("#dispatch/console")).toEqual({
    kind: "dispatch",
    tab: "console",
  })
})

it("statusActionLabel maps lifecycle status to console action", () => {
  expect(statusActionLabel("draft")).toBe("发布")
  expect(statusActionLabel("withdrawn")).toBe("重新发布")
  expect(statusActionLabel("rejected")).toBe("重新发布")
  expect(statusActionLabel("expired")).toBe("重新发布")
  expect(statusActionLabel("published")).toBe("撮合/指派")
  expect(statusActionLabel("accepted")).toBeNull()
})

// ---------------------------------------------------------------------------
// 调度台 tab 可见性（角色门）
// ---------------------------------------------------------------------------

it("hides console tab for non-platform role", () => {
  mocks.user = { id: "fde-1", role: "fde_engineer" }
  stubApi({})
  render(<DispatchPage tab="pool" onTabChange={() => {}} />)
  expect(screen.getByRole("button", { name: "派单池" })).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "调度台" })).not.toBeInTheDocument()
})

it("shows console tab for admin and renders console page", async () => {
  stubApi({
    packages: [packageRow()],
    profiles: [profileRow()],
  })
  render(<DispatchPage tab="console" onTabChange={() => {}} />)
  expect(screen.getByRole("button", { name: "调度台" })).toBeInTheDocument()
  expect(await screen.findByText("PKG-B2CON-01")).toBeInTheDocument()
  expect(screen.getByText("供给池候选（勾选后用于发布授权 / 指派 offer）")).toBeInTheDocument()
  expect(screen.getByText("张三")).toBeInTheDocument()
})

// ---------------------------------------------------------------------------
// 调度台操作面
// ---------------------------------------------------------------------------

it("publishes draft package with selected candidates", async () => {
  const user = userEvent.setup()
  const posts = stubApi({
    packages: [packageRow({ dispatch_status: "draft" })],
    profiles: [profileRow(), profileRow({ user_id: "fde-2", display_name: "李四" })],
  })
  render(<ConsolePage />)
  await screen.findByText("PKG-B2CON-01")

  await user.click(screen.getByRole("checkbox", { name: /张三/ }))
  await user.click(screen.getByRole("checkbox", { name: /李四/ }))
  await user.click(await screen.findByText("PKG-B2CON-01"))
  const publish = await screen.findByRole("button", { name: "发布（已选 2 候选）" })
  await user.click(publish)

  await waitFor(() => {
    const call = posts.find((item) => item.path === "/api/v1/dispatch/packages/pkg-1/publish")
    expect(call).toBeDefined()
    expect(call?.body).toEqual({ candidate_user_ids: ["fde-1", "fde-2"] })
  })
})

it("runs match on published package and renders explainable result", async () => {
  const user = userEvent.setup()
  stubApi({
    packages: [packageRow({ dispatch_status: "published" })],
    profiles: [profileRow()],
    matchResult: {
      scenario: "B",
      offers: [
        {
          offer_id: "offer-1",
          candidate_user_id: "fde-1",
          rank: 1,
          explanation: "加权 0.82 · 行业匹配",
        },
      ],
      rejected: ["fde-9"],
      rule_version: 3,
    },
  })
  render(<ConsolePage />)
  await screen.findByText("PKG-B2CON-01")
  await user.click(await screen.findByText("PKG-B2CON-01"))
  await user.click(screen.getByRole("button", { name: "执行撮合" }))

  expect(
    await screen.findByText(/场景 B（远程·加权排序）\s*·\s*规则版本 v3/)
  ).toBeInTheDocument()
  expect(screen.getByText(/Top1 · 候选 fde-1 · 加权 0.82 · 行业匹配/)).toBeInTheDocument()
  expect(screen.getByText("资格门淘汰 1 人。")).toBeInTheDocument()
})

it("assigns offers to selected candidates on published package", async () => {
  const user = userEvent.setup()
  const posts = stubApi({
    packages: [packageRow({ dispatch_status: "published" })],
    profiles: [profileRow()],
  })
  render(<ConsolePage />)
  await screen.findByText("PKG-B2CON-01")
  await user.click(screen.getByRole("checkbox", { name: /张三/ }))
  await user.click(await screen.findByText("PKG-B2CON-01"))
  await user.click(screen.getByRole("button", { name: "指派 offer（已选 1 候选）" }))

  await waitFor(() => {
    const call = posts.find((item) => item.path === "/api/v1/dispatch/packages/pkg-1/offers")
    expect(call).toBeDefined()
    expect(call?.body).toEqual({ candidate_user_ids: ["fde-1"] })
  })
})

it("withdraws published package", async () => {
  const user = userEvent.setup()
  const posts = stubApi({
    packages: [packageRow({ dispatch_status: "published" })],
    profiles: [],
  })
  render(<ConsolePage />)
  await screen.findByText("PKG-B2CON-01")
  await user.click(await screen.findByText("PKG-B2CON-01"))
  await user.click(screen.getByRole("button", { name: "撤回" }))

  await waitFor(() => {
    expect(
      posts.find((item) => item.path === "/api/v1/dispatch/packages/pkg-1/withdraw")
    ).toBeDefined()
  })
})

it("requires reason before level override on draft package", async () => {
  const user = userEvent.setup()
  const posts = stubApi({
    packages: [packageRow({ dispatch_status: "draft" })],
    profiles: [],
  })
  render(<ConsolePage />)
  await screen.findByText("PKG-B2CON-01")
  await user.click(await screen.findByText("PKG-B2CON-01"))
  await user.click(screen.getByRole("button", { name: "等级覆盖" }))
  await user.click(screen.getByRole("button", { name: "提交覆盖" }))

  expect(
    await screen.findByText("等级覆盖必须写明 reason（§4.5 留痕）。")
  ).toBeInTheDocument()
  expect(
    posts.find((item) => item.path === "/api/v1/dispatch/packages/pkg-1/required-level")
  ).toBeUndefined()

  await user.type(screen.getByLabelText("覆盖原因"), "客户指定高级工程师")
  await user.click(screen.getByRole("button", { name: "提交覆盖" }))
  await waitFor(() => {
    const call = posts.find(
      (item) => item.path === "/api/v1/dispatch/packages/pkg-1/required-level"
    )
    expect(call?.body).toEqual({ level: "L2", reason: "客户指定高级工程师" })
  })
})

it("renders offer trail and accepts on behalf of offered candidate", async () => {
  const user = userEvent.setup()
  const posts = stubApi({
    packages: [packageRow({ dispatch_status: "offered" })],
    profiles: [],
    offers: {
      "pkg-1": [
        offerTrailRow(),
        offerTrailRow({
          offer_id: "offer-2",
          candidate_user_id: "fde-2",
          candidate_display_name: "李四",
          status: "declined",
          rank: null,
          explanation: null,
          deadline: null,
        }),
      ],
    },
  })
  render(<ConsolePage />)
  await screen.findByText("PKG-B2CON-01")
  await user.click(await screen.findByText("PKG-B2CON-01"))

  expect(await screen.findByText("张三")).toBeInTheDocument()
  expect(screen.getByText(/待响应 · 第 1 轮 · Top1/)).toBeInTheDocument()
  expect(screen.getByText(/已拒单 · 第 1 轮 · 指派/)).toBeInTheDocument()
  expect(screen.getByText("确认截止 2026-11-01T12:00:00+00:00")).toBeInTheDocument()

  // 只有 offered 行出「代接单」；declined 行不出
  const acceptButtons = screen.getAllByRole("button", { name: "代接单" })
  expect(acceptButtons).toHaveLength(1)
  await user.click(acceptButtons[0])

  await waitFor(() => {
    const call = posts.find((item) => item.path === "/api/v1/dispatch/packages/pkg-1/accept")
    expect(call?.body).toEqual({ delivery_user_id: "fde-1" })
  })
})
