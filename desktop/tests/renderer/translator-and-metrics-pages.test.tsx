// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import React from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }))
vi.mock('../../src/renderer/src/auth/AuthProvider', () => ({ useAuth: () => mocks }))

import { MetricsReportPage } from '../../src/renderer/src/metrics/MetricsReportPage'
import { TranslatorPortalPage } from '../../src/renderer/src/translator/TranslatorPortalPage'

beforeEach(() => { mocks.apiRequest.mockReset() })
afterEach(cleanup)

describe('翻译器门户（goal-d9 P3 全量）', () => {
  it('诉求为空时提交禁用（AI 只出草稿，提交需原话）', () => {
    render(<TranslatorPortalPage />)
    expect(screen.getByRole('heading', { name: '客户诉求翻译' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /提交 AI 翻译/ })).toBeDisabled()
    expect(screen.getByText('暂无拟问题清单。')).toBeInTheDocument()
  })

  it('本地预览徽标含 severity 预标与 module 待认领（打字期即时反馈保留）', () => {
    render(<TranslatorPortalPage />)
    expect(screen.queryAllByText('module=待认领')).toEqual([]) // 空表单无条目
    expect(screen.getByText(/填写客户诉求原话/)).toBeInTheDocument()
  })

  it('提交后轮询就绪：AI 草稿卡渲染问题清单与「待人工确认」徽标', async () => {
    const user = userEvent.setup()
    mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
      if (path === '/api/v1/translator/translations' && options?.method === 'POST') {
        return Promise.resolve({ data: { id: 't1', status: 'pending' } })
      }
      if (path === '/api/v1/translator/translations/t1') {
        return Promise.resolve({
          id: 't1', status: 'ready', ai_model: 'deepseek-v4-pro',
          failure_code: null, failure_message: null,
          result: {
            executive_summary: '先采集后分析。',
            key_business_problems: [
              { text: '仓库出入库缺少系统留痕', severity: 'high', module: 'wms', classification: 'customer_stated' },
            ],
            open_questions: [{ text: '验收基线未给出' }],
          },
        })
      }
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    render(<TranslatorPortalPage />)
    await user.type(screen.getByLabelText(/客户诉求原话/), '仓库出入库必须过系统留痕')
    await user.click(screen.getByRole('button', { name: /提交 AI 翻译/ }))
    expect(await screen.findByText('AI 草稿 · 待人工确认')).toBeInTheDocument()
    expect(screen.getByText(/仓库出入库缺少系统留痕/)).toBeInTheDocument()
    // 精确匹配：AI 结果徽标无（预标）后缀（本地预览卡另有 severity=high（预标））
    expect(screen.getByText('severity=high')).toBeInTheDocument()
    expect(screen.getByText('module=wms · 客户原话')).toBeInTheDocument()
  })

  it('轮询到失败态：失败码与消息透出（不静默）', async () => {
    const user = userEvent.setup()
    mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
      if (path === '/api/v1/translator/translations' && options?.method === 'POST') {
        return Promise.resolve({ data: { id: 't2', status: 'pending' } })
      }
      if (path === '/api/v1/translator/translations/t2') {
        return Promise.resolve({
          id: 't2', status: 'failed', ai_model: null,
          failure_code: 'ai_output_invalid',
          failure_message: 'AI 返回的项目指引格式不正确。（已自动重试 1 次仍失败，请重新发起翻译）',
          result: null,
        })
      }
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    render(<TranslatorPortalPage />)
    await user.type(screen.getByLabelText(/客户诉求原话/), '诉求')
    await user.click(screen.getByRole('button', { name: /提交 AI 翻译/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/ai_output_invalid/)
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
