// @vitest-environment jsdom
// CR-071（夜审 r8 设计稿推荐 A，r9 实施轮）：web 桥等价性静态钉。
//
// 与桌面侧 tests/main/api-safety-equivalence.test.ts 共享同一份样本集
// （tests/shared/api-safety-samples.ts）——两桥消费同一 shared/api-safety.ts
// 原语 ⇒ 样本判定恒同；web 侧未来单独加/减校验项造成漂移，本测试即红
// （桌面侧样本集漂移由桌面等价性测试捕获，两侧互为镜像）。
//
// 旧 web 桥六缺口（method 白名单／auth 排除／编码双重解码／multipart 静默降级／
// 控制字符区间／body 可序列化）在本轮接共享原语后全部封堵；样本判定
// 「拒」的期望即封堵验收。

import { afterEach, describe, expect, it, vi } from "vitest"

import "../../src/renderer/src/fde-web-bridge" // 注入 window.fde

import type { ApiMethod } from "../../src/shared/contracts"
import {
  BODY_SAMPLES,
  HEADER_SAMPLES,
  METHOD_SAMPLES,
  PATH_SAMPLES,
} from "../shared/api-safety-samples"
import { ENVELOPE_SAMPLES } from "../shared/api-envelope-samples"

function stubFetch(payload: unknown) {
  const fetchMock = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => payload,
  }))
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

async function webJudge(
  kind: "path" | "method" | "body" | "header",
  input: string | unknown,
): Promise<boolean> {
  const fetchMock = stubFetch({ data: {}, error: null })
  const path = kind === "path" ? (input as string) : "/api/v1/projects"
  // method 样本含白名单外值（OPTIONS/TRACE 等）——契约类型是 ApiMethod，
  // 探测面刻意越类型边界喂入，cast 留痕。
  const method = (kind === "method" ? (input as string) : "POST") as ApiMethod
  const request = window.fde.api.request
  const result = kind === "body"
    ? await request(path, { method: "POST", accessToken: "equivalence-probe", body: input })
    : kind === "header"
      ? await request(path, {
          method: "POST",
          accessToken: "equivalence-probe",
          headers: input as Record<string, string>,
        })
      : await request(path, { method, accessToken: "equivalence-probe" })
  const allowed = result.ok === true
  if (allowed) {
    // 放行面必须真实到达 fetch（裸发降级路径的判别信号）
    expect(fetchMock).toHaveBeenCalled()
  }
  return allowed
}

// 获客诊断 T-14a 公开面：捕获 web 桥实际发给 fetch 的请求头。
async function webFetchHeaders(
  path: string,
  options: Record<string, unknown>,
): Promise<Record<string, string>> {
  let seenHeaders: Record<string, string> = {}
  const fetchMock = vi.fn(async (_url: string | URL, init?: RequestInit) => {
    seenHeaders = { ...((init?.headers ?? {}) as Record<string, string>) }
    return { ok: true, status: 200, json: async () => ({ data: {}, error: null }) }
  })
  vi.stubGlobal("fetch", fetchMock)
  const result = await window.fde.api.request(
    path,
    options as unknown as Parameters<typeof window.fde.api.request>[1],
  )
  expect(result.ok).toBe(true)
  return seenHeaders
}

afterEach(() => {
  vi.unstubAllGlobals()
})

// ---------------------------------------------------------------------------
// QR-112（goal-crv-fix2 批 R7）：响应面信封判定 web 侧镜像钉——与桌面侧
// tests/main/api-envelope-equivalence.test.ts 消费同一 ENVELOPE_SAMPLES，
// 两桥 parseApiEnvelope 判定恒同（ok∧error 拒／!ok∧¬error 拒／!ok data 置空／
// 错误体形态校验四处旧缺口封堵后的防再漂移钉）。
// ---------------------------------------------------------------------------
describe("QR-112 响应面信封判定（web 桥侧镜像逐样本）", () => {
  function stubEnvelope(payload: unknown, status: number) {
    const fetchMock = vi.fn(async () => ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => payload,
    }))
    vi.stubGlobal("fetch", fetchMock)
    return fetchMock
  }

  for (const sample of ENVELOPE_SAMPLES) {
    it(`[${sample.status}] ${sample.note}`, async () => {
      stubEnvelope(sample.payload, sample.status)
      const result = await window.fde.api.request("/api/v1/ping", {
        method: "GET",
        accessToken: "equivalence-probe",
      } as unknown as Parameters<typeof window.fde.api.request>[1])
      if (sample.expected.kind === "ok") {
        expect(result.ok).toBe(true)
        if (result.ok) expect(result.data.error).toBeNull()
      } else if (sample.expected.kind === "error") {
        expect(result.ok).toBe(true)
        if (result.ok) {
          expect(result.data.error).not.toBeNull()
          expect(result.data.data).toBeNull()
        }
      } else {
        expect(result.ok).toBe(false)
        if (!result.ok) expect(result.error.code).toBe("invalid_api_response")
      }
    })
  }
})

describe("CR-071 web 桥等价性判定（共享样本集，与桌面恒同）", () => {
  it("路径样本：判定与 expected 逐位一致", async () => {
    for (const sample of PATH_SAMPLES) {
      const actual = await webJudge("path", sample.path)
      expect(
        actual,
        `web 桥路径判定漂移：${sample.path}（${sample.note}）`,
      ).toBe(sample.expected)
    }
  })

  it("method 样本：判定与 expected 逐位一致（旧缺口 1 封堵）", async () => {
    for (const sample of METHOD_SAMPLES) {
      const actual = await webJudge("method", sample.method)
      expect(
        actual,
        `web 桥 method 判定漂移：${JSON.stringify(sample.method)}`,
      ).toBe(sample.expected)
    }
  })

  it("body 样本：判定与 expected 逐位一致（旧缺口 5/7 封堵：非法 multipart 不再无 body 裸发）", async () => {
    for (const sample of BODY_SAMPLES) {
      const actual = await webJudge("body", sample.body)
      expect(
        actual,
        `web 桥 body 判定漂移：${sample.note}`,
      ).toBe(sample.expected)
    }
  })

  it("非法 multipart 形状拒绝时零 fetch（不裸发）", async () => {
    const fetchMock = stubFetch({ data: {}, error: null })
    const result = await window.fde.api.request("/api/v1/projects", {
      method: "POST",
      accessToken: "equivalence-probe",
      body: { kind: "multipart_file", fields: "not-a-record", file: {} },
    })
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error.code).toBe("invalid_request")
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("自定义请求头样本：判定与 expected 逐位一致（T-14a 校验项 9）", async () => {
    for (const sample of HEADER_SAMPLES) {
      const actual = await webJudge("header", sample.headers)
      expect(
        actual,
        `web 桥自定义头判定漂移：${sample.note}`,
      ).toBe(sample.expected)
    }
  })

  it("公开面：空 accessToken 不下发 Authorization，自定义头原样透传", async () => {
    const headers = await webFetchHeaders("/api/v1/diagnostics/questionnaire", {
      method: "GET",
      accessToken: "",
      headers: { "x-diagnostic-token": "diag12" },
    })
    expect(headers.authorization).toBeUndefined()
    expect(headers["x-diagnostic-token"]).toBe("diag12")
  })

  it("非空 accessToken 仍下发 Bearer（公开面扩展零回归）", async () => {
    const headers = await webFetchHeaders("/api/v1/projects", {
      method: "GET",
      accessToken: "probe-token",
    })
    expect(headers.authorization).toBe("Bearer probe-token")
  })
})
