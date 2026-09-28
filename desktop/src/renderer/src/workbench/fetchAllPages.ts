import { ApiClientError, type RendererApiRequestOptions } from "../api/client"
import type { PageDto } from "./types"

interface PageRequester {
  <T>(path: string, options: RendererApiRequestOptions): Promise<T>
}

export async function fetchAllPages<T>({
  apiRequest,
  pathForPage,
  itemKey,
  validateItem,
  signal,
  pageSize = 100,
}: {
  apiRequest: PageRequester
  pathForPage(page: number, pageSize: number): string
  itemKey(item: T): string
  validateItem(item: unknown): item is T
  signal: AbortSignal
  pageSize?: number
}): Promise<T[]> {
  const items = new Map<string, T>()
  let page = 1
  let expectedTotal: number | null = null

  while (true) {
    throwIfAborted(signal)
    const response = await apiRequest<unknown>(pathForPage(page, pageSize), { method: "GET" })
    throwIfAborted(signal)
    const result: PageDto<T> = requirePage(response, page, pageSize, validateItem, expectedTotal)
    if (expectedTotal === null) expectedTotal = result.total
    for (const item of result.items) {
      const key = itemKey(item)
      if (!items.has(key)) items.set(key, item)
    }

    if (page * result.page_size >= result.total) {
      if (items.size !== result.total) throw incompletePagination()
      return [...items.values()]
    }
    if (result.items.length === 0) throw incompletePagination()
    page += 1
  }
}

export function requirePage<T>(
  value: unknown,
  requestedPage: number,
  requestedPageSize: number,
  validateItem: (item: unknown) => item is T,
  expectedTotal: number | null = null,
): PageDto<T> {
  if (
    !isRecord(value) ||
    value.page !== requestedPage ||
    value.page_size !== requestedPageSize ||
    typeof value.total !== "number" ||
    !Number.isInteger(value.total) ||
    value.total < 0 ||
    !Array.isArray(value.items) ||
    value.items.length > requestedPageSize ||
    value.items.length > value.total ||
    (expectedTotal !== null && value.total !== expectedTotal)
  ) {
    throw incompletePagination()
  }
  const items: T[] = []
  for (const item of value.items) {
    if (!validateItem(item)) throw incompletePagination()
    items.push(item)
  }
  return { items, page: requestedPage, page_size: requestedPageSize, total: value.total }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function throwIfAborted(signal: AbortSignal): void {
  if (signal.aborted) throw new DOMException("The paginated request was aborted.", "AbortError")
}

function incompletePagination(): ApiClientError {
  return new ApiClientError({
    code: "incomplete_pagination",
    message: "The paginated response changed or ended before all items were loaded.",
  })
}
