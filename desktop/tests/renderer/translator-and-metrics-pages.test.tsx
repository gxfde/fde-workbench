// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import React from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }))
vi.mock('../../src/renderer/src/auth/AuthProvider', () => ({ useAuth: () => mocks }))

import { MetricsReportPage } from '../../src/renderer/src/metrics/MetricsReportPage'
import { TranslatorPortalPage } from '../../src/renderer/src/translator/TranslatorPortalPage'

beforeEach(() => { mocks.apiRequest.mockReset() })
afterEach(cleanup)

describe('翻译器门户骨架页（goal-d8）', () => {
  it('渲染引导式表单与骨架徽标，提交入口显式禁用（不落库）', () => {
    render(<TranslatorPortalPage />)
    expect(screen.getByRole('heading', { name: '客户诉求翻译（骨架版）' })).toBeInTheDocument()
    expect(screen.getByText('P3 骨架 · 只读预览')).toBeInTheDocument()
    const submit = screen.getByRole('button', { name: /提交翻译/ })
    expect(submit).toBeDisabled()
    expect(screen.getByText('暂无拟问题清单。')).toBeInTheDocument()
  })

  it('预览徽标含 severity 预标与 module 待认领（只读口径可见）', () => {
    render(<TranslatorPortalPage />)
    expect(screen.queryAllByText('module=待认领')).toEqual([]) // 空表单无条目
    expect(screen.getByText(/填写客户诉求原话/)).toBeInTheDocument()
  })
})

describe('P0/P1 指标报表页（goal-d8）', () => {
  const report = {
    generated_at: '2026-11-01T08:00:00+00:00',
    sections: {
      p0: [
        { key: 'presurvey_confirm_rate', label: '售前独立完成录入+确认率', value: 0.9, sample_size: 10, definition: '确认口径', target: 0.9, status: 'ok' },
        { key: 'sow_first_pass_rate', label: 'SOW 一次拍板通过率', value: null, sample_size: 0, definition: '拍板埋点未落', target: 0.7, status: 'insufficient_data' },
      ],
      p1_pilot: [
        { key: 'lite_meeting_share', label: 'lite 档会议占比', value: 1, sample_size: 4, definition: 'lite/总数', target: 1, status: 'ok' },
      ],
      ongoing: [
        { key: 'seat_actions_month', label: '当月工作台动作数', value: 42, sample_size: 42, definition: 'O-3 台账', status: 'ok', detail: { over_quota_rows: 2 } },
      ],
    },
  }

  it('正常渲染三个分区指标卡与目标值', async () => {
    mocks.apiRequest.mockResolvedValue(report)
    render(<MetricsReportPage />)
    expect(await screen.findByText('P0 售前规模化 MVP 指标')).toBeInTheDocument()
    expect(screen.getByText('90.0% · 目标 ≥90%')).toBeInTheDocument()
    expect(screen.getByText('100.0% · 目标 100%')).toBeInTheDocument()
    expect(screen.getByText('样本 42 · 超额标注 2 行')).toBeInTheDocument()
  })

  it('样本不足指标灰态显示「数据未积累」（不编造数值）', async () => {
    mocks.apiRequest.mockResolvedValue(report)
    render(<MetricsReportPage />)
    const insufficient = await screen.findByText('数据未积累')
    expect(insufficient).toBeInTheDocument()
    const card = insufficient.closest('[data-metric]')
    expect(card?.getAttribute('data-metric')).toBe('sow_first_pass_rate')
    expect(card?.className).toContain('metric-insufficient')
  })

  it('加载失败显示错误态', async () => {
    mocks.apiRequest.mockRejectedValue(new Error('down'))
    render(<MetricsReportPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/无法加载指标报表/)
  })
})
