"""
Self-contained HTML reports (inline SVG + CSS, no JavaScript, no external assets).

Per site:
  * summary cards and the decision funnel (where candidate links stopped);
  * semantic map: one lane per topic cluster, pages ordered best-first, circle
    size = internal PageRank after optimization, colour = role, new links in orange;
  * ranking leaderboard: PageRank before/after, rank change, CheiRank,
    pillar-weighted PageRank, click depth, Search Console position;
  * authority / hub plane: PageRank x CheiRank;
  * approved links with the anchor highlighted in its sentence;
  * benchmark verdict (expected links found / missing and why).
"""

import math
from html import escape
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from src.log import get_logger
from src.reporting.analysis import PageMetrics, SiteAnalysis

logger = get_logger(__name__)

ROLE_COLORS = {"pillar": "#7c3aed", "money": "#15803d", "support": "#2563eb"}
NEW_LINK_COLOR = "#ea580c"
EXISTING_LINK_COLOR = "#94a3b8"
LANE_COLORS = ["#eef2ff", "#ecfdf5", "#fff7ed", "#fdf2f8", "#f0f9ff", "#fefce8", "#f5f3ff", "#f1f5f9"]

CSS = """
* { box-sizing: border-box; }
body { font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #0f172a;
       margin: 0; background: #f8fafc; }
header { background: #0f172a; color: #f8fafc; padding: 18px 28px; }
header h1 { margin: 0; font-size: 21px; } header p { margin: 4px 0 0; color: #cbd5e1; }
header a { color: #93c5fd; }
main { padding: 20px 28px 40px; max-width: 1500px; }
section { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px 18px; margin: 0 0 18px; }
h2 { font-size: 17px; margin: 0 0 4px; } .sub { color: #64748b; margin: 0 0 12px; }
.cards { display: flex; flex-wrap: wrap; gap: 12px; }
.card { flex: 1 1 150px; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 12px; background: #fff; }
.card .v { font-size: 22px; font-weight: 700; } .card .k { color: #64748b; font-size: 12px; }
.good { color: #15803d; } .bad { color: #b91c1c; } .warn { color: #b45309; } .muted { color: #64748b; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; }
th { font-size: 12px; color: #475569; background: #f8fafc; position: sticky; top: 0; }
.badge { display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: 11px; color: #fff; }
.tag { display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: 11px; background: #f1f5f9; color: #334155; }
.tag.page2 { background: #fef3c7; color: #92400e; } .tag.orphan { background: #fee2e2; color: #991b1b; }
.bar { position: relative; height: 14px; min-width: 180px; background: #f1f5f9; border-radius: 3px; }
.bar .before { position: absolute; top: 0; left: 0; height: 14px; background: #cbd5e1; border-radius: 3px; }
.bar .after { position: absolute; top: 4px; left: 0; height: 6px; background: #0f172a; border-radius: 3px; }
.up { color: #15803d; font-weight: 600; } .down { color: #b91c1c; font-weight: 600; }
mark { background: #ffedd5; color: #9a3412; padding: 0 2px; border-radius: 3px; font-weight: 600; }
.legend span { margin-right: 14px; white-space: nowrap; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; vertical-align: -1px; }
.scroll { overflow-x: auto; }
.funnel div { display: flex; align-items: center; gap: 8px; margin: 3px 0; }
.funnel .fb { height: 12px; background: #334155; border-radius: 3px; }
.funnel .fb.ok { background: #15803d; }
svg text { font-family: inherit; }
"""


def _short(text: str, max_len: int = 26) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _fmt(value: float) -> str:
    return f"{100 * value:.1f}%"


def _role_badge(role: str) -> str:
    return f'<span class="badge" style="background:{ROLE_COLORS.get(role, "#64748b")}">{escape(role)}</span>'


def _page_tooltip(p: PageMetrics) -> str:
    lines = [
        p.url,
        f"role: {p.role} | cluster: {p.cluster}",
        f"internal PageRank: {_fmt(p.pagerank_before)} -> {_fmt(p.pagerank_after)} (rank #{p.rank_before} -> #{p.rank_after})",
        f"CheiRank (hub): {_fmt(p.cheirank)}",
    ]
    if p.weighted_pagerank is not None:
        lines.append(f"pillar-weighted PageRank: {_fmt(p.weighted_pagerank)}")
    lines.append(f"click depth from pillar: {p.click_depth if p.click_depth is not None else 'unreachable'}")
    lines.append(f"contextual inbound links: {p.inbound_before} -> {p.inbound_after} | outbound: {p.outbound_after}"
                 + (f" | navigation inbound: {p.navigation_inbound}" if p.navigation_inbound else ""))
    if p.gsc_query:
        lines.append(f"Search Console: '{p.gsc_query}' position {p.gsc_position} ({p.gsc_impressions} impressions)")
    if not p.crawled:
        lines.append("(linked from the crawl, not crawled itself)")
    elif not p.indexable:
        lines.append("(not indexable: noindex or canonicalized to another URL; excluded from link proposals)")
    return escape("\n".join(lines))


# ------------------------------------------------------------------ semantic map

def _semantic_map(a: SiteAnalysis) -> str:
    lanes = a.clusters
    by_lane: Dict[str, List[PageMetrics]] = {c: [p for p in a.pages if p.cluster == c] for c in lanes}
    lane_w, top, row_h = 250, 64, 92
    width = max(780, len(lanes) * lane_w + 40)
    height = top + max((len(v) for v in by_lane.values()), default=1) * row_h + 20
    max_pr = max((p.pagerank_after for p in a.pages), default=1.0) or 1.0

    pos: Dict[str, Tuple[float, float, float]] = {}
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="Semantic map of {escape(a.name)}">',
        "<defs>",
        f'<marker id="arrow-new" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" fill="{NEW_LINK_COLOR}"/></marker>',
        f'<marker id="arrow-old" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" fill="{EXISTING_LINK_COLOR}"/></marker>',
        "</defs>",
    ]
    for i, cluster in enumerate(lanes):
        x0 = 20 + i * lane_w
        share = sum(p.pagerank_after for p in by_lane[cluster])
        parts.append(
            f'<rect x="{x0 + 6}" y="8" width="{lane_w - 12}" height="{height - 16}" rx="10" fill="{LANE_COLORS[i % len(LANE_COLORS)]}"/>'
            f'<text x="{x0 + lane_w / 2}" y="32" text-anchor="middle" font-weight="700" font-size="14">{escape(cluster)}</text>'
            f'<text x="{x0 + lane_w / 2}" y="50" text-anchor="middle" font-size="11" fill="#64748b">{_fmt(share)} of link equity · {len(by_lane[cluster])} pages</text>'
        )
        for j, p in enumerate(by_lane[cluster]):
            radius = 7 + 24 * math.sqrt(p.pagerank_after / max_pr)
            pos[p.url] = (x0 + lane_w / 2, top + j * row_h + 34, radius)

    def edge(source: str, target: str, new: bool) -> str:
        x1, y1, r1 = pos[source]
        x2, y2, r2 = pos[target]
        if abs(x1 - x2) < 1:  # same lane: downward links bulge right, upward links left
            bulge = (60 + 0.25 * abs(y2 - y1)) * (1 if y2 > y1 else -1)
            c1, c2 = (x1 + bulge, y1), (x2 + bulge, y2)
        else:
            lift = 30 + 0.1 * abs(x2 - x1)
            c1 = (x1 + (x2 - x1) / 3, min(y1, y2) - lift)
            c2 = (x2 - (x2 - x1) / 3, min(y1, y2) - lift)

        def clip(px, py, cx, cy, r):
            dx, dy = cx - px, cy - py
            length = math.hypot(dx, dy) or 1.0
            return px + r * dx / length, py + r * dy / length

        sx, sy = clip(x1, y1, *c1, r1)
        ex, ey = clip(x2, y2, *c2, r2 + 8)  # stop before the node (and its page 2 ring)
        color, width_, marker = (NEW_LINK_COLOR, 2.4, "arrow-new") if new else (EXISTING_LINK_COLOR, 1.2, "arrow-old")
        return (
            f'<path d="M{sx:.1f},{sy:.1f} C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {ex:.1f},{ey:.1f}" '
            f'fill="none" stroke="{color}" stroke-width="{width_}" opacity="{0.9 if new else 0.7}" marker-end="url(#{marker})">'
            f"<title>{'new' if new else 'existing'} link: {escape(source)} -> {escape(target)}</title></path>"
        )

    parts += [edge(s, t, False) for s, t in a.existing_links if s in pos and t in pos]
    parts += [edge(s, t, True) for s, t in a.new_links if s in pos and t in pos]

    for p in a.pages:
        x, y, r = pos[p.url]
        stroke = ' stroke="#dc2626" stroke-width="2.5" stroke-dasharray="4 3"' if p.orphan_after else ' stroke="#fff" stroke-width="2"'
        ring = f'<circle cx="{x}" cy="{y}" r="{r + 5}" fill="none" stroke="#f59e0b" stroke-width="2.5"/>' if p.page2 else ""
        opacity = "1" if p.crawled else "0.45"
        change = f" ▲{p.rank_change}" if p.rank_change > 0 else (f" ▼{-p.rank_change}" if p.rank_change < 0 else "")
        parts.append(
            f'<g opacity="{opacity}"><title>{_page_tooltip(p)}</title>{ring}'
            f'<circle cx="{x}" cy="{y}" r="{r:.1f}" fill="{ROLE_COLORS.get(p.role, "#64748b")}"{stroke}/>'
            f'<text x="{x}" y="{y + r + 14:.1f}" text-anchor="middle" font-size="11.5" font-weight="600">#{p.rank_after} {escape(_short(p.label))}</text>'
            f'<text x="{x}" y="{y + r + 27:.1f}" text-anchor="middle" font-size="10.5" fill="#475569">{_fmt(p.pagerank_after)}{change}</text></g>'
        )
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------- authority/hub

def _authority_hub_plane(a: SiteAnalysis) -> str:
    width, height, margin = 720, 440, 64
    pages = a.pages
    n = len(pages)
    uniform = 1.0 / n
    xs = [math.log10(p.pagerank_after) for p in pages]
    ys = [math.log10(p.cheirank) for p in pages]
    lo_x, hi_x = min(xs + [math.log10(uniform)]) - 0.08, max(xs + [math.log10(uniform)]) + 0.08
    lo_y, hi_y = min(ys + [math.log10(uniform)]) - 0.08, max(ys + [math.log10(uniform)]) + 0.08

    def sx(v):
        return margin + (v - lo_x) / ((hi_x - lo_x) or 1) * (width - 2 * margin)

    def sy(v):
        return height - margin - (v - lo_y) / ((hi_y - lo_y) or 1) * (height - 2 * margin)

    ux, uy = sx(math.log10(uniform)), sy(math.log10(uniform))
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px" role="img" aria-label="Authority and hub plane">',
        f'<rect x="{margin}" y="{margin}" width="{width - 2 * margin}" height="{height - 2 * margin}" fill="#f8fafc" stroke="#e2e8f0"/>',
        f'<line x1="{ux}" y1="{margin}" x2="{ux}" y2="{height - margin}" stroke="#cbd5e1" stroke-dasharray="4 4"/>',
        f'<line x1="{margin}" y1="{uy}" x2="{width - margin}" y2="{uy}" stroke="#cbd5e1" stroke-dasharray="4 4"/>',
        f'<text x="{width - margin - 6}" y="{height - margin - 8}" text-anchor="end" fill="#64748b" font-size="12">Authorities (receive equity)</text>',
        f'<text x="{margin + 6}" y="{margin + 16}" fill="#64748b" font-size="12">Hubs (distribute equity)</text>',
        f'<text x="{width - margin - 6}" y="{margin + 16}" text-anchor="end" fill="#64748b" font-size="12">Connectors (both)</text>',
        f'<text x="{margin + 6}" y="{height - margin - 8}" fill="#64748b" font-size="12">Peripheral</text>',
        f'<text x="{width / 2}" y="{height - 18}" text-anchor="middle" font-size="12">internal PageRank (log scale) →</text>',
        f'<text x="18" y="{height / 2}" text-anchor="middle" font-size="12" transform="rotate(-90 18 {height / 2})">CheiRank, hub score (log scale) →</text>',
    ]
    for p, x, y in zip(pages, xs, ys):
        parts.append(
            f'<g><title>{_page_tooltip(p)}</title>'
            f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="6" fill="{ROLE_COLORS.get(p.role, "#64748b")}" opacity="0.85"/>'
            f'<text x="{sx(x) + 9:.1f}" y="{sy(y) + 4:.1f}" font-size="10.5">{escape(_short(p.label))}</text></g>'
        )
    parts.append("</svg>")
    return "".join(parts)


# -------------------------------------------------------------------- sections

def _verdict_class(a: SiteAnalysis) -> str:
    """good: every expected link found; warn: only documented known gaps missing; bad: otherwise."""
    b = a.benchmark
    if b is None or (b.recall == 1.0 and not b.unexpected):
        return "good"
    return "warn" if all(known for _, _, known in b.missing) and not b.unexpected else "bad"


def _cards(a: SiteAnalysis) -> str:
    r = a.report
    orphans_before = sum(1 for p in a.pages if p.orphan_before)
    orphans_after = sum(1 for p in a.pages if p.orphan_after)
    best = a.pages[0] if a.pages else None
    cards = [
        ("pages in graph", str(len(a.pages))),
        ("links approved", str(r.links_approved)),
        ("classifier calls (est. cost)", f"{r.candidate_pairs_checked} (${r.estimated_cost_usd:.4f})"),
        ("orphan pages", f"{orphans_before} → {orphans_after}"),
        ("page 2 pages boosted", f"{len(r.page2_pages_boosted)} / {len({row.page for row in r.page2_opportunities})}"),
        ("best page (internal PageRank)", f"{escape(_short(best.label, 22))} · {_fmt(best.pagerank_after)}" if best else "-"),
    ]
    if a.benchmark:
        b = a.benchmark
        value = f'<span class="{_verdict_class(a)}">{len(b.found)}/{b.expected}</span>'
        if b.precision is not None:
            value += f' · precision <span class="{"good" if b.precision == 1.0 else "bad"}">{b.precision:.0%}</span>'
        cards.insert(0, ("expected links found", value))
    return '<div class="cards">' + "".join(
        f'<div class="card"><div class="v">{v}</div><div class="k">{escape(k)}</div></div>' for k, v in cards
    ) + "</div>"


def _funnel(a: SiteAnalysis) -> str:
    counts = a.report.decisions_by_reason
    if not counts:
        return ""
    total = max(counts.values())
    rows = "".join(
        f'<div><span style="width:150px">{escape(reason)}</span>'
        f'<span class="fb{" ok" if reason == "approved" else ""}" style="width:{max(2, 320 * n / total):.0f}px"></span>'
        f"<span>{n}</span></div>"
        for reason, n in sorted(counts.items(), key=lambda kv: -kv[1])
    )
    return (
        '<section><h2>Decision funnel</h2><p class="sub">Where each candidate source → target pair '
        f'stopped in the flow ({sum(counts.values())} pairs).</p><div class="funnel">{rows}</div></section>'
    )


def _leaderboard(a: SiteAnalysis) -> str:
    max_pr = max(max(p.pagerank_after, p.pagerank_before) for p in a.pages) or 1.0
    has_weighted = any(p.weighted_pagerank is not None for p in a.pages)
    has_gsc = any(p.gsc_query for p in a.pages)
    head = ["#", "Δ", "page", "role", "cluster", "internal PageRank (grey: before, black: after)", "CheiRank"]
    head += ["pillar-weighted"] if has_weighted else []
    head += ["depth", "inbound"]
    head += ["Search Console"] if has_gsc else []
    rows = []
    for p in a.pages:
        change = (f'<span class="up">▲{p.rank_change}</span>' if p.rank_change > 0
                  else f'<span class="down">▼{-p.rank_change}</span>' if p.rank_change < 0 else '<span class="muted">–</span>')
        tags = "".join([
            ' <span class="tag orphan">orphan</span>' if p.orphan_after else "",
            ' <span class="tag page2">page 2</span>' if p.page2 else "",
            ' <span class="tag">not crawled</span>' if not p.crawled else "",
            ' <span class="tag">not indexable</span>' if p.crawled and not p.indexable else "",
        ])
        cells = [
            f"<b>{p.rank_after}</b>",
            change,
            f'<span title="{escape(p.url)}">{escape(p.label)}</span>{tags}',
            _role_badge(p.role),
            escape(p.cluster),
            f'<div class="bar"><div class="before" style="width:{100 * p.pagerank_before / max_pr:.1f}%"></div>'
            f'<div class="after" style="width:{100 * p.pagerank_after / max_pr:.1f}%"></div></div>'
            f'<span class="muted">{_fmt(p.pagerank_before)} → <b>{_fmt(p.pagerank_after)}</b></span>',
            _fmt(p.cheirank),
        ]
        if has_weighted:
            cells.append(_fmt(p.weighted_pagerank) if p.weighted_pagerank is not None else "–")
        cells += [
            str(p.click_depth) if p.click_depth is not None else '<span class="muted">∞</span>',
            f"{p.inbound_before} → <b>{p.inbound_after}</b>",
        ]
        if has_gsc:
            cells.append(
                f"{escape(p.gsc_query)} · pos {p.gsc_position} · {p.gsc_impressions} impr." if p.gsc_query else "–"
            )
        rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return (
        '<section><h2>Ranking leaderboard</h2><p class="sub">Pages ordered by internal link equity after '
        "optimization (PageRank of the site's own link graph). Δ = places gained thanks to the new links.</p>"
        '<div class="scroll"><table><thead><tr>' + "".join(f"<th>{escape(h)}</th>" for h in head)
        + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div></section>"
    )


def _highlight(sentence: str, anchor: str, target: str) -> str:
    wrapped = f"[{anchor}]({target})"
    before, _, after = sentence.partition(wrapped)
    return f"{escape(before)}<mark>{escape(anchor)}</mark>{escape(after)}"


def _links(a: SiteAnalysis) -> str:
    if not a.report.results:
        return '<section><h2>Approved links</h2><p class="sub">No link was approved.</p></section>'
    rows = "".join(
        "<tr>"
        f'<td><span title="{escape(r.source_url)}">{escape(a.page(r.source_url).label)}</span> → '
        f'<span title="{escape(r.target_url)}">{escape(a.page(r.target_url).label)}</span>'
        + (f'<br><span class="tag page2">boosts page 2: {escape(r.page2_query)}</span>' if r.page2_query else "")
        + f"</td><td>{_highlight(r.updated_sentence, r.anchor_text, r.target_url)}</td>"
        f"<td>{r.relevance_score} / {r.confidence:.2f}<br><span class=\"muted\">{escape(r.classifier)}</span></td></tr>"
        for r in a.report.results
    )
    return (
        '<section><h2>Approved links</h2><p class="sub">Proposed edits; the anchor is highlighted. '
        "Links that boost SERP page 2 pages come first.</p><div class=\"scroll\"><table><thead><tr>"
        "<th>link</th><th>proposed sentence</th><th>classifier score / confidence</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></section>"
    )


def _verdict(a: SiteAnalysis) -> str:
    b = a.benchmark
    if b is None:
        return ""

    def pair(link):
        return f"{escape(a.page(link[0]).label)} → {escape(a.page(link[1]).label)}"

    items = [f'<li class="good">✔ {pair(link)}</li>' for link in b.found]
    for link, decision, known in b.missing:
        items.append(
            f'<li class="bad">✘ {pair(link)} — <b>{escape(decision.reason)}</b>: {escape(decision.detail)}'
            + (' <span class="tag">known gap</span>' if known else "") + "</li>"
        )
    items += [f'<li class="bad">✘ unexpected: {pair(link)}</li>' for link in b.unexpected]
    precision = f" · precision {b.precision:.0%}" if b.precision is not None else ""
    return (
        f'<section><h2>Benchmark verdict</h2><p class="sub">Expected links from {escape(b.expectation_source)}: '
        f"recall {b.recall:.0%}{precision}.</p><ul>{''.join(items)}</ul></section>"
    )


SEVERITY_CLASSES = {"error": "bad", "warning": "warn", "notice": "muted"}


def _site_health(a: SiteAnalysis) -> str:
    audit = a.site_audit
    if audit is None:
        return ""
    counts = audit.by_severity
    cls = "good" if audit.health == 1.0 else ("warn" if audit.health >= 0.5 else "bad")
    cards = [
        ("healthy pages", f'<span class="{cls}">{len(audit.healthy_pages)}/{len(audit.pages)} ({audit.health:.0%})</span>'),
        ("errors", f'<span class="{"bad" if counts["error"] else "good"}">{counts["error"]}</span>'),
        ("warnings", f'<span class="{"warn" if counts["warning"] else "good"}">{counts["warning"]}</span>'),
        ("notices", str(counts["notice"])),
    ]
    rows = "".join(
        f'<tr><td class="{SEVERITY_CLASSES[i.severity]}">{escape(i.severity)}</td><td>{escape(i.code)}</td>'
        f'<td>{escape(i.url)}</td><td>{escape(i.detail)}</td></tr>'
        for i in audit.issues
    ) or '<tr><td colspan="4" class="good">No issue found.</td></tr>'
    return (
        '<section><h2>Site health</h2><p class="sub">Technical and structural checks on the crawl '
        f"(click depth from the start page, max {audit.max_click_depth}). Healthy = no error or warning.</p>"
        '<div class="cards">' + "".join(
            f'<div class="card"><div class="v">{v}</div><div class="k">{escape(k)}</div></div>' for k, v in cards
        ) + '</div><div class="scroll" style="margin-top:12px"><table><thead><tr><th>severity</th><th>issue</th>'
        f"<th>url</th><th>detail</th></tr></thead><tbody>{rows}</tbody></table></div></section>"
    )


def _legend() -> str:
    roles = "".join(f'<span><i class="dot" style="background:{c}"></i>{r}</span>' for r, c in ROLE_COLORS.items())
    return (
        f'<p class="legend">{roles}<span style="color:{NEW_LINK_COLOR}">━ new link</span>'
        f'<span style="color:{EXISTING_LINK_COLOR}">━ existing link</span>'
        '<span><i class="dot" style="border:2px solid #f59e0b"></i>page 2 query</span>'
        '<span><i class="dot" style="border:2px dashed #dc2626"></i>orphan</span>'
        "<span>size = internal PageRank · hover for details</span></p>"
    )


def _page(title: str, subtitle: str, body: str) -> str:
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title><style>{CSS}</style></head><body>"
        f"<header><h1>{escape(title)}</h1><p>{subtitle}</p></header><main>{body}</main></body></html>"
    )


def render_site_report(a: SiteAnalysis, index_href: str = "") -> str:
    t, rules = a.config.thresholds, a.config.link_rules
    back = f' · <a href="{escape(index_href)}">all sites</a>' if index_href else ""
    subtitle = (
        f"Classifier: {escape(a.report.classifier or 'n/a')} · gate: score ≥ {t.min_score}, "
        f"confidence ≥ {t.min_confidence} · anchors ≥ "
        f"{t.anchor_min_words} topic words · money → support: {escape(rules.money_to_support)}{back}"
    )
    notes = "".join(f'<p class="sub">ℹ {escape(n)}</p>' for n in a.notes)
    body = (
        f"<section>{_cards(a)}</section>"
        + _site_health(a)
        + _verdict(a)
        + '<section><h2>Semantic map</h2><p class="sub">One lane per topic cluster (strongest cluster first); '
        "pages ordered best-first inside each lane. Which page ranks best: the biggest circle at the top of its lane.</p>"
        + _legend() + f'<div class="scroll">{_semantic_map(a)}</div>{notes}</section>'
        + _leaderboard(a)
        + '<section><h2>Authorities and hubs</h2><p class="sub">PageRank measures the equity a page receives, '
        "CheiRank the equity it distributes. Dashed lines = an average page (1/N).</p>"
        + _authority_hub_plane(a) + "</section>"
        + _links(a)
        + _funnel(a)
    )
    return _page(f"SEO-Magus · {a.name}", subtitle, body)


def render_index(analyses: Iterable[SiteAnalysis]) -> str:
    rows = []
    for a in analyses:
        b = a.benchmark
        recall = f"{len(b.found)}/{b.expected}" if b else "–"
        precision = f"{b.precision:.0%}" if b and b.precision is not None else "–"
        best = a.pages[0] if a.pages else None
        audit = a.site_audit
        health = (f'<td class="{"good" if audit.health == 1.0 else "bad"}">{len(audit.healthy_pages)}/{len(audit.pages)}</td>'
                  if audit else "<td>-</td>")
        rows.append(
            f'<tr><td><a href="{escape(a.key)}.html"><b>{escape(a.name)}</b></a></td>'
            f"<td>{len(a.pages)}</td><td>{a.report.links_approved}</td>"
            f'<td class="{_verdict_class(a)}">{recall}</td><td>{precision}</td>'
            f"<td>{escape(best.label) if best else '–'} ({_fmt(best.pagerank_after) if best else '–'})</td>"
            f"<td>{len(a.report.page2_pages_boosted)}</td>{health}<td>{a.report.candidate_pairs_checked}</td></tr>"
        )
    body = (
        '<section><h2>Benchmark sites</h2><p class="sub">Each site is run with its own config '
        "(config/sites/&lt;site&gt;.yaml). Open a site for its semantic map and ranking leaderboard. "
        '<span class="good">green</span>: all expected links found · <span class="warn">amber</span>: only '
        'documented known gaps missing · <span class="bad">red</span>: regression.</p>'
        "<table><thead><tr><th>site</th><th>pages</th><th>links approved</th><th>expected links found</th>"
        "<th>precision</th><th>best page (internal PageRank)</th><th>page 2 pages boosted</th><th>healthy pages (crawled sites)</th><th>classifier calls</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></section>"
    )
    return _page("SEO-Magus · Benchmark report", "Internal linking benchmarks", body)


def write_reports(analyses: List[SiteAnalysis], out_dir) -> List[Path]:
    """Write <key>.html per site plus index.html; returns the written paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for a in analyses:
        path = out / f"{a.key}.html"
        path.write_text(render_site_report(a, index_href="index.html" if len(analyses) > 1 else ""), encoding="utf-8")
        written.append(path)
        logger.info("HTML report written: %s", path)
    if len(analyses) > 1:
        index = out / "index.html"
        index.write_text(render_index(analyses), encoding="utf-8")
        written.insert(0, index)
        logger.info("HTML index written: %s", index)
    return written
