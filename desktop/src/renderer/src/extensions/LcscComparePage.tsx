import { useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { resultFields, type LcscRun } from './LcscToolCard'
import { RunCard } from './LcscToolPage'
import './extensions.css'

interface Comparison {
  baseline: LcscRun
  jev: LcscRun
  comparable: boolean
  analysis: { summary: string; comparability: string; quality: string; efficiency: string; decision?: string; limitations: string; recommendation: string }
  decision_phases?: { baseline: DecisionPhase[]; jev: DecisionPhase[] }
  analysis_model: string
}
interface DecisionPhase { phase: string; calls: number; duration_ms: number | null; input_tokens: number | null; output_tokens: number | null; cost_cny_estimate: string | null; models: string[] }

function summarizeDecisionPhases(run: LcscRun): DecisionPhase[] {
  const phaseOf = (detail: string, action: string) => {
    if (action === 'judge' || detail.includes('候选商品判断')) return '候选商品判断'
    if (detail.includes('逐项查找') || detail.includes('证据选择')) return '目标证据选择'
    if (detail.includes('组织直接回答')) return '按目的组织回答'
    if (detail.includes('核验每项目的及完整性')) return '目标核验与结束判断'
    if (detail.includes('只读安全边界')) return '只读安全判断'
    if (['重新规划', '浏览动作', '下一步', '页面证据未变', '复核是否确实'].some(text => detail.includes(text))) return '浏览动作规划'
    return '其他模型决策'
  }
  const groups = new Map<string, DecisionPhase>()
  for (const step of run.steps) {
    if (!step.model) continue
    const phase = phaseOf(step.detail, step.action)
    const group = groups.get(phase) || { phase, calls: 0, duration_ms: 0, input_tokens: 0, output_tokens: 0, cost_cny_estimate: '0', models: [] }
    group.calls += 1
    group.duration_ms = group.duration_ms == null || step.duration_ms == null ? null : group.duration_ms + step.duration_ms
    group.input_tokens = group.input_tokens == null || step.usage?.input_tokens == null ? null : group.input_tokens + step.usage.input_tokens
    group.output_tokens = group.output_tokens == null || step.usage?.output_tokens == null ? null : group.output_tokens + step.usage.output_tokens
    group.cost_cny_estimate = group.cost_cny_estimate == null || step.cost?.cny_estimate == null ? null : String(Number(group.cost_cny_estimate) + Number(step.cost.cny_estimate))
    if (!group.models.includes(step.model)) group.models.push(step.model)
    groups.set(phase, group)
  }
  return [...groups.values()]
}

export function LcscComparePage() {
  const { apiRequest } = useAuth()
  const [runs, setRuns] = useState<LcscRun[]>([])
  const [baselineId, setBaselineId] = useState('')
  const [jevId, setJevId] = useState('')
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    void apiRequest<{ items: LcscRun[] }>('/api/v1/ai/lcsc-runs', { method: 'GET' })
      .then(value => setRuns(value.items)).catch(e => setError(e.message))
  }, [])
  async function compare() {
    if (!baselineId || !jevId || busy) return
    setBusy(true); setError(''); setComparison(null); setSubmitted(true)
    try {
      setComparison(await apiRequest<Comparison>('/api/v1/ai/lcsc-runs/compare', {
        method: 'POST', body: { baseline_id: baselineId, jev_id: jevId },
      }))
    } catch (e) { setError(e instanceof Error ? e.message : '对比失败。') }
    finally { setBusy(false) }
  }
  const choices = (variant: LcscRun['skill_key']) => runs.filter(run => run.skill_key === variant)
  const label = (run: LcscRun) => `${new Date(run.started_at).toLocaleString()} · ${run.query} · ${run.status} · ${run.id.slice(0, 8)}`
  const shownBaseline = comparison?.baseline || (submitted ? runs.find(run => run.id === baselineId) : undefined)
  const shownJev = comparison?.jev || (submitted ? runs.find(run => run.id === jevId) : undefined)
  return <section className="page-stack lcsc-detail-page lcsc-compare-page">
    <header className="page-header"><div><h1>立创商城查询执行记录对比</h1><p className="supporting-copy">选择已有记录进行分析；不会重新打开商城或执行查询。</p></div><a className="secondary-button button-link compact" href="#extensions?tab=tools">返回工具 / 插件</a></header>
    <section className="panel"><div className="lcsc-compare-selects">
      <label className="field"><span>左侧 · 默认模型版执行记录</span><select value={baselineId} onChange={e => { setBaselineId(e.target.value); setComparison(null); setSubmitted(false) }}><option value="">选择一条记录</option>{choices('lcsc-browser-baseline').map(run => <option value={run.id} key={run.id}>{label(run)}</option>)}</select></label>
      <label className="field"><span>右侧 · Jev 版执行记录</span><select value={jevId} onChange={e => { setJevId(e.target.value); setComparison(null); setSubmitted(false) }}><option value="">选择一条记录</option>{choices('lcsc-browser-jev').map(run => <option value={run.id} key={run.id}>{label(run)}</option>)}</select></label>
    </div><button className="primary-button" disabled={!baselineId || !jevId || busy} onClick={() => void compare()}>{busy ? 'AI 正在分析…' : '对比'}</button>
    {error ? <p className="form-error" role="alert">{error}</p> : null}</section>
    {comparison ? <AnalysisReport value={comparison} /> : null}
    {shownBaseline && shownJev ? <div className="lcsc-compare-results"><section><h2>默认模型版</h2><RunCard key={shownBaseline.id} run={shownBaseline} latest={false} initiallyExpanded inlineLog onLog={() => {}} /></section><section><h2>Jev 版</h2><RunCard key={shownJev.id} run={shownJev} latest={false} initiallyExpanded inlineLog onLog={() => {}} /></section></div> : null}
  </section>
}

function AnalysisReport({ value }: { value: Comparison }) {
  const { baseline: a, jev: b, analysis } = value
  const formatFields = (run: LcscRun) => (run.result.fields || []).map(field => resultFields[field] || field).join('、') || '未记录'
  const formatStatus = (run: LcscRun) => ({succeeded:'已完成', partial:'部分完成', failed:'失败', running:'执行中'}[run.status] || run.status)
  const finishReason = (run: LcscRun) => run.result.details?.other?.reason || run.result.client_error || run.result.details?.missing?.join('；') || (run.status === 'succeeded' ? '已完成' : '未记录')
  const formatNumber = (value?: number | null) => value == null ? '未知' : value.toLocaleString()
  const formatSeconds = (value?: number | null) => value == null ? '未记录' : `${(value / 1000).toFixed(2)} 秒`
  const formatCost = (run: LcscRun) => run.cost.cny_estimate == null ? '待核算' : `¥${Number(run.cost.cny_estimate).toFixed(6)}`
  const checks = [
    ['搜索内容', a.query, b.query],
    ['查询目的', a.result.purpose || '未选择其他目的', b.result.purpose || '未选择其他目的'],
    ['查询字段', formatFields(a), formatFields(b)],
    ['选中商品', a.result.selected_product?.title || '未选中', b.result.selected_product?.title || '未选中'],
    ['完成状态', formatStatus(a), formatStatus(b)],
    ['终止原因', finishReason(a), finishReason(b)],
    ['模型', a.models.map(item => item.model).join('、') || '未记录', b.models.map(item => item.model).join('、') || '未记录'],
  ]
  const metrics = [
    ['总耗时', formatSeconds(a.duration_ms), formatSeconds(b.duration_ms)],
    ['模型判断耗时', formatSeconds(a.result.model_duration_ms), formatSeconds(b.result.model_duration_ms)],
    ['浏览器/代码步骤', String(a.steps.filter(step => !step.model).length), String(b.steps.filter(step => !step.model).length)],
    ['输入 Token', formatNumber(a.usage.input_tokens), formatNumber(b.usage.input_tokens)],
    ['输出 Token', formatNumber(a.usage.output_tokens), formatNumber(b.usage.output_tokens)],
    ['模型费用估算', formatCost(a), formatCost(b)],
  ]
  const decisionPhases = value.decision_phases || { baseline: summarizeDecisionPhases(a), jev: summarizeDecisionPhases(b) }
  const phaseNames = [...new Set([...decisionPhases.baseline, ...decisionPhases.jev].map(item => item.phase))]
  const phaseCell = (item?: DecisionPhase) => item ? <span className="lcsc-phase-cell"><span>{item.calls} 次 · {formatSeconds(item.duration_ms)}</span><span>Token：{formatNumber(item.input_tokens)} 输入 / {formatNumber(item.output_tokens)} 输出</span><span>费用：{item.cost_cny_estimate == null ? '待核算' : `¥${Number(item.cost_cny_estimate).toFixed(6)}`}</span><small>模型：{item.models.join('、') || '未记录'}</small></span> : <span className="field-hint">未调用</span>
  const goals = [...new Set([...(a.result.details?.other?.items || []), ...(b.result.details?.other?.items || [])].map(item => item.goal))]
  const goalText = (run: LcscRun, goal: string) => {
    const item = run.result.details?.other?.items?.find(entry => entry.goal === goal)
    return item ? `${item.status === 'verified' ? '已核实' : '未核实'} · ${item.answer || item.reason || '尚未确认'}` : '未记录'
  }
  const row = ([label, left, right]: string[], index: number) => <div className="lcsc-compare-row" key={`${label}-${index}`}><strong>{label}</strong><span>{left}</span><span>{right}</span></div>
  return <details className="panel lcsc-analysis" aria-label="AI 分析对比结果">
    <summary className="lcsc-analysis-toggle"><span><strong>AI 分析对比结果</strong><small className="lcsc-analysis-closed-label">分析已完成 · 点击展开查看完整报告</small><small className="lcsc-analysis-open-label">完整报告 · 点击收起</small></span><span className="lcsc-analysis-chevron" aria-hidden="true">⌄</span></summary>
    <div className="lcsc-analysis-body"><p className="field-hint">分析模型：{value.analysis_model} · 记录 A 为默认模型版，记录 B 为 Jev 版</p>
    <p className="lcsc-analysis-lead">{analysis.summary}</p>
    {!value.comparable ? <p className="lcsc-missing">搜索内容、查询目的或字段不一致，不能将耗时和费用直接作为版本优劣结论。</p> : null}
    <h3>一、可比性先检查</h3>
    <div className="lcsc-compare-table" role="table" aria-label="可比性检查"><div className="lcsc-compare-row lcsc-compare-table-head" role="row"><strong>维度</strong><strong>记录 A · {a.id.slice(0, 8)}</strong><strong>记录 B · {b.id.slice(0, 8)}</strong></div>{checks.map(row)}</div>
    <p className="lcsc-analysis-copy">{analysis.comparability}</p>
    <h3>二、指标对比</h3>
    <div className="lcsc-compare-table" role="table" aria-label="指标对比"><div className="lcsc-compare-row lcsc-compare-table-head" role="row"><strong>指标</strong><strong>记录 A</strong><strong>记录 B</strong></div>{metrics.map(row)}</div>
    <p className="lcsc-analysis-copy">{analysis.efficiency}</p>
    <h4>模型决策步骤消耗</h4>
    <p className="field-hint">按操作日志中的模型调用归类；浏览器和代码步骤不计入。费用未核实时显示“待核算”。</p>
    <div className="lcsc-compare-table" role="table" aria-label="模型决策步骤消耗"><div className="lcsc-compare-row lcsc-compare-table-head" role="row"><strong>决策阶段</strong><strong>记录 A · 默认模型版</strong><strong>记录 B · Jev 版</strong></div>{phaseNames.length ? phaseNames.map(name => <div className="lcsc-compare-row" role="row" key={name}><strong>{name}</strong>{phaseCell(decisionPhases.baseline.find(item => item.phase === name))}{phaseCell(decisionPhases.jev.find(item => item.phase === name))}</div>) : <p className="field-hint">两条记录均没有可计量的模型决策步骤。</p>}</div>
    {analysis.decision ? <p className="lcsc-analysis-copy">{analysis.decision}</p> : null}
    <h3>三、结果内容对照</h3>
    {goals.length ? <div className="lcsc-compare-table" role="table" aria-label="查询目的对照"><div className="lcsc-compare-row lcsc-compare-table-head" role="row"><strong>查询目的</strong><strong>记录 A</strong><strong>记录 B</strong></div>{goals.map((goal, index) => row([goal, goalText(a, goal), goalText(b, goal)], index))}</div> : <p className="field-hint">两条记录均没有“其他”目的的逐项核验结果；字段详情见下方记录。</p>}
    <p className="lcsc-analysis-copy">{analysis.quality}</p>
    <h3>四、需要注意的限制</h3><p className="lcsc-analysis-copy">{analysis.limitations}</p>
    <h3>五、复测建议</h3><p className="lcsc-analysis-copy">{analysis.recommendation}</p>
    <p className="field-hint">AI 只分析已有记录，不重新查询。原记录的费用为估算；本次分析模型消耗不计入原记录。</p>
    </div>
  </details>
}
