"""
Terminal output: ranking leaderboard, benchmark verdict, site audit and
proposed links.

Output is plain ASCII by default so it renders correctly in every terminal,
console code page and log file. Box-drawing characters and glyphs are opt-in
(--unicode or SEO_MAGUS_UNICODE=1). Colour (ANSI) is only used on an interactive
terminal and never when NO_COLOR is set or with --no-color. Tables are laid out
here (no third-party renderer): they never exceed the terminal width, long cells
are truncated with "..." instead of wrapping.
"""

import os
import shutil
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from src.reporting.analysis import SiteAnalysis

UNICODE_ENV = "SEO_MAGUS_UNICODE"
DEFAULT_WIDTH = 100
ANSI = {"red": "31", "green": "32", "yellow": "33", "blue": "34", "magenta": "35", "dim": "2", "bold": "1"}
ROLE_COLORS = {"pillar": "magenta", "money": "green", "support": "blue"}
SEVERITY_COLORS = {"error": "red", "warning": "yellow", "notice": "dim"}

_ASCII = {"ok": "[OK]", "fail": "[X]", "arrow": "->", "bar": "#", "empty": ".", "none": "-",
          "section": ">>", "item": "  -", "ellipsis": "...",
          "h": "-", "v": "|", "tl": "+", "tm": "+", "tr": "+", "ml": "+", "mm": "+", "mr": "+", "bl": "+", "bm": "+", "br": "+"}
_UNICODE = {"ok": "✓", "fail": "✗", "arrow": "→", "bar": "█", "empty": "·", "none": "∞",
            "section": "▶", "item": "  ↳", "ellipsis": "…",
            "h": "─", "v": "│", "tl": "┌", "tm": "┬", "tr": "┐", "ml": "├", "mm": "┼", "mr": "┤", "bl": "└", "bm": "┴", "br": "┘"}


def _env_flag(name: str) -> Optional[bool]:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class TerminalStyle:
    unicode: bool = False
    color: bool = False
    width: int = DEFAULT_WIDTH

    @classmethod
    def detect(cls, stream=None, unicode: Optional[bool] = None, color: Optional[bool] = None,
               width: Optional[int] = None) -> "TerminalStyle":
        """Explicit arguments > environment (SEO_MAGUS_UNICODE, NO_COLOR, TERM) > terminal detection."""
        stream = stream or sys.stdout
        is_tty = bool(getattr(stream, "isatty", lambda: False)())
        if unicode is None:
            unicode = bool(_env_flag(UNICODE_ENV))
        if color is None:
            color = is_tty and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"
        if width is None:
            width = shutil.get_terminal_size((DEFAULT_WIDTH, 24)).columns if is_tty else DEFAULT_WIDTH
        return cls(unicode=unicode, color=color, width=max(40, width))

    def sym(self, name: str) -> str:
        return (_UNICODE if self.unicode else _ASCII)[name]

    def paint(self, text: str, color: str = "") -> str:
        if not (self.color and color in ANSI):
            return text
        return f"\x1b[{ANSI[color]}m{text}\x1b[0m"


_style = TerminalStyle()


def configure_terminal(style: TerminalStyle) -> TerminalStyle:
    global _style
    _style = style
    return style


def get_style() -> TerminalStyle:
    return _style


def _truncate(text: str, length: int, style: TerminalStyle) -> str:
    if len(text) <= length:
        return text
    ellipsis = style.sym("ellipsis")
    if length <= len(ellipsis):
        return text[:length]
    return text[: length - len(ellipsis)] + ellipsis


@dataclass
class Column:
    name: str
    align: str = "left"        # left | right
    min_width: int = 3
    flex: bool = False          # may shrink below its content width
    shrink_order: int = 0       # flexible columns with lower values shrink first
    drop_order: Optional[int] = None  # optional column: dropped (lowest first) when even minimum widths don't fit


@dataclass
class TableRow:
    cells: Sequence[str]
    colors: Sequence[str] = field(default_factory=tuple)   # per-cell colour names ("" = none)


def render_table(title: str, columns: List[Column], rows: List[TableRow], style: TerminalStyle) -> List[str]:
    """Lay out a table that fits style.width; returns its lines (no trailing spaces)."""
    s = style.sym
    columns, rows = list(columns), list(rows)
    # Narrow terminals: drop optional columns until the minimum layout fits.
    while sum(c.min_width for c in columns) + 3 * len(columns) + 1 > style.width:
        optional = [i for i, c in enumerate(columns) if c.drop_order is not None]
        if not optional:
            break
        drop = min(optional, key=lambda i: columns[i].drop_order)
        columns.pop(drop)
        rows = [TableRow([c for j, c in enumerate(r.cells) if j != drop],
                         [c for j, c in enumerate(r.colors) if j != drop]) for r in rows]
    n = len(columns)
    natural = [max([len(c.name)] + [len(str(r.cells[i])) for r in rows]) for i, c in enumerate(columns)]
    widths = [max(c.min_width, w) for c, w in zip(columns, natural)]
    available = style.width - (3 * n + 1)          # "| " + " | " separators + " |"
    overflow = sum(widths) - available
    for i in sorted((i for i, c in enumerate(columns) if c.flex), key=lambda i: columns[i].shrink_order):
        if overflow <= 0:
            break
        reduce = min(overflow, widths[i] - columns[i].min_width)
        widths[i] -= reduce
        overflow -= reduce

    def line(left: str, mid: str, right: str) -> str:
        return left + mid.join(s("h") * (w + 2) for w in widths) + right

    def cells(values: Sequence[str], colors: Sequence[str] = ()) -> str:
        out = []
        for i, (value, column) in enumerate(zip(values, columns)):
            text = _truncate(str(value), widths[i], style)
            padded = text.rjust(widths[i]) if column.align == "right" else text.ljust(widths[i])
            color = colors[i] if i < len(colors) else ""
            out.append(style.paint(padded, color) if color else padded)
        return f"{s('v')} " + f" {s('v')} ".join(out) + f" {s('v')}"

    lines = [style.paint(_truncate(title, style.width, style), "bold")] if title else []
    lines.append(line(s("tl"), s("tm"), s("tr")))
    lines.append(cells([c.name for c in columns]))
    lines.append(line(s("ml"), s("mm"), s("mr")))
    lines += [cells(r.cells, r.colors) for r in rows]
    lines.append(line(s("bl"), s("bm"), s("br")))
    return lines


def _print_lines(lines: List[str], file) -> None:
    for text in lines:
        print(text, file=file)


def _bar(value: float, maximum: float, width: int, style: TerminalStyle) -> str:
    filled = round(width * value / maximum) if maximum else 0
    return style.sym("bar") * filled + style.sym("empty") * (width - filled)


def _change(delta: int) -> str:
    return f"+{delta}" if delta > 0 else (str(delta) if delta < 0 else "=")


def print_leaderboard(analysis: SiteAnalysis, limit: int = 10, file=None, style: Optional[TerminalStyle] = None) -> None:
    """Top pages by internal PageRank after optimization, best first."""
    file = file or sys.stdout
    style = style or get_style()
    pages = analysis.pages[:limit]
    maximum = max((p.pagerank_after for p in analysis.pages), default=1.0)
    bar_width = 4 if style.width < 70 else (8 if style.width < 110 else 16)
    columns = [
        Column("#", "right", 2), Column("chg", "right", 3),
        Column("page", min_width=10, flex=True, shrink_order=3),
        Column("role", min_width=7, drop_order=5), Column("cluster", min_width=5, flex=True, shrink_order=2, drop_order=3),
        Column("PageRank", min_width=bar_width + 7), Column("hub", "right", 5, drop_order=1),
        Column("depth", "right", 5, drop_order=2), Column("in", "right", 4),
        Column("flags", min_width=5, flex=True, shrink_order=1, drop_order=4),
    ]
    rows = []
    for p in pages:
        flags = " ".join(f for f, on in [("page2", p.page2), ("orphan", p.orphan_after), ("uncrawled", not p.crawled),
                                         ("noindex", p.crawled and not p.indexable)] if on)
        change_color = "green" if p.rank_change > 0 else ("red" if p.rank_change < 0 else "dim")
        rows.append(TableRow(
            [str(p.rank_after), _change(p.rank_change), p.label, p.role, p.cluster,
             f"{_bar(p.pagerank_after, maximum, bar_width, style)} {100 * p.pagerank_after:4.1f}%",
             f"{100 * p.cheirank:.1f}%", style.sym("none") if p.click_depth is None else str(p.click_depth),
             f"{p.inbound_before}{style.sym('arrow')}{p.inbound_after}", flags or "-"],
            ["", change_color, "", ROLE_COLORS.get(p.role, ""), "", "", "", "", "", "yellow" if flags else "dim"],
        ))
    title = f"Ranking: {analysis.name} (internal PageRank after optimization, top {len(pages)} of {len(analysis.pages)})"
    _print_lines(render_table(title, columns, rows, style), file)
    legend = (f"  chg = places gained | hub = CheiRank | depth = clicks from the nearest pillar | "
              f"in = contextual links in, before{style.sym('arrow')}after")
    print(_truncate(legend, style.width, style), file=file)


def print_verdict(analysis: SiteAnalysis, file=None, style: Optional[TerminalStyle] = None) -> None:
    """Benchmark verdict: expected links found, and why missing ones were refused."""
    file = file or sys.stdout
    style = style or get_style()
    b = analysis.benchmark
    if b is None:
        return
    precision = "" if b.precision is None else f" | precision {b.precision:.0%}"
    mark = style.sym("ok") if b.recall == 1.0 and not b.unexpected else style.sym("fail")
    print(f"  {mark} Expected links found: {len(b.found)}/{b.expected} (recall {b.recall:.0%}{precision})", file=file)
    print(f"      source: {b.expectation_source}", file=file)
    arrow = style.sym("arrow")
    for (source, target), decision, known in b.missing:
        label = " [known gap]" if known else ""
        print(f"    {style.sym('fail')} missing{label} {analysis.page(source).label} {arrow} "
              f"{analysis.page(target).label}: {decision.reason} ({decision.detail})", file=file)
    for source, target in b.unexpected:
        print(f"    {style.sym('fail')} unexpected {analysis.page(source).label} {arrow} {analysis.page(target).label}",
              file=file)


def print_site_audit(analysis: SiteAnalysis, limit: int = 25, file=None, style: Optional[TerminalStyle] = None) -> None:
    """Site health summary and the issues found by the crawl audit."""
    file = file or sys.stdout
    style = style or get_style()
    audit = analysis.site_audit
    if audit is None:
        return
    counts = audit.by_severity
    print(f"  Site health: {len(audit.healthy_pages)}/{len(audit.pages)} healthy pages ({audit.health:.0%}) | "
          f"{counts['error']} errors, {counts['warning']} warnings, {counts['notice']} notices", file=file)
    if not audit.issues:
        return
    rows = [
        TableRow([issue.severity, issue.code, issue.url, issue.detail], [SEVERITY_COLORS.get(issue.severity, "")])
        for issue in audit.issues[:limit]
    ]
    columns = [Column("severity", min_width=8), Column("issue", min_width=12, flex=True, shrink_order=3),
               Column("url", min_width=16, flex=True, shrink_order=2),
               Column("detail", min_width=16, flex=True, shrink_order=1, drop_order=1)]
    title = f"Site audit issues (top {min(limit, len(audit.issues))} of {len(audit.issues)})"
    _print_lines(render_table(title, columns, rows, style), file)
    if len(audit.issues) > limit:
        print(f"    ... {len(audit.issues) - limit} more issues not shown (all of them are in the HTML report)", file=file)


def print_links(analysis: SiteAnalysis, limit: Optional[int] = None, file=None, style: Optional[TerminalStyle] = None) -> None:
    """Proposed links with their rewritten sentence."""
    file = file or sys.stdout
    style = style or get_style()
    arrow, item = style.sym("arrow"), style.sym("item")
    results = analysis.report.results[:limit]
    print(f"  Proposed links: {len(analysis.report.results)}", file=file)
    for r in results:
        boost = f" | boosts page 2 query '{r.page2_query}'" if r.page2_query else ""
        print(f"    {analysis.page(r.source_url).label} {arrow} {analysis.page(r.target_url).label} "
              f"[{r.anchor_text}] score {r.relevance_score}, confidence {r.confidence:.2f} ({r.classifier}){boost}",
              file=file)
        print(f"  {item} {r.updated_sentence}", file=file)
