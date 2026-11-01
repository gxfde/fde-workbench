// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  user: { id: "actor-1", role: "fde_engineer" },
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))

import { DispatchPage } from "../../src/renderer/src/dispatch/DispatchPage"
import {
  DECLINE_REASONS,
  formatCountdown,
  isMyOfferView,
  type MyOfferView,
} from "../../src/renderer/src/dispatch/MyOffersPage"
import {
  isMySettlementView,
  MySettlementsPage,
} from "../../src/renderer/src/dispatch/MySettlementsPage"

function packageRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "pkg-1",
    package_code: "PKG-B1MINE-01",
    scope_summary: "交付物 A/B",
    deliverables_json: "交付物 A/B",
    acceptance_criteria: "口径条款逐项可判",
    data_systems: "ERP",
    schedule_text: "远程交付",
    risks_dependencies: "无",
    business_category: "PoV验证",
    client_code: "b1 企业·制造·苏州",
    client_city: "苏州",
    onsite_required: false,
    onsite_visits: null,
    deadline: "2026-12-31",
    delivery_seat_amount: 8000,
    dispatch_status: "offered",
    dispatch_round: 1,
    dispatch_mode: "assign",
    response_window_hours: 24,
    published_at: "2026-10-31T00:00:00+00:00",
    ...overrides,
  }
}

function offerRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    offer_id: "offer-1",
    status: "offered",
    version: 3,
    dispatch_round: 1,
    mode: "assign",
    offered_at: "2026-10-31T12:00:00+00:00",
    responded_at: null,
    deadline: "2026-11-01T12:00:00+00:00",
    match_breakdown: null,
    package: packageRow(),
    ...overrides,
  }
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
  mocks.user = { id: "actor-1", role: "fde_engineer" }
})

afterEach(() => {
  cleanup()
})

it("formatCountdown：未到期/过期/无期限三态", () => {
  const now = new Date("2026-10-31T12:00:00+00:00")
  expect(formatCountdown("2026-10-31T13:30:00+00:00", now)).toBe("剩 1 小时 30 分")
  expect(formatCountdown("2026-10-31T12:40:00+00:00", now)).toBe("剩 40 分钟")
  expect(formatCountdown("2026-10-31T12:00:00+00:00", now)).toBe("已过期")
  expect(formatCountdown(null, now)).toBe("—")
})

it("isMyOfferView / isMySettlementView 守卫", () => {
  expect(isMyOfferView(offerRow())).toBe(true)
  expect(isMyOfferView({ offer_id: "x" })).toBe(false)
  expect(
    isMySettlementView({
      settlement_id: "s1",
      package_code: "P",
      my_amount: 1,
      my_roles: ["delivery"],
    })
  ).toBe(true)
  expect(isMySettlementView({ settlement_id: "s1" })).toBe(false)
})

it("我的接单页：渲染收件箱 + 待响应计数 + 我的档案卡", async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path) === "/api/v1/dispatch/offers/mine") {
      return [
          offerRow(),
          offerRow({
            offer_id: "offer-2",
            status: "declined",
            responded_at: "2026-10-31T13:00:00+00:00",
            package: packageRow({ package_code: "PKG-B1MINE-02" }),
          }),
        ]
    }
    if (String(path) === "/api/v1/dispatch/profiles/me") {
      return {
          level: "L2",
          status: "active",
          scores: {
            biz_cognition: 3,
            scenario_eng: 3,
            ai_tech: 4,
            delivery_assure: 3,
          },
          industry_tags: [],
          module_tags: [],
          home_city: "苏州",
          monthly_capacity_hours: 160,
          avg_delivery_hours: 40,
          in_hand: 1,
          capacity_cap: 4,
        }
    }
    return []
  })
  render(<DispatchPage tab="mine" onTabChange={() => {}} />)
  expect(await screen.findByText("PKG-B1MINE-01")).toBeInTheDocument()
  expect(screen.getByText("待响应 1 条 / 共 2 条")).toBeInTheDocument()
  expect(screen.getByText(/我的档案：L2 · 苏州/)).toBeInTheDocument()
  expect(screen.getByText(/在途 1 \/ 上限 4 单/)).toBeInTheDocument()
  // 待响应行有接单/拒单操作，历史行没有
  expect(screen.getByRole("button", { name: "接单" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "拒单" })).toBeInTheDocument()
})

it("我的接单页：接单调用乐观锁 version", async () => {
  mocks.apiRequest.mockImplementation(async (path: string, options?: { method?: string }) => {
    if (String(path) === "/api/v1/dispatch/offers/mine") return [offerRow()]
    if (String(path) === "/api/v1/dispatch/offers/offer-1/accept") {
      expect(options?.method).toBe("POST")
      return { offer_id: "offer-1", status: "accepted" }
    }
    if (String(path) === "/api/v1/dispatch/profiles/me") return null
    return []
  })
  render(<DispatchPage tab="mine" onTabChange={() => {}} />)
  await userEvent.click(await screen.findByRole("button", { name: "接单" }))
  await waitFor(() => {
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      "/api/v1/dispatch/offers/offer-1/accept",
      expect.objectContaining({ method: "POST", body: { version: 3 } })
    )
  })
})

it("我的接单页：拒单须选原因（枚举四选一）并随请求提交", async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path) === "/api/v1/dispatch/offers/mine") return [offerRow()]
    if (String(path) === "/api/v1/dispatch/offers/offer-1/decline") {
      return { offer_id: "offer-1", status: "declined" }
    }
    return []
  })
  render(<DispatchPage tab="mine" onTabChange={() => {}} />)
  await userEvent.click(await screen.findByRole("button", { name: "拒单" }))
  const select = await screen.findByLabelText("拒单原因")
  const options = Array.from(select.querySelectorAll("option")).map((o) => o.textContent)
  expect(options).toEqual([...DECLINE_REASONS])
  await userEvent.selectOptions(select, "档期冲突")
  await userEvent.click(screen.getByRole("button", { name: "确认拒单" }))
  await waitFor(() => {
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      "/api/v1/dispatch/offers/offer-1/decline",
      expect.objectContaining({
        method: "POST",
        body: { version: 3, reason: "档期冲突" },
      })
    )
  })
})

it("我的接单页：档案 404 显示引导文案而非报错", async () => {
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path) === "/api/v1/dispatch/offers/mine") return []
    throw new ApiClientError(
      { code: "profile_not_found", message: "尚无能力档案（由平台创建/晋级流程建立）。" },
      404
    )
  })
  render(<DispatchPage tab="mine" onTabChange={() => {}} />)
  expect(
    await screen.findByText(/尚无能力档案（由平台创建\/晋级流程建立）。/)
  ).toBeInTheDocument()
})

it("我的结算页：只渲染本人席位金额与角色", async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path) === "/api/v1/dispatch/settlements/mine") {
      return [
          {
            settlement_id: "s1",
            package_code: "PKG-B1MINE-01",
            settlement_key: "M1",
            status: "accrued",
            base_amount: 10000,
            my_roles: ["delivery"],
            my_amount: 4000,
            withholding_tax: 120,
            acceptance_passed_at: null,
            paid_at: null,
          },
        ]
    }
    return []
  })
  render(<MySettlementsPage />)
  expect(await screen.findByText(/PKG-B1MINE-01 · M1/)).toBeInTheDocument()
  expect(screen.getByText(/我的分成 ¥4,000.00/)).toBeInTheDocument()
  expect(screen.getByText(/交付方/)).toBeInTheDocument()
  expect(screen.getByText(/预扣税 ¥120.00/)).toBeInTheDocument()
})

it("派单池：claim 模式已发布包在详情展开后显示抢单按钮并发请求", async () => {
  mocks.apiRequest.mockImplementation(async (path: string, options?: { method?: string }) => {
    if (String(path) === "/api/v1/dispatch/packages") {
      return [
          packageRow({ dispatch_mode: "claim", dispatch_status: "published" }),
          packageRow({ id: "pkg-2", package_code: "PKG-B1ASSIGN-02", dispatch_mode: "assign" }),
        ]
    }
    if (String(path) === "/api/v1/dispatch/packages/pkg-1/claim") {
      expect(options?.method).toBe("POST")
      return { offer_id: "offer-new" }
    }
    return []
  })
  render(<DispatchPage tab="pool" onTabChange={() => {}} />)
  await userEvent.click(await screen.findByText("PKG-B1MINE-01"))
  const claimButton = await screen.findByRole("button", { name: "抢单" })
  await userEvent.click(claimButton)
  await waitFor(() => {
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      "/api/v1/dispatch/packages/pkg-1/claim",
      expect.objectContaining({ method: "POST" })
    )
  })
})

it("派单池：assign 模式包不出现抢单按钮", async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path) === "/api/v1/dispatch/packages") {
      return [packageRow()]
    }
    return []
  })
  render(<DispatchPage tab="pool" onTabChange={() => {}} />)
  await userEvent.click(await screen.findByText("PKG-B1MINE-01"))
  await waitFor(() => {
    expect(screen.queryByRole("button", { name: "抢单" })).not.toBeInTheDocument()
  })
})
