// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import React from 'react'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }))
vi.mock('../../src/renderer/src/auth/AuthProvider', () => ({ useAuth: () => mocks }))
vi.mock('../../src/renderer/src/common/DangerConfirmProvider', () => ({ useDangerConfirm: () => vi.fn() }))
import { ProjectDocuments, opportunityGroups } from '../../src/renderer/src/documents/ProjectDocuments'
import { parseHashRoute, routeHash } from '../../src/renderer/src/routing/useHashRoute'
import type { ResearchSubjectDto } from '../../src/renderer/src/research/types'
afterEach(() => { cleanup(); vi.resetAllMocks(); window.history.replaceState(null, '', '#projects') })
it('preselects the opportunity from the delivery link and omits the library shortcut', async () => {
  window.history.replaceState(null, '', '#projects/p?tab=delivery&opportunity=opp1')
  mocks.apiRequest.mockImplementation(async (path: string) => path.endsWith('/subjects') ? { items: [{ id: 'opp1', name: '机会1', subject_type: 'opportunity', status: 'active' }] } : { items: [] })
  render(<ProjectDocuments projectId="p" canManage deliveryMode />)
  await waitFor(() => expect(screen.getByRole('combobox', { name: '关联机会筛选' })).toHaveTextContent('机会1'))
  expect(screen.queryByText('前往文件库查看导出文件')).not.toBeInTheDocument()
})
it('keeps the opportunity filter in the canonical delivery route', () => {
  const hash = '#projects/project-1?tab=delivery&opportunity=opp-1'
  const route = parseHashRoute(hash)
  expect(route).toEqual({ kind: 'project', projectId: 'project-1', tab: 'delivery', opportunity: 'opp-1' })
  expect(routeHash(route)).toBe(hash)
})
it('defaults to normal documents and can filter archived or all', async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => ({ items: path.endsWith('/documents') ? ['draft', 'archived'].map((status, index) => ({ id: String(index), project_id: 'p', document_type: 'sow', business_code: index ? '已弃用文档' : '正常文档', business_category: null, status, version: 1, current_version_id: null, current_version: null, created_at: '2026-09-09' })) : [] }))
  render(<ProjectDocuments projectId="p" canManage deliveryMode />)
  expect(await screen.findByText('正常文档')).toBeVisible()
  expect(screen.queryByText('已弃用文档')).not.toBeInTheDocument()
  const user = userEvent.setup()
  await user.selectOptions(screen.getByRole('combobox', { name: '筛选文档状态' }), 'archived')
  expect(screen.getByText('已弃用文档')).toBeVisible()
  expect(screen.queryByText('正常文档')).not.toBeInTheDocument()
  await user.selectOptions(screen.getByRole('combobox', { name: '筛选文档状态' }), 'all')
  expect(screen.getByText('正常文档')).toBeVisible()
  expect(screen.getByText('已弃用文档')).toBeVisible()
})
it('hides empty objects and supplies full hover text in the bounded picker', async () => {
  const longName = '需要显示完整内容的长机会名称'.repeat(8)
  mocks.apiRequest.mockImplementation(async (path: string) => ({ items: path.endsWith('/subjects') ? [
    { id: 'root', name: '企业', subject_type: 'project', parent_subject_id: null },
    { id: 'empty', name: '无机会部门', subject_type: 'department', parent_subject_id: 'root' },
    { id: 'o', name: longName, subject_type: 'opportunity', parent_subject_id: 'root', status: 'active' },
  ] : [] }))
  render(<ProjectDocuments projectId="p" canManage deliveryMode />)
  await userEvent.click(screen.getByRole('combobox', { name: '关联机会筛选' }))
  expect(await screen.findByRole('option', { name: longName })).toHaveAttribute('title', longName)
  expect(screen.queryByRole('option', { name: /无机会部门/ })).not.toBeInTheDocument()
})
it('groups opportunities by full object hierarchy and excludes archived test data', () => {
  const subjects = [
    { id: 'p', name: '企业', subject_type: 'project', parent_subject_id: null },
    { id: 'd', name: '研发部', subject_type: 'department', parent_subject_id: 'p' },
    { id: 'r', name: 'NPI 工程师', subject_type: 'role', parent_subject_id: 'd' },
    { id: 'o', name: '流程助手', subject_type: 'opportunity', parent_subject_id: 'r', status: 'active' },
    { id: 'test', name: 'test', subject_type: 'opportunity', parent_subject_id: 'r', status: 'archived' },
  ] as ResearchSubjectDto[]
  const groups = opportunityGroups(subjects)
  expect(groups).toHaveLength(1)
  expect(groups[0].path).toBe('企业 › 研发部 › NPI 工程师')
  expect(groups[0].items.map(item => item.id)).toEqual(['o'])
})
it('requires selection and creates one SOW with multiple opportunity IDs and scope', async () => {
  mocks.apiRequest.mockImplementation(async (path: string, options: { method: string }) => {
    if (path.endsWith('/subjects')) return { items: [1, 2].map(i => ({ id: `opp${i}`, name: `机会${i}`, subject_type: 'opportunity', status: 'active', description: '描述' })) }
    if (path === '/api/v1/projects/p') return { version: 9 }
    if (path.endsWith('/documents') && options.method === 'POST') return { id: 'new-doc', version: 1 }
    return { items: [] }
  })
  render(<ProjectDocuments projectId="p" canManage deliveryMode />)
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '新建文档' }))
  await user.click(screen.getByRole('button', { name: '生成草稿' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('至少选择一个')
  await user.click(screen.getByRole('checkbox', { name: /机会1/ }))
  await user.click(screen.getByRole('checkbox', { name: /机会2/ }))
  await user.type(screen.getByRole('textbox'), '一期交付范围')
  await user.click(screen.getByRole('button', { name: '生成草稿' }))
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith('/api/v1/projects/p/documents', { method: 'POST', body: { document_type: 'sow', expected_version: 9, business_category: null, source_opportunity_ids: ['opp1', 'opp2'], generation_scope: '一期交付范围' } }))
  expect(mocks.apiRequest).toHaveBeenCalledWith('/api/v1/projects/p/documents/new-doc/generate', { method: 'POST', body: { version: 1 } })
})
