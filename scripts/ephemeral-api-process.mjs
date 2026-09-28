import { spawn } from "node:child_process"

const LOOPBACK_URL = /Running on http:\/\/127\.0\.0\.1:(\d+)/

export function startEphemeralApiProcess({ command, args, cwd, env, timeoutMs = 10_000 }) {
  return new Promise((resolveStart, rejectStart) => {
    const child = spawn(command, [...args, "--port", "0"], {
      cwd,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    })
    let settled = false
    const output = { stdout: "", stderr: "" }
    const timeout = setTimeout(() => fail("Ephemeral API process did not report its bound loopback port."), timeoutMs)

    function inspect(stream, chunk) {
      output[stream] = `${output[stream]}${chunk.toString("utf8")}`.slice(-2_048)
      const match = LOOPBACK_URL.exec(output[stream])
      if (!match || settled) return
      settled = true
      clearTimeout(timeout)
      child.off("error", onError)
      child.off("exit", onEarlyExit)
      resolveStart({ process: child, apiUrl: `http://127.0.0.1:${match[1]}` })
    }
    function onError() { fail("Ephemeral API process could not start.") }
    function onEarlyExit() { fail("Ephemeral API process exited before binding a port.") }
    function fail(message) {
      if (settled) return
      settled = true
      clearTimeout(timeout)
      if (child.exitCode === null) child.kill("SIGKILL")
      rejectStart(new Error(message))
    }

    child.stdout.on("data", (chunk) => inspect("stdout", chunk))
    child.stderr.on("data", (chunk) => inspect("stderr", chunk))
    child.once("error", onError)
    child.once("exit", onEarlyExit)
  })
}

export async function stopApiProcess(child, timeoutMs = 3_000) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return
  const exit = new Promise((resolveExit) => child.once("exit", resolveExit))
  child.kill("SIGTERM")
  let timeout
  const exitedGracefully = await Promise.race([
    exit.then(() => true),
    new Promise((resolveTimeout) => { timeout = setTimeout(() => resolveTimeout(false), timeoutMs) }),
  ])
  clearTimeout(timeout)
  if (!exitedGracefully && child.exitCode === null) {
    child.kill("SIGKILL")
    await exit
  }
}
