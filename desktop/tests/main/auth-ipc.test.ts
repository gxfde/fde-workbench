import { describe, expect, it, vi } from "vitest"
import type { IpcMain, IpcMainInvokeEvent } from "electron"

import {
  isAllowedRendererUrl,
  resolveApiBaseUrl,
} from "../../src/main/config"
import { IPC_CHANNELS } from "../../src/shared/contracts"
import {
  AuthIpcError,
  createAuthHandlers,
  registerAuthIpc,
  type AuthStore,
} from "../../src/main/auth-ipc"

const flaskUserDto = {
  id: "1b7a50b8-5f95-4ad5-b1a0-b72d0a86c345",
  username: "sample_user",
  display_name: "示例用户",
  role: "admin",
  must_change_password: false,
  is_active: true,
}

function tokenData(overrides: Record<string, unknown> = {}) {
  return {
    user: flaskUserDto,
    access_token: "access-token",
    refresh_token: "rotated-refresh-token",
    access_expires_at: "2026-08-19T12:15:00+00:00",
    refresh_expires_at: "2026-09-18T12:00:00+00:00",
    ...overrides,
  }
}

type RegisteredIpcHandler = (
  event: IpcMainInvokeEvent,
  ...args: unknown[]
) => unknown

function createRegisteredHarness(options: {
  fetch?: typeof fetch
  storedToken?: string | null
  trusted?: boolean
} = {}) {
  const base = createHarness(options)
  const registered = new Map<string, RegisteredIpcHandler>()
  const handle = vi.fn((channel: string, listener: RegisteredIpcHandler) => {
    registered.set(channel, listener)
  })
  registerAuthIpc({
    ipcMain: { handle } as unknown as Pick<IpcMain, "handle">,
    handlers: base.handlers,
    isTrustedSender: () => options.trusted ?? true,
  })

  return {
    ...base,
    invoke(channel: string, ...args: unknown[]) {
      const handler = registered.get(channel)
      if (!handler) {
        throw new Error(`Missing registered IPC handler: ${channel}`)
      }
      return Promise.resolve(handler({} as IpcMainInvokeEvent, ...args))
    },
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

function createHarness(options: {
  fetch?: typeof fetch
  storedToken?: string | null
  timeoutMs?: number
} = {}) {
  const store: AuthStore = {
    save: vi.fn().mockResolvedValue(undefined),
    load: vi.fn().mockResolvedValue(options.storedToken ?? null),
    clear: vi.fn().mockResolvedValue(undefined),
  }
  const fetchImplementation =
    options.fetch ??
    vi.fn().mockResolvedValue(jsonResponse({ data: tokenData(), error: null }))

  return {
    fetchImplementation,
    store,
    handlers: createAuthHandlers({
      apiBaseUrl: "https://api.example.test",
      fetch: fetchImplementation,
      store,
      timeoutMs: options.timeoutMs ?? 5_000,
    }),
  }
}

describe("desktop API URL", () => {
  it("rejects a non-HTTPS production API URL", () => {
    expect(() =>
      resolveApiBaseUrl("http://api.example.test", { isPackaged: true }),
    ).toThrow("HTTPS")
  })

  it("allows loopback ephemeral ports only for an unpackaged local API", () => {
    expect(
      resolveApiBaseUrl("http://127.0.0.1:8010", { isPackaged: false }),
    ).toBe("http://127.0.0.1:8010")
    expect(
      resolveApiBaseUrl("http://127.0.0.1:43127", { isPackaged: false }),
    ).toBe("http://127.0.0.1:43127")
    expect(() =>
      resolveApiBaseUrl("http://localhost:8010", { isPackaged: false }),
    ).toThrow("HTTPS")
    expect(() =>
      resolveApiBaseUrl("http://127.0.0.1:43127", { isPackaged: true }),
    ).toThrow("HTTPS")
  })

  it("allows the exact local API for an explicitly local packaged build", () => {
    expect(
      resolveApiBaseUrl("http://127.0.0.1:8010", {
        isPackaged: true,
        allowPackagedLocalApi: true,
      }),
    ).toBe("http://127.0.0.1:8010")
    expect(() =>
      resolveApiBaseUrl("http://localhost:8010", {
        isPackaged: true,
        allowPackagedLocalApi: true,
      }),
    ).toThrow("HTTPS")
  })
})

describe("renderer navigation boundary", () => {
  it("allows packaged files only within the renderer directory", () => {
    const environment = {
      isPackaged: true,
      rendererRoot: "/Applications/FDE.app/Contents/Resources/app.asar/out/renderer",
    }

    expect(
      isAllowedRendererUrl(
        "file:///Applications/FDE.app/Contents/Resources/app.asar/out/renderer/assets/app.js",
        environment,
      ),
    ).toBe(true)
    expect(
      isAllowedRendererUrl(
        "file:///Applications/FDE.app/Contents/Resources/app.asar/out/secrets.txt",
        environment,
      ),
    ).toBe(false)
    expect(isAllowedRendererUrl("https://example.test", environment)).toBe(false)
  })

  it("keeps an in-app fragment navigation inside the trusted packaged renderer", () => {
    const environment = {
      isPackaged: true,
      rendererRoot: "/Applications/FDE.app/Contents/Resources/app.asar/out/renderer",
    }

    expect(
      isAllowedRendererUrl(
        "file:///Applications/FDE.app/Contents/Resources/app.asar/out/renderer/index.html#users",
        environment,
      ),
    ).toBe(true)
    expect(
      isAllowedRendererUrl(
        "file:///Applications/FDE.app/Contents/Resources/app.asar/out/renderer/index.html?outside=true",
        environment,
      ),
    ).toBe(false)
  })

  it("allows only the configured development renderer origin", () => {
    const environment = {
      isPackaged: false,
      rendererRoot: "/unused",
      developmentUrl: "http://127.0.0.1:5173",
    }

    expect(
      isAllowedRendererUrl("http://127.0.0.1:5173/assets/app.js", environment),
    ).toBe(true)
    expect(
      isAllowedRendererUrl("http://127.0.0.1:5173.evil.test/", environment),
    ).toBe(false)
    expect(isAllowedRendererUrl("file:///etc/passwd", environment)).toBe(false)
  })
})

describe("authentication handlers", () => {
  it("stores the rotated refresh token before returning a changed-password session", async () => {
    const events: string[] = []
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          data: {
            access_token: "changed-access-token",
            refresh_token: "changed-refresh-token",
            access_expires_at: "2026-08-19T13:15:00+00:00",
            refresh_expires_at: "2026-09-18T13:00:00+00:00",
            user: { ...flaskUserDto, must_change_password: false },
          },
          error: null,
        }),
      )
    const { handlers, store } = createHarness({ fetch: fetchMock })
    vi.mocked(store.save).mockImplementation(async () => {
      events.push("saved")
    })

    const result = await (
      handlers as unknown as {
        changePassword(
          accessToken: string,
          currentPassword: string,
          newPassword: string,
        ): Promise<ReturnType<typeof tokenData>>
      }
    )
      .changePassword("forced-change-access", "TempPass!2345", "ChangedPass!9012")
      .then((value) => {
        events.push("returned")
        return value
      })

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "https://api.example.test/api/v1/auth/change-password",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          authorization: "Bearer forced-change-access",
        }),
        body: JSON.stringify({
          current_password: "TempPass!2345",
          new_password: "ChangedPass!9012",
        }),
      }),
    )
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(store.save).toHaveBeenCalledWith("changed-refresh-token")
    expect(events).toEqual(["saved", "returned"])
    expect(result).toMatchObject({
      accessToken: "changed-access-token",
      user: { mustChangePassword: false },
    })
    expect(JSON.stringify(result)).not.toContain("changed-refresh-token")
  })

  it("stores refresh on login but returns only access data to renderer", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ data: tokenData(), error: null }))
    const { handlers, store } = createHarness({ fetch: fetchMock })

    const result = await handlers.login({
      username: "sample_user",
      password: "Password!234",
      deviceLabel: "Example Mac",
    })

    expect(store.save).toHaveBeenCalledWith("rotated-refresh-token")
    expect(result).toEqual({
      accessToken: "access-token",
      accessExpiresAt: "2026-08-19T12:15:00+00:00",
      refreshExpiresAt: "2026-09-18T12:00:00+00:00",
      user: {
        id: "1b7a50b8-5f95-4ad5-b1a0-b72d0a86c345",
        username: "sample_user",
        displayName: "示例用户",
        role: "admin",
        mustChangePassword: false,
        isActive: true,
      },
    })
    expect(result).not.toHaveProperty("refreshToken")
    expect(JSON.stringify(result)).not.toContain("rotated-refresh-token")
  })

  it("rejects a numeric user ID instead of accepting a non-Flask DTO", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({
        data: tokenData({ user: { ...flaskUserDto, id: 7 } }),
        error: null,
      }),
    )
    const { handlers, store } = createHarness({ fetch: fetchMock })

    await expect(
      handlers.login({
        username: "sample_user",
        password: "Password!234",
        deviceLabel: "Example Mac",
      }),
    ).rejects.toMatchObject({ code: "invalid_api_response" })
    expect(store.save).not.toHaveBeenCalled()
  })

  it("validates login input before making a request", async () => {
    const fetchMock = vi.fn<typeof fetch>()
    const { handlers } = createHarness({ fetch: fetchMock })

    await expect(
      handlers.login({ username: "", password: "Password!234", deviceLabel: "Mac" }),
    ).rejects.toMatchObject({ code: "invalid_request" })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("accepts a 120-character username and rejects 121 before fetch", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({ data: tokenData(), error: null }),
    )
    const { handlers } = createHarness({ fetch: fetchMock })

    await expect(handlers.login({
      username: "u".repeat(120),
      password: "Password!234",
      deviceLabel: "Mac",
    })).resolves.toMatchObject({ accessToken: "access-token" })
    await expect(handlers.login({
      username: "u".repeat(121),
      password: "Password!234",
      deviceLabel: "Mac",
    })).rejects.toMatchObject({ code: "invalid_request" })
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it("maps backend error envelopes without exposing credentials", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(
        {
          data: null,
          error: {
            code: "invalid_credentials",
            message: "Invalid username or password.",
            details: { password: "Password!234" },
          },
        },
        401,
      ),
    )
    const { handlers } = createHarness({ fetch: fetchMock })

    const rejection = handlers.login({
      username: "sample_user",
      password: "Password!234",
      deviceLabel: "Example Mac",
    })

    await expect(rejection).rejects.toMatchObject({
      code: "invalid_credentials",
      message: "Invalid username or password.",
      details: { password: "[REDACTED]" },
    })
    await expect(rejection).rejects.not.toThrow("Password!234")
  })

  it("maps invalid JSON to a safe API error", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response("<html>proxy failure</html>", { status: 502 }))
    const { handlers } = createHarness({ fetch: fetchMock })

    await expect(
      handlers.login({
        username: "sample_user",
        password: "Password!234",
        deviceLabel: "Example Mac",
      }),
    ).rejects.toMatchObject({
      code: "invalid_api_response",
      message: "The authentication service returned an invalid response.",
    })
  })

  it("aborts a request at the configured timeout", async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn<typeof fetch>().mockImplementation((_url, init) => {
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(Object.assign(new Error("aborted"), { name: "AbortError" }))
        })
      })
    })
    const { handlers } = createHarness({ fetch: fetchMock, timeoutMs: 25 })

    const request = handlers.login({
      username: "sample_user",
      password: "Password!234",
      deviceLabel: "Example Mac",
    })
    const rejection = expect(request).rejects.toMatchObject({
      code: "request_timeout",
      message: "The authentication service timed out.",
    })
    await vi.advanceTimersByTimeAsync(25)

    await rejection
    vi.useRealTimers()
  })

  it("maps network failures without leaking low-level messages", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockRejectedValue(new Error("connect ECONNREFUSED token=secret"))
    const { handlers } = createHarness({ fetch: fetchMock })

    const request = handlers.login({
      username: "sample_user",
      password: "Password!234",
      deviceLabel: "Example Mac",
    })

    await expect(request).rejects.toEqual(
      new AuthIpcError("network_error", "Unable to reach the authentication service."),
    )
    await expect(request).rejects.not.toThrow("secret")
  })

  it("accepts Flask UUID user IDs before saving a rotated refresh token", async () => {
    const events: string[] = []
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({
        data: tokenData({ access_token: "new-access-token" }),
        error: null,
      }),
    )
    const { handlers, store } = createHarness({
      fetch: fetchMock,
      storedToken: "old-refresh-token",
    })
    vi.mocked(store.save).mockImplementation(async () => {
      events.push("saved")
    })

    const result = await handlers.refresh().then((value) => {
      events.push("returned")
      return value
    })

    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/api/v1/auth/refresh",
      expect.objectContaining({
        body: JSON.stringify({ refresh_token: "old-refresh-token" }),
      }),
    )
    expect(store.save).toHaveBeenCalledWith("rotated-refresh-token")
    expect(result?.accessToken).toBe("new-access-token")
    expect(result?.user.id).toBe("1b7a50b8-5f95-4ad5-b1a0-b72d0a86c345")
    expect(events).toEqual(["saved", "returned"])
  })

  it("returns null without a request when no refresh session exists", async () => {
    const fetchMock = vi.fn<typeof fetch>()
    const { handlers } = createHarness({ fetch: fetchMock, storedToken: null })

    await expect(handlers.refresh()).resolves.toBeNull()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("clears local storage even when remote logout fails", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockRejectedValue(new Error("connect ECONNREFUSED"))
    const { handlers, store } = createHarness({
      fetch: fetchMock,
      storedToken: "stored-refresh-token",
    })

    await expect(handlers.logout()).rejects.toMatchObject({ code: "network_error" })
    expect(store.clear).toHaveBeenCalledOnce()
  })
})

describe("registered authentication IPC envelope", () => {
  it("returns changed-password access data without exposing the rotated refresh token", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          data: {
            access_token: "changed-access-token",
            refresh_token: "changed-refresh-token",
            access_expires_at: "2026-08-19T13:15:00+00:00",
            refresh_expires_at: "2026-09-18T13:00:00+00:00",
            user: { ...flaskUserDto, must_change_password: false },
          },
          error: null,
        }),
      )
    const harness = createRegisteredHarness({ fetch: fetchMock })

    const result = await harness.invoke(
      IPC_CHANNELS.authChangePassword,
      "forced-change-access",
      "TempPass!2345",
      "ChangedPass!9012",
    )

    expect(result).toMatchObject({
      ok: true,
      data: {
        accessToken: "changed-access-token",
        user: { mustChangePassword: false },
      },
    })
    expect(harness.store.save).toHaveBeenCalledWith("changed-refresh-token")
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(JSON.stringify(result)).not.toContain("changed-refresh-token")
  })

  it("returns a serializable success result from the registered login handler", async () => {
    const harness = createRegisteredHarness()

    const result = await harness.invoke(IPC_CHANNELS.authLogin, {
      username: "sample_user",
      password: "Password!234",
      deviceLabel: "Example Mac",
    })

    expect(result).toEqual({
      ok: true,
      data: {
        accessToken: "access-token",
        accessExpiresAt: "2026-08-19T12:15:00+00:00",
        refreshExpiresAt: "2026-09-18T12:00:00+00:00",
        user: {
          id: "1b7a50b8-5f95-4ad5-b1a0-b72d0a86c345",
          username: "sample_user",
          displayName: "示例用户",
          role: "admin",
          mustChangePassword: false,
          isActive: true,
        },
      },
    })
    expect(JSON.stringify(result)).not.toContain("rotated-refresh-token")
  })

  it("returns a safe serializable error result instead of rejecting IPC", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(
        {
          data: null,
          error: {
            code: "invalid_credentials",
            message: "Password Password!234 and token server-secret are invalid.",
            details: {
              password: "Password!234",
              refresh_token: "server-secret",
            },
          },
        },
        401,
      ),
    )
    const harness = createRegisteredHarness({ fetch: fetchMock })

    const result = await harness.invoke(IPC_CHANNELS.authLogin, {
      username: "sample_user",
      password: "Password!234",
      deviceLabel: "Example Mac",
    })

    expect(result).toEqual({
      ok: false,
      error: {
        code: "invalid_credentials",
        message: "Password [REDACTED] and token [REDACTED] are invalid.",
        details: {
          password: "[REDACTED]",
          refresh_token: "[REDACTED]",
        },
      },
    })
    expect(JSON.stringify(result)).not.toContain("Password!234")
    expect(JSON.stringify(result)).not.toContain("server-secret")
  })

  it("returns an unauthorized envelope from an untrusted IPC sender", async () => {
    const harness = createRegisteredHarness({ trusted: false })

    await expect(harness.invoke(IPC_CHANNELS.authRefresh)).resolves.toEqual({
      ok: false,
      error: {
        code: "unauthorized_ipc",
        message: "The IPC sender is not authorized.",
      },
    })
  })
})
