import { useEffect, useState } from 'react'

import { useAuth } from '../auth/AuthProvider'

// 试点报告页（goal-d11，d6 挂账④收尾）：只读渲染 /api/v1/agents/pilot-report
// ——试点窗口/额度状态 + 六指标。只出数不判阈值（D15：O-8/UM-5 人工评）；
// None 指标灰态显示「数据未积累」，不编造数值（沿 MetricsReportPage 心智）。

interface PilotStatus {
  enabled: boolean
  active: boolean
  started_at?: string
  expires_at?: string
  window_days?: number
  runs_used?: number
  runs_limit?: number
  runs_remaining?: number
  days_remaining?: number
  exhausted?: boolean
}

interface PilotMetrics {
  intercept_rate: number | null
  first_pass_rate: number | null
  avg_meeting_cost_units: number | null
  degraded_rate: number | null
  circuit_breaker_rate: number | null
  median_run_cost_units: number | null
}

interface PilotReport {
  pilot: PilotStatus
  metrics: PilotMetrics
  stuck_inflight_runs?: number
}

const METRIC_LABELS: { key: keyof PilotMetrics; label: string; blurb: string; kind: 'pct' | 'units' }[] = [
  { key: 'intercept_rate', label: '强制门拦截率', blurb: '门拦截 ÷（拦截+过门产物）；持续为 0 或过高都触发复盘', kind: 'pct' },
  { key: 'first_pass_rate', label: '评审后一次通过率', blurb: '过门产物 run 中首次尝试占比', kind: 'pct' },
  { key: 'avg_meeting_cost_units', label: '单会成本（units）', blurb: '召集计费总额 ÷ 会议总数', kind: 'units' },
  { key: 'degraded_rate', label: '降级率', blurb: 'L1+ 占比；持续 >30% = 基座不成熟红线', kind: 'pct' },
  { key: 'circuit_breaker_rate', label: '超时/预算熔断率', blurb: '熔断 run 占比', kind: 'pct' },
  { key: 'median_run_cost_units', label: 'run 成本中位数（units）', blurb: '窗口内全部 run', kind: 'units' },
]

function isPilotReport(value: unknown): value is PilotReport {
  if (!value || typeof value !== 'object') return false
  const row = value as Record<string, unknown>
  return !!row.pilot && typeof row.pilot === 'object' && !!row.metrics && typeof row.metrics === 'object'
}

export function PilotReportPage() {
  const { apiRequest } = useAuth()
  const [report, setReport] = useState<PilotReport | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let active = true
    setLoading(true)
    void apiRequest<unknown>('/api/v1/agents/pilot-report', { method: 'GET' })
      .then((value) => { if (active && isPilotReport(value)) setReport(value) })
      .catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : '试点报告加载失败。') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [apiRequest])
  return (
    <section className="page" aria-label="试点报告">
      <header className="page-header">
        <div>
          <p className="eyebrow">试点报告</p>
          <h1>UM-1 试点观测（30 天 / 20 run）</h1>
          <p>只出数不判阈值（O-8/UM-5 由人工评审）；六指标为空表示窗口内数据未积累。</p>
        </div>
      </header>
      <div className="page-stack">
        {error ? <p role="alert" className="form-error">{error}</p> : null}
        {loading ? <p role="status">加载中…</p> : null}
        {report ? <PilotReportView report={report} /> : null}
      </div>
    </section>
  )
}

function PilotReportView({ report }: { report: PilotReport }) {
  const { pilot: status, metrics } = report
  return <>
    <div className="card" data-testid="pilot-status">
      <div className="card-heading"><div><h3>试点状态</h3></div>
        <span className={`badge ${status.active ? 'ok' : 'muted'}`}>{status.active ? '进行中' : status.enabled ? '未开启/已结束' : '未启用'}</span>
      </div>
      {status.started_at ? (
        <dl className="translator-detail">
          <div><dt>窗口</dt><dd>{status.started_at?.slice(0, 10)} → {status.expires_at?.slice(0, 10)}（{status.window_days} 天）</dd></div>
          <div><dt>run 额度</dt><dd>{status.runs_used} / {status.runs_limit}（余 {status.runs_remaining}）{status.exhausted ? ' · 已耗尽' : ''}</dd></div>
          <div><dt>剩余天数</dt><dd>{status.days_remaining}</dd></div>
          <div><dt>滞留中 run</dt><dd>{report.stuck_inflight_runs ?? 0}</dd></div>
        </dl>
      ) : (
        <p className="muted">试点窗口未配置（settings：agent_pilot_enabled / agent_pilot_started_at）。</p>
      )}
    </div>
    <div className="card" data-testid="pilot-metrics">
      <div className="card-heading"><div><h3>六指标</h3></div></div>
      {METRIC_LABELS.map((metric) => {
        const value = metrics[metric.key]
        const empty = value === null || value === undefined
        return (
          <div key={metric.key} className={`pilot-metric${empty ? ' metric-insufficient' : ''}`} data-metric={metric.key}>
            <strong>{metric.label}</strong>
            <span className={`badge ${empty ? 'muted' : 'ok'}`}>
              {empty ? '数据未积累' : metric.kind === 'pct' ? `${((value as number) * 100).toFixed(1)}%` : String(value)}
            </span>
            <p className="muted">{metric.blurb}</p>
          </div>
        )
      })}
    </div>
  </>
}
