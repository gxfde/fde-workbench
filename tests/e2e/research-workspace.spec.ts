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

test.describe.configure({ mode: "serial" })

test.beforeAll(async () => {
  assertDedicatedTestDatabase(requiredEnvironment("FDE_DATABASE_URL"))
  runServerCommand(["-m", "alembic", "upgrade", "head"])
  testSchemaReady = true
  runServerCommand(["-m", "flask", "--app", "fde_api.app:create_app", "seed-workbench"])
  runServerCommand([cleanupScript, "--ensure-preservation-fixtures"])
  runServerCommand([cleanupScript, "--verify-preservation-fingerprint"])
  runServerCommand([cleanupScript])
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
      "调研 E2E 管理员",
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

test("industry research survives template changes and keeps confirmed history with role isolation", async () => {
  test.setTimeout(300_000)
  const runId = requiredEnvironment("FDE_E2E_RUN_ID")
  const templateName = requiredEnvironment("FDE_E2E_RESEARCH_TEMPLATE_NAME")
  const projectCode = requiredEnvironment("FDE_E2E_RESEARCH_PROJECT_CODE")
  const projectName = `调研项目 ${runId}`
  const admin = account("ADMIN")
  const lead = account("LEAD")
  const engineer = account("ENGINEER")
  const unrelated = account("UNRELATED_ENGINEER")
  const viewer = account("VIEWER")

  let application: ElectronApplication | undefined
  let page: Page | undefined
  try {
    application = await electron.launch({
      args: [
        desktopMainEntry,
        `--user-data-dir=${resolve(requiredEnvironment("FDE_E2E_USER_DATA_PATH"), "research-workspace")}`,
      ],
      env: buildElectronEnvironment(process.env, apiUrl),
    })
    page = await application.firstWindow()
    page.setDefaultTimeout(15_000)

    await loginAndChangePassword(page, admin)
    await createResearchUsers(page, { lead, engineer, unrelated, viewer })
    for (const created of [lead, engineer, unrelated, viewer]) {
      await logout(page)
      await loginAndChangePassword(page, created)
    }
    await logout(page)
    await login(page, admin.username, admin.password)

    const adminAccess = await loginForAccess(admin.username, admin.password)
    await createAndPublishResearchTemplate(page, templateName)
    const templateV1 = await findTemplateVersion(adminAccess, templateName, 1)
    expect(templateV1.status, "template publish boundary").toBe("published")

    const projectId = await createProjectFromTemplate(page, {
      templateName,
      projectCode,
      projectName,
      leaderUserId: await findUserId(adminAccess, lead.username),
    })
    await addProjectMember(page, engineer.username, "member")
    await addProjectMember(page, viewer.username, "viewer")

    const projectV1 = await authenticatedJson(adminAccess, `/api/v1/projects/${projectId}`)
    expect(projectV1.response.status, "project snapshot boundary").toBe(200)
    expect(projectV1.payload.data.template_version_id).toBe(templateV1.version_id)
    expect(researchFieldNames(projectV1.payload.data.research_snapshot)).toContain("旧版岗位字段")
    expect(researchFieldNames(projectV1.payload.data.research_snapshot)).not.toContain("新版岗位字段")

    await logout(page)
    await login(page, engineer.username, engineer.password)
    await openProjectResearch(page, projectId)
    await createSubject(page, "部门", "仓储部")
    await page.getByRole("treeitem", { name: /\u4ed3\u50a8\u90e8/ }).click()
    await createSubject(page, "岗位", "仓库主管")
    await expect(page.getByRole("heading", { name: "岗位调研" }), "subject creation boundary").toBeVisible()
    await page.getByLabel("旧版岗位字段").fill("优化出入库协同")
    await page.getByLabel("在岗人数").fill("12")
    await page.getByLabel("ERP").check()
    await expect(page.getByRole("button", { name: "保存并确认" })).toHaveCount(0)
    await page.getByRole("button", { name: "保存草稿" }).click()
    await expect(page.getByText("草稿已保存。", { exact: true }), "typed answer save boundary").toBeVisible()

    await verifyImportPreviewError(page)

    const engineerAccess = await loginForAccess(engineer.username, engineer.password)
    const roleDraft = await findProjectForm(engineerAccess, projectId, "role_profile")
    expect(answerValue(roleDraft, "headcount"), "typed integer save boundary").toBe(12)
    expect(answerValue(roleDraft, "systems"), "typed multi-choice save boundary").toEqual(["ERP"])
    const engineerConfirm = await authenticatedJson(
      engineerAccess,
      `/api/v1/projects/${projectId}/research/forms/${roleDraft.id}/confirm`,
      { method: "POST", body: JSON.stringify({ version: roleDraft.current_revision.version }) },
    )
    expect(engineerConfirm.response.status, "assigned engineer role isolation").toBe(403)
    expect(engineerConfirm.payload.error.code).toBe("forbidden")

    await logout(page)
    await login(page, lead.username, lead.password)
    await openProjectResearch(page, projectId)
    await page.getByRole("treeitem", { name: /\u4ed3\u5e93\u4e3b\u7ba1/ }).click()
    await page.getByRole("button", { name: "保存并确认" }).click()
    await expect(page.getByText("已确认", { exact: true }), "confirmation boundary").toBeVisible()
    await expect(page.getByText("修订 1", { exact: true })).toBeVisible()

    const leadAccess = await loginForAccess(lead.username, lead.password)
    const confirmedV1 = await findProjectForm(leadAccess, projectId, "role_profile")
    expect(confirmedV1.current_revision.status).toBe("confirmed")
    expect(answerValue(confirmedV1, "legacy_role_note")).toBe("优化出入库协同")

    await logout(page)
    await login(page, admin.username, admin.password)
    await publishChangedTemplate(page, templateName)
    const templateV2 = await findTemplateVersion(adminAccess, templateName, 2)
    expect(templateV2.status, "template v2 publish boundary").toBe("published")
    const v2Definition = await findTemplateResearchDefinition(adminAccess, templateV2)
    expect(researchFieldNames(v2Definition), "template v2 definition boundary").toContain("新版岗位字段")
    expect(researchFieldNames(v2Definition)).not.toContain("旧版岗位字段")

    await openProjectResearch(page, projectId)
    await page.getByRole("treeitem", { name: /\u4ed3\u5e93\u4e3b\u7ba1/ }).click()
    await expect(page.getByLabel("旧版岗位字段"), "frozen project snapshot boundary").toBeVisible()
    await expect(page.getByLabel("新版岗位字段")).toHaveCount(0)
    await page.getByRole("button", { name: "新建修订" }).click()
    await expect(page.getByText("修订 2", { exact: true }), "revision boundary").toBeVisible()
    await expect(page.getByText(/原版本保持不变/)).toBeVisible()
    await page.getByLabel("旧版岗位字段").fill("修订后的岗位答案")
    await page.getByRole("button", { name: "保存并确认" }).click()
    await expect(page.getByText("已确认", { exact: true })).toBeVisible()

    const confirmedV2 = await findProjectForm(adminAccess, projectId, "role_profile")
    expect(confirmedV2.current_revision.revision_number).toBe(2)
    expect(confirmedV2.current_revision.parent_revision_id).toBe(confirmedV1.current_revision.id)
    expect(answerValue(confirmedV2, "legacy_role_note")).toBe("修订后的岗位答案")
    runServerCommand([cleanupScript, "--verify-research-history"])

    const viewerAccess = await loginForAccess(viewer.username, viewer.password)
    const viewerMutation = await authenticatedJson(
      viewerAccess,
      `/api/v1/projects/${projectId}/research/forms/${confirmedV2.id}`,
      { method: "PATCH", body: JSON.stringify({ version: confirmedV2.current_revision.version, answers: {} }) },
    )
    expect(viewerMutation.response.status, "viewer API role isolation").toBe(403)
    expect(viewerMutation.payload.error.code).toBe("forbidden")

    await logout(page)
    await login(page, viewer.username, viewer.password)
    await openProjectResearch(page, projectId)
    await page.getByRole("treeitem", { name: /\u4ed3\u5e93\u4e3b\u7ba1/ }).click()
    await expect(page.getByLabel("旧版岗位字段")).toBeDisabled()
    await expect(page.getByRole("button", { name: "保存草稿" })).toHaveCount(0)
    await expect(page.getByRole("button", { name: "新建修订" })).toHaveCount(0)
    await expect(page.getByRole("button", { name: "新增部门" })).toHaveCount(0)

    const unrelatedAccess = await loginForAccess(unrelated.username, unrelated.password)
    const unrelatedProject = await authenticatedJson(unrelatedAccess, `/api/v1/projects/${projectId}`)
    expect(unrelatedProject.response.status, "unassigned engineer role isolation").toBe(403)
    expect(unrelatedProject.payload.error.code).toBe("forbidden")

    await logout(page)
    await login(page, unrelated.username, unrelated.password)
    await expect(page.getByRole("link", { name: `查看${projectName}` })).toHaveCount(0)
  } finally {
    await closeApplication(application)
  }
})

async function createAndPublishResearchTemplate(page: Page, templateName: string): Promise<void> {
  await page.getByRole("link", { name: "行业模板" }).click()
  await page.getByRole("button", { name: "新建模板" }).click()
  await page.getByLabel("模板名称").fill(templateName)
  await page.getByLabel("行业名称").fill("制造业")
  await addTemplateModule(page)
  await page.getByRole("button", { name: "保存草稿" }).click()
  await expect(page.getByRole("status")).toContainText("草稿已保存")
  await page.getByRole("tab", { name: "调研表" }).click()
  await expect(page.getByRole("heading", { name: "调研表" })).toBeVisible()
  await addResearchForm(page, 1, {
    name: "部门调研",
    key: "department_profile",
    subjectType: "department",
    sectionName: "部门概况",
    sectionKey: "department_basics",
    fields: [{ name: "部门职责", key: "department_mission", type: "short_text", required: true }],
  })
  await addResearchForm(page, 2, {
    name: "岗位调研",
    key: "role_profile",
    subjectType: "role",
    sectionName: "岗位概况",
    sectionKey: "role_basics",
    fields: [
      { name: "旧版岗位字段", key: "legacy_role_note", type: "short_text", required: true },
      { name: "在岗人数", key: "headcount", type: "integer", required: true },
      { name: "系统使用", key: "systems", type: "multi_choice", choices: ["ERP", "WMS"] },
    ],
  })
  await page.getByRole("button", { name: "保存并发布调研模板" }).click()
  await expect(page.getByRole("status")).toContainText("v1 已发布")
}

async function addTemplateModule(page: Page): Promise<void> {
  await page.getByLabel("选择模块").selectOption("pre_diagnosis")
  await page.getByRole("button", { name: "添加模块" }).click()
  const moduleCard = page.locator("article.module-editor-card").filter({ has: page.locator('code:text-is("pre_diagnosis")') })
  await moduleCard.getByRole("button", { name: /新增任务$/ }).click()
  const taskCard = moduleCard.locator("article.task-editor-card").last()
  await taskCard.getByLabel(/任务名称$/).fill("完成调研")
  await taskCard.getByLabel(/稳定任务标识$/).fill("complete_research")
}

interface ResearchFormInput {
  name: string
  key: string
  subjectType: "department" | "role"
  sectionName: string
  sectionKey: string
  fields: Array<{
    name: string
    key: string
    type: "short_text" | "integer" | "multi_choice"
    required?: boolean
    choices?: string[]
  }>
}

async function addResearchForm(page: Page, index: number, input: ResearchFormInput): Promise<void> {
  await page.getByRole("button", { name: "新增调研表" }).click()
  const prefix = `表单 ${index}`
  await page.getByLabel(`${prefix} 名称`).fill(input.name)
  await page.getByLabel(`${prefix} 稳定标识`).fill(input.key)
  await page.getByLabel(`${prefix} 调研主体`).selectOption(input.subjectType)
  await page.getByRole("button", { name: `在${prefix} 中新增章节` }).click()
  const sectionPrefix = `${prefix} 章节 1`
  await page.getByLabel(`${sectionPrefix} 标题`).fill(input.sectionName)
  await page.getByLabel(`${sectionPrefix} 稳定标识`).fill(input.sectionKey)
  for (const [fieldOffset, field] of input.fields.entries()) {
    await page.getByRole("button", { name: `在${sectionPrefix} 中新增字段` }).click()
    const fieldPrefix = `${sectionPrefix} 字段 ${fieldOffset + 1}`
    await page.getByLabel(`${fieldPrefix} 标签`).fill(field.name)
    await page.getByLabel(`${fieldPrefix} 稳定标识`).fill(field.key)
    await page.getByLabel(`${fieldPrefix} 类型`).selectOption(field.type)
    if (field.required) await page.getByLabel(`${fieldPrefix} 必填`).check()
    if (field.choices) {
      await page.getByLabel(`${fieldPrefix} 选项（每行一个）`).fill(field.choices.join("\n"))
    }
  }
}

async function publishChangedTemplate(page: Page, templateName: string): Promise<void> {
  await page.getByRole("link", { name: "行业模板" }).click()
  const templateRows = page.getByRole("row").filter({ hasText: templateName })
  await templateRows.first().getByRole("button", { name: "基于最新版本创建 v2" }).click()
  await expect(page.getByRole("heading", { name: "编辑 v2 草稿" })).toBeVisible()
  await page.getByRole("tab", { name: "调研表" }).click()
  await expect(page.getByRole("heading", { name: "调研表" })).toBeVisible()
  await page.getByLabel("表单 2 章节 1 字段 1 标签").fill("新版岗位字段")
  await page.getByRole("button", { name: "保存并发布调研模板" }).click()
  await expect(page.getByRole("status")).toContainText("v2 已发布")
}

async function createProjectFromTemplate(page: Page, input: {
  templateName: string
  projectCode: string
  projectName: string
  leaderUserId: string
}): Promise<string> {
  await page.getByRole("link", { name: "项目工作台" }).click()
  await page.getByRole("link", { name: "新建项目" }).click()
  await page.getByLabel("项目名称").fill(input.projectName)
  await page.getByLabel("企业名称").fill("调研验证企业")
  await page.getByLabel("项目编号").fill(input.projectCode)
  await page.getByLabel("计划开始日期").fill("2026-09-01")
  await page.getByRole("button", { name: "下一步" }).click()
  await page.getByLabel("行业模板版本").selectOption({ label: `${input.templateName} v1` })
  await page.getByLabel("项目负责人").selectOption(input.leaderUserId)
  await page.getByRole("button", { name: "下一步" }).click()
  await page.getByLabel("前期诊断").check()
  await page.getByRole("button", { name: "下一步" }).click()
  await page.getByRole("button", { name: "创建项目" }).click()
  await page.getByRole("heading", { name: "项目详情" }).waitFor()
  const match = page.url().match(/#projects\/([^?]+)/)
  if (!match) throw new Error("project creation boundary: route did not contain the project ID")
  return decodeURIComponent(match[1])
}

async function addProjectMember(page: Page, username: string, role: "member" | "viewer"): Promise<void> {
  await page.getByRole("tab", { name: "成员" }).click()
  const option = page.getByLabel("用户").locator("option").filter({ hasText: `(${username})` })
  const userId = await option.getAttribute("value")
  if (!userId) throw new Error(`role isolation setup: user option missing for ${username}`)
  await page.getByLabel("用户").selectOption(userId)
  await page.getByLabel("项目访问权限").selectOption(role)
  await page.getByRole("button", { name: "添加成员" }).click()
  await expect(page.getByRole("status")).toContainText("成员已添加")
}

async function createResearchUsers(page: Page, users: Record<string, E2EAccount>): Promise<void> {
  await page.getByRole("link", { name: "用户管理" }).click()
  await createUser(page, users.lead, "调研项目负责人", "project_lead")
  await createUser(page, users.engineer, "已分配调研工程师", "fde_engineer")
  await createUser(page, users.unrelated, "未分配调研工程师", "fde_engineer")
  await createUser(page, users.viewer, "调研查看者", "viewer")
}

async function createUser(page: Page, user: E2EAccount, displayName: string, role: string): Promise<void> {
  await page.getByLabel("用户名").fill(user.username)
  await page.getByLabel("显示名称").fill(displayName)
  await page.getByLabel("角色").selectOption(role)
  await page.getByLabel("临时密码").fill(user.initialPassword)
  await page.getByRole("button", { name: "创建账号" }).click()
  await expect(page.getByRole("status")).toContainText("账号已创建")
}

async function createSubject(page: Page, type: "部门" | "岗位", name: string): Promise<void> {
  await page.getByRole("button", { name: `新增${type}` }).click()
  await page.getByLabel(`${type}名称`).fill(name)
  await page.getByRole("button", { name: "创建", exact: true }).click()
  await expect(page.getByRole("status")).toContainText(`${type}已创建`)
  await expect(page.getByRole("treeitem", { name: new RegExp(name) })).toBeVisible()
}

async function verifyImportPreviewError(page: Page): Promise<void> {
  await page.getByLabel("导入对象类型").selectOption("role")
  await page.getByLabel("调研对象导入文件").setInputFiles({
    name: "roles.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("名称,父级\n夜班主管,不存在\n", "utf8"),
  })
  await page.getByRole("button", { name: "预检导入" }).click()
  const preview = page.getByRole("table", { name: "导入预览" })
  await expect(preview, "import preview boundary").toBeVisible()
  await expect(preview.getByText("第 2 行", { exact: true })).toBeVisible()
  await expect(preview.getByText("通过", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "确认导入" }).click()
  const commitErrors = page.getByRole("list", { name: "导入提交错误" })
  await expect(commitErrors, "import commit error boundary").toBeVisible()
  const errorItems = commitErrors.getByRole("listitem")
  await expect(errorItems).toHaveCount(1)
  await expect(errorItems).toHaveText("第 2 行 · 父级：未找到父级对象。")
}

async function openProjectResearch(page: Page, projectId: string): Promise<void> {
  await page.evaluate(() => { window.location.hash = "#projects" })
  await page.getByRole("heading", { name: "项目工作台" }).waitFor()
  await page.evaluate((id) => { window.location.hash = `#projects/${encodeURIComponent(id)}` }, projectId)
  await page.getByRole("heading", { name: "项目详情" }).waitFor()
  await page.getByRole("tab", { name: "调研" }).click()
  const researchHeading = page.getByRole("heading", { name: "项目调研" })
  try {
    await researchHeading.waitFor({ timeout: 8_000 })
  } catch {
    const alert = page.getByRole("alert")
    throw new Error(`research UI route failed: ${await alert.isVisible() ? await alert.innerText() : await page.locator("main").innerText()}`)
  }
}

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

async function logout(page: Page): Promise<void> {
  await page.getByRole("button", { name: "退出登录" }).click()
  await page.getByRole("heading", { name: "FDE 工作台" }).waitFor()
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

async function findTemplateVersion(accessToken: string, templateName: string, versionNumber: number): Promise<any> {
  const result = await authenticatedJson(accessToken, "/api/v1/industry-templates?page=1&page_size=100")
  expect(result.response.status).toBe(200)
  const version = result.payload.data.items.find((item: any) => item.template_name === templateName && item.version_number === versionNumber)
  if (!version) throw new Error(`template publish boundary: ${templateName} v${versionNumber} missing`)
  return version
}

async function findTemplateResearchDefinition(accessToken: string, version: any): Promise<any> {
  const result = await authenticatedJson(
    accessToken,
    `/api/v1/templates/${version.template_id}/versions/${version.version_id}/research-forms`,
  )
  expect(result.response.status).toBe(200)
  return result.payload.data
}

async function findUserId(accessToken: string, username: string): Promise<string> {
  const result = await authenticatedJson(accessToken, "/api/v1/users?page=1&page_size=100")
  expect(result.response.status).toBe(200)
  const user = result.payload.data.items.find((item: any) => item.username === username)
  if (!user) throw new Error(`project setup: leader missing for ${username}`)
  return String(user.id)
}

async function findProjectForm(accessToken: string, projectId: string, formKey: string): Promise<any> {
  const result = await authenticatedJson(accessToken, `/api/v1/projects/${projectId}/research/forms`)
  expect(result.response.status).toBe(200)
  const form = result.payload.data.items.find((item: any) => item.form_key === formKey)
  if (!form) throw new Error(`research form boundary: ${formKey} missing`)
  return form
}

function answerValue(form: any, fieldKey: string): unknown {
  return form.current_revision.answers.find((answer: any) => answer.field_key === fieldKey)?.value
}

function researchFieldNames(snapshot: any): string[] {
  return (snapshot.forms ?? []).flatMap((form: any) =>
    (form.sections ?? []).flatMap((section: any) => (section.fields ?? []).map((field: any) => field.name)),
  )
}

async function loginForAccess(username: string, password: string): Promise<string> {
  const response = await fetchJson(`${apiUrl}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, device_label: "research-e2e-api" }),
  })
  expect(response.response.status).toBe(200)
  return String(response.payload.data.access_token)
}

function authenticatedJson(accessToken: string, path: string, init: RequestInit = {}) {
  return fetchJson(`${apiUrl}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json", ...init.headers },
  })
}

async function fetchJson(url: string, init?: RequestInit) {
  const response = await fetch(url, init)
  return { response, payload: await response.json() as any }
}

function runServerCommand(args: string[], additionalEnvironment: NodeJS.ProcessEnv = {}): void {
  const result = spawnSync(resolve(serverRoot, ".venv/bin/python"), args, {
    cwd: serverRoot,
    env: { ...serverEnvironment(), ...additionalEnvironment },
    encoding: "utf8",
  })
  if (result.status !== 0) throw new Error(`research E2E server command failed: ${result.stderr || result.stdout}`)
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
  if (parsed.pathname !== "/fde_workbench_test") throw new Error("Research E2E requires the dedicated fde_workbench_test database.")
}

async function waitForApi(): Promise<void> {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    if (server?.exitCode !== null) throw new Error("Research E2E Flask server exited before becoming ready.")
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
  throw new Error("Research E2E API/Redis did not become ready on its assigned loopback port.")
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
  if (!value) throw new Error(`${name} is required for the research Electron E2E test.`)
  return value
}
