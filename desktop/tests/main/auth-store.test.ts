import { Buffer } from "node:buffer"

import { describe, expect, it, vi } from "vitest"

import {
  createAuthStore,
  type AuthStoreFileSystem,
  type SafeStorageAdapter,
} from "../../src/main/auth-store"

function createHarness(options: { encryptionAvailable?: boolean } = {}) {
  const files: AuthStoreFileSystem = {
    mkdir: vi.fn().mockResolvedValue(undefined),
    writeFile: vi.fn().mockResolvedValue(undefined),
    rename: vi.fn().mockResolvedValue(undefined),
    readFile: vi.fn(),
    unlink: vi.fn().mockResolvedValue(undefined),
  }
  const safeStorage: SafeStorageAdapter = {
    isEncryptionAvailable: vi
      .fn()
      .mockReturnValue(options.encryptionAvailable ?? true),
    encryptString: vi
      .fn()
      .mockImplementation((value: string) => Buffer.from(`encrypted:${value.length}`)),
    decryptString: vi.fn().mockReturnValue("decrypted-refresh-token"),
  }

  return {
    files,
    safeStorage,
    store: createAuthStore({
      files,
      safeStorage,
      userDataPath: "/private/user-data",
      temporaryName: () => "session.bin.tmp-test",
    }),
  }
}

describe("auth store", () => {
  it("persists refresh tokens as plaintext to avoid OS keychain prompts", async () => {
    const { files, store } = createHarness()

    await store.save("raw-refresh-token")

    expect(files.writeFile).toHaveBeenCalledWith(
      "/private/user-data/session.bin.tmp-test",
      Buffer.from("raw-refresh-token"),
      { flag: "wx", mode: 0o600 },
    )
    expect(String(vi.mocked(files.writeFile).mock.calls[0]?.[1])).not.toContain(
      "encrypted",
    )
  })

  it("atomically promotes the protected session file", async () => {
    const { files, store } = createHarness()

    await store.save("raw-refresh-token")

    expect(files.mkdir).toHaveBeenCalledWith("/private/user-data", {
      recursive: true,
      mode: 0o700,
    })
    expect(files.rename).toHaveBeenCalledWith(
      "/private/user-data/session.bin.tmp-test",
      "/private/user-data/session.bin",
    )
    expect(vi.mocked(files.writeFile).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(files.rename).mock.invocationCallOrder[0]!,
    )
  })

  it("persists without requiring OS-backed encryption", async () => {
    const { files, store } = createHarness({ encryptionAvailable: false })

    await store.save("raw-refresh-token")

    expect(files.writeFile).toHaveBeenCalled()
  })

  it("loads the plaintext session", async () => {
    const { files, store } = createHarness({ encryptionAvailable: false })
    vi.mocked(files.readFile).mockResolvedValue(Buffer.from("raw-refresh-token"))

    await expect(store.load()).resolves.toBe("raw-refresh-token")
  })

  it("returns null when there is no persisted session", async () => {
    const { files, store } = createHarness()
    vi.mocked(files.readFile).mockRejectedValue(
      Object.assign(new Error("not found"), { code: "ENOENT" }),
    )

    await expect(store.load()).resolves.toBeNull()
  })

  it("clears both the final and interrupted temporary session files", async () => {
    const { files, store } = createHarness()

    await store.clear()

    expect(files.unlink).toHaveBeenCalledWith("/private/user-data/session.bin")
    expect(files.unlink).toHaveBeenCalledWith(
      "/private/user-data/session.bin.tmp-test",
    )
  })
})
