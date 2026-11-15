import type { IpcMain, IpcMainInvokeEvent } from "electron"

import {
  IPC_CHANNELS,
  type ApiErrorDto,
  type ApiMethod,
  type ApiResponse,
  type BridgeResult,
} from "../shared/contracts"
// CR-071（夜审 r8 设计稿推荐 A）：校验族提升 shared/api-safety.ts 纯函数单点，
// 桌面 IPC 与 web 桥双消费同一原语；等价性静态钉防再漂移。
// QR-112（批 R7）：响应面信封判定与脱敏同点提升（四条不变量双桥恒同）。
import {
  collectEnvelopeSensitiveValues as collectSensitiveValues,
  isAllowedMethod,
  isAuthExcludedPath,
  isBodySerializable,
  isRecord,
  isSafeApiPath,
  parseApiEnvelope,
  redactSensitiveString as redactString,
  sanitizeEnvelopeDetails as sanitizeDetails,
  serializeBodyString,
  validateCustomHeaders,
  validateMultipartFileShape,
} from "../shared/api-safety"

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
  /** 获客诊断 T-14a：自定义请求头（允许名单只有 x-diagnostic-token）。 */
  headers?: Record<string, string>
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

export type ApiRequestHandler = (
  input: unknown,
) => Promise<ApiResponse<unknown>>

interface RegisterApiIpcOptions {
  ipcMain: Pick<IpcMain, "handle">
  request: ApiRequestHandler
  isTrustedSender(event: IpcMainInvokeEvent): boolean
}

const ALLOWED_KEYS = new Set(["path", "method", "accessToken", "body", "headers"])
// QR-112：REDACTED 随脱敏族提升 shared/api-safety.ts（RESPONSE_REDACTED）。

export class ApiIpcError extends Error implements ApiErrorDto {
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
    const secrets = [
      request.accessToken,
      ...Object.values(request.headers ?? {}),
      ...collectSensitiveValues(request.body),
    ]
    try {
      const multipartBody = isMultipartFileBody(request.body) ? buildMultipartBody(request.body) : undefined
      const serializedBody = request.body === undefined || multipartBody
        ? undefined
        : serializeBody(request.body)
      const response = await options.fetch(request.url, {
        method: request.method,
        headers: {
          accept: "application/json",
          // 空令牌＝公开面（获客诊断 T-14a 免注册流程）：不下发 Authorization 头。
          ...(request.accessToken
            ? { authorization: `Bearer ${request.accessToken}` }
            : {}),
          ...(serializedBody === undefined || multipartBody
            ? {}
            : { "content-type": "application/json" }),
          // 自定义头只有 x-diagnostic-token（共享原语已把关），不可能与上面
          // 三个桥自带头发生命名冲突。
          ...(request.headers ?? {}),
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
    !isAllowedMethod(value.method) ||
    typeof value.accessToken !== "string" ||
    value.accessToken.length > 16_384
  ) {
    throw invalidRequest()
  }
  // 空令牌＝公开面（获客诊断 T-14a 免注册诊断流程）：桥只做传输安全，
  // 授权永远由服务端判（未授权端点仍回 401）。
  // 校验项 9（shared 原语）：自定义请求头允许名单。
  if (validateCustomHeaders(value.headers) !== null) {
    throw invalidRequest()
  }
  const path = value.path
  let apiOrigin: string
  try {
    apiOrigin = new URL(apiBaseUrl).origin
  } catch {
    throw invalidRequest()
  }
  // 校验项 2+3+4+5（路径遍历/编码结构逃逸/控制字符，raw+decoded 双查）
  // ＋校验项 8（origin 匹配）由 shared 原语 isSafeApiPath 一次判定，
  // 与 web 桥 fde-web-bridge.ts 消费同一实现（等价性静态钉防漂移）。
  if (!isSafeApiPath(path, apiOrigin)) {
    throw invalidRequest()
  }
  // 校验项 2：auth 路径排除（verify-password 唯一例外）
  if (isAuthExcludedPath(path, value.method)) {
    throw invalidRequest()
  }
  if (value.method === "GET" && value.body !== undefined) {
    throw invalidRequest()
  }
  if (value.body !== undefined) {
    // 校验项 6＋7（shared 原语）：声称 multipart_file 的 body 必须过严格 schema
    // （旧内联 validateMultipartFileBody 语义逐位保留——非法形状即拒，绝不落
    // JSON 回环分支被当普通 body 放行）；其余 body 走可序列化回环。
    if (isRecord(value.body) && value.body.kind === "multipart_file") {
      if (validateMultipartFileShape(value.body) !== null) throw invalidRequest()
    } else if (!isBodySerializable(value.body)) {
      throw invalidRequest()
    }
  }
  let finalUrl: URL
  try {
    finalUrl = new URL(path, `${apiBaseUrl}/`)
  } catch {
    throw invalidRequest()
  }
  // url 保留绝对形态（远程 apiBaseUrl 部署必需），isSafeApiPath 已断言
  // finalUrl.origin === apiOrigin，此处归一结果逐位等价旧行为。
  return {
    url: finalUrl.toString(),
    method: value.method as ApiMethod,
    accessToken: value.accessToken,
    ...(value.body === undefined ? {} : { body: value.body }),
    ...(value.headers === undefined
      ? {}
      : { headers: value.headers as Record<string, string> }),
  }
}

function isMultipartFileBody(value: unknown): value is MultipartFileBody {
  if (!isRecord(value) || value.kind !== "multipart_file") return false
  return validateMultipartFileShape(value) === null
}

function buildMultipartBody(value: MultipartFileBody): FormData {
  const body = new FormData()
  for (const [key, item] of Object.entries(value.fields)) body.append(key, item)
  const bytes = value.file.bytes.slice()
  body.append(value.file.field_name, new Blob([bytes], { type: value.file.type }), value.file.name)
  return body
}

// 传输层序列化（handler 内）：shared 原语产出字符串，此处翻译为
// invalid_request（与旧内联版逐位等价；校验面已由 validateRequest 先行通过）。
function serializeBody(body: unknown): string {
  try {
    return serializeBodyString(body)
  } catch {
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
  // QR-112：四条不变量改由 shared/api-safety::parseApiEnvelope 单点判定
  // （web 桥同函数——双桥响应面判定恒同），本侧只负责把 invalid 翻译为
  // ApiIpcError、把 error 体经共享脱敏纯函数出参。
  const verdict = parseApiEnvelope(value, response.status)
  if (verdict.kind === "invalid") {
    throw new ApiIpcError(
      "invalid_api_response",
      "The API service returned an invalid response.",
    )
  }
  if (verdict.kind === "error") {
    return {
      status: response.status,
      data: null,
      error: {
        code: redactString(verdict.error.code as string, secrets),
        message: redactString(verdict.error.message as string, secrets),
        ...(verdict.error.details === undefined
          ? {}
          : { details: sanitizeDetails(verdict.error.details, secrets) }),
      },
    }
  }
  return {
    status: response.status,
    data: verdict.data,
    error: null,
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

// QR-112：collectSensitiveValues / sanitizeDetails / redactString / isSensitiveKey
// / isRecord 已提升 shared/api-safety.ts 单点（import 别名保持调用点零改动）；
// 本地重复定义删除，行为逐位等价（实现逐字迁移）。

function isAbortError(error: unknown): boolean {
  return isRecord(error) && error.name === "AbortError"
}
