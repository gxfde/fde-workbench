// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  user: { id: "actor-1", role: "project_lead" },
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))

import { GateBoard } from "../../src/renderer/src/projects/GateBoard"
import { ApiClientError } from "../../src/renderer/src/api/client"

function gatesPath(projectId = "gate-project"): string {
  return `/api/v1/projects/${projectId}/gates`
}

function gateView(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    project_id: "gate-project",
    sop_phase: "S3",
    events: [],
    gates: [
      {
        gate_key: "G3",
        status: "pending",
        decision: null,
        submitted_at: null,
        decided_at: null,
        checklist: [
          { label: "深度诊断报告", claim_status: null, source_uri: null, content_hash: null },
          { label: "现状与痛点清单", claim_status: null, source_uri: null, content_hash: null },
        ],
        gate_name: "深度诊断完成门",
        node_key: "S3",
        exit_condition: "诊断报告双方确认",
        evidence_location: "fdeops .fde/",
        contract_payment: null,
        signer_role: null,
        fail_exit: null,
        decision_semantics: null,
        template_source_uri: null,
      },
    ],
    ...overrides,
  }
}

function evidenceRequestBodies(): Array<Record<string, unknown>> {
  return mocks.apiRequest.mock.calls
    .filter((call) => String(call[0]).endsWith("/gates/G3/evidence"))
    .map((call) => (call[1] as { body: Record<string, unknown> }).body)
}

function decisionRequestBodies(gateKey = "G6"): Array<Record<string, unknown>> {
  return mocks.apiRequest.mock.calls
    .filter((call) => String(call[0]).endsWith(`/gates/${gateKey}/decision`))
    .map((call) => (call[1] as { body: Record<string, unknown> }).body)
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
  mocks.apiRequest.mockResolvedValue(gateView())
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it("shows the failure banner instead of the board when loading fails", async () => {
  mocks.apiRequest.mockRejectedValue(new Error("网关不可达"))
  render(<GateBoard projectId="gate-project" canManage />)

  const alert = await screen.findByRole("alert")
  expect(alert).toHaveTextContent("门禁数据加载失败，请稍后重试。")
  expect(screen.queryByText("深度诊断完成门")).not.toBeInTheDocument()
})

it("renders gate status and claim badges for read-only viewers", async () => {
  mocks.apiRequest.mockResolvedValue(
    gateView({
      gates: [
        {
          gate_key: "G6",
          status: "evidence",
          decision: null,
          submitted_at: "2026-10-20T08:00:00+00:00",
          decided_at: null,
          checklist: [
            { label: "问题陈述（SCQA）", claim_status: "claimed", source_uri: "fdeops://x/y", content_hash: "a".repeat(64) },
          ],
          gate_name: "提案门",
          node_key: "S4",
          exit_condition: "提案书确认",
          evidence_location: "openfde assets/",
          contract_payment: null,
          signer_role: "客户负责人",
          fail_exit: null,
          decision_semantics: null,
          template_source_uri: null,
        },
      ],
    }),
  )
  render(<GateBoard projectId="gate-project" canManage={false} />)

  expect(await screen.findByRole("heading", { name: /G6 · 提案门/ })).toBeVisible()
  expect(screen.getByText("待核验")).toBeVisible()
  expect(screen.getByText("claimed")).toBeVisible()
  // 只读视图不出现提交/拍板操作
  expect(screen.queryByRole("button", { name: "提交证据" })).not.toBeInTheDocument()
})

it("submits per-item evidence pointers and reloads the board", async () => {
  const user = userEvent.setup()
  render(<GateBoard projectId="gate-project" canManage />)

  await user.click(await screen.findByRole("button", { name: "提交证据" }))

  const uris = screen.getAllByPlaceholderText("fdeops://engagements/<代号>/.fde/…")
  const hashes = screen.getAllByPlaceholderText("sha256（64 位）")
  expect(uris).toHaveLength(2)
  await user.type(uris[0], "fdeops://engagements/demo/.fde/report.md")
  await user.type(hashes[0], "a".repeat(64))
  await user.type(uris[1], "fdeops://engagements/demo/.fde/painpoints.md")
  await user.type(hashes[1], "b".repeat(64))

  await user.click(screen.getByRole("button", { name: "提交证据（标 claimed）" }))

  await waitFor(() => expect(evidenceRequestBodies()).toHaveLength(1))
  expect(evidenceRequestBodies()[0]).toEqual({
    items: [
      {
        label: "深度诊断报告",
        source_uri: "fdeops://engagements/demo/.fde/report.md",
        content_hash: "a".repeat(64),
      },
      {
        label: "现状与痛点清单",
        source_uri: "fdeops://engagements/demo/.fde/painpoints.md",
        content_hash: "b".repeat(64),
      },
    ],
  })
  // 提交成功后回读面板（第二次 GET）
  await waitFor(() => {
    expect(callCount(gatesPath(), "GET")).toBeGreaterThanOrEqual(2)
  })
})

it("keeps the filled evidence form and shows the error when the server rejects", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockImplementation(async (path: string, options?: { method?: string }) => {
    if (String(path).endsWith("/gates/G3/evidence")) {
      throw new Error("证据校验失败：sha256 与文件不符")
    }
    return gateView()
  })
  render(<GateBoard projectId="gate-project" canManage />)

  await user.click(await screen.findByRole("button", { name: "提交证据" }))
  const uris = screen.getAllByPlaceholderText("fdeops://engagements/<代号>/.fde/…")
  const hashes = screen.getAllByPlaceholderText("sha256（64 位）")
  await user.type(uris[0], "fdeops://engagements/demo/.fde/report.md")
  await user.type(hashes[0], "a".repeat(64))
  await user.type(uris[1], "fdeops://engagements/demo/.fde/painpoints.md")
  await user.type(hashes[1], "b".repeat(64))

  await user.click(screen.getByRole("button", { name: "提交证据（标 claimed）" }))

  const alert = await screen.findByRole("alert")
  expect(alert).toHaveTextContent("门禁数据加载失败，请稍后重试。")
  // 失败不收表单：已填的指针与 sha256 保留
  expect((screen.getAllByPlaceholderText("fdeops://engagements/<代号>/.fde/…")[0] as HTMLInputElement).value).toBe(
    "fdeops://engagements/demo/.fde/report.md",
  )
  expect(evidenceRequestBodies()).toHaveLength(1)
})

it("C2: opening the verify panel defaults every checklist item to unchecked", async () => {  const user = userEvent.setup()
  mocks.apiRequest.mockResolvedValue(
    gateView({
      gates: [
        {
          gate_key: "G6",
          status: "evidence",
          decision: null,
          submitted_at: "2026-10-20T08:00:00+00:00",
          decided_at: null,
          checklist: [
            { label: "问题陈述（SCQA）", claim_status: "claimed", source_uri: "fdeops://x/y", content_hash: "a".repeat(64) },
            { label: "解决方案概要", claim_status: "claimed", source_uri: "fdeops://x/z", content_hash: "b".repeat(64) },
          ],
          gate_name: "提案门",
          node_key: "S4",
          exit_condition: "提案书确认",
          evidence_location: "openfde assets/",
          contract_payment: null,
          signer_role: null,
          fail_exit: null,
          decision_semantics: null,
          template_source_uri: null,
        },
      ],
    }),
  )
  render(<GateBoard projectId="gate-project" canManage />)

  await user.click(await screen.findByRole("button", { name: "人工核验拍板" }))

  // claimed ≠ accepted：打开面板时默认全不勾（人工逐项核验后才算 accepted）
  const boxes = screen
    .getAllByRole("checkbox")
    .filter((el) => (el as HTMLInputElement).type === "checkbox") as HTMLInputElement[]
  expect(boxes.length).toBe(2)
  expect(boxes.every((el) => !el.checked)).toBe(true)
  // pass 过门要求全部接受：全不勾时拍板按钮禁用
  expect(screen.getByRole("button", { name: /拍板（接受 0\/2）/ })).toBeDisabled()
})

it("J2: summary badges follow the actual gate statuses, including unknown ones", async () => {
  // 旧实现把徽标状态写死成五态数组：服务端出现新状态时徽标被静默丢弃，
  // 汇总数字与界面显示对不上（J2）。新实现按 summary 的实际 key 遍历。
  const base = gateView().gates as Array<Record<string, unknown>>
  mocks.apiRequest.mockResolvedValue(
    gateView({
      gates: [
        { ...base[0], gate_key: "G1", status: "passed" },
        { ...base[0], gate_key: "G2", status: "passed" },
        { ...base[0], gate_key: "G3", status: "brand_new_state" },
      ],
    }),
  )
  render(<GateBoard projectId="gate-project" canManage />)

  expect(await screen.findByRole("heading", { name: /G1 ·/ })).toBeVisible()
  // 已过门 ×2
  expect(screen.getByText(/已过门 2/)).toBeVisible()
  // 未知状态照样出徽标（显示原值），不被硬编码五态吞掉
  expect(screen.getByText(/brand_new_state 1/)).toBeVisible()
})

const candidateEntry = {
  source_uri: "fdeops://engagements/demo/.fde/gates/G3/report.md",
  content_hash: "c".repeat(64),
  task_id: "task-1",
  task_key: "diagnosis_report",
  task_name: "产出诊断报告",
  proposed_by_user_id: "actor-1",
  proposed_at: "2026-11-04T08:00:00+00:00",
}

it("T-G1: renders task evidence candidates and adopts via the existing submit gate", async () => {
  const user = userEvent.setup()
  const base = gateView().gates as Array<Record<string, unknown>>
  mocks.apiRequest.mockResolvedValue(
    gateView({
      gates: [{ ...base[0], evidence_candidates: [candidateEntry] }],
    }),
  )
  render(<GateBoard projectId="gate-project" canManage />)

  const section = await screen.findByRole("region", { name: "产物候选" })
  expect(section).toBeVisible()
  expect(screen.getByText(/diagnosis_report · 产出诊断报告/)).toBeVisible()

  // 默认选中第一个清单项；改选第二个再采纳——提交体走既有 evidence 闸
  await user.selectOptions(
    screen.getByRole("combobox", { name: "候选 diagnosis_report 的目标清单项" }),
    "现状与痛点清单",
  )
  await user.click(screen.getByRole("button", { name: "采纳到清单" }))

  await waitFor(() => expect(evidenceRequestBodies()).toHaveLength(1))
  expect(evidenceRequestBodies()[0]).toEqual({
    items: [
      {
        label: "现状与痛点清单",
        source_uri: candidateEntry.source_uri,
        content_hash: candidateEntry.content_hash,
      },
    ],
  })
  // 采纳成功后回读面板
  await waitFor(() => {
    expect(callCount(gatesPath(), "GET")).toBeGreaterThanOrEqual(2)
  })
})

it("T-G1: candidates stay read-only for viewers and legacy payloads without the key still render", async () => {
  const base = gateView().gates as Array<Record<string, unknown>>
  mocks.apiRequest.mockResolvedValue(
    gateView({ gates: [{ ...base[0], evidence_candidates: [candidateEntry] }] }),
  )
  const { unmount } = render(<GateBoard projectId="gate-project" canManage={false} />)
  expect(await screen.findByRole("region", { name: "产物候选" })).toBeVisible()
  expect(screen.queryByRole("button", { name: "采纳到清单" })).not.toBeInTheDocument()
  unmount()
  cleanup()

  // 旧服务端载荷不带 evidence_candidates 键 → 照常渲染、无候选区
  mocks.apiRequest.mockResolvedValue(gateView())
  render(<GateBoard projectId="gate-project" canManage />)
  expect(await screen.findByRole("heading", { name: /G3 ·/ })).toBeVisible()
  expect(screen.queryByRole("region", { name: "产物候选" })).not.toBeInTheDocument()
})

it("T-G1: malformed candidate shapes fail validation instead of rendering half a board", async () => {
  const base = gateView().gates as Array<Record<string, unknown>>
  mocks.apiRequest.mockResolvedValue(
    gateView({
      gates: [{ ...base[0], evidence_candidates: [{ source_uri: 123 }] }],
    }),
  )
  render(<GateBoard projectId="gate-project" canManage />)

  const alert = await screen.findByRole("alert")
  expect(alert).toHaveTextContent("门禁数据加载失败，请稍后重试。")
  expect(screen.queryByRole("region", { name: "产物候选" })).not.toBeInTheDocument()
})

// V3 T-W7：workflow 形候选（运行时保留键 gate_evidence 的节点产物）。
const workflowCandidateEntry = {
  source_kind: "workflow",
  source_uri: "fdeops://engagements/demo/.fde/gates/G3/impact.md",
  content_hash: "d".repeat(64),
  workflow_run_id: "run-20261105-abcdef01",
  workflow_node_key: "build_report",
  label: "影响分析产物",
  proposed_by_user_id: "actor-1",
  proposed_at: "2026-11-05T08:00:00+00:00",
}

it("T-W7: renders workflow candidates with the source badge and adopts via the existing gate", async () => {
  const user = userEvent.setup()
  const base = gateView().gates as Array<Record<string, unknown>>
  mocks.apiRequest.mockResolvedValue(
    gateView({ gates: [{ ...base[0], evidence_candidates: [workflowCandidateEntry] }] }),
  )
  render(<GateBoard projectId="gate-project" canManage />)

  const section = await screen.findByRole("region", { name: "产物候选" })
  expect(section).toBeVisible()
  expect(screen.getByText("工作流")).toBeVisible()
  expect(screen.getByText("影响分析产物")).toBeVisible()
  expect(screen.getByText(/run run-2026 · 节点 build_report/)).toBeVisible()

  // 采纳走既有 evidence 闸（默认选第一个清单项），提交体与任务形同构
  await user.click(screen.getByRole("button", { name: "采纳到清单" }))
  await waitFor(() => expect(evidenceRequestBodies()).toHaveLength(1))
  expect(evidenceRequestBodies()[0]).toEqual({
    items: [
      {
        label: "深度诊断报告",
        source_uri: workflowCandidateEntry.source_uri,
        content_hash: workflowCandidateEntry.content_hash,
      },
    ],
  })
})

it("T-W7: task and workflow candidates with the same fingerprint coexist as separate rows", async () => {
  const base = gateView().gates as Array<Record<string, unknown>>
  const samePointerTaskEntry = {
    ...candidateEntry,
    source_uri: workflowCandidateEntry.source_uri,
    content_hash: workflowCandidateEntry.content_hash,
  }
  mocks.apiRequest.mockResolvedValue(
    gateView({
      gates: [{ ...base[0], evidence_candidates: [samePointerTaskEntry, workflowCandidateEntry] }],
    }),
  )
  render(<GateBoard projectId="gate-project" canManage />)

  await screen.findByRole("region", { name: "产物候选" })
  // 同指针+指纹两形并存（T-W7 dedup 按来源粒度隔离）：任务行无徽标，工作流行带徽标
  expect(screen.getByText(/diagnosis_report · 产出诊断报告/)).toBeVisible()
  expect(screen.getByText("影响分析产物")).toBeVisible()
  expect(screen.getAllByText(workflowCandidateEntry.source_uri)).toHaveLength(2)
  expect(screen.queryAllByText("工作流")).toHaveLength(1)
  expect(screen.getAllByRole("button", { name: "采纳到清单" })).toHaveLength(2)
})

it("T-W7: candidates whose uri exceeds the human submit cap stay visible but not adoptable", async () => {
  const base = gateView().gates as Array<Record<string, unknown>>
  mocks.apiRequest.mockResolvedValue(
    gateView({
      gates: [
        {
          ...base[0],
          evidence_candidates: [
            { ...workflowCandidateEntry, source_uri: `fdeops://engagements/demo/.fde/${"x".repeat(600)}/report.md` },
          ],
        },
      ],
    }),
  )
  render(<GateBoard projectId="gate-project" canManage />)

  await screen.findByRole("region", { name: "产物候选" })
  const button = screen.getByRole("button", { name: "采纳到清单" })
  expect(button).toBeDisabled()
  expect(button).toHaveAttribute("title", "URI 超过人工提交闸 500 上限，无法采纳")
})

it("T-W7: workflow-tagged rows missing run/node keys fail validation like malformed task rows", async () => {
  const base = gateView().gates as Array<Record<string, unknown>>
  mocks.apiRequest.mockResolvedValue(
    gateView({
      gates: [{ ...base[0], evidence_candidates: [{ ...candidateEntry, source_kind: "workflow" }] }],
    }),
  )
  render(<GateBoard projectId="gate-project" canManage />)

  const alert = await screen.findByRole("alert")
  expect(alert).toHaveTextContent("门禁数据加载失败，请稍后重试。")
  expect(screen.queryByRole("region", { name: "产物候选" })).not.toBeInTheDocument()
})

// ── B#28 门禁 revision CAS 的桌面接线 ────────────────────────────────
// 服务端 CAS 已在 #130 落地（decide_gate 收可选 expected_revision，不符即
// 409 gate_revision_conflict 且零变更）；桌面此前不知道当前 revision，CAS
// 实际从未被启用。本组用例钉住「面板读到的 revision 原样带回」＋「冲突如实
// 呈现并刷新」，杜绝静默覆盖前写。

function decidableGate(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  const base = gateView().gates as Array<Record<string, unknown>>
  return {
    ...base[0],
    gate_key: "G6",
    status: "evidence",
    checklist: [
      { label: "问题陈述（SCQA）", claim_status: "claimed", source_uri: "fdeops://x/y", content_hash: "a".repeat(64) },
    ],
    ...overrides,
  }
}

it("B#28: 拍板请求带上服务端回传的 expected_revision", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockResolvedValue(gateView({ gates: [decidableGate({ revision: 7 })] }))
  render(<GateBoard projectId="gate-project" canManage />)

  await user.click(await screen.findByRole("button", { name: "人工核验拍板" }))
  await user.click(screen.getByRole("checkbox"))
  await user.click(screen.getByRole("button", { name: /拍板（接受 1\/1）/ }))

  await waitFor(() => {
    expect(decisionRequestBodies().length).toBe(1)
  })
  expect(decisionRequestBodies()[0].expected_revision).toBe(7)
})

it("B#28: 旧服务端载荷无 revision 键时不带 expected_revision（旧客户端兼容）", async () => {
  const user = userEvent.setup()
  mocks.apiRequest.mockResolvedValue(gateView({ gates: [decidableGate()] }))
  render(<GateBoard projectId="gate-project" canManage />)

  await user.click(await screen.findByRole("button", { name: "人工核验拍板" }))
  await user.click(screen.getByRole("checkbox"))
  await user.click(screen.getByRole("button", { name: /拍板（接受 1\/1）/ }))

  await waitFor(() => {
    expect(decisionRequestBodies().length).toBe(1)
  })
  expect(decisionRequestBodies()[0]).not.toHaveProperty("expected_revision")
})

it("B#28: 并发拍板冲突（409）如实呈现并刷新面板，不假装成功", async () => {
  const user = userEvent.setup()
  const view = gateView({ gates: [decidableGate({ revision: 7 })] })
  mocks.apiRequest.mockImplementation((path: string) => {
    if (String(path).endsWith("/decision")) {
      return Promise.reject(
        new ApiClientError(
          { code: "gate_revision_conflict", message: "门禁状态已被推进" },
          409,
        ),
      )
    }
    return Promise.resolve(view)
  })
  render(<GateBoard projectId="gate-project" canManage />)

  await user.click(await screen.findByRole("button", { name: "人工核验拍板" }))
  await user.click(screen.getByRole("checkbox"))
  await user.click(screen.getByRole("button", { name: /拍板（接受 1\/1）/ }))

  const alert = await screen.findByRole("alert")
  expect(alert).toHaveTextContent("门禁状态已被其他操作推进")
  // 冲突后重新拉取门禁视图（拿新 revision，人可基于新状态重拍）
  await waitFor(() => {
    expect(callCount(gatesPath())).toBeGreaterThan(1)
  })
})
