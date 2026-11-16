"""
Site crawler.

Discovery is breadth-first from the start page, level by level, so every page
gets its true click depth; URLs listed only in the sitemap are crawled
afterwards (depth None). Each level is fetched concurrently but processed in
discovery order, so results are identical for any concurrency.
"""

import json
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Set, Tuple, Union
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from src.connectors.crawling.fetcher import USER_AGENT, FetchResult, HttpFetcher, RateLimiter
from src.connectors.crawling.html_extract import (
    LOCATION_CONTENT, PageLink, ParsedPage, _unique, parse_html_page,
)
from src.connectors.crawling.urls import DEFAULT_TRACKING_PARAMS, normalize_url, same_site
from src.log import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class CrawlConfig:
    """Crawler settings (config section `crawler:`; unknown keys are rejected)."""

    max_pages: int = 500                 # HTML pages to crawl at most
    max_depth: Optional[int] = None      # link-following depth from the start page (None: unlimited);
                                         # sitemap URLs are still crawled - use include/exclude/max_pages to limit scope
    concurrency: int = 4                 # parallel requests
    delay: float = 0.0                   # seconds between requests (robots.txt Crawl-delay wins if larger)
    timeout: float = 10.0                # seconds per request
    retries: int = 2                     # retries for HTTP 429/5xx and network errors
    respect_robots: bool = True
    follow_nofollow: bool = True         # also discover pages through rel=nofollow / meta nofollow links
    allow_subdomains: bool = False       # treat blog.example.com as part of example.com
    include: Tuple[str, ...] = ()        # regexes on the URL path+query; if set, only matching URLs are crawled
    exclude: Tuple[str, ...] = ()        # regexes on the URL path+query; matching URLs are skipped
    strip_query_params: Tuple[str, ...] = DEFAULT_TRACKING_PARAMS  # glob patterns removed from URLs
    check_external: bool = False         # request external link targets to find broken outbound links
    max_page_bytes: int = 5_000_000
    max_redirects: int = 10
    user_agent: str = USER_AGENT

    def __post_init__(self):
        for name in ("include", "exclude", "strip_query_params"):
            value = getattr(self, name)
            if isinstance(value, str) or not all(isinstance(v, str) for v in value):
                raise ValueError(f"crawler.{name} must be a list of strings")
            object.__setattr__(self, name, tuple(value))
        for pattern in self.include + self.exclude:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"crawler: invalid regex {pattern!r}: {exc}") from exc
        for name, minimum in (("max_pages", 1), ("concurrency", 1), ("retries", 0), ("max_redirects", 0),
                              ("max_page_bytes", 1024)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"crawler.{name} must be an integer >= {minimum}, got {value!r}")
        if self.max_depth is not None and (not isinstance(self.max_depth, int) or self.max_depth < 0):
            raise ValueError(f"crawler.max_depth must be a non-negative integer or null, got {self.max_depth!r}")
        if self.delay < 0 or self.timeout <= 0:
            raise ValueError("crawler.delay must be >= 0 and crawler.timeout > 0")

    @classmethod
    def from_config(cls, config: Optional[Mapping[str, Any]]) -> "CrawlConfig":
        section = (config or {}).get("crawler") or {}
        if not isinstance(section, Mapping):
            raise ValueError("config 'crawler' must be a mapping")
        names = [f.name for f in fields(cls)]
        unknown = sorted(set(section) - set(names))
        if unknown:
            raise ValueError(f"Unknown crawler settings {unknown}; expected some of {names}")
        return cls(**section)

    def with_overrides(self, **overrides) -> "CrawlConfig":
        return replace(self, **{k: v for k, v in overrides.items() if v is not None})


@dataclass
class CrawlResult:
    start_url: str
    pages: List[ParsedPage]                    # HTML pages answered with 200, BFS order
    sitemap_urls: List[str]                    # URLs listed in the XML sitemap(s)
    sitemap_found: bool
    statuses: Dict[str, int]                   # every internal URL requested -> final HTTP status (0 = error)
    redirects: Dict[str, str]                  # requested URL -> final URL
    robots_blocked: List[str]                  # internal URLs not fetched because of robots.txt
    truncated: bool = False                    # stopped at max_pages
    duration_seconds: float = 0.0
    redirect_chains: Dict[str, List[Tuple[str, int]]] = field(default_factory=dict)  # URL -> redirect hops
    redirect_loops: List[str] = field(default_factory=list)
    excluded: List[str] = field(default_factory=list)          # skipped by include/exclude/max_depth
    external_statuses: Dict[str, int] = field(default_factory=dict)  # only with check_external
    content_types: Dict[str, str] = field(default_factory=dict)      # URL -> content type (non-HTML too)
    requests_made: int = 0
    bytes_downloaded: int = 0
    crawl_delay: float = 0.0

    def page(self, url: str) -> Optional[ParsedPage]:
        return next((p for p in self.pages if p.url == url), None)

    @property
    def broken_urls(self) -> Dict[str, int]:
        return {url: status for url, status in self.statuses.items() if status == 0 or status >= 400}

    @property
    def broken_external_urls(self) -> Dict[str, int]:
        return {url: status for url, status in self.external_statuses.items() if status == 0 or status >= 400}

    def rebase(self, old_base: str, new_base: str) -> "CrawlResult":
        """
        Same crawl with URLs under old_base rewritten to new_base, e.g. a staging
        or local server crawled on behalf of the production host.
        """
        old_base, new_base = old_base.rstrip("/"), new_base.rstrip("/")

        def r(url: str) -> str:
            return new_base + url[len(old_base):] if url and url.startswith(old_base) else url

        pages = [
            replace(p, url=r(p.url), canonical=r(p.canonical),
                    existing_internal_links=[r(u) for u in p.existing_internal_links],
                    links=[replace(l, url=r(l.url), final_url=r(l.final_url)) for l in p.links])
            for p in self.pages
        ]
        return replace(
            self,
            start_url=r(self.start_url),
            pages=pages,
            sitemap_urls=[r(u) for u in self.sitemap_urls],
            statuses={r(u): s for u, s in self.statuses.items()},
            redirects={r(u): r(f) for u, f in self.redirects.items()},
            robots_blocked=[r(u) for u in self.robots_blocked],
            redirect_chains={r(u): [(r(h), s) for h, s in hops] for u, hops in self.redirect_chains.items()},
            redirect_loops=[r(u) for u in self.redirect_loops],
            excluded=[r(u) for u in self.excluded],
            content_types={r(u): t for u, t in self.content_types.items()},
        )

    # -------------------------------------------------------------- persistence

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CrawlResult":
        data = dict(data)
        data["pages"] = [
            ParsedPage(**{**page, "links": [PageLink(**link) for link in page.get("links", [])]})
            for page in data.get("pages", [])
        ]
        data["redirect_chains"] = {u: [tuple(h) for h in hops] for u, hops in data.get("redirect_chains", {}).items()}
        return cls(**data)

    def save(self, path: Union[str, Path]) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
        logger.info("Crawl saved to %s (%d pages)", path, len(self.pages))
        return path

    @classmethod
    def load(cls, path: Union[str, Path]) -> "CrawlResult":
        result = cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
        logger.info("Crawl loaded from %s (%d pages)", path, len(result.pages))
        return result


class SitemapCrawler:
    def __init__(
        self,
        base_url: str,
        max_pages: Optional[int] = None,
        timeout: Optional[float] = None,
        respect_robots: Optional[bool] = None,
        user_agent: Optional[str] = None,
        fetcher: Optional[Callable[[str], FetchResult]] = None,
        config: Optional[CrawlConfig] = None,
    ):
        self.config = (config or CrawlConfig()).with_overrides(
            max_pages=max_pages, timeout=timeout, respect_robots=respect_robots, user_agent=user_agent
        )
        self._normalize = lambda url: normalize_url(url, self.config.strip_query_params)
        self.base_url = self._normalize(base_url)
        parsed = urlparse(self.base_url)
        self.domain = parsed.netloc
        self.root = f"{parsed.scheme}://{parsed.netloc}"
        self.max_pages = self.config.max_pages
        self.respect_robots = self.config.respect_robots
        self.user_agent = self.config.user_agent
        self._rate_limiter = RateLimiter(self.config.delay)
        self._http = HttpFetcher(
            timeout=self.config.timeout, user_agent=self.config.user_agent, retries=self.config.retries,
            max_redirects=self.config.max_redirects, max_bytes=self.config.max_page_bytes,
            rate_limiter=self._rate_limiter, host_filter=self._is_internal,
        )
        self._fetch = fetcher or self._http.fetch
        self._include = [re.compile(p) for p in self.config.include]
        self._exclude = [re.compile(p) for p in self.config.exclude]

    @classmethod
    def get_sample_site_pages(cls) -> List[ParsedPage]:
        """Demo pages of an email marketing site (used by `audit` without --url)."""
        from src.benchmarks.demo import sample_site_pages
        return sample_site_pages()

    def parse_html(self, url: str, html_content: str, status: int = 200, x_robots_tag: str = "") -> ParsedPage:
        """Parses raw HTML into a structured ParsedPage object."""
        page = parse_html_page(url, html_content, status, x_robots_tag, normalizer=self._normalize)
        logger.debug("Parsed %s: %d paragraphs, %d links (%d internal content links)%s",
                     url, len(page.paragraphs), len(page.links), len(page.existing_internal_links),
                     f", robots '{page.meta_robots}'" if page.meta_robots else "")
        return page

    # ------------------------------------------------------------------ rules

    def _is_internal(self, url: str) -> bool:
        return same_site(url, self.domain, self.config.allow_subdomains)

    def _allowed_by_patterns(self, url: str) -> bool:
        parsed = urlparse(url)
        target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        if self._include and not any(p.search(target) for p in self._include):
            return False
        return not any(p.search(target) for p in self._exclude)

    # ------------------------------------------------------------ robots / sitemap

    def _robots(self) -> Tuple[Optional[RobotFileParser], List[str], float]:
        result = self._fetch(f"{self.root}/robots.txt")
        if result.status != 200:
            logger.info("No robots.txt (%s): every URL may be crawled", result.status or result.error)
            return None, [], 0.0
        robots = RobotFileParser()
        robots.parse(result.body.splitlines())
        sitemaps = list(robots.site_maps() or [])
        crawl_delay = float(robots.crawl_delay(self.user_agent) or 0.0)
        logger.info("robots.txt read: %d sitemap declarations, crawl delay %.1fs", len(sitemaps), crawl_delay)
        return robots, sitemaps, crawl_delay

    def _sitemap_urls(self, sitemap_url: str, seen: Set[str]) -> Tuple[List[str], bool]:
        if sitemap_url in seen:
            return [], True
        seen.add(sitemap_url)
        result = self._fetch(sitemap_url)
        if result.status != 200:
            logger.warning("Sitemap %s unavailable (status %s)", sitemap_url, result.status or result.error)
            return [], False
        data = result.raw or result.body.encode("utf-8")
        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:
            logger.warning("Sitemap %s is not valid XML: %s", sitemap_url, exc)
            return [], False
        locs = [self._normalize(el.text) for el in root.iter() if el.tag.endswith("loc") and el.text]
        if root.tag.endswith("sitemapindex"):
            urls: List[str] = []
            for child in locs:
                urls += self._sitemap_urls(child, seen)[0]
            return urls, True
        return locs, True

    # ------------------------------------------------------------------ crawl

    def crawl(self, sitemap_url: Optional[str] = None) -> CrawlResult:
        """
        Crawl the site: breadth-first from the start page (recording click
        depth), then every sitemap URL not reached by links. Internal link
        targets are all requested so broken links and redirects are known;
        external URLs are only requested with check_external.
        """
        cfg = self.config
        started = time.time()
        logger.info("Crawl started: %s (max %d pages, depth %s, concurrency %d)",
                    self.base_url, cfg.max_pages, "unlimited" if cfg.max_depth is None else cfg.max_depth,
                    cfg.concurrency)
        robots, declared, crawl_delay = self._robots() if cfg.respect_robots else (None, [], 0.0)
        if crawl_delay > self._rate_limiter.min_interval:
            self._rate_limiter.min_interval = crawl_delay
        sitemap_sources = [sitemap_url] if sitemap_url else (declared or [f"{self.root}/sitemap.xml"])
        sitemap_urls: List[str] = []
        sitemap_found = False
        seen_sitemaps: Set[str] = set()
        for source in sitemap_sources:
            urls, found = self._sitemap_urls(self._normalize(source), seen_sitemaps)
            sitemap_urls += urls
            sitemap_found = sitemap_found or found
        sitemap_urls = _unique(sitemap_urls)
        logger.info("Sitemap: %d URLs", len(sitemap_urls))

        state = _CrawlState()
        self._bfs([self.base_url], 0, robots, state)
        unreached = [u for u in sitemap_urls if self._is_internal(u) and u not in state.queued]
        if unreached and not state.truncated:
            logger.info("Crawling %d sitemap URLs not reachable by links from the start page", len(unreached))
            self._bfs(unreached, None, robots, state)

        # Resolve links through redirects so the link graph points at real pages.
        for page in state.pages.values():
            for link in page.links:
                if link.url in state.redirects:
                    link.final_url = state.redirects[link.url]
            page.existing_internal_links = _unique(
                l.target for l in page.links
                if l.internal and l.location == LOCATION_CONTENT and l.target != page.url
            )

        # URLs skipped by max_depth but fetched later through the sitemap are not "excluded".
        state.excluded = [u for u in state.excluded if u not in state.statuses]
        external_statuses = self._check_external(state.pages.values()) if cfg.check_external else {}
        result = CrawlResult(
            start_url=self.base_url,
            pages=list(state.pages.values()),
            sitemap_urls=sitemap_urls,
            sitemap_found=sitemap_found,
            statuses=state.statuses,
            redirects=state.redirects,
            robots_blocked=state.blocked,
            truncated=state.truncated,
            duration_seconds=round(time.time() - started, 2),
            redirect_chains=state.chains,
            redirect_loops=state.loops,
            excluded=state.excluded,
            external_statuses=external_statuses,
            content_types=state.content_types,
            requests_made=self._http.requests_made,
            bytes_downloaded=self._http.bytes_downloaded,
            crawl_delay=self._rate_limiter.min_interval,
        )
        logger.info(
            "Crawl finished in %.2fs: %d pages, %d internal URLs requested, %d broken, %d redirects, "
            "%d blocked by robots.txt, %d excluded, %d requests, %.0f KB",
            result.duration_seconds, len(result.pages), len(state.statuses), len(result.broken_urls),
            len(state.redirects), len(state.blocked), len(state.excluded), result.requests_made,
            result.bytes_downloaded / 1024,
        )
        return result

    def _bfs(self, seeds: List[str], depth: Optional[int], robots, state: "_CrawlState") -> None:
        cfg = self.config
        level = [u for u in seeds if state.enqueue(u)]
        while level and not state.truncated:
            allowed = []
            for url in level:
                if robots is not None and not robots.can_fetch(cfg.user_agent, url):
                    state.blocked.append(url)
                    logger.debug("Blocked by robots.txt: %s", url)
                elif not self._allowed_by_patterns(url):
                    state.excluded.append(url)
                    logger.debug("Excluded by include/exclude patterns: %s", url)
                else:
                    allowed.append(url)
            next_level: List[str] = []
            for start in range(0, len(allowed), cfg.concurrency):
                if len(state.pages) >= cfg.max_pages:
                    state.truncated = True
                    logger.warning("Crawl stopped at max_pages=%d; %d URLs left unvisited",
                                   cfg.max_pages, len(allowed) - start)
                    break
                batch = allowed[start:start + cfg.concurrency]
                with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                    results = list(pool.map(self._fetch, batch))
                for url, result in zip(batch, results):  # processed in discovery order
                    page = self._record(url, result, depth, state)
                    if page is None or (page.nofollow and not cfg.follow_nofollow):
                        continue
                    for link in page.links:
                        if not link.internal or (link.nofollow and not cfg.follow_nofollow):
                            continue
                        if depth is not None and cfg.max_depth is not None and depth + 1 > cfg.max_depth:
                            if link.url not in state.queued and link.url not in state.excluded:
                                state.excluded.append(link.url)
                            continue
                        if state.enqueue(link.url):
                            next_level.append(link.url)
            level = next_level
            depth = None if depth is None else depth + 1

    def _record(self, url: str, result: FetchResult, depth: Optional[int], state: "_CrawlState") -> Optional[ParsedPage]:
        state.statuses[url] = result.status
        if result.content_type:
            state.content_types[url] = result.content_type
        if result.redirect_chain:
            state.chains[url] = result.redirect_chain
            state.redirects[url] = result.final_url
            if result.redirect_loop:
                state.loops.append(url)
                logger.debug("Redirect loop: %s", url)
            else:
                state.statuses.setdefault(result.final_url, result.status)
                state.enqueue(result.final_url)
            logger.debug("Redirect: %s -> %s (%d hops)", url, result.final_url, len(result.redirect_chain))
        if result.status != 200:
            logger.debug("HTTP %s for %s %s", result.status, url, result.error)
            return None
        if "html" not in result.content_type or result.final_url in state.pages:
            return None
        if result.truncated:
            logger.warning("Page %s larger than %d bytes: truncated", url, self.config.max_page_bytes)
        page = self.parse_html(result.final_url, result.body, 200, result.headers.get("x-robots-tag", ""))
        page.depth, page.response_ms, page.content_bytes = depth, round(result.elapsed_ms, 1), result.bytes
        state.pages[page.url] = page
        return page

    def _check_external(self, pages) -> Dict[str, int]:
        targets = _unique(l.url for p in pages for l in p.links if not l.internal)
        if not targets:
            return {}
        logger.info("Checking %d external link targets", len(targets))
        checker = HttpFetcher(timeout=self.config.timeout, user_agent=self.config.user_agent, retries=1,
                              max_redirects=self.config.max_redirects, rate_limiter=RateLimiter(0.0))
        with ThreadPoolExecutor(max_workers=self.config.concurrency) as pool:
            statuses = list(pool.map(lambda url: checker.head(url).status, targets))
        return dict(zip(targets, statuses))


class _CrawlState:
    def __init__(self):
        self.queued: Set[str] = set()
        self.pages: Dict[str, ParsedPage] = {}
        self.statuses: Dict[str, int] = {}
        self.redirects: Dict[str, str] = {}
        self.chains: Dict[str, List[Tuple[str, int]]] = {}
        self.loops: List[str] = []
        self.blocked: List[str] = []
        self.excluded: List[str] = []
        self.content_types: Dict[str, str] = {}
        self.truncated = False

    def enqueue(self, url: str) -> bool:
        if url in self.queued:
            return False
        self.queued.add(url)
        return True
