export type LcscVariant = 'lcsc-browser-baseline' | 'lcsc-browser-jev'
export const resultFields = { parameters: '元器件参数', pins: '引脚数', price: '售价', datasheet: '下载规格书', other: '其他' } as const
export type ResultField = keyof typeof resultFields
export type Cost = { cny_estimate?: string | null; note?: string; usd_cny_rate?: string; fx_date?: string; price_source?: string }
export type Usage = { input_tokens?: number | null; output_tokens?: number | null }
export type Product = { title: string; url: string; visible_text: string }
export interface LcscRun {
  id: string; skill_key: LcscVariant; query: string; status: string; error_code: string; browser_url: string; duration_ms: number; started_at: string
  steps: Array<{ at_ms: number; duration_ms?: number; action: string; detail: string; model?: string; status?: string; usage?: Usage; cost?: Cost }>
  candidates: Product[]; models: Array<{ provider: string; model: string }>; usage: Usage; cost: Cost
  result: {
    workflow?: string; fields?: ResultField[]; track?: boolean; candidate_hash?: string; model_duration_ms?: number; purpose?: string
    selected_product?: Product | null; selection?: { reason?: string; confidence?: number; selection?: string }; client_error?: string
    details?: { parameters?: Array<{name: string; value: string}>; prices?: Array<{quantity: string; price: string; source: string}>
      pins?: { count: number; items: Array<{number: string; name: string}>; source: string; screenshot?: string }
      other?: { text?: string; url?: string; purpose: string; complete?: boolean; reason?: string; items?: Array<{goal:string;answer:string;status:string;reason:string;evidence?:{text:string;url:string}|null}> }
      datasheet?: {name: string; url: string; filename: string; status: string}; missing?: string[] }
  }
}
export const variantName = (variant: LcscVariant) => variant === 'lcsc-browser-jev' ? 'Jev 版' : '默认模型版'

export function LcscToolCard({ variant }: { variant: LcscVariant }) {
  return <article className="extension-item lcsc-tool-card">
    <div className="lcsc-tool-heading"><div><strong>立创商城元器件查询 · {variantName(variant)}</strong><p>{variant === 'lcsc-browser-jev' ? 'Jev 判断候选、证据和可用浏览器动作；默认模型回答并在需要时重新规划。' : '用当前默认模型判断候选元器件，按相同流程查询和下载，作为 Jev 的对照组。'}</p></div></div>
    <div className="lcsc-card-footer"><a className="primary-button lcsc-use-link" href={`#extensions/tools/${variant}`}>立即使用</a><span className="extension-scope">浏览器工具</span></div>
  </article>
}
