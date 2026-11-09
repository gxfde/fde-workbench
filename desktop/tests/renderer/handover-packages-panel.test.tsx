// @vitest-environment jsdom
// T-B1 封包半桌面面（goal-tb tb4）：结项交付包面板。
// 钉住：双列表加载与空态 / 创建 POST 形状（勾选→items）/ 状态动作显隐
// （canManage 封存解封、isAdmin 交付登记）/ 详情清单与 manifest 呈现。
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

function mockGet(url: string): unknown {
  if (url.startsWith("/api/v1/handover-packages?")) {
    return { items: [draftPackage], total: null, limit: 50, offset: 0, truncated: false }
  }
  if (url.startsWith("/api/v1/handover-packages/artifacts?")) {
    return { items: [reviewedArtifact], truncated: false }
  }
  if (url === `/api/v1/handover-packages/${draftPackage.id}`) {
    return {
      ...draftPackage,
      items: [
        { id: "item-1", item_type: "artifact", artifact_id: "art-1", run_id: "run-1", kind: "diff", display_name: "change.diff", storage_ref: "run-1/output/change.diff", sha256: "b".repeat(64) },
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

it("加载包列表与挑选面并呈现指针纪律注记", async () => {
  renderPanel()
  expect(await screen.findByRole("heading", { name: "结项交付包" })).toBeInTheDocument()
  expect(screen.getByText("草稿")).toBeInTheDocument()
  expect(screen.getByText(/清单=已复核产物指针\+sha256 快照/)).toBeInTheDocument()
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

it("详情展开：清单表+草稿无 manifest 注记", async () => {
  renderPanel()
  fireEvent.click(await screen.findByText("清单"))
  expect(await screen.findByText("change.diff")).toBeInTheDocument()
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
