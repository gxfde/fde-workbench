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
// CR-071（夜审 r8 设计稿推荐 A）：校验族提升 shared/api-safety.ts 纯函数单点。
// web 桥与桌面 main/api-ipc.ts 消费同一实现——method 白名单／auth 路径排除／
// 编码结构逃逸（raw+decoded 双查）／multipart 严格 schema（非法显式拒绝、
// 不再降级），与桌面恒等价（tests 等价性静态钉防再漂移）。
// QR-112（批 R7）：响应面信封判定（parseApiEnvelope）同点共用——四条不变量
// 双桥恒同，补齐 web 桥响应面校验缺口。
import {
  isAllowedMethod,
  isAuthExcludedPath,
  isBodySerializable,
  isMultipartFileShape,
  isSafeApiPath,
  parseApiEnvelope,
  validateCustomHeaders,
  type MultipartFileBodyShape,
} from "../../shared/api-safety"

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

// CR-071：multipart 组装（形状校验已由 shared 原语 isMultipartFileShape 先行
// 通过；旧版 buildMultipartBody 形状非法 return null 的静默降级路径已废除）。
function buildMultipartBody(value: MultipartFileBodyShape): FormData {
  const form = new FormData()
  for (const [key, item] of Object.entries(value.fields)) {
    if (typeof item === "string") form.append(key, item)
  }
  form.append(value.file.field_name, new Blob([value.file.bytes.slice()], { type: value.file.type }), value.file.name)
  return form
}

// 校验项 2+3+4+5+8：路径安全（raw+decoded 双查遍历/编码结构逃逸/控制字符
// ＋origin 归一匹配）＋auth 路径排除（与桌面同尺，verify-password 唯一例外）。
// 同源 web 形态 origin＝window.location.origin，杜绝把 access token 发到外部域。
function isSafeApiRequest(path: string, method: string): boolean {
  if (!isSafeApiPath(path, window.location.origin)) return false
  return !isAuthExcludedPath(path, method)
}

async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions,
): Promise<BridgeResult<ApiResponse<T>>> {
  // 校验项 1：method 白名单（此前 web 桥零校验，任意 method 可发——本轮封堵）
  if (!isAllowedMethod(options.method)) {
    return fail({ code: "invalid_request", message: "请求方法不合法。" })
  }
  if (!isSafeApiRequest(path, options.method)) {
    return fail({ code: "invalid_request", message: "请求路径不合法。" })
  }
  // GET 不带 body（桌面 validateRequest 同一语义——等价性样本钉覆盖）
  if (options.method === "GET" && options.body !== undefined) {
    return fail({ code: "invalid_request", message: "GET 请求不应携带请求体。" })
  }
  // 校验项 6＋7：multipart 严格 schema（非法显式拒绝，不再无 body 裸发）
  // ＋body 可序列化回环（与桌面 serializeBody 同一语义）
  let multipart: FormData | null = null
  if (isRecord(options.body) && options.body.kind === "multipart_file") {
    if (!isMultipartFileShape(options.body)) {
      return fail({ code: "invalid_request", message: "请求体形状不合法。" })
    }
    multipart = buildMultipartBody(options.body)
  } else if (options.body !== undefined && !isBodySerializable(options.body)) {
    return fail({ code: "invalid_request", message: "请求体不可序列化。" })
  }
  // 校验项 9（shared 原语）：自定义请求头允许名单（只有 x-diagnostic-token）。
  if (validateCustomHeaders(options.headers) !== null) {
    return fail({ code: "invalid_request", message: "自定义请求头不合法。" })
  }
  const headers: Record<string, string> = {
    accept: "application/json",
    // 空令牌＝公开面（获客诊断 T-14a 免注册流程）：不下发 Authorization 头。
    ...(options.accessToken
      ? { authorization: `Bearer ${options.accessToken}` }
      : {}),
    // 自定义头只有 x-diagnostic-token（共享原语已把关），不可能与上面
    // 两个桥自带头发生命名冲突。
    ...(options.headers ?? {}),
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
  // QR-112（goal-crv-fix2 批 R7）：响应面四条不变量改由 shared/api-safety::
  // parseApiEnvelope 单点判定（与桌面桥恒同）——补齐 ok∧error 拒／!ok∧¬error
  // 拒／!ok data 置空／错误体形态校验四处不等价缺口；错误体形态经同一判定。
  const verdict = parseApiEnvelope(payload, response.status)
  if (verdict.kind === "invalid") {
    return fail({ code: "invalid_api_response", message: "服务返回了无效响应。" })
  }
  if (verdict.kind === "error") {
    return ok({
      status: response.status,
      data: null as T,
      error: toApiError(verdict.error, "请求失败，请稍后重试。"),
    })
  }
  return ok({ status: response.status, data: verdict.data as T, error: null })
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
    version: async () => "0.3.0-r52-web",
    setLcscEnabled: async () => {},
    openLcscBrowser: async (url: string) => {
      // CR-070：与桌面 main 层 allowsLcscUrl 同尺三域 https 白名单——
      // 分发的 API 面应收窄；桌面同操作会报「只允许打开立创商城公开页面」。
      if (!/^https:\/\/(www|so|item)\.szlcsc\.com\//.test(url)) return
      window.open(url, "_blank", "noopener,noreferrer")
    },
    showLcscDownload: async () => {},
    copyLcscRunId: async (id: string) => { void navigator.clipboard?.writeText(id) },
    // CR-056（夜审 r6 A′）：直连分片上传计数面。web 形态无 close-guard（同源反代
    // 且无主窗拦截），计数恒为 no-op——保持 FdeBridge 契约形状与桌面 preload 对齐，
    // upload-helper 的 notifyUploadBegin/End 在 web 形态下零行为变化。
    uploadBegin: async () => {},
    uploadEnd: async () => {},
  },
}

window.fde = bridge
