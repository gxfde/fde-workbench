// V3.2 G7 · 失败分析（组件）。
//
// 发现清单按严重度排序；每条显示**根因置信度**（confirmed / likely / hypothesis）——
// 只有 confirmed 的根因能生成改进提案（界面据此提示）。

import { type ReactElement } from "react"

import type { FindingDto } from "./types"

const SEVERITY_LABEL: Record<FindingDto["severity"], string> = {
  high: "高",
  medium: "中",
  low: "低",
}

const CONFIDENCE_LABEL: Record<string, string> = {
  confirmed: "已确认",
  likely: "较可能",
  hypothesis: "待人工确认",
}

export function FailureAnalysis({
  findings,
  onAnalyze,
  busy,
}: {
  findings: FindingDto[]
  onAnalyze?(): Promise<void>
  busy?: boolean
}): ReactElement {
  const ordered = [...findings].sort((left, right) => {
    const rank = { high: 0, medium: 1, low: 2 }
    return rank[left.severity] - rank[right.severity]
  })
  return (
    <section className="simulation-findings" aria-label="失败分析">
      <header className="simulation-section-header">
        <h3>失败分析</h3>
        {onAnalyze ? (
          <button type="button" onClick={() => void onAnalyze()} disabled={busy}>
            {busy ? "分析中…" : "执行失败分析"}
          </button>
        ) : null}
      </header>

      {ordered.length === 0 ? (
        <p className="simulation-empty">
          尚无失败发现。先对该运行执行「评估」，再执行失败分析。
        </p>
      ) : (
        <ul className="simulation-finding-list">
          {ordered.map((finding) => {
            const confirmed = finding.root_causes.some(
              (cause) => cause.confidence === "confirmed",
            )
            return (
              <li key={finding.id} className={`simulation-finding simulation-severity-${finding.severity}`}>
                <header>
                  <code>{finding.code}</code>
                  <strong>{finding.title}</strong>
                  <span className="simulation-severity">{SEVERITY_LABEL[finding.severity]}</span>
                </header>
                <p>{finding.description}</p>
                <ul className="simulation-root-causes">
                  {finding.root_causes.map((cause) => (
                    <li key={cause.code}>
                      <span className={`simulation-confidence simulation-confidence-${cause.confidence}`}>
                        {CONFIDENCE_LABEL[cause.confidence] ?? cause.confidence}
                      </span>
                      {cause.code}
                      <span className="simulation-root-analysis">{cause.analysis}</span>
                    </li>
                  ))}
                </ul>
                <footer>
                  <span>证据 {finding.evidence_refs.length} 条</span>
                  {confirmed ? (
                    <span className="simulation-badge">可生成改进提案</span>
                  ) : (
                    <span className="simulation-hint">根因未确认——先人工复核，不得据此提改进</span>
                  )}
                </footer>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
