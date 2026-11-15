// goal-crv-fix2 批 R7（QR-109/110/111/113）源码级行为钉。
//
// index.ts / lcsc-runner.ts 的闸与复验逻辑深居 Electron 主进程闭包
// （回调运行时求值，直接单测需整窗装配），按 test_crv_batch_e 的
// inspect.getsource 先例以**源码锚钉**守护四项意图↔实现接线：
// 任一锚被移除/改名即红（防再漂移）；行为正确性由 typecheck＋asar
// 字节双证＋真机验收共同兜底。
import { readFileSync } from "node:fs"
import { join } from "node:path"

import { describe, expect, it } from "vitest"

import { DENIED_ACTION_SOURCE } from "../../src/main/lcsc-browser-ui"

const ROOT = join(__dirname, "../..")

function readMain(rel: string): string {
  return readFileSync(join(ROOT, "src/main", rel), "utf8")
}

describe("QR-109 主窗口 will-redirect 守卫（30x 重定向同尺拦截）", () => {
  const source = readMain("index.ts")

  it("主窗口分支 will-navigate 与 will-redirect 成对注册", () => {
    const branch = source.slice(
      source.indexOf('contents.on("will-navigate"'),
      source.indexOf('contents.on("will-attach-webview"'),
    )
    expect(branch).toContain('contents.on("will-navigate"')
    expect(branch).toContain('contents.on("will-redirect"')
    expect(branch.match(/allowsRendererUrl\(url\)/g)?.length).toBeGreaterThanOrEqual(2)
  })
})

describe("QR-110 desktop-execute 桥拦截受 lcscIpcEnabled 默认关闸", () => {
  const source = readMain("index.ts")

  it("desktop-execute 分支在 executeDesktopLcsc 前调用 requireLcscEnabled", () => {
    const anchor = source.indexOf("'/api/v1/ai/lcsc-runs/desktop-execute'")
    const call = source.indexOf("requireLcscEnabled()", anchor)
    const execute = source.indexOf("executeDesktopLcsc(", anchor)
    expect(call).toBeGreaterThan(-1)
    expect(execute).toBeGreaterThan(call)
  })

  it("lcscIpcEnabled 声明先于 registerApiIpc（TDZ 安全）", () => {
    expect(source.indexOf("let lcscIpcEnabled = false")).toBeLessThan(
      source.indexOf("registerApiIpc({"),
    )
  })

  it("其余 LCSC 面仍走同一 requireLcscEnabled 单点", () => {
    expect(source.match(/requireLcscEnabled\(\)/g)?.length).toBeGreaterThanOrEqual(4)
  })
})

describe("QR-111 点击前 denied 复验（单一真身双处内插）", () => {
  it("DENIED_ACTION_SOURCE 导出与 OBSERVE_BROWSER 内联字面逐位一致", () => {
    const observe = readMain("lcsc-browser-ui.ts")
    expect(observe).toContain("export const DENIED_ACTION_SOURCE")
    expect(observe).toContain("new RegExp(${JSON.stringify(DENIED_ACTION_SOURCE)},'i')")
  })

  it("runner 点击分支复验文案/aria-label/title 与 form 归属", () => {
    const runner = readMain("lcsc-runner.ts")
    expect(runner).toContain("DENIED_ACTION_SOURCE")
    const clickBranch = runner.slice(runner.indexOf("控件语义复核未通过"))
    expect(clickBranch).toContain("e.closest('form')")
    expect(clickBranch).toContain("e.click()")
  })
})

describe("QR-113 AgentsConsole 去顶层 error 整页早返回", () => {
  const source = readFileSync(
    join(ROOT, "src/renderer/src/agents/AgentsConsole.tsx"),
    "utf8",
  )

  it("不再存在顶层 if (error) return 整页坍缩", () => {
    expect(source).not.toContain("if (error) return")
  })

  it("页内错误条带重试按钮（load 可重入）", () => {
    expect(source).toContain("{error && (")
    expect(source).toContain("void load()")
  })
})

describe("QR-111 denied 名单单一真身回归（字面守护）", () => {
  it("导出常量含购物车/支付/下载等敏感词（与观察面同尺）", () => {
    for (const term of ["登录", "购物车", "支付", "下载", "checkout", "cart"]) {
      expect(DENIED_ACTION_SOURCE).toContain(term)
    }
  })
})
