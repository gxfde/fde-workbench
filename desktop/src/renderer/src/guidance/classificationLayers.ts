// 项目指引条目的三层归属规则——台账 T-A4。
//
// 缺陷基线（fork/main 实测）：`GuidanceReview` 只读态把每个条目渲染成纯文本
// `<li>`（`GuidanceItems`），classification / source_refs / confirmed **全部丢弃**
// ⇒ 客户原话、AI 推断、待确认项在界面上完全不可区分，「售前录入的事实需客户
// 确认」这条红线在桌面没有视觉落点。
//
// 本模块只做「分类 → 层级」的纯函数判定，不含渲染：
// - 五分类（`ai_schema.py:6` CLASSIFICATIONS）归三层；
// - **降级规则**：非 open_question 且无原文锚点的条目**不得当事实**——服务端 AI
//   生成路径已 fail-closed 拒收（`ai_schema.py:78` `missing_source_ref`：「事实和
//   AI 判断必须引用原文」），人工编辑路径是弱校验，桌面侧同样按待确认呈现，
//   避免把无锚点的判断混进「客户事实」层。
import type { GuidanceClassification, GuidanceItemDto } from "./types"

export type GuidanceLayer = "fact" | "ai" | "open"

export const GUIDANCE_LAYERS: GuidanceLayer[] = ["fact", "ai", "open"]

export const CLASSIFICATION_LABELS: Record<GuidanceClassification, string> = {
  customer_stated: "客户原话",
  ai_synthesized: "AI 综合",
  ai_inferred: "AI 推断",
  open_question: "待确认",
  human_added: "人工补录",
}

export const LAYER_META: Record<GuidanceLayer, { label: string; description: string }> = {
  fact: { label: "客户事实", description: "客户原话与人工补录——已是既定事实" },
  ai: { label: "AI 判断", description: "AI 综合或推断，尚未经客户确认" },
  open: { label: "待确认", description: "开口问题，以及缺少原文锚点的判断项" },
}

/** 条目归属哪一层。降级规则见模块头说明。 */
export function layerOf(item: GuidanceItemDto): GuidanceLayer {
  if (item.classification === "open_question") return "open"
  // human_added 是人工补录，允许无锚点（服务端 `missing_source_ref` 同样豁免它）。
  if (!item.source_refs.length && item.classification !== "human_added") return "open"
  if (item.classification === "customer_stated" || item.classification === "human_added") return "fact"
  return "ai"
}

/** 按三层分组，保持条目在层内的原有顺序。 */
export function groupByLayer(items: GuidanceItemDto[]): Record<GuidanceLayer, GuidanceItemDto[]> {
  const grouped: Record<GuidanceLayer, GuidanceItemDto[]> = { fact: [], ai: [], open: [] }
  for (const item of items) grouped[layerOf(item)].push(item)
  return grouped
}

/**
 * 人工编辑时该条目允许被改成的分类。
 *
 * 无原文锚点的条目不得被改成「事实/AI 判断」类——那等于凭空造出一条客户没说过
 * 的话。与服务端 AI 路径的 `missing_source_ref` 同口径。
 */
export function allowedClassifications(item: GuidanceItemDto): GuidanceClassification[] {
  const allowed: GuidanceClassification[] = item.source_refs.length
    ? ["customer_stated", "ai_synthesized", "ai_inferred", "open_question", "human_added"]
    : ["open_question", "human_added"]
  // 历史数据里可能存在「无锚点却是事实类」的条目（人工编辑路径弱校验留下的）：
  // 当前值必须仍在选项里，否则下拉会显示空白，用户一保存就静默改掉分类。
  return allowed.includes(item.classification) ? allowed : [...allowed, item.classification]
}

/** 新增条目的默认值：人工补录、无锚点、未确认——服务端允许且语义最保守。 */
export function newGuidanceItem(): GuidanceItemDto {
  return { text: "", classification: "human_added", source_refs: [], confirmed: false }
}
