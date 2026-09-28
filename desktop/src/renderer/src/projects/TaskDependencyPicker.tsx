import type { ProjectTaskDto } from "../workbench/types"

export function TaskDependencyPicker({
  currentTaskId,
  tasks,
  value,
  disabled,
  onChange,
}: {
  currentTaskId: string | null
  tasks: ProjectTaskDto[]
  value: string[]
  disabled: boolean
  onChange(value: string[]): void
}) {
  const candidates = tasks.filter((task) => task.id !== currentTaskId && task.status !== "cancelled")
  return (
    <fieldset className="task-dependency-picker wide-field" disabled={disabled}>
      <legend>前置任务</legend>
      {candidates.length ? <div className="task-dependency-options">
        {candidates.map((candidate) => {
          const createsCycle = currentTaskId ? wouldCreateCycle(tasks, candidate.id, currentTaskId) : false
          return <label className="task-dependency-option" key={candidate.id}>
            <input
              type="checkbox"
              aria-label={`前置任务：${candidate.name}`}
              checked={value.includes(candidate.id)}
              disabled={disabled || createsCycle}
              onChange={(event) => onChange(event.target.checked
                ? [...value, candidate.id]
                : value.filter((id) => id !== candidate.id))}
            />
            <span>{candidate.name}{createsCycle ? <small>会形成循环</small> : null}</span>
          </label>
        })}
      </div> : <p className="field-hint">暂无可选前置任务。</p>}
    </fieldset>
  )
}

function wouldCreateCycle(tasks: ProjectTaskDto[], predecessorId: string, successorId: string): boolean {
  if (predecessorId === successorId) return true
  const byId = new Map(tasks.map((task) => [task.id, task]))
  const visited = new Set<string>()
  const stack = [predecessorId]
  while (stack.length) {
    const current = stack.pop()
    if (!current || visited.has(current)) continue
    if (current === successorId) return true
    visited.add(current)
    const task = byId.get(current)
    if (task) stack.push(...task.dependency_ids)
  }
  return false
}
