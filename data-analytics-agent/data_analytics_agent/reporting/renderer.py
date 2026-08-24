"""Trusted deterministic renderer for standalone analytical HTML reports."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from datetime import datetime
import hashlib
from html import escape
import json
import re
from typing import Any

from plotly.io import to_html as plotly_to_html

from data_analytics_agent.agents.visualization.renderer import (
    ChartRenderStyle,
    build_chart,
)
from data_analytics_agent.agents.visualization.schemas import ChartType
from data_analytics_agent.agents.visualization.validation import (
    validate_chart_spec,
)
from data_analytics_agent.reporting.schemas import (
    ReportBlock,
    ReportCalloutBlock,
    ReportChartBlock,
    ReportInfographicBlock,
    ReportMetricsBlock,
    ReportNarrativeBlock,
    ReportSpec,
    ReportStatisticalBlock,
    ReportTableBlock,
    ResolvedStatisticalAnalysis,
)
from data_analytics_agent.schemas import SavedResult

_SCRIPT_PATTERN = re.compile(r"<script(?:\s[^>]*)?>(.*?)</script>", re.DOTALL)
_INLINE_PATTERN = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`")
REPORT_RENDERER_VERSION = "1.2"

# Report-owned semantic chart tokens. Every categorical color maintains at
# least 3:1 contrast against both the light and dark report surfaces.
_REPORT_CHART_DISCRETE = (
    "#2563EB",  # primary blue
    "#D97706",  # highlight amber
    "#0F766E",  # comparison teal
    "#9333EA",  # secondary violet
    "#DB2777",  # secondary rose
    "#4D7C0F",  # secondary olive
    "#0891B2",  # secondary cyan
)
_REPORT_CHART_CONTINUOUS = (
    "#E0F2FE",
    "#7DD3FC",
    "#0284C7",
    "#075985",
    "#082F49",
)
_REPORT_CHART_STYLE = ChartRenderStyle(
    discrete_colors=_REPORT_CHART_DISCRETE,
    continuous_colors=_REPORT_CHART_CONTINUOUS,
    show_title=False,
    font_family=(
        "Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "
        "Segoe UI, sans-serif"
    ),
)


def _inline_text(value: str) -> str:
    """Render a tiny safe inline subset after escaping model-authored text."""

    clean = escape(value)

    def replace(match: re.Match[str]) -> str:
        if match.group(1) is not None:
            return f"<strong>{match.group(1)}</strong>"
        return f"<code>{match.group(2)}</code>"

    return _INLINE_PATTERN.sub(replace, clean)


def _rich_text(value: str) -> str:
    """Render paragraphs and simple lists without accepting raw HTML."""

    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    chunks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    list_tag: str | None = None

    def flush_paragraph() -> None:
        if paragraph:
            chunks.append(f"<p>{'<br>'.join(paragraph)}</p>")
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if list_items and list_tag:
            chunks.append(
                f"<{list_tag}>"
                + "".join(f"<li>{item}</li>" for item in list_items)
                + f"</{list_tag}>"
            )
        list_items.clear()
        list_tag = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_list()
            continue
        unordered = line.startswith(("- ", "* "))
        ordered_match = re.match(r"^\d+\.\s+(.+)$", line)
        if unordered or ordered_match:
            flush_paragraph()
            desired_tag = "ul" if unordered else "ol"
            if list_tag and list_tag != desired_tag:
                flush_list()
            list_tag = desired_tag
            item = line[2:] if unordered else ordered_match.group(1)
            list_items.append(_inline_text(item))
            continue
        flush_list()
        paragraph.append(_inline_text(line))
    flush_paragraph()
    flush_list()
    return "".join(chunks)


def _value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:,.6g}"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _table_html(
    result: SavedResult,
    *,
    title: str,
    caption: str | None,
    columns: Sequence[str],
    rows: Sequence[dict[str, Any]],
) -> str:
    header = "".join(f'<th scope="col">{escape(column)}</th>' for column in columns)
    body = "".join(
        "<tr>"
        + "".join(f"<td>{escape(_value(row.get(column)))}</td>" for column in columns)
        + "</tr>"
        for row in rows
    )
    caption_text = caption or (
        f"{len(rows):,} of {result.row_count:,} stored rows"
        if len(rows) != result.row_count
        else f"{result.row_count:,} stored rows"
    )
    empty = (
        '<p class="empty-state">This result contains no rows.</p>'
        if not rows
        else f'<div class="table-scroll"><table><caption>{escape(caption_text)}</caption>'
        f"<thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>"
    )
    return (
        '<section class="report-block table-block">'
        f"<h2>{escape(title)}</h2>{empty}</section>"
    )


def _narrative(block: ReportNarrativeBlock) -> str:
    title = f"<h2>{escape(block.title)}</h2>" if block.title else ""
    return (
        f'<section class="report-block narrative {block.emphasis}">'
        f"{title}{_rich_text(block.body)}</section>"
    )


def _metrics(block: ReportMetricsBlock) -> str:
    title = f"<h2>{escape(block.title)}</h2>" if block.title else ""
    items = "".join(
        '<article class="metric-card">'
        f'<p class="metric-label">{escape(metric.label)}</p>'
        f'<p class="metric-value">{escape(metric.value)}</p>'
        + (
            f'<p class="metric-change">{escape(metric.change)}</p>'
            if metric.change
            else ""
        )
        + (
            f'<p class="metric-context">{escape(metric.context)}</p>'
            if metric.context
            else ""
        )
        + "</article>"
        for metric in block.metrics
    )
    tablet_columns = min(block.columns, 3)
    mobile_columns = min(block.columns, 2)
    return (
        '<section class="report-block">'
        f"{title}<div class=\"metrics-grid\" style=\"--metric-columns:{block.columns};"
        f"--metric-tablet-columns:{tablet_columns};"
        f"--metric-mobile-columns:{mobile_columns}\">"
        f"{items}</div></section>"
    )


def _callout(block: ReportCalloutBlock) -> str:
    return (
        f'<aside class="report-block callout {block.variant}">'
        f"<h2>{escape(block.title)}</h2>{_rich_text(block.body)}</aside>"
    )


def _infographic(block: ReportInfographicBlock) -> str:
    introduction = (
        f'<div class="infographic-intro">{_rich_text(block.introduction)}</div>'
        if block.introduction
        else ""
    )
    items = "".join(
        '<article class="infographic-item">'
        f'<span class="item-index" aria-hidden="true">{index:02d}</span>'
        f"<h3>{escape(item.label)}</h3>"
        + (
            f'<p class="item-value">{escape(item.value)}</p>'
            if item.value
            else ""
        )
        + f"{_rich_text(item.description)}</article>"
        for index, item in enumerate(block.items, start=1)
    )
    return (
        f'<section class="report-block infographic {block.layout}">'
        f"<h2>{escape(block.title)}</h2>{introduction}"
        f'<div class="infographic-grid">{items}</div></section>'
    )


def _statistical(
    block: ReportStatisticalBlock,
    analysis: ResolvedStatisticalAnalysis,
) -> str:
    outputs: list[str] = []
    if block.include_outputs:
        for output in analysis.outputs:
            name = escape(str(output.get("name") or "Statistical output"))
            kind = str(output.get("kind") or "text")
            if kind == "figure" and output.get("image_base64"):
                media_type = output.get("media_type") or "image/png"
                outputs.append(
                    '<figure class="stat-figure">'
                    f'<img src="data:{escape(str(media_type))};base64,'
                    f'{escape(str(output["image_base64"]))}" alt="{name}">'
                    f"<figcaption>{name}</figcaption></figure>"
                )
            elif kind == "table":
                columns = [str(item) for item in output.get("columns") or []]
                rows = output.get("rows") or []
                header = "".join(
                    f'<th scope="col">{escape(column)}</th>' for column in columns
                )
                body = "".join(
                    "<tr>"
                    + "".join(
                        f"<td>{escape(_value(row.get(column)))}</td>"
                        for column in columns
                    )
                    + "</tr>"
                    for row in rows
                )
                outputs.append(
                    f"<h3>{name}</h3><div class=\"table-scroll\"><table>"
                    f"<thead><tr>{header}</tr></thead><tbody>{body}</tbody>"
                    "</table></div>"
                )
            elif kind == "scalar":
                outputs.append(
                    '<div class="stat-scalar">'
                    f"<span>{name}</span><strong>{escape(_value(output.get('value')))}</strong>"
                    "</div>"
                )
            else:
                outputs.append(
                    f"<h3>{name}</h3>{_rich_text(str(output.get('text') or ''))}"
                )
    assumptions = block.assumptions or analysis.assumptions
    interpretation = block.interpretation or analysis.interpretation
    method = block.method or analysis.method
    details: list[str] = []
    if method:
        details.append(f"<h3>Method</h3>{_rich_text(method)}")
    if assumptions:
        details.append(
            "<h3>Assumptions</h3><ul>"
            + "".join(f"<li>{_inline_text(item)}</li>" for item in assumptions)
            + "</ul>"
        )
    if interpretation:
        details.append(f"<h3>Interpretation</h3>{_rich_text(interpretation)}")
    warning_items = list(dict.fromkeys(analysis.warnings))
    warnings = (
        '<details class="analysis-warnings"><summary>'
        f"Analysis notes and limitations ({len(warning_items)})"
        "</summary><ul>"
        + "".join(
            f'<li class="analysis-warning">{escape(item)}</li>'
            for item in warning_items
        )
        + "</ul></details>"
        if warning_items
        else ""
    )
    return (
        '<section class="report-block statistical-block">'
        f"<h2>{escape(block.title)}</h2>{_rich_text(block.summary)}"
        f"{''.join(outputs)}{warnings}"
        + (
            '<details class="method-details"><summary>Method and assumptions</summary>'
            f"{''.join(details)}</details>"
            if details
            else ""
        )
        + "</section>"
    )


def _chart(
    block: ReportChartBlock,
    result: SavedResult,
    *,
    chart_index: int,
    include_plotly: bool,
) -> str:
    if block.chart.chart_type is ChartType.MAP:
        raise ValueError(
            "Offline report maps are not yet supported because geographic "
            "topology must also be embedded. Use a table or non-map chart."
        )
    validate_chart_spec(block.chart, result)
    rendered = build_chart(
        block.chart,
        result.rows,
        style=_REPORT_CHART_STYLE,
    )
    chart_html = plotly_to_html(
        rendered.figure,
        include_plotlyjs=True if include_plotly else False,
        full_html=False,
        div_id=f"report-chart-{chart_index}",
        config={
            "displaylogo": False,
            "responsive": True,
            "scrollZoom": False,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
    )
    warnings = "".join(
        f'<p class="chart-warning">{escape(item)}</p>'
        for item in rendered.warnings
    )
    data_table = ""
    if block.show_data_table:
        data_table = (
            '<details class="chart-data"><summary>Accessible chart data</summary>'
            + _table_html(
                result,
                title=f"Data for {block.chart.title}",
                caption="Data used by this chart",
                columns=result.columns,
                rows=result.rows,
            )
            + "</details>"
        )
    caption = (
        f"<figcaption>{escape(block.caption)}</figcaption>"
        if block.caption
        else ""
    )
    return (
        '<section class="report-block chart-block">'
        f"<h2>{escape(block.chart.title)}</h2>"
        f'<p class="chart-summary">{escape(block.summary)}</p>'
        f'<figure aria-label="{escape(block.summary)}">{chart_html}{caption}</figure>'
        f"{warnings}{data_table}</section>"
    )


def _font_stack(style: str) -> str:
    return {
        "editorial": "Georgia, 'Times New Roman', serif",
        "technical": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
        "humanist": "Optima, Candara, 'Segoe UI', sans-serif",
        "modern": "Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    }[style]


def _style(spec: ReportSpec) -> str:
    theme = spec.theme
    gap = {"spacious": "2rem", "balanced": "1.35rem", "dense": ".9rem"}[
        theme.density
    ]
    radius = {"square": "0", "soft": ".85rem", "rounded": "1.4rem"}[
        theme.corner_style
    ]
    return f"""
:root {{
  color-scheme: light dark;
  --primary: {theme.primary_color}; --accent: {theme.accent_color};
  --surface: {theme.surface_color}; --background: {theme.background_color};
  --text: {theme.text_color}; --muted: {theme.muted_color};
  --border: color-mix(in srgb, var(--text) 14%, transparent);
  --chart-grid: rgba(71, 85, 105, .24);
  --gap: {gap}; --radius: {radius}; --font: {_font_stack(theme.font_style)};
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{ margin: 0; background: var(--background); color: var(--text); font-family: var(--font); font-size: 16px; line-height: 1.62; }}
button, summary {{ font: inherit; }}
a {{ color: var(--primary); }}
.report-shell {{ width: calc(100% - clamp(1rem, 3vw, 3rem)); max-width: 1360px; margin: 0 auto; padding: clamp(.75rem, 2.5vw, 2.5rem) 0; }}
.report-hero {{ position: relative; overflow: hidden; padding: clamp(1.75rem, 4vw, 3.5rem) clamp(1.25rem, 3vw, 2.5rem); border-radius: calc(var(--radius) * 1.25); color: white; background: linear-gradient(135deg, var(--primary), color-mix(in srgb, var(--primary) 62%, #020617)); box-shadow: 0 24px 70px color-mix(in srgb, var(--primary) 24%, transparent); }}
.report-hero::after {{ content: ''; position: absolute; width: 24rem; height: 24rem; border-radius: 50%; right: -10rem; top: -12rem; background: color-mix(in srgb, var(--accent) 60%, transparent); filter: blur(2px); opacity: .55; }}
.eyebrow {{ margin: 0 0 .75rem; letter-spacing: .13em; text-transform: uppercase; font-size: .78rem; font-weight: 700; }}
h1, h2, h3 {{ line-height: 1.16; text-wrap: balance; }}
h1 {{ position: relative; z-index: 1; margin: 0; max-width: 22ch; font-size: clamp(2.15rem, 6vw, 4.9rem); letter-spacing: -.045em; overflow-wrap: anywhere; }}
.subtitle {{ position: relative; z-index: 1; max-width: 68ch; margin: 1.2rem 0 0; font-size: clamp(1.05rem, 2vw, 1.35rem); opacity: .9; }}
.report-meta {{ position: relative; z-index: 1; display: flex; flex-wrap: wrap; gap: .65rem 1.25rem; margin-top: 2rem; font-size: .88rem; opacity: .84; }}
.report-content {{ display: grid; gap: var(--gap); margin-top: var(--gap); }}
.report-block {{ min-width: 0; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: clamp(1.1rem, 2.25vw, 1.8rem); box-shadow: 0 12px 36px color-mix(in srgb, var(--text) 7%, transparent); }}
.report-block > :first-child {{ margin-top: 0; }} .report-block > :last-child {{ margin-bottom: 0; }}
.report-block h2 {{ margin: 0 0 1rem; font-size: clamp(1.35rem, 3vw, 2rem); letter-spacing: -.025em; }}
.report-block h3 {{ margin: 1.2rem 0 .45rem; font-size: 1.05rem; }}
.narrative.lead {{ font-size: clamp(1.08rem, 2vw, 1.3rem); }} .narrative.muted {{ color: var(--muted); }}
.metrics-grid {{ display: grid; grid-template-columns: repeat(var(--metric-columns), minmax(0, 1fr)); gap: .85rem; }}
.metric-card {{ min-width: 0; padding: 1rem; border-radius: calc(var(--radius) * .75); background: color-mix(in srgb, var(--primary) 7%, var(--surface)); border: 1px solid color-mix(in srgb, var(--primary) 17%, transparent); }}
.metric-label, .metric-context {{ color: var(--muted); }} .metric-label {{ margin: 0; font-size: .83rem; font-weight: 650; }}
.metric-value {{ margin: .25rem 0; font-size: clamp(1.55rem, 4vw, 2.45rem); line-height: 1.05; letter-spacing: -.04em; font-variant-numeric: tabular-nums; font-weight: 750; overflow-wrap: anywhere; }}
.metric-change {{ margin: .5rem 0 0; color: var(--primary); font-weight: 700; }} .metric-context {{ margin: .35rem 0 0; font-size: .82rem; }}
.callout {{ border-left: .38rem solid var(--primary); }} .callout.warning {{ border-left-color: #B45309; }} .callout.action {{ border-left-color: var(--accent); }}
.infographic-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: .9rem; }}
.infographic-item {{ position: relative; padding: 1.15rem; border-radius: calc(var(--radius) * .8); background: color-mix(in srgb, var(--primary) 6%, var(--surface)); border: 1px solid var(--border); }}
.item-index {{ color: var(--primary); font-size: .75rem; font-weight: 800; letter-spacing: .12em; }} .item-value {{ color: var(--accent); font-size: 1.65rem; line-height: 1.1; font-weight: 800; font-variant-numeric: tabular-nums; }}
.infographic.steps .infographic-item:not(:last-child)::after {{ content: '→'; position: absolute; right: -.72rem; top: 50%; color: var(--accent); font-weight: 900; z-index: 2; }}
.table-scroll {{ overflow-x: auto; border: 1px solid var(--border); border-radius: calc(var(--radius) * .65); }}
table {{ width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; font-size: .9rem; }}
caption {{ padding: .8rem 1rem; color: var(--muted); text-align: left; }} th, td {{ padding: .7rem .85rem; text-align: left; border-top: 1px solid var(--border); vertical-align: top; }} th {{ position: sticky; top: 0; background: color-mix(in srgb, var(--primary) 8%, var(--surface)); font-weight: 720; }} tbody tr:nth-child(even) {{ background: color-mix(in srgb, var(--text) 2.5%, transparent); }}
.chart-summary, figcaption {{ color: var(--muted); }} figure {{ margin: 0; }} figcaption {{ margin-top: .6rem; font-size: .88rem; }}
.chart-block .plotly-graph-div {{ max-width: 100%; }} .chart-data .report-block {{ margin-top: .75rem; padding: 0; border: 0; box-shadow: none; }}
.chart-warning {{ padding: .75rem 1rem; color: #7C2D12; background: #FFF7ED; border-radius: .65rem; }}
.analysis-warnings {{ padding: .25rem .9rem; color: #7C2D12; background: #FFF7ED; border-radius: .65rem; }} .analysis-warnings ul {{ margin-top: 0; }} .analysis-warning {{ margin: .45rem 0; }}
.stat-scalar {{ display: flex; justify-content: space-between; gap: 1rem; padding: .85rem 0; border-bottom: 1px solid var(--border); }} .stat-scalar strong {{ font-variant-numeric: tabular-nums; }}
.stat-figure img {{ display: block; width: 100%; height: auto; border-radius: calc(var(--radius) * .65); }}
details {{ margin-top: 1rem; }} summary {{ min-height: 44px; display: flex; align-items: center; cursor: pointer; color: var(--primary); font-weight: 700; }} summary:focus-visible, .theme-toggle:focus-visible {{ outline: 3px solid var(--accent); outline-offset: 3px; }}
.theme-toggle {{ position: fixed; z-index: 10; right: 1rem; bottom: 1rem; min-width: 44px; min-height: 44px; padding: .65rem .85rem; border: 1px solid var(--border); border-radius: 999px; background: var(--surface); color: var(--text); cursor: pointer; box-shadow: 0 8px 28px color-mix(in srgb, var(--text) 15%, transparent); }}
.report-footer {{ color: var(--muted); margin: 2rem auto 0; max-width: 72ch; text-align: center; font-size: .86rem; }}
.sql-queries {{ margin-top: var(--gap); }} .sql-queries-intro, .sql-query-meta {{ color: var(--muted); }}
.sql-query {{ padding-top: 1rem; border-top: 1px solid var(--border); }} .sql-query:first-of-type {{ margin-top: 1rem; }}
.sql-query h3 {{ margin: 0; }} .sql-query-meta {{ margin: .25rem 0 .65rem; font-size: .84rem; }}
.sql-query pre {{ max-width: 100%; margin: 0; padding: 1rem; overflow: auto; border: 1px solid var(--border); border-radius: calc(var(--radius) * .65); background: color-mix(in srgb, var(--text) 6%, var(--surface)); font-size: .82rem; line-height: 1.55; tab-size: 2; white-space: pre; }}
.sql-query pre code {{ padding: 0; background: transparent; }}
code {{ padding: .1rem .3rem; border-radius: .25rem; background: color-mix(in srgb, var(--text) 8%, transparent); }}
body[data-theme='dark'] {{ --surface: #111827; --background: #020617; --text: #F8FAFC; --muted: #CBD5E1; --border: #334155; --chart-grid: rgba(203, 213, 225, .24); }}
@media (prefers-color-scheme: dark) {{ body:not([data-theme='light']) {{ --surface: #111827; --background: #020617; --text: #F8FAFC; --muted: #CBD5E1; --border: #334155; --chart-grid: rgba(203, 213, 225, .24); }} }}
@media (max-width: 1100px) {{ .metrics-grid {{ grid-template-columns: repeat(var(--metric-tablet-columns), minmax(0, 1fr)); }} }}
@media (max-width: 700px) {{ .report-shell {{ width: calc(100% - 1rem); }} .report-hero {{ padding: 1.75rem 1.1rem; }} .metrics-grid {{ grid-template-columns: repeat(var(--metric-mobile-columns), minmax(0, 1fr)); }} .infographic.steps .infographic-item::after {{ display: none; }} .report-block {{ padding: 1.05rem; }} }}
@media (max-width: 430px) {{ .metrics-grid {{ grid-template-columns: 1fr; }} body {{ font-size: 16px; }} .sql-query pre {{ padding: .8rem; font-size: .78rem; }} }}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ scroll-behavior: auto !important; transition: none !important; animation: none !important; }} }}
@media print {{ .theme-toggle {{ display: none; }} body {{ background: white; color: #111827; }} .report-shell {{ width: 100%; max-width: none; padding: 0; }} .report-hero, .report-block {{ box-shadow: none; break-inside: avoid; }} .sql-query pre {{ white-space: pre-wrap; overflow-wrap: anywhere; }} details > * {{ display: block !important; }} }}
"""


def _sql_queries(results: Mapping[str, SavedResult]) -> str:
    """Render exact executed SQL without exposing opaque artifact IDs."""

    if not results:
        return ""
    query_items = "".join(
        '<article class="sql-query">'
        f"<h3>Query {index}: {escape(result.short_label)}</h3>"
        f'<p class="sql-query-meta">Returned {result.row_count:,} rows'
        + (
            " (truncated at the configured limit)"
            if result.truncated
            else ""
        )
        + "</p>"
        f'<pre aria-label="SQL for query {index}"><code class="language-sql">'
        f"{escape(result.executed_sql)}</code></pre></article>"
        for index, result in enumerate(results.values(), start=1)
    )
    return (
        '<section class="report-block sql-queries">'
        "<h2>SQL queries</h2>"
        '<p class="sql-queries-intro">Run these exact executed queries against '
        "the report data source to reproduce its inputs.</p>"
        f"{query_items}</section>"
    )


def _script_csp(document_body: str) -> str:
    hashes: list[str] = []
    for script in _SCRIPT_PATTERN.findall(document_body):
        digest = hashlib.sha256(script.encode("utf-8")).digest()
        hashes.append("'sha256-" + base64.b64encode(digest).decode("ascii") + "'")
    scripts = " ".join(dict.fromkeys(hashes)) or "'none'"
    return (
        "default-src 'none'; "
        f"script-src {scripts}; "
        "style-src 'unsafe-inline'; img-src data: blob:; font-src data:; "
        "connect-src 'none'; media-src data:; object-src 'none'; "
        "frame-src 'none'; base-uri 'none'; form-action 'none'"
    )


def render_report(
    spec: ReportSpec,
    *,
    results: Mapping[str, SavedResult],
    analyses: Mapping[str, ResolvedStatisticalAnalysis],
    generated_at: datetime,
) -> str:
    """Render a validated specification to one offline-capable HTML file."""

    block_html: list[str] = []
    chart_index = 0
    for block in spec.blocks:
        if isinstance(block, ReportNarrativeBlock):
            block_html.append(_narrative(block))
        elif isinstance(block, ReportMetricsBlock):
            block_html.append(_metrics(block))
        elif isinstance(block, ReportCalloutBlock):
            block_html.append(_callout(block))
        elif isinstance(block, ReportInfographicBlock):
            block_html.append(_infographic(block))
        elif isinstance(block, ReportTableBlock):
            result = results[block.result_id]
            columns = block.columns or result.columns
            missing = [column for column in columns if column not in result.columns]
            if missing:
                raise ValueError(
                    "Report table references unknown columns: "
                    + ", ".join(missing)
                )
            rows = result.rows if block.include_all_rows else result.rows[: block.row_limit]
            block_html.append(
                _table_html(
                    result,
                    title=block.title,
                    caption=block.caption,
                    columns=columns,
                    rows=rows,
                )
            )
        elif isinstance(block, ReportChartBlock):
            chart_index += 1
            result = results[block.chart.result_id]
            block_html.append(
                _chart(
                    block,
                    result,
                    chart_index=chart_index,
                    include_plotly=chart_index == 1,
                )
            )
        elif isinstance(block, ReportStatisticalBlock):
            key = block.analysis_id or f"current:{block.parent_result_id}"
            block_html.append(_statistical(block, analyses[key]))
        else:  # pragma: no cover - discriminated union is exhaustive
            raise TypeError(f"Unsupported report block {type(block).__name__}.")

    audience = (
        f"<span>Audience · {escape(spec.audience)}</span>" if spec.audience else ""
    )
    mode = spec.theme.color_mode
    body_theme = "dark" if mode == "dark" else "light" if mode == "light" else ""
    footer = (
        f'<footer class="report-footer">{_rich_text(spec.footer)}</footer>'
        if spec.footer
        else ""
    )
    interaction_script = r"""
(() => {
  const button = document.getElementById('theme-toggle');
  const body = document.body;
  const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');

  const activeTheme = () => body.dataset.theme || (systemTheme.matches ? 'dark' : 'light');

  const syncPlotTheme = () => {
    if (!window.Plotly) return;
    const tokens = getComputedStyle(body);
    const text = tokens.getPropertyValue('--text').trim();
    const muted = tokens.getPropertyValue('--muted').trim();
    const surface = tokens.getPropertyValue('--surface').trim();
    const border = tokens.getPropertyValue('--chart-grid').trim();
    document.querySelectorAll('.plotly-graph-div').forEach((chart) => {
      const update = {
        'font.color': text,
        'legend.font.color': text,
        'hoverlabel.bgcolor': surface,
        'hoverlabel.bordercolor': border,
        'hoverlabel.font.color': text,
        'paper_bgcolor': 'rgba(0,0,0,0)',
        'plot_bgcolor': 'rgba(0,0,0,0)'
      };
      Object.keys(chart.layout || {}).forEach((key) => {
        if (/^[xy]axis\d*$/.test(key)) {
          update[`${key}.color`] = muted;
          update[`${key}.gridcolor`] = border;
        }
      });
      window.Plotly.relayout(chart, update);
    });
  };

  const syncThemeControl = () => {
    const next = activeTheme() === 'dark' ? 'light' : 'dark';
    button.setAttribute('aria-label', `Use ${next} theme`);
    button.textContent = `${next[0].toUpperCase()}${next.slice(1)} theme`;
    syncPlotTheme();
  };

  button.addEventListener('click', () => {
    const next = activeTheme() === 'dark' ? 'light' : 'dark';
    body.dataset.theme = next;
    syncThemeControl();
  });
  systemTheme.addEventListener('change', () => {
    if (!body.dataset.theme) syncThemeControl();
  });
  syncThemeControl();
})();
""".strip()
    content = (
        f'<body data-theme="{body_theme}">'
        '<a class="skip-link" href="#report-content">Skip to report content</a>'
        '<button id="theme-toggle" class="theme-toggle" type="button" aria-label="Toggle report theme">Theme</button>'
        '<main class="report-shell">'
        '<header class="report-hero">'
        + (f'<p class="eyebrow">{escape(spec.eyebrow)}</p>' if spec.eyebrow else "")
        + f"<h1>{escape(spec.title)}</h1>"
        + (f'<p class="subtitle">{escape(spec.subtitle)}</p>' if spec.subtitle else "")
        + '<div class="report-meta">'
        f"<span>Generated {escape(generated_at.isoformat())}</span>{audience}</div>"
        "</header>"
        '<div id="report-content" class="report-content">'
        f"{''.join(block_html)}</div>"
        f"{_sql_queries(results)}{footer}</main>"
        f"<script>{interaction_script}</script></body>"
    )
    csp = _script_csp(content)
    return (
        "<!doctype html><html lang=\"en\"><head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="Content-Security-Policy" content="{escape(csp, quote=True)}">'
        f"<title>{escape(spec.title)}</title><style>{_style(spec)}"
        ".skip-link{position:absolute;left:-9999px;top:.5rem;z-index:20;padding:.7rem 1rem;background:var(--surface);color:var(--text)}"
        ".skip-link:focus{left:.5rem}</style></head>"
        f"{content}</html>"
    )
