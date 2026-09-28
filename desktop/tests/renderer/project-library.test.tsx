// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AuthProvider } from "../../src/renderer/src/auth/AuthProvider"
import { DangerConfirmProvider } from "../../src/renderer/src/common/DangerConfirmProvider"
import { ProjectLibrary } from "../../src/renderer/src/library/ProjectLibrary"
import type { DocumentSummaryDto } from "../../src/renderer/src/documents/types"
import type { ApiResponse, BridgeResult } from "../../src/shared/contracts"
import { adminUser, authResult, bridge, installBridge, ok, renderApp } from "./test-utils"

const projectId = "project-library"

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe("project library", () => {
  it("merges project files and business documents into one list", async () => {
    renderLibrary(requestWith())

    const toolbar = await screen.findByRole("toolbar", { name: "文件库工具栏" })
    expect(within(toolbar).getByRole("button", { name: "上传项目文件" })).toBeVisible()
    expect(within(toolbar).queryByRole("button", { name: "新建文档" })).not.toBeInTheDocument()
    const list = await screen.findByRole("list", { name: "文件库" })
    expect(within(list).getByText("调研附件.pdf")).toBeVisible()
    expect(within(list).getByText("SOW-1")).toBeVisible()
    expect(within(list).getByText("项目文件")).toBeVisible()
    expect(within(list).getByText("业务文档")).toBeVisible()
    expect(within(list).getAllByText("当前版本")).toHaveLength(2)
    expect(within(list).getAllByText("上传时间")).toHaveLength(2)
    expect(within(list).queryByText("状态")).not.toBeInTheDocument()
    expect(within(list).getAllByRole("listitem")).toHaveLength(2)
    expect(within(toolbar).getByLabelText("筛选文件状态")).toHaveValue("normal")
    expect(within(list).getAllByRole("button", { name: "预览" })).toHaveLength(2)
    expect(within(list).getByText("2026/8/28 10:30:00")).toBeVisible()
    expect(within(toolbar).getByLabelText("筛选文件类型").closest("label")).toHaveClass("library-filter")
    expect(within(toolbar).getByLabelText("筛选业务阶段").closest("label")).toHaveClass("library-filter")
  })

  it("filters deprecated items by default and lets managers restore them", async () => {
    const apiRequest = requestWith()
    renderLibrary(apiRequest)
    const user = userEvent.setup()

    const filter = await screen.findByLabelText("筛选文件状态")
    expect(screen.queryByText("旧版协议")).not.toBeInTheDocument()
    expect(screen.queryByText("SOW-ARCHIVED")).not.toBeInTheDocument()
    await user.selectOptions(filter, "deprecated")

    const list = await screen.findByRole("list", { name: "文件库" })
    expect(within(list).getByText("旧版协议")).toBeVisible()
    expect(within(list).getByText("SOW-ARCHIVED")).toBeVisible()
    const restoreButtons = within(list).getAllByRole("button", { name: "恢复" })
    expect(restoreButtons).toHaveLength(2)
    await user.click(restoreButtons[0])
    expect(apiRequest.mock.calls.some(([path, options]) => path === `/api/v1/projects/${projectId}/files/items/file-old/restore` && options.method === "POST")).toBe(true)
  })

  it("keeps a file visible when a deprecated latest history entry has an active fallback", async () => {
    renderLibrary(requestWith({ deprecatedLatestWithFallback: true }))

    const list = await screen.findByRole("list", { name: "文件库" })
    const card = within(list).getByText("调研附件.pdf").closest("article")
    expect(card).not.toBeNull()
    expect(within(card as HTMLElement).getByText("v1")).toBeVisible()
    expect(within(card as HTMLElement).getByRole("button", { name: "预览" })).toBeVisible()
  })

  it("keeps documents usable when the file endpoint fails", async () => {
    renderLibrary(requestWith({ failFiles: true }))

    expect(await screen.findByRole("alert")).toHaveTextContent("项目文件加载失败")
    const list = await screen.findByRole("list", { name: "文件库" })
    expect(within(list).getByText("SOW-1")).toBeVisible()
    expect(within(list).queryByText("调研附件.pdf")).not.toBeInTheDocument()
  })

  it("does not duplicate a generated document's mirrored library file", async () => {
    renderLibrary(requestWith({ documentFileId: "file-1" }))

    const list = await screen.findByRole("list", { name: "文件库" })
    expect(within(list).getAllByRole("listitem")).toHaveLength(1)
    expect(within(list).getByText("SOW-1")).toBeVisible()
    expect(within(list).queryByText("调研附件.pdf")).not.toBeInTheDocument()
  })

  it("shows a loading card as soon as a research export is queued", async () => {
    renderLibrary(requestWith({ generating: true }))

    const list = await screen.findByRole("list", { name: "文件库" })
    const card = within(list).getByText("销售员调研结果").closest("article")
    expect(card).not.toBeNull()
    expect(within(card as HTMLElement).getByRole("status")).toHaveTextContent("正在后台生成")
    expect(within(card as HTMLElement).queryByRole("button", { name: "下载" })).not.toBeInTheDocument()
  })

  it("opens file version history as a second-level page with per-version actions", async () => {
    renderLibrary(requestWith())
    const user = userEvent.setup()

    const list = await screen.findByRole("list", { name: "文件库" })
    const fileCard = within(list).getByText("调研附件.pdf").closest("article")
    expect(fileCard).not.toBeNull()
    await user.click(within(fileCard as HTMLElement).getByRole("button", { name: "版本" }))

    expect(await screen.findByRole("heading", { name: "版本历史：调研附件.pdf" })).toBeVisible()
    expect(screen.queryByRole("dialog", { name: "版本历史：调研附件.pdf" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "预览" })).toBeVisible()
    expect(screen.getByRole("button", { name: "下载" })).toBeVisible()
    await user.click(screen.getByRole("button", { name: "返回文件库" }))
    expect(await screen.findByRole("list", { name: "文件库" })).toBeVisible()
  })

  it("uploads a new version from the version history page into the same file", async () => {
    const apiRequest = requestWith()
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 200, headers: { ETag: '"new-etag"' } })))
    renderLibrary(apiRequest)
    const user = userEvent.setup()
    const list = await screen.findByRole("list", { name: "文件库" })
    const card = within(list).getByText("调研附件.pdf").closest("article")
    await user.click(within(card as HTMLElement).getByRole("button", { name: "版本" }))

    expect(await screen.findByRole("button", { name: "上传新版本" })).toBeVisible()
    fireEvent.change(screen.getByLabelText("选择新版本文件"), {
      target: { files: [new File(["next"], "调研附件-v2.pdf", { type: "application/pdf" })] },
    })

    await waitFor(() => expect(apiRequest.mock.calls).toContainEqual([
      `/api/v1/projects/${projectId}/files`,
      expect.objectContaining({ method: "POST", body: expect.objectContaining({ file_id: "file-1", display_name: "调研附件.pdf" }) }),
    ]))
    await waitFor(() => expect(apiRequest.mock.calls.some(([path, options]) => path === `/api/v1/projects/${projectId}/files/session-version/complete` && options.method === "POST")).toBe(true))
  })

  it("renames a generated document from the icon beside its title", async () => {
    const apiRequest = requestWith()
    renderLibrary(apiRequest)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "重命名：SOW-1" }))
    const dialog = screen.getByRole("dialog", { name: "修改文档名称" })
    const input = within(dialog).getByLabelText("文档名称")
    await user.clear(input)
    await user.type(input, "SOW-销售订单智能预测")
    await user.click(within(dialog).getByRole("button", { name: "保存" }))

    expect(apiRequest.mock.calls.some(([path, options]) =>
      path === `/api/v1/projects/${projectId}/documents/document-1`
      && options.method === "PATCH"
      && options.body?.name === "SOW-销售订单智能预测"
      && options.body?.version === 1
    )).toBe(true)
  })
})

describe("SOW-only project library", () => {
  it("reuses library cards and strictly filters by document type without requesting attachments", async () => {
    const apiRequest = sowRequest()
    renderLibrary(apiRequest, { documentType: "sow" })

    expect(await screen.findByRole("heading", { name: "SOW 文件" })).toBeVisible()
    const list = await screen.findByRole("list", { name: "SOW 文件" })
    expect(within(list).getAllByRole("listitem")).toHaveLength(1)
    expect(within(list).getByText("SOW-1").closest("article")).toHaveClass("library-file-card")
    expect(within(list).queryByText("SOW-名字相似的PoV")).not.toBeInTheDocument()
    expect(within(list).queryByText("调研附件.pdf")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "上传项目文件" })).not.toBeInTheDocument()
    expect(screen.queryByLabelText("筛选文件类型")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "生成" })).not.toBeInTheDocument()
    expect(screen.getByLabelText("筛选文件状态")).toHaveValue("normal")
    expect(apiRequest.mock.calls.some(([path]) => String(path).includes("/files"))).toBe(false)
  })

  it("keeps business-stage filters and restores archived SOW through the shared document action", async () => {
    const apiRequest = sowRequest()
    renderLibrary(apiRequest, { documentType: "sow" })
    const user = userEvent.setup()

    await user.selectOptions(await screen.findByLabelText("筛选业务阶段"), "生产部署")
    await waitFor(() => expect(apiRequest.mock.calls.some(([path]) => path === `/api/v1/projects/${projectId}/documents?business_category=${encodeURIComponent("生产部署")}`)).toBe(true))
    await user.selectOptions(screen.getByLabelText("筛选文件状态"), "deprecated")
    const list = await screen.findByRole("list", { name: "SOW 文件" })
    expect(within(list).getByText("SOW-ARCHIVED")).toBeVisible()
    expect(within(list).queryByText("SOW-1")).not.toBeInTheDocument()
    await user.click(within(list).getByRole("button", { name: "恢复" }))
    expect(apiRequest.mock.calls).toContainEqual([
      `/api/v1/projects/${projectId}/documents/items/document-old/restore`,
      expect.objectContaining({ method: "POST", body: { version: 2 } }),
    ])
  })

  it("downloads the existing SOW version and opens its history as a library page", async () => {
    const apiRequest = sowRequest()
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {})
    renderLibrary(apiRequest, { documentType: "sow" })
    const user = userEvent.setup()

    const list = await screen.findByRole("list", { name: "SOW 文件" })
    expect(within(list).getByRole("button", { name: "预览" })).toBeVisible()
    await user.click(within(list).getByRole("button", { name: "下载" }))
    expect(apiRequest.mock.calls).toContainEqual([
      `/api/v1/projects/${projectId}/documents/document-version-1/download-url`,
      expect.objectContaining({ method: "GET" }),
    ])
    expect(click).toHaveBeenCalledOnce()
    await user.click(within(list).getByRole("button", { name: "版本" }))
    expect(await screen.findByRole("heading", { name: "版本历史：SOW-1" })).toBeVisible()
    expect(screen.queryByRole("dialog", { name: "版本历史：SOW-1" })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "返回文件库" }))
    expect(await screen.findByRole("list", { name: "SOW 文件" })).toBeVisible()
  })

  it("keeps unfinished SOW exports visible and polls their existing job without generating again", async () => {
    const apiRequest = sowRequest({ pendingReads: 1 })
    renderLibrary(apiRequest, { documentType: "sow" })

    const list = await screen.findByRole("list", { name: "SOW 文件" })
    expect(within(list).getByRole("status")).toHaveTextContent("正在后台生成")
    expect(within(list).queryByRole("button", { name: "下载" })).not.toBeInTheDocument()
    await waitFor(() => expect(within(list).getByRole("button", { name: "下载" })).toBeVisible(), { timeout: 3000 })
    expect(apiRequest.mock.calls.every(([, options]) => options.method === "GET")).toBe(true)
    expect(apiRequest.mock.calls.some(([path]) => String(path).includes("/files"))).toBe(false)
  })

  it("reports SOW load failures without claiming another library category is available", async () => {
    renderLibrary(sowRequest({ failDocuments: true }), { documentType: "sow" })

    expect(await screen.findByRole("alert")).toHaveTextContent("SOW 文件加载失败，请稍后重试。")
    expect(screen.queryByText(/另一类内容仍可继续使用/)).not.toBeInTheDocument()
    expect(screen.queryByRole("list", { name: "SOW 文件" })).not.toBeInTheDocument()
  })

  it("keeps read-only access to previews and downloads without mutation controls", async () => {
    renderLibrary(sowRequest(), { documentType: "sow", canManage: false })

    const list = await screen.findByRole("list", { name: "SOW 文件" })
    expect(within(list).getByRole("button", { name: "预览" })).toBeVisible()
    expect(within(list).getByRole("button", { name: "下载" })).toBeVisible()
    expect(within(list).queryByRole("button", { name: "标记为弃用" })).not.toBeInTheDocument()
    expect(within(list).queryByRole("button", { name: /重命名/ })).not.toBeInTheDocument()
  })
})

function renderLibrary(apiRequest: ReturnType<typeof vi.fn>, { documentType, canManage = true }: { documentType?: "sow"; canManage?: boolean } = {}) {
  installBridge(bridge({
    refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
    apiRequest,
  }))
  renderApp(<AuthProvider><DangerConfirmProvider><ProjectLibrary projectId={projectId} canManage={canManage} documentType={documentType} /></DangerConfirmProvider></AuthProvider>)
}

function sowRequest({ failDocuments = false, pendingReads = 0 }: { failDocuments?: boolean; pendingReads?: number } = {}) {
  const base = requestWith({ documentFileId: "file-1" })
  let reads = 0
  return vi.fn(async (path: string, options: { method: string; body?: Record<string, unknown> }) => {
    if (path.endsWith("/download-url")) return apiOk({ url: "https://storage.test/sow.docx", expires_seconds: 300 })
    if (path.endsWith("/versions")) return apiOk({ items: [] })
    const response = await base(path, options)
    if ((path === `/api/v1/projects/${projectId}/documents` || path.startsWith(`/api/v1/projects/${projectId}/documents?`)) && options.method === "GET") {
      if (failDocuments) return apiError("network_error", 503)
      if (!response.ok || !response.data.data) throw new Error("missing fixture")
      const data = response.data.data as { items: DocumentSummaryDto[] }
      const sow = data.items[0]
      const items = [
        reads++ < pendingReads ? { ...sow, current_version_id: null, current_version: null, generation_status: "queued" } : sow,
        ...data.items.slice(1),
        { ...sow, id: "pov-1", business_code: "SOW-名字相似的PoV", document_type: "pov_plan" },
      ]
      return apiOk({ items })
    }
    return response
  })
}

function requestWith({ failFiles = false, generating = false, deprecatedLatestWithFallback = false, documentFileId }: { failFiles?: boolean; generating?: boolean; deprecatedLatestWithFallback?: boolean; documentFileId?: string } = {}) {
  return vi.fn((path: string, options: { method: string; body?: Record<string, unknown> }) => {
    if (path === `/api/v1/projects/${projectId}/files/items/file-1/versions` && options.method === "GET") {
      return Promise.resolve(apiOk({ items: [{ id: "file-version-1", version_number: 1, status: "available", scan_status: "clean", preview_status: "ready", original_filename: "调研附件.pdf", uploaded_by: "管理员", uploaded_at: "2026-08-28T10:30:00+08:00" }] }))
    }
    if (path === `/api/v1/projects/${projectId}/files` && options.method === "POST") {
      return Promise.resolve(apiOk({ id: "session-version", project_id: projectId, name: options.body?.name, category: "attachment", size_bytes: options.body?.size_bytes, mime_type: options.body?.mime_type, part_size: 5242880, upload_id: "upload-version", expires_at: "2026-08-31T22:00:00+08:00", idempotency_key: options.body?.idempotency_key }))
    }
    if (path === `/api/v1/projects/${projectId}/files/session-version/parts` && options.method === "POST") {
      return Promise.resolve(apiOk({ url: "https://storage.test/version-part", part_number: 1, expires_seconds: 300 }))
    }
    if (path === `/api/v1/projects/${projectId}/files/session-version/complete` && options.method === "POST") {
      return Promise.resolve(apiOk({ version_id: "file-version-2", file_id: "file-1", status: "available", scan_status: "clean" }))
    }
    if (path.startsWith(`/api/v1/projects/${projectId}/files`) && options.method === "GET") {
      if (failFiles) return Promise.resolve(apiError("network_error", 503))
      return Promise.resolve(apiOk({ items: [{
        id: "file-1", project_id: projectId, display_name: "调研附件.pdf", category: "attachment",
        business_category: "调研", status: "active", current_version_id: "file-version-1",
        current_version: { id: "file-version-1", version_number: 1, status: "available", scan_status: "clean", preview_status: "ready", uploaded_at: "2026-08-28T10:30:00+08:00" },
        latest_version: deprecatedLatestWithFallback
          ? { id: "file-version-2", version_number: 2, status: "deprecated", scan_status: "clean", preview_status: "ready", uploaded_at: "2026-08-29T10:30:00+08:00" }
          : { id: "file-version-1", version_number: 1, status: "available", scan_status: "clean", preview_status: "ready", uploaded_at: "2026-08-28T10:30:00+08:00" },
        created_by: "管理员",
      }, {
        id: "file-old", project_id: projectId, display_name: "旧版协议", category: "attachment",
        business_category: "商务合约", status: "active", current_version_id: null, current_version: null,
        latest_version: { id: "file-version-old", version_number: 1, status: "deprecated", scan_status: "clean", preview_status: "ready", uploaded_at: "2026-08-20T10:00:00+08:00" },
        created_by: "管理员",
      }, ...(generating ? [{
        id: "file-generating", project_id: projectId, display_name: "销售员调研结果", category: "document",
        business_category: "调研", status: "active", current_version_id: null, current_version: null,
        latest_version: null, created_by: "管理员", generation_status: "queued", generation_message: "",
        generation_export_id: "export-1", generation_form_id: "form-1", generation_updated_at: "2026-08-28T10:40:00+08:00",
      }] : [])] }))
    }
    if (path.startsWith(`/api/v1/projects/${projectId}/documents`) && options.method === "GET") {
      return Promise.resolve(apiOk({ items: [{
        id: "document-1", project_id: projectId, document_type: "sow", business_code: "SOW-1",
        library_file_id: documentFileId,
        business_category: "生产部署", status: "confirmed", version: 1,
        current_version_id: "document-version-1", current_version: { id: "document-version-1", version_number: 1, source: "generated", status: "confirmed", preview_status: "ready", created_at: "2026-08-28T09:00:00+08:00" },
        created_at: "2026-08-26T10:00:00+08:00",
      }, {
        id: "document-old", project_id: projectId, document_type: "sow", business_code: "SOW-ARCHIVED",
        business_category: "生产部署", status: "archived", version: 2,
        current_version_id: "document-version-old", current_version: { id: "document-version-old", version_number: 1, source: "generated", status: "archived", preview_status: "ready", created_at: "2026-08-19T09:00:00+08:00" },
        created_at: "2026-08-19T09:00:00+08:00",
      }] }))
    }
    if (path === `/api/v1/projects/${projectId}/documents/document-1` && options.method === "PATCH") {
      return Promise.resolve(apiOk({ id: "document-1", business_code: options.body?.name, version: 2 }))
    }
    if (path.endsWith("/restore") && options.method === "POST") return Promise.resolve(apiOk({ status: "available" }))
    return Promise.resolve(apiError("unexpected_request", 500))
  })
}

function apiOk<T>(data: T): BridgeResult<ApiResponse<T>> {
  return ok({ status: 200, data, error: null })
}

function apiError(code: string, status: number): BridgeResult<ApiResponse<never>> {
  return ok({ status, data: null, error: { code, message: code } })
}
