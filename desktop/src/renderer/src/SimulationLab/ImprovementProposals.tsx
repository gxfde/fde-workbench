// V3.2 G7 · 改进提案（页面）。
//
// 界面须把「只提案不落地」讲清楚：**审批 ≠ 发布**；发布由人工在 V3.1 的治理面执行。
// 审批需当前账号密码 + 理由。

import { useCallback, useEffect, useRef, useState, type ReactElement } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { AsyncButton, EmptyState, Loading, UiButton } from "../components/ui"
import { decideProposal, listFindings, listProposals } from "./api"
import type { FindingDto, ProposalDto } from "./types"

const STATUS_LABEL: Record<ProposalDto["status"], string> = {
  draft: "草稿",
  in_review: "评审中",
  approved: "已批准",
  rejected: "已驳回",
}

function errorText(caught: unknown): string {
  if (caught instanceof ApiClientError) return caught.message
  if (caught instanceof Error) return caught.message
  return "操作失败，请稍后重试。"
}

export function ImprovementProposals(): ReactElement {
  const { apiRequest } = useAuth()
  const [proposals, setProposals] = useState<ProposalDto[]>([])
  const [findings, setFindings] = useState<FindingDto[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [password, setPassword] = useState("")
  const [note, setNote] = useState("")
  const sequence = useRef(0)

  const load = useCallback(async () => {
    const requestSequence = ++sequence.current
    try {
      const [proposalPayload, findingPayload] = await Promise.all([
        listProposals(apiRequest),
        listFindings(apiRequest),
      ])
      if (requestSequence !== sequence.current) return
      setProposals(proposalPayload.items)
      setFindings(findingPayload.items)
      setError("")
    } catch (caught) {
      if (requestSequence !== sequence.current) return
      setError(errorText(caught))
    } finally {
      if (requestSequence === sequence.current) setLoading(false)
    }
  }, [apiRequest])

  useEffect(() => {
    void load()
  }, [load])

  async function handleDecide(proposal: ProposalDto, approve: boolean): Promise<void> {
    setBusy(true)
    try {
      await decideProposal(apiRequest, proposal.id, { approve, password, note })
      setNotice(approve ? "已批准（未发布——落地由人工在治理面执行）。" : "已驳回。")
      setPassword("")
      setNote("")
      await load()
    } catch (caught) {
      setNotice(errorText(caught))
    } finally {
      setBusy(false)
    }
  }

  const confirmedFindings = findings.filter((finding) =>
    finding.root_causes.some((cause) => cause.confidence === "confirmed"),
  )

  return (
    <section className="simulation-proposals" aria-label="改进提案">
      <header className="simulation-section-header">
        <h3>改进提案</h3>
        <span className="simulation-hint">
          提案只记录改进方向，不自动修改任何生产 Prompt / Skill / Workflow / 本体；
          审批通过后仍需人工在治理面落地。
        </span>
      </header>

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

      <div className="simulation-approval-form">
        <label>
          <span>当前账号密码（审批用）</span>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <label>
          <span>审批理由（必填）</span>
          <input value={note} onChange={(event) => setNote(event.target.value)} />
        </label>
      </div>

      {loading ? <Loading label="正在加载提案…" /> : null}
      {!loading && proposals.length === 0 ? (
        <EmptyState
          title="尚无改进提案"
          description={`从失败发现生成提案（当前有 ${confirmedFindings.length} 条根因已确认的发现可提）。`}
        />
      ) : null}

      <ul className="simulation-proposal-list">
        {proposals.map((proposal) => (
          <li key={proposal.id} className="simulation-proposal">
            <header>
              <code>{proposal.proposal_key}</code>
              <strong>{proposal.title}</strong>
              <span className={`simulation-proposal-status simulation-status-${proposal.status}`}>
                {STATUS_LABEL[proposal.status]}
              </span>
            </header>
            <p>{proposal.problem}</p>
            <dl className="simulation-proposal-meta">
              <dt>改进对象</dt>
              <dd>
                {proposal.target.kind} · {proposal.target.ref}
              </dd>
              <dt>版本</dt>
              <dd>
                {proposal.current_version} → {proposal.proposed_version}
              </dd>
              <dt>失败分类</dt>
              <dd>{proposal.finding_codes.join("、") || "—"}</dd>
              <dt>变更摘要</dt>
              <dd>{proposal.change_summary}</dd>
              <dt>回归计划</dt>
              <dd>{JSON.stringify(proposal.regression_plan)}</dd>
              {proposal.note ? (
                <>
                  <dt>审批意见</dt>
                  <dd>{proposal.note}</dd>
                </>
              ) : null}
            </dl>
            {proposal.status === "draft" || proposal.status === "in_review" ? (
              <div className="simulation-row-actions">
                <AsyncButton
                  variant="primary"
                  actionKey={`proposal-approve-${proposal.id}`}
                  onRun={async () => {
                    await handleDecide(proposal, true)
                  }}
                >
                  批准（不发布）
                </AsyncButton>
                <AsyncButton
                  variant="danger"
                  actionKey={`proposal-reject-${proposal.id}`}
                  onRun={async () => {
                    await handleDecide(proposal, false)
                  }}
                >
                  驳回
                </AsyncButton>
              </div>
            ) : (
              <p className="simulation-hint">
                已审批（{STATUS_LABEL[proposal.status]}）——落地由人工在治理面执行。
              </p>
            )}
          </li>
        ))}
      </ul>

      <UiButton onClick={() => void load()}>刷新</UiButton>
    </section>
  )
}
