# -*- coding: utf-8 -*-
"""
蔡工FDE 品牌交付件构建器（内容源 → 印刷版 HTML）
  · 生成 3 个辅助图形 SVG（几何取自 build_logo_svgs.py 母版）
  · 把 Markdown 规范文档转成 A4 印刷版 HTML（供 render_pdf.mjs 渲染成 PDF）

用法：python build_brand_docs.py
输出：assets/aux-*.svg、deliverables/_html/*.html
"""
import math
import os
import re
import html as html_mod
import markdown

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "assets")
DELIV = os.path.join(ROOT, "deliverables")
HTML_DIR = os.path.join(DELIV, "_html")
os.makedirs(ASSETS, exist_ok=True)
os.makedirs(HTML_DIR, exist_ok=True)

# ---------- 与 build_logo_svgs.py 同源的母版几何 ----------
CX, CY = 256.0, 200.0
R_OUT, R_IN = 100.0, 71.0
STROKE = R_OUT - R_IN          # 29
R_MID = (R_OUT + R_IN) / 2.0  # 85.5
TH_BLACK_START, TH_BLACK_END = 0.0, 300.0
TH_GOLD_START, TH_GOLD_END = 305.0, 332.0
GRAPHITE = "#14181C"
AMBER = "#E8A33D"


def pt(th, r=R_MID, cx=CX, cy=CY):
    a = math.radians(th)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def arc_path(th0, th1, r=R_MID, cx=CX, cy=CY):
    x0, y0 = pt(th0, r, cx, cy)
    x1, y1 = pt(th1, r, cx, cy)
    large = 1 if (th1 - th0) > 180 else 0
    return f"M {x0:.3f},{y0:.3f} A {r:.3f},{r:.3f} 0 {large} 1 {x1:.3f},{y1:.3f}"


def svg_wrap(body, vb, title, desc):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" '
        'role="img" aria-labelledby="t d">\n'
        f'  <title id="t">{title}</title>\n  <desc id="d">{desc}</desc>\n'
        f'{body}\n</svg>\n'
    )


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ---------- B5 辅助图形 ① 金段弧线（拉直为分隔线，保留 45° 斜切端头语义） ----------
arc1 = (
    '  <!-- 主标金弧 305°→332° 的拉直版：斜切端头 + 单一金，用作标题下分割线 -->\n'
    '  <path d="M 8 3 H 232 L 240 12 L 232 21 H 8 L 0 12 Z" '
    f'fill="{AMBER}"/>\n'
)
write_text(
    os.path.join(ASSETS, "aux-gold-arc.svg"),
    svg_wrap(arc1, "0 0 240 24", "金段弧线（辅助图形 ①）",
             "由主标右上金段推导的拉直分隔线，45° 斜切端头，全场唯一暖色，不可拉伸变形。"),
)

# ---------- B5 辅助图形 ② 进度刻度环（G1–G9 九等分） ----------
r2, c2, s2 = 80.0, 100.0, 14.0
parts = [
    '  <!-- 黑弧 0°→300°，九等分刻度对应 G1–G9 -->\n',
    f'  <path d="{arc_path(TH_BLACK_START, TH_BLACK_END, r2, c2, c2)}" '
    f'fill="none" stroke="{GRAPHITE}" stroke-width="{s2}" stroke-linecap="butt"/>\n',
]
for i in range(9):
    th = TH_BLACK_START + (TH_BLACK_END - TH_BLACK_START) * (i + 0.5) / 9.0
    x0, y0 = pt(th, r2 - s2 / 2 - 2, c2, c2)
    x1, y1 = pt(th, r2 + s2 / 2 + 2, c2, c2)
    parts.append(f'  <line x1="{x0:.2f}" y1="{y0:.2f}" x2="{x1:.2f}" y2="{y1:.2f}" '
                 f'stroke="#FFFFFF" stroke-width="1.4" opacity="0.62"/>\n')
parts.append(
    f'  <path d="{arc_path(TH_GOLD_START, TH_GOLD_END, r2, c2, c2)}" '
    f'fill="none" stroke="{AMBER}" stroke-width="{s2}" stroke-linecap="butt"/>\n'
)
write_text(
    os.path.join(ASSETS, "aux-progress-ring.svg"),
    svg_wrap("".join(parts), "0 0 200 200", "进度刻度环（辅助图形 ②）",
             "黑弧 0–300° 九等分刻度对应 G1–G9，末端 305–332° 为主标金段；装饰级元素，不得替代主标。"),
)

# ---------- B5 辅助图形 ③ 闭环箭头 ----------
r3, c3, s3 = 80.0, 100.0, 14.0
ax, ay = pt(296.0, r3, c3, c3)
# 箭头指向顺时针收笔方向（切向）
tang = math.radians(296.0 + 90.0)
ux, uy = math.cos(tang), math.sin(tang)
px, py = -uy, ux
tip = (ax + ux * 13, ay + uy * 13)
base = (ax - ux * 9, ay - uy * 9)
w = 11
p1 = (base[0] + px * w, base[1] + py * w)
p2 = (base[0] - px * w, base[1] - py * w)
arrow = (
    f'  <path d="{arc_path(TH_BLACK_START, 292.0, r3, c3, c3)}" '
    f'fill="none" stroke="{GRAPHITE}" stroke-width="{s3}" stroke-linecap="butt"/>\n'
    f'  <polygon points="{tip[0]:.2f},{tip[1]:.2f} {p1[0]:.2f},{p1[1]:.2f} '
    f'{p2[0]:.2f},{p2[1]:.2f}" fill="{GRAPHITE}"/>\n'
    f'  <path d="{arc_path(TH_GOLD_START, TH_GOLD_END, r3, c3, c3)}" '
    f'fill="none" stroke="{AMBER}" stroke-width="{s3}" stroke-linecap="butt"/>\n'
)
write_text(
    os.path.join(ASSETS, "aux-loop-arrow.svg"),
    svg_wrap(arrow, "0 0 200 200", "闭环箭头（辅助图形 ③）",
             "环形回环笔势收口于右上金段起点，表达「一个闭环」；不得改变开口方向或移动金段角度。"),
)

# ---------- Markdown → A4 印刷版 HTML ----------
PRINT_CSS = """
@page { size: A4; }
* { box-sizing: border-box; }
html, body { margin:0; padding:0; }
body {
  font-family: 'Noto Sans SC','Source Han Sans SC','Microsoft YaHei',sans-serif;
  color:#1A2027; font-size:10.2pt; line-height:1.72;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.cover {
  min-height:252mm; background:#14181C; color:#FFFFFF;
  padding:26mm 20mm 16mm; page-break-after:always; position:relative;
}
.cover .mark { width:34mm; height:34mm; margin-bottom:22mm; }
.cover .kicker { color:#F5B44A; font-size:9pt; letter-spacing:.28em; text-transform:uppercase; }
.cover h1 { font-size:30pt; line-height:1.3; font-weight:700; margin:10mm 0 6mm; border:0; color:#FFFFFF; page-break-before:auto; }
.cover .gold-rule { width:44mm; height:2.2mm; background:#E8A33D; margin:8mm 0 10mm; }
.cover .sub { font-size:12.5pt; color:#B9C2CB; line-height:1.8; max-width:130mm; }
.cover .meta { position:absolute; bottom:18mm; left:20mm; right:20mm;
  border-top:1px solid #3A4048; padding-top:5mm; font-size:8.6pt; color:#8A929E; }
.cover .meta b { color:#F5B44A; font-weight:600; }
.toc { page-break-after:always; min-height:230mm; }
.toc h2 { border:0; font-size:17pt; color:#14181C; margin:0 0 8mm; }
.toc ul { list-style:none; padding:0; margin:0; }
.toc li { border-bottom:1px solid #E4E7EB; padding:2.4mm 0; font-size:10pt; }
.toc a { color:#1A2027; text-decoration:none; }
.toc .toc-num { color:#C98F2B; font-weight:700; margin-right:5mm; }
h1 { font-size:19pt; color:#14181C; border-bottom:2px solid #E8A33D; padding-bottom:3mm;
     margin:0 0 7mm; page-break-before:always; page-break-after:avoid; }
h1:first-of-type { page-break-before:auto; }
h2 { font-size:14pt; color:#14181C; margin:9mm 0 4mm; padding-left:3.5mm;
     border-left:3px solid #C98F2B; page-break-after:avoid; }
h3 { font-size:11.6pt; color:#23282E; margin:6mm 0 2.5mm; page-break-after:avoid; }
p { margin:0 0 3.2mm; }
strong { font-weight:700; color:#14181C; }
a { color:#A3721F; }
ul, ol { margin:0 0 4mm; padding-left:6mm; }
li { margin-bottom:1.4mm; }
table { width:100%; border-collapse:collapse; margin:3mm 0 6mm; font-size:9pt;
        page-break-inside:avoid; }
thead { display:table-header-group; }
th { background:#14181C; color:#FFFFFF; text-align:left; padding:2.3mm 2.6mm;
     font-weight:600; border:1px solid #23282E; }
td { padding:2.1mm 2.6mm; border:1px solid #E4E7EB; vertical-align:top;
     overflow-wrap:anywhere; word-break:break-word; }
td:first-child { min-width:20mm; }
th { overflow-wrap:anywhere; }
tbody tr:nth-child(even) td { background:#F8F8F6; }
blockquote { border-left:3px solid #E8A33D; background:#FBF3E2; margin:3mm 0 5mm;
             padding:3mm 5mm; color:#3A4048; page-break-inside:avoid; }
blockquote p { margin:0 0 2mm; }
code { font-family:Consolas,'Courier New',monospace; font-size:8.8pt;
       background:#F2F4F5; padding:0 1.2mm; color:#5A4312; }
pre { background:#14181C; color:#F2F4F5; padding:4mm; font-size:8.4pt;
      border-radius:2mm; white-space:pre-wrap; page-break-inside:avoid; }
pre code { background:transparent; color:inherit; padding:0; }
hr { border:0; border-top:1px solid #E4E7EB; margin:7mm 0; }
.chip { display:inline-block; width:3.2mm; height:3.2mm; border:1px solid rgba(20,24,28,.18);
        border-radius:.6mm; margin-right:1.8mm; vertical-align:-.4mm; }
.swatch-cell code { background:transparent; padding:0; }
mark, .warn { background:#FBEECC; padding:0 1mm; }
"""

# 封面反白图形标：由母版几何直接生成，避免手写 path 出错
_MARK_VB = f"{CX - R_OUT:.0f} {CY - R_OUT:.0f} {R_OUT * 2:.0f} {R_OUT * 2:.0f}"
MARK_SVG = f"""<svg class="mark" viewBox="{_MARK_VB}" xmlns="http://www.w3.org/2000/svg">
  <path d="{arc_path(TH_BLACK_START, TH_BLACK_END)}" fill="none" stroke="#FFFFFF" stroke-width="{STROKE}" stroke-linecap="butt"/>
  <path d="{arc_path(TH_GOLD_START, TH_GOLD_END)}" fill="none" stroke="#F5B44A" stroke-width="{STROKE}" stroke-linecap="butt"/>
  <path d="M {CX - 17:.0f},{CY:.0f} L {CX + R_OUT:.0f},{CY:.0f}" fill="none" stroke="#FFFFFF" stroke-width="{STROKE}" stroke-linecap="butt"/>
</svg>"""

DOCS = [
    dict(src="BRAND-COLOR-SPEC.md", out="蔡工FDE-配色方案",
         kicker="BRAND / COLOR SYSTEM", sub="独立配色系统文档 · 色阶 / 深浅适配 / UI 令牌 / 对比度实测 / 用色纪律",
         meta="唯一真源：BRAND-COLOR-SPEC.md ｜ 上位：BRAND-LOGO-GUIDE.md §三 ｜ 状态：可直接归档，待确认项开放",
         swatches=True),
    dict(src="BRAND-MASTER-PLAN.md", out="蔡工FDE-品牌全案策划书",
         kicker="BRAND / MASTER PLAN", sub="策略与决策文档 · 定位 / 话术 / 视觉总纲 / 触点矩阵 / 落地路线 / 治理与风险",
         meta="配套：策划书 PPTX、品牌手册 PDF ｜ 说明：本策划书不以清单代替 ｜ 状态：可直接归档，生效待确认",
         swatches=False),
    dict(src="BRAND-GUIDELINES.md", out="蔡工FDE-品牌手册",
         kicker="BRAND / GUIDELINES", sub="执行规范完整版 · 主标 / 配色 / 字体 / 图形图标 / 动效 / 全载体应用示例 / 正误对照",
         meta="对应清单 F1 ｜ PDF 成品 ｜ 状态：内容已齐，发布审批人与生效日期待确认",
         swatches=False),
    dict(src="BRAND-COMPLETION-INDEX.md", out="蔡工FDE-品牌补齐索引",
         kicker="BRAND / COMPLETION", sub="按缺失项分组与清单编号逐项登记 · 五字段 / 引用关系 / 待确认项 / 验证结果",
         meta="对应清单 A4–F3 全部补齐项 ｜ 状态：可直接归档",
         swatches=False),
]

SPECS = [
    ("specs/A-品牌核心补齐.md", "A 组 · 品牌核心（A4、A5）"),
    ("specs/B-VI基础系统补齐.md", "B 组 · VI 基础系统（B3–B8）"),
    ("specs/C-数字载体补齐.md", "C 组 · 数字载体（C6–C9、C4 条件待补）"),
    ("specs/D-商务载体补齐.md", "D 组 · 商务载体（D5、D6）"),
    ("specs/E-现场物料补齐.md", "E 组 · 现场与实体（E1–E5）"),
    ("specs/F-治理补齐.md", "F 组 · 治理（F1–F3）"),
]


def strip_first_h1(md_text):
    lines = md_text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("# "):
            return lines[i][2:].strip(), "\n".join(lines[:i] + lines[i + 1:])
    return "蔡工FDE 品牌文档", md_text


def toc_html(toc):
    """把 markdown toc 扩展生成的 <div class="toc"><ul>... 整理成分页目录。"""
    items = re.findall(r'<li><a href="([^"]+)">(.*?)</a>', toc, flags=re.S)
    if not items:
        return ""
    out = ['<section class="toc"><h2>目录</h2><ul>']
    for n, (href, label) in enumerate(items, 1):
        clean = re.sub(r"<[^>]+>", "", label).strip()
        out.append(f'<li><span class="toc-num">{n:02d}</span><a href="{href}">{html_mod.escape(clean)}</a></li>')
    out.append("</ul></section>")
    return "".join(out)


def add_swatches(fragment):
    """给表格单元格里的 hex 色值加色块（仅配色方案文档）。"""
    def cell_repl(m):
        inner = m.group(2)
        def hex_repl(h):
            color = h.group(0)
            return (f'<span class="chip" style="background:{color}"></span>'
                    f'<code>{color}</code>')
        new_inner = re.sub(r"#[0-9A-Fa-f]{6}\b", hex_repl, inner)
        return m.group(1) + new_inner + m.group(3)
    return re.sub(r"(<td[^>]*>)(.*?)(</td>)", cell_repl, fragment, flags=re.S)


def render_doc(md_text, cfg):
    title, rest = strip_first_h1(md_text)
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "attr_list", "sane_lists"],
                           extension_configs={"toc": {"toc_depth": "2-2"}})
    body = md.convert(rest)
    if cfg.get("swatches"):
        body = add_swatches(body)
    toc = toc_html(md.toc)
    doc_title = cfg["out"]
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{html_mod.escape(doc_title)}</title>
<style>{PRINT_CSS}</style></head><body>
<section class="cover">
  {MARK_SVG}
  <div class="kicker">{cfg['kicker']}</div>
  <h1>{html_mod.escape(doc_title)}</h1>
  <div class="gold-rule"></div>
  <div class="sub">{cfg['sub']}<br><br>蔡工FDE智能交付系统　·　交付有据，一步到位</div>
  <div class="meta"><b>v1.0</b>　｜　2026-11-05　｜　{cfg['meta']}</div>
</section>
{toc}
<section class="body">{body}</section>
</body></html>"""


def main():
    made = []
    for cfg in DOCS:
        path = os.path.join(ROOT, cfg["src"])
        with open(path, encoding="utf-8") as f:
            md_text = f.read()
        out = os.path.join(HTML_DIR, cfg["out"] + ".html")
        write_text(out, render_doc(md_text, cfg))
        made.append(out)

    # 规范补齐包：六组 spec 合并，组间分页
    chunks = []
    for i, (rel, group_title) in enumerate(SPECS):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            _, rest = strip_first_h1(f.read())
        md = markdown.Markdown(extensions=["tables", "fenced_code", "attr_list", "sane_lists"])
        body = md.convert(rest)
        brk = "" if i == 0 else ' style="page-break-before:always"'
        chunks.append(f'<h1{brk}>{html_mod.escape(group_title)}</h1>{body}')
    pack_html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>蔡工FDE-品牌规范补齐包</title>
<style>{PRINT_CSS}</style></head><body>
<section class="cover">
  {MARK_SVG}
  <div class="kicker">BRAND / SPECIFICATION PACK</div>
  <h1>蔡工FDE 品牌规范补齐包</h1>
  <div class="gold-rule"></div>
  <div class="sub">A–F 六组 · 清单 🔲 项逐项规范内容<br>每项含名称 / 适用范围 / 核心内容 / 引用关系 / 待确认项</div>
  <div class="meta"><b>v1.0</b>　｜　2026-11-05　｜　信息不足处均标「待确认」，不臆造品牌信息</div>
</section>
<section class="body">{''.join(chunks)}</section>
</body></html>"""
    pack_out = os.path.join(HTML_DIR, "蔡工FDE-品牌规范补齐包.html")
    write_text(pack_out, pack_html)
    made.append(pack_out)

    print("generated HTML:")
    for p in made:
        print("  ", os.path.relpath(p, ROOT))
    print("generated SVG assets:")
    for name in ("aux-gold-arc.svg", "aux-progress-ring.svg", "aux-loop-arrow.svg"):
        print("  ", os.path.join("assets", name))


if __name__ == "__main__":
    main()
