// V3.1 试点审阅辅助：抽取事实的行号锚点程序化核验（纯函数，零服务端依赖）。
// 背景：推理模型全文抽取存在相邻行滑移（行号锚到空行/邻近行）——面板在加载
// 事实后按 source_ref 拉取对应纪要正文，本地核验每条 line 定位锚点的质量：
//   A = 高危（空行/短行锚、行号越界、锚行与邻近 ±3 行关键词均不命中）
//   B = 疑似滑移（关键词不在锚行、但在 ±3 行内命中）
//   C = 命中（锚行含数字/专名强信号或中文子串弱信号）
// 分级只做「提示」不做「裁决」——接受/拒绝永远人工点（AI 不代拍板）。

export interface FactAnchorInput {
  id: string
  subject: string
  predicate: string
  object_value: unknown
  source_ref: string
  source_locator: { type: string; line?: number }
}

export interface AnchorGrade {
  grade: "A" | "B" | "C"
  reason: string
}

const NEARBY_RANGE = 3

const MIN_ANCHOR_LENGTH = 4

export function strongSignals(obj: unknown, subject: string, predicate: string): string[] {
  const objText = typeof obj === "string" ? obj : safeJson(obj)
  const blob = `${subject} ${predicate} ${objText}`
  const strong = new Set<string>()
  for (const m of objText.matchAll(/\d+(?:\.\d+)?/g)) strong.add(m[0])
  for (const m of blob.matchAll(/[A-Za-z][A-Za-z0-9:+_./-]{1,}/g)) strong.add(m[0])
  return [...strong]
}

export function weakSignals(subject: string, predicate: string): string[] {
  const weak = new Set<string>()
  for (const src of [subject, predicate]) {
    for (const seg of (src ?? "").split(/[·，。；：、（）()【】\[\]\s]+/)) {
      if (seg.length >= 2) weak.add(seg)
    }
  }
  return [...weak]
}

function safeJson(value: unknown): string {
  try {
    return JSON.stringify(value) ?? ""
  } catch {
    return String(value)
  }
}

function countHits(text: string, pool: string[]): number {
  const t = text.replace(/\s+/g, "")
  let hits = 0
  for (const k of pool) {
    if (t.includes(k.replace(/\s+/g, ""))) hits += 1
  }
  return hits
}

// 单条事实核验：非 line 定位返回 null（时段/字符区间不做行锚核验）。
export function auditLineAnchor(fact: FactAnchorInput, lines: string[]): AnchorGrade | null {
  const locator = fact.source_locator
  if (!locator || locator.type !== "line" || typeof locator.line !== "number" || !Number.isInteger(locator.line)) {
    return null
  }
  const ln = locator.line
  if (ln < 1 || ln > lines.length) {
    return { grade: "A", reason: `行号越界（原文共 ${lines.length} 行）` }
  }
  const anchor = (lines[ln - 1] ?? "").trim()
  const strong = strongSignals(fact.object_value, fact.subject, fact.predicate)
  const weak = weakSignals(fact.subject, fact.predicate)
  const strongHit = countHits(anchor, strong)
  const weakHit = countHits(anchor, weak)
  if (anchor.length < MIN_ANCHOR_LENGTH) return { grade: "A", reason: "空行/短行锚" }
  if (strongHit === 0 && weakHit === 0) {
    for (let off = 1; off <= NEARBY_RANGE; off += 1) {
      for (const l2 of [ln - off, ln + off]) {
        if (l2 < 1 || l2 > lines.length) continue
        const nearby = (lines[l2 - 1] ?? "").replace(/\s+/g, "")
        if (countHits(nearby, strong) > 0 || countHits(nearby, weak) > 0) {
          const delta = l2 > ln ? `+${off}` : `${-off}`
          return { grade: "B", reason: `关键词不在锚行，位于行 ${l2}（偏移 ${delta}）——疑似滑移` }
        }
      }
    }
    return { grade: "A", reason: "关键词锚行与邻近 ±3 行均不命中" }
  }
  if (strongHit === 0) return { grade: "C", reason: "中文词命中（数字/专名未中，可能为改写）" }
  return { grade: "C", reason: "锚行命中" }
}

// 批量核验：按 source_ref（interview_minutes:<id>）复用对应纪要的分行正文。
export function auditFacts(
  facts: FactAnchorInput[],
  minutesContentById: Map<string, string>,
): Map<string, AnchorGrade> {
  const result = new Map<string, AnchorGrade>()
  const linesByRef = new Map<string, string[]>()
  for (const fact of facts) {
    let lines = linesByRef.get(fact.source_ref)
    if (!lines) {
      const prefix = "interview_minutes:"
      const minutesId = fact.source_ref.startsWith(prefix) ? fact.source_ref.slice(prefix.length) : ""
      const content = minutesContentById.get(minutesId) ?? ""
      lines = content ? content.split(/\r?\n/) : []
      linesByRef.set(fact.source_ref, lines)
    }
    const grade = lines.length ? auditLineAnchor(fact, lines) : null
    if (grade) result.set(fact.id, grade)
  }
  return result
}

export interface AnchorSummary {
  a: number
  b: number
  c: number
}

export function summarizeAnchorAudit(audit: Map<string, AnchorGrade>): AnchorSummary {
  const summary: AnchorSummary = { a: 0, b: 0, c: 0 }
  for (const g of audit.values()) {
    if (g.grade === "A") summary.a += 1
    else if (g.grade === "B") summary.b += 1
    else summary.c += 1
  }
  return summary
}
