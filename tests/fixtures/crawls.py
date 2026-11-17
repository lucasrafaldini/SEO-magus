"""
Saved crawls of the mock sites, so unit tests get a real crawl without HTTP.

The JSON files next to this module are written by `make fixtures` (this module's
main): each mock site is served on localhost, crawled with the real crawler,
rebased to https://greenleaf.example and saved with its volatile counters
(timings, compressed sizes: gzip output depends on the random server port)
zeroed, so the files are byte-for-byte reproducible.

tests/test_fixtures.py (integration tier) re-crawls the sites and fails when a
saved crawl is stale, e.g. after a mock site or crawler change.

    python -m tests.fixtures.crawls            # same as `make fixtures`
"""

import sys
import warnings
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Dict

from src.benchmarks import BenchmarkSite, get_benchmark, mock_sites, run_benchmark
from src.connectors.sitemap_crawler import CrawlResult

FIXTURES_DIR = Path(__file__).resolve().parent
SITES = tuple(mock_sites.available_sites())   # every directory in mock_sites/ gets a saved crawl


def crawl_path(site: str) -> Path:
    return FIXTURES_DIR / f"{site}.crawl.json"


def normalized(crawl: CrawlResult) -> CrawlResult:
    """The crawl without the values that change from run to run."""
    pages = [replace(page, response_ms=0.0, content_bytes=0) for page in crawl.pages]
    return replace(crawl, pages=pages, duration_seconds=0.0, bytes_downloaded=0)


@lru_cache(maxsize=None)
def _load(site: str) -> CrawlResult:
    path = crawl_path(site)
    if not path.is_file():
        raise FileNotFoundError(f"{path} is missing: run `make fixtures`")
    return CrawlResult.load(path)


def load_crawl(site: str) -> CrawlResult:
    """The saved crawl of a mock site (a fresh copy: tests may modify it)."""
    return CrawlResult.from_dict(_load(site).to_dict())


def offline_benchmark(site: str) -> BenchmarkSite:
    """A crawled benchmark site (greenleaf-good / -scrambled) that uses its saved crawl instead of HTTP."""
    return replace(get_benchmark(site), build_crawl=lambda: mock_sites.MockCrawl(load_crawl(site), [], []))


def offline_analysis(site: str = mock_sites.SCRAMBLED_SITE):
    """Full SiteAnalysis (site audit, link proposals, ranking, verdict) of a mock site, without HTTP."""
    from src.reporting import analyze_benchmark  # reporting imports are heavier; only load when needed
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return analyze_benchmark(run_benchmark(offline_benchmark(site)))


def write_fixtures() -> Dict[str, Path]:
    """Crawl every mock site over HTTP and save the normalized crawls."""
    return {site: normalized(mock_sites.crawl_mock_site(site).result).save(crawl_path(site)) for site in SITES}


def main() -> int:
    for site, path in write_fixtures().items():
        print(f"{site}: saved crawl -> {path.relative_to(FIXTURES_DIR.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
