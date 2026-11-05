// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiClientError } from "../../src/renderer/src/api/client"
import {
  OpportunityDetail,
  createEmptyOpportunityProfile,
  draftErrorMessage,
  opportunityProfileErrorMessage,
  opportunityProfileInput,
  validateOpportunityProfile,
} from "../../src/renderer/src/research/ResearchOpportunity"
import type {
  AIOpportunityProfileDto,
  OpportunityLevel,
  OpportunityStatus,
  ResearchSubjectDto,
} from "../../src/renderer/src/research/types"

afterEach(cleanup)

const ownerOptions = [{ id: "user-1", display_name: "张工" }]

const profile: AIOpportunityProfileDto = {
  target_audience: "质检车间班组长",
  owner_user_id: "user-1",
  owner_display_name: "张工",
  opportunity_status: "assessing",
  priority: "high",
  business_value_score: 4,
  feasibility_score: 3,
  data_readiness_score: null,
  risk_level: "low",
  next_action: "两周内完成现场验证",
}

const opportunity: ResearchSubjectDto = {
  id: "opp-1",
  project_id: "project-1",
  parent_subject_id: null,
  subject_type: "opportunity",
  subject_key: "opportunity_opp_1",
  name: "质检缺陷预测",
  description: "利用历史缺陷记录预测高发环节",
  sort_order: 0,
  status: "active",
  tracking_code: "OPP-001",
  version: 3,
  links: [],
  opportunity_profile: profile,
}

describe("CR-037 · 机会档案校验与错误映射纯函数", () => {
  it("合法档案返回空串，createEmptyOpportunityProfile 可直接过校验", () => {
    expect(validateOpportunityProfile(profile, ownerOptions)).toBe("")
    expect(validateOpportunityProfile(createEmptyOpportunityProfile(), [])).toBe("")
  })

  it("目标使用对象与下一步行动超长分别校验", () => {
    expect(validateOpportunityProfile({ ...profile, target_audience: "车".repeat(301) }, ownerOptions))
      .toBe("目标使用对象不能超过 300 个字符。")
    expect(validateOpportunityProfile({ ...profile, next_action: "查".repeat(1001) }, ownerOptions))
      .toBe("下一步行动不能超过 1000 个字符。")
    expect(validateOpportunityProfile({ ...profile, target_audience: "车".repeat(300), next_action: "查".repeat(1000) }, ownerOptions))
      .toBe("")
  })

  it("状态与优先级/风险等级无效值逐一拦截", () => {
    expect(validateOpportunityProfile({ ...profile, opportunity_status: "bogus" as unknown as OpportunityStatus }, ownerOptions))
      .toBe("状态选项无效，请重新选择。")
    expect(validateOpportunityProfile({ ...profile, priority: "urgent" as unknown as OpportunityLevel }, ownerOptions))
      .toBe("优先级选项无效，请重新选择。")
    expect(validateOpportunityProfile({ ...profile, risk_level: "urgent" as unknown as OpportunityLevel }, ownerOptions))
      .toBe("风险等级选项无效，请重新选择。")
  })

  it("三项评分必须是 1 到 5 的整数（0/6/小数拦截，null 放行）", () => {
    const invalidScores = [0, 6, 2.5]
    for (const key of ["business_value_score", "feasibility_score", "data_readiness_score"] as const) {
      for (const score of invalidScores) {
        expect(validateOpportunityProfile({ ...profile, [key]: score }, ownerOptions))
          .toBe(`${key === "business_value_score" ? "业务价值" : key === "feasibility_score" ? "实施可行性" : "数据准备度"}评分必须是 1 到 5 的整数。`)
      }
      expect(validateOpportunityProfile({ ...profile, [key]: null }, ownerOptions)).toBe("")
    }
  })

  it("负责人必须仍在当前项目成员中", () => {
    expect(validateOpportunityProfile({ ...profile, owner_user_id: "user-gone" }, ownerOptions))
      .toBe("负责人已不在当前项目成员中，请重新选择。")
    expect(validateOpportunityProfile({ ...profile, owner_user_id: null, owner_display_name: null }, [])).toBe("")
  })

  it("opportunityProfileInput 裁剪两端空白并丢弃展示名", () => {
    expect(opportunityProfileInput({ ...profile, target_audience: "  质检班组长  ", next_action: "  现场验证  " }))
      .toEqual({
        target_audience: "质检班组长",
        owner_user_id: "user-1",
        opportunity_status: "assessing",
        priority: "high",
        business_value_score: 4,
        feasibility_score: 3,
        data_readiness_score: null,
        risk_level: "low",
        next_action: "现场验证",
      })
  })

  it("opportunityProfileErrorMessage 按错误码映射中文提示并兜底未知错误", () => {
    expect(opportunityProfileErrorMessage(new Error("boom"))).toBe("机会档案保存失败，未知错误。")
    const cases: Array<[string, string]> = [
      ["stale_version", "AI 机会已被其他人更新，请刷新后重试。"],
      ["forbidden", "当前账号没有编辑该 AI 机会的权限。"],
      ["invalid_opportunity_profile", "服务端判定机会档案字段不合法，请刷新页面后重新选择评分、状态和负责人。"],
      ["invalid_opportunity_owner", "负责人必须是当前项目中的有效成员。"],
      ["research_subject_not_found", "该 AI 机会不存在或已被删除。"],
      ["research_subject_archived", "该 AI 机会已停用，无法保存。"],
      ["invalid_request", "当前服务版本不兼容 AI 机会档案，请重启本地服务后重试。"],
      ["network_error", "无法连接本地服务，请检查服务是否已启动。"],
    ]
    for (const [code, message] of cases) {
      expect(opportunityProfileErrorMessage(new ApiClientError({ code, message: "raw" }))).toBe(message)
    }
    expect(opportunityProfileErrorMessage(new ApiClientError({ code: "unknown_code", message: "原始报错" })))
      .toBe("机会档案保存失败：原始报错")
  })

  it("draftErrorMessage 区分 PoV/SOW 文档名并兜底未知错误", () => {
    expect(draftErrorMessage(new Error("boom"), "pov_plan")).toBe("PoV 文档生成任务提交失败：未知错误。")
    expect(draftErrorMessage(new Error("boom"), "sow")).toBe("SOW 文档生成任务提交失败：未知错误。")
    expect(draftErrorMessage(new ApiClientError({ code: "forbidden", message: "raw" }), "pov_plan"))
      .toBe("当前账号没有生成 PoV 文档的权限。")
    expect(draftErrorMessage(new ApiClientError({ code: "forbidden", message: "raw" }), "sow"))
      .toBe("当前账号没有生成 SOW 文档的权限。")
    expect(draftErrorMessage(new ApiClientError({ code: "invalid_source_opportunity", message: "raw" }), "sow"))
      .toBe("该 AI 机会已失效或不属于当前项目，无法生成 SOW 文档。")
    expect(draftErrorMessage(new ApiClientError({ code: "document_template_not_published", message: "raw" }), "pov_plan"))
      .toBe("尚未发布 PoV 文档模板，请先在文档模板中发布后重试。")
    expect(draftErrorMessage(new ApiClientError({ code: "template_version_not_published", message: "raw" }), "sow"))
      .toBe("SOW 文档模板尚未发布，请发布后重试。")
    expect(draftErrorMessage(new ApiClientError({ code: "template_document_type_mismatch", message: "raw" }), "pov_plan"))
      .toBe("已选模板与 PoV 文档类型不匹配。")
    expect(draftErrorMessage(new ApiClientError({ code: "stale_version", message: "raw" }), "sow"))
      .toBe("项目已被其他人更新，请刷新后重试。")
    expect(draftErrorMessage(new ApiClientError({ code: "invalid_request", message: "raw" }), "pov_plan"))
      .toBe("当前服务版本不兼容从 AI 机会创建 PoV 草稿，请重启本地服务后重试。")
    expect(draftErrorMessage(new ApiClientError({ code: "network_error", message: "raw" }), "sow"))
      .toBe("无法连接本地服务，请检查服务是否已启动。")
    expect(draftErrorMessage(new ApiClientError({ code: "unknown_code", message: "原始报错" }), "pov_plan"))
      .toBe("PoV 文档生成任务提交失败：原始报错")
  })
})

function renderDetail(overrides: Partial<Parameters<typeof OpportunityDetail>[0]> = {}) {
  const props: Parameters<typeof OpportunityDetail>[0] = {
    projectId: "project-1",
    opportunity,
    forms: [],
    ownerOptions,
    canManage: false,
    canFill: true,
    editing: false,
    apiRequest: vi.fn(),
    onOpportunityUpdated: vi.fn(),
    onUpdate: vi.fn(),
    onDirtyChange: vi.fn(),
    onEdit: vi.fn(),
    onDelete: vi.fn(),
    onBack: vi.fn(),
    ...overrides,
  }
  return { props, ...render(<OpportunityDetail {...props} />) }
}

describe("CR-037 · OpportunityDetail 组件", () => {
  it("非编辑态渲染档案网格：状态/优先级/评分/风险中文化 + 空表单提示", () => {
    renderDetail()
    expect(screen.getByRole("heading", { name: "质检缺陷预测" })).toBeVisible()
    expect(screen.getByText("评估中")).toBeVisible()
    expect(screen.getByText("优先级")).toBeVisible()
    expect(screen.getByText("高")).toBeVisible()
    expect(screen.getByText("业务价值 4/5")).toBeVisible()
    expect(screen.getByText("实施可行性 3/5")).toBeVisible()
    expect(screen.getByText("低")).toBeVisible()
    expect(screen.getByText("该 AI 机会暂无调研表，请先补充调研表。")).toBeVisible()
    expect(screen.getByRole("button", { name: "编辑" })).toBeVisible()
    expect(screen.queryByRole("button", { name: "保存机会档案" })).not.toBeInTheDocument()
  })

  it("canManage 经更多菜单删除机会", async () => {
    const user = userEvent.setup()
    const { props } = renderDetail({ canManage: true })
    await user.click(screen.getByText("更多"))
    await user.click(screen.getByRole("button", { name: "删除" }))
    expect(props.onDelete).toHaveBeenCalledOnce()
  })

  it("编辑态保存：PATCH 载荷裁剪说明并回执成功", async () => {
    const user = userEvent.setup()
    const updated = { ...opportunity, description: "更新后的说明", version: 4 }
    const apiRequest = vi.fn().mockResolvedValue(updated)
    const { props } = renderDetail({ editing: true, apiRequest })

    await user.type(screen.getByLabelText("说明"), "更新后的说明")
    await user.type(screen.getByLabelText("目标使用对象"), "与班组长")
    await user.click(screen.getByRole("button", { name: "保存机会档案" }))

    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("/api/v1/projects/project-1/research/subjects/opp-1", {
      method: "PATCH",
      body: {
        version: 3,
        description: "利用历史缺陷记录预测高发环节更新后的说明",
        opportunity_profile: {
          target_audience: "质检车间班组长与班组长",
          owner_user_id: "user-1",
          opportunity_status: "assessing",
          priority: "high",
          business_value_score: 4,
          feasibility_score: 3,
          data_readiness_score: null,
          risk_level: "low",
          next_action: "两周内完成现场验证",
        },
      },
    }))
    expect(props.onOpportunityUpdated).toHaveBeenCalledWith(updated)
    expect(await screen.findByRole("status")).toHaveTextContent("机会档案已保存。")
  })

  it("保存失败按错误码映射提示且不回执更新", async () => {
    const user = userEvent.setup()
    const apiRequest = vi.fn().mockRejectedValue(new ApiClientError({ code: "stale_version", message: "stale" }))
    const { props } = renderDetail({ editing: true, apiRequest })

    await user.click(screen.getByRole("button", { name: "保存机会档案" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("AI 机会已被其他人更新，请刷新后重试。")
    expect(props.onOpportunityUpdated).not.toHaveBeenCalled()
    expect(apiRequest).toHaveBeenCalledOnce()
  })

  it("编辑说明置脏并携带 profileKey，卸载自动清脏", async () => {
    const user = userEvent.setup()
    const { props, unmount } = renderDetail({ editing: true })

    await user.type(screen.getByLabelText("说明"), "改动")
    await waitFor(() => expect(props.onDirtyChange).toHaveBeenCalledWith("opportunity-profile:opp-1", true))

    unmount()
    expect(props.onDirtyChange).toHaveBeenLastCalledWith("opportunity-profile:opp-1", false)
  })
})
