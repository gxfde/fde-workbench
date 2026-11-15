// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ApiClientError } from "../../src/renderer/src/api/client"
import type { ProjectTaskDto } from "../../src/renderer/src/workbench/types"

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  user: { id: "leader-1", role: "project_lead" },
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))

import { TestPlansPanel, type TestPlanDto } from "../../src/renderer/src/quality/TestPlansPanel"

const projectId = "proj-1"

const tasks: ProjectTaskDto[] = [
  {
    id: "task-1",
    project_module_id: "mod-1",
    module_key: "pov",
    task_key: "prepare_data",
    name: "准备数据",
    description: "",
    status: "in_progress",
    planned_start_date: "2026-08-21",
    planned_end_date: "2026-08-24",
    duration_days: 2,
    default_assignee_role: "fde_engineer",
    assignee_user_id: null,
    pending_assignment: false,
    progress: 20,
    blocked_reason: "",
    completed_at: null,
    sort_order: 1,
    collaborator_user_ids: [],
    dependency_ids: [],
    dependency_keys: [],
    dependency_risk: false,
    incomplete_dependency_ids: [],
    version: 1,
  },
  {
    id: "task-cancelled",
    project_module_id: "mod-1",
    module_key: "pov",
    task_key: "cancelled_one",
    name: "已取消任务",
    description: "",
    status: "cancelled",
    planned_start_date: "2026-08-25",
    planned_end_date: "2026-08-26",
    duration_days: 1,
    default_assignee_role: null,
    assignee_user_id: null,
    pending_assignment: false,
    progress: 0,
    blocked_reason: "",
    completed_at: null,
    sort_order: 2,
    collaborator_user_ids: [],
    dependency_ids: [],
    dependency_keys: [],
    dependency_risk: false,
    incomplete_dependency_ids: [],
    version: 1,
  },
]

function makePlan(overrides: Partial<TestPlanDto> = {}): TestPlanDto {
  return {
    id: "tp-1",
    project_id: projectId,
    source_task_id: null,
    title: "测试计划 v1",
    version: 1,
    status: "draft",
    created_by_user_id: "leader-1",
    reviewed_by_user_id: null,
    reviewed_at: null,
    review_comment: null,
    cases: [
      {
        id: "case-1",
        case_key: "TC-abc12345",
        title: "验证：设备台账同步",
        preconditions: null,
        steps: ["打开台账页", "点击同步"],
        expected: "5 分钟内同步完成",
        risk_level: 3,
        automated: false,
        acceptance_mode: "test",
        requirement_key: "R-001",
        sort_order: 0,
      },
      {
        id: "case-2",
        case_key: "TC-def67890",
        title: "人工确认：权限矩阵走查",
        preconditions: null,
        steps: [],
        expected: null,
        risk_level: 1,
        automated: false,
        acceptance_mode: "manual",
        requirement_key: "R-002",
        sort_order: 1,
      },
    ],
    case_count: 2,
    ...overrides,
  }
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
})

afterEach(() => {
  cleanup()
})

describe("TestPlansPanel", () => {
  it("renders plan cards with status, version, and case table columns", async () => {
    mocks.apiRequest.mockResolvedValue({
      items: [
        makePlan({ status: "approved", version: 2, title: "测试计划 v2", source_task_id: "task-1" }),
      ],
    })

    render(<TestPlansPanel projectId={projectId} canManage={false} tasks={tasks} />)

    expect(await screen.findByText("测试计划 v2")).toBeInTheDocument()
    expect(screen.getByText("已批准")).toBeInTheDocument()
    expect(screen.getByText(/v2 · 2 用例/)).toBeInTheDocument()
    expect(screen.getByText("TC-abc12345")).toBeInTheDocument()
    expect(screen.getByText("验证：设备台账同步")).toBeInTheDocument()
    expect(screen.getByText("TC-def67890")).toBeInTheDocument()
    expect(screen.getAllByText("高")).toHaveLength(1)
    expect(screen.getAllByText("测试")).toHaveLength(1)
    expect(screen.getAllByText("人工验收")).toHaveLength(1)
    expect(screen.getByText("R-001")).toBeInTheDocument()
    expect(screen.getByText("R-002")).toBeInTheDocument()
  })

  it("offers both deterministic and AI generation and reloads the list after each", async () => {
    const user = userEvent.setup()
    let plans: TestPlanDto[] = []
    mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
      if (path === `/api/v1/projects/${projectId}/test-plans` && options?.method === "GET") {
        return Promise.resolve({ items: plans })
      }
      if (path === `/api/v1/projects/${projectId}/test-plans/generate` && options?.method === "POST") {
        plans = [makePlan({ id: "tp-det", title: "测试计划 v1", version: 1 })]
        return Promise.resolve({ plan: plans[0], created: true })
      }
      if (path === `/api/v1/projects/${projectId}/test-plans/generate-ai` && options?.method === "POST") {
        plans = [makePlan({ id: "tp-ai", title: "测试计划（AI 起草）v2", version: 2 }), ...plans]
        return Promise.resolve({ plan: plans[0], created: true, model: "MiniMax-M3.1-Flash", prompt_version: "quality-draft-prompt-v1" })
      }
      throw new Error(`unexpected ${options?.method} ${path}`)
    })

    render(<TestPlansPanel projectId={projectId} canManage tasks={tasks} />)
    expect(await screen.findByText("暂无测试计划草稿或已批准版本。")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "确定性生成" }))
    expect(await screen.findByText("测试计划 v1")).toBeInTheDocument()
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      `/api/v1/projects/${projectId}/test-plans/generate`,
      expect.objectContaining({ method: "POST", body: {} }),
    )

    await user.click(screen.getByRole("button", { name: "AI 起草" }))
    expect(await screen.findByText("测试计划（AI 起草）v2")).toBeInTheDocument()
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      `/api/v1/projects/${projectId}/test-plans/generate-ai`,
      expect.objectContaining({ method: "POST", body: {} }),
    )
  })

  it("passes the selected task id through as source_task_id in the generate body", async () => {
    const user = userEvent.setup()
    mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
      if (path === `/api/v1/projects/${projectId}/test-plans` && options?.method === "GET") {
        return Promise.resolve({ items: [] })
      }
      if (path === `/api/v1/projects/${projectId}/test-plans/generate-ai` && options?.method === "POST") {
        return Promise.resolve({ plan: makePlan({ source_task_id: "task-1" }), created: true })
      }
      throw new Error(`unexpected ${options?.method} ${path}`)
    })

    render(<TestPlansPanel projectId={projectId} canManage tasks={tasks} />)
    await screen.findByText("暂无测试计划草稿或已批准版本。")

    await user.selectOptions(screen.getByLabelText("来源任务"), "task-1")
    await user.click(screen.getByRole("button", { name: "AI 起草" }))

    await waitFor(() =>
      expect(mocks.apiRequest).toHaveBeenCalledWith(
        `/api/v1/projects/${projectId}/test-plans/generate-ai`,
        expect.objectContaining({ method: "POST", body: { source_task_id: "task-1" } }),
      ),
    )
  })

  it("does not offer a production environment option in the execution form", async () => {
    const user = userEvent.setup()
    mocks.apiRequest.mockResolvedValue({ items: [makePlan({ status: "approved", version: 1 })] })

    render(<TestPlansPanel projectId={projectId} canManage tasks={tasks} />)
    await user.click(await screen.findByRole("button", { name: "登记执行" }))

    const envSelect = screen.getByLabelText("执行环境") as HTMLSelectElement
    const values = Array.from(envSelect.options).map((option) => option.value)
    expect(values).toEqual(["dev", "staging"])
    expect(values).not.toContain("production")
    expect(screen.queryByText(/production/)).not.toBeInTheDocument()
  })

  it("reviews a draft plan (approve with comment / reject)", async () => {
    const user = userEvent.setup()
    let currentPlan = makePlan({ status: "draft", version: 1 })
    mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
      if (path === `/api/v1/projects/${projectId}/test-plans`) return Promise.resolve({ items: [currentPlan] })
      if (path === `/api/v1/test-plans/tp-1/review` && options?.method === "PATCH") {
        const body = options.body as { decision: string; comment?: string }
        currentPlan = {
          ...currentPlan,
          status: body.decision === "approved" ? "approved" : "superseded",
          review_comment: body.comment ?? null,
        }
        return Promise.resolve({ plan: currentPlan })
      }
      throw new Error(`unexpected ${options?.method} ${path}`)
    })

    render(<TestPlansPanel projectId={projectId} canManage tasks={tasks} />)
    expect(await screen.findByText("草稿")).toBeInTheDocument()

    await user.type(screen.getByLabelText("审阅备注 v1"), "覆盖全部已批准需求，同意")
    await user.click(screen.getByRole("button", { name: "批准" }))

    await waitFor(() =>
      expect(mocks.apiRequest).toHaveBeenCalledWith(
        "/api/v1/test-plans/tp-1/review",
        { method: "PATCH", body: { decision: "approved", comment: "覆盖全部已批准需求，同意" } },
      ),
    )
    expect(await screen.findByText("已批准")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "登记执行" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "批准" })).not.toBeInTheDocument()
  })

  it("blocks the submit when report pointer and sha256 are not paired (frontend gate, no API call)", async () => {
    const user = userEvent.setup()
    mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
      if (path === `/api/v1/projects/${projectId}/test-plans`) return Promise.resolve({ items: [makePlan({ status: "approved" })] })
      if (path === `/api/v1/test-plans/tp-1/execute`) {
        return Promise.reject(new Error("execute should never be called"))
      }
      throw new Error(`unexpected ${options?.method ?? "GET"} ${path}`)
    })

    render(<TestPlansPanel projectId={projectId} canManage tasks={tasks} />)
    await user.click(await screen.findByRole("button", { name: "登记执行" }))

    // 只填指针不填 sha256（用例 1）→ 前端拦截
    await user.selectOptions(screen.getByLabelText("执行结果 TC-abc12345"), "passed")
    await user.type(screen.getByLabelText("报告指针 TC-abc12345"), "file:///D:/reports/r1.html")
    await user.click(screen.getByRole("button", { name: "提交执行记录" }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("用例 TC-abc12345：报告指针与报告 sha256 须成对提供")
    expect(mocks.apiRequest.mock.calls.some(([path]) => String(path).includes("/execute"))).toBe(false)

    // 补齐成对后放行
    await user.type(screen.getByLabelText("报告 sha256 TC-abc12345"), "a".repeat(64))
    mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
      if (path === `/api/v1/projects/${projectId}/test-plans` && options?.method === "GET") {
        return Promise.resolve({ items: [makePlan({ status: "approved" })] })
      }
      if (path === `/api/v1/test-plans/tp-1/execute` && options?.method === "POST") {
        expect(options.body).toEqual({
          environment: "dev",
          executions: [{ case_id: "case-1", result: "passed", report_uri: "file:///D:/reports/r1.html", report_sha256: "a".repeat(64) }],
        })
        return Promise.resolve({ created: [{ execution_id: "exec-1", case_id: "case-1", case_key: "TC-abc12345", result: "passed" }] })
      }
      throw new Error(`unexpected ${options?.method ?? "GET"} ${path}`)
    })
    await user.click(screen.getByRole("button", { name: "提交执行记录" }))
    expect(await screen.findByText(/已登记 1 条执行记录/)).toBeInTheDocument()
  })

  it("surfaces server 409 requirement_coverage_incomplete verbatim including missing keys", async () => {
    const user = userEvent.setup()
    mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
      if (path === `/api/v1/projects/${projectId}/test-plans`) return Promise.resolve({ items: [makePlan({ status: "draft" })] })
      if (path === `/api/v1/test-plans/tp-1/review` && options?.method === "PATCH") {
        return Promise.reject(
          new ApiClientError(
            {
              code: "requirement_coverage_incomplete",
              message: "每条批准需求至少需要一条测试用例或明确人工验收方式。",
              details: { missing_requirement_keys: ["R-003", "R-004"] },
            },
            409,
          ),
        )
      }
      throw new Error(`unexpected ${options?.method ?? "GET"} ${path}`)
    })

    render(<TestPlansPanel projectId={projectId} canManage tasks={tasks} />)
    await screen.findByText("草稿")
    await user.click(screen.getByRole("button", { name: "批准" }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("requirement_coverage_incomplete")
    expect(alert).toHaveTextContent("每条批准需求至少需要一条测试用例或明确人工验收方式。")
    expect(alert).toHaveTextContent("缺失需求：R-003, R-004")
  })
})
