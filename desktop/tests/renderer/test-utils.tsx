import type { ReactElement } from "react"
import { render } from "@testing-library/react"
import { vi } from "vitest"

import type {
  AuthResult,
  BridgeResult,
  FdeBridge,
  UserDto,
} from "../../src/shared/contracts"

export const adminUser: UserDto = {
  id: "1b7a50b8-5f95-4ad5-b1a0-b72d0a86c345",
  username: "admin",
  displayName: "管理员",
  role: "admin",
  mustChangePassword: false,
  isActive: true,
}

export const engineerUser: UserDto = {
  id: "2c8b61c9-60a6-4be6-a2b1-c83e1b97d456",
  username: "engineer.li",
  displayName: "李工程师",
  role: "fde_engineer",
  mustChangePassword: false,
  isActive: true,
}

export function authResult(
  user: UserDto,
  accessToken = "access-token",
): AuthResult {
  return {
    accessToken,
    accessExpiresAt: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
    refreshExpiresAt: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString(),
    user,
  }
}

export function ok<T>(data: T): BridgeResult<T> {
  return { ok: true, data }
}

export function bridge(
  overrides: Partial<FdeBridge["auth"]> & {
    apiRequest?: FdeBridge["api"]["request"]
  } = {},
): FdeBridge {
  return {
    auth: {
      login: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
      refresh: vi.fn().mockResolvedValue(ok(null)),
      changePassword: vi.fn().mockResolvedValue(ok(authResult(adminUser))),
      logout: vi.fn().mockResolvedValue(ok(null)),
      ...overrides,
    },
    api: {
      request:
        overrides.apiRequest ??
        (vi.fn().mockResolvedValue(
          ok({ status: 200, data: {}, error: null }),
        ) as FdeBridge["api"]["request"]),
    },
    app: { version: vi.fn().mockResolvedValue("0.0.0") },
  }
}

export function installBridge(value: FdeBridge): void {
  Object.defineProperty(window, "fde", {
    configurable: true,
    value,
  })
}

export function renderApp(element: ReactElement): ReturnType<typeof render> {
  return render(element)
}

export function deferred<T>(): {
  promise: Promise<T>
  resolve(value: T): void
} {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolver) => {
    resolve = resolver
  })
  return { promise, resolve }
}
