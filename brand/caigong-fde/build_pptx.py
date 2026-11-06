# -*- coding: utf-8 -*-
"""
生成两份 PPTX：
  1) deliverables/蔡工FDE-品牌全案策划书.pptx  （策略演示稿，15 页）
  2) deliverables/caigong-fde-ppt-template.pptx （C8 提案/演示模板，6 页，全部字段占位）

前置：node render_pdf.mjs 已生成 mark-inverse-256.png / mark-transparent-1024.png
用法：python build_pptx.py
"""
import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

ROOT = os.path.dirname(os.path.abspath(__file__))
DELIV = os.path.join(ROOT, "deliverables")
os.makedirs(DELIV, exist_ok=True)

INK = "#14181C"
INK2 = "#23282E"
INK4 = "#5A626D"
INK5 = "#8A929E"
GOLD = "#E8A33D"
GOLD_BRIGHT = "#F5B44A"
GOLD_INK = "#C98F2B"
BG = "#F6F6F4"
WHITE = "#FFFFFF"
LINE = "#E4E7EB"
FONT = "Microsoft YaHei"

SW, SH = 13.333, 7.5
M = 0.72
CW = SW - 2 * M

MARK_DARK = os.path.join(ROOT, "mark-transparent-1024.png")
MARK_LIGHT = os.path.join(ROOT, "assets", "mark-inverse-256.png")


def rgb(h):
    h = h.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rect(slide, x, y, w, h, fill, line=None, line_w=0.75):
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = rgb(fill)
    if line:
        s.line.color.rgb = rgb(line)
        s.line.width = Pt(line_w)
    else:
        s.line.fill.background()
    try:
        s.shadow.inherit = False
    except Exception:
        pass
    return s


def text(slide, x, y, w, h, lines, size=16, color=INK, bold=False,
         align=PP_ALIGN.LEFT, spacing=1.3, gap=0.45):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.TOP
    if isinstance(lines, str):
        lines = [lines]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        p.space_after = Pt(size * gap)
        r = p.add_run()
        r.text = line
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = rgb(color)
        r.font.name = FONT
    return tb


def picture(slide, path, x, y, w, h):
    if os.path.exists(path):
        return slide.shapes.add_picture(path, Inches(x), Inches(y), width=Inches(w), height=Inches(h))
    return None


def new_deck():
    prs = Presentation()
    prs.slide_width = Inches(SW)
    prs.slide_height = Inches(SH)
    return prs


def dark_slide(prs, kicker, title, sub=None, mark=True):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    rect(s, 0, 0, SW, SH, INK)
    if mark:
        picture(s, MARK_LIGHT, M, 0.44, 0.52, 0.52)
    text(s, M + (0.72 if mark else 0), 0.52, 9.0, 0.3,
         kicker, size=10, color=GOLD_BRIGHT, bold=True, spacing=1.0, gap=0)
    text(s, M, 1.28, 11.6, 0.8, title, size=30, color=WHITE, bold=True, spacing=1.15, gap=0)
    rect(s, M, 2.25, 1.15, 0.045, GOLD)
    if sub:
        text(s, M, 2.52, 11.4, 0.5, sub, size=13, color="#B9C2CB", spacing=1.3, gap=0)
    text(s, M, 6.86, 8.0, 0.26, "蔡工FDE智能交付系统　·　交付有据，一步到位",
         size=9, color=INK5, spacing=1.0, gap=0)
    return s


def light_slide(prs, kicker, title, sub=None):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    rect(s, 0, 0, SW, SH, WHITE)
    rect(s, 0, 0, SW, 0.075, INK)
    picture(s, MARK_DARK, M, 0.34, 0.42, 0.42)
    text(s, M + 0.56, 0.34, 8.0, 0.3, kicker, size=10, color=GOLD_INK, bold=True, spacing=1.0, gap=0)
    text(s, M, 0.92, 11.6, 0.62, title, size=25, color=INK, bold=True, spacing=1.15, gap=0)
    rect(s, M, 1.66, 1.0, 0.04, GOLD)
    if sub:
        text(s, M, 1.86, 11.4, 0.4, sub, size=12, color=INK4, spacing=1.2, gap=0)
    rect(s, M, 6.78, CW, 0.012, LINE)
    text(s, M, 6.9, 9.0, 0.26, "蔡工FDE智能交付系统　·　交付有据，一步到位",
         size=9, color=INK5, spacing=1.0, gap=0)
    return s


def card(slide, x, y, w, h, title, body, accent=False):
    rect(slide, x, y, w, h, "#F8F8F6" if not accent else "#FBF3E2", LINE)
    rect(slide, x, y, 0.055, h, GOLD_INK if accent else INK4)
    text(slide, x + 0.24, y + 0.2, w - 0.45, 0.36, title, size=14, color=INK, bold=True, spacing=1.1, gap=0)
    text(slide, x + 0.24, y + 0.68, w - 0.45, h - 0.85, body if isinstance(body, list) else [body],
         size=11.5, color=INK4, spacing=1.35, gap=0.4)


def bullets(slide, x, y, w, items, size=14, color=INK2, gap=0.55, marker=True):
    lines = [(("·  " if marker else "") + t) for t in items]
    return text(slide, x, y, w, SH - y - 0.7, lines, size=size, color=color, spacing=1.35, gap=gap)


# ============================ 交付件 1：品牌全案策划书 PPTX ============================
def build_plan():
    prs = new_deck()

    # 1 封面
    s = prs.slides.add_slide(prs.slide_layouts[6])
    rect(s, 0, 0, SW, SH, INK)
    picture(s, MARK_LIGHT, M, 0.95, 1.5, 1.5)
    text(s, M, 2.85, 11.4, 0.3, "BRAND / MASTER PLAN　·　v1.0", size=11, color=GOLD_BRIGHT, bold=True, gap=0)
    text(s, M, 3.32, 11.4, 1.0, "蔡工FDE智能交付系统　品牌全案策划书", size=34, color=WHITE, bold=True, gap=0)
    rect(s, M, 4.52, 1.5, 0.055, GOLD)
    text(s, M, 4.86, 11.0, 0.6,
         ["策略与决策文档　·　不再以资产清单代替", "交付有据，一步到位"],
         size=15, color="#B9C2CB", spacing=1.5, gap=0.5)
    text(s, M, 6.72, 11.0, 0.3,
         "2026-11-05　｜　状态：可直接归档，发布审批人与生效日期待确认",
         size=10, color=INK5, gap=0)

    # 2 核查结论
    s = light_slide(prs, "01 / 核查结论", "三项前提：本策划书要补什么",
                    "本次对全仓的实际检索结果，不是推测")
    card(s, M, 2.35, 3.75, 2.05, "① docs/ 零命中", [
        "54 个条目全为研发/审计/交付台账", "配色方案、品牌全案、品牌手册、", "品牌故事、话术口径均无独立文档"])
    card(s, M + 3.95, 2.35, 3.75, 2.05, "② 配色规范仅嵌 §三", [
        "色值散在 LOGO-GUIDE、styles.css、", "官网 HTML 三处，无单一真源", "新增载体无规可依"], accent=True)
    card(s, M + 7.9, 2.35, 3.75, 2.05, "③ 全案策划实为清单", [
        "BRAND-ASSET-CHECKLIST.md 只回答", "「做了没」，不回答「为什么」", "与「怎么统一、怎么防走样」"])
    text(s, M, 4.75, CW, 1.2, [
        "结论：形成独立《配色方案》、独立《品牌全案策划书》（PDF + PPT）、"
        "《品牌手册（完整版）》PDF，并按清单编号逐项补齐 🔲 项规范内容。",
        "顺带修正：§〇 一段话介绍由错误的「九步交付法」改为「13 阶段交付 SOP + G1–G9 门禁」。"],
        size=13, color=INK2, spacing=1.4, gap=0.7)

    # 3 结构性问题
    s = light_slide(prs, "02 / 问题诊断", "清单形态暴露的四个结构性问题")
    items = [
        "无策略层：直接跳到「做什么物料」，缺定位与差异化依据，新物料出现时无判断标准",
        "无单一真源：色值、话术、术语散落三处以上，不一致时不知道以谁为准",
        "无执行规范：主标有 §六，但字体层级、图标、辅助图形、摄影、动效、应用示例全空",
        "无治理闭环：无版本/变更/巡检机制；已出现 docx 模板重建覆盖品牌化的真实风险",
    ]
    for i, t in enumerate(items):
        y = 2.15 + i * 1.08
        rect(s, M, y, 0.42, 0.42, INK)
        text(s, M, y + 0.06, 0.42, 0.3, str(i + 1), size=14, color=GOLD_BRIGHT,
             bold=True, align=PP_ALIGN.CENTER, gap=0)
        text(s, M + 0.66, y + 0.02, CW - 0.8, 0.7, t, size=14.5, color=INK2, spacing=1.3, gap=0)

    # 4 品牌定位
    s = dark_slide(prs, "03 / 品牌定位", "核心资产：什么最难被复制",
                   "定位不靠形容词，靠可核验的事实")
    card(s, M, 3.05, 3.72, 2.35, "个人信用", [
        "主标 C+G 直接对应「蔡工」", "§一 明确其为最难被复制的资产", "与具体的人绑定，不随工具迁移"])
    card(s, M + 3.95, 3.05, 3.72, 2.35, "方法论", [
        "13 阶段交付 SOP + G1–G9 门禁", "有节点、出口条件、证据清单", "真值源 server/seeds/gates.json"])
    card(s, M + 7.9, 3.05, 3.72, 2.35, "交付凭据", [
        "证据链 · 可追溯 · 可验收", "验收线达成才放行", "客户能逐项核对，而非「差不多了」"])

    # 5 价值主张
    s = light_slide(prs, "04 / 价值主张", "「交付有据，一步到位」", "标管可靠，话管高效——两者互补，不重复表达同一件事")
    rect(s, M, 2.35, 5.72, 2.7, INK)
    text(s, M + 0.4, 2.7, 4.9, 0.45, "交付有据", size=26, color=GOLD_BRIGHT, bold=True, gap=0)
    text(s, M + 0.4, 3.35, 4.9, 1.4,
         ["门禁 G1–G9 · 证据链 · 可追溯", "回答客户：「凭什么算做完？」"],
         size=13, color="#B9C2CB", spacing=1.5, gap=0.7)
    rect(s, M + 6.0, 2.35, 5.72, 2.7, "#FBF3E2", "#F0D9AC")
    text(s, M + 6.4, 2.7, 4.9, 0.45, "一步到位", size=26, color=GOLD_INK, bold=True, gap=0)
    text(s, M + 6.4, 3.35, 4.9, 1.4,
         ["效率承诺 · 不把返工留给客户", "回答客户：「会不会反复返工？」"],
         size=13, color=INK4, spacing=1.5, gap=0.7)
    text(s, M, 5.4, CW, 0.7,
         "标：C 形环闭环 + 右上验收刻痕　｜　话：全渠道统一，不得改写（§〇 使用规则）",
         size=12.5, color=INK4, gap=0)

    # 6 差异化
    s = light_slide(prs, "05 / 差异化", "差异化表述（只使用已确认事实）")
    rect(s, M, 2.2, CW, 1.5, "#F8F8F6", LINE)
    rect(s, M, 2.2, 0.06, 1.5, GOLD_INK)
    text(s, M + 0.35, 2.48, CW - 0.7, 1.1,
         ["不是把交付写成一份漂亮文档，而是把交付拆成 13 个阶段、设下 G1 到 G9 九道门禁：",
          "每一道都留下证据、给出结论，才允许往下走。客户拿到的是一条从需求到验收、可追溯可验收的闭环。"],
         size=15, color=INK, spacing=1.5, gap=0.7)
    text(s, M, 4.05, CW, 0.4, "禁用口径", size=14, color=GOLD_INK, bold=True, gap=0)
    bullets(s, M, 4.55, CW, [
        "「九步交付法」「九步法」「9 步法」——全仓禁用；正确为 13 阶段交付 SOP + G1–G9 门禁",
        "不得编造门禁名称（G1 立项门 / G9 终验门 均为错误），以 server/seeds/gates.json 为准",
        "创始人背景、成立年份、客户案例、效果数据：未提供书面事实，一律「待确认」，不得代填",
    ], size=13, gap=0.65)

    # 7 命名与话术
    s = light_slide(prs, "06 / 话术体系", "命名层级与术语真值")
    rows = [
        ("全称", "蔡工FDE智能交付系统", "合同 / 页脚 / 签名"),
        ("短名·标准字", "蔡工FDE（不拆行、不改大小写）", "主标组合 / 侧边栏"),
        ("英文", "CAIGONG FDE（全大写，字距 +0.2em）", "英文语境"),
        ("Slogan", "交付有据，一步到位（正式物料带逗号）", "全渠道"),
        ("方法论", "13 阶段交付 SOP + G1–G9 门禁", "全部对外话术"),
    ]
    y0 = 2.15
    rect(s, M, y0, CW, 0.44, INK)
    text(s, M + 0.18, y0 + 0.1, 1.8, 0.3, "层级", size=11.5, color=WHITE, bold=True, gap=0)
    text(s, M + 2.1, y0 + 0.1, 5.5, 0.3, "唯一正确写法", size=11.5, color=WHITE, bold=True, gap=0)
    text(s, M + 7.9, y0 + 0.1, 3.6, 0.3, "适用", size=11.5, color=WHITE, bold=True, gap=0)
    for i, (a, b, c) in enumerate(rows):
        y = y0 + 0.44 + i * 0.62
        rect(s, M, y, CW, 0.62, WHITE if i % 2 == 0 else "#F8F8F6", LINE)
        text(s, M + 0.18, y + 0.16, 1.8, 0.3, a, size=11.5, color=GOLD_INK, bold=True, gap=0)
        text(s, M + 2.1, y + 0.16, 5.5, 0.3, b, size=11.5, color=INK2, gap=0)
        text(s, M + 7.9, y + 0.16, 3.6, 0.3, c, size=11.5, color=INK4, gap=0)
    text(s, M, 5.95, CW, 0.5,
         "G1 线索资格门 → G2 真需求门 → G3 诊断开工门 → G4 试点签约门 → G5 建档门 → G6 发现门 → G7 设计门 → G8 试点毕业门 → G9 上线门",
         size=11, color=INK4, spacing=1.3, gap=0)

    # 8 视觉系统总纲
    s = light_slide(prs, "07 / 视觉系统", "视觉总纲：结构是黑的，强调是金的，其余全是中性灰")
    cards = [
        ("主标", "CG 环形标 · 已定稿", "§一/§二/§五–§七"),
        ("配色", "独立《配色方案》", "BRAND-COLOR-SPEC.md"),
        ("字体", "字阶 + 等宽数字", "B4 规范已出，选型待确认"),
        ("辅助图形", "三母题 + SVG 草案", "B5 · 延展待拍板"),
        ("图标", "24px 网格 / 1.5px 线性", "B6 · 统一待核"),
        ("摄影·插图", "双轨风格已出", "B7 · 素材为零"),
        ("动效", "金段递进母题", "B8 · 未实施"),
        ("图表色板", "条件待补", "B3 · 不虚构色值"),
    ]
    for i, (t, a, b) in enumerate(cards):
        col, row = i % 4, i // 4
        x, y = M + col * 3.03, 2.2 + row * 2.05
        card(s, x, y, 2.85, 1.85, t, [a, b], accent=(i == 7))

    # 9 配色系统
    s = dark_slide(prs, "08 / 配色系统", "石墨黑 + 琥珀金：双阶十色",
                   "所有色值来自 BRAND-COLOR-SPEC.md，与 styles.css :root 逐值一致")
    golds = [("gold-1", "#FBEECC"), ("gold-2", "#F5B44A"), ("gold-3", "#E8A33D"),
             ("gold-4", "#C98F2B"), ("gold-5", "#A3721F")]
    inks = [("ink-1", "#14181C"), ("ink-2", "#23282E"), ("ink-3", "#3A4048"),
            ("ink-4", "#5A626D"), ("ink-5", "#8A929E")]
    for row, (label, group) in enumerate([("金色阶", golds), ("石墨阶", inks)]):
        y = 3.15 + row * 1.55
        text(s, M, y - 0.32, 3.0, 0.3, label, size=12, color=GOLD_BRIGHT, bold=True, gap=0)
        for i, (name, hexv) in enumerate(group):
            x = M + i * 2.38
            rect(s, x, y, 2.18, 0.72, hexv, "#3A4048")
            text(s, x + 0.1, y + 0.42, 2.0, 0.24, f"{name}  {hexv}", size=9.5,
                 color=WHITE if row == 1 and i < 3 else INK, bold=True, gap=0)
    text(s, M, 6.28, CW, 0.4,
         "纪律：金色全场一处 ｜ 深底提亮 #F5B44A ｜ 不得引入第三种彩色 ｜ 语义色不参与品牌表达",
         size=11.5, color="#B9C2CB", gap=0)

    # 10 触点矩阵
    s = light_slide(prs, "09 / 触点矩阵", "36 项触点：现状与本次补齐")
    heads = ["层", "模块", "项数", "原完成", "本次补齐", "剩余条件项"]
    widths = [0.7, 3.0, 1.0, 1.2, 3.2, 2.7]
    x0 = M
    rect(s, M, 2.15, CW, 0.44, INK)
    xx = x0
    for h, w in zip(heads, widths):
        text(s, xx + 0.12, 2.25, w - 0.2, 0.3, h, size=11, color=WHITE, bold=True, gap=0)
        xx += w
    rows = [
        ("A", "品牌核心", "5", "3", "A4、A5", "行业口径 / 创始人背景"),
        ("B", "VI 基础系统", "8", "2", "B3–B8", "字体选型 / 图表色板"),
        ("C", "数字载体", "9", "4", "C6–C9", "C4 macOS 图标 / 联系方式"),
        ("D", "商务载体", "6", "4", "D5、D6", "联系方式 / 签章资质"),
        ("E", "现场与实体", "5", "0", "E1–E5", "印版 / 材质 / 共标授权"),
        ("F", "治理规范", "3", "0", "F1、F2、F3", "审批人 / 巡检人"),
    ]
    for i, row in enumerate(rows):
        y = 2.59 + i * 0.61
        rect(s, M, y, CW, 0.61, WHITE if i % 2 == 0 else "#F8F8F6", LINE)
        xx = x0
        for j, (val, w) in enumerate(zip(row, widths)):
            text(s, xx + 0.12, y + 0.16, w - 0.2, 0.3, val, size=11,
                 color=GOLD_INK if j == 4 else INK2, bold=(j == 0 or j == 4), gap=0)
            xx += w
    text(s, M, 6.35, CW, 0.4,
         "最高杠杆触点：产品内 17 个 docx 模板、桌面端 UI、官网、名片——客户每周都在看",
         size=12, color=INK4, gap=0)

    # 11 本次补齐
    s = light_slide(prs, "10 / 本次交付", "三类缺失的补齐形态：区分「规范」与「成品」")
    card(s, M, 2.2, 3.75, 2.2, "① 独立文档 + PDF/PPTX", [
        "配色方案 MD + PDF", "全案策划书 MD + PDF + PPTX", "品牌手册 MD + PDF（F1）"], accent=True)
    card(s, M + 3.95, 2.2, 3.75, 2.2, "② 六组规范内容", [
        "A–F 六组 specs/*.md", "22 项 + 1 条件说明", "每项五字段齐全"])
    card(s, M + 7.9, 2.2, 3.75, 2.2, "③ 可用模板与资产", [
        "邮件签名 HTML / PPT 模板 PPTX", "3 个辅助图形 SVG", "CHANGELOG / 索引 / 清单更新"])
    text(s, M, 4.72, CW, 1.4, [
        "未伪造为已完成：E 组印刷实物成品、D6 电子章章样、C4 macOS icns、B3 图表色板、"
        "F1 正式发布、全渠道真实联系方式。",
        "本次未改动任何已验收的产品功能与 UI 实现（styles.css / site/index.html / 桌面端 TSX / 17 个 docx 模板）。"],
        size=13, color=INK2, spacing=1.45, gap=0.75)

    # 12 落地路线
    s = light_slide(prs, "11 / 落地路线", "三波路线与本次对照")
    waves = [
        ("第一波 P0 · 10 项", "话术 → 色彩 → 桌面端 → 商务模板 → 官网", "已完成 9 项，余 C4 macOS 图标（环境依赖）"),
        ("第二波 P1 · 11 项", "故事/话术 → 字阶/图形/图标 → 公众号/签名/PPT → 工牌 → 手册/资产", "本次以规范内容形式全部补齐"),
        ("第三波 P2 · 8 项", "插图/动效/截图 → 签章/展会/贴纸/礼品 → 巡检", "本次以规范内容形式全部补齐，成品待外部条件"),
    ]
    for i, (t, a, b) in enumerate(waves):
        y = 2.2 + i * 1.42
        rect(s, M, y, CW, 1.25, "#F8F8F6" if i != 0 else "#FBF3E2", LINE)
        rect(s, M, y, 0.06, 1.25, GOLD_INK)
        text(s, M + 0.28, y + 0.16, 3.1, 0.35, t, size=14, color=GOLD_INK, bold=True, gap=0)
        text(s, M + 3.5, y + 0.16, 8.0, 0.9, [a, b], size=12, color=INK2, spacing=1.35, gap=0.5)

    # 13 治理
    s = dark_slide(prs, "12 / 治理体系", "防止品牌走样：真源、生成物、变更、巡检")
    bullets(s, M, 3.1, CW, [
        "单一真源：BRAND-COLOR-SPEC.md（色值）、§〇（话术）、gates.json（门禁名）、build_logo_svgs.py（几何）",
        "生成物禁手改：8 个 SVG / PNG·ICO / 名片 / 17 个 docx，改真源后重跑生成器",
        "覆盖风险：build-document-templates.py 重建后必须重跑 brandize-document-templates.py",
        "破坏性变更：色值/几何/话术/门禁名任一变更 → 全量同步 + CHANGELOG + F3 全量巡检",
        "文档优先级：定稿话术 §〇 > 品牌手册 > 本策划书 > 资产清单",
    ], size=13.5, color="#E4E7EB", gap=0.85, marker=True)

    # 14 风险
    s = light_slide(prs, "13 / 风险与待确认", "两项高优先已闭环；其余不臆造品牌信息")
    risks = [
        ("行业口径", "✅ 已裁决 2026-11-06：全行业企业。定稿介绍与官网 meta/hero 已回写，原「制造业现场」退役"),
        ("对比度", "✅ 已裁决 2026-11-06：金系按钮改石墨黑字（主态 6.33–8.27:1 达 AA）；hover 深金 4.23:1 残留待拍板"),
        ("签章合规", "D6 只定版式位置；主体资质、备案章样、朱红豁免均待法务与品牌责任人确认"),
        ("G9 口径", "清单 E4 写「G9 终验」，真值为「G9 上线门」；文案待统一"),
    ]
    for i, (t, b) in enumerate(risks):
        y = 2.2 + i * 1.1
        rect(s, M, y, 2.1, 0.92, INK)
        text(s, M + 0.2, y + 0.29, 1.8, 0.35, t, size=14, color=GOLD_BRIGHT, bold=True, gap=0)
        rect(s, M + 2.1, y, CW - 2.1, 0.92, "#F8F8F6", LINE)
        text(s, M + 2.35, y + 0.22, CW - 2.6, 0.6, b, size=12.5, color=INK2, spacing=1.3, gap=0)

    # 15 封底
    s = prs.slides.add_slide(prs.slide_layouts[6])
    rect(s, 0, 0, SW, SH, INK)
    picture(s, MARK_LIGHT, M, 2.35, 1.35, 1.35)
    text(s, M, 4.05, 11.0, 0.6, "交付有据，一步到位", size=30, color=WHITE, bold=True, gap=0)
    rect(s, M, 4.95, 1.5, 0.055, GOLD)
    text(s, M, 5.3, 11.0, 0.9,
         ["蔡工FDE智能交付系统　·　品牌全案策划书 v1.0", "联系 / 官网 / 主体信息：待确认"],
         size=13, color="#B9C2CB", spacing=1.5, gap=0.6)

    out = os.path.join(DELIV, "蔡工FDE-品牌全案策划书.pptx")
    prs.save(out)
    return out, len(prs.slides)


# ============================ 交付件 2：C8 提案/演示 PPT 模板 ============================
def build_template():
    prs = new_deck()

    # 1 使用说明
    s = light_slide(prs, "C8 / TEMPLATE · v1.0", "提案 / 演示 PPT 模板　使用说明")
    bullets(s, M, 2.15, CW, [
        "16:9（13.333 × 7.5 in）；封面/封底为石墨黑深底 + 反白主标，内页为浅底",
        "每页金色只出现一处；深底金色用 #F5B44A 提亮，浅底强调色用金墨 #C98F2B",
        "所有 [[...]] 均为占位字段，须替换为真实值；本模板不含任何虚构联系方式或客户信息",
        "图表页：数据可视化色板（B3）尚未发布，只能用石墨阶/单色 + 文字标注，不得自行造色",
        "话术：13 阶段交付 SOP + G1–G9 门禁；禁用「九步交付法」；一段话介绍逐字引用 §〇",
        "本模板对应规范见 specs/C-数字载体补齐.md C8；发布审批与双语母版待确认",
    ], size=13.5, gap=0.75)

    # 2 封面（占位）
    s = dark_slide(prs, "[[提案类别 / 客户名称 · 占位]]", "[[提案标题 · 占位]]",
                   "[[副标题或一句话价值主张 · 占位]]")
    text(s, M, 5.6, 11.0, 0.9,
         ["交付有据，一步到位", "[[客户名称]]　｜　[[编制单位]]　｜　[[YYYY-MM-DD]]　｜　[[版本]]"],
         size=14, color="#B9C2CB", spacing=1.6, gap=0.7)

    # 3 内页 · 单栏（占位）
    s = light_slide(prs, "[[章节名 · 占位]]", "[[页面标题 · 占位]]",
                    "[[一句导语，说明本页要回答的问题 · 占位]]")
    rect(s, M, 2.35, CW, 3.9, "#F8F8F6", LINE)
    text(s, M + 0.35, 2.65, CW - 0.7, 3.3,
         ["[[正文要点一 · 占位]]", "[[正文要点二 · 占位]]", "[[正文要点三 · 占位]]",
          "", "[[结论 / 下一步 · 占位]]"],
         size=16, color=INK2, spacing=1.5, gap=0.9)
    rect(s, M, 2.35, 0.06, 3.9, GOLD_INK)

    # 4 内页 · 双栏（占位）
    s = light_slide(prs, "[[章节名 · 占位]]", "[[页面标题 · 占位]]")
    card(s, M, 2.2, 5.75, 3.8, "[[左栏标题 · 占位]]",
         ["[[左栏要点一]]", "[[左栏要点二]]", "[[左栏要点三]]"])
    card(s, M + 5.97, 2.2, 5.75, 3.8, "[[右栏标题 · 占位]]",
         ["[[右栏要点一]]", "[[右栏要点二]]", "[[右栏要点三]]"])
    text(s, M, 6.25, CW, 0.35, "[[页脚补充说明 · 占位]]", size=11, color=INK5, gap=0)

    # 5 图表页（占位；B3 条件待补）
    s = light_slide(prs, "[[章节名 · 占位]]", "[[图表页标题 · 占位]]",
                    "数据可视化色板（B3）未发布：本页只用石墨阶 / 单色 + 文字标注")
    rect(s, M, 2.35, 8.2, 3.75, "#F8F8F6", LINE)
    rect(s, M + 0.35, 2.7, 7.5, 0.035, GOLD_INK)
    text(s, M + 0.35, 3.1, 7.4, 2.5,
         ["[[图表占位框 · 单色 / 石墨阶]]", "[[系列名称用文字标注，不以颜色区分]]",
          "[[数据来源 / 口径说明 · 占位]]"],
         size=15, color=INK4, spacing=1.6, gap=1.0)
    rect(s, M + 8.5, 2.35, 3.25, 3.75, "#FBF3E2", "#F0D9AC")
    text(s, M + 8.75, 2.7, 2.8, 3.0,
         ["[[图注 · 占位]]", "", "⚠ 数据色板待 B3 发布", "禁止自行拼造序列色",
          "语义色不得借作序列色"],
         size=12.5, color=INK2, spacing=1.5, gap=0.65)

    # 6 封底（占位）
    s = prs.slides.add_slide(prs.slide_layouts[6])
    rect(s, 0, 0, SW, SH, INK)
    picture(s, MARK_LIGHT, M, 2.5, 1.25, 1.25)
    text(s, M, 4.15, 11.0, 0.55, "交付有据，一步到位", size=28, color=WHITE, bold=True, gap=0)
    rect(s, M, 4.95, 1.5, 0.055, GOLD)
    text(s, M, 5.3, 11.0, 1.0,
         ["[[联系人]]　｜　[[电话]]　｜　[[邮箱]]　｜　[[官网]]", "[[公司主体全称 · 待确认]]"],
         size=13, color="#B9C2CB", spacing=1.6, gap=0.7)

    out = os.path.join(DELIV, "caigong-fde-ppt-template.pptx")
    prs.save(out)
    return out, len(prs.slides)


def main():
    for fn in (build_plan, build_template):
        path, n = fn()
        print(f"PPTX {os.path.relpath(path, ROOT)}  ({n} slides, {os.path.getsize(path) // 1024} KB)")


if __name__ == "__main__":
    main()
