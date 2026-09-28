import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import test from "node:test"

import { findUnavailableRedisPort } from "../../scripts/unavailable-redis-port.mjs"

test("selects a local port that rejects a Redis connection", async () => {
  const port = await findUnavailableRedisPort()

  assert.equal(Number.isInteger(port), true)
  assert.equal(port > 0 && port <= 65_535, true)
  const probe = spawnSync(
    "redis-cli",
    ["-h", "127.0.0.1", "-p", String(port), "ping"],
    { stdio: "ignore", timeout: 1_000 },
  )
  assert.notEqual(probe.status, 0)
})
