import { randomBytes } from "node:crypto"
import { mkdtemp, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { spawn } from "node:child_process"

import { createSignalCoordinator } from "./launchd-port-isolation.mjs"

const userDataPath = await mkdtemp(join(tmpdir(), "fde-workbench-e2e-"))
const runId = randomBytes(6).toString("hex")
const environment = {
  ...process.env,
  FDE_DATABASE_URL:
    process.env.FDE_E2E_DATABASE_URL ??
    "mysql+pymysql://fde_local:change%5Fme@127.0.0.1:3306/fde_workbench_test",
  FDE_JWT_SECRET: randomBytes(32).toString("hex"),
  FDE_E2E_ADMIN_PASSWORD: strongPassword(),
  FDE_E2E_ADMIN_NEW_PASSWORD: strongPassword(),
  FDE_E2E_ENGINEER_PASSWORD: strongPassword(),
  FDE_E2E_ENGINEER_NEW_PASSWORD: strongPassword(),
  FDE_E2E_LEAD_PASSWORD: strongPassword(),
  FDE_E2E_LEAD_NEW_PASSWORD: strongPassword(),
  FDE_E2E_UNRELATED_ENGINEER_PASSWORD: strongPassword(),
  FDE_E2E_UNRELATED_ENGINEER_NEW_PASSWORD: strongPassword(),
  FDE_E2E_VIEWER_PASSWORD: strongPassword(),
  FDE_E2E_VIEWER_NEW_PASSWORD: strongPassword(),
  FDE_E2E_PRESERVED_ADMIN_PASSWORD: strongPassword(),
  FDE_E2E_RUN_ID: runId,
  FDE_E2E_PHASE1_ADMIN_USERNAME: `phase1.admin.${runId}`,
  FDE_E2E_PHASE1_ENGINEER_USERNAME: `phase1.engineer.${runId}`,
  FDE_E2E_ADMIN_USERNAME: `phase2.admin.${runId}`,
  FDE_E2E_ENGINEER_USERNAME: `phase2.engineer.${runId}`,
  FDE_E2E_LEAD_USERNAME: `phase2.lead.${runId}`,
  FDE_E2E_UNRELATED_ENGINEER_USERNAME: `phase2.unrelated.${runId}`,
  FDE_E2E_VIEWER_USERNAME: `phase2.viewer.${runId}`,
  FDE_E2E_PROJECT_CODE: `phase2.${runId}`,
  FDE_E2E_RESEARCH_PROJECT_CODE: `phase2.${runId}.research`,
  FDE_E2E_RESEARCH_TEMPLATE_NAME: `phase2.${runId} 调研模板`,
  FDE_E2E_USER_DATA_PATH: userDataPath,
}

assertDedicatedTestDatabase(environment.FDE_DATABASE_URL)

const signalCoordinator = createSignalCoordinator()
try {
  signalCoordinator.throwIfInterrupted()
  await run(
    "npm",
    ["--workspace", "desktop", "run", "build"],
    environment,
    signalCoordinator,
  )
  signalCoordinator.throwIfInterrupted()
  const requestedSpecs = e2eSpecs(process.argv.slice(2))
  await run(
    "npx",
    ["playwright", "test", ...requestedSpecs, "--workers=1", "--reporter=line"],
    environment,
    signalCoordinator,
  )
  signalCoordinator.throwIfInterrupted()
} catch (error) {
  console.error(`E2E failed: ${safeErrorMessage(error)}`)
  process.exitCode = signalCoordinator.exitCode ?? 1
} finally {
  signalCoordinator.dispose()
  await rm(userDataPath, { recursive: true, force: true })
}

function strongPassword() {
  return `E2e-${randomBytes(18).toString("base64url")}aA1!`
}

function e2eSpecs(arguments_) {
  if (arguments_.length === 0) return ["tests/e2e"]
  return arguments_.map((argument) => {
    if (!/^[A-Za-z0-9._-]+\.spec\.ts$/.test(argument)) {
      throw new Error("E2E spec arguments must be spec filenames inside tests/e2e.")
    }
    return `tests/e2e/${argument}`
  })
}

function assertDedicatedTestDatabase(databaseUrl) {
  if (!databaseUrl.startsWith("mysql+pymysql://")) {
    throw new Error("E2E requires a mysql+pymysql URL for fde_workbench_test.")
  }
  const parsed = new URL(databaseUrl.replace("mysql+pymysql://", "http://"))
  if (parsed.pathname !== "/fde_workbench_test") {
    throw new Error("E2E requires the exact fde_workbench_test database.")
  }
}

function run(command, args, env, signalState) {
  return new Promise((resolveRun, rejectRun) => {
    const child = spawn(command, args, { env, stdio: "inherit" })
    signalState.attachChild(child)
    child.once("error", (error) => {
      signalState.detachChild(child)
      rejectRun(error)
    })
    child.once("exit", (code, signal) => {
      signalState.detachChild(child)
      if (code === 0) resolveRun()
      else rejectRun(new Error(`${command} failed with ${signal ?? `exit code ${code}`}.`))
    })
  })
}

function safeErrorMessage(error) {
  return error instanceof Error ? error.message : "Unknown E2E failure."
}
