import {
  useEffect,
  useState,
  type Dispatch,
  type FormEvent,
  type ReactNode,
  type SetStateAction,
} from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { useDangerConfirm } from "../common/DangerConfirmProvider"
import { fetchAllPages } from "../workbench/fetchAllPages"
import { isModuleCatalogDto } from "../workbench/runtimeValidation"
import type { ModuleCatalogDto } from "../workbench/types"

interface ModuleForm {
  name: string
  description: string
  sortOrder: string
}

const emptyCreateForm = {
  key: "",
  name: "",
  description: "",
  sortOrder: "0",
}

export function ModulesPage() {
  const { apiRequest } = useAuth()
  const dangerConfirm = useDangerConfirm()
  const [modules, setModules] = useState<ModuleCatalogDto[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")
  const [notice, setNotice] = useState("")
  const [actionError, setActionError] = useState("")
  const [creating, setCreating] = useState(false)
  const [createForm, setCreateForm] = useState(emptyCreateForm)
  const [editing, setEditing] = useState<ModuleCatalogDto | null>(null)
  const [editForm, setEditForm] = useState<ModuleForm | null>(null)
  const [saving, setSaving] = useState(false)
  const [staleModuleId, setStaleModuleId] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setLoading(true)
    setLoadError("")
    void listModules(apiRequest, controller.signal)
      .then((items) => {
        if (active) setModules(items)
      })
      .catch((error) => {
        if (active) setLoadError(moduleErrorMessage(error))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [apiRequest])

  async function createModule(event: FormEvent): Promise<void> {
    event.preventDefault()
    setActionError("")
    setNotice("")
    setStaleModuleId(null)
    const key = createForm.key.trim()
    const name = createForm.name.trim()
    const sortOrder = parseWholeNumber(createForm.sortOrder)
    if (!stableKey(key)) {
      setActionError("模块标识需使用小写英文、数字或下划线，且以英文开头。")
      return
    }
    if (!name || sortOrder === null) {
      setActionError("请填写模块名称和有效排序。")
      return
    }
    setCreating(true)
    try {
      const created = await apiRequest<ModuleCatalogDto>("/api/v1/modules", {
        method: "POST",
        body: {
          key,
          name,
          description: createForm.description.trim(),
          sort_order: sortOrder,
          is_active: true,
        },
      })
      setModules((current) => sortedModules([...current, created]))
      setCreateForm(emptyCreateForm)
      setNotice("模块已新增")
    } catch (error) {
      setActionError(moduleErrorMessage(error))
    } finally {
      setCreating(false)
    }
  }

  function openEditor(module: ModuleCatalogDto): void {
    setActionError("")
    setNotice("")
    setStaleModuleId(null)
    setEditing(module)
    setEditForm({
      name: module.name,
      description: module.description,
      sortOrder: String(module.sort_order),
    })
  }

  async function saveModule(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (!editing || !editForm) return
    setActionError("")
    setNotice("")
    setStaleModuleId(null)
    const name = editForm.name.trim()
    const sortOrder = parseWholeNumber(editForm.sortOrder)
    if (!name || sortOrder === null) {
      setActionError("请填写模块名称和有效排序。")
      return
    }
    setSaving(true)
    try {
      const updated = await apiRequest<ModuleCatalogDto>(
        `/api/v1/modules/${editing.id}`,
        {
          method: "PATCH",
          body: {
            version: editing.version,
            name,
            description: editForm.description.trim(),
            sort_order: sortOrder,
          },
        },
      )
      replaceModule(setModules, updated)
      setEditing(null)
      setEditForm(null)
      setNotice("模块已保存")
    } catch (error) {
      if (error instanceof ApiClientError && error.code === "stale_version") {
        setStaleModuleId(editing.id)
      }
      setActionError(moduleErrorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  async function toggleModule(module: ModuleCatalogDto): Promise<void> {
    if (module.is_active) {
      const confirmed = await dangerConfirm({
        title: "停用模块",
        description: `确定停用模块“${module.name}”吗？停用后该模块将不再出现在行业模板的可选模块中。`,
        confirmLabel: "停用",
      })
      if (!confirmed) return
    }
    setActionError("")
    setNotice("")
    setStaleModuleId(null)
    try {
      const updated = await apiRequest<ModuleCatalogDto>(
        `/api/v1/modules/${module.id}`,
        { method: "PATCH", body: { is_active: !module.is_active, version: module.version } },
      )
      replaceModule(setModules, updated)
      setNotice(module.is_active ? "模块已停用" : "模块已启用")
    } catch (error) {
      if (error instanceof ApiClientError && error.code === "stale_version") {
        setStaleModuleId(module.id)
      }
      setActionError(moduleErrorMessage(error))
    }
  }

  async function refreshModuleVersion(): Promise<void> {
    if (!staleModuleId) return
    setSaving(true)
    try {
      const current = await listModules(apiRequest, new AbortController().signal)
      const latest = current.find((module) => module.id === staleModuleId)
      if (!latest) {
        setActionError("该模块已不存在，请返回列表核对。")
        return
      }
      setModules(current)
      if (editing?.id === latest.id) setEditing(latest)
      setStaleModuleId(null)
      setActionError("")
      setNotice("已刷新服务器版本，当前表单内容仍保留。")
    } catch (error) {
      setActionError(moduleErrorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div id="modules" className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">系统管理</p>
          <h1>模块管理</h1>
          <p className="supporting-copy">维护可用于行业模板的标准交付模块。模块标识创建后不会随名称改变。</p>
        </div>
      </header>

      {notice ? <p className="notice" role="status">{notice}</p> : null}
      {actionError ? <p className="form-error banner" role="alert">{actionError}</p> : null}
      {staleModuleId ? <button className="secondary-button" type="button" disabled={saving} onClick={() => void refreshModuleVersion()}>刷新模块版本</button> : null}

      <section className="panel" aria-labelledby="create-module-title">
        <h2 id="create-module-title">新增模块</h2>
        <form className="form-grid module-form" onSubmit={(event) => void createModule(event)} noValidate>
          <Field label="模块标识" id="create-module-key">
            <input id="create-module-key" value={createForm.key} disabled={creating} placeholder="data_governance" onChange={(event) => setCreateForm({ ...createForm, key: event.target.value })} />
          </Field>
          <Field label="模块名称" id="create-module-name">
            <input id="create-module-name" value={createForm.name} disabled={creating} onChange={(event) => setCreateForm({ ...createForm, name: event.target.value })} />
          </Field>
          <Field label="模块说明" id="create-module-description">
            <input id="create-module-description" value={createForm.description} disabled={creating} onChange={(event) => setCreateForm({ ...createForm, description: event.target.value })} />
          </Field>
          <Field label="模块排序" id="create-module-sort">
            <input id="create-module-sort" type="number" step="1" value={createForm.sortOrder} disabled={creating} onChange={(event) => setCreateForm({ ...createForm, sortOrder: event.target.value })} />
          </Field>
          <div className="form-actions"><button className="primary-button" type="submit" disabled={creating}>{creating ? "正在新增" : "新增模块"}</button></div>
        </form>
      </section>

      <section className="panel table-panel" aria-labelledby="module-list-title">
        <div className="panel-heading"><h2 id="module-list-title">模块目录</h2><span>{modules.length} 个模块</span></div>
        {loading ? <p role="status">正在加载模块…</p> : loadError ? (
          <p className="form-error" role="alert">{loadError}</p>
        ) : modules.length === 0 ? <p className="empty-state">暂无模块。</p> : (
          <div className="table-scroll"><table>
            <thead><tr><th>模块</th><th>稳定标识</th><th>说明</th><th>排序</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>{modules.map((module) => <tr key={module.id}>
              <td>{module.name}</td><td><code>{module.key}</code></td><td className="wrap-cell">{module.description || "—"}</td><td>{module.sort_order}</td>
              <td><span className={`badge ${module.is_active ? "success" : "muted"}`}>{module.is_active ? "启用" : "停用"}</span></td>
              <td><div className="row-actions">
                <button className="secondary-button compact" type="button" aria-label={`编辑 ${module.name}`} onClick={() => openEditor(module)}>编辑</button>
                <button className="secondary-button compact" type="button" aria-label={`${module.is_active ? "停用" : "启用"} ${module.name}`} onClick={() => void toggleModule(module)}>{module.is_active ? "停用" : "启用"}</button>
              </div></td>
            </tr>)}</tbody>
          </table></div>
        )}
      </section>

      {editing && editForm ? <section className="panel editor-panel" aria-labelledby="edit-module-title">
        <div className="panel-heading"><h2 id="edit-module-title">编辑模块</h2><span>{editing.name}</span></div>
        <form className="form-grid module-form" onSubmit={(event) => void saveModule(event)} noValidate>
          <Field label="模块标识（只读）" id="edit-module-key"><input id="edit-module-key" value={editing.key} readOnly /></Field>
          <Field label="编辑模块名称" id="edit-module-name"><input id="edit-module-name" value={editForm.name} disabled={saving} onChange={(event) => setEditForm({ ...editForm, name: event.target.value })} /></Field>
          <Field label="编辑模块说明" id="edit-module-description"><input id="edit-module-description" value={editForm.description} disabled={saving} onChange={(event) => setEditForm({ ...editForm, description: event.target.value })} /></Field>
          <Field label="编辑模块排序" id="edit-module-sort"><input id="edit-module-sort" type="number" step="1" value={editForm.sortOrder} disabled={saving} onChange={(event) => setEditForm({ ...editForm, sortOrder: event.target.value })} /></Field>
          <div className="form-actions row-actions"><button className="secondary-button" type="button" disabled={saving} onClick={() => { setEditing(null); setEditForm(null) }}>取消</button><button className="primary-button" type="submit" disabled={saving}>{saving ? "正在保存" : "保存模块"}</button></div>
        </form>
      </section> : null}
    </div>
  )
}

function Field({ label, id, children }: { label: string; id: string; children: ReactNode }) {
  return <div className="field"><label htmlFor={id}>{label}</label>{children}</div>
}

function listModules(
  apiRequest: ReturnType<typeof useAuth>["apiRequest"],
  signal: AbortSignal,
): Promise<ModuleCatalogDto[]> {
  return fetchAllPages({
    apiRequest,
    pathForPage: (page, pageSize) => `/api/v1/modules?page=${page}&page_size=${pageSize}`,
    itemKey: (module) => module.id,
    validateItem: isModuleCatalogDto,
    signal,
  })
}

function replaceModule(setModules: Dispatch<SetStateAction<ModuleCatalogDto[]>>, updated: ModuleCatalogDto): void {
  setModules((current) => sortedModules(current.map((module) => module.id === updated.id ? updated : module)))
}

function sortedModules(modules: ModuleCatalogDto[]): ModuleCatalogDto[] {
  return [...modules].sort((left, right) => left.sort_order - right.sort_order || left.id.localeCompare(right.id))
}

function parseWholeNumber(value: string): number | null {
  if (!/^-?\d+$/.test(value.trim())) return null
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) ? parsed : null
}

function stableKey(value: string): boolean {
  return /^[a-z][a-z0-9_]*$/.test(value)
}

function moduleErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "module_already_exists") return "模块名称或标识已存在。"
  if (error instanceof ApiClientError && error.code === "authentication_refreshed_resubmit") return "登录状态已刷新，请重新提交本次操作。"
  if (error instanceof ApiClientError && error.code === "module_not_found") return "该模块已不存在，请刷新后重试。"
  if (error instanceof ApiClientError && error.code === "stale_version") return "模块已被其他人更新；已保留当前表单，请刷新版本后重试。"
  return "模块操作失败，请稍后重试。"
}
