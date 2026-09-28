import assert from "node:assert/strict"
import { createHash } from "node:crypto"
import { EventEmitter } from "node:events"
import test from "node:test"

const isolationModule = await import("../../scripts/launchd-port-isolation.mjs").catch(
  () => ({}),
)
const { createSignalCoordinator, withLaunchdPortIsolation } = isolationModule

const label = "org.fdeworkbench.api"
const program = "/bin/zsh"
const launchArguments = [program, "-lc", "fixture-api-command"]
const allowedDefinition = {
  label,
  program,
  argumentHashes: launchArguments.map((value) =>
    createHash("sha256").update(value).digest("hex"),
  ),
}

test("runs without changing launchd when the job is unloaded and port 8010 is free", async () => {
  assert.equal(typeof withLaunchdPortIsolation, "function")
  const system = fakeSystem()

  const result = await withLaunchdPortIsolation({
    system,
    allowedDefinition,
    operation: async () => {
      system.events.push("operation")
      return "complete"
    },
  })

  assert.equal(result, "complete")
  assert.deepEqual(system.events, ["operation"])
  assert.equal(system.job, null)
})

test("temporarily removes the exact owning job and restores its definition", async () => {
  assert.equal(typeof withLaunchdPortIsolation, "function")
  const system = fakeSystem({ exactJob: true })

  await withLaunchdPortIsolation({
    system,
    allowedDefinition,
    operation: async () => {
      assert.deepEqual(await system.listenerPids(8010), [])
      system.events.push("operation")
    },
  })

  assert.deepEqual(system.events, ["bootout", "operation", "submit"])
  assert.equal(system.job?.label, label)
  assert.equal(system.job?.program, program)
  assert.deepEqual(system.job?.arguments, launchArguments)
  assert.equal(system.job?.state, "running")
  assert.deepEqual(await system.listenerPids(8010), [202])
})

test("restores the exact owning job when the build or test operation fails", async () => {
  assert.equal(typeof withLaunchdPortIsolation, "function")
  const system = fakeSystem({ exactJob: true })

  await assert.rejects(
    withLaunchdPortIsolation({
      system,
      allowedDefinition,
      operation: async () => {
        system.events.push("operation")
        throw new Error("build failed")
      },
    }),
    /build failed/,
  )

  assert.deepEqual(system.events, ["bootout", "operation", "submit"])
  assert.equal(system.job?.state, "running")
  assert.deepEqual(system.job?.arguments, launchArguments)
})

test("refuses a foreign port listener without booting out any launchd job", async () => {
  assert.equal(typeof withLaunchdPortIsolation, "function")
  const system = fakeSystem({ exactJob: true, listenerPid: 909 })

  await assert.rejects(
    withLaunchdPortIsolation({
      system,
      allowedDefinition,
      operation: async () => {
        system.events.push("operation")
      },
    }),
    /Refusing E2E.*not owned by the allowed launchd job/,
  )

  assert.deepEqual(system.events, [])
  assert.deepEqual(await system.listenerPids(8010), [909])
  assert.equal(system.job?.state, "running")
})

test("revalidates the exact job definition immediately before bootout", async () => {
  assert.equal(typeof withLaunchdPortIsolation, "function")
  const system = fakeSystem({ exactJob: true })
  const readJob = system.readJob.bind(system)
  let reads = 0
  system.readJob = async () => {
    reads += 1
    const job = await readJob()
    if (reads === 1 || !job) return job
    return { ...job, arguments: [program, "-lc", "changed-command"] }
  }

  await assert.rejects(
    withLaunchdPortIsolation({
      system,
      allowedDefinition,
      operation: async () => {
        system.events.push("operation")
      },
    }),
    /Refusing E2E.*not owned by the allowed launchd job/,
  )

  assert.deepEqual(system.events, [])
  assert.equal(system.job?.state, "running")
})

test("does not change an allowed loaded job that is not listening on port 8010", async () => {
  assert.equal(typeof withLaunchdPortIsolation, "function")
  const system = fakeSystem({ exactJob: true, listenerPid: null })

  await withLaunchdPortIsolation({
    system,
    allowedDefinition,
    operation: async () => {
      system.events.push("operation")
    },
  })

  assert.deepEqual(system.events, ["operation"])
  assert.equal(system.job?.pid, 101)
  assert.equal(system.job?.state, "running")
})

test("reports restoration failure even when the E2E operation succeeded", async () => {
  assert.equal(typeof withLaunchdPortIsolation, "function")
  const system = fakeSystem({ exactJob: true, restoreFails: true })

  await assert.rejects(
    withLaunchdPortIsolation({
      system,
      allowedDefinition,
      operation: async () => {
        system.events.push("operation")
      },
    }),
    /launchd API restoration failed.*submit failed/,
  )

  assert.deepEqual(system.events, ["bootout", "operation", "submit"])
  assert.equal(system.job, null)
})

test("SIGINT terminates the active child without exiting before cleanup", () => {
  assert.equal(typeof createSignalCoordinator, "function")
  const processEvents = new EventEmitter()
  let exitCalls = 0
  processEvents.exit = () => {
    exitCalls += 1
  }
  const child = new EventEmitter()
  let killedWith = null
  child.kill = (signal) => {
    killedWith = signal
    return true
  }
  const coordinator = createSignalCoordinator(processEvents)
  coordinator.attachChild(child)

  processEvents.emit("SIGINT")

  assert.equal(killedWith, "SIGINT")
  assert.equal(exitCalls, 0)
  assert.throws(() => coordinator.throwIfInterrupted(), /Interrupted by SIGINT/)
  assert.equal(coordinator.exitCode, 130)
  coordinator.dispose()
  assert.equal(processEvents.listenerCount("SIGINT"), 0)
  assert.equal(processEvents.listenerCount("SIGTERM"), 0)
})

test("SIGTERM terminates the active child without exiting before cleanup", () => {
  assert.equal(typeof createSignalCoordinator, "function")
  const processEvents = new EventEmitter()
  let exitCalls = 0
  processEvents.exit = () => {
    exitCalls += 1
  }
  const child = new EventEmitter()
  let killedWith = null
  child.kill = (signal) => {
    killedWith = signal
    return true
  }
  const coordinator = createSignalCoordinator(processEvents)
  coordinator.attachChild(child)

  processEvents.emit("SIGTERM")

  assert.equal(killedWith, "SIGTERM")
  assert.equal(exitCalls, 0)
  assert.throws(() => coordinator.throwIfInterrupted(), /Interrupted by SIGTERM/)
  assert.equal(coordinator.exitCode, 143)
  coordinator.dispose()
  assert.equal(processEvents.listenerCount("SIGINT"), 0)
  assert.equal(processEvents.listenerCount("SIGTERM"), 0)
})

function fakeSystem({
  exactJob = false,
  listenerPid = exactJob ? 101 : null,
  restoreFails = false,
} = {}) {
  const system = {
    events: [],
    job: exactJob
      ? {
          label,
          program,
          arguments: [...launchArguments],
          pid: 101,
          state: "running",
        }
      : null,
    listenerPid,
    async listenerPids() {
      return this.listenerPid === null ? [] : [this.listenerPid]
    },
    async readJob() {
      return this.job ? structuredClone(this.job) : null
    },
    async bootout() {
      this.events.push("bootout")
      this.job = null
      if (this.listenerPid === 101) this.listenerPid = null
    },
    async submit(snapshot) {
      this.events.push("submit")
      if (restoreFails) throw new Error("submit failed")
      this.job = {
        label: snapshot.label,
        program: snapshot.program,
        arguments: [...snapshot.arguments],
        pid: 202,
        state: "running",
      }
      this.listenerPid = 202
    },
    async healthStatus() {
      return 200
    },
    async wait() {},
  }
  return system
}
