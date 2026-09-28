import { useLayoutEffect, useState, type RefObject } from "react"

import type { GanttTaskDto } from "../workbench/types"

interface DependencyPath {
  from: string
  to: string
  risk: boolean
  d: string
}

export function GanttDependencyLayer({
  tasks,
  containerRef,
}: {
  tasks: GanttTaskDto[]
  containerRef: RefObject<HTMLElement | null>
}) {
  const edges = dependencyEdges(tasks)
  const [paths, setPaths] = useState<DependencyPath[]>(() => edges.map((edge) => ({ ...edge, d: "M 0 0" })))
  const [size, setSize] = useState({ width: 1, height: 1 })

  useLayoutEffect(() => {
    const container = containerRef.current
    if (!container) return
    const update = () => {
      const next = edges.map((edge) => {
        const from = container.querySelector<HTMLElement>(`[data-gantt-task-id="${cssEscape(edge.from)}"]`)
        const to = container.querySelector<HTMLElement>(`[data-gantt-task-id="${cssEscape(edge.to)}"]`)
        if (!from || !to) return { ...edge, d: "M 0 0" }
        const fromPoint = elementPoint(from, container, "end")
        const toPoint = elementPoint(to, container, "start")
        const bendX = Math.max(fromPoint.x + 12, toPoint.x - 12)
        return { ...edge, d: `M ${fromPoint.x} ${fromPoint.y} H ${bendX} V ${toPoint.y} H ${toPoint.x}` }
      })
      setPaths(next)
      setSize({ width: Math.max(container.scrollWidth, container.clientWidth, 1), height: Math.max(container.scrollHeight, container.clientHeight, 1) })
    }
    update()
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update)
    observer?.observe(container)
    window.addEventListener("resize", update)
    return () => {
      observer?.disconnect()
      window.removeEventListener("resize", update)
    }
  }, [containerRef, tasks])

  if (!edges.length) return null
  return (
    <svg
      className="gantt-dependency-layer"
      data-testid="gantt-dependency-layer"
      width={size.width}
      height={size.height}
      viewBox={`0 0 ${size.width} ${size.height}`}
      aria-hidden="true"
    >
      <defs>
        <marker id="gantt-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M 0 0 L 8 4 L 0 8 z" /></marker>
        <marker id="gantt-arrow-risk" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M 0 0 L 8 4 L 0 8 z" /></marker>
      </defs>
      {paths.map((path) => <path
        key={`${path.from}:${path.to}`}
        d={path.d}
        data-dependency-from={path.from}
        data-dependency-to={path.to}
        data-risk={String(path.risk)}
        className={path.risk ? "risk" : ""}
        markerEnd={`url(#${path.risk ? "gantt-arrow-risk" : "gantt-arrow"})`}
      />)}
    </svg>
  )
}

function dependencyEdges(tasks: GanttTaskDto[]): Array<Omit<DependencyPath, "d">> {
  const activeIds = new Set(tasks.filter((task) => !task.cancelled).map((task) => task.id))
  return tasks.flatMap((task) => task.cancelled ? [] : task.dependency_ids
    .filter((id) => activeIds.has(id))
    .map((id) => ({ from: id, to: task.id, risk: task.incomplete_dependency_ids.includes(id) })))
}

function elementPoint(element: HTMLElement, ancestor: HTMLElement, edge: "start" | "end") {
  let x = edge === "end" ? element.offsetWidth : 0
  let y = element.offsetHeight / 2
  let current: HTMLElement | null = element
  while (current && current !== ancestor) {
    x += current.offsetLeft
    y += current.offsetTop
    current = current.offsetParent as HTMLElement | null
  }
  return { x, y }
}

function cssEscape(value: string): string {
  return globalThis.CSS?.escape ? globalThis.CSS.escape(value) : value.replace(/["\\]/g, "\\$&")
}
