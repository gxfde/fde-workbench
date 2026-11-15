// @vitest-environment jsdom
// T-A2 复核闸桌面面（#171 收口）：复核清单唯一投影=服务端 get_analysis
// .redaction_review；confirm 撞 409 redaction_review_required 时呈现清单 +
// 「已复核」ack 重发 redaction_reviewed=true；干净分析零额外负担（不带键）。
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({
  useAuth: () => ({ apiRequest: mocks.apiRequest }),
}))

import { GuidanceReview } from "../../src/renderer/src/guidance/GuidanceReview"

const LIST_FIELDS = [
  "key_business_problems", "priority_departments", "priority_roles", "priority_processes",
  "success_criteria", "out_of_scope", "data_security_redlines", "systems_and_deployment_constraints",
  "assumptions", "open_questions", "next_actions",
] as const

function analysisFixture(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  const base: Record<string, unknown> = {
    id: "analysis-9",
    project_id: "project-1",
    version_number: 4,
    source_file_id: "file-9",
    source_file_version_id: "ver-9",
    source_filename: "预调研表.docx",
    status: "draft",
    analysis_state: "ready",
    customer_vision: "成为北美家庭理疗设备首选供应商",
    current_phase_objective: "完成试点期获客管道搭建",
    executive_summary: "围绕发现-触达-激活三段推进。",
    failure_code: "",
    failure_message: "",
    source_is_stale: false,
    version: 2,
  }
  for (const field of LIST_FIELDS) {
    base[field] = [{ text: "示例条目", classification: "ai_synthesized", source_refs: ["kimi-file:1"], confirmed: false }]
  }
  return { ...base, ...overrides }
}

const REVIEW_ENTRIES = [
  { name: "某疑似企业", occurrences: 2, matched_dict: false },
  { name: "已收录公司", occurrences: 1, matched_dict: true },
]

beforeEach(() => {
  mocks.apiRequest.mockReset()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it("读面复核清单渲染（名称/次数/词典命中标注），服务端唯一投影", () => {
  render(
    <GuidanceReview
      projectId="project-1"
      initial={analysisFixture({ redaction_review: REVIEW_ENTRIES }) as never}
      canManage
      onClose={() => {}}
      onSaved={() => {}}
    />,
  )
  expect(screen.getByLabelText("企业名替换复核清单")).toBeInTheDocument()
  expect(screen.getByText("某疑似企业")).toBeInTheDocument()
  expect(screen.getByText("2 处")).toBeInTheDocument()
  expect(screen.getByText("疑似（未收录）")).toBeInTheDocument()
  expect(screen.getByText("词典命中")).toBeInTheDocument()
  // ack 勾选可用（canManage）
  expect(screen.getByRole("checkbox")).toBeInTheDocument()
})

it("干净分析零额外负担：confirm 请求体不带 redaction_reviewed 键", async () => {
  const patched = analysisFixture({ version: 3 })
  const confirmed = analysisFixture({ version: 4, status: "confirmed" })
  const bodies: Array<Record<string, unknown>> = []
  mocks.apiRequest.mockImplementation(async (_path: string, options?: { method?: string; body?: unknown }) => {
    const method = options?.method ?? "GET"
    if (method === "PATCH") return patched
    if (method === "POST") {
      bodies.push(options?.body as Record<string, unknown>)
      return confirmed
    }
    throw new Error(`unexpected ${method}`)
  })
  render(<GuidanceReview projectId="project-1" initial={analysisFixture() as never} canManage onClose={() => {}} onSaved={() => {}} />)
  fireEvent.click(screen.getByRole("button", { name: "确认并用于项目指引" }))
  await waitFor(() => expect(bodies.length).toBe(1))
  expect(Object.prototype.hasOwnProperty.call(bodies[0], "redaction_reviewed")).toBe(false)
})

it("409 redaction_review_required：呈现拦截提示，勾选已复核后重发带 ack", async () => {
  const patched = analysisFixture({ version: 3, redaction_review: REVIEW_ENTRIES })
  const confirmed = analysisFixture({ version: 4, status: "confirmed" })
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  const bodies: Array<Record<string, unknown>> = []
  let confirmCalls = 0
  mocks.apiRequest.mockImplementation(async (_path: string, options?: { method?: string; body?: unknown }) => {
    const method = options?.method ?? "GET"
    if (method === "PATCH") return patched
    if (method === "POST") {
      confirmCalls += 1
      bodies.push(options?.body as Record<string, unknown>)
      // 复核闸机械强制：未显式携带 ack 一律 409（与路由「只认字面 true」同尺）
      if ((options?.body as Record<string, unknown>)?.redaction_reviewed !== true) {
        throw new ApiClientError(
          { code: "redaction_review_required", message: "存在 2 个企业名替换待复核：请查看复核清单确认替换恰当，或修改正文后重试。" },
          409,
        )
      }
      return confirmed
    }
    throw new Error(`unexpected ${method}`)
  })
  render(
    <GuidanceReview
      projectId="project-1"
      initial={analysisFixture({ redaction_review: REVIEW_ENTRIES }) as never}
      canManage
      onClose={() => {}}
      onSaved={() => {}}
    />,
  )
  fireEvent.click(screen.getByRole("button", { name: "确认并用于项目指引" }))
  // 409 后呈现拦截提示与清单（清单来自读面投影，前端不二次推导）
  expect(await screen.findByText("存在待复核的企业名替换：请逐项核对下方清单后勾选「已复核」，再确认。")).toBeInTheDocument()
  expect(screen.getByText("某疑似企业")).toBeInTheDocument()
  // 未勾选时重试仍不带 ack（fail 向安全侧）
  fireEvent.click(screen.getByRole("button", { name: "确认并用于项目指引" }))
  await waitFor(() => expect(confirmCalls).toBe(2))
  expect(await screen.findByText("存在待复核的企业名替换：请逐项核对下方清单后勾选「已复核」，再确认。")).toBeInTheDocument()
  // 勾选「已复核」→ 重发携带 redaction_reviewed: true → 放行
  fireEvent.click(screen.getByRole("checkbox"))
  fireEvent.click(screen.getByRole("button", { name: "确认并用于项目指引" }))
  await waitFor(() => expect(confirmCalls).toBe(3))
  expect(bodies[2]?.redaction_reviewed).toBe(true)
})

it("本地读面缺清单时 409 触发回读读面补渲染（仍用服务端投影，不自行推导）", async () => {
  const patched = analysisFixture({ version: 3 })
  const withReview = analysisFixture({ version: 3, redaction_review: REVIEW_ENTRIES })
  const confirmed = analysisFixture({ version: 4, status: "confirmed", redaction_review: REVIEW_ENTRIES })
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  let getCalls = 0
  mocks.apiRequest.mockImplementation(async (_path: string, options?: { method?: string; body?: unknown }) => {
    const method = options?.method ?? "GET"
    if (method === "PATCH") return patched
    if (method === "GET") {
      getCalls += 1
      return withReview
    }
    if (method === "POST") {
      throw new ApiClientError(
        { code: "redaction_review_required", message: "存在 2 个企业名替换待复核。" },
        409,
      )
    }
    throw new Error(`unexpected ${method}`)
  })
  render(<GuidanceReview projectId="project-1" initial={analysisFixture() as never} canManage onClose={() => {}} onSaved={() => {}} />)
  fireEvent.click(screen.getByRole("button", { name: "确认并用于项目指引" }))
  // 409 → 回读读面 → 清单出现在面板
  expect(await screen.findByText("某疑似企业")).toBeInTheDocument()
  expect(getCalls).toBeGreaterThan(0)
  expect(confirmed).toBeDefined()
})

// 盲审追批换代用例：#463 服务端投影新形状（指纹条目 name 可空 ＋ 疑似聚合
// 哨兵 {suspect_count}）必须照常渲染并放行 ack——修复前守卫整组丢弃导致
// 复核框消失 → confirm 永远 409 死锁。
const FINGERPRINT_ENTRIES = [
  { name_hash: "a1b2c3d4e5f6", name: null, occurrences: 3, matched_dict: true },
  { suspect_count: 4 },
]

it("新形状投影：指纹条目显示占位＋疑似哨兵聚合行，勾选后 confirm 带 ack", async () => {
  const patched = analysisFixture({ version: 3, redaction_review: FINGERPRINT_ENTRIES })
  const confirmed = analysisFixture({ version: 4, status: "confirmed" })
  const bodies: Array<Record<string, unknown>> = []
  const calls: Array<string> = []
  mocks.apiRequest.mockImplementation(async (_path: string, options?: { method?: string; body?: unknown }) => {
    const method = options?.method ?? "GET"
    calls.push(method)
    if (method === "PATCH") return patched
    if (method === "POST") {
      bodies.push(options?.body as Record<string, unknown>)
      return confirmed
    }
    throw new Error("unexpected GET")
  })
  render(
    <GuidanceReview
      projectId="project-1"
      initial={analysisFixture({ redaction_review: FINGERPRINT_ENTRIES }) as never}
      canManage
      onClose={() => {}}
      onSaved={() => {}}
    />,
  )
  expect(screen.getByLabelText("企业名替换复核清单")).toBeInTheDocument()
  expect(screen.getByText("a1b2c3d4…")).toBeInTheDocument()
  expect(screen.getByText("词典命中")).toBeInTheDocument()
  expect(screen.getByText("疑似企业名（未收录词典）")).toBeInTheDocument()
  expect(screen.getByText("4 处")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("checkbox"))
  fireEvent.click(screen.getByRole("button", { name: "确认并用于项目指引" }))
  await waitFor(() => expect(bodies.length).toBe(1))
  expect(bodies[0]?.redaction_reviewed).toBe(true)
})

it("新形状投影但守卫拒收畸形项时整组丢弃：confirm 409 后走回读刷新路径", async () => {
  const patched = analysisFixture({ version: 3, redaction_review: [{ name: null, occurrences: 1 }] })
  const refreshed = analysisFixture({ version: 3, redaction_review: FINGERPRINT_ENTRIES })
  const confirmed = analysisFixture({ version: 4, status: "confirmed" })
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation(async (_path: string, options?: { method?: string; body?: unknown }) => {
    const method = options?.method ?? "GET"
    if (method === "PATCH") return patched
    if (method === "POST") {
      if ((options?.body as Record<string, unknown>)?.redaction_reviewed !== true) {
        throw new ApiClientError({ code: "redaction_review_required", message: "存在企业名替换待复核" })
      }
      return confirmed
    }
    return refreshed
  })
  render(
    <GuidanceReview
      projectId="project-1"
      initial={analysisFixture({ version: 3, redaction_review: [] }) as never}
      canManage
      onClose={() => {}}
      onSaved={() => {}}
    />,
  )
  // 初渲染空清单 → 直接确认 → 撞 409 → 回读刷新出清单。
  fireEvent.click(screen.getByRole("button", { name: "确认并用于项目指引" }))
  expect(await screen.findByText("a1b2c3d4…")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("checkbox"))
  fireEvent.click(screen.getByRole("button", { name: "确认并用于项目指引" }))
})
