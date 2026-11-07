import { useEffect, useState } from "react"
import type { RendererApiRequestOptions } from "../api/client"
import { isResearchSubjectType } from "./types"

// CR-032 写路径清偿（T-O2b 值域开放的桌面消费面）：新建/导入调研对象时，
// 除内置五类外还应提供本项目的注册对象类型（T-O2 注册表 kind=subject_type）。
// 服务端闸门（create_subject_in_transaction 的 usable_subject_type_codes）
// 早已接受「内置 ∪ 注册表 active − project」；桌面此前只是没有选项入口。
//
// 数据源分两路（T-O2c 偏差清偿）：
// - 项目上下文 → GET /api/v1/projects/{id}/ontology/relation-types
//   （can_view，T-O2；术语表页同源消费）：全局 ∪ 项目内合并面，
//   项目内遮蔽同名全局的语义在服务端。
// - 无项目上下文（projectId=null，行业模板/调研定义编辑器）→
//   GET /api/v1/ontology/relation-types（require_auth，T-O2c 全局只读面）：
//   只收全局行——项目内类型只对本项目生效，不能进全局模板。
// 两路都是客户端过滤 kind=subject_type 且 status=active（draft 未拍板 /
// retired 禁新建，与服务端同一把尺子）。

interface RelationTypeRow {
  kind: unknown
  status: unknown
  code: unknown
}

function isRelationTypeRow(value: unknown): value is RelationTypeRow {
  return typeof value === "object" && value !== null && "kind" in value && "status" in value && "code" in value
}

/**
 * 注册对象类型码（active 行，不含内置五类）。projectId 传 null 时走全局只读面。
 * 拉取失败静默降级为空集——注册类型是增强项，不能因注冊表面加载失败而阻塞
 * 内置五类的创建/导入；值域权威始终在服务端闸门，这里只提供选项。
 */
export function useRegistrySubjectTypes(
  apiRequest: <T>(path: string, options: RendererApiRequestOptions) => Promise<T>,
  projectId: string | null,
  enabled = true,
): string[] {
  const [types, setTypes] = useState<string[]>([])

  useEffect(() => {
    // enabled=false（会话未就绪）时不发请求：apiRequest 在无会话快照时直接
    // 拒绝，且本 effect 只在依赖变化时重跑——错过就要等挂载方重新挂载。
    if (!enabled) return
    let cancelled = false
    const path = projectId === null
      ? "/api/v1/ontology/relation-types"
      : `/api/v1/projects/${encodeURIComponent(projectId)}/ontology/relation-types`
    apiRequest<{ items: unknown[] }>(path, { method: "GET" })
      .then((data) => {
        if (cancelled || !Array.isArray(data?.items)) return
        const codes = data.items
          .filter(isRelationTypeRow)
          .filter((row) => row.kind === "subject_type" && row.status === "active")
          .map((row) => row.code)
          .filter((code): code is string => isResearchSubjectType(code))
        setTypes([...new Set(codes)].sort())
      })
      .catch(() => {
        // 静默降级：形状异常或网络失败都回到「仅内置五类」。
        if (!cancelled) setTypes([])
      })
    return () => {
      cancelled = true
    }
  }, [apiRequest, projectId, enabled])

  return types
}
