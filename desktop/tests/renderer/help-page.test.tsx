// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, expect, it, vi } from "vitest"

import { HelpPage } from "../../src/renderer/src/help/HelpPage"

afterEach(() => {
  cleanup()
})

it("lists every workbench module, the gate flow and the failure checklist", async () => {
  render(<HelpPage />)

  expect(await screen.findByRole("heading", { name: "使用帮助" })).toBeVisible()
  for (const section of [
    "开始前：三件必查的事",
    "角色与权限",
    "项目工作台",
    "工作流与术语表",
    "门禁 G1–G9（最常卡住的地方）",
    "报价收款",
    "集成桥",
    "任务中心",
    "AI Server 对话与扩展",
    "管理页（仅管理员）",
    "故障排查（照顺序查最快）",
  ]) {
    expect(screen.getByRole("heading", { name: section })).toBeVisible()
  }

  // G1–G9 全在门禁表里，且带清单内容
  expect(screen.getByText("certutil -hashfile 文件名 SHA256")).toBeVisible()
  expect(
    screen.getByText("生产环境、Runbook、Go-Live 单、演练记录、SOW-C 里程碑（末款绑 G9，可 conditional_pass）"),
  ).toBeVisible()
  // 门禁故障首因写的是登录态，不是服务坏
  expect(screen.getByText(/全部显示未提交 \/ 提交后转圈又回去/)).toBeVisible()
  // 工作流 run 七态在册（T-W6 控制台）
  expect(screen.getByText(/排队中\/运行中\/等待审批\/已暂停\/成功\/失败\/已取消/)).toBeVisible()
  // 变更集评审的验收分离语义在册
  expect(screen.getByText(/拍板人≠提交人/)).toBeVisible()
})

it("carries the somwyn walkthrough with concrete paths and privacy rules", async () => {
  render(<HelpPage />)

  expect(
    await screen.findByRole("heading", { name: "实操示例：证据文件怎么写（somwyn 样板）" }),
  ).toBeVisible()
  // 具体到这台机器的路径与工具
  expect(screen.getByText(/somwyn 项目已建好 30 件样板/)).toBeVisible()
  expect(screen.getByText("哈希清单.ps1")).toBeVisible()
  expect(screen.getByText("不用新写")).toBeVisible()
  // 隐私铁律：.fde 仓库永不加远程
  expect(screen.getByText(/永不配置远程/)).toBeVisible()
})

it("jumps to a section from the table of contents without navigating away", async () => {
  const user = userEvent.setup()
  // jsdom 没有 scrollIntoView——补一个 spy 既防真实滚动也验证跳转；
  // 测试文件级 jsdom 环境用完即弃，无需还原原型
  const scrollSpy = vi.fn()
  Object.assign(HTMLElement.prototype, { scrollIntoView: scrollSpy })

  render(<HelpPage />)

  const toc = screen.getByRole("navigation", { name: "目录" })

  // 按名称选目录按钮（不锁死索引——章节增减不应改坏测试）
  const troubleshootBtn = [...toc.querySelectorAll("button")].find(
    (button) => button.textContent === "故障排查（照顺序查最快）",
  )
  expect(troubleshootBtn).toBeTruthy()
  await user.click(troubleshootBtn!)
  expect(scrollSpy).toHaveBeenCalledTimes(1)
  expect(scrollSpy).toHaveBeenCalledWith({ behavior: "smooth", block: "start" })
  // 目录按钮不碰 hash（路由解析器不受影响）
  expect(window.location.hash).toBe("")
})

it("keeps known gaps honest — no invented features", () => {
  render(<HelpPage />)
  expect(screen.getByText("调研表 confirm / reject / revise 三态流转——暂无前端入口。")).toBeVisible()
  expect(
    screen.getByText("工作流定义的新建/发布——暂无人工 UI 入口（控制台只读呈现 + 运行控制）。"),
  ).toBeVisible()
})
