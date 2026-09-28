import { spawnSync, type ChildProcess } from "node:child_process"
import { _electron as electron, expect, test, type ElectronApplication, type Page } from "@playwright/test"
import { resolve } from "node:path"

import { buildElectronEnvironment } from "../../scripts/electron-environment.mjs"
import { startEphemeralApiProcess, stopApiProcess } from "../../scripts/ephemeral-api-process.mjs"
import { findUnavailableRedisPort } from "../../scripts/unavailable-redis-port.mjs"

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
      "阶段二管理员",
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
  if (testSchemaReady) runServerCommand([resolve(workbenchRoot, "tests/e2e/cleanup.py")])
})

test("admin publishes a template, creates a project, and engineer updates an assigned task", async () => {
  test.setTimeout(120_000)
  const adminUsername = requiredEnvironment("FDE_E2E_ADMIN_USERNAME")
  const adminInitialPassword = requiredEnvironment("FDE_E2E_ADMIN_PASSWORD")
  const adminPassword = requiredEnvironment("FDE_E2E_ADMIN_NEW_PASSWORD")
  const engineerUsername = requiredEnvironment("FDE_E2E_ENGINEER_USERNAME")
  const engineerInitialPassword = requiredEnvironment("FDE_E2E_ENGINEER_PASSWORD")
  const engineerPassword = requiredEnvironment("FDE_E2E_ENGINEER_NEW_PASSWORD")
  const unrelatedUsername = requiredEnvironment("FDE_E2E_UNRELATED_ENGINEER_USERNAME")
  const unrelatedInitialPassword = requiredEnvironment("FDE_E2E_UNRELATED_ENGINEER_PASSWORD")
  const unrelatedPassword = requiredEnvironment("FDE_E2E_UNRELATED_ENGINEER_NEW_PASSWORD")
  const viewerUsername = requiredEnvironment("FDE_E2E_VIEWER_USERNAME")
  const viewerInitialPassword = requiredEnvironment("FDE_E2E_VIEWER_PASSWORD")
  const viewerPassword = requiredEnvironment("FDE_E2E_VIEWER_NEW_PASSWORD")
  const runId = requiredEnvironment("FDE_E2E_RUN_ID")
  const projectCode = requiredEnvironment("FDE_E2E_PROJECT_CODE")
  const templateName = `phase2.${runId} 制造业 AI 落地`

  let application: ElectronApplication | undefined
  try {
    application = await electron.launch({
      args: [
        desktopMainEntry,
        `--user-data-dir=${resolve(requiredEnvironment("FDE_E2E_USER_DATA_PATH"), "project-workbench")}`,
      ],
      env: buildElectronEnvironment(process.env, apiUrl),
    })
    const page = await application.firstWindow()

    await loginAndChangePassword(page, adminUsername, adminInitialPassword, adminPassword)
    await page.getByRole("link", { name: "用户管理" }).click()
    await page.getByRole("heading", { name: "用户管理" }).waitFor()
    await createUser(page, engineerUsername, "阶段二工程师", "fde_engineer", engineerInitialPassword)
    await createUser(page, unrelatedUsername, "无关工程师", "fde_engineer", unrelatedInitialPassword)
    await createUser(page, viewerUsername, "阶段二查看者", "viewer", viewerInitialPassword)

    await logout(page)
    await loginAndChangePassword(page, engineerUsername, engineerInitialPassword, engineerPassword)
    await logout(page)
    await loginAndChangePassword(page, unrelatedUsername, unrelatedInitialPassword, unrelatedPassword)
    await logout(page)
    await loginAndChangePassword(page, viewerUsername, viewerInitialPassword, viewerPassword)
    await logout(page)
    await login(page, adminUsername, adminPassword)

    await publishTemplate(page, templateName)
    const projectId = await createProject(page, templateName, projectCode)
    await addProjectMember(page, engineerUsername, "member")
    await addProjectMember(page, viewerUsername, "viewer")
    await page.getByRole("tab", { name: "任务" }).click()
    await page.getByRole("button", { name: "更新任务：准备数据" }).click()
    await page.getByLabel("负责人", { exact: true }).selectOption({ label: "阶段二工程师" })
    await page.getByRole("button", { name: "保存任务" }).click()
    await expect(page.getByRole("row").filter({ hasText: "准备数据" })).toContainText("阶段二工程师")

    const adminSession = await loginForSession(adminUsername, adminPassword)
    const engineerSession = await loginForSession(engineerUsername, engineerPassword)
    const adminAccess = String(adminSession.payload.data.access_token)
    const engineerId = String(engineerSession.payload.data.user.id)
    const assignedTasks = await fetchJson(`${apiUrl}/api/v1/projects/${projectId}/tasks`, {
      headers: { Authorization: `Bearer ${adminAccess}` },
    })
    expect(assignedTasks.response.status).toBe(200)
    const assignedPreparedTask = assignedTasks.payload.data.items.find(
      (item: { name: string }) => item.name === "准备数据",
    )
    expect(assignedPreparedTask.assignee_user_id).toBe(engineerId)

    await logout(page)
    await login(page, engineerUsername, engineerPassword)
    await page.getByRole("link", { name: "查看星河 PoV" }).click()
    await page.getByRole("tab", { name: "任务" }).click()
    await page.getByRole("button", { name: "更新任务：准备数据" }).click()
    await page.getByLabel("状态", { exact: true }).selectOption("in_progress")
    await page.getByLabel("进度", { exact: true }).fill("40")
    await page.getByRole("button", { name: "保存任务" }).click()
    const taskRow = page.getByRole("row").filter({ hasText: "准备数据" })
    await expect(taskRow).toContainText("40%")

    const tasks = await fetchJson(`${apiUrl}/api/v1/projects/${projectId}/tasks`, {
      headers: { Authorization: `Bearer ${adminAccess}` },
    })
    expect(tasks.response.status).toBe(200)
    const preparedTask = tasks.payload.data.items.find((item: { name: string }) => item.name === "准备数据")
    expect(preparedTask.progress).toBe(40)

    const unrelatedAccess = await loginForAccess(unrelatedUsername, unrelatedPassword)
    const unrelatedMutation = await mutateTask(projectId, preparedTask.id, preparedTask.version, unrelatedAccess)
    expect(unrelatedMutation.response.status).toBe(403)
    expect(unrelatedMutation.payload.error.code).toBe("forbidden")

    const viewerAccess = await loginForAccess(viewerUsername, viewerPassword)
    const viewerMutation = await mutateTask(projectId, preparedTask.id, preparedTask.version, viewerAccess)
    expect(viewerMutation.response.status).toBe(403)
    expect(viewerMutation.payload.error.code).toBe("forbidden")
  } finally {
    await application?.close()
  }
})

async function publishTemplate(page: Page, templateName: string): Promise<void> {
  await page.getByRole("link", { name: "行业模板" }).click()
  await page.getByRole("button", { name: "新建模板" }).click()
  await page.getByLabel("模板名称").fill(templateName)
  await page.getByLabel("行业名称").fill("制造业")
  await addTemplateModule(page, "pre_diagnosis", "预诊断", "需求确认", "confirm_scope")
  await addTemplateModule(page, "pov", "PoV", "准备数据", "prepare_data")
  await page.getByRole("button", { name: "发布 v1" }).click()
  await expect(page.getByRole("status")).toContainText("v1 已发布")
}

async function addTemplateModule(
  page: Page,
  moduleKey: string,
  moduleName: string,
  taskName: string,
  taskKey: string,
): Promise<void> {
  await page.getByLabel("选择模块").selectOption(moduleKey)
  await page.getByRole("button", { name: "添加模块" }).click()
  const moduleCard = page.locator("article.module-editor-card").filter({ has: page.locator(`code:text-is(\"${moduleKey}\")`) })
  await moduleCard.getByLabel(`${moduleKey} 模块名称`).fill(moduleName)
  await moduleCard.getByRole("button", { name: new RegExp("新增任务$") }).click()
  const taskCard = moduleCard.locator("article.task-editor-card").last()
  await taskCard.getByLabel(/任务名称$/).fill(taskName)
  await taskCard.getByLabel(/稳定任务标识$/).fill(taskKey)
}

async function createProject(page: Page, templateName: string, projectCode: string): Promise<string> {
  await page.getByRole("link", { name: "项目工作台" }).click()
  await page.getByRole("link", { name: "新建项目" }).click()
  await page.getByLabel("项目名称").fill("星河 PoV")
  await page.getByLabel("企业名称").fill("星河制造")
  await page.getByLabel("项目编号").fill(projectCode)
  await page.getByLabel("计划开始日期").fill("2026-09-01")
  await page.getByRole("button", { name: "下一步" }).click()
  await page.getByLabel("行业模板版本").selectOption({ label: `${templateName} v1` })
  await page.getByLabel("项目负责人").selectOption({ label: "阶段二管理员" })
  await page.getByRole("button", { name: "下一步" }).click()
  await page.getByLabel("预诊断").check()
  await page.getByLabel("PoV", { exact: true }).check()
  await page.getByRole("button", { name: "下一步" }).click()
  await page.getByRole("button", { name: "创建项目" }).click()
  await page.getByRole("heading", { name: "项目详情" }).waitFor()
  const match = page.url().match(/#projects\/([^?]+)/)
  if (!match) throw new Error("Created project ID was not present in the route.")
  return decodeURIComponent(match[1])
}

async function addProjectMember(page: Page, username: string, role: "member" | "viewer"): Promise<void> {
  if (await page.getByRole("tab", { name: "成员" }).getAttribute("aria-selected") !== "true") {
    await page.getByRole("tab", { name: "成员" }).click()
  }
  const option = page.getByLabel("用户").locator("option").filter({ hasText: `(${username})` })
  const userId = await option.getAttribute("value")
  if (!userId) throw new Error(`Project member option was not found for ${username}.`)
  await page.getByLabel("用户").selectOption(userId)
  await page.getByLabel("项目访问权限").selectOption(role)
  await page.getByRole("button", { name: "添加成员" }).click()
  await expect(page.getByRole("status")).toContainText("成员已添加")
}

async function createUser(page: Page, username: string, displayName: string, role: string, password: string): Promise<void> {
  await page.getByLabel("用户名").fill(username)
  await page.getByLabel("显示名称").fill(displayName)
  await page.getByLabel("角色").selectOption(role)
  await page.getByLabel("临时密码").fill(password)
  await page.getByRole("button", { name: "创建账号" }).click()
  await expect(page.getByRole("status")).toContainText("账号已创建")
}

async function loginAndChangePassword(page: Page, username: string, currentPassword: string, newPassword: string): Promise<void> {
  await login(page, username, currentPassword, "修改初始密码")
  await page.getByLabel("当前密码").fill(currentPassword)
  await page.getByLabel("新密码", { exact: true }).fill(newPassword)
  await page.getByLabel("确认新密码").fill(newPassword)
  await page.getByRole("button", { name: "保存新密码" }).click()
  await waitForDestinationOrSafeError(page, "项目工作台", "Password change")
}

async function login(page: Page, username: string, password: string, destination = "项目工作台"): Promise<void> {
  await page.evaluate(() => { window.location.hash = "#projects" })
  await page.getByLabel("用户名").fill(username)
  await page.getByLabel("密码").fill(password)
  await page.getByRole("button", { name: "登录" }).click()
  await waitForDestinationOrSafeError(page, destination, "Login")
}

async function logout(page: Page): Promise<void> {
  await page.getByRole("button", { name: "退出登录" }).click()
  await page.getByRole("heading", { name: "FDE 工作台" }).waitFor()
}

async function waitForDestinationOrSafeError(page: Page, heading: string, operation: string): Promise<void> {
  const destination = page.getByRole("heading", { name: heading })
  const alert = page.getByRole("alert")
  try {
    await destination.waitFor({ timeout: 12_000 })
    return
  } catch {
    if (!(await alert.isVisible())) {
      const headings = await page.getByRole("heading").allTextContents()
      throw new Error(
        `${operation} did not reach its destination; visible headings: ${JSON.stringify(headings)}`,
      )
    }
    throw new Error(`${operation} failed in the UI: ${(await alert.textContent())?.trim() || "unknown error"}`)
  }
}

async function loginForAccess(username: string, password: string): Promise<string> {
  const loginResponse = await loginForSession(username, password)
  return String(loginResponse.payload.data.access_token)
}

async function loginForSession(username: string, password: string) {
  const loginResponse = await postJson("/api/v1/auth/login", {
    username,
    password,
    device_label: "phase2-e2e-api",
  })
  expect(loginResponse.response.status).toBe(200)
  return loginResponse
}

function mutateTask(projectId: string, taskId: string, version: number, accessToken: string) {
  return fetchJson(`${apiUrl}/api/v1/projects/${projectId}/tasks/${taskId}`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ status: "in_progress", progress: 50, version }),
  })
}

function runServerCommand(args: string[], additionalEnvironment: NodeJS.ProcessEnv = {}): void {
  const result = spawnSync(resolve(serverRoot, ".venv/bin/python"), args, {
    cwd: serverRoot,
    env: { ...serverEnvironment(), ...additionalEnvironment },
    encoding: "utf8",
  })
  if (result.status !== 0) throw new Error(`E2E server setup failed: ${result.stderr || result.stdout}`)
}

function serverEnvironment(): NodeJS.ProcessEnv {
  if (!unavailableRedisUrl) throw new Error("The unavailable Redis endpoint must be verified before server setup.")
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
  if (parsed.pathname !== "/fde_workbench_test") throw new Error("Electron E2E tests require the dedicated fde_workbench_test database.")
}

async function waitForApi(): Promise<void> {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (server?.exitCode !== null) throw new Error("The E2E Flask server exited before becoming ready.")
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

function requiredEnvironment(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`${name} is required for the Electron E2E test.`)
  return value
}

function postJson(path: string, body: Record<string, unknown>) {
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
