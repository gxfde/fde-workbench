// 视觉走查截图脚本：登录后逐页截图，输出到 gui-harness/shots/<tag>/。
// 用法：node desktop/gui-harness/shots.mjs <tag> [route...]
import { chromium } from "playwright-core"
import { mkdirSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))
const tag = process.argv[2] ?? "current"
const shotDir = resolve(here, "shots", tag)
mkdirSync(shotDir, { recursive: true })

const BASE = process.env.FDE_HARNESS_URL ?? "http://127.0.0.1:5199"
const USERNAME = process.env.FDE_HARNESS_USER ?? "gui.regression"
const PASSWORD = process.env.FDE_HARNESS_PASSWORD ?? "GuiRegression!2026"

// 路由 hash → 截图名。覆盖主要页面，用于横向比对视觉一致性。
const ROUTES = process.argv.slice(3).length
  ? process.argv.slice(3).map((r) => {
      const [name, hash] = r.split("=")
      return { name, hash }
    })
  : [
      { name: "01-login", hash: "" },
      { name: "02-projects", hash: "#projects" },
      { name: "03-task-center", hash: "#task-center" },
      { name: "04-translator", hash: "#translator" },
      { name: "05-extensions", hash: "#extensions" },
      { name: "06-help", hash: "#help" },
      { name: "07-metrics", hash: "#metrics" },
      { name: "08-pilot", hash: "#pilot" },
      { name: "09-users", hash: "#users" },
      { name: "10-dispatch", hash: "#dispatch" },
      { name: "11-bridge", hash: "#bridge" },
      { name: "12-templates", hash: "#templates" },
      { name: "13-account", hash: "#account" },
    ]

const errors = []

async function main() {
  const browser = await chromium.launch()

  // ① 登录页：用干净 context（无会话）单独截
  const guestCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const guest = await guestCtx.newPage()
  await guest.goto(`${BASE}/`, { waitUntil: "domcontentloaded" })
  await guest.waitForTimeout(1200)
  await guest.screenshot({ path: resolve(shotDir, "01-login.png"), fullPage: true })
  console.log("[shot] 01-login")
  await guestCtx.close()

  // ② 其余页面：登录后逐页截图
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()
  page.on("console", (m) => {
    if (m.type() === "error" && !m.text().includes("frame-ancestors")) errors.push(m.text())
  })
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`))

  await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" })
  await page.fill("#login-username", USERNAME)
  await page.fill("#login-password", PASSWORD)
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await page.waitForTimeout(2500)

  for (const r of ROUTES) {
    if (!r.hash) continue
    await page.goto(`${BASE}/${r.hash}`, { waitUntil: "domcontentloaded" })
    await page.waitForTimeout(1800)
    await page.screenshot({ path: resolve(shotDir, `${r.name}.png`), fullPage: true })
    console.log(`[shot] ${r.name}`)
  }

  console.log(errors.length ? `\n[console errors] ${errors.length}\n` + errors.slice(0, 10).join("\n") : "\n[no console errors]")
  await browser.close()
}

main().catch((e) => { console.error(e); process.exit(1) })
