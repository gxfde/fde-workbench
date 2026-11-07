import { readFileSync } from "node:fs"
import { execFile } from "node:child_process"
import { join, resolve } from "node:path"
import { promisify } from "node:util"
import { pathToFileURL, fileURLToPath } from "node:url"

import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  safeStorage,
  session,
  shell,
  clipboard,
  type IpcMainInvokeEvent,
  type WebContents,
  type Session,
} from "electron"

import { IPC_CHANNELS } from "../shared/contracts"
import { PRODUCT_NAME } from "../shared/brand"
import { createApiRequestHandler, registerApiIpc } from "./api-ipc"
import { createAuthHandlers, registerAuthIpc } from "./auth-ipc"
import { createAuthStore } from "./auth-store"
import { createBridgeCaptureHandler, registerBridgeIpc } from "./bridge-capture"
import { executeDesktopLcsc } from './lcsc-runner'
import { buildCloseGuardDialogSpec, shouldDeferWindowClose } from "./close-guard"
import {
  DEVELOPMENT_API_URL,
  isAllowedRendererUrl,
  resolveApiBaseUrl,
} from "./config"

const rendererRoot = resolve(__dirname, "../renderer")
const packagedRendererUrl = pathToFileURL(join(rendererRoot, "index.html")).toString()
let mainWindow: BrowserWindow | null = null
let activeMutations = 0
// CR-034：一次性放行旗标——确认对话框选「仍然退出」后仅对紧随的那次关闭生效。
let allowMainWindowCloseOnce = false
// CR-034：确认框悬起标记——防悬框期间重复触发弹窗叠开。
let closeGuardDialogPending = false
let lcscSession: Session | null = null
let lcscWindow: BrowserWindow | null = null

function allowsLcscUrl(candidate: string): boolean {
  try {
    const url = new URL(candidate)
    return url.protocol === 'https:' && !url.username && !url.password &&
      ['www.szlcsc.com', 'so.szlcsc.com', 'item.szlcsc.com'].includes(url.hostname)
  } catch { return false }
}

function readPackagedApiUrl(): string | undefined {
  if (!app.isPackaged) {
    return undefined
  }
  try {
    const metadata = JSON.parse(
      readFileSync(join(app.getAppPath(), "package.json"), "utf8"),
    ) as { fdeApiUrl?: unknown }
    return typeof metadata.fdeApiUrl === "string" ? metadata.fdeApiUrl : undefined
  } catch {
    return undefined
  }
}

function allowsRendererUrl(candidate: string): boolean {
  if (app.isPackaged) {
    try { const url = new URL(candidate); return url.protocol === 'file:' && !url.search && fileURLToPath(url) === join(rendererRoot, 'index.html') }
    catch { return false }
  }
  return isAllowedRendererUrl(candidate, {
    isPackaged: app.isPackaged,
    rendererRoot,
    developmentUrl: process.env.ELECTRON_RENDERER_URL,
  })
}

function hardenWebContents(contents: WebContents): void {
  if (lcscSession && contents.session === lcscSession) {
    contents.setWindowOpenHandler(() => ({ action: 'deny' }))
    contents.on('will-navigate', (event, url) => { if (!allowsLcscUrl(url)) event.preventDefault() })
    contents.on('will-redirect', (event, url) => { if (!allowsLcscUrl(url)) event.preventDefault() })
    contents.on('will-attach-webview', (event) => event.preventDefault())
    return
  }
  contents.setWindowOpenHandler(() => ({ action: "deny" }))
  contents.on("will-navigate", (event, url) => {
    if (!allowsRendererUrl(url)) {
      event.preventDefault()
    }
  })
  contents.on("will-attach-webview", (event) => event.preventDefault())
}

function isTrustedSender(event: IpcMainInvokeEvent): boolean {
  return (
    event.sender === mainWindow?.webContents &&
    event.senderFrame !== null &&
    allowsRendererUrl(event.senderFrame.url)
  )
}

function createWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 640,
    show: false,
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webviewTag: false,
      allowRunningInsecureContent: false,
    },
  })
  window.once("ready-to-show", () => window.show())

  // CR-034：「在途写不退出」保护——仍有非 GET 请求在途（activeMutations>0）时
  // 拦下主窗口关闭，先问人：「等待完成」取消本次关闭，「仍然退出」一次性放行。
  // closeGuardDialogPending：确认框悬着时再点 X 只拦不再弹（防叠开多框）。
  window.on("close", (event) => {
    const allow = allowMainWindowCloseOnce
    allowMainWindowCloseOnce = false
    if (!shouldDeferWindowClose(activeMutations, allow)) return
    event.preventDefault()
    if (closeGuardDialogPending) return
    closeGuardDialogPending = true
    void dialog.showMessageBox(window, buildCloseGuardDialogSpec(activeMutations)).then(({ response }) => {
      if (response === 1) {
        allowMainWindowCloseOnce = true
        window.close()
      }
    }).finally(() => { closeGuardDialogPending = false })
  })

  const developmentUrl = process.env.ELECTRON_RENDERER_URL
  if (!app.isPackaged && developmentUrl) {
    void window.loadURL(developmentUrl)
  } else {
    void window.loadURL(packagedRendererUrl)
  }
  return window
}

async function start(): Promise<void> {
  await app.whenReady()
  lcscSession = session.fromPartition('fde-lcsc-browser')
  lcscSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
  lcscSession.setPermissionCheckHandler(() => false)

  session.defaultSession.setPermissionRequestHandler(
    (_webContents, _permission, callback) => callback(false),
  )
  session.defaultSession.setPermissionCheckHandler(() => false)

  const packagedApiUrl = readPackagedApiUrl()
  const runtimeApiUrl = process.env.FDE_DESKTOP_API_URL
  const apiBaseUrl = resolveApiBaseUrl(runtimeApiUrl ?? packagedApiUrl, {
    isPackaged: app.isPackaged,
    allowPackagedLocalApi:
      app.isPackaged &&
      runtimeApiUrl === undefined &&
      packagedApiUrl === DEVELOPMENT_API_URL,
  })
  const store = createAuthStore({
    safeStorage,
    userDataPath: app.getPath("userData"),
  })
  const handlers = createAuthHandlers({
    apiBaseUrl,
    fetch: globalThis.fetch,
    store,
    timeoutMs: 10_000,
  })
  registerAuthIpc({ ipcMain, handlers, isTrustedSender })
  const requestApi = createApiRequestHandler({ apiBaseUrl, fetch: globalThis.fetch, timeoutMs: 120_000 })
  registerApiIpc({
    ipcMain,
    request: async (input) => {
      const mutating = (input as { method?: string }).method !== 'GET'
      if (mutating) activeMutations++
      let result
      try {
        const candidate = input as { path?: string; method?: string; accessToken?: string; body?: unknown }
        result = candidate.path === '/api/v1/ai/lcsc-runs/desktop-execute' && candidate.method === 'POST' && typeof candidate.accessToken === 'string'
          ? await executeDesktopLcsc({ accessToken: candidate.accessToken, body: candidate.body }, requestApi, lcscSession!)
          : await requestApi(input)
      } finally { if (mutating) activeMutations-- }
      return result
    },
    isTrustedSender,
  })
  // P2 集成桥「立即采集」：采集器只能跑在 Windows 宿主（openfde CLI 是 Win 版
  // Node 工具），桌面端不复制采集逻辑，只触发宿主计划任务，与 4 小时周期同路径。
  const execFileUtf8 = promisify(execFile)
  registerBridgeIpc({
    ipcMain,
    capture: createBridgeCaptureHandler({
      execFile: (file, args, options) =>
        execFileUtf8(file, args, { ...options, encoding: "utf8" }),
      taskName: process.env.FDE_BRIDGE_TASK_NAME || "FDE-Bridge-Poll",
      timeoutMs: 15_000,
    }),
    isTrustedSender,
  })
  // F3：LCSC 桌面 IPC 默认关闭——渲染端只有在其服务端工具清单确实包含
  // lcsc_search（即账号具备 lcsc.browse 能力，F1 门槛）时才打开开关；
  // 与 weixin_enabled 一致的「默认关、显式开」语义，不删功能只降暴露面。
  let lcscIpcEnabled = false
  ipcMain.handle(IPC_CHANNELS.appSetLcscEnabled, (event, enabled: unknown) => {
    if (!isTrustedSender(event) || typeof enabled !== "boolean") {
      throw new Error("Unauthorized IPC sender or payload.")
    }
    lcscIpcEnabled = enabled
  })
  function requireLcscEnabled(): void {
    if (!lcscIpcEnabled) throw new Error("立创商城集成未启用。")
  }
  ipcMain.handle(IPC_CHANNELS.appVersion, (event) => {
    if (!isTrustedSender(event)) {
      throw new Error("Unauthorized IPC sender.")
    }
    return app.getVersion()
  })
  ipcMain.handle(IPC_CHANNELS.appOpenLcscBrowser, async (event, url: unknown) => {
    requireLcscEnabled()
    if (!isTrustedSender(event) || typeof url !== 'string' || !allowsLcscUrl(url)) {
      throw new Error('只允许打开立创商城公开页面。')
    }
    if (!lcscWindow || lcscWindow.isDestroyed()) {
      lcscWindow = new BrowserWindow({width: 1180, height: 820, minWidth: 800, minHeight: 600,
        title: `立创商城 · ${PRODUCT_NAME}内置浏览器`, webPreferences: {
          partition: 'fde-lcsc-browser', contextIsolation: true, sandbox: true,
          nodeIntegration: false, webviewTag: false, allowRunningInsecureContent: false,
        }})
      lcscWindow.on('closed', () => { lcscWindow = null })
    }
    await lcscWindow.loadURL(url)
    lcscWindow.show()
    lcscWindow.focus()
  })
  ipcMain.handle(IPC_CHANNELS.appShowLcscDownload, (event, filename: unknown) => {
    requireLcscEnabled()
    if (!isTrustedSender(event) || typeof filename !== 'string' || !/^[\p{L}\p{N}._-]+\.pdf$/u.test(filename) || filename.includes('..') || filename.length > 120) throw new Error('文件名无效。')
    shell.showItemInFolder(join(app.getPath('downloads'), 'FDE规格书', filename))
  })
  ipcMain.handle(IPC_CHANNELS.appCopyLcscRunId, (event, id: unknown) => {
    requireLcscEnabled()
    if (!isTrustedSender(event) || typeof id !== 'string' || !/^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(id)) throw new Error('执行记录 ID 无效。')
    clipboard.writeText(id)
  })

  mainWindow = createWindow()
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      mainWindow = createWindow()
    }
  })
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit()
  }
})

app.on("web-contents-created", (_event, contents) => {
  hardenWebContents(contents)
})

void start().catch(() => {
  app.exit(1)
})
