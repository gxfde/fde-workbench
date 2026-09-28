// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest"

import React from "react"
import { cleanup, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { App } from "../../src/renderer/src/App"
import { parseHashRoute } from "../../src/renderer/src/routing/useHashRoute"
import type { UserDto } from "../../src/shared/contracts"
import {
  adminUser,
  authResult,
  bridge,
  installBridge,
  ok,
  renderApp,
} from "./test-utils"

afterEach(() => {
  cleanup()
  location.hash = ""
})

function userFor(role: UserDto["role"]): UserDto {
  return {
    ...adminUser,
    id: `${role}-id`,
    username: `${role}.user`,
    displayName: `${role} 用户`,
    role,
  }
}

function renderAuthenticatedApp(role: UserDto["role"]): void {
  installBridge(
    bridge({
      refresh: vi.fn().mockResolvedValue(ok(authResult(userFor(role)))),
    }),
  )
  renderApp(<App />)
}

function waitForHistoryHash(hash: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      cleanupListeners()
      reject(new Error(`History did not navigate to ${hash}.`))
    }, 1_000)
    const check = () => {
      if (location.hash !== hash) return
      cleanupListeners()
      resolve()
    }
    const cleanupListeners = () => {
      window.clearTimeout(timeout)
      window.removeEventListener("popstate", check)
      window.removeEventListener("hashchange", check)
    }
    window.addEventListener("popstate", check)
    window.addEventListener("hashchange", check)
  })
}

describe("role-aware project workbench navigation", () => {
  it.each([
    ["#projects", { kind: "projects" }],
    ["#projects/new", { kind: "new-project" }],
    ["#projects/73c3f6ee-08a6-41e9-985b-39df01777b67", { kind: "project", projectId: "73c3f6ee-08a6-41e9-985b-39df01777b67" }],
    ["#templates", { kind: "templates" }],
    ["#modules", { kind: "modules" }],
    ["#users", { kind: "users" }],
    ["#system-configuration", { kind: "system-configuration" }],
    ["#task-center", { kind: "task-center" }],
    ["#extensions", { kind: "extensions" }],
    ["#account", { kind: "account" }],
  ])("parses the supported route %s", (hash, route) => {
    expect(parseHashRoute(hash)).toEqual(route)
  })

  it("normalizes legacy project tabs and rejects ambiguous tab queries", () => {
    expect(parseHashRoute("#projects/alpha?tab=gantt")).toEqual({ kind: "project", projectId: "alpha", tab: "overview" })
    expect(parseHashRoute("#projects/alpha?tab=files")).toEqual({ kind: "project", projectId: "alpha", tab: "library" })
    expect(parseHashRoute("#projects/alpha?tab=documents")).toEqual({ kind: "project", projectId: "alpha", tab: "library" })
    expect(parseHashRoute("#projects/alpha?tab=members")).toEqual({ kind: "project", projectId: "alpha", tab: "management" })
    expect(parseHashRoute("#projects/alpha?tab=modules")).toEqual({ kind: "project", projectId: "alpha", tab: "management" })
    expect(parseHashRoute("#projects/alpha?tab=tasks&tab=gantt")).toEqual({ kind: "projects" })
    expect(parseHashRoute("#projects/alpha?tab=unknown")).toEqual({ kind: "projects" })
  })

  it.each([
    "",
    "#",
    "#projects/",
    "#projects/new/extra",
    "#projects/alpha/beta",
    "#projects/%2F",
    "#projects/%252F",
    "#projects/a%252Fb",
    "#projects/%3F",
    "#projects/%23",
    "#projects/%5C",
    "#projects/%25",
    "#projects/a%253Fb",
    "#projects/a%2523b",
    "#projects/a%255Cb",
    "#projects/a%2525b",
    "#projects/%E0%A4%A",
    "#projects/%2D",
    "#projects/.",
    "#unknown",
  ])("rejects an ambiguous or malformed route %s", (hash) => {
    expect(parseHashRoute(hash)).toEqual({ kind: "projects" })
  })

  it.each([
    ["admin", ["项目工作台", "任务中心", "行业模板", "模块管理", "用户管理", "系统配置"]],
    ["project_lead", ["项目工作台", "任务中心"]],
    ["fde_engineer", ["项目工作台", "任务中心"]],
    ["viewer", ["项目工作台", "任务中心"]],
  ] as const)("shows permitted navigation for %s", async (role, labels) => {
    location.hash = "#projects"
    renderAuthenticatedApp(role)

    for (const label of labels) {
      expect(await screen.findByRole("link", { name: label })).toBeVisible()
    }
  })

  it("redirects non-admin template route to projects", async () => {
    location.hash = "#templates"
    renderAuthenticatedApp("project_lead")

    expect(await screen.findByRole("heading", { name: "项目工作台" })).toBeVisible()
    expect(location.hash).toBe("#projects")
  })

  it.each(["fde_engineer", "viewer"] as const)("redirects %s away from project creation", async (role) => {
    location.hash = "#projects/new"
    renderAuthenticatedApp(role)

    expect(await screen.findByRole("heading", { name: "项目工作台" })).toBeVisible()
    expect(location.hash).toBe("#projects")
  })

  it("normalizes a blank history entry and follows later hashchange navigation", async () => {
    location.hash = ""
    renderAuthenticatedApp("admin")

    expect(await screen.findByRole("heading", { name: "项目工作台" })).toBeVisible()
    expect(location.hash).toBe("#projects")

    location.hash = "#templates"
    window.dispatchEvent(new HashChangeEvent("hashchange"))
    expect(await screen.findByRole("heading", { name: "行业模板" })).toBeVisible()

    location.hash = "#modules"
    window.dispatchEvent(new HashChangeEvent("hashchange"))
    expect(await screen.findByRole("heading", { name: "模块管理" })).toBeVisible()
  })

  it("uses browser history to return to projects and then forward to project detail", async () => {
    location.hash = "#projects"
    renderAuthenticatedApp("admin")
    expect(await screen.findByRole("heading", { name: "项目工作台" })).toBeVisible()

    location.hash = "#projects/73c3f6ee-08a6-41e9-985b-39df01777b67"
    expect(await screen.findByRole("heading", { name: "项目详情" })).toBeVisible()

    const back = waitForHistoryHash("#projects")
    window.history.back()
    await back
    expect(await screen.findByRole("heading", { name: "项目工作台" })).toBeVisible()

    const forward = waitForHistoryHash("#projects/73c3f6ee-08a6-41e9-985b-39df01777b67")
    window.history.forward()
    await forward
    expect(await screen.findByRole("heading", { name: "项目详情" })).toBeVisible()
  })
})
