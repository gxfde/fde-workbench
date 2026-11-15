// @vitest-environment node
/**
 * CR-057（夜审 r6 设计稿推荐 A＋D：构建注入）纯函数钉：
 * `buildCspConnectSrc` 派生打包态 CSP connect-src 的行为面。
 *
 * 关键钉（设计稿 §五 红线：本地默认零回归）：
 * - 缺省（apiUrl undefined + 无 oss）⇒ 恒等于本地回环缺省 `http://127.0.0.1:8010`（旧写死值）；
 * - 远程 https API ⇒ connect-src＝该 origin；
 * - OSS 主机 ⇒ 追加 origin（去重）；
 * - 非 http(s) / 解析失败 ⇒ 回落本地回环缺省（更安全，不抛）；
 * - 绝不 `https:` 通配（设计稿 §三 方案 C 否决留痕——只加显式配置的主机）。
 */
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"

import { describe, expect, it } from "vitest"

import { buildCspConnectSrc, DEFAULT_LOCAL_CONNECT_SRC } from "../../src/main/build-csp"

describe("CR-057 buildCspConnectSrc 派生面", () => {
  it("缺省（无 apiUrl 无 oss）＝本地回环缺省（零回归承诺）", () => {
    expect(buildCspConnectSrc()).toBe(DEFAULT_LOCAL_CONNECT_SRC)
    expect(DEFAULT_LOCAL_CONNECT_SRC).toBe("http://127.0.0.1:8010")
    expect(buildCspConnectSrc("")).toBe(DEFAULT_LOCAL_CONNECT_SRC)
  })

  it("远程 https API ⇒ connect-src＝该 origin", () => {
    expect(buildCspConnectSrc("https://app.fde18.com")).toBe("https://app.fde18.com")
    expect(buildCspConnectSrc("https://app.fde18.com")).not.toContain("127.0.0.1")
  })

  it("远程 http API（非 https 也合法打包面）⇒ 取 origin", () => {
    expect(buildCspConnectSrc("http://10.0.0.5:8010")).toBe("http://10.0.0.5:8010")
  })

  it("OSS 主机追加（裸主机默认补 https://）", () => {
    expect(buildCspConnectSrc("https://app.fde18.com", "oss-cn-hangzhou.example.com")).toBe(
      "https://app.fde18.com https://oss-cn-hangzhou.example.com",
    )
  })

  it("OSS 与 API 同 host 去重", () => {
    expect(buildCspConnectSrc("https://bucket.example.com", "bucket.example.com")).toBe(
      "https://bucket.example.com",
    )
  })

  it("本地 API＋OSS：OSS 恒追加（本地形态也可挂 OSS 存储）", () => {
    expect(buildCspConnectSrc(undefined, "https://oss.internal")).toBe(
      "http://127.0.0.1:8010 https://oss.internal",
    )
  })

  it("非 http(s) 协议 ⇒ 回落本地回环缺省（更安全，不抛）", () => {
    expect(buildCspConnectSrc("file:///etc/hosts")).toBe(DEFAULT_LOCAL_CONNECT_SRC)
    expect(buildCspConnectSrc("data:text/html")).toBe(DEFAULT_LOCAL_CONNECT_SRC)
  })

  it("OSS 主机解析失败 ⇒ 不追加、不抛", () => {
    expect(buildCspConnectSrc("https://api.example.com", ":::bad host:::")).toBe(
      "https://api.example.com",
    )
  })

  it("绝不产出 https: 通配（方案 C 否决留痕）", () => {
    const values = [
      buildCspConnectSrc(),
      buildCspConnectSrc("https://api.example.com"),
      buildCspConnectSrc("https://api.example.com", "oss.example.com"),
      buildCspConnectSrc("file:///bad", ":::bad:::"),
    ]
    for (const value of values) {
      expect(value).not.toMatch(/(^|\s)https:$/)
      expect(value).not.toMatch(/(^|\s)https:($|\s)/)
    }
  })
})

describe("CR-057 打包物 CSP 注入静态钉（防写死值回归）", () => {
  const DESKTOP_ROOT = fileURLToPath(new URL("../..", import.meta.url))
  const VITE_CONFIG = readFileSync(join(DESKTOP_ROOT, "electron.vite.config.ts"), "utf-8")

  it("electron.vite 构建链挂接 CSP 注入插件（build-only，不碰 dev）", () => {
    expect(VITE_CONFIG).toMatch(/fde-csp-connect-src-inject/)
    expect(VITE_CONFIG).toMatch(/apply:\s*["']build["']/)
    expect(VITE_CONFIG).toMatch(/buildCspConnectSrc\(/)
  })

  it("桌面与 Web 入口 HTML 的 CSP img-src 均包含 blob:（防 FilePreview 图片预览白屏回归）", () => {
    const indexHtml = readFileSync(join(DESKTOP_ROOT, "src/renderer/index.html"), "utf-8")
    const webHtml = readFileSync(join(DESKTOP_ROOT, "src/renderer/web.html"), "utf-8")
    expect(indexHtml).toContain("img-src 'self' data: blob:;")
    expect(webHtml).toContain("img-src 'self' data: blob:;")
  })
})
