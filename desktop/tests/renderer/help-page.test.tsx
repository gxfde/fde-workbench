// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, render, screen, within } from "@testing-library/react"
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
    "新手上路：5 分钟跑通第一个项目",
    "开始前：三件必查的事",
    "角色与权限：为什么某个按钮不见了",
    "项目工作台",
    "门禁 G1–G9（最常卡住的地方）",
    "实操示例：证据文件怎么准备（somwyn 样板）",
    "报价收款与合同",
    "工作流",
    "术语表与变更集评审",
    "执行事实（只读）",
    "集成桥",
    "任务中心",
    "AI Server 对话与扩展",
    "管理页（仅管理员）",
    "故障排查（照顺序查最快）",
  ]) {
    expect(screen.getByRole("heading", { name: section })).toBeVisible()
  }

  // G1–G9 全在门禁表里，且带清单内容
  expect(screen.getAllByText("certutil -hashfile 文件名 SHA256").length).toBeGreaterThan(0)
  expect(
    screen.getByText("生产环境、Runbook、Go-Live 单、演练记录、SOW-C 里程碑（40/40/20，末款绑 G9）"),
  ).toBeVisible()
  // 门禁故障首因写的是登录态，不是服务坏（文案跨 <strong> 拆节点，用容器文本断言）
  const { container: gateContainer } = render(<HelpPage />)
  const gateText = gateContainer.textContent ?? ""
  expect(gateText).toContain("401")
  expect(gateText).toContain("认证问题")
  expect(gateText).toContain("退出登录")
  // 工作流 run 七态在册（T-W6 控制台）
  expect(gateText).toContain("排队中")
  for (const runState of ["运行中", "等待审批", "已暂停", "成功", "失败", "已取消"]) {
    expect(gateText).toContain(runState)
  }
  // 变更集评审的验收分离语义在册
  expect(gateText).toContain("拍板人不能是提交人")
})

it("carries the somwyn walkthrough with concrete paths and privacy rules", async () => {
  render(<HelpPage />)

  expect(
    await screen.findByRole("heading", { name: "实操示例：证据文件怎么准备（somwyn 样板）" }),
  ).toBeVisible()
  // 具体到这台机器的路径与工具（somwyn 出现在标题与目录按钮多处 → 用容器文本断言）
  const { container: walkContainer } = render(<HelpPage />)
  const walkText = walkContainer.textContent ?? ""
  expect(walkText).toContain("somwyn")
  expect(walkText).toContain("哈希清单.ps1")
  expect(walkText).toContain("不用新写")
  // 隐私铁律：.fde 仓库永不加远程（正则会同时命中「永不配置远程」与「永不配置远程仓库」→ 用容器文本）
  expect(walkText).toContain("永不配置远程")
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
  expect(
    screen.getByText("自动任务创建——暂无前端入口，只能执行已有任务。"),
  ).toBeVisible()
  expect(
    screen.getByText("工作流定义的新建与发布——暂无人工 UI 入口（控制台只读呈现 + 运行控制）。"),
  ).toBeVisible()
})

// 守卫：帮助页是「用户唯一能看到的操作文档」，一旦文案与实现脱节，
// 用户会照着错文案操作并把问题归因到工作台本身。以下断言把文案钉在代码事实上。
it("keeps the tab count in sync with the real project detail tabs", () => {
  render(<HelpPage />)
  // ProjectDetailPage.tsx 的 tabs 定义为 12 项（含「执行事实」）
  // 必须精确等于 12——写成 getAllByText(...).length > 0 时，把「12」改成「11」也能通过，
  // 属守卫形同虚设（变异测试实测）。此处断言具体数值，与 ProjectDetailPage.tsx 的 tabs 长度对齐。
  expect(screen.getAllByText(/12 个标签页/).length).toBeGreaterThan(0)
  expect(screen.queryByText(/11 个标签页/)).toBeNull()
  expect(screen.queryByText(/10 个标签页/)).toBeNull()
  // 全部 12 个标签名都在册（表格首列为行头，用 getByRole("cell") 逐个定位）
  const { container } = render(<HelpPage />)
  const tabTable = [...container.querySelectorAll("table")].find((t) =>
    t.textContent?.includes("执行事实"),
  )
  expect(tabTable).toBeTruthy()
  for (const label of [
    "概览",
    "任务",
    "门禁",
    "报价收款",
    "调研",
    "方案设计",
    "工作流",
    "术语表",
    "执行事实",
    "文件库",
    "项目管理",
  ]) {
    expect(within(tabTable as HTMLElement).getByRole("cell", { name: label })).toBeVisible()
  }
})

it("states the gate five states and keeps conditional_pass scoped to G9", () => {
  render(<HelpPage />)
  for (const state of ["待证据", "待核验", "已过门", "有条件通过", "未过门"]) {
    expect(screen.getByRole("cell", { name: state })).toBeVisible()
  }

  // conditional_pass 只有 G9 能选（服务端 gate_service.py 会对非 G9 报 400）
  // 用容器文本断言（文案跨多个 <strong>/文本节点，正则跨节点匹配不可靠）
  const { container } = render(<HelpPage />)
  const text = container.textContent ?? ""
  expect(text).toContain("conditional_pass")
  expect(text).toContain("只有 G9 能选")
  expect(text).toContain("G8 过门时")
  expect(text).toContain("必须书面拍板")
})

it("gives every operational section the five required blocks", () => {
  const { container } = render(<HelpPage />)
  const text = container.textContent ?? ""

  // 五要素中的关键锚点必须成规模出现，避免某节漏写「前置条件」或「预期结果」
  expect((text.match(/适用场景/g) ?? []).length).toBeGreaterThanOrEqual(8)
  expect((text.match(/前置条件/g) ?? []).length).toBeGreaterThanOrEqual(8)
  expect((text.match(/预期结果/g) ?? []).length).toBeGreaterThanOrEqual(8)
  expect((text.match(/常见问题/g) ?? []).length).toBeGreaterThanOrEqual(6)
})
