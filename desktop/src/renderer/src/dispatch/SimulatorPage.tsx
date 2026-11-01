import { useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"

/** 仿真对比入口（B5 运维页簇；留注⑳）。
 *  只暴露只读回放（当前池 × 当前规则版本的再撮合画像，与 match_package 同
 *  管线不落 offer）。全链路种子化仿真留在 CLI（simulator.py 自建引擎连
 *  沙箱库，库名须 _sim/_test 结尾）——绝不可经 HTTP 触发写库；
 *  口径=仿真，不得当真实成绩引用（r9 诚实声明纪律）。 */

export interface ReplayTopEntry {
  level: string | null
  weighted: number | null
}

export interface ReplayPackageRow {
  package_code: string
  round: number
  scenario?: string
  stage_a_pass?: boolean
  candidates?: number
  rejected?: number
  top?: ReplayTopEntry[]
  skipped?: string
}

export interface ReplayReport {
  mode: string
  rule_version: number | null
  packages: ReplayPackageRow[]
  summary: {
    replayed: number
    scenario_counts: Record<string, number>
    stage_a_pass_rate: number | null
    avg_candidates_when_passable: number | null
    avg_top1_weighted_remote: number | null
  }
}

export function isReplayReport(value: unknown): value is ReplayReport {
  if (typeof value !== "object" || value === null) return false
  const row = value as Record<string, unknown>
  return (
    row.mode === "replay" &&
    typeof row.summary === "object" &&
    row.summary !== null &&
    Array.isArray(row.packages)
  )
}

export const SCENARIO_SHORT_LABELS: Record<string, string> = {
  A: "A 到场",
  B: "B 远程",
  C: "C 兜底",
}

export function SimulatorPage() {
  const { apiRequest } = useAuth()
  const [report, setReport] = useState<ReplayReport | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState("")

  const runReplay = () => {
    setRunning(true)
    setError("")
    void apiRequest<unknown>("/api/v1/dispatch/simulator/replay", { method: "POST" })
      .then((payload) => {
        // goal-d9 fix: apiRequest already unwraps the {data,error} envelope (latent bug family)
        if (isReplayReport(payload)) setReport(payload)
        else throw new Error("invalid replay report")
      })
      .catch((caught: unknown) => {
        setError(
          caught instanceof ApiClientError ? caught.message : "回放执行失败，请稍后重试。"
        )
      })
      .finally(() => setRunning(false))
  }

  return (
    <section className="page" aria-label="仿真对比">
      <header className="page-header">
        <div>
          <h1>仿真对比</h1>
          <p className="page-subtitle">
            历史包只读回放（当前池 × 当前规则版本再撮合画像）；全链路仿真走 CLI
            沙箱库，口径=仿真，不作真实成绩。
          </p>
        </div>
        <button
          className="primary-button"
          type="button"
          disabled={running}
          onClick={runReplay}
        >
          {running ? "回放中…" : report ? "重新回放" : "执行回放"}
        </button>
      </header>
      {error ? (
        <p className="error-text" role="alert">
          {error}
        </p>
      ) : null}
      {!report && !running && !error ? (
        <p className="muted">尚未执行回放。</p>
      ) : null}
      {report ? (
        <>
          <dl className="dispatch-package-detail" aria-label="回放摘要">
            <dt>回放包数</dt>
            <dd>{report.summary.replayed}</dd>
            <dt>场景分布</dt>
            <dd>
              {(Object.entries(report.summary.scenario_counts) as [string, number][])
                .map(([key, count]) => `${SCENARIO_SHORT_LABELS[key] || key}×${count}`)
                .join(" / ") || "—"}
            </dd>
            <dt>规则版本</dt>
            <dd>{report.rule_version ? `v${report.rule_version}` : "无公示版本（降级）"}</dd>
            <dt>Stage A 通过率</dt>
            <dd>{report.summary.stage_a_pass_rate ?? "—"}</dd>
            <dt>平均候选数（可通过）</dt>
            <dd>{report.summary.avg_candidates_when_passable ?? "—"}</dd>
            <dt>Top1 加权均分（远程）</dt>
            <dd>{report.summary.avg_top1_weighted_remote ?? "—"}</dd>
          </dl>
          <ul className="dispatch-package-list">
            {report.packages.map((row) => (
              <li key={`${row.package_code}-${row.round}`} className="dispatch-package-card">
                <div className="dispatch-offer-summary">
                  <strong>{row.package_code}</strong>
                  <span className="muted">第 {row.round} 轮</span>
                  {row.skipped ? (
                    <span className="muted">跳过：{row.skipped}</span>
                  ) : (
                    <span className="muted">
                      场景 {SCENARIO_SHORT_LABELS[row.scenario || ""] || row.scenario} ·
                      候选 {row.candidates ?? 0} · 淘汰 {row.rejected ?? 0}
                    </span>
                  )}
                </div>
                {row.top && row.top.length > 0 ? (
                  <ol className="dispatch-console-trail">
                    {row.top.map((entry, index) => (
                      <li key={index} className="dispatch-console-trail-row">
                        <strong>Top{index + 1}</strong>
                        <span className="muted">
                          {entry.level || "未定级"} · 加权 {entry.weighted ?? "—"}
                        </span>
                      </li>
                    ))}
                  </ol>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  )
}
