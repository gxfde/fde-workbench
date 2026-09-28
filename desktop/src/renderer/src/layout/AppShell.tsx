import { useEffect, useState, type ReactNode } from "react"

import logo from "../assets/logo.png"
import { useAuth } from "../auth/AuthProvider"
import { AIServerChat } from "../ai/AIServerChat"
import { canLeaveDirtyWorkspace } from "../routing/navigationGuard"
import { routeHash, type AppRoute } from "../routing/useHashRoute"

const COLLAPSED_KEY = "fde.sidebar.collapsed"

export function AppShell({
  children,
  route,
}: {
  children: ReactNode
  route: AppRoute
}) {
  const { logout, user } = useAuth()
  const isAdmin = user?.role === "admin"
  const [collapsed, setCollapsed] = useState(() => readCollapsed())
  const [appVersion, setAppVersion] = useState("")

  useEffect(() => {
    let active = true
    void window.fde.app.version()
      .then((version) => { if (active) setAppVersion(version) })
      .catch(() => { /* Version text is supplementary and must not block the app. */ })
    return () => { active = false }
  }, [])

  function toggleCollapsed(): void {
    setCollapsed((current) => {
      const next = !current
      localStorage.setItem(COLLAPSED_KEY, next ? "collapsed" : "expanded")
      return next
    })
  }

  return (
    <div className={`app-shell${collapsed ? " sidebar-collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="sidebar-top">
          <div className="brand-lockup">
            <img className="brand-logo" src={logo} alt="FDE Workbench" />
            <div className="brand-text">
              <span className="brand-name">FDE Workbench</span>
              <span className="brand-subtitle">开源项目工作台</span>
            </div>
          </div>
        </div>
        <nav aria-label="主导航">
          <NavLink route={route} target={{ kind: "projects" }} label="项目工作台" icon={<GridIcon />} />
          <NavLink route={route} target={{ kind: "task-center" }} label="任务中心" icon={<TaskIcon />} />
          <NavLink route={route} target={{ kind: "extensions" }} label="AI 与扩展" icon={<ExtensionIcon />} />
          {isAdmin ? <>
            <NavLink route={route} target={{ kind: "templates" }} label="行业模板" icon={<LayersIcon />} />
            <NavLink route={route} target={{ kind: "document-templates" }} label="文档模板" icon={<DocumentIcon />} />
            <NavLink route={route} target={{ kind: "modules" }} label="模块管理" icon={<BoxesIcon />} />
            <NavLink route={route} target={{ kind: "users" }} label="用户管理" icon={<PeopleIcon />} />
            <NavLink route={route} target={{ kind: "system-configuration" }} label="系统配置" icon={<SettingsIcon />} />
          </> : null}
        </nav>
        <div className="sidebar-bottom">
          <button
            className="sidebar-toggle"
            type="button"
            aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}
            aria-expanded={!collapsed}
            title={collapsed ? "展开侧边栏" : "收起侧边栏"}
            onClick={toggleCollapsed}
          >
            <CollapseIcon />
          </button>
          <div className="sidebar-account">
            <a className="account-name account-link" href={routeHash({ kind: "account" })}>{user?.displayName}</a>
            <small className="account-role">{roleLabel(user?.role)}</small>
            {appVersion ? <small className="app-version">v{appVersion}</small> : null}
            <button className="text-button" type="button" onClick={() => {
              if (!canLeaveDirtyWorkspace("logout")) return
              if (window.confirm("确定退出登录吗？")) void logout()
            }}>
              退出登录
            </button>
          </div>
        </div>
      </aside>
      <main className="workspace">{children}</main>
      <AIServerChat route={route} />
    </div>
  )
}

function NavLink({
  route,
  target,
  label,
  icon,
}: {
  route: AppRoute
  target: AppRoute
  label: string
  icon: ReactNode
}) {
  const current = route.kind === target.kind || (
    target.kind === "projects" && (route.kind === "new-project" || route.kind === "project")
  )
  return (
    <a
      className={`nav-item${current ? " active" : ""}`}
      href={routeHash(target)}
      aria-current={current ? "page" : undefined}
      aria-label={label}
    >
      <span className="nav-icon" aria-hidden="true">{icon}</span>
      <span className="nav-label">{label}</span>
    </a>
  )
}

const iconProps = {
  width: 20,
  height: 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
}

function GridIcon() {
  return (
    <svg {...iconProps}>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </svg>
  )
}

function LayersIcon() {
  return (
    <svg {...iconProps}>
      <path d="m12 2 10 5-10 5L2 7l10-5z" />
      <path d="m2 12 10 5 10-5" />
      <path d="m2 17 10 5 10-5" />
    </svg>
  )
}

function BoxesIcon() {
  return (
    <svg {...iconProps}>
      <path d="M12 3 3.5 7.5v9L12 21l8.5-4.5v-9L12 3z" />
      <path d="M3.5 7.5 12 12l8.5-4.5" />
      <path d="M12 12v9" />
    </svg>
  )
}

function DocumentIcon() {
  return (
    <svg {...iconProps}>
      <path d="M6 2h8l4 4v16H6z" />
      <path d="M14 2v5h5M9 12h6M9 16h6" />
    </svg>
  )
}

function CollapseIcon() {
  return (
    <svg {...iconProps}>
      <path d="m15 18-6-6 6-6" />
    </svg>
  )
}

function PeopleIcon() {
  return (
    <svg {...iconProps}>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20c0-3.1 3-5 6.5-5s6.5 1.9 6.5 5" />
      <circle cx="17" cy="9" r="2.75" />
      <path d="M15.25 15.4c2.9.6 5.25 2.4 5.25 4.6" />
    </svg>
  )
}

function TaskIcon() {
  return (
    <svg {...iconProps}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="m7 9 2 2 4-4M14 10h4M7 15h11" />
    </svg>
  )
}

function ExtensionIcon() {
  return (
    <svg {...iconProps}>
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4" />
      <circle cx="12" cy="12" r="5" />
      <path d="m5.6 5.6 2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8" />
    </svg>
  )
}

function SettingsIcon() {
  return (
    <svg {...iconProps}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1z" />
    </svg>
  )
}

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "collapsed"
  } catch {
    return false
  }
}

function roleLabel(role: string | undefined): string {
  return {
    admin: "管理员",
    fde_engineer: "工程师",
    project_lead: "项目负责人",
    viewer: "查看者",
  }[role ?? ""] ?? "企业用户"
}
