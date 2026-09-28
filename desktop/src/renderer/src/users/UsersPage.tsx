import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react"

import { PASSWORD_MAX_LENGTH, USERNAME_MAX_LENGTH } from "../../../shared/contracts"
import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { useDangerConfirm } from "../common/DangerConfirmProvider"
import { UserAIAccessDialog } from "./UserAIAccessDialog"

interface ApiUser {
  id: string
  username: string
  display_name: string
  role: string
  is_active: boolean
  must_change_password: boolean
  created_at: string
  updated_at: string
}

interface UserList {
  items: ApiUser[]
  page: number
  page_size: number
  total: number
}

export function UsersPage() {
  const { apiRequest } = useAuth()
  const dangerConfirm = useDangerConfirm()
  const [users, setUsers] = useState<ApiUser[]>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [aiAccessTarget, setAIAccessTarget] = useState<ApiUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState("")
  const [error, setError] = useState("")
  const [username, setUsername] = useState("")
  const [displayName, setDisplayName] = useState("")
  const [role, setRole] = useState("fde_engineer")
  const [temporaryPassword, setTemporaryPassword] = useState("")
  const [creating, setCreating] = useState(false)
  const [resetTarget, setResetTarget] = useState<ApiUser | null>(null)
  const [resetPassword, setResetPassword] = useState("")
  const [resetError, setResetError] = useState("")
  const [resetSubmitting, setResetSubmitting] = useState(false)
  const [editing, setEditing] = useState<ApiUser | null>(null)
  const [editDisplayName, setEditDisplayName] = useState("")
  const [editRole, setEditRole] = useState("")
  const [editActive, setEditActive] = useState(true)
  const [editError, setEditError] = useState("")
  const [editSaving, setEditSaving] = useState(false)
  const usernameRef = useRef<HTMLInputElement>(null)
  const resetInputRef = useRef<HTMLInputElement>(null)
  const resetConfirmRef = useRef<HTMLButtonElement>(null)
  const resetInvokerRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (resetTarget) {
      resetInputRef.current?.focus()
    } else if (resetInvokerRef.current) {
      resetInvokerRef.current.focus()
      resetInvokerRef.current = null
    }
  }, [resetTarget])

  useEffect(() => {
    if (resetError && !resetSubmitting) {
      resetInputRef.current?.focus()
    }
  }, [resetError, resetSubmitting])

  useEffect(() => {
    if (editing) {
      setEditDisplayName(editing.display_name)
      setEditRole(editing.role)
      setEditActive(editing.is_active)
    }
  }, [editing])

  async function loadUsers(): Promise<void> {
    const data = await apiRequest<UserList>(
      `/api/v1/users?page=${page}&page_size=20`,
      { method: "GET" },
    )
    setUsers(data.items)
    setTotal(data.total)
  }

  useEffect(() => {
    let active = true
    setLoading(true)
    void loadUsers()
      .catch((caught) => {
        if (active) setError(apiErrorMessage(caught))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [page])

  async function createUser(event: FormEvent): Promise<void> {
    event.preventDefault()
    setError("")
    setNotice("")
    if (!username.trim() || !displayName.trim() || !temporaryPassword) {
      setError("请完整填写账号信息。")
      usernameRef.current?.focus()
      return
    }
    setCreating(true)
    const submittedPassword = temporaryPassword
    try {
      await apiRequest<ApiUser>("/api/v1/users", {
        method: "POST",
        body: {
          username: username.trim(),
          display_name: displayName.trim(),
          role,
          temporary_password: submittedPassword,
        },
      })
      setUsername("")
      setDisplayName("")
      setRole("fde_engineer")
      setNotice("账号已创建")
      await loadUsers()
    } catch (caught) {
      setError(apiErrorMessage(caught))
    } finally {
      setTemporaryPassword("")
      setCreating(false)
    }
  }

  async function toggleUser(user: ApiUser): Promise<void> {
    if (user.is_active) {
      const confirmed = await dangerConfirm({
        title: "停用账号",
        description: `确定停用账号“${user.username}”吗？停用后该账号将无法登录工作台。`,
        confirmLabel: "停用",
      })
      if (!confirmed) return
    }
    setError("")
    setNotice("")
    try {
      await apiRequest<ApiUser>(`/api/v1/users/${user.id}`, {
        method: "PATCH",
        body: { is_active: !user.is_active },
      })
      setNotice(user.is_active ? "账号已停用" : "账号已启用")
      await loadUsers()
    } catch (caught) {
      setError(apiErrorMessage(caught))
    }
  }

  function openEditDialog(user: ApiUser): void {
    setEditError("")
    setEditDisplayName(user.display_name)
    setEditRole(user.role)
    setEditActive(user.is_active)
    setEditing(user)
  }

  function closeEditDialog(): void {
    if (editSaving) return
    setEditError("")
    setEditing(null)
  }

  async function saveEdit(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (!editing || editSaving) return
    if (!editDisplayName.trim()) {
      setEditError("显示名称不能为空。")
      return
    }
    setEditError("")
    setNotice("")
    const target = editing
    setEditSaving(true)
    try {
      await apiRequest<ApiUser>(`/api/v1/users/${target.id}`, {
        method: "PATCH",
        body: {
          display_name: editDisplayName.trim(),
          role: editRole,
          is_active: editActive,
        },
      })
      setNotice("账号信息已更新")
      setEditing(null)
      await loadUsers()
    } catch (caught) {
      setEditError(apiErrorMessage(caught))
    } finally {
      setEditSaving(false)
    }
  }

  async function resetUserPassword(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (!resetTarget || resetSubmitting) return
    setResetError("")
    if (!resetPassword) {
      setResetError("请输入新临时密码。")
      resetInputRef.current?.focus()
      return
    }
    setNotice("")
    const target = resetTarget
    const submittedPassword = resetPassword
    setResetSubmitting(true)
    try {
      await apiRequest<ApiUser>(`/api/v1/users/${target.id}/reset-password`, {
        method: "POST",
        body: { temporary_password: submittedPassword },
      })
      setNotice("密码已重置")
      dismissResetDialog()
      await loadUsers()
    } catch (caught) {
      setResetError(apiErrorMessage(caught))
    } finally {
      setResetPassword("")
      setResetSubmitting(false)
    }
  }

  function openResetDialog(
    user: ApiUser,
    invoker: HTMLButtonElement,
  ): void {
    resetInvokerRef.current = invoker
    setResetPassword("")
    setResetError("")
    setResetTarget(user)
  }

  function closeResetDialog(): void {
    if (resetSubmitting) return
    dismissResetDialog()
  }

  function dismissResetDialog(): void {
    setResetPassword("")
    setResetError("")
    setResetTarget(null)
  }

  function handleResetDialogKeyDown(event: KeyboardEvent<HTMLElement>): void {
    if (event.key === "Escape") {
      event.preventDefault()
      if (!resetSubmitting) closeResetDialog()
      return
    }
    if (event.key !== "Tab" || resetSubmitting) return
    const first = resetInputRef.current
    const last = resetConfirmRef.current
    if (!first || !last) return
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  return (
    <div id="users" className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">系统管理</p>
          <h1>用户管理</h1>
          <p className="supporting-copy">创建企业账号，管理账号状态、初始密码与 AI 权限。</p>
        </div>
      </header>

      {notice ? <p className="notice" role="status">{notice}</p> : null}
      {error ? <p className="form-error banner" role="alert">{error}</p> : null}

      <section className="panel" aria-labelledby="create-user-title">
        <h2 id="create-user-title">创建账号</h2>
        <form className="form-grid create-user-form" onSubmit={(event) => void createUser(event)} noValidate>
          <div className="field">
            <label htmlFor="create-username">用户名</label>
            <input ref={usernameRef} id="create-username" maxLength={USERNAME_MAX_LENGTH} value={username} onChange={(event) => setUsername(event.target.value)} disabled={creating} />
          </div>
          <div className="field">
            <label htmlFor="create-display-name">显示名称</label>
            <input id="create-display-name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} disabled={creating} />
          </div>
          <div className="field">
            <label htmlFor="create-role">角色</label>
            <select id="create-role" value={role} onChange={(event) => setRole(event.target.value)} disabled={creating}>
              <option value="fde_engineer">工程师</option>
              <option value="project_lead">项目负责人</option>
              <option value="viewer">查看者</option>
              <option value="admin">管理员</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="create-temporary-password">临时密码</label>
            <input id="create-temporary-password" type="password" autoComplete="new-password" maxLength={PASSWORD_MAX_LENGTH} value={temporaryPassword} onChange={(event) => setTemporaryPassword(event.target.value)} disabled={creating} />
          </div>
          <div className="form-actions">
            <button className="primary-button" type="submit" disabled={creating}>{creating ? "正在创建" : "创建账号"}</button>
          </div>
        </form>
      </section>

      <section className="panel table-panel" aria-labelledby="user-list-title">
        <div className="panel-heading">
          <h2 id="user-list-title">账号列表</h2>
          <span>{total} 个账号</span>
        </div>
        {loading ? <p role="status">正在加载用户…</p> : (
          <div className="table-scroll">
            <table>
              <thead><tr><th>显示名称</th><th>用户名</th><th>角色</th><th>状态</th><th>密码</th><th>创建时间</th><th>操作</th></tr></thead>
              <tbody>{users.map((user) => (
                <tr key={user.id}>
                  <td>{user.display_name}</td><td>{user.username}</td><td>{roleLabel(user.role)}</td>
                  <td><span className={`badge ${user.is_active ? "success" : "muted"}`}>{user.is_active ? "启用" : "停用"}</span></td>
                  <td><span className={`badge ${user.must_change_password ? "warning" : "success"}`}>{user.must_change_password ? "待修改" : "已设置"}</span></td>
                  <td>{formatDate(user.created_at)}</td>
                  <td><div className="row-actions">
                    <button className="secondary-button compact" type="button" onClick={() => openEditDialog(user)} aria-label={`编辑 ${user.username} 的信息`}>编辑</button>
                    <button className="secondary-button compact" type="button" onClick={() => setAIAccessTarget(user)} aria-label={`管理 ${user.username} 的 AI 权限`}>AI 权限</button>
                    <button className="secondary-button compact" type="button" onClick={() => void toggleUser(user)} aria-label={`${user.is_active ? "停用" : "启用"} ${user.username}`}>{user.is_active ? "停用" : "启用"}</button>
                    <button className="secondary-button compact" type="button" onClick={(event) => openResetDialog(user, event.currentTarget)} aria-label={`重置 ${user.username} 的密码`}>重置密码</button>
                  </div></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>

      {total > 20 ? <nav className="dialog-actions" aria-label="账号分页"><button className="secondary-button" disabled={page <= 1 || loading} onClick={() => setPage(page - 1)}>上一页</button><span>第 {page} / {Math.ceil(total / 20)} 页</span><button className="secondary-button" disabled={page * 20 >= total || loading} onClick={() => setPage(page + 1)}>下一页</button></nav> : null}
      {aiAccessTarget ? <UserAIAccessDialog userId={aiAccessTarget.id} name={aiAccessTarget.display_name} onClose={() => setAIAccessTarget(null)} /> : null}

      {resetTarget ? (
        <div className="dialog-backdrop">
          <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="reset-title" onKeyDown={handleResetDialogKeyDown}>
            <h2 id="reset-title">重置 {resetTarget.username} 的密码</h2>
            <p className="supporting-copy">重置后，该用户需在下次登录时修改密码。</p>
            <form onSubmit={(event) => void resetUserPassword(event)}>
              <div className="field"><label htmlFor="reset-password">新临时密码</label><input ref={resetInputRef} autoFocus id="reset-password" type="password" autoComplete="new-password" maxLength={PASSWORD_MAX_LENGTH} value={resetPassword} disabled={resetSubmitting} aria-invalid={Boolean(resetError)} aria-describedby={resetError ? "reset-error" : undefined} onChange={(event) => setResetPassword(event.target.value)} /></div>
              {resetError ? <p id="reset-error" className="form-error" role="alert">{resetError}</p> : null}
              <div className="dialog-actions"><button className="secondary-button" type="button" disabled={resetSubmitting} onClick={closeResetDialog}>取消</button><button ref={resetConfirmRef} className="primary-button" type="submit" disabled={resetSubmitting}>{resetSubmitting ? "正在重置" : "确认重置"}</button></div>
            </form>
          </section>
        </div>
      ) : null}

      {editing ? (
        <div className="dialog-backdrop">
          <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="edit-user-title">
            <h2 id="edit-user-title">编辑 {editing.username}</h2>
            <p className="supporting-copy">修改账号的显示名称、角色与状态。</p>
            <form onSubmit={(event) => void saveEdit(event)}>
              <div className="field"><label htmlFor="edit-display-name">显示名称</label><input id="edit-display-name" value={editDisplayName} disabled={editSaving} onChange={(event) => setEditDisplayName(event.target.value)} /></div>
              <div className="field"><label htmlFor="edit-role">角色</label><select id="edit-role" value={editRole} disabled={editSaving} onChange={(event) => setEditRole(event.target.value)}>
                <option value="fde_engineer">工程师</option><option value="project_lead">项目负责人</option><option value="viewer">查看者</option><option value="admin">管理员</option>
              </select></div>
              <label className="research-check"><input type="checkbox" checked={editActive} disabled={editSaving} onChange={(event) => setEditActive(event.target.checked)} />启用账号</label>
              {editError ? <p className="form-error" role="alert">{editError}</p> : null}
              <div className="dialog-actions"><button className="secondary-button" type="button" disabled={editSaving} onClick={closeEditDialog}>取消</button><button className="primary-button" type="submit" disabled={editSaving}>{editSaving ? "正在保存" : "保存"}</button></div>
            </form>
          </section>
        </div>
      ) : null}
    </div>
  )
}

function roleLabel(role: string): string {
  return { admin: "管理员", fde_engineer: "工程师", project_lead: "项目负责人", viewer: "查看者" }[role] ?? role
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? "—" : new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(date)
}

function apiErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "authentication_refreshed_resubmit") return "登录状态已刷新，请重新提交本次操作。"
  if (error instanceof ApiClientError && error.code === "username_already_exists") return "用户名已存在。"
  if (error instanceof ApiClientError && error.code === "self_disable_not_allowed") return "不能停用当前登录账号。"
  if (error instanceof ApiClientError && error.code === "user_leads_active_projects") return "该用户仍负责进行中的项目，请先转移项目负责人。"
  if (error instanceof ApiClientError && error.code === "user_has_active_project_memberships") return "该用户仍参与进行中的项目，请先移除其成员身份。"
  if (error instanceof ApiClientError && error.code === "password_too_weak") return "临时密码至少需要 6 位。"
  return "操作失败，请稍后重试。"
}
