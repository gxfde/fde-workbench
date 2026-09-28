// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { App } from "../../src/renderer/src/App"
import type { ApiResponse, BridgeResult, UserDto } from "../../src/shared/contracts"
import type {
  PageDto,
  ProjectDto,
  TemplateVersionDto,
  WorkbenchUserDto,
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

const templateV1: TemplateVersionDto = {
  template_id: "template-generic",
  template_name: "通用企业 AI 落地模板",
  industry_name: "通用",
  description: "从预诊断到 PoV。",
  version_id: "template-v1",
  version_number: 1,
  status: "published",
  version: 2,
  published_by_user_id: "admin-id",
  published_at: "2026-08-21T08:00:00+00:00",
  modules: [
    {
      id: "template-module-pre",
      module_catalog_id: "catalog-pre",
      module_key: "pre_diagnosis",
      name: "预诊断",
      description: "确定高价值场景。",
      sort_order: 10,
      tasks: [{
        id: "task-interview",
        task_key: "interview",
        name: "岗位访谈",
        description: "",
        duration_days: 2,
        default_assignee_role: "project_lead",
        sort_order: 10,
        dependency_keys: [],
      }],
    },
    {
      id: "template-module-pov",
      module_catalog_id: "catalog-pov",
      module_key: "pov",
      name: "PoV",
      description: "验证业务价值。",
      sort_order: 20,
      tasks: [{
        id: "task-validate",
        task_key: "validate_scene",
        name: "场景验证",
        description: "",
        duration_days: 3,
        default_assignee_role: "fde_engineer",
        sort_order: 10,
        dependency_keys: ["interview"],
      }],
    },
  ],
}

const templateV2: TemplateVersionDto = {
  ...templateV1,
  version_id: "template-v2",
  version_number: 2,
  version: 1,
  published_at: "2026-08-21T09:00:00+00:00",
}

const leader: WorkbenchUserDto = {
  id: "leader-wang",
  username: "lead.wang",
  display_name: "项目负责人王工",
  role: "project_lead",
  is_active: true,
  must_change_password: false,
  created_at: "2026-08-20T08:00:00+00:00",
  updated_at: "2026-08-20T08:00:00+00:00",
}

const apiAdmin: WorkbenchUserDto = {
  ...leader,
  id: adminUser.id,
  username: adminUser.username,
  display_name: adminUser.displayName,
  role: "admin",
}

beforeEach(() => {
  location.hash = "#projects/new"
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  location.hash = ""
})

function apiOk<T>(data: T, status = 200): BridgeResult<ApiResponse<T>> {
  return ok({ status, data, error: null })
}

function page<T>(items: T[], pageNumber = 1, pageSize = 100, total = items.length): PageDto<T> {
  return { items, page: pageNumber, page_size: pageSize, total }
}

function createdProject(): ProjectDto {
  return {
    id: "created-project",
    project_code: "XH-POV-001",
    name: "星河 PoV",
    enterprise_name: "星河制造",
    contact_name: "林总",
    contact_phone: "13800000000",
    address: "示例地址",
    background: "验证质检场景",
    notes: "周五例会",
    status: "draft",
    planned_start_date: "2026-08-21",
    planned_end_date: "2026-10-31",
    leader_user_id: leader.id,
    leader: { id: leader.id, display_name: leader.display_name, role: leader.role },
    template_version_id: templateV2.version_id,
    industry: "通用",
    completion: 0,
    version: 1,
    created_at: "2026-08-21T10:00:00+00:00",
    updated_at: "2026-08-21T10:00:00+00:00",
    modules: [],
  }
}

function defaultApi(path: string, options?: { method?: string }): Promise<BridgeResult<ApiResponse<unknown>>> {
  if (path === "/api/v1/industry-templates?page=1&page_size=100") {
    return Promise.resolve(apiOk(page([templateV1, templateV2])))
  }
  if (path === `/api/v1/industry-templates/versions/${templateV2.version_id}`) {
    return Promise.resolve(apiOk(templateV2))
  }
  if (path === `/api/v1/industry-templates/versions/${templateV1.version_id}`) {
    return Promise.resolve(apiOk(templateV1))
  }
  if (path === "/api/v1/users?role=admin&active=true&page=1&page_size=100") {
    return Promise.resolve(apiOk(page([apiAdmin])))
  }
  if (path === "/api/v1/users?role=project_lead&active=true&page=1&page_size=100") {
    return Promise.resolve(apiOk(page([leader])))
  }
  if (path === "/api/v1/projects" && options?.method === "POST") {
    return Promise.resolve(apiOk(createdProject(), 201))
  }
  throw new Error(`Unexpected API path: ${path}`)
}

function renderNewProject(
  apiRequest: ReturnType<typeof vi.fn>,
  currentUser: UserDto = adminUser,
  strict = false,
): void {
  installBridge(bridge({
    refresh: vi.fn().mockResolvedValue(ok(authResult(currentUser))),
    apiRequest,
  }))
  renderApp(strict ? <React.StrictMode><App /></React.StrictMode> : <App />)
}

async function completeBasics(user: ReturnType<typeof userEvent.setup>, mode = "从模板新建"): Promise<void> {
  await screen.findByRole("heading", { name: "新建项目" })
  await user.click(screen.getByRole("button", { name: new RegExp(mode) }))
  await user.type(screen.getByLabelText("项目名称"), "星河 PoV")
  await user.type(screen.getByLabelText("企业名称"), "星河制造")
  await user.type(screen.getByLabelText("项目编号"), "XH-POV-001")
  await user.type(screen.getByLabelText("联系人"), "林总")
  await user.type(screen.getByLabelText("联系电话"), "13800000000")
  await user.type(screen.getByLabelText("企业地址"), "示例地址")
  await user.type(screen.getByLabelText("项目背景"), "验证质检场景")
  await user.type(screen.getByLabelText("备注"), "周五例会")
  await user.type(screen.getByLabelText("计划开始日期"), "2026-08-21")
  await user.type(screen.getByLabelText("计划结束日期"), "2026-10-31")
  await user.click(screen.getByRole("button", { name: "下一步" }))
}

describe("四步项目创建向导", () => {
  it("先显示三种新建入口，不提前加载无关资料", async () => {
    const apiRequest = vi.fn(defaultApi)
    renderNewProject(apiRequest)
    expect(await screen.findByRole("button", { name: /从模板新建/ })).toBeVisible()
    expect(screen.getByRole("button", { name: /上传预调研表新建/ })).toBeVisible()
    expect(screen.getByRole("button", { name: /手动新建/ })).toBeVisible()
    expect(apiRequest).not.toHaveBeenCalled()
  })

  it("手动新建不读取行业模板，快速重复点击仅创建一次并保留自定义快照", async () => {
    const pending = deferred<BridgeResult<ApiResponse<ProjectDto>>>()
    const apiRequest = vi.fn((path: string, options?: { method?: string }) => {
      if (path.startsWith("/api/v1/modules?")) return Promise.resolve(apiOk(page([{ id: "catalog-pre", key: "pre_diagnosis", name: "预诊断", description: "确定场景", sort_order: 1, is_active: true, version: 1 }])))
      if (path === "/api/v1/projects" && options?.method === "POST") return pending.promise
      return defaultApi(path, options)
    })
    vi.spyOn(window, "confirm").mockReturnValue(false)
    renderNewProject(apiRequest, adminUser, true)
    const user = userEvent.setup()
    await completeBasics(user, "手动新建")
    expect(screen.queryByLabelText("行业模板版本")).not.toBeInTheDocument()
    await user.selectOptions(await screen.findByLabelText("负责人"), leader.id)
    await user.click(screen.getByRole("button", { name: "下一步" }))
    await user.click(await screen.findByRole("checkbox", { name: "预诊断" }))
    await user.click(screen.getByRole("button", { name: "下一步" }))
    await user.dblClick(screen.getByRole("button", { name: "创建项目" }))
    expect(postCalls(apiRequest)).toHaveLength(1)
    expect(apiRequest.mock.calls.some(([path]) => path.startsWith("/api/v1/industry-templates"))).toBe(false)
    expect(apiRequest).toHaveBeenCalledWith("/api/v1/projects", expect.objectContaining({ body: expect.objectContaining({
      creation_source: "manual", template_version_id: null, module_keys: ["pre_diagnosis"],
      project_snapshot: expect.objectContaining({ modules: [expect.objectContaining({ module_key: "pre_diagnosis" })] }),
    }) }))
    pending.resolve(apiOk({ ...createdProject(), template_version_id: null }, 201))
    await waitFor(() => expect(location.hash).toBe("#projects/created-project"))
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("另存为新的行业模板草稿"))
  })

  it("提交精确的企业、模板、负责人、日期、可选资料和模块 payload", async () => {
    const apiRequest = vi.fn(defaultApi)
    renderNewProject(apiRequest)
    const user = userEvent.setup()

    await completeBasics(user)
    await user.selectOptions(await screen.findByLabelText("行业模板版本"), templateV2.version_id)
    await user.selectOptions(screen.getByLabelText("项目负责人"), leader.id)
    await user.click(screen.getByRole("button", { name: "下一步" }))
    await user.click(await screen.findByRole("checkbox", { name: "PoV" }))

    expect(screen.getByRole("checkbox", { name: "预诊断" })).toBeChecked()
    expect(screen.getByText(/PoV 需要前置模块/)).toBeVisible()
    await user.click(screen.getByRole("button", { name: "下一步" }))

    const review = await screen.findByRole("region", { name: "创建摘要" })
    expect(within(review).getByText("星河制造")).toBeVisible()
    expect(within(review).getByText("通用企业 AI 落地模板 v2")).toBeVisible()
    expect(within(review).getByText("项目负责人王工")).toBeVisible()
    expect(within(review).getByText("预诊断、PoV")).toBeVisible()
    expect(within(review).getByText("岗位访谈、场景验证")).toBeVisible()
    expect(within(review).getByText("2026-08-21 至 2026-10-31")).toBeVisible()

    await user.click(screen.getByRole("button", { name: "创建项目" }))

    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("/api/v1/projects", expect.objectContaining({
      method: "POST",
      body: {
        name: "星河 PoV",
        enterprise_name: "星河制造",
        contact_name: "林总",
        contact_phone: "13800000000",
        address: "示例地址",
        background: "验证质检场景",
        notes: "周五例会",
        project_code: "XH-POV-001",
        planned_start_date: "2026-08-21",
        planned_end_date: "2026-10-31",
        template_version_id: "template-v2",
        leader_user_id: "leader-wang",
        module_keys: ["pre_diagnosis", "pov"],
      },
    })))
    expect(location.hash).toBe("#projects/created-project")
  })

  it("项目名称、企业名称和开始日期缺失时不允许进入下一步", async () => {
    const apiRequest = vi.fn(defaultApi)
    renderNewProject(apiRequest)
    const user = userEvent.setup()

    await screen.findByRole("heading", { name: "新建项目" })
    await user.click(screen.getByRole("button", { name: /从模板新建/ }))
    await user.click(screen.getByRole("button", { name: "下一步" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("请填写项目名称、企业名称和计划开始日期")
    expect(screen.getByRole("heading", { name: "1. 基础信息" })).toBeVisible()
  })

  it("管理员完整分页加载两类可用负责人，项目负责人账号固定为自己且不调用用户 API", async () => {
    const secondLead = { ...leader, id: "leader-second", display_name: "第二位负责人" }
    const firstPageLeaders = Array.from({ length: 100 }, (_, index) => ({
      ...leader,
      id: `leader-page-one-${index}`,
      username: `leader-page-one-${index}`,
      display_name: `首页负责人 ${index}`,
    }))
    const adminApi = vi.fn((path: string, options?: { method?: string }) => {
      if (path === "/api/v1/users?role=project_lead&active=true&page=1&page_size=100") {
        return Promise.resolve(apiOk(page(firstPageLeaders, 1, 100, 101)))
      }
      if (path === "/api/v1/users?role=project_lead&active=true&page=2&page_size=100") {
        return Promise.resolve(apiOk(page([secondLead], 2, 100, 101)))
      }
      return defaultApi(path, options)
    })
    renderNewProject(adminApi)
    const user = userEvent.setup()
    await completeBasics(user)

    const leaders = await screen.findByLabelText("项目负责人")
    expect(within(leaders).getByRole("option", { name: "第二位负责人" })).toBeVisible()

    cleanup()
    location.hash = "#projects/new"
    const leadUser: UserDto = {
      id: leader.id,
      username: leader.username,
      displayName: leader.display_name,
      role: "project_lead",
      mustChangePassword: false,
      isActive: true,
    }
    const leadApi = vi.fn(defaultApi)
    renderNewProject(leadApi, leadUser)
    await screen.findByRole("heading", { name: "新建项目" })
    await user.click(screen.getByRole("button", { name: /从模板新建/ }))
    await waitFor(() => expect(leadApi).toHaveBeenCalledWith(
      "/api/v1/industry-templates?page=1&page_size=100",
      expect.objectContaining({ method: "GET" }),
    ))
    expect(leadApi.mock.calls.some(([path]) => String(path).startsWith("/api/v1/users"))).toBe(false)
  })

  it("模板列表读取完整分页，仅显示已发布版本并默认最新版本", async () => {
    const draft = { ...templateV1, version_id: "draft-v3", version_number: 3, status: "draft" as const }
    const inactive = { ...templateV1, version_id: "inactive-v4", version_number: 4, status: "inactive" as const }
    const firstPageTemplates = [draft, inactive, ...Array.from({ length: 98 }, (_, index) => ({
      ...inactive,
      version_id: `inactive-filler-${index}`,
      version_number: index + 5,
    }))]
    const apiRequest = vi.fn((path: string, options?: { method?: string }) => {
      if (path === "/api/v1/industry-templates?page=1&page_size=100") {
        return Promise.resolve(apiOk(page(firstPageTemplates, 1, 100, 101)))
      }
      if (path === "/api/v1/industry-templates?page=2&page_size=100") {
        return Promise.resolve(apiOk(page([templateV2], 2, 100, 101)))
      }
      return defaultApi(path, options)
    })
    renderNewProject(apiRequest)
    const user = userEvent.setup()
    await completeBasics(user)

    const select = await screen.findByLabelText("行业模板版本")
    expect(select).toHaveValue(templateV2.version_id)
    expect(within(select).getByRole("option", { name: "通用企业 AI 落地模板 v2" })).toBeVisible()
    expect(within(select).queryByRole("option", { name: /v3/ })).not.toBeInTheDocument()
    expect(within(select).queryByRole("option", { name: /v4/ })).not.toBeInTheDocument()
  })

  it("创建失败后保留四步全部输入与选择", async () => {
    const apiRequest = vi.fn((path: string, options?: { method?: string }) => {
      if (path === "/api/v1/projects" && options?.method === "POST") {
        return Promise.resolve(ok({
          status: 409,
          data: null,
          error: { code: "project_conflict", message: "conflict" },
        }))
      }
      return defaultApi(path, options)
    })
    renderNewProject(apiRequest)
    const user = userEvent.setup()

    await completeBasics(user)
    await user.selectOptions(await screen.findByLabelText("项目负责人"), leader.id)
    await user.click(screen.getByRole("button", { name: "下一步" }))
    await user.click(await screen.findByRole("checkbox", { name: "PoV" }))
    await user.click(screen.getByRole("button", { name: "下一步" }))
    await user.click(screen.getByRole("button", { name: "创建项目" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("项目创建失败")
    await user.click(screen.getByRole("button", { name: "上一步" }))
    expect(screen.getByRole("checkbox", { name: "PoV" })).toBeChecked()
    await user.click(screen.getByRole("button", { name: "上一步" }))
    expect(screen.getByLabelText("项目负责人")).toHaveValue(leader.id)
    await user.click(screen.getByRole("button", { name: "上一步" }))
    expect(screen.getByLabelText("项目名称")).toHaveValue("星河 PoV")
    expect(screen.getByLabelText("项目背景")).toHaveValue("验证质检场景")
  })

  it("StrictMode 中创建请求只发送一次并在成功响应后跳转", async () => {
    const pending = deferred<BridgeResult<ApiResponse<ProjectDto>>>()
    const apiRequest = vi.fn((path: string, options?: { method?: string }) => {
      if (path === "/api/v1/projects" && options?.method === "POST") return pending.promise
      return defaultApi(path, options)
    })
    renderNewProject(apiRequest, adminUser, true)
    const user = userEvent.setup()

    await advanceToReview(user)
    const create = screen.getByRole("button", { name: "创建项目" })
    await user.dblClick(create)
    expect(postCalls(apiRequest)).toHaveLength(1)
    expect(create).toBeDisabled()

    pending.resolve(apiOk(createdProject(), 201))
    await waitFor(() => expect(location.hash).toBe("#projects/created-project"))
    expect(postCalls(apiRequest)).toHaveLength(1)
  })

  it("StrictMode 中创建失败会恢复可提交状态，重试仅增加一次 POST", async () => {
    let attempts = 0
    const apiRequest = vi.fn((path: string, options?: { method?: string }) => {
      if (path === "/api/v1/projects" && options?.method === "POST") {
        attempts += 1
        return Promise.resolve(attempts === 1
          ? ok({ status: 503, data: null, error: { code: "project_creation_failed", message: "failed" } })
          : apiOk(createdProject(), 201))
      }
      return defaultApi(path, options)
    })
    renderNewProject(apiRequest, adminUser, true)
    const user = userEvent.setup()

    await advanceToReview(user)
    await user.click(screen.getByRole("button", { name: "创建项目" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("项目创建失败")
    const retry = screen.getByRole("button", { name: "创建项目" })
    expect(retry).toBeEnabled()
    expect(postCalls(apiRequest)).toHaveLength(1)

    await user.click(retry)
    await waitFor(() => expect(location.hash).toBe("#projects/created-project"))
    expect(postCalls(apiRequest)).toHaveLength(2)
  })

  it("拒绝错页大小的模板或负责人分页响应", async () => {
    const apiRequest = vi.fn((path: string, options?: { method?: string }) => {
      if (path === "/api/v1/users?role=project_lead&active=true&page=1&page_size=100") {
        return Promise.resolve(apiOk(page([leader], 1, 1, 1)))
      }
      return defaultApi(path, options)
    })
    renderNewProject(apiRequest)
    const user = userEvent.setup()
    await completeBasics(user)

    expect(await screen.findByRole("alert")).toHaveTextContent("模板或负责人分页数据不完整")
    expect(screen.getByLabelText("项目负责人")).not.toContainElement(
      screen.queryByRole("option", { name: "项目负责人王工" }),
    )
  })

  it("拒绝缺少必要字段的已发布模板行", async () => {
    const apiRequest = vi.fn((path: string, options?: { method?: string }) => {
      if (path === "/api/v1/industry-templates?page=1&page_size=100") {
        return Promise.resolve(apiOk(page([{ ...templateV2, modules: undefined }])))
      }
      return defaultApi(path, options)
    })
    renderNewProject(apiRequest)
    const user = userEvent.setup()
    await completeBasics(user)

    expect(await screen.findByRole("alert")).toHaveTextContent("模板或负责人分页数据不完整")
    expect(screen.getByLabelText("行业模板版本")).toHaveValue("")
  })
})

async function advanceToReview(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await completeBasics(user)
  await user.selectOptions(await screen.findByLabelText("项目负责人"), leader.id)
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await user.click(await screen.findByRole("checkbox", { name: "预诊断" }))
  await user.click(screen.getByRole("button", { name: "下一步" }))
  await screen.findByRole("region", { name: "创建摘要" })
}

function postCalls(apiRequest: ReturnType<typeof vi.fn>): unknown[][] {
  return apiRequest.mock.calls.filter(([path, options]) => path === "/api/v1/projects" && options?.method === "POST")
}
