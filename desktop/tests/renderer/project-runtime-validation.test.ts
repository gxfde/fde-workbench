import { describe, expect, it } from "vitest"

import {
  isProjectResearchFormDto,
  isResearchImportResultDto,
  parseResearchImportErrorDetails,
} from "../../src/renderer/src/research/projectRuntimeValidation"

function validForm(): Record<string, unknown> {
  const fields = [
    { id: "field-count", field_key: "count", name: "Count", help_text: "", type: "integer", is_required: true, options: { minimum: 0 }, sort_order: 0 },
    { id: "field-rich", field_key: "rich", name: "Rich", help_text: "", type: "rich_text", is_required: false, options: {}, sort_order: 1 },
    { id: "field-choice", field_key: "choice", name: "Choice", help_text: "", type: "single_choice", is_required: false, options: { choices: ["A", "B"] }, sort_order: 2 },
    { id: "field-table", field_key: "table", name: "Table", help_text: "", type: "table", is_required: false, options: { columns: [
      { key: "quantity", name: "Quantity", type: "integer", options: {} },
      { key: "kind", name: "Kind", type: "single_choice", options: { choices: ["A", "B"] } },
    ] }, sort_order: 3 },
    { id: "field-files", field_key: "files", name: "Files", help_text: "", type: "file_reference", is_required: false, options: { max_files: 2 }, sort_order: 4 },
  ]
  return {
    id: "form-1",
    project_id: "project-1",
    subject_id: "subject-1",
    form_key: "runtime",
    name: "Runtime",
    description: "",
    version: 1,
    current_revision: {
      id: "revision-1",
      revision_number: 1,
      parent_revision_id: null,
      status: "draft",
      version: 1,
      returned_by_user_id: null,
      returned_at: null,
      return_comment: null,
      answers: [
        { field_key: "count", value: 3 },
        { field_key: "rich", value: { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "safe" }] }] } },
        { field_key: "choice", value: "A" },
        { field_key: "table", value: [{ quantity: 2, kind: "B" }] },
        { field_key: "files", value: ["file-1"] },
      ],
    },
    completion: {
      visible_total: 5,
      answered_visible: 5,
      required_total: 1,
      required_answered: 1,
      missing_required_count: 0,
      completion_rate: 100,
      visible_required_field_keys: ["count"],
      missing_required_field_keys: [],
      answered_visible_field_count: 5,
    },
    definition_snapshot: {
      id: "definition-1",
      form_key: "runtime",
      name: "Runtime",
      description: "",
      subject_type: "department",
      module_key: null,
      sort_order: 0,
      sections: [{ id: "section-1", section_key: "main", name: "Main", description: "", sort_order: 0, fields }],
    },
  }
}

function mutateAnswer(fieldKey: string, value: unknown): Record<string, unknown> {
  const form = structuredClone(validForm())
  const revision = form.current_revision as { answers: Array<{ field_key: string; value: unknown }> }
  const answer = revision.answers.find((item) => item.field_key === fieldKey)!
  answer.value = value
  return form
}

describe("project research response guards", () => {
  it("accepts the real serializer shape when every answer matches its definition", () => {
    expect(isProjectResearchFormDto(validForm())).toBe(true)
  })

  it.each([
    ["wrong integer", () => mutateAnswer("count", "3")],
    ["wrong rich text", () => mutateAnswer("rich", { type: "doc", content: [{ type: "script", content: [] }] })],
    ["wrong table columns", () => mutateAnswer("table", [{ quantity: 2 }])],
    ["wrong table choice", () => mutateAnswer("table", [{ quantity: 2, kind: "C" }])],
    ["wrong file references", () => mutateAnswer("files", ["../secret", "file-1", "file-2"])],
  ])("rejects definition-incompatible answers: %s", (_name, build) => {
    expect(isProjectResearchFormDto(build())).toBe(false)
  })

  it("rejects unknown and duplicate answer field keys", () => {
    const unknown = structuredClone(validForm())
    const unknownRevision = unknown.current_revision as { answers: Array<{ field_key: string; value: unknown }> }
    unknownRevision.answers.push({ field_key: "unknown", value: "leak" })
    const duplicate = structuredClone(validForm())
    const duplicateRevision = duplicate.current_revision as { answers: Array<{ field_key: string; value: unknown }> }
    duplicateRevision.answers.push({ field_key: "count", value: 4 })

    expect(isProjectResearchFormDto(unknown)).toBe(false)
    expect(isProjectResearchFormDto(duplicate)).toBe(false)
  })

  it("rejects duplicate table definition columns before trusting row answers", () => {
    const form = structuredClone(validForm())
    const definition = form.definition_snapshot as { sections: Array<{ fields: Array<{ field_key: string; options: { columns?: Array<Record<string, unknown>> } }> }> }
    const table = definition.sections[0].fields.find((field) => field.field_key === "table")!
    table.options.columns!.push({ key: "quantity", name: "Duplicate", type: "integer", options: {} })

    expect(isProjectResearchFormDto(form)).toBe(false)
  })

  it("requires imported_count to equal the serialized subject count", () => {
    expect(isResearchImportResultDto({
      subjects: [],
      imported_count: 2,
      project_version: 3,
      idempotent_replay: true,
    })).toBe(false)
  })

  it("counts Unicode code points when enforcing text answer lengths", () => {
    const form = structuredClone(validForm())
    const definition = form.definition_snapshot as { sections: Array<{ fields: Array<Record<string, unknown>> }> }
    definition.sections[0].fields.push({
      id: "field-label",
      field_key: "label",
      name: "Label",
      help_text: "",
      type: "short_text",
      is_required: false,
      options: { max_length: 1 },
      sort_order: 5,
    })
    const revision = form.current_revision as { answers: Array<{ field_key: string; value: unknown }> }
    revision.answers.push({ field_key: "label", value: "😀" })

    expect(isProjectResearchFormDto(form)).toBe(true)
  })

  it("rejects integers outside the shared JSON safe range", () => {
    expect(isProjectResearchFormDto(mutateAnswer("count", 9_007_199_254_740_991))).toBe(true)
    expect(isProjectResearchFormDto(mutateAnswer("count", 9_007_199_254_740_992))).toBe(false)
  })

  it("accepts only exact structured import error details", () => {
    expect(parseResearchImportErrorDetails({ errors: [
      { row: 3, column: "父级", code: "parent_not_found", message: "raw" },
    ] })).toEqual([{ row: 3, column: "父级", code: "parent_not_found", message: "raw" }])
    expect(parseResearchImportErrorDetails({ errors: [{ row: 0, column: "父级", code: "bad", message: "raw" }] })).toBeNull()
    expect(parseResearchImportErrorDetails({ errors: [{ row: 3, column: 7, code: "bad", message: "raw" }] })).toBeNull()
    expect(parseResearchImportErrorDetails({ errors: [], leaked: "raw" })).toBeNull()
  })
})
