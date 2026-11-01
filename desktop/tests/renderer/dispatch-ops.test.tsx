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

import {
  canResolve,
  DisputesPage,
  formatDisputeAmount,
} from "../../src/renderer/src/dispatch/DisputesPage"
import { ClaimGatesPage, gateVerdict } from "../../src/renderer/src/dispatch/ClaimGatesPage"
import { DispatchPage } from "../../src/renderer/src/dispatch/DispatchPage"
import { SimulatorPage } from "../../src/renderer/src/dispatch/SimulatorPage"
import { parseHashRoute } from "../../src/renderer/src/routing/useHashRoute"

function disputeRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    dispute_id: "dsp-1",
    package_id: "pkg-1",
    package_code: "PKG-B3OPS-01",
    settlement_key: "MAB01",
    layer: "L1",
    status: "open",
    amount: 3000,
    reason: "交付方对席位金额有异议",
    resolution: "",
    l0_report_source_uri: null,
    snapshot_hash: "abc123def4567890",
    opened_by: "管理员",
    handled_by: null,
    resolved_at: null,
    created_at: "2026-11-01T09:00:00+00:00",
    ...overrides,
  }
}

function stubApi(options: {
  disputes?: unknown[]
  replay?: unknown
  gates?: unknown[]
}) {
  const posts: { path: string; body: unknown }[] = []
  mocks.apiRequest.mockImplementation(
    (path: string, init?: { method?: string; body?: unknown }) => {
      const method = init?.method ?? "GET"
      if (method !== "GET") {
        posts.push({ path, body: init?.body })
        if (path === "/api/v1/dispatch/simulator/replay") {
          return Promise.resolve(options.replay)
        }
        return Promise.resolve(null)
      }
      if (path === "/api/v1/dispatch/disputes") {
        return Promise.resolve(options.disputes ?? [])
      }
      if (path === "/api/v1/dispatch/claim-gates") {
        return Promise.resolve(options.gates ?? [])
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
// 路由 / 纯函数
// ---------------------------------------------------------------------------

it("parseHashRoute recognizes ops tab hashes", () => {
  expect(parseHashRoute("#dispatch/disputes")).toEqual({
    kind: "dispatch",
    tab: "disputes",
  })
  expect(parseHashRoute("#dispatch/sim")).toEqual({ kind: "dispatch", tab: "sim" })
  expect(parseHashRoute("#dispatch/gates")).toEqual({ kind: "dispatch", tab: "gates" })
})

it("dispute helpers: canResolve and amount format", () => {
  expect(canResolve("open")).toBe(true)
  expect(canResolve("reviewing")).toBe(true)
  expect(canResolve("draft")).toBe(false)
  expect(canResolve("closed")).toBe(false)
  expect(formatDisputeAmount(null)).toBe("—")
  expect(formatDisputeAmount(-12.5)).toBe("¥-12.50")
})

it("gateVerdict maps states to honest verdicts", () => {
  const base = {
    city: "苏州",
    whitelisted: true,
    city_switch: false,
    supply: 1,
    demand: 0,
    offered: 0,
    declined: 0,
    reject_rate: 0,
    conditions: {
      supply_gt_demand: true,
      reject_rate_ok: true,
      rule_publicized: true,
    },
    claim_open: false,
  }
  expect(gateVerdict(base as never)).toContain("开关关闭")
  expect(
    gateVerdict({ ...base, city_switch: true, claim_open: true } as never)
  ).toBe("已开闸")
  expect(
    gateVerdict({ ...base, city_switch: true, claim_open: false } as never)
  ).toBe("条件未满足")
  expect(gateVerdict({ ...base, whitelisted: false } as never)).toBe("非白名单")
})

// ---------------------------------------------------------------------------
// tab 可见性（角色门）
// ---------------------------------------------------------------------------

it("hides ops tabs for non-platform role", () => {
  mocks.user = { id: "fde-1", role: "fde_engineer" }
  stubApi({})
  render(<DispatchPage tab="pool" onTabChange={() => {}} />)
  expect(screen.getByRole("button", { name: "派单池" })).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "争议处理" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "仿真对比" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "开闸运维" })).not.toBeInTheDocument()
})

it("shows ops tabs for platform role", () => {
  stubApi({})
  render(<DispatchPage tab="pool" onTabChange={() => {}} />)
  expect(screen.getByRole("button", { name: "争议处理" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "仿真对比" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "开闸运维" })).toBeInTheDocument()
})

// ---------------------------------------------------------------------------
// 争议处理页
// ---------------------------------------------------------------------------

it("renders dispute rows with pointer field and resolve flow", async () => {
  const user = userEvent.setup()
  const posts = stubApi({
    disputes: [
      disputeRow(),
      disputeRow({
        dispute_id: "dsp-0",
        package_code: "PKG-B3OPS-00",
        layer: "L0",
        status: "draft",
        amount: -12.5,
        resolution: "",
        l0_report_source_uri: "file:///D:/test/FDE/engagements/recon/t+30.csv",
        opened_by: null,
      }),
    ],
  })
  render(<DisputesPage />)
  expect(await screen.findByText("PKG-B3OPS-01")).toBeInTheDocument()
  expect(screen.getByText("L1 平台运营 · 待处理")).toBeInTheDocument()
  expect(screen.getByText("L0 机器对账 · 对账草稿")).toBeInTheDocument()
  // 指针红线：只展示指针本身
  expect(
    screen.getByText("file:///D:/test/FDE/engagements/recon/t+30.csv")
  ).toBeInTheDocument()
  // L0 草稿无裁决按钮；L1 open 有
  expect(screen.getAllByRole("button", { name: "裁决" })).toHaveLength(1)

  await user.click(screen.getByRole("button", { name: "裁决" }))
  await user.type(screen.getByLabelText("裁决结论"), "补足席位差额 ¥500")
  await user.click(screen.getByRole("button", { name: "提交裁决" }))

  await waitFor(() => {
    const call = posts.find((item) =>
      item.path.startsWith("/api/v1/dispatch/disputes/dsp-1/resolve")
    )
    expect(call?.body).toEqual({ resolution: "补足席位差额 ¥500", close: false })
  })
})

it("blocks opening dispute without package_id or reason", async () => {
  const user = userEvent.setup()
  const posts = stubApi({ disputes: [] })
  render(<DisputesPage />)
  await user.click(await screen.findByRole("button", { name: "打开争议" }))
  await user.click(screen.getByRole("button", { name: "提交" }))

  expect(
    await screen.findByText(/package_id 与非空 reason 必填/)
  ).toBeInTheDocument()
  expect(posts.find((item) => item.path === "/api/v1/dispatch/disputes")).toBeUndefined()

  await user.type(screen.getByLabelText("交付包 ID"), "pkg-1")
  await user.type(screen.getByLabelText("争议原因"), "席位金额异议")
  await user.click(screen.getByRole("button", { name: "提交" }))
  await waitFor(() => {
    const call = posts.find((item) => item.path === "/api/v1/dispatch/disputes")
    expect(call?.body).toEqual({
      package_id: "pkg-1",
      layer: "L1",
      reason: "席位金额异议",
    })
  })
})

// ---------------------------------------------------------------------------
// 仿真对比页
// ---------------------------------------------------------------------------

it("runs replay and renders summary with honest caveat", async () => {
  const user = userEvent.setup()
  stubApi({
    replay: {
      mode: "replay",
      rule_version: 1,
      packages: [
        {
          package_code: "PKG-B3OPS-01",
          round: 1,
          scenario: "C",
          stage_a_pass: false,
          candidates: 0,
          rejected: 2,
          top: [],
        },
        {
          package_code: "PKG-B3OPS-02",
          round: 1,
          scenario: "B",
          stage_a_pass: true,
          candidates: 2,
          rejected: 0,
          top: [
            { level: "L2", weighted: 82 },
            { level: "L1", weighted: 40 },
          ],
        },
      ],
      summary: {
        replayed: 2,
        scenario_counts: { A: 0, B: 1, C: 1 },
        stage_a_pass_rate: 0.5,
        avg_candidates_when_passable: 2,
        avg_top1_weighted_remote: 82,
      },
    },
  })
  render(<SimulatorPage />)
  expect(screen.getByText("尚未执行回放。")).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "执行回放" }))
  expect(await screen.findByText("PKG-B3OPS-02")).toBeInTheDocument()
  expect(screen.getByText(/B 远程×1 \/ C 兜底×1/)).toBeInTheDocument()
  expect(screen.queryByText(/跳过/)).not.toBeInTheDocument()
  expect(screen.getByText("Top1")).toBeInTheDocument()
  expect(screen.getByText(/L2 · 加权 82/)).toBeInTheDocument()
  // 口径声明常驻
  expect(screen.getByText(/口径=仿真，不作真实成绩/)).toBeInTheDocument()
})

// ---------------------------------------------------------------------------
// 开闸运维页
// ---------------------------------------------------------------------------

it("renders per-city gate verdicts with explainers", async () => {
  stubApi({
    gates: [
      {
        city: "苏州",
        whitelisted: true,
        city_switch: false,
        supply: 3,
        demand: 1,
        offered: 4,
        declined: 1,
        reject_rate: 0.25,
        conditions: {
          supply_gt_demand: true,
          reject_rate_ok: true,
          rule_publicized: false,
        },
        claim_open: false,
      },
    ],
  })
  render(<ClaimGatesPage />)
  expect(await screen.findByText("苏州")).toBeInTheDocument()
  expect(screen.getByText(/开关关闭/)).toBeInTheDocument()
  expect(screen.getByText(/拒单率 25\.0%/)).toBeInTheDocument()
  expect(screen.getByText(/供给 3 · 需求 1/)).toBeInTheDocument()
  expect(screen.getByText(/改走代码流程——本页只读/)).toBeInTheDocument()
})
