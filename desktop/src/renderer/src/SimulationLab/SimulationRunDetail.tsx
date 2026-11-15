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
  recordHumanEvaluation,
  analyzeRun,
  type HumanEvaluationPayload,
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

function integrationStatus(trace: { payload: Record<string, unknown> }): string {
  const artifact = trace.payload?.artifact
  if (!artifact || typeof artifact !== "object") return ""
  const value = (artifact as Record<string, unknown>).integration_status
  return typeof value === "string" ? value : ""
}

function hasExpandableArtifact(value: unknown): boolean {
  if (value === null || value === undefined) return false
  if (typeof value === "string") return value.trim().length > 0
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === "object") return Object.keys(value as Record<string, unknown>).length > 0
  return true
}

function formatStructuredValue(value: unknown): string {
  if (typeof value === "string") return value
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  if (value === null || value === undefined) return "—"
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

interface TextArtifactEntry {
  name: string
  kind: string
  sha256: string
  text: string
}

function extractTextArtifactEntries(artifact: Record<string, unknown>): TextArtifactEntry[] {
  const rawList = artifact.artifacts
  if (!Array.isArray(rawList)) return []
  const result: TextArtifactEntry[] = []
  for (let index = 0; index < rawList.length; index += 1) {
    const item = rawList[index]
    if (!item || typeof item !== "object" || Array.isArray(item)) continue
    const record = item as Record<string, unknown>
    if (
      typeof record.text === "string" ||
      typeof record.name === "string" ||
      typeof record.sha256 === "string"
    ) {
      result.push({
        name: typeof record.name === "string" && record.name ? record.name : `artifact-${index + 1}`,
        kind: typeof record.kind === "string" && record.kind ? record.kind : "artifact",
        sha256: typeof record.sha256 === "string" ? record.sha256 : "",
        text: typeof record.text === "string" ? record.text : "",
      })
    }
  }
  return result
}

function renderArtifactDetail(artifact: unknown): ReactElement {
  if (!artifact || typeof artifact !== "object" || Array.isArray(artifact)) {
    return (
      <div
        className="simulation-trace-artifact-panel"
        role="region"
        aria-label="阶段交付产物原文"
      >
        <pre className="simulation-artifact-json">{formatStructuredValue(artifact)}</pre>
      </div>
    )
  }
  const record = artifact as Record<string, unknown>
  const textEntries = extractTextArtifactEntries(record)
  const restEntries = Object.entries(record).filter(([key]) =>
    textEntries.length > 0 ? key !== "artifacts" : true,
  )

  return (
    <div
      className="simulation-trace-artifact-panel"
      role="region"
      aria-label="阶段交付产物原文"
    >
      {textEntries.length > 0 ? (
        <ul className="simulation-trace-artifact-files">
          {textEntries.map((entry, idx) => (
            <li key={`${entry.name}-${entry.sha256}-${idx}`} className="simulation-trace-artifact-file">
              <header className="simulation-trace-artifact-file-header">
                <strong>{entry.name}</strong>
                <span className="simulation-trace-artifact-kind">{entry.kind}</span>
                {entry.sha256 ? (
                  <code className="simulation-trace-artifact-sha" title={entry.sha256}>
                    sha256: {entry.sha256}
                  </code>
                ) : null}
              </header>
              <pre className="simulation-trace-artifact-text">{entry.text || "（无正文内容）"}</pre>
            </li>
          ))}
        </ul>
      ) : null}
      {restEntries.length > 0 ? (
        <dl className="simulation-trace-artifact-fields">
          {restEntries.map(([key, val]) => (
            <div key={key} className="simulation-trace-artifact-field">
              <dt>{key}</dt>
              <dd>
                <pre className="simulation-artifact-json">{formatStructuredValue(val)}</pre>
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  )
}

function errorText(caught: unknown): string {
  if (caught instanceof ApiClientError) return caught.message
  if (caught instanceof Error) return caught.message
  return "操作失败，请稍后重试。"
}

export function SimulationRunDetail(): ReactElement {
  const { apiRequest, user } = useAuth()
  // L-C 终裁与改进提案审批同尺：admin / project_lead（服务端 403 兜底，这里只管显隐）。
  const canAdjudicate = user?.role === "admin" || user?.role === "project_lead"
  const [runs, setRuns] = useState<SimulationRunDto[]>([])
  const [scenarios, setScenarios] = useState<ScenarioDto[]>([])
  const [selectedScenarioId, setSelectedScenarioId] = useState("")
  const [selectedId, setSelectedId] = useState("")
  const [splitFilter, setSplitFilter] = useState("")
  // 「执行面」下拉双重职责：过滤下方运行列表 + 作为新运行的默认执行面。
  // 空串 = 全部执行面（列表不按执行面收窄；发起新运行时回落 mock）。
  const [adapterMode, setAdapterMode] = useState<"" | "mock" | "workbench" | "real">("")
  const [statusFilter, setStatusFilter] = useState("")
  const [traces, setTraces] = useState<TraceItemDto[]>([])
  const [phase, setPhase] = useState("")
  const [report, setReport] = useState<EvaluationReportDto | null>(null)
  const [findings, setFindings] = useState<FindingDto[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [expandedTraceSeqs, setExpandedTraceSeqs] = useState<number[]>([])
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
    setExpandedTraceSeqs([])
    void loadRunDetail(selectedId)
  }, [loadRunDetail, selectedId])

  useEffect(() => {
    void listScenarios(apiRequest)
      .then((payload) => {
        setScenarios(payload.items)
        if (payload.items.length > 0) {
          setSelectedScenarioId((prev) => prev || payload.items[0].id)
        }
      })
      .catch(() => setScenarios([]))
  }, [apiRequest])

  const hasNonTerminalRun = runs.some(
    (run) => run.status === "queued" || run.status === "running",
  )

  useEffect(() => {
    if (!hasNonTerminalRun) return
    const timer = setInterval(() => {
      void loadRuns()
      if (selectedId) void loadRunDetail(selectedId)
    }, 3000)
    return () => clearInterval(timer)
  }, [hasNonTerminalRun, loadRunDetail, loadRuns, selectedId])

  async function handleCreate(): Promise<void> {
    const scenario =
      scenarios.find((item) => item.id === selectedScenarioId) ?? scenarios[0]
    if (!scenario) {
      setNotice("案例库为空——先在「案例库」创建或导入案例。")
      return
    }
    setBusy(true)
    try {
      const mode = adapterMode || "mock"
      const created = await createSimulationRun(apiRequest, {
        scenario_id: scenario.id,
        adapter_mode: mode,
        execute: true,
        config: { max_rounds: 6, probe_quality: 1.0 },
      })
      setSelectedId(created.id)
      setNotice(
        mode === "workbench" && created.status === "queued"
          ? `已基于「${scenario.name}」发起内嵌工作台模型运行（后台排队执行中，自动刷新状态）。`
          : `已基于「${scenario.name}」发起一次模拟运行。`,
      )
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

  async function handleRecordHuman(payload: HumanEvaluationPayload): Promise<void> {
    if (!selectedId) return
    setBusy(true)
    try {
      await recordHumanEvaluation(apiRequest, selectedId, payload)
    } catch (caught) {
      // POST 失败必须穿透给表单就地报错（只喂左栏 notice 会让用户误以为没提交）。
      setBusy(false)
      setNotice(errorText(caught))
      throw caught
    }
    try {
      // 终裁后重拉报告：human 层行并列出现，human_review_required 随之解除。
      const fresh = await getEvaluationReport(apiRequest, selectedId)
      setReport(fresh)
      setNotice("人工终裁已落库——机器结论与人工结论并列留痕，未改写任何机器行。")
    } catch (caught) {
      // 落库已成功、仅刷新失败：不得谎报为提交失败（防用户重复提交）。
      setNotice(`人工终裁已落库，但刷新报告失败：${errorText(caught)}——重新选中运行即可看到回显。`)
    } finally {
      setBusy(false)
    }
  }

  // 执行面过滤（客户端收窄 ≤200 行的列表；服务端列表无 adapter_mode 参数）。
  const visibleRuns = adapterMode ? runs.filter((run) => run.adapter_mode === adapterMode) : runs

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
            <span>目标场景（发起运行时选用）</span>
            <select
              value={selectedScenarioId}
              onChange={(event) => setSelectedScenarioId(event.target.value)}
              aria-label="目标场景"
              disabled={scenarios.length === 0}
            >
              {scenarios.length === 0 ? (
                <option value="">暂无可用案例</option>
              ) : (
                scenarios.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}（{item.scenario_key} · v{item.version}）
                  </option>
                ))
              )}
            </select>
          </label>
          <label>
            <span>执行面（过滤列表；发起新运行也用它）</span>
            <select
              value={adapterMode}
              onChange={(event) =>
                setAdapterMode(event.target.value as "" | "mock" | "workbench" | "real")
              }
              aria-label="执行面"
            >
              <option value="">全部执行面</option>
              <option value="mock">脚本化替身（mock）</option>
              <option value="workbench">工作台内嵌模型（workbench）</option>
              <option value="real">真实执行面（real）</option>
            </select>
          </label>
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
        {!loading && runs.length > 0 && visibleRuns.length === 0 ? (
          <p className="simulation-empty">
            当前过滤条件下没有运行——「执行面」选「全部执行面」可看全部 {runs.length} 条。
          </p>
        ) : null}
        {!loading && visibleRuns.length > 0 ? (
          <p className="simulation-hint">
            {visibleRuns.length === runs.length
              ? `共 ${runs.length} 条运行`
              : `过滤后 ${visibleRuns.length} / ${runs.length} 条运行`}
            ；要找某一次运行，认每行开头的短编号（#开头 8 位）。
          </p>
        ) : null}
        <ul className="simulation-run-list">
          {visibleRuns.map((run) => (
            <li
              key={run.id}
              className={`simulation-run-item${run.id === selectedId ? " active" : ""}`}
            >
              <button type="button" onClick={() => setSelectedId(run.id)}>
                <code className="simulation-run-id">#{run.id.slice(0, 8)}</code>
                <span className={`simulation-status simulation-status-${run.status}`}>
                  {RUN_STATUS_LABEL[run.status]}
                </span>
                <span className="simulation-run-split">{SPLIT_LABEL[run.split]}</span>
                <span className="simulation-run-adapter">
                  {run.adapter_mode === "real"
                    ? "真实执行面"
                    : run.adapter_mode === "workbench"
                      ? "工作台内嵌模型"
                      : "脚本化替身"}
                </span>
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
                  {traces.map((trace) => {
                    const artifactValue = trace.payload?.artifact
                    const canExpandArtifact = hasExpandableArtifact(artifactValue)
                    const isExpanded = expandedTraceSeqs.includes(trace.seq)
                    return (
                      <li key={trace.seq}>
                        <div className="simulation-trace-row-head">
                          <span className="simulation-trace-seq">#{trace.seq}</span>
                          <span className="simulation-trace-phase">{trace.phase}</span>
                          <span className="simulation-trace-event">{trace.event_type}</span>
                          <span className="simulation-trace-payload">
                            {Object.entries(trace.payload ?? {})
                              .filter(([key]) => key !== "artifact")
                              .map(([key, value]) => `${key}=${String(value).slice(0, 60)}`)
                              .join("；")}
                          </span>
                          {integrationStatus(trace) ? (
                            <span className="simulation-trace-integration">
                              接线状态 {integrationStatus(trace)}
                            </span>
                          ) : null}
                          {canExpandArtifact ? (
                            <UiButton
                              compact
                              aria-expanded={isExpanded}
                              onClick={() => {
                                setExpandedTraceSeqs((prev) =>
                                  prev.includes(trace.seq)
                                    ? prev.filter((item) => item !== trace.seq)
                                    : [...prev, trace.seq],
                                )
                              }}
                            >
                              {isExpanded ? "收起交付原文" : "展开交付原文"}
                            </UiButton>
                          ) : null}
                        </div>
                        {canExpandArtifact && isExpanded ? renderArtifactDetail(artifactValue) : null}
                      </li>
                    )
                  })}
                </ol>
              )}
            </section>

            <EvaluationReport
              report={report ?? emptyReport()}
              onRecordHuman={
                canAdjudicate
                  ? async (payload) => {
                      await handleRecordHuman(payload)
                    }
                  : undefined
              }
            />

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
