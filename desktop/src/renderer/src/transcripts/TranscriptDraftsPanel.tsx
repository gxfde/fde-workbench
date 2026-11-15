import { useCallback, useEffect, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"

// T-A9 转写草稿区面板（goal-tb tb1）：presurvey 录入卡旁的「转写上传入口」。
// 红线注记（立项文档 §1 逐字锚）：本面板只收文本——录音原件永不进平台
// （SOP :109「只转写不入正式库」/:111「你录的音不能存」）；文件导入只把
// 本地文本读进表单，原件本身不上传；转写文本入库前已过服务端 T-A2 代号化
// 管线（复核条目回显供人工校对）；晋升须带客户确认三要素，无确认不进正式库。

// 复核账条目（盲审追批零真名换代）：同 guidance/discovery 双形状——指纹条目
// （name 词典反解可空）＋疑似聚合哨兵；旧形状宽容兼容。
interface RedactionEntryDto {
  name?: string | null
  name_hash?: string
  occurrences?: number
  matched_dict?: boolean
  suspect_count?: number
}

interface TranscriptDraftRowDto {
  id: string
  project_id: string
  title: string | null
  status: string
  source_kind: string
  engine: string | null
  created_at: string
  expires_at: string
  cleaned_at: string | null
  client_confirmed_by: string | null
  client_confirmed_at: string | null
  client_confirmation_method: string | null
  promoted_ref: string | null
}

interface TranscriptDraftDetailDto extends TranscriptDraftRowDto {
  content?: string
  content_sha256?: string
  redaction_entries?: RedactionEntryDto[]
}

interface MinutesRowDto {
  id: string
  project_id: string
  title: string
  draft_id: string | null
  redaction_hits: number
  client_confirmed_by: string
  client_confirmed_at: string
  client_confirmation_method: string
  created_at: string
}

interface MinutesDetailDto extends MinutesRowDto {
  content: string
  content_sha256: string
}

interface DraftListDto {
  items: TranscriptDraftRowDto[]
  truncated: boolean
}

interface MinutesListDto {
  items: MinutesRowDto[]
  truncated: boolean
}

const DRAFT_STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  promoted: "已晋升",
  expired: "已过期清理",
  discarded: "已弃置",
}

const SOURCE_KIND_LABEL: Record<string, string> = {
  manual: "人工",
  asr: "本地 ASR",
}

const CONFIRM_METHOD_LABEL: Record<string, string> = {
  verbal: "口头确认",
  written: "书面确认",
  meeting: "会议确认",
}

function statusLabel(map: Record<string, string>, value: string): string {
  return map[value] ?? value
}

function errorMessage(caught: unknown): string {
  if (caught instanceof ApiClientError) return caught.message
  if (caught instanceof Error) return caught.message
  return "操作失败，请重试。"
}

function formatDateTime(value: string | null): string {
  return value ? value.slice(0, 19).replace("T", " ") : "—"
}

function shortSha(value: string | null | undefined): string {
  return value ? value.slice(0, 12) : "—"
}

interface TranscriptDraftsPanelProps {
  projectId: string
  canManage: boolean
}

export function TranscriptDraftsPanel({ projectId, canManage }: TranscriptDraftsPanelProps) {
  const { apiRequest } = useAuth()
  const [drafts, setDrafts] = useState<TranscriptDraftRowDto[]>([])
  const [minutes, setMinutes] = useState<MinutesRowDto[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [formOpen, setFormOpen] = useState(false)
  const [title, setTitle] = useState("")
  const [content, setContent] = useState("")
  const [sourceKind, setSourceKind] = useState<"manual" | "asr">("manual")
  const [engine, setEngine] = useState("")
  const [saving, setSaving] = useState(false)
  const [expandedDraftId, setExpandedDraftId] = useState<string | null>(null)
  const [draftDetail, setDraftDetail] = useState<TranscriptDraftDetailDto | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [promoteDraftId, setPromoteDraftId] = useState<string | null>(null)
  const [promoteTitle, setPromoteTitle] = useState("")
  const [promoteContent, setPromoteContent] = useState("")
  const [confirmedBy, setConfirmedBy] = useState("")
  const [confirmedAt, setConfirmedAt] = useState("")
  const [confirmMethod, setConfirmMethod] = useState<"verbal" | "written" | "meeting">("verbal")
  const [expandedMinutesId, setExpandedMinutesId] = useState<string | null>(null)
  const [minutesDetail, setMinutesDetail] = useState<MinutesDetailDto | null>(null)

  const reload = useCallback(async () => {
    try {
      const [draftList, minutesList] = await Promise.all([
        apiRequest<DraftListDto>(
          `/api/v1/transcript-drafts?project_id=${encodeURIComponent(projectId)}`,
          { method: "GET" },
        ),
        apiRequest<MinutesListDto>(
          `/api/v1/interview-minutes?project_id=${encodeURIComponent(projectId)}`,
          { method: "GET" },
        ),
      ])
      setDrafts(draftList.items)
      setMinutes(minutesList.items)
      setError("")
    } catch {
      // 加载失败静默降级（空态仍在；沿 ProjectGuidanceCard 同款 fail-静默——
      // 草稿区是辅助面板，不与页面级 alert 抢道；动作失败仍走 alert 呈现）
    } finally {
      setLoading(false)
    }
  }, [apiRequest, projectId])

  useEffect(() => {
    void reload()
  }, [reload])

  const importFile = async (file: File | undefined) => {
    if (!file) return
    // 红线：只把文本读进表单（本地文件原件不上传、不落平台存储）
    const text = await file.text()
    setContent(text)
    if (!title) setTitle(file.name.replace(/\.(txt|md|vtt|srt)$/i, ""))
  }

  const createDraft = async () => {
    if (saving) return
    setSaving(true)
    setError("")
    setNotice("")
    try {
      await apiRequest<TranscriptDraftDetailDto>("/api/v1/transcript-drafts", {
        method: "POST",
        // body 契约＝对象：主进程 serializeBody 统一 stringify（预 stringify 会二次编码 → 服务端 4xx）。
        body: {
          project_id: projectId,
          title: title || undefined,
          content,
          source_kind: sourceKind,
          ...(sourceKind === "asr" ? { engine } : {}),
        },
      })
      setNotice("草稿已创建（企业名代号化已执行，复核条目见详情）。T+7 未晋升将自动清理。")
      setTitle(""); setContent(""); setEngine(""); setSourceKind("manual"); setFormOpen(false)
      await reload()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setSaving(false)
    }
  }

  const toggleDraftDetail = async (draft: TranscriptDraftRowDto) => {
    if (expandedDraftId === draft.id) {
      setExpandedDraftId(null); setDraftDetail(null); setPromoteDraftId(null)
      return
    }
    setExpandedDraftId(draft.id); setDraftDetail(null); setPromoteDraftId(null)
    setDetailLoading(true)
    try {
      const detail = await apiRequest<TranscriptDraftDetailDto>(
        `/api/v1/transcript-drafts/${encodeURIComponent(draft.id)}`,
        { method: "GET" },
      )
      setDraftDetail(detail)
    } catch (caught) {
      setError(errorMessage(caught))
      setExpandedDraftId(null)
    } finally {
      setDetailLoading(false)
    }
  }

  const discardDraft = async (draftId: string) => {
    setError(""); setNotice("")
    try {
      await apiRequest(`/api/v1/transcript-drafts/${encodeURIComponent(draftId)}/discard`, { method: "POST" })
      setNotice("草稿已弃置（正文与复核条目已抹除）。")
      if (expandedDraftId === draftId) { setExpandedDraftId(null); setDraftDetail(null) }
      await reload()
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }

  const openPromote = (draft: TranscriptDraftRowDto, detail: TranscriptDraftDetailDto | null) => {
    setPromoteDraftId(draft.id)
    setPromoteTitle(detail?.title ? `${detail.title}（纪要）` : "访谈纪要")
    setPromoteContent(detail?.content ?? "")
    setConfirmedBy("")
    setConfirmedAt(new Date().toISOString())
    setConfirmMethod("verbal")
  }

  const promoteDraft = async () => {
    if (!promoteDraftId || saving) return
    setSaving(true)
    setError(""); setNotice("")
    try {
      await apiRequest(`/api/v1/transcript-drafts/${encodeURIComponent(promoteDraftId)}/promote`, {
        method: "POST",
        body: {
          title: promoteTitle,
          content: promoteContent,
          client_confirmed_by: confirmedBy,
          client_confirmed_at: confirmedAt,
          client_confirmation_method: confirmMethod,
        },
      })
      setNotice("已晋升为访谈纪要（正式库）。草稿正文随晋升抹除。")
      setPromoteDraftId(null); setExpandedDraftId(null); setDraftDetail(null)
      await reload()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setSaving(false)
    }
  }

  const toggleMinutesDetail = async (row: MinutesRowDto) => {
    if (expandedMinutesId === row.id) {
      setExpandedMinutesId(null); setMinutesDetail(null)
      return
    }
    setExpandedMinutesId(row.id); setMinutesDetail(null)
    try {
      const detail = await apiRequest<MinutesDetailDto>(
        `/api/v1/interview-minutes/${encodeURIComponent(row.id)}`,
        { method: "GET" },
      )
      setMinutesDetail(detail)
    } catch (caught) {
      setError(errorMessage(caught))
      setExpandedMinutesId(null)
    }
  }

  if (loading) return <p className="empty-copy" role="status">正在加载转写草稿…</p>

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>转写草稿区</h2>
            <p>只收文本，录音原件永不进平台（SOP :109/:111）；T+7 未晋升自动清理；晋升须客户确认三要素。</p>
          </div>
          <button className="secondary-button compact" onClick={() => setFormOpen((open) => !open)}>
            {formOpen ? "收起录入" : "新增转写草稿"}
          </button>
        </div>
        {notice ? <p className="notice" role="status">{notice}</p> : null}
        {error ? <p className="form-error banner" role="alert">{error}</p> : null}
        {formOpen ? (
          <form className="form-grid" onSubmit={(event) => { event.preventDefault(); void createDraft() }}>
            <label htmlFor="transcript-draft-title">标题（可选）</label>
            <input id="transcript-draft-title" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} />
            <label htmlFor="transcript-draft-content">转写文本</label>
            <textarea id="transcript-draft-content" rows={8} value={content} onChange={(event) => setContent(event.target.value)} required />
            <label htmlFor="transcript-draft-import">从本地文件导入（只读文本，原件不上传）</label>
            <input id="transcript-draft-import" type="file" accept=".txt,.md,.vtt,.srt" onChange={(event) => { void importFile(event.target.files?.[0]) }} />
            <label htmlFor="transcript-draft-source">来源</label>
            <select id="transcript-draft-source" value={sourceKind} onChange={(event) => setSourceKind(event.target.value === "asr" ? "asr" : "manual")}>
              <option value="manual">人工手录</option>
              <option value="asr">本地 ASR</option>
            </select>
            {sourceKind === "asr" ? (
              <>
                <label htmlFor="transcript-draft-engine">引擎标注</label>
                <input id="transcript-draft-engine" value={engine} onChange={(event) => setEngine(event.target.value)} placeholder="如 faster-whisper:base" required />
              </>
            ) : null}
            <div>
              <button className="primary-button" type="submit" disabled={saving || !content.trim()}>
                {saving ? "正在保存…" : "保存草稿"}
              </button>
            </div>
          </form>
        ) : null}
        {drafts.length ? (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">标题</th>
                <th scope="col">状态</th>
                <th scope="col">来源</th>
                <th scope="col">创建时间</th>
                <th scope="col">清理期限</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {drafts.map((draft) => (
                <tr key={draft.id}>
                  <td>{draft.title ?? <code>{draft.id.slice(0, 8)}</code>}</td>
                  <td>{statusLabel(DRAFT_STATUS_LABEL, draft.status)}</td>
                  <td>{statusLabel(SOURCE_KIND_LABEL, draft.source_kind)}{draft.engine ? <small> · {draft.engine}</small> : null}</td>
                  <td>{formatDateTime(draft.created_at)}</td>
                  <td>{formatDateTime(draft.expires_at)}</td>
                  <td>
                    <button className="secondary-button" disabled={detailLoading && expandedDraftId === draft.id} onClick={() => { void toggleDraftDetail(draft) }}>
                      {expandedDraftId === draft.id ? "收起" : "详情"}
                    </button>
                    {draft.status === "draft" ? (
                      <>
                        <button className="secondary-button" onClick={() => { void discardDraft(draft.id) }}>弃置</button>
                        {canManage ? (
                          <button className="secondary-button" disabled={!draftDetail || expandedDraftId !== draft.id} onClick={() => openPromote(draft, draftDetail)}>
                            晋升
                          </button>
                        ) : null}
                      </>
                    ) : null}
                    {draft.status === "promoted" && draft.promoted_ref ? (
                      <small title={draft.promoted_ref}>已入正式库</small>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="empty-state">暂无转写草稿。访谈录音先在本地转写为文本（建议 faster-whisper base 档，见横评报告），再在此创建草稿。</p>
        )}
        {expandedDraftId && draftDetail ? (
          <div className="detail-block">
            <h3>草稿详情</h3>
            {draftDetail.content ? <pre className="draft-content">{draftDetail.content}</pre> : <p className="empty-state">该行已终态，正文不可回放（T+7 语义）。</p>}
            {draftDetail.redaction_entries && draftDetail.redaction_entries.length ? (
              <fieldset>
                <legend>企业名替换复核清单</legend>
                <ul className="redaction-list">
                  {draftDetail.redaction_entries.map((entry, index) => {
                    const label = entry.suspect_count !== undefined
                      ? "疑似企业名（未收录词典）"
                      : typeof entry.name === "string" && entry.name
                        ? entry.name
                        : entry.name_hash
                          ? `${entry.name_hash.slice(0, 8)}…`
                          : "未知条目"
                    const count = entry.suspect_count ?? entry.occurrences ?? 0
                    const badge = entry.suspect_count !== undefined
                      ? <span className="badge">疑似聚合</span>
                      : entry.matched_dict
                        ? <span className="badge">词典命中</span>
                        : <span className="badge">疑似</span>
                    return (
                      <li key={entry.name_hash || `entry-${index}`}>
                        <strong>{label}</strong> × {count}
                        {badge}
                      </li>
                    )
                  })}
                </ul>
              </fieldset>
            ) : null}
            <p><small>指纹 <code>{shortSha(draftDetail.content_sha256)}</code></small></p>
            {promoteDraftId === draftDetail.id && canManage ? (
              <form className="form-grid" onSubmit={(event) => { event.preventDefault(); void promoteDraft() }}>
                <h4>晋升为访谈纪要（正式库）</h4>
                <label htmlFor="promote-title">纪要标题</label>
                <input id="promote-title" value={promoteTitle} onChange={(event) => setPromoteTitle(event.target.value)} required maxLength={200} />
                <label htmlFor="promote-content">整理后纪要</label>
                <textarea id="promote-content" rows={8} value={promoteContent} onChange={(event) => setPromoteContent(event.target.value)} required />
                <label htmlFor="promote-confirmed-by">客户确认人（客户侧角色/称呼，入库前将代号化）</label>
                <input id="promote-confirmed-by" value={confirmedBy} onChange={(event) => setConfirmedBy(event.target.value)} required maxLength={160} />
                <label htmlFor="promote-confirmed-at">客户确认时间</label>
                <input id="promote-confirmed-at" type="datetime-local" value={confirmedAt.slice(0, 16)} onChange={(event) => setConfirmedAt(new Date(event.target.value).toISOString())} required />
                <label htmlFor="promote-method">确认方式</label>
                <select id="promote-method" value={confirmMethod} onChange={(event) => setConfirmMethod(event.target.value as "verbal" | "written" | "meeting")}>
                  <option value="verbal">口头确认</option>
                  <option value="written">书面确认</option>
                  <option value="meeting">会议确认</option>
                </select>
                <div>
                  <button className="primary-button" type="submit" disabled={saving}>{saving ? "正在晋升…" : "确认晋升"}</button>
                </div>
              </form>
            ) : null}
          </div>
        ) : null}
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>访谈纪要（正式库）</h2>
            <p>人工整理并经客户确认后的正式记录；与草稿区物理隔离。</p>
          </div>
        </div>
        {minutes.length ? (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">标题</th>
                <th scope="col">确认人</th>
                <th scope="col">方式</th>
                <th scope="col">确认时间</th>
                <th scope="col">代号化命中</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {minutes.map((row) => (
                <tr key={row.id}>
                  <td>{row.title}</td>
                  <td>{row.client_confirmed_by}</td>
                  <td>{statusLabel(CONFIRM_METHOD_LABEL, row.client_confirmation_method)}</td>
                  <td>{formatDateTime(row.client_confirmed_at)}</td>
                  <td>{row.redaction_hits}</td>
                  <td>
                    <button className="secondary-button" onClick={() => { void toggleMinutesDetail(row) }}>
                      {expandedMinutesId === row.id ? "收起" : "详情"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="empty-state">暂无访谈纪要。草稿整理并经客户确认后在此晋升生成。</p>
        )}
        {expandedMinutesId && minutesDetail ? (
          <div className="detail-block">
            <h3>{minutesDetail.title}</h3>
            <pre className="draft-content">{minutesDetail.content}</pre>
            <p><small>指纹 <code>{shortSha(minutesDetail.content_sha256)}</code></small></p>
          </div>
        ) : null}
      </section>
    </div>
  )
}
