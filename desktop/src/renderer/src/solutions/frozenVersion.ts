/**
 * T-A7（谈判版本管理）：方案版本 ↔ SOW 冻结状态的桌面关联。
 *
 * 拍板口径（backlog §拍板闸 6③）：复用既有 solution 版本行——谈判稿=未冻结版本，
 * 最终 SOW 只认冻结版本，桌面把未冻结版本标注为「谈判稿」；零新表零迁移零新 API。
 *
 * 数据源（实测 draft_service._serialize_document_summary）：项目文档列表摘要自带
 * `opportunity_scope.solution.{id,version}`——export_sow 每次导出都把它更新为
 * 导出时刻的方案版本（solutions/service.py 的 scope = {...deepcopy(frozen)}）。
 * 因此无需任何新端点即可反查「该方案最新冻结进 SOW 的版本号」。
 */

/** 项目文档列表摘要中与本功能相关的最小字段（scope 形态对齐 DocumentSummaryDto.opportunity_scope）。 */
export interface DocumentScopeRef {
  document_type: string
  status: string
  opportunity_scope?: {
    solution?: { id?: string; version?: number } | null
    opportunities?: Array<{ source_opportunity_id: string; opportunity_name: string; opportunity_tracking_code: string; version: number }>
    instructions?: string
  } | null
}

/**
 * 该方案最新一次冻结进 SOW 的方案版本号；从未导出过返回 null。
 *
 * 含 archived 文档——弃用的 SOW 快照仍是历史冻结事实（「历史文件保留」）。
 * 同一方案可能有多份 SOW 文档（旧文档弃用后走新文档），取最大版本号。
 */
export function frozenSolutionVersion(documents: DocumentScopeRef[], solutionId: string): number | null {
  let frozen: number | null = null
  for (const document of documents) {
    if (document.document_type !== 'sow') continue
    const version = document.opportunity_scope?.solution?.version
    if (document.opportunity_scope?.solution?.id !== solutionId || typeof version !== 'number' || version < 1) continue
    if (frozen === null || version > frozen) frozen = version
  }
  return frozen
}

export interface VersionBadge {
  label: string
  className: string
  title: string
}

/**
 * 方案当前版本的冻结状态徽标（拍板口径：未冻结版本 = 谈判稿）。
 * - 当前版本 == 最新冻结版本 → 「已冻结进 SOW」
 * - 冻结过且当前版本更新（导出后又改过）→ 「谈判稿 · vN 后已修改」
 * - 从未导出 → 「谈判稿 · 未导出」
 */
export function solutionVersionBadge(solutionVersion: number, frozenVersion: number | null): VersionBadge {
  if (frozenVersion !== null && frozenVersion === solutionVersion) {
    return { label: '已冻结进 SOW', className: 'success', title: `当前方案版本 v${solutionVersion} 的内容已冻结进 SOW 快照；再次导出前修改方案会前进到新版本。` }
  }
  if (frozenVersion !== null && solutionVersion > frozenVersion) {
    return { label: '谈判稿 · 已修改', className: 'warning', title: `方案在 v${frozenVersion} 冻结进 SOW 后又修改过（当前 v${solutionVersion}）——当前内容尚未进入任何 SOW；导出将以当前内容生成新快照。` }
  }
  return { label: '谈判稿 · 未导出', className: 'muted', title: '当前方案内容尚未冻结进任何 SOW；导出 SOW 时将以当前内容生成不可变快照。' }
}
