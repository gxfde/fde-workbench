import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiClientError } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

// 终审台「产物+纪要」合并视图（goal-d9，PRD §3.2 P3 / 总纲 U5）。
// 数据源 = GET .../review-trail（d6 纪要回链 + d9 扩展 artifacts/signoff）。
// 拍板动作 = POST .../signoff（approved/rejected）——人工拍板路径，权限档
// 闸在服务端（checkpoint.required_level），前端按 canManage 出按钮、试错透出。

export interface SignoffArtifactView {
  id: string
  run_id: string
  kind: string
  storage_ref: string
  sha256: string
  reviewed: boolean
  linked_solution_id: string | null
  created_at: string
}

export interface SignoffStateView {
  checkpoint_id: string
  status: string
  required_level: string
  reviewer_user_id: string | null
  handoff_run_id: string | null
  evidence_ref: string | null
  created_at: string
  updated_at: string
}

export interface ReviewTrailView {
  solution_id: string
  agent_run_id: string | null
  meetings: {
    id: string
    template_id: string
    status: string
    gate_tier: string
    degraded: boolean
    sealed: boolean
    minutes?: { consensus: unknown[]; disputes: unknown[]; todos: unknown[] } | null
  }[]
  artifacts: SignoffArtifactView[]
  signoff: SignoffStateView | null
}

export function isReviewTrailView(value: unknown): value is ReviewTrailView {
  if (typeof value !== 'object' || value === null) return false
  const row = value as Record<string, unknown>
  return (
    typeof row.solution_id === 'string' &&
    Array.isArray(row.meetings) &&
    Array.isArray(row.artifacts)
  )
}

const KIND_LABELS: Record<string, string> = {
  code: '代码', doc: '文档', diff: '补丁', config: '配置',
}

export function SignoffConsole({ projectId, solutionId, canManage }: { projectId: string; solutionId: string; canManage: boolean }) {
  const { apiRequest } = useAuth()
  const [trail, setTrail] = useState<ReviewTrailView | null>(null)
  const [error, setError] = useState('')
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)
  const sequence = useRef(0)

  const load = useCallback(async () => {
    const request = ++sequence.current
    try {
      const value = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/solutions/${encodeURIComponent(solutionId)}/review-trail`, { method: 'GET' })
      if (request !== sequence.current) return
      if (!isReviewTrailView(value)) throw new Error('invalid review trail')
      setTrail(value); setError('')
    } catch (caught) {
      if (request !== sequence.current) return
      setError(caught instanceof ApiClientError ? caught.message : '终审台数据加载失败，请稍后重试。')
    }
  }, [apiRequest, projectId, solutionId])
  useEffect(() => { void load(); return () => { sequence.current += 1 } }, [load])

  const resolve = useCallback(async (decision: 'approved' | 'rejected') => {
    if (!trail?.signoff || busy) return
    setBusy(true); setActionError('')
    try {
      await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/solutions/${encodeURIComponent(solutionId)}/signoff`, {
        method: 'POST',
        body: { decision },
      })
      await load()
    } catch (caught) {
      setActionError(caught instanceof ApiClientError ? caught.message : '拍板失败，请稍后重试。')
    } finally {
      setBusy(false)
    }
  }, [apiRequest, projectId, solutionId, trail?.signoff, busy, load])

  const signoff = trail?.signoff ?? null
  const pending = signoff?.status === 'pending'

  return <section className="panel signoff-console" role="region" aria-label="终审台（产物+纪要）">
    <h3>终审台 · 产物与纪要</h3>
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    {trail ? <>
      <div className="signoff-artifacts">
        <h4>产物（{trail.artifacts.length}）</h4>
        {trail.artifacts.length === 0 ? <p className="muted">暂无产物留痕（智能体生成路才会有产物）。</p> : (
          <ul>{trail.artifacts.map(artifact => <li key={artifact.id}>
            <strong>{KIND_LABELS[artifact.kind] || artifact.kind}</strong>
            <span className="muted" title={artifact.sha256}>sha256 {artifact.sha256.slice(0, 12)}…</span>
            {artifact.reviewed
              ? <span className="badge muted">已终审</span>
              : <span className="badge warning">待终审</span>}
            {artifact.linked_solution_id
              ? null
              : <span className="badge warning" title="降级/拦截产物不自动进终审通道">未入终审通道</span>}
          </li>)}</ul>
        )}
      </div>
      <div className="signoff-minutes">
        <h4>评审纪要（{trail.meetings.length}）</h4>
        {trail.meetings.length === 0 ? <p className="muted">暂无关联评审会。</p> : (
          <ul>{trail.meetings.map(meeting => <li key={meeting.id}>
            <strong>{meeting.template_id}</strong>
            <span className="muted">{meeting.gate_tier} 档 · {meeting.status}</span>
            {meeting.sealed
              ? <span className="badge muted" title={meeting.minutes ? `共识 ${meeting.minutes.consensus.length} · 分歧 ${meeting.minutes.disputes.length} · 待办 ${meeting.minutes.todos.length}` : '已封存'}>纪要已封存</span>
              : <span className="badge warning">未封存</span>}
            {meeting.degraded ? <span className="badge warning">降级</span> : null}
          </li>)}</ul>
        )}
      </div>
      <div className="signoff-actions">
        <h4>拍板</h4>
        {signoff === null ? <p className="muted">本方案没有终审检查点（L3 转人工收口时创建）。</p> : null}
        {signoff !== null && pending ? <>
          <p className="muted">待收口：required_level={signoff.required_level}{signoff.handoff_run_id ? ' · 触发 run 已关联' : ''}</p>
          {canManage ? <div className="row-actions">
            <button type="button" className="primary-button" disabled={busy} onClick={() => void resolve('approved')}>{busy ? '处理中…' : '拍板通过'}</button>
            <button type="button" className="secondary-button" disabled={busy} onClick={() => void resolve('rejected')}>驳回</button>
          </div> : <p className="muted">当前账号没有拍板权限（权限档闸在服务端）。</p>}
        </> : null}
        {signoff !== null && !pending ? <p>
          终审结论：<strong>{signoff.status === 'approved' ? '已通过' : '已驳回'}</strong>
          <span className="muted">（required_level={signoff.required_level}）</span>
        </p> : null}
        {actionError ? <p className="form-error" role="alert">{actionError}</p> : null}
      </div>
    </> : null}
    {!error && !trail ? <p role="status">正在加载终审台…</p> : null}
  </section>
}
