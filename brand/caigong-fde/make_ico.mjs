import { chromium } from 'playwright';
import { readFileSync, writeFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const dir = dirname(fileURLToPath(import.meta.url));
const markInv = readFileSync(join(dir, 'caigong-fde-mark-inverse.svg'), 'utf-8');
const sized = (s, px) => s.replace(/width="[^"]*"/, `width="${px}"`).replace(/height="[^"]*"/, `height="${px}"`);
const browser = await chromium.launch();

const sizes = [16, 24, 32, 48, 64, 128, 256];
const pngs = [];
for (const size of sizes) {
  const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
  const pad = Math.max(1, Math.round(size * 0.09));
  const inner = size - pad * 2;
  await page.setContent(
    `<html><body style="margin:0;width:${size}px;height:${size}px;background:#14181C;border-radius:${Math.round(size*0.19)}px;overflow:hidden;display:flex;align-items:center;justify-content:center">
      <div style="width:${inner}px;height:${inner}px;display:flex;align-items:center;justify-content:center">${sized(markInv, inner)}</div>
    </body></html>`
  );
  await page.waitForTimeout(120);
  const buf = await page.screenshot();
  pngs.push({ size, buf });
  await page.close();
}
await browser.close();

// 组装 ICO（内嵌 PNG）
const count = pngs.length;
const header = Buffer.alloc(6);
header.writeUInt16LE(0, 0);
header.writeUInt16LE(1, 2);
header.writeUInt16LE(count, 4);
const dirEntries = [];
let offset = 6 + count * 16;
for (const { size, buf } of pngs) {
  const e = Buffer.alloc(16);
  e.writeUInt8(size >= 256 ? 0 : size, 0);
  e.writeUInt8(size >= 256 ? 0 : size, 1);
  e.writeUInt8(0, 2);
  e.writeUInt8(0, 3);
  e.writeUInt16LE(1, 4);
  e.writeUInt16LE(32, 6);
  e.writeUInt32LE(buf.length, 8);
  e.writeUInt32LE(offset, 12);
  dirEntries.push(e);
  offset += buf.length;
}
const out = Buffer.concat([header, ...dirEntries, ...pngs.map(p => p.buf)]);
writeFileSync(join(dir, 'icon.ico'), out);
console.log('wrote icon.ico', out.length, 'bytes, sizes:', sizes.join(','));
