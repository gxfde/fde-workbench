import path from "node:path"
import { fileURLToPath } from "node:url"

import { defineConfig } from "vite"

// 浏览器发行形态：与 electron-vite 共用同一份 renderer 源码，但入口换成 web.html。
// 生产产物只含同源 /api 请求，反代由 Nginx 承担；dev/preview 的代理仅用于本地联调。
const desktopRoot = path.dirname(fileURLToPath(import.meta.url))
const rendererRoot = path.resolve(desktopRoot, "src", "renderer")
const apiTarget = process.env.FDE_WEB_API_TARGET ?? "http://127.0.0.1:8010"
const proxy = { "/api": { target: apiTarget, changeOrigin: true } }

export default defineConfig({
  root: rendererRoot,
  esbuild: { jsx: "automatic" },
  // electron-vite 内置 @renderer 别名；Web 构建须显式补上，否则源码 import 全部失效。
  resolve: { alias: { "@renderer": path.resolve(rendererRoot, "src") } },
  server: { host: "127.0.0.1", port: 5199, strictPort: true, proxy },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true, proxy },
  build: {
    outDir: path.resolve(desktopRoot, "web-dist"),
    emptyOutDir: true,
    rollupOptions: { input: path.resolve(rendererRoot, "web.html") },
  },
})
