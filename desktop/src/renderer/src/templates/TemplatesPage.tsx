import { useEffect, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { useDangerConfirm } from "../common/DangerConfirmProvider"
import { fetchAllPages } from "../workbench/fetchAllPages"
import { isModuleCatalogDto, isTemplateVersionDto } from "../workbench/runtimeValidation"
import type {
  ModuleCatalogDto,
  TemplateVersionDto,
} from "../workbench/types"
import { TemplateEditor } from "./TemplateEditor"
import { IndustryTemplateAIAssistant } from "./IndustryTemplateAIAssistant"

type EditorTarget =
  | { kind: "new" }
  | { kind: "draft"; version: TemplateVersionDto }

interface TemplateHistoryGroup {
  templateId: string
  versions: TemplateVersionDto[]
  latest: TemplateVersionDto
  draft: TemplateVersionDto | null
}

export function TemplatesPage() {
  const { apiRequest } = useAuth()
  const dangerConfirm = useDangerConfirm()
  const [versions, setVersions] = useState<TemplateVersionDto[]>([])
  const [catalog, setCatalog] = useState<ModuleCatalogDto[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")
  const [actionError, setActionError] = useState("")
  const [notice, setNotice] = useState("")
  const [editor, setEditor] = useState<EditorTarget | null>(null)
  const [viewing, setViewing] = useState<TemplateVersionDto | null>(null)
  const [actingVersionId, setActingVersionId] = useState<string | null>(null)
  const [staleAction, setStaleAction] = useState(false)
  const [aiAssistantOpen, setAIAssistantOpen] = useState(false)
  const [editorNotice, setEditorNotice] = useState("")

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setLoading(true)
    setLoadError("")
    void Promise.all([
      listVersions(apiRequest, controller.signal),
      listActiveModules(apiRequest, controller.signal),
    ])
      .then(([allVersions, activeModules]) => {
        if (!active) return
        setVersions(allVersions)
        setCatalog(activeModules)
      })
      .catch((error) => {
        if (active) setLoadError(listErrorMessage(error))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [apiRequest])

  function openNew(): void {
    setActionError("")
    setNotice("")
    setStaleAction(false)
    setViewing(null)
    setEditor({ kind: "new" })
    setEditorNotice("")
  }

  function openDraft(version: TemplateVersionDto): void {
    setActionError("")
    setNotice("")
    setStaleAction(false)
    setViewing(null)
    setEditor({ kind: "draft", version })
  }

  function viewVersion(version: TemplateVersionDto): void {
    setActionError("")
    setNotice("")
    setStaleAction(false)
    setEditor(null)
    setViewing(version)
  }

  function saveVersion(version: TemplateVersionDto): void {
    setVersions((current) => upsertVersion(current, version))
  }

  function publishVersion(version: TemplateVersionDto): void {
    setVersions((current) => upsertVersion(current, version))
    setEditor(null)
    setViewing(null)
    setNotice(`v${version.version_number} 已发布`)
  }

  function deleteVersion(versionId: string, versionNumber: number): void {
    setVersions((current) => current.filter((version) => version.version_id !== versionId))
    setEditor(null)
    setViewing(null)
    setNotice(`v${versionNumber} 草稿已删除`)
  }

  async function copyLatestVersion(group: TemplateHistoryGroup): Promise<void> {
    setActionError("")
    setNotice("")
    setStaleAction(false)
    setActingVersionId(group.latest.version_id)
    try {
      const copied = await apiRequest<TemplateVersionDto>(
        `/api/v1/industry-templates/${group.templateId}/versions`,
        { method: "POST", body: {} },
      )
      setVersions((current) => upsertVersion(current, copied))
      setViewing(null)
      setEditor({ kind: "draft", version: copied })
    } catch (error) {
      setActionError(templateActionMessage(error))
    } finally {
      setActingVersionId(null)
    }
  }

  async function deactivateVersion(version: TemplateVersionDto): Promise<void> {
    const confirmed = await dangerConfirm({
      title: "停用模板版本",
      description: `确定停用“${version.template_name}”v${version.version_number} 吗？历史版本仍会保留。`,
      confirmLabel: "停用",
    })
    if (!confirmed) return
    setActionError("")
    setNotice("")
    setStaleAction(false)
    setActingVersionId(version.version_id)
    try {
      const inactive = await apiRequest<TemplateVersionDto>(
        `/api/v1/industry-templates/versions/${version.version_id}/deactivate`,
        { method: "POST", body: { version: version.version } },
      )
      setVersions((current) => upsertVersion(current, inactive))
      setViewing((current) => current?.version_id === inactive.version_id ? inactive : current)
      setNotice(`v${version.version_number} 已停用`)
    } catch (error) {
      if (error instanceof ApiClientError && error.code === "stale_version") {
        setStaleAction(true)
      }
      setActionError(templateActionMessage(error))
    } finally {
      setActingVersionId(null)
    }
  }

  async function refreshVersions(): Promise<void> {
    setActingVersionId("refresh")
    try {
      const current = await listVersions(apiRequest, new AbortController().signal)
      setVersions(current)
      setStaleAction(false)
      setActionError("")
      setNotice("模板列表已刷新")
    } catch (error) {
      setActionError(listErrorMessage(error))
    } finally {
      setActingVersionId(null)
    }
  }

  const historyGroups = groupTemplateVersions(versions)

  if (editor) {
    const draft = editor.kind === "draft" ? editor.version : null
    return (
      <>
      <TemplateEditor
        key={draft?.version_id ?? "new-template"}
        draft={draft}
        catalog={catalog}
        onSaved={saveVersion}
        onPublished={publishVersion}
        onDeleted={deleteVersion}
        onCancel={() => setEditor(null)}
        onAIRequested={draft ? undefined : () => setAIAssistantOpen(true)}
        initialNotice={editorNotice}
      />
      {aiAssistantOpen ? (
        <IndustryTemplateAIAssistant
          catalog={catalog}
          onClose={() => setAIAssistantOpen(false)}
          onGenerated={(version) => {
            saveVersion(version)
            setEditorNotice("AI 已生成并保存草稿，请审核后手动发布")
            setAIAssistantOpen(false)
            setEditor({ kind: "draft", version })
          }}
        />
      ) : null}
      </>
    )
  }

  if (viewing) {
    const group = historyGroups.find((candidate) => candidate.versions.some((version) => version.version_id === viewing.version_id))
    const isLatest = group?.latest.version_id === viewing.version_id
    const hasDraft = Boolean(group?.draft)
    return (
      <div id="templates" className="page-stack">
        <header className="page-header">
          <div>
            <p className="eyebrow">系统管理</p>
            <h1>行业模板 · 查看</h1>
            <p className="supporting-copy">只读预览 v{viewing.version_number} 的内容与版本结构。</p>
          </div>
          <button className="secondary-button" type="button" onClick={() => setViewing(null)}>返回列表</button>
        </header>

        {notice ? <p className="notice" role="status">{notice}</p> : null}
        {actionError ? <p className="form-error banner" role="alert">{actionError}</p> : null}

        <section className="panel" aria-labelledby="template-view-title">
          <div className="panel-heading">
            <h2 id="template-view-title">{viewing.template_name}</h2>
            <span className={`badge ${statusClass(viewing.status)}`}>{statusLabel(viewing.status)}</span>
          </div>

          <dl className="template-view-meta">
            <div><dt>行业</dt><dd>{viewing.industry_name}</dd></div>
            <div><dt>版本</dt><dd>v{viewing.version_number}</dd></div>
            <div><dt>模块 / 任务</dt><dd>{viewing.modules.length} / {viewing.modules.reduce((total, module) => total + module.tasks.length, 0)}</dd></div>
            <div className="wide"><dt>说明</dt><dd>{viewing.description || "无说明"}</dd></div>
          </dl>

          <div className="template-view-modules">
            {viewing.modules.length === 0 ? <p className="empty-state">该版本暂未添加模块。</p> : viewing.modules.map((module) => (
              <article className="template-view-module" key={module.id}>
                <h3>{module.name}<code>{module.module_key}</code></h3>
                {module.description ? <p>{module.description}</p> : null}
                <div className="template-view-tasks">
                  {module.tasks.length === 0 ? <p className="empty-state">该模块暂无任务。</p> : module.tasks.map((task) => (
                    <div className="template-view-task" key={task.id}>
                      <div className="template-view-task-head">
                        <strong>{task.name}</strong>
                        <code>{task.task_key || "待填写"}</code>
                      </div>
                      {task.description ? <p>{task.description}</p> : null}
                      <p>预计 {task.duration_days} 个工作日 · 默认负责：{roleLabel(task.default_assignee_role)}</p>
                      {task.dependency_keys.length ? (
                        <div className="task-deps">
                          <span>依赖</span>{task.dependency_keys.map((key) => <span key={key}>{key}</span>)}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </article>
            ))}
          </div>

          <div className="template-view-actions">
            <button className="secondary-button" type="button" onClick={() => setViewing(null)}>返回列表</button>
            {viewing.status === "draft" || viewing.status === "published" ? (
              <button className="primary-button" type="button" onClick={() => openDraft(viewing)}>进入编辑</button>
            ) : null}
            {viewing.status === "published" ? (
              <button className="secondary-button" type="button" disabled={actingVersionId !== null} onClick={() => void deactivateVersion(viewing)}>停用</button>
            ) : null}
            {isLatest && !hasDraft && group ? (
              <button className="secondary-button" type="button" disabled={actingVersionId !== null} aria-label={`基于最新版本创建 v${group.latest.version_number + 1}`} onClick={() => void copyLatestVersion(group)}>创建副本</button>
            ) : null}
          </div>
        </section>
      </div>
    )
  }

  return (
    <div id="templates" className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">系统管理</p>
          <h1>行业模板</h1>
          <p className="supporting-copy">按版本管理行业交付流程，保留草稿、已发布和已停用历史。</p>
        </div>
        <button className="primary-button" type="button" onClick={openNew} disabled={loading || Boolean(loadError)}>新建模板</button>
      </header>

      {notice ? <p className="notice" role="status">{notice}</p> : null}
      {actionError ? <p className="form-error banner" role="alert">{actionError}</p> : null}
      {staleAction ? <button className="secondary-button" type="button" disabled={actingVersionId !== null} onClick={() => void refreshVersions()}>刷新模板列表</button> : null}

      <section className="panel table-panel" aria-labelledby="template-list-title">
        <div className="panel-heading"><h2 id="template-list-title">版本历史</h2><span>{versions.length} 个版本</span></div>
        {loading ? <p role="status">正在加载模板…</p> : loadError ? (
          <p className="form-error" role="alert">{loadError}</p>
        ) : versions.length === 0 ? <p className="empty-state">暂无行业模板，可以创建第一个 v1 草稿。</p> : (
          <div className="table-scroll"><table>
            <thead><tr><th>模板</th><th>行业</th><th>版本</th><th>状态</th><th>模块 / 任务</th><th>发布时间</th><th>操作</th></tr></thead>
            <tbody>{historyGroups.map((group) => group.versions.map((version) => {
              const taskCount = version.modules.reduce((total, module) => total + module.tasks.length, 0)
              const busy = actingVersionId === version.version_id || actingVersionId === group.latest.version_id
              const isLatest = version.version_id === group.latest.version_id
              return <tr key={version.version_id}>
                <td><strong>{version.template_name}</strong><small className="table-subline">{version.description || "无说明"}</small></td>
                <td>{version.industry_name}</td><td>v{version.version_number}</td>
                <td><span className={`badge ${statusClass(version.status)}`}>{statusLabel(version.status)}</span></td>
                <td>{version.modules.length} / {taskCount}</td><td>{formatPublishedAt(version.published_at)}</td>
                <td><div className="row-actions">
                  <button className="secondary-button compact" type="button" aria-label={`查看 v${version.version_number}`} onClick={() => viewVersion(version)}>查看</button>
                  {version.status === "draft" || version.status === "published" ? <button className="secondary-button compact" type="button" disabled={busy} aria-label={`编辑 v${version.version_number}`} onClick={() => openDraft(version)}>编辑</button> : null}
                  {isLatest && group.draft ? <span className="badge warning">已有草稿</span> : null}
                  {isLatest && !group.draft ? <button className="secondary-button compact" type="button" disabled={busy} aria-label={`基于最新版本创建 v${group.latest.version_number + 1}`} onClick={() => void copyLatestVersion(group)}>创建副本</button> : null}
                  {version.status === "published" ? <button className="secondary-button compact" type="button" disabled={busy} aria-label={`停用 v${version.version_number}`} onClick={() => void deactivateVersion(version)}>停用</button> : null}
                </div></td>
              </tr>
            }))}</tbody>
          </table></div>
        )}
      </section>
    </div>
  )
}

function listVersions(
  apiRequest: ReturnType<typeof useAuth>["apiRequest"],
  signal: AbortSignal,
): Promise<TemplateVersionDto[]> {
  return fetchAllPages({
    apiRequest,
    pathForPage: (page, pageSize) => `/api/v1/industry-templates?page=${page}&page_size=${pageSize}`,
    itemKey: (version) => version.version_id,
    validateItem: isTemplateVersionDto,
    signal,
  })
}

function listActiveModules(
  apiRequest: ReturnType<typeof useAuth>["apiRequest"],
  signal: AbortSignal,
): Promise<ModuleCatalogDto[]> {
  return fetchAllPages({
    apiRequest,
    pathForPage: (page, pageSize) => `/api/v1/modules?active=true&page=${page}&page_size=${pageSize}`,
    itemKey: (module) => module.id,
    validateItem: isModuleCatalogDto,
    signal,
  })
}

function groupTemplateVersions(versions: TemplateVersionDto[]): TemplateHistoryGroup[] {
  const grouped = new Map<string, TemplateVersionDto[]>()
  for (const version of versions) {
    const group = grouped.get(version.template_id)
    if (group) group.push(version)
    else grouped.set(version.template_id, [version])
  }
  return [...grouped.entries()].map(([templateId, groupVersions]) => {
    const ordered = [...groupVersions].sort((left, right) => right.version_number - left.version_number || left.version_id.localeCompare(right.version_id))
    return {
      templateId,
      versions: ordered,
      latest: ordered[0],
      draft: ordered.find((version) => version.status === "draft") ?? null,
    }
  })
}

function upsertVersion(versions: TemplateVersionDto[], changed: TemplateVersionDto): TemplateVersionDto[] {
  const withoutChanged = versions.filter((version) => version.version_id !== changed.version_id)
  return [...withoutChanged, changed].sort((left, right) => {
    const name = left.template_name.localeCompare(right.template_name, "zh-CN")
    return name || right.version_number - left.version_number || left.version_id.localeCompare(right.version_id)
  })
}

function statusLabel(status: TemplateVersionDto["status"]): string {
  return { draft: "草稿", published: "已发布", inactive: "已停用" }[status]
}

function statusClass(status: TemplateVersionDto["status"]): string {
  return { draft: "warning", published: "success", inactive: "muted" }[status]
}

function roleLabel(role: string): string {
  return { admin: "管理员", project_lead: "项目负责人", fde_engineer: "FDE 工程师", viewer: "查看者" }[role] ?? role
}

function formatPublishedAt(value: string | null): string {
  if (!value) return "—"
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? "—" : new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(date)
}

function listErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "forbidden") return "当前账号无权查看行业模板。"
  return "无法加载行业模板，请稍后重试。"
}

function templateActionMessage(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "template_draft_exists") return "该模板已有可编辑草稿。"
  if (error instanceof ApiClientError && error.code === "authentication_refreshed_resubmit") return "登录状态已刷新，请重新提交本次操作。"
  if (error instanceof ApiClientError && error.code === "stale_version") return "模板已被其他操作更新；本地状态未改变，请刷新后重试。"
  return "模板操作失败，请稍后重试。"
}
