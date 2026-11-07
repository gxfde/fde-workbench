// V3.2 G7 · 运行台与运行详情。
//
// 左：运行列表（可按数据集/状态过滤，可新建运行）；右：选中运行的详情，
// 分「Trace / 评估 / 失败」三段。

import { useCallback, useEffect, useRef, useState, type ReactElement } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { AsyncButton, EmptyState, Loading, UiButton } from "../components/ui"
import {
  cancelSimulationRun,
  createSimulationRun,
  evaluateRun,
  getEvaluationReport,
  listFindings,
  listRunTraces,
  listScenarios,
  listSimulationRuns,
  analyzeRun,
} from "./api"
import { EvaluationReport } from "./EvaluationReport"
import { FailureAnalysis } from "./FailureAnalysis"
import {
  RUN_STATUS_LABEL,
  SPLIT_LABEL,
  type EvaluationReportDto,
  type FindingDto,
  type ScenarioDto,
  type SimulationRunDto,
  type TraceItemDto,
} from "./types"

const PHASES = [
  "",
  "setup",
  "interview",
  "analysis",
  "design",
  "implementation",
  "validation",
  "wrapup",
]

function errorText(caught: unknown): string {
  if (caught instanceof ApiClientError) return caught.message
  if (caught instanceof Error) return caught.message
  return "操作失败，请稍后重试。"
}

export function SimulationRunDetail(): ReactElement {
  const { apiRequest } = useAuth()
  const [runs, setRuns] = useState<SimulationRunDto[]>([])
  const [scenarios, setScenarios] = useState<ScenarioDto[]>([])
  const [selectedId, setSelectedId] = useState("")
  const [splitFilter, setSplitFilter] = useState("")
  const [statusFilter, setStatusFilter] = useState("")
  const [traces, setTraces] = useState<TraceItemDto[]>([])
  const [phase, setPhase] = useState("")
  const [report, setReport] = useState<EvaluationReportDto | null>(null)
  const [findings, setFindings] = useState<FindingDto[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const sequence = useRef(0)

  const loadRuns = useCallback(async () => {
    const requestSequence = ++sequence.current
    try {
      const payload = await listSimulationRuns(apiRequest, {
        split: splitFilter || undefined,
        status: statusFilter || undefined,
      })
      if (requestSequence !== sequence.current) return
      setRuns(payload.items)
      setError("")
      if (!selectedId && payload.items.length > 0) setSelectedId(payload.items[0].id)
    } catch (caught) {
      if (requestSequence !== sequence.current) return
      setError(errorText(caught))
    } finally {
      if (requestSequence === sequence.current) setLoading(false)
    }
  }, [apiRequest, selectedId, splitFilter, statusFilter])

  const loadRunDetail = useCallback(
    async (runId: string) => {
      if (!runId) return
      try {
        const [tracePayload, findingPayload] = await Promise.all([
          listRunTraces(apiRequest, runId, { phase: phase || undefined }),
          listFindings(apiRequest, runId),
        ])
        setTraces(tracePayload.items)
        setFindings(findingPayload.items)
        try {
          const evaluation = await getEvaluationReport(apiRequest, runId)
          setReport(evaluation)
        } catch {
          setReport(null)
        }
      } catch (caught) {
        setError(errorText(caught))
      }
    },
    [apiRequest, phase],
  )

  useEffect(() => {
    void loadRuns()
  }, [loadRuns])

  useEffect(() => {
    void loadRunDetail(selectedId)
  }, [loadRunDetail, selectedId])

  useEffect(() => {
    void listScenarios(apiRequest)
      .then((payload) => setScenarios(payload.items))
      .catch(() => setScenarios([]))
  }, [apiRequest])

  async function handleCreate(): Promise<void> {
    const scenario = scenarios[0]
    if (!scenario) {
      setNotice("案例库为空——先在「案例库」创建或导入案例。")
      return
    }
    setBusy(true)
    try {
      await createSimulationRun(apiRequest, {
        scenario_id: scenario.id,
        adapter_mode: "mock",
        execute: true,
        config: { max_rounds: 6, probe_quality: 1.0 },
      })
      setNotice(`已基于「${scenario.name}」发起一次模拟运行。`)
      await loadRuns()
    } catch (caught) {
      setNotice(errorText(caught))
    } finally {
      setBusy(false)
    }
  }

  async function handleCancel(runId: string): Promise<void> {
    setBusy(true)
    try {
      await cancelSimulationRun(apiRequest, runId)
      setNotice("已取消该运行。")
      await loadRuns()
    } catch (caught) {
      setNotice(errorText(caught))
    } finally {
      setBusy(false)
    }
  }

  async function handleEvaluate(): Promise<void> {
    if (!selectedId) return
    setBusy(true)
    try {
      const evaluation = await evaluateRun(apiRequest, selectedId)
      setReport(evaluation)
      setNotice(
        evaluation.human_review_required ? "评估完成——需人工复核。" : "评估完成。",
      )
    } catch (caught) {
      setNotice(errorText(caught))
    } finally {
      setBusy(false)
    }
  }

  async function handleAnalyze(): Promise<void> {
    if (!selectedId) return
    setBusy(true)
    try {
      const analysis = await analyzeRun(apiRequest, selectedId)
      setFindings(analysis.items)
      setNotice(`失败分析完成：新增 ${analysis.created} 条发现。`)
    } catch (caught) {
      setNotice(errorText(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="simulation-runs" aria-label="模拟运行台">
      <div className="simulation-run-list-panel">
        <header className="simulation-section-header">
          <h3>运行台</h3>
          <AsyncButton
            variant="primary"
            actionKey="simulation-run-create"
            onRun={async () => {
              await handleCreate()
            }}
          >
            发起模拟运行
          </AsyncButton>
        </header>
        <div className="simulation-filters" role="group" aria-label="运行筛选">
          <label>
            <span>数据集</span>
            <select
              value={splitFilter}
              onChange={(event) => setSplitFilter(event.target.value)}
            >
              <option value="">全部数据集</option>
              <option value="train">训练集</option>
              <option value="regression">回归集</option>
              <option value="blind">盲测集</option>
            </select>
          </label>
          <label>
            <span>状态</span>
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
            >
              <option value="">全部状态</option>
              {Object.entries(RUN_STATUS_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
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
        {loading ? <Loading label="正在加载运行…" /> : null}
        {!loading && runs.length === 0 ? (
          <EmptyState title="尚无运行" description="点击「发起模拟运行」跑一次。" />
        ) : null}
        <ul className="simulation-run-list">
          {runs.map((run) => (
            <li
              key={run.id}
              className={`simulation-run-item${run.id === selectedId ? " active" : ""}`}
            >
              <button type="button" onClick={() => setSelectedId(run.id)}>
                <span className={`simulation-status simulation-status-${run.status}`}>
                  {RUN_STATUS_LABEL[run.status]}
                </span>
                <span className="simulation-run-split">{SPLIT_LABEL[run.split]}</span>
                <span className="simulation-run-key">{run.run_key}</span>
              </button>
              <UiButton compact onClick={() => void handleCancel(run.id)}>
                取消
              </UiButton>
            </li>
          ))}
        </ul>
      </div>

      <div className="simulation-run-detail-panel">
        {selectedId ? (
          <>
            <section className="simulation-trace" aria-label="模拟过程 Trace">
              <header className="simulation-section-header">
                <h3>Trace（{traces.length}）</h3>
                <div className="simulation-filters">
                  <label>
                    <span>相位</span>
                    <select value={phase} onChange={(event) => setPhase(event.target.value)}>
                      {PHASES.map((value) => (
                        <option key={value || "all"} value={value}>
                          {value || "全部相位"}
                        </option>
                      ))}
                    </select>
                  </label>
                  <AsyncButton
                    actionKey="simulation-evaluate"
                    onRun={async () => {
                      await handleEvaluate()
                    }}
                  >
                    评估该运行
                  </AsyncButton>
                </div>
              </header>
              {traces.length === 0 ? (
                <p className="simulation-empty">该运行暂无 Trace。</p>
              ) : (
                <ol className="simulation-trace-list">
                  {traces.map((trace) => (
                    <li key={trace.seq}>
                      <span className="simulation-trace-seq">#{trace.seq}</span>
                      <span className="simulation-trace-phase">{trace.phase}</span>
                      <span className="simulation-trace-event">{trace.event_type}</span>
                      <span className="simulation-trace-payload">
                        {Object.entries(trace.payload)
                          .filter(([key]) => key !== "artifact")
                          .map(([key, value]) => `${key}=${String(value).slice(0, 60)}`)
                          .join("；")}
                      </span>
                    </li>
                  ))}
                </ol>
              )}
            </section>

            <EvaluationReport report={report ?? emptyReport()} />

            <FailureAnalysis
              findings={findings}
              busy={busy}
              onAnalyze={async () => {
                await handleAnalyze()
              }}
            />
          </>
        ) : (
          <EmptyState title="未选中运行" description="从左侧选择一个运行查看过程与评估。" />
        )}
      </div>
    </section>
  )
}

function emptyReport(): EvaluationReportDto {
  return {
    run_id: "",
    layers: [],
    deterministic: null,
    model: null,
    human: [],
    final: null,
    disagreement: 0,
    human_review_required: false,
    meta: { rubric_version: "", adapter_mode: "", disclaimer: "尚未评估。" },
  }
}
