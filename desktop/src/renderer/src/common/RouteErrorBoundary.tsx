import { Component, type ErrorInfo, type ReactNode } from "react"

interface RouteErrorBoundaryProps {
  children: ReactNode
}

interface RouteErrorBoundaryState {
  error: Error | null
}

/**
 * 方案 §3.5 F5：把「视图渲染异常 → 白屏」改成可操作的兜底页。
 *
 * 只包在路由分发的 RoutePage 外层：不改 hash、不改导航守卫、不吞业务错误，
 * 门禁 / 审批链中途出错时仍能看到「当前视图加载失败」而非误判「是否已提交」。
 * 由 App.tsx 以 routeHash 作 key，切换路由时自动重置兜底状态。
 */
export class RouteErrorBoundary extends Component<
  RouteErrorBoundaryProps,
  RouteErrorBoundaryState
> {
  state: RouteErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): RouteErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("[RouteErrorBoundary] 视图渲染失败", error, info.componentStack)
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children
    return (
      <section className="panel" aria-labelledby="route-error-title">
        <h2 id="route-error-title">当前视图加载失败</h2>
        <p className="form-error" role="alert">
          {this.state.error.message || "页面渲染出现异常，请重试。"}
        </p>
        <p className="supporting-copy">当前地址未改变，重试不会丢失你正在查看的位置。</p>
        <div className="row-actions">
          <button
            className="secondary-button"
            type="button"
            onClick={() => this.setState({ error: null })}
          >
            重试
          </button>
          <a className="secondary-button button-link" href="#projects">
            返回工作台
          </a>
        </div>
      </section>
    )
  }
}
