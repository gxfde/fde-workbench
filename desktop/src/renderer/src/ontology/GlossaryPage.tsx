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
  created_by_user_id: string | null
  created_at: string | null
}

// 候选生成来源（discovery 抽取；仅 review_required 可生成——服务端闸
// extraction_not_ready 409 的前端预筛）。字段投影＝serialize_extraction 子集。
interface ExtractionDto {
  id: string
  source_type: string
  status: string
  completed_at: string | null
}

// POST /candidates/generate 响应（键闭集＝generate_discovery_candidates 返回）
interface SkippedEntry {
  term: string
  reason: string
}

interface CrossProjectConflict {
  term: string
  project_ids: string[]
}

interface CandidateGenerateResult {
  change_set: ChangeSetDto
  created: boolean
  skipped: SkippedEntry[]
  cross_project_conflicts: CrossProjectConflict[]
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

// 术语类型值域唯一权威＝服务端 `ontology/models.py::TERM_TYPES`
const TERM_TYPES = ["entity", "attribute", "metric", "alias_target", "generic"] as const
const TERM_TYPE_LABEL: Record<string, string> = {
  entity: "实体",
  attribute: "属性",
  metric: "度量",
  alias_target: "别名指向",
  generic: "通用",
}

const RELATION_KIND_LABEL: Record<string, string> = {
  subject_type: "对象类型",
  link_type: "关系类型",
}

// 与服务端 `ontology/service._normalize_code` 同尺：小写字母开头，仅小写字母/
// 数字/下划线，≤60 字符（RELATION_TYPE_CODE_MAX_LENGTH）。
const RELATION_CODE_PATTERN = /^[a-z][a-z0-9_]*$/

// 手工变更集条目草稿（表单形态；提交前按动作折算成闭集键载荷）
interface DraftItem {
  action: "create_term" | "update_term" | "merge_terms"
  term: string
  definition: string
  term_type: string
  new_term: string
  source_term: string
  target_term: string
}

const EMPTY_DRAFT_ITEM: DraftItem = {
  action: "create_term",
  term: "",
  definition: "",
  term_type: "entity",
  new_term: "",
  source_term: "",
  target_term: "",
}

const EMPTY_RELATION_DRAFT = {
  kind: "subject_type",
  code: "",
  label: "",
  description: "",
  scope: "project",
  sources: "",
  targets: "",
}

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
  const { apiRequest, user } = useAuth()
  const base = `/api/v1/projects/${encodeURIComponent(projectId)}/ontology`
  const discoveryBase = `/api/v1/projects/${encodeURIComponent(projectId)}/discovery`
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
  // —— 桌面第三批 ops3：canManage 写面（候选生成 / 手工变更集 / 关系类型新停）——
  const isAdmin = user?.role === "admin"
  // ① 候选生成（懒加载：展开面板才拉抽取清单，不进首屏）
  const [candOpen, setCandOpen] = useState(false)
  const [extractions, setExtractions] = useState<ExtractionDto[] | null>(null)
  const [candError, setCandError] = useState("")
  const [candBusyId, setCandBusyId] = useState<string | null>(null)
  const [candResult, setCandResult] = useState<CandidateGenerateResult | null>(null)
  // ② 手工提变更集（body 闭集 {title, description?, proposed_json}——captured_from 是 AI 通道专用）
  const [csFormOpen, setCsFormOpen] = useState(false)
  const [csTitle, setCsTitle] = useState("")
  const [csDescription, setCsDescription] = useState("")
  const [csItems, setCsItems] = useState<DraftItem[]>([{ ...EMPTY_DRAFT_ITEM }])
  const [csNotice, setCsNotice] = useState("")
  // ③ 关系类型登记与停用
  const [rtFormOpen, setRtFormOpen] = useState(false)
  const [rtDraft, setRtDraft] = useState({ ...EMPTY_RELATION_DRAFT })
  const [rtNotice, setRtNotice] = useState("")
  const [rtConfirmId, setRtConfirmId] = useState<string | null>(null)

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

  // 禁自审：in_review 行若由当前账号创建，确认/否决必须由另一管理员执行
  // （服务端强制 ≠ 提交人——前端禁点只省一次注定 403 的往返）。
  function isSelfSubmitted(changeSet: ChangeSetDto): boolean {
    return (
      changeSet.status === "in_review" &&
      changeSet.created_by_user_id != null &&
      changeSet.created_by_user_id === user?.id
    )
  }

  // —— ① 候选生成：展开才拉抽取清单（懒加载，不进首屏、不碰只读面）——
  async function openCandidates(): Promise<void> {
    if (candOpen) {
      setCandOpen(false)
      return
    }
    setCandOpen(true)
    setCandError("")
    if (extractions !== null) return
    try {
      const data = await apiRequest<{ items: ExtractionDto[] }>(
        `${discoveryBase}/extractions?limit=50`,
        { method: "GET" },
      )
      setExtractions(
        Array.isArray(data.items)
          ? data.items.filter((row) => row.status === "review_required")
          : [],
      )
    } catch (caught) {
      setCandError(actionMessage(caught))
    }
  }

  async function generateCandidates(extraction: ExtractionDto): Promise<void> {
    setActionError("")
    setCandError("")
    setCandResult(null)
    setCandBusyId(extraction.id)
    try {
      // 全字面量路径（不经 base 拼接）：打包产物特征串核验需要连续的
      // "ontology/candidates/generate" 字节序列（r48 asar 四特征串闸）。
      const data = await apiRequest<CandidateGenerateResult>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/ontology/candidates/generate`,
        { method: "POST", body: { extraction_id: extraction.id } },
      )
      setCandResult(data)
      await load()
    } catch (caught) {
      setCandError(actionMessage(caught))
    } finally {
      setCandBusyId(null)
    }
  }

  // —— ② 手工变更集：按动作折算闭集键载荷（值非法返回文案，不发请求）——
  function buildProposedItem(item: DraftItem): Record<string, unknown> | string {
    const term = item.term.trim()
    const definition = item.definition.trim()
    if (item.action === "create_term") {
      if (!term || !definition) return "create_term 条目需要术语名与定义。"
      return { action: "create_term", term, definition, term_type: item.term_type }
    }
    if (item.action === "update_term") {
      if (!term || !definition) return "update_term 条目需要术语名与定义。"
      const payload: Record<string, unknown> = { action: "update_term", term, definition }
      if (item.term_type) payload.term_type = item.term_type
      if (item.new_term.trim()) payload.new_term = item.new_term.trim()
      return payload
    }
    const source = item.source_term.trim()
    const target = item.target_term.trim()
    if (!source || !target) return "merge_terms 条目需要来源与目标术语名。"
    if (source === target) return "不能把术语合并到它自己（同名合并被禁止）。"
    return { action: "merge_terms", source_term: source, target_term: target }
  }

  async function submitChangeSet(): Promise<void> {
    setActionError("")
    setCsNotice("")
    const title = csTitle.trim()
    if (!title) {
      setActionError("变更集标题必填。")
      return
    }
    const proposed: Array<Record<string, unknown>> = []
    for (const item of csItems) {
      const built = buildProposedItem(item)
      if (typeof built === "string") {
        setActionError(built)
        return
      }
      proposed.push(built)
    }
    // body 闭集 {title, description?, proposed_json}：description 留空不传；
    // 绝不传 captured_from（AI 通道专用，服务端对人工路径显式 400）。
    const body: Record<string, unknown> = { title, proposed_json: proposed }
    const description = csDescription.trim()
    if (description) body.description = description
    setBusy(true)
    try {
      await apiRequest<{ change_set: ChangeSetDto }>(`${base}/change-sets`, {
        method: "POST",
        body,
      })
      setCsTitle("")
      setCsDescription("")
      setCsItems([{ ...EMPTY_DRAFT_ITEM }])
      setCsNotice("变更集已创建（草稿）：提交评审后由另一管理员确认物化。")
      await load()
    } catch (caught) {
      setActionError(actionMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  // —— ③ 关系类型：登记（link_type 必须声明端点约束——服务端硬闸）与停用 ——
  async function submitRelationType(): Promise<void> {
    setActionError("")
    setRtNotice("")
    const code = rtDraft.code.trim()
    if (!RELATION_CODE_PATTERN.test(code) || code.length > 60) {
      setActionError("code 需小写字母开头，仅含小写字母/数字/下划线，且 ≤60 字符。")
      return
    }
    const scope = rtDraft.scope === "global" ? "global" : "project"
    if (scope === "global" && !isAdmin) {
      setActionError("只有管理员可以登记全局类型。")
      return
    }
    // body 闭集 {kind, code, label?, description?, scope}；link_type 另附端点
    // 约束两键（服务端必填：缺 sources/targets 即 400 invalid_request）。
    const body: Record<string, unknown> = { kind: rtDraft.kind, code, scope }
    const label = rtDraft.label.trim()
    if (label) body.label = label
    const description = rtDraft.description.trim()
    if (description) body.description = description
    if (rtDraft.kind === "link_type") {
      const parseList = (raw: string) =>
        raw
          .split(/[,，;\s]+/)
          .map((part) => part.trim())
          .filter(Boolean)
      const sources = parseList(rtDraft.sources)
      const targets = parseList(rtDraft.targets)
      if (!sources.length || !targets.length) {
        setActionError("关系类型必须声明源/目标对象类型约束（先登记对象类型再登记引用它的关系类型）。")
        return
      }
      body.allowed_source_types = sources
      body.allowed_target_types = targets
    }
    setBusy(true)
    try {
      await apiRequest(`${base}/relation-types`, { method: "POST", body })
      setRtDraft({ ...EMPTY_RELATION_DRAFT })
      setRtFormOpen(false)
      setRtNotice(scope === "global" ? "全局类型已登记。" : "项目类型已登记。")
      await load()
    } catch (caught) {
      setActionError(actionMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  // 停用资格：非 retired 行才可停；全局行仅 admin（服务端同尺 403）
  function retireAllowed(rt: RelationTypeDto): boolean {
    return rt.status !== "retired" && (rt.scope !== "global" || isAdmin)
  }

  async function retireRelationType(rt: RelationTypeDto): Promise<void> {
    setActionError("")
    setRtNotice("")
    setBusy(true)
    try {
      await apiRequest(`${base}/relation-types/${encodeURIComponent(rt.id)}/retire`, {
        method: "POST",
      })
      setRtConfirmId(null)
      setRtNotice(`类型「${rt.label || rt.code}」已停用：禁新边，存量边只读。`)
      await load()
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

      {canManage ? (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>候选生成</h2>
              <p>从已完成审阅（review_required）的抽取事实生成本体候选：只创建变更集草稿，采纳仍走提交 → 确认人工管线。</p>
            </div>
            <button className="secondary-button" onClick={() => void openCandidates()}>
              {candOpen ? "收起" : "展开候选来源"}
            </button>
          </div>
          {candOpen ? (
            candError ? (
              <p className="empty-copy" role="alert">{candError}</p>
            ) : extractions === null ? (
              <p className="empty-copy" role="status">正在加载抽取清单…</p>
            ) : (
              <div className="page-stack">
                {candResult ? (
                  <article className="extension-item">
                    <div>
                      <strong>{candResult.created ? "已创建候选变更集" : "复用既有活跃候选变更集"}</strong>
                      <span className="extension-scope">
                        {statusLabel(CHANGE_SET_STATUS_LABEL, candResult.change_set.status)}
                      </span>
                    </div>
                    <p>{candResult.change_set.title}</p>
                    {candResult.skipped.length ? (
                      <p>
                        <small>
                          跳过 {candResult.skipped.length} 项：
                          {candResult.skipped.map((row) => `${row.term}（${row.reason}）`).join("；")}
                        </small>
                      </p>
                    ) : null}
                    {candResult.cross_project_conflicts.length ? (
                      <p>
                        <small>
                          跨项目同名告警（只读提示，不阻断）：
                          {candResult.cross_project_conflicts
                            .map((row) => `${row.term} → ${row.project_ids.join("、")}`)
                            .join("；")}
                        </small>
                      </p>
                    ) : null}
                  </article>
                ) : null}
                {extractions.length ? (
                  extractions.map((extraction) => (
                    <div key={extraction.id} className="plugin-actions">
                      <code>{extraction.id}</code>
                      <span> {extraction.source_type}</span>
                      <button
                        className="secondary-button"
                        disabled={candBusyId !== null}
                        onClick={() => void generateCandidates(extraction)}
                      >
                        {candBusyId === extraction.id ? "生成中…" : "生成候选"}
                      </button>
                    </div>
                  ))
                ) : (
                  <p className="empty-copy">没有待处理的抽取（仅 review_required 状态可生成候选）。</p>
                )}
              </div>
            )
          ) : null}
        </section>
      ) : null}

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>关系类型</h2>
            <p>
              {canManage
                ? "登记项目类型或全局类型（全局行需系统运维员）；停用后禁新边、存量边只读。"
                : "登记与停用走管理通道（全局行需系统运维员），此处只读呈现。"}
            </p>
          </div>
          {canManage ? (
            <button className="secondary-button" onClick={() => { setRtFormOpen(!rtFormOpen); setActionError(""); setRtNotice("") }}>
              {rtFormOpen ? "收起登记表单" : "登记类型"}
            </button>
          ) : null}
        </div>
        {rtNotice ? <p className="empty-copy" role="status">{rtNotice}</p> : null}
        {canManage && rtFormOpen ? (
          <form
            className="page-stack"
            onSubmit={(event) => {
              event.preventDefault()
              void submitRelationType()
            }}
          >
            <div className="plugin-actions">
              <label className="field">
                <span>种类</span>
                <select
                  aria-label="类型种类"
                  value={rtDraft.kind}
                  onChange={(event) => setRtDraft({ ...rtDraft, kind: event.target.value })}
                >
                  <option value="subject_type">对象类型</option>
                  <option value="link_type">关系类型</option>
                </select>
              </label>
              <label className="field">
                <span>code</span>
                <input
                  aria-label="类型 code"
                  placeholder="如 delivery_role"
                  value={rtDraft.code}
                  onChange={(event) => setRtDraft({ ...rtDraft, code: event.target.value })}
                />
              </label>
              <label className="field">
                <span>名称（可选）</span>
                <input
                  aria-label="类型名称"
                  value={rtDraft.label}
                  onChange={(event) => setRtDraft({ ...rtDraft, label: event.target.value })}
                />
              </label>
              <label className="field">
                <span>范围</span>
                <select
                  aria-label="类型范围"
                  value={rtDraft.scope}
                  onChange={(event) => setRtDraft({ ...rtDraft, scope: event.target.value })}
                >
                  <option value="project">项目内</option>
                  {isAdmin ? <option value="global">全局（仅管理员）</option> : null}
                </select>
              </label>
            </div>
            <label className="field">
              <span>说明（可选）</span>
              <input
                aria-label="类型说明"
                value={rtDraft.description}
                onChange={(event) => setRtDraft({ ...rtDraft, description: event.target.value })}
              />
            </label>
            {rtDraft.kind === "link_type" ? (
              <div className="plugin-actions">
                <label className="field">
                  <span>源对象类型（逗号分隔）</span>
                  <input
                    aria-label="源对象类型"
                    placeholder="如 project, department"
                    value={rtDraft.sources}
                    onChange={(event) => setRtDraft({ ...rtDraft, sources: event.target.value })}
                  />
                </label>
                <label className="field">
                  <span>目标对象类型（逗号分隔）</span>
                  <input
                    aria-label="目标对象类型"
                    placeholder="如 role, process"
                    value={rtDraft.targets}
                    onChange={(event) => setRtDraft({ ...rtDraft, targets: event.target.value })}
                  />
                </label>
              </div>
            ) : null}
            <div className="plugin-actions">
              <button className="primary-button" type="submit" disabled={busy}>
                确认登记
              </button>
            </div>
          </form>
        ) : null}
        {relationTypes.length ? (
          <div className="extension-card-grid">
            {relationTypes.map((relationType) => (
              <article key={relationType.id} className="extension-item">
                <div>
                  <span className={`extension-scope ${relationType.scope === "global" ? "public" : ""}`}>
                    {relationType.scope === "global" ? "全局" : "项目"}
                  </span>
                  <strong>{relationType.label}</strong>
                  <small> <code>{relationType.code}</code> · {RELATION_KIND_LABEL[relationType.kind] ?? relationType.kind}</small>
                </div>
                <p>{relationType.description || "暂无说明"}</p>
                <small>
                  源 {relationType.allowed_source_types.join("/") || "—"} → 目标 {relationType.allowed_target_types.join("/") || "—"}
                  {relationType.status !== "active" ? ` · ${relationType.status}` : ""}
                </small>
                {canManage && retireAllowed(relationType) ? (
                  <div className="plugin-actions">
                    {rtConfirmId === relationType.id ? (
                      <>
                        <button
                          className="primary-button"
                          disabled={busy}
                          onClick={() => void retireRelationType(relationType)}
                        >
                          确认停用
                        </button>
                        <button className="secondary-button" disabled={busy} onClick={() => setRtConfirmId(null)}>
                          取消
                        </button>
                      </>
                    ) : (
                      <button
                        className="secondary-button"
                        disabled={busy}
                        onClick={() => { setRtConfirmId(relationType.id); setActionError(""); setRtNotice("") }}
                      >
                        停用
                      </button>
                    )}
                  </div>
                ) : null}
                {canManage && relationType.scope === "global" && !isAdmin && relationType.status !== "retired" ? (
                  <small>全局类型仅系统运维员可停用。</small>
                ) : null}
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
          <div className="plugin-actions">
            {canManage ? (
              <button className="secondary-button" onClick={() => { setCsFormOpen(!csFormOpen); setActionError(""); setCsNotice("") }}>
                {csFormOpen ? "收起起草表单" : "手工提变更集"}
              </button>
            ) : null}
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
        </div>
        {actionError ? <p role="alert" className="empty-copy">{actionError}</p> : null}
        {csNotice ? <p className="empty-copy" role="status">{csNotice}</p> : null}
        {canManage && csFormOpen ? (
          <form
            className="page-stack"
            onSubmit={(event) => {
              event.preventDefault()
              void submitChangeSet()
            }}
          >
            <div className="plugin-actions">
              <label className="field">
                <span>标题</span>
                <input
                  aria-label="变更集标题"
                  placeholder="如 术语口径季度修订"
                  value={csTitle}
                  onChange={(event) => setCsTitle(event.target.value)}
                />
              </label>
              <label className="field">
                <span>说明（可选）</span>
                <input
                  aria-label="变更集说明"
                  value={csDescription}
                  onChange={(event) => setCsDescription(event.target.value)}
                />
              </label>
            </div>
            {csItems.map((item, index) => (
              <div key={index} className="page-stack">
                <div className="plugin-actions">
                  <label className="field">
                    <span>动作 {index + 1}</span>
                    <select
                      aria-label={`条目 ${index + 1} 动作`}
                      value={item.action}
                      onChange={(event) =>
                        setCsItems((current) =>
                          current.map((row, at) =>
                            at === index ? { ...row, action: event.target.value as DraftItem["action"] } : row,
                          ),
                        )
                      }
                    >
                      <option value="create_term">新建术语</option>
                      <option value="update_term">修订术语</option>
                      <option value="merge_terms">合并术语</option>
                    </select>
                  </label>
                  {item.action === "merge_terms" ? (
                    <>
                      <label className="field">
                        <span>来源术语</span>
                        <input
                          aria-label={`条目 ${index + 1} 来源术语`}
                          value={item.source_term}
                          onChange={(event) =>
                            setCsItems((current) =>
                              current.map((row, at) => (at === index ? { ...row, source_term: event.target.value } : row)),
                            )
                          }
                        />
                      </label>
                      <label className="field">
                        <span>目标术语</span>
                        <input
                          aria-label={`条目 ${index + 1} 目标术语`}
                          value={item.target_term}
                          onChange={(event) =>
                            setCsItems((current) =>
                              current.map((row, at) => (at === index ? { ...row, target_term: event.target.value } : row)),
                            )
                          }
                        />
                      </label>
                    </>
                  ) : (
                    <>
                      <label className="field">
                        <span>术语名</span>
                        <input
                          aria-label={`条目 ${index + 1} 术语名`}
                          value={item.term}
                          onChange={(event) =>
                            setCsItems((current) =>
                              current.map((row, at) => (at === index ? { ...row, term: event.target.value } : row)),
                            )
                          }
                        />
                      </label>
                      <label className="field">
                        <span>定义</span>
                        <input
                          aria-label={`条目 ${index + 1} 定义`}
                          value={item.definition}
                          onChange={(event) =>
                            setCsItems((current) =>
                              current.map((row, at) => (at === index ? { ...row, definition: event.target.value } : row)),
                            )
                          }
                        />
                      </label>
                      <label className="field">
                        <span>类型</span>
                        <select
                          aria-label={`条目 ${index + 1} 术语类型`}
                          value={item.term_type}
                          onChange={(event) =>
                            setCsItems((current) =>
                              current.map((row, at) => (at === index ? { ...row, term_type: event.target.value } : row)),
                            )
                          }
                        >
                          {TERM_TYPES.map((termType) => (
                            <option key={termType} value={termType}>{TERM_TYPE_LABEL[termType]}</option>
                          ))}
                        </select>
                      </label>
                      {item.action === "update_term" ? (
                        <label className="field">
                          <span>新名（可选，改名即行级取代）</span>
                          <input
                            aria-label={`条目 ${index + 1} 新名`}
                            value={item.new_term}
                            onChange={(event) =>
                              setCsItems((current) =>
                                current.map((row, at) => (at === index ? { ...row, new_term: event.target.value } : row)),
                              )
                            }
                          />
                        </label>
                      ) : null}
                    </>
                  )}
                  {csItems.length > 1 ? (
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() => setCsItems((current) => current.filter((_, at) => at !== index))}
                    >
                      移除条目
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
            <div className="plugin-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={busy}
                onClick={() => setCsItems((current) => [...current, { ...EMPTY_DRAFT_ITEM, action: current.at(-1)?.action ?? "create_term" }])}
              >
                添加条目
              </button>
              <button className="primary-button" type="submit" disabled={busy}>
                创建变更集（草稿）
              </button>
            </div>
          </form>
        ) : null}
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
                  {canManage && changeSet.status === "in_review" && !isSelfSubmitted(changeSet) ? (
                    <button className="primary-button" disabled={busy} onClick={() => void actChangeSet(changeSet, "confirm")}>
                      确认物化
                    </button>
                  ) : null}
                </div>
                {canManage && isSelfSubmitted(changeSet) ? (
                  <p className="empty-copy">此变更集由当前账号提交——确认或否决须由另一管理员审阅。</p>
                ) : null}
                {canManage && changeSet.status === "in_review" && !isSelfSubmitted(changeSet) ? (
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
