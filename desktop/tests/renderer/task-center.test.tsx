// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

import { AuthProvider, useAuth } from "../../src/renderer/src/auth/AuthProvider"
import { TaskCenterPage } from "../../src/renderer/src/tasks/TaskCenterPage"
import type { ApiResponse, BridgeResult } from "../../src/shared/contracts"
import { adminUser, authResult, bridge, installBridge, ok, renderApp } from "./test-utils"

function AuthenticatedTaskCenter() {
  const { status } = useAuth()
  return status === "authenticated" ? <TaskCenterPage /> : null
}

function App() {
  return <AuthProvider><AuthenticatedTaskCenter /></AuthProvider>
}

function apiOk<T>(data: T, status = 200): BridgeResult<ApiResponse<T>> {
  return ok({ status, data, error: null })
}

beforeEach(() => { location.hash = "#task-center" })
afterEach(() => { cleanup(); vi.restoreAllMocks(); location.hash = "" })

it("shows unified sources and lets an authorized user queue a DSH automation", async () => {
  const taskData = {
    items: [
      {
        id: "automation-1",
        kind: "automation",
        source: "wechat",
        title: "每日检查项目进度",
        description: "",
        status: "active",
        project_id: "project-1",
        project_name: "星河项目",
        assignee_name: "DSH",
        schedule: { kind: "calendar", expression: "0 9 * * 1-5", timezone: "Asia/Shanghai" },
        next_run_at: null,
        updated_at: "2026-09-05T00:00:00+00:00",
        can_run: true,
      },
    ],
    total: 1,
    counts: { project: 0, automation: 1 },
  }
  const apiRequest = vi.fn((path: string, options: { method: string }) => {
    if (path === "/api/v1/task-center/board" && options.method === "GET") return Promise.resolve(apiOk(taskData))
    if (path === "/api/v1/task-center/approvals" && options.method === "GET") return Promise.resolve(apiOk({ items: [], total: 0 }))
    if (path === "/api/v1/task-center/automations/automation-1/runs" && options.method === "POST") {
      return Promise.resolve(apiOk({ id: "run-12345678", task_id: "automation-1", status: "queued" }, 202))
    }
    throw new Error(`Unexpected request: ${options.method} ${path}`)
  })
  installBridge(bridge({
    refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
    apiRequest,
  }))
  renderApp(<App />)

  expect(await screen.findByText("每日检查项目进度")).toBeVisible()
  expect(screen.getByText("微信")).toBeVisible()
  await userEvent.setup().click(screen.getByRole("button", { name: "立即执行" }))

  expect(await screen.findByText(/任务已加入执行队列/)).toBeVisible()
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith(
    "/api/v1/task-center/automations/automation-1/runs",
    expect.objectContaining({ method: "POST" }),
  ))
})

it("requires a password before approving a high-risk DSH operation", async () => {
  const apiRequest = vi.fn((path: string, options: { method: string; body?: unknown }) => {
    if (path === "/api/v1/task-center/board" && options.method === "GET") return Promise.resolve(apiOk({ items: [], total: 0, counts: { project: 0, automation: 0 } }))
    if (path === "/api/v1/task-center/approvals" && options.method === "GET") return Promise.resolve(apiOk({ items: [{ id: "approval-1", run_id: "run-1", project_id: "project-1", project_name: "星河项目", requested_by_name: "示例用户", capability: "task.batch_assign", tool_name: "project_tasks.batch_assign", arguments: { task_ids: ["task-1"] }, risk_level: 3, status: "pending", expires_at: "2026-09-05T10:00:00+08:00", can_review: true }], total: 1 }))
    if (path === "/api/v1/task-center/approvals/approval-1/decision" && options.method === "POST") return Promise.resolve(apiOk({ id: "approval-1", status: "approved" }))
    throw new Error(`Unexpected request: ${options.method} ${path}`)
  })
  installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
  renderApp(<App />)

  expect(await screen.findByText("待审批操作")).toBeVisible()
  await userEvent.setup().click(screen.getByRole("button", { name: "审核并批准" }))
  await userEvent.setup().click(screen.getByRole("button", { name: "确认批准" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("请输入当前密码")

  await userEvent.setup().type(screen.getByLabelText("审批当前密码"), "InitialPass!234")
  await userEvent.setup().click(screen.getByRole("button", { name: "确认批准" }))
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith(
    "/api/v1/task-center/approvals/approval-1/decision",
    expect.objectContaining({ method: "POST", body: expect.objectContaining({ decision: "approve", password: "InitialPass!234" }) }),
  ))
})

const projectTask = {
  id: "task-1", kind: "project", source: "workbench", title: "访谈项目岗位", description: "完成岗位现状访谈",
  status: "not_started", project_id: "project-1", project_name: "星河项目", assignee_name: "示例用户",
  schedule: { kind: "project_dates", expression: "2026-09-05 / 2026-09-06" }, next_run_at: null,
  updated_at: "2026-09-05T00:00:00+00:00", can_edit: true, version: 2, progress: 0,
}

function mountBoard(options: {
  task?: typeof projectTask
  mutate?: (body: Record<string, unknown>) => Promise<BridgeResult<ApiResponse<unknown>>>
} = {}) {
  const task = options.task ?? projectTask
  const apiRequest = vi.fn((path: string, request: { method: string; body?: Record<string, unknown> }) => {
    if (path === "/api/v1/task-center/board" && request.method === "GET") return Promise.resolve(apiOk({ items: [task], total: 1, counts: { project: task.kind === "project" ? 1 : 0, automation: task.kind === "automation" ? 1 : 0 } }))
    if (path === "/api/v1/task-center/approvals") return Promise.resolve(apiOk({ items: [], total: 0 }))
    if (path === `/api/v1/task-center/board/${task.kind}/${task.id}/status` && request.method === "PATCH") return options.mutate ? options.mutate(request.body!) : Promise.resolve(apiOk({ ...task, ...request.body, version: 3 }))
    throw new Error(`Unexpected request: ${request.method} ${path}`)
  })
  installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
  renderApp(<App />)
  return apiRequest
}

it("shows status swimlanes without a refresh button and supports the keyboard status selector", async () => {
  const apiRequest = mountBoard()
  const card = await screen.findByRole("article", { name: projectTask.title })
  expect(screen.queryByRole("button", { name: "刷新" })).not.toBeInTheDocument()
  expect(screen.queryByRole("table")).not.toBeInTheDocument()
  expect(within(screen.getByRole("region", { name: "项目任务：未开始" })).getByRole("article")).toBe(card)
  await userEvent.setup().selectOptions(screen.getByLabelText(`${projectTask.title}的状态`), "in_progress")
  expect(await screen.findByText(/已移至进行中/)).toBeVisible()
  expect(within(screen.getByRole("region", { name: "项目任务：进行中" })).getByRole("article", { name: projectTask.title })).toBeVisible()
  expect(apiRequest).toHaveBeenCalledWith("/api/v1/task-center/board/project/task-1/status", expect.objectContaining({ method: "PATCH", body: { status: "in_progress", version: 2 } }))
})

it("moves a dragged task to a status lane and persists its version", async () => {
  const apiRequest = mountBoard()
  const dataTransfer = { setData: vi.fn(), getData: vi.fn(), effectAllowed: "", dropEffect: "" }
  fireEvent.dragStart(await screen.findByRole("article", { name: projectTask.title }), { dataTransfer })
  const lane = screen.getByRole("region", { name: "项目任务：已完成" })
  fireEvent.dragOver(lane, { dataTransfer })
  fireEvent.drop(lane, { dataTransfer })
  expect(await screen.findByText(/已移至已完成/)).toBeVisible()
  expect(apiRequest).toHaveBeenCalledWith("/api/v1/task-center/board/project/task-1/status", expect.objectContaining({ method: "PATCH", body: { status: "completed", version: 2 } }))
})

it("restores the original lane when saving fails", async () => {
  let rejectSave!: (error: Error) => void
  mountBoard({ mutate: () => new Promise((_, reject) => { rejectSave = reject }) })
  await screen.findByRole("article", { name: projectTask.title })
  await userEvent.setup().selectOptions(screen.getByLabelText(`${projectTask.title}的状态`), "completed")
  expect(within(screen.getByRole("region", { name: "项目任务：已完成" })).getByRole("article")).toBeVisible()
  expect(screen.getByLabelText(`${projectTask.title}的状态`)).toBeDisabled()
  rejectSave(new Error("网络中断，保存失败。"))
  expect(await screen.findByRole("alert")).toHaveTextContent("网络中断")
  expect(within(screen.getByRole("region", { name: "项目任务：未开始" })).getByRole("article")).toBeVisible()
  expect(screen.getByLabelText(`${projectTask.title}的状态`)).not.toBeDisabled()
})

it("requires a reason before moving a task into the blocked lane", async () => {
  const apiRequest = mountBoard()
  await screen.findByRole("article", { name: projectTask.title })
  await userEvent.setup().selectOptions(screen.getByLabelText(`${projectTask.title}的状态`), "blocked")
  const dialog = screen.getByRole("dialog", { name: "填写阻塞原因" })
  expect(within(dialog).getByRole("button", { name: "确认阻塞" })).toBeDisabled()
  expect(apiRequest.mock.calls.filter(([, options]) => options.method === "PATCH")).toHaveLength(0)
  await userEvent.setup().type(screen.getByLabelText("阻塞原因"), "等待客户补充资料")
  await userEvent.setup().click(within(dialog).getByRole("button", { name: "确认阻塞" }))
  expect(await screen.findByText(/已移至已阻塞/)).toBeVisible()
  expect(apiRequest).toHaveBeenCalledWith("/api/v1/task-center/board/project/task-1/status", expect.objectContaining({ body: { status: "blocked", version: 2, blocked_reason: "等待客户补充资料" } }))
})

it("does not mutate a task when its cancellation is dismissed", async () => {
  const apiRequest = mountBoard()
  await screen.findByRole("article", { name: projectTask.title })
  await userEvent.setup().selectOptions(screen.getByLabelText(`${projectTask.title}的状态`), "cancelled")
  expect(screen.getByRole("dialog", { name: "确认取消任务" })).toHaveTextContent("无法再次修改")
  await userEvent.setup().click(screen.getByRole("button", { name: "返回" }))
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  expect(apiRequest.mock.calls.filter(([, options]) => options.method === "PATCH")).toHaveLength(0)
})

it("keeps read-only tasks non-draggable and hides their editing controls", async () => {
  mountBoard({ task: { ...projectTask, can_edit: false } })
  expect(await screen.findByRole("article", { name: projectTask.title })).toHaveAttribute("draggable", "false")
  expect(screen.queryByLabelText(`${projectTask.title}的状态`)).not.toBeInTheDocument()
  expect(screen.getByText("仅可查看")).toBeVisible()
})

it("uses separate scheduling lanes for automations without completion statuses", async () => {
  const task = { ...projectTask, kind: "automation", source: "wechat", status: "active", assignee_name: "AI Server", schedule: { kind: "interval", expression: "1d" } }
  const apiRequest = mountBoard({ task })
  await screen.findByRole("article", { name: task.title })
  expect(screen.queryByRole("region", { name: "项目任务：已完成" })).not.toBeInTheDocument()
  const selector = screen.getByLabelText(`${task.title}的状态`)
  expect(within(selector).queryByRole("option", { name: "已完成" })).not.toBeInTheDocument()
  await userEvent.setup().selectOptions(selector, "paused")
  expect(await screen.findByText(/已移至已暂停/)).toBeVisible()
  expect(apiRequest).toHaveBeenCalledWith("/api/v1/task-center/board/automation/task-1/status", expect.objectContaining({ body: { status: "paused", version: 2 } }))
})

it("reloads after a version conflict without silently retrying the mutation", async () => {
  const apiRequest = mountBoard({ mutate: () => Promise.resolve(ok({ status: 409, data: null, error: { code: "stale_version", message: "The task has been updated." } })) })
  await screen.findByRole("article", { name: projectTask.title })
  await userEvent.setup().selectOptions(screen.getByLabelText(`${projectTask.title}的状态`), "completed")
  expect(await screen.findByRole("alert")).toHaveTextContent("任务已被其他人更新")
  await waitFor(() => expect(apiRequest.mock.calls.filter(([path]) => path === "/api/v1/task-center/board")).toHaveLength(2))
  expect(apiRequest.mock.calls.filter(([, options]) => options.method === "PATCH")).toHaveLength(1)
})
