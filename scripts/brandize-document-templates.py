# -*- coding: utf-8 -*-
"""
蔡工FDE — 文档模板品牌化（D1 + D4）
对 resources/document-templates/*.docx 批量加：
  - 页眉：图形标（左）+ 「蔡工FDE智能交付系统」（右，灰字）+ 金色下边框线
  - 页脚：左「交付有据，一步到位」｜ 右「由蔡工FDE智能交付系统生成本文档」
contract.docx 用纯文字保守版页眉（无图形，黑字+细金线，客户法务场景）
其余 16 个用图形版页眉。

安全边界：
  - 只动 sectPr 的 header/footer 引用（新增 headerN.xml/footerN.xml part），正文零改动
  - 占位符（{{ }} 与 【待填写：】）全在正文与既有页眉文字里，本脚本不触碰正文
  - 已有页眉文字的模板（project_plan_progress 的「FDE 工作台 | ...」）保留原文，
    把品牌行加在其后同段落右侧 → 简化为：保留原文字，品牌图形加在同页眉表格左侧
"""
import shutil
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

REPO = Path(__file__).resolve().parents[1]
TPL_DIR = REPO / "resources" / "document-templates"
BRAND_DIR = REPO / "brand" / "caigong-fde"

INK = RGBColor(0x14, 0x18, 0x1C)
GOLD_HEX = "E8A33D"
GRAY = RGBColor(0x6B, 0x72, 0x80)
LIGHT_GRAY = RGBColor(0x8A, 0x92, 0x9E)

MARK_MONO = BRAND_DIR / "hdr-mark-mono.png"
MARK_COLOR = BRAND_DIR / "hdr-mark-color.png"

SLUGAN = "交付有据，一步到位"
BRAND_FULL = "蔡工FDE智能交付系统"
FOOTER_LEFT = SLUGAN
FOOTER_RIGHT = f"由{BRAND_FULL}生成"

CONSERVATIVE = {"contract"}  # 纯文字保守版（客户法务场景）


def _set_run(run, size, color, bold=False, east_asia="Microsoft YaHei"):
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.font.bold = bold
    run.font.name = "Microsoft YaHei"
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), east_asia)


def _bottom_border(paragraph, color_hex, size_eighth=6, space=4):
    """段落下边框（页眉金线）。"""
    pPr = paragraph._p.get_or_add_pPr()
    existing = pPr.find(qn("w:pBdr"))
    if existing is not None:
        pPr.remove(existing)
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size_eighth))      # 1/8 pt
    bottom.set(qn("w:space"), str(space))
    bottom.set(qn("w:color"), color_hex)
    pBdr.append(bottom)
    pPr.append(pBdr)


def _cell_no_borders(cell):
    tcPr = cell._tc.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "nil")
        borders.append(el)
    tcPr.append(borders)


def _add_image_paragraph(container_paragraph, image_path, height_inches):
    """在既有段落里追加一个图片 run。"""
    run = container_paragraph.add_run()
    run.add_picture(str(image_path), height=Inches(height_inches))
    return run


def brandize(path: Path) -> str:
    doc = Document(str(path))
    conservative = path.stem in CONSERVATIVE
    notes = []

    for section in doc.sections:
        # ---------- 页眉 ----------
        header = section.header
        header.is_linked_to_previous = False
        # 取第一个非空段落；没有则用第一个段落
        paras = header.paragraphs
        target = paras[0] if paras else header.add_paragraph()
        if target.text.strip():
            notes.append(f"保留原页眉文字「{target.text.strip()[:18]}…」")
        # 清空后重建：表格（图标+文字）——若原文字保留则并入右侧
        target.clear()
        target.alignment = WD_ALIGN_PARAGRAPH.LEFT

        if conservative:
            # 纯文字版：品牌名（黑）+ 8 空格 + 原文字（灰）；原文字已含品牌名则只保留原文字
            original = target.text.strip()
            if BRAND_FULL in original.replace(" ", ""):
                run = target.add_run(original)
                _set_run(run, 9, INK, bold=True)
                notes.append("原页眉已含品牌名，仅加金线")
            else:
                run = target.add_run(BRAND_FULL)
                _set_run(run, 9, INK, bold=True)
                run2 = target.add_run("　　" + original)
                _set_run(run2, 8.5, LIGHT_GRAY)
            _bottom_border(target, GOLD_HEX, size_eighth=8, space=2)
        else:
            # 图形版：表格两列（图标 | 品牌名右对齐）
            # 清理可能残留的其他段落，保持页眉只有一行表格
            for p in list(header.paragraphs)[1:]:
                p._p.getparent().remove(p._p)
            # python-docx 建表格
            table = header.add_table(rows=1, cols=2, width=Inches(6.5))
            table.autofit = True
            # 删掉默认空段落？header 保留 target 作为表格后段落（空、小字号）
            left = table.cell(0, 0)
            right = table.cell(0, 1)
            _cell_no_borders(left)
            _cell_no_borders(right)
            left.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            right.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            lp = left.paragraphs[0]
            lp.alignment = WD_ALIGN_PARAGRAPH.LEFT
            _add_image_paragraph(lp, MARK_COLOR, 0.28)
            rp = right.paragraphs[0]
            rp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            run = rp.add_run(BRAND_FULL)
            _set_run(run, 8.5, LIGHT_GRAY)
            # 金线放在表格后的 target 段落上
            _bottom_border(target, GOLD_HEX, size_eighth=8, space=2)

        # ---------- 页脚 ----------
        footer = section.footer
        footer.is_linked_to_previous = False
        fparas = footer.paragraphs
        ftarget = fparas[0] if fparas else footer.add_paragraph()
        ftarget.clear()
        if conservative:
            run = ftarget.add_run(FOOTER_LEFT)
            _set_run(run, 8, LIGHT_GRAY)
            run2 = ftarget.add_run("　　｜　　" + FOOTER_RIGHT)
            _set_run(run2, 8, LIGHT_GRAY)
        else:
            run = ftarget.add_run(FOOTER_LEFT)
            _set_run(run, 8, LIGHT_GRAY)
            run2 = ftarget.add_run("　　｜　　" + FOOTER_RIGHT)
            _set_run(run2, 8, LIGHT_GRAY)
        ftarget.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.core_properties.author = BRAND_FULL
    doc.core_properties.last_modified_by = BRAND_FULL

    out = path.with_suffix(".docx")
    doc.save(str(out))
    return "; ".join(notes) if notes else "纯新增页眉页脚"


def main():
    backups = TPL_DIR / "_backup-pre-brand"
    backups.mkdir(exist_ok=True)
    files = sorted(TPL_DIR.glob("*.docx"))
    if not files:
        print("no templates found"); sys.exit(1)
    print(f"{len(files)} templates, conservative={sorted(CONSERVATIVE)}\n")
    for f in files:
        bak = backups / f.name
        if not bak.exists():
            shutil.copy2(f, bak)
        note = brandize(f)
        print(f"  {f.name:<28} {note}")
    print(f"\nbackups -> {backups}")


if __name__ == "__main__":
    main()
