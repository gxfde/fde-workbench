// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

const runAI = vi.fn()

vi.mock("../../src/renderer/src/ai/AIExecutionProvider", () => ({
  useAIExecution: () => ({ runAI, runTask: vi.fn() }),
}))

import { AIOpportunityDiscoveryDialog } from "../../src/renderer/src/research/AIOpportunityDiscoveryDialog"
import type { ResearchSubjectDto } from "../../src/renderer/src/research/types"

const subject: ResearchSubjectDto = {
  id: "subject-sales",
  project_id: "project-1",
  parent_subject_id: "subject-root",
  subject_type: "department",
  subject_key: "department_sales",
  name: "销售部",
  description: "",
  sort_order: 0,
  status: "active",
  tracking_code: null,
  version: 1,
  links: [],
}

afterEach(() => {
  cleanup()
  runAI.mockReset()
})

describe("AI opportunity discovery guidance", () => {
  it("sends the user's idea together with the project research scope", async () => {
    runAI.mockResolvedValue({ included_form_count: 0, included_memo_count: 1, candidates: [] })
    render(<AIOpportunityDiscoveryDialog
      projectId="project-1"
      subject={subject}
      apiRequest={vi.fn()}
      onClose={vi.fn()}
      onCreated={vi.fn()}
    />)

    fireEvent.change(screen.getByRole("textbox", { name: "补充想法" }), {
      target: { value: "  优先看销售预测和生产排程  " },
    })
    fireEvent.click(screen.getByRole("button", { name: "开始分析" }))

    await waitFor(() => expect(runAI).toHaveBeenCalledWith(expect.objectContaining({
      operation: "project_ai_opportunities_discover",
      payload: {
        project_id: "project-1",
        subject_id: "subject-sales",
        guidance: "优先看销售预测和生产排程",
        references: ["personal_memos", "shared_memos", "research_forms", "guidance"], expand: true,
      },
    })))
    expect(await screen.findByRole("alert")).toHaveTextContent("已分析 0 张调研表、1 份备忘录")
  })

  it("prefills the created opportunity research form and keeps it editable", async () => {
    const researchAnswers = {
      current_state: "当前人工排程。", pain_points: "排程耗时。", business_value: "提升效率。",
      target_scenario: "生产排程。", owner_role: "计划负责人。", technical_prereqs: "订单数据。",
      delivery_scope: "验证一个工厂。", deliverables: "验证原型。", acceptance_criteria: "耗时下降。",
      data_systems: "ERP。", risks_dependencies: "依赖数据质量。",
    }
    runAI.mockResolvedValue({ included_form_count: 2, included_memo_count: 1, candidates: [{
      id: "candidate-1", name: "智能排程", description: "辅助生产排程", target_audience: "计划部门",
      priority: "high", business_value_score: 5, feasibility_score: 4, data_readiness_score: 3,
      risk_level: "medium", next_action: "核验数据", research_answers: researchAnswers, evidence: [],
    }] })
    const apiRequest = vi.fn(async (path: string, options: { method: string }) => {
      if (path === "/api/v1/projects/project-1" && options.method === "GET") return { version: 3 }
      if (path.endsWith("/research/subjects") && options.method === "POST") return { id: "opportunity-1", version: 1, project_version: 4 }
      if (path.endsWith("/research/forms") && options.method === "GET") return { items: [{
        id: "form-1", project_id: "project-1", subject_id: "opportunity-1", form_key: "ai_opportunity_definition",
        name: "AI 机会调研", description: "", version: 1,
        current_revision: { id: "revision-1", revision_number: 1, parent_revision_id: null, status: "draft", version: 1, returned_by_user_id: null, returned_at: null, return_comment: null, answers: [] },
        completion: {}, definition_snapshot: { form_key: "ai_opportunity_definition", name: "AI 机会调研", description: "", subject_type: "opportunity", module_key: null, sort_order: 0, sections: [{ section_key: "discovery", name: "发现", description: "", sort_order: 0, fields: Object.keys(researchAnswers).map((field_key, sort_order) => ({ field_key, name: field_key, help_text: "", type: "long_text", is_required: false, options: {}, sort_order })) }] },
      }] }
      return {}
    })
    render(<AIOpportunityDiscoveryDialog projectId="project-1" subject={subject} apiRequest={apiRequest} onClose={vi.fn()} onCreated={vi.fn()} />)

    fireEvent.click(screen.getByRole("button", { name: "开始分析" }))
    await screen.findByText("智能排程")
    expect(screen.getByText(/已分析 2 张调研表、1 份备忘录/)).toBeInTheDocument()
    expect(screen.getByText(/同步预填“AI 机会调研”/)).toBeInTheDocument()
    expect(screen.queryByLabelText("交付范围")).not.toBeInTheDocument()
    expect(screen.queryByLabelText("验收标准")).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "保存所选机会（1）" }))

    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith(
      "/api/v1/projects/project-1/research/forms/form-1",
      { method: "PATCH", body: { version: 1, answers: {
        current_state: researchAnswers.current_state, pain_points: researchAnswers.pain_points,
        business_value: researchAnswers.business_value, target_scenario: researchAnswers.target_scenario,
        owner_role: researchAnswers.owner_role, technical_prereqs: researchAnswers.technical_prereqs,
      } } },
    ))
  })
})
