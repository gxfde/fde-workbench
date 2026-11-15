#!/usr/bin/env node
/**
 * release-version.mjs —— 打包轮次版本注入（单一真身：仓库根 RELEASE-COUNTER）
 *
 * 解决的问题：desktop/package.json 的 version 只随「发布列车」手动升（0.1.0→0.2.0→0.3.0），
 * 日常打包轮次（r20/r24/…/r45）只体现在文件夹名，应用内 app.getVersion()/侧栏/exe 元数据
 * 全都看不到轮次。本脚本把轮次变成版本后缀：0.3.0 + r46 → "0.3.0-r46"。
 *
 * 用法：
 *   node scripts/release-version.mjs bump            # 打包轮次 +1，三源同步注入（RELEASE-COUNTER +
 *                                                    # desktop/package.json + fde-web-bridge.ts，打包前调）
 *   node scripts/release-version.mjs show            # 只读打印当前轮次与注入后版本
 *   node scripts/release-version.mjs train <part>    # 发布列车升版：part ∈ major|minor|patch，三源同步
 *                                                    # （desktop/package.json + fde-web-bridge.ts + server/pyproject.toml），
 *                                                    # 轮次续接不清零；升完自行走 PR + tag v<新版>
 *
 * 规则（2026-11-13 蔡工拍板，2026-11-14 补齐 CR-058 web 桥第三源同步）：
 *   - 版本格式 = 列车版本 + "-rN"；列车版本取注入前 package.json 的 version（剥掉旧 -rN 后缀）。
 *   - 轮次跨列车**续接**不清零（r1~r45 历史连续，好追溯）。
 *   - RELEASE-COUNTER 不存在时从 1 起算（首次使用自举；不静默猜历史值）。
 *   - bump / train 均同步更新 desktop/src/renderer/src/fde-web-bridge.ts 的 `${version}-web` 字面量
 *     （对齐 CR-058 web-bridge-version-parity.test.ts 静态闸，防止每次 bump CI desktop 必红）。
 *   - train 模式同步改三文件（desktop/package.json + fde-web-bridge.ts + server/pyproject.toml）；
 *     README 徽章与 AGENTS 口径行属文档口径，升版轮人工顺带改。
 *
 * 打包流程（Windows 便携版示例）：
 *   node scripts/release-version.mjs bump
 *   cd desktop && npm run build && npx electron-builder --win dir --x64
 *   # 产物目录名可含轮次：release/蔡工FDE-<version>-便携版-r<N> 与注入版本天然一致
 */

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const counterPath = resolve(repoRoot, "RELEASE-COUNTER");
const pkgPath = resolve(repoRoot, "desktop", "package.json");
const webBridgePath = resolve(
  repoRoot,
  "desktop",
  "src",
  "renderer",
  "src",
  "fde-web-bridge.ts",
);
const pyprojectPath = resolve(repoRoot, "server", "pyproject.toml");

function readCounter() {
  if (!existsSync(counterPath)) return null;
  const raw = readFileSync(counterPath, "utf8").trim();
  if (!/^\d+$/.test(raw)) {
    throw new Error(`RELEASE-COUNTER 内容非法（须为纯数字）：${JSON.stringify(raw)}`);
  }
  return Number.parseInt(raw, 10);
}

function writeCounter(value) {
  // 无 BOM、LF 结尾；数字唯一真身，人类可直接改
  writeFileSync(counterPath, `${value}\n`, "utf8");
}

function syncWebBridgeVersion(version) {
  const raw = readFileSync(webBridgePath, "utf8");
  const pattern = /version:\s*async\s*\(\)\s*=>\s*"[^"]+-web"/;
  if (!pattern.test(raw)) {
    throw new Error(
      "desktop/src/renderer/src/fde-web-bridge.ts 未找到 version 字面量锚点，中止。",
    );
  }
  const nextRaw = raw.replace(pattern, `version: async () => "${version}-web"`);
  const changed = nextRaw !== raw;
  if (changed) {
    writeFileSync(webBridgePath, nextRaw, "utf8");
  }
  return changed;
}

function injectVersion(trainVersion, release) {
  const pkg = JSON.parse(readFileSync(pkgPath, "utf8"));
  const base = trainVersion ?? String(pkg.version).replace(/-r\d+$/, "");
  if (!/^\d+\.\d+\.\d+$/.test(base)) {
    throw new Error(`desktop/package.json 版本不是 semver 三段式：${JSON.stringify(base)}`);
  }
  const next = `${base}-r${release}`;
  const pkgChanged = pkg.version !== next;
  if (pkgChanged) {
    pkg.version = next;
    // 2 缩进 + 结尾换行，与仓库现有 package.json 风格一致
    writeFileSync(pkgPath, `${JSON.stringify(pkg, null, 2)}\n`, "utf8");
  }
  const webBridgeChanged = syncWebBridgeVersion(next);
  return { pkg, next, changed: pkgChanged || webBridgeChanged };
}

const mode = process.argv[2] ?? "show";

if (mode === "show") {
  const current = readCounter();
  const pkg = JSON.parse(readFileSync(pkgPath, "utf8"));
  const base = String(pkg.version).replace(/-r\d+$/, "");
  console.log(
    current === null
      ? `RELEASE-COUNTER 不存在（首次打包将自举为 r1）；列车版本 ${base}`
      : `当前轮次 r${current}；下次打包将注入 ${base}-r${current + 1}`,
  );
} else if (mode === "bump") {
  const current = readCounter();
  const release = (current ?? 0) + 1;
  const { next, changed } = injectVersion(null, release);
  writeCounter(release);
  console.log(
    `已注入 ${next} 到 desktop/package.json 与 fde-web-bridge.ts${changed ? "" : "（值未变化）"}；RELEASE-COUNTER=${release}`,
  );
} else if (mode === "train") {
  const part = process.argv[3];
  if (part !== "major" && part !== "minor" && part !== "patch") {
    console.error("用法：node scripts/release-version.mjs train <major|minor|patch>");
    process.exit(2);
  }
  const pkg = JSON.parse(readFileSync(pkgPath, "utf8"));
  const base = String(pkg.version).replace(/-r\d+$/, "");
  const [maj, min, pat] = base.split(".").map((n) => Number.parseInt(n, 10));
  const bumped =
    part === "major"
      ? `${maj + 1}.0.0`
      : part === "minor"
        ? `${maj}.${min + 1}.0`
        : `${maj}.${min}.${pat + 1}`;
  // 三文件同步：desktop/package.json（剥旧 -rN 后缀落纯净列车版，下一次 bump 再注入）+
  // desktop/src/renderer/src/fde-web-bridge.ts + server/pyproject.toml（列车口径，永不带 -rN 后缀）。
  const pkgRaw = readFileSync(pkgPath, "utf8");
  const pkgNext = pkgRaw.replace(
    new RegExp(`("version"\\s*:\\s*")${base.replace(/\./g, "\\.")}(-r\\d+)?"`),
    `$1${bumped}"`,
  );
  if (pkgNext === pkgRaw) throw new Error("desktop/package.json version 替换未命中，中止。");
  writeFileSync(pkgPath, pkgNext, "utf8");
  syncWebBridgeVersion(bumped);
  const pyRaw = readFileSync(pyprojectPath, "utf8");
  const pyNext = pyRaw.replace(
    new RegExp(`^(version\\s*=\\s*")${base.replace(/\./g, "\\.")}"`, "m"),
    `$1${bumped}"`,
  );
  if (pyNext === pyRaw) throw new Error("server/pyproject.toml version 替换未命中，中止。");
  writeFileSync(pyprojectPath, pyNext, "utf8");
  const current = readCounter();
  console.log(
    `发布列车 ${base} → ${bumped}：desktop/package.json、fde-web-bridge.ts 与 server/pyproject.toml 已同步；` +
      `轮次续接（${current === null ? "未初始化" : `r${current}`}），下次打包注入 ${bumped}-r${(current ?? 0) + 1}。` +
      `README 徽章与 AGENTS 口径行请随升版 PR 人工顺带改；tag v${bumped} 打在 fork。`,
  );
} else {
  console.error("用法：node scripts/release-version.mjs [bump|show|train <major|minor|patch>]");
  process.exit(2);
}
