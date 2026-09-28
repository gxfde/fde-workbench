import { useEffect, useState, type FormEvent } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { resultFields, variantName, type LcscVariant, type LcscRun, type ResultField, type Usage } from './LcscToolCard'
import './extensions.css'

const seconds = (ms?: number) => ms == null ? '未记录' : `${(ms / 1000).toFixed(2)} 秒`
const money = (value?: string | null) => value == null ? '待核算' : `¥${Number(value).toFixed(6)}`
const tokens = (usage?: Usage) => usage?.input_tokens == null || usage?.output_tokens == null ? null : usage.input_tokens + usage.output_tokens
const statusName = (s: string) => ({ succeeded: '已完成', partial: '部分完成', failed: '失败', running: '执行中', selecting: '模型判断中', thinking: '目标核验中', selected: '提取中' }[s] || s)
const presetFields: ResultField[] = ['parameters', 'pins', 'price', 'datasheet']

export function LcscToolPage({ variant }: { variant: LcscVariant }) {
  const { apiRequest } = useAuth()
  const [query, setQuery] = useState('')
  const [purpose, setPurpose] = useState('')
  const [fields, setFields] = useState<ResultField[]>(['parameters', 'price'])
  const allPresetsSelected = presetFields.every(field => fields.includes(field))
  const [track, setTrack] = useState(true)
  const [runs, setRuns] = useState<LcscRun[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [log, setLog] = useState<LcscRun | null>(null)
  const [latest, setLatest] = useState('')
  const jev = variant === 'lcsc-browser-jev'
  async function load() {
    const value = await apiRequest<{items: LcscRun[]}>('/api/v1/ai/lcsc-runs', { method: 'GET' })
    setRuns(value.items)
  }
  useEffect(() => { void load().catch(e => setError(e.message)) }, [])
  useEffect(() => {
    if (!busy) return
    const interval = setInterval(() => { void load().catch(() => {}) }, 2500)
    return () => clearInterval(interval)
  }, [busy])
  useEffect(() => {
    if (!log) return
    const close = (e: KeyboardEvent) => { if (e.key === 'Escape') setLog(null) }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [log])
  async function execute(event: FormEvent) {
    event.preventDefault()
    if (busy || !query.trim() || !fields.length || (fields.includes('other') && !purpose.trim())) return
    setBusy(true); setError('')
    try {
      const run = await apiRequest<LcscRun>('/api/v1/ai/lcsc-runs/desktop-execute', {
        method: 'POST', body: { skill_key: variant, query: query.trim(), fields, track, ...(fields.includes('other') ? { purpose: purpose.trim() } : {}) },
      })
      setLatest(run.id)
      setRuns(current => [run, ...current.filter(r => r.id !== run.id)])
      if (run.status === 'failed') setError(run.result.client_error || run.steps.at(-1)?.detail || '执行失败，请查看操作日志。')
    } catch (e) { setError(e instanceof Error ? e.message : '查询失败。'); void load().catch(() => {}) }
    finally { setBusy(false) }
  }
  return <section className="page-stack lcsc-detail-page">
    <header className="page-header"><div><h1>立创商城元器件查询 · {variantName(variant)}</h1><p className="supporting-copy">搜索、选择商品、读取页面和下载规格书。{jev ? 'Jev 与默认模型协作执行。' : '候选由当前默认模型判断。'}</p></div><a className="secondary-button button-link compact" href="#extensions?tab=tools">返回工具 / 插件</a></header>
    <form className="panel lcsc-query-panel" onSubmit={event => void execute(event)}>
      <label className="field"><span>搜索内容</span><input required maxLength={120} value={query} disabled={busy} onChange={e => setQuery(e.target.value)} placeholder="输入元器件型号、名称或规格要求，例如 STM32F103C8T6" /></label>
      <fieldset disabled={busy} className="lcsc-field-picker"><legend><span className="lcsc-field-heading"><span>需要搜索的结果（可多选）</span><button type="button" className="secondary-button compact" disabled={busy} title="仅控制四个预设选项，不包含其他" onClick={() => setFields(current => current.every(field => field === 'other') || !presetFields.every(field => current.includes(field)) ? [...presetFields, ...current.filter(field => field === 'other')] : current.filter(field => field === 'other'))}>{allPresetsSelected ? '取消选择' : '全选'}</button></span></legend>{Object.entries(resultFields).map(([key, label]) => <label key={key}><input type="checkbox" checked={fields.includes(key as ResultField)} onChange={e => setFields(current => e.target.checked ? [...current, key as ResultField] : current.filter(f => f !== key))} />{label}</label>)}</fieldset>
      {fields.includes('other') ? <label className="field"><span>其他查询目的</span><textarea aria-label="其他查询目的" required maxLength={500} disabled={busy} value={purpose} onChange={e => setPurpose(e.target.value)} placeholder="例如：查看该元器件的包装方式和最小包装数量" /><small className="field-hint">AI 根据每一步的页面状态实时选择只读操作，最多 12 步。仅浏览商城公开资料，不登录、加购或下单；无法完成会说明。</small></label> : null}
      <p className="field-hint">引脚数读取自数据手册弹窗的引脚图；规格书保存到「下载 / FDE规格书」。价格为查询时的数量阶梯报价。</p>
      <p className="field-hint">{jev ? '使用模型管理中的 Jev 凭据；选择“其他”时，Jev 判断下一步浏览动作，默认通用模型负责回答及必要的重规划，费用一并记录。' : '使用模型管理中的默认通用模型，不调用 Jev。'}</p>
      <div className="lcsc-execute-row"><label><input type="checkbox" checked={track} disabled={busy} onChange={e => setTrack(e.target.checked)} />跟踪执行：打开内置浏览器，实时查看操作</label><button className="primary-button" disabled={busy || !query.trim() || !fields.length}>{busy ? '正在执行…' : '执行查询'}</button></div>
      {busy ? <p role="status" className="supporting-copy">浏览器正在执行，可在下方查看当前记录。关闭执行浏览器会中断本次查询。</p> : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
    </form>
    <section className="lcsc-record-list"><div className="panel-heading"><h2>执行记录</h2><button className="secondary-button" onClick={() => void load().catch(e => setError(e.message))}>刷新记录</button></div>
      {runs.filter(r => r.skill_key === variant).map(run => <RunCard key={run.id} run={run} latest={run.id === latest} onLog={() => setLog(run)} />)}
      {!runs.some(r => r.skill_key === variant) ? <p className="empty-state">暂无执行记录，完成一次查询后会在这里展示完整结果。</p> : null}
    </section>
    {log ? <div className="dialog-backdrop"><section className="panel lcsc-log-dialog" role="dialog" aria-modal="true" aria-label="操作日志"><div className="panel-heading"><div><h2>操作日志 · {log.query}</h2><p>{variantName(log.skill_key)} · {log.id}</p></div><button className="secondary-button" onClick={() => setLog(null)}>关闭</button></div>
      <div className="lcsc-log-scroll"><Metrics run={log} />
      <div className="table-scroll"><table><thead><tr><th>步骤 / 操作</th><th>开始 / 耗时</th><th>使用模型</th><th>输入 / 输出 Token</th><th>人民币估算</th></tr></thead><tbody>{log.steps.map((s, i) => <tr key={i}><td className="wrap-cell">{i + 1}. {s.detail}{s.status === 'failed' ? <span className="form-error"> · 失败</span> : null}</td><td>{seconds(s.at_ms)} / {seconds(s.duration_ms)}</td><td>{s.model || '浏览器 / 代码'}</td><td>{s.usage ? `${s.usage.input_tokens ?? '未知'} / ${s.usage.output_tokens ?? '未知'}` : '未记录'}</td><td>{money(s.cost?.cny_estimate)}</td></tr>)}</tbody></table></div>
      <p className="supporting-copy">Token 使用供应商返回值；人民币为估算，浏览器和代码步骤不消耗模型 Token。{log.cost.note} {log.cost.usd_cny_rate ? `美元兑人民币 ${log.cost.usd_cny_rate}（${log.cost.fx_date}）。` : ''}</p>
      <details><summary>候选商品与选择依据</summary><p>{log.result.selection?.reason || (log.result.selection?.confidence != null ? `Jev 判断置信度：${(log.result.selection.confidence * 100).toFixed(1)}%` : '无额外说明')}</p>{log.candidates.map((c, i) => <article className="lcsc-candidate-evidence" key={i}><strong>{i + 1}. {c.title}</strong><pre>{c.visible_text}</pre></article>)}</details>
    </div></section></div> : null}
  </section>
}

function Metrics({ run }: { run: LcscRun }) {
  return <div className="lcsc-metrics"><div><span>总耗时</span><strong>{seconds(run.duration_ms)}</strong></div><div><span>模型判断耗时</span><strong>{seconds(run.result.model_duration_ms)}</strong></div><div><span>模型 Token</span><strong>{tokens(run.usage)?.toLocaleString() ?? '未知'}</strong></div><div><span>模型费用估算</span><strong>{money(run.cost.cny_estimate)}</strong></div></div>
}
export function RunCard({ run, onLog, latest, inlineLog = false, initiallyExpanded = false }: { run: LcscRun; onLog(): void; latest: boolean; inlineLog?: boolean; initiallyExpanded?: boolean }) {
  const [expanded, setExpanded] = useState(initiallyExpanded)
  const [copyStatus, setCopyStatus] = useState('')
  async function copyId() {
    try {
      if(window.fde.app.copyLcscRunId) await window.fde.app.copyLcscRunId(run.id)
      else await navigator.clipboard.writeText(run.id)
      setCopyStatus('已复制')
    } catch {setCopyStatus('复制失败，请选中 ID 手动复制')}
  }
  const data = run.result.details, product = run.result.selected_product
  const purpose = run.result.purpose || data?.other?.purpose
  const instructions = run.result.fields?.map(f => f==='other' ? `其他（${purpose || '未记录查询目的'}）` : resultFields[f]).join(' · ') || '旧版查询记录'
  return <article className={`panel lcsc-result-card${latest ? ' latest' : ''}`}><div className="panel-heading lcsc-record-heading"><div><h3>{product?.title || run.query}</h3><small>{new Date(run.started_at).toLocaleString()}</small></div><div className="lcsc-record-controls"><span className="extension-scope">{statusName(run.status)}</span><button className="secondary-button" aria-expanded={expanded} aria-controls={`record-${run.id}`} onClick={() => setExpanded(!expanded)}>{expanded ? '收起记录' : '展开记录'}</button></div></div>
    <div className="lcsc-record-summary"><div className="lcsc-record-request"><p>搜索：{run.query}</p><p className="lcsc-result-options">执行指令：{instructions}</p></div><div className="lcsc-record-meta"><div className="lcsc-record-id"><span>记录 ID</span><button type="button" className="lcsc-id-copy" title="点击复制执行记录 ID" aria-label={`复制执行记录 ID ${run.id}`} onClick={()=>void copyId()}><code>{run.id}</code></button><span role="status">{copyStatus}</span></div><p>{run.result.track ? '跟踪执行' : '后台执行'} · {run.models.map(m => m.model).join('、') || '尚未调用模型'} · {seconds(run.duration_ms)} · {money(run.cost.cny_estimate)}</p></div></div>
    <div id={`record-${run.id}`} hidden={!expanded}>
    <Metrics run={run} />
    {run.result.client_error ? <p className="form-error">{run.result.client_error}</p> : null}
    {data?.missing?.length ? <p className="lcsc-missing">未完成项：{data.missing.join('；')}</p> : null}
    {data?.parameters?.length ? <div className="lcsc-result-section"><h4>元器件参数</h4><dl className="lcsc-parameter-grid">{data.parameters.map((p, i) => <div key={i}><dt>{p.name}</dt><dd>{p.value}</dd></div>)}</dl></div> : null}
    {data?.prices?.length ? <div className="lcsc-result-section"><h4>售价（人民币）</h4><div className="table-scroll"><table><thead><tr><th>购买数量</th><th>单价</th><th>来源</th></tr></thead><tbody>{data.prices.map((p, i) => <tr key={i}><td>{p.quantity}</td><td>{p.price}</td><td>{p.source}</td></tr>)}</tbody></table></div></div> : null}
    {data?.pins ? <div className="lcsc-result-section"><h4>引脚数：{data.pins.count}</h4><p className="field-hint">{data.pins.source}</p>{data.pins.screenshot?.startsWith('data:image/png;base64,') ? <img className="lcsc-pin-screenshot" src={data.pins.screenshot} alt="查询时数据手册弹窗中的引脚图截图" /> : null}<details><summary>查看完整引脚编号与名称</summary><dl className="lcsc-parameter-grid">{(data.pins.items || []).map((p, i) => <div key={i}><dt>{p.number}</dt><dd>{p.name}</dd></div>)}</dl></details></div> : null}
    {data?.datasheet ? <div className="lcsc-result-section"><h4>规格书</h4><div className="lcsc-file-row"><FileIcon name={data.datasheet.filename} /><div><p>{data.datasheet.name}</p><p className="field-hint">已保存：下载 / FDE规格书 / {data.datasheet.filename}</p></div><button className="secondary-button" onClick={() => void window.fde.app.showLcscDownload?.(data.datasheet!.filename)}>在 Finder 中显示</button></div></div> : null}
    {data?.other ? <div className="lcsc-result-section"><h4>其他查询结果 · {data.other.complete === true ? '目的已达到' : data.other.items ? '尚未全部达到目的' : '旧版记录，未经目标核验'}</h4><p className="field-hint">查询目的：{data.other.purpose}</p>{data.other.reason ? <p className={data.other.complete ? 'supporting-copy' : 'lcsc-missing'}>{data.other.reason}</p> : null}{data.other.items?.map((item,i)=><section className="lcsc-goal-result" key={i}><div><h5>{item.goal}</h5><span className={`lcsc-goal-status ${item.status === 'verified' ? 'verified' : ''}`}>{item.status === 'verified' ? '已核实' : '未核实'}</span></div><p>{item.answer}</p>{item.reason ? <p className="field-hint">原因：{item.reason}</p> : null}{item.evidence ? <details><summary>查看页面依据</summary><blockquote>{item.evidence.text}</blockquote><p className="field-hint">来源：{item.evidence.url}</p></details> : null}</section>)}{data.other.text ? <details><summary>查看旧版采集原文（不代表目的已达到）</summary><pre className="lcsc-legacy-result">{data.other.text}</pre></details> : null}</div> : null}
    {!data && product ? <pre className="lcsc-legacy-result">{product.visible_text}</pre> : null}
    {inlineLog ? <section className="lcsc-result-section"><h4>操作日志</h4><table className="lcsc-inline-log-table"><colgroup><col style={{width:'40%'}} /><col style={{width:'19%'}} /><col style={{width:'17%'}} /><col style={{width:'10%'}} /><col style={{width:'14%'}} /></colgroup><thead><tr><th>步骤 / 操作</th><th>开始 / 耗时</th><th>使用模型</th><th>Token</th><th>人民币估算</th></tr></thead><tbody>{run.steps.map((s, i) => <tr key={i}><td>{i + 1}. {s.detail}{s.status === 'failed' ? <span className="form-error"> · 失败</span> : null}</td><td>{seconds(s.at_ms)} / {seconds(s.duration_ms)}</td><td>{s.model || '浏览器 / 代码'}</td><td title={s.usage ? `输入 ${s.usage.input_tokens ?? '未知'} / 输出 ${s.usage.output_tokens ?? '未知'}` : ''}>{tokens(s.usage)?.toLocaleString() ?? '未知'}</td><td>{money(s.cost?.cny_estimate)}</td></tr>)}</tbody></table><details><summary>候选商品与选择依据</summary><p>{run.result.selection?.reason || '无额外说明'}</p>{run.candidates.map((c,i)=><article className="lcsc-candidate-evidence" key={i}><strong>{c.title}</strong><pre>{c.visible_text}</pre></article>)}</details></section> : null}
    <div className="lcsc-result-actions">{!inlineLog ? <button className="secondary-button" onClick={onLog}>查看操作日志</button> : null}{product ? <button className="secondary-button" onClick={() => void window.fde.app.openLcscBrowser?.(product.url)}>打开商品页</button> : null}</div>
    </div></article>
}

export function FileIcon({ name }: { name: string }) {
  const ext = name.split('.').pop()?.toUpperCase() || ''
  const type = ['PDF', 'TXT', 'DOC', 'DOCX', 'XLS', 'XLSX', 'CSV', 'PNG', 'JPG', 'JPEG', 'ZIP'].includes(ext) ? ext : '其他'
  return <span className={`lcsc-file-icon file-${type.toLowerCase()}`} role="img" aria-label={`${type} 文件`}><svg viewBox="0 0 40 48" aria-hidden="true"><path d="M5 1h21l9 9v36H5z" fill="currentColor" opacity=".12" /><path d="M26 1v10h9M5 1h21l9 9v36H5z" fill="none" stroke="currentColor" strokeWidth="2" /></svg><b>{type}</b></span>
}
