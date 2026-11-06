// @vitest-environment jsdom
// 项目指引三层可视化（台账 T-A4）：客户事实 / AI 判断 / 待确认。
//
// 缺陷基线：GuidanceReview 只读态把条目渲染成纯文本 `<li>`，classification /
// source_refs / confirmed 全部丢弃——客户原话与 AI 推断在界面上完全不可区分，
// 「售前录入的事实需客户确认」这条红线在桌面没有视觉落点；编辑态更是整字段
// 一个 textarea 按行拆，插入或删除一行会让其余条目的分类与原文锚点整体错位，
// 把 A 的锚点贴到 B 的文字上（人工编辑路径是弱校验，错位会静默落库）。
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
}))
vi.mock("../../src/renderer/src/auth/AuthProvider", () => ({
  useAuth: () => ({ apiRequest: mocks.apiRequest }),
}))

import { GuidanceReview } from "../../src/renderer/src/guidance/GuidanceReview"

const LIST_FIELDS = [
  "key_business_problems",
  "priority_departments",
  "priority_roles",
  "priority_processes",
  "success_criteria",
  "out_of_scope",
  "data_security_redlines",
  "systems_and_deployment_constraints",
  "assumptions",
  "open_questions",
  "next_actions",
] as const

function analysisFixture(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  const base: Record<string, unknown> = {
    id: "analysis-ta4",
    project_id: "project-1",
    version_number: 1,
    source_file_id: "file-1",
    source_file_version_id: "ver-1",
    source_filename: "预调研表.docx",
    status: "draft",
    analysis_state: "ready",
    customer_vision: "成为北美家庭理疗设备首选供应商",
    current_phase_objective: "完成试点期获客管道搭建",
    executive_summary: "围绕发现-触达-激活三段推进。",
    failure_code: "",
    failure_message: "",
    source_is_stale: false,
    version: 1,
  }
  for (const field of LIST_FIELDS) base[field] = []
  base.key_business_problems = [
    { text: "客户原话：产线节拍是当前瓶颈", classification: "customer_stated", source_refs: ["kimi-file:ver-1"], confirmed: true },
    { text: "AI 推断：MES 需要预留设备接口", classification: "ai_inferred", source_refs: ["kimi-file:ver-1"], confirmed: false },
    { text: "开口问题：预算上限是多少", classification: "open_question", source_refs: [], confirmed: false },
    { text: "无锚点的 AI 综合项", classification: "ai_synthesized", source_refs: [], confirmed: false },
  ]
  return { ...base, ...overrides }
}

beforeEach(() => {
  mocks.apiRequest.mockReset()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it("只读态：客户原话归客户事实层，AI 推断归 AI 判断层，开口问题归待确认层", () => {
  render(
    <GuidanceReview
      projectId="project-1"
      initial={analysisFixture() as never}
      canManage
      onClose={() => {}}
      onSaved={() => {}}
    />,
  )

  const fact = screen.getByRole("region", { name: "客户事实" })
  const ai = screen.getByRole("region", { name: "AI 判断" })
  const open = screen.getByRole("region", { name: "待确认" })

  expect(within(fact).getByText("客户原话：产线节拍是当前瓶颈")).toBeInTheDocument()
  expect(within(fact).getByText("客户已确认")).toBeInTheDocument()
  expect(within(ai).getByText("AI 推断：MES 需要预留设备接口")).toBeInTheDocument()
  expect(within(open).getByText("开口问题：预算上限是多少")).toBeInTheDocument()
})

it("只读态：无原文锚点的判断项降级为待确认，不混进客户事实层", () => {
  render(
    <GuidanceReview
      projectId="project-1"
      initial={analysisFixture() as never}
      canManage
      onClose={() => {}}
      onSaved={() => {}}
    />,
  )

  const fact = screen.getByRole("region", { name: "客户事实" })
  const open = screen.getByRole("region", { name: "待确认" })

  expect(within(fact).queryByText("无锚点的 AI 综合项")).not.toBeInTheDocument()
  expect(within(open).getByText("无锚点的 AI 综合项")).toBeInTheDocument()
  // 每项都带来源锚点状态：无锚点的显式标出，不假装是原文事实
  // （开口问题与无锚点判断项都无锚点 ⇒ 两处）。
  expect(within(open).getAllByText("无原文锚点")).toHaveLength(2)
})

it("只读态：五类分类各有可读标签，客户原话与 AI 推断不可混淆", () => {
  render(
    <GuidanceReview
      projectId="project-1"
      initial={analysisFixture() as never}
      canManage
      onClose={() => {}}
      onSaved={() => {}}
    />,
  )

  expect(screen.getByText("客户原话")).toBeInTheDocument()
  expect(screen.getByText("AI 推断")).toBeInTheDocument()
  expect(screen.getByText("AI 综合")).toBeInTheDocument()
  // 「待确认」既是层标题也是分类标签——两者都该在。
  expect(screen.getAllByText("待确认").length).toBeGreaterThanOrEqual(2)
  // 条目上带原文锚点（弹窗头部另有一处「来源：文件名」，故限定在层内断言）。
  expect(within(screen.getByRole("region", { name: "客户事实" })).getByText("来源：预调研表.docx")).toBeInTheDocument()
})

it("编辑态：条目粒度呈现，分类与锚点可见可改", () => {
  render(
    <GuidanceReview
      projectId="project-1"
      initial={analysisFixture() as never}
      canManage
      initialEditing
      onClose={() => {}}
      onSaved={() => {}}
    />,
  )

  const group = screen.getByRole("group", { name: "关键业务问题" })
  expect(within(group).getByLabelText("关键业务问题 第 1 条分类")).toHaveValue("customer_stated")
  expect(within(group).getByLabelText("关键业务问题 第 2 条分类")).toHaveValue("ai_inferred")
  expect(within(group).getByLabelText("关键业务问题 第 1 条内容")).toHaveValue("客户原话：产线节拍是当前瓶颈")
  expect(within(group).getByRole("button", { name: "新增条目" })).toBeInTheDocument()
})

it("编辑态：改一条的文本不动其余条目的分类与锚点（错位回归钉）", () => {
  render(
    <GuidanceReview
      projectId="project-1"
      initial={analysisFixture() as never}
      canManage
      initialEditing
      onClose={() => {}}
      onSaved={() => {}}
    />,
  )

  const group = screen.getByRole("group", { name: "关键业务问题" })
  fireEvent.change(within(group).getByLabelText("关键业务问题 第 1 条内容"), { target: { value: "客户原话：产线节拍是当前瓶颈（已确认）" } })

  expect(within(group).getByLabelText("关键业务问题 第 1 条分类")).toHaveValue("customer_stated")
  expect(within(group).getByLabelText("关键业务问题 第 2 条分类")).toHaveValue("ai_inferred")
  expect(within(group).getByLabelText("关键业务问题 第 2 条内容")).toHaveValue("AI 推断：MES 需要预留设备接口")
})

it("编辑态：删除一条后，其余条目的分类与锚点不错位", () => {
  render(
    <GuidanceReview
      projectId="project-1"
      initial={analysisFixture() as never}
      canManage
      initialEditing
      onClose={() => {}}
      onSaved={() => {}}
    />,
  )

  const group = screen.getByRole("group", { name: "关键业务问题" })
  const deleteButtons = within(group).getAllByRole("button", { name: "删除本条" })
  fireEvent.click(deleteButtons[0])

  expect(within(group).getByLabelText("关键业务问题 第 1 条分类")).toHaveValue("ai_inferred")
  expect(within(group).getByLabelText("关键业务问题 第 1 条内容")).toHaveValue("AI 推断：MES 需要预留设备接口")
})

it("编辑态：无锚点条目不能被改成事实类分类（与服务端 missing_source_ref 同口径）", () => {
  render(
    <GuidanceReview
      projectId="project-1"
      initial={analysisFixture() as never}
      canManage
      initialEditing
      onClose={() => {}}
      onSaved={() => {}}
    />,
  )

  const group = screen.getByRole("group", { name: "关键业务问题" })
  const openQuestion = within(group).getByLabelText("关键业务问题 第 3 条分类")
  const options = within(openQuestion).getAllByRole("option").map((option) => (option as HTMLOptionElement).value)
  expect(options).toEqual(["open_question", "human_added"])
})

it("编辑态：新增条目默认为人工补录且无锚点；空条目不随保存提交", async () => {
  mocks.apiRequest.mockImplementation(async () => analysisFixture({ version: 2 }))
  render(
    <GuidanceReview
      projectId="project-1"
      initial={analysisFixture() as never}
      canManage
      initialEditing
      onClose={() => {}}
      onSaved={() => {}}
    />,
  )

  const group = screen.getByRole("group", { name: "关键业务问题" })
  fireEvent.click(within(group).getByRole("button", { name: "新增条目" }))
  expect(within(group).getByLabelText("关键业务问题 第 5 条分类")).toHaveValue("human_added")

  fireEvent.click(screen.getByRole("button", { name: "保存修改" }))
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalled())
  const body = mocks.apiRequest.mock.calls[0][1].body as { key_business_problems: Array<{ text: string }> }
  expect(body.key_business_problems.map((item) => item.text)).not.toContain("")
  expect(body.key_business_problems).toHaveLength(4)
})

it("保存时保留每条目的分类与锚点，不因编辑而降级", async () => {
  mocks.apiRequest.mockImplementation(async () => analysisFixture({ version: 2 }))
  render(
    <GuidanceReview
      projectId="project-1"
      initial={analysisFixture() as never}
      canManage
      initialEditing
      onClose={() => {}}
      onSaved={() => {}}
    />,
  )

  const group = screen.getByRole("group", { name: "关键业务问题" })
  fireEvent.change(within(group).getByLabelText("关键业务问题 第 2 条内容"), { target: { value: "AI 推断：MES 需要预留设备接口（已补充）" } })
  fireEvent.click(screen.getByRole("button", { name: "保存修改" }))

  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalled())
  const body = mocks.apiRequest.mock.calls[0][1].body as { key_business_problems: Array<{ text: string; classification: string; source_refs: string[] }> }
  expect(body.key_business_problems[1]).toEqual({
    text: "AI 推断：MES 需要预留设备接口（已补充）",
    classification: "ai_inferred",
    source_refs: ["kimi-file:ver-1"],
    confirmed: false,
  })
})
