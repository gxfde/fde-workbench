// V3.2 G2 模拟训练场 · 案例库。
//
// 只读列表 + 分类过滤 + 版本可见；写动作（新建/编辑/复制/归档/启用停用/批量导入/导出）全部
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
  importScenarios,
  listScenarios,
  updateScenario,
  type ScenarioWritePayload,
} from "./api"
import { ScenarioEditor } from "./ScenarioEditor"
import {
  INDUSTRY_LABEL,
  SCENARIO_INDUSTRIES,
  SPLIT_LABEL,
  STATUS_LABEL,
  VARIANT_LABEL,
  type ScenarioDto,
  type ScenarioIndustry,
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

const INDUSTRY_OPTIONS: Array<{ value: ScenarioIndustry | ""; label: string }> = [
  { value: "", label: "全部分类" },
  ...SCENARIO_INDUSTRIES.map((key) => ({ value: key, label: INDUSTRY_LABEL[key] })),
]

/** 分类下拉选项文案：有可靠计数时追加「（N）」，未导入的行业显示「（0）」。 */
export function industryOptionLabel(
  key: ScenarioIndustry,
  counts: Record<string, number>,
  reliable: boolean,
): string {
  if (!reliable) return INDUSTRY_LABEL[key]
  return `${INDUSTRY_LABEL[key]}（${counts[key] ?? 0}）`
}

function errorText(caught: unknown): string {
  if (caught instanceof ApiClientError) return caught.message
  if (caught instanceof Error) return caught.message
  return "操作失败，请稍后重试。"
}

/** 读取文件文本：优先 Blob.text()，环境缺失时退 FileReader（jsdom 兼容）。 */
function readFileText(file: File): Promise<string> {
  if (typeof file.text === "function") return file.text()
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new Error("读取导入文件失败。"))
    reader.readAsText(file)
  })
}

/** 批量导入文件解析：兼容「裸场景数组」与 {scenarios:[…]} 包裹两种形态（服务端契约要对象）。 */
export function parseScenarioImportText(text: string): unknown[] {
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    throw new Error("导入文件不是合法 JSON。")
  }
  if (Array.isArray(data)) return data
  if (
    data &&
    typeof data === "object" &&
    Array.isArray((data as { scenarios?: unknown }).scenarios)
  ) {
    return (data as { scenarios: unknown[] }).scenarios
  }
  throw new Error("导入文件须是场景数组，或含 scenarios 数组的 JSON 对象。")
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
  const [industry, setIndustry] = useState<ScenarioIndustry | "">("")
  const [status, setStatus] = useState<ScenarioStatus | "">("")
  const [keyword, setKeyword] = useState("")
  /** 全量有效版本计数（含未导入的行业=0），用于分类下拉旁的数量提示；truncated 时降级隐藏。 */
  const [industryCounts, setIndustryCounts] = useState<Record<string, number>>({})
  const [countsReliable, setCountsReliable] = useState(true)
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<ScenarioDto | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const sequence = useRef(0)
  const loadedOnce = useRef(false)

  const load = useCallback(async () => {
    const requestSequence = ++sequence.current
    try {
      const payload = await listScenarios(apiRequest, {
        variant: variant || undefined,
        split: split || undefined,
        industry: industry || undefined,
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
  }, [apiRequest, industry, keyword, split, status, variant])

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

  const refreshCounts = useCallback(async () => {
    // 单独拉一次全量（独立于列表筛选），统计各分类已导入数量；失败静默降级（隐藏数字，不影响主列表）。
    try {
      const payload = await listScenarios(apiRequest, { limit: 200 })
      const counts: Record<string, number> = {}
      for (const item of payload.items) {
        counts[item.industry] = (counts[item.industry] ?? 0) + 1
      }
      setIndustryCounts(counts)
      setCountsReliable(!payload.truncated)
    } catch {
      setCountsReliable(false)
    }
  }, [apiRequest])

  useEffect(() => {
    void refreshCounts()
  }, [refreshCounts])

  async function handleCreate(payload: ScenarioWritePayload): Promise<void> {
    const created = await createScenario(apiRequest, payload)
    setEditorOpen(false)
    setEditing(null)
    await load()
    void refreshCounts()
    setActionError(`已创建场景「${created.name}」（版本 ${created.version}）。`)
  }

  async function handleUpdate(payload: ScenarioWritePayload): Promise<void> {
    if (!editing) return
    const updated = await updateScenario(apiRequest, editing.id, payload)
    setEditorOpen(false)
    setEditing(null)
    await load()
    void refreshCounts()
    setActionError(`已保存为新版本 v${updated.version}（旧版本保持不可变）。`)
  }

  async function handleDuplicate(scenario: ScenarioDto): Promise<void> {
    const key = window.prompt("复制为新的业务键（scenario_key）", `${scenario.scenario_key}-COPY`)
    if (!key) return
    try {
      await duplicateScenario(apiRequest, scenario.id, key.trim())
      await load()
      void refreshCounts()
      setActionError(`已复制为「${key.trim()}」。`)
    } catch (caught) {
      setActionError(errorText(caught))
    }
  }

  async function handleArchive(scenario: ScenarioDto): Promise<void> {
    try {
      await archiveScenario(apiRequest, scenario.id)
      await load()
      void refreshCounts()
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

  async function handleImportFile(file: File): Promise<void> {
    try {
      const scenarios = parseScenarioImportText(await readFileText(file))
      if (scenarios.length === 0) {
        setActionError("导入文件里没有场景（空数组）。")
        return
      }
      const result = await importScenarios(apiRequest, scenarios)
      if (result.failures.length) {
        const head = result.failures
          .slice(0, 3)
          .map((failure) => `#${failure.index} ${failure.code}：${failure.message}`)
          .join("；")
        const more = result.failures.length > 3 ? "…" : ""
        setActionError(
          `已导入 ${result.created_count} 个场景；失败 ${result.failures.length} 条（${head}${more}）`,
        )
      } else {
        setActionError(`已导入 ${result.created_count} 个场景。`)
      }
      await load()
      void refreshCounts()
    } catch (caught) {
      setActionError(errorText(caught))
    }
  }

  async function handleSetStatus(scenario: ScenarioDto): Promise<void> {
    const next: ScenarioStatus = scenario.status === "active" ? "draft" : "active"
    try {
      const updated = await updateScenario(apiRequest, scenario.id, { status: next })
      await load()
      void refreshCounts()
      const filterHint =
        status && status !== next
          ? `当前正在按「${STATUS_LABEL[status]}」筛选，该行已移入「${STATUS_LABEL[next]}」视图（切到「全部状态」即可查看）。`
          : ""
      setActionError(
        next === "active"
          ? `已启用「${updated.name}」（版本 v${updated.version} 保持不变）。${filterHint}`
          : `已停用「${updated.name}」（版本 v${updated.version} 保持不变）。${filterHint}`,
      )
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
            共 {total} 个案例分支。编辑案例内容会追加不可变新版本；启用/停用仅切换当前版本状态，不增加版本号。
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
          <UiButton onClick={() => fileInputRef.current?.click()}>导入 JSON</UiButton>
          <UiButton onClick={() => void handleExport()}>导出</UiButton>
          <input
            ref={fileInputRef}
            type="file"
            accept=".json,application/json"
            style={{ display: "none" }}
            onChange={(event) => {
              const file = event.target.files?.[0]
              event.target.value = ""
              if (file) void handleImportFile(file)
            }}
          />
        </div>
      </header>

      <div className="simulation-filters" role="group" aria-label="案例筛选">
        <label>
          <span>分类</span>
          <select
            value={industry}
            onChange={(event) => setIndustry(event.target.value as ScenarioIndustry | "")}
          >
            {INDUSTRY_OPTIONS.map((option) => (
              <option key={option.value || "all"} value={option.value}>
                {option.value
                  ? industryOptionLabel(option.value, industryCounts, countsReliable)
                  : option.label}
              </option>
            ))}
          </select>
        </label>
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
        <UiButton onClick={() => { void load(); void refreshCounts() }}>刷新</UiButton>
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
          description={
            industry
              ? "该分类下暂无已导入案例。可切换其他分类，或导入对应案例 JSON。"
              : "还没有场景。可以先新建一个，或导入案例 JSON。"
          }
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
            {items.map((scenario) => {
              const branchKey = `${scenario.scenario_key}:${scenario.variant}`
              return (
              <tr key={branchKey} data-scenario-branch={branchKey}>
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
                  {scenario.status !== "archived" ? (
                    <AsyncButton
                      compact
                      actionKey={`scenario-status-in-place-${branchKey}`}
                      onRun={async () => {
                        await handleSetStatus(scenario)
                      }}
                    >
                      {scenario.status === "active" ? "停用" : "启用"}
                    </AsyncButton>
                  ) : null}
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
                    actionKey={`archive-${branchKey}`}
                    onRun={async () => {
                      await handleArchive(scenario)
                    }}
                  >
                    归档
                  </AsyncButton>
                </td>
              </tr>
              )
            })}
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
