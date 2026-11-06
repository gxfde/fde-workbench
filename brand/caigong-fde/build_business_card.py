# -*- coding: utf-8 -*-
"""
蔡工FDE — 名片双面印刷稿 v2（90×54mm + 四边 3mm 出血）
正面：石墨黑底 + 反白图形标（右）+ 姓名/职位（左下）
背面：浅底 + 主标锁定组合（图形+双行字标）+ slogan + 联系方式占位

布局纪律：
  - 画布 1152×720px @12px/mm（96×60mm 含出血）
  - 安全区：内容距画布边 ≥96px（=成品边内 5mm）
  - 缩放公式：scale = 目标高度px / 200（图形标 viewBox 高 200）
"""
import math
import os

OUT = os.path.dirname(os.path.abspath(__file__))

MM = 12
BLEED = 3
W = (90 + 2 * BLEED) * MM   # 1152
H = (54 + 2 * BLEED) * MM   # 720
SAFE = 8 * MM               # 96px：距画布边的安全边距

INK = "#14181C"
GOLD = "#E8A33D"
GOLD_LT = "#F5B44A"
PAPER = "#FAFAF8"
WHITE = "#FFFFFF"

CX, CY = 256.0, 200.0        # 图形标画心（viewBox 几何中心）
R_OUT, R_IN = 100.0, 71.0
STROKE = R_OUT - R_IN
R_MID = (R_OUT + R_IN) / 2.0
BAR_X0, BAR_X1 = 239.0, 356.0

CJK = "'Source Han Sans SC','Noto Sans SC','Microsoft YaHei',sans-serif"
LAT = "'Montserrat','Inter',Arial,sans-serif"


def pt(th):
    r = math.radians(th)
    return CX + R_MID * math.cos(r), CY + R_MID * math.sin(r)


def arc(th0, th1):
    x0, y0 = pt(th0)
    x1, y1 = pt(th1)
    large = 1 if (th1 - th0) > 180 else 0
    return f"M {x0:.2f},{y0:.2f} A {R_MID:.2f},{R_MID:.2f} 0 {large} 1 {x1:.2f},{y1:.2f}"


def mark(main, accent):
    return f"""    <path d="{arc(0, 300)}" fill="none" stroke="{main}" stroke-width="{STROKE}"/>
    <path d="{arc(305, 332)}" fill="none" stroke="{accent}" stroke-width="{STROKE}"/>
    <path d="M {BAR_X0},{CY} L {BAR_X1},{CY}" fill="none" stroke="{main}" stroke-width="{STROKE}"/>"""


def mark_at(cx, cy, height, main, accent):
    """把图形标放到指定中心点、指定像素高度。scale = height/200。"""
    s = height / 200.0
    return f"""  <g transform="translate({cx:.0f},{cy:.0f}) scale({s:.4f}) translate({-CX},{-CY})">
{mark(main, accent)}
  </g>"""


def card(name, body):
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
  <title>{name}</title>
{body}
</svg>
"""
    p = os.path.join(OUT, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(svg)
    return p


# ================= 正面：石墨黑底 =================
# 图形标：高 300px（25mm），中心在右半区垂直居中
mark_h = 300
mark_cx = W - SAFE - mark_h / 2 - 40   # 右缘留 40px 余量
mark_cy = H / 2 - 40

front = f"""  <rect width="{W}" height="{H}" fill="{INK}"/>
{mark_at(mark_cx, mark_cy, mark_h, WHITE, GOLD_LT)}
  <!-- 姓名块：左下安全区 -->
  <text x="{SAFE}" y="{H - SAFE - 190}" font-family="{CJK}" font-size="52" font-weight="700" letter-spacing="10" fill="{WHITE}">蔡 工</text>
  <text x="{SAFE}" y="{H - SAFE - 132}" font-family="{CJK}" font-size="26" font-weight="500" letter-spacing="3" fill="#B9C0C9">创始人 ｜ FDE 交付负责人</text>
  <rect x="{SAFE}" y="{H - SAFE - 96}" width="30" height="6" fill="{GOLD}"/>
  <text x="{SAFE}" y="{H - SAFE - 52}" font-family="{LAT}" font-size="21" font-weight="600" letter-spacing="6" fill="#8A929E">CAIGONG FDE</text>"""

# ================= 背面：浅底 =================
# 纵向预算（H=720，上安全区 96 起，下安全区 96 止）：
#   mark 180px（96–276）→ 中文标 340 → 英文标 384 → slogan 460 → 联系 536/578
m_h = 180
m_cx = W / 2
m_cy = 96 + m_h / 2
wm_y = 96 + m_h + 64                      # 中文标准字基线
lat_y = wm_y + 44                         # 英文字标基线
slogan_y = lat_y + 76                     # slogan 独立一行
# 联系方式：底部两行
c1_y = H - SAFE - 88
c2_y = c1_y + 42

back = f"""  <rect width="{W}" height="{H}" fill="{PAPER}"/>
{mark_at(m_cx, m_cy, m_h, INK, GOLD)}
  <text x="{W / 2}" y="{wm_y}" text-anchor="middle" font-family="{CJK}" font-size="54" font-weight="700" letter-spacing="4" fill="{INK}">蔡工FDE智能交付系统</text>
  <text x="{W / 2}" y="{lat_y}" text-anchor="middle" font-family="{LAT}" font-size="23" font-weight="600" letter-spacing="9" fill="#6B7280">CAIGONG FDE</text>
  <text x="{W / 2}" y="{slogan_y}" text-anchor="middle" font-family="{CJK}" font-size="32" font-weight="600" letter-spacing="10" fill="{GOLD}">交付有据，一步到位</text>
  <!-- 联系方式占位 -->
  <g font-family="{CJK}" font-size="20" fill="#565F6B">
    <text x="{SAFE}" y="{c1_y}">电话：138-XXXX-XXXX　｜　邮箱：caigong@XXXX.com</text>
    <text x="{SAFE}" y="{c2_y}">微信：caigong-fde　｜　h2-home.com</text>
  </g>
  <!-- 右下角小图形标 -->
{mark_at(W - SAFE - 30, H - SAFE - 34, 60, INK, GOLD)}"""

p1 = card("caigong-fde-card-front.svg", front)
p2 = card("caigong-fde-card-back.svg", back)
print("wrote:", os.path.basename(p1), os.path.basename(p2))
print(f"front mark: h={mark_h} center=({mark_cx:.0f},{mark_cy:.0f})")
print(f"back mark: h={m_h} center=({m_cx:.0f},{m_cy:.0f}); wm_y={wm_y}; slogan_y={slogan_y}")
