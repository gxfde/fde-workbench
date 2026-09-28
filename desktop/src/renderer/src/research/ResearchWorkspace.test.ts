import { describe, expect, it } from "vitest"

import { opportunitiesForSelectedSubject } from "./ResearchWorkspace"
import type { ResearchSubjectDto, ResearchSubjectType } from "./types"

function subject(id: string, type: ResearchSubjectType, parentId: string | null): ResearchSubjectDto {
  return {
    id,
    project_id: "project-1",
    parent_subject_id: parentId,
    subject_type: type,
    subject_key: id,
    name: id,
    description: "",
    sort_order: 0,
    status: "active",
    tracking_code: null,
    version: 1,
    links: [],
  }
}

describe("opportunitiesForSelectedSubject", () => {
  it("returns only opportunities directly attached to the selected object", () => {
    const subjects = [
      subject("project", "project", null),
      subject("sales", "department", "project"),
      subject("role", "role", "sales"),
      subject("project-opportunity", "opportunity", "project"),
      subject("sales-opportunity", "opportunity", "sales"),
      subject("role-opportunity", "opportunity", "role"),
    ]

    expect(opportunitiesForSelectedSubject(subjects, "sales").map((item) => item.id))
      .toEqual(["sales-opportunity"])
    expect(opportunitiesForSelectedSubject(subjects, "project").map((item) => item.id))
      .toEqual(["project-opportunity"])
  })
})
