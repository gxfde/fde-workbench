// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"
import React from "react"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
const mocks = vi.hoisted(() => ({ apiRequest: vi.fn(), user: { id: "actor" } }))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))
import { AIServerChat } from "../../src/renderer/src/ai/AIServerChat"
beforeEach(() => { mocks.apiRequest.mockReset(); mocks.apiRequest.mockResolvedValue({ items: [] }) })
it('collapses history and maximizes without losing the draft',async()=>{
  const user=userEvent.setup();render(<AIServerChat route={{kind:'projects'}} />)
  await user.click(screen.getByRole('button',{name:'打开 AI Server 对话'}))
  await user.type(screen.getByRole('textbox'),'对比这两个执行记录')
  await user.click(screen.getByRole('button',{name:'折叠历史记录'}))
  expect(screen.queryByRole('navigation',{name:'对话列表'})).not.toBeInTheDocument()
  await user.click(screen.getByRole('button',{name:'放大对话窗口'}))
  expect(screen.getByRole('dialog')).toHaveClass('is-maximized')
  expect(screen.getByRole('textbox')).toHaveValue('对比这两个执行记录')
  await user.click(screen.getByRole('button',{name:'展开历史记录'}))
  expect(screen.getByRole('navigation',{name:'对话列表'})).toBeVisible()
  await user.click(screen.getByRole('button',{name:'还原对话窗口'}))
  expect(screen.getByRole('dialog')).not.toHaveClass('is-maximized')
  expect(screen.getByRole('textbox')).toHaveValue('对比这两个执行记录')
})
it("does not pull history readers down on polling and resumes following at the bottom", async () => {
  let polls = 0
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (path.endsWith('/conversations')) return { items: [{ id: 'scroll-test', title: '滚动测试', source: 'desktop' }] }
    if (path.endsWith('/conversations/scroll-test')) return { items: [{ id: 'turn', conversation_id: 'scroll-test', prompt: '测试', response: `输出 ${++polls}`, status: 'running' }] }
    if (path.endsWith('/progress')) return { text: '', steps: [], phase: '执行中' }
    return { items: [] }
  })
  const user = userEvent.setup()
  const { container } = render(<AIServerChat route={{ kind: 'projects' }} />)
  await user.click(screen.getByRole('button', { name: '打开 AI Server 对话' }))
  await user.click(await screen.findByRole('button', { name: '滚动测试' }))
  await screen.findByText('输出 1')
  const transcript = container.querySelector('.ai-chat-transcript') as HTMLDivElement
  Object.defineProperty(transcript, 'scrollHeight', { configurable: true, value: 1000 })
  Object.defineProperty(transcript, 'clientHeight', { configurable: true, value: 300 })
  transcript.scrollTop = 200
  fireEvent.scroll(transcript)
  await screen.findByText('输出 2')
  expect(transcript.scrollTop).toBe(200)
  transcript.scrollTop = 700
  fireEvent.scroll(transcript)
  await screen.findByText('输出 3')
  expect(transcript.scrollTop).toBe(1000)
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

it("shows account-scoped navigation, depth control and an icon-only launcher", async () => {
  const user = userEvent.setup()
  const turn = {id: "turn", conversation_id: "conversation", prompt: "测试", response: "完成", status: "completed"}
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (path.endsWith("/messages")) return turn
    return {items: []}
  })
  render(<AIServerChat route={{kind: "projects"}} />)
  expect(screen.getByRole("button", {name: "打开 AI Server 对话"})).toHaveTextContent("")
  await user.click(screen.getByRole("button", {name: "打开 AI Server 对话"}))
  expect(screen.getByRole("navigation", {name: "对话列表"})).toBeVisible()
  expect(screen.getByText("仅当前账号可见")).toBeVisible()
  await user.click(screen.getByRole("switch", {name: "深度思考"}))
  await user.type(screen.getByRole("textbox"), "测试")
  await user.click(screen.getByRole("button", {name: "发送"}))
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith("/api/v1/ai/chat/messages",
    expect.objectContaining({body: expect.objectContaining({deep_thinking: true})})))
})

it("stays dormant until opened and closes with Escape", async () => {
  const user = userEvent.setup()
  render(<AIServerChat route={{ kind: "projects" }} />)
  expect(mocks.apiRequest).not.toHaveBeenCalled()
  await user.click(screen.getByRole("button", { name: "打开 AI Server 对话" }))
  expect(screen.getByRole("dialog", { name: "AI Server 对话" })).toBeVisible()
  await user.keyboard("{Escape}")
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
})

it("sends once with project scope, renders real saved answer and reopens history", async () => {
  const user = userEvent.setup()
  const turn = { id: "turn", conversation_id: "conversation", prompt: "查询项目", response: "项目资料已读取\n\n| 文件 | 状态 |\n| --- | --- |\n| 调研表 | 可用 |", status: "completed", error_message: "" }
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (path.endsWith("/messages")) return turn
    if (path.endsWith("/conversations/conversation")) return { items: [turn] }
    return { items: [] }
  })
  render(<AIServerChat route={{ kind: "project", projectId: "project-1" }} />)
  await user.click(screen.getByRole("button", { name: "打开 AI Server 对话" }))
  await user.type(screen.getByRole("textbox"), "查询项目")
  await user.click(screen.getByRole("button", { name: "发送" }))
  expect(await screen.findByText("项目资料已读取")).toBeVisible()
  expect(screen.getByRole("table")).toHaveTextContent("调研表")
  const writes = mocks.apiRequest.mock.calls.filter(([path]) => path.endsWith("/messages"))
  expect(writes).toHaveLength(1)
  expect(writes[0][1].body).toMatchObject({ project_id: "project-1", message: "查询项目", conversation_id: null })
  expect(writes[0][1].body.message_id).toMatch(/^[a-f0-9-]{36}$/)
  await user.click(screen.getByRole("button", { name: "关闭对话" }))
  await user.click(screen.getByRole("button", { name: "打开 AI Server 对话" }))
  expect(await screen.findByText("项目资料已读取")).toBeVisible()
})

it("keeps failed message draft and stable id for safe resend", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (path.endsWith("/messages")) throw new Error("DSH 暂时不可用")
    return { items: [] }
  })
  render(<AIServerChat route={{ kind: "projects" }} />)
  await user.click(screen.getByRole("button", { name: "打开 AI Server 对话" }))
  await user.type(screen.getByRole("textbox"), "消息")
  await user.click(screen.getByRole("button", { name: "发送" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("AI Server 暂时不可用")
  expect(screen.getByRole("textbox")).toHaveValue("消息")
  await user.click(screen.getByRole("button", { name: "发送" }))
  await waitFor(() => expect(mocks.apiRequest.mock.calls.filter(([path]) => path.endsWith("/messages"))).toHaveLength(2))
  const writes = mocks.apiRequest.mock.calls.filter(([path]) => path.endsWith("/messages"))
  expect(writes[0][1].body.message_id).toEqual(writes[1][1].body.message_id)
})
