// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { App } from "../../src/renderer/src/App"
import { ResearchField } from "../../src/renderer/src/research/ResearchField"
import { ResearchForm, visibleResearchFieldKeys } from "../../src/renderer/src/research/ResearchForm"
import { ResearchSubjectTree } from "../../src/renderer/src/research/ResearchSubjectTree"
import type {
  ProjectResearchFormDto,
  ResearchAnswerValue,
  ResearchSubjectDto,
} from "../../src/renderer/src/research/types"
import { parseHashRoute } from "../../src/renderer/src/routing/useHashRoute"
import type { ApiResponse, BridgeResult, UserDto } from "../../src/shared/contracts"
import type { ProjectDto } from "../../src/renderer/src/workbench/types"
import { adminUser, authResult, bridge, engineerUser, installBridge, ok, renderApp } from "./test-utils"

const projectId = "project-research"

const project: ProjectDto = {
  id: projectId,
  project_code: "RES-001",
  name: "星河调研项目",
  enterprise_name: "星河制造",
  contact_name: "陈总",
  contact_phone: "13800000000",
  address: "深圳市",
  background: "制造业 AI 调研",
  notes: "",
  status: "active",
  planned_start_date: "2026-08-22",
  planned_end_date: "2026-09-22",
  leader_user_id: adminUser.id,
  leader: { id: adminUser.id, display_name: "管理员", role: "admin" },
  template_version_id: "template-version-1",
  industry: "制造业",
  completion: 0,
  version: 5,
  created_at: "2026-08-22T00:00:00+00:00",
  updated_at: "2026-08-22T00:00:00+00:00",
  modules: [],
  tasks: [],
  members: [
    {
      id: "member-engineer",
      user_id: engineerUser.id,
      display_name: engineerUser.displayName,
      system_role: "fde_engineer",
      role: "member",
    },
  ],
  template_snapshot: {
    template_id: "template-1",
    template_name: "制造业模板",
    industry_name: "制造业",
    description: "",
    version_id: "template-version-1",
    version_number: 1,
    modules: [],
  },
}

const rootSubject: ResearchSubjectDto = {
  id: "subject-root",
  project_id: projectId,
  parent_subject_id: null,
  subject_type: "project",
  subject_key: "project_root",
  name: "星河调研项目",
  description: "",
  sort_order: 0,
  status: "active",
  tracking_code: null,
  version: 1,
  links: [],
}

const departmentSubject: ResearchSubjectDto = {
  id: "subject-sales",
  project_id: projectId,
  parent_subject_id: rootSubject.id,
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

const otherDepartment: ResearchSubjectDto = {
  ...departmentSubject,
  id: "subject-delivery",
  subject_key: "department_delivery",
  name: "交付部",
}

const roleSubject: ResearchSubjectDto = {
  ...departmentSubject,
  id: "subject-role-sales",
  parent_subject_id: departmentSubject.id,
  subject_type: "role",
  subject_key: "role_sales",
  name: "销售专员",
  tracking_code: "JOB-0001",
}

const opportunitySubject: ResearchSubjectDto = {
  ...departmentSubject,
  id: "subject-opportunity-copilot",
  parent_subject_id: departmentSubject.id,
  subject_type: "opportunity",
  subject_key: "opportunity_copilot",
  name: "智能排产助手",
  tracking_code: "OPP-0001",
  opportunity_profile: {
    target_audience: "排产员与生产主管",
    owner_user_id: adminUser.id,
    owner_display_name: "管理员",
    opportunity_status: "ready",
    priority: "high",
    business_value_score: 5,
    feasibility_score: 4,
    data_readiness_score: 3,
    risk_level: "medium",
    next_action: "创建 PoV 验证方案",
  },
}

const opportunityDefinition = {
  id: "form-definition-opportunity",
  form_key: "ai_opportunity_definition",
  name: "AI 机会调研",
  description: "从发现到交付说明，完整定义并推动一项 AI 机会落地。",
  subject_type: "opportunity" as const,
  module_key: null,
  sort_order: 0,
  sections: [
    {
      id: "section-discovery",
      section_key: "discovery",
      name: "发现",
      description: "描述机会的现状、痛点与业务价值。",
      sort_order: 0,
      fields: [
        { id: "field-current-state", field_key: "current_state", name: "现状描述", help_text: "", type: "long_text" as const, is_required: false, options: {}, sort_order: 0 },
        { id: "field-pain-points", field_key: "pain_points", name: "痛点/问题", help_text: "", type: "long_text" as const, is_required: true, options: {}, sort_order: 1 },
        { id: "field-business-value", field_key: "business_value", name: "业务价值", help_text: "", type: "long_text" as const, is_required: true, options: {}, sort_order: 2 },
      ],
    },
    {
      id: "section-delivery",
      section_key: "delivery",
      name: "交付说明",
      description: "明确交付范围、产物与验收标准。",
      sort_order: 1,
      fields: [
        { id: "field-delivery-scope", field_key: "delivery_scope", name: "交付范围", help_text: "", type: "long_text" as const, is_required: true, options: {}, sort_order: 0 },
        { id: "field-deliverables", field_key: "deliverables", name: "交付物", help_text: "", type: "long_text" as const, is_required: false, options: {}, sort_order: 1 },
      ],
    },
  ],
}

function opportunityFormFor(overrides: Partial<ProjectResearchFormDto> = {}): ProjectResearchFormDto {
  return {
    id: "form-opportunity-copilot",
    project_id: projectId,
    subject_id: opportunitySubject.id,
    form_key: opportunityDefinition.form_key,
    name: opportunityDefinition.name,
    description: opportunityDefinition.description,
    version: 1,
    current_revision: {
      id: "revision-opportunity-1",
      revision_number: 1,
      parent_revision_id: null,
      status: "draft",
      version: 1,
      returned_by_user_id: null,
      returned_at: null,
      return_comment: null,
      answers: [],
    },
    completion: {
      visible_total: 5,
      answered_visible: 0,
      required_total: 3,
      required_answered: 0,
      missing_required_count: 3,
      completion_rate: 0,
      visible_required_field_keys: ["pain_points", "business_value", "delivery_scope"],
      missing_required_field_keys: ["pain_points", "business_value", "delivery_scope"],
      answered_visible_field_count: 0,
    },
    definition_snapshot: opportunityDefinition,
    ...overrides,
  }
}

const definition = {
  id: "form-definition-department",
  form_key: "department_basics",
  name: "部门基础调研",
  description: "填写部门目标与现状",
  subject_type: "department" as const,
  module_key: null,
  sort_order: 0,
  sections: [
    {
      id: "section-basics",
      section_key: "basics",
      name: "基础信息",
      description: "",
      sort_order: 0,
      fields: [
        {
          id: "field-goal",
          field_key: "goal",
          name: "核心目标",
          help_text: "请描述期望改善的业务结果",
          type: "short_text" as const,
          is_required: true,
          options: { max_length: 200 },
          sort_order: 0,
        },
      ],
    },
  ],
}

function formFor(
  subjectId: string,
  overrides: Partial<ProjectResearchFormDto> = {},
): ProjectResearchFormDto {
  return {
    id: `form-${subjectId}`,
    project_id: projectId,
    subject_id: subjectId,
    form_key: definition.form_key,
    name: definition.name,
    description: definition.description,
    version: 1,
    current_revision: {
      id: `revision-${subjectId}-1`,
      revision_number: 1,
      parent_revision_id: null,
      status: "draft",
      version: 1,
      returned_by_user_id: null,
      returned_at: null,
      return_comment: null,
      answers: [],
    },
    completion: {
      visible_total: 1,
      answered_visible: 0,
      required_total: 1,
      required_answered: 0,
      missing_required_count: 1,
      completion_rate: 0,
      visible_required_field_keys: ["goal"],
      missing_required_field_keys: ["goal"],
      answered_visible_field_count: 0,
    },
    definition_snapshot: definition,
    ...overrides,
  }
}

type ApiResult = BridgeResult<ApiResponse<unknown>>

function apiOk(data: unknown, status = 200): ApiResult {
  return ok({ status, data, error: null })
}

function apiError(code: string, status: number, details?: unknown, message = "raw backend detail must not render"): ApiResult {
  return ok({ status, data: null, error: { code, message, details } })
}

interface RenderResearchOptions {
  user?: UserDto
  initialSubjects?: ResearchSubjectDto[]
  initialForms?: ProjectResearchFormDto[]
  patchError?: { code: string; status?: number }
  opportunityPatchError?: { code: string; status?: number }
  documentCreateError?: { code: string; status?: number }
  malformedForms?: boolean
  patchErrorOnce?: boolean
  createStaleOnce?: boolean
  projectVersionAfterStale?: number
  initialPersonalMemos?: Array<{ subject_id: string; user_id: string; memo: string; version?: number }>
}

function renderProjectResearch(options: RenderResearchOptions = {}) {
  const currentUser = options.user ?? adminUser
  let currentProject = {
    ...project,
    leader_user_id: currentUser.role === "project_lead" ? currentUser.id : project.leader_user_id,
    leader: currentUser.role === "project_lead"
      ? { id: currentUser.id, display_name: currentUser.displayName, role: currentUser.role }
      : project.leader,
  }
  let subjects = [...(options.initialSubjects ?? [rootSubject])]
  const memos = new Map<string, string>()
  const personalMemos = new Map(
    (options.initialPersonalMemos ?? []).map((item) => [
      `${item.subject_id}:${item.user_id}`,
      { memo: item.memo, version: item.version ?? 1 },
    ]),
  )
  let forms = [...(options.initialForms ?? [])]
  let patchAttempts = 0
  let createAttempts = 0
  const apiRequest = vi.fn(async (path: string, request: { method: string; body?: unknown }): Promise<ApiResult> => {
    if (path === `/api/v1/projects/${projectId}` && request.method === "GET") return apiOk(currentProject)
    if (path.endsWith("/research/subjects") && request.method === "GET") return apiOk({ items: subjects })
    if (/\/research\/subjects\/[^/]+\/memo$/.test(path) && request.method === "GET") {
      const id = path.split("/").at(-2)!
      const current = subjects.find((subject) => subject.id === id)!
      return apiOk({ memo: memos.get(id) ?? "", version: current.version })
    }
    if (/\/research\/subjects\/[^/]+\/memo$/.test(path) && request.method === "PATCH") {
      const id = path.split("/").at(-2)!
      const body = request.body as { version: number; memo: string }
      const current = subjects.find((subject) => subject.id === id)!
      if (body.version !== current.version) return apiError("stale_version", 409)
      const version = current.version + 1
      memos.set(id, body.memo)
      subjects = subjects.map((subject) => subject.id === id ? { ...subject, version } : subject)
      return apiOk({ memo: body.memo, version })
    }
    if (/\/research\/subjects\/[^/]+\/personal-memos$/.test(path) && request.method === "GET") {
      const subjectId = path.split("/").at(-2)!
      const people = [
        { user_id: currentProject.leader.id, display_name: currentProject.leader.display_name },
        ...currentProject.members.map((member) => ({ user_id: member.user_id, display_name: member.display_name })),
        { user_id: currentUser.id, display_name: currentUser.displayName },
      ].filter((person, index, all) => all.findIndex((candidate) => candidate.user_id === person.user_id) === index)
      return apiOk({ items: people.map((person) => {
        const saved = personalMemos.get(`${subjectId}:${person.user_id}`)
        return {
          ...person,
          memo: saved?.memo ?? "",
          version: saved?.version ?? 0,
          is_current_user: person.user_id === currentUser.id,
        }
      }) })
    }
    if (/\/research\/subjects\/[^/]+\/personal-memo$/.test(path) && request.method === "PATCH") {
      const subjectId = path.split("/").at(-2)!
      const body = request.body as { version: number; memo: string }
      const key = `${subjectId}:${currentUser.id}`
      const saved = personalMemos.get(key)
      if (body.version !== (saved?.version ?? 0)) return apiError("stale_version", 409)
      const version = (saved?.version ?? 0) + 1
      personalMemos.set(key, { memo: body.memo, version })
      return apiOk({
        user_id: currentUser.id,
        display_name: currentUser.displayName,
        memo: body.memo,
        version,
        is_current_user: true,
      })
    }
    if (path.endsWith("/research/forms") && request.method === "GET") {
      return apiOk(options.malformedForms ? { items: [{ leaked: "server internals" }] } : { items: forms })
    }
    if (path === "/api/v1/ai/executions" && request.method === "POST" && (request.body as { operation: string }).operation === "project_research_form_generate") {
      const body = request.body as { operation: string; payload: { subject_id: string } }
      const subject = subjects.find((item) => item.id === body.payload.subject_id)!
      return apiOk({ id: "execution-form-generate", operation: body.operation, status: "completed", stage: "正在校验并整理结果", error: null, events: [], next_offset: 0, created_at: "2026-09-04T00:00:00+00:00", updated_at: "2026-09-04T00:00:01+00:00", result: {
        form_key: `${subject.subject_key}_ai_interview`,
        name: `${subject.name} AI 调研`,
        description: "AI 生成，请核对后创建。",
        subject_type: subject.subject_type,
        module_key: null,
        sections: [{
          section_key: "business_context",
          name: "业务现状",
          description: "",
          fields: [{ field_key: "current_process", name: "当前流程", help_text: "请描述当前流程。", type: "long_text", is_required: true, options: {} }],
        }],
      } }, 202)
    }
    if (/\/research\/forms\/[^/]+\/export$/.test(path) && request.method === "POST") {
      return apiOk({
        id: "research-export-1",
        project_id: projectId,
        form_id: `form-${departmentSubject.id}`,
        form_name: "部门基础调研",
        status: "queued",
        file_id: null,
        version_id: null,
        version_number: null,
        display_name: "",
        failure_code: "",
        failure_message: "",
        created_at: "2026-08-28T00:00:00+00:00",
        updated_at: "2026-08-28T00:00:00+00:00",
      }, 202)
    }
    if (path.endsWith("/research/subjects") && request.method === "POST") {
      const body = request.body as Record<string, unknown>
      createAttempts += 1
      if (options.createStaleOnce && createAttempts === 1) {
        currentProject = { ...currentProject, version: options.projectVersionAfterStale ?? currentProject.version + 2 }
        return apiError("stale_version", 409)
      }
      if (body.version !== currentProject.version) return apiError("stale_version", 409)
      const created: ResearchSubjectDto & { project_version: number } = {
        ...departmentSubject,
        id: subjects.some((subject) => subject.id === departmentSubject.id) ? `subject-${String(body.subject_key)}` : departmentSubject.id,
        subject_type: body.subject_type as ResearchSubjectDto["subject_type"],
        subject_key: body.subject_key as string,
        name: body.name as string,
        description: body.description as string,
        parent_subject_id: body.parent_subject_id as string,
        project_version: currentProject.version + 1,
      }
      subjects = [...subjects, created]
      forms = [...forms, formFor(created.id)]
      currentProject = { ...currentProject, version: created.project_version }
      return apiOk(created, 201)
    }
    if (path.includes("/research/subjects/") && request.method === "PATCH") {
      if (options.opportunityPatchError) return apiError(options.opportunityPatchError.code, options.opportunityPatchError.status ?? 400)
      const id = path.split("/").at(-1)
      const body = request.body as { version: number; name?: string; description?: string; opportunity_profile?: ResearchSubjectDto["opportunity_profile"] }
      const current = subjects.find((subject) => subject.id === id)!
      const updated = {
        ...current,
        version: current.version + 1,
        ...(body.name === undefined ? {} : { name: body.name }),
        ...(body.description === undefined ? {} : { description: body.description }),
        ...(body.opportunity_profile === undefined ? {} : { opportunity_profile: {
          ...body.opportunity_profile,
          owner_display_name: body.opportunity_profile.owner_user_id
            ? currentProject.members.find((member) => member.user_id === body.opportunity_profile?.owner_user_id)?.display_name ?? currentProject.leader.display_name
            : null,
        } }),
      }
      subjects = subjects.map((subject) => subject.id === id ? updated : subject)
      return apiOk(updated)
    }
    if (path === "/api/v1/document-templates" && request.method === "GET") {
      return apiOk({ items: [
        { document_type: "pov_plan", versions: [{ id: "template-pov", status: "published" }] },
        { document_type: "sow", versions: [{ id: "template-sow", status: "published" }] },
      ] })
    }
    if (path.endsWith("/documents") && request.method === "POST") {
      if (options.documentCreateError) return apiError(options.documentCreateError.code, options.documentCreateError.status ?? 400)
      const body = request.body as { document_type: string }
      return apiOk({ id: `document-${body.document_type}`, version: 1, business_code: body.document_type === "pov_plan" ? "POV_PLAN-1" : "SOW-1", project_version: currentProject.version + 1 }, 201)
    }
    if (/\/documents\/[^/]+\/generate$/.test(path) && request.method === "POST") {
      return apiOk({ id: "document-generation", status: "queued" }, 202)
    }
    const formIdIn = (suffix: string): string | null => {
      const match = path.match(new RegExp(`/research/forms/([^/]+)${suffix}$`))
      return match ? match[1] : null
    }
    if (formIdIn("") && request.method === "GET") return apiOk(forms.find((item) => item.id === formIdIn("")))
    if (formIdIn("") && request.method === "PATCH") {
      patchAttempts += 1
      if (options.patchErrorOnce && patchAttempts === 1) return apiError("research_form_mutation_failed", 503)
      if (options.patchError) return apiError(options.patchError.code, options.patchError.status ?? 409)
      const formId = formIdIn("")!
      const body = request.body as { version: number; answers: Record<string, ResearchAnswerValue> }
      const current = forms.find((item) => item.id === formId)
      if (!current) throw new Error(`no form ${formId}`)
      if (body.version !== current.current_revision?.version) return apiError("stale_version", 409)
      const answeredCount = Object.keys(body.answers).length
      const saved: ProjectResearchFormDto = {
        ...current,
        current_revision: {
          ...current.current_revision!,
          version: current.current_revision!.version + 1,
          ...(current.current_revision!.status === "confirmed" ? {
            id: `revision-${formId}-2`, revision_number: current.current_revision!.revision_number + 1,
            parent_revision_id: current.current_revision!.id, status: "draft" as const, version: 2,
          } : {}),
          answers: Object.entries(body.answers).map(([field_key, value]) => ({ field_key, value })),
        },
        completion: {
          ...current.completion,
          answered_visible: answeredCount,
          required_answered: answeredCount,
          missing_required_count: 0,
          completion_rate: 100,
          missing_required_field_keys: [],
          answered_visible_field_count: answeredCount,
        },
      }
      forms = forms.map((item) => item.id === saved.id ? saved : item)
      return apiOk(saved)
    }
    if (formIdIn("/confirm") && request.method === "POST") {
      const formId = formIdIn("/confirm")!
      const current = forms.find((item) => item.id === formId)
      if (!current) throw new Error(`no form ${formId}`)
      const confirmed: ProjectResearchFormDto = {
        ...current,
        current_revision: { ...current.current_revision!, status: "confirmed", version: current.current_revision!.version + 1 },
      }
      forms = forms.map((item) => item.id === confirmed.id ? confirmed : item)
      return apiOk(confirmed)
    }
    if (formIdIn("/revise") && request.method === "POST") {
      const formId = formIdIn("/revise")!
      const current = forms.find((item) => item.id === formId)!
      const revised: ProjectResearchFormDto = {
        ...current,
        version: current.version + 1,
        current_revision: {
          ...current.current_revision!,
          id: `revision-${formId}-2`,
          revision_number: 2,
          parent_revision_id: current.current_revision!.id,
          status: "draft",
          version: 1,
        },
      }
      forms = forms.map((item) => item.id === revised.id ? revised : item)
      return apiOk(revised, 201)
    }
    if (formIdIn("/reject") && request.method === "POST") {
      const formId = formIdIn("/reject")!
      const current = forms.find((item) => item.id === formId)!
      const returned: ProjectResearchFormDto = {
        ...current,
        current_revision: {
          ...current.current_revision!,
          version: current.current_revision!.version + 1,
          returned_by_user_id: currentUser.id,
          returned_at: "2026-08-24T03:00:00+00:00",
          return_comment: (request.body as { review_comment: string }).review_comment,
        },
      }
      forms = forms.map((item) => item.id === returned.id ? returned : item)
      return apiOk(returned)
    }
    if (path.endsWith("/research/forms") && request.method === "POST") {
      const body = request.body as Record<string, unknown>
      const sections = (body.sections as Array<Record<string, unknown>>).map((section, sectionIndex) => ({
        id: `section-created-${sectionIndex}`,
        section_key: section.section_key as string,
        name: section.name as string,
        description: (section.description as string) ?? "",
        sort_order: (section.sort_order as number) ?? 0,
        fields: (section.fields as Array<Record<string, unknown>>).map((field, fieldIndex) => ({
          id: `field-created-${sectionIndex}-${fieldIndex}`,
          field_key: field.field_key as string,
          name: field.name as string,
          help_text: (field.help_text as string) ?? "",
          type: field.type as ProjectResearchFormDto["definition_snapshot"]["sections"][number]["fields"][number]["type"],
          is_required: Boolean(field.is_required),
          options: (field.options as Record<string, unknown>) ?? {},
          sort_order: (field.sort_order as number) ?? 0,
        })),
      }))
      const createdDefinition = {
        id: "form-definition-created",
        form_key: body.form_key as string,
        name: body.name as string,
        description: (body.description as string) ?? "",
        subject_type: body.subject_type as ProjectResearchFormDto["definition_snapshot"]["subject_type"],
        module_key: null,
        sort_order: 0,
        sections,
      }
      const created: ProjectResearchFormDto = {
        ...formFor(body.subject_id as string, {
          id: `form-created-${forms.length + 1}`,
          form_key: body.form_key as string,
          name: body.name as string,
          description: (body.description as string) ?? "",
          definition_snapshot: createdDefinition,
        }),
      }
      forms = [...forms, created]
      return apiOk(created, 201)
    }
    if (path.includes("/research/subjects/") && request.method === "DELETE") {
      const id = path.split("/").at(-1)
      if (subjects.some((subject) => subject.parent_subject_id === id && subject.status === "active")) {
        return apiError("research_subject_has_active_children", 409)
      }
      subjects = subjects.map((subject) => subject.id === id ? { ...subject, status: "archived", version: subject.version + 1 } : subject)
      currentProject = { ...currentProject, version: currentProject.version + 1 }
      return apiOk({ ...subjects.find((subject) => subject.id === id)!, project_version: currentProject.version })
    }
    if (path === "/api/v1/ai/executions" && request.method === "POST") {
      const body = request.body as { operation: string; payload: { subject_id: string } }
      if (body.operation === "project_research_memos_merge") {
        const subject = subjects.find((item) => item.id === body.payload.subject_id)!
        const sources = [...personalMemos.entries()]
          .filter(([key, item]) => key.startsWith(`${subject.id}:`) && item.memo.trim())
          .map(([key, item]) => ({
            source: "个人备忘录",
            author: key.endsWith(engineerUser.id) ? engineerUser.displayName : currentUser.displayName,
            content: item.memo,
          }))
        return apiOk({
          id: "execution-memo-merge",
          operation: body.operation,
          status: "completed",
          stage: "正在校验并整理结果",
          result: {
            subject_id: subject.id,
            subject_version: subject.version,
            sources,
            merged_memo: "# 合并结论\n\n- 已整合个人观察",
            change_summary: ["合并重复内容", "保留待确认事项"],
          },
          error: null,
          events: [],
          next_offset: 0,
          created_at: "2026-09-04T00:00:00+00:00",
          updated_at: "2026-09-04T00:00:01+00:00",
        }, 202)
      }
    }
    if (path === "/api/v1/auth/verify-password" && request.method === "POST") {
      return apiOk({ valid: true })
    }
    throw new Error(`Unhandled test API request: ${request.method} ${path}`)
  })

  location.hash = `#projects/${projectId}?tab=research`
  installBridge(bridge({
    refresh: vi.fn().mockResolvedValue(ok(authResult(currentUser))),
    apiRequest,
  }))
  renderApp(<App />)
  return apiRequest
}

function mutationBodies(apiRequest: ReturnType<typeof vi.fn>, suffix: string, method: string): unknown[] {
  return apiRequest.mock.calls
    .filter(([path, options]) => String(path).endsWith(suffix) && options.method === method)
    .map(([, options]) => options.body)
}

async function openResearchForm(user: ReturnType<typeof userEvent.setup>, name = "部门基础调研", action = "填写"): Promise<void> {
  const heading = await screen.findByRole("heading", { name })
  const card = heading.closest("article")!
  await user.click(within(card).getByRole("button", { name: action }))
}

afterEach(() => {
  cleanup()
  location.hash = ""
  vi.restoreAllMocks()
})

describe("project research workspace", () => {
  it("routes the canonical research hash into the project research tab", () => {
    expect(parseHashRoute(`#projects/${projectId}?tab=research`)).toEqual({ kind: "project", projectId, tab: "research" })
  })

  it("supports arrow-key navigation for tabs and the research tree", async () => {
    renderProjectResearch({
      initialSubjects: [rootSubject, departmentSubject, otherDepartment],
      initialForms: [formFor(departmentSubject.id), formFor(otherDepartment.id)],
    })
    const user = userEvent.setup()

    const sales = await screen.findByRole("treeitem", { name: /\u9500\u552e\u90e8/ })
    sales.focus()
    await user.keyboard("{ArrowUp}")
    expect(screen.getByRole("treeitem", { name: /\u4ea4\u4ed8\u90e8/ })).toHaveFocus()
    expect(screen.getByRole("heading", { name: "交付部" })).toBeVisible()

    const researchTab = screen.getByRole("tab", { name: "调研" })
    researchTab.focus()
    await user.keyboard("{ArrowLeft}")
    await waitFor(() => expect(location.hash).toBe(`#projects/${projectId}?tab=tasks`))
  })

  it("collapses and restores all descendants of a research subject", async () => {
    renderProjectResearch({
      initialSubjects: [rootSubject, departmentSubject, roleSubject],
      initialForms: [formFor(departmentSubject.id)],
    })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: `展开${departmentSubject.name}的下级` }))
    expect(await screen.findByRole("treeitem", { name: /销售专员/ })).toBeVisible()
    await user.click(screen.getByRole("button", { name: `收起${departmentSubject.name}的下级` }))

    expect(screen.queryByRole("treeitem", { name: /销售专员/ })).not.toBeInTheDocument()
    const expand = screen.getByRole("button", { name: `展开${departmentSubject.name}的下级` })
    expect(expand).toHaveAttribute("aria-expanded", "false")
    await user.click(expand)

    expect(await screen.findByRole("treeitem", { name: /销售专员/ })).toBeVisible()
  })

  it("supports tree parent navigation, collapse, expand, and first-child focus", async () => {
    renderApp(<ResearchSubjectTree subjects={[rootSubject, departmentSubject, roleSubject]} selectedId={roleSubject.id} canFill={false} onSelect={vi.fn()} onCreate={vi.fn()} onArchive={vi.fn()} />)
    const user = userEvent.setup()
    const role = screen.getByRole("treeitem", { name: /销售专员/ })
    role.focus()

    await user.keyboard("{ArrowLeft}")
    const department = screen.getByRole("treeitem", { name: /销售部/ })
    expect(department).toHaveFocus()
    await user.keyboard("{ArrowLeft}")
    expect(department).toHaveAttribute("aria-expanded", "false")
    expect(screen.queryByRole("treeitem", { name: /销售专员/ })).not.toBeInTheDocument()
    await user.keyboard("{ArrowRight}")
    expect(department).toHaveAttribute("aria-expanded", "true")
    await user.keyboard("{ArrowRight}")
    expect(screen.getByRole("treeitem", { name: /销售专员/ })).toHaveFocus()
  })

  it("does not render a redundant subject-type legend above the tree", () => {
    renderApp(<ResearchSubjectTree subjects={[rootSubject, departmentSubject, roleSubject]} selectedId={rootSubject.id} canFill onSelect={vi.fn()} onCreate={vi.fn()} onRename={vi.fn()} onArchive={vi.fn()} />)

    expect(screen.queryByLabelText("对象类型")).not.toBeInTheDocument()
    expect(screen.getByRole("treeitem", { name: /星河调研项目/ })).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByRole("treeitem", { name: /销售部/ })).toBeVisible()
    expect(screen.queryByRole("treeitem", { name: /销售专员/ })).not.toBeInTheDocument()
  })

  it("creates a department and opens its form card to save answers and return to the list", async () => {
    const apiRequest = renderProjectResearch()
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "新增部门" }))
    await user.type(screen.getByLabelText("部门名称"), "销售部")
    await user.click(screen.getByRole("button", { name: "创建" }))
    expect(await screen.findByRole("treeitem", { name: /销售部/ })).toHaveFocus()
    expect(screen.queryByLabelText("核心目标")).not.toBeInTheDocument()
    await openResearchForm(user)
    await user.type(await screen.findByLabelText("核心目标"), "提高线索转化")
    await user.click(screen.getByRole("button", { name: "保存调研内容" }))

    expect(await screen.findByText("调研内容已保存。")).toBeVisible()
    expect(screen.getByRole("button", { name: "填写" })).toBeVisible()
    expect(screen.queryByLabelText("核心目标")).not.toBeInTheDocument()
    expect(mutationBodies(apiRequest, "/research/forms/form-subject-sales", "PATCH")).toContainEqual({
      version: 1,
      answers: { goal: "提高线索转化" },
    })
    expect(mutationBodies(apiRequest, "/research/forms/form-subject-sales/confirm", "POST")).toHaveLength(0)
  })

  it("shows the saved description for the selected research subject", async () => {
    renderProjectResearch({
      initialSubjects: [
        rootSubject,
        { ...departmentSubject, description: "负责市场线索获取、商机转化与客户管理。" },
      ],
    })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))

    expect(screen.getByText("部门说明")).toBeVisible()
    expect(screen.getByText("负责市场线索获取、商机转化与客户管理。")).toBeVisible()
  })

  it("refreshes the project aggregate after stale create and retries with its current version", async () => {
    const apiRequest = renderProjectResearch({ createStaleOnce: true, projectVersionAfterStale: 7 })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "新增部门" }))
    await user.type(screen.getByLabelText("部门名称"), "运营部")
    await user.click(screen.getByRole("button", { name: "创建" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("已被更新")
    await user.click(screen.getByRole("button", { name: "创建" }))

    expect(await screen.findByRole("treeitem", { name: /运营部/ })).toBeVisible()
    const bodies = mutationBodies(apiRequest, "/research/subjects", "POST") as Array<{ version: number }>
    expect(bodies.map((body) => body.version)).toEqual([5, 7])
  })

  it("edits a department name and description without replacing its research subject", async () => {
    const apiRequest = renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject] })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    await user.click(await screen.findByRole("button", { name: "编辑部门：销售部" }))
    const dialog = screen.getByRole("dialog", { name: "编辑部门" })
    const input = within(dialog).getByLabelText("部门名称")
    await user.clear(input)
    await user.type(input, "大客户销售部")
    await user.type(within(dialog).getByLabelText("部门说明"), "负责战略客户开拓与跟进。")
    await user.click(within(dialog).getByRole("button", { name: "保存" }))

    expect(await screen.findByRole("treeitem", { name: /大客户销售部/ })).toBeVisible()
    expect(await screen.findByText("负责战略客户开拓与跟进。")).toBeVisible()
    expect(mutationBodies(apiRequest, `/research/subjects/${departmentSubject.id}`, "PATCH")).toContainEqual({ version: 1, name: "大客户销售部", description: "负责战略客户开拓与跟进。" })
  })

  it("saves a private memo for the selected role without changing its description", async () => {
    const apiRequest = renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject, roleSubject] })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: `展开${departmentSubject.name}的下级` }))
    await user.click(await screen.findByRole("treeitem", { name: /销售专员/ }))
    const memo = await screen.findByRole("textbox", { name: "岗位备忘录" })
    await user.type(memo, "客户回访仍用 Excel，待确认数据口径。")
    await user.click(screen.getByRole("button", { name: "保存备忘录" }))

    expect(await screen.findByText("岗位备忘录已保存。")).toBeVisible()
    expect(mutationBodies(apiRequest, `/research/subjects/${roleSubject.id}/memo`, "PATCH")).toContainEqual({
      version: 1,
      memo: "客户回访仍用 Excel，待确认数据口径。",
    })
    expect(screen.getByText("岗位备忘录已保存。")).toBeVisible()
  })

  it("shows and saves a memo for the enterprise root", async () => {
    const apiRequest = renderProjectResearch({ initialSubjects: [rootSubject] })
    const user = userEvent.setup()

    const memo = await screen.findByRole("textbox", { name: "企业备忘录" })
    await user.type(memo, "# 客户目标\n两个月内验证")
    memo.focus()
    ;(memo as HTMLTextAreaElement).setSelectionRange(4, 4)
    fireEvent.keyDown(memo, { key: "s", metaKey: true })

    expect(await screen.findByText("企业备忘录已保存。")).toBeVisible()
    expect(memo).toHaveFocus()
    expect((memo as HTMLTextAreaElement).selectionStart).toBe(4)
    expect((memo as HTMLTextAreaElement).selectionEnd).toBe(4)
    expect(mutationBodies(apiRequest, `/research/subjects/${rootSubject.id}/memo`, "PATCH")).toContainEqual({
      version: 1,
      memo: "# 客户目标\n两个月内验证",
    })

    const memoEnd = (memo as HTMLTextAreaElement).value.length
    ;(memo as HTMLTextAreaElement).setSelectionRange(memoEnd, memoEnd)
    fireEvent.keyDown(memo, { key: "Tab" })
    expect(memo).toHaveValue("# 客户目标\n两个月内验证  ")
    expect(memo).toHaveFocus()
    expect((memo as HTMLTextAreaElement).selectionStart).toBe(memoEnd + 2)

    await user.click(screen.getByRole("button", { name: "完成编辑" }))
    expect(await screen.findByRole("heading", { name: "客户目标" })).toBeVisible()
    expect(screen.queryByRole("textbox", { name: "企业备忘录" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "编辑" })).toBeVisible()
  })

  it("shows every member's personal memo but only lets the owner edit it", async () => {
    const apiRequest = renderProjectResearch({
      initialSubjects: [rootSubject],
      initialPersonalMemos: [{
        subject_id: rootSubject.id,
        user_id: engineerUser.id,
        memo: "# 李工程师观察\n\n- 数据口径仍待确认",
      }],
    })
    const user = userEvent.setup()
    const launcher = await screen.findByLabelText("项目成员个人备忘录")
    const engineerMemoButton = await screen.findByRole("button", { name: engineerUser.displayName })

    await user.click(engineerMemoButton)
    let dialog = screen.getByRole("dialog", { name: `个人备忘录 · ${engineerUser.displayName}` })
    expect(within(dialog).getByRole("heading", { name: "李工程师观察" })).toBeVisible()
    expect(within(dialog).queryByRole("textbox")).not.toBeInTheDocument()
    expect(within(dialog).queryByRole("button", { name: "编辑" })).not.toBeInTheDocument()
    await user.click(within(dialog).getAllByRole("button", { name: "关闭" }).at(-1)!)

    await user.click(within(launcher).getByRole("button", { name: adminUser.displayName }))
    dialog = screen.getByRole("dialog", { name: `个人备忘录 · ${adminUser.displayName}` })
    const editor = within(dialog).getByRole("textbox", { name: `${adminUser.displayName}的个人备忘录` })
    await user.type(editor, "# 我的观察\n\n- 跟进客户样本")
    await user.click(within(dialog).getByRole("button", { name: "保存个人备忘录" }))

    expect(mutationBodies(apiRequest, `/research/subjects/${rootSubject.id}/personal-memo`, "PATCH")).toContainEqual({
      version: 0,
      memo: "# 我的观察\n\n- 跟进客户样本",
    })
  })

  it("lets a read-only project member maintain only their own personal memo", async () => {
    const viewer: UserDto = { ...engineerUser, id: "viewer-personal-memo", username: "viewer", displayName: "观察员", role: "viewer" }
    const apiRequest = renderProjectResearch({ user: viewer, initialSubjects: [rootSubject] })
    const user = userEvent.setup()

    expect(await screen.findByRole("heading", { name: "企业备忘录" })).toBeVisible()
    expect(screen.queryByRole("button", { name: "AI 合并整理" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "编辑" })).not.toBeInTheDocument()
    await user.click(await screen.findByRole("button", { name: viewer.displayName }))
    const dialog = screen.getByRole("dialog", { name: `个人备忘录 · ${viewer.displayName}` })
    await user.type(within(dialog).getByRole("textbox"), "仅本人可改")
    await user.click(within(dialog).getByRole("button", { name: "保存个人备忘录" }))

    expect(mutationBodies(apiRequest, `/research/subjects/${rootSubject.id}/personal-memo`, "PATCH")).toContainEqual({ version: 0, memo: "仅本人可改" })
  })

  it("compares AI-merged personal notes before explicitly adopting the shared memo", async () => {
    const apiRequest = renderProjectResearch({
      initialSubjects: [rootSubject],
      initialPersonalMemos: [{ subject_id: rootSubject.id, user_id: engineerUser.id, memo: "客户口径待确认" }],
    })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "AI 合并整理" }))
    const dialog = await screen.findByRole("dialog", { name: `AI 合并整理 · ${rootSubject.name}` })
    expect(within(dialog).getByRole("heading", { name: "整合前" })).toBeVisible()
    expect(within(dialog).getByRole("heading", { name: "AI 整合后" })).toBeVisible()
    expect(within(dialog).getByText("客户口径待确认")).toBeVisible()
    expect(within(dialog).getByText("合并重复内容")).toBeVisible()
    expect(mutationBodies(apiRequest, `/research/subjects/${rootSubject.id}/memo`, "PATCH")).toHaveLength(0)

    await user.click(within(dialog).getByRole("button", { name: "采用整理结果" }))
    expect(mutationBodies(apiRequest, `/research/subjects/${rootSubject.id}/memo`, "PATCH")).toContainEqual({
      version: 1,
      memo: "# 合并结论\n\n- 已整合个人观察",
    })
  })

  it("labels the project subtree as 企业 and shows dynamic add buttons per node type", async () => {
    renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject, roleSubject] })
    const user = userEvent.setup()

    // The 企业 root is auto-selected and labelled 企业 (not 企业根).
    expect(await screen.findByRole("heading", { name: "星河调研项目" })).toBeVisible()
    expect(screen.getByRole("button", { name: "新增部门" })).toBeVisible()
    expect(screen.getByRole("button", { name: "新增流程" })).toBeVisible()
    expect(screen.getByRole("button", { name: "新增 AI 机会" })).toBeVisible()
    expect(screen.queryByRole("button", { name: "新增岗位" })).not.toBeInTheDocument()
    expect(screen.queryByText("企业根")).not.toBeInTheDocument()
    expect(screen.getAllByText("企业").length).toBeGreaterThanOrEqual(1)

    // Selecting a department only offers department child types.
    await user.click(screen.getByRole("treeitem", { name: /销售部/ }))
    expect(await screen.findByRole("button", { name: "新增岗位" })).toBeVisible()
    expect(screen.getByRole("button", { name: "新增流程" })).toBeVisible()
    expect(screen.getByRole("button", { name: "新增 AI 机会" })).toBeVisible()
    expect(screen.queryByRole("button", { name: "新增部门" })).not.toBeInTheDocument()

    // Selecting a role only offers role child types.
    await user.click(screen.getByRole("button", { name: "展开销售部的下级" }))
    await user.click(screen.getByRole("treeitem", { name: /销售专员/ }))
    expect(await screen.findByRole("button", { name: "新增流程" })).toBeVisible()
    expect(screen.getByRole("button", { name: "新增 AI 机会" })).toBeVisible()
    expect(screen.queryByRole("button", { name: "新增岗位" })).not.toBeInTheDocument()
  })

  it("guards workspace replacement actions across forms and restores focus on cancellation", async () => {
    const secondDefinition = {
      ...definition,
      id: "form-definition-extra",
      form_key: "department_extra",
      name: "部门补充调研",
      sections: [{
        ...definition.sections[0],
        fields: [{ ...definition.sections[0].fields[0], id: "extra", field_key: "extra", name: "补充目标" }],
      }],
    }
    const second = formFor(departmentSubject.id, {
      id: "form-subject-sales-extra",
      form_key: "department_extra",
      name: "部门补充调研",
      definition_snapshot: secondDefinition,
    })
    const apiRequest = renderProjectResearch({
      initialSubjects: [rootSubject, departmentSubject],
      initialForms: [formFor(departmentSubject.id), second],
    })
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    await openResearchForm(user, "部门补充调研")
    const dirtyField = screen.getByLabelText("补充目标")
    await user.type(dirtyField, "不能丢")
    await user.click(screen.getByRole("button", { name: "新增岗位" }))
    expect(screen.queryByLabelText("岗位名称")).not.toBeInTheDocument()
    expect(mutationBodies(apiRequest, "/research/subjects", "POST")).toHaveLength(0)
    expect(dirtyField).toHaveValue("不能丢")
    expect(dirtyField).toHaveFocus()
    confirm.mockReturnValue(true)
    await user.click(screen.getByRole("button", { name: "新增岗位" }))
    await user.type(screen.getByLabelText("岗位名称"), "新岗位")
    await user.click(screen.getByRole("button", { name: "创建" }))
    expect(mutationBodies(apiRequest, "/research/subjects", "POST")).toHaveLength(1)
  })

  it("creates an AI opportunity under the selected node and lists it", async () => {
    const apiRequest = renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject] })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    await user.click(screen.getByRole("button", { name: "新增 AI 机会" }))
    await user.type(screen.getByLabelText("AI 机会名称"), "智能配送")
    await user.type(screen.getByLabelText("目标使用对象"), "仓库调度员")
    await user.selectOptions(screen.getByLabelText("优先级"), "high")
    await user.selectOptions(screen.getByLabelText("业务价值"), "5")
    await user.click(screen.getByRole("button", { name: "创建" }))

    expect(await screen.findByRole("heading", { name: "智能配送" })).toBeVisible()
    expect(screen.queryByRole("treeitem", { name: /智能配送/ })).not.toBeInTheDocument()
    const bodies = mutationBodies(apiRequest, "/research/subjects", "POST") as Array<{ subject_type: string; parent_subject_id: string }>
    expect(bodies.at(-1)).toMatchObject({
      subject_type: "opportunity",
      parent_subject_id: departmentSubject.id,
    })
    const profileBody = apiRequest.mock.calls.find(([path, request]) => String(path).includes("/research/subjects/subject-opportunity_") && request.method === "PATCH")?.[1].body
    expect(profileBody).toEqual(expect.objectContaining({
      opportunity_profile: expect.objectContaining({ target_audience: "仓库调度员", priority: "high", business_value_score: 5 }),
    }))
  })

  it("guards sidebar and direct hash navigation while dirty, with cancel focus and confirm paths", async () => {
    renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject], initialForms: [formFor(departmentSubject.id)] })
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    await openResearchForm(user)
    const field = screen.getByLabelText("核心目标")
    await user.type(field, "保留")
    const beforeUnload = new Event("beforeunload", { cancelable: true })
    expect(window.dispatchEvent(beforeUnload)).toBe(false)
    expect(beforeUnload.defaultPrevented).toBe(true)
    await user.click(screen.getByRole("link", { name: "行业模板" }))
    expect(location.hash).toBe(`#projects/${projectId}?tab=research`)
    expect(field).toHaveFocus()

    location.hash = "#users"
    await waitFor(() => expect(location.hash).toBe(`#projects/${projectId}?tab=research`))
    expect(field).toHaveFocus()

    confirm.mockReturnValue(true)
    await user.click(screen.getByRole("link", { name: "行业模板" }))
    await waitFor(() => expect(location.hash).toBe("#templates"))
  })

  it("preserves input after a failed save and advances its version only after an explicit successful retry", async () => {
    const apiRequest = renderProjectResearch({
      initialSubjects: [rootSubject, departmentSubject],
      initialForms: [formFor(departmentSubject.id)],
      patchErrorOnce: true,
    })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /\u9500\u552e\u90e8/ }))
    await openResearchForm(user)
    await user.type(screen.getByLabelText("核心目标"), "保留失败后重试的内容")
    await user.click(screen.getByRole("button", { name: "保存调研内容" }))
    expect(await screen.findByRole("alert")).toBeVisible()
    expect(screen.getByLabelText("核心目标")).toHaveValue("保留失败后重试的内容")
    expect(mutationBodies(apiRequest, "/research/forms/form-subject-sales", "PATCH")).toHaveLength(1)
    await user.click(screen.getByRole("button", { name: "保存调研内容" }))
    expect(await screen.findByText("调研内容已保存。")).toBeVisible()
    await openResearchForm(user)
    expect(screen.getByLabelText("核心目标")).toHaveValue("保留失败后重试的内容")
    await user.type(screen.getByLabelText("核心目标"), "，继续补充")
    await user.click(screen.getByRole("button", { name: "保存调研内容" }))
    expect(mutationBodies(apiRequest, "/research/forms/form-subject-sales", "PATCH")).toEqual([
      { version: 1, answers: { goal: "保留失败后重试的内容" } },
      { version: 1, answers: { goal: "保留失败后重试的内容" } },
      { version: 2, answers: { goal: "保留失败后重试的内容，继续补充" } },
    ])
    expect(mutationBodies(apiRequest, "/research/forms/form-subject-sales/confirm", "POST")).toHaveLength(0)
  })

  it("keeps local input and offers explicit refresh, compare, and discard after stale_version", async () => {
    renderProjectResearch({
      initialSubjects: [rootSubject, departmentSubject],
      initialForms: [formFor(departmentSubject.id)],
      patchError: { code: "stale_version" },
    })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /\u9500\u552e\u90e8/ }))
    await openResearchForm(user)
    await user.type(screen.getByLabelText("核心目标"), "本地未保存内容")
    await user.click(screen.getByRole("button", { name: "保存调研内容" }))

    expect(screen.getByDisplayValue("本地未保存内容")).toBeVisible()
    expect(await screen.findByText(/\u5176\u4ed6\u540c\u4e8b\u5df2\u66f4\u65b0/)).toBeVisible()
    expect(screen.getByRole("button", { name: "刷新远端版本" })).toBeVisible()
    expect(screen.getByRole("button", { name: "比较差异" })).toBeVisible()
    expect(screen.getByRole("button", { name: "放弃本地修改" })).toBeVisible()
    await user.click(screen.getByRole("button", { name: "刷新远端版本" }))
    expect(await screen.findByText("已读取远端版本，本地输入仍保留。")).toBeVisible()
    expect(screen.getByLabelText("核心目标")).toHaveValue("本地未保存内容")
    await user.click(screen.getByRole("button", { name: "比较差异" }))
    expect(screen.getByRole("region", { name: "本地与远端差异" })).toHaveTextContent("本地：本地未保存内容")
    await user.click(screen.getByRole("button", { name: "放弃本地修改" }))
    expect(screen.getByLabelText("核心目标")).toHaveValue("")
    expect(await screen.findByText("已放弃本地修改并采用远端版本。")).toBeVisible()
  })

  it("warns before navigating to another research subject with unsaved input", async () => {
    renderProjectResearch({
      initialSubjects: [rootSubject, departmentSubject, otherDepartment],
      initialForms: [formFor(departmentSubject.id), formFor(otherDepartment.id)],
    })
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /\u9500\u552e\u90e8/ }))
    await openResearchForm(user)
    await user.type(screen.getByLabelText("核心目标"), "未保存")
    await user.click(screen.getByRole("treeitem", { name: /\u4ea4\u4ed8\u90e8/ }))

    expect(confirm).toHaveBeenCalledWith("当前表单有未保存修改，确定离开吗？")
    expect(screen.getByLabelText("核心目标")).toHaveValue("未保存")
  })

  it("lists AI opportunities and hides legacy delivery design in the read-only detail", async () => {
    renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject, opportunitySubject], initialForms: [opportunityFormFor()] })
    const user = userEvent.setup()

    // Only opportunities directly attached to the selected object are listed.
    expect(await screen.findByText("当前选定范围内暂无 AI 机会，可切换上级对象查看。")).toBeVisible()
    await user.click(screen.getByRole("treeitem", { name: /销售部/ }))
    const list = await screen.findByRole("list", { name: "AI 机会列表" })
    expect(within(list).getByText("智能排产助手")).toBeVisible()
    expect(within(list).getByRole("button", { name: "查看" })).toBeVisible()

    // Legacy delivery fields remain stored but are not part of opportunity identification.
    await user.click(within(list).getByRole("button", { name: "查看" }))
    expect(await screen.findByRole("heading", { name: "智能排产助手" })).toBeVisible()
    expect(screen.getByRole("group", { name: "发现" })).toBeVisible()
    expect(screen.queryByRole("group", { name: "交付说明" })).not.toBeInTheDocument()
    expect(screen.getByLabelText("现状描述")).toBeDisabled()
    expect(screen.queryByLabelText("交付范围")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "编辑" })).toBeVisible()
  })

  it("switches an AI opportunity to edit mode and saves answers grouped under the modules", async () => {
    const apiRequest = renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject, opportunitySubject], initialForms: [opportunityFormFor()] })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    await user.click(await screen.findByRole("button", { name: "查看" }))
    await user.click(await screen.findByRole("button", { name: "编辑" }))

    const pain = screen.getByLabelText("痛点/问题")
    expect(pain).toBeEnabled()
    await user.type(pain, "排产依赖人工经验")
    await user.click(screen.getByRole("button", { name: "保存调研内容" }))
    expect(await screen.findByText("调研内容已保存。")).toBeVisible()
    expect(mutationBodies(apiRequest, "/research/forms/form-opportunity-copilot", "PATCH")).toContainEqual({
      version: 1,
      answers: { pain_points: "排产依赖人工经验" },
    })
  })

  it("deletes an AI opportunity from its detail view while retaining history", async () => {
    const apiRequest = renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject, opportunitySubject], initialForms: [opportunityFormFor()] })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    await user.click(await screen.findByRole("button", { name: "查看" }))
    await user.click(screen.getByRole("button", { name: "删除" }))
    const dialog = await screen.findByRole("dialog", { name: "删除 AI 机会" })
    expect(within(dialog).getByText(/历史调研数据仍会保留/)).toBeVisible()
    await user.type(within(dialog).getByLabelText("当前账号密码"), "AdminPass!123")
    await user.click(within(dialog).getByRole("button", { name: "删除" }))

    expect(await screen.findByText("AI 机会已删除，历史数据已保留。")).toBeVisible()
    expect(mutationBodies(apiRequest, `/research/subjects/${opportunitySubject.id}`, "DELETE")).toContainEqual({ version: 1 })
  })

  it("edits the structured AI opportunity profile using the target audience wording", async () => {
    const describedOpportunity = { ...opportunitySubject, description: "减少人工排产时间并降低插单冲突。" }
    const apiRequest = renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject, describedOpportunity], initialForms: [opportunityFormFor()] })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    await user.click(await screen.findByRole("button", { name: "查看" }))
    expect(screen.getByText("目标使用对象")).toBeVisible()
    expect(screen.getByText("排产员与生产主管")).toBeVisible()
    expect(screen.getByText("说明")).toBeVisible()
    expect(screen.getByText("减少人工排产时间并降低插单冲突。")).toBeVisible()
    expect(screen.getByText("业务价值 5/5")).toBeVisible()
    await user.click(screen.getByRole("button", { name: "编辑" }))
    const target = screen.getByLabelText("目标使用对象")
    await user.clear(target)
    await user.type(target, "计划员、车间主管和工厂负责人")
    await user.clear(screen.getByLabelText("说明"))
    await user.type(screen.getByLabelText("说明"), "通过智能排产减少冲突。")
    await user.click(screen.getByRole("button", { name: "保存机会档案" }))

    expect(await screen.findByRole("button", { name: "编辑" })).toBeVisible()
    expect(screen.queryByRole("button", { name: "保存机会档案" })).not.toBeInTheDocument()

    const body = mutationBodies(apiRequest, `/research/subjects/${opportunitySubject.id}`, "PATCH")[0] as Record<string, unknown>
    expect(body).toEqual(expect.objectContaining({
      version: opportunitySubject.version,
      description: "通过智能排产减少冲突。",
      opportunity_profile: expect.objectContaining({ target_audience: "计划员、车间主管和工厂负责人" }),
    }))
    expect(body.opportunity_profile).not.toHaveProperty("owner_display_name")
  })

  it("protects unsaved opportunity profiles before return or workspace replacement and clears the guard after discard", async () => {
    const apiRequest = renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject, opportunitySubject], initialForms: [opportunityFormFor()] })
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    await user.click(screen.getByRole("button", { name: "查看" }))
    await user.click(screen.getByRole("button", { name: "编辑" }))
    await user.type(screen.getByLabelText("说明"), "未保存的机会说明")
    await user.click(screen.getByRole("button", { name: "返回", exact: true }))
    expect(confirm).toHaveBeenCalledWith("返回会退出 AI 机会详情，确定继续吗？")
    expect(screen.getByLabelText("说明")).toHaveValue("未保存的机会说明")
    expect(screen.getByLabelText("说明")).toHaveFocus()
    await user.click(screen.getByRole("button", { name: "新增 AI 机会" }))
    expect(confirm).toHaveBeenLastCalledWith("创建调研对象会切换工作区并放弃未保存修改，确定继续吗？")
    expect(screen.queryByLabelText("AI 机会名称")).not.toBeInTheDocument()
    expect(screen.getByLabelText("说明")).toHaveValue("未保存的机会说明")
    expect(mutationBodies(apiRequest, `/research/subjects/${opportunitySubject.id}`, "PATCH")).toHaveLength(0)
    confirm.mockReturnValue(true)
    await user.click(screen.getByRole("button", { name: "返回", exact: true }))
    expect(screen.queryByLabelText("说明")).not.toBeInTheDocument()
    confirm.mockClear()
    await user.click(screen.getByRole("treeitem", { name: /星河调研项目/ }))
    expect(confirm).not.toHaveBeenCalled()
  })

  it("clears only the saved opportunity profile guard and retains unsaved form-answer protection", async () => {
    renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject, opportunitySubject], initialForms: [opportunityFormFor()] })
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    await user.click(screen.getByRole("button", { name: "查看" }))
    await user.click(screen.getByRole("button", { name: "编辑" }))
    await user.type(screen.getByLabelText("说明"), "已保存的说明")
    await user.type(screen.getByLabelText("痛点/问题"), "尚未保存的答案")
    await user.click(screen.getByRole("button", { name: "保存机会档案" }))
    expect(await screen.findByText("机会档案已保存。")).toBeVisible()
    await user.click(screen.getByRole("button", { name: "返回", exact: true }))
    expect(confirm).toHaveBeenCalled()
    await user.click(screen.getByRole("button", { name: "编辑" }))
    expect(screen.getByLabelText("痛点/问题")).toHaveValue("尚未保存的答案")
    await user.click(screen.getByRole("button", { name: "保存调研内容" }))
    expect(await screen.findByText("调研内容已保存。")).toBeVisible()
    confirm.mockClear()
    await user.click(screen.getByRole("button", { name: "返回", exact: true }))
    expect(confirm).not.toHaveBeenCalled()
  })

  it("blocks an overlong opportunity target before sending the request and names the field", async () => {
    const apiRequest = renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject, opportunitySubject], initialForms: [opportunityFormFor()] })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    await user.click(await screen.findByRole("button", { name: "查看" }))
    await user.click(screen.getByRole("button", { name: "编辑" }))
    fireEvent.change(screen.getByLabelText("目标使用对象"), { target: { value: "人".repeat(301) } })
    await user.click(screen.getByRole("button", { name: "保存机会档案" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("目标使用对象不能超过 300 个字符")
    expect(mutationBodies(apiRequest, `/research/subjects/${opportunitySubject.id}`, "PATCH")).toHaveLength(0)
  })

  it("links opportunity to project delivery documents instead of generating inline", async () => {
    const apiRequest = renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject, opportunitySubject], initialForms: [opportunityFormFor()] })
    const user = userEvent.setup()
    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    await user.click(await screen.findByRole("button", { name: "查看" }))
    await user.click(screen.getByText("更多"))
    expect(screen.getByRole("link", { name: "查看关联方案" })).toHaveAttribute("href", `#projects/${project.id}?tab=delivery&opportunity=${opportunitySubject.id}`)
    expect(screen.queryByRole("button", { name: "生成 PoV 文档" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "生成 SOW 文档" })).not.toBeInTheDocument()
    expect(mutationBodies(apiRequest, "/documents", "POST")).toHaveLength(0)
  })
  it("distinguishes a server-side profile rejection after client validation", async () => {
    renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject, opportunitySubject], initialForms: [opportunityFormFor()], opportunityPatchError: { code: "invalid_opportunity_profile" } })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    await user.click(await screen.findByRole("button", { name: "查看" }))
    await user.click(screen.getByRole("button", { name: "编辑" }))
    await user.click(screen.getByRole("button", { name: "保存机会档案" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("服务端判定机会档案字段不合法")
    expect(screen.getByRole("alert")).toHaveTextContent("重新选择评分、状态和负责人")
  })


  it("keeps the password-confirmed danger archive action in the tree without a duplicate heading action", async () => {
    const apiRequest = renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject] })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    expect(screen.getByRole("button", { name: "停用销售部" })).toHaveClass("danger-button")
    expect(screen.queryByRole("button", { name: "停用", exact: true })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "停用销售部" }))
    const dialog = await screen.findByRole("dialog", { name: "停用调研对象" })
    await user.type(within(dialog).getByLabelText("当前账号密码"), "AdminPass!123")
    await user.click(within(dialog).getByRole("button", { name: "停用" }))
    await waitFor(() => expect(screen.queryByRole("treeitem", { name: /销售部/ })).not.toBeInTheDocument())
    expect(mutationBodies(apiRequest, `/research/subjects/${departmentSubject.id}`, "DELETE")).toContainEqual({ version: 1 })
  })

  it("creates a project-scoped research form bound to a selected node (no template)", async () => {
    const apiRequest = renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject] })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    await user.click(screen.getByRole("button", { name: "新增调研表" }))
    expect(await screen.findByRole("heading", { name: "新增调研表" })).toBeVisible()

    await user.type(screen.getByLabelText("调研表名称"), "销售专项调研")
    await user.type(screen.getByLabelText("稳定标识"), "sales_special")
    await user.click(screen.getByRole("button", { name: "新增章节" }))
    await user.type(screen.getByLabelText("章节标题"), "经营")
    await user.type(screen.getByLabelText("章节稳定标识"), "ops")
    await user.click(screen.getByRole("button", { name: "在章节 1 中新增字段" }))
    await user.type(screen.getByLabelText("字段标签"), "重点")
    await user.type(screen.getByLabelText("字段稳定标识"), "focus")
    await user.click(screen.getByRole("button", { name: "创建调研表" }))

    expect(await screen.findByText("调研表已创建。")).toBeVisible()
    expect(mutationBodies(apiRequest, "/research/forms", "POST")).toContainEqual(expect.objectContaining({
      subject_id: departmentSubject.id,
      form_key: "sales_special",
      subject_type: "department",
    }))
    expect(screen.getByRole("heading", { name: "销售专项调研" })).toBeVisible()
  })

  it("protects unsaved form structure on cancel, subject switch and sidebar navigation", async () => {
    const apiRequest = renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject] })
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    await user.click(screen.getByRole("button", { name: "新增调研表" }))
    await user.type(screen.getByLabelText("调研表名称"), "保留结构")
    await user.click(screen.getByRole("button", { name: "取消", exact: true }))
    expect(confirm).toHaveBeenCalledWith("取消会放弃未保存的结构修改，确定继续吗？")
    expect(screen.getByLabelText("调研表名称")).toHaveValue("保留结构")
    expect(screen.getByLabelText("调研表名称")).toHaveFocus()
    await user.click(screen.getByRole("treeitem", { name: /星河调研项目/ }))
    expect(screen.getByLabelText("调研表名称")).toHaveValue("保留结构")
    await user.click(screen.getByRole("link", { name: "行业模板" }))
    expect(location.hash).toBe(`#projects/${projectId}?tab=research`)
    expect(mutationBodies(apiRequest, "/research/forms", "POST")).toHaveLength(0)
    confirm.mockReturnValue(true)
    await user.click(screen.getByRole("button", { name: "取消", exact: true }))
    expect(screen.queryByLabelText("调研表名称")).not.toBeInTheDocument()
    confirm.mockClear()
    await user.click(screen.getByRole("treeitem", { name: /星河调研项目/ }))
    expect(confirm).not.toHaveBeenCalled()
  })

  it("shows AI generation inside manual creation and prefills the project form builder", async () => {
    const apiRequest = renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject] })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    const formWorkspace = screen.getByRole("main", { name: "调研表单工作区" })
    expect(within(formWorkspace).queryByRole("button", { name: "AI 辅助生成" })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "新增调研表" }))
    const aiButton = within(formWorkspace).getByRole("button", { name: "AI 辅助生成" })
    await user.click(aiButton)
    expect(await screen.findByRole("dialog", { name: "AI 辅助生成调研表" })).toBeVisible()
    await user.type(screen.getByLabelText("生成要求（可选）"), "重点了解销售流程和客户数据")
    await user.click(screen.getByRole("button", { name: "生成调研表" }))

    expect(await screen.findByLabelText("调研表名称")).toHaveValue("销售部 AI 调研")
    expect(screen.getByLabelText("稳定标识")).toHaveValue("department_sales_ai_interview")
    expect(screen.getByLabelText("字段标签")).toHaveValue("当前流程")
    expect(apiRequest).toHaveBeenCalledWith(
      "/api/v1/ai/executions",
      expect.objectContaining({
        method: "POST",
        body: expect.objectContaining({
          operation: "project_research_form_generate",
          payload: expect.objectContaining({ project_id: projectId, subject_id: departmentSubject.id, requirement: "重点了解销售流程和客户数据" }),
        }),
      }),
    )
  })

  it("exports one answered research form from its card and omits the manual refresh action", async () => {
    const baseForm = formFor(departmentSubject.id)
    const answered = formFor(departmentSubject.id, {
      completion: {
        ...baseForm.completion,
        answered_visible: 1,
        answered_visible_field_count: 1,
        completion_rate: 100,
      },
    })
    const apiRequest = renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject], initialForms: [answered] })
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    expect(screen.queryByRole("button", { name: "刷新调研数据" })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "导出到文件库" }))

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("后台生成 DOCX"))
    await waitFor(() => expect(mutationBodies(apiRequest, `/research/forms/${answered.id}/export`, "POST")).toContainEqual({}))
    expect(await screen.findByText(/调研表“部门基础调研”已提交后台生成/)).toBeVisible()
    expect(screen.getByRole("button", { name: "后台生成中…" })).toBeDisabled()
  })

  it("shows the active-child archive error without exposing raw server text", async () => {
    renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject, roleSubject] })
    vi.spyOn(window, "confirm").mockReturnValue(true)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    await user.click(screen.getByRole("button", { name: "停用销售部" }))
    const dialog = await screen.findByRole("dialog", { name: "停用调研对象" })
    await user.type(within(dialog).getByLabelText("当前账号密码"), "AdminPass!123")
    await user.click(within(dialog).getByRole("button", { name: "停用" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("先停用其下级")
    expect(screen.queryByText("raw backend detail must not render")).not.toBeInTheDocument()
  })

  it("restores tree focus to the parent after a successful archive", async () => {
    const apiRequest = renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject] })
    vi.spyOn(window, "confirm").mockReturnValue(true)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    await user.click(screen.getByRole("button", { name: "停用销售部" }))
    const dialog = await screen.findByRole("dialog", { name: "停用调研对象" })
    await user.type(within(dialog).getByLabelText("当前账号密码"), "AdminPass!123")
    await user.click(within(dialog).getByRole("button", { name: "停用" }))

    await waitFor(() => expect(screen.queryByRole("treeitem", { name: /销售部/ })).not.toBeInTheDocument())
    expect(screen.getByRole("treeitem", { name: /星河调研项目/ })).toHaveFocus()
    expect(mutationBodies(apiRequest, `/research/subjects/${departmentSubject.id}`, "DELETE")).toContainEqual({ version: 1 })
  })

  it("returns a nested archived subject selection and focus to its immediate parent", async () => {
    renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject, roleSubject] })
    vi.spyOn(window, "confirm").mockReturnValue(true)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "展开销售部的下级" }))
    await user.click(await screen.findByRole("treeitem", { name: /销售专员/ }))
    await user.click(screen.getByRole("button", { name: "停用销售专员" }))
    const dialog = await screen.findByRole("dialog", { name: "停用调研对象" })
    await user.type(within(dialog).getByLabelText("当前账号密码"), "AdminPass!123")
    await user.click(within(dialog).getByRole("button", { name: "停用" }))

    await waitFor(() => expect(screen.queryByRole("treeitem", { name: /销售专员/ })).not.toBeInTheDocument())
    const parent = screen.getByRole("treeitem", { name: /销售部/ })
    expect(parent).toHaveAttribute("aria-selected", "true")
    expect(parent).toHaveFocus()
  })

  it("guards logout with the active dirty checker and restores focus when cancelled", async () => {
    renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject], initialForms: [formFor(departmentSubject.id)] })
    const logout = vi.spyOn(window.fde.auth, "logout")
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /销售部/ }))
    await openResearchForm(user)
    const field = screen.getByLabelText("核心目标")
    await user.type(field, "保留草稿")
    await user.click(await screen.findByRole("button", { name: "退出登录" }))

    expect(logout).not.toHaveBeenCalled()
    expect(field).toHaveFocus()
    confirm.mockReturnValueOnce(true).mockReturnValueOnce(true)
    await user.click(screen.getByRole("button", { name: "退出登录" }))
    await waitFor(() => expect(logout).toHaveBeenCalledTimes(1))
  })

  it("logs out after one ordinary confirmation without asking for a password", async () => {
    renderProjectResearch({ initialSubjects: [rootSubject] })
    const logout = vi.spyOn(window.fde.auth, "logout")
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "退出登录" }))

    await waitFor(() => expect(logout).toHaveBeenCalledTimes(1))
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(confirm).toHaveBeenCalledWith("确定退出登录吗？")
    expect(screen.queryByLabelText("当前账号密码")).not.toBeInTheDocument()
  })

  it("scopes opportunities to the exact selected object, not its ancestors or descendants", async () => {
    renderProjectResearch({ initialSubjects: [rootSubject, departmentSubject, roleSubject, opportunitySubject], initialForms: [opportunityFormFor()] })
    const user = userEvent.setup()

    await screen.findByRole("treeitem", { name: /星河调研项目/ })
    expect(screen.queryByRole("list", { name: "AI 机会列表" })).not.toBeInTheDocument()
    await user.click(screen.getByRole("treeitem", { name: /销售部/ }))
    const list = await screen.findByRole("list", { name: "AI 机会列表" })
    expect(within(list).getByText("智能排产助手")).toBeVisible()
    expect(within(screen.getByRole("tree", { name: "项目调研对象树" })).queryByText("智能排产助手")).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "展开销售部的下级" }))
    await user.click(screen.getByRole("treeitem", { name: /销售专员/ }))
    expect(await screen.findByText("当前选定范围内暂无 AI 机会，可切换上级对象查看。")).toBeVisible()
    expect(screen.queryByRole("list", { name: "AI 机会列表" })).not.toBeInTheDocument()
  })

  it("lets viewers open form cards read-only without mutation or creation controls", async () => {
    const viewer = { ...engineerUser, id: "viewer-id", username: "viewer", displayName: "查看者", role: "viewer" as const }
    renderProjectResearch({
      user: viewer,
      initialSubjects: [rootSubject, departmentSubject],
      initialForms: [formFor(departmentSubject.id)],
    })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /\u9500\u552e\u90e8/ }))
    await openResearchForm(user, "部门基础调研", "查看")
    expect(screen.getByLabelText("核心目标")).toBeDisabled()
    expect(screen.queryByRole("button", { name: "保存调研内容" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "新增部门" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "新增 AI 机会" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "新增调研表" })).not.toBeInTheDocument()
  })

  it("lets an assigned engineer fill and save directly without legacy confirmation or return workflows", async () => {
    renderProjectResearch({
      user: engineerUser,
      initialSubjects: [rootSubject, departmentSubject],
      initialForms: [formFor(departmentSubject.id)],
    })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /\u9500\u552e\u90e8/ }))
    await openResearchForm(user)
    expect(screen.getByLabelText("核心目标")).toBeEnabled()
    expect(screen.getByRole("button", { name: "保存调研内容" })).toBeVisible()
    expect(screen.queryByRole("button", { name: "保存并确认" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "退回" })).not.toBeInTheDocument()
  })

  it("edits a legacy confirmed form through the canonical save route while preserving its original revision", async () => {
    const confirmed = formFor(departmentSubject.id, {
      current_revision: {
        ...formFor(departmentSubject.id).current_revision!,
        status: "confirmed",
        version: 3,
        answers: [{ field_key: "goal", value: "已确认目标" }],
      },
    })
    const apiRequest = renderProjectResearch({
      initialSubjects: [rootSubject, departmentSubject],
      initialForms: [confirmed],
    })
    const user = userEvent.setup()

    await user.click(await screen.findByRole("treeitem", { name: /\u9500\u552e\u90e8/ }))
    await openResearchForm(user)
    expect(screen.getByLabelText("核心目标")).toBeEnabled()
    expect(screen.getByLabelText("核心目标")).toHaveValue("已确认目标")
    expect(screen.queryByRole("button", { name: "新建修订" })).not.toBeInTheDocument()
    await user.type(screen.getByLabelText("核心目标"), "，后续补充")
    await user.click(screen.getByRole("button", { name: "保存调研内容" }))
    expect(await screen.findByText("调研内容已保存。")).toBeVisible()
    await openResearchForm(user)
    expect(screen.getByLabelText("核心目标")).toHaveValue("已确认目标，后续补充")
    expect(confirmed.current_revision!.answers).toEqual([{ field_key: "goal", value: "已确认目标" }])
    expect(mutationBodies(apiRequest, "/research/forms/form-subject-sales", "PATCH")).toEqual([{ version: 3, answers: { goal: "已确认目标，后续补充" } }])
    expect(mutationBodies(apiRequest, "/research/forms/form-subject-sales/revise", "POST")).toHaveLength(0)
  })

  it("fails closed when the research API returns a malformed DTO", async () => {
    renderProjectResearch({ malformedForms: true })
    expect(await screen.findByRole("alert")).toHaveTextContent("调研数据格式异常")
    expect(screen.queryByText("server internals")).not.toBeInTheDocument()
  })
})

describe("typed research fields", () => {
  it("sends null deletions instead of empty strings for optional date and single-choice answers", async () => {
    const optionalDefinition = {
      ...definition,
      sections: [{
        ...definition.sections[0],
        fields: [
          { ...definition.sections[0].fields[0], id: "due", field_key: "due", name: "日期", type: "date" as const, is_required: false, options: {} },
          { ...definition.sections[0].fields[0], id: "priority", field_key: "priority", name: "优先级", type: "single_choice" as const, is_required: false, options: { choices: ["高", "低"] }, sort_order: 1 },
        ],
      }],
    }
    const optionalForm = formFor(departmentSubject.id, {
      definition_snapshot: optionalDefinition,
      current_revision: {
        ...formFor(departmentSubject.id).current_revision!,
        answers: [{ field_key: "due", value: "2026-08-24" }, { field_key: "priority", value: "高" }],
      },
    })
    const saved = { ...optionalForm, current_revision: { ...optionalForm.current_revision!, version: 2, answers: [] } }
    const apiRequest = vi.fn().mockResolvedValue(saved)
    renderApp(<ResearchForm projectId={projectId} form={optionalForm} canFill apiRequest={apiRequest} onUpdate={vi.fn()} onDirtyChange={vi.fn()} />)
    const user = userEvent.setup()

    await user.clear(screen.getByLabelText("日期"))
    await user.selectOptions(screen.getByLabelText("优先级"), "")
    await user.click(screen.getByRole("button", { name: "保存调研内容" }))

    expect(apiRequest).toHaveBeenCalledWith(expect.any(String), {
      method: "PATCH",
      body: { version: 1, answers: { due: null, priority: null } },
    })
  })

  it("treats cleared table date and choice cells as invalid nulls rather than empty strings", async () => {
    const tableDefinition = {
      ...definition,
      sections: [{ ...definition.sections[0], fields: [{
        ...definition.sections[0].fields[0],
        id: "schedule",
        field_key: "schedule",
        name: "排期表",
        type: "table" as const,
        options: { columns: [
          { key: "due", name: "日期", type: "date" as const, options: {} },
          { key: "priority", name: "优先级", type: "single_choice" as const, options: { choices: ["高", "低"] } },
        ] },
      }] }],
    }
    const tableForm = formFor(departmentSubject.id, {
      definition_snapshot: tableDefinition,
      current_revision: { ...formFor(departmentSubject.id).current_revision!, answers: [{ field_key: "schedule", value: [{ due: "2026-08-24", priority: "高" }] }] },
    })
    const apiRequest = vi.fn()
    renderApp(<ResearchForm projectId={projectId} form={tableForm} canFill apiRequest={apiRequest} onUpdate={vi.fn()} onDirtyChange={vi.fn()} />)
    const user = userEvent.setup()

    await user.clear(screen.getByLabelText("第 1 行 日期"))
    await user.selectOptions(screen.getByLabelText("第 1 行 优先级"), "")
    await user.click(screen.getByRole("button", { name: "保存调研内容" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("排期表格式无效")
    expect(apiRequest).not.toHaveBeenCalled()
  })

  it("sends an explicit null deletion when a persisted number is cleared", async () => {
    const numericDefinition = {
      ...definition,
      sections: [{
        ...definition.sections[0],
        fields: [{ ...definition.sections[0].fields[0], id: "count", field_key: "count", name: "数量", type: "integer" as const, options: {} }],
      }],
    }
    const numericForm = formFor(departmentSubject.id, {
      definition_snapshot: numericDefinition,
      current_revision: {
        ...formFor(departmentSubject.id).current_revision!,
        answers: [{ field_key: "count", value: 42 }],
      },
    })
    const saved = {
      ...numericForm,
      current_revision: { ...numericForm.current_revision!, version: 2, answers: [] },
    }
    const apiRequest = vi.fn().mockResolvedValue(saved)
    renderApp(<ResearchForm projectId={projectId} form={numericForm} canFill apiRequest={apiRequest} onUpdate={vi.fn()} onDirtyChange={vi.fn()} />)
    const user = userEvent.setup()

    await user.clear(screen.getByLabelText("数量"))
    expect(screen.getByText("有未保存修改")).toBeVisible()
    await user.click(screen.getByRole("button", { name: "保存调研内容" }))

    expect(apiRequest).toHaveBeenCalledWith(expect.any(String), {
      method: "PATCH",
      body: { version: 1, answers: { count: null } },
    })
  })

  it("keeps invalid numeric raw text visible and blocks stale-value submission", async () => {
    const numericDefinition = {
      ...definition,
      sections: [{
        ...definition.sections[0],
        fields: [{ ...definition.sections[0].fields[0], id: "amount", field_key: "amount", name: "金额", type: "decimal" as const, options: {} }],
      }],
    }
    const numericForm = formFor(departmentSubject.id, {
      definition_snapshot: numericDefinition,
      current_revision: {
        ...formFor(departmentSubject.id).current_revision!,
        answers: [{ field_key: "amount", value: "12.5" }],
      },
    })
    const apiRequest = vi.fn()
    renderApp(<ResearchForm projectId={projectId} form={numericForm} canFill apiRequest={apiRequest} onUpdate={vi.fn()} onDirtyChange={vi.fn()} />)
    const user = userEvent.setup()

    await user.clear(screen.getByLabelText("金额"))
    await user.type(screen.getByLabelText("金额"), "-")
    expect(screen.getByLabelText("金额")).toHaveValue("-")
    await user.click(screen.getByRole("button", { name: "保存调研内容" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("金额格式无效")
    expect(apiRequest).not.toHaveBeenCalled()
  })

  it("resets invalid numeric raw text when a newer remote revision has the same canonical value", async () => {
    const numericDefinition = {
      ...definition,
      sections: [{ ...definition.sections[0], fields: [{ ...definition.sections[0].fields[0], id: "amount", field_key: "amount", name: "金额", type: "decimal" as const, options: {} }] }],
    }
    const initial = formFor(departmentSubject.id, {
      definition_snapshot: numericDefinition,
      current_revision: { ...formFor(departmentSubject.id).current_revision!, answers: [{ field_key: "amount", value: "12.5" }] },
    })
    const rendered = renderApp(<ResearchForm projectId={projectId} form={initial} canFill apiRequest={vi.fn()} onUpdate={vi.fn()} onDirtyChange={vi.fn()} />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText("金额"), "x")
    expect(screen.getByLabelText("金额")).toHaveValue("12.5x")
    rendered.rerender(<ResearchForm projectId={projectId} form={{
      ...initial,
      current_revision: { ...initial.current_revision!, version: 2, answers: [{ field_key: "amount", value: "12.5" }] },
    }} canFill apiRequest={vi.fn()} onUpdate={vi.fn()} onDirtyChange={vi.fn()} />)

    await waitFor(() => expect(screen.getByLabelText("金额")).toHaveValue("12.5"))
  })

  it("keeps table row identity stable so deleting an invalid equal-valued row cannot contaminate the survivor", async () => {
    const tableDefinition = {
      ...definition,
      sections: [{ ...definition.sections[0], fields: [{
        ...definition.sections[0].fields[0], id: "metrics", field_key: "metrics", name: "数据表", type: "table" as const,
        options: { columns: [{ key: "quantity", name: "数量", type: "integer" as const, options: {} }] },
      }] }],
    }
    const tableForm = formFor(departmentSubject.id, {
      definition_snapshot: tableDefinition,
      current_revision: { ...formFor(departmentSubject.id).current_revision!, answers: [{ field_key: "metrics", value: [{ quantity: 1 }, { quantity: 1 }] }] },
    })
    const saved = { ...tableForm, current_revision: { ...tableForm.current_revision!, version: 2, answers: [{ field_key: "metrics", value: [{ quantity: 1 }] }] } }
    const apiRequest = vi.fn().mockResolvedValue(saved)
    renderApp(<ResearchForm projectId={projectId} form={tableForm} canFill apiRequest={apiRequest} onUpdate={vi.fn()} onDirtyChange={vi.fn()} />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText("第 1 行 数量"), "x")
    expect(screen.getByLabelText("第 1 行 数量")).toHaveValue("1x")
    await user.click(screen.getByRole("button", { name: "删除第 1 行" }))

    expect(screen.getByLabelText("第 1 行 数量")).toHaveValue("1")
    await user.click(screen.getByRole("button", { name: "保存调研内容" }))
    expect(apiRequest).toHaveBeenCalledWith(expect.any(String), {
      method: "PATCH",
      body: { version: 1, answers: { metrics: [{ quantity: 1 }] } },
    })
  })

  it("marks cleared and intermediate table numbers invalid without submitting the old cell", async () => {
    const tableDefinition = {
      ...definition,
      id: "form-table-numeric",
      form_key: "table_numeric",
      sections: [{
        ...definition.sections[0],
        fields: [{
          ...definition.sections[0].fields[0],
          id: "metrics",
          field_key: "metrics",
          name: "数据表",
          type: "table" as const,
          options: { columns: [{ key: "quantity", name: "数量", type: "integer" as const, options: {} }] },
        }],
      }],
    }
    const tableForm = formFor(departmentSubject.id, {
      definition_snapshot: tableDefinition,
      current_revision: {
        ...formFor(departmentSubject.id).current_revision!,
        answers: [{ field_key: "metrics", value: [{ quantity: 9 }] }],
      },
    })
    const apiRequest = vi.fn()
    renderApp(<ResearchForm projectId={projectId} form={tableForm} canFill apiRequest={apiRequest} onUpdate={vi.fn()} onDirtyChange={vi.fn()} />)
    const user = userEvent.setup()

    const cell = screen.getByLabelText("第 1 行 数量")
    await user.clear(cell)
    await user.type(cell, "-")
    expect(cell).toHaveValue("-")
    expect(screen.getByText("有未保存修改")).toBeVisible()
    await user.click(screen.getByRole("button", { name: "保存调研内容" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("数据表格式无效")
    expect(apiRequest).not.toHaveBeenCalled()
  })

  it("normalizes ASCII edge whitespace for local text visibility and emptiness", () => {
    const fields = [
      { ...definition.sections[0].fields[0], id: "mode", field_key: "mode", name: "模式", is_required: true },
      {
        ...definition.sections[0].fields[0],
        id: "detail",
        field_key: "detail",
        name: "详情",
        condition: { field_key: "mode", operator: "equals" as const, value: "ready" },
      },
    ]

    expect(visibleResearchFieldKeys(fields, { mode: "  ready\t" })).toEqual(new Set(["mode", "detail"]))
  })

  it("replaces clean local answers when the same revision is refreshed at a newer version", async () => {
    const initial = formFor(departmentSubject.id, {
      current_revision: {
        ...formFor(departmentSubject.id).current_revision!,
        answers: [{ field_key: "goal", value: "旧答案" }],
      },
    })
    const rendered = renderApp(<ResearchForm projectId={projectId} form={initial} canFill apiRequest={vi.fn()} onUpdate={vi.fn()} onDirtyChange={vi.fn()} />)

    expect(screen.getByLabelText("核心目标")).toHaveValue("旧答案")
    rendered.rerender(<ResearchForm projectId={projectId} form={{
      ...initial,
      current_revision: {
        ...initial.current_revision!,
        version: 2,
        answers: [{ field_key: "goal", value: "远端新答案" }],
      },
    }} canFill apiRequest={vi.fn()} onUpdate={vi.fn()} onDirtyChange={vi.fn()} />)

    await waitFor(() => expect(screen.getByLabelText("核心目标")).toHaveValue("远端新答案"))
  })

  it("keeps the saved notice when its own newer version flows back through props", async () => {
    const initial = formFor(departmentSubject.id, {
      current_revision: {
        ...formFor(departmentSubject.id).current_revision!,
        answers: [{ field_key: "goal", value: "旧答案" }],
      },
    })
    const saved = {
      ...initial,
      current_revision: {
        ...initial.current_revision!,
        version: 2,
        answers: [{ field_key: "goal", value: "自保存答案" }],
      },
    }
    const apiRequest = vi.fn().mockResolvedValue(saved)
    function Harness() {
      const [form, setForm] = React.useState(initial)
      return <ResearchForm projectId={projectId} form={form} canFill apiRequest={apiRequest} onUpdate={setForm} onDirtyChange={vi.fn()} />
    }
    renderApp(<Harness />)
    const user = userEvent.setup()

    await user.clear(screen.getByLabelText("核心目标"))
    await user.type(screen.getByLabelText("核心目标"), "自保存答案")
    await user.click(screen.getByRole("button", { name: "保存调研内容" }))

    expect(await screen.findByText("调研内容已保存。")).toBeVisible()
    expect(screen.getByLabelText("核心目标")).toHaveValue("自保存答案")
  })

  it("counts only visible answered fields in completion without enforcing legacy required flags", async () => {
    const conditionalDefinition = {
      ...definition,
      id: "form-conditional",
      form_key: "conditional",
      sections: [{
        ...definition.sections[0],
        fields: [
          {
            ...definition.sections[0].fields[0],
            id: "field-enabled",
            field_key: "enabled",
            name: "是否启用",
            type: "single_choice" as const,
            options: { choices: ["是", "否"] },
          },
          {
            ...definition.sections[0].fields[0],
            id: "field-context",
            field_key: "context",
            name: "背景备注",
            type: "short_text" as const,
            is_required: false,
            sort_order: 1,
          },
          {
            ...definition.sections[0].fields[0],
            id: "field-conditional-goal",
            field_key: "conditional_goal",
            name: "条件目标",
            sort_order: 2,
            condition: {
              operator: "all" as const,
              conditions: [
                { field_key: "enabled", operator: "equals" as const, value: "是" },
                { operator: "any" as const, conditions: [{ field_key: "context", operator: "is_empty" as const }] },
              ],
            },
          },
        ],
      }],
    }
    const conditionalForm = formFor(departmentSubject.id, {
      id: "form-conditional-runtime",
      form_key: "conditional",
      definition_snapshot: conditionalDefinition,
      completion: { ...formFor(departmentSubject.id).completion, visible_total: 2 },
    })
    renderApp(<ResearchForm projectId={projectId} form={conditionalForm} canFill apiRequest={vi.fn()} onUpdate={vi.fn()} onDirtyChange={vi.fn()} />)
    const user = userEvent.setup()

    expect(screen.queryByLabelText("条件目标")).not.toBeInTheDocument()
    expect(screen.getByLabelText("表单完成度")).toHaveTextContent("已填写 0/2")
    await user.selectOptions(screen.getByLabelText("是否启用"), "是")
    expect(screen.getByLabelText("条件目标")).toBeVisible()
    expect(screen.getByLabelText("表单完成度")).toHaveTextContent("已填写 1/3")
    expect(screen.getByLabelText("条件目标")).not.toBeRequired()
  })

  it("renders all ten safe field controls and emits canonical values", async () => {
    const changes: Record<string, ResearchAnswerValue> = {}
    const fields = [
      { ...definition.sections[0].fields[0], id: "short", field_key: "short", name: "短文本", type: "short_text" as const },
      { ...definition.sections[0].fields[0], id: "long", field_key: "long", name: "长文本", type: "long_text" as const },
      { ...definition.sections[0].fields[0], id: "rich", field_key: "rich", name: "富文本", type: "rich_text" as const, options: {} },
      { ...definition.sections[0].fields[0], id: "integer", field_key: "integer", name: "整数", type: "integer" as const, options: {} },
      { ...definition.sections[0].fields[0], id: "decimal", field_key: "decimal", name: "小数", type: "decimal" as const, options: {} },
      { ...definition.sections[0].fields[0], id: "date", field_key: "date", name: "日期", type: "date" as const, options: {} },
      { ...definition.sections[0].fields[0], id: "single", field_key: "single", name: "单选", type: "single_choice" as const, options: { choices: ["是", "否"] } },
      { ...definition.sections[0].fields[0], id: "multi", field_key: "multi", name: "多选", type: "multi_choice" as const, options: { choices: ["A", "B"] } },
      { ...definition.sections[0].fields[0], id: "table", field_key: "table", name: "表格", type: "table" as const, options: { columns: [{ key: "count", name: "数量", type: "integer" as const, options: {} }] } },
      { ...definition.sections[0].fields[0], id: "files", field_key: "files", name: "文件引用", type: "file_reference" as const, options: { max_files: 2 } },
    ]
    function TypedFieldHarness() {
      const [values, setValues] = React.useState<Record<string, ResearchAnswerValue>>({})
      const request = vi.fn().mockResolvedValue({ items: [{ id: "file-123", project_id: projectId, display_name: "脱敏样本数据", category: "attachment", status: "active", current_version_id: "version-1", current_version: { id: "version-1", version_number: 1, status: "available", scan_status: "clean", original_filename: "sample.xlsx" }, created_by: null }] })
      return <div>{fields.map((field) => <ResearchField key={field.field_key} definition={field} value={values[field.field_key]} projectId={projectId} apiRequest={request} onChange={(value) => { changes[field.field_key] = value; setValues((current) => ({ ...current, [field.field_key]: value })) }} disabled={false} />)}</div>
    }
    renderApp(<TypedFieldHarness />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText("富文本"), "第一段\n第二段")
    await user.type(screen.getByLabelText("整数"), "0042")
    await user.type(screen.getByLabelText("小数"), "01.2300")
    await user.type(screen.getByLabelText("日期"), "2026-08-24")
    await user.selectOptions(screen.getByLabelText("单选"), "是")
    await user.click(screen.getByRole("checkbox", { name: "A" }))
    await user.click(screen.getByRole("button", { name: "为表格新增一行" }))
    await user.type(screen.getByLabelText("第 1 行 数量"), "3")
    await user.click(screen.getByRole("button", { name: "添加附件引用" }))
    await user.click(await screen.findByRole("checkbox", { name: /脱敏样本数据/ }))
    await user.click(screen.getByRole("button", { name: "确认关联（1）" }))

    expect(changes.rich).toEqual({
      type: "doc",
      content: [
        { type: "paragraph", content: [{ type: "text", text: "第一段" }] },
        { type: "paragraph", content: [{ type: "text", text: "第二段" }] },
      ],
    })
    expect(changes.integer).toBe(42)
    expect(changes.decimal).toBe("1.23")
    expect(changes.date).toBe("2026-08-24")
    expect(changes.single).toBe("是")
    expect(changes.multi).toEqual(["A"])
    expect(changes.table).toEqual([{ count: 3 }])
    expect(changes.files).toEqual(["file-123"])
    expect(screen.getByLabelText("文件引用（可关联文件库文件）")).toHaveValue("已关联 1 个文件")
    expect(screen.queryByRole("textbox", { name: /HTML/ })).not.toBeInTheDocument()
  })
})
