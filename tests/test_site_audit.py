"""
Site audit on real crawls of the mock sites: the good site must be clean and
the scrambled site must show exactly the problems planted in it.
"""

import unittest

import pytest

from src.benchmarks import mock_sites
from src.benchmarks.mock_sites import EXPECTED_ISSUES, PRODUCTION_BASE, crawl_mock_site
from src.connectors.sitemap_crawler import CrawlResult, parse_html_page
from src.workflows.site_audit import ERROR, ISSUE_SEVERITY, NOTICE, WARNING, audit_site


@pytest.mark.integration
class TestMockSiteAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.crawls = {site: crawl_mock_site(site).result for site in EXPECTED_ISSUES}
        cls.audits = {site: audit_site(crawl) for site, crawl in cls.crawls.items()}

    def test_issues_match_the_ground_truth_exactly(self):
        for site, expected in EXPECTED_ISSUES.items():
            with self.subTest(site=site):
                found = {(code, url[len(PRODUCTION_BASE):]) for code, url in self.audits[site].issue_keys()}
                self.assertEqual(found, expected)

    def test_good_site_is_fully_healthy(self):
        audit = self.audits[mock_sites.GOOD_SITE]
        self.assertEqual((audit.health, audit.by_severity), (1.0, {ERROR: 0, WARNING: 0, NOTICE: 0}))
        self.assertTrue(all(depth is not None and depth <= 2 for depth in audit.click_depths.values()))

    def test_scrambled_site_health_and_severities(self):
        audit = self.audits[mock_sites.SCRAMBLED_SITE]
        self.assertEqual(audit.by_severity, {ERROR: 4, WARNING: 16, NOTICE: 6})
        self.assertEqual(sorted(audit.non_indexable), [PRODUCTION_BASE + "/blog/hot-composting/print/",
                                                       PRODUCTION_BASE + "/blog/old-news/"])
        self.assertEqual(audit.healthy_pages, [])
        self.assertEqual(audit.click_depths[PRODUCTION_BASE + "/guides/vegetable-gardening/"], 4)
        self.assertIsNone(audit.click_depths[PRODUCTION_BASE + "/blog/hot-composting/"])
        broken = next(i for i in audit.issues if i.code == "broken_internal_link")
        self.assertEqual(broken.affected_pages, {PRODUCTION_BASE + "/blog/raised-bed-soil/"})
        redirect = next(i for i in audit.issues if i.code == "redirected_internal_link")
        self.assertEqual(len(redirect.affected_pages), 11)  # footer link on every page with a footer

    def test_every_issue_code_has_a_severity(self):
        for audit in self.audits.values():
            self.assertTrue(all(issue.code in ISSUE_SEVERITY for issue in audit.issues))


class TestAuditRules(unittest.TestCase):
    def _crawl(self, pages):
        parsed = [parse_html_page(url, html) for url, html in pages.items()]
        return CrawlResult(start_url=parsed[0].url, pages=parsed, sitemap_urls=[], sitemap_found=False,
                           statuses={p.url: 200 for p in parsed}, redirects={}, robots_blocked=[])

    def test_click_depth_limit_is_configurable(self):
        chain = {f"https://x.example/{i}/": f"<h1>P{i}</h1><title>P{i}</title><a href='/{i + 1}/'>next page</a>"
                 for i in range(5)}
        chain["https://x.example/"] = "<title>Home</title><h1>Home</h1><a href='/0/'>first page</a>"
        pages = dict(reversed(list(chain.items())))
        deep = lambda limit: {i.url for i in audit_site(self._crawl(pages), limit).issues if i.code == "deep_page"}
        self.assertEqual(deep(3), {"https://x.example/3/", "https://x.example/4/"})
        self.assertEqual(deep(5), set())

    def test_generic_anchors_in_english_and_portuguese(self):
        crawl = self._crawl({
            "https://x.example/": "<title>Home</title><h1>Home</h1>"
                                  "<p>For details <a href='/a/'>Click here!</a> or <a href='/b/'>saiba mais</a>.</p>"
                                  "<p><a href='/c/'>compost bin troubleshooting</a></p>",
            "https://x.example/a/": "<title>A</title><h1>A</h1>",
            "https://x.example/b/": "<title>B</title><h1>B</h1>",
            "https://x.example/c/": "<title>C</title><h1>C</h1>",
        })
        generic = [i.detail for i in audit_site(crawl).issues if i.code == "generic_anchor"]
        self.assertEqual(len(generic), 2)
        self.assertTrue(any("Click here!" in d for d in generic) and any("saiba mais" in d for d in generic))

    def test_canonical_to_a_broken_url_is_an_error(self):
        crawl = self._crawl({
            "https://x.example/": "<title>Home</title><h1>Home</h1><p><a href='/dup/'>duplicate page</a></p>",
            "https://x.example/dup/": "<title>Dup</title><h1>Dup</h1><link rel='canonical' href='/gone/'>",
        })
        crawl.statuses["https://x.example/gone/"] = 404
        issues = {(i.code, i.url): i for i in audit_site(crawl).issues}
        broken = issues[("canonical_broken", "https://x.example/dup/")]
        self.assertEqual(broken.severity, ERROR)
        self.assertIn("answers HTTP 404", broken.detail)
        self.assertEqual(issues[("canonicalized_page", "https://x.example/dup/")].severity, NOTICE)
        # A canonicalized duplicate is not indexable: no on-page checks for it.
        self.assertNotIn(("missing_meta_description", "https://x.example/dup/"), issues)

    def test_canonical_to_a_working_url_is_only_a_notice(self):
        crawl = self._crawl({
            "https://x.example/": "<title>Home</title><h1>Home</h1><p><a href='/dup/'>duplicate page</a></p>",
            "https://x.example/dup/": "<title>Dup</title><h1>Dup</h1><link rel='canonical' href='/'>",
        })
        codes = {i.code for i in audit_site(crawl).issues if i.url == "https://x.example/dup/"}
        self.assertEqual(codes, {"canonicalized_page"})

    def test_slow_pages_use_the_configured_threshold(self):
        crawl = self._crawl({"https://x.example/": "<title>Home</title><h1>Home</h1>"})
        crawl.pages[0].response_ms = 2500.0
        slow = [i for i in audit_site(crawl).issues if i.code == "slow_page"]
        self.assertEqual([(i.severity, i.detail) for i in slow], [(NOTICE, "answered in 2500 ms (max 2000)")])
        self.assertFalse([i for i in audit_site(crawl, slow_page_ms=3000).issues if i.code == "slow_page"])
        # Notices never make a page unhealthy.
        self.assertEqual(audit_site(crawl).unhealthy_pages, set())

    def test_uncrawled_start_page_leaves_every_depth_unknown(self):
        crawl = self._crawl({
            "https://x.example/a/": "<title>A</title><h1>A</h1><p><a href='/b/'>page b</a></p>",
            "https://x.example/b/": "<title>B</title><h1>B</h1><p><a href='/a/'>page a</a></p>",
        })
        crawl.start_url = "https://x.example/"   # answered with an error: not among the pages
        audit = audit_site(crawl)
        self.assertEqual(audit.click_depths, {"https://x.example/a/": None, "https://x.example/b/": None})
        self.assertEqual({i.url for i in audit.issues if i.code == "unreachable_page"},
                         {"https://x.example/a/", "https://x.example/b/"})


if __name__ == "__main__":
    unittest.main()
