// V3.2 G7 / L4-⑦ · 失败分析与「失败 → AI 起草候选载荷 → 创建改进提案」返件式流程。
//
// 发现清单按严重度排序；每条显示**根因置信度**（confirmed / likely / hypothesis）——
// - L-B 模型建议行（likely）标明「L-B 模型建议 · 待 L-C 复核后方可提案」；
// - 只有 confirmed 的根因能勾选创建正式改进提案；
// - 「AI 起草候选」走 POST /simulation/findings/draft-ai（返件式零落库），
//   用户挑选载体（动态经验卡 lesson_entry / 知识库技能草稿 skill_version_draft /
//   追加提示词片段 prompt_overlay_fragment）并审阅编辑后，显式点击「创建改进提案」才落库。

import { useState, type ReactElement } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { AsyncButton, UiButton } from "../components/ui"
import { createProposal, draftImprovementsAi } from "./api"
import type { DraftAiGroupDto, FindingDto, ProposalDto } from "./types"

const SEVERITY_LABEL: Record<FindingDto["severity"], string> = {
  high: "高",
  medium: "中",
  low: "低",
}

const CONFIDENCE_LABEL: Record<string, string> = {
  confirmed: "已确认",
  likely: "较可能（L-B 建议）",
  hypothesis: "待人工确认",
}

type CarrierChoice = "lesson_entry" | "skill_version_draft" | "prompt_overlay_fragment"

const CARRIER_LABEL: Record<CarrierChoice, string> = {
  lesson_entry: "动态经验卡（Lesson）",
  skill_version_draft: "知识库技能草稿（Skill）",
  prompt_overlay_fragment: "提示词追加片段（Overlay ≤200字）",
}

function errorText(caught: unknown): string {
  if (caught instanceof ApiClientError) return caught.message
  if (caught instanceof Error) return caught.message
  return "操作失败，请稍后重试。"
}

function defaultTargetKindForCarrier(carrier: CarrierChoice): string {
  if (carrier === "skill_version_draft") return "skill"
  if (carrier === "prompt_overlay_fragment") return "prompt"
  return "rule"
}

export function FailureAnalysis({
  findings,
  onAnalyze,
  onProposalCreated,
  busy,
}: {
  findings: FindingDto[]
  onAnalyze?(): Promise<void>
  onProposalCreated?(proposal: ProposalDto): void
  busy?: boolean
}): ReactElement {
  const { apiRequest } = useAuth()
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [draftGroups, setDraftGroups] = useState<DraftAiGroupDto[]>([])
  const [activeGroupIdx, setActiveGroupIdx] = useState(0)
  const [carrier, setCarrier] = useState<CarrierChoice>("lesson_entry")
  const [targetKind, setTargetKind] = useState("rule")
  const [targetRef, setTargetRef] = useState("agent.module.discovery")
  const [changeSummary, setChangeSummary] = useState("")
  const [lessonText, setLessonText] = useState("")
  const [lessonTier, setLessonTier] = useState("agent.module.discovery")
  const [lessonIndustries, setLessonIndustries] = useState("general")
  const [lessonRationale, setLessonRationale] = useState("")
  const [skillRef, setSkillRef] = useState("")
  const [skillSummary, setSkillSummary] = useState("")
  const [skillDelta, setSkillDelta] = useState("")
  const [overlayPurpose, setOverlayPurpose] = useState("simulation_workbench")
  const [overlayFragment, setOverlayFragment] = useState("")
  const [overlayRationale, setOverlayRationale] = useState("")
  const [formOpen, setFormOpen] = useState(false)
  const [draftNotice, setDraftNotice] = useState("")
  const [draftError, setDraftError] = useState("")

  const ordered = [...findings].sort((left, right) => {
    const rank = { high: 0, medium: 1, low: 2 }
    return rank[left.severity] - rank[right.severity]
  })

  function applyGroupToForm(group: DraftAiGroupDto, nextCarrier: CarrierChoice): void {
    setLessonText(group.lesson_entry.text)
    setLessonTier(group.lesson_entry.tier)
    setLessonIndustries(group.lesson_entry.industries.join(","))
    setLessonRationale(group.lesson_entry.rationale)
    setSkillRef(group.skill_version_draft.skill_ref)
    setSkillSummary(group.skill_version_draft.summary)
    setSkillDelta(group.skill_version_draft.instructions_delta)
    setOverlayPurpose(group.prompt_overlay_fragment.purpose_key)
    setOverlayFragment(group.prompt_overlay_fragment.fragment)
    setOverlayRationale(group.prompt_overlay_fragment.rationale)
    const kind = defaultTargetKindForCarrier(nextCarrier)
    setTargetKind(kind)
    if (nextCarrier === "lesson_entry") {
      setTargetRef(group.lesson_entry.tier || "agent.module.discovery")
      setChangeSummary(group.lesson_entry.text)
    } else if (nextCarrier === "skill_version_draft") {
      setTargetRef(group.skill_version_draft.skill_ref || "fde-discovery")
      setChangeSummary(group.skill_version_draft.summary)
    } else {
      setTargetRef(group.prompt_overlay_fragment.purpose_key || "simulation_workbench")
      setChangeSummary(group.prompt_overlay_fragment.fragment)
    }
  }

  function toggleFinding(id: string): void {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]))
  }

  async function handleDraftAi(): Promise<void> {
    if (selectedIds.length === 0) {
      setDraftError("请先勾选至少一条失败发现再执行 AI 起草。")
      return
    }
    setDraftError("")
    setDraftNotice("")
    try {
      const response = await draftImprovementsAi(apiRequest, { finding_ids: selectedIds })
      const groups = response.draft?.groups ?? []
      setDraftGroups(groups)
      setActiveGroupIdx(0)
      setFormOpen(true)
      if (groups[0]) {
        applyGroupToForm(groups[0], carrier)
      }
      setDraftNotice(
        `AI 已起草 ${groups.length} 组候选载荷（零落库返件，指纹 ${response.payload_sha256}）——请核对后创建提案。`,
      )
    } catch (caught) {
      setDraftError(errorText(caught))
    }
  }

  function buildCandidatePayload(): Record<string, unknown> | undefined {
    if (carrier === "lesson_entry" && lessonText.trim()) {
      const industries = lessonIndustries
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
      return {
        lesson_entry: {
          text: lessonText.trim(),
          tier: lessonTier.trim() || "agent.module.discovery",
          industries: industries.length > 0 ? industries : ["general"],
          rationale: lessonRationale.trim() || "基于训练场失败发现蒸馏",
        },
      }
    }
    if (carrier === "skill_version_draft" && skillRef.trim() && skillDelta.trim()) {
      return {
        skill_version_draft: {
          skill_ref: skillRef.trim(),
          summary: skillSummary.trim() || changeSummary.trim(),
          instructions_delta: skillDelta.trim(),
        },
      }
    }
    if (carrier === "prompt_overlay_fragment" && overlayPurpose.trim() && overlayFragment.trim()) {
      return {
        prompt_overlay_fragment: {
          purpose_key: overlayPurpose.trim(),
          fragment: overlayFragment.trim(),
          rationale: overlayRationale.trim() || "基于训练场失败发现追加防呆约束",
        },
      }
    }
    return undefined
  }

  async function handleCreateProposal(): Promise<void> {
    const confirmedSelected = ordered
      .filter(
        (f) =>
          selectedIds.includes(f.id) &&
          f.root_causes.some((c) => c.confidence === "confirmed"),
      )
      .map((f) => f.id)
    if (confirmedSelected.length === 0) {
      setDraftError("创建正式提案要求所勾选发现至少包含一条「已确认（confirmed）」根因。")
      return
    }
    if (!targetRef.trim() || !changeSummary.trim()) {
      setDraftError("改进目标引用（target.ref）与变更摘要均为必填。")
      return
    }
    setDraftError("")
    try {
      const candidatePayload = buildCandidatePayload()
      const created = await createProposal(apiRequest, {
        finding_ids: confirmedSelected,
        target: { kind: targetKind, ref: targetRef.trim() },
        change_summary: changeSummary.trim(),
        ...(candidatePayload ? { candidate_payload: candidatePayload } : {}),
      })
      setDraftNotice(
        `已创建改进提案 ${created.proposal_key}（状态：评审中）——可在「改进提案」标签页完成审批与发布。`,
      )
      setFormOpen(false)
      onProposalCreated?.(created)
    } catch (caught) {
      setDraftError(errorText(caught))
    }
  }

  return (
    <section className="simulation-findings" aria-label="失败分析">
      <header className="simulation-section-header">
        <h3>失败分析</h3>
        <div className="simulation-row-actions">
          {onAnalyze ? (
            <button type="button" onClick={() => void onAnalyze()} disabled={busy}>
              {busy ? "分析中…" : "执行失败分析"}
            </button>
          ) : null}
          {ordered.length > 0 ? (
            <>
              <AsyncButton
                variant="primary"
                actionKey="simulation-findings-draft-ai"
                disabled={busy || selectedIds.length === 0}
                onRun={async () => {
                  await handleDraftAi()
                }}
              >
                AI 起草改进候选
              </AsyncButton>
              <UiButton
                disabled={busy || selectedIds.length === 0}
                onClick={() => setFormOpen((prev) => !prev)}
              >
                {formOpen ? "收起建案表单" : "手工/编辑建案"}
              </UiButton>
            </>
          ) : null}
        </div>
      </header>

      {draftNotice ? (
        <p className="simulation-notice" role="status">
          {draftNotice}
        </p>
      ) : null}
      {draftError ? (
        <p className="simulation-error" role="alert">
          {draftError}
        </p>
      ) : null}

      {formOpen ? (
        <div className="simulation-release-inline-form" role="region" aria-label="创建改进提案表单">
          {draftGroups.length > 1 ? (
            <label>
              <span>失败分类组</span>
              <select
                aria-label="失败分类组"
                value={String(activeGroupIdx)}
                onChange={(event) => {
                  const idx = Number(event.target.value)
                  setActiveGroupIdx(idx)
                  if (draftGroups[idx]) applyGroupToForm(draftGroups[idx], carrier)
                }}
              >
                {draftGroups.map((g, idx) => (
                  <option key={g.code} value={String(idx)}>
                    {g.code}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label>
            <span>进化载体类型</span>
            <select
              aria-label="进化载体类型"
              value={carrier}
              onChange={(event) => {
                const next = event.target.value as CarrierChoice
                setCarrier(next)
                if (draftGroups[activeGroupIdx]) {
                  applyGroupToForm(draftGroups[activeGroupIdx], next)
                } else {
                  setTargetKind(defaultTargetKindForCarrier(next))
                }
              }}
            >
              {(Object.keys(CARRIER_LABEL) as CarrierChoice[]).map((key) => (
                <option key={key} value={key}>
                  {CARRIER_LABEL[key]}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>改进目标种类（target.kind）</span>
            <select
              aria-label="改进目标种类"
              value={targetKind}
              onChange={(event) => setTargetKind(event.target.value)}
            >
              <option value="rule">规则/经验卡（rule）</option>
              <option value="skill">技能（skill）</option>
              <option value="prompt">提示词（prompt）</option>
              <option value="workflow_template">工作流模板（workflow_template）</option>
              <option value="ontology">本体（ontology）</option>
              <option value="case">案例（case）</option>
            </select>
          </label>
          <label>
            <span>目标标识（target.ref）</span>
            <input
              aria-label="目标标识"
              value={targetRef}
              onChange={(event) => setTargetRef(event.target.value)}
            />
          </label>
          <label>
            <span>变更摘要（必填）</span>
            <input
              aria-label="变更摘要"
              value={changeSummary}
              onChange={(event) => setChangeSummary(event.target.value)}
            />
          </label>

          {carrier === "lesson_entry" ? (
            <>
              <label>
                <span>经验卡正文（≤300字）</span>
                <textarea
                  aria-label="经验卡正文"
                  rows={2}
                  value={lessonText}
                  onChange={(event) => setLessonText(event.target.value)}
                />
              </label>
              <label>
                <span>适用能力腿（tier）</span>
                <input
                  aria-label="适用能力腿"
                  value={lessonTier}
                  onChange={(event) => setLessonTier(event.target.value)}
                />
              </label>
              <label>
                <span>适用行业（逗号分隔）</span>
                <input
                  aria-label="适用行业"
                  value={lessonIndustries}
                  onChange={(event) => setLessonIndustries(event.target.value)}
                />
              </label>
            </>
          ) : null}

          {carrier === "skill_version_draft" ? (
            <>
              <label>
                <span>技能标识（skill_ref）</span>
                <input
                  aria-label="技能标识"
                  value={skillRef}
                  onChange={(event) => setSkillRef(event.target.value)}
                />
              </label>
              <label>
                <span>指令增量草稿（instructions_delta）</span>
                <textarea
                  aria-label="指令增量草稿"
                  rows={3}
                  value={skillDelta}
                  onChange={(event) => setSkillDelta(event.target.value)}
                />
              </label>
            </>
          ) : null}

          {carrier === "prompt_overlay_fragment" ? (
            <>
              <label>
                <span>目标用途（purpose_key）</span>
                <input
                  aria-label="目标用途"
                  value={overlayPurpose}
                  onChange={(event) => setOverlayPurpose(event.target.value)}
                />
              </label>
              <label>
                <span>追加陈述片段（≤200字）</span>
                <textarea
                  aria-label="追加陈述片段"
                  rows={2}
                  value={overlayFragment}
                  onChange={(event) => setOverlayFragment(event.target.value)}
                />
              </label>
            </>
          ) : null}

          <div className="simulation-row-actions">
            <AsyncButton
              variant="primary"
              actionKey="simulation-proposal-create"
              disabled={busy}
              onRun={async () => {
                await handleCreateProposal()
              }}
            >
              创建改进提案
            </AsyncButton>
            <UiButton disabled={busy} onClick={() => setFormOpen(false)}>
              取消
            </UiButton>
          </div>
        </div>
      ) : null}

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
            const likelyOnly =
              !confirmed &&
              finding.root_causes.some((cause) => cause.confidence === "likely")
            const checked = selectedIds.includes(finding.id)
            return (
              <li key={finding.id} className={`simulation-finding simulation-severity-${finding.severity}`}>
                <header>
                  <label className="simulation-finding-check">
                    <input
                      type="checkbox"
                      aria-label={`选择发现 ${finding.code}`}
                      checked={checked}
                      onChange={() => toggleFinding(finding.id)}
                    />
                    <code>{finding.code}</code>
                  </label>
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
                  ) : likelyOnly ? (
                    <span className="simulation-hint">
                      L-B 模型建议 · 根因未确认——完成 L-C 人工复核确认后方可建正式提案
                    </span>
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
