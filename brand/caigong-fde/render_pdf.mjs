// 蔡工FDE 品牌交付件：HTML → A4 PDF（Chromium 实渲染），并生成邮件签名用小图标 PNG
// 用法：node render_pdf.mjs
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const HTML_DIR = path.join(ROOT, 'deliverables', '_html');
const DELIV = path.join(ROOT, 'deliverables');
const ASSETS = path.join(ROOT, 'assets');
fs.mkdirSync(DELIV, { recursive: true });
fs.mkdirSync(ASSETS, { recursive: true });

const footer = `
<div style="width:100%;font-family:'Noto Sans SC','Microsoft YaHei',sans-serif;
     font-size:7.5pt;color:#8A929E;padding:0 16mm;box-sizing:border-box;">
  <div style="border-top:0.6px solid #E8A33D;padding-top:2mm;display:flex;
       justify-content:space-between;">
    <span>蔡工FDE智能交付系统　·　交付有据，一步到位</span>
    <span><span class="pageNumber"></span> / <span class="totalPages"></span></span>
  </div>
</div>`;

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1200, height: 1600 } });

  const files = fs.readdirSync(HTML_DIR).filter(f => f.endsWith('.html')).sort();
  for (const file of files) {
    const htmlPath = path.join(HTML_DIR, file);
    const pdfPath = path.join(DELIV, file.replace(/\.html$/, '.pdf'));
    await page.goto('file:///' + htmlPath.replace(/\\/g, '/'), { waitUntil: 'load' });
    await page.evaluate(() => document.fonts.ready);
    await page.pdf({
      path: pdfPath,
      format: 'A4',
      printBackground: true,
      preferCSSPageSize: false,
      margin: { top: '18mm', bottom: '18mm', left: '16mm', right: '16mm' },
      displayHeaderFooter: true,
      headerTemplate: '<div></div>',
      footerTemplate: footer,
    });
    const kb = (fs.statSync(pdfPath).size / 1024).toFixed(0);
    console.log(`PDF  ${file} -> ${path.basename(pdfPath)}  ${kb} KB`);
  }

  // 邮件签名用 64×64 透明底图形标 PNG
  const markPath = path.join(ROOT, 'caigong-fde-mark.svg');
  let svg = fs.readFileSync(markPath, 'utf8');
  svg = svg.replace(/\s(width|height)="[^"]*"/g, '');
  svg = svg.replace('<svg ', '<svg width="64" height="64" ');
  const shot = await browser.newPage({ viewport: { width: 64, height: 64 }, deviceScaleFactor: 2 });
  await shot.setContent(
    `<!doctype html><html><head><meta charset="utf-8"><style>
      html,body{margin:0;padding:0;background:transparent;width:100%;height:100%;
               display:flex;align-items:center;justify-content:center}
      svg{display:block;width:84%;height:84%}
     </style></head><body>${svg}</body></html>`,
    { waitUntil: 'load' }
  );
  const pngPath = path.join(ASSETS, 'mark-64.png');
  await shot.screenshot({ path: pngPath, omitBackground: true, clip: { x: 0, y: 0, width: 64, height: 64 } });
  console.log(`PNG  mark-64.png  ${(fs.statSync(pngPath).size / 1024).toFixed(1)} KB`);

  // PPT 深底封面用：反白图形标 256px 透明底
  const inverseSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="156 100 200 200">
    <path d="M 341.500,200 A 85.500,85.500 0 1 1 298.750,125.960" fill="none" stroke="#FFFFFF" stroke-width="29" stroke-linecap="butt"/>
    <path d="M 305.040,129.958 A 85.500,85.500 0 0 1 331.490,159.856" fill="none" stroke="#F5B44A" stroke-width="29" stroke-linecap="butt"/>
    <path d="M 239,200 L 356,200" fill="none" stroke="#FFFFFF" stroke-width="29" stroke-linecap="butt"/>
  </svg>`;
  const shot2 = await browser.newPage({ viewport: { width: 256, height: 256 }, deviceScaleFactor: 2 });
  await shot2.setContent(
    `<!doctype html><html><head><meta charset="utf-8"><style>
      html,body{margin:0;padding:0;background:transparent;width:100%;height:100%;
               display:flex;align-items:center;justify-content:center}
      svg{display:block;width:84%;height:84%}
     </style></head><body>${inverseSvg}</body></html>`,
    { waitUntil: 'load' }
  );
  const png2 = path.join(ASSETS, 'mark-inverse-256.png');
  await shot2.screenshot({ path: png2, omitBackground: true, clip: { x: 0, y: 0, width: 256, height: 256 } });
  console.log(`PNG  mark-inverse-256.png  ${(fs.statSync(png2).size / 1024).toFixed(1)} KB`);

  // 修正既有缺陷资产：mark-transparent-1024.png 早期渲染只剩残缺黑弧（金段/G 杠丢失）
  // 以正确的 SVG 母版重新渲染，透明底 1024×1024
  let darkSvg = fs.readFileSync(markPath, 'utf8');
  darkSvg = darkSvg.replace(/\s(width|height)="[^"]*"/g, '');
  darkSvg = darkSvg.replace('<svg ', '<svg width="1024" height="1024" ');
  const shot3 = await browser.newPage({ viewport: { width: 1024, height: 1024 }, deviceScaleFactor: 1 });
  await shot3.setContent(
    `<!doctype html><html><head><meta charset="utf-8"><style>
      html,body{margin:0;padding:0;background:transparent;width:100%;height:100%;
               display:flex;align-items:center;justify-content:center}
      svg{display:block;width:84%;height:84%}
     </style></head><body>${darkSvg}</body></html>`,
    { waitUntil: 'load' }
  );
  const png3 = path.join(ROOT, 'mark-transparent-1024.png');
  await shot3.screenshot({ path: png3, omitBackground: true, clip: { x: 0, y: 0, width: 1024, height: 1024 } });
  console.log(`PNG  mark-transparent-1024.png (re-rendered)  ${(fs.statSync(png3).size / 1024).toFixed(1)} KB`);

  await browser.close();
})().catch(err => { console.error(err); process.exitCode = 1; });
