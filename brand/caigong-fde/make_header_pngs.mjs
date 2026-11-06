import { chromium } from 'playwright';
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

// docx 页眉用小图形标：mono-dark（全石墨，印刷安全）与彩色版，透明底 PNG
const dir = dirname(fileURLToPath(import.meta.url));
const browser = await chromium.launch();

const marks = {
  'hdr-mark-mono.png': { file: 'caigong-fde-mark.svg', recolor: '#14181C' },
  'hdr-mark-color.png': { file: 'caigong-fde-mark.svg', recolor: null },
};

for (const [out, spec] of Object.entries(marks)) {
  let svg = readFileSync(join(dir, spec.file), 'utf-8');
  if (spec.recolor) {
    // 单色版：黑环与金段全部改为石墨黑
    svg = svg.replaceAll('#E8A33D', spec.recolor);
  }
  // 页眉高度约 28-32px @2x = 64px 输出；宽按图形宽高比（图形本身 200x200 含负空间，实际视觉宽略大，用 viewBox 等比）
  const size = 64;
  const sized = svg.replace(/width="[^"]*"/, `width="${size}"`).replace(/height="[^"]*"/, `height="${size}"`);
  const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 2 });
  await page.setContent(
    `<html><body style="margin:0;width:${size}px;height:${size}px;background:transparent;display:flex;align-items:center;justify-content:center">
      ${sized}
    </body></html>`
  );
  await page.waitForTimeout(200);
  await page.screenshot({ path: join(dir, out), omitBackground: true });
  await page.close();
  console.log('wrote', out);
}
await browser.close();
