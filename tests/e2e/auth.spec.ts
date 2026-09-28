import { spawnSync, type ChildProcess } from "node:child_process"
import { _electron as electron, expect, test, type ElectronApplication, type Page } from "@playwright/test"
import { resolve } from "node:path"

import { findUnavailableRedisPort } from "../../scripts/unavailable-redis-port.mjs"
import { buildElectronEnvironment } from "../../scripts/electron-environment.mjs"
import { startEphemeralApiProcess, stopApiProcess } from "../../scripts/ephemeral-api-process.mjs"

const workbenchRoot = resolve(__dirname, "../..")
const desktopMainEntry = resolve(workbenchRoot, "desktop/out/main/index.js")
const serverRoot = resolve(workbenchRoot, "server")
let apiUrl = ""
let server: ChildProcess | undefined
let testSchemaReady = false
let unavailableRedisUrl: string | undefined

test.describe.configure({ mode: "serial" })

test.beforeAll(async () => {
  assertDedicatedTestDatabase(requiredEnvironment("FDE_DATABASE_URL"))
  unavailableRedisUrl = `redis://127.0.0.1:${await findUnavailableRedisPort()}/15`
  runServerCommand(["-m", "alembic", "upgrade", "head"])
  testSchemaReady = true
  runServerCommand([resolve(workbenchRoot, "tests/e2e/cleanup.py")])
  runServerCommand(
    [resolve(workbenchRoot, "tests/e2e/cleanup.py"), "--verify-upgrade-preservation"],
    {
      FDE_E2E_PRESERVED_ADMIN_PASSWORD: requiredEnvironment(
        "FDE_E2E_PRESERVED_ADMIN_PASSWORD",
      ),
    },
  )
  runServerCommand(
    [
      "-m",
      "flask",
      "--app",
      "fde_api.app:create_app",
      "create-admin",
      "--username",
      requiredEnvironment("FDE_E2E_PHASE1_ADMIN_USERNAME"),
      "--display-name",
      "系统管理员",
    ],
    { FDE_INITIAL_ADMIN_PASSWORD: requiredEnvironment("FDE_E2E_ADMIN_PASSWORD") },
  )
  const started = await startEphemeralApiProcess({
    command: resolve(serverRoot, ".venv/bin/python"),
    args: ["-m", "flask", "--app", "fde_api.app:create_app", "run", "--host", "127.0.0.1"],
    cwd: serverRoot,
    env: serverEnvironment(),
  })
  server = started.process
  apiUrl = started.apiUrl
  await waitForApi()
})

test.afterAll(async () => {
  await stopApiProcess(server)
  if (testSchemaReady) {
    runServerCommand([resolve(workbenchRoot, "tests/e2e/cleanup.py")])
  }
})

test("admin logs in, changes initial password, and creates an engineer", async () => {
  const initialPassword = requiredEnvironment("FDE_E2E_ADMIN_PASSWORD")
  const newPassword = requiredEnvironment("FDE_E2E_ADMIN_NEW_PASSWORD")
  const engineerPassword = requiredEnvironment("FDE_E2E_ENGINEER_PASSWORD")

  let application: ElectronApplication | undefined
  try {
    application = await electron.launch({
      args: [
        desktopMainEntry,
        `--user-data-dir=${resolve(requiredEnvironment("FDE_E2E_USER_DATA_PATH"), "auth")}`,
      ],
      env: buildElectronEnvironment(process.env, apiUrl),
    })
    const page = await application.firstWindow()

    const readiness = await fetchJson(`${apiUrl}/api/v1/health/ready`)
    expect(readiness.response.status).toBe(200)
    expect(readiness.payload.data).toEqual({ mysql: "ok", redis: "degraded" })

    await page.getByLabel("用户名").fill(requiredEnvironment("FDE_E2E_PHASE1_ADMIN_USERNAME"))
    await page.getByLabel("密码").fill(initialPassword)
    await page.getByRole("button", { name: "登录" }).click()
    await page.getByRole("heading", { name: "修改初始密码" }).waitFor()
    await completePasswordChange(page, initialPassword, newPassword)

    await page.getByRole("link", { name: "用户管理" }).click()
    await page.getByRole("heading", { name: "用户管理" }).waitFor()
    const engineerUsername = requiredEnvironment("FDE_E2E_PHASE1_ENGINEER_USERNAME")
    await createEngineer(page, engineerUsername, engineerPassword)
    await expect(page.getByRole("cell", { name: engineerUsername, exact: true })).toBeVisible()

    await verifyDisabledUserCannotContinue(newPassword, engineerPassword)
  } finally {
    await application?.close()
  }
})

async function completePasswordChange(
  page: Page,
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  await page.getByLabel("当前密码").fill(currentPassword)
  await page.getByLabel("新密码", { exact: true }).fill(newPassword)
  await page.getByLabel("确认新密码").fill(newPassword)
  await page.getByRole("button", { name: "保存新密码" }).click()
  const destination = page.getByRole("heading", { name: "项目工作台" })
  const alert = page.getByRole("alert")
  const outcome = await Promise.race([
    destination.waitFor().then(() => "destination" as const),
    alert.waitFor().then(() => "alert" as const),
  ])
  if (outcome === "alert") {
    throw new Error(
      `Password change failed in the UI: ${(await alert.textContent())?.trim() || "unknown error"}`,
    )
  }
}

async function createEngineer(
  page: Page,
  username: string,
  temporaryPassword: string,
): Promise<void> {
  await page.getByLabel("用户名").fill(username)
  await page.getByLabel("显示名称").fill("阶段一工程师")
  await page.getByLabel("角色").selectOption("fde_engineer")
  await page.getByLabel("临时密码").fill(temporaryPassword)
  await page.getByRole("button", { name: "创建账号" }).click()
  await expect(page.getByRole("status")).toContainText("账号已创建")
}

function requiredEnvironment(name: string): string {
  const value = process.env[name]
  if (!value) {
    throw new Error(`${name} is required for the Electron smoke test.`)
  }
  return value
}

async function verifyDisabledUserCannotContinue(
  adminPassword: string,
  engineerPassword: string,
): Promise<void> {
  const adminLogin = await postJson("/api/v1/auth/login", {
    username: requiredEnvironment("FDE_E2E_PHASE1_ADMIN_USERNAME"),
    password: adminPassword,
    device_label: "phase1-e2e-admin-api",
  })
  expect(adminLogin.response.status).toBe(200)
  const adminAccess = String(adminLogin.payload.data.access_token)

  const engineerLogin = await postJson("/api/v1/auth/login", {
    username: requiredEnvironment("FDE_E2E_PHASE1_ENGINEER_USERNAME"),
    password: engineerPassword,
    device_label: "phase1-e2e-engineer-api",
  })
  expect(engineerLogin.response.status).toBe(200)
  const engineerAccess = String(engineerLogin.payload.data.access_token)
  const engineerRefresh = String(engineerLogin.payload.data.refresh_token)
  const engineerId = String(engineerLogin.payload.data.user.id)

  const disabled = await fetchJson(`${apiUrl}/api/v1/users/${engineerId}`, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${adminAccess}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ is_active: false }),
  })
  expect(disabled.response.status).toBe(200)

  const existingAccess = await fetchJson(`${apiUrl}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${engineerAccess}` },
  })
  expect(existingAccess.response.status).toBe(401)
  expect(existingAccess.payload.error.code).toBe("access_token_invalid")

  const refreshed = await postJson("/api/v1/auth/refresh", {
    refresh_token: engineerRefresh,
  })
  expect(refreshed.response.status).toBe(401)
  expect(refreshed.payload.error.code).toBe("refresh_token_invalid")
}

function runServerCommand(
  args: string[],
  additionalEnvironment: NodeJS.ProcessEnv = {},
): void {
  const result = spawnSync(resolve(serverRoot, ".venv/bin/python"), args, {
    cwd: serverRoot,
    env: { ...serverEnvironment(), ...additionalEnvironment },
    encoding: "utf8",
  })
  if (result.status !== 0) {
    throw new Error(`E2E server setup failed: ${result.stderr || result.stdout}`)
  }
}

function serverEnvironment(): NodeJS.ProcessEnv {
  if (!unavailableRedisUrl) {
    throw new Error("The unavailable Redis endpoint must be verified before server setup.")
  }
  return {
    ...process.env,
    FDE_ENV: "test",
    FDE_API_HOST: "127.0.0.1",
    FDE_API_PORT: "0",
    FDE_DATABASE_URL: requiredEnvironment("FDE_DATABASE_URL"),
    FDE_REDIS_URL: unavailableRedisUrl,
    FDE_JWT_SECRET: requiredEnvironment("FDE_JWT_SECRET"),
  }
}

function assertDedicatedTestDatabase(databaseUrl: string): void {
  const parsed = new URL(databaseUrl.replace("mysql+pymysql://", "http://"))
  if (parsed.pathname !== "/fde_workbench_test") {
    throw new Error("Electron smoke tests require the dedicated fde_workbench_test database.")
  }
}

async function waitForApi(): Promise<void> {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (server?.exitCode !== null) {
      throw new Error("The E2E Flask server exited before becoming ready.")
    }
    try {
      const response = await fetch(`${apiUrl}/api/v1/health/live`)
      if (response.ok) return
    } catch {
      // The server is still starting.
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 100))
  }
  throw new Error("The E2E Flask server did not become ready on its assigned loopback port.")
}

async function postJson(path: string, body: Record<string, unknown>) {
  return fetchJson(`${apiUrl}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

async function fetchJson(url: string, init?: RequestInit) {
  const response = await fetch(url, init)
  return {
    response,
    payload: await response.json() as any,
  }
}
