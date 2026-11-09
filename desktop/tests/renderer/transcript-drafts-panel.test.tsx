// @vitest-environment jsdom
// T-A9 转写草稿区桌面面（goal-tb tb1）：presurvey 卡旁的转写上传入口。
// 钉住：双列表加载与空态 / 新建草稿 POST 形状（manual 无 engine、asr 带引擎）/
// 详情展开（正文+复核条目徽标）/ 弃置 / 晋升三要素 POST 形状与 canManage 显隐。
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

import { TranscriptDraftsPanel } from "../../src/renderer/src/transcripts/TranscriptDraftsPanel"

const draftRow = {
  id: "draft-1",
  project_id: "project-1",
  title: "初诊访谈录音转写",
  status: "draft",
  source_kind: "asr",
  engine: "faster-whisper:base",
  created_at: "2026-11-07T08:00:00+00:00",
  expires_at: "2026-11-14T08:00:00+00:00",
  cleaned_at: null,
  client_confirmed_by: null,
  client_confirmed_at: null,
  client_confirmation_method: null,
  promoted_ref: null,
}

const draftDetail = {
  ...draftRow,
  content: "今天和文档企业开了初诊会，对方痛点是排程靠Excel。",
  content_sha256: "a".repeat(64),
  redaction_entries: [{ name: "合成测试集团", occurrences: 2, matched_dict: true }],
}

const minutesRow = {
  id: "minutes-1",
  project_id: "project-1",
  title: "初诊访谈纪要",
  draft_id: "draft-1",
  redaction_hits: 1,
  client_confirmed_by: "客户方负责人",
  client_confirmed_at: "2026-11-07T10:00:00+00:00",
  client_confirmation_method: "verbal",
  created_at: "2026-11-07T09:00:00+00:00",
}

function mockGet(url: string): unknown {
  if (url.startsWith("/api/v1/transcript-drafts?")) {
    return { items: [draftRow], total: null, limit: 50, offset: 0, truncated: false }
  }
  if (url === `/api/v1/transcript-drafts/${draftRow.id}`) return draftDetail
  if (url.startsWith("/api/v1/interview-minutes?")) {
    return { items: [], total: null, limit: 50, offset: 0, truncated: false }
  }
  throw new Error(`unexpected GET ${url}`)
}

type ApiCall = [string, { method?: string; body?: unknown } | undefined]

function postCalls(): ApiCall[] {
  return (mocks.apiRequest.mock.calls as ApiCall[]).filter((call) => call[1]?.method === "POST")
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
  mocks.apiRequest.mockImplementation((url: string, init?: { method?: string }) => {
    const method = init?.method ?? "GET"
    if (method === "GET") return Promise.resolve(mockGet(url))
    if (method === "POST") return Promise.resolve({ data: {}, error: null })
    throw new Error(`unexpected ${method} ${url}`)
  })
})

afterEach(() => {
  cleanup()
})

function renderPanel(canManage = true) {
  return render(<TranscriptDraftsPanel projectId="project-1" canManage={canManage} />)
}

it("加载草稿与纪要双列表并呈现红线注记", async () => {
  renderPanel()
  expect(await screen.findByText("初诊访谈录音转写")).toBeInTheDocument()
  expect(screen.getByText("本地 ASR")).toBeInTheDocument()
  expect(screen.getByText(/faster-whisper:base/)).toBeInTheDocument()
  expect(screen.getByText(/只收文本，录音原件永不进平台/)).toBeInTheDocument()
})

it("空态引导本地转写后再建草稿", async () => {
  mocks.apiRequest.mockImplementation((url: string) => {
    if (url.startsWith("/api/v1/transcript-drafts?") || url.startsWith("/api/v1/interview-minutes?")) {
      return Promise.resolve({ items: [], total: null, limit: 50, offset: 0, truncated: false })
    }
    throw new Error(`unexpected GET ${url}`)
  })
  renderPanel()
  expect(await screen.findByText(/暂无转写草稿/)).toBeInTheDocument()
  expect(screen.getByText(/建议 faster-whisper base 档/)).toBeInTheDocument()
})

it("新建草稿：manual 不带 engine、asr 带引擎标注", async () => {
  renderPanel()
  fireEvent.click(await screen.findByText("新增转写草稿"))
  fireEvent.change(screen.getByLabelText("转写文本"), { target: { value: "人工录入要点" } })
  fireEvent.click(screen.getByText("保存草稿"))
  await waitFor(() => {
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      "/api/v1/transcript-drafts",
      expect.objectContaining({ method: "POST" }),
    )
  })
  // body 契约＝对象（api-ipc serializeBody 统一 stringify；预 stringify 会二次编码）。
  const body = postCalls()[0]![1]!.body as Record<string, unknown>
  expect(body.source_kind).toBe("manual")
  expect(body.engine).toBeUndefined()

  fireEvent.click(screen.getByText("新增转写草稿"))
  fireEvent.change(screen.getByLabelText("来源"), { target: { value: "asr" } })
  fireEvent.change(screen.getByLabelText("引擎标注"), { target: { value: "faster-whisper:base" } })
  fireEvent.change(screen.getByLabelText("转写文本"), { target: { value: "引擎转写文本" } })
  fireEvent.click(screen.getByText("保存草稿"))
  await waitFor(() => expect(postCalls().length).toBe(2))
  const asrBody = postCalls()[1]![1]!.body as Record<string, unknown>
  expect(asrBody.source_kind).toBe("asr")
  expect(asrBody.engine).toBe("faster-whisper:base")
})

it("详情展开：正文+复核条目（词典命中徽标）", async () => {
  renderPanel()
  const row = await screen.findByText("初诊访谈录音转写")
  const detailButton = row.closest("tr")!.querySelectorAll("button")[0]!
  fireEvent.click(detailButton)
  expect(await screen.findByText(/今天和文档企业开了初诊会/)).toBeInTheDocument()
  expect(screen.getByText(/合成测试集团/)).toBeInTheDocument()
  expect(screen.getByText("词典命中")).toBeInTheDocument()
})

it("弃置走 discard 端点", async () => {
  renderPanel()
  const row = await screen.findByText("初诊访谈录音转写")
  const discardButton = Array.from(row.closest("tr")!.querySelectorAll("button")).find(
    (button) => button.textContent === "弃置",
  )!
  fireEvent.click(discardButton)
  await waitFor(() => {
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      `/api/v1/transcript-drafts/${draftRow.id}/discard`,
      { method: "POST" },
    )
  })
})

it("晋升：canManage 才有入口，POST 带客户确认三要素", async () => {
  renderPanel(true)
  const row = await screen.findByText("初诊访谈录音转写")
  const buttons = row.closest("tr")!.querySelectorAll("button")
  fireEvent.click(buttons[0]!) // 详情
  await screen.findByText(/今天和文档企业开了初诊会/)
  const promoteButton = Array.from(buttons).find((button) => button.textContent === "晋升")
  expect(promoteButton).not.toBeNull()
  fireEvent.click(promoteButton!)
  fireEvent.change(screen.getByLabelText("纪要标题"), { target: { value: "初诊访谈纪要" } })
  fireEvent.change(screen.getByLabelText("客户确认人（客户侧角色/称呼，入库前将代号化）"), {
    target: { value: "客户方信息化负责人" },
  })
  fireEvent.click(screen.getByText("确认晋升"))
  await waitFor(() => {
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      `/api/v1/transcript-drafts/${draftRow.id}/promote`,
      expect.objectContaining({ method: "POST" }),
    )
  })
  const body = postCalls().at(-1)![1]!.body as Record<string, unknown>
  expect(body.client_confirmed_by).toBe("客户方信息化负责人")
  expect(body.client_confirmation_method).toBe("verbal")
  expect(body.client_confirmed_at).toBeTruthy()
})

it("非管理角色无晋升入口（写闸在服务端，呈现同构显隐）", async () => {
  renderPanel(false)
  await screen.findByText("初诊访谈录音转写")
  const row = screen.getByText("初诊访谈录音转写").closest("tr")!
  expect(Array.from(row.querySelectorAll("button")).map((b) => b.textContent)).not.toContain("晋升")
})
