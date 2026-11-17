"""
Saved mock-site crawls (tests/fixtures/*.crawl.json) used by unit tests.

* unit:        the saved crawls reproduce the mock sites' ground truth offline
               (audit issues, link proposals), so unit tests can rely on them;
* integration: the saved crawls equal a fresh HTTP crawl (otherwise: `make fixtures`).
"""

import unittest
import warnings

import pytest

from src.benchmarks import mock_sites, run_benchmark
from src.benchmarks.mock_sites import EXPECTED_ISSUES, PRODUCTION_BASE
from src.workflows.site_audit import audit_site
from tests.fixtures.crawls import SITES, crawl_path, load_crawl, normalized, offline_benchmark


class TestSavedCrawls(unittest.TestCase):
    def test_every_mock_site_has_a_saved_crawl(self):
        self.assertEqual(set(SITES), {mock_sites.GOOD_SITE, mock_sites.SCRAMBLED_SITE})
        for site in SITES:
            self.assertTrue(crawl_path(site).is_file(), f"{crawl_path(site)} missing: run `make fixtures`")

    def test_saved_crawls_are_normalized_and_rebased(self):
        for site in SITES:
            with self.subTest(site=site):
                crawl = load_crawl(site)
                self.assertEqual(crawl, normalized(crawl))
                self.assertTrue(all(page.url.startswith(PRODUCTION_BASE + "/") for page in crawl.pages))

    def test_load_returns_independent_copies(self):
        first = load_crawl(mock_sites.SCRAMBLED_SITE)
        first.pages.clear()
        self.assertTrue(load_crawl(mock_sites.SCRAMBLED_SITE).pages)

    def test_saved_crawls_audit_to_the_ground_truth(self):
        for site, expected in EXPECTED_ISSUES.items():
            with self.subTest(site=site):
                found = {(code, url[len(PRODUCTION_BASE):]) for code, url in audit_site(load_crawl(site)).issue_keys()}
                self.assertEqual(found, expected)

    def test_offline_benchmark_finds_the_expected_links(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            run = run_benchmark(offline_benchmark(mock_sites.SCRAMBLED_SITE))
        self.assertEqual(run.approved_links, run.site.expected_links - set(run.site.known_gaps))
        self.assertEqual(len(run.approved_links), len(mock_sites.SCRAMBLED_EXPECTED_PROPOSALS))
        self.assertEqual(run.crawl_requests, [])  # no HTTP involved


@pytest.mark.integration
class TestSavedCrawlsAreCurrent(unittest.TestCase):
    def test_saved_crawls_match_a_live_crawl(self):
        for site in SITES:
            with self.subTest(site=site):
                live = normalized(mock_sites.crawl_mock_site(site).result)
                self.assertEqual(load_crawl(site), live,
                                 f"{crawl_path(site).name} is stale (mock site or crawler changed): run `make fixtures`")


if __name__ == "__main__":
    unittest.main()
