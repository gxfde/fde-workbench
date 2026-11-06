import { readdirSync, statSync } from "node:fs"
import { join } from "node:path"

/**
 * 构建产物目录：这些目录里的文件是打包/转译后的产物副本
 * （含首帧占位产品名、编译后 CSS 等），不是源码面。
 *
 * 若不排除，任何一次本地构建留在源码树下的输出目录，都会让静态文本闸
 * （红线①产品名单一来源、设计令牌一致性）假红——实测
 * `desktop/src/renderer/out/verify/renderer/index.html` 会命中红线①。
 *
 * 这些目录名均已在 .gitignore 中，绝不入库，因此排除它们
 * 不放宽任何源码约束：真实源码（ts/tsx/css/html）仍 100% 扫描。
 */
export const BUILD_ARTIFACT_DIRS = new Set([
  "out",
  "dist",
  "node_modules",
  ".vite",
  "coverage",
  "release",
])

/**
 * 递归收集源码文件，跳过构建产物目录。
 *
 * @param dir      起始目录
 * @param matchExt 文件名后缀谓词（如 `".tsx"` / `".css"`）
 */
export function walkSourceFiles(dir: string, matchExt: (name: string) => boolean): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      if (BUILD_ARTIFACT_DIRS.has(entry)) continue
      out.push(...walkSourceFiles(full, matchExt))
    } else if (matchExt(entry)) {
      out.push(full)
    }
  }
  return out
}
