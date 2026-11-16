"""
Site Audit: technical / structural SEO checks on a crawl.

Works on a CrawlResult (real HTTP crawl), independently of the link optimizer.
Click depth is measured from the start page over every internal link
(content and navigation), following redirects.

errors    orphan_page, broken_internal_link, sitemap_url_broken, missing_title,
          redirect_loop, canonical_broken
warnings  duplicate_title, missing_h1, multiple_h1, generic_anchor,
          redirected_internal_link, redirect_chain, deep_page, unreachable_page,
          not_in_sitemap, no_contextual_inbound, noindex_in_sitemap,
          sitemap_url_redirect, broken_external_link
notices   missing_meta_description, canonicalized_page, nofollow_internal_link, slow_page

On-page and structural checks only apply to indexable pages (HTTP 200, no
noindex, canonical to themselves): a noindex page or a canonicalized duplicate
is not expected to rank. "Healthy pages" = indexable pages affected by no error
or warning.
"""

import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from src.connectors.sitemap_crawler import LOCATION_CONTENT, CrawlResult
from src.log import get_logger

logger = get_logger(__name__)

ERROR, WARNING, NOTICE = "error", "warning", "notice"
SEVERITY_ORDER = {ERROR: 0, WARNING: 1, NOTICE: 2}

ISSUE_SEVERITY = {
    "orphan_page": ERROR,
    "broken_internal_link": ERROR,
    "sitemap_url_broken": ERROR,
    "missing_title": ERROR,
    "redirect_loop": ERROR,
    "canonical_broken": ERROR,
    "duplicate_title": WARNING,
    "missing_h1": WARNING,
    "multiple_h1": WARNING,
    "generic_anchor": WARNING,
    "redirected_internal_link": WARNING,
    "deep_page": WARNING,
    "unreachable_page": WARNING,
    "not_in_sitemap": WARNING,
    "no_contextual_inbound": WARNING,
    "redirect_chain": WARNING,
    "noindex_in_sitemap": WARNING,
    "sitemap_url_redirect": WARNING,
    "broken_external_link": WARNING,
    "missing_meta_description": NOTICE,
    "canonicalized_page": NOTICE,
    "nofollow_internal_link": NOTICE,
    "slow_page": NOTICE,
}

# Anchors that say nothing about the target (English and Portuguese).
GENERIC_ANCHORS = frozenset({
    "click here", "here", "read more", "more", "learn more", "this", "this page", "link", "continue",
    "go", "see more", "find out more", "details",
    "clique aqui", "aqui", "saiba mais", "leia mais", "veja mais", "mais", "continue lendo", "confira",
})
_PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)

DEFAULT_MAX_CLICK_DEPTH = 3
DEFAULT_SLOW_PAGE_MS = 2000


@dataclass(frozen=True)
class SeoIssue:
    code: str
    url: str                                  # the page (or URL) the issue is about
    detail: str = ""
    affected_pages: FrozenSet[str] = frozenset()  # crawled pages that carry the problem

    @property
    def severity(self) -> str:
        return ISSUE_SEVERITY[self.code]


@dataclass
class SiteAuditReport:
    start_url: str
    pages: List[str]                           # indexable pages (the ones that can rank)
    issues: List[SeoIssue]
    click_depths: Dict[str, Optional[int]]     # None = not reachable from the start page
    max_click_depth: int
    counts: Dict[str, int] = field(default_factory=dict)
    non_indexable: List[str] = field(default_factory=list)  # noindex pages and canonicalized duplicates

    @property
    def by_severity(self) -> Dict[str, int]:
        totals = {ERROR: 0, WARNING: 0, NOTICE: 0}
        for issue in self.issues:
            totals[issue.severity] += 1
        return totals

    @property
    def unhealthy_pages(self) -> Set[str]:
        return {page for i in self.issues if i.severity != NOTICE for page in i.affected_pages}

    @property
    def healthy_pages(self) -> List[str]:
        unhealthy = self.unhealthy_pages
        return [p for p in self.pages if p not in unhealthy]

    @property
    def health(self) -> float:
        return len(self.healthy_pages) / len(self.pages) if self.pages else 1.0

    def issue_keys(self) -> Set[Tuple[str, str]]:
        return {(issue.code, issue.url) for issue in self.issues}


def _is_generic(anchor: str) -> bool:
    return _PUNCTUATION_RE.sub("", anchor).strip().lower() in GENERIC_ANCHORS


def _click_depths(crawl: CrawlResult) -> Dict[str, Optional[int]]:
    pages = {p.url: p for p in crawl.pages}
    start = crawl.redirects.get(crawl.start_url, crawl.start_url)
    depths: Dict[str, Optional[int]] = {url: None for url in pages}
    if start not in pages:
        return depths
    depths[start] = 0
    queue = deque([start])
    while queue:
        url = queue.popleft()
        for link in pages[url].links:
            target = link.target
            if link.internal and target in pages and depths[target] is None and target != start:
                depths[target] = depths[url] + 1
                queue.append(target)
    return depths


def audit_site(crawl: CrawlResult, max_click_depth: int = DEFAULT_MAX_CLICK_DEPTH,
               slow_page_ms: int = DEFAULT_SLOW_PAGE_MS) -> SiteAuditReport:
    """Run every check on a crawl and return the issues found."""
    all_pages = {p.url: p for p in crawl.pages}
    pages = {url: p for url, p in all_pages.items() if p.indexable}
    start = crawl.redirects.get(crawl.start_url, crawl.start_url)
    issues: List[SeoIssue] = []

    def add(code: str, url: str, detail: str = "", affected=None):
        issues.append(SeoIssue(code, url, detail, frozenset(affected if affected is not None else [url])))

    # -- indexability
    for url, page in all_pages.items():
        if page.canonicalized:
            add("canonicalized_page", url, f"canonical points to {page.canonical}", affected=[])
            status = crawl.statuses.get(page.canonical)
            if status is not None and (status == 0 or status >= 400):
                add("canonical_broken", url, f"canonical {page.canonical} answers HTTP {status}")

    # -- on-page checks
    titles: Dict[str, List[str]] = defaultdict(list)
    for url, page in pages.items():
        if not page.title:
            add("missing_title", url, "empty or missing <title>")
        else:
            titles[page.title.strip().lower()].append(url)
        if page.h1_count == 0:
            add("missing_h1", url, "no <h1> element")
        elif (page.h1_count or 0) > 1:
            add("multiple_h1", url, f"{page.h1_count} <h1> elements")
        if not page.meta_description:
            add("missing_meta_description", url, "no meta description")
        if page.response_ms > slow_page_ms:
            add("slow_page", url, f"answered in {page.response_ms:.0f} ms (max {slow_page_ms})")
    for title, urls in titles.items():
        if len(urls) > 1:
            for url in urls:
                others = ", ".join(u for u in urls if u != url)
                add("duplicate_title", url, f"same <title> as {others}")

    # -- links
    inbound: Dict[str, Set[str]] = defaultdict(set)
    inbound_content: Dict[str, Set[str]] = defaultdict(set)
    broken_sources: Dict[str, Set[str]] = defaultdict(set)
    redirect_sources: Dict[str, Set[str]] = defaultdict(set)
    external_sources: Dict[str, Set[str]] = defaultdict(set)
    for url, page in all_pages.items():
        for link in page.links:
            if not link.internal:
                if link.url in crawl.broken_external_urls:
                    external_sources[link.url].add(url)
                continue
            if link.location == LOCATION_CONTENT and link.anchor_text and _is_generic(link.anchor_text):
                add("generic_anchor", url, f"anchor '{link.anchor_text}' -> {link.target}")
            if link.nofollow:
                add("nofollow_internal_link", url, f"rel=nofollow on the link to {link.target}")
            status = crawl.statuses.get(link.url)
            if status is not None and (status == 0 or status >= 400):
                broken_sources[link.url].add(url)
            if link.url in crawl.redirects:
                redirect_sources[link.url].add(url)
            target = link.target
            if target in all_pages and target != url:
                inbound[target].add(url)
                if link.location == LOCATION_CONTENT:
                    inbound_content[target].add(url)
    for target, sources in sorted(broken_sources.items()):
        add("broken_internal_link", target,
            f"HTTP {crawl.statuses[target]} linked from {len(sources)} page(s)", affected=sources)
    for target, sources in sorted(redirect_sources.items()):
        add("redirected_internal_link", target,
            f"redirects to {crawl.redirects[target]}; linked from {len(sources)} page(s)", affected=sources)
    for target, sources in sorted(external_sources.items()):
        add("broken_external_link", target,
            f"HTTP {crawl.external_statuses[target]} linked from {len(sources)} page(s)", affected=sources)
    for url, hops in sorted(crawl.redirect_chains.items()):
        if url in crawl.redirect_loops:
            add("redirect_loop", url, " -> ".join(h for h, _ in hops), affected=redirect_sources.get(url, set()))
        elif len(hops) >= 2:
            add("redirect_chain", url, f"{len(hops)} redirects: " + " -> ".join(h for h, _ in hops)
                + f" -> {crawl.redirects[url]}", affected=redirect_sources.get(url, set()))

    # -- structure (indexable pages)
    depths = _click_depths(crawl)
    for url in pages:
        if url == start:
            continue
        if not inbound[url]:
            add("orphan_page", url, "no internal page links here (only reachable via the sitemap)")
        elif not inbound_content[url]:
            add("no_contextual_inbound", url, f"only linked from navigation ({len(inbound[url])} page(s))")
        depth = depths.get(url)
        if depth is None and inbound[url]:
            add("unreachable_page", url, "not reachable from the start page by following links")
        elif depth is not None and depth > max_click_depth:
            add("deep_page", url, f"{depth} clicks from the start page (max {max_click_depth})")

    # -- sitemap
    if crawl.sitemap_found:
        listed = {crawl.redirects.get(u, u) for u in crawl.sitemap_urls}
        for url in pages:
            if url not in listed:
                add("not_in_sitemap", url, "crawled page missing from the XML sitemap")
        for url in crawl.sitemap_urls:
            status = crawl.statuses.get(url)
            final = crawl.redirects.get(url, url)
            if status is not None and (status == 0 or status >= 400):
                add("sitemap_url_broken", url, f"listed in the sitemap but answers HTTP {status}", affected=[])
            elif url in crawl.redirects:
                add("sitemap_url_redirect", url, f"listed in the sitemap but redirects to {final}", affected=[])
            page = all_pages.get(final)
            if page is not None and page.noindex:
                add("noindex_in_sitemap", final, "listed in the sitemap but marked noindex", affected=[])

    issues.sort(key=lambda i: (SEVERITY_ORDER[i.severity], i.code, i.url))
    counts: Dict[str, int] = defaultdict(int)
    for issue in issues:
        counts[issue.code] += 1
    report = SiteAuditReport(crawl.start_url, list(pages), issues, depths, max_click_depth, dict(counts),
                             [url for url in all_pages if url not in pages])
    logger.info(
        "Site audit of %s: %d indexable pages (%d not indexable), %d healthy (%.0f%%) | "
        "%d errors, %d warnings, %d notices",
        crawl.start_url, len(pages), len(report.non_indexable), len(report.healthy_pages), 100 * report.health,
        report.by_severity[ERROR], report.by_severity[WARNING], report.by_severity[NOTICE],
    )
    for issue in issues:
        logger.debug("Issue [%s] %s %s: %s", issue.severity, issue.code, issue.url, issue.detail)
    return report
