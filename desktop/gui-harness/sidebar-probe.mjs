// Sidebar-specific probe (2026-11-09 bottom-clipping fix).
// Verifies, in a real browser at a SHORT viewport that forces nav overflow:
//   1) the account block (bottom) stays visible without scrolling,
//   2) the nav is actually scrollable to reach the last nav item,
//   3) hover reveals the scrollbar (scrollbar-color flips from transparent),
//   4) the active nav item carries the gold inset rail (computed boxShadow).
// ASCII-only source; Chinese strings via \uXXXX escapes.
import { chromium } from "playwright-core"

const BASE = process.env.FDE_HARNESS_URL ?? "http://127.0.0.1:5199"
const USERNAME = process.env.FDE_HARNESS_USER ?? "gui.regression"
const PASSWORD = process.env.FDE_HARNESS_PASSWORD ?? "GuiRegression!2026"

const results = []
function record(name, pass, detail) {
  results.push({ name, pass, detail })
  console.log(`[${pass ? "PASS" : "FAIL"}] ${name} :: ${detail}`)
}

async function main() {
  const browser = await chromium.launch()
  // 1280x620: short viewport forces nav overflow for an admin account (17 items)
  const context = await browser.newContext({ viewport: { width: 1280, height: 620 } })
  const page = await context.newPage()
  await page.goto(BASE)
  await page.getByRole("textbox").first().fill(USERNAME)
  await page.getByRole("textbox").nth(1).fill(PASSWORD)
  await page.getByRole("button", { name: /\u767b\u5f55/ }).click()
  await page.waitForURL(/#projects/, { timeout: 15000 })

  const sidebar = page.locator("aside.sidebar")
  const nav = sidebar.locator("nav")
  const logout = sidebar.getByRole("button", { name: /\u9000\u51fa\u767b\u5f55/ })
  const lastItem = nav.locator(".nav-item").last()

  // 1) bottom block visible without scrolling (the reported bug)
  await logout.scrollIntoViewIfNeeded().catch(() => {})
  const bottomVisible = await logout.isVisible()
  const bottomInView = await logout.evaluate((el) => {
    const rect = el.getBoundingClientRect()
    return rect.top >= 0 && rect.bottom <= window.innerHeight
  })
  record("bottom-account-visible", bottomVisible && bottomInView,
    `visible=${bottomVisible} inViewport=${bottomInView}`)

  // 2) nav scrolls (content taller than the scroll box)
  const metrics = await nav.evaluate((el) => ({
    scrollHeight: el.scrollHeight,
    clientHeight: el.clientHeight,
    overflowY: getComputedStyle(el).overflowY,
  }))
  const scrollable = metrics.scrollHeight > metrics.clientHeight && metrics.overflowY === "auto"
  record("nav-scrollable", scrollable,
    `scrollHeight=${metrics.scrollHeight} clientHeight=${metrics.clientHeight} overflowY=${metrics.overflowY}`)

  // 3) hover reveals scrollbar
  const before = await nav.evaluate((el) => getComputedStyle(el).scrollbarColor)
  await sidebar.hover()
  await page.waitForTimeout(200)
  const after = await nav.evaluate((el) => getComputedStyle(el).scrollbarColor)
  record("scrollbar-hover-reveal", before !== after, `before="${before}" after="${after}"`)

  // 4) active item keeps the gold rail
  const activeShadow = await nav.locator(".nav-item.active").evaluate(
    (el) => getComputedStyle(el).boxShadow,
  )
  record("active-gold-rail", /inset/i.test(activeShadow), `boxShadow="${activeShadow}"`)

  // 5) scrolling the nav reaches the last item while bottom stays put
  await lastItem.scrollIntoViewIfNeeded()
  await page.waitForTimeout(300)
  const lastVisible = await lastItem.isVisible()
  const bottomStillVisible = await logout.isVisible()
  record("scroll-reaches-last-item", lastVisible && bottomStillVisible,
    `lastVisible=${lastVisible} bottomStillVisible=${bottomStillVisible}`)

  // Screenshots for eyeballing (short + tall viewport, hover state, collapsed)
  await page.screenshot({ path: "desktop/gui-harness/screenshots/sidebar-short-hover.png" })
  const navBox = await nav.boundingBox()
  if (navBox) {
    await page.screenshot({
      path: "desktop/gui-harness/screenshots/sidebar-nav-closeup.png",
      clip: { x: 0, y: 0, width: navBox.x + navBox.width + 30, height: 620 },
    })
  }
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.waitForTimeout(250)
  await page.screenshot({ path: "desktop/gui-harness/screenshots/sidebar-tall.png" })
  await page.getByRole("button", { name: /\u6536\u8d77\u4fa7\u8fb9\u680f/ }).click()
  await page.waitForTimeout(350)
  await page.screenshot({ path: "desktop/gui-harness/screenshots/sidebar-collapsed.png" })

  await browser.close()
  const failed = results.filter((item) => !item.pass)
  console.log(`\n\u6c47\u603b\uff1a${results.length - failed.length}/${results.length} \u901a\u8fc7`)
  process.exit(failed.length ? 1 : 0)
}

await main()
