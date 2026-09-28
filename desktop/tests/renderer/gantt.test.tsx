// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import { GanttChart } from "../../src/renderer/src/projects/GanttChart"
import type { ProjectGanttDto } from "../../src/renderer/src/workbench/types"

const ganttFixture: ProjectGanttDto = {
  project_id: "project-xinghe",
  range: { start: "2026-08-21", end: "2026-08-24" },
  groups: [{
    id: "module-pov",
    module_key: "pov",
    name: "PoV 验证",
    status: "active",
    cancelled: false,
    tasks: [{
      id: "task-prepare",
      task_key: "prepare_data",
      name: "准备数据",
      planned_start_date: "2026-08-21",
      planned_end_date: "2026-08-24",
      assignee: null,
      progress: 50,
      status: "in_progress",
      cancelled: false,
      dependency_ids: [],
      dependency_risk: false,
      incomplete_dependency_ids: [],
    }],
  }],
}

afterEach(cleanup)

describe("GanttChart", () => {
  it("draws predecessor arrows and names dependencies accessibly", () => {
    const predecessor = ganttFixture.groups[0].tasks[0]
    const successor = {
      ...predecessor,
      id: "task-review",
      task_key: "review_data",
      name: "复核数据",
      dependency_ids: [predecessor.id],
      incomplete_dependency_ids: [predecessor.id],
      dependency_risk: true,
    }

    render(<GanttChart data={{ ...ganttFixture, groups: [{ ...ganttFixture.groups[0], tasks: [predecessor, successor] }] }} />)

    expect(screen.getByTestId("gantt-dependency-layer")).toBeVisible()
    expect(document.querySelector('[data-dependency-from="task-prepare"][data-dependency-to="task-review"]')).not.toBeNull()
    expect(document.querySelector('[data-dependency-from="task-prepare"][data-dependency-to="task-review"]')).toHaveAttribute("data-risk", "true")
    expect(screen.getByRole("img", { name: /复核数据.*前置任务：准备数据.*依赖风险/ })).toBeVisible()
  })

  it("renders weekday bars from the API range and labels progress accessibly", () => {
    render(<GanttChart data={ganttFixture} />)

    const bar = screen.getByRole("img", { name: "准备数据，2026-08-21 至 2026-08-24，进度 50%" })
    expect(bar).toHaveStyle({ gridColumn: "1 / span 2" })
    const timeline = screen.getByRole("region", { name: "工作日甘特图" })
    expect(within(timeline).getByText("08-21")).toBeVisible()
    expect(within(timeline).getByText("08-24")).toBeVisible()
    expect(within(timeline).queryByText("08-22")).not.toBeInTheDocument()
  })

  it("announces dependency risk and summarizes cancelled tasks outside the active timeline", () => {
    const data: ProjectGanttDto = {
      ...ganttFixture,
      groups: [{
        ...ganttFixture.groups[0],
        tasks: [{ ...ganttFixture.groups[0].tasks[0], cancelled: true, status: "cancelled" }, {
          ...ganttFixture.groups[0].tasks[0],
          id: "task-risk",
          name: "风险任务",
          dependency_risk: true,
        }],
      }],
    }
    render(<GanttChart data={data} />)

    expect(screen.queryByRole("img", { name: /准备数据/ })).not.toBeInTheDocument()
    expect(screen.getByRole("img", { name: /风险任务.*依赖风险/ })).toHaveClass("dependency-risk")
    const cancelled = screen.getByRole("region", { name: "已取消任务（不在活动时间轴）" })
    expect(within(cancelled).getByText(/准备数据.*2026-08-21 至 2026-08-24/)).toBeVisible()
  })

  it("keeps an all-cancelled project informative when the active API range is empty", () => {
    render(<GanttChart data={{
      project_id: "cancelled",
      range: { start: null, end: null },
      groups: [{
        ...ganttFixture.groups[0],
        status: "cancelled",
        cancelled: true,
        tasks: [{ ...ganttFixture.groups[0].tasks[0], status: "cancelled", cancelled: true }],
      }],
    }} />)

    expect(screen.getByText("暂无活动排期。")).toBeVisible()
    expect(screen.getByText("PoV 验证（已取消）")).toBeVisible()
    expect(screen.getByRole("region", { name: "已取消任务（不在活动时间轴）" })).toBeVisible()
  })

  it("does not place an active out-of-range task in the first date column", () => {
    render(<GanttChart data={{
      ...ganttFixture,
      groups: [{
        ...ganttFixture.groups[0],
        tasks: [{ ...ganttFixture.groups[0].tasks[0], planned_start_date: "2026-08-10", planned_end_date: "2026-08-11" }],
      }],
    }} />)

    expect(screen.queryByRole("img", { name: /准备数据/ })).not.toBeInTheDocument()
    expect(screen.getByText("排期超出当前时间轴：2026-08-10 至 2026-08-11")).toBeVisible()
  })

  it("shows an empty state when the API range is empty", () => {
    render(<GanttChart data={{ project_id: "empty", range: { start: null, end: null }, groups: [] }} />)
    expect(screen.getByText("暂无可排期的任务。")).toBeVisible()
  })
})
