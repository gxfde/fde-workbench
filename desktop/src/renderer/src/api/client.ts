import type {
  ApiErrorDto,
  ApiMethod,
  ApiRequestOptions,
  ApiResponse,
  BridgeResult,
} from "../../../shared/contracts"

export interface ApiTransport {
  request<T>(
    path: string,
    options: ApiRequestOptions,
  ): Promise<BridgeResult<ApiResponse<T>>>
}

export interface ApiSessionAdapter {
  getSessionSnapshot(): ApiSessionSnapshot | null
  refreshAccess(expected: ApiSessionSnapshot): Promise<ApiSessionSnapshot | null>
  onUnauthorized(expected: ApiSessionSnapshot): void
}

export interface ApiSessionSnapshot {
  generation: number
  userId: string
  accessToken: string
  accessExpiresAt: string
}

export interface RendererApiRequestOptions {
  method: ApiMethod
  body?: unknown
  retryAfterAuthRefresh?: boolean
}

export class ApiClientError extends Error implements ApiErrorDto {
  readonly code: string
  readonly details?: unknown
  readonly status?: number

  constructor(error: ApiErrorDto, status?: number) {
    super(error.message.replaceAll("DSH", "AI Server").replaceAll("dsh-market", "AI Server 插件市场"))
    this.name = "ApiClientError"
    this.code = error.code
    this.details = error.details
    this.status = status
  }
}

export function createApiClient(
  transport: ApiTransport,
  session: ApiSessionAdapter,
): <T>(path: string, options: RendererApiRequestOptions) => Promise<T> {
  return async function apiRequest<T>(
    path: string,
    options: RendererApiRequestOptions,
  ): Promise<T> {
    const { retryAfterAuthRefresh: _retryAfterAuthRefresh, ...transportOptions } = options
    const origin = session.getSessionSnapshot()
    if (!origin) {
      throw new ApiClientError({
        code: "authentication_required",
        message: "Authentication is required.",
      })
    }

    const initialResult = await transport.request<T>(path, {
      ...transportOptions,
      accessToken: origin.accessToken,
    })
    if (!sameSnapshot(origin, session.getSessionSnapshot())) {
      throw staleSessionResponse()
    }
    if (!initialResult.ok) {
      throw new ApiClientError(initialResult.error)
    }
    const first = initialResult.data
    if (first.status !== 401) {
      return unwrapApiResponse(first)
    }

    const current = session.getSessionSnapshot()
    if (!sameIdentity(origin, current)) {
      throw staleSessionResponse()
    }

    if (current.accessToken !== origin.accessToken) {
      if (!canRetryAfterRefresh(options)) {
        throw mutationResubmitRequired()
      }
      return retryRequest(transport, session, path, options, current)
    }

    const refreshed = await session.refreshAccess(origin)
    if (!refreshed) {
      const afterFailure = session.getSessionSnapshot()
      if (afterFailure && !sameIdentity(origin, afterFailure)) {
        throw staleSessionResponse()
      }
      if (
        afterFailure &&
        afterFailure.accessToken !== origin.accessToken
      ) {
        if (!canRetryAfterRefresh(options)) {
          throw mutationResubmitRequired()
        }
        return retryRequest(transport, session, path, options, afterFailure)
      }
      session.onUnauthorized(origin)
      throw new ApiClientError(
        first.error ?? {
          code: "authentication_required",
          message: "Authentication is required.",
        },
        401,
      )
    }

    const afterRefresh = session.getSessionSnapshot()
    if (
      !sameIdentity(origin, refreshed) ||
      !sameSnapshot(refreshed, afterRefresh)
    ) {
      throw staleSessionResponse()
    }
    if (!canRetryAfterRefresh(options)) {
      throw mutationResubmitRequired()
    }
    return retryRequest(transport, session, path, options, refreshed)
  }
}

async function retryRequest<T>(
  transport: ApiTransport,
  session: ApiSessionAdapter,
  path: string,
  options: RendererApiRequestOptions,
  snapshot: ApiSessionSnapshot,
): Promise<T> {
  const { retryAfterAuthRefresh: _retryAfterAuthRefresh, ...transportOptions } = options
  const result = await transport.request<T>(path, {
    ...transportOptions,
    accessToken: snapshot.accessToken,
  })
  const current = session.getSessionSnapshot()
  if (!sameSnapshot(snapshot, current)) {
    throw staleSessionResponse()
  }
  if (!result.ok) {
    throw new ApiClientError(result.error)
  }
  const retried = result.data
  if (retried.status === 401) {
    session.onUnauthorized(snapshot)
  }
  return unwrapApiResponse(retried)
}

function canRetryAfterRefresh(options: RendererApiRequestOptions): boolean {
  return options.method === "GET" || options.retryAfterAuthRefresh === true
}

function unwrapApiResponse<T>(response: ApiResponse<T>): T {
  if (response.error) {
    throw new ApiClientError(response.error, response.status)
  }
  if (response.status === 204) return undefined as T
  if (response.data === null) {
    throw new ApiClientError(
      { code: "invalid_api_response", message: "The API response has no data." },
      response.status,
    )
  }
  return response.data
}

function sameIdentity(
  expected: ApiSessionSnapshot,
  current: ApiSessionSnapshot | null,
): current is ApiSessionSnapshot {
  return Boolean(
    current &&
      current.generation === expected.generation &&
      current.userId === expected.userId,
  )
}

function sameSnapshot(
  expected: ApiSessionSnapshot,
  current: ApiSessionSnapshot | null,
): current is ApiSessionSnapshot {
  return sameIdentity(expected, current) &&
    current.accessToken === expected.accessToken &&
    current.accessExpiresAt === expected.accessExpiresAt
}

function staleSessionResponse(): ApiClientError {
  return new ApiClientError({
    code: "stale_session_response",
    message: "登录会话已更改，已忽略过期请求。",
  })
}

function mutationResubmitRequired(): ApiClientError {
  return new ApiClientError({
    code: "authentication_refreshed_resubmit",
    message: "登录状态已刷新，请重新提交本次操作。",
  })
}
