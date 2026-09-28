export const USERNAME_MAX_LENGTH = 120
export const PASSWORD_MAX_LENGTH = 1_024

export const USER_ROLES = ["admin", "project_lead", "fde_engineer", "viewer"] as const
export type UserRole = (typeof USER_ROLES)[number]

export function isUserRole(value: unknown): value is UserRole {
  return typeof value === "string" && (USER_ROLES as readonly string[]).includes(value)
}

export interface UserDto {
  id: string
  username: string
  displayName: string
  role: UserRole
  mustChangePassword: boolean
  isActive: boolean
}

export interface ApiErrorDto {
  code: string
  message: string
  details?: unknown
}

export interface AuthResult {
  accessToken: string
  accessExpiresAt: string
  refreshExpiresAt: string
  user: UserDto
}

export interface LoginInput {
  username: string
  password: string
  deviceLabel: string
}

export type ApiMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE"

export interface ApiRequestOptions {
  method: ApiMethod
  accessToken: string
  body?: unknown
}

export interface ApiResponse<T> {
  status: number
  data: T | null
  error: ApiErrorDto | null
}

export type BridgeResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: ApiErrorDto }

export interface FdeBridge {
  auth: {
    login(input: LoginInput): Promise<BridgeResult<AuthResult>>
    refresh(): Promise<BridgeResult<AuthResult | null>>
    changePassword(
      accessToken: string,
      currentPassword: string,
      newPassword: string,
    ): Promise<BridgeResult<AuthResult>>
    logout(): Promise<BridgeResult<null>>
  }
  api: {
    request<T>(
      path: string,
      options: ApiRequestOptions,
    ): Promise<BridgeResult<ApiResponse<T>>>
  }
  app: {
    version(): Promise<string>
    openLcscBrowser?(url: string): Promise<void>
    showLcscDownload?(filename: string): Promise<void>
    copyLcscRunId?(id: string): Promise<void>
  }
}

export const IPC_CHANNELS = {
  authLogin: "fde:auth:login",
  authRefresh: "fde:auth:refresh",
  authChangePassword: "fde:auth:change-password",
  authLogout: "fde:auth:logout",
  apiRequest: "fde:api:request",
  appVersion: "fde:app:version",
  appOpenLcscBrowser: "fde:app:open-lcsc-browser",
  appShowLcscDownload: "fde:app:show-lcsc-download",
  appCopyLcscRunId: "fde:app:copy-lcsc-run-id",
} as const

declare global {
  interface Window {
    fde: FdeBridge
  }
}
