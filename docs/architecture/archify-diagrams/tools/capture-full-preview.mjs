#!/usr/bin/env node
// 完整整图预览捕获：preview.png 必须覆盖整页。
//
// 背景（2026-11-08 截断事故）：archify visual-check 的截图是固定视口实拍
// （1440×900 等，captureBeyondViewport:false），高图（sequence/architecture/
// workflow）的 preview.png 只拍到首屏，「整个图不完整」。本脚本复用 archify
// 的 Chrome/CDP 栈：先由 inspect() 装载页面并等字体/布局稳定，再用
// Page.captureScreenshot{captureBeyondViewport:true} 实拍整页，保证预览含全部内容。
//
// 用法：
//   node capture-full-preview.mjs <diagram.html> [more.html ...] [--width 1440] [--theme light]
//
// 依赖：本机已安装 archify（ARCHIFY_HOME 可覆盖，默认 ~/.agents/skills/archify/
// archify）；浏览器解析同 archify 约定（ARCHIFY_CHROME，本机为 Edge）。
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

function parseArgs(argv) {
  const options = { width: 1440, theme: 'light' };
  const html = [];
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === '--width') options.width = Number(argv[++index]);
    else if (value === '--theme') options.theme = argv[++index];
    else html.push(value);
  }
  if (!html.length || !Number.isFinite(options.width) || options.width < 320) {
    console.error('usage: node capture-full-preview.mjs <diagram.html> [...] [--width 1440] [--theme light]');
    process.exit(2);
  }
  return { options, html };
}

function pngSize(buffer) {
  // PNG IHDR: width @16, height @20 (big-endian)
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

const { options, html } = parseArgs(process.argv.slice(2));
const archifyHome = process.env.ARCHIFY_HOME
  ?? path.join(os.homedir(), '.agents', 'skills', 'archify', 'archify');
const visualCheckUrl = pathToFileURL(path.join(archifyHome, 'bin', 'visual-check.mjs')).href;
const { findChrome, ChromeVisualBrowser } = await import(visualCheckUrl);

const chromePath = findChrome({ env: process.env, platform: process.platform });
const browser = new ChromeVisualBrowser(chromePath);
let failures = 0;
try {
  for (const htmlPath of html) {
    const artifactPath = path.resolve(htmlPath);
    const outPath = path.join(path.dirname(artifactPath), 'preview.png');
    // inspect() 装载页面、设 data-motion=still、等字体与自适应布局稳定，并回测量。
    const metrics = await browser.inspect({
      artifactPath,
      width: options.width,
      height: 900,
      theme: options.theme,
    });
    const pageWidth = Math.ceil(metrics.scrollWidth);
    const pageHeight = Math.ceil(metrics.scrollHeight);
    // 整页实拍：captureBeyondViewport 绕开窗口表面限制（headless 下窗口表面
    // 恒为启动尺寸，emulation 只改布局不改表面）。
    const sessionId = await browser.sessionPromise;
    const capture = await browser.cdp.send('Page.captureScreenshot', {
      format: 'png',
      fromSurface: true,
      captureBeyondViewport: true,
    }, sessionId, 60000);
    if (!capture.data) throw new Error(`${htmlPath}: Chrome returned an empty screenshot.`);
    fs.writeFileSync(outPath, Buffer.from(capture.data, 'base64'));
    const size = pngSize(fs.readFileSync(outPath));
    const complete = size.width === pageWidth && size.height >= pageHeight;
    console.log(`${complete ? 'PASS' : 'FAIL'} ${htmlPath} -> preview.png ${size.width}x${size.height} (page ${pageWidth}x${pageHeight})`);
    if (!complete) failures += 1;
  }
} finally {
  browser.close();
}
process.exit(failures ? 1 : 0);
