import { createHash } from "node:crypto"
import { spawnSync } from "node:child_process"

export const FDE_API_LAUNCHD_DEFINITION = Object.freeze({
  label: "org.fdeworkbench.api",
  program: "/bin/zsh",
  argumentHashes: Object.freeze([
    "b663616e0c19c82649403596a2fa8185e4ef34c22f2bc3623359e9f0428b9153",
    "18dc8bbe7de6f3f774e664aae7ddbba16dee2cd5ee9736e63e6c5ca4cf26c30c",
    "ac7bc9e79dbf85ca8c5a8f7b3acd2eeafb7b467a3386d5204dffa4fe358bc0c7",
  ]),
})

const DEFAULT_PORT = 8010
const DEFAULT_HEALTH_URL = "http://127.0.0.1:8010/api/v1/health/live"
const POLL_ATTEMPTS = 100
const POLL_INTERVAL_MS = 100

export async function withLaunchdPortIsolation({
  system,
  allowedDefinition = FDE_API_LAUNCHD_DEFINITION,
  operation,
  port = DEFAULT_PORT,
  healthUrl = DEFAULT_HEALTH_URL,
  onEvent = () => {},
}) {
  let snapshot = null
  let operationResult
  let primaryError = null
  let restorationError = null

  try {
    const listenerPids = await inspectListenerPids(system, port)
    if (listenerPids.length === 0) {
      operationResult = await operation()
    } else {
      const listenerPid = requireSingleListener(listenerPids)
      const job = await system.readJob(allowedDefinition.label)
      requireAllowedOwner(job, listenerPid, allowedDefinition)

      const confirmedListenerPids = await inspectListenerPids(system, port)
      if (confirmedListenerPids.length === 0) {
        operationResult = await operation()
      } else {
        if (
          confirmedListenerPids.length !== 1 ||
          confirmedListenerPids[0] !== listenerPid
        ) {
          throw foreignListenerError()
        }
        const confirmedJob = await system.readJob(allowedDefinition.label)
        requireAllowedOwner(confirmedJob, listenerPid, allowedDefinition)
        snapshot = snapshotDefinition(confirmedJob)
        await system.bootout(allowedDefinition.label)
        onEvent("bootout")
        await waitForPortToBeFree(system, port)
        operationResult = await operation()
      }
    }
  } catch (error) {
    primaryError = asError(error)
  } finally {
    if (snapshot) {
      try {
        await restoreSnapshot(system, snapshot, port, healthUrl)
        onEvent("restored")
      } catch (error) {
        restorationError = asError(error)
      }
    }
  }

  if (restorationError && primaryError) {
    throw new AggregateError(
      [primaryError, restorationError],
      `E2E failed and launchd API restoration failed: ${restorationError.message}`,
    )
  }
  if (restorationError) {
    throw new Error(
      `E2E launchd API restoration failed: ${restorationError.message}`,
      { cause: restorationError },
    )
  }
  if (primaryError) throw primaryError
  return operationResult
}

export function createMacLaunchdSystem({
  userId = process.getuid(),
  spawnSyncCommand = spawnSync,
  fetchHealth = fetch,
} = {}) {
  const domainFor = (label) => `gui/${userId}/${label}`

  return {
    async listenerPids(port) {
      const result = spawnSyncCommand(
        "lsof",
        ["-nP", "-t", `-iTCP:${port}`, "-sTCP:LISTEN"],
        { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
      )
      if (result.error) {
        throw new Error("Could not inspect the E2E API port listener.")
      }
      if (result.status === 1 && !result.stdout.trim()) return []
      if (result.status !== 0) {
        throw new Error("Could not inspect the E2E API port listener.")
      }
      const pids = result.stdout
        .split(/\s+/)
        .filter(Boolean)
        .map((value) => Number(value))
      if (pids.some((pid) => !Number.isSafeInteger(pid) || pid <= 0)) {
        throw new Error("The E2E API port listener ownership was ambiguous.")
      }
      return [...new Set(pids)]
    },

    async readJob(label) {
      const domain = domainFor(label)
      const result = spawnSyncCommand(
        "launchctl",
        ["print", domain],
        { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
      )
      if (result.error) {
        throw new Error("Could not inspect the allowed launchd job.")
      }
      if (result.status !== 0) return null
      return parseLaunchctlJob(result.stdout, domain, label)
    },

    async bootout(label) {
      const result = spawnSyncCommand(
        "launchctl",
        ["bootout", domainFor(label)],
        { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
      )
      if (result.error || result.status !== 0) {
        throw new Error("Could not temporarily stop the allowed launchd job.")
      }
    },

    async submit(snapshot) {
      const result = spawnSyncCommand(
        "launchctl",
        ["submit", "-l", snapshot.label, "--", ...snapshot.arguments],
        { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
      )
      if (result.error || result.status !== 0) {
        throw new Error("Could not submit the saved launchd job definition.")
      }
    },

    async healthStatus(url) {
      try {
        const response = await fetchHealth(url, {
          signal: AbortSignal.timeout(500),
        })
        return response.status
      } catch {
        return null
      }
    },

    async wait(milliseconds) {
      await new Promise((resolveWait) => setTimeout(resolveWait, milliseconds))
    },
  }
}

export function createSignalCoordinator(processEvents = process) {
  let interruptedSignal = null
  let activeChild = null

  const handleSignal = (signal) => {
    if (!interruptedSignal) interruptedSignal = signal
    if (activeChild) activeChild.kill(signal)
  }
  const onSigint = () => handleSignal("SIGINT")
  const onSigterm = () => handleSignal("SIGTERM")
  processEvents.on("SIGINT", onSigint)
  processEvents.on("SIGTERM", onSigterm)

  return {
    attachChild(child) {
      activeChild = child
      if (interruptedSignal) child.kill(interruptedSignal)
    },
    detachChild(child) {
      if (activeChild === child) activeChild = null
    },
    throwIfInterrupted() {
      if (!interruptedSignal) return
      const error = new Error(`Interrupted by ${interruptedSignal}; cleanup completed.`)
      error.name = "E2eSignalError"
      error.signal = interruptedSignal
      throw error
    },
    get exitCode() {
      if (interruptedSignal === "SIGINT") return 130
      if (interruptedSignal === "SIGTERM") return 143
      return null
    },
    dispose() {
      processEvents.off("SIGINT", onSigint)
      processEvents.off("SIGTERM", onSigterm)
      activeChild = null
    },
  }
}

async function inspectListenerPids(system, port) {
  const listenerPids = await system.listenerPids(port)
  if (!Array.isArray(listenerPids)) {
    throw new Error("The E2E API port listener ownership was ambiguous.")
  }
  return [...new Set(listenerPids)]
}

function requireSingleListener(listenerPids) {
  if (listenerPids.length !== 1) throw foreignListenerError()
  const [listenerPid] = listenerPids
  if (!Number.isSafeInteger(listenerPid) || listenerPid <= 0) {
    throw foreignListenerError()
  }
  return listenerPid
}

function requireAllowedOwner(job, listenerPid, allowedDefinition) {
  if (
    !job ||
    job.pid !== listenerPid ||
    job.state !== "running" ||
    !matchesAllowedDefinition(job, allowedDefinition)
  ) {
    throw foreignListenerError()
  }
}

function matchesAllowedDefinition(job, allowedDefinition) {
  if (
    job.label !== allowedDefinition.label ||
    job.program !== allowedDefinition.program ||
    !Array.isArray(job.arguments) ||
    job.arguments.length !== allowedDefinition.argumentHashes.length
  ) {
    return false
  }
  return job.arguments.every(
    (argument, index) => sha256(argument) === allowedDefinition.argumentHashes[index],
  )
}

function snapshotDefinition(job) {
  return Object.freeze({
    label: job.label,
    program: job.program,
    arguments: Object.freeze([...job.arguments]),
  })
}

async function waitForPortToBeFree(system, port) {
  for (let attempt = 0; attempt < POLL_ATTEMPTS; attempt += 1) {
    if ((await inspectListenerPids(system, port)).length === 0) return
    await system.wait(POLL_INTERVAL_MS)
  }
  throw new Error("Port 8010 did not become free after stopping the allowed launchd job.")
}

async function restoreSnapshot(system, snapshot, port, healthUrl) {
  const currentJob = await system.readJob(snapshot.label)
  if (currentJob) {
    if (!matchesSnapshot(currentJob, snapshot)) {
      throw new Error("The launchd label was replaced; refusing to overwrite it.")
    }
  } else {
    await system.submit(snapshot)
  }

  for (let attempt = 0; attempt < POLL_ATTEMPTS; attempt += 1) {
    const job = await system.readJob(snapshot.label)
    const listenerPids = await inspectListenerPids(system, port)
    const definitionIsRestored = job && matchesSnapshot(job, snapshot)
    const listenerIsOwned =
      definitionIsRestored &&
      Number.isSafeInteger(job.pid) &&
      listenerPids.length === 1 &&
      listenerPids[0] === job.pid
    if (
      definitionIsRestored &&
      job.state === "running" &&
      listenerIsOwned &&
      (await system.healthStatus(healthUrl)) === 200
    ) {
      return
    }
    await system.wait(POLL_INTERVAL_MS)
  }
  throw new Error("The saved launchd job did not return to running state and health 200.")
}

function matchesSnapshot(job, snapshot) {
  return (
    job.label === snapshot.label &&
    job.program === snapshot.program &&
    Array.isArray(job.arguments) &&
    job.arguments.length === snapshot.arguments.length &&
    job.arguments.every((argument, index) => argument === snapshot.arguments[index])
  )
}

function parseLaunchctlJob(output, domain, label) {
  const lines = output.split(/\r?\n/)
  if (lines[0]?.trim() !== `${domain} = {`) {
    throw new Error("The allowed launchd job definition could not be verified.")
  }
  const program = fieldValue(lines, "program")
  const state = fieldValue(lines, "state")
  const pidText = fieldValue(lines, "pid")
  const argumentsStart = lines.findIndex((line) => line.trim() === "arguments = {")
  if (argumentsStart < 0) {
    throw new Error("The allowed launchd job definition could not be verified.")
  }
  const argumentsList = []
  for (const line of lines.slice(argumentsStart + 1)) {
    if (line.trim() === "}") break
    argumentsList.push(line.trim())
  }
  const pid = Number(pidText)
  if (!program || !state || !Number.isSafeInteger(pid) || argumentsList.length === 0) {
    throw new Error("The allowed launchd job definition could not be verified.")
  }
  return { label, program, arguments: argumentsList, pid, state }
}

function fieldValue(lines, field) {
  const prefix = `${field} = `
  const line = lines.find((candidate) => candidate.trim().startsWith(prefix))
  return line?.trim().slice(prefix.length) ?? null
}

function foreignListenerError() {
  return new Error(
    "Refusing E2E: port 8010 is not owned by the allowed launchd job; no process was stopped.",
  )
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex")
}

function asError(error) {
  return error instanceof Error ? error : new Error("Unknown E2E isolation failure.")
}
