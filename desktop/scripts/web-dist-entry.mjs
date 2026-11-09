// Web 发行产物使用 web.html 作为源码入口（与 Electron 的 index.html 并存）。
// 静态托管与 vite preview 默认查找 index.html，构建后把入口规范成 index.html，
// 避免 Nginx / CDN 增加特例配置。HTML 内资源引用均为绝对路径，重命名不受影响。
import { existsSync, renameSync } from "node:fs"
import { resolve } from "node:path"

const outDir = resolve(process.cwd(), "web-dist")
const from = resolve(outDir, "web.html")
const to = resolve(outDir, "index.html")

if (!existsSync(from)) {
  if (existsSync(to)) process.exit(0) // 幂等：重复执行不报错
  console.error(`[web-dist-entry] missing ${from}; run vite build first`)
  process.exit(1)
}

renameSync(from, to)
console.log(`[web-dist-entry] ${from} -> ${to}`)
