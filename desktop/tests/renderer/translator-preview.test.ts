import { describe, expect, it } from 'vitest'

import { buildTranslationPreview, type TranslatorFormState } from '../../src/renderer/src/translator/preview'

function form(overrides: Partial<TranslatorFormState> = {}): TranslatorFormState {
  return {
    industry: '装备制造',
    scale: '200 人',
    region: '苏州',
    interview_mode: 'onsite',
    customer_vision: '',
    phase_objective: '',
    ...overrides,
  }
}

describe('翻译器骨架实时预览映射（goal-d8，纯前端只读）', () => {
  it('空诉求：draft_problems 为空 + 引导 hint', () => {
    const preview = buildTranslationPreview(form())
    expect(preview.draft_problems).toEqual([])
    expect(preview.hints.length).toBeGreaterThan(0)
    expect(preview.profile).toEqual({ industry: '装备制造', scale: '200 人', region: '苏州', interview_mode: 'onsite' })
  })

  it('按句读切分诉求原话为拟问题清单（≤8 条）', () => {
    const vision = '仓库出入库必须过系统留痕。管理层看不到实时良率；明年要过客户审计！良率报表手工整理'
    const preview = buildTranslationPreview(form({ customer_vision: vision, phase_objective: '诊断' }))
    expect(preview.draft_problems.map((p) => p.text)).toEqual([
      '仓库出入库必须过系统留痕',
      '管理层看不到实时良率',
      '明年要过客户审计',
      '良率报表手工整理',
    ])
  })

  it('高危词触发 severity=high 预标；其余待确认且 module 一律待认领', () => {
    const preview = buildTranslationPreview(
      form({ customer_vision: '出入库必须过系统留痕。报表手工整理' }),
    )
    expect(preview.draft_problems[0]).toMatchObject({ severity: 'high', module: null, tentative: false })
    expect(preview.draft_problems[1]).toMatchObject({ severity: null, module: null, tentative: true })
  })

  it('超长诉求截取前 8 条并提示截断', () => {
    const vision = Array.from({ length: 10 }, (_, i) => `诉求点${i}需要处理`).join('。')
    const preview = buildTranslationPreview(form({ customer_vision: vision }))
    expect(preview.draft_problems).toHaveLength(8)
    expect(preview.hints.some((hint) => hint.includes('前 8 条'))).toBe(true)
  })
})
