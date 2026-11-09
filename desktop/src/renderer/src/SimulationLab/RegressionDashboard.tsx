// V3.2 G7 · 回归与盲测面板（页面）。
//
// 呈现五项检查（不只总分）：总分 Δ、逐维度 Δ（含**退步维度**）、硬性失败差异、
// 成本 Δ、**泛化差与过拟合告警**。过拟合 ⇒ 明确警示「不得进入发布审批」。

import { useCallback, useEffect, useRef, useState, type ReactElement } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { AsyncButton, EmptyState, Loading, UiButton } from "../components/ui"
import {
  createRegressionSuite,
  listRegressionResults,
  listRegressionSuites,
  runRegression,
} from "./api"
import type { RegressionResultDto, RegressionSuiteDto } from "./types"

const VERDICT_LABEL: Record<RegressionResultDto["verdict"], string> = {
  improved: "有改进",
  regressed: "有退化",
  mixed: "有得有失",
  no_change: "无变化",
  inconclusive: "结论不可靠",
}

function errorText(caught: unknown): string {
  if (caught instanceof ApiClientError) return caught.message
  if (caught instanceof Error) return caught.message
  return "操作失败，请稍后重试。"
}

export function RegressionDashboard(): ReactElement {
  const { apiRequest } = useAuth()
  const [suites, setSuites] = useState<RegressionSuiteDto[]>([])
  const [results, setResults] = useState<RegressionResultDto[]>([])
  const [selectedSuite, setSelectedSuite] = useState("")
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const sequence = useRef(0)

  const load = useCallback(async () => {
    const requestSequence = ++sequence.current
    try {
      const [suitePayload, resultPayload] = await Promise.all([
        listRegressionSuites(apiRequest),
        listRegressionResults(apiRequest),
      ])
      if (requestSequence !== sequence.current) return
      setSuites(suitePayload.items)
      setResults(resultPayload.items)
      setError("")
      if (!selectedSuite && suitePayload.items.length > 0) {
        setSelectedSuite(suitePayload.items[0].id)
      }
    } catch (caught) {
      if (requestSequence !== sequence.current) return
      setError(errorText(caught))
    } finally {
      if (requestSequence === sequence.current) setLoading(false)
    }
  }, [apiRequest, selectedSuite])

  useEffect(() => {
    void load()
  }, [load])

  async function handleCreateSuite(): Promise<void> {
    setBusy(true)
    try {
      await createRegressionSuite(apiRequest, { name: `回归套件 ${suites.length + 1}`, split: "train" })
      setNotice("已创建回归套件。")
      await load()
    } catch (caught) {
      setNotice(errorText(caught))
    } finally {
      setBusy(false)
    }
  }

  async function handleRun(suiteId: string): Promise<void> {
    setBusy(true)
    try {
      const result = await runRegression(apiRequest, suiteId)
      setNotice(
        result.overfit_risk
          ? "回归完成——检出过拟合风险，不得进入发布审批。"
          : `回归完成：${VERDICT_LABEL[result.verdict]}。`,
      )
      await load()
    } catch (caught) {
      setNotice(errorText(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="simulation-regression" aria-label="回归与盲测">
      <header className="simulation-section-header">
        <h3>回归与盲测</h3>
        <AsyncButton
          variant="primary"
          actionKey="regression-suite-create"
          onRun={async () => {
            await handleCreateSuite()
          }}
        >
          新建回归套件
        </AsyncButton>
      </header>
      <p className="simulation-hint">
        数据集三分：训练集（可提改进）／回归集（检退化）／盲测集（最终检验）。
        改进只许用训练集的失败——用盲测集调参会让回归失去意义。
      </p>

      {notice ? (
        <p className="simulation-notice" role="status">
          {notice}
        </p>
      ) : null}
      {error ? (
        <p className="simulation-error" role="alert">
          {error}
        </p>
      ) : null}

      {loading ? <Loading label="正在加载回归数据…" /> : null}
      {!loading && suites.length === 0 ? (
        <EmptyState title="尚无回归套件" description="先新建一个套件，再跑基线对比。" />
      ) : null}

      <ul className="simulation-suite-list">
        {suites.map((suite) => (
          <li key={suite.id} className={`simulation-suite${suite.id === selectedSuite ? " active" : ""}`}>
            <button type="button" onClick={() => setSelectedSuite(suite.id)}>
              <strong>{suite.name}</strong>
              <span>{suite.split}</span>
              <span>场景 {suite.scenario_ids.length}</span>
            </button>
            <AsyncButton
              actionKey={`regression-run-${suite.id}`}
              onRun={async () => {
                await handleRun(suite.id)
              }}
            >
              跑对比
            </AsyncButton>
          </li>
        ))}
      </ul>

      {results.length === 0 ? (
        <p className="simulation-empty">尚无回归结果。</p>
      ) : (
        <ul className="simulation-regression-list">
          {results.map((result) => (
            <li key={result.id} className="simulation-regression-result">
              <header>
                <span className={`simulation-verdict simulation-verdict-${result.verdict}`}>
                  {VERDICT_LABEL[result.verdict]}
                </span>
                <span>
                  基线 {result.before.mean_total?.toFixed(2)} → 候选{" "}
                  {result.after.mean_total?.toFixed(2)}
                </span>
                <span>总分 Δ {result.deltas.total_delta?.toFixed(2) ?? "—"}</span>
              </header>
              {result.overfit_risk ? (
                <p className="simulation-warning" role="alert">
                  过拟合风险：泛化差 {result.generalization_gap}（训练集增益显著高于盲测集）
                  ⇒ 该提案不得进入发布审批。
                </p>
              ) : null}
              {result.deltas.regressed_dimensions &&
              result.deltas.regressed_dimensions.length > 0 ? (
                <p className="simulation-warning">
                  退步维度：{result.deltas.regressed_dimensions.join("、")}
                </p>
              ) : null}
              {result.new_hard_failures.length > 0 ? (
                <p className="simulation-error">
                  新增硬性失败：{result.new_hard_failures.join("、")}
                </p>
              ) : null}
              {result.resolved_hard_failures.length > 0 ? (
                <p className="simulation-hint">
                  消除硬性失败：{result.resolved_hard_failures.join("、")}
                </p>
              ) : null}
              <p className="simulation-hint">
                成本 Δ {JSON.stringify(result.deltas.cost_delta ?? {})}｜训练增益{" "}
                {result.deltas.train_gain ?? "—"}｜盲测增益 {result.deltas.blind_gain ?? "—"}
              </p>
            </li>
          ))}
        </ul>
      )}

      <UiButton onClick={() => void load()}>刷新</UiButton>
    </section>
  )
}
