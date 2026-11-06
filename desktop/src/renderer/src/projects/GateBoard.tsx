import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { Loading } from "../components/ui"
import {
  FALLBACK_OPTIONS,
  gateStatusLabel,
  gateStatusTone,
  mergeOptions,
  type WorkbenchOptions,
} from "../workbench/options"

// P3 门禁引擎（设计 §5）：只读投影 + 证据提交/人工核验。
// 状态语义照搬 SOP——pending/evidence/passed/conditional_pass/failed 五态，
// G8 过门必带 proceed/pivot/stop，conditional_pass 仅 G9；
// claimed ≠ accepted：清单项 accepted 之外一律黄标（§5.3）。

interface ChecklistItem {
  label: string
  claim_status: string | null
  source_uri: string | null
  content_hash: string | null
}

// V3 T-G1：任务产物候选（服务端建议性提示；采纳走既有提交闸）。可选键——
// 旧服务端载荷不带此键时照常渲染（读时兼容）。
// V3 T-W7 桌面腿：候选按 source_kind 分两形——task 形（T-G1 起旧行读时缺省）
// 与 workflow 形（运行时保留键 gate_evidence 的节点产物）；两形都只收指针+指纹。
interface TaskEvidenceCandidate {
  source_kind?: "task"
  source_uri: string
  content_hash: string
  task_id: string
  task_key: string
  task_name: string
  proposed_by_user_id: string
  proposed_at: string
}

interface WorkflowEvidenceCandidate {
  source_kind: "workflow"
  source_uri: string
  content_hash: string
  workflow_run_id: string
  workflow_node_key: string
  label: string
  proposed_by_user_id: string
  proposed_at: string
}

type GateEvidenceCandidate = TaskEvidenceCandidate | WorkflowEvidenceCandidate

interface GateDto {
  gate_key: string
  status: string
  decision: string | null
  submitted_at: string | null
  decided_at: string | null
  checklist: ChecklistItem[]
  evidence_candidates?: GateEvidenceCandidate[]
  gate_name: string | null
  node_key: string | null
  exit_condition: string | null
  evidence_location: string | null
  contract_payment: string | null
  signer_role: string | null
  fail_exit: string | null
  decision_semantics: string[] | null
  template_source_uri: string | null
}

interface GateEventDto {
  event_type: string
  occurred_at: string
  actor_display_name: string | null
  changes: Record<string, unknown>
}

interface GatesView {
  project_id: string
  sop_phase: string
  gates: GateDto[]
  events: GateEventDto[]
}

interface GateBoardProps {
  projectId: string
  canManage: boolean
}

// 门禁五态的标签与徽标样式由服务端选项表下发（J1），本地兜底见 workbench/options.ts。
const DECISION_LABEL: Record<string, string> = {
  proceed: "proceed 继续",
  pivot: "pivot 转向",
  stop: "stop 停止",
}

const EVENT_LABEL: Record<string, string> = {
  gates_instantiated: "门禁实例化",
  gate_evidence_submitted: "提交证据",
  gate_decided: "门禁拍板",
  gate_evidence_candidate_attached: "挂候选证据",
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

// V3 T-W7：候选守卫按 source_kind 分形——workflow 形带 run/节点键与 label
// （缺任一即整板拒载，沿 T-G1「在场必须形状齐全」口径）；task 形三键齐全，
// source_kind 读时缺省（服务端旧行不带该键，读时合并为 "task"）。
function isTaskEvidenceCandidate(value: unknown): value is TaskEvidenceCandidate {
  return (
    isRecord(value) &&
    (value.source_kind === undefined || value.source_kind === "task") &&
    typeof value.source_uri === "string" &&
    typeof value.content_hash === "string" &&
    typeof value.task_id === "string" &&
    typeof value.task_key === "string" &&
    typeof value.task_name === "string" &&
    typeof value.proposed_by_user_id === "string" &&
    typeof value.proposed_at === "string"
  )
}

function isWorkflowEvidenceCandidate(value: unknown): value is WorkflowEvidenceCandidate {
  return (
    isRecord(value) &&
    value.source_kind === "workflow" &&
    typeof value.source_uri === "string" &&
    typeof value.content_hash === "string" &&
    typeof value.workflow_run_id === "string" &&
    typeof value.workflow_node_key === "string" &&
    typeof value.label === "string" &&
    typeof value.proposed_by_user_id === "string" &&
    typeof value.proposed_at === "string"
  )
}

function isGateEvidenceCandidate(value: unknown): value is GateEvidenceCandidate {
  return isWorkflowEvidenceCandidate(value) || isTaskEvidenceCandidate(value)
}

function isGatesView(value: unknown): value is GatesView {
  if (!isRecord(value) || typeof value.project_id !== "string") return false
  if (typeof value.sop_phase !== "string" || !Array.isArray(value.gates)) return false
  return value.gates.every(
    (gate) =>
      isRecord(gate) &&
      typeof gate.gate_key === "string" &&
      typeof gate.status === "string" &&
      Array.isArray(gate.checklist) &&
      gate.checklist.every(
        (item) => isRecord(item) && typeof item.label === "string",
      ) &&
      // V3 T-G1：候选可选键——旧载荷缺省合法；在场则必须形状齐全
      (gate.evidence_candidates === undefined ||
        (Array.isArray(gate.evidence_candidates) &&
          gate.evidence_candidates.every(isGateEvidenceCandidate))),
  )
}

export function GateBoard({ projectId, canManage }: GateBoardProps) {
  const { apiRequest } = useAuth()
  const [view, setView] = useState<GatesView | null>(null)
  const [options, setOptions] = useState<WorkbenchOptions>(FALLBACK_OPTIONS)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [actionError, setActionError] = useState("")
  const [busyGate, setBusyGate] = useState("")
  const sequenceRef = useRef(0)

  // J1：选项表由服务端下发；取不到就用本地兜底（界面照常渲染，不阻断读路径）
  useEffect(() => {
    let cancelled = false
    void apiRequest<unknown>("/api/v1/workbench/options", { method: "GET" })
      .then((payload) => {
        if (!cancelled) setOptions(mergeOptions(payload))
      })
      .catch(() => {
        if (!cancelled) setOptions(FALLBACK_OPTIONS)
      })
    return () => {
      cancelled = true
    }
  }, [apiRequest])

  const load = useCallback(async (): Promise<void> => {
    const sequence = ++sequenceRef.current
    try {
      const data = await apiRequest<unknown>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/gates`,
        { method: "GET" },
      )
      if (sequence !== sequenceRef.current) return
      if (!isGatesView(data)) throw new Error("invalid gates view")
      setView(data)
      setError("")
    } catch (caught) {
      if (sequence !== sequenceRef.current) return
      setError(gateError(caught))
    } finally {
      if (sequence === sequenceRef.current) setLoading(false)
    }
  }, [apiRequest, projectId])

  useEffect(() => {
    setLoading(true)
    setView(null)
    setActionError("")
    void load()
  }, [load])

  const submitEvidence = useCallback(
    async (gate: GateDto, items: Array<{ label: string; source_uri: string; content_hash: string }>): Promise<boolean> => {
      setBusyGate(gate.gate_key)
      setActionError("")
      try {
        await apiRequest<unknown>(
          `/api/v1/projects/${encodeURIComponent(projectId)}/gates/${gate.gate_key}/evidence`,
          { method: "POST", body: { items }, retryAfterAuthRefresh: true },
        )
        await load()
        return true
      } catch (caught) {
        setActionError(gateError(caught))
        return false
      } finally {
        setBusyGate("")
      }
    },
    [apiRequest, load, projectId],
  )

  const decide = useCallback(
    async (gate: GateDto, payload: Record<string, unknown>): Promise<boolean> => {
      setBusyGate(gate.gate_key)
      setActionError("")
      try {
        await apiRequest<unknown>(
          `/api/v1/projects/${encodeURIComponent(projectId)}/gates/${gate.gate_key}/decision`,
          { method: "POST", body: payload, retryAfterAuthRefresh: true },
        )
        await load()
        return true
      } catch (caught) {
        setActionError(gateError(caught))
        return false
      } finally {
        setBusyGate("")
      }
    },
    [apiRequest, load, projectId],
  )

  const summary = useMemo(() => {
    if (!view) return null
    const counts: Record<string, number> = {}
    for (const gate of view.gates) counts[gate.status] = (counts[gate.status] ?? 0) + 1
    return counts
  }, [view])

  if (loading) return <Loading label="正在加载门禁…" />
  if (error) return <p className="form-error banner" role="alert">{error}</p>
  if (!view) return null

  return (
    <div className="page-stack">
      <div className="gate-summary">
        <p className="supporting-copy">
          SOP 阶段：<strong>{view.sop_phase}</strong> · 证据真相在 fdeops .fde/ 与 openfde assets/（文件永远赢），
          本页只存出处指针（A4）。清单项未标 accepted 一律视为 claimed 黄标（claimed ≠ accepted）。
        </p>
        {summary ? (
          <div className="gate-summary-badges">
            {Object.entries(summary)
              .filter(([, count]) => count > 0)
              .map(([status, count]) => (
                <span key={status} className={`badge ${gateStatusTone(options, status)}`}>
                  {gateStatusLabel(options, status)} {count}
                </span>
              ))}
          </div>
        ) : null}
      </div>
      {actionError ? <p className="form-error banner" role="alert">{actionError}</p> : null}
      <div className="gate-card-grid">
        {view.gates.map((gate) => (
          <GateCard
            key={gate.gate_key}
            gate={gate}
            canManage={canManage}
            busy={busyGate === gate.gate_key}
            options={options}
            onSubmitEvidence={submitEvidence}
            onDecide={decide}
          />
        ))}
      </div>
      <GateEventFeed events={view.events} />
    </div>
  )
}

interface GateCardProps {
  gate: GateDto
  canManage: boolean
  busy: boolean
  /** J1：门禁状态标签/样式由服务端选项表下发（含本地兜底） */
  options: WorkbenchOptions
  onSubmitEvidence: (
    gate: GateDto,
    items: Array<{ label: string; source_uri: string; content_hash: string }>,
  ) => Promise<boolean>
  onDecide: (gate: GateDto, payload: Record<string, unknown>) => Promise<boolean>
}

function GateCard({ gate, canManage, busy, options, onSubmitEvidence, onDecide }: GateCardProps) {
  const [mode, setMode] = useState<"idle" | "submit" | "decide">("idle")
  const [uris, setUris] = useState<Record<string, string>>({})
  const [hashes, setHashes] = useState<Record<string, string>>({})
  const [accepted, setAccepted] = useState<Record<string, boolean>>({})
  const [result, setResult] = useState<string>("pass")
  const [g8Decision, setG8Decision] = useState<string>("proceed")
  const [note, setNote] = useState("")
  // V3 T-G1：候选采纳的目标清单项选择（task 形键 = task_key|uri|hash 复合；
  // T-W7：workflow 形键 = wf:run|node|uri|hash——同指纹两形并存时键域不撞）
  const [candidateLabels, setCandidateLabels] = useState<Record<string, string>>({})

  const submittable = gate.status === "pending" || gate.status === "failed"
  // 采纳允许到 evidence 态：部分采纳后再补其余清单项与「重新提交」同一条服务端闸
  const adoptable = canManage && gate.status !== "passed" && gate.status !== "conditional_pass"
  const candidates = gate.evidence_candidates ?? []
  const decidable = gate.status === "evidence"
  const isG8 = gate.gate_key === "G8"
  const isG9 = gate.gate_key === "G9"
  const allFilled = gate.checklist.every(
    (item) =>
      (uris[item.label] ?? "").trim().length > 0 &&
      /^[0-9a-fA-F]{64}$/.test((hashes[item.label] ?? "").trim()),
  )
  const acceptedCount = gate.checklist.filter((item) => accepted[item.label] === true).length

  function openMode(next: "submit" | "decide"): void {
    setMode(next)
    setUris({})
    setHashes({})
    // C2：打开核验面板默认全不勾——claimed ≠ accepted，接受是人工逐项
    // 核验后的动作；预勾选会把「没核验」伪装成「已接受」。
    setAccepted(Object.fromEntries(gate.checklist.map((item) => [item.label, false])))
    setResult("pass")
    setG8Decision("proceed")
    setNote("")
  }

  return (
    <article className={`gate-card status-${gate.status}`}>
      <header className="gate-card-header">
        <div>
          <h3>{gate.gate_key} · {gate.gate_name ?? ""}</h3>
          <p className="gate-card-exit">{gate.exit_condition}</p>
        </div>
        <span className={`badge ${gateStatusTone(options, gate.status)}`}>
          {gateStatusLabel(options, gate.status)}
          {gate.decision ? ` · ${gate.decision}` : ""}
        </span>
      </header>

      <ul className="gate-checklist">
        {gate.checklist.map((item) => (
          <li key={item.label} className={`claim-${item.claim_status ?? "none"}`}>
            <span className="gate-check-label">{item.label}</span>
            <span className={`badge ${item.claim_status === "accepted" ? "success" : item.claim_status === "claimed" ? "warning" : "muted"}`}>
              {item.claim_status === "accepted" ? "accepted" : item.claim_status === "claimed" ? "claimed" : "未提交"}
            </span>
            {item.source_uri ? <small className="gate-evidence-uri">{item.source_uri}</small> : null}
          </li>
        ))}
      </ul>

      {candidates.length > 0 ? (
        <section className="gate-candidates" aria-label="产物候选">
          <p className="supporting-copy">
            产物候选（任务/工作流产物的指针+指纹，已登记为一等证据；采纳走提交闸标 claimed）
          </p>
          <ul>
            {candidates.map((candidate) => {
              const isWorkflow = candidate.source_kind === "workflow"
              const key = isWorkflow
                ? `wf:${candidate.workflow_run_id}:${candidate.workflow_node_key}|${candidate.source_uri}|${candidate.content_hash}`
                : `${candidate.task_key}|${candidate.source_uri}|${candidate.content_hash}`
              const displayName = isWorkflow ? candidate.label : candidate.task_key
              const chosen = candidateLabels[key] ?? gate.checklist[0]?.label ?? ""
              // 人工提交闸 uri 上限 500（与手填表单同限）：超限候选可见但不可采
              const uriOverCap = candidate.source_uri.length > 500
              return (
                <li key={key} className="gate-candidate-row">
                  <span className="gate-check-label">
                    {isWorkflow ? <span className="badge muted">工作流</span> : null}
                    {isWorkflow ? candidate.label : `${candidate.task_key} · ${candidate.task_name}`}
                  </span>
                  {isWorkflow ? (
                    <small className="gate-evidence-uri">
                      run {candidate.workflow_run_id.slice(0, 8)} · 节点 {candidate.workflow_node_key}
                    </small>
                  ) : null}
                  <small className="gate-evidence-uri">{candidate.source_uri}</small>
                  <small className="gate-evidence-uri">{candidate.content_hash}</small>
                  {adoptable ? (
                    <span className="gate-candidate-adopt">
                      <select
                        aria-label={`候选 ${displayName} 的目标清单项`}
                        value={chosen}
                        onChange={(event) =>
                          setCandidateLabels((current) => ({ ...current, [key]: event.target.value }))
                        }
                      >
                        {gate.checklist.map((item) => (
                          <option key={item.label} value={item.label}>{item.label}</option>
                        ))}
                      </select>
                      <button
                        className="secondary-button"
                        type="button"
                        disabled={busy || !chosen || uriOverCap}
                        title={uriOverCap ? "URI 超过人工提交闸 500 上限，无法采纳" : undefined}
                        onClick={() => {
                          void onSubmitEvidence(gate, [
                            { label: chosen, source_uri: candidate.source_uri, content_hash: candidate.content_hash },
                          ])
                        }}
                      >
                        采纳到清单
                      </button>
                    </span>
                  ) : null}
                </li>
              )
            })}
          </ul>
        </section>
      ) : null}

      <dl className="gate-meta">
        <div><dt>证据位置</dt><dd>{gate.evidence_location ?? "—"}</dd></div>
        <div><dt>签核角色</dt><dd>{gate.signer_role ?? "—"}</dd></div>
        {gate.contract_payment ? <div><dt>合同/收款</dt><dd>{gate.contract_payment}</dd></div> : null}
        {gate.submitted_at ? <div><dt>提交于</dt><dd>{formatTime(gate.submitted_at)}</dd></div> : null}
        {gate.decided_at ? <div><dt>拍板于</dt><dd>{formatTime(gate.decided_at)}</dd></div> : null}
      </dl>

      {gate.status === "failed" && gate.fail_exit ? (
        <p className="gate-fail-exit">失败出口：{gate.fail_exit}</p>
      ) : null}
      {gate.status === "conditional_pass" ? (
        <p className="gate-fail-exit conditional">有条件通过（仅 G9 语义）：条件与回补动作按 SOP 上线门执行。</p>
      ) : null}

      {canManage && submittable ? (
        mode === "submit" ? (
          <div className="gate-form">
            <p className="supporting-copy">
              逐项填出处指针与 sha256（certutil -hashfile 文件 SHA256 可生成）：
            </p>
            {gate.checklist.map((item) => (
              <div key={item.label} className="gate-form-row">
                <span className="gate-check-label">{item.label}</span>
                <input
                  value={uris[item.label] ?? ""}
                  onChange={(event) => setUris((current) => ({ ...current, [item.label]: event.target.value }))}
                  placeholder="fdeops://engagements/<代号>/.fde/…"
                  maxLength={500}
                />
                <input
                  value={hashes[item.label] ?? ""}
                  onChange={(event) => setHashes((current) => ({ ...current, [item.label]: event.target.value }))}
                  placeholder="sha256（64 位）"
                  maxLength={64}
                />
              </div>
            ))}
            <div className="gate-form-actions">
              <button
                className="primary-button"
                type="button"
                disabled={busy || !allFilled}
                onClick={() => {
                  // 失败不收表单：已填的指针与 sha256 不丢（核验 400 时用户重敲一遍是灾难）
                  void onSubmitEvidence(
                    gate,
                    gate.checklist.map((item) => ({
                      label: item.label,
                      source_uri: (uris[item.label] ?? "").trim(),
                      content_hash: (hashes[item.label] ?? "").trim().toLowerCase(),
                    })),
                  ).then((ok) => {
                    if (ok) setMode("idle")
                  })
                }}
              >
                {busy ? "提交中…" : "提交证据（标 claimed）"}
              </button>
              <button className="secondary-button" type="button" onClick={() => setMode("idle")}>取消</button>
            </div>
          </div>
        ) : (
          <button className="secondary-button" type="button" disabled={busy} onClick={() => openMode("submit")}>
            {gate.status === "failed" ? "重新提交证据" : "提交证据"}
          </button>
        )
      ) : null}

      {canManage && decidable ? (
        mode === "decide" ? (
          <div className="gate-form">
            <p className="gate-form-hint">人工核验：勾选 = 接受为 accepted；过门要求全部接受。</p>
            {gate.checklist.map((item) => (
              <label key={item.label} className="gate-form-row checkbox">
                <input
                  type="checkbox"
                  checked={accepted[item.label] === true}
                  onChange={(event) => setAccepted((current) => ({ ...current, [item.label]: event.target.checked }))}
                />
                <span className="gate-check-label">{item.label}</span>
                <span className={`badge ${item.claim_status === "accepted" ? "success" : "warning"}`}>
                  {item.claim_status === "accepted" ? "accepted" : "claimed"}
                </span>
              </label>
            ))}
            <div className="gate-form-row">
              <label>
                核验结论
                <select value={result} onChange={(event) => setResult(event.target.value)}>
                  <option value="pass">pass 过门</option>
                  {isG9 ? <option value="conditional_pass">conditional_pass 有条件通过</option> : null}
                  <option value="fail">fail 未过门</option>
                </select>
              </label>
              {isG8 && result === "pass" ? (
                <label>
                  G8 三态拍板
                  <select value={g8Decision} onChange={(event) => setG8Decision(event.target.value)}>
                    <option value="proceed">{DECISION_LABEL.proceed}</option>
                    <option value="pivot">{DECISION_LABEL.pivot}</option>
                    <option value="stop">{DECISION_LABEL.stop}</option>
                  </select>
                </label>
              ) : null}
            </div>
            <input
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="拍板说明（可选，500 字内）"
              maxLength={500}
            />
            <div className="gate-form-actions">
              <button
                className="primary-button"
                type="button"
                disabled={
                  busy ||
                  (result === "pass" && acceptedCount < gate.checklist.length) ||
                  (result === "conditional_pass" && gate.checklist.some((item) => !item.claim_status))
                }
                onClick={() => {
                  const payload: Record<string, unknown> = {
                    result,
                    accepted_labels: gate.checklist
                      .filter((item) => accepted[item.label] === true)
                      .map((item) => item.label),
                  }
                  if (isG8 && result === "pass") payload.decision = g8Decision
                  if (note.trim()) payload.note = note.trim()
                  // 失败不收表单（拍板 400 时勾选与说明不丢）
                  void onDecide(gate, payload).then((ok) => {
                    if (ok) setMode("idle")
                  })
                }}
              >
                {busy ? "提交中…" : `拍板（接受 ${acceptedCount}/${gate.checklist.length}）`}
              </button>
              <button className="secondary-button" type="button" onClick={() => setMode("idle")}>取消</button>
            </div>
          </div>
        ) : (
          <button className="primary-button" type="button" disabled={busy} onClick={() => openMode("decide")}>
            人工核验拍板
          </button>
        )
      ) : null}
    </article>
  )
}

function GateEventFeed({ events }: { events: GateEventDto[] }) {
  if (events.length === 0) return null
  return (
    <section className="gate-events" aria-label="门禁事件留痕">
      <h2>事件留痕（最近 30 条）</h2>
      <ul>
        {events.map((event, index) => (
          <li key={`${event.occurred_at}-${index}`}>
            <span className="gate-event-time">{formatTime(event.occurred_at)}</span>
            <strong>{EVENT_LABEL[event.event_type] ?? event.event_type}</strong>
            {typeof event.changes.gate_key === "string" ? ` · ${event.changes.gate_key}` : ""}
            {event.actor_display_name ? ` · ${event.actor_display_name}` : ""}
            {event.event_type === "gate_decided" && typeof event.changes.result === "string"
              ? ` · ${event.changes.result}${typeof event.changes.decision === "string" ? `/${event.changes.decision}` : ""}`
              : ""}
          </li>
        ))}
      </ul>
    </section>
  )
}

function formatTime(iso: string): string {
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return iso
  return parsed.toLocaleString("zh-CN", { hour12: false })
}

function gateError(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (error.code === "project_not_found") return "项目不存在或已被删除。"
    if (error.code === "forbidden") return "你没有该项目门禁的操作权限。"
    return `门禁操作失败：${error.message}`
  }
  return "门禁数据加载失败，请稍后重试。"
}
