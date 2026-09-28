// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AuthProvider, useAuth } from "../../src/renderer/src/auth/AuthProvider"
import { DangerConfirmProvider } from "../../src/renderer/src/common/DangerConfirmProvider"
import { ProjectDocuments } from "../../src/renderer/src/documents/ProjectDocuments"
import type { DocumentSummaryDto } from "../../src/renderer/src/documents/types"
import type { ApiResponse, BridgeResult, UserDto } from "../../src/shared/contracts"
import type { ProjectDto } from "../../src/renderer/src/workbench/types"
import { adminUser, authResult, bridge, engineerUser, installBridge, ok, renderApp } from "./test-utils"

const projectId = "project-xinghe"
const projectDetailPath = `/api/v1/projects/${projectId}`
const documentsPath = `/api/v1/projects/${projectId}/documents`
const documentTemplatesPath = "/api/v1/document-templates"

const project: ProjectDto = {
  id: projectId,
  project_code: "XH-001",
  name: "星河 AI 落地项目",
  enterprise_name: "星河制造",
  contact_name: "陈总",
  contact_phone: "13800000000",
  address: "深圳市",
  background: "设备知识库建设",
  notes: "每周演示",
  status: "active",
  planned_start_date: "2026-08-21",
  planned_end_date: "2026-09-30",
  leader_user_id: "leader-wang",
  leader: { id: "leader-wang", display_name: "王工", role: "project_lead" },
  template_version_id: "template-v1",
  industry: "制造业",
  completion: 20,
  version: 5,
  created_at: "2026-08-21T09:00:00+08:00",
  updated_at: "2026-08-21T09:00:00+08:00",
  modules: [],
  tasks: [],
  members: [],
  template_snapshot: {
    template_id: "template-1",
    template_name: "制造业模板",
    industry_name: "制造业",
    description: "",
    version_id: "template-v1",
    version_number: 1,
    modules: [],
  },
}

const confirmedSow: DocumentSummaryDto = {
  id: "doc-sow",
  project_id: projectId,
  document_type: "sow",
  business_code: "SOW-1",
  status: "confirmed",
  version: 3,
  current_version_id: "ver-sow-3",
  current_version: { id: "ver-sow-3", version_number: 3, source: "generated", status: "confirmed", preview_status: "ready" },
  created_at: "2026-08-22T09:00:00+08:00",
}

const draftContract: DocumentSummaryDto = {
  id: "doc-contract",
  project_id: projectId,
  document_type: "contract",
  business_code: "CONTRACT-1",
  status: "draft",
  version: 1,
  current_version_id: "ver-contract-1",
  current_version: { id: "ver-contract-1", version_number: 1, source: "generated", status: "draft", preview_status: "pending" },
  created_at: "2026-08-23T09:00:00+08:00",
}

const availableSow: DocumentSummaryDto = {
  id: "doc-sow-avail",
  project_id: projectId,
  document_type: "sow",
  business_code: "SOW-2",
  status: "confirmed",
  version: 2,
  current_version_id: "ver-avail",
  current_version: { id: "ver-avail", version_number: 2, source: "generated", status: "confirmed", preview_status: "ready" },
  created_at: "2026-08-22T09:00:00+08:00",
}

const awaitingContract: DocumentSummaryDto = {
  id: "doc-contract-await",
  project_id: projectId,
  document_type: "contract",
  business_code: "CONTRACT-2",
  status: "draft",
  version: 1,
  current_version_id: "ver-await",
  current_version: { id: "ver-await", version_number: 1, source: "generated", status: "draft", preview_status: "pending" },
  created_at: "2026-08-23T09:00:00+08:00",
}

afterEach(() => {
  cleanup()
  location.hash = ""
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("project documents workspace", () => {
  it("places create and business-stage controls together in a left toolbar", async () => {
    const apiRequest = baseRequest({ documents: { list: () => [confirmedSow] } })
    renderDocumentsTab(apiRequest, { role: "admin" })

    const toolbar = await screen.findByRole("toolbar", { name: "文档工具栏" })
    expect(within(toolbar).getByRole("button", { name: "新建文档" })).toBeVisible()
    expect(within(toolbar).getByLabelText("筛选业务阶段")).toBeVisible()
  })

  it("keeps create on the left and pushes the business-stage filter right", async () => {
    const apiRequest = baseRequest({ documents: { list: () => [confirmedSow] } })
    renderDocumentsTab(apiRequest, { role: "admin" })

    const toolbar = await screen.findByRole("toolbar", { name: "文档工具栏" })
    expect(within(toolbar).getByRole("button", { name: "新建文档" })).toBeVisible()
    const filter = within(toolbar).getByLabelText("筛选业务阶段").closest("label")
    expect(filter).not.toBeNull()
    expect(getComputedStyle(filter as HTMLElement).marginLeft).toBe("auto")
  })

  it("leaves the operation cell blank when a document has no available action", async () => {
    const unavailable: DocumentSummaryDto = {
      ...confirmedSow,
      id: "doc-unavailable",
      business_code: "SOW-EMPTY",
      current_version_id: null,
      current_version: null,
    }
    const apiRequest = baseRequest({ documents: { list: () => [unavailable] } })
    renderDocumentsTab(apiRequest, { role: "viewer" })

    const row = (await screen.findByText("SOW-EMPTY")).closest("tr")
    expect(row?.querySelector("td:last-child")).toBeEmptyDOMElement()
  })

  it("renders document list with status chips", async () => {
    const apiRequest = baseRequest({ documents: { list: () => [confirmedSow, draftContract] } })
    renderDocumentsTab(apiRequest, { role: "admin" })

    const table = await screen.findByRole("table", { name: "项目文档" })
    expect(table).toBeVisible()
    expect(within(table).getByText("SOW-1")).toBeVisible()
    expect(within(table).getByText("CONTRACT-1")).toBeVisible()
    expect(within(table).getByText("已确认")).toBeVisible()
    expect(within(table).getByText("草稿")).toBeVisible()
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })

  it("generates a document and creates version 2 via online revise", async () => {
    const createdNoVersion: DocumentSummaryDto = {
      id: "doc-1",
      project_id: projectId,
      document_type: "sow",
      business_code: "SOW-1",
      status: "draft",
      version: 1,
      current_version_id: null,
      current_version: null,
      created_at: "2026-08-24T09:00:00+08:00",
    }
    const createdV1: DocumentSummaryDto = {
      ...createdNoVersion,
      version: 2,
      current_version_id: "ver-1",
      current_version: { id: "ver-1", version_number: 1, source: "generated", status: "draft", preview_status: "pending" },
    }
    const createdV2: DocumentSummaryDto = {
      ...createdNoVersion,
      version: 3,
      current_version_id: "ver-2",
      current_version: { id: "ver-2", version_number: 2, source: "online_revised", status: "draft", preview_status: "pending" },
    }
    let listReads = 0
    const apiRequest = baseRequest({
      documents: {
        list: () => {
          listReads += 1
          if (listReads === 1) return []
          if (listReads === 2) return [createdNoVersion]
          if (listReads === 3) return [createdV1]
          return [createdV2]
        },
        create: () => ({ ...createdNoVersion }),
        generate: () => ({ ...createdV1 }),
        revise: () => ({ ...createdV2 }),
      },
    })
    const user = userEvent.setup()
    renderDocumentsTab(apiRequest, { role: "admin" })

    await screen.findByText("暂无项目文档。")

    await user.click(screen.getByRole("button", { name: "新建文档" }))
    await user.click(await screen.findByRole("button", { name: "创建" }))

    expect(await screen.findByText("SOW-1")).toBeVisible()

    await user.click(screen.getByRole("button", { name: "生成：SOW-1" }))
    expect(await screen.findByText("版本 1 · 系统生成")).toBeVisible()

    await user.click(screen.getByRole("button", { name: "在线修订：SOW-1" }))
    expect(await screen.findByText("版本 2 · 在线修订")).toBeVisible()

    expect(apiRequest.mock.calls).toContainEqual([
      documentsPath,
      expect.objectContaining({
        method: "POST",
        body: expect.objectContaining({ document_type: "sow", template_version_id: expect.any(String), expected_version: 5 }),
      }),
    ])
    expect(apiRequest.mock.calls).toContainEqual([
      `${documentsPath}/doc-1/generate`,
      expect.objectContaining({ method: "POST", body: { version: 1 } }),
    ])
    expect(apiRequest.mock.calls).toContainEqual([
      `${documentsPath}/doc-1/revise`,
      expect.objectContaining({ method: "POST", body: { version: 2, draft_changes: {} } }),
    ])
  })

  it("does not show download for a non-available version", async () => {
    const apiRequest = baseRequest({ documents: { list: () => [awaitingContract, availableSow] } })
    renderDocumentsTab(apiRequest, { role: "viewer" })

    expect(await screen.findByRole("table", { name: "项目文档" })).toBeVisible()
    expect(screen.queryByRole("button", { name: "下载：CONTRACT-2" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "下载：SOW-2" })).toBeVisible()
  })

  it("downloads with a DOM anchor instead of confusing the record with window.document", async () => {
    const clicked: Array<{ href: string; filename: string; attached: boolean }> = []
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push({ href: this.href, filename: this.download, attached: this.isConnected })
    })
    const base = baseRequest({ documents: { list: () => [confirmedSow] } })
    const apiRequest = vi.fn((path: string, options: { method: string; body?: unknown }) => (
      path === `${documentsPath}/ver-sow-3/download-url`
        ? Promise.resolve(apiOk({ url: "https://api.example.com/download/signed-document" }))
        : base(path, options)
    ))
    renderDocumentsTab(apiRequest, { role: "viewer" })

    await userEvent.setup().click(await screen.findByRole("button", { name: "下载：SOW-1" }))

    await waitFor(() => expect(clicked).toEqual([{ href: "https://api.example.com/download/signed-document", filename: "SOW-1.docx", attached: true }]))
    expect(document.querySelector('a[download="SOW-1.docx"]')).toBeNull()
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })

  it("viewer cannot see create/confirm controls", async () => {
    const apiRequest = baseRequest({ documents: { list: () => [confirmedSow] } })
    renderDocumentsTab(apiRequest, { role: "viewer" })

    expect(await screen.findByRole("table", { name: "项目文档" })).toBeVisible()
    expect(screen.getByText("你可以查看并下载可用的文档，但当前角色无法创建或编辑。")).toBeVisible()
    expect(screen.queryByRole("button", { name: "新建文档" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "确认：SOW-1" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "下载：SOW-1" })).toBeVisible()
  })

  it("creates a document with a selected business category in the payload", async () => {
    let listReads = 0
    const created: DocumentSummaryDto = { ...confirmedSow, business_category: "调研" }
    const apiRequest = baseRequest({
      documents: {
        list: () => {
          listReads += 1
          return listReads === 1 ? [] : [created]
        },
        create: () => created,
      },
    })
    const user = userEvent.setup()
    renderDocumentsTab(apiRequest, { role: "admin" })

    await screen.findByText("暂无项目文档。")
    await user.click(screen.getByRole("button", { name: "新建文档" }))
    await user.selectOptions(await screen.findByLabelText("新建文档业务阶段"), "调研")
    await user.click(screen.getByRole("button", { name: "创建" }))

    expect(await screen.findByText("SOW-1")).toBeVisible()
    expect(apiRequest.mock.calls).toContainEqual([
      documentsPath,
      expect.objectContaining({
        method: "POST",
        body: expect.objectContaining({ document_type: "sow", template_version_id: expect.any(String), expected_version: 5, business_category: "调研" }),
      }),
    ])
  })

  it("shows a business-category chip on a categorized document row", async () => {
    const categorized: DocumentSummaryDto = { ...confirmedSow, business_category: "培训预交接" }
    const apiRequest = baseRequest({ documents: { list: () => [categorized] } })
    renderDocumentsTab(apiRequest, { role: "admin" })

    const table = await screen.findByRole("table", { name: "项目文档" })
    expect(table).toBeVisible()
    expect(within(table).getByText("培训预交接")).toBeVisible()
  })

  it("filters the document list by business category and requests only matching rows", async () => {
    const researchDoc: DocumentSummaryDto = { ...confirmedSow, id: "doc-research", business_code: "SOW-2", business_category: "调研" }
    const apiRequest = baseRequest({
      documents: { list: (category?: string) => category === "调研" ? [researchDoc] : [confirmedSow, researchDoc] },
    })
    const user = userEvent.setup()
    renderDocumentsTab(apiRequest, { role: "admin" })

    expect(await screen.findByRole("table", { name: "项目文档" })).toBeVisible()
    expect(screen.getByText("SOW-1")).toBeVisible()
    expect(screen.getByText("SOW-2")).toBeVisible()

    await user.selectOptions(screen.getByLabelText("筛选业务阶段"), "调研")
    await waitFor(() => expect(screen.queryByText("SOW-1")).not.toBeInTheDocument())
    expect(screen.getByText("SOW-2")).toBeVisible()
    expect(apiRequest.mock.calls).toContainEqual([
      `${documentsPath}?business_category=${encodeURIComponent("调研")}`,
      expect.objectContaining({ method: "GET" }),
    ])
  })
})

function baseRequest(options: {
  documents?: {
    list?: (category?: string) => DocumentSummaryDto[]
    create?: () => unknown
    generate?: () => unknown
    revise?: () => unknown
    patchDraft?: () => unknown
  }
}): ReturnType<typeof vi.fn> {
  return vi.fn((path: string, requestOptions: { method: string; body?: unknown }) => {
    if (path === projectDetailPath && requestOptions.method === "GET") {
      return Promise.resolve(apiOk(project))
    }
    if (path === documentTemplatesPath && requestOptions.method === "GET") {
      return Promise.resolve(apiOk({ items: [{ document_type: "sow", id: "tmpl-sow", versions: [{ id: "tmpl-sow-pub", status: "published", version_number: 1 }] }] }))
    }
    if (path === documentsPath && requestOptions.method === "GET") {
      return Promise.resolve(apiOk({ items: options.documents?.list?.() ?? [] }))
    }
    if (path.startsWith(`${documentsPath}?business_category=`) && requestOptions.method === "GET") {
      const category = decodeURIComponent(path.split("business_category=")[1])
      return Promise.resolve(apiOk({ items: options.documents?.list?.(category) ?? [] }))
    }
    if (path === documentsPath && requestOptions.method === "POST") {
      return Promise.resolve(apiOk(options.documents?.create?.() ?? {}))
    }
    if (path === `${documentsPath}/doc-1/generate` && requestOptions.method === "POST") {
      return Promise.resolve(apiOk(options.documents?.generate?.() ?? {}))
    }
    if (path === `${documentsPath}/doc-1/revise` && requestOptions.method === "POST") {
      return Promise.resolve(apiOk(options.documents?.revise?.() ?? {}))
    }
    if (path === `${documentsPath}/doc-1/draft` && requestOptions.method === "PATCH") {
      return Promise.resolve(apiOk(options.documents?.patchDraft?.() ?? { version: 2, document_id: "doc-1", id: "draft-1", field_overrides: {}, rich_text: {}, list_selections: {}, created_at: "2026-08-25T09:00:00+08:00", updated_at: "2026-08-25T09:00:00+08:00" }))
    }
    return Promise.resolve(apiError("unexpected_request", 500))
  })
}

function renderDocumentsTab(apiRequest: ReturnType<typeof vi.fn>, options: { role: UserDto["role"] }): void {
  const currentUser: UserDto = {
    ...(options.role === "admin" ? adminUser : engineerUser),
    id: options.role === "viewer" ? "viewer-id" : options.role === "admin" ? adminUser.id : engineerUser.id,
    role: options.role,
    username: `${options.role}.user`,
    displayName: `${options.role} 用户`,
  }
  installBridge(bridge({
    refresh: vi.fn().mockResolvedValue(ok(authResult(currentUser))),
    apiRequest,
  }))
  renderApp(<AuthProvider><DangerConfirmProvider><DocumentsHarness canManage={options.role !== "viewer"} /></DangerConfirmProvider></AuthProvider>)
}

function DocumentsHarness({ canManage }: { canManage: boolean }) {
  return useAuth().status === "authenticated" ? <ProjectDocuments projectId={projectId} canManage={canManage} /> : null
}

function apiOk<T>(data: T): BridgeResult<ApiResponse<T>> {
  return ok({ status: 200, data, error: null })
}

function apiError(code: string, status: number): BridgeResult<ApiResponse<never>> {
  return ok({ status, data: null, error: { code, message: code } })
}
