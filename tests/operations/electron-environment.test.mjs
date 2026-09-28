import assert from "node:assert/strict"
import test from "node:test"

import { buildElectronEnvironment } from "../../scripts/electron-environment.mjs"

test("passes only operating-system context and the desktop API URL to Electron", () => {
  const result = buildElectronEnvironment({
    PATH: "/usr/bin",
    HOME: "/tmp/home",
    LANG: "zh_CN.UTF-8",
    FDE_DATABASE_URL: "server-database-secret",
    FDE_JWT_SECRET: "server-jwt-secret",
    FDE_REDIS_URL: "redis://server-only",
    FDE_E2E_ADMIN_PASSWORD: "e2e-password-secret",
  }, "http://127.0.0.1:8010")

  assert.deepEqual(result, {
    PATH: "/usr/bin",
    HOME: "/tmp/home",
    LANG: "zh_CN.UTF-8",
    FDE_DESKTOP_API_URL: "http://127.0.0.1:8010",
  })
  assert.equal(JSON.stringify(result).includes("secret"), false)
})
