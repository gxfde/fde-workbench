// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AuthProvider, useAuth } from "../../src/renderer/src/auth/AuthProvider"
import { DangerConfirmProvider } from "../../src/renderer/src/common/DangerConfirmProvider"
import { ProjectFiles } from "../../src/renderer/src/files/ProjectFiles"
import type { ProjectFileDto } from "../../src/renderer/src/files/types"
import type { ApiResponse, BridgeResult, UserDto } from "../../src/shared/contracts"
import type { ProjectDto } from "../../src/renderer/src/workbench/types"
import { adminUser, authResult, bridge, engineerUser, installBridge, ok, renderApp } from "./test-utils"

const projectId = "project-xinghe"
const projectDetailPath = `/api/v1/projects/${projectId}`
const filesPath = `/api/v1/projects/${projectId}/files`
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

const availableFile: ProjectFileDto = {
  id: "file-available",
  project_id: projectId,
  display_name: "可行报告.txt",
  category: "attachment",
  status: "active",
  current_version_id: "version-available",
  current_version: { id: "version-available", version_number: 1, status: "available", scan_status: "clean" },
  created_by: "管理员",
}

const quarantinedFile: ProjectFileDto = {
  id: "file-quarantined",
  project_id: projectId,
  display_name: "被隔离文件.txt",
  category: "document",
  status: "active",
  current_version_id: "version-quarantined",
  current_version: { id: "version-quarantined", version_number: 1, status: "quarantined", scan_status: "pending" },
  created_by: "王工",
}

const session = {
  id: "session-1",
  project_id: projectId,
  name: "报告.txt",
  category: "attachment",
  size_bytes: 11,
  mime_type: "text/plain",
  part_size: 5 * 1024 * 1024,
  upload_id: "upload-1",
  expires_at: "2026-08-25T09:00:00+08:00",
  idempotency_key: "key-1",
}

afterEach(() => {
  cleanup()
  location.hash = ""
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("project files workspace", () => {
  it("keeps upload controls and the business-stage filter in one toolbar", async () => {
    const apiRequest = baseRequest({ files: { list: () => [availableFile] } })
    renderFilesTab(apiRequest, { role: "admin" })

    const toolbar = await screen.findByRole("toolbar", { name: "文件工具栏" })
    expect(within(toolbar).getByRole("button", { name: "上传文件" })).toBeVisible()
    expect(within(toolbar).getByLabelText("筛选业务阶段")).toBeVisible()
  })

  it("renders file list with status labels and gates download on availability", async () => {
    const apiRequest = baseRequest({
      files: { list: () => [availableFile, quarantinedFile] },
    })
    renderFilesTab(apiRequest, { role: "admin" })

    expect(await screen.findByRole("table", { name: "项目文件" })).toBeVisible()
    expect(screen.getByText("可下载")).toBeVisible()
    expect(screen.getByText("处理中")).toBeVisible()

    const table = await screen.findByRole("table", { name: "项目文件" })
    expect(within(table).getByRole("button", { name: "下载：可行报告.txt" })).toBeVisible()
    expect(within(table).queryByRole("button", { name: "下载：被隔离文件.txt" })).not.toBeInTheDocument()
  })

  it("uploads a file through the create/sign/complete part flow and refreshes the list", async () => {
    let listReads = 0
    const apiRequest = baseRequest({
      files: {
        list: () => {
          listReads += 1
          return listReads === 1 ? [] : [availableFile]
        },
        createSession: () => session,
        signPart: (partNumber: number) => ({ url: "https://storage.test/part-1", part_number: partNumber, expires_seconds: 300 }),
        complete: () => ({ version_id: "version-available", file_id: "file-available", status: "quarantined", scan_status: "pending" }),
      },
    })
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 200, headers: { ETag: '"etag-val"' } }))
    vi.stubGlobal("fetch", fetchMock)
    renderFilesTab(apiRequest, { role: "admin" })

    await screen.findByText("暂无项目文件。")
    const input = await screen.findByLabelText("选择文件")
    const file = new File(["hello world"], "报告.txt", { type: "text/plain" })
    fireEvent.change(input, { target: { files: [file] } })
    expect(await screen.findByRole("dialog", { name: "填写文件名称" })).toBeVisible()
    await userEvent.click(screen.getByRole("button", { name: "开始上传" }))

    expect(await screen.findByRole("button", { name: "下载：可行报告.txt" })).toBeVisible()
    expect(screen.getByText("可下载")).toBeVisible()

    expect(apiRequest.mock.calls).toContainEqual([filesPath, expect.objectContaining({
      method: "POST",
      body: expect.objectContaining({ name: "报告.txt", display_name: "报告", size_bytes: 11, mime_type: "text/plain", category: "attachment" }),
    })])
    expect(apiRequest.mock.calls).toContainEqual([`${filesPath}/session-1/parts`, expect.objectContaining({ method: "POST", body: { part_number: 1 } })])
    expect(apiRequest.mock.calls).toContainEqual([`${filesPath}/session-1/complete`, expect.objectContaining({ method: "POST", body: { parts: [{ part_number: 1, etag: "etag-val" }] } })])
    expect(fetchMock).toHaveBeenCalledWith("https://storage.test/part-1", expect.objectContaining({ method: "PUT" }))
    expect(listReads).toBeGreaterThan(1)
  })

  it("does not show the download button for a quarantined file", async () => {
    const apiRequest = baseRequest({
      files: { list: () => [quarantinedFile] },
    })
    renderFilesTab(apiRequest, { role: "admin" })

    expect(await screen.findByText("处理中")).toBeVisible()
    expect(screen.getByRole("table", { name: "项目文件" })).toBeVisible()
    expect(screen.queryByRole("button", { name: "下载：被隔离文件.txt" })).not.toBeInTheDocument()
    const row = screen.getByText("被隔离文件.txt").closest("tr")
    expect(row?.querySelector("td:last-child")).toBeEmptyDOMElement()
  })

  it("renders file management read-only for a viewer", async () => {
    const apiRequest = baseRequest({
      files: { list: () => [availableFile] },
    })
    renderFilesTab(apiRequest, { role: "viewer" })

    expect(await screen.findByRole("table", { name: "项目文件" })).toBeVisible()
    expect(screen.getByText("可下载")).toBeVisible()
    expect(screen.getByText("你可以查看并下载可用的文件，但当前角色无法上传。")).toBeVisible()
  })

  it("renders a signed preview iframe when the preview is ready", async () => {
    const pdfFile: ProjectFileDto = {
      ...availableFile,
      display_name: "可行报告.pdf",
      current_version: { ...availableFile.current_version!, original_filename: "可行报告.pdf" },
    }
    const apiRequest = baseRequest({
      files: { list: () => [pdfFile] },
      previewUrl: apiOk({ url: "https://storage.test/preview.pdf", expires_seconds: 300 }),
    })
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(new Blob(["%PDF-1.7"]), { status: 200 })))
    const user = userEvent.setup()
    renderFilesTab(apiRequest, { role: "admin" })

    await user.click(await screen.findByRole("button", { name: "预览：可行报告.pdf" }))

    expect(await screen.findByTitle("预览：可行报告.pdf")).toHaveAttribute("src", expect.stringMatching(/^blob:/))
    expect(screen.queryByText("预览生成失败，原文件可下载。")).not.toBeInTheDocument()
  })

  it("degrades gracefully when the preview is not available and offers a download link instead of a blank iframe", async () => {
    const docxFile: ProjectFileDto = {
      id: "file-docx",
      project_id: projectId,
      display_name: "方案说明.docx",
      category: "attachment",
      status: "active",
      current_version_id: "version-docx",
      current_version: { id: "version-docx", version_number: 1, status: "available", scan_status: "clean" },
      created_by: "管理员",
    }
    const apiRequest = baseRequest({
      files: { list: () => [docxFile] },
      previewUrl: apiError("preview_not_available", 409),
    })
    const user = userEvent.setup()
    renderFilesTab(apiRequest, { role: "admin" })

    await user.click(await screen.findByRole("button", { name: "预览：方案说明.docx" }))

    expect(await screen.findByText("预览生成失败，原文件可下载。")).toBeVisible()
    expect(screen.getByRole("button", { name: "下载 DOCX" })).toBeVisible()
    expect(screen.getByRole("button", { name: "重新生成预览" })).toBeVisible()
    expect(screen.queryByTitle("预览：方案说明.docx")).not.toBeInTheDocument()
    expect(apiRequest.mock.calls).toContainEqual([
      `${filesPath}/version-docx/preview-url`,
      expect.objectContaining({ method: "GET" }),
    ])
  })

  it("queues preview regeneration from a failed preview", async () => {
    const docxFile: ProjectFileDto = {
      id: "file-docx",
      project_id: projectId,
      display_name: "方案说明.docx",
      category: "attachment",
      status: "active",
      current_version_id: "version-docx",
      current_version: { id: "version-docx", version_number: 1, status: "available", scan_status: "clean", preview_status: "failed" },
      created_by: "管理员",
    }
    const apiRequest = baseRequest({
      files: { list: () => [docxFile] },
      previewUrl: apiError("preview_not_available", 409),
      regeneratePreview: apiOk({ preview_status: "pending" }),
    })
    const user = userEvent.setup()
    renderFilesTab(apiRequest, { role: "admin" })

    await user.click(await screen.findByRole("button", { name: "预览：方案说明.docx" }))
    await user.click(await screen.findByRole("button", { name: "重新生成预览" }))

    expect(await screen.findByText("已提交重新生成。稍后关闭并重新打开预览即可查看结果。")).toBeVisible()
    expect(apiRequest.mock.calls).toContainEqual([
      `${filesPath}/version-docx/preview`,
      expect.objectContaining({ method: "POST" }),
    ])
  })

  it("fetches a signed download URL when recovering from a failed preview", async () => {
    const docxFile: ProjectFileDto = {
      id: "file-docx",
      project_id: projectId,
      display_name: "方案说明.docx",
      category: "attachment",
      status: "active",
      current_version_id: "version-docx",
      current_version: { id: "version-docx", version_number: 1, status: "available", scan_status: "clean" },
      created_by: "管理员",
    }
    const apiRequest = baseRequest({
      files: { list: () => [docxFile] },
      previewUrl: apiError("preview_not_available", 409),
      downloadUrl: apiOk({ url: "https://storage.test/source.docx", expires_seconds: 300 }),
    })
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined)
    const user = userEvent.setup()
    renderFilesTab(apiRequest, { role: "admin" })

    await user.click(await screen.findByRole("button", { name: "预览：方案说明.docx" }))
    expect(await screen.findByText("预览生成失败，原文件可下载。")).toBeVisible()
    await user.click(screen.getByRole("button", { name: "下载 DOCX" }))

    expect(apiRequest.mock.calls).toContainEqual([
      `${filesPath}/version-docx/download-url`,
      expect.objectContaining({ method: "GET" }),
    ])
    expect(anchorClick).toHaveBeenCalled()
  })

  it("uploads a file with the selected business category in the create payload", async () => {
    let listReads = 0
    const apiRequest = baseRequest({
      files: {
        list: () => {
          listReads += 1
          return listReads === 1 ? [] : [availableFile]
        },
        createSession: () => session,
        signPart: (partNumber: number) => ({ url: "https://storage.test/part-1", part_number: partNumber, expires_seconds: 300 }),
        complete: () => ({ version_id: "version-available", file_id: "file-available", status: "quarantined", scan_status: "pending" }),
      },
    })
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 200, headers: { ETag: '"etag-val"' } }))
    vi.stubGlobal("fetch", fetchMock)
    renderFilesTab(apiRequest, { role: "admin" })

    await screen.findByText("暂无项目文件。")
    // The upload category now comes from the single 筛选业务阶段 filter.
    await userEvent.selectOptions(screen.getByLabelText("筛选业务阶段"), "调研")
    const input = await screen.findByLabelText("选择文件")
    const file = new File(["hello world"], "报告.txt", { type: "text/plain" })
    fireEvent.change(input, { target: { files: [file] } })
    await userEvent.click(await screen.findByRole("button", { name: "开始上传" }))

    expect(await screen.findByRole("button", { name: "下载：可行报告.txt" })).toBeVisible()
    expect(apiRequest.mock.calls).toContainEqual([filesPath, expect.objectContaining({
      method: "POST",
      body: expect.objectContaining({ name: "报告.txt", size_bytes: 11, mime_type: "text/plain", category: "attachment", business_category: "调研" }),
    })])
  })

  it("shows a business-category chip on a categorized file row", async () => {
    const categorized: ProjectFileDto = { ...availableFile, business_category: "生产部署" }
    const apiRequest = baseRequest({ files: { list: () => [categorized] } })
    renderFilesTab(apiRequest, { role: "admin" })

    const table = await screen.findByRole("table", { name: "项目文件" })
    expect(table).toBeVisible()
    expect(within(table).getByText("生产部署")).toBeVisible()
  })

  it("filters the file list by business category and requests only matching rows", async () => {
    const researchFile: ProjectFileDto = { ...availableFile, id: "file-research", display_name: "预调研.txt", business_category: "调研" }
    const apiRequest = baseRequest({
      files: { list: (category?: string) => category === "调研" ? [researchFile] : [availableFile, researchFile] },
    })
    renderFilesTab(apiRequest, { role: "admin" })

    expect(await screen.findByRole("table", { name: "项目文件" })).toBeVisible()
    expect(screen.getByText("可行报告.txt")).toBeVisible()
    expect(screen.getByText("预调研.txt")).toBeVisible()

    await userEvent.selectOptions(screen.getByLabelText("筛选业务阶段"), "调研")
    await waitFor(() => expect(screen.queryByText("可行报告.txt")).not.toBeInTheDocument())
    expect(screen.getByText("预调研.txt")).toBeVisible()
    expect(apiRequest.mock.calls).toContainEqual([
      `${filesPath}?business_category=${encodeURIComponent("调研")}`,
      expect.objectContaining({ method: "GET" }),
    ])
  })

  it("filters uncategorized files via the 未分类 filter token", async () => {
    const uncategorized: ProjectFileDto = { ...availableFile, id: "file-uncat", display_name: "未分类.txt", business_category: null }
    const categorized: ProjectFileDto = { ...availableFile, id: "file-cat", display_name: "已分类.txt", business_category: "调研" }
    const apiRequest = baseRequest({
      files: { list: (category?: string) => category === "未分类" ? [uncategorized] : [categorized, uncategorized] },
    })
    renderFilesTab(apiRequest, { role: "admin" })

    expect(await screen.findByRole("table", { name: "项目文件" })).toBeVisible()
    expect(screen.getByText("已分类.txt")).toBeVisible()
    await userEvent.selectOptions(screen.getByLabelText("筛选业务阶段"), "未分类")
    await waitFor(() => expect(screen.queryByText("已分类.txt")).not.toBeInTheDocument())
    expect(screen.getByText("未分类.txt")).toBeVisible()
    expect(apiRequest.mock.calls).toContainEqual([
      `${filesPath}?business_category=${encodeURIComponent("未分类")}`,
      expect.objectContaining({ method: "GET" }),
    ])
  })
})

function baseRequest(options: {
  files?: {
    list?: (category?: string) => ProjectFileDto[]
    createSession?: () => unknown
    signPart?: (partNumber: number) => unknown
    complete?: () => unknown
  }
  previewUrl?: ReturnType<typeof apiOk> | ReturnType<typeof apiError>
  downloadUrl?: ReturnType<typeof apiOk> | ReturnType<typeof apiError>
  regeneratePreview?: ReturnType<typeof apiOk> | ReturnType<typeof apiError>
}): ReturnType<typeof vi.fn> {
  return vi.fn((path: string, requestOptions: { method: string; body?: unknown }) => {
    if (path === projectDetailPath && requestOptions.method === "GET") {
      return Promise.resolve(apiOk(project))
    }
    if (path === filesPath && requestOptions.method === "GET") {
      return Promise.resolve(apiOk({ items: options.files?.list?.() ?? [] }))
    }
    if (path.startsWith(`${filesPath}?business_category=`) && requestOptions.method === "GET") {
      const category = decodeURIComponent(path.split("business_category=")[1])
      return Promise.resolve(apiOk({ items: options.files?.list?.(category) ?? [] }))
    }
    if (path === filesPath && requestOptions.method === "POST") {
      return Promise.resolve(apiOk(options.files?.createSession?.() ?? session))
    }
    if (path === `${filesPath}/session-1/parts` && requestOptions.method === "POST") {
      const partNumber = typeof requestOptions.body === "object" && requestOptions.body !== null && "part_number" in requestOptions.body
        ? (requestOptions.body as { part_number: number }).part_number
        : 1
      return Promise.resolve(apiOk(options.files?.signPart?.(partNumber) ?? { url: "https://storage.test/part-1", part_number: partNumber, expires_seconds: 300 }))
    }
    if (path === `${filesPath}/session-1/complete` && requestOptions.method === "POST") {
      return Promise.resolve(apiOk(options.files?.complete?.() ?? { version_id: "version-available", file_id: "file-available", status: "quarantined", scan_status: "pending" }))
    }
    if (path.endsWith("/preview-url") && requestOptions.method === "GET") {
      return Promise.resolve(options.previewUrl ?? apiOk({ url: "https://storage.test/preview.pdf", expires_seconds: 300 }))
    }
    if (path.endsWith("/download-url") && requestOptions.method === "GET") {
      return Promise.resolve(options.downloadUrl ?? apiOk({ url: "https://storage.test/source.pdf", expires_seconds: 300 }))
    }
    if (path.endsWith("/preview") && requestOptions.method === "POST") {
      return Promise.resolve(options.regeneratePreview ?? apiOk({ preview_status: "pending" }))
    }
    return Promise.resolve(apiError("unexpected_request", 500))
  })
}

function renderFilesTab(apiRequest: ReturnType<typeof vi.fn>, options: { role: UserDto["role"] }): void {
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
  renderApp(<AuthProvider><DangerConfirmProvider><FilesHarness canManage={options.role !== "viewer"} /></DangerConfirmProvider></AuthProvider>)
}

function FilesHarness({ canManage }: { canManage: boolean }) {
  return useAuth().status === "authenticated" ? <ProjectFiles projectId={projectId} canManage={canManage} /> : null
}

function apiOk<T>(data: T): BridgeResult<ApiResponse<T>> {
  return ok({ status: 200, data, error: null })
}

function apiError(code: string, status: number): BridgeResult<ApiResponse<never>> {
  return ok({ status, data: null, error: { code, message: code } })
}
