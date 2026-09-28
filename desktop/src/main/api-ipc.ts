import type { IpcMain, IpcMainInvokeEvent } from "electron"

import {
  IPC_CHANNELS,
  type ApiErrorDto,
  type ApiMethod,
  type ApiResponse,
  type BridgeResult,
} from "../shared/contracts"

interface ApiRequestHandlerOptions {
  apiBaseUrl: string
  fetch: typeof fetch
  timeoutMs: number
}

interface ValidatedApiRequest {
  url: string
  method: ApiMethod
  accessToken: string
  body?: unknown
}

interface MultipartFileBody {
  kind: "multipart_file"
  fields: Record<string, string>
  file: {
    field_name: string
    name: string
    type: string
    bytes: Uint8Array
  }
}

const MAX_MULTIPART_FILE_BYTES = 100 * 1024 * 1024
const MAX_MULTIPART_FIELDS = 20

export type ApiRequestHandler = (
  input: unknown,
) => Promise<ApiResponse<unknown>>

interface RegisterApiIpcOptions {
  ipcMain: Pick<IpcMain, "handle">
  request: ApiRequestHandler
  isTrustedSender(event: IpcMainInvokeEvent): boolean
}

const ALLOWED_METHODS = new Set<ApiMethod>(["GET", "POST", "PUT", "PATCH", "DELETE"])
const ALLOWED_KEYS = new Set(["path", "method", "accessToken", "body"])
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/
const PATH_TRAVERSAL = /(^|\/)\.{1,2}(\/|$)/
const REDACTED = "[REDACTED]"

class ApiIpcError extends Error implements ApiErrorDto {
  readonly code: string
  readonly details?: unknown

  constructor(code: string, message: string, details?: unknown) {
    super(message)
    this.name = "ApiIpcError"
    this.code = code
    this.details = details
  }
}

export function createApiRequestHandler(
  options: ApiRequestHandlerOptions,
): ApiRequestHandler {
  return async (input: unknown): Promise<ApiResponse<unknown>> => {
    const request = validateRequest(input, options.apiBaseUrl)
    const controller = new AbortController()
    const pluginDecision = request.method === "POST"
      && /^\/api\/v1\/extensions\/plugin-requests\/[^/]+\/decision$/.test(new URL(request.url).pathname)
    const timeout = setTimeout(() => controller.abort(), pluginDecision ? Math.max(options.timeoutMs, 330_000) : options.timeoutMs)
    const secrets = [request.accessToken, ...collectSensitiveValues(request.body)]
    try {
      const multipartBody = isMultipartFileBody(request.body) ? buildMultipartBody(request.body) : undefined
      const serializedBody = request.body === undefined || multipartBody
        ? undefined
        : serializeBody(request.body)
      const response = await options.fetch(request.url, {
        method: request.method,
        headers: {
          accept: "application/json",
          authorization: `Bearer ${request.accessToken}`,
          ...(serializedBody === undefined || multipartBody
            ? {}
            : { "content-type": "application/json" }),
        },
        ...(multipartBody ? { body: multipartBody } : serializedBody === undefined ? {} : { body: serializedBody }),
        signal: controller.signal,
        redirect: "error",
        cache: "no-store",
        credentials: "omit",
        referrerPolicy: "no-referrer",
      })
      return parseApiResponse(response, secrets)
    } catch (error) {
      if (error instanceof ApiIpcError) {
        throw error
      }
      if (controller.signal.aborted || isAbortError(error)) {
        throw new ApiIpcError("request_timeout", "AI 或服务端响应超时，请稍后重试。")
      }
      throw new ApiIpcError("network_error", "无法连接本地服务，请确认服务已启动。")
    } finally {
      clearTimeout(timeout)
    }
  }
}

export function registerApiIpc(options: RegisterApiIpcOptions): void {
  options.ipcMain.handle(IPC_CHANNELS.apiRequest, (event, input: unknown) =>
    toBridgeResult(async () => {
      if (!options.isTrustedSender(event)) {
        throw new ApiIpcError(
          "unauthorized_ipc",
          "The IPC sender is not authorized.",
        )
      }
      return options.request(input)
    }),
  )
}

function validateRequest(
  value: unknown,
  apiBaseUrl: string,
): ValidatedApiRequest {
  if (
    !isRecord(value) ||
    Object.keys(value).some((key) => !ALLOWED_KEYS.has(key)) ||
    typeof value.path !== "string" ||
    typeof value.method !== "string" ||
    !ALLOWED_METHODS.has(value.method as ApiMethod) ||
    typeof value.accessToken !== "string" ||
    value.accessToken.length === 0 ||
    value.accessToken.length > 16_384
  ) {
    throw invalidRequest()
  }
  const path = value.path
  const queryIndex = path.indexOf("?")
  const rawPathname = queryIndex === -1 ? path : path.slice(0, queryIndex)
  const rawQuery = queryIndex === -1 ? "" : path.slice(queryIndex + 1)
  let decodedPathname: string
  let decodedQuery: string
  try {
    decodedPathname = decodeURIComponent(rawPathname)
    decodedQuery = decodeURIComponent(rawQuery)
  } catch {
    throw invalidRequest()
  }
  if (
    !rawPathname.startsWith("/api/v1/") ||
    !decodedPathname.startsWith("/api/v1/") ||
    decodedPathname.includes("//") ||
    path.includes("#") ||
    path.includes("\\") ||
    decodedPathname.includes("\\") ||
    decodedQuery.includes("\\") ||
    CONTROL_CHARACTERS.test(path) ||
    CONTROL_CHARACTERS.test(decodedPathname) ||
    PATH_TRAVERSAL.test(rawPathname) ||
    PATH_TRAVERSAL.test(decodedPathname) ||
    hasEncodedStructuralEscape(rawPathname, true) ||
    hasEncodedStructuralEscape(rawQuery, false) ||
    CONTROL_CHARACTERS.test(decodedQuery)
  ) {
    throw invalidRequest()
  }
  const isPasswordVerification =
    decodedPathname === "/api/v1/auth/verify-password" &&
    value.method === "POST"
  if (
    /^\/api\/v1\/auth(?:\/|$)/i.test(decodedPathname) &&
    !isPasswordVerification
  ) {
    throw invalidRequest()
  }
  if (value.method === "GET" && value.body !== undefined) {
    throw invalidRequest()
  }
  if (value.body !== undefined) {
    if (isRecord(value.body) && value.body.kind === "multipart_file") validateMultipartFileBody(value.body)
    else serializeBody(value.body)
  }
  let finalUrl: URL
  let apiOrigin: string
  try {
    finalUrl = new URL(path, `${apiBaseUrl}/`)
    apiOrigin = new URL(apiBaseUrl).origin
  } catch {
    throw invalidRequest()
  }
  if (
    finalUrl.origin !== apiOrigin ||
    !finalUrl.pathname.startsWith("/api/v1/") ||
    PATH_TRAVERSAL.test(finalUrl.pathname)
  ) {
    throw invalidRequest()
  }
  return {
    url: finalUrl.toString(),
    method: value.method as ApiMethod,
    accessToken: value.accessToken,
    ...(value.body === undefined ? {} : { body: value.body }),
  }
}

function validateMultipartFileBody(value: Record<string, unknown>): asserts value is MultipartFileBody & Record<string, unknown> {
  if (!hasExactKeys(value, ["kind", "fields", "file"]) || value.kind !== "multipart_file" || !isRecord(value.fields) || !isRecord(value.file)) throw invalidRequest()
  if (Object.keys(value.fields).length > MAX_MULTIPART_FIELDS) throw invalidRequest()
  for (const [key, item] of Object.entries(value.fields)) {
    if (!/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(key) || typeof item !== "string" || item.length > 10_000 || CONTROL_CHARACTERS.test(item)) throw invalidRequest()
  }
  if (!hasExactKeys(value.file, ["field_name", "name", "type", "bytes"])) throw invalidRequest()
  const { field_name: fieldName, name, type, bytes } = value.file
  if (
    typeof fieldName !== "string" || !/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(fieldName)
    || typeof name !== "string" || name.length < 1 || name.length > 255 || name === "." || name === ".." || /[/\\]/.test(name) || CONTROL_CHARACTERS.test(name)
    || typeof type !== "string" || type.length > 255 || CONTROL_CHARACTERS.test(type)
    || !(bytes instanceof Uint8Array) || bytes.byteLength > MAX_MULTIPART_FILE_BYTES
  ) throw invalidRequest()
}

function isMultipartFileBody(value: unknown): value is MultipartFileBody {
  if (!isRecord(value) || value.kind !== "multipart_file") return false
  validateMultipartFileBody(value)
  return true
}

function buildMultipartBody(value: MultipartFileBody): FormData {
  const body = new FormData()
  for (const [key, item] of Object.entries(value.fields)) body.append(key, item)
  const bytes = value.file.bytes.slice()
  body.append(value.file.field_name, new Blob([bytes], { type: value.file.type }), value.file.name)
  return body
}

function hasExactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  const allowed = new Set(keys)
  return keys.every((key) => Object.hasOwn(value, key)) && Object.keys(value).every((key) => allowed.has(key))
}

function hasEncodedStructuralEscape(
  value: string,
  rejectEncodedDots: boolean,
): boolean {
  if (/%(?:25|2f|3f|23|5c)/i.test(value)) {
    return true
  }
  return rejectEncodedDots && /%2e/i.test(value)
}

function serializeBody(body: unknown): string {
  try {
    const serialized = JSON.stringify(body)
    if (serialized === undefined) {
      throw invalidRequest()
    }
    JSON.parse(serialized)
    return serialized
  } catch (error) {
    if (error instanceof ApiIpcError) {
      throw error
    }
    throw invalidRequest()
  }
}

async function parseApiResponse(
  response: Response,
  secrets: string[],
): Promise<ApiResponse<unknown>> {
  if (response.ok && response.status === 204) {
    return { status: response.status, data: null, error: null }
  }
  let value: unknown
  try {
    value = JSON.parse(await response.text())
  } catch {
    throw new ApiIpcError(
      "invalid_api_response",
      "The API service returned an invalid response.",
    )
  }
  if (!isRecord(value) || !("data" in value) || !("error" in value)) {
    throw new ApiIpcError(
      "invalid_api_response",
      "The API service returned an invalid response.",
    )
  }
  let error: ApiErrorDto | null = null
  if (value.error !== null) {
    if (
      !isRecord(value.error) ||
      typeof value.error.code !== "string" ||
      typeof value.error.message !== "string"
    ) {
      throw new ApiIpcError(
        "invalid_api_response",
        "The API service returned an invalid response.",
      )
    }
    error = {
      code: redactString(value.error.code, secrets),
      message: redactString(value.error.message, secrets),
      ...(value.error.details === undefined
        ? {}
        : { details: sanitizeDetails(value.error.details, secrets) }),
    }
  }
  if (response.ok && error !== null) {
    throw new ApiIpcError(
      "invalid_api_response",
      "The API service returned an invalid response.",
    )
  }
  if (!response.ok && error === null) {
    throw new ApiIpcError(
      "invalid_api_response",
      "The API service returned an invalid response.",
    )
  }
  return {
    status: response.status,
    data: response.ok ? value.data : null,
    error,
  }
}

async function toBridgeResult<T>(
  operation: () => Promise<T>,
): Promise<BridgeResult<T>> {
  try {
    return { ok: true, data: await operation() }
  } catch (error) {
    if (error instanceof ApiIpcError) {
      return {
        ok: false,
        error: {
          code: error.code,
          message: error.message,
          ...(error.details === undefined ? {} : { details: error.details }),
        },
      }
    }
    return {
      ok: false,
      error: { code: "internal_error", message: "请求处理失败，请稍后重试。" },
    }
  }
}

function invalidRequest(): ApiIpcError {
  return new ApiIpcError("invalid_request", "请求内容不符合要求。")
}

function collectSensitiveValues(value: unknown, depth = 0): string[] {
  if (depth > 5 || ArrayBuffer.isView(value) || !isRecord(value)) {
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

function sanitizeDetails(value: unknown, secrets: string[], depth = 0): unknown {
  if (depth > 5) return "[TRUNCATED]"
  if (typeof value === "string") return redactString(value, secrets)
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

function isAbortError(error: unknown): boolean {
  return isRecord(error) && error.name === "AbortError"
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}
