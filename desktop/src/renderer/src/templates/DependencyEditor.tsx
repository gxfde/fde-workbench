export interface DependencyTask {
  clientId: string
  taskKey: string
  name: string
  dependencyKeys: string[]
}

export function DependencyEditor({
  task,
  tasks,
  disabled,
  onChange,
}: {
  task: DependencyTask
  tasks: DependencyTask[]
  disabled: boolean
  onChange(dependencyKeys: string[]): void
}) {
  const candidates = tasks.filter(
    (candidate) => candidate.clientId !== task.clientId && stableKey(candidate.taskKey),
  )
  const labelName = task.name.trim() || `未命名任务 ${task.clientId}`

  return (
    <fieldset className="field dependency-field" aria-label={`${labelName}的前置任务`} disabled={disabled}>
      <legend>{labelName}的前置任务</legend>
      <div className="dependency-checkbox-list">
        {candidates.map((candidate) => {
          const cycle = !task.dependencyKeys.includes(candidate.taskKey) && wouldCreateCycle(
            tasks,
            candidate.taskKey,
            task.taskKey,
          )
          return (
            <label key={candidate.clientId} className={`dependency-checkbox-option${cycle ? " cycle-disabled" : ""}`}>
              <input type="checkbox" checked={task.dependencyKeys.includes(candidate.taskKey)} disabled={cycle} onChange={(event) => onChange(event.target.checked ? [...task.dependencyKeys, candidate.taskKey] : task.dependencyKeys.filter((key) => key !== candidate.taskKey))} />
              <span>{candidate.name.trim() || "未命名任务"}</span>
            </label>
          )
        })}
        {!candidates.length ? <span className="field-hint">暂无可选前置任务。</span> : null}
      </div>
      <small className="field-hint">可勾选多个前置任务，会形成循环的选项已禁用。</small>
    </fieldset>
  )
}

export function documentHasCycle(tasks: DependencyTask[]): boolean {
  return tasks.some((task) => hasPath(tasks, task.taskKey, task.taskKey, new Set(), true))
}

function wouldCreateCycle(
  tasks: DependencyTask[],
  predecessorKey: string,
  successorKey: string,
): boolean {
  if (!stableKey(predecessorKey) || !stableKey(successorKey)) return false
  if (predecessorKey === successorKey) return true
  return hasPath(tasks, successorKey, predecessorKey, new Set(), false)
}

function hasPath(
  tasks: DependencyTask[],
  fromKey: string,
  targetKey: string,
  visited: Set<string>,
  requireEdge: boolean,
): boolean {
  if (visited.has(fromKey)) return false
  visited.add(fromKey)
  const successors = tasks.filter((task) => task.dependencyKeys.includes(fromKey))
  for (const successor of successors) {
    if (successor.taskKey === targetKey) return true
    if (hasPath(tasks, successor.taskKey, targetKey, visited, requireEdge)) return true
  }
  return !requireEdge && fromKey === targetKey
}

function stableKey(value: string): boolean {
  return /^[a-z][a-z0-9_]*$/.test(value)
}
