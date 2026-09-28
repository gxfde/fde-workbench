import { expect, it } from 'vitest'
import { isDocumentListDto } from '../../src/renderer/src/documents/runtimeValidation'
import { DOCUMENT_TYPE_LABELS } from '../../src/renderer/src/documents/types'

it('accepts research results alongside SOW files without rejecting the list', () => {
  const item = { id: '1', project_id: 'p', business_code: 'RESEARCH_RESULT-1',
    created_at: '2026-09-10', status: 'draft', version: 1,
    current_version_id: null, current_version: null }
  expect(isDocumentListDto({ items: [
    { ...item, document_type: 'research_result' },
    { ...item, id: '2', document_type: 'sow' },
  ] })).toBe(true)
  expect(DOCUMENT_TYPE_LABELS.research_result).toBe('调研结果')
  expect(isDocumentListDto({ items: [{ ...item, document_type: 'unknown' }] })).toBe(false)
})
