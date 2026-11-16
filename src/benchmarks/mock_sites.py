"""
Mock websites for offline end-to-end checks of the whole scan.

mock_sites/ holds two static versions of the same fictional site (GreenLeaf
Gardening, production host https://greenleaf.example):

  greenleaf-good       effective SEO: descriptive contextual links, hub-and-spoke
                       pillars, unique titles, one <h1>, meta descriptions, complete sitemap
  greenleaf-scrambled  the same articles with broken SEO: orphan page, buried
                       pillar, "click here" anchors, broken and redirecting links,
                       stale sitemap (404 entry, redirecting entry, noindex page),
                       2-hop redirect chain, canonicalized print duplicate, nofollow
                       and utm-tagged internal links, missing/duplicate titles and
                       <h1>s, plus parser traps (upper-case tags, unclosed <p>, <h1>
                       in <header>, fragments, external links, robots.txt-blocked pages)

MockSiteServer serves a site over real HTTP on localhost (301 for directory URLs
without a trailing slash, redirects declared in a Netlify-style `_redirects` file,
404 for missing files, gzip when accepted) and rewrites the production
host in every served file to its own address, like a staging server. The real
crawler then scans it; CrawlResult.rebase() maps URLs back to the production host.

Browse a site yourself:  python -m src.benchmarks.mock_sites greenleaf-good --port 8000
"""

import argparse
import gzip
import mimetypes
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple
from urllib.parse import unquote, urlparse

from src.connectors.sitemap_crawler import CrawlConfig, CrawlResult, SitemapCrawler
from src.log import get_logger

logger = get_logger(__name__)

MOCK_SITES_DIR = Path(__file__).resolve().parents[2] / "mock_sites"
PRODUCTION_BASE = "https://greenleaf.example"
GOOD_SITE = "greenleaf-good"
SCRAMBLED_SITE = "greenleaf-scrambled"
_TEXT_TYPES = ("text/", "application/xml", "application/javascript")


class _Handler(BaseHTTPRequestHandler):
    server: "_Server"

    def log_message(self, format, *args):  # noqa: A002 - silence default stderr logging
        logger.debug("mock %s: " + format, self.server.site, *args)

    def _send(self, status: int, body: bytes, content_type: str = "text/html; charset=utf-8", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_body(self, status: int, body: bytes, content_type: str):
        """Send with gzip when the client accepts it (as real servers do)."""
        headers = {}
        if "gzip" in self.headers.get("Accept-Encoding", "") and len(body) > 0:
            body = gzip.compress(body)
            headers["Content-Encoding"] = "gzip"
        self.server.encodings.append(headers.get("Content-Encoding", "identity"))
        self._send(status, body, content_type, headers)

    def do_GET(self):  # noqa: N802
        self.server.requests.append(self.path)
        path = unquote(urlparse(self.path).path)
        root = self.server.root
        redirect = self.server.redirect_rules.get(path)
        if redirect:
            location, status = redirect
            return self._send(status, b"", headers={"Location": location})
        target = (root / path.lstrip("/")).resolve()
        if root not in target.parents and target != root:
            return self._send(404, b"<h1>Not found</h1>")
        if target.is_dir():
            if not path.endswith("/"):
                return self._send(301, b"", headers={"Location": path + "/"})
            target = target / "index.html"
        if not target.is_file() or target.name == "_redirects":
            return self._send(404, b"<html><head><title>Not found</title></head><body><h1>404</h1></body></html>")
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith(_TEXT_TYPES):
            body = body.replace(PRODUCTION_BASE.encode(), self.server.base_url.encode())
            content_type += "; charset=utf-8"
        self._send_body(200, body, content_type)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, site: str, port: int):
        self.site = site
        self.root = (MOCK_SITES_DIR / site).resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(f"Unknown mock site {site!r}; available: {available_sites()}")
        self.requests: List[str] = []
        self.encodings: List[str] = []
        # Netlify-style `_redirects` file: "<from path> <to path> [status]" per line.
        self.redirect_rules = {}
        rules = self.root / "_redirects"
        if rules.is_file():
            for line in rules.read_text(encoding="utf-8").splitlines():
                parts = line.split("#", 1)[0].split()
                if len(parts) >= 2:
                    self.redirect_rules[parts[0]] = (parts[1], int(parts[2]) if len(parts) > 2 else 301)
        super().__init__(("127.0.0.1", port), _Handler)
        self.base_url = f"http://127.0.0.1:{self.server_address[1]}"


class MockSiteServer:
    """Serve a mock site on localhost for the duration of a `with` block."""

    def __init__(self, site: str, port: int = 0):
        self._server = _Server(site, port)
        # Short poll interval: shutdown() returns quickly (default is 0.5 s per server).
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)

    @property
    def base_url(self) -> str:
        return self._server.base_url

    @property
    def requests(self) -> List[str]:
        """Paths requested so far (e.g. to prove robots.txt was respected)."""
        return list(self._server.requests)

    @property
    def encodings(self) -> List[str]:
        """Content-Encoding of each 200 response ("gzip" when the client accepted it)."""
        return list(self._server.encodings)

    def __enter__(self) -> "MockSiteServer":
        self._thread.start()
        logger.info("Mock site %s served at %s", self._server.site, self.base_url)
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@dataclass
class MockCrawl:
    result: CrawlResult        # URLs rebased to PRODUCTION_BASE
    requests: List[str]        # paths the crawler requested from the server
    encodings: List[str]       # Content-Encoding of each 200 response


# ---------------------------------------------------------------------------
# Ground truth, written from the site design (paths relative to PRODUCTION_BASE)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpectedPage:
    title: str
    h1: str
    h1_count: int
    has_meta_description: bool
    paragraphs: int
    content_links: FrozenSet[str]          # internal links in the body (after redirects)
    navigation_links: FrozenSet[str]       # internal links in header / nav / footer (after redirects)


def _fs(*paths: str) -> FrozenSet[str]:
    return frozenset(paths)


HOME, ABOUT = "/", "/about/"
COMPOSTING, HOT, TROUBLE, TUMBLER = "/guides/composting/", "/blog/hot-composting/", "/blog/compost-bin-troubleshooting/", "/shop/compost-tumbler/"
VEGETABLES, SOIL, TOMATO, KIT = "/guides/vegetable-gardening/", "/blog/raised-bed-soil/", "/blog/tomato-watering-schedule/", "/shop/raised-bed-kit/"
OLD_NEWS, PRINT = "/blog/old-news/", "/blog/hot-composting/print/"   # scrambled site only, not indexable
PAGES = (HOME, COMPOSTING, HOT, TROUBLE, TUMBLER, VEGETABLES, SOIL, TOMATO, KIT, ABOUT)

# Contextual links of the good site (source -> target), each with a descriptive anchor.
GOOD_LINKS: FrozenSet[Tuple[str, str]] = frozenset({
    (HOME, COMPOSTING), (HOME, VEGETABLES), (HOME, ABOUT),
    (COMPOSTING, HOT), (COMPOSTING, TROUBLE), (COMPOSTING, TUMBLER), (COMPOSTING, SOIL),
    (HOT, COMPOSTING), (HOT, TUMBLER),
    (TROUBLE, HOT), (TROUBLE, COMPOSTING),
    (TUMBLER, COMPOSTING),
    (VEGETABLES, SOIL), (VEGETABLES, TOMATO), (VEGETABLES, KIT), (VEGETABLES, COMPOSTING),
    (SOIL, HOT), (SOIL, VEGETABLES),
    (TOMATO, SOIL), (TOMATO, VEGETABLES),
    (KIT, VEGETABLES),
    (ABOUT, TOMATO),
})
# Contextual links the scrambled site kept (same articles, most links removed).
SCRAMBLED_LINKS: FrozenSet[Tuple[str, str]] = frozenset({
    (COMPOSTING, TROUBLE),                 # as "click here"
    (HOT, COMPOSTING),
    (VEGETABLES, KIT),
    (SOIL, VEGETABLES),
    (TOMATO, SOIL),
    (ABOUT, TOMATO),
})
# The scrambled site's text still mentions every target, so SEO-Magus should
# propose exactly the good site's links that are missing: it rebuilds the good site.
SCRAMBLED_EXPECTED_PROPOSALS: FrozenSet[Tuple[str, str]] = GOOD_LINKS - SCRAMBLED_LINKS

_GOOD_NAV = _fs(HOME, COMPOSTING, VEGETABLES, ABOUT)
EXPECTED_SCAN: Dict[str, Dict[str, ExpectedPage]] = {
    GOOD_SITE: {
        HOME: ExpectedPage("GreenLeaf Gardening | Composting and Vegetable Growing Guides",
                           "Grow Better Soil and Better Vegetables", 1, True, 2, _fs(COMPOSTING, VEGETABLES, ABOUT),
                           _fs(COMPOSTING, VEGETABLES, ABOUT)),
        COMPOSTING: ExpectedPage("Complete Composting Guide", "Complete Composting Guide", 1, True, 5,
                                 _fs(HOT, TROUBLE, TUMBLER, SOIL), _fs(HOME, VEGETABLES, ABOUT)),
        HOT: ExpectedPage("Hot Composting Method", "Hot Composting Method", 1, True, 3, _fs(COMPOSTING, TUMBLER), _GOOD_NAV),
        TROUBLE: ExpectedPage("Compost Bin Troubleshooting", "Compost Bin Troubleshooting", 1, True, 3,
                              _fs(HOT, COMPOSTING), _GOOD_NAV),
        TUMBLER: ExpectedPage("Dual-Chamber Compost Tumbler", "Dual-Chamber Compost Tumbler", 1, True, 2,
                              _fs(COMPOSTING), _GOOD_NAV),
        VEGETABLES: ExpectedPage("Vegetable Gardening Guide", "Vegetable Gardening Guide for Beginners", 1, True, 5,
                                 _fs(SOIL, TOMATO, KIT, COMPOSTING), _fs(HOME, COMPOSTING, ABOUT)),
        SOIL: ExpectedPage("Raised Bed Soil Mix", "The Best Raised Bed Soil Mix", 1, True, 3, _fs(HOT, VEGETABLES), _GOOD_NAV),
        TOMATO: ExpectedPage("Tomato Watering Schedule", "Tomato Watering Schedule", 1, True, 3,
                             _fs(SOIL, VEGETABLES), _GOOD_NAV),
        KIT: ExpectedPage("Cedar Raised Bed Kit", "Cedar Raised Bed Kit", 1, True, 2, _fs(VEGETABLES), _GOOD_NAV),
        ABOUT: ExpectedPage("About GreenLeaf", "About the GreenLeaf Gardeners", 1, True, 2, _fs(TOMATO), _fs(HOME, COMPOSTING, VEGETABLES)),
    },
    SCRAMBLED_SITE: {
        HOME: ExpectedPage("GreenLeaf Gardening", "Grow Better Soil and Better Vegetables", 1, False, 3, _fs(),
                           _fs(ABOUT, TUMBLER, "/private/drafts/")),
        COMPOSTING: ExpectedPage("Complete Composting Guide", "Complete Composting Guide", 1, True, 5, _fs(TROUBLE),
                                 _fs(HOME, ABOUT, TUMBLER, "/private/drafts/")),
        HOT: ExpectedPage("Hot Composting Method", "Hot Composting Method", 1, True, 4, _fs(COMPOSTING, PRINT),
                          _fs(HOME, ABOUT, TUMBLER, "/private/drafts/")),
        PRINT: ExpectedPage("Hot Composting Method", "Hot Composting Method", 1, True, 3, _fs(COMPOSTING), _fs()),
        OLD_NEWS: ExpectedPage("Spring Fair 2019 Recap", "Spring Fair 2019 Recap", 1, True, 1, _fs(),
                               _fs(HOME, ABOUT, TUMBLER, "/private/drafts/")),
        TROUBLE: ExpectedPage("Compost Bin Troubleshooting", "Compost Bin Troubleshooting", 2, True, 3, _fs(),
                              _fs(HOME, ABOUT, TUMBLER, "/private/drafts/")),
        TUMBLER: ExpectedPage("Dual-Chamber Compost Tumbler", "Dual-Chamber Compost Tumbler", 1, True, 2, _fs(),
                              _fs(HOME, ABOUT, "/private/drafts/")),
        VEGETABLES: ExpectedPage("Vegetable Gardening Guide", "Vegetable Gardening Guide for Beginners", 1, True, 5,
                                 _fs(KIT), _fs(HOME, ABOUT, TUMBLER, "/private/drafts/")),
        SOIL: ExpectedPage("Raised Bed Soil Mix", "The Best Raised Bed Soil Mix", 1, True, 4,
                           _fs(VEGETABLES, "/blog/soil-ph-testing/"), _fs(HOME, ABOUT, TUMBLER, "/private/drafts/")),
        TOMATO: ExpectedPage("", "Tomato Watering Schedule", 1, False, 3, _fs(SOIL),
                             _fs(HOME, ABOUT, TUMBLER, "/private/drafts/")),
        KIT: ExpectedPage("Cedar Raised Bed Kit", "", 0, False, 2, _fs(), _fs(HOME, ABOUT, TUMBLER, "/private/drafts/")),
        ABOUT: ExpectedPage("GreenLeaf Gardening", "About the GreenLeaf Gardeners", 1, False, 2, _fs(TOMATO),
                            _fs(HOME, TUMBLER, "/private/drafts/")),
    },
}

# (issue code, path) the site audit must report - nothing more, nothing less.
EXPECTED_ISSUES: Dict[str, FrozenSet[Tuple[str, str]]] = {
    GOOD_SITE: frozenset(),
    SCRAMBLED_SITE: frozenset({
        ("orphan_page", HOT),
        ("broken_internal_link", "/blog/soil-ph-testing/"),
        ("sitemap_url_broken", "/shop/old-compost-kit/"),
        ("missing_title", TOMATO),
        ("duplicate_title", HOME), ("duplicate_title", ABOUT),
        ("missing_h1", KIT),
        ("multiple_h1", TROUBLE),
        ("generic_anchor", COMPOSTING),
        ("redirected_internal_link", "/shop/compost-tumbler"),
        ("deep_page", VEGETABLES), ("deep_page", KIT),
        ("unreachable_page", COMPOSTING), ("unreachable_page", TROUBLE),
        ("not_in_sitemap", KIT),
        ("no_contextual_inbound", TUMBLER), ("no_contextual_inbound", ABOUT),
        ("missing_meta_description", HOME), ("missing_meta_description", ABOUT),
        ("missing_meta_description", TOMATO), ("missing_meta_description", KIT),
        # crawler signals: redirects, canonicals, noindex, nofollow
        ("redirect_chain", "/guides/compost/"),
        ("sitemap_url_redirect", "/guides/compost/"),
        ("noindex_in_sitemap", OLD_NEWS),
        ("canonicalized_page", PRINT),
        ("nofollow_internal_link", TOMATO),
    }),
}
# Paths the crawler must never request (robots.txt) - external URLs are checked separately.
FORBIDDEN_REQUESTS = ("/private/",)


def absolute(path: str) -> str:
    return PRODUCTION_BASE + path


def available_sites() -> List[str]:
    return sorted(p.name for p in MOCK_SITES_DIR.iterdir() if p.is_dir()) if MOCK_SITES_DIR.is_dir() else []


def crawl_mock_site(site: str, max_pages: int = 100, config: Optional[CrawlConfig] = None) -> MockCrawl:
    """Serve a mock site, crawl it with the real crawler over HTTP, and rebase its URLs."""
    config = (config or CrawlConfig(timeout=5)).with_overrides(max_pages=max_pages)
    with MockSiteServer(site) as server:
        result = SitemapCrawler(server.base_url + "/", config=config).crawl()
        requests, encodings = server.requests, server.encodings
    return MockCrawl(result.rebase(server.base_url, PRODUCTION_BASE), requests, encodings)


def main():
    parser = argparse.ArgumentParser(description="Serve a SEO-Magus mock site on localhost")
    parser.add_argument("site", choices=available_sites())
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    with MockSiteServer(args.site, args.port) as server:
        print(f"Serving {args.site} at {server.base_url}/ (Ctrl+C to stop)")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
