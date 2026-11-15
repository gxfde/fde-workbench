// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  user: { id: "leader-1", role: "project_lead" },
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))

import { WorkflowConsole } from "../../src/renderer/src/workflows/WorkflowConsole"

const projectId = "proj-1"

function definition(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    id: "def-1",
    name: "周报汇总",
    description: "汇总门禁结果",
    status: "published",
    version: 2,
    published_at: "2026-11-04T08:00:00",
    dag_json: { nodes: [{ key: "gather" }, { key: "deliver" }] },
    ...overrides,
  }
}

function run(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    id: "run-abcdef1234567890",
    definition_id: "def-1",
    definition_version: 2,
    status: "running",
    error: null,
    started_at: "2026-11-04T09:00:00",
    finished_at: null,
    created_at: "2026-11-04T09:00:00",
    ...overrides,
  }
}

function mockApi(): void {
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === `/api/v1/projects/${projectId}/workflows`) {
      return Promise.resolve({ items: [definition()] })
    }
    if (path === `/api/v1/projects/${projectId}/workflow-runs` && options?.method === "GET") {
      return Promise.resolve({ items: [run()], truncated: false })
    }
    if (path === `/api/v1/projects/${projectId}/workflow-runs/run-abcdef1234567890` && options?.method === "GET") {
      return Promise.resolve({
        run: run({ nodes: [{ node_key: "gather", node_type: "call", status: "succeeded", attempt: 1, error: null }] }),
      })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
}

function callCount(path: string, method?: string): number {
  return mocks.apiRequest.mock.calls.filter(
    (call) =>
      String(call[0]) === path &&
      (method === undefined || (call[1] as { method?: string } | undefined)?.method === method),
  ).length
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
  mockApi()
})

afterEach(() => {
  cleanup()
})

it("renders definitions and runs with status labels and node overview", async () => {
  render(<WorkflowConsole projectId={projectId} canManage={false} />)
  expect(await screen.findByText("周报汇总")).toBeInTheDocument()
  expect(screen.getByText("已发布")).toBeInTheDocument()
  expect(screen.getByText(/2 个节点/)).toBeInTheDocument()
  expect(screen.getByText("运行中")).toBeInTheDocument()
  expect(screen.getByText("run-abcd")).toBeInTheDocument()
  // 运行中：不可恢复（resume 仅 failed），不可取消（无 canManage）
  expect(screen.queryByRole("button", { name: "取消" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "恢复" })).not.toBeInTheDocument()
})

it("shows cancel and resume buttons for canManage and posts cancel", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `/api/v1/projects/${projectId}/workflows`) return Promise.resolve({ items: [] })
    if (path === `/api/v1/projects/${projectId}/workflow-runs` && options?.method === "GET") {
      return Promise.resolve({
        items: [run({ status: "failed", error: "transient:临时失败。" }), run({ id: "run-live00000000000001", status: "queued" })],
        truncated: false,
      })
    }
    if (path?.endsWith("/cancel")) return Promise.resolve({ run: run({ status: "cancelled", finished_at: "2026-11-04T09:30:00" }), cancelled: true })
    if (path?.endsWith("/resume")) return Promise.resolve({ run: run({ status: "running" }), reset_nodes: 1 })
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<WorkflowConsole projectId={projectId} canManage />)
  expect(await screen.findByText("失败")).toBeInTheDocument()
  // failed 已是终态：仅恢复（resume）；queued 非终态：可取消
  expect(screen.getAllByRole("button", { name: "取消" }).length).toBe(1)
  expect(screen.getByRole("button", { name: "恢复" })).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "恢复" }))
  await waitFor(() => expect(callCount(`/api/v1/projects/${projectId}/workflow-runs/run-abcdef1234567890/resume`, "POST")).toBe(1))
  await waitFor(() => expect(screen.getByText("运行中")).toBeInTheDocument())
})

it("surfaces server 409 messages instead of swallowing them", async () => {
  const user = userEvent.setup()
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `/api/v1/projects/${projectId}/workflows`) return Promise.resolve({ items: [] })
    if (path === `/api/v1/projects/${projectId}/workflow-runs` && options?.method === "GET") {
      return Promise.resolve({ items: [run({ status: "running" })], truncated: false })
    }
    // 竞态：行还是 running 时别人已取消 → 服务端 409；控制台原样呈现
    if (path?.endsWith("/cancel")) {
      return Promise.reject(new ApiClientError({ code: "already_terminal", message: "运行已终态（cancelled），不能取消。" }, 409))
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<WorkflowConsole projectId={projectId} canManage />)
  await user.click(await screen.findByRole("button", { name: "取消" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("运行已终态（cancelled），不能取消。")
})

it("expands run detail and fetches the node tree on demand", async () => {
  const user = userEvent.setup()
  render(<WorkflowConsole projectId={projectId} canManage={false} />)
  await user.click(await screen.findByRole("button", { name: "详情" }))
  await waitFor(() =>
    expect(callCount(`/api/v1/projects/${projectId}/workflow-runs/run-abcdef1234567890`, "GET")).toBe(1),
  )
  expect(await screen.findByText("gather")).toBeInTheDocument()
  expect(screen.getByText("成功")).toBeInTheDocument()
})

it("notes truncated run lists honestly", async () => {
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `/api/v1/projects/${projectId}/workflows`) return Promise.resolve({ items: [] })
    if (path === `/api/v1/projects/${projectId}/workflow-runs`) {
      return Promise.resolve({ items: [run()], truncated: true })
    }
    throw new Error(`unexpected api call: GET ${path}`)
  })
  render(<WorkflowConsole projectId={projectId} canManage={false} />)
  expect(await screen.findByText("已显示最近的运行，更早的记录未列出。")).toBeInTheDocument()
})

// ── 第二批桌面 AI 辅助闭环·任务 3：从方案生成草稿（双来源）＋采纳＋干跑＋发布 ──

const draftDag = {
  nodes: [
    { key: "gather_inputs", type: "call", ref: "workbench.project.read@1", depends_on: [] },
    { key: "human_review", type: "human_approval", capability: "workbench.write", depends_on: ["gather_inputs"] },
    { key: "apply_changes", type: "call", ref: "workbench.write@1", depends_on: ["human_review"] },
  ],
}

const aiDraftPayload = {
  draft: {
    dag_json: draftDag,
    validate: {
      valid: true,
      errors: [],
      warnings: [{ code: "external_effect", message: "节点 apply_changes 声明外部副作用，发布前请确认审批门。", node: "apply_changes" }],
      order: ["gather_inputs", "human_review", "apply_changes"],
    },
    dag_sha256: "abc123def456abc123def456abc123def456abc123def456abc123def456abc1",
    plan_ref: "plan-ap-1",
    implementation_skill_ref: "sop-deploy@3",
  },
  model: "MiniMax-M3.1-Flash",
  prompt_version: "workflow-dag-draft-prompt-v1",
}

function mockSourceLists(): void {
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === `/api/v1/projects/${projectId}/workflows` && options?.method === "GET") {
      return Promise.resolve({ items: [] })
    }
    if (path === `/api/v1/projects/${projectId}/workflow-runs` && options?.method === "GET") {
      return Promise.resolve({ items: [], truncated: false })
    }
    if (path === `/api/v1/projects/${projectId}/delivery-plans` && options?.method === "GET") {
      return Promise.resolve({
        items: [
          { id: "plan-ap-1", title: "交付方案 v1", status: "approved", version: 1 },
          { id: "plan-pub-1", title: "交付方案 v2", status: "published", version: 2 },
          { id: "plan-dr-1", title: "交付方案 v3", status: "draft", version: 3 },
          { id: "plan-sup-1", title: "交付方案 v0", status: "superseded", version: 0 },
        ],
      })
    }
    if (path === "/api/v1/extensions" && options?.method === "GET") {
      return Promise.resolve({
        skills: [
          { key: "sop-deploy", name: "部署 SOP", status: "published", current_version: 3 },
          { key: "sop-draft", name: "草稿 SOP", status: "draft", current_version: 1 },
        ],
      })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
}

it("filters plan options to approved/published and skill options to published (key@version refs)", async () => {
  mockSourceLists()
  render(<WorkflowConsole projectId={projectId} canManage isAdmin />)

  const planSelect = (await screen.findByLabelText("交付方案")) as HTMLSelectElement
  const planOptions = Array.from(planSelect.options).map((o) => o.value)
  expect(planOptions).toEqual(["", "plan-ap-1", "plan-pub-1"])

  const skillSelect = screen.getByLabelText("实施技能") as HTMLSelectElement
  const skillOptions = Array.from(skillSelect.options).map((o) => o.value)
  expect(skillOptions).toEqual(["", "sop-deploy@3"])

  expect(screen.getByLabelText("审批能力")).toHaveValue("workbench.write")
})

it("posts compile draft-from-plan with the exact dual-source body and reloads definitions", async () => {
  const user = userEvent.setup()
  let compileCalled = 0
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === `/api/v1/projects/${projectId}/workflows` && options?.method === "GET") {
      return Promise.resolve({
        items: compileCalled
          ? [{ id: "def-new", name: "交付方案 v1 工作流", description: null, status: "draft", version: 1, published_at: null, dag_json: draftDag }]
          : [],
      })
    }
    if (path === `/api/v1/projects/${projectId}/workflow-runs` && options?.method === "GET") {
      return Promise.resolve({ items: [], truncated: false })
    }
    if (path === `/api/v1/projects/${projectId}/delivery-plans` && options?.method === "GET") {
      return Promise.resolve({ items: [{ id: "plan-ap-1", title: "交付方案 v1", status: "approved", version: 1 }] })
    }
    if (path === "/api/v1/extensions" && options?.method === "GET") {
      return Promise.resolve({ skills: [{ key: "sop-deploy", name: "部署 SOP", status: "published", current_version: 3 }] })
    }
    if (path === `/api/v1/projects/${projectId}/workflows/draft-from-plan` && options?.method === "POST") {
      compileCalled += 1
      expect(options.body).toEqual({
        plan_id: "plan-ap-1",
        implementation_skill_ref: "sop-deploy@3",
        approval_capability: "workbench.write",
      })
      return Promise.resolve({ definition: { id: "def-new" }, provenance: {} })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })

  render(<WorkflowConsole projectId={projectId} canManage />)
  await user.selectOptions(await screen.findByLabelText("交付方案"), "plan-ap-1")
  await user.selectOptions(screen.getByLabelText("实施技能"), "sop-deploy@3")
  await user.click(screen.getByRole("button", { name: "编译草稿" }))

  expect(await screen.findByText("交付方案 v1 工作流")).toBeInTheDocument()
  expect(screen.getByText("草稿")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "干跑校验" })).toBeInTheDocument()
  // isAdmin 未传时（默认 false）发布按钮不出现
  expect(screen.queryByRole("button", { name: "发布" })).not.toBeInTheDocument()
})

it("posts generate-ai-draft, previews nodes/validate/sha256 inline, and adopts with exactly name+dag(+description)", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === `/api/v1/projects/${projectId}/workflows` && options?.method === "GET") {
      return Promise.resolve({ items: [] })
    }
    if (path === `/api/v1/projects/${projectId}/workflow-runs` && options?.method === "GET") {
      return Promise.resolve({ items: [], truncated: false })
    }
    if (path === `/api/v1/projects/${projectId}/delivery-plans` && options?.method === "GET") {
      return Promise.resolve({ items: [{ id: "plan-ap-1", title: "交付方案 v1", status: "approved", version: 1 }] })
    }
    if (path === "/api/v1/extensions" && options?.method === "GET") {
      return Promise.resolve({ skills: [{ key: "sop-deploy", name: "部署 SOP", status: "published", current_version: 3 }] })
    }
    if (path === `/api/v1/projects/${projectId}/workflows/generate-ai-draft` && options?.method === "POST") {
      expect(options.body).toEqual({
        plan_id: "plan-ap-1",
        implementation_skill_ref: "sop-deploy@3",
        approval_capability: "workbench.write",
      })
      return Promise.resolve(aiDraftPayload)
    }
    if (path === `/api/v1/projects/${projectId}/workflows` && options?.method === "POST") {
      // 采纳恰含 name/dag(+description)——validate 明细与 sha256 等返件字段不进 body
      expect(options.body).toEqual({
        name: "交付方案 v1 工作流",
        dag: draftDag,
        description: "AI 起草后人工采纳",
      })
      return Promise.resolve({ definition: { id: "def-adopted", name: "交付方案 v1 工作流" } })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })

  render(<WorkflowConsole projectId={projectId} canManage isAdmin />)
  await user.selectOptions(await screen.findByLabelText("交付方案"), "plan-ap-1")
  await user.selectOptions(screen.getByLabelText("实施技能"), "sop-deploy@3")
  await user.click(screen.getByRole("button", { name: "AI 起草草稿" }))

  // 返件就地预览：节点表 + validate 明细 + dag_sha256
  expect(await screen.findByLabelText("AI 起草预览")).toBeInTheDocument()
  expect(screen.getAllByText("gather_inputs").length).toBeGreaterThan(0)
  expect(screen.getAllByText("human_review").length).toBeGreaterThan(0)
  expect(screen.getAllByText("apply_changes").length).toBeGreaterThan(0)
  expect(screen.getByText(/干跑校验：通过/)).toBeInTheDocument()
  expect(screen.getByText(/abc123def456abc1/)).toBeInTheDocument()
  expect(screen.getByText(/外部副作用/)).toBeInTheDocument()
  expect((screen.getByLabelText("定义名称") as HTMLInputElement).value).toBe("交付方案 v1 工作流")

  await user.type(screen.getByLabelText("定义描述"), "AI 起草后人工采纳")
  await user.click(screen.getByRole("button", { name: "采纳为定义" }))
  await waitFor(() => expect(screen.queryByLabelText("AI 起草预览")).not.toBeInTheDocument())
})

it("posts dry-run validate for draft definitions and renders details inline", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === `/api/v1/projects/${projectId}/workflows` && options?.method === "GET") {
      return Promise.resolve({
        items: [{ id: "def-1", name: "周报汇总", description: null, status: "draft", version: 1, published_at: null, dag_json: draftDag }],
      })
    }
    if (path === `/api/v1/projects/${projectId}/workflow-runs` && options?.method === "GET") {
      return Promise.resolve({ items: [], truncated: false })
    }
    if (path === `/api/v1/projects/${projectId}/delivery-plans` && options?.method === "GET") {
      return Promise.resolve({ items: [] })
    }
    if (path === "/api/v1/extensions" && options?.method === "GET") {
      return Promise.resolve({ skills: [] })
    }
    if (path === `/api/v1/projects/${projectId}/workflows/def-1/validate` && options?.method === "POST") {
      return Promise.resolve({
        valid: true,
        errors: [],
        warnings: [{ code: "external_effect", message: "节点 apply_changes 声明外部副作用。", node: "apply_changes" }],
        order: ["gather_inputs", "human_review", "apply_changes"],
        version: 1,
        content_sha256: "deadbeef",
      })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })

  render(<WorkflowConsole projectId={projectId} canManage isAdmin />)
  await user.click(await screen.findByRole("button", { name: "干跑校验" }))

  expect(await screen.findByText(/干跑校验：通过（无错误）/)).toBeInTheDocument()
  expect(screen.getByText(/1 个告警/)).toBeInTheDocument()
  expect(screen.getByText(/apply_changes · external_effect · 节点 apply_changes 声明外部副作用。/)).toBeInTheDocument()
})

it("shows the publish button only for admin and posts publish with reload", async () => {
  const user = userEvent.setup()
  let published = false
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === `/api/v1/projects/${projectId}/workflows` && options?.method === "GET") {
      return Promise.resolve({
        items: [{ id: "def-1", name: "周报汇总", description: null, status: published ? "published" : "draft", version: 1, published_at: null, dag_json: draftDag }],
      })
    }
    if (path === `/api/v1/projects/${projectId}/workflow-runs` && options?.method === "GET") {
      return Promise.resolve({ items: [], truncated: false })
    }
    if (path === `/api/v1/projects/${projectId}/delivery-plans` && options?.method === "GET") {
      return Promise.resolve({ items: [] })
    }
    if (path === "/api/v1/extensions" && options?.method === "GET") {
      return Promise.resolve({ skills: [] })
    }
    if (path === `/api/v1/projects/${projectId}/workflows/def-1/publish` && options?.method === "POST") {
      published = true
      return Promise.resolve({ definition: { id: "def-1" }, version: 1, content_sha256: "deadbeef" })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })

  render(<WorkflowConsole projectId={projectId} canManage isAdmin />)
  await user.click(await screen.findByRole("button", { name: "发布" }))

  await waitFor(() =>
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      `/api/v1/projects/${projectId}/workflows/def-1/publish`,
      expect.objectContaining({ method: "POST" }),
    ),
  )
  expect(await screen.findByText("已发布")).toBeInTheDocument()
  // 发布后回到已发布态：干跑校验/发布按钮消失，启动按钮出现
  expect(screen.queryByRole("button", { name: "发布" })).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "启动" })).toBeInTheDocument()
})

it("surfaces compile 422 skill_ref_not_published and ai-draft 409 ai_draft_contract_failed verbatim", async () => {
  const user = userEvent.setup()
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === `/api/v1/projects/${projectId}/workflows` && options?.method === "GET") {
      return Promise.resolve({ items: [] })
    }
    if (path === `/api/v1/projects/${projectId}/workflow-runs` && options?.method === "GET") {
      return Promise.resolve({ items: [], truncated: false })
    }
    if (path === `/api/v1/projects/${projectId}/delivery-plans` && options?.method === "GET") {
      return Promise.resolve({ items: [{ id: "plan-ap-1", title: "交付方案 v1", status: "approved", version: 1 }] })
    }
    if (path === "/api/v1/extensions" && options?.method === "GET") {
      return Promise.resolve({ skills: [{ key: "sop-deploy", name: "部署 SOP", status: "published", current_version: 3 }] })
    }
    if (path === `/api/v1/projects/${projectId}/workflows/draft-from-plan` && options?.method === "POST") {
      return Promise.reject(
        new ApiClientError(
          { code: "skill_ref_not_published", message: "implementation_skill_ref 引用的技能版本不存在或未发布：sop-deploy@3。" },
          422,
        ),
      )
    }
    if (path === `/api/v1/projects/${projectId}/workflows/generate-ai-draft` && options?.method === "POST") {
      return Promise.reject(
        new ApiClientError(
          { code: "ai_draft_contract_failed", message: "AI 起草结果未通过契约校验（已自动重试仍失败：invalid_json），请重跑或更换模型。" },
          409,
        ),
      )
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })

  render(<WorkflowConsole projectId={projectId} canManage isAdmin />)
  await user.selectOptions(await screen.findByLabelText("交付方案"), "plan-ap-1")
  await user.selectOptions(screen.getByLabelText("实施技能"), "sop-deploy@3")

  await user.click(screen.getByRole("button", { name: "编译草稿" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("skill_ref_not_published")
  expect(screen.getByRole("alert")).toHaveTextContent("implementation_skill_ref 引用的技能版本不存在或未发布：sop-deploy@3。")

  await user.click(screen.getByRole("button", { name: "AI 起草草稿" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("ai_draft_contract_failed")
  expect(screen.getByRole("alert")).toHaveTextContent("请重跑或更换模型")
})
