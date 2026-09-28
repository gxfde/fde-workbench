// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

import { App } from "../../src/renderer/src/App"
import type { ApiResponse, BridgeResult } from "../../src/shared/contracts"
import { adminUser, authResult, bridge, installBridge, ok, renderApp } from "./test-utils"

function apiOk<T>(data: T, status = 200): BridgeResult<ApiResponse<T>> {
  return ok({ status, data, error: null })
}

beforeEach(() => { location.hash = "#extensions" })
afterEach(() => { cleanup(); vi.restoreAllMocks(); location.hash = "" })

it("shows extension boundaries and saves a personal Skill", async () => {
  let skills: unknown[] = []
  const center = () => ({
    skills,
    tools: [],
    plugins: [],
    models: [],
    providers: [],
    permissions: { can_manage_personal_skills: true, can_manage_system: false },
    marketplace: { connected: false, status: "not_connected" },
    credential_storage: "external_secret_reference",
  })
  const apiRequest = vi.fn((path: string, options: { method: string; body?: Record<string, unknown> }) => {
    if (path === "/api/v1/extensions" && options.method === "GET") return Promise.resolve(apiOk(center()))
    if (path === "/api/v1/extensions/skills/personal" && options.method === "POST") {
      skills = [{ id: "skill-1", scope: "personal", key: options.body?.key, name: options.body?.name, description: options.body?.description, status: "active", current_version: 1, can_edit: true }]
      return Promise.resolve(apiOk(skills[0], 201))
    }
    throw new Error(`Unexpected request: ${options.method} ${path}`)
  })
  installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
  renderApp(<App />)

  expect(await screen.findByRole("heading", { name: "AI 与扩展" })).toBeVisible()
  expect(screen.queryByRole("heading", { name: "AI Server 插件市场" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "刷新" })).not.toBeInTheDocument()
  expect(await screen.findByRole("tab", { name: "模型管理" })).toBeVisible()

  const user = userEvent.setup()
  await user.click(screen.getByRole("button", { name: "新建个人 Skill" }))
  await user.type(screen.getByLabelText("Skill 标识"), "meeting-summary")
  await user.type(screen.getByLabelText("Skill 名称"), "会议纪要整理")
  await user.type(screen.getByLabelText("SKILL.md 指令"), "# 整理会议")
  await user.click(screen.getByRole("button", { name: "保存 Skill" }))

  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith(
    "/api/v1/extensions/skills/personal",
    expect.objectContaining({ method: "POST", body: expect.objectContaining({ key: "meeting-summary" }) }),
  ))
  expect(await screen.findByText("会议纪要整理")).toBeVisible()
})

it("lets a system operator approve a pending plugin change", async () => {
  let pending = true
  const center = () => ({
    skills: [],
    tools: [],
    plugins: [{ id: "plugin-1", key: "official.audit", name: "审计插件", description: "", publisher: "FDE", version: "2.0.0", verified: true, installation_status: "not_installed", installed_version: "", rollback_versions: [] }],
    plugin_requests: [{ id: "request-1", plugin: { id: "plugin-1", key: "official.audit", name: "审计插件" }, target_user: { id: "user-1", name: "项目成员" }, action: "install", from_version: "", target_version: "2.0.0", status: pending ? "pending" : "executed", request_reason: "项目使用", decision_reason: "" }],
    models: [], providers: [],
    permissions: { can_manage_personal_skills: true, can_manage_system: true },
    marketplace: { connected: false, enabled: false, status: "disabled" },
    credential_storage: "external_secret_reference",
  })
  const apiRequest = vi.fn((path: string, options: { method: string }) => {
    if (path === "/api/v1/extensions" && options.method === "GET") return Promise.resolve(apiOk(center()))
    if (path === "/api/v1/extensions/plugin-requests/request-1/decision" && options.method === "POST") {
      pending = false
      return Promise.resolve(apiOk(center().plugin_requests[0]))
    }
    throw new Error(`Unexpected request: ${options.method} ${path}`)
  })
  installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
  renderApp(<App />)

  const user = userEvent.setup()
  await user.click(await screen.findByRole("tab", { name: "工具 / 插件" }))
  expect(await screen.findByRole("heading", { name: "插件变更审批" })).toBeVisible()
  await user.click(screen.getByRole("button", { name: "批准并执行" }))
  expect(await screen.findByText("插件变更已由 AI Server 执行。")).toBeVisible()
  expect(screen.getByText("已执行")).toBeVisible()
})

it("shows callable tools and registered plugins without the market", async () => {
  const center = { skills: [], tools: [{key: "lcsc_search", description: "只读立创商城浏览器搜索", capability: null}], plugins: [{id: "p1", name: "项目工具", description: "检索项目", publisher: "开发者", installed_version: "1.0.0"}], models: [], providers: [], permissions: { can_manage_personal_skills: true, can_manage_system: true }, marketplace: { connected: true, plugin_count: 100, status: "ready" } }
  const plugin = { id: "p1", name: "项目工具", description: "检索项目", publisher: "开发者", category: "工具", stars: 8 }
  const apiRequest = vi.fn((path: string) => {
    if (path === "/api/v1/extensions") return Promise.resolve(apiOk(center))
    if (path === "/api/v1/extensions/plugins/p1") return Promise.resolve(apiOk({ ...plugin, capabilities: ["project.read"], install_available: true, installation_status: "not_installed" }))
    throw new Error(path)
  })
  installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
  renderApp(<App />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole("tab", { name: "工具 / 插件" }))
  expect(await screen.findByText("立创商城元器件查询 · 默认模型版")).toBeVisible()
  expect(screen.getByText("立创商城元器件查询 · Jev 版")).toBeVisible()
  expect(screen.getAllByRole("link", { name: "立即使用" })).toHaveLength(3)
  expect(screen.queryByRole("button", { name: "浏览插件目录" })).not.toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "项目工具" }))
  expect(await screen.findByRole("dialog", { name: "项目工具" })).toBeVisible()
  expect(screen.getByText("查看项目资料")).toBeVisible()
  expect(screen.getByRole("button", { name: "安装插件" })).toBeVisible()
})

it("opens each tool detail and keeps formatted results and logs inside the tool", async () => {
  const runs: Array<Record<string, unknown>> = []
  const center = { skills: [], tools: [{ key: "lcsc_search", description: "只读立创商城浏览器搜索", capability: null }], plugins: [], models: [], providers: [], permissions: { can_manage_personal_skills: true, can_manage_system: false } }
  const apiRequest = vi.fn((path: string, options: { method: string; body?: { skill_key: string; query: string } }) => {
    if (path === "/api/v1/extensions") return Promise.resolve(apiOk(center))
    if (path === "/api/v1/ai/lcsc-runs" && options.method === "GET") return Promise.resolve(apiOk({ items: runs }))
    if (path === "/api/v1/ai/lcsc-runs/desktop-execute" && options.method === "POST") {
      const run = { id: `run-${runs.length + 1}`, skill_key: options.body?.skill_key, query: options.body?.query,
        status: "succeeded", error_code: "", browser_url: "https://so.szlcsc.com/global.html?k=C8734", duration_ms: 1350,
        started_at: "2026-09-22T09:00:00Z", steps: [{ at_ms: 1, action: "navigate", detail: "打开立创商城" }],
        candidates: [{ title: "C8734", url: "https://item.szlcsc.com/9243.html", visible_text: "库存 100" }],
        models: options.body?.skill_key === "lcsc-browser-jev" ? [{ provider: "TypeSafe", model: "jev-1.13.0" }] : [],
        usage: {}, cost: { cny_estimate: "0" }, result: { fields: ["parameters", "other"], selected_product: { title: "C8734", url: "https://item.szlcsc.com/9243.html", visible_text: "库存 100" }, details: {other: {purpose:'查看包装数量',complete:false,reason:'仍有信息未确认',items:[{goal:'包装数量',answer:'3000 个 / 圆盘',status:'verified'},{goal:'包装适用范围',answer:'尚未确认',status:'unresolved',reason:'公开页面未展示适用范围'}]}} } }
      runs.unshift(run)
      return Promise.resolve(apiOk(run))
    }
    throw new Error(`Unexpected request: ${options.method} ${path}`)
  })
  installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
  renderApp(<App />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole("tab", { name: "工具 / 插件" }))
  expect(screen.queryByRole("heading", { name: "执行记录" })).not.toBeInTheDocument()
  for (const [name, key] of [["默认模型版", "lcsc-browser-baseline"], ["Jev 版", "lcsc-browser-jev"]]) {
    const card = screen.getByText(`立创商城元器件查询 · ${name}`).closest("article")!
    await user.click(within(card).getByRole("link", { name: "立即使用" }))
    await user.type(await screen.findByLabelText("搜索内容"), "C8734")
    await user.click(screen.getByRole('button', { name: '全选', exact: true }))
    for (const label of ['元器件参数', '引脚数', '售价', '下载规格书']) expect(screen.getByLabelText(label)).toBeChecked()
    expect(screen.getByLabelText('其他')).not.toBeChecked()
    expect(screen.queryByRole('heading', { name: '默认模型与 Jev 的实测对比' })).not.toBeInTheDocument()
    await user.click(screen.getByLabelText('其他'))
    await user.type(screen.getByLabelText('其他查询目的'), '查看包装数量')
    await user.click(screen.getByRole('button', { name: '取消选择', exact: true }))
    for (const label of ['元器件参数', '引脚数', '售价', '下载规格书']) expect(screen.getByLabelText(label)).not.toBeChecked()
    expect(screen.getByLabelText('其他')).toBeChecked()
    expect(screen.getByLabelText('其他查询目的')).toHaveValue('查看包装数量')
    await user.click(screen.getByRole('button', { name: '全选', exact: true }))
    expect(screen.getByLabelText('其他')).toBeChecked()
    await user.click(screen.getByRole("button", { name: "执行查询" }))
    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("/api/v1/ai/lcsc-runs/desktop-execute", expect.objectContaining({ method: "POST", body: { skill_key: key, query: "C8734", fields: ["parameters", "pins", "price", "datasheet", "other"], track: true, purpose: '查看包装数量' } })))
    expect(await screen.findByText("3000 个 / 圆盘")).not.toBeVisible()
    expect(screen.getByText("执行指令：元器件参数 · 其他（查看包装数量）")).toBeVisible()
    expect(screen.getByText(`run-${runs.length}`)).toBeVisible()
    const copy=vi.fn().mockResolvedValue(undefined)
    window.fde.app.copyLcscRunId=copy
    expect(screen.queryByRole('button',{name:'复制 ID',exact:true})).not.toBeInTheDocument()
    await user.click(screen.getByRole('button',{name:`复制执行记录 ID run-${runs.length}`}))
    expect(copy).toHaveBeenCalledWith(`run-${runs.length}`)
    expect(screen.getByRole('button', { name: '展开记录' })).toHaveAttribute('aria-expanded', 'false')
    await user.click(screen.getByRole('button', { name: '展开记录' }))
    expect(screen.getByText('3000 个 / 圆盘')).toBeVisible()
    expect(screen.getByText(/其他查询结果 · 尚未全部达到目的/)).toBeVisible()
    expect(screen.getByText(/公开页面未展示适用范围/)).toBeVisible()
    await user.click(screen.getByRole('button', { name: '收起记录' }))
    expect(screen.getByText('3000 个 / 圆盘')).not.toBeVisible()
    await user.click(screen.getByRole('button', { name: '展开记录' }))
    await user.click(screen.getByRole("button", { name: "查看操作日志" }))
    expect(await screen.findByRole("dialog", { name: "操作日志" })).toBeVisible()
    expect(screen.getByText("1. 打开立创商城")).toBeVisible()
    await user.click(screen.getByRole("button", { name: "关闭" }))
    const back = screen.getByRole("link", { name: "返回工具 / 插件" })
    expect(back).toHaveClass('secondary-button', 'button-link', 'compact')
    expect(back.parentElement).toHaveClass('page-header')
    await user.click(back)
    expect(await screen.findAllByRole("link", { name: "立即使用" })).toHaveLength(3)
  }
})

it("keeps Jev credentials from being saved as a chat default or tool-capable model", async () => {
  const center = { skills: [], tools: [], plugins: [], models: [], providers: [], model_preferences: [], model_credentials_ready: true, permissions: { can_manage_personal_skills: true, can_manage_system: false } }
  const apiRequest = vi.fn((path: string, options: { method: string; body?: Record<string, unknown> }) => {
    if (path === "/api/v1/extensions") return Promise.resolve(apiOk(center))
    if (path === "/api/v1/extensions/model-preferences" && options.method === "POST") return Promise.resolve(apiOk({ id: "jev-credential" }))
    throw new Error(path)
  })
  installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
  renderApp(<App />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole("tab", { name: "模型管理" }))
  await user.click(screen.getByRole("button", { name: "添加 Jev 凭据" }))
  expect(screen.getByRole("dialog", { name: "添加 Jev 凭据" })).toBeVisible()
  expect(screen.getByRole("checkbox", { name: "设为该范围的默认模型" })).toBeDisabled()
  expect(screen.getByRole("checkbox", { name: "支持工具调用" })).toBeDisabled()
  await user.clear(screen.getByLabelText("模型名称"))
  await user.type(screen.getByLabelText("模型名称"), "Jev")
  await user.type(screen.getByLabelText("API Key"), "test-key")
  await user.click(screen.getByRole("button", { name: "保存模型" }))
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("/api/v1/extensions/model-preferences", expect.objectContaining({ method: "POST", body: expect.objectContaining({ name: "Jev", provider: "typesafe", model: "jev-1.13.0", is_default: false, supports_tools: false }) })))
})

it("keeps API Key inside the model tab and saves a personal model", async () => {
  const center = { skills: [], tools: [], plugins: [], models: [], providers: [], model_preferences: [], model_credentials_ready: true, permissions: { can_manage_personal_skills: true, can_manage_system: false }, marketplace: { connected: false, status: "disabled" } }
  const apiRequest = vi.fn((path: string) => {
    if (path === "/api/v1/extensions") return Promise.resolve(apiOk(center))
    if (path === "/api/v1/extensions/model-preferences") return Promise.resolve(apiOk({ id: "personal-1" }))
    throw new Error(path)
  })
  installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
  renderApp(<App />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole("tab", { name: "模型管理" }))
  expect(screen.queryByRole("heading", { name: "AI Server 插件市场" })).not.toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "添加模型" }))
  await user.type(screen.getByLabelText("模型名称"), "自己的模型")
  await user.type(screen.getByLabelText("API Key"), "sk-private")
  expect(screen.getByLabelText("API Key")).toHaveAttribute("type", "password")
  await user.click(screen.getByRole("button", { name: "保存模型" }))
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("/api/v1/extensions/model-preferences", expect.objectContaining({ method: "POST", body: expect.objectContaining({ scope: "personal", api_key: "sk-private" }) })))
  expect(await screen.findByText("模型已保存，API Key 在服务端加密存储，不会回显。")).toBeVisible()
  expect(screen.queryByLabelText("API Key")).not.toBeInTheDocument()
})
