"""
Self-contained HTML evaluation report (inline SVG + CSS, no JavaScript, no external assets).

Sections, each computed from the tidy rows (results.py) and the analysis (analysis.py):
  summary cards        what was measured, on what, and how many claims are established
  claims matrix        every product-vs-baseline claim x every corpus, coloured by verdict
  scores               per task: systems x corpora heatmap of the primary metric (mean, min-max),
                       coloured by chance-normalized skill so every task uses one colour scale
  ranks                critical-difference diagram: average rank over all methodology cells,
                       systems within the Nemenyi CD of the best joined by a bar
  methodologies        agreement of the system rankings across corpora / protocols / samplers /
                       seeds (Kendall's W, winner per level) and the variance each factor explains
  meta-analysis        forest plots: each corpus' effect with its CI, the pooled random effect
  link diagnostics     recall per difficulty stratum and per planted style
  crawl and scale      fidelity table, log-log growth chart
"""

import math
from html import escape
from typing import Dict, List, Optional, Sequence

from src.evaluation.analysis import FACTORS
from src.evaluation.narrative import at_a_glance
from src.evaluation.results import PRIMARY, Row, group

KIND_COLORS = {"product": "#2563eb", "oracle": "#7c3aed", "baseline": "#94a3b8", "gold": "#ca8a04"}
FACTOR_COLORS = {"corpus": "#2563eb", "protocol": "#16a34a", "sampler": "#ea580c", "seed": "#a855f7"}
VERDICT_CLASSES = {"robust": "v-robust", "mixed": "v-mixed", "no": "v-no", "worse": "v-worse",
                   "insufficient data": "v-na"}

CSS = """
* { box-sizing: border-box; }
body { font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #0f172a; margin: 0;
       background: #f8fafc; }
header { background: #0f172a; color: #f8fafc; padding: 18px 28px; } header h1 { margin: 0; font-size: 21px; }
header p { margin: 4px 0 0; color: #cbd5e1; }
main { padding: 20px 28px 40px; max-width: 1500px; }
nav.toc { margin: 0 0 16px; } nav.toc a { margin-right: 14px; color: #2563eb; text-decoration: none; }
section { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px 18px; margin: 0 0 18px; }
h2 { font-size: 17px; margin: 0 0 4px; } h3 { font-size: 14px; margin: 14px 0 6px; }
.sub { color: #64748b; margin: 0 0 12px; }
.cards { display: flex; flex-wrap: wrap; gap: 12px; }
.card { flex: 1 1 160px; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 12px; }
.card .v { font-size: 22px; font-weight: 700; } .card .k { color: #64748b; font-size: 12px; }
table { border-collapse: collapse; margin: 4px 0 10px; } th, td { padding: 5px 8px; border: 1px solid #eef2f7;
       text-align: left; vertical-align: middle; } th { background: #f8fafc; font-size: 12px; color: #475569; }
td.num { text-align: right; font-variant-numeric: tabular-nums; } small { color: #64748b; }
.scroll { overflow-x: auto; }
.v-robust { background: #dcfce7; color: #166534; } .v-mixed { background: #fef9c3; color: #854d0e; }
.v-no { background: #f1f5f9; color: #475569; } .v-worse { background: #fee2e2; color: #991b1b; }
.v-na { background: #fff; color: #94a3b8; }
.status-supported { color: #166534; font-weight: 600; } .status-contradicted { color: #991b1b; font-weight: 600; }
.status-other { color: #475569; }
.warn { background: #fff7ed; border: 1px solid #fed7aa; padding: 8px 12px; border-radius: 8px; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; vertical-align: -1px; }
svg text { font-family: inherit; }
"""


def _fmt(value: Optional[float], digits: int = 3) -> str:
    return "-" if value is None or (isinstance(value, float) and math.isnan(value)) else f"{value:.{digits}f}"


def _skill_color(skill: Optional[float]) -> str:
    """White at chance, green towards perfect, red below chance."""
    if skill is None:
        return "#ffffff"
    s = max(-1.0, min(1.0, skill))
    if s >= 0:
        return f"rgb({int(255 - 135 * s)},{int(255 - 40 * s)},{int(255 - 135 * s)})"
    return f"rgb(255,{int(255 + 120 * s)},{int(255 + 120 * s)})"


def _legend_kinds() -> str:
    return " ".join(f'<span><i class="dot" style="background:{c}"></i>{k}</span>' for k, c in KIND_COLORS.items()
                    if k != "gold")


# ----------------------------------------------------------------- sections


def _cards(report: dict, analysis: dict) -> str:
    claims = report.get("summary", {}).get("claims", [])
    supported = sum(1 for c in claims if c["status"].startswith("supported"))
    corpora = report.get("corpora", [])
    real = [c for c in corpora if c["provenance"]["source"] != "synthetic"]
    cards = [("corpora (real)", f"{len(corpora)} ({len(real)})"), ("runs", str(len(report.get("runs", [])))),
             ("claims established", f"{supported} / {len(claims)}"),
             ("protocol", f"v{report.get('protocol', {}).get('version', '?')} · {report.get('protocol_hash', '?')}")]
    html = '<div class="cards">' + "".join(
        f'<div class="card"><div class="v">{escape(v)}</div><div class="k">{escape(k)}</div></div>' for k, v in cards
    ) + "</div>"
    points = at_a_glance(report, analysis)
    if points:
        html += "<ul>" + "".join(f"<li><b>{escape(title)}</b>: {escape(text)}</li>" for title, text in points) + "</ul>"
    if not any(c.get("evidence", {}).get(t) == "evidence" for c in corpora for t in c.get("evidence", {})):
        html += ('<p class="warn" style="margin-top:12px">No corpus in this report counts as evidence about real-world '
                 "quality (synthetic corpora validate the code; tiny corpora are too small). Add real sources - see "
                 "docs/EVALUATION.md.</p>")
    return f'<section id="summary"><h2>Summary</h2>{html}</section>'


def _claims(report: dict) -> str:
    claims = report.get("summary", {}).get("claims", [])
    if not claims:
        return ""
    corpora = [c["name"] for c in report.get("corpora", [])]
    head = "".join(f"<th>{escape(c)}</th>" for c in corpora)
    rows = []
    for claim in claims:
        cells = []
        for corpus in corpora:
            text = claim["by_corpus"].get(corpus)
            if text is None:
                cells.append('<td class="v-na">·</td>')
                continue
            verdict, _, role = text.partition(" (")
            cells.append(f'<td class="{VERDICT_CLASSES.get(verdict, "v-na")}" title="{escape(role.rstrip(")"))}">'
                         f"{escape(verdict)}</td>")
        status = claim["status"]
        css = ("status-supported" if status.startswith("supported") else
               "status-contradicted" if status.startswith("contradicted") else "status-other")
        rows.append(f"<tr><td>{escape(claim['task'])}</td><td>{escape(claim['protocol'] or '-')}</td>"
                    f"<td>{escape(claim['claim'])}</td><td class=\"{css}\">{escape(status)}</td>{''.join(cells)}</tr>")
    statuses: Dict[str, int] = {}
    for claim in claims:
        statuses[claim["status"]] = statuses.get(claim["status"], 0) + 1
    counts = ", ".join(f"{n} {escape(s)}" for s, n in sorted(statuses.items()))
    return ('<section id="claims"><h2>Claims</h2><p class="sub">Does each system beat each baseline on each corpus? '
            "<b>robust</b>: significant (Holm-corrected) in every sampler × seed run; <b>supported</b>: robust on every "
            "real source. Hover a cell for the corpus' evidence role.</p>"
            f"<details open><summary>{len(claims)} claims: {counts}</summary><div class=\"scroll\"><table><thead><tr>"
            f"<th>task</th><th>protocol</th><th>claim</th><th>status</th>{head}</tr></thead><tbody>{''.join(rows)}"
            "</tbody></table></div></details></section>")


def _scores(analysis: dict) -> str:
    parts = ['<section id="scores"><h2>Scores</h2><p class="sub">Mean primary metric over sampler × seed runs '
             "(min-max below). Colour = chance-normalized skill: white = random level, green = perfect, red = worse "
             f"than chance - one scale for every task. {_legend_kinds()}</p>"]
    by_group: Dict[tuple, Dict[tuple, dict]] = {}
    for entry in analysis["describe"]:
        by_group.setdefault((entry["task"], entry["protocol"]), {})[(entry["system"], entry["corpus"])] = entry
    for (task, protocol), entries in sorted(by_group.items()):
        systems = sorted({s for s, _ in entries}, key=lambda s: (entries_kind(entries, s) != "product", s))
        corpora = sorted({c for _, c in entries})
        head = "".join(f"<th>{escape(c)}</th>" for c in corpora)
        body = []
        for system in systems:
            kind = entries_kind(entries, system)
            cells = []
            for corpus in corpora:
                e = entries.get((system, corpus))
                if e is None or not e.get("n"):
                    cells.append("<td></td>")
                    continue
                cells.append(f'<td class="num" style="background:{_skill_color(e.get("skill"))}">{_fmt(e["mean"])}'
                             f'<br><small>{_fmt(e["min"], 2)}-{_fmt(e["max"], 2)}</small></td>')
            body.append(f'<tr><td><i class="dot" style="background:{KIND_COLORS.get(kind, "#64748b")}"></i>'
                        f"{escape(system)}</td>{''.join(cells)}</tr>")
        label = PRIMARY[task] + ("" if protocol == "-" else f", {protocol}")
        parts.append(f"<h3>{escape(task)} ({escape(label)})</h3><div class=\"scroll\"><table><thead><tr><th>system</th>"
                     f"{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>")
    parts.append("</section>")
    return "".join(parts)


def entries_kind(entries: Dict[tuple, dict], system: str) -> str:
    return next(e["kind"] for (s, _), e in entries.items() if s == system)


def _cd_diagram(entry: dict) -> str:
    """Critical-difference diagram: average ranks on an axis, the best group joined by a bar."""
    ranks = entry["average_rank"]
    k = len(ranks)
    width, left, right = 760, 60, 60
    scale = lambda r: left + (r - 1) / max(1, k - 1) * (width - left - right)
    height = 70 + 18 * k
    svg = [f'<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px" role="img" '
           f'aria-label="Average ranks of {escape(entry["task"])}">',
           f'<line x1="{left}" y1="40" x2="{width - right}" y2="40" stroke="#334155"/>']
    for r in range(1, k + 1):
        x = scale(r)
        svg.append(f'<line x1="{x:.1f}" y1="35" x2="{x:.1f}" y2="45" stroke="#334155"/>'
                   f'<text x="{x:.1f}" y="28" text-anchor="middle" font-size="11">{r}</text>')
    cd = entry.get("critical_difference")
    if cd:
        svg.append(f'<line x1="{scale(1):.1f}" y1="12" x2="{scale(1 + cd):.1f}" y2="12" stroke="#dc2626" stroke-width="3"/>'
                   f'<text x="{scale(1 + cd) + 6:.1f}" y="16" font-size="11" fill="#dc2626">CD {cd:.2f}</text>')
    best = min(ranks.values())
    tied = set(entry.get("tied_with_best", []))
    if len(tied) > 1:
        hi = max(ranks[s] for s in tied)
        svg.append(f'<line x1="{scale(best):.1f}" y1="50" x2="{scale(hi):.1f}" y2="50" stroke="#16a34a" stroke-width="5"/>')
    for i, (system, rank) in enumerate(sorted(ranks.items(), key=lambda kv: kv[1])):
        x, y = scale(rank), 70 + 18 * i
        color = KIND_COLORS.get(entry["kind"].get(system, ""), "#64748b")
        anchor, tx = ("start", x + 6) if rank <= (k + 1) / 2 else ("end", x - 6)
        svg.append(f'<line x1="{x:.1f}" y1="42" x2="{x:.1f}" y2="{y - 4}" stroke="{color}"/>'
                   f'<circle cx="{x:.1f}" cy="{y - 4}" r="3.5" fill="{color}"/>'
                   f'<text x="{tx:.1f}" y="{y}" text-anchor="{anchor}" font-size="12">{escape(system)} '
                   f'({rank:.2f})</text>')
    svg.append("</svg>")
    return "".join(svg)


def _ranks(analysis: dict) -> str:
    overall = [r for r in analysis["ranks"] if r["corpus"] == "(all)"]
    if not overall:
        return ""
    parts = ['<section id="ranks"><h2>Ranks across methodologies</h2><p class="sub">Average rank of each system over '
             "every methodology cell (corpus × protocol × sampler × seed; 1 = best). Friedman test of "
             "\"all systems alike\"; systems closer to the best than the Nemenyi critical difference (red bar) are not "
             "significantly different from it (green bar). Synthetic and real cells are pooled here - check the "
             "evidence column of each corpus.</p>"]
    for entry in overall:
        parts.append(f"<h3>{escape(entry['task'])}: {entry['cells']} cells, Friedman χ² {entry['chi2']:.1f}, "
                     f"p {entry['p_value']:.2g}</h3>{_cd_diagram(entry)}")
    parts.append("</section>")
    return "".join(parts)


def _methodologies(analysis: dict) -> str:
    agreement = analysis["agreement"]
    sensitivity = analysis["sensitivity"]
    if not agreement and not sensitivity:
        return ""
    rows = []
    for entry in agreement:
        w = entry["kendall_w"]
        winners = "; ".join(f"{escape(l)}: <b>{escape(s)}</b>" for l, s in entry["winner_by_level"].items())
        rows.append(f"<tr><td>{escape(entry['task'])}</td><td>{escape(entry['factor'])}</td><td class=\"num\">"
                    f"{entry['levels']}</td><td class=\"num\" style=\"background:{_skill_color(2 * w - 1)}\">{w:.3f}</td>"
                    f"<td>{'yes' if entry['same_winner'] else '<b>no</b>'}</td><td><small>{winners}</small></td></tr>")
    table = ("<table><thead><tr><th>task</th><th>factor</th><th>levels</th><th>Kendall's W</th><th>same winner</th>"
             f"<th>winner per level</th></tr></thead><tbody>{''.join(rows)}</tbody></table>")
    bars = _sensitivity_svg(sensitivity)
    return ('<section id="methodologies"><h2>Methodologies compared</h2><p class="sub">Would a different methodology '
            "tell a different story? For each factor, the systems are ranked under each of its levels (each corpus, "
            "each sampler...); Kendall's W measures how much those rankings agree (1 = identical). The bars show the "
            "share of each system's score variance explained by each factor alone (eta²): the factors that move the "
            f"numbers most.</p>{table}<h3>Variance explained by each factor</h3>{bars}</section>")


def _sensitivity_svg(entries: List[dict]) -> str:
    if not entries:
        return ""
    width, label_w, bar_w, row_h = 760, 260, 420, 20
    height = 30 + row_h * len(entries)
    svg = [f'<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px" role="img" '
           'aria-label="Variance explained by each factor">']
    x = label_w
    for factor in FACTORS:
        svg.append(f'<rect x="{x}" y="4" width="10" height="10" fill="{FACTOR_COLORS[factor]}"/>'
                   f'<text x="{x + 14}" y="13" font-size="11">{factor}</text>')
        x += 90
    for i, entry in enumerate(entries):
        y = 26 + row_h * i
        svg.append(f'<text x="{label_w - 8}" y="{y + 12}" text-anchor="end" font-size="11">'
                   f'{escape(entry["task"])} · {escape(entry["system"])}</text>'
                   f'<rect x="{label_w}" y="{y + 2}" width="{bar_w}" height="{row_h - 6}" fill="#f1f5f9"/>')
        offset = label_w
        for factor in FACTORS:
            share = max(0.0, min(1.0, entry.get(f"eta2_{factor}", 0.0)))
            w = share * bar_w
            if w > 0.5:
                svg.append(f'<rect x="{offset:.1f}" y="{y + 2}" width="{w:.1f}" height="{row_h - 6}" '
                           f'fill="{FACTOR_COLORS[factor]}"><title>{factor}: {share:.0%}</title></rect>')
            offset += w
        svg.append(f'<text x="{label_w + bar_w + 8}" y="{y + 12}" font-size="11" fill="#64748b">sd '
                   f'{entry["sd"]:.3f}</text>')
    svg.append("</svg>")
    return "".join(svg)


def _forest(entry: dict) -> str:
    """Forest plot: one CI per corpus, the pooled random effect as a diamond."""
    studies = entry["per_corpus"]
    pooled = entry.get("all")
    if not studies or not pooled:
        return ""
    lows = [s["effect"] - 1.96 * math.sqrt(s["variance"]) for s in studies] + [pooled["ci_low"], 0.0]
    highs = [s["effect"] + 1.96 * math.sqrt(s["variance"]) for s in studies] + [pooled["ci_high"], 0.0]
    lo, hi = min(lows), max(highs)
    span = (hi - lo) or 1.0
    width, label_w, plot_w, row_h = 760, 250, 300, 20
    sx = lambda v: label_w + (v - lo) / span * plot_w
    height = 48 + row_h * (len(studies) + 1)
    svg = [f'<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px" role="img" '
           f'aria-label="Forest plot {escape(entry["task"])} {escape(entry["protocol"])}: {escape(entry["system"])} vs '
           f'{escape(entry["baseline"])}">',
           f'<line x1="{sx(0):.1f}" y1="8" x2="{sx(0):.1f}" y2="{height - 18}" stroke="#94a3b8" stroke-dasharray="3 3"/>',
           f'<text x="{sx(0):.1f}" y="{height - 5}" text-anchor="middle" font-size="10" fill="#64748b">0 = no difference</text>']
    for i, s in enumerate(studies):
        y = 20 + row_h * i
        half = 1.96 * math.sqrt(s["variance"])
        color = "#0f172a" if s["evidence"] == "evidence" else "#94a3b8"
        svg.append(f'<text x="{label_w - 8}" y="{y + 4}" text-anchor="end" font-size="11">{escape(s["corpus"])}</text>'
                   f'<line x1="{sx(s["effect"] - half):.1f}" y1="{y}" x2="{sx(s["effect"] + half):.1f}" y2="{y}" '
                   f'stroke="{color}" stroke-width="1.5"/><rect x="{sx(s["effect"]) - 3.5:.1f}" y="{y - 3.5}" '
                   f'width="7" height="7" fill="{color}"><title>{s["effect"]:+.3f} ({s["runs"]} runs, '
                   f'{escape(s["evidence"])})</title></rect>'
                   f'<text x="{label_w + plot_w + 10}" y="{y + 4}" font-size="11">{s["effect"]:+.3f}</text>')
    y = 20 + row_h * len(studies) + 4
    c, l, h = sx(pooled["pooled"]), sx(pooled["ci_low"]), sx(pooled["ci_high"])
    svg.append(f'<text x="{label_w - 8}" y="{y + 4}" text-anchor="end" font-size="11" font-weight="600">pooled '
               f'(I² {pooled["i2"]:.0%})</text><polygon points="{l:.1f},{y} {c:.1f},{y - 6} {h:.1f},{y} {c:.1f},{y + 6}" '
               f'fill="#2563eb"/><text x="{label_w + plot_w + 10}" y="{y + 4}" font-size="11" font-weight="600">'
               f'{pooled["pooled"]:+.3f} [{pooled["ci_low"]:+.3f}, {pooled["ci_high"]:+.3f}]</text></svg>')
    return "".join(svg)


def _meta(analysis: dict, system: str = "seo-magus") -> str:
    entries = [m for m in analysis["meta"] if m["system"] == system and m.get("all") and m["all"]["sources"] >= 2]
    if not entries:
        return ""
    parts = [f'<section id="meta"><h2>Meta-analysis across sources ({escape(system)})</h2><p class="sub">Paired '
             "difference of the primary metric against each baseline, per corpus (mean over its runs, 95% CI) and "
             "pooled with random effects (DerSimonian-Laird). I² = share of the variation due to real differences "
             "between corpora: a high I² means the advantage depends on the source. Grey = corpora that are not "
             "evidence (synthetic, tiny).</p>"]
    for entry in entries:
        real = entry.get("real")
        note = (f" · real sources only: {real['pooled']:+.3f} [{real['ci_low']:+.3f}, {real['ci_high']:+.3f}]"
                if real else " · no real source yet")
        label = entry["task"] + ("" if entry["protocol"] == "-" else f" / {entry['protocol']}")
        parts.append(f"<h3>{escape(label)}: vs {escape(entry['baseline'])}{escape(note)}</h3>{_forest(entry)}")
    parts.append("</section>")
    return "".join(parts)


def _diagnostics(rows: Sequence[Row]) -> str:
    strata = [r for r in rows if r.task == "links" and r.metric.startswith("recall[")]
    if not strata:
        return ""
    parts = ['<section id="diagnostics"><h2>Link diagnostics</h2><p class="sub">Recall per difficulty stratum '
             "(does the human anchor name 2+, 1 or 0 words of the target title?) and, on synthetic corpora, per planted "
             "link style; mean over runs. Reachable by anchor-based linking: names-2+, full, inflected.</p>"]
    for (corpus, protocol), members in sorted(group(strata, "corpus", "protocol").items()):
        metrics = sorted({r.metric for r in members}, key=lambda m: (m.startswith("recall[style"), m))
        systems = sorted({r.system for r in members})
        means = {(s, m): sum(r.value for r in v) / len(v) for (s, m), v in group(members, "system", "metric").items()}
        head = "".join(f"<th>{escape(m[len('recall['):-1])}</th>" for m in metrics)
        body = "".join(
            f"<tr><td>{escape(s)}</td>" + "".join(
                f'<td class="num" style="background:{_skill_color(means.get((s, m)))}">{_fmt(means.get((s, m)), 2)}</td>'
                for m in metrics) + "</tr>" for s in systems)
        parts.append(f"<h3>{escape(corpus)} / {escape(protocol)}</h3><div class=\"scroll\"><table><thead><tr>"
                     f"<th>system</th>{head}</tr></thead><tbody>{body}</tbody></table></div>")
    parts.append("</section>")
    return "".join(parts)


def _power_label(exponent: int) -> str:
    value = 10 ** exponent
    for unit, size in (("M", 10 ** 6), ("k", 10 ** 3)):
        if value >= size:
            return f"{value // size}{unit}"
    return str(value) if exponent >= 0 else f"{value:g}"


def _scale_svg(result: dict) -> str:
    """Log-log cost chart with n (linear) and n² (quadratic) reference slopes from the first point."""
    rows = [r for r in result.get("rows", []) if r.get("seconds", 0) > 0 and r.get("classifier_calls", 0) > 0]
    if len(rows) < 2:
        return ""
    width, height, left, right, top, bottom = 680, 320, 60, 150, 20, 44
    xs = [math.log10(r["pages"]) for r in rows]
    series = {"seconds": [math.log10(r["seconds"]) for r in rows],
              "classifier calls": [math.log10(r["classifier_calls"]) for r in rows]}
    first_calls = series["classifier calls"][0]
    guides = {"n (linear)": 1, "n² (quadratic)": 2}
    guide_ends = {name: first_calls + slope * (xs[-1] - xs[0]) for name, slope in guides.items()}
    exhaustive = [(math.log10(r["pages"]), math.log10(r["exhaustive_calls"]), r["exhaustive_calls"])
                  for r in rows if r.get("exhaustive_calls")]
    all_y = [y for ys in series.values() for y in ys] + list(guide_ends.values()) + [y for _, y, _ in exhaustive]
    y0, y1 = math.floor(min(all_y)), math.ceil(max(all_y))
    x0, x1 = xs[0], xs[-1]
    sx = lambda x: left + (x - x0) / ((x1 - x0) or 1) * (width - left - right)
    sy = lambda y: height - bottom - (y - y0) / ((y1 - y0) or 1) * (height - top - bottom)
    colors = {"seconds": "#2563eb", "classifier calls": "#16a34a"}
    svg = [f'<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px" role="img" '
           'aria-label="Cost against site size (log-log)">',
           f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="#334155"/>',
           f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#334155"/>']
    for exponent in range(y0, y1 + 1):
        y = sy(exponent)
        svg.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#f1f5f9"/>'
                   f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="10">{_power_label(exponent)}</text>')
    for r, x in zip(rows, xs):
        svg.append(f'<text x="{sx(x):.1f}" y="{height - bottom + 16}" text-anchor="middle" font-size="11">{r["pages"]}</text>')
    for i, (name, slope) in enumerate(guides.items()):
        at = x0 + (0.35 + 0.25 * i) * (x1 - x0)                   # label along the line, not at its end
        svg.append(f'<line x1="{sx(x0):.1f}" y1="{sy(first_calls):.1f}" x2="{sx(x1):.1f}" y2="{sy(guide_ends[name]):.1f}" '
                   f'stroke="#cbd5e1" stroke-dasharray="4 4"/><text x="{sx(at):.1f}" '
                   f'y="{sy(first_calls + slope * (at - x0)) - 6:.1f}" font-size="10" fill="#94a3b8" '
                   f'text-anchor="end">{name}</text>')
    for name, ys in series.items():
        points = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in zip(xs, ys))
        svg.append(f'<polyline points="{points}" fill="none" stroke="{colors[name]}" stroke-width="2"/>'
                   + "".join(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="3" fill="{colors[name]}"/>'
                             for x, y in zip(xs, ys))
                   + f'<text x="{sx(x1) + 6:.1f}" y="{sy(ys[-1]) + 4:.1f}" font-size="11" fill="{colors[name]}">{name}</text>')
    for x, y, calls in exhaustive:
        svg.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="4" fill="#dc2626"/><text x="{sx(x) + 8:.1f}" '
                   f'y="{sy(y) + 4:.1f}" font-size="11" fill="#dc2626">exhaustive flow: {calls:,} calls</text>')
    svg.append(f'<text x="{(left + width - right) / 2}" y="{height - 8}" text-anchor="middle" font-size="11">pages '
               "(log scale); y: seconds or classifier calls (log scale)</text></svg>")
    return "".join(svg)


def _engineering(report: dict) -> str:
    parts = []
    crawl = report.get("crawl")
    if crawl:
        body = "".join(
            f"<tr><td>{escape(r.get('corpus', '?'))}</td><td class=\"num\">{r['documents']}</td>" + "".join(
                f'<td class="num" style="background:{_skill_color(r[k])}">{_fmt(r[k])}</td>'
                for k in ("coverage", "title_exact", "paragraphs_exact", "link_recall", "link_precision"))
            + f"<td class=\"num\">{r['navigation_leaks']}</td><td class=\"num\">{r['pages_per_second']}</td></tr>"
            for r in crawl)
        parts.append('<section id="crawl"><h2>Crawl fidelity</h2><table><thead><tr><th>corpus</th><th>documents</th>'
                     "<th>coverage</th><th>titles</th><th>paragraphs</th><th>link recall</th><th>link precision</th>"
                     f"<th>nav leaks</th><th>pages/s (lower bound)</th></tr></thead><tbody>{body}</tbody></table></section>")
    scale = report.get("scale")
    if scale:
        body = "".join(
            f"<tr><td class=\"num\">{r['pages']}</td><td class=\"num\">{r['seconds']}</td>"
            f"<td class=\"num\">{r['classifier_calls']}</td><td class=\"num\">{r['links']}</td>"
            f"<td class=\"num\">{r.get('exhaustive_calls', '-')}</td>"
            f"<td>{'yes' if r.get('identical_links') else ('-' if 'identical_links' not in r else '<b>NO</b>')}</td></tr>"
            for r in scale["rows"])
        parts.append(f'<section id="scale"><h2>Scale</h2><p class="sub">time ~ n^{scale["time_exponent"]:.2f}, classifier '
                     f'calls ~ n^{scale["calls_exponent"]:.2f}</p>{_scale_svg(scale)}<table><thead><tr><th>pages</th>'
                     "<th>seconds</th><th>classifier calls</th><th>links</th><th>exhaustive calls</th>"
                     f"<th>identical links</th></tr></thead><tbody>{body}</tbody></table></section>")
    return "".join(parts)


def render_html(report: dict, rows: Sequence[Row], analysis: dict) -> str:
    sections = [("summary", "Summary"), ("claims", "Claims"), ("scores", "Scores"), ("ranks", "Ranks"),
                ("methodologies", "Methodologies"), ("meta", "Meta-analysis"), ("diagnostics", "Link diagnostics"),
                ("crawl", "Crawl"), ("scale", "Scale")]
    body = (_cards(report, analysis) + _claims(report) + (_scores(analysis) if rows else "") + _ranks(analysis)
            + _methodologies(analysis) + _meta(analysis) + _diagnostics(rows) + _engineering(report))
    toc = "".join(f'<a href="#{anchor}">{label}</a>' for anchor, label in sections if f'id="{anchor}"' in body)
    subtitle = (f"Protocol v{escape(str(report.get('protocol', {}).get('version', '?')))} · hash "
                f"{escape(str(report.get('protocol_hash', '?')))} · generated {escape(str(report.get('generated_at', '?')))}")
    return ("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" "
            "content=\"width=device-width, initial-scale=1\"><title>SEO-Magus evaluation</title>"
            f"<style>{CSS}</style></head><body><header><h1>SEO-Magus evaluation</h1><p>{subtitle}</p></header><main>"
            f'<nav class="toc">{toc}</nav>{body}</main></body></html>')
