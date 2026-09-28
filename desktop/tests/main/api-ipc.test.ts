import { describe, expect, it, vi } from "vitest"
import type { IpcMain, IpcMainInvokeEvent } from "electron"

import { IPC_CHANNELS } from "../../src/shared/contracts"

type ApiRequest = (input: unknown) => Promise<unknown>

async function loadApiModule(): Promise<{
  createApiRequestHandler(options: {
    apiBaseUrl: string
    fetch: typeof fetch
    timeoutMs: number
  }): ApiRequest
  registerApiIpc(options: {
    ipcMain: Pick<IpcMain, "handle">
    request: ApiRequest
    isTrustedSender(event: IpcMainInvokeEvent): boolean
  }): void
}> {
  return import("../../src/main/api-ipc")
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

describe("validated main-process API request bridge", () => {
  it("reports generic API timeouts in Chinese", async () => {
    const fetchMock = vi.fn<typeof fetch>((_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")))
    }))
    const { createApiRequestHandler } = await loadApiModule()
    const request = createApiRequestHandler({
      apiBaseUrl: "https://api.example.test",
      fetch: fetchMock,
      timeoutMs: 10,
    })

    await expect(request({ path: "/api/v1/ai/industry-template/chat", method: "POST", accessToken: "access", body: {} }))
      .rejects.toMatchObject({ code: "request_timeout", message: "AI 或服务端响应超时，请稍后重试。" })
  })

  it("builds a bounded single-file multipart request without a caller-owned content-type", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({ data: { preview_token: "preview" }, error: null }),
    )
    const { createApiRequestHandler } = await loadApiModule()
    const request = createApiRequestHandler({
      apiBaseUrl: "https://api.example.test",
      fetch: fetchMock,
      timeoutMs: 5_000,
    })

    await request({
      path: "/api/v1/projects/p1/research/subjects/imports/preview",
      method: "POST",
      accessToken: "access-token",
      body: {
        kind: "multipart_file",
        fields: { subject_type: "department" },
        file: {
          field_name: "file",
          name: "departments.csv",
          type: "text/csv",
          bytes: new Uint8Array([0xe5, 0x90, 0x8d]),
        },
      },
    })

    const init = fetchMock.mock.calls[0][1]
    expect(init?.body).toBeInstanceOf(FormData)
    expect(init?.headers).toEqual({
      accept: "application/json",
      authorization: "Bearer access-token",
    })
    const body = init?.body as FormData
    expect(body.get("subject_type")).toBe("department")
    expect((body.get("file") as File).name).toBe("departments.csv")
  })

  it.each([
    ["extra top-level key", { kind: "multipart_file", fields: {}, file: { field_name: "file", name: "a.csv", type: "text/csv", bytes: new Uint8Array() }, leaked: true }],
    ["unsafe filename", { kind: "multipart_file", fields: {}, file: { field_name: "file", name: "../a.csv", type: "text/csv", bytes: new Uint8Array() } }],
    ["oversized file", { kind: "multipart_file", fields: {}, file: { field_name: "file", name: "a.csv", type: "text/csv", bytes: new Uint8Array(100 * 1024 * 1024 + 1) } }],
  ])("rejects unsafe multipart bodies: %s", async (_label, body) => {
    const fetchMock = vi.fn<typeof fetch>()
    const { createApiRequestHandler } = await loadApiModule()
    const request = createApiRequestHandler({
      apiBaseUrl: "https://api.example.test",
      fetch: fetchMock,
      timeoutMs: 5_000,
    })

    await expect(request({ path: "/api/v1/projects/p1/research/subjects/imports/preview", method: "POST", accessToken: "a", body }))
      .rejects.toMatchObject({ code: "invalid_request" })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("forwards only the validated relative API request with main-owned headers", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({ data: { items: [] }, error: null }),
    )
    const { createApiRequestHandler } = await loadApiModule()
    const request = createApiRequestHandler({
      apiBaseUrl: "https://api.example.test",
      fetch: fetchMock,
      timeoutMs: 5_000,
    })

    await expect(
      request({
        path: "/api/v1/users?page=1",
        method: "GET",
        accessToken: "access-token",
      }),
    ).resolves.toEqual({ status: 200, data: { items: [] }, error: null })
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/api/v1/users?page=1",
      expect.objectContaining({
        method: "GET",
        headers: {
          accept: "application/json",
          authorization: "Bearer access-token",
        },
        redirect: "error",
      }),
    )
  })

  it.each([
    ["absolute URL", { path: "https://evil.test/api/v1/users", method: "GET", accessToken: "a" }],
    ["protocol-relative URL", { path: "//evil.test/api/v1/users", method: "GET", accessToken: "a" }],
    ["raw traversal", { path: "/api/v1/../secrets", method: "GET", accessToken: "a" }],
    ["encoded traversal", { path: "/api/v1/%2e%2e/secrets", method: "GET", accessToken: "a" }],
    ["control character", { path: "/api/v1/users\nInjected: yes", method: "GET", accessToken: "a" }],
    ["encoded control character", { path: "/api/v1/users%0d%0aInjected", method: "GET", accessToken: "a" }],
    ["fragment", { path: "/api/v1/users#outside", method: "GET", accessToken: "a" }],
    ["method outside allowlist", { path: "/api/v1/users", method: "OPTIONS", accessToken: "a" }],
    ["caller headers", { path: "/api/v1/users", method: "GET", accessToken: "a", headers: { host: "evil.test" } }],
    ["encoded query delimiter escape", { path: "/api/v1/sentinel%3f/%2e%2e/%2e%2e/%2e%2e/health", method: "GET", accessToken: "secret-access-token" }],
    ["uppercase encoded query delimiter escape", { path: "/api/v1/sentinel%3F/%2E%2E/%2E%2E/%2E%2E/health", method: "GET", accessToken: "secret-access-token" }],
    ["double-encoded delimiter escape", { path: "/api/v1/sentinel%253f/%252e%252e/%252e%252e/%252e%252e/health", method: "GET", accessToken: "secret-access-token" }],
    ["encoded slash traversal", { path: "/api/v1/sentinel%2f..%2f..%2f..%2fhealth", method: "GET", accessToken: "secret-access-token" }],
  ])("rejects %s before fetch", async (_label, input) => {
    const fetchMock = vi.fn<typeof fetch>()
    const { createApiRequestHandler } = await loadApiModule()
    const request = createApiRequestHandler({
      apiBaseUrl: "https://api.example.test",
      fetch: fetchMock,
      timeoutMs: 5_000,
    })

    await expect(request(input)).rejects.toMatchObject({ code: "invalid_request" })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("allows only the authenticated password-verification endpoint through the generic bridge", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({ data: { valid: true }, error: null }),
    )
    const { createApiRequestHandler } = await loadApiModule()
    const request = createApiRequestHandler({
      apiBaseUrl: "https://api.example.test",
      fetch: fetchMock,
      timeoutMs: 5_000,
    })

    await expect(request({
      path: "/api/v1/auth/verify-password",
      method: "POST",
      accessToken: "access",
      body: { password: "current-password" },
    })).resolves.toEqual({ status: 200, data: { valid: true }, error: null })
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it.each([
    "/api/v1/auth/login",
    "/api/v1/auth/refresh/",
    "/api/v1/AUTH/change-password",
    "/api/v1/auth/verify-password/",
    "/api/v1/%61uth/logout",
    "/api/v1//auth/login",
    "/api/v1///AUTH/refresh",
  ])("keeps the auth namespace outside the generic bridge: %s", async (path) => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({
        data: { refresh_token: "must-never-reach-renderer" },
        error: null,
      }),
    )
    const { createApiRequestHandler } = await loadApiModule()
    const request = createApiRequestHandler({
      apiBaseUrl: "https://api.example.test",
      fetch: fetchMock,
      timeoutMs: 5_000,
    })

    await expect(request({ path, method: "POST", accessToken: "access" }))
      .rejects.toMatchObject({ code: "invalid_request" })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("returns backend status and error so renderer can apply one-refresh policy", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(
        {
          data: null,
          error: { code: "access_token_expired", message: "Access token expired.", details: {} },
        },
        401,
      ),
    )
    const { createApiRequestHandler } = await loadApiModule()
    const request = createApiRequestHandler({
      apiBaseUrl: "https://api.example.test",
      fetch: fetchMock,
      timeoutMs: 5_000,
    })

    await expect(
      request({
        path: "/api/v1/users",
        method: "GET",
        accessToken: "expired-access-token-secret-123",
      }),
    ).resolves.toEqual({
      status: 401,
      data: null,
      error: { code: "access_token_expired", message: "Access token expired.", details: {} },
    })
  })

  it("redacts sensitive request values from backend error envelopes", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(
        {
          data: null,
          error: {
            code: "invalid_request",
            message: "Temporary password TempPass!2345 is invalid.",
            details: { temporary_password: "TempPass!2345" },
          },
        },
        400,
      ),
    )
    const { createApiRequestHandler } = await loadApiModule()
    const request = createApiRequestHandler({
      apiBaseUrl: "https://api.example.test",
      fetch: fetchMock,
      timeoutMs: 5_000,
    })

    const result = await request({
      path: "/api/v1/users",
      method: "POST",
      accessToken: "access-token-secret-123",
      body: { temporary_password: "TempPass!2345" },
    })

    expect(result).toEqual({
      status: 400,
      data: null,
      error: {
        code: "invalid_request",
        message: "Temporary password [REDACTED] is invalid.",
        details: { temporary_password: "[REDACTED]" },
      },
    })
    expect(JSON.stringify(result)).not.toContain("TempPass!2345")
  })

  it("registers a serializable result and rejects untrusted senders", async () => {
    const { registerApiIpc } = await loadApiModule()
    const registered = new Map<string, (event: IpcMainInvokeEvent, input: unknown) => unknown>()
    const handle = vi.fn((channel: string, listener: (event: IpcMainInvokeEvent, input: unknown) => unknown) => {
      registered.set(channel, listener)
    })
    registerApiIpc({
      ipcMain: { handle } as unknown as Pick<IpcMain, "handle">,
      request: vi.fn(),
      isTrustedSender: () => false,
    })

    const listener = registered.get(IPC_CHANNELS.apiRequest)
    expect(listener).toBeDefined()
    await expect(listener?.({} as IpcMainInvokeEvent, {})).resolves.toEqual({
      ok: false,
      error: {
        code: "unauthorized_ipc",
        message: "The IPC sender is not authorized.",
      },
    })
  })
})
