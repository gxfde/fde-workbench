import { describe, expect, it } from "vitest"

import { isResearchDefinitionDto } from "../../src/renderer/src/research/runtimeValidation"
import { normalizeDecimalValue } from "../../src/renderer/src/research/conditionValueContract"

function fullDefinition(): unknown {
  return {
    version: 3,
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
            name: "工作现状",
            description: "",
            sort_order: 10,
            fields: [
              field("short", "short_text", {
                placeholder: "请输入",
                default_value: "",
                min_length: 1,
                max_length: 80,
              }),
              field("long", "long_text", { placeholder: "请描述" }),
              field("rich", "rich_text", { default_value: "<p>初始值</p>" }),
              field("count", "integer", { minimum: 0, maximum: 100, default_value: 1 }),
              field("ratio", "decimal", { minimum: 0.5, maximum: 99.5, default_value: 1.5 }),
              field("day", "date", { minimum: "2026-01-01", maximum: "2026-12-31", default_value: "2026-08-24" }),
              field("state", "single_choice", { choices: ["是", "否"], default_value: "是" }),
              field("tags", "multi_choice", { choices: ["A", "B"], default_value: ["A"] }),
              field("lines", "table", {
                columns: [
                  { key: "title", name: "名称", type: "short_text", options: { max_length: 40 } },
                  { key: "status", name: "状态", type: "single_choice", options: { choices: ["新建", "完成"] } },
                ],
              }),
              {
                ...field("files", "file_reference", { max_files: 3 }),
                condition: {
                  operator: "all",
                  conditions: [
                    { field_key: "state", operator: "equals", value: "是" },
                    {
                      operator: "any",
                      conditions: [
                        { field_key: "tags", operator: "contains", value: "A" },
                        { field_key: "long", operator: "is_empty" },
                      ],
                    },
                  ],
                },
              },
            ],
          },
        ],
      },
    ],
  }
}

function field(fieldKey: string, type: string, options: unknown) {
  return {
    id: `field-${fieldKey}`,
    field_key: fieldKey,
    name: fieldKey,
    help_text: "",
    type,
    is_required: false,
    options,
    sort_order: 10,
  }
}

function clonedDefinition(): Record<string, any> {
  return structuredClone(fullDefinition()) as Record<string, any>
}

describe("research definition runtime contract", () => {
  it("accepts the closed recursive DTO for all ten field types", () => {
    expect(isResearchDefinitionDto(fullDefinition())).toBe(true)
  })

  it.each([true, 0, -1, 1.5, "1", null])("rejects non-positive-integer version %j", (version) => {
    const definition = clonedDefinition()
    definition.version = version
    expect(isResearchDefinitionDto(definition)).toBe(false)
  })

  it("rejects an unknown research field type", () => {
    const definition = clonedDefinition()
    definition.forms[0].sections[0].fields[0].type = "javascript"
    expect(isResearchDefinitionDto(definition)).toBe(false)
  })

  it.each([
    ["definition", (value: any) => { value.script = "alert(1)" }],
    ["form", (value: any) => { value.forms[0].unknown = true }],
    ["section", (value: any) => { value.forms[0].sections[0].unknown = true }],
    ["field", (value: any) => { value.forms[0].sections[0].fields[0].unknown = true }],
    ["options", (value: any) => { value.forms[0].sections[0].fields[0].options.script = "x" }],
    ["condition", (value: any) => { value.forms[0].sections[0].fields[9].condition.script = "x" }],
    ["table column", (value: any) => { value.forms[0].sections[0].fields[8].options.columns[0].script = "x" }],
    ["table column options", (value: any) => { value.forms[0].sections[0].fields[8].options.columns[0].options.script = "x" }],
  ])("rejects unknown keys in the %s schema", (_name, mutate) => {
    const definition = clonedDefinition()
    mutate(definition)
    expect(isResearchDefinitionDto(definition)).toBe(false)
  })

  it("requires exact subject, nullable module key, boolean required, integer sorting, and array shapes", () => {
    const mutations = [
      (value: any) => { value.forms[0].subject_type = "customer" },
      (value: any) => { value.forms[0].module_key = 7 },
      (value: any) => { delete value.forms[0].module_key },
      (value: any) => { value.forms[0].sections[0].fields[0].is_required = 1 },
      (value: any) => { value.forms[0].sort_order = 1.5 },
      (value: any) => { value.forms = {} },
      (value: any) => { value.forms[0].sections = {} },
      (value: any) => { value.forms[0].sections[0].fields = {} },
    ]
    for (const mutate of mutations) {
      const definition = clonedDefinition()
      mutate(definition)
      expect(isResearchDefinitionDto(definition)).toBe(false)
    }
  })

  it("rejects malformed choice defaults, table columns, nested conditions, and operators", () => {
    const mutations = [
      (value: any) => { value.forms[0].sections[0].fields[6].options.choices = "是,否" },
      (value: any) => { value.forms[0].sections[0].fields[7].options.default_value = "A" },
      (value: any) => { value.forms[0].sections[0].fields[8].options.columns = {} },
      (value: any) => { value.forms[0].sections[0].fields[8].options.columns[0].type = "table" },
      (value: any) => { value.forms[0].sections[0].fields[9].condition.conditions = {} },
      (value: any) => { value.forms[0].sections[0].fields[9].condition.conditions[0].operator = "execute" },
      (value: any) => { value.forms[0].sections[0].fields[9].condition.conditions = [] },
    ]
    for (const mutate of mutations) {
      const definition = clonedDefinition()
      mutate(definition)
      expect(isResearchDefinitionDto(definition)).toBe(false)
    }
  })

  it("rejects blank or duplicate choices and defaults outside the declared choices", () => {
    const mutations = [
      (value: any) => { value.forms[0].sections[0].fields[6].options.choices = ["是", "是"] },
      (value: any) => { value.forms[0].sections[0].fields[6].options.choices = ["是", ""] },
      (value: any) => { value.forms[0].sections[0].fields[6].options.default_value = "未声明" },
      (value: any) => { value.forms[0].sections[0].fields[7].options.default_value = ["A", "未声明"] },
      (value: any) => { value.forms[0].sections[0].fields[8].options.columns[1].options.choices = ["完成", "完成"] },
    ]
    for (const mutate of mutations) {
      const definition = clonedDefinition()
      mutate(definition)
      expect(isResearchDefinitionDto(definition)).toBe(false)
    }
  })

  it("rejects blank identities and malformed stable keys at every recursive level", () => {
    const mutations = [
      (value: any) => { value.forms[0].id = "" },
      (value: any) => { value.forms[0].name = "  " },
      (value: any) => { value.forms[0].form_key = "Role-Interview" },
      (value: any) => { value.forms[0].module_key = "Diagnosis Module" },
      (value: any) => { value.forms[0].sections[0].section_key = "1_context" },
      (value: any) => { value.forms[0].sections[0].fields[0].field_key = "short.text" },
      (value: any) => { value.forms[0].sections[0].fields[8].options.columns[0].key = "Title Column" },
      (value: any) => { value.forms[0].sections[0].fields[8].options.columns[0].name = "" },
    ]
    for (const mutate of mutations) {
      const definition = clonedDefinition()
      mutate(definition)
      expect(isResearchDefinitionDto(definition)).toBe(false)
    }
  })

  it("rejects duplicate table column keys even when each key is individually valid", () => {
    const definition = clonedDefinition()
    definition.forms[0].sections[0].fields[8].options.columns.push({
      key: "title",
      name: "重复名称",
      type: "short_text",
      options: {},
    })

    expect(isResearchDefinitionDto(definition)).toBe(false)
  })

  it("rejects boolean, negative, and reversed deterministic option ranges", () => {
    const mutations = [
      (value: any) => { value.forms[0].sections[0].fields[0].options.min_length = true },
      (value: any) => { value.forms[0].sections[0].fields[0].options.min_length = -1 },
      (value: any) => {
        value.forms[0].sections[0].fields[0].options.min_length = 10
        value.forms[0].sections[0].fields[0].options.max_length = 5
      },
      (value: any) => {
        value.forms[0].sections[0].fields[3].options.minimum = 2
        value.forms[0].sections[0].fields[3].options.maximum = 1
      },
      (value: any) => {
        value.forms[0].sections[0].fields[4].options.minimum = 2.5
        value.forms[0].sections[0].fields[4].options.maximum = 2.25
      },
      (value: any) => {
        value.forms[0].sections[0].fields[8].options.columns[0].options.min_length = 4
        value.forms[0].sections[0].fields[8].options.columns[0].options.max_length = 3
      },
    ]
    for (const mutate of mutations) {
      const definition = clonedDefinition()
      mutate(definition)
      expect(isResearchDefinitionDto(definition)).toBe(false)
    }
  })

  it("rejects integer options, table columns, and conditions outside the JSON safe range", () => {
    const mutations = [
      (value: any) => { value.forms[0].sections[0].fields[3].options.maximum = 9_007_199_254_740_992 },
      (value: any) => {
        value.forms[0].sections[0].fields[8].options.columns[0] = {
          key: "title", name: "数量", type: "integer", options: { minimum: -9_007_199_254_740_992 },
        }
      },
      (value: any) => {
        value.forms[0].sections[0].fields[1].condition = {
          field_key: "count", operator: "equals", value: 9_007_199_254_740_992,
        }
      },
    ]
    for (const mutate of mutations) {
      const definition = clonedDefinition()
      mutate(definition)
      expect(isResearchDefinitionDto(definition)).toBe(false)
    }
  })

  it("rejects condition values that are not canonical for the referenced answer type", () => {
    const mutations = [
      (value: any) => {
        value.forms[0].sections[0].fields[1].condition = {
          field_key: "ratio", operator: "equals", value: 1.25,
        }
      },
      (value: any) => {
        value.forms[0].sections[0].fields[1].condition = {
          field_key: "short", operator: "equals", value: " ready ",
        }
      },
      (value: any) => {
        value.forms[0].sections[0].fields[1].condition = {
          field_key: "short", operator: "contains", value: "",
        }
      },
    ]
    for (const mutate of mutations) {
      const definition = clonedDefinition()
      mutate(definition)
      expect(isResearchDefinitionDto(definition)).toBe(false)
    }
  })

  it("accepts a precision-preserving canonical decimal condition string", () => {
    const definition = clonedDefinition()
    definition.forms[0].sections[0].fields[1].condition = {
      field_key: "ratio",
      operator: "equals",
      value: "123456789012345678901234567890.1234567890123456789",
    }

    expect(isResearchDefinitionDto(definition)).toBe(true)
  })

  it("rejects canonical-looking decimals beyond the supported business bounds", () => {
    const values = [
      "9".repeat(101),
      `0.${"0".repeat(100)}1`,
      "1e1000000000",
    ]
    for (const value of values) {
      const definition = clonedDefinition()
      definition.forms[0].sections[0].fields[1].condition = {
        field_key: "ratio", operator: "equals", value,
      }
      expect(isResearchDefinitionDto(definition)).toBe(false)
    }
  })

  it.each(["0e1000000000", "0e-1000000000"])(
    "does not normalize an extreme zero exponent into an apparently safe value: %s",
    (value) => {
      expect(normalizeDecimalValue(value)).toBeNull()
    },
  )

  it.each(["1_0", "١.٢", "\u00851\u0085"])(
    "rejects decimal characters outside the shared ASCII literal grammar: %s",
    (value) => {
      expect(normalizeDecimalValue(value)).toBeNull()
    },
  )

  it.each(["\ufeffready\ufeff", "\u0085ready\u0085"])(
    "accepts non-ASCII text edge content in a server snapshot: %s",
    (value) => {
      const definition = clonedDefinition()
      definition.forms[0].sections[0].fields[1].condition = {
        field_key: "short", operator: "equals", value,
      }

      expect(isResearchDefinitionDto(definition)).toBe(true)
    },
  )

  it.each([
    ["self", (value: any) => {
      value.forms[0].sections[0].fields[0].condition = {
        field_key: "short", operator: "equals", value: "ready",
      }
    }],
    ["two-node", (value: any) => {
      value.forms[0].sections[0].fields[0].condition = {
        field_key: "long", operator: "equals", value: "ready",
      }
      value.forms[0].sections[0].fields[1].condition = {
        field_key: "short", operator: "equals", value: "ready",
      }
    }],
    ["nested group", (value: any) => {
      value.forms[0].sections[0].fields[0].condition = {
        operator: "all",
        conditions: [{
          operator: "any",
          conditions: [{ field_key: "short", operator: "equals", value: "ready" }],
        }],
      }
    }],
  ])("rejects a %s conditional dependency cycle", (_name, mutate) => {
    const definition = clonedDefinition()
    mutate(definition)

    expect(isResearchDefinitionDto(definition)).toBe(false)
  })
})
