// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ResearchSubjectTree } from '../../src/renderer/src/research/ResearchSubjectTree'
import type { ResearchSubjectDto } from '../../src/renderer/src/research/types'
afterEach(cleanup)
const subjects = [
  { id: 'root', parent_subject_id: null, subject_type: 'project', name: '企业', sort_order: 0 },
  { id: 'a', parent_subject_id: 'root', subject_type: 'department', name: '部门甲', sort_order: 10 },
  { id: 'b', parent_subject_id: 'root', subject_type: 'department', name: '部门乙', sort_order: 20 },
].map(item => ({ ...item, status: 'active', version: 1 })) as ResearchSubjectDto[]
function setup(canFill = true) {
  const reorder = vi.fn().mockResolvedValue(undefined)
  render(<ResearchSubjectTree subjects={subjects} selectedId="root" canFill={canFill} onSelect={vi.fn()} onCreate={vi.fn()} onRename={vi.fn()} onArchive={vi.fn()} onReorder={reorder} />)
  return reorder
}
it('drags siblings into order without changing parents', async () => {
  const reorder = setup()
  const source = screen.getByRole('treeitem', { name: /部门乙/ })
  const target = screen.getByRole('treeitem', { name: /部门甲/ })
  const dataTransfer = { setData: vi.fn(), effectAllowed: '', dropEffect: '' }
  fireEvent.dragStart(source, { dataTransfer })
  fireEvent.dragOver(target, { dataTransfer, clientY: 0 })
  fireEvent.drop(target, { dataTransfer, clientY: 0 })
  await waitFor(() => expect(reorder).toHaveBeenCalledOnce())
  expect(reorder.mock.calls[0][0].map((item: ResearchSubjectDto) => item.id)).toEqual(['b', 'a'])
  expect(reorder.mock.calls[0][0].every((item: ResearchSubjectDto) => item.parent_subject_id === 'root')).toBe(true)
})
it('supports keyboard reordering', async () => {
  const reorder = setup()
  fireEvent.keyDown(screen.getByRole('treeitem', { name: /部门乙/ }), { key: 'ArrowUp', altKey: true })
  await waitFor(() => expect(reorder).toHaveBeenCalledOnce())
})
it('does not allow viewers to drag', () => {
  const reorder = setup(false)
  const source = screen.getByRole('treeitem', { name: /部门乙/ })
  expect(source.closest('.research-tree-row')).toHaveAttribute('draggable', 'false')
  fireEvent.dragStart(source, { dataTransfer: { setData: vi.fn() } })
  fireEvent.drop(screen.getByRole('treeitem', { name: /部门甲/ }), { clientY: 0 })
  expect(reorder).not.toHaveBeenCalled()
})
