// @vitest-environment jsdom
// T-B1 封包半桌面面（goal-tb tb4）＋SME 尾巴桌面轮：结项交付包面板。
// 钉住：双列表加载与空态 / 创建 POST 形状（勾选→items，三态指针键随型）/
// 类型切换拉取分型挑选面（?type=）/ 跨类型混装 / 状态动作显隐（canManage
// 封存解封、isAdmin 交付登记）/ 详情清单三态类型列与 manifest 呈现。
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

import { HandoverPackagesPanel } from "../../src/renderer/src/handover/HandoverPackagesPanel"

const draftPackage = {
  id: "pkg-1",
  project_id: "project-1",
  label: "结项交付包",
  status: "draft",
  created_at: "2026-11-07T08:00:00+00:00",
  sealed_by_user_id: null,
  sealed_at: null,
  unsealed_count: 0,
  delivered_by_user_id: null,
  delivered_at: null,
}

const reviewedArtifact = {
  artifact_id: "art-1",
  run_id: "run-1",
  kind: "diff",
  storage_ref: "run-1/output/change.diff",
  sha256: "b".repeat(64),
  reviewed_at: "2026-11-07T07:00:00+00:00",
}

const confirmedDocument = {
  document_version_id: "docv-1",
  document_id: "doc-1",
  version_number: 3,
  kind: "document",
  storage_ref: "document-version:docv-1",
  sha256: "c".repeat(64),
}

const availableFile = {
  file_version_id: "filev-1",
  file_id: "file-1",
  kind: "file",
  storage_ref: "docs/spec.pdf",
  sha256: "d".repeat(64),
}

function mockGet(url: string): unknown {
  if (url.startsWith("/api/v1/handover-packages?")) {
    return { items: [draftPackage], total: null, limit: 50, offset: 0, truncated: false }
  }
  if (url.startsWith("/api/v1/handover-packages/artifacts?")) {
    if (url.endsWith("type=document")) return { items: [confirmedDocument], truncated: false }
    if (url.endsWith("type=file")) return { items: [availableFile], truncated: false }
    return { items: [reviewedArtifact], truncated: false }
  }
  if (url === `/api/v1/handover-packages/${draftPackage.id}`) {
    return {
      ...draftPackage,
      items: [
        { id: "item-1", item_type: "artifact", artifact_id: "art-1", document_version_id: null, file_version_id: null, run_id: "run-1", kind: "diff", display_name: "change.diff", storage_ref: "run-1/output/change.diff", sha256: "b".repeat(64) },
      ],
    }
  }
  throw new Error(`unexpected GET ${url}`)
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
  mocks.apiRequest.mockImplementation((url: string, init?: { method?: string }) => {
    const method = init?.method ?? "GET"
    if (method === "GET") return Promise.resolve(mockGet(url))
    if (method === "POST" || method === "PATCH") return Promise.resolve({ data: {}, error: null })
    throw new Error(`unexpected ${method} ${url}`)
  })
})

afterEach(() => {
  cleanup()
})

function renderPanel(canManage = true, isAdmin = false) {
  return render(<HandoverPackagesPanel projectId="project-1" canManage={canManage} isAdmin={isAdmin} />)
}

it("加载包列表与挑选面并呈现三态指针纪律注记", async () => {
  renderPanel()
  expect(await screen.findByRole("heading", { name: "结项交付包" })).toBeInTheDocument()
  expect(screen.getByText("草稿")).toBeInTheDocument()
  expect(screen.getByText(/清单=产物\/文档\/文件版本指针\+sha256 快照/)).toBeInTheDocument()
  // 挑选面缺省 artifact 带 type 参数（服务端 ?type= 分型投影契约）
  await waitFor(() => {
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      "/api/v1/handover-packages/artifacts?project_id=project-1&type=artifact",
      expect.objectContaining({ method: "GET" }),
    )
  })
})

it("空态提示先复核产物再组包", async () => {
  mocks.apiRequest.mockImplementation((url: string) => {
    if (url.startsWith("/api/v1/handover-packages?")) {
      return Promise.resolve({ items: [], total: null, limit: 50, offset: 0, truncated: false })
    }
    if (url.startsWith("/api/v1/handover-packages/artifacts?")) {
      return Promise.resolve({ items: [], truncated: false })
    }
    throw new Error(`unexpected GET ${url}`)
  })
  renderPanel()
  expect(await screen.findByText(/暂无结项交付包/)).toBeInTheDocument()
  fireEvent.click(screen.getByText("新建交付包"))
  expect(await screen.findByText(/暂无已复核产物/)).toBeInTheDocument()
})

it("创建草稿包：勾选产物→POST items 快照形状", async () => {
  renderPanel()
  fireEvent.click(await screen.findByText("新建交付包"))
  fireEvent.change(screen.getByLabelText("包名（可选）"), { target: { value: "结项包" } })
  fireEvent.click(screen.getByRole("checkbox"))
  fireEvent.click(screen.getByText("创建草稿包"))
  await waitFor(() => {
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      "/api/v1/handover-packages",
      expect.objectContaining({ method: "POST" }),
    )
  })
  const call = mocks.apiRequest.mock.calls.find((c) => c[0] === "/api/v1/handover-packages" && c[1]?.method === "POST")!
  // body 契约＝对象（api-ipc serializeBody 统一 stringify；预 stringify 会二次编码）。
  const body = call[1].body as Record<string, unknown>
  expect(body.label).toBe("结项包")
  expect(body.items).toEqual([{ artifact_id: "art-1", display_name: "change.diff" }])
})

it("类型切换：文档版挑选面拉取与 document_version_id 指针提交", async () => {
  renderPanel()
  fireEvent.click(await screen.findByText("新建交付包"))
  fireEvent.click(screen.getByRole("button", { name: "文档版本" }))
  expect(await screen.findByText("document-version:docv-1")).toBeInTheDocument()
  expect(screen.getByText(/文档 v3/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole("checkbox"))
  fireEvent.click(screen.getByText("创建草稿包"))
  await waitFor(() => {
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      "/api/v1/handover-packages",
      expect.objectContaining({ method: "POST" }),
    )
  })
  const call = mocks.apiRequest.mock.calls.find((c) => c[0] === "/api/v1/handover-packages" && c[1]?.method === "POST")!
  const body = call[1].body as Record<string, unknown>
  // display_name 缺省（undefined 序列化时剔除）→ 服务端默认 business_code v{n}
  expect(body.items).toEqual([{ document_version_id: "docv-1" }])
})

it("类型切换：文件版挑选面与 file_version_id 指针提交", async () => {
  renderPanel()
  fireEvent.click(await screen.findByText("新建交付包"))
  fireEvent.click(screen.getByRole("button", { name: "文件版本" }))
  expect(await screen.findByText("docs/spec.pdf")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("checkbox"))
  fireEvent.click(screen.getByText("创建草稿包"))
  await waitFor(() => {
    const call = mocks.apiRequest.mock.calls.find((c) => c[0] === "/api/v1/handover-packages" && c[1]?.method === "POST")
    expect(call).toBeDefined()
  })
  const call = mocks.apiRequest.mock.calls.find((c) => c[0] === "/api/v1/handover-packages" && c[1]?.method === "POST")!
  const body = call[1].body as Record<string, unknown>
  expect(body.items).toEqual([{ file_version_id: "filev-1" }])
})

it("跨类型混装：artifact+document 双指针同包提交", async () => {
  renderPanel()
  fireEvent.click(await screen.findByText("新建交付包"))
  fireEvent.click(screen.getByRole("checkbox")) // 已复核产物 art-1
  fireEvent.click(screen.getByRole("button", { name: "文档版本" }))
  fireEvent.click(await screen.findByRole("checkbox")) // 文档版本 docv-1
  fireEvent.click(screen.getByText("创建草稿包"))
  await waitFor(() => {
    const call = mocks.apiRequest.mock.calls.find((c) => c[0] === "/api/v1/handover-packages" && c[1]?.method === "POST")
    expect(call).toBeDefined()
  })
  const call = mocks.apiRequest.mock.calls.find((c) => c[0] === "/api/v1/handover-packages" && c[1]?.method === "POST")!
  const body = call[1].body as Record<string, unknown>
  // 勾选累计跨类型保留（同包三态混装）；items 顺序=勾选顺序
  expect(body.items).toEqual([
    { artifact_id: "art-1", display_name: "change.diff" },
    { document_version_id: "docv-1" },
  ])
})

it("详情展开：清单表三态类型列+草稿无 manifest 注记", async () => {
  mocks.apiRequest.mockImplementation((url: string) => {
    if (url.startsWith("/api/v1/handover-packages?")) {
      return Promise.resolve({ items: [draftPackage], total: null, limit: 50, offset: 0, truncated: false })
    }
    if (url.startsWith("/api/v1/handover-packages/artifacts?")) {
      return Promise.resolve({ items: [], truncated: false })
    }
    if (url === `/api/v1/handover-packages/${draftPackage.id}`) {
      return Promise.resolve({
        ...draftPackage,
        items: [
          { id: "item-1", item_type: "artifact", artifact_id: "art-1", document_version_id: null, file_version_id: null, run_id: "run-1", kind: "diff", display_name: "change.diff", storage_ref: "run-1/output/change.diff", sha256: "b".repeat(64) },
          { id: "item-2", item_type: "document", artifact_id: null, document_version_id: "docv-9", file_version_id: null, run_id: null, kind: "document", display_name: "SOW 代号 v2", storage_ref: "document-version:docv-9", sha256: "c".repeat(64) },
        ],
      })
    }
    throw new Error(`unexpected GET ${url}`)
  })
  renderPanel()
  fireEvent.click(await screen.findByText("清单"))
  expect(await screen.findByText("change.diff")).toBeInTheDocument()
  expect(screen.getByText("SOW 代号 v2")).toBeInTheDocument()
  expect(screen.getByRole("columnheader", { name: "类型" })).toBeInTheDocument()
  expect(screen.getByText("文档")).toBeInTheDocument()
  expect(screen.getByText("产物")).toBeInTheDocument()
  expect(screen.getByText(/草稿包无 manifest 指纹/)).toBeInTheDocument()
})

it("状态动作显隐：canManage 封存/解封、isAdmin 才有交付登记", async () => {
  const sealedPackage = { ...draftPackage, status: "sealed", sealed_at: "2026-11-07T09:00:00+00:00" }
  mocks.apiRequest.mockImplementation((url: string) => {
    if (url.startsWith("/api/v1/handover-packages?")) {
      return Promise.resolve({ items: [sealedPackage], total: null, limit: 50, offset: 0, truncated: false })
    }
    if (url.startsWith("/api/v1/handover-packages/artifacts?")) {
      return Promise.resolve({ items: [reviewedArtifact], truncated: false })
    }
    throw new Error(`unexpected GET ${url}`)
  })
  // 非 admin 管理员：解封有、交付登记无
  renderPanel(true, false)
  await screen.findByText("已封存")
  expect(screen.getByText("解封")).toBeInTheDocument()
  expect(screen.queryByText("交付登记")).toBeNull()
  cleanup()
  // admin：交付登记在
  renderPanel(true, true)
  await screen.findByText("已封存")
  expect(screen.getByText("交付登记")).toBeInTheDocument()
  // 非 canManage：无任何动作按钮
  cleanup()
  renderPanel(false, false)
  await screen.findByText("已封存")
  expect(screen.queryByText("解封")).toBeNull()
  expect(screen.queryByText("交付登记")).toBeNull()
})
