// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import React from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn(), user: null as { id: string; role: string } | null }))
vi.mock('../../src/renderer/src/auth/AuthProvider', () => ({ useAuth: () => mocks }))

import { SignoffConsole } from '../../src/renderer/src/solutions/SignoffConsole'
import { DispatchPoolPage } from '../../src/renderer/src/dispatch/DispatchPoolPage'

beforeEach(() => {
  mocks.apiRequest.mockReset()
  mocks.user = null
})
afterEach(cleanup)

const TRAIL = {
  solution_id: 'sol-1',
  agent_run_id: 'run-1',
  meetings: [
    {
      id: 'm1', template_id: 'T2-lite', status: 'closed', gate_tier: 'lite',
      degraded: false, sealed: true,
      minutes: { consensus: [{ text: '通过' }], disputes: [], todos: [] },
    },
    {
      id: 'm2', template_id: 'T4-full', status: 'closed', gate_tier: 'full',
      degraded: true, sealed: false, minutes: null,
    },
  ],
  artifacts: [
    { id: 'a1', run_id: 'run-1', kind: 'doc', storage_ref: 'run-1/output/plan.md', sha256: 'a'.repeat(64), reviewed: false, linked_solution_id: 'sol-1', created_at: '2026-11-01T08:00:00+00:00' },
    { id: 'a2', run_id: 'run-1', kind: 'code', storage_ref: 'run-1/output/x.py', sha256: 'b'.repeat(64), reviewed: false, linked_solution_id: null, created_at: '2026-11-01T08:01:00+00:00' },
  ],
  signoff: {
    checkpoint_id: 'cp-1', status: 'pending', required_level: 'project_manager',
    reviewer_user_id: null, handoff_run_id: 'run-1', evidence_ref: null,
    created_at: '2026-11-01T08:02:00+00:00', updated_at: '2026-11-01T08:02:00+00:00',
  },
}

describe('终审台合并视图（goal-d9）', () => {
  it('产物+纪要同屏：待终审/未入通道/已封存/未封存徽标齐全，pending 出拍板按钮', async () => {
    mocks.apiRequest.mockResolvedValue(TRAIL)
    render(<SignoffConsole projectId="p1" solutionId="sol-1" canManage />)
    expect(await screen.findByText('产物（2）')).toBeInTheDocument()
    expect(screen.getByText('评审纪要（2）')).toBeInTheDocument()
    expect(screen.getAllByText('待终审')).toHaveLength(2)
    expect(screen.getByText('未入终审通道')).toBeInTheDocument()
    expect(screen.getByText('纪要已封存')).toBeInTheDocument()
    expect(screen.getByText('未封存')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '拍板通过' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '驳回' })).toBeInTheDocument()
  })

  it('拍板通过：POST signoff decision=approved 并刷新重取 trail', async () => {
    const user = userEvent.setup()
    const resolved = JSON.parse(JSON.stringify(TRAIL)) as typeof TRAIL
    resolved.signoff.status = 'approved'
    mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
      if (path.endsWith('/signoff') && options?.method === 'POST') {
        expect((options.body as { decision: string }).decision).toBe('approved')
        return Promise.resolve(resolved.signoff)
      }
      if (path.endsWith('/review-trail')) return Promise.resolve(mocks.apiRequest.mock.calls.length <= 1 ? TRAIL : resolved)
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    render(<SignoffConsole projectId="p1" solutionId="sol-1" canManage />)
    await user.click(await screen.findByRole('button', { name: '拍板通过' }))
    expect(await screen.findByText(/已通过/)).toBeInTheDocument()
  })

  it('无权限拍板：按钮不出现，改出权限说明', async () => {
    mocks.apiRequest.mockResolvedValue(TRAIL)
    render(<SignoffConsole projectId="p1" solutionId="sol-1" canManage={false} />)
    expect(await screen.findByText('产物（2）')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '拍板通过' })).toBeNull()
    expect(screen.getByText(/当前账号没有拍板权限/)).toBeInTheDocument()
  })

  it('已收口方案只读展示结论，不再出按钮', async () => {
    const resolved = JSON.parse(JSON.stringify(TRAIL)) as typeof TRAIL
    resolved.signoff.status = 'rejected'
    mocks.apiRequest.mockResolvedValue(resolved)
    render(<SignoffConsole projectId="p1" solutionId="sol-1" canManage />)
    expect(await screen.findByText(/已驳回/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '驳回' })).toBeNull()
  })
})

const PACKAGE = {
  id: 'pkg-1',
  package_code: 'PKG-20261101-001',
  scope_summary: '仓储一体化',
  deliverables_json: null,
  acceptance_criteria: null,
  data_systems: null,
  schedule_text: null,
  risks_dependencies: null,
  business_category: null,
  client_code: 'somwyn·制造·苏州',
  client_city: '苏州',
  onsite_required: false,
  onsite_visits: null,
  deadline: null,
  delivery_seat_amount: 8000,
  dispatch_status: 'accepted',
  dispatch_round: 1,
  dispatch_mode: 'claim',
  response_window_hours: 24,
  published_at: null,
  agent_assisted: false,
  difficulty: 'medium',
  accepted_user_id: 'user-1',
}

describe('派单桌面化（goal-d9）', () => {
  it('接单人视图：accepted 包展示难度档位与协同状态，本人可声明协同', async () => {
    const user = userEvent.setup()
    mocks.user = { id: 'user-1', role: 'fde_engineer' }
    mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
      if (path.endsWith('/agent-assisted') && options?.method === 'POST') {
        expect((options.body as { enabled: boolean }).enabled).toBe(true)
        return Promise.resolve({ data: {} })
      }
      if (path === '/api/v1/dispatch/packages') {
        return Promise.resolve([PACKAGE])
      }
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    render(<DispatchPoolPage />)
    const row = await screen.findByText('PKG-20261101-001')
    await user.click(row)
    expect(await screen.findByText('medium（agent 草稿 + 强制终审）')).toBeInTheDocument()
    expect(screen.getByText('未声明（纯人工交付）')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '声明智能体协同' }))
    expect(mocks.apiRequest.mock.calls.some(([path]) => String(path).endsWith('/agent-assisted'))).toBe(true)
  })

  it('非接单人（或 admin 未登录视角）看不到声明按钮', async () => {
    const user = userEvent.setup()
    mocks.user = { id: 'user-2', role: 'fde_engineer' }
    mocks.apiRequest.mockResolvedValue([PACKAGE])
    render(<DispatchPoolPage />)
    await user.click(await screen.findByText('PKG-20261101-001')) // 展开详情后才进入按钮区
    expect(await screen.findByText(/智能体协同/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '声明智能体协同' })).toBeNull()
  })
})
