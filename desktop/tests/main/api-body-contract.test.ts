// @vitest-environment node
/**
 * api body 契约静态闸（r29 排查实锤后的防复发钉）。
 *
 * 契约：renderer 调 apiRequest 时 body 传**对象**——主进程 api-ipc 的
 * serializeBody 统一 JSON.stringify 一次。若调用点预先 stringify（传字符串），
 * 会被二次编码，服务端 request.json 收到的是「JSON 字符串」而非对象 ⇒
 * 全部写操作 4xx 零落库（r29 实锤：DiscoveryPanel/AgentsConsole/
 * TranscriptDraftsPanel/HandoverPackagesPanel 共 7 处调用点全中，
 * 业务取证=审阅零写入；单测 mock apiRequest 曾把错误形状钉进断言）。
 *
 * 唯一例外 fde-web-bridge.ts：浏览器真 fetch 传输，无主进程序列化层，
 * stringify 是它的正确形态。
 */
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"

import { describe, expect, it } from "vitest"

import { walkSourceFiles } from "./source-walk"

// 扫描面＝renderer（apiRequest 调用方所在层）。main 侧 auth-ipc 等是自持
// fetch 的传输层（自己 stringify），不在本闸语义内。
const SRC_ROOT = join(fileURLToPath(new URL("../..", import.meta.url)), "src", "renderer")

function walk(dir: string): string[] {
  return walkSourceFiles(dir, (name) => /\.(ts|tsx)$/.test(name))
}

const normalize = (p: string) => p.replace(/\\/g, "/")

describe("api body 契约（对象进 apiRequest，序列化归传输层）", () => {
  it("renderer 除 fde-web-bridge（真 fetch 传输）外零 body: JSON.stringify", () => {
    const offenders = walk(SRC_ROOT).filter(
      (file) =>
        !normalize(file).endsWith("fde-web-bridge.ts") &&
        readFileSync(file, "utf-8").includes("body: JSON.stringify"),
    )
    expect(
      offenders,
      `以下调用点把 body 预先 stringify（api-ipc serializeBody 会二次编码，服务端将收到字符串而非对象，应直接传对象）:\n${offenders.join("\n")}`,
    ).toEqual([])
  })
})
