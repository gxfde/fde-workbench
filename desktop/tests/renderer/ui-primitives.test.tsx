// @vitest-environment jsdom
// S2 守卫：UI 原语与反馈一致性的行为契约。
// 覆盖：ConfirmProvider 取代原生 confirm、Toast 的 role 语义、Loading 的 role=status、
// 侧栏四组分组结构、统一错误码表。
import "@testing-library/jest-dom/vitest"

import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ConfirmProvider, useConfirm } from "../../src/renderer/src/common/ConfirmProvider"
import { ToastProvider, showToast, useToast } from "../../src/renderer/src/components/ui"
import { Loading } from "../../src/renderer/src/components/ui"
import { errorMessage, commonErrorMessage } from "../../src/renderer/src/common/errorMessages"
import { ApiClientError } from "../../src/renderer/src/api/client"

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function ConfirmHost({ onResult }: { onResult: (value: boolean) => void }) {
  const confirm = useConfirm()
  return (
    <button
      type="button"
      onClick={() => {
        void confirm({ title: "删除对话", description: "删除后无法恢复。", confirmLabel: "删除" })
          .then(onResult)
      }}
    >
      触发确认
    </button>
  )
}

describe("S2 · ConfirmProvider 统一确认通道", () => {
  it("以统一 Modal 呈现确认，确认后 resolve true", async () => {
    const onResult = vi.fn()
    render(
      <ConfirmProvider>
        <ConfirmHost onResult={onResult} />
      </ConfirmProvider>,
    )
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "触发确认" }))

    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveAttribute("aria-modal", "true")
    expect(screen.getByText("删除对话")).toBeInTheDocument()
    expect(screen.getByText("删除后无法恢复。")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "删除" }))
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(true))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  })

  it("取消时 resolve false", async () => {
    const onResult = vi.fn()
    render(
      <ConfirmProvider>
        <ConfirmHost onResult={onResult} />
      </ConfirmProvider>,
    )
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "触发确认" }))
    await user.click(await screen.findByRole("button", { name: "取消" }))
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(false))
  })
})

function ToastHost() {
  const toast = useToast()
  return (
    <>
      <button type="button" onClick={() => toast.success("已保存")}>成功</button>
      <button type="button" onClick={() => toast.error("保存失败")}>失败</button>
    </>
  )
}

describe("S2 · Toast 回执语义", () => {
  it("success 用 role=status，error 用 role=alert", async () => {
    render(
      <ToastProvider>
        <ToastHost />
      </ToastProvider>,
    )
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "成功" }))
    expect(await screen.findByText("已保存")).toHaveAttribute("role", "status")

    await user.click(screen.getByRole("button", { name: "失败" }))
    expect(await screen.findByText("保存失败")).toHaveAttribute("role", "alert")
  })

  it("模块级 showToast 在 Provider 挂载后可用", async () => {
    render(
      <ToastProvider>
        <span />
      </ToastProvider>,
    )
    showToast("后台提示", "warning")
    expect(await screen.findByText("后台提示")).toHaveAttribute("role", "alert")
  })
})

describe("S2 · Loading 与统一错误码表", () => {
  it("Loading 统一为 role=status", () => {
    render(<Loading label="正在加载项目…" />)
    expect(screen.getByRole("status")).toHaveTextContent("正在加载项目…")
  })

  it("公共错误码跨页得到同一句文案", () => {
    const forbidden = new ApiClientError({ code: "forbidden", message: "server raw" })
    const stale = new ApiClientError({ code: "stale_version", message: "server raw" })
    expect(errorMessage(forbidden, "页面兜底")).toBe("当前账号无权执行此操作。")
    expect(errorMessage(stale, "页面兜底")).toBe("内容已被其他操作更新；本地状态未改变，请刷新后重试。")
    // 未收录的业务专属码：保留页面兜底
    const custom = new ApiClientError({ code: "module_already_exists", message: "server raw" })
    expect(errorMessage(custom, "页面兜底")).toBe("页面兜底")
    // 非服务端错误：走页面兜底
    expect(errorMessage(new Error("boom"), "页面兜底")).toBe("页面兜底")
  })

  it("commonErrorMessage 只查公共表，未命中返回空串交回页面", () => {
    const stale = new ApiClientError({ code: "stale_version", message: "server raw" })
    expect(commonErrorMessage(stale, "")).toBe("内容已被其他操作更新；本地状态未改变，请刷新后重试。")
    // 未收录码返回 fallback（本例为空串），由页面自己的映射表决定
    expect(commonErrorMessage(new ApiClientError({ code: "ai_rate_limited", message: "x" }), "")).toBe("")
    // 非服务端错误
    expect(commonErrorMessage(new Error("boom"), "")).toBe("")
  })

  it("页面专属措辞不被公共表覆盖（AI 机会的 stale_version 保留本地口径）", async () => {
    const { opportunityProfileErrorMessage } = await import(
      "../../src/renderer/src/research/ResearchOpportunity"
    )
    const stale = new ApiClientError({ code: "stale_version", message: "server raw" })
    expect(opportunityProfileErrorMessage(stale)).toBe("AI 机会已被其他人更新，请刷新后重试。")
  })
})
