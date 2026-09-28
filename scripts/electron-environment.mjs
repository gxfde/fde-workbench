const PASSTHROUGH_KEYS = [
  "PATH",
  "HOME",
  "TMPDIR",
  "LANG",
  "LC_ALL",
  "CI",
  "DISPLAY",
  "XDG_RUNTIME_DIR",
  "DBUS_SESSION_BUS_ADDRESS",
]

export function buildElectronEnvironment(source, apiUrl) {
  const result = {}
  for (const key of PASSTHROUGH_KEYS) {
    if (source[key]) result[key] = source[key]
  }
  result.FDE_DESKTOP_API_URL = apiUrl
  return result
}
