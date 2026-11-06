// @vitest-environment node
/**
 * 红线① 防复发静态闸（goal-c CR-001）：产品名只允许两处单点来源——
 * 桌面端 `desktop/src/shared/brand.ts`（PRODUCT_NAME 等常量）与服务端
 * `server/src/fde_api/config.py` 的 `DEFAULT_PRODUCT_NAME`。本测试断言
 * desktop/src 的源码面（ts/tsx/html）除 brand.ts 本体外，零处出现产品全名
 * 字面量——改名只改共享 brand 模块，不再散点同步。
 *
 * 注：`styles.css:2` 注释与 logo svg 的 `<title>` 为资产元数据非界面文案，
 * 不在扫描面内（与台账 CR-001「驳回/观察记录」口径一致）。
 */
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"

import { describe, expect, it } from "vitest"

import { walkSourceFiles } from "./source-walk"

const SRC_ROOT = join(fileURLToPath(new URL("../..", import.meta.url)), "src")
const PRODUCT_FULL_NAME = "蔡工FDE智能交付系统"

function walk(dir: string): string[] {
  // 排除构建产物目录（out/dist/build 等），避免本地打包残留让本闸假红；
  // 真实源码仍全量扫描，约束不放宽。
  return walkSourceFiles(dir, (name) => /\.(ts|tsx|html)$/.test(name))
}

const normalize = (p: string) => p.replace(/\\/g, "/")

describe("红线① 产品名单一来源（桌面侧）", () => {
  it("desktop/src 除 shared/brand.ts 外零硬编码产品全名", () => {
    const offenders = walk(SRC_ROOT).filter(
      (file) =>
        !normalize(file).endsWith("shared/brand.ts") &&
        readFileSync(file, "utf-8").includes(PRODUCT_FULL_NAME),
    )
    expect(offenders, `以下文件硬编码了产品全名（应 import shared/brand.ts）:\n${offenders.join("\n")}`).toEqual([])
  })

  it("shared/brand.ts 确实导出 PRODUCT_NAME 常量（单点来源存在）", () => {
    const brand = readFileSync(join(SRC_ROOT, "shared", "brand.ts"), "utf-8")
    expect(brand).toContain("export const PRODUCT_NAME")
    expect(brand).toContain(PRODUCT_FULL_NAME)
  })
})
