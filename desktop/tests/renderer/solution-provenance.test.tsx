// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import React from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { SolutionProvenanceBadge } from '../../src/renderer/src/solutions/SolutionDetailPage'
import { emptySolution } from '../../src/renderer/src/solutions/types'
import type { SolutionDto } from '../../src/renderer/src/solutions/types'

function solution(overrides: Partial<SolutionDto> = {}): SolutionDto {
  return { ...emptySolution(), id: 's1', project_id: 'p', name: '方案', opportunity_ids: ['opp1'], opportunities: [], version: 1, status: 'active', updated_at: '2026-11-01T00:00:00Z', ...overrides }
}

afterEach(cleanup)

it('human 生成不渲染徽标', () => {
  const { container } = render(<SolutionProvenanceBadge solution={solution({ generated_by: 'human' })} />)
  expect(container).toBeEmptyDOMElement()
})

it('agent 生成渲染常显徽标', () => {
  render(<SolutionProvenanceBadge solution={solution({ generated_by: 'agent', agent_run_id: 'run-1' })} />)
  const badge = screen.getByText('智能体生成')
  expect(badge).toHaveClass('solution-provenance')
  expect(badge).not.toHaveClass('warning')
  expect(badge).toHaveAccessibleDescription(/溯源/)
})

it('降级 agent 生成渲染 warning 徽标（V11：降级必须可见）', () => {
  render(<SolutionProvenanceBadge solution={solution({ generated_by: 'agent', agent_run_id: 'run-1', agent_degraded: true, agent_fallback_level: 'L1' })} />)
  const badge = screen.getByText('智能体生成 · 已降级')
  expect(badge).toHaveClass('warning')
  expect(badge).toHaveAccessibleDescription(/人工终审/)
})

it('缺 agent_run_id 的 agent 标记不渲染徽标（数据不完整即不展示）', () => {
  const { container } = render(<SolutionProvenanceBadge solution={solution({ generated_by: 'agent' })} />)
  expect(container).toBeEmptyDOMElement()
})
