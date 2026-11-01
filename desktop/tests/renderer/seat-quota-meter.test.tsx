// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import React from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }))
vi.mock('../../src/renderer/src/auth/AuthProvider', () => ({ useAuth: () => mocks }))

import { QuotaMeter } from '../../src/renderer/src/solutions/QuotaMeter'

function quota(overrides: Record<string, unknown> = {}) {
  return {
    user_id: 'u1',
    quota_monthly: 100,
    unlimited: false,
    used: 12,
    remaining: 88,
    remaining_pct: 88,
    over_quota: false,
    warn_low_remaining: false,
    pack: { entry: 'action_pack', price_yuan: 1, unit: 'action', note: '加油包按次计价（¥0.5–2/次量级）。' },
    window: { started_at: null, review_due_at: null, review_due: false },
    ...overrides,
  }
}

beforeEach(() => { mocks.apiRequest.mockReset() })
afterEach(cleanup)

it('正常余量：透明显示消耗（37/100 心智）', async () => {
  mocks.apiRequest.mockResolvedValue(quota({ used: 37, remaining: 63, remaining_pct: 63 }))
  render(<QuotaMeter />)
  const badge = await screen.findByText('37/100 次动作')
  expect(badge).toHaveClass('seat-quota')
  expect(badge).not.toHaveClass('warning')
  expect(badge).toHaveAccessibleDescription(/透明显示|工作台动作消耗/)
})

it('余量 ≤20%：warning 提醒（透明化硬规则）', async () => {
  mocks.apiRequest.mockResolvedValue(quota({ used: 85, remaining: 15, remaining_pct: 15, warn_low_remaining: true }))
  render(<QuotaMeter />)
  const badge = await screen.findByText('85/100 次动作 · 余量不足')
  expect(badge).toHaveClass('warning')
  expect(badge).toHaveAccessibleDescription(/≤20% 提醒/)
})

it('超额：只标注 + 加油包计价入口，绝不断供（无任何拦截按钮/文案）', async () => {
  mocks.apiRequest.mockResolvedValue(quota({ used: 100, remaining: 0, remaining_pct: 0, over_quota: true, warn_low_remaining: true }))
  render(<QuotaMeter />)
  const badge = await screen.findByText('额度已用尽 · 加油包 ¥1/次')
  expect(badge).toHaveClass('warning')
  expect(badge).toHaveAccessibleDescription(/次月自动恢复/)
})

it('不限额（quota=0）不渲染', async () => {
  mocks.apiRequest.mockResolvedValue(quota({ quota_monthly: 0, unlimited: true, used: 5, remaining: 0, remaining_pct: null }))
  const { container } = render(<QuotaMeter />)
  await new Promise((resolve) => setTimeout(resolve, 10))
  expect(container).toBeEmptyDOMElement()
})

it('加载失败静默隐藏（辅助信息不阻断主内容）', async () => {
  mocks.apiRequest.mockRejectedValue(new Error('network down'))
  const { container } = render(<QuotaMeter />)
  await new Promise((resolve) => setTimeout(resolve, 10))
  expect(container).toBeEmptyDOMElement()
})
