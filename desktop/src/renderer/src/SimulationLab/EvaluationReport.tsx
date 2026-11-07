// V3.2 G7 · 评估报告（组件）。
//
// 三层**并列呈现不合并**：规则层 / 模型层 / 人工层各自一行，硬性失败单独成块。
// 每个得分可下钻到证据引用；模型层显式标注模式（stub ≠ 真模型）。

import { Fragment, type ReactElement } from "react"

import {
  LAYER_LABEL,
  VERDICT_LABEL,
  type EvaluationLayerDto,
  type EvaluationReportDto,
} from "./types"

function ScoreBar({ value }: { value: number }): ReactElement {
  const percent = Math.max(0, Math.min(100, Math.round(value * 100)))
  return (
    <span className="simulation-score" aria-label={`得分 ${percent}%`}>
      <span className="simulation-score-track" aria-hidden="true">
        <span className="simulation-score-fill" style={{ width: `${percent}%` }} />
      </span>
      <span className="simulation-score-value">{percent}%</span>
    </span>
  )
}

function LayerCard({ layer }: { layer: EvaluationLayerDto }): ReactElement {
  const dimensions = layer.scores?.dimensions ?? []
  const criteria = layer.scores?.criteria ?? []
  return (
    <article className="simulation-layer-card">
      <header>
        <h4>
          {LAYER_LABEL[layer.layer]}（{layer.evaluator_id}）
        </h4>
        <span className={`simulation-verdict simulation-verdict-${layer.verdict}`}>
          {VERDICT_LABEL[layer.verdict]}
        </span>
        <ScoreBar value={layer.total_score} />
      </header>
      <p className="simulation-layer-meta">
        规则版本 {layer.rubric_version}｜模式 {layer.mode}
        {layer.unverified_ratio > 0
          ? `｜无证据分项占比 ${Math.round(layer.unverified_ratio * 100)}%`
          : ""}
      </p>
      {layer.note ? <p className="simulation-hint">{layer.note}</p> : null}
      {dimensions.length > 0 ? (
        <ul className="simulation-dimension-list">
          {dimensions.map((dimension) => (
            <li key={dimension.key}>
              <span>
                {dimension.key} {dimension.name}
              </span>
              <ScoreBar value={layer.scores?.dimension_scores?.[dimension.key] ?? 0} />
            </li>
          ))}
        </ul>
      ) : null}
      {criteria.length > 0 ? (
        <details className="simulation-criteria">
          <summary>评分判据（{criteria.length}）</summary>
          <ul>
            {criteria.map((criterion) => (
              <li key={criterion.key}>
                <code>{criterion.key}</code> {criterion.title}
                <span className="simulation-criterion-score">{criterion.score.toFixed(2)}</span>
                <span className="simulation-criterion-evidence">
                  {criterion.verified
                    ? `证据 ${criterion.evidence_refs?.length ?? 0} 条`
                    : "无证据（未入账）"}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </article>
  )
}

export function EvaluationReport({
  report,
  onRecordHuman,
}: {
  report: EvaluationReportDto
  onRecordHuman?(payload: { verdict: string; total_score: number; note: string }): Promise<void>
}): ReactElement {
  const layers = report.layers ?? []
  return (
    <section className="simulation-evaluation" aria-label="评估报告">
      <header className="simulation-section-header">
        <h3>评估报告</h3>
        <span className="simulation-hint">
          {report.meta?.disclaimer}（rubric {report.meta?.rubric_version}｜执行面{" "}
          {report.meta?.adapter_mode}）
        </span>
      </header>

      {report.human_review_required ? (
        <p className="simulation-warning" role="status">
          需人工复核：两层分歧 {report.disagreement.toFixed(2)}
          {onRecordHuman ? "；请在人工层给出终裁结论。" : ""}
        </p>
      ) : null}

      {layers.length === 0 ? (
        <p className="simulation-empty">尚未评估——对该运行执行「评估」后在此呈现。</p>
      ) : (
        <div className="simulation-layer-stack">
          {layers.map((layer) => (
            <Fragment key={layer.id}>
              <LayerCard layer={layer} />
            </Fragment>
          ))}
        </div>
      )}

      {report.deterministic && report.deterministic.hard_failures.length > 0 ? (
        <section className="simulation-hard-failures" aria-label="硬性失败">
          <h4>硬性失败（不可被其他维度高分抵消）</h4>
          <ul>
            {report.deterministic.hard_failures.map((failure) => (
              <li key={failure.code}>
                <code>{failure.code}</code> {failure.title}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {onRecordHuman ? (
        <HumanReviewForm onSubmit={onRecordHuman} />
      ) : null}
    </section>
  )
}

function HumanReviewForm({
  onSubmit,
}: {
  onSubmit(payload: { verdict: string; total_score: number; note: string }): Promise<void>
}): ReactElement {
  return (
    <form
      className="simulation-human-form"
      onSubmit={(event) => {
        event.preventDefault()
        const form = event.currentTarget
        const verdict = (form.elements.namedItem("verdict") as HTMLSelectElement).value
        const score = Number((form.elements.namedItem("score") as HTMLInputElement).value)
        const note = (form.elements.namedItem("note") as HTMLTextAreaElement).value
        void onSubmit({ verdict, total_score: score, note })
      }}
    >
      <h4>人工抽检结论（终裁）</h4>
      <label>
        <span>结论</span>
        <select name="verdict" defaultValue="conditional">
          <option value="pass">通过</option>
          <option value="conditional">有条件通过</option>
          <option value="fail">未通过</option>
          <option value="hard_fail">硬性失败</option>
          <option value="inconclusive">结论不可靠</option>
        </select>
      </label>
      <label>
        <span>总分（0–1）</span>
        <input name="score" type="number" step="0.01" min="0" max="1" defaultValue="0.5" />
      </label>
      <label>
        <span>理由（必填）</span>
        <textarea name="note" rows={2} />
      </label>
      <button type="submit">提交人工结论</button>
    </form>
  )
}
