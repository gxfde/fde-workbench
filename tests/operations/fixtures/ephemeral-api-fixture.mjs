import http from "node:http"

const portIndex = process.argv.indexOf("--port")
if (portIndex < 0 || process.argv[portIndex + 1] !== "0") throw new Error("fixture requires --port 0")

const server = http.createServer((_request, response) => {
  response.writeHead(200, { "Content-Type": "application/json" })
  response.end('{"status":"ok"}')
})
server.listen(0, "127.0.0.1", () => {
  const address = server.address()
  if (!address || typeof address === "string") throw new Error("fixture did not bind TCP")
  const startup = `Running on http://127.0.0.1:${address.port}\n`
  if (process.argv.includes("--fragment-startup")) {
    const midpoint = Math.floor(startup.length / 2)
    process.stderr.write(startup.slice(0, midpoint))
    setImmediate(() => process.stderr.write(startup.slice(midpoint)))
  } else {
    process.stderr.write(startup)
  }
})
process.on("SIGTERM", () => {
  server.close(() => process.exit(0))
  server.closeAllConnections()
})
