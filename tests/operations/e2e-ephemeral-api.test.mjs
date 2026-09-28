import assert from "node:assert/strict"
import { once } from "node:events"
import { resolve } from "node:path"
import test from "node:test"

import { startEphemeralApiProcess, stopApiProcess } from "../../scripts/ephemeral-api-process.mjs"

const fixture = resolve(import.meta.dirname, "fixtures/ephemeral-api-fixture.mjs")

test("two concurrent E2E API processes bind distinct OS-assigned ports", async () => {
  const processes = await Promise.all([
    startEphemeralApiProcess({ command: process.execPath, args: [fixture, "--fragment-startup"], env: process.env }),
    startEphemeralApiProcess({ command: process.execPath, args: [fixture], env: process.env }),
  ])
  try {
    assert.notEqual(processes[0].apiUrl, processes[1].apiUrl)
    const responses = await Promise.all(processes.map(({ apiUrl }) => fetch(apiUrl)))
    assert.deepEqual(responses.map((response) => response.status), [200, 200])
  } finally {
    await Promise.all(processes.map(({ process: child }) => stopApiProcess(child)))
  }
})

test("cleanup is idempotent after an API child was already terminated by signal", async () => {
  const started = await startEphemeralApiProcess({ command: process.execPath, args: [fixture], env: process.env })
  started.process.kill("SIGKILL")
  await once(started.process, "exit")
  await stopApiProcess(started.process)
  assert.equal(started.process.signalCode, "SIGKILL")
})
