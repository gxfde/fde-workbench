#!/usr/bin/env node
/**
 * asar 字节验证：确认打包产物内含本轮 UI/UX 改动，且其内容与构建输出一致。
 *
 * 背景：AGENTS.md「桌面改动交付：重打包便携版并做 asar 字节验证」。
 * 「字节验证」= 逐字节比对（sha256），不看时间戳、不看文件大小近似值。
 *
 * 用法：node scripts/verify-asar-bytes.mjs <asar 路径> [desktop/out 目录]
 */
import { createHash } from "node:crypto"
import { readFileSync, readdirSync, existsSync } from "node:fs"
import { join } from "node:path"

const asarPath = process.argv[2]
const outDir = process.argv[3] ?? join("desktop", "out")

if (!asarPath || !existsSync(asarPath)) {
  console.error("用法：node scripts/verify-asar-bytes.mjs <asar 路径> [out 目录]")
  process.exit(1)
}

const asar = readFileSync(asarPath)
const headerSize = asar.readUInt32LE(12)
const header = JSON.parse(asar.subarray(16, 16 + headerSize).toString("utf8"))
// asar 规范：数据区起点 = 8 + u32(4)（header pickle 总长，含字符串对齐填充）。
// 旧公式 16 + headerSize 在 header 长度非 4 字节对齐时差 1–3 字节 → 全部文件误判 FAIL
// （2026-11-14 r46 打包实测抓到：62 项同字节数假失败，逐文件哈希对照定位）。
const dataBase = 8 + asar.readUInt32LE(4)

function walk(node, prefix = "") {
  const out = new Map()
  for (const [name, child] of Object.entries(node.files ?? {})) {
    const path = prefix ? `${prefix}/${name}` : name
    if (child.files) {
      for (const [p, v] of walk(child, path)) out.set(p, v)
    } else {
      out.set(path, child)
    }
  }
  return out
}

const entries = walk(header)
const sha256 = (buf) => createHash("sha256").update(buf).digest("hex")

function readAsarFile(path) {
  const entry = entries.get(path)
  if (!entry || entry.unpacked) return null
  const start = dataBase + Number(entry.offset)
  return asar.subarray(start, start + entry.size)
}

let failed = 0

// ---- 第一步：构建输出与 asar 内逐字节一致 ----
console.log("== 第一步：构建输出 ↔ asar 字节一致 ==")
const assetsDir = join(outDir, "renderer", "assets")
const assetFiles = existsSync(assetsDir)
  ? readdirSync(assetsDir).filter((f) => f.endsWith(".css") || f.endsWith(".js"))
  : []
let byteChecked = 0
for (const file of assetFiles) {
  const asarRel = `out/renderer/assets/${file}`
  const inAsar = readAsarFile(asarRel)
  if (!inAsar) continue
  const onDisk = readFileSync(join(assetsDir, file))
  const same = onDisk.length === inAsar.length && sha256(onDisk) === sha256(inAsar)
  if (!same) {
    console.log(` FAIL  ${asarRel}  ${onDisk.length} vs ${inAsar.length} bytes`)
    failed++
  }
  byteChecked++
}
console.log(`  逐字节比对 ${byteChecked} 个产物文件，失败 ${failed} 项`)

// ---- 第二步：asar 内确实含本轮改动特征 ----
console.log("\n== 第二步：asar 内本轮改动特征 ==")
const cssEntry = [...entries.keys()].find((k) => k.startsWith("out/renderer/assets/") && k.endsWith(".css"))
if (!cssEntry) {
  console.log(" FAIL  asar 内无 CSS 产物")
  failed++
} else {
  const css = readAsarFile(cssEntry).toString("utf8")
  const CSS_CHECKS = [
    ["B1 金描边令牌", "--gold-5: #A3721F"],
    ["B1 渐变降级为展示面", "--brand-gradient"],
    ["S0 语义深墨 --danger-ink", "--danger-ink: #96261A"],
    ["S0 深底文字 --on-dark-muted", "--on-dark-muted"],
    ["S0 焦点环亮金", "--brand-gold-bright"],
    ["S0 禁用不透明度", "--opacity-disabled"],
    ["S0 warning 语义", ".notice.warning"],
    ["S2 Modal 原语", ".ui-modal"],
    ["S2 Toast 宿主", ".toast-host"],
    ["S2 Loading", ".ui-loading"],
    ["S2 侧栏分组", ".nav-group"],
    ["S2 面包屑", ".breadcrumb"],
    ["S3 z-index 令牌", "--z-float-top"],
    ["S3 字阶令牌", "--font-micro"],
    ["S3 阴影令牌", "--shadow-brand-hover"],
  ]
  let miss = 0
  for (const [name, needle] of CSS_CHECKS) {
    const ok = css.includes(needle)
    if (!ok) miss++
    console.log(`${ok ? "  OK  " : " FAIL "}${name}  →  ${needle}`)
  }
  console.log(`  CSS 特征命中 ${CSS_CHECKS.length - miss}/${CSS_CHECKS.length}`)
  if (miss > 0) failed++
}

// ---- 第三步：asar 内 JS 含 S1/S2 的关键行为标记 ----
console.log("\n== 第三步：asar 内 JS 含关键行为标记 ==")
const jsFiles = [...entries.keys()].filter(
  (k) => k.startsWith("out/renderer/assets/") && k.endsWith(".js"),
)
const JS_CHECKS = [
  ["S1 统一确认通道", "confirmAsync"],
  ["S1 弹窗键盘契约", "useDialogA11y"],
  ["S1 操作护栏", "aria-busy"],
  ["S2 Toast 回执", "showToast"],
  ["S2 统一错误码表", "commonErrorMessage"],
  ["S2 侧栏分组标题", "nav-group-title"],
]
let jsAll = ""
for (const f of jsFiles) {
  const buf = readAsarFile(f)
  if (buf) jsAll += buf.toString("utf8")
}
let jsMiss = 0
for (const [name, needle] of JS_CHECKS) {
  const ok = jsAll.includes(needle)
  if (!ok) jsMiss++
  console.log(`${ok ? "  OK  " : " FAIL "}${name}  →  ${needle}`)
}
console.log(`  JS 特征命中 ${JS_CHECKS.length - jsMiss}/${JS_CHECKS.length}`)
if (jsMiss > 0) failed++

console.log(`\n字节验证结论：${failed === 0 ? "全部通过" : failed + " 项失败"}`)
process.exit(failed === 0 ? 0 : 1)
