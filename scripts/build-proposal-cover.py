# -*- coding: utf-8 -*-
"""
蔡工FDE — 方案书/报价单封面模板（D2）
caigong-fde-proposal-cover.docx：A4 封面页
  上部：图形标（彩色版）+ 品牌 kicker
  中部：方案名称大标题占位 + 英文 CAIGONG FDE
  下部：slogan（金）+ 提案信息表（客户/编制/日期占位）
  页脚：品牌名 + 生成声明
占位符用与产品一致的「【待填写：…】」口径。
"""
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor, Cm

REPO = Path(__file__).resolve().parents[1]
BRAND_DIR = REPO / "brand" / "caigong-fde"
OUT = REPO / "resources" / "document-templates" / "proposal_cover.docx"

INK = RGBColor(0x14, 0x18, 0x1C)
GOLD = RGBColor(0xE8, 0xA3, 0x3D)
GOLD_INK = RGBColor(0xC9, 0x8F, 0x2B)
GRAY = RGBColor(0x6B, 0x72, 0x80)
LIGHT = RGBColor(0x8A, 0x92, 0x9E)
MARK = BRAND_DIR / "hdr-mark-color.png"


def _set_run(run, size, color, bold=False, east_asia="Microsoft YaHei", spacing=None):
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
    if spacing:
        # 字距（1/20 pt）
        sp = OxmlElement("w:spacing")
        sp.set(qn("w:val"), str(spacing))
        rPr.append(sp)


def _bottom_border(paragraph, color_hex, size_eighth, space=2):
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size_eighth))
    bottom.set(qn("w:space"), str(space))
    bottom.set(qn("w:color"), color_hex)
    pBdr.append(bottom)
    pPr.append(pBdr)


def main():
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)   # A4
    sec.top_margin = Cm(2.5)
    sec.bottom_margin = Cm(2.0)
    sec.left_margin = sec.right_margin = Cm(2.6)

    # ---------- 顶部品牌区 ----------
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run()
    run.add_picture(str(MARK), height=Inches(0.62))

    kick = doc.add_paragraph()
    _set_run(kick.add_run("CAIGONG FDE · 智能交付系统"), 10, GOLD_INK, bold=True, spacing=40)

    # 金色分隔线
    line = doc.add_paragraph()
    _bottom_border(line, "E8A33D", size_eighth=12, space=1)

    # ---------- 中部：方案名大标题 ----------
    for _ in range(5):
        doc.add_paragraph()
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _set_run(title.add_run("【待填写：方案名称】"), 30, INK, bold=True)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _set_run(sub.add_run("方案书 / 报价单"), 14, GRAY)

    # ---------- 下部：slogan + 信息表 ----------
    for _ in range(7):
        doc.add_paragraph()
    slogan = doc.add_paragraph()
    _set_run(slogan.add_run("交付有据，一步到位"), 16, GOLD, bold=True, spacing=60)

    info = doc.add_paragraph()
    _set_run(info.add_run("客户名称：【待填写：客户名称】"), 11, GRAY)
    info2 = doc.add_paragraph()
    _set_run(info2.add_run("编制人：蔡工　　编制日期：【待填写：编制日期】"), 11, GRAY)
    info3 = doc.add_paragraph()
    _set_run(info3.add_run("文档编号：【待填写：文档编号】　　版本：V1.0"), 11, GRAY)

    # ---------- 页脚 ----------
    footer = sec.footer
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_run(fp.add_run("蔡工FDE智能交付系统　·　本文件含商业方案信息，请勿外传"), 8, LIGHT)

    doc.core_properties.title = "方案书封面"
    doc.core_properties.author = "蔡工FDE智能交付系统"
    doc.save(str(OUT))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
