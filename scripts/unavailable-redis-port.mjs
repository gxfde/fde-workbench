import { spawnSync } from "node:child_process"
import { createServer } from "node:net"

export async function findUnavailableRedisPort() {
  const server = createServer()
  const port = await new Promise((resolvePort, rejectPort) => {
    server.once("error", rejectPort)
    server.listen(0, "127.0.0.1", () => {
      const address = server.address()
      if (!address || typeof address === "string") {
        rejectPort(new Error("Could not resolve an ephemeral local port."))
        return
      }
      resolvePort(address.port)
    })
  })
  await new Promise((resolveClose, rejectClose) => {
    server.close((error) => error ? rejectClose(error) : resolveClose())
  })

  const probe = spawnSync(
    "redis-cli",
    ["-h", "127.0.0.1", "-p", String(port), "ping"],
    { stdio: "ignore", timeout: 1_000 },
  )
  if (probe.error) {
    throw new Error("redis-cli is required to verify the unavailable Redis port.", {
      cause: probe.error,
    })
  }
  if (probe.status === 0) {
    throw new Error("The selected Redis degradation port unexpectedly accepted a ping.")
  }
  return port
}
