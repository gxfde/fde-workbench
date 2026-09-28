// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { act, cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AIExecutionPanel, type AIExecutionDto } from "../../src/renderer/src/ai/AIExecutionProvider"

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe("AI execution panel", () => {
  it("updates the elapsed time every second while an execution is running", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-08-31T00:00:00.000Z"))
    const execution: AIExecutionDto = {
      id: "execution-12345678",
      operation: "presurvey",
      status: "running",
      stage: "AI 正在分析预调研表",
      result: null,
      error: null,
      events: [],
      next_offset: 0,
      created_at: "2026-08-31T00:00:00.000Z",
      updated_at: "2026-08-31T00:00:00.000Z",
    }

    render(<AIExecutionPanel title="AI 正在分析预调研表" execution={execution} onClose={() => undefined} />)
    expect(screen.queryByRole("button", { name: "最小化" })).not.toBeInTheDocument()
    expect(screen.getByText("已执行 0 秒")).toBeVisible()

    act(() => { vi.advanceTimersByTime(2_100) })
    expect(screen.getByText("已执行 2 秒")).toBeVisible()
  })
})
