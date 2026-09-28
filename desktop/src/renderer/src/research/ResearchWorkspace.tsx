import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react"
import { MemoMarkdown } from "./MemoMarkdown"

import { ApiClientError } from "../api/client"
import { useAIExecution } from "../ai/AIExecutionProvider"
import { useAuth } from "../auth/AuthProvider"
import { useDangerConfirm } from "../common/DangerConfirmProvider"
import { isProjectDto } from "../workbench/runtimeValidation"
import type { ProjectDto } from "../workbench/types"
import { isProjectResearchFormListDto, isResearchSubjectDto, isResearchSubjectListDto } from "./projectRuntimeValidation"
import { createEmptyOpportunityProfile, OpportunityDetail, OpportunityListPanel, OpportunityProfileFields, opportunityProfileInput, validateOpportunityProfile } from "./ResearchOpportunity"
import { AIOpportunityDiscoveryDialog } from "./AIOpportunityDiscoveryDialog"
import { ProjectResearchFormBuilder, type ProjectResearchFormDraft } from "./ProjectResearchFormBuilder"
import { ResearchForm } from "./ResearchForm"
import { ResearchSubjectTree } from "./ResearchSubjectTree"
import { CHILD_TYPES_BY_PARENT, RESEARCH_FIELD_TYPES, RESEARCH_SUBJECT_LABELS, RESEARCH_SUBJECT_TYPES, type AIOpportunityProfileDto, type ProjectResearchFormDto, type ResearchSubjectDto, type ResearchSubjectType } from "./types"

interface ResearchWorkspaceProps {
  initialOpportunityId?: string
  project: ProjectDto
  canFill: boolean
  canManage: boolean
  onDirtyChange(dirty: boolean): void
}

interface ResearchExportDto {
  id: string
  form_id: string
  form_name: string
  status: "queued" | "generating" | "succeeded" | "failed"
  version_number: number | null
  failure_code: string
  failure_message: string
}

interface SubjectMemoDto {
  memo: string
  version: number
}

interface PersonalMemoDto {
  user_id: string
  display_name: string
  memo: string
  version: number
  is_current_user: boolean
}

interface PersonalMemoListDto { items: PersonalMemoDto[] }

interface MemoMergeSourceDto { source: string; author: string; content: string }

interface MemoMergeResultDto {
  subject_id: string
  subject_version: number
  sources: MemoMergeSourceDto[]
  merged_memo: string
  change_summary: string[]
}

function isSubjectMemoDto(value: unknown): value is SubjectMemoDto {
  return typeof value === "object" && value !== null
    && Object.keys(value).length === 2
    && typeof (value as SubjectMemoDto).memo === "string"
    && Number.isInteger((value as SubjectMemoDto).version)
    && (value as SubjectMemoDto).version >= 1
}

function isPersonalMemoDto(value: unknown): value is PersonalMemoDto {
  if (!isRecord(value)) return false
  return typeof value.user_id === "string"
    && typeof value.display_name === "string"
    && typeof value.memo === "string"
    && Number.isInteger(value.version)
    && Number(value.version) >= 0
    && typeof value.is_current_user === "boolean"
}

function isPersonalMemoListDto(value: unknown): value is PersonalMemoListDto {
  return isRecord(value) && Array.isArray(value.items) && value.items.every(isPersonalMemoDto)
}

function isMemoMergeResultDto(value: unknown): value is MemoMergeResultDto {
  return isRecord(value)
    && typeof value.subject_id === "string"
    && Number.isInteger(value.subject_version)
    && Array.isArray(value.sources)
    && value.sources.every((item) => isRecord(item) && typeof item.source === "string" && typeof item.author === "string" && typeof item.content === "string")
    && typeof value.merged_memo === "string"
    && Array.isArray(value.change_summary)
    && value.change_summary.every((item) => typeof item === "string")
}

const subjectLabels = RESEARCH_SUBJECT_LABELS

export function ResearchWorkspace({ project, canFill, canManage, onDirtyChange, initialOpportunityId }: ResearchWorkspaceProps) {
  const { apiRequest } = useAuth()
  const { runAI } = useAIExecution()
  const dangerConfirm = useDangerConfirm()
  const [subjects, setSubjects] = useState<ResearchSubjectDto[]>([])
  const [forms, setForms] = useState<ProjectResearchFormDto[]>([])
  const [loadGeneration, setLoadGeneration] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [projectVersion, setProjectVersion] = useState(project.version)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [createType, setCreateType] = useState<Exclude<ResearchSubjectType, "project"> | null>(null)
  const [createName, setCreateName] = useState("")
  const [createDescription, setCreateDescription] = useState("")
  const [createOpportunityProfile, setCreateOpportunityProfile] = useState<AIOpportunityProfileDto>(createEmptyOpportunityProfile)
  const [renameSubject, setRenameSubject] = useState<ResearchSubjectDto | null>(null)
  const [renameSubjectName, setRenameSubjectName] = useState("")
  const [renameSubjectDescription, setRenameSubjectDescription] = useState("")
  const [memoDraft, setMemoDraft] = useState("")
  const [memoSaved, setMemoSaved] = useState("")
  const [memoSaving, setMemoSaving] = useState(false)
  const [memoEditing, setMemoEditing] = useState(false)
  const [personalMemos, setPersonalMemos] = useState<PersonalMemoDto[]>([])
  const [personalMemoOpen, setPersonalMemoOpen] = useState<PersonalMemoDto | null>(null)
  const [personalMemoDraft, setPersonalMemoDraft] = useState("")
  const [personalMemoSaved, setPersonalMemoSaved] = useState("")
  const [personalMemoEditing, setPersonalMemoEditing] = useState(false)
  const [personalMemoSaving, setPersonalMemoSaving] = useState(false)
  const [memoMergeResult, setMemoMergeResult] = useState<MemoMergeResultDto | null>(null)
  const [memoMerging, setMemoMerging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [viewedOpportunityId, setViewedOpportunityId] = useState<string | null>(null)
  const openedRouteOpportunity = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (!initialOpportunityId) { openedRouteOpportunity.current = undefined; return }
    if (openedRouteOpportunity.current === initialOpportunityId) return
    const opportunity = subjects.find(item => item.id === initialOpportunityId && item.subject_type === 'opportunity' && item.status === 'active')
    if (!opportunity) return
    openedRouteOpportunity.current = initialOpportunityId
    setSelectedId(opportunity.parent_subject_id ?? opportunity.id)
    setViewedOpportunityId(opportunity.id)
  }, [initialOpportunityId, subjects])
  const [editingOpportunity, setEditingOpportunity] = useState(false)
  const [formBuilderOpen, setFormBuilderOpen] = useState(false)
  const [formBuilderGeneration, setFormBuilderGeneration] = useState(0)
  const [initialFormDraft, setInitialFormDraft] = useState<ProjectResearchFormDraft | null>(null)
  const [editingForm, setEditingForm] = useState<ProjectResearchFormDto | null>(null)
  const [activeFormId, setActiveFormId] = useState<string | null>(null)
  const [aiFormOpen, setAIFormOpen] = useState(false)
  const [aiRequirement, setAIRequirement] = useState("")
  const [aiGenerating, setAIGenerating] = useState(false)
  const [aiError, setAIError] = useState("")
  const [aiOpportunityOpen, setAIOpportunityOpen] = useState(false)
  const [submittingResearchFormId, setSubmittingResearchFormId] = useState<string | null>(null)
  const [researchExports, setResearchExports] = useState<Record<string, ResearchExportDto>>({})
  const dirtyForms = useRef(new Set<string>())
  const memoEditorRef = useRef<HTMLTextAreaElement | null>(null)
  const personalMemoEditorRef = useRef<HTMLTextAreaElement | null>(null)
  const sequence = useRef(0)
  const pendingFocusId = useRef<string | null>(null)

  const loadResearch = useCallback(async (preferredSubjectId?: string): Promise<boolean> => {
    const requestSequence = ++sequence.current
    setError("")
    try {
      const [projectValue, subjectValue, formValue] = await Promise.all([
        apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(project.id)}`, { method: "GET" }),
        apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(project.id)}/research/subjects`, { method: "GET" }),
        apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(project.id)}/research/forms`, { method: "GET" }),
      ])
      if (requestSequence !== sequence.current) return false
      if (!isProjectDto(projectValue) || projectValue.id !== project.id || !isResearchSubjectListDto(subjectValue) || !isProjectResearchFormListDto(formValue)) throw new Error("invalid research dto")
      setProjectVersion((current) => Math.max(current, projectValue.version))
      setSubjects(subjectValue.items)
      setForms(formValue.items)
      setLoadGeneration((current) => current + 1)
      setSelectedId((current) => {
        const wanted = preferredSubjectId ?? current
        if (wanted && subjectValue.items.some((subject) => subject.id === wanted && subject.status === "active")) return wanted
        return subjectValue.items.find((subject) => subject.subject_type === "project" && subject.status === "active")?.id ?? null
      })
      return true
    } catch {
      if (requestSequence === sequence.current) setError("调研数据格式异常或加载失败，请稍后重试。")
      return false
    }
  }, [apiRequest, project.id])

  useEffect(() => {
    let active = true
    setLoading(true)
    void loadResearch().finally(() => { if (active) setLoading(false) })
    return () => { active = false; sequence.current += 1; dirtyForms.current.clear(); onDirtyChange(false) }
  }, [loadResearch, onDirtyChange])

  useEffect(() => setProjectVersion((current) => Math.max(current, project.version)), [project.version])

  useEffect(() => {
    const active = Object.values(researchExports).filter((item) => item.status === "queued" || item.status === "generating")
    if (!active.length) return
    let cancelled = false
    const timer = window.setTimeout(() => {
      void Promise.all(active.map(async (item) => {
        try {
          const value = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(project.id)}/research/exports/${encodeURIComponent(item.id)}`, { method: "GET" })
          if (!isResearchExportDto(value) || cancelled) return
          if (value.status === "succeeded") {
            setResearchExports((current) => withoutKey(current, value.form_id))
            setNotice(`调研表“${value.form_name}”已生成并进入文件库${value.version_number ? `（v${value.version_number}）` : ""}。`)
          } else if (value.status === "failed") {
            setResearchExports((current) => withoutKey(current, value.form_id))
            setError(value.failure_message || "调研结果生成失败，请稍后重试。")
          } else {
            setResearchExports((current) => ({ ...current, [value.form_id]: value }))
          }
        } catch {
          // A temporary polling failure must not cancel the server-side task.
        }
      }))
    }, 1500)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [apiRequest, project.id, researchExports])

  async function refreshProjectVersion(): Promise<number | null> {
    try {
      const value = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(project.id)}`, { method: "GET" })
      if (!isProjectDto(value) || value.id !== project.id) throw new Error("invalid project dto")
      setProjectVersion((current) => Math.max(current, value.version))
      return value.version
    } catch {
      setError("项目版本刷新失败，请稍后重试。")
      return null
    }
  }

  const selected = subjects.find((subject) => subject.id === selectedId && subject.status === "active") ?? null
  const selectedForms = useMemo(() => forms.filter((form) => form.subject_id === selectedId), [forms, selectedId])
  const activeForm = selectedForms.find((form) => form.id === activeFormId) ?? null
  const viewedOpportunity = useMemo(() => subjects.find((subject) => subject.id === viewedOpportunityId && subject.subject_type === "opportunity" && subject.status === "active") ?? null, [subjects, viewedOpportunityId])
  const opportunityForms = useMemo(() => viewedOpportunity ? forms.filter((form) => form.subject_id === viewedOpportunity.id) : [], [forms, viewedOpportunity])
  const filteredOpportunities = useMemo(
    () => opportunitiesForSelectedSubject(subjects, selectedId),
    [subjects, selectedId],
  )
  const canCreateOpportunity = canFill && Boolean(selected) && selected !== null && CHILD_TYPES_BY_PARENT[selected.subject_type]?.includes("opportunity")

  useEffect(() => {
    const subject = selected
    if (!subject || subject.subject_type === "opportunity") {
      setMemoDraft("")
      setMemoSaved("")
      setMemoEditing(false)
      return
    }
    let cancelled = false
    setMemoDraft("")
    setMemoSaved("")
    void apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(project.id)}/research/subjects/${encodeURIComponent(subject.id)}/memo`, { method: "GET" })
      .then((value) => {
        if (cancelled || !isSubjectMemoDto(value)) return
        setMemoDraft(value.memo)
        setMemoSaved(value.memo)
        setMemoEditing(canFill && value.memo.length === 0)
        setSubjects((current) => current.map((item) => item.id === subject.id ? { ...item, version: value.version } : item))
      })
      .catch(() => { if (!cancelled) setError("备忘录加载失败，请稍后重试。") })
    return () => { cancelled = true }
  }, [apiRequest, canFill, project.id, selected?.id, selected?.subject_type])

  useEffect(() => {
    const subject = selected
    setPersonalMemoOpen(null)
    setPersonalMemoDraft("")
    setPersonalMemoSaved("")
    setPersonalMemoEditing(false)
    setMemoMergeResult(null)
    if (!subject || subject.subject_type === "opportunity") {
      setPersonalMemos([])
      return
    }
    let cancelled = false
    setPersonalMemos([])
    void apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(project.id)}/research/subjects/${encodeURIComponent(subject.id)}/personal-memos`, { method: "GET" })
      .then((value) => {
        if (cancelled || !isPersonalMemoListDto(value)) return
        setPersonalMemos(value.items)
      })
      .catch(() => { if (!cancelled) setError("个人备忘录加载失败，请稍后重试。") })
    return () => { cancelled = true }
  }, [apiRequest, project.id, selected?.id, selected?.subject_type])

  useEffect(() => {
    const focusId = pendingFocusId.current
    if (!focusId || selectedId !== focusId) return
    const timeout = window.setTimeout(() => {
      const target = [...document.querySelectorAll<HTMLButtonElement>("button[data-research-subject-id]")]
        .find((button) => button.dataset.researchSubjectId === focusId)
      if (target) {
        target.focus()
        pendingFocusId.current = null
      }
    }, 0)
    return () => window.clearTimeout(timeout)
  }, [selectedId, subjects])

  function focusFirstDirtyForm(): void {
    window.setTimeout(() => {
      const card = document.querySelector<HTMLElement>('[data-research-dirty="true"]')
      const field = card?.querySelector<HTMLElement>('input:not([disabled]), textarea:not([disabled]), select:not([disabled])')
        ?? card?.querySelector<HTMLElement>('button:not([disabled])')
      field?.focus()
    }, 0)
  }

  function confirmDiscard(message: string): boolean {
    if (!dirtyForms.current.size) return true
    if (window.confirm(message)) return true
    focusFirstDirtyForm()
    return false
  }

  function clearDirtyRegistry(): void {
    dirtyForms.current.clear()
    onDirtyChange(false)
  }

  function resetDetailViews(): void {
    setViewedOpportunityId(null)
    setEditingOpportunity(false)
    setFormBuilderOpen(false)
    setEditingForm(null)
    setActiveFormId(null)
  }

  function selectSubject(subject: ResearchSubjectDto): void {
    if (subject.id === selectedId && !viewedOpportunityId && !formBuilderOpen && !activeFormId) return
    if (!confirmDiscard("当前表单有未保存修改，确定离开吗？")) return
    clearDirtyRegistry()
    resetDetailViews()
    setSelectedId(subject.id)
    setCreateType(null)
    setError("")
    setNotice("")
  }

  function beginCreate(type: Exclude<ResearchSubjectType, "project">): void {
    if (!selected) {
      setError("请先在对象树中选择上级调研对象，再新增下级。")
      return
    }
    const allowed = CHILD_TYPES_BY_PARENT[selected.subject_type] ?? []
    if (!allowed.includes(type)) {
      setError(`不能在“${subjectLabels[selected.subject_type]}”下新增${subjectLabels[type]}。`)
      return
    }
    if (!confirmDiscard("创建调研对象会切换工作区并放弃未保存修改，确定继续吗？")) return
    clearDirtyRegistry()
    resetDetailViews()
    setCreateType(type)
    setCreateName("")
    setCreateDescription("")
    setCreateOpportunityProfile(createEmptyOpportunityProfile())
    setError("")
  }

  function beginCreateOpportunity(): void {
    beginCreate("opportunity")
  }

  function viewOpportunity(opportunity: ResearchSubjectDto): void {
    if (!confirmDiscard("查看 AI 机会详情会离开当前提交区，确定继续吗？")) return
    clearDirtyRegistry()
    setCreateType(null)
    setFormBuilderOpen(false)
    setViewedOpportunityId(opportunity.id)
    setEditingOpportunity(false)
    setError("")
    setNotice("")
  }

  async function createSubject(): Promise<void> {
    if (!createType || !createName.trim()) {
      setError("请填写调研对象名称。")
      return
    }
    const parent = selected
    if (!parent) {
      setError("无法确定上级调研对象。")
      return
    }
    const allowed = CHILD_TYPES_BY_PARENT[parent.subject_type] ?? []
    if (!allowed.includes(createType)) {
      setError(`不能在“${subjectLabels[parent.subject_type]}”下新增${subjectLabels[createType]}。`)
      return
    }
    if (!confirmDiscard("创建调研对象会切换工作区并放弃未保存修改，确定继续吗？")) return
    if (createType === "opportunity") {
      const validationError = validateOpportunityProfile(createOpportunityProfile, opportunityOwnerOptions(project))
      if (validationError) { setError(validationError); return }
    }
    setBusy(true)
    setError("")
    try {
      const value = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(project.id)}/research/subjects`, {
        method: "POST",
        body: {
          version: projectVersion,
          subject_type: createType,
          subject_key: `${createType}_${Date.now().toString(36)}`,
          name: createName.trim(),
          description: createDescription.trim(),
          sort_order: subjects.filter((subject) => subject.subject_type === createType).length,
          parent_subject_id: parent.id,
        },
      })
      if (!isResearchSubjectDto(value)) throw new Error("invalid research subject")
      let created = value
      if (createType === "opportunity") {
        const updated = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(project.id)}/research/subjects/${encodeURIComponent(value.id)}`, {
          method: "PATCH",
          body: { version: value.version, opportunity_profile: opportunityProfileInput(createOpportunityProfile) },
        })
        if (!isResearchSubjectDto(updated)) throw new Error("invalid research subject profile")
        created = updated
      }
      const returnedVersion = (created as ResearchSubjectDto & { project_version?: number }).project_version
      if (returnedVersion) setProjectVersion((current) => Math.max(current, returnedVersion))
      setCreateType(null)
      setNotice(`${subjectLabels[createType]}已创建。`)
      clearDirtyRegistry()
      pendingFocusId.current = created.id
      await loadResearch(created.id)
    } catch (caught) {
      if (caught instanceof ApiClientError && caught.code === "stale_version") await refreshProjectVersion()
      setError(subjectMutationError(caught))
    } finally {
      setBusy(false)
    }
  }

  async function archiveSubject(subject: ResearchSubjectDto): Promise<void> {
    const isOpportunity = subject.subject_type === "opportunity"
    const action = isOpportunity ? "删除" : "停用"
    const objectName = isOpportunity ? "AI 机会" : "调研对象"
    const message = dirtyForms.current.size
      ? `${action}“${subject.name}”会放弃未保存修改，历史调研数据仍会保留。确定继续吗？`
      : `确定${action}“${subject.name}”吗？历史调研数据仍会保留。`
    if (!confirmDiscard(message)) return
    const confirmed = await dangerConfirm({
      title: `${action}${isOpportunity ? " " : ""}${objectName}`,
      description: `确定${action}“${subject.name}”吗？完成后将从当前列表移除，历史调研数据仍会保留。`,
      confirmLabel: action,
    })
    if (!confirmed) return
    setBusy(true)
    setError("")
    try {
      const value = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(project.id)}/research/subjects/${encodeURIComponent(subject.id)}`, { method: "DELETE", body: { version: subject.version } })
      if (!isResearchSubjectDto(value)) throw new Error("invalid research subject")
      const returnedVersion = (value as ResearchSubjectDto & { project_version?: number }).project_version
      if (returnedVersion) setProjectVersion((current) => Math.max(current, returnedVersion))
      clearDirtyRegistry()
      resetDetailViews()
      const parentId = subject.parent_subject_id ?? subjects.find((item) => item.subject_type === "project")?.id ?? null
      pendingFocusId.current = parentId
      await loadResearch(parentId ?? undefined)
      setNotice(isOpportunity ? "AI 机会已删除，历史数据已保留。" : "调研对象已停用，历史数据已保留。")
    } catch (caught) {
      setError(subjectMutationError(caught))
    } finally {
      setBusy(false)
    }
  }

  function beginRenameSubject(subject: ResearchSubjectDto): void {
    if (!["department", "role", "process"].includes(subject.subject_type)) return
    setRenameSubject(subject)
    setRenameSubjectName(subject.name)
    setRenameSubjectDescription(subject.description)
    setError("")
  }

  async function saveSubjectName(): Promise<void> {
    const subject = renameSubject
    const name = renameSubjectName.trim()
    const description = renameSubjectDescription.trim()
    if (!subject || !name) {
      setError("请填写调研对象名称。")
      return
    }
    const changes = {
      ...(name === subject.name ? {} : { name }),
      ...(description === subject.description ? {} : { description }),
    }
    if (!Object.keys(changes).length) {
      setRenameSubject(null)
      return
    }
    setBusy(true)
    setError("")
    try {
      const value = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(project.id)}/research/subjects/${encodeURIComponent(subject.id)}`, {
        method: "PATCH",
        body: { version: subject.version, ...changes },
      })
      if (!isResearchSubjectDto(value)) throw new Error("invalid research subject")
      setSubjects((current) => current.map((item) => item.id === value.id ? value : item))
      setRenameSubject(null)
      setNotice(`${subjectLabels[subject.subject_type]}信息已更新。`)
    } catch (caught) {
      if (caught instanceof ApiClientError && caught.code === "stale_version") await loadResearch(subject.id)
      setError(subjectMutationError(caught))
    } finally {
      setBusy(false)
    }
  }

  function updateForm(next: ProjectResearchFormDto): void {
    setForms((current) => current.some((form) => form.id === next.id) ? current.map((form) => form.id === next.id ? next : form) : [...current, next])
  }

  function updateOpportunity(next: ResearchSubjectDto): void {
    setSubjects((current) => current.map((subject) => subject.id === next.id ? next : subject))
  }

  function updateDirty(formId: string, dirty: boolean): void {
    if (dirty) dirtyForms.current.add(formId)
    else dirtyForms.current.delete(formId)
    onDirtyChange(dirtyForms.current.size > 0)
  }

  function updateMemoDraft(value: string): void {
    if (!selected || selected.subject_type === "opportunity") return
    setMemoDraft(value)
    updateDirty(`subject-memo:${selected.id}`, value !== memoSaved)
  }

  async function saveSubjectMemo(): Promise<boolean> {
    const subject = selected
    if (!subject || subject.subject_type === "opportunity") return false
    const memo = memoDraft
    if (memo === memoSaved) {
      updateDirty(`subject-memo:${subject.id}`, false)
      return true
    }
    setMemoSaving(true)
    setError("")
    try {
      const value = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(project.id)}/research/subjects/${encodeURIComponent(subject.id)}/memo`, {
        method: "PATCH",
        body: { version: subject.version, memo },
      })
      if (!isSubjectMemoDto(value)) throw new Error("invalid subject memo")
      setSubjects((current) => current.map((item) => item.id === subject.id ? { ...item, version: value.version } : item))
      setMemoDraft(value.memo)
      setMemoSaved(value.memo)
      updateDirty(`subject-memo:${subject.id}`, false)
      setNotice(`${subjectLabels[subject.subject_type]}备忘录已保存。`)
      return true
    } catch (caught) {
      if (caught instanceof ApiClientError && caught.code === "stale_version") await loadResearch(subject.id)
      setError(subjectMutationError(caught))
      return false
    } finally {
      setMemoSaving(false)
    }
  }

  function restoreMemoCursor(start: number, end: number): void {
    window.requestAnimationFrame(() => {
      const editor = memoEditorRef.current
      if (!editor) return
      editor.focus()
      editor.setSelectionRange(start, end)
    })
  }

  function handleMemoKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
      event.preventDefault()
      const start = event.currentTarget.selectionStart
      const end = event.currentTarget.selectionEnd
      void saveSubjectMemo().finally(() => restoreMemoCursor(start, end))
      return
    }
    if (event.key !== "Tab") return
    event.preventDefault()
    const editor = event.currentTarget
    const start = editor.selectionStart
    const end = editor.selectionEnd
    const indentation = "  "
    updateMemoDraft(`${memoDraft.slice(0, start)}${indentation}${memoDraft.slice(end)}`)
    restoreMemoCursor(start + indentation.length, start + indentation.length)
  }

  async function finishMemoEditing(): Promise<void> {
    if (memoDraft !== memoSaved && !(await saveSubjectMemo())) return
    setMemoEditing(false)
  }

  function beginMemoEditing(): void {
    setMemoEditing(true)
    window.requestAnimationFrame(() => memoEditorRef.current?.focus())
  }

  function openPersonalMemo(item: PersonalMemoDto): void {
    setPersonalMemoOpen(item)
    setPersonalMemoDraft(item.memo)
    setPersonalMemoSaved(item.memo)
    setPersonalMemoEditing(item.is_current_user && item.memo.length === 0)
    setError("")
  }

  function closePersonalMemo(): void {
    if (personalMemoDraft !== personalMemoSaved && !window.confirm("个人备忘录尚未保存，确定关闭吗？")) return
    if (personalMemoOpen) updateDirty(`personal-memo:${selected?.id}:${personalMemoOpen.user_id}`, false)
    setPersonalMemoOpen(null)
    setPersonalMemoEditing(false)
  }

  function updatePersonalMemoDraft(value: string): void {
    if (!selected || !personalMemoOpen?.is_current_user) return
    setPersonalMemoDraft(value)
    updateDirty(`personal-memo:${selected.id}:${personalMemoOpen.user_id}`, value !== personalMemoSaved)
  }

  async function savePersonalMemo(): Promise<boolean> {
    const subject = selected
    const personalMemo = personalMemoOpen
    if (!subject || subject.subject_type === "opportunity" || !personalMemo?.is_current_user) return false
    if (personalMemoDraft === personalMemoSaved) {
      updateDirty(`personal-memo:${subject.id}:${personalMemo.user_id}`, false)
      return true
    }
    setPersonalMemoSaving(true)
    setError("")
    try {
      const value = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(project.id)}/research/subjects/${encodeURIComponent(subject.id)}/personal-memo`, {
        method: "PATCH",
        body: { version: personalMemo.version, memo: personalMemoDraft },
      })
      if (!isPersonalMemoDto(value)) throw new Error("invalid personal memo")
      setPersonalMemos((current) => current.map((item) => item.user_id === value.user_id ? value : item))
      setPersonalMemoOpen(value)
      setPersonalMemoDraft(value.memo)
      setPersonalMemoSaved(value.memo)
      updateDirty(`personal-memo:${subject.id}:${value.user_id}`, false)
      setNotice("个人备忘录已保存，项目成员均可查看。")
      return true
    } catch (caught) {
      if (caught instanceof ApiClientError && caught.code === "stale_version") {
        setError("个人备忘录已在别处更新，请关闭后重新打开再编辑。")
      } else {
        setError("个人备忘录保存失败，请稍后重试。")
      }
      return false
    } finally {
      setPersonalMemoSaving(false)
    }
  }

  function restorePersonalMemoCursor(start: number, end: number): void {
    window.requestAnimationFrame(() => {
      const editor = personalMemoEditorRef.current
      if (!editor) return
      editor.focus()
      editor.setSelectionRange(start, end)
    })
  }

  function handlePersonalMemoKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
      event.preventDefault()
      const start = event.currentTarget.selectionStart
      const end = event.currentTarget.selectionEnd
      void savePersonalMemo().finally(() => restorePersonalMemoCursor(start, end))
      return
    }
    if (event.key !== "Tab") return
    event.preventDefault()
    const start = event.currentTarget.selectionStart
    const end = event.currentTarget.selectionEnd
    const indentation = "  "
    updatePersonalMemoDraft(`${personalMemoDraft.slice(0, start)}${indentation}${personalMemoDraft.slice(end)}`)
    restorePersonalMemoCursor(start + indentation.length, start + indentation.length)
  }

  async function finishPersonalMemoEditing(): Promise<void> {
    if (personalMemoDraft !== personalMemoSaved && !(await savePersonalMemo())) return
    setPersonalMemoEditing(false)
  }

  async function mergeMemosWithAI(): Promise<void> {
    const subject = selected
    if (!subject || subject.subject_type === "opportunity" || !canFill) return
    if (memoDraft !== memoSaved && !(await saveSubjectMemo())) return
    setMemoMerging(true)
    setError("")
    try {
      const value = await runAI<unknown>({
        operation: "project_research_memos_merge",
        title: `AI 正在整理“${subject.name}”的备忘录`,
        payload: { project_id: project.id, subject_id: subject.id },
      })
      if (!isMemoMergeResultDto(value)) throw new Error("invalid memo merge result")
      setMemoMergeResult(value)
    } catch (caught) {
      if (caught instanceof ApiClientError && caught.code === "memo_content_required") {
        setError("共用备忘录和个人备忘录都还没有内容，暂时无法整理。")
      } else if (caught instanceof ApiClientError && caught.code === "forbidden") {
        setError("你没有权限修改共用备忘录。")
      } else {
        setError(caught instanceof ApiClientError ? caught.message : "AI 合并整理失败，请稍后重试。")
      }
    } finally {
      setMemoMerging(false)
    }
  }

  async function adoptMergedMemo(): Promise<void> {
    const result = memoMergeResult
    const subject = selected
    if (!result || !subject || result.subject_id !== subject.id || !canFill) return
    setMemoSaving(true)
    setError("")
    try {
      const value = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(project.id)}/research/subjects/${encodeURIComponent(subject.id)}/memo`, {
        method: "PATCH",
        body: { version: result.subject_version, memo: result.merged_memo },
      })
      if (!isSubjectMemoDto(value)) throw new Error("invalid subject memo")
      setSubjects((current) => current.map((item) => item.id === subject.id ? { ...item, version: value.version } : item))
      setMemoDraft(value.memo)
      setMemoSaved(value.memo)
      setMemoEditing(false)
      updateDirty(`subject-memo:${subject.id}`, false)
      setMemoMergeResult(null)
      setNotice(`${subjectLabels[subject.subject_type]}共用备忘录已采用 AI 整理结果，个人备忘录保持不变。`)
    } catch (caught) {
      if (caught instanceof ApiClientError && caught.code === "stale_version") {
        await loadResearch(subject.id)
        setMemoMergeResult(null)
        setError("共用备忘录在整理期间发生了更新，请重新执行 AI 合并整理。")
      } else {
        setError("AI 整理结果保存失败，请稍后重试。")
      }
    } finally {
      setMemoSaving(false)
    }
  }

  function openFormBuilder(initialForm: ProjectResearchFormDraft | null = null, alreadyConfirmed = false): void {
    if (!selected) return
    if (!alreadyConfirmed && !confirmDiscard("新增调研表会离开当前提交区，确定继续吗？")) return
    clearDirtyRegistry()
    setCreateType(null)
    setViewedOpportunityId(null)
    setEditingOpportunity(false)
    setInitialFormDraft(initialForm)
    setEditingForm(null)
    setActiveFormId(null)
    setFormBuilderGeneration((current) => current + 1)
    setFormBuilderOpen(true)
    setError("")
    setNotice("")
  }

  function editFormDefinition(form: ProjectResearchFormDto): void {
    if (!confirmDiscard("修改调研表结构会离开当前填写区，确定继续吗？")) return
    clearDirtyRegistry()
    setInitialFormDraft(draftFromForm(form))
    setEditingForm(form)
    setActiveFormId(null)
    setFormBuilderOpen(true)
    setError("")
    setNotice("")
  }

  function returnToFormList(): void {
    if (!confirmDiscard("当前调研内容尚未保存，确定返回吗？")) return
    clearDirtyRegistry()
    setActiveFormId(null)
    setError("")
  }

  async function deleteForm(form: ProjectResearchFormDto): Promise<void> {
    const confirmed = await dangerConfirm({
      title: "删除调研表",
      description: `确定删除调研表“${form.name}”吗？表结构、已填内容和历史版本都将被永久删除。`,
      confirmLabel: "删除",
    })
    if (!confirmed) return
    setBusy(true)
    setError("")
    setNotice("")
    try {
      await apiRequest<void>(`/api/v1/projects/${encodeURIComponent(project.id)}/research/forms/${encodeURIComponent(form.id)}`, {
        method: "DELETE",
        body: { version: form.version },
      })
      setForms((current) => current.filter((item) => item.id !== form.id))
      setNotice(`调研表“${form.name}”已删除。`)
    } catch (caught) {
      if (caught instanceof ApiClientError && caught.code === "stale_version") {
        setError("调研表已被其他人更新，请刷新调研数据后重试。")
      } else if (caught instanceof ApiClientError && caught.code === "forbidden") {
        setError("你没有权限删除该调研表。")
      } else {
        setError("调研表删除失败，请稍后重试。")
      }
    } finally {
      setBusy(false)
    }
  }

  function openAIFormAssistant(): void {
    if (!selected) return
    if (!confirmDiscard("AI 生成调研表后会进入新增页面，当前未保存修改将被放弃。确定继续吗？")) return
    setAIError("")
    setAIFormOpen(true)
  }

  async function exportResearchResult(form: ProjectResearchFormDto): Promise<void> {
    if (submittingResearchFormId || researchExports[form.id]) return
    if (!window.confirm(`确定将调研表“${form.name}”导出到文件库吗？\n\n确认后系统将在后台生成 DOCX，期间可继续使用其他功能。`)) return
    setSubmittingResearchFormId(form.id); setError(""); setNotice("")
    try {
      const value = await apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(project.id)}/research/forms/${encodeURIComponent(form.id)}/export`, { method: "POST", body: {} })
      if (!isResearchExportDto(value)) throw new Error("invalid export")
      setResearchExports((current) => ({ ...current, [form.id]: value }))
      setNotice(`调研表“${form.name}”已提交后台生成，完成后会自动进入文件库。`)
    } catch (caught) {
      if (caught instanceof ApiClientError) {
        const messages: Record<string, string> = { research_answers_required: "当前调研表还没有可导出的调研内容。", ai_timeout: "AI 生成调研总结超时，请稍后重试。", ai_service_not_configured: "AI 服务尚未配置，请联系管理员。", ai_output_invalid: "AI 返回的调研总结格式不正确，请重试。" }
        setError(messages[caught.code] ?? `调研结果导出失败：${caught.message}`)
      } else setError("调研结果导出失败，请稍后重试。")
    } finally { setSubmittingResearchFormId(null) }
  }

  async function generateResearchFormWithAI(): Promise<void> {
    if (!selected || aiGenerating) return
    setAIGenerating(true)
    setAIError("")
    try {
      const value = await runAI<unknown>({ operation: "project_research_form_generate", title: `AI 正在为“${selected.name}”生成调研表`, payload: {
          project_id: project.id,
          subject_id: selected.id,
          requirement: aiRequirement.trim(),
          existing_forms: selectedForms.map((form) => ({
            form_key: form.form_key,
            name: form.name,
            subject_type: form.definition_snapshot.subject_type,
          })),
        } })
      if (!isProjectResearchFormDraft(value) || value.subject_type !== selected.subject_type) {
        throw new Error("invalid_ai_project_research_form")
      }
      setAIFormOpen(false)
      setAIRequirement("")
      openFormBuilder(value, true)
    } catch (caught) {
      setAIError(aiProjectResearchFormError(caught))
    } finally {
      setAIGenerating(false)
    }
  }

  return <div className="research-workspace">
    <div className="research-workspace-heading"><div><h2>项目调研</h2><p className="supporting-copy">按企业、部门、岗位、流程和 AI 机会维护内部调研记录。</p></div></div>
    {error ? <p className="form-error banner" role="alert">{error}</p> : null}
    {notice ? <p className="notice" role="status">{notice}</p> : null}
    {loading ? <p role="status">正在加载调研数据…</p> : <div className="research-workspace-grid">
      <div className="research-subject-column">
        <ResearchSubjectTree subjects={subjects} selectedId={selectedId} canFill={canFill} onSelect={selectSubject} onCreate={beginCreate} onRename={beginRenameSubject} onArchive={(subject) => void archiveSubject(subject)} onReorder={async (ordered) => {
          if (dirtyForms.current.size) throw new Error("请先保存当前未保存的内容，再调整顺序。")
          try {
            const result = await apiRequest<{ items: ResearchSubjectDto[] }>(`/api/v1/projects/${project.id}/research/subjects/reorder`, { method: "POST", body: { items: ordered.map(item => ({ id: item.id, version: item.version })) } })
            setSubjects(current => current.map(item => result.items.find(updated => updated.id === item.id) ?? item))
          } catch (error) {
            if (error instanceof ApiClientError && error.code === "stale_version") throw new Error("调研对象已被更新，请重新进入项目后再排序；本次未修改顺序。")
            throw error
          }
        }} />
        <OpportunityListPanel opportunities={filteredOpportunities} canCreateOpportunity={canCreateOpportunity} onCreate={beginCreateOpportunity} onAIGenerate={() => setAIOpportunityOpen(true)} onView={viewOpportunity} />
      </div>
      <main className="research-form-column" aria-label="调研表单工作区">
        {viewedOpportunity
          ? <OpportunityDetail projectId={project.id} opportunity={viewedOpportunity} forms={opportunityForms} ownerOptions={opportunityOwnerOptions(project)} canManage={canManage} canFill={canFill} editing={editingOpportunity} apiRequest={apiRequest} onOpportunityUpdated={(updated) => { updateOpportunity(updated); setEditingOpportunity(false) }} onUpdate={updateForm} onDirtyChange={updateDirty} onEdit={() => setEditingOpportunity(true)} onDelete={() => void archiveSubject(viewedOpportunity)} onBack={() => { if (confirmDiscard("返回会退出 AI 机会详情，确定继续吗？")) { clearDirtyRegistry(); setViewedOpportunityId(null); setEditingOpportunity(false) } }} /> : null}
        {formBuilderOpen ? <ProjectResearchFormBuilder key={formBuilderGeneration} projectId={project.id} subject={selected!} initialForm={initialFormDraft} editingForm={editingForm} apiRequest={apiRequest} onDirtyChange={(dirty) => updateDirty("research-form-builder", dirty)} onAIGenerate={canFill && !editingForm ? openAIFormAssistant : undefined} onCreated={(form) => { updateForm(form); setFormBuilderOpen(false); setInitialFormDraft(null); setEditingForm(null); setNotice(editingForm ? "调研表结构已更新，已填内容已保留。" : "调研表已创建。"); clearDirtyRegistry() }} onCancel={() => { if (confirmDiscard("取消会放弃未保存的结构修改，确定继续吗？")) { setFormBuilderOpen(false); setInitialFormDraft(null); setEditingForm(null) } }} /> : null}
        {!viewedOpportunity && !formBuilderOpen && createType ? <section className="panel research-create-panel" aria-labelledby="create-research-subject"><h2 id="create-research-subject">新增{subjectLabels[createType]}</h2><div className={createType === "opportunity" ? "opportunity-profile-form" : undefined}><label className={`field${createType === "opportunity" ? " wide" : ""}`}><span>{subjectLabels[createType]}名称</span><input autoFocus value={createName} disabled={busy} onChange={(event) => setCreateName(event.target.value)} /></label>{createType === "opportunity" ? <OpportunityProfileFields description={createDescription} profile={createOpportunityProfile} ownerOptions={opportunityOwnerOptions(project)} disabled={busy} onDescriptionChange={setCreateDescription} onProfileChange={setCreateOpportunityProfile} /> : <label className="field"><span>说明</span><textarea value={createDescription} disabled={busy} onChange={(event) => setCreateDescription(event.target.value)} /></label>}</div><div className="dialog-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => setCreateType(null)}>取消</button><button type="button" className="primary-button" disabled={busy} onClick={() => void createSubject()}>创建</button></div></section> : null}
        {selected && !viewedOpportunity && !formBuilderOpen ? <header className="research-selection-heading">
          <div className="research-selection-summary"><div className="research-selection-title"><span className="badge muted">{subjectLabels[selected.subject_type]}</span><h2>{selected.name}</h2></div>{selected.description.trim() ? <p className="research-subject-description"><span>{subjectLabels[selected.subject_type]}说明</span>{selected.description}</p> : null}</div>
          <div className="research-selection-side">
            <div className="research-selection-actions">{activeForm ? <button type="button" className="secondary-button compact" onClick={returnToFormList}>返回调研表列表</button> : canFill ? <button type="button" className="secondary-button compact" onClick={() => openFormBuilder()}>新增调研表</button> : null}</div>
            {!activeForm && selected.subject_type !== "opportunity" ? <div className="personal-memo-launcher" aria-label="项目成员个人备忘录"><span>个人备忘录</span>{personalMemos.map((item) => <button key={item.user_id} type="button" className={`secondary-button compact personal-memo-person${item.memo.trim() ? " has-content" : ""}${item.is_current_user ? " current" : ""}`} onClick={() => openPersonalMemo(item)} title={item.is_current_user ? "查看或编辑我的个人备忘录" : `查看${item.display_name}的个人备忘录`}>{item.display_name}</button>)}</div> : null}
          </div>
        </header> : null}
        {selected && selected.subject_type !== "opportunity" && !viewedOpportunity && !formBuilderOpen && !activeForm ? <section className="panel subject-memo-panel" data-research-dirty={memoDraft !== memoSaved ? "true" : "false"} aria-labelledby="subject-memo-title"><div className="subject-memo-heading"><div><div className="subject-memo-title-row"><h3 id="subject-memo-title">{subjectLabels[selected.subject_type]}备忘录</h3><span className="badge muted">共用</span></div><p className="supporting-copy compact-copy">记录团队共享的访谈线索、现场情况和待跟进事项；个人记录请使用上方个人备忘录。</p></div>{canFill ? <div className="subject-memo-actions"><button type="button" className="secondary-button compact ai-memo-merge-button" disabled={memoMerging || (!memoDraft.trim() && !personalMemos.some((item) => item.memo.trim()))} onClick={() => void mergeMemosWithAI()}>{memoMerging ? "正在整理" : "AI 合并整理"}</button>{memoEditing ? <><button type="button" className="secondary-button compact" disabled={memoSaving} onClick={() => void finishMemoEditing()}>完成编辑</button><button type="button" className="primary-button compact" disabled={memoSaving || memoDraft === memoSaved} onClick={() => void saveSubjectMemo()}>{memoSaving ? "正在保存" : "保存备忘录"}</button></> : <button type="button" className="secondary-button compact" onClick={beginMemoEditing}>编辑</button>}</div> : null}</div>{memoEditing && canFill ? <div className="subject-memo-editor"><textarea ref={memoEditorRef} aria-label={`${subjectLabels[selected.subject_type]}备忘录`} rows={7} maxLength={20_000} value={memoDraft} disabled={memoSaving} placeholder="支持 Markdown。例如：记录当前情况、待确认问题和后续跟进事项。" onKeyDown={handleMemoKeyDown} onChange={(event) => updateMemoDraft(event.target.value)} /><p className="subject-memo-shortcut-hint">支持 Markdown；Command+S 保存，Tab 插入缩进。</p></div> : <div className="subject-memo-preview">{memoSaved ? <MemoMarkdown>{memoSaved}</MemoMarkdown> : <p className="empty-state compact">暂无共用备忘录。</p>}</div>}</section> : null}
        {selected && !viewedOpportunity && !formBuilderOpen && !selectedForms.length ? <p className="empty-state">当前对象没有适用于已启用项目模块的调研表。可点击“新增调研表”为它配置调研表，或后续追加模块后刷新查看新表单。</p> : null}
        {!viewedOpportunity && !formBuilderOpen && !activeForm && selectedForms.length ? <div className="research-form-card-grid">{selectedForms.map((form) => <article className="panel research-form-summary-card" key={form.id}><div><h3>{form.name}</h3>{form.description ? <p className="supporting-copy">{form.description}</p> : null}</div><div className="research-card-progress"><span>完成度 {form.completion.completion_rate}%</span><progress max="100" value={form.completion.completion_rate}>{form.completion.completion_rate}%</progress><small>{form.completion.answered_visible}/{form.completion.visible_total} 项已填写</small></div><div className="research-card-actions">{canFill && form.completion.answered_visible > 0 ? <button type="button" className="secondary-button compact" disabled={busy || Boolean(submittingResearchFormId) || Boolean(researchExports[form.id])} onClick={() => void exportResearchResult(form)}>{submittingResearchFormId === form.id ? "正在提交…" : researchExports[form.id] ? "后台生成中…" : "导出到文件库"}</button> : null}{canFill ? <button type="button" className="primary-button compact" disabled={busy} onClick={() => setActiveFormId(form.id)}>填写</button> : <button type="button" className="secondary-button compact" disabled={busy} onClick={() => setActiveFormId(form.id)}>查看</button>}{canFill ? <button type="button" className="secondary-button compact" disabled={busy} onClick={() => editFormDefinition(form)}>修改结构</button> : null}{canManage ? <button type="button" className="danger-button compact" disabled={busy} onClick={() => void deleteForm(form)}>删除</button> : null}</div></article>)}</div> : null}
        {!viewedOpportunity && !formBuilderOpen && activeForm ? <ResearchForm key={`${activeForm.id}:${loadGeneration}`} projectId={project.id} form={activeForm} canFill={canFill} apiRequest={apiRequest} onUpdate={updateForm} onDirtyChange={(dirty) => updateDirty(activeForm.id, dirty)} onSaved={(saved) => { updateForm(saved); clearDirtyRegistry(); setActiveFormId(null); setNotice("调研内容已保存。") }} onCancel={returnToFormList} /> : null}
      </main>
    </div>}
    {aiFormOpen && selected ? <div className="dialog-backdrop">
      <section className="dialog ai-research-form-dialog" role="dialog" aria-modal="true" aria-labelledby="project-ai-research-form-title">
        <div className="dialog-heading"><div><h3 id="project-ai-research-form-title">AI 辅助生成调研表</h3><p className="supporting-copy compact-copy">当前对象：{subjectLabels[selected.subject_type]}“{selected.name}”。可直接生成，也可补充调研重点。</p></div><button className="secondary-button compact" type="button" disabled={aiGenerating} onClick={() => setAIFormOpen(false)}>关闭</button></div>
        <div className="field"><label htmlFor="project-ai-research-form-requirement">生成要求（可选）</label><textarea id="project-ai-research-form-requirement" rows={5} maxLength={4000} value={aiRequirement} disabled={aiGenerating} placeholder="例如：重点了解当前工作流程、痛点、数据现状和可量化目标。" onChange={(event) => setAIRequirement(event.target.value)} /></div>
        {aiError ? <p className="form-error banner" role="alert">{aiError}</p> : null}
        <div className="dialog-actions"><button className="secondary-button" type="button" disabled={aiGenerating} onClick={() => setAIFormOpen(false)}>取消</button><button className="primary-button" type="button" disabled={aiGenerating} onClick={() => void generateResearchFormWithAI()}>{aiGenerating ? "正在生成调研表" : "生成调研表"}</button></div>
      </section>
    </div> : null}
    {aiOpportunityOpen && selected ? <AIOpportunityDiscoveryDialog projectId={project.id} subject={selected} apiRequest={apiRequest} onClose={() => setAIOpportunityOpen(false)} onCreated={async () => { await loadResearch(selected.id); setNotice("AI 机会候选已保存，可继续人工审核和编辑。") }} /> : null}
    {personalMemoOpen && selected ? <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !personalMemoSaving) closePersonalMemo() }}>
      <section className="dialog personal-memo-dialog" role="dialog" aria-modal="true" aria-labelledby="personal-memo-title">
        <div className="dialog-heading"><div><h3 id="personal-memo-title">个人备忘录 · {personalMemoOpen.display_name}</h3><p className="supporting-copy compact-copy">项目成员均可查看；只有{personalMemoOpen.is_current_user ? "你自己" : personalMemoOpen.display_name}可以编辑这份内容。</p></div><button type="button" className="secondary-button compact" disabled={personalMemoSaving} onClick={closePersonalMemo}>关闭</button></div>
        {personalMemoEditing && personalMemoOpen.is_current_user ? <div className="subject-memo-editor"><textarea ref={personalMemoEditorRef} aria-label={`${personalMemoOpen.display_name}的个人备忘录`} rows={13} maxLength={20_000} value={personalMemoDraft} disabled={personalMemoSaving} placeholder="支持 Markdown。例如：记录个人观察、访谈线索、疑问和待跟进事项。" onKeyDown={handlePersonalMemoKeyDown} onChange={(event) => updatePersonalMemoDraft(event.target.value)} /><p className="subject-memo-shortcut-hint">支持 Markdown；Command+S 保存，Tab 插入缩进。</p></div> : <div className="subject-memo-preview personal-memo-preview">{personalMemoSaved ? <MemoMarkdown>{personalMemoSaved}</MemoMarkdown> : <p className="empty-state compact">暂无个人备忘录。</p>}</div>}
        <div className="dialog-actions"><button type="button" className="secondary-button" disabled={personalMemoSaving} onClick={closePersonalMemo}>关闭</button>{personalMemoOpen.is_current_user ? personalMemoEditing ? <><button type="button" className="secondary-button" disabled={personalMemoSaving} onClick={() => void finishPersonalMemoEditing()}>完成编辑</button><button type="button" className="primary-button" disabled={personalMemoSaving || personalMemoDraft === personalMemoSaved} onClick={() => void savePersonalMemo()}>{personalMemoSaving ? "正在保存" : "保存个人备忘录"}</button></> : <button type="button" className="primary-button" onClick={() => { setPersonalMemoEditing(true); window.requestAnimationFrame(() => personalMemoEditorRef.current?.focus()) }}>编辑</button> : null}</div>
      </section>
    </div> : null}
    {memoMergeResult && selected ? <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !memoSaving) setMemoMergeResult(null) }}>
      <section className="dialog memo-merge-dialog" role="dialog" aria-modal="true" aria-labelledby="memo-merge-title">
        <div className="dialog-heading"><div><h3 id="memo-merge-title">AI 合并整理 · {selected.name}</h3><p className="supporting-copy compact-copy">先对照原始记录和 AI 整理结果；只有点击“采用整理结果”才会更新共用备忘录，个人备忘录不会改变。</p></div><button type="button" className="secondary-button compact" disabled={memoSaving} onClick={() => setMemoMergeResult(null)}>关闭</button></div>
        <div className="memo-merge-comparison">
          <section className="memo-merge-column"><h4>整合前</h4><div className="memo-source-list">{memoMergeResult.sources.map((source, index) => <article className="memo-source-card" key={`${source.source}:${source.author}:${index}`}><div><strong>{source.source}</strong><span>{source.author}</span></div><div className="subject-memo-preview"><MemoMarkdown>{source.content}</MemoMarkdown></div></article>)}</div></section>
          <section className="memo-merge-column"><h4>AI 整合后</h4><div className="subject-memo-preview merged-memo-preview"><MemoMarkdown>{memoMergeResult.merged_memo}</MemoMarkdown></div></section>
        </div>
        <section className="memo-merge-analysis"><h4>变化分析</h4><ul>{memoMergeResult.change_summary.map((item, index) => <li key={`${index}:${item}`}>{item}</li>)}</ul></section>
        <div className="dialog-actions"><button type="button" className="secondary-button" disabled={memoSaving} onClick={() => setMemoMergeResult(null)}>保留原内容</button><button type="button" className="primary-button" disabled={memoSaving || !canFill} onClick={() => void adoptMergedMemo()}>{memoSaving ? "正在保存" : "采用整理结果"}</button></div>
      </section>
    </div> : null}
    {renameSubject ? <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) setRenameSubject(null) }}>
      <section className="dialog research-rename-dialog" role="dialog" aria-modal="true" aria-labelledby="research-rename-title">
        <div className="dialog-heading"><div><h3 id="research-rename-title">编辑{subjectLabels[renameSubject.subject_type]}</h3><p className="supporting-copy compact-copy">修改名称或说明，已有调研表和填写内容都会保留。</p></div></div>
        <label className="field"><span>{subjectLabels[renameSubject.subject_type]}名称</span><input autoFocus maxLength={160} value={renameSubjectName} disabled={busy} onChange={(event) => setRenameSubjectName(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void saveSubjectName() } }} /></label>
        <label className="field"><span>{subjectLabels[renameSubject.subject_type]}说明</span><textarea rows={5} value={renameSubjectDescription} disabled={busy} onChange={(event) => setRenameSubjectDescription(event.target.value)} /></label>
        <div className="dialog-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => setRenameSubject(null)}>取消</button><button type="button" className="primary-button" disabled={busy || !renameSubjectName.trim()} onClick={() => void saveSubjectName()}>{busy ? "正在保存" : "保存"}</button></div>
      </section>
    </div> : null}
  </div>
}

export function opportunitiesForSelectedSubject(subjects: ResearchSubjectDto[], selectedId: string | null): ResearchSubjectDto[] {
  if (!selectedId) return []
  return subjects.filter((subject) => (
    subject.subject_type === "opportunity"
    && subject.status === "active"
    && subject.parent_subject_id === selectedId
  ))
}

function draftFromForm(form: ProjectResearchFormDto): ProjectResearchFormDraft {
  return {
    form_key: form.form_key,
    name: form.name,
    description: form.description,
    subject_type: form.definition_snapshot.subject_type,
    module_key: form.definition_snapshot.module_key,
    sections: form.definition_snapshot.sections.map((section) => ({
      section_key: section.section_key,
      name: section.name,
      description: section.description,
      fields: section.fields.map((field) => ({
        field_key: field.field_key,
        name: field.name,
        help_text: field.help_text,
        type: field.type,
        is_required: false,
        options: field.options,
        ...(field.condition ? { condition: field.condition } : {}),
      })),
    })),
  }
}

function opportunityOwnerOptions(project: ProjectDto): Array<{ id: string; display_name: string }> {
  const options = [{ id: project.leader.id, display_name: project.leader.display_name }]
  for (const member of project.members ?? []) {
    if (!options.some((item) => item.id === member.user_id)) options.push({ id: member.user_id, display_name: member.display_name })
  }
  return options
}

function subjectMutationError(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (error.code === "stale_version") return "项目或调研对象已被更新，请刷新调研数据后重试。"
    if (error.code === "research_subject_has_active_children") return "该对象仍有启用中的下级，请先停用其下级后再重试。"
    if (error.code === "forbidden") return "你没有权限修改该项目的调研对象。"
  }
  return "调研对象操作失败，请稍后重试。"
}

function isProjectResearchFormDraft(value: unknown): value is ProjectResearchFormDraft {
  if (!isRecord(value)) return false
  if (typeof value.form_key !== "string" || typeof value.name !== "string" || typeof value.description !== "string") return false
  if (!RESEARCH_SUBJECT_TYPES.some((type) => type === value.subject_type)) return false
  if (value.module_key !== null && typeof value.module_key !== "string") return false
  if (!Array.isArray(value.sections) || value.sections.length === 0) return false
  return value.sections.every((section) => {
    if (!isRecord(section) || typeof section.section_key !== "string" || typeof section.name !== "string" || typeof section.description !== "string" || !Array.isArray(section.fields) || section.fields.length === 0) return false
    return section.fields.every((field) => isRecord(field)
      && typeof field.field_key === "string"
      && typeof field.name === "string"
      && typeof field.help_text === "string"
      && RESEARCH_FIELD_TYPES.some((type) => type === field.type)
      && typeof field.is_required === "boolean"
      && isRecord(field.options))
  })
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isResearchExportDto(value: unknown): value is ResearchExportDto {
  return isRecord(value)
    && typeof value.id === "string"
    && typeof value.form_id === "string"
    && typeof value.form_name === "string"
    && ["queued", "generating", "succeeded", "failed"].includes(String(value.status))
    && (value.version_number === null || typeof value.version_number === "number")
    && typeof value.failure_code === "string"
    && typeof value.failure_message === "string"
}

function withoutKey<T>(value: Record<string, T>, key: string): Record<string, T> {
  const next = { ...value }
  delete next[key]
  return next
}

function aiProjectResearchFormError(error: unknown): string {
  if (error instanceof ApiClientError) {
    const messages: Record<string, string> = {
      ai_service_not_configured: "AI 服务尚未配置，请联系管理员。",
      ai_authentication_failed: "AI 服务认证失败，请检查服务端配置。",
      ai_rate_limited: "AI 请求过于频繁，请稍后重试。",
      ai_timeout: "AI 生成超时，请稍后重试。",
      request_timeout: "AI 响应时间较长，请稍后重试。",
      ai_service_unavailable: "暂时无法连接 AI 服务，请稍后重试。",
      ai_output_invalid: "AI 生成的调研表结构不符合要求，请调整描述后重试。",
      research_subject_not_found: "当前调研对象不存在或已停用。",
      project_not_found: "项目不存在或无权访问。",
      forbidden: "你没有权限为当前项目生成调研表。",
      network_error: "无法连接本地服务，请确认服务已启动。",
    }
    return messages[error.code] ?? error.message
  }
  return "AI 生成的调研表格式无效，请重试。"
}
