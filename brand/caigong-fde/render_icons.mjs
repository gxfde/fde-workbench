import { chromium } from 'playwright';
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const dir = dirname(fileURLToPath(import.meta.url));
const browser = await chromium.launch();

// 图形标（透明底，黑+金）→ app icon 源
const markSvg = readFileSync(join(dir, 'caigong-fde-mark.svg'), 'utf-8');
const markInvSvg = readFileSync(join(dir, 'caigong-fde-mark-inverse.svg'), 'utf-8');

// 去掉 SVG 自带的 width/height 属性，让 CSS 尺寸生效
function sized(svg, px) {
  return svg
    .replace(/width="[^"]*"/, `width="${px}"`)
    .replace(/height="[^"]*"/, `height="${px}"`);
}

async function shoot(svg, size, out, bg, pad, color) {
  const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
  const inner = size - pad * 2;
  await page.setContent(
    `<html><body style="margin:0;width:${size}px;height:${size}px;background:${bg};display:flex;align-items:center;justify-content:center">
      <div style="width:${inner}px;height:${inner}px;display:flex;align-items:center;justify-content:center">
        ${sized(svg, inner)}
      </div></body></html>`
  );
  await page.waitForTimeout(200);
  await page.screenshot({ path: out, omitBackground: bg === 'transparent' });
  await page.close();
  console.log('wrote', out);
}

// 1) 应用图标：深底圆角方 + 反白图形标（1024），图形占约 62%
{
  const page = await browser.newPage({ viewport: { width: 1024, height: 1024 }, deviceScaleFactor: 1 });
  await page.setContent(
    `<html><body style="margin:0;width:1024px;height:1024px;background:#14181C">
      <div style="width:1024px;height:1024px;border-radius:228px;overflow:hidden;display:flex;align-items:center;justify-content:center;background:#14181C">
        <div style="width:640px;height:640px;display:flex;align-items:center;justify-content:center">
          ${sized(markInvSvg, 640)}
        </div>
      </div></body></html>`
  );
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(dir, 'app-icon-1024.png') });
  await page.close();
  console.log('wrote app-icon-1024.png');
}

// 2) 透明底图形标 1024（黑白印刷/资料用）
await shoot(markSvg, 1024, join(dir, 'mark-transparent-1024.png'), 'transparent', 40);

// 3) favicon 32
await shoot(markInvSvg, 32, join(dir, 'favicon-32.png'), '#14181C', 3);

await browser.close();
