import { ApiClientError } from '../api/client'

export function solutionError(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (['stale_version', 'version_conflict'].includes(error.code)) return '方案已被其他操作更新。请先保留当前修改，再返回方案详情重新加载最新版本后修改或导出。'
    if (error.code === 'invalid_password') return '当前账号密码错误，请重新输入。'
    if (error.code === 'forbidden') return '当前账号没有执行此操作的权限。'
    if (['authentication_required', 'authentication_refreshed_resubmit'].includes(error.code)) return '登录状态已更新，请重新提交本次操作。'
    if (['solution_not_found', 'opportunity_not_found'].includes(error.code)) return '方案或关联机会已发生变化，请重新进入方案设计。'
    if (error.code === 'solution_archived') return '此方案已弃用，不能继续编辑或生成文档。'
    if (error.code === 'solution_export_archived') return '这一版方案对应的 SOW 已弃用。可在 SOW 文件中查看或恢复；需要新 SOW 时，请先编辑并保存新的方案版本。'
    if (error.code === 'solution_design_required') return '请先填写并保存方案设计，再导出 SOW。'
    if (error.code === 'invalid_opportunities') return '关联机会已发生变化。请选择本项目的有效机会，最多可关联 100 个。'
    if (['solution_template_upgrade_required', 'solution_template_unavailable'].includes(error.code)) return '当前 SOW 模板尚未支持方案设计或不可用。请管理员发布新版 SOW 模板后再导出，已保存方案不受影响。'
    if (['ai_unavailable', 'ai_generation_failed', 'ai_service_unavailable'].includes(error.code)) return 'AI 整理暂时未成功。已填写内容仍保留，可以重试或手动完善。'
  }
  return '操作未完成，请稍后重试。当前填写内容不会自动丢失。'
}
