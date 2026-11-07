// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import React from 'react'
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ApiClientError } from '../../src/renderer/src/api/client'
import type { ResearchSubjectDto } from '../../src/renderer/src/research/types'
import { emptySolution } from '../../src/renderer/src/solutions/types'
import { solutionError } from '../../src/renderer/src/solutions/solutionErrors'
import type { SolutionDto } from '../../src/renderer/src/solutions/types'

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }))

it('explains archived SOW and unavailable template recovery in Chinese', () => {
  expect(solutionError(new ApiClientError({ code: 'solution_export_archived', message: '' }))).toContain('SOW 文件')
  expect(solutionError(new ApiClientError({ code: 'solution_template_unavailable', message: '' }))).toContain('发布新版 SOW 模板')
})
vi.mock('../../src/renderer/src/auth/AuthProvider', () => ({ useAuth: () => mocks }))
vi.mock('../../src/renderer/src/common/DangerConfirmProvider', () => ({ useDangerConfirm: () => vi.fn() }))
import { SolutionDesign as SolutionDesignPage } from '../../src/renderer/src/solutions/SolutionDesign'
import { parseHashRoute, routeHash, useHashRoute } from '../../src/renderer/src/routing/useHashRoute'
import { SolutionExport } from '../../src/renderer/src/solutions/SolutionExport'
import type { SolutionExportResult } from '../../src/renderer/src/solutions/SolutionExport'

const subjects = [
  { id: 'root', subject_type: 'project', name: '示例企业', status: 'active', parent_subject_id: null },
  { id: 'department', subject_type: 'department', name: '研发部', status: 'active', parent_subject_id: 'root' },
  { id: 'role', subject_type: 'role', name: 'NPI 工程师', status: 'active', parent_subject_id: 'department' },
  { id: 'empty', subject_type: 'department', name: '没有机会的部门', status: 'active', parent_subject_id: 'root' },
  { id: 'opp1', subject_type: 'opportunity', name: 'BOM 智能审核', tracking_code: 'OPP-0001', status: 'active', parent_subject_id: 'role' },
  { id: 'opp2', subject_type: 'opportunity', name: '工程资料整理', tracking_code: 'OPP-0002', status: 'active', parent_subject_id: 'role' },
] as ResearchSubjectDto[]

function solution(overrides: Partial<SolutionDto> = {}): SolutionDto {
  return { ...emptySolution(), id: 'solution1', project_id: 'p', name: '工程资料智能助手', design_markdown: '## 业务目标\n\n减少 **重复录入**，保留人工审核。', opportunity_ids: ['opp1'], opportunities: [{ id: 'opp1', name: 'BOM 智能审核', tracking_code: 'OPP-0001', parent_id: 'role' }], business_category: '生产部署', version: 3, status: 'active', updated_at: '2026-09-09T08:00:00Z', ...overrides }
}
let records: SolutionDto[]
function SolutionDesign({ projectId, canManage }: { projectId: string; canManage: boolean }) {
  const route = useHashRoute()
  return <><a href="#task-center">任务中心</a><a href={`#projects/${projectId}?tab=research`}>调研页</a>{route.kind === 'project' && route.tab === 'delivery'
    ? <SolutionDesignPage projectId={projectId} canManage={canManage} solutionId={route.solution} mode={route.mode} opportunityId={route.opportunity} />
    : <h2>其他页面</h2>}</>
}
beforeEach(() => {
  window.history.replaceState(null, '', '#projects/p?tab=delivery')
  records = [solution()]
  mocks.apiRequest.mockImplementation(async (path: string, options: { method: string; body?: Record<string, unknown> }) => {
    if (path.endsWith('/research/subjects')) return { items: subjects }
    if (path.endsWith('/solutions') && options.method === 'GET') return { items: records }
    if (path.endsWith('/solutions') && options.method === 'POST') {
      const item = solution({ ...options.body, id: 'new-solution', version: 1 })
      records.push(item); return item
    }
    if (path.includes('/solutions/') && options.method === 'GET') return records.find(item => path.endsWith(`/solutions/${item.id}`))
    if (path.endsWith('/solutions/solution1') && options.method === 'PATCH') { records[0] = { ...records[0], ...options.body, version: records[0].version + 1 }; return records[0] }
    if (path.endsWith('/documents')) return { items: [] }
    throw new Error(`Unexpected request: ${options.method} ${path}`)
  })
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.resetAllMocks(); window.history.replaceState(null, '', '#projects') })

it('uses solution cards and defaults to normal with all and archived filters', async () => {
  records.push(solution({ id: 'old', name: '已弃用旧方案', status: 'archived' }))
  render(<SolutionDesign projectId="p" canManage />)
  expect(await screen.findByRole('article', { name: '方案：工程资料智能助手' })).toBeVisible()
  expect(screen.queryByRole('article', { name: '方案：已弃用旧方案' })).not.toBeInTheDocument()
  expect(screen.queryByRole('table')).not.toBeInTheDocument()
  const user = userEvent.setup()
  await user.selectOptions(screen.getByRole('combobox', { name: '筛选方案状态' }), 'archived')
  expect(screen.getByRole('article', { name: '方案：已弃用旧方案' })).toBeVisible()
  expect(screen.queryByRole('button', { name: '弃用方案：已弃用旧方案' })).not.toBeInTheDocument()
  await user.selectOptions(screen.getByRole('combobox', { name: '筛选方案状态' }), 'all')
  expect(screen.getAllByRole('article')).toHaveLength(2)
})

it('filters associated opportunity hierarchy, hides empty objects, and supports linked opportunity routes', async () => {
  window.history.replaceState(null, '', '#projects/p?tab=delivery&opportunity=opp2')
  render(<SolutionDesign projectId="p" canManage />)
  expect(await screen.findByText('暂无符合筛选条件的方案。')).toBeVisible()
  const user = userEvent.setup()
  await user.click(screen.getByRole('combobox', { name: '关联机会筛选' }))
  expect(screen.queryByRole('option', { name: /没有机会的部门/ })).not.toBeInTheDocument()
  await user.click(screen.getByRole('option', { name: '示例企业 › 研发部 › NPI 工程师' }))
  expect(screen.getByRole('article', { name: '方案：工程资料智能助手' })).toBeVisible()
})

it('creates a solution with multiple associated opportunities and previews saved Markdown without generating a document', async () => {
  render(<SolutionDesign projectId="p" canManage />)
  const user = userEvent.setup()
  await waitFor(() => expect(screen.getByRole('button', { name: '新建方案' })).toBeEnabled())
  await user.click(screen.getByRole('button', { name: '新建方案' }))
  await user.click(await screen.findByRole('button', { name: '保存方案' }))
  expect(screen.getByRole('alert')).toHaveTextContent('至少选择一个')
  await user.click(screen.getByRole('checkbox', { name: /OPP-0001/ }))
  await user.click(screen.getByRole('checkbox', { name: /OPP-0002/ }))
  await user.type(screen.getByRole('textbox', { name: '方案名称' }), '联合工程方案')
  await user.type(screen.getByRole('textbox', { name: '方案设计' }), '## 设计内容\n保留 **人工复核**。')
  await user.type(screen.getByRole('textbox', { name: '交付物' }), '审核模块、使用手册')
  await user.click(screen.getByRole('button', { name: '保存方案' }))
  expect(await screen.findByRole('region', { name: '查看方案：联合工程方案' })).toBeVisible()
  expect(window.location.hash).toBe('#projects/p?tab=delivery&solution=new-solution')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '设计内容' })).toBeVisible()
  expect(screen.getByText('人工复核', { selector: 'strong' })).toBeVisible()
  expect(mocks.apiRequest).toHaveBeenCalledWith('/api/v1/projects/p/solutions', expect.objectContaining({ method: 'POST', body: expect.objectContaining({ name: '联合工程方案', opportunity_ids: ['opp1', 'opp2'], deliverables: '审核模块、使用手册' }) }))
  expect(mocks.apiRequest.mock.calls.some(([path]) => path.endsWith('/export-sow') || path.endsWith('/generate'))).toBe(false)
})

it('AI organization only prefills text for review, never changes associations or saves automatically', async () => {
  const original = mocks.apiRequest.getMockImplementation()!
  mocks.apiRequest.mockImplementation(async (path, options) => path.endsWith('/ai-organize') ? { fields: { name: 'AI 整理方案', design_markdown: '## 整理后的设计\n需确认数据授权。', deliverables: '资料整理模块', opportunity_ids: ['unauthorized-opp'], business_category: '商务合约' } } : original(path, options))
  render(<SolutionDesign projectId="p" canManage />)
  const user = userEvent.setup()
  await waitFor(() => expect(screen.getByRole('button', { name: '新建方案' })).toBeEnabled())
  await user.click(screen.getByRole('button', { name: '新建方案' }))
  await user.click(await screen.findByRole('checkbox', { name: /OPP-0001/ }))
  await user.type(screen.getByRole('textbox', { name: '方案参考' }), '先整理资料，再支持人工审核')
  await user.click(screen.getByRole('button', { name: 'AI 整理' }))
  expect(await screen.findByRole('heading', { name: '整理后的设计' })).toBeVisible()
  expect(screen.getByRole('textbox', { name: '方案名称' })).toHaveValue('AI 整理方案')
  expect(screen.getByRole('textbox', { name: '交付物' })).toHaveValue('资料整理模块')
  expect(screen.getByRole('checkbox', { name: /OPP-0001/ })).toBeChecked()
  expect(screen.getByRole('checkbox', { name: /OPP-0002/ })).not.toBeChecked()
  expect(screen.getByRole('status')).toHaveTextContent('尚未写入正式方案')
  expect(mocks.apiRequest.mock.calls.filter(([path, options]) => path.endsWith('/solutions') && options.method === 'POST')).toHaveLength(0)
})

it('retains manually entered contents after AI fails', async () => {
  const original = mocks.apiRequest.getMockImplementation()!
  mocks.apiRequest.mockImplementation(async (path, options) => { if (path.endsWith('/ai-organize')) throw new Error('unavailable'); return original(path, options) })
  render(<SolutionDesign projectId="p" canManage />)
  const user = userEvent.setup()
  await waitFor(() => expect(screen.getByRole('button', { name: '新建方案' })).toBeEnabled())
  await user.click(screen.getByRole('button', { name: '新建方案' }))
  await user.click(await screen.findByRole('checkbox', { name: /OPP-0001/ }))
  await user.type(screen.getByRole('textbox', { name: '方案设计' }), '我的设计内容')
  await user.type(screen.getByRole('textbox', { name: '方案参考' }), '整理参考')
  await user.click(screen.getByRole('button', { name: 'AI 整理' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('操作未完成')
  expect(screen.getByRole('textbox', { name: '方案设计' })).toHaveValue('我的设计内容')
})

it('loads the latest solution before editing and submits an optimistic version', async () => {
  render(<SolutionDesign projectId="p" canManage />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: '编辑方案：工程资料智能助手' }))
  await user.type(await screen.findByRole('textbox', { name: '计划排期' }), '两阶段实施')
  expect(mocks.apiRequest).toHaveBeenCalledWith('/api/v1/projects/p/solutions/solution1', { method: 'GET' })
  await user.click(screen.getByRole('button', { name: '保存方案' }))
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith('/api/v1/projects/p/solutions/solution1', expect.objectContaining({ method: 'PATCH', body: expect.objectContaining({ version: 3, schedule: '两阶段实施' }) })))
})

it('requires current account password in the archive request and clears it after rejection', async () => {
  const original = mocks.apiRequest.getMockImplementation()!
  mocks.apiRequest.mockImplementation(async (path, options) => { if (path.endsWith('/archive')) throw new ApiClientError({ code: 'invalid_password', message: 'bad password' }); return original(path, options) })
  render(<SolutionDesign projectId="p" canManage />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: '弃用方案：工程资料智能助手' }))
  await user.click(screen.getByRole('button', { name: '确认弃用' }))
  expect(screen.getByRole('alert')).toHaveTextContent('请输入当前账号密码')
  expect(mocks.apiRequest.mock.calls.some(([path]) => path.endsWith('/archive'))).toBe(false)
  await user.type(screen.getByLabelText('当前账号密码'), 'example-test-password')
  await user.click(screen.getByRole('button', { name: '确认弃用' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('当前账号密码错误')
  expect(screen.getByLabelText('当前账号密码')).toHaveValue('')
  expect(mocks.apiRequest).toHaveBeenCalledWith('/api/v1/projects/p/solutions/solution1/archive', { method: 'POST', body: { version: 3, password: 'example-test-password' } })
  expect(screen.getByRole('article', { name: '方案：工程资料智能助手' })).toBeVisible()
})

it('does not expose mutation controls to read-only users', async () => {
  render(<SolutionDesign projectId="p" canManage={false} />)
  const card = await screen.findByRole('article', { name: '方案：工程资料智能助手' })
  expect(screen.queryByRole('button', { name: '新建方案' })).not.toBeInTheDocument()
  expect(within(card).queryByRole('button', { name: /编辑方案|导出 SOW|弃用方案/ })).not.toBeInTheDocument()
  await userEvent.click(within(card).getByRole('button', { name: '查看' }))
  expect(await screen.findByRole('region', { name: '查看方案：工程资料智能助手' })).toBeVisible()
  expect(screen.queryByRole('link', { name: '编辑方案' })).not.toBeInTheDocument()
})

it('uses the shared file library behind a collapsed SOW-only entry without creating documents here', async () => {
  render(<SolutionDesign projectId="p" canManage />)
  await screen.findByRole('article')
  expect(mocks.apiRequest.mock.calls.some(([path]) => path.endsWith('/documents'))).toBe(false)
  await userEvent.click(screen.getByText('SOW 文件'))
  expect(await screen.findByRole('heading', { name: 'SOW 文件' })).toBeVisible()
  expect(screen.queryByRole('button', { name: '新建文档' })).not.toBeInTheDocument()
})

it('exports only the saved solution version and makes the generated SOW available to download', async () => {
  const original = mocks.apiRequest.getMockImplementation()!
  mocks.apiRequest.mockImplementation(async (path, options) => path.endsWith('/export-sow') ? { document_id: 'doc1', document_version_id: 'dv1', document: { id: 'doc1', current_version: { id: 'dv1', status: 'draft', docx_file_version_id: 'file1' }, generation_status: 'succeeded' } } : original(path, options))
  render(<SolutionDesign projectId="p" canManage />)
  await userEvent.click(await screen.findByRole('button', { name: '导出 SOW：工程资料智能助手' }))
  expect(await screen.findByRole('dialog', { name: '导出 SOW' })).toBeVisible()
  expect(screen.getByRole('button', { name: '下载 SOW' })).toBeEnabled()
  expect(mocks.apiRequest).toHaveBeenCalledWith('/api/v1/projects/p/solutions/solution1/export-sow', { method: 'POST', body: { version: 3 } })
})

it('does not execute raw HTML in saved Markdown', async () => {
  records = [solution({ design_markdown: '<script>window.attack = true</script>\n\n<img src=x onerror="window.attack=true">\n\n## 安全设计' })]
  render(<SolutionDesign projectId="p" canManage />)
  await userEvent.click(await screen.findByRole('button', { name: '查看' }))
  const viewer = await screen.findByRole('region', { name: '查看方案：工程资料智能助手' })
  expect(within(viewer).getByRole('heading', { name: '安全设计' })).toBeVisible()
  expect(viewer.querySelector('script, img[onerror]')).toBeNull()
})

it('groups delivery details into paired compact cards with full-width risk information while preserving Markdown', async () => {
  records = [solution({
    deliverables: '- **审核模块**\n- 使用手册',
    acceptance_criteria: '每项结论需要 **人工复核**。',
    data_systems: '读取 `ERP` 中已授权的物料资料。',
    schedule: '第一阶段梳理；第二阶段验证。',
    risks_dependencies: '## 数据授权\n由客户确认可使用的数据范围。',
  })]
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=solution1')
  render(<SolutionDesign projectId="p" canManage />)
  const viewer = await screen.findByRole('region', { name: '查看方案：工程资料智能助手' })
  const group = within(viewer).getByRole('group', { name: '交付信息' })
  const cards = [...group.querySelectorAll(':scope > section')]
  expect(cards).toHaveLength(5)
  expect(cards.map(card => within(card as HTMLElement).getAllByRole('heading')[0].textContent)).toEqual(['交付物', '预期指标/验收标准', '所需数据/系统', '计划排期', '风险与依赖'])
  expect(cards.slice(0, 4).every(card => card.classList.contains('solution-delivery-card') && !card.classList.contains('solution-delivery-card-full'))).toBe(true)
  expect(cards[4]).toHaveClass('solution-delivery-card-full')
  expect(within(group).getByText('审核模块', { selector: 'strong' })).toBeVisible()
  expect(within(group).getByText('人工复核', { selector: 'strong' })).toBeVisible()
  expect(within(group).getByText('ERP', { selector: 'code' })).toBeVisible()
  expect(within(group).getByText('第一阶段梳理；第二阶段验证。')).toBeVisible()
  expect(within(group).getByRole('heading', { name: '数据授权' })).toBeVisible()
  expect(within(group).getByText('由客户确认可使用的数据范围。')).toBeVisible()
  expect(within(viewer).getByRole('heading', { name: '业务目标' }).closest('.solution-delivery-grid')).toBeNull()
  expect(mocks.apiRequest.mock.calls.every(([, options]) => options.method === 'GET')).toBe(true)
})

it('retains all five labels and pending-confirmation placeholders for empty delivery details', async () => {
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=solution1')
  render(<SolutionDesign projectId="p" canManage />)
  const group = await screen.findByRole('group', { name: '交付信息' })
  expect(within(group).getAllByText('待确认')).toHaveLength(5)
  expect(within(group).getAllByRole('heading')).toHaveLength(5)
})

it('warns before discarding an unsaved form and can continue editing', async () => {
  render(<SolutionDesign projectId="p" canManage />)
  const user = userEvent.setup()
  await waitFor(() => expect(screen.getByRole('button', { name: '新建方案' })).toBeEnabled())
  await user.click(screen.getByRole('button', { name: '新建方案' }))
  await user.type(await screen.findByRole('textbox', { name: '方案名称' }), '未保存方案')
  await user.click(screen.getByRole('button', { name: '取消' }))
  expect(screen.getByRole('alert')).toHaveTextContent('尚未保存')
  await user.click(screen.getByRole('button', { name: '继续编辑' }))
  expect(screen.getByRole('textbox', { name: '方案名称' })).toHaveValue('未保存方案')
})

it('does not mark the requested SOW ready just because a newer export is ready', async () => {
  mocks.apiRequest.mockResolvedValue({ items: [{ id: 'requested', status: 'draft', docx_file_version_id: null, generation_status: 'queued' }, { id: 'newer', status: 'draft', docx_file_version_id: 'new-file' }] })
  const result = { document_id: 'doc1', document_version_id: 'requested', document: { current_version: { id: 'newer', status: 'draft', docx_file_version_id: 'new-file' }, generation_status: 'succeeded' } } as SolutionExportResult
  render(<SolutionExport projectId="p" result={result} name="当前方案" onRetry={vi.fn()} onClose={vi.fn()} />)
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith('/api/v1/projects/p/documents/doc1/versions', { method: 'GET' }))
  expect(screen.getByRole('button', { name: '下载 SOW' })).toBeDisabled()
})

it('allows downloading the requested SOW even while a newer export is still queued', async () => {
  mocks.apiRequest.mockResolvedValue({ items: [{ id: 'newer', status: 'draft', docx_file_version_id: null, generation_status: 'queued' }, { id: 'requested', status: 'draft', docx_file_version_id: 'requested-file' }] })
  const result = { document_id: 'doc1', document_version_id: 'requested', document: { current_version: { id: 'newer', status: 'draft', docx_file_version_id: null }, generation_status: 'queued' } } as SolutionExportResult
  render(<SolutionExport projectId="p" result={result} name="当前方案" onRetry={vi.fn()} onClose={vi.fn()} />)
  await waitFor(() => expect(screen.getByRole('button', { name: '下载 SOW' })).toBeEnabled())
})

it('offers retry when the exact requested generation fails', async () => {
  mocks.apiRequest.mockResolvedValue({ items: [{ id: 'requested', status: 'draft', generation_status: 'failed' }] })
  const retry = vi.fn()
  const result = { document_id: 'doc1', document_version_id: 'requested', document: { current_version: null } } as SolutionExportResult
  render(<SolutionExport projectId="p" result={result} name="当前方案" onRetry={retry} onClose={vi.fn()} />)
  await userEvent.click(await screen.findByRole('button', { name: '重试导出' }))
  expect(retry).toHaveBeenCalledOnce()
})

it('marks migrated delivery text for review instead of implying an approved solution', async () => {
  records = [solution({ source: { kind: 'legacy_opportunity_delivery' } })]
  render(<SolutionDesign projectId="p" canManage />)
  expect(await screen.findByText('历史交付说明 · 待整理')).toBeVisible()
})

it('keeps the migration source after editing without continuing to label it pending organization', async () => {
  records = [solution({ source: { kind: 'legacy_opportunity_delivery', reviewed: true } })]
  render(<SolutionDesign projectId="p" canManage />)
  expect(await screen.findByText('历史交付说明', { exact: true })).toBeVisible()
  expect(screen.queryByText('历史交付说明 · 待整理')).not.toBeInTheDocument()
})

it('shows solution SOW exports as the same file-library cards without old document-editing controls', async () => {
  const original = mocks.apiRequest.getMockImplementation()!
  mocks.apiRequest.mockImplementation(async (path, options) => path.endsWith('/documents') ? { items: [{ id: 'doc1', project_id: 'p', document_type: 'sow', business_code: 'SOW-方案', status: 'draft', version: 1, created_at: '2026-09-09', current_version_id: 'v1', current_version: { id: 'v1', version_number: 1, source: 'generated', status: 'draft', docx_file_version_id: 'f1' }, opportunity_scope: { solution: { id: 'solution1', name: '工程资料智能助手', version: 3 }, opportunities: [] } }] } : original(path, options))
  render(<SolutionDesign projectId="p" canManage />)
  await screen.findByRole('article')
  await userEvent.click(screen.getByText('SOW 文件'))
  expect(await screen.findByText('SOW-方案')).toBeVisible()
  expect(screen.queryByRole('table')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '在线修订：SOW-方案' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '编辑：SOW-方案' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '生成：SOW-方案' })).not.toBeInTheDocument()
})

it('still allows creating another solution after an export operation fails', async () => {
  const original = mocks.apiRequest.getMockImplementation()!
  mocks.apiRequest.mockImplementation(async (path, options) => { if (path.endsWith('/export-sow')) throw new ApiClientError({ code: 'solution_template_upgrade_required', message: 'template upgrade' }); return original(path, options) })
  render(<SolutionDesign projectId="p" canManage />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: '导出 SOW：工程资料智能助手' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('发布新版 SOW 模板')
  expect(screen.getByRole('button', { name: '新建方案' })).toBeEnabled()
  await user.click(screen.getByRole('button', { name: '新建方案' }))
  expect(await screen.findByRole('region', { name: '新建方案' })).toBeVisible()
})

it.each([
  '#projects/p?tab=delivery&solution=solution1',
  '#projects/p?tab=delivery&solution=solution1&mode=edit',
  '#projects/p?tab=delivery&solution=new',
  '#projects/p?tab=delivery&opportunity=opp1&solution=solution1&mode=edit',
])('round-trips canonical standalone solution route %s', hash => {
  expect(parseHashRoute(hash).kind).toBe('project')
  expect(routeHash(parseHashRoute(hash))).toBe(hash)
})

it.each([
  '#projects/p?tab=research&solution=solution1',
  '#projects/p?tab=delivery&solution=solution1&mode=view',
  '#projects/p?tab=delivery&solution=new&mode=edit',
  '#projects/p?tab=delivery&mode=edit',
  '#projects/p?tab=delivery&solution=solution1&solution=solution2',
  '#projects/p?tab=delivery&solution=solution1&extra=x',
  '#projects/p?tab=delivery&solution=%2F',
  '#projects/p?tab=delivery&solution=%73olution1',
  '#projects/p?solution=solution1&tab=delivery',
])('rejects malformed solution route %s', hash => {
  expect(parseHashRoute(hash)).toEqual({ kind: 'projects' })
})

it('opens a direct detail link from the server and returns to the same opportunity-filtered list', async () => {
  window.history.replaceState(null, '', '#projects/p?tab=delivery&opportunity=opp1&solution=solution1')
  render(<SolutionDesign projectId="p" canManage />)
  expect(await screen.findByRole('region', { name: '查看方案：工程资料智能助手' })).toBeVisible()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(mocks.apiRequest.mock.calls.some(([path]) => path.endsWith('/solutions'))).toBe(false)
  await userEvent.click(screen.getByRole('link', { name: '返回方案列表' }))
  expect(await screen.findByRole('article')).toBeVisible()
  expect(window.location.hash).toBe('#projects/p?tab=delivery&opportunity=opp1')
})

it('uses a dedicated edit page and returns to detail on cancel or save', async () => {
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=solution1')
  render(<SolutionDesign projectId="p" canManage />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('link', { name: '编辑方案' }))
  expect(await screen.findByRole('region', { name: '编辑方案' })).toBeVisible()
  expect(window.location.hash).toBe('#projects/p?tab=delivery&solution=solution1&mode=edit')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '取消' }))
  expect(await screen.findByRole('region', { name: '查看方案：工程资料智能助手' })).toBeVisible()
  await user.click(screen.getByRole('link', { name: '编辑方案' }))
  await user.type(await screen.findByRole('textbox', { name: '交付物' }), '新交付物')
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  await user.click(screen.getByRole('button', { name: '保存方案' }))
  expect(await screen.findByRole('region', { name: '查看方案：工程资料智能助手' })).toBeVisible()
  expect(screen.getByText('新交付物')).toBeVisible()
  expect(window.location.hash).toBe('#projects/p?tab=delivery&solution=solution1')
  expect(confirm).not.toHaveBeenCalled()
})

it('protects unsaved editing against sidebar links, project tabs and hash/back navigation', async () => {
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=solution1&mode=edit')
  render(<SolutionDesign projectId="p" canManage />)
  const user = userEvent.setup()
  const input = await screen.findByRole('textbox', { name: '方案名称' })
  await user.type(input, '未保存')
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  for (const name of ['任务中心', '调研页', '返回方案列表']) {
    await user.click(screen.getByRole('link', { name }))
    expect(input).toHaveValue('工程资料智能助手未保存')
    expect(window.location.hash).toBe('#projects/p?tab=delivery&solution=solution1&mode=edit')
  }
  act(() => { window.location.hash = '#projects' })
  await waitFor(() => expect(window.location.hash).toBe('#projects/p?tab=delivery&solution=solution1&mode=edit'))
  expect(confirm).toHaveBeenCalledTimes(4)
  confirm.mockReturnValue(true)
  await user.click(screen.getByRole('link', { name: '任务中心' }))
  expect(await screen.findByRole('heading', { name: '其他页面' })).toBeVisible()
  expect(confirm).toHaveBeenCalledTimes(5)
})

it('rejects direct editor access without management permission and treats archived editors as read-only', async () => {
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=solution1&mode=edit')
  const page = render(<SolutionDesign projectId="p" canManage={false} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('没有创建或编辑方案的权限')
  expect(screen.queryByRole('button', { name: '保存方案' })).not.toBeInTheDocument()
  page.unmount()
  records[0] = solution({ status: 'archived' })
  render(<SolutionDesign projectId="p" canManage />)
  expect(await screen.findByText('此方案已弃用，仅可查看内容。')).toBeVisible()
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
})

it('shows recoverable detail errors instead of a dead end', async () => {
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=missing')
  const original = mocks.apiRequest.getMockImplementation()!
  mocks.apiRequest.mockImplementation(async (path, options) => { if (path.endsWith('/solutions/missing')) throw new ApiClientError({ code: 'solution_not_found', message: '' }); return original(path, options) })
  render(<SolutionDesign projectId="p" canManage />)
  expect(await screen.findByRole('alert')).toHaveTextContent('方案或关联机会已发生变化')
  expect(screen.getByRole('button', { name: '重试加载' })).toBeEnabled()
  await userEvent.click(screen.getByRole('link', { name: '返回方案列表' }))
  expect(await screen.findByRole('article')).toBeVisible()
})

it('ignores older requests when quickly navigating between standalone details', async () => {
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=solution1')
  let resolveOld!: (value: SolutionDto) => void
  const oldRequest = new Promise<SolutionDto>(resolve => { resolveOld = resolve })
  const original = mocks.apiRequest.getMockImplementation()!
  records.push(solution({ id: 'solution2', name: '第二份方案' }))
  mocks.apiRequest.mockImplementation((path, options) => path.endsWith('/solutions/solution1') ? oldRequest : original(path, options))
  render(<SolutionDesign projectId="p" canManage />)
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith('/api/v1/projects/p/solutions/solution1', { method: 'GET' }))
  act(() => { window.location.hash = '#projects/p?tab=delivery&solution=solution2' })
  expect(await screen.findByRole('region', { name: '查看方案：第二份方案' })).toBeVisible()
  await act(async () => { resolveOld(solution()); await oldRequest })
  expect(screen.queryByRole('region', { name: '查看方案：工程资料智能助手' })).not.toBeInTheDocument()
})

it('generates a solution skeleton from confirmed guidance and surfaces server 409 guidance requirement', async () => {
  const user = userEvent.setup()
  const skeleton = solution({ id: 'skeleton-1', name: '零售连锁方案骨架', version: 1 })
  let skeletonAllowed = false
  mocks.apiRequest.mockImplementation(async (path: string, options: { method: string; body?: Record<string, unknown> }) => {
    if (path.endsWith('/research/subjects')) return { items: subjects }
    if (path.endsWith('/solutions') && options.method === 'GET') return { items: records }
    if (path.endsWith('/solutions/skeleton') && options.method === 'POST') {
      if (!skeletonAllowed) throw new ApiClientError({ code: 'solution_skeleton_guidance_required', message: '请先在预调研中完成项目指引确认，再生成方案骨架。' })
      records = [skeleton]
      return skeleton
    }
    if (path.endsWith('/documents')) return { items: [] }
    throw new Error(`Unexpected request: ${options.method} ${path}`)
  })
  const view = render(<SolutionDesign projectId="p" canManage />)

  const button = await screen.findByRole('button', { name: '按预调研生成骨架' })
  await user.click(button)
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('请先在预调研中完成项目指引确认'))

  skeletonAllowed = true
  await user.click(button)
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('已按预调研指引生成方案骨架'))
  await waitFor(() => expect(screen.getByTitle('零售连锁方案骨架')).toBeInTheDocument())
  expect(view).toBeDefined()
})

// ---- T-A6：报价核验 → 冻结 SOW 桌面闭环（建交付包入口） ----

function quoteSummary(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'q1',
    quote_key: 'Q-001',
    status: 'finalized',
    tier_label: 'B 试点',
    claims_summary: { accepted: 9, total: 9 },
    ...overrides,
  }
}

function packageLauncherMock(rows: Record<string, unknown>[], handlers: Record<string, (path: string, options: { method: string; body?: Record<string, unknown> }) => unknown> = {}) {
  const original = mocks.apiRequest.getMockImplementation()!
  mocks.apiRequest.mockImplementation(async (path: string, options: { method: string; body?: Record<string, unknown> }) => {
    if (path.endsWith('/quotes') && options.method === 'GET') return { quotes: rows }
    if (path === '/api/v1/dispatch/packages' && options.method === 'POST') {
      const handler = handlers['create']
      if (handler) return handler(path, options)
      return { id: 'pkg-new', package_code: 'PKG-01', dispatch_status: 'draft' }
    }
    return original(path, options)
  })
}

it('T-A6: offers finalized quotes for package creation and posts solution_id+quote_id to the dispatch API', async () => {
  packageLauncherMock([
    quoteSummary({ id: 'q-final', quote_key: 'Q-002', status: 'finalized', claims_summary: { accepted: 9, total: 9 } }),
    quoteSummary({ id: 'q-draft', quote_key: 'Q-001', status: 'draft', claims_summary: { accepted: 3, total: 9 } }),
  ])
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=solution1')
  render(<SolutionDesign projectId="p" canManage />)
  const launcher = await screen.findByRole('region', { name: '建交付包：工程资料智能助手' })
  const select = await within(launcher).findByRole('combobox', { name: '选择报价' })
  const user = userEvent.setup()
  // 默认选中第一笔 finalized 报价；草稿报价选项禁用（发布前必须成交回填）
  expect(select).toHaveValue('q-final')
  expect(within(launcher).getByRole('option', { name: /Q-001 · B 试点 · 草稿/ })).toBeDisabled()
  expect(within(launcher).getByRole('option', { name: /Q-002 .*已成交回填.*claims 9\/9/ })).toBeEnabled()
  await user.click(within(launcher).getByRole('button', { name: '创建交付包（草稿）' }))
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith('/api/v1/dispatch/packages', { method: 'POST', body: { solution_id: 'solution1', quote_id: 'q-final' } }))
  expect(await within(launcher).findByRole('status')).toHaveTextContent('交付包已创建（草稿）')
  expect(within(launcher).getByRole('status')).toHaveTextContent('发布后报价与方案要素即冻结为快照')
})

it('T-A6: gates the launcher with a readable checklist when no quote is finalized yet', async () => {
  packageLauncherMock([quoteSummary({ id: 'q-draft', quote_key: 'Q-001', status: 'draft', claims_summary: { accepted: 3, total: 9 } })])
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=solution1')
  render(<SolutionDesign projectId="p" canManage />)
  const launcher = await screen.findByRole('region', { name: '建交付包：工程资料智能助手' })
  // 无 finalized 报价 ⇒ 全部报价草稿提示 + 带报价收款页链接
  expect(await within(launcher).findByText(/全部报价仍是草稿/)).toBeVisible()
  expect(within(launcher).getByRole('link', { name: '报价收款' })).toHaveAttribute('href', '#projects/p?tab=commercial')
  // 草稿报价在下拉里禁用（不可选）——前置闸而非等服务端 422；未选中报价 ⇒ 按钮禁用、无建包请求
  expect(within(launcher).getByRole('option', { name: /Q-001 .*草稿/ })).toBeDisabled()
  expect(within(launcher).getByRole('button', { name: '创建交付包（草稿）' })).toBeDisabled()
  expect(mocks.apiRequest.mock.calls.some(([path]) => path === '/api/v1/dispatch/packages')).toBe(false)
})

it('T-A6: hides the package launcher for read-only users and on archived solutions', async () => {
  // 只读用户：列表点查看进详情 ⇒ 无建交付包区块
  render(<SolutionDesign projectId="p" canManage={false} />)
  await userEvent.click(await screen.findByRole('button', { name: '查看' }))
  expect(await screen.findByRole('region', { name: '查看方案：工程资料智能助手' })).toBeVisible()
  expect(screen.queryByRole('region', { name: /建交付包/ })).not.toBeInTheDocument()

  // 弃用方案：canManage 但 status=archived ⇒ 同样隐藏
  records = [solution({ status: 'archived' })]
  cleanup()
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=solution1')
  render(<SolutionDesign projectId="p" canManage />)
  expect(await screen.findByRole('region', { name: '查看方案：工程资料智能助手' })).toBeVisible()
  expect(screen.queryByRole('region', { name: /建交付包/ })).not.toBeInTheDocument()
})

it('T-A6: surfaces package_exists and verifier_role_required errors in Chinese', async () => {
  packageLauncherMock([quoteSummary({ id: 'q-final' })], {
    create: () => { throw new ApiClientError({ code: 'package_exists', message: '该方案已有交付包。' }) },
  })
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=solution1')
  render(<SolutionDesign projectId="p" canManage />)
  const launcher = await screen.findByRole('region', { name: '建交付包：工程资料智能助手' })
  const user = userEvent.setup()
  await user.click(await within(launcher).findByRole('button', { name: '创建交付包（草稿）' }))
  expect(await within(launcher).findByRole('alert')).toHaveTextContent('该方案已有交付包（撤回/拒绝后重发走同一行）')

  cleanup()
  packageLauncherMock([quoteSummary({ id: 'q-final' })], {
    create: () => { throw new ApiClientError({ code: 'verifier_role_required', message: '只有平台侧可建交付包。' }) },
  })
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=solution1')
  render(<SolutionDesign projectId="p" canManage />)
  const launcher2 = await screen.findByRole('region', { name: '建交付包：工程资料智能助手' })
  await user.click(await within(launcher2).findByRole('button', { name: '创建交付包（草稿）' }))
  expect(await within(launcher2).findByRole('alert')).toHaveTextContent('只有平台侧（管理员/项目负责人）可建交付包')
})

it('T-A6: quote card shows next-step guidance to the solution page after finalization', async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path).endsWith('/quotes')) return { quotes: [quoteSummary({ id: 'q1', quote_key: 'Q-001', status: 'finalized', tier_label: 'B 试点', ledger: { final_amount: 80000, final_deviation_pct: 0.05, allowance_cap: 10000, allowance_paid: 0, ticket_deal: false, ticket_note: '' }, calibration: { actual_hours: 80, deviation_pct: 0.1, deviation_reason: '回校完成', calibrated_buffer_factor: 1.8 }, computed: { realistic_hours: 60, total_cost: 50000, formula_price: 70000, b_layer_factor: 1.05, b_reference_price: null, anchor_low: 70000, anchor_high: 90000, branch: 'A', quote_low: 70000, quote_high: 90000, c_handling: null, c_handling_label: null }, field_claims: {}, claims_summary: { accepted: 9, total: 9 }, inputs: { ideal_hours: 40, integration_factor: 1, data_factor: 1, compliance_factor: 1, buffer_factor: 2, hourly_rate: 150, cash_cost: 5000, b_layer_score: 3, anchor_mode: 'cold_start' }, preset: null })] }
    if (String(path).endsWith('/payments')) return { payments: [], summary: { receivable: 0, received: 0, outstanding: 0, overdue: 0, dunning_counts: {} } }
    if (String(path).endsWith('/contracts')) return { contracts: [] }
    return {}
  })
  const { CommercialBoard } = await import('../../src/renderer/src/projects/CommercialBoard')
  render(<CommercialBoard projectId="comm" canManage />)
  const guide = await screen.findByText(/已成交回填。下一步：到/)
  expect(guide).toBeVisible()
  expect(screen.getByRole('link', { name: '方案设计' })).toHaveAttribute('href', '#projects/comm?tab=delivery')
  // 草稿报价不出现引导
  cleanup()
  const impl = mocks.apiRequest.getMockImplementation()!
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (String(path).endsWith('/quotes')) {
      const payload = await impl(String(path)) as { quotes: Array<Record<string, unknown>> }
      return { quotes: payload.quotes.map(row => ({ ...row, status: 'draft' })) }
    }
    return impl(String(path))
  })
  render(<CommercialBoard projectId="comm" canManage />)
  await screen.findByText('暂无收款计划。B 试点按 50/50 生成两行（G4 预付 / G8 尾款）。')
  expect(screen.queryByText(/已成交回填。下一步：到/)).not.toBeInTheDocument()
})

// ---- T-A7：谈判版本管理（谈判稿=未冻结版本，冻结状态在详情页可见） ----

function frozenDocsMock(rows: Array<{ id?: string; version?: number; status?: string }> = []): Record<string, unknown> {
  return { items: rows.map(row => ({ id: `doc-${row.id ?? row.version}`, project_id: 'p', document_type: 'sow', business_code: 'SOW-方案', status: row.status ?? 'draft', version: 1, created_at: '2026-09-09', current_version_id: 'v1', current_version: { id: 'v1', version_number: 1, source: 'generated', status: 'draft', docx_file_version_id: 'f1' }, opportunity_scope: { solution: { id: 'solution1', name: '工程资料智能助手', version: row.version }, opportunities: [] } })) }
}

function withFrozenDocs(rows: Array<{ version?: number; status?: string }> = []): void {
  const original = mocks.apiRequest.getMockImplementation()!
  mocks.apiRequest.mockImplementation(async (path: string, options: { method: string; body?: Record<string, unknown> }) => {
    if (path.endsWith('/documents')) return frozenDocsMock(rows)
    return original(path, options)
  })
}

it('T-A7: detail page labels the current version as frozen into SOW when versions match', async () => {
  // 种子方案 version=3，SOW 快照 scope.solution.version=3 ⇒ 已冻结
  withFrozenDocs([{ version: 3 }])
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=solution1')
  render(<SolutionDesign projectId="p" canManage />)
  expect(await screen.findByRole('region', { name: '查看方案：工程资料智能助手' })).toBeVisible()
  const badge = screen.getByText('已冻结进 SOW')
  expect(badge).toBeVisible()
  expect(badge).toHaveClass('success')
})

it('T-A7: detail page labels a newer unfrozen revision as edited negotiation draft', async () => {
  // 方案 version=3，但 SOW 只冻结过 v1 ⇒ 当前内容未进任何 SOW
  withFrozenDocs([{ version: 1 }])
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=solution1')
  render(<SolutionDesign projectId="p" canManage />)
  expect(await screen.findByRole('region', { name: '查看方案：工程资料智能助手' })).toBeVisible()
  const badge = screen.getByText('谈判稿 · 已修改')
  expect(badge).toBeVisible()
  expect(badge).toHaveClass('warning')
})

it('T-A7: detail page labels a never-exported solution as negotiation draft and degrades silently without documents', async () => {
  // 默认 beforeEach：/documents 返回空列表 ⇒ 从未导出 ⇒ 谈判稿
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=solution1')
  render(<SolutionDesign projectId="p" canManage />)
  expect(await screen.findByRole('region', { name: '查看方案：工程资料智能助手' })).toBeVisible()
  const badge = screen.getByText('谈判稿 · 未导出')
  expect(badge).toBeVisible()
  expect(badge).toHaveClass('muted')

  // /documents 拉取失败 ⇒ 静默降级为「谈判稿 · 未导出」，主内容不受影响
  cleanup()
  const original = mocks.apiRequest.getMockImplementation()!
  mocks.apiRequest.mockImplementation(async (path: string, options: { method: string; body?: Record<string, unknown> }) => {
    if (path.endsWith('/documents')) throw new Error('documents unavailable')
    return original(path, options)
  })
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=solution1')
  render(<SolutionDesign projectId="p" canManage />)
  expect(await screen.findByRole('region', { name: '查看方案：工程资料智能助手' })).toBeVisible()
  expect(screen.getByText('谈判稿 · 未导出')).toBeVisible()
})

it('T-A7: export dialog states which solution version the snapshot freezes and reuses', async () => {
  const original = mocks.apiRequest.getMockImplementation()!
  mocks.apiRequest.mockImplementation(async (path: string, options: { method: string; body?: Record<string, unknown> }) => {
    if (path.endsWith('/export-sow')) return { document_id: 'doc1', document_version_id: 'dv1', solution_version: 3, reused: false, document: { id: 'doc1', current_version: { id: 'dv1', status: 'draft', docx_file_version_id: 'file1' }, generation_status: 'succeeded' } }
    return original(path, options)
  })
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=solution1')
  render(<SolutionDesign projectId="p" canManage />)
  await userEvent.click(await screen.findByRole('button', { name: '导出 SOW' }))
  const dialog = await screen.findByRole('dialog', { name: '导出 SOW' })
  expect(await within(dialog).findByText((_, node) => node?.tagName === 'P' && node.textContent === '本 SOW 快照冻结的是方案 v3 的内容。后续修改方案会前进到新版本，不会覆盖这份 SOW；生成的文件也会保存在文件库中。')).toBeVisible()
  expect(within(dialog).queryByText((_, node) => node?.tagName === 'P' && typeof node.textContent === 'string' && node.textContent.includes('复用既有快照'))).not.toBeInTheDocument()

  // 同版本重复导出 ⇒ reused=true，文案带复用说明
  cleanup()
  mocks.apiRequest.mockImplementation(async (path: string, options: { method: string; body?: Record<string, unknown> }) => {
    if (path.endsWith('/export-sow')) return { document_id: 'doc1', document_version_id: 'dv1', solution_version: 3, reused: true, document: { id: 'doc1', current_version: { id: 'dv1', status: 'draft', docx_file_version_id: 'file1' }, generation_status: 'succeeded' } }
    return original(path, options)
  })
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=solution1')
  render(<SolutionDesign projectId="p" canManage />)
  await userEvent.click(await screen.findByRole('button', { name: '导出 SOW' }))
  const dialog2 = await screen.findByRole('dialog', { name: '导出 SOW' })
  const hint = await within(dialog2).findByText((_, node) => node?.tagName === 'P' && typeof node.textContent === 'string' && node.textContent.includes('复用既有快照'))
  expect(hint).toBeVisible()
})

it('T-A7: archived solutions keep the frozen badge visible in read-only view', async () => {
  // 弃用方案：徽标仍然呈现（冻结是历史事实，弃用不改变它）——但区块隐藏的建包入口不变
  records = [solution({ status: 'archived' })]
  withFrozenDocs([{ version: 3 }])
  window.history.replaceState(null, '', '#projects/p?tab=delivery&solution=solution1')
  render(<SolutionDesign projectId="p" canManage />)
  expect(await screen.findByRole('region', { name: '查看方案：工程资料智能助手' })).toBeVisible()
  expect(screen.getByText('已冻结进 SOW')).toBeVisible()
})
