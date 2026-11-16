"""
Sitemap and Content Crawler (public entry point).

The implementation lives in src/connectors/crawling/:
  urls.py          URL normalization (tracking parameters, ports, fragments)
  html_extract.py  HTML -> ParsedPage (title, meta, robots, canonical, h1s, paragraphs, links)
  fetcher.py       HTTP: redirects hop by hop, retries/backoff, rate limiting, gzip, charsets
  crawler.py       CrawlConfig, SitemapCrawler (robots.txt, sitemaps, BFS), CrawlResult (save/load)

Standard library only, so crawling works with zero dependencies.
"""

from src.connectors.crawling.crawler import CrawlConfig, CrawlResult, SitemapCrawler
from src.connectors.crawling.fetcher import USER_AGENT, FetchResult, HttpFetcher, RateLimiter
from src.connectors.crawling.html_extract import (
    LOCATION_CONTENT,
    LOCATION_NAVIGATION,
    MIN_PARAGRAPH_CHARS,
    HtmlPageExtractor,
    PageLink,
    ParsedPage,
    parse_html_page,
)
from src.connectors.crawling.urls import DEFAULT_TRACKING_PARAMS, normalize_url, same_site


def fetch_url(url: str, timeout: float = 10.0, user_agent: str = USER_AGENT) -> FetchResult:
    """GET a URL (redirects followed and recorded, retries on transient errors); never raises."""
    return HttpFetcher(timeout=timeout, user_agent=user_agent).fetch(url)


__all__ = [
    "CrawlConfig", "CrawlResult", "DEFAULT_TRACKING_PARAMS", "FetchResult", "HtmlPageExtractor", "HttpFetcher",
    "LOCATION_CONTENT", "LOCATION_NAVIGATION", "MIN_PARAGRAPH_CHARS", "PageLink", "ParsedPage", "RateLimiter",
    "SitemapCrawler", "USER_AGENT", "fetch_url", "normalize_url", "parse_html_page", "same_site",
]
