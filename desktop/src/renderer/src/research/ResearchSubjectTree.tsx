import { useEffect, useRef, useState } from "react"

import { CHILD_TYPES_BY_PARENT, RESEARCH_SUBJECT_LABELS, type ResearchSubjectDto, type ResearchSubjectType } from "./types"

interface ResearchSubjectTreeProps {
  subjects: ResearchSubjectDto[]
  selectedId: string | null
  canFill: boolean
  onSelect(subject: ResearchSubjectDto): void
  onCreate(type: Exclude<ResearchSubjectType, "project">): void
  onRename(subject: ResearchSubjectDto): void
  onArchive(subject: ResearchSubjectDto): void
  onReorder?(subjects: ResearchSubjectDto[]): Promise<void>
}

const typeLabels = RESEARCH_SUBJECT_LABELS

export function ResearchSubjectTree({ subjects, selectedId, canFill, onSelect, onCreate, onRename, onArchive, onReorder }: ResearchSubjectTreeProps) {
  const dragged = useRef<string | null>(null)
  const [sorting, setSorting] = useState(false)
  const [sortError, setSortError] = useState("")
  const treeRef = useRef<HTMLUListElement>(null)
  function clearDrag() {
    dragged.current = null
    treeRef.current?.querySelectorAll('[data-drop-position]').forEach(node => node.removeAttribute('data-drop-position'))
  }
  function targetSubject(target: EventTarget) {
    const row = target instanceof Element ? target.closest('.research-tree-row') : null
    const id = row?.querySelector<HTMLElement>('[data-research-subject-id]')?.dataset.researchSubjectId
    return { row, subject: subjects.find(item => item.id === id) }
  }
  async function move(sourceId: string, targetId: string, after: boolean) {
    if (!onReorder || sorting || !canFill) return
    const source = subjects.find(item => item.id === sourceId)
    const target = subjects.find(item => item.id === targetId)
    if (!source || !target || source.id === target.id || source.parent_subject_id !== target.parent_subject_id || source.subject_type === 'project') return
    const siblings = subjects.filter(item => item.status === 'active' && item.subject_type !== 'opportunity' && item.parent_subject_id === source.parent_subject_id).sort(subjectSort)
    const reordered = siblings.filter(item => item.id !== source.id)
    reordered.splice(reordered.findIndex(item => item.id === target.id) + (after ? 1 : 0), 0, source)
    if (reordered.every((item, index) => item.id === siblings[index].id)) return
    setSorting(true); setSortError("")
    try { await onReorder(reordered) } catch (error) { setSortError(error instanceof Error ? error.message : "排序保存失败，请重试。") } finally { setSorting(false) }
  }
  const active = subjects.filter((subject) => subject.status === "active" && subject.subject_type !== "opportunity")
  const root = active.find((subject) => subject.subject_type === "project") ?? null
  const selected = active.find((subject) => subject.id === selectedId) ?? null
  const selectedType = selected?.subject_type ?? "project"
  const creatableTypes = canFill ? (CHILD_TYPES_BY_PARENT[selectedType] ?? []) : []
  const [expanded, setExpanded] = useState<Set<string>>(() => defaultExpandedIds(active, selectedId))
  const previousParentIds = useRef(parentIds(active))

  useEffect(() => {
    const nextParentIds = parentIds(active)
    setExpanded((current) => {
      const activeIds = new Set(active.map((subject) => subject.id))
      const next = new Set([...current].filter((id) => activeIds.has(id)))
      for (const id of nextParentIds) if (!previousParentIds.current.has(id)) next.add(id)
      return next
    })
    previousParentIds.current = nextParentIds
  }, [subjects])

  useEffect(() => {
    if (!selectedId) return
    const ancestors = ancestorIds(active, selectedId)
    if (!ancestors.size) return
    setExpanded((current) => new Set([...current, ...ancestors]))
  }, [subjects, selectedId])

  function toggleSubject(subjectId: string): void {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(subjectId)) next.delete(subjectId)
      else next.add(subjectId)
      return next
    })
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLUListElement>): void {
    if (event.altKey && ["ArrowUp", "ArrowDown"].includes(event.key) && canFill && onReorder) {
      event.preventDefault()
      const { subject } = targetSubject(event.target)
      if (!subject) return
      const siblings = active.filter(item => item.parent_subject_id === subject.parent_subject_id).sort(subjectSort)
      const target = siblings[siblings.findIndex(item => item.id === subject.id) + (event.key === 'ArrowUp' ? -1 : 1)]
      if (target) void move(subject.id, target.id, event.key === 'ArrowDown')
      return
    }
    if (!["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return
    const items = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('button[role="treeitem"]')]
    const current = items.indexOf(event.target as HTMLButtonElement)
    if (current < 0 || !items.length) return
    event.preventDefault()
    const currentItem = items[current]
    const subjectId = currentItem.dataset.researchSubjectId
    if (event.key === "ArrowLeft") {
      if (subjectId && currentItem.getAttribute("aria-expanded") === "true") {
        setExpanded((value) => { const next = new Set(value); next.delete(subjectId); return next })
      } else {
        items.find((item) => item.dataset.researchSubjectId === currentItem.dataset.researchParentId)?.focus()
      }
      return
    }
    if (event.key === "ArrowRight") {
      if (!subjectId || currentItem.getAttribute("aria-expanded") === null) return
      if (currentItem.getAttribute("aria-expanded") === "false") {
        setExpanded((value) => new Set([...value, subjectId]))
      } else {
        items.find((item) => item.dataset.researchParentId === subjectId)?.focus()
      }
      return
    }
    const next = event.key === "Home"
      ? 0
      : event.key === "End"
        ? items.length - 1
        : event.key === "ArrowDown"
          ? Math.min(items.length - 1, current + 1)
          : Math.max(0, current - 1)
    items[next].focus()
    items[next].click()
  }

  return <aside className="panel research-subject-panel" aria-label="调研对象导航">
    {canFill && onReorder ? <p className="research-sort-hint" role="status">{sorting ? "正在保存顺序…" : "拖动对象调整同级顺序；也可用 Alt + ↑ / ↓"}</p> : null}
    {sortError ? <p className="form-error" role="alert">{sortError}</p> : null}
    <div className="panel-heading"><h2>调研对象</h2><span>{active.length} 个</span></div>
    {canFill ? <div className="research-create-actions" aria-label="新增调研对象">{creatableTypes.map((type) => <button type="button" className="secondary-button compact" key={type} onClick={() => onCreate(type)}>新增{typeLabels[type]}</button>)}{selected && selected.subject_type !== "project" ? <button type="button" className="danger-button compact" aria-label={`停用${selected.name}`} onClick={() => onArchive(selected)}>停用</button> : null}</div> : null}
    {root ? <ul className="research-tree" role="tree" aria-label="项目调研对象树" ref={treeRef} onKeyDown={handleKeyDown} onDragStart={(event) => {
      const { subject } = targetSubject(event.target)
      if (!canFill || !onReorder || sorting || !subject || subject.subject_type === 'project') { event.preventDefault(); return }
      dragged.current = subject.id; event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', subject.id)
    }} onDragOver={(event) => {
      const { row, subject } = targetSubject(event.target)
      const source = subjects.find(item => item.id === dragged.current)
      treeRef.current?.querySelectorAll('[data-drop-position]').forEach(node => node.removeAttribute('data-drop-position'))
      if (!row || !subject || !source || source.id === subject.id || source.parent_subject_id !== subject.parent_subject_id) return
      event.preventDefault(); event.dataTransfer.dropEffect = 'move'
      row.setAttribute('data-drop-position', event.clientY > row.getBoundingClientRect().top + row.getBoundingClientRect().height / 2 ? 'after' : 'before')
    }} onDrop={(event) => {
      event.preventDefault()
      const { row, subject } = targetSubject(event.target)
      if (dragged.current && subject && row) void move(dragged.current, subject.id, event.clientY > row.getBoundingClientRect().top + row.getBoundingClientRect().height / 2)
      clearDrag()
    }} onDragEnd={clearDrag}><SubjectNode subject={root} subjects={active} selectedId={selectedId} expanded={expanded} canFill={canFill} onSelect={onSelect} onRename={onRename} onToggle={toggleSubject} /></ul> : <p className="empty-state">项目调研根对象缺失。</p>}
  </aside>
}

function SubjectNode({ subject, subjects, selectedId, expanded, canFill, onSelect, onRename, onToggle }: {
  subject: ResearchSubjectDto
  subjects: ResearchSubjectDto[]
  selectedId: string | null
  expanded: Set<string>
  canFill: boolean
  onSelect(subject: ResearchSubjectDto): void
  onRename(subject: ResearchSubjectDto): void
  onToggle(subjectId: string): void
}) {
  const children = subjects.filter((candidate) => candidate.parent_subject_id === subject.id).sort(subjectSort)
  const isExpanded = children.length > 0 && expanded.has(subject.id)
  const canRename = canFill && ["department", "role", "process"].includes(subject.subject_type)
  return <li role="none"><div draggable={canRename} className={`research-tree-row ${selectedId === subject.id ? "selected" : ""}`}><button type="button" role="treeitem" data-research-subject-id={subject.id} data-research-parent-id={subject.parent_subject_id ?? undefined} aria-selected={selectedId === subject.id} aria-expanded={children.length ? isExpanded : undefined} tabIndex={selectedId === subject.id ? 0 : -1} onClick={() => onSelect(subject)}><span className="research-subject-type">{typeLabels[subject.subject_type]}</span><strong>{subject.name}</strong></button>{children.length ? <button type="button" className="research-tree-toggle" aria-label={`${isExpanded ? "收起" : "展开"}${subject.name}的下级`} aria-expanded={isExpanded} onClick={() => onToggle(subject.id)}><ChevronIcon expanded={isExpanded} /></button> : null}{canRename ? <button type="button" className="research-rename-button" aria-label={`编辑${typeLabels[subject.subject_type]}：${subject.name}`} title="编辑" onClick={() => onRename(subject)}><RenameIcon /></button> : null}</div>{isExpanded ? <ul role="group">{children.map((child) => <SubjectNode key={child.id} subject={child} subjects={subjects} selectedId={selectedId} expanded={expanded} canFill={canFill} onSelect={onSelect} onRename={onRename} onToggle={onToggle} />)}</ul> : null}</li>
}

function ChevronIcon({ expanded }: { expanded: boolean }) {
  return <svg viewBox="0 0 24 24" aria-hidden="true" className={expanded ? "expanded" : ""}><path d="m9 6 6 6-6 6" /></svg>
}

function RenameIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-4-4L4 16v4Z" /><path d="m13.5 6.5 4 4" /></svg>
}

function parentIds(subjects: ResearchSubjectDto[]): Set<string> {
  return new Set(subjects.map((subject) => subject.parent_subject_id).filter((id): id is string => Boolean(id)))
}

function ancestorIds(subjects: ResearchSubjectDto[], selectedId: string | null): Set<string> {
  const ancestors = new Set<string>()
  const byId = new Map(subjects.map((subject) => [subject.id, subject]))
  let current = selectedId ? byId.get(selectedId) : undefined
  while (current?.parent_subject_id) {
    ancestors.add(current.parent_subject_id)
    current = byId.get(current.parent_subject_id)
  }
  return ancestors
}

function defaultExpandedIds(subjects: ResearchSubjectDto[], selectedId: string | null): Set<string> {
  const expanded = ancestorIds(subjects, selectedId)
  const root = subjects.find((subject) => subject.subject_type === "project")
  if (root) expanded.add(root.id)
  return expanded
}

function subjectSort(left: ResearchSubjectDto, right: ResearchSubjectDto): number {
  const order: Record<ResearchSubjectType, number> = { project: 0, department: 1, role: 2, process: 3, opportunity: 4 }
  return left.sort_order - right.sort_order || order[left.subject_type] - order[right.subject_type] || left.name.localeCompare(right.name, "zh-CN")
}
