// @vitest-environment node
// QR-112（goal-crv-fix2 批 R7）：响应面信封判定等价性静态钉。
//
// 共享样本集 tests/shared/api-envelope-samples.ts 的判定在**桌面侧**
// （main/api-ipc.ts::parseApiResponse → shared/api-safety.ts::parseApiEnvelope）
// 逐位断言；web 侧镜像断言在 tests/renderer/fde-web-bridge-equivalence.test.ts。
// 两桥消费同一 shared 判定 ⇒ 样本 verdict 恒同；任一侧单独改判定造成漂移，
// 对应侧测试即红（补齐 web 桥响应面四缺口后的防再漂移钉）。

import { describe, expect, it } from "vitest"

import {
  parseApiEnvelope,
  redactSensitiveString,
  sanitizeEnvelopeDetails,
} from "../../src/shared/api-safety"
import {
  ENVELOPE_SAMPLES,
  REDACTION_SAMPLES,
} from "../shared/api-envelope-samples"

const API_BASE_URL = "http://127.0.0.1:8010"

async function loadApiModule(): Promise<{
  createApiRequestHandler(options: {
    apiBaseUrl: string
    fetch: typeof fetch
    timeoutMs: number
  }): (input: unknown) => Promise<unknown>
}> {
  return import("../../src/main/api-ipc")
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

/** 桌面侧判定：跑真 parseApiResponse，把结果翻译回 shared verdict 形状。 */
async function desktopVerdict(payload: unknown, status: number): Promise<unknown> {
  const { createApiRequestHandler } = await loadApiModule()
  const request = createApiRequestHandler({
    apiBaseUrl: API_BASE_URL,
    fetch: (() => Promise.resolve(jsonResponse(payload, status))) as typeof fetch,
    timeoutMs: 5_000,
  })
  try {
    // createApiRequestHandler 返回 ApiResponse（校验失败抛 ApiIpcError，
    // 与 registerApiIpc 的 BridgeResult 包装分层不同——此处测的就是下层）。
    const body = (await request({
      path: "/api/v1/ping",
      method: "GET",
      accessToken: "tok",
    })) as { status: number; data: unknown; error: unknown }
    if (body.error !== null) return { kind: "error" }
    return { kind: "ok" }
  } catch {
    return { kind: "invalid", reason: "bridged_invalid" }
  }
}

describe("QR-112 响应面信封判定（桌面桥侧逐样本）", () => {
  for (const sample of ENVELOPE_SAMPLES) {
    it(`[${sample.status}] ${sample.note}`, async () => {
      const verdict = await desktopVerdict(sample.payload, sample.status)
      if (sample.expected.kind === "ok") {
        expect(verdict).toEqual({ kind: "ok" })
      } else if (sample.expected.kind === "error") {
        expect(verdict).toEqual({ kind: "error" })
      } else {
        expect(verdict).toMatchObject({ kind: "invalid" })
      }
    })
  }
})

describe("QR-112 脱敏纯函数（shared 单点行为钉）", () => {
  for (const sample of REDACTION_SAMPLES) {
    it(sample.note, () => {
      expect(sanitizeEnvelopeDetails(sample.value, sample.secrets)).toEqual(sample.expected)
    })
  }

  it("redactSensitiveString 空秘钥零改动", () => {
    expect(redactSensitiveString("plain", [])).toBe("plain")
  })
})
