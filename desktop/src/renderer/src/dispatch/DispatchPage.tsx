import { CapabilityProfilesPage } from "./CapabilityProfilesPage"
import { ClaimGatesPage } from "./ClaimGatesPage"
import { ConsolePage } from "./ConsolePage"
import { DisputesPage } from "./DisputesPage"
import { DispatchPoolPage } from "./DispatchPoolPage"
import { MyOffersPage } from "./MyOffersPage"
import { MySettlementsPage } from "./MySettlementsPage"
import { RuleVersionsPage } from "./RuleVersionsPage"
import { SimulatorPage } from "./SimulatorPage"
import { useAuth } from "../auth/AuthProvider"

/** P2-1 派单页簇容器 + B1 接单工作台 + B2 调度台 + B3/B5/B6 运维页簇：
 *  九个子页 tab（派单池 / 我的接单 / 我的结算 / 能力档案与产能 / 权重与
 *  规则版本 / 调度台 / 争议处理 / 仿真对比 / 开闸运维）。
 *  tab 状态由 hash 路由承载（#dispatch[/(pool|mine|settlements|profiles|
 *  rules|console|disputes|sim|gates)]）。「我的接单/我的结算」是交付工程师
 *  视角（授权可见 + offer 流，§9.2/§6.3）；派单池/档案/规则沿用平台侧只读
 *  视图；「调度台/争议处理/仿真对比/开闸运维」仅平台侧角色可见
 *  （admin/project_lead——动作权限在服务端复核）。 */

export type DispatchTab =
  | "pool"
  | "mine"
  | "settlements"
  | "profiles"
  | "rules"
  | "console"
  | "disputes"
  | "sim"
  | "gates"

const TABS: { key: DispatchTab; label: string; platformOnly?: boolean }[] = [
  { key: "pool", label: "派单池" },
  { key: "mine", label: "我的接单" },
  { key: "settlements", label: "我的结算" },
  { key: "profiles", label: "能力档案与产能" },
  { key: "rules", label: "权重与规则版本" },
  { key: "console", label: "调度台", platformOnly: true },
  { key: "disputes", label: "争议处理", platformOnly: true },
  { key: "sim", label: "仿真对比", platformOnly: true },
  { key: "gates", label: "开闸运维", platformOnly: true },
]

export function DispatchPage({
  tab,
  onTabChange,
}: {
  tab: DispatchTab
  onTabChange: (tab: DispatchTab) => void
}) {
  const { user } = useAuth()
  const isPlatform = user?.role === "admin" || user?.role === "project_lead"
  const visibleTabs = TABS.filter((item) => !item.platformOnly || isPlatform)
  return (
    <div className="dispatch-page">
      {/* N2：上级 › 当前 文本面包屑——仅展示，不新增路由 */}
      <nav className="breadcrumb" aria-label="面包屑">
        <a href="#projects">项目工作台</a>
        <span className="breadcrumb-separator" aria-hidden="true">›</span>
        <span aria-current="page">派单池</span>
      </nav>
      {/* N3：tab 归一到 ProjectDetailPage 范式——role=tablist + aria-selected + 方向键 */}
      <nav className="dispatch-tabs" role="tablist" aria-label="派单子页">
        {visibleTabs.map((item, index) => (
          <button
            key={item.key}
            id={`dispatch-tab-${item.key}`}
            type="button"
            role="tab"
            aria-selected={tab === item.key}
            aria-controls="dispatch-tabpanel"
            tabIndex={tab === item.key ? 0 : -1}
            className={`dispatch-tab${tab === item.key ? " active" : ""}`}
            onKeyDown={(event) => {
              if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return
              event.preventDefault()
              const next =
                event.key === "Home" ? 0
                : event.key === "End" ? visibleTabs.length - 1
                : event.key === "ArrowLeft" ? (index - 1 + visibleTabs.length) % visibleTabs.length
                : (index + 1) % visibleTabs.length
              const target = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]
              target?.focus()
              target?.click()
            }}
            onClick={() => onTabChange(item.key)}
          >
            {item.label}
          </button>
        ))}
      </nav>
      <div id="dispatch-tabpanel" role="tabpanel" aria-labelledby={`dispatch-tab-${tab}`}>
      {tab === "pool" ? <DispatchPoolPage /> : null}
      {tab === "mine" ? <MyOffersPage /> : null}
      {tab === "settlements" ? <MySettlementsPage /> : null}
      {tab === "profiles" ? <CapabilityProfilesPage /> : null}
      {tab === "rules" ? <RuleVersionsPage /> : null}
      {tab === "console" ? (
        isPlatform ? (
          <ConsolePage />
        ) : (
          <p className="muted">调度台仅对平台侧角色（admin/project_lead）开放。</p>
        )
      ) : null}
      {tab === "disputes" ? (
        isPlatform ? (
          <DisputesPage />
        ) : (
          <p className="muted">争议处理仅对平台侧角色（admin/project_lead）开放。</p>
        )
      ) : null}
      {tab === "sim" ? (
        isPlatform ? (
          <SimulatorPage />
        ) : (
          <p className="muted">仿真对比仅对平台侧角色（admin/project_lead）开放。</p>
        )
      ) : null}
      {tab === "gates" ? (
        isPlatform ? (
          <ClaimGatesPage />
        ) : (
          <p className="muted">开闸运维仅对平台侧角色（admin/project_lead）开放。</p>
        )
      ) : null}
      </div>
    </div>
  )
}
