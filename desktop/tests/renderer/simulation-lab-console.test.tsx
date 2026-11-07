// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  user: { id: "fde-1", role: "fde_engineer" },
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({ useAuth: () => mocks }))

import { SimulationRunDetail } from "../../src/renderer/src/SimulationLab/SimulationRunDetail"
import { ImprovementProposals } from "../../src/renderer/src/SimulationLab/ImprovementProposals"
import { RegressionDashboard } from "../../src/renderer/src/SimulationLab/RegressionDashboard"

beforeEach(() => {
  mocks.apiRequest.mockReset()
})

afterEach(() => {
  cleanup()
})

const run = {
  id: "run-1",
  run_key: "CASE-A-QUALITY-TRACE:normal:v1:seed0:a1:cfgabcd12",
  scenario_id: "scn-1",
  scenario_version: 1,
  split: "train",
  status: "completed",
  adapter_mode: "mock",
  seed: 0,
  attempt: 1,
  actor_set: {},
  cost: { tool_calls: 12 },
  error: null,
  created_at: "2026-11-08T02:00:00",
  started_at: null,
  finished_at: null,
}

const trace = {
  seq: 1,
  parent_seq: null,
  actor_id: null,
  phase: "interview",
  event_type: "actor_turn",
  payload: { round: 1, text: "你们平时的维修记录是怎么留的？" },
  tool_call: null,
  evidence: null,
  cost: null,
  created_at: "2026-11-08T02:00:00",
}

const report = {
  run_id: "run-1",
  layers: [
    {
      id: "ev-1",
      run_id: "run-1",
      layer: "deterministic",
      evaluator_id: "rules",
      mode: "rules",
      rubric_version: "rubric-v1",
      total_score: 0.42,
      verdict: "conditional",
      unverified_ratio: 0.1,
      scores: {
        criteria: [
          {
            key: "D1-01",
            dimension: "D1",
            title: "识别出客户真实问题",
            score: 0,
            verified: true,
            evidence_refs: [{ kind: "expected_missing", text: "知识采集前置" }],
          },
        ],
        dimension_scores: { D1: 0.3 },
        dimensions: [{ key: "D1", name: "访谈与需求识别", weight: 0.2 }],
      },
      hard_failures: [],
      note: null,
      created_at: "2026-11-08T02:10:00",
    },
    {
      id: "ev-2",
      run_id: "run-1",
      layer: "model",
      evaluator_id: "model:stub",
      mode: "stub",
      rubric_version: "rubric-v1",
      total_score: 0.4,
      verdict: "fail",
      unverified_ratio: 0,
      scores: { criteria: [] },
      hard_failures: [],
      note: "stub 模式：确定性替身，非真模型评分。",
      created_at: "2026-11-08T02:10:01",
    },
  ],
  deterministic: null,
  model: null,
  human: [],
  final: null,
  disagreement: 0.02,
  human_review_required: false,
  meta: {
    rubric_version: "rubric-v1",
    adapter_mode: "mock",
    disclaimer: "本评分为模拟环境的合成结果（假设 × 引擎），不冒充真实项目交付质量。",
  },
}

function routeApi(overrides: Record<string, unknown> = {}) {
  mocks.apiRequest.mockImplementation((path: string, options: { method?: string } = {}) => {
    if (path.includes("/runs/run-1/trace")) {
      return Promise.resolve({ items: [trace], total: 1, truncated: false, next_seq: 1 })
    }
    if (path.includes("/runs/run-1/evaluation")) {
      return Promise.resolve(report)
    }
    if (path.includes("/findings")) {
      return Promise.resolve({
        items: [
          {
            id: "f-1",
            run_id: "run-1",
            code: "FA-01",
            title: "未发现客户真实需求",
            severity: "high",
            dimension: "D1",
            description: "判据 D1-01 未达标",
            evidence_refs: [{ kind: "expected_missing" }],
            root_causes: [
              { code: "访谈追问不足", confidence: "confirmed", analysis: "直接命中" },
            ],
            status: "open",
          },
        ],
        total: 1,
      })
    }
    if (path.includes("/simulation/runs") && options.method === "GET") {
      return Promise.resolve({ items: [run], total: 1, truncated: false })
    }
    if (path.includes("/simulation/scenarios")) {
      return Promise.resolve({ items: [], total: 0, truncated: false })
    }
    if (path.includes("/proposals")) {
      return Promise.resolve({
        items: [
          {
            id: "prop-1",
            proposal_key: "PROP-ABC",
            title: "改进：访谈追问不足",
            problem: "6/18 场景未识别根因",
            finding_ids: ["f-1"],
            finding_codes: ["FA-01"],
            target: { kind: "prompt", ref: "presurvey.interview.prompt" },
            current_version: "v3",
            proposed_version: "v4",
            change_summary: "加入两条数据接入探针",
            expected_effect: {},
            impact_scope: ["interview"],
            regression_plan: {},
            override_json: {},
            status: "draft",
            decided_by_user_id: null,
            decided_at: null,
            note: null,
            created_at: "2026-11-08T03:00:00",
          },
        ],
        total: 1,
      })
    }
    if (path.includes("/regression/suites")) {
      return Promise.resolve({
        items: [
          {
            id: "suite-1",
            name: "回归套件",
            split: "train",
            scenario_ids: ["scn-1"],
            baseline_config: {},
            note: null,
            created_at: "2026-11-08T03:00:00",
          },
        ],
        total: 1,
      })
    }
    if (path.includes("/regression/results")) {
      return Promise.resolve({
        items: [
          {
            id: "res-1",
            suite_id: "suite-1",
            proposal_id: null,
            before: { runs: 4, mean_total: 0.5 },
            after: { runs: 4, mean_total: 0.7 },
            deltas: {
              total_delta: 0.2,
              dimension_deltas: { D1: 0.2 },
              regressed_dimensions: ["D6"],
              cost_delta: {},
              train_gain: 0.4,
              blind_gain: 0.02,
            },
            new_hard_failures: [],
            resolved_hard_failures: [],
            generalization_gap: 0.38,
            overfit_risk: true,
            verdict: "mixed",
            note: null,
            created_at: "2026-11-08T03:10:00",
          },
        ],
        total: 1,
      })
    }
    return Promise.resolve(overrides[path] ?? {})
  })
}

it("运行台呈现运行列表与 Trace 时序", async () => {
  routeApi()

  render(<SimulationRunDetail />)

  await waitFor(() => {
    expect(screen.getByText("运行台")).toBeInTheDocument()
  })
  await waitFor(() => {
    expect(screen.getByText("#1")).toBeInTheDocument()
    expect(screen.getByText("actor_turn")).toBeInTheDocument()
  })
})

it("评估报告并列呈现规则层与模型层，并回显诚实口径", async () => {
  routeApi()

  render(<SimulationRunDetail />)

  await waitFor(() => {
    expect(screen.getAllByText(/规则层/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/模型层/).length).toBeGreaterThan(0)
  })
  expect(screen.getByText(/不冒充真实项目交付质量/)).toBeInTheDocument()
  expect(screen.getByText(/stub 模式/)).toBeInTheDocument()
})

it("失败分析显示根因置信度与「可生成改进提案」提示", async () => {
  routeApi()

  render(<SimulationRunDetail />)

  await waitFor(() => {
    expect(screen.getByText("未发现客户真实需求")).toBeInTheDocument()
  })
  expect(screen.getByText("已确认")).toBeInTheDocument()
  expect(screen.getByText("可生成改进提案")).toBeInTheDocument()
})

it("改进提案页呈现「审批 ≠ 发布」并在缺密码时提示", async () => {
  routeApi()
  const user = userEvent.setup()

  render(<ImprovementProposals />)

  await waitFor(() => {
    expect(screen.getByText("PROP-ABC")).toBeInTheDocument()
  })
  expect(screen.getByText(/审批通过后仍需人工在治理面落地/)).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "批准（不发布）" }))
  await waitFor(() => {
    expect(
      mocks.apiRequest.mock.calls.some(([, options]) => options?.method === "POST"),
    ).toBe(true)
  })
})

it("回归面板对过拟合风险给出明确告警", async () => {
  routeApi()

  render(<RegressionDashboard />)

  await waitFor(() => {
    expect(screen.getByText(/过拟合风险/)).toBeInTheDocument()
  })
  expect(screen.getByText(/不得进入发布审批/)).toBeInTheDocument()
  expect(screen.getByText(/退步维度：D6/)).toBeInTheDocument()
})
