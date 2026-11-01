// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  user: { id: "actor-1", role: "admin" },
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))

import { DispatchPage } from "../../src/renderer/src/dispatch/DispatchPage"
import { formatSeatAmount, isPackageView } from "../../src/renderer/src/dispatch/DispatchPoolPage"
import { snapshotValue } from "../../src/renderer/src/dispatch/RuleVersionsPage"

function packageRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    package_code: "PKG-AB12CD34-01",
    scope_summary: "交付物 A/B",
    deliverables_json: "交付物 A/B",
    acceptance_criteria: "口径条款逐项可判",
    data_systems: "ERP",
    schedule_text: "需到场实施",
    risks_dependencies: "无",
    business_category: "PoV验证",
    client_code: "r7 企业·制造·苏州",
    client_city: "苏州",
    onsite_required: true,
    onsite_visits: 2,
    deadline: "2026-12-31",
    delivery_seat_amount: 8000,
    dispatch_status: "published",
    dispatch_round: 1,
    dispatch_mode: "assign",
    response_window_hours: 24,
    published_at: "2026-10-31T00:00:00+00:00",
    ...overrides,
  }
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
  mocks.user = { id: "actor-1", role: "admin" }
})

afterEach(() => {
  cleanup()
})

it("派单池页渲染白名单字段且不出现报价明细字段", async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path) === "/api/v1/dispatch/packages") {
      return [packageRow()]
    }
    return []
  })
  render(<DispatchPage tab="pool" onTabChange={() => {}} />)
  expect(await screen.findByText("PKG-AB12CD34-01")).toBeInTheDocument()
  expect(screen.getByText(/交付方席位 ¥8,000.00/)).toBeInTheDocument()
  // 展开详情
  await userEvent.click(screen.getByText("PKG-AB12CD34-01"))
  expect(await screen.findByText("口径条款逐项可判")).toBeInTheDocument()
  expect(screen.getByText("r7 企业·制造·苏州")).toBeInTheDocument()
  const bodyText = document.body.textContent || ""
  expect(bodyText).not.toContain("final_amount")
  expect(bodyText).not.toContain("b_layer_score")
  expect(bodyText).not.toContain("received_amount")
})

it("派单池空态与错误路径", async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path) === "/api/v1/dispatch/packages") return []
    return []
  })
  const { rerender } = render(<DispatchPage tab="pool" onTabChange={() => {}} />)
  expect(await screen.findByText("暂无被授权的交付包。")).toBeInTheDocument()

  mocks.apiRequest.mockRejectedValueOnce(new Error("boom"))
  rerender(<DispatchPage tab="pool" onTabChange={() => {}} />)
  await userEvent.click(screen.getByRole("button", { name: "刷新" }))
  expect(await screen.findByText(/派单池加载失败/)).toBeInTheDocument()
})

it("能力档案页渲染产能与负载", async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path) === "/api/v1/dispatch/profiles") {
      return [
          {
            user_id: "u-1",
            username: "fde.one",
            display_name: "交付方一号",
            level: "L2",
            status: "active",
            scores: { biz_cognition: 2, scenario_eng: 3, ai_tech: 2, delivery_assure: 2 },
            industry_tags: ["制造业"],
            module_tags: ["pre_diagnosis"],
            home_city: "苏州",
            geo_fence_km: 25,
            monthly_capacity_hours: 100,
            avg_delivery_hours: 10,
            in_hand: 2,
            capacity_cap: 10,
          },
        ]
    }
    return []
  })
  render(<DispatchPage tab="profiles" onTabChange={() => {}} />)
  expect(await screen.findByText("交付方一号")).toBeInTheDocument()
  expect(screen.getByText("2/10")).toBeInTheDocument()
  expect(screen.getByText("20%")).toBeInTheDocument()
  expect(screen.getByText("L2 场景工程师")).toBeInTheDocument()
})

it("权重页渲染版本快照与只读常数", async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path) === "/api/v1/dispatch/rules") {
      return {
          versions: [
            {
              id: "rv-1",
              version_no: 1,
              status: "active",
              rule_snapshot: {
                stage_b_weights: { level: 40, industry: 30, sla: 20, geo_remote: 10 },
                level_score_map: { L1: 40, L2: 60, L3: 80, L4: 100 },
                seat_shares: { platform: 35, region: 5, city: 20, delivery: 40 },
              },
              published_at: "2026-09-01T00:00:00+00:00",
              effective_at: "2026-10-01T00:00:00+00:00",
              retired_at: null,
            },
          ],
          constants: { response_window_hours: 24, top_n: 3 },
        }
    }
    return []
  })
  render(<DispatchPage tab="rules" onTabChange={() => {}} />)
  expect(await screen.findByText("v1")).toBeInTheDocument()
  expect(screen.getByText("生效中")).toBeInTheDocument()
  expect(screen.getByText(/"response_window_hours": 24/)).toBeInTheDocument()
})

it("tab 切换回调携带子页键", async () => {
  mocks.apiRequest.mockImplementation(async () => [])
  const onTabChange = vi.fn()
  render(<DispatchPage tab="pool" onTabChange={onTabChange} />)
  await userEvent.click(screen.getByRole("button", { name: "能力档案与产能" }))
  expect(onTabChange).toHaveBeenCalledWith("profiles")
})

it("纯函数：金额格式化 / 包视图守卫 / 快照取值", () => {
  expect(formatSeatAmount(8000)).toBe("¥8,000.00")
  expect(formatSeatAmount(null)).toBe("—")
  expect(isPackageView({ package_code: "x", client_code: "y" })).toBe(true)
  expect(isPackageView({ package_code: "x" })).toBe(false)
  expect(snapshotValue({ a: 1 }, "a")).toBe("1")
  expect(snapshotValue({}, "a")).toBe("—")
})
