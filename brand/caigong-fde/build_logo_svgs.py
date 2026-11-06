# -*- coding: utf-8 -*-
"""
蔡工FDE 智能交付系统 — 品牌主标矢量资产生成器
基准：方案一（CG 环形主标），精修定稿几何。
输出：彩色主标 / 反白版 / 双单色版 / 纯图形 / 应用图标 / favicon，全部 SVG（无平台水印）。
"""
import math
import os

OUT = os.path.dirname(os.path.abspath(__file__))

# ---------- 品牌色 ----------
GRAPHITE = "#14181C"   # 石墨黑（主）
AMBER    = "#E8A33D"   # 琥珀金（辅）
AMBER_LT = "#F5B44A"   # 深底提亮金
WHITE    = "#FFFFFF"
NEUTRAL  = "#F2F4F5"   # 浅中性底

# ---------- 主标几何（viewBox 512 宽，画心 (256,200)）----------
CX, CY = 256.0, 200.0
R_OUT, R_IN = 100.0, 71.0
STROKE = R_OUT - R_IN          # 29
R_MID = (R_OUT + R_IN) / 2.0   # 85.5

TH_BLACK_START, TH_BLACK_END = 0.0, 300.0   # 黑色 C 形环
TH_GOLD_START,  TH_GOLD_END  = 305.0, 332.0 # 金色独立段
BAR_X0, BAR_X1 = 239.0, R_OUT + CX  # G 字横杠：左端略过中心，右端与环外缘齐平

CJK_FONT = "'Source Han Sans SC','Noto Sans SC','PingFang SC','Microsoft YaHei','Hiragino Sans GB',sans-serif"
LAT_FONT = "'Montserrat','Inter','Helvetica Neue',Arial,sans-serif"


def pt(th):
    r = math.radians(th)
    return CX + R_MID * math.cos(r), CY + R_MID * math.sin(r)


def arc_path(th0, th1):
    """顺时针（SVG sweep=1）圆弧。th 为数学角，y 向下故顺时针 = 角度递增。"""
    x0, y0 = pt(th0)
    x1, y1 = pt(th1)
    large = 1 if (th1 - th0) > 180 else 0
    return f"M {x0:.3f},{y0:.3f} A {R_MID:.3f},{R_MID:.3f} 0 {large} 1 {x1:.3f},{y1:.3f}"


def mark_group(color_main, color_accent, gid=None):
    """纯图形主体：黑色 C 环 + 金色独立段 + G 字横杠。"""
    uid = gid or "cg"
    return f"""  <g id="{uid}">
    <path d="{arc_path(TH_BLACK_START, TH_BLACK_END)}" fill="none" stroke="{color_main}" stroke-width="{STROKE}" stroke-linecap="butt"/>
    <path d="{arc_path(TH_GOLD_START, TH_GOLD_END)}" fill="none" stroke="{color_accent}" stroke-width="{STROKE}" stroke-linecap="butt"/>
    <path d="M {BAR_X0:.3f},{CY:.3f} L {BAR_X1:.3f},{CY:.3f}" fill="none" stroke="{color_main}" stroke-width="{STROKE}" stroke-linecap="butt"/>
  </g>"""


def lockup(color_main, color_accent, bg=None, cjk_size=66, lat_size=25, gid="cg"):
    """图形 + 中英双行字标（横版锁定组合）。viewBox 高度 460 容纳完整英文行。"""
    lat_w = 7
    lat_len = 12
    lat_total = lat_len * (lat_size * 0.62) + (lat_len - 1) * lat_w
    cjk_total = 2 * cjk_size + 3 * (cjk_size * 0.60) + 5 * 2
    maxw = max(lat_total, cjk_total)
    bg_rect = ""
    if bg:
        bg_rect = f'  <rect x="0" y="0" width="{maxw + 120:.1f}" height="460" fill="{bg}"/>\n'
    return f"""{bg_rect}{mark_group(color_main, color_accent, gid)}
  <text x="{CX:.1f}" y="{CY + R_OUT + 92:.1f}" text-anchor="middle"
        font-family="{CJK_FONT}" font-size="{cjk_size}" font-weight="700"
        letter-spacing="2" fill="{color_main}">蔡工FDE</text>
  <text x="{CX:.1f}" y="{CY + R_OUT + 134:.1f}" text-anchor="middle"
        font-family="{LAT_FONT}" font-size="{lat_size}" font-weight="600"
        letter-spacing="{lat_w}" fill="{color_main}">CAIGONG FDE</text>"""


def write(name, body, w, h, title, desc):
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-labelledby="t">
  <title id="t">{title}</title>
  <desc>{desc}</desc>
{body}
</svg>
"""
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    return path, len(svg)


written = []

# 1) 彩色主标（透明底，主用）
body = lockup(GRAPHITE, AMBER, gid="cg-master")
written.append(write("caigong-fde-logo-master.svg", body, 512, 460,
    "蔡工FDE 智能交付系统 — 主标", "CG 环形主标 + 中文标准字 + 英文字标，透明底，主用彩色版本"))

# 2) 反白版（深色背景用）
body = lockup(WHITE, AMBER_LT, gid="cg-inverse")
written.append(write("caigong-fde-logo-inverse.svg", body, 512, 460,
    "蔡工FDE 智能交付系统 — 反白版", "深色背景使用的反白主标，琥珀金提亮以保证暗底对比"))

# 3) 单色·深（黑白印刷 / 单色丝印）
body = lockup(GRAPHITE, GRAPHITE, gid="cg-mono-dark")
written.append(write("caigong-fde-logo-mono-dark.svg", body, 512, 460,
    "蔡工FDE 智能交付系统 — 单色深版", "全石墨黑单色版，供单色印刷、激光雕刻、合同页眉使用"))

# 4) 单色·浅（深底单色）
body = lockup(WHITE, WHITE, gid="cg-mono-light")
written.append(write("caigong-fde-logo-mono-light.svg", body, 512, 460,
    "蔡工FDE 智能交付系统 — 单色浅版", "全白单色版，供深色底单色印刷、烫白使用"))

# ---------- 图形标专用 viewBox：几何不在原点，必须按画心推导 ----------
MARK_VB = f"{CX - R_OUT:.0f} {CY - R_OUT:.0f} {R_OUT * 2:.0f} {R_OUT * 2:.0f}"  # "156 100 200 200"


def write_mark(name, body, title, desc):
    """纯图形标按 MARK_VB 输出（几何不在原点，不能用 0 0 w h）。"""
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{MARK_VB}" width="{R_OUT * 2:.0f}" height="{R_OUT * 2:.0f}" role="img" aria-labelledby="t">
  <title id="t">{title}</title>
  <desc>{desc}</desc>
{body}
</svg>
"""
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    return path, len(svg)


# 5) 纯图形（无字标，用于 app 图标/favicon/水印底纹）
mark_only = mark_group(GRAPHITE, AMBER, "cg-mark")
written.append(write_mark("caigong-fde-mark.svg", mark_only,
    "蔡工FDE — 图形标", "不含字标的纯图形标，可独立使用"))

# 5b) 反白纯图形（深色侧边栏 / 深底小尺寸）
mark_inv = mark_group(WHITE, AMBER_LT, "cg-mark-inverse")
written.append(write_mark("caigong-fde-mark-inverse.svg", mark_inv,
    "蔡工FDE — 图形标（反白）", "深色背景使用的反白纯图形标"))

# 6) 应用图标（1024 圆角方形深底 + 白金图形，图形占约 62% 视觉重量）
inner = f"""  <g transform="translate(512,512) scale(3.10) translate(-256,-200)">
{mark_group(WHITE, AMBER, "cg-app")}
  </g>"""
app_body = f"""  <rect x="0" y="0" width="1024" height="1024" rx="228" fill="{GRAPHITE}"/>
{inner}"""
written.append(write("caigong-fde-app-icon.svg", app_body, 1024, 1024,
    "蔡工FDE — 应用图标", "1024 圆角方形深底图标，白色图形 + 琥珀金段"))

# 7) favicon（32 网格，纯图形，自动裁切友好）
fav_body = f"""  <rect x="0" y="0" width="32" height="32" rx="7" fill="{GRAPHITE}"/>
  <g transform="translate(16,16) scale(0.115) translate(-256,-200)">
{mark_group(WHITE, AMBER, "cg-fav")}
  </g>"""
written.append(write("caigong-fde-favicon.svg", fav_body, 32, 32,
    "蔡工FDE — favicon", "32px 网格 favicon，图形居中，favicon 最小尺寸仍可辨识"))

for p, n in written:
    print(f"{os.path.basename(p):<40} {n:>6} bytes")
print(f"\n共 {len(written)} 个矢量文件 -> {OUT}")
