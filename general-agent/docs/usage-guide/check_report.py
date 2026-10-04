"""Inspect the local guide. Do not start the application or contact services."""

import asyncio
import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "index.html"
EVIDENCE = ROOT / "evidence"
VIEWPORTS = [(1440, 900), (1600, 1000), (1920, 1080), (2048, 1320),
             (768, 1024), (375, 812), (812, 375)]


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])


CONTRAST_JS = """() => {
  const rgb=s=>{const m=s.match(/[\\d.]+/g);return m?m.map(Number):[0,0,0,0]};
  const lum=c=>c.slice(0,3).map(x=>{x/=255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4}).reduce((a,x,i)=>a+x*[.2126,.7152,.0722][i],0);
  const background=el=>{let out=[255,255,255];const chain=[];for(let x=el;x;x=x.parentElement)chain.push(x);for(const x of chain.reverse()){const c=rgb(getComputedStyle(x).backgroundColor);const a=c.length>3?c[3]:1;out=out.map((v,i)=>v*(1-a)+c[i]*a)}return out};
  const failures=[];let checked=0,min=21;
  for(const el of document.querySelectorAll('main p,main li,main a,main button,main label,main summary,main td,main th,aside a,aside small,aside summary')){
    if(!el.getClientRects().length||!el.textContent.trim())continue;
    if(![...el.childNodes].some(n=>n.nodeType===3&&n.textContent.trim()))continue;
    const st=getComputedStyle(el);const fg=rgb(st.color),bg=background(el),a=lum(fg),b=lum(bg),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
    checked++;min=Math.min(min,ratio);if(ratio<4.5)failures.push({tag:el.tagName,text:el.textContent.trim().slice(0,80),ratio:+ratio.toFixed(2)});
  }
  return {checked,minimum_ratio:+min.toFixed(2),failures};
}"""


async def main():
    EVIDENCE.mkdir(exist_ok=True)
    original = REPORT.read_bytes()
    html = original.decode()
    refs = References()
    refs.feed(html)
    assert len(refs.ids) == len(set(refs.ids)), "Duplicate HTML IDs"
    broken = []
    for href in refs.links:
        url = urlsplit(href)
        if url.scheme:
            continue
        if not url.path:
            if url.fragment and url.fragment not in refs.ids:
                broken.append(href)
        elif not (ROOT / unquote(url.path)).exists():
            broken.append(href)
    assert not broken, broken
    embedded = []
    for name, filename in [("general", "general-assistant.html"), ("coding", "coding-workbench.html")]:
        match = re.search(rf'<script id="diagram-{name}"[^>]*>([^<]+)</script>', html)
        raw = base64.b64decode(match[1], validate=True)
        assert raw == (ROOT / "architecture" / filename).read_bytes()
        embedded.append({"diagram": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    assert "__ARCHIFY_" not in html
    receipt = {"artifact": {"file": str(REPORT), "bytes": len(original),
                           "sha256": hashlib.sha256(original).hexdigest()},
               "checked_at_utc": datetime.now(timezone.utc).isoformat(),
               "scope": "Local report only; no app server, model call, or connector action.",
               "local_links_checked": len(refs.links), "broken_links": broken,
               "embedded_diagrams": embedded, "layouts": [], "text_contrast": [],
               "interactions": {}, "browser_errors": [], "external_requests": []}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-background-networking", "--disable-component-update"])
        context = await browser.new_context(viewport={"width": 1440, "height": 900},
                                            accept_downloads=True, reduced_motion="reduce")
        async def guard(route):
            if urlsplit(route.request.url).scheme in {"http", "https"}:
                receipt["external_requests"].append(route.request.url)
                await route.abort()
            else:
                await route.continue_()
        await context.route("**/*", guard)
        page = await context.new_page()
        page.on("pageerror", lambda error: receipt["browser_errors"].append(str(error)))
        await page.goto(REPORT.as_uri())
        await page.wait_for_selector("#architecture-frame")
        await page.wait_for_timeout(350)
        for theme in ["light", "dark"]:
            if await page.locator("html").get_attribute("data-theme") != theme:
                await page.locator("#theme-toggle").click()
            for width, height in VIEWPORTS:
                await page.set_viewport_size({"width": width, "height": height})
                await page.reload()
                await page.wait_for_timeout(280)
                m = await page.evaluate("""() => ({width:innerWidth,height:innerHeight,
                  scroll_width:document.documentElement.scrollWidth,
                  scroll_height:document.documentElement.scrollHeight,
                  reduced_motion:matchMedia('(prefers-reduced-motion:reduce)').matches})""")
                m["theme"] = theme
                m["horizontal_overflow"] = m["scroll_width"] > width
                assert not m["horizontal_overflow"], m
                assert m["reduced_motion"]
                receipt["layouts"].append(m)
                if (width, height) in [(1440, 900), (375, 812)]:
                    await page.evaluate("scrollTo(0,0)")
                    await page.screenshot(path=str(EVIDENCE / f"guide-{width}x{height}-{theme}.png"))
            await page.set_viewport_size({"width": 1440, "height": 900})
            await page.evaluate("document.querySelectorAll('main details').forEach(d=>d.open=true)")
            contrast = await page.evaluate(CONTRAST_JS)
            contrast["theme"] = theme
            receipt["text_contrast"].append(contrast)
            assert not contrast["failures"], contrast["failures"]
            await page.evaluate("document.querySelectorAll('main details').forEach(d=>d.open=false)")
        # Keyboard search includes closed details; Escape clears it.
        await page.locator("#guide-search").fill("token refresh")
        assert await page.locator("#search-results a").count() >= 1
        await page.locator("#guide-search").press("Enter")
        assert await page.evaluate("location.hash") == "#connections"
        assert await page.locator("#connections details[open]").count() == 5
        await page.locator("#guide-search").focus()
        await page.locator("#guide-search").press("Escape")
        assert await page.locator("#guide-search").input_value() == ""
        await page.locator("#guide-search").fill("no-such-topic-4321")
        assert "No guide topics match" in await page.locator("#search-status").inner_text()
        await page.locator("#clear-search").click()
        receipt["interactions"]["search_keyboard_closed_topics_and_empty_state"] = "passed"
        await page.locator(".skip").focus()
        await page.locator(".skip").press("Enter")
        assert await page.evaluate("document.activeElement.id") == "main"
        receipt["interactions"]["keyboard_skip_link"] = "passed"
        await page.locator("#contents summary").click()
        assert not await page.locator("#chapter-nav").is_visible()
        await page.locator("#contents summary").press("Enter")
        assert await page.locator("#chapter-nav").is_visible()
        receipt["interactions"]["chapter_menu_pointer_and_keyboard"] = "passed"
        await page.locator("#review-1").check()
        assert "1 of 5" in await page.locator("#review-progress").inner_text()
        await page.locator("#review-1").uncheck()
        receipt["interactions"]["review_checklist_status"] = "passed"
        await page.get_by_role("button", name="Copy request", exact=True).first.click()
        await page.locator("#global-status").filter(has_text=re.compile("Copied|text is selected")).wait_for(timeout=5000)
        receipt["interactions"]["copy_feedback"] = "passed"
        await page.locator("#theme-toggle").click()
        assert await page.locator("#theme-toggle").get_attribute("aria-pressed") == "false"
        await page.reload()
        assert await page.locator("html").get_attribute("data-theme") == "light"
        receipt["interactions"]["theme_persistence"] = "passed"
        # Exact embedded bytes run as an independent document in the frame.
        for name in ["general", "coding"]:
            await page.locator("#diagram-choice").select_option(name)
            await page.locator("#architecture-frame").scroll_into_view_if_needed()
            await page.wait_for_timeout(250)
            frame = page.frame_locator("#architecture-frame")
            assert await frame.get_by_role("button", name="Find a node", exact=True).count() == 1
            for width, height in [(1440, 900), (375, 812)]:
                await page.set_viewport_size({"width": width, "height": height})
                await page.wait_for_timeout(600)
                m = await frame.locator("html").evaluate("""el => ({width:innerWidth,height:innerHeight,
                  scroll_width:el.scrollWidth,scroll_height:el.scrollHeight})""")
                assert m["scroll_width"] <= m["width"], m
                assert m["scroll_height"] <= m["height"] + 1, m
                receipt["interactions"][f"embedded_{name}_{width}"] = m
            await page.set_viewport_size({"width": 1440, "height": 900})
            await page.locator("#architecture-frame").scroll_into_view_if_needed()
            await page.mouse.move(10, 10)
            await page.wait_for_function("document.getElementById('global-status').textContent === ''", timeout=9000)
            await page.wait_for_timeout(160)
            await page.screenshot(path=str(EVIDENCE / f"guide-architecture-{name}.png"))
            async with page.expect_download() as info:
                await page.locator("#download-diagram").click()
            downloaded = EVIDENCE / f"download-{name}.html"
            await (await info.value).save_as(downloaded)
            assert downloaded.read_bytes() == base64.b64decode(re.search(rf'<script id="diagram-{name}"[^>]*>([^<]+)</script>', html)[1])
            downloaded.unlink()
        receipt["interactions"]["diagram_selection_and_exact_html_download"] = "passed"
        # Count instruction sentences separately from supporting descriptions.
        language = await page.evaluate("""() => ({
          instructions:[...document.querySelectorAll('[data-procedure] > li')].map(li=>li.querySelector('strong')?.textContent||li.textContent),
          descriptions:[...document.querySelectorAll('main p')].filter(p=>!p.classList.contains('source-link')).map(p=>p.textContent)
        })""")
        def long_sentences(values, maximum):
            result = []
            for text in values:
                for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
                    words = sentence.split()
                    if len(words) > maximum:
                        result.append({"words": len(words), "text": sentence})
            return result
        language_result = {"instruction_items": len(language["instructions"]),
                           "descriptive_paragraphs": len(language["descriptions"]),
                           "instruction_over_20": long_sentences(language["instructions"], 20),
                           "description_over_25": long_sentences(language["descriptions"], 25),
                           "note": "Approximate sentence count; not a formal STE dictionary audit."}
        receipt["language_principles"] = language_result
        assert not language_result["instruction_over_20"], language_result["instruction_over_20"]
        assert not language_result["description_over_25"], language_result["description_over_25"]
        await page.evaluate("dispatchEvent(new Event('beforeprint'))")
        await page.emulate_media(media="print")
        assert await page.locator(".sidebar").is_visible() is False
        assert await page.locator("#browser-setup .detail-content").is_visible()
        for theme in ["light", "dark"]:
            await page.locator("html").evaluate("(el, theme) => el.dataset.theme=theme", theme)
            contrast = await page.evaluate(CONTRAST_JS)
            contrast["theme"] = theme
            contrast["media"] = "print"
            receipt["text_contrast"].append(contrast)
            assert not contrast["failures"], contrast["failures"]
        await page.locator("html").evaluate("el => el.dataset.theme='light'")
        await page.emulate_media(media="screen")
        await page.evaluate("dispatchEvent(new Event('afterprint'))")
        receipt["interactions"]["print_expands_details_and_restores_state"] = "passed"
        assert not receipt["browser_errors"], receipt["browser_errors"]
        assert not receipt["external_requests"], receipt["external_requests"]
        assert REPORT.read_bytes() == original
        await context.close()
        await browser.close()
    receipt["status"] = "passed"
    receipt["visual_review"] = "pending independent image inspection"
    (EVIDENCE / "report-check.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": "passed", "layouts": len(receipt["layouts"]),
                      "external_requests": 0, "browser_errors": 0,
                      "receipt": str(EVIDENCE / "report-check.json")}))


if __name__ == "__main__":
    asyncio.run(main())
