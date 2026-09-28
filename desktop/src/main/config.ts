import { isAbsolute, relative, sep } from "node:path"
import { fileURLToPath } from "node:url"

export const DEVELOPMENT_API_URL = "http://127.0.0.1:8010"

export interface ApiUrlEnvironment {
  isPackaged: boolean
  allowPackagedLocalApi?: boolean
}

export interface RendererUrlEnvironment {
  isPackaged: boolean
  rendererRoot: string
  developmentUrl?: string
}

export function resolveApiBaseUrl(
  configuredUrl: string | undefined,
  environment: ApiUrlEnvironment,
): string {
  const candidate = configuredUrl ?? (environment.isPackaged ? undefined : DEVELOPMENT_API_URL)
  if (!candidate) {
    throw new Error("FDE_DESKTOP_API_URL is required in production.")
  }

  let url: URL
  try {
    url = new URL(candidate)
  } catch {
    throw new Error("FDE_DESKTOP_API_URL must be a valid absolute URL.")
  }

  if (
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  ) {
    throw new Error("FDE_DESKTOP_API_URL must contain only an origin.")
  }

  const normalized = url.origin
  if (url.protocol === "https:") {
    return normalized
  }

  if (
    (!environment.isPackaged
      && url.protocol === "http:"
      && url.hostname === "127.0.0.1"
      && url.port !== "")
    || (
      normalized === DEVELOPMENT_API_URL
      && environment.allowPackagedLocalApi === true
    )
  ) {
    return normalized
  }

  throw new Error(
    "FDE_DESKTOP_API_URL must use HTTPS (except an explicitly enabled exact local API URL).",
  )
}

export function isAllowedRendererUrl(
  candidate: string,
  environment: RendererUrlEnvironment,
): boolean {
  if (!environment.isPackaged && environment.developmentUrl) {
    try {
      const target = new URL(candidate)
      const development = new URL(environment.developmentUrl)
      return (
        (development.protocol === "http:" || development.protocol === "https:") &&
        target.origin === development.origin
      )
    } catch {
      return false
    }
  }

  try {
    const url = new URL(candidate)
    if (url.protocol !== "file:" || url.search) {
      return false
    }
    const child = relative(environment.rendererRoot, fileURLToPath(url))
    return (
      child === "" ||
      (child !== ".." && !child.startsWith(`..${sep}`) && !isAbsolute(child))
    )
  } catch {
    return false
  }
}
