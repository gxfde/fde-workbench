import assert from "node:assert/strict"
import { existsSync, readFileSync } from "node:fs"
import { join } from "node:path"
import test from "node:test"
import { fileURLToPath } from "node:url"

const appRoot = new URL("../../", import.meta.url)
const appRootPath = fileURLToPath(appRoot)
const rootPackage = JSON.parse(readFileSync(new URL("package.json", appRoot), "utf8"))
const desktopPackage = JSON.parse(
  readFileSync(new URL("desktop/package.json", appRoot), "utf8"),
)
const packageLock = JSON.parse(
  readFileSync(new URL("package-lock.json", appRoot), "utf8"),
)

test("defines a reproducible ARM64 DMG package contract", () => {
  assert.equal(rootPackage.scripts["package:mac"], "npm --workspace desktop run package:mac")
  assert.equal(rootPackage.scripts["verify:mac"], "bash scripts/verify-dmg.sh")
  assert.match(desktopPackage.version, /^\d+\.\d+\.\d+$/)
  assert.equal(packageLock.packages.desktop.version, desktopPackage.version)
  assert.equal(desktopPackage.description, "FDE 项目工作台桌面客户端")
  assert.equal(desktopPackage.author, "FDE Workbench Contributors")
  assert.match(desktopPackage.scripts["package:mac"], /electron-builder/)
  assert.match(desktopPackage.scripts["package:mac"], /--arm64/)
  assert.equal(desktopPackage.devDependencies["electron-builder"], "26.15.3")
  assert.equal(desktopPackage.dependencies?.electron, undefined)
  assert.equal(desktopPackage.devDependencies.electron, "43.4.1")
  assert.equal(desktopPackage.dependencies["docx-preview"], "^0.4.0")
  assert.equal(desktopPackage.dependencies["react-markdown"], "^10.1.0")
  assert.equal(desktopPackage.dependencies["remark-gfm"], "^4.0.1")
  assert.equal(desktopPackage.devDependencies["electron-vite"], "5.0.0")
  assert.equal(desktopPackage.devDependencies.react, "19.2.8")
  assert.equal(desktopPackage.devDependencies["react-dom"], "19.2.8")

  assert.equal(desktopPackage.build.appId, "org.fdeworkbench.desktop")
  assert.equal(desktopPackage.build.productName, "FDE 工作台")
  assert.equal(desktopPackage.build.asar, true)
  assert.equal(desktopPackage.build.directories.output, "../release")
  assert.equal(desktopPackage.build.mac.identity, "-")
  assert.deepEqual(desktopPackage.build.mac.target, [
    { target: "dmg", arch: ["arm64"] },
  ])
  assert.equal(
    desktopPackage.build.extraMetadata.fdeApiUrl,
    "http://127.0.0.1:8010",
  )
  const rendererHtml = readFileSync(
    new URL("desktop/src/renderer/index.html", appRoot),
    "utf8",
  )
  assert.match(rendererHtml, /connect-src[^;]*http:\/\/127\.0\.0\.1:8010/)
  assert.equal(
    desktopPackage.build.artifactName,
    "FDE-Workbench-${version}-${arch}.${ext}",
  )

  assert.equal(
    existsSync(join(appRootPath, "desktop/build/icon.svg")),
    true,
  )
  assert.equal(
    existsSync(join(appRootPath, "desktop/scripts/generate-icon.sh")),
    true,
  )
  assert.equal(
    existsSync(join(appRootPath, "scripts/verify-dmg.sh")),
    true,
  )
})
