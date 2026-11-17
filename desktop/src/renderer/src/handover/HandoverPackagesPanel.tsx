import { useCallback, useEffect, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"

// T-B1 封包半（goal-tb tb4）：结项交付包面板（delivery tab，方案设计下方）。
// 生命周期 draft→sealed→delivered；封存冻结清单+manifest 指纹；交付登记=
// admin 专属终态不可逆（D11 草案「delivered（登记对外交付）=admin」）。
// 清单只收指针+指纹（真相原则：文件本体留在项目工作目录，原件永不进库）。
// 挑选面三态（#495 服务端 ?type= 分型投影）：artifact/document/file 分型
// 拉取、勾选跨型累计、提交体按型落指针键（服务端按键自反推 item_type）。

interface PackageRowDto {
  id: string
  project_id: string
  label: string | null
  status: string
  created_at: string
  sealed_by_user_id: string | null
  sealed_at: string | null
  unsealed_count: number
  delivered_by_user_id: string | null
  delivered_at: string | null
  manifest_sha256?: string
}

interface PackageItemDto {
  id: string
  item_type: string
  artifact_id: string | null
  document_version_id: string | null
  file_version_id: string | null
  run_id: string | null
  kind: string
  display_name: string
  storage_ref: string
  sha256: string
}

interface PackageDetailDto extends PackageRowDto {
  items: PackageItemDto[]
  manifest?: {
    package_id: string
    label: string | null
    sealed_at: string | null
    items: Array<{
      item_type: string
      artifact_id: string | null
      document_version_id: string | null
      file_version_id: string | null
      run_id: string | null
      kind: string
      display_name: string
      storage_ref: string
      sha256: string
    }>
  }
}

interface PackageListDto {
  items: PackageRowDto[]
  truncated: boolean
}

// 挑选面三态（#495 服务端 ?type= 分型投影）：artifact=已复核产物／
// document=已确认文档版本／file=可用文件版本。指针键随类型（恰一互斥）。
type PickerKind = "artifact" | "document" | "file"

const PICKER_TYPES: PickerKind[] = ["artifact", "document", "file"]

const PICKER_TYPE_LABEL: Record<PickerKind, string> = {
  artifact: "已复核产物",
  document: "文档版本",
  file: "文件版本",
}

const PICKER_CAPTION: Record<PickerKind, string> = {
  artifact: "已复核产物（勾选入包）",
  document: "已确认文档版本（勾选入包）",
  file: "可用文件版本（勾选入包）",
}

const PICKER_EMPTY_HINT: Record<PickerKind, string> = {
  artifact: "暂无已复核产物——先在「智能体」页对 run 产物「标记复核」，再回来组包。",
  document: "暂无已确认（confirmed）文档版本——项目文档确认后再入包。",
  file: "暂无可用（available）文件版本——项目文件处理完成后再入包。",
}

const ITEM_TYPE_LABEL: Record<string, string> = {
  artifact: "产物",
  document: "文档",
  file: "文件",
}

interface PickerArtifactDto {
  artifact_id: string
  run_id: string | null
  kind: string
  storage_ref: string
  sha256: string
  reviewed_at: string | null
}

interface PickerDocumentDto {
  document_version_id: string
  document_id: string
  version_number: number
  kind: string
  storage_ref: string
  sha256: string
}

interface PickerFileDto {
  file_version_id: string
  file_id: string
  kind: string
  storage_ref: string
  sha256: string
}

type PickerRowDto = PickerArtifactDto | PickerDocumentDto | PickerFileDto

interface PickerDto {
  items: PickerRowDto[]
  truncated: boolean
}

function pickerRowMeta(row: PickerRowDto): { itemType: PickerKind; pointerKey: string; pointerId: string } {
  if ("document_version_id" in row) {
    return { itemType: "document", pointerKey: "document_version_id", pointerId: row.document_version_id }
  }
  if ("file_version_id" in row) {
    return { itemType: "file", pointerKey: "file_version_id", pointerId: row.file_version_id }
  }
  return { itemType: "artifact", pointerKey: "artifact_id", pointerId: row.artifact_id }
}

// 行副标签：文档版本带版本号（人类可读），其余沿 kind
function pickerRowCaption(row: PickerRowDto): string {
  if ("version_number" in row) return `文档 v${row.version_number}`
  return row.kind
}

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  sealed: "已封存",
  delivered: "已交付",
}

function statusLabel(value: string): string {
  return STATUS_LABEL[value] ?? value
}

function errorMessage(caught: unknown): string {
  if (caught instanceof ApiClientError) return caught.message
  if (caught instanceof Error) return caught.message
  return "操作失败，请重试。"
}

function formatDateTime(value: string | null): string {
  return value ? value.slice(0, 19).replace("T", " ") : "—"
}

interface HandoverPackagesPanelProps {
  projectId: string
  canManage: boolean
  isAdmin: boolean
}

export function HandoverPackagesPanel({ projectId, canManage, isAdmin }: HandoverPackagesPanelProps) {
  const { apiRequest } = useAuth()
  const [packages, setPackages] = useState<PackageRowDto[]>([])
  const [picker, setPicker] = useState<PickerRowDto[]>([])
  const [pickerType, setPickerType] = useState<PickerKind>("artifact")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [formOpen, setFormOpen] = useState(false)
  const [label, setLabel] = useState("")
  // 勾选跨类型累计（同包可混装三态）：键 = `${item_type}:${pointerId}`，值 = display_name 缺省
  const [selected, setSelected] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<PackageDetailDto | null>(null)
  // 挑选面响应序号：快速连点类型钮时弃过期响应（慢响应后到会覆盖新类型行）
  const pickerSeqRef = useRef(0)

  const reload = useCallback(async () => {
    try {
      const list = await apiRequest<PackageListDto>(
        `/api/v1/handover-packages?project_id=${encodeURIComponent(projectId)}`,
        { method: "GET" },
      )
      setPackages(list.items)
      setError("")
    } catch {
      // 加载失败静默降级（沿面板族 fail-静默纪律；动作失败走 alert）
    } finally {
      setLoading(false)
    }
  }, [apiRequest, projectId])

  const loadPicker = useCallback(async (type: PickerKind) => {
    const seq = ++pickerSeqRef.current
    try {
      const pickerData = await apiRequest<PickerDto>(
        `/api/v1/handover-packages/artifacts?project_id=${encodeURIComponent(projectId)}&type=${type}`,
        { method: "GET" },
      )
      if (seq !== pickerSeqRef.current) return // 已切到其他类型：过期响应丢弃
      setPicker(pickerData.items)
    } catch {
      // 同上：挑选面失败静默降级
    }
  }, [apiRequest, projectId])

  useEffect(() => {
    void reload()
  }, [reload])

  useEffect(() => {
    void loadPicker(pickerType)
  }, [loadPicker, pickerType])

  const switchPickerType = (type: PickerKind) => {
    if (type === pickerType) return
    setPickerType(type)
    setPicker([]) // 先清旧类型行，防换型瞬间误勾
  }

  const toggleDetail = async (row: PackageRowDto) => {
    if (expandedId === row.id) {
      setExpandedId(null); setDetail(null)
      return
    }
    setExpandedId(row.id); setDetail(null)
    try {
      const data = await apiRequest<PackageDetailDto>(
        `/api/v1/handover-packages/${encodeURIComponent(row.id)}`,
        { method: "GET" },
      )
      setDetail(data)
    } catch (caught) {
      setError(errorMessage(caught))
      setExpandedId(null)
    }
  }

  const createPackage = async () => {
    if (saving) return
    const pickedKeys = Object.keys(selected)
    if (!pickedKeys.length) {
      setError("请至少勾选一项入包内容。")
      return
    }
    setSaving(true)
    setError(""); setNotice("")
    try {
      await apiRequest<PackageDetailDto>("/api/v1/handover-packages", {
        method: "POST",
        // body 契约＝对象：主进程 serializeBody 统一 stringify（预 stringify 会二次编码 → 服务端 4xx）。
        body: {
          project_id: projectId,
          label: label || undefined,
          // 三态指针键：服务端按键自反推 item_type（恰一键）；document/file
          // display_name 缺省交服务端默认（business_code v{n} / 原文件名）。
          items: pickedKeys.map((key) => {
            const sep = key.indexOf(":")
            const itemType = key.slice(0, sep)
            const pointerId = key.slice(sep + 1)
            const pointerKey =
              itemType === "document" ? "document_version_id" : itemType === "file" ? "file_version_id" : "artifact_id"
            return { [pointerKey]: pointerId, display_name: selected[key] || undefined }
          }),
        },
      })
      setNotice("草稿交付包已创建（清单为指针+指纹快照）。")
      setLabel(""); setSelected({}); setFormOpen(false)
      await reload()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setSaving(false)
    }
  }

  const act = async (packageId: string, action: "seal" | "unseal" | "deliver", done: string) => {
    setBusyId(packageId)
    setError(""); setNotice("")
    try {
      await apiRequest(`/api/v1/handover-packages/${encodeURIComponent(packageId)}/${action}`, { method: "POST" })
      setNotice(done)
      if (expandedId === packageId) {
        const data = await apiRequest<PackageDetailDto>(
          `/api/v1/handover-packages/${encodeURIComponent(packageId)}`,
          { method: "GET" },
        )
        setDetail(data)
      }
      await reload()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusyId(null)
    }
  }

  if (loading) return <p className="empty-copy" role="status">正在加载结项交付包…</p>

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>结项交付包</h2>
            <p>清单=产物/文档/文件版本指针+sha256 快照（原件留在项目工作目录）；封存冻结并生成 manifest 指纹；交付登记为管理员终态动作。</p>
          </div>
          {canManage ? (
            <button className="secondary-button compact" onClick={() => setFormOpen((open) => !open)}>
              {formOpen ? "收起" : "新建交付包"}
            </button>
          ) : null}
        </div>
        {notice ? <p className="notice" role="status">{notice}</p> : null}
        {error ? <p className="form-error banner" role="alert">{error}</p> : null}
        {formOpen && canManage ? (
          <form className="form-grid" onSubmit={(event) => { event.preventDefault(); void createPackage() }}>
            <label htmlFor="handover-label">包名（可选）</label>
            <input id="handover-label" value={label} onChange={(event) => setLabel(event.target.value)} maxLength={200} placeholder="如：初诊项目结项交付包" />
            <div role="group" aria-label="入包类型">
              {PICKER_TYPES.map((type) => (
                <button
                  key={type}
                  type="button"
                  className={type === pickerType ? "primary-button compact" : "secondary-button compact"}
                  aria-pressed={type === pickerType}
                  onClick={() => switchPickerType(type)}
                >
                  {PICKER_TYPE_LABEL[type]}
                </button>
              ))}
            </div>
            <p className="handover-picker-caption">{PICKER_CAPTION[pickerType]}</p>
            {picker.length ? (
              <div className="handover-picker">
                {picker.map((row) => {
                  const meta = pickerRowMeta(row)
                  const pickKey = `${meta.itemType}:${meta.pointerId}`
                  return (
                    <label key={pickKey} className="handover-picker-row" htmlFor={`handover-pick-${meta.pointerId}`}>
                      <input
                        id={`handover-pick-${meta.pointerId}`}
                        type="checkbox"
                        checked={pickKey in selected}
                        onChange={(event) => {
                          setSelected((prev) => {
                            const next = { ...prev }
                            if (event.target.checked) {
                              // artifact 缺省名=storage_ref 文件名；document/file 交服务端默认
                              // （business_code v{n}／原文件名，代号化安全）
                              next[pickKey] =
                                meta.itemType === "artifact"
                                  ? row.storage_ref.split("/").pop() || row.storage_ref
                                  : ""
                            } else {
                              delete next[pickKey]
                            }
                            return next
                          })
                        }}
                      />
                      <code>{row.storage_ref}</code>
                      <small>{pickerRowCaption(row)} · {row.sha256.slice(0, 12)}…</small>
                    </label>
                  )
                })}
              </div>
            ) : (
              <p className="empty-state">{PICKER_EMPTY_HINT[pickerType]}</p>
            )}
            <div>
              <button className="primary-button" type="submit" disabled={saving || !Object.keys(selected).length}>
                {saving ? "正在创建…" : "创建草稿包"}
              </button>
            </div>
          </form>
        ) : null}
        {packages.length ? (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">包名</th>
                <th scope="col">状态</th>
                <th scope="col">封存时间</th>
                <th scope="col">交付时间</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {packages.map((row) => (
                <tr key={row.id}>
                  <td>{row.label ?? <code>{row.id.slice(0, 8)}</code>}</td>
                  <td>
                    {statusLabel(row.status)}
                    {row.unsealed_count ? <small> · 解封 {row.unsealed_count} 次</small> : null}
                  </td>
                  <td>{formatDateTime(row.sealed_at)}</td>
                  <td>{formatDateTime(row.delivered_at)}</td>
                  <td>
                    <button className="secondary-button" onClick={() => { void toggleDetail(row) }}>
                      {expandedId === row.id ? "收起" : "清单"}
                    </button>
                    {canManage && row.status === "draft" ? (
                      <button className="secondary-button" disabled={busyId === row.id} onClick={() => { void act(row.id, "seal", "已封存（清单冻结，manifest 指纹已生成）。") }}>
                        {busyId === row.id ? "正在提交…" : "封存"}
                      </button>
                    ) : null}
                    {canManage && row.status === "sealed" ? (
                      <button className="secondary-button" disabled={busyId === row.id} onClick={() => { void act(row.id, "unseal", "已解封回草稿（解封次数已留痕）。") }}>
                        {busyId === row.id ? "正在提交…" : "解封"}
                      </button>
                    ) : null}
                    {isAdmin && row.status === "sealed" ? (
                      <button className="secondary-button" disabled={busyId === row.id} onClick={() => { void act(row.id, "deliver", "已登记交付（终态不可逆）。") }}>
                        {busyId === row.id ? "正在提交…" : "交付登记"}
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="empty-state">暂无结项交付包。项目结项时把已复核的 run 产物组包封存，交付登记后进入对外交付留痕。</p>
        )}
        {expandedId && detail ? (
          <div className="detail-block">
            <h3>{detail.label ?? "交付包清单"}</h3>
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">名称</th>
                  <th scope="col">类型</th>
                  <th scope="col">种类</th>
                  <th scope="col">指针</th>
                  <th scope="col">sha256</th>
                </tr>
              </thead>
              <tbody>
                {detail.items.map((item) => (
                  <tr key={item.id}>
                    <td>{item.display_name}</td>
                    <td>{ITEM_TYPE_LABEL[item.item_type] ?? item.item_type}</td>
                    <td>{item.kind}</td>
                    <td><code>{item.storage_ref}</code></td>
                    <td><code>{item.sha256.slice(0, 12)}…</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {detail.manifest ? (
              <p><small>manifest_sha256 <code>{detail.manifest_sha256}</code>（清单规范化 JSON 哈希，可复算校验）</small></p>
            ) : (
              <p className="empty-state">草稿包无 manifest 指纹（封存后生成）。</p>
            )}
          </div>
        ) : null}
      </section>
    </div>
  )
}
