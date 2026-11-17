"""
Crawler: HTML extraction and real HTTP crawls of the mock sites (mock_sites/).
"""

import gzip
import http.client
import io
import tempfile
import threading
import time
import unittest
import zlib
from contextlib import redirect_stdout
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import pytest

from src import cli
from src.benchmarks import mock_sites
from src.benchmarks.mock_sites import EXPECTED_SCAN, PRODUCTION_BASE, MockSiteServer, crawl_mock_site
from src.connectors.crawling.fetcher import FetchResult, HttpFetcher, RateLimiter, _decode_body
from src.connectors.sitemap_crawler import (
    LOCATION_CONTENT, LOCATION_NAVIGATION, CrawlConfig, CrawlResult, SitemapCrawler, normalize_url, parse_html_page,
    same_site,
)
from src.workflows.site_audit import audit_site

QUIRKY_HTML = """<html><head><TITLE>Hello &amp; World</TITLE>
<meta name=Description content=" A  description ">
<link rel='canonical' href='/a/'></head>
<body><header><h1>Top <b>title</b></h1><nav><a href='/'>Home</a></nav></header>
<P>Read the <a href="/guides/composting/#step-2">complete composting guide</a> first, it is long enough.
<p>Second paragraph without a closing tag, but long enough to count
<div>short</div>
<a href='mailto:x@y.z'>mail</a><a href='#top'>top</a><a href='https://other.example/x'>external</a>
<a href="/shop/"><img src="k.png" alt="Compost kit"></a>
<script>var html = '<p>not a paragraph at all, inside a script</p>';</script>
<footer><a href='/about/'>About us</a></footer></body></html>"""


class TestExtractor(unittest.TestCase):
    def setUp(self):
        self.page = parse_html_page("https://site.example/a/", QUIRKY_HTML)

    def test_head_fields(self):
        self.assertEqual(self.page.title, "Hello & World")
        self.assertEqual(self.page.meta_description, "A description")
        self.assertEqual(self.page.canonical, "https://site.example/a/")

    def test_h1_inside_header_is_counted(self):
        self.assertEqual((self.page.h1, self.page.h1_count), ("Top title", 1))

    def test_paragraphs_keep_spacing_and_skip_scripts(self):
        self.assertEqual(self.page.paragraphs, [
            "Read the complete composting guide first, it is long enough.",
            "Second paragraph without a closing tag, but long enough to count",
        ])

    def test_links_locations_anchors_and_normalization(self):
        links = [(l.url, l.anchor_text, l.location, l.internal) for l in self.page.links]
        self.assertEqual(links, [
            ("https://site.example/", "Home", LOCATION_NAVIGATION, True),
            ("https://site.example/guides/composting/", "complete composting guide", LOCATION_CONTENT, True),
            ("https://other.example/x", "external", LOCATION_CONTENT, False),
            ("https://site.example/shop/", "Compost kit", LOCATION_CONTENT, True),
            ("https://site.example/about/", "About us", LOCATION_NAVIGATION, True),
        ])  # mailto:, #top (self) dropped; fragment stripped; image alt used as anchor
        self.assertEqual(self.page.existing_internal_links,
                         ["https://site.example/guides/composting/", "https://site.example/shop/"])
        self.assertEqual(self.page.navigation_links, ["https://site.example/", "https://site.example/about/"])
        self.assertEqual(self.page.content_anchor_texts, ["complete composting guide", "external", "Compost kit"])

    def test_normalize_url(self):
        self.assertEqual(normalize_url(" HTTPS://Site.Example/a/#x "), "https://site.example/a/")
        self.assertEqual(normalize_url("https://user:pw@Site.Example:443/a"), "https://user:pw@site.example/a")


class TestExtractorEdgeCases(unittest.TestCase):
    """HTML quirks found on real sites."""

    def test_lang_and_base_href(self):
        page = parse_html_page("https://site.example/x/", "<html lang=' PT-BR '><head><base href='/blog/'></head>"
                                                          "<p><a href='post/'>a relative post link</a></p></html>")
        self.assertEqual(page.lang, "pt-br")
        self.assertEqual(page.existing_internal_links, ["https://site.example/blog/post/"])

    def test_robots_meta_googlebot_header_and_none(self):
        page = parse_html_page("https://site.example/", "<meta name='googlebot' content='NOINDEX'>", x_robots_tag="nofollow")
        self.assertEqual(page.meta_robots, "noindex, nofollow")
        self.assertTrue(page.noindex and page.nofollow)
        self.assertFalse(page.indexable)
        none = parse_html_page("https://site.example/", "<meta name='robots' content='none'>")
        self.assertTrue(none.noindex and none.nofollow)

    def test_line_breaks_and_sponsored_links(self):
        page = parse_html_page("https://site.example/", "<p>Line one<br>line two, <a href='/ad/' rel='Sponsored'>"
                                                        "a sponsored link</a> here.</p>")
        self.assertEqual(page.paragraphs, ["Line one line two, a sponsored link here."])
        self.assertTrue(page.links[0].nofollow)

    def test_self_closing_and_stray_boilerplate_tags_do_not_swallow_content(self):
        page = parse_html_page("https://site.example/", "</script><nav/><aside/>"
                                                        "<p><a href='/x/'>a content link in the text</a></p>")
        self.assertEqual([(l.location, l.anchor_text) for l in page.links], [(LOCATION_CONTENT, "a content link in the text")])

    def test_skipped_regions_nest_and_hide_their_markup(self):
        page = parse_html_page("https://site.example/", "<noscript><p>Hidden paragraph text in noscript.</p></noscript>"
                                                        "<template><svg><p>inside</p></template>"
                                                        "<p>Visible paragraph after the template.</p>")
        self.assertEqual(page.paragraphs, ["Visible paragraph after the template."])


class TestFetcherDecoding(unittest.TestCase):
    def test_deflate_raw_deflate_and_gzip_by_magic_bytes(self):
        raw = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        raw_deflate = raw.compress(b"hello") + raw.flush()
        self.assertEqual(_decode_body(zlib.compress(b"hello"), "deflate", ""), b"hello")
        self.assertEqual(_decode_body(raw_deflate, "deflate", ""), b"hello")
        self.assertEqual(_decode_body(gzip.compress(b"hello"), "", "application/gzip"), b"hello")
        self.assertEqual(_decode_body(b"plain", "identity", "text/html"), b"plain")

    def test_connection_dropped_mid_body_is_a_network_error(self):
        headers = Message()
        headers["Content-Type"] = "text/html"
        response = mock.MagicMock(status=200, headers=headers)
        response.__enter__.return_value = response
        response.read.side_effect = ConnectionResetError("peer reset")
        fetcher = HttpFetcher(retries=0)
        with mock.patch.object(fetcher._opener, "open", return_value=response):
            result = fetcher.fetch("https://x.example/")
        self.assertEqual((result.status, result.error, result.body), (0, "read failed: peer reset", ""))

    def test_fetcher_is_callable(self):
        fetcher = HttpFetcher()
        with mock.patch.object(fetcher, "fetch", return_value="result") as fetch:
            self.assertEqual(fetcher("https://x.example/"), "result")
        fetch.assert_called_once_with("https://x.example/")

    def test_fetch_url_helper_passes_its_settings(self):
        from src.connectors import sitemap_crawler
        with mock.patch.object(sitemap_crawler, "HttpFetcher") as fetcher_cls:
            sitemap_crawler.fetch_url("https://x.example/", timeout=3, user_agent="bot")
        fetcher_cls.assert_called_once_with(timeout=3, user_agent="bot")
        fetcher_cls.return_value.fetch.assert_called_once_with("https://x.example/")


class FakeFetcher:
    """In-memory stand-in for HttpFetcher.fetch: path -> (status, content type, body)."""

    def __init__(self, base: str, routes):
        self.base, self.routes, self.requests = base, routes, []

    def __call__(self, url: str):
        self.requests.append(url)
        status, content_type, body = self.routes.get(url[len(self.base):], (404, "text/html", ""))
        return FetchResult(url, url, status, content_type, body, raw=body.encode())


class TestCrawlerWithFakeFetcher(unittest.TestCase):
    """Crawl logic without HTTP (the crawler accepts any fetcher)."""

    BASE = "https://site.example"
    HOME = (200, "text/html", "<title>Home</title><p><a href='/a/'>the a page</a></p>")

    def crawl(self, routes, **config):
        fetcher = FakeFetcher(self.BASE, routes)
        result = SitemapCrawler(self.BASE + "/", fetcher=fetcher, config=CrawlConfig(**config)).crawl()
        return result, fetcher

    def test_invalid_sitemap_xml_is_a_warning_not_a_crash(self):
        routes = {"/": self.HOME, "/a/": (200, "text/html", "<title>A</title>"),
                  "/sitemap.xml": (200, "application/xml", "<urlset><url><loc>broken")}
        with self.assertLogs("seo_magus.connectors.crawling.crawler", "WARNING") as logs:
            result, _ = self.crawl(routes)
        self.assertIn("is not valid XML", logs.output[0])
        self.assertEqual((result.sitemap_found, result.sitemap_urls), (False, []))
        self.assertEqual([p.url for p in result.pages], [self.BASE + "/", self.BASE + "/a/"])

    def test_sitemap_index_cycles_are_read_once(self):
        index = ("<sitemapindex><sitemap><loc>https://site.example/sitemap.xml</loc></sitemap>"
                 "<sitemap><loc>https://site.example/pages.xml</loc></sitemap></sitemapindex>")
        routes = {"/": self.HOME, "/a/": (200, "text/html", "<title>A</title>"),
                  "/sitemap.xml": (200, "application/xml", index),
                  "/pages.xml": (200, "application/xml", "<urlset><url><loc>https://site.example/a/</loc></url></urlset>")}
        result, fetcher = self.crawl(routes)
        self.assertTrue(result.sitemap_found)
        self.assertEqual(result.sitemap_urls, [self.BASE + "/a/"])
        self.assertEqual(fetcher.requests.count(self.BASE + "/sitemap.xml"), 1)

    def test_external_check_without_external_links_requests_nothing(self):
        result, fetcher = self.crawl({"/": self.HOME, "/a/": (200, "text/html", "<title>A</title>")},
                                     check_external=True)
        self.assertEqual(result.external_statuses, {})
        self.assertTrue(all(url.startswith(self.BASE) for url in fetcher.requests))


@pytest.mark.integration
class TestMockSiteScan(unittest.TestCase):
    """The crawler must see exactly what the mock sites contain."""

    @classmethod
    def setUpClass(cls):
        cls.crawls = {site: crawl_mock_site(site) for site in EXPECTED_SCAN}

    def test_every_page_matches_the_ground_truth(self):
        for site, expected_pages in EXPECTED_SCAN.items():
            result = self.crawls[site].result
            self.assertEqual({p.url for p in result.pages}, {PRODUCTION_BASE + path for path in expected_pages})
            for path, expected in expected_pages.items():
                page = result.page(PRODUCTION_BASE + path)
                with self.subTest(site=site, page=path):
                    self.assertEqual(page.title, expected.title)
                    self.assertEqual(page.h1, expected.h1)
                    self.assertEqual(page.h1_count, expected.h1_count)
                    self.assertEqual(bool(page.meta_description), expected.has_meta_description)
                    self.assertEqual(len(page.paragraphs), expected.paragraphs)
                    strip = lambda urls: frozenset(u[len(PRODUCTION_BASE):] for u in urls)
                    self.assertEqual(strip(page.existing_internal_links), expected.content_links)
                    self.assertEqual(strip(page.navigation_links), expected.navigation_links)

    def test_robots_txt_and_external_links_are_respected(self):
        for site, crawl in self.crawls.items():
            with self.subTest(site=site):
                self.assertFalse([r for r in crawl.requests if r.startswith(mock_sites.FORBIDDEN_REQUESTS)])
                self.assertTrue(all(r.startswith("/") for r in crawl.requests))  # only the mock host was contacted
        scrambled = self.crawls[mock_sites.SCRAMBLED_SITE].result
        self.assertEqual(scrambled.robots_blocked, [PRODUCTION_BASE + "/private/drafts/"])

    def test_statuses_redirects_and_sitemap(self):
        good = self.crawls[mock_sites.GOOD_SITE].result
        self.assertEqual((good.broken_urls, good.redirects), ({}, {}))
        self.assertEqual(len(good.sitemap_urls), 10)
        scrambled = self.crawls[mock_sites.SCRAMBLED_SITE].result
        self.assertEqual(scrambled.broken_urls, {
            PRODUCTION_BASE + "/shop/old-compost-kit/": 404, PRODUCTION_BASE + "/blog/soil-ph-testing/": 404,
        })
        self.assertEqual(scrambled.redirects, {
            PRODUCTION_BASE + "/shop/compost-tumbler": PRODUCTION_BASE + "/shop/compost-tumbler/",
            PRODUCTION_BASE + "/guides/compost/": PRODUCTION_BASE + "/guides/composting/",
        })
        self.assertEqual(scrambled.redirect_chains[PRODUCTION_BASE + "/guides/compost/"], [
            (PRODUCTION_BASE + "/guides/compost/", 301), (PRODUCTION_BASE + "/guides/composting", 301),
        ])
        # Links through the redirect point at the real page in the link graph.
        home = scrambled.page(PRODUCTION_BASE + "/")
        self.assertIn(PRODUCTION_BASE + "/shop/compost-tumbler/", home.navigation_links)
        self.assertNotIn(PRODUCTION_BASE + "/shop/raised-bed-kit/", scrambled.sitemap_urls)

    def test_served_files_use_the_production_host(self):
        # Sitemap and canonicals are written with the production host; the server
        # rewrites them and rebase() maps everything back.
        good = self.crawls[mock_sites.GOOD_SITE].result
        self.assertTrue(all(u.startswith(PRODUCTION_BASE) for u in good.sitemap_urls))
        self.assertEqual(good.page(PRODUCTION_BASE + "/about/").canonical, PRODUCTION_BASE + "/about/")


@pytest.mark.integration
class TestCrawlerBehaviour(unittest.TestCase):
    def _site(self, files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name, "tmp-site")
        for path, content in files.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        patcher = mock.patch.object(mock_sites, "MOCK_SITES_DIR", Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        return "tmp-site"

    def test_max_pages_truncates(self):
        pages = {f"p{i}/index.html": f"<p>Page number {i} with enough text to count.</p><a href='/p{i + 1}/'>next</a>"
                 for i in range(6)}
        pages["index.html"] = "<a href='/p0/'>start</a>"
        site = self._site(pages)
        with MockSiteServer(site) as server:
            result = SitemapCrawler(server.base_url + "/", max_pages=3).crawl()
        self.assertEqual(len(result.pages), 3)
        self.assertTrue(result.truncated)

    def test_without_robots_or_sitemap_links_are_followed(self):
        site = self._site({"index.html": "<a href='/a/'>a</a>", "a/index.html": "<a href='/'>home</a>"})
        with MockSiteServer(site) as server:
            result = SitemapCrawler(server.base_url + "/").crawl()
        self.assertEqual(len(result.pages), 2)
        self.assertFalse(result.sitemap_found)

    def test_sitemap_index_is_followed(self):
        site = self._site({
            "index.html": "<p>home</p>",
            "robots.txt": "User-agent: *\nDisallow:\nSitemap: https://greenleaf.example/sitemap-index.xml\n",
            "sitemap-index.xml": '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                 "<sitemap><loc>https://greenleaf.example/pages.xml</loc></sitemap></sitemapindex>",
            "pages.xml": '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                         "<url><loc>https://greenleaf.example/hidden/</loc></url></urlset>",
            "hidden/index.html": "<p>Only reachable through the nested sitemap.</p>",
        })
        with MockSiteServer(site) as server:
            result = SitemapCrawler(server.base_url + "/").crawl().rebase(server.base_url, PRODUCTION_BASE)
        self.assertEqual(result.sitemap_urls, [PRODUCTION_BASE + "/hidden/"])
        self.assertIsNotNone(result.page(PRODUCTION_BASE + "/hidden/"))

    def test_unreachable_host_does_not_raise(self):
        result = SitemapCrawler("http://127.0.0.1:9/", config=CrawlConfig(timeout=1, retries=0)).crawl()
        self.assertEqual(result.pages, [])
        self.assertEqual(result.statuses, {"http://127.0.0.1:9/": 0})

    def test_mock_server_rewrites_text_only_and_never_leaves_its_root(self):
        site = self._site({
            "index.html": "<p>Home of https://greenleaf.example/</p>",
            "logo.png": "PNG https://greenleaf.example/",
            "_redirects": "/old /index.html 302\n# comment line\n",
        })
        with MockSiteServer(site) as server:
            connection = http.client.HTTPConnection(server.base_url[len("http://"):], timeout=5)

            def get(path):
                connection.request("GET", path)   # no Accept-Encoding: the server must answer uncompressed
                response = connection.getresponse()
                return response.status, response.getheader("Content-Type"), response.getheader("Location"), response.read()

            home, logo = get("/"), get("/logo.png")
            traversal, rules, redirect = get("/%2e%2e/%2e%2e/Makefile"), get("/_redirects"), get("/old")
            connection.close()
            encodings = server.encodings
        self.assertEqual((home[0], home[3]), (200, f"<p>Home of {server.base_url}/</p>".encode()))
        self.assertEqual((logo[1], logo[3]), ("image/png", b"PNG https://greenleaf.example/"))  # binary: untouched
        self.assertEqual((traversal[0], rules[0]), (404, 404))
        self.assertEqual((redirect[0], redirect[2]), (302, "/index.html"))
        self.assertEqual(encodings, ["identity", "identity"])

    def test_unknown_mock_site_is_a_clear_error(self):
        with self.assertRaisesRegex(FileNotFoundError, "Unknown mock site 'nope'; available: \\['greenleaf-good'"):
            MockSiteServer("nope")

    def test_mock_site_module_entry_point(self):
        class InterruptedEvent:
            def wait(self):
                raise KeyboardInterrupt

        out = io.StringIO()
        with mock.patch.object(mock_sites, "threading", mock.Mock(Event=InterruptedEvent, Thread=threading.Thread)), \
                mock.patch("sys.argv", ["mock_sites", mock_sites.GOOD_SITE, "--port", "0"]), redirect_stdout(out):
            mock_sites.main()
        self.assertRegex(out.getvalue(), r"Serving greenleaf-good at http://127\.0\.0\.1:\d+/")

    def test_rebase(self):
        crawl = crawl_mock_site(mock_sites.GOOD_SITE).result
        back = crawl.rebase(PRODUCTION_BASE, "https://staging.example")
        self.assertTrue(all(p.url.startswith("https://staging.example/") for p in back.pages))
        self.assertTrue(all(u.startswith("https://staging.example/") for p in back.pages for u in p.existing_internal_links))


# ---------------------------------------------------------------------------
# Crawler features, each exercised against a small real HTTP server
# ---------------------------------------------------------------------------


class RouteServer:
    """HTTP server answering from a routes dict: path -> (status, headers, body) or callable(count) -> tuple."""

    def __init__(self, routes, delay: float = 0.0):
        self.routes, self.requests, self.delay = routes, [], delay
        self.counts = {}
        self.in_flight = self.max_in_flight = 0     # concurrent requests being answered (proves parallelism)
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _answer(self, send_body: bool):
                with outer._lock:
                    outer.requests.append((self.command, self.path))
                    outer.counts[self.path] = outer.counts.get(self.path, 0) + 1
                    outer.in_flight += 1
                    outer.max_in_flight = max(outer.max_in_flight, outer.in_flight)
                try:
                    if outer.delay:
                        time.sleep(outer.delay)
                finally:
                    with outer._lock:
                        outer.in_flight -= 1
                route = outer.routes.get(self.path, (404, {}, "<h1>Not found</h1>"))
                status, headers, body = route(outer.counts[self.path]) if callable(route) else route
                data = body.encode("utf-8") if isinstance(body, str) else body
                self.send_response(status)
                headers = {"Content-Type": "text/html; charset=utf-8", **headers}
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if send_body:
                    self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                self._answer(True)

            def do_HEAD(self):  # noqa: N802
                self._answer(False)

        class _ThreadingServer(ThreadingHTTPServer):
            request_queue_size = 64

        self.server = _ThreadingServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def page(title, *links, body=""):
    anchors = "".join(f'<p>Read more about <a href="{href}">{text}</a> in this paragraph.</p>' for href, text in links)
    return f"<html><head><title>{title}</title></head><body><h1>{title}</h1>{body}{anchors}</body></html>"


@pytest.mark.integration
class ServerTestCase(unittest.TestCase):
    def serve(self, routes, delay=0.0) -> RouteServer:
        server = RouteServer(routes, delay)
        self.addCleanup(server.close)
        return server

    def crawl(self, server, **config):
        config.setdefault("timeout", 5)
        return SitemapCrawler(server.url + "/", config=CrawlConfig(**config)).crawl()


class TestUrlNormalization(unittest.TestCase):
    def test_ports_case_fragments_and_tracking_parameters(self):
        self.assertEqual(normalize_url("HTTP://Example.COM:80"), "http://example.com/")
        self.assertEqual(normalize_url("https://example.com:443/a?utm_source=x&id=3&gclid=y#top"),
                         "https://example.com/a?id=3")
        self.assertEqual(normalize_url("https://example.com:8443/a/"), "https://example.com:8443/a/")
        self.assertEqual(normalize_url("https://x.com/a?utm_source=1", strip_params=()), "https://x.com/a?utm_source=1")

    def test_same_site(self):
        self.assertTrue(same_site("https://example.com/x", "example.com"))
        self.assertFalse(same_site("https://blog.example.com/x", "example.com"))
        self.assertTrue(same_site("https://blog.example.com/x", "www.example.com", allow_subdomains=True))
        self.assertFalse(same_site("https://notexample.com/x", "example.com", allow_subdomains=True))


class TestCrawlConfig(unittest.TestCase):
    def test_strict_config_section(self):
        self.assertEqual(CrawlConfig.from_config({}), CrawlConfig())
        config = CrawlConfig.from_config({"crawler": {"max_pages": 50, "exclude": ["^/tag/"], "delay": 0.5}})
        self.assertEqual((config.max_pages, config.exclude, config.delay), (50, ("^/tag/",), 0.5))
        for bad in ({"crawler": {"max_page": 5}}, {"crawler": {"max_pages": 0}}, {"crawler": {"exclude": "^/x"}},
                    {"crawler": {"include": ["(unclosed"]}}, {"crawler": {"concurrency": True}},
                    {"crawler": {"max_depth": -1}}, {"crawler": {"delay": -1}}, {"crawler": {"timeout": 0}},
                    {"crawler": ["max_pages", 5]}):
            with self.subTest(config=bad), self.assertRaises(ValueError):
                CrawlConfig.from_config(bad)


class TestCrawlerFeatures(ServerTestCase):
    def test_gzip_and_tracking_parameters_on_the_mock_site(self):
        crawl = crawl_mock_site(mock_sites.SCRAMBLED_SITE)
        self.assertTrue(crawl.encodings and set(crawl.encodings) == {"gzip"})
        self.assertFalse([r for r in crawl.requests if "utm_" in r])
        about = crawl.result.page(PRODUCTION_BASE + "/about/")
        self.assertEqual(about.existing_internal_links, [PRODUCTION_BASE + "/blog/tomato-watering-schedule/"])

    def test_indexability_signals(self):
        server = self.serve({
            "/": (200, {}, page("Home", ("/noindex/", "a"), ("/header-noindex/", "b"), ("/dup/", "c"))),
            "/noindex/": (200, {}, '<meta name="robots" content="NOINDEX, follow">' + page("N")),
            "/header-noindex/": (200, {"X-Robots-Tag": "noindex"}, page("H")),
            "/dup/": (200, {}, '<link rel="canonical" href="/">' + page("Dup")),
        })
        result = self.crawl(server)
        by_path = {p.url[len(server.url):]: p for p in result.pages}
        self.assertTrue(by_path["/noindex/"].noindex and by_path["/header-noindex/"].noindex)
        self.assertTrue(by_path["/dup/"].canonicalized)
        self.assertEqual([p for p, pg in by_path.items() if pg.indexable], ["/"])

    def test_transient_errors_are_retried(self):
        flaky = lambda n: (503, {"Retry-After": "0"}, "busy") if n == 1 else (200, {}, page("Home"))
        server = self.serve({"/": flaky})
        self.assertEqual(len(self.crawl(server, retries=1).pages), 1)
        self.assertEqual(server.counts["/"], 2)
        server2 = self.serve({"/": flaky})
        result = self.crawl(server2, retries=0)
        self.assertEqual((result.pages, result.statuses[server2.url + "/"]), ([], 503))

    def test_redirect_chains_loops_and_external_redirects(self):
        other = self.serve({"/": (200, {}, page("Elsewhere"))})
        server = self.serve({
            "/": (200, {}, page("Home", ("/old", "old"), ("/loop-a", "loop"), ("/away", "away"))),
            "/old": (301, {"Location": "/older"}, ""), "/older": (301, {"Location": "/new"}, ""),
            "/new": (200, {}, page("New")),
            "/loop-a": (302, {"Location": "/loop-b"}, ""), "/loop-b": (302, {"Location": "/loop-a"}, ""),
            "/away": (301, {"Location": other.url + "/"}, ""),
        })
        result = self.crawl(server)
        base = server.url
        self.assertEqual(result.redirect_chains[base + "/old"], [(base + "/old", 301), (base + "/older", 301)])
        self.assertEqual(result.redirects[base + "/old"], base + "/new")
        self.assertEqual(result.redirect_loops, [base + "/loop-a"])
        self.assertEqual(other.requests, [])  # a redirect leaving the site is recorded, not followed
        codes = {i.code for i in audit_site(result).issues}
        self.assertTrue({"redirect_chain", "redirect_loop"} <= codes)

    def test_max_depth_include_and_exclude(self):
        routes = {"/": (200, {}, page("Home", ("/a/", "a"), ("/tag/x/", "tag")))}
        routes["/a/"] = (200, {}, page("A", ("/a/b/", "b")))
        routes["/a/b/"] = (200, {}, page("B", ("/a/b/c/", "c")))
        routes["/a/b/c/"] = (200, {}, page("C"))
        routes["/tag/x/"] = (200, {}, page("Tag"))
        server = self.serve(routes)
        paths = lambda result: sorted(p.url[len(server.url):] for p in result.pages)
        self.assertEqual(paths(self.crawl(server, max_depth=1)), ["/", "/a/", "/tag/x/"])
        self.assertEqual(paths(self.crawl(server, exclude=("^/tag/",))), ["/", "/a/", "/a/b/", "/a/b/c/"])
        limited = self.crawl(server, include=("^/$", "^/a/$"))
        self.assertEqual(paths(limited), ["/", "/a/"])
        self.assertIn(server.url + "/tag/x/", limited.excluded)
        depths = {p.url[len(server.url):]: p.depth for p in self.crawl(server).pages}
        self.assertEqual(depths, {"/": 0, "/a/": 1, "/tag/x/": 1, "/a/b/": 2, "/a/b/c/": 3})

    def test_non_html_size_limit_and_charset(self):
        latin = '<meta charset="iso-8859-1"><title>Ação</title><h1>Ação</h1>'.encode("latin-1")
        server = self.serve({
            "/": (200, {}, page("Home", ("/file.pdf", "pdf"), ("/big/", "big"), ("/latin/", "latin"))),
            "/file.pdf": (200, {"Content-Type": "application/pdf"}, b"%PDF" + b"0" * 200_000),
            "/big/": (200, {}, "<title>Big</title>" + "<p>" + "x" * 4000 + "</p>"),
            "/latin/": (200, {"Content-Type": "text/html"}, latin),
        })
        result = self.crawl(server, max_page_bytes=2048)
        self.assertEqual(result.content_types[server.url + "/file.pdf"], "application/pdf")
        self.assertIsNone(result.page(server.url + "/file.pdf"))
        self.assertLess(result.bytes_downloaded, 20_000)  # the PDF body was never downloaded
        self.assertEqual(result.page(server.url + "/latin/").title, "Ação")
        self.assertEqual(result.page(server.url + "/big/").content_bytes, 2048)

    def test_concurrency_is_parallel_and_deterministic(self):
        # Parallelism is asserted on the server side (requests in flight at the same time),
        # not with wall-clock ratios that flake on a loaded machine or under coverage tracing.
        routes = {"/": (200, {}, page("Home", *[(f"/p{i}/", f"page {i}") for i in range(8)]))}
        routes.update({f"/p{i}/": (200, {}, page(f"P{i}", ("/", "home"))) for i in range(8)})
        serial_server, parallel_server = self.serve(routes, delay=0.05), self.serve(routes, delay=0.05)
        serial = self.crawl(serial_server, concurrency=1, respect_robots=False)
        parallel = self.crawl(parallel_server, concurrency=8, respect_robots=False)
        self.assertEqual(serial_server.max_in_flight, 1)
        self.assertGreater(parallel_server.max_in_flight, 1)
        def shape(result, base):   # page order and links, independent of the server's port
            strip = lambda url: url[len(base):]
            return [(strip(p.url), [strip(u) for u in p.existing_internal_links]) for p in result.pages]

        self.assertEqual(shape(parallel, parallel_server.url), shape(serial, serial_server.url))
        self.assertEqual(len(serial.pages), 9)

    def test_politeness_delay_and_robots_crawl_delay(self):
        limiter = RateLimiter(0.05)
        started = time.perf_counter()
        for _ in range(5):
            limiter.wait()
        self.assertGreaterEqual(time.perf_counter() - started, 0.19)
        server = self.serve({"/": (200, {}, page("Home")),
                             "/robots.txt": (200, {"Content-Type": "text/plain"}, "User-agent: *\nCrawl-delay: 1\n")})
        result = self.crawl(server)
        self.assertEqual(result.crawl_delay, 1.0)
        self.assertGreaterEqual(result.duration_seconds, 1.0)

    def test_external_links_are_only_checked_on_request(self):
        external = self.serve({"/ok/": (200, {}, page("OK"))})
        server = self.serve({"/": (200, {}, page("Home", (external.url + "/ok/", "ok"), (external.url + "/gone/", "gone")))})
        self.crawl(server)
        self.assertEqual(external.requests, [])
        result = self.crawl(server, check_external=True)
        self.assertEqual(result.external_statuses, {external.url + "/ok/": 200, external.url + "/gone/": 404})
        broken = [i for i in audit_site(result).issues if i.code == "broken_external_link"]
        self.assertEqual([i.url for i in broken], [external.url + "/gone/"])
        self.assertTrue(all(method == "HEAD" for method, _ in external.requests))

    def test_gzipped_sitemap(self):
        xml = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{base}/hidden/</loc></url></urlset>'
        server = self.serve({"/": (200, {}, page("Home")), "/hidden/": (200, {}, page("Hidden"))})
        server.routes["/robots.txt"] = (200, {"Content-Type": "text/plain"}, f"Sitemap: {server.url}/sitemap.xml.gz\n")
        server.routes["/sitemap.xml.gz"] = (200, {"Content-Type": "application/gzip"},
                                            gzip.compress(xml.format(base=server.url).encode()))
        result = self.crawl(server)
        self.assertEqual(result.sitemap_urls, [server.url + "/hidden/"])
        self.assertIsNone(result.page(server.url + "/hidden/").depth)  # only reachable through the sitemap

    def test_save_and_load_round_trip(self):
        crawl = crawl_mock_site(mock_sites.SCRAMBLED_SITE).result
        with tempfile.TemporaryDirectory() as tmp:
            loaded = CrawlResult.load(crawl.save(Path(tmp, "crawl.json")))
        self.assertEqual(loaded, crawl)
        self.assertEqual(audit_site(loaded).issue_keys(), audit_site(crawl).issue_keys())

    def test_redirect_limit_stops_long_chains(self):
        server = self.serve({f"/r{i}": (301, {"Location": f"/r{i + 1}"}, "") for i in range(6)})
        result = HttpFetcher(timeout=5, retries=0, max_redirects=2).fetch(server.url + "/r0")
        self.assertEqual((result.status, result.error), (301, "more than 2 redirects"))
        self.assertEqual([hop for hop, _ in result.redirect_chain], [server.url + f"/r{i}" for i in range(3)])
        self.assertEqual(len(server.requests), 3)  # stopped: /r3 is never requested

    def test_fetcher_head_falls_back_to_get(self):
        server = self.serve({"/x": lambda n: (405, {}, "") if server.requests[-1][0] == "HEAD" else (200, {}, "ok")})
        self.assertEqual(HttpFetcher(timeout=5, retries=0).head(server.url + "/x").status, 200)
        self.assertEqual([m for m, _ in server.requests], ["HEAD", "GET"])


@pytest.mark.integration
class TestCrawlCommand(unittest.TestCase):
    def test_crawl_save_and_audit_from_saved_crawl(self):
        with MockSiteServer(mock_sites.SCRAMBLED_SITE) as server, tempfile.TemporaryDirectory() as tmp:
            saved = Path(tmp, "crawl.json")
            out = io.StringIO()
            with redirect_stdout(out):
                cli.main(["crawl", "--url", server.base_url + "/", "--save-crawl", str(saved), "--issues", "3"])
            self.assertIn("Site health: 0/10 healthy pages", out.getvalue())
            self.assertNotIn("Classifier calls", out.getvalue())  # crawl makes no classifier calls
            self.assertTrue(saved.is_file())
            out = io.StringIO()
            with redirect_stdout(out):
                cli.main(["audit", "--from-crawl", str(saved), "--config", "config/sites/greenleaf.yaml"])
            self.assertIn("Loaded saved crawl", out.getvalue())
            self.assertIn("Links proposed             : 16", out.getvalue())


if __name__ == "__main__":
    unittest.main()
