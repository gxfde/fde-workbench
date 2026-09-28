import { Buffer } from "node:buffer"
import { promises as nodeFiles } from "node:fs"
import { join } from "node:path"

export interface SafeStorageAdapter {
  isEncryptionAvailable(): boolean
  encryptString(value: string): Buffer
  decryptString(value: Buffer): string
}

export interface AuthStoreFileSystem {
  mkdir(path: string, options: { recursive: true; mode: number }): Promise<unknown>
  writeFile(
    path: string,
    data: Uint8Array,
    options: { flag: "wx"; mode: number },
  ): Promise<unknown>
  rename(from: string, to: string): Promise<unknown>
  readFile(path: string): Promise<Buffer>
  unlink(path: string): Promise<unknown>
}

export interface AuthStore {
  save(refreshToken: string): Promise<void>
  load(): Promise<string | null>
  clear(): Promise<void>
}

interface CreateAuthStoreOptions {
  safeStorage: SafeStorageAdapter
  userDataPath: string
  files?: AuthStoreFileSystem
  temporaryName?: () => string
}

export class SecureStorageUnavailableError extends Error {
  constructor() {
    super("OS-backed secure storage is unavailable.")
    this.name = "SecureStorageUnavailableError"
  }
}

export class SessionStoreError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = "SessionStoreError"
  }
}

export function createAuthStore(options: CreateAuthStoreOptions): AuthStore {
  const files = options.files ?? nodeFiles
  const finalPath = join(options.userDataPath, "session.bin")
  const temporaryPath = join(
    options.userDataPath,
    options.temporaryName?.() ?? "session.bin.tmp",
  )

  async function save(refreshToken: string): Promise<void> {
    if (!refreshToken) {
      throw new SessionStoreError("Cannot store an empty session.")
    }

    await files.mkdir(options.userDataPath, { recursive: true, mode: 0o700 })
    await unlinkIfPresent(files, temporaryPath)
    try {
      await files.writeFile(temporaryPath, Buffer.from(refreshToken, "utf8"), {
        flag: "wx",
        mode: 0o600,
      })
      await files.rename(temporaryPath, finalPath)
    } catch (error) {
      await unlinkIfPresent(files, temporaryPath)
      throw new SessionStoreError("The session could not be persisted.", {
        cause: error,
      })
    }
  }

  async function load(): Promise<string | null> {
    let value: Buffer
    try {
      value = await files.readFile(finalPath)
    } catch (error) {
      if (isMissingFile(error)) {
        return null
      }
      throw new SessionStoreError("The session could not be read.", {
        cause: error,
      })
    }

    const token = value.toString("utf8")
    if (!token) {
      throw new SessionStoreError("The session was empty.")
    }
    return token
  }

  async function clear(): Promise<void> {
    const results = await Promise.allSettled([
      unlinkIfPresent(files, finalPath),
      unlinkIfPresent(files, temporaryPath),
    ])
    const failure = results.find(
      (result): result is PromiseRejectedResult => result.status === "rejected",
    )
    if (failure) {
      throw new SessionStoreError("The local session could not be cleared.", {
        cause: failure.reason,
      })
    }
  }

  return { save, load, clear }
}

async function unlinkIfPresent(
  files: AuthStoreFileSystem,
  path: string,
): Promise<void> {
  try {
    await files.unlink(path)
  } catch (error) {
    if (!isMissingFile(error)) {
      throw error
    }
  }
}

function isMissingFile(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "ENOENT"
  )
}
