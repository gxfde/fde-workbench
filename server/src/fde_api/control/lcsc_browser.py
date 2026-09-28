"""Bounded, read-only Chromium search of the public LCSC storefront."""
from __future__ import annotations

import os
import re
from time import monotonic
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from fde_api.control.service import ControlServiceError


HOME = "https://www.szlcsc.com/"
ALLOWED_HOSTS = {"www.szlcsc.com", "so.szlcsc.com", "item.szlcsc.com"}
QUERY_PATTERN = re.compile(r"^[^\x00-\x1f\x7f]{1,120}$")


def _safe_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password:
        raise ControlServiceError("lcsc_navigation_blocked", "立创页面跳转到了未授权站点，查询已停止。", 409)
    return value


def search_storefront(query: str, *, max_results: int = 5, steps: list[dict] | None = None) -> tuple[list[dict], list[dict], str]:
    """Search through the public UI; no undocumented site API or login session."""
    if not isinstance(query, str) or not QUERY_PATTERN.fullmatch(query.strip()):
        raise ControlServiceError("invalid_request", "搜索词需为 1–120 个可见字符。", 400)
    query = query.strip()
    steps = steps if steps is not None else []
    started = monotonic()

    def log(action: str, detail: str, **extra):
        steps.append({"at_ms": round((monotonic() - started) * 1000), "action": action,
                      "detail": detail, **extra})

    try:
        with sync_playwright() as playwright:
            launch = {"headless": True}
            executable = os.environ.get("FDE_LCSC_CHROMIUM_PATH")
            if executable:
                launch["executable_path"] = executable
            browser = playwright.chromium.launch(**launch)
            try:
                context = browser.new_context(accept_downloads=False, service_workers="block")
                context.set_default_timeout(12_000)
                page = context.new_page()
                page.on("popup", lambda popup: popup.close())
                page.goto(HOME, wait_until="domcontentloaded", timeout=25_000)
                _safe_url(page.url)
                log("navigate", "打开立创商城首页", url=HOME)
                search_box = page.locator("input[placeholder]").first
                search_box.fill(query)
                log("fill", "在搜索栏输入用户指定内容", value=query)
                page.get_by_role("button", name="搜索").first.click(timeout=10_000)
                page.wait_for_url("https://so.szlcsc.com/**", timeout=20_000)
                _safe_url(page.url)
                log("click", "点击搜索并打开结果页", url=page.url)
                page.locator(".product-group-leader").first.wait_for(state="visible", timeout=15_000)
                raw = page.locator(".product-group-leader").evaluate_all("""(nodes, args) => nodes.slice(0, args.limit).map((node) => {
                  const links = [...node.querySelectorAll('a[href]')].filter(a => a.href.startsWith('https://item.szlcsc.com/') && a.textContent.trim());
                  const normalized = s => s.toUpperCase().replace(/[^A-Z0-9]/g, '');
                  const link = links.find(a => normalized(a.textContent.trim()) === normalized(args.query)) ||
                    links.find(a => a.textContent.trim().length > 4 && !['爆款','立推'].includes(a.textContent.trim())) || links[0];
                  return {text: node.innerText.slice(0, 2400), title: link?.textContent.trim() || '', url: link?.href || ''};
                })""", {"limit": max_results, "query": query})
                products = []
                for item in raw:
                    if not item["title"] or not item["url"]:
                        continue
                    products.append({"title": item["title"][:160], "url": _safe_url(item["url"]),
                                     "visible_text": item["text"]})
                log("extract", "读取公开结果卡片", count=len(products))
                return products, steps, page.url
            finally:
                browser.close()
                log("close", "关闭本次隔离浏览器会话")
    except ControlServiceError:
        raise
    except PlaywrightError as error:
        raise ControlServiceError("lcsc_browser_failed", "立创页面当前无法由浏览器完成查询，请稍后重试。", 502) from error
