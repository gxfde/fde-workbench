import { spawnSync, type ChildProcess } from "node:child_process"
import { _electron as electron, expect, test, type ElectronApplication, type Page } from "@playwright/test"
import { resolve } from "node:path"

import { buildElectronEnvironment } from "../../scripts/electron-environment.mjs"
import { startEphemeralApiProcess, stopApiProcess } from "../../scripts/ephemeral-api-process.mjs"

const workbenchRoot = resolve(__dirname, "../..")
const desktopMainEntry = resolve(workbenchRoot, "desktop/out/main/index.js")
const serverRoot = resolve(workbenchRoot, "server")
const cleanupScript = resolve(workbenchRoot, "tests/e2e/cleanup.py")
let apiUrl = ""
let server: ChildProcess | undefined
let testSchemaReady = false

// A small text file that the uploader promotes through the real signing/complete
// UI flow, and a second file we force into the "quarantined" state to prove a
// non-available version exposes no download/preview actions.
const FILE_NAME = "附件.txt"
const QUARANTINED_NAME = "隔离.txt"
const TEXT_MIME = "text/plain"
const TEXT_CONTENT = "hello"
// The generic template seeded by `seed-workbench`; matches `GENERIC_TEMPLATE_NAME`
// in `server/src/fde_api/workbench/seed.py`.
const GENERIC_TEMPLATE_NAME = "通用企业 AI 落地模板"

test.describe.configure({ mode: "serial" })

test.beforeAll(async () => {
  assertDedicatedTestDatabase(requiredEnvironment("FDE_DATABASE_URL"))
  runServerCommand(["-m", "alembic", "upgrade", "head"])
  testSchemaReady = true
  // Seed the shared generic template (used to create the project via the API),
  // then empty any rows left by a previous run of this runner.
  runServerCommand([cleanupScript])
  runServerCommand(["-m", "flask", "--app", "fde_api.app:create_app", "seed-workbench"])
  runServerCommand(
    [
      "-m",
      "flask",
      "--app",
      "fde_api.app:create_app",
      "create-admin",
      "--username",
      requiredEnvironment("FDE_E2E_ADMIN_USERNAME"),
      "--display-name",
      "文件 E2E 管理员",
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
  if (testSchemaReady) runServerCommand([cleanupScript])
})

test("upload a project file via the real UI flow and gate its download/preview actions on availability", async () => {
  test.setTimeout(300_000)
  const runId = requiredEnvironment("FDE_E2E_RUN_ID")
  const projectCode = requiredEnvironment("FDE_E2E_PROJECT_CODE")
  const projectName = `文件 E2E 项目 ${runId}`
  const admin = account("ADMIN")

  let application: ElectronApplication | undefined
  let page: Page | undefined
  try {
    application = await electron.launch({
      args: [
        desktopMainEntry,
        `--user-data-dir=${resolve(requiredEnvironment("FDE_E2E_USER_DATA_PATH"), "project-files")}`,
      ],
      env: buildElectronEnvironment(process.env, apiUrl),
    })
    page = await application.firstWindow()
    page.setDefaultTimeout(15_000)

    await loginAndChangePassword(page, admin)

    const adminAccess = await loginForAccess(admin.username, admin.password)
    const projectId = await createProjectViaApi(adminAccess, {
      projectName,
      projectCode,
      leaderUserId: await findUserId(adminAccess, admin.username),
    })

    // Navigate to the project's 文件 tab and upload a real text file.
    await openProjectFiles(page, projectId)
    await page.getByLabel("选择文件").setInputFiles({
      name: FILE_NAME,
      mimeType: TEXT_MIME,
      buffer: Buffer.from(TEXT_CONTENT, "utf8"),
    })

    // The real UI upload runs through session creation -> signed part PUT ->
    // completion, which creates an immutable ProjectFileVersion.  Without a live
    // ClamAV worker this version stays "uploading"/"pending", so the *only*
    // reliably true assertions here are that the upload completed and the file
    // row is listed.  (We then force the version to "available" deterministically
    // below so we can assert its download/preview actions.)
    await expect(page.getByRole("row").filter({ hasText: FILE_NAME }), "file listed boundary").toBeVisible()

    // Read the newly created version id, then force it to "available" through a
    // test-only server command so download/preview are exposed WITHOUT a real
    // ClamAV scan.  The project file list still polls while a version is
    // uploading/quarantined, but we re-open the tab for a deterministic reload.
    const versionId = await findCurrentVersionId(adminAccess, projectId, FILE_NAME)
    expect(versionId, "upload finished and produced a version").toBeTruthy()
    forceFileVersionStatus(versionId, "available", "clean")

    await openProjectFiles(page, projectId)
    const availableRow = page.getByRole("row").filter({ hasText: FILE_NAME })
    await expect(availableRow.getByText("可下载", { exact: true }), "available status boundary").toBeVisible()
    await expect(availableRow.getByRole("button", { name: `下载：${FILE_NAME}` })).toBeVisible()
    await expect(availableRow.getByRole("button", { name: `预览：${FILE_NAME}` })).toBeVisible()

    // The signed download URL must be handed out for the available version.
    const downloadUrl = await authenticatedJson(
      adminAccess,
      `/api/v1/projects/${projectId}/files/${encodeURIComponent(versionId)}/download-url`,
    )
    expect(downloadUrl.response.status, "download url boundary").toBe(200)
    expect(String(downloadUrl.payload.data.url)).toContain("projects/")

    // Upload a second file and force it into the quarantined state: it must NOT
    // expose download/preview actions even though it is listed.
    await page.getByLabel("选择文件").setInputFiles({
      name: QUARANTINED_NAME,
      mimeType: TEXT_MIME,
      buffer: Buffer.from(TEXT_CONTENT, "utf8"),
    })
    const quarantinedRow = page.getByRole("row").filter({ hasText: QUARANTINED_NAME })
    await expect(quarantinedRow, "second file listed boundary").toBeVisible()
    const quarantinedVersionId = await findCurrentVersionId(adminAccess, projectId, QUARANTINED_NAME)
    expect(quarantinedVersionId, "second upload produced a version").toBeTruthy()
    forceFileVersionStatus(quarantinedVersionId, "quarantined", "error")

    await openProjectFiles(page, projectId)
    const blockedRow = page.getByRole("row").filter({ hasText: QUARANTINED_NAME })
    await expect(blockedRow.getByText("等待安全扫描", { exact: true }), "quarantined status boundary").toBeVisible()
    await expect(blockedRow.getByRole("button", { name: `下载：${QUARANTINED_NAME}` })).toHaveCount(0)
    await expect(blockedRow.getByRole("button", { name: `预览：${QUARANTINED_NAME}` })).toHaveCount(0)

    // The page reflects only safe status labels + generated ids and no storage /
    // credential material.
    await expect(page.getByRole("heading", { name: "项目文件" })).toBeVisible()
    await expect(page.getByText(FILE_NAME, { exact: true })).toBeVisible()
    await expect(page.getByText(QUARANTINED_NAME, { exact: true })).toBeVisible()
    await expect(page).toHaveURL(new RegExp(encodeURIComponent(projectId)))
    await expect(page.locator("body")).not.toContainText("oss_access_key")
    await expect(page.locator("body")).not.toContainText("x-oss-meta")
    await expect(page.locator("body")).not.toContainText("AccessKeySecret")
  } finally {
    await closeApplication(application)
  }
})

// ---------------------------------------------------------------------------
// API / server helpers
// ---------------------------------------------------------------------------

async function createProjectViaApi(
  accessToken: string,
  input: { projectName: string; projectCode: string; leaderUserId: string },
): Promise<string> {
  const templateVersion = await findTemplateVersion(accessToken, GENERIC_TEMPLATE_NAME, 1)
  const created = await authenticatedJson(accessToken, "/api/v1/projects", {
    method: "POST",
    body: JSON.stringify({
      name: input.projectName,
      enterprise_name: "文件 E2E 验证企业",
      planned_start_date: "2026-10-01",
      template_version_id: templateVersion.version_id,
      leader_user_id: input.leaderUserId,
      module_keys: ["pre_diagnosis"],
      project_code: input.projectCode,
    }),
  })
  expect(created.response.status, "project creation boundary").toBe(201)
  return String(created.payload.data.id)
}

async function findTemplateVersion(
  accessToken: string,
  templateName: string,
  versionNumber: number,
): Promise<{ template_id: string; version_id: string }> {
  const result = await authenticatedJson(accessToken, "/api/v1/industry-templates?page=1&page_size=100")
  expect(result.response.status).toBe(200)
  const version = result.payload.data.items.find(
    (item: any) => item.template_name === templateName && item.version_number === versionNumber,
  )
  if (!version) throw new Error(`File E2E template boundary: ${templateName} v${versionNumber} missing`)
  return { template_id: String(version.template_id), version_id: String(version.version_id) }
}

async function findUserId(accessToken: string, username: string): Promise<string> {
  const result = await authenticatedJson(accessToken, "/api/v1/users?page=1&page_size=100")
  expect(result.response.status).toBe(200)
  const user = result.payload.data.items.find((item: any) => item.username === username)
  if (!user) throw new Error(`File E2E setup: leader missing for ${username}`)
  return String(user.id)
}

async function findCurrentVersionId(
  accessToken: string,
  projectId: string,
  displayName: string,
): Promise<string> {
  const result = await authenticatedJson(accessToken, `/api/v1/projects/${projectId}/files`)
  expect(result.response.status).toBe(200)
  const file = result.payload.data.items.find((item: any) => item.display_name === displayName)
  const versionId = file?.current_version?.id
  if (!versionId) throw new Error(`File E2E: current version missing for ${displayName}`)
  return String(versionId)
}

// Force a file version into a known status through a test-only server command.
// This keeps the spec deterministic WITHOUT a real ClamAV worker: the version is
// still genuinely created by the real UI upload, then only its status/scan_status
// columns are advanced so download/preview action gating can be asserted.
function forceFileVersionStatus(versionId: string, status: string, scanStatus: string): void {
  const script = [
    "import os",
    "from sqlalchemy import create_engine, text",
    "engine = create_engine(os.environ['FDE_DATABASE_URL'])",
    "with engine.begin() as conn:",
    "    conn.execute(",
    "        text('UPDATE project_file_versions SET status = :status, scan_status = :scan_status WHERE id = :id'),",
    "        {'status': os.environ['FORCE_STATUS'], 'scan_status': os.environ['FORCE_SCAN_STATUS'], 'id': os.environ['FORCE_VERSION_ID']},",
    "    )",
    "engine.dispose()",
  ].join("\n")
  runServerCommand(["-c", script], {
    FORCE_VERSION_ID: versionId,
    FORCE_STATUS: status,
    FORCE_SCAN_STATUS: scanStatus,
  })
}

async function loginForAccess(username: string, password: string): Promise<string> {
  const loginResponse = await postJson("/api/v1/auth/login", {
    username,
    password,
    device_label: "project-files-e2e-api",
  })
  expect(loginResponse.response.status).toBe(200)
  return String(loginResponse.payload.data.access_token)
}

function authenticatedJson(accessToken: string, path: string, init: RequestInit = {}) {
  return fetchJson(`${apiUrl}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json", ...init.headers },
  })
}

// ---------------------------------------------------------------------------
// UI helpers (mirrors research-workspace.spec.ts)
// ---------------------------------------------------------------------------

interface E2EAccount { username: string; initialPassword: string; password: string }

function account(prefix: "ADMIN" | "LEAD" | "ENGINEER" | "UNRELATED_ENGINEER" | "VIEWER"): E2EAccount {
  return {
    username: requiredEnvironment(`FDE_E2E_${prefix}_USERNAME`),
    initialPassword: requiredEnvironment(`FDE_E2E_${prefix}_PASSWORD`),
    password: requiredEnvironment(`FDE_E2E_${prefix}_NEW_PASSWORD`),
  }
}

async function loginAndChangePassword(page: Page, user: E2EAccount): Promise<void> {
  await login(page, user.username, user.initialPassword, "修改初始密码")
  await page.getByLabel("当前密码").fill(user.initialPassword)
  await page.getByLabel("新密码", { exact: true }).fill(user.password)
  await page.getByLabel("确认新密码").fill(user.password)
  await page.getByRole("button", { name: "保存新密码" }).click()
  await waitForDestinationOrSafeError(page, "项目工作台", "password change")
}

async function login(page: Page, username: string, password: string, destination = "项目工作台"): Promise<void> {
  await page.evaluate(() => { window.location.hash = "#projects" })
  await page.getByLabel("用户名").fill(username)
  await page.getByLabel("密码").fill(password)
  await page.getByRole("button", { name: "登录" }).click()
  await waitForDestinationOrSafeError(page, destination, "login")
}

async function waitForDestinationOrSafeError(page: Page, heading: string, operation: string): Promise<void> {
  const destination = page.getByRole("heading", { name: heading })
  const alert = page.getByRole("alert")
  try {
    await destination.waitFor({ timeout: 12_000 })
  } catch {
    if (await alert.isVisible()) throw new Error(`${operation} failed in UI: ${(await alert.textContent())?.trim() || "unknown error"}`)
    throw new Error(`${operation} did not reach ${heading}`)
  }
}

async function openProjectFiles(page: Page, projectId: string): Promise<void> {
  await page.evaluate(() => { window.location.hash = "#projects" })
  await page.getByRole("heading", { name: "项目工作台" }).waitFor()
  await page.evaluate((id) => { window.location.hash = `#projects/${encodeURIComponent(id)}` }, projectId)
  await page.getByRole("heading", { name: "项目详情" }).waitFor()
  await page.getByRole("tab", { name: "文件" }).click()
  await page.getByRole("heading", { name: "项目文件" }).waitFor()
}

async function closeApplication(application: ElectronApplication | undefined): Promise<void> {
  if (!application) return
  let process: ReturnType<ElectronApplication["process"]>
  try {
    process = application.process()
  } catch {
    return
  }
  if (process.exitCode !== null) return
  const exit = new Promise<void>((resolveExit) => process.once("exit", () => resolveExit()))
  process.kill("SIGKILL")
  await exit
}

// ---------------------------------------------------------------------------
// Server bootstrap helpers (mirrors research-workspace.spec.ts)
// ---------------------------------------------------------------------------

function runServerCommand(args: string[], additionalEnvironment: NodeJS.ProcessEnv = {}): void {
  const result = spawnSync(resolve(serverRoot, ".venv/bin/python"), args, {
    cwd: serverRoot,
    env: { ...serverEnvironment(), ...additionalEnvironment },
    encoding: "utf8",
  })
  if (result.status !== 0) throw new Error(`File E2E server command failed: ${result.stderr || result.stdout}`)
}

function serverEnvironment(): NodeJS.ProcessEnv {
  return {
    ...process.env,
    FDE_ENV: "test",
    FDE_API_HOST: "127.0.0.1",
    FDE_API_PORT: "0",
    FDE_DATABASE_URL: requiredEnvironment("FDE_DATABASE_URL"),
    FDE_REDIS_URL: process.env.FDE_E2E_REDIS_URL ?? "redis://127.0.0.1:6379/15",
    FDE_JWT_SECRET: requiredEnvironment("FDE_JWT_SECRET"),
  }
}

function assertDedicatedTestDatabase(databaseUrl: string): void {
  const parsed = new URL(databaseUrl.replace("mysql+pymysql://", "http://"))
  if (parsed.pathname !== "/fde_workbench_test") throw new Error("File E2E requires the dedicated fde_workbench_test database.")
}

async function waitForApi(): Promise<void> {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    if (server?.exitCode !== null) throw new Error("File E2E Flask server exited before becoming ready.")
    try {
      const response = await fetch(`${apiUrl}/api/v1/health/ready`)
      if (response.ok) {
        const payload = await response.json() as any
        if (payload.data?.mysql === "ok" && payload.data?.redis === "ok") return
      }
    } catch {
      // Server or Redis is still starting.
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 100))
  }
  throw new Error("File E2E API/Redis did not become ready on its assigned loopback port.")
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
  return { response, payload: await response.json() as any }
}

function requiredEnvironment(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`${name} is required for the File Electron E2E test.`)
  return value
}
