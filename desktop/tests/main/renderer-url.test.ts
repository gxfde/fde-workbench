// G7 缺口④补钉（架构评估 2026-11-07 D9）：渲染器 URL 信任判定的单测。
//
// 此前 allowsRendererUrl（isTrustedSender 的判定核心）内联在 index.ts、零单测
// ——主进程信任边界只有集成覆盖。本文件钉住 config.isAllowedRendererUrl 的
// 三段语义（开发 origin / 打包态 file: 包含性 / 异常一律拒绝），判定本体是
// 纯函数（environment 显式注入），无需 electron 运行时。
import { describe, expect, it } from "vitest"
import { pathToFileURL } from "node:url"
import { resolve } from "node:path"

import { isAllowedRendererUrl } from "../../src/main/config"

const RENDERER_ROOT = resolve("/opt/app/resources/renderer")
const DEV_URL = "http://localhost:5173"

function env(overrides: Partial<{ isPackaged: boolean; developmentUrl?: string }> = {}) {
  return { isPackaged: false, rendererRoot: RENDERER_ROOT, developmentUrl: DEV_URL, ...overrides }
}

describe("isAllowedRendererUrl（渲染器信任边界，G7-④）", () => {
  it("开发态：同 origin 的 http(s) URL 放行，跨 origin / 非 http(s) 拒绝", () => {
    expect(isAllowedRendererUrl("http://localhost:5173/index.html", env())).toBe(true)
    expect(isAllowedRendererUrl(`${DEV_URL}/assets/main-abc.js`, env())).toBe(true)
    expect(isAllowedRendererUrl("http://evil.example/index.html", env())).toBe(false)
    expect(isAllowedRendererUrl("https://localhost:5173/index.html", env())).toBe(false)
    expect(isAllowedRendererUrl("file:///opt/app/resources/renderer/index.html", env())).toBe(false)
  })

  it("打包态：rendererRoot 内的 file: URL 放行（isAllowedRendererUrl 的 file: 分支）", () => {
    const packaged = env({ isPackaged: true, developmentUrl: undefined })
    expect(isAllowedRendererUrl(pathToFileURL(`${RENDERER_ROOT}/index.html`).toString(), packaged)).toBe(true)
    expect(isAllowedRendererUrl(pathToFileURL(`${RENDERER_ROOT}/assets/main.js`).toString(), packaged)).toBe(true)
  })

  it("打包态：带 query 的 file: URL 拒绝（?payload= 注入面）", () => {
    const packaged = env({ isPackaged: true, developmentUrl: undefined })
    const withQuery = `${pathToFileURL(`${RENDERER_ROOT}/index.html`).toString()}?evil=1`
    expect(isAllowedRendererUrl(withQuery, packaged)).toBe(false)
  })

  it("打包态：rendererRoot 之外 / 目录逃逸的 file: URL 拒绝", () => {
    const packaged = env({ isPackaged: true, developmentUrl: undefined })
    expect(isAllowedRendererUrl(pathToFileURL("/opt/app/evil/index.html").toString(), packaged)).toBe(false)
    expect(
      isAllowedRendererUrl(pathToFileURL(`${RENDERER_ROOT}/../evil/index.html`).toString(), packaged),
    ).toBe(false)
  })

  it("打包态：远程协议（https/http）一律拒绝", () => {
    const packaged = env({ isPackaged: true, developmentUrl: undefined })
    expect(isAllowedRendererUrl("https://evil.example/index.html", packaged)).toBe(false)
    expect(isAllowedRendererUrl("http://127.0.0.1:8010/", packaged)).toBe(false)
  })

  it("异常输入（无法解析的 URL）一律拒绝", () => {
    expect(isAllowedRendererUrl("not-a-url", env())).toBe(false)
    expect(isAllowedRendererUrl("", env())).toBe(false)
  })
})
