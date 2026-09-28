// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"
import React from "react"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { OpportunityAdjustment } from "../../src/renderer/src/research/OpportunityAdjustment"
import type { ResearchSubjectDto } from "../../src/renderer/src/research/types"
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", "") }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open") }
})
afterEach(cleanup)
const opportunity = { id: "opp", name: "原机会", version: 7 } as ResearchSubjectDto
const proposal = { name: "新标题", description: "新说明", target_audience: "工程师", next_action: "验证" }
it("previews without writing and saves only the existing opportunity with its version", async () => {
  const api = vi.fn().mockResolvedValueOnce({ subject_id: "opp", version: 7, proposal }).mockResolvedValueOnce({ ...opportunity, name: "新标题", version: 8 })
  const saved = vi.fn(); const close = vi.fn(); const user = userEvent.setup()
  render(<OpportunityAdjustment projectId="project" opportunity={opportunity} apiRequest={api} onSaved={saved} onClose={close} />)
  expect(screen.getByRole("button", { name: "生成调整建议" })).toBeDisabled()
  await user.type(screen.getByLabelText("调整要求"), "缩小范围")
  await user.click(screen.getByRole("button", { name: "生成调整建议" }))
  expect(await screen.findByDisplayValue("新标题")).toBeInTheDocument()
  expect(api).toHaveBeenCalledTimes(1)
  await user.click(screen.getByRole("button", { name: "确认保存到原机会" }))
  await waitFor(() => expect(saved).toHaveBeenCalled())
  expect(api).toHaveBeenLastCalledWith("/api/v1/projects/project/research/subjects/opp", { method: "PATCH", body: { version: 7, name: "新标题", description: "新说明", opportunity_profile: { target_audience: "工程师", next_action: "验证" } } })
  expect(close).toHaveBeenCalledOnce()
})
it("cancels without writing", async () => {
  const api = vi.fn(); const close = vi.fn()
  render(<OpportunityAdjustment projectId="project" opportunity={opportunity} apiRequest={api} onSaved={vi.fn()} onClose={close} />)
  await userEvent.click(screen.getByRole("button", { name: "取消" }))
  expect(api).not.toHaveBeenCalled(); expect(close).toHaveBeenCalledOnce()
})
