// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"

import { webBridgeSessionState } from "../../src/renderer/src/fde-web-bridge"
// QR-112 换代注记：version 断言与 CR-058 对账钉同源——动态读 package.json version
//（打包轮次 bump 后两侧恒同步，不再硬编码字面量）。
import pkg from "../../package.json"
const pkgVersion = pkg.version as string

const authPayload = {
  data: {
    access_token: "access-1",
    refresh_token: "refresh-1",
    access_expires_at: "2026-11-10T00:00:00Z",
    refresh_expires_at: "2026-11-17T00:00:00Z",
    user: {
      id: "u-1",
      username: "guest-a",
      display_name: "演示账号",
      role: "project_lead",
      must_change_password: false,
      is_active: true,
    },
  },
  error: null,
}

function stubFetch(payload: unknown, status = 200) {
  const fetchMock = vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  }))
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("浏览器版 window.fde 桥", () => {
  it("注入完整契约且不会落到 Web Storage", async () => {
    expect(typeof window.fde.auth.login).toBe("function")
    expect(typeof window.fde.auth.refresh).toBe("function")
    expect(typeof window.fde.auth.changePassword).toBe("function")
    expect(typeof window.fde.auth.logout).toBe("function")
    expect(typeof window.fde.api.request).toBe("function")
    expect(typeof window.fde.bridge.capture).toBe("function")
    expect(typeof window.fde.app.version).toBe("function")
    expect(await window.fde.app.version()).toBe(`${pkgVersion}-web`)
    

    stubFetch(authPayload)
    await window.fde.auth.login({ username: "guest-a", password: "x", deviceLabel: "test" })
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.length).toBe(0)
    expect(webBridgeSessionState()).toEqual({ hasAccess: true, hasRefresh: true, username: "guest-a" })
  })

  it("把服务端 snake_case user 转成 camelCase，并把请求发到同源 /api", async () => {
    const fetchMock = stubFetch(authPayload)
    const result = await window.fde.auth.login({ username: "guest-a", password: "x", deviceLabel: "test" })
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.data.user.displayName).toBe("演示账号")
      expect(result.data.user.role).toBe("project_lead")
      expect(result.data.user.mustChangePassword).toBe(false)
      expect(result.data.accessToken).toBe("access-1")
    }
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe("/api/v1/auth/login")
    expect(init.credentials).toBe("omit")
    expect(JSON.parse(String(init.body))).toMatchObject({ username: "guest-a", device_label: "test" })
  })

  it("拒绝越界路径，不把 access token 发到外部域", async () => {
    const fetchMock = stubFetch({ data: null, error: null })
    const cases = [
      "../etc/passwd",
      "https://evil.example/api/v1/projects",
      "/api/v1/../../admin",
      "/api/v1/projects\\..\\users",
      "/api/v1/x#fragment",
      "//evil.example/api/v1/projects",
    ]
    for (const bad of cases) {
      const result = await window.fde.api.request(bad, { method: "GET", accessToken: "secret-token" })
      expect(result.ok).toBe(false)
      if (!result.ok) expect(result.error.code).toBe("invalid_request")
    }
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("合法路径透传 Bearer 与 JSON body，并保留服务端错误信封", async () => {
    // QR-112 换代注记：错误信封真实形态是 4xx（200+error 属违约形态，由
    // shared parseApiEnvelope 四不变量拒绝——等价性钉样本另有覆盖）。
    const payload = { data: null, error: { code: "password_change_required", message: "请先修改密码" } }
    const fetchMock = stubFetch(payload, 409)
    const result = await window.fde.api.request("/api/v1/projects", {
      method: "POST",
      accessToken: "access-1",
      body: { name: "代号项目" },
    })
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.data.status).toBe(409)
      expect(result.data.error?.code).toBe("password_change_required")
    }
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe("/api/v1/projects")
    expect((init.headers as Record<string, string>).authorization).toBe("Bearer access-1")
    expect(JSON.parse(String(init.body))).toEqual({ name: "代号项目" })
  })

  it("宿主采集能力明确降级，而不是静默成功", async () => {
    const result = await window.fde.bridge.capture()
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error.code).toBe("bridge_platform")
  })

  it("logout 清空内存会话", async () => {
    stubFetch(authPayload)
    await window.fde.auth.login({ username: "guest-a", password: "x", deviceLabel: "test" })
    const result = await window.fde.auth.logout()
    expect(result.ok).toBe(true)
    expect(webBridgeSessionState()).toEqual({ hasAccess: false, hasRefresh: false, username: null })
  })
})


describe("web 桥 openLcscBrowser 域白名单（CR-070）", () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("只放行立创三域 https URL（与桌面 allowsLcscUrl 同尺）", async () => {
    const opened: string[] = []
    vi.spyOn(window, "open").mockImplementation(((url: string) => {
      opened.push(url)
      return null
    }) as typeof window.open)
    await window.fde.app.openLcscBrowser?.("https://www.szlcsc.com/product-detail?code=C123")
    await window.fde.app.openLcscBrowser?.("https://so.szlcsc.com/global.html?k=cap")
    await window.fde.app.openLcscBrowser?.("https://item.szlcsc.com/C123.html")
    expect(opened).toHaveLength(3)
  })

  it("非白名单域不打开（钓鱼/污染 URL 拦截）", async () => {
    const opened: string[] = []
    vi.spyOn(window, "open").mockImplementation(((url: string) => {
      opened.push(url)
      return null
    }) as typeof window.open)
    await window.fde.app.openLcscBrowser?.("https://evil.example.com/C123.html")
    await window.fde.app.openLcscBrowser?.("http://www.szlcsc.com/product-detail")
    await window.fde.app.openLcscBrowser?.("https://www.szlcsc.com.evil.com/x")
    expect(opened).toHaveLength(0)
  })
})
