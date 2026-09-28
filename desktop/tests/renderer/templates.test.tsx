// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { App } from "../../src/renderer/src/App"
import type { ApiResponse, BridgeResult } from "../../src/shared/contracts"
import type {
  ModuleCatalogDto,
  PageDto,
  TemplateVersionDto,
} from "../../src/renderer/src/workbench/types"
import {
  adminUser,
  authResult,
  bridge,
  deferred,
  installBridge,
  ok,
  renderApp,
} from "./test-utils"

const catalogModule: ModuleCatalogDto = {
  id: "module-pov",
  key: "pov",
  name: "PoV 验证",
  description: "验证优先场景。",
  sort_order: 30,
  is_active: true,
  version: 1,
}

const publishedV1: TemplateVersionDto = {
  template_id: "template-manufacturing",
  template_name: "制造业 AI 落地模板",
  industry_name: "制造业",
  description: "从诊断到 PoV。",
  version_id: "version-v1",
  version_number: 1,
  status: "published",
  version: 2,
  published_by_user_id: "admin-id",
  published_at: "2026-08-21T08:00:00+00:00",
  modules: [
    {
      id: "template-module-pov",
      module_catalog_id: "module-pov",
      module_key: "pov",
      name: "PoV 验证",
      description: "验证优先场景。",
      sort_order: 30,
      tasks: [
        {
          id: "task-prepare",
          task_key: "prepare_data",
          name: "准备数据",
          description: "",
          duration_days: 2,
          default_assignee_role: "fde_engineer",
          sort_order: 10,
          dependency_keys: [],
        },
      ],
    },
  ],
}

const draftV2: TemplateVersionDto = {
  ...publishedV1,
  version_id: "version-v2",
  version_number: 2,
  status: "draft",
  version: 1,
  published_by_user_id: null,
  published_at: null,
}

beforeEach(() => {
  location.hash = "#templates"
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  location.hash = ""
})

function apiOk<T>(data: T, status = 200): BridgeResult<ApiResponse<T>> {
  return ok({ status, data, error: null })
}

function list<T>(items: T[]): PageDto<T> {
  return { items, page: 1, page_size: 100, total: items.length }
}

function page<T>(items: T[], pageNumber: number, pageSize: number, total: number): PageDto<T> {
  return { items, page: pageNumber, page_size: pageSize, total }
}

function researchDefinition(version: number) {
  return { version, forms: [] }
}

function renderTemplates(apiRequest: ReturnType<typeof vi.fn>): void {
  installBridge(
    bridge({
      refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
      apiRequest,
    }),
  )
  renderApp(<App />)
}

function initialResponses(versions: TemplateVersionDto[] = [draftV2, publishedV1]) {
  return [
    apiOk(list(versions)),
    apiOk(list([catalogModule])),
  ]
}

async function openNewTemplate(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await screen.findByRole("heading", { name: "行业模板" })
  await user.click(screen.getByRole("button", { name: "新建模板" }))
  await user.type(screen.getByLabelText("模板名称"), "制造业场景验证")
  await user.type(screen.getByLabelText("行业名称"), "制造业")
  await user.selectOptions(screen.getByLabelText("选择模块"), "pov")
  await user.click(screen.getByRole("button", { name: "添加模块" }))
}

async function addTwoTasks(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.click(screen.getByRole("button", { name: "在 PoV 验证中新增任务" }))
  await user.click(screen.getByRole("button", { name: "在 PoV 验证中新增任务" }))
  const names = screen.getAllByLabelText(/任务名称$/)
  const keys = screen.getAllByLabelText(/稳定任务标识$/)
  await user.type(names[0], "准备数据")
  await user.type(keys[0], "prepare_data")
  await user.type(names[1], "验证场景")
  await user.type(keys[1], "validate_scene")
}

describe("行业模板版本管理", () => {
  it("列表展示同一模板的草稿与已发布历史", async () => {
    const pending = deferred<BridgeResult<ApiResponse<PageDto<TemplateVersionDto>>>>()
    const apiRequest = vi
      .fn()
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValueOnce(apiOk(list([catalogModule])))
    renderTemplates(apiRequest)

    expect(await screen.findByText("正在加载模板…")).toBeVisible()
    pending.resolve(apiOk(list([draftV2, publishedV1])))
    const rows = await screen.findAllByRole("row", { name: /制造业 AI 落地模板/ })
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText("v2")).toBeVisible()
    expect(within(rows[0]).getByText("草稿")).toBeVisible()
    expect(within(rows[1]).getByText("v1")).toBeVisible()
    expect(within(rows[1]).getByText("已发布")).toBeVisible()
    expect(apiRequest).toHaveBeenCalledWith(
      "/api/v1/industry-templates?page=1&page_size=100",
      expect.objectContaining({ method: "GET" }),
    )
  })

  it("创建 v1 草稿，完整保存模块、任务和依赖 payload", async () => {
    const created: TemplateVersionDto = {
      ...publishedV1,
      template_name: "制造业场景验证",
      version_id: "new-v1",
      status: "draft",
      version: 1,
      published_by_user_id: null,
      published_at: null,
    }
    const apiRequest = vi.fn()
    for (const response of initialResponses([])) apiRequest.mockResolvedValueOnce(response)
    apiRequest
      .mockResolvedValueOnce(apiOk(created, 201))
      .mockResolvedValueOnce(apiOk(researchDefinition(2)))
    renderTemplates(apiRequest)
    const user = userEvent.setup()

    await openNewTemplate(user)
    await addTwoTasks(user)
    await user.click(within(screen.getByLabelText("验证场景的前置任务")).getByRole("checkbox", { name: "准备数据" }))
    await user.click(screen.getByRole("button", { name: "保存草稿" }))

    expect(await screen.findByText("草稿已保存")).toBeVisible()
    expect(apiRequest).toHaveBeenNthCalledWith(3, "/api/v1/industry-templates", expect.objectContaining({
      method: "POST",
      body: {
        name: "制造业场景验证",
        industry_name: "制造业",
        description: "",
        modules: [
          {
            module_key: "pov",
            name: "PoV 验证",
            description: "验证优先场景。",
            sort_order: 30,
            tasks: [
              {
                task_key: "prepare_data",
                name: "准备数据",
                description: "",
                duration_days: 1,
                default_assignee_role: "fde_engineer",
                sort_order: 10,
                dependency_keys: [],
              },
              {
                task_key: "validate_scene",
                name: "验证场景",
                description: "",
                duration_days: 1,
                default_assignee_role: "fde_engineer",
                sort_order: 20,
                dependency_keys: ["prepare_data"],
              },
            ],
          },
        ],
      },
    }))
    expect(apiRequest).toHaveBeenNthCalledWith(4,
      "/api/v1/templates/template-manufacturing/versions/new-v1/research-forms",
      expect.objectContaining({ method: "PUT", body: { version: 1, forms: [] } }),
    )
  })

  it("草稿编辑发送服务端 version，stale 错误时保留本地值", async () => {
    const apiRequest = vi.fn()
    for (const response of initialResponses([draftV2])) apiRequest.mockResolvedValueOnce(response)
    apiRequest
      .mockResolvedValueOnce(apiOk(researchDefinition(1)))
      .mockResolvedValueOnce(
        ok({ status: 409, data: null, error: { code: "stale_version", message: "stale" } }),
      )
      .mockResolvedValueOnce(apiOk({ ...draftV2, version: 2, description: "服务器中的说明" }))
      .mockResolvedValueOnce(apiOk(researchDefinition(2)))
      .mockResolvedValueOnce(apiOk({ ...draftV2, version: 3, description: "本地尚未保存的说明" }))
      .mockResolvedValueOnce(apiOk(researchDefinition(4)))
    renderTemplates(apiRequest)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "编辑 v2" }))
    const description = screen.getByLabelText("模板说明")
    await user.clear(description)
    await user.type(description, "本地尚未保存的说明")
    await user.click(screen.getByRole("button", { name: "保存草稿" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("草稿已被其他操作更新")
    expect(description).toHaveValue("本地尚未保存的说明")
    expect(apiRequest).toHaveBeenNthCalledWith(4, "/api/v1/industry-templates/versions/version-v2", expect.objectContaining({
      method: "PATCH",
      body: expect.objectContaining({
        version: 1,
        description: "本地尚未保存的说明",
      }),
    }))
    expect(apiRequest).toHaveBeenCalledTimes(4)

    await user.click(screen.getByRole("button", { name: "重新加载服务器完整草稿（舍弃本地修改）" }))
    expect(apiRequest).toHaveBeenNthCalledWith(
      5,
      "/api/v1/industry-templates/versions/version-v2",
      expect.objectContaining({ method: "GET" }),
    )
    expect(description).toHaveValue("服务器中的说明")
    await user.clear(description)
    await user.type(description, "本地尚未保存的说明")

    await user.click(screen.getByRole("button", { name: "保存草稿" }))
    expect(await screen.findByText("草稿已保存")).toBeVisible()
    expect(apiRequest).toHaveBeenNthCalledWith(
      7,
      "/api/v1/industry-templates/versions/version-v2",
      expect.objectContaining({
        method: "PATCH",
        body: expect.objectContaining({
          version: 2,
          description: "本地尚未保存的说明",
        }),
      }),
    )
  })

  it("保存新 v1 后调用发布端点并返回历史列表", async () => {
    const created = { ...draftV2, version_id: "new-v1", version_number: 1 }
    const published = {
      ...created,
      status: "published" as const,
      version: 2,
      published_by_user_id: "admin-id",
      published_at: "2026-08-21T09:00:00+00:00",
    }
    const apiRequest = vi.fn()
    for (const response of initialResponses([])) apiRequest.mockResolvedValueOnce(response)
    apiRequest
      .mockResolvedValueOnce(apiOk(created, 201))
      .mockResolvedValueOnce(apiOk(researchDefinition(2)))
      .mockResolvedValueOnce(apiOk({ ...published, version: 3 }))
    renderTemplates(apiRequest)
    const user = userEvent.setup()

    await openNewTemplate(user)
    await addTwoTasks(user)
    await user.click(within(screen.getByLabelText("验证场景的前置任务")).getByRole("checkbox", { name: "准备数据" }))
    await user.click(screen.getByRole("button", { name: "发布 v1" }))

    expect(await screen.findByText("v1 已发布")).toBeVisible()
    expect(apiRequest).toHaveBeenNthCalledWith(
      5,
      "/api/v1/industry-templates/versions/new-v1/publish",
      expect.objectContaining({ method: "POST", body: { version: 2 } }),
    )
    expect(screen.getByRole("row", { name: /制造业 AI 落地模板/ })).toHaveTextContent("已发布")
  })

  it("发布失败时在发布操作旁显示服务校验并保留草稿", async () => {
    const apiRequest = vi.fn()
    for (const response of initialResponses([draftV2])) apiRequest.mockResolvedValueOnce(response)
    apiRequest
      .mockResolvedValueOnce(apiOk(researchDefinition(1)))
      .mockResolvedValueOnce(apiOk({ ...draftV2, version: 2 }))
      .mockResolvedValueOnce(
        ok({ status: 400, data: null, error: { code: "cyclic_dependency", message: "cycle" } }),
      )
    renderTemplates(apiRequest)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "编辑 v2" }))
    const description = screen.getByLabelText("模板说明")
    await user.clear(description)
    await user.type(description, "发布前的本地草稿")
    await user.click(screen.getByRole("button", { name: "发布 v2" }))

    const actions = screen.getByTestId("publish-actions")
    expect(await within(actions).findByRole("alert")).toHaveTextContent("任务依赖存在循环")
    expect(description).toHaveValue("发布前的本地草稿")
    expect(apiRequest).toHaveBeenNthCalledWith(
      5,
      "/api/v1/industry-templates/versions/version-v2/publish",
      expect.objectContaining({ method: "POST", body: { version: 2 } }),
    )
  })

  it("发布 stale 时保留草稿且不自动重试", async () => {
    const saved = { ...draftV2, version: 2, description: "本地待发布草稿" }
    const apiRequest = vi.fn()
    for (const response of initialResponses([draftV2])) apiRequest.mockResolvedValueOnce(response)
    apiRequest
      .mockResolvedValueOnce(apiOk(researchDefinition(1)))
      .mockResolvedValueOnce(apiOk(saved))
      .mockResolvedValueOnce(
        ok({ status: 409, data: null, error: { code: "stale_version", message: "stale" } }),
      )
      .mockResolvedValueOnce(apiOk({ ...saved, version: 4, description: "服务器草稿" }))
    renderTemplates(apiRequest)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "编辑 v2" }))
    const description = screen.getByLabelText("模板说明")
    await user.clear(description)
    await user.type(description, "本地待发布草稿")
    await user.click(screen.getByRole("button", { name: "发布 v2" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("草稿已被其他操作更新")
    expect(description).toHaveValue("本地待发布草稿")
    expect(apiRequest).toHaveBeenNthCalledWith(
      5,
      "/api/v1/industry-templates/versions/version-v2/publish",
      expect.objectContaining({ method: "POST", body: { version: 2 } }),
    )
    expect(apiRequest).toHaveBeenCalledTimes(5)

    await user.click(screen.getByRole("button", { name: "重新加载服务器完整草稿（舍弃本地修改）" }))
    expect(description).toHaveValue("服务器草稿")
    expect(apiRequest).toHaveBeenNthCalledWith(
      6,
      "/api/v1/industry-templates/versions/version-v2",
      expect.objectContaining({ method: "GET" }),
    )
  })

  it("删除草稿要求当前密码并发送当前 version 接受 204", async () => {
    const apiRequest = vi.fn()
    for (const response of initialResponses([draftV2])) {
      apiRequest.mockResolvedValueOnce(response)
    }
    apiRequest.mockResolvedValueOnce(apiOk({ valid: true }))
    apiRequest.mockResolvedValueOnce(apiOk<void>(undefined, 204))
    renderTemplates(apiRequest)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "编辑 v2" }))

    await user.click(screen.getByRole("button", { name: "删除草稿" }))
    const dialog = await screen.findByRole("dialog", { name: "删除草稿" })
    await user.type(within(dialog).getByLabelText("当前账号密码"), "AdminPass!123")
    await user.click(within(dialog).getByRole("button", { name: "删除" }))

    expect(await screen.findByText("v2 草稿已删除")).toBeVisible()
    expect(apiRequest).toHaveBeenNthCalledWith(
      3,
      "/api/v1/auth/verify-password",
      expect.objectContaining({ method: "POST", body: { password: "AdminPass!123" } }),
    )
    expect(apiRequest).toHaveBeenNthCalledWith(
      4,
      "/api/v1/industry-templates/versions/version-v2",
      expect.objectContaining({ method: "DELETE", body: { version: 1 } }),
    )
  })

  it("依赖选项只显示任务名称，并将会形成循环的任务置灰禁用", async () => {
    const apiRequest = vi.fn()
    for (const response of initialResponses([])) apiRequest.mockResolvedValueOnce(response)
    renderTemplates(apiRequest)
    const user = userEvent.setup()
    await openNewTemplate(user)
    await addTwoTasks(user)

    const validationDependencies = screen.getByLabelText("验证场景的前置任务")
    expect(within(validationDependencies).queryByRole("checkbox", { name: /验证场景/ })).not.toBeInTheDocument()
    const prepareData = within(validationDependencies).getByRole("checkbox", { name: "准备数据" })
    expect(prepareData).toBeVisible()
    await user.click(prepareData)

    const prepareDependencies = screen.getByLabelText("准备数据的前置任务")
    const cyclicTask = within(prepareDependencies).getByRole("checkbox", { name: "验证场景" })
    expect(cyclicTask).toBeDisabled()
    expect(cyclicTask.closest("label")).toHaveClass("cycle-disabled")
  })

  it("仅从聚合最新版本创建下一版草稿，旧版本行无复制动作", async () => {
    const inactiveV2: TemplateVersionDto = {
      ...publishedV1,
      version_id: "version-v2",
      version_number: 2,
      status: "inactive",
    }
    const publishedV3: TemplateVersionDto = {
      ...publishedV1,
      version_id: "version-v3",
      version_number: 3,
    }
    const draftV4: TemplateVersionDto = {
      ...publishedV3,
      version_id: "version-v4",
      version_number: 4,
      status: "draft",
      version: 1,
      published_by_user_id: null,
      published_at: null,
    }
    const apiRequest = vi.fn()
    for (const response of initialResponses([publishedV3, inactiveV2, publishedV1])) apiRequest.mockResolvedValueOnce(response)
    apiRequest.mockResolvedValueOnce(apiOk(draftV4, 201))
    renderTemplates(apiRequest)
    const user = userEvent.setup()
    const createNext = await screen.findByRole("button", { name: "基于最新版本创建 v4" })
    expect(screen.queryByRole("button", { name: /复制 v1/ })).not.toBeInTheDocument()
    expect(screen.getAllByRole("button", { name: /基于最新版本/ })).toHaveLength(1)
    await user.click(createNext)

    expect(await screen.findByRole("heading", { name: "编辑 v4 草稿" })).toBeVisible()
    expect(apiRequest).toHaveBeenNthCalledWith(
      3,
      "/api/v1/industry-templates/template-manufacturing/versions",
      expect.objectContaining({ method: "POST", body: {} }),
    )
  })

  it("聚合已有草稿时说明状态且不提供新版本动作", async () => {
    const publishedV2 = { ...publishedV1, version_id: "published-v2", version_number: 2 }
    const draftV3 = { ...draftV2, version_id: "draft-v3", version_number: 3 }
    const apiRequest = vi.fn()
    for (const response of initialResponses([draftV3, publishedV2, publishedV1])) apiRequest.mockResolvedValueOnce(response)
    renderTemplates(apiRequest)

    expect(await screen.findByText("已有草稿")).toBeVisible()
    expect(screen.queryByRole("button", { name: /基于最新版本/ })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "编辑 v3" })).toBeVisible()
  })

  it("模板历史消费第二页并可编辑第 101 个版本", async () => {
    const firstPage = Array.from({ length: 100 }, (_, index): TemplateVersionDto => ({
      ...publishedV1,
      template_id: `template-${index + 1}`,
      template_name: `历史模板 ${index + 1}`,
      version_id: `history-${index + 1}`,
    }))
    const pageTwoDraft: TemplateVersionDto = {
      ...draftV2,
      template_id: "template-101",
      template_name: "第 101 个模板",
      version_id: "history-101",
    }
    const apiRequest = vi.fn((path: string) => {
      if (path === "/api/v1/industry-templates?page=1&page_size=100") return Promise.resolve(apiOk(page(firstPage, 1, 100, 101)))
      if (path === "/api/v1/industry-templates?page=2&page_size=100") return Promise.resolve(apiOk(page([pageTwoDraft], 2, 100, 101)))
      if (path === "/api/v1/modules?active=true&page=1&page_size=100") return Promise.resolve(apiOk(list([catalogModule])))
      throw new Error(`Unexpected API path: ${path}`)
    })
    renderTemplates(apiRequest)
    const user = userEvent.setup()

    expect(await screen.findByText("101 个版本")).toBeVisible()
    await user.click(screen.getByRole("button", { name: "编辑 v2" }))
    expect(await screen.findByRole("heading", { name: "编辑 v2 草稿" })).toBeVisible()
  })

  it("模板编辑器可选择活动模块目录第二页的第 101 条", async () => {
    const firstPage = Array.from({ length: 100 }, (_, index): ModuleCatalogDto => ({
      ...catalogModule,
      id: `catalog-${index + 1}`,
      key: `catalog_${index + 1}`,
      name: `可选模块 ${index + 1}`,
      sort_order: index + 1,
    }))
    const pageTwoModule: ModuleCatalogDto = {
      ...catalogModule,
      id: "catalog-101",
      key: "catalog_101",
      name: "第二页可选模块",
      sort_order: 101,
    }
    const apiRequest = vi.fn((path: string) => {
      if (path === "/api/v1/industry-templates?page=1&page_size=100") return Promise.resolve(apiOk(list([])))
      if (path === "/api/v1/modules?active=true&page=1&page_size=100") return Promise.resolve(apiOk(page(firstPage, 1, 100, 101)))
      if (path === "/api/v1/modules?active=true&page=2&page_size=100") return Promise.resolve(apiOk(page([pageTwoModule], 2, 100, 101)))
      throw new Error(`Unexpected API path: ${path}`)
    })
    renderTemplates(apiRequest)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "新建模板" }))

    expect(screen.getByRole("option", { name: "第二页可选模块（catalog_101）" })).toBeVisible()
  })

  it("停用已发布版本前要求输入当前密码", async () => {
    const inactive = { ...publishedV1, status: "inactive" as const }
    const apiRequest = vi.fn()
    for (const response of initialResponses([publishedV1])) apiRequest.mockResolvedValueOnce(response)
    apiRequest.mockResolvedValueOnce(apiOk({ valid: true }))
    apiRequest.mockResolvedValueOnce(apiOk(inactive))
    renderTemplates(apiRequest)
    const user = userEvent.setup()
    const deactivate = await screen.findByRole("button", { name: "停用 v1" })

    await user.click(deactivate)
    let dialog = await screen.findByRole("dialog", { name: "停用模板版本" })
    await user.click(within(dialog).getByRole("button", { name: "取消" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(apiRequest).toHaveBeenCalledTimes(2)

    await user.click(deactivate)
    dialog = await screen.findByRole("dialog", { name: "停用模板版本" })
    await user.type(within(dialog).getByLabelText("当前账号密码"), "AdminPass!123")
    await user.click(within(dialog).getByRole("button", { name: "停用" }))
    await waitFor(() => expect(apiRequest).toHaveBeenCalledTimes(4))
    expect(apiRequest).toHaveBeenNthCalledWith(
      3,
      "/api/v1/auth/verify-password",
      expect.objectContaining({ method: "POST", body: { password: "AdminPass!123" } }),
    )
    expect(apiRequest).toHaveBeenNthCalledWith(
      4,
      "/api/v1/industry-templates/versions/version-v1/deactivate",
      expect.objectContaining({ method: "POST", body: { version: 2 } }),
    )
    expect(await screen.findByText("已停用")).toBeVisible()
  })

  it("停用 stale 时不改本地状态并可显式刷新列表", async () => {
    const latest = { ...publishedV1, version: 3 }
    const apiRequest = vi.fn()
    for (const response of initialResponses([publishedV1])) apiRequest.mockResolvedValueOnce(response)
    apiRequest
      .mockResolvedValueOnce(apiOk({ valid: true }))
      .mockResolvedValueOnce(
        ok({ status: 409, data: null, error: { code: "stale_version", message: "stale" } }),
      )
      .mockResolvedValueOnce(apiOk(list([latest])))
    renderTemplates(apiRequest)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "停用 v1" }))
    let dialog = await screen.findByRole("dialog", { name: "停用模板版本" })
    await user.type(within(dialog).getByLabelText("当前账号密码"), "AdminPass!123")
    await user.click(within(dialog).getByRole("button", { name: "停用" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("模板已被其他操作更新")
    expect(screen.getByText("已发布")).toBeVisible()
    expect(apiRequest).toHaveBeenCalledTimes(4)

    await user.click(screen.getByRole("button", { name: "刷新模板列表" }))
    expect(apiRequest).toHaveBeenNthCalledWith(
      5,
      "/api/v1/industry-templates?page=1&page_size=100",
      expect.objectContaining({ method: "GET" }),
    )
  })

  it("已发布版本可进入编辑且不显示发布/删除动作", async () => {
    const apiRequest = vi.fn()
    for (const response of initialResponses([publishedV1])) apiRequest.mockResolvedValueOnce(response)
    renderTemplates(apiRequest)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "编辑 v1" }))
    expect(await screen.findByRole("heading", { name: "编辑 v1 版本" })).toBeVisible()
    expect(screen.queryByRole("button", { name: /发布 v1/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "删除草稿" })).not.toBeInTheDocument()
  })

  it("已发布版本可直接保存并递增服务端 version", async () => {
    const updated = { ...publishedV1, version: 3, description: "发布后修订" }
    const apiRequest = vi.fn()
    for (const response of initialResponses([publishedV1])) apiRequest.mockResolvedValueOnce(response)
    apiRequest
      .mockResolvedValueOnce(apiOk(researchDefinition(2)))
      .mockResolvedValueOnce(apiOk(updated))
    renderTemplates(apiRequest)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "编辑 v1" }))
    const description = screen.getByLabelText("模板说明")
    await user.clear(description)
    await user.type(description, "发布后修订")
    await user.click(screen.getByRole("button", { name: "保存草稿" }))

    expect(await screen.findByText("草稿已保存")).toBeVisible()
    expect(apiRequest).toHaveBeenNthCalledWith(
      4,
      "/api/v1/industry-templates/versions/version-v1",
      expect.objectContaining({
        method: "PATCH",
        body: expect.objectContaining({ version: 2, description: "发布后修订" }),
      }),
    )
  })
})
