// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { App } from "../../src/renderer/src/App"
import { createApiRequestHandler } from "../../src/main/api-ipc"
import { createApiClient } from "../../src/renderer/src/api/client"
import { AuthProvider } from "../../src/renderer/src/auth/AuthProvider"
import { DangerConfirmProvider } from "../../src/renderer/src/common/DangerConfirmProvider"
import { ProjectModules } from "../../src/renderer/src/projects/ProjectModules"
import type { ApiResponse, BridgeResult, UserDto } from "../../src/shared/contracts"
import type { ProjectDto, ProjectTaskDto } from "../../src/renderer/src/workbench/types"
import type { GuidanceAnalysisDto } from "../../src/renderer/src/guidance/types"
import { GuidanceReview } from "../../src/renderer/src/guidance/GuidanceReview"
import { authResult, bridge, engineerUser, installBridge, ok, renderApp } from "./test-utils"

const projectId = "project-xinghe"
const engineerId = engineerUser.id

const task: ProjectTaskDto = {
  id: "task-prepare",
  project_module_id: "project-module-pov",
  module_key: "pov",
  task_key: "prepare_data",
  name: "准备数据",
  description: "整理验证数据",
  status: "in_progress",
  planned_start_date: "2026-08-21",
  planned_end_date: "2026-08-24",
  duration_days: 2,
  default_assignee_role: "fde_engineer",
  assignee_user_id: null,
  pending_assignment: true,
  progress: 20,
  blocked_reason: "",
  completed_at: null,
  sort_order: 1,
  collaborator_user_ids: [engineerId],
  dependency_ids: [],
  dependency_keys: [],
  dependency_risk: false,
  incomplete_dependency_ids: [],
  version: 3,
}

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
  modules: [{
    id: "project-module-pov",
    module_key: "pov",
    name: "PoV 验证",
    description: "验证价值",
    status: "active",
    sort_order: 1,
    planned_start_date: "2026-08-21",
    planned_end_date: "2026-08-24",
  }],
  tasks: [task],
  members: [{
    id: "membership-engineer",
    user_id: engineerId,
    display_name: "李工程师",
    system_role: "fde_engineer",
    role: "member",
  }],
  template_snapshot: {
    template_id: "template-1",
    template_name: "制造业模板",
    industry_name: "制造业",
    description: "",
    version_id: "template-v1",
    version_number: 1,
    modules: [{
      id: "template-module-pov",
      module_catalog_id: "catalog-pov",
      module_key: "pov",
      name: "PoV 验证",
      description: "验证价值",
      sort_order: 1,
      tasks: [],
    }, {
      id: "template-module-launch",
      module_catalog_id: "catalog-launch",
      module_key: "launch",
      name: "上线与移交",
      description: "生产上线",
      sort_order: 2,
      tasks: [],
    }],
  },
}

const guidanceItem = { text: "减少重复录入", classification: "customer_stated" as const, source_refs: ["p1"], confirmed: true }
const confirmedGuidance: GuidanceAnalysisDto = {
  id: "guidance-v1", project_id: projectId, version_number: 1, source_file_id: "file-1", source_file_version_id: "file-version-1",
  source_filename: "预调研表.docx", status: "confirmed", analysis_state: "ready", customer_vision: "建设人工智能工厂",
  current_phase_objective: "完成进场前诊断", executive_summary: "围绕客户目标推进诊断。", key_business_problems: [guidanceItem],
  priority_departments: [], priority_roles: [], priority_processes: [], success_criteria: [], out_of_scope: [],
  data_security_redlines: [], systems_and_deployment_constraints: [], assumptions: [], open_questions: [], next_actions: [],
  failure_code: "", failure_message: "", source_is_stale: false, version: 2,
}

afterEach(() => {
  cleanup()
  location.hash = ""
  vi.restoreAllMocks()
})

describe("project detail workspace", () => {
  it("opens a newly generated guidance draft directly in edit mode", async () => {
    installBridge(bridge())
    renderApp(<AuthProvider><GuidanceReview projectId={projectId} initial={{ ...confirmedGuidance, status: "draft" }} canManage initialEditing onClose={() => undefined} onSaved={() => undefined} /></AuthProvider>)

    expect(await screen.findByLabelText("客户长期愿景")).toHaveValue("建设人工智能工厂")
    expect(screen.getByRole("button", { name: "确认并用于项目指引" })).toBeVisible()
  })

  it("shows project-level delivery documents alongside research and library", async () => {
    renderProjectDetail({ role: "viewer", tab: "overview" })

    await screen.findByRole("heading", { name: "企业与项目信息" })
    expect(screen.getAllByRole("tab").map((item) => item.textContent)).toEqual([
      "概览",
      "任务",
      "调研",
      "方案设计",
      "文件库",
      "项目管理",
    ])
  })

  it("submits project plan export from the page header", async () => {
    const apiRequest = renderProjectDetail({ role: "project_lead", tab: "overview" })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "导出项目计划及进度" }))

    await screen.findByText("项目计划及进度已提交生成，完成后会自动进入文件库并保留为新版本。")
    expect(apiRequest).toHaveBeenCalledWith(`/api/v1/projects/${projectId}/documents`, expect.objectContaining({
      method: "POST", body: { document_type: "project_plan_progress", expected_version: 5 },
    }))
    expect(apiRequest).toHaveBeenCalledWith(`/api/v1/projects/${projectId}/documents/project-plan-document/generate`, expect.objectContaining({
      method: "POST", body: { version: 1 },
    }))
  })

  it("refreshes the project version immediately before exporting the project plan", async () => {
    let requestCount = 0
    const apiRequest = renderProjectDetail({
      role: "project_lead",
      tab: "overview",
      projectDetail: () => ({ ...project, version: ++requestCount === 1 ? 5 : 8 }),
    })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "导出项目计划及进度" }))

    await screen.findByText("项目计划及进度已提交生成，完成后会自动进入文件库并保留为新版本。")
    expect(apiRequest).toHaveBeenCalledWith(`/api/v1/projects/${projectId}/documents`, expect.objectContaining({
      method: "POST", body: { document_type: "project_plan_progress", expected_version: 8 },
    }))
  })

  it.each([
    ["document_template_not_published", "尚未发布“项目计划及进度”模板。请前往“文档模板”上传模板，并将该版本发布后再导出。"],
    ["template_version_not_published", "尚未发布“项目计划及进度”模板。请前往“文档模板”上传模板，并将该版本发布后再导出。"],
    ["unknown_document_type", "当前线上服务尚未支持“项目计划及进度”导出。请先更新服务端；更新后还需在“文档模板”中上传并发布对应模板。"],
  ])("explains project plan export prerequisite failures for %s", async (code, message) => {
    renderProjectDetail({ role: "project_lead", tab: "overview", documentPost: apiError(code, code === "unknown_document_type" ? 400 : 422) })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "导出项目计划及进度" }))

    expect(await screen.findByText(message)).toHaveAttribute("role", "alert")
  })

  it("leaves empty overview values blank", async () => {
    renderProjectDetail({
      role: "viewer",
      tab: "overview",
      rawProject: { ...project, contact_name: "", contact_phone: "", address: "", background: "", notes: "" },
    })

    const overview = (await screen.findByRole("heading", { name: "企业与项目信息" })).closest("section")
    expect(overview).not.toBeNull()
    expect(within(overview as HTMLElement).queryAllByText("—")).toHaveLength(0)
  })

  it("accepts a project created from an uploaded presurvey without template identifiers", async () => {
    renderProjectDetail({
      role: "viewer",
      tab: "overview",
      rawProject: {
        ...project,
        template_version_id: null,
        template_snapshot: {
          template_id: null,
          template_name: "非模板项目",
          industry_name: "电子制造服务(EMS)",
          description: "由预调研表生成",
          version_id: null,
          creation_source: "presurvey",
          modules: [{
            id: null,
            module_catalog_id: "catalog-pre",
            module_key: "pre_diagnosis",
            name: "预调研",
            description: "收集并确认信息",
            sort_order: 0,
            tasks: [{
              id: null,
              task_key: "pre_1",
              name: "预调研表收集与信息确认",
              description: "核对预调研信息",
              duration_days: 3,
              default_assignee_role: "project_lead",
              sort_order: 1,
              dependency_keys: [],
            }],
          }],
        },
      },
    })

    expect(await screen.findByRole("heading", { name: "企业与项目信息" })).toBeVisible()
    expect(screen.queryByText("项目详情加载失败，请稍后重试。")).not.toBeInTheDocument()
  })

  it("passes member-removal DELETE bodies through the desktop bridge and accepts an empty 204", async () => {
    const fetchStub = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    const request = createApiRequestHandler({ apiBaseUrl: "https://fde.test", fetch: fetchStub, timeoutMs: 1_000 })

    await expect(request({
      path: `/api/v1/projects/${projectId}/members/membership-engineer`,
      method: "DELETE",
      accessToken: "access-token",
      body: { version: 5 },
    })).resolves.toEqual({ status: 204, data: null, error: null })
    expect(fetchStub).toHaveBeenCalledWith(
      `https://fde.test/api/v1/projects/${projectId}/members/membership-engineer`,
      expect.objectContaining({ method: "DELETE", body: JSON.stringify({ version: 5 }) }),
    )
  })

  it("treats a successful 204 mutation as an empty renderer result", async () => {
    const snapshot = { generation: 1, userId: "admin", accessToken: "access-token" }
    const client = createApiClient({
      request: vi.fn().mockResolvedValue(ok({ status: 204, data: null, error: null })),
    }, {
      getSessionSnapshot: () => snapshot,
      refreshAccess: vi.fn(),
      onUnauthorized: vi.fn(),
    })

    await expect(client<void>(`/api/v1/projects/${projectId}/members/member`, {
      method: "DELETE",
      body: { version: 5 },
    })).resolves.toBeUndefined()
  })

  it("lets a collaborating engineer update progress but hides project management controls", async () => {
    const apiRequest = renderProjectDetail({ role: "fde_engineer", tab: "tasks" })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "更新任务：准备数据" }))
    await user.clear(screen.getByLabelText("进度"))
    await user.type(screen.getByLabelText("进度"), "40")
    await user.click(screen.getByRole("button", { name: "保存任务" }))

    await waitFor(() => expect(mutationBodies(apiRequest, "PATCH")).toContainEqual(expect.objectContaining({
      progress: 40,
      version: 3,
    })))
    expect(screen.queryByLabelText("计划开始日期")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "追加模块" })).not.toBeInTheDocument()
  })

  it("spaces the new-task action away from the task count", async () => {
    renderProjectDetail({ role: "project_lead", tab: "tasks" })

    const actions = (await screen.findByRole("button", { name: "新增任务" })).parentElement
    expect(actions).not.toBeNull()
    expect(getComputedStyle(actions as HTMLElement).gap).toBe("12px")
  })

  it("restores dependency controls when creating a task and submits selected predecessors", async () => {
    const apiRequest = renderProjectDetail({ role: "project_lead", tab: "tasks" })
    const user = userEvent.setup()

    expect(await screen.findByRole("list", { name: "项目任务" })).toBeVisible()
    await user.click(await screen.findByRole("button", { name: "新增任务" }))
    const predecessor = screen.getByRole("checkbox", { name: "前置任务：准备数据" })
    await user.click(predecessor)
    await user.type(screen.getByLabelText("任务名称"), "整理访谈资料")
    await user.click(screen.getByRole("button", { name: "创建任务" }))

    await waitFor(() => expect(mutationBodies(apiRequest, "POST")).toHaveLength(1))
    expect(mutationBodies(apiRequest, "POST")[0]).toEqual(expect.objectContaining({ dependency_ids: [task.id] }))
  })

  it("lets managers edit task predecessors", async () => {
    const dependent = { ...task, id: "task-dependent", task_key: "review_data", name: "复核数据", dependency_ids: [task.id], dependency_keys: [task.task_key] }
    const apiRequest = renderProjectDetail({ role: "project_lead", tab: "tasks", tasks: [task, dependent] })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "更新任务：复核数据" }))
    const predecessor = screen.getByRole("checkbox", { name: "前置任务：准备数据" })
    expect(predecessor).toBeChecked()
    expect(screen.queryByRole("checkbox", { name: "前置任务：复核数据" })).not.toBeInTheDocument()
    await user.click(predecessor)
    await user.click(screen.getByRole("button", { name: "保存任务" }))

    await waitFor(() => expect(mutationBodies(apiRequest, "PATCH")).toContainEqual(expect.objectContaining({ dependency_ids: [] })))
  })

  it("keeps planned dates and workday duration synchronized", async () => {
    const apiRequest = renderProjectDetail({ role: "project_lead", tab: "tasks" })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "更新任务：准备数据" }))
    await user.clear(screen.getByLabelText("计划结束日期"))
    await user.type(screen.getByLabelText("计划结束日期"), "2026-08-26")

    expect(screen.getByLabelText("工期（工作日）")).toHaveValue(4)

    await user.clear(screen.getByLabelText("工期（工作日）"))
    await user.type(screen.getByLabelText("工期（工作日）"), "3")
    expect(screen.getByLabelText("计划结束日期")).toHaveValue("2026-08-25")

    await user.click(screen.getByRole("button", { name: "保存任务" }))
    await waitFor(() => expect(mutationBodies(apiRequest, "PATCH")).toContainEqual(expect.objectContaining({
      planned_start_date: "2026-08-21",
      planned_end_date: "2026-08-25",
      duration_days: 3,
    })))
  })

  it("keeps an engineer with viewer project membership read-only even if an old task names them", async () => {
    renderProjectDetail({
      role: "fde_engineer",
      tab: "tasks",
      rawProject: { ...project, members: project.members?.map((member) => ({ ...member, role: "viewer" })) },
    })

    expect(await screen.findByRole("list", { name: "项目任务" })).toBeVisible()
    expect(screen.queryByRole("button", { name: "更新任务：准备数据" })).not.toBeInTheDocument()
  })

  it("lets a non-leader project lead with working membership execute a collaborating task", async () => {
    const nonLeaderId = "lead-chen"
    renderProjectDetail({
      role: "project_lead",
      userId: nonLeaderId,
      tab: "tasks",
      tasks: [{ ...task, collaborator_user_ids: [nonLeaderId] }],
      rawProject: {
        ...project,
        tasks: [{ ...task, collaborator_user_ids: [nonLeaderId] }],
        members: [...(project.members ?? []), {
          id: "membership-lead-chen",
          user_id: nonLeaderId,
          display_name: "陈负责人",
          system_role: "project_lead",
          role: "member",
        }],
      },
    })

    await screen.findByRole("list", { name: "项目任务" })
    expect(screen.getByRole("button", { name: "更新任务：准备数据" })).toBeVisible()
    expect(screen.queryByLabelText("计划开始日期")).not.toBeInTheDocument()
  })

  it("preserves unsaved task input on stale version and refreshes only the version token", async () => {
    let taskReads = 0
    const apiRequest = renderProjectDetail({
      role: "fde_engineer",
      tab: "tasks",
      taskPatch: apiError("stale_version", 409),
      taskDetail: () => {
        taskReads += 1
        return apiOk({ ...task, progress: 25, version: 4 })
      },
    })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "更新任务：准备数据" }))
    await user.clear(screen.getByLabelText("进度"))
    await user.type(screen.getByLabelText("进度"), "40")
    await user.click(screen.getByRole("button", { name: "保存任务" }))

    expect(await screen.findByText("内容已被其他人更新，请刷新后重试")).toBeVisible()
    expect(screen.getByLabelText("进度")).toHaveValue(40)
    expect(taskReads).toBe(0)

    await user.click(screen.getByRole("button", { name: "刷新任务" }))
    await waitFor(() => expect(taskReads).toBe(1))
    expect(screen.getByLabelText("进度")).toHaveValue(40)
    expect(mutationBodies(apiRequest, "PATCH")).toHaveLength(1)
  })

  it("shows enterprise completion and sends a manager status transition with project version", async () => {
    const apiRequest = renderProjectDetail({ role: "project_lead", tab: "overview" })
    const user = userEvent.setup()

    expect(await screen.findByText("星河制造")).toBeVisible()
    expect(screen.getByText("20%")).toBeVisible()
    await user.selectOptions(screen.getByLabelText("项目状态"), "paused")
    await user.click(screen.getByRole("button", { name: "更新项目状态" }))

    await waitFor(() => expect(mutationBodies(apiRequest, "PATCH")).toContainEqual({
      status: "paused",
      version: 5,
    }))
  })

  it("shows compact guidance in the overview and creates a revision before editing confirmed content", async () => {
    const apiRequest = renderProjectDetail({ role: "project_lead", tab: "overview", guidance: confirmedGuidance })
    const user = userEvent.setup()

    const overview = await screen.findByRole("heading", { name: "企业与项目信息" })
    expect(overview.closest(".overview-three-column")).not.toBeNull()
    expect(await screen.findByText("建设人工智能工厂")).toBeVisible()
    await user.click(screen.getByRole("button", { name: "查看详情" }))
    const dialog = await screen.findByRole("dialog", { name: "审核客户目标与项目指引" })
    expect(within(dialog).queryByRole("textbox")).not.toBeInTheDocument()
    await user.click(within(dialog).getByRole("button", { name: "编辑" }))

    expect(await within(dialog).findByLabelText("客户长期愿景")).toHaveValue("建设人工智能工厂")
    expect(apiRequest).toHaveBeenCalledWith(
      `/api/v1/projects/${projectId}/guidance-analyses/guidance-v1/revisions`,
      expect.objectContaining({ method: "POST", body: { version: 2 } }),
    )
  })

  it("requires the current password before cancelling a project", async () => {
    const apiRequest = renderProjectDetail({ role: "project_lead", tab: "overview" })
    const user = userEvent.setup()

    expect(await screen.findByText("星河制造")).toBeVisible()
    await user.selectOptions(screen.getByLabelText("项目状态"), "cancelled")
    await user.click(screen.getByRole("button", { name: "更新项目状态" }))
    const dialog = await screen.findByRole("dialog", { name: "取消项目" })

    await user.click(within(dialog).getByRole("button", { name: "取消" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(mutationBodies(apiRequest, "PATCH")).toHaveLength(0)

    await user.click(screen.getByRole("button", { name: "更新项目状态" }))
    const confirmDialog = await screen.findByRole("dialog", { name: "取消项目" })
    await user.type(within(confirmDialog).getByLabelText("当前账号密码"), "AdminPass!123")
    await user.click(within(confirmDialog).getByRole("button", { name: "确认取消" }))

    await waitFor(() =>
      expect(mutationBodies(apiRequest, "PATCH")).toContainEqual({
        status: "cancelled",
        version: 5,
      }),
    )
  })

  it("keeps an unsaved status selection when a stale project is manually refreshed", async () => {
    let projectReads = 0
    const apiRequest = renderProjectDetail({
      role: "project_lead",
      tab: "overview",
      projectPatch: apiError("stale_version", 409),
      projectDetail: () => {
        projectReads += 1
        return { ...project, version: projectReads === 1 ? 5 : 6 }
      },
    })
    const user = userEvent.setup()

    await user.selectOptions(await screen.findByLabelText("项目状态"), "paused")
    await user.click(screen.getByRole("button", { name: "更新项目状态" }))
    expect(await screen.findByText("内容已被其他人更新，请刷新后重试")).toBeVisible()
    await user.click(screen.getByRole("button", { name: "刷新项目" }))

    await waitFor(() => expect(projectReads).toBe(2))
    expect(screen.getByLabelText("项目状态")).toHaveValue("paused")
    expect(mutationBodies(apiRequest, "PATCH")).toHaveLength(1)
  })

  it("renders task dependency information and risk in the responsive card list", async () => {
    renderProjectDetail({
      role: "viewer",
      tab: "tasks",
      tasks: [{ ...task, dependency_risk: true, dependency_keys: ["collect_source"] }],
    })

    const list = await screen.findByRole("list", { name: "项目任务" })
    expect(within(list).getAllByRole("listitem")).toHaveLength(1)
    expect(within(list).getByText("待分配")).toBeVisible()
    expect(within(list).getByText("前置任务")).toBeVisible()
    expect(within(list).getByText("依赖风险")).toBeVisible()
    expect(screen.getByLabelText("按状态筛选")).toBeVisible()
    expect(screen.queryByRole("button", { name: "更新任务：准备数据" })).not.toBeInTheDocument()
  })

  it("omits empty predecessor sections while preserving dependency details", async () => {
    renderProjectDetail({
      role: "viewer",
      tab: "tasks",
      tasks: [task, { ...task, id: "task-dependent-card", name: "有前置任务", dependency_ids: [task.id], dependency_keys: [task.task_key] }],
    })

    const cards = await screen.findAllByRole("listitem")
    expect(within(cards[0]).queryByText("前置任务")).not.toBeInTheDocument()
    expect(within(cards[1]).getByText("前置任务")).toBeVisible()
    expect(within(cards[1]).getByText("准备数据")).toBeVisible()
  })

  it("refreshes manager task versions after a mutation that may reschedule dependencies", async () => {
    let taskListReads = 0
    const apiRequest = renderProjectDetail({
      role: "project_lead",
      tab: "tasks",
      taskList: () => {
        taskListReads += 1
        return [{ ...task, version: taskListReads === 1 ? 3 : 9, progress: taskListReads === 1 ? 20 : 40 }]
      },
    })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "更新任务：准备数据" }))
    await user.clear(screen.getByLabelText("进度"))
    await user.type(screen.getByLabelText("进度"), "40")
    await user.click(screen.getByRole("button", { name: "保存任务" }))

    await waitFor(() => expect(taskListReads).toBe(2))
    await user.click(await screen.findByRole("button", { name: "更新任务：准备数据" }))
    expect(screen.getByText("v9")).toBeVisible()
    expect(mutationBodies(apiRequest, "PATCH")).toContainEqual(expect.objectContaining({
      planned_start_date: "2026-08-21",
      planned_end_date: "2026-08-24",
      duration_days: 2,
      collaborator_user_ids: [engineerId],
      version: 3,
    }))
  })

  it("refreshes the active filtered task query after an engineer mutation", async () => {
    let filteredReads = 0
    const apiRequest = renderProjectDetail({
      role: "fde_engineer",
      tab: "tasks",
      taskList: (path) => {
        if (path.includes("status=in_progress")) {
          filteredReads += 1
          return filteredReads === 1 ? [task] : []
        }
        return [{ ...task, status: filteredReads > 1 ? "completed" : "in_progress", version: filteredReads > 1 ? 4 : 3 }]
      },
    })
    const user = userEvent.setup()

    await user.selectOptions(await screen.findByLabelText("按状态筛选"), "in_progress")
    await user.click(await screen.findByRole("button", { name: "更新任务：准备数据" }))
    await user.click(screen.getByRole("button", { name: "保存任务" }))

    expect(await screen.findByText("暂无符合条件的任务。")).toBeVisible()
    expect(filteredReads).toBe(2)
    expect(apiRequest.mock.calls.filter(([path, options]) => String(path).includes("status=in_progress") && options.method === "GET")).toHaveLength(2)
  })

  it("derives manager filtered rows from one authoritative unfiltered task snapshot", async () => {
    let filteredReads = 0
    let unfilteredReads = 0
    const apiRequest = renderProjectDetail({
      role: "project_lead",
      tab: "tasks",
      taskList: (path) => {
        if (path.includes("status=in_progress")) {
          filteredReads += 1
          return [{ ...task, version: 3 }]
        }
        unfilteredReads += 1
        return [{ ...task, version: unfilteredReads === 1 ? 3 : 10 }]
      },
    })
    const user = userEvent.setup()

    await user.selectOptions(await screen.findByLabelText("按状态筛选"), "in_progress")
    await user.click(await screen.findByRole("button", { name: "更新任务：准备数据" }))
    await user.click(screen.getByRole("button", { name: "保存任务" }))

    await waitFor(() => expect(unfilteredReads).toBe(2))
    expect(filteredReads).toBe(1)
    expect(unfilteredReads).toBe(2)
    const taskGets = apiRequest.mock.calls.filter(([path, options]) => String(path).startsWith(`/api/v1/projects/${projectId}/tasks`) && options.method === "GET")
    expect(taskGets.at(-1)?.[0]).toBe(`/api/v1/projects/${projectId}/tasks`)
    await user.click(await screen.findByRole("button", { name: "更新任务：准备数据" }))
    expect(screen.getByText("v10")).toBeVisible()
  })

  it("keeps a successful task mutation when its list refresh fails", async () => {
    let taskReads = 0
    const apiRequest = renderProjectDetail({
      role: "fde_engineer",
      tab: "tasks",
      taskPatch: apiOk({ ...task, status: "completed", progress: 100, version: 4 }),
      taskListResponse: () => {
        taskReads += 1
        return taskReads < 3 ? apiOk({ items: [task] }) : apiError("service_unavailable", 503)
      },
    })
    const user = userEvent.setup()

    await user.selectOptions(await screen.findByLabelText("按状态筛选"), "in_progress")
    await user.click(await screen.findByRole("button", { name: "更新任务：准备数据" }))
    await user.selectOptions(screen.getByLabelText("状态"), "completed")
    await user.clear(screen.getByLabelText("进度"))
    await user.type(screen.getByLabelText("进度"), "100")
    await user.click(screen.getByRole("button", { name: "保存任务" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("任务已保存，列表刷新失败")
    expect(screen.getByText("暂无符合条件的任务。")).toBeVisible()
    expect(mutationBodies(apiRequest, "PATCH")).toHaveLength(1)
  })

  it("omits the old blocked reason when a task leaves blocked status", async () => {
    const blockedTask = { ...task, status: "blocked" as const, blocked_reason: "等待客户数据" }
    const apiRequest = renderProjectDetail({ role: "fde_engineer", tab: "tasks", tasks: [blockedTask] })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "更新任务：准备数据" }))
    await user.selectOptions(screen.getByLabelText("状态"), "in_progress")
    expect(screen.getByText("非阻塞状态不会提交阻塞原因。")).toBeVisible()
    expect(screen.getByLabelText("阻塞原因")).toBeDisabled()
    await user.click(screen.getByRole("button", { name: "保存任务" }))

    await waitFor(() => expect(mutationBodies(apiRequest, "PATCH")[0]).toEqual({ status: "in_progress", progress: 20, version: 3 }))
  })

  it("lets a user save only a status change by normalizing the linked progress", async () => {
    const notStartedTask = { ...task, status: "not_started" as const, progress: 0 }
    const apiRequest = renderProjectDetail({ role: "fde_engineer", tab: "tasks", tasks: [notStartedTask] })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "更新任务：准备数据" }))
    await user.selectOptions(screen.getByLabelText("状态"), "in_progress")

    expect(screen.getByLabelText("进度")).toHaveValue(1)
    await user.click(screen.getByRole("button", { name: "保存任务" }))

    await waitFor(() => expect(mutationBodies(apiRequest, "PATCH")).toContainEqual(expect.objectContaining({
      status: "in_progress",
      progress: 1,
      version: 3,
    })))
  })

  it("requires a reason before submitting blocked status", async () => {
    const apiRequest = renderProjectDetail({ role: "fde_engineer", tab: "tasks" })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "更新任务：准备数据" }))
    await user.selectOptions(screen.getByLabelText("状态"), "blocked")
    await user.click(screen.getByRole("button", { name: "保存任务" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("阻塞状态必须填写阻塞原因")
    expect(mutationBodies(apiRequest, "PATCH")).toHaveLength(0)
    expect(screen.getByRole("button", { name: "保存任务" })).toBeEnabled()

    await user.type(screen.getByLabelText("阻塞原因"), "等待客户确认")
    await user.click(screen.getByRole("button", { name: "保存任务" }))
    await waitFor(() => expect(mutationBodies(apiRequest, "PATCH")).toEqual([{
      status: "blocked",
      progress: 20,
      blocked_reason: "等待客户确认",
      version: 3,
    }]))
  })

  it("keeps the selected tab in the hash for refresh and history", async () => {
    renderProjectDetail({ role: "viewer", tab: "overview" })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("tab", { name: "任务" }))
    await waitFor(() => expect(location.hash).toBe(`#projects/${projectId}?tab=tasks`))
    expect(screen.getByRole("tab", { name: "任务" })).toHaveAttribute("aria-selected", "true")
  })

  it("rejects a malformed project task tree instead of rendering partial detail", async () => {
    renderProjectDetail({
      role: "viewer",
      tab: "overview",
      rawProject: { ...project, tasks: [{ ...task, collaborator_user_ids: null }] },
    })

    expect(await screen.findByRole("alert")).toHaveTextContent("项目详情加载失败")
    expect(screen.queryByText("星河制造")).not.toBeInTheDocument()
  })

  it("lets the current project leader manage members with explicit user IDs and sequential project versions", async () => {
    const apiRequest = renderProjectDetail({ role: "project_lead", tab: "members" })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText("用户 ID"), "engineer-new")
    await user.selectOptions(screen.getByLabelText("项目访问权限"), "member")
    await user.click(screen.getByRole("button", { name: "添加成员" }))
    await user.click(await screen.findByRole("button", { name: "按默认角色分派待分配任务" }))

    expect(apiRequest.mock.calls.some(([path]) => String(path).startsWith("/api/v1/users"))).toBe(false)
    expect(mutationBodies(apiRequest, "POST")).toEqual(expect.arrayContaining([
      { user_id: "engineer-new", role: "member", version: 5 },
      { version: 6 },
    ]))
  })

  it("uses the standard table select and leaves unavailable member actions blank", async () => {
    const leader = {
      id: "membership-leader",
      user_id: project.leader_user_id,
      display_name: "王工",
      system_role: "project_lead" as const,
      role: "member" as const,
    }
    renderProjectDetail({
      role: "project_lead",
      tab: "members",
      memberList: () => Promise.resolve(apiOk({ items: [leader, ...(project.members ?? [])], project_version: 5 })),
    })

    const permission = await screen.findByLabelText("更新王工的项目权限")
    expect(permission).toHaveClass("table-select")
    expect(screen.getByRole("button", { name: "批量分配任务给：王工" })).toBeVisible()
    expect(screen.getByRole("button", { name: "移除成员：李工程师" })).toHaveClass("danger-button", "compact")
  })

  it("batch assigns selected tasks to a project member as assignee or collaborator", async () => {
    const secondTask = {
      ...task,
      id: "task-review",
      task_key: "review_data",
      name: "复核数据",
      assignee_user_id: "other-member",
      collaborator_user_ids: [],
      version: 2,
    }
    const apiRequest = renderProjectDetail({ role: "project_lead", tab: "members", tasks: [task, secondTask] })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "批量分配任务给：李工程师" }))
    const dialog = screen.getByRole("dialog", { name: "批量分配任务：李工程师" })
    expect(dialog).toHaveClass("batch-assignment-dialog")
    await user.selectOptions(within(dialog).getByLabelText("分配方式"), "assignee")
    await user.click(within(dialog).getByRole("checkbox", { name: /复核数据/ }))
    await user.click(within(dialog).getByRole("button", { name: "确认分配（1）" }))

    await waitFor(() => expect(mutationBodies(apiRequest, "POST")).toContainEqual({
      member_user_id: engineerId,
      mode: "assignee",
      tasks: [{ task_id: secondTask.id, version: 2 }],
    }))
    expect(await screen.findByText("已将 1 项任务分配给 李工程师。")).toBeVisible()
  })

  it("keeps member writes disabled until the authoritative member read finishes", async () => {
    const membersRead = deferred<BridgeResult<ApiResponse<unknown>>>()
    renderProjectDetail({ role: "project_lead", tab: "members", memberList: () => membersRead.promise })

    const add = await screen.findByRole("button", { name: "添加成员" })
    const assign = screen.getByRole("button", { name: "按默认角色分派待分配任务" })
    expect(add).toBeDisabled()
    expect(assign).toBeDisabled()

    membersRead.resolve(apiOk({ items: project.members, project_version: 5 }))
    await waitFor(() => expect(assign).toBeEnabled())
  })

  it("keeps writes disabled during a deferred stale refresh and uses its authoritative version", async () => {
    const staleRead = deferred<BridgeResult<ApiResponse<unknown>>>()
    let memberReads = 0
    const apiRequest = renderProjectDetail({
      role: "project_lead",
      tab: "members",
      memberList: () => {
        memberReads += 1
        return memberReads === 1
          ? Promise.resolve(apiOk({ items: project.members, project_version: 5 }))
          : staleRead.promise
      },
      memberPost: apiError("stale_version", 409),
    })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText("用户 ID"), "engineer-new")
    await user.click(screen.getByRole("button", { name: "添加成员" }))
    await user.click(await screen.findByRole("button", { name: "刷新成员" }))
    expect(screen.getByRole("button", { name: "按默认角色分派待分配任务" })).toBeDisabled()

    staleRead.resolve(apiOk({ items: project.members, project_version: 6 }))
    await waitFor(() => expect(screen.getByRole("button", { name: "按默认角色分派待分配任务" })).toBeEnabled())
    await user.click(screen.getByRole("button", { name: "按默认角色分派待分配任务" }))
    expect(mutationBodies(apiRequest, "POST")).toContainEqual({ version: 6 })
  })

  it.each([
    ["unknown status", { status: "unknown" }],
    ["fractional version", { version: 3.5 }],
    ["zero version", { version: 0 }],
    ["invalid progress", { progress: 101 }],
    ["invalid duration", { duration_days: 0 }],
    ["invalid role", { default_assignee_role: "operator" }],
    ["invalid completed time", { completed_at: 42 }],
    ["invalid dependency element", { incomplete_dependency_ids: [42] }],
  ])("rejects a task DTO with %s before any mutation token can be used", async (_label, invalid) => {
    const apiRequest = renderProjectDetail({
      role: "project_lead",
      tab: "tasks",
      rawProject: { ...project, tasks: [{ ...task, ...invalid }] },
    })

    expect(await screen.findByRole("alert")).toHaveTextContent("项目详情加载失败")
    expect(mutationBodies(apiRequest, "PATCH")).toHaveLength(0)
  })

  it.each([
    ["zero project version", { version: 0 }],
    ["fractional completion", { completion: 20.5 }],
    ["completion over 100", { completion: 101 }],
  ])("rejects project detail with %s", async (_label, invalid) => {
    renderProjectDetail({ role: "viewer", tab: "overview", rawProject: { ...project, ...invalid } })
    expect(await screen.findByRole("alert")).toHaveTextContent("项目详情加载失败")
  })

  it("rejects malformed member version data and never enables mutations", async () => {
    const apiRequest = renderProjectDetail({
      role: "project_lead",
      tab: "members",
      memberList: () => Promise.resolve(apiOk({ items: project.members, project_version: 0 })),
    })

    expect(await screen.findByRole("alert")).toHaveTextContent("成员操作失败")
    expect(screen.getByRole("button", { name: "按默认角色分派待分配任务" })).toBeDisabled()
    expect(mutationBodies(apiRequest, "POST")).toHaveLength(0)
  })

  it("appends a remaining snapshot module, confirms cancellation, and advances project versions", async () => {
    const apiRequest = renderProjectDetail({ role: "project_lead", tab: "modules" })
    const user = userEvent.setup()

    await user.selectOptions(await screen.findByLabelText("待追加模块"), "launch")
    await user.clear(screen.getByLabelText("计划开始日期"))
    await user.type(screen.getByLabelText("计划开始日期"), "2026-09-01")
    await user.click(screen.getByRole("button", { name: "追加模块" }))
    await user.click(await screen.findByRole("button", { name: "取消模块：上线与移交" }))

    const dialog = await screen.findByRole("dialog", { name: "取消模块" })
    await user.type(within(dialog).getByLabelText("当前账号密码"), "AdminPass!123")
    await user.click(within(dialog).getByRole("button", { name: "确认取消" }))
    await waitFor(() =>
      expect(mutationBodies(apiRequest, "DELETE")).toContainEqual({ version: 6 }),
    )
    expect(mutationBodies(apiRequest, "POST")).toContainEqual({ module_key: "launch", planned_start_date: "2026-09-01", version: 5 })
    expect(screen.queryByRole("option", { name: "上线与移交" })).not.toBeInTheDocument()
  })

  it("marks the append action for bottom alignment with its form fields", async () => {
    renderProjectDetail({ role: "project_lead", tab: "modules" })

    expect(await screen.findByRole("button", { name: "追加模块" })).toHaveClass("module-append-submit")
  })

  it("refreshes authoritative tasks after appending a module", async () => {
    const dependency = { ...task, id: "task-source", task_key: "source", name: "前置任务", status: "completed" as const, progress: 100 }
    const appended = {
      ...task,
      id: "task-launch",
      project_module_id: "project-module-launch",
      module_key: "launch",
      task_key: "go_live",
      name: "生产上线",
      dependency_ids: [dependency.id],
      dependency_keys: [dependency.task_key],
      version: 1,
    }
    let taskReads = 0
    const apiRequest = renderProjectDetail({
      role: "project_lead",
      tab: "modules",
      tasks: [dependency],
      taskList: () => {
        taskReads += 1
        return [dependency, appended]
      },
      modulePostTasks: [{
        ...appended,
        dependency_keys: undefined,
        collaborator_user_ids: undefined,
      }],
    })
    const user = userEvent.setup()

    await user.selectOptions(await screen.findByLabelText("待追加模块"), "launch")
    await user.click(screen.getByRole("button", { name: "追加模块" }))
    await waitFor(() => expect(taskReads).toBe(1))

    expect(apiRequest.mock.calls).toContainEqual([`/api/v1/projects/${projectId}/tasks`, expect.objectContaining({ method: "GET" })])
  })

  it("keeps an accepted module append when task refresh fails and retries only the refresh", async () => {
    let taskReads = 0
    const apiRequest = renderProjectDetail({
      role: "project_lead",
      tab: "modules",
      taskListResponse: () => {
        taskReads += 1
        return taskReads === 1 ? apiError("service_unavailable", 503) : apiOk({ items: [task] })
      },
    })
    const user = userEvent.setup()

    await user.selectOptions(await screen.findByLabelText("待追加模块"), "launch")
    await user.click(screen.getByRole("button", { name: "追加模块" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("模块已追加，任务刷新失败，请刷新")
    expect(screen.queryByText("模块操作失败，请稍后重试。")).not.toBeInTheDocument()
    expect(screen.queryByRole("option", { name: "上线与移交" })).not.toBeInTheDocument()
    expect(mutationBodies(apiRequest, "POST").filter((body) => "module_key" in (body as Record<string, unknown>))).toHaveLength(1)

    await user.click(screen.getByRole("button", { name: "刷新任务" }))
    await waitFor(() => expect(screen.queryByText("模块已追加，任务刷新失败，请刷新")).not.toBeInTheDocument())
    expect(taskReads).toBe(2)
    expect(mutationBodies(apiRequest, "POST").filter((body) => "module_key" in (body as Record<string, unknown>))).toHaveLength(1)
  })

  it("merges an old append refresh into the latest cancelled project without reverting other fields", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true)
    let taskReads = 0
    const updatedTask = { ...task, progress: 65, version: 9 }
    const apiRequest = vi.fn((path: string, requestOptions: { method: string }) => {
      if (path === `/api/v1/projects/${projectId}/modules` && requestOptions.method === "POST") {
        return Promise.resolve(apiOk(moduleMutation("active", 6)))
      }
      if (path === `/api/v1/projects/${projectId}/modules/project-module-launch` && requestOptions.method === "DELETE") {
        return Promise.resolve(apiOk(moduleMutation("cancelled", 8)))
      }
      if (path === `/api/v1/projects/${projectId}/tasks` && requestOptions.method === "GET") {
        taskReads += 1
        return Promise.resolve(taskReads === 1 ? apiError("service_unavailable", 503) : apiOk({ items: [updatedTask] }))
      }
      if (path === "/api/v1/auth/verify-password" && requestOptions.method === "POST") {
        return Promise.resolve(apiOk({ valid: true }))
      }
      return Promise.resolve(apiError("unexpected_request", 500))
    })
    const currentUser: UserDto = {
      ...engineerUser,
      id: project.leader_user_id,
      role: "project_lead",
      username: "project_lead.user",
      displayName: "项目负责人",
    }
    installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(currentUser))), apiRequest }))

    function Harness() {
      const [current, setCurrent] = React.useState(project)
      return <>
        <button type="button" onClick={() => setCurrent((latest) => ({
          ...latest,
          status: "paused",
          version: 7,
          members: [...(latest.members ?? []), {
            id: "membership-auditor",
            user_id: "auditor-zhou",
            display_name: "周审核",
            system_role: "viewer",
            role: "viewer",
          }],
        }))}>模拟后续项目更新</button>
        <output aria-label="最新项目状态">{JSON.stringify(current)}</output>
        <ProjectModules project={current} canManage onProjectChange={setCurrent} onRefresh={async () => current} />
      </>
    }

    renderApp(
      <AuthProvider>
        <DangerConfirmProvider>
          <Harness />
        </DangerConfirmProvider>
      </AuthProvider>,
    )
    const user = userEvent.setup()
    await user.selectOptions(await screen.findByLabelText("待追加模块"), "launch")
    await user.click(screen.getByRole("button", { name: "追加模块" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("模块已追加，任务刷新失败，请刷新")

    await user.click(screen.getByRole("button", { name: "模拟后续项目更新" }))
    await user.click(await screen.findByRole("button", { name: "取消模块：上线与移交" }))
    const dialog = await screen.findByRole("dialog", { name: "取消模块" })
    await user.type(within(dialog).getByLabelText("当前账号密码"), "AdminPass!123")
    await user.click(within(dialog).getByRole("button", { name: "确认取消" }))
    await user.click(screen.getByRole("button", { name: "刷新任务" }))

    await waitFor(() => {
      const current = JSON.parse(screen.getByRole("status", { name: "最新项目状态" }).textContent ?? "{}") as ProjectDto
      expect(current.status).toBe("paused")
      expect(current.version).toBe(8)
      expect(current.members).toEqual(expect.arrayContaining([expect.objectContaining({ user_id: "auditor-zhou" })]))
      expect(current.modules.find((module) => module.module_key === "launch")?.status).toBe("cancelled")
      expect(current.tasks).toEqual([updatedTask])
    })
    expect(screen.queryByRole("button", { name: "取消模块：上线与移交" })).not.toBeInTheDocument()
    expect(mutationBodies(apiRequest, "DELETE")).toContainEqual({ version: 7 })
    expect(taskReads).toBe(2)
  })

  it("rejects malformed nested module tasks without refreshing from an untrusted mutation", async () => {
    const apiRequest = renderProjectDetail({
      role: "project_lead",
      tab: "modules",
      modulePostTasks: [{ ...task, dependency_ids: [42], collaborator_user_ids: undefined, dependency_keys: undefined }],
    })
    const user = userEvent.setup()

    await user.selectOptions(await screen.findByLabelText("待追加模块"), "launch")
    await user.click(screen.getByRole("button", { name: "追加模块" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("模块操作失败")
    expect(apiRequest.mock.calls.filter(([path, options]) => path === `/api/v1/projects/${projectId}/tasks` && options.method === "GET")).toHaveLength(0)
  })

  it("lets a manager set task collaborators through the task editor", async () => {
    const engineer2Id = "lead-wang-2"
    const twoMemberProject = {
      ...project,
      members: [
        { id: "membership-engineer", user_id: engineerId, display_name: "李工程师", system_role: "fde_engineer" as const, role: "member" as const },
        { id: "membership-lead2", user_id: engineer2Id, display_name: "王工", system_role: "fde_engineer" as const, role: "member" as const },
      ],
    }
    const apiRequest = renderProjectDetail({
      role: "project_lead",
      tab: "tasks",
      projectDetail: () => twoMemberProject,
      tasks: [{ ...task, collaborator_user_ids: [] }],
    })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "更新任务：准备数据" }))
    const collaboratorGroup = screen.getByRole("group", { name: "协作人" })
    expect(within(collaboratorGroup).getByRole("checkbox", { name: "王工" })).toBeVisible()
    expect(screen.getByText("可多选项目成员；负责人不能同时作为协作人。")).toBeVisible()

    await user.click(within(collaboratorGroup).getByRole("checkbox", { name: "王工" }))
    await user.click(screen.getByRole("button", { name: "保存任务" }))

    await waitFor(() => expect(mutationBodies(apiRequest, "PATCH")).toContainEqual(expect.objectContaining({
      collaborator_user_ids: [engineer2Id],
      version: 3,
    })))
    expect(mutationBodies(apiRequest, "PATCH")).toHaveLength(1)
  })

  it("shows active predecessor choices in the manager editor and omits cancelled tasks", async () => {
    const sourceTask = { ...task, id: "task-source", task_key: "source", name: "前置任务", status: "completed" as const, progress: 100 }
    const cancelledTask = { ...task, id: "task-cancelled", task_key: "cancelled-key", name: "已取消任务", status: "cancelled" as const, progress: 0 }
    const apiRequest = renderProjectDetail({
      role: "project_lead",
      tab: "tasks",
      tasks: [task, sourceTask, cancelledTask],
    })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "更新任务：准备数据" }))
    await user.click(screen.getByRole("checkbox", { name: "前置任务：前置任务" }))
    expect(screen.queryByRole("checkbox", { name: "前置任务：已取消任务" })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "保存任务" }))

    await waitFor(() => expect(mutationBodies(apiRequest, "PATCH")).toHaveLength(1))
    const body = mutationBodies(apiRequest, "PATCH")[0]
    expect(body).toEqual(expect.objectContaining({ dependency_ids: [sourceTask.id] }))
  })

  it("surfaces a server cyclic-dependency rejection in the task dialog instead of a generic error", async () => {
    const apiRequest = renderProjectDetail({
      role: "project_lead",
      tab: "tasks",
      taskPatch: apiError("cyclic_dependency", 400),
    })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "更新任务：准备数据" }))
    await user.click(screen.getByRole("button", { name: "保存任务" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("依赖关系存在循环，无法保存。")
  })

  it("lets a project lead edit enterprise and project info inline and send only the changed fields", async () => {
    const apiRequest = renderProjectDetail({
      role: "project_lead",
      tab: "overview",
      projectPatch: apiOk({ ...project, enterprise_name: "星河智造", version: 6 }),
    })
    const user = userEvent.setup()

    expect(await screen.findByText("星河制造")).toBeVisible()
    await user.click(screen.getByRole("button", { name: "编辑" }))
    const enterpriseInput = screen.getByLabelText("企业")
    await user.clear(enterpriseInput)
    await user.type(enterpriseInput, "星河智造")
    await user.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => expect(mutationBodies(apiRequest, "PATCH")).toContainEqual({
      enterprise_name: "星河智造",
      version: 5,
    }))
    expect(await screen.findByText("星河智造")).toBeVisible()
    expect(screen.getByRole("button", { name: "编辑" })).toBeVisible()
  })

  it("cancels an overview edit without issuing a mutation", async () => {
    const apiRequest = renderProjectDetail({ role: "project_lead", tab: "overview" })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "编辑" }))
    await user.type(screen.getByLabelText("项目名称"), "临时改名")
    await user.click(screen.getByRole("button", { name: "取消" }))

    expect(screen.queryByLabelText("项目名称")).not.toBeInTheDocument()
    expect(screen.getByText("星河制造")).toBeVisible()
    expect(mutationBodies(apiRequest, "PATCH")).toHaveLength(0)
  })

  it("hides the overview edit control for viewers", async () => {
    renderProjectDetail({ role: "viewer", tab: "overview" })

    expect(await screen.findByText("星河制造")).toBeVisible()
    expect(screen.queryByRole("button", { name: "编辑" })).not.toBeInTheDocument()
  })

  it("prompts a refresh when an overview edit hits a stale project", async () => {
    const apiRequest = renderProjectDetail({
      role: "project_lead",
      tab: "overview",
      projectPatch: apiError("stale_version", 409),
    })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "编辑" }))
    const enterpriseInput = screen.getByLabelText("企业")
    await user.clear(enterpriseInput)
    await user.type(enterpriseInput, "星河智造")
    await user.click(screen.getByRole("button", { name: "保存" }))

    expect(await screen.findByText("内容已被其他人更新，请刷新后重试")).toBeVisible()
    expect(screen.getByRole("button", { name: "刷新项目" })).toBeVisible()
    expect(mutationBodies(apiRequest, "PATCH")).toHaveLength(1)
  })

  it("shows a stable Gantt load error for malformed nested assignee roles", async () => {
    renderProjectDetail({
      role: "viewer",
      tab: "gantt",
      gantt: {
        project_id: projectId,
        range: { start: "2026-08-21", end: "2026-08-21" },
        groups: [{
          id: "project-module-pov",
          module_key: "pov",
          name: "PoV 验证",
          status: "active",
          cancelled: false,
          tasks: [{
            id: task.id,
            task_key: task.task_key,
            name: task.name,
            planned_start_date: task.planned_start_date,
            planned_end_date: task.planned_end_date,
            assignee: { id: engineerId, display_name: "李工程师", role: "operator" },
            progress: 20,
            status: "in_progress",
            cancelled: false,
            dependency_ids: [],
            dependency_risk: false,
            incomplete_dependency_ids: [],
          }],
        }],
      },
    })

    expect(await screen.findByRole("alert")).toHaveTextContent("甘特图加载失败")
  })

  it("rejects a half-empty Gantt range instead of treating it as an empty project", async () => {
    renderProjectDetail({
      role: "viewer",
      tab: "gantt",
      gantt: { project_id: projectId, range: { start: null, end: "2026-08-21" }, groups: [] },
    })

    expect(await screen.findByRole("alert")).toHaveTextContent("甘特图加载失败")
  })
})

type Role = UserDto["role"]

function renderProjectDetail(options: {
  role: Role
  tab: "overview" | "tasks" | "gantt" | "members" | "modules"
  tasks?: ProjectTaskDto[]
  taskPatch?: BridgeResult<ApiResponse<unknown>>
  taskDetail?: () => BridgeResult<ApiResponse<ProjectTaskDto>>
  taskList?: (path: string) => ProjectTaskDto[]
  taskListResponse?: (path: string) => BridgeResult<ApiResponse<unknown>> | Promise<BridgeResult<ApiResponse<unknown>>>
  projectPatch?: BridgeResult<ApiResponse<unknown>>
  projectDetail?: () => ProjectDto
  rawProject?: unknown
  userId?: string
  memberList?: () => Promise<BridgeResult<ApiResponse<unknown>>>
  memberPost?: BridgeResult<ApiResponse<unknown>>
  modulePostTasks?: unknown[]
  gantt?: unknown
  guidance?: GuidanceAnalysisDto | null
  documentPost?: BridgeResult<ApiResponse<unknown>>
}) {
  const currentUser: UserDto = {
    ...engineerUser,
    id: options.userId ?? (options.role === "project_lead" ? project.leader_user_id : engineerId),
    role: options.role,
    username: `${options.role}.user`,
    displayName: `${options.role} 用户`,
  }
  const taskItems = options.tasks ?? [task]
  const apiRequest = vi.fn((path: string, requestOptions: { method: string }) => {
    if (path === `/api/v1/projects/${projectId}` && requestOptions.method === "GET") {
      return Promise.resolve(apiOk(options.rawProject ?? { ...(options.projectDetail?.() ?? project), tasks: taskItems }))
    }
    if (path.startsWith(`/api/v1/projects/${projectId}/tasks`) && !path.includes(`/tasks/${task.id}`) && requestOptions.method === "GET") {
      if (options.taskListResponse) return Promise.resolve(options.taskListResponse(path))
      return Promise.resolve(apiOk({ items: options.taskList?.(path) ?? taskItems }))
    }
    if (path === `/api/v1/projects/${projectId}/tasks/${task.id}` && requestOptions.method === "GET") {
      return Promise.resolve(options.taskDetail?.() ?? apiOk(task))
    }
    if (path === `/api/v1/projects/${projectId}/tasks/${task.id}` && requestOptions.method === "PATCH") {
      return Promise.resolve(options.taskPatch ?? apiOk({ ...task, progress: 40, version: 4 }))
    }
    if (path === `/api/v1/projects/${projectId}` && requestOptions.method === "PATCH") {
      return Promise.resolve(options.projectPatch ?? apiOk({ ...project, status: "paused", version: 6 }))
    }
    if (path === `/api/v1/projects/${projectId}/gantt` && requestOptions.method === "GET") {
      return Promise.resolve(apiOk(options.gantt))
    }
    if (path === `/api/v1/projects/${projectId}/guidance` && requestOptions.method === "GET") {
      return Promise.resolve(apiOk(options.guidance ?? null))
    }
    if (path === `/api/v1/projects/${projectId}/documents` && requestOptions.method === "POST") {
      if (options.documentPost) return Promise.resolve(options.documentPost)
      return Promise.resolve(apiOk({
        id: "project-plan-document", project_id: projectId, document_type: "project_plan_progress", business_code: "PLAN-1",
        status: "draft", version: 1, current_version_id: null, current_version: null, draft: {
          id: "project-plan-draft", document_id: "project-plan-document", version: 1, field_overrides: {}, rich_text: {}, list_selections: {},
          created_at: "2026-08-31T00:00:00Z", updated_at: "2026-08-31T00:00:00Z",
        }, history: [], created_at: "2026-08-31T00:00:00Z", project_version: 6,
      }))
    }
    if (path === `/api/v1/projects/${projectId}/documents/project-plan-document/generate` && requestOptions.method === "POST") {
      return Promise.resolve(apiOk({
        id: "project-plan-version", document_id: "project-plan-document", version_number: 1, source: "generated", status: "draft",
        created_at: "2026-08-31T00:00:00Z",
      }))
    }
    if (path === `/api/v1/projects/${projectId}/guidance-analyses/guidance-v1/revisions` && requestOptions.method === "POST") {
      return Promise.resolve(apiOk({ ...confirmedGuidance, id: "guidance-v2", version_number: 2, status: "draft", version: 1 }))
    }
    if (path === `/api/v1/projects/${projectId}/members` && requestOptions.method === "GET") {
      return options.memberList?.() ?? Promise.resolve(apiOk({ items: project.members, project_version: 5 }))
    }
    if (path === `/api/v1/projects/${projectId}/members` && requestOptions.method === "POST") {
      return Promise.resolve(options.memberPost ?? apiOk({
        id: "membership-new",
        user_id: "engineer-new",
        display_name: "新工程师",
        system_role: "fde_engineer",
        role: "member",
        project_version: 6,
      }))
    }
    if (path === `/api/v1/projects/${projectId}/tasks/assign-defaults` && requestOptions.method === "POST") {
      return Promise.resolve(apiOk({ assigned_count: 1, assignments: [{ task_id: task.id, assignee_user_id: "engineer-new" }], project_version: 7 }))
    }
    if (path === `/api/v1/projects/${projectId}/tasks/batch-assignments` && requestOptions.method === "POST") {
      const selected = taskItems[1] ?? taskItems[0]
      return Promise.resolve(apiOk({
        updated_count: 1,
        skipped_count: 0,
        tasks: [{ ...selected, assignee_user_id: engineerId, collaborator_user_ids: [], version: selected.version + 1 }],
      }))
    }
    if (path === `/api/v1/projects/${projectId}/modules` && requestOptions.method === "POST") {
      return Promise.resolve(apiOk({
        id: "project-module-launch",
        module_key: "launch",
        name: "上线与移交",
        description: "生产上线",
        status: "active",
        sort_order: 2,
        planned_start_date: "2026-09-01",
        planned_end_date: "2026-09-01",
        tasks: options.modulePostTasks ?? [],
        project_version: 6,
      }))
    }
    if (path === `/api/v1/projects/${projectId}/modules/project-module-launch` && requestOptions.method === "DELETE") {
      return Promise.resolve(apiOk({
        id: "project-module-launch",
        module_key: "launch",
        name: "上线与移交",
        description: "生产上线",
        status: "cancelled",
        sort_order: 2,
        planned_start_date: "2026-09-01",
        planned_end_date: "2026-09-01",
        tasks: [],
        project_version: 7,
      }))
    }
    if (path === "/api/v1/auth/verify-password" && requestOptions.method === "POST") {
      return Promise.resolve(apiOk({ valid: true }))
    }
    return Promise.resolve(apiError("unexpected_request", 500))
  })
  location.hash = `#projects/${projectId}${options.tab === "overview" ? "" : `?tab=${options.tab}`}`
  installBridge(bridge({
    refresh: vi.fn().mockResolvedValue(ok(authResult(currentUser))),
    apiRequest,
  }))
  renderApp(<App />)
  return apiRequest
}

function apiOk<T>(data: T): BridgeResult<ApiResponse<T>> {
  return ok({ status: 200, data, error: null })
}

function apiError(code: string, status: number): BridgeResult<ApiResponse<never>> {
  return ok({ status, data: null, error: { code, message: code } })
}

function mutationBodies(apiRequest: ReturnType<typeof vi.fn>, method: string): unknown[] {
  return apiRequest.mock.calls
    .filter(([, options]) => options.method === method)
    .map(([, options]) => options.body)
}

function moduleMutation(status: "active" | "cancelled", projectVersion: number) {
  return {
    id: "project-module-launch",
    module_key: "launch",
    name: "上线与移交",
    description: "生产上线",
    status,
    sort_order: 2,
    planned_start_date: "2026-09-01",
    planned_end_date: "2026-09-01",
    tasks: [],
    project_version: projectVersion,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
