import { useEffect, useId, useRef, useState } from 'react'

export type OpportunityFilterOption = { value: string; label: string; level?: number }
export function OpportunityFilter({ value, options, onChange }: { value: string; options: OpportunityFilterOption[]; onChange(value: string): void }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const id = useId()
  const label = options.find(item => item.value === value)?.label ?? '全部机会'
  useEffect(() => {
    const outside = (event: PointerEvent) => { if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(false) }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [])
  useEffect(() => {
    if (open) root.current?.querySelector<HTMLButtonElement>('[aria-selected="true"]')?.focus()
  }, [open])
  return <div className="delivery-filter-control" ref={root} onKeyDown={event => {
    if (event.key === 'Escape') { setOpen(false); trigger.current?.focus() }
    if (open && ['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault()
      const items = [...root.current!.querySelectorAll<HTMLButtonElement>('[role="option"]')]
      const index = items.indexOf(document.activeElement as HTMLButtonElement)
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : Math.max(0, Math.min(items.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)))
      items[next]?.focus()
    }
  }}>
    <span id={`${id}-label`}>关联机会筛选</span>
    <button ref={trigger} type="button" role="combobox" aria-labelledby={`${id}-label`} aria-expanded={open} aria-controls={`${id}-options`} aria-haspopup="listbox" title={label} onClick={() => setOpen(current => !current)} onKeyDown={event => { if (!open && event.key === 'ArrowDown') { event.preventDefault(); setOpen(true) } }}><span>{label}</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg></button>
    {open ? <div id={`${id}-options`} role="listbox" aria-label="关联机会" className="delivery-filter-options">{options.map(option => <button key={option.value} type="button" role="option" aria-selected={option.value === value} title={option.label} className={option.level ? 'nested' : ''} onClick={() => { onChange(option.value); setOpen(false); trigger.current?.focus() }}>{option.label}</button>)}</div> : null}
  </div>
}
