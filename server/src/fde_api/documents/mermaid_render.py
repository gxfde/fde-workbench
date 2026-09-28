"""Bounded offline renderer subprocess. Never load user URLs or configuration."""
import json
import os
from pathlib import Path
import re
import sys


def prepare(source):
    if len(source) > 20000: raise ValueError("Diagram too large")
    def strip_init(match):
        value = json.loads(match[1])
        if not isinstance(value, dict): raise ValueError("Invalid configuration")
        return ""
    source = re.sub(r"^\s*%%\{\s*init\s*:\s*([\s\S]*?)\}%%\s*$", strip_init, source, flags=re.M | re.I)
    def strip_style(match):
        properties = match[1].strip().rstrip(";").split(",")
        if not all(re.fullmatch(r"\s*(fill|stroke|color)\s*:\s*#(?:[\da-f]{3}|[\da-f]{4}|[\da-f]{6}|[\da-f]{8})\s*", x, re.I) for x in properties):
            raise ValueError("Unsupported styling")
        return ""
    source = re.sub(r"^[ \t]*classDef\s+[\w-]+\s+([^\n]*)$", strip_style, source, flags=re.M)
    if re.search(r"%%\s*\{|^\s*---|(?:^|[;\n])\s*(?:click|classDef|style|linkStyle)\b", source, re.M | re.I):
        raise ValueError("Unsupported directives")
    return source


def main():
    from playwright.sync_api import sync_playwright
    source = prepare(Path(sys.argv[1]).read_text())
    bundle = Path(os.environ.get("FDE_MERMAID_BUNDLE", str(Path(__file__).resolve().parents[4] / "resources/mermaid.min.js")))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 1000}, device_scale_factor=2)
            page.route("**/*", lambda route: route.abort())
            page.set_content('<html><meta charset="utf-8"><body style="margin:0;background:white"><div id="diagram"></div></body></html>')
            page.add_script_tag(path=str(bundle))
            page.evaluate("""async source => {
                mermaid.initialize({startOnLoad:false, securityLevel:'strict', maxEdges:500,
                    maxTextSize:20000, theme:'default', fontFamily:'Noto Sans CJK SC, sans-serif',
                    flowchart:{htmlLabels:true,useMaxWidth:false}});
                const {svg}=await mermaid.render('sow-diagram',source);
                document.getElementById('diagram').innerHTML=svg;
                await document.fonts.ready;
                const el=document.querySelector('svg'), box=el.viewBox.baseVal;
                if(box.width>6000 || box.height>10000) throw Error('Diagram too large');
                el.style.maxWidth='none'; el.setAttribute('width',box.width); el.setAttribute('height',box.height);
            }""", source)
            page.locator("#diagram svg").screenshot(path=sys.argv[2], timeout=20000)
        finally: browser.close()


if __name__ == "__main__": main()
