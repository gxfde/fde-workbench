import { useEffect, useState } from "react"
import { aiCapabilityLabels } from "../ai/accessLabels"
import { useAuth } from "../auth/AuthProvider"
import { ModelPreferencesPanel } from "./ModelPreferencesPanel"
import { LcscToolCard } from "./LcscToolCard"
import "./extensions.css"

interface Skill { id: string; scope: "public" | "personal"; key: string; name: string; description: string; status: string; current_version: number; can_edit: boolean }
interface SkillDetail extends Skill { instructions: string; manifest: Record<string, unknown>; required_capabilities: string[] }
interface Plugin { id: string; name: string; description: string; publisher: string; version?: string; installed_version?: string; installation_status?: string }
interface PluginDetail extends Plugin { category: string; capabilities: string[]; install_available: boolean }
type PluginAction = "install" | "upgrade" | "rollback" | "disable" | "remove"
interface PluginRequest { id: string; plugin: { id: string; name: string }; target_user: { name: string }; action: PluginAction; target_version: string; status: "pending" | "approved" | "rejected" | "executed" | "failed" }
export interface ModelPreference { id: string; scope: "public" | "personal"; name: string; provider: string; base_url: string; model: string; is_default: boolean; supports_tools: boolean; credential_configured: boolean; can_edit: boolean; version: number }
interface ExtensionCenter {
  skills: Skill[]; tools: Array<{key: string; description: string; capability: string | null}>; plugins: Plugin[]; plugin_requests?: PluginRequest[]
  models: Array<{ id: string; provider: { name: string }; key: string; name: string; supports_tools: boolean; supports_json: boolean }>
  model_preferences?: ModelPreference[]; model_credentials_ready?: boolean
  permissions: { can_manage_personal_skills: boolean; can_manage_system: boolean }
}
const emptySkill = { key: "", name: "", description: "", instructions: "", manifest: { entrypoint: "SKILL.md", format: "markdown" } as Record<string, unknown>, required_capabilities: [] as string[] }
// Display terminology only: retain the upstream package name/id for installation.
const displayPlugin = <T extends Plugin,>(plugin: T): T => ({ ...plugin, description: plugin.description.replaceAll("DSH", "AI Server") })

export function ExtensionsPage({ initialTab }: { initialTab?: 'tools' }) {
  const { apiRequest } = useAuth()
  const [data, setData] = useState<ExtensionCenter | null>(null)
  const [tab, setTab] = useState<"skills" | "tools" | "models">(initialTab || "skills")
  const [draft, setDraft] = useState(emptySkill)
  const [editingSkill, setEditingSkill] = useState(false)
  const [skillScope, setSkillScope] = useState<"personal" | "public">("personal")
  const [pluginDetail, setPluginDetail] = useState<PluginDetail | null>(null)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [busy, setBusy] = useState(false)
  async function load(): Promise<void> { const result = await apiRequest<ExtensionCenter>("/api/v1/extensions", { method: "GET" }); setData({ ...result, plugins: result.plugins.map(displayPlugin) }) }
  useEffect(() => { void load().catch((caught) => setError(messageOf(caught))) }, [])
  useEffect(() => {
    if (!editingSkill && !pluginDetail) return
    const close = (event: KeyboardEvent) => { if (event.key === "Escape" && !busy) { setEditingSkill(false); setPluginDetail(null) } }
    window.addEventListener("keydown", close)
    return () => window.removeEventListener("keydown", close)
  }, [editingSkill, pluginDetail, busy])
  async function perform(action: () => Promise<void>): Promise<void> {
    if (busy) return
    setBusy(true); setError(""); setNotice("")
    try { await action() } catch (caught) { setError(messageOf(caught)) } finally { setBusy(false) }
  }
  async function editSkill(skill: Skill): Promise<void> {
    await perform(async () => {
      const detail = await apiRequest<SkillDetail>(`/api/v1/extensions/skills/${skill.id}`, { method: "GET" })
      setSkillScope(detail.scope)
      setDraft({ key: detail.key, name: detail.name, description: detail.description, instructions: detail.instructions, manifest: detail.manifest, required_capabilities: detail.required_capabilities })
      setEditingSkill(true)
    })
  }
  async function showPlugin(id: string): Promise<void> { await perform(async () => { setPluginDetail(displayPlugin(await apiRequest<PluginDetail>(`/api/v1/extensions/plugins/${id}`, { method: "GET" }))) }) }
  async function changePlugin(pluginId: string, action: PluginAction): Promise<void> {
    await perform(async () => {
      const change = await apiRequest<PluginRequest>(`/api/v1/extensions/plugins/${pluginId}/requests`, { method: "POST", body: { action, target_version: "", reason: "由扩展中心提交" } })
      if (data?.permissions.can_manage_system) {
        await apiRequest(`/api/v1/extensions/plugin-requests/${change.id}/decision`, { method: "POST", body: { decision: "approve", reason: "管理员从扩展中心执行" } })
        setNotice(`插件${pluginActionLabel(action)}已执行。`)
      } else setNotice("插件申请已提交，等待管理员审批。")
      await load()
      if (pluginDetail?.id === pluginId) setPluginDetail(await apiRequest<PluginDetail>(`/api/v1/extensions/plugins/${pluginId}`, { method: "GET" }))
    })
  }
  async function decidePlugin(requestId: string, decision: "approve" | "reject"): Promise<void> {
    await perform(async () => {
      await apiRequest(`/api/v1/extensions/plugin-requests/${requestId}/decision`, { method: "POST", body: { decision, reason: decision === "approve" ? "管理员批准执行" : "暂不批准" } })
      setNotice(decision === "approve" ? "插件变更已由 AI Server 执行。" : "插件申请已拒绝。")
      await load()
    })
  }
  const canManage = data?.permissions.can_manage_system ?? false
  return <section className="page extensions-page">
    <header className="page-heading"><div><p className="eyebrow">能力配置</p><h1>AI 与扩展</h1><p>集中查看 Skills、可调用工具与已登记插件，以及模型配置。</p></div></header>
    {error ? <p className="form-error banner" role="alert">{error}</p> : null}
    {notice ? <p className="notice" role="status">{notice}</p> : null}
    {!data ? <p role="status">正在加载扩展配置…</p> : <div className="extension-stack">
      <div className="extension-tabs" role="tablist" aria-label="AI 与扩展分类"><button id="skills-tab" role="tab" aria-selected={tab === "skills"} aria-controls="skills-panel" onClick={() => setTab("skills")}>Skills</button><button id="tools-tab" role="tab" aria-selected={tab === "tools"} aria-controls="tools-panel" onClick={() => setTab("tools")}>工具 / 插件</button><button id="models-tab" role="tab" aria-selected={tab === "models"} aria-controls="models-panel" onClick={() => setTab("models")}>模型管理</button></div>
      {tab === "skills" ? <section id="skills-panel" role="tabpanel" aria-labelledby="skills-tab" className="panel extension-panel"><div className="panel-heading"><div><h2>Skills</h2><p>公共 Skill 供所有已开通 AI 的账号使用；个人 Skill 仅自己可见。</p></div><div className="extension-heading-actions">
        {canManage ? <button className="secondary-button" onClick={() => { setDraft(emptySkill); setSkillScope("public"); setEditingSkill(true) }}>新建公共 Skill</button> : null}
        {data.permissions.can_manage_personal_skills ? <button className="primary-button" onClick={() => { setDraft(emptySkill); setSkillScope("personal"); setEditingSkill(true) }}>新建个人 Skill</button> : null}
      </div></div><div className="extension-card-grid">{data.skills.length ? data.skills.map((skill) => <article key={skill.id} className="extension-item"><div><span className={`extension-scope ${skill.scope}`}>{skill.scope === "public" ? "公共" : "个人"}</span><strong>{skill.name}</strong>{skill.status === "disabled" ? <span className="extension-scope">已停用</span> : null}</div><p>{skill.description || "暂无说明"}</p><small>{skill.key} · v{skill.current_version}</small>
        {skill.can_edit ? <div className="plugin-actions"><button className="secondary-button" disabled={busy} onClick={() => void editSkill(skill)}>编辑</button><button className="secondary-button" disabled={busy} onClick={() => void perform(async () => { await apiRequest(`/api/v1/extensions/skills/${skill.id}`, { method: "PATCH", body: { status: skill.status === "active" ? "disabled" : "active" } }); await load() })}>{skill.status === "active" ? "停用" : "启用"}</button></div> : null}
      </article>) : <p className="empty-copy">还没有 Skill，可以新建一个。</p>}</div></section> : null}
      {tab === "tools" ? <section id="tools-panel" role="tabpanel" aria-labelledby="tools-tab" className="panel extension-panel">
        <div className="panel-heading"><div><h2>工具 / 插件</h2><p>点击「立即使用」进入工具详情页，执行操作并查看结果与日志；其余能力可通过 AI 对话调用。</p></div></div>
        <div className="extension-card-grid">{data.tools?.some(tool => tool.key === "lcsc_search") ? <><LcscToolCard variant="lcsc-browser-baseline" /><LcscToolCard variant="lcsc-browser-jev" /><article className="extension-item lcsc-tool-card"><div className="lcsc-tool-heading"><div><strong>立创商城查询执行记录对比</strong><p>选择默认模型版与 Jev 版的已有执行记录，查看完整结果和日志，并生成 AI 对比分析。</p></div></div><div className="lcsc-card-footer"><a className="primary-button lcsc-use-link" href="#extensions/tools/lcsc-compare">立即使用</a><span className="extension-scope">对比工具</span></div></article></> : null}{(data.tools || []).filter(tool => tool.key !== "lcsc_search").map((tool) => <article key={tool.key} className="extension-item"><strong>{tool.key}</strong><p>{tool.description}</p><small>可通过 AI 对话调用{tool.capability ? ` · 需要 ${aiCapabilityLabels[tool.capability] || tool.capability} 权限` : ""}</small></article>)}</div>
        <div className="extension-items"><h3>已登记插件</h3>{data.plugins.length ? data.plugins.map((plugin) => <article className="extension-item" key={plugin.id}><button className="extension-name-button" disabled={busy} onClick={() => void showPlugin(plugin.id)}>{plugin.name}</button><p>{plugin.description}</p><small>{plugin.installed_version ? `已安装 v${plugin.installed_version}` : "未安装"}</small></article>) : <p className="empty-copy">暂无已登记插件。</p>}</div>
        {(data.plugin_requests || []).length ? <div className="extension-items"><h3>{canManage ? "插件变更审批" : "我的插件申请"}</h3>{data.plugin_requests!.map((item) => <article key={item.id} className="extension-item"><div><strong>{item.plugin.name}</strong><span className="extension-scope">{pluginRequestStatus(item.status)}</span></div><p>{pluginActionLabel(item.action)} · {item.target_version === "catalog" ? "目录版本（安装时锁定）" : item.target_version || "未指定版本"}{canManage ? ` · ${item.target_user.name}` : ""}</p>{canManage && item.status === "pending" ? <div className="plugin-actions"><button className="secondary-button" disabled={busy} onClick={() => void decidePlugin(item.id, "reject")}>拒绝</button><button className="primary-button" disabled={busy} onClick={() => void decidePlugin(item.id, "approve")}>批准并执行</button></div> : null}</article>)}</div> : null}
      </section> : null}
      {tab === "models" ? <section id="models-panel" role="tabpanel" aria-labelledby="models-tab" className="panel extension-panel"><ModelPreferencesPanel items={data.model_preferences || []} canManage={canManage} credentialsReady={data.model_credentials_ready !== false} onSaved={load} />
        {data.models.length ? <><h3 className="legacy-model-title">系统登记模型</h3><div className="extension-card-grid">{data.models.map((model) => <article key={model.id} className="extension-item"><strong>{model.name}</strong><p>{model.provider.name} · {model.key}</p><small>{model.supports_tools ? "支持工具调用" : "普通对话"}{model.supports_json ? " · 支持 JSON" : ""}</small></article>)}</div></> : null}
      </section> : null}
    </div>}
    {editingSkill ? <div className="dialog-backdrop"><section className="dialog extension-dialog" role="dialog" aria-modal="true" aria-labelledby="skill-editor-title"><h2 id="skill-editor-title">{skillScope === "public" ? "公共" : "个人"} Skill</h2><form onSubmit={(event) => { event.preventDefault(); void perform(async () => { await apiRequest(`/api/v1/extensions/skills/${skillScope}`, { method: "POST", body: draft }); setDraft(emptySkill); setEditingSkill(false); setNotice("Skill 已保存，历史版本保留。"); await load() }) }}><div className="skill-editor"><label className="field"><span>标识</span><input autoFocus aria-label="Skill 标识" required value={draft.key} onChange={(event) => setDraft({ ...draft, key: event.target.value })} /></label><label className="field"><span>名称</span><input aria-label="Skill 名称" required value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label><label className="field full"><span>说明</span><input aria-label="Skill 说明" value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label><label className="field full"><span>SKILL.md 指令</span><textarea aria-label="SKILL.md 指令" required rows={9} value={draft.instructions} onChange={(event) => setDraft({ ...draft, instructions: event.target.value })} /></label></div><div className="dialog-actions"><button className="secondary-button" disabled={busy} type="button" onClick={() => setEditingSkill(false)}>取消</button><button className="primary-button" disabled={busy} type="submit">保存 Skill</button></div></form></section></div> : null}
    {pluginDetail ? <div className="dialog-backdrop"><section className="dialog extension-dialog" role="dialog" aria-modal="true" aria-labelledby="plugin-detail-title"><h2 id="plugin-detail-title">{pluginDetail.name}</h2><p>{pluginDetail.description || "暂无说明"}</p><dl className="plugin-detail-list"><dt>发布者</dt><dd>{pluginDetail.publisher}</dd><dt>分类</dt><dd>{pluginDetail.category || "未分类"}</dd><dt>安装状态</dt><dd>{pluginDetail.installation_status === "installed" ? `已安装 v${pluginDetail.installed_version}` : pluginDetail.installation_status === "disabled" ? "已停用" : "未安装"}</dd><dt>权限</dt><dd>{pluginDetail.capabilities.length ? pluginDetail.capabilities.map((item) => aiCapabilityLabels[item] || "扩展能力").join("、") : "安装时由运行环境校验插件清单"}</dd></dl><p className="supporting-copy">第三方插件由其发布者维护。安装由隔离运行环境执行，只有执行成功才会标记为已安装。</p><div className="dialog-actions"><button className="secondary-button" disabled={busy} onClick={() => setPluginDetail(null)}>关闭</button>{pluginDetail.install_available ? pluginDetail.installation_status === "installed" || pluginDetail.installation_status === "disabled" ? <button className="secondary-button" disabled={busy} onClick={() => void changePlugin(pluginDetail.id, "remove")}>{canManage ? "卸载插件" : "申请卸载"}</button> : <button className="primary-button" disabled={busy} onClick={() => void changePlugin(pluginDetail.id, "install")}>{canManage ? "安装插件" : "申请安装"}</button> : <span className="supporting-copy">插件运行环境暂不可用</span>}</div></section></div> : null}
  </section>
}
function messageOf(caught: unknown): string { return caught instanceof Error ? caught.message : "操作失败，请稍后重试。" }
function pluginActionLabel(action: PluginAction): string { return ({ install: "安装", upgrade: "升级", rollback: "回滚", disable: "停用", remove: "卸载" })[action] }
function pluginRequestStatus(status: PluginRequest["status"]): string { return ({ pending: "待审批", approved: "已批准", rejected: "已拒绝", executed: "已执行", failed: "执行失败" })[status] }
