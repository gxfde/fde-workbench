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
  mocks.user.role = "fde_engineer"
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

const humanLayer = {
  id: "ev-human",
  run_id: "run-1",
  layer: "human",
  evaluator_id: "human:fde-1",
  mode: "manual",
  rubric_version: "rubric-v1",
  total_score: 0.55,
  verdict: "conditional",
  unverified_ratio: 0,
  scores: { criteria: [] },
  hard_failures: [],
  note: "人工复核：以交付物原文为准，取中间结论。",
  created_at: "2026-11-09T09:00:00",
}

const reportNeedingReview = {
  ...report,
  disagreement: 0.2518,
  human_review_required: true,
}

const reportWithHumanVerdict = {
  ...report,
  layers: [...report.layers, humanLayer],
  human: [humanLayer],
  final: humanLayer,
  human_review_required: false,
}

function routeApi(overrides: Record<string, unknown> = {}) {
  mocks.apiRequest.mockImplementation((path: string, options: { method?: string } = {}) => {
    if (path.includes("/runs/run-1/trace")) {
      return Promise.resolve({ items: [trace], total: 1, truncated: false, next_seq: 1 })
    }
    if (path.includes("/runs/run-1/evaluation")) {
      return Promise.resolve(report)
    }
    if (path.includes("/findings") && path.includes("/adjudicate")) {
      return Promise.resolve({ id: "f-1", status: "confirmed" })
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
            evidence_refs: [
              { kind: "expected_missing", text: "初访未索取知识采集清单——第二访补齐后仍缺失" },
            ],
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

it("失败分析发现卡提供「原文核对」只读展开：证据条原文呈现并标注 AI 蒸馏面不携带（L-C 复核对读入口）", async () => {
  routeApi()

  render(<SimulationRunDetail />)

  await waitFor(() => {
    expect(screen.getByText("未发现客户真实需求")).toBeInTheDocument()
  })
  expect(screen.getByText(/原文核对（1）/)).toBeInTheDocument()
  expect(screen.getByText(/AI 蒸馏面不携带/)).toBeInTheDocument()
  expect(
    screen.getByText("初访未索取知识采集清单——第二访补齐后仍缺失"),
  ).toBeInTheDocument()
})

it("失败分析发现卡人工裁定：admin 打开表单、note 必填禁用提交、POST adjudicate 留痕", async () => {
  mocks.user.role = "admin"
  routeApi()
  const user = userEvent.setup()

  render(<SimulationRunDetail />)

  await waitFor(() => {
    expect(screen.getByText("未发现客户真实需求")).toBeInTheDocument()
  })
  await user.click(screen.getByRole("button", { name: "人工裁定" }))
  expect(screen.getByLabelText("裁定动作")).toBeInTheDocument()
  const submit = screen.getByRole("button", { name: "提交裁定" })
  expect(submit).toBeDisabled()
  await user.type(screen.getByLabelText("裁定理由（必填）"), "人工核对原文属实，单点确认。")
  expect(submit).toBeEnabled()
  await user.click(submit)
  await waitFor(() => {
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      expect.stringContaining("/findings/f-1/adjudicate"),
      expect.objectContaining({
        method: "POST",
        body: { action: "confirm", note: "人工核对原文属实，单点确认。" },
      }),
    )
  })
})

it("fde_engineer 不见发现裁定入口（与 L-C 终裁同尺）", async () => {
  routeApi()

  render(<SimulationRunDetail />)

  await waitFor(() => {
    expect(screen.getByText("未发现客户真实需求")).toBeInTheDocument()
  })
  expect(screen.queryByRole("button", { name: "人工裁定" })).toBeNull()
})

it("被取代发现置灰呈现：取代提示＋复选框禁用＋无裁定按钮", async () => {
  routeApi()
  const base = mocks.apiRequest.getMockImplementation()
  if (!base) throw new Error("routeApi 基础 mock 未就位")
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path.includes("/findings") && !path.includes("/adjudicate")) {
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
            evidence_refs: [],
            root_causes: [
              { code: "访谈追问不足", confidence: "confirmed", analysis: "直接命中" },
            ],
            status: "open",
            superseded: true,
          },
        ],
        total: 1,
      })
    }
    return base(path, options)
  })
  mocks.user.role = "admin"

  render(<SimulationRunDetail />)

  await waitFor(() => {
    expect(screen.getByText(/已被更新的 L-C 终裁取代/)).toBeInTheDocument()
  })
  expect(screen.getByLabelText("选择发现 FA-01")).toBeDisabled()
  expect(screen.queryByRole("button", { name: "人工裁定" })).toBeNull()
})

it("评估报告 L-C 终裁历史链：多轮终裁行带序标，最新行标现行，通知含现行结论摘要", async () => {
  routeApi()
  const base = mocks.apiRequest.getMockImplementation()
  if (!base) throw new Error("routeApi 基础 mock 未就位")
  const secondHuman = {
    ...humanLayer,
    id: "ev-human-2",
    evaluator_id: "human:fde-1:r2",
    created_at: "2026-11-09T10:00:00",
    note: "第二轮终裁（改判）：根因指向追问方式而非次数",
  }
  const twoRoundReport = {
    ...reportWithHumanVerdict,
    layers: [...reportWithHumanVerdict.layers, secondHuman],
    human: [humanLayer, secondHuman],
    final: secondHuman,
  }
  mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
    if (path.includes("/runs/run-1/evaluation")) {
      return Promise.resolve(twoRoundReport)
    }
    return base(path, options)
  })

  render(<SimulationRunDetail />)

  await waitFor(() => {
    expect(screen.getByText(/第 1 次终裁（已被取代）/)).toBeInTheDocument()
  })
  expect(screen.getByText(/第 2 次终裁（现行）/)).toBeInTheDocument()
  expect(screen.getByText(/现行结论：第二轮终裁（改判）/)).toBeInTheDocument()
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

it("运行台可切换执行面并在 Trace 呈现接线状态", async () => {
  routeApi()
  const user = userEvent.setup()

  render(<SimulationRunDetail />)

  await waitFor(() => {
    expect(screen.getByLabelText("执行面")).toBeInTheDocument()
  })
  // 默认「全部执行面」——列表不按执行面收窄
  expect(screen.getByLabelText("执行面")).toHaveValue("")
  // 运行列表标注执行面
  expect(screen.getByText("脚本化替身")).toBeInTheDocument()
})

it("admin 可见 L-C 终裁表单并 POST /evaluation/human，提交后重拉报告", async () => {
  mocks.user.role = "admin"
  mocks.apiRequest.mockImplementation((path: string, options: { method?: string } = {}) => {
    if (path.includes("/runs/run-1/trace")) {
      return Promise.resolve({ items: [trace], total: 1, truncated: false, next_seq: 1 })
    }
    if (path.includes("/runs/run-1/evaluation/human") && options.method === "POST") {
      return Promise.resolve(humanLayer)
    }
    if (path.includes("/runs/run-1/evaluation")) {
      return Promise.resolve(reportNeedingReview)
    }
    if (path.includes("/findings")) {
      return Promise.resolve({ items: [], total: 0 })
    }
    if (path.includes("/simulation/runs") && options.method === "GET") {
      return Promise.resolve({ items: [run], total: 1, truncated: false })
    }
    if (path.includes("/simulation/scenarios")) {
      return Promise.resolve({ items: [], total: 0, truncated: false })
    }
    return Promise.resolve({})
  })
  const user = userEvent.setup()

  render(<SimulationRunDetail />)

  expect(await screen.findByText(/模型层分歧 0.25/)).toBeInTheDocument()
  expect(screen.getByText(/人工抽检结论（L-C 终裁）/)).toBeInTheDocument()

  await user.type(screen.getByLabelText("理由（必填）"), "人工复核：以交付物原文为准。")
  await user.click(screen.getByRole("button", { name: "提交人工终裁" }))

  await waitFor(() => {
    const post = mocks.apiRequest.mock.calls.find(
      ([path]) => String(path).includes("/evaluation/human"),
    )
    expect(post).toBeTruthy()
    const [, options] = post as [string, { method: string; body?: Record<string, unknown> }]
    expect(options.method).toBe("POST")
    expect(options.body?.verdict).toBe("conditional")
    expect(options.body?.total_score).toBe(0.5)
    expect(String(options.body?.note)).toContain("人工复核")
  })
  await waitFor(() => {
    expect(screen.getByText(/人工终裁已落库——机器结论与人工结论并列留痕/)).toBeInTheDocument()
  })
  // 就地回执（G7b 追加：表单旁必须能看到提交结果，不能只靠左栏 notice）
  expect(
    screen.getByText(/提交成功——人工终裁已落库/),
  ).toBeInTheDocument()
  // 终裁后重拉报告（evaluation GET 再次被调用）
  const evaluationGets = mocks.apiRequest.mock.calls.filter(
    ([path, options]) =>
      String(path).includes("/runs/run-1/evaluation") &&
      !String(path).includes("/human") &&
      (options as { method?: string } | undefined)?.method === "GET",
  )
  expect(evaluationGets.length).toBeGreaterThanOrEqual(2)
})

it("fde_engineer 不见终裁表单，告警指向有权限的角色", async () => {
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path.includes("/runs/run-1/trace")) {
      return Promise.resolve({ items: [trace], total: 1, truncated: false, next_seq: 1 })
    }
    if (path.includes("/runs/run-1/evaluation")) {
      return Promise.resolve(reportNeedingReview)
    }
    if (path.includes("/findings")) {
      return Promise.resolve({ items: [], total: 0 })
    }
    if (path.includes("/simulation/runs")) {
      return Promise.resolve({ items: [run], total: 1, truncated: false })
    }
    if (path.includes("/simulation/scenarios")) {
      return Promise.resolve({ items: [], total: 0, truncated: false })
    }
    return Promise.resolve({})
  })

  render(<SimulationRunDetail />)

  expect(await screen.findByText(/模型层分歧 0.25/)).toBeInTheDocument()
  expect(screen.queryByText(/人工抽检结论（L-C 终裁）/)).not.toBeInTheDocument()
  expect(screen.getByText(/终裁须由项目负责人或管理员/)).toBeInTheDocument()
})

it("已终裁的报告醒目回显人工结论（final=human）", async () => {
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path.includes("/runs/run-1/trace")) {
      return Promise.resolve({ items: [trace], total: 1, truncated: false, next_seq: 1 })
    }
    if (path.includes("/runs/run-1/evaluation")) {
      return Promise.resolve(reportWithHumanVerdict)
    }
    if (path.includes("/findings")) {
      return Promise.resolve({ items: [], total: 0 })
    }
    if (path.includes("/simulation/runs")) {
      return Promise.resolve({ items: [run], total: 1, truncated: false })
    }
    if (path.includes("/simulation/scenarios")) {
      return Promise.resolve({ items: [], total: 0, truncated: false })
    }
    return Promise.resolve({})
  })

  render(<SimulationRunDetail />)

  expect(await screen.findByText(/人工终裁已记录/)).toBeInTheDocument()
  expect(screen.getByText(/机器原行保留并列/)).toBeInTheDocument()
  expect(screen.getAllByText(/人工层/).length).toBeGreaterThan(0)
})

const realRun = {
  ...run,
  id: "91d00a0f-a966-4a54-9271-752a8ab3bb28",
  run_key: "CASE-A-QUALITY-TRACE:normal:v1:seed0:a1:cfgreal99",
  adapter_mode: "real",
}

it("执行面下拉真正过滤列表：选「真实执行面」只剩 real 那条，行首带短编号", async () => {
  routeApi()
  // 注入两条运行（mock + real）
  mocks.apiRequest.mockImplementation((path: string, options: { method?: string } = {}) => {
    if (path.includes("/runs/run-1/trace")) {
      return Promise.resolve({ items: [trace], total: 1, truncated: false, next_seq: 1 })
    }
    if (path.includes("/runs/run-1/evaluation")) {
      return Promise.resolve(report)
    }
    if (path.includes("/findings")) {
      return Promise.resolve({ items: [], total: 0 })
    }
    if (path.includes("/simulation/runs") && options.method === "GET") {
      return Promise.resolve({ items: [run, realRun], total: 2, truncated: false })
    }
    if (path.includes("/simulation/scenarios")) {
      return Promise.resolve({ items: [], total: 0, truncated: false })
    }
    return Promise.resolve({})
  })
  const user = userEvent.setup()

  render(<SimulationRunDetail />)

  await waitFor(() => {
    expect(screen.getByText("#91d00a0f")).toBeInTheDocument()
  })
  expect(screen.getByText(/共 2 条运行/)).toBeInTheDocument()

  await user.selectOptions(screen.getByLabelText("执行面"), "real")
  expect(screen.getByText("#91d00a0f")).toBeInTheDocument()
  expect(screen.getByText(/过滤后 1 \/ 2 条运行/)).toBeInTheDocument()
  expect(screen.queryByText("#run-1")).not.toBeInTheDocument()

  await user.selectOptions(screen.getByLabelText("执行面"), "mock")
  expect(screen.getByText("#run-1")).toBeInTheDocument()
  expect(screen.queryByText("#91d00a0f")).not.toBeInTheDocument()

  await user.selectOptions(screen.getByLabelText("执行面"), "")
  expect(screen.getByText("#91d00a0f")).toBeInTheDocument()
  expect(screen.getByText("#run-1")).toBeInTheDocument()
})

it("执行面过滤无命中时给指路空态而非空白", async () => {
  mocks.apiRequest.mockImplementation((path: string, options: { method?: string } = {}) => {
    if (path.includes("/runs/run-1/trace")) {
      return Promise.resolve({ items: [], total: 0, truncated: false, next_seq: 0 })
    }
    if (path.includes("/runs/run-1/evaluation")) {
      return Promise.resolve(report)
    }
    if (path.includes("/findings")) {
      return Promise.resolve({ items: [], total: 0 })
    }
    if (path.includes("/simulation/runs") && options.method === "GET") {
      return Promise.resolve({ items: [run], total: 1, truncated: false })
    }
    if (path.includes("/simulation/scenarios")) {
      return Promise.resolve({ items: [], total: 0, truncated: false })
    }
    return Promise.resolve({})
  })
  const user = userEvent.setup()

  render(<SimulationRunDetail />)
  await waitFor(() => {
    expect(screen.getByText("#run-1")).toBeInTheDocument()
  })

  await user.selectOptions(screen.getByLabelText("执行面"), "real")
  expect(screen.getByText(/当前过滤条件下没有运行/)).toBeInTheDocument()
})

it("终裁提交失败时在表单旁就地报错而非静默", async () => {
  mocks.user.role = "admin"
  mocks.apiRequest.mockImplementation((path: string, options: { method?: string } = {}) => {
    if (path.includes("/runs/run-1/trace")) {
      return Promise.resolve({ items: [trace], total: 1, truncated: false, next_seq: 1 })
    }
    if (path.includes("/runs/run-1/evaluation/human") && options.method === "POST") {
      return Promise.reject(new Error("forbidden: 人工抽检结论需项目负责人或管理员。"))
    }
    if (path.includes("/runs/run-1/evaluation")) {
      return Promise.resolve(reportNeedingReview)
    }
    if (path.includes("/findings")) {
      return Promise.resolve({ items: [], total: 0 })
    }
    if (path.includes("/simulation/runs") && options.method === "GET") {
      return Promise.resolve({ items: [run], total: 1, truncated: false })
    }
    if (path.includes("/simulation/scenarios")) {
      return Promise.resolve({ items: [], total: 0, truncated: false })
    }
    return Promise.resolve({})
  })
  const user = userEvent.setup()

  render(<SimulationRunDetail />)

  expect(await screen.findByText(/人工抽检结论（L-C 终裁）/)).toBeInTheDocument()
  await user.type(screen.getByLabelText("理由（必填）"), "核对后再裁。")
  await user.click(screen.getByRole("button", { name: "提交人工终裁" }))

  await waitFor(() => {
    expect(screen.getByText(/提交失败：forbidden/)).toBeInTheDocument()
  })
  // 失败后按钮恢复可再提交
  expect(screen.getByRole("button", { name: "提交人工终裁" })).toBeEnabled()
})

it("Trace 行对非空 payload.artifact 提供展开/收起面板，区分自由文本与结构化产物", async () => {
  const textArtifactTrace = {
    seq: 2,
    parent_seq: 1,
    actor_id: "agent:fde",
    phase: "design",
    event_type: "artifact",
    payload: {
      kind: "design",
      artifact: {
        structured: false,
        integration_status: "verified",
        artifacts: [
          {
            name: "solution-draft.md",
            kind: "doc",
            sha256: "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            text: "# 交付方案\n第一阶段先盘点车间台账与设备接口。",
          },
        ],
      },
    },
    tool_call: null,
    evidence: null,
    cost: null,
    created_at: "2026-11-08T02:02:00",
  }
  const structuredArtifactTrace = {
    seq: 3,
    parent_seq: 2,
    actor_id: "agent:fde",
    phase: "validate",
    event_type: "artifact",
    payload: {
      kind: "validation",
      artifact: {
        verdict: "pass",
        checks: [{ key: "G3", passed: true }],
      },
    },
    tool_call: null,
    evidence: null,
    cost: null,
    created_at: "2026-11-08T02:05:00",
  }

  mocks.apiRequest.mockImplementation((path: string, options: { method?: string } = {}) => {
    if (path.includes("/runs/run-1/trace")) {
      return Promise.resolve({
        items: [trace, textArtifactTrace, structuredArtifactTrace],
        total: 3,
        truncated: false,
        next_seq: 3,
      })
    }
    if (path.includes("/runs/run-1/evaluation")) {
      return Promise.resolve(reportNeedingReview)
    }
    if (path.includes("/findings")) {
      return Promise.resolve({ items: [], total: 0 })
    }
    if (path.includes("/simulation/runs") && options.method === "GET") {
      return Promise.resolve({ items: [run], total: 1, truncated: false })
    }
    if (path.includes("/simulation/scenarios")) {
      return Promise.resolve({ items: [], total: 0, truncated: false })
    }
    return Promise.resolve({})
  })
  const user = userEvent.setup()

  render(<SimulationRunDetail />)

  const expandButtons = await screen.findAllByRole("button", { name: "展开交付原文" })
  expect(expandButtons).toHaveLength(2)
  expect(screen.queryByText("solution-draft.md")).not.toBeInTheDocument()

  // 展开自由文本产物：展示 name / kind / sha256 / 只读 text
  await user.click(expandButtons[0])
  const detailPanels = screen.getAllByRole("region", { name: "阶段交付产物原文" })
  expect(detailPanels).toHaveLength(1)
  expect(within(detailPanels[0]).getByText("solution-draft.md")).toBeInTheDocument()
  expect(within(detailPanels[0]).getByText("doc")).toBeInTheDocument()
  expect(
    within(detailPanels[0]).getByText(
      /sha256: 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08/,
    ),
  ).toBeInTheDocument()
  expect(
    within(detailPanels[0]).getByText(/第一阶段先盘点车间台账与设备接口/),
  ).toBeInTheDocument()

  // 展开结构化产物：展示键值与 JSON
  await user.click(expandButtons[1])
  const bothPanels = screen.getAllByRole("region", { name: "阶段交付产物原文" })
  expect(bothPanels).toHaveLength(2)
  expect(within(bothPanels[1]).getByText("verdict")).toBeInTheDocument()
  expect(within(bothPanels[1]).getByText("checks")).toBeInTheDocument()
  expect(within(bothPanels[1]).getByText(/"G3"/)).toBeInTheDocument()

  // 收起自由文本产物
  await user.click(screen.getAllByRole("button", { name: "收起交付原文" })[0])
  expect(screen.queryByText("solution-draft.md")).not.toBeInTheDocument()
})

it("提案页正确渲染已发布状态与发布/回滚记录，非管理员不展示发布或回滚按钮", async () => {
  mocks.user.role = "fde_engineer"
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path.includes("/findings")) {
      return Promise.resolve({ items: [], total: 0 })
    }
    if (path.includes("/proposals")) {
      return Promise.resolve({
        items: [
          {
            id: "prop-pub",
            proposal_key: "PROP-PUB-1",
            title: "改进：补齐交付门禁探针",
            problem: "验证阶段遗漏指针",
            finding_ids: ["f-1"],
            finding_codes: ["FA-02"],
            target: { kind: "prompt", ref: "delivery.gate.prompt" },
            current_version: "v1",
            proposed_version: "v2",
            change_summary: "新增门禁探针提示",
            expected_effect: {},
            impact_scope: ["validate"],
            regression_plan: { suite: "smoke-18" },
            status: "published",
            decided_by_user_id: "admin-1",
            decided_at: "2026-11-12T08:00:00Z",
            note: "评审通过",
            release: {
              released_at: "2026-11-12T10:00:00Z",
              released_by_user_id: "admin-1",
              released_version: "v2",
              release_note: "首轮受控灰度发布",
              rollback: null,
            },
          },
          {
            id: "prop-rb",
            proposal_key: "PROP-RB-2",
            title: "改进：历史已回滚提案",
            problem: "回归波动",
            finding_ids: ["f-1"],
            finding_codes: ["FA-03"],
            target: { kind: "prompt", ref: "presurvey.interview.prompt" },
            current_version: "v3",
            proposed_version: "v4",
            change_summary: "调整追问顺序",
            expected_effect: {},
            impact_scope: ["interview"],
            regression_plan: { suite: "smoke-18" },
            status: "approved",
            decided_by_user_id: "admin-1",
            decided_at: "2026-11-12T08:00:00Z",
            note: "批准试验",
            release: {
              released_at: "2026-11-12T09:00:00Z",
              released_by_user_id: "admin-1",
              released_version: "v4",
              release_note: "初次发布",
              rollback: {
                rolled_back_at: "2026-11-12T11:30:00Z",
                rolled_back_by_user_id: "admin-1",
                rollback_note: "噪声超限回退",
              },
            },
          },
        ],
        total: 2,
      })
    }
    return Promise.resolve({})
  })

  render(<ImprovementProposals />)

  expect(await screen.findByText("PROP-PUB-1")).toBeInTheDocument()
  expect(screen.getByText("已发布")).toBeInTheDocument()
  expect(screen.queryByText("undefined")).not.toBeInTheDocument()
  expect(screen.getByText(/首轮受控灰度发布/)).toBeInTheDocument()
  expect(screen.getByText(/噪声超限回退/)).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "发布记账" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "回滚" })).not.toBeInTheDocument()
})

it("管理员可对 approved 提案发起发布记账、对 published 提案发起回滚，回归计划为空时禁用并清密码 state", async () => {
  mocks.user.role = "admin"
  const calls: Array<{ path: string; method?: string; body?: unknown }> = []
  let failNextRelease = true

  mocks.apiRequest.mockImplementation(
    (path: string, options: { method?: string; body?: unknown } = {}) => {
      calls.push({ path, method: options.method, body: options.body })
      if (path.includes("/findings")) {
        return Promise.resolve({ items: [], total: 0 })
      }
      if (path === "/api/v1/simulation/proposals/prop-ok/release" && options.method === "POST") {
        if (failNextRelease) {
          failNextRelease = false
          return Promise.reject(new Error("管理员密码校验失败"))
        }
        return Promise.resolve({ id: "prop-ok", status: "published" })
      }
      if (path === "/api/v1/simulation/proposals/prop-pub/rollback" && options.method === "POST") {
        return Promise.resolve({ id: "prop-pub", status: "approved" })
      }
      if (path.includes("/proposals")) {
        return Promise.resolve({
          items: [
            {
              id: "prop-empty-plan",
              proposal_key: "PROP-NOPLAN",
              title: "无回归计划提案",
              problem: "缺少计划",
              finding_ids: [],
              finding_codes: [],
              target: { kind: "prompt", ref: "p.a" },
              current_version: "v1",
              proposed_version: "v2",
              change_summary: "微调",
              expected_effect: {},
              impact_scope: [],
              regression_plan: {},
              status: "approved",
              decided_by_user_id: "admin-1",
              decided_at: "2026-11-12T08:00:00Z",
              note: "已批",
              release: null,
            },
            {
              id: "prop-ok",
              proposal_key: "PROP-READY",
              title: "可发布提案",
              problem: "有完整回归计划",
              finding_ids: [],
              finding_codes: [],
              target: { kind: "prompt", ref: "p.b" },
              current_version: "v2",
              proposed_version: "v3",
              change_summary: "补齐字段",
              expected_effect: {},
              impact_scope: [],
              regression_plan: { scenarios: ["CASE-A"] },
              status: "approved",
              decided_by_user_id: "admin-1",
              decided_at: "2026-11-12T08:10:00Z",
              note: "已批可发",
              release: null,
            },
            {
              id: "prop-pub",
              proposal_key: "PROP-LIVE",
              title: "在线提案",
              problem: "已发布待观察",
              finding_ids: [],
              finding_codes: [],
              target: { kind: "prompt", ref: "p.c" },
              current_version: "v3",
              proposed_version: "v4",
              change_summary: "上线版",
              expected_effect: {},
              impact_scope: [],
              regression_plan: { scenarios: ["CASE-B"] },
              status: "published",
              decided_by_user_id: "admin-1",
              decided_at: "2026-11-12T08:20:00Z",
              note: "已批",
              release: {
                released_at: "2026-11-12T09:00:00Z",
                released_by_user_id: "admin-1",
                released_version: "v4",
                release_note: "正式记账",
                rollback: null,
              },
            },
          ],
          total: 3,
        })
      }
      return Promise.resolve({})
    },
  )
  const user = userEvent.setup()

  render(<ImprovementProposals />)

  expect(await screen.findByText("PROP-NOPLAN")).toBeInTheDocument()
  expect(screen.getByText("回归计划为空，无法发起发布记账。")).toBeInTheDocument()

  const releaseButtons = screen.getAllByRole("button", { name: "发布记账" })
  expect(releaseButtons[0]).toBeDisabled()
  expect(releaseButtons[1]).toBeEnabled()

  // 打开内联框 -> 输入密码 -> 取消应立即清空密码并收起
  await user.click(releaseButtons[1])
  const releaseRegion = screen.getByRole("region", { name: "发布记账确认" })
  await user.type(within(releaseRegion).getByLabelText("管理员密码（发布记账必填）"), "temp-secret")
  await user.click(within(releaseRegion).getByRole("button", { name: "取消" }))
  expect(screen.queryByRole("region", { name: "发布记账确认" })).not.toBeInTheDocument()

  // 重新打开：密码框为空；首次提交触发失败时显错且密码立即清空
  await user.click(screen.getAllByRole("button", { name: "发布记账" })[1])
  const releaseRegion2 = screen.getByRole("region", { name: "发布记账确认" })
  const pwdInput = within(releaseRegion2).getByLabelText(
    "管理员密码（发布记账必填）",
  ) as HTMLInputElement
  expect(pwdInput.value).toBe("")
  await user.type(pwdInput, "wrong-pass")
  await user.type(within(releaseRegion2).getByLabelText("发布备注（必填）"), "灰度发布 v3")
  await user.click(within(releaseRegion2).getByRole("button", { name: "确认发布记账" }))

  await waitFor(() => {
    expect(within(releaseRegion2).getByRole("alert")).toHaveTextContent("管理员密码校验失败")
  })
  expect(pwdInput.value).toBe("")

  // 重新输入正确密码提交成功 -> 关闭内联框
  await user.type(pwdInput, "admin-correct-pass")
  await user.click(within(releaseRegion2).getByRole("button", { name: "确认发布记账" }))

  await waitFor(() => {
    expect(screen.queryByRole("region", { name: "发布记账确认" })).not.toBeInTheDocument()
  })
  const releaseCall = calls.filter(
    (item) => item.path === "/api/v1/simulation/proposals/prop-ok/release",
  )
  expect(releaseCall).toHaveLength(2)
  expect(releaseCall[1].body).toEqual({
    password: "admin-correct-pass",
    note: "灰度发布 v3",
  })

  // 对 published 提案执行回滚
  await user.click(screen.getByRole("button", { name: "回滚" }))
  const rollbackRegion = screen.getByRole("region", { name: "发布回滚确认" })
  const rbPwdInput = within(rollbackRegion).getByLabelText(
    "管理员密码（回滚必填）",
  ) as HTMLInputElement
  await user.type(rbPwdInput, "admin-rb-pass")
  await user.type(within(rollbackRegion).getByLabelText("回滚备注（必填）"), "线上指标回退")
  await user.click(within(rollbackRegion).getByRole("button", { name: "确认回滚" }))

  await waitFor(() => {
    expect(screen.queryByRole("region", { name: "发布回滚确认" })).not.toBeInTheDocument()
  })
  const rollbackCall = calls.find(
    (item) => item.path === "/api/v1/simulation/proposals/prop-pub/rollback",
  )
  expect(rollbackCall?.body).toEqual({
    password: "admin-rb-pass",
    note: "线上指标回退",
  })
})

const sampleScenario = {
  id: "scen-1",
  scenario_key: "CASE-A-QUALITY-TRACE",
  name: "质量追溯试点场景",
  variant: "normal",
  version: 1,
  industry: "manufacturing",
  scale: "medium",
  difficulty: "normal" as const,
  split: "train" as const,
  source_kind: "seed",
  status: "active" as const,
  tags: [],
  content_sha256: "abc123",
  created_at: "2026-11-08T01:00:00Z",
}

const sampleProposal = {
  id: "prop-base",
  proposal_key: "PROP-BASE",
  title: "改进提案示例",
  problem: "范围蔓延",
  finding_ids: ["f-confirmed-1"],
  finding_codes: ["FA-02"],
  target: { kind: "prompt", ref: "simulation_workbench" },
  current_version: "v1",
  proposed_version: "v2",
  change_summary: "补充边界清单",
  expected_effect: {},
  impact_scope: ["design"],
  regression_plan: { suite: "smoke" },
  status: "in_review" as const,
  decided_by_user_id: null,
  decided_at: null,
  note: null,
  release: null,
}

it("运行台支持目标场景选择器与 workbench 内嵌模型执行面（不再写死 scenarios[0]）", async () => {
  const secondScenario = {
    ...sampleScenario,
    id: "scen-2",
    scenario_key: "CASE-B-TRADE-DOCS",
    name: "外贸单证自动化场景",
    version: 3,
  }
  const workbenchRun = {
    ...run,
    id: "wb-77889900-1111-2222-3333-444455556666",
    run_key: "CASE-B-TRADE-DOCS:normal:v3:seed0:a1:cfgwb",
    adapter_mode: "workbench" as const,
    status: "completed" as const,
  }
  const calls: Array<{ path: string; method?: string; body?: unknown }> = []

  mocks.apiRequest.mockImplementation(
    (path: string, options: { method?: string; body?: unknown } = {}) => {
      calls.push({ path, method: options.method, body: options.body })
      if (path.includes("/runs/") && path.includes("/trace")) {
        return Promise.resolve({ items: [trace], total: 1, truncated: false, next_seq: 1 })
      }
      if (path.includes("/simulation/scenarios")) {
        return Promise.resolve({
          items: [sampleScenario, secondScenario],
          total: 2,
          truncated: false,
        })
      }
      if (path === "/api/v1/simulation/runs" && options.method === "POST") {
        return Promise.resolve({ ...workbenchRun, status: "queued" })
      }
      if (path.includes("/simulation/runs") && options.method === "GET") {
        return Promise.resolve({ items: [run, workbenchRun], total: 2, truncated: false })
      }
      if (path.includes("/evaluation")) {
        return Promise.resolve(report)
      }
      if (path.includes("/findings")) {
        return Promise.resolve({ items: [], total: 0 })
      }
      return Promise.resolve({})
    },
  )
  const user = userEvent.setup()

  render(<SimulationRunDetail />)

  await waitFor(() => {
    expect(screen.getByLabelText("目标场景")).toHaveValue("scen-1")
  })
  expect(screen.getByText("工作台内嵌模型")).toBeInTheDocument()

  await user.selectOptions(screen.getByLabelText("目标场景"), "scen-2")
  await user.selectOptions(screen.getByLabelText("执行面"), "workbench")
  expect(screen.getByText("#wb-77889")).toBeInTheDocument()
  expect(screen.queryByText("#run-1")).not.toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "发起模拟运行" }))

  await waitFor(() => {
    const post = calls.find(
      (item) => item.path === "/api/v1/simulation/runs" && item.method === "POST",
    )
    expect(post?.body).toEqual({
      scenario_id: "scen-2",
      adapter_mode: "workbench",
      execute: true,
      config: { max_rounds: 6, probe_quality: 1.0 },
    })
  })
  expect(
    await screen.findByText(/已基于「外贸单证自动化场景」发起内嵌工作台模型运行/),
  ).toBeInTheDocument()
})

it("失败分析支持 L-B likely 标记提示与「失败 → AI 起草改进候选 → 创建改进提案」闭环", async () => {
  const confirmedFinding = {
    id: "f-confirmed-1",
    code: "FA-02",
    title: "范围蔓延或目标发散",
    severity: "high" as const,
    dimension: "D2",
    description: "边界条款缺失。",
    evidence_refs: [{ seq: 2 }],
    root_causes: [
      {
        code: "RC-SCOPE",
        category: "prompt",
        confidence: "confirmed" as const,
        analysis: "缺少明确 In-Scope / Out-of-Scope 表述。",
      },
    ],
    created_at: "2026-11-14T00:00:00Z",
  }
  const likelyFinding = {
    id: "f-likely-2",
    code: "FA-03",
    title: "方案缺乏架构依据（L-B 模型层建议）",
    severity: "medium" as const,
    dimension: "D3",
    description: "模型层评分偏低（待 L-C 复核）。",
    evidence_refs: [],
    root_causes: [
      {
        code: "RC-L-B",
        category: "model_evaluation",
        confidence: "likely" as const,
        analysis: "来源 L-B model:server。",
      },
    ],
    created_at: "2026-11-14T00:01:00Z",
  }
  const calls: Array<{ path: string; method?: string; body?: unknown }> = []

  mocks.apiRequest.mockImplementation(
    (path: string, options: { method?: string; body?: unknown } = {}) => {
      calls.push({ path, method: options.method, body: options.body })
      if (path.includes("/runs/") && path.includes("/trace")) {
        return Promise.resolve({ items: [trace], total: 1, truncated: false, next_seq: 1 })
      }
      if (path.includes("/simulation/scenarios")) {
        return Promise.resolve({ items: [sampleScenario], total: 1, truncated: false })
      }
      if (path.includes("/simulation/runs") && options.method === "GET") {
        return Promise.resolve({ items: [run], total: 1, truncated: false })
      }
      if (path.includes("/evaluation")) {
        return Promise.resolve(report)
      }
      if (path === "/api/v1/simulation/findings/draft-ai" && options.method === "POST") {
        return Promise.resolve({
          draft: {
            groups: [
              {
                code: "FA-02",
                lesson_entry: {
                  text: "方案定稿前必须显式列出 In-Scope 与 Out-of-Scope 清单。",
                  tier: "agent.module.discovery",
                  industries: ["manufacturing"],
                  rationale: "防止范围蔓延。",
                },
                skill_version_draft: {
                  skill_ref: "fde-scope-guard",
                  summary: "补充范围边界核对清单",
                  instructions_delta: "输出方案时附带边界对照表。",
                },
                prompt_overlay_fragment: {
                  purpose_key: "simulation_workbench",
                  fragment: "方案阶段须输出明确的交付范围边界与排外事项。",
                  rationale: "约束方案输出完整性。",
                },
              },
            ],
          },
          payload_sha256: "ab12cd34ef567890",
          finding_ids: ["f-confirmed-1"],
          prompt_version: "simulation-improvement-draft-prompt-v1",
          prompt_fingerprint: "8cec4edef64a2b2f50c6edb644406716ffdd85ce85f061919b2ec87b1296e831",
        })
      }
      if (path === "/api/v1/simulation/proposals" && options.method === "POST") {
        return Promise.resolve({
          ...sampleProposal,
          proposal_key: "PROP-L4-NEW",
          candidate_payload: (options.body as { candidate_payload?: Record<string, unknown> })
            ?.candidate_payload,
        })
      }
      if (path.includes("/findings")) {
        return Promise.resolve({ items: [confirmedFinding, likelyFinding], total: 2 })
      }
      return Promise.resolve({})
    },
  )
  const user = userEvent.setup()

  render(<SimulationRunDetail />)

  expect(
    await screen.findByText(/L-B 模型建议 · 根因未确认——完成 L-C 人工复核确认后方可建正式提案/),
  ).toBeInTheDocument()

  // 仅勾选 likely 行尝试手工建案 -> 前端拦截要求至少含一条 confirmed 根因
  await user.click(screen.getByLabelText("选择发现 FA-03"))
  await user.click(screen.getByRole("button", { name: "手工/编辑建案" }))
  await user.type(screen.getByLabelText("变更摘要（必填）"), "尝试用 likely 建案")
  await user.click(screen.getByRole("button", { name: "创建改进提案" }))
  expect(
    await screen.findByText(/创建正式提案要求所勾选发现至少包含一条「已确认（confirmed）」根因/),
  ).toBeInTheDocument()

  // 勾选 confirmed 行 -> AI 起草改进候选 -> 切换为 prompt_overlay_fragment -> 创建提案带 candidate_payload
  await user.click(screen.getByLabelText("选择发现 FA-03"))
  await user.click(screen.getByLabelText("选择发现 FA-02"))
  await user.click(screen.getByRole("button", { name: "AI 起草改进候选" }))

  expect(await screen.findByText(/AI 已起草 1 组候选载荷/)).toBeInTheDocument()
  expect(screen.getByLabelText("经验卡正文（≤300字）")).toHaveValue(
    "方案定稿前必须显式列出 In-Scope 与 Out-of-Scope 清单。",
  )

  await user.selectOptions(screen.getByLabelText("进化载体类型"), "prompt_overlay_fragment")
  expect(screen.getByLabelText("追加陈述片段（≤200字）")).toHaveValue(
    "方案阶段须输出明确的交付范围边界与排外事项。",
  )

  await user.click(screen.getByRole("button", { name: "创建改进提案" }))

  await waitFor(() => {
    const createCall = calls.find(
      (item) => item.path === "/api/v1/simulation/proposals" && item.method === "POST",
    )
    expect(createCall?.body).toEqual({
      finding_ids: ["f-confirmed-1"],
      target: { kind: "prompt", ref: "simulation_workbench" },
      change_summary: "方案阶段须输出明确的交付范围边界与排外事项。",
      candidate_payload: {
        prompt_overlay_fragment: {
          purpose_key: "simulation_workbench",
          fragment: "方案阶段须输出明确的交付范围边界与排外事项。",
          rationale: "约束方案输出完整性。",
        },
      },
    })
  })
  expect(await screen.findByText(/已创建改进提案 PROP-L4-NEW/)).toBeInTheDocument()
})

it("L5 提案发布弹窗加载三载体并排预览（含注入终文与近 30 天调用量）并展示热生效/回滚退役摘要", async () => {
  mocks.user.role = "admin"
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path.includes("/findings")) {
      return Promise.resolve({ items: [], total: 0 })
    }
    if (path === "/api/v1/simulation/proposals/prop-l5-ov/release-preview") {
      return Promise.resolve({
        proposal_id: "prop-l5-ov",
        proposal_key: "PROP-L5-OV",
        status: "approved",
        overfit_blocked: false,
        latest_regression_id: "reg-1",
        latest_regression_verdict: "improved",
        branches: ["prompt_overlay_fragment"],
        overlay_preview: {
          purpose_key: "simulation_workbench",
          purpose_allowed: true,
          prompt_version: "simulation-workbench-prompt-v1",
          base_prompt: "原始基座系统提示词正文。",
          existing_overlay_count: 0,
          candidate_fragment: "未确认预算范围前不出具固定总价承诺。",
          effective_prompt:
            "原始基座系统提示词正文。\n\n【平台动态经验条款】\n未确认预算范围前不出具固定总价承诺。",
          syntax_violation: null,
          ngram_overlap_ratio: 0.0,
          ngram_blocked: false,
          calls_last_30d: 42,
        },
        lesson_preview: null,
        skill_preview: null,
      })
    }
    if (path.includes("/proposals")) {
      return Promise.resolve({
        items: [
          {
            ...sampleProposal,
            id: "prop-l5-ov",
            proposal_key: "PROP-L5-OV",
            status: "approved",
            regression_plan: { suite: "smoke-l5" },
            candidate_payload: {
              prompt_overlay_fragment: {
                purpose_key: "simulation_workbench",
                fragment: "未确认预算范围前不出具固定总价承诺。",
              },
            },
          },
          {
            ...sampleProposal,
            id: "prop-l5-mat",
            proposal_key: "PROP-L5-MAT",
            status: "published",
            regression_plan: { suite: "smoke-l5" },
            release: {
              released_at: "2026-11-14T12:00:00Z",
              released_by_user_id: "admin-1",
              released_version: "v2",
              release_note: "L5 热生效发布",
              materialized: {
                lesson: { entry_id: "LESS-DYN-PROP-L5-MAT", text_sha256: "deadbeef" },
                overlay: { overlay_id: "ov-uuid-01", content_sha256: "cafebabe" },
              },
              rollback: null,
            },
          },
        ],
        total: 2,
      })
    }
    return Promise.resolve({})
  })
  const user = userEvent.setup()

  render(<ImprovementProposals />)

  expect(await screen.findByText("PROP-L5-OV")).toBeInTheDocument()
  expect(screen.getByText(/Lesson 已生效：LESS-DYN-PROP-L5-MAT/)).toBeInTheDocument()
  expect(screen.getByText(/Overlay 已生效：ov-uuid-01/)).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "发布记账" }))
  const previewRegion = await screen.findByRole("region", { name: "三载体发布并排预览" })
  expect(within(previewRegion).getByText("42")).toBeInTheDocument()
  expect(
    within(previewRegion).getByText(/【平台动态经验条款】/),
  ).toBeInTheDocument()
})

it("L5 回归面板呈现 L-B 模型层噪声带判定并支持 202 异步回归作业排队提示", async () => {
  mocks.apiRequest.mockImplementation(
    (path: string, options: { method?: string } = {}) => {
      if (path === "/api/v1/simulation/regression/suites" && options.method === "GET") {
        return Promise.resolve({
          items: [
            {
              id: "suite-async",
              name: "真模型异步套件",
              split: "regression",
              scenario_ids: ["scn-1", "scn-2", "scn-3"],
              baseline_config: { adapter_mode: "workbench", model_mode: "server" },
              note: null,
              created_at: "2026-11-14T10:00:00Z",
            },
          ],
          total: 1,
        })
      }
      if (path.includes("/regression/results") && options.method === "GET") {
        return Promise.resolve({
          items: [
            {
              id: "res-l5-1",
              suite_id: "suite-async",
              proposal_id: "prop-1",
              before: { runs: 3, mean_total: 0.65, mean_model_total: 0.61 },
              after: { runs: 3, mean_total: 0.72, mean_model_total: 0.68 },
              deltas: {
                total_delta: 0.07,
                model_verdict: "within_noise",
                model_total_delta: 0.07,
                noise_band: 0.1049,
                noise_band_axis: "rubric-v1|model:server",
              },
              new_hard_failures: [],
              resolved_hard_failures: [],
              generalization_gap: 0.01,
              overfit_risk: false,
              verdict: "improved",
              note: null,
              created_at: "2026-11-14T11:00:00Z",
            },
          ],
          total: 1,
        })
      }
      if (path === "/api/v1/simulation/regression/suites/suite-async/run" && options.method === "POST") {
        return Promise.resolve({
          queued_async: true,
          job_id: "job-99887766-abcd",
          outbox_event_id: "evt-1",
          job_status: "pending",
          suite_id: "suite-async",
          proposal_id: null,
          adapter_mode: "workbench",
          model_mode: "server",
        })
      }
      return Promise.resolve({})
    },
  )
  const user = userEvent.setup()

  render(<RegressionDashboard />)

  expect(await screen.findByText(/落在噪声带内（不可判改进）/)).toBeInTheDocument()
  expect(screen.getByText(/噪声带 ±0.1049/)).toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "跑对比" }))
  expect(
    await screen.findByText(/真模型回归已转入后台作业（Job #job-9988/),
  ).toBeInTheDocument()
})



