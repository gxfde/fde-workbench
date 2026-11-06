// @vitest-environment jsdom
// T-A1（台账「售前主线登记（T-A 系列）」T-A1）：presurvey S3 前置闸的桌面可读提示。
//
// 缺陷基线：G3 诊断开工门在服务端已落地（_require_s3_gate 抛 409
// presurvey_s3_gate_open，message 含 SOW-A 签署 / A 款到账 / 数据授权书四项
// 勾选文案），但桌面 start() 的 catch 把它吞成通用文案「无法开始 AI 分析」
// ——售前不知道被什么闸住、要去哪里补。
//
// 本测试钉住四件事：
// 1. 409 presurvey_s3_gate_open → 渲染拦截态（role=alert）+ 服务端 message 原文；
// 2. 拦截态拉取 G3 清单并按 claimed ≠ accepted 语义渲染徽标；
// 3. 「前往门禁页」跳转锚指向既有 ?tab=gates 路由（零新路由）；
// 4. 非 409 错误仍然回落通用文案（不误伤既有行为）。
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  runTask: vi.fn(),
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({
  useAuth: () => ({ apiRequest: mocks.apiRequest }),
}))
vi.mock("../../src/renderer/src/ai/AIExecutionProvider", () => ({
  useAIExecution: () => ({ runTask: mocks.runTask }),
}))
vi.mock("../../src/renderer/src/guidance/GuidanceReview", () => ({
  GuidanceReview: () => null,
}))

import { ApiClientError } from "../../src/renderer/src/api/client"
import { PresurveyAnalysisAction } from "../../src/renderer/src/guidance/PresurveyAnalysisAction"
import { gatesHref } from "../../src/renderer/src/guidance/PresurveyGateHint"

const GATE_OPEN_MESSAGE = "需先通过 G3 诊断开工门（SOW-A 签署、A 款到账、数据授权书四项勾选），才能上传预调研文件或发起 AI 分析。"

function gateOpenError(): ApiClientError {
  return new ApiClientError({ code: "presurvey_s3_gate_open", message: GATE_OPEN_MESSAGE, details: null })
}

function gateView(): Record<string, unknown> {
  return {
    gates: [
      {
        gate_key: "G3",
        gate_name: "诊断开工门",
        status: "pending",
        checklist: [
          { label: "诊断报告（数字全 claimed）", claim_status: null },
          { label: "SOW-A 签署", claim_status: "claimed" },
          { label: "A 款预付到账", claim_status: null },
          { label: "数据授权书四项勾选", claim_status: "accepted" },
        ],
      },
    ],
  }
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
  mocks.runTask.mockReset()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it("renders a readable blocked state with the server message when G3 gate rejects the analysis", async () => {
  mocks.runTask.mockImplementation(async ({ task }: { task: () => Promise<unknown> }) => task())
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path).endsWith("/guidance-analyses")) throw gateOpenError()
    if (String(path).endsWith("/gates")) return gateView()
    throw new Error("unexpected call: " + String(path))
  })

  render(<PresurveyAnalysisAction projectId="project-1" fileVersionId="file-1" canManage />)
  await userEvent.click(screen.getByRole("button", { name: "AI 分析预调研表" }))

  const alert = await screen.findByRole("alert")
  expect(alert).toHaveTextContent("暂不能上传预调研文件或发起 AI 分析")
  expect(alert).toHaveTextContent(GATE_OPEN_MESSAGE)
  // 通用文案不得出现——这就是缺陷基线
  expect(screen.queryByText("分析失败")).toBeNull()
})

it("lists the G3 evidence checklist with claimed ≠ accepted badge semantics", async () => {
  mocks.runTask.mockImplementation(async ({ task }: { task: () => Promise<unknown> }) => task())
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path).endsWith("/guidance-analyses")) throw gateOpenError()
    if (String(path).endsWith("/gates")) return gateView()
    throw new Error("unexpected call: " + String(path))
  })

  render(<PresurveyAnalysisAction projectId="project-1" fileVersionId="file-1" canManage />)
  await userEvent.click(screen.getByRole("button", { name: "AI 分析预调研表" }))

  const alert = await screen.findByRole("alert")
  await waitFor(() => expect(alert).toHaveTextContent("SOW-A 签署"))
  expect(alert).toHaveTextContent("诊断报告（数字全 claimed）")
  expect(alert).toHaveTextContent("A 款预付到账")
  expect(alert).toHaveTextContent("数据授权书四项勾选")
  // 徽标语义：accepted / claimed / 未提交 三态各自呈现
  expect(alert).toHaveTextContent("claimed")
  expect(alert).toHaveTextContent("accepted")
  expect(alert).toHaveTextContent("未提交")
  // claimed ≠ accepted 纪律文案
  expect(alert).toHaveTextContent("claimed ≠ accepted")
})

it("links to the existing gates tab route", async () => {
  mocks.runTask.mockImplementation(async ({ task }: { task: () => Promise<unknown> }) => task())
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path).endsWith("/guidance-analyses")) throw gateOpenError()
    if (String(path).endsWith("/gates")) return gateView()
    throw new Error("unexpected call: " + String(path))
  })

  render(<PresurveyAnalysisAction projectId="project-1" fileVersionId="file-1" canManage />)
  await userEvent.click(screen.getByRole("button", { name: "AI 分析预调研表" }))

  const link = await screen.findByRole("link", { name: "前往门禁页提交 G3 证据" })
  expect(link).toHaveAttribute("href", gatesHref("project-1"))
  expect(link).toHaveAttribute("href", "#projects/project-1?tab=gates")
})

it("falls back to the generic error for non-gate failures (no behavior change)", async () => {
  mocks.runTask.mockImplementation(async ({ task }: { task: () => Promise<unknown> }) => task())
  mocks.apiRequest.mockImplementation(async () => {
    throw new ApiClientError({ code: "some_other_error", message: "其他错误", details: null })
  })

  render(<PresurveyAnalysisAction projectId="project-1" fileVersionId="file-1" canManage />)
  await userEvent.click(screen.getByRole("button", { name: "AI 分析预调研表" }))

  await waitFor(() => expect(screen.getByTitle("其他错误")).toBeInTheDocument())
  expect(screen.queryByRole("alert")).toBeNull()
})

it("degrades to message-only hint when the gates list fails to load", async () => {
  mocks.runTask.mockImplementation(async ({ task }: { task: () => Promise<unknown> }) => task())
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path).endsWith("/guidance-analyses")) throw gateOpenError()
    if (String(path).endsWith("/gates")) throw new Error("gates unavailable")
    throw new Error("unexpected call: " + String(path))
  })

  render(<PresurveyAnalysisAction projectId="project-1" fileVersionId="file-1" canManage />)
  await userEvent.click(screen.getByRole("button", { name: "AI 分析预调研表" }))

  const alert = await screen.findByRole("alert")
  await waitFor(() => expect(alert).toHaveTextContent(GATE_OPEN_MESSAGE))
  // 清单拉不到时降级为纯文案态，但跳转锚仍在
  expect(screen.getByRole("link", { name: "前往门禁页提交 G3 证据" })).toBeInTheDocument()
})
