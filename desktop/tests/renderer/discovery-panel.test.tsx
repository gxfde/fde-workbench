// @vitest-environment jsdom
// V3.1 P0-1 批B：访谈事实与需求审阅面板（discovery 桌面消费面）。
// 钉住：三列表加载 / 抽取发起 POST 形状与幂等提示 / 重跑按钮仅 failed 显隐 /
// 事实审阅三动作 + 批量接受只打 pending / 需求审阅 / 锚点三形态呈现 /
// canManage 写操作显隐。
// 试点审阅轮追加：锚点核验 A/B/C 徽标与汇总 / 仅看可疑过滤 / 审阅后就地
// 更新（不整表刷新）/ 事实分页加载更多。
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

import { DiscoveryPanel } from "../../src/renderer/src/discovery/DiscoveryPanel"

const minutes = { id: "min-1", title: "初诊纪要", project_id: "project-1", draft_id: null, redaction_hits: 0, client_confirmed_by: "客户A", client_confirmed_at: "2026-11-07T00:00:00+00:00", client_confirmation_method: "verbal", created_at: "2026-11-07T00:00:00+00:00" }
// 纪要正文：第 1 行支撑 fact-1（询盘处理/销售人工分配）；第 9 行为空行（供锚 A 用例）。
const minutesDetail = {
  id: "min-1", title: "初诊纪要",
  content: "询盘处理当前由销售人工分配。\n第二行内容。\n第三行内容。\n第四行内容。\n第五行内容。\n第六行内容。\n第七行内容。\n第八行内容。\n",
}

const extractionReady = {
  id: "ext-1", source_type: "interview_minutes", source_id: "min-1",
  source_sha256: "c".repeat(64), status: "review_required",
  extractor_version: "discovery-extractor-v1", prompt_version: "discovery-prompt-v1",
  ai_model: "test-model", completed_at: "2026-11-07T01:00:00+00:00",
  failure_code: null, failure_message: null,
  redaction_entries: [{ name: "合成测试集团", occurrences: 2, matched_dict: true }],
}
const extractionFailed = { ...extractionReady, id: "ext-2", status: "failed", failure_code: "ai_output_invalid", failure_message: "格式错误", ai_model: null }

const factPending = {
  id: "fact-1", fact_type: "process", classification: "customer_stated",
  subject: "询盘处理", predicate: "当前步骤", object_value: { step: "销售人工分配" },
  confidence: 0.9, source_ref: "interview_minutes:min-1",
  source_locator: { type: "line", line: 1 },
  review_status: "pending", review_comment: null, reviewed_at: null,
}
const factSegment = {
  ...factPending, id: "fact-2", review_status: "needs_clarification",
  classification: "ai_inferred", subject: "排程瓶颈",
  source_locator: { type: "transcript_segment", start_ms: 12000, end_ms: 18500 },
  confidence: null,
}
const factAccepted = {
  ...factPending, id: "fact-3", review_status: "accepted",
  reviewed_at: "2026-11-07T02:00:00+00:00",
  source_locator: { type: "char_span", start: 3, end: 9 },
}
// 锚 A 夹具：line 定位锚到第 9 行（纪要正文该行为空行）——空行锚＝高危。
const factEmptyAnchor = {
  ...factPending, id: "fact-4", review_status: "accepted",
  subject: "看板异常", predicate: "静默错误", object_value: { mode: "silent" },
  source_locator: { type: "line", line: 9 },
}

const requirement = {
  id: "req-1", requirement_key: "R-abc12345", title: "询盘自动分配",
  description: null, requirement_type: "functional", priority: "high",
  acceptance_criteria: ["5 分钟内分配到人"], status: "pending",
  approved_at: null, review_comment: null,
  source_fact_ids: ["fact-1"], source_count: 1,
}

function mockGet(url: string): unknown {
  if (url.startsWith("/api/v1/interview-minutes?")) return { items: [minutes], truncated: false }
  if (url.startsWith("/api/v1/interview-minutes/")) return minutesDetail
  if (url.includes("/discovery/extractions?")) return { items: [extractionReady, extractionFailed] }
  if (url.includes("/business-facts?")) return { items: [factPending, factSegment, factAccepted, factEmptyAnchor] }
  if (url.includes("/requirements?")) return { items: [requirement] }
  throw new Error(`unexpected GET ${url}`)
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
  mocks.apiRequest.mockImplementation((url: string, init?: { method?: string }) => {
    const method = init?.method ?? "GET"
    if (method === "GET") return Promise.resolve(mockGet(url))
    return Promise.resolve({ data: {}, error: null })
  })
})

afterEach(() => {
  cleanup()
})

function renderPanel(canManage = true) {
  return render(<DiscoveryPanel projectId="project-1" canManage={canManage} />)
}

it("加载三列表并呈现抽取状态、复核条目与失败码", async () => {
  renderPanel()
  expect(await screen.findByRole("heading", { name: "访谈事实与需求（AI 抽取草稿 · 人工审阅定案）" })).toBeInTheDocument()
  expect(screen.getByText("待审阅")).toBeInTheDocument()
  expect(screen.getByText("失败")).toBeInTheDocument()
  expect(screen.getByText("ai_output_invalid")).toBeInTheDocument()
  expect(screen.getByText(/脱敏复核 1 项/)).toBeInTheDocument()
})

it("锚点三形态呈现：行号/时间段/字符区间", async () => {
  renderPanel()
  expect(await screen.findByText("第 1 行")).toBeInTheDocument()
  expect(screen.getByText("12000–18500 ms")).toBeInTheDocument()
  expect(screen.getByText("字符 3–9")).toBeInTheDocument()
})

it("发起抽取 POST 形状与幂等提示", async () => {
  mocks.apiRequest.mockImplementation((url: string, init?: { method?: string; body?: string }) => {
    const method = init?.method ?? "GET"
    if (method === "GET") return Promise.resolve(mockGet(url))
    if (method === "POST" && url.endsWith("/discovery/extractions")) {
      expect(JSON.parse(init?.body ?? "{}")).toEqual({ source_type: "interview_minutes", source_id: "min-1" })
      return Promise.resolve({ ...extractionReady, created: true })
    }
    return Promise.resolve({ data: {}, error: null })
  })
  renderPanel()
  const select = await screen.findByLabelText("抽取来源（访谈纪要）")
  fireEvent.change(select, { target: { value: "min-1" } })
  fireEvent.click(screen.getByRole("button", { name: "发起 AI 抽取" }))
  expect(await screen.findByText("抽取任务已入队，完成后回到「待审阅」状态。")).toBeInTheDocument()
})

it("重跑按钮仅 failed 行显示", async () => {
  renderPanel()
  await screen.findByText("失败")
  const rerunButtons = screen.getAllByRole("button", { name: "重跑" })
  expect(rerunButtons).toHaveLength(1)
})

it("事实审阅三动作 PATCH 形状（澄清走 needs_clarification）", async () => {
  const patches: Array<{ url: string; body: unknown }> = []
  mocks.apiRequest.mockImplementation((url: string, init?: { method?: string; body?: string }) => {
    const method = init?.method ?? "GET"
    if (method === "GET") return Promise.resolve(mockGet(url))
    if (method === "PATCH") {
      patches.push({ url, body: JSON.parse(init?.body ?? "{}") })
      return Promise.resolve({ data: {}, error: null })
    }
    return Promise.resolve({ data: {}, error: null })
  })
  renderPanel()
  const clarifyButtons = await screen.findAllByRole("button", { name: "澄清" })
  fireEvent.click(clarifyButtons[0])
  await waitFor(() => expect(patches).toHaveLength(1))
  expect(patches[0].url).toBe("/api/v1/business-facts/fact-1/review")
  expect(patches[0].body).toEqual({ review_status: "needs_clarification" })
})

it("批量接受只打 pending 行且逐条 PATCH", async () => {
  const patchedUrls: string[] = []
  mocks.apiRequest.mockImplementation((url: string, init?: { method?: string; body?: string }) => {
    const method = init?.method ?? "GET"
    if (method === "GET") return Promise.resolve(mockGet(url))
    if (method === "PATCH" && url.includes("/business-facts/")) {
      patchedUrls.push(url)
      return Promise.resolve({ data: {}, error: null })
    }
    return Promise.resolve({ data: {}, error: null })
  })
  renderPanel()
  fireEvent.click(await screen.findByRole("button", { name: "批量接受已加载待审" }))
  await waitFor(() => expect(patchedUrls).toHaveLength(1))
  expect(patchedUrls[0]).toBe("/api/v1/business-facts/fact-1/review")
  expect(await screen.findByText("已批量接受 1 条待审事实。")).toBeInTheDocument()
})

it("viewer 无写操作：发起/审阅/批量按钮全部隐藏", async () => {
  renderPanel(false)
  await screen.findByText("待审阅")
  expect(screen.queryByRole("button", { name: "发起 AI 抽取" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "重跑" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "批量接受已加载待审" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "接受" })).not.toBeInTheDocument()
})

it("锚点核验分级徽标与汇总：命中行锚C、空行锚A、非行定位不标", async () => {
  renderPanel()
  expect(await screen.findByText("锚C")).toBeInTheDocument()
  expect(screen.getByText("锚A")).toBeInTheDocument()
  expect(screen.getByText(/锚点核验：A 1 · B 0 · C 1/)).toBeInTheDocument()
  expect(screen.queryByText("锚B")).not.toBeInTheDocument()
})

it("仅看锚点可疑过滤：A 级保留、C 级隐藏", async () => {
  renderPanel()
  await screen.findByText("锚A")
  fireEvent.change(screen.getByLabelText("锚点核验"), { target: { value: "suspect" } })
  expect(screen.getByText("看板异常 · 静默错误")).toBeInTheDocument()
  expect(screen.queryByText("询盘处理 · 当前步骤")).not.toBeInTheDocument()
})

it("审阅后就地更新：PATCH 成功后不整表刷新（facts GET 仍只一次）", async () => {
  const factsGets: string[] = []
  const patches: string[] = []
  mocks.apiRequest.mockImplementation((url: string, init?: { method?: string; body?: string }) => {
    const method = init?.method ?? "GET"
    if (method === "GET") {
      if (url.includes("/business-facts?")) factsGets.push(url)
      return Promise.resolve(mockGet(url))
    }
    if (method === "PATCH" && url.includes("/business-facts/")) {
      patches.push(url)
      return Promise.resolve({ data: {}, error: null })
    }
    return Promise.resolve({ data: {}, error: null })
  })
  renderPanel()
  await screen.findByText("锚C")
  const acceptButtons = screen.getAllByRole("button", { name: "接受" })
  fireEvent.click(acceptButtons[0])
  await waitFor(() => expect(patches).toHaveLength(1))
  // 就地更新：fact-1 状态翻转（fact-3 本就 accepted，故「已接受」≥2 处）但不再发整表 GET。
  await waitFor(() => expect(screen.getAllByText("已接受").length).toBeGreaterThanOrEqual(2))
  expect(factsGets).toHaveLength(1)
})

it("事实分页：首页满页显示加载更多，翻页后到底自动收起", async () => {
  const bulk = Array.from({ length: 100 }, (_, i) => ({
    ...factPending,
    id: `fact-bulk-${i}`,
    subject: `批量主体${i}`,
    source_locator: { type: "line", line: ((i % 8) + 1) },
  }))
  mocks.apiRequest.mockImplementation((url: string, init?: { method?: string }) => {
    const method = init?.method ?? "GET"
    if (method === "GET") {
      if (url.includes("/business-facts?")) {
        const page2 = url.includes("offset=100")
          ? Array.from({ length: 2 }, (_, i) => ({ ...factPending, id: `fact-page2-${i}`, subject: `次页主体${i}` }))
          : bulk
        return Promise.resolve({ items: page2 })
      }
      if (url.startsWith("/api/v1/interview-minutes?")) return Promise.resolve({ items: [minutes] })
      if (url.startsWith("/api/v1/interview-minutes/")) return Promise.resolve(minutesDetail)
      if (url.includes("/discovery/extractions?")) return Promise.resolve({ items: [] })
      if (url.includes("/requirements?")) return Promise.resolve({ items: [] })
    }
    return Promise.resolve({ data: {}, error: null })
  })
  renderPanel()
  expect(await screen.findByText("业务事实（已加载 100+）")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "加载更多事实" }))
  expect(await screen.findByText("业务事实（已加载 102）")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "加载更多事实" })).not.toBeInTheDocument()
})
