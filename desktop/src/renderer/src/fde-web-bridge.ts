// 浏览器发行形态的 window.fde 实现。
//
// 与 Electron preload 共用 shared/contracts.ts 的 FdeBridge 契约，但所有请求走
// 同源 /api 反向代理（API_BASE = ""），因此服务端无需 CORS、无需改动鉴权端点。
//
// 会话只保留在模块内存：刷新页面即回到登录页。refresh token 不写 localStorage /
// sessionStorage，避免落到可被 XSS 读取的持久存储。改成 httpOnly cookie 需要服务端
// 调整 /api/v1/auth/refresh 的取参方式，属于独立的后续增强，不在本次范围。
//
// 桌面端不会加载本文件：electron-vite 的 renderer 入口固定 index.html -> main.tsx，
// 只有 web.html -> web-main.tsx 会引入这里。

import {
  isUserRole,
  type ApiErrorDto,
  type ApiRequestOptions,
  type ApiResponse,
  type AuthResult,
  type BridgeResult,
  type FdeBridge,
  type LoginInput,
  type UserDto,
} from "../../shared/contracts"

// 同源反代：路径一律以 /api/v1/ 开头，由 Nginx 转发到回环 8010。
const API_BASE = ""

let accessToken: string | null = null
let refreshToken: string | null = null
let currentUser: UserDto | null = null

function ok<T>(data: T): BridgeResult<T> {
  return { ok: true, data }
}

function fail(error: ApiErrorDto): BridgeResult<never> {
  return { ok: false, error }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function toApiError(value: unknown, fallback: string): ApiErrorDto {
  if (isRecord(value) && typeof value.code === "string" && typeof value.message === "string") {
    return { code: value.code, message: value.message, ...(value.details === undefined ? {} : { details: value.details }) }
  }
  return { code: "request_failed", message: fallback }
}

// 服务端 login / refresh / change-password 返回的 user 是 snake_case，
// 渲染层 UserDto 是 camelCase —— 桌面端由 main/auth-ipc.ts 转换，此处等价实现。
function toUser(raw: unknown): UserDto | null {
  if (!isRecord(raw)) return null
  if (
    typeof raw.id !== "string" || typeof raw.username !== "string" ||
    typeof raw.display_name !== "string" || !isUserRole(raw.role) ||
    typeof raw.must_change_password !== "boolean" || typeof raw.is_active !== "boolean"
  ) return null
  return {
    id: raw.id,
    username: raw.username,
    displayName: raw.display_name,
    role: raw.role,
    mustChangePassword: raw.must_change_password,
    isActive: raw.is_active,
  }
}

function toAuthResult(raw: unknown): { result: AuthResult; refreshToken: string } | null {
  if (!isRecord(raw)) return null
  const nextUser = toUser(raw.user)
  if (
    !nextUser || typeof raw.access_token !== "string" || !raw.access_token ||
    typeof raw.refresh_token !== "string" || !raw.refresh_token ||
    typeof raw.access_expires_at !== "string" || typeof raw.refresh_expires_at !== "string"
  ) return null
  return {
    result: {
      accessToken: raw.access_token,
      accessExpiresAt: raw.access_expires_at,
      refreshExpiresAt: raw.refresh_expires_at,
      user: nextUser,
    },
    refreshToken: raw.refresh_token,
  }
}

function storeSession(parsed: { result: AuthResult; refreshToken: string }): AuthResult {
  accessToken = parsed.result.accessToken
  refreshToken = parsed.refreshToken
  currentUser = parsed.result.user
  return parsed.result
}

// 仅供诊断/断言使用，不对外暴露令牌。
export function webBridgeSessionState(): { hasAccess: boolean; hasRefresh: boolean; username: string | null } {
  return {
    hasAccess: accessToken !== null,
    hasRefresh: refreshToken !== null,
    username: currentUser?.username ?? null,
  }
}

async function postAuth(
  path: string,
  body: Record<string, unknown>,
  bearer?: string,
): Promise<BridgeResult<Record<string, unknown>>> {
  let response: Response
  try {
    response = await fetch(API_BASE + path, {
      method: "POST",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
        ...(bearer ? { authorization: `Bearer ${bearer}` } : {}),
      },
      body: JSON.stringify(body),
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer",
    })
  } catch {
    return fail({ code: "network_error", message: "无法连接服务，请稍后重试。" })
  }
  let payload: unknown = null
  try { payload = await response.json() } catch { /* handled below */ }
  if (!isRecord(payload) || !("data" in payload) || !("error" in payload)) {
    return fail({ code: "invalid_api_response", message: "认证服务返回了无效响应。" })
  }
  if (payload.error !== null) {
    return fail(toApiError(payload.error, "认证请求失败。"))
  }
  if (!response.ok || !isRecord(payload.data)) {
    return fail({ code: "invalid_api_response", message: "认证服务返回了无效响应。" })
  }
  return ok(payload.data)
}

async function login(input: LoginInput): Promise<BridgeResult<AuthResult>> {
  const response = await postAuth("/api/v1/auth/login", {
    username: input.username,
    password: input.password,
    device_label: input.deviceLabel || "FDE Workbench Web",
  })
  if (!response.ok) return response
  const parsed = toAuthResult(response.data)
  if (!parsed) return fail({ code: "invalid_api_response", message: "登录响应缺少令牌。" })
  return ok(storeSession(parsed))
}

async function refresh(): Promise<BridgeResult<AuthResult | null>> {
  if (!refreshToken) return ok(null)
  const response = await postAuth("/api/v1/auth/refresh", { refresh_token: refreshToken })
  if (!response.ok) return response
  const parsed = toAuthResult(response.data)
  if (!parsed) return fail({ code: "invalid_api_response", message: "刷新响应缺少令牌。" })
  return ok(storeSession(parsed))
}

async function changePassword(
  accessTokenOverride: string,
  currentPassword: string,
  newPassword: string,
): Promise<BridgeResult<AuthResult>> {
  const response = await postAuth("/api/v1/auth/change-password", {
    current_password: currentPassword,
    new_password: newPassword,
  }, accessTokenOverride)
  if (!response.ok) return response
  const parsed = toAuthResult(response.data)
  if (!parsed) return fail({ code: "invalid_api_response", message: "改密响应缺少令牌。" })
  return ok(storeSession(parsed))
}

async function logout(): Promise<BridgeResult<null>> {
  const current = refreshToken
  accessToken = null
  refreshToken = null
  currentUser = null
  if (current) {
    try {
      await fetch(API_BASE + "/api/v1/auth/logout", {
        method: "POST",
        headers: { "content-type": "application/json", accept: "application/json" },
        body: JSON.stringify({ refresh_token: current }),
        credentials: "omit",
        cache: "no-store",
        referrerPolicy: "no-referrer",
      })
    } catch { /* 本地会话已清，远端失败不影响登出 */ }
  }
  return ok(null)
}

function buildMultipartBody(value: Record<string, unknown>): FormData | null {
  const fields = value.fields
  const file = value.file
  if (!isRecord(fields) || !isRecord(file)) return null
  const fieldName = file.field_name
  const name = file.name
  const type = file.type
  const bytes = file.bytes
  if (typeof fieldName !== "string" || typeof name !== "string" ||
      typeof type !== "string" || !(bytes instanceof Uint8Array)) return null
  const form = new FormData()
  for (const [key, item] of Object.entries(fields)) {
    if (typeof item === "string") form.append(key, item)
  }
  form.append(fieldName, new Blob([bytes.slice()], { type }), name)
  return form
}

// 路径白名单：只允许同源 /api/v1/ 下的相对路径，杜绝把 access token 发到外部域。
function isSafePath(path: string): boolean {
  if (!path.startsWith("/api/v1/") || path.includes("\\") || path.includes("#") ||
      path.includes("..") || /[\u0000-\u001f\u007f]/.test(path)) return false
  try {
    const url = new URL(path, window.location.origin)
    return url.origin === window.location.origin && url.pathname.startsWith("/api/v1/")
  } catch { return false }
}

async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions,
): Promise<BridgeResult<ApiResponse<T>>> {
  if (!isSafePath(path)) {
    return fail({ code: "invalid_request", message: "请求路径不合法。" })
  }
  const multipart = isRecord(options.body) && options.body.kind === "multipart_file"
    ? buildMultipartBody(options.body) : null
  const headers: Record<string, string> = {
    accept: "application/json",
    authorization: `Bearer ${options.accessToken}`,
  }
  let body: BodyInit | undefined
  if (multipart) body = multipart
  else if (options.body !== undefined) {
    headers["content-type"] = "application/json"
    body = JSON.stringify(options.body)
  }
  let response: Response
  try {
    response = await fetch(API_BASE + path, {
      method: options.method,
      headers,
      ...(body === undefined ? {} : { body }),
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer",
    })
  } catch {
    return fail({ code: "network_error", message: "无法连接服务，请确认服务已启动。" })
  }
  if (response.ok && response.status === 204) {
    return ok({ status: 204, data: null, error: null })
  }
  let payload: unknown = null
  try { payload = await response.json() } catch { /* handled below */ }
  if (!isRecord(payload) || !("data" in payload) || !("error" in payload)) {
    return fail({ code: "invalid_api_response", message: "服务返回了无效响应。" })
  }
  const error = payload.error === null ? null : toApiError(payload.error, "请求失败，请稍后重试。")
  return ok({ status: response.status, data: payload.data as T, error })
}

const bridge: FdeBridge = {
  auth: {
    login,
    refresh,
    changePassword,
    logout,
  },
  api: {
    request: <T>(path: string, options: ApiRequestOptions) => apiRequest<T>(path, options),
  },
  bridge: {
    // 浏览器无宿主计划任务，采集能力明确降级而不是假装成功。
    capture: async () => fail({ code: "bridge_platform", message: "浏览器版无宿主计划任务，无法手动采集。" }),
  },
  app: {
    version: async () => "0.3.0-web",
    setLcscEnabled: async () => {},
    openLcscBrowser: async (url: string) => { window.open(url, "_blank", "noopener,noreferrer") },
    showLcscDownload: async () => {},
    copyLcscRunId: async (id: string) => { void navigator.clipboard?.writeText(id) },
  },
}

window.fde = bridge
