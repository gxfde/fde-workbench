import type { IpcMain, IpcMainInvokeEvent } from "electron"

import {
  IPC_CHANNELS,
  isUserRole,
  type ApiErrorDto,
  type AuthResult,
  type BridgeResult,
  type LoginInput,
  type UserDto,
  PASSWORD_MAX_LENGTH,
  USERNAME_MAX_LENGTH,
} from "../shared/contracts"
import {
  SecureStorageUnavailableError,
  SessionStoreError,
  type AuthStore,
} from "./auth-store"

export type { AuthStore } from "./auth-store"

interface AuthHandlersOptions {
  apiBaseUrl: string
  fetch: typeof fetch
  store: AuthStore
  timeoutMs: number
}

export interface AuthHandlers {
  login(input: unknown): Promise<AuthResult>
  refresh(): Promise<AuthResult | null>
  changePassword(
    accessToken: unknown,
    currentPassword: unknown,
    newPassword: unknown,
  ): Promise<AuthResult>
  logout(): Promise<void>
}

interface RegisterAuthIpcOptions {
  ipcMain: Pick<IpcMain, "handle">
  handlers: AuthHandlers
  isTrustedSender(event: IpcMainInvokeEvent): boolean
}

interface ApiTokenData {
  accessToken: string
  refreshToken: string
  accessExpiresAt: string
  refreshExpiresAt: string
  user: UserDto
}

const REDACTED = "[REDACTED]"
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export class AuthIpcError extends Error implements ApiErrorDto {
  readonly code: string
  readonly details?: unknown

  constructor(code: string, message: string, details?: unknown) {
    super(message)
    this.name = "AuthIpcError"
    this.code = code
    this.details = details
  }
}

export function createAuthHandlers(options: AuthHandlersOptions): AuthHandlers {
  let sessionMutation = Promise.resolve()

  function exclusively<T>(operation: () => Promise<T>): Promise<T> {
    const result = sessionMutation.then(operation, operation)
    sessionMutation = result.then(
      () => undefined,
      () => undefined,
    )
    return result
  }

  async function login(input: unknown): Promise<AuthResult> {
    return exclusively(async () => {
      const loginInput = validateLoginInput(input)
      const data = await postJson(
        options,
        "/api/v1/auth/login",
        {
          username: loginInput.username,
          password: loginInput.password,
          device_label: loginInput.deviceLabel,
        },
        [loginInput.password],
      )
      const tokenData = parseTokenData(data)
      await saveSession(options.store, tokenData.refreshToken)
      return stripRefreshToken(tokenData)
    })
  }

  async function refresh(): Promise<AuthResult | null> {
    return exclusively(async () => {
      const currentRefreshToken = await loadSession(options.store)
      if (!currentRefreshToken) {
        return null
      }
      const data = await postJson(
        options,
        "/api/v1/auth/refresh",
        { refresh_token: currentRefreshToken },
        [currentRefreshToken],
      )
      const tokenData = parseTokenData(data)
      await saveSession(options.store, tokenData.refreshToken)
      return stripRefreshToken(tokenData)
    })
  }

  async function changePassword(
    accessToken: unknown,
    currentPassword: unknown,
    newPassword: unknown,
  ): Promise<AuthResult> {
    return exclusively(async () => {
      const input = validateChangePasswordInput(
        accessToken,
        currentPassword,
        newPassword,
      )
      const data = await postJson(
        options,
        "/api/v1/auth/change-password",
        {
          current_password: input.currentPassword,
          new_password: input.newPassword,
        },
        [input.accessToken, input.currentPassword, input.newPassword],
        input.accessToken,
      )
      const tokenData = parseTokenData(data)
      await saveSession(options.store, tokenData.refreshToken)
      return stripRefreshToken(tokenData)
    })
  }

  async function logout(): Promise<void> {
    return exclusively(async () => {
      let requestFailure: unknown
      let loadFailure: unknown
      let refreshToken: string | null = null
      try {
        refreshToken = await options.store.load()
      } catch (error) {
        loadFailure = mapStorageError(error)
      }

      if (refreshToken) {
        try {
          await postJson(
            options,
            "/api/v1/auth/logout",
            { refresh_token: refreshToken },
            [refreshToken],
          )
        } catch (error) {
          requestFailure = error
        }
      }

      try {
        await options.store.clear()
      } catch (error) {
        throw mapStorageError(error)
      }
      if (loadFailure) {
        throw loadFailure
      }
      if (requestFailure) {
        throw requestFailure
      }
    })
  }

  return { login, refresh, changePassword, logout }
}

export function registerAuthIpc(options: RegisterAuthIpcOptions): void {
  options.ipcMain.handle(IPC_CHANNELS.authLogin, (event, input: unknown) =>
    toBridgeResult(async () => {
      requireTrustedSender(event, options.isTrustedSender)
      return options.handlers.login(input)
    }),
  )
  options.ipcMain.handle(IPC_CHANNELS.authRefresh, (event) =>
    toBridgeResult(async () => {
      requireTrustedSender(event, options.isTrustedSender)
      return options.handlers.refresh()
    }),
  )
  options.ipcMain.handle(
    IPC_CHANNELS.authChangePassword,
    (event, accessToken: unknown, currentPassword: unknown, newPassword: unknown) =>
      toBridgeResult(async () => {
        requireTrustedSender(event, options.isTrustedSender)
        return options.handlers.changePassword(
          accessToken,
          currentPassword,
          newPassword,
        )
      }),
  )
  options.ipcMain.handle(IPC_CHANNELS.authLogout, (event) =>
    toBridgeResult(async () => {
      requireTrustedSender(event, options.isTrustedSender)
      await options.handlers.logout()
      return null
    }),
  )
}

async function toBridgeResult<T>(
  operation: () => Promise<T>,
): Promise<BridgeResult<T>> {
  try {
    return { ok: true, data: await operation() }
  } catch (error) {
    return { ok: false, error: toApiErrorDto(error) }
  }
}

function toApiErrorDto(error: unknown): ApiErrorDto {
  if (error instanceof AuthIpcError) {
    const details = sanitizeDetails(error.details, [])
    return {
      code: error.code,
      message: error.message,
      ...(details === undefined ? {} : { details }),
    }
  }
  return {
    code: "internal_error",
    message: "The authentication request could not be completed.",
  }
}

function requireTrustedSender(
  event: IpcMainInvokeEvent,
  isTrustedSender: (event: IpcMainInvokeEvent) => boolean,
): void {
  if (!isTrustedSender(event)) {
    throw new AuthIpcError("unauthorized_ipc", "The IPC sender is not authorized.")
  }
}

async function postJson(
  options: AuthHandlersOptions,
  path: string,
  body: Record<string, string>,
  secrets: string[],
  accessToken?: string,
): Promise<unknown> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs)
  try {
    const response = await options.fetch(`${options.apiBaseUrl}${path}`, {
      method: "POST",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
        ...(accessToken ? { authorization: `Bearer ${accessToken}` } : {}),
      },
      body: JSON.stringify(body),
      signal: controller.signal,
      redirect: "error",
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer",
    })
    return await parseEnvelope(response, secrets)
  } catch (error) {
    if (error instanceof AuthIpcError) {
      throw error
    }
    if (controller.signal.aborted || isAbortError(error)) {
      throw new AuthIpcError(
        "request_timeout",
        "The authentication service timed out.",
      )
    }
    throw new AuthIpcError(
      "network_error",
      "Unable to reach the authentication service.",
    )
  } finally {
    clearTimeout(timeout)
  }
}

async function parseEnvelope(response: Response, secrets: string[]): Promise<unknown> {
  let envelope: unknown
  try {
    envelope = JSON.parse(await response.text())
  } catch {
    throw invalidApiResponse()
  }
  if (!isRecord(envelope) || !("data" in envelope) || !("error" in envelope)) {
    throw invalidApiResponse()
  }
  if (envelope.error !== null) {
    if (
      !isRecord(envelope.error) ||
      typeof envelope.error.code !== "string" ||
      typeof envelope.error.message !== "string"
    ) {
      throw invalidApiResponse()
    }
    const allSecrets = [...secrets, ...collectSensitiveValues(envelope.error.details)]
    throw new AuthIpcError(
      redactString(envelope.error.code, allSecrets),
      redactString(envelope.error.message, allSecrets),
      sanitizeDetails(envelope.error.details, allSecrets),
    )
  }
  if (!response.ok || envelope.data === null) {
    throw invalidApiResponse()
  }
  return envelope.data
}

function parseTokenData(value: unknown): ApiTokenData {
  if (!isRecord(value) || !isRecord(value.user)) {
    throw invalidApiResponse()
  }
  const tokenPair = parseTokenPair(value)
  const user = parseUser(value.user)
  return { ...tokenPair, user }
}

function parseTokenPair(value: unknown): Omit<ApiTokenData, "user"> {
  if (!isRecord(value)) {
    throw invalidApiResponse()
  }
  if (
    typeof value.access_token !== "string" ||
    !value.access_token ||
    typeof value.refresh_token !== "string" ||
    !value.refresh_token ||
    !isIsoTimestamp(value.access_expires_at) ||
    !isIsoTimestamp(value.refresh_expires_at)
  ) {
    throw invalidApiResponse()
  }
  return {
    accessToken: value.access_token,
    refreshToken: value.refresh_token,
    accessExpiresAt: value.access_expires_at,
    refreshExpiresAt: value.refresh_expires_at,
  }
}

function parseUser(value: unknown): UserDto {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    !UUID_PATTERN.test(value.id) ||
    typeof value.username !== "string" ||
    typeof value.display_name !== "string" ||
    !isUserRole(value.role) ||
    typeof value.must_change_password !== "boolean" ||
    typeof value.is_active !== "boolean"
  ) {
    throw invalidApiResponse()
  }
  return {
    id: value.id,
    username: value.username,
    displayName: value.display_name,
    role: value.role,
    mustChangePassword: value.must_change_password,
    isActive: value.is_active,
  }
}

function stripRefreshToken(value: ApiTokenData): AuthResult {
  return {
    accessToken: value.accessToken,
    accessExpiresAt: value.accessExpiresAt,
    refreshExpiresAt: value.refreshExpiresAt,
    user: value.user,
  }
}

function validateLoginInput(value: unknown): LoginInput {
  if (!isRecord(value)) {
    throw invalidRequest()
  }
  const { username, password, deviceLabel } = value
  if (
    typeof username !== "string" ||
    username.trim().length === 0 ||
    username.length > USERNAME_MAX_LENGTH ||
    typeof password !== "string" ||
    password.length === 0 ||
    password.length > PASSWORD_MAX_LENGTH ||
    typeof deviceLabel !== "string" ||
    deviceLabel.trim().length === 0 ||
    deviceLabel.length > 120
  ) {
    throw invalidRequest()
  }
  return { username, password, deviceLabel }
}

function validateChangePasswordInput(
  accessToken: unknown,
  currentPassword: unknown,
  newPassword: unknown,
): { accessToken: string; currentPassword: string; newPassword: string } {
  if (
    typeof accessToken !== "string" ||
    accessToken.length === 0 ||
    accessToken.length > 16_384 ||
    typeof currentPassword !== "string" ||
    currentPassword.length === 0 ||
    currentPassword.length > PASSWORD_MAX_LENGTH ||
    typeof newPassword !== "string" ||
    newPassword.length === 0 ||
    newPassword.length > PASSWORD_MAX_LENGTH
  ) {
    throw invalidRequest()
  }
  return { accessToken, currentPassword, newPassword }
}

async function loadSession(store: AuthStore): Promise<string | null> {
  try {
    return await store.load()
  } catch (error) {
    throw mapStorageError(error)
  }
}

async function saveSession(store: AuthStore, refreshToken: string): Promise<void> {
  try {
    await store.save(refreshToken)
  } catch (error) {
    throw mapStorageError(error)
  }
}

function mapStorageError(error: unknown): AuthIpcError {
  if (error instanceof SecureStorageUnavailableError) {
    return new AuthIpcError(
      "secure_storage_unavailable",
      "Secure session storage is unavailable on this device.",
    )
  }
  if (error instanceof SessionStoreError) {
    return new AuthIpcError(
      "session_storage_error",
      "The local authentication session could not be updated.",
    )
  }
  return new AuthIpcError(
    "session_storage_error",
    "The local authentication session could not be updated.",
  )
}

function invalidRequest(): AuthIpcError {
  return new AuthIpcError(
    "invalid_request",
    "The authentication request is invalid.",
  )
}

function invalidApiResponse(): AuthIpcError {
  return new AuthIpcError(
    "invalid_api_response",
    "The authentication service returned an invalid response.",
  )
}

function sanitizeDetails(
  value: unknown,
  secrets: string[],
  depth = 0,
): unknown {
  if (depth > 5) {
    return "[TRUNCATED]"
  }
  if (typeof value === "string") {
    return redactString(value, secrets)
  }
  if (Array.isArray(value)) {
    return value.slice(0, 50).map((item) => sanitizeDetails(item, secrets, depth + 1))
  }
  if (isRecord(value)) {
    return Object.fromEntries(
      Object.entries(value)
        .slice(0, 50)
        .map(([key, item]) => [
          key,
          isSensitiveKey(key)
            ? REDACTED
            : sanitizeDetails(item, secrets, depth + 1),
        ]),
    )
  }
  if (value === null || typeof value === "number" || typeof value === "boolean") {
    return value
  }
  return undefined
}

function redactString(value: string, secrets: string[]): string {
  return secrets.reduce(
    (result, secret) => (secret ? result.split(secret).join(REDACTED) : result),
    value,
  )
}

function isSensitiveKey(key: string): boolean {
  return /password|token|secret|authorization|credential/i.test(key)
}

function collectSensitiveValues(value: unknown, depth = 0): string[] {
  if (depth > 5 || !isRecord(value)) {
    return []
  }
  return Object.entries(value).flatMap(([key, item]) => {
    if (isSensitiveKey(key) && typeof item === "string" && item) {
      return [item]
    }
    if (Array.isArray(item)) {
      return item.flatMap((entry) => collectSensitiveValues(entry, depth + 1))
    }
    return collectSensitiveValues(item, depth + 1)
  })
}

function isIsoTimestamp(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && !Number.isNaN(Date.parse(value))
}

function isAbortError(error: unknown): boolean {
  return isRecord(error) && error.name === "AbortError"
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}
