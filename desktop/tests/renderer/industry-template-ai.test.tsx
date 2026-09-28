// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

import { App } from "../../src/renderer/src/App"
import type { ApiResponse, BridgeResult } from "../../src/shared/contracts"
import type { ModuleCatalogDto, PageDto, TemplateVersionDto } from "../../src/renderer/src/workbench/types"
import { adminUser, authResult, bridge, installBridge, ok, renderApp } from "./test-utils"


const catalog: ModuleCatalogDto = {
  id: "module-pre",
  key: "pre_diagnosis",
  name: "预诊断",
  description: "澄清目标",
  sort_order: 10,
  is_active: true,
  version: 1,
}

const generated: TemplateVersionDto = {
  template_id: "template-ai",
  template_name: "制造业 AI 模板",
  industry_name: "制造业",
  description: "AI 生成",
  version_id: "version-ai",
  version_number: 1,
  status: "draft",
  version: 1,
  published_by_user_id: null,
  published_at: null,
  modules: [],
}

function apiOk<T>(data: T, status = 200): BridgeResult<ApiResponse<T>> {
  return ok({ status, data, error: null })
}

function execution(result: unknown, operation = "industry_template_chat") {
  return { id: `execution-${operation}`, operation, status: "completed", stage: "结果已校验", result,
    error: null, events: [], next_offset: 0, created_at: "2026-09-05T00:00:00Z", updated_at: "2026-09-05T00:00:01Z" }
}

function list<T>(items: T[]): PageDto<T> {
  return { items, page: 1, page_size: 100, total: items.length }
}

function renderAI(apiRequest: ReturnType<typeof vi.fn>) {
  installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
  renderApp(<App />)
}

beforeEach(() => {
  location.hash = "#templates"
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  location.hash = ""
})


it("shows a loading indicator while waiting for the AI chat reply", async () => {
  let resolveChat: ((value: BridgeResult<ApiResponse<unknown>>) => void) | undefined
  const pendingChat = new Promise<BridgeResult<ApiResponse<unknown>>>((resolve) => {
    resolveChat = resolve
  })
  const apiRequest = vi.fn()
    .mockResolvedValueOnce(apiOk(list([])))
    .mockResolvedValueOnce(apiOk(list([catalog])))
    .mockReturnValueOnce(pendingChat)
  renderAI(apiRequest)
  const user = userEvent.setup()
  await screen.findByRole("heading", { name: "行业模板" })
  await user.click(screen.getByRole("button", { name: "新建模板" }))
  await user.click(screen.getByRole("button", { name: "AI 辅助创建" }))
  await user.type(screen.getByLabelText("告诉 AI 你的需求"), "只生成两个模块")
  await user.click(screen.getByRole("button", { name: "发送" }))

  expect(await screen.findByRole("status")).toHaveTextContent("正在启动 AI")
  expect(screen.getByRole("button", { name: "正在发送" })).toBeDisabled()

  resolveChat?.(apiOk(execution({
    status: "need_more_information",
    message: "请补充范围",
    known_information: {},
    missing_fields: [],
    questions: ["需要哪些模块？"],
  })))
})


it("continues clarification and preserves the conversation", async () => {
  const apiRequest = vi.fn()
    .mockResolvedValueOnce(apiOk(list([])))
    .mockResolvedValueOnce(apiOk(list([catalog])))
    .mockResolvedValueOnce(apiOk(execution({
      status: "need_more_information",
      message: "请补充目标",
      known_information: { industry: "制造业" },
      missing_fields: ["business_goal"],
      questions: ["最希望改善什么流程？"],
    })))
  renderAI(apiRequest)
  const user = userEvent.setup()
  await screen.findByRole("heading", { name: "行业模板" })
  await user.click(screen.getByRole("button", { name: "新建模板" }))
  const aiButton = screen.getByRole("button", { name: "AI 辅助创建" })
  expect(aiButton).toHaveClass("ai-assist-button")
  await user.click(aiButton)
  await user.type(screen.getByLabelText("告诉 AI 你的需求"), "制造业")
  await user.click(screen.getByRole("button", { name: "发送" }))

  expect(await screen.findByText("最希望改善什么流程？")).toBeVisible()
  expect(screen.getByText("制造业")).toBeVisible()
  expect(screen.getByText(adminUser.username)).toBeVisible()
  expect(screen.queryByText("你")).not.toBeInTheDocument()
  const chatLog = screen.getByText("制造业").closest(".ai-chat-log")
  expect(chatLog).toHaveClass("content-sized")
  expect(screen.getByLabelText("告诉 AI 你的需求")).toBeEnabled()
  expect(screen.getByRole("button", { name: "按现有信息生成草稿" })).toBeEnabled()
})


it("allows generating immediately instead of forcing more clarification", async () => {
  const apiRequest = vi.fn()
    .mockResolvedValueOnce(apiOk(list([])))
    .mockResolvedValueOnce(apiOk(list([catalog])))
    .mockResolvedValueOnce(apiOk(execution({
      status: "need_more_information",
      message: "如果你愿意可以补充目标。",
      known_information: { company: "华翊智能" },
      missing_fields: ["business_goal"],
      questions: ["最关注哪个业务环节？"],
    })))
    .mockResolvedValueOnce(apiOk(execution(generated, "industry_template_generate"), 201))
  renderAI(apiRequest)
  const user = userEvent.setup()
  await screen.findByRole("heading", { name: "行业模板" })
  await user.click(screen.getByRole("button", { name: "新建模板" }))
  await user.click(screen.getByRole("button", { name: "AI 辅助创建" }))
  await user.type(screen.getByLabelText("告诉 AI 你的需求"), "华翊智能")
  await user.click(screen.getByRole("button", { name: "发送" }))
  await user.click(await screen.findByRole("button", { name: "按现有信息生成草稿" }))

  expect(await screen.findByDisplayValue("制造业 AI 模板")).toBeVisible()
  expect(apiRequest).toHaveBeenLastCalledWith(
    "/api/v1/ai/executions",
    expect.objectContaining({
      method: "POST",
      body: expect.objectContaining({ operation: "industry_template_generate", payload: expect.objectContaining({ known_information: { company: "华翊智能" } }) }),
    }),
  )
})


it("locks input, generates a draft and opens the existing editor", async () => {
  const apiRequest = vi.fn()
    .mockResolvedValueOnce(apiOk(list([])))
    .mockResolvedValueOnce(apiOk(list([catalog])))
    .mockResolvedValueOnce(apiOk(execution({
      status: "ready_to_generate",
      message: "信息已充分，开始生成模板。",
      known_information: { industry: "制造业" },
      missing_fields: [],
      questions: [],
    })))
    .mockResolvedValueOnce(apiOk(execution(generated, "industry_template_generate"), 201))
  renderAI(apiRequest)
  const user = userEvent.setup()
  await screen.findByRole("heading", { name: "行业模板" })
  await user.click(screen.getByRole("button", { name: "新建模板" }))
  await user.click(screen.getByRole("button", { name: "AI 辅助创建" }))
  await user.type(screen.getByLabelText("告诉 AI 你的需求"), "制造业，改善订单流程")
  await user.click(screen.getByRole("button", { name: "发送" }))

  expect(await screen.findByDisplayValue("制造业 AI 模板")).toBeVisible()
  expect(screen.getByText("AI 已生成并保存草稿，请审核后手动发布")).toBeVisible()
  expect(apiRequest).toHaveBeenCalledWith(
    "/api/v1/ai/executions",
    expect.objectContaining({ method: "POST", body: expect.objectContaining({ operation: "industry_template_generate" }) }),
  )
})


it("shows a Chinese message when the AI endpoint is missing", async () => {
  installBridge(bridge({
    refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
    apiRequest: vi.fn()
      .mockResolvedValueOnce(apiOk(list([])))
      .mockResolvedValueOnce(apiOk(list([catalog])))
      .mockResolvedValueOnce(ok({
        status: 404,
        data: null,
        error: { code: "not_found", message: "The requested URL was not found on the server." },
      })),
  }))
  renderApp(<App />)
  const user = userEvent.setup()
  await screen.findByRole("heading", { name: "行业模板" })
  await user.click(screen.getByRole("button", { name: "新建模板" }))
  await user.click(screen.getByRole("button", { name: "AI 辅助创建" }))
  await user.type(screen.getByLabelText("告诉 AI 你的需求"), "制造业")
  await user.click(screen.getByRole("button", { name: "发送" }))

  expect(await screen.findByText("AI 接口不可用，请重启本地服务或联系管理员检查版本。")).toBeVisible()
})
