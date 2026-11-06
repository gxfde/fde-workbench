import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

import { walkSourceFiles } from "./source-walk"

/**
 * 设计令牌静态守卫（B / S0）
 *
 * 与 brand-hardcode.test.ts 同属「静态文本闸」：不启动 Electron、不渲染 React、
 * 不改写任何既有用例。docs/tokens.json 是配色与视觉变量的唯一规范真源，
 * 运行时 :root 是它的镜像；本文件负责让两者不再各自漂移。
 *
 * 对应方案：docs/UI-UX美化方案-v2.md §3.0 B0 / §3.5 F7 / §6 验收。
 */

const REPO_ROOT = fileURLToPath(new URL("../../..", import.meta.url))
const read = (relative: string): string =>
  readFileSync(join(REPO_ROOT, relative), "utf8")

const styles = read("desktop/src/renderer/src/styles.css")
const site = read("site/index.html")
const tokens = JSON.parse(read("docs/tokens.json")) as {
  color: {
    brand: {
      primary: { value: string }
      accent: { value: string }
      accentOnDark: { value: string }
      interactive: { value: string }
      interactiveDeep: { value: string }
    }
    background: {
      page: { value: string }
      surface: { value: string }
      print: { value: string }
      dark: { value: string }
      darkAlt: { value: string }
      sidebarB: { value: string }
    }
    text: {
      primary: { value: string }
      secondary: { value: string }
      siteScale: { ink3: { value: string }; ink4: { value: string }; ink5: { value: string } }
    }
    border: { default: { value: string }; buttonPrimary: { value: string }; official: { value: string } }
    status: {
      success: { base: string }
      warning: { base: string }
      danger: { base: string }
      info: { base: string; border: string }
    }
    button: { primary: { text: { value: string }; background: { value: string } } }
  }
}

/** 抽出某个选择器的声明块（CSS 内无嵌套花括号，够用且不会误吞相邻规则）。 */
function block(source: string, selector: string): string {
  const start = source.indexOf(selector)
  if (start < 0) return ""
  const open = source.indexOf("{", start)
  const close = source.indexOf("}", open)
  if (open < 0 || close < 0) return ""
  return source.slice(open + 1, close)
}

/** 静态文本检测前剥离 CSS 注释，避免「说明文字里写了某个变量名」被当成真实引用。 */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "")
}

/** 剥离 TS/TSX 的行注释与块注释，避免说明文字里的字样被当成真实代码。 */
function stripTsComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
}

/** 抽出 :root 中的自定义属性声明。 */
function rootDeclarations(): Map<string, string> {
  const rootBlock = stripComments(block(styles, ":root {"))
  const declarations = new Map<string, string>()
  for (const match of rootBlock.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    declarations.set(match[1].trim(), match[2].trim())
  }
  return declarations
}

function collectTsx(dir: string): string[] {
  return walkSourceFiles(dir, (name) => name.endsWith(".tsx"))
}

const root = rootDeclarations()

describe("设计令牌 · 单一真源与 :root 一致性", () => {
  it("docs/tokens.json 可解析且核心色值与运行时 :root 逐项一致", () => {
    const expected: Array<[string, string]> = [
      ["--brand-ink", tokens.color.brand.primary.value],
      ["--brand-gold", tokens.color.brand.accent.value],
      ["--brand-blue", tokens.color.brand.interactive.value],
      ["--gold-5", tokens.color.brand.interactiveDeep.value],
      ["--bg", tokens.color.background.page.value],
      ["--surface", tokens.color.background.surface.value],
      ["--text", tokens.color.text.primary.value],
      ["--muted", tokens.color.text.secondary.value],
      ["--line", tokens.color.border.default.value],
      ["--success", tokens.color.status.success.base],
      ["--warning", tokens.color.status.warning.base],
      ["--danger", tokens.color.status.danger.base],
      ["--info", tokens.color.status.info.base],
      ["--info-border", tokens.color.status.info.border],
    ]
    for (const [name, value] of expected) {
      expect(root.get(name)?.toUpperCase(), `${name} 应与 tokens.json 一致`).toBe(
        value.toUpperCase(),
      )
    }
  })

  it("不存在对未定义变量的引用，重复令牌已别名化", () => {
    expect(stripComments(styles)).not.toMatch(/var\(--primary\)/)
    expect(root.get("--blue-pale-border")).toBe("var(--info-border)")
    expect(root.get("--radius-lg")).toBe("var(--radius)")
  })

  it("深底文字令牌与语义色小字加深令牌已建立", () => {
    for (const name of [
      "--on-dark-primary",
      "--on-dark-secondary",
      "--on-dark-muted",
      "--on-dark-disabled",
      "--success-ink",
      "--warning-ink",
      "--danger-ink",
      "--info-ink",
      "--opacity-disabled",
    ]) {
      expect(root.has(name), `${name} 应已在 :root 定义`).toBe(true)
    }
    expect(block(styles, ".sidebar-account .app-version {")).not.toMatch(/11px/)
  })
})

describe("主按钮（B1 / D4）· 两处选择器族默认态与 hover 态", () => {
  const expectedText = tokens.color.button.primary.text.value
  const expectedBackground = tokens.color.button.primary.background.value

  it("桌面端 .primary-button 为白底 + 石墨黑文字 + 达标金描边，hover 保持白底", () => {
    const base = block(styles, ".primary-button {")
    const hover = block(styles, ".primary-button:hover:not(:disabled) {")
    expect(base).toContain("background: var(--surface)")
    expect(base).toContain("color: var(--brand-ink)")
    expect(base).toContain("border: 1px solid var(--gold-5)")
    expect(base).not.toContain("brand-gradient")
    expect(hover).toContain("background: var(--surface)")
    expect(hover).toContain("border-color: var(--gold-5)")
    expect(hover).not.toContain("brand-gradient")
    expect(hover).not.toContain("filter: brightness")
    // 描边色对白底须 ≥3:1：#C98F2B 只有 2.82:1，故使用 --gold-5（4.21:1）
    expect(root.get("--gold-5")?.toUpperCase()).toBe(
      tokens.color.border.buttonPrimary.value.toUpperCase(),
    )
    expect(expectedText).toBe("#14181C")
    expect(expectedBackground).toBe("#FFFFFF")
  })

  it("官网 .btn-gold 为白底 + 石墨黑文字，hover 不再以 --gold-deep 作背景", () => {
    const base = block(site, ".btn-gold{")
    const hover = block(site, ".btn-gold:hover{")
    expect(base).toContain("background:var(--card)")
    expect(base).toContain("color:var(--ink)")
    expect(base).toContain("border-color:var(--gold-deep)")
    expect(base).not.toContain("brand-gradient")
    expect(hover).toContain("background:var(--card)")
    expect(hover).toContain("border-color:var(--gold-deep)")
    expect(hover).not.toContain("background:var(--gold-deep)")
    expect(hover).not.toContain("background: var(--gold-deep)")
  })
})

describe("--brand-gradient 降级为非交互展示面", () => {
  it("交互控件（主按钮 / 官网 CTA / 侧栏激活态 / 两个 tab 激活态）不再铺渐变", () => {
    for (const [source, selector] of [
      [styles, ".primary-button {"] as const,
      [styles, ".primary-button:hover:not(:disabled) {"] as const,
      [styles, ".nav-item.active {"] as const,
      [styles, ".template-editor-tabs button.active {"] as const,
      [styles, ".detail-tabs a.active {"] as const,
      [site, ".btn-gold{"] as const,
      [site, ".btn-gold:hover{"] as const,
    ]) {
      expect(block(source, selector), `${selector} 应存在且不含渐变`).not.toContain(
        "brand-gradient",
      )
    }
  })

  it("展示面仍保留品牌渐变（文字渐变 / 装饰条 / 进度条 / 甘特条）", () => {
    expect(styles).toContain("progress::-webkit-progress-value { background: var(--brand-gradient)")
    expect(styles).toContain(".gantt-bar > span { position: absolute; inset: 0 auto 0 0; background: var(--brand-gradient)")
    expect(styles).toContain(".completion-value { background: var(--brand-gradient)")
    expect(styles).toContain(".project-completion { display: block; background: var(--brand-gradient)")
  })
})

describe("S0 · 焦点与可读性", () => {
  it("全局焦点环统一为 2px 实心亮金 + offset 2px，不再有 3px/4px 混用", () => {
    expect(styles).toContain("outline: 2px solid var(--brand-gold-bright)")
    expect(styles).not.toContain("outline: 3px solid var(--brand-focus)")
    expect(styles).not.toContain("outline-offset: 4px")
    expect(styles).not.toContain("outline-offset:3px")
  })

  it("语义色 12px 小字使用加深 ink 色，soft 底与边框不变", () => {
    expect(styles).toContain(".badge.success, .badge.ok { background: var(--success-soft); color: var(--success-ink); }")
    expect(styles).toContain(".notice { border: 1px solid var(--success-border); background: var(--success-soft); color: var(--success-ink); }")
    expect(styles).toContain("color: var(--danger-ink)")
    expect(styles).toContain("color: var(--warning-ink)")
    expect(styles).toContain("color: var(--info-ink)")
  })
})

describe("S0 起禁止新增原生确认旁路（裁决 4）", () => {
  // 2026-11-06 S2 归一后实测 8 处：均为「必须同步返回 boolean」的
  // registerHashNavigationGuard 守卫回调与同步关闭流程，不能改成异步 Modal，
  // 否则切页保护会失效。其余 8 处已改走 ConfirmProvider / ToastProvider。
  // 本守卫锁「不得新增」，不改写既有用例；S2 后续归一时同步下调此值。
  const BASELINE_NATIVE_CONFIRM_CALLS = 8

  it("window.confirm / window.alert 调用数不超过实施基线", () => {
    const srcDir = join(REPO_ROOT, "desktop/src/renderer/src")
    const hits = collectTsx(srcDir).reduce((total, file) => {
      const source = readFileSync(file, "utf8")
      return total + (source.match(/window\.(?:confirm|alert)/g) ?? []).length
    }, 0)
    expect(hits, "如需新增原生确认，请改走统一 Modal（见方案 F6 / 裁决 4）").toBeLessThanOrEqual(
      BASELINE_NATIVE_CONFIRM_CALLS,
    )
  })
})

describe("S2 · 弹窗与表单语义归一", () => {
  const srcDir = join(REPO_ROOT, "desktop/src/renderer/src")

  it("不再使用原生 <dialog> 元素（统一走 Modal 原语）", () => {
    const offenders = collectTsx(srcDir).filter((file) =>
      /<dialog[\s>]/.test(stripTsComments(readFileSync(file, "utf8"))),
    )
    expect(
      offenders.map((file) => file.slice(REPO_ROOT.length + 1).replace(/\\/g, "/")),
      "原生 <dialog> 缺 aria-modal / 焦点陷阱，请改走 components/ui 的 Modal 原语（见方案 F6）",
    ).toEqual([])
  })

  it("DangerConfirmDialog 仍保留密码二次校验（人工确认强度不降）", () => {
    const source = readFileSync(join(srcDir, "common/DangerConfirmDialog.tsx"), "utf8")
    expect(source, "必须校验当前账号密码").toContain("/api/v1/auth/verify-password")
    expect(source, "必须保留密码输入框").toContain('type="password"')
    expect(source, "必须保留 aria-describedby 关联").toContain("aria-describedby")
    // 呈现层已吸收到 Modal 原语
    expect(source, "应使用统一 Modal 原语").toContain('from "../components/ui"')
  })

  it("label 与控件显式关联（htmlFor + id），无游离 label", () => {
    const offenders: string[] = []
    for (const file of collectTsx(srcDir)) {
      const source = stripTsComments(readFileSync(file, "utf8"))
      for (const match of source.matchAll(/<label(?![^>]*htmlFor)[^>]*>(.*?)<\/label>/gs)) {
        const body = match[1]
        // 隐式关联：label 内直接包含控件 → 有效
        if (/<(input|select|textarea)\b/.test(body)) continue
        offenders.push(file.slice(REPO_ROOT.length + 1).replace(/\\/g, "/"))
      }
    }
    expect(
      [...new Set(offenders)],
      "以下 label 未关联任何控件，请补 htmlFor + id（见无障碍规范-v1.md §4）",
    ).toEqual([])
  })

  it("二级 tab 统一为 role=tablist + aria-selected", () => {
    for (const rel of ["dispatch/DispatchPage.tsx", "projects/ProjectDetailPage.tsx"]) {
      const source = readFileSync(join(srcDir, rel), "utf8")
      expect(source, `${rel} 缺 role="tablist"`).toContain('role="tablist"')
      expect(source, `${rel} 缺 aria-selected`).toContain("aria-selected")
      expect(source, `${rel} 缺 role="tabpanel"`).toContain('role="tabpanel"')
    }
  })

  it("详情页提供「上级 › 当前」面包屑（仅展示，不新增路由）", () => {
    for (const rel of ["projects/ProjectDetailPage.tsx", "dispatch/DispatchPage.tsx"]) {
      const source = readFileSync(join(srcDir, rel), "utf8")
      expect(source, `${rel} 缺面包屑`).toContain('className="breadcrumb"')
      expect(source, `${rel} 面包屑缺 aria-current`).toContain('aria-current="page"')
    }
  })
})

/** S3：收集 8 个 CSS 文件（去注释后）的正文。 */
function collectCssBodies(): Array<{ file: string; body: string }> {
  const cssDir = join(REPO_ROOT, "desktop/src/renderer/src")
  const out: Array<{ file: string; body: string }> = []
  for (const full of walkSourceFiles(cssDir, (name) => name.endsWith(".css"))) {
    out.push({
      file: full.slice(REPO_ROOT.length + 1).replace(/\\/g, "/"),
      body: stripComments(readFileSync(full, "utf8")),
    })
  }
  return out
}

describe("S3 · 数值治理：z-index / 字号 / 阴影只允许走令牌", () => {
  const cssFiles = collectCssBodies()

  it("行高只允许走 --lh-* 令牌（单行元素的 line-height:1 除外）", () => {
    // 2026-11-06 S3 收口：原为 13 种行高散值，按方案 C6「新增 --lh-tight/--lh-body/
    // --lh-relaxed」就近归并到 3 档，89 处收敛完成。
    // `line-height: 1` 是图标/单行元素的语义值（不需行距），保留但计数。
    const offenders: string[] = []
    let singleLine = 0
    for (const entry of cssFiles) {
      for (const match of entry.body.matchAll(/line-height\s*:\s*([0-9]*\.?[0-9]+)/g)) {
        if (match[1] === "1") {
          singleLine++
          continue
        }
        offenders.push(`${entry.file}: line-height: ${match[1]}`)
      }
    }
    expect(
      offenders,
      `以下行高未走令牌，请改用 --lh-tight/--lh-body/--lh-relaxed：\n${offenders.join("\n")}`,
    ).toEqual([])
    expect(singleLine, "line-height:1 只用于图标/单行元素，出现过多说明误改").toBeLessThanOrEqual(10)
  })

  it("同名 @keyframes 不重复定义（方案 G4）", () => {
    const seen = new Map<string, string[]>()
    for (const entry of cssFiles) {
      for (const match of entry.body.matchAll(/@keyframes\s+([\w-]+)/g)) {
        const name = match[1]
        if (!seen.has(name)) seen.set(name, [])
        seen.get(name)!.push(entry.file)
      }
    }
    const duplicates = [...seen.entries()]
      .filter(([, files]) => files.length > 1)
      .map(([name, files]) => `${name} × ${files.length}（${files.join(", ")}）`)
    expect(
      duplicates,
      `同名 @keyframes 重复定义，后定义者会覆盖前者（见方案 G4）：\n${duplicates.join("\n")}`,
    ).toEqual([])
  })

  it("C7 高对比与动效适配存在（prefers-contrast / forced-colors / reduced-motion）", () => {
    const all = cssFiles.map((entry) => entry.body).join("\n")
    expect(all, "缺 @media (prefers-contrast: more)").toContain("prefers-contrast: more")
    expect(all, "缺 @media (forced-colors: active)").toContain("forced-colors: active")
    expect(all, "缺 @media (prefers-reduced-motion: reduce)").toContain("prefers-reduced-motion: reduce")
  })

  it("z-index 全部取自 --z-* 令牌，无裸数值", () => {    const offenders = cssFiles
      .map((file) => ({
        file: file.file,
        hits: file.body.match(/z-index\s*:\s*\d+/g) ?? [],
      }))
      .filter((entry) => entry.hits.length > 0)
    expect(
      offenders,
      `以下文件仍有裸 z-index，请改用 --z-base/--z-sticky/--z-dropdown/--z-rail/--z-float/--z-float-top：\n${offenders
        .map((entry) => `${entry.file}: ${entry.hits.join(", ")}`)
        .join("\n")}`,
    ).toEqual([])
  })

  it("z-index 令牌已在 :root 定义", () => {
    for (const name of [
      "--z-base",
      "--z-sticky",
      "--z-dropdown",
      "--z-rail",
      "--z-float",
      "--z-float-top",
    ]) {
      expect(root.has(name), `:root 缺少 ${name}`).toBe(true)
    }
  })

  it("字体字号不再出现裸 px（C6 字阶锁档已完成）", () => {
    // 2026-11-06 S3 收口：此前残留 15 处散值（15/17/18/19/22/23/24/26px），
    // 已按方案 C6「字阶锁 5 档 + 26/28px 归并」全部收敛到语义档位：
    //   --font-card (15) / --font-title (20) / --font-display (24) / --size-icon (22)
    // 图标字形尺寸（chevron、拖拽手柄）走 --size-icon，不属文字层级。
    // 现已零散值，白名单移除——新增裸 px 会被本守卫拦下。
    const offenders: string[] = []
    for (const entry of cssFiles) {
      for (const match of entry.body.matchAll(/font-size\s*:\s*(\d+px)/g)) {
        offenders.push(`${entry.file}: font-size: ${match[1]}`)
      }
    }
    expect(
      offenders,
      `以下字号未走字阶令牌，请改用 --font-tiny/--font-micro/--font-caption/--font-label/--font-body/--font-card/--font-section/--font-title/--font-display/--font-page（图标用 --size-icon）：\n${offenders.join("\n")}`,
    ).toEqual([])
  })

  it("阴影不出现令牌误用（把阴影值拼进 box-shadow 当颜色）", () => {
    // 误用形态：`box-shadow: 0 1px 3px var(--shadow-sm)` —— 阴影令牌被当成颜色拼进阴影值。
    // 合法形态：多段阴影里阴影令牌独占一段，如
    //   `box-shadow: 0 0 0 1px var(--gold-5), var(--shadow-brand-hover)`。
    // 因此按逗号分段：某段内既有数值又有阴影令牌 → 误用。
    const offenders: string[] = []
    for (const entry of cssFiles) {
      for (const match of entry.body.matchAll(/box-shadow\s*:\s*([^;]+);/g)) {
        const segments = match[1].split(",").map((part) => part.trim())
        for (const segment of segments) {
          if (!segment.includes("var(--shadow")) continue
          // 该段除阴影令牌外还有别的内容 → 令牌被拼进了阴影值
          const withoutToken = segment.replace(/var\(--shadow[\w-]*\)/g, "").trim()
          if (withoutToken.length > 0) {
            offenders.push(`${entry.file}: ${match[1].trim()}`)
            break
          }
        }
      }
    }
    expect(
      offenders,
      `阴影令牌被当成颜色拼进 box-shadow（属语法错误，见方案 G6）：\n${offenders.join("\n")}`,
    ).toEqual([])
  })

  it("box-shadow 不出现裸 rgba 阴影（焦点环与 inset 描边除外）", () => {
    const offenders: string[] = []
    for (const entry of cssFiles) {
      for (const match of entry.body.matchAll(/box-shadow\s*:\s*([^;]+);/g)) {
        const value = match[1].trim()
        if (value === "none") continue
        // 整段都含令牌 → 已归一（含多段阴影）
        if (value.includes("var(--shadow")) continue
        // 焦点环（0 0 0 Npx var(--brand-*)）与 inset 描边保留
        if (/^0 0 0 \d+px var\(/.test(value)) continue
        if (/^inset /.test(value) && value.includes("var(")) continue
        offenders.push(`${entry.file}: ${value}`)
      }
    }
    expect(
      offenders,
      `以下 box-shadow 仍是裸数值，请补 --shadow-* 令牌：\n${offenders.join("\n")}`,
    ).toEqual([])
  })
})

/** 抽出官网 site/index.html 的 :root 令牌。 */
function siteRootDeclarations(): Map<string, string> {
  const rootBlock = stripComments(block(site, ":root{"))
  const declarations = new Map<string, string>()
  for (const match of rootBlock.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    declarations.set(match[1].trim(), match[2].trim())
  }
  return declarations
}

const siteRoot = siteRootDeclarations()

describe("官网 site/index.html · 令牌与真源一致", () => {
  // 官网侧令牌此前只存在于 site/index.html，docs/tokens.json 未登记 →
  // 官网改色不会触发任何守卫（真源治理薄弱点）。本块把官网侧钉死。
  const expected: Array<[string, string]> = [
    ["--paper", tokens.color.background.page.value],
    ["--paper-2", tokens.color.background.print.value],
    ["--card", tokens.color.background.surface.value],
    ["--dark-bg", tokens.color.background.dark.value],
    ["--dark-bg-2", tokens.color.background.darkAlt.value],
    ["--ink-2", tokens.color.background.sidebarB.value],
    ["--ink-3", tokens.color.text.siteScale.ink3.value],
    ["--ink-4", tokens.color.text.siteScale.ink4.value],
    ["--ink-5", tokens.color.text.siteScale.ink5.value],
    ["--line", tokens.color.border.official.value],
    ["--gold", tokens.color.brand.accent.value],
    ["--gold-lt", tokens.color.brand.accentOnDark.value],
    ["--gold-ink", tokens.color.brand.interactive.value],
    ["--gold-deep", tokens.color.brand.interactiveDeep.value],
    ["--ink", tokens.color.brand.primary.value],
  ]

  it("官网 :root 令牌值与 docs/tokens.json 逐项一致", () => {
    for (const [name, value] of expected) {
      expect(siteRoot.get(name)?.toUpperCase(), `官网 ${name} 应与 tokens.json 一致`).toBe(
        value.toUpperCase(),
      )
    }
  })

  it("官网 :root 令牌全部已在 tokens.json 登记（无游离色值）", () => {
    const known = new Set(expected.map(([name]) => name))
    const unregistered = [...siteRoot.keys()].filter((name) => !known.has(name))
    expect(
      unregistered,
      `以下官网令牌未在 docs/tokens.json 登记，请补登记或纳入 expected：\n${unregistered.join("\n")}`,
    ).toEqual([])
  })

  it("官网 --line 与桌面端 --line 的 1 级差为已登记现状（未擅自收敛）", () => {
    // tokens.json 已注明「与桌面端 --line 有 1 级差，待治理收敛」。
    // 本守卫钉住「差值仍在、且两端各自与真源一致」，
    // 待治理时改官网 --line 会自动报红，避免无声漂移。
    expect(siteRoot.get("--line")?.toUpperCase()).toBe(
      tokens.color.border.official.value.toUpperCase(),
    )
    expect(root.get("--line")?.toUpperCase()).toBe(
      tokens.color.border.default.value.toUpperCase(),
    )
    expect(tokens.color.border.official.value.toUpperCase()).not.toBe(
      tokens.color.border.default.value.toUpperCase(),
    )
  })
})
