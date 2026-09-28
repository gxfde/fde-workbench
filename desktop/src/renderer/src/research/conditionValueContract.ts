import type { ResearchConditionDto } from "./types"

// Mirrored by server research.answers; changing a value requires contract tests in both runtimes.
export const MAX_DECIMAL_INPUT_CHARACTERS = 256
export const MAX_DECIMAL_SIGNIFICANT_DIGITS = 100
export const MAX_DECIMAL_ABSOLUTE_EXPONENT = 100
export const MAX_DECIMAL_INTEGER_DIGITS = 100
export const MAX_DECIMAL_SCALE = 100
export const MAX_DECIMAL_EXPANDED_CHARACTERS = 202

const ASCII_EDGE_WHITESPACE = /^[ \t\r\n]+|[ \t\r\n]+$/g
const DECIMAL_LITERAL = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/

export function normalizeAsciiEdgeWhitespace(value: string): string {
  return value.replace(ASCII_EDGE_WHITESPACE, "")
}

export function isCanonicalConditionText(value: unknown): boolean {
  return typeof value === "string"
    && value.length > 0
    && normalizeAsciiEdgeWhitespace(value) === value
}

export function normalizeDecimalValue(value: string): string | null {
  if (value.length > MAX_DECIMAL_INPUT_CHARACTERS) return null
  const trimmed = normalizeAsciiEdgeWhitespace(value)
  const match = DECIMAL_LITERAL.exec(trimmed)
  if (!match) return null

  const negative = match[1] === "-"
  const fraction = match[3] ?? match[4] ?? ""
  let coefficient = `${match[2] ?? "0"}${fraction}`.replace(/^0+/, "")
  let exponent: bigint
  try {
    exponent = BigInt(match[5] ?? "0") - BigInt(fraction.length)
  } catch {
    return null
  }
  const zero = coefficient.length === 0
  const trailingZeroCount = zero ? 0 : coefficient.length - coefficient.replace(/0+$/, "").length
  if (!zero && trailingZeroCount) {
    coefficient = coefficient.slice(0, -trailingZeroCount)
    exponent += BigInt(trailingZeroCount)
  }

  const significantDigits = BigInt(zero ? 1 : coefficient.length)
  const adjusted = exponent + significantDigits - 1n
  const integerDigits = adjusted >= 0n ? adjusted + 1n : 1n
  const scale = exponent < 0n ? -exponent : 0n
  const expandedCharacters = integerDigits + (scale > 0n ? scale + 1n : 0n) + (negative ? 1n : 0n)
  if (significantDigits > BigInt(MAX_DECIMAL_SIGNIFICANT_DIGITS)
    || exponent > BigInt(MAX_DECIMAL_ABSOLUTE_EXPONENT)
    || exponent < -BigInt(MAX_DECIMAL_ABSOLUTE_EXPONENT)
    || integerDigits > BigInt(MAX_DECIMAL_INTEGER_DIGITS)
    || scale > BigInt(MAX_DECIMAL_SCALE)
    || expandedCharacters > BigInt(MAX_DECIMAL_EXPANDED_CHARACTERS)) return null
  if (zero) return "0"

  let plain: string
  if (exponent >= 0n) {
    plain = `${coefficient}${"0".repeat(Number(exponent))}`
  } else {
    const scaleNumber = Number(scale)
    plain = scaleNumber < coefficient.length
      ? `${coefficient.slice(0, coefficient.length - scaleNumber)}.${coefficient.slice(-scaleNumber)}`
      : `0.${"0".repeat(scaleNumber - coefficient.length)}${coefficient}`
  }
  return negative ? `-${plain}` : plain
}

export function isCanonicalDecimalValue(value: unknown): value is string {
  return typeof value === "string" && normalizeDecimalValue(value) === value
}

export function hasConditionalDependencyCycle(
  fields: Array<{ fieldKey: string; condition?: ResearchConditionDto }>,
): boolean {
  const graph = new Map(fields.map((field) => [field.fieldKey, conditionReferences(field.condition)]))
  const visiting = new Set<string>()
  const visited = new Set<string>()

  function visit(key: string): boolean {
    if (visiting.has(key)) return true
    if (visited.has(key)) return false
    visiting.add(key)
    for (const referenced of graph.get(key) ?? []) {
      if (graph.has(referenced) && visit(referenced)) return true
    }
    visiting.delete(key)
    visited.add(key)
    return false
  }

  return fields.some((field) => visit(field.fieldKey))
}

function conditionReferences(condition: ResearchConditionDto | undefined): Set<string> {
  if (!condition) return new Set()
  if (condition.operator === "all" || condition.operator === "any") {
    return new Set(condition.conditions.flatMap((child) => [...conditionReferences(child)]))
  }
  return new Set([condition.field_key])
}
