import { useCallback, useEffect, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"

// V3 T-W6 Skill 版本治理视图（域 8 消费面）：版本历史 + 效果统计（T-S2 usage 块）
// + 治理动作（提交评审/发布/回滚/弃用）。四闸语义在服务层（密码确认、材料闸、
// admin 闸）——控制台诚实呈现 403/409，不本地放行。

export interface SkillVersionsSkill {
  id: string
  key: string
  name: string
  scope: string
  status: string
  current_version: number
  can_edit: boolean
}

interface SkillVersionRow {
  version: number
  content_sha256: string
  created_at: string | null
  has_test_report: boolean
  is_current: boolean
}

interface SkillUsageDto {
  total: number
  chat: number
  workflow: number
  last_used_at: string | null
  by_version: Record<string, number>
  truncated: boolean
}

interface VersionsDto {
  skill: SkillVersionsSkill
  versions: SkillVersionRow[]
  usage: SkillUsageDto
}

const SKILL_STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  in_review: "评审中",
  published: "已发布",
  deprecated: "已弃用",
  disabled: "已停用",
}

type LifecycleAction = "publish" | "rollback"

function actionMessage(caught: unknown): string {
  if (caught instanceof ApiClientError) return caught.message
  if (caught instanceof Error) return caught.message
  return "操作失败，请重试。"
}

interface SkillVersionsPageProps {
  skill: Pick<SkillVersionsSkill, "id" | "name">
  onClose: () => void
  onChanged: () => void | Promise<void>
}

export function SkillVersionsPage({ skill, onClose, onChanged }: SkillVersionsPageProps) {
  const { apiRequest } = useAuth()
  const [data, setData] = useState<VersionsDto | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [actionError, setActionError] = useState("")
  const [busy, setBusy] = useState(false)
  const [action, setAction] = useState<LifecycleAction | null>(null)
  const [password, setPassword] = useState("")
  const [waiveReason, setWaiveReason] = useState("")
  const [rollbackVersion, setRollbackVersion] = useState("")

  const load = useCallback(async (): Promise<void> => {
    setError("")
    try {
      const versions = await apiRequest<VersionsDto>(
        `/api/v1/extensions/skills/${encodeURIComponent(skill.id)}/versions`,
        { method: "GET" },
      )
      setData(versions)
    } catch (caught) {
      setError(actionMessage(caught))
    }
  }, [apiRequest, skill.id])

  useEffect(() => {
    let active = true
    setLoading(true)
    void load().finally(() => {
      if (active) setLoading(false)
    })
    return () => {
      active = false
    }
  }, [load])

  function onKey(event: KeyboardEvent): void {
    if (event.key === "Escape" && !busy) onClose()
  }
  useEffect(() => {
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy])

  function resetAction(): void {
    setAction(null)
    setPassword("")
    setWaiveReason("")
    setRollbackVersion("")
  }

  async function submitReview(): Promise<void> {
    setActionError("")
    setBusy(true)
    try {
      await apiRequest(`/api/v1/extensions/skills/${encodeURIComponent(skill.id)}/submit-review`, {
        method: "POST",
        body: {},
      })
      resetAction()
      await load()
      await onChanged()
    } catch (caught) {
      setActionError(actionMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  async function deprecate(): Promise<void> {
    setActionError("")
    setBusy(true)
    try {
      await apiRequest(`/api/v1/extensions/skills/${encodeURIComponent(skill.id)}/deprecate`, {
        method: "POST",
        body: {},
      })
      resetAction()
      await load()
      await onChanged()
    } catch (caught) {
      setActionError(actionMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  async function runLifecycle(): Promise<void> {
    if (!action) return
    if (!password) {
      setActionError("密码确认必填。")
      return
    }
    if (action === "rollback" && !rollbackVersion) {
      setActionError("请选择回滚目标版本。")
      return
    }
    setActionError("")
    setBusy(true)
    try {
      const body: Record<string, unknown> =
        action === "publish"
          ? { password }
          : { password, version: Number(rollbackVersion) }
      const waive = waiveReason.trim()
      if (waive) body.waive_reason = waive
      await apiRequest(
        `/api/v1/extensions/skills/${encodeURIComponent(skill.id)}/${action}`,
        { method: "POST", body },
      )
      resetAction()
      await load()
      await onChanged()
    } catch (caught) {
      setActionError(actionMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const current = data?.skill.status
  const lifecycleTarget: LifecycleAction | null =
    current === "in_review" ? "publish" : current === "published" ? "rollback" : null

  return (
    <div className="dialog-backdrop">
      <section className="dialog extension-dialog" role="dialog" aria-modal="true" aria-labelledby="skill-versions-title">
        <h2 id="skill-versions-title">版本治理 · {skill.name}</h2>
        {loading ? <p className="empty-copy" role="status">正在加载版本…</p> : null}
        {error ? <p className="empty-copy" role="alert">{error}</p> : null}
        {data ? (
          <div className="page-stack">
            <p>
              <span className={`extension-scope ${data.skill.scope === "public" ? "public" : ""}`}>
                {data.skill.scope === "public" ? "公共" : "个人"}
              </span>{" "}
              <code>{data.skill.key}</code> · 当前 v{data.skill.current_version} ·{" "}
              {SKILL_STATUS_LABEL[data.skill.status] ?? data.skill.status}
            </p>

            <section aria-label="效果统计">
              <h3>效果统计</h3>
              <p>
                累计消费 <strong>{data.usage.total}</strong> 次（聊天 {data.usage.chat} · 工作流 {data.usage.workflow}）
                {data.usage.last_used_at ? ` · 最近 ${data.usage.last_used_at.slice(0, 19).replace("T", " ")}` : " · 从未被消费"}
              </p>
              <p>
                <small>
                  按版本：
                  {Object.keys(data.usage.by_version).length
                    ? Object.entries(data.usage.by_version)
                        .map(([version, count]) => `v${version} ×${count}`)
                        .join("，")
                    : "—"}
                </small>
              </p>
              {data.usage.truncated ? (
                <p><small>统计仅覆盖最近 1000 条消费事件。</small></p>
              ) : null}
            </section>

            <section aria-label="版本历史">
              <h3>版本历史</h3>
              {data.versions.length ? (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th scope="col">版本</th>
                      <th scope="col">指纹</th>
                      <th scope="col">测试报告</th>
                      <th scope="col">创建时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.versions.map((row) => (
                      <tr key={row.version}>
                        <td>
                          v{row.version}
                          {row.is_current ? <strong>（当前）</strong> : null}
                        </td>
                        <td><code>{row.content_sha256.slice(0, 12)}</code></td>
                        <td>{row.has_test_report ? "有" : "无"}</td>
                        <td>{row.created_at ? row.created_at.slice(0, 19).replace("T", " ") : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="empty-copy">还没有版本。</p>
              )}
            </section>

            {actionError ? <p role="alert" className="empty-copy">{actionError}</p> : null}

            {data.skill.can_edit ? (
              <div className="plugin-actions">
                {current === "draft" ? (
                  <button className="primary-button" disabled={busy} onClick={() => void submitReview()}>
                    提交评审
                  </button>
                ) : null}
                {lifecycleTarget ? (
                  <button
                    className="secondary-button"
                    disabled={busy}
                    onClick={() => (action === lifecycleTarget ? resetAction() : setAction(lifecycleTarget))}
                  >
                    {action === lifecycleTarget ? "收起表单" : lifecycleTarget === "publish" ? "发布" : "回滚"}
                  </button>
                ) : null}
                {current === "published" ? (
                  <button className="secondary-button" disabled={busy} onClick={() => void deprecate()}>
                    弃用
                  </button>
                ) : null}
                {current === "deprecated" ? <small>已弃用；复活=重新编辑走治理。</small> : null}
              </div>
            ) : (
              <p className="empty-copy">只有公共 Skill 运维员或个人 Skill 属主可以执行治理动作。</p>
            )}

            {action ? (
              <form
                aria-label={action === "publish" ? "发布确认" : "回滚确认"}
                onSubmit={(event) => {
                  event.preventDefault()
                  void runLifecycle()
                }}
              >
                <div className="skill-editor">
                  {action === "rollback" ? (
                    <label className="field">
                      <span>回滚目标版本</span>
                      <select
                        aria-label="回滚目标版本"
                        value={rollbackVersion}
                        onChange={(event) => setRollbackVersion(event.target.value)}
                      >
                        <option value="">选择版本</option>
                        {data.versions
                          .filter((row) => row.version !== data.skill.current_version)
                          .map((row) => (
                            <option key={row.version} value={String(row.version)}>
                              v{row.version}
                            </option>
                          ))}
                      </select>
                    </label>
                  ) : null}
                  <label className="field">
                    <span>密码确认（当前账号密码）</span>
                    <input
                      type="password"
                      aria-label="密码确认"
                      autoComplete="current-password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                    />
                  </label>
                  <label className="field full">
                    <span>豁免说明（无测试报告时必填）</span>
                    <input
                      aria-label="豁免说明"
                      value={waiveReason}
                      onChange={(event) => setWaiveReason(event.target.value)}
                    />
                  </label>
                </div>
                <div className="dialog-actions">
                  <button className="secondary-button" type="button" disabled={busy} onClick={resetAction}>
                    取消
                  </button>
                  <button className="primary-button" type="submit" disabled={busy}>
                    {action === "publish" ? "确认发布" : "确认回滚"}
                  </button>
                </div>
              </form>
            ) : null}
          </div>
        ) : null}

        <div className="dialog-actions">
          <button className="secondary-button" disabled={busy} onClick={onClose}>
            关闭
          </button>
        </div>
      </section>
    </div>
  )
}
