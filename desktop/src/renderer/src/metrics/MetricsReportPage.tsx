import { useEffect, useState } from 'react'

import { useAuth } from '../auth/AuthProvider'

// P0/P1 指标报表页（goal-d8，PRD §10 分期业务指标）：只读渲染
// /api/v1/metrics/report 聚合结果；样本不足的指标灰态显示「数据未积累」
// （服务端显式 insufficient_data，不编造数值）。

interface MetricCard {
  key: string
  label: string
  value: number | null
  sample_size: number
  definition: string
  target: number | null
  status: 'ok' | 'insufficient_data'
  detail?: { over_quota_rows?: number }
}

interface MetricsReport {
  generated_at: string
  sections: {
    p0: MetricCard[]
    p1_pilot: MetricCard[]
    ongoing: MetricCard[]
  }
}

const SECTION_TITLES: { key: keyof MetricsReport['sections']; title: string; blurb: string }[] = [
  { key: 'p0', title: 'P0 售前规模化 MVP 指标', blurb: '录入确认率 / 草稿耗时 / SOW 一次拍板 / 资深介入时长' },
  { key: 'p1_pilot', title: 'P1 试点观测（30 天 / 20 run）', blurb: 'lite 档占比 / 一次通过率 / 降级率' },
  { key: 'ongoing', title: '持续观测', blurb: '单 run 成本 / 拦截率 / 当月工作台动作（O-3）' },
]

function isMetricsReport(value: unknown): value is MetricsReport {
  if (!value || typeof value !== 'object') return false
  const item = value as Record<string, unknown>
  return typeof item.generated_at === 'string' && !!item.sections && typeof item.sections === 'object'
}

function formatValue(card: MetricCard): string {
  if (card.status === 'insufficient_data' || card.value === null) return '数据未积累'
  if (card.key.endsWith('_rate') || card.key.endsWith('_share')) {
    return `${(card.value * 100).toFixed(1)}%`
  }
  return String(card.value)
}

function MetricCardView({ card }: { card: MetricCard }) {
  const insufficient = card.status === 'insufficient_data'
  return (
    <div className={`card metric-card${insufficient ? ' metric-insufficient' : ''}`} data-metric={card.key}>
      <div className="card-heading">
        <div>
          <strong>{card.label}</strong>
          <p className="muted">{card.definition}</p>
        </div>
        <span className={`badge ${insufficient ? 'muted' : 'ok'} metric-value`}>
          {formatValue(card)}
          {card.target != null && card.status === 'ok' ? ` · 目标 ${card.target >= 1 ? `${card.target * 100}%` : `≥${card.target * 100}%`}` : ''}
        </span>
      </div>
      <p className="muted">
        样本 {card.sample_size}
        {card.detail && typeof card.detail.over_quota_rows === 'number'
          ? ` · 超额标注 ${card.detail.over_quota_rows} 行`
          : ''}
      </p>
    </div>
  )
}

export function MetricsReportPage() {
  const { apiRequest } = useAuth()
  const [report, setReport] = useState<MetricsReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    void apiRequest<unknown>('/api/v1/metrics/report', { method: 'GET' })
      .then((value) => {
        if (active) {
          if (isMetricsReport(value)) setReport(value)
          else setError('指标报表载荷异常。')
        }
      })
      .catch(() => {
        if (active) setError('无法加载指标报表（服务端未连接或无权限）。')
      })
    return () => { active = false }
  }, [apiRequest])

  if (error) {
    return (
      <section className="page" aria-label="指标报表">
        <header className="page-heading"><div><p className="eyebrow">指标报表</p><h1>P0 / P1 指标</h1></div></header>
        <p role="alert">{error}</p>
      </section>
    )
  }
  if (!report) {
    return (
      <section className="page" aria-label="指标报表">
        <header className="page-heading"><div><p className="eyebrow">指标报表</p><h1>P0 / P1 指标</h1></div></header>
        <p role="status">正在加载指标报表…</p>
      </section>
    )
  }
  return (
    <section className="page" aria-label="指标报表">
      <header className="page-header">
        <div>
          <p className="eyebrow">指标报表</p>
          <h1>P0 / P1 指标</h1>
          <p className="muted">生成于 {new Date(report.generated_at).toLocaleString()} · 只读聚合（PRD §10 分期业务指标）</p>
        </div>
      </header>
      <div className="page-stack">
        {SECTION_TITLES.map((section) => (
          <div key={section.key} className="card metrics-section" data-section={section.key}>
            <div className="card-heading">
              <div>
                <h3>{section.title}</h3>
                <p className="muted">{section.blurb}</p>
              </div>
            </div>
            <div className="page-stack">
              {report.sections[section.key].map((card) => (
                <MetricCardView key={card.key} card={card} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
