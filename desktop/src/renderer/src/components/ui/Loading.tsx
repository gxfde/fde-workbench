import { type ReactElement, type ReactNode } from "react"

/** S2 / F3：把散落的「正在加载…」文案收敛成一种形态。 */
export function Loading({
  label = "正在加载…",
  skeleton = false,
}: {
  label?: string
  skeleton?: boolean
}): ReactElement {
  if (skeleton) return <div className="ui-skeleton" aria-hidden="true" />
  return <p className="ui-loading" role="status">{label}</p>
}

/** S2 / F3：空状态统一到 `styles.css` 的 `.empty-state` 契约。 */
export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: ReactNode
}): ReactElement {
  return (
    <div className="empty-state">
      <p className="empty-state-title">{title}</p>
      {description ? <p className="supporting-copy">{description}</p> : null}
      {action ? <div className="row-actions">{action}</div> : null}
    </div>
  )
}
