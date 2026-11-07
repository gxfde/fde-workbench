// V3.2 G2 模拟训练场 · 案例库。
//
// 只读列表 + 分类过滤 + 版本可见；写动作（新建/编辑/复制/归档/导入导出）全部
// 走服务端闸（can_write 由服务端判定，前端不做业务判定）。403/409 原样呈现。

import { useCallback, useEffect, useRef, useState, type ReactElement } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { AsyncButton, EmptyState, Loading, UiButton } from "../components/ui"
import {
  archiveScenario,
  createScenario,
  duplicateScenario,
  exportScenarios,
  listScenarios,
  updateScenario,
  type ScenarioWritePayload,
} from "./api"
import { ScenarioEditor } from "./ScenarioEditor"
import {
  SPLIT_LABEL,
  STATUS_LABEL,
  VARIANT_LABEL,
  type ScenarioDto,
  type ScenarioSplit,
  type ScenarioStatus,
  type ScenarioVariant,
} from "./types"

const VARIANT_OPTIONS: Array<{ value: ScenarioVariant | ""; label: string }> = [
  { value: "", label: "全部客户行为" },
  { value: "normal", label: VARIANT_LABEL.normal },
  { value: "vague", label: VARIANT_LABEL.vague },
  { value: "complex", label: VARIANT_LABEL.complex },
]

const SPLIT_OPTIONS: Array<{ value: ScenarioSplit | ""; label: string }> = [
  { value: "", label: "全部数据集" },
  { value: "train", label: SPLIT_LABEL.train },
  { value: "regression", label: SPLIT_LABEL.regression },
  { value: "blind", label: SPLIT_LABEL.blind },
]

const STATUS_OPTIONS: Array<{ value: ScenarioStatus | ""; label: string }> = [
  { value: "", label: "全部状态" },
  { value: "draft", label: STATUS_LABEL.draft },
  { value: "active", label: STATUS_LABEL.active },
  { value: "archived", label: STATUS_LABEL.archived },
]

function errorText(caught: unknown): string {
  if (caught instanceof ApiClientError) return caught.message
  if (caught instanceof Error) return caught.message
  return "操作失败，请稍后重试。"
}

export function ScenarioLibrary(): ReactElement {
  const { apiRequest } = useAuth()
  const [items, setItems] = useState<ScenarioDto[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [actionError, setActionError] = useState("")
  const [variant, setVariant] = useState<ScenarioVariant | "">("")
  const [split, setSplit] = useState<ScenarioSplit | "">("")
  const [status, setStatus] = useState<ScenarioStatus | "">("")
  const [keyword, setKeyword] = useState("")
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<ScenarioDto | null>(null)
  const sequence = useRef(0)
  const loadedOnce = useRef(false)

  const load = useCallback(async () => {
    const requestSequence = ++sequence.current
    try {
      const payload = await listScenarios(apiRequest, {
        variant: variant || undefined,
        split: split || undefined,
        status: status || undefined,
        q: keyword.trim() || undefined,
      })
      if (requestSequence !== sequence.current) return
      setItems(payload.items)
      setTotal(payload.total)
      setError("")
    } catch (caught) {
      if (requestSequence !== sequence.current) return
      setError(errorText(caught))
    } finally {
      if (requestSequence === sequence.current) {
        loadedOnce.current = true
        setLoading(false)
      }
    }
  }, [apiRequest, keyword, split, status, variant])

  useEffect(() => {
    let active = true
    void load().then(() => {
      if (!active) return
      setLoading(false)
    })
    return () => {
      active = false
      sequence.current += 1
    }
  }, [load])

  async function handleCreate(payload: ScenarioWritePayload): Promise<void> {
    const created = await createScenario(apiRequest, payload)
    setEditorOpen(false)
    setEditing(null)
    await load()
    setActionError(`已创建场景「${created.name}」（版本 ${created.version}）。`)
  }

  async function handleUpdate(payload: ScenarioWritePayload): Promise<void> {
    if (!editing) return
    const updated = await updateScenario(apiRequest, editing.id, payload)
    setEditorOpen(false)
    setEditing(null)
    await load()
    setActionError(`已保存为新版本 v${updated.version}（旧版本保持不可变）。`)
  }

  async function handleDuplicate(scenario: ScenarioDto): Promise<void> {
    const key = window.prompt("复制为新的业务键（scenario_key）", `${scenario.scenario_key}-COPY`)
    if (!key) return
    try {
      await duplicateScenario(apiRequest, scenario.id, key.trim())
      await load()
      setActionError(`已复制为「${key.trim()}」。`)
    } catch (caught) {
      setActionError(errorText(caught))
    }
  }

  async function handleArchive(scenario: ScenarioDto): Promise<void> {
    try {
      await archiveScenario(apiRequest, scenario.id)
      await load()
      setActionError(`已归档「${scenario.name}」（历史版本仍可运行）。`)
    } catch (caught) {
      setActionError(errorText(caught))
    }
  }

  async function handleExport(): Promise<void> {
    try {
      const payload = await exportScenarios(apiRequest, {
        split: split || undefined,
        variant: variant || undefined,
      })
      setActionError(`已导出 ${payload.total} 个场景（有效版本）。`)
    } catch (caught) {
      setActionError(errorText(caught))
    }
  }

  return (
    <section className="simulation-library" aria-label="模拟案例库">
      <header className="simulation-library-header">
        <div>
          <h2>案例库</h2>
          <p className="simulation-hint">
            共 {total} 个案例分支（6 个案例 × 3 种客户行为）。编辑场景会**追加新版本**，历史版本保持不可变。
          </p>
        </div>
        <div className="simulation-actions">
          <UiButton
            variant="primary"
            onClick={() => {
              setEditing(null)
              setEditorOpen(true)
            }}
          >
            新建场景
          </UiButton>
          <UiButton onClick={() => void handleExport()}>导出</UiButton>
        </div>
      </header>

      <div className="simulation-filters" role="group" aria-label="案例筛选">
        <label>
          <span>客户行为</span>
          <select
            value={variant}
            onChange={(event) => setVariant(event.target.value as ScenarioVariant | "")}
          >
            {VARIANT_OPTIONS.map((option) => (
              <option key={option.value || "all"} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>数据集</span>
          <select
            value={split}
            onChange={(event) => setSplit(event.target.value as ScenarioSplit | "")}
          >
            {SPLIT_OPTIONS.map((option) => (
              <option key={option.value || "all"} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>状态</span>
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as ScenarioStatus | "")}
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value || "all"} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>关键字</span>
          <input
            type="search"
            value={keyword}
            placeholder="案例名或业务键"
            onChange={(event) => setKeyword(event.target.value)}
          />
        </label>
        <UiButton onClick={() => void load()}>刷新</UiButton>
      </div>

      {actionError ? (
        <p className="simulation-notice" role="status">
          {actionError}
        </p>
      ) : null}
      {error ? (
        <p className="simulation-error" role="alert">
          {error}
        </p>
      ) : null}

      {loading && !loadedOnce.current ? <Loading label="正在加载案例库…" /> : null}

      {!loading && items.length === 0 ? (
        <EmptyState
          title="案例库为空"
          description="还没有场景。可以先新建一个，或导入案例 JSON。"
        />
      ) : null}

      {items.length > 0 ? (
        <table className="simulation-table">
          <thead>
            <tr>
              <th scope="col">案例</th>
              <th scope="col">客户行为</th>
              <th scope="col">数据集</th>
              <th scope="col">状态</th>
              <th scope="col">版本</th>
              <th scope="col">标签</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((scenario) => (
              <tr key={scenario.id}>
                <td>
                  <div className="simulation-case-name">{scenario.name}</div>
                  <code className="simulation-case-key">{scenario.scenario_key}</code>
                </td>
                <td>{VARIANT_LABEL[scenario.variant]}</td>
                <td>{SPLIT_LABEL[scenario.split]}</td>
                <td>{STATUS_LABEL[scenario.status]}</td>
                <td>v{scenario.version}</td>
                <td>
                  {scenario.tags.length ? scenario.tags.join("、") : "—"}
                </td>
                <td className="simulation-row-actions">
                  <UiButton
                    compact
                    onClick={() => {
                      setEditing(scenario)
                      setEditorOpen(true)
                    }}
                  >
                    编辑
                  </UiButton>
                  <UiButton compact onClick={() => void handleDuplicate(scenario)}>
                    复制
                  </UiButton>
                  <AsyncButton
                    compact
                    actionKey={`archive-${scenario.id}`}
                    onRun={async () => {
                      await handleArchive(scenario)
                    }}
                  >
                    归档
                  </AsyncButton>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {editorOpen ? (
        <ScenarioEditor
          scenario={editing}
          onCancel={() => {
            setEditorOpen(false)
            setEditing(null)
          }}
          onSubmit={editing ? handleUpdate : handleCreate}
        />
      ) : null}
    </section>
  )
}
