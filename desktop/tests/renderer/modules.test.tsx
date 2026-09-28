// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { App } from "../../src/renderer/src/App"
import type { ApiResponse, BridgeResult } from "../../src/shared/contracts"
import type { ModuleCatalogDto, PageDto } from "../../src/renderer/src/workbench/types"
import {
  adminUser,
  authResult,
  bridge,
  deferred,
  installBridge,
  ok,
  renderApp,
} from "./test-utils"

const moduleItem: ModuleCatalogDto = {
  id: "module-pov",
  key: "pov",
  name: "PoV 验证",
  description: "验证业务价值。",
  sort_order: 30,
  is_active: true,
  version: 1,
}

beforeEach(() => {
  location.hash = "#modules"
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  location.hash = ""
})

function apiOk<T>(data: T, status = 200): BridgeResult<ApiResponse<T>> {
  return ok({ status, data, error: null })
}

function moduleList(items: ModuleCatalogDto[] = [moduleItem]) {
  return apiOk<PageDto<ModuleCatalogDto>>({
    items,
    page: 1,
    page_size: 100,
    total: items.length,
  })
}

function modulePage(items: ModuleCatalogDto[], page: number, pageSize: number, total: number) {
  return apiOk<PageDto<ModuleCatalogDto>>({ items, page, page_size: pageSize, total })
}

function numberedModule(index: number): ModuleCatalogDto {
  return {
    ...moduleItem,
    id: `module-${index}`,
    key: `module_${index}`,
    name: `模块 ${index}`,
    sort_order: index,
  }
}

function renderModules(apiRequest: ReturnType<typeof vi.fn>): void {
  installBridge(
    bridge({
      refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
      apiRequest,
    }),
  )
  renderApp(<App />)
}

describe("模块目录管理", () => {
  it("加载并展示模块的标识、排序、说明与状态", async () => {
    const pending = deferred<BridgeResult<ApiResponse<PageDto<ModuleCatalogDto>>>>()
    const apiRequest = vi.fn().mockReturnValueOnce(pending.promise)
    renderModules(apiRequest)

    expect(await screen.findByText("正在加载模块…")).toBeVisible()
    pending.resolve(moduleList())
    const row = await screen.findByRole("row", { name: /PoV 验证/ })
    expect(within(row).getByText("pov")).toBeVisible()
    expect(within(row).getByText("验证业务价值。")).toBeVisible()
    expect(within(row).getByText("30")).toBeVisible()
    expect(within(row).getByText("启用")).toBeVisible()
    expect(apiRequest).toHaveBeenCalledWith(
      "/api/v1/modules?page=1&page_size=100",
      expect.objectContaining({ method: "GET" }),
    )
  })

  it("新增模块时使用当前服务的精确 payload", async () => {
    const created: ModuleCatalogDto = {
      ...moduleItem,
      id: "module-data",
      key: "data_governance",
      name: "数据治理",
      description: "数据准备与质量检查。",
      sort_order: 40,
    }
    const apiRequest = vi
      .fn()
      .mockResolvedValueOnce(moduleList())
      .mockResolvedValueOnce(apiOk(created, 201))
    renderModules(apiRequest)
    const user = userEvent.setup()
    await screen.findByText("PoV 验证")

    await user.type(screen.getByLabelText("模块标识"), "data_governance")
    await user.type(screen.getByLabelText("模块名称"), "数据治理")
    await user.type(screen.getByLabelText("模块说明"), "数据准备与质量检查。")
    await user.clear(screen.getByLabelText("模块排序"))
    await user.type(screen.getByLabelText("模块排序"), "40")
    await user.click(screen.getByRole("button", { name: "新增模块" }))

    expect(await screen.findByText("模块已新增")).toBeVisible()
    expect(screen.getByRole("row", { name: /数据治理/ })).toBeVisible()
    expect(apiRequest).toHaveBeenNthCalledWith(2, "/api/v1/modules", expect.objectContaining({
      method: "POST",
      body: {
        key: "data_governance",
        name: "数据治理",
        description: "数据准备与质量检查。",
        sort_order: 40,
        is_active: true,
      },
    }))
  })

  it("编辑名称时保持模块 key 只读且不发送 key", async () => {
    const renamed = { ...moduleItem, name: "价值验证", version: 2 }
    const apiRequest = vi
      .fn()
      .mockResolvedValueOnce(moduleList())
      .mockResolvedValueOnce(apiOk(renamed))
    renderModules(apiRequest)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "编辑 PoV 验证" }))

    const key = screen.getByLabelText("模块标识（只读）")
    expect(key).toHaveValue("pov")
    expect(key).toHaveAttribute("readonly")
    const name = screen.getByLabelText("编辑模块名称")
    await user.clear(name)
    await user.type(name, "价值验证")
    await user.click(screen.getByRole("button", { name: "保存模块" }))

    expect(await screen.findByText("模块已保存")).toBeVisible()
    expect(apiRequest).toHaveBeenNthCalledWith(2, "/api/v1/modules/module-pov", expect.objectContaining({
      method: "PATCH",
      body: {
        version: 1,
        name: "价值验证",
        description: "验证业务价值。",
        sort_order: 30,
      },
    }))
    expect(screen.getByText("pov")).toBeVisible()
  })

  it("过期编辑保留表单，由用户刷新版本后再重试", async () => {
    const latest = { ...moduleItem, name: "服务器名称", version: 2 }
    const apiRequest = vi
      .fn()
      .mockResolvedValueOnce(moduleList())
      .mockResolvedValueOnce(
        ok({ status: 409, data: null, error: { code: "stale_version", message: "stale" } }),
      )
      .mockResolvedValueOnce(moduleList([latest]))
      .mockResolvedValueOnce(apiOk({ ...latest, name: "本地未保存名称", version: 3 }))
    renderModules(apiRequest)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "编辑 PoV 验证" }))
    const name = screen.getByLabelText("编辑模块名称")
    await user.clear(name)
    await user.type(name, "本地未保存名称")
    await user.click(screen.getByRole("button", { name: "保存模块" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("模块已被其他人更新")
    expect(name).toHaveValue("本地未保存名称")
    expect(apiRequest).toHaveBeenCalledTimes(2)
    expect(apiRequest).toHaveBeenNthCalledWith(2, "/api/v1/modules/module-pov", expect.objectContaining({
      method: "PATCH",
      body: expect.objectContaining({ version: 1, name: "本地未保存名称" }),
    }))

    await user.click(screen.getByRole("button", { name: "刷新模块版本" }))
    expect(name).toHaveValue("本地未保存名称")
    expect(apiRequest).toHaveBeenNthCalledWith(
      3,
      "/api/v1/modules?page=1&page_size=100",
      expect.objectContaining({ method: "GET" }),
    )

    await user.click(screen.getByRole("button", { name: "保存模块" }))
    expect(await screen.findByText("模块已保存")).toBeVisible()
    expect(apiRequest).toHaveBeenNthCalledWith(4, "/api/v1/modules/module-pov", expect.objectContaining({
      method: "PATCH",
      body: expect.objectContaining({ version: 2, name: "本地未保存名称" }),
    }))
  })

  it("冲突时就地显示错误并保留新增表单", async () => {
    const apiRequest = vi
      .fn()
      .mockResolvedValueOnce(moduleList())
      .mockResolvedValueOnce(
        ok({
          status: 409,
          data: null,
          error: { code: "module_already_exists", message: "conflict" },
        }),
      )
    renderModules(apiRequest)
    const user = userEvent.setup()
    await screen.findByText("PoV 验证")

    await user.type(screen.getByLabelText("模块标识"), "pov")
    await user.type(screen.getByLabelText("模块名称"), "重复模块")
    await user.click(screen.getByRole("button", { name: "新增模块" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("模块名称或标识已存在")
    expect(screen.getByLabelText("模块标识")).toHaveValue("pov")
    expect(screen.getByLabelText("模块名称")).toHaveValue("重复模块")
  })

  it("停用前要求输入当前密码并发送状态 PATCH", async () => {
    const inactive = { ...moduleItem, is_active: false, version: 2 }
    const apiRequest = vi
      .fn()
      .mockResolvedValueOnce(moduleList())
      .mockResolvedValueOnce(apiOk({ valid: true }))
      .mockResolvedValueOnce(apiOk(inactive))
    renderModules(apiRequest)
    const user = userEvent.setup()
    const deactivate = await screen.findByRole("button", { name: "停用 PoV 验证" })

    await user.click(deactivate)
    const dialog = await screen.findByRole("dialog", { name: "停用模块" })
    await user.type(within(dialog).getByLabelText("当前账号密码"), "AdminPass!123")
    await user.click(within(dialog).getByRole("button", { name: "停用" }))
    await waitFor(() => expect(apiRequest).toHaveBeenCalledTimes(3))
    expect(apiRequest).toHaveBeenNthCalledWith(
      2,
      "/api/v1/auth/verify-password",
      expect.objectContaining({ method: "POST", body: { password: "AdminPass!123" } }),
    )
    expect(apiRequest).toHaveBeenNthCalledWith(3, "/api/v1/modules/module-pov", expect.objectContaining({
      method: "PATCH",
      body: { is_active: false, version: 1 },
    }))
    expect(within(screen.getByRole("row", { name: /PoV 验证/ })).getByText("停用")).toBeVisible()
  })

  it("读取 101 个模块的所有分页并可管理第 101 条", async () => {
    const firstPage = Array.from({ length: 100 }, (_, index) => numberedModule(index + 1))
    const lastModule = numberedModule(101)
    const apiRequest = vi
      .fn()
      .mockResolvedValueOnce(modulePage(firstPage, 1, 100, 101))
      .mockResolvedValueOnce(modulePage([lastModule], 2, 100, 101))
    renderModules(apiRequest)
    const user = userEvent.setup()

    expect(await screen.findByText("101 个模块")).toBeVisible()
    await user.click(screen.getByRole("button", { name: "编辑 模块 101" }))

    expect(screen.getByLabelText("模块标识（只读）")).toHaveValue("module_101")
    expect(apiRequest).toHaveBeenNthCalledWith(
      2,
      "/api/v1/modules?page=2&page_size=100",
      expect.objectContaining({ method: "GET" }),
    )
  })

  it("后续分页失败时不把第一页显示为完整目录", async () => {
    const apiRequest = vi
      .fn()
      .mockResolvedValueOnce(modulePage([moduleItem], 1, 1, 2))
      .mockResolvedValueOnce(
        ok({ status: 503, data: null, error: { code: "module_list_failed", message: "failed" } }),
      )
    renderModules(apiRequest)

    expect(await screen.findByRole("alert")).toHaveTextContent("模块操作失败")
    expect(screen.queryByRole("row", { name: /PoV 验证/ })).not.toBeInTheDocument()
  })

  it("拒绝 version 为 0 的模块 DTO", async () => {
    const apiRequest = vi.fn().mockResolvedValueOnce(moduleList([{ ...moduleItem, version: 0 }]))
    renderModules(apiRequest)

    expect(await screen.findByRole("alert")).toHaveTextContent("模块操作失败")
    expect(screen.queryByRole("row", { name: /PoV 验证/ })).not.toBeInTheDocument()
  })
})
