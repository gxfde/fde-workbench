import { useEffect, useState } from "react"

import type { UserRole } from "../../../shared/contracts"
import { canAcceptHashNavigation } from "./navigationGuard"

export type AppRoute =
  | { kind: "projects" }
  | { kind: "bridge" }
  | { kind: "new-project" }
  | { kind: "project"; projectId: string; tab?: ProjectDetailTab; opportunity?: string; solution?: string; mode?: 'edit' }
  | { kind: "templates" }
  | { kind: "document-templates" }
  | { kind: "modules" }
  | { kind: "users" }
  | { kind: "system-configuration" }
  | { kind: "task-center" }
  | { kind: "translator" }
  | { kind: "metrics" }
  | { kind: "pilot" }
  | {
      kind: "dispatch"
      tab?:
        | "pool"
        | "mine"
        | "settlements"
        | "profiles"
        | "rules"
        | "console"
        | "disputes"
        | "sim"
        | "gates"
    }
  | { kind: "help" }
  | { kind: "extensions"; tool?: 'lcsc-browser-baseline' | 'lcsc-browser-jev' | 'lcsc-compare'; tab?: 'tools' }
  | { kind: "account" }

const projectsRoute: AppRoute = { kind: "projects" }
const bridgeRoute: AppRoute = { kind: "bridge" }
export const PROJECT_DETAIL_TABS = ["overview", "tasks", "gates", "commercial", "research", "delivery", "library", "management"] as const
export type ProjectDetailTab = (typeof PROJECT_DETAIL_TABS)[number]

const LEGACY_PROJECT_TABS: Record<string, ProjectDetailTab> = {
  gantt: "overview",
  files: "library",
  documents: "library",
  members: "management",
  modules: "management",
}

export function normalizeLegacyProjectTab(tab: string): ProjectDetailTab | null {
  if (PROJECT_DETAIL_TABS.some((candidate) => candidate === tab)) return tab as ProjectDetailTab
  return LEGACY_PROJECT_TABS[tab] ?? null
}

export function parseHashRoute(hash: string): AppRoute {
  if (hash === "#projects") return projectsRoute
  if (hash === "#bridge") return bridgeRoute
  if (hash === "#projects/new") return { kind: "new-project" }
  if (hash === "#templates") return { kind: "templates" }
  if (hash === "#document-templates") return { kind: "document-templates" }
  if (hash === "#modules") return { kind: "modules" }
  if (hash === "#users") return { kind: "users" }
  if (hash === "#system-configuration") return { kind: "system-configuration" }
  if (hash === "#task-center") return { kind: "task-center" }
  if (hash === "#translator") return { kind: "translator" }
  if (hash === "#metrics") return { kind: "metrics" }
  if (hash === "#pilot") return { kind: "pilot" }
  if (hash === "#dispatch") return { kind: "dispatch" }
  if (hash === "#dispatch/pool") return { kind: "dispatch", tab: "pool" }
  if (hash === "#dispatch/mine") return { kind: "dispatch", tab: "mine" }
  if (hash === "#dispatch/settlements") return { kind: "dispatch", tab: "settlements" }
  if (hash === "#dispatch/profiles") return { kind: "dispatch", tab: "profiles" }
  if (hash === "#dispatch/rules") return { kind: "dispatch", tab: "rules" }
  if (hash === "#dispatch/console") return { kind: "dispatch", tab: "console" }
  if (hash === "#dispatch/disputes") return { kind: "dispatch", tab: "disputes" }
  if (hash === "#dispatch/sim") return { kind: "dispatch", tab: "sim" }
  if (hash === "#dispatch/gates") return { kind: "dispatch", tab: "gates" }
  if (hash === "#help") return { kind: "help" }
  if (hash === "#extensions") return { kind: "extensions" }
  if (hash === "#extensions?tab=tools") return { kind: "extensions", tab: 'tools' }
  if (hash === "#extensions/tools/lcsc-browser-baseline") return { kind: "extensions", tool: 'lcsc-browser-baseline' }
  if (hash === "#extensions/tools/lcsc-browser-jev") return { kind: "extensions", tool: 'lcsc-browser-jev' }
  if (hash === "#extensions/tools/lcsc-compare") return { kind: "extensions", tool: 'lcsc-compare' }
  if (hash === "#account") return { kind: "account" }

  const prefix = "#projects/"
  if (!hash.startsWith(prefix)) return projectsRoute
  const remainder = hash.slice(prefix.length)
  const queryIndex = remainder.indexOf("?")
  const rawProjectId = queryIndex === -1 ? remainder : remainder.slice(0, queryIndex)
  const rawQuery = queryIndex === -1 ? "" : remainder.slice(queryIndex + 1)
  if (!rawProjectId || rawProjectId.includes("/")) return projectsRoute
  try {
    const projectId = decodeURIComponent(rawProjectId)
    if (
      !projectId ||
      projectId === "." ||
      projectId === ".." ||
      projectId.includes("/") ||
      /[?#\\%]/.test(projectId) ||
      /%[0-9a-f]{2}/i.test(projectId) ||
      encodeURIComponent(projectId) !== rawProjectId
    ) return projectsRoute
    if (!rawQuery) return { kind: "project", projectId }
    const params = new URLSearchParams(rawQuery)
    const entries = [...params.entries()]
    if (entries.length > 1 && params.get('tab') === 'research') {
      const opportunity = params.get('opportunity')
      if (!opportunity || !/^[a-zA-Z0-9_-]+$/.test(opportunity)) return projectsRoute
      const route: AppRoute = { kind: 'project', projectId, tab: 'research', opportunity }
      return routeHash(route) === hash ? route : projectsRoute
    }
    if (entries.length > 1 && params.get('tab') === 'delivery') {
      const opportunity = params.get('opportunity')
      const solution = params.get('solution')
      const mode = params.get('mode')
      if (opportunity !== null && !/^[a-zA-Z0-9_-]+$/.test(opportunity)) return projectsRoute
      if (solution !== null && !/^[a-zA-Z0-9_-]+$/.test(solution)) return projectsRoute
      if (mode !== null && (mode !== 'edit' || !solution || solution === 'new')) return projectsRoute
      if (!opportunity && !solution) return projectsRoute
      const route: AppRoute = { kind: 'project', projectId, tab: 'delivery', ...(opportunity ? { opportunity } : {}), ...(solution ? { solution } : {}), ...(mode === 'edit' ? { mode } : {}) }
      // Reject unknown/duplicate parameters, ambiguous encodings and alternate orders.
      return routeHash(route) === hash ? route : projectsRoute
    }
    if (entries.length !== 1 || entries[0][0] !== "tab") return projectsRoute
    const rawTab = params.get("tab")
    const normalizedTab = rawTab ? normalizeLegacyProjectTab(rawTab) : null
    if (!rawTab || rawQuery !== `tab=${rawTab}` || !normalizedTab) return projectsRoute
    return { kind: "project", projectId, tab: normalizedTab }
  } catch {
    return projectsRoute
  }
}

export function routeHash(route: AppRoute): string {
  switch (route.kind) {
    case "projects": return "#projects"
    case "bridge": return "#bridge"
    case "new-project": return "#projects/new"
    case "project": return `#projects/${encodeURIComponent(route.projectId)}${route.tab && route.tab !== "overview" ? `?tab=${route.tab}` : ""}${(route.tab === 'delivery' || route.tab === 'research') && route.opportunity ? `&opportunity=${encodeURIComponent(route.opportunity)}` : ''}${route.tab === 'delivery' && route.solution ? `&solution=${encodeURIComponent(route.solution)}${route.mode === 'edit' && route.solution !== 'new' ? '&mode=edit' : ''}` : ''}`
    case "templates": return "#templates"
    case "document-templates": return "#document-templates"
    case "modules": return "#modules"
    case "users": return "#users"
    case "system-configuration": return "#system-configuration"
    case "task-center": return "#task-center"
    case "translator": return "#translator"
    case "metrics": return "#metrics"
    case "pilot": return "#pilot"
    case "dispatch":
      return route.tab && route.tab !== "pool" ? `#dispatch/${route.tab}` : "#dispatch"
    case "help": return "#help"
    case "extensions": return route.tool ? `#extensions/tools/${route.tool}` : route.tab ? '#extensions?tab=tools' : '#extensions'
    case "account": return "#account"
  }
}

export function authorizedRoute(route: AppRoute, role: UserRole): AppRoute {
  if (route.kind === "templates" || route.kind === "document-templates" || route.kind === "modules" || route.kind === "users" || route.kind === "system-configuration") {
    return role === "admin" ? route : projectsRoute
  }
  // J6：扩展中心（LCSC 工具页 / 插件审批 / 模型配置）属管理口径——非管理员
  // 直接访问 #extensions 时不再渲染该页（服务端仍会拦，这里是减少暴露面）。
  if (route.kind === "extensions") {
    return role === "admin" ? route : projectsRoute
  }
  if (route.kind === "new-project") {
    return role === "admin" || role === "project_lead" ? route : projectsRoute
  }
  // P0/P1 指标报表（goal-d8）：运营口径——平台侧（admin/project_lead）专属，
  // 其他角色回落项目列表（服务端 require_auth 是最终防线，这里减少暴露面）。
  if (route.kind === "metrics") {
    return role === "admin" || role === "project_lead" ? route : projectsRoute
  }
  // UM-1 试点报告（goal-d11）：admin 专属——d11 挂账④：非 admin 直输 #/pilot
  // 此前会渲染页面并吃到服务端 403（pilot_report_forbidden），现在与导航
  // isAdmin 门对齐，直接回落项目列表（服务端仍是最终防线，这里减少暴露面）。
  if (route.kind === "pilot") {
    return role === "admin" ? route : projectsRoute
  }
  return route
}

export function useHashRoute(): AppRoute {
  const [route, setRoute] = useState(() => parseHashRoute(window.location.hash))

  useEffect(() => {
    let acceptedHash = window.location.hash
    function updateRoute(): void {
      const hash = window.location.hash
      if (hash === acceptedHash) return
      if (!canAcceptHashNavigation(hash)) {
        window.location.hash = acceptedHash
        return
      }
      const parsed = parseHashRoute(hash)
      const normalized = routeHash(parsed)
      if (hash !== normalized) {
        acceptedHash = normalized
        window.location.hash = normalized
        setRoute(parsed)
        return
      }
      acceptedHash = hash
      setRoute(parsed)
    }

    const initial = parseHashRoute(acceptedHash)
    if (acceptedHash !== routeHash(initial)) {
      acceptedHash = routeHash(initial)
      window.location.hash = acceptedHash
    }
    window.addEventListener("hashchange", updateRoute)
    return () => window.removeEventListener("hashchange", updateRoute)
  }, [])

  return route
}
