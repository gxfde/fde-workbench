import { useEffect, useState } from "react"
import { useAuth } from "../auth/AuthProvider"

/**
 * T-A1（台账「售前主线登记（T-A 系列）」）：presurvey S3 前置闸的桌面可读提示。
 *
 * 背景（登记实测）：G3 诊断开工门已在服务端落地（guidance/service.py 的
 * _require_s3_gate 在 set_presurvey_source 与 create_analysis 两处强制调用，
 * 未通过即抛 409 presurvey_s3_gate_open）——缺的是桌面呈现：拦截面此前只有
 * 通用文案「无法开始 AI 分析」，服务端 message（含三件套清单）与跳转入口
 * 都被丢弃，售前不知道被什么闸住、要去哪里补。
 *
 * 本组件在 409 拦截态渲染：
 * 1. 服务端可读文案（message 原文，零改写）；
 * 2. G3 证据清单四项（claim_status 徽标沿用 GateBoard 的 claimed ≠ accepted
 *    黄标语义——未标 accepted 一律视为 claimed）；
 * 3. 「前往门禁页」跳转锚（复用既有 ?tab=gates 路由，零新路由）。
 *
 * 数据源：GET /projects/{id}/gates（与 GateBoard 同一只读端点）——零服务端改动。
 * G3 不在返回中（理论上不该发生：门禁种子含 G3）时降级为仅显示服务端文案。
 */

interface GateChecklistItem {
  label: string
  claim_status: string | null
}

interface GateListItem {
  gate_key: string
  gate_name: string | null
  status: string
  checklist: GateChecklistItem[]
}

function isGateList(value: unknown): value is { gates: GateListItem[] } {
  if (!value || typeof value !== "object") return false
  const gates = (value as { gates?: unknown }).gates
  if (!Array.isArray(gates)) return false
  return gates.every(
    (gate) =>
      gate !== null &&
      typeof gate === "object" &&
      typeof (gate as GateListItem).gate_key === "string" &&
      Array.isArray((gate as GateListItem).checklist),
  )
}

export const S3_GATE_BLOCKED_CODE = "presurvey_s3_gate_open"

export function gatesHref(projectId: string): string {
  return `#projects/${encodeURIComponent(projectId)}?tab=gates`
}

export function PresurveyGateHint({ projectId, serverMessage }: { projectId: string; serverMessage: string }) {
  const { apiRequest } = useAuth()
  const [checklist, setChecklist] = useState<GateChecklistItem[]>([])
  const [gateStatus, setGateStatus] = useState<string>("")
  const [gateName, setGateName] = useState<string>("")

  useEffect(() => {
    let active = true
    void apiRequest<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/gates`, { method: "GET" })
      .then((value) => {
        if (!active || !isGateList(value)) return
        const gate = value.gates.find((item) => item.gate_key === "G3")
        if (gate) {
          setChecklist(gate.checklist)
          setGateStatus(gate.status)
          setGateName(gate.gate_name ?? "")
        }
      })
      .catch(() => {
        // 清单加载失败不阻塞提示本身：服务端 message 已含三件套文案，
        // 静默降级为纯文案态（与登记条目「G3 缺失时降级为仅显示文案」一致）。
      })
    return () => {
      active = false
    }
  }, [apiRequest, projectId])

  return (
    <div className="presurvey-gate-hint" role="alert">
      <p className="presurvey-gate-hint-title">暂不能上传预调研文件或发起 AI 分析</p>
      <p className="presurvey-gate-hint-message">{serverMessage}</p>
      {checklist.length ? (
        <div className="presurvey-gate-hint-checklist">
          <p className="presurvey-gate-hint-caption">
            G3 {gateName ? `· ${gateName} ` : ""}证据清单
            {gateStatus ? `（当前状态：${gateStatus}）` : ""}：
          </p>
          <ul>
            {checklist.map((item) => (
              <li key={item.label} className={`claim-${item.claim_status ?? "none"}`}>
                <span
                  className={`badge ${item.claim_status === "accepted" ? "success" : item.claim_status === "claimed" ? "warning" : "muted"}`}
                >
                  {item.claim_status === "accepted" ? "accepted" : item.claim_status === "claimed" ? "claimed" : "未提交"}
                </span>
                {item.label}
              </li>
            ))}
          </ul>
          <p className="presurvey-gate-hint-caption">清单项未标 accepted 一律视为 claimed（claimed ≠ accepted）。</p>
        </div>
      ) : null}
      <a className="presurvey-gate-hint-link" href={gatesHref(projectId)}>
        前往门禁页提交 G3 证据
      </a>
    </div>
  )
}
