import { describe, expect, it, vi } from "vitest"

import { createApiClient } from "../../src/renderer/src/api/client"
import type {
  ApiResponse,
  BridgeResult,
  UserDto,
} from "../../src/shared/contracts"

interface SessionSnapshot {
  generation: number
  userId: string
  accessToken: string
  accessExpiresAt: string
}

const userA: UserDto = {
  id: "1b7a50b8-5f95-4ad5-b1a0-b72d0a86c345",
  username: "admin.a",
  displayName: "Admin A",
  role: "admin",
  mustChangePassword: false,
  isActive: true,
}

const userB: UserDto = {
  ...userA,
  id: "2c8b61c9-60a6-4be6-a2b1-c83e1b97d456",
  username: "admin.b",
  displayName: "Admin B",
}

function snapshot(
  generation: number,
  user: UserDto,
  accessToken: string,
): SessionSnapshot {
  return { generation, userId: user.id, accessToken, accessExpiresAt: "2026-08-28T18:30:00.000Z" }
}

function ok<T>(data: T): BridgeResult<T> {
  return { ok: true, data }
}

function apiOk<T>(data: T): BridgeResult<ApiResponse<T>> {
  return ok({ status: 200, data, error: null })
}

function unauthorized<T>(): BridgeResult<ApiResponse<T>> {
  return ok({
    status: 401,
    data: null,
    error: { code: "access_token_expired", message: "expired" },
  })
}

function deferred<T>(): { promise: Promise<T>; resolve(value: T): void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolver) => {
    resolve = resolver
  })
  return { promise, resolve }
}

function clientHarness(initial: SessionSnapshot) {
  let current: SessionSnapshot | null = initial
  const request = vi.fn()
  const refreshAccess = vi.fn()
  const onUnauthorized = vi.fn()
  const adapter = {
    getSessionSnapshot: () => current,
    refreshAccess,
    onUnauthorized,
  }
  const apiRequest = createApiClient(
    { request } as never,
    adapter as never,
  )
  return {
    apiRequest,
    request,
    refreshAccess,
    onUnauthorized,
    setCurrent(next: SessionSnapshot | null) {
      current = next
    },
  }
}

describe("renderer API session race boundary", () => {
  it("does not return a delayed initial 200 after the user switches", async () => {
    const first = deferred<BridgeResult<ApiResponse<{ secret: string }>>>()
    const harness = clientHarness(snapshot(1, userA, "user-a-access"))
    harness.request.mockReturnValueOnce(first.promise)

    const result = harness.apiRequest<{ secret: string }>("/api/v1/users", {
      method: "GET",
    })
    harness.setCurrent(snapshot(2, userB, "user-b-access"))
    first.resolve(apiOk({ secret: "old-user-data" }))

    await expect(result).rejects.toMatchObject({ code: "stale_session_response" })
  })

  it("does not surface a delayed initial transport error after the user switches", async () => {
    const first = deferred<BridgeResult<ApiResponse<{ secret: string }>>>()
    const harness = clientHarness(snapshot(1, userA, "user-a-access"))
    harness.request.mockReturnValueOnce(first.promise)

    const result = harness.apiRequest<{ secret: string }>("/api/v1/users", {
      method: "GET",
    })
    harness.setCurrent(snapshot(2, userB, "user-b-access"))
    first.resolve({
      ok: false,
      error: { code: "network_error", message: "old-user-transport-error" },
    })

    await expect(result).rejects.toMatchObject({ code: "stale_session_response" })
  })

  it("rejects a delayed initial 401 after the access token changes", async () => {
    const old = snapshot(4, userA, "old-access")
    const fresh = snapshot(4, userA, "fresh-access")
    const first = deferred<BridgeResult<ApiResponse<{ items: string[] }>>>()
    const harness = clientHarness(old)
    harness.request
      .mockReturnValueOnce(first.promise)

    const result = harness.apiRequest<{ items: string[] }>("/api/v1/users", {
      method: "GET",
    })
    harness.setCurrent(fresh)
    first.resolve(unauthorized())

    await expect(result).rejects.toMatchObject({ code: "stale_session_response" })
    expect(harness.refreshAccess).not.toHaveBeenCalled()
    expect(harness.request).toHaveBeenCalledOnce()
  })

  it("uses a concurrent fresh token when it changes at the refresh boundary", async () => {
    const old = snapshot(5, userA, "old-access")
    const fresh = snapshot(5, userA, "fresh-access")
    const harness = clientHarness(old)
    harness.request
      .mockResolvedValueOnce(unauthorized())
      .mockResolvedValueOnce(apiOk({ items: ["fresh"] }))
    harness.refreshAccess.mockImplementationOnce(async () => {
      harness.setCurrent(fresh)
      return null
    })

    const result = harness.apiRequest<{ items: string[] }>("/api/v1/users", {
      method: "GET",
    })

    await expect(result).resolves.toEqual({ items: ["fresh"] })
    expect(harness.request).toHaveBeenNthCalledWith(
      2,
      "/api/v1/users",
      expect.objectContaining({ accessToken: "fresh-access" }),
    )
    expect(harness.onUnauthorized).not.toHaveBeenCalled()
  })

  it("ignores a delayed 401 from a prior logout/login generation", async () => {
    const first = deferred<BridgeResult<ApiResponse<{ items: string[] }>>>()
    const harness = clientHarness(snapshot(7, userA, "user-a-access"))
    harness.request.mockReturnValueOnce(first.promise)

    const result = harness.apiRequest<{ items: string[] }>("/api/v1/users", {
      method: "GET",
    })
    harness.setCurrent(snapshot(9, userB, "user-b-access"))
    first.resolve(unauthorized())

    await expect(result).rejects.toMatchObject({ code: "stale_session_response" })
    expect(harness.request).toHaveBeenCalledOnce()
    expect(harness.refreshAccess).not.toHaveBeenCalled()
    expect(harness.onUnauthorized).not.toHaveBeenCalled()
  })

  it("does not retry under a new user when the session switches during refresh", async () => {
    const old = snapshot(11, userA, "old-access")
    const refresh = deferred<SessionSnapshot | null>()
    const harness = clientHarness(old)
    harness.request.mockResolvedValueOnce(unauthorized())
    harness.refreshAccess.mockReturnValueOnce(refresh.promise)

    const result = harness.apiRequest<{ items: string[] }>("/api/v1/users", {
      method: "GET",
    })
    await vi.waitFor(() => expect(harness.refreshAccess).toHaveBeenCalledOnce())
    harness.setCurrent(snapshot(13, userB, "user-b-access"))
    refresh.resolve(snapshot(11, userA, "fresh-old-user-access"))

    await expect(result).rejects.toMatchObject({ code: "stale_session_response" })
    expect(harness.request).toHaveBeenCalledOnce()
    expect(harness.onUnauthorized).not.toHaveBeenCalled()
  })

  it("does not clear a new session when a retried GET returns a delayed 401", async () => {
    const old = snapshot(15, userA, "old-access")
    const fresh = snapshot(15, userA, "fresh-access")
    const retry = deferred<BridgeResult<ApiResponse<{ items: string[] }>>>()
    const harness = clientHarness(old)
    harness.request
      .mockResolvedValueOnce(unauthorized())
      .mockReturnValueOnce(retry.promise)
    harness.refreshAccess.mockImplementationOnce(async () => {
      harness.setCurrent(fresh)
      return fresh
    })

    const result = harness.apiRequest<{ items: string[] }>("/api/v1/users", {
      method: "GET",
    })
    await vi.waitFor(() => expect(harness.request).toHaveBeenCalledTimes(2))
    harness.setCurrent(snapshot(17, userB, "user-b-access"))
    retry.resolve(unauthorized())

    await expect(result).rejects.toMatchObject({ code: "stale_session_response" })
    expect(harness.onUnauthorized).not.toHaveBeenCalled()
  })

  it("does not return old-user data when a retried GET 200 arrives after session switch", async () => {
    const old = snapshot(16, userA, "old-access")
    const fresh = snapshot(16, userA, "fresh-access")
    const retry = deferred<BridgeResult<ApiResponse<{ items: string[] }>>>()
    const harness = clientHarness(old)
    harness.request
      .mockResolvedValueOnce(unauthorized())
      .mockReturnValueOnce(retry.promise)
    harness.refreshAccess.mockImplementationOnce(async () => {
      harness.setCurrent(fresh)
      return fresh
    })

    const result = harness.apiRequest<{ items: string[] }>("/api/v1/users", {
      method: "GET",
    })
    await vi.waitFor(() => expect(harness.request).toHaveBeenCalledTimes(2))
    harness.setCurrent(snapshot(18, userB, "user-b-access"))
    retry.resolve(apiOk({ items: ["old-user-private-data"] }))

    await expect(result).rejects.toMatchObject({ code: "stale_session_response" })
    expect(harness.onUnauthorized).not.toHaveBeenCalled()
  })

  it("does not surface an old-session retry transport error after session switch", async () => {
    const old = snapshot(19, userA, "old-access")
    const fresh = snapshot(19, userA, "fresh-access")
    const retry = deferred<BridgeResult<ApiResponse<{ items: string[] }>>>()
    const harness = clientHarness(old)
    harness.request
      .mockResolvedValueOnce(unauthorized())
      .mockReturnValueOnce(retry.promise)
    harness.refreshAccess.mockImplementationOnce(async () => {
      harness.setCurrent(fresh)
      return fresh
    })

    const result = harness.apiRequest<{ items: string[] }>("/api/v1/users", {
      method: "GET",
    })
    await vi.waitFor(() => expect(harness.request).toHaveBeenCalledTimes(2))
    harness.setCurrent(snapshot(21, userB, "user-b-access"))
    retry.resolve({
      ok: false,
      error: { code: "network_error", message: "old session transport failed" },
    })

    await expect(result).rejects.toMatchObject({ code: "stale_session_response" })
    expect(harness.onUnauthorized).not.toHaveBeenCalled()
  })

  it("refreshes after a mutation 401 but never automatically replays it", async () => {
    const old = snapshot(20, userA, "old-access")
    const fresh = snapshot(20, userA, "fresh-access")
    const harness = clientHarness(old)
    harness.request.mockResolvedValueOnce(unauthorized())
    harness.refreshAccess.mockImplementationOnce(async () => {
      harness.setCurrent(fresh)
      return fresh
    })

    const result = harness.apiRequest("/api/v1/users", {
      method: "POST",
      body: { username: "new.user" },
    })

    await expect(result).rejects.toMatchObject({
      code: "authentication_refreshed_resubmit",
      message: "登录状态已刷新，请重新提交本次操作。",
    })
    expect(harness.request).toHaveBeenCalledOnce()
    expect(harness.refreshAccess).toHaveBeenCalledOnce()
  })

  it("replays an explicitly safe AI POST once after refreshing authentication", async () => {
    const old = snapshot(22, userA, "old-access")
    const fresh = { ...snapshot(22, userA, "fresh-access"), accessExpiresAt: "2026-08-28T19:00:00.000Z" }
    const harness = clientHarness(old)
    harness.request
      .mockResolvedValueOnce(unauthorized())
      .mockResolvedValueOnce(apiOk({ candidates: [] }))
    harness.refreshAccess.mockImplementationOnce(async () => {
      harness.setCurrent(fresh)
      return fresh
    })

    const result = harness.apiRequest<{ candidates: unknown[] }>(
      "/api/v1/ai/project-ai-opportunities/discover",
      {
        method: "POST",
        retryAfterAuthRefresh: true,
        body: { project_id: "project-1", subject_id: "subject-1" },
      },
    )

    await expect(result).resolves.toEqual({ candidates: [] })
    expect(harness.request).toHaveBeenCalledTimes(2)
    expect(harness.request).toHaveBeenNthCalledWith(
      2,
      "/api/v1/ai/project-ai-opportunities/discover",
      expect.objectContaining({ accessToken: "fresh-access" }),
    )
  })
})
