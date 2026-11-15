// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  user: { id: "leader-1", role: "project_lead" },
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))

import { AgentsConsole } from "../../src/renderer/src/agents/AgentsConsole"

const projectId = "proj-ta8"

function runRow(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    id: "run-abcdef1234567890",
    project_id: projectId,
    agent_id: "agent-1234567890",
    status: "completed",
    capability_used: "agent.code.write",
    initiated_by_user_id: "user-1",
    context_ref: "agent-workspaces/x/context.md",
    token_cost: 1200,
    duration_ms: 4300,
    exit_code: 0,
    degraded: false,
    degraded_reason: null,
    fallback_level: null,
    retry_of: null,
    idempotency_key: "k1",
    cost_owner_type: "project",
    cost_owner_id: null,
    handoff_user_id: null,
    difficulty: "standard",
    created_at: "2026-11-07T08:00:00",
    updated_at: "2026-11-07T08:01:00",
    ...overrides,
  }
}

function costSummary(): Record<string, unknown> {
  return { scope: "project", project_id: projectId, items: [], total_token_cost: 3200, monthly: { "2026-11": 3200 } }
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it("渲染 run 列表与项目成本汇总（列表→成本两面板）", async () => {
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.resolve({ items: [runRow()], truncated: false })
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<AgentsConsole projectId={projectId} />)
  expect(await screen.findByText("已完成")).toBeInTheDocument()
  expect(screen.getByText("agent.code.write")).toBeInTheDocument()
  expect(screen.getByText("3200")).toBeInTheDocument() // 成本汇总
  expect(screen.getByText(/2026-11=3200/)).toBeInTheDocument()
})

it("详情展开拉 run 详情与工具调用（详情+工具调用面板）", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.resolve({ items: [runRow({ status: "succeeded_but_receipt_invalid" })], truncated: false })
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    if (path === "/api/v1/agents/runs/run-abcdef1234567890" && options?.method === "GET") {
      return Promise.resolve(runRow({
        agent: { name: "ZCode 沙箱智能体", kind: "zcode" },
        artifacts: [{ id: "art-1", kind: "doc", storage_ref: "output/plan.md", sha256: "a".repeat(64), reviewed: false, linked_solution_id: null }],
      }))
    }
    if (path === "/api/v1/agents/runs/run-abcdef1234567890/tool-calls" && options?.method === "GET") {
      return Promise.resolve({
        items: [{ id: "call-1", tool_name: "read_file", decision: "allowed", capability: "fs.read", reason: null, duration_ms: 12 }],
        denied_count: 0,
      })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<AgentsConsole projectId={projectId} />)
  expect(await screen.findByText("成功但回执无效")).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "详情" }))
  expect(await screen.findByText("ZCode 沙箱智能体（zcode）")).toBeInTheDocument()
  expect(screen.getByText("output/plan.md")).toBeInTheDocument()
  expect(screen.getByText(/aaaaaaaaaaaa…/)).toBeInTheDocument()
  expect(screen.getByText("read_file")).toBeInTheDocument()
  expect(screen.getByText("放行")).toBeInTheDocument()
})

it("详情收起后再次展开重新拉取；收起不重复请求", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.resolve({ items: [runRow()], truncated: false })
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    if (path === "/api/v1/agents/runs/run-abcdef1234567890" && options?.method === "GET") {
      return Promise.resolve(runRow({ agent: { name: "ZCode 沙箱智能体", kind: "zcode" }, artifacts: [] }))
    }
    if (path === "/api/v1/agents/runs/run-abcdef1234567890/tool-calls" && options?.method === "GET") {
      return Promise.resolve({ items: [], denied_count: 0 })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<AgentsConsole projectId={projectId} />)
  await user.click(await screen.findByRole("button", { name: "详情" }))
  await screen.findByText("运行详情")
  await user.click(screen.getByRole("button", { name: "收起" }))
  await waitFor(() => expect(screen.queryByText("运行详情")).not.toBeInTheDocument())
  const detailCalls = mocks.apiRequest.mock.calls.filter((call) => String(call[0]) === "/api/v1/agents/runs/run-abcdef1234567890").length
  expect(detailCalls).toBe(1)
})

it("truncated 标记呈现「更早的记录未列出」", async () => {
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.resolve({ items: [runRow()], truncated: true })
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<AgentsConsole projectId={projectId} />)
  expect(await screen.findByText("已显示最近的运行，更早的记录未列出。")).toBeInTheDocument()
})

it("服务端错误（403 等）原样呈现", async () => {
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.reject(new ApiClientError({ code: "project_forbidden", message: "无权访问该项目。" }, 403))
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<AgentsConsole projectId={projectId} />)
  expect(await screen.findByRole("alert")).toHaveTextContent("无权访问该项目。")
})

it("空列表呈现空态文案", async () => {
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.resolve({ items: [], truncated: false })
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    throw new Error(`unexpected api call: ${path}`)
  })
  render(<AgentsConsole projectId={projectId} />)
  expect(await screen.findByText("本项目还没有智能体运行记录。")).toBeInTheDocument()
})

// —— T-B1（goal-tb tb2）：产物人工接受面 ——

it("canManage 时产物行可标记复核并回拉详情（PATCH reviewed:true）", async () => {
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: string }) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.resolve({ items: [runRow()], truncated: false })
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    if (path === "/api/v1/agents/runs/run-abcdef1234567890" && options?.method === "GET") {
      return Promise.resolve(runRow({
        agent: { name: "ZCode 沙箱智能体", kind: "zcode" },
        artifacts: [{ id: "art-1", kind: "doc", storage_ref: "output/plan.md", sha256: "a".repeat(64), reviewed: false, linked_solution_id: null }],
      }))
    }
    if (path === "/api/v1/agents/runs/run-abcdef1234567890/artifacts/art-1" && options?.method === "PATCH") {
      expect(options.body).toEqual({ reviewed: true })
      return Promise.resolve({ reviewed: true })
    }
    if (path === "/api/v1/agents/runs/run-abcdef1234567890/tool-calls" && options?.method === "GET") {
      return Promise.resolve({ items: [], denied_count: 0 })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<AgentsConsole projectId={projectId} canManage />)
  fireEvent.click(await screen.findByText("详情"))
  const button = await screen.findByText("标记复核")
  fireEvent.click(button)
  expect(await screen.findByText("已标记复核。")).toBeInTheDocument()
  expect(mocks.apiRequest.mock.calls.some((call) => call[0] === "/api/v1/agents/runs/run-abcdef1234567890/artifacts/art-1")).toBe(true)
})

it("canManage 缺省 false：产物行无复核操作按钮（写闸在服务端，呈现同构显隐）", async () => {
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.resolve({ items: [runRow()], truncated: false })
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    if (path === "/api/v1/agents/runs/run-abcdef1234567890" && options?.method === "GET") {
      return Promise.resolve(runRow({
        agent: { name: "ZCode 沙箱智能体", kind: "zcode" },
        artifacts: [{ id: "art-1", kind: "doc", storage_ref: "output/plan.md", sha256: "a".repeat(64), reviewed: false, linked_solution_id: null }],
      }))
    }
    if (path === "/api/v1/agents/runs/run-abcdef1234567890/tool-calls" && options?.method === "GET") {
      return Promise.resolve({ items: [], denied_count: 0 })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })
  render(<AgentsConsole projectId={projectId} />)
  fireEvent.click(await screen.findByText("详情"))
  await screen.findByText("未复核")
  expect(screen.queryByText("标记复核")).toBeNull()
})

// —— N3c G-15：跨 run 终审队列与批量复核（写语义零新增：逐件既有 PATCH）——

function baseMocks(): (path: string, options?: { method?: string; body?: unknown }) => Promise<unknown> {
  return (path: string, options?: { method?: string; body?: unknown }) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.resolve({
        items: [
          runRow({ id: "run-aaaaaaaa12345678", status: "completed" }),
          runRow({ id: "run-bbbbbbbb12345678", status: "failed" }),
        ],
        truncated: false,
      })
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    if (path === "/api/v1/agents/runs/run-aaaaaaaa12345678" && options?.method === "GET") {
      return Promise.resolve(runRow({
        id: "run-aaaaaaaa12345678",
        artifacts: [
          { id: "art-a1", kind: "doc", storage_ref: "output/plan.md", sha256: "a".repeat(64), reviewed: false, linked_solution_id: null },
          { id: "art-a2", kind: "doc", storage_ref: "output/done.md", sha256: "b".repeat(64), reviewed: true, linked_solution_id: null },
        ],
      }))
    }
    if (path === "/api/v1/agents/runs/run-bbbbbbbb12345678" && options?.method === "GET") {
      return Promise.resolve(runRow({
        id: "run-bbbbbbbb12345678",
        artifacts: [
          { id: "art-b1", kind: "config", storage_ref: "output/settings.json", sha256: "c".repeat(64), reviewed: false, linked_solution_id: null },
        ],
      }))
    }
    if (/\/artifacts\/art-(a1|b1)$/.test(path) && options?.method === "PATCH") {
      expect(options.body).toEqual({ reviewed: true })
      return Promise.resolve({ reviewed: true })
    }
    if (/\/runs\/run-[ab]{8}12345678\/tool-calls$/.test(path) && options?.method === "GET") {
      return Promise.resolve({ items: [], denied_count: 0 })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  }
}

it("G-15：勾选多 run 汇总未复核产物进终审队列，批量标记复核＝逐件 PATCH＋回执就地呈现", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation(baseMocks())
  render(<AgentsConsole projectId={projectId} canManage />)
  await user.click(await screen.findByRole("checkbox", { name: "选择运行 run-aaaa" }))
  await user.click(await screen.findByRole("checkbox", { name: "选择运行 run-bbbb" }))
  // 队列只收未复核产物（art-a2 已复核不出现）
  expect(await screen.findByText("output/plan.md")).toBeInTheDocument()
  expect(screen.getByText("output/settings.json")).toBeInTheDocument()
  expect(screen.queryByText("output/done.md")).toBeNull()
  // 批量＝逐件既有 PATCH
  await user.click(screen.getByRole("button", { name: "批量标记复核（2）" }))
  expect(await screen.findByText("批量复核完成：成功 2。")).toBeInTheDocument()
  const patchCalls = mocks.apiRequest.mock.calls.filter(
    (call) => typeof call[0] === "string" && /\/artifacts\/art-(a1|b1)$/.test(String(call[0])) && (call[1] as { method?: string } | undefined)?.method === "PATCH",
  )
  expect(patchCalls).toHaveLength(2)
})

it("G-15：批量复核逐件结果如实呈现（1 成功 1 失败不吞错）", async () => {
  const user = userEvent.setup()
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (/\/artifacts\/art-b1$/.test(path) && options?.method === "PATCH") {
      return Promise.reject(new ApiClientError({ code: "project_forbidden", message: "产物复核需要项目管理权限。" }, 403))
    }
    return baseMocks()(path, options)
  })
  render(<AgentsConsole projectId={projectId} canManage />)
  await user.click(await screen.findByRole("checkbox", { name: "选择运行 run-aaaa" }))
  await user.click(await screen.findByRole("checkbox", { name: "选择运行 run-bbbb" }))
  await user.click(await screen.findByRole("button", { name: "批量标记复核（2）" }))
  expect(await screen.findByText("批量复核完成：成功 1，失败 1。")).toBeInTheDocument()
})

// —— N3c T-A10：产物就地预览/下载（content 路由 sha256 自证；降级显式呈现）——

function contentPayload(storageRef: string): Record<string, unknown> {
  const text = storageRef.endsWith(".json") ? '{"model":"glm","tokens":16}' : "# 计划\n交付内容"
  // 服务端 base64 编码的是 UTF-8 字节；jsdom 的 btoa 只收 Latin1，须先过 TextEncoder
  const bytes = new TextEncoder().encode(text)
  let binary = ""
  bytes.forEach((byte) => { binary += String.fromCharCode(byte) })
  return {
    run_id: "run-aaaaaaaa12345678",
    artifact_id: "art-a1",
    kind: "doc",
    storage_ref: storageRef,
    sha256: "a".repeat(64),
    size: bytes.length,
    mime: "text/markdown",
    reviewed: false,
    content_base64: btoa(binary),
  }
}

it("T-A10：队列产物预览拉 content 路由并渲染；下载走 anchor（原件落本地）", async () => {
  const user = userEvent.setup()
  const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {})
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === "/api/v1/agents/runs/run-aaaaaaaa12345678/artifacts/art-a1/content" && options?.method === "GET") {
      return Promise.resolve(contentPayload("run-aaaa/output/plan.md"))
    }
    return baseMocks()(path, options)
  })
  render(<AgentsConsole projectId={projectId} canManage />)
  await user.click(await screen.findByRole("checkbox", { name: "选择运行 run-aaaa" }))
  await user.click(await screen.findByRole("button", { name: "预览" }))
  // doc 类走 MemoMarkdown 同构：「# 计划」渲染为标题，正文段落可断言
  expect(await screen.findByRole("heading", { name: "计划" })).toBeInTheDocument()
  expect(screen.getByText("交付内容")).toBeInTheDocument()
  await user.click(screen.getAllByRole("button", { name: "下载" })[0])
  await waitFor(() => expect(clickSpy).toHaveBeenCalled())
  const anchor = clickSpy.mock.instances[0] as HTMLAnchorElement
  expect(anchor.download).toBe("plan.md")
  clickSpy.mockRestore()
})

it("T-A10：容器态降级显式呈现（content 404 错误不吞不静默）", async () => {
  const user = userEvent.setup()
  const { ApiClientError } = await import("../../src/renderer/src/api/client")
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path.endsWith("/content")) {
      return Promise.reject(new ApiClientError({ code: "artifact_content_unavailable", message: "产物原件不在服务端可见的工作区（宿主裸跑态在部署机本地可用；容器部署态读不到宿主路径）。" }, 404))
    }
    return baseMocks()(path, options)
  })
  render(<AgentsConsole projectId={projectId} canManage />)
  await user.click(await screen.findByRole("checkbox", { name: "选择运行 run-aaaa" }))
  await user.click(await screen.findByRole("button", { name: "预览" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("产物原件不在服务端可见的工作区")
})

it("T-A10：非 canManage 无预览/下载按钮（服务端 can_manage 同尺，呈现同构显隐）", async () => {
  mocks.apiRequest.mockImplementation(baseMocks())
  render(<AgentsConsole projectId={projectId} />)
  fireEvent.click((await screen.findAllByText("详情"))[0])
  await screen.findByText("未复核")
  expect(screen.queryByRole("button", { name: "预览" })).toBeNull()
  expect(screen.queryByRole("button", { name: "下载" })).toBeNull()
  expect(screen.queryByRole("button", { name: "采纳为方案" })).toBeNull()
})

it("产物采纳为方案：canManage 在终态展示「采纳为方案」，POST adopt-solution 空 body 后回显「查看方案」并按 allowNextHashNavigation 跳转；幂等与非终态边界覆盖", async () => {
  const user = userEvent.setup()
  const {
    canAcceptHashNavigation,
    registerHashNavigationGuard,
  } = await import("../../src/renderer/src/routing/navigationGuard")
  const unregisterGuard = registerHashNavigationGuard(() => false)
  let linkedSolutionId: string | null = null
  const adoptCalls: { path: string; body: unknown }[] = []

  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.resolve({
        items: [
          runRow({ id: "run-term-1", status: "succeeded_but_receipt_invalid" }),
          runRow({ id: "run-running-2", status: "running" }),
        ],
        truncated: false,
      })
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    if (path === "/api/v1/agents/runs/run-term-1" && options?.method === "GET") {
      return Promise.resolve(
        runRow({
          id: "run-term-1",
          status: "succeeded_but_receipt_invalid",
          agent: { name: "ZCode 沙箱智能体", kind: "zcode" },
          artifacts: [
            {
              id: "art-adopt-1",
              kind: "doc",
              storage_ref: "output/solution.md",
              sha256: "b".repeat(64),
              reviewed: true,
              linked_solution_id: linkedSolutionId,
            },
          ],
        }),
      )
    }
    if (path === "/api/v1/agents/runs/run-term-1/tool-calls" && options?.method === "GET") {
      return Promise.resolve({ items: [], denied_count: 0 })
    }
    if (path === "/api/v1/agents/runs/run-running-2" && options?.method === "GET") {
      return Promise.resolve(
        runRow({
          id: "run-running-2",
          status: "running",
          agent: { name: "ZCode 沙箱智能体", kind: "zcode" },
          artifacts: [
            {
              id: "art-running-1",
              kind: "doc",
              storage_ref: "output/wip.md",
              sha256: "c".repeat(64),
              reviewed: false,
              linked_solution_id: null,
            },
          ],
        }),
      )
    }
    if (path === "/api/v1/agents/runs/run-running-2/tool-calls" && options?.method === "GET") {
      return Promise.resolve({ items: [], denied_count: 0 })
    }
    if (
      path === "/api/v1/agents/runs/run-term-1/artifacts/art-adopt-1/adopt-solution" &&
      options?.method === "POST"
    ) {
      adoptCalls.push({ path, body: options?.body })
      linkedSolutionId = "sol-adopted-99"
      return Promise.resolve({
        solution_id: "sol-adopted-99",
        run_id: "run-term-1",
        artifact_id: "art-adopt-1",
        adopted: true,
        duplicate: false,
        solution: { id: "sol-adopted-99", name: "AI 产物采纳方案·doc" },
      })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })

  window.location.hash = `#projects/${projectId}?tab=agents`
  render(<AgentsConsole projectId={projectId} canManage />)

  const detailButtons = await screen.findAllByRole("button", { name: "详情" })
  // 先展开 running 态：非终态不应出现「采纳为方案」
  await user.click(detailButtons[1])
  await screen.findByText("output/wip.md")
  expect(screen.queryByRole("button", { name: "采纳为方案" })).toBeNull()

  // 再展开 succeeded_but_receipt_invalid 终态：出现「采纳为方案」
  await user.click(detailButtons[0])
  await screen.findByText("output/solution.md")
  const adoptBtn = screen.getByRole("button", { name: "采纳为方案" })
  await user.click(adoptBtn)

  await waitFor(() => expect(adoptCalls).toHaveLength(1))
  expect(adoptCalls[0]).toEqual({
    path: "/api/v1/agents/runs/run-term-1/artifacts/art-adopt-1/adopt-solution",
    body: {},
  })

  expect(await screen.findByText(/已将该产物采纳为交付方案/)).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "采纳为方案" })).toBeNull()

  const viewBtn = screen.getByRole("button", { name: "查看方案" })
  try {
    await user.click(viewBtn)
    const expectedHash = `#projects/${projectId}?tab=delivery&solution=sol-adopted-99`
    expect(window.location.hash).toBe(expectedHash)
    // 在 activeGuard 恒返 false 下，仅当 allowNextHashNavigation 已放行该目标时 canAcceptHashNavigation 才返回 true
    expect(canAcceptHashNavigation(expectedHash)).toBe(true)
  } finally {
    unregisterGuard()
  }
})

it("产物采纳幂等回执与只读跳转：linked_solution_id 非空在非 canManage 下仍展示「查看方案」；duplicate=true 展示幂等提示", async () => {
  const user = userEvent.setup()
  let linkedSolutionId: string | null = null
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    if (path === `/api/v1/agents/runs?project_id=${projectId}`) {
      return Promise.resolve({ items: [runRow({ id: "run-linked-1", status: "completed" })], truncated: false })
    }
    if (path === `/api/v1/agents/cost?scope=project&project_id=${projectId}`) {
      return Promise.resolve(costSummary())
    }
    if (path === "/api/v1/agents/runs/run-linked-1" && options?.method === "GET") {
      return Promise.resolve(
        runRow({
          id: "run-linked-1",
          status: "completed",
          agent: { name: "ZCode 沙箱智能体", kind: "zcode" },
          artifacts: [
            {
              id: "art-linked-1",
              kind: "doc",
              storage_ref: "output/linked.md",
              sha256: "d".repeat(64),
              reviewed: true,
              linked_solution_id: linkedSolutionId,
            },
          ],
        }),
      )
    }
    if (path === "/api/v1/agents/runs/run-linked-1/tool-calls" && options?.method === "GET") {
      return Promise.resolve({ items: [], denied_count: 0 })
    }
    if (
      path === "/api/v1/agents/runs/run-linked-1/artifacts/art-linked-1/adopt-solution" &&
      options?.method === "POST"
    ) {
      linkedSolutionId = "sol-existing-1"
      return Promise.resolve({
        solution_id: "sol-existing-1",
        run_id: "run-linked-1",
        artifact_id: "art-linked-1",
        adopted: false,
        duplicate: true,
        solution: { id: "sol-existing-1", name: "既有方案" },
      })
    }
    throw new Error(`unexpected api call: ${options?.method ?? "GET"} ${path}`)
  })

  // 1) canManage 下触发 duplicate=true 幂等回执
  const { unmount } = render(<AgentsConsole projectId={projectId} canManage />)
  await user.click(await screen.findByRole("button", { name: "详情" }))
  await user.click(await screen.findByRole("button", { name: "采纳为方案" }))
  expect(await screen.findByText(/该产物已关联交付方案（幂等回执）/)).toBeInTheDocument()
  unmount()

  // 2) 非 canManage 下 linked_solution_id 非空仍可点击「查看方案」
  render(<AgentsConsole projectId={projectId} />)
  await user.click(await screen.findByRole("button", { name: "详情" }))
  const viewBtn = await screen.findByRole("button", { name: "查看方案" })
  expect(screen.queryByRole("button", { name: "采纳为方案" })).toBeNull()
  await user.click(viewBtn)
  expect(window.location.hash).toBe(`#projects/${projectId}?tab=delivery&solution=sol-existing-1`)
})

