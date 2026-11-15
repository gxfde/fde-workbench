// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ApiClientError } from "../../src/renderer/src/api/client"
import type { ProjectModuleDto } from "../../src/renderer/src/workbench/types"

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  user: { id: "leader-1", role: "project_lead" },
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))

import { DeliveryPlansPanel, type DeliveryPlanDto } from "../../src/renderer/src/plans/DeliveryPlansPanel"

const projectId = "proj-1"

const defaultModules: ProjectModuleDto[] = [
  {
    id: "mod-pov",
    module_key: "pov",
    name: "PoV 验证",
    description: "验证价值",
    status: "active",
    sort_order: 1,
    planned_start_date: "2026-08-21",
    planned_end_date: "2026-08-24",
  },
  {
    id: "mod-launch",
    module_key: "launch",
    name: "上线与移交",
    description: "生产上线",
    status: "active",
    sort_order: 2,
    planned_start_date: "2026-09-01",
    planned_end_date: "2026-09-10",
  },
]

function makePlan(overrides: Partial<DeliveryPlanDto> = {}): DeliveryPlanDto {
  return {
    id: "plan-1",
    project_id: projectId,
    title: "交付方案 v1",
    summary: "需求 2 条 · 事实 3 条",
    status: "draft",
    version: 1,
    source_extraction_id: null,
    created_by_user_id: "leader-1",
    reviewed_by_user_id: null,
    reviewed_at: null,
    review_comment: null,
    published_by_user_id: null,
    published_at: null,
    items: [
      {
        id: "item-1",
        item_type: "requirement",
        title: "需求 R-001：设备台账同步",
        detail: "验收标准：同步延迟 < 5 分钟",
        priority: "high",
        requirement_keys: ["R-001"],
        fact_ids: ["fact-1"],
        sort_order: 0,
        task_id: null,
      },
      {
        id: "item-2",
        item_type: "open_question",
        title: "待澄清：ERP 接口鉴权方式",
        detail: "需客户 IT 确认",
        priority: "medium",
        requirement_keys: [],
        fact_ids: ["fact-2"],
        sort_order: 1,
        task_id: null,
      },
    ],
    task_link_count: 0,
    ...overrides,
  }
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
})

afterEach(() => {
  cleanup()
})

describe("DeliveryPlansPanel", () => {
  it("renders plan cards with status, version, and item summary", async () => {
    mocks.apiRequest.mockResolvedValue({
      items: [
        makePlan({ status: "published", version: 2, title: "交付方案（AI 起草）v2", task_link_count: 1 }),
      ],
    })

    render(<DeliveryPlansPanel projectId={projectId} canManage={false} modules={defaultModules} />)

    expect(await screen.findByText("交付方案（AI 起草）v2")).toBeInTheDocument()
    expect(screen.getByText("已发布")).toBeInTheDocument()
    expect(screen.getByText(/v2 · 2 条目 · 已关联任务 1/)).toBeInTheDocument()
    expect(screen.getByText("需求 R-001：设备台账同步")).toBeInTheDocument()
    expect(screen.getByText("（需求：R-001）")).toBeInTheDocument()
  })

  it("hides all write buttons when canManage is false (zero writes)", async () => {
    mocks.apiRequest.mockResolvedValue({
      items: [
        makePlan({ id: "p-draft", status: "draft", version: 1 }),
        makePlan({ id: "p-approved", status: "approved", version: 2 }),
        makePlan({ id: "p-pub", status: "published", version: 3 }),
      ],
    })

    render(<DeliveryPlansPanel projectId={projectId} canManage={false} modules={defaultModules} />)

    expect(await screen.findByText("已批准")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "确定性生成" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "AI 起草" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "批准" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "驳回" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "发布" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "分解任务" })).not.toBeInTheDocument()
    expect(mocks.apiRequest).toHaveBeenCalledTimes(1)
  })

  it("triggers deterministic generate and AI generate-ai in parallel dual-source controls and reloads list", async () => {
    const user = userEvent.setup()
    let plans: DeliveryPlanDto[] = []
    mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
      if (path === `/api/v1/projects/${projectId}/delivery-plans` && options?.method === "GET") {
        return Promise.resolve({ items: plans })
      }
      if (path === `/api/v1/projects/${projectId}/delivery-plans/generate` && options?.method === "POST") {
        plans = [makePlan({ id: "plan-det", title: "交付方案 v1", version: 1 })]
        return Promise.resolve(plans[0])
      }
      if (path === `/api/v1/projects/${projectId}/delivery-plans/generate-ai` && options?.method === "POST") {
        plans = [
          makePlan({ id: "plan-ai", title: "交付方案（AI 起草）v2", version: 2 }),
          ...plans,
        ]
        return Promise.resolve({ plan: plans[0], created: true })
      }
      throw new Error(`unexpected ${options?.method} ${path}`)
    })

    render(<DeliveryPlansPanel projectId={projectId} canManage modules={defaultModules} />)
    expect(await screen.findByText("暂无交付方案草稿或已发布版本。")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "确定性生成" }))
    expect(await screen.findByText("交付方案 v1")).toBeInTheDocument()
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      `/api/v1/projects/${projectId}/delivery-plans/generate`,
      expect.objectContaining({ method: "POST", body: {} }),
    )

    await user.click(screen.getByRole("button", { name: "AI 起草" }))
    expect(await screen.findByText("交付方案（AI 起草）v2")).toBeInTheDocument()
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      `/api/v1/projects/${projectId}/delivery-plans/generate-ai`,
      expect.objectContaining({ method: "POST", body: {} }),
    )
  })

  it("reviews a draft plan (approve with inline comment / reject) and publishes an approved plan", async () => {
    const user = userEvent.setup()
    let currentPlan = makePlan({ status: "draft", version: 1 })
    mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
      if (path === `/api/v1/projects/${projectId}/delivery-plans` && options?.method === "GET") {
        return Promise.resolve({ items: [currentPlan] })
      }
      if (path === `/api/v1/delivery-plans/plan-1/review` && options?.method === "PATCH") {
        const body = options.body as { decision: string; comment?: string }
        currentPlan = {
          ...currentPlan,
          status: body.decision === "approved" ? "approved" : "superseded",
          review_comment: body.comment ?? null,
        }
        return Promise.resolve(currentPlan)
      }
      if (path === `/api/v1/delivery-plans/plan-1/publish` && options?.method === "POST") {
        currentPlan = { ...currentPlan, status: "published" }
        return Promise.resolve(currentPlan)
      }
      throw new Error(`unexpected ${options?.method} ${path}`)
    })

    render(<DeliveryPlansPanel projectId={projectId} canManage modules={defaultModules} />)
    expect(await screen.findByText("草稿")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "发布" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "分解任务" })).not.toBeInTheDocument()

    await user.type(screen.getByLabelText("审阅备注 v1"), "条目覆盖完整，同意进入实施")
    await user.click(screen.getByRole("button", { name: "批准" }))

    await waitFor(() =>
      expect(mocks.apiRequest).toHaveBeenCalledWith(
        "/api/v1/delivery-plans/plan-1/review",
        { method: "PATCH", body: { decision: "approved", comment: "条目覆盖完整，同意进入实施" } },
      ),
    )
    expect(await screen.findByText("已批准")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "发布" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "分解任务" })).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "发布" }))
    await waitFor(() =>
      expect(mocks.apiRequest).toHaveBeenCalledWith(
        "/api/v1/delivery-plans/plan-1/publish",
        { method: "POST", body: {} },
      ),
    )
    expect(await screen.findByText("已发布")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "发布" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "分解任务" })).toBeInTheDocument()
  })

  it("supports reject decision on draft plan", async () => {
    const user = userEvent.setup()
    let currentPlan = makePlan({ status: "draft", version: 1 })
    mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
      if (path === `/api/v1/projects/${projectId}/delivery-plans`) return Promise.resolve({ items: [currentPlan] })
      if (path === `/api/v1/delivery-plans/plan-1/review` && options?.method === "PATCH") {
        currentPlan = { ...currentPlan, status: "superseded" }
        return Promise.resolve(currentPlan)
      }
      throw new Error(`unexpected ${options?.method} ${path}`)
    })

    render(<DeliveryPlansPanel projectId={projectId} canManage modules={defaultModules} />)
    await user.click(await screen.findByRole("button", { name: "驳回" }))
    await waitFor(() =>
      expect(mocks.apiRequest).toHaveBeenCalledWith(
        "/api/v1/delivery-plans/plan-1/review",
        { method: "PATCH", body: { decision: "rejected" } },
      ),
    )
    expect(await screen.findByText("已取代")).toBeInTheDocument()
  })

  it("decomposes tasks in two stages: dry_run:true preview then dry_run:false commit and reloads", async () => {
    const user = userEvent.setup()
    const onTasksCreated = vi.fn()
    let currentPlan = makePlan({ status: "approved", version: 1 })
    mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
      if (path === `/api/v1/projects/${projectId}/delivery-plans` && options?.method === "GET") {
        return Promise.resolve({ items: [currentPlan] })
      }
      if (path === `/api/v1/delivery-plans/plan-1/tasks` && options?.method === "POST") {
        const body = options.body as { module_id: string; dry_run: boolean; item_ids?: string[] }
        if (body.dry_run) {
          return Promise.resolve({
            dry_run: true,
            created: [],
            skipped: [],
            preview: [
              {
                item_id: "item-1",
                item_type: "requirement",
                name: "需求 R-001：设备台账同步",
                description: "验收标准：同步延迟 < 5 分钟",
                duration_days: 1,
              },
            ],
          })
        }
        currentPlan = {
          ...currentPlan,
          task_link_count: 1,
          items: currentPlan.items.map((it) => (it.id === "item-1" ? { ...it, task_id: "task-99990000" } : it)),
        }
        return Promise.resolve({
          dry_run: false,
          created: [{ item_id: "item-1", task_id: "task-99990000" }],
          skipped: [],
          preview: [],
        })
      }
      throw new Error(`unexpected ${options?.method} ${path}`)
    })

    render(
      <DeliveryPlansPanel
        projectId={projectId}
        canManage
        modules={defaultModules}
        onTasksCreated={onTasksCreated}
      />,
    )

    await user.click(await screen.findByRole("button", { name: "分解任务" }))
    await user.selectOptions(screen.getByLabelText("目标模块"), "mod-launch")
    // 取消勾选第二条，仅分解第一条
    await user.click(screen.getByLabelText("待澄清：ERP 接口鉴权方式"))

    expect(screen.queryByRole("button", { name: "确认创建任务" })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "预览分解" }))

    await waitFor(() =>
      expect(mocks.apiRequest).toHaveBeenCalledWith(
        "/api/v1/delivery-plans/plan-1/tasks",
        {
          method: "POST",
          body: { module_id: "mod-launch", dry_run: true, item_ids: ["item-1"] },
        },
      ),
    )
    expect(await screen.findByText(/预览：将创建 1 条任务/)).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "确认创建任务" }))
    await waitFor(() =>
      expect(mocks.apiRequest).toHaveBeenCalledWith(
        "/api/v1/delivery-plans/plan-1/tasks",
        {
          method: "POST",
          body: { module_id: "mod-launch", dry_run: false, item_ids: ["item-1"] },
        },
      ),
    )
    expect(await screen.findByText(/已分解创建 1 条任务/)).toBeInTheDocument()
    expect(onTasksCreated).toHaveBeenCalledTimes(1)
  })

  it("disables task decomposition when project.modules has no active modules", async () => {
    mocks.apiRequest.mockResolvedValue({
      items: [makePlan({ status: "approved", version: 1 })],
    })

    render(<DeliveryPlansPanel projectId={projectId} canManage modules={[]} />)
    const btn = await screen.findByRole("button", { name: "分解任务" })
    expect(btn).toBeDisabled()
  })

  it("surfaces server 409 error code and message verbatim without swallowing", async () => {
    const user = userEvent.setup()
    mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
      if (path === `/api/v1/projects/${projectId}/delivery-plans` && options?.method === "GET") {
        return Promise.resolve({ items: [] })
      }
      if (path === `/api/v1/projects/${projectId}/delivery-plans/generate-ai` && options?.method === "POST") {
        return Promise.reject(
          new ApiClientError(
            { code: "no_approved_inputs", message: "尚无已批准需求或已接受事实：先完成访谈事实/需求审阅再生成方案。" },
            409,
          ),
        )
      }
      throw new Error(`unexpected ${options?.method} ${path}`)
    })

    render(<DeliveryPlansPanel projectId={projectId} canManage modules={defaultModules} />)
    await screen.findByText("暂无交付方案草稿或已发布版本。")
    await user.click(screen.getByRole("button", { name: "AI 起草" }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("no_approved_inputs")
    expect(alert).toHaveTextContent("尚无已批准需求或已接受事实：先完成访谈事实/需求审阅再生成方案。")
  })
})
