import { useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { DocumentVersionTimeline, versionCanDownload } from '../documents/DocumentVersionTimeline'
import type { DocumentSummaryDto, DocumentVersionSummary } from '../documents/types'
import { solutionError } from './solutionErrors'

export interface SolutionExportResult {
  document_id: string
  document_version_id: string
  document: DocumentSummaryDto
  generation?: ExportVersion | null
}

type ExportVersion = DocumentVersionSummary & { generation_status?: string | null; generation_message?: string }

export function SolutionExport({ projectId, result, name, retrying = false, requestError = '', onRetry, onClose }: { projectId: string; result: SolutionExportResult; name: string; retrying?: boolean; requestError?: string; onRetry(): void; onClose(): void }) {
  const { apiRequest } = useAuth()
  const [target, setTarget] = useState<ExportVersion | null>(() => {
    if (result.generation?.id === result.document_version_id) return result.generation
    if (result.document.current_version?.id === result.document_version_id) return { ...result.document.current_version, generation_status: result.document.generation_status }
    return null
  })
  const [error, setError] = useState('')
  const [timeline, setTimeline] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const ready = Boolean(target && versionCanDownload(target))
  const failed = !ready && ['failed', 'cancelled'].includes(target?.generation_status ?? '')
  useEffect(() => {
    if (ready || failed) return
    let active = true
    const load = async () => {
      try {
        // Follow the immutable requested version, never another user's newer export.
        const next = await apiRequest<{ items: ExportVersion[] }>(`/api/v1/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(result.document_id)}/versions`, { method: 'GET' })
        const current = next.items.find(item => item.id === result.document_version_id)
        if (active && current) { setTarget(current); setError('') }
      } catch (caught) { if (active) setError(solutionError(caught)) }
    }
    void load()
    const timer = window.setInterval(() => { void load() }, 2000)
    return () => { active = false; window.clearInterval(timer) }
  }, [apiRequest, projectId, result.document_id, result.document_version_id, ready, failed])
  async function download() {
    setDownloading(true); setError('')
    try {
      const next = await apiRequest<{ url: string }>(`/api/v1/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(result.document_version_id)}/download-url`, { method: 'GET' })
      const url = new URL(next.url)
      if (!['https:', 'http:'].includes(url.protocol)) throw new Error('invalid download url')
      const anchor = window.document.createElement('a')
      anchor.href = url.href; anchor.download = `${name}-SOW.docx`
      window.document.body.appendChild(anchor); anchor.click(); anchor.remove()
    } catch (caught) { setError(solutionError(caught)) }
    finally { setDownloading(false) }
  }
  return <><div className="dialog-backdrop"><section className="dialog solution-export-dialog" role="dialog" aria-modal="true" aria-label="导出 SOW">
    <div className="dialog-heading"><h2>导出 SOW</h2><button className="secondary-button compact" type="button" onClick={onClose}>关闭</button></div>
    <p>{name}</p><p className="field-hint">以已保存方案的当前版本生成。后续修改方案不会覆盖这份 SOW；生成的文件也会保存在文件库中。</p>
    <p role="status">{ready ? 'SOW 已生成，可以下载。' : failed ? 'SOW 生成未完成，已保留方案和文档记录。' : '正在生成 SOW，可以关闭窗口，稍后从 SOW 文件查看结果。'}</p>
    {error || requestError ? <p role="alert" className="form-error">{error || requestError}</p> : null}
    <div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => setTimeline(true)}>查看版本</button>{failed ? <button type="button" className="primary-button" disabled={retrying} onClick={onRetry}>{retrying ? '重新提交中…' : '重试导出'}</button> : <button type="button" className="primary-button" disabled={!ready || downloading} onClick={() => void download()}>{downloading ? '准备下载…' : '下载 SOW'}</button>}</div>
  </section></div>{timeline ? <DocumentVersionTimeline projectId={projectId} documentId={result.document_id} title={`${name} · SOW`} onClose={() => setTimeline(false)} /> : null}</>
}
