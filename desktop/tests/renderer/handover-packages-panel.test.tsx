// @vitest-environment jsdom
// T-B1 封包半桌面面（goal-tb tb4）＋SME 尾巴桌面轮：结项交付包面板。
// 钉住：双列表加载与空态 / 创建 POST 形状（勾选→items，三态指针键随型）/
// 类型切换拉取分型挑选面（?type=）/ 跨类型混装 / 状态动作显隐（canManage
// 封存解封、isAdmin 交付登记）/ 详情清单三态类型列与 manifest 呈现。
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({
  useAuth: () => ({ apiRequest: mocks.apiRequest }),
}))

import { ApiClientError } from "../../src/renderer/src/api/client"
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

const detailPath = `/api/v1/handover-packages/${draftPackage.id}`
const sealedDetail = {
  ...draftPackage,
  status: "sealed",
  sealed_at: "2026-11-07T09:00:00+00:00",
  unsealed_count: 2,
  manifest_sha256: "f".repeat(64),
  write_preconditions: "v1",
  items: [reviewedArtifact],
}

function mockDelivery(read: () => unknown, write = vi.fn<() => unknown>()) {
  mocks.apiRequest.mockImplementation(async (url: string) => {
    if (url === `${detailPath}/deliver`) return write()
    if (url === detailPath) return read()
    if (url.startsWith("/api/v1/handover-packages?")) return { items: [sealedDetail], truncated: false }
    return mockGet(url)
  })
  return write
}

async function openDelivery() {
  fireEvent.click(await screen.findByRole("button", { name: "交付登记" }))
  return screen.findByRole("dialog", { name: "确认交付登记" })
}

it("冻结详情中的完整摘要和解封次数，仅确认后发送原批次", async () => {
  const returned = { ...sealedDetail }
  const write = mockDelivery(() => returned, vi.fn(() => ({ ...sealedDetail, status: "delivered" })))
  renderPanel(true, true)
  const dialog = await openDelivery()
  expect(within(dialog).getByText(sealedDetail.manifest_sha256)).toBeVisible()
  expect(within(dialog).getByText("1 件")).toBeVisible()
  expect(within(dialog).getByText("2026-11-07 09:00:00")).toBeVisible()
  expect(write).not.toHaveBeenCalled()
  returned.manifest_sha256 = "0".repeat(64)
  returned.unsealed_count += 1
  fireEvent.click(within(dialog).getByRole("button", { name: "确认登记" }))
  expect(await screen.findByText(/本次登记成功/)).toBeVisible()
  expect(mocks.apiRequest).toHaveBeenCalledWith(`${detailPath}/deliver`, {
    method: "POST", retryAfterAuthRefresh: false,
    body: { expected_manifest_sha256: sealedDetail.manifest_sha256, expected_unsealed_count: 2 },
  })
  expect(write).toHaveBeenCalledTimes(1)
})

it("取消确认不会写入", async () => {
  const write = mockDelivery(() => sealedDetail)
  renderPanel(true, true)
  fireEvent.click(within(await openDelivery()).getByRole("button", { name: "取消" }))
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  expect(write).not.toHaveBeenCalled()
})

it("旧服务端即使返回摘要也不会收到登记请求", async () => {
  const write = mockDelivery(() => ({ ...sealedDetail, write_preconditions: undefined }))
  renderPanel(true, true)
  fireEvent.click(await screen.findByRole("button", { name: "交付登记" }))
  expect(await screen.findByText(/当前服务端不支持封存批次确认/)).toBeVisible()
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  expect(write).not.toHaveBeenCalled()
})

it("封存批次冲突后关闭旧确认，等待用户重新确认", async () => {
  const write = mockDelivery(() => sealedDetail, vi.fn(() => {
    throw new ApiClientError({ code: "handover_snapshot_conflict", message: "封存批次已变化，本次未登记。" }, 409)
  }))
  renderPanel(true, true)
  fireEvent.click(within(await openDelivery()).getByRole("button", { name: "确认登记" }))
  expect(await screen.findByText(/本次未登记/)).toBeVisible()
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  expect(screen.getByRole("button", { name: "交付登记" })).toBeEnabled()
  expect(screen.getByRole("button", { name: "解封" })).toBeEnabled()
  expect(screen.queryByRole("button", { name: "查询登记状态" })).not.toBeInTheDocument()
  expect(screen.queryByText(/本次登记成功/)).not.toBeInTheDocument()
  expect(write).toHaveBeenCalledTimes(1)
})

it("登记超时自动回读，回读失败可手动再查，不会重发登记", async () => {
  const read = vi.fn<() => unknown>()
    .mockReturnValueOnce(sealedDetail)
    .mockRejectedValueOnce(new Error("offline"))
    .mockReturnValueOnce({ ...sealedDetail, status: "delivered" })
  const write = mockDelivery(read, vi.fn(() => {
    throw new ApiClientError({ code: "request_timeout", message: "超时" })
  }))
  renderPanel(true, true)
  fireEvent.click(within(await openDelivery()).getByRole("button", { name: "确认登记" }))
  expect(await screen.findByText(/登记结果未知，暂无法回读/)).toBeVisible()
  expect(screen.getByRole("button", { name: "交付登记" })).toBeDisabled()
  fireEvent.click(screen.getByRole("button", { name: "查询登记状态" }))
  expect(await screen.findByText(/回读查到该批次已登记/)).toBeVisible()
  expect(screen.queryByText(/本次登记成功/)).not.toBeInTheDocument()
  expect(read).toHaveBeenCalledTimes(3)
  expect(write).toHaveBeenCalledTimes(1)
})

it("登记超时后同批次仍封存则持续待核对，稍后读到已登记也不归功于本次请求", async () => {
  const read = vi.fn<() => unknown>()
    .mockReturnValueOnce(sealedDetail)
    .mockReturnValueOnce(sealedDetail)
    .mockReturnValueOnce(sealedDetail)
    .mockReturnValueOnce({ ...sealedDetail, status: "delivered" })
  const write = mockDelivery(read, vi.fn(() => {
    throw new ApiClientError({ code: "request_timeout", message: "超时" })
  }))
  renderPanel(true, true)
  fireEvent.click(within(await openDelivery()).getByRole("button", { name: "确认登记" }))

  const query = await screen.findByRole("button", { name: "查询登记状态" })
  expect(screen.getByRole("button", { name: "交付登记" })).toBeDisabled()
  expect(screen.getByRole("button", { name: "解封" })).toBeDisabled()
  expect(screen.queryByText(/本次登记成功/)).not.toBeInTheDocument()

  fireEvent.click(query)
  await waitFor(() => expect(read).toHaveBeenCalledTimes(3))
  await waitFor(() => expect(query).toBeEnabled())
  expect(screen.getByRole("button", { name: "交付登记" })).toBeDisabled()
  expect(screen.getByRole("button", { name: "解封" })).toBeDisabled()
  expect(screen.queryByText(/本次登记成功/)).not.toBeInTheDocument()

  fireEvent.click(query)
  expect(await screen.findByText(/回读查到该批次已登记，无法确认是否由本次请求完成/)).toBeVisible()
  expect(screen.getByText("已交付")).toBeVisible()
  expect(screen.queryByRole("button", { name: "交付登记" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "解封" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "查询登记状态" })).not.toBeInTheDocument()
  expect(screen.queryByText(/本次登记成功/)).not.toBeInTheDocument()
  expect(write).toHaveBeenCalledTimes(1)
  expect(mocks.apiRequest.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1)
})

it("待核对状态提供显式解除占用，解除后可重新确认但不自动重发", async () => {
  const read = vi.fn<() => unknown>()
    .mockReturnValueOnce(sealedDetail)
    .mockReturnValueOnce(sealedDetail)
    .mockReturnValueOnce(sealedDetail)
  const write = mockDelivery(read, vi.fn(() => {
    throw new ApiClientError({ code: "request_timeout", message: "超时" })
  }))
  renderPanel(true, true)
  fireEvent.click(within(await openDelivery()).getByRole("button", { name: "确认登记" }))

  expect(await screen.findByRole("button", { name: "查询登记状态" })).toBeEnabled()
  expect(screen.getByRole("button", { name: "交付登记" })).toBeDisabled()
  fireEvent.click(screen.getByRole("button", { name: "判定未提交并解除占用" }))

  expect(await screen.findByText(/已解除待核对/)).toBeVisible()
  expect(screen.queryByRole("button", { name: "查询登记状态" })).not.toBeInTheDocument()
  await waitFor(() => expect(screen.getByRole("button", { name: "交付登记" })).toBeEnabled())
  expect(screen.getByRole("button", { name: "解封" })).toBeEnabled()
  expect(write).toHaveBeenCalledTimes(1)
  expect(mocks.apiRequest.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1)
})

it("回读确认解封次数变化后解除待核对，重新登记须再次人工确认", async () => {
  const nextBatch = { ...sealedDetail, unsealed_count: sealedDetail.unsealed_count + 1 }
  const read = vi.fn<() => unknown>()
    .mockReturnValueOnce(sealedDetail)
    .mockReturnValueOnce(nextBatch)
    .mockReturnValueOnce(nextBatch)
  const write = mockDelivery(read, vi.fn(() => {
    throw new ApiClientError({ code: "request_timeout", message: "超时" })
  }))
  renderPanel(true, true)
  fireEvent.click(within(await openDelivery()).getByRole("button", { name: "确认登记" }))
  expect(await screen.findByText(/回读发现封存批次已变化/)).toBeVisible()
  await waitFor(() => expect(screen.getByRole("button", { name: "交付登记" })).toBeEnabled())
  expect(screen.getByRole("button", { name: "解封" })).toBeEnabled()
  expect(screen.queryByRole("button", { name: "查询登记状态" })).not.toBeInTheDocument()
  expect(screen.queryByText(/本次登记成功/)).not.toBeInTheDocument()
  await openDelivery()
  expect(write).toHaveBeenCalledTimes(1)
})

it("列表断网显示读取失败，原地重试成功为空才显示空态", async () => {
  const readList = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({ items: [], truncated: false })
  mocks.apiRequest.mockImplementation(async (url: string) => url.includes("?project_id=") && !url.includes("/artifacts?")
    ? readList() : mockGet(url))
  renderPanel()
  expect(await screen.findByText("交付包列表读取失败。")).toBeVisible()
  expect(screen.queryByText(/暂无结项交付包/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "重试读取交付包" }))
  expect(await screen.findByText(/暂无结项交付包/)).toBeVisible()
})

it("文档候选 5xx 可独立重试，保留跨类型勾选", async () => {
  const readDocuments = vi.fn().mockRejectedValueOnce(new ApiClientError({ code: "server_error", message: "读取失败" }, 500))
    .mockResolvedValueOnce({ items: [confirmedDocument], truncated: true })
  const create = vi.fn()
  mocks.apiRequest.mockImplementation(async (url: string, init?: { method?: string; body?: unknown }) => {
    if (url.endsWith("type=document")) return readDocuments()
    if (init?.method === "POST") return create(init.body)
    return mockGet(url)
  })
  renderPanel()
  fireEvent.click(await screen.findByRole("button", { name: "新建交付包" }))
  fireEvent.click(await screen.findByRole("checkbox"))
  fireEvent.click(screen.getByRole("button", { name: "文档版本" }))
  expect(await screen.findByText(/候选读取失败，已保留勾选/)).toBeVisible()
  expect(screen.queryByText(/暂无已确认/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "重试读取候选" }))
  expect(await screen.findByText(/候选仅显示部分结果/)).toBeVisible()
  fireEvent.click(screen.getByRole("checkbox"))
  fireEvent.click(screen.getByRole("button", { name: "创建草稿包" }))
  expect(create).toHaveBeenCalledWith(expect.objectContaining({ items: [
    { artifact_id: "art-1", display_name: "change.diff" }, { document_version_id: "docv-1" },
  ] }))
})
