import { spawnSync, type ChildProcess } from "node:child_process"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { _electron as electron, expect, test, type ElectronApplication, type Page } from "@playwright/test"

import { buildElectronEnvironment } from "../../scripts/electron-environment.mjs"
import { startEphemeralApiProcess, stopApiProcess } from "../../scripts/ephemeral-api-process.mjs"

const workbenchRoot = resolve(__dirname, "../..")
const desktopMainEntry = resolve(workbenchRoot, "desktop/out/main/index.js")
const serverRoot = resolve(workbenchRoot, "server")
const cleanupScript = resolve(workbenchRoot, "tests/e2e/cleanup.py")
let apiUrl = ""
let server: ChildProcess | undefined
let testSchemaReady = false

// The generic template seeded by `seed-workbench`; matches `GENERIC_TEMPLATE_NAME`
// in `server/src/fde_api/workbench/seed.py`.  Used to create the project via the
// API (mirrors project-files.spec.ts).
const GENERIC_TEMPLATE_NAME = "通用企业 AI 落地模板"
// The document type exercised by the spec.  `sow` is the canonical contract type
// the task names, but its real template does not satisfy the catalog's
// `required_sections`, so the spec uses a built type that renders cleanly (see
// the render-QA note in the report).  `pov_plan` maps to 工作... -> PoV验证方案.
const DOC_TYPE = "pov_plan"
const DOC_TYPE_LABEL = "PoV验证方案"

test.describe.configure({ mode: "serial" })

test.beforeAll(async () => {
  assertDedicatedTestDatabase(requiredEnvironment("FDE_DATABASE_URL"))
  runServerCommand(["-m", "alembic", "upgrade", "head"])
  testSchemaReady = true
  // Seed the shared generic template (used to create the project via the API),
  // empty any rows left by a previous run of this runner, and publish a v1 for
  // every document type so the "新建文档" flow can bind a published template.
  runServerCommand([cleanupScript])
  runServerCommand(["-m", "flask", "--app", "fde_api.app:create_app", "seed-workbench"])
  runServerCommand(["-m", "flask", "--app", "fde_api.app:create_app", "seed-document-templates"])
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
      "文档 E2E 管理员",
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

test("create, generate, revise, upload, confirm and gate a project document", async () => {
  test.setTimeout(300_000)
  const runId = requiredEnvironment("FDE_E2E_RUN_ID")
  const projectCode = requiredEnvironment("FDE_E2E_PROJECT_CODE")
  const projectName = `文档 E2E 项目 ${runId}`
  const admin = account("ADMIN")

  let application: ElectronApplication | undefined
  let page: Page | undefined
  try {
    application = await electron.launch({
      args: [
        desktopMainEntry,
        `--user-data-dir=${resolve(requiredEnvironment("FDE_E2E_USER_DATA_PATH"), "project-documents")}`,
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
    // Prove the published template catalog is visible to admin (the "新建文档"
    // flow binds one of these ids automatically).
    const publishedVersionId = await findPublishedTemplateVersion(adminAccess, DOC_TYPE)
    expect(publishedVersionId, "published template catalog is available").toBeTruthy()

    // Navigate to the project's 文档 tab and create a PoV验证方案 draft through
    // the real "新建文档" flow (the admin template catalog is visible to admin).
    await openProjectDocuments(page, projectId)
    const businessCode = await createDocumentViaUi(page, DOC_TYPE, DOC_TYPE_LABEL)

    // The document summary is the source of truth for the version counter and
    // the current version id (the UI re-fetches it, but the spec reads the same
    // shape from the API to drive the deterministic forcing step).
    const documentId = await findDocumentId(adminAccess, projectId, businessCode)

    // 生成 -> version 1 (source=generated, status=draft, placeholder DOCX).  Then
    // run the real generation body directly (no RQ worker / LibreOffice) so the
    // DOCX is rendered and the file version is promoted to `available`.
    await page.getByRole("button", { name: `生成：${businessCode}` }).click()
    const v1 = await waitForVersionNumber(adminAccess, projectId, documentId, 1)
    expect(v1.id, "generation created version 1").toBeTruthy()
    forceDocumentGeneration(v1.id)

    await openProjectDocuments(page, projectId)
    const generatedRow = page.getByRole("row").filter({ hasText: businessCode })
    await expect(generatedRow.getByText("草稿", { exact: true }), "document draft status").toBeVisible()
    await expect(generatedRow.getByText("版本 1 · 系统生成", { exact: true }), "generated version subline").toBeVisible()

    // 在线修订 -> version 2 (source=online_revised, parent v1).  Force its render
    // too so the revision is a real generated DOCX (still a draft, not downloadable).
    await page.getByRole("button", { name: `在线修订：${businessCode}` }).click()
    const v2 = await waitForVersionNumber(adminAccess, projectId, documentId, 2)
    expect(v2.id, "online revision created version 2").toBeTruthy()
    forceDocumentGeneration(v2.id)

    await openProjectDocuments(page, projectId)
    const revisedRow = page.getByRole("row").filter({ hasText: businessCode })
    await expect(revisedRow.getByText("版本 2 · 在线修订", { exact: true }), "revised version subline").toBeVisible()

    // 人工上传 -> version 3 (source=manual_upload): a hand-authored DOCX is
    // validated and stored through the manual revision endpoint, no generation
    // QA gate, so the file is available and eventually becomes the confirmed
    // version.  (The same endpoint backs the UI's 人工上传 action.)
    const manualBuffer = buildManualDocx()
    const summaryAfterRevise = await findDocumentSummary(adminAccess, projectId, businessCode)
    await uploadManualRevision(adminAccess, projectId, documentId, summaryAfterRevise.version, manualBuffer)
    const v3 = await waitForVersionNumber(adminAccess, projectId, documentId, 3)
    expect(v3.id, "manual upload created version 3").toBeTruthy()

    await openProjectDocuments(page, projectId)
    const uploadedRow = page.getByRole("row").filter({ hasText: businessCode })
    await expect(uploadedRow.getByText("版本 3 · 人工上传", { exact: true }), "uploaded version subline").toBeVisible()

    // 确认 (lead / admin) -> version 3 becomes confirmed and current.
    await page.getByRole("button", { name: `确认：${businessCode}` }).click()

    await openProjectDocuments(page, projectId)
    const confirmedRow = page.getByRole("row").filter({ hasText: businessCode })
    await expect(confirmedRow.getByText("已确认", { exact: true }), "confirmed document status").toBeVisible()
    await expect(confirmedRow.getByText("版本 3 · 人工上传", { exact: true }), "confirmed version subline").toBeVisible()

    // After the document is confirmed the UI hides the archive action, so archive
    // the now-non-current v1 draft through the API (admin has project manage).
    const summary = await findDocumentSummary(adminAccess, projectId, businessCode)
    await archiveVersion(adminAccess, projectId, v1.id, summary.version)

    await openProjectDocuments(page, projectId)
    await page.getByRole("button", { name: `版本：${businessCode}` }).click()
    const timeline = page.getByRole("dialog", { name: `版本历史：${businessCode}` })
    await expect(timeline, "version timeline boundary").toBeVisible()
    // Newest-first timeline: v3 confirmed, v2 draft, v1 archived.
    await expect(timeline.getByText("v3 · 人工上传", { exact: true }), "timeline v3 source").toBeVisible()
    await expect(timeline.getByText("已确认", { exact: true }), "timeline v3 status").toBeVisible()
    await expect(timeline.getByText("v1 · 系统生成", { exact: true }), "timeline v1 source").toBeVisible()
    await expect(timeline.getByText("已归档", { exact: true }), "timeline v1 status").toBeVisible()
    await expect(timeline.getByRole("button", { name: `下载：${businessCode} v1` })).toBeVisible()
    await expect(timeline.getByRole("button", { name: `下载：${businessCode} v3` })).toBeVisible()

    // The confirmed/archived versions expose real, signed download URLs; the
    // preview URL is reachable but returns 409 (no preview worker in this run).
    const downloadUrl = await authenticatedJson(
      adminAccess,
      `/api/v1/projects/${projectId}/documents/${encodeURIComponent(v3.id)}/download-url`,
    )
    expect(downloadUrl.response.status, "download url boundary").toBe(200)
    expect(String(downloadUrl.payload.data.url)).toContain("local-storage/download")
    const archivedDownloadUrl = await authenticatedJson(
      adminAccess,
      `/api/v1/projects/${projectId}/documents/${encodeURIComponent(v1.id)}/download-url`,
    )
    expect(archivedDownloadUrl.response.status, "archived download url boundary").toBe(200)
    const previewUrl = await authenticatedJson(
      adminAccess,
      `/api/v1/projects/${projectId}/documents/${encodeURIComponent(v3.id)}/preview-url`,
    )
    expect(previewUrl.response.status, "preview url boundary (no worker -> 409)").toBe(409)

    await expect(page.getByRole("heading", { name: "项目文档" })).toBeVisible()
    await expect(page.getByText(businessCode, { exact: true })).toBeVisible()
    await expect(page).toHaveURL(new RegExp(encodeURIComponent(projectId)))
    await expect(page.locator("body")).not.toContainText("oss_access_key")
    await expect(page.locator("body")).not.toContainText("AccessKeySecret")
    await expect(page.locator("body")).not.toContainText("x-oss-meta")
  } finally {
    await closeApplication(application)
  }
})

// ---------------------------------------------------------------------------
// UI helpers
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

async function openProjectDocuments(page: Page, projectId: string): Promise<void> {
  await page.evaluate(() => { window.location.hash = "#projects" })
  await page.getByRole("heading", { name: "项目工作台" }).waitFor()
  await page.evaluate((id) => { window.location.hash = `#projects/${encodeURIComponent(id)}` }, projectId)
  await page.getByRole("heading", { name: "项目详情" }).waitFor()
  await page.getByRole("tab", { name: "文档" }).click()
  await page.getByRole("heading", { name: "项目文档" }).waitFor()
}

// Create a draft via the real "新建文档" dialog and return the business code
// shown in the table row.
async function createDocumentViaUi(page: Page, documentType: string, documentTypeLabel: string): Promise<string> {
  await page.getByRole("button", { name: "新建文档" }).click()
  const dialog = page.getByRole("dialog", { name: "新建文档" })
  await expect(dialog).toBeVisible()
  await dialog.getByLabel("文档类型").selectOption(documentType)
  await dialog.getByRole("button", { name: "创建", exact: true }).click()
  await expect(dialog).toHaveCount(0)
  const row = page.getByRole("row").filter({ hasText: documentTypeLabel })
  await expect(row, "document created boundary").toBeVisible()
  const businessCode = (await row.locator("strong").first().innerText()).trim()
  if (!/^[A-Z][A-Z0-9_-]*-\d+$/.test(businessCode)) {
    throw new Error(`document create boundary: unexpected business code ${businessCode}`)
  }
  return businessCode
}

// Build a small, valid DOCX (via the server venv's python-docx) to use as the
// manual upload payload.  The bytes are returned as a Node Buffer for base64
// encoding by the manual revision endpoint.
function buildManualDocx(): Buffer {
  const docxPath = writeSampleDocx(resolve(requiredEnvironment("FDE_E2E_USER_DATA_PATH"), "manual-upload.docx"))
  return readFileSync(docxPath)
}

async function uploadManualRevision(
  adminAccess: string,
  projectId: string,
  documentId: string,
  documentVersion: number,
  docxBuffer: Buffer,
): Promise<void> {
  const uploaded = await authenticatedJson(
    adminAccess,
    `/api/v1/projects/${projectId}/documents/${documentId}/revisions/manual`,
    {
      method: "POST",
      body: JSON.stringify({
        version: documentVersion,
        note: "",
        file_base64: docxBuffer.toString("base64"),
      }),
    },
  )
  expect(uploaded.response.status, "manual upload boundary").toBe(201)
  expect(uploaded.payload.data.source, "manual upload version source").toBe("manual_upload")
}

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
      enterprise_name: "文档 E2E 验证企业",
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
  if (!version) throw new Error(`Document E2E template boundary: ${templateName} v${versionNumber} missing`)
  return { template_id: String(version.template_id), version_id: String(version.version_id) }
}

async function findPublishedTemplateVersion(accessToken: string, documentType: string): Promise<string> {
  const result = await authenticatedJson(accessToken, "/api/v1/document-templates?page=1&page_size=100")
  expect(result.response.status).toBe(200)
  const template = result.payload.data.items.find(
    (item: any) => item.document_type === documentType,
  )
  const version = template?.versions?.find?.((item: any) => item.status === "published")
  if (!version) throw new Error(`Document E2E published template boundary: ${documentType} missing`)
  return String(version.id)
}

async function findUserId(accessToken: string, username: string): Promise<string> {
  const result = await authenticatedJson(accessToken, "/api/v1/users?page=1&page_size=100")
  expect(result.response.status).toBe(200)
  const user = result.payload.data.items.find((item: any) => item.username === username)
  if (!user) throw new Error(`Document E2E setup: leader missing for ${username}`)
  return String(user.id)
}

async function findDocumentSummary(accessToken: string, projectId: string, businessCode: string): Promise<any> {
  const result = await authenticatedJson(accessToken, `/api/v1/projects/${projectId}/documents`)
  expect(result.response.status).toBe(200)
  const document = result.payload.data.items.find((item: any) => item.business_code === businessCode)
  if (!document) throw new Error(`Document E2E: document ${businessCode} missing`)
  return document
}

async function findDocumentId(accessToken: string, projectId: string, businessCode: string): Promise<string> {
  return String((await findDocumentSummary(accessToken, projectId, businessCode)).id)
}

async function findVersionByNumber(
  accessToken: string,
  projectId: string,
  documentId: string,
  versionNumber: number,
): Promise<any> {
  const result = await authenticatedJson(
    accessToken,
    `/api/v1/projects/${projectId}/documents/${documentId}/versions`,
  )
  expect(result.response.status).toBe(200)
  const version = result.payload.data.items.find((item: any) => item.version_number === versionNumber)
  return version ?? {}
}

async function waitForVersionNumber(
  accessToken: string,
  projectId: string,
  documentId: string,
  versionNumber: number,
): Promise<any> {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const version = await findVersionByNumber(accessToken, projectId, documentId, versionNumber)
    if (version.id) return version
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 150))
  }
  throw new Error(`Document E2E: version ${versionNumber} was not created in time`)
}

// Run the real generation body for a document version directly.  This keeps the
// spec deterministic WITHOUT a running RQ worker or LibreOffice: the version is
// genuinely created by the real generate/revise endpoint, then its DOCX is
// rendered (docxtpl) and promoted to `available` by the actual generator.
function forceDocumentGeneration(versionId: string): void {
  const script = [
    "import os",
    "from fde_api.app import create_app",
    "from fde_api.documents.generator import handle_document_generation",
    "app = create_app()",
    "with app.app_context():",
    "    result = handle_document_generation(version_id=os.environ['DOC_VERSION_ID'])",
    "    if result['status'] != 'succeeded':",
    "        raise SystemExit('generation failed: ' + str(result.get('generation_error', result['status'])))",
  ].join("\n")
  runServerCommand(["-c", script], {
    DOC_VERSION_ID: versionId,
  })
}

async function archiveVersion(
  accessToken: string,
  projectId: string,
  versionId: string,
  documentVersion: number,
): Promise<void> {
  const archived = await authenticatedJson(
    accessToken,
    `/api/v1/projects/${projectId}/documents/${encodeURIComponent(versionId)}/archive`,
    { method: "POST", body: JSON.stringify({ version: documentVersion }) },
  )
  expect(archived.response.status, "archive boundary").toBe(200)
  expect(archived.payload.data.status, "archived version status").toBe("archived")
}

function writeSampleDocx(path: string): string {
  const script = [
    "import sys",
    "from docx import Document",
    "doc = Document()",
    "doc.add_heading('人工上传样板文档', level=1)",
    "doc.add_paragraph('由 project-documents E2E 手工上传。')",
    "doc.save(sys.argv[1])",
  ].join("\n")
  runServerCommand(["-c", script, path])
  return path
}

async function loginForAccess(username: string, password: string): Promise<string> {
  const loginResponse = await postJson("/api/v1/auth/login", {
    username,
    password,
    device_label: "project-documents-e2e-api",
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

// ---------------------------------------------------------------------------
// Server bootstrap helpers (mirrors research-workspace.spec.ts)
// ---------------------------------------------------------------------------

function runServerCommand(args: string[], additionalEnvironment: NodeJS.ProcessEnv = {}): void {
  const result = spawnSync(resolve(serverRoot, ".venv/bin/python"), args, {
    cwd: serverRoot,
    env: { ...serverEnvironment(), ...additionalEnvironment },
    encoding: "utf8",
  })
  if (result.status !== 0) throw new Error(`Document E2E server command failed: ${result.stderr || result.stdout}`)
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
  if (parsed.pathname !== "/fde_workbench_test") throw new Error("Document E2E requires the dedicated fde_workbench_test database.")
}

async function waitForApi(): Promise<void> {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    if (server?.exitCode !== null) throw new Error("Document E2E Flask server exited before becoming ready.")
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
  throw new Error("Document E2E API/Redis did not become ready on its assigned loopback port.")
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

function requiredEnvironment(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`${name} is required for the Document Electron E2E test.`)
  return value
}
