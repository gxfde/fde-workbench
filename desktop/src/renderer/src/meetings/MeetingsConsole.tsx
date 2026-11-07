import { useCallback, useEffect, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"

// T-A8 评审会控制台（台账「售前主线登记」节）：会议列表 → 话轮流 → 纪要呈现。
// 页面仅呈现（拍板 6⑥：与 B#9 执行事实面板界面分离）；召集/插话/收敛等写
// 操作不在本页，服务端 403/409 原样呈现不吞。纪要只在 closed 会议拉取
// （live/paused 尚未封存，不预取）。

interface MeetingRowDto {
  id: string
  project_id: string
  template_id: string
  status: string
  gate_tier: string
  trigger: string
  turns_count: number
  hosted_by_user_id: string
  degraded: boolean
  created_at: string | null
}

interface MeetingTurnDto {
  seq: number
  speaker_agent_id: string | null
  speaker_user_id: string | null
  content: Record<string, unknown>
}

interface MeetingDetailDto extends MeetingRowDto {
  turns: MeetingTurnDto[]
}

interface MinutesDto {
  id: string
  meeting_id: string
  consensus: Array<Record<string, unknown>>
  disputes: Array<Record<string, unknown>>
  todos: Array<Record<string, unknown>>
  sealed_sha256: string
  created_at: string | null
}

interface MeetingListDto {
  items: MeetingRowDto[]
  truncated: boolean
}

const MEETING_STATUS_LABEL: Record<string, string> = {
  live: "进行中",
  paused: "已暂停",
  closed: "已收敛",
}

const GATE_TIER_LABEL: Record<string, string> = {
  lite: "轻量门",
  std: "标准门",
  full: "完整门",
}

const TRIGGER_LABEL: Record<string, string> = {
  mandatory: "强制门",
  adhoc: "自主召集",
  manual: "人工开会",
}

function statusLabel(map: Record<string, string>, value: string): string {
  return map[value] ?? value
}

function shortId(value: string): string {
  return value.length > 8 ? value.slice(0, 8) : value
}

function actionMessage(caught: unknown): string {
  if (caught instanceof ApiClientError) return caught.message
  if (caught instanceof Error) return caught.message
  return "操作失败，请重试。"
}

function turnText(content: Record<string, unknown>): string {
  const text = content.text
  return typeof text === "string" ? text : JSON.stringify(content)
}

function entryText(entry: Record<string, unknown>): string {
  const text = entry.text
  return typeof text === "string" ? text : JSON.stringify(entry)
}

interface MeetingsConsoleProps {
  projectId: string
}

export function MeetingsConsole({ projectId }: MeetingsConsoleProps) {
  const { apiRequest } = useAuth()
  const [meetings, setMeetings] = useState<MeetingRowDto[]>([])
  const [truncated, setTruncated] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [detailError, setDetailError] = useState("")
  const [expandedMeetingId, setExpandedMeetingId] = useState<string | null>(null)
  const [detail, setDetail] = useState<MeetingDetailDto | null>(null)
  const [minutes, setMinutes] = useState<MinutesDto | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const load = useCallback(async (): Promise<void> => {
    setError("")
    try {
      const data = await apiRequest<MeetingListDto>(
        `/api/v1/meetings?project_id=${encodeURIComponent(projectId)}`,
        { method: "GET" },
      )
      setMeetings(data.items)
      setTruncated(data.truncated)
    } catch (caught) {
      setError(actionMessage(caught))
    }
  }, [apiRequest, projectId])

  useEffect(() => {
    let active = true
    setLoading(true)
    void load().finally(() => {
      if (active) setLoading(false)
    })
    return () => {
      active = false
    }
  }, [load])

  async function toggleMeetingDetail(meeting: MeetingRowDto): Promise<void> {
    if (expandedMeetingId === meeting.id) {
      setExpandedMeetingId(null)
      setDetail(null)
      setMinutes(null)
      return
    }
    setDetailError("")
    setExpandedMeetingId(meeting.id)
    setDetail(null)
    setMinutes(null)
    setDetailLoading(true)
    try {
      const data = await apiRequest<MeetingDetailDto>(
        `/api/v1/meetings/${encodeURIComponent(meeting.id)}`,
        { method: "GET" },
      )
      setDetail(data)
      if (data.status === "closed") {
        try {
          const minutesData = await apiRequest<MinutesDto>(
            `/api/v1/meetings/${encodeURIComponent(meeting.id)}/minutes`,
            { method: "GET" },
          )
          setMinutes(minutesData)
        } catch (caught) {
          setDetailError(actionMessage(caught))
        }
      }
    } catch (caught) {
      setDetailError(actionMessage(caught))
      setExpandedMeetingId(null)
    } finally {
      setDetailLoading(false)
    }
  }

  if (loading) return <p className="empty-copy" role="status">正在加载评审会…</p>
  if (error) return <p className="empty-copy" role="alert">{error}</p>

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>评审会</h2>
            <p>本项目的评审会议列表（协作过程）；话轮流与纪要在详情按需展开。</p>
          </div>
        </div>
        {meetings.length ? (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">会议</th>
                <th scope="col">状态</th>
                <th scope="col">模板</th>
                <th scope="col">门档</th>
                <th scope="col">召集缘由</th>
                <th scope="col">话轮</th>
                <th scope="col">召集时间</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {meetings.map((meeting) => (
                <tr key={meeting.id}>
                  <td><code>{shortId(meeting.id)}</code>{meeting.degraded ? <div><small>守卫降级标注</small></div> : null}</td>
                  <td>{statusLabel(MEETING_STATUS_LABEL, meeting.status)}</td>
                  <td><code>{meeting.template_id}</code></td>
                  <td>{statusLabel(GATE_TIER_LABEL, meeting.gate_tier)}</td>
                  <td>{statusLabel(TRIGGER_LABEL, meeting.trigger)}</td>
                  <td>{meeting.turns_count}</td>
                  <td>{meeting.created_at ? meeting.created_at.slice(0, 19).replace("T", " ") : "—"}</td>
                  <td>
                    <button
                      className="secondary-button"
                      disabled={detailLoading && expandedMeetingId === meeting.id}
                      onClick={() => void toggleMeetingDetail(meeting)}
                    >
                      {expandedMeetingId === meeting.id ? "收起" : "详情"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="empty-copy">本项目还没有评审会议。</p>
        )}
        {truncated ? <p className="empty-copy">已显示最近的会议，更早的记录未列出。</p> : null}
      </section>

      {expandedMeetingId ? (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>会议详情</h2>
              <p>话轮流（按序）；纪要在会议收敛封存后生成。</p>
            </div>
          </div>
          {detailError ? <p role="alert" className="empty-copy">{detailError}</p> : null}
          {detailLoading ? <p className="empty-copy" role="status">正在加载详情…</p> : null}
          {detail && !detailLoading ? (
            <div className="page-stack">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col">发言方</th>
                    <th scope="col">内容</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.turns.length ? (
                    detail.turns.map((turn) => (
                      <tr key={turn.seq}>
                        <td>{turn.seq}</td>
                        <td>
                          {turn.speaker_agent_id ? <code>智能体 {shortId(turn.speaker_agent_id)}</code> : null}
                          {turn.speaker_user_id ? <code>成员 {shortId(turn.speaker_user_id)}</code> : null}
                        </td>
                        <td>{turnText(turn.content)}</td>
                      </tr>
                    ))
                  ) : (
                    <tr><td colSpan={3}>该会议暂无话轮。</td></tr>
                  )}
                </tbody>
              </table>
              {detail.status === "closed" ? (
                minutes ? (
                  <div className="page-stack">
                    <h3>纪要（已封存）</h3>
                    <p><small>sealed_sha256: <code>{minutes.sealed_sha256.slice(0, 16)}…</code></small></p>
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th scope="col">共识</th>
                          <th scope="col">分歧</th>
                          <th scope="col">待办</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <td>{minutes.consensus.length ? <ul>{minutes.consensus.map((entry, index) => <li key={index}>{entryText(entry)}</li>)}</ul> : "—"}</td>
                          <td>{minutes.disputes.length ? <ul>{minutes.disputes.map((entry, index) => <li key={index}>{entryText(entry)}</li>)}</ul> : "—"}</td>
                          <td>{minutes.todos.length ? <ul>{minutes.todos.map((entry, index) => <li key={index}>{entryText(entry)}</li>)}</ul> : "—"}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                ) : (
                  !detailError ? <p className="empty-copy" role="status">正在加载纪要…</p> : null
                )
              ) : (
                <p className="empty-copy">会议收敛后生成纪要（当前状态：{statusLabel(MEETING_STATUS_LABEL, detail.status)}）。</p>
              )}
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  )
}
