import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"

import type {
  ApiErrorDto,
  AuthResult,
  LoginInput,
  UserDto,
} from "../../../shared/contracts"
import {
  ApiClientError,
  createApiClient,
  type ApiSessionSnapshot,
  type RendererApiRequestOptions,
} from "../api/client"

type AuthStatus = "loading" | "unauthenticated" | "authenticated"

interface AuthContextValue {
  status: AuthStatus
  user: UserDto | null
  login(input: LoginInput): Promise<void>
  changePassword(currentPassword: string, newPassword: string): Promise<void>
  updateDisplayName(displayName: string): void
  logout(): Promise<void>
  apiRequest<T>(path: string, options: RendererApiRequestOptions): Promise<T>
}

const AuthContext = createContext<AuthContextValue | null>(null)
const PROACTIVE_REFRESH_LEAD_MS = 2 * 60 * 1000

export class AuthUiError extends Error {
  readonly code: string
  readonly details?: unknown

  constructor(error: ApiErrorDto) {
    super(error.message)
    this.name = "AuthUiError"
    this.code = error.code
    this.details = error.details
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading")
  const [session, setSession] = useState<AuthResult | null>(null)
  const sessionRef = useRef<AuthResult | null>(null)
  const generationRef = useRef(0)
  const startupRef = useRef(false)
  const refreshPromiseRef = useRef<{
    expected: ApiSessionSnapshot
    promise: Promise<ApiSessionSnapshot | null>
  } | null>(null)

  const renderSession = useCallback((next: AuthResult | null) => {
    sessionRef.current = next
    setSession(next)
    setStatus(next ? "authenticated" : "unauthenticated")
  }, [])

  const currentSnapshot = useCallback((): ApiSessionSnapshot | null => {
    const current = sessionRef.current
    return current
      ? {
          generation: generationRef.current,
          userId: current.user.id,
          accessToken: current.accessToken,
          accessExpiresAt: current.accessExpiresAt,
        }
      : null
  }, [])

  const establishSession = useCallback(
    (next: AuthResult | null) => {
      generationRef.current += 1
      renderSession(next)
    },
    [renderSession],
  )

  const clearExpectedSession = useCallback(
    (expected: ApiSessionSnapshot): void => {
      if (!sameSnapshot(expected, currentSnapshot())) return
      generationRef.current += 1
      renderSession(null)
    },
    [currentSnapshot, renderSession],
  )

  const restoreSession = useCallback(async (): Promise<void> => {
    try {
      const result = await window.fde.auth.refresh()
      establishSession(result.ok ? result.data : null)
    } catch {
      establishSession(null)
    }
  }, [establishSession])

  const refreshAccess = useCallback(async (
    expected: ApiSessionSnapshot,
  ): Promise<ApiSessionSnapshot | null> => {
    if (!sameSnapshot(expected, currentSnapshot())) return null
    if (
      refreshPromiseRef.current &&
      sameSnapshot(expected, refreshPromiseRef.current.expected)
    ) {
      return refreshPromiseRef.current.promise
    }
    const refresh = (async () => {
      const result = await window.fde.auth.refresh()
      if (!sameSnapshot(expected, currentSnapshot())) return null
      if (!result.ok || !result.data) {
        clearExpectedSession(expected)
        return null
      }
      if (result.data.user.id !== expected.userId) {
        clearExpectedSession(expected)
        return null
      }
      renderSession(result.data)
      return currentSnapshot()
    })().catch(() => {
      clearExpectedSession(expected)
      return null
    })
    refreshPromiseRef.current = { expected, promise: refresh }
    try {
      return await refresh
    } finally {
      if (refreshPromiseRef.current?.promise === refresh) {
        refreshPromiseRef.current = null
      }
    }
  }, [clearExpectedSession, currentSnapshot, renderSession])

  useEffect(() => {
    if (startupRef.current) return
    startupRef.current = true
    void restoreSession()
  }, [restoreSession])

  useEffect(() => {
    if (!session) return
    const expiresAt = Date.parse(session.accessExpiresAt)
    if (!Number.isFinite(expiresAt)) return
    const expected = currentSnapshot()
    if (!expected) return
    const delay = Math.max(0, expiresAt - Date.now() - PROACTIVE_REFRESH_LEAD_MS)
    const timer = window.setTimeout(() => {
      void refreshAccess(expected)
    }, delay)
    return () => window.clearTimeout(timer)
  }, [currentSnapshot, refreshAccess, session])

  const login = useCallback(
    async (input: LoginInput): Promise<void> => {
      const result = await window.fde.auth.login(input)
      if (!result.ok) {
        throw new AuthUiError(result.error)
      }
      establishSession(result.data)
    },
    [establishSession],
  )

  const changePassword = useCallback(
    async (currentPassword: string, newPassword: string): Promise<void> => {
      const expected = currentSnapshot()
      if (!expected) {
        establishSession(null)
        throw new AuthUiError({
          code: "authentication_required",
          message: "Authentication is required.",
        })
      }
      const result = await window.fde.auth.changePassword(
        expected.accessToken,
        currentPassword,
        newPassword,
      )
      if (!result.ok) {
        throw new AuthUiError(result.error)
      }
      if (!sameSnapshot(expected, currentSnapshot())) {
        throw new AuthUiError({
          code: "stale_session_response",
          message: "The login session changed during password update.",
        })
      }
      renderSession(result.data)
    },
    [currentSnapshot, establishSession, renderSession],
  )

  const logout = useCallback(async (): Promise<void> => {
    try {
      const result = await window.fde.auth.logout()
      if (!result.ok) {
        // The remote error is intentionally not allowed to preserve local access.
        void result.error
      }
    } finally {
      establishSession(null)
    }
  }, [establishSession])

  const updateDisplayName = useCallback((displayName: string): void => {
    const current = sessionRef.current
    if (!current) return
    renderSession({ ...current, user: { ...current.user, displayName } })
  }, [renderSession])

  const apiRequest = useMemo(
    () =>
      createApiClient(window.fde.api, {
        getSessionSnapshot: currentSnapshot,
        refreshAccess,
        onUnauthorized: clearExpectedSession,
      }),
    [clearExpectedSession, currentSnapshot, refreshAccess],
  )

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user: session?.user ?? null,
      login,
      changePassword,
      updateDisplayName,
      logout,
      apiRequest,
    }),
    [apiRequest, changePassword, login, logout, session?.user, status, updateDisplayName],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

function sameSnapshot(
  expected: ApiSessionSnapshot,
  current: ApiSessionSnapshot | null,
): boolean {
  return Boolean(
    current &&
      current.generation === expected.generation &&
      current.userId === expected.userId &&
      current.accessToken === expected.accessToken &&
      current.accessExpiresAt === expected.accessExpiresAt,
  )
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new ApiClientError({
      code: "auth_context_missing",
      message: "AuthProvider is required.",
    })
  }
  return context
}
