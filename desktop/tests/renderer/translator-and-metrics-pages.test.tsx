// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import React from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }))
vi.mock('../../src/renderer/src/auth/AuthProvider', () => ({ useAuth: () => mocks }))

import { MetricsReportPage } from '../../src/renderer/src/metrics/MetricsReportPage'
import { PilotReportPage } from '../../src/renderer/src/pilot/PilotReportPage'
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
        return Promise.resolve({ id: 't1', status: 'pending' })
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
        return Promise.resolve({ id: 't2', status: 'pending' })
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

  it('采纳流（goal-d10）：ready 草稿选项目采纳 → POST adopt → 成功提示跳项目', async () => {
    const user = userEvent.setup()
    const adoptCalls: Array<{ path: string; body: unknown }> = []
    mocks.apiRequest.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects?page=1&page_size=50') {
        return Promise.resolve({ items: [{ id: 'p1', name: 'somwyn 交付' }], page: 1, page_size: 50, total: 1 })
      }
      if (path === '/api/v1/translator/translations' && options?.method === 'POST') {
        return Promise.resolve({ id: 't9', status: 'pending' })
      }
      if (path === '/api/v1/translator/translations/t9') {
        return Promise.resolve({
          id: 't9', status: 'ready', ai_model: 'deepseek-v4-pro',
          failure_code: null, failure_message: null,
          result: {
            executive_summary: '先采集后分析。',
            key_business_problems: [
              { text: '仓库出入库缺少系统留痕', severity: 'high', module: 'wms', classification: 'customer_stated' },
            ],
            open_questions: [],
          },
        })
      }
      if (path === '/api/v1/translator/translations/t9/adopt' && options?.method === 'POST') {
        adoptCalls.push({ path, body: options.body })
        return Promise.resolve({ id: 'g1', project_id: 'p1', status: 'draft', analysis_state: 'ready' })
      }
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    render(<TranslatorPortalPage />)
    await user.type(screen.getByLabelText(/客户诉求原话/), '仓库出入库必须过系统留痕')
    await user.click(screen.getByRole('button', { name: /提交 AI 翻译/ }))
    expect(await screen.findByText('AI 草稿 · 待人工确认')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '采纳到项目' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '采纳到项目' })).toBeDisabled() // 未选项目时禁用
    await screen.findByRole('option', { name: 'somwyn 交付' }) // 项目列表异步就绪
    await user.selectOptions(screen.getByLabelText('采纳到项目'), 'p1')
    await user.click(screen.getByRole('button', { name: '采纳到项目' }))
    expect(await screen.findByRole('status')).toHaveTextContent(/已采纳到项目「somwyn 交付」/)
    expect(screen.getByRole('link', { name: '打开项目' })).toHaveAttribute('href', '#/projects/p1')
    expect(adoptCalls).toHaveLength(1)
    expect(adoptCalls[0].body).toEqual({ project_id: 'p1' })
  })

  it('已采纳徽标（goal-d10 挂账 #1）：详情带 adopted_into 时渲染项目链接', async () => {
    mocks.apiRequest.mockImplementation((path: string, options?: { method?: string }) => {
      if (path === '/api/v1/translator/translations' && options?.method === 'POST') {
        return Promise.resolve({ id: 't7', status: 'pending' })
      }
      if (path === '/api/v1/translator/translations/t7') {
        return Promise.resolve({
          id: 't7', status: 'ready', ai_model: 'deepseek-v4-pro',
          failure_code: null, failure_message: null,
          adopted_into: [{ project_id: 'p9', analysis_id: 'g9' }],
          result: {
            executive_summary: '摘要',
            key_business_problems: [
              { text: '问题一', severity: 'low', module: 'wms', classification: 'customer_stated' },
            ],
            open_questions: [],
          },
        })
      }
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    render(<TranslatorPortalPage />)
    await userEvent.setup().type(screen.getByLabelText(/客户诉求原话/), '诉求')
    await userEvent.setup().click(screen.getByRole('button', { name: /提交 AI 翻译/ }))
    expect(await screen.findAllByRole('link', { name: '项目' })).toHaveLength(1)
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


describe('试点报告页（goal-d11）', () => {
  const report = {
    pilot: {
      enabled: true, active: true, started_at: '2026-11-01T00:00:00+00:00',
      expires_at: '2026-12-01T00:00:00+00:00', window_days: 30,
      runs_used: 5, runs_limit: 20, runs_remaining: 15, days_remaining: 29,
      exhausted: false,
    },
    metrics: {
      intercept_rate: 0.25, first_pass_rate: null,
      avg_meeting_cost_units: 0.75, degraded_rate: null,
      circuit_breaker_rate: 0.1, median_run_cost_units: 42,
    },
    stuck_inflight_runs: 1,
  }

  it('试点状态卡与六指标渲染；None 指标灰态「数据未积累」', async () => {
    mocks.apiRequest.mockResolvedValue(report)
    render(<PilotReportPage />)
    expect(await screen.findByText('进行中')).toBeInTheDocument()
    expect(screen.getByText('5 / 20（余 15）')).toBeInTheDocument()
    expect(screen.getByText('25.0%')).toBeInTheDocument() // intercept_rate
    expect(screen.getByText('42')).toBeInTheDocument() // median_run_cost_units
    const empty = screen.getAllByText('数据未积累')
    expect(empty.length).toBe(2) // first_pass_rate + degraded_rate
  })

  it('试点未启用时状态徽标与空态文案（不编造数值）', async () => {
    mocks.apiRequest.mockResolvedValue({ pilot: { enabled: false, active: false }, metrics: {}, stuck_inflight_runs: 0 })
    render(<PilotReportPage />)
    expect(await screen.findByText('未启用')).toBeInTheDocument()
    expect(screen.getByText(/试点窗口未配置/)).toBeInTheDocument()
  })
})