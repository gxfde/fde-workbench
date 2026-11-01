import { useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'

// O-3 配额快照（goal-d7）：/api/v1/agents/quota 的 data 载荷
interface SeatQuota {
  quota_monthly: number
  unlimited: boolean
  used: number
  remaining: number
  remaining_pct: number | null
  over_quota: boolean
  warn_low_remaining: boolean
  pack: { price_yuan: number; unit: string; note: string }
}

function isSeatQuota(value: unknown): value is SeatQuota {
  if (!value || typeof value !== 'object') return false
  const item = value as Record<string, unknown>
  return typeof item.quota_monthly === 'number' && typeof item.used === 'number'
    && typeof item.unlimited === 'boolean' && typeof item.over_quota === 'boolean'
    && typeof item.warn_low_remaining === 'boolean'
    && (!!item.pack && typeof (item.pack as Record<string, unknown>).price_yuan === 'number')
}

// 额度透明化（O-3 硬规则，自动交付 §6）：每次动作后可见消耗（如 37/100）、
// 余量 ≤20% 提醒、用尽显示加油包计价入口（绝不断供——超额只是标注与入口，
// 平台永不静默断供）。加载失败静默隐藏（辅助信息不阻断主内容）。
export function QuotaMeter() {
  const { apiRequest } = useAuth()
  const [quota, setQuota] = useState<SeatQuota | null>(null)
  useEffect(() => {
    let active = true
    void apiRequest<unknown>('/api/v1/agents/quota', { method: 'GET' })
      .then((value) => {
        if (active && isSeatQuota(value)) setQuota(value)
      })
      .catch(() => {})
    return () => { active = false }
  }, [apiRequest])
  if (!quota || quota.unlimited) return null
  if (quota.over_quota) {
    return <span className="badge warning seat-quota" title={`本月 ${quota.used}/${quota.quota_monthly} 次动作已用尽；次月自动恢复。${quota.pack.note}`}>额度已用尽 · 加油包 ¥{quota.pack.price_yuan}/次</span>
  }
  if (quota.warn_low_remaining) {
    return <span className="badge warning seat-quota" title={`本月已用 ${quota.used}/${quota.quota_monthly} 次动作，余量 ${quota.remaining_pct}%（≤20% 提醒）。${quota.pack.note}`}>{quota.used}/{quota.quota_monthly} 次动作 · 余量不足</span>
  }
  return <span className="badge muted seat-quota" title="工作台动作消耗透明显示（O-3）：一次动作 = 一次方案生成 / 一场评审会 / 一次问题清单分析">{quota.used}/{quota.quota_monthly} 次动作</span>
}
