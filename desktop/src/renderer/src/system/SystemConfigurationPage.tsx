import { useEffect, useState, type FormEvent, type ReactNode } from "react"
import { useAuth } from "../auth/AuthProvider"

type Values = Record<string, string | number | boolean | null>
interface Configuration { values: Values; secrets_configured: Record<string, boolean>; version: number; bootstrap_fields: string[] }

const secretLabels: Record<string, string> = {
  deepseek_api_key: "DeepSeek API Key", kimi_project_presurvey_api_key: "Kimi API Key",
  dsh_service_token: "AI Server 服务令牌", weixin_credential_key: "微信凭据加密密钥",
  clawbot_gateway_token: "ClawBot 网关令牌", oss_access_key_id: "OSS AccessKey ID",
  oss_access_key_secret: "OSS AccessKey Secret",
}

export function SystemConfigurationPage() {
  const { apiRequest } = useAuth()
  const [configuration, setConfiguration] = useState<Configuration | null>(null)
  const [values, setValues] = useState<Values>({})
  const [secrets, setSecrets] = useState<Record<string, string>>({})
  const [clearSecrets, setClearSecrets] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")

  async function load() {
    const result = await apiRequest<Configuration>("/api/v1/system/configuration", { method: "GET" })
    setConfiguration(result); setValues(result.values); setSecrets({}); setClearSecrets([])
  }
  useEffect(() => { void load().catch((caught) => setError(messageOf(caught))) }, [])
  function set(key: string, value: string | number | boolean | null) { setValues(current => ({ ...current, [key]: value })) }
  async function save(event: FormEvent) {
    event.preventDefault(); if (!configuration || busy) return
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await apiRequest<Configuration>("/api/v1/system/configuration", { method: "PUT", body: { values, secrets, clear_secrets: clearSecrets, version: configuration.version } })
      setConfiguration(result); setValues(result.values); setSecrets({}); setClearSecrets([]); setNotice("系统配置已保存并生效。")
    } catch (caught) { setError(messageOf(caught)) } finally { setBusy(false) }
  }
  if (!configuration) return <section className="page"><p role="status">正在加载系统配置…</p>{error ? <p role="alert" className="form-error">{error}</p> : null}</section>
  const secret = (key: string) => <label className="field"><span>{secretLabels[key]}</span><input type="password" autoComplete="new-password" value={secrets[key] || ""} placeholder={configuration.secrets_configured[key] ? "已加密保存；留空保持不变" : "尚未配置"} onChange={event => { setSecrets(current => ({ ...current, [key]: event.target.value })); setClearSecrets(current => current.filter(item => item !== key)) }} />{configuration.secrets_configured[key] ? <label className="inline-check"><input type="checkbox" checked={clearSecrets.includes(key)} onChange={event => setClearSecrets(current => event.target.checked ? [...current, key] : current.filter(item => item !== key))} />清除此密钥</label> : null}</label>
  return <section className="page system-configuration-page">
    <header className="page-heading"><div><p className="eyebrow">管理员设置</p><h1>系统配置</h1><p>集中管理外部服务、存储和安全集成。密钥只在服务端加密保存，不会回显。</p></div></header>
    {error ? <p role="alert" className="form-error banner">{error}</p> : null}{notice ? <p role="status" className="notice">{notice}</p> : null}
    <p className="panel supporting-copy">数据库、Redis、JWT 签名密钥、API 监听地址和桌面端 API 地址必须在服务启动前配置；其余运行配置均在本页管理。</p>
    <form onSubmit={save} className="extension-stack">
      <ConfigSection title="AI 模型服务" description="供行业模板、调研、机会分析与文档生成使用。对话模型也可在“AI 与扩展”中配置。">
        <TextField label="DeepSeek API 地址" value={values.deepseek_base_url} onChange={v => set("deepseek_base_url", v)} />{secret("deepseek_api_key")}
        <TextField label="行业模板模型" value={values.deepseek_industry_template_model} onChange={v => set("deepseek_industry_template_model", v)} /><TextField label="项目预调研模型" value={values.deepseek_project_presurvey_model} onChange={v => set("deepseek_project_presurvey_model", v)} />
        <TextField label="机会分析模型" value={values.deepseek_ai_opportunity_model} onChange={v => set("deepseek_ai_opportunity_model", v)} /><TextField label="调研导出模型" value={values.deepseek_research_export_model} onChange={v => set("deepseek_research_export_model", v)} />
        <TextField label="文档生成模型" value={values.deepseek_document_generation_model} onChange={v => set("deepseek_document_generation_model", v)} /><NumberField label="DeepSeek 超时（秒）" value={values.deepseek_timeout_seconds} onChange={v => set("deepseek_timeout_seconds", v)} />
        <TextField label="Kimi API 地址" value={values.kimi_base_url} onChange={v => set("kimi_base_url", v)} />{secret("kimi_project_presurvey_api_key")}<TextField label="Kimi 模型" value={values.kimi_project_presurvey_model} onChange={v => set("kimi_project_presurvey_model", v)} /><NumberField label="Kimi 超时（秒）" value={values.kimi_timeout_seconds} onChange={v => set("kimi_timeout_seconds", v)} />
      </ConfigSection>
      <ConfigSection title="AI Server 与扩展市场" description="启用前请先保存服务令牌；内网 HTTP 仅建议用于开发环境。">
        <CheckField label="启用 AI Server" checked={values.dsh_enabled} onChange={v => set("dsh_enabled", v)} /><TextField label="AI Server 地址" value={values.dsh_base_url} onChange={v => set("dsh_base_url", v)} />{secret("dsh_service_token")}<TextField label="运行时版本" value={values.dsh_runtime_version} onChange={v => set("dsh_runtime_version", v)} /><TextField label="协议版本" value={values.dsh_protocol_version} onChange={v => set("dsh_protocol_version", v)} /><NumberField label="执行超时（秒）" value={values.dsh_timeout_seconds} onChange={v => set("dsh_timeout_seconds", v)} /><TextField label="内部 API 地址" value={values.ai_internal_api_url} onChange={v => set("ai_internal_api_url", v)} />
        <CheckField label="启用扩展市场" checked={values.dsh_market_enabled} onChange={v => set("dsh_market_enabled", v)} /><TextField label="扩展市场清单地址" value={values.dsh_market_registry_url} onChange={v => set("dsh_market_registry_url", v)} /><NumberField label="市场请求超时（秒）" value={values.dsh_market_timeout_seconds} onChange={v => set("dsh_market_timeout_seconds", v)} /><NumberField label="市场清单最大字节数" value={values.dsh_market_max_catalog_bytes} onChange={v => set("dsh_market_max_catalog_bytes", v)} />
      </ConfigSection>
      <ConfigSection title="微信与 ClawBot" description="关闭时不接受对应渠道请求；凭据不会发送到桌面端。">
        <CheckField label="启用微信渠道" checked={values.weixin_enabled} onChange={v => set("weixin_enabled", v)} />{secret("weixin_credential_key")}<CheckField label="启用 ClawBot" checked={values.clawbot_enabled} onChange={v => set("clawbot_enabled", v)} />{secret("clawbot_gateway_token")}
      </ConfigSection>
      <ConfigSection title="文件存储与安全" description="切换存储后只影响新文件；迁移已有文件需另行执行。">
        <label className="field"><span>存储方式</span><select value={String(values.storage_backend)} onChange={event => set("storage_backend", event.target.value)}><option value="local">本地存储</option><option value="oss">兼容 OSS 的对象存储</option></select></label><TextField label="本地存储目录" value={values.local_storage_root} onChange={v => set("local_storage_root", v)} /><TextField label="OSS Endpoint" value={values.oss_endpoint} onChange={v => set("oss_endpoint", v || null)} /><TextField label="OSS Bucket" value={values.oss_bucket} onChange={v => set("oss_bucket", v || null)} />{secret("oss_access_key_id")}{secret("oss_access_key_secret")}<TextField label="ClamAV 主机" value={values.clamav_host} onChange={v => set("clamav_host", v)} /><NumberField label="ClamAV 端口" value={values.clamav_port} onChange={v => set("clamav_port", v)} /><NumberField label="扫描超时（秒）" value={values.clamav_timeout_seconds} onChange={v => set("clamav_timeout_seconds", v)} /><NumberField label="Socket 超时（秒）" value={values.clamav_socket_timeout_seconds} onChange={v => set("clamav_socket_timeout_seconds", v)} />
      </ConfigSection>
      <div className="form-actions"><button className="primary-button" type="submit" disabled={busy}>{busy ? "正在保存…" : "保存系统配置"}</button></div>
    </form>
  </section>
}

function ConfigSection({ title, description, children }: { title: string; description: string; children: ReactNode }) { return <section className="panel"><div className="panel-heading"><div><h2>{title}</h2><p>{description}</p></div></div><div className="form-grid system-config-grid">{children}</div></section> }
function TextField({ label, value, onChange }: { label: string; value: unknown; onChange(value: string): void }) { return <label className="field"><span>{label}</span><input value={value == null ? "" : String(value)} onChange={event => onChange(event.target.value)} /></label> }
function NumberField({ label, value, onChange }: { label: string; value: unknown; onChange(value: number): void }) { return <label className="field"><span>{label}</span><input type="number" value={Number(value)} onChange={event => onChange(Number(event.target.value))} /></label> }
function CheckField({ label, checked, onChange }: { label: string; checked: unknown; onChange(value: boolean): void }) { return <label className="inline-check system-config-check"><input type="checkbox" checked={Boolean(checked)} onChange={event => onChange(event.target.checked)} /><span>{label}</span></label> }
function messageOf(error: unknown) { return error instanceof Error ? error.message : "系统配置操作失败。" }
