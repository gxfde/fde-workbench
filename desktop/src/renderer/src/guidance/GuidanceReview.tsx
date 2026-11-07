import { useEffect, useMemo, useRef, useState } from "react"
import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import type { GuidanceAnalysisDto, GuidanceClassification, GuidanceItemDto, GuidanceRedactionReviewEntry } from "./types"
import { isRedactionReviewEntries } from "./types"
import {
  CLASSIFICATION_LABELS,
  GUIDANCE_LAYERS,
  LAYER_META,
  allowedClassifications,
  groupByLayer,
  newGuidanceItem,
} from "./classificationLayers"
import { isGuidanceAnalysis } from "./runtimeValidation"

const sections: Array<[keyof GuidanceAnalysisDto, string]> = [
  ["key_business_problems", "关键业务问题"], ["priority_departments", "优先部门"], ["priority_roles", "优先岗位"],
  ["priority_processes", "优先流程"], ["success_criteria", "成功标准"], ["out_of_scope", "本阶段不包含"],
  ["data_security_redlines", "数据与安全红线"], ["systems_and_deployment_constraints", "系统与部署约束"],
  ["assumptions", "假设"], ["open_questions", "待确认问题"], ["next_actions", "下一步行动"],
]

export function GuidanceReview({ projectId, initial, canManage, initialEditing = false, onClose, onSaved }: { projectId: string; initial: GuidanceAnalysisDto; canManage: boolean; initialEditing?: boolean; onClose(): void; onSaved(value: GuidanceAnalysisDto): void }) {
  const { apiRequest } = useAuth()
  const [draft, setDraft] = useState(initial)
  const [baseline, setBaseline] = useState(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const published = useRef<GuidanceAnalysisDto | null>(null)
  const [editing, setEditing] = useState(initialEditing && initial.status === "draft" && initial.analysis_state === "ready")
  // T-A2 复核闸桌面面（拍板 6①）：复核清单唯一投影=服务端 get_analysis
  // .redaction_review（#171 派生），前端不二次推导文本；「已复核」ack 随
  // confirm 请求显式 redaction_reviewed=true（路由只认字面 true）。
  const [reviewAcked, setReviewAcked] = useState(false)
  const [reviewBlocked, setReviewBlocked] = useState(false)
  useEffect(() => {
    // A locally published revision is echoed back by the parent. Do not turn
    // off editing immediately after the user explicitly requested that revision.
    if (initial === published.current) return
    setDraft(initial); setBaseline(initial); setEditing(initialEditing && initial.status === "draft" && initial.analysis_state === "ready")
    setReviewAcked(false); setReviewBlocked(false)
  }, [initial, initialEditing])
  const canEdit = canManage && draft.analysis_state === "ready"
  const reviewList: GuidanceRedactionReviewEntry[] = isRedactionReviewEntries(draft.redaction_review) ? draft.redaction_review : []
  // 空文本条目在保存前滤掉——服务端 `invalid_text` 拒收空条目，而「新增条目」
  // 允许先建空行再填。
  const payload = useMemo(() => Object.fromEntries(sections.map(([key]) => [
    key, (draft[key] as GuidanceItemDto[]).filter((item) => item.text.trim()),
  ])), [draft])
  async function save(confirm = false) {
    setSaving(true); setError("")
    try {
      let next = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/guidance-analyses/${encodeURIComponent(draft.id)}`, { method: "PATCH", body: { version: draft.version, customer_vision: draft.customer_vision, current_phase_objective: draft.current_phase_objective, executive_summary: draft.executive_summary, ...payload } })
      if (!isGuidanceAnalysis(next)) throw new Error("invalid guidance")
      // 台账七.1（goal-d2 S0-3）：PATCH 成功即推进本地版本基线——否则 confirm
      // 网络失败后本地 version 停在旧值，重试 PATCH 携带陈旧 version 必被
      // 乐观锁拦成 409，用户只能关面板重开。父组件 initial 引用稳定至
      // onSaved，这里提前推进不会触发回置。
      setDraft(next); setBaseline(next)
      if (confirm) {
        const analysisId = next.id
        // T-A2 复核闸：清单非空且已勾选「已复核」时显式携带 ack（路由只认
        // 字面 true）；清单为空不带该键——干净分析零额外负担。
        const ackBody = reviewList.length && reviewAcked ? { redaction_reviewed: true } : {}
        try {
          next = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/guidance-analyses/${encodeURIComponent(analysisId)}/confirm`, { method: "POST", body: { version: next.version, ...ackBody } })
        } catch (confirmCaught) {
          if (confirmCaught instanceof ApiClientError && confirmCaught.code === "redaction_review_required") {
            setReviewBlocked(true)
            if (!reviewList.length) {
              // 本地无清单（旧载荷或读面缺失）：回读读面取唯一投影，不自行推导。
              try {
                const refreshed = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/guidance-analyses/${encodeURIComponent(analysisId)}`, { method: "GET" })
                if (isGuidanceAnalysis(refreshed)) { setDraft(refreshed); setBaseline(refreshed) }
              } catch { /* 读面拉取失败只保留 409 文案 */ }
            }
          }
          throw confirmCaught
        }
        if (!isGuidanceAnalysis(next)) throw new Error("invalid guidance")
        setDraft(next); setBaseline(next)
      }
      published.current = next; onSaved(next)
      if (confirm) onClose()
      else setEditing(false)
    } catch (caught) {
      setError(caught instanceof ApiClientError ? caught.message : "项目指引保存失败，请稍后重试。")
    } finally { setSaving(false) }
  }
  async function beginEditing() {
    if (draft.status === "draft") { setEditing(true); return }
    setSaving(true); setError("")
    try {
      const next = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/guidance-analyses/${encodeURIComponent(draft.id)}/revisions`, { method: "POST", body: { version: draft.version } })
      if (!isGuidanceAnalysis(next)) throw new Error("invalid guidance")
      setDraft(next); setBaseline(next); published.current = next; onSaved(next); setEditing(true)
    } catch (caught) {
      setError(caught instanceof ApiClientError ? caught.message : "项目指引修订版创建失败，请稍后重试。")
    } finally { setSaving(false) }
  }
  // 条目粒度更新：元数据（classification / source_refs / severity / module）与
  // 条目对象绑定，不再按「整字段 textarea 的行号」重排——插入或删除一行会让
  // 其余条目的分类与原文锚点整体错位，把 A 的锚点贴到 B 的文字上，且人工编辑
  // 路径是弱校验（不查 source_refs），错位会静默落库。
  function changeItems(key: keyof GuidanceAnalysisDto, next: GuidanceItemDto[]) {
    setDraft({ ...draft, [key]: next })
  }
  function cancelEditing() { setDraft(baseline); setError(""); setEditing(false) }
  return <div className="dialog-backdrop"><section className="dialog guidance-review-dialog" role="dialog" aria-modal="true" aria-label="审核客户目标与项目指引">
    <div className="dialog-heading"><div><h3>客户目标与项目指引 · v{draft.version_number}</h3><p className="field-hint">来源：{draft.source_filename}</p></div><div className="row-actions">{canEdit ? <button className="secondary-button compact" type="button" disabled={saving} onClick={() => editing ? cancelEditing() : void beginEditing()}>{saving && !editing ? "创建修订中…" : editing ? "取消编辑" : "编辑"}</button> : null}<button className="secondary-button compact" type="button" onClick={onClose}>关闭</button></div></div>
    <div className="guidance-review-body">
      {draft.analysis_state !== "ready" ? draft.analysis_state === "failed" ? <p className="form-error" role="alert">{draft.failure_message}</p> : draft.analysis_state === "cancelled" ? <div className="guidance-analysis-progress" role="status"><strong>分析已取消</strong><p>本次预调研分析已取消，不会继续执行；可重新发起 AI 分析或上传新版预调研表。</p></div> : <div className="guidance-analysis-progress" role="status"><strong>预调研分析正在后台继续</strong><p>可以先关闭本页处理其他工作；进入分析时会显示 AI 执行中心，完成后这里会自动更新为审核内容。</p></div> : editing ? <div className="guidance-form">
        <label className="field"><span>客户长期愿景</span><textarea rows={3} value={draft.customer_vision} onChange={(event) => setDraft({ ...draft, customer_vision: event.target.value })} /></label>
        <label className="field"><span>当前阶段目标</span><textarea rows={3} value={draft.current_phase_objective} onChange={(event) => setDraft({ ...draft, current_phase_objective: event.target.value })} /></label>
        {sections.map(([key, label]) => <GuidanceItemsEditor key={key} title={label} items={draft[key] as GuidanceItemDto[]} sourceFilename={draft.source_filename} onChange={(next) => changeItems(key, next)} />)}
        <label className="field"><span>执行摘要</span><textarea rows={4} value={draft.executive_summary} onChange={(event) => setDraft({ ...draft, executive_summary: event.target.value })} /></label>
      </div> : <div className="guidance-detail-grid">
        <GuidanceText title="客户长期愿景" text={draft.customer_vision} wide />
        <GuidanceText title="当前阶段目标" text={draft.current_phase_objective} wide />
        {sections.map(([key, label]) => <GuidanceItems key={key} title={label} items={draft[key] as GuidanceItemDto[]} sourceFilename={draft.source_filename} />)}
        <GuidanceText title="执行摘要" text={draft.executive_summary} wide />
      </div>}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {reviewList.length && draft.status === "draft" ? (
        <fieldset className="field guidance-redaction-review" aria-label="企业名替换复核清单">
          <legend>企业名替换复核清单（{reviewList.length} 项）</legend>
          {reviewBlocked ? <p className="form-error" role="alert">存在待复核的企业名替换：请逐项核对下方清单后勾选「已复核」，再确认。</p> : null}
          <ul className="guidance-item-editor-list">
            {reviewList.map((entry) => <li key={entry.name} className="guidance-item-editor">
              <div className="guidance-item-editor-head">
                <span className="guidance-item-text">{entry.name}</span>
                <span className="guidance-item-meta">
                  <span className="guidance-item-source">{entry.occurrences} 处</span>
                  <span className={entry.matched_dict ? "guidance-item-confirmed" : "guidance-item-unconfirmed"}>{entry.matched_dict ? "词典命中" : "疑似（未收录）"}</span>
                </span>
              </div>
            </li>)}
          </ul>
          {canEdit ? <label className="guidance-item-confirmed-toggle">
            <input type="checkbox" checked={reviewAcked} onChange={(event) => setReviewAcked(event.target.checked)} />
            已复核：以上企业名替换已逐项人工核对（勾选后确认才会放行）
          </label> : null}
        </fieldset>
      ) : null}
      {editing && canEdit ? <div className="row-actions guidance-review-actions"><button className="secondary-button" type="button" disabled={saving} onClick={cancelEditing}>取消</button><button className="secondary-button" disabled={saving} onClick={() => void save(false)}>{saving ? "保存中…" : "保存修改"}</button><button className="primary-button" disabled={saving} onClick={() => void save(true)}>确认并用于项目指引</button></div>
        : !editing && canEdit && draft.status === "draft" ? <div className="row-actions guidance-review-actions"><button className="primary-button" disabled={saving} onClick={() => void save(true)}>{saving ? "确认中…" : "确认并用于项目指引"}</button></div> : null}
    </div>
  </section></div>
}

function GuidanceText({ title, text, wide = false }: { title: string; text: string; wide?: boolean }) {
  return <article className={`guidance-detail-section${wide ? " wide" : ""}`}><h4>{title}</h4><p>{text}</p></article>
}

function GuidanceItems({ title, items, sourceFilename }: { title: string; items: GuidanceItemDto[]; sourceFilename: string }) {
  const grouped = groupByLayer(items)
  return <article className="guidance-detail-section"><h4>{title}</h4>{items.length ? <div className="guidance-layers">{GUIDANCE_LAYERS.map((layer) => {
    const layerItems = grouped[layer]
    if (!layerItems.length) return null
    return <section key={layer} className={`guidance-layer guidance-layer-${layer}`} aria-label={LAYER_META[layer].label}>
      <header className="guidance-layer-heading"><h5>{LAYER_META[layer].label}</h5><span className="guidance-layer-count">{layerItems.length} 条</span></header>
      <ul className="guidance-layer-list">{layerItems.map((item, index) => <li key={index} className="guidance-layer-item">
        <span className={`guidance-classification-tag guidance-tag-${item.classification}`}>{CLASSIFICATION_LABELS[item.classification]}</span>
        <span className="guidance-item-text">{item.text}</span>
        <span className="guidance-item-meta">
          <span className="guidance-item-source">{item.source_refs.length ? `来源：${sourceFilename}` : "无原文锚点"}</span>
          {layer === "fact" ? <span className={item.confirmed ? "guidance-item-confirmed" : "guidance-item-unconfirmed"}>{item.confirmed ? "客户已确认" : "未确认"}</span> : null}
        </span>
      </li>)}</ul>
    </section>
  })}</div> : <p className="guidance-empty-copy">暂无内容</p>}</article>
}

function GuidanceItemsEditor({ title, items, sourceFilename, onChange }: { title: string; items: GuidanceItemDto[]; sourceFilename: string; onChange(next: GuidanceItemDto[]): void }) {
  function patch(index: number, changes: Partial<GuidanceItemDto>) {
    onChange(items.map((item, current) => current === index ? { ...item, ...changes } : item))
  }
  return <fieldset className="field guidance-items-editor">
    <legend>{title}</legend>
    <ul className="guidance-item-editor-list">
      {items.map((item, index) => <li key={index} className="guidance-item-editor">
        <div className="guidance-item-editor-head">
          <select className="guidance-item-classification" aria-label={`${title} 第 ${index + 1} 条分类`} value={item.classification} onChange={(event) => patch(index, { classification: event.target.value as GuidanceClassification })}>
            {allowedClassifications(item).map((value) => <option key={value} value={value}>{CLASSIFICATION_LABELS[value]}</option>)}
          </select>
          <span className="guidance-item-source">{item.source_refs.length ? `来源：${sourceFilename}` : "无原文锚点"}</span>
          <label className="guidance-item-confirmed-toggle"><input type="checkbox" checked={item.confirmed} onChange={(event) => patch(index, { confirmed: event.target.checked })} />客户已确认</label>
          <button type="button" className="secondary-button compact" onClick={() => onChange(items.filter((_, current) => current !== index))}>删除本条</button>
        </div>
        <textarea rows={2} aria-label={`${title} 第 ${index + 1} 条内容`} value={item.text} onChange={(event) => patch(index, { text: event.target.value })} />
      </li>)}
    </ul>
    <button type="button" className="secondary-button compact" onClick={() => onChange([...items, newGuidanceItem()])}>新增条目</button>
  </fieldset>
}
