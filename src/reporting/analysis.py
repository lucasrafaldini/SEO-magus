"""
Per-page ranking analysis of one optimization run.

"Ranks best" here means internal link equity: PageRank of the site's own link
graph, before (crawl links only) and after (crawl + approved links). CheiRank
shows hub pages, the pillar-weighted PageRank discounts equity by click depth,
and Search Console positions (when available) show how pages actually rank.
"""

import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from src.config import SiteConfig
from src.connectors.gsc_connector import GSCQueryRow
from src.connectors.sitemap_crawler import ParsedPage
from src.engines.link_graph import LinkGraph, NoPillarsWarning
from src.engines.taxonomy import url_key
from src.log import get_logger
from src.workflows.linking_optimizer import AuditReport, LinkDecision
from src.workflows.site_audit import SiteAuditReport

logger = get_logger(__name__)

Link = Tuple[str, str]


@dataclass
class PageMetrics:
    url: str
    label: str
    role: str
    cluster: str
    crawled: bool                       # False for link targets that were not crawled
    pagerank_before: float
    pagerank_after: float
    rank_before: int                    # 1 = best
    rank_after: int
    cheirank: float
    weighted_pagerank: Optional[float]  # None when the site has no pillars
    click_depth: Optional[int]          # from the nearest pillar, None if unreachable
    inbound_before: int
    inbound_after: int
    outbound_after: int
    new_inbound: int
    new_outbound: int
    gsc_query: Optional[str] = None     # best (most impressions) Search Console query
    gsc_position: Optional[float] = None
    gsc_impressions: int = 0
    page2: bool = False
    navigation_inbound: int = 0         # pages linking here from header/nav/footer (crawled sites)
    indexable: bool = True              # False for noindex pages and canonicalized duplicates

    @property
    def rank_change(self) -> int:
        """Positive = moved up the internal ranking."""
        return self.rank_before - self.rank_after

    @property
    def orphan_before(self) -> bool:
        """No internal link at all (contextual or navigation) points here."""
        return self.inbound_before == 0 and self.navigation_inbound == 0

    @property
    def orphan_after(self) -> bool:
        return self.inbound_after == 0 and self.navigation_inbound == 0


@dataclass
class BenchmarkVerdict:
    expectation_source: str
    expected: int
    found: List[Link]
    missing: List[Tuple[Link, LinkDecision, bool]]   # (link, why refused, is a known gap)
    unexpected: List[Link]                           # only reported for exhaustive benchmarks
    recall: float
    precision: Optional[float]


@dataclass
class SiteAnalysis:
    key: str
    name: str
    pages: List[PageMetrics]            # sorted by pagerank_after, best first
    report: AuditReport
    config: SiteConfig
    existing_links: List[Link]
    new_links: List[Link]
    benchmark: Optional[BenchmarkVerdict] = None
    notes: List[str] = field(default_factory=list)
    site_audit: Optional[SiteAuditReport] = None

    def page(self, url: str) -> PageMetrics:
        return next(p for p in self.pages if p.url == url)

    @property
    def clusters(self) -> List[str]:
        """Clusters ordered by their total link equity (strongest first)."""
        totals: Dict[str, float] = {}
        for p in self.pages:
            totals[p.cluster] = totals.get(p.cluster, 0.0) + p.pagerank_after
        return sorted(totals, key=lambda c: -totals[c])


def short_label(url: str) -> str:
    """Last path segment (the slug) of a page URL; renderers truncate it for display."""
    parsed = urlparse(url)
    return parsed.path.rstrip("/").rsplit("/", 1)[-1] or "/"


def _ranks(scores: Dict[str, float]) -> Dict[str, int]:
    ordered = sorted(scores, key=lambda url: (-scores[url], url))
    return {url: index for index, url in enumerate(ordered, start=1)}


def analyze_site(
    key: str,
    name: str,
    pages: List[ParsedPage],
    baseline_graph: LinkGraph,
    graph: LinkGraph,
    report: AuditReport,
    config: SiteConfig,
    gsc_rows: Optional[List[GSCQueryRow]] = None,
) -> SiteAnalysis:
    """Compute the per-page metrics of one optimization run."""
    pr_before = baseline_graph.compute_pagerank()
    pr_after = graph.compute_pagerank()
    cheirank = graph.compute_cheirank()
    depths = graph.compute_pillar_depths()
    weighted: Dict[str, float] = {}
    if depths:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NoPillarsWarning)
            weighted = graph.compute_weighted_pagerank()
    rank_before, rank_after = _ranks(pr_before), _ranks(pr_after)

    best_rows: Dict[Tuple[str, str], GSCQueryRow] = {}
    for row in gsc_rows or []:
        k = url_key(row.page)
        if k not in best_rows or row.impressions > best_rows[k].impressions:
            best_rows[k] = row
    t = config.thresholds

    crawled = {page.url for page in pages}
    indexable = {page.url: page.indexable for page in pages}
    navigation_inbound: Dict[str, int] = {}
    for page in pages:
        for target in page.navigation_links:
            navigation_inbound[target] = navigation_inbound.get(target, 0) + 1
    metrics = []
    for url in graph.nodes:
        meta = graph.page_metadata[url]
        row = best_rows.get(url_key(url))
        metrics.append(PageMetrics(
            url=url,
            label=short_label(url),
            role=meta["role"],
            cluster=meta["cluster"],
            crawled=url in crawled,
            pagerank_before=pr_before[url],
            pagerank_after=pr_after[url],
            rank_before=rank_before[url],
            rank_after=rank_after[url],
            cheirank=cheirank[url],
            weighted_pagerank=weighted.get(url) if weighted else None,
            click_depth=depths.get(url),
            inbound_before=len(baseline_graph.in_edges[url]),
            inbound_after=len(graph.in_edges[url]),
            outbound_after=len(graph.edges[url]),
            new_inbound=len(graph.in_edges[url] - baseline_graph.in_edges[url]),
            new_outbound=len(graph.edges[url] - baseline_graph.edges[url]),
            gsc_query=row.query if row else None,
            gsc_position=row.position if row else None,
            gsc_impressions=row.impressions if row else 0,
            page2=bool(row) and t.page2_min_position <= row.position <= t.page2_max_position
            and row.impressions >= t.min_impressions,
            navigation_inbound=navigation_inbound.get(url, 0),
            indexable=indexable.get(url, True),
        ))
    metrics.sort(key=lambda m: m.rank_after)

    existing = sorted((s, t_) for s, targets in baseline_graph.edges.items() for t_ in targets)
    new = [(r.source_url, r.target_url) for r in report.results]
    analysis = SiteAnalysis(key, name, metrics, report, config, existing, new)
    if not depths:
        analysis.notes.append("No pillar pages configured: the pillar-weighted PageRank is not shown.")
    logger.info(
        "Analysis of %s: best page %s (PageRank %.3f), %d pages moved up, orphans %d -> %d",
        name, metrics[0].url if metrics else "-", metrics[0].pagerank_after if metrics else 0.0,
        sum(1 for m in metrics if m.rank_change > 0),
        sum(1 for m in metrics if m.orphan_before), sum(1 for m in metrics if m.orphan_after),
    )
    return analysis


def analyze_benchmark(run) -> SiteAnalysis:
    """SiteAnalysis of a BenchmarkRun, including the benchmark verdict."""
    site, optimizer = run.site, run.optimizer
    gsc_rows = site.build_gsc_rows() if site.build_gsc_rows else None
    analysis = analyze_site(
        site.key, site.name, run.pages, run.baseline_graph, run.link_graph, run.report, run.config, gsc_rows
    )
    missing = []
    for link in sorted(run.missing_links):
        decision = optimizer.explain_link(*link)
        missing.append((link, decision, site.known_gaps.get(link) == decision.reason))
    analysis.site_audit = run.site_audit
    analysis.benchmark = BenchmarkVerdict(
        expectation_source=site.expectation_source,
        expected=len(site.expected_links),
        found=sorted(run.found_links),
        missing=missing,
        unexpected=sorted(run.unexpected_links) if site.exhaustive else [],
        recall=run.recall,
        precision=run.precision,
    )
    return analysis
