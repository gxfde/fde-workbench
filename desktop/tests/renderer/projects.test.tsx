// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { App } from "../../src/renderer/src/App"
import type { ApiResponse, BridgeResult } from "../../src/shared/contracts"
import type { PageDto, ProjectDto } from "../../src/renderer/src/workbench/types"
import {
  adminUser,
  authResult,
  bridge,
  deferred,
  installBridge,
  ok,
  renderApp,
} from "./test-utils"

const project: ProjectDto = {
  id: "project-xinghe",
  project_code: "XH-001",
  name: "星河 PoV",
  enterprise_name: "星河制造",
  contact_name: "林总",
  contact_phone: "13800000000",
  address: "示例地址",
  background: "验证质检场景",
  notes: "",
  status: "active",
  planned_start_date: "2026-08-21",
  planned_end_date: "2026-09-10",
  leader_user_id: "leader-wang",
  leader: { id: "leader-wang", display_name: "项目负责人王工", role: "project_lead" },
  template_version_id: "template-v1",
  industry: "通用",
  completion: 55,
  version: 1,
  created_at: "2026-08-21T08:00:00+00:00",
  updated_at: "2026-08-21T09:00:00+00:00",
  modules: [
    {
      id: "project-module-pre",
      module_key: "pre_diagnosis",
      name: "预诊断",
      description: "",
      status: "active",
      sort_order: 10,
      planned_start_date: "2026-08-21",
      planned_end_date: "2026-08-22",
    },
    {
      id: "project-module-pov",
      module_key: "pov",
      name: "PoV",
      description: "",
      status: "active",
      sort_order: 20,
      planned_start_date: "2026-08-25",
      planned_end_date: "2026-09-10",
    },
  ],
}

beforeEach(() => {
  location.hash = "#projects"
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  location.hash = ""
})

function apiOk<T>(data: T, status = 200): BridgeResult<ApiResponse<T>> {
  return ok({ status, data, error: null })
}

function projectPage(
  items: ProjectDto[],
  page = 1,
  pageSize = 20,
  total = items.length,
): BridgeResult<ApiResponse<PageDto<ProjectDto>>> {
  return apiOk({ items, page, page_size: pageSize, total })
}

function renderProjects(apiRequest: ReturnType<typeof vi.fn>): void {
  installBridge(bridge({
    refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
    apiRequest,
  }))
  renderApp(<App />)
}

function projectListApi(
  listResponse: BridgeResult<ApiResponse<PageDto<ProjectDto>>> = projectPage([project]),
  facetItems: ProjectDto[] = [project],
): ReturnType<typeof vi.fn> {
  return vi.fn((path: string) => Promise.resolve(
    path === "/api/v1/projects?page=1&page_size=100"
      ? projectPage(facetItems, 1, 100, facetItems.length)
      : listResponse,
  ))
}

describe("项目列表", () => {
  it("按项目或企业、状态、负责人、行业和模块使用稳定顺序的查询参数筛选", async () => {
    const apiRequest = projectListApi()
    renderProjects(apiRequest)
    const user = userEvent.setup()

    await screen.findByRole("article", { name: /星河 PoV/ })
    await user.type(screen.getByLabelText("搜索项目或企业"), "星河")
    await user.selectOptions(screen.getByLabelText("项目状态"), "active")
    await user.selectOptions(screen.getByLabelText("项目负责人"), "leader-wang")
    await user.selectOptions(screen.getByLabelText("行业"), "通用")
    await user.selectOptions(screen.getByLabelText("模块"), "pov")
    await user.click(screen.getByRole("button", { name: "筛选" }))

    expect(apiRequest).toHaveBeenLastCalledWith(
      "/api/v1/projects?search=%E6%98%9F%E6%B2%B3&status=active&leader_user_id=leader-wang&industry=%E9%80%9A%E7%94%A8&module_key=pov&page=1&page_size=20",
      expect.objectContaining({ method: "GET" }),
    )
  })

  it("展示项目状态、负责人、模块、完成度和详情链接", async () => {
    const apiRequest = projectListApi()
    renderProjects(apiRequest)

    const card = await screen.findByRole("article", { name: /星河 PoV/ })
    expect(within(card).getByText("进行中")).toBeVisible()
    expect(within(card).getByText("项目负责人王工")).toBeVisible()
    expect(within(card).getByText("预诊断")).toBeVisible()
    expect(within(card).getByText("PoV")).toBeVisible()
    expect(within(card).getByText("55%")).toBeVisible()
    expect(within(card).getByRole("link", { name: "进入项目：星河 PoV" })).toHaveAttribute(
      "href",
      "#projects/project-xinghe",
    )
  })

  it("分别呈现加载、空列表和服务错误", async () => {
    const pending = deferred<BridgeResult<ApiResponse<PageDto<ProjectDto>>>>()
    const apiRequest = vi.fn((path: string) => (
      path === "/api/v1/projects?page=1&page_size=100"
        ? Promise.resolve(projectPage([], 1, 100, 0))
        : pending.promise
    ))
    renderProjects(apiRequest)

    expect(await screen.findByText("正在加载项目…")).toBeVisible()
    pending.resolve(projectPage([]))
    expect(await screen.findByText("暂无符合条件的项目。")).toBeVisible()

    cleanup()
    installBridge(bridge({
      refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
      apiRequest: vi.fn((path: string) => path === "/api/v1/projects?page=1&page_size=100"
        ? Promise.resolve(projectPage([], 1, 100, 0))
        : Promise.resolve(ok({
          status: 503,
          data: null,
          error: { code: "project_list_failed", message: "failed" },
        }))),
    }))
    renderApp(<App />)
    expect(await screen.findByRole("alert")).toHaveTextContent("项目加载失败")
  })

  it("翻页时保留已应用的筛选条件并发送对应 page", async () => {
    const apiRequest = vi.fn((path: string) => {
      if (path === "/api/v1/projects?page=1&page_size=100") return Promise.resolve(projectPage([project], 1, 100, 1))
      if (path.includes("page=2")) return Promise.resolve(projectPage([], 2, 20, 21))
      return Promise.resolve(projectPage([project], 1, 20, 21))
    })
    renderProjects(apiRequest)
    const user = userEvent.setup()

    await screen.findByRole("article", { name: /星河 PoV/ })
    await user.type(screen.getByLabelText("搜索项目或企业"), "星河")
    await user.click(screen.getByRole("button", { name: "筛选" }))
    await user.click(await screen.findByRole("button", { name: "下一页" }))

    await waitFor(() => expect(apiRequest).toHaveBeenLastCalledWith(
      "/api/v1/projects?search=%E6%98%9F%E6%B2%B3&page=2&page_size=20",
      expect.objectContaining({ method: "GET" }),
    ))
    expect(screen.getByText("第 2 / 2 页")).toBeVisible()
  })

  it("从独立全量分页来源加载 facets，首页可直接选择仅存在第二页的值", async () => {
    const firstFacetPage = Array.from({ length: 100 }, (_, index): ProjectDto => ({
      ...project,
      id: `facet-project-${index + 1}`,
      name: `项目 ${index + 1}`,
    }))
    const secondPageProject: ProjectDto = {
      ...project,
      id: "facet-page-two",
      leader_user_id: "leader-page-two",
      leader: { ...project.leader, id: "leader-page-two", display_name: "第二页负责人" },
      industry: "第二页行业",
      modules: [{ ...project.modules[0], id: "module-page-two", module_key: "page_two", name: "第二页模块" }],
    }
    const apiRequest = vi.fn((path: string) => {
      if (path === "/api/v1/projects?page=1&page_size=20") return Promise.resolve(projectPage([project]))
      if (path === "/api/v1/projects?page=1&page_size=100") return Promise.resolve(projectPage(firstFacetPage, 1, 100, 101))
      if (path === "/api/v1/projects?page=2&page_size=100") return Promise.resolve(projectPage([secondPageProject], 2, 100, 101))
      if (path.includes("leader_user_id=leader-page-two")) return Promise.resolve(projectPage([secondPageProject]))
      throw new Error(`Unexpected API path: ${path}`)
    })
    renderProjects(apiRequest)
    const user = userEvent.setup()

    await screen.findByRole("article", { name: /星河 PoV/ })
    await user.selectOptions(await screen.findByLabelText("项目负责人"), "leader-page-two")
    await user.selectOptions(screen.getByLabelText("行业"), "第二页行业")
    await user.selectOptions(screen.getByLabelText("模块"), "page_two")
    await user.click(screen.getByRole("button", { name: "筛选" }))

    expect(apiRequest).toHaveBeenLastCalledWith(
      "/api/v1/projects?leader_user_id=leader-page-two&industry=%E7%AC%AC%E4%BA%8C%E9%A1%B5%E8%A1%8C%E4%B8%9A&module_key=page_two&page=1&page_size=20",
      expect.objectContaining({ method: "GET" }),
    )
  })

  it("拒绝错页、错页大小、负 total 和缺少必要字段的列表响应", async () => {
    const invalidResponses: unknown[] = [
      { items: [project], page: 2, page_size: 20, total: 1 },
      { items: [project], page: 1, page_size: 10, total: 1 },
      { items: [project], page: 1, page_size: 20, total: -1 },
      { items: [{ ...project, leader: undefined }], page: 1, page_size: 20, total: 1 },
    ]
    for (const invalid of invalidResponses) {
      const apiRequest = vi.fn((path: string) => {
        if (path.endsWith("page_size=100")) return Promise.resolve(projectPage([] as ProjectDto[], 1, 100, 0))
        return Promise.resolve(apiOk(invalid))
      })
      renderProjects(apiRequest)
      expect(await screen.findByRole("alert")).toHaveTextContent("项目加载失败")
      cleanup()
    }
  })

  it("facet 第二页行结构异常时不提交部分选项", async () => {
    const apiRequest = vi.fn((path: string) => {
      if (path === "/api/v1/projects?page=1&page_size=20") return Promise.resolve(projectPage([project]))
      if (path === "/api/v1/projects?page=1&page_size=100") return Promise.resolve(projectPage(
        Array.from({ length: 100 }, (_, index) => ({ ...project, id: `facet-${index}` })),
        1,
        100,
        101,
      ))
      if (path === "/api/v1/projects?page=2&page_size=100") return Promise.resolve(apiOk({
        items: [{ ...project, id: "broken", modules: undefined }],
        page: 2,
        page_size: 100,
        total: 101,
      }))
      throw new Error(`Unexpected API path: ${path}`)
    })
    renderProjects(apiRequest)

    expect(await screen.findByRole("alert")).toHaveTextContent("筛选项加载失败")
    expect(screen.queryByRole("option", { name: "通用" })).not.toBeInTheDocument()
  })
})
