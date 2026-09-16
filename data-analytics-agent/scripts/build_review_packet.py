#!/usr/bin/env python3
"""Build a self-contained, accessible reading packet from the two review sources."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = (
    (
        "architecture-review",
        "Architecture & product review",
        ROOT / "doc/reviews/design-review-2026-09-10.md",
        "The baseline assessment of the current agent's architecture and product direction.",
    ),
    (
        "data-plugin-review",
        "Data plugin comparative review",
        ROOT / "doc/reviews/data-plugin-comparative-review-2026-09-14.md",
        "A detailed comparison with the official Data plugin and a practical adoption path.",
    ),
)
OUTPUT = ROOT / "doc/reviews/review-packet.html"

FENCE = re.compile(r"^```(?P<language>[\w-]*)\s*$")
HEADING = re.compile(r"^(?P<level>#{1,6})\s+(?P<text>.+?)\s*$")
ORDERED = re.compile(r"^\s*\d+\.\s+(?P<text>.+)$")
UNORDERED = re.compile(r"^\s*[-*]\s+(?P<text>.+)$")
TABLE_SEPARATOR = re.compile(r"^\|\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|\s*$")
INLINE = re.compile(r"(\*\*.+?\*\*|`.+?`|\[.+?\]\([^\s)]+\))")


def slug(value: str) -> str:
    compact = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return compact or "section"


def inline(value: str) -> str:
    """Render the small Markdown subset used by the two authored reports."""

    parts: list[str] = []
    for part in INLINE.split(value):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            parts.append(f"<strong>{html.escape(part[2:-2])}</strong>")
        elif part.startswith("`") and part.endswith("`"):
            parts.append(f"<code>{html.escape(part[1:-1])}</code>")
        elif part.startswith("["):
            label, target = part[1:].split("](", 1)
            target = target[:-1]
            if target.startswith(("https://", "http://", "/")):
                parts.append(
                    f'<a href="{html.escape(target, quote=True)}">{html.escape(label)}</a>'
                )
            else:
                parts.append(html.escape(part))
        else:
            parts.append(html.escape(part))
    return "".join(parts)


def cells(line: str) -> list[str]:
    return [item.strip() for item in line.strip().strip("|").split("|")]


def render_markdown(markdown: str, report_id: str) -> tuple[str, list[tuple[int, str, str]]]:
    lines = markdown.splitlines()
    output: list[str] = []
    headings: list[tuple[int, str, str]] = []
    paragraph: list[str] = []
    heading_counts: dict[str, int] = {}
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{'<br>'.join(inline(line) for line in paragraph)}</p>")
            paragraph.clear()

    while index < len(lines):
        current = lines[index]
        fence = FENCE.match(current)
        if fence:
            flush_paragraph()
            language = fence.group("language") or "text"
            code: list[str] = []
            index += 1
            while index < len(lines) and not FENCE.match(lines[index]):
                code.append(lines[index])
                index += 1
            output.append(
                '<pre class="code-block" data-language="'
                + html.escape(language, quote=True)
                + '"><code>'
                + html.escape("\n".join(code))
                + "</code></pre>"
            )
        elif not current.strip():
            flush_paragraph()
        elif (match := HEADING.match(current)):
            flush_paragraph()
            level = len(match.group("level"))
            text = match.group("text")
            base = slug(text)
            heading_counts[base] = heading_counts.get(base, 0) + 1
            suffix = "" if heading_counts[base] == 1 else f"-{heading_counts[base]}"
            anchor = f"{report_id}-{base}{suffix}"
            headings.append((level, text, anchor))
            output.append(f"<h{level} id=\"{anchor}\">{inline(text)}</h{level}>")
        elif (
            index + 1 < len(lines)
            and current.startswith("|")
            and TABLE_SEPARATOR.match(lines[index + 1])
        ):
            flush_paragraph()
            headers = cells(current)
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].startswith("|"):
                rows.append(cells(lines[index]))
                index += 1
            header_html = "".join(f"<th scope=\"col\">{inline(value)}</th>" for value in headers)
            body_html = "".join(
                "<tr>"
                + "".join(f"<td>{inline(value)}</td>" for value in row)
                + "</tr>"
                for row in rows
            )
            output.append(
                '<div class="table-wrap" tabindex="0" aria-label="Scrollable comparison table">'
                f"<table><thead><tr>{header_html}</tr></thead><tbody>{body_html}</tbody></table></div>"
            )
            continue
        elif UNORDERED.match(current) or ORDERED.match(current):
            flush_paragraph()
            ordered = bool(ORDERED.match(current))
            tag = "ol" if ordered else "ul"
            items: list[str] = []
            while index < len(lines):
                match = ORDERED.match(lines[index]) if ordered else UNORDERED.match(lines[index])
                if not match:
                    break
                items.append(f"<li>{inline(match.group('text'))}</li>")
                index += 1
            output.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue
        else:
            paragraph.append(current.strip())
        index += 1

    flush_paragraph()
    return "\n".join(output), headings


def toc_items(headings: list[tuple[int, str, str]]) -> str:
    chosen = [item for item in headings if item[0] in (2, 3)]
    return "".join(
        f'<li class="toc-level-{level}"><a href="#{anchor}">{html.escape(text)}</a></li>'
        for level, text, anchor in chosen
    )


def report_section(report_id: str, title: str, summary: str, markdown: str) -> str:
    rendered, headings = render_markdown(markdown, report_id)
    return f"""
<article class="report" id="{report_id}" data-report="{report_id}" aria-labelledby="{report_id}-title">
  <header class="report-header">
    <p class="eyebrow">Detailed review</p>
    <h1 id="{report_id}-title">{html.escape(title)}</h1>
    <p class="report-summary">{html.escape(summary)}</p>
  </header>
  <div class="report-layout">
    <aside class="section-nav" aria-label="{html.escape(title)} contents">
      <p class="nav-label">On this page</p>
      <ol>{toc_items(headings)}</ol>
    </aside>
    <div class="report-content">{rendered}</div>
  </div>
  <details class="source-markdown">
    <summary>View the original Markdown source</summary>
    <pre><code>{html.escape(markdown)}</code></pre>
  </details>
</article>"""


def build() -> None:
    reports = []
    for report_id, title, path, summary in REPORTS:
        reports.append((report_id, title, summary, path.read_text(encoding="utf-8")))
    report_html = "\n".join(
        report_section(report_id, title, summary, markdown)
        for report_id, title, summary, markdown in reports
    )
    source_payload = json.dumps(
        {report_id: markdown for report_id, _title, _summary, markdown in reports},
        ensure_ascii=False,
    ).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    OUTPUT.write_text(
        HTML.replace("__REPORTS__", report_html).replace("__SOURCE_PAYLOAD__", source_payload),
        encoding="utf-8",
    )


HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="A detailed, mobile-friendly packet containing two data analytics architecture reviews.">
  <title>Data Analytics Agent — Review Packet</title>
  <style>
    :root { --ink:#172033; --muted:#526078; --paper:#fffdf9; --canvas:#f3f0e8; --line:#d9d4c7; --accent:#8a4d14; --accent-deep:#5f320c; --accent-soft:#f4e7d0; --focus:#155e75; --max:76rem; --reading:46rem; --shadow:0 16px 44px rgba(31, 41, 55, .10); }
    * { box-sizing:border-box; }
    html { scroll-behavior:smooth; }
    body { margin:0; min-width:320px; background:var(--canvas); color:var(--ink); font:18px/1.68 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    a { color:var(--accent-deep); text-decoration-thickness:.1em; text-underline-offset:.16em; }
    a:hover { color:var(--accent); }
    a:focus-visible, button:focus-visible, summary:focus-visible, .table-wrap:focus-visible { outline:3px solid var(--focus); outline-offset:3px; }
    .skip-link { position:absolute; left:1rem; top:-5rem; z-index:5; padding:.6rem .85rem; border-radius:.35rem; background:#fff; color:var(--ink); font-weight:700; }
    .skip-link:focus { top:1rem; }
    .hero { padding:clamp(2.5rem, 8vw, 6.5rem) 1.25rem clamp(1.75rem, 5vw, 4rem); background:linear-gradient(128deg, #172033 0%, #26324b 63%, #5f320c 190%); color:#fffdf9; }
    .hero-inner { max-width:var(--max); margin:auto; }
    .eyebrow { margin:0 0:.7rem; color:inherit; font-size:.78rem; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }
    .hero h1 { max-width:18ch; margin:0; font-family:Georgia, "Times New Roman", serif; font-size:clamp(2.35rem, 7vw, 5.2rem); line-height:1.01; letter-spacing:-.04em; }
    .hero p:not(.eyebrow) { max-width:50rem; margin:1.2rem 0 0; color:#e5e7eb; font-size:clamp(1.04rem, 2.8vw, 1.32rem); }
    .meta { display:flex; flex-wrap:wrap; gap:.55rem 1rem; margin-top:1.5rem; color:#e5e7eb; font-size:.9rem; }
    .meta span { display:flex; gap:.45rem; align-items:center; }
    .meta span::before { width:.4rem; height:.4rem; border-radius:50%; background:#fbbf24; content:""; }
    .packet-nav { position:sticky; top:0; z-index:3; border-bottom:1px solid var(--line); background:rgba(255,253,249,.96); backdrop-filter:blur(12px); }
    .packet-nav-inner { max-width:var(--max); margin:auto; display:flex; align-items:center; gap:.75rem; padding:.65rem 1.25rem; overflow-x:auto; }
    .packet-nav p { flex:0 0 auto; margin:0 .15rem 0 0; color:var(--muted); font-size:.82rem; font-weight:700; }
    .packet-nav button { min-height:44px; flex:0 0 auto; border:1px solid transparent; border-radius:999px; padding:.55rem .85rem; background:transparent; color:var(--ink); cursor:pointer; font:inherit; font-size:.88rem; font-weight:700; }
    .packet-nav button[aria-pressed="true"] { border-color:#d7a96b; background:var(--accent-soft); color:var(--accent-deep); }
    main { max-width:var(--max); margin:auto; padding:clamp(1.25rem, 4vw, 3rem) 1.25rem 4rem; }
    .reader-note { max-width:var(--reading); margin:0 auto clamp(2.5rem, 5vw, 4rem); padding:1rem 1.15rem; border-left:4px solid var(--accent); background:#fff8eb; color:#3e4657; font-size:.95rem; }
    .reader-note strong { color:var(--ink); }
    .report { scroll-margin-top:5.5rem; }
    .report + .report { margin-top:clamp(4rem, 9vw, 8rem); padding-top:clamp(3rem, 7vw, 6rem); border-top:1px solid var(--line); }
    .report[hidden] { display:none; }
    .report-header { max-width:var(--reading); margin:0 auto 2.5rem; }
    .report-header .eyebrow { color:var(--accent-deep); }
    .report-header h1 { margin:0; font-family:Georgia, "Times New Roman", serif; font-size:clamp(2rem, 5vw, 3.55rem); line-height:1.1; letter-spacing:-.035em; }
    .report-summary { margin:1rem 0 0; color:var(--muted); font-size:1.08rem; }
    .report-layout { display:grid; grid-template-columns:minmax(0, 12rem) minmax(0, var(--reading)); justify-content:center; gap:clamp(1.5rem, 5vw, 4rem); }
    .section-nav { align-self:start; position:sticky; top:5.25rem; max-height:calc(100vh - 6rem); overflow:auto; padding:.9rem 0; }
    .nav-label { margin:0 0:.5rem; color:var(--muted); font-size:.8rem; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
    .section-nav ol { margin:0; padding:0; list-style:none; font-size:.8rem; line-height:1.35; }
    .section-nav li { margin:.35rem 0; }
    .section-nav .toc-level-3 { margin-left:.7rem; font-size:.92em; }
    .section-nav a { color:var(--muted); text-decoration:none; }
    .section-nav a:hover { color:var(--accent-deep); text-decoration:underline; }
    .report-content { min-width:0; }
    .report-content > :first-child { margin-top:0; }
    .report-content h1, .report-content h2, .report-content h3 { color:var(--ink); font-family:Georgia, "Times New Roman", serif; line-height:1.16; letter-spacing:-.022em; scroll-margin-top:5.5rem; }
    .report-content h2 { margin:3.2rem 0 1rem; font-size:clamp(1.55rem, 3.5vw, 2.25rem); }
    .report-content h3 { margin:2.2rem 0 .75rem; font-size:clamp(1.22rem, 3vw, 1.48rem); }
    .report-content p { margin:1rem 0; overflow-wrap:anywhere; }
    .report-content ul, .report-content ol { margin:1rem 0; padding-left:1.4rem; }
    .report-content li + li { margin-top:.45rem; }
    .report-content code { padding:.08em .3em; border-radius:.25rem; background:#eeeae1; font: .88em/1.2 ui-monospace, SFMono-Regular, Consolas, monospace; overflow-wrap:anywhere; }
    .table-wrap { margin:1.4rem 0; overflow-x:auto; border:1px solid var(--line); border-radius:.55rem; background:var(--paper); box-shadow:0 2px 8px rgba(31,41,55,.04); }
    table { width:100%; border-collapse:collapse; min-width:38rem; font-size:.85rem; line-height:1.48; }
    th, td { padding:.75rem .85rem; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; overflow-wrap:anywhere; }
    th { position:sticky; top:0; background:#f0ece2; color:#26324b; font-size:.76rem; letter-spacing:.02em; text-transform:uppercase; }
    tr:last-child td { border-bottom:0; }
    .code-block { position:relative; margin:1.4rem 0; padding:1.15rem; overflow:auto; border:1px solid #d8d5cd; border-radius:.55rem; background:#202938; color:#edf2f7; font: .8rem/1.55 ui-monospace, SFMono-Regular, Consolas, monospace; white-space:pre; }
    .code-block::before { position:sticky; left:0; display:block; width:max-content; margin:-.15rem 0 .65rem; color:#cbd5e1; content:attr(data-language); font:700 .7rem/1 ui-sans-serif, system-ui, sans-serif; letter-spacing:.08em; text-transform:uppercase; }
    .source-markdown { max-width:var(--reading); margin:3rem auto 0; border:1px solid var(--line); border-radius:.55rem; background:#f8f6f0; }
    .source-markdown summary { min-height:44px; display:flex; align-items:center; padding:.6rem .9rem; cursor:pointer; color:var(--accent-deep); font-size:.9rem; font-weight:750; }
    .source-markdown pre { margin:0; max-height:30rem; overflow:auto; padding:1rem; border-top:1px solid var(--line); background:#fff; font:.76rem/1.55 ui-monospace, SFMono-Regular, Consolas, monospace; white-space:pre-wrap; overflow-wrap:anywhere; }
    .footer { max-width:var(--reading); margin:4rem auto 0; padding-top:1.25rem; border-top:1px solid var(--line); color:var(--muted); font-size:.84rem; }
    @media (max-width: 850px) { body { font-size:17px; } .report-layout { display:block; } .section-nav { position:static; max-height:none; margin:0 0 1.8rem; padding:1rem; border:1px solid var(--line); border-radius:.55rem; background:#f8f6f0; } .section-nav ol { columns:2; column-gap:1.25rem; } .section-nav li { break-inside:avoid; } .report-content h2 { margin-top:2.6rem; } }
    @media (max-width: 520px) { .hero { padding-inline:1rem; } main { padding-inline:1rem; } .packet-nav-inner { padding-inline:1rem; } .packet-nav p { display:none; } .section-nav ol { columns:1; } .report-header h1 { font-size:2.1rem; } .report-content h2 { font-size:1.55rem; } th, td { padding:.65rem .7rem; } }
    @media print { body { background:#fff; color:#000; font-size:11pt; } .hero { padding:1cm; background:#fff; color:#000; border-bottom:2px solid #000; } .hero p:not(.eyebrow), .meta { color:#333; } .packet-nav, .section-nav, .reader-note, .source-markdown { display:none; } main { max-width:none; padding:0; } .report + .report { margin-top:2cm; padding-top:1cm; } .report-content { max-width:none; } .table-wrap { overflow:visible; } table { min-width:0; font-size:8pt; } th { position:static; background:#eee; } .code-block { white-space:pre-wrap; color:#000; background:#f4f4f4; } h2, h3 { break-after:avoid; } table, pre { break-inside:avoid; } }
    @media (prefers-reduced-motion: reduce) { html { scroll-behavior:auto; } * { transition:none !important; } }
  </style>
</head>
<body>
  <a class="skip-link" href="#packet-content">Skip to the review content</a>
  <header class="hero">
    <div class="hero-inner">
      <p class="eyebrow">Reader edition</p>
      <h1>Data analytics agent review packet</h1>
      <p>Two detailed architecture reviews, presented for focused reading on desktop or phone. The original Markdown is embedded in full within this offline file.</p>
      <div class="meta"><span>2 reports</span><span>5.6k words</span><span>Offline-ready</span><span>Mobile-friendly</span></div>
    </div>
  </header>
  <nav class="packet-nav" aria-label="Choose report display">
    <div class="packet-nav-inner">
      <p>Show</p>
      <button type="button" data-view="all" aria-pressed="true">Both reports</button>
      <button type="button" data-view="architecture-review" aria-pressed="false">Architecture review</button>
      <button type="button" data-view="data-plugin-review" aria-pressed="false">Data plugin review</button>
    </div>
  </nav>
  <main id="packet-content" tabindex="-1">
    <aside class="reader-note"><strong>Reading tip:</strong> Use the report selector above to focus on one review, or keep both visible for the complete packet. Tables scroll within their own cards on small screens. Every rendered report also includes its exact original Markdown source at the end.</aside>
    __REPORTS__
    <footer class="footer">Generated from the two canonical review files in this repository. This packet has no external fonts, scripts, analytics, or network dependency.</footer>
  </main>
  <script id="original-markdown" type="application/json">__SOURCE_PAYLOAD__</script>
  <script>
    (() => {
      const buttons = [...document.querySelectorAll('[data-view]')];
      const reports = [...document.querySelectorAll('[data-report]')];
      const setView = (view, moveFocus) => {
        reports.forEach((report) => { report.hidden = view !== 'all' && report.dataset.report !== view; });
        buttons.forEach((button) => { button.setAttribute('aria-pressed', String(button.dataset.view === view)); });
        if (moveFocus && view !== 'all') document.getElementById(view).scrollIntoView({ block: 'start' });
        const url = new URL(window.location);
        if (view === 'all') url.searchParams.delete('view'); else url.searchParams.set('view', view);
        history.replaceState(null, '', url);
      };
      buttons.forEach((button) => button.addEventListener('click', () => setView(button.dataset.view, true)));
      const requested = new URLSearchParams(window.location.search).get('view');
      if (requested && reports.some((report) => report.dataset.report === requested)) setView(requested, false);
    })();
  </script>
</body>
</html>'''


if __name__ == "__main__":
    build()
