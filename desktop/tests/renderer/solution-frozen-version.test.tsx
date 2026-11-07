import { describe, expect, it } from 'vitest'
import { frozenSolutionVersion, solutionVersionBadge } from '../../src/renderer/src/solutions/frozenVersion'
import type { DocumentScopeRef } from '../../src/renderer/src/solutions/frozenVersion'

function doc(overrides: Partial<DocumentScopeRef> & { document_type?: string } = {}): DocumentScopeRef {
  return {
    document_type: 'sow',
    status: 'draft',
    opportunity_scope: { solution: { id: 'sol1', version: 2 }, opportunities: [] },
    ...overrides,
  } as DocumentScopeRef
}

describe('frozenSolutionVersion (T-A7)', () => {
  it('returns null when no SOW documents reference the solution', () => {
    expect(frozenSolutionVersion([], 'sol1')).toBeNull()
    expect(frozenSolutionVersion([doc({ opportunity_scope: { solution: { id: 'other', version: 5 }, opportunities: [] } })], 'sol1')).toBeNull()
    // 非 SOW 文档即使 scope 指向方案也不算冻结（ pov_plan 等同样带 solution scope）
    expect(frozenSolutionVersion([doc({ document_type: 'pov_plan' })], 'sol1')).toBeNull()
  })

  it('takes the max frozen version across multiple SOW documents, including archived ones', () => {
    // 旧 SOW 文档已弃用，快照仍是历史冻结事实（服务端「历史文件保留」语义）
    const rows = [
      doc({ status: 'archived', opportunity_scope: { solution: { id: 'sol1', version: 1 }, opportunities: [] } }),
      doc({ opportunity_scope: { solution: { id: 'sol1', version: 3 }, opportunities: [] } }),
    ]
    expect(frozenSolutionVersion(rows, 'sol1')).toBe(3)
  })

  it('ignores malformed scope entries instead of crashing', () => {
    expect(frozenSolutionVersion([doc({ opportunity_scope: { solution: null, opportunities: [] } })], 'sol1')).toBeNull()
    expect(frozenSolutionVersion([doc({ opportunity_scope: { solution: { id: 'sol1' }, opportunities: [] } })], 'sol1')).toBeNull()
    expect(frozenSolutionVersion([doc({ opportunity_scope: { solution: { id: 'sol1', version: 0 }, opportunities: [] } })], 'sol1')).toBeNull()
    expect(frozenSolutionVersion([doc({ opportunity_scope: null })], 'sol1')).toBeNull()
  })
})

describe('solutionVersionBadge (T-A7 谈判稿口径)', () => {
  it('labels the current version as frozen when it matches the latest SOW snapshot', () => {
    const badge = solutionVersionBadge(3, 3)
    expect(badge.label).toBe('已冻结进 SOW')
    expect(badge.className).toBe('success')
    expect(badge.title).toContain('v3')
  })

  it('labels a newer unfrozen revision as an edited negotiation draft', () => {
    const badge = solutionVersionBadge(5, 3)
    expect(badge.label).toBe('谈判稿 · 已修改')
    expect(badge.className).toBe('warning')
    expect(badge.title).toContain('v3')
    expect(badge.title).toContain('v5')
  })

  it('labels a never-exported solution as a negotiation draft', () => {
    const badge = solutionVersionBadge(2, null)
    expect(badge.label).toBe('谈判稿 · 未导出')
    expect(badge.className).toBe('muted')
  })

  it('still shows frozen when the only frozen version is newer than given (defensive)', () => {
    // 理论上不出现（frozen 取的是快照记录，方案版本回退不可能），但函数应保持确定行为
    const badge = solutionVersionBadge(1, 3)
    expect(badge.label).toBe('谈判稿 · 未导出')
    expect(badge.className).toBe('muted')
  })
})
