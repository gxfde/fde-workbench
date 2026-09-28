// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AuthProvider } from "../../src/renderer/src/auth/AuthProvider"
import { DangerConfirmProvider } from "../../src/renderer/src/common/DangerConfirmProvider"
import { ResearchDefinitionEditor, chineseResearchPath } from "../../src/renderer/src/research/ResearchDefinitionEditor"
import { TemplateEditor } from "../../src/renderer/src/templates/TemplateEditor"
import type { ApiResponse, BridgeResult } from "../../src/shared/contracts"
import type { TemplateVersionDto } from "../../src/renderer/src/workbench/types"
import { adminUser, authResult, bridge, deferred, installBridge, ok } from "./test-utils"

const emptyDefinition = { version: 4, forms: [] }

const definitionWithTwoFields = {
  version: 4,
  forms: [
    {
      id: "form-1",
      form_key: "role_interview",
      name: "岗位访谈",
      description: "",
      subject_type: "role",
      module_key: null,
      sort_order: 10,
      sections: [
        {
          id: "section-1",
          section_key: "context",
          name: "基本信息",
          description: "",
          sort_order: 10,
          fields: [
            { id: "field-1", field_key: "goal", name: "目标", help_text: "", type: "short_text", is_required: true, options: {}, sort_order: 10 },
            { id: "field-2", field_key: "notes", name: "备注", help_text: "", type: "long_text", is_required: false, options: {}, sort_order: 20 },
          ],
        },
      ],
    },
  ],
}

function apiOk<T>(data: T, status = 200): BridgeResult<ApiResponse<T>> {
  return ok({ status, data, error: null })
}

function apiError(code: string, status: number, details?: unknown): BridgeResult<ApiResponse<never>> {
  return ok({ status, data: null, error: { code, message: `raw-${code}-server-message`, details } })
}

function renderEditor(apiRequest: ReturnType<typeof vi.fn>, onVersionChange = vi.fn()) {
  installBridge(bridge({
    refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
    apiRequest,
  }))
  render(
    <AuthProvider>
      <ResearchDefinitionEditor
        templateId="template-1"
        versionId="version-2"
        version={4}
        moduleKeys={["diagnosis", "pov"]}
        onVersionChange={onVersionChange}
      />
    </AuthProvider>,
  )
  return onVersionChange
}

type CycleConfigurator = (user: ReturnType<typeof userEvent.setup>) => Promise<void>

const cycleConfigurators: Array<[string, CycleConfigurator]> = [
  ["self", async (user) => {
    await user.click(screen.getByLabelText("表单 1 章节 1 字段 1 启用显示条件"))
    await user.selectOptions(screen.getByLabelText("表单 1 章节 1 字段 1 条件引用字段"), "goal")
    await user.type(screen.getByLabelText("表单 1 章节 1 字段 1 条件值"), "ready")
  }],
  ["two-node", async (user) => {
    await user.click(screen.getByLabelText("表单 1 章节 1 字段 1 启用显示条件"))
    await user.selectOptions(screen.getByLabelText("表单 1 章节 1 字段 1 条件引用字段"), "notes")
    await user.type(screen.getByLabelText("表单 1 章节 1 字段 1 条件值"), "ready")
    await user.click(screen.getByLabelText("表单 1 章节 1 字段 2 启用显示条件"))
    await user.selectOptions(screen.getByLabelText("表单 1 章节 1 字段 2 条件引用字段"), "goal")
    await user.type(screen.getByLabelText("表单 1 章节 1 字段 2 条件值"), "ready")
  }],
  ["nested group", async (user) => {
    await user.click(screen.getByLabelText("表单 1 章节 1 字段 1 启用显示条件"))
    await user.selectOptions(screen.getByLabelText("表单 1 章节 1 字段 1 条件运算符"), "all")
    await user.selectOptions(screen.getByLabelText("表单 1 章节 1 字段 1 第 1 个子条件运算符"), "any")
    await user.selectOptions(screen.getByLabelText("表单 1 章节 1 字段 1 第 1 个子条件 第 1 个子条件引用字段"), "goal")
    await user.type(screen.getByLabelText("表单 1 章节 1 字段 1 第 1 个子条件 第 1 个子条件值"), "ready")
  }],
]

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe("ResearchDefinitionEditor", () => {
  it.each([
    ["", "调研定义"],
    ["forms[0].form_key", "第 1 个表单 > 表单稳定标识"],
    ["forms[0].sections[1].fields[2].field_key", "第 1 个表单 > 第 2 个章节 > 第 3 个字段 > 字段稳定标识"],
    ["forms[0].sections[0].fields[1].condition.conditions[2].field_key", "第 1 个表单 > 第 1 个章节 > 第 2 个字段 > 显示条件 > 第 3 个子条件 > 引用字段"],
    ["forms[1].sections[0].fields[0].options.columns[3].type", "第 2 个表单 > 第 1 个章节 > 第 1 个字段 > 字段配置 > 第 4 个表格列 > 类型"],
  ])("maps server path %s to an exact Chinese editor location", (path, expected) => {
    expect(chineseResearchPath(path)).toBe(expected)
  })

  it("maps unknown server paths to a safe generic location", () => {
    expect(chineseResearchPath("forms[0].server_secret.internal_stack")).toBe("调研定义中的某项配置")
  })

  it("manages optional fields, module scope, conditions, and keyboard ordering without mandatory toggles", async () => {
    const apiRequest = vi.fn().mockResolvedValueOnce(apiOk(emptyDefinition))
    renderEditor(apiRequest)
    const user = userEvent.setup()

    await screen.findByText("暂无调研表")
    await user.click(screen.getByRole("button", { name: "新增调研表" }))
    await user.type(screen.getByLabelText("表单 1 名称"), "岗位访谈")
    await user.type(screen.getByLabelText("表单 1 稳定标识"), "role_interview")
    await user.selectOptions(screen.getByLabelText("表单 1 所属模块"), "diagnosis")
    await user.click(screen.getByRole("button", { name: "在表单 1 中新增章节" }))
    await user.type(screen.getByLabelText("表单 1 章节 1 标题"), "基本信息")
    await user.type(screen.getByLabelText("表单 1 章节 1 稳定标识"), "context")
    await user.click(screen.getByRole("button", { name: "在表单 1 章节 1 中新增字段" }))
    await user.click(screen.getByRole("button", { name: "在表单 1 章节 1 中新增字段" }))
    await user.type(screen.getByLabelText("表单 1 章节 1 字段 1 标签"), "目标")
    await user.type(screen.getByLabelText("表单 1 章节 1 字段 1 稳定标识"), "goal")
    expect(screen.queryByLabelText("表单 1 章节 1 字段 1 必填")).not.toBeInTheDocument()
    await user.type(screen.getByLabelText("表单 1 章节 1 字段 2 标签"), "说明")
    await user.type(screen.getByLabelText("表单 1 章节 1 字段 2 稳定标识"), "details")
    await user.click(screen.getByRole("button", { name: "向上移动表单 1 章节 1 字段 2" }))
    expect(screen.getAllByLabelText(/ 字段 \d 标签$/).map((input) => (input as HTMLInputElement).value)).toEqual(["说明", "目标"])
    await user.click(screen.getByLabelText("表单 1 章节 1 字段 1 启用显示条件"))
    await user.selectOptions(screen.getByLabelText("表单 1 章节 1 字段 1 条件运算符"), "equals")
    expect(screen.getByLabelText("表单 1 章节 1 字段 1 条件引用字段")).toBeVisible()
  })

  it("places AI generation before manual creation and appends an editable generated form", async () => {
    const generatedForm = {
      form_key: "production_lead_interview",
      name: "生产部门负责人访谈",
      description: "了解生产计划、质量异常与数据现状。",
      subject_type: "department",
      module_key: "diagnosis",
      sections: [{
        section_key: "business_context",
        name: "业务现状",
        description: "",
        fields: [{
          field_key: "current_process",
          name: "当前流程",
          help_text: "请描述当前流程。",
          type: "long_text",
          is_required: true,
          options: {},
        }],
      }],
    }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk(emptyDefinition))
      .mockResolvedValueOnce(apiOk(generatedForm))
    renderEditor(apiRequest)
    const user = userEvent.setup()

    await screen.findByText("暂无调研表")
    const aiButton = screen.getByRole("button", { name: "AI 辅助生成" })
    const manualButton = screen.getByRole("button", { name: "新增调研表" })
    expect(aiButton.compareDocumentPosition(manualButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    await user.click(aiButton)
    await user.type(screen.getByLabelText("生成要求（可选）"), "生产部门负责人访谈")
    await user.click(screen.getByRole("button", { name: "生成调研表" }))

    expect(await screen.findByLabelText("表单 1 名称")).toHaveValue("生产部门负责人访谈")
    expect(screen.getByLabelText("表单 1 章节 1 字段 1 标签")).toHaveValue("当前流程")
    expect(screen.getByText("AI 已生成调研表，请检查修改后保存。")).toBeVisible()
    expect(apiRequest).toHaveBeenLastCalledWith(
      "/api/v1/ai/industry-template/research-form/generate",
      expect.objectContaining({
        method: "POST",
        body: expect.objectContaining({ requirement: "生产部门负责人访谈" }),
      }),
    )
  })

  it("keeps unsaved research forms mounted across workflow tab changes", async () => {
    const draft: TemplateVersionDto = {
      template_id: "template-1", template_name: "制造业模板", industry_name: "制造业", description: "",
      version_id: "version-2", version_number: 2, status: "draft", version: 4,
      published_by_user_id: null, published_at: null, modules: [],
    }
    const apiRequest = vi.fn().mockResolvedValueOnce(apiOk(emptyDefinition))
    installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
    render(<AuthProvider><DangerConfirmProvider><TemplateEditor draft={draft} catalog={[]} onSaved={vi.fn()} onPublished={vi.fn()} onDeleted={vi.fn()} onCancel={vi.fn()} /></DangerConfirmProvider></AuthProvider>)
    const user = userEvent.setup()

    await user.click(screen.getByRole("tab", { name: "调研表" }))
    await screen.findByText("暂无调研表")
    await user.click(screen.getByRole("button", { name: "新增调研表" }))
    await user.type(screen.getByLabelText("表单 1 名称"), "未保存访谈")
    await user.click(screen.getByRole("tab", { name: "模块与任务" }))
    await user.click(screen.getByRole("tab", { name: "调研表" }))

    expect(screen.getByLabelText("表单 1 名称")).toHaveValue("未保存访谈")
    expect(apiRequest).toHaveBeenCalledTimes(1)
  })

  it("blocks stale base writes when research GET observes a newer aggregate version", async () => {
    const draft: TemplateVersionDto = {
      template_id: "template-1", template_name: "旧模板名", industry_name: "制造业", description: "旧说明",
      version_id: "version-2", version_number: 2, status: "draft", version: 4,
      published_by_user_id: null, published_at: null, modules: [],
    }
    const apiRequest = vi.fn().mockResolvedValueOnce(apiOk({ ...emptyDefinition, version: 5 }))
    const onSaved = vi.fn()
    installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
    render(<AuthProvider><DangerConfirmProvider><TemplateEditor draft={draft} catalog={[]} onSaved={onSaved} onPublished={vi.fn()} onDeleted={vi.fn()} onCancel={vi.fn()} /></DangerConfirmProvider></AuthProvider>)
    const user = userEvent.setup()
    await user.clear(screen.getByLabelText("模板名称"))
    await user.type(screen.getByLabelText("模板名称"), "本地未保存模板名")

    await user.click(screen.getByRole("tab", { name: "调研表" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("服务器完整草稿已更新")
    expect(screen.getByRole("button", { name: "重新加载服务器完整草稿（舍弃本地修改）" })).toBeVisible()
    expect(screen.getByLabelText("模板名称")).toHaveValue("本地未保存模板名")
    await user.click(screen.getByRole("button", { name: "保存草稿" }))
    expect(apiRequest).toHaveBeenCalledTimes(1)
    expect(onSaved).not.toHaveBeenCalled()
  })

  it("does not downgrade when a late research GET returns an older aggregate version", async () => {
    const draft: TemplateVersionDto = {
      template_id: "template-1", template_name: "当前模板", industry_name: "制造业", description: "",
      version_id: "version-2", version_number: 2, status: "draft", version: 5,
      published_by_user_id: null, published_at: null, modules: [],
    }
    const apiRequest = vi.fn().mockResolvedValueOnce(apiOk(emptyDefinition))
    installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
    render(<AuthProvider><DangerConfirmProvider><TemplateEditor draft={draft} catalog={[]} onSaved={vi.fn()} onPublished={vi.fn()} onDeleted={vi.fn()} onCancel={vi.fn()} /></DangerConfirmProvider></AuthProvider>)
    const user = userEvent.setup()

    await user.click(screen.getByRole("tab", { name: "调研表" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("服务器完整草稿已更新")
    expect(screen.getByRole("button", { name: "重新加载服务器完整草稿（舍弃本地修改）" })).toBeVisible()
    await user.click(screen.getByRole("button", { name: "保存草稿" }))
    expect(apiRequest).toHaveBeenCalledTimes(1)
  })

  it("offers the full-snapshot resolution action when an in-editor research save is stale", async () => {
    const draft: TemplateVersionDto = {
      template_id: "template-1", template_name: "当前模板", industry_name: "制造业", description: "",
      version_id: "version-2", version_number: 2, status: "draft", version: 4,
      published_by_user_id: null, published_at: null, modules: [],
    }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk(definitionWithTwoFields))
      .mockResolvedValueOnce(apiError("stale_version", 409))
    installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
    render(<AuthProvider><DangerConfirmProvider><TemplateEditor draft={draft} catalog={[]} onSaved={vi.fn()} onPublished={vi.fn()} onDeleted={vi.fn()} onCancel={vi.fn()} /></DangerConfirmProvider></AuthProvider>)
    const user = userEvent.setup()

    await user.click(screen.getByRole("tab", { name: "调研表" }))
    const formName = await screen.findByLabelText("表单 1 名称")
    await user.clear(formName)
    await user.type(formName, "本地未保存访谈")
    await user.click(screen.getByRole("button", { name: "保存调研模板" }))

    expect(await screen.findByRole("button", { name: "重新加载服务器完整草稿（舍弃本地修改）" })).toBeVisible()
    expect(formName).toHaveValue("本地未保存访谈")
  })

  it("reloads the full base snapshot before saving after another administrator updates it", async () => {
    const draft: TemplateVersionDto = {
      template_id: "template-1", template_name: "旧模板名", industry_name: "旧行业", description: "旧说明",
      version_id: "version-2", version_number: 2, status: "draft", version: 4,
      published_by_user_id: null, published_at: null, modules: [],
    }
    const remote: TemplateVersionDto = {
      ...draft,
      template_name: "管理员乙的新模板名",
      industry_name: "新能源制造",
      description: "管理员乙的新说明",
      version: 5,
    }
    const savedBase = { ...remote, version: 6 }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk({ ...emptyDefinition, version: 5 }))
      .mockResolvedValueOnce(apiOk(remote))
      .mockResolvedValueOnce(apiOk({ ...emptyDefinition, version: 5 }))
      .mockResolvedValueOnce(apiOk(savedBase))
    installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
    render(<AuthProvider><DangerConfirmProvider><TemplateEditor draft={draft} catalog={[]} onSaved={vi.fn()} onPublished={vi.fn()} onDeleted={vi.fn()} onCancel={vi.fn()} /></DangerConfirmProvider></AuthProvider>)
    const user = userEvent.setup()

    await user.click(screen.getByRole("tab", { name: "调研表" }))
    await user.click(await screen.findByRole("button", { name: "重新加载服务器完整草稿（舍弃本地修改）" }))
    expect(await screen.findByLabelText("模板名称")).toHaveValue("管理员乙的新模板名")
    await waitFor(() => expect(apiRequest).toHaveBeenCalledTimes(3))
    await user.click(screen.getByRole("button", { name: "保存草稿" }))

    await screen.findByText("草稿已保存")
    expect(apiRequest).toHaveBeenNthCalledWith(4,
      "/api/v1/industry-templates/versions/version-2",
      expect.objectContaining({
        method: "PATCH",
        body: expect.objectContaining({
          version: 5,
          name: "管理员乙的新模板名",
          industry_name: "新能源制造",
          description: "管理员乙的新说明",
          modules: [],
        }),
      }),
    )
    expect(apiRequest).toHaveBeenCalledTimes(4)
  })

  it("offers every field type and the type-specific options including table columns", async () => {
    const apiRequest = vi.fn().mockResolvedValueOnce(apiOk(definitionWithTwoFields))
    renderEditor(apiRequest)
    const user = userEvent.setup()
    const type = await screen.findByLabelText("表单 1 章节 1 字段 1 类型")

    expect(within(type).getAllByRole("option").map((option) => option.getAttribute("value"))).toEqual([
      "short_text", "long_text", "rich_text", "integer", "decimal", "date", "single_choice", "multi_choice", "table", "file_reference",
    ])
    await user.selectOptions(type, "single_choice")
    expect(screen.getByLabelText("表单 1 章节 1 字段 1 选项（每行一个）")).toBeVisible()
    await user.selectOptions(type, "table")
    await user.click(screen.getByRole("button", { name: "在表单 1 章节 1 字段 1 中新增表格列" }))
    expect(screen.getByLabelText("表单 1 章节 1 字段 1 表格列 1 标题")).toBeVisible()
    await user.selectOptions(type, "file_reference")
    expect(screen.getByLabelText("表单 1 章节 1 字段 1 最多文件数")).toBeVisible()
  })

  it("serializes an integer condition value as a JSON number and exposes recursive edits", async () => {
    const typedDefinition = structuredClone(definitionWithTwoFields)
    typedDefinition.forms[0].sections[0].fields[0] = {
      ...typedDefinition.forms[0].sections[0].fields[0],
      type: "integer",
      options: {},
    }
    typedDefinition.forms[0].sections[0].fields[1] = {
      ...typedDefinition.forms[0].sections[0].fields[1],
      condition: { field_key: "goal", operator: "equals", value: 0 },
    }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk(typedDefinition))
      .mockResolvedValueOnce(apiOk({ ...typedDefinition, version: 5 }))
    renderEditor(apiRequest)
    const user = userEvent.setup()

    const value = await screen.findByLabelText("表单 1 章节 1 字段 2 条件值")
    expect(value).toHaveAttribute("type", "number")
    await user.clear(value)
    await user.type(value, "1")
    await user.selectOptions(screen.getByLabelText("表单 1 章节 1 字段 2 条件运算符"), "all")
    await user.click(screen.getByRole("button", { name: "新增子条件" }))
    expect(screen.getByRole("button", { name: "移除第 2 个子条件" })).toBeVisible()
    await user.click(screen.getByRole("button", { name: "移除第 2 个子条件" }))
    await user.selectOptions(screen.getByLabelText("表单 1 章节 1 字段 2 第 1 个子条件引用字段"), "goal")
    const nestedValue = screen.getByLabelText("表单 1 章节 1 字段 2 第 1 个子条件值")
    await user.clear(nestedValue)
    await user.type(nestedValue, "1")
    await user.click(screen.getByRole("button", { name: "保存调研模板" }))

    await screen.findByText("调研模板已保存")
    const body = apiRequest.mock.calls[1][1].body
    expect(body.forms[0].sections[0].fields[1].condition).toEqual({
      operator: "all",
      conditions: [{ field_key: "goal", operator: "equals", value: 1 }],
    })
  })

  it("reports a missing or unsupported condition reference before PUT", async () => {
    const invalid = structuredClone(definitionWithTwoFields)
    invalid.forms[0].sections[0].fields[0] = {
      ...invalid.forms[0].sections[0].fields[0],
      type: "rich_text",
      options: {},
    }
    invalid.forms[0].sections[0].fields[1] = {
      ...invalid.forms[0].sections[0].fields[1],
      condition: { field_key: "goal", operator: "equals", value: "text" },
    }
    const apiRequest = vi.fn().mockResolvedValueOnce(apiOk(invalid))
    renderEditor(apiRequest)
    const user = userEvent.setup()

    expect(await screen.findByRole("alert")).toHaveTextContent("服务器返回的调研模板数据格式无效")
    await user.click(screen.getByRole("button", { name: "保存调研模板" }))
    expect(apiRequest).toHaveBeenCalledTimes(1)
  })

  it("rejects a non-text condition value for a text controller before PUT", async () => {
    const invalid = structuredClone(definitionWithTwoFields)
    invalid.forms[0].sections[0].fields[1] = {
      ...invalid.forms[0].sections[0].fields[1],
      condition: { field_key: "goal", operator: "equals", value: 1 },
    }
    const apiRequest = vi.fn().mockResolvedValueOnce(apiOk(invalid))
    renderEditor(apiRequest)

    expect(await screen.findByRole("alert")).toHaveTextContent("服务器返回的调研模板数据格式无效")
    expect(apiRequest).toHaveBeenCalledTimes(1)
  })

  it("rejects a non-decimal string condition value before PUT", async () => {
    const invalid = structuredClone(definitionWithTwoFields)
    invalid.forms[0].sections[0].fields[0] = {
      ...invalid.forms[0].sections[0].fields[0], type: "decimal", options: {},
    }
    invalid.forms[0].sections[0].fields[1] = {
      ...invalid.forms[0].sections[0].fields[1],
      condition: { field_key: "goal", operator: "equals", value: "not-a-decimal" },
    }
    const apiRequest = vi.fn().mockResolvedValueOnce(apiOk(invalid))
    renderEditor(apiRequest)

    expect(await screen.findByRole("alert")).toHaveTextContent("服务器返回的调研模板数据格式无效")
    expect(apiRequest).toHaveBeenCalledTimes(1)
  })

  it("can edit and re-save a legal server decimal condition snapshot", async () => {
    const preciseDecimal = "123456789012345678901234567890.1234567890123456789"
    const valid = structuredClone(definitionWithTwoFields)
    valid.forms[0].sections[0].fields[0] = {
      ...valid.forms[0].sections[0].fields[0], type: "decimal", options: {},
    }
    valid.forms[0].sections[0].fields[1] = {
      ...valid.forms[0].sections[0].fields[1],
      condition: { field_key: "goal", operator: "equals", value: preciseDecimal },
    }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk(valid))
      .mockResolvedValueOnce(apiOk({ ...valid, version: 5 }))
    renderEditor(apiRequest)
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText("表单 1 名称"), "更新")
    await user.click(screen.getByRole("button", { name: "保存调研模板" }))

    expect(await screen.findByText("调研模板已保存")).toBeVisible()
    expect(apiRequest.mock.calls[1][1].body.forms[0].sections[0].fields[1].condition).toEqual({
      field_key: "goal", operator: "equals", value: preciseDecimal,
    })
  })

  it("normalizes a text condition to the stored answer contract before PUT", async () => {
    const valid = structuredClone(definitionWithTwoFields)
    valid.forms[0].sections[0].fields[1] = {
      ...valid.forms[0].sections[0].fields[1],
      condition: { field_key: "goal", operator: "equals", value: "ready" },
    }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk(valid))
      .mockResolvedValueOnce(apiOk({ ...valid, version: 5 }))
    renderEditor(apiRequest)
    const user = userEvent.setup()
    const conditionValue = await screen.findByLabelText("表单 1 章节 1 字段 2 条件值")

    await user.clear(conditionValue)
    await user.type(conditionValue, "  ready  ")
    await user.tab()
    expect(conditionValue).toHaveValue("ready")
    await user.type(screen.getByLabelText("表单 1 名称"), "更新")
    await user.click(screen.getByRole("button", { name: "保存调研模板" }))

    expect(await screen.findByText("调研模板已保存")).toBeVisible()
    expect(apiRequest.mock.calls[1][1].body.forms[0].sections[0].fields[1].condition.value).toBe("ready")
  })

  it("normalizes a bounded decimal exponent without JavaScript number conversion", async () => {
    const valid = structuredClone(definitionWithTwoFields)
    valid.forms[0].sections[0].fields[0] = {
      ...valid.forms[0].sections[0].fields[0], type: "decimal", options: {},
    }
    valid.forms[0].sections[0].fields[1] = {
      ...valid.forms[0].sections[0].fields[1],
      condition: { field_key: "goal", operator: "equals", value: "1" },
    }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk(valid))
      .mockResolvedValueOnce(apiOk({ ...valid, version: 5 }))
    renderEditor(apiRequest)
    const user = userEvent.setup()
    const input = await screen.findByLabelText("表单 1 章节 1 字段 2 条件值")

    await user.clear(input)
    await user.type(input, "1e2")
    await user.tab()
    expect(input).toHaveValue("100")
    await user.click(screen.getByRole("button", { name: "保存调研模板" }))

    expect(await screen.findByText("调研模板已保存")).toBeVisible()
    expect(apiRequest.mock.calls[1][1].body.forms[0].sections[0].fields[1].condition.value).toBe("100")
  })

  it("preflights an oversized plain decimal before any base or research write", async () => {
    const draft: TemplateVersionDto = {
      template_id: "template-1", template_name: "制造业模板", industry_name: "制造业", description: "",
      version_id: "version-2", version_number: 2, status: "draft", version: 4,
      published_by_user_id: null, published_at: null, modules: [],
    }
    const valid = structuredClone(definitionWithTwoFields)
    valid.forms[0].sections[0].fields[0] = {
      ...valid.forms[0].sections[0].fields[0], type: "decimal", options: {},
    }
    valid.forms[0].sections[0].fields[1] = {
      ...valid.forms[0].sections[0].fields[1],
      condition: { field_key: "goal", operator: "equals", value: "1" },
    }
    const apiRequest = vi.fn().mockResolvedValueOnce(apiOk(valid))
    installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
    render(<AuthProvider><DangerConfirmProvider><TemplateEditor draft={draft} catalog={[]} onSaved={vi.fn()} onPublished={vi.fn()} onDeleted={vi.fn()} onCancel={vi.fn()} /></DangerConfirmProvider></AuthProvider>)
    const user = userEvent.setup()
    await user.click(screen.getByRole("tab", { name: "调研表" }))
    const input = await screen.findByLabelText("表单 1 章节 1 字段 2 条件值")
    await user.clear(input)
    await user.type(input, "9".repeat(101))

    await user.click(screen.getByRole("button", { name: "保存草稿" }))

    const alerts = await screen.findAllByRole("alert")
    expect(alerts.some((alert) => alert.textContent?.includes("小数条件值超出支持范围"))).toBe(true)
    expect(apiRequest).toHaveBeenCalledTimes(1)
  })

  it.each(["\ufeffready\ufeff", "\u0085ready\u0085"])(
    "preserves non-ASCII text edge content when editing and saving: %s",
    async (value) => {
      const valid = structuredClone(definitionWithTwoFields)
      valid.forms[0].sections[0].fields[1] = {
        ...valid.forms[0].sections[0].fields[1],
        condition: { field_key: "goal", operator: "equals", value: "ready" },
      }
      const apiRequest = vi.fn()
        .mockResolvedValueOnce(apiOk(valid))
        .mockResolvedValueOnce(apiOk({ ...valid, version: 5 }))
      renderEditor(apiRequest)
      const user = userEvent.setup()
      const input = await screen.findByLabelText("表单 1 章节 1 字段 2 条件值")

      await user.clear(input)
      await user.type(input, value)
      await user.tab()
      expect(input).toHaveValue(value)
      await user.click(screen.getByRole("button", { name: "保存调研模板" }))

      expect(await screen.findByText("调研模板已保存")).toBeVisible()
      expect(apiRequest.mock.calls[1][1].body.forms[0].sections[0].fields[1].condition.value).toBe(value)
    },
  )

  it("rejects an impossible ISO-shaped date condition before PUT", async () => {
    const invalid = structuredClone(definitionWithTwoFields)
    invalid.forms[0].sections[0].fields[0] = {
      ...invalid.forms[0].sections[0].fields[0], type: "date", options: {},
    }
    invalid.forms[0].sections[0].fields[1] = {
      ...invalid.forms[0].sections[0].fields[1],
      condition: { field_key: "goal", operator: "equals", value: "2026-13-40" },
    }
    const apiRequest = vi.fn().mockResolvedValueOnce(apiOk(invalid))
    renderEditor(apiRequest)

    expect(await screen.findByRole("alert")).toHaveTextContent("服务器返回的调研模板数据格式无效")
    expect(apiRequest).toHaveBeenCalledTimes(1)
  })

  it("rejects duplicate table column keys and undeclared choice defaults before PUT", async () => {
    const apiRequest = vi.fn().mockResolvedValueOnce(apiOk(definitionWithTwoFields))
    renderEditor(apiRequest)
    const user = userEvent.setup()
    const type = await screen.findByLabelText("表单 1 章节 1 字段 1 类型")
    await user.selectOptions(type, "table")
    await user.click(screen.getByRole("button", { name: "在表单 1 章节 1 字段 1 中新增表格列" }))
    await user.click(screen.getByRole("button", { name: "在表单 1 章节 1 字段 1 中新增表格列" }))
    const keys = screen.getAllByLabelText(/表格列 \d 稳定标识$/)
    const names = screen.getAllByLabelText(/表格列 \d 标题$/)
    await user.type(keys[0], "item")
    await user.type(keys[1], "item")
    await user.type(names[0], "项目一")
    await user.type(names[1], "项目二")
    await user.click(screen.getByRole("button", { name: "保存调研模板" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("表格列稳定标识必须唯一")
    expect(apiRequest).toHaveBeenCalledTimes(1)

    await user.selectOptions(type, "single_choice")
    await user.type(screen.getByLabelText("表单 1 章节 1 字段 1 选项（每行一个）"), "是\n否")
    await user.type(screen.getByLabelText("表单 1 章节 1 字段 1 默认选项（每行一个）"), "未知")
    await user.click(screen.getByRole("button", { name: "保存调研模板" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("默认选项必须来自已声明选项")
    expect(apiRequest).toHaveBeenCalledTimes(1)
  })

  it("restores focus to the adjacent field control after deleting a field", async () => {
    const apiRequest = vi.fn().mockResolvedValueOnce(apiOk(definitionWithTwoFields))
    renderEditor(apiRequest)
    const user = userEvent.setup()
    const removeFirst = await screen.findByRole("button", { name: "移除表单 1 章节 1 字段 1" })

    await user.click(removeFirst)

    expect(screen.getByRole("button", { name: "移除表单 1 章节 1 字段 1" })).toHaveFocus()
  })

  it("restores focus to the adjacent table column after deleting a column", async () => {
    const apiRequest = vi.fn().mockResolvedValueOnce(apiOk(definitionWithTwoFields))
    renderEditor(apiRequest)
    const user = userEvent.setup()
    await user.selectOptions(await screen.findByLabelText("表单 1 章节 1 字段 1 类型"), "table")
    const addColumn = screen.getByRole("button", { name: "在表单 1 章节 1 字段 1 中新增表格列" })
    await user.click(addColumn)
    await user.click(addColumn)

    await user.click(screen.getByRole("button", { name: "移除表单 1 章节 1 字段 1 表格列 2" }))

    expect(screen.getByRole("button", { name: "移除表单 1 章节 1 字段 1 表格列 1" })).toHaveFocus()
  })

  it("saves a closed definition and adopts the server version", async () => {
    const saved = { ...definitionWithTwoFields, version: 5 }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk(definitionWithTwoFields))
      .mockResolvedValueOnce(apiOk(saved))
    const onVersionChange = renderEditor(apiRequest)
    const user = userEvent.setup()

    await user.clear(await screen.findByLabelText("表单 1 名称"))
    await user.type(screen.getByLabelText("表单 1 名称"), "新岗位访谈")
    await user.click(screen.getByRole("button", { name: "保存调研模板" }))

    expect(await screen.findByText("调研模板已保存")).toBeVisible()
    expect(apiRequest).toHaveBeenNthCalledWith(2,
      "/api/v1/templates/template-1/versions/version-2/research-forms",
      expect.objectContaining({ method: "PUT", body: expect.objectContaining({ version: 4 }) }),
    )
    const body = apiRequest.mock.calls[1][1].body
    expect(body.forms[0].name).toBe("新岗位访谈")
    expect(onVersionChange).toHaveBeenCalledWith(5)
  })

  it("shows exact Chinese validation paths without exposing the raw response", async () => {
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk(definitionWithTwoFields))
      .mockResolvedValueOnce(apiError("invalid_research_definition", 400, {
        issues: [{ code: "unknown_condition_field", path: "forms[0].sections[0].fields[1].condition.field_key" }],
        stack: "SECRET STACK",
      }))
    renderEditor(apiRequest)
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText("表单 1 名称"), "更新")
    await user.click(screen.getByRole("button", { name: "保存调研模板" }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("第 1 个表单 > 第 1 个章节 > 第 2 个字段 > 显示条件 > 引用字段")
    expect(alert).not.toHaveTextContent("SECRET STACK")
    expect(alert).not.toHaveTextContent("raw-invalid_research_definition-server-message")
  })

  it.each([
    ["stale_version", "调研模板已被其他操作更新"],
    ["forbidden", "当前账号无权修改调研模板"],
    ["network_error", "网络连接异常"],
  ])("keeps local input and presents a safe message for %s", async (code, message) => {
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk(definitionWithTwoFields))
      .mockResolvedValueOnce(apiError(code, code === "stale_version" ? 409 : code === "forbidden" ? 403 : 503, { stack: "SECRET STACK" }))
    renderEditor(apiRequest)
    const user = userEvent.setup()
    const name = await screen.findByLabelText("表单 1 名称")
    await user.clear(name)
    await user.type(name, "本地未保存内容")
    await user.click(screen.getByRole("button", { name: "保存调研模板" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(message)
    expect(name).toHaveValue("本地未保存内容")
    expect(screen.getByRole("alert")).not.toHaveTextContent("SECRET STACK")
    expect(apiRequest).toHaveBeenCalledTimes(2)
  })

  it("labels every control, uses fieldsets, explicit button types, and keeps move controls keyboard focusable", async () => {
    const apiRequest = vi.fn().mockResolvedValueOnce(apiOk(definitionWithTwoFields))
    renderEditor(apiRequest)
    await screen.findByLabelText("表单 1 名称")

    expect(screen.getAllByRole("group").length).toBeGreaterThan(0)
    const buttons = screen.getAllByRole("button")
    expect(buttons.every((button) => button.getAttribute("type") === "button")).toBe(true)
    expect(screen.getByLabelText("表单 1 稳定标识")).toBeDisabled()
    expect(screen.getByLabelText("表单 1 章节 1 稳定标识")).toBeDisabled()
    expect(screen.getByLabelText("表单 1 章节 1 字段 1 稳定标识")).toBeDisabled()
    const move = screen.getByRole("button", { name: "向上移动表单 1 章节 1 字段 2" })
    move.focus()
    expect(move).toHaveFocus()
    expect(document.querySelectorAll("input:not([aria-label]):not([id])")).toHaveLength(0)
  })

  it("integrates with TemplateEditor and publishes only after saving research at the latest aggregate version", async () => {
    const draft: TemplateVersionDto = {
      template_id: "template-1",
      template_name: "制造业模板",
      industry_name: "制造业",
      description: "",
      version_id: "version-2",
      version_number: 2,
      status: "draft",
      version: 4,
      published_by_user_id: null,
      published_at: null,
      modules: [],
    }
    const savedTemplate = { ...draft, version: 5 }
    const savedResearch = { ...definitionWithTwoFields, version: 6 }
    const published = { ...savedTemplate, version: 7, status: "published" as const, published_by_user_id: "admin-1", published_at: "2026-08-24T09:00:00+08:00" }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk(definitionWithTwoFields))
      .mockResolvedValueOnce(apiOk(savedTemplate))
      .mockResolvedValueOnce(apiOk(savedResearch))
      .mockResolvedValueOnce(apiOk(published))
    const onPublished = vi.fn()
    installBridge(bridge({
      refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
      apiRequest,
    }))
    render(<AuthProvider><DangerConfirmProvider><TemplateEditor
      draft={draft}
      catalog={[]}
      onSaved={vi.fn()}
      onPublished={onPublished}
      onDeleted={vi.fn()}
      onCancel={vi.fn()}
    /></DangerConfirmProvider></AuthProvider>)
    const user = userEvent.setup()

    const workflowTab = screen.getByRole("tab", { name: "模块与任务" })
    const researchTab = screen.getByRole("tab", { name: "调研表" })
    workflowTab.focus()
    await user.keyboard("{ArrowRight}")
    expect(researchTab).toHaveFocus()
    expect(researchTab).toHaveAttribute("aria-selected", "true")
    await user.clear(await screen.findByLabelText("表单 1 名称"))
    await user.type(screen.getByLabelText("表单 1 名称"), "本地调研修改")
    await user.click(screen.getByRole("button", { name: "保存并发布调研模板" }))

    await waitFor(() => expect(onPublished).toHaveBeenCalledWith(published))
    expect(apiRequest).toHaveBeenNthCalledWith(2,
      "/api/v1/industry-templates/versions/version-2",
      expect.objectContaining({ method: "PATCH", body: expect.objectContaining({ version: 4 }) }),
    )
    expect(apiRequest).toHaveBeenNthCalledWith(3,
      "/api/v1/templates/template-1/versions/version-2/research-forms",
      expect.objectContaining({ method: "PUT", body: expect.objectContaining({ version: 5 }) }),
    )
    expect(apiRequest).toHaveBeenNthCalledWith(4,
      "/api/v1/industry-templates/versions/version-2/publish",
      expect.objectContaining({ method: "POST", body: { version: 6 } }),
    )
  })

  it("global draft save persists base then the mounted research draft at the latest version", async () => {
    const draft: TemplateVersionDto = {
      template_id: "template-1", template_name: "制造业模板", industry_name: "制造业", description: "",
      version_id: "version-2", version_number: 2, status: "draft", version: 4,
      published_by_user_id: null, published_at: null, modules: [],
    }
    const savedBase = { ...draft, template_name: "制造业新模板", version: 5 }
    const savedResearch = { ...definitionWithTwoFields, version: 6 }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk(definitionWithTwoFields))
      .mockResolvedValueOnce(apiOk(savedBase))
      .mockResolvedValueOnce(apiOk(savedResearch))
    const onSaved = vi.fn()
    installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
    render(<AuthProvider><DangerConfirmProvider><TemplateEditor draft={draft} catalog={[]} onSaved={onSaved} onPublished={vi.fn()} onDeleted={vi.fn()} onCancel={vi.fn()} /></DangerConfirmProvider></AuthProvider>)
    const user = userEvent.setup()

    await user.click(screen.getByRole("tab", { name: "调研表" }))
    await user.clear(await screen.findByLabelText("表单 1 名称"))
    await user.type(screen.getByLabelText("表单 1 名称"), "本地调研草稿")
    await user.click(screen.getByRole("tab", { name: "模块与任务" }))
    await user.clear(screen.getByLabelText("模板名称"))
    await user.type(screen.getByLabelText("模板名称"), "制造业新模板")
    await user.click(screen.getByRole("button", { name: "保存草稿" }))

    expect(await screen.findByText("草稿已保存")).toBeVisible()
    expect(apiRequest).toHaveBeenNthCalledWith(2,
      "/api/v1/industry-templates/versions/version-2",
      expect.objectContaining({ method: "PATCH", body: expect.objectContaining({ version: 4, name: "制造业新模板" }) }),
    )
    expect(apiRequest).toHaveBeenNthCalledWith(3,
      "/api/v1/templates/template-1/versions/version-2/research-forms",
      expect.objectContaining({ method: "PUT", body: expect.objectContaining({ version: 5, forms: [expect.objectContaining({ name: "本地调研草稿" })] }) }),
    )
    expect(onSaved).toHaveBeenLastCalledWith(expect.objectContaining({ version: 6 }))
  })

  it("preflights invalid mounted research before any base or research write", async () => {
    const draft: TemplateVersionDto = {
      template_id: "template-1", template_name: "制造业模板", industry_name: "制造业", description: "",
      version_id: "version-2", version_number: 2, status: "draft", version: 4,
      published_by_user_id: null, published_at: null, modules: [],
    }
    const loaded = structuredClone(definitionWithTwoFields)
    loaded.forms[0].sections[0].fields[1] = {
      ...loaded.forms[0].sections[0].fields[1],
      condition: { field_key: "goal", operator: "equals", value: "safe comparison" },
    }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk(loaded))
      .mockResolvedValueOnce(apiOk({ ...draft, version: 5 }))
    installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
    render(<AuthProvider><DangerConfirmProvider><TemplateEditor draft={draft} catalog={[]} onSaved={vi.fn()} onPublished={vi.fn()} onDeleted={vi.fn()} onCancel={vi.fn()} /></DangerConfirmProvider></AuthProvider>)
    const user = userEvent.setup()
    await user.click(screen.getByRole("tab", { name: "调研表" }))
    await screen.findByLabelText("表单 1 名称")
    await user.selectOptions(screen.getByLabelText("表单 1 章节 1 字段 1 类型"), "rich_text")

    await user.click(screen.getByRole("button", { name: "保存草稿" }))

    const alerts = await screen.findAllByRole("alert")
    expect(alerts.some((alert) => alert.textContent?.includes("该字段类型不支持条件比较"))).toBe(true)
    expect(apiRequest).toHaveBeenCalledTimes(1)
  })

  it.each(cycleConfigurators)(
    "preflights a %s condition cycle before any base or research write",
    async (_name, configureCycle) => {
      const draft: TemplateVersionDto = {
        template_id: "template-1", template_name: "制造业模板", industry_name: "制造业", description: "",
        version_id: "version-2", version_number: 2, status: "draft", version: 4,
        published_by_user_id: null, published_at: null, modules: [],
      }
      const apiRequest = vi.fn().mockResolvedValueOnce(apiOk(definitionWithTwoFields))
      installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
      render(<AuthProvider><DangerConfirmProvider><TemplateEditor draft={draft} catalog={[]} onSaved={vi.fn()} onPublished={vi.fn()} onDeleted={vi.fn()} onCancel={vi.fn()} /></DangerConfirmProvider></AuthProvider>)
      const user = userEvent.setup()
      await user.click(screen.getByRole("tab", { name: "调研表" }))
      await screen.findByLabelText("表单 1 名称")
      await configureCycle(user)

      await user.click(screen.getByRole("button", { name: "保存草稿" }))

      const alerts = await screen.findAllByRole("alert")
      expect(alerts.some((alert) => alert.textContent?.includes("显示条件不能形成循环依赖"))).toBe(true)
      expect(apiRequest).toHaveBeenCalledTimes(1)
    },
  )

  it("preflights a new blank research form before any base or research write", async () => {
    const draft: TemplateVersionDto = {
      template_id: "template-1", template_name: "制造业模板", industry_name: "制造业", description: "",
      version_id: "version-2", version_number: 2, status: "draft", version: 4,
      published_by_user_id: null, published_at: null, modules: [],
    }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk(emptyDefinition))
      .mockResolvedValueOnce(apiOk({ ...draft, version: 5 }))
    installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
    render(<AuthProvider><DangerConfirmProvider><TemplateEditor draft={draft} catalog={[]} onSaved={vi.fn()} onPublished={vi.fn()} onDeleted={vi.fn()} onCancel={vi.fn()} /></DangerConfirmProvider></AuthProvider>)
    const user = userEvent.setup()
    await user.click(screen.getByRole("tab", { name: "调研表" }))
    await screen.findByText("暂无调研表")
    await user.click(screen.getByRole("button", { name: "新增调研表" }))

    await user.click(screen.getByRole("button", { name: "保存草稿" }))

    const alerts = await screen.findAllByRole("alert")
    expect(alerts.some((alert) => alert.textContent?.includes("表单名称和稳定标识"))).toBe(true)
    expect(apiRequest).toHaveBeenCalledTimes(1)
  })

  it.each([
    ["负数最小长度", "-1", "", "长度限制必须是非负整数"],
    ["反向长度范围", "10", "5", "最小长度不能大于最大长度"],
  ])("preflights %s before any base or research write", async (_caseName, minimum, maximum, message) => {
    const draft: TemplateVersionDto = {
      template_id: "template-1", template_name: "制造业模板", industry_name: "制造业", description: "",
      version_id: "version-2", version_number: 2, status: "draft", version: 4,
      published_by_user_id: null, published_at: null, modules: [],
    }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk(definitionWithTwoFields))
      .mockResolvedValueOnce(apiOk({ ...draft, version: 5 }))
      .mockResolvedValueOnce(apiOk({ ...definitionWithTwoFields, version: 6 }))
    installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
    render(<AuthProvider><DangerConfirmProvider><TemplateEditor draft={draft} catalog={[]} onSaved={vi.fn()} onPublished={vi.fn()} onDeleted={vi.fn()} onCancel={vi.fn()} /></DangerConfirmProvider></AuthProvider>)
    const user = userEvent.setup()
    await user.click(screen.getByRole("tab", { name: "调研表" }))
    const minimumInput = await screen.findByLabelText("表单 1 章节 1 字段 1 最小长度")
    await user.clear(minimumInput)
    await user.type(minimumInput, minimum)
    if (maximum) {
      const maximumInput = screen.getByLabelText("表单 1 章节 1 字段 1 最大长度")
      await user.clear(maximumInput)
      await user.type(maximumInput, maximum)
    }

    await user.click(screen.getByRole("button", { name: "保存草稿" }))

    const alerts = await screen.findAllByRole("alert")
    expect(alerts.some((alert) => alert.textContent?.includes(message))).toBe(true)
    expect(apiRequest).toHaveBeenCalledTimes(1)
  })

  it("saves base without replacing existing research when the research tab was never opened", async () => {
    const draft: TemplateVersionDto = {
      template_id: "template-1", template_name: "制造业模板", industry_name: "制造业", description: "",
      version_id: "version-2", version_number: 2, status: "draft", version: 4,
      published_by_user_id: null, published_at: null, modules: [],
    }
    const savedBase = { ...draft, template_name: "制造业模板二", version: 5 }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk({ ...definitionWithTwoFields, version: 4 }))
      .mockResolvedValueOnce(apiOk(savedBase))
    installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
    render(<AuthProvider><DangerConfirmProvider><TemplateEditor draft={draft} catalog={[]} onSaved={vi.fn()} onPublished={vi.fn()} onDeleted={vi.fn()} onCancel={vi.fn()} /></DangerConfirmProvider></AuthProvider>)
    const user = userEvent.setup()
    await user.clear(screen.getByLabelText("模板名称"))
    await user.type(screen.getByLabelText("模板名称"), "制造业模板二")

    await user.click(screen.getByRole("button", { name: "保存草稿" }))

    expect(await screen.findByText("草稿已保存")).toBeVisible()
    expect(apiRequest).toHaveBeenCalledTimes(2)
    expect(apiRequest).toHaveBeenNthCalledWith(1,
      "/api/v1/templates/template-1/versions/version-2/research-forms",
      expect.objectContaining({ method: "GET" }),
    )
    expect(apiRequest).toHaveBeenNthCalledWith(2,
      "/api/v1/industry-templates/versions/version-2",
      expect.objectContaining({ method: "PATCH", body: expect.objectContaining({ version: 4 }) }),
    )
  })

  it("does not replace loaded research until the user changes it", async () => {
    const draft: TemplateVersionDto = {
      template_id: "template-1", template_name: "制造业模板", industry_name: "制造业", description: "",
      version_id: "version-2", version_number: 2, status: "draft", version: 4,
      published_by_user_id: null, published_at: null, modules: [],
    }
    const savedBase = { ...draft, description: "仅修改基础说明", version: 5 }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk(definitionWithTwoFields))
      .mockResolvedValueOnce(apiOk(savedBase))
    installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
    render(<AuthProvider><DangerConfirmProvider><TemplateEditor draft={draft} catalog={[]} onSaved={vi.fn()} onPublished={vi.fn()} onDeleted={vi.fn()} onCancel={vi.fn()} /></DangerConfirmProvider></AuthProvider>)
    const user = userEvent.setup()
    await user.click(screen.getByRole("tab", { name: "调研表" }))
    await screen.findByLabelText("表单 1 名称")
    await user.click(screen.getByRole("tab", { name: "模块与任务" }))
    await user.type(screen.getByLabelText("模板说明"), "仅修改基础说明")

    await user.click(screen.getByRole("button", { name: "保存草稿" }))

    expect(await screen.findByText("草稿已保存")).toBeVisible()
    expect(apiRequest).toHaveBeenCalledTimes(2)
  })

  it("adopts a base-only aggregate version before the next research edit and save", async () => {
    const draft: TemplateVersionDto = {
      template_id: "template-1", template_name: "制造业模板", industry_name: "制造业", description: "",
      version_id: "version-2", version_number: 2, status: "draft", version: 4,
      published_by_user_id: null, published_at: null, modules: [],
    }
    const savedBase = { ...draft, description: "只修改基础说明", version: 5 }
    const savedResearch = {
      ...definitionWithTwoFields,
      version: 6,
      forms: [{ ...definitionWithTwoFields.forms[0], name: "岗位访谈更新" }],
    }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk(definitionWithTwoFields))
      .mockResolvedValueOnce(apiOk(savedBase))
      .mockResolvedValueOnce(apiOk(savedResearch))
    installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
    render(<AuthProvider><DangerConfirmProvider><TemplateEditor draft={draft} catalog={[]} onSaved={vi.fn()} onPublished={vi.fn()} onDeleted={vi.fn()} onCancel={vi.fn()} /></DangerConfirmProvider></AuthProvider>)
    const user = userEvent.setup()
    await user.click(screen.getByRole("tab", { name: "调研表" }))
    await screen.findByLabelText("表单 1 名称")
    await user.click(screen.getByRole("tab", { name: "模块与任务" }))
    await user.type(screen.getByLabelText("模板说明"), "只修改基础说明")
    await user.click(screen.getByRole("button", { name: "保存草稿" }))
    await screen.findByText("草稿已保存")

    await user.click(screen.getByRole("tab", { name: "调研表" }))
    const formName = screen.getByLabelText("表单 1 名称")
    expect(formName).toBeEnabled()
    await user.clear(formName)
    await user.type(formName, "岗位访谈更新")
    await user.click(screen.getByRole("button", { name: "保存调研模板" }))

    expect(await screen.findByText("调研模板已保存")).toBeVisible()
    expect(apiRequest).toHaveBeenCalledTimes(3)
    expect(apiRequest).toHaveBeenNthCalledWith(3,
      "/api/v1/templates/template-1/versions/version-2/research-forms",
      expect.objectContaining({ method: "PUT", body: expect.objectContaining({ version: 5 }) }),
    )
  })

  it("clears research dirty state after a successful local save", async () => {
    const draft: TemplateVersionDto = {
      template_id: "template-1", template_name: "制造业模板", industry_name: "制造业", description: "",
      version_id: "version-2", version_number: 2, status: "draft", version: 4,
      published_by_user_id: null, published_at: null, modules: [],
    }
    const locallySaved = { ...definitionWithTwoFields, version: 5, forms: [{ ...definitionWithTwoFields.forms[0], name: "已保存访谈" }] }
    const savedBase = { ...draft, version: 6, description: "随后修改基础说明" }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk(definitionWithTwoFields))
      .mockResolvedValueOnce(apiOk(locallySaved))
      .mockResolvedValueOnce(apiOk(savedBase))
    installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
    render(<AuthProvider><DangerConfirmProvider><TemplateEditor draft={draft} catalog={[]} onSaved={vi.fn()} onPublished={vi.fn()} onDeleted={vi.fn()} onCancel={vi.fn()} /></DangerConfirmProvider></AuthProvider>)
    const user = userEvent.setup()
    await user.click(screen.getByRole("tab", { name: "调研表" }))
    await user.clear(await screen.findByLabelText("表单 1 名称"))
    await user.type(screen.getByLabelText("表单 1 名称"), "已保存访谈")
    await user.click(screen.getByRole("button", { name: "保存调研模板" }))
    await screen.findByText("调研模板已保存")
    await user.click(screen.getByRole("tab", { name: "模块与任务" }))
    await user.type(screen.getByLabelText("模板说明"), "随后修改基础说明")

    await user.click(screen.getByRole("button", { name: "保存草稿" }))

    expect(await screen.findByText("草稿已保存")).toBeVisible()
    expect(apiRequest).toHaveBeenCalledTimes(3)
    expect(apiRequest).toHaveBeenNthCalledWith(3,
      "/api/v1/industry-templates/versions/version-2",
      expect.objectContaining({ method: "PATCH", body: expect.objectContaining({ version: 5 }) }),
    )
  })

  it("maps publish-time research validation paths even when the research tab was not opened", async () => {
    const draft: TemplateVersionDto = {
      template_id: "template-1",
      template_name: "制造业模板",
      industry_name: "制造业",
      description: "",
      version_id: "version-2",
      version_number: 2,
      status: "draft",
      version: 4,
      published_by_user_id: null,
      published_at: null,
      modules: [],
    }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk({ ...definitionWithTwoFields, version: 4 }))
      .mockResolvedValueOnce(apiOk({ ...draft, version: 5 }))
      .mockResolvedValueOnce(apiError("invalid_research_definition", 400, {
        issues: [{ code: "unknown_condition_field", path: "forms[0].sections[0].fields[1].condition.field_key" }],
        stack: "SECRET STACK",
      }))
    installBridge(bridge({
      refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
      apiRequest,
    }))
    render(<AuthProvider><DangerConfirmProvider><TemplateEditor
      draft={draft}
      catalog={[]}
      onSaved={vi.fn()}
      onPublished={vi.fn()}
      onDeleted={vi.fn()}
      onCancel={vi.fn()}
    /></DangerConfirmProvider></AuthProvider>)
    const user = userEvent.setup()

    await user.click(screen.getByRole("button", { name: "发布 v2" }))

    const publishActions = screen.getByTestId("publish-actions")
    const alert = await within(publishActions).findByRole("alert")
    expect(alert).toHaveTextContent("第 1 个表单 > 第 1 个章节 > 第 2 个字段 > 显示条件 > 引用字段")
    expect(alert).not.toHaveTextContent("SECRET STACK")
    expect(alert).not.toHaveTextContent("raw-invalid_research_definition-server-message")
  })

  it("does not overwrite research or patch the template while the opened research tab is still loading", async () => {
    const draft: TemplateVersionDto = {
      template_id: "template-1", template_name: "制造业模板", industry_name: "制造业", description: "",
      version_id: "version-2", version_number: 2, status: "draft", version: 4,
      published_by_user_id: null, published_at: null, modules: [],
    }
    const pending = deferred<BridgeResult<ApiResponse<typeof definitionWithTwoFields>>>()
    const apiRequest = vi.fn().mockReturnValueOnce(pending.promise)
    installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
    render(<AuthProvider><DangerConfirmProvider><TemplateEditor draft={draft} catalog={[]} onSaved={vi.fn()} onPublished={vi.fn()} onDeleted={vi.fn()} onCancel={vi.fn()} /></DangerConfirmProvider></AuthProvider>)
    const user = userEvent.setup()
    await user.click(screen.getByRole("tab", { name: "调研表" }))
    await screen.findByText("正在加载调研模板…")

    await user.click(screen.getByRole("button", { name: "发布 v2" }))

    expect(await within(screen.getByTestId("publish-actions")).findByRole("alert")).toHaveTextContent("调研模板仍在加载")
    expect(apiRequest).toHaveBeenCalledTimes(1)
    pending.resolve(apiOk(definitionWithTwoFields))
    await screen.findByLabelText("表单 1 名称")
  })

  it("propagates a standalone research save version back to the template history state", async () => {
    const draft: TemplateVersionDto = {
      template_id: "template-1", template_name: "制造业模板", industry_name: "制造业", description: "",
      version_id: "version-2", version_number: 2, status: "draft", version: 4,
      published_by_user_id: null, published_at: null, modules: [],
    }
    const apiRequest = vi.fn()
      .mockResolvedValueOnce(apiOk(definitionWithTwoFields))
      .mockResolvedValueOnce(apiOk({ ...definitionWithTwoFields, version: 5 }))
    const onSaved = vi.fn()
    installBridge(bridge({ refresh: vi.fn().mockResolvedValue(ok(authResult(adminUser))), apiRequest }))
    render(<AuthProvider><DangerConfirmProvider><TemplateEditor draft={draft} catalog={[]} onSaved={onSaved} onPublished={vi.fn()} onDeleted={vi.fn()} onCancel={vi.fn()} /></DangerConfirmProvider></AuthProvider>)
    const user = userEvent.setup()
    await user.click(screen.getByRole("tab", { name: "调研表" }))
    await user.type(await screen.findByLabelText("表单 1 名称"), "更新")

    await user.click(screen.getByRole("button", { name: "保存调研模板" }))

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ version_id: "version-2", version: 5 })))
  })

  it("exports the current definition as a JSON file download named after the first form key", async () => {
    const apiRequest = vi.fn().mockResolvedValueOnce(apiOk(definitionWithTwoFields))
    renderEditor(apiRequest)
    await screen.findByLabelText("表单 1 名称")

    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:mock-url")
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined)
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined)
    const user = userEvent.setup()

    await user.click(screen.getByRole("button", { name: "导出 JSON" }))

    expect(createObjectURL).toHaveBeenCalledTimes(1)
    const blob = createObjectURL.mock.calls[0][0] as Blob
    expect(blob).toBeInstanceOf(Blob)
    const text = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result))
      reader.onerror = () => reject(reader.error)
      reader.readAsText(blob)
    })
    const payload = JSON.parse(text)
    expect(payload.forms).toHaveLength(1)
    expect(payload.forms[0].form_key).toBe("role_interview")
    expect(payload.forms[0].sections[0].fields[0]).toEqual(expect.objectContaining({
      field_key: "goal",
      name: "目标",
      type: "short_text",
      is_required: false,
    }))
    const anchor = clickSpy.mock.instances[0] as unknown as HTMLAnchorElement
    expect(anchor.download).toBe("role_interview.json")
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url"))
  })

  it("imports a JSON definition and replaces the current editor state with regenerated client ids", async () => {
    const imported = {
      forms: [{
        form_key: "imported_survey",
        name: "导入的调研表",
        description: "说明",
        subject_type: "department",
        module_key: null,
        sections: [{
          section_key: "basic",
          name: "基本信息",
          description: "",
          fields: [{ field_key: "goal", name: "目标", help_text: "", type: "short_text", is_required: true, options: {} }],
        }],
      }],
    }
    const apiRequest = vi.fn().mockResolvedValueOnce(apiOk(emptyDefinition))
    renderEditor(apiRequest)
    await screen.findByText("暂无调研表")
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true)
    const file = new File([JSON.stringify(imported)], "import.json", { type: "application/json" })

    fireEvent.change(screen.getByLabelText("导入调研定义 JSON 文件"), { target: { files: [file] } })

    expect(await screen.findByLabelText("表单 1 名称")).toHaveValue("导入的调研表")
    expect(screen.getByLabelText("表单 1 稳定标识")).toHaveValue("imported_survey")
    expect(screen.getByLabelText("表单 1 稳定标识")).toBeEnabled()
    expect(screen.getByLabelText("表单 1 章节 1 标题")).toHaveValue("基本信息")
    expect(screen.getByLabelText("表单 1 章节 1 字段 1 标签")).toHaveValue("目标")
    expect(screen.getByText("已导入调研定义，请核对后再保存。")).toBeVisible()
    expect(confirm).toHaveBeenCalledTimes(1)
  })

  it("rejects an invalid import JSON with an error banner and does not mutate state", async () => {
    const apiRequest = vi.fn().mockResolvedValueOnce(apiOk(definitionWithTwoFields))
    renderEditor(apiRequest)
    await screen.findByLabelText("表单 1 名称")
    const confirm = vi.spyOn(window, "confirm")
    const file = new File([JSON.stringify({ hello: "world" })], "bad.json", { type: "application/json" })

    fireEvent.change(screen.getByLabelText("导入调研定义 JSON 文件"), { target: { files: [file] } })

    expect(await screen.findByRole("alert")).toHaveTextContent("不是有效的调研定义")
    expect(screen.getByLabelText("表单 1 名称")).toHaveValue("岗位访谈")
    expect(confirm).not.toHaveBeenCalled()
  })

  it("keeps the existing definition when the import confirm is cancelled", async () => {
    const apiRequest = vi.fn().mockResolvedValueOnce(apiOk(definitionWithTwoFields))
    renderEditor(apiRequest)
    await screen.findByLabelText("表单 1 名称")
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
    const file = new File([JSON.stringify({
      forms: [{
        form_key: "cancelled_form", name: "取消的调研表", description: "", subject_type: "role", module_key: null,
        sections: [],
      }],
    })], "cancel.json", { type: "application/json" })

    fireEvent.change(screen.getByLabelText("导入调研定义 JSON 文件"), { target: { files: [file] } })

    await waitFor(() => expect(confirm).toHaveBeenCalled())
    expect(screen.getByLabelText("表单 1 名称")).toHaveValue("岗位访谈")
    expect(screen.queryByText("已导入调研定义，请核对后再保存。")).not.toBeInTheDocument()
  })
})
