import { Fragment, useCallback, useEffect, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { Loading } from "../components/ui"

// V3 T-W6 本体术语页（ontology-glossary-v1 §4 消费面）：术语只读清单 + 关系类型
// 只读清单 + 变更集评审（propose 之外的 submit/confirm/reject 按钮）。写路径全部
// 走既有服务层闸（can_manage；confirm/reject 服务端强制 ≠ 提交人）——403/409 原样呈现。
// 影响分析（T-I1 名字域纽带只读消费面，GET terms/{id}/impact）：行内展开三面清单
// （subjects/links/forms + counts）；对并入行查询 = 查其存活概念的影响面（resolved）。
// 改名流程见 docs/architecture/术语改名SOP-v1.md。

interface TermDto {
  id: string
  term: string
  term_type: string
  definition: string | null
  status: string
  version: number
  canonical_term_id: string | null
  updated_at: string | null
}

interface RelationTypeDto {
  id: string
  scope: string
  kind: string
  code: string
  label: string
  description: string | null
  allowed_source_types: string[]
  allowed_target_types: string[]
  status: string
}

interface ChangeSetDto {
  id: string
  title: string
  description: string | null
  proposed_json: Array<Record<string, unknown>>
  diff_summary: string | null
  status: string
  base_snapshot_sha256: string | null
  captured_from: string | null
  rejected_reason: string | null
  created_at: string | null
}

interface ChangeSetListDto {
  items: ChangeSetDto[]
}

// 影响分析（GET terms/{id}/impact）响应键集＝服务端 ontology/service.impact_of_term
interface TermImpactDto {
  term: TermDto
  resolved: { canonical_term_id: string; lineage_term_ids: string[] }
  subjects: Array<{
    id: string
    subject_key: string
    name: string
    subject_type: string
    status: string
    merged_into_subject_id: string | null
    matched_via: string
    matched_term_id: string
  }>
  links: Array<{
    id: string
    link_type: string
    source_subject_id: string
    source_subject_name: string | null
    target_subject_id: string
    target_subject_name: string | null
  }>
  forms: Array<{
    id: string
    form_key: string
    name: string
    subject_id: string
    subject_name: string | null
    current_revision_status: string | null
  }>
  counts: { subjects: number; links: number; forms: number }
}

// 术语状态值域唯一权威＝服务端 `ontology/models.py::TERM_STATUSES`
// （draft / confirmed / superseded / merged）。CR-040：此前此处写的是
// candidate / retired（服务端无此二值）且缺 draft / superseded → 状态列
// 直接回显英文原值，中文标签永不生效。
const TERM_STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  confirmed: "已确认",
  superseded: "已取代",
  merged: "已合并",
}

const CHANGE_SET_STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  in_review: "评审中",
  confirmed: "已确认",
  rejected: "已否决",
  superseded: "已取代",
}

const CHANGE_SET_STATUSES = ["draft", "in_review", "confirmed", "rejected", "superseded"] as const

function statusLabel(map: Record<string, string>, value: string): string {
  return map[value] ?? value
}

function actionMessage(caught: unknown): string {
  if (caught instanceof ApiClientError) return caught.message
  if (caught instanceof Error) return caught.message
  return "操作失败，请重试。"
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function describeAction(item: Record<string, unknown>): string {
  const action = typeof item.action === "string" ? item.action : "unknown"
  const term = typeof item.term === "string" ? item.term : ""
  const kind = typeof item.kind === "string" ? item.kind : ""
  const parts = [action]
  if (term) parts.push(term)
  if (kind) parts.push(kind)
  return parts.join(" · ")
}

interface GlossaryPageProps {
  projectId: string
  canManage: boolean
}

export function GlossaryPage({ projectId, canManage }: GlossaryPageProps) {
  const { apiRequest } = useAuth()
  const base = `/api/v1/projects/${encodeURIComponent(projectId)}/ontology`
  const [terms, setTerms] = useState<TermDto[]>([])
  const [termQuery, setTermQuery] = useState("")
  const [relationTypes, setRelationTypes] = useState<RelationTypeDto[]>([])
  const [changeSets, setChangeSets] = useState<ChangeSetDto[]>([])
  const [csFilter, setCsFilter] = useState<string>("")
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<ChangeSetDto | null>(null)
  const [rejectReason, setRejectReason] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [actionError, setActionError] = useState("")
  const [busy, setBusy] = useState(false)
  // CR-035：搜索每键一触发 → 请求并发返回乱序（后发先至的旧响应会覆盖新结果）。
  // 序列号守卫：只有最新一次请求的结果可以落表；组件卸载同样作废在途请求。
  const sequence = useRef(0)
  // 首屏才整页 loading；后续搜索/筛选保留旧内容，避免每次按键闪空。
  const loadedOnce = useRef(false)
  // 影响分析（T-I1 消费接线）：行内按需展开；连点不同行同样按序列号只认最新请求。
  const [impactTermId, setImpactTermId] = useState<string | null>(null)
  const [impact, setImpact] = useState<TermImpactDto | null>(null)
  const [impactLoading, setImpactLoading] = useState(false)
  const [impactError, setImpactError] = useState("")
  const impactSequence = useRef(0)

  const load = useCallback(async (): Promise<number> => {
    const requestSequence = ++sequence.current
    setError("")
    try {
      const query = termQuery.trim()
        ? `?q=${encodeURIComponent(termQuery.trim())}`
        : ""
      const [termData, typeData, csData] = await Promise.all([
        apiRequest<{ items: TermDto[] }>(`${base}/terms${query}`, { method: "GET" }),
        apiRequest<{ items: RelationTypeDto[] }>(`${base}/relation-types`, { method: "GET" }),
        apiRequest<ChangeSetListDto>(
          csFilter ? `${base}/change-sets?status=${encodeURIComponent(csFilter)}` : `${base}/change-sets`,
          { method: "GET" },
        ),
      ])
      if (requestSequence !== sequence.current) return requestSequence
      setTerms(termData.items)
      setRelationTypes(typeData.items)
      setChangeSets(csData.items)
    } catch (caught) {
      if (requestSequence !== sequence.current) return requestSequence
      setError(actionMessage(caught))
    }
    return requestSequence
  }, [apiRequest, base, termQuery, csFilter])

  useEffect(() => {
    let active = true
    if (!loadedOnce.current) setLoading(true)
    void load().then((requestSequence) => {
      if (active && requestSequence === sequence.current) {
        loadedOnce.current = true
        setLoading(false)
      }
    })
    return () => {
      active = false
      sequence.current += 1
    }
  }, [load])

  async function toggleImpact(term: TermDto): Promise<void> {
    if (impactTermId === term.id) {
      setImpactTermId(null)
      setImpact(null)
      setImpactError("")
      return
    }
    setActionError("")
    setImpactError("")
    setImpactTermId(term.id)
    setImpact(null)
    setImpactLoading(true)
    const requestSequence = ++impactSequence.current
    try {
      const data = await apiRequest<TermImpactDto>(
        `${base}/terms/${encodeURIComponent(term.id)}/impact`,
        { method: "GET" },
      )
      if (requestSequence !== impactSequence.current) return
      setImpact(data)
    } catch (caught) {
      if (requestSequence !== impactSequence.current) return
      // 失败不收行：错误留在点击处行内呈现（再点一次先收起、第三击才重取）
      setImpactError(actionMessage(caught))
    } finally {
      if (requestSequence === impactSequence.current) setImpactLoading(false)
    }
  }

  async function toggleDetail(changeSet: ChangeSetDto): Promise<void> {
    if (expandedId === changeSet.id) {
      setExpandedId(null)
      setDetail(null)
      return
    }
    setActionError("")
    setExpandedId(changeSet.id)
    try {
      const data = await apiRequest<{ change_set: ChangeSetDto }>(
        `${base}/change-sets/${encodeURIComponent(changeSet.id)}`,
        { method: "GET" },
      )
      setDetail(data.change_set)
    } catch (caught) {
      setActionError(actionMessage(caught))
      setExpandedId(null)
    }
  }

  async function actChangeSet(
    changeSet: ChangeSetDto,
    action: "submit" | "confirm" | "reject",
  ): Promise<void> {
    setActionError("")
    setBusy(true)
    try {
      const body = action === "reject" ? { reason: rejectReason.trim() } : {}
      const data = await apiRequest<{ change_set: ChangeSetDto }>(
        `${base}/change-sets/${encodeURIComponent(changeSet.id)}/${action}`,
        { method: "POST", body },
      )
      setChangeSets((current) =>
        current.map((row) => (row.id === changeSet.id ? data.change_set : row)),
      )
      if (detail?.id === changeSet.id) setDetail(data.change_set)
      setRejectReason("")
    } catch (caught) {
      setActionError(actionMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <Loading label="正在加载术语表…" />
  if (error) return <p className="empty-copy" role="alert">{error}</p>

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>术语表</h2>
            <p>项目术语与别名（只读）；候选与修订一律走变更集评审，控制台不直接改术语。</p>
          </div>
          <form
            className="field"
            onSubmit={(event) => {
              event.preventDefault()
              void load()
            }}
          >
            <input
              aria-label="搜索术语"
              placeholder="按规范名或别名搜索"
              value={termQuery}
              onChange={(event) => setTermQuery(event.target.value)}
            />
          </form>
        </div>
        {terms.length ? (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">术语</th>
                <th scope="col">类型</th>
                <th scope="col">定义</th>
                <th scope="col">状态</th>
                <th scope="col">版本</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {terms.map((term) => (
                <Fragment key={term.id}>
                  <tr>
                    <td>
                      <strong>{term.term}</strong>
                      {term.canonical_term_id ? <small>（让位别名）</small> : null}
                    </td>
                    <td>{term.term_type}</td>
                    <td>{term.definition || "—"}</td>
                    <td>{statusLabel(TERM_STATUS_LABEL, term.status)}</td>
                    <td>v{term.version}</td>
                    <td>
                      <button
                        className="secondary-button"
                        onClick={() => void toggleImpact(term)}
                      >
                        影响分析
                      </button>
                    </td>
                  </tr>
                  {impactTermId === term.id ? (
                    <tr>
                      <td colSpan={6}>
                        {impactLoading ? (
                          <p className="empty-copy" role="status">正在加载影响分析…</p>
                        ) : impactError ? (
                          <p className="empty-copy" role="alert">{impactError}</p>
                        ) : impact && impact.term.id === term.id ? (
                          <div className="page-stack">
                            <p>
                              <strong>引用面：</strong>
                              调研对象 {impact.counts.subjects} · 关联边 {impact.counts.links} · 表单 {impact.counts.forms}
                              {impact.resolved.canonical_term_id !== impact.term.id ? (
                                <small>
                                  （并入行：已解析到存活概念 <code>{impact.resolved.canonical_term_id}</code>，血缘 {impact.resolved.lineage_term_ids.length} 行）
                                </small>
                              ) : null}
                            </p>
                            {impact.subjects.length ? (
                              <ul>
                                {impact.subjects.map((subject) => (
                                  <li key={subject.id}>
                                    <code>{subject.subject_key}</code> {subject.name} · {subject.subject_type} · {subject.status}
                                    · 命中经 {subject.matched_via === "term" ? "规范名" : "别名"}
                                  </li>
                                ))}
                              </ul>
                            ) : (
                              <p className="empty-copy">没有引用该术语的调研对象。</p>
                            )}
                            {impact.links.length ? (
                              <ul>
                                {impact.links.map((link) => (
                                  <li key={link.id}>
                                    <code>{link.link_type}</code>：
                                    {link.source_subject_name ?? link.source_subject_id} → {link.target_subject_name ?? link.target_subject_id}
                                  </li>
                                ))}
                              </ul>
                            ) : null}
                            {impact.forms.length ? (
                              <ul>
                                {impact.forms.map((form) => (
                                  <li key={form.id}>
                                    <code>{form.form_key}</code> {form.name}
                                    {form.current_revision_status ? ` · 修订 ${form.current_revision_status}` : ""}
                                  </li>
                                ))}
                              </ul>
                            ) : null}
                          </div>
                        ) : null}
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="empty-copy">{termQuery.trim() ? "没有匹配的术语。" : "还没有术语。"}</p>
        )}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>关系类型</h2>
            <p>登记与停用走管理通道（全局行需系统运维员），此处只读呈现。</p>
          </div>
        </div>
        {relationTypes.length ? (
          <div className="extension-card-grid">
            {relationTypes.map((relationType) => (
              <article key={relationType.id} className="extension-item">
                <div>
                  <span className={`extension-scope ${relationType.scope === "global" ? "public" : ""}`}>
                    {relationType.scope === "global" ? "全局" : "项目"}
                  </span>
                  <strong>{relationType.label}</strong>
                  <small> <code>{relationType.code}</code> · {relationType.kind}</small>
                </div>
                <p>{relationType.description || "暂无说明"}</p>
                <small>
                  源 {relationType.allowed_source_types.join("/") || "—"} → 目标 {relationType.allowed_target_types.join("/") || "—"}
                  {relationType.status !== "active" ? ` · ${relationType.status}` : ""}
                </small>
              </article>
            ))}
          </div>
        ) : (
          <p className="empty-copy">还没有关系类型。</p>
        )}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>变更集评审</h2>
            <p>AI 候选与人工提案的唯一落点：draft → in_review → confirmed/rejected；确认前不物化。</p>
          </div>
          <label className="field">
            <span>状态过滤</span>
            <select
              aria-label="按状态过滤变更集"
              value={csFilter}
              onChange={(event) => setCsFilter(event.target.value)}
            >
              <option value="">全部</option>
              {CHANGE_SET_STATUSES.map((status) => (
                <option key={status} value={status}>{statusLabel(CHANGE_SET_STATUS_LABEL, status)}</option>
              ))}
            </select>
          </label>
        </div>
        {actionError ? <p role="alert" className="empty-copy">{actionError}</p> : null}
        {changeSets.length ? (
          <div className="page-stack">
            {changeSets.map((changeSet) => (
              <article key={changeSet.id} className="extension-item">
                <div>
                  <span className={`extension-scope ${changeSet.status === "confirmed" ? "public" : ""}`}>
                    {statusLabel(CHANGE_SET_STATUS_LABEL, changeSet.status)}
                  </span>
                  <strong>{changeSet.title}</strong>
                  {changeSet.captured_from ? <small> · 来源 {changeSet.captured_from}</small> : null}
                </div>
                <p>{changeSet.diff_summary || changeSet.description || "暂无摘要"}</p>
                {changeSet.rejected_reason ? <p><small>否决理由：{changeSet.rejected_reason}</small></p> : null}
                <div className="plugin-actions">
                  <button
                    className="secondary-button"
                    disabled={busy}
                    onClick={() => void toggleDetail(changeSet)}
                  >
                    {expandedId === changeSet.id ? "收起" : "评审载荷"}
                  </button>
                  {canManage && changeSet.status === "draft" ? (
                    <button className="primary-button" disabled={busy} onClick={() => void actChangeSet(changeSet, "submit")}>
                      提交评审
                    </button>
                  ) : null}
                  {canManage && changeSet.status === "in_review" ? (
                    <button className="primary-button" disabled={busy} onClick={() => void actChangeSet(changeSet, "confirm")}>
                      确认物化
                    </button>
                  ) : null}
                </div>
                {canManage && changeSet.status === "in_review" ? (
                  <div className="plugin-actions">
                    <input
                      aria-label="否决理由"
                      placeholder="否决需说明理由（留痕）"
                      value={expandedId === changeSet.id ? rejectReason : ""}
                      onChange={(event) => setRejectReason(event.target.value)}
                    />
                    <button
                      className="secondary-button"
                      disabled={busy || !rejectReason.trim()}
                      onClick={() => void actChangeSet(changeSet, "reject")}
                    >
                      否决
                    </button>
                  </div>
                ) : null}
                {expandedId === changeSet.id ? (
                  detail && detail.id === changeSet.id ? (
                    <div>
                      <small>base 指纹：<code>{detail.base_snapshot_sha256 || "—"}</code></small>
                      <ul>
                        {detail.proposed_json.map((item, index) => (
                          <li key={index}>
                            {isRecord(item) ? describeAction(item) : String(item)}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : (
                    <p className="empty-copy">正在加载载荷…</p>
                  )
                ) : null}
              </article>
            ))}
          </div>
        ) : (
          <p className="empty-copy">没有变更集。</p>
        )}
      </section>
    </div>
  )
}
