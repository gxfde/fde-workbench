# -*- coding: utf-8 -*-
"""
生成 C7 全员统一邮件签名 HTML（字段全部为占位，不填虚构信息）。
前置：node render_pdf.mjs 已生成 assets/mark-64.png
用法：python build_signature.py
"""
import base64
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
PNG = os.path.join(ROOT, "assets", "mark-64.png")
OUT = os.path.join(ROOT, "assets", "email-signature.html")

if not os.path.exists(PNG):
    raise SystemExit("缺少 assets/mark-64.png，请先运行 node render_pdf.mjs")

data_uri = "data:image/png;base64," + base64.b64encode(open(PNG, "rb").read()).decode("ascii")

HTML = """<!doctype html>
<!--
  蔡工FDE智能交付系统 — 全员统一邮件签名模板 (C7 / v1.0 / 2026-11-05)
  ------------------------------------------------------------------
  · 所有 [[...]] 均为占位符，必须由业务方提供真实值后替换；本模板不含任何虚构信息。
  · 图片默认内联 data-URI（Apple Mail / Thunderbird / 部分 Webmail 可用）。
    Gmail / Outlook 桌面端不支持 data-URI，请改为可公开访问的 HTTPS 地址：
    把下方 img 的 src 换成 [[LOGO_HTTPS_URL]]，并把 PNG 托管到该地址。
  · 全内联 CSS，宽度 600px，不使用 web font、二维码、追踪像素。
  · 规范见 BRAND-ASSET-CHECKLIST.md C7 / specs/C-数字载体补齐.md C7。
-->
<html lang="zh-CN"><head><meta charset="utf-8">
<title>蔡工FDE 邮件签名模板（占位版）</title></head>
<body style="margin:0;padding:0;background:#FFFFFF;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0"
       style="width:600px;max-width:600px;border-collapse:collapse;font-family:'Microsoft YaHei','Noto Sans SC',Arial,sans-serif;">
  <tr>
    <!-- 左列：纯图形标 -->
    <td valign="middle" style="width:76px;padding:0 14px 0 0;border-right:2px solid #E8A33D;">
      <img src="__DATA_URI__" width="56" height="56" alt="蔡工FDE"
           style="display:block;width:56px;height:56px;border:0;">
    </td>
    <!-- 右列：信息 -->
    <td valign="middle" style="padding:0 0 0 16px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
        <tr><td style="font-size:15px;font-weight:700;color:#14181C;line-height:1.5;">
          [[姓名]]&nbsp;&nbsp;<span style="font-size:12px;font-weight:400;color:#5A626D;">[[职位]]</span>
        </td></tr>
        <tr><td style="font-size:12px;color:#3A4048;line-height:1.7;">
          蔡工FDE智能交付系统
        </td></tr>
        <tr><td style="font-size:12px;color:#3A4048;line-height:1.7;font-variant-numeric:tabular-nums;">
          电话 [[电话]]　｜　[[邮箱]]　｜　[[官网域名]]
        </td></tr>
        <tr><td style="font-size:12px;color:#3A4048;line-height:1.7;">
          [[公司主体全称 · 待确认]]
        </td></tr>
      </table>
    </td>
  </tr>
  <tr>
    <td colspan="2" style="padding:10px 0 0 0;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
        <tr>
          <td style="width:120px;height:2px;background:#E8A33D;font-size:0;line-height:0;">&nbsp;</td>
          <td style="font-size:11px;color:#6B7280;padding-left:12px;letter-spacing:0.06em;">
            交付有据，一步到位
          </td>
        </tr>
      </table>
    </td>
  </tr>
  <!-- 免责声明：法务措辞待确认，确认前请保持注释状态
  <tr><td colspan="2" style="font-size:10px;color:#8A929E;padding-top:10px;line-height:1.6;">
    [[保密声明 · 法务确认后启用]]
  </td></tr>
  -->
</table>
</body></html>
""".replace("__DATA_URI__", data_uri)

with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    f.write(HTML)
print("written:", os.path.relpath(OUT, ROOT), f"({len(HTML) // 1024} KB, data-URI 内嵌)")
