/**
 * The fixed business stage shared by project files and project documents.
 *
 * The value itself is the Chinese label; `BUSINESS_CATEGORY_UNCATEGORIZED_LABEL`
 * (未分类) is only a filter token for the list dropdowns, never a stored column
 * value (uncategorized is stored as `NULL`).
 */
export const BUSINESS_CATEGORIES = [
  "商务合约",
  "预调研",
  "调研",
  "PoV验证",
  "生产部署",
  "培训预交接",
] as const

export type BusinessCategory = (typeof BUSINESS_CATEGORIES)[number]

/** Filter token meaning "no business stage assigned" (stored as `NULL`). */
export const BUSINESS_CATEGORY_UNCATEGORIZED_LABEL = "未分类"

/** Human-readable select/chip labels for the six business stages. */
export const BUSINESS_CATEGORY_LABELS: Record<BusinessCategory, string> = {
  商务合约: "商务合约",
  预调研: "预调研",
  调研: "调研",
  PoV验证: "PoV验证",
  生产部署: "生产部署",
  培训预交接: "培训预交接",
}
