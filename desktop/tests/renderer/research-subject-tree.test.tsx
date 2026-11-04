// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ResearchSubjectTree } from "../../src/renderer/src/research/ResearchSubjectTree"
import type { ResearchSubjectDto, ResearchSubjectType } from "../../src/renderer/src/research/types"

afterEach(cleanup)

describe("research subject tree rename actions", () => {
  it("expands only the first level by default and preserves manual collapse", async () => {
    const subjects = [
      subject("project", "project", null, "示例企业"),
      subject("department", "department", "project", "销售部"),
      subject("role", "role", "department", "销售经理"),
    ]
    render(<ResearchSubjectTree subjects={subjects} selectedId="project" canFill onSelect={vi.fn()} onCreate={vi.fn()} onRename={vi.fn()} onArchive={vi.fn()} />)
    const user = userEvent.setup()

    expect(screen.getByRole("treeitem", { name: /销售部/ })).toBeVisible()
    expect(screen.queryByRole("treeitem", { name: /销售经理/ })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "收起示例企业的下级" }))
    expect(screen.queryByRole("treeitem", { name: /销售部/ })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "展开示例企业的下级" }))
    expect(screen.getByRole("treeitem", { name: /销售部/ })).toBeVisible()
    expect(screen.queryByRole("treeitem", { name: /销售经理/ })).not.toBeInTheDocument()
  })

  it("offers rename actions for departments, roles and processes only", async () => {
    const onRename = vi.fn()
    const subjects = [
      subject("project", "project", null, "示例企业"),
      subject("department", "department", "project", "销售部"),
      subject("role", "role", "department", "销售经理"),
      subject("process", "process", "role", "报价流程"),
    ]
    render(<ResearchSubjectTree subjects={subjects} selectedId="department" canFill onSelect={vi.fn()} onCreate={vi.fn()} onRename={onRename} onArchive={vi.fn()} />)
    const user = userEvent.setup()

    expect(screen.queryByRole("button", { name: "编辑企业：示例企业" })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "编辑部门：销售部" }))
    await user.click(screen.getByRole("button", { name: "展开销售部的下级" }))
    await user.click(screen.getByRole("button", { name: "编辑岗位：销售经理" }))
    await user.click(screen.getByRole("button", { name: "展开销售经理的下级" }))
    await user.click(screen.getByRole("button", { name: "编辑流程：报价流程" }))

    expect(onRename.mock.calls.map(([item]) => item.id)).toEqual(["department", "role", "process"])
  })

  it("hides rename actions from read-only users", () => {
    const subjects = [subject("project", "project", null, "示例企业"), subject("department", "department", "project", "销售部")]
    render(<ResearchSubjectTree subjects={subjects} selectedId="department" canFill={false} onSelect={vi.fn()} onCreate={vi.fn()} onRename={vi.fn()} onArchive={vi.fn()} />)
    expect(screen.queryByRole("button", { name: "编辑部门：销售部" })).not.toBeInTheDocument()
  })
})

describe("research subject tree merge and archived rows", () => {
  it("offers the merge action for the selected non-root subject only", async () => {
    const onMerge = vi.fn()
    const subjects = [subject("project", "project", null, "示例企业"), subject("department", "department", "project", "销售部")]
    render(<ResearchSubjectTree subjects={subjects} selectedId="department" canFill onSelect={vi.fn()} onCreate={vi.fn()} onRename={vi.fn()} onArchive={vi.fn()} onMerge={onMerge} />)
    const user = userEvent.setup()
    expect(screen.queryByRole("button", { name: "合并示例企业" })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "合并销售部" }))
    expect(onMerge.mock.calls.map(([item]) => item.id)).toEqual(["department"])
  })

  it("hides the merge action without a handler or write access", () => {
    const subjects = [subject("project", "project", null, "示例企业"), subject("department", "department", "project", "销售部")]
    const first = render(<ResearchSubjectTree subjects={subjects} selectedId="department" canFill onSelect={vi.fn()} onCreate={vi.fn()} onRename={vi.fn()} onArchive={vi.fn()} />)
    expect(screen.queryByRole("button", { name: "合并销售部" })).not.toBeInTheDocument()
    first.unmount()
    render(<ResearchSubjectTree subjects={subjects} selectedId="department" canFill={false} onSelect={vi.fn()} onCreate={vi.fn()} onRename={vi.fn()} onArchive={vi.fn()} onMerge={vi.fn()} />)
    expect(screen.queryByRole("button", { name: "合并销售部" })).not.toBeInTheDocument()
  })

  it("collapses archived rows and links merged rows back to their target", async () => {
    const onSelect = vi.fn()
    const merged = { ...subject("archived-sales", "department", "project", "旧销售部"), status: "archived" as const, merged_into_subject_id: "department" }
    const plain = { ...subject("archived-role", "role", "department", "旧岗位"), status: "archived" as const }
    const subjects = [
      subject("project", "project", null, "示例企业"),
      subject("department", "department", "project", "销售部"),
      merged,
      plain,
    ]
    render(<ResearchSubjectTree subjects={subjects} selectedId="project" canFill onSelect={onSelect} onCreate={vi.fn()} onRename={vi.fn()} onArchive={vi.fn()} onMerge={vi.fn()} />)
    const user = userEvent.setup()

    expect(screen.queryByText("旧销售部")).not.toBeInTheDocument()
    expect(screen.queryByRole("treeitem", { name: /旧销售部/ })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "已归档（2）" }))
    expect(screen.getByText("旧销售部")).toBeVisible()
    expect(screen.getByText("旧岗位")).toBeVisible()
    expect(screen.queryByRole("button", { name: "已并入 旧岗位" })).not.toBeInTheDocument()
    const backlink = screen.getByRole("button", { name: "已并入 销售部" })
    await user.click(backlink)
    expect(onSelect.mock.calls.map(([item]) => item.id)).toEqual(["department"])
  })
})

function subject(id: string, type: ResearchSubjectType, parentId: string | null, name: string): ResearchSubjectDto {
  return {
    id,
    project_id: "project-1",
    parent_subject_id: parentId,
    subject_type: type,
    subject_key: id,
    name,
    description: "",
    sort_order: 0,
    status: "active",
    tracking_code: null,
    version: 1,
    links: [],
  }
}
